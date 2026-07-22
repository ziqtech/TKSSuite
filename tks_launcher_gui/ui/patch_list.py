"""补丁列表 — 单一面板内用 Tab 切换 可选/必选 两组补丁表格

每个表格含 启用/补丁名称/类型 三列。
必选补丁始终勾选且锁定不可改; 可选补丁可勾选并持久化。
Tab 顺序: 可选补丁 → 必选补丁, 默认选中可选补丁。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from core.config_loader import PatchDef
from editor_utils.dock_components import DockHeader

# 可选补丁区固定默认高度（不再按条数动态计算）；MOD 详情预览区同步使用此值
OPTIONAL_PATCH_DEFAULT_HEIGHT = 320

# 补丁内部类型 → 玩家友好中文标签 (显示于"类型"列)
_TYPE_LABELS = {
    "patch_imm32":            "数值修改",
    "patch_warpc_addr":       "地址重定位",
    "patch_bytes":            "指令修补",
    "cave_hook":              "代码注入",
    "patch_summon_table":     "召唤表",
    "runtime_watchdog":       "运行守护",
    "patch_drop_probability": "掉落概率",
    "patch_font_config":      "字体配置",
    "patch_animation_speed":  "动画速度",
}

_COLUMNS = ["启用", "补丁名称", "类型"]
_COL_ENABLE = 0
_COL_NAME = 1
_COL_TYPE = 2


class PatchListWidget(QWidget):
    """单一“补丁列表”面板, 用 Tab 切换 可选/必选 两组补丁表格。"""

    # 可选补丁勾选状态变化时发出, 供外部持久化保存
    state_changed = Signal()

    def __init__(self, patches: list[PatchDef],
                 initial_states: dict[str, bool] | None = None, parent=None):
        super().__init__(parent)

        # 持久化的勾选状态快照 (仅对可选补丁生效)
        self._initial_states: dict[str, bool] = initial_states or {}
        # id → (table, row) 行定位索引
        self._row_index: dict[str, tuple[QTableWidget, int]] = {}
        # 可选(可编辑)补丁 id 集合
        self._optional_ids: set[str] = set()
        # 各表格表头叠加的"全选"复选框 {table: QCheckBox}
        self._header_checks: dict[QTableWidget, QCheckBox] = {}
        self._syncing = False   # 防表头三态与行勾选互相触发的递归
        self._loading = False   # 批量设置勾选态时抑制逐条回调

        required = [p for p in patches if not p.optional]
        optional = [p for p in patches if p.optional]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 单一面板标题
        outer.addWidget(DockHeader("补丁列表"))

        self._req_table = self._make_table(required, interactive=False)
        self._opt_table = self._make_table(optional, interactive=True)

        # Tab 切换: 可选补丁在前, 必选补丁在后; 默认选中可选补丁
        self._tabs = QTabWidget()
        self._tabs.addTab(self._opt_table, f"可选补丁 ({len(optional)})")
        self._tabs.addTab(self._req_table, f"必选补丁 ({len(required)})")
        self._tabs.setCurrentIndex(0)
        outer.addWidget(self._tabs, 1)

        # 初始化可选表"全选"框的三态显示
        self._update_header_check_state()

    @property
    def optional_default_height(self) -> int:
        """可选补丁区的固定默认高度（供其他面板同步高度参考）。"""
        return OPTIONAL_PATCH_DEFAULT_HEIGHT

    # ── 表格构建 ──

    def _make_table(self, patches: list[PatchDef], interactive: bool) -> QTableWidget:
        """创建一个补丁表格。interactive=False 时行锁定(必选, 始终勾选)。"""
        table = QTableWidget(0, len(_COLUMNS))
        table.setHorizontalHeaderLabels(_COLUMNS)
        table.setProperty("class", "GrowthTable")  # 复用主题的表格选中/行背景样式
        table.setAlternatingRowColors(False)  # 移除斑马纹, 行背景统一
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)

        h = table.horizontalHeader()
        h.setHighlightSections(False)
        # 启用列固定为窄宽度（仅容纳居中的复选框），避免被表头文字撞宽
        h.setSectionResizeMode(_COL_ENABLE, QHeaderView.Fixed)
        table.setColumnWidth(_COL_ENABLE, 28)
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeToContents)

        if patches:
            table.setRowCount(len(patches))
            for row, p in enumerate(patches):
                self._fill_row(table, row, p, interactive)
        else:
            self._fill_empty(table)

        # 可选表格的勾选变化才需要通知外部保存 (必选行锁定, 不会变)
        if interactive:
            table.itemChanged.connect(self._on_item_changed)
        # 表头叠加"全选"复选框, 替代"启用"文字 (与模组列表一致)
        self._setup_header_check(table, interactive)
        return table

    def _fill_row(self, table: QTableWidget, row: int,
                  p: PatchDef, interactive: bool) -> None:
        # 启用列: 复选框
        enable_item = QTableWidgetItem()
        enable_item.setTextAlignment(Qt.AlignCenter)
        if interactive:
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # 可选补丁: 优先用持久化状态, 其次用 default_checked
            checked = self._initial_states.get(p.id, p.default_checked)
            self._optional_ids.add(p.id)
        else:
            # 必选补丁: 始终勾选, 锁定不可改 (不含 UserCheckable)
            enable_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checked = True
        enable_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        table.setItem(row, _COL_ENABLE, enable_item)

        # 补丁名称列: 纯中文名 (缺省回退 desc/id)
        name_item = QTableWidgetItem(p.name or p.desc or p.id)
        name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        table.setItem(row, _COL_NAME, name_item)

        # 类型列: 友好中文类型标签 (未知类型回退原始 type)
        type_item = QTableWidgetItem(_TYPE_LABELS.get(p.type, p.type))
        type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        type_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, _COL_TYPE, type_item)

        # 整行悬浮提示: 详细技术描述 + ID + 原始类型 (供进阶用户查阅)
        detail = p.desc or p.name or "(无描述)"
        tip = f"{detail}\n\nID: {p.id}\n类型: {p.type}"
        for col in range(len(_COLUMNS)):
            it = table.item(row, col)
            if it is not None:
                it.setToolTip(tip)

        self._row_index[p.id] = (table, row)

    def _fill_empty(self, table: QTableWidget) -> None:
        """无补丁时显示占位提示行。"""
        table.setRowCount(1)
        hint = QTableWidgetItem("（无）")
        hint.setFlags(Qt.ItemIsEnabled)
        hint.setForeground(Qt.gray)
        table.setItem(0, _COL_NAME, hint)
        table.setSpan(0, 0, 1, len(_COLUMNS))

    def _setup_header_check(self, table: QTableWidget, interactive: bool) -> None:
        """在表头"启用"列叠加复选框, 替代文字标题 (与模组列表一致)。

        可选表: 三态"全选/全不选"框; 必选表: 禁用的常勾选框 (仅示意锁定)。
        """
        h = table.horizontalHeader()
        table.setHorizontalHeaderItem(_COL_ENABLE, QTableWidgetItem(""))
        chk = QCheckBox(h)
        chk.setAttribute(Qt.WA_TranslucentBackground, True)
        chk.setStyleSheet("background: transparent;")
        if interactive:
            chk.setTristate(True)
            chk.setToolTip("全选 / 全不选")
            chk.stateChanged.connect(self._on_header_check_changed)
        else:
            chk.setChecked(True)
            chk.setEnabled(False)
            chk.setToolTip("必选补丁始终启用")
        self._header_checks[table] = chk
        h.geometriesChanged.connect(lambda: self._position_header_check(table))
        h.sectionResized.connect(lambda *_: self._position_header_check(table))
        self._position_header_check(table)

    def _position_header_check(self, table: QTableWidget) -> None:
        """将表头复选框定位到"启用"列 section 的中心。"""
        chk = self._header_checks.get(table)
        if chk is None:
            return
        h = table.horizontalHeader()
        x = h.sectionViewportPosition(_COL_ENABLE)
        w = h.sectionSize(_COL_ENABLE)
        if w <= 0:
            chk.setVisible(False)
            return
        sh = chk.sizeHint()
        chk.setGeometry(
            x + (w - sh.width()) // 2,
            (h.height() - sh.height()) // 2,
            sh.width(), sh.height())
        chk.setVisible(True)
        chk.raise_()

    # ── 事件 ──

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _COL_ENABLE:
            return
        self._update_header_check_state()
        self.state_changed.emit()

    def _on_header_check_changed(self, _state) -> None:
        """点击可选表"全选"框: 全部已选→全不选; 否则→全选。"""
        if self._syncing:
            return
        all_checked = bool(self._optional_ids) and all(
            self._is_checked(*self._row_index[pid]) for pid in self._optional_ids)
        self._set_all_optional(Qt.Unchecked if all_checked else Qt.Checked)

    def _update_header_check_state(self) -> None:
        """根据可选行勾选情况刷新表头"全选"框的三态。"""
        chk = self._header_checks.get(self._opt_table)
        if chk is None:
            return
        ids = self._optional_ids
        checked = sum(1 for pid in ids if self._is_checked(*self._row_index[pid]))
        if not ids or checked == 0:
            st = Qt.Unchecked
        elif checked == len(ids):
            st = Qt.Checked
        else:
            st = Qt.PartiallyChecked
        self._syncing = True
        chk.setCheckState(st)
        self._syncing = False

    # ── 对外接口 (保持与原实现一致) ──

    def get_selected_patches(self) -> set[str]:
        """返回所有勾选的补丁 id (必选恒选 + 已勾选的可选)。"""
        return {pid for pid, (t, r) in self._row_index.items()
                if self._is_checked(t, r)}

    def get_patch_states(self) -> dict[str, bool]:
        """返回所有可选补丁的勾选状态 {id: bool}（必选补丁始终启用, 不记录）。"""
        return {pid: self._is_checked(*self._row_index[pid])
                for pid in self._optional_ids}

    def set_patch_states(self, states: dict[str, bool]) -> None:
        """恢复可选补丁勾选状态 (用于存档恢复)。"""
        self._loading = True
        for pid, val in states.items():
            if pid in self._optional_ids:
                table, row = self._row_index[pid]
                item = table.item(row, _COL_ENABLE)
                if item is not None:
                    item.setCheckState(Qt.Checked if val else Qt.Unchecked)
        self._loading = False
        self._update_header_check_state()
        self.state_changed.emit()

    def select_all(self):
        self._set_all_optional(Qt.Checked)

    def deselect_all(self):
        self._set_all_optional(Qt.Unchecked)

    # ── 内部辅助 ──

    def _set_all_optional(self, state) -> None:
        """批量设置可选补丁勾选态 (必选行锁定, 不受影响)。"""
        self._loading = True
        for pid in self._optional_ids:
            table, row = self._row_index[pid]
            item = table.item(row, _COL_ENABLE)
            if item is not None:
                item.setCheckState(state)
        self._loading = False
        self._update_header_check_state()
        self.state_changed.emit()

    @staticmethod
    def _is_checked(table: QTableWidget, row: int) -> bool:
        item = table.item(row, _COL_ENABLE)
        return item is not None and item.checkState() == Qt.Checked
