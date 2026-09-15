"""
EquipTypeLabelsPanel — 装备使用权限位值→中文标签 配置面板
编辑 equip_type_labels.json 中的 6 个页面，每页为 [[位值, 名称], ...]。
"""
from functools import partial
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QPushButton, QToolButton, QLabel, QAbstractItemView,
)
from PySide6.QtCore import Qt

from editor_utils.ui_helpers import EditorComboBox
from editor_utils.adaptive_table import AdaptiveTableWidget
from .base_panel import ConfigPanelBase

# 页面定义: (JSON键, 显示名)
PAGES = [
    ("0", "药品"), ("1", "道具"), ("2", "武器"),
    ("3", "防具"), ("4", "饰品"), ("5", "特殊"),
]

# 允许的位值: 0(通用) + 2^0 ~ 2^15
ALLOWED_BIT_VALUES = [0] + [1 << i for i in range(16)]


class EquipTypeLabelsPanel(ConfigPanelBase):
    config_name = "equip_type_labels"
    tab_label = "装备类型标签"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_page = "2"  # 默认武器页
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 页面选择 ──
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("页面:"))
        self._page_combo = EditorComboBox()
        for key, name in PAGES:
            self._page_combo.addItem(name, key)
        self._page_combo.setMinimumWidth(140)
        self._page_combo.setMaximumWidth(180)
        self._page_combo.currentIndexChanged.connect(self._on_page_changed)
        page_row.addWidget(self._page_combo)
        page_row.addStretch()
        layout.addLayout(page_row)

        # ── 表格 ──
        self._table = AdaptiveTableWidget(
            0, 3,
            stretch_columns={1},
            minimum_widths=[160, 120, 92],
            row_height=44,
        )
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["位值", "名称", "操作"])
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(2, 92)
        self._table.setProperty("noRowHover", True)
        # 本表所有可编辑内容都是单元格内控件，不需要整行选中高亮。
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self._table)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_add = QPushButton("添加条目")
        btn_add.clicked.connect(self._on_add)
        btn_row.addWidget(btn_add)

        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self.reset)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_page_changed(self):
        key = self._page_combo.currentData()
        self._current_page = key
        self._refresh_table()

    def _refresh_table(self):
        """从 self._data 填充当前页面到表格。"""
        entries = self._data.get(self._current_page, [])
        self._table.setRowCount(len(entries))
        for i, (bit_val, name) in enumerate(entries):
            # 位值列：与 wardata_editor 陷阱类型一致，使用常驻下拉框。
            bit_combo = EditorComboBox()
            for v in ALLOWED_BIT_VALUES:
                bit_combo.addItem(str(v), v)
            idx = bit_combo.findData(bit_val)
            if idx >= 0:
                bit_combo.setCurrentIndex(idx)
            bit_combo.currentIndexChanged.connect(
                lambda _idx, row=i: self._on_bit_value_changed(row))
            self._table.setCellWidget(i, 0, bit_combo)

            # 名称列
            name_item = QTableWidgetItem(str(name))
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(i, 1, name_item)

            # 操作列 (删除按钮)
            del_btn = QToolButton()
            del_btn.setText("删除")
            del_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            del_btn.setAutoRaise(True)
            del_btn.clicked.connect(lambda checked, row=i: self._on_delete(row))
            self._table.setCellWidget(i, 2, del_btn)

        self._table.blockSignals(False)

    def _on_bit_value_changed(self, row):
        self._collect_table_to_data()
        self._mark_dirty()

    def _on_add(self):
        """添加新条目: 位值选择下一个未使用的 2^n。"""
        entries = self._data.get(self._current_page, [])
        used_values = {e[0] for e in entries}
        next_val = 0
        for v in ALLOWED_BIT_VALUES:
            if v not in used_values and v != 0:
                next_val = v
                break
        entries.append([next_val, ""])
        self._data[self._current_page] = entries
        self._refresh_table()
        self._mark_dirty()

    def _on_delete(self, row):
        entries = self._data.get(self._current_page, [])
        if 0 <= row < len(entries):
            del entries[row]
            self._data[self._current_page] = entries
            self._refresh_table()
            self._mark_dirty()

    def _on_item_changed(self, _item=None):
        """表格内容变化时收集数据并标记 dirty。"""
        self._collect_table_to_data()
        self._mark_dirty()

    def _collect_table_to_data(self):
        """从表格收集数据到 self._data。"""
        entries = []
        for r in range(self._table.rowCount()):
            bit_combo = self._table.cellWidget(r, 0)
            name_item = self._table.item(r, 1)
            bit_val = bit_combo.currentData() if bit_combo else 0
            if bit_val is None:
                bit_val = 0
            name = name_item.text() if name_item else ""
            entries.append([int(bit_val), name])
        self._data[self._current_page] = entries

    # ── ConfigPanelBase 实现 ──

    def _populate_ui(self, data: dict):
        self._data = data
        # 默认选中武器页 (index=2)
        self._page_combo.blockSignals(True)
        self._page_combo.setCurrentIndex(2)
        self._page_combo.blockSignals(False)
        self._current_page = "2"
        self._refresh_table()
        # 连接 itemChanged 信号（在 _populate_ui 之后，避免初始填充时触发）
        self._table.itemChanged.connect(partial(self._on_item_changed))

    def _collect_ui(self) -> dict:
        """收集所有页面的数据。由于编辑时可能切换了页面，
        需要确保当前表格的数据已写回 self._data。"""
        self._collect_table_to_data()
        # 返回所有页面的数据
        result = {}
        for key, _ in PAGES:
            if key in self._data:
                result[key] = self._data[key]
        return result
