#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器
=============================================================
逆向依据:
  sub_412688:21: sub_452544(aTkmatDat_0, dword_51AF40, 2304000)
    → 原始二进制读取, 6000条 × 384B (96×int32) = 2,304,000B
  sub_41103C:26: sub_452B14(v5, &v8, dword_51AF40)
    → 场景文件 LZSS 解压覆盖实体表区域
  sub_405CBC: 实体类型分支 (5/10/15/16/20/110/200)
  sub_4077E4: 朝向 [13], sub_407070: 坐标 [10][11]
  sub_40C388: tick [4], sub_40BF88: timer [3]
  sub_40EBD4: 脚本PC[42]/DefUnit索引[44]/子场景[30-35]
  sub_4066F0: DefUnit链头[39-41]
  sub_40C5A4/sub_40C648: 标志位 [2] bit0/bit1

用法:
  python mat_editor.py
"""

import struct
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# 常量
# ============================================================

REC_SIZE = 384       # 96 × 4 字节
REC_COUNT = 6000     # 实体总数
FILE_SIZE = 2304000  # 6000 × 384
DWORD_COUNT = 96     # 每条记录 96 个 int32

ENTITY_TYPES = {
    0: "空槽",
    5: "入口/传送点",
    10: "地形块",
    15: "障碍物",
    16: "建筑/门",
    20: "事件对象",
    110: "特殊机关",
    200: "NPC/角色",
}

TYPE_COLORS = {
    0: "#AAA",
    5: "#2196F3",
    10: "#4CAF50",
    15: "#FF9800",
    16: "#795548",
    20: "#9C27B0",
    110: "#E91E63",
    200: "#F44336",
}

DIR_MODES = {0: "静态", 4: "NPC四方向", 8: "玩家八方向"}

# ============================================================
# 字段分组定义
# ============================================================

BASIC_FIELDS = [
    ("type", 0, "实体类型", "实体类型: 5=入口 10=地形 15=障碍 16=建筑 20=事件 110=机关 200=NPC"),
    ("scene_id", 1, "场景ID", "所属场景 (-1=全局)。TKT_ID = scene_id + 300"),
    ("flags", 2, "标志位", "sub_40C5A4/40C648: bit0=启用 bit1=活跃"),
    ("param", 3, "扩展参数", "扩展参数 (道具数量/金钱等)"),
]

POS_FIELDS = [
    ("x", 10, "坐标X", "世界坐标X (像素)。sub_407070: a1[10]=x"),
    ("y", 11, "坐标Y", "世界坐标Y (像素)。sub_407070: a1[11]=y"),
    ("bound_x", 18, "碰撞X", "碰撞盒/区域X起点。sub_410B74"),
    ("bound_y", 19, "碰撞Y", "碰撞盒/区域Y起点。sub_410B74"),
    ("direction", 13, "朝向", "朝向 1~8。sub_4077E4: if(a2>0&&a2<=8) a1[13]=a2"),
]

ANIM_FIELDS = [
    ("anim_set", 9, "动画集ID", "动画集索引 0-4。sub_405CBC: dword_755AC0[v2[9]]"),
    ("dir_mode", 53, "方向模式", "4=NPC四方向 8=玩家八方向 0=静态。sub_4077E4"),
    ("sub_model", 64, "子模型ID", "子角色动画模型ID。sub_405CBC, sub_40C1A4"),
    ("anim_speed", 69, "动画速度", "动画播放速度/延迟。sub_40C1A4"),
]

SCRIPT_FIELDS = [
    ("cur_define", 28, "当前DEFINE", "当前激活的DEFINE脚本号。sub_40B520"),
    ("defunit_idx", 44, "DefUnit索引", "DefUnit记录索引。sub_40EBD4: word_755AB2=[96*a1+44]"),
    ("max_A", 30, "子场景最大A", "子场景A最大阶段数。sub_40B520, sub_40EBD4"),
    ("max_B", 31, "子场景最大B", ""),
    ("max_C", 32, "子场景最大C", ""),
    ("cur_A", 33, "子场景当前A", "子场景A当前阶段。sub_40EBD4 case 0"),
    ("cur_B", 34, "子场景当前B", ""),
    ("cur_C", 35, "子场景当前C", ""),
    ("head_A", 39, "DefUnit链头A", "子场景A的DefUnit链头。sub_4066F0(a2=0)"),
    ("head_B", 40, "DefUnit链头B", "子场景B的DefUnit链头。sub_4066F0(a2=1)"),
    ("head_C", 41, "DefUnit链头C", "子场景C的DefUnit链头。sub_4066F0(a2=2)"),
]

INTERACT_FIELDS = [
    ("char_id", 50, "所需角色ID", "条件: 若>0 必须匹配玩家角色ID。sub_4081F8"),
    ("picture_id", 51, "图片ID", "角色图片ID/访问位掩码。sub_4081F8, sub_405CBC"),
    ("anim_handle", 52, "动画句柄", "主动画句柄 (通常运行时赋值)。sub_405CBC, sub_40D0CC"),
]

RUNTIME_FIELDS = [
    ("tick", 4, "tick", "事件Tick周期。sub_40C388: [96*a1+4]=a2 (运行时)"),
    ("sub_flags", 8, "子标志", "运行时标志。sub_408E5C"),
    ("timer", 12, "计时器", "等待计时器。sub_40BF88 (运行时)"),
    ("frame_idx", 14, "帧索引", "当前动画帧索引。sub_4077E4 (运行时)"),
    ("frame_count", 16, "总帧数", "总帧数。sub_4540E8 (运行时)"),
    ("frame_cur", 17, "帧计数", "当前帧计数。sub_405CBC (运行时)"),
    ("script_PC", 42, "脚本PC", "脚本程序计数器。sub_40EBD4 (运行时)"),
    ("saved_PC", 43, "保存PC", "保存的程序计数器。sub_40EBD4 (运行时)"),
    ("saved_x", 56, "保存X", "保存的X坐标。sub_408E5C (运行时)"),
    ("saved_y", 57, "保存Y", "保存的Y坐标。sub_408E5C (运行时)"),
    ("dest_x", 60, "目标X", "移动目标X。sub_408E5C (运行时)"),
    ("dest_y", 61, "目标Y", "移动目标Y。sub_408E5C (运行时)"),
    ("sub_handle", 65, "子句柄", "子角色动画句柄。sub_405CBC (运行时)"),
    ("cur_frame", 67, "当前帧", "当前动画帧。sub_405CBC (运行时)"),
    ("max_frame", 68, "最大帧", "最大动画帧。sub_405CBC (运行时)"),
    ("moving", 70, "移动中", "移动中标志。sub_4077E4 (运行时)"),
]

ALL_EDIT_FIELDS = (BASIC_FIELDS + POS_FIELDS + ANIM_FIELDS +
                   SCRIPT_FIELDS + INTERACT_FIELDS)

# ============================================================
# TKT 场景名加载
# ============================================================

SCENE_NAME_TKT_BASE = 300  # TKT_ID = scene_id + 300


def load_tkt_scene_names(tkt_path):
    """从 TKT.dat 加载场景名称 (TKT_ID = scene_id + 300)。"""
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    total_size = struct.unpack_from('<I', raw, 0)[0]
    count = struct.unpack_from('<I', raw, 4)[0]
    dec = bytes(b ^ 0xFF for b in raw[8:8 + total_size])

    id_table_size = count * 4
    offset_table_size = count * 4
    text_base = id_table_size + offset_table_size

    lookup = {}
    for i in range(count):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        off = struct.unpack_from('<I', dec, id_table_size + i * 4)[0]
        ao = text_base + off
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


def scene_name(tkt_lookup, sid):
    """获取场景名称"""
    if sid == -1:
        return "全局(所有场景)"
    tkt_id = SCENE_NAME_TKT_BASE + sid
    return tkt_lookup.get(tkt_id, f"场景{sid}")


# ============================================================
# 数据加载/保存
# ============================================================

def load_mat(fp):
    """加载 TKMat.Dat — sub_412688: sub_452544 原始读取"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if len(raw) != FILE_SIZE:
        raise ValueError(f"文件大小异常: {len(raw)}, 期望 {FILE_SIZE}")
    recs = []
    for i in range(REC_COUNT):
        off = i * REC_SIZE
        dwords = struct.unpack_from('<' + 'i' * DWORD_COUNT, raw, off)
        rec = {'index': i}
        for di in range(DWORD_COUNT):
            rec[f'd{di}'] = dwords[di]
        recs.append(rec)
    return recs


def save_mat(fp, recs):
    """保存 TKMat.Dat — 原始二进制写入"""
    buf = bytearray(FILE_SIZE)
    for rec in recs[:REC_COUNT]:
        off = rec['index'] * REC_SIZE
        for di in range(DWORD_COUNT):
            struct.pack_into('<i', buf, off + di * 4,
                             rec.get(f'd{di}', 0))
    with open(fp, 'wb') as f:
        f.write(bytes(buf))
    return True


def is_empty(rec):
    """空记录: type == 0"""
    return rec['d0'] == 0


def has_data(rec):
    return rec['d0'] != 0


# ============================================================
# GUI
# ============================================================

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_B = ('Microsoft YaHei UI', 11, 'bold')


class MatEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKMat.Dat 地图实体编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1220x780")
        self.root.minsize(980, 580)

        self.dat_path = None
        self.tkt_path = None
        self.records = []
        self.tkt_scenes = {}
        self.filtered_indices = []
        self._dirty = False

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f'1220x780+{(sw-1220)//2}+{(sh-780)//2}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_dir,
                       accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="另存为…", command=self._save_as)
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
        vm.add_command(label="统计信息", command=self._show_stats)
        vm.add_command(label="场景列表", command=self._show_scene_list)
        mb.add_cascade(label="查看", menu=vm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="导出 CSV…", command=self._export_csv)
        hm.add_command(label="字段说明", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.bind('<Control-o>', lambda e: self._load_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_record())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))

        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.search_var, width=16)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter,
                   width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter,
                   width=5).pack(side=tk.LEFT, padx=1)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(tb, text="类型:").pack(side=tk.LEFT)
        self.filter_type = tk.StringVar(value="全部")
        type_choices = ["全部"] + [f"{k}-{v}" for k, v in
                                   sorted(ENTITY_TYPES.items()) if k != 0]
        cb_type = ttk.Combobox(tb, textvariable=self.filter_type,
                               values=type_choices, state='readonly', width=14)
        cb_type.pack(side=tk.LEFT, padx=2)
        cb_type.bind('<<ComboboxSelected>>', lambda e: self._apply_filter())

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(tb, text="场景:").pack(side=tk.LEFT)
        self.filter_scene = tk.StringVar(value="全部")
        self.cb_scene = ttk.Combobox(tb, textvariable=self.filter_scene,
                                     values=["全部"], state='readonly',
                                     width=18)
        self.cb_scene.pack(side=tk.LEFT, padx=2)
        self.cb_scene.bind('<<ComboboxSelected>>',
                           lambda e: self._apply_filter())

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        self.show_empty = tk.BooleanVar(value=False)
        ttk.Checkbutton(tb, text="显示空槽", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(tb, text="重新加载", command=self._reload).pack(
            side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(
            value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # 主区域
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧列表
        lf = ttk.Frame(paned)
        paned.add(lf, weight=2)

        cols = ('index', 'type', 'scene', 'x', 'y')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings',
                                 selectmode='browse')
        col_defs = [
            ('index', '索引', 55),
            ('type', '类型', 100),
            ('scene', '场景', 140),
            ('x', 'X', 55),
            ('y', 'Y', 55),
        ]
        for cid, cn, cw in col_defs:
            self.tree.heading(cid, text=cn,
                              command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw,
                             anchor='center' if cid in ('index', 'x', 'y')
                             else 'w', minwidth=cw)

        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        for tval, color in TYPE_COLORS.items():
            self.tree.tag_configure(f'type{tval}', foreground=color)

        # 右侧编辑面板
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_title = ttk.Label(rf, text="未选中", font=FONT_B)
        self.lbl_title.pack(anchor=tk.W, pady=(0, 6), padx=4)

        # 滚动区域
        mid = ttk.Frame(rf)
        mid.pack(fill=tk.BOTH, expand=True)
        lc = ttk.Frame(mid)
        lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scb = ttk.Scrollbar(mid, orient=tk.VERTICAL)
        scb.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(lc, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind('<Configure>',
                             lambda e: canvas.configure(
                                 scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.edit_inner, anchor='nw')
        canvas.configure(yscrollcommand=scb.set)
        canvas.bind('<Configure>',
                    lambda e: self.edit_inner.columnconfigure(0,
                                                              minsize=e.width))

        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._edit_vars = {}

        # 编辑字段组
        self._build_group("基础属性", BASIC_FIELDS, 0)
        self._build_group("位置", POS_FIELDS, 1)
        self._build_group("动画", ANIM_FIELDS, 2)
        self._build_group("脚本", SCRIPT_FIELDS, 3)
        self._build_group("交互/角色", INTERACT_FIELDS, 4)
        self._build_group("运行时 (只读)", RUNTIME_FIELDS, 5)

        # 底部按钮
        bf = ttk.Frame(rf)
        bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit,
                   width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置", command=self._reset_edit,
                   width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="跳转到空槽…", command=self._goto_empty,
                   width=12).pack(side=tk.RIGHT, padx=2)

        # 底部路径
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_group(self, title, fields, row):
        lf = ttk.LabelFrame(self.edit_inner, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X)

        for fi, (key, di, label, cmt) in enumerate(fields):
            r, c = divmod(fi, 3)
            frm = ttk.Frame(grid)
            frm.grid(row=r, column=c, sticky='nw', padx=4, pady=2)

            lbl = ttk.Label(frm, text=f"[{di:02d}] {label}", font=FONT_S)
            lbl.pack(anchor=tk.W)
            if cmt:
                self._bind_tooltip(lbl, f"[{di:02d}] {cmt}")

            if key == 'type':
                cb = ttk.Combobox(
                    frm, state='readonly',
                    values=[f"{k}-{v}" for k, v in
                            sorted(ENTITY_TYPES.items())],
                    width=14, font=FONT)
                cb.pack(fill=tk.X)
                self._edit_vars[key] = cb
            elif key == 'dir_mode':
                cb = ttk.Combobox(
                    frm, state='readonly',
                    values=[f"{k}-{v}" for k, v in DIR_MODES.items()],
                    width=14, font=FONT)
                cb.pack(fill=tk.X)
                self._edit_vars[key] = cb
            else:
                ev = tk.StringVar()
                self._edit_vars[key] = ev
                ttk.Entry(frm, textvariable=ev, width=14,
                          font=FONT).pack(fill=tk.X)

            # 场景名显示
            if key == 'scene_id':
                nl = ttk.Label(frm, text="", foreground='#3366cc',
                               font=FONT_S, wraplength=150)
                nl.pack(anchor=tk.W)
                self._edit_vars['_scene_label'] = nl

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget); w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid',
                      borderwidth=1, font=FONT_S, wraplength=450,
                      padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']: tip['win'].destroy(); tip['win'] = None
        widget.bind('<Enter>', _enter); widget.bind('<Leave>', _leave)

    # ----------- 数据加载 -----------

    def _load_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return
        mat_p = os.path.join(d, "TKMat.Dat")
        tkt_p = os.path.join(d, "TKT.dat")
        if not os.path.exists(mat_p):
            messagebox.showwarning("文件缺失", f"未找到 TKMat.Dat\n{d}")
            return
        self.dat_path = mat_p
        self.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        self._reload()

    def _reload(self):
        if not self.dat_path:
            return
        self.status_var.set("加载中…")
        self.root.update()
        if self.tkt_path:
            self.tkt_scenes = load_tkt_scene_names(self.tkt_path)
        try:
            self.records = load_mat(self.dat_path)
            self._dirty = False
            nonempty = sum(1 for r in self.records if has_data(r))
            scenes = set(r['d1'] for r in self.records if has_data(r))
            self.status_var.set(
                f"{REC_COUNT} 条 | 有效 {nonempty} | 场景 {len(scenes)} | "
                f"TKT {len(self.tkt_scenes)} 条")
            # 更新场景筛选列表
            scene_choices = ["全部"] + sorted(
                f"{s}: {scene_name(self.tkt_scenes, s)}" for s in scenes)
            self.cb_scene['values'] = scene_choices
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            self.records = []
        self._update_path()
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
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton,
                                ttk.Button)):
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

    def _update_path(self):
        G, R = "#228B22", "#CC3333"
        if not self.dat_path:
            self.lbl_path.config(text="(未加载)", foreground=R)
        elif not os.path.exists(self.dat_path):
            self.lbl_path.config(text=f"(不存在) {self.dat_path}",
                                 foreground=R)
        else:
            self.lbl_path.config(text=self.dat_path, foreground=G)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.search_var.get().strip().lower()
        ftype = self.filter_type.get()
        fscene = self.filter_scene.get()
        self.filtered_indices = []

        for rec in self.records:
            if not self.show_empty.get() and is_empty(rec):
                continue

            # 类型筛选
            if ftype and ftype != "全部":
                tval = int(ftype.split('-')[0])
                if rec['d0'] != tval:
                    continue

            # 场景筛选
            if fscene and fscene != "全部":
                sid = int(fscene.split(':')[0])
                if rec['d1'] != sid:
                    continue

            # 文本搜索
            if q:
                parts = [str(rec['index']), str(rec['d0']), str(rec['d1']),
                         str(rec['d10']), str(rec['d11'])]
                sname = scene_name(self.tkt_scenes, rec['d1'])
                parts.append(sname)
                tname = ENTITY_TYPES.get(rec['d0'], '')
                parts.append(tname)
                if q not in ' '.join(parts).lower():
                    continue

            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _clear_filter(self):
        self.search_var.set("")
        self.filter_type.set("全部")
        self.filter_scene.set("全部")
        self._apply_filter()

    def _refresh_table(self):
        sel_idx = None
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], 'values')
            if vals:
                sel_idx = vals[0]

        self.tree.delete(*self.tree.get_children())
        for idx in self.filtered_indices:
            rec = self.records[idx]
            tval = rec['d0']
            sname = scene_name(self.tkt_scenes, rec['d1'])
            vals = (str(idx),
                    f"{tval}-{ENTITY_TYPES.get(tval, '未知')}",
                    sname,
                    str(rec['d10']),
                    str(rec['d11']))
            tag = f'type{tval}' if tval in TYPE_COLORS else ''
            self.tree.insert('', 'end', values=vals, tags=(tag,))

        if sel_idx:
            for item in self.tree.get_children():
                if self.tree.item(item, 'values')[0] == sel_idx:
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    break

    def _sort_by(self, col):
        ci = {'index': 0, 'type': 1, 'scene': 2, 'x': 3, 'y': 4}.get(col, 0)
        items = [(self.tree.item(item, 'values'), item)
                 for item in self.tree.get_children()]
        try:
            items.sort(key=lambda x: (
                int(x[0][ci]) if x[0][ci].lstrip('-').isdigit() else 0)
                if ci in (0, 3, 4) else x[0][ci])
        except Exception:
            pass
        for i, (_, item) in enumerate(items):
            self.tree.move(item, '', i)

    # ----------- 编辑 -----------

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self.lbl_title.config(text="未选中")
            self._clear_form()
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        self._show_record(self.records[idx])

    def _show_record(self, rec):
        idx = rec['index']
        tval = rec['d0']
        tname = ENTITY_TYPES.get(tval, f"未知({tval})")
        sname = scene_name(self.tkt_scenes, rec['d1'])
        self.lbl_title.config(
            text=f"实体 #{idx}  [{tname}]  {sname}  ({rec['d10']},{rec['d11']})")

        for key, di, label, cmt in ALL_EDIT_FIELDS:
            val = rec[f'd{di}']
            if key == 'type':
                self._edit_vars[key].set(f"{val}-{ENTITY_TYPES.get(val, '未知')}")
            elif key == 'dir_mode':
                self._edit_vars[key].set(
                    f"{val}-{DIR_MODES.get(val, '其他')}" if val in DIR_MODES
                    else f"{val}-其他")
            else:
                self._edit_vars[key].set(str(val))

        # 运行时字段 (只读)
        for key, di, label, cmt in RUNTIME_FIELDS:
            if key in self._edit_vars:
                self._edit_vars[key].set(str(rec[f'd{di}']))

        # 场景名标签
        if '_scene_label' in self._edit_vars:
            self._edit_vars['_scene_label'].config(text=sname)

    def _clear_form(self):
        for key, var in self._edit_vars.items():
            if isinstance(var, tk.StringVar):
                var.set("")
            elif isinstance(var, ttk.Combobox):
                var.set("")
        if '_scene_label' in self._edit_vars:
            self._edit_vars['_scene_label'].config(text="")

    def _read_form(self):
        vals = {}
        for key, di, label, cmt in ALL_EDIT_FIELDS:
            var = self._edit_vars[key]
            if isinstance(var, ttk.Combobox):
                raw = var.get()
                try:
                    v = int(raw.split('-')[0])
                except (ValueError, IndexError):
                    return None
            else:
                try:
                    v = int(var.get())
                except ValueError:
                    return None
            vals[f'd{di}'] = v
        return vals

    def _apply_edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        new_vals = self._read_form()
        if new_vals is None:
            messagebox.showwarning("输入错误", "字段值必须是整数")
            return
        idx = int(self.tree.item(sel[0], 'values')[0])
        rec = self.records[idx]
        for key, val in new_vals.items():
            rec[key] = val
        self._dirty = True
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
        for di in range(DWORD_COUNT):
            rec[f'd{di}'] = 0
        rec['d0'] = 200  # 默认 NPC
        rec['d1'] = -1   # 全局场景
        rec['d10'] = 0
        rec['d11'] = 0
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
        for di in range(DWORD_COUNT):
            dst[f'd{di}'] = src[f'd{di}']
        dst['index'] = empty_idx  # keep index
        self._dirty = True
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
        if not messagebox.askyesno("确认", f"清空实体 #{idx}? (type 设为 0)"):
            return
        for di in range(DWORD_COUNT):
            self.records[idx][f'd{di}'] = 0
        self._dirty = True
        self._apply_filter()
        self._show_record(self.records[idx])

    def _goto_empty(self):
        for rec in self.records:
            if is_empty(rec):
                self.search_var.set("")
                self.filter_type.set("全部")
                self.filter_scene.set("全部")
                self.show_empty.set(True)
                self._apply_filter()
                for item in self.tree.get_children():
                    if self.tree.item(item, 'values')[0] == str(rec['index']):
                        self.tree.selection_set(item)
                        self.tree.see(item)
                        self._show_record(rec)
                        return
        messagebox.showinfo("提示", "无空槽")

    # ----------- 查看 -----------

    def _show_stats(self):
        if not self.records:
            return
        from collections import Counter
        type_cnt = Counter()
        scene_cnt = Counter()
        for rec in self.records:
            if has_data(rec):
                type_cnt[rec['d0']] += 1
                scene_cnt[rec['d1']] += 1
        nonempty = sum(type_cnt.values())

        msg = (f"TKMat.Dat 统计\n{'─'*40}\n"
               f"总槽位: {REC_COUNT} | 有效: {nonempty} | "
               f"空: {REC_COUNT - nonempty}\n"
               f"场景数: {len(scene_cnt)}\n\n"
               f"类型分布:\n")
        for tval in sorted(type_cnt.keys()):
            tname = ENTITY_TYPES.get(tval, f"类型{tval}")
            cnt = type_cnt[tval]
            msg += f"  {tval}-{tname}: {cnt} ({cnt/nonempty*100:.1f}%)\n"
        messagebox.showinfo("统计信息", msg)

    def _show_scene_list(self):
        if not self.records:
            return
        from collections import defaultdict
        scene_map = defaultdict(list)
        for rec in self.records:
            if has_data(rec):
                scene_map[rec['d1']].append(rec['index'])

        lines = [f"{'场景ID':<6} {'场景名称':<24} {'实体数':<6}"]
        lines.append('-' * 40)
        for sid in sorted(scene_map.keys()):
            sname = scene_name(self.tkt_scenes, sid)
            lines.append(f"{sid:<6} {sname:<24} {len(scene_map[sid]):<6}")

        top = tk.Toplevel(self.root)
        top.title("场景列表")
        top.geometry("500x500")
        txt = tk.Text(top, font=('Consolas', 10), wrap='none')
        txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        txt.insert('1.0', '\n'.join(lines))
        txt.config(state='disabled')

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.dat_path:
            self._save_as()
            return
        try:
            save_mat(self.dat_path, self.records)
            self._dirty = False
            self.status_var.set("已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _save_as(self):
        fp = filedialog.asksaveasfilename(
            title="另存 TKMat.Dat",
            defaultextension=".Dat",
            filetypes=[("DAT 文件", "*.Dat;*.dat"), ("所有文件", "*.*")])
        if not fp:
            return
        try:
            save_mat(fp, self.records)
            self.dat_path = fp
            self._dirty = False
            self._update_path()
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
            headers = ['index'] + [f'd{i}' for i in range(DWORD_COUNT)]
            headers += ['type_name', 'scene_name']
            f.write(','.join(headers) + '\n')
            for rec in self.records:
                if not has_data(rec):
                    continue
                row = [str(rec['index'])]
                for di in range(DWORD_COUNT):
                    row.append(str(rec[f'd{di}']))
                row.append(ENTITY_TYPES.get(rec['d0'], ''))
                row.append(scene_name(self.tkt_scenes, rec['d1']))
                f.write(','.join(row) + '\n')
        messagebox.showinfo("导出完成", f"已导出到 {fp}")

    def _show_field_ref(self):
        msg = (
            "TKMat.Dat 实体表字段说明\n"
            f"{'─'*50}\n\n"
            "加载: sub_412688:21 sub_452544(TKMat.Dat, dword_51AF40, 2304000)\n"
            "结构: 6000条 × 384B (96 × int32 LE)\n\n"
            "已证实字段 (反编译代码):\n"
            "  [0] type — sub_405CBC 类型分支\n"
            "  [1] scene_id — 场景归属\n"
            "  [2] flags — sub_40C5A4/40C648 启用/禁用\n"
            "  [3] timer — sub_40BF88 SetWait\n"
            "  [4] tick — sub_40C388 SetTick\n"
            "  [10][11] x/y — sub_407070 坐标\n"
            "  [13] direction — sub_4077E4 朝向(1-8)\n"
            "  [30-35] sub-scene counters — sub_40EBD4 case 0\n"
            "  [39-41] DefUnit chain heads — sub_4066F0\n"
            "  [42-43] script PC — sub_40EBD4\n"
            "  [44] defunit_idx — sub_40EBD4:18\n"
            "  [53] dir_mode — sub_4077E4 (4/8方向)\n"
        )
        messagebox.showinfo("字段说明", msg)

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKMat.Dat 地图实体编辑器\n\n"
            "逆向依据:\n"
            "  sub_412688: 加载 TKMat.Dat → dword_51AF40\n"
            "  sub_405CBC: 实体类型分支渲染\n"
            "  sub_4077E4: 朝向设置\n"
            "  sub_40EBD4: 脚本解释器\n"
            f"格式: {REC_COUNT}条 × {REC_SIZE}B = {FILE_SIZE}B"
        )


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    app = MatEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
