#!/usr/bin/env python3
r"""
TKS Save Editor v2.0
加载/编辑/保存 游戏存档数据 (save\sav.N + N.sav), 支持全部9个存档槽位。

逆向来源: TKS.exe sub_410ED4 (SaveTKMat), sub_41103C (LoadTKMat)
索引文件: sub_41CE10 (SaveIndexWrite), sub_41B1A8 (SaveSlotDisplay)
兼容性:   支持 TKSLauncher 扩展后的 WarPC 缓冲区 (动态大小检测)

存档数据文件格式 (sav.N):
  Frame 1: [4B compressed_size][LZSS(2304000B TKMat实体表)]
  Frame 2: [4B compressed_size][LZSS(BlockA 3432B + BlockB 5768B + BlockC WarPC)]
  WarPC 原始大小 = 143*1054 = 150722B, 启动器扩展后可能更大

索引文件格式 (N.sav, 28字节):
  [6×1B team_ids][2B gold][4B unix_timestamp][6×2B team_levels][4B scene_id]
"""

import datetime
import os
import struct
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.lzss import (lzss_decompress_dat as _lzss_decompress_dat,
                                lzss_compress_dat as _lzss_compress_dat,
                                lzss_decompress_save, lzss_compress_save)
from editor_utils.tkt_loader import load_tkt_simple

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress_dat(data):
    return _lzss_decompress_dat(data)


def lzss_decompress(data):
    return lzss_decompress_save(data)


def lzss_compress(data):
    return lzss_compress_save(data)


def load_tkt(tkt_path):
    return load_tkt_simple(tkt_path, skip_range=None)

# ============================================================
# 常量 (来自逆向工程 — 每个值附带反编译代码证据)
# ============================================================

# Frame 1: TKMat 游戏实体表 (dword_51AF40)
# 证据: 410ED4.c:21 "v6 = 2304000", 412688.c:21 "sub_452544(aTkmatDat_0, dword_51AF40, 2304000)"
GAMESTATE_SIZE = 2304000  # 6000 entities × 384 bytes

# Frame 2 三段布局 (来源: 410ED4.c:25-28, 41103C.c:28,34-36)
SEG1_SIZE = 3432   # Block A: 脚本全局变量 (unk_755B18)
SEG2_SIZE = 5768   # Block B: 背包/队伍/金币 (unk_756880)
WARPC_OFFSET = 9200  # = SEG1_SIZE + SEG2_SIZE, WarPC在Frame2中的偏移
WARPC_REC = 1054   # 每条WarPC记录字节数 (527 WORD = 1054 bytes, 4173F8.c:48 v4+=527)
WARPC_ORIG_CNT = 143  # 原始角色数量
WARPC_ORIG_SIZE = 150722  # = 143 × 1054, 原始WarPC大小

# .sav 索引文件 (28字节, 来源: 41CE10.c:103-124, 41B1A8.c:53-120)
SAV_META_SIZE = 28

# ============================================================
# 段1 (0x755B18, 3432B) 已知字段 (相对段1起始偏移)
# ============================================================

SEG1_BASIC_FIELDS = [
    # (key, offset, size, label, struct_fmt, 逆向证据)
    ("map_id",       0x40, 4, "当前地图ID",     "I",  "dword_755B58, sub_40C044地图切换"),
    ("current_char", 0x44, 4, "当前角色ID",     "I",  "dword_755B5C, sub_40C7CC SetPlayer事件"),
    ("game_active",  0x48, 4, "游戏激活标志",    "I",  "dword_755B60, sub_41103C读档后置1"),
    ("given_name",   0x4C, 5, "名",             "big5", "byte_755B64, sub_40D2D0 strcpy→名 上限2Big5字"),
    ("surname",      0x54, 5, "姓",             "big5", "byte_755B6C, sub_40D2D0 strcpy→姓 上限2Big5字"),
]

SEG1_SLOT_FIELDS = [
    ("slot1_active", 0x15C, 2, "编成槽1激活",    "H",  "word_755C74, sub_41FAAC编成UI"),
    ("slot1_idx",    0x15E, 2, "编成槽1角色索引", "H",  "word_755C76, sub_41FAAC"),
    ("slot2_active", 0x160, 2, "编成槽2激活",    "H",  "word_755C78, sub_41FAAC"),
    ("slot2_idx",    0x162, 2, "编成槽2角色索引", "H",  "word_755C7A, sub_41FAAC"),
]

SEG1_MAP_FIELDS = [
    ("battle_flags", 0x168, 4, "遭遇战旗标",     "I",  "dword_755C80, sub_4084E0 bit0减半/bit1禁止/bit2强制/bit3反击"),
    ("map_timer",    0x82C, 2, "地图计时器",     "H",  "word_756344, sub_43CA64"),
    ("door_unlock",  0x82E, 2, "开门标志",       "H",  "word_756346, sub_4307CC"),
]

SEG1_EVENT_FIELDS = [
    ("comp_flag",    0x336, 2, "同伴管理标志",    "H",  "word_755E4E, sub_420844"),
    ("minigame_rst", 0x366, 2, "小游戏结果",     "H",  "word_755E7E, sub_40E97C"),
    ("last_acq",     0x566, 2, "最后获得量",     "H",  "word_75607E, sub_40CE30"),
]

# 数组字段
SEG1_ARRAYS = [
    # (key, offset, count, elem_size, label, 证据)
    ("bgm_flags",    0x05C, 250, 1, "角色BGM标志",   "byte_755B74[250], sub_40C044"),
    ("switches",     0x2F8, 32,  2, "事件开关",      "word_755E10[32], sub_40EBD4 case49"),
    ("results",      0x338, 24,  2, "事件结果",      "word_755E50[24], sub_40EBD4 case60"),
    ("variables",    0x368, 256, 2, "事件变量",      "word_755E80[256], sub_40EBD4 case36-39"),
    ("flags",        0x568, 1024,2, "事件标志",      "word_756080[1024], sub_40CB08/sub_40CB4C"),
]

# ============================================================
# 段2 (0x756880, 5768B) 已知字段 (相对段2起始偏移)
# ============================================================

SEG2_CORE_FIELDS = [
    ("gold",         0x02, 2, "金钱",          "H",  "word_756882, sub_40CE30 上限30000"),
    ("wisdom",       0x04, 2, "智慧",         "H",  "word_756884, WarPC[27]团队汇总 (EXE确认WORD)"),
    ("benevolence",  0x06, 2, "仁德",         "H",  "word_756886, WarPC[28]团队汇总 (EXE确认WORD)"),
    ("courage",      0x08, 2, "勇气",         "H",  "word_756888, WarPC[29]汇总"),
    ("medicine",     0x0A, 2, "医术",         "H",  "word_75688A, WarPC[30]汇总 上限100"),
]

SEG2_TEAM_FIELDS = [
    ("team0", 0x0C, 2, "队伍成员1", "h", "word_75688C[0], -1=空"),
    ("team1", 0x0E, 2, "队伍成员2", "h", "word_75688C[1]"),
    ("team2", 0x10, 2, "队伍成员3", "h", "word_75688C[2]"),
    ("team3", 0x12, 2, "队伍成员4", "h", "word_75688C[3]"),
    ("team4", 0x14, 2, "队伍成员5", "h", "word_75688C[4]"),
    ("team5", 0x16, 2, "队伍成员6", "h", "word_75688C[5]"),
]

SEG2_BATTLE_FIELDS = [
    # 来源: sub_41A080 (状态画面渲染) L61-67, 按显示顺序排列
    ("wins",         0x163A, 2, "胜场数",       "H",  "word_757EBA, sub_41A080 L61 勝場數"),
    ("losses",       0x163C, 2, "败场数",       "H",  "word_757EBC, sub_41A080 L62 敗場數"),
    ("kills",        0x163E, 2, "杀敌数",       "H",  "word_757EBE, sub_41A080 L63 殺敵數"),
    ("quest_pct",    0x167E, 2, "完成任务%",    "H",  "word_757EFE, sub_41A080 L64 完成任務% / sub_40E11C case10"),
    ("special_pct",  0x1680, 2, "特殊物品%",    "H",  "word_757F00, sub_41A080 L65 特殊物品% / sub_40E11C case11"),
    ("souls",        0x1684, 2, "收纳灵魂",      "H",  "word_757F04, sub_41A080 L66 收納靈魂"),
    ("beasts",       0x1686, 2, "收纳兽元",      "H",  "word_757F06, sub_41A080 L67 收納獸元"),
]

SEG2_INV_COUNT = ("inv_count", 0x828, 2, "物品种类数", "H", "word_7570A8, sub_40CD90")

SEG2_INVENTORY = [
    ("inv_items", 0x82A, 600, "物品ID",      "word_7570AA[600]"),
    ("inv_types", 0xCDA, 600, "物品类型索引", "word_75755A[600]"),
    ("inv_qtys",  0x118A,600, "物品堆叠数量", "word_757A0A[600]"),
]

# ============================================================
# WarPC 字段定义 (来自 warpc_editor 和逆向分析)
# ============================================================

WARPC_IDENTITY = [
    ("name_id",       0,   "名称TKT ID",   "角色名称 → TKT.dat"),
    ("portrait",      2,   "头像索引",     "Fa.JVG大幅图=×2, 缩略=×2+1"),
    ("level",         4,   "等级",         "角色等级"),
    ("role",          6,   "身份",         "-1=未激活 0=已激活(sub_410674 L40入队时置0)"),
    ("exp_to_next",   8,   "升级所需经验", "绝大多数=100"),
    ("awk_sprite_id", 520, "战场图集索引", "WarPC[260], Awk.JVG块号"),
    ("portrait_menu", 522, "队伍头像ID",   "WarPC[261], Mu.JVG块号"),
    ("entity_link",   526, "地图实体ID",   "离队后NPC实体 → TKMat"),
]

WARPC_HPMP = [
    ("cur_hp",  10, "当前HP", "当前生命值"),
    ("cur_mp",  12, "当前MP", "当前内力值"),
    ("hp_base", 14, "HP基础", "HP基础值"),
    ("hp_max",  16, "HP上限", "HP上限(基础+装备)"),
    ("mp_base", 18, "MP基础", "MP基础值"),
    ("mp_max",  20, "MP上限", "MP上限(基础+装备)"),
]

STAT_NAMES = ["攻击", "防御", "命中", "闪避", "速度", "幸运", "移动", "悟性"]
STAT_SHORTS = ["atk", "def", "hit", "eva", "spd", "luk", "mov", "wis"]
STAT_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]  # 基础值偏移, +2为当前值

WARPC_CHAR_ATTR = [
    ("char_wisdom",      54, "智慧", "曹操=5 司马懿=20"),
    ("char_benevolence", 56, "仁德", "曹操=-1 司马懿=-5"),
    ("char_courage",     58, "勇气", "曹操=10 司马懿=0"),
    ("char_medicine",    60, "医术", "曹操=0 司马懿=10, 上限100"),
    ("jp_total",         62, "技能点数", "累计技能点数 曹操=400"),
]

WARPC_SKILL_BONUS = [
    ("atk_count",   64,  "攻击次数",     "sub_42234C初始=1"),
    ("special_flag",66,  "特殊能力标志", "TKItem[20]位掩码"),
    ("mp_reduce",   68,  "内力消耗减少%","TKSkill[33]内息"),
    ("magic_def",   70,  "法伤减少%",    "TKSkill[38]抗魔"),
    ("exp_bonus",   72,  "经验增加%",    "TKSkill[36]鬼才"),
    ("jp_bonus",    74,  "技能点增加%",  "TKSkill[37]天才"),
    ("move_flags",  76,  "移动特殊标志", "bit0飘浮 bit1飙行 bit2搜宝 bit3解陷"),
    ("heal_move",   78,  "移动恢复HP%",  "TKSkill[22]自愈"),
    ("mp_move",     80,  "移动恢复MP%",  "TKSkill[24]回气"),
]

WARPC_REACTION_FIELDS = [
    ("reaction_group",  82, "反应组", "被动技能反应组 1-10"),
    ("reaction_trigger",84, "触发概率", "TKSkill[44] %%"),
]

WARPC_EQUIP = [
    ("equip_idx0", 138, "装备索引0", "TKItem数组下标缓存"),
    ("equip_idx1", 140, "装备索引1", ""),
    ("equip_idx2", 142, "装备索引2", ""),
    ("equip_idx3", 144, "装备索引3", ""),
    ("equip_id0",  146, "装备物品ID0","DAT原始ID"),
    ("equip_id1",  148, "装备物品ID1",""),
    ("equip_id2",  150, "装备物品ID2",""),
    ("equip_id3",  152, "装备物品ID3",""),
]

WARPC_EQUIP_SKILL_FIELDS = [
    ("equip_skill0", 164, "装备技能0", "sub_42234C"),
    ("equip_skill1", 166, "装备技能1", ""),
    ("equip_skill2", 168, "装备技能2", ""),
    ("equip_skill3", 170, "装备技能3", ""),
    ("passive1",     172, "被动技能1", "sub_422BBC"),
    ("passive2",     174, "被动技能2", ""),
]

WARPC_USE_RIGHT_FIELDS = [
    ("use_right_medicine",  154, "药品权限",   ""),
    ("use_right_item",      156, "道具权限",   "1=战斗 2=非战斗 4=主角限定"),
    ("use_right_weapon",    158, "武器权限",   "1=刀 2=剑 4=枪 8=矛 16=弓 32=大刀 64=戟 128=锤"),
    ("use_right_armor",     160, "防具权限",   "1=衣袍 2=铠甲"),
    ("use_right_accessory", 162, "饰品权限",   ""),
]

WARPC_GROWTH = [
    ("growth_early", 528, "成长率初期", "五爪金龍=27"),
    ("growth_mid",   530, "成长率中期", "五爪金龍=24"),
    ("growth_late",  532, "成长率后期", "五爪金龍=21"),
]

WARPC_BATTLE_REWARD = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点"),
    ("gold_reward", 538, "战后金钱基数","实际=基数×2"),
]

WARPC_DROP = [
    ("drop_item0", 540, "必掉落物品",  "可掉落物品0 ID"),
    ("drop_item1", 542, "高概率掉落",  "可掉落物品1 ID"),
    ("drop_item2", 544, "低概率掉落",  "可掉落物品2 ID"),
]

WARPC_CAUSE_MASK_FIELDS = [
    ("cause_mask1", 134, "攻击导致状态 1-16",  "装备v9[26]位掩码"),
    ("cause_mask2", 136, "攻击导致状态 17-32", "装备v9[27]位掩码"),
]

STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

SKILL_LEARN_COUNT = 344

# ============================================================
# 文件加载/保存 (兼容TKSLauncher扩展后的WarPC)
# ============================================================

def load_save_data(path):
    """加载 sav.N 数据文件.
    返回 (game_state, seg1, seg2, seg3).
    seg3 大小可能不是标准150722 (若由扩展启动器保存)."""
    with open(path, 'rb') as f:
        raw = f.read()
    offset = 0

    # Frame 1: TKMat 实体表 (2304000B)
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame1 大小")
    comp1 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4
    if offset + comp1 > len(raw):
        raise ValueError(f"Frame1 数据不完整 (需要 {comp1} 字节)")
    game_state = lzss_decompress(raw[offset:offset + comp1])
    offset += comp1
    if len(game_state) != GAMESTATE_SIZE:
        raise ValueError(f"Frame1 解压大小异常: {len(game_state)} (期望 {GAMESTATE_SIZE})")

    # Frame 2: 全局状态 (BlockA + BlockB + BlockC)
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame2 大小")
    comp2 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4
    if offset + comp2 > len(raw):
        raise ValueError(f"Frame2 数据不完整 (需要 {comp2} 字节)")
    frame2 = lzss_decompress(raw[offset:offset + comp2])

    # 动态解析 Frame2: 前3432=SEG1, 中5768=SEG2, 剩余=SEG3(WarPC)
    if len(frame2) < WARPC_OFFSET:
        raise ValueError(f"Frame2 解压大小不足: {len(frame2)} < {WARPC_OFFSET}")
    seg1 = bytearray(frame2[:SEG1_SIZE])
    seg2 = bytearray(frame2[SEG1_SIZE:WARPC_OFFSET])
    seg3 = bytearray(frame2[WARPC_OFFSET:])

    return bytearray(game_state), seg1, seg2, seg3


def save_save_data(path, game_state, seg1, seg2, seg3):
    """保存 sav.N 数据文件. 自动备份原文件."""
    # 组装 Frame2
    frame2 = bytes(seg1) + bytes(seg2) + bytes(seg3)

    # 压缩
    inner1 = lzss_compress(bytes(game_state))
    inner2 = lzss_compress(frame2)

    # 备份
    if os.path.exists(path):
        bak = path + '.bak'
        try:
            with open(path, 'rb') as s:
                with open(bak, 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass

    # 写入
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
    """加载 N.sav 索引文件 (28字节).
    返回解析后的字典, 或 None (文件不存在/损坏)."""
    if not os.path.exists(path):
        return None
    data = bytearray(open(path, 'rb').read())
    if len(data) < SAV_META_SIZE:
        return None
    # 解析 (来源: 41CE10.c:103-124)
    team_ids = [data[i] if data[i] != 0xFF else -1 for i in range(6)]
    gold = struct.unpack_from('<H', data, 6)[0]
    timestamp = struct.unpack_from('<I', data, 8)[0]
    team_levels = [struct.unpack_from('<H', data, 12 + i*2)[0] for i in range(6)]
    scene_id = struct.unpack_from('<i', data, 24)[0]
    return {
        'raw': data,
        'team_ids': team_ids,
        'gold': gold,
        'timestamp': timestamp,
        'team_levels': team_levels,
        'scene_id': scene_id,
    }


def save_index_file(path, meta_dict):
    """保存 N.sav 索引文件."""
    data = bytearray(SAV_META_SIZE)
    for i, tid in enumerate(meta_dict['team_ids'][:6]):
        data[i] = tid & 0xFF if tid >= 0 else 0xFF
    struct.pack_into('<H', data, 6, meta_dict['gold'] & 0xFFFF)
    struct.pack_into('<I', data, 8, meta_dict['timestamp'] & 0xFFFFFFFF)
    for i, lv in enumerate(meta_dict['team_levels'][:6]):
        struct.pack_into('<H', data, 12 + i*2, lv & 0xFFFF)
    struct.pack_into('<i', data, 24, meta_dict['scene_id'])

    # 备份
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
# WarPC 辅助函数
# ============================================================

def warpc_get(seg3, char_idx, byte_offset):
    """读取 WarPC int16 字段."""
    off = char_idx * WARPC_REC + byte_offset
    if off + 2 > len(seg3):
        return 0
    return struct.unpack_from('<h', seg3, off)[0]


def warpc_set(seg3, char_idx, byte_offset, value):
    """写入 WarPC int16 字段."""
    off = char_idx * WARPC_REC + byte_offset
    if off + 2 > len(seg3):
        return
    v = max(-32768, min(32767, value))
    struct.pack_into('<h', seg3, off, v)


def warpc_get_byte(seg3, char_idx, byte_offset):
    """读取 WarPC 单字节."""
    off = char_idx * WARPC_REC + byte_offset
    if off >= len(seg3):
        return 0
    return seg3[off]


def warpc_set_byte(seg3, char_idx, byte_offset, value):
    """写入 WarPC 单字节."""
    off = char_idx * WARPC_REC + byte_offset
    if off >= len(seg3):
        return
    seg3[off] = value & 0xFF


# ============================================================
# Mu.JVG 图标加载 (精简版, 仅取精灵列表)
# ============================================================
def _load_mu_sprites(mu_path):
    """加载 Mu.JVG — 严格对照 item_editor/load_mu_sprites"""
    try:
        from PIL import Image
    except ImportError:
        return []
    if not mu_path or not os.path.exists(mu_path): return []
    with open(mu_path, 'rb') as f: data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG': return []
    bc = struct.unpack_from('<I', data, 8)[0]; off = 32; sprites = []
    for _ in range(bc):
        if off + 32 > len(data) or data[off:off+4] != b'@JVM': break
        sc = struct.unpack_from('<I', data, off+4)[0]; ds = struct.unpack_from('<I', data, off+12)[0]
        s1 = off + 32; co = [struct.unpack_from('<I', data, s1+j*4)[0] for j in range(sc+1)]
        po = s1 + (sc+1)*4
        pal_entries = []
        for j in range(256):
            e = struct.unpack_from('<H', data, po+j*2)[0]
            r = ((e>>11)&0x1F)<<3; g = ((e>>5)&0x3F)<<2; b = (e&0x1F)<<3
            pal_entries.extend([r,g,b])
        pal_bytes = bytes(pal_entries)
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]; ws = struct.unpack_from('<8H', data, mo)
            w, h = ws[2], ws[3]
            if w <= 0 or h <= 0: sprites.append(None); continue
            eo = mo + 16; ed = data[eo:eo+co[si+1]-co[si]-16]
            total = w*h; px = bytearray(total); alpha = bytearray(total)
            recs = []; rp = 0
            while rp + 4 <= len(ed):
                sk = struct.unpack_from('<H', ed, rp)[0]; rw = struct.unpack_from('<H', ed, rp+2)[0]; rp += 4
                rw = min(rw, len(ed)-rp); rd = ed[rp:rp+rw] if rw>0 else b''; rp += rw
                recs.append((sk, rw, rd))
            if not recs: continue
            simple = (recs[0][0]==0 and recs[0][1]==w and all(r[1]==w for r in recs))
            if simple:
                for ri, (_, rw, rpix) in enumerate(recs):
                    if ri >= h: break
                    tr = h-1-ri
                    for c in range(min(rw, len(rpix))): px[tr*w+c] = rpix[rw-1-c]; alpha[tr*w+c] = 255
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
                        if 0 <= bp < total: px[bp] = rpix[k]; alpha[bp] = 255
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

def _get_icon_photo(sprites, icon_val, size=(20,20), cache=None):
    """获取图标 PhotoImage (缓存)"""
    if not sprites: return None
    idx = icon_val + 130
    if idx < 0 or idx >= len(sprites) or sprites[idx] is None: return None
    if cache is None: cache = {}
    ck = (idx, size)
    if ck in cache: return cache[ck]
    try:
        from PIL import Image, ImageTk
        img = sprites[idx].resize(size, Image.NEAREST)
        photo = ImageTk.PhotoImage(img)
        cache[ck] = photo
        return photo
    except Exception:
        return None

PAGE_NAMES = {0:"药品", 1:"道具", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}

# ============================================================
# GUI - 主窗口
# ============================================================

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_M = ('Consolas', 9)
FONT_TITLE = ('Microsoft YaHei UI', 11, 'bold')


class SaveEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKS 存档编辑器 v2.0")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1360x820")
        self.root.minsize(1100, 700)

        # --- 数据状态 ---
        self.save_dir = None
        self.slot = 1
        self.game_state = None
        self.seg1 = None
        self.seg2 = None
        self.seg3 = None
        self.index_meta = None  # 解析后的索引字典
        self._dirty = False
        self.warpc_count = WARPC_ORIG_CNT

        # --- 外部资源 ---
        self.tkt = {}
        self.skill_names = {}
        self.item_names = {}
        self.item_idx_names = {}

        # --- 构建 UI ---
        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 1360, 820
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- 菜单栏 ---
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="打开存档目录…", command=self._cmd_open, accelerator="Ctrl+O")
        fm.add_command(label="保存当前槽位", command=self._cmd_save, accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_close)
        mb.add_cascade(label="文件", menu=fm)

        tm = tk.Menu(mb, tearoff=0)
        tm.add_command(label="刷新数据显示", command=self._refresh_all)
        mb.add_cascade(label="工具", menu=tm)

        self.root.bind('<Control-o>', lambda e: self._cmd_open())
        self.root.bind('<Control-s>', lambda e: self._cmd_save())

        # --- 顶部工具栏 ---
        toolbar = ttk.Frame(self.root, padding=(8, 4))
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="打开目录", command=self._cmd_open).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="保存", command=self._cmd_save).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="存档槽位:", font=FONT).pack(side=tk.LEFT, padx=(0, 4))

        # 9个槽位按钮
        self._slot_btns = []
        self._slot_frame = ttk.Frame(toolbar)
        self._slot_frame.pack(side=tk.LEFT)
        for i in range(1, 10):
            btn = ttk.Button(self._slot_frame, text=str(i), width=3,
                             command=lambda s=i: self._switch_slot(s))
            btn.pack(side=tk.LEFT, padx=1)
            self._slot_btns.append(btn)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        self._status_var = tk.StringVar(value="请点击「打开目录」加载存档")
        ttk.Label(toolbar, textvariable=self._status_var, font=FONT_S,
                  foreground='#666').pack(side=tk.RIGHT, padx=4)

        # --- 主 Notebook ---
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._build_overview_tab()
        self._build_team_tab()
        self._build_inventory_tab()
        self._build_global_tab()
        self._build_warpc_tab()

        # 底部状态栏 — 参照 item_editor "当前加载"
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._lbl_save = ttk.Label(pf, text="存档: (未打开)", foreground="gray", font=FONT_S)
        self._lbl_save.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self._lbl_tkt = ttk.Label(pf, text="TKT: (未加载)", foreground="gray", font=FONT_S)
        self._lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self._lbl_item = ttk.Label(pf, text="TKItem: (未加载)", foreground="gray", font=FONT_S)
        self._lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self._lbl_mu = ttk.Label(pf, text="Mu.JVG: (未加载)", foreground="gray", font=FONT_S)
        self._lbl_mu.pack(side=tk.LEFT, padx=10, pady=2)

    def _update_load_status(self):
        """更新底部当前加载状态 — 参照 item_editor/_update_paths"""
        g, r = "#228B22", "#CC3333"
        def _f(lb, p, label):
            if not p: lb.config(text=f"{label}: (未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"{label}: (不存在)", foreground=r)
            else: lb.config(text=f"{label}: {p}", foreground=g)
        parent = os.path.dirname(self.save_dir.rstrip('/\\')) if self.save_dir else None
        _f(self._lbl_save, self.save_dir, "存档")
        _f(self._lbl_tkt, os.path.join(parent, 'TKT.dat') if parent else None, "TKT")
        _f(self._lbl_item, os.path.join(parent, 'TKItem.dat') if parent else None, "TKItem")
        _f(self._lbl_mu, os.path.join(parent, 'Mu.JVG') if parent else None, "Mu.JVG")

    # ================================================================
    # Tab 0: 存档总览
    # ================================================================

    def _build_overview_tab(self):
        frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(frame, text=" 总览 ")

        # 槽位信息面板
        top = ttk.LabelFrame(frame, text="索引文件信息 (N.sav — 28字节)", padding=10)
        top.pack(fill=tk.X, pady=(0, 8))

        # 逆向证据标注
        info_text = ("格式来源: sub_41CE10 写入 / sub_41B1A8 读取\n"
                     "结构: [6B team_ids][2B gold][4B timestamp][12B levels][4B scene_id]")
        ttk.Label(top, text=info_text, font=FONT_S, foreground='#888').pack(anchor=tk.W)

        grid = ttk.Frame(top)
        grid.pack(fill=tk.X, pady=(8, 0))

        self._ov_vars = {}
        fields = [
            ("gold", "金钱"),
            ("timestamp", "存档时间"),
            ("scene_id", "场景ID"),
        ]
        for col, (key, label) in enumerate(fields):
            ttk.Label(grid, text=label, font=FONT_S).grid(row=0, column=col, padx=12, sticky='w')
            sv = tk.StringVar(value="—")
            self._ov_vars[key] = sv
            ttk.Label(grid, textvariable=sv, font=FONT_M).grid(row=1, column=col, padx=12, sticky='w')

        # 队伍预览
        team_frame = ttk.LabelFrame(frame, text="当前队伍", padding=10)
        team_frame.pack(fill=tk.X, pady=(0, 8))

        self._ov_team_labels = []
        for i in range(6):
            col_f = ttk.Frame(team_frame)
            col_f.pack(side=tk.LEFT, padx=12)
            ttk.Label(col_f, text=f"成员{i+1}", font=FONT_S, foreground='#666').pack()
            lbl = ttk.Label(col_f, text="—", font=FONT)
            lbl.pack()
            lv_lbl = ttk.Label(col_f, text="", font=FONT_S, foreground='#888')
            lv_lbl.pack()
            self._ov_team_labels.append((lbl, lv_lbl))

        # 摘要文本
        summary_frame = ttk.LabelFrame(frame, text="存档摘要", padding=10)
        summary_frame.pack(fill=tk.BOTH, expand=True)
        self._summary_text = tk.Text(summary_frame, height=12, font=FONT_M,
                                     state='disabled', wrap=tk.WORD, bg='#FAFAFA')
        sb = ttk.Scrollbar(summary_frame, orient=tk.VERTICAL, command=self._summary_text.yview)
        self._summary_text.configure(yscrollcommand=sb.set)
        self._summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    # ================================================================
    # Tab 1: 队伍与经济
    # ================================================================

    def _build_team_tab(self):
        frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(frame, text=" 队伍 ")

        # 队伍成员编辑
        lf = ttk.LabelFrame(frame, text="队伍成员 (word_75688C[6], -1=空槽)", padding=10)
        lf.pack(fill=tk.X, pady=(0, 8))

        self._team_vars = []
        self._team_name_labels = []
        for i in range(6):
            col = ttk.Frame(lf)
            col.pack(side=tk.LEFT, padx=10)
            ttk.Label(col, text=f"成员{i+1}", font=FONT_S).pack()
            sv = tk.StringVar(value="-1")
            self._team_vars.append(sv)
            ttk.Entry(col, textvariable=sv, width=6, font=FONT_M, justify='center').pack()
            nlbl = ttk.Label(col, text="", font=FONT_S, foreground='#3366CC')
            nlbl.pack()
            self._team_name_labels.append(nlbl)

        # 金钱与四维
        lf2 = ttk.LabelFrame(frame, text="经济与声望", padding=10)
        lf2.pack(fill=tk.X, pady=(0, 8))

        self._econ_vars = {}
        econ_fields = [
            ("gold", "金钱 (上限30000)"),
            ("wisdom", "智慧"),
            ("benevolence", "仁德"),
            ("courage", "勇气"),
            ("medicine", "医术 (上限100)"),
        ]
        for key, label in econ_fields:
            col = ttk.Frame(lf2)
            col.pack(side=tk.LEFT, padx=10)
            ttk.Label(col, text=label, font=FONT_S).pack()
            sv = tk.StringVar(value="0")
            self._econ_vars[key] = sv
            ttk.Entry(col, textvariable=sv, width=8, font=FONT_M, justify='center').pack()

        # 战斗统计
        lf3 = ttk.LabelFrame(frame, text="战斗统计", padding=10)
        lf3.pack(fill=tk.X, pady=(0, 8))

        self._battle_vars = {}
        for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
            col = ttk.Frame(lf3)
            col.pack(side=tk.LEFT, padx=10)
            lbl = ttk.Label(col, text=label, font=FONT_S)
            lbl.pack()
            self._bind_tooltip(lbl, cmt)
            sv = tk.StringVar(value="0")
            self._battle_vars[key] = sv
            ttk.Entry(col, textvariable=sv, width=8, font=FONT_M, justify='center').pack()

        # 应用按钮
        btn_f = ttk.Frame(frame)
        btn_f.pack(fill=tk.X, pady=4)
        ttk.Button(btn_f, text="应用队伍修改", command=self._apply_team).pack(side=tk.LEFT)
        ttk.Label(btn_f, text="(修改后需保存到文件才生效)", font=FONT_S,
                  foreground='#888').pack(side=tk.LEFT, padx=8)

    # ================================================================
    # Tab 2: 物品
    # ================================================================

    def _build_inventory_tab(self):
        frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(frame, text=" 物品 ")

        ctrl = ttk.Frame(frame)
        ctrl.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(ctrl, text="物品种类数:", font=FONT_S).pack(side=tk.LEFT)
        self._inv_count_var = tk.StringVar(value="0")
        ttk.Entry(ctrl, textvariable=self._inv_count_var, width=6, font=FONT_M).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="刷新列表", command=self._refresh_inventory).pack(side=tk.LEFT, padx=8)
        ttk.Button(ctrl, text="应用物品修改", command=self._apply_inventory).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="新增物品", command=self._add_inv_item_dialog).pack(side=tk.LEFT, padx=8)

        # 物品列表 Treeview — 参照 item_editor 布局
        cols = ('idx', 'item_id', 'page', 'name', 'qty')
        tree_f = ttk.Frame(frame)
        tree_f.pack(fill=tk.BOTH, expand=True)
        self._inv_tree = ttk.Treeview(tree_f, columns=cols, show='tree headings', height=20)
        self._inv_tree.column('#0', width=36, minwidth=36, stretch=False, anchor='center')
        self._inv_tree.heading('#0', text='')
        for cid, cn, cw in [('idx','#',38),('item_id','ID',48),('page','页面',48),
                             ('name','物品名称',200),('qty','数量',48)]:
            self._inv_tree.heading(cid, text=cn)
            self._inv_tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w')
        vsb = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=self._inv_tree.yview)
        self._inv_tree.configure(yscrollcommand=vsb.set)
        self._inv_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._inv_photos = []  # prevent GC

        # 编辑区
        edit_f = ttk.LabelFrame(frame, text="编辑选中物品", padding=8)
        edit_f.pack(fill=tk.X, pady=(4, 0))
        self._inv_edit_id_var = tk.StringVar()
        self._inv_edit_qty_var = tk.StringVar()
        ttk.Label(edit_f, text="物品ID:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(edit_f, textvariable=self._inv_edit_id_var, width=8, font=FONT_M).pack(side=tk.LEFT, padx=2)
        ttk.Label(edit_f, text="数量:").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(edit_f, textvariable=self._inv_edit_qty_var, width=6, font=FONT_M).pack(side=tk.LEFT, padx=2)
        ttk.Button(edit_f, text="修改", command=self._apply_inv_edit).pack(side=tk.LEFT, padx=8)
        ttk.Button(edit_f, text="删除选中", command=self._delete_inv_item).pack(side=tk.LEFT, padx=4)

        self._inv_tree.bind('<<TreeviewSelect>>', self._on_inv_select)

    # ================================================================
    # Tab 3: 全局状态
    # ================================================================

    def _build_global_tab(self):
        frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(frame, text=" 全局状态 ")

        # 可滚动
        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll = ttk.Frame(canvas)
        scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._global_vars = {}

        # 基本状态
        self._build_global_section(scroll, "基本状态 (SEG1)", SEG1_BASIC_FIELDS, 'seg1')
        self._build_global_section(scroll, "编成槽", SEG1_SLOT_FIELDS, 'seg1')
        self._build_global_section(scroll, "地图相关", SEG1_MAP_FIELDS, 'seg1')
        self._build_global_section(scroll, "事件系统", SEG1_EVENT_FIELDS, 'seg1')

        # 事件开关/变量 (压缩显示)
        self._build_array_editor(scroll, "事件开关 [32项]", "switches", 0x2F8, 32, 2, 'seg1')
        self._build_array_editor(scroll, "事件变量 [256项]", "variables", 0x368, 256, 2, 'seg1')

        # 应用按钮
        btn_f = ttk.Frame(scroll)
        btn_f.pack(fill=tk.X, pady=8)
        ttk.Button(btn_f, text="应用全局状态修改", command=self._apply_global).pack(side=tk.LEFT)

    def _build_global_section(self, parent, title, fields, seg):
        lf = ttk.LabelFrame(parent, text=title, padding=8)
        lf.pack(fill=tk.X, padx=4, pady=4)
        for row, (key, off, size, label, fmt, cmt) in enumerate(fields):
            ttk.Label(lf, text=f"{label} [+0x{off:X}]", font=FONT_S).grid(
                row=row, column=0, sticky='w', padx=4, pady=1)
            sv = tk.StringVar()
            self._global_vars[key] = (sv, off, size, fmt, seg)
            ttk.Entry(lf, textvariable=sv, width=16, font=FONT_M).grid(
                row=row, column=1, sticky='w', padx=4)
            ttk.Label(lf, text=cmt, font=FONT_S, foreground='#888').grid(
                row=row, column=2, sticky='w', padx=4)

    def _build_array_editor(self, parent, title, key, offset, count, elem_size, seg):
        lf = ttk.LabelFrame(parent, text=title, padding=8)
        lf.pack(fill=tk.X, padx=4, pady=4)

        # 使用Text控件紧凑显示
        txt = tk.Text(lf, height=min(4, (count + 15) // 16), font=FONT_M, wrap=tk.WORD)
        txt.pack(fill=tk.X)
        self._global_vars[f'_arr_{key}'] = (txt, offset, count, elem_size, seg)

    # ================================================================
    # Tab 4: WarPC 角色数据
    # ================================================================

    def _build_warpc_tab(self):
        frame = ttk.Frame(self.nb, padding=8)
        self.nb.add(frame, text=" 角色 ")

        paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # --- 左侧: 角色列表 ---
        left = ttk.Frame(paned, width=380)
        paned.add(left, weight=1)

        # 搜索/过滤
        sf = ttk.Frame(left)
        sf.pack(fill=tk.X, pady=(0, 4))
        self._warpc_search_var = tk.StringVar()
        se = ttk.Entry(sf, textvariable=self._warpc_search_var)
        se.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        se.insert(0, "搜索角色...")
        se.bind('<FocusIn>', lambda e: se.delete(0, tk.END) if se.get() == "搜索角色..." else None)
        se.bind('<FocusOut>', lambda e: se.insert(0, "搜索角色...") if not se.get() else None)
        self._warpc_search_var.trace_add('write', lambda *a: self._refresh_warpc_list())

        self._warpc_filter_var = tk.StringVar(value="全部")
        ttk.Combobox(sf, textvariable=self._warpc_filter_var, state='readonly',
                     values=["全部", "未激活", "已激活"], width=8).pack(side=tk.LEFT)
        self._warpc_filter_var.trace_add('write', lambda *a: self._refresh_warpc_list())

        # TreeView
        tree_f = ttk.Frame(left)
        tree_f.pack(fill=tk.BOTH, expand=True)
        cols = ('idx', 'name', 'lv', 'role', 'hp', 'mp')
        self._warpc_tree = ttk.Treeview(tree_f, columns=cols, show='headings', selectmode='browse')
        for cid, cn, cw in [('idx','#',35),('name','名称',110),('lv','LV',35),
                             ('role','身份',40),('hp','HP',55),('mp','MP',55)]:
            self._warpc_tree.heading(cid, text=cn)
            self._warpc_tree.column(cid, width=cw, minwidth=cw, anchor='center')
        vsb = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=self._warpc_tree.yview)
        self._warpc_tree.configure(yscrollcommand=vsb.set)
        self._warpc_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._warpc_tree.bind('<<TreeviewSelect>>', self._on_warpc_select)

        # --- 右侧: 编辑面板 ---
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self._warpc_right = right
        self._warpc_cur_idx = -1
        self._warpc_edit_vars = {}

        # 初始占位
        self._warpc_placeholder = ttk.Label(right, text="← 选择左侧角色进行编辑",
                                            font=FONT, foreground='#999')
        self._warpc_placeholder.pack(expand=True)

    # ================================================================
    # 数据加载
    # ================================================================

    def _cmd_open(self):
        d = filedialog.askdirectory(title="选择存档目录 (包含 save 子目录或直接包含 sav.N 文件)")
        if not d:
            return
        # 智能检测: 目录本身包含 sav.N 或其 save 子目录
        if os.path.exists(os.path.join(d, 'sav.1')):
            self.save_dir = d
        elif os.path.exists(os.path.join(d, 'save', 'sav.1')):
            self.save_dir = os.path.join(d, 'save')
        else:
            self.save_dir = d

        # 加载外部资源
        self._load_resources()
        self._update_load_status()
        # 加载第一个存在的槽位
        for s in range(1, 10):
            if os.path.exists(os.path.join(self.save_dir, f'sav.{s}')):
                self._switch_slot(s)
                return
        messagebox.showwarning("未找到存档", f"目录中未找到任何 sav.N 文件:\n{self.save_dir}")

    def _load_resources(self):
        """加载 TKT/TKItem/TKSkill/Mu.JVG 等外部资源."""
        parent = os.path.dirname(self.save_dir.rstrip('/\\'))
        # TKT
        tkt_path = os.path.join(parent, 'TKT.dat')
        if os.path.exists(tkt_path):
            self.tkt = load_tkt(tkt_path)
        # TKSkill
        sk_path = os.path.join(parent, 'TKSkill.dat')
        if os.path.exists(sk_path):
            self.skill_names = self._parse_skill_dat(sk_path)
        # TKItem
        it_path = os.path.join(parent, 'TKItem.dat')
        if os.path.exists(it_path):
            self.item_records, self.item_names, self.item_idx_names = self._parse_item_dat(it_path)
        # Mu.JVG 图标
        mu_path = os.path.join(parent, 'Mu.JVG')
        self._mu_sprites = []
        self._icon_photos = {}
        if os.path.exists(mu_path):
            try:
                self._mu_sprites = _load_mu_sprites(mu_path)
            except Exception:
                pass

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
        """加载 TKItem.dat, 返回 (records_by_idx, id_names, idx_names).
        records_by_idx: {TKItem数组下标: {item_id,name_id,tab_code,icon,...}}
        id_names: {item_id: name}  (辅助, 装备编辑器用)
        idx_names: {TKItem下标: name}
        """
        try:
            with open(path, 'rb') as f:
                dec = lzss_decompress_dat(f.read())
        except Exception:
            return {}, {}, {}
        idx_records = {}
        id_lookup = {}
        idx_lookup = {}
        for i in range(600):
            off = i * 64
            if off + 10 > len(dec): break
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
            rec = {'item_id': item_id, 'name_id': name_id, 'tab_code': tab_code,
                   'icon': icon, 'equip_type': equip_type, 'price': price, 'name': nm}
            if item_id > 0:
                id_lookup[item_id] = nm
            idx_records[i] = rec
            if nm:
                idx_lookup[i] = nm
        return idx_records, id_lookup, idx_lookup

    def _switch_slot(self, slot_num):
        """切换到指定槽位."""
        if self._dirty:
            if not messagebox.askyesno("未保存", "当前有未保存修改，是否放弃并切换?"):
                return
        self.slot = slot_num
        self._load_current_slot()
        # 高亮当前槽位按钮
        for i, btn in enumerate(self._slot_btns):
            if i + 1 == slot_num:
                btn.state(['pressed'])
            else:
                btn.state(['!pressed'])

    def _load_current_slot(self):
        """加载当前槽位数据."""
        if not self.save_dir:
            return
        sav_data_path = os.path.join(self.save_dir, f'sav.{self.slot}')
        sav_index_path = os.path.join(self.save_dir, f'{self.slot}.sav')

        if not os.path.exists(sav_data_path):
            self._status_var.set(f"槽位 {self.slot}: 数据文件不存在")
            self.game_state = self.seg1 = self.seg2 = self.seg3 = None
            self.index_meta = None
            return

        try:
            self.game_state, self.seg1, self.seg2, self.seg3 = load_save_data(sav_data_path)
            # 动态计算 WarPC 角色数量 (兼容 TKSLauncher 扩展)
            self.warpc_count = len(self.seg3) // WARPC_REC
        except Exception as e:
            messagebox.showerror("加载失败", f"解析存档失败:\n{e}")
            self.game_state = None
            return

        # 加载索引文件
        self.index_meta = load_index_file(sav_index_path)
        self._dirty = False
        self._refresh_all()

        size_info = (f"Frame1={GAMESTATE_SIZE:,}B  "
                     f"SEG1={SEG1_SIZE}B  SEG2={SEG2_SIZE}B  "
                     f"WarPC={len(self.seg3):,}B ({self.warpc_count}角色)")
        self._status_var.set(f"槽位 {self.slot} 已加载 | {size_info}")

    def _refresh_all(self):
        """刷新所有 Tab 显示."""
        self._refresh_overview()
        self._refresh_team()
        self._refresh_inventory()
        self._refresh_global()
        self._refresh_warpc_list()

    # ================================================================
    # 数据填充 — 总览
    # ================================================================

    def _refresh_overview(self):
        if self.index_meta:
            m = self.index_meta
            self._ov_vars['gold'].set(str(m['gold']))
            try:
                ts = m['timestamp']
                dt = datetime.datetime.fromtimestamp(ts)
                self._ov_vars['timestamp'].set(dt.strftime('%Y-%m-%d %H:%M:%S'))
            except Exception:
                self._ov_vars['timestamp'].set(str(m['timestamp']))
            self._ov_vars['scene_id'].set(str(m['scene_id']))

            for i in range(6):
                tid = m['team_ids'][i]
                lv = m['team_levels'][i]
                name = self._get_char_name(tid) if tid >= 0 else "(空)"
                self._ov_team_labels[i][0].config(text=name)
                self._ov_team_labels[i][1].config(text=f"Lv.{lv}" if tid >= 0 else "")
        else:
            for k in self._ov_vars:
                self._ov_vars[k].set("—")
            for lbl, lv_lbl in self._ov_team_labels:
                lbl.config(text="—")
                lv_lbl.config(text="")

        # 摘要
        lines = []
        if self.game_state is not None:
            lines.append(f"存档目录: {self.save_dir}")
            lines.append(f"当前槽位: {self.slot}")
            lines.append(f"数据文件: sav.{self.slot} ({os.path.getsize(os.path.join(self.save_dir, f'sav.{self.slot}')):,} bytes)")
            lines.append(f"Frame1 (TKMat实体表): {GAMESTATE_SIZE:,} bytes")
            lines.append(f"Frame2: SEG1={SEG1_SIZE}B + SEG2={SEG2_SIZE}B + WarPC={len(self.seg3):,}B")
            lines.append(f"WarPC 角色数: {self.warpc_count} (记录大小 {WARPC_REC}B)")
            if self.warpc_count != WARPC_ORIG_CNT:
                lines.append(f"  ⚠ 非标准角色数 (原始143), 已被TKSLauncher扩展")
            # 队伍
            if self.seg2:
                gold = struct.unpack_from('<H', self.seg2, 0x02)[0]
                lines.append(f"金钱: {gold}")
                team_strs = []
                for i in range(6):
                    tid = struct.unpack_from('<h', self.seg2, 0x0C + i*2)[0]
                    if tid >= 0:
                        team_strs.append(f"{self._get_char_name(tid)}(#{tid})")
                lines.append(f"队伍: {', '.join(team_strs) if team_strs else '(空)'}")
            # 全部9槽位状态
            lines.append("")
            lines.append("═══ 全部槽位状态 ═══")
            for s in range(1, 10):
                idx_path = os.path.join(self.save_dir, f'{s}.sav')
                data_path = os.path.join(self.save_dir, f'sav.{s}')
                if os.path.exists(data_path):
                    meta = load_index_file(idx_path)
                    if meta:
                        names = [self._get_char_name(t) for t in meta['team_ids'] if t >= 0]
                        try:
                            ts_str = datetime.datetime.fromtimestamp(meta['timestamp']).strftime('%m/%d %H:%M')
                        except Exception:
                            ts_str = "?"
                        lines.append(f"  槽{s}: {ts_str} | {', '.join(names[:3])}{'...' if len(names)>3 else ''}")
                    else:
                        lines.append(f"  槽{s}: (索引损坏)")
                else:
                    lines.append(f"  槽{s}: (空)")

        self._summary_text.configure(state='normal')
        self._summary_text.delete('1.0', tk.END)
        self._summary_text.insert('1.0', '\n'.join(lines))
        self._summary_text.configure(state='disabled')

    # ================================================================
    # 数据填充 — 队伍
    # ================================================================

    def _refresh_team(self):
        if self.seg2 is None:
            return
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i*2)[0]
            self._team_vars[i].set(str(tid))
            self._team_name_labels[i].config(
                text=self._get_char_name(tid) if tid >= 0 else "(空)")
        for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
            val = struct.unpack_from('<' + fmt, self.seg2, off)[0]
            if key in self._econ_vars:
                self._econ_vars[key].set(str(val))
        for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
            val = struct.unpack_from('<H', self.seg2, off)[0]
            if key in self._battle_vars:
                self._battle_vars[key].set(str(val))

    # ================================================================
    # 数据填充 — 物品
    # ================================================================

    def _refresh_inventory(self):
        if self.seg2 is None:
            return
        key, off, size, label, fmt, cmt = SEG2_INV_COUNT
        count = struct.unpack_from('<H', self.seg2, off)[0]
        self._inv_count_var.set(str(count))

        self._inv_tree.delete(*self._inv_tree.get_children())
        self._inv_photos.clear()
        off_items = SEG2_INVENTORY[0][1]
        off_types = SEG2_INVENTORY[1][1]
        off_qtys = SEG2_INVENTORY[2][1]
        for i in range(min(count, 600)):
            item_id = struct.unpack_from('<h', self.seg2, off_items + i*2)[0]
            type_idx = struct.unpack_from('<H', self.seg2, off_types + i*2)[0]
            qty = struct.unpack_from('<H', self.seg2, off_qtys + i*2)[0]
            # 用 type_idx (TKItem数组下标) 查找物品信息
            rec = self.item_records.get(type_idx, {})
            name = rec.get('name', f'物品#{item_id}') if rec else f'物品#{item_id}'
            tab = rec.get('tab_code', 0)
            page = PAGE_NAMES.get(tab, '?')
            icon_val = rec.get('icon', 0)
            photo = _get_icon_photo(self._mu_sprites, icon_val, (24,24), self._icon_photos)
            self._inv_photos.append(photo)
            self._inv_tree.insert('', tk.END,
                image=photo if photo else '',
                values=(i, item_id, page, name, qty))

    def _on_inv_select(self, event=None):
        sel = self._inv_tree.selection()
        if sel:
            vals = self._inv_tree.item(sel[0], 'values')
            self._inv_edit_id_var.set(str(vals[1]))
            self._inv_edit_qty_var.set(str(vals[4]))

    def _apply_inv_edit(self):
        sel = self._inv_tree.selection()
        if not sel or self.seg2 is None:
            return
        vals = self._inv_tree.item(sel[0], 'values')
        idx = int(vals[0])
        try:
            new_id = int(self._inv_edit_id_var.get())
            new_qty = int(self._inv_edit_qty_var.get())
        except ValueError:
            messagebox.showerror("输入错误", "请输入有效数字")
            return
        # 通过 item_id 反查 TKItem 数组下标
        new_type = self._find_item_idx_by_id(new_id)
        struct.pack_into('<h', self.seg2, SEG2_INVENTORY[0][1] + idx*2, new_id)
        struct.pack_into('<H', self.seg2, SEG2_INVENTORY[1][1] + idx*2, new_type)
        struct.pack_into('<H', self.seg2, SEG2_INVENTORY[2][1] + idx*2, new_qty)
        self._dirty = True
        self._refresh_inventory()

    def _find_item_idx_by_id(self, item_id):
        """通过 item_id 反查 TKItem 数组下标，找不到返回0."""
        for arr_idx, rec in self.item_records.items():
            if rec.get('item_id') == item_id:
                return arr_idx
        return 0

    def _delete_inv_item(self):
        sel = self._inv_tree.selection()
        if not sel or self.seg2 is None:
            return
        vals = self._inv_tree.item(sel[0], 'values')
        idx = int(vals[0])
        count_off = SEG2_INV_COUNT[1]
        arr_offs = [f[1] for f in SEG2_INVENTORY]
        count = struct.unpack_from('<H', self.seg2, count_off)[0]
        if idx >= count:
            return
        # 移动后续物品前移
        for i in range(idx, count - 1):
            for arr_off in arr_offs:
                v = struct.unpack_from('<H', self.seg2, arr_off + (i+1)*2)[0]
                struct.pack_into('<H', self.seg2, arr_off + i*2, v)
        # 清除末尾
        for arr_off in arr_offs:
            struct.pack_into('<H', self.seg2, arr_off + (count-1)*2, 0)
        struct.pack_into('<H', self.seg2, count_off, count - 1)
        self._dirty = True
        self._refresh_inventory()

    def _add_inv_item_dialog(self):
        """弹出全物品选择对话框 (与 item_editor 左侧列表一致)."""
        if not self.item_records:
            messagebox.showinfo("提示", "请先加载存档目录 (需要TKItem.dat)")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("新增物品 — 选择物品")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("640x560")
        dlg.minsize(480, 360)
        # 居中
        dlg.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        dw = dlg.winfo_width()
        dh = dlg.winfo_height()
        dlg.geometry(f"+{rx+(rw-dw)//2}+{ry+(rh-dh)//2}")

        # 搜索栏 (参照 item_editor 布局)
        sf = ttk.Frame(dlg, padding=5)
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:", font=FONT_S).pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=22, font=FONT).pack(side=tk.LEFT, padx=5)
        ttk.Button(sf, text="清除", command=lambda: qv.set(""), width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(sf, text="页面:", font=FONT_S).pack(side=tk.LEFT, padx=(10, 2))
        page_var = tk.StringVar(value="全部页面")
        page_vals = ["全部页面"] + [f"{k}-{v}" for k, v in PAGE_NAMES.items()]
        ttk.Combobox(sf, textvariable=page_var, values=page_vals,
                     state='readonly', width=10).pack(side=tk.LEFT, padx=2)

        nonempty_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sf, text="仅非空", variable=nonempty_var).pack(side=tk.LEFT, padx=10)

        # 物品列表 Treeview (与 item_editor 左侧一致: 图标列 + index/ID/页面/名称/价格)
        tree_f = ttk.Frame(dlg)
        tree_f.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        cols = ('index', 'item_id', 'page', 'name', 'price')
        tree = ttk.Treeview(tree_f, columns=cols, show='tree headings', selectmode='browse')
        tree.column('#0', width=36, minwidth=36, stretch=False, anchor='center')
        tree.heading('#0', text='')
        for cid, cn, cw in [('index','#',38), ('item_id','ID',42), ('page','页面',48),
                             ('name','物品名称',200), ('price','价格',48)]:
            tree.heading(cid, text=cn)
            tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w')
        vsb = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        def _mw(e):
            tree.yview_scroll(int(-1*(e.delta/120)), "units")
        tree.bind("<Enter>", lambda e: tree.bind_all("<MouseWheel>", _mw))
        tree.bind("<Leave>", lambda e: tree.unbind_all("<MouseWheel>"))

        # 底部: 数量 + 按钮
        bf = ttk.Frame(dlg, padding=5)
        bf.pack(fill=tk.X)
        ttk.Label(bf, text="数量:", font=FONT).pack(side=tk.LEFT)
        qty_var = tk.StringVar(value="1")
        ttk.Entry(bf, textvariable=qty_var, width=8, font=FONT_M, justify='center').pack(side=tk.LEFT, padx=4)
        ttk.Label(bf, text="(上限30000)", font=FONT_S, foreground='#888').pack(side=tk.LEFT)

        selected = {'idx': None, 'item_id': None}

        def _do_add():
            if selected['idx'] is None:
                messagebox.showwarning("提示", "请先在列表中选择物品", parent=dlg)
                return
            try:
                qty = int(qty_var.get())
                if qty <= 0 or qty > 30000:
                    raise ValueError
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效数量 (1-30000)", parent=dlg)
                return
            self._add_inv_item_to_inventory(selected['idx'], selected['item_id'], qty)
            dlg.destroy()

        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="添加", command=_do_add).pack(side=tk.RIGHT, padx=2)
        tree.bind('<Double-1>', lambda e: _do_add())

        # 填充列表 + 筛选
        photos = []

        def _refresh(*args):
            tree.delete(*tree.get_children())
            photos.clear()
            q = qv.get().strip().lower()
            pg = page_var.get()
            ne = nonempty_var.get()

            for arr_idx, rec in self.item_records.items():
                name = rec.get('name', '')
                item_id = rec.get('item_id', 0)
                tab = rec.get('tab_code', 0)
                price = rec.get('price', 0)
                icon_val = rec.get('icon', 0)

                if ne and not name:
                    continue
                if pg != "全部页面":
                    if tab != int(pg.split('-')[0]):
                        continue
                if q:
                    if q not in f"{arr_idx} {item_id} {name}".lower():
                        continue

                page_name = PAGE_NAMES.get(tab, '?')
                photo = _get_icon_photo(self._mu_sprites, icon_val, (24, 24), self._icon_photos)
                photos.append(photo)
                tree.insert('', tk.END,
                           image=photo if photo else '',
                           values=(arr_idx, item_id, page_name, name, price))

        qv.trace_add('write', lambda *a: _refresh())
        page_var.trace_add('write', lambda *a: _refresh())
        nonempty_var.trace_add('write', lambda *a: _refresh())

        def _on_select(event):
            sel = tree.selection()
            if sel:
                vals = tree.item(sel[0], 'values')
                selected['idx'] = int(vals[0])
                selected['item_id'] = int(vals[1])

        tree.bind('<<TreeviewSelect>>', _on_select)

        _refresh()
        dlg.wait_window()

    def _add_inv_item_to_inventory(self, type_idx, item_id, qty):
        """添加物品: 已存在则叠加数量, 不存在则新增."""
        if self.seg2 is None:
            return

        count_off = SEG2_INV_COUNT[1]
        off_items = SEG2_INVENTORY[0][1]
        off_types = SEG2_INVENTORY[1][1]
        off_qtys = SEG2_INVENTORY[2][1]

        count = struct.unpack_from('<H', self.seg2, count_off)[0]

        # 检查是否已存在相同物品 (通过 inv_types 即 TKItem 数组下标比较)
        for i in range(min(count, 600)):
            existing_type = struct.unpack_from('<H', self.seg2, off_types + i*2)[0]
            if existing_type == type_idx:
                old_qty = struct.unpack_from('<H', self.seg2, off_qtys + i*2)[0]
                new_qty = min(old_qty + qty, 30000)
                struct.pack_into('<H', self.seg2, off_qtys + i*2, new_qty)
                self._dirty = True
                self._refresh_inventory()
                rec = self.item_records.get(type_idx, {})
                name = rec.get('name', f'物品#{item_id}')
                self._status_var.set(f"物品已存在: {name}  数量 {old_qty} → {new_qty}")
                return

        # 不存在，新增到末尾
        if count >= 600:
            messagebox.showwarning("物品已满", "物品已达上限 600 种")
            return

        struct.pack_into('<h', self.seg2, off_items + count*2, item_id)
        struct.pack_into('<H', self.seg2, off_types + count*2, type_idx)
        struct.pack_into('<H', self.seg2, off_qtys + count*2, qty)
        struct.pack_into('<H', self.seg2, count_off, count + 1)

        self._dirty = True
        self._refresh_inventory()
        rec = self.item_records.get(type_idx, {})
        name = rec.get('name', f'物品#{item_id}')
        self._status_var.set(f"已添加: {name} ×{qty}")

    # ================================================================
    # 数据填充 — 全局
    # ================================================================

    def _refresh_global(self):
        if self.seg1 is None:
            return
        for key, (sv, off, size, fmt, seg) in self._global_vars.items():
            if key.startswith('_arr_'):
                continue
            data = self.seg1 if seg == 'seg1' else self.seg2
            if data is None or off + size > len(data):
                continue
            if fmt == 'big5':
                sv.set(self._decode_big5(data[off:off+size]))
            else:
                sv.set(str(struct.unpack_from(fmt, data, off)[0]))

        # 数组字段
        for key, info in self._global_vars.items():
            if not key.startswith('_arr_'):
                continue
            txt_widget, offset, count, elem_size, seg = info
            data = self.seg1 if seg == 'seg1' else self.seg2
            if data is None:
                continue
            fmt_c = 'B' if elem_size == 1 else '<H'
            vals = []
            for i in range(count):
                o = offset + i * elem_size
                if o + elem_size <= len(data):
                    v = struct.unpack_from(fmt_c, data, o)[0] if elem_size > 1 else data[o]
                    vals.append(str(v))
            txt_widget.configure(state='normal')
            txt_widget.delete('1.0', tk.END)
            txt_widget.insert('1.0', ' '.join(vals))
            txt_widget.configure(state='normal')  # 保持可编辑

    # ================================================================
    # 数据填充 — WarPC 列表
    # ================================================================

    def _refresh_warpc_list(self):
        tree = self._warpc_tree
        tree.delete(*tree.get_children())
        if self.seg3 is None:
            return

        # 获取当前队伍成员 (word_75688C)
        team_set = set()
        if self.seg2 is not None:
            for i in range(6):
                tid = struct.unpack_from('<h', self.seg2, 0x0C + i*2)[0]
                if tid >= 0:
                    team_set.add(tid)

        search = self._warpc_search_var.get().strip().lower()
        if search == "搜索角色...":
            search = ""
        filt = self._warpc_filter_var.get()

        for i in range(self.warpc_count):
            name_id = warpc_get(self.seg3, i, 0)
            lv = warpc_get(self.seg3, i, 4)
            role = warpc_get(self.seg3, i, 6)
            hp = warpc_get(self.seg3, i, 10)
            mp = warpc_get(self.seg3, i, 12)
            name = self.tkt.get(name_id, f"ID:{name_id}") if name_id else ""

            in_team = i in team_set
            if filt == "未激活":
                if role != -1:
                    continue
            elif filt == "已激活":
                if role != 0:
                    continue

            if search and search not in str(i) and search not in name.lower():
                continue

            if in_team:
                role_str = "队伍"
                tag = 'party'
            elif role == -1:
                role_str = "未激活"
                tag = 'inactive'
            else:
                role_str = "已激活"
                tag = 'active'
            tree.insert('', tk.END, values=(i, name, lv, role_str, hp, mp), tags=(tag,))

        tree.tag_configure('party', foreground='#228B22')
        tree.tag_configure('inactive', foreground='#2266CC')
        tree.tag_configure('active', foreground='#CC3333')

    def _on_warpc_select(self, event=None):
        sel = self._warpc_tree.selection()
        if not sel:
            return
        vals = self._warpc_tree.item(sel[0], 'values')
        idx = int(vals[0])
        self._warpc_cur_idx = idx
        self._build_warpc_editor(idx)

    def _build_warpc_editor(self, idx):
        """构建/刷新角色编辑面板."""
        # 清除旧控件
        for w in self._warpc_right.winfo_children():
            w.destroy()
        self._warpc_edit_vars = {}

        if self.seg3 is None or idx < 0:
            return

        # 标题 (包含队伍状态)
        name_id = warpc_get(self.seg3, idx, 0)
        name = self.tkt.get(name_id, f"ID:{name_id}")
        in_team = False
        if self.seg2 is not None:
            for ti in range(6):
                if struct.unpack_from('<h', self.seg2, 0x0C + ti*2)[0] == idx:
                    in_team = True
                    break
        status = " [队伍中]" if in_team else ""
        ttk.Label(self._warpc_right, text=f"角色 #{idx} - {name}{status}",
                  font=FONT_TITLE).pack(anchor=tk.W, padx=4, pady=(4, 2))

        # 编辑区 (可滚动)
        canvas = tk.Canvas(self._warpc_right, highlightthickness=0)
        sb = ttk.Scrollbar(self._warpc_right, orient=tk.VERTICAL, command=canvas.yview)
        scroll = ttk.Frame(canvas)
        scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        # 各区段
        self._warpc_section(scroll, "身份信息", WARPC_IDENTITY, idx)
        self._warpc_section(scroll, "HP / MP", WARPC_HPMP, idx)
        self._warpc_stat_section(scroll, idx)
        self._warpc_section(scroll, "角色五维", WARPC_CHAR_ATTR, idx)
        self._warpc_section(scroll, "技能加成", WARPC_SKILL_BONUS, idx)
        self._warpc_section(scroll, "装备", WARPC_EQUIP, idx)
        self._warpc_section(scroll, "装备技能", WARPC_EQUIP_SKILL_FIELDS, idx)
        self._warpc_section(scroll, "成长率", WARPC_GROWTH, idx)
        self._warpc_section(scroll, "战后奖励/掉落", WARPC_BATTLE_REWARD + WARPC_DROP, idx)

        # 应用按钮
        btn_f = ttk.Frame(scroll)
        btn_f.pack(fill=tk.X, pady=8, padx=4)
        ttk.Button(btn_f, text="应用角色修改", command=self._apply_warpc).pack(side=tk.LEFT)
        ttk.Label(btn_f, text="(修改后需保存到文件)", font=FONT_S,
                  foreground='#888').pack(side=tk.LEFT, padx=8)

    def _warpc_section(self, parent, title, fields, idx):
        lf = ttk.LabelFrame(parent, text=title, padding=6)
        lf.pack(fill=tk.X, padx=4, pady=3)
        cols = 4
        for fi, item in enumerate(fields):
            fn, fo, label = item[0], item[1], item[2]
            cmt = item[3] if len(item) > 3 else ""
            r, c = divmod(fi, cols)
            frm = ttk.Frame(lf)
            frm.grid(row=r, column=c, sticky='nw', padx=4, pady=2)
            ttk.Label(frm, text=f"{label} [{fo}]", font=FONT_S).pack(anchor=tk.W)
            val = warpc_get(self.seg3, idx, fo)
            sv = tk.StringVar(value=str(val))
            self._warpc_edit_vars[fn] = (sv, fo)
            ttk.Entry(frm, textvariable=sv, width=10, font=FONT_M).pack(fill=tk.X)
            if cmt:
                ttk.Label(frm, text=cmt, font=('', 7), foreground='#999',
                          wraplength=120).pack(anchor=tk.W)

    def _warpc_stat_section(self, parent, idx):
        """八属性专用区段."""
        lf = ttk.LabelFrame(parent, text="八属性 (基础/当前)", padding=6)
        lf.pack(fill=tk.X, padx=4, pady=3)
        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_OFFSETS)):
            col = ttk.Frame(lf)
            col.grid(row=0, column=ci, sticky='n', padx=4, pady=2)
            ttk.Label(col, text=name, font=('', 9, 'bold')).pack()
            base_val = warpc_get(self.seg3, idx, bo)
            cur_val = warpc_get(self.seg3, idx, bo + 2)
            sv_b = tk.StringVar(value=str(base_val))
            sv_c = tk.StringVar(value=str(cur_val))
            self._warpc_edit_vars[f'{short}_base'] = (sv_b, bo)
            self._warpc_edit_vars[f'{short}_cur'] = (sv_c, bo + 2)
            f1 = ttk.Frame(col)
            f1.pack(fill=tk.X)
            ttk.Label(f1, text="基", font=FONT_S, foreground='#888').pack(side=tk.LEFT)
            ttk.Entry(f1, textvariable=sv_b, width=5, font=FONT_M, justify='center').pack(side=tk.RIGHT)
            f2 = ttk.Frame(col)
            f2.pack(fill=tk.X)
            ttk.Label(f2, text="当", font=FONT_S, foreground='#228B22').pack(side=tk.LEFT)
            ttk.Entry(f2, textvariable=sv_c, width=5, font=FONT_M, justify='center').pack(side=tk.RIGHT)

    # ================================================================
    # 应用修改
    # ================================================================

    def _apply_team(self):
        if self.seg2 is None:
            return
        try:
            for i in range(6):
                v = int(self._team_vars[i].get())
                struct.pack_into('<h', self.seg2, 0x0C + i*2, v)
            for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
                if key in self._econ_vars:
                    v = int(self._econ_vars[key].get())
                    mask = 0xFFFF if size == 2 else 0xFF
                    struct.pack_into('<' + fmt, self.seg2, off, v & mask)
            for key, off, size, label, fmt, cmt in SEG2_BATTLE_FIELDS:
                if key in self._battle_vars:
                    v = int(self._battle_vars[key].get())
                    struct.pack_into('<H', self.seg2, off, v & 0xFFFF)
            self._dirty = True
            self._status_var.set(f"槽位 {self.slot}: 队伍数据已修改 (未保存)")
            # 更新索引元数据
            self._sync_index_from_seg2()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))

    def _apply_inventory(self):
        if self.seg2 is None:
            return
        try:
            count = int(self._inv_count_var.get())
            struct.pack_into('<H', self.seg2, SEG2_INV_COUNT[1], count & 0xFFFF)
            self._dirty = True
            self._refresh_inventory()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))

    def _apply_global(self):
        if self.seg1 is None:
            return
        try:
            for key, (sv, off, size, fmt, seg) in self._global_vars.items():
                if key.startswith('_arr_'):
                    continue
                data = self.seg1 if seg == 'seg1' else self.seg2
                if data is None:
                    continue
                txt = sv.get()
                if fmt == 'big5':
                    data[off:off+size] = self._encode_big5(txt, size)
                else:
                    struct.pack_into(fmt, data, off, int(txt))

            # 数组字段
            for key, info in self._global_vars.items():
                if not key.startswith('_arr_'):
                    continue
                txt_widget, offset, count, elem_size, seg = info
                data = self.seg1 if seg == 'seg1' else self.seg2
                if data is None:
                    continue
                text = txt_widget.get('1.0', tk.END).strip()
                vals = text.split()
                for i, vs in enumerate(vals[:count]):
                    o = offset + i * elem_size
                    v = int(vs)
                    if elem_size == 1:
                        data[o] = v & 0xFF
                    else:
                        struct.pack_into('<H', data, o, v & 0xFFFF)

            self._dirty = True
            self._status_var.set(f"槽位 {self.slot}: 全局状态已修改 (未保存)")
        except (ValueError, struct.error) as e:
            messagebox.showerror("输入错误", str(e))

    def _apply_warpc(self):
        if self.seg3 is None or self._warpc_cur_idx < 0:
            return
        idx = self._warpc_cur_idx
        try:
            for fn, (sv, fo) in self._warpc_edit_vars.items():
                v = int(sv.get())
                warpc_set(self.seg3, idx, fo, v)
            self._dirty = True
            self._refresh_warpc_list()
            self._status_var.set(f"角色 #{idx} 已修改 (未保存)")
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))

    # ================================================================
    # 保存
    # ================================================================

    def _cmd_save(self):
        if self.game_state is None:
            messagebox.showwarning("无数据", "请先加载存档")
            return
        if not messagebox.askyesno("确认保存",
                f"将覆盖 sav.{self.slot} 和 {self.slot}.sav, 是否继续?"):
            return
        try:
            sav_data = os.path.join(self.save_dir, f'sav.{self.slot}')
            sav_idx = os.path.join(self.save_dir, f'{self.slot}.sav')
            save_save_data(sav_data, self.game_state, self.seg1, self.seg2, self.seg3)
            # 保存索引文件
            self._sync_index_from_seg2()
            if self.index_meta:
                save_index_file(sav_idx, self.index_meta)
            self._dirty = False
            self._status_var.set(f"槽位 {self.slot}: 保存成功!")
            messagebox.showinfo("保存成功", f"存档已保存到 sav.{self.slot}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _sync_index_from_seg2(self):
        """从 seg2 同步索引元数据 (模拟 sub_41CE10 的行为)."""
        if self.seg2 is None:
            return
        if self.index_meta is None:
            self.index_meta = {
                'team_ids': [0xFF]*6,
                'gold': 0,
                'timestamp': int(time.time()),
                'team_levels': [0]*6,
                'scene_id': -1,
            }
        # 队伍ID (低字节截断, 与游戏行为一致: 41CE10.c L103)
        for i in range(6):
            tid = struct.unpack_from('<h', self.seg2, 0x0C + i*2)[0]
            self.index_meta['team_ids'][i] = tid & 0xFF if tid >= 0 else 0xFF
        # 金钱 (word_756882 = seg2 offset 0x02)
        # 从 41CE10.c:111: sub_41DAC4(v21, &word_756882, 2) → 写入索引文件偏移6
        # SEG2_CORE_FIELDS 中: ("gold", 0x02, 2, "金钱", "H", "word_756882...")
        self.index_meta['gold'] = struct.unpack_from('<H', self.seg2, 0x02)[0]
        # 时间戳 (当前时间)
        self.index_meta['timestamp'] = int(time.time())
        # 等级 (从WarPC读取: word_757F0C[527*id] = WarPC[id].level, byte offset 4)
        if self.seg3 is not None:
            for i in range(6):
                tid = struct.unpack_from('<h', self.seg2, 0x0C + i*2)[0]
                if tid >= 0 and tid < self.warpc_count:
                    lv = warpc_get(self.seg3, tid, 4)
                    self.index_meta['team_levels'][i] = lv & 0xFFFF
                else:
                    self.index_meta['team_levels'][i] = 0
        # 场景ID
        if self.seg1 is not None:
            self.index_meta['scene_id'] = struct.unpack_from('<i', self.seg1, 0x40)[0]

    # ================================================================
    # 辅助方法
    # ================================================================

    def _get_char_name(self, char_idx):
        """获取角色名称."""
        if self.seg3 is None or char_idx < 0 or char_idx >= self.warpc_count:
            return f"#{char_idx}"
        name_id = warpc_get(self.seg3, char_idx, 0)
        if name_id and name_id in self.tkt:
            return self.tkt[name_id]
        return f"#{char_idx}"

    def _bind_mousewheel(self, canvas):
        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _bind_tooltip(self, widget, text):
        """鼠标悬浮显示提示文本."""
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=420, padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None
        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _decode_big5(self, raw):
        """Big5字节串解码为文本（用于显示）."""
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
        """文本转为Big5字节串（简→繁转换后编码，用于保存）."""
        text = text.strip()
        if not text:
            return b'\x00' * size
        import zhconv
        text = zhconv.convert(text, 'zh-hant')
        try:
            b = text.encode('big5')
        except UnicodeEncodeError:
            b = text.encode('big5', errors='replace')
        max_len = size - 1
        b = b[:max_len]
        return b.ljust(size, b'\x00')[:size]

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
