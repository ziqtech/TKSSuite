#!/usr/bin/env python3
"""
TKItem.dat 可视化编辑器

逆向依据:
  - sub_45343C: DAT 加载 (LZSS, 64B/条, 600条, a3=38400)
  - sub_452B14: LZSS (4096窗口, 0x20, 起始4078)
  - sub_41E40C: 物品使用 (v15[7-10]=HP/MP, v15[11-18]=属性, v15[28-29]=位掩码)
  - sub_42234C: 装备应用 (v9[21]=技能, v9[22]=状态, v9[26-27]=防御)
  - sub_424A2C: 物品显示 (word_77CBCE=name_id, word_77CC08=price)
  - sub_4246D8: word_77CBCC[32*idx]=tab_code 商店过滤

用法: python item_editor.py
"""

import struct, os, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# LZSS (sub_452B14, sub_45343C)
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
# TKT / TKSkill
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
# 常量
# ============================================================
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","误导",
    "混乱","禁制","定身","诅咒","封印","燃烧","冰冻","虚弱",
    "麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

ITEM_REC = 64; ITEM_CNT = 600
FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)

TAB_NAMES = {0:"消耗品", 1:"书籍", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
TAB_VALUES = [f"{k}-{v}" for k, v in sorted(TAB_NAMES.items())]

EQUIP_NAMES = {0:"消耗品/书籍", 1:"近战武器", 2:"远程武器", 3:"防具", 4:"饰品",
               8:"特殊8", 16:"特殊16", 32:"特殊32", 64:"特殊64", 128:"特殊128"}
EQUIP_VALUES = ["0-消耗品/书籍","1-近战武器","2-远程武器","3-防具","4-饰品",
                "8-特殊8","16-特殊16","32-特殊32","64-特殊64","128-特殊128"]

# 字段: (键名, 偏移, 标签, 类型, 宽度)
# type: int=数字, tab=商店下拉, tkt=TKT弹窗, skill=技能弹窗,
#       status=状态多选, ssingle=状态单选, equip=物品类型下拉
ITEM_FIELDS = [
    ("item_id",      0,  "物品ID",        'int',   6),
    ("tab_code",     2,  "商店类型",      'tab',   14),
    ("name_id",      4,  "名称代码→TKT",   'tkt',   6),
    ("desc_id",      6,  "说明代码→TKT",   'tkt',   6),
    ("icon",         8,  "图标",          'int',   5),
    ("equip_type",  10,  "物品类型",      'equip', 14),
    ("battle_anim", 12,  "战场动画",      'int',   5),
    ("hp_increase", 14,  "增加生命(HP)", 'int',   5),
    ("hp_heal",     16,  "恢复生命(HP)", 'int',   5),
    ("mp_increase", 18,  "增加内力(MP)", 'int',   5),
    ("mp_heal",     20,  "恢复内力(MP)", 'int',   5),
    ("str_bonus",   22,  "攻击(武力)",    'int',   5),
    ("int_bonus",   24,  "防御(智力)",    'int',   5),
    ("cmd_bonus",   26,  "命中(统御)",    'int',   5),
    ("agi_bonus",   28,  "闪避(敏捷)",    'int',   5),
    ("spd_bonus",   30,  "速度(SPD)",    'int',   5),
    ("luk_bonus",   32,  "幸运(LUK)",    'int',   5),
    ("spi_bonus",   34,  "悟性(精神)",    'int',   5),
    ("vit_bonus",   36,  "移动(体力)",    'int',   5),
    ("crit",        38,  "暴击/戒指判定", 'int',   5),
    ("special_flags",40, "战斗判定",      'int',   6),
    ("skill_id",    42,  "附加技能→TKSkill",'skill',6),
    ("abnormal_state",44,"导致状态(偏移量)",'int',5),
    ("learn_skill1", 46, "装备后学习技能1",'skill',6),
    ("learn_skill2", 48, "装备后学习技能2",'skill',6),
    ("exp_bonus",   50,  "经验值/JP",    'int',   5),
    ("ranged_def",  52,  "医术(远程防)", 'int',   5),
    ("magic_def",   54,  "法术防御",      'int',   5),
    ("cure_mask1",  56,  "解除状态1-16",  'status',14),
    ("cure_mask2",  58,  "解除状态17-32", 'status',14),
    ("extra_flags", 60,  "额外标志",      'int',   6),
    ("price",       62,  "价格",          'int',   6),
]

def is_empty_item(rec):
    """判断是否为占位空槽 (sub_40CE30: item_id==0或1均为无效物品)"""
    return rec['item_id'] == 0 or rec['item_id'] == 1

def item_display_name(rec, tkt):
    """物品的显示名称 (逆向自 sub_4067E8)"""
    if is_empty_item(rec):
        return f"(空槽 #{rec['index']})"
    if rec['name_id'] > 0 and rec['name_id'] in tkt:
        return tkt[rec['name_id']]
    return f"ID#{rec['item_id']}"

# ============================================================
# 数据
# ============================================================
def load_items(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); recs = []
    for i in range(ITEM_CNT):
        off = i * ITEM_REC
        if off + ITEM_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h'*32, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _, _) in enumerate(ITEM_FIELDS): rec[fn] = fields[fi]
        recs.append(rec)
    return recs

def save_items(fp, recs):
    buf = bytearray(ITEM_CNT * ITEM_REC)
    for rec in recs[:ITEM_CNT]:
        i = rec['index']; off = i * ITEM_REC
        for fi, (fn, fo, _, _, _) in enumerate(ITEM_FIELDS):
            struct.pack_into('<h', buf, off + fo, rec[fn])
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
        self.root.title("TKItem.dat 可视化编辑器")
        self.root.geometry("1220x720"); self.root.minsize(1000, 580)
        self.item_path = self.tkt_path = self.skill_path = None
        self.records = []; self.tkt = {}; self.skill_names = {}
        self.filtered_indices = []; self._dirty = False
        # 筛选状态
        self.filter_tab = tk.StringVar(value="全部商店")
        self.filter_equip = tk.StringVar(value="全部类型")
        self.filter_empty = tk.BooleanVar(value=True)   # 默认显示非空
        self._build_ui(); self._set_edit_enabled(False)

    def _build_ui(self):
        # 菜单
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator(); fm.add_command(label="保存 (Ctrl+S)", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator(); fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="使用说明", command=self._show_help)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())

        # 工具栏 — 搜索 + 三筛选
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        ttk.Entry(tb, textvariable=self.sv, width=16).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=4).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=4).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(tb, text="商店:").pack(side=tk.LEFT)
        ttk.Combobox(tb, textvariable=self.filter_tab, values=["全部商店"]+TAB_VALUES,
                     state='readonly', width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(tb, text="类型:").pack(side=tk.LEFT, padx=(6,0))
        ttk.Combobox(tb, textvariable=self.filter_equip, values=["全部类型"]+EQUIP_VALUES,
                     state='readonly', width=13).pack(side=tk.LEFT, padx=2)
        cb_empty = ttk.Checkbutton(tb, text="非空", variable=self.filter_empty,
                                     command=self._apply_filter)
        cb_empty.pack(side=tk.LEFT, padx=6)
        # 绑定筛选事件
        self.filter_tab.trace_add('write', lambda *a: self._apply_filter())
        self.filter_equip.trace_add('write', lambda *a: self._apply_filter())
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # 左右分栏
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧表格
        lf = ttk.Frame(paned); paned.add(lf, weight=3)
        cols = ('index','item_id','tab_code','name','equip_type','price')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [('index','索引',38),('item_id','ID',45),('tab_code','商店',50),
              ('name','物品名称',260),('equip_type','类型',46),('price','价格',46)]
        for cid,cn,cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧编辑区 — 5列布局
        rf = ttk.LabelFrame(paned, text="编辑区", padding=6); paned.add(rf, weight=2)
        self.edit_frame = rf
        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 10, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0,4))

        canvas = tk.Canvas(rf, highlightthickness=0)
        sb = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=canvas.yview)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}; self._edit_extras = {}
        COLS = 5
        for fi, (fn, fo, fl, ft, fw) in enumerate(ITEM_FIELDS):
            row, col = fi // COLS, fi % COLS
            frm = ttk.Frame(self.edit_inner); frm.grid(row=row, column=col, sticky='ew', padx=2, pady=1)
            ttk.Label(frm, text=fl, font=FONT_S).pack(anchor=tk.W)

            if ft == 'tab':
                cb = ttk.Combobox(frm, state='readonly', values=TAB_VALUES, width=13, font=FONT)
                cb.pack(fill=tk.X); self._edit_extras[fn] = cb; self._edit_vars[fn] = tk.StringVar()
            elif ft == 'equip':
                cb = ttk.Combobox(frm, state='readonly', values=EQUIP_VALUES, width=13, font=FONT)
                cb.pack(fill=tk.X); self._edit_extras[fn] = cb; self._edit_vars[fn] = tk.StringVar()
            elif ft == 'tkt':
                fr2 = ttk.Frame(frm); fr2.pack(fill=tk.X)
                ev = tk.StringVar(); self._edit_vars[fn] = ev
                ttk.Entry(fr2, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
                ttk.Button(fr2, text="…", width=2, command=lambda f=fn: self._pick_tkt(f)).pack(side=tk.LEFT, padx=1)
                self._edit_extras[fn] = ttk.Label(fr2, text="", foreground='#3366cc', font=FONT_S, wraplength=140)
                self._edit_extras[fn].pack(side=tk.LEFT, padx=3)
            elif ft == 'skill':
                fr2 = ttk.Frame(frm); fr2.pack(fill=tk.X)
                ev = tk.StringVar(); self._edit_vars[fn] = ev
                ttk.Entry(fr2, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
                ttk.Button(fr2, text="…", width=2, command=lambda f=fn: self._pick_skill(f)).pack(side=tk.LEFT, padx=1)
                self._edit_extras[fn] = ttk.Label(fr2, text="", foreground='#228B22', font=FONT_S)
                self._edit_extras[fn].pack(side=tk.LEFT, padx=3)
            elif ft == 'status':
                btn_text = f"选择状态…"
                lbl = ttk.Button(frm, text=btn_text, command=lambda f=fn: self._pick_status(f))
                lbl.pack(fill=tk.X)
                self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#3366cc', font=FONT_S, wraplength=140)
                self._edit_extras[fn].pack(anchor=tk.W)
                self._edit_vars[fn] = tk.StringVar()
            elif ft == 'ssingle':
                btn_text = f"选择…"
                lbl = ttk.Button(frm, text=btn_text, command=lambda f=fn: self._pick_status_single(f))
                lbl.pack(fill=tk.X)
                self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#CC3333', font=FONT_S)
                self._edit_extras[fn].pack(anchor=tk.W)
                self._edit_vars[fn] = tk.StringVar()
            else:
                ev = tk.StringVar(); self._edit_vars[fn] = ev
                ttk.Entry(frm, textvariable=ev, width=fw, font=FONT).pack(fill=tk.X)

        # 按钮
        bf = ttk.Frame(self.edit_inner)
        bf.grid(row=(len(ITEM_FIELDS)//COLS)+1, column=0, columnspan=COLS, sticky='ew', pady=(8,0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        ttk.Button(bf, text="复制记录", command=self._copy_record).pack(side=tk.LEFT, padx=2)

        # 底部路径
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0,2))
        self.lbl_item = ttk.Label(pf, text="", foreground="gray"); self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray"); self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray"); self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)

    def _bind_mousewheel(self, canvas):
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ---- 数据加载 ----
    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        it = os.path.join(d, "TKItem.dat"); tk_ = os.path.join(d, "TKT.dat"); sk = os.path.join(d, "TKSkill.dat")
        if not os.path.exists(it): messagebox.showwarning("文件缺失","未找到 TKItem.dat"); return
        self.item_path = it; self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.skill_path = sk if os.path.exists(sk) else None; self._reload()

    def _reload(self):
        if not self.item_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path: self.tkt = load_tkt(self.tkt_path)
        if self.skill_path: self.skill_names = load_tkskill_names(self.skill_path, self.tkt)
        try:
            self.records = load_items(self.item_path); self._dirty = False
            self.status_var.set(f"{len(self.records)}条 + {len(self.tkt)}TKT + {len(self.skill_names)}技能")
        except Exception as e: messagebox.showerror("加载失败",str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children(): self._set_ws(c, en)
    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)): w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, ttk.Combobox): w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)

    def _update_paths(self):
        g,r = "#228B22","#CC3333"
        def _f(lb,p):
            if not p: lb.config(text="(未加载)",foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}",foreground=r)
            else: lb.config(text=p,foreground=g)
        _f(self.lbl_item,self.item_path); _f(self.lbl_tkt,self.tkt_path); _f(self.lbl_skill,self.skill_path)

    # ---- 筛选 ----
    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        ftab = self.filter_tab.get(); fequip = self.filter_equip.get()
        for rec in self.records:
            # 空数据筛选
            empty = is_empty_item(rec)
            if self.filter_empty.get() and empty: continue
            # 商店类型筛选
            if ftab and not ftab.startswith("全部"):
                fid = int(ftab.split('-')[0])
                if rec['tab_code'] != fid: continue
            # 物品类型筛选
            if fequip and not fequip.startswith("全部"):
                fid = int(fequip.split('-')[0])
                if rec['equip_type'] != fid: continue
            # 文本搜索
            if q:
                nm = item_display_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['item_id']} {rec['tab_code']} {nm}".lower(): continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        self.status_var.set(f"显示 {len(self.filtered_indices)}/{len(self.records)}条  |  Ctrl+S 保存")

    def _clear_filter(self):
        self.sv.set(""); self.filter_tab.set("全部商店"); self.filter_equip.set("全部类型")
        self.filter_empty.set(True); self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        et_short = {0:"消耗",1:"近战",2:"远程",3:"防具",4:"饰品"}
        for idx in self.filtered_indices:
            r = self.records[idx]
            et = et_short.get(r['equip_type'], f"#{r['equip_type']}") if r['equip_type'] else "—"
            self.tree.insert('','end',values=(
                r['index'], r['item_id'], TAB_NAMES.get(r['tab_code'],'?'),
                item_display_name(r, self.tkt), et, r['price']))

    def _sort_by(self, col):
        rev = getattr(self,'_sort_reverse',False)
        km = {'item_id':'item_id','tab_code':'tab_code','price':'price','equip_type':'equip_type'}
        self.filtered_indices.sort(key=lambda i: self.records[i].get(km.get(col,'index'),0), reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ---- 编辑 ----
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0]); self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        self.lbl_rec_idx.config(text=f"记录 #{rec['index']}   ID={rec['item_id']}   商店={TAB_NAMES.get(rec['tab_code'],'?')}")
        for fi, (fn, fo, fl, ft, fw) in enumerate(ITEM_FIELDS):
            val = rec[fn]; sv = str(val)
            self._edit_vars[fn].set(sv)
            if ft == 'tab':
                cb = self._edit_extras[fn]
                for i, item_text in enumerate(cb['values']):
                    if item_text.startswith(f"{val}-"): cb.current(i); break
                else: cb.set(sv)
            elif ft == 'equip':
                cb = self._edit_extras[fn]
                for i, item_text in enumerate(cb['values']):
                    if item_text.startswith(f"{val}-"): cb.current(i); break
                else: cb.set(sv)
            elif ft == 'tkt':
                tid = int(val) if val else 0; txt = self.tkt.get(tid,"") if tid>0 else ""
                self._edit_extras[fn].config(text=txt[:30] if txt else "(无效)")
            elif ft == 'skill':
                sid = int(val) if val else -1
                self._edit_extras[fn].config(text=self.skill_names.get(sid,"(无)")[:22] if sid>=0 else "(无)")
            elif ft == 'status':
                mask = int(val) if val else 0; self._update_status_label(fn, mask)
            elif ft == 'ssingle':
                sidx = int(val) if val else -1
                if 0 <= sidx < len(STATUS_NAMES): self._edit_extras[fn].config(text=STATUS_NAMES[sidx])
                else: self._edit_extras[fn].config(text="(无)")

    def _update_status_label(self, fn, mask):
        base = 0 if fn == 'cure_mask1' else 16; selected = []
        for i in range(16):
            if mask & (1 << i) and base+i < len(STATUS_NAMES):
                selected.append(STATUS_NAMES[base+i])
        self._edit_extras[fn].config(text=", ".join(selected) if selected else "(无)")

    # ---- 弹窗 ----
    def _pick_status(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择解除状态"); dlg.geometry("420x400")
        dlg.transient(self.root); dlg.grab_set()
        base = 0 if fn == 'cure_mask1' else 16
        cur_mask = int(self._edit_vars[fn].get() or 0)
        vars_ = []
        canvas = tk.Canvas(dlg); sb2 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas); inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb2.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8); sb2.pack(side=tk.RIGHT, fill=tk.Y)
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES): break
            v = tk.BooleanVar(value=bool(cur_mask & (1 << i)))
            ttk.Checkbutton(inner, text=f"{idx+1}. {STATUS_NAMES[idx]}", variable=v).pack(anchor=tk.W, pady=1)
            vars_.append(v)
        bf = ttk.Frame(dlg); bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            m = 0
            for i, v in enumerate(vars_):
                if v.get(): m |= (1 << i)
            self._edit_vars[fn].set(str(m)); self._update_status_label(fn, m); dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_status_single(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择导致状态"); dlg.geometry("300x420")
        dlg.transient(self.root); dlg.grab_set()
        cur = int(self._edit_vars[fn].get() or -1)
        lb = tk.Listbox(dlg, font=FONT, selectmode=tk.SINGLE)
        for i, sn in enumerate(STATUS_NAMES): lb.insert(tk.END, f"{i}. {sn}")
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        if 0 <= cur < len(STATUS_NAMES): lb.selection_set(cur); lb.see(cur)
        bf = ttk.Frame(dlg); bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            sel = lb.curselection()
            if sel:
                self._edit_vars[fn].set(str(sel[0])); self._edit_extras[fn].config(text=STATUS_NAMES[sel[0]])
            else:
                self._edit_vars[fn].set("-1"); self._edit_extras[fn].config(text="(无)")
            dlg.destroy()
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="清除", command=lambda: [
            self._edit_vars[fn].set("-1"), self._edit_extras[fn].config(text="(无)"), dlg.destroy()
        ]).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_tkt(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择TKT文本"); dlg.geometry("480x450")
        dlg.transient(self.root); dlg.grab_set()
        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT); qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('id','text'), show='headings', selectmode='browse', height=18)
        tree.heading('id', text='ID'); tree.heading('text', text='文本')
        tree.column('id', width=55, anchor='center'); tree.column('text', width=380, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _refresh(q=""):
            tree.delete(*tree.get_children()); ql = q.strip().lower()
            for eid, txt in sorted(self.tkt.items(), key=lambda x: x[0]):
                if ql and ql not in txt.lower(): continue
                tree.insert('','end',values=(eid, txt[:70]))
        _refresh(); qv.trace_add('write', lambda *a: _refresh(qv.get()))
        tree.bind('<Double-1>', lambda e: _sel())
        bf2 = ttk.Frame(dlg, padding=5); bf2.pack(fill=tk.X)
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0])); self._edit_extras[fn].config(text=str(v[1])[:30])
                dlg.destroy()
        ttk.Button(bf2, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf2, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_skill(self, fn):
        dlg = tk.Toplevel(self.root); dlg.title("选择技能"); dlg.geometry("430x450")
        dlg.transient(self.root); dlg.grab_set()
        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text="搜索:").pack(side=tk.LEFT); qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)
        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('idx','name'), show='headings', selectmode='browse', height=18)
        tree.heading('idx', text='索引'); tree.heading('name', text='技能名称')
        tree.column('idx', width=45, anchor='center'); tree.column('name', width=350, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _refresh(q=""):
            tree.delete(*tree.get_children()); ql = q.strip().lower()
            for idx, name in sorted(self.skill_names.items(), key=lambda x: x[0]):
                if ql and ql not in name.lower(): continue
                tree.insert('','end',values=(idx, name[:50]))
        _refresh(); qv.trace_add('write', lambda *a: _refresh(qv.get()))
        tree.bind('<Double-1>', lambda e: _sel())
        bf2 = ttk.Frame(dlg, padding=5); bf2.pack(fill=tk.X)
        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0])); self._edit_extras[fn].config(text=str(v[1])[:22])
                dlg.destroy()
        ttk.Button(bf2, text="确定", command=_sel).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf2, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        for fi, (fn, fo, fl, ft, fw) in enumerate(ITEM_FIELDS):
            try:
                if ft == 'tab':
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-')[0]) if '-' in sv else int(sv)
                elif ft == 'equip':
                    sv = self._edit_extras[fn].get()
                    rec[fn] = int(sv.split('-')[0]) if '-' in sv else int(sv)
                else:
                    rec[fn] = int(self._edit_vars[fn].get())
            except ValueError: rec[fn] = 0
        self._dirty = True; self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child); self.tree.see(child); break
        self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'): return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_empty_item(rec):
                for fi, (fn,_,_,_,_) in enumerate(ITEM_FIELDS): rec[fn] = src[fn]
                rec['index']=i; rec['item_id']=0; self._dirty=True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0])==i:
                        self.tree.selection_set(child); self.tree.see(child); break
                self.status_var.set(f"已复制到空槽 #{i}"); return
        messagebox.showwarning("已满", "600条记录无空槽")

    # ---- 保存/导出 ----
    def _save(self):
        if not self.item_path or not self.records: messagebox.showinfo("提示","请先加载数据"); return
        if not messagebox.askyesno("确认保存",f"保存 {len(self.records)} 条到:\n{self.item_path}\n\n原文件将被覆盖。"): return
        try:
            with open(self.item_path,'rb') as s:
                with open(self.item_path+".bak",'wb') as d: d.write(s.read())
        except: pass
        try:
            save_items(self.item_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.item_path}"); messagebox.showinfo("保存成功",f"已保存\n备份: {self.item_path}.bak")
        except Exception as e: messagebox.showerror("保存失败",str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not p: return
        with open(p,'w',encoding='utf-8-sig') as f:
            f.write(','.join(['索引']+[fl for _,_,fl,_,_ in ITEM_FIELDS])+'\n')
            for rec in self.records:
                f.write(','.join([str(rec['index'])]+[str(rec[fn]) for fn,_,_,_,_ in ITEM_FIELDS])+'\n')
        self.status_var.set(f"已导出: {p}")

    def _show_help(self):
        messagebox.showinfo("使用说明",
            "TKItem.dat 可视化编辑器\n\n"
            "1. 文件→加载TKS目录: 自动关联TKItem/TKT/TKSkill\n"
            "2. 工具栏筛选: 商店类型/物品类型/仅非空(默认勾选)\n"
            "3. 名称/说明代码: 输入框旁…按钮弹窗搜索TKT\n"
            "4. 附加技能/学习技能: …按钮弹窗搜索技能名\n"
            "5. 解除状态: 点按钮多选checkbox\n"
            "6. 导致状态: 点按钮单选Listbox\n"
            "7. HP≤1000=固定值, >1000=百分比")

    def _show_about(self):
        messagebox.showinfo("关于","TKItem.dat 可视化编辑器 v1.0\n\n基于《三国群侠传》逆向工程\n600条记录 32字段 完整编辑")

def main():
    root = tk.Tk(); ItemEditor(root); root.mainloop()

if __name__ == '__main__': main()
