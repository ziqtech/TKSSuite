#!/usr/bin/env python3
"""
WarPC.dat 可视化编辑器 v2.0 (PySide6 — Godot 4.6 风格)
===========================================================
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

Tab 分区 (按字段索引顺序排列):
  Tab 1: 核心属性 [0]-[68]
  Tab 2: 装备与技能 [69]-[87] + [260]-[272]
  Tab 3: 技能学习状态 [88]-[259]
  Tab 4: 技能效果判定 [273]+
  Tab 5: 全部字段 (raw grid)

字段布局 (仅列出反编译已验证的字段; 未验证字段标注 "未验证"):
  [0]   name_id      — 角色名称 TKT ID
  [1]   portrait     — 头像索引 (×2=Fa.JVG大幅图, ×2+1=缩略图)
  [2]   level        — 等级
  [3]   role         — 身份 (-1=未激活 0=已激活(sub_410674 L40入队时置0))
  [4]   exp_to_next  — 升级所需经验 (大多数=100; BOSS版较高: 呂布5092 張角7292)
  [5]-[10]  HP/MP    — 当前/基础/上限
  [11]-[26] 8通用属性 — 攻击/防御/命中/闪避/速度/幸运/移动/悟性 (基础/当前)
  [27]-[31] 角色五维  — 智慧/仁德/勇气/医术/技能点数
  [32]-[40] 技能加成  — 来自 TKSkill 装备效果
  [41]-[42] 反应组    — 被动技能触发分类
  [43]-[50] 状态槽    — 8个状态效果槽
  [51]-[66] 状态抵抗  — 32状态×1byte
  [67]-[68] 导致状态  — 攻击导致状态掩码
  [69]-[76] 装备      — 索引缓存+装备ID
  [77]-[81] 使用权限  — 药品/道具/武器/防具/饰品
  [82]-[87] 装备技能  — 4装备技能+2被动技能
  [88]-[259] 技能学习 — 344技能×1byte
  [260]-[263] 补丁字段 — awk_sprite/portrait_menu/history_text/entity_link
  [264]-[266] 成长率   — 初期/中期/后期
  [268]-[269] 战后奖励 — JP/金
  [270]-[272] 掉落物品 — 3个物品ID
  [273]+     技能效果  — TKKon ID 映射表

用法:
  python warpc_editor_v2.py
"""

import struct, os, sys, csv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar, QTabWidget,
)
from PySide6.QtGui import QColor, QFont, QIcon, QIntValidator
from PySide6.QtCore import Qt

# ═══════════════════════════════════════════════════════════════
# LZSS 编解码 (100% 原始逻辑)
# ═══════════════════════════════════════════════════════════════

def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]; bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078; out = bytearray(); flags = 0; pos = 12; bc = 4
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
                b = w[(j + ro) & 0xFFF]; out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

def lzss_compress(data):
    src = data; sl = len(src); flat = bytes(bytearray([0x20] * 4096) + src)
    tokens = []; pos = 0
    while pos < sl:
        curr = 4096 + pos; ms = min(18, sl - pos); bl, bo = 0, 0
        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat[curr:curr + length]; end = curr + length - 1; start = max(0, curr - 4096)
                idx = flat.rfind(pat, start, end)
                if idx != -1: bl = length; bo = (idx - 18) & 0xFFF; break
        if bl >= 3: tokens.append((False, bo, bl)); pos += bl
        else: tokens.append((True, src[pos], 0)); pos += 1
    stream = bytearray(); ti = 0
    while ti < len(tokens):
        fb = 0; be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]: fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]: stream.append(tokens[i][1])
            else:
                off, length = tokens[i][1], tokens[i][2]; el = length - 3
                stream.append(off & 0xFF); stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    ds = sl; bd = struct.pack('<I', ds) + bytes(stream)
    return struct.pack('<II', ds, len(bd)) + bd

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
    try: from PIL import Image
    except ImportError: return None
    if not jvg_path or not os.path.exists(jvg_path): return None
    with open(jvg_path, 'rb') as f: data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG': return None
    bc = struct.unpack_from('<I', data, 8)[0]; off = 32; sprites = []
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
        pal_bytes = bytes(pal_entries); dr = po + 512
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
                img = Image.frombytes('P', (w, h), bytes(px)); img.putpalette(pal_bytes)
                rgba = img.convert('RGBA')
                a_img = Image.frombytes('L', (w, h), bytes(alpha)); rgba.putalpha(a_img)
                sprites.append(rgba)
        off += 32 + (sc+1)*4 + 512 + ds
    return sprites

# ═══════════════════════════════════════════════════════════════
# 常量 (100% 原始定义)
# ═══════════════════════════════════════════════════════════════

WARPC_REC = 1054; WARPC_FIELD_COUNT = 527; WARPC_ORIG_COUNT = 143; WARPC_ORIG_SIZE = 150722

STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

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
    'use_right_item': ("道具使用权限", [(1,"战斗","可在战斗中"),(2,"非战斗","可在非战斗"),(4,"主角限定","仅主角可用")]),
    'use_right_weapon': ("武器装备权限", [(1,"刀",""),(2,"剑",""),(4,"枪",""),(8,"矛",""),(16,"弓",""),(32,"大刀",""),(64,"戟",""),(128,"锤","")]),
    'use_right_armor': ("防具装备权限", [(1,"衣袍",""),(2,"铠甲","")]),
}

SKILL_LEARN_COUNT = 344
SKILL_LEARN_STATES = ["0-不会","1-等待学","10-可以学","20-组技能学会","30-子技能学会"]

# 核心字段 — 已验证 (格式: key, offset, label, comment)
IDENTITY_FIELDS = [
    ("name_id",    0,  "名称TKT ID",  "角色名称 → TKT.dat (sub_4067E8)"),
    ("portrait",   2,  "头像索引",    "头像索引 ×2 = Fa.JVG 大幅图, ×2+1 = 缩略图"),
    ("level",      4,  "等级",        "角色等级 (数值显示)"),
    ("role",       6,  "身份",        "-1=未激活 0=已激活(sub_410674 L40入队时置0)"),
    ("exp_to_next", 8,  "升级所需经验","升至下一级所需经验; 绝大多数角色=100, BOSS版较高(呂布5092 張角7292)"),
]
# 补丁专用字段 [260]-[263] — 配合运行时补丁使用; 0=使用原硬编码公式
PATCH_FIELDS = [
    ("awk_sprite_id", 520, "战场图集索引（补丁专用）", "战斗中Awk.JVG/Awt.JVG块号; 0=使用原硬编码公式(PATH1:WarPC索引+6, PATH2:WarPC记录号+12); 非0=补丁直接使用此值"),
    ("portrait_menu_id", 522, "队伍头像ID（补丁专用）", "队伍菜单Mu.JVG精灵块号; 0=使用原公式(portrait+211); 非0=直接使用此值"),
    ("history_text_id", 524, "历史文本ID（补丁专用）", "角色界面「历史」标签页TKT文本ID; 0=使用原公式(9050+角色序号); 替代sub_41A080:104"),
    ("entity_link", 526, "地图实体ID",  "离队后在地图上显示的NPC实体ID → TKMat.dat; sub_41EEC0→sub_40C648"),
]
HPMP_FIELDS = [
    ("cur_hp",    10,  "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",    12,  "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base",   14,  "HP基础",      "HP基础值"),
    ("hp_max",    16,  "HP上限",      "HP上限 (基础+装备; sub_42234C)"),
    ("mp_base",   18,  "MP基础",      "MP基础值"),
    ("mp_max",    20,  "MP上限",      "MP上限 (基础+装备; sub_42234C)"),
]

STAT_NAMES_CN = ["攻击","防御","命中","闪避","速度","幸运","移动","悟性"]
STAT_SHORTS = ["atk","def","hit","eva","spd","luk","mov","wis"]
STAT_BASE_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]
# 8 属性对 (基础/当前) — sub_42234C L24-31/63-70 验证
STAT_FIELDS = []
for i, (n, s, bo) in enumerate(zip(STAT_NAMES_CN, STAT_SHORTS, STAT_BASE_OFFSETS)):
    STAT_FIELDS.append((f"{s}_base", bo, f"{n}(基础)",
                        f"{n}基础值 (sub_42234C: a2[{11+i*2}] initial)"))
    STAT_FIELDS.append((f"{s}_cur", bo+2, f"{n}(当前)",
                        f"{n}当前值 (基础+装备; sub_42234C L63-70 a2[{12+i*2}]+=v9[{11+i}])"))

# 技能加成区 [32]-[40] — sub_422BBC 应用 TKSkill 效果, sub_42234C 初始化
SKILL_BONUS_FIELDS = [
    ("atk_count",   64,  "攻击次数",       "攻击次数 (sub_42234C=1; sub_422BBC L29: a2[32]+=v6[31]=TKSkill增攻次)"),
    ("special_flag",66,  "特殊能力标志",   "来自装备 TKItem[20] (sub_42234C L73: a2[33]|=v9[20])"),
    ("mp_reduce",   68,  "内力消耗减少%",  "内息百分比 来自主动技能 TKSkill[33] (sub_422BBC L29: a2[34]+=v6[33])"),
    ("magic_def",   70,  "所受法伤减少%",  "抗魔百分比 来自主动技能 TKSkill[38] (sub_422BBC L45: a2[35]+=v6[38])"),
    ("exp_bonus",   72,  "战斗经验增加%",  "鬼才百分比 来自主动技能 TKSkill[36] (sub_422BBC L43: a2[36]+=v6[36])"),
    ("jp_bonus",    74,  "战斗技能点增加%","天才百分比 来自主动技能 TKSkill[37] (sub_422BBC L44: a2[37]+=v6[37])"),
    ("move_flags",  76,  "移动特殊标志",   "来自移动技能 TKSkill[32] (sub_422BBC L124: a2[38]|=v6[32])"),
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
# 反应组 [41]-[42] — 运行时字段, sub_422BBC type=2 写入, sub_42234C 初始化为0
REACTION_FIELDS = [
    ("reaction_group",  82,  "反应组",   "被动技能反应组编号 1-10 (sub_422BBC type=2; 初始化=0)"),
    ("reaction_trigger",84,  "触发概率", "被动技能触发概率 %%, 来自 TKSkill[44] (sub_422BBC: a2[42]=v6[44])"),
]
REACTION_GROUP_VALUES = ["0-无","1-近戰反擊","2-遠程反擊","3-法術反彈","4-先發制人","5-時序回饋","6-損傷賠償","7-環境探索","8-國色天香","9-有福同享","10-國士無雙"]

# 身上状态槽 [43]-[50] — sub_41E40C 验证: 8个状态效果槽, 每槽(status_id:byte, duration:byte)
STATUS_SLOT_FIELDS = [
    (f"status_slot{i}", 86+i*2, f"状态槽{i}",
     f"身上状态效果槽{i} (sub_41E40C: v8+{i*2}); 低字节=状态ID(1-32) 高字节=持续回合")
    for i in range(8)
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

ALL_NAMED_FIELDS = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS + CHAR_ATTR_FIELDS +
    SKILL_BONUS_FIELDS + REACTION_FIELDS + STATUS_SLOT_FIELDS +
    STATUS_FIELDS_CAUSE + EQUIP_FIELDS + CHAR_USE_RIGHT_FIELDS +
    EQUIP_SKILL_FIELDS + PATCH_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)

# ═══════════════════════════════════════════════════════════════
# 数据加载/保存 (100% 原始逻辑)
# ═══════════════════════════════════════════════════════════════

def load_warpc(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    if len(dec) % WARPC_REC != 0:
        raise ValueError(f"解压后大小 {len(dec)} 不是 {WARPC_REC} 的整数倍")
    recs = []; cnt = len(dec) // WARPC_REC
    for i in range(cnt):
        off = i * WARPC_REC
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        recs.append({'index': i, 'fields': list(vals)})
    return recs

def save_warpc(fp, recs):
    count = len(recs); buf = bytearray(count * WARPC_REC)
    for i, rec in enumerate(recs):
        rec['index'] = i; off = i * WARPC_REC
        struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, buf, off, *rec['fields'])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

def get_field(rec, byte_off):
    """读取指定字节偏移处的 int16 字段值"""
    return rec['fields'][byte_off // 2]

def set_field(rec, byte_off, val):
    """写入指定字节偏移处的 int16 字段值"""
    rec['fields'][byte_off // 2] = val

# 尾部未分析区域
TAIL_START = 260  # int16 offset (技能学习状态结束于 [259])
TAIL_END = 527

# ═══════════════════════════════════════════════════════════════
# 主题 QSS 加载 (从 themes/ 目录读取外部文件)
# ═══════════════════════════════════════════════════════════════

def _load_qss(filename):
    """加载 themes/ 目录下的 QSS 文件"""
    qss_path = os.path.join(os.path.dirname(__file__), 'themes', filename)
    if os.path.exists(qss_path):
        with open(qss_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

GODOT_DARK_QSS = _load_qss('dark.qss')
GODOT_LIGHT_QSS = _load_qss('light.qss')

# ═══════════════════════════════════════════════════════════════
# Dock 面板组件 (对齐 kon_editor_v2)
# ═══════════════════════════════════════════════════════════════

class NoWheelComboBox(QComboBox):
    """禁用鼠标滚轮切换值的下拉框，避免在滚动区域中误触"""
    def wheelEvent(self, event):
        event.ignore()

class DockHeader(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(4)
        lbl = QLabel(title); lbl.setObjectName("DockTitle"); layout.addWidget(lbl, 1)

def make_fake_input(line_edit=None, combo=None, button=None, stretch=True):
    box = QFrame(); box.setObjectName("FakeInputBox")
    h = QHBoxLayout(box); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
    if line_edit: line_edit.setFrame(False); h.addWidget(line_edit)
    if combo: h.addWidget(combo)
    if button: h.addWidget(button)
    if stretch: h.addStretch()
    return box

# ═══════════════════════════════════════════════════════════════
# 弹窗选择器
# ═══════════════════════════════════════════════════════════════

class SkillPickerDialog(QDialog):
    def __init__(self, parent, skill_names, skill_types, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能"); self.resize(550, 520)
        self.selected_index = None; self.skill_names = skill_names; self.skill_types = skill_types

        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["技能#","类型","名称"])
        self.table.setColumnWidth(0, 55); self.table.setColumnWidth(1, 55)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        bl = QHBoxLayout()
        btn_clr = QPushButton("清空(-1)"); btn_clr.clicked.connect(lambda: self._clear())
        bl.addWidget(btn_clr); bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept)); layout.addLayout(bl)

        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower(); self.table.setRowCount(0); row = 0
        type_names = {0:"指令",1:"主动",2:"被动",3:"移动"}
        for idx in sorted(self.skill_names.keys()):
            nm = self.skill_names[idx]; tp = type_names.get(self.skill_types.get(idx,-1),"?")
            if q and q not in f"{idx} {tp} {nm}".lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(tp))
            self.table.setItem(row, 2, QTableWidgetItem(nm)); row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel: self.selected_index = int(self.table.item(sel[0].row(), 0).text()); self.accept()

    def _clear(self): self.selected_index = -1; self.accept()

class ItemPickerDialog(QDialog):
    def __init__(self, parent, lookup, cur_val, is_idx=False, idx_to_id=None, id_to_idx=None):
        super().__init__(parent)
        self.setWindowTitle("选择物品"); self.resize(520, 520)
        self.selected_key = None; self.lookup = lookup; self.is_idx = is_idx
        self.idx_to_id = idx_to_id or {}; self.id_to_idx = id_to_idx or {}

        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)

        self.table = QTableWidget(0, 2)
        label = "物品#" if is_idx else "物品ID"
        self.table.setHorizontalHeaderLabels([label, "名称"])
        self.table.setColumnWidth(0, 80)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        bl = QHBoxLayout()
        clear_val = "-1" if is_idx else "0"
        btn_clr = QPushButton(f"清空({clear_val})"); btn_clr.clicked.connect(lambda: self._clear(clear_val))
        bl.addWidget(btn_clr); bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept)); layout.addLayout(bl)
        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower(); self.table.setRowCount(0); row = 0
        for k, v in sorted(self.lookup.items(), key=lambda x: x[0]):
            if q and q not in f"{k} {v}".lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(k)))
            self.table.setItem(row, 1, QTableWidgetItem(v)); row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel: self.selected_key = int(self.table.item(sel[0].row(), 0).text()); self.accept()

    def _clear(self, val): self.selected_key = int(val); self.accept()

class TktPickerDialog(QDialog):
    def __init__(self, parent, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择 TKT 文本"); self.resize(500, 500)
        self.selected_id = None
        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["ID","文本"])
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)
        bl = QHBoxLayout(); bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept)); layout.addLayout(bl)
        self.items = sorted(tkt_dict.items(), key=lambda x: x[0]); self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower(); self.table.setRowCount(0); row = 0
        for eid, txt in self.items:
            if q and q not in txt.lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(eid)))
            self.table.setItem(row, 1, QTableWidgetItem(txt[:80].replace('\n',' '))); row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel: self.selected_id = int(self.table.item(sel[0].row(), 0).text()); self.accept()

class StatusMaskDialog(QDialog):
    def __init__(self, parent, title, current_mask, base_idx):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(320, 520)
        self.checkboxes = []
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); vlay = QVBoxLayout(content)
        for i in range(16):
            idx = base_idx + i
            if idx >= len(STATUS_NAMES): break
            cb = QCheckBox(f"{idx}. {STATUS_NAMES[idx]}"); cb.setChecked(bool(current_mask & (1<<i)))
            self.checkboxes.append(cb); vlay.addWidget(cb)
        vlay.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [c.setChecked(True) for c in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [c.setChecked(False) for c in self.checkboxes]))
        bl.addStretch(); bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self.accept)); layout.addLayout(bl)

    def get_mask(self):
        m = sum((1<<i) for i, cb in enumerate(self.checkboxes) if cb.isChecked())
        return m if m < 0x8000 else m - 0x10000

class FlagsDialog(QDialog):
    def __init__(self, parent, title, bits, current_val):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(400, 250)
        self.bits = bits; self.vars = []
        layout = QVBoxLayout(self)
        for bit, name, desc in bits:
            cb = QCheckBox(f"bit{bit} {name}" if not desc else f"{name} ({desc})")
            cb.setChecked(bool(current_val & (1<<bit))); self.vars.append((bit, cb))
            layout.addWidget(cb)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [v.setChecked(True) for _,v in self.vars]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [v.setChecked(False) for _,v in self.vars]))
        bl.addStretch(); bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self.accept)); layout.addLayout(bl)

    def get_value(self):
        m = sum((1<<bit) for bit, cb in self.vars if cb.isChecked())
        return m if m < 0x8000 else m - 0x10000

class UseRightDialog(QDialog):
    def __init__(self, parent, title, opts, current_val):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(360, 60+max(len(opts),2)*32)
        self.opts = opts; self.vars = []
        layout = QVBoxLayout(self)
        for bit, name, desc in opts:
            cb = QCheckBox(f"{name}" + (f" ({desc})" if desc else ""))
            cb.setChecked(bool(current_val & bit)); self.vars.append((bit, cb))
            layout.addWidget(cb)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [v.setChecked(True) for _,v in self.vars]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [v.setChecked(False) for _,v in self.vars]))
        bl.addStretch(); bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self.accept)); layout.addLayout(bl)

    def get_value(self):
        m = sum(bit for bit, cb in self.vars if cb.isChecked())
        return m if m < 0x8000 else m - 0x10000

class TkkonPickerDialog(QDialog):
    def __init__(self, parent, tkkon_names, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择 TKKon"); self.resize(500, 500)
        self.selected_id = None
        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["TKKon#","名称"])
        self.table.setColumnWidth(0, 70)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("清空(-1)", clicked=lambda: (setattr(self,'selected_id',-1), self.accept())))
        bl.addStretch(); bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept)); layout.addLayout(bl)
        self.items = sorted(tkkon_names.items(), key=lambda x: x[0]) if tkkon_names else []; self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower(); self.table.setRowCount(0); row = 0
        for idx, nm in self.items:
            if q and q not in f"{idx} {nm}".lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(nm)); row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel: self.selected_id = int(self.table.item(sel[0].row(), 0).text()); self.accept()

class FieldRefDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段参考 v2.0 (逆向来源)"); self.resize(700, 600)
        layout = QVBoxLayout(self)
        text = QTextEdit(); text.setReadOnly(True); text.setFont(QFont("Consolas", 9))
        lines = ["WarPC.dat 字段映射 (反编译依据):", ""]
        cnt = WARPC_ORIG_COUNT
        lines.append(f"【记录布局】{cnt} 角色 × {WARPC_REC} 字节 = {cnt*WARPC_REC} 字节")
        lines.append(f"  原游戏 143 角色 ({WARPC_ORIG_SIZE} 字节), 编辑器支持动态扩展")
        lines.append(f"  {WARPC_FIELD_COUNT} × int16 (小端序) 共 {WARPC_REC} 字节/角色")
        lines.append("")
        lines.append("【已验证字段 (反编译直接引用)】")
        for title, fields in [
            ("基本信息 [0]-[4]", IDENTITY_FIELDS), ("HP/MP [5]-[10]", HPMP_FIELDS),
            ("八属性 [11]-[26] (攻击/防御/命中/闪避/速度/幸运/悟性/移动)", STAT_FIELDS),
            ("角色五维 [27]-[31]", CHAR_ATTR_FIELDS),
            ("技能加成 [32]-[40] (sub_422BBC TKSkill效果验证)", SKILL_BONUS_FIELDS),
            ("反应组 [41]-[42]", REACTION_FIELDS),
            ("身上状态 [43]-[50]", STATUS_SLOT_FIELDS),
            ("状态抵抗 [51]-[66] (32状态×1byte)", []),
            ("攻击导致状态 [67]-[68] (sub_42234C L94-95; 来自装备)", STATUS_FIELDS_CAUSE),
            ("装备索引 [69]-[72]", EQUIP_FIELDS[:4]), ("装备ID [73]-[76]", EQUIP_FIELDS[4:]),
            ("使用/装备权限 [77]-[81]", CHAR_USE_RIGHT_FIELDS),
            ("装备技能 [82]-[87] (Maker验证: 周倉)", EQUIP_SKILL_FIELDS),
            ("补丁专用字段 [260]-[263]", PATCH_FIELDS),
            ("成长率 [264]-[266]", GROWTH_FIELDS),
            ("战后奖励 [268]-[269]", BATTLE_REWARD_FIELDS),
            ("可掉落物品 [270]-[272]", DROP_ITEM_FIELDS),
        ]:
            lines.append(f"【{title}】")
            for field_tuple in fields:
                fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
                cmt = field_tuple[3] if len(field_tuple) > 3 else ''
                lines.append(f"  [{fo//2:3d}] bo={fo:4d} {fl:<14s} {cmt}")
        lines.append("")
        lines.append("【技能学习状态】")
        lines.append(f"  [88-259] 反编译验证: 不会/等待学(1~9进展累积)/可以学(≥10)/父技学会(20)/独立技学会(30)")
        lines.append(f"  344技能×1byte (TKSkill #0-#343), 存储在172个int16的高低字节中")
        lines.append("")
        lines.append("【技能效果判定】")
        lines.append(f"  [273]-[273+count-1] sub_4307CC/sub_435D68 验证: 技能→TKKon动画映射表")
        lines.append(f"  全部type=0指令技能(末尾为普通攻击); 每字段=int16 TKKon ID (0~649)")
        lines.append("")
        lines.append("【核心反编译函数】")
        for s in ["sub_42234C 装备/技能/属性应用 (字段 [5-10]/[11-26]/[32-42]/[67-72]/[86-87])",
                  "sub_41E40C 物品使用效果",
                  "sub_422768 角色初始化",
                  "sub_422BBC 被动技能效果计算",
                  "sub_4173F8 装备ID→索引匹配 ([69-72]←[73-76])",
                  "sub_45343C DAT 文件统一加载",
                  "sub_452B14 LZSS 解压引擎"]:
            lines.append(f"  {s}")
        text.setPlainText('\n'.join(lines)); layout.addWidget(text)
        bl = QHBoxLayout(); bl.addStretch(); bl.addWidget(QPushButton("关闭", clicked=self.close)); layout.addLayout(bl)

# ═══════════════════════════════════════════════════════════════
# 主编辑器窗口
# ═══════════════════════════════════════════════════════════════

class WarpcEditorV2(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WarPC.dat 可视化编辑器 v2.0 - PySide6")
        self.resize(1400, 850); self.setMinimumSize(1100, 680)

        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        self.warpc_path = self.tkt_path = None
        self.records = []; self.tkt = {}
        self.skill_names = {}; self._skill_types = {}; self.tkkon_names = {}
        self.item_names = {}; self.item_idx_names = {}; self._idx_to_id = {}; self._id_to_idx = {}
        self.filtered_indices = []; self._dirty = False; self._editing_idx = -1

        self._edit_vars = {}; self._edit_extras = {}; self._status_widgets = []
        self._status_resist_widgets = []; self._skill_learn_widgets = []
        self._skill_effect_widgets = []; self._skill_effect_name_labels = []
        self._fa_sprites = []; self._fa_photos = {}

        self._build_ui(); self._set_edit_enabled(False); self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        self.setStyleSheet(GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS)
        self._update_paths()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark; self._apply_theme(); self._refresh_table()

    def _update_paths(self):
        cg = "color:#55b572;" if self._is_dark else "color:#178a39;"
        cr = "color:#e27d60;" if self._is_dark else "color:#c93b16;"
        for lb, p, key in [(self.lbl_warpc, self.warpc_path, 'WarPC'),
                            (self.lbl_tkt, self.tkt_path, 'TKT')]:
            if not p: lb.setStyleSheet(cr); lb.setText(f"{key}: 未加载")
            else: lb.setStyleSheet(cg); lb.setText(f"{key}: {p}")
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        for lb, fn, key in [(self.lbl_item, 'TKItem.dat', 'TKItem'),
                             (self.lbl_skill, 'TKSkill.dat', 'TKSkill'),
                             (self.lbl_fa, 'Fa.JVG', 'Fa.JVG')]:
            p = os.path.join(tks_dir, fn) if tks_dir else ''
            if not p or not os.path.exists(p): lb.setStyleSheet(cr); lb.setText(f"{key}: 未找到")
            else: lb.setStyleSheet(cg); lb.setText(f"{key}: {p}")

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QVBoxLayout(central); main_layout.setContentsMargins(8,8,8,4); main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…\tCtrl+O", self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出 CSV…", self._export_csv)
        fm.addSeparator(); fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新增角色\tCtrl+N", self._add_new)
        em.addAction("复制当前角色", self._copy_record)
        em.addAction("导出当前角色(.warpc)…", self._export_warpc)
        em.addAction("导入角色(.warpc)…", self._import_warpc)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段参考 (逆向来源)", self._show_field_ref)
        hm.addAction("关于", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit(); self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter); toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主 Splitter
        splitter = QSplitter(Qt.Horizontal); splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False); main_layout.addWidget(splitter, 1)

        # 左侧：角色列表
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#","角色名称","等级","身份","HP","MP"])
        self.table.setColumnWidth(0, 40); self.table.setColumnWidth(2, 45); self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(4, 70); self.table.setColumnWidth(5, 70)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        splitter.addWidget(self.table)

        # 右侧：编辑面板
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4,4,4,4); rl.setSpacing(4)

        # 预览头
        preview = QFrame(); preview.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview); pl.setContentsMargins(8,8,8,8); pl.setSpacing(4)

        hdr_row = QHBoxLayout()
        self.preview_avatar = QLabel(""); hdr_row.addWidget(self.preview_avatar)
        info_col = QVBoxLayout()
        self.preview_name = QLabel("(未选中)"); self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True); info_col.addWidget(self.preview_name)
        self.preview_meta = QLabel(""); self.preview_meta.setProperty("class", "PreviewMeta")
        self.preview_meta.setWordWrap(True); info_col.addWidget(self.preview_meta)
        hdr_row.addLayout(info_col, 1); pl.addLayout(hdr_row)

        self.preview_desc = QLabel("请在左侧列表中选择角色。")
        self.preview_desc.setProperty("class", "PreviewDesc"); self.preview_desc.setWordWrap(True)
        pl.addWidget(self.preview_desc)
        rl.addWidget(preview)

        # Tab 页
        self.tabs = QTabWidget()
        self._build_tab1(); self._build_tab2(); self._build_tab3(); self._build_tab4(); self._build_tab5()
        rl.addWidget(self.tabs, 1)

        # 底部按钮
        bf = QHBoxLayout()
        bf.addWidget(QPushButton("✅ 应用修改", clicked=self._apply_edit))
        bf.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit)); bf.addStretch()
        rl.addLayout(bf)
        splitter.addWidget(right); splitter.setSizes([350, 1050])

        # 底部路径栏
        path_layout = QHBoxLayout(); path_layout.setContentsMargins(4,2,4,2)
        self.lbl_warpc = QLabel(); self.lbl_tkt = QLabel(); self.lbl_item = QLabel()
        self.lbl_skill = QLabel(); self.lbl_fa = QLabel()
        for w in [self.lbl_warpc, self.lbl_tkt, self.lbl_item, self.lbl_skill, self.lbl_fa]:
            path_layout.addWidget(w); path_layout.addSpacing(15)
        path_layout.addStretch(); main_layout.addLayout(path_layout)

    def _build_scroll_tab(self, name):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(4,4,12,4); inner.layout().setSpacing(4)
        scroll.setWidget(inner); self.tabs.addTab(scroll, name)
        return inner

    def _build_section(self, parent, title, fields, cols=8, field_ft='int'):
        """构建字段分组"""
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader(title))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)
        for fi, field_tuple in enumerate(fields):
            fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
            cmt = field_tuple[3] if len(field_tuple) > 3 else fl
            r, c = divmod(fi, cols)
            self._build_field_widget(grid, r, c, fn, fo, fl, field_ft, cmt)
        bl.addLayout(grid); gl.addWidget(body); parent.layout().addWidget(grp)

    def _build_field_widget(self, grid, r, c, fn, fo, fl, field_ft='int', cmt=''):
        """单个字段控件"""
        cell = QVBoxLayout(); cell.setSpacing(2)
        lbl = QLabel(fl); lbl.setToolTip(f"[{fo//2}] byte {fo}: {cmt}"); lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        ev = QLineEdit(); self._edit_vars[fn] = ev

        if fn == 'role':
            cb = NoWheelComboBox(); cb.addItems(["-1-未激活", "0-已激活"])
            cell.addWidget(make_fake_input(combo=cb)); self._edit_extras[fn] = cb
        elif fn == 'reaction_group':
            cb = NoWheelComboBox(); cb.addItems(REACTION_GROUP_VALUES)
            cell.addWidget(make_fake_input(combo=cb)); self._edit_extras[fn] = cb
        elif fn in FLAG_DEFS:
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev_hidden = QLineEdit(); ev_hidden.hide(); self._edit_vars[fn] = ev_hidden
            btn = QPushButton("配置…"); btn.clicked.connect(lambda _, f=fn: self._pick_flags(f))
            bh.addWidget(btn, 1); cell.addWidget(box)
            extra = QLabel("(无)"); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        elif fn in USE_RIGHT_DEFS:
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev_hidden = QLineEdit(); ev_hidden.hide(); self._edit_vars[fn] = ev_hidden
            btn = QPushButton("配置权限…"); btn.clicked.connect(lambda _, f=fn: self._pick_use_right(f))
            bh.addWidget(btn, 1); cell.addWidget(box)
            extra = QLabel("(无)"); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        elif fn.startswith('cause_mask'):
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev_hidden = QLineEdit(); ev_hidden.hide(); self._edit_vars[fn] = ev_hidden
            is_cause = fn.startswith('cause_')
            btn = QPushButton("选择导致状态…" if is_cause else "选择解除状态…")
            btn.clicked.connect(lambda _, f=fn: self._pick_status_mask(f))
            bh.addWidget(btn, 1); cell.addWidget(box)
            extra = QLabel("(无)"); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        elif field_ft == 'skill_pick':
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev.setMaximumWidth(50); bh.addWidget(ev)
            btn = QPushButton("…"); btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))
            bh.addWidget(btn); cell.addWidget(box)
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        elif field_ft == 'item_pick':
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev.setMaximumWidth(50); bh.addWidget(ev)
            btn = QPushButton("…"); btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, f=fn: self._pick_item(f))
            bh.addWidget(btn); cell.addWidget(box)
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        elif fn == 'portrait':
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev.setMaximumWidth(50); bh.addWidget(ev)
            btn = QPushButton("…"); btn.setFixedWidth(28)
            btn.clicked.connect(lambda: self._pick_portrait())
            bh.addWidget(btn); cell.addWidget(box)
        elif fn == 'history_text_id':
            cell.addWidget(make_fake_input(line_edit=ev))
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText"); extra.setWordWrap(True)
            cell.addWidget(extra); self._edit_extras[fn] = extra
        else:
            cell.addWidget(make_fake_input(line_edit=ev))

        grid.addLayout(cell, r, c, Qt.AlignTop)

    # ── Tab 构建 ──
    def _build_tab1(self):
        p = self._build_scroll_tab("核心属性")
        self._build_section(p, "基本信息 [0]-[8]", IDENTITY_FIELDS, 6)
        self._build_section(p, "HP / MP [10]-[20]", HPMP_FIELDS, 6)
        self._build_section(p, "八属性 [22]-[50]", STAT_FIELDS, 8)
        self._build_section(p, "角色五维 [54]-[62]", CHAR_ATTR_FIELDS, 5)
        self._build_section(p, "技能加成 [64]-[80] (来自TKSkill)", SKILL_BONUS_FIELDS, 5)
        self._build_section(p, "反应组 [82]-[84]", REACTION_FIELDS, 2)
        self._build_status_slots(p)
        self._build_status_resist(p)
        self._build_section(p, "攻击导致状态 [134]-[136]", STATUS_FIELDS_CAUSE, 2, 'mask')

    def _build_status_slots(self, parent):
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader("身上状态 [86]-[100] (8槽×2字节)"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)
        status_options = ["(无)"] + [f"{i+1}-{STATUS_NAMES[i]}" for i in range(len(STATUS_NAMES))]
        for si, field_tuple in enumerate(STATUS_SLOT_FIELDS):
            fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
            cmt = field_tuple[3] if len(field_tuple) > 3 else fl
            r, c = divmod(si, 4)
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(f"状态槽{si}"); lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(f"[{fo//2}] {cmt}"); cell.addWidget(lbl)
            cb = NoWheelComboBox(); cb.addItems(status_options)
            dur = QLineEdit("0"); dur.setMinimumWidth(40)
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            lb2 = QLabel("持续:"); lb2.setMinimumWidth(50); lb2.setAlignment(Qt.AlignCenter); lb2.setProperty("class", "PropLabel"); bh.addWidget(lb2)
            bh.addWidget(dur)
            sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFixedWidth(1); sep.setProperty("class", "FakeInputSep"); bh.addWidget(sep)
            bh.addWidget(cb, 1)
            cell.addWidget(box)
            self._status_widgets.append((fn, fo, cb, dur))
            ev_hidden = QLineEdit(); ev_hidden.hide(); self._edit_vars[fn] = ev_hidden
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid); gl.addWidget(body); parent.layout().addWidget(grp)

    def _build_status_resist(self, parent):
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader("状态抵抗 [102]-[132] (32状态×1byte)"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setVerticalSpacing(2); grid.setHorizontalSpacing(4)
        for i in range(32):
            r, c = divmod(i, 16)
            sname = STATUS_NAMES[i] if i < len(STATUS_NAMES) else f"{i+1}"
            cell = QVBoxLayout(); cell.setSpacing(1)
            lbl = QLabel(sname); lbl.setProperty("class", "PropLabel"); lbl.setToolTip(f"[51+{i//2}]")
            cell.addWidget(lbl)
            ev = QLineEdit("0"); cell.addWidget(ev)
            self._status_resist_widgets.append((i, ev))
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid); gl.addWidget(body); parent.layout().addWidget(grp)

    def _build_tab2(self):
        p = self._build_scroll_tab("装备与技能")
        self._build_section(p, "装备索引 [138]-[144]", EQUIP_FIELDS[:4], 4, 'item_pick')
        self._build_section(p, "装备物品ID [146]-[152]", EQUIP_FIELDS[4:], 4, 'item_pick')
        self._build_section(p, "使用/装备权限 [154]-[162]", CHAR_USE_RIGHT_FIELDS, 5)
        self._build_section(p, "装备技能 [164]-[174] (6字段)", EQUIP_SKILL_FIELDS, 3, 'skill_pick')
        self._build_section(p, "补丁字段 [520]-[526]", PATCH_FIELDS, 4)
        self._build_section(p, "成长率 [528]-[532]", GROWTH_FIELDS, 3)
        self._build_section(p, "战后奖励 [536]-[538]", BATTLE_REWARD_FIELDS, 2)
        self._build_section(p, "可掉落物品 [540]-[544]", DROP_ITEM_FIELDS, 3, 'item_pick')

    def _build_tab3(self):
        """技能学习状态 [176]-[518]"""
        p = self._build_scroll_tab("技能学习")
        self._skill_learn_labels = []
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader(f"技能学习状态 [176]-[518] ({SKILL_LEARN_COUNT}技能×1byte)"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setVerticalSpacing(2); grid.setHorizontalSpacing(4)
        for i in range(SKILL_LEARN_COUNT):
            r, c = divmod(i, 8)
            sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
            if i == 343: sname = "普通攻击"
            cell = QVBoxLayout(); cell.setSpacing(1)
            lbl = QLabel(sname[:12])
            lbl.setToolTip(f"[{88+i//2}] {sname}")
            lbl.setProperty("class", "PropLabel"); cell.addWidget(lbl)
            cb = NoWheelComboBox(); cb.addItems(SKILL_LEARN_STATES); cell.addWidget(cb)
            self._skill_learn_widgets.append((i, cb)); self._skill_learn_labels.append(lbl)
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid); gl.addWidget(body); p.layout().addWidget(grp)

    def _build_tab4(self):
        """技能效果判定"""
        p = self._build_scroll_tab("技能效果判定")
        self._effect_inner = p

    def _build_skill_effect_section(self, parent):
        active_indices = [i for i in range(350) if self._skill_types.get(i)==0] if self._skill_types else []
        max_slots = WARPC_FIELD_COUNT - 273; count = min(len(active_indices), max_slots)
        if count == 0:
            lbl = QLabel("(需要加载 TKSkill.dat 数据)"); parent.layout().addWidget(lbl); return
        self._skill_effect_widgets = []; self._skill_effect_name_labels = []
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader(f"技能效果判定 [546]-[{546+(count-1)*2}] ({count}个指令技能→TKKon)"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)
        for i in range(count):
            r, c = divmod(i, 8)
            skill_idx = active_indices[i]
            sname = "普通攻击" if skill_idx == 344 else self.skill_names.get(skill_idx, f"技能#{skill_idx}")
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(sname[:15]); lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(f"[{273+i}] TKSkill#{skill_idx} → TKKon ID"); cell.addWidget(lbl)
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            ev = QLineEdit("-1"); bh.addWidget(ev)
            btn = QPushButton("…"); btn.setFixedWidth(26)
            btn.clicked.connect(lambda _, idx=i, sv=ev: self._pick_tkkon(idx, sv))
            bh.addWidget(btn); cell.addWidget(box)
            name_lbl = QLabel("(未设置)"); name_lbl.setProperty("class", "ExtraPreviewText")
            cell.addWidget(name_lbl); self._skill_effect_widgets.append((i, ev))
            self._skill_effect_name_labels.append(name_lbl)
            ev.textChanged.connect(lambda _, idx=i, sv=ev: self._update_kon_label(idx, sv))
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid); gl.addWidget(body); parent.layout().addWidget(grp)

    def _build_tab5(self):
        p = self._build_scroll_tab("全部字段")
        self._tab5_inner = p

    def _build_raw_grid(self, parent):
        COLS = 8
        for base in range(0, WARPC_FIELD_COUNT, 100):
            end = min(base+100, WARPC_FIELD_COUNT)
            grp = QWidget()
            gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
            gl.addWidget(DockHeader(f"字段 [{base}] — [{end-1}]"))
            body = QWidget(); body.setObjectName("DockBody")
            bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
            grid = QGridLayout(); grid.setVerticalSpacing(1); grid.setHorizontalSpacing(2)
            for j in range(base, end):
                r, c = divmod(j-base, COLS)
                cell = QVBoxLayout(); cell.setSpacing(1)
                lbl = QLabel(f"[{j}]"); lbl.setProperty("class", "PropLabel"); cell.addWidget(lbl)
                fn = f"raw_{j}"
                ev = QLineEdit(); ev.setMaximumWidth(65); self._edit_vars[fn] = ev; cell.addWidget(ev)
                grid.addLayout(cell, r, c, Qt.AlignTop)
            bl.addLayout(grid); gl.addWidget(body); parent.layout().addWidget(grp)

    # ── 数据加载 ──
    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        wp = os.path.join(d, "WarPC.dat"); tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(wp):
            QMessageBox.warning(self, "文件缺失", "未找到 WarPC.dat"); return
        self.warpc_path = wp; self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.warpc_path: return
        self.status_var.setText("加载中…"); QApplication.processEvents()

        orig_path = self.warpc_path + ".orig"
        if os.path.exists(orig_path):
            if QMessageBox.question(self, "检测到未恢复的备份",
                "发现 WarPC.dat.orig, 是否从备份恢复?",
                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                try:
                    bak = orig_path + ".editor_bak"
                    import shutil
                    if not os.path.exists(bak): shutil.copy2(self.warpc_path, bak)
                    os.replace(orig_path, self.warpc_path)
                    self.status_var.setText("已从 .orig 备份恢复")
                except Exception as e:
                    QMessageBox.critical(self, "恢复失败", str(e))

        if self.tkt_path: self.tkt = load_tkt(self.tkt_path)
        tks_dir = os.path.dirname(self.warpc_path)
        fa_path = os.path.join(tks_dir, 'Fa.JVG')
        self._fa_sprites = load_jvg_sprites(fa_path) or []; self._fa_photos.clear()

        try:
            self.records = load_warpc(self.warpc_path); self._dirty = False
            self.skill_names, self._skill_types = self._load_skill_names()
            self.tkkon_names = self._load_tkkon_names()
            self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()

            # 更新技能学习标签
            if hasattr(self, '_skill_learn_labels') and self._skill_learn_labels:
                for i, lbl in enumerate(self._skill_learn_labels):
                    if i < len(self._skill_learn_labels):
                        sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
                        if i == 343: sname = "普通攻击"
                        lbl.setText(sname[:12])

            # 重建技能效果判定
            if hasattr(self, '_effect_inner') and self._effect_inner:
                self._clear_layout(self._effect_inner.layout())
                self._build_skill_effect_section(self._effect_inner)

            # 重建全部字段
            if hasattr(self, '_tab5_inner') and self._tab5_inner:
                self._clear_layout(self._tab5_inner.layout())
                self._build_raw_grid(self._tab5_inner)

            nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
            tkkon_count = len(self.tkkon_names)
            self.status_var.setText(f"{len(self.records)} 角色 | 有效 {nonempty} | TKT {len(self.tkt)} 条 | 物品 {len(self.item_names)} 技能 {len(self.skill_names)} TKKon {tkkon_count}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _clear_layout(self, layout):
        if layout is None: return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            elif item.layout(): self._clear_layout(item.layout())

    def _load_skill_names(self):
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        sk_path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path): return {}, {}
        try:
            with open(sk_path, 'rb') as f: dec = lzss_decompress(f.read())
            names, types = {}, {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec): break
                name_id = struct.unpack_from('<h', dec, off)[0]
                stype = struct.unpack_from('<h', dec, off + 4)[0]
                types[i] = stype
                if name_id > 0 and name_id in self.tkt:
                    names[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
                elif name_id:
                    names[i] = f'#{name_id}'
            return names, types
        except: return {}, {}

    def _load_tkkon_names(self):
        name_csv = os.path.join(os.path.dirname(__file__), 'tkkon_names.csv')
        if not os.path.exists(name_csv): return {}
        try:
            lookup = {}
            with open(name_csv, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f); next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip().isdigit():
                        idx = int(row[0]); name = row[1].strip()
                        if name: lookup[idx] = name
            return lookup
        except: return {}

    def _load_item_names(self):
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        it_path = os.path.join(tks_dir, 'TKItem.dat')
        if not os.path.exists(it_path): return {}, {}, {}, {}
        try:
            with open(it_path, 'rb') as f: dec = lzss_decompress(f.read())
            id_lookup, idx_lookup, idx_to_id, id_to_idx = {}, {}, {}, {}
            for i in range(600):
                off = i * 64
                if off + 10 > len(dec): break
                item_id = struct.unpack_from('<h', dec, off)[0]
                name_id = struct.unpack_from('<h', dec, off + 4)[0]
                if name_id > 0 and name_id in self.tkt:
                    nm = self.tkt[name_id].split('\n')[0].strip()[:25]
                elif item_id > 0:
                    nm = f'物品#{item_id}'
                else: continue
                if item_id > 0:
                    id_lookup[item_id] = nm; idx_to_id[i] = item_id; id_to_idx[item_id] = i
                idx_lookup[i] = nm
            return id_lookup, idx_lookup, idx_to_id, id_to_idx
        except: return {}, {}, {}, {}

    def _set_edit_enabled(self, en):
        self.tabs.setEnabled(en)

    # ── 筛选/列表 ──
    def _char_name(self, rec):
        f = rec['fields']; nid = f[0]
        if nid > 0 and nid in self.tkt:
            return self.tkt[nid].split('\n')[0].strip()[:20]
        if nid < 0 and -nid in self.tkt:
            return self.tkt[-nid].split('\n')[0].strip()[:20]
        return f"#{nid}" if nid else f"(空-#{rec['index']})"

    def _apply_filter(self):
        q = self.search_entry.text().strip().lower(); self.filtered_indices = []
        for rec in self.records:
            if q:
                nm = self._char_name(rec)
                if q not in f"{rec['index']} {nm} {rec['fields'][2]} {rec['fields'][3]}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
        msg = f"显示 {len(self.filtered_indices)}/{len(self.records)} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.setText(msg)

    def _clear_filter(self):
        self.search_entry.clear(); self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True); self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]; f = r['fields']
            nm = self._char_name(r)
            hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
            mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
            role_val = f[3]; role_str = '未激活' if role_val==-1 else ('已激活' if role_val==0 else str(role_val))
            tag_color = QColor("#2266CC") if role_val==-1 else QColor("#CC3333") if role_val==0 else QColor("#dcdcdc")
            self.table.insertRow(row)
            for ci, v in enumerate([str(r['index']), nm, str(f[2]), role_str, hp_str, mp_str]):
                item = QTableWidgetItem(v); item.setForeground(tag_color)
                if ci in (0, 2, 3): item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, ci, item)
        self.table.blockSignals(False)

    def _get_fa_photo(self, sprite_idx, size=(24,24)):
        if not self._fa_sprites: return None
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites): return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None: return None
        cache_key = (sprite_idx, size)
        if cache_key in self._fa_photos: return self._fa_photos[cache_key]
        try:
            from PIL import Image
            img = sprite.resize(size, Image.NEAREST).convert('RGBA')
            data = img.tobytes('raw', 'RGBA')
            from PySide6.QtGui import QImage, QPixmap
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg); self._fa_photos[cache_key] = pix; return pix
        except: return None

    # ── 编辑 ──
    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel:
            # 清除视图
            self._editing_idx = -1; self.preview_name.setText("(未选中)")
            self.preview_meta.setText(""); self.preview_desc.setText("请在左侧列表中选择角色。")
            self.preview_avatar.clear(); return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']; f = rec['fields']; nm = self._char_name(rec)

        # 预览
        self.preview_name.setText(f"{nm}  (编号 #{rec['index']})")
        role_str = '未激活' if f[3]==-1 else ('已激活' if f[3]==0 else str(f[3]))
        self.preview_meta.setText(
            f"等级={f[2]}  |  身份={role_str}  |  HP={f[5]}/{f[8]}  |  MP={f[6]}/{f[10]}")

        desc_parts = []
        for si, name in enumerate(STAT_NAMES_CN):
            base = f[STAT_BASE_OFFSETS[si]//2]; cur = f[STAT_BASE_OFFSETS[si]//2+1]
            desc_parts.append(f"{name}={cur}")
        self.preview_desc.setText("  |  ".join(desc_parts))

        portrait = f[1]; large_idx = portrait * 2 if portrait >= 0 else 0
        pix = self._get_fa_photo(large_idx, (72, 72))
        self.preview_avatar.setPixmap(pix) if pix else self.preview_avatar.clear()

        # 填充字段
        for fn, fo, _, *_ in ALL_NAMED_FIELDS:
            val = str(f[fo//2])
            if fn in self._edit_vars:
                w = self._edit_vars[fn]; w.setText(val)
            if fn == 'role' and fn in self._edit_extras:
                cb = self._edit_extras[fn]
                for i in range(cb.count()):
                    if cb.itemText(i).startswith(f'{f[3]}-'): cb.setCurrentIndex(i); break
            if fn == 'reaction_group' and fn in self._edit_extras:
                cb = self._edit_extras[fn]
                for i in range(cb.count()):
                    if cb.itemText(i).startswith(f'{f[41]}-'): cb.setCurrentIndex(i); break

        # 状态槽
        if hasattr(self, '_status_widgets'):
            for fs_fn, fo, cb, ev_dur in self._status_widgets:
                v = f[fo//2]; sid = v & 0xFF; dur = (v>>8) & 0xFF
                if sid == 0 or sid > len(STATUS_NAMES): cb.setCurrentIndex(0)
                else: cb.setCurrentIndex(sid)
                ev_dur.setText(str(dur) if sid != 0 and dur != 0xFF else "0")

        # 状态抵抗
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                field_idx = 51 + byte_idx//2; is_high = byte_idx%2
                unsigned = f[field_idx] & 0xFFFF; byte_val = (unsigned>>(8*is_high)) & 0xFF
                ev.setText(str(byte_val))

        # 技能学习
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                field_idx = 88 + skill_idx//2; is_high = skill_idx%2
                unsigned = f[field_idx] & 0xFFFF; byte_val = (unsigned>>(8*is_high)) & 0xFF
                for vi, item in enumerate(cb.itemText(i) for i in range(cb.count())):
                    if item.startswith(f'{byte_val}-'): cb.setCurrentIndex(vi); break

        # 技能效果
        if hasattr(self, '_skill_effect_widgets'):
            for i, ev in self._skill_effect_widgets:
                field_idx = 273 + i
                if field_idx < WARPC_FIELD_COUNT: ev.setText(str(f[field_idx]))

        # 额外文本解析
        for fn, fo, _, *_ in EQUIP_SKILL_FIELDS:
            if fn in self._edit_extras:
                sid = f[fo//2]
                if sid == -1: self._edit_extras[fn].setText('(未装备)')
                elif sid in self.skill_names: self._edit_extras[fn].setText(self.skill_names[sid])
                else: self._edit_extras[fn].setText(f'技能#{sid}')

        for fn, fo, _, *_ in EQUIP_FIELDS[:4]:
            if fn in self._edit_extras:
                idx = f[fo//2]
                if idx == -1: self._edit_extras[fn].setText('(未装备)')
                elif idx in self.item_idx_names: self._edit_extras[fn].setText(self.item_idx_names[idx])
                else: self._edit_extras[fn].setText(f'物品#{idx}')

        for fn, fo, _, *_ in EQUIP_FIELDS[4:]:
            if fn in self._edit_extras:
                iid = f[fo//2]
                if iid == -1: self._edit_extras[fn].setText('(未装备)')
                elif iid in self.item_names: self._edit_extras[fn].setText(self.item_names[iid])
                else: self._edit_extras[fn].setText(f'物品#{iid}')

        for fn, fo, _, *_ in DROP_ITEM_FIELDS:
            if fn in self._edit_extras:
                iid = f[fo//2]
                if iid == 0: self._edit_extras[fn].setText('(无)')
                elif iid in self.item_names: self._edit_extras[fn].setText(self.item_names[iid])
                else: self._edit_extras[fn].setText(f'物品#{iid}')

        if 'history_text_id' in self._edit_extras:
            hid = f[524//2]
            if hid == 0:
                default_id = 9050 + rec['index']
                if default_id in self.tkt:
                    txt = self.tkt[default_id].split('\n')[0].strip()[:25]
                    self._edit_extras['history_text_id'].setText(f'默认→TKT#{default_id}: {txt}')
                else:
                    self._edit_extras['history_text_id'].setText(f'默认→TKT#{default_id} (未找到)')
            elif hid in self.tkt:
                txt = self.tkt[hid].split('\n')[0].strip()[:25]
                self._edit_extras['history_text_id'].setText(f'TKT#{hid}: {txt}')
            else:
                self._edit_extras['history_text_id'].setText(f'TKT#{hid} (未找到)')

        for fn in FLAG_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try: val = int(self._edit_vars[fn].text())
                except: val = 0
                _, bits = FLAG_DEFS[fn]; mask = val & 0xFFFF
                sel = [name for bit, name, _ in bits if mask & (1<<bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

        for fn in USE_RIGHT_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try: val = int(self._edit_vars[fn].text())
                except: val = 0
                _, opts = USE_RIGHT_DEFS[fn]; mask = val & 0xFFFF
                sel = [name for bit, name, _ in opts if (mask & bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

        for fn, *rest in STATUS_FIELDS_CAUSE:
            if fn in self._edit_extras:
                mask = f[134//2] if fn=='cause_mask1' else f[136//2]
                self._update_status_label(fn, mask & 0xFFFF)

        # 全部字段 Tab
        for j in range(WARPC_FIELD_COUNT):
            fn = f"raw_{j}"
            if fn in self._edit_vars: self._edit_vars[fn].setText(str(f[j]))

    # ── 弹窗 ──
    def _pick_skill(self, fn):
        if not self.skill_names: return
        try: cur = int(self._edit_vars[fn].text() or 0)
        except: cur = 0
        dlg = SkillPickerDialog(self, self.skill_names, self._skill_types, cur)
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self._edit_vars[fn].setText(str(dlg.selected_index))
            if fn in self._edit_extras:
                nm = self.skill_names.get(dlg.selected_index, '')
                if dlg.selected_index == -1: self._edit_extras[fn].setText('(未装备)')
                elif nm: self._edit_extras[fn].setText(nm)
                else: self._edit_extras[fn].setText(f'技能#{dlg.selected_index}')

    def _pick_item(self, fn):
        is_idx = fn.startswith('equip_idx')
        lookup = self.item_idx_names if is_idx else self.item_names
        if not lookup: return
        try: cur = int(self._edit_vars[fn].text() or 0)
        except: cur = 0
        dlg = ItemPickerDialog(self, lookup, cur, is_idx, self._idx_to_id, self._id_to_idx)
        if dlg.exec() == QDialog.Accepted and dlg.selected_key is not None:
            self._edit_vars[fn].setText(str(dlg.selected_key))
            if fn in self._edit_extras:
                if is_idx:
                    nm = self.item_idx_names.get(dlg.selected_key, '')
                    self._edit_extras[fn].setText(nm if dlg.selected_key!=-1 else '(未装备)')
                else:
                    nm = self.item_names.get(dlg.selected_key, '')
                    self._edit_extras[fn].setText(nm if dlg.selected_key!=-1 else '(未装备)')
            # 同步配对字段
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_id{slot}'; pair_val = self._idx_to_id.get(dlg.selected_key, 0)
            else:
                pair_fn = f'equip_idx{slot}'; pair_val = self._id_to_idx.get(dlg.selected_key, -1)
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].setText(str(pair_val))
            if pair_fn in self._edit_extras:
                if pair_val == -1:
                    self._edit_extras[pair_fn].setText('(未装备)')
                elif is_idx:
                    self._edit_extras[pair_fn].setText(self.item_names.get(pair_val, f'物品#{pair_val}'))
                else:
                    self._edit_extras[pair_fn].setText(self.item_idx_names.get(pair_val, f'物品#{pair_val}'))

    def _pick_flags(self, fn):
        if fn not in FLAG_DEFS: return
        title, bits = FLAG_DEFS[fn]
        try: cur = int(self._edit_vars[fn].text() or 0)
        except: cur = 0
        dlg = FlagsDialog(self, title, bits, cur & 0xFFFF)
        if dlg.exec() == QDialog.Accepted:
            val = dlg.get_value()
            self._edit_vars[fn].setText(str(val))
            if fn in self._edit_extras:
                mask = val & 0xFFFF
                sel = [name for bit, name, _ in bits if mask & (1<<bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_use_right(self, fn):
        if fn not in USE_RIGHT_DEFS: return
        title, opts = USE_RIGHT_DEFS[fn]
        try: cur = int(self._edit_vars[fn].text() or 0)
        except: cur = 0
        dlg = UseRightDialog(self, title, opts, cur & 0xFFFF)
        if dlg.exec() == QDialog.Accepted:
            val = dlg.get_value()
            self._edit_vars[fn].setText(str(val))
            if fn in self._edit_extras:
                mask = val & 0xFFFF
                sel = [name for bit, name, _ in opts if (mask & bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_status_mask(self, fn):
        try: cur = int(self._edit_vars[fn].text() or 0)
        except: cur = 0
        base = 0 if fn.endswith('_mask1') else 16
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = StatusMaskDialog(self, title, cur & 0xFFFF, base)
        if dlg.exec() == QDialog.Accepted:
            new_mask = dlg.get_mask()
            self._edit_vars[fn].setText(str(new_mask))
            if fn in self._edit_extras:
                self._update_status_label(fn, new_mask & 0xFFFF)

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_mask1') else 16
        sel = [STATUS_NAMES[base+i] for i in range(16)
               if (mask & (1<<i)) and base+i < len(STATUS_NAMES)]
        if fn in self._edit_extras:
            self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_portrait(self):
        if not self._fa_sprites: return
        fn = 'portrait'
        try: cur_val = int(self._edit_vars[fn].text() or 0)
        except: cur_val = 0
        dlg = QDialog(self); dlg.setWindowTitle("选择头像 (Fa.JVG)"); dlg.resize(780, 560)
        layout = QVBoxLayout(dlg)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); grid = QGridLayout(inner); grid.setSpacing(2)
        large_indices = [(si, si//2) for si in range(0, len(self._fa_sprites), 2) if self._fa_sprites[si] is not None]
        COLS = 8
        for sprite_idx, portrait_idx in large_indices:
            r, c = divmod(portrait_idx, COLS)
            btn = QPushButton()
            btn.setFixedSize(80, 90)
            btn.setCursor(Qt.PointingHandCursor)
            if portrait_idx == cur_val:
                btn.setStyleSheet("QPushButton{background-color:#2e3548; border:2px solid #478cbf;}" if self._is_dark else "QPushButton{background-color:#f0f0f0; border:2px solid #478cbf;}")
            else:
                btn.setStyleSheet("QPushButton{background-color:transparent; border:1px solid transparent;}")
            pix = self._get_fa_photo(sprite_idx, (64, 64))
            if pix:
                btn.setIcon(QIcon(pix)); btn.setIconSize(pix.size())
            btn.setText(str(portrait_idx))
            btn.clicked.connect(lambda checked, v=portrait_idx: (self._edit_vars[fn].setText(str(v)), dlg.accept()))
            grid.addWidget(btn, r, c)
        scroll.setWidget(inner); layout.addWidget(scroll)
        bl = QHBoxLayout(); bl.addStretch(); bl.addWidget(QPushButton("取消", clicked=dlg.reject))
        layout.addLayout(bl); dlg.exec()

    def _pick_tkkon(self, idx, ev):
        if not self.tkkon_names: return
        try: cur = int(ev.text() or 0)
        except: cur = 0
        dlg = TkkonPickerDialog(self, self.tkkon_names, cur)
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            ev.setText(str(dlg.selected_id))

    def _update_kon_label(self, idx, ev):
        if idx >= len(self._skill_effect_name_labels): return
        try: kon_id = int(ev.text())
        except: return
        name = self.tkkon_names.get(kon_id, f"TKKon#{kon_id}") if kon_id >= 0 else "(未设置)"
        self._skill_effect_name_labels[idx].setText(name)

    # ── 应用编辑 ──
    def _apply_edit(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]; f = rec['fields']

        # Role / Reaction group
        if 'role' in self._edit_extras:
            sv = self._edit_extras['role'].currentText()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                f[3] = int(sv[:sep]) if sep >= 0 else int(sv)
        if 'reaction_group' in self._edit_extras:
            sv = self._edit_extras['reaction_group'].currentText()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                f[41] = int(sv[:sep]) if sep >= 0 else int(sv)

        # 状态槽
        if hasattr(self, '_status_widgets'):
            for fs_fn, fo, cb, ev_dur in self._status_widgets:
                sid = cb.currentIndex()
                if sid == 0: v = -256
                else:
                    try: dur = int(ev_dur.text())
                    except: dur = 1
                    if dur < 0: dur = 1
                    if dur > 255: dur = 255
                    v = (sid & 0xFF) | ((dur & 0xFF) << 8)
                    if v >= 0x8000: v -= 0x10000
                f[fo//2] = v

        # 状态抵抗
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                try: byte_val = int(ev.text())
                except: continue
                if byte_val < 0: byte_val = 0
                if byte_val > 255: byte_val = 255
                field_idx = 51 + byte_idx//2; is_high = byte_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                new_val = (unsigned & 0x00FF) | (byte_val << 8) if is_high else (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000: new_val -= 0x10000
                f[field_idx] = new_val

        # 技能学习
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                sv = cb.currentText()
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                byte_val = int(sv[:sep]) if sep >= 0 else 0
                field_idx = 88 + skill_idx//2; is_high = skill_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                new_val = (unsigned & 0x00FF) | (byte_val << 8) if is_high else (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000: new_val -= 0x10000
                f[field_idx] = new_val

        # 技能效果
        if hasattr(self, '_skill_effect_widgets'):
            for i, ev in self._skill_effect_widgets:
                field_idx = 273 + i
                if field_idx >= WARPC_FIELD_COUNT: continue
                try: v = int(ev.text()); f[field_idx] = max(-32768, min(32767, v))
                except: pass

        # 命名字段
        for fn, fo, _, *_ in ALL_NAMED_FIELDS:
            if fn in self._edit_vars and fn not in ('role', 'reaction_group'):
                try: v = int(self._edit_vars[fn].text()); f[fo//2] = max(-32768, min(32767, v))
                except: pass

        # 全部字段 — 跳过已由命名字段+状态抵抗+技能学习+技能效果覆盖的
        named_indices = set(fo//2 for _, fo, *rest in ALL_NAMED_FIELDS)
        for j in range(51, 67): named_indices.add(j)
        for j in range(88, 260): named_indices.add(j)
        if hasattr(self, '_skill_effect_widgets'):
            for i, _ in self._skill_effect_widgets: named_indices.add(273 + i)
        for j in range(WARPC_FIELD_COUNT):
            if j in named_indices: continue
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                try: v = int(self._edit_vars[fn].text()); f[j] = max(-32768, min(32767, v))
                except: pass

        self._dirty = True
        nm = self._char_name(rec)
        hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
        mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
        role_str = '未激活' if f[3]==-1 else ('已激活' if f[3]==0 else str(f[3]))
        self._refresh_table()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == rec['index']:
                self.table.selectRow(r); break
        self.status_var.setText(f"角色 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx >= 0: self._populate_edit(self.records[self._editing_idx])

    # ── 新增/复制/导出/导入 ──
    def _add_new(self):
        if not self.records: return
        new_idx = len(self.records)
        fields = [0]*WARPC_FIELD_COUNT
        fields[3] = -1; fields[4] = 100; fields[2] = 1
        fields[5] = 50; fields[6] = 25; fields[7] = 50; fields[8] = 50; fields[9] = 25; fields[10] = 25
        for si in range(8): fields[22+si*4] = 10; fields[22+si*4+2] = 10
        fields[32] = 1
        for si in range(82, 88): fields[si] = -1
        self.records.append({'index': new_idx, 'fields': fields})
        self._dirty = True; self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == new_idx:
                self.table.selectRow(r); break
        self.status_var.setText(f"已新增角色 #{new_idx} (内存, 未保存)")

    def _copy_record(self):
        if self._editing_idx < 0: return
        src = self.records[self._editing_idx]
        new_idx = len(self.records)
        self.records.append({'index': new_idx, 'fields': list(src['fields'])})
        self._dirty = True; self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == new_idx:
                self.table.selectRow(r); break
        self.status_var.setText(f"已复制 #{self._editing_idx} → #{new_idx}")

    def _export_warpc(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]; nm = self._char_name(rec)
        safe_name = "".join(c for c in nm if c not in r'\/:*?"<>|' and ord(c)>=32) or f"角色_{self._editing_idx}"
        fp, _ = QFileDialog.getSaveFileName(self, "导出角色", f"{safe_name}.warpc", "WarPC文件 (*.warpc)")
        if not fp: return
        magic = b'WPC1'; raw = struct.pack('<' + 'h' * WARPC_FIELD_COUNT, *rec['fields'])
        with open(fp, 'wb') as f: f.write(magic + raw)
        self.status_var.setText(f"已导出: {os.path.basename(fp)}")

    def _import_warpc(self):
        if not self.records: return
        fp, _ = QFileDialog.getOpenFileName(self, "导入角色", "", "WarPC文件 (*.warpc)")
        if not fp: return
        try:
            with open(fp, 'rb') as f: data = f.read()
            if len(data) < 4 or data[:4] != b'WPC1':
                QMessageBox.critical(self, "格式错误", "不是有效的 .warpc 文件"); return
            raw = data[4:]
            if len(raw) < WARPC_FIELD_COUNT*2:
                QMessageBox.critical(self, "格式错误", f"需要 {WARPC_FIELD_COUNT*2} 字节, 实际 {len(raw)}"); return
            fields = list(struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, raw, 0))
            new_idx = len(self.records)
            self.records.append({'index': new_idx, 'fields': fields})
            self._dirty = True; self._apply_filter()
            for r in range(self.table.rowCount()):
                if int(self.table.item(r, 0).text()) == new_idx:
                    self.table.selectRow(r); break
            self.status_var.setText(f"已导入: {os.path.basename(fp)} → #{new_idx}")
        except Exception as e: QMessageBox.critical(self, "导入失败", str(e))

    # ── 保存/导出CSV ──
    def _save(self):
        if not self.warpc_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        if QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 个角色到:\n{self.warpc_path}\n\n原文件将被覆盖 (生成 .bak).",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        try:
            with open(self.warpc_path, 'rb') as s:
                with open(self.warpc_path+".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.setText("正在保存…"); QApplication.processEvents()
            save_warpc(self.warpc_path, self.records); self._dirty = False
            self.status_var.setText(f"已保存 → {self.warpc_path}")
            QMessageBox.information(self, "成功", f"已保存\n备份: {self.warpc_path}.bak")
        except Exception as e: QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "", "CSV (*.csv)")
        if not p: return
        with open(p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            hdr = ['索引','名称','等级','身份','类型','HP当前','HP上限','MP当前','MP上限']
            for name in STAT_NAMES_CN: hdr += [f'{name}(基础)', f'{name}(当前)']
            hdr += [f'field[{i}]' for i in range(27, WARPC_FIELD_COUNT)]
            writer.writerow(hdr)
            for rec in self.records:
                fl = rec['fields']
                row = [str(rec['index']), self._char_name(rec), str(fl[2]), str(fl[3]), str(fl[4]),
                       str(fl[5]), str(fl[8]), str(fl[6]), str(fl[10])]
                for bo in STAT_BASE_OFFSETS: row += [str(fl[bo//2]), str(fl[bo//2+1])]
                row += [str(fl[i]) for i in range(27, WARPC_FIELD_COUNT)]
                writer.writerow(row)
        self.status_var.setText(f"已导出: {p}")

    # ── 帮助 ──
    def _show_field_ref(self):
        FieldRefDialog(self).exec()

    def _show_about(self):
        cnt = len(self.records) if self.records else WARPC_ORIG_COUNT
        QMessageBox.about(self, "关于",
            f"WarPC.dat 可视化编辑器 v2.0 (PySide6)\n\n"
            f"基于《三国群侠传》 TKS.exe 反编译\n"
            f"{cnt} 角色 × {WARPC_REC} 字节 ({WARPC_FIELD_COUNT}×int16)\n"
            f"原游戏: {WARPC_ORIG_COUNT} 角色 ({WARPC_ORIG_SIZE} 字节), 支持动态扩展\n\n"
            f"Godot 4.6 风格 UI · FakeInputBox · 深/浅色主题切换\n\n"
            f"逆向依据:\n"
            f"  sub_42234C  装备/技能/属性应用\n"
            f"  sub_41E40C  物品使用效果\n"
            f"  sub_422BBC  被动技能效果计算\n"
            f"  sub_4173F8  装备索引匹配\n"
            f"  sub_45343C  DAT 统一加载\n"
            f"  sub_452B14  LZSS 解压引擎\n\n"
            f"Tab 分区 (按字段索引顺序):\n"
            f"  Tab 1: 核心属性 [0]-[68]\n"
            f"  Tab 2: 装备与技能 [69]-[87] + [260]-[272]\n"
            f"  Tab 3: 技能学习状态 [88]-[259]\n"
            f"  Tab 4: 技能效果判定 [273]+\n"
            f"  Tab 5: 全部字段 (raw grid)")

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存", "有未保存的修改, 确定退出?")
            if reply == QMessageBox.No: event.ignore(); return
        event.accept()

# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("WarPC Editor")
    editor = WarpcEditorV2(); editor.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
