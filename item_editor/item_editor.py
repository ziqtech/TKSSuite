#!/usr/bin/env python3
"""
TKItem.dat 可视化编辑器 v2.2 (对照 Maker.exe UI 布局)

记录结构: 32 x int16 = 64 字节, 共 600 条. 基址 word_77CBCA, 索引步长 32 字.

【字段映射实测验证】通过实际读取六破散 (record #19) 反推 Maker UI 字段位置:
  六破散 desc: "非常狠毒的毒藥，中毒者五感皆痺、內息散亂…"
    offset 52 = 0x001F -> 破兵/碎甲/昏眩/封锁/羁绊 (导致状态 mask1)
    offset 58 = 0x2000 -> 明镜                    (解除状态 mask2)

因此 Maker UI 字段位置 (与 TKS.exe 代码变量名不直接对应):
  [44] v15[22]   Maker UI 未显示 (sub_42234C 单选; 本编辑器作为隐含字段透传)
  [52] v15[26]   UI "导致状态 1-16"  (位掩码, bit i = 状态 i)
  [54] v15[27]   UI "导致状态 17-32" (位掩码, bit i = 状态 16+i)
  [56] v15[28]   UI "解除状态 1-16"  (位掩码)
  [58] v15[29]   UI "解除状态 17-32" (位掩码)

其他字段 (按字节偏移, int16 索引 = offset/2):
  [0]  item_id         物品代码 (10000=金钱)
  [2]  page_code       页面号/商店过滤键
  [4]  name_id         名称 TKT 代码
  [6]  desc_id         说明 TKT 代码
  [8]  image           形象/图标
  [10] use_right       使用权限/装备类型
  [12] battle_anim     战场动画
  [14] hp_bonus        增加生命
  [16] hp_heal         恢复生命
  [18] mp_bonus        增加内力
  [20] mp_heal         恢复内力
  [22] atk             增加攻击
  [24] def_            增加防御
  [26] hit             增加命中
  [28] dodge           增加闪避
  [30] speed           增加速度
  [32] luck            增加幸运
  [34] spirit          增加悟性
  [36] vitality        增加体力
  [38] jp_bonus        增加JP
  [40] ring_flag       戒指判定/位掩码
  [42] attach_skill    附加技能 (sub_422BBC)
  [46] learn_skill1    装备后学习技能 1 (byte_757FB8)
  [48] learn_skill2    装备后学习技能 2
  [50] medicine        增加医术
  [60] combat_flag     战斗相关判断
  [62] price           价格
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
# 常量 (逆向 sub_41E40C / sub_42234C + Maker.exe TksModify.dll 字符串)
# ============================================================
# 状态名 (31 种, 取自 Maker.exe TksModify.dll; 含两个"连计")
# 状态索引 0..30 = Maker UI 列表索引
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

# 使用权限 (逆向未枚举, 沿用装备类型经验值)
USE_RIGHT = {0:"消耗/书籍", 1:"近战武器", 2:"远程武器", 3:"防具", 4:"饰品",
             8:"特殊8", 16:"特殊16", 32:"特殊32", 64:"特殊64", 128:"特殊128"}
USE_RIGHT_VALUES = [f"{k}-{v}" for k,v in sorted(USE_RIGHT.items())]

# 页面号 (商店分页, 游戏内 6 类)
PAGE_NAMES = {0:"消耗品", 1:"书籍", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
PAGE_VALUES = [f"{k}-{v}" for k,v in sorted(PAGE_NAMES.items())]

ITEM_REC = 64; ITEM_CNT = 600
FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)

# 统一编辑控件宽度 (问题 4: 每个输入框/下拉框宽度保持一致)
W_INPUT = 12  # Entry / Combobox 统一宽度

# 顶部基础属性网格 (对照 Maker.exe 修改器 5 列布局)
# (键名, 偏移, 标签, 类型, 宽度, 逆向注释)
GRID_FIELDS = [
    ("item_id",      0, "物品代码",       'int',       W_INPUT, "v15[0] 物品ID; 10000=金钱(sub_40CE30)"),
    ("page_code",    2, "页面号",         'page',      W_INPUT, "v15[1] 商店页(word_77CBCC, sub_4246D8)"),
    ("name_id",      4, "名称代码",       'tkt',       W_INPUT, "v15[2] TKT.dat 文本 ID (word_77CBCE)"),
    ("desc_id",      6, "说明代码",       'tkt',       W_INPUT, "v15[3] TKT 说明文本 ID"),
    ("image",        8, "形象",           'int',       W_INPUT, "v15[4] 图标 (word_77CBD2)"),

    ("use_right",   10, "使用权限",       'use_right', W_INPUT, "v15[5] 装备类型/槽位限制"),
    ("battle_anim", 12, "战场动画",       'int',       W_INPUT, "v15[6] 战斗特效动画"),
    ("hp_bonus",    14, "增加生命",       'int',       W_INPUT, "v15[7] HP 上限+值;>1000=百分比(sub_41E40C)"),
    ("hp_heal",     16, "恢复生命",       'int',       W_INPUT, "v15[8] 当前 HP 回复"),
    ("mp_bonus",    18, "增加内力",       'int',       W_INPUT, "v15[9] MP 上限+值;同百分比规则"),

    ("mp_heal",     20, "恢复内力",       'int',       W_INPUT, "v15[10] 当前 MP 回复"),
    ("atk",         22, "增加攻击",       'int',       W_INPUT, "v15[11] word_757F1E +="),
    ("def_",        24, "增加防御",       'int',       W_INPUT, "v15[12] word_757F22 +="),
    ("hit",         26, "增加命中",       'int',       W_INPUT, "v15[13] word_757F26 +="),
    ("dodge",       28, "增加闪避",       'int',       W_INPUT, "v15[14] word_757F2A +="),

    ("speed",       30, "增加速度",       'int',       W_INPUT, "v15[15] word_757F2E +="),
    ("luck",        32, "增加幸运",       'int',       W_INPUT, "v15[16] word_757F32 +="),
    ("spirit",      34, "增加悟性",       'int',       W_INPUT, "v15[17] word_757F3A +="),
    ("vitality",    36, "增加体力",       'int',       W_INPUT, "v15[18] word_757F36 +="),
    ("jp_bonus",    38, "增加JP",         'int',       W_INPUT, "v15[19] word_757F46 += (sub_41E40C)"),

    ("ring_flag",   40, "戒指判定",       'int',       W_INPUT, "v15[20] 位掩码 a2[33]|=v9[20]"),
    ("medicine",    50, "增加医术",       'int',       W_INPUT, "v15[25] word_75688A += (sub_41E40C)"),
    ("combat_flag", 60, "战斗相关判断",   'int',       W_INPUT, "v15[30] dword_755C80|= (sub_41F784)"),
    ("price",       62, "价格",           'int',       W_INPUT, "v15[31] word_77CC08 买卖价"),
]

# 附加技能组 (按 Maker UI 命名: 附加技能 / 装备后学习技能 1 / 2)
SKILL_FIELDS = [
    ("attach_skill", 42, "附加技能",         "v15[21] sub_422BBC 装备时附加的技能 (主动/被动)"),
    ("learn_skill1", 46, "装备后学习技能1",  "v15[23] byte_757FB8[v15[23]]=10 (装备/使用时学会)"),
    ("learn_skill2", 48, "装备后学习技能2",  "v15[24] byte_757FB8[v15[24]]=10 (装备/使用时学会)"),
]

# 隐含数据字段 (Maker UI 未显示, 但 TKItem 记录仍占用; 保留读写以免丢数据)
# v15[22] offset 44: 实测六破散此字段=0, 非"导致状态"单选. sub_42234C 中按 byte 偏移写入
#                    角色状态区; Maker 修改器未在 UI 中暴露编辑, 故作为隐含字段透传.
HIDDEN_FIELDS = [
    ("_u22", 44, "保留 v15[22]", 'int', W_INPUT, "v15[22] sub_42234C byte offset (Maker UI 未显示)"),
]

# 导致状态 (2 x 16 位掩码, v15[26]/v15[27] offset 52/54) —— 实测验证, Maker UI 标签
CAUSE_MASK_FIELDS = [
    ("cause_mask1", 52, "导致状态 1-16",  "v15[26] mask bit i -> 状态 i (六破散=0x001F 破兵..羁绊)"),
    ("cause_mask2", 54, "导致状态 17-32", "v15[27] mask bit i -> 状态 16+i"),
]

# 解除状态 (2 x 16 位掩码, v15[28]/v15[29] offset 56/58) —— 实测验证, Maker UI 标签
CURE_MASK_FIELDS = [
    ("cure_mask1", 56, "解除状态 1-16",  "v15[28] mask bit i -> 状态 i"),
    ("cure_mask2", 58, "解除状态 17-32", "v15[29] mask bit i -> 状态 16+i (六破散=0x2000 明镜)"),
]

ALL_FIELDS = (GRID_FIELDS + HIDDEN_FIELDS +
              [(k,o,l,'skill',W_INPUT,c) for k,o,l,c in SKILL_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CAUSE_MASK_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CURE_MASK_FIELDS])

def is_empty_item(rec):
    """占位空槽: item_id == 0 或 1 (惯用, sub_40CE30 以 word_77CBCA 起列表匹配)."""
    return rec['item_id'] == 0 or rec['item_id'] == 1

def item_display_name(rec, tkt):
    if is_empty_item(rec):
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
        # 按每字段声明的字节偏移读取 (fo//2 = int16 索引)
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
# GUI
# ============================================================
class ItemEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKItem.dat 可视化编辑器 v2.2 (对照 Maker.exe UI 布局)")
        self.root.geometry("1320x760"); self.root.minsize(1100, 620)
        self.item_path = self.tkt_path = self.skill_path = None
        self.records = []; self.tkt = {}; self.skill_names = {}
        self.filtered_indices = []; self._dirty = False
        self.filter_page = tk.StringVar(value="全部页面")
        self.filter_right = tk.StringVar(value="全部权限")
        self.filter_empty = tk.BooleanVar(value=True)
        self._build_ui(); self._set_edit_enabled(False)

    # ----------- UI 构建 -----------
    def _build_ui(self):
        # 菜单
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator(); fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段来源", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())

        # 工具栏
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
                     state='readonly', width=13).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(tb, text="仅非空", variable=self.filter_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=6)
        self.filter_page.trace_add('write', lambda *a: self._apply_filter())
        self.filter_right.trace_add('write', lambda *a: self._apply_filter())
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # 主分栏
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧表格
        lf = ttk.Frame(paned); paned.add(lf, weight=2)
        cols = ('index','item_id','page','name','right','price')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [('index','#',40),('item_id','ID',50),('page','页面',55),
              ('name','物品名称',220),('right','权限',55),('price','价格',55)]
        for cid,cn,cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧编辑区
        rf = ttk.Frame(paned); paned.add(rf, weight=3)
        self.edit_frame = rf

        # 记录头
        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0,4), padx=4)

        # 可滚动编辑容器
        canvas = tk.Canvas(rf, highlightthickness=0)
        sb = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=canvas.yview)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}; self._edit_extras = {}

        # --- 名称/说明文本预览区 (问题 5: 独立预览, 不在下拉框下 inline) ---
        pv_lf = ttk.LabelFrame(self.edit_inner, text="文本预览 (TKT.dat)", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        pv_lf.columnconfigure(1, weight=1)
        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground='#666').grid(
            row=0, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=680, justify='left')
        self.preview_name.grid(row=0, column=1, sticky='ew', pady=1)
        ttk.Label(pv_lf, text="说明:", font=FONT_S, foreground='#666').grid(
            row=1, column=0, sticky='nw', padx=(2,4), pady=1)
        self.preview_desc = ttk.Label(pv_lf, text="(未选中)", foreground='#228B22',
                                       font=FONT, wraplength=680, justify='left')
        self.preview_desc.grid(row=1, column=1, sticky='ew', pady=1)

        # --- 基础属性网格 (对照修改器图: 5列) ---
        grid_lf = ttk.LabelFrame(self.edit_inner, text="基础属性 (Maker.exe 布局)", padding=4)
        grid_lf.grid(row=1, column=0, sticky='ew', padx=2, pady=2)
        COLS = 5
        for fi, (fn, fo, fl, ft, fw, cmt) in enumerate(GRID_FIELDS):
            row, col = fi // COLS, fi % COLS
            self._build_field(grid_lf, row, col, fn, fo, fl, ft, fw, cmt)

        # --- 状态组 (Maker UI 实测: 导致=52/54 mask, 解除=56/58 mask, 各 2 个 mask) ---
        st_lf = ttk.LabelFrame(self.edit_inner,
                                text="状态 (位掩码; bit i = 对应状态名)", padding=4)
        st_lf.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        for ci, (fn, fo, fl, cmt) in enumerate(CAUSE_MASK_FIELDS):
            self._build_field(st_lf, 0, ci, fn, fo, fl, 'mask', W_INPUT, cmt)
        for ci, (fn, fo, fl, cmt) in enumerate(CURE_MASK_FIELDS):
            self._build_field(st_lf, 0, 2+ci, fn, fo, fl, 'mask', W_INPUT, cmt)

        # --- 附加技能组 (3 条技能字段) ---
        sk_lf = ttk.LabelFrame(self.edit_inner,
                                text="技能 (sub_422BBC / byte_757FB8)", padding=4)
        sk_lf.grid(row=3, column=0, sticky='ew', padx=2, pady=2)
        for si, (fn, fo, fl, cmt) in enumerate(SKILL_FIELDS):
            self._build_field(sk_lf, 0, si, fn, fo, fl, 'skill', W_INPUT, cmt)

        # 注: 原"装备防御"分组已按需求 6 移除. v15[26]/v15[27] 数据仍读写
        #     (见 HIDDEN_FIELDS), 但不暴露编辑 UI, 避免混淆.
        # 为 HIDDEN_FIELDS 预创建 StringVar, 让 load/save 能透传原始数据
        for fn, _fo, _fl, _ft, _fw, _cmt in HIDDEN_FIELDS:
            self._edit_vars[fn] = tk.StringVar()

        # --- 按钮条 ---
        bf = ttk.Frame(self.edit_inner)
        bf.grid(row=4, column=0, sticky='ew', pady=(8,0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        ttk.Button(bf, text="复制到空槽", command=self._copy_record).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit).pack(side=tk.LEFT, padx=2)

        # 底部路径栏
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_item = ttk.Label(pf, text="", foreground="gray"); self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray"); self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray"); self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field(self, parent, row, col, fn, fo, fl, ft, fw, cmt):
        """根据类型构建单个字段编辑控件. 所有控件统一使用 W_INPUT 宽度 (问题 4)."""
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        # 标签 (含 tooltip)
        lbl = ttk.Label(frm, text=fl, font=FONT_S)
        lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        if ft == 'page':
            cb = ttk.Combobox(frm, state='readonly', values=PAGE_VALUES,
                              width=W_INPUT, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'use_right':
            cb = ttk.Combobox(frm, state='readonly', values=USE_RIGHT_VALUES,
                              width=W_INPUT, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'tkt':
            # 问题 5: 不在下拉框下显示 inline 文本; 文本预览区统一渲染
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=W_INPUT, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_tkt(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = None  # 占位, populate 时不写 inline
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
            # 导致/解除状态 统一 mask 类型; 按字段名决定按钮文案 & 标签颜色
            is_cause = fn.startswith('cause_')
            btn_text = "选择导致状态…" if is_cause else "选择解除状态…"
            color = '#CC3333' if is_cause else '#3366cc'
            ttk.Button(frm, text=btn_text, width=W_INPUT+3,
                       command=lambda f=fn: self._pick_status(f)).pack(fill=tk.X)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground=color,
                                              font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        else:  # int
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(frm, textvariable=ev, width=W_INPUT, font=FONT).pack(fill=tk.X)

    # ----------- Tooltip -----------
    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10; y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget); w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=380, padding=3).pack()
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
            if self.filter_empty.get() and is_empty_item(rec): continue
            if fpg and not fpg.startswith("全部"):
                if rec['page_code'] != int(fpg.split('-')[0]): continue
            if frg and not frg.startswith("全部"):
                if rec['use_right'] != int(frg.split('-')[0]): continue
            if q:
                nm = item_display_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['item_id']} {rec['page_code']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        self.status_var.set(f"显示 {len(self.filtered_indices)}/{len(self.records)} | Ctrl+S 保存")

    def _clear_filter(self):
        self.sv.set(""); self.filter_page.set("全部页面")
        self.filter_right.set("全部权限"); self.filter_empty.set(True)
        self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        rt_short = {0:"消耗",1:"近战",2:"远程",3:"防具",4:"饰品"}
        for idx in self.filtered_indices:
            r = self.records[idx]
            rt = rt_short.get(r['use_right'], f"#{r['use_right']}") if r['use_right'] else "—"
            self.tree.insert('', 'end', values=(
                r['index'], r['item_id'],
                PAGE_NAMES.get(r['page_code'], '?'),
                item_display_name(r, self.tkt),
                rt, r['price']))

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        km = {'item_id':'item_id', 'page':'page_code', 'price':'price', 'right':'use_right'}
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
            f"页面号={PAGE_NAMES.get(rec['page_code'],'?')}   "
            f"名称={item_display_name(rec, self.tkt)}"
        ))
        # 预览区: 名称/说明完整文本 (问题 5)
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
                # 不再渲染 inline 文本, 已移动到顶部预览区
                pass
            elif ft == 'skill':
                sid = int(val) if val else -1
                nm = self.skill_names.get(sid, "(无)")
                self._edit_extras[fn].config(text=nm[:30] if sid >= 0 else "(无)")
            elif ft == 'mask':
                # 导致/解除状态 mask 摘要
                self._update_status_label(fn, int(val) if val else 0)

    def _set_combobox(self, cb, val):
        for i, t in enumerate(cb['values']):
            if t.startswith(f"{val}-"): cb.current(i); return True
        return False

    def _update_status_label(self, fn, mask):
        """导致/解除 状态 mask 摘要: *_mask1 对应状态 0-15, *_mask2 对应 16-30."""
        base = 0 if fn.endswith('_mask1') else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    # ----------- 弹窗: 导致/解除 状态 mask 多选 -----------
    def _pick_status(self, fn):
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = tk.Toplevel(self.root); dlg.title(title)
        dlg.geometry("360x480"); dlg.transient(self.root); dlg.grab_set()
        base = 0 if fn.endswith('_mask1') else 16
        cur_mask = int(self._edit_vars[fn].get() or 0)
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
            self._edit_vars[fn].set(str(m)); self._update_status_label(fn, m); dlg.destroy()
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
                # 更新顶部预览区 (问题 5)
                try:
                    tid = int(v[0]); txt = self.tkt.get(tid, "")
                    if fn == 'name_id':
                        self.preview_name.config(text=txt if txt else "(无 / TKT 未提供)")
                    elif fn == 'desc_id':
                        self.preview_desc.config(text=txt if txt else "(无 / TKT 未提供)")
                except Exception:
                    pass
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
                    # int16 范围保护
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

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'): return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_empty_item(rec):
                for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
                    rec[fn] = src[fn]
                rec['index'] = i
                rec['item_id'] = 0
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == i:
                        self.tree.selection_set(child); self.tree.see(child); break
                self.status_var.set(f"已复制到空槽 #{i}")
                return
        messagebox.showwarning("已满", "600 条记录无空槽")

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
        lines = ["TKItem.dat 字段映射 (实测六破散 + Maker.exe UI 对照):", ""]
        lines.append("顶部基础属性网格 (对照 Maker.exe 修改器布局):")
        for fn, fo, fl, ft, fw, cmt in GRID_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("导致状态 mask (实测: 六破散 offset 52 = 0x001F):")
        for fn, fo, fl, cmt in CAUSE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("解除状态 mask (实测: 六破散 offset 58 = 0x2000 明镜):")
        for fn, fo, fl, cmt in CURE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("技能组:")
        for fn, fo, fl, cmt in SKILL_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append(""); lines.append("隐含数据 (Maker 未显 UI, 但 TKItem 记录保留):")
        for fn, fo, fl, ft, fw, cmt in HIDDEN_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")

        dlg = tk.Toplevel(self.root); dlg.title("字段来源 (逆向佐证)")
        dlg.geometry("780x540"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='none')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        sb2 = ttk.Scrollbar(dlg, orient=tk.HORIZONTAL, command=tx.xview)
        tx.configure(yscrollcommand=sb1.set, xscrollcommand=sb2.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y); sb2.pack(side=tk.BOTTOM, fill=tk.X)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKItem.dat 可视化编辑器 v2.2\n\n"
            "基于《三国群侠传》 TKS.exe 逆向 + Maker.exe 修改器布局对照开发\n"
            "600 条记录 x 32 字段\n\n"
            "核心依据: sub_45343C 装载, sub_41E40C 使用, sub_42234C 装备,\n"
            "sub_424A2C 显示, sub_4246D8 商店过滤, sub_41F784 战斗标志"
        )


def main():
    root = tk.Tk(); ItemEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
