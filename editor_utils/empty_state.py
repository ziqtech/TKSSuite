"""Empty state 引导层 — 数据未加载时的居中引导 (可选附加项)。

在宿主控件 (列表区/QSplitter 等) 上覆盖一层透明引导: 图标 + 标题 +
快捷键提示, 替代未加载数据时的空白面板。典型用法::

    self._empty_state = EmptyStateOverlay(
        host, title="尚未加载数据", hint="Ctrl+O 打开数据",
        icon_name="open", activate=self._load_tks_dir)
    ...
    self._empty_state.set_empty(not loaded)   # 数据加载/清空时切换

说明:
  * 覆盖层铺满宿主并随宿主 resize 自动同步, 不拦截滚轮 (转发给宿主);
  * 提供 activate 回调时整层可点击, 等价于引导的快捷键操作;
  * 标题/提示配色走主题 QSS (emptyStateTitle/emptyStateHint), 图标经
    theme_manager.themed_icon 取深浅变体, refresh() 供主题切换后重取。
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from editor_utils import theme_manager, theme_switcher

_ICON_SIZE = 56


class EmptyStateOverlay(QWidget):
    """宿主区域的居中引导覆盖层 — set_empty(bool) 控制显隐。

    host 必须是普通容器 (QWidget); 覆盖层作为其子控件, 不可挂到
    QSplitter 上 (QSplitter 会把子控件误纳入分割面板管理)。
    需要只覆盖 host 内某个子区域时传 track (如 host 里的 QSplitter),
    几何随 track 同步; 默认铺满 host。
    """

    def __init__(self, host: QWidget, title: str, hint: str,
                 icon_name: str = "open", activate=None, track: QWidget = None):
        super().__init__(host)
        self._host = host
        self._track = track or host
        self._icon_name = icon_name
        self._activate = activate
        self.setObjectName("EmptyStateOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, activate is None)
        self.setCursor(Qt.PointingHandCursor if activate else Qt.ArrowCursor)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon_label)

        title_label = QLabel(title)
        title_label.setObjectName("emptyStateTitle")
        title_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setObjectName("emptyStateHint")
        hint_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint_label)

        self._track.installEventFilter(self)
        self.hide()
        self._refresh_icon()

    # ── 显隐 ──
    def set_empty(self, empty: bool) -> None:
        """数据未加载时 True 显示引导; 加载后 False 隐藏。"""
        self._refresh_icon()
        self.setVisible(bool(empty))
        if empty:
            self.raise_()
            self.setGeometry(self._track.geometry())

    def refresh(self) -> None:
        """主题切换后重取图标深浅变体 (标题/提示配色由 QSS 自动更新)。"""
        self._refresh_icon()

    # ── 事件 ──
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._track and event.type() == QEvent.Resize:
            self.setGeometry(self._track.geometry())
        return False

    def mousePressEvent(self, event) -> None:
        if self._activate is not None:
            self._activate()
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:
        # 覆盖层不消费滚轮, 转发宿主 (宿主内的滚动区域/表头保持可滚)
        event.ignore()

    # ── 内部 ──
    def _refresh_icon(self) -> None:
        theme_id = theme_switcher.current_window_theme(self.window())
        self._icon_label.setPixmap(
            theme_manager.themed_icon(self._icon_name, theme_id)
            .pixmap(_ICON_SIZE, _ICON_SIZE))
