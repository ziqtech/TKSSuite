"""通用编辑器下拉框。

所有 PySide 编辑器和编辑器弹窗统一使用 :class:`EditorComboBox`，获得：

* 在滚动面板中悬停滚轮不会误切换选项；
* 使用 Qt 原生 ``QMenu`` 弹层，避免 ``QComboBox`` 默认视图在不同平台
  下出现额外矩形边框、错位或顶层窗口生命周期问题；
* 菜单始终从控件下沿弹出，并自动限制在当前屏幕可用区域内；
* 条目超过上限时改用 :class:`EditorComboListPopup` 可滚动列表弹层
  (真实滚动条), 而非无限增高的菜单。

弹层的具体颜色由 editor_themes 下四个主题 QSS（gpt-dark/gpt-light/
classic-dark/classic-light）中的 ``QMenu#EditorComboMenu`` /
``QWidget#EditorComboPopup`` / ``QListWidget#EditorComboList`` 统一控制。
"""

import sys

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBitmap, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QListWidget,
    QListWidgetItem, QMenu, QVBoxLayout, QWidget,
)


def _apply_rounded_window_region(widget, radius=8):
    """将顶层弹出窗口裁剪为圆角矩形。

    Windows 上 QWidget 弹层的 QSS ``border-radius`` 只圆角化边框, 不会裁剪
    不透明背景填充, 四角会露出矩形背景形成锐角; 此处用原生窗口区域 API
    裁剪整个窗口 (与 :class:`RoundedComboMenu` 行为一致), 其他平台回退到
    QBitmap mask。供 QMenu 弹层与可滚动列表弹层共用。
    """
    if sys.platform == "win32":
        try:
            import ctypes

            width = max(1, widget.width())
            height = max(1, widget.height())
            diameter = radius * 2
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            gdi32.CreateRoundRectRgn.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int,
            ]
            user32.SetWindowRgn.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool,
            ]
            region = gdi32.CreateRoundRectRgn(
                0, 0, width + 1, height + 1, diameter, diameter,
            )
            if region:
                hwnd = int(widget.winId())
                user32.SetWindowRgn(ctypes.c_void_p(hwnd), region, True)
            return
        except Exception:
            pass

    bitmap = QBitmap(widget.size())
    bitmap.fill(Qt.color0)
    painter = QPainter(bitmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.color1)
    painter.drawRoundedRect(
        QRectF(0, 0, widget.width(), widget.height()), radius, radius)
    painter.end()
    widget.setMask(bitmap)


class RoundedComboMenu(QMenu):
    """带统一圆角裁剪的下拉菜单。

    Windows 的 QMenu 弹出层通常不会可靠遵守 QSS 的底部 border-radius，
    这里通过原生窗口区域 API 将整个菜单裁剪成圆角矩形；其他平台回退到
    QBitmap mask。
    """

    RADIUS = 8

    def _apply_window_region(self):
        _apply_rounded_window_region(self, self.RADIUS)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_window_region()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_window_region()


class EditorComboListPopup(QWidget):
    """可滚动下拉弹层 — 条目超过上限时的列表弹窗, 带真实垂直滚动条。

    QMenu 的 ``setMaximumHeight`` 并不会启用其内部滚动, 超出条目会被
    直接裁掉且不可达; 且条目极多时 QMenu 内部按屏幕高度截断的 sizeHint
    会干扰弹出位置 (菜单被翻到屏幕顶部)。因此条目较多时改用本组件:
    ``Qt.Popup`` 顶层窗口 (点击外部/Escape 自动关闭) + QListWidget 滚动。
    观感由主题 QSS 的 ``QWidget#EditorComboPopup`` / ``QListWidget#EditorComboList``
    控制, 与 ``QMenu#EditorComboMenu`` 弹层配色一致。
    """

    #: 选中某条目时发出 (参数为该条目的 data)
    selected = Signal(int)

    OBJECT_NAME = "EditorComboPopup"
    LIST_OBJECT_NAME = "EditorComboList"
    RADIUS = 8

    def __init__(self, parent=None, max_visible=10):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setObjectName(self.OBJECT_NAME)
        self._max_visible = max(1, int(max_visible))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        self.list = QListWidget(self)
        self.list.setObjectName(self.LIST_OBJECT_NAME)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.itemClicked.connect(self._choose)
        self.list.itemActivated.connect(self._choose)
        lay.addWidget(self.list)

    def _apply_window_region(self):
        _apply_rounded_window_region(self, self.RADIUS)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_window_region()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_window_region()

    def set_items(self, items, current=None):
        """填充条目。

        items: [(icon, text, data, enabled), ...] 的可迭代对象;
        current: 初始选中条目的 data (无则不选中)。
        """
        self.list.clear()
        cur_row = -1
        for row, (icon, text, data, enabled) in enumerate(items):
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, data)
            if not enabled:
                item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
            if current is not None and data == current:
                cur_row = row
        if cur_row >= 0:
            self.list.setCurrentRow(cur_row)
            # 当前项若在可见区之外, 打开时滚动到可见
            self.list.scrollToItem(
                self.list.item(cur_row), QAbstractItemView.EnsureVisible)

    def _choose(self, item):
        self.selected.emit(int(item.data(Qt.UserRole)))
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def popup_below(self, anchor, width):
        """在 anchor 控件正下方弹出; 下方空间不足时翻到上方, 并钳制在屏幕内。"""
        row_h = self.list.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 24
        rows = min(self.list.count(), self._max_visible)
        self.list.setFixedHeight(row_h * rows)
        # 总高实测自布局 sizeHint (列表定高 + 上下 margins + QSS 盒模型
        # 调整后的 contentsMargins), QSS 改边框/边距后自动跟随, 不再硬编码
        height = max(self.sizeHint().height(), row_h * rows)

        below = anchor.mapToGlobal(QPoint(0, anchor.height()))
        screen = QApplication.screenAt(below) or QApplication.primaryScreen()
        x, y = below.x(), below.y()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(1, available.width()))
            x = max(available.left(), min(x, available.right() - width + 1))
            if y + height > available.bottom() + 1:
                y = anchor.mapToGlobal(QPoint(0, 0)).y() - height
            y = max(available.top(), y)
        else:
            width = max(1, width)

        self.setFixedSize(width, height)
        self.move(x, y)
        self.show()
        # Qt.Popup 抓取键盘后把焦点交给列表, 支持方向键导航与 Enter 选择
        self.list.setFocus()


class EditorComboBox(QComboBox):
    """编辑器通用下拉框。

    组件保留 ``QComboBox`` 的数据模型、信号和编辑接口，仅替换弹出层；
    因此可直接用于普通表单、滚动页、QDialog 以及 item delegate。

    条目数不超过 :attr:`MAX_VISIBLE_ITEMS` 时使用 ``QMenu`` 弹层
    (带选中勾选标记); 超过时改用 :class:`EditorComboListPopup`
    可滚动列表弹层 (真实滚动条, 最多直接显示 MAX_VISIBLE_ITEMS 条)。
    """

    MENU_OBJECT_NAME = "EditorComboMenu"

    #: 弹出弹层最多直接可见的条目数, 超出后出现滚动条
    MAX_VISIBLE_ITEMS = 10

    def wheelEvent(self, event):
        """将滚轮交给外层滚动容器，避免悬停时误修改当前值。"""
        event.ignore()

    def _menu_width(self):
        """返回弹出弹层的宽度 — 默认与下拉框本身同宽。"""
        return self.width()

    def _item_enabled(self, index):
        """读取模型项的启用状态，兼容自定义 model 的下拉框。"""
        model_index = self.model().index(
            index, self.modelColumn(), self.rootModelIndex())
        return bool(model_index.flags() & Qt.ItemIsEnabled)

    def showPopup(self):
        if self.count() == 0:
            return
        if self.count() > self.MAX_VISIBLE_ITEMS:
            self._show_scrollable_popup()
            return
        self._show_menu_popup()

    def _show_scrollable_popup(self):
        """条目较多时弹出可滚动列表 (真实滚动条)。"""
        popup = EditorComboListPopup(self, self.MAX_VISIBLE_ITEMS)
        items = [
            (self.itemIcon(i), self.itemText(i), i, self._item_enabled(i))
            for i in range(self.count())
        ]
        popup.set_items(items, current=self.currentIndex())
        popup.selected.connect(self.setCurrentIndex)
        # 持有引用防止 Python 侧被回收 (关闭后由 WA_DeleteOnClose 释放)
        self._scroll_popup = popup
        popup.popup_below(self, self._menu_width())

    def _show_menu_popup(self):
        """条目较少时弹出 QMenu (带勾选标记, 同最初形态)。"""
        menu = RoundedComboMenu(self)
        menu.setObjectName(self.MENU_OBJECT_NAME)
        menu.setToolTipsVisible(False)

        for index in range(self.count()):
            action = QAction(self.itemIcon(index), self.itemText(index), menu)
            action.setData(index)
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.setEnabled(self._item_enabled(index))
            menu.addAction(action)

        # 默认从控件正下方弹出；靠近屏幕底部时才翻到控件上方，避免
        # Qt 自动选择侧向弹出造成“没有向下弹出”的视觉问题。
        below = self.mapToGlobal(QPoint(0, self.height()))
        screen = QApplication.screenAt(below) or QApplication.primaryScreen()
        width = self._menu_width()
        if screen is not None:
            width = min(width, max(1, screen.availableGeometry().width()))
        menu.setFixedWidth(width)

        anchor = below
        if screen is not None:
            available = screen.availableGeometry()
            menu_height = menu.sizeHint().height()
            x = max(available.left(), min(
                below.x(), available.right() - width + 1))
            y = below.y()
            if y + menu_height > available.bottom() + 1:
                y = self.mapToGlobal(QPoint(0, 0)).y() - menu_height
            y = max(available.top(), y)
            anchor = QPoint(x, y)

        selected = menu.exec(anchor)
        if selected is not None:
            index = selected.data()
            if index is not None:
                self.setCurrentIndex(int(index))


# 旧名称保留给外部脚本和未迁移的第三方调用方；实际类型就是统一组件。
NoWheelComboBox = EditorComboBox
