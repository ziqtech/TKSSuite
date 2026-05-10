#!/usr/bin/env python3
"""
TKAct.dat 多图层 2D 精灵动画编辑器 v2.3
=============================================================
修订依据:
  - v2.0/v2.1: 逆向工作区/TKS_AI分析act_editor记录.md
  - v2.2    : 逆向工作区/TKS_AI修正TKAct.dat实际JVG绑定.md
  - v2.3    : 尾部 64B 逆向确认为"音效触发表"
              (sub_4434BC L111-119 预加载 + L627-636 触发)

  v2.0 修正要点:
    1. 前 32 字节 = 4 方向 × 8 字节 的图层绘制顺序 (z-order)
    2. 8 个槽位即 8 个图层 (layer), 按语义分组编辑
    3. 字段按语义命名并按功能分组 (来源/帧范围/时序/渲染/位移/…)
    4. 尾部 64B 按 16 对 (value, count) 显示
    5. 预览节拍遵循 tick_interval / start_delay / [first,last] 语义

  v2.2 关键修正 (sub_4434BC + sub_42FEE0 反编译证据):
    · layer_type == 1 → Aa.jvg  (dword_951924, 主角动作库)
    · layer_type != 1 → Af.jvg  (dword_951930, 特效/物件库)
    · Cha.jvg 走 sub_458020(dword_755AF0, ...) 直接绘制角色基础行走图,
      不经 ACT 图层系统, 故不再作为编辑器资源加载.
    · Ani.jvg 未被 sub_4434BC 引用, 移出 ACT 编辑器视野.

  v2.3 新增 (sub_451780 + sub_451C38 反编译证据):
    · 尾部 16 对 = 音效触发表: (sound_id, trigger_tick)
      · sub_4434BC L111-119  执行前预加载 16 个音效  (sub_451780(1))
      · sub_4434BC L627-636  每 tick 检查 v5[1] == word_9D03A0 → 播放
    · 音效实际来源 = SWS.GRP (sub_451780 L48-61):
      · A2C22C == 1 → sub_4B22A8(..., *(+16)+4*v19, 0)  从 GRP 按 sid 取
      · A2C22C == 0 → sub_4B2ECC(..., "sound\\%04d.wav", v19)  文件 fallback
      · 实测 Sound/ 目录不完整 (仅 29 文件, 但 sid 最高达 95+),
        必须从 SWS.GRP 读取; Sound/ 仅作历史兜底.
    · SWS.GRP 结构 (SWS.IDX 索引, 每段 = RIFF WAV):
      · IDX = 连续 <I 偏移表, 末尾 = 文件大小
      · 506 段 (SWS.IDX 507 偏移), 每段可直接作为 WAV 字节流播放
    · 预览画面:
      · 不再每帧重算 bbox, 改为条目级固定 bbox (切条目时算一次)
      · 原点 (0,0) 固定在画布中央偏下 (模拟角色脚底锚点)
      · 切换方向/播放不会造成画面跳动
    · 预览 tick 推进时自动按 trigger_tick 触发 SWS.GRP 音效播放

文件结构 (784 字节/条, 共 650 条 = 509,600 字节):
  [0-31]    方向表: 4 方向 × 8 字节, 每字节为 1-based 图层号 (0=空)
  [32-79]   条目级参数区 (24 int16, 多数预留/未知)
  [80-719]  图层 × 8 (各 80 字节 = 40 int16)
  [720-783] 尾部 = 音效触发表 16 对 × (sound_id, trigger_tick) × int16

逆向关键函数:
  sub_411624: sub_452544(aTkactDat, &unk_9539CA, 509600)  初始化载入
  sub_452544: 原始 I/O 读取 (非 LZSS)
  sub_4434BC: 动画运行时处理 (本编辑器语义的主要证据来源)
  sub_45408C: 帧基址计算
  sub_45410C: param_key 查表
  sub_451780: 加载 sound\\%04d.wav → DirectSound 缓冲 (a2 = sound_id)
  sub_451C38: 播放已加载音效缓冲 (eax = 资源表, edx = sound_id)
"""

import os, sys, struct, tkinter as tk
from tkinter import ttk, messagebox, filedialog

HAS_PIL = False
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass


# ============================================================
# 音效播放 (Windows MCI + SWS.GRP 资源包)
#   sub_451780 关键逻辑 (L48-61):
#     if dword_A2C22C == 1:
#         sub_4B22A8(*(+28), *(+16)+4*v19, 0)   # 从 GRP 资源包按 sid 取
#     elif dword_A2C22C == 0:
#         sub_4B2ECC(..., "sound\\%04d.wav", v19)  # 文件路径 fallback
#   说明: 实际游戏运行时走 A2C22C=1 分支, 从 SWS.GRP 读 WAV;
#         Sound/ 目录仅作历史 fallback, 不完整 (只有 29 个音效,
#         而 TKAct 里 sid 最高出现 95+, 必须走 SWS.GRP).
#   SWS.GRP 结构 (grp_editor.py 验证):
#     - SWS.IDX = 连续 <I 偏移表, 最后一个 = 文件大小
#     - num_sections = len(idx) - 1
#     - 每 section 直接就是一个 RIFF WAV 字节流
# ============================================================
_mci_alias_counter = [0]
_sws_tempfiles = []  # 进程退出时清理


class _SWSGrp:
    """SWS.GRP 音效资源包最小读取器 (按需流式读取, 不一次性载入).
    get_wav(sid) → 返回原始 WAV 字节或 None.
    extract_to_temp(sid) → 写到临时 .wav 文件供 MCI 播放, 返回路径或 None.
    """

    def __init__(self, grp_path, idx_path):
        self.grp_path = grp_path
        self.idx_path = idx_path
        self.offsets = []
        self._wav_cache = {}
        self._temp_cache = {}

    def load_index(self):
        with open(self.idx_path, 'rb') as f:
            data = f.read()
        if len(data) < 8 or len(data) % 4:
            return 0
        self.offsets = [struct.unpack_from('<I', data, i)[0]
                        for i in range(0, len(data), 4)]
        # 合法性校验: 末尾必须 = grp 文件大小
        try:
            grp_sz = os.path.getsize(self.grp_path)
        except OSError:
            return 0
        if not self.offsets or self.offsets[-1] != grp_sz:
            self.offsets = []
            return 0
        return self.section_count

    @property
    def section_count(self):
        return max(0, len(self.offsets) - 1)

    def get_wav(self, sid):
        if sid < 0 or sid >= self.section_count:
            return None
        cached = self._wav_cache.get(sid)
        if cached is not None:
            return cached
        start = self.offsets[sid]
        end = self.offsets[sid + 1]
        if end <= start:
            return None
        try:
            with open(self.grp_path, 'rb') as f:
                f.seek(start)
                data = f.read(end - start)
        except OSError:
            return None
        # 校验 RIFF/WAVE 头
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            return None
        # 最多缓存 32 条 (防内存膨胀)
        if len(self._wav_cache) < 32:
            self._wav_cache[sid] = data
        return data

    def extract_to_temp(self, sid):
        """把 sid 对应的 WAV 写到临时文件, 返回路径 (MCI 需要文件路径)."""
        if sid in self._temp_cache and os.path.exists(self._temp_cache[sid]):
            return self._temp_cache[sid]
        data = self.get_wav(sid)
        if not data:
            return None
        import tempfile
        fd, path = tempfile.mkstemp(prefix=f'tkact_sws_{sid:04d}_',
                                    suffix='.wav')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
        except OSError:
            return None
        self._temp_cache[sid] = path
        _sws_tempfiles.append(path)
        return path

    def wav_info(self, sid):
        """返回简要信息 (ch, sr, bits, duration_s) 或 None."""
        data = self.get_wav(sid)
        if not data:
            return None
        try:
            import io as _io
            import wave as _wave
            with _wave.open(_io.BytesIO(data), 'rb') as wf:
                nf = wf.getnframes()
                sr = wf.getframerate()
                return (wf.getnchannels(), sr, wf.getsampwidth() * 8,
                        nf / sr if sr > 0 else 0.0)
        except Exception:
            return None


def _mci_send(cmd):
    """winmm.dll mciSendStringW 包装; 失败返回 (errno, err_msg)"""
    if sys.platform != 'win32':
        return (-1, 'not-windows')
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        rc = winmm.mciSendStringW(ctypes.c_wchar_p(cmd), None, 0, None)
        if rc != 0:
            buf = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(rc, buf, 256)
            return (rc, buf.value)
        return (0, '')
    except Exception as e:
        return (-1, str(e))


def _mci_play_async(path):
    """异步播放 wav 文件, 返回 alias; 失败返回 None"""
    if not path or not os.path.exists(path):
        return None
    _mci_alias_counter[0] += 1
    alias = f"tkact_snd_{_mci_alias_counter[0]}"
    _mci_send(f'close {alias}')
    rc, msg = _mci_send(f'open "{path}" type waveaudio alias {alias}')
    if rc != 0:
        rc, msg = _mci_send(f'open "{path}" alias {alias}')
        if rc != 0:
            return None
    rc, msg = _mci_send(f'play {alias}')
    if rc != 0:
        _mci_send(f'close {alias}')
        return None
    return alias


def _mci_close(alias):
    if alias:
        _mci_send(f'stop {alias}')
        _mci_send(f'close {alias}')


def _cleanup_sws_tempfiles():
    for p in list(_sws_tempfiles):
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass
    _sws_tempfiles.clear()


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
#   引擎按 "==1 vs !=1" 切换贴图源:
#     type == 1 : v32 = dword_951924  →  Aa.jvg  (主角动作库)
#     type != 1 : v32 = dword_951930  →  Af.jvg  (特效/物件库)
#   渲染阶段:
#     type <  3 : 主渲染段 (sub_4434BC L305)
#     type == 3 : 延迟渲染段 (sub_4434BC L402), 仍用 Af.jvg
#     type == 4 : 坐标锚点 (sub_42F9C8), 不渲染
#     type == 5 : 结束标记 (v28=1), 不渲染
# ⚠ 历史纠错: v2.1 曾把贴图源误标为 Cha.jvg / Ani.jvg;
#   实测 sub_42FEE0 显示 dword_951924 = Aa.jvg, dword_951930 = Af.jvg.
#   Cha.jvg 由 sub_458020(dword_755AF0, ...) 直接绘制, 不经 ACT 图层.
LAYER_TYPE_LABELS = {
    0: "0 空",
    1: "1 Aa.jvg 主角动作 · 主段",
    2: "2 Af.jvg 特效/物件 · 主段",
    3: "3 Af.jvg 特效/物件 · 延迟段",
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
# (基于 Aa.jvg/Af.jvg 实测分布: Aa 全是 4 的倍数; Af 多为单向)
_JVG_LAYOUT_HINTS = [
    (28, 4, 7),   # ★ Aa 最常见: 4 向 × 7 帧
    (32, 4, 8),   # Aa 次常见: 4 向 × 8 帧
    (36, 4, 9),   # Aa: 4 向 × 9 帧
    (48, 4, 12),  # Aa: 4 向 × 12 帧
    (40, 4, 10),  # Aa: 4 向 × 10 帧
    (44, 4, 11),  # Aa: 4 向 × 11 帧
    (24, 4, 6),   # Aa: 4 向 × 6 帧
    (20, 4, 5),   # Af/Aa: 4 向 × 5 帧
    (4,  4, 1),   # 4 向纯静态
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
# Aa.jvg / Af.jvg 块结构约定 (实测分布, 非 sub_4434BC 自身规定)
# ============================================================
# Aa.jvg (dword_951924, 158 blocks, 40 MB):
#   主角/角色 "ACT 扩展动作库" —— 下蹲/出剑/抬手/治疗/倒地/
#   起身/蓄力/挥拳 等相对于 Cha.jvg 基础行走的附加姿势.
#   帧数分布 (占比前几位):
#     ┌──────┬────────┬────────────────────────────┐
#     │ 总帧 │ 次数   │ 典型语义 (4 方向)          │
#     │  28  │  25    │ 4 向 × 7 帧 ★              │
#     │  32  │  21    │ 4 向 × 8 帧                │
#     │  36  │  17    │ 4 向 × 9 帧                │
#     │  48  │  14    │ 4 向 × 12 帧               │
#     │  40  │  12    │ 4 向 × 10 帧               │
#     │  44  │   9    │ 4 向 × 11 帧               │
#     │  24  │   8    │ 4 向 × 6 帧                │
#     └──────┴────────┴────────────────────────────┘
#   所有 block 帧数均为 4 的倍数 → 主角动作均为 4 方向结构.
#
# Af.jvg (dword_951930, 367 blocks, 347 MB):
#   特效/物件/刀光/箭矢/爆点/飞行物 等通用动画池.
#   帧数分布 (前几位): 20/24/17/19/28/15/16/18/7 ... 
#   大量非 4 倍数块 → 多数特效/物件为单方向动画,
#   ACT 数据里对应 direction_mode == 0 (固定方向 0).
#
# ⚠ Cha.jvg (dword_755AF0, 178 blocks) 的 "block 0=阴影, block 1=72帧
#   主角行走, block 2..=28帧 NPC 行走" 约定属于"地图角色基础渲染"系统,
#   由 sub_458020 按角色 base block 直接绘制, 与 TKAct 图层系统无关.
#   (编辑器不加载 Cha/Ani, 它们不是 ACT 消费资源)
#
# ⚠ ACT 引擎 sub_4434BC 方向表循环步长是 8 字节/方向, 前 32 字节仅容
#   纳 4 方向的绘制顺序, 故 v33 ∈ {0,1,2,3}. 哪怕 Aa 某块帧数=72 (不存在)
#   或 Af 某块为 8 方向结构, ACT 也只能驱动前 4 方向.
#
# ACT 侧的"帧片段"由三个字段组合决定, 与 JVG 块真实帧数解耦:
#   dir_frame_offset  方向间帧步长   (该块每方向帧数, 典型 7/8/5/9/1)
#   first_frame       方向内起始帧   (通常=0)
#   last_frame        方向内终止帧   (通常=dfo-1)
#
# 帧片段读取示例 (dirmode=4 随朝向变):
#   dfo=7 first=0 last=6  ⇒ 4 向×7 帧 (28 帧 Aa 块全取)
#   dfo=8 first=0 last=7  ⇒ 4 向×8 帧 (32 帧 Aa 块全取)
#   dfo=9 first=0 last=8  ⇒ 4 向×9 帧 (36 帧 Aa 块全取)
#   dfo=1 first=0 last=0  ⇒ 4 向×1 帧 (4 帧纯静态块全取)
# ============================================================

# ============================================================
# 图层字段定义 — 按"语义分组"组织, 每字段 = (key, int16_idx, 标签, 宽度, 描述)
# ★ 标记表示 v1.0 中错标的字段已纠正
# ============================================================

# 单字段元组结构: (key, int16_idx, label, width, tooltip)
FIELD_GROUPS = [
    ("来源", [
        ("layer_type",       0,  "类型",       W_INPUT,
         "sub_4434BC: *(_WORD*)(+0)\n"
         "  ==1 → Aa.jvg (dword_951924, 主角动作库)\n"
         "  !=1 → Af.jvg (dword_951930, 特效/物件库)\n"
         "  渲染阶段: <3 主段 / ==3 延迟段 / ==4 锚点 / ==5 结束"),
        ("jvg_block_index",  1,  "JVG 块号",    W_INPUT,
         "sub_4434BC: *(_WORD*)(+2) → sub_45410C 查表\n"
         "Aa.jvg (158块) 主角动作库, 帧数多为 4 倍数:\n"
         "  28(4×7,★) 32(4×8) 36(4×9) 48(4×12) 40(4×10) 44(4×11) 24(4×6)\n"
         "Af.jvg (367块) 特效/物件库, 多为单向动画:\n"
         "  常见 20/24/17/19/28/15/16/18/7 帧 (大量非 4 倍数)"),
    ]),
    ("帧范围", [
        ("first_frame",      17, "起始帧",     W_INPUT,
         "sub_4434BC L595: *(_WORD*)(+34)  动画起始帧号\n"
         "★ 此为'方向内相对帧号', 引擎按 dir_frame_offset × direction 再叠加\n"
         "  标准行走约定: =0 (即该方向静止姿)"),
        ("last_frame",       18, "终止帧",     W_INPUT,
         "sub_4434BC L593: *(_WORD*)(+36)  到达即触发循环/停止\n"
         "★ 方向内相对帧号; 典型值:\n"
         "  =0  纯静止  =dfo-1  跑满该方向全部帧 (如 28帧Aa块时=6, 32帧=7)"),
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
         "  =7 (28帧Aa块, 4向×7)  =8 (32帧Aa块, 4向×8)\n"
         "  =9 (36帧Aa块, 4向×9)  =12 (48帧Aa块, 4向×12)\n"
         "  =1 (4帧纯静态块)       =0 (固定方向 0, 无朝向步进)"),
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
        self.root.title("TKAct.dat 多图层 2D 精灵动画编辑器 v2.2")
        ico = os.path.join(os.path.dirname(__file__), '..', 'kon_editor',
                           'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1320x860")
        self.root.minsize(1080, 680)

        self.act_path = None
        self.aa_path = None      # Aa.jvg (layer_type==1 的贴图源)
        self.af_path = None      # Af.jvg (layer_type!=1 的贴图源)
        self.sound_dir = None    # TKS/Sound 目录 (legacy fallback, 可缺失)
        self.sws_grp = None      # _SWSGrp 实例 (sub_451780 A2C22C=1 分支)
        self.entries = []
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None

        # JVG 数据 (预览用, 完整解码)
        self._aa_data = None
        self._af_data = None
        self._jvg_cache = {}     # {(src, block, frame): PhotoImage}

        # JVG 轻量探针 (block 帧数列表)
        self._aa_counts = []
        self._af_counts = []

        # 预览状态
        self._preview_job = None
        self._preview_tick_idx = 0
        # 固定包围盒 (切换条目时算一次, 避免随方向/tick 抖动)
        #   {'l':..,'r':..,'t':..,'b':..}  世界坐标, 含原点(0,0)
        self._preview_bbox = None
        # 预览音效: 已触发 tick 集合 (防止同一 tick 反复播放)
        self._preview_played_ticks = set()
        # MCI 别名池: [(alias, 开始时间, 大致时长)] —— 由 _preview_stop 清理
        self._preview_sfx_aliases = []

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
                "  · 实际帧数 ← 从 Aa.jvg / Af.jvg 头部扫描得到\n"
                "  · 推断布局 ← 按 4 方向优先匹配得出\n"
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

    # -------- Tab: 尾部 (16 对) = 音效触发表 --------

    def _build_tail_ui(self):
        main = ttk.Frame(self.tail_frame, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="尾部 (bytes 720-783) = 音效触发表  16 对 × (sound_id, trigger_tick)\n"
                 "逆向证据: sub_4434BC L111-119 对 &unk_9D064A 逐对 sub_451780(1) 预加载;\n"
                 "          L627-636 每 tick 检查 v5[1] == word_9D03A0 时 sub_451C38(0) 播放.\n"
                 "音效路径: sound\\%04d.wav (sub_451780 L56); 实测目录为 .mp3 时编辑器自动兼容.\n"
                 "sound_id = 0 表示该对空位 (不触发).",
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

        ttk.Label(inner, text="#", font=FONT_B, width=3).grid(
            row=0, column=0, padx=2)
        ttk.Label(inner, text="sound_id", font=FONT_B, width=9).grid(
            row=0, column=1, padx=2)
        ttk.Label(inner, text="trigger_tick", font=FONT_B, width=11).grid(
            row=0, column=2, padx=2)
        ttk.Label(inner, text="", font=FONT_B, width=3).grid(
            row=0, column=3, padx=2)
        ttk.Label(inner, text="文件", font=FONT_B, width=20).grid(
            row=0, column=4, padx=4, sticky='w')
        ttk.Label(inner, text="原 int16", font=FONT_S,
                  foreground='#999').grid(row=0, column=5, padx=8, sticky='w')

        self._tail_vars = []      # 平铺 32 个 StringVar
        self._tail_file_lbls = []  # 每对的文件状态标签 (sound_id 变化时刷新)
        for pair in range(16):
            r = pair + 1
            ttk.Label(inner, text=f"{pair:02d}", font=FONT_S,
                      foreground='#666').grid(row=r, column=0, padx=2)
            v_var = tk.StringVar()
            c_var = tk.StringVar()
            self._tail_vars.append(v_var)   # 偶数: sound_id
            self._tail_vars.append(c_var)   # 奇数: trigger_tick
            id_ent = ttk.Entry(inner, textvariable=v_var, width=8,
                               font=FONT)
            id_ent.grid(row=r, column=1, padx=2)
            tick_ent = ttk.Entry(inner, textvariable=c_var, width=10,
                                 font=FONT)
            tick_ent.grid(row=r, column=2, padx=2)
            # 试听按钮
            btn = ttk.Button(inner, text="▶",
                             width=2,
                             command=lambda idx=pair: self._on_tail_preview(idx))
            btn.grid(row=r, column=3, padx=1)
            self._bind_tooltip(btn, "试听此 sound_id 对应的音效文件")
            # 文件状态标签
            fl = ttk.Label(inner, text="", font=FONT_S, foreground='#999',
                           anchor='w', width=24)
            fl.grid(row=r, column=4, padx=4, sticky='w')
            self._tail_file_lbls.append(fl)
            ttk.Label(inner, text=f"[{pair*2}], [{pair*2+1}]",
                      font=FONT_S, foreground='#AAA').grid(
                row=r, column=5, padx=8, sticky='w')
            # sound_id 变化时刷新文件标签
            v_var.trace_add('write',
                            lambda *a, idx=pair: self._refresh_tail_file_lbl(idx))

    def _refresh_tail_file_lbl(self, pair_idx):
        """根据 sound_id 刷新该对的文件标签 (优先 SWS.GRP, 回退 Sound/)"""
        if pair_idx >= len(self._tail_file_lbls):
            return
        lbl = self._tail_file_lbls[pair_idx]
        try:
            sid = int(self._tail_vars[pair_idx * 2].get() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            lbl.config(text="(空位)", foreground='#AAA')
            return
        # 优先走 SWS.GRP
        if self.sws_grp is not None:
            info = self.sws_grp.wav_info(sid)
            if info is not None:
                ch, sr, bits, dur = info
                lbl.config(
                    text=(f"SWS#{sid:03d}  {ch}ch {sr}Hz {bits}bit "
                          f"{dur:.2f}s"),
                    foreground='#093')
                return
            if sid >= self.sws_grp.section_count:
                lbl.config(
                    text=f"SWS#{sid}  ✗ 超出段数({self.sws_grp.section_count})",
                    foreground='#C33')
                return
            lbl.config(text=f"SWS#{sid:03d}  (非 WAV 段)", foreground='#C60')
            return
        # 回退到 Sound/
        if self.sound_dir:
            base = f"{sid:04d}"
            for ext in ('.wav', '.WAV', '.mp3', '.MP3'):
                p = os.path.join(self.sound_dir, base + ext)
                if os.path.exists(p):
                    lbl.config(text=os.path.basename(p), foreground='#093')
                    return
            lbl.config(text=f"sound\\{sid:04d}.wav  ✗ 未找到",
                       foreground='#C33')
            return
        lbl.config(text=f"SWS#{sid:04d}  (未加载 TKS 目录)",
                   foreground='#C60')

    def _resolve_sound_path(self, sid):
        """解析 sound_id → 可播放的 .wav 本地路径.
        优先 SWS.GRP (提取到临时文件), 回退 Sound/ 目录. 返回 None 表示缺失."""
        if sid <= 0:
            return None
        if self.sws_grp is not None:
            p = self.sws_grp.extract_to_temp(sid)
            if p:
                return p
        if self.sound_dir:
            base = f"{sid:04d}"
            for ext in ('.wav', '.WAV', '.mp3', '.MP3'):
                p = os.path.join(self.sound_dir, base + ext)
                if os.path.exists(p):
                    return p
        return None

    def _on_tail_preview(self, pair_idx):
        """试听按钮: 播放该对 sound_id 指向的音效"""
        try:
            sid = int(self._tail_vars[pair_idx * 2].get() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            self.status_var.set(f"尾部 #{pair_idx:02d}: sound_id=0 空位, 无音效")
            return
        if self.sws_grp is None and not self.sound_dir:
            messagebox.showinfo(
                "未加载音效源",
                "请先通过 文件 → 加载 TKS 目录 来定位 SWS.GRP")
            return
        p = self._resolve_sound_path(sid)
        if not p:
            src = "SWS.GRP" if self.sws_grp is not None else "Sound/"
            self.status_var.set(f"未找到音效 sid={sid} (来源: {src})")
            return
        alias = _mci_play_async(p)
        if alias is None:
            self.status_var.set(f"播放失败: sid={sid}")
        else:
            # 判断来源: SWS 提取的文件名会带 'tkact_sws_' 前缀
            src_tag = "SWS" if "tkact_sws_" in os.path.basename(p) else "Sound/"
            self.status_var.set(f"▶ sid={sid} (来自 {src_tag})")

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
        # Aa.jvg / Af.jvg 才是 ACT 图层的实际贴图源
        # 先尝试常见大小写组合 (Windows 文件系统不区分, 但用 exists() 更安全)
        def _pick(*names):
            for n in names:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    return p
            return None
        aa = _pick("Aa.jvg", "Aa.JVG", "aa.jvg")
        af = _pick("Af.jvg", "Af.JVG", "af.jvg")
        # Sound 目录 (sub_451780 fallback 路径, 实际资源不完整)
        sd = None
        for name in ("Sound", "sound", "SOUND"):
            p = os.path.join(d, name)
            if os.path.isdir(p):
                sd = p
                break
        # SWS.GRP + SWS.IDX = 实际运行时音效源 (sub_451780 A2C22C=1 分支)
        sws_path = _pick("SWS.GRP", "SWS.grp", "sws.grp")
        swi_path = _pick("SWS.IDX", "SWS.idx", "sws.idx")
        sws = None
        if sws_path and swi_path:
            tmp = _SWSGrp(sws_path, swi_path)
            if tmp.load_index() > 0:
                sws = tmp
        if not os.path.exists(act):
            messagebox.showwarning("文件缺失", "未找到 TKAct.dat")
            return
        self.act_path = act
        self.aa_path = aa
        self.af_path = af
        self.sound_dir = sd
        self.sws_grp = sws
        self._reload()

    def _reload(self):
        if not self.act_path:
            return
        self._preview_stop()
        self._aa_data = None
        self._af_data = None
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
        self._aa_counts = (scan_jvg_frame_counts(self.aa_path)
                           if self.aa_path else [])
        self._af_counts = (scan_jvg_frame_counts(self.af_path)
                           if self.af_path else [])
        aa_note = (f"{len(self._aa_counts)} blocks"
                   if self._aa_counts else "✗")
        af_note = (f"{len(self._af_counts)} blocks"
                   if self._af_counts else "✗")
        # SWS.GRP 状态 (主音效源)
        if self.sws_grp is not None:
            sws_note = f"{self.sws_grp.section_count} 段"
            sws_ok = True
        else:
            sws_note = "✗"
            sws_ok = False
        # Sound 目录状态 (fallback)
        if self.sound_dir and os.path.isdir(self.sound_dir):
            try:
                n_snd = sum(1 for f in os.listdir(self.sound_dir)
                            if f.lower().endswith(('.wav', '.mp3')))
                snd_note = f"{n_snd} 文件"
            except Exception:
                snd_note = "?"
        else:
            snd_note = "✗"
        self.lbl_jvg.config(
            text=(f"Aa.jvg (主角动作): {aa_note}   |   "
                  f"Af.jvg (特效/物件): {af_note}   |   "
                  f"SWS.GRP: {sws_note}   |   "
                  f"Sound/: {snd_note}"),
            foreground=g if (self._aa_counts or self._af_counts) else r)

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

        # 选择 JVG 源 (sub_4434BC: type==1 用 dword_951924=Aa.jvg, 否则 dword_951930=Af.jvg)
        if ltype == 1:
            src_name, counts = 'Aa.jvg', self._aa_counts
        else:
            src_name, counts = 'Af.jvg', self._af_counts

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
            if self.aa_path and not self._aa_data:
                self._aa_data = jvg_mod.load_jvg(self.aa_path)
            if self.af_path and not self._af_data:
                self._af_data = jvg_mod.load_jvg(self.af_path)
        except Exception:
            pass
        return (self._aa_data is not None) or (self._af_data is not None)

    def _preview_get_frame(self, src, block_idx, frame_idx):
        key = (src, block_idx, frame_idx)
        cached = self._jvg_cache.get(key)
        if cached is not None:
            return cached
        jvg = self._aa_data if src == 'aa' else self._af_data
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
        if not self._aa_data and not self._af_data:
            self._preview_load_jvg()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        # 条目级固定 bbox: 遍历全部方向/全部帧/全部图层算一次外接矩形
        self._preview_bbox = self._compute_entry_bbox(
            self.entries[self._editing_idx])
        self._preview_update_vis()
        self._preview_redraw()

    def _compute_entry_bbox(self, entry):
        """计算条目级固定包围盒 (bbox_l, bbox_t, bbox_r, bbox_b).
        遍历:
          · 全部 4 个方向 (z-order 不同 → 激活图层可能不同)
          · 每图层 first..last 全部帧
          · 同时把原点 (0,0) 纳入, 保证原点在画布内
        需要 JVG 已加载, 否则返回 None (退化到旧的动态 bbox).
        """
        if self._aa_data is None and self._af_data is None:
            return None
        xs = [0]
        ys = [0]
        for direction in range(4):
            order = [v for v in entry['dirs'][direction] if v]
            if not order:
                from_active = sorted(entry_active_layers(entry))
                order = from_active
            for slot in order:
                if slot < 1 or slot > ACT_MAX_LAYER:
                    continue
                L = entry['layers'][slot - 1]
                if L[0] == 0:
                    continue
                src = 'aa' if L[0] == 1 else 'af'
                jvg = self._aa_data if src == 'aa' else self._af_data
                pk = L[1]
                if jvg is None or pk < 0 or pk >= len(jvg.blocks):
                    continue
                blk = jvg.blocks[pk]
                n_frames = blk.frame_count
                if n_frames <= 0:
                    continue
                eff_dir = direction if L[2] == 4 else 0
                ox = L[3 + eff_dir]
                oy = L[7 + eff_dir]
                first = max(0, min(n_frames - 1, L[17]))
                last = max(first, min(n_frames - 1, L[18]))
                # 若带方向帧偏移, 要扩展到 last + L[16]*3 范围内覆盖
                if L[2] == 4 and L[16]:
                    extra = L[16] * 3
                    last = min(n_frames - 1, max(last, last + extra))
                for fi in range(first, last + 1):
                    if fi < 0 or fi >= n_frames:
                        continue
                    f = blk.frames[fi]
                    if f.width <= 0 or f.height <= 0:
                        continue
                    l = f.x_off + ox
                    t = f.y_off + oy
                    r = l + f.width - 1
                    b = t + f.height - 1
                    xs.extend([l, r])
                    ys.extend([t, b])
        if len(xs) < 2 or len(ys) < 2:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

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
        if not self._aa_data and not self._af_data:
            if not self._preview_load_jvg():
                return
        self._preview_stop()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        self._preview_tick()

    def _preview_stop(self):
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None
        # 关闭所有 MCI 别名, 防止音效残留
        if self._preview_sfx_aliases:
            for a in list(self._preview_sfx_aliases):
                _mci_close(a)
            self._preview_sfx_aliases = []

    def _preview_tick(self):
        self._preview_tick_idx += 1
        # 音效触发: sub_4434BC L627-636 每 tick 检查 v5[1] == word_9D03A0
        self._preview_sync_sfx()
        self._preview_redraw()
        speed = max(10, self._preview_speed.get())
        self._preview_job = self.root.after(speed, self._preview_tick)

    def _preview_sync_sfx(self):
        """扫描 tail 16 对, 若 trigger_tick == 当前 tick 则播放 sound_id.
        音效源优先 SWS.GRP (sub_451780 A2C22C=1 分支), 回退 Sound/.
        使用 _preview_played_ticks 防重放 (同一对 tick 只触发 1 次)."""
        if self._editing_idx is None:
            return
        if self.sws_grp is None and not self.sound_dir:
            return
        entry = self.entries[self._editing_idx]
        tail = entry.get('tail') or []
        cur_tick = self._preview_tick_idx
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0:
                continue
            if trig != cur_tick:
                continue
            key = (i, cur_tick)
            if key in self._preview_played_ticks:
                continue
            self._preview_played_ticks.add(key)
            path = self._resolve_sound_path(sid)
            if not path:
                continue
            alias = _mci_play_async(path)
            if alias:
                self._preview_sfx_aliases.append(alias)

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
        if not self._aa_data and not self._af_data:
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
        dyn_x, dyn_y = [], []  # 仅作 bbox 未缓存时的回退
        for slot, eff_dir, L in layers:
            v = self._preview_vis_vars.get(slot)
            if v is not None and not v.get():
                continue
            src = 'aa' if L[0] == 1 else 'af'
            pk = L[1]
            jvg = self._aa_data if src == 'aa' else self._af_data
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
            dyn_x.extend([spr_l, spr_r, -ox])
            dyn_y.extend([spr_t, spr_b, -oy])
            sprites.append((slot, eff_dir, L, src, blk, cur_abs, frame,
                            ox, oy, spr_l, spr_t, spr_r, spr_b, stopped))

        if not sprites:
            c.create_text(200, 100,
                          text=f"方向 {direction}: 无可渲染帧\n(检查图层可见性)",
                          fill="#888", font=("", 11))
            return

        # 使用条目级固定 bbox, 保证切方向/逐帧时画面不晃; 缺失时回退到动态计算
        if self._preview_bbox is not None:
            bbox_l, bbox_t, bbox_r, bbox_b = self._preview_bbox
        else:
            bbox_l, bbox_r = min(dyn_x), max(dyn_x)
            bbox_t, bbox_b = min(dyn_y), max(dyn_y)
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return
        margin = 40
        bw = max(bbox_r - bbox_l, 1)
        bh = max(bbox_b - bbox_t, 1)
        sx = (cw - margin * 2) / bw
        sy = (ch - margin * 2) / bh
        scale = min(sx, sy, 3.0)
        # 锚点 (0,0) 居中显示在画布: bbox 中心对齐画布中心
        draw_w = bw * scale
        draw_h = bh * scale
        off_x = (cw - draw_w) / 2 - bbox_l * scale
        off_y = (ch - draw_h) / 2 - bbox_t * scale

        def to_cv(gx, gy):
            return (off_x + gx * scale, off_y + gy * scale)

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
        _cleanup_sws_tempfiles()
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
            "TKAct.dat 多图层 2D 精灵动画编辑器 v2.2\n\n"
            "修订依据:\n"
            "  · 逆向工作区/TKS_AI分析act_editor记录.md (v2.0/v2.1)\n"
            "  · 逆向工作区/TKS_AI修正TKAct.dat实际JVG绑定.md (v2.2)\n\n"
            "650 条 × 784 字节 = 509,600 字节\n\n"
            "v2.2 关键修正:\n"
            "  · 图层贴图源: 实际是 Aa.jvg / Af.jvg, 不是 Cha.jvg / Ani.jvg\n"
            "  · type==1 → Aa.jvg (dword_951924, 主角动作库, 158 blocks)\n"
            "  · type!=1 → Af.jvg (dword_951930, 特效/物件库, 367 blocks)\n"
            "  · Cha.jvg 由 sub_458020(dword_755AF0, ...) 直接绘制基础行走图,\n"
            "    不经 ACT 图层系统, 故不再作为编辑器资源\n\n"
            "v2.0 累积修正 (保留):\n"
            "  · 前 32 字节 = 4 方向 × 8 字节 (非 8 组)\n"
            "  · layer_type = 贴图源+渲染阶段 组合标识\n"
            "  · tick_interval / start_delay 作为可编辑数据字段\n"
            "  · blend_mode / direction_mode / dir_frame_offset 语义命名\n"
            "  · 尾部按 16 对 (value, count) 展示\n\n"
            "逆向来源: sub_4434BC / sub_42FEE0 / sub_45408C / sub_45410C")


def main():
    root = tk.Tk()
    ActEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
