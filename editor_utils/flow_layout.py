"""FlowLayout — 流式布局: 子控件从左到右排列, 超出可用宽度自动换行。

各编辑器共享的公共布局组件 (从 item_editor 提取)。
典型用法::

    content = QWidget()
    flow = FlowLayout(content, margin=0, spacing=8)
    flow.addWidget(some_widget)

可选"右侧固定项" (set_right_pinned): 不参与流式换行, 始终贴在
控制区右缘 (有两行以上时贴第 2 行, 只有一行时贴该行右缘);
其所在行装箱时会为它预留右侧宽度。供工具条"应用/重置"类
按钮组固定右置使用 (act_editor)。
"""
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """子控件左右排列, 超出可用宽度时自动换到下一行。

    同一行的子项按行高垂直居中: 标签与高控件 (下拉框/输入框/按钮)
    共享一条水平中线, 矮控件不再顶对齐。
    """

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []
        self._pin = None

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

    def set_right_pinned(self, widget):
        """设置右侧固定项 (传 None 清除)。该项父窗口须与本布局相同。

        固定项不参与换行; 先按整宽装箱定行数, 再令其所在行
        (默认第 2 行) 装箱时预留右缘宽度, 行号钳制到末行。
        """
        self._pin = widget
        self.update()
        self.invalidate()

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
        if self._pin is not None:
            size = size.expandedTo(self._pin.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _pin_size(self):
        return self._pin.sizeHint() if self._pin is not None else QSize()

    def _pack_rows(self, width, reduced_row):
        """按可用宽度贪心装箱, 返回 [(items, row_w, row_h), ...]。

        reduced_row 行的可用宽度扣除右侧固定项占位 (负数表示不扣)。
        """
        pin_w = 0
        if self._pin is not None and reduced_row >= 0:
            pin_w = self._pin_size().width() + self.spacing()
        rows = []
        row, row_w, row_h = [], 0, 0
        for item in self._items:
            sz = item.sizeHint()
            avail = width - (pin_w if len(rows) == reduced_row else 0)
            nx = row_w + sz.width() + (self.spacing() if row else 0)
            if row and nx > avail:
                rows.append((row, row_w, row_h))
                row, row_w, row_h = [], 0, 0
                nx = sz.width()
            row.append((item, sz, row_w + (self.spacing() if row_w else 0)))
            row_w = nx
            row_h = max(row_h, sz.height())
        if row:
            rows.append((row, row_w, row_h))
        return rows

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), 0)
        pin = self._pin
        pin_hint = self._pin_size()

        # 先按整宽装箱定行数, 再令固定项所在行 (默认第 2 行) 预留右缘;
        # 固定项让该行变挤可能多折一行, 但行号仍有效, 只需钳到末行。
        rows = self._pack_rows(effective.width(), -1)
        pin_row = -1
        if pin is not None:
            pin_row = min(1, len(rows) - 1)
            rows = self._pack_rows(effective.width(), pin_row)
            pin_row = min(pin_row, len(rows) - 1)

        if not test_only:
            row_top = effective.y()
            for ri, (row_items, _rw, row_h) in enumerate(rows):
                # 行内垂直居中: QLabel/QCheckBox 等矮控件与按钮/下拉框同行时
                # 不再顶对齐 (否则文字视觉偏上)。
                line_h = max(row_h, pin_hint.height() if ri == pin_row else 0)
                for item, sz, ix in row_items:
                    iy = row_top + max(0, (line_h - sz.height()) // 2)
                    item.setGeometry(QRect(QPoint(ix, iy), sz))
                if ri == pin_row:
                    px = effective.right() + 1 - pin_hint.width()
                    py = row_top + max(0, (line_h - pin_hint.height()) // 2)
                    pin.setGeometry(QRect(QPoint(px, py), pin_hint))
                row_top += line_h + self.spacing()
        y = effective.y()
        for ri, (_row_items, _rw, row_h) in enumerate(rows):
            y += max(row_h, pin_hint.height() if ri == pin_row else 0) \
                + self.spacing()
        if rows:
            y -= self.spacing()
        return y - rect.y() + m.bottom()
