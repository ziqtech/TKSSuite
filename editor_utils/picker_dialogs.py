"""
通用选择器对话框 — 供所有编辑器统一使用
包含: TktPickerDialog (TKT 文本选择器)
      SkillPickerDialog (技能选择器 — 参数化数据源)
      StatusPickerDialog (状态位掩码多选器)
      WarpcPickerDialog (WarPC 角色选择器)
      ItemPickerDialog  (物品选择器 — 完整表格 + 页面/权限/非空筛选)
      BitmaskPickerDialog (位标志多选器 — item/warpc 旗标与使用权限弹窗共用)
      GrowthTableDialog (角色逐级成长数据表 — warpc 编辑器/tks_book 查看器共用)
"""
import json

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from editor_utils.ui_helpers import resolve_config_path, EditorComboBox
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.search_utils import search_match
from editor_utils.theme_manager import business_colors
from editor_utils.theme_switcher import apply_theme_to_window
from editor_utils.window_theme import apply_titlebar_theme


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
        self.table = AdaptiveTableWidget(
            0, 2,
            stretch_columns={1},
            minimum_widths=[60, 90],
        )
        self.table.setHorizontalHeaderLabels(["ID", "文本"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("✅ 确定")
        btn_ok.clicked.connect(self._accept)
        btn_layout.addWidget(btn_ok)
        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        # 数据
        self._data = sorted(tkt_dict.items(), key=lambda x: x[0])
        self._populate()

    def showEvent(self, event):
        super().showEvent(event)

        # 选中当前值
        if self.selected_id > 0:
            for row in range(self.table.rowCount()):
                if int(self.table.item(row, 0).text()) == self.selected_id:
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


class SkillPickerDialog(QDialog):
    """技能选择对话框 — 搜索/类型筛选表格, 双击或确定返回所选行 key。

    阶段 4 去重: 合并 item / skill / warpc 三份同构实现, 数据源由调用方
    预构建为 ``rows``, 每项 ``(key, cells, type_id)``:
      key: 确定后写入 ``selected_index`` 的整数 (技能索引);
      cells: 表格显示文本元组 (长度与 headers 一致);
      type_id: 类型筛选匹配值 (无类型维度的调用方恒传 None)。

    Args:
        parent: 父窗口
        rows: 行数据 (见上)
        headers: 表头标签
        stretch_columns / minimum_widths: 透传 AdaptiveTableWidget
        type_filter: ``[(匹配值, 显示名)]`` — 提供时显示"类型"下拉
            (type_id 为 None 的行仅在"全部"时可见)
        clear_value: "清空"按钮写入 selected_index 的值 (item/skill=0, warpc=-1)
        clear_label: 清空按钮文本
        size: 窗口尺寸
    """

    def __init__(self, parent, rows, headers, *,
                 stretch_columns=None, minimum_widths=None,
                 type_filter=None, clear_value=0,
                 clear_label="清空选择", size=(460, 550)):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(*size)
        self.selected_index = None
        self._rows = rows
        self._clear_value = clear_value

        layout = QVBoxLayout(self)
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        sf.addWidget(self.search_box)
        self.type_box = None
        if type_filter:
            sf.addWidget(QLabel("类型:"))
            self.type_box = EditorComboBox()
            self.type_box.addItem("全部", userData=None)
            for value, display in type_filter:
                self.type_box.addItem(display, userData=value)
            self.type_box.currentIndexChanged.connect(self._refresh)
            sf.addWidget(self.type_box)
        layout.addLayout(sf)

        self.table = AdaptiveTableWidget(
            0, len(headers),
            stretch_columns=stretch_columns,
            minimum_widths=minimum_widths,
        )
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        bl = QHBoxLayout()
        bl.addWidget(QPushButton(clear_label, clicked=self._clear))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept))
        layout.addLayout(bl)
        self._refresh()

    def _refresh(self):
        query = self.search_box.text()
        ft = self.type_box.currentData() if self.type_box else None
        self.table.setRowCount(0)
        self._row_keys = []
        for key, cells, type_id in self._rows:
            if ft is not None and type_id != ft:
                continue
            if not search_match(query, key, *cells):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
            self._row_keys.append(key)

    def _accept(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = self._row_keys[sel[0].row()]
            self.accept()

    def _clear(self):
        self.selected_index = self._clear_value
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
        self.setWindowTitle(title)
        self.resize(380, 520)
        self.selected_mask = None
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        cl = QVBoxLayout(content)
        self.checkboxes = []
        for i in range(16):
            idx = base + i
            if idx >= len(status_names): break
            row = QHBoxLayout()
            if get_pixmap_fn is not None:
                pix = get_pixmap_fn(STATUS_ICON_BASE + idx - 130, (20, 20))
                if pix:
                    lbl = QLabel()
                    lbl.setPixmap(pix)
                    row.addWidget(lbl)
            cb = QCheckBox(f"{idx}. {status_names[idx]}")
            cb.setChecked(bool(cur_mask & (1 << i)))
            self.checkboxes.append((i, cb))
            row.addWidget(cb)
            row.addStretch()
            cl.addLayout(row)
        cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: self._set_all_checked(True)))
        bl.addWidget(QPushButton("全清", clicked=lambda: self._set_all_checked(False)))
        bl.addStretch()
        bl.addWidget(QPushButton("✅ 确定", clicked=self._ok))
        bl.addWidget(QPushButton("❌ 取消", clicked=self.reject))
        layout.addLayout(bl)

    def _set_all_checked(self, state):
        for _, cb in self.checkboxes:
            cb.setChecked(state)

    def _ok(self):
        m = 0
        for i, cb in self.checkboxes:
            if cb.isChecked():
                m |= (1 << i)
        if m >= 0x8000:
            m -= 0x10000
        self.selected_mask = m
        self.accept()

    def get_mask(self):
        """兼容旧调用: 返回与 selected_mask 相同的带符号 int16"""
        return self.selected_mask


# ═══════════════════════════════════════════════════════════════
# 物品选择器 — 统一完整表格 + 页面/权限/非空筛选
# ═══════════════════════════════════════════════════════════════

# 内置默认使用权限 (equip_type_labels.json 缺失时回退)
_USE_RIGHT_DEFAULTS = {
    0: [(1, "战斗"), (2, "非战斗")],
    1: [(1, "战斗"), (2, "非战斗"), (4, "主角限定")],
    2: [(1, "刀"), (2, "剑"), (4, "枪"), (8, "矛"),
        (16, "弓"), (32, "大刀"), (64, "戟"), (128, "锤")],
    3: [(1, "衣袍"), (2, "铠甲")],
    4: [(0, "通用")],
    5: [(0, "通用")],
}

_PAGE_NAMES = {0: "药品", 1: "道具", 2: "武器", 3: "防具", 4: "饰品", 5: "特殊"}
_PAGE_VALUES = [f"{k}-{v}" for k, v in sorted(_PAGE_NAMES.items())]


def _load_equip_type_options():
    """从 configs/equip_type_labels.json 加载使用权限选项。

    支持开发环境和打包环境的路径解析。
    返回 dict[int, list[(int, str)]]，加载失败时返回内置默认。
    """
    opts = {p: list(v) for p, v in _USE_RIGHT_DEFAULTS.items()}
    path = resolve_config_path('equip_type_labels.json')
    if not path:
        return opts
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return opts
    try:
        for page_key, items in data.items():
            try:
                page = int(page_key)
            except (ValueError, TypeError):
                continue
            pairs = [(int(it[0]), str(it[1])) for it in items]
            if pairs:
                opts[page] = pairs
    except (TypeError, IndexError, ValueError):
        pass
    return opts


def _use_right_label(val, page, opts=None):
    """根据页面号解析使用权限为可读文本"""
    if opts is None:
        opts = _USE_RIGHT_DEFAULTS.get(page, [])
    sel = [name for bit, name in opts if bit == 0 or (val & bit)]
    return ", ".join(sel) if sel else "(无)"


class ItemPickerDialog(QDialog):
    """统一物品选择对话框 — 完整物品列表表格 + 页面号/权限/仅非空 筛选。

    表格列与 item_editor 完全一致: 图标 | # | ID | 页面 | 物品名称 | 权限 | 价格

    支持两种数据模式:

    **完整模式** — *items* 为 ``list[dict]``, 每条记录::

        {
            'index': int,        # 数组索引 (0-599)
            'item_id': int,      # 物品 ID
            'tab_code': int,     # 页面号 (0-5)
            'name': str,         # 显示名称
            'equip_type': int,   # 使用权限位掩码 (可选, 默认 0)
            'icon': int,         # 图标精灵索引 (可选, 默认 0)
            'price': int,        # 价格 (可选, 默认 0)
        }

    **简单模式** — *items* 为 ``dict[int, str]`` (键→名称), 仅显示两列。

    Args:
        parent: 父窗口
        items: 物品数据 (完整模式 list[dict] 或简单模式 dict)
        use_right_options: ``dict[int, list[(int,str)]]`` 权限选项;
            为 None 时自动从 equip_type_labels.json 加载 (回退内置默认)
        icon_pixmap_fn: 图标回调 ``fn(icon_val, size) -> QPixmap|None``
        current_value: 当前值 (用于回显选中行)
        title: 窗口标题
        clear_text: 清空按钮文本; None 表示不显示清空按钮
        return_key: 完整模式下 ``selected_value`` 返回的字段名
            (默认 ``'item_id'``; 可选 ``'index'``)
    """

    # 完整模式固定列宽; 页面(3) 与权限(5) 按内容自适应
    def __init__(self, parent, items, *, use_right_options=None,
                 icon_pixmap_fn=None, current_value=None,
                 title="选择物品", clear_text=None,
                 return_key='item_id'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 560)
        self.setMinimumSize(760, 360)
        self.selected_value = None
        self._icon_pixmap_fn = icon_pixmap_fn
        self._clear_text = clear_text
        self._return_key = return_key
        self._guard_right_reset = False

        # ── 权限选项 ──
        if use_right_options is not None:
            self._use_right_options = {p: list(opts) for p, opts in use_right_options.items()}
        else:
            self._use_right_options = _load_equip_type_options()

        # ── 数据模式判定 ──
        if isinstance(items, dict):
            self._simple_mode = True
            self._lookup = items
            self._records = []
        else:
            self._simple_mode = False
            self._lookup = {}
            self._records = list(items)

        self._build_ui()
        self._refresh_table()

        # 回显当前值
        if current_value is not None and self._table.rowCount() > 0:
            # 简单模式: col0=ID; 完整模式: return_key='item_id'→col2=item_id, 'index'→col1=#
            if self._simple_mode:
                match_col = 0
            else:
                match_col = 2 if self._return_key == 'item_id' else 1
            for row in range(self._table.rowCount()):
                item = self._table.item(row, match_col)
                if item:
                    try:
                        if int(item.text().lstrip('#')) == current_value:
                            self._table.selectRow(row)
                            break
                    except (ValueError, AttributeError):
                        pass

    # ── UI 构建 ──
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 搜索栏
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按名称/ID/索引搜索...")
        self._search.textChanged.connect(self._refresh_table)
        sf.addWidget(self._search)
        sf.addWidget(QPushButton("清除", clicked=self._search.clear))
        layout.addLayout(sf)

        # 筛选栏
        ff = QHBoxLayout()
        if not self._simple_mode:
            ff.addWidget(QLabel("页面号:"))
            self._page_cb = EditorComboBox()
            self._page_cb.addItems(["全部页面"] + _PAGE_VALUES)
            self._page_cb.currentIndexChanged.connect(self._on_page_changed)
            ff.addWidget(self._page_cb)
            ff.addSpacing(6)
            ff.addWidget(QLabel("权限:"))
            self._perm_cb = EditorComboBox()
            self._perm_cb.addItems(["全部权限"])
            self._perm_cb.currentIndexChanged.connect(self._on_perm_changed)
            ff.addWidget(self._perm_cb)
            ff.addSpacing(6)
            self._nonempty_cb = QCheckBox("仅非空")
            self._nonempty_cb.setChecked(True)
            self._nonempty_cb.stateChanged.connect(self._refresh_table)
            ff.addWidget(self._nonempty_cb)
        ff.addStretch()
        layout.addLayout(ff)

        # 表格
        if self._simple_mode:
            self._table = AdaptiveTableWidget(
                0, 2,
                stretch_columns={1},
                minimum_widths=[80, 90],
            )
            self._table.setHorizontalHeaderLabels(["ID", "名称"])
        else:
            self._table = AdaptiveTableWidget(
                0, 7,
                stretch_columns={4},
                minimum_widths=[56, 56, 80, 50, 96, 50, 80],
                row_height=44,
            )
            self._table.setHorizontalHeaderLabels(
                ['图标', '#', 'ID', '页面', '物品名称', '权限', '价格'])
            self._table.setIconSize(QSize(36, 36))
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._accept)
        layout.addWidget(self._table, 1)

        # 底部按钮
        bl = QHBoxLayout()
        if self._clear_text is not None:
            btn_clr = QPushButton(self._clear_text)
            btn_clr.clicked.connect(self._do_clear)
            bl.addWidget(btn_clr)
        bl.addStretch()
        bl.addWidget(QPushButton("❌ 取消", clicked=self.reject))
        btn_ok = QPushButton("✅ 确定")
        btn_ok.clicked.connect(self._accept)
        bl.addWidget(btn_ok)
        layout.addLayout(bl)

    # ── 权限联动 ──
    def _update_perm_options(self, page_text):
        """根据页面筛选值动态填充权限下拉框选项 (与 item_editor 一致)"""
        if page_text.startswith("全部"):
            seen = set()
            all_opts = []
            for page in sorted(self._use_right_options):
                for bit, name in self._use_right_options[page]:
                    key = (bit, name)
                    if key not in seen:
                        seen.add(key)
                        all_opts.append(f"{bit}-{name}")
        else:
            page = int(page_text.split('-')[0])
            opts = self._use_right_options.get(page, [])
            all_opts = [f"{bit}-{name}" for bit, name in opts]
        new_vals = ["全部权限"] + all_opts
        current_vals = [self._perm_cb.itemText(i) for i in range(self._perm_cb.count())]
        if new_vals != current_vals:
            self._guard_right_reset = True
            self._perm_cb.clear()
            self._perm_cb.addItems(new_vals)
            self._perm_cb.setCurrentIndex(0)  # 重置为"全部权限"
            self._guard_right_reset = False

    def _on_page_changed(self):
        if self._guard_right_reset:
            return
        self._update_perm_options(self._page_cb.currentText())
        self._refresh_table()

    def _on_perm_changed(self):
        if self._guard_right_reset:
            return
        self._refresh_table()

    # ── 表格刷新 ──
    def _refresh_table(self):
        self._table.setRowCount(0)

        if self._simple_mode:
            self._refresh_simple()
            return

        q = self._search.text().strip().lower()
        pg = self._page_cb.currentText()
        frg = self._perm_cb.currentText()
        ne = self._nonempty_cb.isChecked()

        def _is_match(rec):
            name = rec.get('name', '')
            # 仅非空筛选
            if ne and (not name or name.startswith("Item#") or name.startswith("(空") or name == "0"):
                return False
            # 页面筛选
            if pg and not pg.startswith("全部"):
                if rec.get('tab_code', 0) != int(pg.split('-')[0]):
                    return False
            # 权限筛选 (与 item_editor._apply_filter 一致)
            if frg and not frg.startswith("全部"):
                bit = int(frg.split('-')[0])
                eq = rec.get('equip_type', 0)
                if bit == 0:
                    if eq != 0:
                        return False
                elif (eq & bit) == 0:
                    return False
            # 搜索过滤
            if q and q not in f"{rec.get('index', 0)} {rec.get('item_id', 0)} {rec.get('tab_code', 0)} {name}".lower():
                return False
            return True

        for rec in filter(_is_match, self._records):
            name = rec.get('name', '')
            item_id = rec.get('item_id', 0)
            tab = rec.get('tab_code', 0)
            equip_type = rec.get('equip_type', 0)
            idx = rec.get('index', 0)

            # 插入行
            row = self._table.rowCount()
            self._table.insertRow(row)

            # 列顺序: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
            icon_item = QTableWidgetItem()
            if self._icon_pixmap_fn:
                pix = self._icon_pixmap_fn(rec.get('icon', 0), (36, 36))
                if pix:
                    icon_item.setIcon(QIcon(pix))
            self._table.setItem(row, 0, icon_item)
            self._table.setItem(row, 1, QTableWidgetItem(str(idx)))
            self._table.setItem(row, 2, QTableWidgetItem(str(item_id)))
            self._table.setItem(row, 3, QTableWidgetItem(_PAGE_NAMES.get(tab, '?')))
            self._table.setItem(row, 4, QTableWidgetItem(name))
            rt = _use_right_label(equip_type, tab,
                                  self._use_right_options.get(tab))
            self._table.setItem(row, 5, QTableWidgetItem(rt))
            self._table.setItem(row, 6, QTableWidgetItem(str(rec.get('price', 0))))

    def _refresh_simple(self):
        """简单模式: 仅两列 (ID + 名称)"""
        q = self._search.text().strip().lower()
        for k, v in sorted(self._lookup.items(), key=lambda x: x[0]):
            if q and q not in f"{k} {v}".lower():
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(k)))
            self._table.setItem(row, 1, QTableWidgetItem(v))

    # ── 确定 / 清空 ──
    def _accept(self):
        sel = self._table.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        if self._simple_mode:
            self.selected_value = int(self._table.item(row, 0).text())
        else:
            self.selected_value = int(
                self._table.item(row, 2 if self._return_key == 'item_id' else 1).text())
        self.accept()

    def _do_clear(self):
        """清空: 根据模式返回对应的清空值"""
        if self._simple_mode:
            # 简单模式: 由调用者决定清空语义 (idx→-1, id→0)
            self.selected_value = -1 if self._clear_text and '-1' in self._clear_text else 0
        else:
            self.selected_value = -1 if self._return_key == 'index' else 0
        self.accept()


# ═══════════════════════════════════════════════════════════════
# 位标志多选器 (item/warpc 旗标与使用权限弹窗共用)
# ═══════════════════════════════════════════════════════════════

class BitmaskPickerDialog(QDialog):
    """位标志多选对话框 — 合并 item/warpc 四份同构实现 (旗标 ×2 + 使用权限 ×2)。

    bits 每项 ``(bit, name)`` 或 ``(bit, name, desc)``:
      bit: use_bit_shift=True 时为位序号, 掩码 = 1<<bit (warpc 旗标/item extra_flags);
           否则 bit 直接即掩码值 (item combat_flag/双方 use_right)
      desc: 非空时内联为 "name (desc)" 复选框文案; 2 元组或空 desc 仅显示 name
    manual=True 时附加手动输入框 — MOD 可能使用超出内置预定义的位掩码,
    允许直接输入任意数值; 勾选框变动实时同步到输入框。

    结果双轨兼容: ``selected_mask`` (确定后为 int, 取消为 None) 与 ``get_value()``。
    """

    def __init__(self, parent, title, bits, current_val, use_bit_shift=False, manual=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        n = max(len(bits), 2)
        self.resize(*(360, 90 + n * 32) if manual else (420, 110 + n * 34))
        self.selected_mask = None
        self.manual = manual
        layout = QVBoxLayout(self)
        if manual:
            manual_row = QHBoxLayout()
            manual_row.addWidget(QLabel("当前值:"))
            self.manual_edit = QLineEdit(str(current_val & 0xFFFF))
            self.manual_edit.setPlaceholderText("可直接输入任意数值 (含 MOD 扩展位)")
            manual_row.addWidget(self.manual_edit, 1)
            layout.addLayout(manual_row)
        self.checkboxes = []
        for entry in bits:
            bit, name = entry[0], entry[1]
            desc = entry[2] if len(entry) > 2 else ""
            mask = (1 << bit) if use_bit_shift else bit
            cb = QCheckBox(f"{name} ({desc})" if desc else name)
            cb.setChecked(bool(current_val & mask))
            if manual:
                cb.toggled.connect(self._sync_from_boxes)
            self.checkboxes.append((mask, cb))
            layout.addWidget(cb)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._ok)
        bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _sync_from_boxes(self):
        """勾选框变动时同步到手动输入框"""
        self.manual_edit.setText(str(self._mask_from_boxes()))

    def _mask_from_boxes(self):
        m = 0
        for mask, cb in self.checkboxes:
            if cb.isChecked():
                m |= mask
        return m

    def _ok(self):
        if self.manual:
            try:
                m = int(self.manual_edit.text().strip() or 0)
            except ValueError:
                m = self._mask_from_boxes()
            m &= 0xFFFF                      # 16 位字段
        else:
            m = self._mask_from_boxes()
        self.selected_mask = m if m < 0x8000 else m - 0x10000  # 转有符号
        self.accept()

    def get_value(self):
        """返回确定时计算的位掩码 (取消时为 None)"""
        return self.selected_mask


# ═══════════════════════════════════════════════════════════════
# WarPC 角色选择器
# ═══════════════════════════════════════════════════════════════

def _pil_to_pixmap(img, size=(32, 32)):
    """将 PIL.Image 转为 QPixmap。img 为 None 时返回 None。"""
    if img is None:
        return None
    img = img.resize(size, 1)  # Image.NEAREST = 1
    img = img.convert('RGBA')
    data = img.tobytes('raw', 'RGBA')
    qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


class WarpcPickerDialog(QDialog):
    """WarPC 角色选择对话框 — 搜索过滤表格，支持单选/多选。

    Args:
        parent: 父窗口
        war_pc_records: list[dict]，每条 {'index': i, 'fields': [...]}（fields[0]=name_id, fields[1]=portrait）
        tkt_names: dict[int, str]，{tkt_id: 角色名称}
        fa_sprites: list[PIL.Image|None]，Fa.JVG 头像精灵列表（可为空列表）
        multi_select: True=多选模式，False=单选模式
        current_indices: 当前已选中的 WarPC 索引列表（用于回显选中状态）
        excluded_indices: 排除的索引列表（多选模式中防止重复选择）
    """

    def __init__(self, parent, war_pc_records=None, tkt_names=None,
                 fa_sprites=None, multi_select=False,
                 current_indices=None, excluded_indices=None):
        super().__init__(parent)
        self.setWindowTitle("选择 WarPC 角色" + (" (多选)" if multi_select else ""))
        self.resize(520, 560)

        self._records = war_pc_records or []
        self._tkt = tkt_names or {}
        self._fa_sprites = fa_sprites or []
        self._multi = multi_select
        self._excluded = set(excluded_indices or [])
        self._selected_indices = list(current_indices or [])
        self._pixmap_cache = {}

        layout = QVBoxLayout(self)
        # 搜索框
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("🔍"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按名称或索引搜索...")
        self._search.textChanged.connect(self._populate)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)

        # 表格
        self._table = AdaptiveTableWidget(
            0, 3,
            stretch_columns={2},
            minimum_widths=[40, 40, 80],
            row_height=44,
        )
        self._table.setHorizontalHeaderLabels(["头像", "索引", "名称"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if multi_select:
            self._table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        else:
            self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        # 已选栏
        self._selected_label = QLabel("")
        self._selected_label.setWordWrap(True)
        self._selected_label.setObjectName("WarpcSelectedLabel")
        layout.addWidget(self._selected_label)
        self._update_selected_label()

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self._populate()

    def _get_name(self, idx):
        """通过 WarPC 索引获取角色名称。"""
        if idx < 0 or idx >= len(self._records):
            return f"未知 #{idx}"
        rec = self._records[idx]
        name_id = rec['fields'][0]
        name = self._tkt.get(name_id)
        if name:
            return name
        return f"未知 #{idx}"

    def _get_pixmap(self, idx, size=(32, 32)):
        """获取 WarPC 索引对应的头像 QPixmap。"""
        cache_key = (idx, size)
        if cache_key in self._pixmap_cache:
            return self._pixmap_cache[cache_key]
        if not self._fa_sprites or idx < 0 or idx >= len(self._records):
            return None
        rec = self._records[idx]
        portrait = rec['fields'][1]
        sprite_idx = portrait * 2  # 大幅图
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites):
            return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None:
            return None
        pix = _pil_to_pixmap(sprite, size)
        self._pixmap_cache[cache_key] = pix
        return pix

    def _populate(self, filter_text=""):
        """填充表格。"""
        self._table.setRowCount(0)
        ft = filter_text.strip().lower()
        for i, rec in enumerate(self._records):
            name = self._get_name(i)
            # 搜索过滤
            if ft and ft not in name.lower() and ft != str(i):
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)

            # 头像列
            lbl = QLabel()
            pix = self._get_pixmap(i)
            if pix:
                lbl.setPixmap(pix)
            else:
                lbl.setText("👤")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 0, lbl)

            # 索引列
            idx_item = QTableWidgetItem(f"#{i}")
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            idx_item.setData(Qt.ItemDataRole.UserRole, i)
            self._table.setItem(row, 1, idx_item)

            # 名称列
            name_item = QTableWidgetItem(name)
            # 已排除的行灰色显示
            if i in self._excluded:
                name_item.setForeground(Qt.GlobalColor.gray)
                idx_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 2, name_item)

            # 回显选中状态
            if i in self._selected_indices:
                self._table.selectRow(row)

    def _on_double_click(self):
        """双击行: 单选模式直接确定。"""
        if not self._multi:
            self._on_accept()

    def _on_accept(self):
        """确定: 收集选中的索引。"""
        selected_rows = self._table.selectionModel().selectedRows()
        indices = []
        for idx in selected_rows:
            row = idx.row()
            item = self._table.item(row, 1)
            if item:
                warpc_idx = item.data(Qt.ItemDataRole.UserRole)
                if warpc_idx not in self._excluded:
                    indices.append(warpc_idx)
        self._selected_indices = indices
        self.accept()

    def _update_selected_label(self):
        """更新已选栏显示。"""
        if not self._selected_indices:
            self._selected_label.setText("")
            self._selected_label.setVisible(False)
            return
        self._selected_label.setVisible(True)
        names = [f"{self._get_name(i)}(#{i})" for i in self._selected_indices]
        self._selected_label.setText(f"已选 ({len(names)}): {', '.join(names)}")

    @property
    def selected_indices(self):
        """返回选中的 WarPC 索引列表。单选时列表长度为 1。"""
        return self._selected_indices

    @property
    def selected_index(self):
        """单选模式: 返回选中的 WarPC 索引，无选中时返回 None。"""
        return self._selected_indices[0] if self._selected_indices else None


# ═══════════════════════════════════════════════════════════════
# 成长数据表 (阶段 4 合并: warpc 编辑器 / tks_book 查看器共用;
# 逆向来源: sub_410674 / sub_43066C / sub_4302D8)
# ═══════════════════════════════════════════════════════════════

class GrowthTableDialog(QDialog):
    """角色逐级成长数据表 — 基于反编译公式 (sub_410674/sub_43066C)

    成长公式 (每升一级):
      选择成长率除数:
        level < 21       → growth_early  (field[264], byte 528)
        21 ≤ level < 41  → growth_mid    (field[265], byte 530)
        level ≥ 41       → growth_late   (field[266], byte 532)
      stat += stat // divisor + 1   (hp/mp/atk/def/hit/eva)
      spd  += 1                     (固定)
      hp = min(hp, 9999);  mp = min(mp, 9999)

    等级上限: 60 (sub_43066C L13: if level < 60)

    敌方属性加成 (sub_4302D8:53-62, enemy_grp/enemy_power):
      HP  += grp × HP          (×(grp+1), cap 20000)
      MP  += grp × MP / 4      (cap 20000)
      ATK += grp × ATK / 8
      DEF += grp × DEF / 8
      HIT += grp × HIT / 12
      EVA += grp × EVA / 12
      SPD += grp × level / 10
    """

    STAT_CAP_HPMP = 9999
    STAT_CAP_HPMP_ENEMY = 20000
    MAX_LEVEL = 60

    # WarPC int16 字段索引 (byte_offset // 2)
    _IDX_HP   = 7    # hp_base
    _IDX_MP   = 9    # mp_base
    _IDX_ATK  = 11   # atk_base
    _IDX_DEF  = 13   # def_base
    _IDX_HIT  = 15   # hit_base
    _IDX_EVA  = 17   # eva_base
    _IDX_SPD  = 19   # spd_base (field[38//2])
    _IDX_GE   = 264  # growth_early
    _IDX_GM   = 265  # growth_mid
    _IDX_GL   = 266  # growth_late

    STAT_LABELS = ["HP", "MP", "攻击", "防御", "命中", "闪避", "速度"]

    def __init__(self, parent, rec, char_name, grp=0, theme_id="gpt-dark"):
        super().__init__(parent)
        self.setWindowTitle(f"成长数据表 — {char_name}")
        self.resize(1100, 800)
        self._rec = rec
        self._char_name = char_name
        self._f = rec['fields']
        self._grp = grp

        # 应用主题样式表
        apply_theme_to_window(self, theme_id, persist=False)

        # 主题颜色 (与 editor_themes 色板对齐)
        # 注: 当前等级行不再用白色文字+蓝底高亮 — QSS 的 ::item background-color
        # 会覆盖 item.setBackground(), 导致蓝底丢失、白字残留在浅色背景上不可读。
        # 改为仅用粗体字标记当前等级行。
        pal = business_colors("growth", theme_id)
        self._CLR_DELTA = QColor(pal["delta"])   # Δ增量
        self._CLR_GRP = QColor(pal["grp"])       # grp 最终属性

        # 读取当前数据
        self._cur_level = max(1, self._f[2])
        self._cur_stats = [
            self._f[self._IDX_HP], self._f[self._IDX_MP],
            self._f[self._IDX_ATK], self._f[self._IDX_DEF],
            self._f[self._IDX_HIT], self._f[self._IDX_EVA],
            self._f[self._IDX_SPD],
        ]
        self._ge = self._f[self._IDX_GE]
        self._gm = self._f[self._IDX_GM]
        self._gl = self._f[self._IDX_GL]

        # 估算 1 级基础值 (二分搜索)
        self._base_stats = [self._estimate_base(cur, self._cur_level)
                            for cur in self._cur_stats]

        # 计算完整成长表 (1-60级)
        self._table_data = self._build_table()
        self._build_ui()
        self._update_grp_summary()

    def showEvent(self, event):
        super().showEvent(event)
        apply_titlebar_theme(self, self._theme_id)

    # ── 成长模拟 (对应 sub_410674 循环体) ──

    def _get_divisor(self, level):
        """获取指定等级段的成长率除数"""
        if level >= 41: return self._gl
        if level >= 21: return self._gm
        return self._ge

    def _simulate_stat(self, base, from_level, to_level):
        """模拟单项属性从 from_level 升至 to_level (sub_410674 循环体)"""
        val = base
        for lvl in range(from_level, to_level):
            d = self._get_divisor(lvl)
            if d > 0:
                val += val // d + 1
            else:
                val += 1
        return val

    def _simulate_spd(self, base_spd, from_level, to_level):
        """速度: 每级固定 +1 (sub_410674 L33: ++a1[19])"""
        return base_spd + (to_level - from_level)

    def _estimate_base(self, current_stat, current_level):
        """二分搜索估算 1 级时的属性基础值 (取最接近当前值的基点)"""
        if current_level <= 1:
            return current_stat
        # 对速度特殊处理 (固定+1/级)
        # 注意: 此函数不区分 stat 类型, 速度单独在 _build_table 处理
        lo, hi = 1, max(current_stat, 1)
        while lo < hi:
            mid = (lo + hi) // 2
            sim = self._simulate_stat(mid, 1, current_level)
            if sim < current_stat:
                lo = mid + 1
            else:
                hi = mid
        # lo = 最小 sim >= current 的 base; 检查 lo-1 是否更接近
        if lo > 1:
            sim_lo  = self._simulate_stat(lo, 1, current_level)
            sim_lo1 = self._simulate_stat(lo - 1, 1, current_level)
            if abs(sim_lo1 - current_stat) <= abs(sim_lo - current_stat):
                return lo - 1
        return lo

    def _build_table(self):
        """构建 1 至 MAX_LEVEL 级完整数据表"""
        data = []
        # 速度基础: spd_base 是当前的速度值 (含 +1/级), 1级基础 = cur - (level-1)
        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base = list(self._base_stats[:6]) + [spd_base]

        prev = list(base)
        for lvl in range(1, self.MAX_LEVEL + 1):
            if lvl == 1:
                stats = list(base)
            else:
                d = self._get_divisor(lvl - 1)
                stats = []
                for i in range(6):
                    v = prev[i]
                    stats.append(v + (v // d + 1) if d > 0 else v + 1)
                stats.append(prev[6] + 1)  # spd 固定 +1

            # HP/MP 上限 cap (sub_410674 L35-38 / sub_43066C L37-40)
            capped = list(stats)
            capped[0] = min(capped[0], self.STAT_CAP_HPMP)
            capped[1] = min(capped[1], self.STAT_CAP_HPMP)

            deltas = [capped[i] - prev[i] for i in range(7)] if lvl > 1 else [0] * 7
            divisor = self._get_divisor(lvl)

            data.append({
                'level': lvl, 'divisor': divisor, 'stats': capped,
                'deltas': deltas, 'is_current': (lvl == self._cur_level),
            })
            prev = capped
        return data

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 顶部: 公式说明 + 1级基础值
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.setSpacing(2)
        info_layout.addWidget(QLabel(
            f"<b>{self._char_name}</b>  (编号 #{self._rec['index']},  "
            f"当前等级 {self._cur_level})"))
        info_layout.addWidget(QLabel(
            f"成长率: 初期={self._ge} (Lv1-20) | "
            f"中期={self._gm} (Lv21-40) | "
            f"后期={self._gl} (Lv41-60)"))
        info_layout.addWidget(QLabel(
            f"公式: stat += stat // divisor + 1 "
            f"(来源 sub_410674/sub_43066C) | "
            f"速度: 每级固定+1 | HP/MP上限={self.STAT_CAP_HPMP}"))

        # 速度基础: 固定+1/级, 1级值 = 当前值 - (等级-1)
        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base_parts = [f"{l}={b}" for l, b in zip(self.STAT_LABELS[:6], self._base_stats[:6])]
        base_parts.append(f"速度={spd_base} (固定+1/级)")
        base_str = "  |  ".join(base_parts)
        base_lbl = QLabel(f"<b>估算 1 级基础值</b>: {base_str}")
        base_lbl.setWordWrap(True)
        info_layout.addWidget(base_lbl)
        layout.addWidget(info_frame)

        # ── grp 加成控制行 ──
        grp_frame = QFrame()
        grp_frame.setObjectName("DockBody")
        grp_row = QHBoxLayout(grp_frame)
        grp_row.setContentsMargins(8, 4, 8, 4)
        grp_row.addWidget(QLabel("属性加成倍率 (grp):"))
        self._grp_spin = QSpinBox()
        self._grp_spin.setRange(0, 10)
        self._grp_spin.setValue(self._grp)
        self._grp_spin.setToolTip(
            "敌方属性加成倍率 (sub_4302D8:53-62)\n"
            "0=普通士兵  1+=将领/Boss\n"
            "HP += grp×HP  MP += grp×MP/4\n"
            "ATK/DEF += grp×stat/8  HIT/EVA += grp×stat/12\n"
            "SPD += grp×level/10")
        self._grp_spin.valueChanged.connect(self._update_grp_summary)
        grp_row.addWidget(self._grp_spin)
        grp_row.addSpacing(20)
        self._grp_formula_lbl = QLabel(
            "<i>grp=0: 仅显示等级成长数据; 设为 1+ 可查看敌方加成后的最终属性</i>")
        self._grp_formula_lbl.setWordWrap(True)
        grp_row.addWidget(self._grp_formula_lbl, 1)
        layout.addWidget(grp_frame)

        # 表格 (16 基础列 + 7 grp 最终列)
        self._BASE_COLS = ["等级", "成长率", "HP", "Δ", "MP", "Δ",
                            "攻击", "Δ", "防御", "Δ", "命中", "Δ",
                            "闪避", "Δ", "速度", "Δ"]
        self._GRP_COLS = ["HP★", "MP★", "攻击★", "防御★",
                           "命中★", "闪避★", "速度★"]
        all_cols = self._BASE_COLS + self._GRP_COLS
        self._growth_table = AdaptiveTableWidget(
            len(self._table_data), len(all_cols),
            stretch_columns=set(range(len(all_cols))),
            minimum_widths=[45] + [52] * 15 + [58] * 7,
        )
        self._growth_table.setHorizontalHeaderLabels(all_cols)
        self._growth_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._growth_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._growth_table.verticalHeader().setVisible(False)
        self._growth_table.setAlternatingRowColors(True)
        # 修复深色模式下交替行背景色 (QSS 不覆盖 palette 的 AlternateBase)
        self._growth_table.setProperty("class", "GrowthTable")
        self._growth_table.setFont(QFont("Consolas", 9))
        # 初始隐藏 grp 列 (setColumnHidden 会触发自适应重排)
        for ci in range(16, 23):
            self._growth_table.setColumnHidden(ci, True)
        self._populate_table()
        layout.addWidget(self._growth_table, 1)

        # 底部按钮
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("关闭", clicked=self.close))
        layout.addLayout(bl)

    def _populate_table(self):
        font_bold = QFont("Consolas", 9, QFont.Bold)
        for row, d in enumerate(self._table_data):
            is_cur = d['is_current']
            items = [str(d['level']), str(d['divisor'])]
            for si in range(7):
                items.append(str(d['stats'][si]))
                delta = d['deltas'][si]
                items.append(f"+{delta}" if delta > 0 else str(delta))
            for ci, txt in enumerate(items):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                if is_cur:
                    item.setFont(font_bold)
                if ci in (3, 5, 7, 9, 11, 13, 15) and d['level'] > 1:
                    item.setForeground(self._CLR_DELTA)
                self._growth_table.setItem(row, ci, item)
        # 滚动到当前等级
        for row, d in enumerate(self._table_data):
            if d['is_current']:
                self._growth_table.scrollToItem(
                    self._growth_table.item(row, 0))
                break

    # ── grp 加成计算 (sub_4302D8:53-62) ──

    def _update_grp_summary(self):
        """根据 grp 值切换成长表中的 grp 列并填充各级最终属性"""
        grp = self._grp_spin.value()

        # 显示/隐藏 grp 列 (col 16-22)
        for ci in range(16, 23):
            self._growth_table.setColumnHidden(ci, grp == 0)

        # 更新公式标签
        if grp > 0:
            cap = self.STAT_CAP_HPMP_ENEMY
            self._grp_formula_lbl.setText(
                f"<b>grp={grp}</b>: "
                f"★列 = 成长值 + grp加成  "
                f"HP×{grp+1}(cap {cap})  MP+{grp}×MP/4  "
                f"ATK/DEF+{grp}/8  HIT/EVA+{grp}/12  SPD+{grp}×Lv/10")
        else:
            self._grp_formula_lbl.setText(
                "<i>grp=0: 仅显示等级成长数据; "
                "设为 1+ 可查看敌方加成后的最终属性</i>")
            return  # grp=0 时不需要填充

        # 填充各级 grp 最终属性 (每行用该级自己的成长值 + 该级自己的 level)
        grp_divs = [1, 4, 8, 8, 12, 12, 0]
        cap = self.STAT_CAP_HPMP_ENEMY
        font_bold = QFont("Consolas", 9, QFont.Bold)

        for row, d in enumerate(self._table_data):
            lv = d['level']
            base = d['stats']
            for si in range(7):
                bonus = (grp * base[si] // grp_divs[si]
                         if grp_divs[si] > 0
                         else grp * lv // 10)
                final = base[si] + bonus
                if si < 2:
                    final = min(final, cap)
                item = QTableWidgetItem(str(final))
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(self._CLR_GRP)
                item.setFont(font_bold)
                self._growth_table.setItem(row, 16 + si, item)
