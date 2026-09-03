"""app_shell — 编辑器应用壳：统一启动样板与主窗口样板（阶段 3）。

所有编辑器的 main() 与窗口初始化样板收敛到此：

  * :func:`run_editor` — 吸收 18 个入口逐字重复的 13 行 main()
    （单实例 → QApplication → 对话框主题过滤 → Fusion → 翻译器 →
    图标 → 窗口 → exec）
  * :class:`EditorMainWindow` — 吸收窗口初始化样板（objectName/标题/
    尺寸/主题初始化）与五件套（_create_dock/_apply_theme/_toggle_theme/
    _show_help/_show_about）

子类约定::

    class XxxEditorWindow(EditorMainWindow):
        EDITOR_KEY = "xxx_editor"        # version.py 的 app_id
        DEFAULT_SIZE = (1100, 680)
        MIN_SIZE = (950, 550)            # 可省略
        HELP_TEXT = "……"                 # 帮助说明全文

        def _init_data(self): ...        # 可选: 属性初始化 (主题应用前)
        def _build_ui(self): ...         # 必须: 菜单栏 + 中心部件
            # 菜单栏追加标准"主题/帮助"菜单:
            self.add_standard_menus(self.menuBar())

    def main():
        run_editor(XxxEditorWindow, "TKXxx Editor")

执行顺序与原样板一致：属性初始化 → 主题初始化（persist=False）→ UI 构建。
子类需要主题派生同步时实现 ``_on_theme_applied``（theme_switcher 统一钩子），
需要额外行为时覆盖五件套并按需调用 ``super()``。
"""
from __future__ import annotations

import inspect
import os
import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from editor_utils import theme_manager
from editor_utils.dock_components import create_dock
from editor_utils.theme_switcher import (
    apply_theme_to_window, create_theme_menu, current_window_theme,
    toggle_theme_in_family,
)
from editor_utils.ui_helpers import themed_messagebox
from editor_utils.version import format_about_header, format_title


class EditorMainWindow(QMainWindow):
    """编辑器主窗口基类 — 见模块 docstring 的子类约定。"""

    EDITOR_KEY: str = ""
    DEFAULT_SIZE: tuple[int, int] = (1100, 680)
    MIN_SIZE: tuple[int, int] | None = None
    HELP_TEXT: str = ""
    ABOUT_TITLE: str = "关于编辑器"  # 查看器类应用可覆盖 (如 tks_book 用"关于查看器")
    THEME_MENU_TITLE: str = "主题(&T)"  # 键位冲突的编辑器可覆盖 (如 save 用 &M)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EditorWindow")
        self._dirty_flag = False  # _dirty property 的存储位
        self.setWindowTitle(format_title(self.EDITOR_KEY))
        self.resize(*self.DEFAULT_SIZE)
        if self.MIN_SIZE:
            self.setMinimumSize(*self.MIN_SIZE)
        # 窗口图标继承自 QApplication（run_editor 已设置，无需逐窗口设置）
        self._init_data()
        # 主题初始化: 跟随持久化选择, 无存档时按系统深浅色
        apply_theme_to_window(self, theme_manager.load_initial_theme(),
                              persist=False)
        self._build_ui()
        self._after_build()

    # ── 脏状态 (统一标题栏 * 修改标记) ────────────────────────
    # _dirty 以 property 承载: 子类既有的 self._dirty = True/False 赋值
    # 自动同步标题栏修改标记, 无需逐编辑器改造。
    @property
    def _dirty(self) -> bool:
        return self._dirty_flag

    @_dirty.setter
    def _dirty(self, value) -> None:
        self._dirty_flag = bool(value)
        self.setWindowModified(self._dirty_flag)

    def set_dirty(self, dirty) -> None:
        """统一脏状态入口: 置/清修改标记 (标题栏 * 号)。

        子类在数据变更处调用 set_dirty(True), 保存/加载后调用
        set_dirty(False); 需追加派生行为时覆盖并调用 super()。
        直接给 self._dirty 赋值等效。
        """
        self._dirty = dirty

    # ── 子类钩子 ──────────────────────────────────────────────
    def _init_data(self):
        """子类钩子: 属性/数据初始化 (在主题应用与 UI 构建之前)。"""

    def _build_ui(self):
        """子类必须实现: 构建菜单栏与中心部件。"""
        raise NotImplementedError

    def _after_build(self):
        """子类钩子: UI 构建完成后的收尾 (如路径标签刷新、初始状态)。"""

    # ── 样板五件套 (子类可覆盖) ────────────────────────────────
    def _create_dock(self, title, widget_content):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components。"""
        return create_dock(title, widget_content)

    def _apply_theme(self):
        """重新应用当前主题 (子类可覆盖以追加派生同步)。"""
        apply_theme_to_window(self, current_window_theme(self))

    def _toggle_theme(self):
        """族内深浅快速切换 (子类可覆盖以追加刷新)。"""
        toggle_theme_in_family(self)

    def _show_help(self):
        if self.HELP_TEXT:
            themed_messagebox(self, QMessageBox.Information, "使用说明",
                              self.HELP_TEXT)

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, self.ABOUT_TITLE,
                          format_about_header(self.EDITOR_KEY))

    # ── 标准菜单 ─────────────────────────────────────────────
    def _extra_help_actions(self):
        """子类钩子: 帮助菜单在"关于"前插入的专属项。

        返回 [(label, slot), …]; 默认无。
        """
        return []

    def add_theme_submenu(self, parent_menu):
        """把标准"主题"菜单挂到指定父菜单 (顶级或嵌套均可)。"""
        parent_menu.addMenu(create_theme_menu(self, self.THEME_MENU_TITLE))

    def add_help_menu(self, menubar):
        """在菜单栏追加标准的"帮助"菜单 (含 _extra_help_actions 专属项)。"""
        help_menu = menubar.addMenu("帮助(&H)")
        action_help = QAction("帮助说明", self)
        action_help.triggered.connect(self._show_help)
        help_menu.addAction(action_help)
        for label, slot in self._extra_help_actions():
            help_menu.addAction(label).triggered.connect(slot)
        action_about = QAction("关于编辑器", self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)
        return help_menu

    def add_standard_menus(self, menubar):
        """在菜单栏追加标准的"主题"与"帮助"菜单 (编辑器各异的专业
        菜单由子类在调用本方法前自行构建)。"""
        self.add_theme_submenu(menubar)
        self.add_help_menu(menubar)


def run_editor(window_cls, app_name: str | None = None, *,
               app_version: str | None = None,
               org_name: str | None = None,
               icon_dir: str | None = None,
               translator: bool = True,
               **window_kwargs):
    """编辑器统一入口 — 替代各编辑器逐字重复的 main() 样板。

    Args:
        window_cls: EditorMainWindow 子类 (或任意主窗口类, 如 launcher 的 MainWindow)
        app_name: QApplication 名称 (如 "TKShop Editor"); None 则不设置
        app_version / org_name: QApplication 元信息 (launcher 等特殊入口用)
        icon_dir: 图标查找目录; None 则取 window_cls 所在目录
        translator: 是否装载 Qt 中文翻译器 (launcher 原本不装, 传 False 保持行为)
        **window_kwargs: 传给窗口构造函数的额外参数 (如 filepath)
    """
    from editor_utils.app_init import (
        ensure_single_instance, install_translator, setup_app_icon)
    from editor_utils.ui_helpers import install_dialog_theme_filter

    ensure_single_instance()
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")  # Fusion 样式, 避免 Windows 原生样式覆盖 QSS
    if app_name:
        app.setApplicationName(app_name)
    if app_version:
        app.setApplicationVersion(app_version)
    if org_name:
        app.setOrganizationName(org_name)
    _t = None
    if translator:
        _t = install_translator(app)  # 保持引用防 GC
    setup_app_icon(app, icon_dir or os.path.dirname(inspect.getfile(window_cls)))

    window = window_cls(**window_kwargs)
    window.show()

    sys.exit(app.exec())
