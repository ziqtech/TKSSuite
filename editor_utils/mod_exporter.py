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


# ═══════════════════════════════════════════════════════════════
# 参考目录选择 + 原始数据加载辅助
# ═══════════════════════════════════════════════════════════════

def ask_reference_directory(parent, title="选择原始游戏目录 (作为 MOD 差异参考)") -> str | None:
    """弹出目录选择对话框，让用户选择原始/未修改的游戏目录作为 diff 参考基准。

    Returns:
        目录路径，或 None（用户取消）
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    d = QFileDialog.getExistingDirectory(parent, title)
    if not d:
        return None
    return d


def load_reference_dat_fields(ref_dir: str, dat_name: str, rec_size: int,
                              field_count: int, field_fmt: str = 'h',
                              use_lzss: bool = True) -> list[list[int]] | None:
    """从参考目录加载 DAT 文件的全部记录字段（用于 diff 比较）。

    Args:
        ref_dir: 参考游戏目录
        dat_name: 文件名 (如 "WarPC.dat")
        rec_size: 每条记录字节数
        field_count: 每条记录字段数
        field_fmt: struct 格式字符 ('h'=int16, 'H'=uint16, 'i'=int32)
        use_lzss: 是否需要 LZSS 解压

    Returns:
        [[field0, field1, ...], ...] 或 None (文件不存在)
    """
    import struct as _struct
    fp = os.path.join(ref_dir, dat_name)
    if not os.path.isfile(fp):
        return None

    with open(fp, 'rb') as f:
        raw = f.read()

    if use_lzss:
        from .lzss import lzss_decompress_dat
        dec = lzss_decompress_dat(raw)
    else:
        dec = raw

    count = len(dec) // rec_size
    fmt = '<' + field_fmt * field_count
    records = []
    for i in range(count):
        off = i * rec_size
        if off + rec_size > len(dec):
            break
        vals = _struct.unpack_from(fmt, dec, off)
        records.append(list(vals))
    return records


def load_reference_tkt_entries(ref_dir: str) -> dict[int, str] | None:
    """从参考目录加载 TKT.dat 的全部文本条目。

    使用 load_tkt_full 进行完整解码（含控制标签），确保与编辑器内部表示一致，
    避免因解码方式不同导致 diff 误判。

    Returns:
        {text_id: text_content, ...} 或 None (文件不存在)
    """
    fp = os.path.join(ref_dir, "TKT.dat")
    if not os.path.isfile(fp):
        return None
    from .tkt_loader import load_tkt_full
    entries = load_tkt_full(fp)
    return {e['id']: e['text'] for e in entries}


# ═══════════════════════════════════════════════════════════════
# 块级增量: JVG / GRP 二进制资源
# ═══════════════════════════════════════════════════════════════

import base64


def diff_binary_blocks(original_blocks: list[bytes], current_blocks: list[bytes]
                       ) -> dict:
    """对比二进制块列表，返回修改/新增的块索引及其 base64 编码数据。

    用于 JVG (@JVM块) 和 GRP (区段) 的增量导出。
    每个块作为整体单元比较——如果内容不同则整块替换。

    Args:
        original_blocks: 原始文件中各块的原始字节
        current_blocks: 当前编辑后各块的原始字节

    Returns:
        {
          "modified": [{"index": i, "data_b64": "..."}, ...],
          "appended": [{"index": i, "data_b64": "..."}, ...],
          "deleted_indices": [i, ...]
        }
    """
    modified = []
    appended = []
    deleted_indices = []

    # 比对已有块
    for i in range(min(len(original_blocks), len(current_blocks))):
        if original_blocks[i] != current_blocks[i]:
            modified.append({
                "index": i,
                "data_b64": base64.b64encode(current_blocks[i]).decode('ascii'),
            })

    # 新增块
    for i in range(len(original_blocks), len(current_blocks)):
        appended.append({
            "index": i,
            "data_b64": base64.b64encode(current_blocks[i]).decode('ascii'),
        })

    # 删除块（当前比原始少）
    for i in range(len(current_blocks), len(original_blocks)):
        deleted_indices.append(i)

    return {"modified": modified, "appended": appended, "deleted_indices": deleted_indices}


def build_block_diff_json(target: str, block_type: str, original_count: int,
                          original_crc32: str, diff_result: dict) -> dict:
    """构建块级增量 JSON 结构。

    Args:
        target: 目标文件名 (如 "Cha.JVG")
        block_type: "jvm_block" | "grp_section"
        original_count: 原始块/段数量
        original_crc32: 原始文件 CRC32
        diff_result: diff_binary_blocks() 返回值
    """
    return {
        "target": target,
        "patch_type": "block_diff",
        "block_type": block_type,
        "original_count": original_count,
        "original_crc32": original_crc32,
        "modified": diff_result.get("modified", []),
        "appended": diff_result.get("appended", []),
        "deleted_indices": diff_result.get("deleted_indices", []),
    }


def load_jvg_raw_blocks(filepath: str) -> list[bytes] | None:
    """加载 JVG 文件中每个 @JVM 块的原始字节数据（含块头）。

    Returns:
        [block0_bytes, block1_bytes, ...] 或 None
    """
    import struct as _struct
    if not os.path.isfile(filepath):
        return None
    with open(filepath, 'rb') as f:
        data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG':
        return None

    block_count = _struct.unpack_from('<I', data, 8)[0]
    blocks = []
    off = 32  # 跳过 @JVG 文件头

    for _ in range(block_count):
        if off + 32 > len(data) or data[off:off+4] != b'@JVM':
            break
        sprite_count = _struct.unpack_from('<I', data, off + 4)[0]
        data_size = _struct.unpack_from('<I', data, off + 12)[0]
        # 块总大小 = 块头(32B) + 偏移表((sprite_count+1)*4) + 调色板(512B) + 数据(data_size)
        block_size = 32 + (sprite_count + 1) * 4 + 512 + data_size
        block_bytes = data[off:off + block_size]
        blocks.append(block_bytes)
        off += block_size

    return blocks


def load_grp_raw_sections(filepath: str, idx_path: str | None = None
                          ) -> list[bytes] | None:
    """加载 GRP 文件中每个区段的原始字节数据。

    Returns:
        [section0_bytes, section1_bytes, ...] 或 None
    """
    import struct as _struct
    if not os.path.isfile(filepath):
        return None

    with open(filepath, 'rb') as f:
        data = f.read()

    # 尝试找 IDX 文件
    if idx_path is None:
        from pathlib import Path
        for ext in ['.IDX', '.idx']:
            candidate = str(Path(filepath).with_suffix(ext))
            if os.path.exists(candidate):
                idx_path = candidate
                break

    if not idx_path or not os.path.isfile(idx_path):
        return None

    with open(idx_path, 'rb') as f:
        idx_data = f.read()

    if len(idx_data) < 8 or len(idx_data) % 4 != 0:
        return None

    offsets = [_struct.unpack_from('<I', idx_data, i)[0]
               for i in range(0, len(idx_data), 4)]

    sections = []
    for i in range(len(offsets) - 1):
        start = offsets[i]
        end = offsets[i + 1]
        if start <= end <= len(data):
            sections.append(data[start:end])
        else:
            sections.append(b'')

    return sections


# ═══════════════════════════════════════════════════════════════
# MOD 导入 — 核心函数
# ═══════════════════════════════════════════════════════════════

def import_tksmod_records(mod_path: str, ref_dir: str, target_name: str,
                          rec_size: int, field_count: int,
                          field_fmt: str = 'h', use_lzss: bool = True
                          ) -> tuple[dict | None, list[list[int]] | None]:
    """从 .tksmod 导入定长记录类数据 (WarPC/Item/Skill/Kon/Shop)。

    流程: 加载原始数据 → 应用 diff → 返回完整记录数组

    Args:
        mod_path: .tksmod 文件路径
        ref_dir: 原始游戏目录 (基底数据)
        target_name: 目标文件名 (如 "WarPC.dat")
        rec_size: 每条记录字节数
        field_count: 每条记录字段数
        field_fmt: struct 格式字符 ('h'=int16, 'H'=uint16, 'i'=int32)
        use_lzss: 是否需要 LZSS 解压

    Returns:
        (metadata, records)
        metadata: mod.json 解析后的元数据字典
        records: [[field0, field1, ...], ...] 完整记录数组 (已应用差异)
        如果失败返回 (None, None)
    """
    # 1. 解析 .tksmod
    mod_json, data_files = read_tksmod(mod_path)
    if mod_json is None:
        return None, None

    # 2. 找到对应 target 的差异数据
    diff_data = _find_component_data(mod_json, data_files, target_name)
    if diff_data is None:
        return mod_json, None  # MOD 中不包含此 target 的数据

    # 3. 加载原始数据
    ref_records = load_reference_dat_fields(
        ref_dir, target_name,
        rec_size=rec_size, field_count=field_count,
        field_fmt=field_fmt, use_lzss=use_lzss
    )
    if ref_records is None:
        return mod_json, None

    # 4. 应用差异
    result = _apply_record_diff(ref_records, diff_data, field_count)
    return mod_json, result


def import_tksmod_text_defines(mod_path: str, ref_dir: str
                               ) -> tuple[dict | None, dict[str, str] | None]:
    """从 .tksmod 导入 TKD.dat 文本脚本差异。

    流程: 加载原始 TKD → 解析 DEFINE 块 → 应用 diff → 返回完整 defines 字典

    Returns:
        (metadata, defines_dict)
        defines_dict: {define_id_str: full_text, ...}
    """
    mod_json, data_files = read_tksmod(mod_path)
    if mod_json is None:
        return None, None

    diff_data = _find_component_data(mod_json, data_files, "TKD.dat")
    if diff_data is None:
        return mod_json, None

    # 加载原始 TKD.dat
    tkd_path = os.path.join(ref_dir, "TKD.dat")
    if not os.path.isfile(tkd_path):
        return mod_json, None

    # XOR 解密 + Big5 解码
    xor_table = bytes([i ^ 0xFF for i in range(256)])
    with open(tkd_path, 'rb') as f:
        raw = f.read()
    decoded = raw.translate(xor_table)
    try:
        text = decoded.decode('big5', errors='replace')
    except Exception:
        text = decoded.decode('gbk', errors='replace')

    # 解析为 DEFINE 块字典
    defines = _parse_defines_to_dict(text)

    # 应用差异
    modified = diff_data.get("modified", {})
    appended = diff_data.get("appended", [])
    deleted = diff_data.get("deleted", [])

    for did, content in modified.items():
        defines[did] = content

    if isinstance(appended, list):
        for content in appended:
            for line in content.split('\n'):
                stripped = line.strip().rstrip('\r')
                if stripped.startswith('DEFINE'):
                    parts = stripped.split(None, 1)
                    if len(parts) > 1:
                        defines[parts[1]] = content
                    break
    elif isinstance(appended, dict):
        for did, content in appended.items():
            defines[did] = content

    for did in deleted:
        defines.pop(did, None)

    return mod_json, defines


def import_tksmod_text_entries(mod_path: str, ref_dir: str
                               ) -> tuple[dict | None, dict[int, str] | None]:
    """从 .tksmod 导入 TKT.dat 文本条目差异。

    Returns:
        (metadata, entries_dict)
        entries_dict: {text_id: text_content, ...}
    """
    mod_json, data_files = read_tksmod(mod_path)
    if mod_json is None:
        return None, None

    diff_data = _find_component_data(mod_json, data_files, "TKT.dat")
    if diff_data is None:
        return mod_json, None

    # 加载原始 TKT 文本
    ref_entries = load_reference_tkt_entries(ref_dir)
    if ref_entries is None:
        return mod_json, None

    # 应用差异
    modified = diff_data.get("modified", {})
    appended = diff_data.get("appended", {})
    deleted = diff_data.get("deleted", [])

    for id_str, text in modified.items():
        ref_entries[int(id_str)] = text

    if isinstance(appended, dict):
        for id_str, text in appended.items():
            ref_entries[int(id_str)] = text

    for id_str in deleted:
        ref_entries.pop(int(id_str), None)

    return mod_json, ref_entries


def import_tksmod_blocks(mod_path: str, ref_dir: str, target_name: str,
                         block_type: str = "jvm_block"
                         ) -> tuple[dict | None, list[bytes] | None]:
    """从 .tksmod 导入块级二进制差异 (JVG/GRP)。

    流程: 加载原始块列表 → 应用块级 diff → 返回完整块列表

    Args:
        mod_path: .tksmod 文件路径
        ref_dir: 原始游戏目录
        target_name: 目标文件名 (如 "Cha.JVG" 或 "BattleBG.GRP")
        block_type: "jvm_block" | "grp_section"

    Returns:
        (metadata, blocks)
        blocks: [block0_bytes, block1_bytes, ...]
    """
    mod_json, data_files = read_tksmod(mod_path)
    if mod_json is None:
        return None, None

    diff_data = _find_component_data(mod_json, data_files, target_name)
    if diff_data is None:
        return mod_json, None

    # 加载原始块列表
    ref_path = os.path.join(ref_dir, target_name)
    if block_type == "jvm_block":
        blocks = load_jvg_raw_blocks(ref_path)
    else:
        blocks = load_grp_raw_sections(ref_path)

    if blocks is None:
        return mod_json, None

    # 应用差异
    modified_blocks = diff_data.get("modified", [])
    appended_blocks = diff_data.get("appended", [])
    deleted_indices = diff_data.get("deleted_indices", [])

    for entry in modified_blocks:
        idx = entry.get("index", -1)
        data_b64 = entry.get("data_b64", "")
        if 0 <= idx < len(blocks) and data_b64:
            blocks[idx] = base64.b64decode(data_b64)

    for entry in appended_blocks:
        idx = entry.get("index", -1)
        data_b64 = entry.get("data_b64", "")
        if data_b64:
            block_data = base64.b64decode(data_b64)
            while len(blocks) <= idx:
                blocks.append(b'')
            blocks[idx] = block_data

    for idx in sorted(deleted_indices, reverse=True):
        if 0 <= idx < len(blocks):
            blocks[idx] = b''

    return mod_json, blocks


def get_tksmod_info(mod_path: str) -> dict | None:
    """获取 .tksmod 的摘要信息，用于导入预览。

    Returns:
        {
            "id": str, "name": str, "version": str,
            "author": str, "description": str,
            "type": str, "mode": str, "load_order": int,
            "created": str,
            "components": [{"file": ..., "target": ...}],
            "targets": [target_name, ...],
            "stats": {target: {"modified": n, "appended": n, ...}},
        }
    """
    mod_json, data_files = read_tksmod(mod_path)
    if mod_json is None:
        return None

    targets = []
    stats = {}
    for comp in mod_json.get("components", []):
        target = comp.get("target", "")
        internal = comp.get("file", "")
        if target:
            targets.append(target)
        if internal in data_files:
            d = data_files[internal]
            stat = {}
            if isinstance(d.get("modified"), list):
                stat["modified"] = len(d["modified"])
            elif isinstance(d.get("modified"), dict):
                stat["modified"] = len(d["modified"])
            if isinstance(d.get("appended"), (list, dict)):
                stat["appended"] = len(d["appended"])
            if "deleted" in d:
                stat["deleted"] = len(d["deleted"])
            if "deleted_indices" in d:
                stat["deleted"] = len(d["deleted_indices"])
            stats[target] = stat

    return {
        "id": mod_json.get("id", ""),
        "name": mod_json.get("name", ""),
        "version": mod_json.get("version", ""),
        "author": mod_json.get("author", ""),
        "description": mod_json.get("description", ""),
        "type": mod_json.get("type", ""),
        "mode": mod_json.get("mode", ""),
        "load_order": mod_json.get("load_order", 100),
        "created": mod_json.get("created", ""),
        "dependencies": mod_json.get("dependencies", []),
        "conflicts": mod_json.get("conflicts", []),
        "id_ranges": mod_json.get("id_ranges", {}),
        "warpc_expand": mod_json.get("warpc_expand", 0),
        "scene_scope": mod_json.get("scene_scope", []),
        "scene_name": mod_json.get("scene_name", ""),
        "components": mod_json.get("components", []),
        "resources": mod_json.get("resources", []),
        "targets": targets,
        "stats": stats,
    }


# ── 导入辅助内部函数 ──

def _find_component_data(mod_json: dict, data_files: dict,
                         target_name: str) -> dict | None:
    """在 MOD 组件中找到指定 target 的差异数据。"""
    for comp in mod_json.get("components", []):
        if comp.get("target", "").lower() == target_name.lower():
            internal = comp.get("file", "")
            if internal in data_files:
                return data_files[internal]
    return None


def _apply_record_diff(original: list[list[int]], diff_data: dict,
                       field_count: int) -> list[list[int]]:
    """将定长记录差异应用到原始数据，返回完整修改后记录数组。"""
    # 深拷贝以避免修改原始
    result = [row[:] for row in original]

    # 确定最终大小
    max_idx = len(result) - 1
    for entry in diff_data.get("appended", []):
        idx = entry.get("index", 0)
        if idx > max_idx:
            max_idx = idx

    # 扩展到需要的大小
    while len(result) <= max_idx:
        result.append([0] * field_count)

    # 应用修改
    for entry in diff_data.get("modified", []):
        idx = entry.get("index", -1)
        if idx < 0 or idx >= len(result):
            continue
        fields = entry.get("fields", {})
        for fkey, value in fields.items():
            if fkey.startswith('f'):
                try:
                    fi = int(fkey[1:])
                    if 0 <= fi < field_count:
                        result[idx][fi] = int(value)
                except (ValueError, IndexError):
                    pass

    # 应用追加
    for entry in diff_data.get("appended", []):
        idx = entry.get("index", -1)
        if idx < 0 or idx >= len(result):
            continue
        fields = entry.get("fields", {})
        for fkey, value in fields.items():
            if fkey.startswith('f'):
                try:
                    fi = int(fkey[1:])
                    if 0 <= fi < field_count:
                        result[idx][fi] = int(value)
                except (ValueError, IndexError):
                    pass

    return result


def _parse_defines_to_dict(text: str) -> dict[str, str]:
    """解析 TKD.dat 文本为 DEFINE 块字典 {define_id_str: full_block_text}。"""
    lines = text.split('\n')
    defines = {}
    current_id = None
    current_lines = []

    for line in lines:
        raw = line.rstrip('\r')
        stripped = raw.strip()
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            define_id = parts[1] if len(parts) > 1 else "0"
            if current_id is not None:
                defines[current_id] = '\r\n'.join(current_lines)
            current_id = define_id
            current_lines = [raw]
        elif stripped.startswith('};') and current_id is not None:
            current_lines.append(raw)
            defines[current_id] = '\r\n'.join(current_lines)
            current_id = None
            current_lines = []
        elif current_id is not None:
            current_lines.append(raw)

    if current_id is not None:
        defines[current_id] = '\r\n'.join(current_lines)

    return defines


# ═══════════════════════════════════════════════════════════════
# MOD 导入预览对话框
# ═══════════════════════════════════════════════════════════════

class ModImportPreviewDialog(QDialog):
    """MOD 导入预览对话框 — 显示 MOD 信息并确认导入。"""

    def __init__(self, parent=None, mod_info: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("导入 MOD (.tksmod)")
        self.resize(520, 400)
        self._accepted = False
        info = mod_info or {}

        layout = QVBoxLayout(self)

        # MOD 基本信息
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("MOD ID:"), row, 0)
        grid.addWidget(QLabel(f"<b>{info.get('id', '—')}</b>"), row, 1)

        row += 1
        grid.addWidget(QLabel("名称:"), row, 0)
        grid.addWidget(QLabel(f"<b>{info.get('name', '—')}</b>"), row, 1)

        row += 1
        grid.addWidget(QLabel("版本:"), row, 0)
        grid.addWidget(QLabel(info.get('version', '—')), row, 1)

        row += 1
        grid.addWidget(QLabel("作者:"), row, 0)
        grid.addWidget(QLabel(info.get('author', '—')), row, 1)

        row += 1
        grid.addWidget(QLabel("创建时间:"), row, 0)
        grid.addWidget(QLabel(info.get('created', '—')), row, 1)

        row += 1
        grid.addWidget(QLabel("类型:"), row, 0)
        grid.addWidget(QLabel(info.get('type', '—')), row, 1)

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        grid.addWidget(QLabel(str(info.get('load_order', 100))), row, 1)

        layout.addLayout(grid)

        # 描述
        desc = info.get('description', '')
        if desc:
            layout.addSpacing(8)
            desc_lbl = QLabel(f"描述: {desc}")
            desc_lbl.setWordWrap(True)
            layout.addWidget(desc_lbl)

        # 组件变更统计
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>包含数据:</b>"))

        stats = info.get('stats', {})
        targets = info.get('targets', [])
        if targets:
            for t in targets:
                s = stats.get(t, {})
                parts = []
                if s.get('modified', 0): parts.append(f"{s['modified']} 处修改")
                if s.get('appended', 0): parts.append(f"{s['appended']} 处追加")
                if s.get('deleted', 0): parts.append(f"{s['deleted']} 处删除")
                stat_str = ", ".join(parts) if parts else "无变更"
                layout.addWidget(QLabel(f"  • {t}: {stat_str}"))
        else:
            layout.addWidget(QLabel("  (无数据组件)"))

        # 资源文件
        resources = info.get('resources', [])
        if resources:
            layout.addSpacing(8)
            layout.addWidget(QLabel(f"<b>资源替换: {len(resources)} 个文件</b>"))

        layout.addStretch()

        # 提示
        layout.addWidget(QLabel(
            "<i>导入将加载此 MOD 的修改数据到编辑器中。\n"
            "您需要指定原始游戏目录作为基底数据。</i>"))

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("导入")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
