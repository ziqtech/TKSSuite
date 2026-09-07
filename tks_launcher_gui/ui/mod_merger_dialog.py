"""模组合并对话框 — 将多个 .tksmod 深度合并为一个 .tksmod

与「模组打包」(生成 .tksmodpak 合集, 不合并内容) 不同:
本对话框在数据文件级深度合并 —— 多个模组若改动同一游戏文件(如都改 Mu.JVG)
的不同帧 / 记录 / 条目, 会被合并进同一个数据文件; 改动同一处时后者生效。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from core.mod_merger import (
    analyze_merge, deep_merge_tksmods, suggest_merge_output_name,
)
from core.mod_packer import list_tksmod_contents, read_tksmod_content
from editor_utils import theme_tokens as _tt_tokens
_PLACEHOLDER_GRAY = _tt_tokens.business_colors("launcher", _tt_tokens.THEMES[0])["placeholder_gray"]
from editor_utils.mod_exporter import generate_short_uuid
from editor_utils.ui_helpers import themed_question, clamp_dialog_size
from editor_utils.task_runner import run_background, is_running
from editor_utils.ui_helpers import EditorComboBox

# 差异类别 -> 中文显示 / 悬停详情 (列宽有限, 长说明放 tooltip)
_KIND_LABEL = {
    "block": "帧/块",
    "grp_layer": "图层",
    "record": "记录",
    "text": "文本",
    "resource": "资源",
    "unknown": "未知",
}
_KIND_TIP = {
    "block": "帧/块合并 (JVG·动作·GRP 整段)",
    "grp_layer": "图层像素合并 (GRP)",
    "record": "记录合并 (数值表)",
    "text": "文本合并 (剧情·文本表)",
    "resource": "资源整文件替换",
    "unknown": "未知类型",
}


class ModMergerDialog(QDialog):
    """模组合并对话框 — 选择多个 .tksmod, 深度合并为一个 .tksmod。"""

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self.setWindowTitle("模组合并 — 将多个 .tksmod 深度合并为一个")
        # 双栏布局内容最小高度 ~640 逻辑像素, 钳制到屏幕可用区域内
        clamp_dialog_size(self, 950, 700)
        self._mods_dir = mods_dir
        self._file_paths: list[str] = []
        self._preview_path: str = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- 主体双栏: 左 = 文件列表 + 合并分析, 右 = 元数据 + 输出 + 日志 ----
        # (单栏堆叠时最小高度 ~1140, 1080p 下超屏; 双栏后 ~640, 各缩放档位均可容纳)
        body = QHBoxLayout()
        body.setSpacing(10)

        # ---- 左栏 · 文件列表区 ----
        file_group = QGroupBox("源文件列表 (将深度合并为一个 .tksmod)")
        file_layout = QVBoxLayout(file_group)

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_list.setMinimumHeight(90)
        file_layout.addWidget(self._file_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("添加文件")
        btn_add.clicked.connect(self._on_add_files)
        btn_row.addWidget(btn_add)
        btn_add_dir = QPushButton("从目录添加")
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

        # 左栏容器: 文件列表 + 合并分析 纵向堆叠
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        left_col.addWidget(file_group, 2)

        # ---- 左栏 · 合并分析区 ----
        analysis_group = QGroupBox("合并分析 (按目标游戏文件汇总)")
        analysis_layout = QVBoxLayout(analysis_group)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["目标文件", "合并方式", "来源数", "改动数", "重叠(后者生效)"])
        self._tree.setRootIsDecorated(False)
        self._tree.setMinimumHeight(110)
        # 列宽用固定初值 + 首列拉伸 (ResizeToContents 会被长标签撑出横向滚动条)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 96), (2, 56), (3, 56), (4, 100)):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self._tree.setColumnWidth(col, width)
        analysis_layout.addWidget(self._tree)
        self._lbl_summary = QLabel("请添加要合并的 .tksmod 文件")
        self._lbl_summary.setWordWrap(True)
        analysis_layout.addWidget(self._lbl_summary)
        left_col.addWidget(analysis_group, 3)
        body.addLayout(left_col, 3)

        # ---- 右栏 · 元数据区 ----
        right_col = QVBoxLayout()
        right_col.setSpacing(10)
        meta_group = QGroupBox("合并后模组元数据")
        grid = QGridLayout(meta_group)
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("模组 ID *:"), row, 0)
        id_row = QHBoxLayout()
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("唯一标识符, 如 merged_visual")
        self.edit_id.setMaxLength(16)
        self.edit_id.textChanged.connect(self._on_id_text_changed)
        id_row.addWidget(self.edit_id)
        self.btn_regen_id = QPushButton("重新生成")
        self.btn_regen_id.clicked.connect(self._regen_id)
        id_row.addWidget(self.btn_regen_id)
        grid.addLayout(id_row, row, 1)

        row += 1
        grid.addWidget(QLabel("名称 *:"), row, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("合并后模组的显示名称")
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
        self.edit_desc.setMaximumHeight(52)
        self.edit_desc.setPlaceholderText("模组简介，描述合并内容")
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

        row += 1
        grid.addWidget(QLabel("预览图:"), row, 0, Qt.AlignTop)
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
        _preview_info.setSpacing(6)
        self._lbl_preview_name = QLabel(f"<i style='color:{_PLACEHOLDER_GRAY}'>未选择图片</i>")
        self._lbl_preview_name.setWordWrap(True)
        _preview_info.addWidget(self._lbl_preview_name)
        _pv_btn_row = QHBoxLayout()
        _pv_btn_row.setSpacing(8)
        _btn_pick = QPushButton("选择图片")
        _btn_pick.setFixedWidth(100)
        _btn_pick.clicked.connect(self._on_pick_preview)
        _pv_btn_row.addWidget(_btn_pick)
        _btn_clear_pv = QPushButton("清除")
        _btn_clear_pv.setFixedWidth(60)
        _btn_clear_pv.clicked.connect(self._on_clear_preview)
        _pv_btn_row.addWidget(_btn_clear_pv)
        _pv_btn_row.addStretch()
        _preview_info.addLayout(_pv_btn_row)
        _preview_info.addStretch()
        _preview_card.addLayout(_preview_info, 1)
        grid.addLayout(_preview_card, row, 1)
        right_col.addWidget(meta_group)

        # ---- 右栏 · 输出区 ----
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出文件:"))
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("输出的 .tksmod 文件路径")
        out_row.addWidget(self.edit_output, 1)
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._on_browse_output)
        out_row.addWidget(btn_browse)
        right_col.addLayout(out_row)

        # ---- 右栏 · 日志 ----
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMinimumHeight(54)
        self._log_area.setPlaceholderText("合并日志将显示在这里...")
        right_col.addWidget(self._log_area, 1)

        body.addLayout(right_col, 2)
        layout.addLayout(body, 1)

        # ---- 进度 ----
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ---- 底部按钮 ----
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self.btn_merge = QPushButton("执行合并")
        btn_merge = self.btn_merge
        btn_merge.setObjectName("btnPack")
        btn_merge.clicked.connect(self._on_merge)
        bottom_row.addWidget(btn_merge)
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
        existing = set(self._file_paths)
        for fp in file_paths:
            if fp in existing:
                continue
            self._file_paths.append(fp)
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
        self._refresh_analysis()

    def _on_remove_selected(self):
        for item in self._file_list.selectedItems():
            row = self._file_list.row(item)
            self._file_list.takeItem(row)
            if row < len(self._file_paths):
                self._file_paths.pop(row)
        self._update_count()
        self._refresh_analysis()

    def _on_clear(self):
        self._file_list.clear()
        self._file_paths.clear()
        self._update_count()
        self._refresh_analysis()

    def _update_count(self):
        self._lbl_count.setText(f"共 {len(self._file_paths)} 个文件")

    # ────────────────────────────────────────────────
    # 合并分析
    # ────────────────────────────────────────────────

    def _refresh_analysis(self):
        self._tree.clear()
        if not self._file_paths:
            self._lbl_summary.setText("请添加要合并的 .tksmod 文件")
            return

        info = analyze_merge(self._file_paths)
        if not info.get("valid"):
            self._lbl_summary.setText(f"无法分析: {info.get('error', '')}")
            return

        targets = info.get("targets", [])
        merged_targets = sum(1 for t in targets if len(t["sources"]) > 1)
        total_overlap = sum(len(t["overlap"]) for t in targets)

        for t in targets:
            n_src = len(t["sources"])
            overlap = t["overlap"]
            ov_text = "—"
            if overlap:
                shown = ", ".join(str(x) for x in overlap[:8])
                ov_text = shown + (" …" if len(overlap) > 8 else "")
            total_text = "—" if t["is_resource"] else str(t["total"])
            item = QTreeWidgetItem([
                t["target"],
                _KIND_LABEL.get(t["kind"], t["kind"]),
                str(n_src),
                total_text,
                ov_text,
            ])
            tip = "来源: " + "、".join(t["sources"])
            item.setToolTip(0, tip)
            item.setToolTip(1, _KIND_TIP.get(t["kind"], ""))
            # 多来源合并的目标高亮; 有重叠的更醒目
            if overlap:
                item.setForeground(4, Qt.red)
            if n_src > 1:
                item.setForeground(2, Qt.darkGreen)
            self._tree.addTopLevelItem(item)

        parts = [f"{len(self._file_paths)} 个文件 → {len(targets)} 个目标文件"]
        if merged_targets:
            parts.append(f"其中 {merged_targets} 个目标由多模组合并")
        if total_overlap:
            parts.append(f"⚠ 共 {total_overlap} 处改动重叠(后加入者生效)")
        else:
            parts.append("无重叠冲突，改动可完全共存")
        self._lbl_summary.setText("；".join(parts))

    # ────────────────────────────────────────────────
    # 元数据
    # ────────────────────────────────────────────────

    def _auto_fill_metadata(self):
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
        if descs and not self.edit_desc.toPlainText().strip():
            self.edit_desc.setPlainText("\n---\n".join(descs))

    def _regen_id(self):
        self.edit_id.setText(generate_short_uuid())
        self.edit_id.setFocus()

    def _on_id_text_changed(self, text: str):
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
                scaled = pm.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._lbl_preview_thumb.setPixmap(scaled)
            else:
                self._lbl_preview_thumb.setText("无法加载")

    def _on_clear_preview(self):
        self._preview_path = ""
        self._lbl_preview_thumb.clear()
        self._lbl_preview_thumb.setText("无预览图")
        self._lbl_preview_name.setText(f"<i style='color:{_PLACEHOLDER_GRAY}'>未选择图片</i>")

    # ────────────────────────────────────────────────
    # 输出路径
    # ────────────────────────────────────────────────

    def _on_browse_output(self):
        suggested = suggest_merge_output_name(self._get_metadata())
        default_path = os.path.join(self._mods_dir, suggested)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并后的 .tksmod 文件", default_path,
            "TKS 模组文件 (*.tksmod);;所有文件 (*)"
        )
        if path:
            self.edit_output.setText(path)

    # ────────────────────────────────────────────────
    # 合并
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

    def _on_merge(self):
        if len(self._file_paths) < 2:
            QMessageBox.warning(self, "提示", "请至少添加 2 个 .tksmod 文件进行合并")
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

        output = self.edit_output.text().strip()
        if not output:
            output = os.path.join(self._mods_dir, suggest_merge_output_name(metadata))
            self.edit_output.setText(output)
        if not output.lower().endswith(".tksmod"):
            output += ".tksmod"
            self.edit_output.setText(output)

        # 避免输出覆盖某个源文件
        norm_out = os.path.normcase(os.path.abspath(output))
        for fp in self._file_paths:
            if os.path.normcase(os.path.abspath(fp)) == norm_out:
                QMessageBox.warning(
                    self, "路径冲突",
                    "输出文件与某个源文件相同，请更换输出文件名以免覆盖源模组。")
                return

        if os.path.isfile(output):
            ret = themed_question(
                self, "确认覆盖",
                f"文件已存在:\n{output}\n\n是否覆盖？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        self._log_area.clear()
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self.btn_merge.setEnabled(False)

        def log(msg):
            self._log_area.append(msg)

        log(f"开始深度合并 {len(self._file_paths)} 个 .tksmod 文件...")
        log(f"输出: {output}")
        log("")

        # 后台线程执行深度合并 (P3-3): 日志经信号排队回 UI 线程
        file_paths, preview_path = list(self._file_paths), self._preview_path

        def work(w):
            return deep_merge_tksmods(
                file_paths, output, metadata,
                preview_image_path=preview_path, log_func=w.progress)

        self._merge_worker = run_background(
            self, work,
            on_success=self._on_merge_done,
            on_progress=log)

    def _on_merge_done(self, result):
        self._progress.setVisible(False)
        self.btn_merge.setEnabled(True)
        output = self.edit_output.text().strip()

        def log(msg):
            self._log_area.append(msg)

        if result.success:
            for w in result.warnings:
                log(w)
            log(f"\n✅ 合并完成！{result.total_components} 个组件, "
                f"{result.total_resources} 个资源")
            warn_text = ""
            if result.warnings:
                warn_text = ("\n\n注意事项:\n" +
                             "\n".join("• " + w.replace("[WARN] ", "")
                                       for w in result.warnings[:12]))
                if len(result.warnings) > 12:
                    warn_text += f"\n… 其余 {len(result.warnings) - 12} 条见日志"
            QMessageBox.information(
                self, "合并成功",
                f"已将 {len(self._file_paths)} 个模组深度合并为:\n\n"
                f"{os.path.basename(output)}\n\n"
                f"组件 {result.total_components} 个 · 资源 {result.total_resources} 个"
                + warn_text)
        else:
            log(f"\n❌ 合并失败: {result.error}")
            QMessageBox.critical(self, "合并失败", result.error)
