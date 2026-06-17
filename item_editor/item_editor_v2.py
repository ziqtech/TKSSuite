#!/usr/bin/env python3
"""
TKItem.dat 可视化编辑器 v2.0 (PySide6 — Godot 4.6 风格)
===========================================================
基于 item_editor.py v3.0 的完整功能, 使用 PySide6 重写 UI 层。
保留全部逆向分析、字段定义、LZSS 编解码、JVG 图标加载逻辑。
支持深色/浅色主题切换 (默认跟随系统), 共享 editor_themes/ 主题。

用法:
  python item_editor_v2.py
"""

import struct, os, sys, csv, re

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QMessageBox, QFileDialog, QDialog, QGridLayout, QFrame, QScrollArea,
    QSizePolicy, QMenu, QMenuBar
)
from PySide6.QtGui import QAction, QKeySequence, QIcon, QImage, QPixmap
from PySide6.QtCore import Qt

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
                idx = flat_bytes.rfind(pat, start_idx, end_idx)
                if idx != -1:
                    bl = length
                    bo = (idx - 18) & 0xFFF
                    break
        if bl >= 3:
            tokens.append((False, bo, bl)); pos += bl
        else:
            tokens.append((True, src[pos], 0)); pos += 1
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
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path, 'rb') as f: raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]; cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8+ts]; dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt*4, cnt*4; lookup = {}; SKIP = set(range(0,10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i*4)[0]
        if eid in SKIP: continue
        off = struct.unpack_from('<I', dec, idsz + i*4)[0]; ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0: end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try: s = txt.decode('big5', errors='replace')
            except: s = txt.decode('gbk', errors='replace')
            if s and s != '0': lookup[eid] = s.split('\n')[0].strip()
    return lookup

def load_tkt_full(tkt_path):
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path, 'rb') as f: raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]; cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8+ts]; dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt*4, cnt*4; lookup = {}; SKIP = set(range(0,10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i*4)[0]
        if eid in SKIP: continue
        off = struct.unpack_from('<I', dec, idsz + i*4)[0]; ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0: end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try: s = txt.decode('big5', errors='replace')
            except: s = txt.decode('gbk', errors='replace')
            if s and s != '0': lookup[eid] = s.strip()
    return lookup

def load_tkskill_names(sp, tkt):
    if not sp or not os.path.exists(sp): return {}
    with open(sp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); REC = 94; names = {}
    for i in range(min(350, len(dec)//REC)):
        sid = struct.unpack_from('<h', dec, i*REC)[0]
        n = tkt.get(sid,"") or tkt.get(-sid,"") or f"Skill#{sid}"
        names[i] = n
    return names

# ============================================================
# Mu.JVG 物品图标加载 (icon + 130 = 精灵索引)
# ============================================================
def load_mu_sprites(mu_path):
    try:
        from PIL import Image
    except ImportError:
        return None
    if not mu_path or not os.path.exists(mu_path): return None
    with open(mu_path, 'rb') as f: data = f.read()
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
# 常量 (Maker.exe TksModify.dll 文案 + TKS.exe 反编译)
# ============================================================
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]
STATUS_ICON_BASE = 242

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

USE_RIGHT_OPTIONS = {
    0: [(1, "战斗"), (2, "非战斗")],
    1: [(1, "战斗"), (2, "非战斗"), (4, "主角限定")],
    2: [(1, "刀"), (2, "剑"), (4, "枪"), (8, "矛"),
        (16, "弓"), (32, "大刀"), (64, "戟"), (128, "锤")],
    3: [(1, "衣袍"), (2, "铠甲")],
    4: [(0, "通用")],
    5: [(0, "通用")],
}

def _use_right_label(val, page):
    opts = USE_RIGHT_OPTIONS.get(page, [])
    sel = [name for bit, name in opts if bit == 0 or (val & bit)]
    return ", ".join(sel) if sel else "(无)"

PAGE_NAMES = {0:"药品", 1:"道具", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
PAGE_VALUES = [f"{k}-{v}" for k,v in sorted(PAGE_NAMES.items())]

ITEM_REC = 64; ITEM_CNT = 600
W_INPUT = 12

# ============================================================
# 字段定义
# ============================================================
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

SKILL_FIELDS = [
    ("attach_skill",    42, "附加技能",         "装备后直接施加技能被动效果(属性加成等)，不写入技能栏 (v15[21])"),
    ("equip_learn",     44, "装备后学习技能",   "⚠ 仅升级已有技能(1-19→10级)，不会从零教会！未习得技能无效果 (v15[22])"),
    ("use_learn1",      46, "使用后学习技能1",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[23])"),
    ("use_learn2",      48, "使用后学习技能2",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[24])"),
]

CAUSE_MASK_FIELDS = [
    ("cause_mask1", 52, "导致状态 1-16",  "装备/命中时让目标进入的状态位掩码，每位对应状态表第 i 项 (v15[26])"),
    ("cause_mask2", 54, "导致状态 17-32", "装备/命中时让目标进入的状态位掩码，每位对应状态表第 16+i 项 (v15[27])"),
]

CURE_MASK_FIELDS = [
    ("cure_mask1", 56, "解除状态 1-16",  "使用物品时解除的状态位掩码，每位对应状态表第 i 项 (v15[28])"),
    ("cure_mask2", 58, "解除状态 17-32", "使用物品时解除的状态位掩码，每位对应状态表第 16+i 项 (v15[29])"),
]

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
    if rec.get('item_id', 0) in (0, 1): return True
    if rec.get('name_id', 0) <= 0: return True
    if tkt is not None:
        nm = tkt.get(rec['name_id'], "")
        if not nm or not nm.strip(): return True
    return False

def is_pure_empty_slot(rec):
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
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); recs = []
    for i in range(ITEM_CNT):
        off = i * ITEM_REC
        if off + ITEM_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h'*32, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_items(fp, recs):
    buf = bytearray(ITEM_CNT * ITEM_REC)
    for rec in recs[:ITEM_CNT]:
        i = rec['index']; off = i * ITEM_REC
        for k, fo, _, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# QSS 主题加载 (共享 editor_themes/ 目录)
# ============================================================
def _load_qss(theme: str) -> str:
    themes_dir = os.path.join(os.path.dirname(__file__), '..', 'editor_themes')
    qss_path = os.path.join(themes_dir, f'{theme}.qss')
    if os.path.exists(qss_path):
        with open(qss_path, 'r', encoding='utf-8') as f:
            qss = f.read()
        themes_dir_abs = os.path.abspath(themes_dir).replace("\\", "/")
        qss = re.sub(r"url\(([^)]+)\)", lambda m: f"url({themes_dir_abs}/{m.group(1)})", qss)
        return qss
    return ''

GODOT_DARK_QSS = _load_qss('dark')
GODOT_LIGHT_QSS = _load_qss('light')

# ============================================================
# UI 辅助组件
# ============================================================
class DockHeader(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(4)
        lbl = QLabel(title); lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)

def make_fake_input(line_edit=None, combo=None, button=None, stretch=True):
    box = QFrame(); box.setObjectName("FakeInputBox")
    h = QHBoxLayout(box); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
    if line_edit: h.addWidget(line_edit)
    if combo: h.addWidget(combo, 1)
    if button: h.addWidget(button)
    if stretch: h.addStretch()
    return box

# ============================================================
# 弹窗选择器
# ============================================================
class TktPickerDialog(QDialog):
    def __init__(self, parent, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择 TKT 文本"); self.resize(520, 550)
        self.selected_id = None
        self.tkt_items = sorted(tkt_dict.items(), key=lambda x: x[0])
        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['ID', '文本'])
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        bl = QHBoxLayout(); bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._accept_selection); bl.addWidget(btn_ok)
        layout.addLayout(bl)
        self._refresh()

    def _refresh(self):
        query = self.search_box.text().strip().lower()
        self.table.setRowCount(0); row = 0
        for eid, txt in self.tkt_items:
            if query and query not in txt.lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(eid)))
            self.table.setItem(row, 1, QTableWidgetItem(txt[:80].replace('\n', ' ')))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_id = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

class SkillPickerDialog(QDialog):
    def __init__(self, parent, skill_names, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能"); self.resize(460, 550)
        self.selected_index = None; self.skill_names = skill_names
        layout = QVBoxLayout(self)
        sf = QHBoxLayout(); sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit(); self.search_box.textChanged.connect(self._refresh); sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['索引', '技能名称'])
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("清空选择", clicked=self._clear))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept_selection))
        layout.addLayout(bl)
        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower()
        self.table.setRowCount(0); row = 0
        for idx in sorted(self.skill_names.keys()):
            nm = self.skill_names[idx]
            if q and q not in f"{idx} {nm}".lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(nm[:60]))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

    def _clear(self):
        self.selected_index = 0; self.accept()

class IconPickerDialog(QDialog):
    def __init__(self, parent, mu_sprites, get_pixmap_fn, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择图标 (索引 = 游戏值 + 130)"); self.resize(780, 560)
        self.selected_value = None
        self.mu_sprites = mu_sprites; self.get_pixmap_fn = get_pixmap_fn; self.cur_val = cur_val
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); self.grid = QGridLayout(inner); self.grid.setSpacing(2)
        COLS = 12
        for si in range(len(mu_sprites)):
            if mu_sprites[si] is None: continue
            game_idx = si - 130
            r, c = divmod(si, COLS)
            btn = QPushButton(); btn.setFixedSize(52, 56); btn.setCursor(Qt.PointingHandCursor)
            if game_idx == cur_val:
                btn.setStyleSheet("QPushButton{background-color:#2e3548; border:2px solid #478cbf;}")
            else:
                btn.setStyleSheet("QPushButton{background-color:transparent; border:1px solid transparent;}")
            pix = get_pixmap_fn(game_idx, (40, 40))
            if pix:
                btn.setIcon(QIcon(pix)); btn.setIconSize(pix.size())
            btn.setText(str(game_idx))
            btn.setToolTip(f"精灵索引: {si}\n游戏值: {game_idx}")
            btn.clicked.connect(lambda checked, v=game_idx: self._select(v))
            self.grid.addWidget(btn, r, c)
        scroll.setWidget(inner); layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QLabel("点击图标选择，索引 = 游戏精灵索引 - 130"))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        layout.addLayout(bl)

    def _select(self, v):
        self.selected_value = v; self.accept()

class StatusPickerDialog(QDialog):
    def __init__(self, parent, title, status_names, get_pixmap_fn, cur_mask, base, is_cause):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(380, 520)
        self.selected_mask = None
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); cl = QVBoxLayout(content)
        self.checkboxes = []
        for i in range(16):
            idx = base + i
            if idx >= len(status_names): break
            row = QHBoxLayout()
            pix = get_pixmap_fn(STATUS_ICON_BASE + idx - 130, (20, 20))
            if pix:
                lbl = QLabel(); lbl.setPixmap(pix); row.addWidget(lbl)
            cb = QCheckBox(f"{idx}. {status_names[idx]}")
            cb.setChecked(bool(cur_mask & (1 << i)))
            self.checkboxes.append((i, cb)); row.addWidget(cb); row.addStretch()
            cl.addLayout(row)
        cl.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._ok); bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _ok(self):
        m = 0
        for i, cb in self.checkboxes:
            if cb.isChecked(): m |= (1 << i)
        if m >= 0x8000: m -= 0x10000
        self.selected_mask = m; self.accept()

class FlagPickerDialog(QDialog):
    """通用位标志选择弹窗 (combat_flag / extra_flags)"""
    def __init__(self, parent, title, flag_bits, cur_val, use_bit_shift=False):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(420, 280)
        self.selected_mask = None; self.use_bit_shift = use_bit_shift
        layout = QVBoxLayout(self)
        self.checkboxes = []
        for bit, name, desc in flag_bits:
            row = QHBoxLayout()
            mask = (1 << bit) if use_bit_shift else bit
            cb = QCheckBox(f"{name}" + (f" (bit{bit})" if use_bit_shift else ""))
            cb.setChecked(bool(cur_val & mask))
            self.checkboxes.append((mask, cb)); row.addWidget(cb)
            row.addWidget(QLabel(desc), 1)
            layout.addLayout(row)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._ok); bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _ok(self):
        m = 0
        for mask, cb in self.checkboxes:
            if cb.isChecked(): m |= mask
        if m >= 0x8000: m -= 0x10000
        self.selected_mask = m; self.accept()

class UseRightPickerDialog(QDialog):
    def __init__(self, parent, opts, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择使用权限 (多选位掩码)"); self.resize(320, 60 + max(len(opts), 2) * 28)
        self.selected_mask = None
        layout = QVBoxLayout(self)
        self.checkboxes = []
        for bit, name in opts:
            cb = QCheckBox(f"{bit}-{name}" if bit != 0 else name)
            cb.setChecked(bool(cur_val & bit) if bit != 0 else False)
            self.checkboxes.append((bit, cb)); layout.addWidget(cb)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._ok); bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _ok(self):
        m = 0
        for bit, cb in self.checkboxes:
            if cb.isChecked(): m += bit
        if m >= 0x8000: m -= 0x10000
        self.selected_mask = m; self.accept()

# ============================================================
# GUI 核心编辑器
# ============================================================
class ItemEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKItem.dat 可视化编辑器 v2.0 (PySide6)")
        self.resize(1360, 860); self.setMinimumSize(1120, 700)

        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path): self.setWindowIcon(QIcon(ico_path))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        self.item_path = self.tkt_path = self.skill_path = self.mu_path = None
        self.records = []; self.tkt = {}; self.tkt_full = {}; self.skill_names = {}
        self._mu_sprites = []; self._icon_pixmaps = {}
        self.filtered_indices = []; self._dirty = False; self._editing_idx = None
        self._sort_reverse = False
        self._guard_right_reset = False

        self.widget_map = {}; self.extra_map = {}

        self._build_ui(); self._set_edit_enabled(False); self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        self.setStyleSheet(GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS)
        self._update_paths()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark; self._apply_theme(); self._refresh_table()

    def _create_dock(self, title, widget_content):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(DockHeader(title))
        body = QWidget(); body.setObjectName("DockBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.addWidget(widget_content)
        layout.addWidget(body, 1)
        return container

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4); main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…\tCtrl+O", self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出 CSV…", self._export_csv)
        fm.addSeparator(); fm.addAction("退出", self.close)
        em = mb.addMenu("编辑(&E)")
        em.addAction("新建物品 (填充空槽)\tCtrl+N", self._new_item)
        em.addAction("复制当前到空槽", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)
        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段来源 (逆向+Maker)", self._show_field_ref)
        hm.addAction("关于", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("页面号:"))
        self.filter_page = QComboBox()
        self.filter_page.addItems(["全部页面"] + PAGE_VALUES)
        self.filter_page.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_page)
        toolbar.addSpacing(6)
        toolbar.addWidget(QLabel("权限:"))
        self.filter_right = QComboBox()
        self.filter_right.addItems(["全部权限"])
        self.filter_right.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_right)
        toolbar.addSpacing(6)
        self.filter_empty = QCheckBox("仅非空")
        self.filter_empty.setChecked(True)
        self.filter_empty.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_empty)
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("新建物品", clicked=self._new_item))
        toolbar.addWidget(QPushButton("重新加载", clicked=self._reload))
        toolbar.addStretch()
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主分割窗口
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # 左侧: 物品列表 (列顺序与原版一致: 图标在最前)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['图标', '#', 'ID', '页面', '物品名称', '权限', '价格'])
        self.table.setColumnWidth(0, 40); self.table.setColumnWidth(1, 40)
        self.table.setColumnWidth(2, 50); self.table.setColumnWidth(3, 50)
        self.table.setColumnWidth(4, 160); self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by)
        self.splitter.addWidget(self._create_dock("物品列表", self.table))

        # 右侧: 编辑器
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 顶部行: 记录标签 + 操作按钮
        header_row = QHBoxLayout()
        self.lbl_rec_idx = QLabel("未选中")
        self.lbl_rec_idx.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_row.addWidget(self.lbl_rec_idx)
        header_row.addStretch()
        header_row.addWidget(QPushButton("✅ 应用", clicked=self._apply_edit))
        header_row.addWidget(QPushButton("📋 复制到空槽", clicked=self._copy_record))
        header_row.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit))
        header_row.addWidget(QPushButton("🗑 清空", clicked=self._clear_current))
        right_layout.addLayout(header_row)

        # 滚动编辑区
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.edit_inner = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_inner)
        self.edit_layout.setContentsMargins(4, 4, 16, 4); self.edit_layout.setSpacing(4)

        # 预览面板
        self._build_preview()

        # 基础属性网格
        self._build_field_group("基础属性", GRID_FIELDS, 5)
        # 技能组
        self._build_field_group("技能", [(k,o,l,'skill',W_INPUT,c) for k,o,l,c in SKILL_FIELDS], 4)
        # 状态组
        status_fields = [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CAUSE_MASK_FIELDS + CURE_MASK_FIELDS]
        self._build_field_group("状态位掩码 (导致/解除)", status_fields, 4)
        # 隐含字段
        self._build_field_group("隐含数据 (保留原始数据)", HIDDEN_FIELDS, 2)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)
        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setSizes([420, 940])

        # 底部路径栏
        path_layout = QHBoxLayout()
        self.lbl_item = QLabel("TKItem.dat: 未加载")
        self.lbl_tkt = QLabel("TKT.dat: 未加载")
        self.lbl_skill = QLabel("TKSkill.dat: 未加载")
        path_layout.addWidget(self.lbl_item); path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt); path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_skill); path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_preview(self):
        preview_frame = QFrame(); preview_frame.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(8, 12, 8, 12); pl.setSpacing(6)

        # 名称 + 图标
        top_row = QHBoxLayout()
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        top_row.addWidget(self.preview_name, 1)
        self.preview_icon = QLabel()
        top_row.addWidget(self.preview_icon)
        pl.addLayout(top_row)

        # 元数据
        self.preview_meta = QLabel("")
        self.preview_meta.setProperty("class", "PreviewMeta")
        self.preview_meta.setWordWrap(True)
        pl.addWidget(self.preview_meta)

        # 说明
        self.preview_desc = QLabel("请在左侧列表中选择物品。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.preview_desc)

        # 技能预览 (4列)
        skill_row = QHBoxLayout()
        skill_labels = ["附加技能", "装备后学习", "使用后学习1", "使用后学习2"]
        self._preview_skills = []
        for slbl in skill_labels:
            col = QVBoxLayout()
            lbl_t = QLabel(f"{slbl}:"); lbl_t.setProperty("class", "PropLabel")
            col.addWidget(lbl_t)
            lbl_v = QLabel("—"); lbl_v.setProperty("class", "PreviewDesc")
            lbl_v.setWordWrap(True)
            col.addWidget(lbl_v)
            self._preview_skills.append(lbl_v)
            skill_row.addLayout(col)
        pl.addLayout(skill_row)

        # 状态预览 (4列, 含图标)
        status_row = QHBoxLayout()
        status_labels = ["导致状态 1-16", "导致状态 17-32", "解除状态 1-16", "解除状态 17-32"]
        self._preview_status_containers = []
        for si, slbl in enumerate(status_labels):
            col = QVBoxLayout()
            lbl_t = QLabel(f"{slbl}:"); lbl_t.setProperty("class", "PropLabel")
            col.addWidget(lbl_t)
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            col.addWidget(container)
            self._preview_status_containers.append(container)
            status_row.addLayout(col)
        pl.addLayout(status_row)

        self.edit_layout.addWidget(preview_frame)

    def _build_field_group(self, title, fields, cols):
        group_widget = QWidget()
        v_layout = QVBoxLayout(group_widget)
        v_layout.setContentsMargins(0, 4, 0, 4); v_layout.setSpacing(6)

        lbl_title = QLabel(title); lbl_title.setProperty("class", "InspectorTitle")
        v_layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setVerticalSpacing(6); grid.setHorizontalSpacing(15)
        grid.setContentsMargins(10, 0, 0, 0)

        for fi, field_def in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, field_def)

        v_layout.addLayout(grid)
        self.edit_layout.addWidget(group_widget)

    def _build_field(self, grid, row, col, field_def):
        fn, fo, fl = field_def[0], field_def[1], field_def[2]
        ft = field_def[3] if len(field_def) > 3 else 'int'
        cmt = field_def[5] if len(field_def) > 5 else (field_def[4] if len(field_def) > 4 else "")

        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")

        if ft == 'page':
            cb = QComboBox(); cb.addItems(PAGE_VALUES)
            box = make_fake_input(combo=cb)
            self.widget_map[fn] = cb; self.extra_map[fn] = None
        elif ft in ('tkt', 'icon', 'use_right', 'combat_flag', 'extra_flags', 'skill'):
            inp = QLineEdit()
            btn = QPushButton("..."); btn.setFixedWidth(28)
            btn.setCursor(Qt.PointingHandCursor)
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            box = make_fake_input(line_edit=inp, button=btn, stretch=False)
            field_wrap = QVBoxLayout(); field_wrap.setContentsMargins(0,0,0,0); field_wrap.setSpacing(0)
            field_wrap.addWidget(box); field_wrap.addWidget(extra)
            self.widget_map[fn] = inp; self.extra_map[fn] = extra
            if ft == 'tkt': btn.clicked.connect(lambda _, f=fn: self._pick_tkt(f))
            elif ft == 'icon': btn.clicked.connect(lambda _, f=fn: self._pick_icon(f))
            elif ft == 'use_right': btn.clicked.connect(lambda _, f=fn: self._pick_use_right(f))
            elif ft == 'combat_flag': btn.clicked.connect(lambda _, f=fn: self._pick_combat_flags(f))
            elif ft == 'extra_flags': btn.clicked.connect(lambda _, f=fn: self._pick_extra_flags(f))
            elif ft == 'skill': btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))
            wrap_w = QWidget(); wrap_w.setLayout(field_wrap)
            grid.addWidget(lbl, row, col*2, alignment=Qt.AlignRight|Qt.AlignVCenter)
            grid.addWidget(wrap_w, row, col*2+1)
            return
        elif ft == 'mask':
            inp = QLineEdit(); inp.setVisible(False)
            btn = QPushButton("配置"); btn.setCursor(Qt.PointingHandCursor); btn.setMaximumWidth(60)
            is_cause = fn.startswith('cause_')
            extra = QLabel("(无)")
            extra.setProperty("class", "StatusInflict" if is_cause else "StatusRemove")
            extra.setWordWrap(True)
            box = make_fake_input(line_edit=inp, button=btn, stretch=False)
            field_wrap = QVBoxLayout(); field_wrap.setContentsMargins(0,0,0,0); field_wrap.setSpacing(0)
            field_wrap.addWidget(box); field_wrap.addWidget(extra)
            self.widget_map[fn] = inp; self.extra_map[fn] = extra
            btn.clicked.connect(lambda _, f=fn: self._pick_status(f))
            wrap_w = QWidget(); wrap_w.setLayout(field_wrap)
            grid.addWidget(lbl, row, col*2, alignment=Qt.AlignRight|Qt.AlignVCenter)
            grid.addWidget(wrap_w, row, col*2+1)
            return
        else:
            inp = QLineEdit()
            box = make_fake_input(line_edit=inp)
            self.widget_map[fn] = inp; self.extra_map[fn] = None

        grid.addWidget(lbl, row, col*2, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(box, row, col*2+1)

    # ── 启用/禁用编辑 ──
    def _set_edit_enabled(self, en):
        self.edit_inner.setEnabled(en)

    def _update_paths(self):
        cg = "color:#55b572;" if self._is_dark else "color:#178a39;"
        cr = "color:#e27d60;" if self._is_dark else "color:#c93b16;"
        for lb, p, key in [(self.lbl_item, self.item_path, 'TKItem'),
                           (self.lbl_tkt, self.tkt_path, 'TKT'),
                           (self.lbl_skill, self.skill_path, 'TKSkill')]:
            if not p: lb.setStyleSheet(cr); lb.setText(f"{key}: 未加载")
            elif not os.path.exists(p): lb.setStyleSheet(cr); lb.setText(f"{key}: (不存在){p}")
            else: lb.setStyleSheet(cg); lb.setText(f"{key}: {p}")

    # ── 数据加载 ──
    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        it = os.path.join(d, "TKItem.dat")
        tk_ = os.path.join(d, "TKT.dat")
        sk = os.path.join(d, "TKSkill.dat")
        if not os.path.exists(it):
            QMessageBox.warning(self, "文件缺失", "未找到 TKItem.dat"); return
        self.item_path = it
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.skill_path = sk if os.path.exists(sk) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        if not os.path.exists(self.mu_path): self.mu_path = None
        self._reload()

    def _reload(self):
        if not self.item_path: return
        self.status_var.setText("加载中…")
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        else:
            self.tkt_full = {}
        if self.skill_path:
            self.skill_names = load_tkskill_names(self.skill_path, self.tkt)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()
        try:
            self.records = load_items(self.item_path); self._dirty = False
            self.status_var.setText(f"{len(self.records)} 条 | TKT {len(self.tkt)} 条 | 技能 {len(self.skill_names)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        if not self._mu_sprites: return None
        idx = icon_val + 130
        if idx < 0 or idx >= len(self._mu_sprites): return None
        sprite = self._mu_sprites[idx]
        if sprite is None: return None
        cache_key = (idx, size)
        if cache_key in self._icon_pixmaps: return self._icon_pixmaps[cache_key]
        try:
            from PIL import Image
            img = sprite.resize(size, Image.NEAREST).convert('RGBA')
            data = img.tobytes('raw', 'RGBA')
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg); self._icon_pixmaps[cache_key] = pix
            return pix
        except: return None

    # ── 筛选/列表 ──
    def _update_right_options(self, page_filter_text):
        if page_filter_text.startswith("全部"):
            seen = set(); all_opts = []
            for page in sorted(USE_RIGHT_OPTIONS):
                for bit, name in USE_RIGHT_OPTIONS[page]:
                    key = (bit, name)
                    if key not in seen:
                        seen.add(key); all_opts.append(f"{bit}-{name}")
        else:
            page = int(page_filter_text.split('-')[0])
            opts = USE_RIGHT_OPTIONS.get(page, [])
            all_opts = [f"{bit}-{name}" for bit, name in opts]
        new_vals = ["全部权限"] + all_opts
        current_vals = [self.filter_right.itemText(i) for i in range(self.filter_right.count())]
        if new_vals != current_vals:
            self._guard_right_reset = True
            self.filter_right.clear(); self.filter_right.addItems(new_vals)
            self.filter_right.setCurrentIndex(0)  # 重置为"全部权限"
            self._guard_right_reset = False

    def _apply_filter(self):
        if self._guard_right_reset: return
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        fpg = self.filter_page.currentText()
        self._update_right_options(fpg)
        frg = self.filter_right.currentText()
        for rec in self.records:
            if self.filter_empty.isChecked() and is_empty_item(rec, self.tkt): continue
            if fpg and not fpg.startswith("全部"):
                if rec['tab_code'] != int(fpg.split('-')[0]): continue
            if frg and not frg.startswith("全部"):
                bit = int(frg.split('-')[0])
                if bit == 0:
                    if rec['equip_type'] != 0: continue
                else:
                    if (rec['equip_type'] & bit) == 0: continue
            if q:
                nm = item_display_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['item_id']} {rec['tab_code']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        empty_cnt = sum(1 for r in self.records if is_pure_empty_slot(r))
        self.status_var.setText(
            f"显示 {len(self.filtered_indices)}/{len(self.records)} | 真空槽剩余 {empty_cnt}/40 | Ctrl+S 保存")

    def _clear_filter(self):
        self.search_entry.clear()
        self.filter_page.setCurrentIndex(0)
        self.filter_right.setCurrentIndex(0)
        self.filter_empty.setChecked(True)
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            et = r['equip_type']
            rt = _use_right_label(et, r.get('tab_code', 0)) if et or et == 0 else "—"
            self.table.insertRow(row)
            # 列顺序: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
            icon_item = QTableWidgetItem()
            pix = self._get_icon_pixmap(r['icon'], (24, 24))
            if pix: icon_item.setIcon(QIcon(pix))
            self.table.setItem(row, 0, icon_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 2, QTableWidgetItem(str(r['item_id'])))
            self.table.setItem(row, 3, QTableWidgetItem(PAGE_NAMES.get(r['tab_code'], '?')))
            self.table.setItem(row, 4, QTableWidgetItem(item_display_name(r, self.tkt)))
            self.table.setItem(row, 5, QTableWidgetItem(rt))
            self.table.setItem(row, 6, QTableWidgetItem(str(r['price'])))
        self.table.blockSignals(False)

    def _sort_by(self, col):
        # 列: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
        km = {2:'item_id', 3:'tab_code', 5:'equip_type', 6:'price'}
        key = km.get(col, 'index')
        self.filtered_indices.sort(key=lambda i: self.records[i].get(key, 0), reverse=self._sort_reverse)
        self._sort_reverse = not self._sort_reverse; self._refresh_table()

    # ── 编辑 ──
    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 1).text())  # 列1=索引 (列0=图标)
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        self.lbl_rec_idx.setText(
            f"记录 #{rec['index']}   物品代码={rec['item_id']}   "
            f"页面号={PAGE_NAMES.get(rec['tab_code'],'?')}   "
            f"名称={item_display_name(rec, self.tkt)}")

        # 预览
        nid = rec.get('name_id', 0) or 0
        did = rec.get('desc_id', 0) or 0
        n_txt = self.tkt.get(int(nid), "") if nid > 0 else ""
        self.preview_name.setText(n_txt if n_txt else "(无 / TKT 未提供)")
        d_txt = self.tkt_full.get(int(did), "") if did > 0 else ""
        self.preview_desc.setText(d_txt if d_txt else "(无 / TKT 未提供)")

        # 元数据
        page_str = PAGE_NAMES.get(rec['tab_code'], '?')
        et_label = _use_right_label(rec.get('equip_type', 0), rec.get('tab_code', 0))
        self.preview_meta.setText(f"页面={page_str}  |  权限={et_label}  |  价格={rec['price']}  |  图标={rec.get('icon',0)}")

        # 图标预览
        pix = self._get_icon_pixmap(rec.get('icon', 0), (40, 40))
        if pix: self.preview_icon.setPixmap(pix)
        else: self.preview_icon.clear()

        # 技能预览
        skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
        for si, sk in enumerate(skill_keys):
            sid = int(rec.get(sk, 0)) if rec.get(sk, 0) else -1
            if sid > 0:
                nm = self.skill_names.get(sid, f"技能#{sid}")
                self._preview_skills[si].setText(nm)
            else:
                self._preview_skills[si].setText("—")

        # 状态预览
        status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
        for si, sk in enumerate(status_keys):
            mask = int(rec.get(sk, 0)) if rec.get(sk, 0) else 0
            base = 0 if sk.endswith('_mask1') else 16
            sel = [(base+i, STATUS_NAMES[base+i]) for i in range(16) if mask & (1 << i) and base+i < len(STATUS_NAMES)]
            self._update_preview_status(si, sel)

        # 填充字段
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            val = rec[fn]; sv = str(val)
            w = self.widget_map.get(fn)
            if not w: continue
            if ft == 'page':
                for i in range(w.count()):
                    if w.itemText(i).startswith(f"{val}-"): w.setCurrentIndex(i); break
            else:
                w.setText(sv)

            if ft == 'tkt':
                tid = int(val) if val else 0
                txt = self.tkt.get(tid, "") if tid > 0 else ""
                t = txt.split('\n')[0] if txt else ""
                self.extra_map[fn].setText((t[:12]+'...') if len(t) > 12 else t)
            elif ft == 'use_right':
                page = rec.get('tab_code', 0)
                self.extra_map[fn].setText(_use_right_label(int(val) if val else 0, page))
            elif ft == 'combat_flag':
                self._update_flag_label(fn, int(val) if val else 0, COMBAT_FLAG_BITS)
            elif ft == 'extra_flags':
                self._update_flag_label(fn, int(val) if val else 0, EXTRA_FLAG_BITS, use_bit_shift=True)
            elif ft == 'skill':
                sid = int(val) if val else -1
                nm = self.skill_names.get(sid, "(无)") if sid > 0 else "(无)"
                self.extra_map[fn].setText(nm[:30] if sid > 0 else "(无)")
            elif ft == 'mask':
                self._update_status_label(fn, int(val) if val else 0)
            elif ft == 'icon':
                ival = int(val) if val else 0
                self.extra_map[fn].setText(f"[图标 {ival}]")

    def _update_flag_label(self, fn, val, flag_bits, use_bit_shift=False):
        mask = val & 0xFFFF
        sel = []
        for bit, name, _ in flag_bits:
            if use_bit_shift:
                if mask & (1 << bit): sel.append(name)
            else:
                if mask & bit: sel.append(name)
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_preview_status(self, si, sel):
        container = self._preview_status_containers[si]
        # 清除旧内容
        while container.layout().count():
            child = container.layout().takeAt(0)
            if child.widget(): child.widget().deleteLater()
        if not sel:
            lbl = QLabel("—"); lbl.setProperty("class", "PreviewDesc")
            container.layout().addWidget(lbl); return
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0)
        for idx, nm in sel:
            cell = QVBoxLayout(); cell.setContentsMargins(0,0,0,0); cell.setSpacing(0)
            pix = self._get_icon_pixmap(STATUS_ICON_BASE + idx - 130, (16, 16))
            if pix:
                il = QLabel(); il.setPixmap(pix); cell.addWidget(il)
            lbl = QLabel(nm); lbl.setStyleSheet("font-size: 10px;")
            cell.addWidget(lbl)
            row.addLayout(cell)
        container.layout().addLayout(row)

    # ── 弹窗: TKT ──
    def _pick_tkt(self, fn):
        if not self.tkt: return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = TktPickerDialog(self, self.tkt, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            self.widget_map[fn].setText(str(dlg.selected_id))
            txt = self.tkt.get(dlg.selected_id, "")
            t = txt.split('\n')[0] if txt else ""
            self.extra_map[fn].setText((t[:12]+'...') if len(t) > 12 else t)
            if fn == 'name_id': self.preview_name.setText(txt if txt else "(无)")
            elif fn == 'desc_id':
                d_txt = self.tkt_full.get(dlg.selected_id, "")
                self.preview_desc.setText(d_txt if d_txt else "(无 / TKT 未提供)")

    # ── 弹窗: 技能 ──
    def _pick_skill(self, fn):
        if not self.skill_names: return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = SkillPickerDialog(self, self.skill_names, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = self.skill_names.get(dlg.selected_index, "") if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText(nm[:20] if nm else "(无)")
            skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
            if fn in skill_keys:
                self._preview_skills[skill_keys.index(fn)].setText(nm if nm else "—")

    # ── 弹窗: 图标 ──
    def _pick_icon(self, fn):
        if not self._mu_sprites:
            QMessageBox.information(self, "提示", "未加载 Mu.JVG 图标文件"); return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = IconPickerDialog(self, self._mu_sprites, self._get_icon_pixmap, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_value is not None:
            self.widget_map[fn].setText(str(dlg.selected_value))
            self.extra_map[fn].setText(f"[图标 {dlg.selected_value}]")
            pix = self._get_icon_pixmap(dlg.selected_value, (40, 40))
            if pix: self.preview_icon.setPixmap(pix)
            else: self.preview_icon.clear()

    # ── 弹窗: 状态 mask ──
    def _pick_status(self, fn):
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        base = 0 if fn.endswith('_mask1') else 16
        cur_mask = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = StatusPickerDialog(self, title, STATUS_NAMES, self._get_icon_pixmap, cur_mask, base, is_cause)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_status_label(fn, dlg.selected_mask & 0xFFFF)
            status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
            if fn in status_keys:
                si = status_keys.index(fn)
                sel = [(base+i, STATUS_NAMES[base+i]) for i in range(16) if (dlg.selected_mask & 0xFFFF) & (1 << i) and base+i < len(STATUS_NAMES)]
                self._update_preview_status(si, sel)

    # ── 弹窗: 战斗结算效果 ──
    def _pick_combat_flags(self, fn):
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = FlagPickerDialog(self, "选择战斗结算效果 (位掩码)", COMBAT_FLAG_BITS, cur_val, use_bit_shift=False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_flag_label(fn, dlg.selected_mask, COMBAT_FLAG_BITS)

    # ── 弹窗: 额外标志 ──
    def _pick_extra_flags(self, fn):
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = FlagPickerDialog(self, "选择额外标志 (位掩码)", EXTRA_FLAG_BITS, cur_val, use_bit_shift=True)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_flag_label(fn, dlg.selected_mask, EXTRA_FLAG_BITS, use_bit_shift=True)

    # ── 弹窗: 使用权限 ──
    def _pick_use_right(self, fn):
        if not self.records or self._editing_idx is None: return
        page = self.records[self._editing_idx].get('tab_code', 0)
        opts = USE_RIGHT_OPTIONS.get(page, [])
        if len(opts) == 1 and opts[0][0] == 0:
            self.widget_map[fn].setText("0")
            self.extra_map[fn].setText(_use_right_label(0, page)); return
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = UseRightPickerDialog(self, opts, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self.extra_map[fn].setText(_use_right_label(dlg.selected_mask, page))

    # ── 编辑应用 ──
    def _apply_edit(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            try:
                w = self.widget_map.get(fn)
                if not w: continue
                if ft == 'page':
                    sv = w.currentText()
                    rec[fn] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
                else:
                    v = int(w.text() or 0)
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    rec[fn] = v
            except ValueError:
                rec[fn] = 0
        self._dirty = True; self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 1).text()) == rec['index']:
                self.table.selectRow(r); break
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _clear_current(self):
        if self._editing_idx is None:
            QMessageBox.information(self, "提示", "请先选择一条记录"); return
        reply = QMessageBox.question(self, "确认清空",
            f"将记录 #{self._editing_idx} 清为空槽模板 (item_id=0, name_id=0, desc_id=600).\n确定?")
        if reply != QMessageBox.Yes: return
        rec = self.records[self._editing_idx]
        for fn, _, _, _, _, _ in ALL_FIELDS: rec[fn] = 0
        rec['desc_id'] = 600
        self._dirty = True; self._apply_filter(); self._populate_edit(rec)
        self.status_var.setText(f"记录 #{self._editing_idx} 已清空")

    def _copy_record(self):
        if self._editing_idx is None:
            QMessageBox.information(self, "提示", "请先选择一条记录"); return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_pure_empty_slot(rec):
                for fn, fo, fl, ft, fw, cmt in ALL_FIELDS: rec[fn] = src[fn]
                rec['index'] = i
                self._dirty = True; self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 1).text()) == i:
                        self.table.selectRow(r); break
                self.status_var.setText(f"已复制到空槽 #{i}"); return
        QMessageBox.warning(self, "已满", "无真·空槽 (id=0 的记录) 可复制到.\n可先使用『清空此记录』释放一个槽位.")

    def _new_item(self):
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载 TKItem.dat"); return
        target = None
        for rec in self.records:
            if is_pure_empty_slot(rec): target = rec; break
        if target is None:
            QMessageBox.warning(self, "已满",
                "600 条记录上限已满 (sub_45343C 硬编码 38400 字节)\n无真·空槽 (id=0) 可用."); return
        for fn, _, _, _, _, _ in ALL_FIELDS: target[fn] = 0
        used_ids = {r['item_id'] for r in self.records if r['item_id'] > 0}
        new_id = 600
        while new_id in used_ids and new_id < 9999: new_id += 1
        target['item_id'] = new_id; target['desc_id'] = 600; target['price'] = 1; target['tab_code'] = 0
        self._dirty = True; self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 1).text()) == target['index']:
                self.table.selectRow(r); break
        self._populate_edit(target)
        QMessageBox.information(self, "新建物品",
            f"已在空槽 #{target['index']} 创建新物品\n"
            f"初始 item_id={new_id} (请改为你想要的值)\n"
            f"请填写 名称代码/说明代码/其他属性, 然后 Ctrl+S 保存.")
        self.status_var.setText(f"新建物品: #{target['index']} item_id={new_id}")

    # ── 保存/导出 ──
    def _save(self):
        if not self.item_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        reply = QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.item_path}\n\n原文件将被覆盖 (生成 .bak).")
        if reply != QMessageBox.Yes: return
        try:
            with open(self.item_path, 'rb') as s:
                with open(self.item_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.setText("正在保存…")
            save_items(self.item_path, self.records); self._dirty = False
            self.status_var.setText(f"已保存 → {self.item_path}")
            QMessageBox.information(self, "保存成功", f"已保存\n备份: {self.item_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p, _ = QFileDialog.getSaveFileName(self, "导出CSV", "", "CSV (*.csv)")
        if not p: return
        with open(p, 'w', encoding='utf-8-sig', newline='') as f:
            hdr = ['索引'] + [fl for _, _, fl, _, _, _ in ALL_FIELDS]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                row = [str(rec['index'])] + [str(rec[fn]) for fn, _, _, _, _, _ in ALL_FIELDS]
                f.write(','.join(row) + '\n')
        self.status_var.setText(f"已导出: {p}")

    # ── 帮助 ──
    def _show_field_ref(self):
        lines = ["TKItem.dat 字段映射 v3.0 (反编译 + Maker.exe TksModify.dll 实证):", ""]
        lines.append("【基础属性 (Maker UI 可见字段 22 条)】")
        for fn, fo, fl, ft, fw, cmt in GRID_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("【技能 (Maker UI 4 字段)】")
        for fn, fo, fl, cmt in SKILL_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("【导致状态 (Maker UI; 战斗时读取角色 a2[67]/a2[68])】")
        for fn, fo, fl, cmt in CAUSE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("【解除状态 (sub_41E40C 使用物品时清除)】")
        for fn, fo, fl, cmt in CURE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("【隐含数据 (Maker UI 未显示, 但 TKItem 记录占用)】")
        for fn, fo, fl, ft, fw, cmt in HIDDEN_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("【使用权限 (equip_type) 实测值】")
        for page, opts in sorted(USE_RIGHT_OPTIONS.items()):
            lines.append(f"  页面{page}({PAGE_NAMES.get(page,'?')}): {opts}")
        lines.append(""); lines.append("【记录数硬限制】")
        lines.append("  600 条 x 64 字节 = 38400 字节 (sub_45343C 固定加载量)")
        lines.append("  sub_42F8D4 搜索循环 `while (v3 < 600)` 是硬编码")
        lines.append("  #560-#599 (40条) 为真空槽, 可用于新增物品 (item_id=0, name_id=0)")
        dlg = QDialog(self); dlg.setWindowTitle("字段来源 v3.0 (逆向+Maker 实证)"); dlg.resize(820, 580)
        layout = QVBoxLayout(dlg)
        from PySide6.QtWidgets import QTextEdit
        tx = QTextEdit(); tx.setReadOnly(True); tx.setPlainText('\n'.join(lines))
        tx.setStyleSheet("font-family: 'Consolas', 'Courier New', monospace; font-size: 9pt;")
        layout.addWidget(tx)
        dlg.exec()

    def _show_about(self):
        QMessageBox.about(self, "关于",
            "TKItem.dat 可视化编辑器 v2.0 (PySide6)\n\n"
            "基于《三国群侠传》 TKS.exe 反编译 + Maker.exe TksModify.dll 文案对照\n"
            "600 条记录 x 32 字段 (int16 x 32 = 64 字节)\n\n"
            "核心反编译函数:\n"
            "  sub_45343C  数据载入 (硬编码 38400 字节)\n"
            "  sub_41E40C  物品使用 (药品 / 使用后学习技能 / 解除状态)\n"
            "  sub_42234C  装备应用 (装备后学习技能 / 导致状态)\n"
            "  sub_422BBC  附加技能 type=1/2/3 效果展开\n"
            "  sub_42F8D4  物品查找 (< 600 循环)\n"
            "  sub_424A2C  背包/商店显示")

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存", "有未保存的修改, 确定退出?")
            if reply == QMessageBox.No:
                event.ignore(); return
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    editor = ItemEditorApp()
    editor.show()
    sys.exit(app.exec())