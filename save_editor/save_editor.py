#!/usr/bin/env python3
r"""
TKS Save Editor
加载/编辑/保存 游戏存档数据 (save\sav.N + N.sav)

逆向来源: TKS.exe sub_410ED4 (SaveTKMat), sub_41103C (LoadTKMat)
"""

import os, struct, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# 常量 (来自逆向工程)
# ============================================================

# Block 1: 游戏状态缓冲区 dword_51AF40
GAMESTATE_DECOMPRESSED = 2304000

# Block 2: TKMat 三段
SEG1_BASE = 0x755B18   # 段1: 全局变量 (来源: sub_41103C line 34)
SEG1_SIZE = 3432       # 来源: sub_410ED4 line 26
SEG2_BASE = 0x756880   # 段2: 队伍数据 (来源: sub_41103C line 35)
SEG2_SIZE = 5768       # 来源: sub_410ED4 line 27
SEG3_BASE = 0x757F08   # 段3: WarPC 数据 (来源: sub_41103C line 36)
SEG3_SIZE = 150722     # 来源: sub_410ED4 line 28
TKMAT_DECOMPRESSED = SEG1_SIZE + SEG2_SIZE + SEG3_SIZE  # 159922

WARPC_REC = 1054       # 每条记录字节数
WARPC_CNT = SEG3_SIZE // WARPC_REC  # 143
WARPC_FIELD_COUNT = 527  # 每条记录 int16 字段数

# .sav 元数据大小 (来源: sub_41B1A8 文件名 save\%d.sav)
SAV_META_SIZE = 28

# ============================================================
# 段1 (0x755B18, 3432B) 已知字段偏移 (相对段1起始)
# ============================================================

# SEG1 字段定义 — 每个标签必须有反编译代码直接证据
SEG1_BASIC_FIELDS = [
    ("map_id",       0x40, 4, "当前地图ID",     "I",  "dword_755B58, sub_40C044 地图切换; 常量2/3/4/5/18/25/31/201"),
    ("current_char", 0x44, 4, "当前角色ID",     "I",  "dword_755B5C, sub_40C7CC SetPlayer事件; a1=-1时的默认目标"),
    ("game_active",  0x48, 4, "游戏激活标志",    "I",  "dword_755B60, sub_41103C读档后置1; sub_40EBD4 opcode31"),
    ("char_name",    0x4C, 5, "玩家名字(5B)",   "5s", "byte_755B64, sub_40D2D0名字输入 strcpy(byte_755B64, byte_95102D)"),
    ("name_short",   0x54, 3, "名字短串(3B)",   "3s", "byte_755B6C, sub_40D2D0 strcpy(byte_755B6C, byte_951028)"),
    ("checksum",     0x164, 4, "校验码",        "I",  "sub_411624: sub_4E4FB0(1024,9)哈希4B, 运行时从不读取"),
]

SEG1_SLOT_FIELDS = [
    ("slot1_active", 0x15C, 2, "编成槽1激活",    "H",  "word_755C74, sub_41FAAC编成UI: 0/1"),
    ("slot1_idx",    0x15E, 2, "编成槽1角色索引", "H",  "word_755C76, sub_41FAAC: 值域1-5"),
    ("slot2_active", 0x160, 2, "编成槽2激活",    "H",  "word_755C78, sub_41FAAC: 与slot1镜像"),
    ("slot2_idx",    0x162, 2, "编成槽2角色索引", "H",  "word_755C7A, sub_41FAAC: 值域1-5"),
]

SEG1_MAP_FIELDS = [
    ("battle_flags", 0x168, 4, "遭遇战旗标",     "I",  "dword_755C80, sub_4084E0: bit0减半/bit1禁止/bit2强制/bit3反击"),
    ("map_timer",    0x82C, 2, "地图计时器",     "H",  "word_756344, sub_43CA64计算"),
    ("door_unlock",  0x82E, 2, "开门标志",       "H",  "word_756346, sub_4307CC门检测置1"),
]

SEG1_EVENT_FIELDS = [
    ("comp_flag",    0x336, 2, "同伴管理标志",    "H",  "word_755E4E, sub_420844检查"),
    ("minigame_rst", 0x366, 2, "小游戏结果",     "H",  "word_755E7E, sub_40E97C输出"),
    ("last_acq",     0x566, 2, "最后获得量",     "H",  "word_75607E, sub_40CE30获得动画显示"),
]

# 数组字段 (key, offset, count, elem_size, label, comment)
# NOTE: flags数组(0x568,1024×2=0x800字节)范围0x568-0xD67与map_timer(0x82C)/door_unlock(0x82E)存在重叠
SEG1_ARRAYS = [
    ("bgm_flags",    0x05C, 250, 1, "角色BGM标志",   "byte_755B74[250], sub_40C044地图切换BGM; sub_40EBD4 case53/54"),
    ("switches",     0x2F8, 32,  2, "事件开关",      "word_755E10[32], sub_40EBD4 case49 SetSwitch"),
    ("results",      0x338, 24,  2, "事件结果",      "word_755E50[24], sub_40EBD4 case60 CheckResult"),
    ("variables",    0x368, 256, 2, "事件变量",      "word_755E80[256], sub_40EBD4 case36-39 SetVar/FlagVar"),
    ("flags",        0x568, 1024,2, "事件标志",      "word_756080[1024], sub_40CB08 SetFlag/sub_40CB4C AddFlag"),
]

CHARA_FLAG_OFFSET = 0x5C
CHARA_FLAG_SIZE = 250

# ============================================================
# 段2 (0x756880, 5768B) 已知字段偏移 (相对段2起始)
# ============================================================

# SEG2 字段定义 — 每个标签必须有反编译代码直接证据
SEG2_CORE_FIELDS = [
    ("gold",         0x02, 2, "金钱",          "H",  "word_756882, sub_40CE30: 上限30000"),
    ("wisdom",       0x04, 2, "智慧",         "H",  "word_756884=word_757F3E[527*i]; WarPC[27]汇总, 下限0"),
    ("benevolence",  0x06, 2, "仁德",         "H",  "word_756886=word_757F40[527*i]; WarPC[28]汇总, 下限0"),
    ("courage",      0x08, 2, "勇气",         "H",  "word_756888=word_757F42[527*i]; WarPC[29]汇总, 下限0"),
    ("medicine",     0x0A, 2, "医术",         "H",  "word_75688A=word_757F44[527*i]; WarPC[30]汇总, 上限100"),
]

SEG2_TEAM_FIELDS = [
    ("team0",        0x0C, 2, "队伍成员1",     "h",  "word_75688C[0], sub_40DA00: -1=空"),
    ("team1",        0x0E, 2, "队伍成员2",     "h",  "word_75688C[1]"),
    ("team2",        0x10, 2, "队伍成员3",     "h",  "word_75688C[2]"),
    ("team3",        0x12, 2, "队伍成员4",     "h",  "word_75688C[3]"),
    ("team4",        0x14, 2, "队伍成员5",     "h",  "word_75688C[4]"),
    ("team5",        0x16, 2, "队伍成员6",     "h",  "word_75688C[5]"),
]

# SEG2 间隙字段 (0x018-0x7E7) — 逆向搜索仅发现以下引用
SEG2_GAP_FIELDS_1 = [
    ("opcode46_data", 0x58, 2, "事件数据46(word)", "H",  "word_7568D8, sub_40DBF4 opcode46数组写入; 未验证"),
]

SEG2_BATTLE_FIELDS = [
    ("encounters",   0x15FA, 2, "遭遇/逃跑次数", "H",  "word_757EBA, sub_43CA64递增 上限30000"),
    ("wins",         0x15FC, 2, "胜利次数",     "H",  "word_757EBC, sub_43CA64递增 上限30000"),
    ("losses",       0x15FE, 2, "败北次数",     "H",  "word_757EBE, sub_43C988递增 上限30000"),
    ("battle_pts",   0x163E, 2, "战斗点数",     "H",  "word_757EFE, sub_40E11C case10"),
    ("teleport_pct", 0x1640, 2, "传送进度",     "H",  "word_757F00, sub_41A080: 100*值/84百分比"),
    ("encounter_x",  0x1644, 2, "遭遇率X",      "H",  "word_757F04, sub_438F28战斗生成条件"),
    ("encounter_y",  0x1646, 2, "遭遇率Y",      "H",  "word_757F06, sub_4458B0战后递减"),
]

# 库存数组
SEG2_INVENTORY = [
    # (key, offset, count, label, comment)
    ("inv_items",    0x7EA, 600, "物品ID",      "word_7570AA[600], sub_40CE30增删"),
    ("inv_types",    0xD3A, 600, "物品类型索引", "word_75755A[600], sub_40CE30"),
    ("inv_qtys",     0x12CA,600, "物品堆叠数量", "word_757A0A[600], sub_40CE30"),
]

SEG2_INV_COUNT = ("inv_count",  0x7E8, 2, "物品种类数",  "H", "word_7570A8, sub_40CD90增减")

# ============================================================
# WarPC 字段定义 (来自 warpc_editor, 部分关键字段)
# ============================================================

# 身份字段 (来自 warpc_editor)
WARPC_IDENTITY = [
    ("name_id",         0,   "名称TKT ID",       "角色名称 → TKT.dat (sub_4067E8)"),
    ("portrait",        2,   "头像索引",         "头像索引 ×2 = Fa.JVG 大幅图, ×2+1 = 缩略图"),
    ("level",           4,   "等级",             "角色等级 (数值显示)"),
    ("role",            6,   "身份",             "0=敌方 -1=我方"),
    ("exp_to_next",     8,   "升级所需经验",     "升至下一级所需经验; 绝大多数角色=100, 敌方版较高(呂布5092 張角7292)"),
    ("awk_sprite_id", 520,   "战场图集索引",     "战斗中Awk.JVG/Awt.JVG块号 — 配合运行时补丁使用; 0=使用原硬编码公式"),
    ("portrait_menu_id",522,  "队伍头像ID",       "队伍菜单中Mu.JVG精灵块号 — 配合运行时补丁使用; 0=使用原公式(portrait+211)"),
    ("entity_link",   526,   "地图实体ID",       "离队后在地图上显示的NPC实体ID → TKMat.dat; sub_41EEC0→sub_40C648 启用此实体使其回到原位"),
]

# HP/MP 字段 (来自 warpc_editor)
WARPC_HPMP = [
    ("cur_hp",  10, "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",  12, "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base", 14, "HP基础",      "HP基础值"),
    ("hp_max",  16, "HP上限",      "HP上限 (基础+装备; sub_42234C)"),
    ("mp_base", 18, "MP基础",      "MP基础值"),
    ("mp_max",  20, "MP上限",      "MP上限 (基础+装备; sub_42234C)"),
]

STAT_NAMES = ["攻击", "防御", "命中", "闪避", "速度", "幸运", "移动", "悟性"]
STAT_SHORTS = ["atk", "def", "hit", "eva", "spd", "luk", "mov", "wis"]
STAT_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]

# 状态效果名称 (共31种, 索引0-30; sub_41E40C 使用 status_id 1-32) — 来自 warpc_editor
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

# 反应组语义值 — 来自 warpc_editor REACTION_GROUP_VALUES
REACTION_GROUP_VALUES = [
    "0-无",
    "1-近戰反擊",
    "2-遠程反擊",
    "3-法術反彈",
    "4-先發制人",
    "5-時序回饋",
    "6-損傷賠償",
    "7-環境探索",
    "8-國色天香",
    "9-有福同享",
    "10-國士無雙",
]

# 技能加成字段 (来自 warpc_editor)
WARPC_SKILL_BONUS = [
    ("atk_count",   64,  "攻击次数",       "攻击次数 (sub_42234C=1; sub_422BBC L29: a2[32]+=v6[31]=TKSkill增攻次)"),
    ("special_flag",66,  "特殊能力标志",   "来自装备 TKItem[20] (sub_42234C L73: a2[33]|=v9[20])"),
    ("mp_reduce",   68,  "内力消耗减少%",  "内息百分比 来自主动技能 TKSkill[33] (sub_422BBC L29: a2[34]+=v6[33])"),
    ("magic_def",   70,  "所受法伤减少%",  "抗魔百分比 来自主动技能 TKSkill[38] (sub_422BBC L45: a2[35]+=v6[38])"),
    ("exp_bonus",   72,  "战斗经验增加%",  "鬼才百分比 来自主动技能 TKSkill[36] (sub_422BBC L43: a2[36]+=v6[36])"),
    ("jp_bonus",    74,  "战斗技能点增加%","天才百分比 来自主动技能 TKSkill[37] (sub_422BBC L44: a2[37]+=v6[37])"),
    ("move_flags",  76,  "移动特殊标志",   "来自移动技能 TKSkill[32] (sub_422BBC L124: a2[38]|=v6[32]; bit0飘浮bit1飙行bit2搜宝bit3解陷)"),
    ("heal_move",   78,  "移动恢复生命%",  "自愈百分比 来自移动技能 TKSkill[22] (sub_422BBC L125: a2[39]+=v6[22])"),
    ("mp_move",     80,  "移动恢复内力%",  "回气百分比 来自移动技能 TKSkill[24] (sub_422BBC L126: a2[40]+=v6[24])"),
]

# 角色属性字段 (来自 warpc_editor)
WARPC_CHAR_ATTR = [
    ("wisdom",      54,  "智慧",        "智慧值 (曹操=5 司马懿=20)"),
    ("benevolence", 56,  "仁德",        "仁德值 (曹操=-1 司马懿=-5)"),
    ("courage",     58,  "勇气",        "勇气值 (曹操=10 司马懿=0)"),
    ("medicine",    60,  "医术",        "医术值 (曹操=0 司马懿=10; sub_40E11C case4→word_75688A capped 100)"),
    ("jp_total",    62,  "技能点数",    "累计技能点数 (曹操=400 司马懿=300; r=0.992与等级相关; sub_422A5C入队累加)"),
]

# 装备字段 (来自 warpc_editor)
WARPC_EQUIP = [
    ("equip_idx0", 138, "装备索引0",   "运行时装备索引缓存 (sub_4173F8 计算)"),
    ("equip_idx1", 140, "装备索引1",   "运行时装备索引缓存"),
    ("equip_idx2", 142, "装备索引2",   "运行时装备索引缓存"),
    ("equip_idx3", 144, "装备索引3",   "运行时装备索引缓存"),
    ("equip_id0",  146, "装备物品ID0", "装备物品 ID (DAT原始; 查 TKItem.field[0])"),
    ("equip_id1",  148, "装备物品ID1", "装备物品 ID"),
    ("equip_id2",  150, "装备物品ID2", "装备物品 ID"),
    ("equip_id3",  152, "装备物品ID3", "装备物品 ID"),
]

# 成长率字段 (来自 warpc_editor)
WARPC_GROWTH = [
    ("growth_early", 528, "成长率初期", "成长率初期; 五爪金龍=27 西羌王=27 呂布=20"),
    ("growth_mid",   530, "成长率中期", "成长率中期; 五爪金龍=24 西羌王=24 呂布=25"),
    ("growth_late",  532, "成长率后期", "成长率后期; 五爪金龍=21 西羌王=21 呂布=25"),
]

# 战斗奖励字段 (来自 warpc_editor)
WARPC_BATTLE_REWARD = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点数 (直接值, 无等级缩放); 盜賊嘍嘍=2 西羌王=100"),
    ("gold_reward", 538, "战后金钱基数","击败后获得金钱基数; 实际获得=基数×2; 盜賊嘍嘍=20→40 小混混=25→50"),
]

# 掉落字段 (来自 warpc_editor)
WARPC_DROP = [
    ("drop_item0", 540, "必掉落物品",  "可掉落物品0 ID; 五爪金龍=顛海神珠(537)"),
    ("drop_item1", 542, "高概率掉落",  "可掉落物品1 ID; 五爪金龍=金龍魂(234)"),
    ("drop_item2", 544, "低概率掉落",  "可掉落物品2 ID; 五爪金龍=虎項龍紋鎧(8081)"),
]

# 反应组字段 [41]-[42] — sub_422BBC 应用被动技能效果, sub_42234C 初始化为0 (来自 warpc_editor REACTION_FIELDS)
WARPC_REACTION_FIELDS = [
    ("reaction_group",  82,  "反应组",   "被动技能反应组编号 1-10 (sub_422BBC type=2; 初始化=0)"),
    ("reaction_trigger",84,  "触发概率", "被动技能触发概率 %%, 来自 TKSkill[44] (sub_422BBC: a2[42]=v6[44])"),
]

# 身上状态槽 [43]-[50] — sub_41E40C 验证: 8个状态效果槽, 每槽(status_id:byte, duration:byte) (来自 warpc_editor STATUS_SLOT_FIELDS)
WARPC_STATUS_SLOT_FIELDS = [
    (f"status_slot{i}", 86 + i*2, f"状态槽{i}",
     f"身上状态效果槽{i} (sub_41E40C: v8+{i*2}); 低字节=状态ID(1-32) 高字节=持续回合")
    for i in range(8)
]

# 状态抵抗 — 32状态×1byte抵抗力, 存储在[51]-[66]的高低字节中 (offsets 102-133; 来自 warpc_editor)
WARPC_STATUS_RESIST_FIELDS = [
    (f"status_resist{i}", 102 + i, f"{name}抵抗", f"{name}抵抗力")
    for i, name in enumerate(STATUS_NAMES + ["未知"])
]

# 攻击导致状态掩码 — 来自装备 v9[26]/v9[27] (来自 warpc_editor STATUS_FIELDS)
WARPC_CAUSE_MASK_FIELDS = [
    ("cause_mask1", 134, "攻击导致状态 1-16",  "攻击/命中时让目标进入的状态位掩码 (bit0-15; 来自装备 v9[26])"),
    ("cause_mask2", 136, "攻击导致状态 17-32", "攻击/命中时让目标进入的状态位掩码 (bit16-31; 来自装备 v9[27])"),
]

# 角色使用/装备权限 [77]-[81] — sub_41928C 按位与校验 (来自 warpc_editor CHAR_USE_RIGHT_FIELDS)
WARPC_USE_RIGHT_FIELDS = [
    ("use_right_medicine",  154, "药品权限",   "药品使用权限位掩码 (待验证); 全143条原始值=0"),
    ("use_right_item",      156, "道具权限",   "药品/道具使用权限位掩码 (1=战斗 2=非战斗 4=主角限定); 主角#0=7"),
    ("use_right_weapon",    158, "武器权限",   "武器装备权限位掩码 (1=刀 2=剑 4=枪 8=矛 16=弓 32=大刀 64=戟 128=锤); 主角#0=63"),
    ("use_right_armor",     160, "防具权限",   "防具装备权限位掩码 (1=衣袍 2=铠甲); 主角#0=3"),
    ("use_right_accessory", 162, "饰品权限",   "饰品装备权限位掩码 (待验证); 全143条原始值=0"),
]

# 装备技能 [82]-[87] — sub_42234C/sub_422BBC 应用 (来自 warpc_editor EQUIP_SKILL_FIELDS)
WARPC_EQUIP_SKILL_FIELDS = [
    ("equip_skill0", 164, "装备技能0", "装备技能槽0 → TKSkill (sub_42234C v4 loop)"),
    ("equip_skill1", 166, "装备技能1", "装备技能槽1 → TKSkill"),
    ("equip_skill2", 168, "装备技能2", "装备技能槽2 → TKSkill (sub_42234C: a2[84])"),
    ("equip_skill3", 170, "装备技能3", "装备技能槽3 → TKSkill (sub_42234C: a2[85])"),
    ("passive1",     172, "被动技能1", "被动技能1 → TKSkill (sub_422BBC)"),
    ("passive2",     174, "被动技能2", "被动技能2 → TKSkill (sub_422BBC)"),
]

# 标志位定义 — 用于 checkbox 弹窗选择
COMBAT_FLAG_BITS = [
    (0, "JP×2~3",           "战后技能点数×2~3 (無方戒; TKItem[20] bit0)"),
    (1, "战后全恢复+异常全解", "战斗结束HP/MP全恢复+清除异常 (無雙戒; bit1)"),
    (2, "经验×2~3平分队友",   "战斗经验×2~3并平分队友 (無嗔戒; bit2)"),
    (3, "经验独得",           "战斗经验归一人独享 (無道戒; bit3)"),
]

MOVE_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻 (sub_422BBC bit0)"),
    (1, "飙行", "移动范围扩大 (sub_422BBC bit1)"),
    (2, "搜宝", "获得额外宝物 (sub_422BBC bit2)"),
    (3, "解陷", "自动解除陷阱 (sub_422BBC bit3)"),
]

FLAG_DEFS = {
    'special_flag': ("特殊能力标志", COMBAT_FLAG_BITS),
    'move_flags':   ("移动特殊标志", MOVE_FLAG_BITS),
}

USE_RIGHT_DEFS = {
    'use_right_item': ("道具使用权限", [
        (1, "战斗", "可在战斗中使用"),
        (2, "非战斗", "可在非战斗中使用"),
        (4, "主角限定", "仅主角可使用"),
    ]),
    'use_right_weapon': ("武器装备权限", [
        (1, "刀", ""), (2, "剑", ""), (4, "枪", ""), (8, "矛", ""),
        (16, "弓", ""), (32, "大刀", ""), (64, "戟", ""), (128, "锤", ""),
    ]),
    'use_right_armor': ("防具装备权限", [
        (1, "衣袍", ""), (2, "铠甲", ""),
    ]),
}

SKILL_LEARN_COUNT = 344
SKILL_LEARN_STATES = [
    "0-不会",
    "1-等待学",
    "10-可以学",
    "20-组技能学会",
    "30-子技能学会",
]

# 技能学习状态 [88]-[259] — 344个技能×1byte, 存储在172个int16的高低字节中 (offsets 176-519; 来自 warpc_editor)
WARPC_SKILL_LEARN_DEF = ("skill_learn", 176, 344, "技能学习状态")

# ============================================================
# LZSS 压缩/解压 (SaveBufLZSS 格式, sub_4530A8/sub_452B14)
# ============================================================

def save_lzss_decompress(data):
    """解压 SaveBufLZSS 内部块 (sub_452B14).
    格式: [uncompressed_size:4][LZSS_stream]
    """
    if len(data) < 4:
        return b''
    total_size = struct.unpack_from('<I', data, 0)[0]
    w = bytearray([0x20] * 4096)
    wp = 4078
    out = bytearray()
    flags = 0
    pos = 4
    while pos < len(data) and len(out) < total_size:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1
        if flags & 1:
            if pos >= len(data):
                break
            b = data[pos]
            pos += 1
            out.append(b)
            w[wp] = b
            wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            b1 = data[pos]
            b2 = data[pos + 1]
            pos += 2
            ro = ((b2 & 0xF0) << 4) | b1
            rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]
                out.append(b)
                w[wp] = b
                wp = (wp + 1) & 0xFFF
    return bytes(out[:total_size])


def save_lzss_compress(data):
    """压缩为 SaveBufLZSS 内部块 (sub_4530A8).
    返回: [uncompressed_size:4][LZSS_stream]
    """
    src = data
    sl = len(src)
    flat = bytes(bytearray([0x20] * 4096) + src)
    tokens = []
    pos = 0
    while pos < sl:
        curr = 4096 + pos
        ms = min(18, sl - pos)
        bl = 0
        bo = 0
        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat[curr:curr + length]
                end = curr + length - 1
                start = max(0, curr - 4096)
                idx = flat.rfind(pat, start, end)
                if idx != -1:
                    bl = length
                    bo = (idx - 18) & 0xFFF
                    break
        if bl >= 3:
            tokens.append((False, bo, bl))
            pos += bl
        else:
            tokens.append((True, src[pos], 0))
            pos += 1
    stream = bytearray()
    ti = 0
    while ti < len(tokens):
        fb = 0
        be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]:
                fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]:
                stream.append(tokens[i][1])
            else:
                off = tokens[i][1]
                length = tokens[i][2]
                el = length - 3
                stream.append(off & 0xFF)
                stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    return struct.pack('<I', sl) + bytes(stream)


# ============================================================
# 文件加载/保存
# ============================================================

def load_save(sav_n_path):
    """加载 sav.N 存档文件, 返回 (game_state_bytes, seg1_bytes, seg2_bytes, seg3_bytes)."""
    with open(sav_n_path, 'rb') as f:
        raw = f.read()

    offset = 0

    # Block 1: 游戏状态
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Block1 大小")
    comp_size1 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4
    if offset + comp_size1 > len(raw):
        raise ValueError(f"Block1 数据不完整: 需要 {comp_size1} 字节")
    inner1 = raw[offset:offset + comp_size1]
    offset += comp_size1
    game_state = save_lzss_decompress(inner1)
    if len(game_state) != GAMESTATE_DECOMPRESSED:
        raise ValueError(
            f"Block1 解压大小 {len(game_state)} != {GAMESTATE_DECOMPRESSED}")

    # Block 2: TKMat
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Block2 大小")
    comp_size2 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4
    if offset + comp_size2 > len(raw):
        raise ValueError(f"Block2 数据不完整: 需要 {comp_size2} 字节")
    inner2 = raw[offset:offset + comp_size2]
    offset += comp_size2
    tkmat = save_lzss_decompress(inner2)
    if len(tkmat) != TKMAT_DECOMPRESSED:
        raise ValueError(f"Block2 解压大小 {len(tkmat)} != {TKMAT_DECOMPRESSED}")

    seg1 = bytearray(tkmat[0:SEG1_SIZE])                    # 3432B
    seg2 = bytearray(tkmat[SEG1_SIZE:SEG1_SIZE + SEG2_SIZE])  # 5768B
    seg3 = bytearray(tkmat[SEG1_SIZE + SEG2_SIZE:])           # 150722B
    game_state = bytearray(game_state)

    return game_state, seg1, seg2, seg3


def save_save(sav_n_path, game_state, seg1, seg2, seg3):
    """保存 sav.N 存档文件."""
    # 组装 TKMat
    tkmat = seg1 + seg2 + seg3
    assert len(tkmat) == TKMAT_DECOMPRESSED, \
        f"TKMat 大小 {len(tkmat)} != {TKMAT_DECOMPRESSED}"

    # 压缩
    inner1 = save_lzss_compress(bytes(game_state))
    inner2 = save_lzss_compress(bytes(tkmat))

    # 备份原文件
    if os.path.exists(sav_n_path):
        bak = sav_n_path + '.bak'
        try:
            with open(sav_n_path, 'rb') as s:
                with open(bak, 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass

    # 写入
    with open(sav_n_path, 'wb') as f:
        f.write(struct.pack('<I', len(inner1)))
        f.write(inner1)
        f.write(struct.pack('<I', len(inner2)))
        f.write(inner2)

    # 验证
    gs_v, s1_v, s2_v, s3_v = load_save(sav_n_path)
    if gs_v != game_state:
        raise RuntimeError("保存验证失败: Block1 回写不匹配!")
    if s1_v != seg1 or s2_v != seg2 or s3_v != seg3:
        raise RuntimeError("保存验证失败: Block2 回写不匹配!")


def load_sav_meta(sav_path):
    """加载 N.sav 元数据文件."""
    with open(sav_path, 'rb') as f:
        return bytearray(f.read())


def save_sav_meta(sav_path, data):
    """保存 N.sav 元数据文件."""
    assert len(data) == SAV_META_SIZE
    if os.path.exists(sav_path):
        bak = sav_path + '.bak'
        try:
            with open(sav_path, 'rb') as s:
                with open(bak, 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
    with open(sav_path, 'wb') as f:
        f.write(bytes(data))


# ============================================================
# WarPC 记录辅助函数
# ============================================================

def get_warpc_field(seg3, idx, byte_off):
    """读取 WarPC 单个 int16 字段."""
    off = idx * WARPC_REC + byte_off
    return struct.unpack_from('<h', seg3, off)[0]


def set_warpc_field(seg3, idx, byte_off, val):
    """写入 WarPC 单个 int16 字段."""
    off = idx * WARPC_REC + byte_off
    struct.pack_into('<h', seg3, off, val)


def get_warpc_status_slot(seg3, idx, slot_num):
    """读取状态槽 (status_id:byte, duration:byte). slot_num: 0-7"""
    off = idx * WARPC_REC + 86 + slot_num * 2
    return seg3[off], seg3[off + 1]  # (status_id, duration)


def set_warpc_status_slot(seg3, idx, slot_num, status_id, duration):
    """写入状态槽"""
    off = idx * WARPC_REC + 86 + slot_num * 2
    seg3[off] = status_id & 0xFF
    seg3[off + 1] = duration & 0xFF


def get_warpc_status_resist(seg3, idx, resist_idx):
    """读取状态抵抗值 (0-255). resist_idx: 0-31"""
    off = idx * WARPC_REC + 102 + resist_idx
    return seg3[off]


def set_warpc_status_resist(seg3, idx, resist_idx, value):
    """写入状态抵抗值"""
    off = idx * WARPC_REC + 102 + resist_idx
    seg3[off] = value & 0xFF


def get_warpc_skill_learn(seg3, idx, skill_idx):
    """读取技能学习状态 (0-255). skill_idx: 0-343"""
    off = idx * WARPC_REC + 176 + skill_idx
    return seg3[off]


def set_warpc_skill_learn(seg3, idx, skill_idx, value):
    """写入技能学习状态"""
    off = idx * WARPC_REC + 176 + skill_idx
    seg3[off] = value & 0xFF


# ============================================================
# GUI
# ============================================================

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_M = ('Consolas', 9)
FONT_HEX = ('Consolas', 9)


class SaveEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKS Save Editor")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1300x780")
        self.root.minsize(1000, 600)

        # 数据
        self.save_dir = None       # 存档目录 (包含 sav.N 和 N.sav)
        self.slot = 1              # 当前槽位
        self.game_state = None     # Block1 bytes
        self.seg1 = None           # 段1 bytes (3432)
        self.seg2 = None           # 段2 bytes (5768)
        self.seg3 = None           # 段3 bytes (150722)
        self.sav_meta = None       # .sav 元数据 (28B)
        self._dirty = False

        # WarPC 名称缓存 (需 TKT.dat)
        self.tkt = {}
        self.tkt_path = None

        # 额外数据加载
        self.skill_names = {}
        self._skill_types = {}
        self.item_names = {}
        self.item_idx_names = {}
        self._idx_to_id = {}
        self._id_to_idx = {}
        self._fa_sprites = []
        self._fa_photos = {}

        # WarPC 编辑器 widget 存储
        self._edit_vars = {}
        self._edit_extras = {}
        self._status_widgets = []
        self._status_resist_widgets = []
        self._skill_learn_widgets = []
        self._skill_learn_labels = []

        self._build_ui()
        self._set_ws('disabled')

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1300) // 2
        y = (sh - 780) // 2
        self.root.geometry(f'1300x780+{x}+{y}')

    # ========== UI 构建 ==========

    def _build_ui(self):
        # 菜单栏
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载存档目录…", command=self._load_save_dir,
                       accelerator="Ctrl+O")
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        self.root.bind('<Control-o>', lambda e: self._load_save_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Button(tb, text="加载存档", command=self._load_save_dir).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(tb, text="保存", command=self._save).pack(
            side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(tb, text="槽位:").pack(side=tk.LEFT)
        self.slot_var = tk.StringVar(value="1")
        cb = ttk.Combobox(tb, textvariable=self.slot_var, values=['1', '2'],
                          state='readonly', width=3)
        cb.pack(side=tk.LEFT, padx=2)
        cb.bind('<<ComboboxSelected>>', lambda e: self._switch_slot())
        ttk.Button(tb, text="切换槽位", command=self._switch_slot, width=8).pack(
            side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请加载存档目录")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # Notebook
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._build_save_info_tab()
        self._build_team_tab()
        self._build_global_tab()
        self._build_warpc_tab()

    def _set_ws(self, state):
        """递归设置所有子控件状态."""
        for tab in (self._info_frame, self._team_frame, self._global_frame,
                     self._warpc_frame):
            for child in tab.winfo_children():
                try:
                    child.configure(state=state)
                except Exception:
                    pass

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid',
                      borderwidth=1, font=FONT_S, wraplength=420,
                      padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None
        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    # ========== Tab 0: 存档信息 ==========

    def _build_save_info_tab(self):
        self._info_frame = ttk.Frame(self.nb, padding=8)
        self.nb.add(self._info_frame, text="存档信息")

        # .sav 元数据编辑
        lf = ttk.LabelFrame(self._info_frame, text="槽位元数据 (.sav 文件)", padding=8)
        lf.pack(fill=tk.X, padx=4, pady=4)

        self._meta_vars = {}
        row = 0
        # 字段布局: 已知结构
        # byte 0: unknown (值=0)
        # byte 1-6: always 0xFF (来源: 实测)
        # byte 7-8: word_07 (变化值)
        # byte 9-12: timestamp (FILETIME?)
        # byte 13-16: dword_13 (值=3)
        # byte 17-27: padding / slot status flags
        meta_fields = [
            ("meta_00", 0, "byte_00", "B", "字节0 (值=0)"),
            ("meta_07", 7, "word_07", "H", "word偏移7 (变化值)"),
            ("meta_09", 9, "timestamp", "I", "时间戳/校验"),
            ("meta_13", 13, "dword_13", "I", "dword偏移13 (常量=3)"),
            ("meta_17", 17, "dword_17", "I", "dword偏移17"),
            ("meta_21", 21, "dword_21", "I", "dword偏移21"),
        ]
        for key, off, label, fmt, cmt in meta_fields:
            ttk.Label(lf, text=label, font=FONT_S).grid(
                row=row, column=0, sticky='w', padx=4, pady=1)
            sv = tk.StringVar()
            self._meta_vars[key] = (sv, off, fmt)
            ttk.Entry(lf, textvariable=sv, width=16, font=FONT_M).grid(
                row=row, column=1, sticky='w', padx=4)
            ttk.Label(lf, text=cmt, font=FONT_S, foreground='#888').grid(
                row=row, column=2, sticky='w', padx=4)
            row += 1

        # 完整 hex 显示
        ttk.Label(lf, text="完整28字节 (hex):", font=FONT_S).grid(
            row=row, column=0, sticky='nw', padx=4, pady=(8, 1))
        self._meta_hex_var = tk.StringVar()
        ttk.Entry(lf, textvariable=self._meta_hex_var, font=FONT_M, width=60).grid(
            row=row, column=1, columnspan=2, sticky='ew', padx=4)

        # 存档信息摘要
        lf2 = ttk.LabelFrame(self._info_frame, text="存档摘要", padding=8)
        lf2.pack(fill=tk.X, padx=4, pady=4)
        self._summary_text = tk.Text(lf2, height=10, width=80,
                                      font=FONT_M, state='disabled')
        self._summary_text.pack(fill=tk.BOTH, expand=True)

    # ========== Tab 1: 队伍数据 ==========

    def _build_team_tab(self):
        self._team_frame = ttk.Frame(self.nb, padding=8)
        self.nb.add(self._team_frame, text="队伍数据")

        self._team_vars = {}

        # 队伍成员
        lf_team = ttk.LabelFrame(self._team_frame,
                                  text="队伍成员 (word_75688C[6])", padding=8)
        lf_team.pack(fill=tk.X, padx=4, pady=4)
        self._team_member_vars = []
        self._team_member_name_labels = []
        for i in range(6):
            frm = ttk.Frame(lf_team)
            frm.pack(side=tk.LEFT, padx=8, pady=2)
            ttk.Label(frm, text=f"成员{i+1}").pack()
            sv = tk.StringVar()
            self._team_member_vars.append(sv)
            cb = ttk.Combobox(frm, textvariable=sv, width=8,
                              state='readonly', values=['-1-空'] + [str(x) for x in range(144)])
            cb.pack()
            name_lbl = ttk.Label(frm, text="", font=FONT_S, foreground='#888')
            name_lbl.pack()
            self._team_member_name_labels.append(name_lbl)

        # 资源/金钱
        lf_res = ttk.LabelFrame(self._team_frame,
                                 text="金钱与四维 (word_756882~75688A)", padding=8)
        lf_res.pack(fill=tk.X, padx=4, pady=4)
        res_fields = [
            ("gold", 0, 2, "金钱"),
            ("wisdom", 1, 2, "智慧"),
            ("benevolence", 2, 2, "仁德"),
            ("courage", 3, 2, "勇气"),
            ("medicine", 4, 2, "医术"),
        ]
        for key, col, width, label in res_fields:
            frm = ttk.Frame(lf_res)
            frm.pack(side=tk.LEFT, padx=8, pady=2)
            ttk.Label(frm, text=label, font=FONT_S).pack()
            sv = tk.StringVar()
            self._team_vars[key] = sv
            ttk.Entry(frm, textvariable=sv, width=8, font=FONT_M).pack()

        # 战斗统计
        lf_battle = ttk.LabelFrame(self._team_frame,
                                    text="战斗统计 (word_757EBA~757F06)", padding=8)
        lf_battle.pack(fill=tk.X, padx=4, pady=4)
        for fi, (key, off, size, label, fmt, cmt) in enumerate(SEG2_BATTLE_FIELDS):
            frm = ttk.Frame(lf_battle)
            frm.pack(side=tk.LEFT, padx=8, pady=2)
            ttk.Label(frm, text=label, font=FONT_S).pack()
            sv = tk.StringVar()
            self._team_vars[key] = sv
            ttk.Entry(frm, textvariable=sv, width=8, font=FONT_M).pack()

        # 库存摘要
        lf_inv = ttk.LabelFrame(self._team_frame,
                                 text="库存摘要 (word_7570A8)", padding=8)
        lf_inv.pack(fill=tk.X, padx=4, pady=4)
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        frm = ttk.Frame(lf_inv)
        frm.pack(side=tk.LEFT, padx=8, pady=2)
        ttk.Label(frm, text=label, font=FONT_S).pack()
        self._team_inv_count_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self._team_inv_count_var, width=8, font=FONT_M).pack()
        ttk.Label(frm, text="(库存物品种类数)", font=FONT_S, foreground='#888').pack()

    # ========== Tab 2: 全局状态 ==========

    def _build_global_tab(self):
        self._global_frame = ttk.Frame(self.nb, padding=8)
        self.nb.add(self._global_frame, text="全局状态")

        # 可滚动画布
        canvas = tk.Canvas(self._global_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self._global_frame, orient=tk.VERTICAL,
                                   command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>",
                         lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._global_vars = {}
        self._global_array_vars = {}
        self._seg2_gap_vars = {}

        # --- 基本状态 ---
        lf = ttk.LabelFrame(scrollable, text="基本状态", padding=8)
        lf.pack(fill=tk.X, padx=4, pady=4)
        row = 0
        for key, off, size, label, fmt, cmt in SEG1_BASIC_FIELDS:
            self._add_global_field(lf, key, off, size, label, fmt, cmt, row)
            row += 1

        # --- 编成槽 ---
        lf_slot = ttk.LabelFrame(scrollable, text="编成槽状态", padding=8)
        lf_slot.pack(fill=tk.X, padx=4, pady=4)
        row = 0
        for key, off, size, label, fmt, cmt in SEG1_SLOT_FIELDS:
            self._add_global_field(lf_slot, key, off, size, label, fmt, cmt, row)
            row += 1

        # --- 地图相关 ---
        lf_map = ttk.LabelFrame(scrollable, text="地图相关", padding=8)
        lf_map.pack(fill=tk.X, padx=4, pady=4)
        row = 0
        for key, off, size, label, fmt, cmt in SEG1_MAP_FIELDS:
            self._add_global_field(lf_map, key, off, size, label, fmt, cmt, row)
            row += 1

        # --- 事件系统 ---
        lf_evt = ttk.LabelFrame(scrollable, text="事件系统", padding=8)
        lf_evt.pack(fill=tk.X, padx=4, pady=4)
        row = 0
        for key, off, size, label, fmt, cmt in SEG1_EVENT_FIELDS:
            self._add_global_field(lf_evt, key, off, size, label, fmt, cmt, row)
            row += 1

        # --- 数组字段 ---
        for arr_key, arr_off, arr_cnt, arr_esz, arr_label, arr_cmt in SEG1_ARRAYS:
            self._build_array_section(scrollable, arr_key, arr_off, arr_cnt,
                                       arr_label, arr_cmt)

        # --- SEG2 间隙字段 ---
        lf_seg2_gap = ttk.LabelFrame(scrollable, text="SEG2间隙字段", padding=8)
        lf_seg2_gap.pack(fill=tk.X, padx=4, pady=4)
        row = 0
        for key, off, size, label, fmt, cmt in SEG2_GAP_FIELDS_1:
            ttk.Label(lf_seg2_gap, text=f"{label} (未验证) [+0x{off:X}]",
                      font=FONT_S).grid(row=row, column=0, sticky='w', padx=4, pady=1)
            sv = tk.StringVar()
            self._seg2_gap_vars[key] = (sv, off, size, fmt)
            ent = ttk.Entry(lf_seg2_gap, textvariable=sv, width=18, font=FONT_M)
            ent.grid(row=row, column=1, sticky='w', padx=4)
            lbl = ttk.Label(lf_seg2_gap, text=cmt, font=FONT_S, foreground='#888')
            lbl.grid(row=row, column=2, sticky='w', padx=4)
            self._bind_tooltip(ent, cmt)
            self._bind_tooltip(lbl, cmt)
            row += 1

    def _add_global_field(self, parent, key, off, size, label, fmt, cmt, row):
        ttk.Label(parent, text=f"{label} [+0x{off:X}]", font=FONT_S).grid(
            row=row, column=0, sticky='w', padx=4, pady=1)
        sv = tk.StringVar()
        self._global_vars[key] = (sv, off, size, fmt)
        ttk.Entry(parent, textvariable=sv, width=18, font=FONT_M).grid(
            row=row, column=1, sticky='w', padx=4)
        lbl = ttk.Label(parent, text=cmt, font=FONT_S, foreground='#888')
        lbl.grid(row=row, column=2, sticky='w', padx=4)
        self._bind_tooltip(lbl, cmt)

    def _build_array_section(self, parent, key, off, cnt, label, cmt):
        lf = ttk.LabelFrame(parent, text=f"{label} [{cnt}个]", padding=8)
        lf.pack(fill=tk.X, padx=4, pady=4)

        if cnt <= 32:
            self._build_small_array(lf, key, off, cnt, label)
        elif cnt <= 256:
            self._build_medium_array(lf, key, off, cnt, label)
        else:
            self._build_large_array(lf, key, off, cnt, label)

    def _build_small_array(self, parent, key, off, cnt, label):
        """≤32项: 网格展示"""
        self._global_array_vars[key] = []
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)
        cols = min(cnt, 8)
        for i in range(cnt):
            r, c = divmod(i, cols)
            sv = tk.StringVar()
            self._global_array_vars[key].append(sv)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, padx=1, pady=1)
            ttk.Label(frm, text=str(i), font=('Consolas', 6),
                      foreground='#888').pack()
            ttk.Entry(frm, textvariable=sv, width=6, font=('Consolas', 7)).pack()

    def _build_medium_array(self, parent, key, off, cnt, label):
        """≤256项: 可滚动25列网格"""
        self._global_array_vars[key] = []
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)
        for i in range(cnt):
            r, c = divmod(i, 25)
            sv = tk.StringVar()
            self._global_array_vars[key].append(sv)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, padx=1, pady=1)
            ttk.Label(frm, text=str(i), font=('Consolas', 5),
                      foreground='#888').pack()
            ttk.Entry(frm, textvariable=sv, width=4, font=('Consolas', 6)).pack()

    def _build_large_array(self, parent, key, off, cnt, label):
        """>256项: 分页视图"""
        self._global_array_vars[key] = {}
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill=tk.X)
        ttk.Label(ctrl, text=f"共{cnt}项, 页:", font=FONT_S).pack(side=tk.LEFT)
        page_var = tk.StringVar(value="0")
        ttk.Entry(ctrl, textvariable=page_var, width=6, font=FONT_M).pack(side=tk.LEFT, padx=2)
        items_per_page = 100
        total_pages = (cnt + items_per_page - 1) // items_per_page
        ttk.Label(ctrl, text=f"/ {total_pages-1}", font=FONT_S).pack(side=tk.LEFT)

        display_frame = ttk.Frame(parent)
        display_frame.pack(fill=tk.X, pady=2)

        def _show_page(*args):
            try:
                pg = int(page_var.get())
            except ValueError:
                return
            start = pg * items_per_page
            end = min(start + items_per_page, cnt)
            for w in display_frame.winfo_children():
                w.destroy()
            page_vars = []
            for i in range(start, end):
                r, c = divmod(i - start, 25)
                sv = tk.StringVar()
                page_vars.append((i, sv))
                frm = ttk.Frame(display_frame)
                frm.grid(row=r, column=c, padx=1, pady=1)
                ttk.Label(frm, text=str(i), font=('Consolas', 5),
                          foreground='#888').pack()
                ttk.Entry(frm, textvariable=sv, width=4, font=('Consolas', 6)).pack()
            self._global_array_vars[key][pg] = page_vars

        page_var.trace_add('write', _show_page)
        page_var.set("0")

    # ========== Tab 2: WarPC 数据 ==========

    def _build_warpc_tab(self):
        self._warpc_frame = ttk.Frame(self.nb, padding=8)
        self.nb.add(self._warpc_frame, text="WarPC数据")

        # 上部: 角色列表
        paned = ttk.PanedWindow(self._warpc_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左侧: TreeView
        lf = ttk.Frame(paned)
        paned.add(lf, weight=1)

        # 搜索/过滤栏
        filter_frame = ttk.Frame(lf)
        filter_frame.pack(fill=tk.X, pady=(0, 4))
        self._warpc_search_var = tk.StringVar()
        search_entry = ttk.Entry(filter_frame, textvariable=self._warpc_search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.insert(0, "搜索角色...")

        def _on_search_focus_in(e):
            if search_entry.get() == "搜索角色...":
                search_entry.delete(0, tk.END)

        def _on_search_focus_out(e):
            if not search_entry.get():
                search_entry.insert(0, "搜索角色...")

        search_entry.bind('<FocusIn>', _on_search_focus_in)
        search_entry.bind('<FocusOut>', _on_search_focus_out)
        self._warpc_search_var.trace_add('write', lambda *args: self._on_warpc_search_changed())

        self._warpc_filter_var = tk.StringVar(value="全部")
        filter_combo = ttk.Combobox(filter_frame, textvariable=self._warpc_filter_var,
                                    values=["全部", "我方", "敌方"], state='readonly', width=6)
        filter_combo.pack(side=tk.LEFT, padx=(4, 0))
        filter_combo.bind('<<ComboboxSelected>>', lambda e: self._on_warpc_filter_changed())

        # TreeView
        tree_frame = ttk.Frame(lf)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        cols = ('idx', 'name', 'level', 'role', 'hp', 'mp')
        self.warpc_tree = ttk.Treeview(tree_frame, columns=cols, show='headings',
                                        selectmode='browse')
        self.warpc_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                   command=self.warpc_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.warpc_tree.configure(yscrollcommand=scrollbar.set)
        for cid, cn, cw in [
            ('idx', '#', 35), ('name', '名称', 100), ('level', 'LV', 40),
            ('role', '身份', 45), ('hp', 'HP', 65), ('mp', 'MP', 65),
        ]:
            self.warpc_tree.heading(cid, text=cn)
            self.warpc_tree.column(cid, width=cw, minwidth=cw, anchor='center')
        self.warpc_tree.bind('<Double-1>', lambda e: self._on_warpc_select())
        self.warpc_tree.bind('<Return>', lambda e: self._on_warpc_select())

        # 右侧: 编辑面板
        rf = ttk.Frame(paned)
        paned.add(rf, weight=2)
        self._warpc_right_frame = rf

        self.warpc_widgets = {}
        self._warpc_edit_vars = {}
        self._warpc_cur_idx = -1
        self._warpc_editor_built = False

        ttk.Label(self._warpc_right_frame, text="双击左侧角色编辑",
                   font=FONT).pack(pady=20)
        self._warpc_status = ttk.Label(self._warpc_right_frame, text="",
                                        foreground='gray')
        self._warpc_status.pack()

    def _build_warpc_editor(self):
        """为当前选中的 WarPC 角色构建编辑控件."""
        if self._warpc_editor_built:
            return
        idx = self._warpc_cur_idx
        if idx < 0 or self.seg3 is None:
            return
        self._warpc_editor_built = True

        # 清除占位符
        for w in self._warpc_right_frame.winfo_children():
            w.destroy()

        self._warpc_status = ttk.Label(self._warpc_right_frame, text="",
                                        foreground='gray')
        self._warpc_status.pack(fill=tk.X, padx=4, pady=2)

        nb = ttk.Notebook(self._warpc_right_frame)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._warpc_nb = nb

        self._build_warpc_core_tab(nb)
        self._build_warpc_equip_tab(nb)
        self._build_warpc_raw_tab(nb)

        btn_frame = ttk.Frame(self._warpc_right_frame)
        btn_frame.pack(pady=4)
        ttk.Button(btn_frame, text="应用修改",
                   command=self._apply_warpc_edit).pack(side=tk.LEFT, padx=4)

    def _build_stat_fields(self):
        fields = []
        for i, name in enumerate(STAT_NAMES):
            bo = STAT_OFFSETS[i]
            fields.append((f"stat_{i}_base", bo, f"{name}(基础)"))
            fields.append((f"stat_{i}_cur", bo + 2, f"{name}(当前)"))
        return fields

    def _get_warpc_var(self, offset):
        if offset not in self.warpc_widgets:
            self.warpc_widgets[offset] = tk.StringVar()
        return self.warpc_widgets[offset]

    def _get_warpc_field_name(self, offset):
        if not hasattr(self, '_warpc_field_name_map'):
            self._warpc_field_name_map = {}
            for group in [WARPC_IDENTITY, WARPC_HPMP, WARPC_SKILL_BONUS,
                          WARPC_CHAR_ATTR, WARPC_EQUIP, WARPC_GROWTH,
                          WARPC_BATTLE_REWARD, WARPC_DROP,
                          WARPC_REACTION_FIELDS, WARPC_STATUS_SLOT_FIELDS,
                          WARPC_STATUS_RESIST_FIELDS, WARPC_CAUSE_MASK_FIELDS,
                          WARPC_USE_RIGHT_FIELDS, WARPC_EQUIP_SKILL_FIELDS]:
                for item in group:
                    fn, fo, fl = item[0], item[1], item[2]
                    self._warpc_field_name_map[fo] = fl
            for i, name in enumerate(STAT_NAMES):
                bo = STAT_OFFSETS[i]
                self._warpc_field_name_map[bo] = f"{name}(基础)"
                self._warpc_field_name_map[bo + 2] = f"{name}(当前)"
        return self._warpc_field_name_map.get(offset, f"[{offset//2}]")

    def _skill_val_to_text(self, val):
        if val == 0:
            return "0-不会"
        if 1 <= val <= 9:
            return f"{val}-学习中"
        if 10 <= val <= 19:
            return f"{val}-可学"
        if val == 20:
            return "20-父技学会"
        if val == 30:
            return "30-独立技学会"
        return str(val)

    def _skill_text_to_val(self, text):
        if isinstance(text, int):
            return text
        s = str(text).strip()
        if '-' in s:
            s = s.split('-')[0]
        return int(s)

    # ---------- WarPC 弹窗对话框 ----------

    def _center_dialog(self, dlg, w, h):
        dlg.withdraw(); dlg.geometry(f'{w}x{h}'); dlg.update_idletasks()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        x = rx + (rw - w) // 2; y = ry + (rh - h) // 2
        dlg.geometry(f'+{x}+{y}'); dlg.deiconify()

    def _pick_flags(self, fn):
        """弹窗选择标志位 (Checkbox 位掩码)"""
        if fn not in FLAG_DEFS: return
        title, bits = FLAG_DEFS[fn]
        dlg = tk.Toplevel(self.root); dlg.title(f"选择{title} (位掩码)")
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 400, 250)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        wrap = ttk.Frame(dlg, padding=8); wrap.pack(fill=tk.BOTH, expand=True)
        vars_ = []
        for bit, name, desc in bits:
            v = tk.BooleanVar(value=bool(cur_val & (1 << bit)))
            row = ttk.Frame(wrap); row.pack(anchor=tk.W, fill=tk.X, pady=1)
            ttk.Checkbutton(row, text=f"bit{bit} {name}", variable=v).pack(side=tk.LEFT)
            ttk.Label(row, text=desc, foreground='#999', font=('', 7)).pack(side=tk.LEFT, padx=(8, 0))
            vars_.append((bit, v))
        bf = ttk.Frame(dlg, padding=4); bf.pack(side=tk.BOTTOM, fill=tk.X)
        def _ok():
            m = 0
            for bit, v in vars_:
                if v.get(): m |= (1 << bit)
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_flags_label(fn, m); dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for _, v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_flags_label(self, fn, val):
        """更新标志位的标签显示"""
        if fn not in FLAG_DEFS: return
        mask = val & 0xFFFF
        _, bits = FLAG_DEFS[fn]
        sel = [name for bit, name, _ in bits if mask & (1 << bit)]
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _pick_use_right(self, fn):
        """弹窗选择使用/装备权限 (位掩码多选)"""
        if fn not in USE_RIGHT_DEFS: return
        title, opts = USE_RIGHT_DEFS[fn]
        dlg = tk.Toplevel(self.root); dlg.title(f"选择{title} (位掩码)")
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 360, 60 + max(len(opts), 2) * 32)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        wrap = ttk.Frame(dlg, padding=8); wrap.pack(fill=tk.BOTH, expand=True)
        vars_ = []
        for bit, name, desc in opts:
            v = tk.BooleanVar(value=bool(cur_val & bit))
            row = ttk.Frame(wrap); row.pack(anchor=tk.W, fill=tk.X, pady=1)
            ttk.Checkbutton(row, text=f"{name}", variable=v).pack(side=tk.LEFT)
            if desc:
                ttk.Label(row, text=desc, foreground='#999', font=('', 7)).pack(side=tk.LEFT, padx=(8, 0))
            vars_.append((bit, v))
        bf = ttk.Frame(dlg, padding=4); bf.pack(side=tk.BOTTOM, fill=tk.X)
        def _ok():
            m = 0
            for bit, v in vars_:
                if v.get(): m += bit
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_use_right_label(fn, m); dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for _, v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_use_right_label(self, fn, val):
        """更新权限字段的标签显示"""
        if fn not in USE_RIGHT_DEFS: return
        _, opts = USE_RIGHT_DEFS[fn]
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in opts if (mask & bit)]
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _pick_status(self, fn):
        """弹窗选择状态位掩码 (16个复选框)"""
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = tk.Toplevel(self.root); dlg.title(title)
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 320, 500)
        base = 0 if fn.endswith('_mask1') else 16
        cur_mask = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        vars_ = []
        wrap = ttk.Frame(dlg, padding=8); wrap.pack(fill=tk.BOTH, expand=True)
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES): break
            v = tk.BooleanVar(value=bool(cur_mask & (1 << i)))
            ttk.Checkbutton(wrap, text=f"{idx}. {STATUS_NAMES[idx]}",
                             variable=v).pack(anchor=tk.W, pady=1)
            vars_.append(v)
        bf = ttk.Frame(dlg); bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            m = 0
            for i, v in enumerate(vars_):
                if v.get(): m |= (1 << i)
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_status_label(fn, m & 0xFFFF); dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_status_label(self, fn, mask):
        """更新状态掩码标签显示"""
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _pick_skill(self, fn):
        """弹出技能选择对话框 — 加载 TKSkill.dat 显示技能名称"""
        if self.seg3 is None: return
        dlg = tk.Toplevel(self.root); dlg.title('选择技能')
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 550, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)

        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text='搜索:').pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)

        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('index', 'type', 'name'),
                            show='headings', selectmode='browse', height=20)
        tree.heading('index', text='技能#'); tree.column('index', width=55, anchor='center')
        tree.heading('type', text='类型'); tree.column('type', width=55, anchor='center')
        tree.heading('name', text='技能名称'); tree.column('name', width=400, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        type_names = {0: '指令', 1: '主动', 2: '被动', 3: '移动'}
        items = [(i, type_names.get(self._skill_types.get(i, -1), '?'),
                  self.skill_names.get(i, f'技能#{i}'))
                 for i in sorted(self.skill_names.keys())]

        def _refresh(q=''):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for idx, tp, nm in items:
                if ql and ql not in f'{idx} {tp} {nm}'.lower(): continue
                iid = tree.insert('', 'end', values=(idx, tp, nm))
                if idx == cur_val: tree.selection_set(iid); tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))

        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                sk_name = self.skill_names.get(int(v[0]), '')
                if fn in self._edit_extras:
                    self._edit_extras[fn].config(text=sk_name)
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        def _clear():
            self._edit_vars[fn].set('-1')
            if fn in self._edit_extras:
                self._edit_extras[fn].config(text='(未装备)')
            dlg.destroy()
        ttk.Button(bf, text='清空', command=_clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text='确定', command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_item(self, fn):
        """弹出物品选择对话框 — 装备索引(按TKItem下标)或装备ID"""
        if self.seg3 is None: return
        is_idx = fn.startswith('equip_idx')
        dlg = tk.Toplevel(self.root); dlg.title('选择物品')
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 550, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)

        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text='搜索:').pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)

        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        id_label = '物品#' if is_idx else '物品ID'
        tree = ttk.Treeview(lf2, columns=('key', 'name'),
                            show='headings', selectmode='browse', height=20)
        tree.heading('key', text=id_label); tree.column('key', width=80, anchor='center')
        tree.heading('name', text='物品名称'); tree.column('name', width=430, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        lookup = self.item_idx_names if is_idx else self.item_names
        items = sorted(lookup.items(), key=lambda x: x[0])

        def _refresh(q=''):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for key_val, nm in items:
                if ql and ql not in f'{key_val} {nm}'.lower(): continue
                iid = tree.insert('', 'end', values=(key_val, nm))
                if key_val == cur_val: tree.selection_set(iid); tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))

        def _sync_pair(key_val, nm):
            """双向同步: equip_idx ↔ equip_id"""
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_id{slot}'
                pair_val = self._idx_to_id.get(key_val, 0)
            else:
                pair_fn = f'equip_idx{slot}'
                pair_val = self._id_to_idx.get(key_val, -1)
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].set(str(pair_val))
            if pair_fn in self._edit_extras:
                if pair_val == -1:
                    self._edit_extras[pair_fn].config(text='(未装备)')
                elif is_idx:
                    self._edit_extras[pair_fn].config(
                        text=self.item_names.get(pair_val, f'物品#{pair_val}'))
                else:
                    self._edit_extras[pair_fn].config(
                        text=self.item_idx_names.get(pair_val, f'物品#{pair_val}'))

        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                if fn in self._edit_extras:
                    self._edit_extras[fn].config(text=v[1] if v[1] else '')
                _sync_pair(v[0], v[1])
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        clear_val = '-1' if is_idx else '0'
        clear_text = '(未装备)' if is_idx else ''
        def _clear():
            self._edit_vars[fn].set(clear_val)
            if fn in self._edit_extras:
                self._edit_extras[fn].config(text=clear_text)
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_idx{slot}'
            else:
                pair_fn = f'equip_id{slot}'
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].set('0' if is_idx else '-1')
            if pair_fn in self._edit_extras:
                self._edit_extras[pair_fn].config(text='' if is_idx else '(未装备)')
            dlg.destroy()
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text='清空', command=_clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text='确定', command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_portrait(self):
        """弹窗选择头像 — 展示 Fa.JVG 中所有大幅图 (偶数索引)"""
        if not self._fa_sprites:
            messagebox.showinfo("提示", "未加载 Fa.JVG 头像文件"); return
        fn = 'portrait'; cur_val = int(self._edit_vars[fn].get() or 0)
        dlg = tk.Toplevel(self.root); dlg.title("选择头像 (Fa.JVG 大幅图)")
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 800, 560)
        dlg.grid_rowconfigure(0, weight=1); dlg.grid_columnconfigure(0, weight=1)
        dlg.resizable(True, True)
        cvs = tk.Canvas(dlg, highlightthickness=0)
        sb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=cvs.yview)
        grid_frame = ttk.Frame(cvs)
        cvs.create_window((0,0), window=grid_frame, anchor='nw')
        cvs.configure(yscrollcommand=sb.set)
        cvs.grid(row=0, column=0, sticky='nsew', padx=4, pady=(4,0))
        sb.grid(row=0, column=1, sticky='ns', pady=(4,0))
        def _mw(e): cvs.yview_scroll(int(-1*(e.delta/120)), "units")
        cvs.bind("<Enter>", lambda e: cvs.bind_all("<MouseWheel>", _mw))
        cvs.bind("<Leave>", lambda e: cvs.unbind_all("<MouseWheel>"))
        bf = ttk.Frame(dlg, padding=4)
        bf.grid(row=1, column=0, columnspan=2, sticky='ew')
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Label(bf, text="点击头像选择，数字为头像索引", foreground='#666', font=FONT_S).pack(side=tk.LEFT, padx=4)

        large_indices = [(si, si // 2) for si in range(0, len(self._fa_sprites), 2)
                         if self._fa_sprites[si] is not None]
        CELL_W = 68; _last_cols = [0]
        def _build_grid(cols=None):
            if cols is None:
                cols = max(4, (cvs.winfo_width() - 4) // CELL_W)
                if cols <= 0: cols = 6
            if cols == _last_cols[0]: return
            _last_cols[0] = cols
            for w in grid_frame.winfo_children(): w.destroy()
            photo_refs = []
            for sprite_idx, portrait_idx in large_indices:
                row, col = divmod(portrait_idx, cols)
                frm = ttk.Frame(grid_frame)
                frm.grid(row=row, column=col, padx=1, pady=1)
                photo = self._get_fa_photo(sprite_idx, (64, 64))
                if portrait_idx == cur_val:
                    frm.configure(relief='solid', borderwidth=2)
                if photo:
                    photo_refs.append(photo)
                    lbl = ttk.Label(frm, image=photo)
                else:
                    lbl = ttk.Label(frm, text=str(portrait_idx), font=FONT_S, width=8)
                lbl.pack()
                ttk.Label(frm, text=str(portrait_idx), font=('', 7)).pack()
                frm.bind('<Button-1>', lambda e, v=portrait_idx: (
                    self._edit_vars[fn].set(str(v)), dlg.destroy()))
                lbl.bind('<Button-1>', lambda e, v=portrait_idx: (
                    self._edit_vars[fn].set(str(v)), dlg.destroy()))
            grid_frame.update_idletasks()
            cvs.configure(scrollregion=cvs.bbox('all'))
            if cur_val >= 0 and grid_frame.winfo_children():
                row_h = grid_frame.winfo_children()[0].winfo_reqheight() + 2
                y = (cur_val // cols) * row_h
                total_h = cvs.bbox('all')[3] if cvs.bbox('all') else 1
                cvs.yview_moveto(min(1.0, max(0, y - 100) / total_h))

        cvs.bind('<Configure>', lambda e: _build_grid(), add='+')
        dlg.after(100, _build_grid)
        dlg.wait_window()

    # ---------- WarPC UI 构建辅助 ----------

    def _build_section(self, parent, title, fields, ft='int'):
        lf = ttk.LabelFrame(parent, text=title, padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        cols = 4
        for fi, item in enumerate(fields):
            fn, fo, fl = item[0], item[1], item[2]
            cmt = item[3] if len(item) > 3 else ""
            if fn in FLAG_DEFS:
                field_ft = 'flags'
            elif fn in USE_RIGHT_DEFS:
                field_ft = 'use_right'
            elif fn.startswith('cause_mask'):
                field_ft = 'mask'
            else:
                field_ft = ft
            self._build_field_widget(grid, fi // cols, fi % cols, fn, fo, fl, 10, cmt, field_ft)

    def _build_field_widget(self, parent, row, col, fn, fo, fl, fw, cmt, ft='int'):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=2, pady=1)
        lbl = ttk.Label(frm, text=fl, font=FONT_S); lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo//2}] byte {fo}: {cmt}")
        ev = tk.StringVar(); self._edit_vars[fn] = ev
        if fn == 'role':
            cb = ttk.Combobox(frm, state='readonly', values=['-1-我方', '0-敌方'],
                              width=fw + 3, font=FONT)
            cb.pack(fill=tk.X)
            self._edit_extras[fn] = cb
        elif fn == 'reaction_group':
            cb = ttk.Combobox(frm, state='readonly', values=REACTION_GROUP_VALUES,
                              width=fw + 3, font=FONT)
            cb.pack(fill=tk.X)
            self._edit_extras[fn] = cb
        elif ft in ('skill_pick', 'item_pick'):
            pick_fn = self._pick_skill if ft == 'skill_pick' else self._pick_item
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text='…', width=2,
                       command=lambda f=fn: pick_fn(f)).pack(side=tk.LEFT, padx=1)
            color = '#3366cc' if ft == 'skill_pick' else '#CC6633'
            self._edit_extras[fn] = ttk.Label(frm, text='', foreground=color,
                                               font=FONT_S, wraplength=150)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'flags':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_flags(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666',
                                               font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'use_right':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_use_right(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666',
                                               font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'mask':
            is_cause = fn.startswith('cause_')
            btn_text = "选择导致状态…" if is_cause else "选择解除状态…"
            color = '#CC3333' if is_cause else '#3366cc'
            ttk.Button(frm, text=btn_text, width=fw + 3,
                       command=lambda f=fn: self._pick_status(f)).pack(fill=tk.X)
            self._edit_extras[fn] = ttk.Label(frm, text="(无)", foreground=color,
                                               font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        elif fn == 'portrait':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda: self._pick_portrait()).pack(side=tk.LEFT, padx=1)
        else:
            ttk.Entry(frm, textvariable=ev, width=fw, font=FONT).pack(fill=tk.X)

    def _build_stat_row(self, parent):
        """八属性 — 一行八列, 每列(名称 + 基础 + 当前)"""
        lf = ttk.LabelFrame(parent, text="八属性 (基础/当前 = 基础+装备加成)", padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        for c in range(8):
            lf.columnconfigure(c, weight=1, minsize=90)

        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_OFFSETS)):
            col = ttk.Frame(lf); col.grid(row=0, column=ci, sticky='n', padx=3, pady=2)

            lbl = ttk.Label(col, text=name, font=('', 9, 'bold'))
            lbl.pack(anchor=tk.CENTER)

            fn_base = f"{short}_base"
            frm_b = ttk.Frame(col); frm_b.pack(fill=tk.X, pady=(2, 0))
            ttk.Label(frm_b, text="基础", font=FONT_S, foreground='#888').pack(side=tk.LEFT)
            ev_b = tk.StringVar(); self._edit_vars[fn_base] = ev_b
            ttk.Entry(frm_b, textvariable=ev_b, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_b, f"[{bo//2}] {name}基础值 (sub_42234C: a2[{11+ci*2}] initial)")

            fn_cur = f"{short}_cur"
            frm_c = ttk.Frame(col); frm_c.pack(fill=tk.X)
            ttk.Label(frm_c, text="当前", font=FONT_S, foreground='#228B22').pack(side=tk.LEFT)
            ev_c = tk.StringVar(); self._edit_vars[fn_cur] = ev_c
            ttk.Entry(frm_c, textvariable=ev_c, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_c, f"[{bo//2+1}] {name}当前值 (基础+装备; sub_42234C L63-70)")

    def _build_status_slots(self, parent):
        """身上状态 [43]-[50] — 8槽, 每槽(status_id, duration)"""
        lf = ttk.LabelFrame(parent, text="身上状态 [43]-[50] (sub_41E40C 验证: 8槽×2字节=状态ID+持续回合)", padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        self._status_widgets = []
        status_options = ["(无)"] + [f"{i+1}-{STATUS_NAMES[i]}" for i in range(len(STATUS_NAMES))]
        for si, item in enumerate(WARPC_STATUS_SLOT_FIELDS):
            fn, fo, fl = item[0], item[1], item[2]
            cmt = item[3] if len(item) > 3 else ""
            r, c = divmod(si, 4)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            ttl = ttk.Frame(col); ttl.pack(fill=tk.X)
            lbl = ttk.Label(ttl, text=f"状态{si}", font=FONT)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{fo//2}] bo={fo}: {cmt}")
            ttk.Label(ttl, text="持续回合", font=FONT, foreground='#888').pack(side=tk.RIGHT)
            inp = ttk.Frame(col); inp.pack(fill=tk.X, pady=(1, 0))
            cb = ttk.Combobox(inp, values=status_options, state='readonly', width=6, font=FONT)
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ev_dur = tk.StringVar(value="0")
            ttk.Entry(inp, textvariable=ev_dur, width=4, font=FONT, justify='center').pack(side=tk.RIGHT, padx=(1, 0))
            self._status_widgets.append((fn, fo, cb, ev_dur))
            self._edit_vars[fn] = tk.StringVar()

    def _build_status_resist(self, parent):
        """状态抵抗 — 32状态×1byte, 存储在[51]-[66]的每个字节中"""
        lf = ttk.LabelFrame(parent, text="状态抵抗 [51]-[66] (32状态×1byte抵抗力; sub_42234C初始化为0)", padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        for c in range(8):
            lf.columnconfigure(c, weight=1, minsize=100)
        self._status_resist_widgets = []
        for i in range(32):
            r, c = divmod(i, 8)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            sname = STATUS_NAMES[i] if i < len(STATUS_NAMES) else f"状态{i+1}"
            field_idx = 51 + i // 2
            byte_pos = "高" if i % 2 else "低"
            inp = ttk.Frame(col); inp.pack(fill=tk.X)
            lbl = ttk.Label(inp, text=sname, font=FONT, width=6)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{field_idx}] {byte_pos}字节: {sname}抵抗力")
            ev = tk.StringVar(value="0")
            ttk.Entry(inp, textvariable=ev, width=5, font=FONT, justify='center').pack(side=tk.RIGHT, padx=(1, 0))
            self._status_resist_widgets.append((i, ev))

    def _build_skill_learn(self, parent):
        """技能学习状态 — 344技能×1byte, 存储在[88]-[259]的每个字节中"""
        lf = ttk.LabelFrame(parent, text="技能学习状态 [88]-[259] (344技能×1byte; 反编译验证: 不会/等待学(1~9进展累积)/可以学(≥10)/父技学会(20)/独立技学会(30))", padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        for c in range(4):
            lf.columnconfigure(c, weight=1, minsize=180)
        self._skill_learn_widgets = []; self._skill_learn_labels = []
        for i in range(SKILL_LEARN_COUNT):
            r, c = divmod(i, 4)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
            if i == 343: sname = "普通攻击"
            field_idx = 88 + i // 2; byte_pos = "高" if i % 2 else "低"
            inp = ttk.Frame(col); inp.pack(fill=tk.X)
            lbl = ttk.Label(inp, text=sname, font=FONT, width=10)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{field_idx}] {byte_pos}字节: {sname} 0不会 1~9进展 10可学 20父技 30独立技")
            cb = ttk.Combobox(inp, values=SKILL_LEARN_STATES, state='readonly',
                              width=10, font=FONT)
            cb.pack(side=tk.RIGHT, padx=(1, 0))
            self._skill_learn_widgets.append((i, cb))
            self._skill_learn_labels.append(lbl)

    def _build_warpc_core_tab(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="核心属性")

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll = ttk.Frame(canvas)
        scroll.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._build_section(scroll, "基本信息", WARPC_IDENTITY)
        self._build_section(scroll, "HP / MP", WARPC_HPMP)
        self._build_stat_row(scroll)
        self._build_section(scroll, "技能加成 [32]-[40] (sub_422BBC TKSkill效果; sub_42234C初始=0)", WARPC_SKILL_BONUS)
        self._build_section(scroll, "反应组 [41]-[42] (运行时字段; sub_422BBC type=2 写入, sub_42234C 初始化为0)", WARPC_REACTION_FIELDS)
        self._build_section(scroll, "攻击导致状态 (来源于装备; sub_42234C L94-95)", WARPC_CAUSE_MASK_FIELDS, ft='mask')
        self._build_status_slots(scroll)
        self._build_section(scroll, "角色五维 [27]-[31] (曹操验证: 智慧5 仁德-1 勇气10 医术0 技能点400)", WARPC_CHAR_ATTR)
        self._build_section(scroll, "使用/装备权限 [77]-[81] (sub_41928C 验证: 主角#0 [77]=? [78]=7 [79]=63 [80]=3 [81]=?)", WARPC_USE_RIGHT_FIELDS)
        self._build_section(scroll, "成长率 [264]-[266] (五爪金龍: 初期27 中期24 后期21)", WARPC_GROWTH)
        self._build_section(scroll, "战后奖励 [268]-[269] (Gold=基数×2; JP=直接值)", WARPC_BATTLE_REWARD)
        self._build_section(scroll, "可掉落物品 [270]-[272] (五爪金龍验证: 顛海神珠/金龍魂/虎項龍紋鎧)", WARPC_DROP, ft='item_pick')

    def _build_warpc_equip_tab(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="装备与技能")

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll = ttk.Frame(canvas)
        scroll.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._build_section(scroll, "装备索引 [69]-[72] (TKItem数组下标; 运行时缓存)", WARPC_EQUIP[:4], ft='item_pick')
        self._build_section(scroll, "装备物品 ID [73]-[76] (DAT原始; 查 TKItem.field[0])", WARPC_EQUIP[4:], ft='item_pick')
        self._build_section(scroll, "装备技能 [82]-[87] (6字段; sub_42234C/sub_422BBC; Maker验证: 周倉)", WARPC_EQUIP_SKILL_FIELDS, ft='skill_pick')
        self._build_status_resist(scroll)
        self._build_skill_learn(scroll)

    def _build_warpc_status_tab(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="状态与抵抗")

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll = ttk.Frame(canvas)
        scroll.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        lf = ttk.LabelFrame(scroll, text="状态槽", padding=4)
        lf.pack(fill=tk.X, padx=4, pady=2)
        for i in range(8):
            frm = ttk.Frame(lf)
            frm.pack(fill=tk.X, pady=1)
            ttk.Label(frm, text=f"槽{i}", font=FONT_S).pack(
                side=tk.LEFT, padx=3)
            ttk.Label(frm, text="状态ID", font=FONT_S).pack(
                side=tk.LEFT, padx=3)
            sv_id = tk.StringVar()
            self.warpc_widgets[('slot', i, 'id')] = sv_id
            ttk.Entry(frm, textvariable=sv_id, width=6,
                      font=FONT_M).pack(side=tk.LEFT, padx=3)
            ttk.Label(frm, text="持续", font=FONT_S).pack(
                side=tk.LEFT, padx=3)
            sv_dur = tk.StringVar()
            self.warpc_widgets[('slot', i, 'dur')] = sv_dur
            ttk.Entry(frm, textvariable=sv_dur, width=6,
                      font=FONT_M).pack(side=tk.LEFT, padx=3)

        lf2 = ttk.LabelFrame(scroll, text="攻击导致状态", padding=4)
        lf2.pack(fill=tk.X, padx=4, pady=2)
        grid = ttk.Frame(lf2)
        grid.pack(fill=tk.X)
        for fi, (fn, fo, fl) in enumerate(WARPC_CAUSE_MASK_FIELDS):
            r, c = divmod(fi, 2)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, sticky='w', padx=3, pady=1)
            lbl = ttk.Label(frm, text=fl, font=FONT_S)
            lbl.pack(anchor=tk.W)
            off_str = f"[{fo//2}] +{fo}"
            self._bind_tooltip(lbl, f"{fn} {off_str}")
            sv = self._get_warpc_var(fo)
            ttk.Entry(frm, textvariable=sv, width=10,
                      font=FONT_M).pack(fill=tk.X)

        lf3 = ttk.LabelFrame(scroll, text="状态抵抗", padding=4)
        lf3.pack(fill=tk.X, padx=4, pady=2)
        grid = ttk.Frame(lf3)
        grid.pack(fill=tk.X)
        names = STATUS_NAMES + ["未知"]
        for i, name in enumerate(names):
            r, c = divmod(i, 8)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, sticky='w', padx=2, pady=1)
            ttk.Label(frm, text=name, font=FONT_S).pack(anchor=tk.W)
            sv = tk.StringVar()
            self.warpc_widgets[('resist', i)] = sv
            ttk.Entry(frm, textvariable=sv, width=5,
                      font=FONT_M).pack(fill=tk.X)

    def _build_warpc_skill_tab(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="技能学习")

        ctrl = ttk.Frame(frame)
        ctrl.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(ctrl, text="全部设为可学",
                   command=self._set_all_skills_learnable).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="全部清除",
                   command=self._clear_all_skills).pack(
            side=tk.LEFT, padx=4)

        ttk.Label(ctrl, text="页码:", font=FONT_S).pack(
            side=tk.LEFT, padx=(20, 2))
        page_var = tk.StringVar(value="1")
        self.warpc_widgets['skill_page_var'] = page_var
        total_pages = (344 + 49) // 50
        page_combo = ttk.Combobox(ctrl, textvariable=page_var, width=5,
                                   state='readonly',
                                   values=[str(i+1) for i in range(total_pages)])
        page_combo.pack(side=tk.LEFT, padx=2)

        nav = ttk.Frame(frame)
        nav.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(nav, text="上一页",
                   command=lambda: self._change_skill_page(-1)).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(nav, text="下一页",
                   command=lambda: self._change_skill_page(1)).pack(
            side=tk.LEFT, padx=2)

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        display = ttk.Frame(canvas)
        display.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=display, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)
        self.warpc_widgets['skill_display'] = display

        for i in range(344):
            sv = tk.StringVar()
            self.warpc_widgets[('skill', i)] = sv

        def _show_skill_page(*args):
            disp = self.warpc_widgets['skill_display']
            for w in disp.winfo_children():
                w.destroy()
            try:
                page = int(page_var.get()) - 1
            except ValueError:
                page = 0
            start = page * 50
            end = min(start + 50, 344)
            for i in range(start, end):
                r, c = divmod(i - start, 2)
                frm = ttk.Frame(disp)
                frm.grid(row=r, column=c, sticky='w', padx=4, pady=1)
                ttk.Label(frm, text=f"技能{i}", font=FONT_S).pack(
                    side=tk.LEFT, padx=2)
                sv = self.warpc_widgets[('skill', i)]
                cb = ttk.Combobox(frm, textvariable=sv, width=12,
                                   font=FONT_M)
                cb['values'] = (
                    ['0-不会'] +
                    [f'{j}-学习中' for j in range(1, 10)] +
                    [f'{j}-可学' for j in range(10, 20)] +
                    ['20-父技学会', '30-独立技学会']
                )
                cb.pack(side=tk.LEFT, padx=2)

        page_var.trace_add('write', _show_skill_page)
        _show_skill_page()

    def _build_warpc_raw_tab(self, nb):
        frame = ttk.Frame(nb)
        nb.add(frame, text="全部字段")

        ctrl = ttk.Frame(frame)
        ctrl.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(ctrl, text="页码:", font=FONT_S).pack(
            side=tk.LEFT, padx=(20, 2))
        page_var = tk.StringVar(value="1")
        self.warpc_widgets['raw_page_var'] = page_var
        all_offsets = list(range(0, WARPC_REC, 2))
        total_pages = (len(all_offsets) + 99) // 100
        page_combo = ttk.Combobox(ctrl, textvariable=page_var, width=5,
                                   state='readonly',
                                   values=[str(i+1) for i in range(total_pages)])
        page_combo.pack(side=tk.LEFT, padx=2)

        nav = ttk.Frame(frame)
        nav.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(nav, text="上一页",
                   command=lambda: self._change_raw_page(-1)).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(nav, text="下一页",
                   command=lambda: self._change_raw_page(1)).pack(
            side=tk.LEFT, padx=2)

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        display = ttk.Frame(canvas)
        display.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=display, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)
        self.warpc_widgets['raw_display'] = display

        for off in all_offsets:
            self._get_warpc_var(off)

        def _show_raw_page(*args):
            disp = self.warpc_widgets['raw_display']
            for w in disp.winfo_children():
                w.destroy()
            try:
                page = int(page_var.get()) - 1
            except ValueError:
                page = 0
            start = page * 100
            end = min(start + 100, len(all_offsets))
            for i in range(start, end):
                off = all_offsets[i]
                r, c = divmod(i - start, 4)
                frm = ttk.Frame(disp)
                frm.grid(row=r, column=c, sticky='w', padx=3, pady=1)
                name = self._get_warpc_field_name(off)
                if name.startswith('['):
                    lbl_text = f"[{off//2}] 0x{off:03X}"
                else:
                    lbl_text = f"[{off//2}] 0x{off:03X} {name}"
                ttk.Label(frm, text=lbl_text, font=FONT_S).pack(
                    anchor=tk.W)
                sv = self.warpc_widgets[off]
                ttk.Entry(frm, textvariable=sv, width=10,
                          font=FONT_M).pack(fill=tk.X)

        page_var.trace_add('write', _show_raw_page)
        _show_raw_page()

    def _change_skill_page(self, delta):
        page_var = self.warpc_widgets.get('skill_page_var')
        if not page_var:
            return
        try:
            cur = int(page_var.get())
        except ValueError:
            cur = 1
        max_page = (344 + 49) // 50
        new_page = max(1, min(max_page, cur + delta))
        page_var.set(str(new_page))

    def _change_raw_page(self, delta):
        page_var = self.warpc_widgets.get('raw_page_var')
        if not page_var:
            return
        try:
            cur = int(page_var.get())
        except ValueError:
            cur = 1
        all_offsets = list(range(0, WARPC_REC, 2))
        max_page = (len(all_offsets) + 99) // 100
        new_page = max(1, min(max_page, cur + delta))
        page_var.set(str(new_page))

    def _set_all_skills_learnable(self):
        for i in range(344):
            sv = self.warpc_widgets.get(('skill', i))
            if sv:
                sv.set('10-可学')

    def _clear_all_skills(self):
        for i in range(344):
            sv = self.warpc_widgets.get(('skill', i))
            if sv:
                sv.set('0-不会')

    def _populate_warpc_fields(self):
        if self.seg3 is None or self._warpc_cur_idx < 0:
            return
        idx = self._warpc_cur_idx
        self._warpc_status.configure(
            text=f"编辑角色 {idx} (0x{idx*WARPC_REC:04X})")

        # Populate raw fields
        for off in range(0, WARPC_REC, 2):
            sv = self.warpc_widgets.get(off)
            if sv:
                val = get_warpc_field(self.seg3, idx, off)
                sv.set(str(val))

        # Populate all named fields
        all_named_fields = (WARPC_IDENTITY + WARPC_HPMP + WARPC_SKILL_BONUS +
                           WARPC_EQUIP + WARPC_EQUIP_SKILL_FIELDS +
                           WARPC_CAUSE_MASK_FIELDS + WARPC_CHAR_ATTR +
                           WARPC_USE_RIGHT_FIELDS + WARPC_REACTION_FIELDS +
                           WARPC_GROWTH + WARPC_BATTLE_REWARD + WARPC_DROP)
        for item in all_named_fields:
            fn, fo = item[0], item[1]
            val = get_warpc_field(self.seg3, idx, fo)
            if fn in self._edit_vars:
                self._edit_vars[fn].set(str(val))

        # Populate role combobox
        role_val = get_warpc_field(self.seg3, idx, 6)
        if 'role' in self._edit_extras:
            cb = self._edit_extras['role']
            for i, item in enumerate(cb['values']):
                if item.startswith(f'{role_val}-'):
                    cb.current(i); break

        # Populate reaction_group combobox
        rg_val = get_warpc_field(self.seg3, idx, 82)
        if 'reaction_group' in self._edit_extras:
            cb = self._edit_extras['reaction_group']
            for i, item in enumerate(cb['values']):
                if item.startswith(f'{rg_val}-'):
                    cb.current(i); break

        # Populate stat fields
        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_OFFSETS)):
            base_val = get_warpc_field(self.seg3, idx, bo)
            cur_val = get_warpc_field(self.seg3, idx, bo + 2)
            fn_base = f"{short}_base"
            fn_cur = f"{short}_cur"
            if fn_base in self._edit_vars:
                self._edit_vars[fn_base].set(str(base_val))
            if fn_cur in self._edit_vars:
                self._edit_vars[fn_cur].set(str(cur_val))

        # Populate status slot widgets
        if hasattr(self, '_status_widgets'):
            for fn, fo, cb, ev_dur in self._status_widgets:
                v = get_warpc_field(self.seg3, idx, fo)
                sid = v & 0xFF
                dur = (v >> 8) & 0xFF
                if sid == 0 or sid > len(STATUS_NAMES):
                    cb.current(0)
                else:
                    cb.current(sid)
                ev_dur.set(str(dur) if sid != 0 and dur != 0xFF else "0")

        # Populate status resist widgets
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                val = get_warpc_status_resist(self.seg3, idx, byte_idx)
                ev.set(str(val))

        # Populate skill learn widgets
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                val = get_warpc_skill_learn(self.seg3, idx, skill_idx)
                for vi, item in enumerate(cb['values']):
                    if item.startswith(f'{val}-'):
                        cb.current(vi); break

        # Resolve skill names for equip skill fields
        for item in WARPC_EQUIP_SKILL_FIELDS:
            fn, fo = item[0], item[1]
            sid = get_warpc_field(self.seg3, idx, fo)
            if fn in self._edit_extras:
                if sid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif self.skill_names and sid in self.skill_names:
                    self._edit_extras[fn].config(text=self.skill_names[sid])
                else:
                    self._edit_extras[fn].config(text=f'技能#{sid}')

        # Resolve item names for equip_idx fields
        for item in WARPC_EQUIP[:4]:
            fn, fo = item[0], item[1]
            idx_val = get_warpc_field(self.seg3, idx, fo)
            if fn in self._edit_extras:
                if idx_val == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif self.item_idx_names and idx_val in self.item_idx_names:
                    self._edit_extras[fn].config(text=self.item_idx_names[idx_val])
                else:
                    self._edit_extras[fn].config(text=f'物品#{idx_val}')

        # Resolve item names for equip_id fields
        for item in WARPC_EQUIP[4:]:
            fn, fo = item[0], item[1]
            iid = get_warpc_field(self.seg3, idx, fo)
            if fn in self._edit_extras:
                if iid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif self.item_names and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Resolve item names for drop item fields
        for item in WARPC_DROP:
            fn, fo = item[0], item[1]
            iid = get_warpc_field(self.seg3, idx, fo)
            if fn in self._edit_extras:
                if iid == 0:
                    self._edit_extras[fn].config(text='(无)')
                elif self.item_names and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Update flag labels
        for fn in FLAG_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].get())
                    self._update_flags_label(fn, val)
                except ValueError:
                    self._update_flags_label(fn, 0)

        # Update use_right labels
        for fn in USE_RIGHT_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].get())
                    self._update_use_right_label(fn, val)
                except ValueError:
                    self._update_use_right_label(fn, 0)

        # Update status mask labels
        for item in WARPC_CAUSE_MASK_FIELDS:
            fn, fo = item[0], item[1]
            if fn in self._edit_extras:
                val = get_warpc_field(self.seg3, idx, fo)
                self._update_status_label(fn, val)


    # ========== 鼠标滚轮绑定 ==========

    def _bind_mousewheel(self, canvas):
        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ========== 数据加载 ==========

    def _load_save_dir(self):
        d = filedialog.askdirectory(title="选择存档目录 (包含 sav.N 和 N.sav 文件)")
        if not d:
            return
        self.save_dir = d
        self.slot = 1
        self.slot_var.set("1")
        self._load_slot()

    def _load_slot(self):
        if not self.save_dir:
            return
        slot = self.slot

        sav_n = os.path.join(self.save_dir, f"sav.{slot}")
        sav_meta = os.path.join(self.save_dir, f"{slot}.sav")

        if not os.path.exists(sav_n):
            messagebox.showwarning("文件缺失", f"未找到 {sav_n}")
            return
        if not os.path.exists(sav_meta):
            messagebox.showwarning("文件缺失", f"未找到 {sav_meta}")
            return

        try:
            self.game_state, self.seg1, self.seg2, self.seg3 = load_save(sav_n)
            self.sav_meta = load_sav_meta(sav_meta)
        except Exception as e:
            messagebox.showerror("加载失败", f"解析存档失败:\n{e}")
            return

        # 尝试加载 TKT.dat
        parent_dir = os.path.dirname(self.save_dir.rstrip('/\\'))
        tkt_path = os.path.join(parent_dir, "TKT.dat")
        if os.path.exists(tkt_path):
            self.tkt_path = tkt_path
            self.tkt = self._load_tkt(tkt_path)

        self.skill_names, self._skill_types = self._load_skill_names()
        self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()
        self._fa_sprites = self._load_fa_sprites()
        self._fa_photos.clear()
        # 更新技能学习标签文本
        if hasattr(self, '_skill_learn_labels'):
            for i, lbl in enumerate(self._skill_learn_labels):
                sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
                if i == 343: sname = "普通攻击"
                lbl.config(text=sname)

        self._dirty = False
        self._set_ws('normal')
        self._populate_all()

        self.status_var.set(
            f"已加载: 槽位{slot} | "
            f"Block1={len(self.game_state)}B | "
            f"Seg1={len(self.seg1)}B Seg2={len(self.seg2)}B Seg3={len(self.seg3)}B | "
            f"TKT {len(self.tkt)} 物品 {len(self.item_names)} 技能 {len(self.skill_names)}")

    def _switch_slot(self):
        try:
            self.slot = int(self.slot_var.get())
        except ValueError:
            return
        if self._dirty:
            if not messagebox.askyesno("未保存", "当前槽位有未保存的修改, 是否继续切换?"):
                return
        self._load_slot()

    def _load_tkt(self, tkt_path):
        """加载 TKT.dat (XOR 0xFF 编码的 Big5 文本数据库)."""
        with open(tkt_path, 'rb') as f:
            raw = f.read()
        ts = struct.unpack_from('<I', raw, 0)[0]
        cnt = struct.unpack_from('<I', raw, 4)[0]
        enc = raw[8:8 + ts]
        dec = bytes([b ^ 0xFF for b in enc])
        idsz = cnt * 4
        ofsz = cnt * 4
        lookup = {}
        SKIP = set(range(0, 10))
        for i in range(cnt):
            eid = struct.unpack_from('<i', dec, i * 4)[0]
            if eid in SKIP:
                continue
            off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
            ao = idsz + ofsz + off
            if ao < len(dec):
                end = ao
                while end < len(dec) and dec[end] != 0:
                    end += 1
                txt = dec[ao:end].replace(b'\x1e', b'\n')
                try:
                    s = txt.decode('big5', errors='replace')
                except Exception:
                    s = txt.decode('gbk', errors='replace')
                if s and s != '0':
                    lookup[eid] = s
        return lookup

    def _load_item_names(self):
        """加载 TKItem.dat → {item_id: item_name} + {item_index: item_name}"""
        if not self.save_dir:
            return {}, {}, {}, {}
        parent_dir = os.path.dirname(self.save_dir.rstrip('/\\'))
        it_path = os.path.join(parent_dir, 'TKItem.dat')
        if not os.path.exists(it_path):
            return {}, {}, {}, {}
        try:
            with open(it_path, 'rb') as f:
                dec = save_lzss_decompress(f.read())
            id_lookup = {}; idx_lookup = {}; idx_to_id = {}; id_to_idx = {}
            for i in range(600):
                off = i * 64
                if off + 10 > len(dec): break
                item_id = struct.unpack_from('<h', dec, off)[0]
                name_id = struct.unpack_from('<h', dec, off + 4)[0]
                if name_id > 0 and name_id in self.tkt:
                    nm = self.tkt[name_id].split('\n')[0].strip()[:25]
                elif item_id > 0:
                    nm = f'物品#{item_id}'
                else:
                    continue
                if item_id > 0:
                    id_lookup[item_id] = nm
                    idx_to_id[i] = item_id
                    id_to_idx[item_id] = i
                idx_lookup[i] = nm
            return id_lookup, idx_lookup, idx_to_id, id_to_idx
        except Exception:
            return {}, {}, {}, {}

    def _load_skill_names(self):
        """加载 TKSkill.dat → {skill_index: name} + {skill_index: type}"""
        if not self.save_dir:
            return {}, {}
        parent_dir = os.path.dirname(self.save_dir.rstrip('/\\'))
        sk_path = os.path.join(parent_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path):
            return {}, {}
        try:
            with open(sk_path, 'rb') as f:
                dec = save_lzss_decompress(f.read())
            name_lookup = {}; type_lookup = {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec): break
                name_id = struct.unpack_from('<h', dec, off)[0]
                stype = struct.unpack_from('<h', dec, off + 4)[0]
                type_lookup[i] = stype
                if name_id > 0 and name_id in self.tkt:
                    name_lookup[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
                elif name_id:
                    name_lookup[i] = f'#{name_id}'
            return name_lookup, type_lookup
        except Exception:
            return {}, {}

    def _load_fa_sprites(self):
        """加载 Fa.JVG → PIL Image 列表"""
        try:
            from PIL import Image
        except ImportError:
            return []
        if not self.save_dir:
            return []
        parent_dir = os.path.dirname(self.save_dir.rstrip('/\\'))
        fa_path = os.path.join(parent_dir, 'Fa.JVG')
        if not os.path.exists(fa_path):
            return []
        with open(fa_path, 'rb') as f:
            data = f.read()
        if len(data) < 32 or data[:4] != b'@JVG':
            return []
        bc = struct.unpack_from('<I', data, 8)[0]
        off = 32; sprites = []
        for bi in range(bc):
            if off + 32 > len(data) or data[off:off+4] != b'@JVM': break
            sc = struct.unpack_from('<I', data, off+4)[0]
            ds = struct.unpack_from('<I', data, off+12)[0]
            s1 = off + 32
            co = [struct.unpack_from('<I', data, s1+j*4)[0] for j in range(sc+1)]
            po = s1 + (sc+1)*4
            pal_entries = []
            for j in range(256):
                e = struct.unpack_from('<H', data, po+j*2)[0]
                r = ((e>>11)&0x1F)<<3; g = ((e>>5)&0x3F)<<2; b = (e&0x1F)<<3
                pal_entries.extend([r,g,b])
            pal_bytes = bytes(pal_entries)
            dr = po + 512
            for si in range(sc):
                mo = dr + co[si]
                ws = struct.unpack_from('<8H', data, mo)
                w, h = ws[2], ws[3]
                if w <= 0 or h <= 0:
                    sprites.append(None)
                    continue
                eo = mo + 16
                ed = data[eo:eo+co[si+1]-co[si]-16]
                total = w*h; px = bytearray(total); alpha = bytearray(total)
                recs = []; rp = 0
                while rp + 4 <= len(ed):
                    sk = struct.unpack_from('<H', ed, rp)[0]
                    rw = struct.unpack_from('<H', ed, rp+2)[0]
                    rp += 4
                    rw = min(rw, len(ed)-rp)
                    rd = ed[rp:rp+rw] if rw>0 else b''
                    rp += rw
                    recs.append((sk, rw, rd))
                if not recs: continue
                simple = (recs[0][0]==0 and recs[0][1]==w and all(r[1]==w for r in recs))
                if simple:
                    for ri, (_, rw, rpix) in enumerate(recs):
                        if ri >= h: break
                        tr = h-1-ri
                        for c in range(min(rw, len(rpix))):
                            px[tr*w+c] = rpix[rw-1-c]
                            alpha[tr*w+c] = 255
                else:
                    scr_w = 640; gap = max(scr_w-w, 0); bp = total-1; pg = 0
                    for sa, rw, rpix in recs:
                        rem = sa-pg; pg = 0
                        if rem < 0: rem = 0
                        while rem > 0 and bp >= 0:
                            col = (total-1-bp)%w; tb = w-col
                            if rem <= tb: bp -= rem; rem = 0
                            else: bp -= tb; rem -= tb+gap; rem = max(rem, 0)
                        cb = (total-1-bp)%w if bp >= 0 else 0
                        al = min(rw, len(rpix))
                        for k in range(al):
                            if 0 <= bp < total:
                                px[bp] = rpix[k]
                                alpha[bp] = 255
                            bp -= 1
                        pg = gap if al > 0 and cb+al >= w else 0
                if w > 0 and h > 0:
                    img = Image.frombytes('P', (w, h), bytes(px))
                    img.putpalette(pal_bytes)
                    rgba = img.convert('RGBA')
                    a_img = Image.frombytes('L', (w, h), bytes(alpha))
                    rgba.putalpha(a_img)
                    sprites.append(rgba)
            off += 32 + (sc+1)*4 + 512 + ds
        return sprites

    def _get_fa_photo(self, sprite_idx, size=(24,24)):
        """从 Fa.JVG 精灵集中获取 PhotoImage (缓存)"""
        if not self._fa_sprites:
            return None
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites):
            return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None:
            return None
        cache_key = (sprite_idx, size)
        if cache_key in self._fa_photos:
            return self._fa_photos[cache_key]
        try:
            from PIL import ImageTk
            img = sprite.resize(size, ImageTk.Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self._fa_photos[cache_key] = photo
            return photo
        except Exception:
            return None

    # ========== 填充所有 Tab ==========

    def _populate_all(self):
        self._populate_save_info()
        self._populate_team()
        self._populate_global()
        self._populate_warpc_list()

    # --- 存档信息 ---

    def _populate_save_info(self):
        if self.sav_meta is None:
            return
        for key, (sv, off, fmt) in self._meta_vars.items():
            size = struct.calcsize(fmt)
            if off + size > len(self.sav_meta):
                continue
            val = struct.unpack_from(fmt, self.sav_meta, off)[0]
            sv.set(str(val))
        self._meta_hex_var.set(self.sav_meta.hex(' '))

        # 摘要
        s = []
        s.append(f"槽位: {self.slot}")
        s.append(f"存档文件: sav.{self.slot} ({os.path.getsize(os.path.join(self.save_dir, f'sav.{self.slot}')):,} bytes)")
        s.append(f"元数据文件: {self.slot}.sav (28 bytes)")
        s.append(f"Block1 游戏状态: {len(self.game_state):,} bytes (解压后)")
        s.append(f"Block2 TKMat: S1={SEG1_SIZE}B S2={SEG2_SIZE}B S3={SEG3_SIZE}B (解压后)")
        # 队伍概况
        team = []
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
            if tid >= 0:
                name = self._get_char_name(tid)
                team.append(f"[{i+1}]={tid}({name})")
            else:
                team.append(f"[{i+1}]=空")
        s.append(f"队伍: {', '.join(team)}")
        gold = struct.unpack_from('<H', self.seg2, 0x02)[0]
        s.append(f"金钱: {gold}")
        map_id = struct.unpack_from('<I', self.seg1, 0x40)[0]
        s.append(f"地图ID: {map_id} ({'无' if map_id == 0xFFFFFFFF else map_id})")

        self._summary_text.configure(state='normal')
        self._summary_text.delete('1.0', tk.END)
        self._summary_text.insert('1.0', '\n'.join(s))
        self._summary_text.configure(state='disabled')

    def _get_char_name(self, char_idx):
        """通过 WarPC name_id 从 TKT 获取角色名称."""
        if self.seg3 is None:
            return f"#{char_idx}"
        name_id = get_warpc_field(self.seg3, char_idx, 0)
        if name_id and name_id in self.tkt:
            return self.tkt[name_id]
        return f"#{char_idx}(ID={name_id})"

    # --- 队伍数据 ---

    def _populate_team(self):
        if self.seg2 is None:
            return
        # 队伍成员
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i * 2)[0]
            self._team_member_vars[i].set(str(tid))
            if tid == 0:
                self._team_member_name_labels[i].config(text="主角")
            elif tid > 0:
                self._team_member_name_labels[i].config(text=self._get_char_name(tid))
            else:
                self._team_member_name_labels[i].config(text="(空)")
        # 核心字段
        for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
            val = struct.unpack_from('<' + fmt.lower(), self.seg2, off)[0]
            self._team_vars[key].set(str(val))
        # 战斗统计
        for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
            val = struct.unpack_from('<' + fmt.lower(), self.seg2, off)[0]
            self._team_vars[key].set(str(val))
        # 库存计数
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        val = struct.unpack_from('<' + fmt.lower(), self.seg2, off)[0]
        self._team_inv_count_var.set(str(val))

    # --- 全局状态 ---

    def _populate_global(self):
        if self.seg1 is None:
            return
        # 单值字段
        for key, (sv, off, size, fmt) in self._global_vars.items():
            if off + size > len(self.seg1):
                continue
            if fmt == '5s':
                val = self.seg1[off:off+5].hex()
            elif fmt == '3s':
                val = self.seg1[off:off+3].hex()
            else:
                val = struct.unpack_from(fmt, self.seg1, off)[0]
            sv.set(str(val))
        # SEG2 间隙字段
        if self.seg2 is not None:
            for key, (sv, off, size, fmt) in self._seg2_gap_vars.items():
                if off + size > len(self.seg2):
                    continue
                val = struct.unpack_from('<' + fmt.lower(), self.seg2, off)[0]
                sv.set(str(val))
        # 数组字段
        for arr_key, arr_off, arr_cnt, arr_esz, arr_label, arr_cmt in SEG1_ARRAYS:
            arr_data = self._global_array_vars.get(arr_key)
            if arr_data is None:
                continue
            fmt_char = 'B' if arr_esz == 1 else 'H'
            if arr_cnt <= 256:
                for i in range(arr_cnt):
                    off = arr_off + i * arr_esz
                    val = struct.unpack_from('<' + fmt_char, self.seg1, off)[0]
                    arr_data[i].set(str(val))
            else:
                for pg, page_vars in list(arr_data.items()):
                    for i, sv in page_vars:
                        off = arr_off + i * arr_esz
                        val = struct.unpack_from('<' + fmt_char, self.seg1, off)[0]
                        sv.set(str(val))

    # --- WarPC 列表 ---

    def _populate_warpc_list(self):
        tree = self.warpc_tree
        # Preserve current selection
        prev_sel = None
        sel = tree.selection()
        if sel:
            prev_sel = int(tree.item(sel[0], 'values')[0])

        tree.delete(*tree.get_children())
        if self.seg3 is None:
            return

        search_text = self._warpc_search_var.get().strip().lower()
        if search_text == "搜索角色...":
            search_text = ""
        filter_val = self._warpc_filter_var.get()

        for i in range(WARPC_CNT):
            name_id = get_warpc_field(self.seg3, i, 0)
            level = get_warpc_field(self.seg3, i, 4)
            role = get_warpc_field(self.seg3, i, 6)
            hp = get_warpc_field(self.seg3, i, 10)
            mp = get_warpc_field(self.seg3, i, 12)
            name = self.tkt.get(name_id, f"ID:{name_id}") if name_id else ""

            # Filter by role
            if filter_val == "我方" and role != -1:
                continue
            if filter_val == "敌方" and role != 0:
                continue

            # Search by name or index
            if search_text:
                idx_str = str(i)
                name_lower = name.lower()
                if search_text not in idx_str and search_text not in name_lower:
                    continue

            role_str = "我方" if role == -1 else ("敌方" if role == 0 else str(role))
            tag = 'ally' if role == -1 else 'enemy'
            item_id = tree.insert('', tk.END, values=(i, name, level, role_str, hp, mp),
                        tags=(tag,))
            if prev_sel is not None and i == prev_sel:
                tree.selection_set(item_id)
                tree.see(item_id)

        tree.tag_configure('ally', foreground='#2266CC')
        tree.tag_configure('enemy', foreground='#CC3333')

    def _on_warpc_search_changed(self, *args):
        self._populate_warpc_list()

    def _on_warpc_filter_changed(self, *args):
        self._populate_warpc_list()

    def _on_warpc_select(self):
        sel = self.warpc_tree.selection()
        if not sel:
            return
        vals = self.warpc_tree.item(sel[0], 'values')
        idx = int(vals[0])
        self._warpc_cur_idx = idx
        self._build_warpc_editor()
        self._populate_warpc_fields()

    def _apply_warpc_edit(self):
        if self.seg3 is None or self._warpc_cur_idx < 0:
            return
        idx = self._warpc_cur_idx

        # Apply role combobox
        if 'role' in self._edit_extras:
            sv = self._edit_extras['role'].get().strip()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                role_val = int(sv[:sep]) if sep >= 0 else int(sv)
                set_warpc_field(self.seg3, idx, 6, role_val)
                self._edit_vars['role'].set(str(role_val))

        # Apply reaction_group combobox
        if 'reaction_group' in self._edit_extras:
            sv = self._edit_extras['reaction_group'].get().strip()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                rg_val = int(sv[:sep]) if sep >= 0 else int(sv)
                set_warpc_field(self.seg3, idx, 82, rg_val)
                self._edit_vars['reaction_group'].set(str(rg_val))

        # Sync status slot UI widgets → seg3
        if hasattr(self, '_status_widgets'):
            for fn, fo, cb, ev_dur in self._status_widgets:
                sid = cb.current()
                if sid == 0:
                    v = -256
                else:
                    try:
                        dur = int(ev_dur.get())
                        if dur < 0: dur = 1
                        if dur > 255: dur = 255
                    except ValueError:
                        dur = 1
                    v = (sid & 0xFF) | ((dur & 0xFF) << 8)
                    if v >= 0x8000: v -= 0x10000
                set_warpc_field(self.seg3, idx, fo, v)

        # Apply status resist widgets
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                try:
                    byte_val = int(ev.get())
                    if byte_val < 0: byte_val = 0
                    if byte_val > 255: byte_val = 255
                except ValueError:
                    continue
                set_warpc_status_resist(self.seg3, idx, byte_idx, byte_val)

        # Apply skill learn widgets
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                sv = cb.get()
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                byte_val = int(sv[:sep]) if sep >= 0 else 0
                set_warpc_skill_learn(self.seg3, idx, skill_idx, byte_val)

        # Apply named fields
        all_named_fields = (WARPC_IDENTITY + WARPC_HPMP + WARPC_SKILL_BONUS +
                           WARPC_EQUIP + WARPC_EQUIP_SKILL_FIELDS +
                           WARPC_CAUSE_MASK_FIELDS + WARPC_CHAR_ATTR +
                           WARPC_USE_RIGHT_FIELDS + WARPC_REACTION_FIELDS +
                           WARPC_GROWTH + WARPC_BATTLE_REWARD + WARPC_DROP)
        for item in all_named_fields:
            fn, fo = item[0], item[1]
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    set_warpc_field(self.seg3, idx, fo, v)
                except ValueError:
                    pass

        # Apply stat fields
        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_OFFSETS)):
            fn_base = f"{short}_base"
            fn_cur = f"{short}_cur"
            if fn_base in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn_base].get())
                    set_warpc_field(self.seg3, idx, bo, v)
                except ValueError:
                    pass
            if fn_cur in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn_cur].get())
                    set_warpc_field(self.seg3, idx, bo + 2, v)
                except ValueError:
                    pass

        # Collect named indices to skip in raw loop
        named_indices = set()
        for item in all_named_fields:
            named_indices.add(item[1] // 2)
        # Status resist
        for j in range(51, 67):
            named_indices.add(j)
        # Skill learn
        for j in range(88, 260):
            named_indices.add(j)

        # Apply raw fields (skip named)
        for off in range(0, WARPC_REC, 2):
            j = off // 2
            if j in named_indices:
                continue
            sv = self.warpc_widgets.get(off)
            if sv:
                try:
                    val = int(sv.get())
                    if val < -32768 or val > 32767:
                        raise ValueError(f"值 {val} 超出 int16 范围")
                    set_warpc_field(self.seg3, idx, off, val)
                except ValueError:
                    pass

        self._dirty = True
        self._populate_warpc_list()
        self.status_var.set(f"角色 {idx} 已修改 (未保存)")

    # ========== 保存 ==========

    def _save(self):
        if self.game_state is None:
            messagebox.showwarning("无数据", "请先加载存档目录")
            return

        if not messagebox.askyesno("确认保存",
            f"将覆盖保存到 sav.{self.slot} 和 {self.slot}.sav, 是否继续?"):
            return

        try:
            # 收集段2修改 (队伍+资源)
            self._collect_team_changes()
            # 收集段1修改 (全局变量)
            self._collect_global_changes()
            # 收集 .sav 元数据修改
            self._collect_meta_changes()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return

        sav_n = os.path.join(self.save_dir, f"sav.{self.slot}")
        sav_meta = os.path.join(self.save_dir, f"{self.slot}.sav")

        try:
            save_save(sav_n, self.game_state, self.seg1, self.seg2, self.seg3)
            save_sav_meta(sav_meta, self.sav_meta)
            self._dirty = False
            self.status_var.set(f"已保存: 槽位{self.slot}")
            messagebox.showinfo("保存成功", f"存档已保存到 sav.{self.slot}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _collect_team_changes(self):
        """从 UI 收集队伍数据修改."""
        # 队伍成员
        for i in range(6):
            try:
                val = int(self._team_member_vars[i].get())
                if val < -1 or val >= WARPC_CNT:
                    raise ValueError(f"队伍成员{i+1} 值 {val} 超出范围")
                struct.pack_into('<h', self.seg2, 0x0C + i * 2, val)
            except ValueError as e:
                raise ValueError(f"队伍成员{i+1}: {e}")
        # 核心字段 + 战斗统计 (都在 _team_vars 中)
        for field_list in (SEG2_CORE_FIELDS, SEG2_BATTLE_FIELDS):
            for key, off, size, label, fmt, cmt in field_list:
                sv = self._team_vars.get(key)
                if sv is None:
                    continue
                try:
                    val = int(sv.get())
                    struct.pack_into('<' + fmt.lower(), self.seg2, off, val)
                except ValueError as e:
                    raise ValueError(f"{label}: {e}")
        # 库存计数
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        try:
            val = int(self._team_inv_count_var.get())
            struct.pack_into('<' + fmt.lower(), self.seg2, off, val)
        except ValueError as e:
            raise ValueError(f"{label}: {e}")
        self._dirty = True

    def _collect_global_changes(self):
        """从 UI 收集全局变量修改."""
        # 单值字段
        for key, (sv, off, size, fmt) in self._global_vars.items():
            try:
                txt = sv.get()
                if fmt in ('5s', '3s'):
                    data = bytes.fromhex(txt)
                    self.seg1[off:off+size] = data.ljust(size, b'\x00')
                else:
                    val = int(txt)
                    struct.pack_into(fmt, self.seg1, off, val)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"全局字段 {key}: {e}")
        # SEG2 间隙字段
        if self.seg2 is not None:
            for key, (sv, off, size, fmt) in self._seg2_gap_vars.items():
                try:
                    val = int(sv.get())
                    struct.pack_into('<' + fmt.lower(), self.seg2, off, val)
                except (ValueError, AttributeError) as e:
                    raise ValueError(f"SEG2间隙字段 {key}: {e}")
        # 数组字段
        for arr_key, arr_off, arr_cnt, arr_esz, arr_label, arr_cmt in SEG1_ARRAYS:
            arr_data = self._global_array_vars.get(arr_key)
            if arr_data is None:
                continue
            fmt_char = 'B' if arr_esz == 1 else 'H'
            if arr_cnt <= 256:
                for i in range(arr_cnt):
                    try:
                        val = int(arr_data[i].get())
                        struct.pack_into('<' + fmt_char, self.seg1, arr_off + i * arr_esz, val)
                    except ValueError as e:
                        raise ValueError(f"{arr_label}[{i}]: {e}")
            else:
                for pg, page_vars in list(arr_data.items()):
                    for i, sv in page_vars:
                        try:
                            val = int(sv.get())
                            struct.pack_into('<' + fmt_char, self.seg1, arr_off + i * arr_esz, val)
                        except ValueError as e:
                            raise ValueError(f"{arr_label}[{i}]: {e}")
        self._dirty = True

    def _collect_meta_changes(self):
        """从 UI 收集 .sav 元数据修改."""
        for key, (sv, off, fmt) in self._meta_vars.items():
            try:
                val = int(sv.get())
                size = struct.calcsize(fmt)
                struct.pack_into(fmt, self.sav_meta, off, val)
            except ValueError:
                pass  # 跳过无法解析的字段

    # ========== 辅助 ==========

    def _format_hex(self, data, base_addr):
        """格式化十六进制 dump."""
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            addr = base_addr + i
            hex_str = ' '.join(f'{b:02X}' for b in chunk)
            ascii_str = ''.join(
                chr(b) if 32 <= b < 127 else '.' for b in chunk)
            lines.append(f'{addr:08X}  {hex_str:<48s}  {ascii_str}')
        return '\n'.join(lines)

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 是否退出?"):
                return
        self.root.destroy()


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    app = SaveEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
