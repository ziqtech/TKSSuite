"""我的 MOD 面板 — 可滚动扁平列表

结构:
    兼容模式说明条 (仅兼容模式显示)
    可滚动表格: 启用 / 模组名称 / 分类 / 作者 (其余字段进悬浮提示与详情面板)
兼容模式下标题区显示"兼容模式下仍可加载已勾选的 MOD。"。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.mod_loader import ModInfo, scan_mods
from ui.centered_checkbox_delegate import (
    CenteredCheckBoxDelegate, position_checkbox_indicator,
)
from editor_utils.dock_components import create_dock

# 行布局: 名称 + 分类 + 作者; ID/加载顺序/描述进悬浮提示与详情面板
_COLUMNS = ["启用", "模组名称", "分类", "作者"]
_COL_ENABLE = 0
_COL_NAME = 1
_COL_CATEGORY = 2
_COL_AUTHOR = 3

_CATEGORY_LABELS = {
    "visual": "美化", "avatar": "头像", "music": "音乐",
    "story": "剧情", "gameplay": "功能", "save": "存档",
    "tks_exe": "TKS.exe 替换", "config": "配置", "mixed": "综合",
    "other": "其他", "font": "字体", "interface": "界面", "map": "地图",
}

# 分类 → QSS class 名 (各分类的 Tag 配色维护于 editor_themes 两个主题文件)
_CATEGORY_CLASSES = {
    "visual": "TagVisual", "avatar": "TagAvatar", "music": "TagMusic",
    "story": "TagStory", "gameplay": "TagGameplay", "save": "TagSave",
    "tks_exe": "TagExe", "config": "TagConfig", "mixed": "TagMixed",
    "other": "TagOther", "font": "TagFont", "interface": "TagInterface",
    "map": "TagMap",
}


class _CategoryTag(QWidget):
    """分类彩色 Tag 标签。

    PySide6 (Qt Widgets) 没有可嵌入表格的原生 Tag/Chip 组件,
    故自定义轻量实现: 居中 QLabel + 主题 QSS 按分类着色。
    """

    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        lay.addStretch(1)
        self._label = QLabel(_CATEGORY_LABELS.get(category, "其他"))
        self._label.setProperty(
            "class", _CATEGORY_CLASSES.get(category, "TagOther"))
        self._label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._label)
        lay.addStretch(1)

    def text(self) -> str:
        return self._label.text()

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self._label.setToolTip(tip)


class ModListWidget(QWidget):
    """我的 MOD 面板，嵌入主窗口。选中行时发出 mod_selected 信号。"""

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
        # row → self._mods 下标
        self._row_mod_index: dict[int, int] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Dock 面板内容 (DockHeader + DockBody 包裹)
        content = QWidget()
        # 裸 QWidget 会被全局 QWidget 背景规则染色, 透明以露出 DockBody 表面
        content.setObjectName("TransparentBg")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        # 表格
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setObjectName("LauncherModTable")
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setProperty("class", "GrowthTable")  # 复用主题的表格选中/行背景样式
        self._table.setAlternatingRowColors(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.ElideRight)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.currentItemChanged.connect(self._on_current_changed)

        h = self._table.horizontalHeader()
        h.setHighlightSections(False)
        h.setSectionResizeMode(_COL_ENABLE, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_ENABLE, 40)
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        # 分类使用彩色 Tag，给它稳定的呼吸空间，避免长分类被压成色块。
        h.setSectionResizeMode(_COL_CATEGORY, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_CATEGORY, 120)
        h.setSectionResizeMode(_COL_AUTHOR, QHeaderView.Interactive)
        self._table.setColumnWidth(_COL_AUTHOR, 96)
        self._table.setItemDelegateForColumn(
            _COL_ENABLE, CenteredCheckBoxDelegate(self._table))

        # 启用列表头叠加一个真实 QCheckBox（受 QCheckBox::indicator QSS 样式控制，
        # 与表格单元格复选框外观一致），用作全选/全不选
        self._header = h
        self._table.setHorizontalHeaderItem(_COL_ENABLE, QTableWidgetItem(""))
        self._header_check = QCheckBox(h)
        self._header_check.setObjectName("headerCheck")
        self._header_check.setTristate(True)
        self._header_check.stateChanged.connect(self._on_header_check_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        # 表头尺寸/位置变化时重新定位复选框
        h.geometriesChanged.connect(self._position_header_check)
        h.sectionResized.connect(self._position_header_check)

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

        outer.addWidget(create_dock("MOD列表", content, header_layout=header_row,
                                    body_margins=(0, 0, 0, 0)))

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
        # 默认排序: 加载顺序 > 作者 > 模组名称 > 版本号 > 描述 > ID
        self._mods.sort(key=self._default_sort_key)

        # 检测重复 ID
        dup_ids = self._detect_dup_ids()
        self.duplicate_ids_detected.emit(len(dup_ids) > 0)

        self._populate_table(dup_ids)

        self._loading = False
        self._update_header_check_state()

    def _detect_dup_ids(self) -> set[str]:
        """检测当前模组列表中的重复 ID"""
        id_counts: dict[str, int] = {}
        for mod in self._mods:
            id_counts[mod.mod_id] = id_counts.get(mod.mod_id, 0) + 1
        return {k for k, v in id_counts.items() if v > 1}

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

    def _populate_table(self, dup_ids: set[str] | None = None):
        """从 self._mods 按排序顺序填充表格行 (保留刷新前滚动位置)"""
        if dup_ids is None:
            dup_ids = set()
        scroll = self._table.verticalScrollBar().value()

        self._table.setRowCount(len(self._mods))
        self._row_mod_index.clear()
        for row, mod in enumerate(self._mods):
            self._row_mod_index[row] = row
            enable_item = QTableWidgetItem()
            enable_item.setTextAlignment(Qt.AlignCenter)
            enable_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # 优先用持久化状态覆盖; 持久化中无记录时用 mod.enabled
            if mod.mod_id in self._initial_states:
                is_enabled = self._initial_states[mod.mod_id]
            else:
                is_enabled = mod.enabled
            enable_item.setCheckState(Qt.Checked if is_enabled else Qt.Unchecked)
            self._table.setItem(row, _COL_ENABLE, enable_item)

            name_item = self._set_text(row, _COL_NAME, mod.name)
            is_dup = mod.mod_id in dup_ids
            if is_dup:
                # 重复 ID 双重指示: 红色 + 加粗 (避免颜色作为唯一信号)
                name_item.setForeground(QColor(220, 50, 50))
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
            # 分类列: 彩色 Tag 标签 (列表不显示"自动识别"字样, 仅保留在悬浮提示)
            inferred = "（自动识别）" if mod.inferred_metadata else ""
            tag = _CategoryTag(mod.category or "other")
            self._table.setCellWidget(row, _COL_CATEGORY, tag)
            self._set_text(row, _COL_AUTHOR, mod.author or "未知")

            # 整行 tooltip: 高级信息 (ID/加载顺序/标签/兼容声明) 不进列
            compatibility = mod.compatibility.get("compatible")
            if compatibility is True:
                compat_label = "兼容模式：作者声明支持"
            elif compatibility is False:
                compat_label = "兼容模式：作者声明不支持"
            else:
                compat_label = "兼容模式：作者未声明"
            tag_text = ", ".join(mod.tags) if mod.tags else "无"
            tip = (f"{mod.description or '(无说明)'}\n\n"
                   f"分类: {mod.category or 'other'}{inferred}\n"
                   f"版本: {mod.version or '未知'}\n标签: {tag_text}\n"
                   f"{compat_label}\n加载顺序: {mod.load_order}\nID: {mod.mod_id}")
            if is_dup:
                tip += "\n⚠ 该 ID 与其他模组重复"
            for col in range(len(_COLUMNS)):
                it = self._table.item(row, col)
                if it is not None:
                    it.setToolTip(tip)
            tag.setToolTip(tip)
        self._table.verticalScrollBar().setValue(scroll)

    # ── 表头全选 ──

    def _position_header_check(self):
        """将表头复选框定位到启用列 section 的中心"""
        h = self._header
        x = h.sectionViewportPosition(_COL_ENABLE)
        w = h.sectionSize(_COL_ENABLE)
        if w <= 0:
            self._header_check.setVisible(False)
            return
        position_checkbox_indicator(self._header_check, x, w, h.height())
        self._header_check.setVisible(True)
        self._header_check.raise_()

    def _mod_rows(self) -> list[int]:
        """全部模组行 (表头全选的作用范围)。"""
        return list(self._row_mod_index)

    def _on_item_changed(self, item):
        """单行勾选状态变化时，同步表头复选框的三态"""
        if self._loading or item.column() != _COL_ENABLE:
            return
        self._update_header_check_state()
        self.state_changed.emit()

    def _on_header_check_changed(self, state):
        """点击表头复选框：模组行全部已选 -> 全不选；否则 -> 全选。"""
        if self._syncing:
            return
        rows = self._mod_rows()
        all_checked = bool(rows) and all(self._is_checked(r) for r in rows)
        self._set_rows_check_state(
            rows, Qt.Unchecked if all_checked else Qt.Checked)

    def _set_rows_check_state(self, rows: list[int], state) -> None:
        self._loading = True
        for row in rows:
            cell = self._table.item(row, _COL_ENABLE)
            if cell is not None:
                cell.setCheckState(state)
        self._loading = False
        self._update_header_check_state()
        self.state_changed.emit()

    def _update_header_check_state(self):
        """根据模组行勾选情况刷新表头复选框状态（三态）"""
        rows = self._mod_rows()
        checked = sum(1 for r in rows if self._is_checked(r))
        if not rows or checked == 0:
            st = Qt.Unchecked
        elif checked == len(rows):
            st = Qt.Checked
        else:
            st = Qt.PartiallyChecked
        self._syncing = True
        self._header_check.setCheckState(st)
        self._syncing = False

    def _is_checked(self, row: int) -> bool:
        item = self._table.item(row, _COL_ENABLE)
        return item is not None and item.checkState() == Qt.Checked

    # ── 对外接口 ──

    def _on_current_changed(self, current, previous):
        if current is None:
            self.mod_selected.emit(None)
            return
        mod_index = self._row_mod_index.get(current.row())
        if mod_index is None:
            self.mod_selected.emit(None)
            return
        self.mod_selected.emit(self._mods[mod_index])

    def _set_text(self, row: int, col: int, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, col, item)
        return item

    def get_selected_mod(self) -> ModInfo | None:
        """获取当前选中的 MOD，无选中则返回 None"""
        items = self._table.selectedItems()
        if not items:
            return None
        mod_index = self._row_mod_index.get(items[0].row())
        if mod_index is None:
            return None
        return self._mods[mod_index]

    def get_enabled_mods(self) -> list[ModInfo]:
        """获取所有勾选启用的 MOD 列表"""
        enabled = []
        for row, mod_index in self._row_mod_index.items():
            item = self._table.item(row, _COL_ENABLE)
            self._mods[mod_index].enabled = bool(item and item.checkState() == Qt.Checked)
            if self._mods[mod_index].enabled:
                enabled.append(self._mods[mod_index])
        return enabled

    def get_mod_states(self) -> dict[str, bool]:
        """返回所有模组的启用状态 {mod_id: bool}"""
        result: dict[str, bool] = {}
        for row, mod_index in self._row_mod_index.items():
            item = self._table.item(row, _COL_ENABLE)
            result[self._mods[mod_index].mod_id] = bool(item and item.checkState() == Qt.Checked)
        return result

    def set_mod_states(self, states: dict[str, bool]) -> None:
        """恢复模组启用状态 (用于存档恢复)"""
        self._loading = True
        for row, mod_index in self._row_mod_index.items():
            mod_id = self._mods[mod_index].mod_id
            if mod_id in states:
                item = self._table.item(row, _COL_ENABLE)
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
