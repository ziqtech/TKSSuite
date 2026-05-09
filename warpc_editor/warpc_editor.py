#!/usr/bin/env python3
"""
WarPC.dat 可视化编辑器 v1.0
=============================================================
逆向依据:
  - sub_45343C:     DAT 文件统一加载 (LZSS 解压, 1054字节/角色, 143角色)
  - sub_452B14:     LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_42234C:     装备/技能/属性应用 (字段 [5]-[10]/[11]-[26]/[32]-[42]/[67]-[72]/[86]-[87])
  - sub_41E40C:     物品使用效果 (字段 [11]-[26] 属性加成)
  - sub_422768:     角色初始化
  - sub_422BBC:     被动技能效果计算 (字段 [41]/[42]/[86]/[87])
  - sub_4173F8:     装备 ID→索引匹配 (字段 [69]-[72]←[73]-[76])
  - Maker.exe sub_4027FF: 校验解压后大小 150722 = 1054 × 143

WarPC.dat 格式 (每条 1054 字节, 共 143 角色):
  527 × int16 (小端序)

字段布局 (仅列出反编译已验证的字段; 未验证字段标注 "未验证"):
  [0]   name_id      — 角色名称 TKT ID
  [1]   portrait     — 头像索引 (×2=Fa.JVG大幅图, ×2+1=缩略图)
  [2]   level        — 等级
  [3]   role         — 身份 (0=敌方 -1=我方)
  [4]   exp_to_next  — 升级所需经验 (大多数=100; 敌方版较高: 呂布5092 張角7292)

  [5]   cur_hp       — 当前生命 (cap at hp_max)
  [6]   cur_mp       — 当前内力 (cap at mp_max)
  [7]   hp_base      — 生命基础值
  [8]   hp_max       — 生命上限 (基础+装备)
  [9]   mp_base      — 内力基础值
  [10]  mp_max       — 内力上限 (基础+装备)

  8 通用属性 (基础/当前) — sub_42234C + sub_41E40C 验证:
  [11]  atk_base     — 攻击(基础)    [12]  atk_cur  — 攻击(当前)
  [13]  def_base     — 防御(基础)    [14]  def_cur  — 防御(当前)
  [15]  hit_base     — 命中(基础)    [16]  hit_cur  — 命中(当前)
  [17]  eva_base     — 闪避(基础)    [18]  eva_cur  — 闪避(当前)
  [19]  spd_base     — 速度(基础)    [20]  spd_cur  — 速度(当前)
  [21]  luk_base     — 幸运(基础)    [22]  luk_cur  — 幸运(当前)
  [23]  mov_base     — 移动(基础)    [24]  mov_cur  — 移动(当前)  ※TKItem[18]=vit
  [25]  wis_base     — 悟性(基础)    [26]  wis_cur  — 悟性(当前)  ※TKItem[17]=spi

  [31]  field_31     — 等级强相关 (r=0.992), 疑似技能点数/累计经验

  [268] jp_reward    — 战后JP点 (直接值, 无等级缩放; 盜賊嘍嘍=2 西羌王=100)
  [269] gold_reward  — 战后金钱基数 (实际获得 = 基数 × 2; 盜賊=20→40 小混混=25→50)

  [32]-[42] runtime  — 运行时状态 (sub_42234C 初始化, 非角色固有属性, 语义未验证)

  [51]-[66] status_resist — 状态抵抗 (32状态×1byte; sub_42234C 初始化为 0)
  [88]-[259] skill_learn — 技能学习状态 (344技能×1byte; Maker Frm_WarPC: 不会/等待学/可以学/独立技学会/父技学会/支技能学会)

  [67]  cause_mask1  — 导致状态掩码1 (1-16; 来自装备 v9[26])
  [68]  cause_mask2  — 导致状态掩码2 (17-32; 来自装备 v9[27])

  [69]-[72] equip_idx —运行时装备索引缓存 (sub_4173F8 从 [73-76] 计算)
  [73]-[76] equip_id  — 装备物品 ID (DAT 原始; 查 TKItem.field[0])

  [82]-[87] equip_skill — 装备技能区 (6字段; Maker Frm_WarPC 暴露; sub_42234C/sub_422BBC 应用)
                         [82]=装备技能0 [83]=装备技能1 [84]=装备技能2 [85]=装备技能3
                         [86]=被动技能1 [87]=被动技能2
                         验证: 周倉 [82]=43武術 [83]=83輔助 [84]=273二連擊 [85]=279無隙1 [86]=303近戰反擊1 [87]=334飄浮

用法:
  python warpc_editor.py
"""

import struct, os, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# LZSS 编解码 (sub_452B14)
# ============================================================

def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]
    bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data): break
            flags = data[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(data): break
            b = data[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data): break
            b1, b2 = data[pos], data[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

def lzss_compress(data):
    src = data; sl = len(src)
    flat = bytes(bytearray([0x20] * 4096) + src)
    tokens = []; pos = 0
    while pos < sl:
        curr = 4096 + pos; ms = min(18, sl - pos); bl, bo = 0, 0
        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat[curr:curr + length]
                end = curr + length - 1
                start = max(0, curr - 4096)
                idx = flat.rfind(pat, start, end)
                if idx != -1: bl = length; bo = (idx - 18) & 0xFFF; break
        if bl >= 3:
            tokens.append((False, bo, bl)); pos += bl
        else:
            tokens.append((True, src[pos], 0)); pos += 1
    stream = bytearray(); ti = 0
    while ti < len(tokens):
        fb = 0; be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]: fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]:
                stream.append(tokens[i][1])
            else:
                off, length = tokens[i][1], tokens[i][2]; el = length - 3
                stream.append(off & 0xFF)
                stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    ds = sl; bd = struct.pack('<I', ds) + bytes(stream)
    return struct.pack('<II', ds, len(bd)) + bd

# ============================================================
# TKT 文本加载
# ============================================================

def load_tkt(tkt_path):
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path, 'rb') as f: raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]; cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]; dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt * 4, cnt * 4; lookup = {}
    SKIP = set(range(0, 10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        if eid in SKIP: continue
        off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0: end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try: s = txt.decode('big5', errors='replace')
            except: s = txt.decode('gbk', errors='replace')
            if s and s != '0': lookup[eid] = s
    return lookup

def load_jvg_sprites(jvg_path):
    """加载 Fa.JVG 并返回 PIL Image 列表 (PIL 不可用时返回 None)"""
    try:
        from PIL import Image
    except ImportError:
        return None
    if not jvg_path or not os.path.exists(jvg_path): return None
    with open(jvg_path, 'rb') as f: data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG': return None
    bc = struct.unpack_from('<I', data, 8)[0]
    off = 32; sprites = []
    for bi in range(bc):
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
            if w <= 0 or h <= 0:
                sprites.append(None)
                continue
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

# ============================================================
# 常量
# ============================================================

WARPC_REC = 1054      # 527 × int16
WARPC_CNT = 143
WARPC_FIELD_COUNT = 527
WARPC_DECOMPRESSED = 150722

FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 8

# 状态效果名称 (共31种, 索引0-30; sub_41E40C 使用 status_id 1-32)
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
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

# ============================================================
# 字段定义 — 按功能分组, 基于反编译验证
# ============================================================

# 统计名称 (8 通用属性, sub_42234C + sub_41E40C 验证)
# TKItem[11-18] → WarPC[11-26]: 攻击/防御/命中/闪避/速度/幸运/悟性/移动
STAT_NAMES = ["攻击", "防御", "命中", "闪避", "速度", "幸运", "移动", "悟性"]
STAT_SHORTS = ["atk", "def", "hit", "eva", "spd", "luk", "mov", "wis"]

# 核心字段 — 已验证 (格式: key, offset, label, comment)
IDENTITY_FIELDS = [
    ("name_id",    0,  "名称TKT ID",  "角色名称 → TKT.dat (sub_4067E8)"),
    ("portrait",   2,  "头像索引",    "头像索引 ×2 = Fa.JVG 大幅图, ×2+1 = 缩略图"),
    ("level",      4,  "等级",        "角色等级 (数值显示)"),
    ("role",       6,  "身份",        "0=敌方 -1=我方"),
    ("exp_to_next", 8,  "升级所需经验","升至下一级所需经验; 绝大多数角色=100, 敌方版较高(呂布5092 張角7292)"),
]

HPMP_FIELDS = [
    ("cur_hp",    10,  "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",    12,  "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base",   14,  "HP基础",      "HP基础值"),
    ("hp_max",    16,  "HP上限",      "HP上限 (基础+装备; sub_42234C)"),
    ("mp_base",   18,  "MP基础",      "MP基础值"),
    ("mp_max",    20,  "MP上限",      "MP上限 (基础+装备; sub_42234C)"),
]

# 8 属性对 (基础/当前) — sub_42234C L24-31/63-70 验证
STAT_FIELDS = []
STAT_BASE_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]  # byte offsets for [11,13,15,17,19,21,23,25]
for i, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_BASE_OFFSETS)):
    STAT_FIELDS.append((f"{short}_base", bo, f"{name}(基础)",
                        f"{name}基础值 (sub_42234C: a2[{11+i*2}] initial)"))
    STAT_FIELDS.append((f"{short}_cur", bo + 2, f"{name}(当前)",
                        f"{name}当前值 (基础+装备; sub_42234C L63-70 a2[{12+i*2}]+=v9[{11+i}])"))

# 技能加成区 [32]-[40] — sub_422BBC 应用 TKSkill 效果, sub_42234C 初始化
SKILL_BONUS_FIELDS = [
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

# 角色五维 [27]-[31] — 曹操验证: 智慧5 仁德-1 勇气10 医术0 技能点数400
CHAR_ATTR_FIELDS = [
    ("wisdom",      54,  "智慧",        "智慧值 (曹操=5 司马懿=20)"),
    ("benevolence", 56,  "仁德",        "仁德值 (曹操=-1 司马懿=-5)"),
    ("courage",     58,  "勇气",        "勇气值 (曹操=10 司马懿=0)"),
    ("medicine",    60,  "医术",        "医术值 (曹操=0 司马懿=10; sub_40E11C case4→word_75688A capped 100)"),
    ("jp_total",    62,  "技能点数",    "累计技能点数 (曹操=400 司马懿=300; r=0.992与等级相关; sub_422A5C入队累加)"),
]

# 身上状态槽 [43]-[50] — sub_41E40C 验证: 8个状态效果槽, 每槽(status_id:byte, duration:byte)
STATUS_SLOT_FIELDS = []
for i in range(8):
    STATUS_SLOT_FIELDS.append(
        (f"status_slot{i}", 86 + i*2, f"状态槽{i}",
         f"身上状态效果槽{i} (sub_41E40C: v8+{i*2}); 低字节=状态ID(1-32) 高字节=持续回合"))

# 反应组 [41]-[42] — 运行时字段, sub_422BBC type=2 写入, sub_42234C 初始化为0
# [41] 反应组编号 (1-10), 由被动技能索引区间判定:
#   303-305=近戰反擊 306-308=遠程反擊 309-311=法術反彈 312-314=先發制人
#   315-317=時序回饋 318-320=損傷賠償 321-323=環境探索 324-326=國色天香
#   327-329=有福同享 330+=國士無雙
# [42] 触发概率 = TKSkill[44] (技能编辑器 offset 88)
# 反应组语义: 被动技能的触发行为分类, 当角色被攻击时游戏据此决定触发哪种被动反应.
#   值为派生数据 — sub_42234C 初始化为0, sub_422BBC 根据角色装备的被动技能自动计算,
#   不是角色固有属性. 反编译中仅 sub_422BBC 写入, 读取端在未导出的战斗函数中.
REACTION_FIELDS = [
    ("reaction_group",  82,  "反应组",   "被动技能反应组编号 1-10 (sub_422BBC type=2; 初始化=0)"),
    ("reaction_trigger",84,  "触发概率", "被动技能触发概率 %%, 来自 TKSkill[44] (sub_422BBC: a2[42]=v6[44])"),
]

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

EQUIP_FIELDS = [
    ("equip_idx0", 138, "装备索引0",   "运行时装备索引缓存 (sub_4173F8 计算)"),
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
    ("equip_skill0", 164, "装备技能0", "装备技能槽0 → TKSkill (sub_42234C v4 loop)"),
    ("equip_skill1", 166, "装备技能1", "装备技能槽1 → TKSkill"),
    ("equip_skill2", 168, "装备技能2", "装备技能槽2 → TKSkill (sub_42234C: a2[84])"),
    ("equip_skill3", 170, "装备技能3", "装备技能槽3 → TKSkill (sub_42234C: a2[85])"),
    ("passive1",     172, "被动技能1", "被动技能1 → TKSkill (sub_422BBC)"),
    ("passive2",     174, "被动技能2", "被动技能2 → TKSkill (sub_422BBC)"),
]

STATUS_FIELDS = [
    ("cause_mask1", 134, "攻击导致状态 1-16",  "攻击/命中时让目标进入的状态位掩码 (bit0-15; 来自装备 v9[26])"),
    ("cause_mask2", 136, "攻击导致状态 17-32", "攻击/命中时让目标进入的状态位掩码 (bit16-31; 来自装备 v9[27])"),
]

# 战后奖励 — 实测验证: 盜賊嘍嘍 field[268]=2→JP=2, field[269]=20→Lv3 Gold=40
BATTLE_REWARD_FIELDS = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点数 (直接值, 无等级缩放); 盜賊嘍嘍=2 西羌王=100"),
    ("gold_reward", 538, "战后金钱基数","击败后获得金钱基数; 实际获得=基数×2; 盜賊嘍嘍=20→40 小混混=25→50"),
]

# 成长率 [264]-[266] — 五爪金龍验证: 初期27 中期24 后期21
# 等级 >= 21 中期，等级 >= 41 后期
GROWTH_FIELDS = [
    ("growth_early", 528, "成长率初期", "成长率初期; 五爪金龍=27 西羌王=27 呂布=20"),
    ("growth_mid",   530, "成长率中期", "成长率中期; 五爪金龍=24 西羌王=24 呂布=25"),
    ("growth_late",  532, "成长率后期", "成长率后期; 五爪金龍=21 西羌王=21 呂布=25"),
]

# 可掉落物品 [270]-[272] — 五爪金龍验证: 顛海神珠(537) 金龍魂(234) 虎項龍紋鎧(8081)
DROP_ITEM_FIELDS = [
    ("drop_item0", 540, "必掉落物品",  "可掉落物品0 ID; 五爪金龍=顛海神珠(537)"),
    ("drop_item1", 542, "高概率掉落",  "可掉落物品1 ID; 五爪金龍=金龍魂(234)"),
    ("drop_item2", 544, "低概率掉落",  "可掉落物品2 ID; 五爪金龍=虎項龍紋鎧(8081)"),
]

# 角色使用/装备权限 [77]-[81] — 来自物品编辑器 USE_RIGHT_OPTIONS 验证
# sub_41928C: word_77CBD4[32*idx] & word_757FA4[527*char] → 装备/使用时按位与校验
# 主角#0 验证: [77]=? [78]=7(战斗|非战斗|主角限定) [79]=63(刀|剑|枪|矛|弓|大刀) [80]=3(衣袍|铠甲) [81]=?
CHAR_USE_RIGHT_FIELDS = [
    ("use_right_medicine",  154, "药品权限",   "药品使用权限位掩码 (待验证); 全143条原始值=0"),
    ("use_right_item",      156, "道具权限",   "药品/道具使用权限位掩码 (1=战斗 2=非战斗 4=主角限定); 主角#0=7"),
    ("use_right_weapon",    158, "武器权限",   "武器装备权限位掩码 (1=刀 2=剑 4=枪 8=矛 16=弓 32=大刀 64=戟 128=锤); 主角#0=63"),
    ("use_right_armor",     160, "防具权限",   "防具装备权限位掩码 (1=衣袍 2=铠甲); 主角#0=3"),
    ("use_right_accessory", 162, "饰品权限",   "饰品装备权限位掩码 (待验证); 全143条原始值=0"),
]

# 权限字段 → (弹窗标题, [(bit, 名称, 描述), ...])
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

# 状态抵抗 — 32状态×1byte抵抗力, 存储在[51]-[66]的高低字节中
# UI 由 _build_status_resist 构建, 数据通过 _status_resist_widgets 读写

# 技能学习状态 [88]-[259] — 344个技能×1byte, 存储在172个int16的高低字节中
# Maker Frm_WarPC 暴露: 从"兵  法"到"回氣  ３"(TKSkill #0-#343), 每技能6种状态选择
# UI 由 _build_skill_learn 构建, 数据通过 _skill_learn_widgets 读写
SKILL_LEARN_COUNT = 344  # TKSkill #0-#343
SKILL_LEARN_STATES = [
    "0-不会",
    "1-等待学",
    "10-可以学",
    "20-独立技学会",
    "20-父技学会",
    "30-支技能学会",
]

# 尾部未分析区域
TAIL_START = 260  # int16 offset (技能学习状态结束于 [259])
TAIL_END = 527
UNVERIFIED_RANGES = []  # 全部未验证范围已查明

# ============================================================
# 数据加载/保存
# ============================================================

def load_warpc(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    if len(dec) != WARPC_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 {WARPC_DECOMPRESSED} (Maker.exe sub_4027FF)")
    recs = []
    for i in range(WARPC_CNT):
        off = i * WARPC_REC
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        recs.append({'index': i, 'fields': list(vals)})
    return recs

def save_warpc(fp, recs):
    buf = bytearray(WARPC_CNT * WARPC_REC)
    for rec in recs[:WARPC_CNT]:
        i = rec['index']; off = i * WARPC_REC
        struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, buf, off, *rec['fields'])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

def get_field(rec, byte_off):
    return rec['fields'][byte_off // 2]

def set_field(rec, byte_off, val):
    rec['fields'][byte_off // 2] = val

# ============================================================
# GUI
# ============================================================

class WarpcEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("WarPC.dat 可视化编辑器 v1.0")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.root.iconbitmap(default=ico)
        self.root.geometry("1500x820"); self.root.minsize(1050, 650)
        self.warpc_path = self.tkt_path = None
        self.records = []; self.tkt = {}; self.skill_names = {}; self._skill_types = {}; self.item_names = {}; self.item_idx_names = {}; self._idx_to_id = {}; self._id_to_idx = {}
        self.filtered_indices = []; self._dirty = False
        self._edit_vars = {}; self._edit_extras = {}; self._tab_grids = {}
        self._fa_sprites = []; self._fa_photos = {}; self._tree_photos = []
        self._build_ui(); self._set_edit_enabled(False)
        sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        x = (sw - 1500) // 2; y = (sh - 820) // 2
        self.root.geometry(f'1500x820+{x}+{y}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator(); fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=22); e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned); paned.add(lf, weight=1)
        cols = ('index', 'name', 'level', 'role', 'hp', 'mp')
        self.tree = ttk.Treeview(lf, columns=cols, show='tree headings', selectmode='browse')
        self.tree.column('#0', width=28, minwidth=28, stretch=False, anchor='center')
        self.tree.heading('#0', text='')
        self.tree.tag_configure('ally', foreground='#2266CC')
        self.tree.tag_configure('enemy', foreground='#CC3333')
        cc = [
            ('index', '#', 40), ('name', '角色名称', 130), ('level', '等级', 45),
            ('role', '身份', 50), ('hp', 'HP', 70), ('mp', 'MP', 70),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # Right: Edit panel with Notebook tabs
        rf = ttk.Frame(paned); paned.add(rf, weight=3)
        self.edit_frame = rf

        hdr = ttk.Frame(rf); hdr.pack(fill=tk.X, pady=(0, 4), padx=4)
        self.lbl_rec_idx = ttk.Label(hdr, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(side=tk.LEFT)
        self.lbl_avatar = ttk.Label(hdr, text="")
        self.lbl_avatar.pack(side=tk.RIGHT, padx=(8, 0))

        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: 核心属性
        tab1 = ttk.Frame(self.notebook); self.notebook.add(tab1, text="核心属性")
        t1_canvas = tk.Canvas(tab1, highlightthickness=0)
        t1_sb = ttk.Scrollbar(tab1, orient=tk.VERTICAL, command=t1_canvas.yview)
        t1_canvas.configure(yscrollcommand=t1_sb.set)
        self.t1_inner = ttk.Frame(t1_canvas)
        t1_canvas.create_window((0, 0), window=self.t1_inner, anchor='nw')
        t1_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t1_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1_inner.bind('<Configure>', lambda e: t1_canvas.configure(scrollregion=t1_canvas.bbox('all')))
        self._bind_mousewheel(t1_canvas)

        # Tab 2: 装备与技能
        tab2 = ttk.Frame(self.notebook); self.notebook.add(tab2, text="装备与技能")
        t2_canvas = tk.Canvas(tab2, highlightthickness=0)
        t2_sb = ttk.Scrollbar(tab2, orient=tk.VERTICAL, command=t2_canvas.yview)
        t2_canvas.configure(yscrollcommand=t2_sb.set)
        self.t2_inner = ttk.Frame(t2_canvas)
        t2_canvas.create_window((0, 0), window=self.t2_inner, anchor='nw')
        t2_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t2_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2_inner.bind('<Configure>', lambda e: t2_canvas.configure(scrollregion=t2_canvas.bbox('all')))
        self._bind_mousewheel(t2_canvas)

        # Tab 3: 全部字段 (raw grid)
        tab3 = ttk.Frame(self.notebook); self.notebook.add(tab3, text="全部字段")
        t3_canvas = tk.Canvas(tab3, highlightthickness=0)
        t3_sb = ttk.Scrollbar(tab3, orient=tk.VERTICAL, command=t3_canvas.yview)
        t3_canvas.configure(yscrollcommand=t3_sb.set)
        self.t3_inner = ttk.Frame(t3_canvas)
        t3_canvas.create_window((0, 0), window=self.t3_inner, anchor='nw')
        t3_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t3_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3_inner.bind('<Configure>', lambda e: t3_canvas.configure(scrollregion=t3_canvas.bbox('all')))
        self._bind_mousewheel(t3_canvas)

        # Bottom buttons
        bf = ttk.Frame(rf); bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit, width=12).pack(side=tk.LEFT, padx=2)

        # Build tab contents
        self._build_tab1(self.t1_inner)
        self._build_tab2(self.t2_inner)
        self._build_tab3(self.t3_inner)

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_warpc = ttk.Label(pf, text="", foreground="gray")
        self.lbl_warpc.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_item = ttk.Label(pf, text="", foreground="gray")
        self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray")
        self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_fa = ttk.Label(pf, text="", foreground="gray")
        self.lbl_fa.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_tab1(self, parent):
        """核心属性 — 基本信息 + HP/MP + 8属性 + 战斗能力 + 状态掩码"""
        self._build_section(parent, "基本信息", IDENTITY_FIELDS, 0)
        self._build_section(parent, "HP / MP", HPMP_FIELDS, 1)
        # 八属性 — 一行八列紧凑布局
        self._build_stat_row(parent)
        self._build_section(parent, "技能加成 [32]-[40] (sub_422BBC TKSkill效果; sub_42234C初始=0)", SKILL_BONUS_FIELDS, 3)
        self._build_section(parent, "反应组 [41]-[42] (运行时字段; sub_422BBC type=2 写入, sub_42234C 初始化为0)", REACTION_FIELDS, 4)
        self._build_section(parent, "攻击导致状态 (来源于装备; sub_42234C L94-95)", STATUS_FIELDS, 5, ft='mask')
        self._build_status_slots(parent, 6)
        self._build_section(parent, "角色五维 [27]-[31] (曹操验证: 智慧5 仁德-1 勇气10 医术0 技能点400)", CHAR_ATTR_FIELDS, 7)
        self._build_section(parent, "使用/装备权限 [77]-[81] (sub_41928C 验证: 主角#0 [77]=? [78]=7 [79]=63 [80]=3 [81]=?)", CHAR_USE_RIGHT_FIELDS, 8)
        # 战后奖励 [268]-[269]
        self._build_section(parent, "成长率 [264]-[266] (五爪金龍: 初期27 中期24 后期21)", GROWTH_FIELDS, 9)
        self._build_section(parent, "战后奖励 [268]-[269] (Gold=基数×2; JP=直接值)", BATTLE_REWARD_FIELDS, 10)
        self._build_section(parent, "可掉落物品 [270]-[272] (五爪金龍验证: 顛海神珠/金龍魂/虎項龍紋鎧)", DROP_ITEM_FIELDS, 11, ft='item_pick')

    def _build_stat_row(self, parent):
        """八属性 — 一行八列, 每列(名称 + 基础 + 当前)"""
        lf = ttk.LabelFrame(parent, text="八属性 (基础/当前 = 基础+装备加成)", padding=4)
        lf.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        for c in range(8):
            lf.columnconfigure(c, weight=1, minsize=90)

        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_BASE_OFFSETS)):
            col = ttk.Frame(lf); col.grid(row=0, column=ci, sticky='n', padx=3, pady=2)

            # 属性名
            lbl = ttk.Label(col, text=name, font=('', 9, 'bold'))
            lbl.pack(anchor=tk.CENTER)

            # 基础值
            fn_base = f"{short}_base"
            frm_b = ttk.Frame(col); frm_b.pack(fill=tk.X, pady=(2, 0))
            ttk.Label(frm_b, text="基础", font=FONT_S, foreground='#888').pack(side=tk.LEFT)
            ev_b = tk.StringVar(); self._edit_vars[fn_base] = ev_b
            ttk.Entry(frm_b, textvariable=ev_b, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_b, f"[{bo//2}] {name}基础值 (sub_42234C: a2[{11+ci*2}] initial)")

            # 当前值
            fn_cur = f"{short}_cur"
            frm_c = ttk.Frame(col); frm_c.pack(fill=tk.X)
            ttk.Label(frm_c, text="当前", font=FONT_S, foreground='#228B22').pack(side=tk.LEFT)
            ev_c = tk.StringVar(); self._edit_vars[fn_cur] = ev_c
            ttk.Entry(frm_c, textvariable=ev_c, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_c, f"[{bo//2+1}] {name}当前值 (基础+装备; sub_42234C L63-70)")

    def _build_status_slots(self, parent, row):
        """身上状态 [43]-[50] — 8槽, 每槽(status_id, duration)"""
        lf = ttk.LabelFrame(parent, text="身上状态 [43]-[50] (sub_41E40C 验证: 8槽×2字节=状态ID+持续回合)", padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        self._status_widgets = []
        status_options = ["(无)"] + [f"{i+1}-{STATUS_NAMES[i]}" for i in range(len(STATUS_NAMES))]
        for si, (fn, fo, fl, cmt) in enumerate(STATUS_SLOT_FIELDS):
            r, c = divmod(si, 4)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            # Title row: 槽N状态 | 回合
            ttl = ttk.Frame(col); ttl.pack(fill=tk.X)
            lbl = ttk.Label(ttl, text=f"状态{si}", font=FONT)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{fo//2}] bo={fo}: {cmt}")
            ttk.Label(ttl, text="持续回合", font=FONT, foreground='#888').pack(side=tk.RIGHT)
            # Input row: Combobox | Entry
            inp = ttk.Frame(col); inp.pack(fill=tk.X, pady=(1, 0))
            cb = ttk.Combobox(inp, values=status_options, state='readonly', width=6, font=FONT)
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ev_dur = tk.StringVar(value="0")
            ttk.Entry(inp, textvariable=ev_dur, width=4, font=FONT, justify='center').pack(side=tk.RIGHT, padx=(1, 0))
            # Store widgets
            self._status_widgets.append((fn, fo, cb, ev_dur))
            self._edit_vars[fn] = tk.StringVar()  # hidden int16 value

    def _get_fa_photo(self, sprite_idx, size=(24,24)):
        """从 Fa.JVG 精灵集中获取 PhotoImage (缓存)"""
        if not self._fa_sprites: return None
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites): return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None: return None
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

    def _build_status_resist(self, parent, row):
        """状态抵抗 — 32状态×1byte, 存储在[51]-[66]的每个字节中"""
        lf = ttk.LabelFrame(parent, text="状态抵抗 [51]-[66] (32状态×1byte抵抗力; sub_42234C初始化为0)", padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        for c in range(8):
            lf.columnconfigure(c, weight=1, minsize=100)
        self._status_resist_widgets = []
        for i in range(32):
            r, c = divmod(i, 8)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            sname = STATUS_NAMES[i] if i < len(STATUS_NAMES) else f"状态{i+1}"
            field_idx = 51 + i // 2
            byte_pos = "高" if i % 2 else "低"
            # Input row: label (status name) | entry
            inp = ttk.Frame(col); inp.pack(fill=tk.X)
            lbl = ttk.Label(inp, text=sname, font=FONT, width=6)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{field_idx}] {byte_pos}字节: {sname}抵抗力")
            ev = tk.StringVar(value="0")
            ttk.Entry(inp, textvariable=ev, width=5, font=FONT, justify='center').pack(side=tk.RIGHT, padx=(1, 0))
            self._status_resist_widgets.append((i, ev))

    def _build_skill_learn(self, parent, row):
        """技能学习状态 — 344技能×1byte, 存储在[88]-[259]的每个字节中"""
        lf = ttk.LabelFrame(parent, text="技能学习状态 [88]-[259] (344技能×1byte; Maker Frm_WarPC: 不会/等待学/可以学/独立技学会/父技学会/支技能学会)", padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        for c in range(4):
            lf.columnconfigure(c, weight=1, minsize=180)
        self._skill_learn_widgets = []; self._skill_learn_labels = []
        for i in range(SKILL_LEARN_COUNT):
            r, c = divmod(i, 4)
            col = ttk.Frame(lf); col.grid(row=r, column=c, sticky='n', padx=2, pady=1)
            sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
            field_idx = 88 + i // 2; byte_pos = "高" if i % 2 else "低"
            # Input row: label (skill name) | combobox
            inp = ttk.Frame(col); inp.pack(fill=tk.X)
            lbl = ttk.Label(inp, text=sname, font=FONT, width=10)
            lbl.pack(side=tk.LEFT)
            self._bind_tooltip(lbl, f"[{field_idx}] {byte_pos}字节: {sname}学习状态")
            cb = ttk.Combobox(inp, values=SKILL_LEARN_STATES, state='readonly',
                              width=10, font=FONT)
            cb.pack(side=tk.RIGHT, padx=(1, 0))
            self._skill_learn_widgets.append((i, cb))
            self._skill_learn_labels.append(lbl)

    def _build_tab2(self, parent):
        """装备与技能"""
        self._build_section(parent, "装备索引 [69]-[72] (TKItem数组下标; 运行时缓存)", EQUIP_FIELDS[:4], 0, ft='item_pick')
        self._build_section(parent, "装备物品 ID [73]-[76] (DAT原始; 查 TKItem.field[0])", EQUIP_FIELDS[4:], 1, ft='item_pick')
        self._build_section(parent, "装备技能 [82]-[87] (6字段; sub_42234C/sub_422BBC; Maker验证: 周倉)", EQUIP_SKILL_FIELDS, 2, ft='skill_pick')
        self._build_status_resist(parent, 3)
        self._build_skill_learn(parent, 4)

    def _build_tab3(self, parent):
        """全部 527 字段的紧凑网格"""
        self._tab3_labels = []
        self._tab3_entries = []
        COLS = 8
        # Show all fields 0-526 in groups of 100
        for base in range(0, 527, 100):
            end = min(base + 100, 527)
            lf = ttk.LabelFrame(parent, text=f"字段 [{base}] — [{end-1}] (int16 偏移)", padding=4)
            lf.pack(fill=tk.X, padx=2, pady=2)
            grid = ttk.Frame(lf); grid.pack(fill=tk.X)
            for j in range(base, end):
                r, c = divmod(j - base, COLS)
                bo = j * 2
                fn = f"raw_{j}"
                frm = ttk.Frame(grid); frm.grid(row=r, column=c, sticky='w', padx=1, pady=1)
                lbl = ttk.Label(frm, text=f"[{j}]", font=('Consolas', 7), foreground='#888')
                lbl.pack(anchor=tk.W)
                ev = tk.StringVar(); self._edit_vars[fn] = ev
                ent = ttk.Entry(frm, textvariable=ev, width=6, font=('Consolas', 7))
                ent.pack(fill=tk.X)
                self._tab3_entries.append((j, fn, lbl))
            # configure grid columns
            for c in range(COLS):
                grid.columnconfigure(c, weight=1, minsize=90)

    def _build_section(self, parent, title, fields, row, cols=8, ft='int'):
        lf = ttk.LabelFrame(parent, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            if fn in FLAG_DEFS:
                field_ft = 'flags'
            elif fn in USE_RIGHT_DEFS:
                field_ft = 'use_right'
            elif fn.startswith('cause_mask'):
                field_ft = 'mask'
            else:
                field_ft = ft
            self._build_field_widget(grid, fi // cols, fi % cols, fn, fo, fl, W_INPUT, cmt, field_ft)

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

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10; y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget); w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=420, padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']: tip['win'].destroy(); tip['win'] = None
        widget.bind('<Enter>', _enter); widget.bind('<Leave>', _leave)

    def _bind_mousewheel(self, canvas):
        def _mw(e): canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        wp = os.path.join(d, "WarPC.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(wp):
            messagebox.showwarning("文件缺失", "未找到 WarPC.dat"); return
        self.warpc_path = wp
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _load_skill_names(self):
        """加载 TKSkill.dat → {skill_index: name} 查找表 + 类型表"""
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        sk_path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path):
            return {}, {}
        try:
            with open(sk_path, 'rb') as f:
                dec = lzss_decompress(f.read())
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

    def _load_item_names(self):
        """加载 TKItem.dat → {item_id: item_name} + {item_index: item_name}"""
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        it_path = os.path.join(tks_dir, 'TKItem.dat')
        if not os.path.exists(it_path):
            return {}, {}
        try:
            with open(it_path, 'rb') as f:
                dec = lzss_decompress(f.read())
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

    def _reload(self):
        if not self.warpc_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
        tks_dir = os.path.dirname(self.warpc_path)
        fa_path = os.path.join(tks_dir, 'Fa.JVG')
        self._fa_sprites = load_jvg_sprites(fa_path) or []
        self._fa_photos.clear()
        try:
            self.records = load_warpc(self.warpc_path); self._dirty = False
            self.skill_names, self._skill_types = self._load_skill_names()
            if hasattr(self, '_skill_learn_labels'):
                for i, lbl in enumerate(self._skill_learn_labels):
                    if i < len(self._skill_learn_labels):
                        sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
                        lbl.config(text=sname)
            self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()
            nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
            self.status_var.set(
                f"{len(self.records)} 角色 (1054字节/角色) | 有效 {nonempty} | TKT {len(self.tkt)} 条 | 物品 {len(self.item_names)} 技能 {len(self.skill_names)}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children():
            if isinstance(c, ttk.Frame):
                self._set_ws(c, en)

    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p, label=''):
            if not p: lb.config(text=f"({label}未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=f"{label}: {p}" if label else p, foreground=g)
        _f(self.lbl_warpc, self.warpc_path, 'WarPC')
        _f(self.lbl_tkt, self.tkt_path, 'TKT')
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        it_path = os.path.join(tks_dir, 'TKItem.dat') if tks_dir else ''
        sk_path = os.path.join(tks_dir, 'TKSkill.dat') if tks_dir else ''
        _f(self.lbl_item, it_path if os.path.exists(it_path) else None, 'TKItem')
        _f(self.lbl_skill, sk_path if os.path.exists(sk_path) else None, 'TKSkill')
        fa_path = os.path.join(tks_dir, 'Fa.JVG') if tks_dir else ''
        _f(self.lbl_fa, fa_path if os.path.exists(fa_path) else None, 'Fa.JVG')

    # ----------- 筛选/列表 -----------

    def _char_name(self, rec):
        nid = rec['fields'][0]
        if nid > 0 and nid in self.tkt:
            return self.tkt[nid].split('\n')[0].strip()[:20]
        if nid < 0 and -nid in self.tkt:
            return self.tkt[-nid].split('\n')[0].strip()[:20]
        return f"#{nid}" if nid else f"(空-#{rec['index']})"

    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        for rec in self.records:
            if q:
                nm = self._char_name(rec)
                search_text = f"{rec['index']} {nm} {rec['fields'][2]} {rec['fields'][3]}".lower()
                if q not in search_text:
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
        msg = f"显示 {len(self.filtered_indices)}/{WARPC_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set(""); self._apply_filter()

    def _refresh_table(self):
        self._tree_photos.clear()
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            f = r['fields']
            nm = self._char_name(r)
            hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
            mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
            role_val = f[3]; role_str = '我方' if role_val == -1 else ('敌方' if role_val == 0 else str(role_val))
            tag = 'ally' if role_val == -1 else ('enemy' if role_val == 0 else '')
            portrait = f[1]; thumb_idx = portrait * 2 + 1 if portrait >= 0 else 0
            photo = self._get_fa_photo(thumb_idx, (24, 24))
            self._tree_photos.append(photo)
            self.tree.insert('', 'end', image=photo if photo else '',
                             values=(r['index'], nm, f[2], role_str, hp_str, mp_str),
                             tags=(tag,) if tag else ())

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'name':
            self.filtered_indices.sort(key=lambda i: self._char_name(self.records[i]).lower(), reverse=rev)
        elif col in ('level', 'role'):
            self.filtered_indices.sort(key=lambda i: self.records[i]['fields'][{'level':2,'role':3}[col]], reverse=rev)
        else:
            self.filtered_indices.sort(reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ----------- 编辑 -----------

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        f = rec['fields']
        nm = self._char_name(rec)

        self.lbl_rec_idx.config(text=(
            f"角色 #{rec['index']}    {nm}    "
            f"等级={f[2]}  身份={'我方' if f[3]==-1 else ('敌方' if f[3]==0 else str(f[3]))}    "
            f"HP={f[5]}/{f[8]}  MP={f[6]}/{f[10]}"
        ))
        portrait = f[1]; large_idx = portrait * 2 if portrait >= 0 else 0
        photo = self._get_fa_photo(large_idx, (70, 70))
        if photo:
            self.lbl_avatar.configure(image=photo, text="")
            self.lbl_avatar.image = photo
        else:
            self.lbl_avatar.configure(image="", text="")

        # Populate role combobox
        role_val = f[3]
        if 'role' in self._edit_extras:
            cb = self._edit_extras['role']
            for i, item in enumerate(cb['values']):
                if item.startswith(f'{role_val}-'):
                    cb.current(i); break

        # Populate reaction_group combobox
        rg_val = f[41]
        if 'reaction_group' in self._edit_extras:
            cb = self._edit_extras['reaction_group']
            for i, item in enumerate(cb['values']):
                if item.startswith(f'{rg_val}-'):
                    cb.current(i); break

        # Populate all known fields
        all_named_fields = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS +
                           SKILL_BONUS_FIELDS + EQUIP_FIELDS + EQUIP_SKILL_FIELDS +
                           STATUS_FIELDS + STATUS_SLOT_FIELDS + CHAR_ATTR_FIELDS + CHAR_USE_RIGHT_FIELDS + REACTION_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)
        for fn, fo, _, _ in all_named_fields:
            sv = str(f[fo // 2])
            if fn in self._edit_vars:
                self._edit_vars[fn].set(sv)

        # Populate status slot widgets
        if hasattr(self, '_status_widgets'):
            for fn, fo, cb, ev_dur in self._status_widgets:
                v = f[fo // 2]
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
                field_idx = 51 + byte_idx // 2
                is_high = byte_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                byte_val = (unsigned >> (8 * is_high)) & 0xFF
                ev.set(str(byte_val))

        # Populate skill learn widgets
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                field_idx = 88 + skill_idx // 2
                is_high = skill_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                byte_val = (unsigned >> (8 * is_high)) & 0xFF
                for vi, item in enumerate(cb['values']):
                    if item.startswith(f'{byte_val}-'):
                        cb.current(vi); break

        # Resolve skill names for equip skill fields
        for fn, fo, _, _ in EQUIP_SKILL_FIELDS:
            sid = f[fo // 2]
            if fn in self._edit_extras:
                if sid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'skill_names') and sid in self.skill_names:
                    self._edit_extras[fn].config(text=self.skill_names[sid])
                else:
                    self._edit_extras[fn].config(text=f'技能#{sid}')

        # Resolve item names for equip_idx fields
        for fn, fo, _, _ in EQUIP_FIELDS[:4]:
            idx = f[fo // 2]
            if fn in self._edit_extras:
                if idx == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'item_idx_names') and idx in self.item_idx_names:
                    self._edit_extras[fn].config(text=self.item_idx_names[idx])
                else:
                    self._edit_extras[fn].config(text=f'物品#{idx}')

        # Resolve item names for drop item fields
        for fn, fo, _, _ in DROP_ITEM_FIELDS:
            iid = f[fo // 2]
            if fn in self._edit_extras:
                if iid == 0:
                    self._edit_extras[fn].config(text='(无)')
                elif hasattr(self, 'item_names') and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Resolve item names for equip_id fields
        for fn, fo, _, _ in EQUIP_FIELDS[4:]:
            iid = f[fo // 2]
            if fn in self._edit_extras:
                if iid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'item_names') and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Update flag labels (special_flag, move_flags)
        for fn in FLAG_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].get())
                    self._update_flags_label(fn, val)
                except ValueError:
                    self._update_flags_label(fn, 0)

        # Update use_right labels (use_right_item, use_right_weapon, use_right_armor)
        for fn in USE_RIGHT_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].get())
                    self._update_use_right_label(fn, val)
                except ValueError:
                    self._update_use_right_label(fn, 0)

        # Update status mask labels (cause_mask1, cause_mask2)
        for fn, fo, _, _ in STATUS_FIELDS:
            if fn in self._edit_extras:
                self._update_status_label(fn, f[fo // 2])

        # Tab 3: all raw fields
        for j in range(WARPC_FIELD_COUNT):
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                self._edit_vars[fn].set(str(f[j]))

    # ----------- 弹窗 -----------

    def _center_dialog(self, dlg, w, h):
        dlg.withdraw(); dlg.geometry(f'{w}x{h}'); dlg.update_idletasks()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        x = rx + (rw - w) // 2; y = ry + (rh - h) // 2
        dlg.geometry(f'+{x}+{y}'); dlg.deiconify()

    def _pick_skill(self, fn):
        """弹出技能选择对话框 — 加载 TKSkill.dat 显示技能名称"""
        if not self.records: return
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
        ttk.Button(bf, text='清空', command=lambda: [
            self._edit_vars[fn].set('-1'),
            self._edit_extras[fn].config(text='(未装备)') if fn in self._edit_extras else None,
            dlg.destroy()
        ]).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text='确定', command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_item(self, fn):
        """弹出物品选择对话框 — 装备索引(按TKItem下标)或装备ID"""
        if not self.records: return
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
            slot = fn[-1]  # '0','1','2','3'
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
            # also clear paired field
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_id{slot}'
            else:
                pair_fn = f'equip_idx{slot}'
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

        # 收集所有大幅图 (偶数索引)
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
                    ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=1)
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
            if cur_val >= 0:
                row_h = grid_frame.winfo_children()[0].winfo_reqheight() + 2 if grid_frame.winfo_children() else 70
                y = (cur_val // cols) * row_h
                total_h = cvs.bbox('all')[3] if cvs.bbox('all') else 1
                cvs.yview_moveto(min(1.0, max(0, y - 100) / total_h))

        cvs.bind('<Configure>', lambda e: _build_grid(), add='+')
        dlg.after(100, _build_grid)
        dlg.wait_window()

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
        """弹窗选择状态位掩码 (16个复选框, 对齐物品编辑器)"""
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
        """更新状态掩码标签显示 (逗号分隔的状态名列表)"""
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    # ----------- 编辑应用 -----------

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        f = rec['fields']

        # Apply role combobox
        if 'role' in self._edit_extras:
            sv = self._edit_extras['role'].get()
            f[3] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
            self._edit_vars['role'].set(str(f[3]))

        # Apply reaction_group combobox
        if 'reaction_group' in self._edit_extras:
            sv = self._edit_extras['reaction_group'].get()
            f[41] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
            self._edit_vars['reaction_group'].set(str(f[41]))

        # Sync status slot UI widgets → StringVars
        if hasattr(self, '_status_widgets'):
            for fn, fo, cb, ev_dur in self._status_widgets:
                sid = cb.current()  # 0="(无)", 1="1-破兵", ...
                if sid == 0:
                    v = -256  # empty slot sentinel (0xFF00)
                else:
                    try:
                        dur = int(ev_dur.get())
                        if dur < 0: dur = 1
                        if dur > 255: dur = 255
                    except ValueError:
                        dur = 1
                    v = (sid & 0xFF) | ((dur & 0xFF) << 8)
                    if v >= 0x8000: v -= 0x10000
                self._edit_vars[fn].set(str(v))

        # Apply status resist widgets
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                try:
                    byte_val = int(ev.get())
                    if byte_val < 0: byte_val = 0
                    if byte_val > 255: byte_val = 255
                except ValueError:
                    continue
                field_idx = 51 + byte_idx // 2
                is_high = byte_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                if is_high:
                    new_val = (unsigned & 0x00FF) | (byte_val << 8)
                else:
                    new_val = (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000:
                    new_val -= 0x10000
                f[field_idx] = new_val

        # Apply skill learn widgets
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                sv = cb.get()
                byte_val = int(sv.split('-', 1)[0]) if '-' in sv else 0
                field_idx = 88 + skill_idx // 2
                is_high = skill_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                if is_high:
                    new_val = (unsigned & 0x00FF) | (byte_val << 8)
                else:
                    new_val = (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000:
                    new_val -= 0x10000
                f[field_idx] = new_val

        # Apply named fields
        all_named_fields = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS +
                           SKILL_BONUS_FIELDS + EQUIP_FIELDS + EQUIP_SKILL_FIELDS +
                           STATUS_FIELDS + STATUS_SLOT_FIELDS + CHAR_ATTR_FIELDS + CHAR_USE_RIGHT_FIELDS + REACTION_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)
        for fn, fo, _, _ in all_named_fields:
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    f[fo // 2] = v
                except ValueError:
                    pass

        # 收集已由命名字段覆盖的 int16 索引, 避免 raw 循环用旧值覆盖
        named_indices = set()
        for _, fo, _, _ in all_named_fields:
            named_indices.add(fo // 2)
        # 状态抵抗占用的 [51]-[66] 由 _status_resist_widgets 处理
        for j in range(51, 67):
            named_indices.add(j)
        # 技能学习状态占用的 [88]-[259] 由 _skill_learn_widgets 处理
        for j in range(88, 260):
            named_indices.add(j)

        # Apply all raw fields from tab3 (跳过已由命名字段处理的)
        for j in range(WARPC_FIELD_COUNT):
            if j in named_indices: continue
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    f[j] = v
                except ValueError:
                    pass

        self._dirty = True
        # 仅更新当前行, 临时解绑避免 _on_tree_select→_populate_edit 覆盖编辑区
        nm = self._char_name(rec)
        hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
        mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
        role_val = f[3]; role_str = '我方' if role_val == -1 else ('敌方' if role_val == 0 else str(role_val))
        tag = 'ally' if role_val == -1 else ('enemy' if role_val == 0 else '')
        self.tree.unbind('<<TreeviewSelect>>')
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.item(child, values=(rec['index'], nm, f[2], role_str, hp_str, mp_str),
                               tags=(tag,) if tag else ())
                self.tree.selection_set(child); self.tree.see(child)
                break
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.status_var.set(f"角色 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.warpc_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 个角色到:\n{self.warpc_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.warpc_path, 'rb') as s:
                with open(self.warpc_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.set("正在保存…"); self.root.update()
            save_warpc(self.warpc_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.warpc_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.warpc_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['索引', '名称', '等级', '身份', '类型', 'HP当前', 'HP上限', 'MP当前', 'MP上限']
            for name in STAT_NAMES:
                hdr += [f'{name}(基础)', f'{name}(当前)']
            hdr += [f'field[{i}]' for i in range(27, 527)]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                fl = rec['fields']
                row = [str(rec['index']), self._char_name(rec),
                       str(fl[2]), str(fl[3]), str(fl[4]),
                       str(fl[5]), str(fl[8]), str(fl[6]), str(fl[10])]
                for i, bo in enumerate(STAT_BASE_OFFSETS):
                    row += [str(fl[bo//2]), str(fl[bo//2 + 1])]
                row += [str(fl[i]) for i in range(27, 527)]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = ["WarPC.dat 字段映射 (反编译依据):", ""]
        lines.append(f"【记录布局】{WARPC_CNT} 角色 × {WARPC_REC} 字节 = {WARPC_DECOMPRESSED} 字节")
        lines.append(f"  {WARPC_FIELD_COUNT} × int16 (小端序) 共 {WARPC_REC} 字节/角色")
        lines.append("")
        lines.append("【已验证字段 (反编译直接引用)】")
        for title, fields in [
            ("基本信息", IDENTITY_FIELDS), ("HP/MP", HPMP_FIELDS),
            ("八属性 (攻击/防御/命中/闪避/速度/幸运/悟性/移动)", STAT_FIELDS),
            ("技能加成 [32]-[42] (sub_422BBC TKSkill效果验证)", SKILL_BONUS_FIELDS),
            ("使用/装备权限 [77]-[81] (sub_41928C 验证: 主角#0 药品[77]=? 道具[78]=7 武器[79]=63 防具[80]=3 饰品[81]=?)", CHAR_USE_RIGHT_FIELDS),
            ("装备索引", EQUIP_FIELDS[:4]), ("装备ID", EQUIP_FIELDS[4:]),
            ("装备技能 [82]-[87] (6字段; Maker验证: 周倉)", EQUIP_SKILL_FIELDS),
            ("攻击导致状态 [67]-[68] (sub_42234C L94-95; 来自装备)", STATUS_FIELDS),
            ("状态抵抗 (32状态×1byte, 占16个int16[51]-[66]; sub_42234C初始化为0)", []),
            ("战后奖励 [268]-[269] (实测: 盜賊嘍嘍JP=2 Gold基数=20→Lv3得40)", BATTLE_REWARD_FIELDS),
        ]:
            lines.append(f"【{title}】")
            for fn, fo, fl, cmt in fields:
                lines.append(f"  [{fo//2:3d}] bo={fo:4d} {fl:<14s} {cmt}")
        lines.append("")
        lines.append("【技能学习状态】")
        lines.append(f"  [{88}-{259}] Maker Frm_WarPC: 不会/等待学/可以学/独立技学会/父技学会/支技能学会")
        lines.append(f"  344技能×1byte (TKSkill #0-#343), 存储在172个int16的高低字节中")
        lines.append("")
        lines.append("【尾部未分析区域】")
        lines.append(f"  [{TAIL_START}-{TAIL_END-1}] (426 字段) — 无反编译引用")
        lines.append("")
        lines.append("【核心反编译函数】")
        lines.append("  sub_42234C  装备/技能/属性应用 (字段 [5-10]/[11-26]/[32-42]/[67-72]/[86-87])")
        lines.append("  sub_41E40C  物品使用效果")
        lines.append("  sub_422768  角色初始化")
        lines.append("  sub_422BBC  被动技能效果计算")
        lines.append("  sub_4173F8  装备ID→索引匹配 ([69-72]←[73-76])")

        dlg = tk.Toplevel(self.root); dlg.title("字段参考 v1.0 (逆向)")
        dlg.geometry("680x600"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "WarPC.dat 可视化编辑器 v1.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "143 角色 × 1054 字节 (527×int16)\n\n"
            "逆向依据:\n"
            "  sub_42234C  装备/技能/属性应用\n"
            "  sub_41E40C  物品使用效果\n"
            "  sub_422BBC  被动技能效果计算\n"
            "  sub_4173F8  装备索引匹配\n"
            "  sub_45343C  DAT 统一加载\n"
            "  sub_452B14  LZSS 解压引擎"
        )


def main():
    root = tk.Tk(); WarpcEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
