"""act_editor 数据层 — 常量/字段表/JVG 布局推断/act 读写 (T16 自 act_editor.py 迁出)。"""
import struct

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
    0: "0 空",
    1: "1 角色攻击动作 (Aa.jvg, 攻击者位置)",
    2: "2 技能攻击特效 (Af.jvg, 攻击者位置)",
    3: "3 受击特效     (Af.jvg, 受击方位置)",
    4: "4 命中锚点坐标 (不渲染)",  # sub_42F9C8
    5: "5 全屏特效     (屏幕中心 320,300)",
}

BLEND_MODE_LABELS = {
    0: "0 正常",
    1: "1 闪烁/染色",
    2: "2 加法/发光",
    3: "3 减法/压暗",
    4: "4 亮度融合",
    5: "5 水平翻转",
}

DIRECTION_MODE_LABELS = {
    0: "0 固定方向0",
    4: "4 随朝向变",
}

LOOP_BEHAVIOR_LABELS = {
    -1: "-1 (0xFFFF) 循环到起始帧",
    -2: "-2 (0xFFFE) 停止本图层",
}

MOVE_MODE_LABELS = {
    0: "0 无",
    1: "1 跟随移动",
    2: "2 四方来回",
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

# 条目级参数区在 UI 上的网格列数（共 24 项，4 列 → 6 行）
PARAM_GRID_COLUMNS = 4

# 条目级参数字段说明 (entry bytes 32-79, int16[16..39])。
# 这里只保存显示名称和提示，不参与二进制编解码；索引与原版寻址保持不变。
PARAM_FIELD_INFO = {
    16: ("保留字段[16]", "原版逆向代码中未发现该字段的有效引用。"),
    17: ("保留字段[17]", "原版逆向代码中未发现该字段的有效引用。"),
    18: ("动画总时长", "动画播放的总时间（原版内部按 Tick 计数）；用于限制各次飘字的触发时间。"),
    19: ("当前播放时间（自动）", "原版自动维护的播放进度（内部按 Tick 计数）；开始播放时重置并递增，不需要手工配置。"),
    20: ("第1次飘字", "动画播放到这个时间时，显示第1次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    21: ("第2次飘字", "动画播放到这个时间时，显示第2次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    22: ("第3次飘字", "动画播放到这个时间时，显示第3次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    23: ("第4次飘字", "动画播放到这个时间时，显示第4次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    24: ("第5次飘字", "动画播放到这个时间时，显示第5次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    25: ("第6次飘字", "动画播放到这个时间时，显示第6次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    26: ("第7次飘字", "动画播放到这个时间时，显示第7次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
    27: ("第8次飘字", "动画播放到这个时间时，显示第8次飘字，并触发对应的伤害、恢复或其他效果；多个触发时间决定数值分几段显示。"),
}
for _idx in range(28, 40):
    PARAM_FIELD_INFO[_idx] = (
        f"保留字段[{_idx}]",
        "原版逆向代码中未发现该字段与飘字分段有关的有效引用。",
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
