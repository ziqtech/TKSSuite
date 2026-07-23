"""FlowLayout — 流式布局: 子控件从左到右排列, 超出可用宽度自动换行。

各编辑器共享的公共布局组件 (从 item_editor 提取)。
典型用法::

    content = QWidget()
    flow = FlowLayout(content, margin=0, spacing=8)
    flow.addWidget(some_widget)
"""
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """子控件左右排列, 超出可用宽度时自动换到下一行。"""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), 0)
        x = effective.x()
        y = effective.y()
        row_h = 0
        for item in self._items:
            sz = item.sizeHint()
            nx = x + sz.width()
            if nx - effective.x() > effective.width() and row_h > 0:
                x = effective.x()
                y += row_h + self.spacing()
                row_h = 0
                nx = x + sz.width()
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = nx + self.spacing()
            row_h = max(row_h, sz.height())
        return y + row_h - rect.y() + m.bottom()
