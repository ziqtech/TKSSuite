"""
通用选择器对话框 — 供所有编辑器统一使用
包含: TktPickerDialog (TKT 文本选择器)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QHeaderView
)
from PySide6.QtCore import Qt


class TktPickerDialog(QDialog):
    """TKT 文本选择对话框 — 搜索过滤表格，支持双击选择"""

    def __init__(self, parent, tkt_dict, cur_val=0):
        super().__init__(parent)
        self.setWindowTitle("选择 TKT 文本")
        self.resize(500, 400)
        self.selected_id = cur_val

        layout = QVBoxLayout(self)

        # 搜索框
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索...")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["ID", "文本"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._accept)
        btn_layout.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        # 数据
        self._data = sorted(tkt_dict.items(), key=lambda x: x[0])
        self._populate()

        # 选中当前值
        if cur_val > 0:
            for row in range(self.table.rowCount()):
                if int(self.table.item(row, 0).text()) == cur_val:
                    self.table.selectRow(row)
                    break

    def _populate(self, filter_text=""):
        self.table.setRowCount(0)
        for tid, text in self._data:
            if filter_text and filter_text.lower() not in text.lower() and filter_text != str(tid):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(tid)))
            self.table.setItem(row, 1, QTableWidgetItem(text[:80]))

    def _filter(self, text):
        self._populate(text)

    def _accept(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_id = int(self.table.item(sel[0].row(), 0).text())
        self.accept()
