#!/usr/bin/env python3
"""
TKItem.dat 可视化编辑器 v3.0 (严格对照 Maker.exe TksModify.dll UI 布局 + TKS.exe 反编译)

【v3.0 变更】基于反编译源码 (sub_41E40C/sub_42234C/sub_422BBC) + Maker 文案 + 实测数据验证:
  1. 字段 [22] offset 44: "装备后学习技能" (v15[22] -> char+176+v15[22]=10, 装备时学会)
     ※实测验证: 蟬翼刀#178 [22]=135=技能"蟬翼刀"; 虎紋刀#177 [22]=134=技能"虎紋刀"
  2. 字段 [23] offset 46: "使用后学习技能1" (v15[23] -> byte_757FB8[1054*a2+v15[23]]=10, 使用时)
     ※实测验证: 遁甲天書#79 [23]=24=技能"瀚力術"
  3. 字段 [24] offset 48: "使用后学习技能2"
     ※实测验证: 遁甲天書#79 [24]=25=技能"遲緩術"
  4. 字段 [26] offset 52: "导致状态 1-16" (Maker UI 标签)
     ※实测验证: 紅顏知己[27]=0x1000 bit12=28迷恋; 大骨鎚[27]=0xC bit2/3=18禁制+19定身
     (反编译 a2[67]=v9[26] 只是保存, 战斗时读取作状态 mask 使用)
  5. 字段 [27] offset 54: "导致状态 17-32"
  6. 字段 [28] offset 56: "解除状态 1-16"
  7. 字段 [29] offset 58: "解除状态 17-32"
  8. 字段 [25] offset 50: "增加医术" (Maker UI 文案; word_75688A += v15[25])
  9. 使用权限 (equip_type) 位掩码语义 (2026-05 全面重分析):
     0=通用/饰品(110条): 坐骑/饰品/任务物品, 0b0=无限制
     1=刀/道具/轻衣(39条): 刀类武器+消耗品+轻便衣物/披风/袍, 0b1=bit0
     2=剑/书籍/铠甲(97条): 剑类武器+书籍+重甲防具, 0b10=bit1
     3=药品/食物(26条): 治疗物品, 刀剑通用 0b11=bit0|bit1
     4=枪/秘笈(18条): 枪类武器+特殊秘笈/法宝, 0b100=bit2
     8=矛(8条), 16=弓弩(12条), 32=大刀(12条), 64=戟(6条), 128=锤(6条)
     (基于 sub_41928C/sub_41F318/sub_4307CC 逆向+全600条实测验证)
 10. 记录数硬限制: 600 条 (sub_45343C 加载 38400 字节 = 600x64; sub_42F8D4 遍历 < 600)
 11. 空槽 (40 条可新增物品): #560-#599, item_id=0 & name_id=0 & desc_id=600
"""

import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ============================================================
# LZSS 编解码 (sub_452B14)
# ============================================================
def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]; bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20]*4096); wp = 4078; out = bytearray(); flags = 0; pos = 12; bc = 4
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
            b1, b2 = data[pos], data[pos+1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

def lzss_compress(data):
    src = data; sl = len(src)
    # 极速优化：使用线性 bytes 并借助底层 C 实现的 rfind 替代缓慢的纯 Python O(N^2) 搜索
    # 初始化完整的 4096 字节虚拟历史记录与当前数据拼接
    flat_bytes = bytes(bytearray([0x20]*4096) + src)

    tokens = []; pos = 0
    while pos < sl:
        curr = 4096 + pos
        ms = min(18, sl - pos)
        bl, bo = 0, 0

        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat_bytes[curr : curr + length]
                end_idx = curr + length - 1
                start_idx = max(0, curr - 4096)

                # 寻找在 4096 窗口内最近的匹配项
                idx = flat_bytes.rfind(pat, start_idx, end_idx)
                if idx != -1:
                    bl = length
                    # 将绝对索引直接转换为 Ring Buffer 的偏移量
                    bo = (idx - 18) & 0xFFF
                    break

        if bl >= 3:
            tokens.append((False, bo, bl))
            pos += bl
        else:
            tokens.append((True, src[pos], 0))
            pos += 1

    stream = bytearray(); ti = 0
    while ti < len(tokens):
        fb = 0; be = min(ti+8, len(tokens))
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

# ============================================================
# TKT / TKSkill 文本加载
# ============================================================
def load_tkt(tkt_path):
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8+ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt*4, cnt*4
    lookup = {}
    SKIP = set(range(0,10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i*4)[0]
        if eid in SKIP:
            continue
        off = struct.unpack_from('<I', dec, idsz + i*4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0:
                end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try:
                s = txt.decode('big5', errors='replace')
            except:
                s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.split('\n')[0].strip()
    return lookup

def load_tkt_full(tkt_path):
    """加载 TKT 全部文本（保留完整多行内容，\x1e 转为换行）"""
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8+ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt*4, cnt*4
    lookup = {}
    SKIP = set(range(0,10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i*4)[0]
        if eid in SKIP:
            continue
        off = struct.unpack_from('<I', dec, idsz + i*4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0:
                end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try:
                s = txt.decode('big5', errors='replace')
            except:
                s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.strip()
    return lookup

def load_tkskill_names(sp, tkt):
    if not sp or not os.path.exists(sp):
        return {}
    with open(sp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    REC = 94
    names = {}
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % REC == 0 and (len(dec) == 0 or len(dec) % REC != 0):
        dec = raw
    for i in range(min(350, len(dec)//REC)):
        sid = struct.unpack_from('<h', dec, i*REC)[0]
        n = tkt.get(sid,"") or tkt.get(-sid,"") or f"Skill#{sid}"
        names[i] = n
    return names

# ============================================================
# Mu.JVG 物品图标加载 (icon + 130 = 精灵索引)
# ============================================================
def load_mu_sprites(mu_path):
    """加载 Mu.JVG 并返回 PIL Image 列表 (PIL 可用时) 或 None"""
    try:
        from PIL import Image
    except ImportError:
        return None
    if not mu_path or not os.path.exists(mu_path):
        return None
    with open(mu_path, 'rb') as f:
        data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG':
        return None
    bc = struct.unpack_from('<I', data, 8)[0]
    off = 32
    sprites = []
    for bi in range(bc):
        if off + 32 > len(data) or data[off:off+4] != b'@JVM':
            break
        sc = struct.unpack_from('<I', data, off+4)[0]
        ds = struct.unpack_from('<I', data, off+12)[0]
        s1 = off + 32
        co = [struct.unpack_from('<I', data, s1+j*4)[0] for j in range(sc+1)]
        po = s1 + (sc+1)*4
        pal_entries = []
        for j in range(256):
            e = struct.unpack_from('<H', data, po+j*2)[0]
            r = ((e>>11)&0x1F)<<3
            g = ((e>>5)&0x3F)<<2
            b = (e&0x1F)<<3
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
            # RLE 解码 (对齐 jvg_editor _decode_rle)
            total = w*h
            px = bytearray(total)
            alpha = bytearray(total)
            recs = []
            rp = 0
            while rp + 4 <= len(ed):
                sk = struct.unpack_from('<H', ed, rp)[0]
                rw = struct.unpack_from('<H', ed, rp+2)[0]
                rp += 4
                rw = min(rw, len(ed)-rp)
                rd = ed[rp:rp+rw] if rw>0 else b''
                rp += rw
                recs.append((sk, rw, rd))
            if not recs:
                continue
            simple = (recs[0][0]==0 and recs[0][1]==w and all(r[1]==w for r in recs))
            if simple:
                for ri, (_, rw, rpix) in enumerate(recs):
                    if ri >= h:
                        break
                    tr = h-1-ri
                    for c in range(min(rw, len(rpix))):
                        px[tr*w+c] = rpix[rw-1-c]
                        alpha[tr*w+c] = 255
            else:
                scr_w = 640
                gap = max(scr_w-w, 0)
                bp = total-1
                pg = 0
                for sa, rw, rpix in recs:
                    rem = sa-pg
                    pg = 0
                    if rem < 0:
                        rem = 0
                    while rem > 0 and bp >= 0:
                        col = (total-1-bp)%w
                        tb = w-col
                        if rem <= tb:
                            bp -= rem
                            rem = 0
                        else:
                            bp -= tb
                            rem -= tb+gap
                            rem = max(rem, 0)
                    cb = (total-1-bp)%w if bp >= 0 else 0
                    al = min(rw, len(rpix))
                    for k in range(al):
                        if 0 <= bp < total:
                            px[bp] = rpix[k]
                            alpha[bp] = 255
                        bp -= 1
                    pg = gap if al > 0 and cb+al >= w else 0
            # 创建 PIL Image (alpha 通道由 RLE 解码器提供, 不依赖 palette index 0)
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
# 常量 (Maker.exe TksModify.dll 文案 + TKS.exe 反编译)
# ============================================================
# 31 种状态 (bit 0..30; Maker UI 状态列表)
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]
STATUS_ICON_BASE = 242  # Mu.JVG 中 31 个 30x30 状态图标起始精灵索引

# 战斗结算效果 (combat_flag, field [20]) — sub_42234C: a2[33] |= v9[20]; 战斗结算时按位检查
COMBAT_FLAG_BITS = [
    (1, "JP×2~3",              "战后技能点数×2~3 (無方戒; bit0)"),
    (2, "战后全恢复+异常全解",  "战斗结束HP/MP全恢复+清除异常 (無雙戒; bit1)"),
    (4, "经验×2~3平分队友",    "战斗经验×2~3并平分队友 (無嗔戒; bit2)"),
    (8, "经验独得",            "战斗经验归一人独享 (無道戒; bit3)"),
]
EXTRA_FLAG_BITS = [
    (0, "遇敌率降低",     "随机阈值140→遇敌率↓; 战斗时序+30%; sub_4084E0 bit0 (偽裝戒指)"),
    (1, "遇敌率大幅降低", "随机阈值200→遇敌率↓↓; 战斗时序+50%; sub_4084E0 bit1 (隱藏戒指)"),
    (2, "免遇敌",         "完全跳过随机战斗; sub_4084E0 bit2 (虛無戒指)"),
    (3, "战斗时序加速",   "敌方计时条额外扣减(每回合); sub_431E70 bit3 (無常戒)"),
    (4, "银两×2~5",      "物品描述声称此效果; 逆向全量代码未找到实现, Cut Content (無心戒)"),
    (5, "战斗时序强效",   "敌方计时条强制扣减(更强效); sub_431E70 bit5 (六無玄冥石)"),
]

# 使用权限 (equip_type) — 多选位掩码，选项根据页面号动态切换
#  sub_41928C: word_77CBD4[32*idx] & word_757FA4[527*char] → 权限位与校验
USE_RIGHT_OPTIONS = {
    0: [(1, "战斗"), (2, "非战斗")],                              # 药品
    1: [(1, "战斗"), (2, "非战斗"), (4, "主角限定")],              # 道具
    2: [(1, "刀"), (2, "剑"), (4, "枪"), (8, "矛"),
        (16, "弓"), (32, "大刀"), (64, "戟"), (128, "锤")],      # 武器
    3: [(1, "衣袍"), (2, "铠甲")],                                # 防具
    4: [(0, "通用")],                                             # 饰品
    5: [(0, "通用")],                                             # 特殊
}

def _use_right_label(val, page):
    """根据页面号解析使用权限为可读文本"""
    opts = USE_RIGHT_OPTIONS.get(page, [])
    sel = [name for bit, name in opts if bit == 0 or (val & bit)]
    return ", ".join(sel) if sel else "(无)"

# 页面号 (tab_code, Maker UI 未显示; 商店分页, 0-5)
PAGE_NAMES = {0:"药品", 1:"道具", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
PAGE_VALUES = [f"{k}-{v}" for k,v in sorted(PAGE_NAMES.items())]

ITEM_REC = 64
ITEM_CNT = 600  # 游戏硬编码: sub_45343C(aTkitemDat, word_77CBCA, 38400)
FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ============================================================
# 字段定义 - 严格按 Maker UI 文案 + 反编译证据
# (键, 字节偏移, UI标签, 类型, 宽度, 反编译注释)
# ============================================================
# 顶部基础属性网格 (Maker UI 可见字段 22 条; 技能/状态在下方分组)
GRID_FIELDS = [
    ("item_id",      0, "物品代码",       'int',       W_INPUT, "物品唯一标识，全游戏查找主键 (v15[0])"),
    ("name_id",      4, "名称代码",       'tkt',       W_INPUT, "TKT 文本数据库 ID，用于物品显示名称 (v15[2])"),
    ("desc_id",      6, "说明代码",       'tkt',       W_INPUT, "TKT 文本数据库 ID，用于物品描述文本 (v15[3])"),
    ("icon",         8, "形象",           'icon',      W_INPUT, "背包/商店显示图标的精灵索引，实际值 +130 (v15[4])"),
    ("equip_type",  10, "使用权限",       'use_right', W_INPUT, "角色武器专精位掩码，控制谁可装备/使用此物品 (v15[5])"),

    ("tkkon_index", 12, "TKKon索引",       'int',       W_INPUT, "TKKon.dat 记录索引 (0-649). 战斗使用物品时: Item→TKKon→cond_id→TKAct动画 (v15[6])"),
    ("hp_inc",      14, "增加生命",       'int',       W_INPUT, "永久增加生命上限，≤1000固定值，>1000为百分比加成 (v15[7])"),
    ("hp_heal",     16, "恢复生命",       'int',       W_INPUT, "使用后回复当前 HP，≤1000固定值，>1000为百分比回复 (v15[8])"),
    ("mp_inc",      18, "增加内力",       'int',       W_INPUT, "永久增加内力上限，≤1000固定值，>1000为百分比加成 (v15[9])"),
    ("mp_heal",     20, "恢复内力",       'int',       W_INPUT, "使用后回复当前 MP，≤1000固定值，>1000为百分比回复 (v15[10])"),

    ("atk",         22, "增加攻击",       'int',       W_INPUT, "武力(STR)永久加成，同时增加基础值和当前值 (v15[11])"),
    ("def_",        24, "增加防御",       'int',       W_INPUT, "智力(INT)永久加成，同时增加基础值和当前值 (v15[12])"),
    ("hit",         26, "增加命中",       'int',       W_INPUT, "统御(CMD)永久加成，同时增加基础值和当前值 (v15[13])"),
    ("dodge",       28, "增加闪避",       'int',       W_INPUT, "敏捷(AGI)永久加成，同时增加基础值和当前值 (v15[14])"),
    ("spd",         30, "增加速度",       'int',       W_INPUT, "速度(SPD)永久加成，上限100 (v15[15])"),

    ("luk",         32, "增加幸运",       'int',       W_INPUT, "运气(LUK)永久加成，商店物品出现条件的基准值 (v15[16])"),
    ("spi",         34, "增加悟性",       'int',       W_INPUT, "精神(SPI)悟性永久加成 (v15[17])"),
    ("vit",         36, "增加移动",       'int',       W_INPUT, "体力(VIT)移动永久加成 (v15[18])"),
    ("jp_bonus",    38, "增加技能点",     'int',       W_INPUT, "技能点数(JP); sub_41E40C: word_757F46+=v15[19] 使用时增加; sub_41E248学习技能时消耗; sub_4189BC判定技能可用性。Maker.exe原标签'戒指判定'(误) (v15[19])"),
    ("combat_flag", 40, "战斗结算效果",   'combat_flag', W_INPUT, "战斗结算位掩码; sub_42234C: a2[33]|=v9[20]; 战斗结束后按位触发奖励效果 (v15[20])"),

    ("medicine",    50, "增加医术",       'int',       W_INPUT, "使用后获得的医术点数，累加到全局医术计数 (v15[25])"),
    ("price",       62, "价格",           'int',       W_INPUT, "物品买卖价格，商店卖出时折半 (v15[31])"),
]

# 技能组 (4 个字段; 全部对应全局技能等级表)
SKILL_FIELDS = [
    ("attach_skill",    42, "附加技能",         "装备后直接施加技能被动效果(属性加成等)，不写入技能栏 (v15[21])"),
    ("equip_learn",     44, "装备后学习技能",   "⚠ 仅升级已有技能(1-19→10级)，不会从零教会！未习得技能无效果 (v15[22])"),
    ("use_learn1",      46, "使用后学习技能1",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[23])"),
    ("use_learn2",      48, "使用后学习技能2",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[24])"),
]

# 导致状态 (装备/命中时让目标进入异常状态; 干將莫邪[26]=0x03=破兵+碎甲; 紅顏知己[27]=0x1000=迷恋)
CAUSE_MASK_FIELDS = [
    ("cause_mask1", 52, "导致状态 1-16",  "装备/命中时让目标进入的状态位掩码，每位对应状态表第 i 项 (v15[26])"),
    ("cause_mask2", 54, "导致状态 17-32", "装备/命中时让目标进入的状态位掩码，每位对应状态表第 16+i 项 (v15[27])"),
]

# 解除状态 (使用物品时按位清除角色异常状态)
CURE_MASK_FIELDS = [
    ("cure_mask1", 56, "解除状态 1-16",  "使用物品时解除的状态位掩码，每位对应状态表第 i 项 (v15[28])"),
    ("cure_mask2", 58, "解除状态 17-32", "使用物品时解除的状态位掩码，每位对应状态表第 16+i 项 (v15[29])"),
]

# 隐含字段 (TKItem 记录占用但 Maker UI 未显示，读写透传保留原始数据)
HIDDEN_FIELDS = [
    ("tab_code",     2, "页面号",       'page', W_INPUT, "物品在商店中的分页编号 (0=药品,1=道具,2=武器,3=防具,4=饰品,5=特殊)"),
    ("extra_flags", 60, "额外标志",     'extra_flags', W_INPUT, "地图/战斗全局标志(sub_41F784 OR到dword_755C80) (v15[30])"),
]

ALL_FIELDS = (GRID_FIELDS + HIDDEN_FIELDS +
              [(k,o,l,'skill',W_INPUT,c) for k,o,l,c in SKILL_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CAUSE_MASK_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CURE_MASK_FIELDS])

# ============================================================
# 空槽/显示名辅助
# ============================================================
def is_empty_item(rec, tkt=None):
    """严格空槽: item_id in (0,1) 或 name_id<=0 或 tkt 中无对应名称.
    - #560-#599 真空槽: id=0 & name_id=0 (可新增物品复用)
    - id=1 占位: 约 225 条游戏保留记录 (#550-559 等)
    - 无 TKT 名: 孤立记录, 无法显示
    """
    if rec.get('item_id', 0) in (0, 1):
        return True
    if rec.get('name_id', 0) <= 0:
        return True
    if tkt is not None:
        nm = tkt.get(rec['name_id'], "")
        if not nm or not nm.strip():
            return True
    return False

def is_pure_empty_slot(rec):
    """真·空槽 (可作新增物品起始模板): item_id==0 AND name_id==0."""
    return rec.get('item_id', 0) == 0 and rec.get('name_id', 0) == 0

def item_display_name(rec, tkt):
    if is_empty_item(rec, tkt):
        return f"(空槽 #{rec['index']})"
    nid = rec['name_id']
    if nid > 0 and nid in tkt:
        return tkt[nid]
    return f"ID#{rec['item_id']}"

# ============================================================
# 数据加载/保存
# ============================================================
def load_items(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % ITEM_REC == 0 and (len(dec) == 0 or len(dec) % ITEM_REC != 0):
        dec = raw
    recs = []
    for i in range(ITEM_CNT):
        off = i * ITEM_REC
        if off + ITEM_REC > len(dec):
            break
        fields = struct.unpack_from('<' + 'h'*32, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_items(fp, recs):
    buf = bytearray(ITEM_CNT * ITEM_REC)
    # 空槽模板 (#560-#599 原始值: name_id=0, desc_id=600) 在保存时保持 desc_id=600
    for rec in recs[:ITEM_CNT]:
        i = rec['index']
        off = i * ITEM_REC
        for k, fo, _, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True


# ============================================================
# GUI
# ============================================================
class ItemEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKItem.dat 可视化编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1360x860")
        self.root.minsize(1120, 700)
        self.item_path = self.tkt_path = self.skill_path = self.mu_path = None
        self.records = []
        self.tkt = {}
        self.tkt_full = {}
        self.skill_names = {}
        self._mu_sprites = []
        self._icon_photos = {}  # 图标缓存 (idx -> PhotoImage)
        self.filtered_indices = []
        self._dirty = False
        self.filter_page = tk.StringVar(value="全部页面")
        self.filter_right = tk.StringVar(value="全部权限")
        self.filter_empty = tk.BooleanVar(value=True)
        self._build_ui()
        self._set_edit_enabled(False)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1360) // 2
        y = (sh - 860) // 2
        self.root.geometry(f'1360x860+{x}+{y}')

    # ----------- UI 构建 -----------
    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新建物品 (填充空槽)", command=self._new_item, accelerator="Ctrl+N")
        em.add_command(label="复制当前到空槽", command=self._copy_record)
        em.add_command(label="清空当前记录", command=self._clear_current)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段来源 (逆向+Maker)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_item())

        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=18)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(tb, text="页面号:").pack(side=tk.LEFT)
        ttk.Combobox(tb, textvariable=self.filter_page, values=["全部页面"]+PAGE_VALUES,
                     state='readonly', width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(tb, text="权限:").pack(side=tk.LEFT, padx=(6,0))
        self.filter_right_cb = ttk.Combobox(tb, textvariable=self.filter_right, values=["全部权限"],
                                            state='readonly', width=16)
        self.filter_right_cb.pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(tb, text="仅非空", variable=self.filter_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=6)
        self.filter_page.trace_add('write', lambda *a: self._apply_filter())
        self.filter_right.trace_add('write', lambda *a: self._apply_filter())
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="新建物品", command=self._new_item).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左表 (tree headings 模式以支持 #0 列显示图标)
        lf = ttk.Frame(paned)
        paned.add(lf, weight=2)
        cols = ('index','item_id','page','name','right','price')
        self.tree = ttk.Treeview(lf, columns=cols, show='tree headings', selectmode='browse')
        self.tree.column('#0', width=36, minwidth=36, stretch=False, anchor='center')
        self.tree.heading('#0', text='')
        cc = [('index','#',38),('item_id','ID',42),('page','页面',48),
              ('name','物品名称',100),('right','权限',82),('price','价格',48)]
        for cid,cn,cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self._tree_photos = []  # 防止 GC

        # 右编辑
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0,4), padx=4)

        # middle: 编辑区容器, 左侧放 canvas+按钮栏, 右侧放滚动条
        middle = ttk.Frame(rf)
        middle.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(middle)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(middle, orient=tk.VERTICAL)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 按钮栏 — 固定在 left_col 底部, 不参与滚动
        bf = ttk.Frame(left_col)
        bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2,0))
        ttk.Button(bf, text="清空此记录", command=self._clear_current, width=12).pack(side=tk.RIGHT)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit, width=12).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="复制到空槽", command=self._copy_record, width=12).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)

        canvas = tk.Canvas(left_col, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self._canvas_win = canvas.create_window((0,0), window=self.edit_inner, anchor='nw')
        # edit_inner 宽度通过 column minsize 强制跟随 canvas, 高度由内容自然撑开
        canvas.bind('<Configure>', lambda e: self.edit_inner.columnconfigure(0, minsize=e.width))
        canvas.configure(yscrollcommand=sb.set)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}
        self._edit_extras = {}

        # 文本预览
        pv_lf = ttk.LabelFrame(self.edit_inner, text="物品预览", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        for c in range(1, 5):
            pv_lf.columnconfigure(c, weight=1)
        LBL_CLR = '#666'  # 统一标签颜色
        # 名称 + 图标
        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground=LBL_CLR).grid(
            row=0, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=620, justify='left')
        self.preview_name.grid(row=0, column=1, columnspan=3, sticky='ew', pady=1)
        self.preview_icon = ttk.Label(pv_lf, text="")
        self.preview_icon.grid(row=0, column=4, sticky='e', padx=(0,4), pady=1)
        # 说明 (多行, 去除白色背景)
        self.preview_desc = tk.Text(pv_lf, height=4, width=60, font=FONT,
                                     foreground='#228B22', wrap='word',
                                     relief='flat', borderwidth=0,
                                     state='disabled', bg=self.root.cget('bg'))
        ttk.Label(pv_lf, text="说明:", font=FONT_S, foreground=LBL_CLR).grid(
            row=1, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_desc.grid(row=1, column=1, columnspan=4, sticky='ew', pady=1)
        # 技能预览 (一行四列, col 0=附加技能 左对齐标签)
        self._preview_skills = []
        skill_labels = ["附加技能", "装备后学习", "使用后学习1", "使用后学习2"]
        for ci, slbl in enumerate(skill_labels):
            col = 1+ci
            if ci == 0:
                # 第一列: col 0 放标签, col 1 放值
                ttk.Label(pv_lf, text=f"{slbl}:", font=FONT_S, foreground=LBL_CLR).grid(
                    row=2, column=0, sticky='nw', padx=(2,4), pady=1)
                lbl = ttk.Label(pv_lf, text="—", foreground='#228B22',
                               font=FONT, wraplength=170, justify='left')
                lbl.grid(row=2, column=1, sticky='ew', padx=2, pady=1)
            else:
                # 其余列: 标签+值放在同一列
                frm = ttk.Frame(pv_lf)
                frm.grid(row=2, column=col, sticky='ew', padx=2, pady=1)
                ttk.Label(frm, text=f"{slbl}:", font=FONT_S, foreground=LBL_CLR).pack(side=tk.LEFT)
                lbl = ttk.Label(frm, text="—", foreground='#228B22', font=FONT, wraplength=120)
                lbl.pack(side=tk.LEFT, padx=(2,0))
            self._preview_skills.append(lbl)
        # 状态预览 (一行四列, col 0=导致状态 1-16 左对齐标签)
        self._preview_statuses = []
        status_labels = ["导致状态 1-16", "导致状态 17-32", "解除状态 1-16", "解除状态 17-32"]
        status_val_colors = ['#CC3333', '#CC3333', '#3366cc', '#3366cc']
        for ci, (slbl, sc) in enumerate(zip(status_labels, status_val_colors)):
            if ci == 0:
                ttk.Label(pv_lf, text=f"{slbl}:", font=FONT_S, foreground=LBL_CLR).grid(
                    row=3, column=0, sticky='nw', padx=(2,4), pady=1)
                val_frame = ttk.Frame(pv_lf)
                val_frame.grid(row=3, column=1, sticky='w', padx=2, pady=1)
            else:
                outer = ttk.Frame(pv_lf)
                outer.grid(row=3, column=1+ci, sticky='w', padx=2, pady=1)
                ttk.Label(outer, text=f"{slbl}:", font=FONT_S, foreground=LBL_CLR).pack(side=tk.LEFT)
                val_frame = ttk.Frame(outer)
                val_frame.pack(side=tk.LEFT, padx=(2,0))
            val_frame._val_color = sc
            self._preview_statuses.append(val_frame)

        # 基础属性网格
        grid_lf = ttk.LabelFrame(self.edit_inner, text="基础属性", padding=4)
        grid_lf.grid(row=1, column=0, sticky='ew', padx=2, pady=2)
        COLS = 5
        for fi, (fn, fo, fl, ft, fw, cmt) in enumerate(GRID_FIELDS):
            row, col = fi // COLS, fi % COLS
            self._build_field(grid_lf, row, col, fn, fo, fl, ft, fw, cmt)

        # 技能组 (4 字段)
        sk_lf = ttk.LabelFrame(self.edit_inner,
                                text="技能", padding=4)
        sk_lf.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        for si, (fn, fo, fl, cmt) in enumerate(SKILL_FIELDS):
            self._build_field(sk_lf, 0, si, fn, fo, fl, 'skill', W_INPUT, cmt)

        # 状态组
        st_lf = ttk.LabelFrame(self.edit_inner,
                                text="状态位掩码 (导致/解除)", padding=4)
        st_lf.grid(row=3, column=0, sticky='ew', padx=2, pady=2)
        for ci, (fn, fo, fl, cmt) in enumerate(CAUSE_MASK_FIELDS):
            self._build_field(st_lf, 0, ci, fn, fo, fl, 'mask', W_INPUT, cmt)
        for ci, (fn, fo, fl, cmt) in enumerate(CURE_MASK_FIELDS):
            self._build_field(st_lf, 0, 2+ci, fn, fo, fl, 'mask', W_INPUT, cmt)

        # 隐含字段
        hd_lf = ttk.LabelFrame(self.edit_inner,
                                text="隐含数据 (保留原始数据)", padding=4)
        hd_lf.grid(row=4, column=0, sticky='ew', padx=2, pady=2)
        for hi, (fn, fo, fl, ft, fw, cmt) in enumerate(HIDDEN_FIELDS):
            self._build_field(hd_lf, 0, hi, fn, fo, fl, ft, fw, cmt)

        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_item = ttk.Label(pf, text="", foreground="gray")
        self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray")
        self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field(self, parent, row, col, fn, fo, fl, ft, fw, cmt):
        frm = ttk.Frame(parent)
        frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=fl, font=FONT_S)
        lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        if ft == 'page':
            cb = ttk.Combobox(frm, state='readonly', values=PAGE_VALUES,
                              width=W_INPUT, font=FONT)
            cb.pack(fill=tk.X)
            self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'use_right':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_use_right(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666',
                                               font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'tkt':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_tkt(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = None
        elif ft == 'skill':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_skill(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#228B22',
                                              font=FONT_S, wraplength=160)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'mask':
            is_cause = fn.startswith('cause_')
            btn_text = "选择导致状态…" if is_cause else "选择解除状态…"
            color = '#CC3333' if is_cause else '#3366cc'
            ttk.Button(frm, text=btn_text, width=W_INPUT+3,
                       command=lambda f=fn: self._pick_status(f)).pack(fill=tk.X)
            extras = ttk.Frame(frm)
            extras.pack(anchor=tk.W, fill=tk.X)
            self._edit_extras[fn] = (extras, ttk.Label(extras, text="(无)", foreground=color,
                                                        font=FONT_S, wraplength=180))
            self._edit_extras[fn][1].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'combat_flag':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_combat_flags(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666', font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'extra_flags':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_extra_flags(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666', font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'icon':
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_icon(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", font=FONT_S)
            self._edit_extras[fn].pack(anchor=tk.W)
        else:
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ttk.Entry(frm, textvariable=ev, width=W_INPUT, font=FONT).pack(fill=tk.X)

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
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=420, padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None
        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _bind_mousewheel(self, canvas):
        def _mw(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ----------- 数据加载 -----------
    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return
        it = os.path.join(d, "TKItem.dat")
        tk_ = os.path.join(d, "TKT.dat")
        sk = os.path.join(d, "TKSkill.dat")
        if not os.path.exists(it):
            messagebox.showwarning("文件缺失","未找到 TKItem.dat")
            return
        self.item_path = it
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.skill_path = sk if os.path.exists(sk) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        if not os.path.exists(self.mu_path):
            self.mu_path = None
        self._reload()

    def _reload(self):
        if not self.item_path:
            return
        self.status_var.set("加载中…")
        self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        else:
            self.tkt_full = {}
        if self.skill_path:
            self.skill_names = load_tkskill_names(self.skill_path, self.tkt)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_photos.clear()
        try:
            self.records = load_items(self.item_path)
            self._dirty = False
            self.status_var.set(f"{len(self.records)} 条 | TKT {len(self.tkt)} 条 | 技能 {len(self.skill_names)} 条")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children():
            self._set_ws(c, en)
    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except:
            pass
        for c in w.winfo_children():
            self._set_ws(c, en)

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p):
            if not p:
                lb.config(text="(未加载)", foreground=r)
            elif not os.path.exists(p):
                lb.config(text=f"(不存在){p}", foreground=r)
            else:
                lb.config(text=p, foreground=g)
        _f(self.lbl_item, self.item_path)
        _f(self.lbl_tkt, self.tkt_path)
        _f(self.lbl_skill, self.skill_path)

    # ----------- 筛选/列表 -----------
    def _update_right_options(self, page_filter_value):
        """根据页面筛选值动态填充权限下拉框选项"""
        if page_filter_value.startswith("全部"):
            # 全部页面: 收集所有唯一选项
            seen = set()
            all_opts = []
            for page in sorted(USE_RIGHT_OPTIONS):
                for bit, name in USE_RIGHT_OPTIONS[page]:
                    key = (bit, name)
                    if key not in seen:
                        seen.add(key)
                        all_opts.append(f"{bit}-{name}")
        else:
            page = int(page_filter_value.split('-')[0])
            opts = USE_RIGHT_OPTIONS.get(page, [])
            all_opts = [f"{bit}-{name}" for bit, name in opts]
        new_vals = ["全部权限"] + all_opts
        current_vals = list(self.filter_right_cb['values'])
        if new_vals != current_vals:
            self.filter_right_cb['values'] = new_vals
            self._guard_right_reset = True
            self.filter_right.set("全部权限")
            self._guard_right_reset = False

    def _apply_filter(self, *_):
        if getattr(self, '_guard_right_reset', False):
            return
        q = self.sv.get().strip().lower()
        self.filtered_indices = []
        self._update_right_options(self.filter_page.get())
        fpg = self.filter_page.get()
        frg = self.filter_right.get()
        for rec in self.records:
            if self.filter_empty.get() and is_empty_item(rec, self.tkt):
                continue
            if fpg and not fpg.startswith("全部"):
                if rec['tab_code'] != int(fpg.split('-')[0]):
                    continue
            if frg and not frg.startswith("全部"):
                bit = int(frg.split('-')[0])
                if bit == 0:
                    if rec['equip_type'] != 0:
                        continue
                else:
                    if (rec['equip_type'] & bit) == 0:
                        continue
            if q:
                nm = item_display_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['item_id']} {rec['tab_code']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        empty_cnt = sum(1 for r in self.records if is_pure_empty_slot(r))
        self.status_var.set(
            f"显示 {len(self.filtered_indices)}/{len(self.records)} | 真空槽剩余 {empty_cnt}/40 | Ctrl+S 保存")

    def _clear_filter(self):
        self.sv.set("")
        self.filter_page.set("全部页面")
        self.filter_right.set("全部权限")
        self.filter_empty.set(True)
        self._apply_filter()

    def _refresh_table(self):
        self._tree_photos.clear()
        for it in self.tree.get_children():
            self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            et = r['equip_type']
            rt = _use_right_label(et, r.get('tab_code', 0)) if et or et == 0 else "—"
            photo = self._get_icon_photo(r['icon'], (24,24))
            self._tree_photos.append(photo)
            self.tree.insert('', 'end', image=photo if photo else '',
                           values=(
                r['index'], r['item_id'],
                PAGE_NAMES.get(r['tab_code'], '?'),
                item_display_name(r, self.tkt),
                rt, r['price']))

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        km = {'item_id':'item_id', 'page':'tab_code', 'price':'price', 'right':'equip_type'}
        self.filtered_indices.sort(key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=rev)
        self._sort_reverse = not rev
        self._refresh_table()

    # ----------- 编辑 -----------
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        self.lbl_rec_idx.config(text=(
            f"记录 #{rec['index']}   物品代码={rec['item_id']}   "
            f"页面号={PAGE_NAMES.get(rec['tab_code'],'?')}   "
            f"名称={item_display_name(rec, self.tkt)}"
        ))
        nid = rec.get('name_id', 0) or 0
        did = rec.get('desc_id', 0) or 0
        # 名称 — 使用 tkt (首行)
        n_txt = self.tkt.get(int(nid), "") if nid > 0 else ""
        self.preview_name.config(text=n_txt if n_txt else "(无 / TKT 未提供)")
        # 说明 — 使用 tkt_full (完整多行文本)
        d_txt = self.tkt_full.get(int(did), "") if did > 0 else ""
        self.preview_desc.configure(state='normal')
        self.preview_desc.delete('1.0', 'end')
        self.preview_desc.insert('1.0', d_txt if d_txt else "(无 / TKT 未提供)")
        self.preview_desc.configure(state='disabled')
        # 技能预览 (一行四列)
        skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
        for si, sk in enumerate(skill_keys):
            sid = int(rec.get(sk, 0)) if rec.get(sk, 0) else -1
            if sid > 0:
                nm = self.skill_names.get(sid, f"技能#{sid}")
                self._preview_skills[si].config(text=nm)
            else:
                self._preview_skills[si].config(text="—")
        # 状态预览 (一行四列)
        status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
        for si, sk in enumerate(status_keys):
            mask = int(rec.get(sk, 0)) if rec.get(sk, 0) else 0
            base = 0 if sk.endswith('_mask1') else 16
            sel = []
            for i in range(16):
                if mask & (1 << i) and base + i < len(STATUS_NAMES):
                    sel.append((base + i, STATUS_NAMES[base + i]))
            self._update_preview_status(si, sel)

        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            val = rec[fn]
            sv = str(val)
            self._edit_vars[fn].set(sv)
            if ft == 'page':
                cb = self._edit_extras[fn]
                if not self._set_combobox(cb, val):
                    cb.set(sv)
            elif ft == 'use_right':
                page = rec.get('tab_code', 0)
                self._edit_extras[fn].config(text=_use_right_label(int(val) if val else 0, page))
            elif ft == 'combat_flag':
                self._update_combat_flags_label(fn, int(val) if val else 0)
            elif ft == 'tkt':
                pass
            elif ft == 'skill':
                sid = int(val) if val else -1
                nm = self.skill_names.get(sid, "(无)")
                self._edit_extras[fn].config(text=nm[:30] if sid > 0 else "(无)")
            elif ft == 'mask':
                self._update_status_label(fn, int(val) if val else 0)
            elif ft == 'extra_flags':
                self._update_extra_flags_label(fn, int(val) if val else 0)
            elif ft == 'icon':
                ival = int(val) if val else 0
                self._update_icon_preview(ival)

    def _set_combobox(self, cb, val):
        for i, t in enumerate(cb['values']):
            if t.startswith(f"{val}-"):
                cb.current(i)
                return True
        return False

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append((base + i, STATUS_NAMES[base + i]))
        extras_frame, txt_lbl = self._edit_extras[fn]
        for w in extras_frame.winfo_children():
            if w != txt_lbl:
                w.destroy()
        if sel:
            txt_lbl.config(text="")
            txt_lbl.pack_forget()
            COLS = 3  # 每行最多3个状态
            for si, (idx, nm) in enumerate(sel):
                row, col = divmod(si, COLS)
                cell = ttk.Frame(extras_frame)
                cell.grid(row=row, column=col, sticky='w', padx=(0, 6), pady=1)
                nl = ttk.Label(cell, text=nm, foreground=txt_lbl.cget('foreground'), font=FONT_S)
                nl.pack(side=tk.LEFT)
                photo = self._get_icon_photo(STATUS_ICON_BASE + idx - 130, (18,18))
                if photo:
                    il = ttk.Label(cell, image=photo)
                    il.image = photo
                    il.pack(side=tk.LEFT, padx=(1,0))
        else:
            txt_lbl.config(text="(无)")
            txt_lbl.pack(anchor=tk.W)
        # 同步更新预览区状态
        status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
        if fn in status_keys:
            si = status_keys.index(fn)
            self._update_preview_status(si, sel)

    def _center_dialog(self, dlg, w, h):
        """将弹窗定位到主窗口中心（先隐藏避免闪烁）"""
        dlg.withdraw()
        dlg.geometry(f"{w}x{h}")
        dlg.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()

    # ----------- 图标 -----------
    def _get_icon_photo(self, icon_val, size=(48,48)):
        """获取图标的 PhotoImage (缓存), icon_val 为游戏原始值 (实际显示值 +130)"""
        if not self._mu_sprites:
            return None
        idx = icon_val + 130
        if idx < 0 or idx >= len(self._mu_sprites):
            return None
        cache_key = (idx, size)
        if cache_key in self._icon_photos:
            return self._icon_photos[cache_key]
        try:
            from PIL import Image, ImageTk
            img = self._mu_sprites[idx].resize(size, Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self._icon_photos[cache_key] = photo
            return photo
        except Exception:
            return None

    def _pick_icon(self, fn):
        """弹窗选择物品图标"""
        if not self._mu_sprites:
            messagebox.showinfo("提示", "未加载 Mu.JVG 图标文件")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("选择图标 (索引 = 游戏值 + 130)")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 780, 560)
        dlg.grid_rowconfigure(0, weight=1)
        dlg.grid_columnconfigure(0, weight=1)
        dlg.resizable(True, True)
        cur_val = int(self._edit_vars[fn].get() or 0)
        cvs = tk.Canvas(dlg, highlightthickness=0)
        sb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=cvs.yview)
        grid_frame = ttk.Frame(cvs)
        cvs.create_window((0,0), window=grid_frame, anchor='nw')
        cvs.configure(yscrollcommand=sb.set)
        cvs.grid(row=0, column=0, sticky='nsew', padx=4, pady=(4,0))
        sb.grid(row=0, column=1, sticky='ns', pady=(4,0))
        def _mw(e):
            cvs.yview_scroll(int(-1*(e.delta/120)), "units")
        cvs.bind("<Enter>", lambda e: cvs.bind_all("<MouseWheel>", _mw))
        cvs.bind("<Leave>", lambda e: cvs.unbind_all("<MouseWheel>"))
        bf = ttk.Frame(dlg, padding=4)
        bf.grid(row=1, column=0, columnspan=2, sticky='ew')
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Label(bf, text="点击图标选择，索引 = 游戏精灵索引 - 130", foreground='#666', font=FONT_S).pack(side=tk.LEFT, padx=4)

        # 响应式图标网格
        CELL_W = 46
        _last_cols = [0]
        def _build_grid(cols=None):
            if cols is None:
                cols = max(5, (cvs.winfo_width() - 4) // CELL_W)
                if cols <= 0:
                    cols = 10
            if cols == _last_cols[0]:
                return
            _last_cols[0] = cols
            for w in grid_frame.winfo_children():
                w.destroy()
            photo_refs = []
            for si in range(len(self._mu_sprites)):
                game_idx = si - 130
                row, col = divmod(si, cols)
                frm = ttk.Frame(grid_frame)
                frm.grid(row=row, column=col, padx=1, pady=1)
                photo = self._get_icon_photo(game_idx, (40,40))
                if game_idx == cur_val:
                    frm.configure(relief='solid', borderwidth=2)
                    ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=1)
                if photo:
                    photo_refs.append(photo)
                    lbl = ttk.Label(frm, image=photo)
                else:
                    lbl = ttk.Label(frm, text=str(game_idx), font=FONT_S, width=5)
                lbl.pack()
                ttk.Label(frm, text=str(game_idx), font=('', 7)).pack()
                frm.bind('<Button-1>', lambda e, v=game_idx: (
                    self._edit_vars[fn].set(str(v)),
                    self._update_icon_preview(v), dlg.destroy()))
                lbl.bind('<Button-1>', lambda e, v=game_idx: (
                    self._edit_vars[fn].set(str(v)),
                    self._update_icon_preview(v), dlg.destroy()))
            grid_frame.update_idletasks()
            cvs.configure(scrollregion=cvs.bbox('all'))
            # 滚动到选中位置
            if cur_val >= -130:
                si = cur_val + 130
                row_h = grid_frame.winfo_children()[0].winfo_reqheight() + 2 if grid_frame.winfo_children() else 52
                y = (si // cols) * row_h
                total_h = cvs.bbox('all')[3] if cvs.bbox('all') else 1
                cvs.yview_moveto(min(1.0, max(0, y - 100) / total_h))

        cvs.bind('<Configure>', lambda e: _build_grid(), add='+')
        dlg.after(100, _build_grid)
        dlg.wait_window()

    def _update_icon_preview(self, icon_val):
        """更新预览区的图标"""
        photo = self._get_icon_photo(icon_val, (40,40))
        if photo:
            self.preview_icon.configure(image=photo, text="")
            self.preview_icon.image = photo
        else:
            self.preview_icon.configure(image="", text=f"[图标 {icon_val}]")

    def _pick_extra_flags(self, fn):
        """弹窗选择额外标志位"""
        dlg = tk.Toplevel(self.root)
        dlg.title("选择额外标志 (位掩码)")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 400, 280)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        wrap = ttk.Frame(dlg, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)
        vars_ = []
        for bit, name, desc in EXTRA_FLAG_BITS:
            v = tk.BooleanVar(value=bool(cur_val & (1 << bit)))
            row = ttk.Frame(wrap)
            row.pack(anchor=tk.W, fill=tk.X, pady=1)
            ttk.Checkbutton(row, text=f"bit{bit} {name}", variable=v).pack(side=tk.LEFT)
            ttk.Label(row, text=desc, foreground='#999', font=('', 7)).pack(side=tk.LEFT, padx=(8,0))
            vars_.append((bit, v))
        bf = ttk.Frame(dlg, padding=4)
        bf.pack(side=tk.BOTTOM, fill=tk.X)
        def _ok():
            m = 0
            for bit, v in vars_:
                if v.get():
                    m |= (1 << bit)
            if m >= 0x8000:
                m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_extra_flags_label(fn, m)
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for _, v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_extra_flags_label(self, fn, val):
        """更新额外标志的标签显示"""
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in EXTRA_FLAG_BITS if mask & (1 << bit)]
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _pick_combat_flags(self, fn):
        """弹窗选择战斗结算效果 (位掩码多选)"""
        dlg = tk.Toplevel(self.root)
        dlg.title("选择战斗结算效果 (位掩码)")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 420, 210)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        wrap = ttk.Frame(dlg, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)
        vars_ = []
        for bit, name, desc in COMBAT_FLAG_BITS:
            v = tk.BooleanVar(value=bool(cur_val & bit))
            row = ttk.Frame(wrap)
            row.pack(anchor=tk.W, fill=tk.X, pady=1)
            ttk.Checkbutton(row, text=name, variable=v).pack(side=tk.LEFT)
            ttk.Label(row, text=desc, foreground='#999', font=('', 7)).pack(side=tk.LEFT, padx=(8, 0))
            vars_.append((bit, v))
        bf = ttk.Frame(dlg, padding=4)
        bf.pack(side=tk.BOTTOM, fill=tk.X)
        def _ok():
            m = 0
            for bit, v in vars_:
                if v.get():
                    m |= bit
            if m >= 0x8000:
                m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_combat_flags_label(fn, m)
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for _, v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_combat_flags_label(self, fn, val):
        """更新战斗结算效果的标签显示"""
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in COMBAT_FLAG_BITS if mask & bit]
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _pick_use_right(self, fn):
        """弹窗选择使用权限 (根据当前页面号动态切换选项)"""
        if not self.records:
            return
        page = self.records[self._editing_idx].get('tab_code', 0)
        opts = USE_RIGHT_OPTIONS.get(page, [])
        # 仅有一个值为0的选项时，直接设为0
        if len(opts) == 1 and opts[0][0] == 0:
            self._edit_vars[fn].set("0")
            self._edit_extras[fn].config(text=_use_right_label(0, page))
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("选择使用权限 (多选位掩码)")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 320, 60 + max(len(opts), 2) * 28)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        wrap = ttk.Frame(dlg, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)
        vars_ = []
        for bit, name in opts:
            v = tk.BooleanVar(value=bool(cur_val & bit))
            row = ttk.Frame(wrap)
            row.pack(anchor=tk.W, fill=tk.X, pady=1)
            ttk.Checkbutton(row, text=f"{bit}-{name}" if bit != 0 else name, variable=v).pack(side=tk.LEFT)
            vars_.append((bit, v))
        bf = ttk.Frame(dlg, padding=4)
        bf.pack(side=tk.BOTTOM, fill=tk.X)
        def _ok():
            m = 0
            for bit, v in vars_:
                if v.get():
                    m += bit
            if m >= 0x8000:
                m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._edit_extras[fn].config(text=_use_right_label(m, page))
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for _, v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_preview_status(self, si, sel):
        """更新预览区中单个状态列 (含图标, 每行最多3个)"""
        frame = self._preview_statuses[si]
        for w in frame.winfo_children():
            w.destroy()
        COLS = 3
        for i, (idx, nm) in enumerate(sel):
            row, col = divmod(i, COLS)
            cell = ttk.Frame(frame)
            cell.grid(row=row, column=col, sticky='w', padx=(0, 4))
            photo = self._get_icon_photo(STATUS_ICON_BASE + idx - 130, (16,16))
            if photo:
                il = ttk.Label(cell, image=photo)
                il.image = photo
                il.pack(side=tk.LEFT)
            ttk.Label(cell, text=nm, font=('', 7),
                     foreground=frame._val_color).pack(side=tk.LEFT)

    # ----------- 弹窗: 状态 mask 多选 -----------
    def _pick_status(self, fn):
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 360, 520)
        base = 0 if fn.endswith('_mask1') else 16
        cur_mask = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        vars_ = []
        wrap = ttk.Frame(dlg, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES):
                break
            row_frm = ttk.Frame(wrap)
            row_frm.pack(anchor=tk.W, fill=tk.X, pady=1)
            photo = self._get_icon_photo(STATUS_ICON_BASE + idx - 130, (20,20))
            if photo:
                ttk.Label(row_frm, image=photo).pack(side=tk.LEFT, padx=(0,4))
            v = tk.BooleanVar(value=bool(cur_mask & (1 << i)))
            ttk.Checkbutton(row_frm, text=f"{idx}. {STATUS_NAMES[idx]}",
                             variable=v).pack(side=tk.LEFT)
            vars_.append(v)
        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            m = 0
            for i, v in enumerate(vars_):
                if v.get():
                    m |= (1 << i)
            # 转回有符号 int16
            if m >= 0x8000:
                m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_status_label(fn, m & 0xFFFF)
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 弹窗: TKT -----------
    def _pick_tkt(self, fn):
        dlg = tk.Toplevel(self.root)
        dlg.title("选择 TKT 文本")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 520, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)  # 当前选中值
        sf = ttk.Frame(dlg, padding=5)
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg)
        lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('id','text'), show='headings', selectmode='browse', height=22)
        tree.heading('id', text='ID')
        tree.heading('text', text='文本')
        tree.column('id', width=60, anchor='center')
        tree.column('text', width=420, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        _tkt_items = sorted(self.tkt.items(), key=lambda x: x[0])
        def _refresh(q=""):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for eid, txt in _tkt_items:
                if ql and ql not in txt.lower():
                    continue
                iid = tree.insert('', 'end', values=(eid, txt[:80]))
                if eid == cur_val:
                    tree.selection_set(iid)
                    tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                try:
                    tid = int(v[0])
                    if fn == 'name_id':
                        txt = self.tkt.get(tid, "")
                        self.preview_name.config(text=txt if txt else "(无 / TKT 未提供)")
                    elif fn == 'desc_id':
                        txt = self.tkt_full.get(tid, "")
                        self.preview_desc.configure(state='normal')
                        self.preview_desc.delete('1.0', 'end')
                        self.preview_desc.insert('1.0', txt if txt else "(无 / TKT 未提供)")
                        self.preview_desc.configure(state='disabled')
                except Exception:
                    pass
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 弹窗: 技能 -----------
    def _pick_skill(self, fn):
        dlg = tk.Toplevel(self.root)
        dlg.title("选择技能")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 460, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)  # 当前选中值
        sf = ttk.Frame(dlg, padding=5)
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg)
        lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('idx','name'), show='headings', selectmode='browse', height=22)
        tree.heading('idx', text='索引')
        tree.heading('name', text='技能名称')
        tree.column('idx', width=50, anchor='center')
        tree.column('name', width=380, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        _skill_items = sorted(self.skill_names.items(), key=lambda x: x[0])
        def _refresh(q=""):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for idx, nm in _skill_items:
                if ql and ql not in nm.lower():
                    continue
                iid = tree.insert('', 'end', values=(idx, nm[:60]))
                if idx == cur_val:
                    tree.selection_set(iid)
                    tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                self._edit_extras[fn].config(text=str(v[1])[:30])
                # 同步更新文本预览中的技能标签
                skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
                if fn in skill_keys:
                    self._preview_skills[skill_keys.index(fn)].config(text=str(v[1]))
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 编辑应用 -----------
    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'):
            return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            try:
                if ft == 'page':
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
                else:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767:
                        v = 32767
                    if v < -32768:
                        v = -32768
                    rec[fn] = v
            except ValueError:
                rec[fn] = 0
        self._dirty = True
        self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    def _clear_current(self):
        """把当前选中记录清为空槽模板 (恢复 #560-599 原始值)."""
        if not hasattr(self, '_editing_idx'):
            messagebox.showinfo("提示", "请先选择一条记录")
            return
        if not messagebox.askyesno("确认清空",
            f"将记录 #{self._editing_idx} 清为空槽模板 (item_id=0, name_id=0, desc_id=600).\n确定?"):
            return
        rec = self.records[self._editing_idx]
        for fn, _, _, _, _, _ in ALL_FIELDS:
            rec[fn] = 0
        rec['desc_id'] = 600  # 空槽模板的默认 desc_id
        self._dirty = True
        self._apply_filter()
        self._populate_edit(rec)
        self.status_var.set(f"记录 #{self._editing_idx} 已清空")

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'):
            messagebox.showinfo("提示", "请先选择一条记录")
            return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_pure_empty_slot(rec):
                for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
                    rec[fn] = src[fn]
                rec['index'] = i
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == i:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self.status_var.set(f"已复制到空槽 #{i}")
                return
        messagebox.showwarning("已满", "无真·空槽 (id=0 的记录) 可复制到.\n可先使用『清空此记录』释放一个槽位.")

    def _new_item(self):
        """新增物品: 在空槽 #560-#599 中找第一条 item_id=0 的记录, 填入默认值并选中.
        游戏硬编码限制 600 条, 无法扩容; 但 #560-#599 40 条空槽可用.
        """
        if not self.records:
            messagebox.showinfo("提示", "请先加载 TKItem.dat")
            return
        target = None
        for rec in self.records:
            if is_pure_empty_slot(rec):
                target = rec
                break
        if target is None:
            messagebox.showwarning("已满",
                "600 条记录上限已满 (sub_45343C 硬编码 38400 字节)\n"
                "无真·空槽 (id=0) 可用. 可使用『清空此记录』释放一个旧记录."
            )
            return
        # 填入默认值 (参考 #560-599 原始模板)
        for fn, _, _, _, _, _ in ALL_FIELDS:
            target[fn] = 0
        # 估算一个未占用的 item_id (避免碰撞)
        used_ids = {r['item_id'] for r in self.records if r['item_id'] > 0}
        new_id = 600
        while new_id in used_ids and new_id < 9999:
            new_id += 1
        target['item_id'] = new_id
        target['desc_id'] = 600  # 模板默认
        target['price'] = 1
        target['tab_code'] = 0
        self._dirty = True
        self._apply_filter()
        # 选中新记录
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == target['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self._populate_edit(target)
        messagebox.showinfo("新建物品",
            f"已在空槽 #{target['index']} 创建新物品\n"
            f"初始 item_id={new_id} (请改为你想要的值)\n"
            f"请填写 名称代码/说明代码/其他属性, 然后 Ctrl+S 保存."
        )
        self.status_var.set(f"新建物品: #{target['index']} item_id={new_id}")

    # ----------- 保存/导出 -----------
    def _save(self):
        if not self.item_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据")
            return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.item_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.item_path, 'rb') as s:
                with open(self.item_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except:
            pass
        try:
            self.status_var.set("正在保存…")
            self.root.update()
            save_items(self.item_path, self.records)
            self._dirty = False
            self.status_var.set(f"已保存 → {self.item_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.item_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['索引'] + [fl for _, _, fl, _, _, _ in ALL_FIELDS]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                row = [str(rec['index'])] + [str(rec[fn]) for fn, _, _, _, _, _ in ALL_FIELDS]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------
    def _show_field_ref(self):
        lines = ["TKItem.dat 字段映射 v3.0 (反编译 + Maker.exe TksModify.dll 实证):", ""]
        lines.append("【基础属性 (Maker UI 可见字段 22 条)】")
        for fn, fo, fl, ft, fw, cmt in GRID_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【技能 (Maker UI 4 字段)】")
        for fn, fo, fl, cmt in SKILL_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【导致状态 (Maker UI; 战斗时读取角色 a2[67]/a2[68])】")
        for fn, fo, fl, cmt in CAUSE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【解除状态 (sub_41E40C 使用物品时清除)】")
        for fn, fo, fl, cmt in CURE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【隐含数据 (Maker UI 未显示, 但 TKItem 记录占用)】")
        for fn, fo, fl, ft, fw, cmt in HIDDEN_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【使用权限 (equip_type) 实测值】")
        for page, opts in sorted(USE_RIGHT_OPTIONS.items()):
            lines.append(f"  页面{page}({PAGE_NAMES.get(page,'?')}): {opts}")
        lines.append("")
        lines.append("【记录数硬限制】")
        lines.append("  600 条 x 64 字节 = 38400 字节 (sub_45343C 固定加载量)")
        lines.append("  sub_42F8D4 搜索循环 `while (v3 < 600)` 是硬编码")
        lines.append("  #560-#599 (40条) 为真空槽, 可用于新增物品 (item_id=0, name_id=0)")

        dlg = tk.Toplevel(self.root)
        dlg.title("字段来源 v3.0 (逆向+Maker 实证)")
        dlg.geometry("820x580")
        dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='none')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        sb2 = ttk.Scrollbar(dlg, orient=tk.HORIZONTAL, command=tx.xview)
        tx.configure(yscrollcommand=sb1.set, xscrollcommand=sb2.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        sb2.pack(side=tk.BOTTOM, fill=tk.X)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines))
        tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKItem.dat 可视化编辑器 v3.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译 + Maker.exe TksModify.dll 文案对照\n"
            "600 条记录 x 32 字段 (int16 x 32 = 64 字节)\n\n"
            "核心反编译函数:\n"
            "  sub_45343C  数据载入 (硬编码 38400 字节)\n"
            "  sub_41E40C  物品使用 (药品 / 使用后学习技能 / 解除状态)\n"
            "  sub_42234C  装备应用 (装备后学习技能 / 导致状态)\n"
            "  sub_422BBC  附加技能 type=1/2/3 效果展开\n"
            "  sub_42F8D4  物品查找 (< 600 循环)\n"
            "  sub_424A2C  背包/商店显示\n\n"
            "v3.0 修正 v2.2 的错误字段映射 (原将 [22] 误标导致状态)"
        )


def main():
    root = tk.Tk()
    ItemEditor(root)
    root.mainloop()

if __name__ == '__main__':
    main()

