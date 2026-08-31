"""自适应表格控件。

QTableWidget 的两个常见坑在这里统一处理：
1. QSS 的 item min-height 不会改变默认行高；
2. 固定列宽 + Stretch 只能让个别列吃剩余空间，窗口放大后整体观感不稳定。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget


class AdaptiveTableWidget(QTableWidget):
    """按“内容基准宽 + 剩余宽度分配”自适应的 QTableWidget。"""

    def __init__(self, rows=0, columns=0, parent=None,
                 stretch_columns=None, minimum_widths=None,
                 row_height=44, content_padding=14):
        super().__init__(rows, columns, parent)
        self._content_padding = content_padding
        self._minimum_widths = {}
        self._user_widths = {}
        self._configured_stretch_columns = (
            set(stretch_columns) if stretch_columns is not None else None
        )
        self._inferred_stretch_columns = None
        self._applying_widths = False
        self._fit_scheduled = False

        if minimum_widths:
            for column, width in enumerate(minimum_widths):
                if width is not None:
                    self._minimum_widths[column] = max(1, int(width))

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_section_resized)
        self.verticalHeader().setDefaultSectionSize(max(30, int(row_height)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.itemChanged.connect(lambda _item: self._schedule_fit())

    def set_adaptive_row_height(self, height):
        self.verticalHeader().setDefaultSectionSize(max(30, int(height)))

    def set_adaptive_columns(self, stretch_columns=None, minimum_widths=None):
        if stretch_columns is not None:
            self._configured_stretch_columns = set(stretch_columns)
        if minimum_widths:
            for column, width in enumerate(minimum_widths):
                if width is not None:
                    self._minimum_widths[column] = max(1, int(width))
        self._schedule_fit()

    def setColumnWidth(self, column, width):
        """外部 setColumnWidth 视为该列的内容基准宽，而不是一次性宽度。"""
        if not self._applying_widths:
            self._minimum_widths[column] = max(1, int(width))
        super().setColumnWidth(column, width)
        self._schedule_fit()

    def setHorizontalHeaderLabels(self, labels):
        super().setHorizontalHeaderLabels(labels)
        self._schedule_fit()

    def setCellWidget(self, row, column, widget):
        super().setCellWidget(row, column, widget)
        self._schedule_fit()

    def setColumnHidden(self, column, hide):
        super().setColumnHidden(column, hide)
        self._schedule_fit()

    def insertColumn(self, column):
        super().insertColumn(column)
        self._shift_width_maps(column, 1)
        self._schedule_fit()

    def removeColumn(self, column):
        super().removeColumn(column)
        self._shift_width_maps(column + 1, -1)
        self._schedule_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns_to_viewport()

    def showEvent(self, event):
        super().showEvent(event)
        self._capture_header_stretch_modes()
        self.fit_columns_to_viewport()

    def fit_columns_to_viewport(self):
        if self.columnCount() == 0 or not self.isVisible():
            return

        self._applying_widths = True
        try:
            visible_columns = [
                column for column in range(self.columnCount())
                if not self.isColumnHidden(column)
            ]
            if not visible_columns:
                return

            base_widths = {
                column: self._column_base_width(column)
                for column in visible_columns
            }
            stretch_columns = self._effective_stretch_columns(visible_columns)
            available = self.viewport().width()

            widths = dict(base_widths)
            if stretch_columns and available > sum(base_widths.values()):
                extra = available - sum(base_widths.values())
                stretch_total = sum(base_widths[column] for column in stretch_columns)
                if stretch_total <= 0:
                    share = extra / len(stretch_columns)
                    for column in stretch_columns:
                        widths[column] += share
                else:
                    for column in stretch_columns:
                        widths[column] += extra * base_widths[column] / stretch_total

            for column, width in widths.items():
                super().setColumnWidth(column, max(1, round(width)))
        finally:
            self._applying_widths = False

    def _column_base_width(self, column):
        header_hint = self.horizontalHeader().sectionSizeHint(column)
        content_hint = self.sizeHintForColumn(column)
        widget_hint = self._cell_widget_width_hint(column)
        configured = self._minimum_widths.get(column, 0)
        user_width = self._user_widths.get(column)

        base = max(header_hint, content_hint + self._content_padding,
                   widget_hint, configured, 36)
        if user_width is not None:
            base = max(user_width, configured)
        return max(1, base)

    def _cell_widget_width_hint(self, column):
        best = 0
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, column)
            if widget is not None:
                best = max(best, widget.sizeHint().width() + 12)
        return best

    def _effective_stretch_columns(self, visible_columns):
        if self._configured_stretch_columns is not None:
            stretch = self._configured_stretch_columns.intersection(visible_columns)
            return stretch or set(visible_columns)
        if self._inferred_stretch_columns is None:
            return set(visible_columns)
        return self._inferred_stretch_columns.intersection(visible_columns)

    def _capture_header_stretch_modes(self):
        if self._configured_stretch_columns is not None:
            return
        stretch = set()
        for column in range(self.columnCount()):
            if self.isColumnHidden(column):
                continue
            mode = self.horizontalHeader().sectionResizeMode(column)
            if mode == QHeaderView.ResizeMode.Stretch:
                stretch.add(column)
        if self.horizontalHeader().stretchLastSection():
            stretch.add(self.columnCount() - 1)
        self._inferred_stretch_columns = stretch or set(
            column for column in range(self.columnCount())
            if not self.isColumnHidden(column)
        )

        # 自适应宽度由本类统一计算；Interactive 保留用户手动拖列的能力。
        self._applying_widths = True
        try:
            self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.horizontalHeader().setStretchLastSection(False)
        finally:
            self._applying_widths = False

    def _on_section_resized(self, logical_index, _old_size, new_size):
        if (self._applying_widths or not self.isVisible()
                or logical_index < 0 or logical_index >= self.columnCount()):
            return
        if new_size > 0:
            self._user_widths[logical_index] = new_size

    def _schedule_fit(self):
        if self._fit_scheduled:
            return
        self._fit_scheduled = True
        QTimer.singleShot(0, self._deferred_fit)

    def _deferred_fit(self):
        self._fit_scheduled = False
        self.fit_columns_to_viewport()

    def _shift_width_maps(self, start, delta):
        for mapping in (self._minimum_widths, self._user_widths):
            new_mapping = {}
            for column, value in mapping.items():
                if column >= start:
                    new_mapping[column + delta] = value
                else:
                    new_mapping[column] = value
            mapping.clear()
            mapping.update(new_mapping)
