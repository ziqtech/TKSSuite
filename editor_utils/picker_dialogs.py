"""
通用选择器对话框 — 供所有编辑器统一使用
包含: TktPickerDialog (TKT 文本选择器)
      StatusPickerDialog (状态位掩码多选器)
      WarpcPickerDialog (WarPC 角色选择器)
      ItemPickerDialog  (物品选择器 — 完整表格 + 页面/权限/非空筛选)
"""
import json

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from editor_utils.ui_helpers import resolve_config_path, NoWheelComboBox


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

    表格列与 item_editor_v2 完全一致: 图标 | # | ID | 页面 | 物品名称 | 权限 | 价格

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

    # 完整模式表格列宽: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
    _COLUMN_WIDTHS = {0: 50, 1: 40, 2: 50, 3: 50, 5: 100, 6: 60}

    def __init__(self, parent, items, *, use_right_options=None,
                 icon_pixmap_fn=None, current_value=None,
                 title="选择物品", clear_text=None,
                 return_key='item_id'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 560)
        self.setMinimumSize(480, 360)
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
            self._page_cb = NoWheelComboBox()
            self._page_cb.addItems(["全部页面"] + _PAGE_VALUES)
            self._page_cb.currentIndexChanged.connect(self._on_page_changed)
            ff.addWidget(self._page_cb)
            ff.addSpacing(6)
            ff.addWidget(QLabel("权限:"))
            self._perm_cb = NoWheelComboBox()
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
            self._table = QTableWidget(0, 2)
            self._table.setHorizontalHeaderLabels(["ID", "名称"])
            self._table.setColumnWidth(0, 80)
            self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        else:
            self._table = QTableWidget(0, 7)
            self._table.setHorizontalHeaderLabels(
                ['图标', '#', 'ID', '页面', '物品名称', '权限', '价格'])
            for col, width in self._COLUMN_WIDTHS.items():
                self._table.setColumnWidth(col, width)
            self._table.verticalHeader().setDefaultSectionSize(44)
            self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
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
        """根据页面筛选值动态填充权限下拉框选项 (与 item_editor_v2 一致)"""
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
            # 权限筛选 (与 item_editor_v2._apply_filter 一致)
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
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["头像", "索引", "名称"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 40)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
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
