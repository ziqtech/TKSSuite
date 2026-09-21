"""游戏功能面板 — 单一可滚动扁平列表

结构自上而下:
    兼容模式说明条 (仅兼容模式显示)
    可滚动表格: 启用 / 功能名称 / 状态(必选·推荐·可选)
    选中项目详情

必选功能始终勾选且锁定不可改; 可选功能可勾选并持久化。
兼容模式下面板整体置灰并显示说明, 勾选状态保留。
"""
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QLabel, QToolButton,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
    QHBoxLayout,
)
from core.config_loader import PatchDef, patch_metadata, resolve_effective_patches
from core.patch_plan import migrate_patch_states
from ui.centered_checkbox_delegate import (
    CenteredCheckBoxDelegate, position_checkbox_indicator,
)
from editor_utils.dock_components import create_dock
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.ui_helpers import wrap_tooltip_text

# 可选补丁区固定默认高度（供 MOD 详情预览区同步高度参照）
OPTIONAL_PATCH_DEFAULT_HEIGHT = 320

_COLUMNS = ["启用", "功能名称", "类型"]
_COL_ENABLE = 0
_COL_NAME = 1
_COL_TYPE = 2

# 补丁内部类型 → 玩家友好中文标签 (显示于"类型"列与详情框)
# 维护约定: 这里必须覆盖 patch_engine 实际分发的全部 type, 否则"类型"列会漏出
# 英文内部名 (例如 fixed_layout_cave / patch_sites / patch_data_expand)。
_TYPE_LABELS = {
    "patch_imm32": "数值修改",
    "patch_warpc_addr": "地址重定位",
    "patch_bytes": "指令修补",
    "patch_extra_section": "额外段修补",
    "patch_data_expand": "数据段注入",
    "patch_exp_lock": "经验锁定",
    "cave_hook": "代码注入",
    "fixed_layout_cave": "固定布局注入",
    "patch_sites": "位点表注入",
    "patch_summon_table": "召唤表",
    "patch_drop_probability": "掉落概率",
    "patch_font_config": "字体配置",
    "patch_animation_speed": "动画速度",
    "script": "外部脚本",
    "bundle": "组合补丁",
}


def patch_type_label(type_name: str) -> str:
    """内部 type → 玩家友好中文标签 (未知 type 原样返回)。

    所有面向玩家的界面 (补丁列表 / 详情框 / "生成启动器") 都走这里, 避免各处
    自己 `get(type, type)` 而在新类型上漏出英文内部名。
    """
    return _TYPE_LABELS.get(type_name, type_name)


class PatchListWidget(QWidget):
    """游戏功能面板: 可滚动扁平列表 + 选中详情。"""

    # 可选补丁勾选状态变化时发出, 供外部持久化保存
    state_changed = Signal()

    def __init__(self, patches: list[PatchDef],
                 initial_states: dict[str, bool] | None = None, parent=None):
        super().__init__(parent)

        # 全量定义仅用于依赖解析; internal 不成为用户可切换的列表项。
        self._patches = list(patches)
        self._visible_patches = [
            p for p in self._patches if not patch_metadata(p, "internal", False)]
        self._initial_states = migrate_patch_states(
            self._patches, initial_states or {})
        # id → row 行定位索引
        self._row_index: dict[str, int] = {}
        # row → PatchDef 行索引
        self._row_patch: dict[int, PatchDef] = {}
        # 可选(可编辑) 补丁 id 集合
        self._optional_ids = {p.id for p in self._visible_patches if p.optional}
        self._option_checks: dict[str, QCheckBox] = {}
        self._options_by_patch: dict[str, list[QCheckBox]] = {}
        self._syncing = False   # 防表头三态与行勾选互相触发的递归
        self._loading = False   # 批量设置勾选态时抑制逐条回调
        self._view = "optional"  # Dock 右侧切换: 可选补丁 / 必选补丁
        self._compatible_mode = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        # 裸 QWidget 会被全局 QWidget 背景规则染色, 透明以露出 DockBody 表面
        content.setObjectName("TransparentBg")
        layout = QVBoxLayout(content)
        # 列表与详情之间留出清晰的层级间距，避免两个表面粘连。
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(8)

        # 可滚动表格
        self._table = self._make_table()
        layout.addWidget(self._table, 1)

        # 选中项目详情
        self._detail = QTextBrowser()
        self._detail.setObjectName("detailBox")
        self._detail.setPlaceholderText("选中游戏功能查看详情")
        self._detail.setFixedHeight(96)
        self._detail.setOpenLinks(False)
        layout.addWidget(self._detail)
        self._options_box = self._make_options()
        layout.addWidget(self._options_box)

        # body_margins 四周内收: 表格避开 DockBody 圆角, 顶部与左右间距一致
        outer.addWidget(
            create_dock("补丁列表", content, header_layout=self._build_header_toggle(),
                        body_margins=(6, 6, 6, 6)), 1)

        # 兼容模式蒙板: 覆盖整个面板 (含标题栏), 圆角与 DockHeader/DockBody 一致 (样式见 QSS)
        self._compat_overlay = QWidget(self)
        self._compat_overlay.setObjectName("compatOverlay")
        ov_lay = QVBoxLayout(self._compat_overlay)
        ov_lay.setContentsMargins(0, 0, 0, 0)
        ov_lab = QLabel("兼容模式不启用")
        ov_lab.setObjectName("compatOverlayLabel")
        ov_lab.setAlignment(Qt.AlignCenter)
        ov_lay.addWidget(ov_lab)
        self._compat_overlay.hide()

        self._populate()
        self._apply_view()
        self._update_header_check_state()

    def _make_options(self) -> QWidget:
        """包内高级选项独立保存, 仅在选中所属包时显示, 不参与全选。"""
        box = QWidget()
        box.setObjectName("TransparentBg")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel("高级选项（不随全选改变）"))
        for patch in self._visible_patches:
            checks = []
            for option in patch_metadata(patch, "options", []):
                oid = option["id"]
                check = QCheckBox(option.get("name") or oid)
                check.setChecked(bool(self._initial_states.get(
                    oid, option.get("default", False))))
                tip = (f"{wrap_tooltip_text(option.get('desc') or '（无说明）')}"
                       f"\n\nID: {oid}\n此选项独立保存，不随全选改变。")
                check.setToolTip("<qt>" + escape(tip).replace("\n", "<br>") + "</qt>")
                check.toggled.connect(self._on_option_changed)
                layout.addWidget(check)
                self._option_checks[oid] = check
                checks.append(check)
            self._options_by_patch[patch.id] = checks
        box.hide()
        return box

    def _build_header_toggle(self) -> QHBoxLayout:
        """Dock 标题栏右侧的 可选补丁 / 必选补丁 切换按钮。"""
        header_right = QHBoxLayout()
        header_right.setContentsMargins(0, 0, 0, 0)
        header_right.setSpacing(4)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._btn_opt = QToolButton()
        self._btn_opt.setText(f"可选补丁 ({len(self._optional_ids)})")
        self._btn_opt.setCheckable(True)
        self._btn_opt.setAutoRaise(True)
        self._btn_opt.setObjectName("dockToolButton")
        self._btn_opt.setCursor(Qt.PointingHandCursor)
        self._btn_req = QToolButton()
        self._btn_req.setText(
            f"必选补丁 ({len(self._visible_patches) - len(self._optional_ids)})")
        self._btn_req.setCheckable(True)
        self._btn_req.setAutoRaise(True)
        self._btn_req.setObjectName("dockToolButton")
        self._btn_req.setCursor(Qt.PointingHandCursor)
        self._view_group.addButton(self._btn_opt, 0)
        self._view_group.addButton(self._btn_req, 1)
        self._btn_opt.setChecked(True)
        self._view_group.idClicked.connect(self._on_view_changed)
        header_right.addWidget(self._btn_opt)
        header_right.addWidget(self._btn_req)
        return header_right

    def _on_view_changed(self, index: int) -> None:
        self._view = "optional" if index == 0 else "required"
        self._apply_view()

    def _apply_view(self) -> None:
        """按当前切换状态显隐行: 可选补丁 / 必选补丁。"""
        show_optional = self._view == "optional"
        for row, patch in self._row_patch.items():
            self._table.setRowHidden(row, patch.optional != show_optional)
        # 必选视图下全选框无意义, 置灰
        self._header_check.setEnabled(show_optional and not self._compatible_mode)
        self._update_header_check_state()
        self._on_selection_changed()

    @property
    def optional_default_height(self) -> int:
        """可选补丁区的固定默认高度（供其他面板同步高度参照）。"""
        return OPTIONAL_PATCH_DEFAULT_HEIGHT

    # ── 表格构建 ──

    def _make_table(self) -> QTableWidget:
        table = AdaptiveTableWidget(
            0, len(_COLUMNS),
            stretch_columns={_COL_NAME},
            minimum_widths=[40, 140, 80],
            row_height=30,
            fill_viewport=True,
        )
        table.setObjectName("LauncherPatchTable")
        table.setHorizontalHeaderLabels(_COLUMNS)
        table.setProperty("class", "GrowthTable")  # 复用主题的表格选中/行背景样式
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.verticalHeader().setVisible(False)

        h = table.horizontalHeader()
        h.setHighlightSections(False)
        # 启用列复选框由专用委托严格居中绘制。
        table.setItemDelegateForColumn(
            _COL_ENABLE, CenteredCheckBoxDelegate(table))

        table.itemChanged.connect(self._on_item_changed)
        table.itemSelectionChanged.connect(self._on_selection_changed)
        self._setup_header_check(table)
        return table

    def _populate(self) -> None:
        """按加载顺序重建表格行 (勾选状态来自持久化快照/默认值)。"""
        table = self._table
        scroll = table.verticalScrollBar().value() if table.rowCount() else 0

        self._loading = True
        try:
            table.setRowCount(len(self._visible_patches))
            self._row_index.clear()
            self._row_patch.clear()
            for row, patch in enumerate(self._visible_patches):
                self._row_patch[row] = patch
                self._fill_row(row, patch)
                self._row_index[patch.id] = row
        finally:
            self._loading = False

        table.verticalScrollBar().setValue(scroll)

    def _fill_row(self, row: int, p: PatchDef) -> None:
        table = self._table
        # 启用列: 复选框
        enable_item = QTableWidgetItem()
        enable_item.setTextAlignment(Qt.AlignCenter)
        if p.optional:
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # 可选补丁: 优先用持久化状态, 其次用 default_checked
            checked = self._initial_states.get(p.id, p.default_checked)
        else:
            # 必选补丁: 始终勾选, 锁定不可改 (不含 UserCheckable)
            enable_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checked = True
        enable_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        table.setItem(row, _COL_ENABLE, enable_item)

        # 名称列: 纯中文名 (缺省回退 desc/id); 显式提示包内可发现的选项入口。
        name = p.name or p.desc or p.id
        if self._options_by_patch.get(p.id):
            name += "（含高级选项）"
        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        table.setItem(row, _COL_NAME, name_item)

        # 类型列: 玩家友好标签 (未知类型回退原始 type)
        type_item = QTableWidgetItem(patch_type_label(p.type))
        type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        type_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, _COL_TYPE, type_item)

        # 整行悬浮提示: 详细技术描述 + ID + 原始类型 (供进阶用户查阅)
        # 说明按固定像素宽度预换行: Qt 自带 tooltip 的换行阈值随屏幕宽度变化,
        # 中等长度的说明在宽屏上会拉成一条横贯屏幕的宽条 (见 wrap_tooltip_text)
        tip = (f"{wrap_tooltip_text(p.desc or p.name or '(无描述)')}\n\n"
               f"类型: {patch_type_label(p.type)} ({p.type})\nID: {p.id}")
        if self._options_by_patch.get(p.id):
            tip += "\n选中此补丁，在详情下方调整高级选项。"
        tip = "<qt>" + escape(tip).replace("\n", "<br>") + "</qt>"
        for col in range(len(_COLUMNS)):
            it = table.item(row, col)
            if it is not None:
                it.setToolTip(tip)

    def _setup_header_check(self, table: QTableWidget) -> None:
        """在表头"启用"列叠加三态"全选"复选框 (只统计可选功能行)。"""
        h = table.horizontalHeader()
        table.setHorizontalHeaderItem(_COL_ENABLE, QTableWidgetItem(""))
        chk = QCheckBox(h)
        chk.setObjectName("headerCheck")
        chk.setAttribute(Qt.WA_TranslucentBackground, True)
        chk.setTristate(True)
        chk.setToolTip("全选 / 全不选 (可选功能)")
        chk.stateChanged.connect(self._on_header_check_changed)
        self._header_check = chk
        h.geometriesChanged.connect(lambda: self._position_header_check(table))
        h.sectionResized.connect(lambda *_: self._position_header_check(table))
        self._position_header_check(table)

    def _position_header_check(self, table: QTableWidget) -> None:
        """将表头复选框定位到"启用"列 section 的中心。"""
        chk = getattr(self, "_header_check", None)
        if chk is None:
            return
        h = table.horizontalHeader()
        x = h.sectionViewportPosition(_COL_ENABLE)
        w = h.sectionSize(_COL_ENABLE)
        if w <= 0:
            chk.setVisible(False)
            return
        position_checkbox_indicator(chk, x, w, h.height())
        chk.setVisible(True)
        chk.raise_()

    # ── 事件 ──

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _COL_ENABLE:
            return
        self._update_header_check_state()
        self._on_selection_changed()
        self.state_changed.emit()

    def _on_option_changed(self, _checked: bool) -> None:
        if self._loading:
            return
        self._on_selection_changed()
        self.state_changed.emit()

    def _on_selection_changed(self) -> None:
        """详情仅解析当前用户选择, 不读取游戏数据或把自动依赖写回勾选态。"""
        if self._loading:
            return
        rows = self._table.selectionModel().selectedRows()
        patch = None
        for index in rows:
            if self._table.isRowHidden(index.row()):
                continue
            patch = self._row_patch.get(index.row())
            if patch is not None:
                break
        for pid, checks in self._options_by_patch.items():
            for check in checks:
                check.setVisible(patch is not None and pid == patch.id)
        self._options_box.setVisible(
            patch is not None and bool(self._options_by_patch.get(patch.id)))
        if patch is None:
            self._detail.clear()
            return
        status = ("必选" if not patch.optional
                  else "推荐" if patch.default_checked else "可选")
        detail = (
            f"<b>名称：</b>{escape(patch.name or patch.id)}<br>"
            f"<b>类型：</b>{escape(patch_type_label(patch.type))}<br>"
            f"<b>状态：</b>{status}<br>"
            f"<b>说明：</b>{escape(patch.desc or '（无）')}")
        selected = self.get_selected_patches()
        try:
            effective = resolve_effective_patches(self._patches, selected=selected)
        except ValueError as exc:
            detail += f"<br><b>依赖解析：</b>{escape(str(exc))}"
        else:
            names = {p.id: p.name or p.id for p in self._patches}
            names.update({oid: check.text()
                          for oid, check in self._option_checks.items()})

            def display_name(pid):
                return escape(names.get(pid, pid))

            def dependency_reason(pid):
                source = effective.required_by.get(pid)
                return f"{display_name(source)} 的依赖" if source else "必选基础支持"

            if patch.id in effective.superseded:
                reason = f"由 {display_name(effective.superseded[patch.id])} 替代"
            elif patch.id not in effective.ids:
                reason = "未启用"
            elif not patch.optional:
                reason = "必选补丁"
            elif patch.id in selected:
                reason = "用户选择"
            else:
                reason = f"自动启用（{dependency_reason(patch.id)}）"
            detail += f"<br><b>启用原因：</b>{reason}"
            automatic = [
                f"{display_name(p.id)}（{dependency_reason(p.id)}）"
                for p in effective.patches if p.id not in selected]
            if automatic:
                detail += "<br><b>当前选择的自动依赖：</b><br>" + "<br>".join(automatic)
        detail += "<br>数据文件检测由运行前计划处理。"
        self._detail.setHtml(detail)

    def _on_header_check_changed(self, _state) -> None:
        """点击表头"全选"框: 可选行全部已选→全不选; 否则→全选。"""
        if self._syncing:
            return
        rows = self._optional_rows()
        all_checked = bool(rows) and all(self._is_checked(r) for r in rows)
        self._set_rows_check_state(
            rows, Qt.Unchecked if all_checked else Qt.Checked)

    def _set_rows_check_state(self, rows: list[int], state) -> None:
        self._loading = True
        for row in rows:
            item = self._table.item(row, _COL_ENABLE)
            if item is not None:
                item.setCheckState(state)
        self._loading = False
        self._update_header_check_state()
        self._on_selection_changed()
        self.state_changed.emit()

    def _update_header_check_state(self) -> None:
        """根据可选行勾选情况刷新表头"全选"框的三态。"""
        chk = getattr(self, "_header_check", None)
        if chk is None:
            return
        rows = self._optional_rows()
        checked = sum(1 for r in rows if self._is_checked(r))
        if not rows or checked == 0:
            st = Qt.Unchecked
        elif checked == len(rows):
            st = Qt.Checked
        else:
            st = Qt.PartiallyChecked
        self._syncing = True
        chk.setCheckState(st)
        self._syncing = False

    def _optional_rows(self) -> list[int]:
        """当前可见的可选功能行 (表头全选的作用范围)。"""
        return [row for row, patch in self._row_patch.items()
                if patch.optional and not self._table.isRowHidden(row)]

    # ── 兼容模式 ──

    def set_compatible_mode(self, compatible: bool) -> None:
        """兼容模式下整体置灰并罩上蒙板; 勾选状态保留, 不清空。提示文案由主窗口状态栏展示。"""
        self._compatible_mode = compatible
        for widget in (self._table, self._options_box,
                       self._btn_opt, self._btn_req):
            widget.setEnabled(not compatible)
        self._header_check.setEnabled(not compatible and self._view == "optional")
        self._compat_overlay.setVisible(compatible)
        if compatible:
            self._compat_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 蒙板始终铺满整个面板
        if hasattr(self, "_compat_overlay"):
            self._compat_overlay.setGeometry(0, 0, self.width(), self.height())

    # ── 对外接口 (保持与原实现一致) ──

    def get_selected_patches(self) -> set[str]:
        """返回用户选择 + 必选 + 已选高级选项 ID, 不把自动依赖变成手选。"""
        return ({pid for pid, row in self._row_index.items()
                 if self._is_checked(row)}
                | {oid for oid, check in self._option_checks.items()
                   if check.isChecked()})

    def get_patch_states(self) -> dict[str, bool]:
        """保存普通可选项及全部高级选项, 包括明确关闭的 False。"""
        states = {pid: self._is_checked(self._row_index[pid])
                  for pid in self._optional_ids}
        states.update({oid: check.isChecked()
                       for oid, check in self._option_checks.items()})
        return states

    def set_patch_states(self, states: dict[str, bool]) -> None:
        """迁移并恢复可选补丁和高级选项勾选状态 (用于存档恢复)。"""
        states = migrate_patch_states(self._patches, states)
        self._loading = True
        try:
            for pid, val in states.items():
                if pid in self._optional_ids:
                    row = self._row_index[pid]
                    item = self._table.item(row, _COL_ENABLE)
                    if item is not None:
                        item.setCheckState(Qt.Checked if val else Qt.Unchecked)
                elif pid in self._option_checks:
                    self._option_checks[pid].setChecked(bool(val))
        finally:
            self._loading = False
        self._update_header_check_state()
        self._on_selection_changed()
        self.state_changed.emit()

    def select_all(self):
        self._set_rows_check_state(self._optional_rows(), Qt.Checked)

    def deselect_all(self):
        self._set_rows_check_state(self._optional_rows(), Qt.Unchecked)

    # ── 内部辅助 ──

    def _is_checked(self, row: int) -> bool:
        item = self._table.item(row, _COL_ENABLE)
        return item is not None and item.checkState() == Qt.Checked
