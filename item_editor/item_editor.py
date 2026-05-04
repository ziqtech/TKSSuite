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
  9. 使用权限 (equip_type) 值语义实测:
     0=饰品/坐骑(111条), 1=消耗品/刀(39条), 2=书籍(97条), 3=药品(26条), 4=特殊(18条),
     8=矛(8条), 16=弓弩(12条), 32=大刀(12条), 64=戟(6条), 128=锤(6条)
 10. 记录数硬限制: 600 条 (sub_45343C 加载 38400 字节 = 600x64; sub_42F8D4 遍历 < 600)
 11. 空槽 (40 条可新增物品): #560-#599, item_id=0 & name_id=0 & desc_id=600
"""

import struct, os, tkinter as tk
from tkinter import ttk, messagebox, filedialog

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
    src = data; sl = len(src); w = bytearray([0x20]*4096); wp = 4078
    tokens = []; pos = 0
    while pos < sl:
        bl, bo = 0, 0; ms = min(18, sl - pos)
        for length in range(ms, 2, -1):
            if bl >= length: break
            pat = src[pos:pos+length]
            for off in range(4096):
                ok = True
                for j in range(length):
                    if w[(off+j)&0xFFF] != pat[j]: ok = False; break
                if ok: bl = length; bo = off; break
            if bl >= length: break
        if bl >= 3:
            if wp <= bo + bl: bl = wp - bo
            if bl >= 3:
                tokens.append((False, bo, bl))
                for j in range(bl): w[wp] = src[pos+j]; wp = (wp+1)&0xFFF
                pos += bl; continue
        tokens.append((True, src[pos], 0))
        w[wp] = src[pos]; wp = (wp+1)&0xFFF; pos += 1
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
# 常量 (Maker.exe TksModify.dll 文案 + TKS.exe 反编译)
# ============================================================
# 31 种状态 (bit 0..30; Maker UI 状态列表)
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

# 使用权限 (equip_type) 实测值语义 — 2026-05 probe 数据完全匹配用户观察
#  sub_41928C: word_77CBD4[32 * item_idx] & word_757FA4[527 * char_idx] 作位与权限校验
USE_RIGHT = {
    0:   "饰品/坐骑",
    1:   "消耗品/刀",
    2:   "书籍",
    3:   "药品",
    4:   "特殊",
    8:   "矛类武器",
    16:  "弓弩武器",
    32:  "大刀类武器",
    64:  "戟类武器",
    128: "锤类武器",
}
USE_RIGHT_VALUES = [f"{k}-{v}" for k,v in sorted(USE_RIGHT.items())]

# 页面号 (tab_code, Maker UI 未显示; 商店分页, 0-5)
PAGE_NAMES = {0:"消耗品", 1:"书籍", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
PAGE_VALUES = [f"{k}-{v}" for k,v in sorted(PAGE_NAMES.items())]

ITEM_REC = 64; ITEM_CNT = 600  # 游戏硬编码: sub_45343C(aTkitemDat, word_77CBCA, 38400)
FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ============================================================
# 字段定义 - 严格按 Maker UI 文案 + 反编译证据
# (键, 字节偏移, UI标签, 类型, 宽度, 反编译注释)
# ============================================================
# 顶部基础属性网格 (Maker UI 可见字段 22 条; 技能/状态在下方分组)
GRID_FIELDS = [
    ("item_id",      0, "物品代码",       'int',       W_INPUT, "v15[0] sub_40CE30 查找主键"),
    ("name_id",      4, "名称代码",       'tkt',       W_INPUT, "v15[2] TKT 文本 ID (word_77CBCE)"),
    ("desc_id",      6, "说明代码",       'tkt',       W_INPUT, "v15[3] TKT 说明 ID (word_77CBD0)"),
    ("icon",         8, "形象",           'int',       W_INPUT, "v15[4] 图标索引 +130"),
    ("equip_type",  10, "使用权限",       'use_right', W_INPUT, "v15[5] 装备/使用位标志"),

    ("battle_anim", 12, "战场动画",       'int',       W_INPUT, "v15[6] 武器攻击范围/动画"),
    ("hp_inc",      14, "增加生命",       'int',       W_INPUT, "v15[7] HP上限; >1000=百分比"),
    ("hp_heal",     16, "恢复生命",       'int',       W_INPUT, "v15[8] 当前HP回复; >1000=百分比"),
    ("mp_inc",      18, "增加内力",       'int',       W_INPUT, "v15[9] MP上限; >1000=百分比"),
    ("mp_heal",     20, "恢复内力",       'int',       W_INPUT, "v15[10] 当前MP回复; >1000=百分比"),

    ("atk",         22, "增加攻击",       'int',       W_INPUT, "v15[11] STR(武力) word_757F1E +="),
    ("def_",        24, "增加防御",       'int',       W_INPUT, "v15[12] INT(智力) word_757F22 +="),
    ("hit",         26, "增加命中",       'int',       W_INPUT, "v15[13] CMD(统御) word_757F26 +="),
    ("dodge",       28, "增加闪避",       'int',       W_INPUT, "v15[14] AGI(敏捷) word_757F2A +="),
    ("spd",         30, "增加速度",       'int',       W_INPUT, "v15[15] SPD word_757F2E +=, 上限100"),

    ("luk",         32, "增加幸运",       'int',       W_INPUT, "v15[16] LUK word_757F32 +=, 商店条件基准"),
    ("spi",         34, "增加悟性",       'int',       W_INPUT, "v15[17] SPI word_757F3A +="),
    ("vit",         36, "增加移动",       'int',       W_INPUT, "v15[18] VIT word_757F36 +="),
    ("ring_flag",   38, "戒指判定",       'int',       W_INPUT, "v15[19] word_757F46 +="),
    ("combat_flag", 40, "战斗相关判定",   'int',       W_INPUT, "v15[20] word_757F4A |=, a2[33] |="),

    ("medicine",    50, "增加医术",       'int',       W_INPUT, "v15[25] word_75688A += (Maker UI 文案)"),
    ("price",       62, "价格",           'int',       W_INPUT, "v15[31] word_77CC08 买卖价"),
]

# 技能组 (Maker UI 4 个独立字段; 全部对应 byte_757FB8 全局技能等级表, 等级 10)
SKILL_FIELDS = [
    ("attach_skill",    42, "附加技能",         "v15[21] sub_422BBC 装备时应用 skill type=1/2/3 效果"),
    ("equip_learn",     44, "装备后学习技能",   "v15[22] sub_42234C 装备时 byte_757FB8[1054*char+v15[22]]=10"),
    ("use_learn1",      46, "使用后学习技能1",  "v15[23] sub_41E40C 使用时 byte_757FB8[1054*char+v15[23]]=10"),
    ("use_learn2",      48, "使用后学习技能2",  "v15[24] sub_41E40C 使用时 byte_757FB8[1054*char+v15[24]]=10"),
]

# 导致状态 (v15[26]/v15[27] offset 52/54; Maker UI "导致状态 1-16 / 17-32")
# 装备时 sub_42234C: a2[67]=v9[26], a2[68]=v9[27] (战斗代码读取 a2[67]/a2[68] 作状态 mask)
# 实测验证: 干將莫邪[26]=0x03(破兵+碎甲); 紅顏知己[27]=0x1000(迷恋); 大骨鎚[27]=0xC(禁制+定身)
CAUSE_MASK_FIELDS = [
    ("cause_mask1", 52, "导致状态 1-16",  "v15[26] a2[67]=v9[26] 战斗时作 mask bit i -> 状态 i"),
    ("cause_mask2", 54, "导致状态 17-32", "v15[27] a2[68]=v9[27] 战斗时作 mask bit i -> 状态 16+i"),
]

# 解除状态 (v15[28]/v15[29] offset 56/58; sub_41E40C 使用时按位清除角色状态)
CURE_MASK_FIELDS = [
    ("cure_mask1", 56, "解除状态 1-16",  "v15[28] (v15[28] & (1<<(s-1))) 清除状态 1-16"),
    ("cure_mask2", 58, "解除状态 17-32", "v15[29] (v15[29] & (1<<(s-17))) 清除状态 17-32"),
]

# 隐含字段 (Maker UI 未显示, 但 TKItem 记录占用; 读写透传)
HIDDEN_FIELDS = [
    ("tab_code",     2, "页面号",       'page', W_INPUT, "v15[1] 商店分页 (sub_4246D8)"),
    ("extra_flags", 60, "额外标志",     'int',  W_INPUT, "v15[30] word_77CC06 OR-> dword_755C80 (sub_41F784)"),
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
    if rec.get('item_id', 0) in (0, 1): return True
    if rec.get('name_id', 0) <= 0: return True
    if tkt is not None:
        nm = tkt.get(rec['name_id'], "")
        if not nm or not nm.strip(): return True
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
    # 空槽模板 (#560-#599 原始值: name_id=0, desc_id=600) 在保存时保持 desc_id=600
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
# GUI
# ============================================================
class ItemEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKItem.dat 可视化编辑器 v3.0 (对照 Maker.exe TksModify.dll)")
        self.root.geometry("1360x780"); self.root.minsize(1120, 640)
        self.item_path = self.tkt_path = self.skill_path = None
        self.records = []; self.tkt = {}; self.skill_names = {}
        self.filtered_indices = []; self._dirty = False
        self.filter_page = tk.StringVar(value="全部页面")
        self.filter_right = tk.StringVar(value="全部权限")
        self.filter_empty = tk.BooleanVar(value=True)
        self._build_ui(); self._set_edit_enabled(False)

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

        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=18); e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(tb, text="页面号:").pack(side=tk.LEFT)
        ttk.Combobox(tb, textvariable=self.filter_page, values=["全部页面"]+PAGE_VALUES,
                     state='readonly', width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(tb, text="权限:").pack(side=tk.LEFT, padx=(6,0))
        ttk.Combobox(tb, textvariable=self.filter_right, values=["全部权限"]+USE_RIGHT_VALUES,
                     state='readonly', width=16).pack(side=tk.LEFT, padx=2)
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

        # 左表
        lf = ttk.Frame(paned); paned.add(lf, weight=2)
        cols = ('index','item_id','page','name','right','price')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [('index','#',40),('item_id','ID',50),('page','页面',55),
              ('name','物品名称',220),('right','权限',90),('price','价格',55)]
        for cid,cn,cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右编辑
        rf = ttk.Frame(paned); paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0,4), padx=4)

        canvas = tk.Canvas(rf, highlightthickness=0)
        sb = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=canvas.yview)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}; self._edit_extras = {}

        # 文本预览
        pv_lf = ttk.LabelFrame(self.edit_inner, text="文本预览 (TKT.dat)", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        pv_lf.columnconfigure(1, weight=1)
        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground='#666').grid(
            row=0, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=700, justify='left')
        self.preview_name.grid(row=0, column=1, sticky='ew', pady=1)
        ttk.Label(pv_lf, text="说明:", font=FONT_S, foreground='#666').grid(
            row=1, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_desc = ttk.Label(pv_lf, text="(未选中)", foreground='#228B22',
                                       font=FONT, wraplength=700, justify='left')
        self.preview_desc.grid(row=1, column=1, sticky='ew', pady=1)

        # 基础属性网格
        grid_lf = ttk.LabelFrame(self.edit_inner, text="基础属性 (Maker.exe UI 布局)", padding=4)
        grid_lf.grid(row=1, column=0, sticky='ew', padx=2, pady=2)
        COLS = 5
        for fi, (fn, fo, fl, ft, fw, cmt) in enumerate(GRID_FIELDS):
            row, col = fi // COLS, fi % COLS
            self._build_field(grid_lf, row, col, fn, fo, fl, ft, fw, cmt)

        # 技能组 (4 字段)
        sk_lf = ttk.LabelFrame(self.edit_inner,
                                text="技能 (Maker UI 4 字段; sub_422BBC / byte_757FB8)", padding=4)
        sk_lf.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        for si, (fn, fo, fl, cmt) in enumerate(SKILL_FIELDS):
            self._build_field(sk_lf, 0, si, fn, fo, fl, 'skill', W_INPUT, cmt)

        # 状态组
        st_lf = ttk.LabelFrame(self.edit_inner,
                                text="状态位掩码 (Maker UI 导致/解除; bit i = 状态表第 i 项)", padding=4)
        st_lf.grid(row=3, column=0, sticky='ew', padx=2, pady=2)
        for ci, (fn, fo, fl, cmt) in enumerate(CAUSE_MASK_FIELDS):
            self._build_field(st_lf, 0, ci, fn, fo, fl, 'mask', W_INPUT, cmt)
        for ci, (fn, fo, fl, cmt) in enumerate(CURE_MASK_FIELDS):
            self._build_field(st_lf, 0, 2+ci, fn, fo, fl, 'mask', W_INPUT, cmt)

        # 隐含字段
        hd_lf = ttk.LabelFrame(self.edit_inner,
                                text="隐含数据 (Maker UI 未显示, 保留原始数据透传)", padding=4)
        hd_lf.grid(row=4, column=0, sticky='ew', padx=2, pady=2)
        for hi, (fn, fo, fl, ft, fw, cmt) in enumerate(HIDDEN_FIELDS):
            self._build_field(hd_lf, 0, hi, fn, fo, fl, ft, fw, cmt)

        bf = ttk.Frame(self.edit_inner)
        bf.grid(row=5, column=0, sticky='ew', pady=(8,0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        ttk.Button(bf, text="复制到空槽", command=self._copy_record).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="清空此记录", command=self._clear_current).pack(side=tk.LEFT, padx=2)

        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_item = ttk.Label(pf, text="", foreground="gray"); self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray"); self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray"); self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field(self, parent, row, col, fn, fo, fl, ft, fw, cmt):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=fl, font=FONT_S); lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        if ft == 'page':
            cb = ttk.Combobox(frm, state='readonly', values=PAGE_VALUES,
                              width=W_INPUT, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'use_right':
            cb = ttk.Combobox(frm, state='readonly', values=USE_RIGHT_VALUES,
                              width=W_INPUT+3, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'tkt':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_tkt(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = None
        elif ft == 'skill':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
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
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground=color,
                                              font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        else:
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(frm, textvariable=ev, width=W_INPUT, font=FONT).pack(fill=tk.X)

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
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ----------- 数据加载 -----------
    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        it = os.path.join(d, "TKItem.dat")
        tk_ = os.path.join(d, "TKT.dat")
        sk = os.path.join(d, "TKSkill.dat")
        if not os.path.exists(it):
            messagebox.showwarning("文件缺失","未找到 TKItem.dat"); return
        self.item_path = it
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.skill_path = sk if os.path.exists(sk) else None
        self._reload()

    def _reload(self):
        if not self.item_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path: self.tkt = load_tkt(self.tkt_path)
        if self.skill_path: self.skill_names = load_tkskill_names(self.skill_path, self.tkt)
        try:
            self.records = load_items(self.item_path); self._dirty = False
            self.status_var.set(f"{len(self.records)} 条 | TKT {len(self.tkt)} 条 | 技能 {len(self.skill_names)} 条")
        except Exception as e:
            messagebox.showerror("加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children(): self._set_ws(c, en)
    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p):
            if not p: lb.config(text="(未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=p, foreground=g)
        _f(self.lbl_item, self.item_path)
        _f(self.lbl_tkt, self.tkt_path)
        _f(self.lbl_skill, self.skill_path)

    # ----------- 筛选/列表 -----------
    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        fpg = self.filter_page.get(); frg = self.filter_right.get()
        for rec in self.records:
            if self.filter_empty.get() and is_empty_item(rec, self.tkt): continue
            if fpg and not fpg.startswith("全部"):
                if rec['tab_code'] != int(fpg.split('-')[0]): continue
            if frg and not frg.startswith("全部"):
                if rec['equip_type'] != int(frg.split('-')[0]): continue
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
        self.sv.set(""); self.filter_page.set("全部页面")
        self.filter_right.set("全部权限"); self.filter_empty.set(True)
        self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            et = r['equip_type']
            rt = USE_RIGHT.get(et, f"#{et}") if et or et == 0 else "—"
            self.tree.insert('', 'end', values=(
                r['index'], r['item_id'],
                PAGE_NAMES.get(r['tab_code'], '?'),
                item_display_name(r, self.tkt),
                rt, r['price']))

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        km = {'item_id':'item_id', 'page':'tab_code', 'price':'price', 'right':'equip_type'}
        self.filtered_indices.sort(key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ----------- 编辑 -----------
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
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
        n_txt = self.tkt.get(int(nid), "") if nid > 0 else ""
        d_txt = self.tkt.get(int(did), "") if did > 0 else ""
        self.preview_name.config(text=n_txt if n_txt else "(无 / TKT 未提供)")
        self.preview_desc.config(text=d_txt if d_txt else "(无 / TKT 未提供)")

        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            val = rec[fn]; sv = str(val)
            self._edit_vars[fn].set(sv)
            if ft == 'page':
                cb = self._edit_extras[fn]
                if not self._set_combobox(cb, val): cb.set(sv)
            elif ft == 'use_right':
                cb = self._edit_extras[fn]
                if not self._set_combobox(cb, val): cb.set(sv)
            elif ft == 'tkt':
                pass
            elif ft == 'skill':
                sid = int(val) if val else -1
                nm = self.skill_names.get(sid, "(无)")
                self._edit_extras[fn].config(text=nm[:30] if sid > 0 else "(无)")
            elif ft == 'mask':
                self._update_status_label(fn, int(val) if val else 0)

    def _set_combobox(self, cb, val):
        for i, t in enumerate(cb['values']):
            if t.startswith(f"{val}-"): cb.current(i); return True
        return False

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    # ----------- 弹窗: 状态 mask 多选 -----------
    def _pick_status(self, fn):
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = tk.Toplevel(self.root); dlg.title(title)
        dlg.geometry("360x480"); dlg.transient(self.root); dlg.grab_set()
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
            # 转回有符号 int16
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_status_label(fn, m & 0xFFFF); dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 弹窗: TKT -----------
    def _pick_tkt(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择 TKT 文本")
        dlg.geometry("520x500"); dlg.transient(self.root); dlg.grab_set()
        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('id','text'), show='headings', selectmode='browse', height=20)
        tree.heading('id', text='ID'); tree.heading('text', text='文本')
        tree.column('id', width=60, anchor='center'); tree.column('text', width=420, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _refresh(q=""):
            tree.delete(*tree.get_children()); ql = q.strip().lower()
            for eid, txt in sorted(self.tkt.items(), key=lambda x: x[0]):
                if ql and ql not in txt.lower(): continue
                tree.insert('', 'end', values=(eid, txt[:80]))
        _refresh(); qv.trace_add('write', lambda *a: _refresh(qv.get()))
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                try:
                    tid = int(v[0]); txt = self.tkt.get(tid, "")
                    if fn == 'name_id':
                        self.preview_name.config(text=txt if txt else "(无 / TKT 未提供)")
                    elif fn == 'desc_id':
                        self.preview_desc.config(text=txt if txt else "(无 / TKT 未提供)")
                except Exception: pass
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 弹窗: 技能 -----------
    def _pick_skill(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择技能")
        dlg.geometry("460x500"); dlg.transient(self.root); dlg.grab_set()
        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('idx','name'), show='headings', selectmode='browse', height=20)
        tree.heading('idx', text='索引'); tree.heading('name', text='技能名称')
        tree.column('idx', width=50, anchor='center'); tree.column('name', width=380, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _refresh(q=""):
            tree.delete(*tree.get_children()); ql = q.strip().lower()
            for idx, nm in sorted(self.skill_names.items(), key=lambda x: x[0]):
                if ql and ql not in nm.lower(): continue
                tree.insert('', 'end', values=(idx, nm[:60]))
        _refresh(); qv.trace_add('write', lambda *a: _refresh(qv.get()))
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                self._edit_extras[fn].config(text=str(v[1])[:30])
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 编辑应用 -----------
    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            try:
                if ft in ('page', 'use_right'):
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-')[0]) if '-' in sv else int(sv)
                else:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    rec[fn] = v
            except ValueError:
                rec[fn] = 0
        self._dirty = True; self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child); self.tree.see(child); break
        self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    def _clear_current(self):
        """把当前选中记录清为空槽模板 (恢复 #560-599 原始值)."""
        if not hasattr(self, '_editing_idx'):
            messagebox.showinfo("提示", "请先选择一条记录"); return
        if not messagebox.askyesno("确认清空",
            f"将记录 #{self._editing_idx} 清为空槽模板 (item_id=0, name_id=0, desc_id=600).\n确定?"):
            return
        rec = self.records[self._editing_idx]
        for fn, _, _, _, _, _ in ALL_FIELDS:
            rec[fn] = 0
        rec['desc_id'] = 600  # 空槽模板的默认 desc_id
        self._dirty = True
        self._apply_filter(); self._populate_edit(rec)
        self.status_var.set(f"记录 #{self._editing_idx} 已清空")

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'):
            messagebox.showinfo("提示", "请先选择一条记录"); return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_pure_empty_slot(rec):
                for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
                    rec[fn] = src[fn]
                rec['index'] = i
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == i:
                        self.tree.selection_set(child); self.tree.see(child); break
                self.status_var.set(f"已复制到空槽 #{i}")
                return
        messagebox.showwarning("已满", "无真·空槽 (id=0 的记录) 可复制到.\n可先使用『清空此记录』释放一个槽位.")

    def _new_item(self):
        """新增物品: 在空槽 #560-#599 中找第一条 item_id=0 的记录, 填入默认值并选中.
        游戏硬编码限制 600 条, 无法扩容; 但 #560-#599 40 条空槽可用.
        """
        if not self.records:
            messagebox.showinfo("提示", "请先加载 TKItem.dat"); return
        target = None
        for rec in self.records:
            if is_pure_empty_slot(rec):
                target = rec; break
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
                self.tree.selection_set(child); self.tree.see(child); break
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
            messagebox.showinfo("提示", "请先加载数据"); return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.item_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.item_path, 'rb') as s:
                with open(self.item_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            save_items(self.item_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.item_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.item_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
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
        for k, v in sorted(USE_RIGHT.items()):
            lines.append(f"  #{k:<3d}  {v}")
        lines.append(""); lines.append("【记录数硬限制】")
        lines.append("  600 条 x 64 字节 = 38400 字节 (sub_45343C 固定加载量)")
        lines.append("  sub_42F8D4 搜索循环 `while (v3 < 600)` 是硬编码")
        lines.append("  #560-#599 (40条) 为真空槽, 可用于新增物品 (item_id=0, name_id=0)")

        dlg = tk.Toplevel(self.root); dlg.title("字段来源 v3.0 (逆向+Maker 实证)")
        dlg.geometry("820x580"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='none')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        sb2 = ttk.Scrollbar(dlg, orient=tk.HORIZONTAL, command=tx.xview)
        tx.configure(yscrollcommand=sb1.set, xscrollcommand=sb2.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y); sb2.pack(side=tk.BOTTOM, fill=tk.X)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKItem.dat 可视化编辑器 v3.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译 + Maker.exe TksModify.dll 文案对照\n"
            "600 条记录 x 32 字段 (int16 x 32 = 64 字节)\n\n"
            "核心反编译函数:\n"
            "  sub_45343C  数据载入 (硬编码 38400 字节)\n"
            "  sub_41E40C  物品使用 (消耗品 / 使用后学习技能 / 解除状态)\n"
            "  sub_42234C  装备应用 (装备后学习技能 / 导致状态)\n"
            "  sub_422BBC  附加技能 type=1/2/3 效果展开\n"
            "  sub_42F8D4  物品查找 (< 600 循环)\n"
            "  sub_424A2C  背包/商店显示\n\n"
            "v3.0 修正 v2.2 的错误字段映射 (原将 [22] 误标导致状态)"
        )


def main():
    root = tk.Tk(); ItemEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
