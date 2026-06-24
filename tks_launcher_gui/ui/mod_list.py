"""MOD 列表面板 — 以表格显示 mods/ 目录中的 .tksmod 文件，支持启用/禁用"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QTextEdit,
    QHeaderView, QSplitter,
)
from PySide6.QtCore import Qt

from editor_utils.dock_components import create_dock
from core.mod_loader import scan_mods, ModInfo

_COLUMNS = ["启用", "名称", "ID", "版本", "作者", "描述"]
_COL_ENABLE = 0
_COL_NAME = 1
_COL_ID = 2
_COL_VERSION = 3
_COL_AUTHOR = 4
_COL_DESC = 5


class ModListWidget(QWidget):
    """MOD 列表面板，嵌入主窗口左侧"""

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

        # 表格 + 详情 用垂直分割, 详情高度可拖动调整
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(4)
        split.setChildrenCollapsible(False)

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
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_ID, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_VERSION, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_AUTHOR, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        self._table.setColumnWidth(_COL_NAME, 140)
        self._table.setColumnWidth(_COL_ID, 100)
        self._table.setColumnWidth(_COL_AUTHOR, 100)
        split.addWidget(self._table)

        # 详情
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMinimumHeight(40)
        self._detail.setPlaceholderText("选中 MOD 查看详情")
        split.addWidget(self._detail)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1000, 72])
        body.addWidget(split)

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

        outer.addWidget(create_dock("MOD 列表", content, header_layout=header_row))

        # 初始加载
        self.refresh_mods()


    def refresh_mods(self):
        """重新扫描 mods 目录"""
        self._table.setRowCount(0)
        self._mods = scan_mods(self._mods_dir)

        self._table.setRowCount(len(self._mods))
        for row, mod in enumerate(self._mods):
            enable_item = QTableWidgetItem()
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            enable_item.setCheckState(Qt.Checked if mod.enabled else Qt.Unchecked)
            self._table.setItem(row, _COL_ENABLE, enable_item)

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

        self._detail.setPlainText(
            f"目录: {self._mods_dir}\n共 {len(self._mods)} 个 MOD")

    def _set_text(self, row: int, col: int, text: str):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, col, item)

    def _on_current_changed(self, current, previous):
        if current is None:
            self._detail.setPlainText("")
            return
        row = current.row()
        if row < 0 or row >= len(self._mods):
            self._detail.setPlainText("")
            return
        mod = self._mods[row]
        lines = [
            f"名称: {mod.name}",
            f"ID: {mod.mod_id}",
            f"版本: {mod.version}",
            f"作者: {mod.author}",
            f"类型: {mod.mod_type} / {mod.mode}",
            f"加载顺序: {mod.load_order}",
            f"描述: {mod.description}",
        ]
        if mod.dependencies:
            lines.append(f"依赖: {', '.join(mod.dependencies)}")
        if mod.conflicts:
            lines.append(f"冲突: {', '.join(mod.conflicts)}")
        if mod.warpc_expand:
            lines.append(f"WarPC 扩展到: {mod.warpc_expand} 角色")
        if mod.id_ranges:
            ranges = [f"  {k}: {v.get('start',0)}-{v.get('end',0)}"
                      for k, v in mod.id_ranges.items()]
            lines.append("ID 范围:\n" + "\n".join(ranges))
        self._detail.setPlainText("\n".join(lines))

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
