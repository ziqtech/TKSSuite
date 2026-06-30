#!/usr/bin/env python3
"""
TKSkill.dat 可视化编辑器 (PySide6 最终完美 Godot 风格版)
=============================================================
修复了布局对齐、去除了冗余线框，并 100% 还原了 Godot 4.6 滚动条及主题样式。
"""

import struct, os, sys, csv, re
from collections import OrderedDict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QTextEdit, QComboBox, QMessageBox, QFileDialog,
    QDialog, QGridLayout, QFrame, QScrollArea
)
from PySide6.QtGui import QAction, QKeySequence, QColor, QFont, QIcon
from PySide6.QtCore import Qt, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.lzss import lzss_decompress_dat, lzss_compress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.mod_exporter import (
    diff_records, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, ModMetadataDialog,
    ask_reference_directory, load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, ModImportPreviewDialog,
)

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data): return lzss_decompress_dat(data)
def lzss_compress(data): return lzss_compress_dat(data)

def load_tkt(tkt_path): return load_tkt_simple(tkt_path)
def load_tkt_full(tkt_path): return load_tkt_simple(tkt_path, full_strip=True)

from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap

SKILL_REC = 94; SKILL_CNT = 350
SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_VALUES = [f"{k}-{v}" for k, v in sorted(SKILL_TYPES.items())]
ATK_TYPE_VALUES = ["-1-近战攻击", "0-物理攻击", "1-术法攻击", "10-召唤攻击"]

# STATUS_NAMES / STATUS_ICON_BASE 由 editor_utils.picker_dialogs 提供 (本地别名见下方导入)

SPECIAL_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻"), (1, "飙行", "移动范围扩大"),
    (2, "搜宝", "获得额外宝物"), (3, "解陷", "自动解除陷阱"),
]

BASIC_FIELDS = [
    ("skill_text_id", 0, "名称文本ID", 'tkt', "技能名称 TKT 文本ID"),
    ("skill_desc_id", 2, "说明文本ID", 'tkt', "技能说明 TKT 文本ID = skill_text_id + 400"),
    ("type", 4, "技能类型", 'type', "0=指令 1=主动 2=被动 3=移动"),
    ("jp_cost", 6, "技能点数", 'int', "学习技能所需点数 (JP)"),
]

TREE_FIELDS = []
for i in range(8):
    TREE_FIELDS.append(("ref_skill%d" % i, 8 + i*4, f"目标技能{i}", 'skill_pick', "受影响的目标技能索引"))
    TREE_FIELDS.append(("ref_type%d" % i, 10 + i*4, f"技能进度{i}", 'int', "累加进度权重(>=10可学), 20=归组"))

EFFECT_FIELDS = [
    ("timing", 40, "时序值Delay", 'int', "技能行动时序值"),
    ("hp_pct", 42, "生命加成%", 'int', "HP%加成"),
    ("heal_move", 44, "移步回血%", 'int', "自癒1=2 自癒2=3"),
    ("mp_pct", 46, "内力加成%", 'int', "MP%加成"),
    ("mp_move", 48, "移步回气%", 'int', "回气1=2 回气2=3"),
    ("atk_pct", 50, "攻击加成%", 'int', "攻击%加成"),
    ("def_pct", 52, "防御加成%", 'int', "防御%加成"),
    ("hit_pct", 54, "命中加成%", 'int', "命中%加成"),
    ("eva_pct", 56, "闪避加成%", 'int', "闪避%加成"),
    ("spd_pct", 58, "速度加成%", 'int', "速度%加成"),
    ("move_up", 60, "增加移动", 'int', "移动+1=2, 移动+2=3"),
    ("atk_count", 62, "增攻次数", 'int', "二連=2 三連=3"),
    ("special_flags",64,"特殊标志", 'flags', "飘浮/飙行等掩码"),
    ("mp_reduce", 66, "内息消耗减%", 'int', "施展指令技能内息减少%"),
]

IMMUNE_FIELDS = [
    ("immunity1", 68, "状态免疫 1-16", 'mask', "状态免疫位掩码 (状态 1-16)"),
    ("immunity2", 70, "状态免疫 17-32", 'mask', "状态免疫位掩码 (状态 17-32)"),
    ("exp_bonus", 72, "战后经验增加%", 'int', "战斗经验值增加% (鬼才)"),
    ("jp_bonus", 74, "战后技点增加%", 'int', "战斗技能点增加% (天才)"),
    ("magic_def", 76, "所受法伤减少%", 'int', "减少法术伤害% (抗魔)"),
    ("cost_gold", 78, "消耗金钱", 'int', "技能消耗金钱"),
    ("cost_res2", 80, "耗费兽元", 'int', "召唤技能兽元消耗"),
]

ADVANCED_FIELDS = [
    ("cost_res3", 82, "耗费灵魂", 'int', "幻灵技能灵魂消耗"),
    ("turn_shift", 84, "调整时序", 'int', "敌人行动时序偏移"),
    ("mp_cost", 86, "耗费内力", 'int', "技能消耗内力值"),
    ("trigger_prob",88, "触发概率", 'int', "状态免疫等级/被动技能触发概率"),
    ("sub_count", 90, "子技能数量", 'int', "技能组头子技能数 (-1=独立)"),
    ("atk_type", 92, "攻击类型", 'atk_type', "攻击伤害类别 (-1近战 0物理 1术法 10召唤)"),
]

ALL_FIELDS = (BASIC_FIELDS + EFFECT_FIELDS + IMMUNE_FIELDS + list(ADVANCED_FIELDS) + TREE_FIELDS)

TYPE_HINT_LABELS = {
    1: "主动技能: 百分比属性加成 → 角色战斗属性",
    2: "被动技能: 触发概率 → 角色反应系统",
    3: "移动技能: 特殊标志 + 移动能力 → 角色地图能力",
    0: "指令技能: 技能组根节点, 含子技能列表",
}

def skill_name(rec, tkt):
    sid = rec.get('skill_text_id', 0)
    if sid and sid in tkt: return tkt[sid].split('\n')[0].strip()
    if sid and -sid in tkt: return tkt[-sid].split('\n')[0].strip()
    return f"Skill#{sid}" if sid else f"(空-#{rec['index']})"

def load_skills(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); recs = []
    for i in range(SKILL_CNT):
        off = i * SKILL_REC
        if off + SKILL_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h' * 47, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _ in ALL_FIELDS: rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_skills(fp, recs):
    buf = bytearray(SKILL_CNT * SKILL_REC)
    for rec in recs[:SKILL_CNT]:
        i = rec['index']; off = i * SKILL_REC
        for k, fo, _, _, _ in ALL_FIELDS: struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    with open(fp, 'wb') as f: f.write(compressed)
    return True

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.picker_dialogs import (
    TktPickerDialog, StatusPickerDialog, STATUS_NAMES, STATUS_ICON_BASE
)
from editor_utils.ui_helpers import make_fake_input, update_path_labels, confirm_close, export_csv

# ============================================================
# 弹窗选择器 (技能)
# ============================================================

class SkillPickerDialog(QDialog):
    def __init__(self, parent, records, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(600, 550)
        self.selected_index = None
        self.records = records
        self.tkt_dict = tkt_dict
        
        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        search_layout.addWidget(self.search_box)
        search_layout.addWidget(QLabel("类型:"))
        self.type_box = QComboBox()
        self.type_box.addItems(["全部"] + SKILL_TYPE_VALUES)
        self.type_box.currentIndexChanged.connect(self._refresh)
        search_layout.addWidget(self.type_box)
        layout.addLayout(search_layout)
        
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称'])
        self.table.setColumnWidth(0, 60); self.table.setColumnWidth(1, 60); self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("清空选择")
        btn_clear.clicked.connect(self._clear_selection)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._accept_selection)
        btn_layout.addWidget(btn_cancel); btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        self._refresh()
        
    def _refresh(self):
        query = self.search_box.text().strip().lower()
        ft = self.type_box.currentText()
        self.table.setRowCount(0)
        row = 0
        for r in self.records:
            if r['skill_text_id'] == 0: continue
            idx = r['index']; sid = r['skill_text_id']; st = r['type']
            sn = skill_name(r, self.tkt_dict)
            if query and query not in f"{idx} {sid} {sn}".lower(): continue
            if ft != "全部":
                try: ft_val = int(ft.split('-')[0])
                except: ft_val = None
                if st != ft_val: continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(str(sid)))
            self.table.setItem(row, 2, QTableWidgetItem(SKILL_TYPES.get(st, str(st))))
            self.table.setItem(row, 3, QTableWidgetItem(sn))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()
            
    def _clear_selection(self):
        self.selected_index = 0
        self.accept()

# ============================================================
# GUI 核心编辑器
# ============================================================

class SkillEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKSkill.dat 可视化编辑器 (PySide6)")
        self.resize(1260, 820)
        self.setMinimumSize(1000, 650)

        # 补全：精准加载原版要求的图标文件 TKS.ico
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        import sys as _sys
        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

        self.skill_path = self.tkt_path = None
        self.records = []; self.tkt = {}; self.tkt_full = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.filtered_indices = []; self._dirty = False
        self._editing_idx = None

        self.mu_path = None
        self._mu_sprites = []; self._icon_pixmaps = {}

        self.widget_map = {}
        self.extra_map = {}
        
        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出 CSV…", self._export_csv)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("新建技能", QKeySequence("Ctrl+N"), self._new_skill)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)

        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("关于", self._show_about)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar.addWidget(btn_search)
        
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar.addWidget(btn_clear)
        
        toolbar.addSpacing(15)
        toolbar.addWidget(QLabel("类型:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型"] + SKILL_TYPE_VALUES)
        self.type_filter.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_filter)
        
        toolbar.addSpacing(15)
        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)
        
        toolbar.addStretch()
        
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)
        
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # --- Main Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # --- Left Pane (Table) ---
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称', '技能点数', '耗费内力'])
        self.table.setColumnWidth(0, 60); self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(4, 70); self.table.setColumnWidth(5, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.splitter.addWidget(self._create_dock("技能列表", self.table))

        # --- Right Pane (Inspector) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)

        # 顶部行：记录标签 + 操作按钮
        header_row = QHBoxLayout()
        self.lbl_rec_idx = QLabel("未选中")
        self.lbl_rec_idx.setProperty("class", "RecordHeader")
        header_row.addWidget(self.lbl_rec_idx)
        header_row.addStretch()
        btn_apply = QPushButton("✅ 应用")
        btn_apply.clicked.connect(self._apply_edit)
        btn_reset = QPushButton("🔄 重置")
        btn_reset.clicked.connect(self._reset_edit)
        header_row.addWidget(btn_apply)
        header_row.addWidget(btn_reset)
        right_layout.addLayout(header_row)

        # Scroll Area for properties (Godot Style Layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.edit_inner = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_inner)
        self.edit_layout.setContentsMargins(4, 4, 16, 4)
        
        # =======================================================
        # Preview Panel (Godot 资源检查器头部风格)
        # =======================================================
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(8, 12, 8, 12)
        pl.setSpacing(6)

        # 1. 技能名称 (大标题)
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        pl.addWidget(self.preview_name)

        # 2. 技能元数据 (类型、点数、内力)
        self.preview_type = QLabel("")
        self.preview_type.setProperty("class", "PreviewMeta")
        self.preview_type.setWordWrap(True)
        pl.addWidget(self.preview_type)

        # 3. 技能描述 (替换掉丑陋的 QTextEdit，改用自动撑高的 QLabel)
        self.preview_desc = QLabel("请在左侧列表中选择一项技能。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextInteractionFlags(Qt.TextSelectableByMouse) # 允许鼠标选中文本复制
        pl.addWidget(self.preview_desc)

        # 4. 子技能高亮提示
        self.preview_sub = QLabel("")
        self.preview_sub.setProperty("class", "PreviewSubMeta")
        self.preview_sub.setWordWrap(True)
        pl.addWidget(self.preview_sub)

        self.edit_layout.addWidget(preview_frame)

        # Properties (No wireframes, Godot inspector grid alignment)
        self._build_field_group("基础属性", BASIC_FIELDS, 4)
        self._build_field_group("效果加成 (主动技能核心)", EFFECT_FIELDS, 4)
        self._build_field_group("状态免疫", IMMUNE_FIELDS, 4)
        self._build_field_group("高级属性", ADVANCED_FIELDS, 4)
        self._build_field_group("技能树引用表 (8组: 目标/进度)", TREE_FIELDS, 4)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)

        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setSizes([440, 820])

        # Bottom Path
        path_layout = QHBoxLayout()
        self.lbl_skill_path = QLabel("TKSkill.dat: 未加载")
        self.lbl_tkt_path = QLabel("TKT.dat: 未加载")
        path_layout.addWidget(self.lbl_skill_path)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt_path)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_field_group(self, title, fields, cols):
        """字段分组：标签在上、输入框在下 (对齐 warpc_editor_v2 布局)"""
        group_widget = QWidget()
        v_layout = QVBoxLayout(group_widget)
        v_layout.setContentsMargins(0, 4, 0, 4)
        v_layout.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "InspectorTitle")
        v_layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(15)
        grid.setContentsMargins(10, 0, 0, 0)

        for fi, (fn, fo, fl, ft, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, fn, fo, fl, ft, cmt)

        for c in range(cols):
            grid.setColumnStretch(c, 1)
        v_layout.addLayout(grid)
        self.edit_layout.addWidget(group_widget)

    def _build_field(self, grid, row, col, fn, fo, fl, ft, cmt):
        """单字段控件：标签在上、输入框在下"""
        cell = QVBoxLayout()
        cell.setSpacing(2)

        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        if ft == 'tkt' or ft == 'skill_pick':
            box = QFrame()
            box.setObjectName("FakeInputBox")
            container = QHBoxLayout(box)
            container.setSpacing(0)
            container.setContentsMargins(0, 0, 0, 0)

            inp = QLineEdit()
            inp.setMaximumWidth(50)
            btn = QPushButton("...")
            btn.setFixedWidth(28)
            btn.setCursor(Qt.PointingHandCursor)

            container.addWidget(inp)
            container.addStretch()
            container.addWidget(btn)
            cell.addWidget(box)

            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)

            self.widget_map[fn] = inp; self.extra_map[fn] = extra
            if ft == 'tkt': btn.clicked.connect(lambda _, f=fn: self._pick_tkt(f))
            else: btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))

        elif ft == 'type' or ft == 'atk_type':
            cb = QComboBox()
            if ft == 'type': cb.addItems(SKILL_TYPE_VALUES)
            else: cb.addItems(ATK_TYPE_VALUES)
            cell.addWidget(make_fake_input(combo=cb))
            self.widget_map[fn] = cb

        elif ft == 'mask' or ft == 'flags':
            inp = QLineEdit()
            inp.setVisible(False)

            btn = QPushButton("配置免疫状态…" if ft == 'mask' else "配置特殊标志…")
            btn.setCursor(Qt.PointingHandCursor)

            box = QFrame()
            box.setObjectName("FakeInputBox")
            container = QHBoxLayout(box)
            container.setSpacing(0)
            container.setContentsMargins(0, 0, 0, 0)
            container.addWidget(btn, 1)
            cell.addWidget(box)

            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)

            self.widget_map[fn] = inp; self.extra_map[fn] = extra
            if ft == 'mask':
                btn.clicked.connect(lambda _, f=fn: self._pick_status(f))
            else:
                btn.clicked.connect(lambda _, f=fn: self._pick_flags(f))
        else:
            inp = QLineEdit()
            cell.addWidget(make_fake_input(line_edit=inp))
            self.widget_map[fn] = inp

        grid.addLayout(cell, row, col, Qt.AlignTop)

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

    def _apply_theme(self):
        qss = ThemeManager.dark_qss() if self._is_dark else ThemeManager.light_qss()
        self.setStyleSheet(qss)
        self._update_paths()

    def _update_paths(self):
        update_path_labels([
            (self.lbl_skill_path, self.skill_path, "TKSkill.dat"),
            (self.lbl_tkt_path, self.tkt_path, "TKT.dat"),
        ], self._is_dark)

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        sk = os.path.join(d, "TKSkill.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(sk):
            QMessageBox.warning(self, "文件缺失", "未找到 TKSkill.dat"); return
        self.skill_path = sk
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        self._reload()

    def _reload(self):
        if not self.skill_path: return
        self.status_var.setText("加载中…")
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()
        try:
            self.records = load_skills(self.skill_path); self._dirty = False
            # MOD 导出使用原始字节序 (word index = byte_offset // 2)，与启动器 _apply_fields_to_record 一致
            self._original_records = []
            for rec in self.records:
                row = [0] * (SKILL_REC // 2)
                for k, fo, _, _, _ in ALL_FIELDS:
                    row[fo // 2] = rec[k]
                self._original_records.append(row)
            nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
            self.status_var.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    def _set_edit_enabled(self, en):
        self.edit_inner.setEnabled(en)

    def _apply_filter(self):
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        ftype = self.type_filter.currentText()
        for rec in self.records:
            if rec['skill_text_id'] == 0: continue
            if ftype and not ftype.startswith("全部"):
                if rec['type'] != int(ftype.split('-')[0]): continue
            if q:
                nm = skill_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['skill_text_id']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _clear_filter(self):
        self.search_entry.clear()
        self.type_filter.setCurrentIndex(0)
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            stype = SKILL_TYPES.get(r['type'], f"#{r['type']}")
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 1, QTableWidgetItem(str(r['skill_text_id'])))
            self.table.setItem(row, 2, QTableWidgetItem(stype))
            self.table.setItem(row, 3, QTableWidgetItem(skill_name(r, self.tkt)))
            self.table.setItem(row, 4, QTableWidgetItem(str(r['jp_cost'])))
            self.table.setItem(row, 5, QTableWidgetItem(str(r['mp_cost'])))

            # ==== 核心改造：为所有 4 种技能类型分配高辨识度专属颜色 ====
            if self._is_dark:
                # 深色模式高亮配色
                if r['type'] == 0:   color = QColor("#478cbf") # 指令: 引擎蓝
                elif r['type'] == 1: color = QColor("#e27d60") # 主动: 珊瑚橙 (极高辨识度)
                elif r['type'] == 2: color = QColor("#55b572") # 被动: 翠绿
                elif r['type'] == 3: color = QColor("#b988db") # 移动: 柔和紫
                else:                color = QColor("#dcdcdc") # 未知: 默认白灰
            else:
                # 浅色模式需要更深的颜色才能在白底上压住视觉
                if r['type'] == 0:   color = QColor("#28638f") # 深蓝
                elif r['type'] == 1: color = QColor("#bd5739") # 深橙红
                elif r['type'] == 2: color = QColor("#2d8046") # 深绿
                elif r['type'] == 3: color = QColor("#8a5bb8") # 深紫
                else:                color = QColor("#222222") # 未知: 默认黑

            for c in range(6):
                self.table.item(row, c).setForeground(color)

        self.table.blockSignals(False)

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        stype = SKILL_TYPES.get(rec['type'], f"#{rec['type']}")
        self.lbl_rec_idx.setText(f"技能 #{rec['index']}  文本ID={rec['skill_text_id']}  类型={stype}")

        nid = rec.get('skill_text_id', 0)
        n_txt = self.tkt.get(nid, "") if nid > 0 else ""
        # 加上前缀增加仪式感，空名称处理也更加优雅
        self.preview_name.setText(n_txt.split('\n')[0].strip() if n_txt else "未命名技能")

        did = nid + 400
        d_txt = self.tkt_full.get(did, "") if did > 0 else ""
        # 改用 setText，因为组件已经换成了 QLabel
        self.preview_desc.setText(d_txt if d_txt else "暂无关于该技能的详细描述。")
        
        hint = TYPE_HINT_LABELS.get(rec['type'], "")

        # ==== 检查器预览区类型同步高亮 ====
        if self._is_dark:
            type_color = {0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db"}.get(rec['type'], "#dcdcdc")
        else:
            type_color = {0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8"}.get(rec['type'], "#222222")

        # 使用 HTML 富文本进行局部着色，完美保留 QSS 的边框与排版
        self.preview_type.setText(
            f'<span style="color: {type_color}; font-weight: bold;">【{stype}】</span> '
            f'| 点数={rec["jp_cost"]} | 内力={rec["mp_cost"]} | {hint}'
        )
        sc = rec.get('sub_count', -1)
        self.preview_sub.setText(f"子技能: {sc} 个 (ID {rec['index']+1} - {rec['index']+sc})" if sc >= 0 else "")

        for fn, fo, fl, ft, _ in ALL_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if not w: continue
            
            if ft == 'type' or ft == 'atk_type':
                for i in range(w.count()):
                    if w.itemText(i).startswith(f"{val}-"): w.setCurrentIndex(i); break
            else:
                w.setText(str(val))
                
            if ft == 'tkt':
                nid = int(val) if val else 0
                txt = self.tkt.get(nid, "") if nid > 0 else ""
                t = txt.split('\n')[0] if txt else ""
                self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            elif ft == 'mask':
                self._update_mask_label(fn, int(val) if val else 0)
            elif ft == 'flags':
                self._update_flags_label(fn, int(val) if val else 0)
            elif ft == 'skill_pick':
                sidx = int(val) if val else 0
                if 0 < sidx < len(self.records) and self.records[sidx]['skill_text_id'] != 0:
                    nm = skill_name(self.records[sidx], self.tkt)
                    self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)
                else:
                    self.extra_map[fn].setText("")

    def _update_mask_label(self, fn, mask):
        base = 0 if fn == 'immunity1' else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_flags_label(self, fn, val):
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in SPECIAL_FLAG_BITS if mask & (1 << bit)]
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_tkt(self, fn):
        if not self.tkt: return
        dlg = TktPickerDialog(self, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            self.widget_map[fn].setText(str(dlg.selected_id))
            txt = self.tkt.get(dlg.selected_id, "")
            t = txt.split('\n')[0] if txt else ""
            self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            if fn == 'skill_text_id': self.preview_name.setText(txt.split('\n')[0].strip() if txt else "(无)")

    def _pick_skill(self, fn):
        if not self.records: return
        dlg = SkillPickerDialog(self, self.records, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = skill_name(self.records[dlg.selected_index], self.tkt) if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)

    def _pick_status(self, fn):
        base = 0 if fn == 'immunity1' else 16
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = StatusPickerDialog(self, "选择免疫状态 (位掩码)", STATUS_NAMES,
                                 cur, base, self._get_icon_pixmap, False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_mask_label(fn, dlg.selected_mask & 0xFFFF)

    def _pick_flags(self, fn):
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = QDialog(self)
        dlg.setWindowTitle("选择特殊标志")
        dlg.resize(300, 200)
        layout = QVBoxLayout(dlg)
        checkboxes = []
        for bit, name, desc in SPECIAL_FLAG_BITS:
            cb = QCheckBox(f"{name} ({desc})")
            cb.setChecked(bool(cur & (1 << bit)))
            checkboxes.append((bit, cb))
            layout.addWidget(cb)
            
        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("全清")
        btn_clear.clicked.connect(lambda: [cb.setChecked(False) for _, cb in checkboxes])
        btn_ok = QPushButton("确定")
        def _ok():
            m = 0
            for bit, cb in checkboxes:
                if cb.isChecked(): m |= (1 << bit)
            if m >= 0x8000: m -= 0x10000
            self.widget_map[fn].setText(str(m))
            self._update_flags_label(fn, m)
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_layout.addWidget(btn_clear); btn_layout.addStretch(); btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _apply_edit(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, _ in ALL_FIELDS:
            w = self.widget_map.get(fn)
            if not w: continue
            try:
                if ft == 'type' or ft == 'atk_type':
                    v = int(w.currentText().split('-')[0])
                else:
                    v = int(w.text() or 0)
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                rec[fn] = v
            except ValueError:
                rec[fn] = 0
                
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == rec['index']:
                self.table.selectRow(r); break
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存)")

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _new_skill(self):
        if not self.records: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                rec['skill_text_id'] = rec['index'] + 1
                rec['type'] = 1; rec['jp_cost'] = 1
                rec['sub_count'] = -1; rec['atk_type'] = -1
                self._dirty = True; self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r); break
                self._populate_edit(rec)
                self.status_var.setText(f"已创建新技能 → 槽位 #{rec['index']}")
                return
        QMessageBox.warning(self, "槽位已满", f"所有 {SKILL_CNT} 个槽位均已占用")

    def _copy_record(self):
        if self._editing_idx is None: return
        src = self.records[self._editing_idx]
        if src['skill_text_id'] == 0: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True; self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r); break
                self._populate_edit(rec)
                return

    def _clear_current(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        if rec['skill_text_id'] == 0: return
        reply = QMessageBox.question(self, "确认", f"确定清空记录 #{rec['index']}?")
        if reply == QMessageBox.Yes:
            for k, fo, _, _, _ in ALL_FIELDS: rec[k] = 0
            rec['sub_count'] = -1
            self._dirty = True; self._apply_filter()
            self._populate_edit(rec)

    def _save(self):
        if not self.skill_path or not self.records: return
        reply = QMessageBox.question(self, "确认保存", f"将覆盖保存并生成.bak:\n{self.skill_path}")
        if reply == QMessageBox.Yes:
            try:
                with open(self.skill_path, 'rb') as s:
                    with open(self.skill_path + ".bak", 'wb') as d: d.write(s.read())
            except: pass
            try:
                save_skills(self.skill_path, self.records); self._dirty = False
                QMessageBox.information(self, "成功", "保存成功！")
                self.status_var.setText(f"已保存 → {self.skill_path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        filtered = [r for r in self.records if r['skill_text_id'] != 0]
        hdr = ['索引', '名称', '类型'] + [fl for _, _, fl, _, _ in ALL_FIELDS]
        def row_func(rec):
            return [rec['index'], skill_name(rec, self.tkt),
                    SKILL_TYPES.get(rec['type'], str(rec['type']))] + \
                   [rec[fn] for fn, _, _, _, _ in ALL_FIELDS]
        if export_csv(self, filtered, hdr, row_func, "TKSkill.csv"):
            self.status_var.setText("已导出 CSV")

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        if not self.records or not self._original_records:
            QMessageBox.information(self, "提示", "请先加载数据"); return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 构建原始字节序字段数组 (word index = byte_offset // 2)，与启动器一致
        current_fields = []
        for rec in self.records:
            row = [0] * (SKILL_REC // 2)
            for k, fo, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)
        diff_result = diff_records(
            self._original_records, current_fields, field_count, len(self._original_records))

        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。"); return

        crc = compute_crc32(self.skill_path) if self.skill_path else "0x00000000"
        data_json = build_data_diff_json(
            target="TKSkill.dat", record_size=SKILL_REC, field_type="int16",
            field_count=field_count, original_count=len(self._original_records),
            original_crc32=crc, diff_result=diff_result)

        components = [{"file": "data/TKSkill.dat.json", "target": "TKSkill.dat"}]
        mod_json = generate_mod_json(metadata, components)

        default_name = f"{metadata['id']}.tksmod"
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", default_name, "TKS MOD (*.tksmod)")
        if not fp: return

        try:
            pack_tksmod(fp, mod_json, {"data/TKSkill.dat.json": data_json})
            n_mod = len(diff_result['modified']); n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(self, "导出成功", f"已导出 MOD 文件:\n{fp}\n\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        ref_dir = ask_reference_directory(self)
        if not ref_dir: return
        ref_records = load_reference_dat_fields(ref_dir, "TKSkill.dat",
            rec_size=SKILL_REC, field_count=len(ALL_FIELDS), field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKSkill.dat"); return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata(); self._last_mod_metadata = metadata

        # 构建原始字节序字段数组 (word index = byte_offset // 2)，与启动器一致
        current_fields = []
        for rec in self.records:
            row = [0] * (SKILL_REC // 2)
            for k, fo, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)
        diff_result = diff_records(ref_records, current_fields, field_count, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。"); return

        crc = compute_crc32(os.path.join(ref_dir, "TKSkill.dat"))
        data_json = build_data_diff_json(target="TKSkill.dat", record_size=SKILL_REC, field_type="int16",
            field_count=field_count, original_count=len(ref_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKSkill.dat.json", "target": "TKSkill.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{metadata['id']}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKSkill.dat.json": data_json})
            n_mod = len(diff_result['modified']); n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件"); return

        if "TKSkill.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 TKSkill.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}"); return

        dlg = ModImportPreviewDialog(self, info)
        if dlg.exec() != QDialog.Accepted: return

        ref_dir = ask_reference_directory(self, "选择原始游戏目录 (作为基底数据)")
        if not ref_dir: return

        mod_json, records = import_tksmod_records(
            fp, ref_dir, "TKSkill.dat",
            rec_size=SKILL_REC, field_count=len(ALL_FIELDS),
            field_fmt='h', use_lzss=True
        )
        if records is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 TKSkill.dat"); return

        new_records = []
        for i, fields in enumerate(records):
            rec = {'index': i}
            for k, fo, _, _, _ in ALL_FIELDS:
                word_idx = fo // 2
                rec[k] = fields[word_idx] if word_idx < len(fields) else 0
            new_records.append(rec)

        self.records = new_records
        self._original_records = [list(row) for row in records]
        self._dirty = False

        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "type": info.get("type", "data"),
            "mode": info.get("mode", "mixed"),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(self.records)} 条技能")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 条记录。\n"
            f"您现在可以继续编辑并重新导出。")

    def _show_about(self):
        QMessageBox.about(self, "关于", "TKSkill.dat PySide6 编辑器\n已应用 Godot 4.6 级别布局与纯净控件约束。")

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _t = QTranslator()
    _t.load("qtbase_zh_CN", os.path.join(os.path.dirname(__file__), '..', 'editor_utils'))
    app.installTranslator(_t)
    editor = SkillEditorApp()
    editor.show()
    sys.exit(app.exec())