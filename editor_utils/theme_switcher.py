"""
主题切换组件 —— 所有编辑器与启动器的统一主题入口。

交互约定：

* 菜单栏的"主题"菜单（:func:`create_theme_menu`）可任选 4 个主题，
  当前主题带勾选标记；
* 工具栏"🌗 切换主题"按钮与既有快捷键统一接
  :func:`toggle_theme_in_family`，在当前主题族（modern / classic）内
  快速深/浅互换，不弹菜单；
* 主题应用只走 :func:`apply_theme_to_window`：QSS + 调色板 + Windows
  标题栏一次完成，并同步窗口上的兼容属性（``_is_dark`` 等）与内嵌
  ``EditorTabWidget`` 的自绘边框。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QMenu

from editor_utils import theme_manager, theme_tokens
from editor_utils.window_theme import apply_titlebar_theme

# 窗口上记录当前主题的权威属性，供 tab_widget 等组件读取。
THEME_ATTR = "_theme_id"


def _accent_swatch_icon(theme_id: str) -> QIcon:
    """主题菜单条目的 accent 色块小图标 (P4-6), 让用户切换前有颜色预期。"""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme_tokens.SLOTS["accent"][
        theme_manager.THEME_ORDER.index(theme_id)])
    painter.setBrush(color)
    painter.setPen(QPen(QColor(128, 128, 128, 160), 1))
    painter.drawRoundedRect(1, 1, 10, 10, 3, 3)
    painter.end()
    return QIcon(pixmap)


def current_window_theme(window) -> str:
    """返回窗口当前主题；窗口尚未初始化时回退到持久化/系统默认。"""
    value = getattr(window, THEME_ATTR, None)
    if value is not None and str(value) in theme_manager.THEMES:
        return str(value)
    return theme_manager.load_initial_theme()


def apply_theme_to_window(window, theme_id: str, *, persist: bool = True) -> str:
    """把主题应用到窗口并同步所有派生状态，返回生效的主题 id。

    ``persist=False`` 用于启动初始化：沿用存档或系统默认，不把检测结果
    写回注册表；用户显式切换（菜单/按钮）使用默认值 ``True``。
    """
    value = theme_manager.normalize_theme(theme_id)
    if persist:
        theme_manager.set_current_theme(value)
    spec = theme_manager.THEMES[value]

    theme_manager.apply_theme(window, value)
    apply_titlebar_theme(window, value)

    # 兼容属性：原生对话框主题过滤器、启动器自绘组件等仍按深浅读取。
    # _is_dark 是全套件通用约定，无条件维护；其余两个仅在窗口已使用时同步。
    window._is_dark = spec.is_dark
    for attr in ("_dark_mode", "is_dark_theme"):
        if hasattr(window, attr):
            setattr(window, attr, spec.is_dark)
    setattr(window, THEME_ATTR, value)

    _sync_tab_widgets(window, spec)

    hook = getattr(window, "_on_theme_applied", None)
    if callable(hook):
        hook(value)
    return value


def _sync_tab_widgets(window, spec):
    """把主题同步给窗口内所有自绘 Tab（含动态创建前的既有实例）。"""
    try:
        from editor_utils.tab_widget import EditorTabWidget
    except ImportError:
        return
    for child in window.findChildren(EditorTabWidget):
        child.set_theme(spec.is_dark, spec.family)


def toggle_theme_in_family(window) -> str:
    """族内深/浅快速切换（工具栏按钮与快捷键的统一槽函数）。"""
    current = current_window_theme(window)
    return apply_theme_to_window(window, theme_manager.family_toggle(current))


def create_theme_menu(window, title: str = "主题(&T)") -> QMenu:
    """生成菜单栏用的"主题"菜单：4 个主题互斥勾选，随当前主题同步。"""
    menu = QMenu(title, window)
    group = QActionGroup(menu)
    group.setExclusive(True)

    actions: dict[str, QAction] = {}
    for theme_id in theme_manager.THEME_ORDER:
        spec = theme_manager.THEMES[theme_id]
        action = QAction(spec.display_name, window, checkable=True)
        action.setStatusTip(f"切换到{spec.display_name}主题")
        action.setIcon(_accent_swatch_icon(theme_id))
        group.addAction(action)
        menu.addAction(action)
        action.triggered.connect(
            lambda _checked=False, _window=window, _tid=theme_id:
                apply_theme_to_window(_window, _tid)
        )
        actions[theme_id] = action

    def _sync_checks():
        current = current_window_theme(window)
        for theme_id, action in actions.items():
            action.setChecked(theme_id == current)

    menu.aboutToShow.connect(_sync_checks)

    # 族内快速切换作为标准项进入主题菜单 (Ctrl+T) — P3-8: 全编辑器统一
    # "Ctrl+T 快速切深浅" 行为; 已自带 Ctrl+T 绑定的编辑器应移除自有绑定。
    quick = QAction("族内快速切换 (深/浅)", window)
    quick.setStatusTip("在当前主题族 (modern/classic) 内快速切换深色/浅色 (Ctrl+T)")
    quick.setShortcut(QKeySequence("Ctrl+T"))
    quick.triggered.connect(lambda: toggle_theme_in_family(window))
    menu.addSeparator()
    menu.addAction(quick)
    return menu
