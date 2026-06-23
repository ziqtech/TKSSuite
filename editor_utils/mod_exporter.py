"""
mod_exporter — MOD 导出公共模块
=================================
为所有编辑器提供统一的 .tksmod 导出功能：
  - diff_records():        定长记录字段级差异算法
  - diff_text_defines():   TKD DEFINE 块差异算法
  - diff_text_entries():   TKT 文本 ID 级差异算法
  - compute_crc32():       文件 CRC32 校验
  - pack_tksmod():         ZIP 打包为 .tksmod
  - ModMetadataDialog:     MOD 元数据输入对话框 (PySide6)

.tksmod 格式: ZIP 压缩包，内含 mod.json + data/*.json + resources/*
"""
import os
import json
import zlib
import zipfile
import copy
from datetime import datetime, timezone, timedelta
from typing import Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QPushButton, QMessageBox,
)
from PySide6.QtCore import Qt


# ═══════════════════════════════════════════════════════════════
# 差异算法
# ═══════════════════════════════════════════════════════════════

def diff_records(original: list[list[int]], current: list[list[int]],
                 field_count: int, original_count: int | None = None
                 ) -> dict:
    """对比定长记录数组，生成字段级差异。

    Args:
        original: 原始记录列表，每条为 field values list
        current:  当前记录列表
        field_count: 每条记录的字段数
        original_count: 原始文件的记录数（默认=len(original)）

    Returns:
        {"modified": [...], "appended": [...]}
    """
    if original_count is None:
        original_count = len(original)

    modified = []
    appended = []

    # 比对原有记录
    for i in range(min(len(original), len(current), original_count)):
        orig = original[i]
        cur = current[i]
        field_diffs = {}
        for fi in range(min(field_count, len(orig), len(cur))):
            if orig[fi] != cur[fi]:
                field_diffs[f"f{fi}"] = cur[fi]
        if field_diffs:
            modified.append({"index": i, "fields": field_diffs})

    # 追加新记录（超出原始范围的部分）
    for i in range(original_count, len(current)):
        cur = current[i]
        # 只记录非零字段以节省空间
        field_diffs = {}
        for fi in range(min(field_count, len(cur))):
            if cur[fi] != 0:
                field_diffs[f"f{fi}"] = cur[fi]
        if field_diffs:
            appended.append({"index": i, "fields": field_diffs})

    return {"modified": modified, "appended": appended}


def diff_text_defines(original_defines: dict[str, str],
                      current_defines: dict[str, str]) -> dict:
    """对比 TKD.dat DEFINE 块，生成块级差异。

    Args:
        original_defines: {define_id_str: full_text, ...}
        current_defines:  {define_id_str: full_text, ...}

    Returns:
        {"modified": {id: text}, "appended": [text, ...], "deleted": [id, ...]}
    """
    modified = {}
    appended = []
    deleted = []

    for did, content in current_defines.items():
        if did not in original_defines:
            appended.append(content)
        elif content != original_defines[did]:
            modified[did] = content

    for did in original_defines:
        if did not in current_defines:
            deleted.append(did)

    return {"modified": modified, "appended": appended, "deleted": deleted}


def diff_text_entries(original_entries: dict[int, str],
                      current_entries: dict[int, str]) -> dict:
    """对比 TKT.dat 文本条目，生成 ID 级差异。

    Args:
        original_entries: {text_id: text, ...}
        current_entries:  {text_id: text, ...}

    Returns:
        {"modified": {id_str: text}, "appended": {id_str: text}, "deleted": [id_str, ...]}
    """
    modified = {}
    appended = {}
    deleted = []

    for tid, text in current_entries.items():
        sid = str(tid)
        if tid not in original_entries:
            appended[sid] = text
        elif text != original_entries[tid]:
            modified[sid] = text

    for tid in original_entries:
        if tid not in current_entries:
            deleted.append(str(tid))

    return {"modified": modified, "appended": appended, "deleted": deleted}


# ═══════════════════════════════════════════════════════════════
# CRC32 计算
# ═══════════════════════════════════════════════════════════════

def compute_crc32(file_path: str) -> str:
    """计算文件的 CRC32 校验值，返回 '0xABCD1234' 格式字符串。"""
    if not os.path.isfile(file_path):
        return "0x00000000"
    crc = 0
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return f"0x{crc & 0xFFFFFFFF:08X}"


def compute_crc32_bytes(data: bytes) -> str:
    """计算字节数据的 CRC32 校验值。"""
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return f"0x{crc:08X}"


# ═══════════════════════════════════════════════════════════════
# mod.json 生成
# ═══════════════════════════════════════════════════════════════

def generate_mod_json(metadata: dict, components: list[dict],
                      resources: list[dict] | None = None) -> dict:
    """生成 mod.json 内容。

    Args:
        metadata: 包含 id, name, version, author, description, type, mode,
                  dependencies, conflicts, load_order, id_ranges, warpc_expand
        components: [{"file": "data/X.json", "target": "X.dat"}, ...]
        resources: [{"file": "resources/X.JVG", "target": "X.JVG"}, ...]

    Returns:
        完整的 mod.json 字典
    """
    now = datetime.now(timezone(timedelta(hours=8)))

    mod_json = {
        "format": "TKSMOD",
        "format_version": 1,
        "id": metadata.get("id", "unnamed_mod"),
        "name": metadata.get("name", "Unnamed MOD"),
        "version": metadata.get("version", "1.0.0"),
        "author": metadata.get("author", ""),
        "description": metadata.get("description", ""),
        "created": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "game_version": metadata.get("game_version", "1.0"),

        "type": metadata.get("type", "data"),
        "mode": metadata.get("mode", "mixed"),

        "dependencies": metadata.get("dependencies", []),
        "conflicts": metadata.get("conflicts", []),
        "load_order": metadata.get("load_order", 100),

        "id_ranges": metadata.get("id_ranges", {}),
        "warpc_expand": metadata.get("warpc_expand", 0),

        "components": components,
        "resources": resources or [],
    }
    return mod_json


# ═══════════════════════════════════════════════════════════════
# .tksmod 打包
# ═══════════════════════════════════════════════════════════════

def pack_tksmod(output_path: str, mod_json: dict,
                data_files: dict[str, Any],
                resource_files: dict[str, str] | None = None) -> bool:
    """将 MOD 数据打包为 .tksmod (ZIP) 文件。

    Args:
        output_path: 输出 .tksmod 文件路径
        mod_json: mod.json 字典内容
        data_files: {"data/WarPC.dat.json": dict_content, ...}
                    value 为字典，将被 json.dumps 序列化
        resource_files: {"resources/Cha.JVG": "/abs/path/to/file", ...}
                        value 为源文件的绝对路径

    Returns:
        True 成功
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 写入 mod.json
        mod_json_str = json.dumps(mod_json, ensure_ascii=False, indent=2)
        zf.writestr("mod.json", mod_json_str)

        # 写入数据差异文件
        for internal_path, content_dict in data_files.items():
            json_str = json.dumps(content_dict, ensure_ascii=False, indent=2)
            zf.writestr(internal_path, json_str)

        # 写入资源文件
        if resource_files:
            for internal_path, source_path in resource_files.items():
                if os.path.isfile(source_path):
                    zf.write(source_path, internal_path)

    return True


# ═══════════════════════════════════════════════════════════════
# .tksmod 解包/读取
# ═══════════════════════════════════════════════════════════════

def read_tksmod(mod_path: str) -> tuple[dict | None, dict[str, Any]]:
    """读取 .tksmod 文件。

    Returns:
        (mod_json, data_files_dict)
        mod_json: mod.json 解析后的字典
        data_files_dict: {"data/X.dat.json": parsed_dict, ...}
    """
    if not os.path.isfile(mod_path):
        return None, {}

    try:
        with zipfile.ZipFile(mod_path, 'r') as zf:
            # 读取 mod.json
            mod_json_str = zf.read("mod.json").decode('utf-8')
            mod_json = json.loads(mod_json_str)

            # 读取所有 data/ 下的 JSON 文件
            data_files = {}
            for name in zf.namelist():
                if name.startswith("data/") and name.endswith(".json"):
                    content = zf.read(name).decode('utf-8')
                    data_files[name] = json.loads(content)

            return mod_json, data_files
    except Exception:
        return None, {}


# ═══════════════════════════════════════════════════════════════
# 数据差异文件构建辅助
# ═══════════════════════════════════════════════════════════════

def build_data_diff_json(target: str, record_size: int, field_type: str,
                         field_count: int, original_count: int,
                         original_crc32: str, diff_result: dict) -> dict:
    """构建 A 类（定长记录）数据差异 JSON 结构。"""
    return {
        "target": target,
        "record_size": record_size,
        "field_type": field_type,
        "field_count": field_count,
        "original_count": original_count,
        "original_crc32": original_crc32,
        "modified": diff_result.get("modified", []),
        "appended": diff_result.get("appended", []),
    }


def build_text_diff_json(target: str, original_crc32: str,
                         diff_result: dict) -> dict:
    """构建 B/C 类（文本）数据差异 JSON 结构。"""
    return {
        "target": target,
        "original_crc32": original_crc32,
        "modified": diff_result.get("modified", {}),
        "appended": diff_result.get("appended", [] if isinstance(diff_result.get("appended"), list) else {}),
        "deleted": diff_result.get("deleted", []),
    }


# ═══════════════════════════════════════════════════════════════
# MOD 元数据对话框
# ═══════════════════════════════════════════════════════════════

class ModMetadataDialog(QDialog):
    """MOD 元数据输入对话框，用于首次导出时收集信息。"""

    def __init__(self, parent=None, defaults: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("导出为 MOD (.tksmod)")
        self.resize(500, 420)
        self.metadata = {}
        defaults = defaults or {}

        layout = QVBoxLayout(self)

        # 表单
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("MOD ID *:"), row, 0)
        self.edit_id = QLineEdit(defaults.get("id", ""))
        self.edit_id.setPlaceholderText("唯一标识符, 如 my_balance_mod")
        grid.addWidget(self.edit_id, row, 1)

        row += 1
        grid.addWidget(QLabel("名称 *:"), row, 0)
        self.edit_name = QLineEdit(defaults.get("name", ""))
        self.edit_name.setPlaceholderText("MOD 显示名称")
        grid.addWidget(self.edit_name, row, 1)

        row += 1
        grid.addWidget(QLabel("版本:"), row, 0)
        self.edit_version = QLineEdit(defaults.get("version", "1.0.0"))
        grid.addWidget(self.edit_version, row, 1)

        row += 1
        grid.addWidget(QLabel("作者:"), row, 0)
        self.edit_author = QLineEdit(defaults.get("author", ""))
        grid.addWidget(self.edit_author, row, 1)

        row += 1
        grid.addWidget(QLabel("描述:"), row, 0)
        self.edit_desc = QTextEdit()
        self.edit_desc.setPlainText(defaults.get("description", ""))
        self.edit_desc.setMaximumHeight(80)
        grid.addWidget(self.edit_desc, row, 1)

        row += 1
        grid.addWidget(QLabel("类型:"), row, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["data", "story", "visual", "mixed"])
        idx = self.combo_type.findText(defaults.get("type", "data"))
        if idx >= 0:
            self.combo_type.setCurrentIndex(idx)
        grid.addWidget(self.combo_type, row, 1)

        row += 1
        grid.addWidget(QLabel("模式:"), row, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["diff", "append", "mixed"])
        idx = self.combo_mode.findText(defaults.get("mode", "mixed"))
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        grid.addWidget(self.combo_mode, row, 1)

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        self.spin_order.setValue(defaults.get("load_order", 100))
        grid.addWidget(self.spin_order, row, 1)

        layout.addLayout(grid)
        layout.addSpacing(12)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("导出")
        btn_ok.clicked.connect(self._accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _accept(self):
        mod_id = self.edit_id.text().strip()
        mod_name = self.edit_name.text().strip()
        if not mod_id:
            QMessageBox.warning(self, "必填", "请输入 MOD ID")
            return
        if not mod_name:
            QMessageBox.warning(self, "必填", "请输入 MOD 名称")
            return

        self.metadata = {
            "id": mod_id,
            "name": mod_name,
            "version": self.edit_version.text().strip() or "1.0.0",
            "author": self.edit_author.text().strip(),
            "description": self.edit_desc.toPlainText().strip(),
            "type": self.combo_type.currentText(),
            "mode": self.combo_mode.currentText(),
            "load_order": self.spin_order.value(),
        }
        self.accept()

    def get_metadata(self) -> dict:
        return self.metadata
