"""
font_editor.py — FONT9696 字体编辑器主入口
================================================
功能:
  1. 创建字体: 选择 TTF + 简繁体 → 生成 FONT9696
  2. 字体预览: 加载 FONT9696, 预览 8 个 FTYPE 区段字形
  3. 导出 MOD: 将 FONT9696 打包为 .tksmod (resources 整体替换)
  4. 导入 MOD: 从 .tksmod 提取 FONT9696 字体文件

工程约定遵循 project_memory.md:
  - '关于(&A)' 菜单独立
  - '切换 Godot 主题' action 放在 '视图(&V)' 菜单
  - install_dialog_theme_filter 紧跟 QApplication 后调用
  - 主窗口暴露 _is_dark 属性供弹窗继承主题
  - functools.partial 替代 lambda
  - 版本号通过 editor_utils/version.py 统一管理
"""
import os
import sys
import shutil
import tempfile
import zipfile
from functools import partial
from pathlib import Path

# ── runtime bootstrap (必须在 PySide6 导入前) ──
_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_EDITOR_DIR, '..'))   # 
sys.path.insert(0, _EDITOR_DIR)                        # font_editor/
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize
from PySide6.QtGui import QAction, QIcon, QImage, QPixmap, QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGridLayout, QPushButton, QLabel, QLineEdit, QComboBox,
    QCheckBox, QFileDialog, QMessageBox, QGroupBox, QSpinBox, QProgressBar,
    QScrollArea, QFrame, QSplitter, QStatusBar, QListWidget, QListWidgetItem,
    QTextEdit,
)

from editor_utils.theme_manager import ThemeManager
from editor_utils.ui_helpers import install_dialog_theme_filter, themed_messagebox, NoWheelComboBox
from editor_utils.dock_components import create_dock
from editor_utils.app_init import install_translator, setup_app_icon
from editor_utils.version import format_title, format_about_header
from editor_utils.mod_exporter import (
    generate_mod_json, pack_tksmod, ModMetadataDialog, safe_mod_filename,
    read_tksmod,
)
from font9696_codec import Font9696
from ttf_converter import (
    generate_font9696_from_ttf, generate_font9696_multi_ttf,
)


# ── 预览示例文本 ──
PREVIEW_SAMPLES = [
    "三國群俠傳",
    "荀彧",
    "子青套件",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "~%！？。，、；：「」『』",
    "天下大事，分久必合，合久必分。",
]


# ── 后台生成线程 ──

class _ConvertWorker(QObject):
    """TTF → FONT9696 转换工作线程。"""
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(bool, str)       # success, message

    def __init__(self, ttf_paths: list[str], output_path: str,
                 ftype_assignments: dict[int, str], simplified: bool,
                 pixel_size: int, fallback_ttf: str | None = None):
        super().__init__()
        self._ttf_paths = ttf_paths
        self._output_path = output_path
        self._ftype_assignments = ftype_assignments
        self._simplified = simplified
        self._pixel_size = pixel_size
        self._fallback_ttf = fallback_ttf

    def run(self):
        try:
            if len(self._ftype_assignments) == 0:
                self.finished.emit(False, "未指定任何 FTYPE 区段")
                return

            ok, msg = generate_font9696_multi_ttf(
                self._ttf_paths,
                self._output_path,
                self._ftype_assignments,
                simplified=self._simplified,
                pixel_size=self._pixel_size,
                fallback_ttf=self._fallback_ttf,
                progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
            )
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, f"转换异常: {e}")


# ═══════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════

class FontEditorWindow(QMainWindow):
    """FONT9696 字体编辑器主窗口。"""

    def __init__(self):
        super().__init__()
        self.setObjectName("EditorWindow")
        self.setWindowTitle(format_title("font_editor"))
        self.resize(960, 580)
        self.setMinimumSize(820, 520)

        # 主题状态 (install_dialog_theme_filter 沿父链查找 _is_dark)
        app = QApplication.instance()
        self._is_dark = (app.styleHints().colorScheme() == Qt.ColorScheme.Dark
                         if app else False)

        # 当前打开的 FONT9696 文件
        self._font_path: str | None = None
        self._font_index: list[int] = []
        self._modified = False

        # 转换线程
        self._convert_thread: QThread | None = None
        self._convert_worker: _ConvertWorker | None = None

        # 创建字体页面控件
        self._ttf_list: QListWidget | None = None
        self._ftype_checks: list[QCheckBox] = []
        self._simplified_check: QCheckBox | None = None
        self._pixel_size_spin: QSpinBox | None = None
        self._convert_btn: QPushButton | None = None
        self._convert_progress: QProgressBar | None = None
        self._convert_status: QLabel | None = None

        # 预览页面控件
        self._preview_ftype_combo: QComboBox | None = None
        self._preview_path_label: QLabel | None = None
        self._preview_container: QWidget | None = None

        # 构建 UI
        self._build_ui()
        self._build_menu()
        self._build_statusbar()
        self._apply_theme()
        self._update_window_title()

    # ── UI 构建 ──

    def _build_ui(self):
        """构建主界面: QTabWidget 三个标签页。"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_create_tab(), "创建字体")
        tabs.addTab(self._build_preview_tab(), "字体预览")

        # Tab 栏右上角: 主题切换按钮
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        btn_theme.setProperty("class", "CompactBtn")
        corner_layout.addWidget(btn_theme)
        tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)

        self._tabs = tabs

    def _build_create_tab(self) -> QWidget:
        """构建"创建字体"标签页。

        左右双栏布局:
          左侧: TTF 字体文件
          右侧: 生成选项 (上) + FTYPE 区段 (中) + 生成 (下)
        """
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        main_splitter = QSplitter(Qt.Horizontal)

        # ════════ 左侧面板 ════════
        # ── TTF 字体文件 ──
        ttf_content = QWidget()
        ttf_layout = QVBoxLayout(ttf_content)
        ttf_layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加 TTF…")
        add_btn.clicked.connect(self._on_add_ttf)
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self._on_remove_ttf)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._on_clear_ttf)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        ttf_layout.addLayout(btn_row)

        self._ttf_list = QListWidget()
        ttf_layout.addWidget(self._ttf_list)

        main_splitter.addWidget(create_dock("TTF 字体文件", ttf_content))
        # 左侧 TTF 列表吸收所有垂直空间, 右侧面板均为固定高度

        # ════════ 右侧面板 (固定内容, 用 QVBoxLayout 排列) ════════
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # ── 生成选项 ──
        opt_content = QWidget()
        opt_layout = QFormLayout(opt_content)
        opt_layout.setContentsMargins(0, 0, 0, 0)
        opt_layout.setSpacing(6)

        # 简繁体
        self._simplified_check = QCheckBox("简体字形 (取消勾选则生成繁体)")
        self._simplified_check.setChecked(True)
        opt_layout.addRow("字符集:", self._simplified_check)

        # 像素大小
        self._pixel_size_spin = QSpinBox()
        self._pixel_size_spin.setRange(40, 95)
        self._pixel_size_spin.setValue(80)
        self._pixel_size_spin.setSuffix(" px")
        opt_layout.addRow("渲染像素大小:", self._pixel_size_spin)

        # 回退字体 (主字体缺字时使用)
        self._fallback_combo = NoWheelComboBox()
        self._fallback_combo.addItem("(不使用回退)", None)
        opt_layout.addRow("回退字体:", self._fallback_combo)

        right_layout.addWidget(create_dock("生成选项", opt_content))

        # ── FTYPE 区段 (4行×2列布局) ──
        ftype_content = QWidget()
        ftype_grid = QGridLayout(ftype_content)
        ftype_grid.setHorizontalSpacing(16)
        ftype_grid.setVerticalSpacing(6)
        ftype_grid.setContentsMargins(0, 0, 0, 0)

        # 8 个 FTYPE, 4行×2列
        self._ftype_checks = []
        self._ftype_ttf_combos: list[QComboBox] = []
        ftype_names = [
            "FTYPE 0", "FTYPE 1", "FTYPE 2", "FTYPE 3",
            "FTYPE 4", "FTYPE 5", "FTYPE 6", "FTYPE 7",
        ]
        for i, name in enumerate(ftype_names):
            row = i // 2      # 0-3
            col = i % 2       # 0 或 1
            # 每列: 勾选框 (固定宽) + 下拉框 (stretch)
            col_widget = QWidget()
            col_layout = QHBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(8)

            chk = QCheckBox(name)
            chk.setFixedWidth(80)
            chk.setChecked(True)   # 默认勾选所有 FTYPE 区段
            chk.toggled.connect(self._on_ftype_check_toggled)
            self._ftype_checks.append(chk)
            col_layout.addWidget(chk)

            combo = NoWheelComboBox()
            combo.setEnabled(False)   # 未勾选时禁用
            col_layout.addWidget(combo, 1)   # stretch=1 占满剩余空间
            self._ftype_ttf_combos.append(combo)

            ftype_grid.addWidget(col_widget, row, col)

        ftype_grid.setColumnStretch(0, 1)
        ftype_grid.setColumnStretch(1, 1)

        right_layout.addWidget(create_dock("FTYPE 区段", ftype_content))

        # ── 生成 (右侧底部) ──
        action_content = QWidget()
        action_layout = QVBoxLayout(action_content)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        self._convert_btn = QPushButton("开始生成 FONT9696")
        self._convert_btn.setProperty("class", "ConfirmBtn")
        self._convert_btn.clicked.connect(self._on_start_convert)
        action_layout.addWidget(self._convert_btn)

        self._convert_progress = QProgressBar()
        self._convert_progress.setVisible(False)
        action_layout.addWidget(self._convert_progress)

        self._convert_status = QLabel("")
        self._convert_status.setWordWrap(True)
        action_layout.addWidget(self._convert_status)

        right_layout.addWidget(create_dock("生成", action_content))
        right_layout.addStretch()   # 多余空间留白在底部

        main_splitter.addWidget(right_panel)

        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([400, 500])
        outer.addWidget(main_splitter)

        # 创建页选项变化时刷新预览 (TTF 预览模式实时更新)
        self._simplified_check.toggled.connect(self._refresh_preview)
        self._pixel_size_spin.valueChanged.connect(self._refresh_preview)
        self._fallback_combo.currentIndexChanged.connect(self._refresh_preview)
        for combo in self._ftype_ttf_combos:
            combo.currentIndexChanged.connect(self._refresh_preview)

        return page

    def _build_preview_tab(self) -> QWidget:
        """构建"字体预览"标签页。"""
        page = QWidget()
        outer = QVBoxLayout(page)

        # 顶部控制栏
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("FTYPE:"))

        self._preview_ftype_combo = NoWheelComboBox()
        for i in range(8):
            self._preview_ftype_combo.addItem(f"FTYPE {i}", i)
        self._preview_ftype_combo.currentIndexChanged.connect(self._refresh_preview)
        ctrl_row.addWidget(self._preview_ftype_combo)

        ctrl_row.addStretch()
        ctrl_row.addWidget(QLabel("当前文件:"))
        self._preview_path_label = QLabel("(未加载)")
        self._preview_path_label.setProperty("status", "unloaded")
        ctrl_row.addWidget(self._preview_path_label)

        load_btn = QPushButton("打开 FONT9696…")
        load_btn.clicked.connect(self._on_open_font)
        ctrl_row.addWidget(load_btn)

        outer.addLayout(ctrl_row)

        # 滚动预览区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._preview_container = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_container)
        self._preview_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self._preview_container)

        outer.addWidget(scroll, 1)
        return page

    def _build_menu(self):
        """构建菜单栏: 文件/帮助 (与 v2 编辑器风格一致)。"""
        menubar = self.menuBar()

        # ── 文件(F) ──
        file_menu = menubar.addMenu("文件(F)")

        open_act = QAction("打开 FONT9696…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._on_open_font)
        file_menu.addAction(open_act)

        save_act = QAction("保存", self)
        save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self._on_save_font)
        file_menu.addAction(save_act)

        save_as_act = QAction("另存为…", self)
        save_as_act.triggered.connect(self._on_save_as_font)
        file_menu.addAction(save_as_act)

        file_menu.addSeparator()

        export_mod_act = QAction("导出为 MOD (.tksmod)…", self)
        export_mod_act.triggered.connect(self._on_export_mod)
        file_menu.addAction(export_mod_act)

        import_mod_act = QAction("从 MOD 导入…", self)
        import_mod_act.triggered.connect(self._on_import_mod)
        file_menu.addAction(import_mod_act)

        file_menu.addSeparator()

        exit_act = QAction("退出", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # ── 帮助(H) ──
        help_menu = menubar.addMenu("帮助(H)")
        help_menu.addAction("帮助说明", self._show_help)
        help_menu.addAction("关于编辑器", self._show_about)

    def _build_statusbar(self):
        """构建状态栏。"""
        self._status_label = QLabel("就绪")
        self.statusBar().addWidget(self._status_label)

    # ── 主题 ──

    def _apply_theme(self):
        """应用主题: QSS 客户区 + DWM 标题栏 (双机制)。"""
        ThemeManager.apply_theme(self, 'dark' if self._is_dark else 'light')
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)
        # 切换主题后刷新预览 (颜色变化)
        if self._font_path:
            self._refresh_preview()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _glyph_fg_color(self) -> str:
        """返回当前主题下字形笔画颜色 (渲染进位图像素), 与 editor_themes 文字色一致。"""
        return "#dcdcdc" if self._is_dark else "#222222"

    # ── 窗口标题 ──

    def _update_window_title(self):
        if self._font_path:
            name = os.path.basename(self._font_path)
            title = format_title("font_editor", name)
        else:
            title = format_title("font_editor")
        if self._modified:
            title = "*" + title
        self.setWindowTitle(title)

    # ── 文件操作 ──

    def _on_open_font(self):
        """打开现有 FONT9696 文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 FONT9696 文件", "",
            "FONT9696 文件 (FONT9696*);;所有文件 (*)")
        if not path:
            return
        self._load_font_file(path)

    def _load_font_file(self, path: str):
        """加载 FONT9696 文件到内存索引表。"""
        try:
            self._font_index = Font9696.load_index(path)
            self._font_path = path
            self._modified = False
            self._preview_path_label.setText(os.path.basename(path))
            self._preview_path_label.setProperty("status", "loaded")
            self._preview_path_label.style().unpolish(self._preview_path_label)
            self._preview_path_label.style().polish(self._preview_path_label)
            self._status_label.setText(f"已加载: {path}")
            self._refresh_preview()
            self._update_window_title()
        except Exception as e:
            QMessageBox.critical(self, "加载失败",
                                 f"读取 FONT9696 失败:\n{e}")

    def _on_save_font(self):
        if not self._font_path:
            QMessageBox.information(self, "无文件", "请先打开或创建 FONT9696 文件。")
            return
        # 当前版本不支持在线编辑字形, 保存即复制工作文件
        QMessageBox.information(self, "保存",
                                f"当前文件: {self._font_path}\n"
                                '字形编辑功能尚未实现, 请使用「创建字体」重新生成。')

    def _on_save_as_font(self):
        if not self._font_path:
            QMessageBox.information(self, "无文件", "请先打开或创建 FONT9696 文件。")
            return
        default_name = os.path.basename(self._font_path) or "FONT9696"
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default_name,
            "FONT9696 文件 (FONT9696*);;所有文件 (*)")
        if not path:
            return
        try:
            shutil.copy2(self._font_path, path)
            self._font_path = path
            self._preview_path_label.setText(os.path.basename(path))
            self._update_window_title()
            self._status_label.setText(f"已保存: {path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"另存为失败:\n{e}")

    # ── TTF 列表操作 ──

    def _on_add_ttf(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 TTF/OTF 字体文件", "",
            "字体文件 (*.ttf *.otf *.ttc);;所有文件 (*)")
        if not paths:
            return
        for p in paths:
            # 避免重复添加
            existing = [self._ttf_list.item(i).data(Qt.UserRole)
                        for i in range(self._ttf_list.count())]
            if p not in existing:
                item = QListWidgetItem(os.path.basename(p) + f"  [{p}]")
                item.setData(Qt.UserRole, p)
                item.setToolTip(p)
                self._ttf_list.addItem(item)
        if self._ttf_list.count() > 0:
            self._ttf_list.setCurrentRow(0)
        self._refresh_ttf_combos()

    def _on_remove_ttf(self):
        row = self._ttf_list.currentRow()
        if row >= 0:
            self._ttf_list.takeItem(row)
        self._refresh_ttf_combos()

    def _on_clear_ttf(self):
        self._ttf_list.clear()
        self._refresh_ttf_combos()

    def _get_ttf_paths(self) -> list[str]:
        """获取当前 TTF 列表的所有路径。"""
        return [self._ttf_list.item(i).data(Qt.UserRole)
                for i in range(self._ttf_list.count())]

    def _refresh_ttf_combos(self):
        """TTF 列表变化时, 同步刷新所有 FTYPE 下拉和回退字体下拉。"""
        ttf_paths = self._get_ttf_paths()

        # 刷新每个 FTYPE 的 TTF 下拉
        for i, combo in enumerate(self._ftype_ttf_combos):
            # 保留当前选中路径
            current_data = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for p in ttf_paths:
                name = os.path.basename(p)
                combo.addItem(name, p)
            # 恢复选中 (若仍存在), 否则选第一个
            if current_data in ttf_paths:
                idx = ttf_paths.index(current_data)
                combo.setCurrentIndex(idx)
            elif ttf_paths:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
            # 启用状态: 勾选且有 TTF
            combo.setEnabled(self._ftype_checks[i].isChecked() and bool(ttf_paths))

        # 刷新回退字体下拉
        current_fb = self._fallback_combo.currentData()
        self._fallback_combo.blockSignals(True)
        self._fallback_combo.clear()
        self._fallback_combo.addItem("(不使用回退)", None)
        for p in ttf_paths:
            name = os.path.basename(p)
            self._fallback_combo.addItem(name, p)
        if current_fb in ttf_paths:
            idx = ttf_paths.index(current_fb) + 1   # +1 跳过"不使用回退"
            self._fallback_combo.setCurrentIndex(idx)
        self._fallback_combo.blockSignals(False)
        # TTF 列表变化后刷新预览 (TTF 预览模式)
        self._refresh_preview()

    def _on_ftype_check_toggled(self):
        """FTYPE 勾选状态变化时, 启用/禁用对应的 TTF 下拉。"""
        for i, chk in enumerate(self._ftype_checks):
            self._ftype_ttf_combos[i].setEnabled(
                chk.isChecked() and self._ftype_ttf_combos[i].count() > 0)

    # ── 转换流程 ──

    def _on_start_convert(self):
        """开始 TTF → FONT9696 转换。"""
        # 收集 TTF 路径
        ttf_paths = self._get_ttf_paths()
        if not ttf_paths:
            QMessageBox.warning(self, "无 TTF", "请先添加至少一个 TTF 字体文件。")
            return

        # 收集选中的 FTYPE 区段及其 TTF 映射
        ftype_assignments: dict[int, str] = {}
        for i, chk in enumerate(self._ftype_checks):
            if chk.isChecked():
                combo = self._ftype_ttf_combos[i]
                ttf_path = combo.currentData()
                if not ttf_path:
                    QMessageBox.warning(self, "未选择 TTF",
                        f"FTYPE {i} 已勾选但未选择 TTF 字体。")
                    return
                ftype_assignments[i] = ttf_path

        if not ftype_assignments:
            QMessageBox.warning(self, "无 FTYPE", "请至少选择一个 FTYPE 区段。")
            return

        # 选择输出路径
        default_path = os.path.join(os.path.expanduser("~"), "FONT9696")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 FONT9696", default_path,
            "FONT9696 文件 (FONT9696*);;所有文件 (*)")
        if not save_path:
            return

        simplified = self._simplified_check.isChecked()
        pixel_size = self._pixel_size_spin.value()
        fallback_ttf = self._fallback_combo.currentData()

        # 启动后台线程
        self._convert_btn.setEnabled(False)
        self._convert_progress.setVisible(True)
        self._convert_progress.setRange(0, 100)
        self._convert_progress.setValue(0)
        self._convert_status.setText("正在初始化…")

        self._convert_thread = QThread()
        self._convert_worker = _ConvertWorker(
            ttf_paths, save_path, ftype_assignments, simplified, pixel_size,
            fallback_ttf)
        self._convert_worker.moveToThread(self._convert_thread)

        self._convert_thread.started.connect(self._convert_worker.run)
        self._convert_worker.progress.connect(self._on_convert_progress)
        self._convert_worker.finished.connect(self._on_convert_finished)
        self._convert_worker.finished.connect(self._convert_thread.quit)

        self._convert_thread.start()

    def _on_convert_progress(self, current: int, total: int, msg: str):
        if total > 0:
            pct = int(current * 100 / total)
            self._convert_progress.setValue(pct)
        self._convert_status.setText(msg)
        self._status_label.setText(f"转换中: {current}/{total}")

    def _on_convert_finished(self, success: bool, msg: str):
        self._convert_btn.setEnabled(True)
        self._convert_progress.setVisible(False)
        self._convert_status.setText(msg)
        self._status_label.setText("就绪")

        if success:
            # 自动加载生成的文件
            output_path = msg.split("→")[-1].strip() if "→" in msg else None
            if output_path and os.path.isfile(output_path):
                self._load_font_file(output_path)
                QMessageBox.information(self, "生成成功",
                                        f"FONT9696 文件已生成并加载:\n{output_path}")
            else:
                QMessageBox.information(self, "生成成功", msg)
        else:
            QMessageBox.critical(self, "生成失败", msg)

        # 清理线程
        if self._convert_thread:
            self._convert_thread.deleteLater()
            self._convert_thread = None
            self._convert_worker = None

    # ── 字体预览 ──

    def _refresh_preview(self):
        """刷新预览区。

        支持两种预览来源:
        1. FONT9696 文件 (已加载索引表) — 从文件解码字形
        2. TTF 直接预览 (未生成 FONT9696 时) — 用 PIL 直接渲染 TTF
        """
        # 清空现有内容
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        has_font9696 = bool(self._font_path and self._font_index)
        ttf_paths = self._get_ttf_paths()

        if not has_font9696 and not ttf_paths:
            hint = QLabel('请通过「文件 → 打开 FONT9696…」加载字体文件,\n'
                          '或在「创建字体」标签页添加 TTF 后预览。')
            hint.setAlignment(Qt.AlignCenter)
            hint.setProperty("class", "StatusHint")
            hint.setContentsMargins(40, 40, 40, 40)
            self._preview_layout.addWidget(hint)
            return

        ftype = self._preview_ftype_combo.currentData() or 0
        fg_color = self._glyph_fg_color()

        if has_font9696:
            # ── FONT9696 文件预览 ──
            self._preview_path_label.setText(os.path.basename(self._font_path))
            self._preview_path_label.setProperty("status", "loaded")
            self._preview_path_label.style().unpolish(self._preview_path_label)
            self._preview_path_label.style().polish(self._preview_path_label)

            # 示例文本预览
            sample_group = QGroupBox("示例文本预览 (FONT9696)")
            sample_layout = QVBoxLayout(sample_group)
            for text in PREVIEW_SAMPLES:
                row_widget = self._render_text_row_from_font(text, ftype, fg_color)
                sample_layout.addWidget(row_widget)
            self._preview_layout.addWidget(sample_group)

            # 字形网格
            self._render_glyph_grid(ftype, fg_color)

        else:
            # ── TTF 直接预览 (未生成 FONT9696) ──
            # 选择当前 FTYPE 对应的 TTF
            ttf_path = self._get_ttf_for_ftype(ftype)
            if not ttf_path:
                ttf_path = ttf_paths[0]   # 回退到第一个

            self._preview_path_label.setText(
                f"TTF 预览: {os.path.basename(ttf_path)}")
            self._preview_path_label.setProperty("status", "unloaded")
            self._preview_path_label.style().unpolish(self._preview_path_label)
            self._preview_path_label.style().polish(self._preview_path_label)

            simplified = self._simplified_check.isChecked()
            pixel_size = self._pixel_size_spin.value()

            try:
                from PIL import ImageFont
                pil_font = ImageFont.truetype(ttf_path, pixel_size)
            except Exception as e:
                hint = QLabel(f"无法加载 TTF: {e}")
                hint.setProperty("probe", "error")
                hint.setContentsMargins(20, 20, 20, 20)
                self._preview_layout.addWidget(hint)
                return

            # 回退字体
            fallback_path = self._fallback_combo.currentData()
            fallback_font = None
            if fallback_path:
                try:
                    fallback_font = ImageFont.truetype(fallback_path, pixel_size)
                except Exception:
                    pass

            # 示例文本预览
            sample_group = QGroupBox(
                f"示例文本预览 (TTF 直接渲染, {pixel_size}px, "
                f"{'简体' if simplified else '繁体'})")
            sample_layout = QVBoxLayout(sample_group)
            for text in PREVIEW_SAMPLES:
                row_widget = self._render_text_row_from_ttf(
                    text, pil_font, fallback_font, simplified, fg_color)
                sample_layout.addWidget(row_widget)
            self._preview_layout.addWidget(sample_group)

    def _get_ttf_for_ftype(self, ftype: int) -> str | None:
        """获取指定 FTYPE 在创建页选中的 TTF 路径。"""
        if 0 <= ftype < len(self._ftype_ttf_combos):
            combo = self._ftype_ttf_combos[ftype]
            data = combo.currentData()
            if data:
                return data
        ttf_paths = self._get_ttf_paths()
        return ttf_paths[0] if ttf_paths else None

    def _render_text_row_from_font(self, text: str, ftype: int,
                                    fg_color: str) -> QWidget:
        """从 FONT9696 文件渲染一行示例文本。"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 4, 4, 4)
        row_layout.setSpacing(0)

        text_label = QLabel(f"{text}:")
        text_label.setProperty("class", "PropLabel")
        text_label.setMinimumWidth(180)
        row_layout.addWidget(text_label)

        for ch in text:
            glyph_label = self._render_char_from_font(ch, ftype, fg_color)
            row_layout.addWidget(glyph_label)

        row_layout.addStretch()
        return row

    def _render_char_from_font(self, ch: str, ftype: int,
                                fg_color: str) -> QLabel:
        """从 FONT9696 渲染单个字符为 QLabel。

        ASCII 字符通过 word_4EC810 重映射表查找对应的 BIG5 全角码,
        与游戏引擎 sub_44B384 的处理逻辑一致。
        """
        try:
            code_point = ord(ch)
            if code_point < 0x80:
                # ASCII: 直接传码点, big5_to_index 内部会查 _ASCII_TO_BIG5 表
                idx = Font9696.big5_to_index(code_point, ftype)
            else:
                big5_bytes = ch.encode('big5')
                if len(big5_bytes) != 2:
                    return self._make_placeholder("?", fg_color)
                big5_code = (big5_bytes[0] << 8) | big5_bytes[1]
                idx = Font9696.big5_to_index(big5_code, ftype)
            if idx is None:
                return self._make_placeholder("?", fg_color)

            rle = Font9696.load_glyph_data(self._font_path, idx,
                                            self._font_index)
            if not rle:
                return self._make_empty_glyph()
            bitmap = Font9696.decode_rle(rle)
            stroke_bitmap = Font9696.invert_polarity(bitmap)
            return self._make_glyph_label(stroke_bitmap, fg_color)
        except (UnicodeEncodeError, LookupError, ValueError):
            return self._make_placeholder("?", fg_color)

    def _render_text_row_from_ttf(self, text: str, pil_font, fallback_font,
                                   simplified: bool,
                                   fg_color: str) -> QWidget:
        """从 TTF 直接渲染一行示例文本 (不依赖 FONT9696)。"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 4, 4, 4)
        row_layout.setSpacing(0)

        text_label = QLabel(f"{text}:")
        text_label.setProperty("class", "PropLabel")
        text_label.setMinimumWidth(180)
        row_layout.addWidget(text_label)

        for ch in text:
            glyph_label = self._render_char_from_ttf(
                ch, pil_font, fallback_font, simplified, fg_color)
            row_layout.addWidget(glyph_label)

        row_layout.addStretch()
        return row

    def _render_char_from_ttf(self, ch: str, pil_font, fallback_font,
                               simplified: bool,
                               fg_color: str) -> QLabel:
        """从 TTF 直接渲染单个字符为 QLabel (32×32 缩放预览)。"""
        from ttf_converter import _render_glyph_pillow, _convert_t2s

        render_ch = _convert_t2s(ch) if simplified else ch

        stroke_bitmap = _render_glyph_pillow(render_ch, pil_font)
        if stroke_bitmap is None and fallback_font is not None:
            stroke_bitmap = _render_glyph_pillow(render_ch, fallback_font)
        if stroke_bitmap is None:
            return self._make_placeholder("?", fg_color)

        return self._make_glyph_label(stroke_bitmap, fg_color)

    def _render_glyph_grid(self, ftype: int, fg_color: str):
        """渲染前 64 个 BIG5 字形网格 (FONT9696 文件模式)。"""
        grid_group = QGroupBox(f"字形网格 (FTYPE {ftype}, 前 64 个 BIG5 字符)")
        grid_layout = QGridLayout(grid_group)
        grid_layout.setSpacing(2)

        all_codes = Font9696.iter_all_big5_codes()
        for i in range(min(64, len(all_codes))):
            big5_code, idx_in_section = all_codes[i]
            global_idx = idx_in_section + Font9696.GLYPHS_PER_SECTION * ftype

            try:
                rle = Font9696.load_glyph_data(self._font_path, global_idx,
                                                self._font_index)
                if not rle:
                    glyph_img = self._make_empty_glyph()
                else:
                    bitmap = Font9696.decode_rle(rle)
                    stroke_bitmap = Font9696.invert_polarity(bitmap)
                    glyph_img = self._make_glyph_label(stroke_bitmap, fg_color)
            except Exception:
                glyph_img = self._make_empty_glyph()

            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(0)
            glyph_img.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(glyph_img)
            code_label = QLabel(f"{big5_code:04X}")
            code_label.setAlignment(Qt.AlignCenter)
            code_label.setProperty("class", "StatusHint")
            cell_layout.addWidget(code_label)
            grid_layout.addWidget(cell, i // 8, i % 8)

        self._preview_layout.addWidget(grid_group)

    def _make_placeholder(self, char: str, fg_color: str) -> QLabel:
        """生成占位字符 QLabel。"""
        placeholder = QLabel(char)
        placeholder.setProperty("class", "GlyphCell")
        placeholder.setFixedSize(32, 32)
        placeholder.setAlignment(Qt.AlignCenter)
        return placeholder

    def _make_glyph_label(self, stroke_bitmap: bytes,
                          fg_color: str) -> QLabel:
        """从笔画位图创建 QLabel (含 32×32 缩放预览)。"""
        # 渲染为 96×96 RGBA → 缩放到 32×32
        rgba = Font9696.render_glyph_from_bitmap(
            stroke_bitmap,
            color=self._parse_color(fg_color))
        if rgba is None:
            return self._make_empty_glyph()

        img = QImage(rgba, 96, 96, 96 * 4, QImage.Format_RGBA8888)
        if img.isNull():
            return self._make_empty_glyph()
        pix = QPixmap.fromImage(img).scaled(32, 32, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation)
        lbl = QLabel()
        lbl.setProperty("class", "GlyphCell")
        lbl.setPixmap(pix)
        lbl.setFixedSize(32, 32)
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    def _make_empty_glyph(self) -> QLabel:
        lbl = QLabel()
        lbl.setProperty("class", "GlyphCell")
        lbl.setFixedSize(32, 32)
        return lbl

    @staticmethod
    def _parse_color(hex_color: str) -> tuple[int, int, int]:
        """'#RRGGBB' → (R, G, B)"""
        h = hex_color.lstrip('#')
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    # ── MOD 导入导出 ──

    def _on_export_mod(self):
        """导出 FONT9696 为 .tksmod (resources 整体替换)。"""
        if not self._font_path or not os.path.isfile(self._font_path):
            QMessageBox.warning(self, "无文件", "请先打开或生成 FONT9696 文件。")
            return

        # 弹出 MOD 元数据对话框 (ID 自动随机生成, 名称/描述默认为空)
        dlg = ModMetadataDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        metadata = dlg.get_metadata()

        # 选择保存路径
        default_name = safe_mod_filename(metadata.get("name", "font_mod"),
                                          metadata.get("id", "font_mod"))
        default_path = os.path.join(os.path.expanduser("~"),
                                     f"{default_name}.tksmod")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 MOD", default_path, "TKS MOD (*.tksmod)")
        if not save_path:
            return
        if not save_path.lower().endswith(".tksmod"):
            save_path += ".tksmod"

        # 构造 resources 声明 (FONT9696 文件整体替换)
        resources_meta = [
            {"file": "resources/FONT9696", "target": "FONT9696"}
        ]
        resource_files = {
            "resources/FONT9696": self._font_path
        }

        # 生成 mod.json
        mod_json = generate_mod_json(
            metadata, components=[], resources=resources_meta, configs=None)

        # 打包
        try:
            pack_tksmod(save_path, mod_json, data_files={},
                        resource_files=resource_files,
                        preview_image_path=metadata.get("preview_image_path") or None)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"打包 .tksmod 失败:\n{e}")
            return

        QMessageBox.information(self, "导出成功",
            f"已导出 MOD:\n  {save_path}\n"
            f"  包含资源: FONT9696 (整体替换)\n"
            f"  启动器加载此 MOD 后会自动备份原 FONT9696 为 .mod_orig 并替换。")

    def _on_import_mod(self):
        """从 .tksmod 导入 FONT9696 文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 .tksmod 文件", "",
            "TKS MOD (*.tksmod);;所有文件 (*)")
        if not path:
            return

        try:
            mod_json, _ = read_tksmod(path)
            if mod_json is None:
                QMessageBox.critical(self, "导入失败",
                                     "无法读取 mod.json, 文件可能不是有效的 .tksmod。")
                return

            # 检查 resources 中是否有 FONT9696
            resources = mod_json.get("resources", [])
            font_resource = None
            for r in resources:
                target = r.get("target", "").upper()
                if target == "FONT9696":
                    font_resource = r
                    break

            if font_resource is None:
                QMessageBox.warning(self, "无字体资源",
                    f"该 MOD 不包含 FONT9696 资源。\n"
                    f"resources 列表: {resources}")
                return

            internal_path = font_resource.get("file", "resources/FONT9696")
            mod_name = mod_json.get("name", os.path.basename(path))

            # 选择保存位置
            default_path = os.path.join(os.path.expanduser("~"), "FONT9696")
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存导入的 FONT9696", default_path,
                "FONT9696 文件 (FONT9696*);;所有文件 (*)")
            if not save_path:
                return

            # 从 ZIP 中提取
            with zipfile.ZipFile(path, 'r') as zf:
                with zf.open(internal_path) as src:
                    data = src.read()
            with open(save_path, 'wb') as dst:
                dst.write(data)

            # 自动加载
            self._load_font_file(save_path)

            QMessageBox.information(self, "导入成功",
                f"已从 MOD '{mod_name}' 提取 FONT9696:\n"
                f"  内部路径: {internal_path}\n"
                f"  保存到: {save_path}\n"
                f"  文件大小: {len(data)} 字节")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"导入 MOD 失败:\n{e}")

    # ── 帮助/关于 ──

    def _show_help(self):
        """显示帮助说明。"""
        themed_messagebox(
            self, QMessageBox.Information, "帮助说明",
            "功能: 生成与预览《三国群侠传》FONT9696 位图字体\n\n"
            "创建字体:\n"
            "  1. 添加 TTF/OTF 字体文件\n"
            "  2. 勾选要生成的 FTYPE 区段 (默认全选)\n"
            "  3. 选择简体/繁体字形, 调整渲染像素大小 (建议 70-85)\n"
            "  4. 为每个 FTYPE 区段独立选择 TTF\n"
            "  5. 点击「开始生成」并选择输出路径\n\n"
            "字体预览:\n"
            "  加载 FONT9696 后可查看 8 个 FTYPE 区段的字形\n"
            "  预览包含示例文本和前 64 个 BIG5 字符网格\n"
            "  ASCII 字符通过 word_4EC810 重映射为 BIG5 全角码显示\n\n"
            "MOD 导出/导入:\n"
            "  通过「文件」菜单将 FONT9696 打包为 .tksmod 或从 .tksmod 导入\n"
            "  MOD 采用 resources 整体替换机制\n\n"
            "格式说明:\n"
            "  8 FTYPE × 14915 字形 × uint32 偏移索引 + RLE 压缩 96×96 1bpp 位图\n"
            "  BIG5 编码索引, bit=1 为背景, bit=0 为笔画\n\n"
            "逆向依据:\n"
            "  sub_44ADB0 (字体构造), sub_44B384 (BIG5 索引), sub_44B208 (RLE 编解码)"
        )

    def _show_about(self):
        """显示关于对话框。"""
        themed_messagebox(
            self, QMessageBox.Information, "关于编辑器",
            format_about_header('font_editor')
        )

    # ── 关闭事件 ──

    def closeEvent(self, event):
        """关闭窗口时清理线程。"""
        if self._convert_thread and self._convert_thread.isRunning():
            reply = QMessageBox.question(
                self, "转换进行中",
                "字体转换正在进行中, 确定退出?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._convert_thread.terminate()
            self._convert_thread.wait()
        event.accept()


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    from editor_utils.app_init import ensure_single_instance
    ensure_single_instance()
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)              # 必须紧跟 QApplication 后调用
    app.setStyle("Fusion")
    app.setApplicationName("TKS Font Editor")
    _t = install_translator(app)                  # 保持引用防 GC
    setup_app_icon(app, os.path.dirname(__file__))

    window = FontEditorWindow()

    # 检测系统主题
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    window._is_dark = is_dark
    window._apply_theme()

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
