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

import struct, os, sys, time, datetime, csv

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QMessageBox, QFileDialog, QDialog, QGridLayout, QFrame, QScrollArea,
    QTabWidget, QTextEdit, QSpinBox, QGroupBox, QFormLayout, QInputDialog,
)
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator, QPainter
from PySide6.QtCore import Qt, QTranslator, QSize

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.window_theme import apply_godot_theme
from editor_utils.ui_helpers import update_path_labels, confirm_close, make_fake_input
from editor_utils.lzss import lzss_decompress_save, lzss_compress_save, lzss_decompress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.dock_components import DockHeader
from editor_utils.kon_name_resolver import KonNameResolver
from editor_utils.picker_dialogs import ItemPickerDialog


# ============================================================
# 数据段定义
# 常量 (来自逆向工程 — 每个值附带反编译代码证据)
# ============================================================

# Frame 1: TKMat 游戏实体表 (dword_51AF40)
GAMESTATE_SIZE = 2304000  # 6000 entities × 384 bytes

# Frame 2 三段布局 (来源: 410ED4.c:25-28, 41103C.c:28,34-36)
SEG1_SIZE = 3432   # Block A: 脚本全局变量 (unk_755B18)
SEG2_SIZE = 5768   # Block B: 背包/队伍/金币 (unk_756880)
WARPC_OFFSET = 9200  # = SEG1_SIZE + SEG2_SIZE
WARPC_REC = 1054   # 每条WarPC记录字节数

# .sav 索引文件 (28字节)
SAV_META_SIZE = 28

# ============================================================
# 段1 (0x755B18, 3432B) 已知字段
# ============================================================
SEG1_BASIC_FIELDS = [
    ("map_id",       0x40, 4, "当前地图ID",     "I",  "dword_755B58, sub_40C044地图切换"),
    ("current_char", 0x44, 4, "当前角色ID",     "I",  "dword_755B5C, sub_40C7CC SetPlayer事件"),
    ("game_active",  0x48, 4, "游戏激活标志",    "I",
     "dword_755B60, sub_41103C读档后置1, opcode31(PlayerAct)控制。为0时sub_4081F8/4084E0/408E5C全部跳过"),
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
    ("battle_flags", 0x168, 4, "遭遇战旗标",     "I",
     "dword_755C80 位域(sub_41F784 按队伍装备 word_77CC06 OR 聚合)。bit0=遇敌冷却+30%(rand140) bit1=遇敌冷却+50%(rand200) bit2=禁止遇敌(sub_4084E0 检查&4跳过) bit3/5=战斗数值修正(sub_431E70) bit4/5=战斗修正(sub_43B7FC)。注: bit3 旧注'反击'未获代码证实"),
    ("map_timer",    0x82C, 2, "地图计时器",     "H",  "word_756344"),
    ("door_unlock",  0x82E, 2, "开门标志",       "H",  "word_756346"),
]

SEG1_EVENT_FIELDS = [
    ("comp_flag",    0x336, 2, "同伴选人模式",    "H",
     "word_755E4E = switch[31] 别名(switch基址0x2F8+31×2=0x336)。sub_420844 战斗判定读取: !word_755E4E 时触发某自动分支(sub_41DFDC)。对应 TKD 注释 '讓主角選人' (脚本交互选人模式)。注意: 与事件系统 tab 的 switch[31] 是同一内存, 两边编辑不同步"),
    ("minigame_rst", 0x366, 2, "小游戏分数(瞬态)", "H",
     "word_755E7E = result[23] 别名(result基址0x338+23×2=0x366)。opcode64 MiniGame(sub_40E97C)写入: a1(1-7)选7种小游戏之一, 全部把本次分数 v8 写入此同一槽(每次覆盖)。分数当场与阈值 a2 比较(40E97C.c:64-70)返回 1/0 给 case64 跳转, 引擎不回读。存档值为上次残留, 编辑基本无游戏效果"),
    ("last_acq",     0x566, 2, "最近获得量(瞬态)", "H",
     "word_75607E = var[255] 别名(var基址0x368+255×2=0x566)。sub_40CE30(opcode40)写入: 金币获取时=本次数量(a2), 物品获取时=物品属性 word_77CBCE[32*idx]。写后由 opcode5 消息(sub_40B1B4)用于'获得'提示显示(经文本格式化case21读var槽)。引擎仅写不读, 存档值为上次拾取残留, 编辑无游戏效果"),
]

# 数组字段定义
SEG1_ARRAYS = [
    ("switches",     0x2F8, 32,  2, "事件开关",      "word_755E10[32], case49"),
    ("results",      0x338, 24,  2, "事件结果",      "word_755E50[24], case60"),
    ("variables",    0x368, 250, 2, "事件变量",      "word_755E80, case36-39。上限因操作码而异: case36 SetVar >0xF9 (max 249); case37 Random / case38 SetFlagVar / case39 AddFlagVar >=0x100 (max 255)。存档预留256槽(0x368-0x567), 编辑器编辑0-249, 槽255=last_acq别名"),
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
# 事件语义标注 (基于反编译+TKD.dat脚本+存档三方交叉验证)
# ============================================================
# 分析来源: TKS.exe sub_40EBD4(脚本VM), TKD.dat(Big5注释), sav.1/sav.2(实际存档)
# 详见: 事件系统语义分析.md

# ── 事件开关: word_755E10[32], case 49 (SetSwitch) 设置 ──
# 读取: sub_408E5C (对话/事件激活检查), 检查 switch[0] 非零才允许触发
# 语义: 全局功能控制开关, 与 Flags 的"持久剧情进度"不同
SWITCH_SEMANTICS = {
    0:  "【主开关】游戏对话/事件系统启用 — 几乎所有DEFINE开头都调SetSwitch(0,1)",
    31: "脚本交互模式切换 — 配合PlayerAct(1)使用, TKD注释'讓主角選人'",
}
# 填充未确定项
for _i in range(32):
    if _i not in SWITCH_SEMANTICS:
        SWITCH_SEMANTICS[_i] = f"开关#{_i} (未观察到使用)"

# ── 事件变量: word_755E80[250], case 36 (SetVar) / case 37 (Random) 设置 ──
# 读取: case 38 (SetFlagVar) / case 39 (AddFlagVar) — 作为flag值来源
# 语义: 脚本运行时临时工作区。Random→变量→SetFlagVar→标志 的值传递桥梁
# TKD统计: SetVar从未直接调用; Random仅有 Random(0,0,4)=15次, Random(0,0,1)=2次
VARIABLE_SEMANTICS = {
    0:  "【主随机槽】Random(0,0,4)输出 — 用于随机NPC位置/事件分支, 然后SetFlagVar转存到flag",
}
# 填充未确定项 (SetVar极少直接使用, 所有17次Random都写入var[0])
for _i in range(250):
    if _i not in VARIABLE_SEMANTICS:
        VARIABLE_SEMANTICS[_i] = f"变量#{_i} (TKD脚本中未观察到使用)"

# ── 事件标志: word_756080[1024], case 32(SetFlag)/33(AddFlag)/38(SetFlagVar)/39(AddFlagVar) 设置 ──
# 检查: case 61 (CheckFlag) → sub_40E40C, 支持6种比较: <(-2) <=(-1) ==(0) >=(1) >(2) !=(3)
# 语义: 持久化剧情进度追踪, 是事件系统核心。值域: 0=未触发 1=进行中 2+=完成/分支结果
FLAG_SEMANTICS = {}

# === 三国武将角色事件标志 (flags 7-13, 1001-1006, 501-507) ===
_CHAR_FLAGS = {
    7:   "關羽 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    8:   "張飛 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    9:   "黃忠 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1) TKD注释'完成黃忠事件'",
    10:  "馬超 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    11:  "趙雲 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    12:  "馬良 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    13:  "找人计数 — 0=一開始沒有人 1-6=找到N個人 (值域0-6, 6种比较)",
    1001: "陸遜 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    1002: "甘寧 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    1003: "太史慈 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1) TKD注释'完成太史慈事件'",
    1004: "魯肅 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    1005: "呂蒙 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    1006: "黃蓋 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1)",
    501: "檢查回來人數 — 0=沒有人 1-6=N人 (值域0-6, 6种比较)",
    502: "夏侯惇 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1 值域1-2)",
    503: "張遼 — 角色事件 TKD注释'完成張遼事件'/'未完成張遼事件' (值域0-2)",
    504: "典韋 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1 值域1-2)",
    505: "賈詡 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1 值域1-2)",
    506: "荀彧 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1 值域1-2)",
    507: "許褚 — 角色加入/事件完成 (SetFlag=1, CheckFlag>=1 值域1-2)",
}

# === 主线剧情阶段标志 ===
_STORY_FLAGS = {
    142: "諸葛亮主线 — 7阶段剧情 (值域0-6, 594次引用, CheckFlag<6/==N) TKD注释'諸葛亮'",
    143: "周瑜主线 — 7阶段剧情 (值域0-6, 594次引用, CheckFlag<6/==N) TKD注释'周瑜'",
    144: "司馬懿主线 — 7阶段剧情 (值域0-6, 594次引用, CheckFlag<6/==N) TKD注释'司馬懿'",
    145: "三主线完成计数 — CheckFlag(==3)配合142/143/144, AddFlag(1)跨实体673-4348 (6个DEFINE)",
    146: "九鼎收集 — 找到七個以上的鼎 (CheckFlag>=3/>=7, 存档1=1存档2=1)",
    121: "曹操歸來 — 0=曹操未回來 1=已回來 (CheckFlag==0/>=1)",
    301: "華佗終章 — 完成三人及麻沸散事件 (CheckFlag>=4)",
    302: "華佗进度 — 1=第一次遇華佗 2=第二次 3=第三次(找藥材) (值域0-3, SetFlag=1/2/3)",
    303: "夏侯惇对话进度 — AddFlag(1)阶段递进 SetFlag(2→5) 实体1114-1116 '與夏侯惇對話' (3个DEFINE)",
}

# === 计数/统计类标志 (值域1-6, 通常只做==比较) ===
_COUNT_FLAGS = {
    # flags 100-105: 跨9个实体(666-674)的计数模式, 每个实体AddFlag/SetFlag
    # DEFINE头部均为"1 #Define"系列, 无场景注释 — 推测为通用角色/队伍计数
    100: "计数A — AddFlag(1)模式跨9个实体(666-674) (132次引用, CheckFlag==1~6)",
    101: "计数B — AddFlag(1)模式跨9个实体(666-674) (24次引用, CheckFlag==1~6)",
    102: "二值A — SetFlag(1)模式跨9个实体(666-674) (42次引用, CheckFlag==1)",
    103: "金錢計數A — CheckFlag==1~6 TKD注释'錢' 实体2390-2391 (132次引用)",
    104: "官名計數A — CheckFlag==1~6 TKD注释'官名' 实体2390-2391 (24次引用, 存档2=1)",
    105: "二值B — SetFlag(0/1)跨9个实体(2390-2391+) (39次引用, CheckFlag==1)",
    106: "配对计数 — CheckFlag(==0/>=1)与flag[105]配对 实体2390 'XX加入事件' (存档2=1)",
    # flags 110-119: 跨实体4283-4293的事件组, 头DEFINE有场景注释
    110: "事件组A·阶段 — CheckFlag(>=0/==0/==1) 实体4283场景'XX加入事件' (3个DEFINE)",
    111: "官名計數B — CheckFlag==1~6 TKD注释'官名..N人' (24次引用)",
    112: "事件组A·旗1 — SetFlag(0/1) 实体4283-4288 'XX加入事件' (42次引用, CheckFlag==1)",
    113: "金錢計數B — CheckFlag==1~6 TKD注释'錢..N人' (132次引用)",
    114: "事件组A·旗2 — SetFlag(1→2) 实体4283-4288 'XX加入事件' (3次引用)",
    115: "事件组A·旗3 — SetFlag(1→2) 实体4283-4290 'XX加入事件' (3次引用)",
    116: "事件组A·旗4 — SetFlag(1→2) 实体4283-4289 'XX加入事件' (3次引用)",
    117: "事件组A·旗5 — SetFlag(1→2) 实体4283-4291 'XX加入事件' (3次引用)",
    118: "事件组A·旗6 — SetFlag(1→2) 实体4283-4293 'XX加入事件' (3次引用)",
    119: "事件组A·旗7 — SetFlag(1→2) 实体4283-4292 'XX加入事件' (3次引用)",
    # flags 130-139: 跨实体666-680的事件组, 头DEFINE场景"一般對話"
    130: "事件组B·阶段 — CheckFlag(>=0/==0/==1) 实体672场景'一般對話' (3个DEFINE)",
    134: "事件组B·旗1 — SetFlag(1→2) 实体666-680 '一般對話' (3次引用)",
    135: "事件组B·旗2 — SetFlag(1→2) 实体667-680 '一般對話' (3次引用)",
    136: "事件组B·旗3 — SetFlag(1→2) 实体669-680 '一般對話' (3次引用)",
    137: "事件组B·旗4 — SetFlag(1→2) 实体666-680 '一般對話' (3次引用)",
    138: "事件组B·旗5 — SetFlag(1→2) 实体667-680 '一般對話' (3次引用)",
    139: "事件组B·旗6 — SetFlag(1→2) 实体668-680 '一般對話' (3次引用)",
    1011: "檢查回來人數B — 1-6人 (36次引用, 存档2=1)",
}

# === 多阶段任务标志 ===
_QUEST_FLAGS = {
    1012: "周瑜任务 — 找到焦尾琴 (SetFlag=1/2/10, CheckFlag!=/==, 值域0-10) TKD注释'講過焦尾琴'",
    1013: "馬良任务 — 多阶段递进 (SetFlag=1-5, CheckFlag<=/==, 值域1-5)",
    1016: "解良任务 — 第二次對話後未離開 (SetFlag=1-16, CheckFlag==/!=, 多阶段) TKD注释'第二次對話'",
    1018: "孟獲任务 — 多阶段递进 (SetFlag=3/4/7/9/10, 值域3-10) TKD注释'孟獲'",
    1021: "太史慈任务 — 多阶段 (SetFlag=1/3/10/11, CheckFlag>=1) TKD注释'太史慈'",
    1022: "多阶段任务 — SetFlag(1/2/10/11) 跨实体1148-2069 5种比较 (10个DEFINE)",
    1023: "多阶段任务 — SetFlag(1/2) CheckFlag(==0/==1/==2) 跨实体2035-2372 (8个DEFINE)",
    1014: "多阶段任务 — SetFlag(2/3/6) CheckFlag(==1/==3/==5) 跨实体2230-2312 (3个DEFINE)",
}

# === 通用阶段控制标志 ===
_GENERIC_FLAGS = {
    # flags 305-312: 跨多个实体的事件组, CheckFlag/AddFlag阶段控制
    305: "阶段计数A — AddFlag(1)跨5个实体(1179-1183+) (5个DEFINE, CheckFlag==4)",
    306: "阶段计数B·重置 — SetFlag(0)清零+AddFlag(1) 实体4389 '2-6 #Define'系列 (136次引用)",
    307: "阶段计数B·累加 — AddFlag(1)累加器 实体4389 '2-6 #Define'系列 (64次引用, 配合306)",
    309: "阶段计数C — AddFlag(1)/CheckFlag(==4/==5) 跨实体1230-4447 (10个DEFINE)",
    310: "激活开关 — CheckFlag(1)→SetFlag(1) 实体1242-1250 (5个DEFINE, 配合309)",
    312: "二阶段旗 — SetFlag(1→2) 实体352/4384-4388 (4个DEFINE, CheckFlag==2)",
    343: "通用阶段 — 4阶段 (值域0-4, 282次引用, CheckFlag==0-4)",
    344: "通用阶段+Random — 5阶段 SetFlagVar(0) Random→flag 实体672 '一般對話' (36次引用)",
    346: "通用阶段 — 5阶段 (值域0-4, 18次引用, CheckFlag==0-4)",
    347: "通用阶段 — 5阶段 (值域0-4, 18次引用, CheckFlag==0-4)",
}

# === 特殊用途标志 ===
_SPECIAL_FLAGS = {
    999: "【随机结果槽】Random→SetFlagVar专用 (值域0-4, 存档1=3存档2=3)",
    0:   "游戏初始化完成 (两个存档均为1)",
    1:   "序章/初始化 — 场景2「桃源鄉」实体43/338 脚本对象'虎牢關之役' (4个DEFINE, 存档1=1存档2=1)",
    2:   "初始化组 — 场景2「桃源鄉」实体43/338 脚本对象 (3个DEFINE, 存档1=0存档2=1)",
    3:   "早期进度 — 场景2「桃源鄉」+场景53「長沙街道」+场景55「長沙馬廄」 (4个DEFINE, 存档1=0存档2=1)",
    106: "某主线事件 — 与flag[105]组配对 (存档1=0存档2=1)",
    107: "某主线分支 — 值=2代表某分支完成 (存档1=0存档2=2)",
    354: "三分支结果 — (存档1=3存档2=0, 值=3)",
}

# === 场景事件标志 (从DEFINE头部注释+TKMat+TKT三方交叉验证) ===
# 场景名来源: TKT[300+scene_id] → Big5解码第一行
_SCENE_FLAGS = {
    5:   "長安對話计数 — 场景94「北平城區」NPC 实体403-404 (7个DEFINE)",
    6:   "長安对话二值 — 场景94「北平城區」+95「北平武器店」+108「許家村民房」+163「長安城外」 (5个DEFINE)",
    103: "金錢計數 — 场景31「建業王殿」NPC 实体2390-2391 (132次引用)",
    104: "官名計數 — 场景31「建業王殿」NPC 实体2390-2391 (24次引用, 存档2=1)",
    105: "二值状态 — 场景31「建業王殿」NPC 实体2390-2391 (39次引用)",
    303: "夏侯惇对话 — 场景140「南蠻村莊」+143「南蠻村長家」+0「大地圖」 实体1114-1116 (3个DEFINE)",
    356: "無法回頭 — 场景165「長安道觀」+0「大地圖」 实体885/1946 一次性门禁 (3个DEFINE)",
    309: "阶段计数 — 场景30「建業內城」+23「成都內城」 脚本对象 (10个DEFINE, CheckFlag==4/5)",
    310: "激活开关 — 场景106「許家村」+77「武威街道」+125「武陵街道」+32「睢陽街道」 NPC (5个DEFINE)",
    312: "二阶段旗 — 场景53「長沙街道」+54「長沙酒樓」+45「南陽大街」 NPC (4个DEFINE)",
    344: "通用+随机 — 场景25「成都王殿」+134「下邳市集」 NPC Random→SetFlagVar (6个DEFINE)",
    1014:"夏侯惇任务 — 场景139「夏侯惇軍營主帳」+138「夏侯惇軍營營區」 脚本对象 (3个DEFINE)",
    1022:"武威任务 — 场景78「武威酒館」+76「武威城門」 事件对象/NPC (10个DEFINE)",
    1023:"許家村任务 — 场景106「許家村」 NPC/脚本对象 (8个DEFINE)",
}

# === 事件组A (flags 110-119) — 场景18「鄴城王殿」NPC 实体4283 ===
_EVENT_GROUP_A = {
    110: "事件组A·阶段 — 场景18「鄴城王殿」NPC 实体4283 'XX加入事件' (CheckFlag>=0/==0/==1 3个DEFINE)",
    112: "事件组A·旗1 — 场景18「鄴城王殿」NPC 实体4283 (42次引用, CheckFlag==1, SetFlag 0/1)",
    114: "事件组A·旗2 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285 (SetFlag 1→2)",
    115: "事件组A·旗3 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285",
    116: "事件组A·旗4 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285",
    117: "事件组A·旗5 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285",
    118: "事件组A·旗6 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285",
    119: "事件组A·旗7 — 场景18「鄴城王殿」+17「鄴城內城」 实体4283/4285",
}

# === 事件组B (flags 130-139) — 场景25「成都王殿」NPC 实体672 + 场景23「成都內城」传送点 实体680 ===
_EVENT_GROUP_B = {
    130: "事件组B·阶段 — 场景25「成都王殿」NPC 实体672 '一般對話' (CheckFlag>=0/==0/==1 3个DEFINE)",
    134: "事件组B·旗1 — 场景25「成都王殿」+23「成都內城」 实体666/669/672/680",
    135: "事件组B·旗2 — 场景25「成都王殿」+23「成都內城」 实体667/670/672/680",
    136: "事件组B·旗3 — 场景25「成都王殿」+23「成都內城」 实体669/671/672/680",
    137: "事件组B·旗4 — 场景25「成都王殿」+23「成都內城」 实体666/672/680",
    138: "事件组B·旗5 — 场景25「成都王殿」+23「成都內城」 实体667/672/680",
    139: "事件组B·旗6 — 场景25「成都王殿」+23「成都內城」 实体668/672/680",
}

# === 计数/统计类标志（含场景名）===
_COUNT_SCENE_FLAGS = {
    100: "计数A — 场景25「成都王殿」NPC 实体666-669 AddFlag(1) (132次引用)",
    101: "计数B — 场景25「成都王殿」NPC 实体666-669 AddFlag(1) (24次引用)",
    102: "二值A — 场景25「成都王殿」NPC 实体666-669 SetFlag(1) (42次引用)",
    # flags 111/113 仍暂用原标注 (来自TKD注释)
}

# === 阶段计数标志（含场景名）===
_STAGE_SCENE_FLAGS = {
    305: "阶段计数A — 场景9「天師塚西玄穴」脚本对象 实体1179-1182 AddFlag(1)/CheckFlag==4 (5个DEFINE)",
    306: "阶段计数B·重置 — 场景21「成都蒲良武器店」NPC 实体4389 CheckFlag→AddFlag '2-6 #Define'系列 (136次引用)",
    307: "阶段计数B·累加 — 场景21「成都蒲良武器店」NPC 实体4389 AddFlag(1)累加器 (64次引用)",
    145: "三主线完成计数 — 场景25「成都王殿」NPC 实体673 CheckFlag==3 配合142/143/144 (6个DEFINE)",
}

# 合并所有标志语义 (优先级: 后合并的覆盖先合并的)
for _d in [_CHAR_FLAGS, _STORY_FLAGS, _COUNT_FLAGS, _QUEST_FLAGS,
           _GENERIC_FLAGS, _SPECIAL_FLAGS, _SCENE_FLAGS,
           _EVENT_GROUP_A, _EVENT_GROUP_B, _COUNT_SCENE_FLAGS, _STAGE_SCENE_FLAGS]:
    FLAG_SEMANTICS.update(_d)

# 填充未确定项 — 按值域类型分类
for _i in range(1024):
    if _i not in FLAG_SEMANTICS:
        FLAG_SEMANTICS[_i] = f"标志#{_i}"

# ── 事件结果: word_755E50[24], case 7 (MenuTalk→sub_40B710) 设置 ──
# 检查: case 60 (CheckResult) 仅支持 == 比较
# 语义: 存储玩家菜单选择索引, MenuTalk写入→CheckResult立即消费
# TKD统计: 583次MenuTalk调用, 全部使用result[0]
RESULT_SEMANTICS = {
    0: "【主菜单槽】MenuTalk选择结果 — 583次调用全部使用此槽, 0=选项1 1=选项2...",
}
for _i in range(1, 24):
    RESULT_SEMANTICS[_i] = f"结果#{_i} (TKD中未观察到使用, 所有MenuTalk都用result[0])"

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
        self.warpc_count = 143  # default, updated on load

        # 外部资源
        self.tkt = {}
        self.item_records = {}
        self.item_names = {}
        self.tkkon_names = {}
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
        fm.addAction("📂 打开存档目录…\tCtrl+O", self._cmd_open)
        fm.addAction("💾 保存当前槽位\tCtrl+S", self._cmd_save)
        fm.addSeparator()
        fm.addAction("🚪 退出", self.close)
        tm = mb.addMenu("工具(&T)")
        tm.addAction("🔄 刷新数据显示", self._refresh_all)
        hm = mb.addMenu("帮助(&H)")
        hm.addAction("ℹ️ 关于", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QPushButton("📂 打开目录", clicked=self._cmd_open))
        toolbar.addWidget(QPushButton("💾 保存", clicked=self._cmd_save))
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("槽位:"))
        self._slot_btns = []
        for i in range(1, 10):
            btn = QPushButton(f"{i}")
            btn.setFixedWidth(32)
            btn.setToolTip(f"槽位 {i}")
            btn.clicked.connect(lambda checked, s=i: self._switch_slot(s))
            toolbar.addWidget(btn)
            self._slot_btns.append(btn)
        toolbar.addStretch()
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
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

        # 底部路径栏
        path_row = QHBoxLayout()
        self.lbl_save = QLabel("存档: 未加载")
        self.lbl_tkt = QLabel("TKT: 未加载")
        self.lbl_item = QLabel("TKItem: 未加载")
        self.lbl_mu = QLabel("Mu.JVG: 未加载")
        path_row.addWidget(self.lbl_save)
        path_row.addSpacing(16)
        path_row.addWidget(self.lbl_tkt)
        path_row.addSpacing(16)
        path_row.addWidget(self.lbl_item)
        path_row.addSpacing(16)
        path_row.addWidget(self.lbl_mu)
        path_row.addStretch()
        main_layout.addLayout(path_row)

    def _update_paths(self):
        parent = os.path.dirname(self.save_dir.rstrip('/\\')) if self.save_dir else None
        update_path_labels([
            (self.lbl_save, self.save_dir, '存档'),
            (self.lbl_tkt, os.path.join(parent, 'TKT.dat') if parent else None, 'TKT'),
            (self.lbl_item, os.path.join(parent, 'TKItem.dat') if parent else None, 'TKItem'),
            (self.lbl_mu, os.path.join(parent, 'Mu.JVG') if parent else None, 'Mu.JVG'),
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

        self.tabs.addTab(w, "📊 总览")

    # ================================================================
    # Tab 1: 队伍与经济
    # ================================================================
    def _build_team_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        # 队伍成员
        self._team_edits = []
        self._team_name_labels = []
        team_grp = QWidget()
        tvl = QVBoxLayout(team_grp); tvl.setContentsMargins(0, 0, 0, 0); tvl.setSpacing(0)
        tvl.addWidget(DockHeader("队伍成员 (word_75688C[6], -1=空)"))
        tbody = QWidget(); tbody.setObjectName("DockBody")
        tbl = QVBoxLayout(tbody); tbl.setContentsMargins(8, 8, 8, 8)
        tgl = QGridLayout(); tgl.setVerticalSpacing(4); tgl.setHorizontalSpacing(8)
        tgl.setContentsMargins(10, 0, 0, 0)
        for i in range(6):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(f"成员{i+1}"); lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            edit = QLineEdit("-1"); edit.setFont(QFont("Consolas", 9))
            cell.addWidget(make_fake_input(line_edit=edit, stretch=False))
            nlbl = QLabel(""); nlbl.setProperty("class", "ExtraPreviewText")
            cell.addWidget(nlbl)
            tgl.addLayout(cell, 0, i, Qt.AlignTop)
            self._team_edits.append(edit)
            self._team_name_labels.append(nlbl)
        for c in range(7):
            tgl.setColumnStretch(c, 1)
        tgl.addWidget(QWidget(), 0, 6)
        tbl.addLayout(tgl)
        tvl.addWidget(tbody)
        layout.addWidget(team_grp)

        # 经济
        econ_grp = QWidget()
        evl = QVBoxLayout(econ_grp); evl.setContentsMargins(0, 0, 0, 0); evl.setSpacing(0)
        evl.addWidget(DockHeader("经济与声望"))
        ebody = QWidget(); ebody.setObjectName("DockBody")
        ebl = QVBoxLayout(ebody); ebl.setContentsMargins(8, 8, 8, 8)
        egl = QGridLayout(); egl.setVerticalSpacing(4); egl.setHorizontalSpacing(8)
        egl.setContentsMargins(10, 0, 0, 0)
        self._econ_edits = {}
        econ_fields = [("gold", "金钱(上限30000)"), ("wisdom", "智慧"),
                       ("benevolence", "仁德"), ("courage", "勇气"), ("medicine", "医术(上限100)")]
        for col, (key, label) in enumerate(econ_fields):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(label); lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            edit = QLineEdit("0"); edit.setFont(QFont("Consolas", 9))
            cell.addWidget(make_fake_input(line_edit=edit, stretch=False))
            egl.addLayout(cell, 0, col, Qt.AlignTop)
            self._econ_edits[key] = edit
        for c in range(7):
            egl.setColumnStretch(c, 1)
        for c in range(5, 7):
            egl.addWidget(QWidget(), 0, c)
        ebl.addLayout(egl)
        evl.addWidget(ebody)
        layout.addWidget(econ_grp)

        # 战斗统计
        battle_grp = QWidget()
        bvl = QVBoxLayout(battle_grp); bvl.setContentsMargins(0, 0, 0, 0); bvl.setSpacing(0)
        bvl.addWidget(DockHeader("战斗统计"))
        bbody = QWidget(); bbody.setObjectName("DockBody")
        bbl = QVBoxLayout(bbody); bbl.setContentsMargins(8, 8, 8, 8)
        bgl = QGridLayout(); bgl.setVerticalSpacing(4); bgl.setHorizontalSpacing(8)
        bgl.setContentsMargins(10, 0, 0, 0)
        self._battle_edits = {}
        for col, (key, off, size, label, fmt, cmt) in enumerate(SEG2_BATTLE_FIELDS):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(label); lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(cmt)
            cell.addWidget(lbl)
            edit = QLineEdit("0"); edit.setFont(QFont("Consolas", 9))
            cell.addWidget(make_fake_input(line_edit=edit, stretch=False))
            bgl.addLayout(cell, 0, col, Qt.AlignTop)
            self._battle_edits[key] = edit
        for c in range(7):
            bgl.setColumnStretch(c, 1)
        bbl.addLayout(bgl)
        bvl.addWidget(bbody)
        layout.addWidget(battle_grp)

        # 应用按钮
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("✅ 应用队伍修改", clicked=self._apply_team))
        btn_row.addWidget(QLabel("(修改后需保存到文件)"))
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self.tabs.addTab(w, "👥 队伍")

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
        ctrl.addWidget(QPushButton("🔄 刷新", clicked=self._refresh_inventory))
        ctrl.addWidget(QPushButton("✅ 应用修改", clicked=self._apply_inventory))
        ctrl.addWidget(QPushButton("➕ 新增物品", clicked=self._add_inv_item_dialog))
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # 物品表格
        self._inv_table = QTableWidget(0, 6)
        self._inv_table.setHorizontalHeaderLabels(['图标', '#', 'ID', '页面', '物品名称', '数量'])
        self._inv_table.setColumnWidth(0, 50)
        self._inv_table.setColumnWidth(1, 36)
        self._inv_table.setColumnWidth(2, 46)
        self._inv_table.setColumnWidth(3, 46)
        self._inv_table.setColumnWidth(4, 200)
        self._inv_table.setColumnWidth(5, 55)
        self._inv_table.verticalHeader().setDefaultSectionSize(44)
        self._inv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._inv_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._inv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._inv_table.verticalHeader().setVisible(False)
        self._inv_table.horizontalHeader().setStretchLastSection(True)
        self._inv_table.setIconSize(QSize(36, 36))
        layout.addWidget(self._inv_table, 1)
        self._inv_photos = []  # prevent GC

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
        edit_row.addWidget(QPushButton("✅ 修改选中", clicked=self._apply_inv_edit))
        edit_row.addWidget(QPushButton("🗑 删除选中", clicked=self._delete_inv_item))
        edit_row.addStretch()
        layout.addLayout(edit_row)

        self._inv_table.itemSelectionChanged.connect(self._on_inv_select)
        self.tabs.addTab(w, "🎒 物品")

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
            "🔘 事件开关", 32, SWITCH_SEMANTICS, "word_755E10, case49 设置")
        # 子Tab: 变量
        self._var_table = self._build_event_subtab(
            "🔢 事件变量", 250, VARIABLE_SEMANTICS, "word_755E80, case36/37 设置")
        # 子Tab: 标志
        self._flag_table = self._build_event_subtab(
            "🚩 事件标志", 1024, FLAG_SEMANTICS, "word_756080, sub_40CB08 设置")
        # 子Tab: 结果
        self._result_table = self._build_event_subtab(
            "🎯 事件结果", 24, RESULT_SEMANTICS, "word_755E50, case60 检查")

        # 控制栏
        ctrl = QHBoxLayout()
        self._event_nonzero_cb = QCheckBox("仅显示非零项")
        self._event_nonzero_cb.stateChanged.connect(self._filter_event_tables)
        ctrl.addWidget(self._event_nonzero_cb)
        self._event_hex_cb = QCheckBox("十六进制显示")
        self._event_hex_cb.stateChanged.connect(self._refresh_event_display)
        ctrl.addWidget(self._event_hex_cb)
        ctrl.addStretch()
        ctrl.addWidget(QPushButton("✅ 应用事件修改", clicked=self._apply_events))
        layout.addLayout(ctrl)

        self.tabs.addTab(w, "📋 事件系统")

    def _build_event_subtab(self, title, count, semantics, source_note):
        """构建事件子Tab: 返回 QTableWidget"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel(f"来源: {source_note}  |  共 {count} 项"))

        table = QTableWidget(count, 4)
        table.setHorizontalHeaderLabels(['索引', '值', '语义标注', '十六进制'])
        table.verticalHeader().setVisible(False)
        # 列宽策略: 索引/值/十六进制适应内容, 语义标注列自适应填充剩余宽度
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        # 设置最小宽度防止过度压缩
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 60)
        table.setColumnWidth(3, 70)
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
        btn_row.addWidget(QPushButton("✅ 应用全局修改", clicked=self._apply_global))
        btn_row.addStretch()
        inner_layout.addLayout(btn_row)
        inner_layout.addStretch()

        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.tabs.addTab(w, "🌍 全局状态")

    def _build_global_section(self, parent_layout, title, fields, seg):
        grp = QWidget()
        vl = QVBoxLayout(grp); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(0)
        vl.addWidget(DockHeader(title))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8, 8, 8, 8)
        gl = QGridLayout(); gl.setVerticalSpacing(6); gl.setHorizontalSpacing(8)
        gl.setContentsMargins(10, 0, 0, 0)
        cols = 5
        for fi, (key, off, size, label, fmt, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(f"{label} [+0x{off:X}]")
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(cmt)
            cell.addWidget(lbl)
            edit = QLineEdit("0")
            edit.setFont(QFont("Consolas", 9))
            cell.addWidget(make_fake_input(line_edit=edit, stretch=False))
            gl.addLayout(cell, r, c, Qt.AlignTop)
            self._global_edits[key] = (edit, off, size, fmt, seg)
        for c in range(cols):
            gl.setColumnStretch(c, 1)
        if fields:
            last_row = len(fields) // cols
            last_count = len(fields) % cols
            if last_count != 0:
                for c in range(last_count, cols):
                    gl.addWidget(QWidget(), last_row, c)
        bl.addLayout(gl)
        vl.addWidget(body)
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
        self._warpc_search.setPlaceholderText("🔍 搜索角色...")
        self._warpc_search.textChanged.connect(self._refresh_warpc_list)
        sf.addWidget(self._warpc_search)
        self._warpc_filter = QComboBox()
        self._warpc_filter.addItems(["全部", "✅ 已激活", "❌ 未激活", "👥 队伍中"])
        self._warpc_filter.currentIndexChanged.connect(self._refresh_warpc_list)
        sf.addWidget(self._warpc_filter)
        left_layout.addLayout(sf)

        self._warpc_table = QTableWidget(0, 6)
        self._warpc_table.setHorizontalHeaderLabels(['#', '名称', 'LV', '身份', 'HP', 'MP'])
        self._warpc_table.setColumnWidth(0, 35)
        self._warpc_table.setColumnWidth(1, 110)
        self._warpc_table.setColumnWidth(2, 35)
        self._warpc_table.setColumnWidth(3, 50)
        self._warpc_table.setColumnWidth(4, 55)
        self._warpc_table.setColumnWidth(5, 55)
        self._warpc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._warpc_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._warpc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._warpc_table.verticalHeader().setVisible(False)
        self._warpc_table.itemSelectionChanged.connect(self._on_warpc_select)
        left_layout.addWidget(self._warpc_table)

        # 右侧: 复用 warpc_editor_v2 的独立编辑面板
        self._warpc_panel = WarpcEditPanel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._warpc_panel)
        splitter.setSizes([350, 1050])
        layout.addWidget(splitter)

        self._warpc_cur_idx = -1
        self._warpc_panel.record_applied.connect(self._on_warpc_record_applied)
        self.tabs.addTab(w, "👤 角色")

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
        # TKItem
        it_path = os.path.join(parent, 'TKItem.dat')
        if os.path.exists(it_path):
            self.item_records, self.item_names = self._parse_item_dat(it_path)
        # Mu.JVG
        mu_path = os.path.join(parent, 'Mu.JVG')
        if os.path.exists(mu_path):
            self._mu_sprites = load_mu_sprites(mu_path) or []
            self._icon_pixmaps.clear()
        # TKKon 名称 (动态解析)
        try:
            resolver = KonNameResolver(parent)
            self.tkkon_names = resolver.get_all_names()
        except Exception:
            self.tkkon_names = {}

    def _parse_skill_dat(self, path):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % 94 == 0 and (len(dec) == 0 or len(dec) % 94 != 0):
                dec = raw
            names = {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec):
                    break
                name_id = struct.unpack_from('<h', dec, off)[0]
                if name_id > 0 and name_id in self.tkt:
                    names[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
                elif name_id < 0 and -name_id in self.tkt:
                    names[i] = self.tkt[-name_id].split('\n')[0].strip()[:20]
                elif name_id:
                    names[i] = f'#{name_id}'
            return names
        except Exception:
            return {}

    def _parse_skill_types(self, path):
        """解析 TKSkill.dat 的 type 字段 (供 warpc editor 技能效果判定 tab 使用)
        TKSkill 记录 94 字节: [0]name_id [2]unknown [4]type [6]...
        """
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % 94 == 0 and (len(dec) == 0 or len(dec) % 94 != 0):
                dec = raw
            types = {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec):
                    break
                skill_type = struct.unpack_from('<h', dec, off + 4)[0]
                types[i] = skill_type
            return types
        except Exception:
            return {}

    def _load_tkkon_names(self, tks_dir=None):
        """[已废弃] 从游戏数据动态解析 TKKon 名称映射.
        
        现在由 _load_resources() 通过 KonNameResolver 自动完成。
        保留此方法仅为兼容旧调用。
        """
        if not tks_dir:
            return {}
        try:
            resolver = KonNameResolver(tks_dir)
            return resolver.get_all_names()
        except Exception:
            return {}

    def _parse_item_dat(self, path):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % 64 == 0 and (len(dec) == 0 or len(dec) % 64 != 0):
                dec = raw
        except Exception:
            return {}, {}
        records = {}
        names = {}
        for i in range(600):
            off = i * 64
            if off + 64 > len(dec):
                break
            item_id = struct.unpack_from('<h', dec, off)[0]
            name_id = struct.unpack_from('<h', dec, off + 4)[0]
            tab_code = struct.unpack_from('<h', dec, off + 2)[0]
            icon = struct.unpack_from('<h', dec, off + 8)[0]
            equip_type = struct.unpack_from('<h', dec, off + 10)[0]
            price = struct.unpack_from('<h', dec, off + 62)[0]
            nm = ""
            if name_id > 0 and name_id in self.tkt:
                nm = self.tkt[name_id].split('\n')[0].strip()[:25]
            elif item_id > 0:
                nm = f'物品#{item_id}'
            records[i] = {'item_id': item_id, 'name_id': name_id,
                          'tab_code': tab_code, 'icon': icon,
                          'equip_type': equip_type, 'price': price, 'name': nm}
            if item_id > 0:
                names[item_id] = nm
        return records, names

    def _switch_slot(self, slot_num):
        if self._dirty:
            if QMessageBox.question(self, "未保存", "有未保存修改，是否放弃?") != QMessageBox.Yes:
                return
        self.slot = slot_num
        self._load_current_slot()
        for i, btn in enumerate(self._slot_btns):
            btn.setProperty("active", "true" if i + 1 == slot_num else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _load_current_slot(self):
        if not self.save_dir:
            return
        sav_data = os.path.join(self.save_dir, f'sav.{self.slot}')
        sav_idx = os.path.join(self.save_dir, f'{self.slot}.sav')
        if not os.path.exists(sav_data):
            self._status_label.setText(f"槽位 {self.slot}: 数据文件不存在")
            self.game_state = self.seg1 = self.seg2 = self.seg3 = None
            self.index_meta = None
            self._dirty = False
            self._refresh_all()
            return
        try:
            self.game_state, self.seg1, self.seg2, self.seg3 = load_save_data(sav_data)
            self.warpc_count = len(self.seg3) // WARPC_REC
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.game_state = self.seg1 = self.seg2 = self.seg3 = None
            self.index_meta = None
            self._dirty = False
            self._refresh_all()
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
                if i == 0:
                    name = self._get_player_name()
                else:
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
            if self.warpc_count != 143:  # 原始143角色
                lines.append(f"  * 非标准角色数 (原始143), 已被TKSLauncher扩展")
            if self.seg2:
                gold = struct.unpack_from('<H', self.seg2, 0x02)[0]
                team_strs = []
                for i in range(6):
                    tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
                    if tid >= 0:
                        if i == 0:
                            name = self._get_player_name()
                        else:
                            name = self._get_char_name(tid)
                        team_strs.append(f"{name}(#{tid})")
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
                        # 当前槽位: 成员1优先用姓+名
                        if s == self.slot and meta['team_ids'][0] >= 0:
                            names[0] = self._get_player_name()
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
            for i in range(6):
                self._team_edits[i].setText("-1")
                self._team_name_labels[i].setText("")
            for key in self._econ_edits:
                self._econ_edits[key].setText("0")
            for key in self._battle_edits:
                self._battle_edits[key].setText("0")
            return
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
            self._team_edits[i].setText(str(tid))
            if i == 0:
                # 成员1: 优先用姓+名拼接，否则显示"主角"
                self._team_name_labels[i].setText(self._get_player_name())
            else:
                self._team_name_labels[i].setText(self._get_char_name(tid) if tid >= 0 else "(空)")
        for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
            val = struct.unpack_from('<' + fmt, self.seg2, off)[0]
            if key in self._econ_edits:
                self._econ_edits[key].setText(str(val))
        for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
            val = struct.unpack_from('<H', self.seg2, off)[0]
            if key in self._battle_edits:
                self._battle_edits[key].setText(str(val))

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24, 24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    # ================================================================
    # 刷新: 物品
    # ================================================================
    def _refresh_inventory(self):
        if self.seg2 is None:
            self._inv_count_edit.setText("0")
            self._inv_table.setRowCount(0)
            return
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        count = struct.unpack_from('<H', self.seg2, off)[0]
        self._inv_count_edit.setText(str(count))
        self._inv_table.setRowCount(0)
        self._inv_photos.clear()
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
            icon_val = rec.get('icon', 0) if rec else 0
            row = self._inv_table.rowCount()
            self._inv_table.insertRow(row)
            # 图标列
            icon_item = QTableWidgetItem()
            pix = self._get_icon_pixmap(icon_val, (36, 36))
            if pix:
                icon_item.setIcon(QIcon(pix))
            self._inv_table.setItem(row, 0, icon_item)
            self._inv_table.setItem(row, 1, QTableWidgetItem(str(i)))
            self._inv_table.setItem(row, 2, QTableWidgetItem(str(item_id)))
            self._inv_table.setItem(row, 3, QTableWidgetItem(page))
            self._inv_table.setItem(row, 4, QTableWidgetItem(name))
            self._inv_table.setItem(row, 5, QTableWidgetItem(str(qty)))

    # ================================================================
    # 刷新: 事件系统
    # ================================================================
    def _refresh_events(self):
        if self.seg1 is None:
            for table in [self._switch_table, self._var_table, self._flag_table, self._result_table]:
                for row in range(table.rowCount()):
                    table.item(row, 1).setText("0")
                    table.item(row, 3).setText("0x0000")
                    table.setRowHidden(row, False)
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
            for key, (edit, off, size, fmt, seg) in self._global_edits.items():
                edit.setText("0")
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
            mp = warpc_get(self.seg3, i, 12)
            name = self.tkt.get(name_id, f"ID:{name_id}") if name_id else ""
            in_team = i in team_set

            if filt == "❌ 未激活" and role != -1:
                continue
            if filt == "✅ 已激活" and role != 0:
                continue
            if filt == "👥 队伍中" and not in_team:
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
            self._warpc_table.setItem(row, 5, QTableWidgetItem(str(mp)))

    def _on_warpc_select(self):
        sel = self._warpc_table.selectedItems()
        if not sel:
            return
        idx = int(self._warpc_table.item(sel[0].row(), 0).text())
        self._warpc_cur_idx = idx
        # 将 seg3 数据转为 warpc editor 的记录格式
        if self.seg3 is not None:
            off = idx * WARPC_REC
            if off + WARPC_REC <= len(self.seg3):
                vals = list(struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, self.seg3, off))
                rec = {'index': idx, 'fields': vals}
                self._warpc_panel._current_record = rec
                self._warpc_panel._editing_idx = idx
                # 传递外部资源
                self._warpc_panel.tkt = self.tkt
                self._warpc_panel.skill_names = self.skill_names
                self._warpc_panel._skill_types = self._skill_types
                self._warpc_panel.item_names = self.item_names
                self._warpc_panel._mu_sprites = self._mu_sprites
                self._warpc_panel._icon_pixmaps = {}
                self._warpc_panel.tkkon_names = self.tkkon_names
                # 构建 item_idx_names (TKItem数组下标→名称)
                self._warpc_panel.item_idx_names = {
                    idx: rec['name'] for idx, rec in self.item_records.items() if rec.get('name')
                }
                self._warpc_panel._populate_edit(rec)

    def _on_warpc_record_applied(self, idx):
        """编辑面板点击应用后, 同步回 seg3"""
        rec = self._warpc_panel._current_record
        if rec and self.seg3 is not None:
            off = idx * WARPC_REC
            if off + WARPC_REC <= len(self.seg3):
                struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, self.seg3, off, *rec['fields'])
                self._dirty = True
                self._refresh_warpc_list()
                self._status_label.setText(f"角色 #{idx} 已修改 (未保存)")









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



    # ================================================================
    # 物品操作
    # ================================================================
    def _on_inv_select(self):
        sel = self._inv_table.selectedItems()
        if sel:
            row = sel[0].row()
            self._inv_edit_id.setText(self._inv_table.item(row, 2).text())
            self._inv_edit_qty.setText(self._inv_table.item(row, 5).text())

    def _apply_inv_edit(self):
        sel = self._inv_table.selectedItems()
        if not sel or self.seg2 is None:
            return
        row = sel[0].row()
        idx = int(self._inv_table.item(row, 1).text())
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
        idx = int(self._inv_table.item(row, 1).text())
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
        # 构造完整物品记录列表 (与 item_editor 统一格式)
        item_list = []
        for arr_idx, rec in self.item_records.items():
            item_list.append({
                'index': arr_idx,
                'item_id': rec.get('item_id', 0),
                'tab_code': rec.get('tab_code', 0),
                'name': rec.get('name', ''),
                'equip_type': rec.get('equip_type', 0),
                'icon': rec.get('icon', 0),
                'price': rec.get('price', 0),
            })
        dlg = ItemPickerDialog(
            self, item_list,
            icon_pixmap_fn=self._get_icon_pixmap,
            title="➕ 新增物品 — 选择物品",
            return_key='index',
        )
        if dlg.exec() != QDialog.Accepted or dlg.selected_value is None:
            return
        arr_idx = dlg.selected_value
        rec = self.item_records.get(arr_idx, {})
        item_id = rec.get('item_id', 0)
        # 数量输入
        qty, ok = QInputDialog.getInt(
            self, "输入数量", f"为 物品#{item_id} (idx={arr_idx}) 设置数量:",
            value=1, minValue=1, maxValue=30000)
        if not ok:
            return
        self._add_inv_item(arr_idx, item_id, qty)

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

    def _get_player_name(self):
        """获取主角名称: seg1中的姓+名拼接, 为空则返回'主角'"""
        if self.seg1 is None:
            return "主角"
        given = self._decode_big5(self.seg1[0x4C:0x4C + 5])
        surname = self._decode_big5(self.seg1[0x54:0x54 + 5])
        full = (surname + given).strip()
        return full if full else "主角"

    def _scene_name(self, scene_id):
        """从TKT获取场景名称 (TKT_ID = scene_id + 300).
        与mat_editor_v2的scene_name()一致。"""
        if scene_id < 0:
            return "全局"
        tkt_id = 300 + scene_id
        if self.tkt and tkt_id in self.tkt:
            return self.tkt[tkt_id].split('\n')[0].strip()
        return f"场景{scene_id}"

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

def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    editor = SaveEditorApp()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
