#!/usr/bin/env python3
"""
WarPC.dat 字段 Schema (唯一字段定义源)
===========================================================
由 warpc_editor.py 抽取的字段元数据统一定义:
  - 记录布局常量 (WARPC_REC / WARPC_FIELD_COUNT / ...)
  - 各分区字段元组列表 (IDENTITY_FIELDS / HPMP_FIELDS / ... 保持原格式,
    供表单模式既有代码零改动使用)
  - FieldDef / FIELD_SCHEMA / SCHEMA_GROUPS: 带类型语义的统一字段描述,
    供表格编辑模式使用
  - 打包字节编解码 (技能学习 [88]-[259] / 状态抵抗 [51]-[66] 等
    "2字节装1对byte" 的高低字节读写)

本模块无 Qt 依赖, 可被 CLI 工具安全导入。
字段布局逆向依据见 warpc_editor.py 模块头注释。
"""

from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════
# 常量 (100% 原始定义)
# ═══════════════════════════════════════════════════════════════

WARPC_REC = 1054
WARPC_FIELD_COUNT = 527
WARPC_ORIG_COUNT = 143
WARPC_ORIG_SIZE = 150722

COMBAT_FLAG_BITS = [
    (0, "JP×2~3", "战后技能点数×2~3"), (1, "战后全恢复+异常全解", "HP/MP全恢复+清除异常"),
    (2, "经验×2~3平分队友", "经验×2~3并平分队友"), (3, "经验独得", "经验归一人独享"),
]
MOVE_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻"), (1, "飙行", "移动范围扩大"),
    (2, "搜宝", "获得额外宝物"), (3, "解陷", "自动解除陷阱"),
]
FLAG_DEFS = {'special_flag': ("特殊能力标志", COMBAT_FLAG_BITS), 'move_flags': ("移动特殊标志", MOVE_FLAG_BITS)}

USE_RIGHT_DEFS = {
    'use_right_medicine': ("药品使用权限", [(1,"战斗"),(2,"非战斗")]),
    'use_right_item': ("道具使用权限", [(1,"战斗"),(2,"非战斗"),(4,"主角限定")]),
    'use_right_weapon': ("武器装备权限", [(1,"刀"),(2,"剑"),(4,"枪"),(8,"矛"),(16,"弓"),(32,"大刀"),(64,"戟"),(128,"锤")]),
    'use_right_armor': ("防具装备权限", [(1,"衣袍"),(2,"铠甲")]),
    'use_right_accessory': ("饰品使用权限", [(0,"通用")]),
}
# 页面号 → 权限字段名 (与 item_editor standard_config.json 的页面号语义一致)
# 页面 0=药品 1=道具 2=武器 3=防具 4=饰品 5=特殊; 5=特殊在 WarPC 中无对应字段，故不映射
USE_RIGHT_PAGE_TO_FIELD = {
    0: 'use_right_medicine', 1: 'use_right_item', 2: 'use_right_weapon',
    3: 'use_right_armor', 4: 'use_right_accessory',
}

SKILL_LEARN_COUNT = 344   # 原版学习区条数 (0..343); 扩展技能 350+ 见 editor_utils.skill_table
SKILL_LEARN_STATES = ["0-不会","1-等待学","10-可以学","20-组技能学会","30-子技能学会"]

# 技能学习/状态抵抗 打包字节区起始 int16 字段索引
SKILL_LEARN_BASE = 88     # [88]-[259] 344技能×1byte
STATUS_RESIST_BASE = 51   # [51]-[66]  32状态×1byte
STATUS_RESIST_COUNT = 32
STATUS_SLOT_BASE = 43     # [43]-[50]  8槽×(低字节=状态ID, 高字节=持续回合)
STATUS_SLOT_COUNT = 8

ROLE_VALUES = ["-1-未激活", "0-已激活"]

# 核心字段 — 已验证 (格式: key, offset, label, comment)
IDENTITY_FIELDS = [
    ("name_id",    0,  "名称TKT ID",  "角色名称 → TKT.dat"),  # sub_4067E8
    ("portrait",   2,  "头像索引",    "头像索引 ×2 = Fa.JVG 大幅图, ×2+1 = 缩略图"),
    ("level",      4,  "等级",        "角色等级 (数值显示)"),
    ("role",       6,  "身份",        "-1=未激活 0=已激活(入队时置0)"),  # sub_410674 L40
    ("exp_to_next", 8,  "升级所需经验","升至下一级所需经验; 绝大多数角色=100, BOSS版较高(呂布5092 張角7292)"),
]
# 补丁专用字段 [260]-[263] — 配合运行时补丁使用; 0=使用原硬编码公式
# 注: entity_link 是 field[263](字节偏移526), 勿与 field[526](字节偏移1052, 战斗精灵索引) 混淆
PATCH_FIELDS = [
    ("awk_sprite_id", 520, "战场图集索引（补丁专用）", "战斗中Awk.JVG/Awt.JVG块号; 0=使用原硬编码公式(PATH1:WarPC索引+6, PATH2:WarPC记录号+12); 非0=补丁直接使用此值"),
    ("portrait_menu_id", 522, "队伍头像ID（补丁专用）", "队伍菜单Mu.JVG精灵块号; 0=使用原公式(portrait+211); 非0=直接使用此值"),
    ("history_text_id", 524, "历史文本ID（补丁专用）", "角色界面「历史」标签页TKT文本ID; 0=使用原公式(9050+角色序号)"),  # sub_41A080:104
    ("entity_link", 526, "地图实体ID（补丁专用）", "离队后在地图上显示的NPC实体ID → TKMat.dat (field[263], 非field[526])"),  # sub_41EEC0 → sub_40C648
]
HPMP_FIELDS = [
    ("cur_hp",    10,  "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",    12,  "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base",   14,  "HP基础",      "HP基础值"),
    ("hp_max",    16,  "HP上限",      "HP上限 (基础+装备)"),  # sub_42234C
    ("mp_base",   18,  "MP基础",      "MP基础值"),
    ("mp_max",    20,  "MP上限",      "MP上限 (基础+装备)"),  # sub_42234C
]

STAT_NAMES_CN = ["攻击","防御","命中","闪避","速度","幸运","移动","悟性"]
STAT_SHORTS = ["atk","def","hit","eva","spd","luk","mov","wis"]
STAT_BASE_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]
# 8 属性对 (基础/当前) — sub_42234C L24-31/63-70 验证
STAT_FIELDS = []
for i, (n, s, bo) in enumerate(zip(STAT_NAMES_CN, STAT_SHORTS, STAT_BASE_OFFSETS)):
    STAT_FIELDS.append((f"{s}_base", bo, f"{n}(基础)",
                        f"{n}基础值"))  # sub_42234C: a2[{11+i*2}]
    STAT_FIELDS.append((f"{s}_cur", bo+2, f"{n}(当前)",
                        f"{n}当前值 (基础+装备)"))  # sub_42234C L63-70 a2[{12+i*2}]+=v9[{11+i}]

# 技能加成区 [32]-[40] — sub_422BBC 应用 TKSkill 效果, sub_42234C 初始化
SKILL_BONUS_FIELDS = [
    ("atk_count",   64,  "攻击次数",       "攻击次数 (含TKSkill增加的攻击次数)"),  # sub_42234C=1; sub_422BBC L29: a2[32]+=v6[31]
    ("special_flag",66,  "特殊能力标志",   "来自装备 TKItem[20]"),  # sub_42234C L73: a2[33]|=v9[20]
    ("mp_reduce",   68,  "内力消耗减少%",  "内息百分比 来自主动技能 TKSkill[33]"),  # sub_422BBC L29: a2[34]+=v6[33]
    ("magic_def",   70,  "所受法伤减少%",  "抗魔百分比 来自主动技能 TKSkill[38]"),  # sub_422BBC L45: a2[35]+=v6[38]
    ("exp_bonus",   72,  "战斗经验增加%",  "鬼才百分比 来自主动技能 TKSkill[36]"),  # sub_422BBC L43: a2[36]+=v6[36]
    ("jp_bonus",    74,  "战斗技能点增加%","天才百分比 来自主动技能 TKSkill[37]"),  # sub_422BBC L44: a2[37]+=v6[37]
    ("move_flags",  76,  "移动特殊标志",   "来自移动技能 TKSkill[32]"),  # sub_422BBC L124: a2[38]|=v6[32]
    ("heal_move",   78,  "移动恢复生命%",  "自愈百分比 来自移动技能 TKSkill[22]"),  # sub_422BBC L125: a2[39]+=v6[22]
    ("mp_move",     80,  "移动恢复内力%",  "回气百分比 来自移动技能 TKSkill[24]"),  # sub_422BBC L126: a2[40]+=v6[24]
]
# 角色五维 [27]-[31] — 曹操验证: 智慧5 仁德-1 勇气10 医术0 技能点数400
CHAR_ATTR_FIELDS = [
    ("wisdom",      54,  "智慧",        "智慧值 (曹操=5 司马懿=20)"),
    ("benevolence", 56,  "仁德",        "仁德值 (曹操=-1 司马懿=-5)"),
    ("courage",     58,  "勇气",        "勇气值 (曹操=10 司马懿=0)"),
    ("medicine",    60,  "医术",        "医术值 (曹操=0 司马懿=10; 上限100)"),  # sub_40E11C case4→word_75688A
    ("jp_total",    62,  "技能点数",    "累计技能点数 (曹操=400 司马懿=300; 与等级相关)"),  # sub_422A5C 入队累加
]
# 反应组 [41]-[42] — 运行时字段, sub_422BBC type=2 写入, sub_42234C 初始化为0
REACTION_FIELDS = [
    ("reaction_group",  82,  "反应组",   "被动技能反应组编号 1-10 (初始化=0)"),  # sub_422BBC type=2
    ("reaction_trigger",84,  "触发概率", "被动技能触发概率 %%, 来自 TKSkill[44]"),  # sub_422BBC: a2[42]=v6[44]
]
REACTION_GROUP_VALUES = ["0-无","1-近戰反擊","2-遠程反擊","3-法術反彈","4-先發制人","5-時序回饋","6-損傷賠償","7-環境探索","8-國色天香","9-有福同享","10-國士無雙"]

# 身上状态槽 [43]-[50] — sub_41E40C 验证: 8个状态效果槽, 每槽(status_id:byte, duration:byte)
STATUS_SLOT_FIELDS = [
    (f"status_slot{i}", 86+i*2, f"状态槽{i}",
     f"身上状态效果槽{i}; 低字节=状态ID(1-32) 高字节=持续回合")  # sub_41E40C: v8+{i*2}
    for i in range(8)
]

EQUIP_FIELDS = [
    ("equip_idx0", 138, "装备索引0",   "运行时装备索引缓存"),  # sub_4173F8
    ("equip_idx1", 140, "装备索引1",   "运行时装备索引缓存"),
    ("equip_idx2", 142, "装备索引2",   "运行时装备索引缓存"),
    ("equip_idx3", 144, "装备索引3",   "运行时装备索引缓存"),
    ("equip_id0",  146, "装备物品ID0", "装备物品 ID (DAT原始; 查 TKItem.field[0])"),
    ("equip_id1",  148, "装备物品ID1", "装备物品 ID"),
    ("equip_id2",  150, "装备物品ID2", "装备物品 ID"),
    ("equip_id3",  152, "装备物品ID3", "装备物品 ID"),
]
# 装备技能 [82]-[87] — Maker Frm_WarPC 暴露, sub_42234C/sub_422BBC 应用
# 周倉 验证: [82]=43武術 [83]=83輔助 [84]=273二連擊 [85]=279無隙1 [86]=303近戰反擊1 [87]=334飄浮
EQUIP_SKILL_FIELDS = [
    ("equip_skill0", 164, "装备技能0", "装备技能槽0 → TKSkill"),  # sub_42234C v4 loop
    ("equip_skill1", 166, "装备技能1", "装备技能槽1 → TKSkill"),
    ("equip_skill2", 168, "装备技能2", "装备技能槽2 → TKSkill"),  # sub_42234C: a2[84]
    ("equip_skill3", 170, "装备技能3", "装备技能槽3 → TKSkill"),  # sub_42234C: a2[85]
    ("passive1",     172, "被动技能1", "被动技能1 → TKSkill"),  # sub_422BBC
    ("passive2",     174, "被动技能2", "被动技能2 → TKSkill"),  # sub_422BBC
]
# 角色使用/装备权限 [77]-[81] — sub_41928C: 按位与校验
CHAR_USE_RIGHT_FIELDS = [
    ("use_right_medicine",  154, "药品权限",   "药品使用权限位掩码 (待验证); 全143条原始值=0"),
    ("use_right_item",      156, "道具权限",   "道具使用权限位掩码 (1=战斗 2=非战斗 4=主角限定); 主角#0=7"),
    ("use_right_weapon",    158, "武器权限",   "武器装备权限位掩码 (1=刀 2=剑 4=枪 8=矛 16=弓 32=大刀 64=戟 128=锤); 主角#0=63"),
    ("use_right_armor",     160, "防具权限",   "防具装备权限位掩码 (1=衣袍 2=铠甲); 主角#0=3"),
    ("use_right_accessory", 162, "饰品权限",   "饰品装备权限位掩码 (待验证); 全143条原始值=0"),
]
STATUS_FIELDS_CAUSE = [
    ("cause_mask1", 134, "攻击导致状态 1-16",  "攻击/命中时让目标进入的状态位掩码 (bit0-15; 来自装备 v9[26])"),
    ("cause_mask2", 136, "攻击导致状态 17-32", "攻击/命中时让目标进入的状态位掩码 (bit16-31; 来自装备 v9[27])"),
]
# 战后奖励 — 实测验证: 盜賊嘍嘍 field[268]=2→JP=2, field[269]=20→Lv3 Gold=40
BATTLE_REWARD_FIELDS = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点数 (直接值, 无等级缩放); 盜賊嘍嘍=2 西羌王=100"),
    ("gold_reward", 538, "战后金钱基数","击败后获得金钱基数; 实际获得=基数×2; 盜賊嘍嘍=20→40 小混混=25→50"),
]
# 成长率 [264]-[266] — 五爪金龍验证: 初期27 中期24 后期21; 等级>=21中期, >=41后期
# 物理抵抗 [267] — 独立显示字段
GROWTH_FIELDS = [
    ("growth_early", 528, "成长率初期", "成长率初期; 五爪金龍=27 西羌王=27 呂布=20"),
    ("growth_mid",   530, "成长率中期", "成长率中期; 五爪金龍=24 西羌王=24 呂布=25"),
    ("growth_late",  532, "成长率后期", "成长率后期; 五爪金龍=21 西羌王=21 呂布=25"),
    ("physical_resist", 534, "物理抵抗", "物理抵抗参数; 字段[267]"),
]
# 可掉落物品 [270]-[272] — 双路径机制，详见 掉落物品概率分析.md
# 路径A（死亡掉落, sub_4400DC）: 独立 100/20/5; 路径B（探寶技能, action 239）: 级联 80/15/5
DROP_ITEM_FIELDS = [
    ("drop_item0", 540, "必掉落物品", "死亡掉落(路径A)中100%掉落; 探寶技能(路径B)中80%掉落; 仅此槽有物品时必掉"),
    ("drop_item1", 542, "高概率掉落", "死亡掉落(路径A)中20%掉落; 探寶技能(路径B)中15%掉落; 优先填第2槽"),
    ("drop_item2", 544, "低概率掉落", "死亡掉落(路径A)中5%掉落; 探寶技能(路径B)中5%掉落; 判定优先级最高"),
]

ALL_NAMED_FIELDS = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS + CHAR_ATTR_FIELDS +
    SKILL_BONUS_FIELDS + REACTION_FIELDS + STATUS_SLOT_FIELDS +
    STATUS_FIELDS_CAUSE + EQUIP_FIELDS + CHAR_USE_RIGHT_FIELDS +
    EQUIP_SKILL_FIELDS + PATCH_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)

# 装备与技能标签页字段 (Tab2) — 供跨角色复制/粘贴使用 (顺序与 _build_tab2 一致)
EQUIP_PANEL_FIELDS = (EQUIP_FIELDS + CHAR_USE_RIGHT_FIELDS + EQUIP_SKILL_FIELDS +
    PATCH_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)

# 尾部未分析区域
TAIL_START = 260  # int16 offset (技能学习状态结束于 [259])
TAIL_END = 527

# ═══════════════════════════════════════════════════════════════
# FieldDef / FIELD_SCHEMA — 带类型语义的统一字段描述
# ═══════════════════════════════════════════════════════════════

INT16_MIN, INT16_MAX = -32768, 32767


@dataclass
class FieldDef:
    """单个命名字段的完整元数据 (表格编辑模式的列定义来源)"""
    key: str
    offset: int            # 字节偏移
    label: str
    ftype: str = 'int'     # int/enum/flags/use_right/skill_ref/item_idx_ref/item_id_ref/status_mask
    group: str = ''
    tab: int = 0           # 表单模式所在 Tab 索引 (0=核心属性 1=装备与技能)
    vrange: tuple = (INT16_MIN, INT16_MAX)
    comment: str = ''
    enum_items: list = field(default=None)  # enum 类型的 "值-标签" 列表

    @property
    def index(self):
        """int16 字段索引"""
        return self.offset // 2


# (元组列表, group, tab, {key: ftype 覆盖}, 默认 ftype)
_SCHEMA_SOURCES = [
    (IDENTITY_FIELDS,       "基本信息",     0, {'role': 'enum'}, 'int'),
    (HPMP_FIELDS,           "HP/MP",        0, {}, 'int'),
    (STAT_FIELDS,           "八属性",       0, {}, 'int'),
    (CHAR_ATTR_FIELDS,      "角色五维",     0, {}, 'int'),
    (SKILL_BONUS_FIELDS,    "技能加成",     0, {'special_flag': 'flags', 'move_flags': 'flags'}, 'int'),
    (REACTION_FIELDS,       "反应组",       0, {'reaction_group': 'enum'}, 'int'),
    (STATUS_SLOT_FIELDS,    "身上状态",     0, {}, 'int'),
    (STATUS_FIELDS_CAUSE,   "攻击导致状态", 0, {}, 'status_mask'),
    (EQUIP_FIELDS[:4],      "装备索引",     1, {}, 'item_idx_ref'),
    (EQUIP_FIELDS[4:],      "装备物品ID",   1, {}, 'item_id_ref'),
    (CHAR_USE_RIGHT_FIELDS, "使用装备权限", 1, {}, 'use_right'),
    (EQUIP_SKILL_FIELDS,    "装备技能",     1, {}, 'skill_ref'),
    (PATCH_FIELDS,          "补丁字段",     1, {}, 'int'),
    (GROWTH_FIELDS,         "成长率",       1, {}, 'int'),
    (BATTLE_REWARD_FIELDS,  "战后奖励",     1, {}, 'int'),
    (DROP_ITEM_FIELDS,      "掉落物品",     1, {}, 'item_id_ref'),
]

_ENUM_ITEMS = {'role': ROLE_VALUES, 'reaction_group': REACTION_GROUP_VALUES}


def _build_schema():
    schema = {}
    groups = []
    for fields, group, tab, overrides, default_ft in _SCHEMA_SOURCES:
        keys = []
        for tup in fields:
            key, off, label = tup[0], tup[1], tup[2]
            cmt = tup[3] if len(tup) > 3 else ''
            ft = overrides.get(key, default_ft)
            schema[key] = FieldDef(
                key=key, offset=off, label=label, ftype=ft, group=group,
                tab=tab, comment=cmt, enum_items=_ENUM_ITEMS.get(key))
            keys.append(key)
        groups.append((group, keys))
    return schema, groups


FIELD_SCHEMA, SCHEMA_GROUPS = _build_schema()


def parse_enum_value(text):
    """从 '值-标签' 格式解析整数值 (兼容负数前缀, 如 '-1-未激活')"""
    sep = text.find('-', 1) if text.startswith('-') else text.find('-')
    return int(text[:sep]) if sep >= 0 else int(text)


# ═══════════════════════════════════════════════════════════════
# int16 / 打包字节 编解码
# ═══════════════════════════════════════════════════════════════

def clamp_int16(v):
    return max(INT16_MIN, min(INT16_MAX, int(v)))


def get_packed_byte(fields, base_idx, byte_idx):
    """读取以 base_idx 为起点的打包字节区中第 byte_idx 个 byte (0-255)"""
    fi = base_idx + byte_idx // 2
    return ((fields[fi] & 0xFFFF) >> (8 * (byte_idx % 2))) & 0xFF


def set_packed_byte(fields, base_idx, byte_idx, byte_val):
    """写入打包字节区中第 byte_idx 个 byte, 保持另一半字节不变"""
    byte_val = max(0, min(255, int(byte_val)))
    fi = base_idx + byte_idx // 2
    unsigned = fields[fi] & 0xFFFF
    if byte_idx % 2:
        new_val = (unsigned & 0x00FF) | (byte_val << 8)
    else:
        new_val = (unsigned & 0xFF00) | byte_val
    fields[fi] = new_val - 0x10000 if new_val >= 0x8000 else new_val


__all__ = [
    'WARPC_REC', 'WARPC_FIELD_COUNT', 'WARPC_ORIG_COUNT', 'WARPC_ORIG_SIZE',
    'COMBAT_FLAG_BITS', 'MOVE_FLAG_BITS', 'FLAG_DEFS',
    'USE_RIGHT_DEFS', 'USE_RIGHT_PAGE_TO_FIELD',
    'SKILL_LEARN_COUNT', 'SKILL_LEARN_STATES',
    'SKILL_LEARN_BASE', 'STATUS_RESIST_BASE', 'STATUS_RESIST_COUNT',
    'STATUS_SLOT_BASE', 'STATUS_SLOT_COUNT',
    'ROLE_VALUES',
    'IDENTITY_FIELDS', 'PATCH_FIELDS', 'HPMP_FIELDS',
    'STAT_NAMES_CN', 'STAT_SHORTS', 'STAT_BASE_OFFSETS', 'STAT_FIELDS',
    'SKILL_BONUS_FIELDS', 'CHAR_ATTR_FIELDS',
    'REACTION_FIELDS', 'REACTION_GROUP_VALUES', 'STATUS_SLOT_FIELDS',
    'EQUIP_FIELDS', 'EQUIP_SKILL_FIELDS', 'CHAR_USE_RIGHT_FIELDS',
    'STATUS_FIELDS_CAUSE', 'BATTLE_REWARD_FIELDS', 'GROWTH_FIELDS',
    'DROP_ITEM_FIELDS', 'ALL_NAMED_FIELDS', 'EQUIP_PANEL_FIELDS',
    'TAIL_START', 'TAIL_END',
    'INT16_MIN', 'INT16_MAX',
    'FieldDef', 'FIELD_SCHEMA', 'SCHEMA_GROUPS', 'parse_enum_value',
    'clamp_int16', 'get_packed_byte', 'set_packed_byte',
]
