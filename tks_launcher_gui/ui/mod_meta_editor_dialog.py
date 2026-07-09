"""模组元数据编辑对话框 — 加载 .tksmod / .tksmodpak 编辑元数据后保存，不改模组内容"""
import json
import os
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
)

from core.mod_packer import read_tksmod_content, rewrite_mod_metadata
from editor_utils.mod_exporter import extract_preview_image, generate_short_uuid


class ModMetaEditorDialog(QDialog):
    """模组元数据编辑器：打开 .tksmod → 编辑元数据 → 保存/另存为。

    仅修改 mod.json 中的元数据字段，data/* 与 resources/* 内容保持不变。
    """

    def __init__(self, mods_dir: str = "mods", parent=None, initial_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("模组信息编辑")
        self.resize(560, 540)
        self._mods_dir = mods_dir
        self._mod_path: str = ""

        layout = QVBoxLayout(self)

        # ---- 文件选择 ----
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("模组文件:"))
        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("点击「打开…」选择 .tksmod 文件")
        file_row.addWidget(self.edit_path, 1)
        self.btn_open = QPushButton("打开…")
        self.btn_open.clicked.connect(self._on_open)
        file_row.addWidget(self.btn_open)
        layout.addLayout(file_row)

        # ---- 元数据表单 ----
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("模组 ID *:"), row, 0)
        id_row = QHBoxLayout()
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("唯一标识符")
        self.edit_id.setMaxLength(16)  # 模组 ID 最大 16 位
        # 输入时实时移除所有空格（前后及中间），并保持光标位置
        self.edit_id.textChanged.connect(self._on_id_text_changed)
        id_row.addWidget(self.edit_id)
        self.btn_regen_id = QPushButton("重新生成")
        self.btn_regen_id.clicked.connect(self._regen_id)
        id_row.addWidget(self.btn_regen_id)
        grid.addLayout(id_row, row, 1)

        row += 1
        grid.addWidget(QLabel("名称 *:"), row, 0)
        self.edit_name = QLineEdit()
        grid.addWidget(self.edit_name, row, 1)

        row += 1
        grid.addWidget(QLabel("版本:"), row, 0)
        self.edit_version = QLineEdit()
        grid.addWidget(self.edit_version, row, 1)

        row += 1
        grid.addWidget(QLabel("作者:"), row, 0)
        self.edit_author = QLineEdit()
        grid.addWidget(self.edit_author, row, 1)

        row += 1
        grid.addWidget(QLabel("描述:"), row, 0)
        self.edit_desc = QTextEdit()
        self.edit_desc.setMaximumHeight(80)
        grid.addWidget(self.edit_desc, row, 1)

        row += 1

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        grid.addWidget(self.spin_order, row, 1)

        row += 1
        grid.addWidget(QLabel("游戏版本:"), row, 0)
        self.edit_gamever = QLineEdit()
        grid.addWidget(self.edit_gamever, row, 1)

        row += 1
        grid.addWidget(QLabel("依赖:"), row, 0)
        self.edit_deps = QLineEdit()
        self.edit_deps.setPlaceholderText("逗号分隔的模组 ID")
        grid.addWidget(self.edit_deps, row, 1)

        row += 1
        grid.addWidget(QLabel("冲突:"), row, 0)
        self.edit_conflicts = QLineEdit()
        self.edit_conflicts.setPlaceholderText("逗号分隔的模组 ID")
        grid.addWidget(self.edit_conflicts, row, 1)

        # 预览图行
        row += 1
        grid.addWidget(QLabel("预览图:"), row, 0, Qt.AlignTop)
        self._preview_path: str = ""  # 新选择的本地图片路径
        self._orig_preview_name: str = ""  # 原文件中的预览图文件名
        _preview_card = QHBoxLayout()
        _preview_card.setContentsMargins(0, 4, 0, 4)
        _preview_card.setSpacing(14)
        self._lbl_preview_thumb = QLabel()
        self._lbl_preview_thumb.setFixedSize(120, 120)
        self._lbl_preview_thumb.setAlignment(Qt.AlignCenter)
        self._lbl_preview_thumb.setStyleSheet(
            "QLabel { border: 2px dashed #555; border-radius: 6px; "
            "background: #1e1e1e; color: #666; }")
        self._lbl_preview_thumb.setText("无预览图")
        _preview_card.addWidget(self._lbl_preview_thumb)
        _preview_info = QVBoxLayout()
        _preview_info.setContentsMargins(0, 0, 0, 0)
        _preview_info.setSpacing(8)
        self._lbl_preview_name = QLabel("<i style='color:#888'>未选择图片</i>")
        self._lbl_preview_name.setWordWrap(True)
        _preview_info.addWidget(self._lbl_preview_name)
        _btn_row = QHBoxLayout()
        _btn_row.setSpacing(8)
        _btn_pick = QPushButton("选择图片…")
        _btn_pick.setFixedWidth(100)
        _btn_pick.clicked.connect(self._on_pick_preview)
        _btn_row.addWidget(_btn_pick)
        _btn_clear = QPushButton("清除")
        _btn_clear.setFixedWidth(60)
        _btn_clear.clicked.connect(self._on_clear_preview)
        _btn_row.addWidget(_btn_clear)
        _btn_row.addStretch()
        _preview_info.addLayout(_btn_row)
        _preview_info.addStretch()
        _preview_card.addLayout(_preview_info, 1)
        grid.addLayout(_preview_card, row, 1)

        layout.addLayout(grid)

        # 提示
        tip = QLabel("<i>仅修改元数据，模组数据与资源内容保持不变。</i>")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("btnPack")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_saveas = QPushButton("另存为…")
        self.btn_saveas.clicked.connect(self._on_save_as)
        self.btn_saveas.setEnabled(False)
        btn_row.addWidget(self.btn_saveas)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._set_fields_enabled(False)

        # 若传入了初始路径且文件存在，自动加载
        if initial_path and os.path.isfile(initial_path):
            self._load(initial_path)

    # ────────────────────────────────────────────────
    # 字段状态
    # ────────────────────────────────────────────────

    def _fields(self):
        return (self.edit_id, self.btn_regen_id, self.edit_name, self.edit_version,
                self.edit_author, self.edit_desc,
                self.spin_order, self.edit_gamever, self.edit_deps, self.edit_conflicts)

    def _set_fields_enabled(self, enabled: bool):
        for w in self._fields():
            w.setEnabled(enabled)

    # ────────────────────────────────────────────────
    # 打开 / 加载
    # ────────────────────────────────────────────────

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模组文件", self._mods_dir,
            "TKS 模组文件 (*.tksmod *.tksmodpak);;所有文件 (*)"
        )
        if not path:
            return
        self._load(path)

    def _load(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".tksmodpak":
            self._load_tksmodpak(path)
        else:
            self._load_tksmod(path)

    def _load_tksmod(self, path: str):
        content = read_tksmod_content(path)
        if not content.valid:
            QMessageBox.warning(self, "无法加载", f"读取失败: {content.error}")
            return
        self._mod_path = path
        self.edit_path.setText(path)
        self._fill_fields(content.mod_json)

    def _load_tksmodpak(self, path: str):
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                if "mod.json" not in zf.namelist():
                    QMessageBox.warning(self, "无法加载", "该合集文件中缺少 mod.json")
                    return
                mj_str = zf.read("mod.json").decode('utf-8')
                mj = json.loads(mj_str)
        except Exception as e:
            QMessageBox.warning(self, "无法加载", f"读取失败: {e}")
            return

        self._mod_path = path
        self.edit_path.setText(path)
        self._fill_fields(mj)

    def _fill_fields(self, mj: dict):
        self.edit_id.setText(mj.get("id", ""))
        self.edit_name.setText(mj.get("name", ""))
        self.edit_version.setText(mj.get("version", "1.0.0"))
        self.edit_author.setText(mj.get("author", ""))
        self.edit_desc.setPlainText(mj.get("description", ""))

        self.spin_order.setValue(mj.get("load_order", 100))
        self.edit_gamever.setText(mj.get("game_version", "1.0"))
        self.edit_deps.setText(", ".join(mj.get("dependencies", [])))
        self.edit_conflicts.setText(", ".join(mj.get("conflicts", [])))

        # 预览图
        self._preview_path = ""
        self._orig_preview_name = mj.get("preview_image", "")
        if self._orig_preview_name:
            # 从文件中提取预览图显示
            img_data = extract_preview_image(self._mod_path)
            if img_data:
                pm = QPixmap()
                pm.loadFromData(img_data)
                if not pm.isNull():
                    scaled = pm.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._lbl_preview_thumb.setPixmap(scaled)
                    self._lbl_preview_name.setText(self._orig_preview_name)
                else:
                    self._lbl_preview_thumb.setText("无法加载")
                    self._lbl_preview_name.setText(self._orig_preview_name)
            else:
                self._lbl_preview_thumb.setText("无预览图")
                self._lbl_preview_name.setText(self._orig_preview_name)
        else:
            self._lbl_preview_thumb.setText("无预览图")
            self._lbl_preview_name.setText("<i>未选择</i>")

        self._set_fields_enabled(True)
        self.btn_save.setEnabled(True)
        self.btn_saveas.setEnabled(True)


    # ────────────────────────────────────────────────
    # 收集 / 校验 / 保存
    # ────────────────────────────────────────────────

    def _collect_metadata(self) -> dict:
        deps = [s.strip() for s in self.edit_deps.text().split(",") if s.strip()]
        conflicts = [s.strip() for s in self.edit_conflicts.text().split(",") if s.strip()]
        meta = {
            "id": self.edit_id.text().strip(),
            "name": self.edit_name.text().strip(),
            "version": self.edit_version.text().strip() or "1.0.0",
            "author": self.edit_author.text().strip(),
            "description": self.edit_desc.toPlainText().strip(),
            "load_order": self.spin_order.value(),
            "game_version": self.edit_gamever.text().strip() or "1.0",
            "dependencies": deps,
            "conflicts": conflicts,
        }
        # 预览图：优先用新选择的，否则保留原始的
        if self._preview_path and os.path.isfile(self._preview_path):
            ext = os.path.splitext(self._preview_path)[1].lower() or ".png"
            meta["preview_image"] = f"preview{ext}"
        elif self._orig_preview_name:
            meta["preview_image"] = self._orig_preview_name
        return meta

    def _validate(self) -> bool:
        if not self._mod_path:
            QMessageBox.warning(self, "提示", "请先打开一个模组文件")
            return False
        if not self.edit_id.text().strip():
            QMessageBox.warning(self, "必填", "请输入模组 ID")
            self.edit_id.setFocus()
            return False
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, "必填", "请输入模组名称")
            self.edit_name.setFocus()
            return False
        return True

    def _is_pak(self, path: str = None) -> bool:
        """判断给定路径（默认当前打开的文件）是否为 .tksmodpak 合集格式。"""
        p = path or self._mod_path
        return os.path.splitext(p)[1].lower() == ".tksmodpak"

    def _on_save(self):
        if not self._validate():
            return
        if self._is_pak():
            ok, msg = self._save_tksmodpak(self._mod_path)
        else:
            ok, msg = self._save_with_preview(self._mod_path)
        if ok:
            QMessageBox.information(self, "保存成功", f"已更新元数据:\n{self._mod_path}")
        else:
            QMessageBox.critical(self, "保存失败", msg)

    def _on_save_as(self):
        if not self._validate():
            return
        default = os.path.join(self._mods_dir, os.path.basename(self._mod_path))
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default,
            "TKS 模组文件 (*.tksmod *.tksmodpak);;所有文件 (*)"
        )
        if not path:
            return
        if self._is_pak(path):
            ok, msg = self._save_tksmodpak(path)
        else:
            ok, msg = self._save_with_preview(path)
        if ok:
            QMessageBox.information(self, "保存成功", f"已另存为:\n{path}")
        else:
            QMessageBox.critical(self, "保存失败", msg)

    def _save_with_preview(self, output_path: str) -> tuple[bool, str]:
        """保存 .tksmod，支持替换/删除预览图。保留原有数据/资源文件不变。"""
        new_meta = self._collect_metadata()
        old_preview = self._orig_preview_name  # 旧预览图文件名（在 ZIP 内）
        new_preview = self._preview_path        # 新选择的本地图片路径
        # 若用户清除了预览，或换了新图，跳过旧预览图文件
        has_new = bool(new_preview and os.path.isfile(new_preview))
        skip_old_preview = old_preview and (has_new or not new_meta.get("preview_image"))
        tmp = output_path + ".tmp"
        try:
            with zipfile.ZipFile(self._mod_path, 'r') as src, \
                 zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
                # 读取原始 mod.json，在其基础上合并用户编辑的字段
                orig_mj = json.loads(src.read("mod.json").decode('utf-8'))
                orig_mj.update(new_meta)
                # 强制保留格式标识
                orig_mj["format"] = "TKSMOD"
                orig_mj["format_version"] = 1
                dst.writestr("mod.json",
                             json.dumps(orig_mj, ensure_ascii=False, indent=2))
                # 复制其他文件（跳过旧预览图和 mod.json）
                skip_names = {"mod.json"}
                if skip_old_preview:
                    skip_names.add(old_preview)
                for item in src.infolist():
                    if item.filename in skip_names:
                        continue
                    dst.writestr(item, src.read(item.filename))
                # 写入新预览图
                if has_new:
                    preview_name = new_meta.get("preview_image", "preview.png")
                    dst.write(new_preview, preview_name)
            os.replace(tmp, output_path)
            return True, "保存成功"
        except Exception as e:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False, f"保存失败: {e}"

    def _save_tksmodpak(self, path: str) -> tuple[bool, str]:
        """写入 .tksmodpak 的 mod.json 元数据，支持替换/删除预览图。保留 .tksmod 文件不变。"""
        new_meta = self._collect_metadata()
        old_preview = self._orig_preview_name
        new_preview = self._preview_path
        has_new = bool(new_preview and os.path.isfile(new_preview))
        skip_old_preview = old_preview and (has_new or not new_meta.get("preview_image"))
        try:
            tmp = path + ".tmp"
            with zipfile.ZipFile(path, 'r') as src, \
                 zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
                # 读取原始 mod.json，在其基础上合并用户编辑的字段
                orig_mj = json.loads(src.read("mod.json").decode('utf-8'))
                orig_mj.update(new_meta)
                # 强制保留格式标识
                orig_mj["format"] = "TKSMODPAK"
                orig_mj["format_version"] = 1
                dst.writestr("mod.json",
                            json.dumps(orig_mj, ensure_ascii=False, indent=2))
                skip_names = {"mod.json"}
                if skip_old_preview:
                    skip_names.add(old_preview)
                for item in src.infolist():
                    if item.filename in skip_names:
                        continue
                    dst.writestr(item, src.read(item.filename))
                # 写入新预览图
                if has_new:
                    preview_name = new_meta.get("preview_image", "preview.png")
                    dst.write(new_preview, preview_name)
            os.replace(tmp, path)
            return True, "保存成功"
        except Exception as e:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False, f"保存失败: {e}"

    def _regen_id(self):
        """重新生成模组 ID（直接覆盖）。"""
        self.edit_id.setText(generate_short_uuid())
        self.edit_id.setFocus()

    def _on_pick_preview(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择预览图", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)")
        if path:
            self._preview_path = path
            self._lbl_preview_name.setText(os.path.basename(path))
            pm = QPixmap(path)
            if not pm.isNull():
                scaled = pm.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._lbl_preview_thumb.setPixmap(scaled)
            else:
                self._lbl_preview_thumb.setText("无法加载")

    def _on_clear_preview(self):
        self._preview_path = ""
        self._orig_preview_name = ""
        self._lbl_preview_thumb.clear()
        self._lbl_preview_thumb.setText("无预览图")
        self._lbl_preview_name.setText("<i style='color:#888'>未选择图片</i>")

    def _on_id_text_changed(self, text: str):
        """实时移除模组 ID 中的所有空格（前后及中间），保持光标位置不跳变。"""
        if ' ' not in text:
            return
        cursor = self.edit_id.cursorPosition()
        spaces_before = text[:cursor].count(' ')
        no_space = text.replace(' ', '')
        self.edit_id.blockSignals(True)
        self.edit_id.setText(no_space)
        self.edit_id.blockSignals(False)
        self.edit_id.setCursorPosition(max(0, cursor - spaces_before))
