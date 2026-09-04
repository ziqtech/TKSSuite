"""
主题切换组件 —— 所有编辑器与启动器的统一主题入口。

交互约定：

* 菜单栏的"主题"菜单（:func:`create_theme_menu`）可任选 4 个主题，
  当前主题带勾选标记；
* 工具栏"切换主题"按钮与既有快捷键统一接
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
    sync_themed_icons(window, value)

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


# 按钮标签 → 图标名 (P4-1 自动图标): 标签精确匹配的按钮在主题应用时
# 自动获得对应 SVG 图标, 深浅变体自动切换; 未命中标签保持纯文本。
_LABEL_ICONS: dict[str, str] = {
    "切换主题": "theme",
    "确定": "apply", "应用": "apply", "应用修改": "apply",
    "应用全局修改": "apply", "应用事件修改": "apply", "应用队伍修改": "apply",
    "修改选中": "apply", "替换选中": "image", "替换当前层": "image",
    "搜索": "search", "选择…": "search",
    "刷新": "refresh", "重新加载": "refresh",
    "保存": "save", "保存 / 另存为": "save",
    "新增": "add", "新增条目": "add", "新增记录": "add", "新增物品": "add",
    "新增区段": "add",
    "添加条目": "add", "添加图片": "add", "添加…": "add", "区段": "add",
    "删除": "delete", "删除选中": "delete", "删除实体": "delete", "移除区段": "delete",
    "清空": "delete", "清除": "delete",
    "打开目录": "open", "打开 GXP": "open", "打开 GRP": "open",
    "加载TKS目录": "open",
    "撤销修改": "undo", "撤销": "undo", "重置": "refresh", "重置默认": "refresh",
    "恢复默认": "refresh",
    "播放": "play", "播放全部": "play", "播放选中": "play",
    "暂停": "pause", "暂停全部": "pause",
    "伪彩导出": "palette", "伪彩导入": "palette", "导出当前层": "export",
    "替换音频": "music",
    "编辑": "pencil",
    # 第二轮核对补充 (launcher 对话框 / configs 面板 / 各编辑器残留)
    "过滤": "wand",
    "恢复选中备份": "package", "执行打包": "package", "执行合并": "package",
    "执行拆分": "package",
    "导入图集": "import", "导入 .tksmod": "import", "导入外部图片": "import",
    "导出当前分组": "export", "导出网格图集": "export",
    "导出为 .tksmod": "export", "导出日志…": "export", "导出 24位 PNG": "export",
    "选择物品…": "search", "选择…": "search", "定位": "search",
    "创建备份": "save", "另存为…": "save", "删除选中备份": "delete",
    "上传图片": "image", "逐帧": "camera", "动画": "clapper",
    "姓名宏": "pencil", "修复验证": "wrench",
    "脚本模板": "copy", "复制到空槽": "copy", "复制行": "copy",
    "\u2715": "close", "浏览…": "open", "打开…": "open", "打开 FONT9696…": "open",
    "确定生成": "apply", "确认合并": "apply", "确认拆分": "apply",
    "全选": "apply",
    "新建物品": "new", "新建": "new",
    "重新扫描": "refresh", "重新生成": "refresh",
    "新增音效": "add", "上一帧": "prev", "下一帧": "next",
    # 第三轮核对补充
    "刷新列表": "refresh", "重新拆分": "refresh",
    "从目录添加…": "add", "添加文件…": "add",
    "导入图片": "import", "导入全部头像": "import",
    "导出选中帧": "export", "导出全部头像": "export", "导出每帧头像": "export",
    "导出全部 (每帧)": "export",
    "删除行": "delete", "删除列": "delete", "移除选中": "delete", "全清": "delete",
    "复制列": "copy",
    "预览": "image", "预览选中": "image", "预览全部": "image",
    "确认并继续": "apply", "选择图片…": "image",
}


def sync_themed_icons(window, theme_id: str) -> None:
    """为窗口内全部按钮挂主题感知图标 (P4-1)。

    图标来源优先级:
      1. 动态属性 themedIcon (显式指定, 见 ui_helpers.set_themed_icon);
      2. 按钮文本精确匹配 _LABEL_ICONS (自动);
      3. 均未命中则保持无图标 (纯文本, 不做运行时文本改写)。
    在 apply_theme_to_window 中自动执行, 主题切换时深浅变体同步更换。
    """
    from PySide6.QtWidgets import QAbstractButton
    for button in window.findChildren(QAbstractButton):
        name = button.property("themedIcon")
        if not name:
            name = _LABEL_ICONS.get(button.text().strip())
        if name:
            button.setIcon(theme_manager.themed_icon(name, theme_id))


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
