#!/usr/bin/env python3
"""
TKAct.dat 多图层 2D 精灵动画编辑器 v2.0
=============================================================
修订依据 (AI 分析记录: 逆向工作区/TKS_AI分析act_editor记录.md)
  旧版 v1.0 问题：
    - 把"4 方向绘制顺序"误称为"8 个索引组"
    - 把"主角/特效/交互图层"混称"实例槽位"并 8 个平级展示
    - 把可编辑字段 tick_interval / start_delay 误标为"运行时只读"
    - 用 effect_type / flag / extra_mult 等抽象名掩盖真实语义
  v2.0 修正要点 (每条均有 sub_4434BC 行号级证据, 见文末注释):
    1. 前 32 字节 = 4 方向 × 8 字节 的图层绘制顺序 (z-order)
    2. 8 个槽位即 8 个图层 (layer), 按语义分组编辑
    3. 字段按语义命名并按功能分组 (来源/帧范围/时序/渲染/位移/…)
    4. 尾部 64B 按 16 对 (value, count) 显示
    5. 预览节拍遵循 tick_interval / start_delay / [first,last] 语义

文件结构 (784 字节/条, 共 650 条 = 509,600 字节):
  [0-31]    方向表: 4 方向 × 8 字节, 每字节为 1-based 图层号 (0=空)
  [32-79]   条目级参数区 (24 int16, 多数预留/未知)
  [80-719]  图层 × 8 (各 80 字节 = 40 int16)
  [720-783] 尾部 (32 int16 = 16 对 value/count, 未在 sub_4434BC 中引用)

逆向关键函数:
  sub_411624: sub_452544(aTkactDat, &unk_9539CA, 509600)  初始化载入
  sub_452544: 原始 I/O 读取 (非 LZSS)
  sub_4434BC: 动画运行时处理 (本编辑器语义的主要证据来源)
  sub_45408C: 帧基址计算
  sub_45410C: param_key 查表
"""

import os, sys, struct, tkinter as tk
from tkinter import ttk, messagebox, filedialog

HAS_PIL = False
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass

# ------------------------------------------------------------
# JVG 加载 (从 jvg_editor 导入)
# ------------------------------------------------------------
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
# 常量
# ============================================================

ACT_ENTRY_SIZE = 784
ACT_ENTRY_COUNT = 650
ACT_LAYER_SIZE = 80            # 每图层 80 字节 = 40 int16
ACT_MAX_LAYER = 8              # 方向表字节值域 1..8
ACT_HEADER_SIZE = 80
ACT_PARAM_OFFSET = 32          # 条目级参数区起点
ACT_TAIL_OFFSET = 720
ACT_TAIL_SIZE = 64
ACT_DECOMPRESSED = 509600

# 方向顺序 — sub_4434BC 以字节下标 v33 ∈ [0,3] 索引方向组;
# 实测 entry #0 的 4 组 z-order 呈 "前/后朝向反转" 模式,
# 下/右使用 [3,4,1,2], 上/左使用 [1,2,3,4], 故与常见 RPG 四方向一致:
DIRECTION_LABELS = ["方向0 (下)", "方向1 (上)", "方向2 (左)", "方向3 (右)"]

# 图层类型 (sub_4434BC: *(_WORD*)dword_9D0690)
#   引擎只按 "==1 vs !=1" 切换贴图源 (Cha.jvg / Ani.jvg)
#   type <  3 : 主渲染段 (L305)  —— 角色/物件/特效均可
#   type == 3 : 延迟渲染段 (L402) —— 独立于 a1 自身的精灵, 常用于场景对象
#   type == 4 : 坐标锚点 (sub_42F9C8), 不渲染
#   type == 5 : 结束标记 (v28=1), 不渲染
# ⚠ 注意: 该字段本质是 "贴图源 + 渲染阶段" 的组合标识,
#   并不区分 "主角 / NPC / 特效 / 物品" —— 这些归属完全由 jvg_block_index 所指的精灵内容决定
LAYER_TYPE_LABELS = {
    0: "0 空",
    1: "1 Cha.jvg 精灵 · 主段",
    2: "2 Ani.jvg 精灵 · 主段",
    3: "3 Ani.jvg 精灵 · 延迟段",
    4: "4 坐标锚点 (不渲染)",
    5: "5 结束标记 (不渲染)",
}

# 混合模式 (sub_4434BC: switch(+22) → 6 个渲染函数)
BLEND_MODE_LABELS = {
    0: "0 正常 sub_4544EC",
    1: "1 闪烁 sub_454D24",
    2: "2 半透叠加 sub_4559D0",
    3: "3 阴影 sub_458020",
    4: "4 负片 sub_459168",
    5: "5 另类 sub_458D08",
}

# 方向感知 (sub_4434BC L308: if(+4==4) v34=v33 else v34=0)
DIRECTION_MODE_LABELS = {
    0: "0 固定方向0",
    4: "4 随朝向变",
}

# 循环行为 (sub_4434BC L593-610: 当前帧到达 last_frame 后, 依 +38 处理)
LOOP_BEHAVIOR_LABELS = {
    -1: "-1 (0xFFFF) 循环到起始帧",
    -2: "-2 (0xFFFE) 停止本图层",
}

# 移动模式 (sub_4434BC +50 == 1/2)
MOVE_MODE_LABELS = {
    0: "0 无",
    1: "1 跟随移动",
    2: "2 四方来回",
}

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
W_INPUT = 10
W_INPUT_S = 6

# ============================================================
# JVG 轻量帧数探针  (不解码像素, 仅读 @JVG header + 各 @JVM sub_count)
# ============================================================

def scan_jvg_frame_counts(path):
    """读取 JVG 文件, 返回每个 block 的帧数列表 List[int].
    失败/文件不存在时返回 []. 只解析头部结构, 耗时常 <10ms."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception:
        return []
    if len(data) < 32 or data[0:4] != b'@JVG':
        return []
    try:
        block_count = struct.unpack('<I', data[8:12])[0]
    except struct.error:
        return []
    counts = []
    off = 32
    for _ in range(block_count):
        if off + 32 > len(data) or data[off:off + 4] != b'@JVM':
            break
        sub_count = struct.unpack('<I', data[off + 4:off + 8])[0]
        data_size = struct.unpack('<I', data[off + 12:off + 16])[0]
        counts.append(sub_count)
        # @JVM 总大小 = 32 头 + (sub_count+1)*4 偏移表 + 512 调色板 + data_size
        off += 32 + (sub_count + 1) * 4 + 512 + data_size
    return counts


# 常见 "总帧数 → (方向数, 每方向帧数)" 推断优先级表
_JVG_LAYOUT_HINTS = [
    (72, 8, 9),   # 8 向 × 9 帧 (主角级完整行走)
    (28, 4, 7),   # 4 向 × 7 帧 (标准行走) ★
    (32, 4, 8),   # 4 向 × 8 帧
    (20, 4, 5),   # 4 向 × 5 帧
    (4,  4, 1),   # 4 向纯静态
    (2,  2, 1),   # 2 向纯静态
]


def infer_jvg_layout(n_frames):
    """根据总帧数推断 (方向数, 每方向帧数, 是否确定模式)."""
    if n_frames <= 0:
        return (0, 0, False)
    for total, dirs, per in _JVG_LAYOUT_HINTS:
        if n_frames == total:
            return (dirs, per, True)
    for d in (4, 2, 1):
        if n_frames % d == 0:
            return (d, n_frames // d, False)
    return (1, n_frames, False)


# ============================================================
# Cha.jvg / Ani.jvg 块布局约定 (实测知识, 非 sub_4434BC 自身规定)
# ============================================================
# Cha.jvg:
#   block 0  = 角色脚下的阴影 (一大一小两个, 用于不同体型的角色)
#   block 1+ = 各角色的动画, 每个 block 一个角色
#              每个 block 的 "帧池大小" 与 "方向数×每方向帧数" 不固定:
#
#   ┌─────────┬────────────┬────────────────────────────────────┐
#   │ 总帧数  │ 方向×帧/向  │ 语义                                │
#   ├─────────┼────────────┼────────────────────────────────────┤
#   │   2     │ 2  × 1     │ 2 方向静态 (只有 2 静止姿, 无动画)  │
#   │   4     │ 4  × 1     │ 4 方向静态 (只有 4 静止姿, 无动画)  │
#   │  20     │ 4  × 5     │ 4 方向动画 (每向 5 帧)              │
#   │  28     │ 4  × 7     │ 4 方向标准行走 (静 1 + 走 6) ★常见   │
#   │  32     │ 4  × 8     │ 4 方向动画 (每向 8 帧)              │
#   │  72     │ 8  × 9     │ 8 方向行走 (静 1 + 走 8)            │
#   └─────────┴────────────┴────────────────────────────────────┘
#
#   约定: 每方向的"首帧"为该方向的静止姿势, 其余为该方向的行走/动作动画.
#
# Ani.jvg:
#   通用动画池, 可存特效/物件/飞行物, 也可以存剧情用的特殊角色精灵
#   按 jvg_block_index 查表, 帧布局无固定约定
#
# ⚠ 重要: ACT 引擎 sub_4434BC 的方向表循环步长是 8 字节/方向, 前 32 字节仅
#   容纳 4 方向的绘制顺序表, 故 v33 ∈ {0,1,2,3}. ACT 无法直接驱动 8 方向,
#   72 帧的块被 ACT 引用时只能用其中 4 方向部分 (如 dfo=9 first=0 last=8
#   将拿到 block 的 0..35 帧, 后 36..71 帧由其他渲染路径或闲置处理).
#
# ACT 侧的"帧片段"由以下三个字段组合决定, 与 JVG 块真实帧数解耦:
#   dir_frame_offset  方向间帧步长   (该块每方向帧数, 典型 7/8/5/9/1)
#   first_frame       方向内起始帧   (标准行走=0)
#   last_frame        方向内终止帧   (标准行走=该向帧数-1, 如 7帧时=6)
#
# 帧片段读取示例 (dirmode=4 随朝向变):
#   dfo=7 first=0 last=6  ⇒ 4 向×7 帧 (标准行走, 用 28 帧块全部)
#   dfo=9 first=0 last=8  ⇒ 4 向×9 帧 (切 72 帧块的前 4 向)
#   dfo=5 first=0 last=4  ⇒ 4 向×5 帧 (20 帧块全部)
#   dfo=8 first=0 last=7  ⇒ 4 向×8 帧 (32 帧块全部)
#   dfo=1 first=0 last=0  ⇒ 4 向×1 帧 (4 帧静态块全部)
#   dfo=7 first=0 last=0  ⇒ 4 向各取静止首帧 (只要站姿时使用 28 帧块)
#
# 引擎侧: sub_4434BC 只用 layer_type==1 切贴图源 (Cha.jvg vs Ani.jvg),
#         不做任何 "block 0 是阴影" 之类的判定, 语义完全由 jvg 内容决定.
#
# 典型"标准 28 帧角色行走"图层特征 (可用于编辑器推断):
#   layer_type == 1                   # Cha.jvg
#   jvg_block_index >= 1              # 不是阴影
#   direction_mode == 4               # 随朝向变
#   dir_frame_offset == 7             # 每方向 7 帧
#   first_frame == 0, last_frame == 6 # 一方向内的 7 帧
# ============================================================

# ============================================================
# 图层字段定义 — 按"语义分组"组织, 每字段 = (key, int16_idx, 标签, 宽度, 描述)
# ★ 标记表示 v1.0 中错标的字段已纠正
# ============================================================

# 单字段元组结构: (key, int16_idx, label, width, tooltip)
FIELD_GROUPS = [
    ("来源", [
        ("layer_type",       0,  "类型",       W_INPUT,
         "sub_4434BC: *(_WORD*)(+0)  1=Cha.jvg 其他=Ani.jvg"),
        ("jvg_block_index",  1,  "JVG 块号",    W_INPUT,
         "sub_4434BC: *(_WORD*)(+2)  → sub_45410C 查表\n"
         "Cha.jvg[0]=阴影(大/小各一); [1+]=角色动画\n"
         "  角色块帧数不固定: 2(2向静) 4(4向静) 20(4向×5) 28(4向×7,★常见)\n"
         "  32(4向×8) 72(8向×9, ACT只能用前4向)\n"
         "Ani.jvg 通用动画池 (特效/物件/剧情角色), 帧布局无固定约定"),
    ]),
    ("帧范围", [
        ("first_frame",      17, "起始帧",     W_INPUT,
         "sub_4434BC L595: *(_WORD*)(+34)  动画起始帧号\n"
         "★ 此为'方向内相对帧号', 引擎按 dir_frame_offset × direction 再叠加\n"
         "  标准行走约定: =0 (即该方向静止姿)"),
        ("last_frame",       18, "终止帧",     W_INPUT,
         "sub_4434BC L593: *(_WORD*)(+36)  到达即触发循环/停止\n"
         "★ 方向内相对帧号; 典型值:\n"
         "  =0  纯静止  =dfo-1  跑满该方向全部帧 (如 28帧块时=6, 72帧块时=8)"),
        ("loop_behavior",    19, "循环行为",   W_INPUT,
         "sub_4434BC L603: *(_WORD*)(+38)  -1 循环/-2 停止/≥0 跳帧"),
    ]),
    ("时序 ★", [
        ("tick_interval",    21, "帧停留 tick ★", W_INPUT,
         "sub_4434BC L574: if(counter>=+42) 翻下一帧  ← 数据字段, 可编辑"),
        ("start_delay",      22, "启动延迟 ★",    W_INPUT,
         "sub_4434BC L248/L566: !*(+44) 才递增, --*(+44)  ← 数据字段, 可编辑"),
    ]),
    ("渲染", [
        ("blend_mode",       11, "混合模式",   W_INPUT,
         "sub_4434BC L320-339: switch(+22) → 6 种渲染"),
        ("blend_param",      12, "混合参数",   W_INPUT,
         "sub_4434BC: *(_WORD*)(+24)  颜色/alpha/随机种等"),
        ("blend_param_step", 13, "混合参数步进", W_INPUT,
         "sub_4434BC L613: *(+24) += *(+26)  每翻帧的累加量"),
    ]),
    ("位移 (方向 0~3)", [
        ("x_off_d0",         3,  "X₀", W_INPUT_S, "sub_4434BC: +6  方向0 的 X 偏移"),
        ("x_off_d1",         4,  "X₁", W_INPUT_S, "sub_4434BC: +8  方向1 的 X 偏移"),
        ("x_off_d2",         5,  "X₂", W_INPUT_S, "sub_4434BC: +10 方向2 的 X 偏移"),
        ("x_off_d3",         6,  "X₃", W_INPUT_S, "sub_4434BC: +12 方向3 的 X 偏移"),
        ("y_off_d0",         7,  "Y₀", W_INPUT_S, "sub_4434BC: +14 方向0 的 Y 偏移"),
        ("y_off_d1",         8,  "Y₁", W_INPUT_S, "sub_4434BC: +16 方向1 的 Y 偏移"),
        ("y_off_d2",         9,  "Y₂", W_INPUT_S, "sub_4434BC: +18 方向2 的 Y 偏移"),
        ("y_off_d3",         10, "Y₃", W_INPUT_S, "sub_4434BC: +20 方向3 的 Y 偏移"),
    ]),
    ("方向感知", [
        ("direction_mode",   2,  "方向模式",   W_INPUT,
         "sub_4434BC L308: if(+4==4) 随朝向变 else 固定方向0"),
        ("dir_frame_offset", 16, "方向帧偏移", W_INPUT,
         "sub_4434BC L309: v35 += +32 × v33 (方向模式=4 时按朝向偏移帧号)\n"
         "★ 等于'该方向帧段长度'(即每方向帧数); 常见值:\n"
         "  =7  (28帧块, 4向×7)  =8  (32帧块, 4向×8)  =5  (20帧块, 4向×5)\n"
         "  =9  (72帧块前半, 4向×9)  =1  (4帧纯静态块)"),
    ]),
    ("自动移动", [
        ("move_mode",        25, "移动模式",   W_INPUT,
         "sub_4434BC L577-591: +50 == 1 跟随 / == 2 四方往返"),
        ("step_value",       26, "步进值",     W_INPUT_S,
         "sub_4434BC: *(_WORD*)(+52)"),
        ("step_delta",       27, "步进增量",   W_INPUT_S,
         "sub_4434BC: *(_WORD*)(+54)"),
    ]),
    ("运行时 (只读, 文件=0)", [
        ("_rt_frame_base",   14, "帧基址",     W_INPUT_S,
         "sub_4434BC: +28 = sub_45408C(...)"),
        ("_rt_cur_frame",    15, "当前帧",     W_INPUT_S,
         "sub_4434BC: +30 = base+init"),
        ("_rt_20",           20, "RT20",       W_INPUT_S, "运行时"),
        ("_rt_counter",      23, "RT 计数",    W_INPUT_S,
         "sub_4434BC: *(+46)"),
        ("_rt_dir_sign",     24, "RT 方向符",  W_INPUT_S,
         "sub_4434BC: +48 ∈ {0,1,-1}"),
    ]),
    ("保留 / 未知", [
        (f"_res_{i}", i, f"[{i}]", W_INPUT_S, f"int16[{i}] 未在 sub_4434BC 中引用")
        for i in range(28, 40)
    ]),
]

# 平铺全部字段 (供加载/保存使用)
ALL_FIELDS = [f for _, grp in FIELD_GROUPS for f in grp]

# 运行时 / 保留字段 (UI 上以只读灰显呈现)
READONLY_KEYS = {f[0] for f in ALL_FIELDS
                 if f[0].startswith('_rt') or f[0].startswith('_res')}


# ============================================================
# 数据加载 / 保存
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
        data = raw[off:off + ACT_ENTRY_SIZE]

        # 方向表: 4 方向 × 8 字节
        dirs = []
        for d in range(4):
            dirs.append(list(data[d * 8: d * 8 + 8]))

        # 条目级参数区 int16[16..39] (bytes 32..79)
        param16 = list(struct.unpack_from('<24h', data, ACT_PARAM_OFFSET))

        # 8 个图层
        layers = []
        for s in range(1, ACT_MAX_LAYER + 1):
            lo = s * ACT_LAYER_SIZE
            layers.append(list(struct.unpack_from('<40h', data, lo)))

        # 尾部 32 int16 → 16 对 (value, count)
        tail = list(struct.unpack_from('<32h', data, ACT_TAIL_OFFSET))

        entries.append({
            'index':   i,
            'dirs':    dirs,
            'param16': param16,
            'layers':  layers,
            'tail':    tail,
        })
    return entries


def save_act(fp, entries):
    """保存 TKAct.dat (原始文件, 非 LZSS)"""
    buf = bytearray(ACT_ENTRY_COUNT * ACT_ENTRY_SIZE)
    for entry in entries:
        i = entry['index']
        off = i * ACT_ENTRY_SIZE

        # 方向表
        for d in range(4):
            b = entry['dirs'][d]
            buf[off + d * 8: off + d * 8 + 8] = bytes(
                v & 0xFF for v in b)

        # 条目级参数
        struct.pack_into('<24h', buf, off + ACT_PARAM_OFFSET,
                         *entry['param16'])

        # 图层
        for s in range(ACT_MAX_LAYER):
            lo = off + (s + 1) * ACT_LAYER_SIZE
            struct.pack_into('<40h', buf, lo, *entry['layers'][s])

        # 尾部
        struct.pack_into('<32h', buf, off + ACT_TAIL_OFFSET, *entry['tail'])

    if len(buf) != ACT_DECOMPRESSED:
        raise RuntimeError(f"回写缓冲区大小异常: {len(buf)}")

    with open(fp, 'wb') as f:
        f.write(buf)
    return True


def entry_is_empty(entry):
    for d in range(4):
        if any(entry['dirs'][d]):
            return False
    if any(entry['param16']):
        return False
    for s in range(ACT_MAX_LAYER):
        if any(v != 0 for v in entry['layers'][s]):
            return False
    if any(entry['tail']):
        return False
    return True


def entry_active_layers(entry):
    """返回 type ≠ 0 的图层号集合 (1-based)"""
    used = set()
    for s in range(ACT_MAX_LAYER):
        if entry['layers'][s][0] != 0:
            used.add(s + 1)
    return used


def entry_referenced_layers(entry):
    """返回方向表引用过的图层号集合 (1-based)"""
    used = set()
    for d in range(4):
        for v in entry['dirs'][d]:
            if v:
                used.add(v)
    return used


def entry_summary(entry):
    refd = entry_referenced_layers(entry)
    act = entry_active_layers(entry)
    shown = sorted(refd | act)
    if not shown:
        return "(空)"
    parts = []
    for s in shown[:6]:
        t = entry['layers'][s - 1][0] if 1 <= s <= ACT_MAX_LAYER else 0
        parts.append(f"#{s}({t})")
    if len(shown) > 6:
        parts.append("…")
    return " ".join(parts)


# ============================================================
# GUI
# ============================================================

class ActEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKAct.dat 多图层 2D 精灵动画编辑器 v2.0")
        ico = os.path.join(os.path.dirname(__file__), '..', 'kon_editor',
                           'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1320x860")
        self.root.minsize(1080, 680)

        self.act_path = None
        self.ani_path = None     # Ani.jvg
        self.cha_path = None     # Cha.jvg
        self.entries = []
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None

        # JVG 数据
        self._ani_data = None
        self._cha_data = None
        self._jvg_cache = {}     # {(src, block, frame): PhotoImage}

        # JVG 轻量探针 (block 帧数列表)
        self._cha_counts = []
        self._ani_counts = []

        # 预览状态
        self._preview_job = None
        self._preview_tick_idx = 0

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1320) // 2
        y = (sh - 860) // 2
        self.root.geometry(f'1320x860+{x}+{y}')

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
        em.add_command(label="复制当前条目到空位", command=self._copy_entry)
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
        ttk.Checkbutton(tb, text="显示空条目", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(
            side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(
            side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned)
        paned.add(lf, weight=1)
        cols = ('index', 'summary', 'n_layer')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings',
                                 selectmode='browse')
        cc = [
            ('index', '动画#', 55),
            ('summary', '图层组成 (#图层(type))', 220),
            ('n_layer', '图层数', 60),
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

        # Tab 1: 方向与绘制顺序 (z-order)
        self.dir_frame = ttk.Frame(self.nb)
        self.nb.add(self.dir_frame, text="方向与绘制顺序")

        # Tab 2: 图层编辑 (8 子 Tab, 每个按语义分组)
        self.layer_nb = ttk.Notebook(self.nb)
        self.nb.add(self.layer_nb, text="图层编辑")
        self._layer_frames = []
        self._layer_vars = []   # [{key: StringVar, '_type_combo': Combobox, ...}] × 8
        for s in range(1, ACT_MAX_LAYER + 1):
            sf = ttk.Frame(self.layer_nb)
            self.layer_nb.add(sf, text=f"#{s}")
            self._layer_frames.append(sf)

        # Tab 3: 条目级参数
        self.param_frame = ttk.Frame(self.nb)
        self.nb.add(self.param_frame, text="条目级参数")

        # Tab 4: 动画预览
        self.preview_frame = ttk.Frame(self.nb)
        self.nb.add(self.preview_frame, text="动画预览")

        # Tab 5: 尾部数据 (16 对)
        self.tail_frame = ttk.Frame(self.nb)
        self.nb.add(self.tail_frame, text="尾部数据")

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_path = ttk.Label(pf, text="", foreground="gray")
        self.lbl_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_jvg = ttk.Label(pf, text="", foreground="gray")
        self.lbl_jvg.pack(side=tk.LEFT, padx=10, pady=2)

        self._build_direction_ui()
        self._build_layer_uis()
        self._build_param_ui()
        self._build_preview_ui()
        self._build_tail_ui()

    # -------- Tab: 方向与绘制顺序 --------

    def _build_direction_ui(self):
        """4 × 8 表格: 行=方向, 列=z-order 位次, 单元格=图层号 (0/1..8)
        sub_4434BC: v22[8*v33 + i] 按字节序依次渲染 → 后绘制在上层
        """
        main = ttk.Frame(self.dir_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="方向表 (bytes 0-31): 每行 8 个槽 = 该方向的绘制顺序 "
                 "(从左到右: 底层 → 顶层)。单元格值 0=空, 1~8=图层号。",
            font=FONT_S, foreground='#666', wraplength=900, justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        tbl = ttk.Frame(main)
        tbl.pack(anchor=tk.W)

        # 表头
        ttk.Label(tbl, text="", width=14).grid(row=0, column=0)
        ttk.Label(tbl, text="底层", font=FONT_S,
                  foreground='#888').grid(row=0, column=1, sticky='w')
        ttk.Label(tbl, text="→ 顶层", font=FONT_S,
                  foreground='#888').grid(row=0, column=8, sticky='e')
        for s in range(8):
            ttk.Label(tbl, text=f"z{s}", font=FONT_S,
                      foreground='#999').grid(row=1, column=1 + s, padx=2)

        # 4 行 × 8 列
        self._dir_vars = [[tk.StringVar() for _ in range(8)] for _ in range(4)]
        for d in range(4):
            ttk.Label(tbl, text=DIRECTION_LABELS[d], font=FONT_B).grid(
                row=2 + d, column=0, sticky='w', padx=(0, 6), pady=2)
            for i in range(8):
                ent = ttk.Entry(tbl, textvariable=self._dir_vars[d][i],
                                width=4, font=FONT, justify='center')
                ent.grid(row=2 + d, column=1 + i, padx=1, pady=1)
                self._bind_tooltip(
                    ent,
                    f"{DIRECTION_LABELS[d]} z-order[{i}] (byte {d*8+i})\n"
                    f"值 0=空, 1-8=图层号\n"
                    f"sub_4434BC 按此顺序依次渲染, 后画的覆盖前画的")

        ttk.Label(
            main,
            text="说明: 朝向不同时顺序常反转 (如下/右 = [3,4,1,2], 上/左 = [1,2,3,4]), "
                 "这就是 2.5D 身前/身后遮挡关系的数据源。",
            font=FONT_S, foreground='#888', wraplength=900, justify='left'
        ).pack(anchor=tk.W, pady=(10, 0))

    # -------- Tab: 图层编辑 --------

    def _build_layer_uis(self):
        self._layer_vars = []
        for s in range(1, ACT_MAX_LAYER + 1):
            sf = self._layer_frames[s - 1]

            canvas = tk.Canvas(sf, highlightthickness=0)
            sb = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=canvas.yview)
            inner = ttk.Frame(canvas)
            inner.bind('<Configure>',
                       lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
            canvas.create_window((0, 0), window=inner, anchor='nw')
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)

            def _mw(e, c=canvas):
                c.yview_scroll(int(-1 * (e.delta / 120)), "units")

            canvas.bind("<Enter>",
                        lambda e, c=canvas: c.bind_all("<MouseWheel>", _mw))
            canvas.bind("<Leave>",
                        lambda e, c=canvas: c.unbind_all("<MouseWheel>"))

            vars_row = {}

            # 头部: 图层号与类型
            head = ttk.Frame(inner, padding=(4, 4))
            head.pack(fill=tk.X, anchor=tk.W)
            ttk.Label(head, text=f"图层 #{s}", font=('', 11, 'bold')
                      ).pack(side=tk.LEFT)
            ttk.Label(head, text="类型:", font=FONT).pack(side=tk.LEFT,
                                                         padx=(12, 2))
            type_var = tk.StringVar()
            vars_row['layer_type'] = type_var
            type_combo = ttk.Combobox(
                head, textvariable=type_var,
                values=list(LAYER_TYPE_LABELS.values()),
                width=26, state='readonly', font=FONT)
            type_combo.pack(side=tk.LEFT, padx=2)
            vars_row['_type_combo'] = type_combo
            self._layer_vars.append(vars_row)

            # 探针面板 (显示 JVG 实际帧数/推断布局/ACT 切片比例)
            probe_row = ttk.Frame(inner, padding=(4, 0))
            probe_row.pack(fill=tk.X, anchor=tk.W)
            probe_lbl = ttk.Label(
                probe_row, text="", font=FONT_S,
                foreground='#556', justify='left')
            probe_lbl.pack(side=tk.LEFT, anchor='w')
            vars_row['_probe_lbl'] = probe_lbl
            self._bind_tooltip(
                probe_lbl,
                "JVG 帧数探针 — 自动对比此图层的 (type, jvg_block_index)\n"
                "  · 实际帧数 ← 从 Cha.jvg / Ani.jvg 头部扫描得到\n"
                "  · 推断布局 ← 按 4/8 方向优先匹配得出\n"
                "  · ACT 切片 ← 由当前 dfo/first/last 字段决定")

            # 按语义分组渲染字段
            for grp_name, fields in FIELD_GROUPS:
                lf_grp = ttk.LabelFrame(inner, text=grp_name, padding=4)
                lf_grp.pack(fill=tk.X, padx=4, pady=3, anchor=tk.W)

                self._render_field_group(lf_grp, fields, vars_row)

            # 字段变化时刷新探针 (layer_type 由 combo 的 bind 处理)
            for fn in ('jvg_block_index', 'dir_frame_offset',
                       'first_frame', 'last_frame', 'direction_mode'):
                if fn in vars_row:
                    vars_row[fn].trace_add(
                        'write',
                        lambda *_a, idx=s-1: self._update_layer_probe(idx))
            type_combo.bind(
                '<<ComboboxSelected>>',
                lambda _e, idx=s-1: self._update_layer_probe(idx),
                add='+')

    def _render_field_group(self, parent, fields, vars_row):
        """在 parent 内以每行 4 列网格渲染字段"""
        row = 0
        col = 0
        per_row = 4
        for (fn, idx, label, width, comment) in fields:
            if fn == 'layer_type':
                # 已在 head 单独渲染
                continue
            cell = ttk.Frame(parent)
            cell.grid(row=row, column=col, sticky='w', padx=4, pady=1)
            is_ro = fn in READONLY_KEYS

            lbl = ttk.Label(cell, text=f"{label}  [{idx}]", font=FONT_S,
                            foreground=('#AAA' if is_ro else '#444'))
            lbl.pack(anchor=tk.W)
            self._bind_tooltip(lbl, comment)

            sv = tk.StringVar()
            vars_row[fn] = sv

            # 下拉候选 (枚举字段)
            if fn == 'blend_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(BLEND_MODE_LABELS.values()),
                                     width=22, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'direction_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(DIRECTION_MODE_LABELS.values()),
                                     width=14, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'loop_behavior':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(LOOP_BEHAVIOR_LABELS.values()),
                                     width=22, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            elif fn == 'move_mode':
                combo = ttk.Combobox(cell, textvariable=sv,
                                     values=list(MOVE_MODE_LABELS.values()),
                                     width=14, font=FONT)
                combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                vars_row[f'_{fn}_combo'] = combo
            else:
                ent = ttk.Entry(cell, textvariable=sv, width=width, font=FONT)
                if is_ro:
                    ent.configure(state='readonly', foreground='#AAA')
                ent.pack(side=tk.LEFT, fill=tk.X, expand=True)

            col += 1
            if col >= per_row:
                col = 0
                row += 1

    # -------- Tab: 条目级参数 --------

    def _build_param_ui(self):
        """条目级参数区 (bytes 32-79, int16[16..39], 共 24 项)"""
        main = ttk.Frame(self.param_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="条目级参数区 (bytes 32-79, int16[16..39], 共 24 项)。\n"
                 "★ [18] 疑似总 tick;  [20/22/24/…] 疑似每激活图层的 tick 配额;  其余多为 0。",
            font=FONT_S, foreground='#666', justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        grid = ttk.Frame(main)
        grid.pack(anchor=tk.W)

        self._param_vars = []
        for k, idx in enumerate(range(16, 40)):
            row = k // 6
            col = k % 6
            cell = ttk.Frame(grid)
            cell.grid(row=row, column=col, sticky='w', padx=3, pady=2)

            hint = ""
            if idx == 18:
                hint = " 总tick?"
            elif idx in (20, 22, 24, 26, 28):
                hint = " 图层tick?"
            ttk.Label(cell, text=f"[{idx:2d}]{hint}", font=FONT_S,
                      foreground='#888').pack(anchor=tk.W)
            sv = tk.StringVar()
            self._param_vars.append(sv)
            ent = ttk.Entry(cell, textvariable=sv, width=8, font=FONT)
            ent.pack(side=tk.LEFT)
            self._bind_tooltip(
                ent, f"int16[{idx}] = bytes {idx*2}..{idx*2+1}")

    # -------- Tab: 尾部 (16 对) --------

    def _build_tail_ui(self):
        main = ttk.Frame(self.tail_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="尾部 (bytes 720-783, 16 对 value/count) — 未在 sub_4434BC 中直接引用\n"
                 "疑似关键帧/触发表, 用途未完全验证",
            font=FONT_S, foreground='#666', justify='left'
        ).pack(anchor=tk.W, pady=(0, 6))

        canvas = tk.Canvas(main, highlightthickness=0)
        sb = ttk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>',
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(inner, text="#", font=FONT_B, width=4).grid(
            row=0, column=0, padx=2)
        ttk.Label(inner, text="value", font=FONT_B, width=8).grid(
            row=0, column=1, padx=2)
        ttk.Label(inner, text="count", font=FONT_B, width=8).grid(
            row=0, column=2, padx=2)
        ttk.Label(inner, text="原 int16 索引", font=FONT_B,
                  foreground='#999').grid(row=0, column=3, padx=8, sticky='w')

        self._tail_vars = []
        for pair in range(16):
            r = pair + 1
            ttk.Label(inner, text=f"{pair:02d}", font=FONT_S,
                      foreground='#666').grid(row=r, column=0, padx=2)
            v_var = tk.StringVar()
            c_var = tk.StringVar()
            self._tail_vars.append(v_var)
            self._tail_vars.append(c_var)
            ttk.Entry(inner, textvariable=v_var, width=8,
                      font=FONT).grid(row=r, column=1, padx=2)
            ttk.Entry(inner, textvariable=c_var, width=8,
                      font=FONT).grid(row=r, column=2, padx=2)
            ttk.Label(inner, text=f"[{pair*2}], [{pair*2+1}]",
                      font=FONT_S, foreground='#AAA').grid(
                row=r, column=3, padx=8, sticky='w')

    # -------- Tab: 动画预览 --------

    def _build_preview_ui(self):
        main = ttk.Frame(self.preview_frame, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(ctrl, text="方向:", font=FONT_S).pack(side=tk.LEFT)
        self._preview_dir_var = tk.IntVar(value=0)
        for d in range(4):
            ttk.Radiobutton(ctrl, text=DIRECTION_LABELS[d][:3],
                            variable=self._preview_dir_var, value=d,
                            command=self._preview_redraw,
                            width=5).pack(side=tk.LEFT)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(ctrl, text="tick 周期(ms):", font=FONT_S).pack(side=tk.LEFT)
        self._preview_speed = tk.IntVar(value=50)
        ttk.Spinbox(ctrl, textvariable=self._preview_speed,
                    from_=10, to=500, increment=10, width=5,
                    font=FONT).pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl, text="▶", command=self._preview_play,
                   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(ctrl, text="⏸", command=self._preview_stop,
                   width=3).pack(side=tk.LEFT, padx=1)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)

        self._preview_vis_frame = ttk.Frame(ctrl)
        self._preview_vis_frame.pack(side=tk.LEFT, fill=tk.X)
        self._preview_vis_vars = {}

        self._preview_canvas = tk.Canvas(main, bg='#1a1a2e',
                                         highlightthickness=0)
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas.bind('<Configure>',
                                  lambda e: self._preview_redraw())

        if not HAS_PIL:
            self._preview_canvas.create_text(
                200, 100, text="需要 Pillow 库:\npip install Pillow",
                fill="#888", font=("", 11))

    # -------- 通用辅助 --------

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
                      borderwidth=1, font=FONT_S, wraplength=480,
                      padding=3).pack()
            tip['win'] = w

        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None

        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

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
            elif isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton,
                                ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except Exception:
            pass
        for c in w.winfo_children():
            self._set_ws(c, en)

    @staticmethod
    def _enum_to_label(value, label_map):
        return label_map.get(value, f"{value} (未知)")

    @staticmethod
    def _label_to_enum(label, label_map):
        for k, v in label_map.items():
            if v == label:
                return k
        try:
            return int((label or '0').strip().split()[0])
        except Exception:
            return 0

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
        self._ani_data = None
        self._cha_data = None
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
        else:
            self.lbl_path.config(text=f"TKAct: {self.act_path}", foreground=g)
        # 探针: 轻量扫描 JVG 获取 block 帧数 (不解码像素)
        self._cha_counts = (scan_jvg_frame_counts(self.cha_path)
                            if self.cha_path else [])
        self._ani_counts = (scan_jvg_frame_counts(self.ani_path)
                            if self.ani_path else [])
        cha_note = (f"{len(self._cha_counts)} blocks"
                    if self._cha_counts else "✗")
        ani_note = (f"{len(self._ani_counts)} blocks"
                    if self._ani_counts else "✗")
        self.lbl_jvg.config(
            text=(f"Cha.jvg: {cha_note}   |   "
                  f"Ani.jvg: {ani_note}"),
            foreground=g if (self._cha_counts or self._ani_counts) else r)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower()
        self.filtered_indices = []
        for entry in self.entries:
            if not self.show_empty.get() and entry_is_empty(entry):
                continue
            if q:
                text = f"{entry['index']} {entry_summary(entry)}".lower()
                if q not in text:
                    continue
            self.filtered_indices.append(entry['index'])
        self._refresh_table()
        nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
        msg = (f"显示 {len(self.filtered_indices)}/{ACT_ENTRY_COUNT} "
               f"(非空 {nonempty}) | Ctrl+S 保存")
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
            n_layer = len(entry_active_layers(entry))
            has_data = not entry_is_empty(entry)
            tags = ['active'] if has_data else ['empty']
            self.tree.insert('', 'end',
                             values=(entry['index'],
                                     entry_summary(entry), n_layer),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'summary':
            self.filtered_indices.sort(
                key=lambda i: entry_summary(self.entries[i]).lower(),
                reverse=rev)
        elif col == 'n_layer':
            self.filtered_indices.sort(
                key=lambda i: len(entry_active_layers(self.entries[i])),
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
        active = sorted(entry_active_layers(entry))
        refd = sorted(entry_referenced_layers(entry))
        self.lbl_entry.config(
            text=(f"动画 #{entry['index']}   "
                  f"活跃图层 {active if active else '(空)'}   "
                  f"方向表引用 {refd if refd else '(无)'}"))

        for d in range(4):
            for i in range(8):
                self._dir_vars[d][i].set(str(entry['dirs'][d][i]))

        for s in range(ACT_MAX_LAYER):
            self._populate_layer(s, entry['layers'][s])

        for k in range(24):
            self._param_vars[k].set(str(entry['param16'][k]))

        for k in range(32):
            self._tail_vars[k].set(str(entry['tail'][k]))

        for s in range(ACT_MAX_LAYER):
            t = entry['layers'][s][0]
            if t == 0:
                self.layer_nb.tab(s, text=f"#{s+1} (空)")
            else:
                full = LAYER_TYPE_LABELS.get(t, str(t))
                parts = full.split(' ', 1)
                lab = (parts[1].split('(')[0].strip()
                       if len(parts) > 1 else full)
                self.layer_nb.tab(s, text=f"#{s+1} {lab}")

        self._preview_reload()

    def _populate_layer(self, layer_idx, vals):
        vars_row = self._layer_vars[layer_idx]
        t = vals[0]
        combo = vars_row.get('_type_combo')
        if combo is not None:
            combo.set(self._enum_to_label(t, LAYER_TYPE_LABELS))
        vars_row['layer_type'].set(str(t))

        for (fn, idx, _, _, _) in ALL_FIELDS:
            if fn == 'layer_type' or fn not in vars_row:
                continue
            v = vals[idx]
            if fn == 'blend_mode':
                vars_row[fn].set(self._enum_to_label(v, BLEND_MODE_LABELS))
            elif fn == 'direction_mode':
                vars_row[fn].set(self._enum_to_label(v, DIRECTION_MODE_LABELS))
            elif fn == 'loop_behavior':
                vars_row[fn].set(self._enum_to_label(v, LOOP_BEHAVIOR_LABELS))
            elif fn == 'move_mode':
                vars_row[fn].set(self._enum_to_label(v, MOVE_MODE_LABELS))
            else:
                vars_row[fn].set(str(v))

        self._update_layer_probe(layer_idx)

    # ----------- JVG 帧数探针 -----------

    def _update_layer_probe(self, layer_idx):
        """刷新指定图层的探针标签: 显示 JVG 实际帧数、推断布局、ACT 切片比例"""
        vars_row = self._layer_vars[layer_idx]
        lbl = vars_row.get('_probe_lbl')
        if lbl is None:
            return

        def _iv(key, default=0):
            try:
                raw = vars_row[key].get() if key in vars_row else ''
                # 枚举字段 (如 direction_mode) 取前缀数字
                raw = raw.split(' ', 1)[0] if raw else ''
                return int(raw) if raw.lstrip('-').isdigit() else default
            except Exception:
                return default

        # layer_type 直接从 combo 取
        combo = vars_row.get('_type_combo')
        type_lbl = combo.get() if combo else ''
        try:
            ltype = int(type_lbl.split(' ', 1)[0]) if type_lbl else 0
        except Exception:
            ltype = 0

        blk = _iv('jvg_block_index', -1)
        dfo = _iv('dir_frame_offset', 0)
        first = _iv('first_frame', 0)
        last = _iv('last_frame', 0)
        dmode = _iv('direction_mode', 0)

        # 空图层
        if ltype == 0:
            lbl.config(text="— (空图层)", foreground='#AAA')
            return

        # 非渲染图层
        if ltype >= 4:
            name = {4: '坐标锚点', 5: '结束标记'}.get(ltype, '非渲染')
            lbl.config(text=f"— {name} (无 JVG 引用)", foreground='#AAA')
            return

        # 选择 JVG 源
        if ltype == 1:
            src_name, counts = 'Cha.jvg', self._cha_counts
        else:
            src_name, counts = 'Ani.jvg', self._ani_counts

        if not counts:
            lbl.config(
                text=f"{src_name}[{blk}]  (未加载 JVG, 无法探测实际帧数)",
                foreground='#C60')
            return
        if blk < 0 or blk >= len(counts):
            lbl.config(
                text=f"{src_name}[{blk}]  ✗ 块号越界 (共 {len(counts)} 块)",
                foreground='#C33')
            return

        n_frames = counts[blk]
        dirs, per, is_std = infer_jvg_layout(n_frames)

        # ACT 切片窗口 (方向内帧范围)
        per_dir_act = (last - first + 1) if last >= first else 0
        # 全部方向下读取到的帧号范围 (dmode=4 时跨 4 向, 否则仅方向 0)
        if dmode == 4:
            read_max = last + dfo * 3
            span_desc = f"方向 0: {first}..{last}  方向 3: {first+dfo*3}..{read_max}"
            used = per_dir_act * 4
        else:
            read_max = last
            span_desc = f"方向 0 (固定): {first}..{last}"
            used = per_dir_act

        pct = (used * 100 // n_frames) if n_frames > 0 else 0
        tag = '✓' if is_std else '·'
        layout_desc = f"{tag} 推断 {dirs}向×{per}帧"

        # 告警: 只标识"一定是错的"情况 (方向 0 单向就越界)
        warn = ''
        if last >= n_frames or first < 0:
            warn = f"  ⚠ 方向 0 切片 {first}..{last} 越出池 0..{n_frames-1}"

        # 信息提示 (不标红): dfo 与推断不符
        info = ''
        if is_std and dfo > 0 and dfo != per and dmode == 4:
            info = f"  (dfo={dfo} ≠ 推断 {per}, 非标准切片)"

        if warn:
            color = '#C33'
        elif is_std and not info:
            color = '#093'
        else:
            color = '#456'

        lbl.config(
            text=(f"{src_name}[{blk}]  实际 {n_frames} 帧   {layout_desc}{info}\n"
                  f"    {span_desc}   切片量 {used}/{n_frames} ({pct}%){warn}"),
            foreground=color)

    def _apply_edit(self):
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]

        for d in range(4):
            for i in range(8):
                try:
                    v = int(self._dir_vars[d][i].get() or 0)
                except ValueError:
                    v = 0
                entry['dirs'][d][i] = max(0, min(255, v))

        for s in range(ACT_MAX_LAYER):
            vals = entry['layers'][s]
            vars_row = self._layer_vars[s]
            combo = vars_row.get('_type_combo')
            if combo is not None:
                vals[0] = self._label_to_enum(combo.get(), LAYER_TYPE_LABELS)

            for (fn, idx, _, _, _) in ALL_FIELDS:
                if fn == 'layer_type' or fn not in vars_row:
                    continue
                raw = vars_row[fn].get()
                if fn == 'blend_mode':
                    v = self._label_to_enum(raw, BLEND_MODE_LABELS)
                elif fn == 'direction_mode':
                    v = self._label_to_enum(raw, DIRECTION_MODE_LABELS)
                elif fn == 'loop_behavior':
                    v = self._label_to_enum(raw, LOOP_BEHAVIOR_LABELS)
                elif fn == 'move_mode':
                    v = self._label_to_enum(raw, MOVE_MODE_LABELS)
                else:
                    try:
                        v = int((raw or '0').strip())
                    except ValueError:
                        v = 0
                vals[idx] = max(-32768, min(32767, v))

        for k in range(24):
            try:
                v = int(self._param_vars[k].get() or 0)
            except ValueError:
                v = 0
            entry['param16'][k] = max(-32768, min(32767, v))

        for k in range(32):
            try:
                v = int(self._tail_vars[k].get() or 0)
            except ValueError:
                v = 0
            entry['tail'][k] = max(-32768, min(32767, v))

        self._dirty = True
        self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == entry['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self._populate_edit(entry)
        self.status_var.set(f"动画 #{entry['index']} 已修改 (内存, 未保存)")

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
                entry['dirs'] = [list(d) for d in src['dirs']]
                entry['param16'] = list(src['param16'])
                entry['layers'] = [list(L) for L in src['layers']]
                entry['tail'] = list(src['tail'])
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
                               f"所有 {ACT_ENTRY_COUNT} 个条目均已占用")

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
        self.entries[idx_save] = {
            'index': idx_save,
            'dirs': [[0] * 8 for _ in range(4)],
            'param16': [0] * 24,
            'layers': [[0] * 40 for _ in range(ACT_MAX_LAYER)],
            'tail': [0] * 32,
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
        if not messagebox.askyesno(
                "确认保存",
                f"保存 {len(self.entries)} 条到:\n{self.act_path}\n\n"
                f"原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.act_path, 'rb') as s:
                with open(self.act_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except Exception:
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
            cols = ['动画#', '图层组成']
            for s in range(1, ACT_MAX_LAYER + 1):
                for (fn, _, _, _, _) in ALL_FIELDS:
                    cols.append(f"L{s}_{fn}")
            f.write(','.join(cols) + '\n')
            for entry in self.entries:
                if entry_is_empty(entry):
                    continue
                row = [str(entry['index']), entry_summary(entry)]
                for s in range(ACT_MAX_LAYER):
                    L = entry['layers'][s]
                    for (_, idx, _, _, _) in ALL_FIELDS:
                        row.append(str(L[idx]))
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ============================================================
    # 动画预览 (遵循 sub_4434BC 语义)
    # ============================================================

    def _preview_active_layers(self, direction):
        """按方向表的 z-order 返回 (slot, eff_dir, layer_vals): 底层→顶层"""
        entry = self.entries[self._editing_idx]
        order = [v for v in entry['dirs'][direction % 4] if v]
        if not order:
            order = sorted(entry_active_layers(entry))
        out = []
        for slot in order:
            if slot < 1 or slot > ACT_MAX_LAYER:
                continue
            L = entry['layers'][slot - 1]
            if L[0] == 0:
                continue
            eff_dir = direction if L[2] == 4 else 0
            out.append((slot, eff_dir, L))
        return out

    def _preview_load_jvg(self):
        if not HAS_PIL:
            return False
        jvg_mod = _get_jvg_loader()
        if not jvg_mod:
            return False
        try:
            if self.cha_path and not self._cha_data:
                self._cha_data = jvg_mod.load_jvg(self.cha_path)
            if self.ani_path and not self._ani_data:
                self._ani_data = jvg_mod.load_jvg(self.ani_path)
        except Exception:
            pass
        return (self._cha_data is not None) or (self._ani_data is not None)

    def _preview_get_frame(self, src, block_idx, frame_idx):
        key = (src, block_idx, frame_idx)
        cached = self._jvg_cache.get(key)
        if cached is not None:
            return cached
        jvg = self._cha_data if src == 'cha' else self._ani_data
        if jvg is None or block_idx < 0 or block_idx >= len(jvg.blocks):
            return None
        blk = jvg.blocks[block_idx]
        if frame_idx < 0 or frame_idx >= blk.frame_count:
            return None
        f = blk.frames[frame_idx]
        if f.width <= 0 or f.height <= 0:
            return None
        pal_rgb = blk.palette.to_rgb888()
        rgba = bytearray(f.width * f.height * 4)
        for py in range(f.height):
            base = py * f.width
            for px in range(f.width):
                p = base + px
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                o = p * 4
                rgba[o] = pal_rgb[idx * 3]
                rgba[o + 1] = pal_rgb[idx * 3 + 1]
                rgba[o + 2] = pal_rgb[idx * 3 + 2]
                rgba[o + 3] = 255
        try:
            img = Image.frombytes('RGBA', (f.width, f.height), bytes(rgba))
            tk_img = ImageTk.PhotoImage(img)
            res = (tk_img, f, blk)
            self._jvg_cache[key] = res
            return res
        except Exception:
            return None

    def _preview_reload(self):
        self._preview_stop()
        if self._editing_idx is None:
            return
        if not self._ani_data and not self._cha_data:
            self._preview_load_jvg()
        self._preview_tick_idx = 0
        self._preview_update_vis()
        self._preview_redraw()

    def _preview_update_vis(self):
        for w in self._preview_vis_frame.winfo_children():
            w.destroy()
        self._preview_vis_vars.clear()
        if self._editing_idx is None:
            return
        entry = self.entries[self._editing_idx]
        slots = entry_referenced_layers(entry) | entry_active_layers(entry)
        if not slots:
            return
        for slot in sorted(slots):
            t = entry['layers'][slot - 1][0]
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self._preview_vis_frame,
                                 text=f"#{slot}(t={t})",
                                 variable=var,
                                 command=self._preview_redraw)
            cb.pack(side=tk.LEFT, padx=1)
            self._preview_vis_vars[slot] = var

    def _preview_play(self):
        if self._editing_idx is None:
            return
        if not self._ani_data and not self._cha_data:
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
        speed = max(10, self._preview_speed.get())
        self._preview_job = self.root.after(speed, self._preview_tick)

    def _compute_layer_frame(self, L, tick):
        """按 sub_4434BC 语义计算当前帧号:
          start_delay (+44): 先倒数; 期间不播放
          tick_interval (+42): 每积累此值 tick 翻帧 (0 视作 1)
          first..last (+34..+36): 播放区间
          loop_behavior (+38): -1 回到 first, -2 停止, ≥0 跳到该帧
        返回 (cur_frame, stopped)"""
        start_delay = L[22]
        tick_interval = L[21]
        first = L[17]
        last = L[18]
        loop = L[19]

        if start_delay > 0:
            if tick < start_delay:
                return first, False
            tick -= start_delay

        step = max(1, tick_interval)
        frame_adv = tick // step
        span = max(1, last - first + 1)

        if loop == -1:
            return first + (frame_adv % span), False
        if loop == -2:
            if frame_adv >= span:
                return last, True
            return first + frame_adv, False
        if loop >= 0:
            if frame_adv < span:
                return first + frame_adv, False
            rem = frame_adv - span
            tail = max(1, last - loop + 1)
            return loop + (rem % tail), False
        return first + (frame_adv % span), False

    def _preview_redraw(self):
        c = self._preview_canvas
        c.delete("all")

        if self._editing_idx is None:
            return
        if not self._ani_data and not self._cha_data:
            c.create_text(200, 100,
                          text="未加载 JVG\n请先 文件 → 加载 TKS 目录",
                          fill="#888", font=("", 11))
            return

        direction = self._preview_dir_var.get()
        layers = self._preview_active_layers(direction)
        if not layers:
            c.create_text(200, 100, text=f"方向 {direction}: 无活跃图层",
                          fill="#888", font=("", 11))
            return

        tick = self._preview_tick_idx
        sprites = []
        all_x, all_y = [], []
        for slot, eff_dir, L in layers:
            v = self._preview_vis_vars.get(slot)
            if v is not None and not v.get():
                continue
            src = 'cha' if L[0] == 1 else 'ani'
            pk = L[1]
            jvg = self._cha_data if src == 'cha' else self._ani_data
            if jvg is None or pk < 0 or pk >= len(jvg.blocks):
                continue
            blk = jvg.blocks[pk]
            n_frames = blk.frame_count
            if n_frames <= 0:
                continue

            cur_abs, stopped = self._compute_layer_frame(L, tick)
            if L[2] == 4:
                cur_abs += L[16] * eff_dir
            cur_abs = cur_abs % n_frames if n_frames > 0 else 0
            frame = blk.frames[cur_abs]

            ox = L[3 + eff_dir]
            oy = L[7 + eff_dir]
            spr_l = frame.x_off + ox
            spr_t = frame.y_off + oy
            spr_r = spr_l + frame.width - 1
            spr_b = spr_t + frame.height - 1
            all_x.extend([spr_l, spr_r, -ox])
            all_y.extend([spr_t, spr_b, -oy])
            sprites.append((slot, eff_dir, L, src, blk, cur_abs, frame,
                            ox, oy, spr_l, spr_t, spr_r, spr_b, stopped))

        if not sprites:
            c.create_text(200, 100,
                          text=f"方向 {direction}: 无可渲染帧\n(检查图层可见性)",
                          fill="#888", font=("", 11))
            return

        bbox_l, bbox_r = min(all_x), max(all_x)
        bbox_t, bbox_b = min(all_y), max(all_y)
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

        ox_c, oy_c = to_cv(0, 0)
        c.create_line(ox_c - 16, oy_c, ox_c + 16, oy_c,
                      fill='#00ff00', width=2)
        c.create_line(ox_c, oy_c - 16, ox_c, oy_c + 16,
                      fill='#00ff00', width=2)
        c.create_text(ox_c + 18, oy_c + 4, text="原点", fill='#0f0',
                      font=("Consolas", 7), anchor=tk.NW)

        scaled_cache = []
        slot_colors = ['#4488ff', '#ff8844', '#44ff88', '#ff44ff',
                       '#ffff44', '#44ffff', '#ff8888', '#88ff88']
        info = [f"方向{direction} | 可见{len(sprites)}图层 | Tick:{tick}"]

        for sp in sprites:
            (slot, eff_dir, L, src, blk, cur_abs, frame,
             ox, oy, spr_l, spr_t, spr_r, spr_b, stopped) = sp

            pk = L[1]
            tup = self._preview_get_frame(src, pk, cur_abs)
            if not tup:
                continue
            img, _f, _blk = tup

            cx, cy = to_cv(spr_l, spr_t)
            nw = max(1, int(frame.width * scale))
            nh = max(1, int(frame.height * scale))
            color = slot_colors[(slot - 1) % len(slot_colors)]

            if nw == frame.width and nh == frame.height:
                c.create_image(cx, cy, image=img, anchor=tk.NW)
            else:
                try:
                    pal_rgb = blk.palette.to_rgb888()
                    rgba = bytearray(frame.width * frame.height * 4)
                    for py in range(frame.height):
                        base = py * frame.width
                        for px in range(frame.width):
                            p = base + px
                            if p < len(frame.alpha) and frame.alpha[p] == 0:
                                continue
                            idx = (frame.pixels[p]
                                   if p < len(frame.pixels) else 0)
                            o = p * 4
                            rgba[o] = pal_rgb[idx * 3]
                            rgba[o + 1] = pal_rgb[idx * 3 + 1]
                            rgba[o + 2] = pal_rgb[idx * 3 + 2]
                            rgba[o + 3] = 255
                    pil_img = Image.frombytes(
                        'RGBA', (frame.width, frame.height), bytes(rgba))
                    pil_img = pil_img.resize((nw, nh), Image.NEAREST)
                    stk = ImageTk.PhotoImage(pil_img)
                    scaled_cache.append(stk)
                    c.create_image(cx, cy, image=stk, anchor=tk.NW)
                except Exception:
                    c.create_image(cx, cy, image=img, anchor=tk.NW)

            rx, ry = to_cv(spr_r, spr_b)
            c.create_rectangle(cx, cy, rx + 1, ry + 1,
                               outline=color, width=1)
            c.create_text(cx + 2, cy + 2, text=f"#{slot}",
                          fill=color, font=("Consolas", 6), anchor=tk.NW)

            info.append(
                f"  #{slot} src={src} blk={pk} t={L[0]} dir={eff_dir} "
                f"f={cur_abs+1}/{blk.frame_count} "
                f"off=({ox:+d},{oy:+d}) "
                f"int={L[21]} delay={L[22]} "
                f"[{L[17]}..{L[18]}] loop={L[19]}"
                f"{' [STOP]' if stopped else ''}")

        self._preview_scaled_cache = scaled_cache
        for li, line in enumerate(info[:14]):
            c.create_text(8, 8 + li * 14, text=line, fill="#0f0",
                          font=("Consolas", 8), anchor=tk.NW)

    def _on_close(self):
        self._preview_stop()
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = [
            "TKAct.dat 字段语义 v2.0 (基于 sub_4434BC 反编译)",
            "",
            f"【文件结构】{ACT_ENTRY_COUNT} 条 × {ACT_ENTRY_SIZE} 字节 "
            f"= {ACT_DECOMPRESSED} 字节",
            "  每条 = 方向表[32B] + 条目级参数[48B] + 8图层×80B + 尾部[64B]",
            "",
            "【方向表 (bytes 0-31)】",
            "  4 方向 × 8 字节, 每字节 = 1-based 图层号 (0=空)",
            "  sub_4434BC: v22[8*v33+i] 依次渲染, 后画的在上层 (z-order)",
            "  约束: v33 ∈ [0,3], 否则 +2*v34+6 会越界侵入 Y 数组",
            "",
            "【图层 × 8 (各 80 字节, 40 int16)】",
        ]
        for grp_name, fields in FIELD_GROUPS:
            lines.append(f"  — {grp_name} —")
            for (fn, idx, label, _, comment) in fields:
                lines.append(f"    [{idx:2d}] {fn:<18s} {label}")
                lines.append(f"         {comment}")
            lines.append("")
        lines.append("【尾部 (bytes 720-783)】")
        lines.append("  16 对 (value, count), 疑似关键帧/触发表")
        lines.append("  未在 sub_4434BC 中引用, 用途未完全验证")

        dlg = tk.Toplevel(self.root)
        dlg.title("字段参考 (反编译来源)")
        dlg.geometry("760x640")
        dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines))
        tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKAct.dat 多图层 2D 精灵动画编辑器 v2.1\n\n"
            "修订依据: 逆向工作区/TKS_AI分析act_editor记录.md\n"
            "650 条 × 784 字节 = 509,600 字节\n\n"
            "关键变更:\n"
            "  · 前 32 字节 = 4 方向 × 8 字节 (非 8 组)\n"
            "  · layer_type = 贴图源+渲染阶段 (不区分主角/NPC/特效)\n"
            "  · type 1=Cha.jvg 2=Ani.jvg主段 3=Ani.jvg延迟段 4=锚点 5=结束\n"
            "  · tick_interval / start_delay 作为可编辑数据字段\n"
            "  · blend_mode / direction_mode / dir_frame_offset 语义命名\n"
            "  · 尾部按 16 对 (value, count) 展示\n\n"
            "逆向来源: sub_4434BC / sub_45408C / sub_45410C")


def main():
    root = tk.Tk()
    ActEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
