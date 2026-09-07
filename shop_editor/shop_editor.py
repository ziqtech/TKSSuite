#!/usr/bin/env python3
"""
TKShop.dat 可视化编辑器 (PySide6 重构版)

逆向依据:
  - sub_45343C: DAT 文件统一加载 (LZSS 解压, 8字节/条, 240条, 基址 unk_9508A0)
  - sub_452B14: LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_4244CC: 商店过滤 (*(a1+56) 匹配 area_id, condition 判定逻辑)
  - sub_4246D8: 商品信息读取 (word_77CBCC[32*item_ref] 取 TKItem ID)
  - sub_40EBD4 case 50: Shop(a1,a2,a3) 脚本指令, a3=area_id → sub_40D804 → sub_4233C4
  - sub_4233C4: a1[28]=a3, a2 作为缓存键

TKShop.dat 格式 (每条 8 字节, 共 240 条):
  [0:2] int16 area_id   — 商店库存表索引 (0=药店,1=道具,2=武器防具,3=杂货,4=饰品,9=无)
  [2:4] int16 item_ref  — TKItem 数组下标 (0-599)
  [4:6] int16 condition — 出现条件: 1=随机, >1=等级门槛, ≤0=始终
  [6]   byte  display   — 显示标志 (sub_4244CC: ==1 表示已显示/可购买)
  [7]   byte  reserved  — 保留

LZSS 文件头 (sub_45343C 读取):
  [0:4] uint32 decompressed_size  (1920 = 8×240)
  [4:8] uint32 block_size         (含下面4字节)
  [8:12] uint32 decompressed_size (重复)
  [12:] LZSS 压缩流

用法:
  python shop_editor_pyside6.py
"""

import os
import struct
import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import (
    QColor, QFont, QAction, QKeySequence, QIcon
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLabel,
    QLineEdit, QSpinBox, QRadioButton, QButtonGroup, QTextEdit,
    QFileDialog, QMessageBox, QDialog, QFrame, QAbstractItemView
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.lzss import lzss_decompress_dat, lzss_compress_dat
from editor_utils.mod_exporter import (
    RecordModSpec, export_records_mod, import_records_mod,
)
from editor_utils.picker_dialogs import ItemPickerDialog
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.ui_helpers import themed_question, update_path_labels, EditorComboBox, backup_existing_file
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput
from editor_utils.task_runner import run_background, is_running

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data):
    return lzss_decompress_dat(data)


def lzss_compress(data):
    return lzss_compress_dat(data)


# ============================================================
# TKItem 名称加载 (逆向自 sub_424A2C, sub_4067E8)
# ============================================================

def load_tkitem_with_tkt(item_dat_path, tkt_dat_path):
    """
    加载 TKItem 并关联 TKT 名称, 同时提取 equip_type / icon / price
    field[0]=item_id, field[1]=tab_code, field[4]=icon, field[5]=equip_type, field[31]=price
    返回: list[(idx, item_id, tab_code, name_id, equip_type, name, icon, price)]
    """
    with open(item_dat_path, 'rb') as f:
        raw = f.read()
    decompressed = lzss_decompress(raw)
    REC_SIZE = 64
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % REC_SIZE == 0 and (len(decompressed) == 0 or len(decompressed) % REC_SIZE != 0):
        decompressed = raw

    items_raw = []
    for i in range(min(600, len(decompressed) // REC_SIZE)):
        off = i * REC_SIZE
        item_id = struct.unpack_from('<h', decompressed, off)[0]
        tab_code = struct.unpack_from('<h', decompressed, off + 2)[0]
        name_id = struct.unpack_from('<h', decompressed, off + 4)[0]
        icon = struct.unpack_from('<h', decompressed, off + 8)[0]
        equip_type = struct.unpack_from('<h', decompressed, off + 10)[0]
        price = struct.unpack_from('<h', decompressed, off + 62)[0] if off + 64 <= len(decompressed) else 0
        items_raw.append((i, item_id, tab_code, name_id, equip_type, icon, price))

    tkt_lookup = {}
    if tkt_dat_path and os.path.exists(tkt_dat_path):
        with open(tkt_dat_path, 'rb') as f:
            raw = f.read()
        total_size = struct.unpack_from('<I', raw, 0)[0]
        count = struct.unpack_from('<I', raw, 4)[0]
        encrypted = raw[8:8 + total_size]
        decrypted = bytes([b ^ 0xFF for b in encrypted])
        id_table_size = count * 4
        offset_table_size = count * 4

        # TKT ID 0-9 是系统消息 (sub_4067E8)
        SYSTEM_IDS = set(range(0, 10))

        for i in range(count):
            eid = struct.unpack_from('<i', decrypted, i * 4)[0]
            if eid in SYSTEM_IDS:
                continue
            off = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0]
            text_base = id_table_size + offset_table_size
            abs_off = text_base + off
            if abs_off < len(decrypted):
                end = abs_off
                while end < len(decrypted) and decrypted[end] != 0:
                    end += 1
                text = decrypted[abs_off:end].replace(b'\x1e', b'\n')
                try:
                    tkt_lookup[eid] = text.decode('big5', errors='replace')
                except:
                    tkt_lookup[eid] = text.decode('gbk', errors='replace')

    result = []
    for idx, item_id, tab_code, name_id, equip_type, icon, price in items_raw:
        if name_id > 0 and name_id in tkt_lookup:
            name = tkt_lookup[name_id]
            if name and name != '0':
                name = name.split('\n')[0].strip()
            else:
                name = ""
        else:
            name = ""
        if not name or name == "0":
            name = f"Item#{item_id}" if item_id else f"(空-{idx})"
        result.append((idx, item_id, tab_code, name_id, equip_type, name, icon, price))

    return result


# ============================================================
# TKShop 数据模型 (逆向自 sub_4244CC, sub_4246D8)
# ============================================================

AREA_NAMES = {0: "药店", 1: "道具", 2: "武器防具", 3: "杂货", 4: "饰品", 9: "无"}

def area_label(area_id):
    return AREA_NAMES.get(area_id, f"未知({area_id})")

REC_SIZE = 8

def load_shop_data(filepath):
    """加载 TKShop.dat (固定 240 条, sub_45343C a3=1920)"""
    with open(filepath, 'rb') as f:
        raw = f.read()

    decompressed = lzss_decompress(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % REC_SIZE == 0 and (len(decompressed) == 0 or len(decompressed) % REC_SIZE != 0):
        decompressed = raw
    FIXED_COUNT = 240
    records = []

    for i in range(FIXED_COUNT):
        offset = i * REC_SIZE
        if offset + REC_SIZE > len(decompressed):
            break
        area_id = struct.unpack_from('<h', decompressed, offset)[0]
        item_ref = struct.unpack_from('<h', decompressed, offset + 2)[0]
        condition = struct.unpack_from('<h', decompressed, offset + 4)[0]
        display = decompressed[offset + 6]
        reserved = decompressed[offset + 7]

        records.append({
            'index': i,
            'area_id': area_id,
            'item_ref': item_ref,
            'condition': condition,
            'display': display,
            'reserved': reserved,
        })

    return records

def save_shop_data(filepath, records):
    """保存 TKShop.dat (LZSS 压缩)

    sub_45343C 调用: sub_45343C("TKShop.dat", &unk_9508A0, 1920)
    第19行检查: if (decompressed_size <= 1920) ... else ERROR
    必须恰好 240 条记录 (1920 字节), 否则游戏拒绝加载!
    """
    FIXED_COUNT = 240
    buf = bytearray(FIXED_COUNT * REC_SIZE)
    for rec in records[:FIXED_COUNT]:
        i = rec['index']
        offset = i * REC_SIZE
        struct.pack_into('<h', buf, offset, rec['area_id'])
        struct.pack_into('<h', buf, offset + 2, rec['item_ref'])
        struct.pack_into('<h', buf, offset + 4, rec['condition'])
        buf[offset + 6] = rec['display']
        buf[offset + 7] = rec.get('reserved', 0)

    compressed = lzss_compress(bytes(buf))

    # Verify round-trip
    verify = lzss_decompress(compressed)
    if len(verify) != len(buf) or verify != bytes(buf):
        raise RuntimeError("压缩回写验证失败! 数据不一致.")

    with open(filepath, 'wb') as f:
        f.write(compressed)
    return True

# tab_code → 商店区域约束 (sub_4233C4 switch + sub_4246D8 过滤)
TAB_TO_SHOP = {
    0: [0, 3],       # 消耗品 → 药店, 杂货
    1: [1, 3],       # 书籍 → 道具店, 杂货
    2: [2],          # 武器 → 武器防具
    3: [2],          # 防具 → 武器防具
    4: [4],          # 饰品 → 饰品店
    5: [],           # 特殊 → 不显示在商店
}

# ============================================================
# GUI 编辑器 (PySide6)
# ============================================================

class ShopEditorWindow(EditorMainWindow):
    EDITOR_KEY = "shop_editor"
    TKS_DIR_PROMPT = "选择 TKS 游戏目录 (包含 TKShop.dat / TKItem.dat / TKT.dat)"
    DEFAULT_SIZE = (1100, 680)
    MIN_SIZE = (950, 550)

    HELP_TEXT = (
        "TKShop.dat 可视化编辑器\n\n"
        "1. 文件 → 加载 TKS 目录: 选择包含 TKShop.dat / TKItem.dat / TKT.dat 的目录\n"
        "2. 左侧表格: 单击行查看/编辑, 支持区域过滤和关键词搜索, 点击表头可排序\n"
        "3. 右侧面板: 修改区域/物品/出现条件/显示标志, 点「应用修改」保存到内存\n"
        "4. 文件 → 保存 (Ctrl+S): 将内存中的修改写入 TKShop.dat\n"
        "5. + 新增记录: 在240条中查找空槽位复用\n"
        "6. 出现条件 (基于队伍最高幸运 LUK):\n"
        "   - 随机: 每次进入商店时随机抽选 (最多5件)\n"
        "   - 始终: 设为-100, 任意幸运值都100%出现\n"
        "   - 幸运: 出现概率 = clamp(幸运 - 条件值, 0, 100)%\n"
        "7. 物品与区域有兼容性限制 (由游戏代码决定):\n"
        "   选择物品后区域下方会显示是否兼容及建议放置的商店\n\n"
        "功能: 编辑《三国群侠传》商店数据\n\n"
        "特性:\n"
        "  · 自动关联物品数据库显示物品名称\n"
        "  · 深色/浅色主题切换")

    def _init_data(self):
        self.shop_path = None
        self.item_path = None
        self.tkt_path = None
        self.mu_path = None

        self.records = []
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.items = []
        self.item_names = {}
        self._item_icons = {}  # 数组索引 → icon 精灵值
        self._mu_sprites = []
        self._icon_pixmaps = {}
        self.filtered_indices = []

        self._dirty = False
        self._editing_idx = -1
        self.sort_col = 0
        self.sort_reverse = False

    def _after_build(self):
        self._update_path_labels()
        self._set_edit_enabled(False)

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        # ---- 菜单栏 ----
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")

        action_load = QAction("加载 TKS 目录", self)
        action_load.setShortcut(QKeySequence("Ctrl+O"))
        action_load.triggered.connect(self._load_tks_dir)
        file_menu.addAction(action_load)
        self.attach_recent_dirs_menu(file_menu)

        file_menu.addSeparator()

        action_save = QAction("保存", self)
        action_save.setShortcut(QKeySequence("Ctrl+S"))
        action_save.triggered.connect(self._save)
        file_menu.addAction(action_save)

        action_export_mod = QAction("导出为 MOD (.tksmod)", self)
        action_export_mod.triggered.connect(self._export_tksmod)
        file_menu.addAction(action_export_mod)

        action_export_mod_ref = QAction("导出为 MOD (指定参考目录)", self)
        action_export_mod_ref.triggered.connect(self._export_tksmod_with_ref)
        file_menu.addAction(action_export_mod_ref)

        file_menu.addSeparator()
        action_import_mod = QAction("导入 MOD (.tksmod)", self)
        action_import_mod.triggered.connect(self._import_tksmod)
        file_menu.addAction(action_import_mod)

        file_menu.addSeparator()
        action_exit = QAction("退出", self)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        self.add_standard_menus(menubar)

        # ---- 中心部件 ----
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # ---- 工具栏区域 ----
        toolbar_layout = QHBoxLayout()

        toolbar_layout.addWidget(QLabel("区域:"))
        self.area_filter_combo = EditorComboBox()
        self.area_filter_combo.addItem("全部")
        for k, v in AREA_NAMES.items():
            self.area_filter_combo.addItem(f"{k}-{v}", userData=k)
        self.area_filter_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar_layout.addWidget(self.area_filter_combo)

        toolbar_layout.addSpacing(10)
        toolbar_layout.addWidget(QLabel("搜索:"))
        self.search_input = SearchInput("搜索区域或物品名称")
        self.search_input.setMinimumWidth(160)
        self.search_input.textChanged.connect(self._apply_filter)
        self.search_input.returnPressed.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_input)

        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar_layout.addWidget(btn_search)

        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar_layout.addWidget(btn_clear)

        toolbar_layout.addWidget(self._make_v_sep())

        btn_add = QPushButton("新增记录")
        btn_add.clicked.connect(self._add_record)
        toolbar_layout.addWidget(btn_add)

        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar_layout.addWidget(btn_reload)

        toolbar_layout.addWidget(self._make_v_sep())

        btn_theme = QPushButton("切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar_layout.addWidget(btn_theme)

        toolbar_layout.addStretch()

        self.lbl_status = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.lbl_status.setProperty("class", "StatusHint")
        toolbar_layout.addWidget(self.lbl_status)

        main_layout.addLayout(toolbar_layout)

        # ---- 左右分栏 ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # 左侧: 表格
        self.table = AdaptiveTableWidget(
            0, 7,
            stretch_columns={5},
            minimum_widths=[50, 50, 60, 80, 70, 90, 100],
            row_height=44,
        )
        self.table.setHorizontalHeaderLabels(["图标", "索引", "区域ID", "区域名称", "物品索引", "物品名称", "出现条件"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(36, 36))

        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_click)

        splitter.addWidget(self.table)

        # 右侧: 编辑面板
        self.edit_content = QWidget()
        edit_layout = QVBoxLayout(self.edit_content)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_rec_idx = QLabel("未选中")
        font_bold = QFont()
        font_bold.setBold(True)
        font_bold.setPointSize(11)
        self.lbl_rec_idx.setFont(font_bold)
        edit_layout.addWidget(self.lbl_rec_idx)

        # Area
        edit_layout.addWidget(QLabel("区域:"))
        self.edit_area_combo = EditorComboBox()
        for k, v in sorted(AREA_NAMES.items()):
            self.edit_area_combo.addItem(v, userData=k)
        self.edit_area_combo.currentIndexChanged.connect(self._on_area_changed)
        edit_layout.addWidget(self.edit_area_combo)

        self.lbl_compat = QLabel("")
        self.lbl_compat.setWordWrap(True)
        edit_layout.addWidget(self.lbl_compat)

        # Item
        edit_layout.addWidget(QLabel("物品:"))
        item_row = QHBoxLayout()
        self.lbl_editing_item_idx = QLabel("")
        self.lbl_editing_item_idx.setFont(font_bold)
        item_row.addWidget(self.lbl_editing_item_idx)

        self.lbl_item_name = QLabel("(未选择)")
        self.lbl_item_name.setProperty("class", "PrimaryTitle")
        item_row.addWidget(self.lbl_item_name, 1)

        btn_pick_item = QPushButton("选择物品")
        btn_pick_item.clicked.connect(self._pick_item)
        item_row.addWidget(btn_pick_item)
        edit_layout.addLayout(item_row)

        edit_layout.addSpacing(10)

        # Condition
        edit_layout.addWidget(QLabel("出现条件:"))
        cond_row = QHBoxLayout()
        self.cond_group = QButtonGroup(self)

        self.radio_random = QRadioButton("随机")
        self.radio_always = QRadioButton("始终")
        self.radio_custom = QRadioButton("幸运:")
        self.cond_group.addButton(self.radio_random)
        self.cond_group.addButton(self.radio_always)
        self.cond_group.addButton(self.radio_custom)
        self.cond_group.buttonClicked.connect(self._on_cond_mode)

        cond_row.addWidget(self.radio_random)
        cond_row.addWidget(self.radio_always)
        cond_row.addWidget(self.radio_custom)

        self.spin_cond = QSpinBox()
        self.spin_cond.setRange(-999, 999)
        self.spin_cond.valueChanged.connect(self._on_cond_changed)
        cond_row.addWidget(self.spin_cond)
        cond_row.addStretch()
        edit_layout.addLayout(cond_row)

        # Probability Table
        self.txt_cond_table = QTextEdit()
        self.txt_cond_table.setReadOnly(True)
        self.txt_cond_table.setMaximumHeight(160)
        self.txt_cond_table.setProperty("class", "MonoText")
        edit_layout.addWidget(self.txt_cond_table)

        edit_layout.addStretch()

        # Action Buttons
        btn_action_row = QHBoxLayout()
        btn_apply = QPushButton("应用修改")
        btn_apply.clicked.connect(self._apply_edit)
        btn_action_row.addWidget(btn_apply, 1)

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_record)
        btn_action_row.addWidget(btn_delete)
        edit_layout.addLayout(btn_action_row)

        splitter.addWidget(self._create_dock("编辑记录", self.edit_content))
        splitter.setSizes([700, 400])

        # ---- 底部: 文件路径 ----
        path_content = QWidget()
        path_layout = QHBoxLayout(path_content)
        path_layout.setContentsMargins(4, 4, 4, 0)

        self.lbl_shop_path = QLabel("TKShop.dat: 未加载")
        self.lbl_item_path = QLabel("TKItem.dat: 未加载")
        self.lbl_tkt_path = QLabel("TKT.dat: 未加载")
        self.lbl_mu_path = QLabel("Mu.JVG: 未加载")

        path_layout.addWidget(self.lbl_shop_path)
        path_layout.addWidget(self._make_v_sep())
        path_layout.addWidget(self.lbl_item_path)
        path_layout.addWidget(self._make_v_sep())
        path_layout.addWidget(self.lbl_tkt_path)
        path_layout.addWidget(self._make_v_sep())
        path_layout.addWidget(self.lbl_mu_path)
        path_layout.addStretch()

        main_layout.addWidget(path_content)

    # ================================================================
    # 状态与主题管理
    # ================================================================

    def _set_edit_enabled(self, enabled):
        self.edit_content.setEnabled(enabled)

    def _make_v_sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setProperty("class", "VSepLine")
        return sep

    def _update_path_labels(self):
        update_path_labels([
            (self.lbl_shop_path, self.shop_path, "TKShop.dat"),
            (self.lbl_item_path, self.item_path, "TKItem.dat"),
            (self.lbl_tkt_path, self.tkt_path, "TKT.dat"),
            (self.lbl_mu_path, self.mu_path, "Mu.JVG"),
        ], self._is_dark)

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._update_path_labels()
        self._refresh_table()

    # ================================================================
    # 数据加载
    # ================================================================

    def load_tks_dir(self, tks_dir):
        shop = os.path.join(tks_dir, "TKShop.dat")
        item = os.path.join(tks_dir, "TKItem.dat")
        tkt  = os.path.join(tks_dir, "TKT.dat")
        mu   = os.path.join(tks_dir, "Mu.JVG")

        missing = []
        for p, n in [(shop, "TKShop.dat"), (item, "TKItem.dat")]:
            if not os.path.exists(p):
                missing.append(n)

        if missing:
            QMessageBox.warning(self, "文件缺失", f"目录中未找到: {', '.join(missing)}\n\n请确认选择了正确的 TKS 目录。")
            return

        self.shop_path = shop
        self.item_path = item
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self.mu_path = mu if os.path.exists(mu) else None
        self._reload()

    def _reload(self):
        if not self.shop_path:
            return
        if is_running(getattr(self, '_load_worker', None)):
            return

        self.lbl_status.setText("加载中…")
        shop_path, item_path, tkt_path, mu_path = (
            self.shop_path, self.item_path, self.tkt_path, self.mu_path)

        # 后台线程: 纯文件 IO/解码 (P3-3), UI 刷新在 _on_load_success
        def work(w):
            items = []
            if item_path and os.path.exists(item_path):
                items = load_tkitem_with_tkt(item_path, tkt_path or "")
            mu = []
            if mu_path and os.path.exists(mu_path):
                mu = load_mu_sprites(mu_path) or []
            records = load_shop_data(shop_path)
            return items, mu, records

        self._load_worker = run_background(
            self, work,
            on_success=self._on_load_success,
            on_error=self._on_load_error)

    def _on_load_success(self, result):
        items, mu, records = result
        self.items = items
        self.item_names = {it[0]: it[5] for it in self.items}
        # 物品图标查找表 (数组索引 → icon 精灵值)
        self._item_icons = {it[0]: it[6] for it in self.items}
        self._mu_sprites = mu
        self._icon_pixmaps.clear()
        self.records = records
        self._original_records = [[r['area_id'], r['item_ref'], r['condition'], r['display']] for r in self.records]
        self._dirty = False
        self.lbl_status.setText(f"已加载 {len(self.records)} 条商店记录 + {len(self.items)} 个物品")
        self._update_path_labels()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _on_load_error(self, err_msg):
        QMessageBox.critical(self, "加载失败", f"无法加载 TKShop.dat:\n{err_msg}")
        self.records = []
        self._update_path_labels()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _get_icon_pixmap(self, icon_val, size=(24, 24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    # ================================================================
    # 过滤 & 表格
    # ================================================================

    def _apply_filter(self):
        area_filter_idx = self.area_filter_combo.currentIndex()
        search_text = self.search_input.text()

        self.filtered_indices = []
        for rec in self.records:
            if area_filter_idx > 0:
                fid = self.area_filter_combo.currentData()
                if rec['area_id'] != fid:
                    continue
            if search_text:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                cond_str = self._cond_str(rec['condition'])
                if not search_match(
                    search_text,
                    rec['index'], rec['area_id'], area_label(rec['area_id']),
                    rec['item_ref'], iname, cond_str,
                ):
                    continue
            self.filtered_indices.append(rec['index'])

        self._refresh_table()
        self.lbl_status.setText(f"显示 {len(self.filtered_indices)} / {len(self.records)} 条  |  文件 → 保存 (Ctrl+S) 写入磁盘")

    def _clear_filter(self):
        self.search_input.clear()
        self.area_filter_combo.setCurrentIndex(0)
        self._apply_filter()

    def _cond_str(self, cond):
        if cond == 1:
            return "随机抽选"
        return f"幸运{cond:+d}"

    def _refresh_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.filtered_indices))

        color_random = QColor("#D4883A") if self._is_dark else QColor("#CC6600")  # 主题感知: 深浅两档

        for r, idx in enumerate(self.filtered_indices):
            rec = self.records[idx]
            iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
            cond_str = self._cond_str(rec['condition'])

            # 图标列 (column 0)
            icon_item = QTableWidgetItem()
            icon_val = self._item_icons.get(rec['item_ref'], 0)
            pix = self._get_icon_pixmap(icon_val, (36, 36)) if icon_val else None
            if pix:
                icon_item.setIcon(QIcon(pix))

            item_idx = QTableWidgetItem()
            item_idx.setData(Qt.DisplayRole, rec['index'])
            item_idx.setData(Qt.UserRole, rec['index'])  # 缓存原始索引

            item_aid = QTableWidgetItem()
            item_aid.setData(Qt.DisplayRole, rec['area_id'])

            item_aname = QTableWidgetItem(area_label(rec['area_id']))

            item_iref = QTableWidgetItem()
            item_iref.setData(Qt.DisplayRole, rec['item_ref'])

            item_iname = QTableWidgetItem(iname)
            item_cond = QTableWidgetItem(cond_str)

            # 条件着色
            if rec['condition'] == 1:
                for col_item in (item_idx, item_aid, item_aname, item_iref, item_iname, item_cond):
                    col_item.setForeground(color_random)

            self.table.setItem(r, 0, icon_item)
            self.table.setItem(r, 1, item_idx)
            self.table.setItem(r, 2, item_aid)
            self.table.setItem(r, 3, item_aname)
            self.table.setItem(r, 4, item_iref)
            self.table.setItem(r, 5, item_iname)
            self.table.setItem(r, 6, item_cond)

    def _on_header_click(self, logicalIndex):
        if self.sort_col == logicalIndex:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = logicalIndex
            self.sort_reverse = False

        keys = {1: 'index', 2: 'area_id', 3: 'area_id', 4: 'item_ref', 5: 'item_ref', 6: 'condition'}
        key = keys.get(logicalIndex, 'index')

        self.filtered_indices.sort(key=lambda i: self.records[i].get(key, 0), reverse=self.sort_reverse)
        self._refresh_table()

    # ================================================================
    # 右侧编辑面板
    # ================================================================

    def _on_table_select(self):
        row = self.table.currentRow()
        if row < 0:
            return
        # 从索引列 (column 1) 的 UserRole 获取真正的记录 index
        idx_item = self.table.item(row, 1)
        if not idx_item:
            return
        idx = idx_item.data(Qt.UserRole)
        rec = self.records[idx]
        self._populate_edit(rec)

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        self.lbl_rec_idx.setText(f"记录 #{rec['index']}")

        # area
        idx = self.edit_area_combo.findData(rec['area_id'])
        if idx >= 0:
            self.edit_area_combo.setCurrentIndex(idx)

        # item
        self.lbl_editing_item_idx.setText(str(rec['item_ref']))
        iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
        self.lbl_item_name.setText(iname)
        self._update_compat_label(rec['area_id'], rec['item_ref'])

        # condition
        cond = rec['condition']
        self.spin_cond.blockSignals(True)
        self.spin_cond.setValue(cond)
        self.spin_cond.blockSignals(False)

        if cond == 1:
            self.radio_random.setChecked(True)
        elif cond <= -100:
            self.radio_always.setChecked(True)
        else:
            self.radio_custom.setChecked(True)

        self._on_cond_mode()

    def _get_item_tab(self, item_ref):
        for it in self.items:
            if it[0] == item_ref:
                return it[2]
        return -1

    def _update_compat_label(self, area_id, item_ref):
        item_tab = self._get_item_tab(item_ref)
        allowed = TAB_TO_SHOP.get(item_tab, [])

        color_ok = "#4CAF50" if self._is_dark else "#228B22"  # 主题感知: 深浅两档
        color_err = "#E57373" if self._is_dark else "#CC3333"  # 主题感知: 深浅两档

        if area_id in allowed:
            self.lbl_compat.setText("✓ 该物品可在此商店出现")
            self.lbl_compat.setProperty("status", "loaded")
        elif not allowed:
            self.lbl_compat.setText("⚠ 该物品不会在任何商店出现")
            self.lbl_compat.setProperty("status", "missing")
        else:
            shop_names = [AREA_NAMES.get(a, str(a)) for a in allowed]
            self.lbl_compat.setText(f"⚠ 不兼容! 该物品仅适用于: {', '.join(shop_names)}")
            self.lbl_compat.setProperty("status", "missing")
        self.lbl_compat.style().unpolish(self.lbl_compat)
        self.lbl_compat.style().polish(self.lbl_compat)

    def _on_area_changed(self):
        if self._editing_idx < 0:
            return
        try:
            item_ref = int(self.lbl_editing_item_idx.text())
        except ValueError:
            return
        area_id = self.edit_area_combo.currentData()
        self._update_compat_label(area_id, item_ref)

    def _on_cond_mode(self):
        if self.radio_random.isChecked():
            self.spin_cond.setValue(1)
            self.spin_cond.setEnabled(False)
        elif self.radio_always.isChecked():
            self.spin_cond.setValue(-100)
            self.spin_cond.setEnabled(False)
        else:
            self.spin_cond.setEnabled(True)
        self._refresh_cond_table()

    def _on_cond_changed(self):
        if self.radio_custom.isChecked():
            self._refresh_cond_table()

    def _refresh_cond_table(self):
        offset = self.spin_cond.value()

        if offset == 1 and self.radio_random.isChecked():
            self.txt_cond_table.setPlainText(
                "  (随机抽选模式)\n  每次进入商店时随机判定\n  最多同时出现5件商品"
            )
            return

        if offset > 0:
            desc = f"队伍最大幸运 ＞ {offset} 时开始出现"
        elif offset == 0:
            desc = f"队伍最大幸运 ≥ 1 时开始出现"
        else:
            desc = f"队伍最大幸运 ≥ 0 时已有 {min(100, -offset)}% 概率"

        lines = [f"  {desc}", f"  每多1点幸运, 概率+1%", ""]

        for pct in [25, 50, 75, 100]:
            need_luk = offset + pct
            if need_luk >= 0:
                label = "必定出现" if pct >= 100 else ""
                lines.append(f"  幸运 ≥ {need_luk:>3d}  →  {pct:>3d}%  {label}")

        header = f"  条件值: {offset:+d}"
        self.txt_cond_table.setPlainText(header + '\n' + '\n'.join(lines))

    def _pick_item(self):
        # 将 shop items tuple 列表转换为 ItemPickerDialog 所需的 dict 列表
        item_list = []
        for idx, item_id, tab_code, name_id, equip_type, name, icon, price in self.items:
            item_list.append({
                'index': idx, 'item_id': item_id, 'tab_code': tab_code,
                'name': name, 'equip_type': equip_type,
                'icon': icon, 'price': price,
            })
        dialog = ItemPickerDialog(
            self, item_list,
            icon_pixmap_fn=self._get_icon_pixmap,
            return_key='index',
        )
        if dialog.exec() == QDialog.Accepted and dialog.selected_value is not None:
            picked = dialog.selected_value
            if picked >= 0:
                self.lbl_editing_item_idx.setText(str(picked))
                self.lbl_item_name.setText(self.item_names.get(picked, f"Item#{picked}"))
                self._on_area_changed()  # 更新兼容性验证

    def _apply_edit(self):
        if self._editing_idx < 0:
            return

        rec = self.records[self._editing_idx]
        rec['area_id'] = self.edit_area_combo.currentData()
        rec['item_ref'] = int(self.lbl_editing_item_idx.text())
        rec['condition'] = self.spin_cond.value()

        self._dirty = True
        self._apply_filter()

        # 重新选中编辑行
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1) and self.table.item(r, 1).data(Qt.UserRole) == rec['index']:
                self.table.selectRow(r)
                break

        self.lbl_status.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存到磁盘)")

    def _delete_record(self):
        if self._editing_idx < 0:
            return
        if themed_question(self, "确认删除", f"确定要清空记录 #{self._editing_idx} 吗?\n\n记录将被重置为零值, 而非物理删除。") != QMessageBox.Yes:
            return

        self.records[self._editing_idx] = {
            'index': self._editing_idx, 'area_id': 0, 'item_ref': 0,
            'condition': 0, 'display': 0, 'reserved': 0
        }
        self._dirty = True
        self._apply_filter()

    def _add_record(self):
        FIXED_COUNT = 240
        while len(self.records) < FIXED_COUNT:
            self.records.append({
                'index': len(self.records), 'area_id': 0, 'item_ref': 0,
                'condition': 0, 'display': 0, 'reserved': 0
            })

        for rec in self.records[:FIXED_COUNT]:
            if rec['area_id'] == 0 and rec['item_ref'] == 0 and rec['condition'] == 0:
                self._dirty = True
                self._apply_filter()

                for r in range(self.table.rowCount()):
                    if self.table.item(r, 1) and self.table.item(r, 1).data(Qt.UserRole) == rec['index']:
                        self.table.selectRow(r)
                        self.table.scrollToItem(self.table.item(r, 1))
                        break

                self.lbl_status.setText(f"选中空槽 #{rec['index']}, 请在右侧编辑后应用修改")
                return

        QMessageBox.warning(self, "已满", "240 条记录全部非空, 无法新增。\n请先删除一条旧记录腾出空槽。")

    # ================================================================
    # 保存 & 导出
    # ================================================================

    def _save(self):
        if not self.shop_path or not self.records:
            QMessageBox.information(self, "提示", "请先通过 文件 → 加载 TKS 目录 打开数据")
            return

        if themed_question(self, "确认保存", f"将保存 {len(self.records)} 条记录到:\n{self.shop_path}\n\n原文件将被覆盖。继续?") != QMessageBox.Yes:
            return

        backup_existing_file(self.shop_path)

        try:
            save_shop_data(self.shop_path, self.records)
            self._dirty = False
            self.lbl_status.setText(f"已保存 {len(self.records)} 条记录 → {self.shop_path}")
            QMessageBox.information(self, "保存成功", f"已保存 {len(self.records)} 条记录\n备份: {self.shop_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ── MOD 导出/导入编排 (T10 收敛: 编排在 mod_exporter, 此处仅声明数据差异) ──

    _MOD_SPEC = RecordModSpec(
        dat_name="TKShop.dat", rec_size=8, field_type="mixed", field_count=4,
        to_fields=lambda records: [[r['area_id'], r['item_ref'], r['condition'], r['display']]
                                   for r in records],
        from_fields=lambda field_rows: [
            {'index': i,
             'area_id': fields[0] if len(fields) > 0 else 0,
             'item_ref': fields[1] if len(fields) > 1 else 0,
             'condition': fields[2] if len(fields) > 2 else 0,
             'display': fields[3] if len(fields) > 3 else 0}
            for i, fields in enumerate(field_rows)
        ],
        path_attr="shop_path", status_attr="lbl_status",
        refresh_attr="_refresh_table", noun="条记录")

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        export_records_mod(self, self._MOD_SPEC)

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        export_records_mod(self, self._MOD_SPEC, ref_mode=True)

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        import_records_mod(self, self._MOD_SPEC)


# ============================================================
# 入口
# ============================================================

def main():
    run_editor(ShopEditorWindow, "TKShop Editor")

if __name__ == '__main__':
    main()
