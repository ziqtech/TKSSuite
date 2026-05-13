#!/usr/bin/env python3
"""
TKDefUnit.dat 可视化编辑器
=============================================================
严格依据逆向工程。每条记录 16 字节 = 8 × uint16 LE, 共 5000 条。

=== 字段语义 (仅含反编译代码直接证实的) ===

  ✓ = 反编译代码证实    ★ = 无任何函数访问

  f0 [00] 字段0 (语义未证实)
          反编译仅检查整个 DWORD(f0|f1<<16)==0, 未单独读取 f0
  f1 [02] 实体ID ✓
          sub_402E88:31 v2=*(int*)(buf+16*i)>>16 → 索引 NPC 表
          NPC表 dword_51AF40: 96 DWORD/条, 含坐标/动画/脚本PC/链表头
  f2 [04] 脚本Ptr(低) ✓
          文件值无意义(通常=0); sub_402E88:38 运行时 = sub_41425C()
          sub_41425C 创建实体脚本对象; sub_40EBD4:22 读为字节码基址
  f3 [06] 脚本Ptr(高) ✓
          与 f2 组成 32位脚本指针; sub_40EBD4 以此为基址执行脚本指令
  f4 [08] 字段4 ★
          反编译代码中完全未引用 (无法证实任何语义)
  f5 [10] 字段5 ★
          反编译代码中完全未引用 (无法证实任何语义)
  f6 [12] 链表下一节点 ✓
          sub_4066F0:53 *(DWORD*)(buf+16*v7+12) 遍历链
          NPC表存 3 个链表头(索引39/40/41)对应子场景A/B/C
  f7 [14] 字段7 (DWORD对齐)
          全部为0; 使 offset 12-15 可作 DWORD 读取

=== 核心反编译函数 ===
  sub_402E88: 加载 TKDefUnit.dat, 分配 80000 字节, 5000条×16B
  sub_452544: 原始 ReadFile (无 LZSS 压缩)
  sub_40EBD4: 实体脚本解释器 (82+指令, switch case 0-66/82)
  sub_4066F0: DefUnit 链表遍历 (offset 12 作 DWORD)
  sub_4119CC: 清理 (释放 offset 4 脚本指针 → 确认为运行时数据)
  sub_40C044: 场景切换 (a1=实体ID, a2=X坐标, a3=Y坐标, a4=绘图层)
  sub_41425C: 创建实体脚本对象, 返回值存 offset 4
  sub_402BE8: TKD 脚本解析 (aDefine/aEnd), 计数指令

用法:
  python defunit_editor.py
"""

import struct
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# 常量 (sub_402E88: dword_753504=5000, 16*dword_753504=80000)
# ============================================================

REC_SIZE = 16
REC_COUNT = 5000
FILE_SIZE = 80000
FIELD_COUNT = 8

# TKMat.Dat 交叉引用常量
MAT_REC_SIZE = 384
MAT_REC_COUNT = 6000
MAT_DWORD_COUNT = 96
SCENE_NAME_TKT_BASE = 300
ENTITY_TYPES = {0:"空槽",5:"入口/传送点",10:"地形块",15:"障碍物",16:"建筑/门",
                20:"事件对象",110:"特殊机关",200:"NPC/角色"}

# ============================================================
# 字段语义定义
# 严格依据反编译代码 — 每个字段标注证据函数和行号
# ============================================================
#
#   反编译代码访问汇总 (全部 DeUnit 数据引用):
#   ┌──────────┬────────────────────────────────────────────┐
#   │ 偏移     │ 访问函数                                    │
#   ├──────────┼────────────────────────────────────────────┤
#   │ 0-3      │ sub_402E88:29  *(DWORD*)(buf+16*i)!=0 判空 │
#   │          │ sub_402E88:31  >>16 提取实体ID              │
#   │ 4-7      │ sub_402E88:34  写0 (无效实体)               │
#   │          │ sub_402E88:38  写 sub_41425C() 返回值       │
#   │          │ sub_40EBD4:22  读为脚本字节码指针            │
#   │          │ sub_4119CC:72  遍历释放非零指针              │
#   │ 8-11     │ ★ 无任何反编译函数访问 ★                    │
#   │ 12-15    │ sub_4066F0:53  *(DWORD*)(buf+16*v7+12) 遍历│
#   └──────────┴────────────────────────────────────────────┘
#
#   NPC实体表 dword_51AF40 (96 DWORD/条, 384字节):
#   索引 39/40/41 = 三个子场景的 DefUnit 链表头 (sub_4066F0)
#   索引 42 = 脚本PC (sub_40EBD4)
#   索引 44 = 初始 DefUnit 记录索引 (sub_40EBD4:18)
#   索引 30-35 = 子场景 A/B/C 计数器 (max/cur, sub_40EBD4 case 0)

PRIMARY_FIELDS = [
    ("f0",  0, "字段0 (语义未证实)",
     "反编译代码仅检查整个 DWORD(f0|f1<<16)==0, 未单独读取 f0\n"
     "实测: 18种值 (范围 0-266, 含 256-265 序列)\n"
     "注意: 无反编译代码证实 f0 有独立语义, 以下仅为数据观察"),
    ("f1",  2, "实体ID ✓",
     "sub_402E88:31 v2=*(int*)(buf+16*i)>>16\n"
     "→ 索引 NPC 表 dword_51AF40[96*v2+dword_4E6EF0]\n"
     "NPC表 96 DWORD/条 (384字节), 含坐标/动画/脚本状态"),
    ("f2",  4, "脚本Ptr(低) ✓",
     "文件值无意义 (通常=0, 实测仅13条非零)\n"
     "运行时: sub_402E88:38 = sub_41425C(dword_4FA598-1, dword_4FA000)\n"
     "sub_41425C 创建实体脚本对象并返回指针\n"
     "sub_4119CC:72 遍历释放此指针 → 确认为动态分配"),
    ("f3",  6, "脚本Ptr(高) ✓",
     "与 f2 组成 32位脚本指针, sub_40EBD4:22 读此 DWORD\n"
     "作为脚本字节码基址: *(WORD*)(ptr + 2*PC + N) 读取指令"),
]

SECONDARY_FIELDS = [
    ("f4",  8, "字段4 (语义未证实)",
     "★ 反编译代码中完全未引用 ★\n"
     "实测: 17种值, 449条非零; 数值分布类似 f0\n"
     "无任何函数单独读取 offset 8-11"),
    ("f5", 10, "字段5 (语义未证实)",
     "★ 反编译代码中完全未引用 ★\n"
     "实测: 258种值, 449条非零; 数值分布类似 f1\n"
     "无任何函数单独读取 offset 8-11"),
    ("f6", 12, "链表下一节点 ✓",
     "sub_4066F0:53 *(DWORD*)(buf+16*v7+12) 遍历链\n"
     "NPC表存 3 个链表头 (索引 39/40/41, 对应子场景 A/B/C)\n"
     "sub_4066F0 遍历逻辑: for(i=1; i<=max; i++) v7=DefUnit[16*v7+12]\n"
     "实测: 472条非零, 267个链表头; f7=0 故 DWORD 即 f6 值"),
    ("f7", 14, "字段7 (DWORD对齐)",
     "实测: 全部1541条有效记录均为 0\n"
     "使 offset 12-15 可作 DWORD 读: f6|(f7<<16) = f6"),
]

ALL_FIELDS = PRIMARY_FIELDS + SECONDARY_FIELDS


# ============================================================
# 数据加载/保存
# ============================================================

def load_defunit(fp):
    """加载 TKDefUnit.dat — sub_452544: 原始 ReadFile, 无 LZSS 压缩"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if len(raw) != FILE_SIZE:
        raise ValueError(f"文件大小异常: {len(raw)}, 期望 {FILE_SIZE}")
    recs = []
    for i in range(REC_COUNT):
        off = i * REC_SIZE
        fields = struct.unpack_from('<' + 'H' * FIELD_COUNT, raw, off)
        rec = {'index': i}
        for fi in range(FIELD_COUNT):
            rec[f'f{fi}'] = fields[fi]
        recs.append(rec)
    return recs


def save_defunit(fp, recs):
    """保存 TKDefUnit.dat — 原始二进制写入"""
    buf = bytearray(FILE_SIZE)
    for rec in recs[:REC_COUNT]:
        off = rec['index'] * REC_SIZE
        for fi in range(FIELD_COUNT):
            struct.pack_into('<H', buf, off + fi * 2, rec.get(f'f{fi}', 0))
    with open(fp, 'wb') as f:
        f.write(bytes(buf))
    return True


def load_mat_entities(fp):
    """加载 TKMat.Dat 实体关键字段用于交叉引用"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if len(raw) != MAT_REC_SIZE * MAT_REC_COUNT:
        return []
    ents = []
    for i in range(MAT_REC_COUNT):
        off = i * MAT_REC_SIZE
        dw = struct.unpack_from('<' + 'i' * MAT_DWORD_COUNT, raw, off)
        if dw[0] != 0:  # 非空实体
            ents.append({
                'index': i, 'type': dw[0], 'scene_id': dw[1],
                'flags': dw[2], 'x': dw[10], 'y': dw[11],
                'direction': dw[13], 'cur_define': dw[28],
                'defunit_idx': dw[44], 'char_id': dw[50],
                'picture_id': dw[51], 'dir_mode': dw[53],
                'sub_model': dw[64], 'moving': dw[70],
            })
    return ents


def load_tkt_scene_names(tkt_path):
    """加载 TKT.dat 场景名称"""
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    total_size = struct.unpack_from('<I', raw, 0)[0]
    count = struct.unpack_from('<I', raw, 4)[0]
    dec = bytes(b ^ 0xFF for b in raw[8:8 + total_size])
    id_sz, off_sz = count * 4, count * 4
    tb = id_sz + off_sz
    lookup = {}
    for i in range(count):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        off = struct.unpack_from('<I', dec, id_sz + i * 4)[0]
        ao = tb + off
        if ao >= len(dec):
            continue
        end = ao
        while end < len(dec) and dec[end] != 0:
            end += 1
        txt = dec[ao:end].replace(b'\x1e', b'\n')
        try:
            s = txt.decode('big5', errors='replace')
        except Exception:
            s = txt.decode('gbk', errors='replace')
        if s:
            lookup[eid] = s.split('\n')[0].strip()
    return lookup


# ============================================================
# 空记录检测 (sub_402E88: *(DWORD*)(buf+16*i)==0 → LABEL_10)
# ============================================================

def is_empty(rec):
    """空记录: 前 4 字节 DWORD == 0 (sub_402E88)"""
    return rec['f0'] == 0 and rec['f1'] == 0


def has_data(rec):
    return any(rec.get(f'f{fi}', 0) != 0 for fi in range(FIELD_COUNT))


# ============================================================
# 链表分析 (sub_4066F0: *(DWORD*)(buf+16*v7+12))
# ============================================================

def build_chains(recs):
    """构建 f6 链表 (sub_4066F0 遍历逻辑)"""
    next_map = {}
    for rec in recs:
        if has_data(rec) and rec['f6'] != 0:
            next_map[rec['index']] = rec['f6']
    pointed_to = set(next_map.values())
    heads = sorted(set(next_map.keys()) - pointed_to)
    return next_map, heads


def trace_chain(recs, start, next_map, max_len=50):
    """追踪从 start 开始的链表"""
    chain = [start]
    cur = start
    visited = {start}
    while cur in next_map:
        nxt = next_map[cur]
        if nxt in visited:
            chain.append(f"(循环→{nxt})")
            break
        if nxt >= REC_COUNT:
            chain.append(f"(越界→{nxt})")
            break
        visited.add(nxt)
        chain.append(nxt)
        cur = nxt
        if len(chain) >= max_len:
            chain.append("...")
            break
    return chain


# ============================================================
# GUI
# ============================================================

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_BOLD = ('Microsoft YaHei UI', 11, 'bold')


class DefUnitEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKDefUnit.dat 可视化编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1180x760")
        self.root.minsize(950, 560)

        self.dat_path = None
        self.mat_path = None
        self.tkt_path = None
        self.records = []
        self.mat_entities = []    # TKMat.Dat 实体列表 (交叉引用)
        self.mat_entity_map = {}  # index -> entity dict
        self.tkt_scenes = {}      # TKT 场景名称
        self.filtered_indices = []
        self.chain_next = {}   # f6 链表映射
        self.chain_heads = []  # 链表头
        self._dirty = False
        self._chain_highlight = set()

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1180) // 2
        y = (sh - 760) // 2
        self.root.geometry(f'1180x760+{x}+{y}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir,
                       accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="另存为…", command=self._save_as,
                       accelerator="Ctrl+Shift+S")
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新增记录", command=self._new_record,
                       accelerator="Ctrl+N")
        em.add_command(label="复制当前记录", command=self._copy_record)
        em.add_command(label="清空当前记录", command=self._clear_current)
        mb.add_cascade(label="编辑", menu=em)

        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="显示当前记录链表", command=self._show_chain)
        vm.add_command(label="清空链表高亮", command=self._clear_chain_highlight)
        vm.add_separator()
        vm.add_command(label="统计信息", command=self._show_stats)
        mb.add_cascade(label="查看", menu=vm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="导出 CSV…", command=self._export_csv)
        hm.add_command(label="字段说明 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-Shift-S>', lambda e: self._save_as())
        self.root.bind('<Control-n>', lambda e: self._new_record())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))

        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.search_var, width=20)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(
            side=tk.LEFT, padx=1)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        self.show_empty = tk.BooleanVar(value=False)
        ttk.Checkbutton(tb, text="显示空记录", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(tb, text="重新加载", command=self._reload).pack(
            side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(
            value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # 主区域 PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # === 左侧: 记录列表 ===
        lf = ttk.Frame(paned)
        paned.add(lf, weight=2)

        cols = ('index', 'f0', 'f1', 'f6')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings',
                                 selectmode='browse')
        col_defs = [
            ('index', '索引', 50),
            ('f0', '字段0(*)', 72),
            ('f1', '实体ID', 72),
            ('f6', '下一节点', 60),
        ]
        for cid, cn, cw in col_defs:
            self.tree.heading(cid, text=cn,
                              command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw,
                             anchor='center' if cid in ('index', 'f0', 'f1', 'f6')
                             else 'w', minwidth=cw)

        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('chain', background='#FFF0D0')
        self.tree.tag_configure('empty', foreground='#AAA')

        # === 右侧: 编辑面板 ===
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=FONT_BOLD)
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 6), padx=4)

        # 滚动区域
        middle = ttk.Frame(rf)
        middle.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(middle)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scb = ttk.Scrollbar(middle, orient=tk.VERTICAL)
        scb.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(left_col, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind(
            '<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self._canvas_win = canvas.create_window(
            (0, 0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=scb.set)
        canvas.bind(
            '<Configure>',
            lambda e: self.edit_inner.columnconfigure(0, minsize=e.width))

        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._edit_vars = {}
        self._edit_labels = {}

        # 编辑字段组
        self._build_semantic_group(
            "主单元 [offset 0-7]",
            PRIMARY_FIELDS, 0)
        self._build_semantic_group(
            "第二单元 [offset 8-15]",
            SECONDARY_FIELDS, 1)

        # 链表预览
        lf_chain = ttk.LabelFrame(self.edit_inner,
                                  text="链表追踪 (sub_4066F0)", padding=4)
        lf_chain.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        self.chain_info = ttk.Label(lf_chain, text="", font=FONT_S,
                                    foreground='#CC6633', wraplength=600,
                                    justify='left')
        self.chain_info.pack(anchor=tk.W, padx=2)

        # TKMat.Dat 实体交叉引用
        lf_mat = ttk.LabelFrame(self.edit_inner,
                                text="TKMat.Dat 实体引用 [f1=实体ID]", padding=4)
        lf_mat.grid(row=3, column=0, sticky='ew', padx=2, pady=2)
        self.mat_info = ttk.Label(lf_mat, text="(未加载)", font=FONT_S,
                                  foreground='#3366cc', wraplength=600,
                                  justify='left')
        self.mat_info.pack(anchor=tk.W, padx=2)

        # 底部按钮
        bf = ttk.Frame(rf)
        bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(
            side=tk.LEFT)
        ttk.Button(bf, text="重置", command=self._reset_edit, width=8).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(bf, text="追踪链表", command=self._show_chain, width=10).pack(
            side=tk.LEFT, padx=8)
        ttk.Button(bf, text="跳转到空槽…", command=self._goto_empty, width=12).pack(
            side=tk.RIGHT, padx=2)

        # 底部路径栏
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_dat = ttk.Label(pf, text="", foreground="gray")
        self.lbl_dat.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_semantic_group(self, title, fields, row):
        """构建语义字段组"""
        lf = ttk.LabelFrame(self.edit_inner, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)

        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X)

        for fi, (key, off, label, cmt) in enumerate(fields):
            r, c = divmod(fi, 2)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, sticky='nw', padx=4, pady=3)

            lbl = ttk.Label(frm, text=f"[{off:02d}] {label}", font=FONT_S)
            lbl.pack(anchor=tk.W)
            self._bind_tooltip(lbl, f"offset {off:02d}\n{cmt}")

            ev = tk.StringVar()
            self._edit_vars[key] = ev
            ttk.Entry(frm, textvariable=ev, width=10, font=FONT).pack(fill=tk.X)

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget); w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid',
                      borderwidth=1, font=FONT_S, wraplength=480,
                      padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']: tip['win'].destroy(); tip['win'] = None
        widget.bind('<Enter>', _enter); widget.bind('<Leave>', _leave)

    # ----------- 数据加载 (加载目录模式) -----------

    def _load_tks_dir(self):
        """加载 TKS 游戏目录 (TKDefUnit.dat + TKMat.Dat + TKT.dat)"""
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return
        du = os.path.join(d, "TKDefUnit.dat")
        if not os.path.exists(du):
            messagebox.showwarning("文件缺失", f"未找到 TKDefUnit.dat\n{d}")
            return
        self.dat_path = du
        # 交叉引用文件 (可选)
        mat_p = os.path.join(d, "TKMat.Dat")
        tkt_p = os.path.join(d, "TKT.dat")
        self.mat_path = mat_p if os.path.exists(mat_p) else None
        self.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        self._reload()

    def _reload(self):
        if not self.dat_path:
            return
        self.status_var.set("加载中…")
        self.root.update()
        try:
            self.records = load_defunit(self.dat_path)
            self._dirty = False
            self.chain_next, self.chain_heads = build_chains(self.records)
            self._chain_highlight = set()
            # 加载 TKMat.Dat 交叉引用
            if self.mat_path:
                self.mat_entities = load_mat_entities(self.mat_path)
                self.mat_entity_map = {e['index']: e for e in self.mat_entities}
            else:
                self.mat_entities = []
                self.mat_entity_map = {}
            # 加载 TKT 场景名
            if self.tkt_path:
                self.tkt_scenes = load_tkt_scene_names(self.tkt_path)
            else:
                self.tkt_scenes = {}
            nonempty = sum(1 for r in self.records if has_data(r))
            self.status_var.set(
                f"{REC_COUNT} 条 | 有效 {nonempty} | "
                f"链表 {len(self.chain_heads)} 条"
                f"{' | TKMat '+str(len(self.mat_entities))+'实体' if self.mat_entities else ''}")
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
        except Exception:
            pass
        for c in w.winfo_children():
            self._set_ws(c, en)

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    def _update_paths(self):
        G, R = "#228B22", "#CC3333"
        def _f(lb, p, tp):
            if not p: lb.config(text=tp, foreground=R)
            elif not os.path.exists(p):
                lb.config(text=f"(不存在) {p}", foreground=R)
            else: lb.config(text=p, foreground=G)
        _f(self.lbl_dat, self.dat_path, "(未加载 TKDefUnit.dat)")

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.search_var.get().strip().lower()
        self.filtered_indices = []
        for rec in self.records:
            if not self.show_empty.get() and is_empty(rec):
                continue
            if q:
                parts = [str(rec['index'])]
                for fi in range(FIELD_COUNT):
                    parts.append(str(rec[f'f{fi}']))
                if q not in ' '.join(parts).lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _clear_filter(self):
        self.search_var.set("")
        self._apply_filter()

    def _refresh_table(self):
        sel_idx = None
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], 'values')
            if vals: sel_idx = vals[0]

        self.tree.delete(*self.tree.get_children())
        for idx in self.filtered_indices:
            rec = self.records[idx]
            vals = (
                str(idx),
                str(rec['f0']),
                str(rec['f1']),
                str(rec['f6']) if rec['f6'] else "",
            )
            tags = []
            if is_empty(rec):
                tags.append('empty')
            if idx in self._chain_highlight:
                tags.append('chain')
            self.tree.insert('', 'end', values=vals, tags=tuple(tags))

        if sel_idx:
            for item in self.tree.get_children():
                if self.tree.item(item, 'values')[0] == sel_idx:
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    break

    def _sort_by(self, col):
        ci = {'index': 0, 'f0': 1, 'f1': 2, 'f6': 3}.get(col, 0)
        items = [(self.tree.item(item, 'values'), item)
                 for item in self.tree.get_children()]
        try:
            items.sort(key=lambda x: (int(x[0][ci])
                       if x[0][ci] and ci <= 3 else 0)
                       if ci <= 3 else x[0][ci])
        except Exception:
            items.sort(key=lambda x: x[0][ci])
        for i, (_, item) in enumerate(items):
            self.tree.move(item, '', i)

    # ----------- 编辑 -----------

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self.lbl_rec_idx.config(text="未选中")
            self._clear_edit()
            return
        vals = self.tree.item(sel[0], 'values')
        idx = int(vals[0])
        self._show_record(self.records[idx])

    def _show_record(self, rec):
        idx = rec['index']
        empty_flag = "(空槽)" if is_empty(rec) else ""
        self.lbl_rec_idx.config(text=f"记录 #{idx} {empty_flag}")

        for fi in range(FIELD_COUNT):
            key = f'f{fi}'
            self._edit_vars[key].set(str(rec[key]))

        # 链表信息
        self._update_chain_display(idx)

        # TKMat.Dat 实体交叉引用
        self._update_mat_info(rec['f1'])

    def _update_chain_display(self, idx):
        """更新链表追踪显示 (sub_4066F0)"""
        if idx in self.chain_next or idx in self.chain_next.values():
            rev_map = {v: k for k, v in self.chain_next.items()}
            head = idx
            while head in rev_map:
                head = rev_map[head]

            chain = trace_chain(self.records, head, self.chain_next)
            chain_strs = []
            for ci in chain[:30]:
                if isinstance(ci, str):
                    chain_strs.append(ci)
                else:
                    r = self.records[ci]
                    mark = "◀" if ci == idx else ""
                    chain_strs.append(f"#{ci}{mark}(f0={r['f0']}, f1={r['f1']})")
            info = f"链表 #{head} (共 {len(chain)} 节点):\n"
            info += " → ".join(chain_strs)
            self.chain_info.config(text=info)
        else:
            self.chain_info.config(
                text="(此记录不在链表中 — f6=0 且无其他节点指向它)")

    def _update_mat_info(self, entity_id):
        """显示 f1 对应的 TKMat.Dat 实体信息"""
        if not self.mat_entity_map or entity_id not in self.mat_entity_map:
            self.mat_info.config(
                text="(未加载 TKMat.Dat 或实体不存在)")
            return
        e = self.mat_entity_map[entity_id]
        tname = ENTITY_TYPES.get(e['type'], f"未知({e['type']})")
        sid = e['scene_id']
        sname = self.tkt_scenes.get(SCENE_NAME_TKT_BASE + sid, f"场景{sid}") if sid >= 0 else "全局"
        info = (
            f"实体 #{entity_id}  [{tname}]  场景: {sname} (ID={sid})\n"
            f"坐标: ({e['x']}, {e['y']})  朝向: {e['direction']}  "
            f"方向模式: {e['dir_mode']}  移动中: {'是' if e['moving'] else '否'}\n"
            f"DEFINE: {e['cur_define']}  "
            f"DefUnit索引: {e['defunit_idx']}  "
            f"图片ID: {e['picture_id']}  子模型: {e['sub_model']}  "
            f"char_id: {e['char_id']}"
        )
        self.mat_info.config(text=info)

    def _clear_edit(self):
        for fi in range(FIELD_COUNT):
            self._edit_vars[f'f{fi}'].set("")
        self.chain_info.config(text="")
        self.mat_info.config(text="(未加载)")

    def _read_form(self):
        vals = {}
        for fi in range(FIELD_COUNT):
            key = f'f{fi}'
            try:
                v = int(self._edit_vars[key].get())
                if v < 0 or v > 0xFFFF:
                    raise ValueError
                vals[key] = v
            except ValueError:
                return None
        return vals

    def _apply_edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        new_vals = self._read_form()
        if new_vals is None:
            messagebox.showwarning("输入错误", "字段值必须是 0-65535 整数")
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        rec = self.records[idx]
        for fi in range(FIELD_COUNT):
            rec[f'f{fi}'] = new_vals[f'f{fi}']
        self._dirty = True
        # 重建链表映射
        self.chain_next, self.chain_heads = build_chains(self.records)
        self._show_record(rec)
        self._apply_filter()

    def _reset_edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        self._show_record(self.records[idx])

    # ----------- 新增/复制/清空 -----------

    def _new_record(self):
        if not self.records:
            return
        empty_idx = None
        for rec in self.records:
            if is_empty(rec):
                empty_idx = rec['index']
                break
        if empty_idx is None:
            messagebox.showinfo("无空槽", f"所有 {REC_COUNT} 条记录均已占用")
            return
        rec = self.records[empty_idx]
        # 除 f1 外全部置零, 用户自行填入实体ID
        for fi in range(FIELD_COUNT):
            rec[f'f{fi}'] = 0
        self._dirty = True
        self._apply_filter()
        for item in self.tree.get_children():
            if self.tree.item(item, 'values')[0] == str(empty_idx):
                self.tree.selection_set(item)
                self.tree.see(item)
                self._show_record(rec)
                break

    def _copy_record(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择记录")
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        src = self.records[idx]
        empty_idx = None
        for rec in self.records:
            if is_empty(rec):
                empty_idx = rec['index']
                break
        if empty_idx is None:
            messagebox.showinfo("无空槽", f"所有 {REC_COUNT} 条记录均已占用")
            return
        dst = self.records[empty_idx]
        for fi in range(FIELD_COUNT):
            dst[f'f{fi}'] = src[f'f{fi}']
        self._dirty = True
        self.chain_next, self.chain_heads = build_chains(self.records)
        self._apply_filter()
        for item in self.tree.get_children():
            if self.tree.item(item, 'values')[0] == str(empty_idx):
                self.tree.selection_set(item)
                self.tree.see(item)
                self._show_record(dst)
                break

    def _clear_current(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        if not messagebox.askyesno("确认", f"清空记录 #{idx}? (全部字段置零)"):
            return
        for fi in range(FIELD_COUNT):
            self.records[idx][f'f{fi}'] = 0
        self._dirty = True
        self.chain_next, self.chain_heads = build_chains(self.records)
        self._apply_filter()
        self._show_record(self.records[idx])
        self.mat_info.config(text="(已清空)")

    def _goto_empty(self):
        for rec in self.records:
            if is_empty(rec):
                self.search_var.set("")
                self.show_empty.set(True)
                self._apply_filter()
                for item in self.tree.get_children():
                    if self.tree.item(item, 'values')[0] == str(rec['index']):
                        self.tree.selection_set(item)
                        self.tree.see(item)
                        self._show_record(rec)
                        return
        messagebox.showinfo("提示", "无空槽")

    # ----------- 链表查看 -----------

    def _show_chain(self):
        """高亮当前记录所在的链表"""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        self._chain_highlight = set()
        if idx in self.chain_next or idx in self.chain_next.values():
            rev_map = {v: k for k, v in self.chain_next.items()}
            head = idx
            while head in rev_map:
                head = rev_map[head]
            chain = trace_chain(self.records, head, self.chain_next)
            for ci in chain:
                if isinstance(ci, int):
                    self._chain_highlight.add(ci)
        else:
            return
        self._apply_filter()
        # 跳转到链表头
        for item in self.tree.get_children():
            if self.tree.item(item, 'values')[0] == str(head):
                self.tree.selection_set(item)
                self.tree.see(item)
                self._show_record(self.records[head])
                break

    def _clear_chain_highlight(self):
        self._chain_highlight = set()
        self._apply_filter()

    # ----------- 统计 -----------

    def _show_stats(self):
        if not self.records:
            return
        nonempty = sum(1 for r in self.records if has_data(r))
        empty_cnt = sum(1 for r in self.records if is_empty(r))
        f0_vals = sorted(set(r['f0'] for r in self.records if has_data(r) and r['f0']))
        f1_vals = set(r['f1'] for r in self.records if has_data(r) and r['f1'])
        f2_nonzero = sum(1 for r in self.records if r['f2'])
        f4_nonzero = sum(1 for r in self.records if r['f4'])
        f5_nonzero = sum(1 for r in self.records if r['f5'])
        f6_nonzero = sum(1 for r in self.records if has_data(r) and r['f6'])
        chains = len(self.chain_heads)

        msg = (
            f"TKDefUnit.dat 统计 (sub_402E88: 5000×16B={FILE_SIZE}B)\n"
            f"{'─'*50}\n"
            f"有效记录: {nonempty} (DWORD≠0)\n"
            f"空记录:   {empty_cnt} (DWORD=0)\n\n"
            f"=== 已证实语义 ===\n"
            f"f1 实体ID: {len(f1_vals)} 种 (NPC表索引)\n"
            f"f2 非零:   {f2_nonzero} 条 (13条含文件值)\n"
            f"f3 非零:   {sum(1 for r in self.records if r['f3'])} 条\n"
            f"f6 链表:   {f6_nonzero} 条 → {chains} 条链 (sub_4066F0)\n\n"
            f"=== 未证实语义 ===\n"
            f"f0 值:     {f0_vals}\n"
            f"f4 非零:   {f4_nonzero} 条 (值域类似 f0)\n"
            f"f5 非零:   {f5_nonzero} 条 (值域类似 f1)\n"
            f"f7:        全部为 0 (DWORD对齐)\n"
        )
        messagebox.showinfo("统计信息", msg)

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.dat_path:
            self._save_as()
            return
        try:
            save_defunit(self.dat_path, self.records)
            self._dirty = False
            self.status_var.set("已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _save_as(self):
        fp = filedialog.asksaveasfilename(
            title="另存 TKDefUnit.dat",
            defaultextension=".dat",
            filetypes=[("DAT 文件", "*.dat"), ("所有文件", "*.*")])
        if not fp:
            return
        try:
            save_defunit(fp, self.records)
            self.dat_path = fp
            self._dirty = False
            self._update_paths()
            self.status_var.set("已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        fp = filedialog.asksaveasfilename(
            title="导出 CSV", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not fp:
            return
        with open(fp, 'w', encoding='utf-8-sig') as f:
            headers = ['index'] + [f'f{i}' for i in range(FIELD_COUNT)]
            f.write(','.join(headers) + '\n')
            for rec in self.records:
                if not has_data(rec):
                    continue
                row = [str(rec['index'])]
                for fi in range(FIELD_COUNT):
                    row.append(str(rec[f'f{fi}']))
                f.write(','.join(row) + '\n')
        messagebox.showinfo("导出完成", f"已导出到 {fp}")

    def _show_field_ref(self):
        msg = (
            "TKDefUnit.dat 字段语义 — 仅含反编译代码直接证实的\n"
            f"{'─'*55}\n\n"
            "✓ = 反编译证实  ★ = 无任何函数访问\n\n"
            "【主单元 — bytes 0-7】\n"
            "f0 [00] 语义未证实\n"
            "  反编译仅检查 DWORD(f0|f1<<16)==0, 未单独读取\n"
            "  实测: 18种值 (含 256-265 序列)\n\n"
            "f1 [02] 实体ID ✓ sub_402E88:31\n"
            "  v2=*(int*)(buf+16*i)>>16 → NPC表索引\n"
            "  NPC表 96 DWORD/条, 含坐标/动画/脚本\n\n"
            "f2-f3 [04-07] 脚本指针 ✓ sub_402E88:38, sub_4119CC:72\n"
            "  文件值=0 (仅13条非零)\n"
            "  运行时 = sub_41425C() 返回的脚本对象指针\n"
            "  sub_40EBD4:22 读此指针为脚本字节码基址\n\n"
            "【第二单元 — bytes 8-11】\n"
            "f4 [08] ★ 反编译代码中完全未引用 ★\n"
            "  实测: 17种值, 数值分布类似 f0\n"
            "f5 [10] ★ 反编译代码中完全未引用 ★\n"
            "  实测: 258种值, 数值分布类似 f1\n\n"
            "【链表 — bytes 12-15】\n"
            "f6 [12] 链表下一节点 ✓ sub_4066F0:53\n"
            "  *(DWORD*)(buf+16*v7+12) 遍历链\n"
            "  NPC表存3个链表头(索引39/40/41)→子场景A/B/C\n"
            "  实测: 472条非零, 267个链表头\n"
            "f7 [14] 全部为0 — DWORD对齐\n"
            "  使 offset 12-15 可作 DWORD: f6|(f7<<16)=f6\n\n"
            "【空记录】✓ sub_402E88:29\n"
            "  if(!*(DWORD*)(buf+16*i)) → 清零\n\n"
            "【关键发现】\n"
            "  sub_40EBD4 case 19: 脚本中 spawn 实体\n"
            "  a1=实体ID, a2=X坐标, a3=Y坐标, a4=绘图层(1-8)\n"
            "  sub_407070: a1[10]=a2(X), a1[11]=a3(Y)\n"
            "  sub_4077E4: a1[13]=a4(绘图层)\n"
        )
        messagebox.showinfo("字段说明 (逆向来源)", msg)

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKDefUnit.dat 可视化编辑器\n\n"
            "已证实语义 (反编译代码直接证据):\n"
            "  f1 实体ID — sub_402E88:31\n"
            "  f2-f3 脚本指针 — sub_402E88:38 / sub_4119CC:72\n"
            "  f6 链表下一节点 — sub_4066F0:53\n\n"
            "未证实语义 (无反编译代码引用):\n"
            "  f0, f4, f5, f7\n\n"
            "核心函数:\n"
            "  sub_402E88: 加载, 16B×5000, 判空\n"
            "  sub_452544: 原始 ReadFile (无压缩)\n"
            "  sub_40EBD4: 脚本解释器 (82+指令)\n"
            "  sub_4066F0: 链表遍历 (3子场景)\n"
            "  sub_40C044: 场景切换 (实体ID+XY坐标+绘图层)\n"
            f"总大小: {FILE_SIZE} 字节"
        )


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    app = DefUnitEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
