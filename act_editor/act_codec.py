"""act_editor 数据层 — 常量/字段表/JVG 布局推断/act 读写 (T16 自 act_editor.py 迁出)。"""
import struct

# 预览/时间轴固定色 — 画布恒为深色系 (图像编辑器惯例) + 领域语义色
# (阶段 2 豁免: 主题无关领域色, 见 docs/PySide6样式体系整改方案.md)
PREVIEW_CANVAS_BG = "#1a1e27"        # 精灵预览画布底 (恒深色)
PEN_TRAJECTORY_GREEN = "#00ff00"    # 弹道轨迹绿
PEN_TRAJECTORY_RED = "#ff4444"      # 事件块红 (轨迹/命中)
BLOCK_SHADOW_BG = "#442222"         # 事件块阴影底
BLOCK_SHADOW_BORDER = "#884444"     # 事件块阴影边
SELECT_RED = "#e74c3c"              # 选中框/时间指针红
GUIDE_BLUE = "#3498db"              # 对齐参考虚线蓝
STMT_INCOMPLETE_COLOR = "#CC3333"   # 语句表: 原版未完成 (红)
STMT_UNKNOWN_COLOR = "#CC8800"      # 语句表: 未知 (橙)
STMT_HAS_DATA_COLOR = "#228B22"     # 语句表: 有数据 (绿)
STMT_NO_DATA_COLOR = "#AAAAAA"      # 语句表: 无数据 (灰)
# 图层槽位分类色 (预览外框与图层列表共用)
SLOT_COLORS = ["#4488ff", "#ff8844", "#44ff88", "#ff44ff",
               "#ffff44", "#44ffff", "#ff8888", "#88ff88"]

# ============================================================
# 常量
# ============================================================

ACT_ENTRY_SIZE = 784
ACT_ENTRY_COUNT = 650
ACT_LAYER_SIZE = 80
ACT_MAX_LAYER = 8
PREVIEW_ENEMY_X = 160
ACT_HEADER_SIZE = 80
ACT_PARAM_OFFSET = 32
ACT_TAIL_OFFSET = 720
ACT_TAIL_SIZE = 64
ACT_DECOMPRESSED = 509600

DIRECTION_LABELS = ["方向0 (右上)", "方向1 (右下)", "方向2 (左下)", "方向3 (左上)"]
DIRECTION_SHORT = ["右上", "右下", "左下", "左上"]

LAYER_TYPE_LABELS = {
    0: "0 不使用",
    1: "1 人物动作",
    2: "2 攻击方特效",
    3: "3 受击方特效",
    4: "4 位置标记（不显示画面）",  # sub_42F9C8
    5: "5 全屏特效（屏幕中央）",
}

BLEND_MODE_LABELS = {
    0: "0 正常显示",
    1: "1 闪烁变色",
    2: "2 发光叠加",
    3: "3 压暗/阴影",
    4: "4 按亮度半透明",
    5: "5 左右镜像",
}

DIRECTION_MODE_LABELS = {
    0: "0 固定画面方向",
    4: "4 跟随人物朝向",
}

LOOP_BEHAVIOR_LABELS = {
    -1: "-1 循环播放",
    -2: "-2 播完隐藏",
}

MOVE_MODE_LABELS = {
    0: "0 不自动移动",
    1: "1 跟着角色移动",
    2: "2 来回飘动",
}

FONT_FAMILY = 'Microsoft YaHei UI'
FONT_SIZE = 9
FONT_SIZE_S = 8
W_INPUT = 10
W_INPUT_S = 6

# ============================================================
# JVG 轻量帧数探针
# ============================================================

_JVG_LAYOUT_HINTS = [
    (28, 4, 7),
    (32, 4, 8),
    (36, 4, 9),
    (48, 4, 12),
    (40, 4, 10),
    (44, 4, 11),
    (24, 4, 6),
    (20, 4, 5),
    (4,  4, 1),
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
# 图层字段定义
# ============================================================

FIELD_GROUPS = [
    ("来源", [
        ("layer_type",       0,  "资源与渲染类型", W_INPUT,
         "图层类型\n"
         "  1 → 主角动作库 (Aa.jvg)\n"
         "  其他 → 特效/物件库 (Af.jvg)\n"
         "  渲染阶段: <3 主段 / 3 延迟段 / 4 锚点 / 5 结束"),  # sub_4434BC: *(_WORD*)(+0)
        ("jvg_block_index",  1,  "JVG 资源块索引", W_INPUT,
         "JVG 资源块编号"),  # sub_4434BC: +2 → sub_45410C
    ]),
    ("动画帧范围", [
        ("first_frame",      17, "起始帧",     W_INPUT,
         "动画起始帧号"),  # sub_4434BC L595: +34
        ("last_frame",       18, "终止帧",     W_INPUT,
         "动画终止帧号 (到达后触发循环或停止)"),  # sub_4434BC L593: +36
        ("loop_behavior",    19, "结束行为",   W_INPUT,
         "动画到达终止帧后的行为: -1 循环 / -2 停止 / ≥0 跳转到指定帧"),  # sub_4434BC L603: +38
    ]),
    ("动画时序 ★", [
        ("tick_interval",    21, "每帧停留 Tick ★", W_INPUT,
         "每帧停留的 Tick 数; 计数器达到此值时切换到下一帧"),  # sub_4434BC L574: +42
        ("start_delay",      22, "播放启动延迟 ★", W_INPUT,
         "播放启动前的延迟 Tick; 非0时等待递减至0才开始"),  # sub_4434BC L248/L566: +44
    ]),
    ("渲染", [
        ("blend_mode",       11, "图像混合模式", W_INPUT,
         "混合模式 (6种渲染方式)"),  # sub_4434BC L320-339: +22
        ("blend_param",      12, "混合参数",   W_INPUT,
         "混合参数 (颜色/透明度/随机种等)"),  # sub_4434BC: +24
        ("blend_param_step", 13, "混合参数步进", W_INPUT,
         "混合参数步进 (每翻帧的累加量)"),  # sub_4434BC L613: +26
    ]),
    ("方向位移 (方向 0~3)", [
        ("x_off_d0",         3,  "方向0 X偏移", W_INPUT_S, "方向0 的 X 偏移"),
        ("x_off_d1",         4,  "方向1 X偏移", W_INPUT_S, "方向1 的 X 偏移"),
        ("x_off_d2",         5,  "方向2 X偏移", W_INPUT_S, "方向2 的 X 偏移"),
        ("x_off_d3",         6,  "方向3 X偏移", W_INPUT_S, "方向3 的 X 偏移"),
        ("y_off_d0",         7,  "方向0 Y偏移", W_INPUT_S, "方向0 的 Y 偏移"),
        ("y_off_d1",         8,  "方向1 Y偏移", W_INPUT_S, "方向1 的 Y 偏移"),
        ("y_off_d2",         9,  "方向2 Y偏移", W_INPUT_S, "方向2 的 Y 偏移"),
        ("y_off_d3",         10, "方向3 Y偏移", W_INPUT_S, "方向3 的 Y 偏移"),
    ]),
    ("朝向与帧选择", [
        ("direction_mode",   2,  "朝向模式",   W_INPUT,
         "方向模式: 4=随朝向变化 / 其他=固定方向0"),  # sub_4434BC L308: +4
        ("dir_frame_offset", 16, "朝向帧偏移", W_INPUT,
         "按朝向偏移帧号"),  # sub_4434BC L309: +32
    ]),
    ("自动移动", [
        ("move_mode",        25, "自动移动模式", W_INPUT,
         "移动模式: 1=跟随 / 2=四方往返"),  # sub_4434BC L577-591: +50
        ("step_value",       26, "自动移动步进值", W_INPUT_S, "自动移动使用的步进值"),
        ("step_delta",       27, "自动移动步进增量", W_INPUT_S, "自动移动使用的步进增量"),
    ]),
    ("运行时工作字段 (只读, 文件=0)", [
        ("_rt_frame_base",   14, "运行时帧基准", W_INPUT_S, "运行时工作字段; 原版文件值为0"),  # sub_4434BC: +28
        ("_rt_cur_frame",    15, "运行时当前帧", W_INPUT_S, "运行时工作字段; 原版文件值为0"),  # sub_4434BC: +30
        ("_rt_20",           20, "运行时字段[20]", W_INPUT_S, "运行时工作字段; 原版文件值为0"),
        ("_rt_counter",      23, "运行时计数器", W_INPUT_S, "运行时工作字段; 原版文件值为0"),  # sub_4434BC: +46
        ("_rt_dir_sign",     24, "运行时方向符号", W_INPUT_S, "运行时工作字段; 原版文件值为0"),  # sub_4434BC: +48
    ]),
    ("保留 / 未知", [
        (f"_res_{i}", i, f"保留字段[{i}]", W_INPUT_S, f"int16[{i}] 保留字段 (未使用)")  # sub_4434BC 未引用
        for i in range(28, 40)
    ]),
]

# 条目级参数区在 UI 上的网格列数。
PARAM_GRID_COLUMNS = 4

# 条目级参数字段说明 (entry bytes 32-79, int16[0..23])。
# 这里只保存显示名称和提示，不参与二进制编解码；索引与原版寻址保持不变。
#
# 原版关键字段：
#   int16[2]  = byte +36       word_9D039E 动画总帧数
#   int16[4..11] = byte +40..55 word_9D03A2[8] 命中/飘字触发帧表
#
# 旧版 UI 曾以 [18]/[20..27] 显示这些字段，并通过 param_idx - 16
# 映射到实际的 [2]/[4..11]。当前 UI 直接使用真实索引。
PARAM_FIELD_INFO = {
    2: ("动画总时长",
        "原版 word_9D039E（定义 +36）：攻击演出主循环的总帧数。"),
}
for _slot in range(8):
    PARAM_FIELD_INFO[4 + _slot] = (
        f"第{_slot + 1}次数字出现",
        f"原版 word_9D03A2[{_slot}]（定义 +{40 + _slot * 2}）："
        f"第 {_slot + 1} 段伤害/恢复飘字的触发帧。",
    )
for _idx in range(24):
    if _idx not in PARAM_FIELD_INFO:
        PARAM_FIELD_INFO[_idx] = (
            f"保留字段[{_idx}]",
            "原版逆向代码中未发现该字段的有效引用。",
        )

ALL_FIELDS = [f for _, grp in FIELD_GROUPS for f in grp]

READONLY_KEYS = {f[0] for f in ALL_FIELDS
                 if f[0].startswith('_rt') or f[0].startswith('_res')}


# ============================================================
# 数据加载 / 保存 (100% 原始逻辑)
# ============================================================

def load_act(fp):
    """加载 TKAct.dat (原始文件, 非 LZSS)"""
    with open(fp, 'rb') as f:
        raw = f.read()
    if not raw or len(raw) % ACT_ENTRY_SIZE:
        raise ValueError(
            f"文件大小 {len(raw)} 不是 {ACT_ENTRY_SIZE} 字节的整数倍, 无法按 TKAct 记录解析")
    entry_count = len(raw) // ACT_ENTRY_SIZE
    entries = []
    for i in range(entry_count):
        off = i * ACT_ENTRY_SIZE
        data = raw[off:off + ACT_ENTRY_SIZE]

        dirs = []
        for d in range(4):
            dirs.append(list(data[d * 8: d * 8 + 8]))

        param16 = list(struct.unpack_from('<24h', data, ACT_PARAM_OFFSET))

        layers = []
        for s in range(1, ACT_MAX_LAYER + 1):
            lo = s * ACT_LAYER_SIZE
            layers.append(list(struct.unpack_from('<40h', data, lo)))

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
    buf = bytearray(len(entries) * ACT_ENTRY_SIZE)
    for i, entry in enumerate(entries):
        entry['index'] = i
        off = i * ACT_ENTRY_SIZE

        for d in range(4):
            b = entry['dirs'][d]
            buf[off + d * 8: off + d * 8 + 8] = bytes(
                v & 0xFF for v in b)

        struct.pack_into('<24h', buf, off + ACT_PARAM_OFFSET,
                         *entry['param16'])

        for s in range(ACT_MAX_LAYER):
            lo = off + (s + 1) * ACT_LAYER_SIZE
            struct.pack_into('<40h', buf, lo, *entry['layers'][s])

        struct.pack_into('<32h', buf, off + ACT_TAIL_OFFSET, *entry['tail'])

    if len(buf) % ACT_ENTRY_SIZE:
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
