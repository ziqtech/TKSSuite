"""通用编辑器下拉框。

所有 PySide 编辑器和编辑器弹窗统一使用 :class:`EditorComboBox`，获得：

* 在滚动面板中悬停滚轮不会误切换选项；
* 使用 Qt 原生 ``QMenu`` 弹层，避免 ``QComboBox`` 默认视图在不同平台
  下出现额外矩形边框、错位或顶层窗口生命周期问题；
* 菜单始终从控件下沿弹出，并自动限制在当前屏幕可用区域内。

菜单的具体颜色由 editor_themes/dark.qss 和 light.qss 中的
``QMenu#EditorComboMenu`` 统一控制。
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QComboBox, QMenu


class EditorComboBox(QComboBox):
    """编辑器通用下拉框。

    组件保留 ``QComboBox`` 的数据模型、信号和编辑接口，仅替换弹出层；
    因此可直接用于普通表单、滚动页、QDialog 以及 item delegate。
    """

    MENU_OBJECT_NAME = "EditorComboMenu"

    def wheelEvent(self, event):
        """将滚轮交给外层滚动容器，避免悬停时误修改当前值。"""
        event.ignore()

    def _menu_width(self):
        """返回适合当前选项文本的菜单宽度。"""
        text_width = max(
            (self.fontMetrics().horizontalAdvance(self.itemText(i))
             for i in range(self.count())),
            default=0,
        )
        # 预留菜单左右 padding、选中标记、图标槽和少量呼吸空间。
        return max(self.width(), text_width + 42)

    def _item_enabled(self, index):
        """读取模型项的启用状态，兼容自定义 model 的下拉框。"""
        model_index = self.model().index(
            index, self.modelColumn(), self.rootModelIndex())
        return bool(model_index.flags() & Qt.ItemIsEnabled)

    def showPopup(self):
        menu = QMenu(self)
        menu.setObjectName(self.MENU_OBJECT_NAME)
        menu.setToolTipsVisible(False)

        for index in range(self.count()):
            action = QAction(self.itemIcon(index), self.itemText(index), menu)
            action.setData(index)
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.setEnabled(self._item_enabled(index))
            menu.addAction(action)

        width = self._menu_width()
        menu.setFixedWidth(width)

        # 默认从控件正下方弹出；靠近屏幕底部时才翻到控件上方，避免
        # Qt 自动选择侧向弹出造成“没有向下弹出”的视觉问题。
        below = self.mapToGlobal(QPoint(0, self.height()))
        screen = QApplication.screenAt(below) or QApplication.primaryScreen()
        anchor = below
        if screen is not None:
            available = screen.availableGeometry()
            menu_height = menu.sizeHint().height()
            x = max(available.left(), min(
                below.x(), available.right() - width + 1))
            y = below.y()
            if y + menu_height > available.bottom() + 1:
                y = self.mapToGlobal(QPoint(0, 0)).y() - menu_height
            anchor = QPoint(x, y)

        selected = menu.exec(anchor)
        if selected is not None:
            index = selected.data()
            if index is not None:
                self.setCurrentIndex(int(index))


# 旧名称保留给外部脚本和未迁移的第三方调用方；实际类型就是统一组件。
NoWheelComboBox = EditorComboBox

