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
import base64
import json
import os
import re
import struct as _struct
import uuid
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTextEdit, QVBoxLayout,
)

from editor_utils import theme_tokens as _tt_tokens
_PLACEHOLDER_GRAY = _tt_tokens.business_colors("launcher", _tt_tokens.THEMES[0])["placeholder_gray"]
from editor_utils.combo_box import EditorComboBox
from editor_utils.lzss import (
    MAX_MATCH as MAX_MATCH_LZ,
    MIN_MATCH as MIN_MATCH_LZ,
    RING_INIT_POS as RING_INIT,
    RING_INIT_VAL,
    RING_SIZE,
    lzss_compress_stream as _lzss_compress_stream,
    lzss_decompress_dat,
    lzss_decompress_stream as _lzss_decompress_stream,
)
from editor_utils.tkt_loader import load_tkt_full


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
        limit = min(field_count, len(orig), len(cur))
        field_diffs = {f"f{fi}": cur[fi] for fi in range(limit) if orig[fi] != cur[fi]}
        if field_diffs:
            modified.append({"index": i, "fields": field_diffs})

    # 追加新记录（超出原始范围的部分）
    for i in range(original_count, len(current)):
        cur = current[i]
        # 只记录非零字段以节省空间
        field_diffs = {f"f{fi}": cur[fi] for fi in range(min(field_count, len(cur))) if cur[fi] != 0}
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
                      resources: list[dict] | None = None,
                      configs: list[dict] | None = None) -> dict:
    """生成 mod.json 内容。

    Args:
        metadata: 包含 id, name, version, author, description, type, mode,
                  dependencies, conflicts, load_order, id_ranges, warpc_expand,
                  preview_image_path (可选, 本地预览图路径)
        components: [{"file": "data/X.json", "target": "X.dat"}, ...]
        resources: [{"file": "resources/X.JVG", "target": "X.JVG"}, ...]
        configs: [{"file": "configs/summon_table.json", "name": "summon_table"}, ...]
                 白名单内的启动器配置文件，MOD 包中携带时优先级最高

    Returns:
        完整的 mod.json 字典
    """
    now = datetime.now(timezone(timedelta(hours=8)))

    # 若有预览图，记录内部文件名（不含路径，仅文件名）
    preview_image = ""
    preview_path = metadata.get("preview_image_path", "")
    if preview_path and os.path.isfile(preview_path):
        ext = os.path.splitext(preview_path)[1].lower() or ".png"
        preview_image = f"preview{ext}"

    mod_json = {
        "format": "TKSMOD",
        "format_version": 1,
        "id": metadata.get("id", "unnamed_mod"),
        "name": metadata.get("name", "Unnamed MOD"),
        "version": metadata.get("version", "1.0.0"),
        "author": metadata.get("author", ""),
        "description": metadata.get("description", ""),
        "category": metadata.get("category", "other"),
        "tags": metadata.get("tags", []),
        "compatibility": metadata.get("compatibility", {}),
        "requires_features": metadata.get("requires_features", []),
        "notes": metadata.get("notes", ""),
        "created": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "game_version": metadata.get("game_version", "1.0"),

        "dependencies": metadata.get("dependencies", []),
        "conflicts": metadata.get("conflicts", []),
        "load_order": metadata.get("load_order", 100),

        "id_ranges": metadata.get("id_ranges", {}),
        "warpc_expand": metadata.get("warpc_expand", 0),

        "components": components,
        "resources": resources or [],
        "configs": configs or [],
    }
    if preview_image:
        mod_json["preview_image"] = preview_image
        # 内部辅助字段，供 pack_tksmod 读取原图路径，写入 ZIP 时自动过滤
        mod_json["_preview_image_path"] = preview_path
    return mod_json


# ═══════════════════════════════════════════════════════════════
# .tksmod 打包
# ═══════════════════════════════════════════════════════════════

def pack_tksmod(output_path: str, mod_json: dict,
                data_files: dict[str, Any],
                resource_files: dict[str, str] | None = None,
                preview_image_path: str | None = None,
                config_files: dict[str, Any] | None = None,
                blob_files: dict[str, bytes] | None = None) -> bool:
    """将 MOD 数据打包为 .tksmod (ZIP) 文件。

    Args:
        output_path: 输出 .tksmod 文件路径
        mod_json: mod.json 字典内容
        data_files: {"data/WarPC.dat.json": dict_content, ...}
                    value 为字典，将被 json.dumps 序列化
        resource_files: {"resources/Cha.JVG": "/abs/path/to/file", ...}
                        value 为源文件的绝对路径
        preview_image_path: 预览图本地路径（可选），自动打入 ZIP 根目录
        config_files: {"configs/summon_table.json": dict_content, ...}
                      白名单内的启动器配置文件，value 为已解析的字典

    Returns:
        True 成功
    """
    # 优先从参数取，其次从 mod_json 元数据取
    _preview = preview_image_path or mod_json.get("_preview_image_path", "")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 写入 mod.json
        # 去掉内部辅助字段（不应写入文件）
        _clean_json = {k: v for k, v in mod_json.items()
                       if not k.startswith('_')}
        mod_json_str = json.dumps(_clean_json, ensure_ascii=False, indent=2)
        zf.writestr("mod.json", mod_json_str)

        # 写入数据差异文件
        for internal_path, content_dict in data_files.items():
            json_str = json.dumps(content_dict, ensure_ascii=False, indent=2)
            zf.writestr(internal_path, json_str)

        # 写入启动器配置文件 (白名单内)
        if config_files:
            for internal_path, content_dict in config_files.items():
                json_str = json.dumps(content_dict, ensure_ascii=False, indent=2)
                zf.writestr(internal_path, json_str)

        # 写入二进制成员 (如 GRP 新增区段的原始字节, 避免 base64 膨胀/阻碍压缩)
        if blob_files:
            for internal_path, raw in blob_files.items():
                zf.writestr(internal_path, raw)

        # 写入资源文件
        if resource_files:
            for internal_path, source_path in resource_files.items():
                if os.path.isfile(source_path):
                    zf.write(source_path, internal_path)

        # 写入预览图
        if _preview and os.path.isfile(_preview):
            preview_internal = mod_json.get("preview_image", "") or \
                               f"preview{os.path.splitext(_preview)[1].lower() or '.png'}"
            zf.write(_preview, preview_internal)

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


def extract_preview_image(mod_path: str) -> bytes | None:
    """从 .tksmod/.tksmodpak 中提取预览图字节数据。

    根据 mod.json 中的 preview_image 字段定位文件并读取。

    Returns:
        图片字节数据，或 None（无预览图/读取失败）
    """
    if not os.path.isfile(mod_path):
        return None
    try:
        with zipfile.ZipFile(mod_path, 'r') as zf:
            if "mod.json" not in zf.namelist():
                return None
            mj = json.loads(zf.read("mod.json").decode('utf-8'))
            preview_name = mj.get("preview_image", "")
            if not preview_name or preview_name not in zf.namelist():
                return None
            return zf.read(preview_name)
    except Exception:
        return None


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

def safe_mod_filename(name: str, fallback_id: str) -> str:
    """将 MOD 名称转为安全的文件名。name 为空时回退到 fallback_id。

    用于导出 MOD 时生成保存对话框的默认文件名.
    过滤 Windows 文件名非法字符, 移除首尾空格和点.

    Args:
        name: MOD 显示名称 (来自 ModMetadataDialog)
        fallback_id: MOD ID, 名称不可用时回退

    Returns:
        安全的文件名字符串 (不含扩展名)
    """
    if not name or not name.strip():
        return fallback_id
    safe = re.sub(r'[<>:"/\\|?*]', '_', name.strip())
    safe = safe.strip('. ')
    return safe or fallback_id


def generate_short_uuid(length: int = 16) -> str:
    """生成不含 '-' 的短 UUID（取 uuid4 十六进制前 length 位）。

    Args:
        length: 返回字符数，默认 16

    Returns:
        不含 '-' 的大写十六进制字符串，如 'A1B2C3D4E5F67890'
    """
    return uuid.uuid4().hex[:length].upper()


class ModMetadataDialog(QDialog):
    """MOD 元数据输入对话框，用于首次导出时收集信息。"""

    _PREVIEW_IMG_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)"
    _PREVIEW_THUMB_SIZE = 120  # 预览图缩略图最大边长

    def __init__(self, parent=None, defaults: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("导出为 MOD (.tksmod)")
        self.resize(520, 430)
        self.metadata = {}
        self._preview_path: str = ""  # 当前选中的预览图本地路径
        defaults = defaults or {}

        layout = QVBoxLayout(self)

        # 表单
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("MOD ID *:"), row, 0)
        id_row = QHBoxLayout()
        self.edit_id = QLineEdit(defaults.get("id", "") or generate_short_uuid())
        self.edit_id.setPlaceholderText("唯一标识符, 可手动修改或重新生成")
        id_row.addWidget(self.edit_id)
        self.btn_regen_id = QPushButton("重新生成")
        self.btn_regen_id.clicked.connect(self._regen_id)
        id_row.addWidget(self.btn_regen_id)
        grid.addLayout(id_row, row, 1)

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
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        self.spin_order.setValue(defaults.get("load_order", 100))
        grid.addWidget(self.spin_order, row, 1)

        row += 1
        grid.addWidget(QLabel("分类:"), row, 0)
        self.edit_category = EditorComboBox()
        for value, label in (("other", "其他"), ("visual", "美化"),
                             ("avatar", "头像"), ("music", "音乐"),
                             ("story", "剧情"), ("gameplay", "功能"),
                             ("save", "存档"), ("config", "配置"),
                             ("tks_exe", "TKS.exe 替换"), ("mixed", "综合"),
                             ("font", "字体"), ("interface", "界面"),
                             ("map", "地图")):
            self.edit_category.addItem(label, value)
        default_category = self.edit_category.findData(defaults.get("category", "other"))
        self.edit_category.setCurrentIndex(default_category if default_category >= 0 else 0)
        grid.addWidget(self.edit_category, row, 1)

        row += 1
        grid.addWidget(QLabel("标签:"), row, 0)
        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("逗号分隔，例如 avatar, visual, resource")
        default_tags = defaults.get("tags", [])
        self.edit_tags.setText(", ".join(default_tags) if isinstance(default_tags, list) else "")
        grid.addWidget(self.edit_tags, row, 1)

        # 预览图行
        row += 1
        grid.addWidget(QLabel("预览图:"), row, 0, Qt.AlignTop)
        preview_card = QHBoxLayout()
        preview_card.setContentsMargins(0, 4, 0, 4)
        preview_card.setSpacing(14)

        self._lbl_preview_thumb = QLabel()
        self._lbl_preview_thumb.setObjectName("previewThumb")
        self._lbl_preview_thumb.setFixedSize(
            self._PREVIEW_THUMB_SIZE, self._PREVIEW_THUMB_SIZE)
        self._lbl_preview_thumb.setAlignment(Qt.AlignCenter)
        self._lbl_preview_thumb.setText("无预览图")
        preview_card.addWidget(self._lbl_preview_thumb)

        preview_info = QVBoxLayout()
        preview_info.setContentsMargins(0, 0, 0, 0)
        preview_info.setSpacing(8)
        self._lbl_preview_name = QLabel(f"<i style='color:{_PLACEHOLDER_GRAY}'>未选择图片</i>")
        self._lbl_preview_name.setWordWrap(True)
        preview_info.addWidget(self._lbl_preview_name)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_pick_img = QPushButton("选择图片")
        self._btn_pick_img.setFixedWidth(100)
        self._btn_pick_img.clicked.connect(self._on_pick_preview_image)
        btn_row.addWidget(self._btn_pick_img)
        self._btn_clear_img = QPushButton("清除")
        self._btn_clear_img.setFixedWidth(60)
        self._btn_clear_img.clicked.connect(self._on_clear_preview_image)
        btn_row.addWidget(self._btn_clear_img)
        btn_row.addStretch()
        preview_info.addLayout(btn_row)

        preview_info.addStretch()
        preview_card.addLayout(preview_info, 1)
        grid.addLayout(preview_card, row, 1)

        # 恢复默认预览图路径
        default_preview = defaults.get("preview_image_path", "")
        if default_preview and os.path.isfile(default_preview):
            self._set_preview_image(default_preview)

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

    def _on_pick_preview_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择预览图", "", self._PREVIEW_IMG_FILTER)
        if path:
            self._set_preview_image(path)

    def _on_clear_preview_image(self):
        self._preview_path = ""
        self._lbl_preview_thumb.clear()
        self._lbl_preview_thumb.setText("无预览图")
        self._lbl_preview_name.setText(f"<i style='color:{_PLACEHOLDER_GRAY}'>未选择图片</i>")

    def _set_preview_image(self, path: str):
        """加载并显示预览图缩略图。"""
        self._preview_path = path
        self._lbl_preview_name.setText(os.path.basename(path))
        pm = QPixmap(path)
        if not pm.isNull():
            scaled = pm.scaled(
                self._PREVIEW_THUMB_SIZE, self._PREVIEW_THUMB_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._lbl_preview_thumb.setPixmap(scaled)
        else:
            self._lbl_preview_thumb.setText("无法加载")

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
            "load_order": self.spin_order.value(),
            "category": self.edit_category.currentData() or "other",
            "tags": [s.strip() for s in self.edit_tags.text().split(",") if s.strip()],
            "preview_image_path": self._preview_path,
        }
        self.accept()

    def get_metadata(self) -> dict:
        return self.metadata

    def _regen_id(self):
        """重新生成默认 MOD ID（不影响已手动修改的内容，直接覆盖）。"""
        self.edit_id.setText(generate_short_uuid())
        self.edit_id.setFocus()


# ═══════════════════════════════════════════════════════════════
# 参考目录选择 + 原始数据加载辅助
# ═══════════════════════════════════════════════════════════════

def ask_reference_directory(parent, title="选择原始游戏目录 (作为 MOD 差异参考)") -> str | None:
    """弹出目录选择对话框，让用户选择原始/未修改的游戏目录作为 diff 参考基准。

    Returns:
        目录路径，或 None（用户取消）
    """
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
    fp = os.path.join(ref_dir, dat_name)
    if not os.path.isfile(fp):
        return None

    with open(fp, 'rb') as f:
        raw = f.read()

    if use_lzss:
        dec = lzss_decompress_dat(raw)
        # 兜底: 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
        if len(raw) % rec_size == 0 and (len(dec) == 0 or len(dec) % rec_size != 0):
            dec = raw
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
    entries = load_tkt_full(fp)
    return {e['id']: e['text'] for e in entries}


# ═══════════════════════════════════════════════════════════════
# 块级增量: JVG / GRP 二进制资源
# ═══════════════════════════════════════════════════════════════

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
    if not os.path.isfile(filepath):
        return None

    with open(filepath, 'rb') as f:
        data = f.read()

    # 尝试找 IDX 文件
    if idx_path is None:
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


# 定长记录文件的块大小映射 (与 tks_launcher_gui/core/mod_loader.py 保持一致)
_FIXED_RECORD_SIZES = {
    "act_entry": 784,   # TKAct.dat: 650 条 × 784 字节
}


def load_fixed_record_blocks(filepath: str, record_size: int
                             ) -> list[bytes] | None:
    """加载定长记录的平坦二进制文件为块列表 (无头部、无压缩)。

    用于 TKAct.dat 等固定记录文件，每条记录作为一个独立的 block。

    Args:
        filepath: 文件路径
        record_size: 每条记录的字节数 (如 TKAct.dat = 784)

    Returns:
        [record0_bytes, record1_bytes, ...] 或 None (文件不存在/大小不对齐)
    """
    if not os.path.isfile(filepath):
        return None
    with open(filepath, 'rb') as f:
        data = f.read()
    if len(data) == 0 or len(data) % record_size != 0:
        return None
    count = len(data) // record_size
    return [data[i * record_size:(i + 1) * record_size] for i in range(count)]


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

    # 规范化: list → {id: content} 字典，统一按 dict 处理
    if isinstance(appended, list):
        _appended_dict = {}
        for content in appended:
            for line in content.split('\n'):
                stripped = line.strip().rstrip('\r')
                if stripped.startswith('DEFINE'):
                    parts = stripped.split(None, 1)
                    if len(parts) > 1:
                        _appended_dict[parts[1]] = content
                    break
        appended = _appended_dict

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
    """从 .tksmod 导入块级二进制差异 (JVG/GRP/定长记录)。

    流程: 加载原始块列表 → 应用块级 diff → 返回完整块列表

    Args:
        mod_path: .tksmod 文件路径
        ref_dir: 原始游戏目录
        target_name: 目标文件名 (如 "Cha.JVG" / "BattleBG.GRP" / "TKAct.dat")
        block_type: "jvm_block" | "grp_section" | "act_entry"

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
    elif block_type in _FIXED_RECORD_SIZES:
        blocks = load_fixed_record_blocks(ref_path, _FIXED_RECORD_SIZES[block_type])
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
        "configs": mod_json.get("configs", []),
        "preview_image": mod_json.get("preview_image", ""),
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


def _update_record_fields(record: list[int], fields: dict, field_count: int):
    """将字段差异字典应用到单条记录。"""
    for fkey, value in fields.items():
        if fkey.startswith('f'):
            fi = int(fkey[1:])
            if 0 <= fi < field_count:
                record[fi] = int(value)


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

    # 应用修改 & 追加（共用字段更新逻辑）
    for key in ("modified", "appended"):
        for entry in diff_data.get(key, []):
            idx = entry.get("index", -1)
            if 0 <= idx < len(result):
                _update_record_fields(result[idx], entry.get("fields", {}), field_count)

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

    def __init__(self, parent=None, mod_info: dict | None = None, default_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("导入 MOD (.tksmod)")
        self.resize(520, 460)
        self._accepted = False
        self._ref_dir = default_dir
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

        # 参考目录选择
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>原始游戏目录 (基底数据):</b>"))
        dir_layout = QHBoxLayout()
        self._dir_edit = QLineEdit(self._ref_dir)
        self._dir_edit.setReadOnly(True)
        self._dir_edit.setMinimumWidth(280)
        dir_layout.addWidget(self._dir_edit, 1)
        btn_browse = QPushButton("选择目录")
        btn_browse.clicked.connect(self._on_browse_dir)
        dir_layout.addWidget(btn_browse)
        layout.addLayout(dir_layout)

        layout.addStretch()

        # 提示
        layout.addWidget(QLabel(
            "<i>导入将以此目录中的原始文件为基底，应用 MOD 的差异数据。</i>"))

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("导入")
        btn_ok.clicked.connect(self._on_import)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _on_browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择原始游戏目录", self._ref_dir)
        if d:
            self._ref_dir = d
            self._dir_edit.setText(d)

    def _on_import(self):
        if not self._ref_dir or not os.path.isdir(self._ref_dir):
            QMessageBox.warning(self, "缺少目录", "请先选择原始游戏目录。")
            return
        self.accept()

    def get_ref_dir(self) -> str:
        return self._ref_dir


# ═══════════════════════════════════════════════════════════════
# 跨编辑器共享状态 (最近使用的参考目录)
# ═══════════════════════════════════════════════════════════════
# 实现已迁移至 editor_utils.shared_state, 此处保留同名函数兼容现有调用
from editor_utils.shared_state import (  # noqa: E402
    get_last_ref_dir,
    save_last_ref_dir,
)


# ═══════════════════════════════════════════════════════════════
# MOD 导出预览对话框
# ═══════════════════════════════════════════════════════════════

class ModExportPreviewDialog(QDialog):
    """MOD 导出预览对话框 — 选择参考目录并显示组件变更统计。

    流程: 用户确认目录和变更统计 → 点击"导出" → 调用方弹出 ModMetadataDialog 填写元数据。

    参考目录记忆: 优先加载共享状态中最近一次选择的目录 (跨编辑器共享);
    确认导出后自动保存当前目录供其它编辑器默认加载。
    """

    def __init__(self, parent=None, default_dir: str = "",
                 compute_stats: callable = None,
                 mod_info: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("导出为 MOD — 选择参考目录")
        self.resize(520, 420)
        # 优先使用共享记忆中最近选择的参考目录, 否则回退到调用方默认目录
        _saved_dir = get_last_ref_dir()
        self._ref_dir = _saved_dir if _saved_dir else default_dir
        self._compute_stats = compute_stats
        self._info = mod_info or {}
        self._has_diff = False

        layout = QVBoxLayout(self)

        # ── 参考目录选择 ──
        layout.addWidget(QLabel("<b>原始游戏目录 (差异参考):</b>"))
        dir_layout = QHBoxLayout()
        self._dir_edit = QLineEdit(self._ref_dir)
        self._dir_edit.setReadOnly(True)
        self._dir_edit.setMinimumWidth(280)
        dir_layout.addWidget(self._dir_edit, 1)
        btn_browse = QPushButton("选择目录")
        btn_browse.clicked.connect(self._on_browse_dir)
        dir_layout.addWidget(btn_browse)
        layout.addLayout(dir_layout)

        layout.addSpacing(12)

        # ── 组件变更统计 ──
        layout.addWidget(QLabel("<b>包含数据:</b>"))
        self._stats_layout = QVBoxLayout()
        self._stats_layout.setSpacing(2)
        layout.addLayout(self._stats_layout)

        layout.addStretch()

        # ── 提示 ──
        self._hint_label = QLabel(
            "<i>确认参考目录和变更统计后，点击「导出」填写 MOD 元数据。</i>")
        layout.addWidget(self._hint_label)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        self._btn_export = QPushButton("导出")
        self._btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self._btn_export)
        layout.addLayout(btn_layout)

        # 初始计算
        self._refresh_stats()

    def _on_browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择原始游戏目录", self._ref_dir)
        if d:
            self._ref_dir = d
            self._dir_edit.setText(d)
            self._refresh_stats()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh_stats(self):
        self._clear_layout(self._stats_layout)
        self._has_diff = False

        if not self._compute_stats:
            self._stats_layout.addWidget(QLabel("  (无统计数据)"))
            return
        if not self._ref_dir or not os.path.isdir(self._ref_dir):
            self._stats_layout.addWidget(QLabel("  (请选择有效的原始游戏目录)"))
            return

        try:
            result = self._compute_stats(self._ref_dir)
        except Exception as e:
            self._stats_layout.addWidget(QLabel(f"  (计算失败: {e})"))
            return

        if result is None or not result.get("valid", False):
            err = (result or {}).get("error", "目录中未找到目标文件")
            self._stats_layout.addWidget(QLabel(f"  (错误: {err})"))
            return

        targets = result.get("targets", [])
        if not targets:
            self._stats_layout.addWidget(QLabel("  (当前数据与参考文件相同，无差异)"))
            return

        self._has_diff = True
        for t in targets:
            name = t.get("name", "?")
            parts = []
            if t.get("modified", 0): parts.append(f"{t['modified']} 处修改")
            if t.get("appended", 0): parts.append(f"{t['appended']} 处追加")
            if t.get("deleted", 0): parts.append(f"{t['deleted']} 处删除")
            stat_str = ", ".join(parts) if parts else "无变更"
            self._stats_layout.addWidget(QLabel(f"  • {name}: {stat_str}"))

    def _on_export(self):
        if not self._ref_dir or not os.path.isdir(self._ref_dir):
            QMessageBox.warning(self, "缺少目录", "请先选择原始游戏目录。")
            return
        if not self._has_diff:
            return  # 无差异时静默忽略点击
        # 记住本次选择的参考目录, 供所有编辑器下次导出默认加载
        save_last_ref_dir(self._ref_dir)
        self.accept()

    def get_ref_dir(self) -> str:
        return self._ref_dir


# ═══════════════════════════════════════════════════════════════
# 记录型编辑器统一的 .tksmod 导出/导入编排 (T10 收敛)
# 收敛自 item/skill/kon/shop 四份逐字级克隆; 差异经 RecordModSpec 声明。
# warpc (草稿守卫+id_ranges 扩展) 与 wardata (_raw 结构化+双文件) 有
# 真实域差异, 保留各自实现。
# ═══════════════════════════════════════════════════════════════

class RecordModSpec:
    """记录型编辑器导出/导入的数据差异描述。

    Attributes:
        dat_name:    目标文件名 (如 "TKItem.dat")
        rec_size:    每条记录字节数
        field_type:  build_data_diff_json 的 field_type ("int16"/"mixed")
        field_count: 字段数
        to_fields:   records -> list[list[int]] (与编辑器 _original_records 同布局)
        from_fields: list[list[int]] -> records (导入后重建编辑器记录)
        path_attr:   编辑器数据文件路径属性名 (如 "item_path")
        status_attr: 状态栏文本控件属性名 (status_var/status_label/lbl_status)
        refresh_attr: 导入后刷新列表的方法名 (_apply_filter/_refresh_table)
        noun:        导入成功状态栏中的记录量词 (如 "条物品")
    """

    def __init__(self, *, dat_name, rec_size, field_type, field_count,
                 to_fields, from_fields, path_attr, status_attr,
                 refresh_attr, noun="条记录"):
        self.dat_name = dat_name
        self.rec_size = rec_size
        self.field_type = field_type
        self.field_count = field_count
        self.to_fields = to_fields
        self.from_fields = from_fields
        self.path_attr = path_attr
        self.status_attr = status_attr
        self.refresh_attr = refresh_attr
        self.noun = noun

    def status(self, editor):
        return getattr(editor, self.status_attr)


def export_records_mod(editor, spec, ref_mode=False):
    """统一导出编排 — 原 item/skill/kon/shop 的 _export_tksmod[_with_ref]。

    ref_mode=False: 与加载基线 (editor._original_records) 比对;
    ref_mode=True:  弹参考目录选择, 与参考目录中的原版文件比对。
    """
    if ref_mode:
        if not editor.records:
            QMessageBox.information(editor, "提示", "请先加载数据")
            return
    else:
        if not editor.records or not editor._original_records:
            QMessageBox.information(editor, "提示", "请先加载数据")
            return

    current_fields = spec.to_fields(editor.records)
    ref_records = None

    if ref_mode:
        def _compute_stats(ref_dir):
            ref = load_reference_dat_fields(ref_dir, spec.dat_name,
                rec_size=spec.rec_size, field_count=spec.field_count,
                field_fmt='h', use_lzss=True)
            if ref is None:
                return {"valid": False, "error": f"目录中未找到 {spec.dat_name}"}
            diff = diff_records(ref, current_fields, spec.field_count, len(ref))
            targets = []
            if diff['modified'] or diff['appended']:
                targets.append({"name": spec.dat_name,
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": 0})
            return {"valid": True, "targets": targets}

        base_dir = getattr(editor, spec.path_attr, None)
        preview_dlg = ModExportPreviewDialog(editor,
            default_dir=os.path.dirname(base_dir) if base_dir else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_records = load_reference_dat_fields(ref_dir, spec.dat_name,
            rec_size=spec.rec_size, field_count=spec.field_count,
            field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(editor, "参考目录无效", f"在 {ref_dir} 中未找到 {spec.dat_name}")
            return
        diff_result = diff_records(ref_records, current_fields, spec.field_count, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(editor, "无差异", "当前数据与参考文件相同，无需导出。")
            return
    else:
        diff_result = diff_records(editor._original_records, current_fields,
                                   spec.field_count, len(editor._original_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(editor, "无差异", "当前数据与原始文件相同，无需导出。")
            return

    dlg = ModMetadataDialog(editor, getattr(editor, '_last_mod_metadata', None))
    if dlg.exec() != QDialog.Accepted: return
    metadata = dlg.get_metadata()
    editor._last_mod_metadata = metadata

    if ref_mode:
        src_path = os.path.join(ref_dir, spec.dat_name)
        original_count = len(ref_records)
    else:
        src_path = getattr(editor, spec.path_attr, None)
        original_count = len(editor._original_records)
    crc = compute_crc32(src_path) if src_path else "0x00000000"
    data_json = build_data_diff_json(target=spec.dat_name, record_size=spec.rec_size,
        field_type=spec.field_type, field_count=spec.field_count,
        original_count=original_count, original_crc32=crc, diff_result=diff_result)
    mod_json = generate_mod_json(metadata,
        [{"file": f"data/{spec.dat_name}.json", "target": spec.dat_name}])
    fp, _ = QFileDialog.getSaveFileName(editor, "导出为 MOD",
        f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
    if not fp: return
    try:
        pack_tksmod(fp, mod_json, {f"data/{spec.dat_name}.json": data_json})
        n_mod = len(diff_result['modified'])
        n_app = len(diff_result['appended'])
        if ref_mode:
            spec.status(editor).setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(editor, "导出成功",
                f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {n_mod} 条\n追加: {n_app} 条")
        else:
            spec.status(editor).setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(editor, "导出成功",
                f"已导出:\n{fp}\n\n修改: {n_mod} 条\n追加: {n_app} 条")
    except Exception as e:
        QMessageBox.critical(editor, "导出失败", str(e))


def import_records_mod(editor, spec):
    """统一导入编排 — 原 item/skill/kon/shop 的 _import_tksmod。

    整体替换 records 并重置 _original_records; 撤销栈清空
    (kon 原实现漏调 clear_undo, 收敛后与其余三家对齐)。"""
    fp, _ = QFileDialog.getOpenFileName(editor, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
    if not fp: return

    info = get_tksmod_info(fp)
    if info is None:
        QMessageBox.warning(editor, "无效文件", "无法解析此 .tksmod 文件")
        return

    if spec.dat_name not in info.get("targets", []):
        QMessageBox.warning(editor, "不兼容", f"此 MOD 不包含 {spec.dat_name} 的数据\n\n"
            f"包含的数据: {', '.join(info.get('targets', []))}")
        return

    base_dir = getattr(editor, spec.path_attr, None)
    dlg = ModImportPreviewDialog(editor, info,
        default_dir=os.path.dirname(base_dir) if base_dir else "")
    if dlg.exec() != QDialog.Accepted: return
    ref_dir = dlg.get_ref_dir()
    if not ref_dir: return

    mod_json, records = import_tksmod_records(
        fp, ref_dir, spec.dat_name,
        rec_size=spec.rec_size, field_count=spec.field_count,
        field_fmt='h', use_lzss=True
    )
    if records is None:
        QMessageBox.warning(editor, "导入失败",
            f"无法导入 MOD 数据。\n请确认参考目录中包含有效的 {spec.dat_name}")
        return

    editor.records = spec.from_fields(records)
    if hasattr(editor, 'clear_undo'):
        editor.clear_undo()  # 导入整体替换, 旧变更集失效 (P3-4)
    editor._original_records = [list(row) for row in records]
    editor._dirty = False

    editor._last_mod_metadata = {
        "id": info.get("id", ""),
        "name": info.get("name", ""),
        "version": info.get("version", "1.0.0"),
        "author": info.get("author", ""),
        "description": info.get("description", ""),
        "load_order": info.get("load_order", 100),
    }

    getattr(editor, spec.refresh_attr)()
    spec.status(editor).setText(
        f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
        f"{len(editor.records)} {spec.noun}")
    QMessageBox.information(editor, "导入成功",
        f"已导入 MOD: {info.get('name', '')}\n"
        f"版本: {info.get('version', '')}\n"
        f"作者: {info.get('author', '')}\n\n"
        f"共加载 {len(records)} 条记录。\n"
        f"您现在可以继续编辑并重新导出。")
