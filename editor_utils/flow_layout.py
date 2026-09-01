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
        row_top = effective.y()
        row_h = 0
        rows = []   # [(row_top, row_h, [(item, size, x), ...])]
        row = []
        for item in self._items:
            sz = item.sizeHint()
            nx = x + sz.width()
            if nx - effective.x() > effective.width() and row_h > 0:
                rows.append((row_top, row_h, row))
                x = effective.x()
                row_top += row_h + self.spacing()
                row_h = 0
                row = []
                nx = x + sz.width()
            row.append((item, sz, x))
            x = nx + self.spacing()
            row_h = max(row_h, sz.height())
        if row:
            rows.append((row_top, row_h, row))
        if not test_only:
            # 行内垂直居中: QLabel/QCheckBox 等矮控件与按钮/下拉框同行时
            # 不再顶对齐 (否则文字视觉偏上)。
            for top, height, row_items in rows:
                for item, sz, ix in row_items:
                    iy = top + (height - sz.height()) // 2
                    item.setGeometry(QRect(QPoint(ix, iy), sz))
        return row_top + row_h - rect.y() + m.bottom()
