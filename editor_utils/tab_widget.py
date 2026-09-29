"""通用编辑器标签页组件。

所有 PySide6 编辑器统一使用 :class:`EditorTabWidget`，集中处理：

* TabBar 的基础行为和跨编辑器的一致性；
* 普通卡片式标签页与连续内容面板（flat pane）两种布局；
* 内容控件覆盖 Qt 原生 pane 边框时的轻量边框绘制。

颜色和字体仍由编辑器主题 QSS 负责，这个模块只处理 Qt 原生控件
难以通过 QSS 稳定解决的几何和绘制细节。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QTabBar, QTabWidget, QToolButton,
                               QWidget)

from editor_utils import theme_tokens


class EditorTabBar(QTabBar):
    """编辑器统一 TabBar。

    ``extend_to_host`` 用于连续内容面板：让底边线覆盖整个内容区，
    而不是只覆盖已有标签的宽度。
    左右滚动按钮 (标签溢出时的 ◀/▶) 钉成正方形: 默认按字体度量
    得到的宽高比例失衡。
    """

    SCROLLER_SIDE = 20

    def __init__(self, parent: QWidget | None = None, *, extend_to_host=False):
        super().__init__(parent)
        self._extend_to_host = bool(extend_to_host)
        self._sync_scroller_buttons()

    def _sync_scroller_buttons(self):
        for btn in self.findChildren(QToolButton):
            btn.setFixedSize(self.SCROLLER_SIDE, self.SCROLLER_SIDE)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_scroller_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_scroller_buttons()

    def sizeHint(self):
        hint = super().sizeHint()
        if self._extend_to_host:
            host = self.parentWidget()
            if host is not None:
                hint.setWidth(max(hint.width(), host.width()))
        return hint


class EditorTabPane(QWidget):
    """连续内容面板的边框覆盖层。

    Qt 的 ``QTabWidget::pane`` 会被其中的 ``QScrollArea`` 等子控件覆盖，
    导致底部圆角或侧边线在不同平台不完整。这个透明覆盖层只绘制下方
    内容区域的外框，并把鼠标事件继续交给真正的内容控件。
    """

    RADIUS = float(theme_tokens.SLOTS["radius_md"][0].rstrip("px"))

    # 自绘边框色按主题族区分：modern 为中性灰，classic 为 Godot 蓝灰。
    # bd_regular 槽位 (P3-6 收编) 存的是完整 CSS 边框串 "1px solid #xxx"，
    # QColor 解析不了整串会静默退成纯黑画笔（flat 标签页三边纯黑边框的
    # 根因），故只取末段色值。
    _bd = tuple(v.split()[-1] for v in theme_tokens.SLOTS["bd_regular"])
    _BORDER_COLORS = {
        ("modern", True): _bd[0],
        ("modern", False): _bd[1],
        ("classic", True): _bd[2],
        ("classic", False): _bd[3],
    }

    def __init__(self, parent: QTabWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._dark = True
        self._family = "modern"

    def set_theme(self, dark: bool, family: str = "modern"):
        """设置边框颜色主题；面板背景和标签颜色由 QSS 处理。"""
        dark = bool(dark)
        family = family if family in ("modern", "classic") else "modern"
        if self._dark != dark or self._family != family:
            self._dark = dark
            self._family = family
            self.update()

    def paintEvent(self, event):
        del event
        parent = self.parentWidget()
        if not isinstance(parent, QTabWidget):
            return

        bar = parent.tabBar()
        if bar is None:
            return
        top = bar.height()
        if top >= self.height():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        border_color = self._BORDER_COLORS[(self._family, self._dark)]
        painter.setPen(QPen(QColor(border_color), 1))
        painter.setBrush(Qt.NoBrush)

        width = float(max(self.width() - 1, 1))
        bottom = float(self.height() - 1)
        radius = min(self.RADIUS, width / 2, max((bottom - top) / 2, 0))

        path = QPainterPath()
        path.moveTo(0.0, float(top))
        path.lineTo(0.0, bottom - radius)
        path.arcTo(
            QRectF(0.0, bottom - 2 * radius, 2 * radius, 2 * radius),
            180.0,
            90.0,
        )
        path.lineTo(width - radius, bottom)
        path.arcTo(
            QRectF(width - 2 * radius, bottom - 2 * radius, 2 * radius, 2 * radius),
            270.0,
            90.0,
        )
        path.lineTo(width, float(top))
        painter.drawPath(path)
        painter.end()


class EditorTabWidget(QTabWidget):
    """编辑器通用标签页容器。

    默认使用普通卡片式 pane；传入 ``flat=True`` 时使用连续内容面板，
    适合 WarPC 这类右侧主编辑区域。两种模式都保留 QTabWidget 的完整
    API，因此旧代码只需替换构造类即可。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        flat: bool = False,
        object_name: str | None = None,
    ):
        super().__init__(parent)
        self._flat = bool(flat)
        self.setObjectName(object_name or ("EditorFlatTabs" if flat else "EditorTabs"))
        self.setProperty("tabStyle", "flat" if self._flat else "card")

        self.setTabBar(EditorTabBar(extend_to_host=self._flat))
        self.setDocumentMode(self._flat)
        self.tabBar().setObjectName("EditorTabBar")
        self.tabBar().setExpanding(False)
        # 主题 QSS 负责绘制标签与 pane 的分界线，关闭 Fusion 原生 base 线，
        # 避免不同平台出现重复或错位的横线。
        self.tabBar().setDrawBase(False)

        self._tab_pane = EditorTabPane(self) if self._flat else None
        if self._tab_pane is not None:
            self._tab_pane.setGeometry(self.rect())
            self._tab_pane.show()
            self._tab_pane.raise_()

    def setCornerWidget(self, widget, corner=Qt.TopRightCorner):
        """统一处理 Tab 右侧附加区域，避免覆盖标签栏底部边线。

        QTabWidget 的 corner widget 会覆盖 TabBar 右侧区域，透明控件即使
        写了 ``border-bottom`` 也不会实际绘制边线。交给主题 QSS 绘制实心
        背景和底线，并将内部内容顶部对齐，让附加控件略微上移且线保持连续。
        """
        if widget is not None:
            widget.setObjectName("EditorTabCorner")
            # 透明背景会让 Qt Style Sheet 跳过 QWidget 的 border 绘制，
            # 从而把 TabBar 右侧底线变成透明区域；由主题 QSS 提供实心底色。
            widget.setAttribute(Qt.WA_TranslucentBackground, False)
            layout = widget.layout()
            if layout is not None:
                margins = layout.contentsMargins()
                layout.setContentsMargins(
                    margins.left(), margins.top(), margins.right(),
                    max(2, margins.bottom()),
                )
                layout.setAlignment(Qt.AlignTop)
        super().setCornerWidget(widget, corner)

    @property
    def tab_pane(self) -> EditorTabPane | None:
        """返回 flat 模式的 pane 覆盖层，普通模式返回 ``None``。"""
        return self._tab_pane

    def set_theme(self, dark: bool, family: str = "modern"):
        """同步 pane 边框主题；普通模式无需额外绘制。"""
        if self._tab_pane is not None:
            self._tab_pane.set_theme(dark, family)
        # TKSBook 等页面会动态创建内嵌 Tab，统一向下同步主题，避免
        # 内嵌 Pane 在浅色主题下仍保留默认深色边框。
        for child in self.findChildren(EditorTabWidget):
            child.set_theme(dark, family)

    def _sync_theme_from_ancestors(self):
        """动态创建的 Tab 首次显示时，从宿主编辑器读取当前主题。"""
        from editor_utils import theme_manager

        parent = self.parentWidget()
        while parent is not None:
            theme_id = getattr(parent, "_theme_id", None)
            if theme_id is not None and str(theme_id) in theme_manager.THEMES:
                spec = theme_manager.THEMES[str(theme_id)]
                self.set_theme(spec.is_dark, spec.family)
                return
            for attr in ("_is_dark", "is_dark_theme", "_dark_mode"):
                value = getattr(parent, attr, None)
                if value is not None:
                    self.set_theme(bool(value))
                    return
            parent = parent.parentWidget()

        app = QApplication.instance()
        if app is not None:
            self.set_theme(app.styleHints().colorScheme() == Qt.ColorScheme.Dark)

    def _raise_tab_pane(self):
        if self._tab_pane is not None:
            self._tab_pane.setGeometry(self.rect())
            self._tab_pane.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._raise_tab_pane()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_theme_from_ancestors()
        self._raise_tab_pane()
