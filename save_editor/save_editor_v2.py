#!/usr/bin/env python3
"""
TKS Save Editor v2.0 (PySide6 — Godot 4.6 风格)
===========================================================
加载/编辑/保存 游戏存档数据 (save\\sav.N + N.sav), 支持全部9个存档槽位。

逆向来源: TKS.exe sub_410ED4 (SaveTKMat), sub_41103C (LoadTKMat)
索引文件: sub_41CE10 (SaveIndexWrite), sub_41B1A8 (SaveSlotDisplay)
兼容性:   支持 TKSLauncher 扩展后的 WarPC 缓冲区 (动态大小检测)

存档数据文件格式 (sav.N):
  Frame 1: [4B compressed_size][LZSS(2304000B TKMat实体表)]
  Frame 2: [4B compressed_size][LZSS(BlockA 3432B + BlockB 5768B + BlockC WarPC)]
  WarPC 原始大小 = 143*1054 = 150722B, 启动器扩展后可能更大

索引文件格式 (N.sav, 28字节):
  [6×1B team_ids][2B gold][4B unix_timestamp][6×2B team_levels][4B scene_id]

用法:
  python save_editor_v2.py
"""

import struct, os, sys, time, datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QMessageBox, QFileDialog, QDialog, QGridLayout, QFrame, QScrollArea,
    QTabWidget, QTextEdit, QSpinBox, QGroupBox, QFormLayout,
)
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator
from PySide6.QtCore import Qt, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.window_theme import apply_godot_theme
from editor_utils.ui_helpers import update_path_labels, confirm_close
from editor_utils.lzss import lzss_decompress_save, lzss_compress_save, lzss_decompress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap

# ============================================================
# 常量 (来自逆向工程 — 每个值附带反编译代码证据)
# ============================================================

# Frame 1: TKMat 游戏实体表 (dword_51AF40)
GAMESTATE_SIZE = 2304000  # 6000 entities × 384 bytes

# Frame 2 三段布局 (来源: 410ED4.c:25-28, 41103C.c:28,34-36)
SEG1_SIZE = 3432   # Block A: 脚本全局变量 (unk_755B18)
SEG2_SIZE = 5768   # Block B: 背包/队伍/金币 (unk_756880)
WARPC_OFFSET = 9200  # = SEG1_SIZE + SEG2_SIZE
WARPC_REC = 1054   # 每条WarPC记录字节数
WARPC_ORIG_CNT = 143
WARPC_ORIG_SIZE = 150722

# .sav 索引文件 (28字节)
SAV_META_SIZE = 28

# ============================================================
# 段1 (0x755B18, 3432B) 已知字段
# ============================================================
SEG1_BASIC_FIELDS = [
    ("map_id",       0x40, 4, "当前地图ID",     "I",  "dword_755B58, sub_40C044地图切换"),
    ("current_char", 0x44, 4, "当前角色ID",     "I",  "dword_755B5C, sub_40C7CC SetPlayer事件"),
    ("game_active",  0x48, 4, "游戏激活标志",    "I",  "dword_755B60, sub_41103C读档后置1"),
    ("given_name",   0x4C, 5, "名",             "big5", "byte_755B64, sub_40D2D0"),
    ("surname",      0x54, 5, "姓",             "big5", "byte_755B6C, sub_40D2D0"),
]

SEG1_SLOT_FIELDS = [
    ("slot1_active", 0x15C, 2, "编成槽1激活",    "H",  "word_755C74"),
    ("slot1_idx",    0x15E, 2, "编成槽1角色索引", "H",  "word_755C76"),
    ("slot2_active", 0x160, 2, "编成槽2激活",    "H",  "word_755C78"),
    ("slot2_idx",    0x162, 2, "编成槽2角色索引", "H",  "word_755C7A"),
]

SEG1_MAP_FIELDS = [
    ("battle_flags", 0x168, 4, "遭遇战旗标",     "I",  "dword_755C80, bit0减半/bit1禁止/bit2强制/bit3反击"),
    ("map_timer",    0x82C, 2, "地图计时器",     "H",  "word_756344"),
    ("door_unlock",  0x82E, 2, "开门标志",       "H",  "word_756346"),
]

SEG1_EVENT_FIELDS = [
    ("comp_flag",    0x336, 2, "同伴管理标志",    "H",  "word_755E4E"),
    ("minigame_rst", 0x366, 2, "小游戏结果",     "H",  "word_755E7E"),
    ("last_acq",     0x566, 2, "最后获得量",     "H",  "word_75607E"),
]

# 数组字段定义
SEG1_ARRAYS = [
    ("switches",     0x2F8, 32,  2, "事件开关",      "word_755E10[32], case49"),
    ("results",      0x338, 24,  2, "事件结果",      "word_755E50[24], case60"),
    ("variables",    0x368, 256, 2, "事件变量",      "word_755E80[256], case36-39"),
    ("flags",        0x568, 1024,2, "事件标志",      "word_756080[1024], sub_40CB08/sub_40CB4C"),
]

# ============================================================
# 段2 (0x756880, 5768B) 已知字段
# ============================================================
SEG2_CORE_FIELDS = [
    ("gold",         0x02, 2, "金钱",          "H",  "word_756882, 上限30000"),
    ("wisdom",       0x07, 1, "智慧",         "B",  "byte_756886"),
    ("benevolence",  0x06, 1, "仁德",         "B",  "byte_756887"),
    ("courage",      0x08, 2, "勇气",         "H",  "word_756888"),
    ("medicine",     0x0A, 2, "医术",         "H",  "word_75688A, 上限100"),
]

SEG2_TEAM_FIELDS = [
    ("team0", 0x0C, 2, "队伍成员1", "h", "-1=空"),
    ("team1", 0x0E, 2, "队伍成员2", "h", ""),
    ("team2", 0x10, 2, "队伍成员3", "h", ""),
    ("team3", 0x12, 2, "队伍成员4", "h", ""),
    ("team4", 0x14, 2, "队伍成员5", "h", ""),
    ("team5", 0x16, 2, "队伍成员6", "h", ""),
]

SEG2_BATTLE_FIELDS = [
    ("wins",         0x163A, 2, "胜场数",       "H",  "word_757EBA"),
    ("losses",       0x163C, 2, "败场数",       "H",  "word_757EBC"),
    ("kills",        0x163E, 2, "杀敌数",       "H",  "word_757EBE"),
    ("quest_pct",    0x167E, 2, "完成任务%",    "H",  "word_757EFE"),
    ("special_pct",  0x1680, 2, "特殊物品%",    "H",  "word_757F00"),
    ("souls",        0x1684, 2, "收纳灵魂",      "H",  "word_757F04"),
    ("beasts",       0x1686, 2, "收纳兽元",      "H",  "word_757F06"),
]

SEG2_INV_COUNT = ("inv_count", 0x828, 2, "物品种类数", "H", "word_7570A8")

SEG2_INVENTORY = [
    ("inv_items", 0x82A, 600, "物品ID",      "word_7570AA[600]"),
    ("inv_types", 0xCDA, 600, "物品类型索引", "word_75755A[600]"),
    ("inv_qtys",  0x118A, 600, "物品堆叠数量", "word_757A0A[600]"),
]

# ============================================================
# WarPC 字段定义
# ============================================================
WARPC_IDENTITY = [
    ("name_id",       0,   "名称TKT ID",   "角色名称"),
    ("portrait",      2,   "头像索引",     "Fa.JVG ×2大幅图"),
    ("level",         4,   "等级",         ""),
    ("role",          6,   "身份",         "-1=未激活 0=已激活"),
    ("exp_to_next",   8,   "升级所需经验", ""),
    ("awk_sprite_id", 520, "战场图集索引", "Awk.JVG块号"),
    ("portrait_menu", 522, "队伍头像ID",   "Mu.JVG块号"),
    ("entity_link",   526, "地图实体ID",   "离队后NPC实体"),
]

WARPC_HPMP = [
    ("cur_hp",  10, "当前HP", ""), ("cur_mp",  12, "当前MP", ""),
    ("hp_base", 14, "HP基础", ""), ("hp_max",  16, "HP上限", ""),
    ("mp_base", 18, "MP基础", ""), ("mp_max",  20, "MP上限", ""),
]

STAT_NAMES = ["攻击", "防御", "命中", "闪避", "速度", "幸运", "移动", "悟性"]
STAT_SHORTS = ["atk", "def", "hit", "eva", "spd", "luk", "mov", "wis"]
STAT_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]

WARPC_CHAR_ATTR = [
    ("char_wisdom",      54, "智慧", ""), ("char_benevolence", 56, "仁德", ""),
    ("char_courage",     58, "勇气", ""), ("char_medicine",    60, "医术", "上限100"),
    ("jp_total",         62, "技能点数", ""),
]

WARPC_GROWTH = [
    ("growth_early", 528, "成长率初期", ""), ("growth_mid", 530, "成长率中期", ""),
    ("growth_late",  532, "成长率后期", ""),
]

WARPC_BATTLE_REWARD = [
    ("jp_reward",   536, "战后JP点", ""), ("gold_reward", 538, "战后金钱基数", ""),
]

WARPC_DROP = [
    ("drop_item0", 540, "必掉落物品", ""), ("drop_item1", 542, "高概率掉落", ""),
    ("drop_item2", 544, "低概率掉落", ""),
]

WARPC_EQUIP = [
    ("equip_idx0", 138, "装备索引0", ""), ("equip_idx1", 140, "装备索引1", ""),
    ("equip_idx2", 142, "装备索引2", ""), ("equip_idx3", 144, "装备索引3", ""),
    ("equip_id0",  146, "装备物品ID0", ""), ("equip_id1",  148, "装备物品ID1", ""),
    ("equip_id2",  150, "装备物品ID2", ""), ("equip_id3",  152, "装备物品ID3", ""),
]

# ============================================================
# 事件语义标注 (从逆向分析提取)
# ============================================================
# 事件开关: word_755E10[32], case 49 设置
# 语义需从脚本数据(TKD.dat)中具体事件调用来推导, 此处标注通用用途
SWITCH_SEMANTICS = {i: f"开关#{i}" for i in range(32)}

# 事件变量: word_755E80[250], case 36/37 设置
# case 36: 直接赋值; case 37: 随机数; case 38/39: 作为 flag 操作的值来源
VARIABLE_SEMANTICS = {i: f"变量#{i}" for i in range(250)}

# 事件标志: word_756080[1024], sub_40CB08 设置 / sub_40CB4C 累加
# case 61 (sub_40E40C) 检查: 比较 flag[id] 与期望值
FLAG_SEMANTICS = {i: f"标志#{i}" for i in range(1024)}

# 事件结果: word_755E50[24], case 60 检查
RESULT_SEMANTICS = {i: f"结果#{i}" for i in range(24)}

PAGE_NAMES = {0: "药品", 1: "道具", 2: "武器", 3: "防具", 4: "饰品", 5: "特殊"}


# ============================================================
# 数据加载/保存
# ============================================================

def load_save_data(path):
    """加载 sav.N 数据文件. 返回 (game_state, seg1, seg2, seg3)."""
    with open(path, 'rb') as f:
        raw = f.read()
    offset = 0
    # Frame 1
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame1 大小")
    comp1 = struct.unpack_from('<I', raw, offset)[0]; offset += 4
    if offset + comp1 > len(raw):
        raise ValueError(f"Frame1 数据不完整 (需要 {comp1} 字节)")
    game_state = lzss_decompress_save(raw[offset:offset + comp1]); offset += comp1
    if len(game_state) != GAMESTATE_SIZE:
        raise ValueError(f"Frame1 解压大小异常: {len(game_state)} (期望 {GAMESTATE_SIZE})")
    # Frame 2
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame2 大小")
    comp2 = struct.unpack_from('<I', raw, offset)[0]; offset += 4
    if offset + comp2 > len(raw):
        raise ValueError(f"Frame2 数据不完整 (需要 {comp2} 字节)")
    frame2 = lzss_decompress_save(raw[offset:offset + comp2])
    if len(frame2) < WARPC_OFFSET:
        raise ValueError(f"Frame2 解压大小不足: {len(frame2)} < {WARPC_OFFSET}")
    seg1 = bytearray(frame2[:SEG1_SIZE])
    seg2 = bytearray(frame2[SEG1_SIZE:WARPC_OFFSET])
    seg3 = bytearray(frame2[WARPC_OFFSET:])
    return bytearray(game_state), seg1, seg2, seg3


def save_save_data(path, game_state, seg1, seg2, seg3):
    """保存 sav.N 数据文件. 自动备份原文件."""
    frame2 = bytes(seg1) + bytes(seg2) + bytes(seg3)
    inner1 = lzss_compress_save(bytes(game_state))
    inner2 = lzss_compress_save(frame2)
    if os.path.exists(path):
        try:
            with open(path, 'rb') as s:
                with open(path + '.bak', 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
    with open(path, 'wb') as f:
        f.write(struct.pack('<I', len(inner1)))
        f.write(inner1)
        f.write(struct.pack('<I', len(inner2)))
        f.write(inner2)
    # 验证回读
    gs_v, s1_v, s2_v, s3_v = load_save_data(path)
    if gs_v != game_state:
        raise RuntimeError("保存验证失败: Frame1 回写不匹配!")
    if s1_v != seg1 or s2_v != seg2 or s3_v != seg3:
        raise RuntimeError("保存验证失败: Frame2 回写不匹配!")


def load_index_file(path):
    """加载 N.sav 索引文件 (28字节)."""
    if not os.path.exists(path):
        return None
    data = bytearray(open(path, 'rb').read())
    if len(data) < SAV_META_SIZE:
        return None
    team_ids = [data[i] if data[i] != 0xFF else -1 for i in range(6)]
    gold = struct.unpack_from('<H', data, 6)[0]
    timestamp = struct.unpack_from('<I', data, 8)[0]
    team_levels = [struct.unpack_from('<H', data, 12 + i * 2)[0] for i in range(6)]
    scene_id = struct.unpack_from('<i', data, 24)[0]
    return {'team_ids': team_ids, 'gold': gold, 'timestamp': timestamp,
            'team_levels': team_levels, 'scene_id': scene_id}


def save_index_file(path, meta_dict):
    """保存 N.sav 索引文件."""
    data = bytearray(SAV_META_SIZE)
    for i, tid in enumerate(meta_dict['team_ids'][:6]):
        data[i] = tid & 0xFF if tid >= 0 else 0xFF
    struct.pack_into('<H', data, 6, meta_dict['gold'] & 0xFFFF)
    struct.pack_into('<I', data, 8, meta_dict['timestamp'] & 0xFFFFFFFF)
    for i, lv in enumerate(meta_dict['team_levels'][:6]):
        struct.pack_into('<H', data, 12 + i * 2, lv & 0xFFFF)
    struct.pack_into('<i', data, 24, meta_dict['scene_id'])
    if os.path.exists(path):
        try:
            with open(path, 'rb') as s:
                with open(path + '.bak', 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
    with open(path, 'wb') as f:
        f.write(bytes(data))


# ============================================================
# WarPC 辅助
# ============================================================

def warpc_get(seg3, char_idx, byte_offset):
    off = char_idx * WARPC_REC + byte_offset
    if off + 2 > len(seg3):
        return 0
    return struct.unpack_from('<h', seg3, off)[0]


def warpc_set(seg3, char_idx, byte_offset, value):
    off = char_idx * WARPC_REC + byte_offset
    if off + 2 > len(seg3):
        return
    struct.pack_into('<h', seg3, off, max(-32768, min(32767, value)))


# ============================================================
# GUI 主窗口
# ============================================================

class SaveEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKS 存档编辑器 v2.0 (PySide6)")
        self.resize(1400, 880)
        self.setMinimumSize(1100, 700)

        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True
        apply_godot_theme(self, self._is_dark)

        # 数据状态
        self.save_dir = None
        self.slot = 1
        self.game_state = None
        self.seg1 = None
        self.seg2 = None
        self.seg3 = None
        self.index_meta = None
        self._dirty = False
        self.warpc_count = WARPC_ORIG_CNT

        # 外部资源
        self.tkt = {}
        self.skill_names = {}
        self.item_records = {}
        self.item_names = {}
        self._mu_sprites = []
        self._icon_pixmaps = {}

        self._build_ui()
        self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        self.setStyleSheet(ThemeManager.dark_qss() if self._is_dark else ThemeManager.light_qss())
        self._update_paths()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        apply_godot_theme(self, self._is_dark)

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("打开存档目录…\tCtrl+O", self._cmd_open)
        fm.addAction("保存当前槽位\tCtrl+S", self._cmd_save)
        fm.addSeparator()
        fm.addAction("退出", self.close)
        tm = mb.addMenu("工具(&T)")
        tm.addAction("刷新数据显示", self._refresh_all)
        hm = mb.addMenu("帮助(&H)")
        hm.addAction("关于", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QPushButton("打开目录", clicked=self._cmd_open))
        toolbar.addWidget(QPushButton("保存", clicked=self._cmd_save))
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("槽位:"))
        self._slot_btns = []
        for i in range(1, 10):
            btn = QPushButton(str(i))
            btn.setFixedWidth(32)
            btn.clicked.connect(lambda checked, s=i: self._switch_slot(s))
            toolbar.addWidget(btn)
            self._slot_btns.append(btn)
        toolbar.addStretch()
        toolbar.addWidget(QPushButton("切换主题", clicked=self._toggle_theme))
        self._status_label = QLabel("请打开存档目录")
        toolbar.addWidget(self._status_label)
        main_layout.addLayout(toolbar)

        # 主 TabWidget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        self._build_overview_tab()
        self._build_team_tab()
        self._build_inventory_tab()
        self._build_event_tab()
        self._build_global_tab()
        self._build_warpc_tab()

        # 底部路径栏
        path_row = QHBoxLayout()
        self.lbl_save = QLabel("存档: 未加载")
        self.lbl_tkt = QLabel("TKT: 未加载")
        self.lbl_item = QLabel("TKItem: 未加载")
        path_row.addWidget(self.lbl_save)
        path_row.addSpacing(16)
        path_row.addWidget(self.lbl_tkt)
        path_row.addSpacing(16)
        path_row.addWidget(self.lbl_item)
        path_row.addStretch()
        main_layout.addLayout(path_row)

    def _update_paths(self):
        parent = os.path.dirname(self.save_dir.rstrip('/\\')) if self.save_dir else None
        update_path_labels([
            (self.lbl_save, self.save_dir, '存档'),
            (self.lbl_tkt, os.path.join(parent, 'TKT.dat') if parent else None, 'TKT'),
            (self.lbl_item, os.path.join(parent, 'TKItem.dat') if parent else None, 'TKItem'),
        ], self._is_dark)

    # ================================================================
    # Tab 0: 总览
    # ================================================================
    def _build_overview_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        # 索引信息
        info_grp = QGroupBox("索引文件信息 (N.sav — 28字节)")
        ig = QGridLayout(info_grp)
        self._ov_labels = {}
        for col, (key, label) in enumerate([("gold", "金钱"), ("timestamp", "存档时间"), ("scene_id", "场景ID")]):
            ig.addWidget(QLabel(label), 0, col)
            lbl = QLabel("—")
            lbl.setFont(QFont("Consolas", 10))
            ig.addWidget(lbl, 1, col)
            self._ov_labels[key] = lbl
        layout.addWidget(info_grp)

        # 队伍预览
        team_grp = QGroupBox("当前队伍")
        tl = QHBoxLayout(team_grp)
        self._ov_team = []
        for i in range(6):
            col_w = QWidget()
            cl = QVBoxLayout(col_w)
            cl.setContentsMargins(4, 4, 4, 4)
            cl.addWidget(QLabel(f"成员{i+1}"))
            name_lbl = QLabel("—")
            name_lbl.setProperty("class", "PreviewDesc")
            cl.addWidget(name_lbl)
            lv_lbl = QLabel("")
            cl.addWidget(lv_lbl)
            tl.addWidget(col_w)
            self._ov_team.append((name_lbl, lv_lbl))
        layout.addWidget(team_grp)

        # 摘要
        self._summary_text = QTextEdit()
        self._summary_text.setReadOnly(True)
        self._summary_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self._summary_text, 1)

        self.tabs.addTab(w, "总览")

    # ================================================================
    # Tab 1: 队伍与经济
    # ================================================================
    def _build_team_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        # 队伍成员
        team_grp = QGroupBox("队伍成员 (word_75688C[6], -1=空)")
        tl = QHBoxLayout(team_grp)
        self._team_edits = []
        self._team_name_labels = []
        for i in range(6):
            col_w = QWidget()
            cl = QVBoxLayout(col_w)
            cl.addWidget(QLabel(f"成员{i+1}"))
            edit = QLineEdit("-1")
            edit.setFixedWidth(60)
            edit.setFont(QFont("Consolas", 9))
            cl.addWidget(edit)
            nlbl = QLabel("")
            nlbl.setProperty("class", "ExtraPreviewText")
            cl.addWidget(nlbl)
            tl.addWidget(col_w)
            self._team_edits.append(edit)
            self._team_name_labels.append(nlbl)
        layout.addWidget(team_grp)

        # 经济
        econ_grp = QGroupBox("经济与声望")
        el = QGridLayout(econ_grp)
        self._econ_edits = {}
        econ_fields = [("gold", "金钱(上限30000)"), ("wisdom", "智慧"),
                       ("benevolence", "仁德"), ("courage", "勇气"), ("medicine", "医术(上限100)")]
        for col, (key, label) in enumerate(econ_fields):
            el.addWidget(QLabel(label), 0, col)
            edit = QLineEdit("0")
            edit.setFixedWidth(70)
            edit.setFont(QFont("Consolas", 9))
            el.addWidget(edit, 1, col)
            self._econ_edits[key] = edit
        layout.addWidget(econ_grp)

        # 战斗统计
        battle_grp = QGroupBox("战斗统计")
        bl = QGridLayout(battle_grp)
        self._battle_edits = {}
        for col, (key, off, size, label, fmt, cmt) in enumerate(SEG2_BATTLE_FIELDS):
            bl.addWidget(QLabel(label), 0, col)
            edit = QLineEdit("0")
            edit.setFixedWidth(70)
            edit.setFont(QFont("Consolas", 9))
            edit.setToolTip(cmt)
            bl.addWidget(edit, 1, col)
            self._battle_edits[key] = edit
        layout.addWidget(battle_grp)

        # 应用按钮
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("应用队伍修改", clicked=self._apply_team))
        btn_row.addWidget(QLabel("(修改后需保存到文件)"))
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self.tabs.addTab(w, "队伍")

    # ================================================================
    # Tab 2: 物品
    # ================================================================
    def _build_inventory_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("物品种类数:"))
        self._inv_count_edit = QLineEdit("0")
        self._inv_count_edit.setFixedWidth(60)
        ctrl.addWidget(self._inv_count_edit)
        ctrl.addWidget(QPushButton("刷新", clicked=self._refresh_inventory))
        ctrl.addWidget(QPushButton("应用修改", clicked=self._apply_inventory))
        ctrl.addWidget(QPushButton("新增物品", clicked=self._add_inv_item_dialog))
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # 物品表格
        self._inv_table = QTableWidget(0, 5)
        self._inv_table.setHorizontalHeaderLabels(['#', 'ID', '页面', '物品名称', '数量'])
        self._inv_table.setColumnWidth(0, 40)
        self._inv_table.setColumnWidth(1, 50)
        self._inv_table.setColumnWidth(2, 50)
        self._inv_table.setColumnWidth(3, 200)
        self._inv_table.setColumnWidth(4, 60)
        self._inv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._inv_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._inv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._inv_table.verticalHeader().setVisible(False)
        self._inv_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._inv_table, 1)

        # 编辑行
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("物品ID:"))
        self._inv_edit_id = QLineEdit()
        self._inv_edit_id.setFixedWidth(70)
        edit_row.addWidget(self._inv_edit_id)
        edit_row.addWidget(QLabel("数量:"))
        self._inv_edit_qty = QLineEdit()
        self._inv_edit_qty.setFixedWidth(60)
        edit_row.addWidget(self._inv_edit_qty)
        edit_row.addWidget(QPushButton("修改选中", clicked=self._apply_inv_edit))
        edit_row.addWidget(QPushButton("删除选中", clicked=self._delete_inv_item))
        edit_row.addStretch()
        layout.addLayout(edit_row)

        self._inv_table.itemSelectionChanged.connect(self._on_inv_select)
        self.tabs.addTab(w, "物品")

    # ================================================================
    # Tab 3: 事件系统 (核心改进)
    # ================================================================
    def _build_event_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._event_tabs = QTabWidget()
        layout.addWidget(self._event_tabs)

        # 子Tab: 开关
        self._switch_table = self._build_event_subtab(
            "事件开关", 32, SWITCH_SEMANTICS, "word_755E10, case49 设置")
        # 子Tab: 变量
        self._var_table = self._build_event_subtab(
            "事件变量", 250, VARIABLE_SEMANTICS, "word_755E80, case36/37 设置")
        # 子Tab: 标志
        self._flag_table = self._build_event_subtab(
            "事件标志", 1024, FLAG_SEMANTICS, "word_756080, sub_40CB08 设置")
        # 子Tab: 结果
        self._result_table = self._build_event_subtab(
            "事件结果", 24, RESULT_SEMANTICS, "word_755E50, case60 检查")

        # 控制栏
        ctrl = QHBoxLayout()
        self._event_nonzero_cb = QCheckBox("仅显示非零项")
        self._event_nonzero_cb.stateChanged.connect(self._filter_event_tables)
        ctrl.addWidget(self._event_nonzero_cb)
        self._event_hex_cb = QCheckBox("十六进制显示")
        self._event_hex_cb.stateChanged.connect(self._refresh_event_display)
        ctrl.addWidget(self._event_hex_cb)
        ctrl.addStretch()
        ctrl.addWidget(QPushButton("应用事件修改", clicked=self._apply_events))
        layout.addLayout(ctrl)

        self.tabs.addTab(w, "事件系统")

    def _build_event_subtab(self, title, count, semantics, source_note):
        """构建事件子Tab: 返回 QTableWidget"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel(f"来源: {source_note}  |  共 {count} 项"))

        table = QTableWidget(count, 4)
        table.setHorizontalHeaderLabels(['索引', '值', '语义标注', '十六进制'])
        table.setColumnWidth(0, 60)
        table.setColumnWidth(1, 80)
        table.setColumnWidth(2, 300)
        table.setColumnWidth(3, 80)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)

        for i in range(count):
            # 索引列 (只读)
            idx_item = QTableWidgetItem(str(i))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(i, 0, idx_item)
            # 值列 (可编辑)
            table.setItem(i, 1, QTableWidgetItem("0"))
            # 语义列 (只读)
            sem_item = QTableWidgetItem(semantics.get(i, ""))
            sem_item.setFlags(sem_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(i, 2, sem_item)
            # 十六进制列 (只读)
            hex_item = QTableWidgetItem("0x0000")
            hex_item.setFlags(hex_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(i, 3, hex_item)

        layout.addWidget(table, 1)
        self._event_tabs.addTab(w, title)
        return table

    # ================================================================
    # Tab 4: 全局状态
    # ================================================================
    def _build_global_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        self._global_edits = {}

        # 基本状态
        self._build_global_section(inner_layout, "基本状态 (SEG1)", SEG1_BASIC_FIELDS, 'seg1')
        self._build_global_section(inner_layout, "编成槽", SEG1_SLOT_FIELDS, 'seg1')
        self._build_global_section(inner_layout, "地图相关", SEG1_MAP_FIELDS, 'seg1')
        self._build_global_section(inner_layout, "事件字段", SEG1_EVENT_FIELDS, 'seg1')

        # 应用按钮
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("应用全局修改", clicked=self._apply_global))
        btn_row.addStretch()
        inner_layout.addLayout(btn_row)
        inner_layout.addStretch()

        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.tabs.addTab(w, "全局状态")

    def _build_global_section(self, parent_layout, title, fields, seg):
        grp = QGroupBox(title)
        gl = QGridLayout(grp)
        for row, (key, off, size, label, fmt, cmt) in enumerate(fields):
            gl.addWidget(QLabel(f"{label} [+0x{off:X}]"), row, 0)
            edit = QLineEdit("0")
            edit.setFixedWidth(120)
            edit.setFont(QFont("Consolas", 9))
            edit.setToolTip(cmt)
            gl.addWidget(edit, row, 1)
            gl.addWidget(QLabel(cmt), row, 2)
            self._global_edits[key] = (edit, off, size, fmt, seg)
        parent_layout.addWidget(grp)

    # ================================================================
    # Tab 5: 角色 (WarPC)
    # ================================================================
    def _build_warpc_tab(self):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # 左侧: 角色列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 搜索
        sf = QHBoxLayout()
        self._warpc_search = QLineEdit()
        self._warpc_search.setPlaceholderText("搜索角色...")
        self._warpc_search.textChanged.connect(self._refresh_warpc_list)
        sf.addWidget(self._warpc_search)
        self._warpc_filter = QComboBox()
        self._warpc_filter.addItems(["全部", "已激活", "未激活", "队伍中"])
        self._warpc_filter.currentIndexChanged.connect(self._refresh_warpc_list)
        sf.addWidget(self._warpc_filter)
        left_layout.addLayout(sf)

        self._warpc_table = QTableWidget(0, 5)
        self._warpc_table.setHorizontalHeaderLabels(['#', '名称', 'LV', '身份', 'HP'])
        self._warpc_table.setColumnWidth(0, 35)
        self._warpc_table.setColumnWidth(1, 110)
        self._warpc_table.setColumnWidth(2, 35)
        self._warpc_table.setColumnWidth(3, 50)
        self._warpc_table.setColumnWidth(4, 55)
        self._warpc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._warpc_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._warpc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._warpc_table.verticalHeader().setVisible(False)
        self._warpc_table.itemSelectionChanged.connect(self._on_warpc_select)
        left_layout.addWidget(self._warpc_table)

        # 右侧: 编辑面板
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._warpc_title = QLabel("← 选择角色编辑")
        self._warpc_title.setProperty("class", "InspectorTitle")
        right_layout.addWidget(self._warpc_title)

        self._warpc_scroll = QScrollArea()
        self._warpc_scroll.setWidgetResizable(True)
        self._warpc_edit_inner = QWidget()
        self._warpc_edit_layout = QVBoxLayout(self._warpc_edit_inner)
        self._warpc_scroll.setWidget(self._warpc_edit_inner)
        right_layout.addWidget(self._warpc_scroll, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 600])
        layout.addWidget(splitter)

        self._warpc_cur_idx = -1
        self._warpc_edit_vars = {}
        self.tabs.addTab(w, "角色")

    # ================================================================
    # 数据加载
    # ================================================================
    def _cmd_open(self):
        d = QFileDialog.getExistingDirectory(self, "选择存档目录 (含 save 子目录或 sav.N 文件)")
        if not d:
            return
        if os.path.exists(os.path.join(d, 'sav.1')):
            self.save_dir = d
        elif os.path.exists(os.path.join(d, 'save', 'sav.1')):
            self.save_dir = os.path.join(d, 'save')
        else:
            self.save_dir = d
        self._load_resources()
        self._update_paths()
        for s in range(1, 10):
            if os.path.exists(os.path.join(self.save_dir, f'sav.{s}')):
                self._switch_slot(s)
                return
        QMessageBox.warning(self, "未找到存档", f"目录中未找到 sav.N 文件:\n{self.save_dir}")

    def _load_resources(self):
        parent = os.path.dirname(self.save_dir.rstrip('/\\'))
        # TKT
        tkt_path = os.path.join(parent, 'TKT.dat')
        if os.path.exists(tkt_path):
            self.tkt = load_tkt_simple(tkt_path, skip_range=None)
        # TKSkill
        sk_path = os.path.join(parent, 'TKSkill.dat')
        if os.path.exists(sk_path):
            self.skill_names = self._parse_skill_dat(sk_path)
        # TKItem
        it_path = os.path.join(parent, 'TKItem.dat')
        if os.path.exists(it_path):
            self.item_records, self.item_names = self._parse_item_dat(it_path)
        # Mu.JVG
        mu_path = os.path.join(parent, 'Mu.JVG')
        if os.path.exists(mu_path):
            self._mu_sprites = load_mu_sprites(mu_path) or []
            self._icon_pixmaps.clear()

    def _parse_skill_dat(self, path):
        try:
            with open(path, 'rb') as f:
                dec = lzss_decompress_dat(f.read())
            names = {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec):
                    break
                name_id = struct.unpack_from('<h', dec, off)[0]
                if name_id > 0 and name_id in self.tkt:
                    names[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
            return names
        except Exception:
            return {}

    def _parse_item_dat(self, path):
        try:
            with open(path, 'rb') as f:
                dec = lzss_decompress_dat(f.read())
        except Exception:
            return {}, {}
        records = {}
        names = {}
        for i in range(600):
            off = i * 64
            if off + 10 > len(dec):
                break
            item_id = struct.unpack_from('<h', dec, off)[0]
            name_id = struct.unpack_from('<h', dec, off + 4)[0]
            tab_code = struct.unpack_from('<h', dec, off + 2)[0]
            icon = struct.unpack_from('<h', dec, off + 8)[0]
            nm = ""
            if name_id > 0 and name_id in self.tkt:
                nm = self.tkt[name_id].split('\n')[0].strip()[:25]
            elif item_id > 0:
                nm = f'物品#{item_id}'
            if item_id > 0:
                records[i] = {'item_id': item_id, 'name_id': name_id,
                              'tab_code': tab_code, 'icon': icon, 'name': nm}
                names[item_id] = nm
        return records, names

    def _switch_slot(self, slot_num):
        if self._dirty:
            if QMessageBox.question(self, "未保存", "有未保存修改，是否放弃?") != QMessageBox.Yes:
                return
        self.slot = slot_num
        self._load_current_slot()
        for i, btn in enumerate(self._slot_btns):
            btn.setStyleSheet("font-weight: bold; color: #478cbf;" if i + 1 == slot_num else "")

    def _load_current_slot(self):
        if not self.save_dir:
            return
        sav_data = os.path.join(self.save_dir, f'sav.{self.slot}')
        sav_idx = os.path.join(self.save_dir, f'{self.slot}.sav')
        if not os.path.exists(sav_data):
            self._status_label.setText(f"槽位 {self.slot}: 数据文件不存在")
            self.game_state = self.seg1 = self.seg2 = self.seg3 = None
            return
        try:
            self.game_state, self.seg1, self.seg2, self.seg3 = load_save_data(sav_data)
            self.warpc_count = len(self.seg3) // WARPC_REC
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.game_state = None
            return
        self.index_meta = load_index_file(sav_idx)
        self._dirty = False
        self._refresh_all()
        self._status_label.setText(
            f"槽位 {self.slot} | WarPC={len(self.seg3):,}B ({self.warpc_count}角色)")

    def _refresh_all(self):
        self._refresh_overview()
        self._refresh_team()
        self._refresh_inventory()
        self._refresh_events()
        self._refresh_global()
        self._refresh_warpc_list()

    # ================================================================
    # 刷新: 总览
    # ================================================================
    def _refresh_overview(self):
        if self.index_meta:
            m = self.index_meta
            self._ov_labels['gold'].setText(str(m['gold']))
            try:
                dt = datetime.datetime.fromtimestamp(m['timestamp'])
                self._ov_labels['timestamp'].setText(dt.strftime('%Y-%m-%d %H:%M:%S'))
            except Exception:
                self._ov_labels['timestamp'].setText(str(m['timestamp']))
            self._ov_labels['scene_id'].setText(str(m['scene_id']))
            for i in range(6):
                tid = m['team_ids'][i]
                lv = m['team_levels'][i]
                name = self._get_char_name(tid) if tid >= 0 else "(空)"
                self._ov_team[i][0].setText(name)
                self._ov_team[i][1].setText(f"Lv.{lv}" if tid >= 0 else "")
        else:
            for lbl in self._ov_labels.values():
                lbl.setText("—")
            for n, l in self._ov_team:
                n.setText("—"); l.setText("")

        # 摘要
        lines = []
        if self.game_state is not None:
            lines.append(f"存档目录: {self.save_dir}")
            lines.append(f"当前槽位: {self.slot}")
            fsize = os.path.getsize(os.path.join(self.save_dir, f'sav.{self.slot}'))
            lines.append(f"数据文件: sav.{self.slot} ({fsize:,} bytes)")
            lines.append(f"Frame1 (TKMat): {GAMESTATE_SIZE:,}B | Frame2: SEG1={SEG1_SIZE}B SEG2={SEG2_SIZE}B WarPC={len(self.seg3):,}B")
            lines.append(f"WarPC 角色数: {self.warpc_count} (记录大小 {WARPC_REC}B)")
            if self.warpc_count != WARPC_ORIG_CNT:
                lines.append(f"  * 非标准角色数 (原始143), 已被TKSLauncher扩展")
            if self.seg2:
                gold = struct.unpack_from('<H', self.seg2, 0x02)[0]
                team_strs = []
                for i in range(6):
                    tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
                    if tid >= 0:
                        team_strs.append(f"{self._get_char_name(tid)}(#{tid})")
                lines.append(f"金钱: {gold} | 队伍: {', '.join(team_strs) if team_strs else '(空)'}")
            lines.append("")
            lines.append("=== 全部槽位状态 ===")
            for s in range(1, 10):
                dp = os.path.join(self.save_dir, f'sav.{s}')
                ip = os.path.join(self.save_dir, f'{s}.sav')
                if os.path.exists(dp):
                    meta = load_index_file(ip)
                    if meta:
                        names = [self._get_char_name(t) for t in meta['team_ids'] if t >= 0]
                        try:
                            ts_str = datetime.datetime.fromtimestamp(meta['timestamp']).strftime('%m/%d %H:%M')
                        except Exception:
                            ts_str = "?"
                        lines.append(f"  槽{s}: {ts_str} | {', '.join(names[:3])}")
                    else:
                        lines.append(f"  槽{s}: (索引损坏)")
                else:
                    lines.append(f"  槽{s}: (空)")
        self._summary_text.setPlainText('\n'.join(lines))

    # ================================================================
    # 刷新: 队伍
    # ================================================================
    def _refresh_team(self):
        if self.seg2 is None:
            return
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
            self._team_edits[i].setText(str(tid))
            self._team_name_labels[i].setText(self._get_char_name(tid) if tid >= 0 else "(空)")
        for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
            val = struct.unpack_from('<' + fmt, self.seg2, off)[0]
            if key in self._econ_edits:
                self._econ_edits[key].setText(str(val))
        for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
            val = struct.unpack_from('<H', self.seg2, off)[0]
            if key in self._battle_edits:
                self._battle_edits[key].setText(str(val))

    # ================================================================
    # 刷新: 物品
    # ================================================================
    def _refresh_inventory(self):
        if self.seg2 is None:
            return
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        count = struct.unpack_from('<H', self.seg2, off)[0]
        self._inv_count_edit.setText(str(count))
        self._inv_table.setRowCount(0)
        off_items = SEG2_INVENTORY[0][1]
        off_types = SEG2_INVENTORY[1][1]
        off_qtys = SEG2_INVENTORY[2][1]
        for i in range(min(count, 600)):
            item_id = struct.unpack_from('<h', self.seg2, off_items + i * 2)[0]
            type_idx = struct.unpack_from('<H', self.seg2, off_types + i * 2)[0]
            qty = struct.unpack_from('<H', self.seg2, off_qtys + i * 2)[0]
            rec = self.item_records.get(type_idx, {})
            name = rec.get('name', f'物品#{item_id}') if rec else f'物品#{item_id}'
            tab = rec.get('tab_code', 0)
            page = PAGE_NAMES.get(tab, '?')
            row = self._inv_table.rowCount()
            self._inv_table.insertRow(row)
            self._inv_table.setItem(row, 0, QTableWidgetItem(str(i)))
            self._inv_table.setItem(row, 1, QTableWidgetItem(str(item_id)))
            self._inv_table.setItem(row, 2, QTableWidgetItem(page))
            self._inv_table.setItem(row, 3, QTableWidgetItem(name))
            self._inv_table.setItem(row, 4, QTableWidgetItem(str(qty)))

    # ================================================================
    # 刷新: 事件系统
    # ================================================================
    def _refresh_events(self):
        if self.seg1 is None:
            return
        # 开关 (32项, offset 0x2F8)
        for i in range(32):
            val = struct.unpack_from('<h', self.seg1, 0x2F8 + i * 2)[0]
            self._switch_table.item(i, 1).setText(str(val))
            self._switch_table.item(i, 3).setText(f"0x{val & 0xFFFF:04X}")
        # 变量 (250项, offset 0x368)
        for i in range(250):
            off = 0x368 + i * 2
            if off + 2 <= len(self.seg1):
                val = struct.unpack_from('<h', self.seg1, off)[0]
            else:
                val = 0
            self._var_table.item(i, 1).setText(str(val))
            self._var_table.item(i, 3).setText(f"0x{val & 0xFFFF:04X}")
        # 标志 (1024项, offset 0x568)
        for i in range(1024):
            off = 0x568 + i * 2
            if off + 2 <= len(self.seg1):
                val = struct.unpack_from('<h', self.seg1, off)[0]
            else:
                val = 0
            self._flag_table.item(i, 1).setText(str(val))
            self._flag_table.item(i, 3).setText(f"0x{val & 0xFFFF:04X}")
        # 结果 (24项, offset 0x338)
        for i in range(24):
            val = struct.unpack_from('<h', self.seg1, 0x338 + i * 2)[0]
            self._result_table.item(i, 1).setText(str(val))
            self._result_table.item(i, 3).setText(f"0x{val & 0xFFFF:04X}")
        self._filter_event_tables()

    def _refresh_event_display(self):
        """十六进制/十进制切换时刷新显示."""
        self._filter_event_tables()

    def _filter_event_tables(self):
        """过滤事件表格 (仅非零)."""
        nonzero_only = self._event_nonzero_cb.isChecked()
        for table in [self._switch_table, self._var_table, self._flag_table, self._result_table]:
            for row in range(table.rowCount()):
                val_item = table.item(row, 1)
                if val_item:
                    try:
                        val = int(val_item.text())
                    except ValueError:
                        val = 0
                    table.setRowHidden(row, nonzero_only and val == 0)

    # ================================================================
    # 刷新: 全局
    # ================================================================
    def _refresh_global(self):
        if self.seg1 is None:
            return
        for key, (edit, off, size, fmt, seg) in self._global_edits.items():
            data = self.seg1 if seg == 'seg1' else self.seg2
            if data is None or off + size > len(data):
                continue
            if fmt == 'big5':
                edit.setText(self._decode_big5(data[off:off + size]))
            else:
                edit.setText(str(struct.unpack_from(fmt, data, off)[0]))

    # ================================================================
    # 刷新: 角色列表
    # ================================================================
    def _refresh_warpc_list(self):
        self._warpc_table.setRowCount(0)
        if self.seg3 is None:
            return
        team_set = set()
        if self.seg2 is not None:
            for i in range(6):
                tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
                if tid >= 0:
                    team_set.add(tid)
        search = self._warpc_search.text().strip().lower()
        filt = self._warpc_filter.currentText()

        for i in range(self.warpc_count):
            name_id = warpc_get(self.seg3, i, 0)
            lv = warpc_get(self.seg3, i, 4)
            role = warpc_get(self.seg3, i, 6)
            hp = warpc_get(self.seg3, i, 10)
            name = self.tkt.get(name_id, f"ID:{name_id}") if name_id else ""
            in_team = i in team_set

            if filt == "未激活" and role != -1:
                continue
            if filt == "已激活" and role != 0:
                continue
            if filt == "队伍中" and not in_team:
                continue
            if search and search not in str(i) and search not in name.lower():
                continue

            role_str = "队伍" if in_team else ("未激活" if role == -1 else "已激活")
            row = self._warpc_table.rowCount()
            self._warpc_table.insertRow(row)
            self._warpc_table.setItem(row, 0, QTableWidgetItem(str(i)))
            ni = QTableWidgetItem(name)
            if in_team:
                ni.setForeground(QColor("#228B22"))
            elif role == -1:
                ni.setForeground(QColor("#2266CC"))
            else:
                ni.setForeground(QColor("#CC3333"))
            self._warpc_table.setItem(row, 1, ni)
            self._warpc_table.setItem(row, 2, QTableWidgetItem(str(lv)))
            self._warpc_table.setItem(row, 3, QTableWidgetItem(role_str))
            self._warpc_table.setItem(row, 4, QTableWidgetItem(str(hp)))

    def _on_warpc_select(self):
        sel = self._warpc_table.selectedItems()
        if not sel:
            return
        idx = int(self._warpc_table.item(sel[0].row(), 0).text())
        self._warpc_cur_idx = idx
        self._build_warpc_editor(idx)

    def _build_warpc_editor(self, idx):
        """构建角色编辑面板."""
        # 清除旧内容
        while self._warpc_edit_layout.count():
            item = self._warpc_edit_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._warpc_edit_vars = {}
        if self.seg3 is None or idx < 0:
            return

        name_id = warpc_get(self.seg3, idx, 0)
        name = self.tkt.get(name_id, f"ID:{name_id}")
        self._warpc_title.setText(f"角色 #{idx} - {name}")

        # 各区段
        self._warpc_section("身份信息", WARPC_IDENTITY, idx)
        self._warpc_section("HP / MP", WARPC_HPMP, idx)
        self._warpc_stat_section(idx)
        self._warpc_section("角色五维", WARPC_CHAR_ATTR, idx)
        self._warpc_section("装备", WARPC_EQUIP, idx)
        self._warpc_section("成长率", WARPC_GROWTH, idx)
        self._warpc_section("战后奖励/掉落", WARPC_BATTLE_REWARD + WARPC_DROP, idx)

        # 应用按钮
        btn = QPushButton("应用角色修改")
        btn.clicked.connect(self._apply_warpc)
        self._warpc_edit_layout.addWidget(btn)
        self._warpc_edit_layout.addStretch()

    def _warpc_section(self, title, fields, idx):
        grp = QGroupBox(title)
        gl = QGridLayout(grp)
        cols = 4
        for fi, item in enumerate(fields):
            fn, fo, label = item[0], item[1], item[2]
            cmt = item[3] if len(item) > 3 else ""
            r, c = divmod(fi, cols)
            gl.addWidget(QLabel(f"{label}[{fo}]"), r * 2, c)
            val = warpc_get(self.seg3, idx, fo)
            edit = QLineEdit(str(val))
            edit.setFixedWidth(80)
            edit.setFont(QFont("Consolas", 9))
            if cmt:
                edit.setToolTip(cmt)
            gl.addWidget(edit, r * 2 + 1, c)
            self._warpc_edit_vars[fn] = (edit, fo)
        self._warpc_edit_layout.addWidget(grp)

    def _warpc_stat_section(self, idx):
        grp = QGroupBox("八属性 (基础/当前)")
        gl = QGridLayout(grp)
        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_OFFSETS)):
            gl.addWidget(QLabel(name), 0, ci)
            base_val = warpc_get(self.seg3, idx, bo)
            cur_val = warpc_get(self.seg3, idx, bo + 2)
            eb = QLineEdit(str(base_val))
            eb.setFixedWidth(50)
            eb.setFont(QFont("Consolas", 9))
            ec = QLineEdit(str(cur_val))
            ec.setFixedWidth(50)
            ec.setFont(QFont("Consolas", 9))
            gl.addWidget(QLabel("基"), 1, ci)
            gl.addWidget(eb, 2, ci)
            gl.addWidget(QLabel("当"), 3, ci)
            gl.addWidget(ec, 4, ci)
            self._warpc_edit_vars[f'{short}_base'] = (eb, bo)
            self._warpc_edit_vars[f'{short}_cur'] = (ec, bo + 2)
        self._warpc_edit_layout.addWidget(grp)

    # ================================================================
    # 应用修改
    # ================================================================
    def _apply_team(self):
        if self.seg2 is None:
            return
        try:
            for i in range(6):
                v = int(self._team_edits[i].text())
                struct.pack_into('<h', self.seg2, 0x0C + i * 2, v)
            for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
                if key in self._econ_edits:
                    v = int(self._econ_edits[key].text())
                    mask = 0xFFFF if size == 2 else 0xFF
                    struct.pack_into('<' + fmt, self.seg2, off, v & mask)
            for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
                if key in self._battle_edits:
                    v = int(self._battle_edits[key].text())
                    struct.pack_into('<H', self.seg2, off, v & 0xFFFF)
            self._dirty = True
            self._sync_index_from_seg2()
            self._status_label.setText(f"槽位 {self.slot}: 队伍数据已修改 (未保存)")
        except ValueError as e:
            QMessageBox.critical(self, "输入错误", str(e))

    def _apply_inventory(self):
        if self.seg2 is None:
            return
        try:
            count = int(self._inv_count_edit.text())
            struct.pack_into('<H', self.seg2, SEG2_INV_COUNT[1], count & 0xFFFF)
            self._dirty = True
            self._refresh_inventory()
        except ValueError as e:
            QMessageBox.critical(self, "输入错误", str(e))

    def _apply_events(self):
        """从事件表格中读取值写回 seg1."""
        if self.seg1 is None:
            return
        try:
            # 开关
            for i in range(32):
                val = int(self._switch_table.item(i, 1).text())
                struct.pack_into('<h', self.seg1, 0x2F8 + i * 2, val)
            # 变量
            for i in range(250):
                val = int(self._var_table.item(i, 1).text())
                off = 0x368 + i * 2
                if off + 2 <= len(self.seg1):
                    struct.pack_into('<h', self.seg1, off, val)
            # 标志
            for i in range(1024):
                val = int(self._flag_table.item(i, 1).text())
                off = 0x568 + i * 2
                if off + 2 <= len(self.seg1):
                    struct.pack_into('<h', self.seg1, off, val)
            # 结果
            for i in range(24):
                val = int(self._result_table.item(i, 1).text())
                struct.pack_into('<h', self.seg1, 0x338 + i * 2, val)
            self._dirty = True
            self._status_label.setText(f"槽位 {self.slot}: 事件数据已修改 (未保存)")
        except ValueError as e:
            QMessageBox.critical(self, "输入错误", str(e))

    def _apply_global(self):
        if self.seg1 is None:
            return
        try:
            for key, (edit, off, size, fmt, seg) in self._global_edits.items():
                data = self.seg1 if seg == 'seg1' else self.seg2
                if data is None:
                    continue
                txt = edit.text()
                if fmt == 'big5':
                    data[off:off + size] = self._encode_big5(txt, size)
                else:
                    struct.pack_into(fmt, data, off, int(txt))
            self._dirty = True
            self._status_label.setText(f"槽位 {self.slot}: 全局状态已修改 (未保存)")
        except (ValueError, struct.error) as e:
            QMessageBox.critical(self, "输入错误", str(e))

    def _apply_warpc(self):
        if self.seg3 is None or self._warpc_cur_idx < 0:
            return
        idx = self._warpc_cur_idx
        try:
            for fn, (edit, fo) in self._warpc_edit_vars.items():
                v = int(edit.text())
                warpc_set(self.seg3, idx, fo, v)
            self._dirty = True
            self._refresh_warpc_list()
            self._status_label.setText(f"角色 #{idx} 已修改 (未保存)")
        except ValueError as e:
            QMessageBox.critical(self, "输入错误", str(e))

    # ================================================================
    # 物品操作
    # ================================================================
    def _on_inv_select(self):
        sel = self._inv_table.selectedItems()
        if sel:
            row = sel[0].row()
            self._inv_edit_id.setText(self._inv_table.item(row, 1).text())
            self._inv_edit_qty.setText(self._inv_table.item(row, 4).text())

    def _apply_inv_edit(self):
        sel = self._inv_table.selectedItems()
        if not sel or self.seg2 is None:
            return
        row = sel[0].row()
        idx = int(self._inv_table.item(row, 0).text())
        try:
            new_id = int(self._inv_edit_id.text())
            new_qty = int(self._inv_edit_qty.text())
        except ValueError:
            QMessageBox.critical(self, "输入错误", "请输入有效数字")
            return
        new_type = self._find_item_idx_by_id(new_id)
        struct.pack_into('<h', self.seg2, SEG2_INVENTORY[0][1] + idx * 2, new_id)
        struct.pack_into('<H', self.seg2, SEG2_INVENTORY[1][1] + idx * 2, new_type)
        struct.pack_into('<H', self.seg2, SEG2_INVENTORY[2][1] + idx * 2, new_qty)
        self._dirty = True
        self._refresh_inventory()

    def _find_item_idx_by_id(self, item_id):
        for arr_idx, rec in self.item_records.items():
            if rec.get('item_id') == item_id:
                return arr_idx
        return 0

    def _delete_inv_item(self):
        sel = self._inv_table.selectedItems()
        if not sel or self.seg2 is None:
            return
        row = sel[0].row()
        idx = int(self._inv_table.item(row, 0).text())
        count_off = SEG2_INV_COUNT[1]
        arr_offs = [f[1] for f in SEG2_INVENTORY]
        count = struct.unpack_from('<H', self.seg2, count_off)[0]
        if idx >= count:
            return
        for i in range(idx, count - 1):
            for arr_off in arr_offs:
                v = struct.unpack_from('<H', self.seg2, arr_off + (i + 1) * 2)[0]
                struct.pack_into('<H', self.seg2, arr_off + i * 2, v)
        for arr_off in arr_offs:
            struct.pack_into('<H', self.seg2, arr_off + (count - 1) * 2, 0)
        struct.pack_into('<H', self.seg2, count_off, count - 1)
        self._dirty = True
        self._refresh_inventory()

    def _add_inv_item_dialog(self):
        if not self.item_records:
            QMessageBox.information(self, "提示", "请先加载存档目录")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("新增物品")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)

        # 搜索
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        search_edit = QLineEdit()
        sf.addWidget(search_edit)
        layout.addLayout(sf)

        # 列表
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(['ID', '名称', '页面'])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)

        # 数量
        qty_row = QHBoxLayout()
        qty_row.addWidget(QLabel("数量:"))
        qty_edit = QLineEdit("1")
        qty_edit.setFixedWidth(80)
        qty_row.addWidget(qty_edit)
        qty_row.addStretch()
        qty_row.addWidget(QPushButton("取消", clicked=dlg.reject))
        ok_btn = QPushButton("添加")
        qty_row.addWidget(ok_btn)
        layout.addLayout(qty_row)

        selected = {'idx': None, 'item_id': None}

        def refresh_list():
            table.setRowCount(0)
            q = search_edit.text().strip().lower()
            for arr_idx, rec in self.item_records.items():
                name = rec.get('name', '')
                item_id = rec.get('item_id', 0)
                if not name:
                    continue
                if q and q not in f"{arr_idx} {item_id} {name}".lower():
                    continue
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(str(item_id)))
                table.setItem(row, 1, QTableWidgetItem(name))
                table.setItem(row, 2, QTableWidgetItem(PAGE_NAMES.get(rec.get('tab_code', 0), '?')))

        def on_select():
            sel = table.selectedItems()
            if sel:
                selected['item_id'] = int(table.item(sel[0].row(), 0).text())

        def do_add():
            if selected['item_id'] is None:
                QMessageBox.warning(dlg, "提示", "请选择物品")
                return
            try:
                qty = int(qty_edit.text())
                if qty <= 0 or qty > 30000:
                    raise ValueError
            except ValueError:
                QMessageBox.critical(dlg, "输入错误", "数量 1-30000")
                return
            type_idx = self._find_item_idx_by_id(selected['item_id'])
            self._add_inv_item(type_idx, selected['item_id'], qty)
            dlg.accept()

        search_edit.textChanged.connect(lambda: refresh_list())
        table.itemSelectionChanged.connect(on_select)
        ok_btn.clicked.connect(do_add)
        refresh_list()
        dlg.exec()

    def _add_inv_item(self, type_idx, item_id, qty):
        if self.seg2 is None:
            return
        count_off = SEG2_INV_COUNT[1]
        off_items = SEG2_INVENTORY[0][1]
        off_types = SEG2_INVENTORY[1][1]
        off_qtys = SEG2_INVENTORY[2][1]
        count = struct.unpack_from('<H', self.seg2, count_off)[0]
        # 检查是否已存在
        for i in range(min(count, 600)):
            existing_type = struct.unpack_from('<H', self.seg2, off_types + i * 2)[0]
            if existing_type == type_idx:
                old_qty = struct.unpack_from('<H', self.seg2, off_qtys + i * 2)[0]
                new_qty = min(old_qty + qty, 30000)
                struct.pack_into('<H', self.seg2, off_qtys + i * 2, new_qty)
                self._dirty = True
                self._refresh_inventory()
                return
        if count >= 600:
            QMessageBox.warning(self, "物品已满", "物品已达上限 600 种")
            return
        struct.pack_into('<h', self.seg2, off_items + count * 2, item_id)
        struct.pack_into('<H', self.seg2, off_types + count * 2, type_idx)
        struct.pack_into('<H', self.seg2, off_qtys + count * 2, qty)
        struct.pack_into('<H', self.seg2, count_off, count + 1)
        self._dirty = True
        self._refresh_inventory()

    # ================================================================
    # 保存
    # ================================================================
    def _cmd_save(self):
        if self.game_state is None:
            QMessageBox.warning(self, "无数据", "请先加载存档")
            return
        if QMessageBox.question(self, "确认保存",
                f"将覆盖 sav.{self.slot} 和 {self.slot}.sav, 继续?") != QMessageBox.Yes:
            return
        try:
            sav_data = os.path.join(self.save_dir, f'sav.{self.slot}')
            sav_idx = os.path.join(self.save_dir, f'{self.slot}.sav')
            save_save_data(sav_data, self.game_state, self.seg1, self.seg2, self.seg3)
            self._sync_index_from_seg2()
            if self.index_meta:
                save_index_file(sav_idx, self.index_meta)
            self._dirty = False
            self._status_label.setText(f"槽位 {self.slot}: 保存成功!")
            QMessageBox.information(self, "保存成功", f"存档已保存到 sav.{self.slot}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _sync_index_from_seg2(self):
        if self.seg2 is None:
            return
        if self.index_meta is None:
            self.index_meta = {'team_ids': [0xFF] * 6, 'gold': 0,
                               'timestamp': int(time.time()), 'team_levels': [0] * 6, 'scene_id': -1}
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
            self.index_meta['team_ids'][i] = tid & 0xFF if tid >= 0 else 0xFF
        self.index_meta['gold'] = struct.unpack_from('<H', self.seg2, 0x02)[0]
        self.index_meta['timestamp'] = int(time.time())
        if self.seg3 is not None:
            for i in range(6):
                tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
                if 0 <= tid < self.warpc_count:
                    lv = warpc_get(self.seg3, tid, 4)
                    self.index_meta['team_levels'][i] = lv & 0xFFFF
                else:
                    self.index_meta['team_levels'][i] = 0
        if self.seg1 is not None:
            self.index_meta['scene_id'] = struct.unpack_from('<i', self.seg1, 0x40)[0]

    # ================================================================
    # 辅助
    # ================================================================
    def _get_char_name(self, char_idx):
        if self.seg3 is None or char_idx < 0 or char_idx >= self.warpc_count:
            return f"#{char_idx}"
        name_id = warpc_get(self.seg3, char_idx, 0)
        if name_id and name_id in self.tkt:
            return self.tkt[name_id]
        return f"#{char_idx}"

    def _decode_big5(self, raw):
        null_idx = raw.find(b'\x00')
        if null_idx >= 0:
            raw = raw[:null_idx]
        if not raw:
            return ""
        try:
            return raw.decode('big5')
        except UnicodeDecodeError:
            return raw.hex()

    def _encode_big5(self, text, size):
        text = text.strip()
        if not text:
            return b'\x00' * size
        try:
            import zhconv
            text = zhconv.convert(text, 'zh-hant')
        except ImportError:
            pass
        try:
            b = text.encode('big5')
        except UnicodeEncodeError:
            b = text.encode('big5', errors='replace')
        return b[:size - 1].ljust(size, b'\x00')[:size]

    def _show_about(self):
        QMessageBox.about(self, "关于",
            "TKS 存档编辑器 v2.0 (PySide6)\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "存档格式: 2帧LZSS压缩\n"
            "  Frame1: 2304000B TKMat实体表\n"
            "  Frame2: 3432B全局 + 5768B背包 + WarPC角色\n\n"
            "核心逆向函数:\n"
            "  sub_410ED4  SaveTKMat\n"
            "  sub_41103C  LoadTKMat\n"
            "  sub_41CE10  SaveIndexWrite\n"
            "  sub_40EBD4  事件脚本处理器\n"
            "  sub_40CB08/40CB4C  标志设置/累加")

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()


# ============================================================
# 入口
# ============================================================

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _t = QTranslator()
    _t.load("qtbase_zh_CN", os.path.join(os.path.dirname(__file__), '..', 'editor_utils'))
    app.installTranslator(_t)
    editor = SaveEditorApp()
    editor.show()
    sys.exit(app.exec())
