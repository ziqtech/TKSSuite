"""
EquipTypeLabelsPanel — 装备使用权限位值→中文标签 配置面板
编辑 equip_type_labels.json 中的 6 个页面，每页为 [[位值, 名称], ...]。
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QComboBox, QTableWidget, QTableWidgetItem,
    QPushButton, QToolButton, QLabel, QWidget, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QMessageBox
)
from PySide6.QtCore import Qt

from .base_panel import ConfigPanelBase

# 页面定义: (JSON键, 显示名)
PAGES = [
    ("0", "药品"), ("1", "道具"), ("2", "武器"),
    ("3", "防具"), ("4", "饰品"), ("5", "特殊"),
]

# 允许的位值: 0(通用) + 2^0 ~ 2^15
ALLOWED_BIT_VALUES = [0] + [1 << i for i in range(16)]


class BitValueComboDelegate(QStyledItemDelegate):
    """位值列使用 QComboBox 下拉选择的委托"""

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for v in ALLOWED_BIT_VALUES:
            combo.addItem(str(v), v)
        return combo

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.EditRole)
        combo = editor
        idx = combo.findData(val)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        combo = editor
        val = combo.currentData()
        model.setData(index, val, Qt.ItemDataRole.EditRole)
        model.setData(index, str(val), Qt.ItemDataRole.DisplayRole)


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
        self._page_combo = QComboBox()
        for key, name in PAGES:
            self._page_combo.addItem(name, key)
        self._page_combo.currentIndexChanged.connect(self._on_page_changed)
        page_row.addWidget(self._page_combo, 1)
        page_row.addStretch()
        layout.addLayout(page_row)

        # ── 表格 ──
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["位值", "名称", "操作"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 70)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setItemDelegateForColumn(0, BitValueComboDelegate(self._table))
        layout.addWidget(self._table)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕ 添加条目")
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
            # 位值列
            bit_item = QTableWidgetItem()
            bit_item.setData(Qt.ItemDataRole.EditRole, bit_val)
            bit_item.setData(Qt.ItemDataRole.DisplayRole, str(bit_val))
            bit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(i, 0, bit_item)

            # 名称列
            name_item = QTableWidgetItem(str(name))
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(i, 1, name_item)

            # 操作列 (删除按钮)
            del_btn = QToolButton()
            del_btn.setText("🗑 删除")
            del_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            del_btn.setAutoRaise(True)
            del_btn.clicked.connect(lambda checked, row=i: self._on_delete(row))
            self._table.setCellWidget(i, 2, del_btn)

        self._table.blockSignals(False)

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

    def _on_item_changed(self):
        """表格内容变化时收集数据并标记 dirty。"""
        self._collect_table_to_data()
        self._mark_dirty()

    def _collect_table_to_data(self):
        """从表格收集数据到 self._data。"""
        entries = []
        for r in range(self._table.rowCount()):
            bit_item = self._table.item(r, 0)
            name_item = self._table.item(r, 1)
            bit_val = bit_item.data(Qt.ItemDataRole.EditRole) if bit_item else 0
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
        self._table.itemChanged.connect(lambda: self._on_item_changed())

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
