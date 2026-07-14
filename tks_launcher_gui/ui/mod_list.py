"""模组列表面板 — 以表格显示 mods/ 目录中的 .tksmod 文件，支持启用/禁用"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.mod_loader import ModInfo, scan_mods
from editor_utils.dock_components import create_dock

_COLUMNS = ["启用", "模组名称", "版本", "加载顺序", "ID", "作者", "描述"]
_COL_ENABLE = 0
_COL_NAME = 1
_COL_VERSION = 2
_COL_LOAD_ORDER = 3
_COL_ID = 4
_COL_AUTHOR = 5
_COL_DESC = 6


class ModListWidget(QWidget):
    """模组列表面板，嵌入主窗口。选中行时发出 mod_selected 信号。"""

    # 选中模组时发出（None 表示无选中），供独立的模组信息预览面板订阅
    mod_selected = Signal(object)
    # 重复 ID 检测结果：True 表示存在重复
    duplicate_ids_detected = Signal(bool)
    # 勾选状态变化时发出, 供外部持久化保存
    state_changed = Signal()

    def __init__(self, mods_dir: str = "mods",
                 initial_states: dict[str, bool] | None = None, parent=None):
        super().__init__(parent)
        self._mods_dir = mods_dir
        self._mods: list[ModInfo] = []
        self._loading = False
        self._syncing = False  # 防止表头复选框与行同步时递归
        # 持久化的启用状态快照 {mod_id: bool}; 刷新时会被当前表格状态覆盖
        self._initial_states: dict[str, bool] = initial_states or {}
        self._first_refresh = True  # 首次加载用传入快照, 后续刷新用当前表格状态

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
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_LOAD_ORDER, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_ID, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_VERSION, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_AUTHOR, QHeaderView.Interactive)
        h.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        self._table.setColumnWidth(_COL_NAME, 180)
        self._table.setColumnWidth(_COL_ID, 150)
        self._table.setColumnWidth(_COL_AUTHOR, 100)

        # 启用列表头叠加一个真实 QCheckBox（受 QCheckBox::indicator QSS 样式控制，
        # 与表格单元格复选框外观一致），用作全选/全不选
        self._header = h
        self._table.setHorizontalHeaderItem(_COL_ENABLE, QTableWidgetItem(""))
        self._header_check = QCheckBox(h)
        self._header_check.setTristate(True)
        # 透明背景，使控件融入表头 section 背景（避免默认窗口背景色）
        self._header_check.setAttribute(Qt.WA_TranslucentBackground, True)
        self._header_check.setStyleSheet("background: transparent;")
        self._header_check.stateChanged.connect(self._on_header_check_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        # 表头尺寸/位置变化时重新定位复选框
        h.geometriesChanged.connect(self._position_header_check)
        h.sectionResized.connect(self._position_header_check)

        # 表头点击三态排序 (默认 → 升序 → 降序 → 默认)
        self._sort_column: int = -1   # -1 = 默认顺序 (按 mod_id)
        self._sort_state: int = 0     # 0=默认, 1=升序, 2=降序
        h.sectionClicked.connect(self._on_header_clicked)

        body.addWidget(self._table)

        # DockHeader 右侧操作按钮
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        header_row.addStretch()
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("刷新")
        self.btn_refresh.setAutoRaise(True)
        self.btn_refresh.setObjectName("dockToolButton")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_mods)
        header_row.addWidget(self.btn_refresh)

        outer.addWidget(create_dock("模组列表", content, header_layout=header_row))

        # 初始加载
        self.refresh_mods()
        self._position_header_check()

    def refresh_mods(self):
        """重新扫描 mods 目录"""
        self._loading = True
        # 后续刷新: 先保留当前勾选状态, 用于刷新后恢复 (首次加载用构造时传入的快照)
        if not self._first_refresh:
            self._initial_states = self.get_mod_states()
        self._first_refresh = False
        self._table.setRowCount(0)
        self._mods = scan_mods(self._mods_dir)
        # 默认多级排序: 加载顺序 > 作者 > 模组名称 > 版本号 > 描述 > ID
        self._mods.sort(key=self._default_sort_key)
        # 应用用户选择的排序
        self._apply_user_sort()

        # 检测重复 ID
        dup_ids = self._detect_dup_ids()
        self.duplicate_ids_detected.emit(len(dup_ids) > 0)

        self._populate_table(dup_ids)

        self._loading = False
        self._update_header_check_state()
        self._update_sort_indicator()

    def _detect_dup_ids(self) -> set[str]:
        """检测当前模组列表中的重复 ID"""
        id_counts: dict[str, int] = {}
        for mod in self._mods:
            id_counts[mod.mod_id] = id_counts.get(mod.mod_id, 0) + 1
        return {k for k, v in id_counts.items() if v > 1}

    def _populate_table(self, dup_ids: set[str] | None = None):
        """从 self._mods 填充表格行 (已排好序)"""
        if dup_ids is None:
            dup_ids = set()
        self._table.setRowCount(len(self._mods))
        for row, mod in enumerate(self._mods):
            enable_item = QTableWidgetItem()
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # 优先用持久化状态覆盖; 持久化中无记录时用 mod.enabled
            if mod.mod_id in self._initial_states:
                is_enabled = self._initial_states[mod.mod_id]
            else:
                is_enabled = mod.enabled
            enable_item.setCheckState(Qt.Checked if is_enabled else Qt.Unchecked)
            self._table.setItem(row, _COL_ENABLE, enable_item)

            self._set_text(row, _COL_NAME, mod.name)
            self._set_text(row, _COL_VERSION, mod.version)
            self._set_text(row, _COL_LOAD_ORDER, str(mod.load_order))

            id_item = self._set_text(row, _COL_ID, mod.mod_id)
            if mod.mod_id in dup_ids:
                id_item.setForeground(QColor(220, 50, 50))

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

    # ── 表头三态排序 ──

    def _on_header_clicked(self, col: int):
        """表头点击: 三态排序切换 (默认 → 升序 → 降序 → 默认)"""
        if col == _COL_ENABLE:
            return  # 启用列有表头复选框，不参与排序
        if self._sort_column != col:
            self._sort_column = col
            self._sort_state = 1  # 升序
        else:
            self._sort_state = (self._sort_state + 1) % 3
            if self._sort_state == 0:
                self._sort_column = -1  # 回到默认
        self._resort()

    def _resort(self):
        """重新排序并刷新表格 (不重新扫描目录)"""
        self._loading = True
        self._initial_states = self.get_mod_states()
        self._mods.sort(key=self._default_sort_key)
        self._apply_user_sort()
        dup_ids = self._detect_dup_ids()
        self._table.setRowCount(0)
        self._populate_table(dup_ids)
        self._loading = False
        self._update_header_check_state()
        self._update_sort_indicator()

    def _apply_user_sort(self):
        """根据用户选择的列和方向排序 self._mods

        点击列作为主键, 其余列按默认优先级
        (加载顺序 > 作者 > 模组名称 > 版本号 > 描述 > ID) 作为次级键
        """
        if self._sort_column < 0 or self._sort_state == 0:
            return
        col = self._sort_column
        reverse = (self._sort_state == 2)
        self._mods.sort(
            key=lambda m: self._composite_sort_key(m, col), reverse=reverse)

    def _default_sort_key(self, mod: ModInfo):
        """默认多级排序键: 加载顺序 > 作者 > 模组名称 > 版本号 > 描述 > ID"""
        return (
            mod.load_order,
            (mod.author or "").lower(),
            (mod.name or "").lower(),
            (mod.version or "").lower(),
            (mod.description or "").lower(),
            (mod.mod_id or "").lower(),
        )

    def _composite_sort_key(self, mod: ModInfo, col: int):
        """组合排序键: 用户点击列为主键, 默认优先级链为次级键 (tiebreaker)"""
        return (self._get_sort_key(mod, col),) + self._default_sort_key(mod)

    def _get_sort_key(self, mod: ModInfo, col: int):
        if col == _COL_NAME:
            return (mod.name or "").lower()
        elif col == _COL_VERSION:
            return (mod.version or "").lower()
        elif col == _COL_LOAD_ORDER:
            return mod.load_order
        elif col == _COL_ID:
            return (mod.mod_id or "").lower()
        elif col == _COL_AUTHOR:
            return (mod.author or "").lower()
        elif col == _COL_DESC:
            return (mod.description or "").lower()
        return ""

    def _update_sort_indicator(self):
        """更新表头排序指示器"""
        h = self._table.horizontalHeader()
        if self._sort_column < 0 or self._sort_state == 0:
            h.setSortIndicatorShown(False)
        else:
            order = Qt.AscendingOrder if self._sort_state == 1 else Qt.DescendingOrder
            h.setSortIndicator(self._sort_column, order)
            h.setSortIndicatorShown(True)

    def _set_text(self, row: int, col: int, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, col, item)
        return item

    def _on_current_changed(self, current, previous):
        if current is None:
            self.mod_selected.emit(None)
            return
        row = current.row()
        if row < 0 or row >= len(self._mods):
            self.mod_selected.emit(None)
            return
        self.mod_selected.emit(self._mods[row])

    def _position_header_check(self):
        """将表头复选框定位到启用列 section 的中心"""
        h = self._header
        x = h.sectionViewportPosition(_COL_ENABLE)
        w = h.sectionSize(_COL_ENABLE)
        if w <= 0:
            self._header_check.setVisible(False)
            return
        sh = self._header_check.sizeHint()
        cw, ch = sh.width(), sh.height()
        self._header_check.setGeometry(
            x + (w - cw) // 2,
            (h.height() - ch) // 2,
            cw, ch,
        )
        self._header_check.setVisible(True)
        self._header_check.raise_()

    def _on_item_changed(self, item):
        """单行勾选状态变化时，同步表头复选框的三态"""
        if self._loading or item.column() != _COL_ENABLE:
            return
        self._update_header_check_state()
        self.state_changed.emit()

    def _on_header_check_changed(self, state):
        """点击表头复选框：全选/全不选。

        判定依据当前各行状态（点击前的状态）：
        全部已选 -> 全不选；否则 -> 全选。
        """
        if self._syncing:
            return
        rows = self._table.rowCount()
        all_checked = rows > 0 and all(
            (self._table.item(i, _COL_ENABLE) is not None
             and self._table.item(i, _COL_ENABLE).checkState() == Qt.Checked)
            for i in range(rows)
        )
        target = Qt.Unchecked if all_checked else Qt.Checked
        self._table.blockSignals(True)
        for i in range(rows):
            cell = self._table.item(i, _COL_ENABLE)
            if cell is not None:
                cell.setCheckState(target)
        self._table.blockSignals(False)
        self._update_header_check_state()
        self.state_changed.emit()

    def _update_header_check_state(self):
        """根据各行勾选情况刷新表头复选框状态（三态）"""
        total = self._table.rowCount()
        if total == 0:
            st = Qt.Unchecked
        else:
            checked = sum(
                1 for i in range(total)
                if self._table.item(i, _COL_ENABLE) is not None
                and self._table.item(i, _COL_ENABLE).checkState() == Qt.Checked
            )
            if checked == total:
                st = Qt.Checked
            elif checked == 0:
                st = Qt.Unchecked
            else:
                st = Qt.PartiallyChecked
        self._syncing = True
        self._header_check.setCheckState(st)
        self._syncing = False

    def get_selected_mod(self) -> ModInfo | None:
        """获取当前选中的 MOD，无选中则返回 None"""
        items = self._table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        if row < 0 or row >= len(self._mods):
            return None
        return self._mods[row]

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

    def get_mod_states(self) -> dict[str, bool]:
        """返回所有模组的启用状态 {mod_id: bool}"""
        result: dict[str, bool] = {}
        for i in range(self._table.rowCount()):
            if i >= len(self._mods):
                break
            item = self._table.item(i, _COL_ENABLE)
            result[self._mods[i].mod_id] = bool(item and item.checkState() == Qt.Checked)
        return result

    def set_mod_states(self, states: dict[str, bool]) -> None:
        """恢复模组启用状态 (用于存档恢复)"""
        self._loading = True
        for i in range(self._table.rowCount()):
            if i >= len(self._mods):
                break
            mod_id = self._mods[i].mod_id
            if mod_id in states:
                item = self._table.item(i, _COL_ENABLE)
                if item is not None:
                    item.setCheckState(Qt.Checked if states[mod_id] else Qt.Unchecked)
        self._loading = False
        self._update_header_check_state()
        self.state_changed.emit()

    def set_mods_dir(self, mods_dir: str):
        """更新 MOD 目录并刷新"""
        self._mods_dir = mods_dir
        self.refresh_mods()

    def has_duplicate_ids(self) -> bool:
        """检查当前模组列表中是否存在重复 ID"""
        id_counts: dict[str, int] = {}
        for mod in self._mods:
            id_counts[mod.mod_id] = id_counts.get(mod.mod_id, 0) + 1
        return any(v > 1 for v in id_counts.values())
