"""模组列表面板 — 以表格显示 mods/ 目录中的 .tksmod 文件，支持启用/禁用"""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView,
)
from PySide6.QtCore import Qt, Signal

from editor_utils.dock_components import create_dock
from core.mod_loader import scan_mods, ModInfo

_COLUMNS = ["启用", "文件名", "模组名称", "ID", "版本", "作者", "描述"]
_COL_ENABLE = 0
_COL_FILENAME = 1
_COL_NAME = 2
_COL_ID = 3
_COL_VERSION = 4
_COL_AUTHOR = 5
_COL_DESC = 6


class ModListWidget(QWidget):
    """模组列表面板，嵌入主窗口。选中行时发出 mod_selected 信号。"""

    # 选中模组时发出（None 表示无选中），供独立的模组信息预览面板订阅
    mod_selected = Signal(object)

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self._mods_dir = mods_dir
        self._mods: list[ModInfo] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Dock 面板内容 (DockHeader + DockBody 包裹)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 表格
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.currentItemChanged.connect(self._on_current_changed)

        h = self._table.horizontalHeader()
        h.setSectionResizeMode(_COL_ENABLE, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_FILENAME, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_ID, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_VERSION, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_AUTHOR, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        self._table.setColumnWidth(_COL_FILENAME, 160)
        self._table.setColumnWidth(_COL_NAME, 140)
        self._table.setColumnWidth(_COL_ID, 150)
        self._table.setColumnWidth(_COL_AUTHOR, 100)
        body.addWidget(self._table)

        # DockHeader 右侧操作按钮
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        header_row.addStretch()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("dockToolButton")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_mods)
        header_row.addWidget(self.btn_refresh)

        outer.addWidget(create_dock("模组列表", content, header_layout=header_row))

        # 初始加载
        self.refresh_mods()

    def refresh_mods(self):
        """重新扫描 mods 目录"""
        self._table.setRowCount(0)
        self._mods = scan_mods(self._mods_dir)
        # 默认按 MOD ID 排序（不区分大小写）
        self._mods.sort(key=lambda m: m.mod_id.lower())

        self._table.setRowCount(len(self._mods))
        for row, mod in enumerate(self._mods):
            enable_item = QTableWidgetItem()
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            enable_item.setCheckState(Qt.Checked if mod.enabled else Qt.Unchecked)
            self._table.setItem(row, _COL_ENABLE, enable_item)

            self._set_text(row, _COL_FILENAME, os.path.basename(mod.path))
            self._set_text(row, _COL_NAME, mod.name)
            self._set_text(row, _COL_ID, mod.mod_id)
            self._set_text(row, _COL_VERSION, mod.version)
            self._set_text(row, _COL_AUTHOR, mod.author)

            desc_item = QTableWidgetItem(mod.description)
            desc_item.setToolTip(mod.description)
            desc_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self._table.setItem(row, _COL_DESC, desc_item)

            # 整行 tooltip
            tip = f"ID: {mod.mod_id}\n作者: {mod.author}\n{mod.description}"
            for col in range(len(_COLUMNS)):
                it = self._table.item(row, col)
                if it is not None:
                    it.setToolTip(tip)

    def _set_text(self, row: int, col: int, text: str):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, col, item)

    def _on_current_changed(self, current, previous):
        if current is None:
            self.mod_selected.emit(None)
            return
        row = current.row()
        if row < 0 or row >= len(self._mods):
            self.mod_selected.emit(None)
            return
        self.mod_selected.emit(self._mods[row])

    def get_enabled_mods(self) -> list[ModInfo]:
        """获取所有勾选启用的 MOD 列表"""
        enabled = []
        for i in range(self._table.rowCount()):
            if i >= len(self._mods):
                break
            item = self._table.item(i, _COL_ENABLE)
            self._mods[i].enabled = bool(item and item.checkState() == Qt.Checked)
            if self._mods[i].enabled:
                enabled.append(self._mods[i])
        return enabled

    def set_mods_dir(self, mods_dir: str):
        """更新 MOD 目录并刷新"""
        self._mods_dir = mods_dir
        self.refresh_mods()
