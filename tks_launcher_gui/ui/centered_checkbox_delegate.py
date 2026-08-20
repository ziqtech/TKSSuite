"""启动器列表的居中复选框委托。

Qt 默认的 QTableWidgetItem 复选框会受到单元格 padding 和样式布局影响，
在窄列中容易偏向左侧。这个委托保留表格原有的行背景/选中态，只接管
启用列指示器的绘制，并把它严格放在单元格中心。
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
)


def position_checkbox_indicator(widget, section_x: int, section_width: int,
                                section_height: int) -> None:
    """按指示器本身而不是 QCheckBox 整体宽度对齐表头复选框。"""
    option = QStyleOptionButton()
    widget.initStyleOption(option)
    indicator = widget.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator, option, widget)
    size = widget.sizeHint()
    indicator_center_x = indicator.left() + indicator.width() / 2
    widget_x = round(section_x + section_width / 2 - indicator_center_x)
    widget_y = (section_height - size.height()) // 2
    widget.setGeometry(widget_x, widget_y, size.width(), size.height())


class CenteredCheckBoxDelegate(QStyledItemDelegate):
    """只负责一个启用列的复选框绘制，点击行为仍由 Qt 标准委托处理。"""

    def paint(self, painter: QPainter, option, index) -> None:
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)

        # 先让标准委托绘制单元格背景、选中态和焦点态，但不绘制默认的
        # 左对齐复选框；指示器稍后用表格样式手动居中绘制。
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        view_option.text = ""
        view_option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        super().paint(painter, view_option, index)

        if state is None:
            return

        style = view_option.widget.style() if view_option.widget else QApplication.style()
        check_option = QStyleOptionButton()
        check_option.palette = view_option.palette
        check_option.rect = self._indicator_rect(style, option.rect, check_option,
                                                 view_option.widget)

        if view_option.state & QStyle.StateFlag.State_Enabled:
            check_option.state |= QStyle.StateFlag.State_Enabled
        # QAbstractItemModel 通常返回裸 int，而不是 Qt.CheckState 枚举。
        state_value = getattr(state, "value", state)
        if state_value == Qt.CheckState.Checked.value:
            check_option.state |= QStyle.StateFlag.State_On
        elif state_value == Qt.CheckState.PartiallyChecked.value:
            check_option.state |= QStyle.StateFlag.State_NoChange
        else:
            check_option.state |= QStyle.StateFlag.State_Off

        # PE_IndicatorItemViewItemCheck 与 QTableWidget::indicator 的主题规则
        # 保持一致，避免为深浅主题额外复制一套复选框颜色。
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
            check_option,
            painter,
            view_option.widget,
        )

    @staticmethod
    def _indicator_rect(style, cell_rect: QRect, option, widget) -> QRect:
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, widget)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, option, widget)
        width = max(16, width)
        height = max(16, height)
        return QRect(
            cell_rect.center().x() - width // 2,
            cell_rect.center().y() - height // 2,
            width,
            height,
        )

    def editorEvent(self, event, model, option, index) -> bool:
        # 保留 QStyledItemDelegate 的标准键盘/鼠标切换逻辑；它会更新
        # CheckStateRole，从而继续触发现有的 itemChanged 状态同步。
        return super().editorEvent(event, model, option, index)
