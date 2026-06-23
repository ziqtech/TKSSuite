"""
通用选择器对话框 — 供所有编辑器统一使用
包含: TktPickerDialog (TKT 文本选择器)
      StatusPickerDialog (状态位掩码多选器)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QHeaderView,
    QScrollArea, QWidget, QCheckBox, QLabel
)
from PySide6.QtCore import Qt


# 31 种状态名称 (Maker UI 状态列表; bit 0..30) — 供状态弹窗/标签渲染共用
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]
# Mu.JVG 中状态图标起始精灵索引 (对齐 item_editor); 用于状态弹窗/预览中的图标
STATUS_ICON_BASE = 242


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


class StatusPickerDialog(QDialog):
    """状态位掩码多选对话框。

    16 个状态复选框 (base 起始), 可选每行前显示状态图标。
    确定后通过 ``selected_mask`` 属性返回带符号 int16。

    Args:
        parent: 父窗口
        title: 窗口标题
        status_names: 状态名称列表 (通常为 STATUS_NAMES)
        cur_mask: 当前掩码 (uint16)
        base: 起始状态索引 (0 或 16)
        get_pixmap_fn: 可选的图标获取回调 ``fn(icon_val, size) -> QPixmap``;
                       为 None 时不显示图标。
        is_cause: 是否为"导致状态"语义 (仅用于标题区分, 不影响渲染)。
    """
    def __init__(self, parent, title, status_names, cur_mask, base,
                 get_pixmap_fn=None, is_cause=False):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(380, 520)
        self.selected_mask = None
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); cl = QVBoxLayout(content)
        self.checkboxes = []
        for i in range(16):
            idx = base + i
            if idx >= len(status_names): break
            row = QHBoxLayout()
            if get_pixmap_fn is not None:
                pix = get_pixmap_fn(STATUS_ICON_BASE + idx - 130, (20, 20))
                if pix:
                    lbl = QLabel(); lbl.setPixmap(pix); row.addWidget(lbl)
            cb = QCheckBox(f"{idx}. {status_names[idx]}")
            cb.setChecked(bool(cur_mask & (1 << i)))
            self.checkboxes.append((i, cb)); row.addWidget(cb); row.addStretch()
            cl.addLayout(row)
        cl.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._ok); bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _ok(self):
        m = 0
        for i, cb in self.checkboxes:
            if cb.isChecked(): m |= (1 << i)
        if m >= 0x8000: m -= 0x10000
        self.selected_mask = m; self.accept()

    def get_mask(self):
        """兼容旧调用: 返回与 selected_mask 相同的带符号 int16"""
        return self.selected_mask
