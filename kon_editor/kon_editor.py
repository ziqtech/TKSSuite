#!/usr/bin/env python3
"""
TKKon.dat 可视化编辑器 v2.0
=============================================================
逆向依据 (2026-05 重新分析修正):
  - sub_45343C:     DAT 文件统一加载 (LZSS 解压, 40字节/条, 650条)
  - sub_452B14:     LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_4173F8:     TKKon 加载入口 → &unk_9D0698, 26000
  - sub_4434BC:     运行时条件处理 — 按 word_9D069E[20*i] 索引,
                    stride=40字节(20×int16), 确认 [3]=条件ID
  - Maker.exe sub_4027FF: 校验解压后大小 26000 = 40 × 650

关键发现 (修正旧版 13×int16/1000条 错误):
  - 26000 = 40 × 650 (非 26 × 1000)
  - 每条 20 个 int16 (40 字节), 共 650 条
  - field[3] 为顺序索引 0..649, 是游戏内条件唯一ID
  - field[15]-[18] 在所有650条中恒为0 (未使用)

字段布局 (20 × int16, 40字节/条):
  [0]  cond_type   — 条件类型/场景文本 → TKT (256=匈奴民帳, 512=草原, 768/1024/1280/1536...)
  [1]  target1     — 目标/次级场景 → TKT
  [2]  mode        — 模式/标志 (1, 2, 256, 257, 258...)
  [3]  cond_id     — ★条件唯一ID (0..649, 顺序递增, 反编译 word_9D069E[20*i])
  [4]  value       — 参数值/终止标记 (-1=终止, 20/30/40/60/80/120等数值)
  [5]  param5      — 参数5 (21条使用)
  [6]  param6      — 参数6 (33条使用)
  [7]  param7      — 参数7 (1条使用)
  [8]  dialog1     — 对话文本ID1 → TKT (30条使用)
  [9]  dialog2     — 对话文本ID2 → TKT (16条使用)
  [10] param10     — 参数10 (84条使用, 位标志/数值)
  [11] param11     — 参数11 (107条使用, 位标志/数值)
  [12] param12     — 参数12 (26条使用, 大数值)
  [13] param13     — 参数13 (62条使用, 大数值)
  [14] param14     — 参数14 (7条使用)
  [15] unused15    — 未使用 (始终为0)
  [16] unused16    — 未使用 (始终为0)
  [17] unused17    — 未使用 (始终为0)
  [18] unused18    — 未使用 (始终为0)
  [19] end_flag    — 结束标记 (0=无 1= 3= 4=; 219条非零)

用法:
  python kon_editor.py
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

# ============================================================
# 常量 — 修正为 40 字节/条 × 650 条
# ============================================================

KON_REC = 40       # 20 × int16
KON_CNT = 650      # 26000 / 40
KON_FIELD_COUNT = 20
KON_DECOMPRESSED = 26000

FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ============================================================
# 字段定义 (key, byte_offset, ui_label, comment)
# ============================================================

KON_FIELDS = [
    ("cond_type",   0,  "条件类型",   "条件类型/场景文本 → TKT (256=匈奴民帳, 512=草原之黃巾賊, 768/1024/1280/1536…)"),
    ("target1",     2,  "目标1",      "目标/次级场景 → TKT (256=匈奴民帳, 512=江岸…)"),
    ("mode",        4,  "模式标志",   "模式/标志 (1=啊！, 2=虎牢關之役, 256/257/258…)"),
    ("cond_id",     6,  "★条件ID",   "条件唯一ID (0..649, 顺序递增) — 反编译 word_9D069E[20*i] 索引源"),
    ("value",       8,  "参数值",     "参数值/终止标记 (-1=终止, 20/30/40/60/80/120 等数值)"),
    ("param5",      10, "参数5",      "参数5 (21条使用)"),
    ("param6",      12, "参数6",      "参数6 (33条使用)"),
    ("param7",      14, "参数7",      "参数7 (1条使用)"),
    ("dialog1",     16, "对话文本1",  "对话文本ID1 → TKT (30条使用)"),
    ("dialog2",     18, "对话文本2",  "对话文本ID2 → TKT (16条使用)"),
    ("param10",     20, "参数10",     "参数10 (84条使用, 位标志/数值)"),
    ("param11",     22, "参数11",     "参数11 (107条使用, 位标志/数值)"),
    ("param12",     24, "参数12",     "参数12 (26条使用, 大数值; 32767=任意)"),
    ("param13",     26, "参数13",     "参数13 (62条使用, 大数值; 32767=任意)"),
    ("param14",     28, "参数14",     "参数14 (7条使用)"),
    ("unused15",    30, "未使用15",   "● 始终为0 (650条中0条非零)"),
    ("unused16",    32, "未使用16",   "● 始终为0 (650条中0条非零)"),
    ("unused17",    34, "未使用17",   "● 始终为0 (650条中0条非零)"),
    ("unused18",    36, "未使用18",   "● 始终为0 (650条中0条非零)"),
    ("end_flag",    38, "结束标记",   "结束/类型标记 (0/1/3/4; 219条非零)"),
]

ACTIVE_FIELDS = [f for f in KON_FIELDS if not f[0].startswith('unused')]

# ============================================================
# 数据加载/保存
# ============================================================

def resolve_kon_val(val, tkt):
    """解析 int16 值 → TKT 文本或特殊标记"""
    if val == 0: return ""
    if val in (-1, 65535): return "(终止)"
    if val == 32767: return "(最大值/任意)"
    if val > 0 and val in tkt:
        txt = tkt[val].split('\n')[0].strip()
        return txt[:35] if txt else ""
    if val < 0 and -val in tkt:
        txt = tkt[-val].split('\n')[0].strip()
        return txt[:35] if txt else ""
    return ""

def kon_record_name(rec, tkt):
    """生成条件记录的可读名称"""
    ct = rec.get('cond_type', 0)
    if ct != 0:
        ct_txt = resolve_kon_val(ct, tkt)
        if ct_txt: return ct_txt[:25]
    for fld in ['target1', 'dialog1', 'dialog2']:
        v = rec.get(fld, 0)
        if v != 0:
            t = resolve_kon_val(v, tkt)
            if t: return t[:25]
    return f"条件#{rec.get('cond_id', rec['index'])}"

def load_kon(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    if len(dec) != KON_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 26000 (Maker.exe sub_4027FF)")
    recs = []
    for i in range(KON_CNT):
        off = i * KON_REC
        vals = struct.unpack_from('<' + 'h' * KON_FIELD_COUNT, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _) in enumerate(KON_FIELDS):
            rec[fn] = vals[fi]
        recs.append(rec)
    return recs

def save_kon(fp, recs):
    buf = bytearray(KON_CNT * KON_REC)
    for rec in recs[:KON_CNT]:
        i = rec['index']; off = i * KON_REC
        vals = [rec[fn] for fn, _, _, _ in KON_FIELDS]
        struct.pack_into('<' + 'h' * KON_FIELD_COUNT, buf, off, *vals)
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# GUI
# ============================================================

class KonEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKKon.dat 可视化编辑器 v2.0")
        self.root.geometry("1320x820"); self.root.minsize(1050, 650)
        self.kon_path = self.tkt_path = None
        self.records = []; self.tkt = {}
        self.filtered_indices = []; self._dirty = False
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
        em.add_command(label="新建条件", command=self._new_record, accelerator="Ctrl+N")
        em.add_command(label="复制当前记录", command=self._copy_record)
        em.add_command(label="清空当前记录", command=self._clear_current)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_record())
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
        # Filter toggle for empty records
        self.show_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="显示空槽", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned); paned.add(lf, weight=2)
        cols = ('index', 'cond_id', 'cond_type', 'tkt_name', 'value', 'end_flag')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [
            ('index', '记录#', 50),
            ('cond_id', '条件ID', 55),
            ('cond_type', '类型', 65),
            ('tkt_name', 'TKT解析/名称', 230),
            ('value', '参数值', 55),
            ('end_flag', '结束', 45),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'tkt_name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('active', foreground='#228B22')  # 有内容的条件
        self.tree.tag_configure('empty', foreground='#AAAAAA')    # 空记录

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
        pv_lf = ttk.LabelFrame(self.edit_inner, text="条件预览", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        for c in range(4): pv_lf.columnconfigure(c, weight=1)
        LBL_CLR = '#666'

        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground=LBL_CLR).grid(
            row=0, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=700, justify='left')
        self.preview_name.grid(row=0, column=1, columnspan=3, sticky='ew', pady=1)

        ttk.Label(pv_lf, text="详情:", font=FONT_S, foreground=LBL_CLR).grid(
            row=1, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_info = ttk.Label(pv_lf, text="", foreground='#228B22',
                                       font=FONT_S, wraplength=700, justify='left')
        self.preview_info.grid(row=1, column=1, columnspan=3, sticky='ew', pady=1)

        # Field groups — active fields only, skip unused
        self._build_field_group("核心属性 (offset 0–8)", ACTIVE_FIELDS[:5], 1, 5)
        self._build_field_group("参数区 (offset 10–18)", ACTIVE_FIELDS[5:10], 2, 5)
        self._build_field_group("扩展参数 (offset 20–28)", ACTIVE_FIELDS[10:15], 3, 5)
        self._build_field_group("未使用 (offset 30–36) + 结束标记", KON_FIELDS[15:], 4, 5)

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_kon = ttk.Label(pf, text="", foreground="gray")
        self.lbl_kon.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field_group(self, title, fields, row, cols):
        lf = ttk.LabelFrame(self.edit_inner, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            is_unused = fn.startswith('unused')
            self._build_field(grid, r, c, fn, fo, fl, W_INPUT, cmt, readonly=is_unused)

    def _build_field(self, parent, row, col, fn, fo, fl, fw, cmt, readonly=False):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=fl, font=FONT_S)
        if readonly:
            lbl.configure(foreground='#AAA')
        lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        box = ttk.Frame(frm); box.pack(fill=tk.X)
        ev = tk.StringVar(); self._edit_vars[fn] = ev
        ent = ttk.Entry(box, textvariable=ev, width=fw, font=FONT)
        if readonly:
            ent.configure(state='readonly', foreground='#AAA')
        ent.pack(side=tk.LEFT)
        # TKT 文本解析显示 (for non-unused fields)
        if not readonly:
            self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#3366cc',
                                               font=FONT_S, wraplength=180)
            self._edit_extras[fn].pack(anchor=tk.W)

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
        ko = os.path.join(d, "TKKon.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(ko):
            messagebox.showwarning("文件缺失", "未找到 TKKon.dat"); return
        self.kon_path = ko
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.kon_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
        try:
            self.records = load_kon(self.kon_path); self._dirty = False
            nonempty = sum(1 for r in self.records
                          if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
            self.status_var.set(
                f"{len(self.records)} 条 (40字节/条) | 有效 {nonempty} | TKT {len(self.tkt)} 条")
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
        _f(self.lbl_kon, self.kon_path)
        _f(self.lbl_tkt, self.tkt_path)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        for rec in self.records:
            if not self.show_empty.get():
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                    continue
            if q:
                nm = kon_record_name(rec, self.tkt)
                search_text = f"{rec['index']} {rec['cond_id']} {rec['cond_type']} {nm} " \
                              f"{' '.join(str(rec[fn]) for fn,_,_,_ in KON_FIELDS)}".lower()
                if q not in search_text:
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records
                      if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        msg = f"显示 {len(self.filtered_indices)}/{KON_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set(""); self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            nm = kon_record_name(r, self.tkt)
            has_data = any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS)
            tags = ['active'] if has_data else ['empty']
            val_str = str(r['value']) if r['value'] != 0 else ""
            if r['value'] == -1: val_str = "终止"
            ef = r['end_flag']
            ef_str = str(ef) if ef != 0 else ""
            self.tree.insert('', 'end',
                             values=(r['index'], r['cond_id'], r['cond_type'],
                                     nm if nm else f"(空-#{idx})",
                                     val_str, ef_str),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'tkt_name':
            self.filtered_indices.sort(
                key=lambda i: kon_record_name(self.records[i], self.tkt).lower(), reverse=rev)
        else:
            km = {'cond_id': 'cond_id', 'cond_type': 'cond_type', 'value': 'value',
                  'end_flag': 'end_flag'}
            self.filtered_indices.sort(
                key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ----------- 编辑 -----------

    def _new_record(self):
        if not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                rec['cond_type'] = 256; rec['target1'] = 256
                rec['cond_id'] = rec['index']
                rec['value'] = -1; rec['end_flag'] = 4
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child); self.tree.see(child); break
                self._populate_edit(rec)
                self.status_var.set(f"已创建新条件 → 槽位 #{rec['index']} (ID={rec['cond_id']})"); return
        messagebox.showwarning("槽位已满", f"所有 {KON_CNT} 个槽位均已占用")

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'): return
        src = self.records[self._editing_idx]
        if all(src[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            messagebox.showinfo("提示", "当前记录为空, 无需复制"); return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True; self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child); self.tree.see(child); break
                self._populate_edit(rec)
                self.status_var.set(f"已复制 #{src['index']} → #{rec['index']}"); return
        messagebox.showwarning("槽位已满", f"所有 {KON_CNT} 个槽位均已占用")

    def _clear_current(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            messagebox.showinfo("提示", "当前记录已经为空"); return
        if not messagebox.askyesno("确认清空", f"确定清空条件 #{rec['index']} 的所有字段?"):
            return
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = 0
        rec['cond_id'] = 0; rec['index'] = rec['index']  # preserve index
        self._dirty = True; self._apply_filter()
        self._populate_edit(rec)
        self.status_var.set(f"已清空条件 #{rec['index']}")

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        nm = kon_record_name(rec, self.tkt)
        ct = rec.get('cond_type', 0)
        ct_txt = resolve_kon_val(ct, self.tkt)
        cid = rec.get('cond_id', 0)

        self.lbl_rec_idx.config(text=(
            f"记录 #{rec['index']}    条件ID={cid}    类型={ct}"
            + (f" ({ct_txt})" if ct_txt else "")
            + (f"    名称={nm}" if nm else "")
        ))

        # Preview
        self.preview_name.config(text=nm if nm else "(无TKT匹配)")
        info_parts = []
        t1 = rec.get('target1', 0)
        if t1: info_parts.append(f"目标1={t1}" + (f"({resolve_kon_val(t1, self.tkt)})" if resolve_kon_val(t1, self.tkt) else ""))
        m = rec.get('mode', 0)
        if m: info_parts.append(f"模式={m}" + (f"({resolve_kon_val(m, self.tkt)})" if resolve_kon_val(m, self.tkt) else ""))
        v = rec.get('value', 0)
        if v: info_parts.append(f"参数值={v}")
        d1 = rec.get('dialog1', 0)
        if d1: info_parts.append(f"对话1={d1}" + (f"({resolve_kon_val(d1, self.tkt)})" if resolve_kon_val(d1, self.tkt) else ""))
        d2 = rec.get('dialog2', 0)
        if d2: info_parts.append(f"对话2={d2}" + (f"({resolve_kon_val(d2, self.tkt)})" if resolve_kon_val(d2, self.tkt) else ""))
        ef = rec.get('end_flag', 0)
        if ef: info_parts.append(f"结束标记={ef}")
        self.preview_info.config(text=" | ".join(info_parts) if info_parts else "(空条件)")

        # 填充编辑控件
        for fn, fo, fl, _ in KON_FIELDS:
            val = rec.get(fn, 0); sv = str(val)
            self._edit_vars.get(fn, tk.StringVar()).set(sv)
            if fn in self._edit_extras:
                resolved = resolve_kon_val(int(val) if val else 0, self.tkt)
                self._edit_extras[fn].config(text=resolved)

    # ----------- 编辑应用 -----------

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, _ in KON_FIELDS:
            if fn.startswith('unused'): continue  # skip unused readonly fields
            try:
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

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.kon_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.kon_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.kon_path, 'rb') as s:
                with open(self.kon_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.set("正在保存…"); self.root.update()
            save_kon(self.kon_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.kon_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.kon_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['记录索引', '条件ID', 'TKT解析名称'] + [fn for fn, _, _, _ in KON_FIELDS]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
                row = [str(rec['index']), str(rec.get('cond_id', '')),
                       kon_record_name(rec, self.tkt)]
                row += [str(rec[fn]) for fn, _, _, _ in KON_FIELDS]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = ["TKKon.dat 字段映射 v2.0 (重新分析修正)", ""]
        lines.append(f"【记录布局】{KON_CNT} 条 × {KON_REC} 字节 = {KON_DECOMPRESSED} 字节")
        lines.append(f"  20 × int16 (小端序) 共 {KON_REC} 字节/条")
        lines.append("")
        lines.append("【★ 2026-05 修正要点】")
        lines.append("  旧版: 13×int16 (26字节) × 1000条 = 26000 ← 错误!")
        lines.append("  修正: 20×int16 (40字节) × 650条  = 26000 ← 正确!")
        lines.append("  证据: sub_4434BC 按 word_9D069E[20*i] (stride=40字节) 索引;")
        lines.append("        field[3] 在所有 650 条中为 0..649 顺序递增的唯一ID")
        lines.append("")
        lines.append("【字段详情】")
        for fn, fo, fl, cmt in KON_FIELDS:
            marker = " ● 未使用" if fn.startswith('unused') else ""
            lines.append(f"  [{fo:02d}] {fl:<10s}{marker}")
            lines.append(f"       {cmt}")
        lines.append("")
        lines.append("【反编译函数引用】")
        lines.append("  sub_4173F8: sub_45343C(aTkkonDat, &unk_9D0698, 26000)")
        lines.append("  sub_4434BC: word_9D069E[20*i] 索引 (offset 6, stride 40=20×int16)")
        lines.append("  Maker.exe sub_4027FF: 解压后大小校验 v19 == 26000")
        lines.append("  sub_45343C:  DAT 统一加载 (LZSS 解压)")
        lines.append("  sub_452B14:  LZSS 解压引擎")

        dlg = tk.Toplevel(self.root); dlg.title("字段参考 v2.0 (修正版)")
        dlg.geometry("680x560"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKKon.dat 可视化编辑器 v2.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "2026-05 修正版: 650条 × 40字节 (20×int16)\n\n"
            "旧版错误: 误用 1000条 × 26字节 (13×int16)\n"
            "修正依据: sub_4434BC (word_9D069E[20*i]),\n"
            "          field[3] 顺序索引 0..649 验证\n\n"
            "逆向来源:\n"
            "  sub_4173F8  TKKon 加载\n"
            "  sub_4434BC  条件运行时处理\n"
            "  sub_45343C  DAT 统一加载\n"
            "  sub_452B14  LZSS 解压引擎"
        )


def main():
    root = tk.Tk(); KonEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
