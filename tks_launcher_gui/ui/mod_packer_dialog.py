"""模组打包对话框 — 将多个 .tksmod 打包为一个 .tksmodpak 合集文件"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout,
)

from core.mod_packer import (
    create_tksmodpak, list_tksmod_contents, read_tksmod_content,
    suggest_output_name,
)
from editor_utils.mod_exporter import generate_short_uuid
from editor_utils.ui_helpers import EditorComboBox


class ModPackerDialog(QDialog):
    """模组打包对话框 — 选择多个 .tksmod 文件，设置合集元数据后打包为 .tksmodpak"""

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self.setWindowTitle("模组打包 — 将多个 .tksmod 打包为合集文件")
        self.resize(700, 620)
        self._mods_dir = mods_dir
        self._file_paths: list[str] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- 文件列表区 ----
        file_group = QGroupBox("源文件列表 (将打包为一个 .tksmodpak)")
        file_layout = QVBoxLayout(file_group)

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_list.setMinimumHeight(160)
        file_layout.addWidget(self._file_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("添加文件...")
        btn_add.clicked.connect(self._on_add_files)
        btn_row.addWidget(btn_add)

        btn_add_dir = QPushButton("从目录添加...")
        btn_add_dir.clicked.connect(self._on_add_from_dir)
        btn_row.addWidget(btn_add_dir)

        btn_remove = QPushButton("移除选中")
        btn_remove.clicked.connect(self._on_remove_selected)
        btn_row.addWidget(btn_remove)

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(btn_clear)

        btn_row.addStretch()
        self._lbl_count = QLabel("共 0 个文件")
        btn_row.addWidget(self._lbl_count)
        file_layout.addLayout(btn_row)

        layout.addWidget(file_group)

        # ---- 元数据区 ----
        meta_group = QGroupBox("合集元数据")
        grid = QGridLayout(meta_group)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("模组 ID *:"), row, 0)
        id_row = QHBoxLayout()
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("唯一标识符, 如 zhangxiu_mod")
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
        self.edit_name.setPlaceholderText("模组显示名称, 如 张绣传")
        grid.addWidget(self.edit_name, row, 1)

        row += 1
        grid.addWidget(QLabel("版本:"), row, 0)
        self.edit_version = QLineEdit("1.0.0")
        grid.addWidget(self.edit_version, row, 1)

        row += 1
        grid.addWidget(QLabel("作者:"), row, 0)
        self.edit_author = QLineEdit()
        grid.addWidget(self.edit_author, row, 1)

        row += 1
        grid.addWidget(QLabel("描述:"), row, 0)
        self.edit_desc = QTextEdit()
        self.edit_desc.setMaximumHeight(60)
        self.edit_desc.setPlaceholderText("模组简介，描述修改内容")
        grid.addWidget(self.edit_desc, row, 1)

        row += 1
        grid.addWidget(QLabel("类型:"), row, 0)
        self.combo_type = EditorComboBox()
        self.combo_type.addItems(["mixed", "data", "story", "visual"])
        grid.addWidget(self.combo_type, row, 1)

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        self.spin_order.setValue(100)
        grid.addWidget(self.spin_order, row, 1)

        # 预览图行
        row += 1
        grid.addWidget(QLabel("预览图:"), row, 0, Qt.AlignTop)
        self._preview_path: str = ""
        _preview_card = QHBoxLayout()
        _preview_card.setContentsMargins(0, 4, 0, 4)
        _preview_card.setSpacing(14)
        self._lbl_preview_thumb = QLabel()
        self._lbl_preview_thumb.setObjectName("previewThumb")
        self._lbl_preview_thumb.setFixedSize(120, 120)
        self._lbl_preview_thumb.setAlignment(Qt.AlignCenter)
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

        layout.addWidget(meta_group)

        # ---- 输出区 ----
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出文件:"))
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("输出的 .tksmodpak 文件路径")
        out_row.addWidget(self.edit_output, 1)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse_output)
        out_row.addWidget(btn_browse)
        layout.addLayout(out_row)

        # ---- 进度和日志 ----
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMaximumHeight(100)
        self._log_area.setPlaceholderText("合并日志将显示在这里...")
        layout.addWidget(self._log_area)

        # ---- 底部按钮 ----
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        btn_pack = QPushButton("📦 执行打包")
        btn_pack.setObjectName("btnPack")
        btn_pack.clicked.connect(self._on_pack)
        bottom_row.addWidget(btn_pack)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        bottom_row.addWidget(btn_close)

        layout.addLayout(bottom_row)

    # ────────────────────────────────────────────────
    # 文件操作
    # ────────────────────────────────────────────────

    def _on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 .tksmod 文件", self._mods_dir,
            "TKS 模组文件 (*.tksmod);;所有文件 (*)"
        )
        if files:
            self._add_files(files)

    def _on_add_from_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择包含 .tksmod 文件的目录", self._mods_dir
        )
        if dir_path:
            files = [os.path.join(dir_path, f)
                     for f in sorted(os.listdir(dir_path))
                     if f.lower().endswith('.tksmod')]
            if files:
                self._add_files(files)
            else:
                QMessageBox.information(self, "提示", "该目录中未找到 .tksmod 文件")

    def _add_files(self, file_paths: list[str]):
        """添加文件到列表（去重）"""
        existing = set(self._file_paths)
        for fp in file_paths:
            if fp not in existing:
                self._file_paths.append(fp)
                # 读取内容预览
                info = list_tksmod_contents(fp)
                filename = os.path.basename(fp)
                if info.get("valid"):
                    comps = info.get("components", [])
                    targets = [c.get("target", "?") for c in comps]
                    label = f"{filename}  →  {', '.join(targets)}" if targets else filename
                else:
                    label = f"{filename}  [无效: {info.get('error', '')}]"

                item = QListWidgetItem(label)
                item.setToolTip(fp)
                self._file_list.addItem(item)

        self._update_count()
        self._auto_fill_metadata()

    def _on_remove_selected(self):
        for item in self._file_list.selectedItems():
            row = self._file_list.row(item)
            self._file_list.takeItem(row)
            if row < len(self._file_paths):
                self._file_paths.pop(row)
        self._update_count()

    def _on_clear(self):
        self._file_list.clear()
        self._file_paths.clear()
        self._update_count()

    def _update_count(self):
        self._lbl_count.setText(f"共 {len(self._file_paths)} 个文件")

    def _auto_fill_metadata(self):
        """从已添加的模组文件自动填充元数据（仅当字段为空时）。

        ID/名称/作者取自第一个有效文件；描述合并所有文件的描述。
        """
        if not self._file_paths:
            return
        first_valid = None
        descs = []
        for fp in self._file_paths:
            content = read_tksmod_content(fp)
            if not content.valid:
                continue
            mj = content.mod_json
            if first_valid is None:
                first_valid = mj
            desc = mj.get("description", "").strip()
            if desc:
                descs.append(desc)

        if first_valid is None:
            return

        if not self.edit_id.text().strip():
            mod_id = first_valid.get("id", "")
            if mod_id:
                base_id = mod_id.rsplit('_', 1)[0] if '_' in mod_id else mod_id
                self.edit_id.setText(base_id)
        if not self.edit_name.text().strip():
            self.edit_name.setText(first_valid.get("name", ""))
        if not self.edit_author.text().strip():
            self.edit_author.setText(first_valid.get("author", ""))

        # 合并所有模组描述到描述输入框
        if descs and not self.edit_desc.toPlainText().strip():
            self.edit_desc.setPlainText("\n---\n".join(descs))

    def _regen_id(self):
        """重新生成模组 ID（直接覆盖）。"""
        self.edit_id.setText(generate_short_uuid())
        self.edit_id.setFocus()

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

    # ────────────────────────────────────────────────
    # 预览图
    # ────────────────────────────────────────────────

    _PREVIEW_IMG_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)"

    def _on_pick_preview(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择预览图", "", self._PREVIEW_IMG_FILTER)
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
        self._lbl_preview_thumb.clear()
        self._lbl_preview_thumb.setText("无预览图")
        self._lbl_preview_name.setText("<i style='color:#888'>未选择图片</i>")

    # ────────────────────────────────────────────────
    # 输出路径
    # ────────────────────────────────────────────────

    def _on_browse_output(self):
        suggested = suggest_output_name(self._file_paths, self._get_metadata())
        default_path = os.path.join(self._mods_dir, suggested)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 .tksmodpak 合集文件", default_path,
            "TKS 模组合集 (*.tksmodpak);;所有文件 (*)"
        )
        if path:
            self.edit_output.setText(path)

    # ────────────────────────────────────────────────
    # 打包
    # ────────────────────────────────────────────────

    def _get_metadata(self) -> dict:
        return {
            "id": self.edit_id.text().strip(),
            "name": self.edit_name.text().strip(),
            "version": self.edit_version.text().strip() or "1.0.0",
            "author": self.edit_author.text().strip(),
            "description": self.edit_desc.toPlainText().strip(),
            "type": self.combo_type.currentText(),
            "mode": "mixed",
            "load_order": self.spin_order.value(),
            "preview_image_path": self._preview_path,
        }

    def _on_pack(self):
        if not self._file_paths:
            QMessageBox.warning(self, "提示", "请先添加要打包的 .tksmod 文件")
            return

        metadata = self._get_metadata()
        if not metadata["id"]:
            QMessageBox.warning(self, "必填", "请输入模组 ID")
            self.edit_id.setFocus()
            return
        if not metadata["name"]:
            QMessageBox.warning(self, "必填", "请输入模组名称")
            self.edit_name.setFocus()
            return

        # 确定输出路径
        output = self.edit_output.text().strip()
        if not output:
            suggested = suggest_output_name(self._file_paths, metadata)
            output = os.path.join(self._mods_dir, suggested)
            self.edit_output.setText(output)
        if not output.lower().endswith(".tksmodpak"):
            output += ".tksmodpak"
            self.edit_output.setText(output)

        # 确认覆盖
        if os.path.isfile(output):
            ret = QMessageBox.question(
                self, "确认覆盖",
                f"文件已存在:\n{output}\n\n是否覆盖？",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        # 执行打包
        self._log_area.clear()
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)

        def log(msg):
            self._log_area.append(msg)

        log(f"开始打包 {len(self._file_paths)} 个 .tksmod 文件...")
        log(f"输出: {output}")
        log("")

        ok, msg = create_tksmodpak(
            self._file_paths, output, metadata,
            preview_image_path=self._preview_path,
            log_func=log)

        self._progress.setVisible(False)

        if ok:
            log(f"\n✅ {msg}")
            QMessageBox.information(
                self, "打包成功",
                f"已成功将 {len(self._file_paths)} 个文件打包为:\n\n"
                f"{os.path.basename(output)}\n\n"
                f"可通过「模组拆分」功能还原原始文件。"
            )
        else:
            log(f"\n❌ {msg}")
            QMessageBox.critical(self, "打包失败", msg)
