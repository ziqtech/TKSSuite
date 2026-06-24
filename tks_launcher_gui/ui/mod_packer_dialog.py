"""MOD 打包器对话框 — 将多个 .tksmod 合并为一个统一 MOD 包"""
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QGroupBox, QProgressBar, QAbstractItemView,
)
from PySide6.QtCore import Qt

from core.mod_packer import (
    read_tksmod_content, validate_merge, merge_tksmod_files,
    suggest_output_name, list_tksmod_contents,
)


class ModPackerDialog(QDialog):
    """MOD 打包对话框 — 选择多个 .tksmod 文件，设置统一元数据后合并为一个"""

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self.setWindowTitle("MOD 打包器 — 合并多个 .tksmod 为一个 MOD 包")
        self.resize(700, 620)
        self._mods_dir = mods_dir
        self._file_paths: list[str] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- 文件列表区 ----
        file_group = QGroupBox("源文件列表 (将合并为一个 MOD 包)")
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
        meta_group = QGroupBox("MOD 包元数据 (合并后的统一信息)")
        grid = QGridLayout(meta_group)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("MOD ID *:"), row, 0)
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("唯一标识符, 如 zhangxiu_mod")
        grid.addWidget(self.edit_id, row, 1)

        row += 1
        grid.addWidget(QLabel("名称 *:"), row, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("MOD 显示名称, 如 张绣传")
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
        self.edit_desc.setPlaceholderText("MOD 简介，描述修改内容")
        grid.addWidget(self.edit_desc, row, 1)

        row += 1
        grid.addWidget(QLabel("类型:"), row, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["mixed", "data", "story", "visual"])
        grid.addWidget(self.combo_type, row, 1)

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        self.spin_order.setValue(100)
        grid.addWidget(self.spin_order, row, 1)

        layout.addWidget(meta_group)

        # ---- 输出区 ----
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出文件:"))
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("合并后的 .tksmod 文件路径")
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

        btn_validate = QPushButton("验证兼容性")
        btn_validate.clicked.connect(self._on_validate)
        bottom_row.addWidget(btn_validate)

        btn_pack = QPushButton("🔗 执行合并")
        btn_pack.setObjectName("btnPack")
        btn_pack.setStyleSheet("font-weight: bold; padding: 6px 20px;")
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
            "TKS MOD 文件 (*.tksmod);;所有文件 (*)"
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
        """从第一个有效文件自动填充元数据（仅当字段为空时）"""
        if not self._file_paths:
            return
        for fp in self._file_paths:
            content = read_tksmod_content(fp)
            if content.valid:
                mj = content.mod_json
                if not self.edit_id.text().strip():
                    # 从 mod_id 推导包 ID
                    mod_id = mj.get("id", "")
                    if mod_id:
                        # 去除可能的后缀如 _kon, _act 等
                        base_id = mod_id.rsplit('_', 1)[0] if '_' in mod_id else mod_id
                        self.edit_id.setText(base_id)
                if not self.edit_name.text().strip():
                    self.edit_name.setText(mj.get("name", ""))
                if not self.edit_author.text().strip():
                    self.edit_author.setText(mj.get("author", ""))
                break

    # ────────────────────────────────────────────────
    # 输出路径
    # ────────────────────────────────────────────────

    def _on_browse_output(self):
        suggested = suggest_output_name(self._file_paths, self._get_metadata())
        default_path = os.path.join(self._mods_dir, suggested)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并后的 MOD 包", default_path,
            "TKS MOD 文件 (*.tksmod);;所有文件 (*)"
        )
        if path:
            self.edit_output.setText(path)

    # ────────────────────────────────────────────────
    # 验证和打包
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
        }

    def _on_validate(self):
        if not self._file_paths:
            QMessageBox.warning(self, "提示", "请先添加要合并的 .tksmod 文件")
            return

        self._log_area.clear()
        can_merge, warnings = validate_merge(self._file_paths)

        if warnings:
            for w in warnings:
                self._log_area.append(w)
        else:
            self._log_area.append("✅ 所有文件兼容，可以合并")

        if can_merge:
            self._log_area.append(f"\n验证通过: {len(self._file_paths)} 个文件可以合并")
        else:
            self._log_area.append("\n❌ 验证失败，请修复错误后重试")

    def _on_pack(self):
        # 基本验证
        if not self._file_paths:
            QMessageBox.warning(self, "提示", "请先添加要合并的 .tksmod 文件")
            return

        metadata = self._get_metadata()
        if not metadata["id"]:
            QMessageBox.warning(self, "必填", "请输入 MOD ID")
            self.edit_id.setFocus()
            return
        if not metadata["name"]:
            QMessageBox.warning(self, "必填", "请输入 MOD 名称")
            self.edit_name.setFocus()
            return

        # 确定输出路径
        output = self.edit_output.text().strip()
        if not output:
            suggested = suggest_output_name(self._file_paths, metadata)
            output = os.path.join(self._mods_dir, suggested)
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

        # 执行合并
        self._log_area.clear()
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # 不确定进度

        def log(msg):
            self._log_area.append(msg)

        log(f"开始合并 {len(self._file_paths)} 个 .tksmod 文件...")
        log(f"输出: {output}")
        log("")

        result = merge_tksmod_files(self._file_paths, output, metadata, log_func=log)

        self._progress.setVisible(False)

        if result.success:
            log(f"\n✅ 合并成功！")
            log(f"   组件数: {result.total_components}")
            log(f"   资源数: {result.total_resources}")
            if result.warnings:
                log(f"   警告: {len(result.warnings)} 条")

            QMessageBox.information(
                self, "合并成功",
                f"已成功将 {len(self._file_paths)} 个文件合并为:\n\n"
                f"{os.path.basename(output)}\n\n"
                f"组件: {result.total_components}, 资源: {result.total_resources}\n\n"
                f"玩家只需将此文件放入 mods/ 目录即可使用。"
            )
        else:
            log(f"\n❌ 合并失败: {result.error}")
            QMessageBox.critical(self, "合并失败", result.error)
