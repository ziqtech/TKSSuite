#!/usr/bin/env python3
"""
TKAct.dat 可视化编辑器 v1.0
=============================================================
逆向依据 (sub_4434BC 动画运行时处理, sub_452544 加载, sub_411624 初始化):
  - sub_452544:     原始文件读取 (非 LZSS), 509600 字节
  - sub_411624:     sub_452544(aTkactDat, &unk_9539CA, 509600)
  - sub_4434BC:     qmemcpy(&unk_9D037A, 784*sprite_idx+9779658, 0x310)
                    每帧循环: v44 = v22[8*v33+i]; instance = &unk_9D037A + 80*v44
  - Maker.exe:      650 条动画定义, 每 784 字节

结构 (784 字节/条):
  头部 (80 字节, offset 0-79):
    [0-31]  8 组 × 8 字节索引表 (每字节 = 1-based 槽位索引, 0=空)
            → sub_4434BC: v22[8*v33] 读取偏移 8*v33 处的组
    [32-63] 头部参数区 (32 字节 = 16 int16)
    [64-79] 头部参数续 (16 字节, 部分条目非零)

  实例槽位 1-8 (各 80 字节, 偏移=slot×80, slot 从 1 开始):
    int16[0]   type            — 类型 (1=普通动画, 2=?, 3=交互, 4=检查点, 5=结束动作)
            → sub_4434BC: *(_WORD *)dword_9D0690 == 1/4/5
    int16[1]   param_key       — sub_45410C 查表键值
            → sub_4434BC: *(__int16 *)(dword_9D0690 + 2)
    int16[2]   flag            — 标志位 (代码中与 4 比较)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 4) == 4
    int16[3-6] x_pos[4]        — 4 方向 X 偏移
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 2*v34 + 6)
    int16[7-10] y_pos[4]       — 4 方向 Y 偏移
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 2*v34 + 14)
    int16[11]  effect_type     — 效果类型 (switch 0-5)
            → sub_4434BC: switch(*(_WORD *)(dword_9D0690 + 22))
    int16[12]  effect_param    — 效果参数
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 24)
    int16[13]  delta           — 增量值
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 26) += *(_WORD *)(dword_9D0690 + 54)
    int16[14]  _runtime_init   — 运行时计算值 (sub_45408C 结果, 文件内恒为 0)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 28) = sub_45408C(...)
    int16[15]  _runtime_cur    — 运行时当前帧 (文件内恒为 0)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 30) = base + init
    int16[16]  extra_mult      — 额外乘数 (type=4 时乘以方向)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 32) * v33
    int16[17]  base_value      — 基础帧值
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 34)
    int16[18]  max_value       — 终止帧值
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 36)
    int16[19]  loop_behavior   — 循环行为
            → sub_4434BC: 0xFFFF(-1)=重置循环 0xFFFE(-2)=停用 >=0=跳转目标帧
    int16[20-21] _runtime      — 运行时 (文件内恒为 0)
    int16[22]  active_flag     — 活跃标记
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 44)
    int16[23]  _runtime_ctr    — 运行时计数器 (文件内恒为 0)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 46)
    int16[24]  _runtime_dir    — 运行时方向符号 (文件内恒为 0)
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 48) = 0/1/-1
    int16[25]  move_mode       — 移动模式
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 50) == 1/2
    int16[26]  step_value      — 步进值
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 52)
    int16[27]  step_delta      — 步进增量
            → sub_4434BC: *(_WORD *)(dword_9D0690 + 54)
    int16[28-39] _reserved     — 保留

  尾部数据 (64 字节, offset 720-783, 32 int16):
    未在 sub_4434BC 中直接引用的附加数据, 推测为精灵帧索引表
    (前 10 条目样本: Entry#0 包含 40,74,63,69,66 等值)

用法:
  python act_editor.py
"""

import struct, os, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# PIL 可选 (动画预览需要)
HAS_PIL = False
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass

# JVG 加载 (从 jvg_editor 导入)
_jvg_loader = None

def _get_jvg_loader():
    global _jvg_loader
    if _jvg_loader is None:
        jvg_dir = os.path.join(os.path.dirname(__file__), '..', 'jvg_editor')
        if jvg_dir not in sys.path:
            sys.path.insert(0, jvg_dir)
        try:
            import jvg_editor as _jvg_editor
            _jvg_loader = _jvg_editor
        except ImportError:
            _jvg_loader = False
    return _jvg_loader if _jvg_loader is not False else None

# ============================================================
# 常量 — 基于反编译验证
# ============================================================

ACT_ENTRY_SIZE = 784       # 每动画条目字节数
ACT_ENTRY_COUNT = 650      # 总条目数 (509600 / 784)
ACT_INST_SIZE = 80         # 每实例字节数 (40 int16)
ACT_MAX_INST = 8           # 最大实例槽位数 (索引组值范围 1-8)
ACT_HEADER_SIZE = 80       # 头部块大小
ACT_TAIL_OFFSET = 720      # 尾部数据起始偏移
ACT_TAIL_SIZE = 64         # 尾部数据大小 (bytes 720-783, 32 int16)
ACT_DECOMPRESSED = 509600  # 总文件大小

# 索引组标签 (头部 8 组 × 8 字节, sub_4434BC: 按 v22[8*v33] 偏移选取)
GROUP_LABELS = ["组0 (off 0)", "组1 (off 8)", "组2 (off 16)", "组3 (off 24)",
               "组4 (off 32)", "组5 (off 40)", "组6 (off 48)", "组7 (off 56)"]

# 类型值 (sub_4434BC: *(_WORD *)dword_9D0690)
#   1: v32=dword_951924(Cha.jvg), 受 0x4000 标志影响
#   2: v32=dword_951930(Ani.jvg)
#   3: 交互渲染路径 (L414), 位置固定 dir=0
#   4: 检查点 (L149), 保存参考坐标
#   5: 结束动作 (L156)
INST_TYPES = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5"}

# 效果类型 (sub_4434BC: switch at offset +22)
EFFECT_TYPES = {
    0: "0: sub_4544EC",
    1: "1: sub_454D24",
    2: "2: sub_4559D0",
    3: "3: sub_458020",
    4: "4: sub_459168",
    5: "5: sub_458D08",
}

# 循环行为 (sub_4434BC: offset +38 的比较)
#   0xFFFF(-1): 重置当前帧到基础值
#   0xFFFE(-2): 标记类型为0(停用)
#   >=0: 跳转到该帧
LOOP_LABELS = {-1: "-1 (0xFFFF)", -2: "-2 (0xFFFE)"}

# 移动模式 (sub_4434BC: +50 的比较)
#   1: 跟随模式 (L577-580)
#   2: 往返模式 (L582-591)
MOVE_MODES = {0: "0", 1: "1", 2: "2"}

# 运行时字段索引 (文件数据中始终为 0, 仅供运行时使用)
RUNTIME_FIELDS = {14, 15, 20, 21, 23, 24}

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 10
W_INPUT_S = 6

# ============================================================
# 字段定义 — 严格基于 sub_4434BC 反编译
# ============================================================

INST_FIELDS = [
    # (key, int16索引, 标签, 宽度, 注释/反编译来源)
    ("inst_type",       0,  "类型",        W_INPUT_S, "sub_4434BC: *(_WORD *)dword_9D0690"),
    ("param_key",       1,  "查表键",      W_INPUT,   "sub_4434BC: *(__int16 *)(dword_9D0690 + 2) → sub_45410C"),
    ("flag",            2,  "标志",        W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 4) == 4"),
    ("x_pos_d0",        3,  "X 方向0",     W_INPUT_S, "sub_4434BC: +2*v34+6 (v34=0)"),
    ("x_pos_d1",        4,  "X 方向1",     W_INPUT_S, "sub_4434BC: +2*v34+6 (v34=1)"),
    ("x_pos_d2",        5,  "X 方向2",     W_INPUT_S, "sub_4434BC: +2*v34+6 (v34=2)"),
    ("x_pos_d3",        6,  "X 方向3",     W_INPUT_S, "sub_4434BC: +2*v34+6 (v34=3)"),
    ("y_pos_d0",        7,  "Y 方向0",     W_INPUT_S, "sub_4434BC: +2*v34+14 (v34=0)"),
    ("y_pos_d1",        8,  "Y 方向1",     W_INPUT_S, "sub_4434BC: +2*v34+14 (v34=1)"),
    ("y_pos_d2",        9,  "Y 方向2",     W_INPUT_S, "sub_4434BC: +2*v34+14 (v34=2)"),
    ("y_pos_d3",        10, "Y 方向3",     W_INPUT_S, "sub_4434BC: +2*v34+14 (v34=3)"),
    ("effect_type",     11, "效果类型",    W_INPUT_S, "sub_4434BC: switch(*(_WORD *)(+22)) → 0-5"),
    ("effect_param",    12, "效果参数",    W_INPUT,   "sub_4434BC: *(_WORD *)(dword_9D0690 + 24)"),
    ("delta",           13, "增量",        W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 26)"),
    ("_runtime_init",   14, "●运行时初值", W_INPUT_S, "sub_4434BC: +28 = sub_45408C(...) [文件=0]"),
    ("_runtime_cur",    15, "●运行时当前", W_INPUT_S, "sub_4434BC: +30 = base+init [文件=0]"),
    ("extra_mult",      16, "额外乘数",    W_INPUT_S, "sub_4434BC: *(_WORD *)(+32) * v33 (type=4时)"),
    ("base_value",      17, "基础值",      W_INPUT,   "sub_4434BC: *(_WORD *)(dword_9D0690 + 34)"),
    ("max_value",       18, "最大值",      W_INPUT,   "sub_4434BC: *(_WORD *)(dword_9D0690 + 36)"),
    ("loop_behavior",   19, "循环行为",    W_INPUT_S, "sub_4434BC: +38: 0xFFFF=-1=重置 0xFFFE=-2=停用 >=0=跳转帧"),
    ("_runtime20",      20, "●运行时20",   W_INPUT_S, "运行时字段 [文件=0]"),
    ("_runtime21",      21, "●运行时21",   W_INPUT_S, "运行时字段 [文件=0]"),
    ("active_flag",     22, "活跃标记",    W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 44)"),
    ("_runtime_ctr",    23, "●运行时计数", W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 46) [文件=0]"),
    ("_runtime_dir",    24, "●运行时方向", W_INPUT_S, "sub_4434BC: +48 = 0/1/-1 [文件=0]"),
    ("move_mode",       25, "移动模式",    W_INPUT_S, "sub_4434BC: +50 == 1(跟随) == 2(往返)"),
    ("step_value",      26, "步进值",      W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 52)"),
    ("step_delta",      27, "步进增量",    W_INPUT_S, "sub_4434BC: *(_WORD *)(dword_9D0690 + 54)"),
    ("_reserved28",     28, "●保留28",     W_INPUT_S, "保留字段"),
    ("_reserved29",     29, "●保留29",     W_INPUT_S, "保留字段"),
    ("_reserved30",     30, "●保留30",     W_INPUT_S, "保留字段"),
    ("_reserved31",     31, "●保留31",     W_INPUT_S, "保留字段"),
    ("_reserved32",     32, "●保留32",     W_INPUT_S, "保留字段"),
    ("_reserved33",     33, "●保留33",     W_INPUT_S, "保留字段"),
    ("_reserved34",     34, "●保留34",     W_INPUT_S, "保留字段"),
    ("_reserved35",     35, "●保留35",     W_INPUT_S, "保留字段"),
    ("_reserved36",     36, "●保留36",     W_INPUT_S, "保留字段"),
    ("_reserved37",     37, "●保留37",     W_INPUT_S, "保留字段"),
    ("_reserved38",     38, "●保留38",     W_INPUT_S, "保留字段"),
    ("_reserved39",     39, "●保留39",     W_INPUT_S, "保留字段"),
]

# 区分编辑字段和运行时/保留字段
EDITABLE_FIELDS = [f for f in INST_FIELDS
                   if not f[0].startswith('_runtime') and not f[0].startswith('_reserved')]
DISPLAY_FIELDS = INST_FIELDS  # 全部显示


# ============================================================
# 数据加载/保存
# ============================================================

def load_act(fp):
    """加载 TKAct.dat (原始文件, 非 LZSS)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if len(raw) != ACT_DECOMPRESSED:
        raise ValueError(
            f"文件大小 {len(raw)} 不等于预期 {ACT_DECOMPRESSED} (650×784)")
    entries = []
    for i in range(ACT_ENTRY_COUNT):
        off = i * ACT_ENTRY_SIZE
        entry_data = raw[off:off + ACT_ENTRY_SIZE]

        # 解析头部 (80 字节 = 40 int16)
        header_vals = list(struct.unpack_from('<40h', entry_data, 0))

        # 解析前 4 组索引 (bytes 0-31, 每组 8 字节; 后 4 组在 header_vals[16-31])
        phases = []
        for p in range(4):
            p_off = p * 8
            slots = list(entry_data[p_off:p_off + 8])
            phases.append(slots)

        # 解析 8 个实例 (offset = slot * 80, slot=1..8)
        instances = []
        for s in range(1, ACT_MAX_INST + 1):
            inst_off = s * ACT_INST_SIZE
            inst_raw = entry_data[inst_off:inst_off + ACT_INST_SIZE]
            inst_vals = list(struct.unpack_from('<40h', inst_raw, 0))
            instances.append(inst_vals)

        # 尾部数据 (64 字节 = 32 int16, offset 720-783)
        tail_raw = entry_data[ACT_TAIL_OFFSET:ACT_TAIL_OFFSET + ACT_TAIL_SIZE]
        tail_vals = list(struct.unpack_from('<32h', tail_raw, 0))

        entries.append({
            'index': i,
            'header_vals': header_vals,
            'phases': phases,
            'instances': instances,
            'tail_vals': tail_vals,
            '_raw': entry_data,
        })
    return entries


def save_act(fp, entries):
    """保存 TKAct.dat (原始文件, 非 LZSS)"""
    buf = bytearray(ACT_ENTRY_COUNT * ACT_ENTRY_SIZE)
    for entry in entries:
        i = entry['index']
        off = i * ACT_ENTRY_SIZE

        # 打包头部 int16
        struct.pack_into('<40h', buf, off, *entry['header_vals'])

        # 打包索引组 (覆盖 bytes 0-31)
        for p in range(4):
            p_off = off + p * 8
            buf[p_off:p_off + 8] = bytes(entry['phases'][p])

        # 打包实例 (8 个, offset = s * 80)
        for s in range(ACT_MAX_INST):
            inst_off = off + (s + 1) * ACT_INST_SIZE
            struct.pack_into('<40h', buf, inst_off, *entry['instances'][s])

        # 打包尾部数据 (64 字节 = 32 int16)
        tail_off = off + ACT_TAIL_OFFSET
        struct.pack_into('<32h', buf, tail_off, *entry['tail_vals'])

    if len(buf) != ACT_DECOMPRESSED:
        raise RuntimeError(f"回写缓冲区大小异常: {len(buf)}")

    with open(fp, 'wb') as f:
        f.write(buf)
    return True


def entry_is_empty(entry):
    """检查条目是否完全为空"""
    for p in range(4):
        if any(entry['phases'][p]):
            return False
    for s in range(ACT_MAX_INST):
        if any(v != 0 for v in entry['instances'][s]):
            return False
    for v in entry['header_vals'][16:]:
        if v != 0:
            return False
    if any(v != 0 for v in entry.get('tail_vals', [])):
        return False
    return True


def entry_summary(entry):
    """生成条目的可读摘要"""
    # 收集使用的实例
    used = set()
    for p in range(4):
        for slot in entry['phases'][p]:
            if slot:
                used.add(slot)
    if used:
        return f"实例槽: {sorted(used)}"
    return "(空)"


# ============================================================
# GUI
# ============================================================

class ActEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKAct.dat 动画编辑器 v1.0")
        ico = os.path.join(os.path.dirname(__file__), '..', 'kon_editor', 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1280x820")
        self.root.minsize(1050, 650)
        self.act_path = None
        self.ani_path = None     # Ani.jvg 路径 (动画精灵)
        self.cha_path = None     # Cha.jvg 路径 (角色精灵)
        self.entries = []
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None
        self._jvg_data = None    # 加载的 JVG 数据
        self._jvg_cache = {}     # {(block_idx, frame_idx): PhotoImage} 按需渲染缓存
        self._preview_job = None
        self._preview_tick_idx = 0
        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1280) // 2
        y = (sh - 820) // 2
        self.root.geometry(f'1280x820+{x}+{y}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir,
                       accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="复制当前条目", command=self._copy_entry)
        em.add_command(label="清空当前条目", command=self._clear_entry)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=22)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        self.show_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="显示空槽", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(
            side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(
            value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned)
        paned.add(lf, weight=1)
        cols = ('index', 'summary', 'inst_count')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings',
                                 selectmode='browse')
        cc = [
            ('index', '条目#', 55),
            ('summary', '摘要', 180),
            ('inst_count', '实例数', 55),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn,
                              command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center'
                             if cid != 'summary' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('active', foreground='#228B22')
        self.tree.tag_configure('empty', foreground='#AAAAAA')

        # Right: Edit panel
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)
        self.edit_frame = rf

        # Scrollable edit area
        top_bar = ttk.Frame(rf)
        top_bar.pack(fill=tk.X)
        self.lbl_entry = ttk.Label(top_bar, text="未选中",
                                   font=('', 11, 'bold'))
        self.lbl_entry.pack(side=tk.LEFT, padx=4, pady=(0, 4))
        ttk.Button(top_bar, text="应用修改", command=self._apply_edit,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top_bar, text="重置", command=self._reset_edit,
                   width=6).pack(side=tk.RIGHT, padx=1)

        # Notebook for tabs
        self.nb = ttk.Notebook(rf)
        self.nb.pack(fill=tk.BOTH, expand=True)

        # Tab: Phase Reference
        self.phase_frame = ttk.Frame(self.nb)
        self.nb.add(self.phase_frame, text="索引组")

        # Tab: Instance Detail
        self.inst_notebook = ttk.Notebook(self.nb)
        self.nb.add(self.inst_notebook, text="实例详情")
        self._inst_frames = []
        self._inst_vars = []
        for s in range(1, ACT_MAX_INST + 1):
            sf = ttk.Frame(self.inst_notebook)
            self.inst_notebook.add(sf, text=f"实例{s}")
            self._inst_frames.append(sf)

        # Tab: Preview
        self.preview_frame = ttk.Frame(self.nb)
        self.nb.add(self.preview_frame, text="动画预览")

        # Tab: Tail Data
        self.tail_frame = ttk.Frame(self.nb)
        self.nb.add(self.tail_frame, text="尾部数据")

        # Tab: Raw Header Int16
        self.header_frame = ttk.Frame(self.nb)
        self.nb.add(self.header_frame, text="头部 int16")

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_jvg = ttk.Label(pf, text="", foreground="gray")
        self.lbl_jvg.pack(side=tk.LEFT, padx=10, pady=2)

        # Build phase reference UI
        self._build_phase_ui()
        # Build instance UIs
        self._build_instance_uis()
        # Build header UI
        self._build_header_ui()
        # Build preview
        self._build_preview_ui()
        # Build tail data UI
        self._build_tail_ui()

    def _build_phase_ui(self):
        """构建索引组编辑 UI"""
        main = ttk.Frame(self.phase_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="索引组 → 实例槽位引用 (来自 sub_4434BC: v22[8*v33])",
                  font=FONT_S, foreground='#666').pack(anchor=tk.W, pady=(0, 5))

        self._phase_vars = []
        for p in range(4):
            pf = ttk.LabelFrame(main, text=f"{GROUP_LABELS[p]} (byte offset {p*8})", padding=4)
            pf.pack(fill=tk.X, pady=2)

            row = ttk.Frame(pf)
            row.pack(fill=tk.X)
            p_vars = []
            for s in range(4):
                ttk.Label(row, text=f"[{s}]:", font=FONT_S).pack(side=tk.LEFT)
                sv = tk.StringVar()
                ent = ttk.Entry(row, textvariable=sv, width=4, font=FONT)
                ent.pack(side=tk.LEFT, padx=(0, 6))
                # Tooltip
                self._bind_tooltip(ent,
                    f"组{p} 字节{s}\n"
                    f"0=空, 1-8=实例槽位号\n"
                    f"运行时: &unk_9D037A + 80×此值")
                p_vars.append(sv)
            self._phase_vars.append(p_vars)

        # Legend
        ttk.Label(main, text="值: 0=空 | 1-8=对应槽位 (实例槽位偏移 = 值 × 80 字节)",
                  font=FONT_S, foreground='#888').pack(anchor=tk.W, pady=(5, 0))

    def _build_instance_uis(self):
        """构建 9 个实例标签页的编辑 UI"""
        self._inst_vars = []
        for s in range(1, ACT_MAX_INST + 1):
            sf = self._inst_frames[s - 1]

            # Scrollable canvas
            canvas = tk.Canvas(sf, highlightthickness=0)
            scrollbar = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=canvas.yview)
            inner = ttk.Frame(canvas)

            inner.bind('<Configure>',
                       lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
            canvas.create_window((0, 0), window=inner, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Bind mousewheel
            def _mw(e, c=canvas):
                c.yview_scroll(int(-1 * (e.delta / 120)), "units")

            def _enter(e, c=canvas):
                c.bind_all("<MouseWheel>", _mw)

            def _leave(e, c=canvas):
                c.unbind_all("<MouseWheel>")

            canvas.bind("<Enter>", _enter)
            canvas.bind("<Leave>", _leave)

            # Build field rows
            vars_row = {}
            type_var = tk.StringVar()
            vars_row['inst_type'] = type_var

            # Type selector at top
            type_frame = ttk.Frame(inner, padding=3)
            type_frame.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
            ttk.Label(type_frame, text="类型:", font=FONT).pack(side=tk.LEFT)
            type_combo = ttk.Combobox(type_frame, textvariable=type_var,
                                      values=list(INST_TYPES.values()),
                                      width=12, state='readonly', font=FONT)
            type_combo.pack(side=tk.LEFT, padx=4)
            type_combo.bind('<<ComboboxSelected>>',
                            lambda e, v=type_var, t=INST_TYPES:
                            self._on_type_select(v, t))
            ttk.Label(type_frame, text="(sub_4434BC: == 1/4/5 分支)",
                      font=FONT_S, foreground='#888').pack(side=tk.LEFT, padx=5)
            vars_row['_type_combo'] = type_combo

            # All editable fields
            for fi, (fn, idx, label, width, comment) in enumerate(INST_FIELDS):
                if fn == 'inst_type':
                    continue  # already handled above

                row_idx = 1 + fi // 3
                col_idx = fi % 3
                frm = ttk.Frame(inner)
                frm.grid(row=row_idx, column=col_idx, sticky='nw', padx=2,
                         pady=1)
                inner.columnconfigure(col_idx, weight=1)

                is_runtime = fn.startswith('_runtime') or fn.startswith('_reserved')
                lbl = ttk.Label(frm, text=label, font=FONT_S)
                if is_runtime:
                    lbl.configure(foreground='#AAA')
                lbl.pack(anchor=tk.W)
                self._bind_tooltip(lbl, f"[int16 {idx}] {comment}")

                sv = tk.StringVar()
                vars_row[fn] = sv
                ent = ttk.Entry(frm, textvariable=sv, width=width, font=FONT)
                if is_runtime:
                    ent.configure(state='readonly', foreground='#AAA')
                ent.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self._inst_vars.append(vars_row)

    def _build_header_ui(self):
        """构建头部 int16 原始值 UI"""
        main = ttk.Frame(self.header_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="头部 80 字节 = 40 int16 (bytes 0-63 为索引组, bytes 64-79 为参数)",
                  font=FONT_S, foreground='#666').pack(anchor=tk.W, pady=(0, 5))

        canvas = tk.Canvas(main, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>',
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._header_vars = []
        # Phase reference area (int16[0-15])
        ttk.Label(inner, text="索引组区 (int16[0-15], bytes 0-31)",
                  font=('', 9, 'bold')).grid(row=0, column=0, columnspan=4,
                                             sticky='w', pady=(2, 5))
        for idx in range(16):
            row = 1 + idx // 4
            col = idx % 4
            frm = ttk.Frame(inner)
            frm.grid(row=row, column=col, sticky='nw', padx=2, pady=1)
            label = f"[{idx:2d}]"
            if idx % 4 == 0:
                label += f" P{idx//4}"
            ttk.Label(frm, text=label, font=FONT_S, foreground='#888').pack(
                anchor=tk.W)
            sv = tk.StringVar()
            ent = ttk.Entry(frm, textvariable=sv, width=8, font=FONT)
            ent.pack(side=tk.LEFT)
            self._bind_tooltip(ent,
                f"int16[{idx}] = bytes {idx*2}-{idx*2+1}")
            self._header_vars.append(sv)

        # Parameter area (int16[16-39])
        ttk.Label(inner, text="参数区 (int16[16-39], bytes 32-79)",
                  font=('', 9, 'bold')).grid(row=6, column=0, columnspan=4,
                                             sticky='w', pady=(10, 5))
        for idx in range(16, 40):
            row = 7 + (idx - 16) // 4
            col = (idx - 16) % 4
            frm = ttk.Frame(inner)
            frm.grid(row=row, column=col, sticky='nw', padx=2, pady=1)
            ttk.Label(frm, text=f"[{idx:2d}]", font=FONT_S,
                      foreground='#888').pack(anchor=tk.W)
            sv = tk.StringVar()
            ent = ttk.Entry(frm, textvariable=sv, width=8, font=FONT)
            ent.pack(side=tk.LEFT)
            self._bind_tooltip(ent,
                f"int16[{idx}] = bytes {idx*2}-{idx*2+1}")
            self._header_vars.append(sv)

    def _build_preview_ui(self):
        """构建动画预览 UI — 实例可见性开关 + 叠加渲染"""
        main = ttk.Frame(self.preview_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        # 控制栏
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(ctrl, text="方向:", font=FONT_S).pack(side=tk.LEFT)
        self._preview_dir_var = tk.IntVar(value=0)
        for d in range(4):
            ttk.Radiobutton(ctrl, text=str(d), variable=self._preview_dir_var,
                            value=d, command=self._preview_redraw,
                            width=2).pack(side=tk.LEFT)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(ctrl, text="速度(ms):", font=FONT_S).pack(side=tk.LEFT)
        self._preview_speed = tk.IntVar(value=120)
        ttk.Spinbox(ctrl, textvariable=self._preview_speed,
                    from_=30, to=500, increment=10, width=5,
                    font=FONT).pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl, text="▶", command=self._preview_play,
                   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="⏸", command=self._preview_stop,
                   width=3).pack(side=tk.LEFT, padx=1)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)

        # 实例可见性开关 (动态填充)
        self._preview_vis_frame = ttk.Frame(ctrl)
        self._preview_vis_frame.pack(side=tk.LEFT, fill=tk.X)
        self._preview_vis_vars = {}   # {slot: BooleanVar}
        self._preview_vis_cbs = {}    # {slot: Checkbutton}

        # 画布
        self._preview_canvas = tk.Canvas(main, bg='#1a1a2e',
                                         highlightthickness=0)
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas.bind('<Configure>',
                                  lambda e: self._preview_redraw())

        if not HAS_PIL:
            self._preview_canvas.create_text(
                200, 100, text="需要 Pillow 库:\npip install Pillow",
                fill="#888", font=("", 11))

    def _build_tail_ui(self):
        """构建尾部数据 UI (bytes 720-783, 32 int16)"""
        main = ttk.Frame(self.tail_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="尾部数据 (offset 720-783, 32 int16) — 未在 sub_4434BC 中直接引用",
                  font=FONT_S, foreground='#666').pack(anchor=tk.W, pady=(0, 5))

        canvas = tk.Canvas(main, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>',
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._tail_vars = []
        for idx in range(32):
            row = idx // 8
            col = idx % 8
            frm = ttk.Frame(inner)
            frm.grid(row=row, column=col, sticky='nw', padx=2, pady=1)
            ttk.Label(frm, text=f"[{idx:2d}]", font=FONT_S,
                      foreground='#888').pack(anchor=tk.W)
            sv = tk.StringVar()
            ent = ttk.Entry(frm, textvariable=sv, width=7, font=FONT)
            ent.pack(side=tk.LEFT)
            self._bind_tooltip(ent,
                f"tail int16[{idx}] = bytes 720+{idx*2}")
            self._tail_vars.append(sv)

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
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid',
                      borderwidth=1, font=FONT_S, wraplength=420,
                      padding=3).pack()
            tip['win'] = w

        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None

        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _on_type_select(self, var, type_map):
        """类型下拉框选择时更新显示"""
        val = var.get()
        for k, v in type_map.items():
            if v == val:
                var.set(str(k))
                break

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children():
            self._set_ws(c, en)
        for tab_id in self.nb.tabs():
            tab = self.nb.nametowidget(tab_id)
            for c in tab.winfo_children():
                self._set_ws(c, en)

    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, (ttk.Combobox)):
                w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except:
            pass
        for c in w.winfo_children():
            self._set_ws(c, en)

    # ----------- 动画预览 -----------

    def _preview_active_instances(self, direction):
        """获取指定方向下的活跃实例列表

        sub_4434BC: flag==4 或 type<3 → 有效方向=当前方向, 否则固定方向0
        返回: [(slot, eff_dir, inst_data), ...]
        """
        entry = self.entries[self._editing_idx]
        phases = entry['phases']
        slot_order = [s for s in phases[direction % 4] if s]
        if not slot_order:
            slot_order = [s for s in range(1, ACT_MAX_INST + 1)
                         if entry['instances'][s - 1][0] != 0]
        result = []
        for slot in slot_order:
            inst = entry['instances'][slot - 1]
            if inst[0] == 0:
                continue
            eff_dir = direction if (inst[2] == 4 or inst[0] < 3) else 0
            result.append((slot, eff_dir, inst))
        return result

    def _preview_load_jvg(self):
        """加载 JVG 文件 (仅解析, 不预渲染帧)"""
        if not HAS_PIL:
            return False
        jvg_mod = _get_jvg_loader()
        if not jvg_mod:
            return False
        jvg_path = self.ani_path or self.cha_path
        if not jvg_path or not os.path.exists(jvg_path):
            return False
        try:
            self._jvg_data = jvg_mod.load_jvg(jvg_path)
            self._jvg_cache.clear()
            return True
        except Exception as e:
            return False

    def _preview_get_frame(self, block_idx, frame_idx):
        """按需渲染单个 JVG 帧 → PhotoImage (带缓存)"""
        key = (block_idx, frame_idx)
        if key in self._jvg_cache:
            return self._jvg_cache[key]
        jvg = self._jvg_data
        if block_idx >= len(jvg.blocks):
            return None
        blk = jvg.blocks[block_idx]
        if frame_idx >= blk.frame_count:
            return None
        f = blk.frames[frame_idx]
        if f.width <= 0 or f.height <= 0:
            return None
        pal_rgb = blk.palette.to_rgb888()
        rgba = bytearray(f.width * f.height * 4)
        for py in range(f.height):
            for px in range(f.width):
                p = py * f.width + px
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                off = p * 4
                rgba[off] = pal_rgb[idx * 3]
                rgba[off + 1] = pal_rgb[idx * 3 + 1]
                rgba[off + 2] = pal_rgb[idx * 3 + 2]
                rgba[off + 3] = 255
        try:
            img = Image.frombytes('RGBA', (f.width, f.height), bytes(rgba))
            tk_img = ImageTk.PhotoImage(img)
            self._jvg_cache[key] = tk_img
            return tk_img
        except Exception:
            return None

    def _preview_reload(self):
        """条目切换时: 建可见性开关, 清缓存, 重绘"""
        self._preview_stop()
        if self._editing_idx is None:
            return
        if not self._jvg_data:
            if not self._preview_load_jvg():
                return
        self._jvg_cache.clear()
        self._preview_tick_idx = 0
        self._preview_update_vis()
        self._preview_redraw()

    def _preview_update_vis(self):
        """重建实例可见性复选框 (基于当前条目的活跃实例)"""
        for w in self._preview_vis_frame.winfo_children():
            w.destroy()
        self._preview_vis_vars.clear()
        self._preview_vis_cbs.clear()

        entry = self.entries[self._editing_idx]
        # 收集所有方向中用到的实例
        all_slots = set()
        for d in range(4):
            for s in entry['phases'][d]:
                if s:
                    all_slots.add(s)
        if not all_slots:
            for s in range(1, ACT_MAX_INST + 1):
                if entry['instances'][s - 1][0] != 0:
                    all_slots.add(s)

        # 默认只显示第一个实例, 其余需手动勾选
        first = True
        for slot in sorted(all_slots):
            inst = entry['instances'][slot - 1]
            type_name = INST_TYPES.get(inst[0], str(inst[0]))[:2]
            label = f"#{slot}({type_name})"
            var = tk.BooleanVar(value=first)
            first = False
            cb = ttk.Checkbutton(self._preview_vis_frame, text=label,
                                 variable=var, command=self._preview_redraw)
            cb.pack(side=tk.LEFT, padx=1)
            self._preview_vis_vars[slot] = var
            self._preview_vis_cbs[slot] = cb

    def _preview_play(self):
        if self._editing_idx is None:
            return
        if not self._jvg_data:
            if not self._preview_load_jvg():
                return
        self._preview_stop()
        self._preview_tick_idx = 0
        self._preview_tick()

    def _preview_stop(self):
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None

    def _preview_tick(self):
        self._preview_tick_idx += 1
        self._preview_redraw()
        speed = max(30, self._preview_speed.get())
        self._preview_job = self.root.after(speed, self._preview_tick)

    def _preview_redraw(self):
        """重绘画布 — 可见实例叠加, 按 sub_4544EC 偏移逻辑"""
        c = self._preview_canvas
        c.delete("all")

        if not self._jvg_data or self._editing_idx is None:
            c.create_text(200, 100, text="未加载 JVG\n请先加载 TKS 目录",
                          fill="#888", font=("", 11))
            return

        direction = self._preview_dir_var.get()
        active = self._preview_active_instances(direction)
        if not active:
            c.create_text(200, 100, text=f"方向{direction}: 无活跃实例",
                          fill="#888", font=("", 11))
            return

        jvg = self._jvg_data
        tick = self._preview_tick_idx

        # ── 第一遍: 收集可见实例的包围盒 ──
        sprites = []
        all_x, all_y = [], []

        for slot, eff_dir, inst in active:
            # 可见性检查
            if slot in self._preview_vis_vars and not self._preview_vis_vars[slot].get():
                continue
            pk = inst[1]
            if pk < 0 or pk >= len(jvg.blocks):
                continue
            blk = jvg.blocks[pk]
            n_frames = blk.frame_count
            if n_frames <= 0:
                continue

            cur_frame = tick % n_frames
            jvg_f = blk.frames[cur_frame]
            inst_x = inst[3 + eff_dir]
            inst_y = inst[7 + eff_dir]

            spr_l = jvg_f.x_off + inst_x
            spr_t = jvg_f.y_off + inst_y
            spr_r = jvg_f.x_off + jvg_f.width - 1 + inst_x
            spr_b = jvg_f.y_off + jvg_f.height - 1 + inst_y

            all_x.extend([spr_l, spr_r, -inst_x])
            all_y.extend([spr_t, spr_b, -inst_y])
            sprites.append((slot, eff_dir, inst, blk, cur_frame, jvg_f,
                           inst_x, inst_y, spr_l, spr_t, spr_r, spr_b))

        if not sprites:
            c.create_text(200, 100,
                          text=f"方向{direction}: 无可渲染帧\n(检查实例可见性开关)",
                          fill="#888", font=("", 11))
            return

        bbox_l = min(all_x)
        bbox_r = max(all_x)
        bbox_t = min(all_y)
        bbox_b = max(all_y)

        # ── 缩放到画布 ──
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return
        margin = 40
        sx = (cw - margin * 2) / max(bbox_r - bbox_l, 1)
        sy = (ch - margin * 2) / max(bbox_b - bbox_t, 1)
        scale = min(sx, sy, 3.0)

        def to_cv(gx, gy):
            return (margin + (gx - bbox_l) * scale,
                    margin + (gy - bbox_t) * scale)

        # ── 原点标记 ──
        ox, oy = to_cv(0, 0)
        c.create_line(ox - 16, oy, ox + 16, oy, fill='#00ff00', width=2)
        c.create_line(ox, oy - 16, ox, oy + 16, fill='#00ff00', width=2)
        c.create_text(ox + 18, oy + 4, text="原点(0,0)", fill='#0f0',
                      font=("Consolas", 7), anchor=tk.NW)

        # ── 渲染精灵 ──
        scaled_cache = []
        slot_colors = ['#4488ff', '#ff8844', '#44ff88', '#ff44ff',
                       '#ffff44', '#44ffff', '#ff8888', '#88ff88']
        info_lines = [f"方向{direction} | 可见{len(sprites)}实例 | Tick:{tick}"]

        for sp in sprites:
            (slot, eff_dir, inst, blk, cur_frame, jvg_f,
             inst_x, inst_y, spr_l, spr_t, spr_r, spr_b) = sp

            pk = inst[1]
            img = self._preview_get_frame(pk, cur_frame)
            if not img:
                continue

            cx, cy = to_cv(spr_l, spr_t)
            nw = max(1, int(jvg_f.width * scale))
            nh = max(1, int(jvg_f.height * scale))
            color = slot_colors[(slot - 1) % len(slot_colors)]

            if nw == jvg_f.width and nh == jvg_f.height:
                c.create_image(cx, cy, image=img, anchor=tk.NW)
            else:
                # 需要缩放: 从缓存取原图 resize
                try:
                    # PIL resize from the cached raw pixels
                    pal_rgb = blk.palette.to_rgb888()
                    rgba = bytearray(jvg_f.width * jvg_f.height * 4)
                    for py in range(jvg_f.height):
                        for px in range(jvg_f.width):
                            p = py * jvg_f.width + px
                            if p < len(jvg_f.alpha) and jvg_f.alpha[p] == 0:
                                continue
                            idx = jvg_f.pixels[p] if p < len(jvg_f.pixels) else 0
                            off = p * 4
                            rgba[off] = pal_rgb[idx * 3]
                            rgba[off + 1] = pal_rgb[idx * 3 + 1]
                            rgba[off + 2] = pal_rgb[idx * 3 + 2]
                            rgba[off + 3] = 255
                    pil_img = Image.frombytes('RGBA', (jvg_f.width, jvg_f.height),
                                              bytes(rgba))
                    pil_img = pil_img.resize((nw, nh), Image.NEAREST)
                    scaled_tk = ImageTk.PhotoImage(pil_img)
                    scaled_cache.append(scaled_tk)
                    c.create_image(cx, cy, image=scaled_tk, anchor=tk.NW)
                except Exception:
                    c.create_image(cx, cy, image=img, anchor=tk.NW)

            # 边框 + 锚点
            rx, ry = to_cv(spr_r, spr_b)
            c.create_rectangle(cx, cy, rx + 1, ry + 1, outline=color, width=1)
            ax, ay = to_cv(jvg_f.x_off + jvg_f.width - 1 + inst_x,
                          jvg_f.y_off + jvg_f.height - 1 + inst_y)
            c.create_oval(ax - 2, ay - 2, ax + 2, ay + 2,
                         outline=color, fill=color)
            c.create_text(cx + 2, cy + 2,
                         text=f"#{slot}", fill=color,
                         font=("Consolas", 6), anchor=tk.NW)

            info_lines.append(
                f"  #{slot} pk={pk} t={inst[0]} dir={eff_dir} "
                f"f={cur_frame+1}/{blk.frame_count} ({inst_x:+d},{inst_y:+d})")

        self._preview_scaled_cache = scaled_cache

        # ── 信息面板 ──
        for li, line in enumerate(info_lines[:14]):
            c.create_text(8, 8 + li * 16, text=line, fill="#0f0",
                          font=("Consolas", 8), anchor=tk.NW)

    def _on_close(self):
        self._preview_stop()
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return
        act = os.path.join(d, "TKAct.dat")
        ani = os.path.join(d, "Ani.jvg")
        cha = os.path.join(d, "Cha.jvg")
        if not os.path.exists(act):
            messagebox.showwarning("文件缺失", "未找到 TKAct.dat")
            return
        self.act_path = act
        self.ani_path = ani if os.path.exists(ani) else None
        self.cha_path = cha if os.path.exists(cha) else None
        self._reload()

    def _reload(self):
        if not self.act_path:
            return
        self._preview_stop()
        self._jvg_data = None
        self._jvg_cache.clear()
        self.status_var.set("加载中…")
        self.root.update()
        try:
            self.entries = load_act(self.act_path)
            self._dirty = False
            nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
            self.status_var.set(
                f"{len(self.entries)} 条 (784 字节/条) | 非空 {nonempty}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            self.entries = []
        self._set_edit_enabled(True)
        self._update_path()
        self._apply_filter()

    def _update_path(self):
        g, r = "#228B22", "#CC3333"
        if not self.act_path:
            self.lbl_path.config(text="TKAct: (未加载)", foreground=r)
        elif not os.path.exists(self.act_path):
            self.lbl_path.config(text=f"TKAct: (不存在){self.act_path}", foreground=r)
        else:
            self.lbl_path.config(text=f"TKAct: {self.act_path}", foreground=g)

        jvg_path = self.ani_path or self.cha_path
        if not jvg_path:
            self.lbl_jvg.config(text="JVG: (未找到)", foreground=r)
        elif not os.path.exists(jvg_path):
            self.lbl_jvg.config(text=f"JVG: (不存在){jvg_path}", foreground=r)
        else:
            self.lbl_jvg.config(text=f"JVG: {jvg_path}", foreground=g)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower()
        self.filtered_indices = []
        for entry in self.entries:
            if not self.show_empty.get() and entry_is_empty(entry):
                continue
            if q:
                summary = entry_summary(entry)
                search_text = f"{entry['index']} {summary} " \
                              f"{' '.join(str(v) for v in entry['header_vals'][:16])}".lower()
                if q not in search_text:
                    continue
            self.filtered_indices.append(entry['index'])
        self._refresh_table()
        nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
        msg = f"显示 {len(self.filtered_indices)}/{ACT_ENTRY_COUNT} (非空 {nonempty}) | Ctrl+S 保存"
        if self._dirty:
            msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set("")
        self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        for idx in self.filtered_indices:
            entry = self.entries[idx]
            summary = entry_summary(entry)
            used_count = 0
            for p in range(4):
                used_count += sum(1 for s in entry['phases'][p] if s)
            has_data = not entry_is_empty(entry)
            tags = ['active'] if has_data else ['empty']
            self.tree.insert('', 'end',
                             values=(entry['index'], summary, used_count),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'summary':
            self.filtered_indices.sort(
                key=lambda i: entry_summary(self.entries[i]).lower(),
                reverse=rev)
        elif col == 'inst_count':
            self.filtered_indices.sort(
                key=lambda i: sum(
                    1 for p in range(4) for s in self.entries[i]['phases'][p]
                    if s),
                reverse=rev)
        else:
            self.filtered_indices.sort(reverse=rev)
        self._sort_reverse = not rev
        self._refresh_table()

    # ----------- 编辑 -----------

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.entries[idx])

    def _populate_edit(self, entry):
        self._editing_idx = entry['index']

        # 更新标签
        used_slots = set()
        for p in range(4):
            for slot in entry['phases'][p]:
                if slot:
                    used_slots.add(slot)
        self.lbl_entry.config(
            text=f"动画 #{entry['index']}    "
                 f"使用实例: {sorted(used_slots) if used_slots else '(空)'}")

        # 填充索引组
        for p in range(4):
            for s in range(4):
                self._phase_vars[p][s].set(str(entry['phases'][p][s]))

        # 填充实例数据
        for inst_idx in range(ACT_MAX_INST):
            inst_vals = entry['instances'][inst_idx]
            vars_row = self._inst_vars[inst_idx]

            # Type combo
            type_val = inst_vals[0]
            type_name = INST_TYPES.get(type_val, f"未知({type_val})")
            if '_type_combo' in vars_row:
                vars_row['_type_combo'].set(type_name)
            vars_row['inst_type'].set(str(type_val))

            # Other fields
            for fn, idx, label, width, comment in INST_FIELDS:
                if fn == 'inst_type':
                    continue
                if fn in vars_row:
                    vars_row[fn].set(str(inst_vals[idx]))

        # 填充头部 int16
        for idx in range(40):
            self._header_vars[idx].set(str(entry['header_vals'][idx]))

        # 填充尾部数据
        for idx in range(32):
            self._tail_vars[idx].set(str(entry['tail_vals'][idx]))

        # 触发预览重载
        self._preview_reload()

    def _apply_edit(self):
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]

        # 读取索引组
        for p in range(4):
            for s in range(4):
                try:
                    v = int(self._phase_vars[p][s].get() or 0)
                    if v < 0:
                        v = 0
                    if v > 255:
                        v = 255
                    entry['phases'][p][s] = v
                except ValueError:
                    entry['phases'][p][s] = 0

        # 读取实例数据
        for inst_idx in range(ACT_MAX_INST):
            inst_vals = entry['instances'][inst_idx]
            vars_row = self._inst_vars[inst_idx]

            # Type
            try:
                inst_vals[0] = int(vars_row['inst_type'].get() or 0)
            except ValueError:
                inst_vals[0] = 0

            # Other fields
            for fn, idx, label, width, comment in INST_FIELDS:
                if fn == 'inst_type':
                    continue
                if fn in vars_row:
                    try:
                        v = int(vars_row[fn].get() or 0)
                        if v > 32767:
                            v = 32767
                        if v < -32768:
                            v = -32768
                        inst_vals[idx] = v
                    except ValueError:
                        inst_vals[idx] = 0

        # 同步头部 int16 (仅 bytes 32-79 参数区; bytes 0-31 由索引组自动覆盖)
        for idx in range(16, 40):
            try:
                entry['header_vals'][idx] = int(
                    self._header_vars[idx].get() or 0)
            except ValueError:
                entry['header_vals'][idx] = 0

        # 将索引组同步到 header_vals[0-15]
        for p in range(4):
            p_off = p * 4
            raw_bytes = bytes(entry['phases'][p])
            entry['header_vals'][p_off] = struct.unpack_from(
                '<h', raw_bytes, 0)[0]
            entry['header_vals'][p_off + 1] = struct.unpack_from(
                '<h', raw_bytes, 2)[0]
            entry['header_vals'][p_off + 2] = struct.unpack_from(
                '<h', raw_bytes, 4)[0]
            entry['header_vals'][p_off + 3] = struct.unpack_from(
                '<h', raw_bytes, 6)[0]

        # 读取尾部数据
        for idx in range(32):
            try:
                entry['tail_vals'][idx] = int(self._tail_vars[idx].get() or 0)
            except ValueError:
                entry['tail_vals'][idx] = 0

        self._dirty = True
        self._apply_filter()
        # 保持选中
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == entry['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self.status_var.set(
            f"动画 #{entry['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.entries[self._editing_idx])

    def _copy_entry(self):
        if self._editing_idx is None:
            return
        src = self.entries[self._editing_idx]
        if entry_is_empty(src):
            messagebox.showinfo("提示", "当前条目为空, 无需复制")
            return
        for entry in self.entries:
            if entry_is_empty(entry):
                idx_bak = entry['index']
                entry['phases'] = [list(p) for p in src['phases']]
                entry['instances'] = [list(i) for i in src['instances']]
                entry['header_vals'] = list(src['header_vals'])
                entry['tail_vals'] = list(src['tail_vals'])
                entry['index'] = idx_bak
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == idx_bak:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self._populate_edit(entry)
                self.status_var.set(
                    f"已复制 #{src['index']} → #{idx_bak}")
                return
        messagebox.showwarning("槽位已满",
                               f"所有 {ACT_ENTRY_COUNT} 个槽位均已占用")

    def _clear_entry(self):
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        if entry_is_empty(entry):
            messagebox.showinfo("提示", "当前条目已经为空")
            return
        if not messagebox.askyesno("确认清空",
                                   f"确定清空动画 #{entry['index']}?"):
            return
        idx_save = entry['index']
        # Reset all
        self.entries[idx_save] = {
            'index': idx_save,
            'header_vals': [0] * 40,
            'phases': [[0] * 8 for _ in range(4)],
            'instances': [[0] * 40 for _ in range(ACT_MAX_INST)],
            'tail_vals': [0] * 32,
            '_raw': bytearray(ACT_ENTRY_SIZE),
        }
        self._dirty = True
        self._apply_filter()
        self._populate_edit(self.entries[idx_save])
        self.status_var.set(f"已清空动画 #{idx_save}")

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.act_path or not self.entries:
            messagebox.showinfo("提示", "请先加载数据")
            return
        if not messagebox.askyesno("确认保存",
                                   f"保存 {len(self.entries)} 条到:\n"
                                   f"{self.act_path}\n\n"
                                   f"原文件将被覆盖 (生成 .bak)."):
            return
        # 备份
        try:
            with open(self.act_path, 'rb') as s:
                with open(self.act_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except:
            pass
        try:
            self.status_var.set("正在保存…")
            self.root.update()
            save_act(self.act_path, self.entries)
            self._dirty = False
            self.status_var.set(f"已保存 → {self.act_path}")
            messagebox.showinfo("保存成功",
                                f"已保存\n备份: {self.act_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.entries:
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        with open(p, 'w', encoding='utf-8-sig') as f:
            # Header
            cols = ['条目索引', '索引组摘要']
            for s in range(1, ACT_MAX_INST + 1):
                cols.append(f"实例{s}_类型")
                cols += [f"实例{s}_{fn}" for fn, _, _, _, _ in INST_FIELDS
                         if fn != 'inst_type']
            f.write(','.join(cols) + '\n')

            for entry in self.entries:
                if entry_is_empty(entry):
                    continue
                row = [str(entry['index']), entry_summary(entry)]
                for s in range(ACT_MAX_INST):
                    inst = entry['instances'][s]
                    row.append(str(inst[0]))
                    for fn, idx, _, _, _ in INST_FIELDS:
                        if fn != 'inst_type':
                            row.append(str(inst[idx]))
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = ["TKAct.dat 字段映射 v1.0 (基于反编译)", ""]
        lines.append(f"【文件结构】{ACT_ENTRY_COUNT} 条 × "
                     f"{ACT_ENTRY_SIZE} 字节 = {ACT_DECOMPRESSED} 字节")
        lines.append("  每动画条目 = 1 头部(80字节) + 9 实例槽位(各80字节)")
        lines.append("")
        lines.append("【反编译函数引用】")
        lines.append("  sub_411624: sub_452544(aTkactDat, &unk_9539CA, 509600)")
        lines.append("  sub_452544: 原始文件读取 (非 LZSS)")
        lines.append("  sub_4434BC: 动画运行时处理")
        lines.append("    qmemcpy(&unk_9D037A, 784*sprite_idx+9779658, 0x310)")
        lines.append("    v44 = v22[8*v33+i]; dword_9D0690 = &unk_9D037A + 80*v44")
        lines.append("")
        lines.append("【实例字段 (各80字节, 40 int16)】")
        for fn, idx, label, width, comment in INST_FIELDS:
            marker = ""
            if fn.startswith('_runtime'):
                marker = " [运行时]"
            elif fn.startswith('_reserved'):
                marker = " [保留]"
            lines.append(f"  [{idx:2d}] {label:<10s}{marker}")
            lines.append(f"       {comment}")
        lines.append("")
        lines.append("【索引组 (头部 bytes 0-31)】")
        lines.append("  8 组 × 8 字节索引表 = 32 字节")
        lines.append("  每字节值为 1-based 实例槽位号 (0=空)")
        lines.append("  sub_4434BC 运行时: v22[8*v33] 按偏移选择组")

        dlg = tk.Toplevel(self.root)
        dlg.title("字段参考 (反编译来源)")
        dlg.geometry("680x560")
        dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines))
        tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
                            "TKAct.dat 动画编辑器 v1.0\n\n"
                            "基于《三国群侠传》 TKS.exe 反编译\n"
                            "650 条目 × 784 字节 = 509,600 字节\n\n"
                            "逆向来源:\n"
                            "  sub_411624  动画系统初始化\n"
                            "  sub_452544  TKAct.dat 加载 (原始读取)\n"
                            "  sub_4434BC  动画运行时处理\n"
                            "  sub_45408C  动画值计算\n"
                            "  sub_45410C  动画上下文查表")


def main():
    root = tk.Tk()
    ActEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
