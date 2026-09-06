#!/usr/bin/env python3
"""
Spritesheet Editor - 精灵表编辑器 (PySide6)
================================================
功能:
  1. 导入多张图片, 设置 columns/rows/padding, 拼成 Spritesheet
  2. 按 columns/rows/padding 拆分导入的 Spritesheet
  3. 拖拽调整序列帧顺序 / 整行上下排序 / 整列左右排序
  4. 选中多个帧后预览动画, 也可预览整个 Spritesheet
  5. 导出时选择 PNG 像素格式: RGBA8888 / RGB888 / RGB565 / RGBA4444 / RGBA5551
  6. 深浅色主题切换

用法: python spritesheet_editor.py [spritesheet.png]
"""

from __future__ import annotations
import os
import re
import sys
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import List, Optional, Set, Tuple

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsTextItem,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QCheckBox, QRadioButton,
    QGroupBox, QTextEdit,
    QMenu, QDialog, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QButtonGroup,
    QListView, QAbstractItemView, QSlider, QSplitter, QLineEdit, QScrollArea,
)
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QPalette, QColor, QIcon, QAction,
    QKeySequence, QShortcut, QFont, QPen, QBrush, QWheelEvent, QMouseEvent,
    QContextMenuEvent,
)
from PySide6.QtCore import (
    Qt, QObject, Signal, QTimer, QSize, QRect, QPoint, QRectF, QPointF,
)

HAS_PIL = False
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils import theme_manager
from editor_utils.theme_manager import business_colors
from editor_utils.theme_switcher import toggle_theme_in_family
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.ui_helpers import themed_question, EditorComboBox


from sprite_image_ops import apply_alpha_mode, convert_pixel_format
from sprite_model import SpriteSheetModel
from sprite_widgets import (
    ImageListWidget, PreviewView, SettingsPanel, SpriteGraphicsView,
)


# ═══════════════════════════════════════════════════════════════
# 主编辑器窗口 (QMainWindow)
# ═══════════════════════════════════════════════════════════════

class SpriteSheetEditorWindow(EditorMainWindow):
    """Spritesheet 编辑器主窗口 (PySide6)"""

    EDITOR_KEY = "spritesheet_editor"
    DEFAULT_SIZE = (1200, 800)  # 实际尺寸由 _after_build 的 _fit_to_screen 决定
    MIN_SIZE = (1200, 800)

    HELP_TEXT = (
        "功能: 制作和编辑游戏精灵表 (Spritesheet)\n\n"
        "特性:\n"
        "  · 导入多张图片拼合为精灵表\n"
        "  · 按列数/行数/间距拆分已有精灵表\n"
        "  · 拖拽调整帧顺序, 支持整行/整列移动\n"
        "  · 选中多帧后可预览动画播放\n"
        "  · 多种像素格式导出 (RGBA8888 / RGB888 / RGB565 等)\n"
        "  · 深色/浅色主题切换\n\n"
        "快捷键:\n"
        "  Ctrl+A = 全选   Ctrl+C/V = 复制/粘贴   Delete = 删除选中帧\n"
        "  Ctrl+方向键 = 移动选中帧\n"
        "  Shift+方向键 = 移动整行/整列")

    def __init__(self, filepath: Optional[str] = None):
        self._initial_path = filepath
        super().__init__()

    def _init_data(self):
        # 应用默认字体 (用 pointSize 而非 pixelSize:
        #   pixelSize 会使 font.pointSize() 返回 -1, 点击 EditorComboBox 弹出菜单时
        #   Qt 内部以 font.pointSize() 调 setPointSize 触发 "Point size <= 0 (-1)" 警告;
        #   实际显示由 QSS 的 px 字号覆盖)
        app = QApplication.instance()
        if app:
            font = QFont()
            font.setPointSize(9)
            app.setFont(font)

        self._dirty = False  # 模型变更置位, 加载/新建/保存后复位 (closeEvent 退出确认)
        self._set_model(SpriteSheetModel())
        self._source_sheet: Optional[Image.Image] = None
        self._preview_mode: str = "grid"
        self._suppress_mode_change: bool = False

    def _build_ui(self):
        self._build_layout()
        self._build_menu()
        self._build_shortcuts()

    def _after_build(self):
        # 采用 QApplication 级样式表，让无父窗口的弹窗也继承主题
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)

        # 初始画布背景色同步 (跟随 OS 主题)
        bg_color = QColor(business_colors("spritesheet", self._theme_id)["canvas_bg"])
        self.canvas.setBackgroundBrush(QBrush(bg_color))
        self.preview_view._disp.setObjectName("GamePreview")
        self.preview_view._disp.style().unpolish(self.preview_view._disp)
        self.preview_view._disp.style().polish(self.preview_view._disp)

        if self._initial_path:
            self._load_spritesheet(Path(self._initial_path))

        self._fit_to_screen()

    def _fit_to_screen(self):
        """根据屏幕可用空间设定窗口尺寸并居中。"""
        screen_geo = QApplication.primaryScreen().availableGeometry()
        hint = self.sizeHint()
        w = min(hint.width(), int(screen_geo.width() * 0.92))
        h = min(hint.height(), int(screen_geo.height() * 0.88))
        self.resize(w, h)
        self.setMinimumSize(1200, 800)
        # 用 frameGeometry 居中（含窗口边框/标题栏），避免客户区与框架尺寸不一致
        fg = self.frameGeometry()
        fg.moveCenter(screen_geo.center())
        self.move(fg.topLeft())


    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # ── 工具栏 ──
        # 先创建 SettingsPanel, 工具栏按钮需要引用 self.settings._move_row/_move_col
        self.settings = SettingsPanel(self.model, self)
        # 先创建 canvas/preview_view, 左侧面板按钮需要引用 self.canvas.move_selected_*
        self.canvas = SpriteGraphicsView(self.model, self)
        self.preview_view = PreviewView(self)
        self.preview_view.setVisible(False)
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("模式:"))

        self._mode_merge = QRadioButton("组合")
        self._mode_merge.setChecked(True)
        self._mode_split = QRadioButton("拆分")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._mode_merge)
        mode_group.addButton(self._mode_split)
        mode_group.buttonToggled.connect(self._on_workflow_mode_changed)

        toolbar.addWidget(self._mode_merge)
        toolbar.addWidget(self._mode_split)
        toolbar.addWidget(self._v_sep())

        btn_new = QPushButton("新建")
        btn_new.clicked.connect(self._new)
        toolbar.addWidget(btn_new)

        self._btn_import_merge = QPushButton("导入图片")
        self._btn_import_merge.clicked.connect(self._import_images)
        toolbar.addWidget(self._btn_import_merge)

        self._btn_import_split = QPushButton("导入图集")
        self._btn_import_split.clicked.connect(self._import_spritesheet)
        self._btn_import_split.setEnabled(False)
        toolbar.addWidget(self._btn_import_split)

        toolbar.addWidget(self._v_sep())

        btn_preview_sel = QPushButton("预览选中")
        btn_preview_sel.clicked.connect(self._preview_selected)
        toolbar.addWidget(btn_preview_sel)

        btn_preview_all = QPushButton("预览全部")
        btn_preview_all.clicked.connect(self._preview_all)
        toolbar.addWidget(btn_preview_all)

        toolbar.addWidget(self._v_sep())

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_from_list)
        toolbar.addWidget(btn_delete)

        toolbar.addWidget(self._v_sep())

        btn_copy_row = QPushButton("复制行")
        btn_copy_row.clicked.connect(self._copy_row)
        toolbar.addWidget(btn_copy_row)

        btn_delete_row = QPushButton("删除行")
        btn_delete_row.clicked.connect(self._delete_row)
        toolbar.addWidget(btn_delete_row)

        toolbar.addWidget(self._v_sep())

        btn_copy_col = QPushButton("复制列")
        btn_copy_col.clicked.connect(self._copy_col)
        toolbar.addWidget(btn_copy_col)

        btn_delete_col = QPushButton("删除列")
        btn_delete_col.clicked.connect(self._delete_col)
        toolbar.addWidget(btn_delete_col)

        btn_flip = QPushButton("水平翻转")
        btn_flip.clicked.connect(self._flip_horizontal)
        toolbar.addWidget(btn_flip)

        toolbar.addWidget(self._v_sep())

        btn_row_up = QPushButton("行上移")
        btn_row_up.clicked.connect(partial(self.settings._move_row, -1))
        toolbar.addWidget(btn_row_up)
        btn_row_down = QPushButton("行下移")
        btn_row_down.clicked.connect(partial(self.settings._move_row, 1))
        toolbar.addWidget(btn_row_down)
        btn_col_left = QPushButton("列左移")
        btn_col_left.clicked.connect(partial(self.settings._move_col, -1))
        toolbar.addWidget(btn_col_left)
        btn_col_right = QPushButton("列右移")
        btn_col_right.clicked.connect(partial(self.settings._move_col, 1))
        toolbar.addWidget(btn_col_right)

        # 深浅色切换
        toolbar.addWidget(self._v_sep())
        btn_theme = QPushButton("切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)

        toolbar.addStretch()
        self._status_label = QLabel("就绪")
        self._status_label.setProperty("class", "StatusHint")
        toolbar.addWidget(self._status_label)

        main_layout.addLayout(toolbar)

        # ── 主内容区 (QSplitter + Dock 面板) ──
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(6)

        # ── 左侧: 精灵资产库 ──
        left_widget = QWidget()
        left_panel = QVBoxLayout(left_widget)
        left_panel.setContentsMargins(0, 0, 0, 0)
        left_header = QHBoxLayout()
        self._list_title = QLabel("导入的精灵")
        left_header.addWidget(self._list_title)
        btn_clear = QPushButton("清空")
        btn_clear.setProperty("class", "CompactBtn")
        btn_clear.clicked.connect(self._clear_list)
        left_header.addWidget(btn_clear)
        btn_up = QPushButton("▲上移")
        btn_up.setProperty("class", "CompactBtn")
        btn_up.clicked.connect(partial(self.canvas.move_selected_left))
        left_header.addWidget(btn_up)
        btn_down = QPushButton("▼下移")
        btn_down.setProperty("class", "CompactBtn")
        btn_down.clicked.connect(partial(self.canvas.move_selected_right))
        left_header.addWidget(btn_down)
        left_panel.addLayout(left_header)

        self.image_list = ImageListWidget(self)
        self.image_list.itemClicked.connect(self.image_list._on_item_clicked)
        left_panel.addWidget(self.image_list, 1)

        list_info = QLabel("未导入图片")
        list_info.setProperty("class", "StatusHint")
        self._list_info_label = list_info
        left_panel.addWidget(list_info)

        main_splitter.addWidget(self._create_dock("精灵资产库", left_widget))

        # ── 中间: 2D 渲染视口 ──
        center_widget = QWidget()
        center = QVBoxLayout(center_widget)
        center.setContentsMargins(0, 0, 0, 0)

        # 预览模式切换栏 + 缩放
        preview_bar = QHBoxLayout()
        preview_bar.addWidget(QLabel("显示:"))

        self._mode_grid = QRadioButton("网格")
        self._mode_grid.setChecked(True)
        self._mode_single = QRadioButton("单帧")
        self._mode_anim = QRadioButton("动画")
        mode_group2 = QButtonGroup(self)
        mode_group2.addButton(self._mode_grid)
        mode_group2.addButton(self._mode_single)
        mode_group2.addButton(self._mode_anim)
        mode_group2.buttonToggled.connect(self._on_preview_mode_changed)
        preview_bar.addWidget(self._mode_grid)
        preview_bar.addWidget(self._mode_single)
        preview_bar.addWidget(self._mode_anim)

        preview_bar.addStretch()

        preview_bar.addWidget(QLabel("缩放:"))
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setProperty("class", "CompactBtn")
        btn_zoom_out.clicked.connect(partial(self._shared_zoom_step, -0.25))
        preview_bar.addWidget(btn_zoom_out)
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setProperty("class", "CompactBtn")
        btn_zoom_in.clicked.connect(partial(self._shared_zoom_step, 0.25))
        preview_bar.addWidget(btn_zoom_in)
        btn_zoom_1 = QPushButton("1:1")
        btn_zoom_1.setProperty("class", "CompactBtn")
        btn_zoom_1.clicked.connect(self._shared_zoom_reset)
        preview_bar.addWidget(btn_zoom_1)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(40)
        preview_bar.addWidget(self._zoom_label)

        center.addLayout(preview_bar)

        # 堆栈: 网格视图 / 预览视图
        self._stack = QWidget()
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        # 网格视图容器
        self._grid_container = QWidget()
        grid_layout = QVBoxLayout(self._grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        # self.canvas 已在工具栏构建前创建 (左侧面板按钮需要引用)
        grid_layout.addWidget(self.canvas)
        stack_layout.addWidget(self._grid_container)

        # 预览视图 (self.preview_view 已在工具栏构建前创建, 此处加入布局)
        stack_layout.addWidget(self.preview_view)

        center.addWidget(self._stack, 1)

        hint = QLabel("操作: 点击选帧 | Ctrl+多选 | Shift+范围选 | 拖拽帧/行头/列头排序")
        hint.setProperty("class", "StatusHint")
        center.addWidget(hint)

        main_splitter.addWidget(self._create_dock("2D 渲染视口", center_widget))

        # ── 右侧: 检查器 (每个区域独立 Dock 面板, ScrollArea 应对小窗口) ──
        # self.settings 已在工具栏构建前创建 (工具栏按钮需要引用)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        for title, widget in self.settings.sections():
            right_layout.addWidget(self._create_dock(title, widget))
        right_layout.addStretch()
        right_scroll = QScrollArea()
        right_scroll.setWidget(right_container)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(260)
        main_splitter.addWidget(right_scroll)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([260, 600, 300])
        main_layout.addWidget(main_splitter, 1)

        # ── 信号/槽连接 (MVC 解耦) ──
        self.canvas.selectionChangedCustom.connect(self._on_selection_changed)
        self.image_list.selectionChangedCustom.connect(self._on_selection_changed)

        # 初始渲染空网格
        self.canvas.redraw()

    def _set_model(self, model: SpriteSheetModel) -> None:
        """替换数据模型并保持所有视图订阅同一个变更信号。"""
        self.model = model
        self.model.model_changed.connect(self._on_model_changed)
        if hasattr(self, "canvas"):
            self.canvas.model = model
        if hasattr(self, "settings"):
            self.settings.model = model

    def _replace_model(self, *, clear_source: bool = True) -> None:
        """创建空模型并清理依赖旧模型的 UI 状态。"""
        self._set_model(SpriteSheetModel())
        if clear_source:
            self._source_sheet = None
        self.image_list._image_paths.clear()
        self.image_list._path_by_id.clear()
        self.image_list._selected_idx = -1
        self.image_list._anchor_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1

    def _reset_import_state(self) -> None:
        """清理导入/拆分后需要重新计算的列表和选择状态。"""
        self.image_list._image_paths.clear()
        self.image_list._path_by_id.clear()
        self.image_list._selected_idx = -1
        self.image_list._anchor_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1

    def _v_sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        return sep

    def _build_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("导入图片(合并)", self._import_images)
        file_menu.addAction("导入图集(拆分)", self._import_spritesheet)
        file_menu.addSeparator()
        file_menu.addAction("新建空白", self._new)
        file_menu.addSeparator()
        file_menu.addAction("保存图集\tCtrl+S", self._save)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        # 编辑菜单 — 仅显示快捷键提示, 实际绑定由 QShortcut 统一处理
        edit_menu = menubar.addMenu("编辑")
        edit_menu.addAction("全选\tCtrl+A", self.canvas.select_all)
        edit_menu.addAction("复制\tCtrl+C", self.canvas.shortcut_copy)
        edit_menu.addAction("粘贴\tCtrl+V", self.canvas.shortcut_paste)
        edit_menu.addAction("取消选择\tEscape", self.canvas.select_none)
        edit_menu.addSeparator()
        edit_menu.addAction("删除选中帧\tDelete", self.canvas.delete_selected)
        edit_menu.addSeparator()
        edit_menu.addAction("选中帧左移\tCtrl+←", self.canvas.move_selected_left)
        edit_menu.addAction("选中帧右移\tCtrl+→", self.canvas.move_selected_right)
        edit_menu.addAction("选中帧上移\tCtrl+↑", self.canvas.move_selected_up)
        edit_menu.addAction("选中帧下移\tCtrl+↓", self.canvas.move_selected_down)
        edit_menu.addSeparator()
        edit_menu.addAction("当前列左移\tShift+←", lambda: self.settings._move_col(-1))
        edit_menu.addAction("当前列右移\tShift+→", lambda: self.settings._move_col(1))
        edit_menu.addAction("当前行上移\tShift+↑", lambda: self.settings._move_row(-1))
        edit_menu.addAction("当前行下移\tShift+↓", lambda: self.settings._move_row(1))
        edit_menu.addSeparator()
        edit_menu.addAction("删除当前列", self._delete_col)

        # 预览菜单
        view_menu = menubar.addMenu("预览")
        view_menu.addAction("预览选中帧", self._preview_selected)
        view_menu.addAction("预览全部", self._preview_all)

        self.add_standard_menus(menubar)

    def _build_shortcuts(self):
        """统一快捷键注册 — 仅 QShortcut (避免与 QAction 双重注册冲突)"""
        _w = self._shortcut_wrap
        # 基础快捷键 (不经过输入控件检测, 因其不与文本编辑冲突)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Ctrl+A"), self, self.canvas.select_all)
        QShortcut(QKeySequence("Ctrl+C"), self, _w(self.canvas.shortcut_copy))
        QShortcut(QKeySequence("Ctrl+V"), self, _w(self.canvas.shortcut_paste))
        QShortcut(QKeySequence("Escape"), self, self.canvas.select_none)
        QShortcut(QKeySequence("Delete"), self, self.canvas.delete_selected)
        # 方向键移动 — 必须经 _shortcut_wrap 避开输入控件焦点
        QShortcut(QKeySequence("Ctrl+Left"),  self, _w(self.canvas.move_selected_left))
        QShortcut(QKeySequence("Ctrl+Right"), self, _w(self.canvas.move_selected_right))
        QShortcut(QKeySequence("Ctrl+Up"),    self, _w(self.canvas.move_selected_up))
        QShortcut(QKeySequence("Ctrl+Down"),  self, _w(self.canvas.move_selected_down))
        # Shift+方向键 = 换行/换列
        QShortcut(QKeySequence("Shift+Left"),  self, _w(lambda: self.settings._move_col(-1)))
        QShortcut(QKeySequence("Shift+Right"), self, _w(lambda: self.settings._move_col(1)))
        QShortcut(QKeySequence("Shift+Up"),    self, _w(lambda: self.settings._move_row(-1)))
        QShortcut(QKeySequence("Shift+Down"),  self, _w(lambda: self.settings._move_row(1)))

    def _shortcut_wrap(self, func):
        """包装快捷键回调: SpinBox/TextEdit/ComboBox 获得焦点时不劫持文本编辑"""
        def wrapper():
            w = QApplication.focusWidget()
            if isinstance(w, (QLineEdit, QTextEdit, QSpinBox, EditorComboBox)):
                return
            func()
        return wrapper

    # ── 模型变更通知 ───────────────────
    def _on_model_changed(self):
        self._dirty = True
        self.canvas.redraw()
        self.image_list.refresh_values()
        self._update_status()
        if self._preview_mode != "grid":
            self._refresh_inline_preview(keep_idx=True)

    def _update_status(self):
        m = self.model
        total = m.total_cells
        shown = sum(1 for f in m.frames if f is not None)
        self._status_label.setText(
            f"帧: {m.frame_count}/{total}  "
            f"网格: {m.columns}x{m.rows}  "
            f"Cell: {m.cell_width}x{m.cell_height}  "
            f"Padding: {m.padding}"
        )
        self._list_info_label.setText(
            f"{shown} 张 | 网格 {m.columns}×{m.rows}={total}")

    # ── 新建 ───────────────────────────
    def _new(self):
        if self.model.frame_count > 0:
            if themed_question(self, "确认", "当前内容将被清除，确定新建吗?") != QMessageBox.Yes:
                return
        self._replace_model()
        self.settings.refresh_values()
        self._on_model_changed()
        self._dirty = False
        self._status_label.setText("新建空白 Spritesheet")

    # ── 导入 ───────────────────────────
    def _import_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要导入的图片", "",
            "图片文件 (*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp);;所有文件 (*.*)")
        if not files:
            return
        # 切换到组合模式 (若已有数据会弹出确认框, 用户取消则跳过加载)
        self._mode_merge.setChecked(True)
        if not self._mode_merge.isChecked():
            return

        # 按文件名排序（自然排序：数字按数值大小排）
        files = sorted(files, key=lambda f: [
            int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', Path(f).name)
        ])

        images = []
        paths = []  # 与 images 一一对应 (跳过加载失败的文件)
        for fp in files:
            try:
                img = Image.open(fp).convert("RGBA")
                images.append(img)
                paths.append(fp)
            except Exception as e:
                QMessageBox.warning(self, "警告", f"无法读取 {Path(fp).name}: {e}")

        if not images:
            return

        # 追加导入: 已有帧保持原位, 新图按扫描顺序填补空格,
        # 空格不足时追加到末尾并扩展行数 (列数不变, 网格位置稳定)
        m = self.model
        m.normalize()
        frames = list(m.frames)
        pending = list(images)
        for i in range(len(frames)):
            if not pending:
                break
            if frames[i] is None:
                frames[i] = pending.pop(0)
        if pending:
            frames.extend(pending)  # normalize 后长度=cols*rows, 追加从新行开头开始
            cols = max(1, m.columns)
            m.rows = max(m.rows, (len(frames) + cols - 1) // cols)
        m.frames = frames
        m.padding = self.settings._spin_padding.value()
        # 用户未手动设定 cell 尺寸时自动适配 (含新导入的更大图片)
        if not m._cell_size_set:
            m.auto_detect_cell_size()

        # 记录新图路径 (按对象 id 供左侧列表显示文件名, 保留旧图记录)
        for img, fp in zip(images, paths):
            self.image_list._path_by_id[id(img)] = fp
        self.image_list._image_paths.extend(paths)

        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.image_list._selected_idx = -1
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_label.setText(
            f"已导入 {len(images)} 张图片 (共 {m.frame_count} 帧) "
            f"→ {m.columns}×{m.rows} 网格")

    def _import_spritesheet(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择图集图片", "",
            "PNG 图片 (*.png);;所有图片 (*.png *.bmp *.jpg);;所有文件 (*.*)")
        if not fp:
            return
        # 切换到拆分模式 (若已有数据会弹出确认框, 用户取消则跳过加载)
        self._mode_split.setChecked(True)
        if self._mode_split.isChecked():
            self._load_spritesheet(Path(fp))

    def _load_spritesheet(self, path: Path):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法读取图片: {e}")
            return

        self._source_sheet = img

        m = self.model
        cols = max(1, int(m.columns))
        rows = max(1, int(m.rows))
        pad = max(0, int(m.padding))
        # 用户未手动设定 cell 宽高时自动反算；已手动设定则使用用户值
        if not m._cell_size_set:
            iw, ih = img.size
            m.cell_width = max(1, (iw - max(0, cols - 1) * pad) // cols)
            m.cell_height = max(1, (ih - max(0, rows - 1) * pad) // rows)
        self._reset_import_state()
        m.split_spritesheet(img)
        self.settings.refresh_values()
        self._dirty = False
        self._status_label.setText(
            f"已拆分: {path.name} → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _resplit(self):
        img = self._source_sheet
        if img is None:
            QMessageBox.information(self, "提示", "请先通过《导入拆分》加载一张 Spritesheet")
            return
        if self.model.frame_count > 0:
            if themed_question(self, "确认",
                    "重新拆分将丢弃当前排序和删除, 确定继续吗?") != QMessageBox.Yes:
                return

        m = self.model
        # 用户未手动设定 cell 宽高时自动反算；已手动设定则使用用户值
        if not m._cell_size_set:
            iw, ih = img.size
            cols = max(1, int(m.columns))
            rows = max(1, int(m.rows))
            pad = max(0, int(m.padding))
            m.cell_width = max(1, (iw - max(0, cols - 1) * pad) // cols)
            m.cell_height = max(1, (ih - max(0, rows - 1) * pad) // rows)
        self._reset_import_state()
        m.split_spritesheet(img)
        self.settings.refresh_values()
        self._dirty = False
        self._status_label.setText(
            f"已重新拆分 → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _export_all_frames(self):
        m = self.model
        if m.frame_count == 0:
            QMessageBox.information(self, "提示", "没有帧数据可导出")
            return
        sel = self.canvas.selection
        if sel:
            indices = sorted(i for i in sel if 0 <= i < len(m.frames) and m.frames[i] is not None)
        else:
            indices = [i for i, f in enumerate(m.frames) if f is not None]
        if not indices:
            QMessageBox.information(self, "提示", "没有可导出的帧")
            return

        outdir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not outdir:
            return
        fmt = self.settings._fmt_combo.currentText()
        alpha_mode = self.settings._alpha_combo.currentText()
        tex_fmt = self.settings._tex_combo.currentText()
        count = 0
        for idx in indices:
            f = m.get_frame(idx)
            if f is None:
                continue
            try:
                processed = apply_alpha_mode(f, alpha_mode)
                converted = convert_pixel_format(processed, fmt)
                fp = Path(outdir) / f"frame_{idx:03d}.png"
                converted.save(fp, "PNG")
                count += 1
            except Exception as e:
                print(f"导出失败 #{idx}: {e}")
        self._status_label.setText(
            f"已导出 {count}/{len(indices)} 帧 → {outdir} ({tex_fmt} / {fmt} / {alpha_mode})")

    # ── 删除 / 复制行 / 翻转 ──────────
    def _delete_from_list(self):
        if self.canvas.selection:
            self.canvas.delete_selected()

    def _clear_list(self):
        self.image_list.clear_all()

    def _copy_row(self):
        """复制当前选中行（支持多行）"""
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要复制行中的任意帧")
            return
        old_cols = max(1, self.model.columns)
        rows = sorted(set(idx // old_cols for idx in sel))
        # 先把选中行装入块级剪贴板（在原地插入之前抓取, 避免索引错位）
        cells: List[Tuple[int, int, Optional[Image.Image]]] = []
        for row in rows:
            for dc in range(old_cols):
                idx = row * old_cols + dc
                f = self.model.frames[idx] if idx < len(self.model.frames) else None
                cells.append((0, dc, f.copy() if f is not None else None))
        self.canvas._copied_cells = cells
        # 将原 sel 按旧列数转换为 (row, col) 对
        old_sel_positions = [(idx // old_cols, idx % old_cols) for idx in sel]
        if len(rows) == 1:
            self.model.copy_row(rows[0])
            # 仅保留原选择（按新列数重新索引）
            new_sel = set()
            for r, c in old_sel_positions:
                new_sel.add(r * self.model.columns + c)
            self.canvas.selection = new_sel
            self.settings._spin_rows.setValue(self.model.rows)
            self._on_model_changed()
            self._status_label.setText(
                f"已复制行 R{rows[0]} → R{rows[0] + 1} (剪贴板 {len(cells)} 帧)")
        else:
            new_rows = self.model.copy_rows(rows)
            new_sel = set()
            for r, c in old_sel_positions:
                new_sel.add(r * self.model.columns + c)
            self.canvas.selection = new_sel
            self.settings._spin_rows.setValue(self.model.rows)
            self._on_model_changed()
            row_str = ", ".join(f"R{r}" for r in rows)
            new_row_str = ", ".join(f"R{r}" for r in new_rows)
            self._status_label.setText(
                f"已复制行 {row_str} → {new_row_str} (剪贴板 {len(cells)} 帧)")

    def _delete_row(self):
        """删除当前选中行（支持多行）"""
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要删除行中的任意帧")
            return
        cols = max(1, self.model.columns)
        self.model.normalize()
        # 计算所有涉及的行
        rows_to_delete = sorted(set(idx // cols for idx in sel), reverse=True)
        if len(rows_to_delete) == 1 and self.model.rows <= 1:
            QMessageBox.information(self, "提示", "仅剩 1 行, 无法删除")
            return
        # 统计要删除的非空帧数
        removed = 0
        for row in rows_to_delete:
            removed += sum(
                1 for c in range(self.model.columns)
                if self.model.frames[row * self.model.columns + c] is not None)
        row_str = ", ".join(f"R{r}" for r in sorted(rows_to_delete))
        if removed > 0:
            if themed_question(
                    self, "确认",
                    f"删除行 {row_str} 将一并移除其中 {removed} 个帧, "
                    f"后续行上移, 确定吗?") != QMessageBox.Yes:
                return
        # 从最大行号开始删除，避免索引变化
        for row in rows_to_delete:
            self.model.delete_row(row)
        self.canvas.selection.clear()
        self.settings._spin_rows.setValue(self.model.rows)
        self._on_model_changed()
        self._status_label.setText(
            f"已删除行 {row_str} → {self.model.columns}列 × {self.model.rows}行")

    def _delete_col(self):
        """删除当前选中列（支持多列）"""
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要删除列中的任意帧")
            return
        cols = max(1, self.model.columns)
        self.model.normalize()
        # 计算所有涉及的列
        cols_to_delete = sorted(set(idx % cols for idx in sel), reverse=True)
        if len(cols_to_delete) == 1 and cols <= 1:
            QMessageBox.information(self, "提示", "仅剩 1 列, 无法删除")
            return
        # 统计要删除的非空帧数
        removed = 0
        for col in cols_to_delete:
            removed += sum(
                1 for r in range(self.model.rows)
                if self.model.frames[r * cols + col] is not None)
        col_str = ", ".join(f"C{c}" for c in sorted(cols_to_delete))
        if removed > 0:
            if themed_question(
                    self, "确认",
                    f"删除列 {col_str} 将一并移除其中 {removed} 个帧, "
                    f"后续列左移, 确定吗?") != QMessageBox.Yes:
                return
        # 从最大列号开始删除，避免索引变化
        for col in cols_to_delete:
            self.model.delete_col(col)
        self.canvas.selection.clear()
        self.settings._spin_columns.setValue(self.model.columns)
        self._on_model_changed()
        self._status_label.setText(
            f"已删除列 {col_str} → {self.model.columns}列 × {self.model.rows}行")

    def _copy_col(self):
        """复制当前选中列（支持多列）"""
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要复制列中的任意帧")
            return
        old_cols = max(1, self.model.columns)
        old_rows = max(1, self.model.rows)
        col_set = sorted(set(idx % old_cols for idx in sel))
        # 先把选中列装入块级剪贴板（在原地插入之前抓取, 避免索引错位）
        cells: List[Tuple[int, int, Optional[Image.Image]]] = []
        for dc, col in enumerate(col_set):
            for dr in range(old_rows):
                idx = dr * old_cols + col
                f = self.model.frames[idx] if idx < len(self.model.frames) else None
                cells.append((dr, dc, f.copy() if f is not None else None))
        self.canvas._copied_cells = cells
        # 将原 sel 按旧列数转换为 (row, col) 对，复制后用新列数重新映射
        old_sel_positions = [(idx // old_cols, idx % old_cols) for idx in sel]
        if len(col_set) == 1:
            col = col_set[0]
            self.model.copy_col(col)
            new_col = col + 1
            # 仅保留原选择（按新列数重新索引）
            new_sel = set()
            for r, c in old_sel_positions:
                new_sel.add(r * self.model.columns + c)
            self.canvas.selection = new_sel
            self.settings._spin_columns.setValue(self.model.columns)
            self._on_model_changed()
            self._status_label.setText(
                f"已复制列 C{col} → C{new_col} (剪贴板 {len(cells)} 帧)")
        else:
            new_cols = self.model.copy_cols(col_set)
            # 仅保留原选择
            new_sel = set()
            for r, c in old_sel_positions:
                new_sel.add(r * self.model.columns + c)
            self.canvas.selection = new_sel
            self.settings._spin_columns.setValue(self.model.columns)
            self._on_model_changed()
            col_str = ", ".join(f"C{c}" for c in col_set)
            new_col_str = ", ".join(f"C{c}" for c in new_cols)
            self._status_label.setText(
                f"已复制列 {col_str} → {new_col_str} (剪贴板 {len(cells)} 帧)")

    def _flip_horizontal(self):
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要翻转的帧")
            return
        for idx in sel:
            frame = self.model.get_frame(idx)
            if frame is not None:
                self.model.frames[idx] = frame.transpose(Image.FLIP_LEFT_RIGHT)
        self._on_model_changed()
        self._status_label.setText(f"已水平翻转 {len(sel)} 帧")

    # ── 工作模式 / 预览模式 ────────────
    def _on_workflow_mode_changed(self):
        if self._suppress_mode_change:
            return
        if self._mode_merge.isChecked():
            if self.model.frame_count > 0:
                if themed_question(self, "确认",
                        "切换模式将清空当前数据, 确定继续吗?") != QMessageBox.Yes:
                    self._suppress_mode_change = True
                    self._mode_split.setChecked(True)
                    self._suppress_mode_change = False
                    return
                self._reset_model()
            self._list_title.setText("导入的精灵")
            self._btn_import_merge.setEnabled(True)
            self._btn_import_split.setEnabled(False)
            self.settings._btn_resplit.setEnabled(False)
        else:
            if self.model.frame_count > 0:
                if themed_question(self, "确认",
                        "切换模式将清空当前数据, 确定继续吗?") != QMessageBox.Yes:
                    self._suppress_mode_change = True
                    self._mode_merge.setChecked(True)
                    self._suppress_mode_change = False
                    return
                self._reset_model()
            self._list_title.setText("导入的精灵组")
            self._btn_import_merge.setEnabled(False)
            self._btn_import_split.setEnabled(True)
            self.settings._btn_resplit.setEnabled(True)

        self._preview_mode = "grid"
        self._mode_grid.setChecked(True)
        self._show_grid_view()
        self._status_label.setText(
            "已切换到组合模式" if self._mode_merge.isChecked() else "已切换到拆分模式")

    def _reset_model(self):
        self._replace_model()
        self.settings.refresh_values()
        self._on_model_changed()

    def _on_preview_mode_changed(self):
        if self._mode_grid.isChecked():
            self._preview_mode = "grid"
            self.preview_view.stop()
            self._show_grid_view()
            self._zoom_label.setText(f"{int(self.canvas._zoom * 100)}%")
        elif self._mode_single.isChecked():
            self._preview_mode = "single"
            self._show_preview_view()
            self.preview_view.set_mode("single")
            self._refresh_inline_preview(keep_idx=False)
            self._zoom_label.setText(f"{int(self.preview_view._zoom * 100)}%")
        else:
            self._preview_mode = "anim"
            self._show_preview_view()
            self.preview_view.set_mode("anim")
            self._refresh_inline_preview(keep_idx=False)
            self._zoom_label.setText(f"{int(self.preview_view._zoom * 100)}%")

    def _show_grid_view(self):
        self._grid_container.setVisible(True)
        self.preview_view.setVisible(False)
        self._relayout_viewport()

    def _show_preview_view(self):
        self._grid_container.setVisible(False)
        self.preview_view.setVisible(True)
        self._relayout_viewport()

    def _relayout_viewport(self):
        """强制整窗重排, 等效于"最大化→还原"触发的一次自顶向下 resize 级联。

        preview_view 构造起即隐藏, 首次 setVisible(True) 时其内部 QLabel
        仍持有隐藏期间缓存的几何; 仅 activate() 本层布局无法让父级
        (QSplitter / Dock) 重新分配空间, 故需沿父链逐层 invalidate+activate,
        再延迟一帧在显示事件处理完后重设 pixmap。
        """
        w = self._stack
        while w is not None:
            lay = w.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            w = w.parentWidget()
        QTimer.singleShot(0, self._refresh_preview_geometry)

    def _refresh_preview_geometry(self):
        if not self.preview_view.isVisible():
            return
        self.preview_view.updateGeometry()
        if self.preview_view._frames:
            self.preview_view._show_frame(self.preview_view._current)

    def _refresh_inline_preview(self, keep_idx: bool = True):
        if self._preview_mode == "grid":
            return
        if self._preview_mode == "single":
            sel = self.canvas.selection
            if sel:
                idx = self.canvas._last_click_idx
                if idx < 0 or idx not in sel:
                    idx = min(sel)
                frame = self.model.get_frame(idx)
                frames = [frame] if frame is not None else []
            else:
                frames = [f for f in self.model.frames if f is not None][:1]
        else:  # anim
            if self.preview_view._range_sel.isChecked() and self.canvas.selection:
                frames = [self.model.get_frame(i) for i in sorted(self.canvas.selection)]
                frames = [f for f in frames if f is not None]
            else:
                frames = [f for f in self.model.frames if f is not None]
        self.preview_view.set_frames(frames, keep_idx=keep_idx)

    def _on_selection_changed(self):
        try:
            self.image_list._refresh_highlight()
        except Exception:
            pass
        if self._preview_mode == "grid":
            return
        if self._preview_mode == "single":
            self._refresh_inline_preview(keep_idx=False)
        elif self.preview_view._range_sel.isChecked():
            self._refresh_inline_preview(keep_idx=False)

    # ── 共享缩放 ───────────────────────
    def _shared_zoom_step(self, delta: float):
        if self._preview_mode == "grid":
            self.canvas.zoom_step(delta)
        else:
            self.preview_view.zoom_step(delta)

    def _shared_zoom_reset(self):
        if self._preview_mode == "grid":
            self.canvas.zoom_reset()
        else:
            self.preview_view.zoom_reset()

    # ── 预览 ───────────────────────────
    def _preview_selected(self):
        frames = self._get_selected_frames()
        if not frames:
            QMessageBox.information(self, "提示",
                "请先在画布上选择要预览的帧\n(点击选择, Ctrl+点击多选, Shift+点击范围选择)")
            return
        self.preview_view._range_sel.setChecked(True)
        self._mode_anim.setChecked(True)

    def _preview_all(self):
        self.model.normalize()
        frames = [f for f in self.model.frames if f is not None]
        if not frames:
            QMessageBox.information(self, "提示", "没有可预览的帧")
            return
        self.preview_view._range_all.setChecked(True)
        self._mode_anim.setChecked(True)

    def _get_selected_frames(self) -> List[Image.Image]:
        frames = []
        for idx in sorted(self.canvas.selection):
            frame = self.model.get_frame(idx)
            if frame is not None:
                frames.append(frame.copy())
        return frames

    # ── 保存 ───────────────────────────
    def _save(self):
        self.settings._save_current_fmt()

    # ── 主题切换 ───────────────────────
    def _toggle_theme(self):
        toggle_theme_in_family(self)
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)

        # 强制同步视口背景 (QSS 无法穿透 QGraphicsScene 底层)
        bg_color = QColor(business_colors("spritesheet", self._theme_id)["canvas_bg"])
        self.canvas.setBackgroundBrush(QBrush(bg_color))
        self.preview_view._disp.setObjectName("GamePreview")
        self.preview_view._disp.style().unpolish(self.preview_view._disp)
        self.preview_view._disp.style().polish(self.preview_view._disp)
        self.canvas.redraw()


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main():
    if not HAS_PIL:
        print("错误: 需要安装 Pillow 库")
        print("  pip install Pillow")
        sys.exit(1)
    run_editor(SpriteSheetEditorWindow, "Spritesheet Editor",
               filepath=sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    main()
