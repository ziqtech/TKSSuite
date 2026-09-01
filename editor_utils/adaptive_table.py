"""自适应表格控件。

QTableWidget 的两个常见坑在这里统一处理：
1. QSS 的 item min-height 不会改变默认行高；
2. 固定列宽 + Stretch 只能让个别列吃剩余空间，窗口放大后整体观感不稳定。

列宽策略（对齐桌面专业软件的通行做法：Excel / DataGrip / Qt Creator）：
- 内容基准：每列取表头提示、内容提示、单元格控件提示、配置下限中的最大值；
- 受控拉伸：视口剩余宽度按比例分配给拉伸列，但每列有拉伸上限（内容基准
  的倍数，或通过 maximum_widths 显式指定像素值），触顶即停止增长；
- 尾部留白：所有拉伸列触顶后，多余空间保留在最后一列右侧，不再强行摊进
  列里——高分辨率宽屏下数值列不会被撑得稀疏难看；
- 防滚动条：内容基准超出视口时按比例回缩各列（不低于配置下限和用户拖过
  的宽度），只有下限总和都放不下时才出现横向滚动条；
- 用户优先：手动拖过的列宽始终优先于自动计算，拉伸上限不会收缩用户拖宽。

fill_viewport=True 时切换为“完全撑满”模式：拉伸列不再封顶，视口剩余宽度
全部由拉伸列吃掉，表格右侧不留学生白（Excel / 文件管理器风格）。适用于
嵌入窗口固定区域、希望始终铺满的表格（如 tks_launcher_gui）。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget

# 拉伸列的默认封顶策略：列宽最多增长到 max(基准×factor, 基准+margin)。
# 数值列基准小 → 封顶紧；长文本列基准大 → 封顶随内容放大，比例观感稳定。
DEFAULT_STRETCH_CAP_FACTOR = 1.5
DEFAULT_STRETCH_CAP_MARGIN = 64


def _normalize_widths(value):
    """宽度配置归一化: list/tuple 按下标成列, dict 键即列号; None 项跳过。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {int(c): max(1, int(w)) for c, w in value.items() if w is not None}
    return {c: max(1, int(w)) for c, w in enumerate(value) if w is not None}


class AdaptiveTableWidget(QTableWidget):
    """按“内容基准宽 + 受控拉伸 + 尾部留白”自适应的 QTableWidget。"""

    def __init__(self, rows=0, columns=0, parent=None,
                 stretch_columns=None, minimum_widths=None, maximum_widths=None,
                 row_height=44, content_padding=14,
                 stretch_cap_factor=DEFAULT_STRETCH_CAP_FACTOR,
                 stretch_cap_margin=DEFAULT_STRETCH_CAP_MARGIN,
                 fill_viewport=False):
        super().__init__(rows, columns, parent)
        self._content_padding = content_padding
        self._minimum_widths = {}
        self._maximum_widths = {}
        self._user_widths = {}
        self._fill_viewport = bool(fill_viewport)
        self._configured_stretch_columns = (
            set(stretch_columns) if stretch_columns is not None else None
        )
        self._inferred_stretch_columns = None
        self._applying_widths = False
        self._fit_scheduled = False
        self._stretch_cap_factor = max(1.0, float(stretch_cap_factor))
        self._stretch_cap_margin = max(0, int(stretch_cap_margin))

        if minimum_widths:
            self._minimum_widths.update(_normalize_widths(minimum_widths))
        if maximum_widths:
            self._maximum_widths.update(_normalize_widths(maximum_widths))

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_section_resized)
        self.verticalHeader().setDefaultSectionSize(max(30, int(row_height)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.itemChanged.connect(lambda _item: self._schedule_fit())

    def set_adaptive_row_height(self, height):
        self.verticalHeader().setDefaultSectionSize(max(30, int(height)))

    def set_adaptive_columns(self, stretch_columns=None, minimum_widths=None,
                             maximum_widths=None):
        if stretch_columns is not None:
            self._configured_stretch_columns = set(stretch_columns)
        if minimum_widths is not None:
            self._minimum_widths.update(_normalize_widths(minimum_widths))
        if maximum_widths is not None:
            self._maximum_widths.update(_normalize_widths(maximum_widths))
        self._schedule_fit()

    def reset_column_layout(self, stretch_columns=None, minimum_widths=None,
                            maximum_widths=None):
        """整体重置列布局 (动态换列场景): 清除手动拖宽后应用新配置。"""
        self._user_widths.clear()
        self._configured_stretch_columns = (
            set(stretch_columns) if stretch_columns is not None else None
        )
        self._minimum_widths = _normalize_widths(minimum_widths)
        self._maximum_widths = _normalize_widths(maximum_widths)
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
            extra = available - sum(widths.values())
            if extra > 0 and stretch_columns:
                caps = {
                    column: self._column_stretch_cap(column, widths[column])
                    for column in stretch_columns
                }
                widths = self._distribute_extra(widths, stretch_columns, caps, extra)
            elif extra < 0:
                widths = self._shrink_to_fit(widths, visible_columns, -extra)

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

    def _column_stretch_cap(self, column, base):
        """拉伸列的宽度封顶值；显式 maximum_widths 优先于默认倍数策略。"""
        if self._fill_viewport:
            # 完全撑满模式: 拉伸列不封顶, 剩余宽度全部摊给拉伸列
            return float("inf")
        explicit = self._maximum_widths.get(column)
        if explicit is not None:
            return max(base, explicit)
        return max(base,
                   base * self._stretch_cap_factor,
                   base + self._stretch_cap_margin)

    def _column_floor_width(self, column):
        """回缩阶段的下限：配置下限与用户拖过的宽度取最大，保证不截断用户意图。"""
        return max(self._minimum_widths.get(column, 0),
                   self._user_widths.get(column, 0), 36)

    def _shrink_to_fit(self, widths, visible_columns, deficit):
        """反向水位填充：视口装不下时按“可压缩余量”比例回缩各列到下限，
        下限总和仍超出时才保留溢出（此时横向滚动条不可避免）。"""
        floors = {c: self._column_floor_width(c) for c in visible_columns}
        eligible = [c for c in visible_columns if widths[c] > floors[c]]
        while deficit >= 1 and eligible:
            total_slack = sum(widths[c] - floors[c] for c in eligible)
            if total_slack <= deficit:
                for c in eligible:
                    widths[c] = floors[c]
                break
            clamped = False
            remaining = []
            for c in eligible:
                slack = widths[c] - floors[c]
                target = widths[c] - deficit * slack / total_slack
                if target <= floors[c]:
                    deficit -= slack
                    widths[c] = floors[c]
                    clamped = True
                else:
                    remaining.append(c)
            if not clamped:
                for c in eligible:
                    widths[c] -= deficit * (widths[c] - floors[c]) / total_slack
                break
            eligible = remaining
        return widths

    @staticmethod
    def _distribute_extra(widths, stretch_columns, caps, extra):
        """水位填充：按基准比例向拉伸列分配剩余宽度，单列触顶即固定，
        余量继续分给未触顶的列；全部触顶后剩余空间留在表格尾部。"""
        eligible = [c for c in stretch_columns if caps[c] > widths[c]]
        while extra >= 1 and eligible:
            total = sum(widths[c] for c in eligible)
            if total <= 0:
                shares = {c: extra / len(eligible) for c in eligible}
            else:
                shares = {c: extra * widths[c] / total for c in eligible}
            clamped = False
            remaining = []
            for column in eligible:
                target = widths[column] + shares[column]
                if target >= caps[column]:
                    extra -= caps[column] - widths[column]
                    widths[column] = caps[column]
                    clamped = True
                else:
                    remaining.append(column)
            if not clamped:
                for column in eligible:
                    widths[column] += shares[column]
                break
            eligible = remaining
        return widths

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
        for mapping in (self._minimum_widths, self._maximum_widths, self._user_widths):
            new_mapping = {}
            for column, value in mapping.items():
                if column >= start:
                    new_mapping[column + delta] = value
                else:
                    new_mapping[column] = value
            mapping.clear()
            mapping.update(new_mapping)
