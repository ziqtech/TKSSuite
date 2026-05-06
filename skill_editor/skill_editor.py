#!/usr/bin/env python3
"""
TKSkill.dat 可视化编辑器
=============================================================
逆向依据:
  - sub_45343C: DAT 文件统一加载 (LZSS 解压, 94字节/条, 350条)
  - sub_452B14: LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_422BBC: 被动技能属性加成 (type=1/2/3 分支)
  - sub_438F28: 技能列表/技能组层次结构 (sub_count, atk_type)
  - sub_447DAC: 攻击类型判定 (field[46]+1)
  - sub_4458B0: 调整时序 (field[42])
  - sub_438AFC: 图标/消耗资源读取 (field[20],[39],[40],[41])

TKSkill.dat 格式 (每条 94 字节, 共 350 条):
  47 × int16 + 1 × byte @offset 88

用法:
  python skill_editor.py
"""

import struct, os, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# LZSS 编解码 (sub_452B14)
# ============================================================

def lzss_decompress(data):
    """LZSS 解压 — sub_452B14: 4096窗口, 0x20填充, 起始位4078"""
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
    """LZSS 压缩 — sub_452B14 逆向: 4096窗口, 0x20填充, 起始位4078"""
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

def load_tkt_full(tkt_path):
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
            if s and s != '0': lookup[eid] = s.strip()
    return lookup

# ============================================================
# 常量
# ============================================================

SKILL_REC = 94; SKILL_CNT = 350  # sub_45343C: 32900 = 94 × 350

SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_VALUES = [f"{k}-{v}" for k, v in sorted(SKILL_TYPES.items())]

ATK_TYPE_VALUES = ["-1-近战攻击", "0-物理攻击", "1-术法攻击", "10-召唤攻击"]

STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

SPECIAL_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻 (sub_422BBC bit0)"),
    (1, "飙行", "移动范围扩大 (sub_422BBC bit1)"),
    (2, "搜宝", "获得额外宝物 (sub_422BBC bit2)"),
    (3, "解陷", "自动解除陷阱 (sub_422BBC bit3)"),
]

FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ============================================================
# 字段定义 (key, byte_offset, ui_label, field_type, comment)
# ============================================================

BASIC_FIELDS = [
    ("skill_text_id",    0, "技能名称文本ID",     'tkt',     "技能名称 TKT 文本ID (sub_438F28)"),
    ("skill_desc_id",  2, "技能说明文本ID", 'int',     "技能说明 TKT 文本ID = skill_text_id + 400 (sub_438F28)"),
    ("type",        4, "技能类型",   'type',    "sub_422BBC v6[2]: 0=指令 1=主动 2=被动 3=移动"),
    ("jp_cost",     6, "技能点数",   'int',     "学习技能所需点数 (Maker.exe: 学习耗费JP)"),
]

# 技能树引用表: off8-38=8组(改变技能,改变类型)
# 注意: 所有引用值均为技能ID (= 列表中的 # 列), 即 TKSkill.dat 中的记录索引
# Pair 0 约定: type=0→ref_type=20(前组尾链); type=1/2/3→ref_type=10(升级链)
TREE_FIELDS = []
for i in range(8):
    TREE_FIELDS.append(
        ("ref_skill%d" % i, 8 + i*4, "改变技能%d" % i, 'int',
         "学会后改变技能%d — 指向目标技能的记录索引" % i))
    TREE_FIELDS.append(
        ("ref_type%d" % i, 10 + i*4, "改变类型%d" % i, 'int',
         "改变类型%d: 20=前组尾链 10=升级链 6=主技能 5=进阶前 3=下级 2=链接 1=特殊" % i))

EFFECT_FIELDS = [
    ("timing",      40, "时序值Delay",   'int',     "技能行动时序值 (Maker.exe: 改变时序, sub_438AFC: word_7861F2)"),
    ("hp_pct",      42, "生命加成%",     'int',     "HP%加成 (sub_422BBC: a2[8]+=v6[21]*a2[7]/100)"),
    ("heal_move",   44, "移动每格恢复生命%", 'int',  "移动每格恢复生命%: 自癒1=2 自癒2=3 自癒3=4 (sub_422BBC: v6[22])"),
    ("mp_pct",      46, "内力加成%",     'int',     "MP%加成 (sub_422BBC: a2[10]+=v6[23]*a2[9]/100)"),
    ("mp_move",     48, "移动每格恢复内力%", 'int',  "移动每格恢复内力%: 回气1=2 回气2=3 回气3=4 (sub_422BBC: v6[24])"),
    ("atk_pct",     50, "攻击加成%",     'int',     "攻击%加成 (sub_422BBC: a2[12]+=v6[25]*a2[11]/100)"),
    ("def_pct",     52, "防御加成%",     'int',     "防御%加成 (sub_422BBC: a2[14]+=v6[26]*a2[13]/100)"),
    ("hit_pct",     54, "命中加成%",     'int',     "命中%加成 (sub_422BBC: a2[16]+=v6[27]*a2[15]/100)"),
    ("eva_pct",     56, "闪避加成%",     'int',     "闪避%加成 (sub_422BBC: a2[18]+=v6[28]*a2[17]/100)"),
    ("spd_pct",     58, "速度加成%",     'int',     "速度%加成 (sub_422BBC: a2[20]+=v6[29]*a2[19]/100)"),
    ("move_up",     60, "增加移动",      'int',     "移动力增加值: 移动+1=2, 移动+2=3 (Maker.exe: 增加移动)"),
    ("atk_count",   62, "增攻击次数",    'int',     "增加攻击次数: 二連=2 三連=3 (Maker.exe: 增攻击次数)"),
    ("special_flags",64,"特殊标志",      'flags',   "type=3: a2[38]|=v6[32]; bit0=飘浮 bit1=飙行 bit2=搜宝 bit3=解陷"),
    ("mp_reduce",   66, "内力消耗减少%", 'int',     "施展指令技能内力减少% (Maker.exe: 内息百分比)"),
]

IMMUNE_FIELDS = [
    ("immunity1",   68, "状态免疫 1-16",  'mask',  "状态免疫位掩码 (状态 1-16)"),
    ("immunity2",   70, "状态免疫 17-32", 'mask',  "状态免疫位掩码 (状态 17-32)"),
    ("exp_bonus",   72, "战斗经验增加%", 'int',     "战斗经验值增加% (Maker.exe: 鬼才百分比)"),
    ("jp_bonus",   74, "战斗技能点增加%", 'int',     "战斗技能点数增加% (Maker.exe: 天才百分比)"),
    ("magic_def",   76, "所受法伤减少%", 'int',     "减少法术伤害% (Maker.exe: 抗魔百分比)"),
    ("cost_gold",   78, "消耗金钱",      'int',     "资源消耗1·金钱 (sub_438AFC: word_786218)"),
    ("cost_res2",   80, "耗费兽元",     'int',     "召唤技能兽元消耗 (Maker.exe: 耗费兽元, sub_438AFC: word_78621A)"),
]

ADVANCED_FIELDS = [
    ("cost_res3",   82, "耗费灵魂",     'int',     "幻灵技能灵魂消耗 (Maker.exe: 耗费灵魂, sub_438AFC: word_78621C)"),
    ("turn_shift",  84, "调整时序", 'int',     "敌人行动时序偏移: 正=后移N位, 负=前移N位 (Maker: 敌人损回合, sub_4458B0: word_78621E)"),
    ("mp_cost",     86, "耗费内力",    'int',     "技能消耗内力值 — 与TKT描述一致 (word_786220)"),
    ("trigger_prob",88, "触发概率",      'int',     "type=1→状态免疫等级; type=2→被动技能触发概率 (offset 88 int16)"),
    ("sub_count",   90, "子技能数量",    'int',     "技能组头子技能数 (-1=独立技能, ≥0=母技能有子技能)"),
    ("atk_type",    92, "攻击类型",      'atk_type',"攻击伤害类别, 战斗引擎 3 处分支: "
     "①sub_4389B0: 1=术法受抗性减半时序伤害; "
     "②sub_4458B0: -1=近战不受国士无双免疫(无条件物理路径), 0=单目标物理, ≥1=术法受法术反弹; "
     "③sub_447DAC: byte_9D6C78=LOBYTE(field[46])+1, 0=近战 1=物理 2=术法 11=召唤"),
]

ALL_FIELDS = (BASIC_FIELDS + TREE_FIELDS + EFFECT_FIELDS + IMMUNE_FIELDS +
              list(ADVANCED_FIELDS))

# ============================================================
# 类型相关字段分组 (用于 UI 提示)
# ============================================================

TYPE_HINT_FIELDS = {
    1: ["hp_pct","mp_pct","atk_pct","def_pct","hit_pct","eva_pct","spd_pct",
        "move_up","atk_count","heal_move","mp_move","mp_reduce","exp_bonus","jp_bonus","magic_def"],
    2: ["trigger_prob","mp_reduce","exp_bonus","jp_bonus","magic_def"],
    3: ["special_flags","heal_move","mp_move","atk_count","move_up"],
    0: ["sub_count"],
}

TYPE_HINT_LABELS = {
    1: "主动技能: 百分比属性加成 → 角色战斗属性",
    2: "被动技能: 触发概率 → 角色反应系统",
    3: "移动技能: 特殊标志 + 移动能力 → 角色地图能力",
    0: "指令技能: 技能组根节点, 含子技能列表",
}

# ============================================================
# 数据加载/保存
# ============================================================

def skill_name(rec, tkt):
    sid = rec.get('skill_text_id', 0)
    if sid and sid in tkt:
        return tkt[sid].split('\n')[0].strip()
    if sid and -sid in tkt:
        return tkt[-sid].split('\n')[0].strip()
    return f"Skill#{sid}" if sid else f"(空-#{rec['index']})"

def load_skills(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); recs = []
    for i in range(SKILL_CNT):
        off = i * SKILL_REC
        if off + SKILL_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h' * 47, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_skills(fp, recs):
    buf = bytearray(SKILL_CNT * SKILL_REC)
    for rec in recs[:SKILL_CNT]:
        i = rec['index']; off = i * SKILL_REC
        for k, fo, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# GUI
# ============================================================

class SkillEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKSkill.dat 可视化编辑器")
        self.root.geometry("1260x820"); self.root.minsize(1000, 650)
        self.skill_path = self.tkt_path = None
        self.records = []; self.tkt = {}; self.tkt_full = {}
        self.filtered_indices = []; self._dirty = False
        self.filter_type = tk.StringVar(value="全部类型")
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
        em.add_command(label="新建技能", command=self._new_skill, accelerator="Ctrl+N")
        em.add_command(label="复制当前记录", command=self._copy_record)
        em.add_command(label="清空当前记录", command=self._clear_current)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_skill())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=20); e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(tb, text="类型:").pack(side=tk.LEFT)
        ttk.Combobox(tb, textvariable=self.filter_type,
                     values=["全部类型"] + SKILL_TYPE_VALUES,
                     state='readonly', width=12).pack(side=tk.LEFT, padx=2)
        self.filter_type.trace_add('write', lambda *a: self._apply_filter())
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned); paned.add(lf, weight=2)
        cols = ('index', 'skill_text_id', 'type', 'name', 'jp_cost', 'mp_cost')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [('index', '技能ID', 52), ('skill_text_id', '文本ID', 52), ('type', '类型', 72),
              ('name', '技能名称', 160), ('jp_cost', '技能点数', 38), ('mp_cost', '耗费内力', 38)]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('cmd', foreground='#3366cc')
        self.tree.tag_configure('passive', foreground='#228B22')

        # Right: Edit panel
        rf = ttk.Frame(paned); paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 4), padx=4)

        # Scrollable edit area
        middle = ttk.Frame(rf); middle.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(middle); left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(middle, orient=tk.VERTICAL); sb.pack(side=tk.RIGHT, fill=tk.Y)

        bf = ttk.Frame(left_col); bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit, width=12).pack(side=tk.LEFT, padx=2)

        canvas = tk.Canvas(left_col, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self._canvas_win = canvas.create_window((0, 0), window=self.edit_inner, anchor='nw')
        canvas.bind('<Configure>', lambda e: self.edit_inner.columnconfigure(0, minsize=e.width))
        canvas.configure(yscrollcommand=sb.set)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}; self._edit_extras = {}

        # Preview panel
        pv_lf = ttk.LabelFrame(self.edit_inner, text="技能预览", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        for c in range(4): pv_lf.columnconfigure(c, weight=1)
        LBL_CLR = '#666'
        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground=LBL_CLR).grid(
            row=0, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=600, justify='left')
        self.preview_name.grid(row=0, column=1, columnspan=3, sticky='ew', pady=1)
        self.preview_desc = tk.Text(pv_lf, height=8, width=70, font=FONT,
                                     foreground='#228B22', wrap='word',
                                     relief='flat', borderwidth=0,
                                     state='disabled', bg=self.root.cget('bg'))
        ttk.Label(pv_lf, text="描述:", font=FONT_S, foreground=LBL_CLR).grid(
            row=1, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_desc.grid(row=1, column=1, columnspan=3, sticky='ew', pady=1)
        # type hint row
        self.preview_type = ttk.Label(pv_lf, text="", font=FONT_S, foreground='#888')
        self.preview_type.grid(row=2, column=0, columnspan=4, sticky='w', padx=4, pady=1)
        # sub-skill count hint
        self.preview_sub = ttk.Label(pv_lf, text="", font=FONT_S, foreground='#CC6633')
        self.preview_sub.grid(row=3, column=0, columnspan=4, sticky='w', padx=4, pady=1)

        # Field groups
        self._build_field_group("基础属性", BASIC_FIELDS, 1, 5)
        self._build_field_group("效果加成 (主动技能核心)", EFFECT_FIELDS, 2, 5)
        self._build_field_group("状态免疫", IMMUNE_FIELDS, 3, 4)
        self._build_field_group("高级属性", ADVANCED_FIELDS, 4, 4)
        # Skill tree reference table
        self._build_field_group("技能树引用表 (8组: 改变技能 / 改变类型)", TREE_FIELDS, 5, 6)

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray")
        self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field_group(self, title, fields, row, cols):
        lf = ttk.LabelFrame(self.edit_inner, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        # Type hint label for this group
        hint_lbl = ttk.Label(lf, text="", font=FONT_S, foreground='#888')
        hint_lbl.pack(anchor=tk.W, padx=2, pady=(0, 2))
        setattr(self, f'_hint_{row}', hint_lbl)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        for fi, (fn, fo, fl, ft, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, fn, fo, fl, ft, W_INPUT, cmt)

    def _build_field(self, parent, row, col, fn, fo, fl, ft, fw, cmt):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=fl, font=FONT_S); lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        if ft == 'tkt':
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text="…", width=2,
                       command=lambda f=fn: self._pick_tkt(f)).pack(side=tk.LEFT, padx=1)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#3366cc',
                                               font=FONT_S, wraplength=150)
            self._edit_extras[fn].pack(anchor=tk.W)
        elif ft == 'type':
            cb = ttk.Combobox(frm, state='readonly', values=SKILL_TYPE_VALUES,
                              width=fw + 2, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
            cb.bind('<<ComboboxSelected>>', lambda e: self._on_type_change())
        elif ft == 'mask':
            is_immune = fn.startswith('immunity')
            btn_text = "选择免疫状态…" if is_immune else "选择状态…"
            color = '#3366cc' if is_immune else '#CC3333'
            ttk.Button(frm, text=btn_text, width=fw + 3,
                       command=lambda f=fn: self._pick_status(f)).pack(fill=tk.X)
            extras = ttk.Frame(frm)
            extras.pack(anchor=tk.W, fill=tk.X)
            self._edit_extras[fn] = (extras, ttk.Label(extras, text="(无)", foreground=color,
                                                        font=FONT_S, wraplength=180))
            self._edit_extras[fn][1].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'flags':
            ttk.Button(frm, text="选择标志…", width=fw + 3,
                       command=lambda f=fn: self._pick_flags(f)).pack(fill=tk.X)
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#666', font=FONT_S, wraplength=150)
            self._edit_extras[fn].pack(anchor=tk.W)
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'atk_type':
            cb = ttk.Combobox(frm, state='readonly',
                              values=ATK_TYPE_VALUES,
                              width=fw + 6, font=FONT)
            cb.pack(fill=tk.X); self._edit_extras[fn] = cb
            self._edit_vars[fn] = tk.StringVar()
        elif ft == 'byte':
            ev = tk.StringVar(); self._edit_vars[fn] = ev
            ttk.Entry(frm, textvariable=ev, width=4, font=FONT).pack(fill=tk.X)
        else:
            ev = tk.StringVar(); self._edit_vars[fn] = ev
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
        sk = os.path.join(d, "TKSkill.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(sk):
            messagebox.showwarning("文件缺失", "未找到 TKSkill.dat"); return
        self.skill_path = sk
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.skill_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        try:
            self.records = load_skills(self.skill_path); self._dirty = False
            nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
            self.status_var.set(
                f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
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

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p):
            if not p: lb.config(text="(未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=p, foreground=g)
        _f(self.lbl_skill, self.skill_path)
        _f(self.lbl_tkt, self.tkt_path)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        ftype = self.filter_type.get()
        for rec in self.records:
            if rec['skill_text_id'] == 0: continue  # skip empty slots
            if ftype and not ftype.startswith("全部"):
                if rec['type'] != int(ftype.split('-')[0]): continue
            if q:
                nm = skill_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['skill_text_id']} {nm} {SKILL_TYPES.get(rec['type'], '')}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
        msg = f"显示 {len(self.filtered_indices)}/{nonempty} | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set(""); self.filter_type.set("全部类型"); self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            stype = SKILL_TYPES.get(r['type'], f"#{r['type']}")
            tags = []
            if r['type'] == 0: tags = ['cmd']
            elif r['type'] == 2: tags = ['passive']
            self.tree.insert('', 'end',
                             values=(r['index'], r['skill_text_id'], stype,
                                     skill_name(r, self.tkt), r['jp_cost'], r['mp_cost']),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'name':
            self.filtered_indices.sort(
                key=lambda i: skill_name(self.records[i], self.tkt).lower(), reverse=rev)
        else:
            km = {'skill_text_id': 'skill_text_id', 'type': 'type', 'jp_cost': 'jp_cost', 'mp_cost': 'mp_cost'}
            self.filtered_indices.sort(
                key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ----------- 编辑 -----------

    def _new_skill(self):
        """查找第一个空槽(skill_text_id=0)，设置默认模板"""
        if not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                rec['skill_text_id'] = rec['index'] + 1
                rec['type'] = 1; rec['jp_cost'] = 1
                rec['sub_count'] = -1; rec['atk_type'] = -1
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child); self.tree.see(child); break
                self._populate_edit(rec)
                self.status_var.set(f"已创建新技能 → 槽位 #{rec['index']}"); return
        messagebox.showwarning("槽位已满", f"所有 {SKILL_CNT} 个槽位均已占用")

    def _copy_record(self):
        """复制当前选中记录到下一个空槽"""
        if not hasattr(self, '_editing_idx'): return
        src = self.records[self._editing_idx]
        if src['skill_text_id'] == 0:
            messagebox.showinfo("提示", "当前记录为空, 无需复制"); return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child); self.tree.see(child); break
                self._populate_edit(rec)
                self.status_var.set(f"已复制 #{src['index']} → #{rec['index']}"); return
        messagebox.showwarning("槽位已满", f"所有 {SKILL_CNT} 个槽位均已占用")

    def _clear_current(self):
        """清空当前记录的所有字段"""
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        if rec['skill_text_id'] == 0:
            messagebox.showinfo("提示", "当前记录已经为空"); return
        if not messagebox.askyesno("确认清空", f"确定清空记录 #{rec['index']}?"):
            return
        for k, fo, _, _, _ in ALL_FIELDS:
            rec[k] = 0
        rec['sub_count'] = -1
        self._dirty = True; self._apply_filter()
        self._populate_edit(rec)
        self.status_var.set(f"已清空记录 #{rec['index']}")

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        stype = SKILL_TYPES.get(rec['type'], f"#{rec['type']}")
        self.lbl_rec_idx.config(text=(
            f"技能 #{rec['index']}    文本ID={rec['skill_text_id']}    "
            f"类型={stype}   名称={skill_name(rec, self.tkt)}"
        ))

        # Preview
        nid = rec.get('skill_text_id', 0)
        n_txt = self.tkt.get(nid, "") if nid > 0 else ""
        self.preview_name.config(text=n_txt.split('\n')[0].strip() if n_txt else "(无 / TKT 未提供)")
        did = nid + 400
        d_txt = self.tkt_full.get(did, "") if did > 0 else ""
        self.preview_desc.configure(state='normal')
        self.preview_desc.delete('1.0', 'end')
        self.preview_desc.insert('1.0', d_txt if d_txt else "(无描述 / TKT 未提供)")
        self.preview_desc.configure(state='disabled')
        # type hint
        hint = TYPE_HINT_LABELS.get(rec['type'], "")
        self.preview_type.config(text=f"类型: {stype} | 技能点数={rec['jp_cost']} | 耗费内力={rec['mp_cost']} | Pair0类型={rec['ref_type0']} | {hint}" if hint else
                                  f"类型: {stype} | 技能点数={rec['jp_cost']} | 耗费内力={rec['mp_cost']} | Pair0类型={rec['ref_type0']}")
        # sub count
        sc = rec.get('sub_count', -1)
        if sc >= 0:
            self.preview_sub.config(
                text=f"子技能: {sc} 个 (技能ID {rec['index']+1} – {rec['index']+sc})")
        else:
            self.preview_sub.config(text="")

        # Update type hint labels
        self._update_type_hints(rec['type'])

        for fn, fo, fl, ft, _ in ALL_FIELDS:
            val = rec.get(fn, 0); sv = str(val)
            self._edit_vars.get(fn, tk.StringVar()).set(sv)
            if ft == 'type':
                cb = self._edit_extras[fn]
                for i, t in enumerate(cb['values']):
                    if t.startswith(f"{val}-"): cb.current(i); break
            elif ft == 'tkt':
                # update resolved name
                nid = int(val) if val else 0
                if nid > 0:
                    txt = self.tkt.get(nid, "")
                    self._edit_extras[fn].config(text=txt.split('\n')[0][:25] if txt else "")
                else:
                    self._edit_extras[fn].config(text="")
            elif ft == 'mask':
                self._update_mask_label(fn, int(val) if val else 0)
            elif ft == 'flags':
                self._update_flags_label(fn, int(val) if val else 0)
            elif ft == 'atk_type':
                cb = self._edit_extras[fn]
                for i, t in enumerate(cb['values']):
                    if t.startswith(f"{val}-"): cb.current(i); break
    def _update_type_hints(self, skill_type):
        """Highlight groups relevant to this skill type"""
        # Row 2 = EFFECT_FIELDS, Row 3 = IMMUNE_FIELDS, Row 4 = ADVANCED_FIELDS
        # _hint_2 = effects, _hint_3 = immune, _hint_4 = advanced
        hints = {
            1: {
                2: "▼ 主动技能核心加成 (百分比属性 → 角色战斗值)",
                3: "▼ 状态免疫 (可选, 格挡/连击/精算)",
                4: "▼ 高级属性 (消耗资源/调整时序/攻击类型)",
            },
            2: {
                2: "效果加成 (被动技能多数不适用)",
                3: "▼ 状态免疫 + 格挡/连击 (被动技能核心)",
                4: "▼ 高级属性 (触发概率 为核心)",
            },
            3: {
                2: "▼ 特殊标志 + 自愈/回气/移动 (移动技能核心)",
                3: "状态免疫 (移动技能不太适用)",
                4: "▼ 高级属性 (消耗/调整时序)",
            },
            0: {
                2: "效果加成 (指令技能不太适用)",
                3: "状态免疫 (指令技能不太适用)",
                4: "▼ 子技能数量 (指令技能核心: 技能组头)",
            },
        }
        for row in [2, 3, 4]:
            lbl = getattr(self, f'_hint_{row}', None)
            if lbl:
                txt = hints.get(skill_type, {}).get(row, "")
                if skill_type in (1, 2, 3, 0) and txt:
                    lbl.config(text=txt, foreground='#228B22')
                else:
                    lbl.config(text="", foreground='#888')

    def _update_mask_label(self, fn, mask):
        base = 0 if fn == 'immunity1' else 16
        extras_frame, txt_lbl = self._edit_extras[fn]
        for w in extras_frame.winfo_children():
            if w != txt_lbl: w.destroy()
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append((base + i, STATUS_NAMES[base + i]))
        if sel:
            txt_lbl.config(text="")
            txt_lbl.pack_forget()
            COLS = 4
            for si, (idx, nm) in enumerate(sel):
                row, col = divmod(si, COLS)
                ttk.Label(extras_frame, text=nm, foreground=txt_lbl.cget('foreground'),
                         font=FONT_S).grid(row=row, column=col, sticky='w', padx=(0, 8), pady=1)
        else:
            txt_lbl.config(text="(无一免疫)")
            txt_lbl.pack(anchor=tk.W)

    def _update_flags_label(self, fn, val):
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in SPECIAL_FLAG_BITS if mask & (1 << bit)]
        self._edit_extras[fn].config(text=", ".join(sel) if sel else "(无)")

    def _on_type_change(self):
        """When type exp_bonusbox changes, update type hint labels"""
        try:
            new_type = int(self._edit_extras['type'].get().split('-')[0])
            self._update_type_hints(new_type)
        except: pass

    # ----------- 弹窗 -----------

    def _center_dialog(self, dlg, w, h):
        dlg.withdraw(); dlg.geometry(f"{w}x{h}"); dlg.update_idletasks()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        x = rx + (rw - w) // 2; y = ry + (rh - h) // 2
        dlg.geometry(f"+{x}+{y}"); dlg.deiconify()

    def _pick_tkt(self, fn):
        if not self.tkt: return
        dlg = tk.Toplevel(self.root); dlg.title("选择 TKT 文本")
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 520, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)
        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('id', 'text'), show='headings', selectmode='browse', height=22)
        tree.heading('id', text='ID'); tree.heading('text', text='文本')
        tree.column('id', width=60, anchor='center'); tree.column('text', width=420, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        _tkt_items = sorted(self.tkt.items(), key=lambda x: x[0])
        def _refresh(q=""):
            tree.delete(*tree.get_children()); ql = q.strip().lower()
            for eid, txt in _tkt_items:
                if ql and ql not in txt.lower(): continue
                iid = tree.insert('', 'end', values=(eid, txt[:80]))
                if eid == cur_val: tree.selection_set(iid); tree.see(iid)
        _refresh(); qv.trace_add('write', lambda *a: _refresh(qv.get()))
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                try:
                    tid = int(v[0])
                    txt = self.tkt.get(tid, "")
                    if fn == 'skill_text_id':
                        self.preview_name.config(text=txt.split('\n')[0].strip() if txt else "(无)")
                except: pass
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_status(self, fn):
        title = "选择免疫状态 (位掩码)"
        dlg = tk.Toplevel(self.root); dlg.title(title)
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 360, 520)
        base = 0 if fn == 'immunity1' else 16
        cur_mask = int(self._edit_vars.get(fn, tk.StringVar()).get() or 0) & 0xFFFF
        vars_ = []
        wrap = ttk.Frame(dlg, padding=8); wrap.pack(fill=tk.BOTH, expand=True)
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES): break
            v = tk.BooleanVar(value=bool(cur_mask & (1 << i)))
            ttk.Checkbutton(wrap, text=f"{idx}. {STATUS_NAMES[idx]}",
                            variable=v).pack(anchor=tk.W, pady=2)
            vars_.append(v)
        bf = ttk.Frame(dlg); bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            m = 0
            for i, v in enumerate(vars_):
                if v.get(): m |= (1 << i)
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            try: self._update_mask_label(fn, m & 0xFFFF)
            except: pass
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_flags(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择特殊标志 (位掩码)")
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 360, 220)
        cur_val = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        vars_ = []
        wrap = ttk.Frame(dlg, padding=8); wrap.pack(fill=tk.BOTH, expand=True)
        for bit, name, desc in SPECIAL_FLAG_BITS:
            row = ttk.Frame(wrap); row.pack(anchor=tk.W, fill=tk.X, pady=2)
            v = tk.BooleanVar(value=bool(cur_val & (1 << bit)))
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
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for _, v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 编辑应用 -----------

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, _ in ALL_FIELDS:
            try:
                if ft == 'type':
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
                elif ft == 'atk_type':
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
                else:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    rec[fn] = v
            except ValueError:
                rec[fn] = 0
        # 验证并警告 (逆向依据: sub_422BBC/sub_447DAC)
        warnings = []
        if rec['type'] not in (0, 1, 2, 3):
            warnings.append(f"技能类型 {rec['type']} 超出有效范围 0-3 (sub_422BBC)")
        sc = rec.get('sub_count', -1)
        if sc < -1 or sc > 349:
            warnings.append(f"子技能数量 {sc} 超出有效范围 -1~349")
        at = rec.get('atk_type', -1)
        if at < -1 or at > 10:
            warnings.append(f"攻击类型 {at} 超出有效范围 -1~10 (sub_447DAC/sub_4458B0)")
        if rec.get('mp_cost', 0) < 0:
            warnings.append("耗费内力不应为负值")
        if rec.get('jp_cost', 0) < 0:
            warnings.append("技能点数不应为负值")
        if warnings:
            messagebox.showwarning("数据验证警告",
                "以下字段值可能存在问题:\n\n" + "\n".join(f"• {w}" for w in warnings) +
                "\n\n修改已应用 (内存), 请确认后保存。")
        self._dirty = True; self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child); self.tree.see(child); break
        self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.skill_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.skill_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.skill_path, 'rb') as s:
                with open(self.skill_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.set("正在保存…"); self.root.update()
            save_skills(self.skill_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.skill_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.skill_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        csv_fields = ALL_FIELDS
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['索引', '名称', '类型'] + [fl for _, _, fl, _, _ in csv_fields]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                if rec['skill_text_id'] == 0: continue
                row = [str(rec['index']), skill_name(rec, self.tkt), SKILL_TYPES.get(rec['type'], str(rec['type']))]
                row += [str(rec[fn]) for fn, _, _, _, _ in csv_fields]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        groups = [
            ("基础标识区 (offset 0–6)", BASIC_FIELDS),
            ("技能树引用区 (offset 8–38)", TREE_FIELDS),
            ("效果加成区 (offset 40–68)", EFFECT_FIELDS),
            ("状态免疫区 (offset 68–82)", IMMUNE_FIELDS),
            ("高级属性区 (offset 82–94)", ADVANCED_FIELDS),
        ]
        lines = ["TKSkill.dat 字段映射 (反编译依据):", ""]
        for title, fields in groups:
            lines.append(f"【{title}】")
            for fn, fo, fl, ft, cmt in fields:
                lines.append(f"  [{fo:02d}] {fl:<14s} {cmt}")
            lines.append("")
        lines.append("【核心反编译函数】")
        lines.append("  sub_422BBC  被动技能属性加成 (type=1/2/3 分支)")
        lines.append("  sub_438F28  技能列表/技能组层次结构")
        lines.append("  sub_447DAC  攻击类型判定 (field[46]+1)")
        lines.append("  sub_4458B0  调整时序 (field[42])")
        lines.append("  sub_438AFC  图标/资源消耗读取")
        lines.append(""); lines.append("【记录数】")
        lines.append("  350 条 × 94 字节 = 32,900 字节 (sub_45343C 固定)")

        dlg = tk.Toplevel(self.root); dlg.title("字段参考 v1.0 (逆向)")
        dlg.geometry("700x560"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKSkill.dat 可视化编辑器 v1.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "350 条记录 × 94 字节 (47×int16 + 1×byte)\n\n"
            "核心反编译函数:\n"
            "  sub_422BBC  被动技能属性加成\n"
            "  sub_438F28  技能组层次结构\n"
            "  sub_447DAC  攻击类型判定\n"
            "  sub_4458B0  调整时序\n"
            "  sub_438AFC  图标/消耗读取"
        )


def main():
    root = tk.Tk(); SkillEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
