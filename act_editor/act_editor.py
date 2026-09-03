#!/usr/bin/env python3
"""
TKAct.dat 多图层 2D 精灵动画编辑器 (PySide6 — Godot 4.6 风格)
=============================================================
逆向依据:
  - 反编译产物/decompile/4434BC.c
    (TKAct 动画运行时与 Tick 触发)
  - 反编译产物/disassembly/4400DC.asm
    (战斗效果处理与飘字分段调用)
  - 反编译产物/decompile/433F04.c
    (伤害数字队列写入)
  - 尾部 64B 逆向确认为"音效触发表"
    (sub_4434BC L111-119 预加载 + L627-636 触发)
  - layer_type 语义精细化 + 预览图像混合模式生效
    (sub_4434BC L305/L414/L460/L518 四段位置分流)
  - mode=2 是加法饱和混合 (additive), 非 alpha 半透.
    查表 word_A3AD30[i+j]=min(i+j,31) (sub_453554 L43-52)
    param=0/>31 → full additive; 0<p<=31 → scaled additive.
  - mode=3/4 修正 (依据 sub_45871C / sub_459854):
    mode=3 (sub_45871C L118-134): per-channel 减法钳 0
          dst.RGB = max(dst - src, 0)          # 非 RGB/3 阴影!
    mode=4 (sub_459854 L109-124): 按 src 亮度 alpha-blend
          α = word_A3AEB0[src] & 0x1F          # NTSC 灰度 5-bit
          α==0 跳过; α>28 覆盖;
          其他 dst = dst*(32-α)/32 + src*α/32  # 非 RGB 取反!

文件结构 (784 字节/条, 共 650 条 = 509,600 字节):
  原版固定 650 条; 编辑器支持读取/保存 650 条以上的扩展文件,
  游戏侧需启用 tks_launcher_gui 的 tkact_expand 补丁。
  [0-31]    方向表: 4 方向 × 8 字节, 每字节为 1-based 图层号 (0=空)
  [32-79]   条目级参数区 (24 int16): [18] 动画总时长, [19] 当前播放时间,
             [20..27] 每次飘字的触发时间, 其余为预留/未知
  [80-719]  图层 × 8 (各 80 字节 = 40 int16)
  [720-783] 尾部 = 音效触发表 16 对 × (sound_id, trigger_tick) × int16

用法:
  python act_editor.py
"""

import collections
import os
import struct
import sys
import time

# ── PySide6 imports ──
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar,
    QComboBox, QSpinBox, QSlider, QRadioButton, QButtonGroup, QGroupBox,
    QStyle, QMenu,
    QToolTip,
)
from PySide6.QtGui import (
    QColor, QFont, QIntValidator, QPainter, QPen, QBrush,
    QPixmap, QImage, QAction, QPalette, QFontMetrics, QMouseEvent,
    QWheelEvent, QKeyEvent, QShortcut, QKeySequence, QCursor,
)
from PySide6.QtCore import (
    Qt, QTimer, QTranslator, Signal, QPoint, QRect, QSize,
)

# ── editor_utils 公共模块 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import business_colors

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
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.version import format_title
from editor_utils.search_utils import search_match
from editor_utils.kon_name_resolver import KonNameResolver
from editor_utils.lzss import lzss_decompress_dat
from editor_utils.shared_state import pick_tks_directory
from editor_utils.dock_components import DockHeader
from editor_utils.ui_helpers import (
    make_fake_input, update_path_labels, confirm_close, EditorComboBox,
)
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.mod_exporter import (
    compute_crc32, generate_mod_json, pack_tksmod, ModMetadataDialog, safe_mod_filename,
    diff_binary_blocks, build_block_diff_json,
    get_tksmod_info, import_tksmod_blocks, ModImportPreviewDialog, ModExportPreviewDialog,
)

HAS_PIL = False
try:
    from PIL import Image, ImageChops
    HAS_PIL = True
except ImportError:
    pass


# ============================================================
# LRU 缓存
# ============================================================

class LRUCache:
    """固定容量的 LRU 缓存, 兼容 dict 的 get/set/clear 接口."""
    def __init__(self, capacity=500):
        self.cache = collections.OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()


# ============================================================
# 音效播放 (Windows MCI + SWS.GRP 资源包)
#   sub_451780 关键逻辑 (L48-61):
#     if dword_A2C22C == 1:
#         sub_4B22A8(*(+28), *(+16)+4*v19, 0)   # 从 GRP 资源包按 sid 取
#     elif dword_A2C22C == 0:
#         sub_4B2ECC(..., "sound\\%04d.wav", v19)  # 文件路径 fallback
# ============================================================
_mci_alias_counter = [0]
_sws_tempfiles = []


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
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            return None
        if len(self._wav_cache) < 32:
            self._wav_cache[sid] = data
        return data

    def extract_to_temp(self, sid):
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
# JVG 按需加载器 (只解码当前条目引用的块, 不加载全量 40MB+347MB)
# ------------------------------------------------------------

class _LazyJvgReader:
    """JVG 文件按需读取: 首次扫描仅解析头部 (块偏移+帧数), 不解码像素.
    get_block(idx) 时才 RLE 解码该块的帧, 并缓存."""

    def __init__(self, path):
        self.path = path
        self._offsets = []
        self._sub_counts = []
        self._cache = {}
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except Exception:
            self._valid = False
            return
        if len(data) < 32 or data[0:4] != b'@JVG':
            self._valid = False
            return
        self._data = data
        self._valid = True
        bc = struct.unpack('<I', data[8:12])[0]
        off = 32
        for _ in range(bc):
            if off + 32 > len(data) or data[off:off+4] != b'@JVM':
                break
            sc = struct.unpack('<I', data[off+4:off+8])[0]
            ds = struct.unpack('<I', data[off+12:off+16])[0]
            self._sub_counts.append(sc)
            self._offsets.append(off)
            off += 32 + (sc + 1) * 4 + 512 + ds

    @property
    def valid(self):
        return self._valid

    @property
    def block_count(self):
        return len(self._offsets)

    @property
    def frame_counts(self):
        return list(self._sub_counts)

    def get_block(self, idx):
        if idx < 0 or idx >= len(self._offsets):
            return None
        if idx in self._cache:
            return self._cache[idx]
        jvg_mod = _get_jvg_loader()
        if not jvg_mod:
            return None
        off = self._offsets[idx]
        end = (self._offsets[idx+1] if idx+1 < len(self._offsets)
               else len(self._data))
        raw = self._data[off:end]
        sc = self._sub_counts[idx]
        s1 = 32
        co = [struct.unpack('<I', raw[s1+j*4:s1+j*4+4])[0] for j in range(sc+1)]
        po = s1 + (sc+1)*4
        blk = jvg_mod.JVMBlock(f"blk_{idx:03d}")
        for j in range(256):
            blk.palette.entries[j] = struct.unpack('<H', raw[po+j*2:po+j*2+2])[0]
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]
            ws = struct.unpack('<8H', raw[mo:mo+16])
            f = jvg_mod.JVGFrame()
            f.x_max = ws[0]
            f.y_max = ws[1]
            f.width = ws[2]
            f.height = ws[3]
            f.row_count = ws[7]
            eo = mo + 16
            f.encoded_data = raw[eo:eo+co[si+1]-co[si]-16]
            if f.width > 0 and f.height > 0:
                f.pixels, f.alpha = jvg_mod._decode_rle(
                    f.encoded_data, f.width, f.height)
            blk.frames.append(f)
        self._cache[idx] = blk
        return blk


_jvg_loader = None


def _get_jvg_loader():
    """获取 JVG 数据模块 (从 editor_utils.jvg_data 共享模块导入, 避免打包路径问题)"""
    global _jvg_loader
    if _jvg_loader is None:
        try:
            import editor_utils.jvg_data as _jvg_editor
            _jvg_loader = _jvg_editor
        except ImportError:
            _jvg_loader = False
    return _jvg_loader if _jvg_loader is not False else None


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


# ============================================================
# PIL ↔ QPixmap 转换
# ============================================================

def pil_to_qpixmap(pil_image):
    """将 PIL RGBA Image 转换为 QPixmap"""
    if pil_image is None:
        return None
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')
    data = pil_image.tobytes('raw', 'RGBA')
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def pil_to_qimage(pil_image):
    """将 PIL RGBA Image 转换为 QImage"""
    if pil_image is None:
        return None
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')
    data = pil_image.tobytes('raw', 'RGBA')
    return QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)


# ============================================================
# 预览: JVG 帧提取 + 混合模式
# ============================================================

def _compute_layer_frame(L, tick):
    """按 sub_4434BC 语义计算当前帧号.
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
        return loop + (rem % tail), True
    return first + (frame_adv % span), False


def _apply_blend(pil_img, mode, param):
    """对 PIL RGBA 图像应用混合模式近似变换.
    注: mode=2/3/4 的混合必须访问 dst, 由合成阶段处理; 此处原样返回.
    """
    if pil_img is None:
        return None
    if mode == 0 or mode not in (1, 2, 3, 4, 5):
        return pil_img
    if mode in (2, 3, 4):
        return pil_img

    if mode == 5:
        try:
            return pil_img.transpose(Image.FLIP_LEFT_RIGHT)
        except Exception:
            return pil_img

    try:
        src = pil_img.tobytes()
    except Exception:
        return pil_img
    buf = bytearray(src)
    n = len(buf) // 4

    if mode == 1:
        p = int(param) & 0xFFFF
        if p == 0 or p > 31:
            return pil_img
        p &= 0x1F
        if p < 8:
            tr, tg, tb = 255, 0, 0
        elif p < 16:
            tr, tg, tb = 255, 255, 0
        elif p < 24:
            tr, tg, tb = 0, 255, 0
        else:
            tr, tg, tb = 0, 0, 255
        for i in range(n):
            o = i * 4
            if buf[o + 3] == 0:
                continue
            buf[o]     = (buf[o]     + tr) >> 1
            buf[o + 1] = (buf[o + 1] + tg) >> 1
            buf[o + 2] = (buf[o + 2] + tb) >> 1

    try:
        return Image.frombytes('RGBA', pil_img.size, bytes(buf))
    except Exception:
        return pil_img


def _composite_additive(composite, rgba_src, dx, dy, param):
    """Additive 加法饱和混合 (mode=2)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        try:
            p = int(param)
        except Exception:
            p = 0
        if 0 < p <= 31:
            factor = p / 32.0
            masked = masked.point(lambda v, f=factor: int(v * f))
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.add(dst_crop, masked)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


def _composite_subtract(composite, rgba_src, dx, dy):
    """减法饱和混合 (mode=3): dst.RGB = max(dst - src, 0)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.subtract(dst_crop, masked)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


def _composite_luma_alpha(composite, rgba_src, dx, dy):
    """按 src 亮度做 alpha blend (mode=4)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        luma = src_rgb.convert('L')
        mask_luma = luma.point(
            lambda v: 0 if v == 0 else (255 if v > 224 else v))
        alpha_bin = alpha.point(lambda v: 255 if v > 0 else 0)
        mask = ImageChops.multiply(mask_luma, alpha_bin)
        dst_crop = composite.crop((l, t, r, b))
        blended = Image.composite(src_rgb, dst_crop, mask)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


# ============================================================
# 枚举类型辅助
# ============================================================

def _enum_to_label(value, label_map):
    return label_map.get(value, f"{value} (未知)")


def _label_to_enum(label, label_map):
    for k, v in label_map.items():
        if v == label:
            return k
    try:
        return int((label or '0').strip().split()[0])
    except Exception:
        return 0


# ============================================================
# 预览画布 (QWidget 自定义绘制)
# ============================================================

class PreviewCanvas(QWidget):
    """动画预览画布: PIL 合成 + QPainter 叠加标注"""
    dragOffsetChanged = Signal(int, int, int, int)  # slot, eff_dir, gdx, gdy

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._composite_pixmap = None
        self._comp_ox = 0
        self._comp_oy = 0
        self._sprite_boxes = []
        self._origin_cv = (0, 0)
        self._enemy_cv = (0, 0)
        self._info_lines = []
        self._all_stopped = False
        self._tick = 0
        self._direction = 0
        self._scale = 1.0
        self._off_x = 0
        self._off_y = 0
        self._bbox = None
        self._drag_state = None
        self._entry_title = ""
        self._cursor_over_sprite = False

    def set_entry_title(self, title):
        self._entry_title = title
        self.update()

    def set_frame_data(self, composite_pixmap, comp_ox, comp_oy,
                       sprite_boxes, origin_cv, enemy_cv, info_lines,
                       all_stopped, tick, direction, scale, off_x, off_y, bbox):
        self._composite_pixmap = composite_pixmap
        self._comp_ox = comp_ox
        self._comp_oy = comp_oy
        self._sprite_boxes = sprite_boxes
        self._origin_cv = origin_cv
        self._enemy_cv = enemy_cv
        self._info_lines = info_lines
        self._all_stopped = all_stopped
        self._tick = tick
        self._direction = direction
        self._scale = scale
        self._off_x = off_x
        self._off_y = off_y
        self._bbox = bbox
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        # 背景
        painter.fillRect(0, 0, w, h, QColor(PREVIEW_CANVAS_BG))

        if self._composite_pixmap and not self._composite_pixmap.isNull():
            painter.drawPixmap(int(self._comp_ox), int(self._comp_oy),
                             self._composite_pixmap)

        # Sprite 外框
        slot_colors = [QColor(c) for c in SLOT_COLORS]
        for (slot, eff_dir, cx, cy, ex, ey, ox, oy) in self._sprite_boxes:
            color = slot_colors[(slot - 1) % len(slot_colors)]
            pen = QPen(color, 1)
            painter.setPen(pen)
            painter.drawRect(QRect(int(cx), int(cy), int(ex - cx), int(ey - cy)))
            painter.setFont(QFont("Consolas", 6))
            painter.drawText(int(cx) + 2, int(cy) - 2, f"#{slot}")

        # 原点十字 (攻击方)
        ox_c, oy_c = self._origin_cv
        pen_green = QPen(QColor(PEN_TRAJECTORY_GREEN), 2)
        painter.setPen(pen_green)
        painter.drawLine(int(ox_c - 16), int(oy_c), int(ox_c + 16), int(oy_c))
        painter.drawLine(int(ox_c), int(oy_c - 16), int(ox_c), int(oy_c + 16))
        painter.setFont(QFont("Consolas", 7))
        painter.drawText(int(ox_c + 18), int(oy_c + 4), "攻击方")

        # 假想敌位置 (受击方)
        ex_c, ey_c = self._enemy_cv
        pen_red = QPen(QColor(PEN_TRAJECTORY_RED), 2)
        painter.setPen(pen_red)
        painter.drawLine(int(ex_c - 16), int(ey_c), int(ex_c + 16), int(ey_c))
        painter.drawLine(int(ex_c), int(ey_c - 16), int(ex_c), int(ey_c + 16))
        painter.drawText(int(ex_c + 18), int(ey_c + 4), "受击方")
        # 假想敌人形
        painter.fillRect(QRect(int(ex_c - 15), int(ey_c - 40), 30, 40), QColor(BLOCK_SHADOW_BG))
        painter.setPen(QColor(BLOCK_SHADOW_BORDER))
        painter.drawRect(QRect(int(ex_c - 15), int(ey_c - 40), 30, 40))
        painter.setPen(QColor('#f44'))
        painter.drawText(int(ex_c - 4), int(ey_c - 22), "敌")

        # 播放完毕标记
        if self._all_stopped:
            painter.setPen(QColor('#ff0'))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(w // 2 - 60, h - 16, f"■ 播放完毕 (tick {self._tick})")

        # 信息行 (左上)
        painter.setPen(QColor('#0f0'))
        painter.setFont(QFont("Consolas", 8))
        y = 12
        for line in self._info_lines[:24]:
            painter.drawText(8, y, line)
            y += 14

        # 条目标题 (左下, 同字体样式)
        if self._entry_title:
            painter.setPen(QColor('#0f0'))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(8, h - 12, self._entry_title)

    def _cv_to_game(self, cv_x, cv_y):
        """画布坐标 → 游戏坐标"""
        gx = (cv_x - self._off_x) / self._scale
        gy = (cv_y - self._off_y) / self._scale
        return gx, gy

    def _hit_test(self, cv_x, cv_y):
        for (slot, eff_dir, sx, sy, ex, ey, ox, oy) in self._sprite_boxes:
            if sx <= cv_x <= ex and sy <= cv_y <= ey:
                return (slot, eff_dir, ox, oy, sx, sy)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._hit_test(event.position().x(), event.position().y())
            if hit:
                slot, eff_dir, ox, oy, sx, sy = hit
                self._drag_state = (slot, eff_dir, ox, oy,
                                   event.position().x(), event.position().y(),
                                   sx, sy)
                self.setCursor(Qt.ClosedHandCursor)
                self.editor._preview_stop()
            else:
                self._drag_state = None

    def mouseMoveEvent(self, event):
        if self._drag_state is not None:
            slot, eff_dir, ox, oy, px, py, sx, sy_orig = self._drag_state
            dx = event.position().x() - px
            dy = event.position().y() - py
            gdx = int(dx / self._scale) if self._scale > 0 else 0
            gdy = int(dy / self._scale) if self._scale > 0 else 0
            self.editor._preview_apply_drag(slot, eff_dir, gdx, gdy)
            self._drag_state = (slot, eff_dir,
                              self.editor._get_layer_offset(slot, eff_dir, 'x'),
                              self.editor._get_layer_offset(slot, eff_dir, 'y'),
                              event.position().x(), event.position().y(),
                              sx + gdx, sy_orig + gdy)
        else:
            hit = self._hit_test(event.position().x(), event.position().y())
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_state is not None:
            self.editor._preview_finish_drag()
        self._drag_state = None
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        pass  # 缩放暂不实现

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.editor._preview_redraw()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.editor._tl_step_prev()
        elif event.key() == Qt.Key_Right:
            self.editor._tl_step_next()
        else:
            super().keyPressEvent(event)


# ============================================================
# 时间轴画布 (QWidget 自定义绘制)
# ============================================================

class TimelineWidget(QWidget):
    """时间轴可视化 + 编辑交互组件 (轨道边缘拖拽 / 平移 / 磁吸 / 框选 / 右键菜单)"""
    playheadMoved = Signal(int)

    TRACK_COLORS = ['#e74c3c', '#3498db', '#f39c12', '#2ecc71',
                    '#9b59b6', '#1abc9c', '#e67e22', '#95a5a6']
    SFX_COLORS = ['#e91e63', '#9c27b0', '#3f51b5', '#009688',
                  '#ff9800', '#795548', '#607d8b', '#4caf50']

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._zoom = 40
        self._pan_x = 0
        self._pan_y = 0
        self._track_h = 28
        self._margin = 30
        self._ruler_h = 22
        self._track_gap = 4
        self._playhead = 0
        self._layers_info = []
        self._sfx_in = []          # (0,0,sid,trig,idx) 入参
        self._sfx_pos = []         # (sx,sy,sid,trig,idx) widget 坐标 (paintEvent 算)
        self._track_bb = {}        # s -> (x1,y1,x2,y2) widget 坐标
        self._delay_bb = {}        # s -> (x1,y1,x2,y2)
        self._vis_bb = {}          # s -> (x1,y1,x2,y2) 眼睛点击区
        self._ph_bottom = 100
        self._pan_start = None
        self._drag_state = None
        self._marquee_start = None

    def set_zoom(self, z):
        self._zoom = z
        self.update()

    def zoom(self):
        return self._zoom

    def set_track_h(self, h):
        self._track_h = h
        self.update()

    def track_h(self):
        return self._track_h

    def set_data(self, playhead, layers_info, sfx_markers):
        self._playhead = playhead
        self._layers_info = layers_info
        self._sfx_in = sfx_markers
        self.update()

    def set_playhead(self, ph):
        self._playhead = ph
        self.update()

    def _content_x(self, tick):
        return self._margin + int(tick * self._zoom) + self._pan_x

    def _tick_at(self, widget_x):
        return max(0, int((widget_x - self._margin - self._pan_x) / self._zoom + 0.5))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w, h = self.width(), self.height()
        zoom = self._zoom
        margin = self._margin
        track_h = self._track_h
        track_gap = self._track_gap
        ruler_h = self._ruler_h

        is_dark = self.editor._is_dark
        bg = QColor(business_colors("act", self.editor._theme_id)["timeline_bg"])
        painter.fillRect(0, 0, w, h, bg)

        if not self._layers_info:
            return

        max_tick = 10
        for (s, ltype, delay, play_ticks, loop, interval) in self._layers_info:
            dur = delay + play_ticks
            if dur > max_tick:
                max_tick = dur

        # 刻度尺
        tick_step = max(1, int(20 / zoom))
        ruler_color = QColor('#888') if is_dark else QColor('#666')
        painter.setPen(QPen(ruler_color, 1))
        painter.setFont(QFont(FONT_FAMILY, 8))
        for t in range(0, max_tick + tick_step, tick_step):
            x = self._content_x(t)
            painter.drawLine(int(x), ruler_h - 4, int(x), ruler_h)
            if t % max(1, tick_step * 5) == 0 or t == 0:
                painter.drawText(int(x) - 10, ruler_h - 6, str(t))

        self._track_bb.clear()
        self._delay_bb.clear()
        self._vis_bb.clear()

        for i, (s, ltype, delay, play_ticks, loop, interval) in enumerate(self._layers_info):
            y = ruler_h + i * (track_h + track_gap) + 4 + self._pan_y
            color = QColor(self.TRACK_COLORS[s % 8])
            is_sel = s in getattr(self.editor, '_tl_selected_layers', set())

            # 可见性眼睛 (左侧, 可点击)
            vis_cb = self.editor._preview_vis.get(s + 1)
            vis_on = vis_cb.isChecked() if vis_cb else True
            painter.setPen(QColor(self.TRACK_COLORS[s % 8] if vis_on else '#555'))
            painter.setFont(QFont(FONT_FAMILY, 10))
            painter.drawText(18 + self._pan_x, int(y + track_h // 2 + 4),
                             '●' if vis_on else '○')
            self._vis_bb[s] = (0 + self._pan_x, int(y),
                               30 + self._pan_x, int(y + track_h))

            # 图层标签
            painter.setPen(color)
            painter.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
            painter.drawText(34 + self._pan_x, int(y + track_h // 2 + 4), f"#{s+1}")

            # 延迟区
            dx = self._content_x(0)
            if delay > 0:
                dw = int(delay * zoom)
                painter.fillRect(QRect(int(dx), int(y), int(dw), track_h),
                               QColor(business_colors("act", self.editor._theme_id)["grid_major"]))
                painter.setPen(QColor(business_colors("act", self.editor._theme_id)["grid_minor"]))
                painter.drawRect(QRect(int(dx), int(y), int(dw), track_h))

            # 播放区
            px = self._content_x(delay)
            pw = max(4, int(play_ticks * zoom))
            painter.fillRect(QRect(int(px), int(y), int(pw), track_h), color)
            painter.setPen(color.darker(120))
            painter.drawRect(QRect(int(px), int(y), int(pw), track_h))
            if is_sel:
                painter.setPen(QPen(QColor('#fff'), 3))
                painter.drawRect(QRect(int(px), int(y), int(pw), track_h))

            # 帧范围文字
            painter.setPen(QColor('#fff'))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(int(px + 3), int(y + track_h // 2 + 4),
                           f"[{self.editor._get_layer_val(s, 17)}..{self.editor._get_layer_val(s, 18)}]")

            # Loop 标记
            loop_val = self.editor._get_layer_val(s, 19)
            if loop_val == -1:
                mark = "↻"
            elif loop_val == -2:
                mark = "■"
            elif loop_val >= 0:
                mark = f"↷{loop_val}"
            else:
                mark = ""
            if mark:
                painter.setPen(color)
                painter.drawText(int(px + pw + 4), int(y + track_h // 2 + 4), mark)

            self._track_bb[s] = (int(px), int(y), int(px + pw), int(y + track_h))
            self._delay_bb[s] = (int(dx), int(y), int(px), int(y + track_h))

        # 播放头
        ph_x = self._content_x(self._playhead)
        content_h = ruler_h + len(self._layers_info) * (track_h + track_gap) + 10
        self._ph_bottom = content_h
        painter.setPen(QPen(QColor(SELECT_RED), 2))
        painter.drawLine(int(ph_x), 0, int(ph_x), content_h)
        painter.setBrush(QColor(SELECT_RED))
        painter.drawPolygon([
            QPoint(int(ph_x - 5), 0),
            QPoint(int(ph_x + 5), 0),
            QPoint(int(ph_x), 8),
        ])

        # 音效标记 (同 tick 合并为一个 ♪, 下方列出所有 sid)
        self._sfx_pos = []
        sfx_y = content_h + 4 + self._pan_y
        # 按 trig 分组
        by_trig = {}  # trig → [(sid, idx), ...]
        for (sx_val, sy_val, sid, trig, idx) in self._sfx_in:
            by_trig.setdefault(trig, []).append((sid, idx))
        for trig, items in sorted(by_trig.items()):
            sx = self._content_x(trig)
            n = len(items)
            color = QColor(self.SFX_COLORS[items[0][1] % len(self.SFX_COLORS)])
            # ♪ 图标
            painter.setPen(color)
            painter.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
            note = "♪" if n == 1 else f"♪×{n}"
            painter.drawText(int(sx) - 8, int(sfx_y + 10), note)
            # sid 列表 (每个一行, 纵向错开)
            painter.setFont(QFont(FONT_FAMILY, 7))
            for i, (sid, idx) in enumerate(items):
                c = QColor(self.SFX_COLORS[idx % len(self.SFX_COLORS)])
                painter.setPen(c)
                painter.drawText(int(sx) - 12, int(sfx_y + 22 + i * 14), f"sid={sid}")
            # 虚线连接到轨道
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.drawLine(int(sx), int(sfx_y - 6), int(sx), int(sfx_y))
            # 记录点击区域 (覆盖整个 group)
            self._sfx_pos.append((int(sx), int(sfx_y), items[0][0], trig, items[0][1]))

        # 框选矩形
        if self._marquee_start is not None:
            x0, y0 = self._marquee_start
            pos = self.mapFromGlobal(QCursor.pos())
            x1, y1 = pos.x(), pos.y()
            painter.setPen(QPen(QColor(GUIDE_BLUE), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(min(x0, x1), min(y0, y1),
                                   abs(x1 - x0), abs(y1 - y0)))

    def _hit_test(self, x, y):
        """返回 (layer_idx|None, hit_type, tick). hit_type ∈
        playhead/left_edge/right_edge/body/sfx/empty"""
        ruler_h = self._ruler_h
        edge_margin = 6
        tick = self._tick_at(x)
        if y < ruler_h:
            return None, 'playhead', tick
        for s, bb in self._track_bb.items():
            db = self._delay_bb.get(s)
            if bb is None or db is None:
                continue
            ty, by = bb[1], bb[3]
            if not (ty <= y <= by):
                continue
            left_x = bb[0]
            if db[2] > db[0] and abs(x - left_x) <= edge_margin:
                return s, 'left_edge', tick
            right_x = bb[2]
            if abs(x - right_x) <= edge_margin:
                return s, 'right_edge', tick
            if db[0] <= x <= bb[2]:
                return s, 'body', tick
        for (sx, sy, sid, trig, idx) in self._sfx_pos:
            if abs(x - sx) < 12 and abs(y - sy) < 36:
                return idx, 'sfx', trig
        return None, 'empty', tick

    def mousePressEvent(self, event):
        x = event.position().x()
        y = event.position().y()
        edit_ok = self.editor._tl_edit_enabled

        if event.button() == Qt.MiddleButton:
            self._pan_start = (x, y, self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() != Qt.LeftButton:
            return

        # 可见性眼睛点击
        for s, bb in self._vis_bb.items():
            if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]:
                cb = self.editor._preview_vis.get(s + 1)
                if cb is not None:
                    cb.setChecked(not cb.isChecked())
                    self.editor._preview_redraw()
                    self.update()
                return

        layer_idx, hit_type, tick = self._hit_test(x, y)
        self._drag_state = None
        self._marquee_start = None

        if hit_type == 'sfx':
            if edit_ok:
                self._drag_state = ('sfx', layer_idx)
                return
            if self.editor._editing_idx >= 0:
                tail = self.editor.entries[self.editor._editing_idx].get('tail') or []
                sid = tail[layer_idx * 2] if layer_idx * 2 < len(tail) else 0
                if sid and self.editor.sws_grp:
                    self.editor._play_sound_preview(sid)
        elif hit_type in ('left_edge', 'right_edge') and edit_ok:
            self._drag_state = (layer_idx, hit_type)
        elif hit_type == 'body':
            if edit_ok:
                if not (event.modifiers() & Qt.ShiftModifier):
                    if layer_idx not in self.editor._tl_selected_layers:
                        self.editor._tl_selected_layers.clear()
                        self.editor._tl_selected_layers.add(layer_idx)
                else:
                    self.editor._tl_selected_layers.add(layer_idx)
                self.editor._tl_refresh_thumbnails()
                if self.editor._editing_idx >= 0:
                    entry = self.editor.entries[self.editor._editing_idx]
                    orig_delays = {}
                    for sel in self.editor._tl_selected_layers:
                        orig_delays[sel] = entry['layers'][sel][22]
                    self._drag_state = ('batch_move', tick, orig_delays)
                self.update()
            else:
                self.editor._tl_select_layer(layer_idx)
        elif hit_type == 'empty':
            if edit_ok:
                self._marquee_start = (x, y)
                if not (event.modifiers() & Qt.ShiftModifier):
                    self.editor._tl_selected_layers.clear()
                self.update()
        elif hit_type == 'playhead':
            self._playhead = tick
            self.editor._on_timeline_clicked(tick)
            self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        y = event.position().y()

        if self._pan_start is not None:
            sx, sy, px0, py0 = self._pan_start
            self._pan_x = px0 + (x - sx)
            self._pan_y = py0 + (y - sy)
            self.update()
            return

        if self._marquee_start is not None:
            self.update()
            return

        if self._drag_state is not None:
            self.editor._tl_handle_drag(self._drag_state, x, y,
                                        event.modifiers() & Qt.ShiftModifier)
            return

        if self.editor._tl_edit_enabled:
            _, hit_type, _ = self._hit_test(x, y)
            if hit_type == 'sfx':
                self.setCursor(Qt.PointingHandCursor)
            elif hit_type in ('left_edge', 'right_edge'):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            return
        if event.button() != Qt.LeftButton:
            return

        if self._marquee_start is not None:
            x0, y0 = self._marquee_start
            x1 = event.position().x()
            y1 = event.position().y()
            min_x, max_x = min(x0, x1), max(x0, x1)
            min_y, max_y = min(y0, y1), max(y0, y1)
            for s, bb in self._track_bb.items():
                hit = not (max_x < bb[0] or min_x > bb[2]
                           or max_y < bb[1] or min_y > bb[3])
                if hit:
                    self.editor._tl_selected_layers.add(s)
            self._marquee_start = None
            self.editor._tl_refresh_thumbnails()
            self.update()
            return

        had_drag = self._drag_state is not None
        was_sfx = had_drag and self._drag_state[0] == 'sfx'
        self._drag_state = None
        if had_drag:
            self.editor._tl_handle_release(was_sfx)
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            old_zoom = self._zoom
            old_cx = event.position().x() - self._pan_x - self._margin
            old_tick = old_cx / max(1, old_zoom)
            delta = 1 if event.angleDelta().y() > 0 else -1
            self._zoom = max(2, min(40, self._zoom + delta * 2))
            new_cx = old_tick * self._zoom
            self._pan_x = self._pan_x + (old_cx - new_cx)
            self.editor._tl_update_zoom_lbl()
            self.update()
        elif event.modifiers() & Qt.ShiftModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            self._track_h = max(20, min(80, self._track_h + delta * 4))
            self.update()
        else:
            self._pan_y -= int(event.angleDelta().y() / 120) * 30
            self.update()

    def contextMenuEvent(self, event):
        if not self.editor._tl_edit_enabled:
            return
        x = event.pos().x()
        y = event.pos().y()
        layer_idx, hit_type, _ = self._hit_test(x, y)
        if layer_idx is None:
            return
        if hit_type not in ('body', 'left_edge', 'right_edge'):
            return
        if self.editor._editing_idx < 0:
            return
        self.editor._tl_select_layer(layer_idx)
        menu = QMenu(self)
        vis_cb = self.editor._preview_vis.get(layer_idx + 1)
        is_vis = vis_cb.isChecked() if vis_cb else True
        menu.addAction("隐藏图层" if is_vis else "显示图层",
                       lambda li=layer_idx: self.editor._quick_toggle_vis(li))
        menu.addSeparator()
        blend_menu = menu.addMenu("混合模式")
        for val, label in BLEND_MODE_LABELS.items():
            blend_menu.addAction(
                label, lambda v=val, li=layer_idx: self.editor._quick_set_blend(li, v))
        menu.addSeparator()
        menu.addAction("清空该图层数据",
                       lambda li=layer_idx: self.editor._quick_clear_layer(li))
        menu.exec(event.globalPos())


# ============================================================
# 缩略图条 (QWidget 自定义绘制)
# ============================================================

class ThumbnailStrip(QWidget):
    """帧缩略图选择器"""
    frameRangeChanged = Signal(int, int)  # first, last

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(58)
        self.setMaximumHeight(58)
        self._pixmaps = []
        self._total_frames = 0
        self._first = 0
        self._last = 0
        self._dfo = 0
        self._thumb_h = 40
        self._thumb_spacing = 4
        self._margin = 4
        self._anchor = None

    def set_data(self, pixmaps, total_frames, first, last, dfo):
        self._pixmaps = pixmaps
        self._total_frames = total_frames
        self._first = first
        self._last = last
        self._dfo = dfo
        self.update()

    def clear(self):
        self._pixmaps = []
        self._total_frames = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        is_dark = self.editor._is_dark
        bg = QColor('#1a1e27') if is_dark else QColor('#f5f5f5')
        painter.fillRect(0, 0, w, h, bg)

        if not self._pixmaps:
            painter.setPen(QColor('#999'))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(w // 2 - 60, h // 2, "(选择图层查看帧缩略图)")
            return

        thumb_h = self._thumb_h
        spacing = self._thumb_spacing
        margin = self._margin

        for fi, pix in enumerate(self._pixmaps):
            x = margin + fi * (thumb_h + spacing)
            if pix and not pix.isNull():
                painter.drawPixmap(int(x), 8, pix)

        # DFO 标记
        if self._dfo > 0:
            pen_dfo = QPen(QColor(GUIDE_BLUE), 1)
            painter.setPen(pen_dfo)
            painter.setFont(QFont(FONT_FAMILY, 6))
            for di in range(0, self._total_frames, self._dfo):
                x = margin + di * (thumb_h + spacing)
                painter.drawLine(int(x), thumb_h + 8, int(x), thumb_h + 16)
                painter.drawText(int(x) - 4, thumb_h + 26, str(di))

        # 选中范围
        fx = margin + self._first * (thumb_h + spacing) - 1
        lx = margin + self._last * (thumb_h + spacing) + thumb_h + 1
        pen_sel = QPen(QColor(SELECT_RED), 2)
        painter.setPen(pen_sel)
        painter.drawRect(QRect(int(fx), 6, int(lx - fx), thumb_h + 4))
        painter.setFont(QFont(FONT_FAMILY, 7, QFont.Bold))
        painter.drawText(int(fx) + 2, 18, f"first={self._first}")
        painter.drawText(int(lx) - 40, 18, f"last={self._last}")

    def mousePressEvent(self, event):
        if not self._pixmaps:
            return
        x = event.position().x()
        thumb_h = self._thumb_h
        spacing = self._thumb_spacing
        margin = self._margin
        fi = int((x - margin) / (thumb_h + spacing) + 0.5)
        fi = max(0, min(self._total_frames - 1, fi))

        if event.modifiers() & Qt.ShiftModifier:
            if self._anchor is not None:
                f = min(self._anchor, fi)
                l = max(self._anchor, fi)
                self.frameRangeChanged.emit(f, l)
        else:
            self._anchor = fi
            self.frameRangeChanged.emit(fi, fi)


# ============================================================
# 主编辑器窗口
# ============================================================

class ActEditorV2(EditorMainWindow):
    # 右侧图层卡片需要约 520px，左侧列表需要约 280px；控制栏拆行后，
    # 1680×960 可以在默认布局下同时保留两侧面板和足够的预览空间。
    EDITOR_KEY = "act_editor"
    DEFAULT_SIZE = (1680, 960)
    MIN_SIZE = (1420, 800)

    HELP_TEXT = (
        "功能: 编辑《三国群侠传》角色动画数据\n"
        "数据: 原版 650 条 × 784 字节 = 509,600 字节\n"
        "      新建条目在列表末尾新增空条目；>650 为扩展条目，需扩容补丁\n\n"
        "特性:\n"
        "  · 多图层 2D 精灵动画编辑\n"
        "  · 6 种图像混合模式\n"
        "  · 实时动画预览\n"
        "  · 音效触发表编辑\n"
        "  · 每行右键: 复制 / 粘贴 / 清除；扩展条目另有删除\n"
        "  · 原版条目只能清除；扩展条目可清除或删除\n"
        "  · 深色/浅色主题切换")

    def _init_data(self):
        # 数据状态
        self.act_path = None
        self.aa_path = None
        self.af_path = None
        self.sws_grp = None
        self.entries = []
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = -1
        self._clipboard = None
        self._edit_snapshot = None
        self.names = {}

        # JVG 数据
        self._aa_data = None
        self._af_data = None
        self._jvg_cache = LRUCache(capacity=500)
        self._pil_cache = LRUCache(capacity=500)
        self._aa_counts = []
        self._af_counts = []

        # 预览状态
        self._is_playing = False
        self._preview_tick_idx = 0
        self._play_timer = None
        self._tick_accumulator = 0.0
        self._last_time = 0.0
        self._preview_bbox = None
        self._preview_played_ticks = set()
        self._preview_sfx_aliases = []
        self._preview_dir = 0
        self._preview_speed = 120
        self._preview_vis = {}

        # 时间轴编辑状态
        self._tl_selected_layers = set()
        self._tl_edit_enabled = False
        self._marquee_start = None

        # 图层编辑变量
        self._layer_vars = [{} for _ in range(ACT_MAX_LAYER)]
        self._dir_vars = [[None]*8 for _ in range(4)]
        self._param_vars = []
        self._tail_vars = []
        self._tail_file_lbls = []

        self._auto_fill_enabled = True
        self._greenscreen_remove = True

    def _after_build(self):
        self._apply_theme()
        self._set_edit_enabled(False)
        self._install_nle_shortcuts()

    # ── 主题 ──

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        self._update_paths()

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._update_paths()

    def _compact_threshold(self):
        return 3 if self.compact_cb.isChecked() else 0

    def _rebuild_names(self):
        """精简显示切换时重建名称缓存并刷新列表。"""
        if not self.act_path:
            return
        tks_dir = os.path.dirname(self.act_path)
        self.names = self._build_act_names(tks_dir, self._compact_threshold())
        self._apply_filter()

    def _update_paths(self):
        tks_dir = os.path.dirname(self.act_path) if self.act_path else ''
        update_path_labels([
            (self.lbl_act, self.act_path, "TKAct"),
            (self.lbl_aa, self.aa_path, "Aa"),
            (self.lbl_af, self.af_path, "Af"),
        ], self._is_dark)

    # ── UI 构建 ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…\tCtrl+O", self._load_tks_dir)
        self.attach_recent_dirs_menu(fm)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新建条目", QKeySequence("Ctrl+N"), self._new_entry)
        em.addAction("复制当前条目", self._copy_current)
        em.addAction("粘贴到当前条目", self._paste_current)
        em.addAction("清除当前条目", self._clear_entry)
        em.addAction("删除当前条目", self._delete_entry)

        self.add_theme_submenu(mb)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段参考", self._show_field_ref)
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于编辑器", self._show_about)

        # 快捷键
        act_save = QAction(self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._save)
        self.addAction(act_save)

        act_open = QAction(self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._load_tks_dir)
        self.addAction(act_open)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.setMinimumWidth(160)
        self.search_entry.setClearButtonEnabled(True)
        self.search_entry.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("🔍 搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("✕ 清除", clicked=self._clear_filter))
        toolbar.addSpacing(8)

        self.show_empty_cb = QCheckBox("显示空条目")
        self.show_empty_cb.setChecked(True)
        self.show_empty_cb.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.show_empty_cb)

        self.compact_cb = QCheckBox("精简显示")
        self.compact_cb.setChecked(True)
        self.compact_cb.setToolTip("当同一 TKKon 被超过3个角色配置时，仅显示技能名称")
        self.compact_cb.stateChanged.connect(self._rebuild_names)
        toolbar.addWidget(self.compact_cb)

        self.greenscreen_cb = QCheckBox("去绿幕")
        self.greenscreen_cb.setChecked(True)
        self.greenscreen_cb.stateChanged.connect(self._on_greenscreen_toggle)
        toolbar.addWidget(self.greenscreen_cb)

        toolbar.addSpacing(8)
        toolbar.addWidget(QPushButton("🔄 重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()

        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主 Splitter (三栏: 条目列表 | 时间轴与预览 | 参数面板)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # 左栏: 条目列表
        self.table = AdaptiveTableWidget(
            0, 4,
            stretch_columns={1, 2},
            minimum_widths=[45, 90, 90, 45],
            row_height=44,
        )
        self.table.setHorizontalHeaderLabels(["序号", "名称", "图层组成", "层数"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by)
        self.table.setSortingEnabled(False)
        self.table.setMinimumWidth(280)
        splitter.addWidget(self.table)

        # 中栏: 时间轴与预览
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)

        self._build_timeline_into(cl)
        splitter.addWidget(center)
        self._center_widget = center

        # 右栏: 参数面板 (方向 / 条目级参数 / 尾部)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.setSpacing(4)
        right.setMinimumWidth(520)

        # 与 WarPC 主编辑区一致：标签栏和内容区共享连续的 flat Pane 边界。
        self.tabs = EditorTabWidget(
            flat=True,
            object_name="ActEditorTabs",
        )
        self._build_direction_tab()
        self._build_param_tab()
        self._build_layer_cards_tab()
        self._build_tail_tab()
        self.tabs.setCurrentIndex(2)  # 默认激活「图层编辑」(按物理偏移排第3)
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)

        # 左侧列表随窗口一起响应式拉伸（让出一部分增量），中央栏仍是主扩容区，
        # 右侧参数面板保持可读宽度。拉伸权重决定最大化时各栏分到的剩余空间比例。
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 800, 520])

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_act = QLabel()
        self.lbl_aa = QLabel()
        self.lbl_af = QLabel()
        for w in [self.lbl_act, self.lbl_aa, self.lbl_af]:
            path_layout.addWidget(w)
            path_layout.addSpacing(15)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_scroll_tab(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(4, 4, 12, 4)
        inner.layout().setSpacing(4)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, name)
        return inner

    # ── Tab 1: 方向与绘制顺序 ──

    def _build_direction_tab(self):
        inner = self._build_scroll_tab("方向与绘制顺序")

        lbl = QLabel(
            "方向表 (bytes 0-31): 每行 8 个槽 = 该方向的绘制顺序 "
            "(从左到右: 底层 → 顶层)。单元格值 0=空, 1~8=图层号。\n"
            "说明: 朝向不同时顺序常反转 (如下/右 = [3,4,1,2], 上/左 = [1,2,3,4]), "
            "这就是 2.5D 身前/身后遮挡关系的数据源。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(2)

        # 表头
        grid.addWidget(QLabel(""), 0, 0)
        for s in range(8):
            lbl_z = QLabel(f"z{s}")
            lbl_z.setProperty("class", "PropLabel")
            lbl_z.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl_z, 0, s + 1)

        for d in range(4):
            lbl_dir = QLabel(DIRECTION_LABELS[d])
            lbl_dir.setProperty("class", "PropLabel")
            lbl_dir.setMinimumWidth(100)
            grid.addWidget(lbl_dir, d + 1, 0)
            for i in range(8):
                le = QLineEdit("0")
                le.setFixedWidth(32)
                le.setAlignment(Qt.AlignCenter)
                self._dir_vars[d][i] = le
                grid.addWidget(le, d + 1, i + 1)

        inner.layout().addLayout(grid)
        inner.layout().addStretch()

    # ── 中栏: 时间轴与预览 (统一视图) ──

    def _build_timeline_into(self, parent_layout):
        inner = QWidget()
        inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(0, 0, 0, 0)
        inner.layout().setSpacing(4)
        parent_layout.addWidget(inner, 1)

        # 控制栏分两行：单行会把中央栏的最小宽度推到 1000px 以上，
        # 进而在默认窗口下挤压左侧列表。第一行放播放/方向/周期，
        # 第二行放播放头和编辑操作。
        ctrl = QVBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(2)

        playback_ctrl = QHBoxLayout()
        playback_ctrl.setSpacing(4)

        btn_first = QPushButton("⏮️", clicked=self._tl_goto_first)
        btn_first.setToolTip("跳至首帧 (Ctrl+◀◀)")
        playback_ctrl.addWidget(btn_first)

        btn_prev = QPushButton("◀️", clicked=self._tl_step_prev)
        btn_prev.setToolTip("后退一帧 (J / ←)")
        playback_ctrl.addWidget(btn_prev)

        btn_play = QPushButton("▶️", clicked=self._preview_play)
        btn_play.setToolTip("播放动画 (L)")
        playback_ctrl.addWidget(btn_play)

        btn_stop = QPushButton("⏹️", clicked=self._preview_stop)
        btn_stop.setToolTip("停止播放 (K)")
        playback_ctrl.addWidget(btn_stop)

        btn_last = QPushButton("⏭️", clicked=self._tl_goto_last)
        btn_last.setToolTip("跳至末帧 (Ctrl+▶▶)")
        playback_ctrl.addWidget(btn_last)

        playback_ctrl.addSpacing(4)
        playback_ctrl.addWidget(QLabel("方向:"))

        self._dir_btns = QButtonGroup(self)
        for d in range(4):
            rb = QRadioButton(DIRECTION_SHORT[d])
            rb.setChecked(d == 0)
            self._dir_btns.addButton(rb, d)
            playback_ctrl.addWidget(rb)
        self._dir_btns.buttonClicked.connect(self._on_dir_changed)

        playback_ctrl.addSpacing(4)
        playback_ctrl.addWidget(QLabel("周期:"))
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(10, 500)
        self._speed_spin.setValue(120)
        self._speed_spin.setSingleStep(10)
        # 主题 QSS 会为边框、内边距和右侧上下箭头预留空间；52px 会
        # 把 QSpinBox 内部的 QLineEdit 压成几乎不可见，导致无法输入。
        # 周期范围是 10~500，固定留出三位数字的可编辑区域。
        self._speed_spin.setFixedWidth(80)
        playback_ctrl.addWidget(self._speed_spin)
        playback_ctrl.addStretch()
        ctrl.addLayout(playback_ctrl)

        edit_ctrl = QHBoxLayout()
        edit_ctrl.setSpacing(4)
        btn_zero = QPushButton("↩️ 归零", clicked=self._tl_reset_playhead)
        btn_zero.setToolTip("播放头归零")
        edit_ctrl.addWidget(btn_zero)
        self._tl_tick_lbl = QLabel("tick: 0")
        edit_ctrl.addWidget(self._tl_tick_lbl)

        self._edit_mode_cb = QCheckBox("编辑模式")
        self._edit_mode_cb.setChecked(False)
        self._edit_mode_cb.stateChanged.connect(self._toggle_edit_mode)
        edit_ctrl.addWidget(self._edit_mode_cb)

        edit_ctrl.addStretch()
        edit_ctrl.addWidget(QPushButton("✅ 应用修改", clicked=self._apply_edit))
        edit_ctrl.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit))
        ctrl.addLayout(edit_ctrl)
        inner.layout().addLayout(ctrl)

        # 垂直分割: 预览区 + 时间轴区 (工具栏附在时间轴顶部)
        vpw = QSplitter(Qt.Vertical)
        vpw.setHandleWidth(6)
        vpw.setChildrenCollapsible(False)
        inner.layout().addWidget(vpw, 1)

        # 预览画布 (上区)
        self.preview_canvas = PreviewCanvas(self)
        vpw.addWidget(self.preview_canvas)

        # 时间轴容器: 工具栏 (上) + TimelineWidget (下)
        tl_container = QWidget()
        tl_layout = QVBoxLayout(tl_container)
        tl_layout.setContentsMargins(0, 0, 0, 0)
        tl_layout.setSpacing(0)

        merged_w = QWidget()
        merged_bar = QHBoxLayout(merged_w)
        merged_bar.setContentsMargins(4, 2, 4, 2)
        merged_bar.addWidget(QLabel("图层可见:"))
        self._vis_frame = QWidget()
        self._vis_layout = QHBoxLayout(self._vis_frame)
        self._vis_layout.setContentsMargins(0, 0, 0, 0)
        self._vis_layout.setSpacing(2)
        merged_bar.addWidget(self._vis_frame)
        merged_bar.addStretch()
        merged_bar.addWidget(QLabel("缩放:"))
        self._tl_zoom_lbl = QLabel("×40")
        self._tl_zoom_lbl.setFixedWidth(36)
        self._tl_zoom_lbl.setAlignment(Qt.AlignCenter)
        merged_bar.addWidget(self._tl_zoom_lbl)
        zoom_slider = QSlider(Qt.Horizontal)
        zoom_slider.setRange(2, 40)
        zoom_slider.setValue(40)
        zoom_slider.setTickInterval(2)
        zoom_slider.setPageStep(4)
        zoom_slider.setMaximumWidth(160)
        zoom_slider.setToolTip("时间轴缩放 (Ctrl+滚轮)")
        zoom_slider.valueChanged.connect(self._tl_zoom_slider_changed)
        merged_bar.addWidget(zoom_slider)
        self._tl_zoom_slider = zoom_slider
        tl_layout.addWidget(merged_w)

        self.timeline_widget = TimelineWidget(self)
        self.timeline_widget.playheadMoved.connect(self._on_timeline_clicked)
        tl_layout.addWidget(self.timeline_widget, 1)

        vpw.addWidget(tl_container)
        vpw.setSizes([500, 180])

        # 缩略图条 (固定在时间轴下方, 高度最小)
        self.thumb_strip = ThumbnailStrip(self)
        self.thumb_strip.frameRangeChanged.connect(self._on_thumb_range_changed)
        inner.layout().addWidget(self.thumb_strip)

    def _build_layer_cards_tab(self):
        """图层编辑 Tab: 8 个图层的紧凑参数卡片 (放在右侧参数面板)"""
        inner = self._build_scroll_tab("图层编辑")
        self._card_inner = inner
        self._build_layer_cards()

    @staticmethod
    def _no_wheel_combo(items=None):
        """创建禁用滚轮切换的下拉框 (防止滚动面板时误改选项)"""
        combo = EditorComboBox()
        if items:
            combo.addItems(items)
        return combo

    @staticmethod
    def _sync_editable_combo_value(combo, index=None):
        """让可编辑枚举框显示底层数值，而不是选项说明文字。"""
        if not combo.isEditable():
            return
        if index is None:
            index = combo.currentIndex()
        if index < 0:
            return
        value = combo.itemData(index)
        if value is None:
            return
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setText(str(value))

    def _build_layer_cards(self):
        """构建 8 个图层的紧凑卡片"""
        for s in range(ACT_MAX_LAYER):
            card = self._build_single_card(s)
            self._card_inner.layout().addWidget(card)

    def _build_single_card(self, layer_idx):
        s = layer_idx + 1
        vars_row = self._layer_vars[layer_idx]
        COL = 4  # 每行 4 列, 等宽

        card = QFrame()
        card.setObjectName("DockBody")
        card.setFrameShape(QFrame.StyledPanel)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 6, 8, 8)
        cl.setSpacing(6)

        # ── 头部: 图层号 + 类型 ──
        head = QHBoxLayout()
        head.setSpacing(6)
        lbl = QLabel(f"#{s}")
        lbl.setProperty("class", "PreviewName")
        head.addWidget(lbl)
        vars_row['_card_label'] = lbl

        type_combo = self._no_wheel_combo(list(LAYER_TYPE_LABELS.values()))
        type_combo.setCurrentIndex(0)
        type_combo.currentIndexChanged.connect(
            lambda idx, li=layer_idx: self._on_layer_type_changed(li))
        head.addWidget(type_combo, 1)
        vars_row['_type_combo'] = type_combo
        cl.addLayout(head)

        # ── 属性网格: 标签在上 → 输入框在下 → 4 列等宽 ──
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(8)

        def _cell(label, widget):
            """创建 '标签在上, 控件在下' 的 VBox 单元"""
            c = QVBoxLayout()
            c.setSpacing(2)
            lb = QLabel(label)
            lb.setProperty("class", "PropLabel")
            c.addWidget(lb)
            c.addWidget(widget)
            c.addStretch()
            return c

        FW = 104  # 所有输入控件统一宽度

        def _le(key, default="0", ro=False):
            le = QLineEdit(default)
            le.setMinimumWidth(FW)
            if ro:
                le.setReadOnly(True)
            le.textChanged.connect(lambda txt, li=layer_idx, f=key: self._on_layer_field_change(li, f))
            vars_row[key] = le
            return le

        def _cb(key, labels_dict, editable=False):
            cb = self._no_wheel_combo()
            for value, label in labels_dict.items():
                cb.addItem(label, value)
            cb.setMinimumWidth(FW)
            if editable:
                cb.setEditable(True)
                cb.setInsertPolicy(QComboBox.NoInsert)
                cb.currentIndexChanged.connect(
                    lambda idx, combo=cb:
                    self._sync_editable_combo_value(combo, idx))
                self._sync_editable_combo_value(cb)
            vars_row[key] = cb
            return cb

        # Row 0: JVG块号 | 混合模式 | 循环行为 | 方向模式
        grid.addLayout(_cell("JVG 块号", _le("jvg_block_index")), 0, 0)
        bc = _cb("blend_mode", BLEND_MODE_LABELS)
        vars_row['_blend_combo'] = bc
        grid.addLayout(_cell("混合模式", bc), 0, 1)
        lc = _cb("loop_behavior", LOOP_BEHAVIOR_LABELS, editable=True)
        vars_row['_loop_combo'] = lc
        grid.addLayout(_cell("循环行为", lc), 0, 2)
        grid.addLayout(_cell("方向模式", _cb("direction_mode", DIRECTION_MODE_LABELS)), 0, 3)

        # Row 1: 起始帧 | 终止帧 | 方向帧偏移 | 移动模式
        grid.addLayout(_cell("起始帧", _le("first_frame")), 1, 0)
        grid.addLayout(_cell("终止帧", _le("last_frame")), 1, 1)
        grid.addLayout(_cell("方向帧偏移", _le("dir_frame_offset")), 1, 2)
        grid.addLayout(_cell("移动模式", _cb("move_mode", MOVE_MODE_LABELS)), 1, 3)

        # Row 2: 帧停留 tick | 启动延迟 | 混合参数 | 参数步进
        grid.addLayout(_cell("帧停留 tick", _le("tick_interval")), 2, 0)
        grid.addLayout(_cell("启动延迟", _le("start_delay")), 2, 1)
        grid.addLayout(_cell("混合参数", _le("blend_param")), 2, 2)
        grid.addLayout(_cell("参数步进", _le("blend_param_step")), 2, 3)

        # Row 3: 步进值 | 步进增量 | 帧标签(只读) | —
        grid.addLayout(_cell("步进值", _le("step_value")), 3, 0)
        grid.addLayout(_cell("步进增量", _le("step_delta")), 3, 1)
        fr = QLabel("[0..0]")
        fr.setProperty("class", "ExtraPreviewText")
        fr.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        grid.addLayout(_cell("帧范围", fr), 3, 2)
        vars_row['_frame_lbl'] = fr
        grid.addLayout(_cell("", QWidget()), 3, 3)  # 占位对齐

        # 四列等宽
        for c in range(COL):
            grid.setColumnStretch(c, 1)

        cl.addLayout(grid)

        # ── 详细区域 (默认隐藏: 位移/运行时/保留字段) ──
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(2, 2, 2, 2)
        dl.setSpacing(6)

        EXCLUDE_COMPACT = {'layer_type', 'jvg_block_index', 'blend_mode',
                          'loop_behavior', 'direction_mode', 'move_mode',
                          'first_frame', 'last_frame', 'dir_frame_offset',
                          'tick_interval', 'start_delay',
                          'blend_param', 'blend_param_step',
                          'step_value', 'step_delta'}
        for grp_name, fields in FIELD_GROUPS:
            rem = [(fn, idx, label, w, cmt) for (fn, idx, label, w, cmt) in fields
                   if fn not in EXCLUDE_COMPACT]
            if not rem:
                continue
            grp_w = QGroupBox(grp_name)
            dg = QGridLayout(grp_w)
            dg.setVerticalSpacing(6)
            dg.setHorizontalSpacing(8)
            for fi, (fn, idx, label, w, cmt) in enumerate(rem):
                r, c = divmod(fi, COL)
                dc = QVBoxLayout()
                dc.setSpacing(2)
                dlb = QLabel(label)
                dlb.setProperty("class", "PropLabel")
                dlb.setToolTip(cmt)
                dc.addWidget(dlb)
                ro = fn in READONLY_KEYS
                dw = QLineEdit("0")
                dw.setMinimumWidth(FW)
                if ro:
                    dw.setReadOnly(True)
                dw.textChanged.connect(lambda txt, li=layer_idx, f=fn: self._on_layer_field_change(li, f))
                dc.addWidget(dw)
                vars_row[fn] = dw
                dc.addStretch()
                dg.addLayout(dc, r, c)
            # 填充末行空白
            if rem:
                lrc = len(rem) % COL
                if lrc != 0:
                    lr = len(rem) // COL
                    for cc in range(lrc, COL):
                        dg.addWidget(QWidget(), lr, cc)
            for cc in range(COL):
                dg.setColumnStretch(cc, 1)
            dl.addWidget(grp_w)

        # 探针标签
        probe_lbl = QLabel("")
        probe_lbl.setProperty("class", "ExtraPreviewText")
        probe_lbl.setWordWrap(True)
        dl.addWidget(probe_lbl)
        vars_row['_probe_lbl'] = probe_lbl

        detail.setVisible(False)
        cl.addWidget(detail)
        vars_row['_detail'] = detail

        # ── 展开/折叠 ──
        toggle_btn = QPushButton("🔽 展开详情")
        toggle_btn.setFixedWidth(100)
        toggle_btn.clicked.connect(lambda checked, li=layer_idx: self._toggle_card_detail(li))
        cl.addWidget(toggle_btn)
        vars_row['_toggle_btn'] = toggle_btn
        vars_row['_detail_expanded'] = False

        return card

    def _toggle_card_detail(self, layer_idx):
        vr = self._layer_vars[layer_idx]
        detail = vr.get('_detail')
        btn = vr.get('_toggle_btn')
        if vr.get('_detail_expanded', False):
            detail.setVisible(False)
            btn.setText("🔽 展开详情")
            vr['_detail_expanded'] = False
        else:
            detail.setVisible(True)
            btn.setText("🔼 收起详情")
            vr['_detail_expanded'] = True

    # ── Tab 3: 条目级参数 ──

    def _build_param_tab(self):
        inner = self._build_scroll_tab("条目级参数")

        lbl = QLabel(
            "条目级参数区 (bytes 32-79, int16[16..39], 共 24 项)。\n"
            "[18] 是动画总时长，[19] 是当前播放时间（自动）；"
            "[20]~[27] 是第1~8次飘字对应的触发时间。\n"
            "已填写的飘字触发时间数量，会决定伤害或恢复数值分几段显示；这些时间应按先后顺序递增，且小于[18]，最多填写8次。\n"
            "[19] 由原版运行时自动维护，通常不需要手工配置；其余未标明字段目前按原版逆向结果保留/未知处理。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(8)
        self._param_vars = []

        for k, idx in enumerate(range(16, 40)):
            r, c = divmod(k, PARAM_GRID_COLUMNS)
            cell = QVBoxLayout()
            cell.setSpacing(2)

            label, comment = PARAM_FIELD_INFO[idx]
            lbl_f = QLabel(f"[{idx}] {label}")
            lbl_f.setProperty("class", "PropLabel")
            lbl_f.setToolTip(comment)
            lbl_f.setWordWrap(True)
            cell.addWidget(lbl_f)

            le = QLineEdit("0")
            le.setMinimumWidth(70)
            le.setToolTip(comment)
            self._param_vars.append(le)
            cell.addWidget(le)
            grid.addLayout(cell, r, c)

        for c in range(PARAM_GRID_COLUMNS):
            grid.setColumnStretch(c, 1)

        inner.layout().addLayout(grid)
        inner.layout().addStretch()

    # ── Tab 4: 尾部数据 (音效触发表) ──

    def _build_tail_tab(self):
        inner = self._build_scroll_tab("尾部数据")

        lbl = QLabel(
            "尾部 (bytes 720-783) = 音效触发表  16 对 × (sound_id, trigger_tick)\n"
            "逆向证据: sub_4434BC L111-119 对 &unk_9D064A 逐对 sub_451780(1) 预加载;\n"
            "          L627-636 每 tick 检查 v5[1] == word_9D03A0 时 sub_451C38(0) 播放.\n"
            "sound_id = 0 表示该对空位 (不触发)。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(2)
        grid.addWidget(QLabel("#"), 0, 0)
        grid.addWidget(QLabel("sound_id"), 0, 1)
        grid.addWidget(QLabel("trigger_tick"), 0, 2)
        grid.addWidget(QLabel(""), 0, 3)
        grid.addWidget(QLabel("文件"), 0, 4)
        grid.addWidget(QLabel("原 int16"), 0, 5)

        self._tail_vars = []
        self._tail_file_lbls = []

        for pair in range(16):
            r = pair + 1
            grid.addWidget(QLabel(f"{pair:02d}"), r, 0)

            le_id = QLineEdit("0")
            le_id.setFixedWidth(70)
            grid.addWidget(le_id, r, 1)
            self._tail_vars.append(le_id)

            le_tick = QLineEdit("0")
            le_tick.setFixedWidth(80)
            grid.addWidget(le_tick, r, 2)
            self._tail_vars.append(le_tick)

            btn = QPushButton("▶️")
            btn.setFixedWidth(40)
            btn.setToolTip("试听此 sound_id 对应的音效文件")
            btn.clicked.connect(lambda checked, idx=pair: self._on_tail_preview(idx))
            grid.addWidget(btn, r, 3)

            fl = QLabel("")
            fl.setProperty("class", "ExtraPreviewText")
            grid.addWidget(fl, r, 4)
            self._tail_file_lbls.append(fl)

            grid.addWidget(QLabel(f"[{pair*2}],[{pair*2+1}]"), r, 5)

            le_id.textChanged.connect(lambda txt, idx=pair: self._refresh_tail_file_lbl(idx))

        inner.layout().addLayout(grid)
        inner.layout().addStretch()

    # ── 数据加载 ──

    def _load_tks_dir(self):
        d = pick_tks_directory(self)
        if d:
            self.load_tks_dir(d)

    def load_tks_dir(self, d):
        def _pick(*names):
            for n in names:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    return p
            return None

        act = os.path.join(d, "TKAct.dat")
        aa = _pick("Aa.jvg", "Aa.JVG", "aa.jvg")
        af = _pick("Af.jvg", "Af.JVG", "af.jvg")
        sws_path = _pick("SWS.GRP", "SWS.grp", "sws.grp")
        swi_path = _pick("SWS.IDX", "SWS.idx", "sws.idx")

        sws = None
        if sws_path and swi_path:
            tmp = _SWSGrp(sws_path, swi_path)
            if tmp.load_index() > 0:
                sws = tmp

        if not os.path.exists(act):
            QMessageBox.warning(self, "文件缺失", "未找到 TKAct.dat")
            return

        self.act_path = act
        self.aa_path = aa
        self.af_path = af
        self.sws_grp = sws
        self._reload()

    def _reload(self):
        if not self.act_path:
            return
        self._preview_stop()
        self._aa_data = None
        self._af_data = None
        self._jvg_cache.clear()
        self._pil_cache.clear()
        self.status_var.setText("加载中…")
        QApplication.processEvents()

        try:
            self.entries = load_act(self.act_path)

            tks_dir = os.path.dirname(self.act_path)
            self.names = self._build_act_names(tks_dir, self._compact_threshold())

            self._dirty = False
            nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
            self.status_var.setText(
                f"{len(self.entries)} 条 (784 字节/条) | 非空 {nonempty}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.entries = []

        self._set_edit_enabled(True)
        self._update_paths()
        self._apply_filter()

    def _build_act_names(self, tks_dir: str, compact_threshold: int = 3) -> dict[int, str]:
        """构建 TKAct 索引 → 名称 的反向映射。

        TKAct 条目被 TKKon.tkact_id 和 TKItem.tkkon_index→TKKon.tkact_id
        多对一引用。此方法收集所有引用源并合并显示。
        """
        import struct
        names: dict[int, list[str]] = {}

        # 1. 获取 TKKon 名称解析器
        try:
            resolver = KonNameResolver(tks_dir)
        except Exception:
            return {}

        # 2. TKKon → TKAct: kon[k].tkact_id → resolver.get_name(k)
        kon_path = os.path.join(tks_dir, 'TKKon.dat')
        kon_act_map: dict[int, int] = {}  # kon_index → tkact_id
        if os.path.exists(kon_path):
            try:
                with open(kon_path, 'rb') as f:
                    raw = f.read()
                dec = lzss_decompress_dat(raw)
                if len(raw) % 40 == 0 and (len(dec) == 0 or len(dec) % 40 != 0):
                    dec = raw
                for i in range(len(dec) // 40):
                    off = i * 40
                    if off + 8 > len(dec):
                        break
                    tkact_id = struct.unpack_from('<h', dec, off + 6)[0]
                    if tkact_id >= 0:
                        kon_act_map[i] = tkact_id
            except Exception:
                pass

        for kon_idx, act_idx in kon_act_map.items():
            name = resolver.get_name(kon_idx, compact_threshold=compact_threshold)
            if name and not name.startswith('空槽-'):
                if act_idx not in names:
                    names[act_idx] = []
                if name not in names[act_idx]:
                    names[act_idx].append(name)

        # 3. TKItem → TKKon → TKAct: item.tkkon_index → kon_act_map → act_idx
        item_path = os.path.join(tks_dir, 'TKItem.dat')
        if os.path.exists(item_path):
            try:
                with open(item_path, 'rb') as f:
                    raw = f.read()
                dec = lzss_decompress_dat(raw)
                if len(raw) % 64 == 0 and (len(dec) == 0 or len(dec) % 64 != 0):
                    dec = raw
                for i in range(len(dec) // 64):
                    off = i * 64
                    if off + 14 > len(dec):
                        break
                    item_id = struct.unpack_from('<h', dec, off)[0]
                    if item_id <= 0:
                        continue
                    tkkon_idx = struct.unpack_from('<h', dec, off + 12)[0]
                    if tkkon_idx in kon_act_map:
                        act_idx = kon_act_map[tkkon_idx]
                        kon_name = resolver.get_name(tkkon_idx, compact_threshold=compact_threshold)
                        if kon_name and not kon_name.startswith('空槽-'):
                            if act_idx not in names:
                                names[act_idx] = []
                            if kon_name not in names[act_idx]:
                                names[act_idx].append(kon_name)
            except Exception:
                pass

        return {k: '\n'.join(v) for k, v in names.items()}

    # ── 路径更新 ──

    def _update_paths(self):
        update_path_labels([(self.lbl_act, self.act_path, "TKAct")], self._is_dark)

        if self.aa_path and not self._aa_counts:
            rdr = _LazyJvgReader(self.aa_path)
            if rdr.valid:
                self._aa_counts = rdr.frame_counts
        if self.af_path and not self._af_counts:
            rdr = _LazyJvgReader(self.af_path)
            if rdr.valid:
                self._af_counts = rdr.frame_counts

        aa_note = f"{len(self._aa_counts)} blocks" if self._aa_counts else "✗"
        af_note = f"{len(self._af_counts)} blocks" if self._af_counts else "✗"
        if self.sws_grp is not None:
            sws_note = f"{self.sws_grp.section_count} 段"
        else:
            sws_note = "✗"

        self.lbl_aa.setText(f"Aa.jvg (主角动作): {aa_note}")
        self.lbl_af.setText(f"Af.jvg (特效/物件): {af_note} | SWS.GRP: {sws_note}")

    # ── 筛选/列表 ──

    def _apply_filter(self):
        q = self.search_entry.text()
        show_empty = self.show_empty_cb.isChecked()
        self.filtered_indices = []
        for entry in self.entries:
            if not show_empty and entry_is_empty(entry):
                continue
            if q:
                name = self.names.get(entry['index'], '')
                if not search_match(q, entry['index'], name, entry_summary(entry)):
                    continue
            self.filtered_indices.append(entry['index'])
        self._refresh_table()
        nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
        msg = (f"显示 {len(self.filtered_indices)}/{len(self.entries)} "
               f"(非空 {nonempty}) | Ctrl+S 保存")
        if self._dirty:
            msg += " [已修改]"
        self.status_var.setText(msg)

    def _clear_filter(self):
        self.search_entry.clear()
        self._apply_filter()

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 2:
            self.filtered_indices.sort(
                key=lambda i: entry_summary(self.entries[i]).lower(), reverse=rev)
        elif col == 3:
            self.filtered_indices.sort(
                key=lambda i: len(entry_active_layers(self.entries[i])), reverse=rev)
        else:
            self.filtered_indices.sort(reverse=rev)
        self._sort_reverse = not rev
        self._refresh_table()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            entry = self.entries[idx]
            has_data = not entry_is_empty(entry)
            if has_data:
                nm = self.names.get(idx, '')
                if not nm and idx >= ACT_ENTRY_COUNT:
                    nm = '新增'
                elif not nm and idx in (640, 641, 642):
                    nm = '未知'
            else:
                nm = '空槽'
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(nm))
            self.table.setItem(row, 2, QTableWidgetItem(entry_summary(entry)))
            n_layer = len(entry_active_layers(entry))
            self.table.setItem(row, 3, QTableWidgetItem(str(n_layer)))
            # 颜色标记 (名称语义优先)
            if "原版未完成" in nm:
                color = QColor(STMT_INCOMPLETE_COLOR)
            elif "未知" in nm:
                color = QColor(STMT_UNKNOWN_COLOR)
            elif "空槽" in nm:
                color = QColor(business_colors("act", self._theme_id)["stmt_muted"])
            elif has_data:
                color = QColor(STMT_HAS_DATA_COLOR)
            else:
                color = QColor(STMT_NO_DATA_COLOR)
            for ci in range(4):
                self.table.item(row, ci).setForeground(color)
        self.table.blockSignals(False)

    # ── 列表交互 ──

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        if row >= len(self.filtered_indices):
            return
        idx = self.filtered_indices[row]
        entry = self.entries[idx]
        self._edit_snapshot = {
            'dirs': [list(d) for d in entry['dirs']],
            'param16': list(entry['param16']),
            'layers': [list(L) for L in entry['layers']],
            'tail': list(entry['tail']),
        }
        self._populate_edit(entry)

    def _select_entry(self, idx):
        for row, i in enumerate(self.filtered_indices):
            if i == idx:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                return True
        return False

    def _clone_entry(self, src):
        return {
            'dirs': [list(d) for d in src['dirs']],
            'param16': list(src['param16']),
            'layers': [list(L) for L in src['layers']],
            'tail': list(src['tail']),
        }

    def _on_table_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.addAction("新增条目", self._new_entry)
            menu.exec(self.table.viewport().mapToGlobal(pos))
            return
        row = item.row()
        if row >= len(self.filtered_indices):
            return
        idx = self.filtered_indices[row]
        entry = self.entries[idx]
        self._editing_idx = idx
        self._populate_edit(entry)

        menu = QMenu(self)
        menu.addAction("复制", lambda: self._clipboard_copy(idx))
        paste_action = menu.addAction("粘贴", lambda: self._clipboard_paste(idx))
        paste_action.setEnabled(self._clipboard is not None)
        menu.addAction("清除", lambda: self._clear_entry_idx(idx))
        if idx >= ACT_ENTRY_COUNT:
            menu.addAction("删除", lambda: self._delete_entry(idx))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _clipboard_copy(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx < 0 or idx >= len(self.entries):
            return
        self._clipboard = self._clone_entry(self.entries[idx])
        self.status_var.setText(
            f"已复制条目 #{idx} (可右键粘贴到任意条目)")

    def _copy_current(self):
        self._clipboard_copy()

    def _clipboard_paste(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if self._clipboard is None or idx < 0 or idx >= len(self.entries):
            return
        entry = self.entries[idx]
        if not entry_is_empty(entry):
            if QMessageBox.question(
                    self, "确认覆盖",
                    f"粘贴将覆盖条目 #{idx} 的现有内容，是否继续？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        data = self._clone_entry(self._clipboard)
        data['index'] = idx
        self.entries[idx] = data
        self._dirty = True
        if entry_is_empty(data) and not self.show_empty_cb.isChecked():
            self.show_empty_cb.setChecked(True)
        else:
            self._apply_filter()
        self._select_entry(idx)
        self._populate_edit(self.entries[idx])
        self.status_var.setText(f"已粘贴到条目 #{idx}")

    def _paste_current(self):
        self._clipboard_paste()

    # ── 编辑填充 ──

    def _populate_edit(self, entry):
        self._editing_idx = entry['index']
        active = sorted(entry_active_layers(entry))
        refd = sorted(entry_referenced_layers(entry))
        self.preview_canvas.set_entry_title(
            f"动画 #{entry['index']}  "
            f"活跃图层 {active if active else '(空)'}  "
            f"方向表引用 {refd if refd else '(无)'}")

        for d in range(4):
            for i in range(8):
                if self._dir_vars[d][i] is not None:
                    self._dir_vars[d][i].setText(str(entry['dirs'][d][i]))

        for s in range(ACT_MAX_LAYER):
            self._populate_layer(s, entry['layers'][s])

        for k in range(24):
            if k < len(self._param_vars):
                self._param_vars[k].setText(str(entry['param16'][k]))

        for k in range(32):
            if k < len(self._tail_vars):
                self._tail_vars[k].setText(str(entry['tail'][k]))

        # 更新卡片标签
        for s in range(ACT_MAX_LAYER):
            t = entry['layers'][s][0]
            lbl = self._layer_vars[s].get('_card_label')
            if lbl:
                if t == 0:
                    lbl.setText(f"#{s+1} (空)")
                else:
                    full = LAYER_TYPE_LABELS.get(t, str(t))
                    parts = full.split(' ', 1)
                    lab = parts[1].split('(')[0].strip() if len(parts) > 1 else full
                    lbl.setText(f"#{s+1} {lab}")

        # 刷新尾部文件标签
        for pair in range(16):
            self._refresh_tail_file_lbl(pair)

        self._preview_reload()
        self._tl_auto_zoom()

    def _populate_layer(self, layer_idx, vals):
        self._auto_fill_enabled = False
        vars_row = self._layer_vars[layer_idx]
        t = vals[0]

        combo = vars_row.get('_type_combo')
        if combo:
            combo.blockSignals(True)
            label = _enum_to_label(t, LAYER_TYPE_LABELS)
            idx = combo.findText(label)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        for (fn, idx, _, _, _) in ALL_FIELDS:
            if fn == 'layer_type' or fn not in vars_row:
                continue
            v = vals[idx]
            widget = vars_row[fn]
            if isinstance(widget, QLineEdit):
                widget.blockSignals(True)
                if fn == 'blend_mode':
                    widget.setText(_enum_to_label(v, BLEND_MODE_LABELS))
                elif fn == 'direction_mode':
                    widget.setText(_enum_to_label(v, DIRECTION_MODE_LABELS))
                elif fn == 'loop_behavior':
                    widget.setText(_enum_to_label(v, LOOP_BEHAVIOR_LABELS))
                elif fn == 'move_mode':
                    widget.setText(_enum_to_label(v, MOVE_MODE_LABELS))
                else:
                    widget.setText(str(v))
                widget.blockSignals(False)
            elif isinstance(widget, EditorComboBox):
                widget.blockSignals(True)
                if fn == 'blend_mode':
                    label = _enum_to_label(v, BLEND_MODE_LABELS)
                elif fn == 'direction_mode':
                    label = _enum_to_label(v, DIRECTION_MODE_LABELS)
                elif fn == 'move_mode':
                    label = _enum_to_label(v, MOVE_MODE_LABELS)
                else:
                    label = str(v)
                idx_c = widget.findText(label)
                if idx_c >= 0:
                    widget.setCurrentIndex(idx_c)
                    if widget.isEditable():
                        self._sync_editable_combo_value(widget, idx_c)
                elif widget.isEditable():
                    widget.setCurrentText(str(v))
                widget.blockSignals(False)

        # 同步卡片里的 combo
        blend_combo = vars_row.get('_blend_combo')
        if blend_combo:
            blend_combo.blockSignals(True)
            label = _enum_to_label(vals[11], BLEND_MODE_LABELS)
            idx_c = blend_combo.findText(label)
            if idx_c >= 0:
                blend_combo.setCurrentIndex(idx_c)
            blend_combo.blockSignals(False)

        loop_combo = vars_row.get('_loop_combo')
        if loop_combo:
            loop_combo.blockSignals(True)
            v = vals[19]
            label = _enum_to_label(v, LOOP_BEHAVIOR_LABELS)
            idx_c = loop_combo.findText(label)
            if idx_c >= 0:
                loop_combo.setCurrentIndex(idx_c)
                self._sync_editable_combo_value(loop_combo, idx_c)
            elif loop_combo.isEditable():
                loop_combo.setCurrentText(str(v))
            loop_combo.blockSignals(False)

        # 帧范围标签
        fl = vars_row.get('_frame_lbl')
        if fl:
            fl.setText(f"[{vals[17]}..{vals[18]}]")

        self._auto_fill_enabled = True
        self._update_layer_probe(layer_idx)

    # ── 图层探针 ──

    def _update_layer_probe(self, layer_idx):
        vr = self._layer_vars[layer_idx]
        lbl = vr.get('_probe_lbl')
        if lbl is None:
            return

        def _iv(key, default=0):
            try:
                w = vr.get(key)
                if w is None:
                    return default
                if isinstance(w, QLineEdit):
                    raw = w.text()
                elif isinstance(w, EditorComboBox):
                    raw = w.currentText()
                else:
                    return default
                raw = raw.split(' ', 1)[0] if raw else ''
                return int(raw) if raw.lstrip('-').isdigit() else default
            except Exception:
                return default

        combo = vr.get('_type_combo')
        type_lbl = combo.currentText() if combo else ''
        try:
            ltype = int(type_lbl.split(' ', 1)[0]) if type_lbl else 0
        except Exception:
            ltype = 0

        blk = _iv('jvg_block_index', -1)
        dfo = _iv('dir_frame_offset', 0)
        first = _iv('first_frame', 0)
        last = _iv('last_frame', 0)
        dmode = _iv('direction_mode', 0)

        if ltype == 0:
            lbl.setText("— (空图层)")
            return

        if ltype >= 4:
            name = {4: '坐标锚点', 5: '结束标记'}.get(ltype, '非渲染')
            lbl.setText(f"— {name} (无 JVG 引用)")
            return

        if ltype == 1:
            src_name, counts = 'Aa.jvg', self._aa_counts
        else:
            src_name, counts = 'Af.jvg', self._af_counts

        if not counts:
            lbl.setText(f"{src_name}[{blk}]  (未加载 JVG, 无法探测实际帧数)")
            return
        if blk < 0 or blk >= len(counts):
            lbl.setText(f"{src_name}[{blk}]  ✗ 块号越界 (共 {len(counts)} 块)")
            return

        n_frames = counts[blk]
        dirs, per, is_std = infer_jvg_layout(n_frames)
        per_dir_act = (last - first + 1) if last >= first else 0

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

        warn = ''
        if last >= n_frames or first < 0:
            warn = f"  ⚠ 方向 0 切片 {first}..{last} 越出池 0..{n_frames-1}"

        info = ''
        if is_std and dfo > 0 and dfo != per and dmode == 4:
            info = f"  (dfo={dfo} ≠ 推断 {per}, 非标准切片)"

        if warn:
            color = '#C33'
        elif is_std and not info:
            color = '#093'
        else:
            color = '#AAA'

        lbl.setText(
            f"{src_name}[{blk}]  实际 {n_frames} 帧   {layout_desc}{info}\n"
            f"    {span_desc}   切片量 {used}/{n_frames} ({pct}%){warn}")
        if color == '#C33':
            lbl.setProperty("probe", "error")
        elif color == '#093':
            lbl.setProperty("probe", "ok")
        elif color == '#C60':
            lbl.setProperty("probe", "warn")
        else:
            lbl.setProperty("probe", "empty")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

    def _on_layer_field_change(self, layer_idx, field_name):
        self._update_layer_probe(layer_idx)
        if field_name == 'jvg_block_index' and self._auto_fill_enabled:
            self._auto_fill_jvg_params(layer_idx)

    def _on_layer_type_changed(self, layer_idx):
        self._update_layer_probe(layer_idx)

    def _auto_fill_jvg_params(self, layer_idx):
        vr = self._layer_vars[layer_idx]

        try:
            w = vr.get('jvg_block_index')
            if isinstance(w, QLineEdit):
                blk = int(w.text() or '0')
            else:
                return
        except (ValueError, AttributeError):
            return
        if blk <= 0:
            return

        combo = vr.get('_type_combo')
        type_str = combo.currentText() if combo else ''
        try:
            ltype = int(type_str.split(' ', 1)[0]) if type_str else 0
        except ValueError:
            ltype = 0

        if ltype == 1:
            counts = self._aa_counts
        elif ltype in (2, 3):
            counts = self._af_counts
        else:
            return

        if not counts or blk >= len(counts):
            return
        n_frames = counts[blk]
        if n_frames <= 0:
            return

        dirs, per, _ = infer_jvg_layout(n_frames)
        if dirs < 1:
            return

        for key, val in [
            ('direction_mode', f'{dirs} {"四向感知" if dirs == 4 else "双向感知" if dirs == 2 else f"{dirs}向"}'),
            ('first_frame', '0'),
            ('last_frame', str(per - 1)),
            ('dir_frame_offset', str(per)),
            ('loop_behavior', str(per - 1)),
        ]:
            w = vr.get(key)
            if isinstance(w, QLineEdit):
                w.setText(val)
            elif isinstance(w, EditorComboBox):
                idx_c = w.findText(val, Qt.MatchStartsWith)
                if idx_c >= 0:
                    w.setCurrentIndex(idx_c)

        self._update_layer_probe(layer_idx)

    # ── 编辑操作 ──

    def _get_layer_val(self, layer_idx, field_idx):
        """从 UI 变量读取图层字段值 (用于时间轴显示)"""
        if self._editing_idx < 0:
            return 0
        return self.entries[self._editing_idx]['layers'][layer_idx][field_idx]

    def _get_layer_offset(self, slot, eff_dir, axis):
        """读取图层位移值"""
        if self._editing_idx < 0:
            return 0
        L = self.entries[self._editing_idx]['layers'][slot - 1]
        if axis == 'x':
            return L[3 + eff_dir]
        else:
            return L[7 + eff_dir]

    def _apply_edit(self):
        if self._editing_idx < 0:
            return
        entry = self.entries[self._editing_idx]

        for d in range(4):
            for i in range(8):
                if self._dir_vars[d][i] is not None:
                    try:
                        v = int(self._dir_vars[d][i].text() or 0)
                    except ValueError:
                        v = 0
                    entry['dirs'][d][i] = max(0, min(255, v))

        for s in range(ACT_MAX_LAYER):
            vals = entry['layers'][s]
            vr = self._layer_vars[s]
            combo = vr.get('_type_combo')
            if combo:
                vals[0] = _label_to_enum(combo.currentText(), LAYER_TYPE_LABELS)

            for (fn, idx, _, _, _) in ALL_FIELDS:
                if fn == 'layer_type' or fn not in vr:
                    continue
                w = vr[fn]
                if isinstance(w, QLineEdit):
                    raw = w.text()
                elif isinstance(w, EditorComboBox):
                    raw = w.currentText()
                else:
                    continue

                if fn == 'blend_mode':
                    v = _label_to_enum(raw, BLEND_MODE_LABELS)
                elif fn == 'direction_mode':
                    v = _label_to_enum(raw, DIRECTION_MODE_LABELS)
                elif fn == 'loop_behavior':
                    v = _label_to_enum(raw, LOOP_BEHAVIOR_LABELS)
                elif fn == 'move_mode':
                    v = _label_to_enum(raw, MOVE_MODE_LABELS)
                else:
                    try:
                        v = int((raw or '0').strip())
                    except ValueError:
                        v = 0
                vals[idx] = max(-32768, min(32767, v))

        for k in range(24):
            if k < len(self._param_vars):
                try:
                    v = int(self._param_vars[k].text() or 0)
                except ValueError:
                    v = 0
                entry['param16'][k] = max(-32768, min(32767, v))

        for k in range(32):
            if k < len(self._tail_vars):
                try:
                    v = int(self._tail_vars[k].text() or 0)
                except ValueError:
                    v = 0
                entry['tail'][k] = max(-32768, min(32767, v))

        self._dirty = True
        self._apply_filter()
        self._populate_edit(entry)
        self.status_var.setText(f"动画 #{entry['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx >= 0 and self._edit_snapshot is not None:
            snap = self._edit_snapshot
            entry = self.entries[self._editing_idx]
            entry['dirs'] = [list(d) for d in snap['dirs']]
            entry['param16'] = list(snap['param16'])
            entry['layers'] = [list(L) for L in snap['layers']]
            entry['tail'] = list(snap['tail'])
            self._dirty = False
            self._preview_vis.clear()
            self._populate_edit(entry)
            self.status_var.setText("已重置为编辑前的状态")

    def _make_empty_entry(self, idx):
        return {
            'index': idx,
            'dirs': [[0] * 8 for _ in range(4)],
            'param16': [0] * 24,
            'layers': [[0] * 40 for _ in range(ACT_MAX_LAYER)],
            'tail': [0] * 32,
        }

    def _new_entry(self, source=None):
        if not self.entries:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        idx = len(self.entries)
        entry = self._make_empty_entry(idx)
        self.entries.append(entry)
        self._dirty = True
        self.search_entry.clear()
        if not self.show_empty_cb.isChecked():
            self.show_empty_cb.setChecked(True)
        else:
            self._apply_filter()
        self._select_entry(idx)
        self._populate_edit(entry)
        self.status_var.setText(
            f"已新增空条目 #{idx} (共 {len(self.entries)} 条, 已修改)")

    def _remove_extended_entry(self, idx):
        if idx < ACT_ENTRY_COUNT or idx >= len(self.entries):
            return
        if QMessageBox.question(
                self, "确认移除",
                f"确定移除扩展条目 #{idx} 吗？\n"
                "扩展区条目移除后，后续条目序号会自动前移。",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.entries.pop(idx)
        for i, entry in enumerate(self.entries):
            entry['index'] = i
        self._dirty = True
        self._editing_idx = -1
        self._preview_stop()
        self._apply_filter()
        self.status_var.setText(
            f"已移除扩展条目 #{idx} (共 {len(self.entries)} 条, 已修改)")

    def _clear_entry_at(self, idx, ask=True, title="确认清除", question_text=None):
        if idx < 0 or idx >= len(self.entries):
            return False
        entry = self.entries[idx]
        if entry_is_empty(entry):
            return False
        if ask and QMessageBox.question(
                self, title,
                question_text or f"确定要清除条目 #{idx} 吗？\n此操作不可撤销。",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        self.entries[idx] = self._make_empty_entry(idx)
        self._dirty = True
        if not self.show_empty_cb.isChecked():
            self.show_empty_cb.setChecked(True)
        else:
            self._apply_filter()
        if self._editing_idx == idx:
            self._populate_edit(self.entries[idx])
            self._preview_stop()
            self._preview_redraw()
            self._tl_redraw()
        return True

    def _clear_entry(self):
        if self._editing_idx < 0:
            return
        if self._clear_entry_at(self._editing_idx):
            self.status_var.setText(f"已清除条目 #{self._editing_idx}")
        elif self._editing_idx < len(self.entries) and entry_is_empty(self.entries[self._editing_idx]):
            QMessageBox.information(self, "提示", "当前条目已经为空")

    def _clear_entry_idx(self, idx):
        if self._clear_entry_at(idx):
            self.status_var.setText(f"已清除条目 #{idx}")
        elif idx < len(self.entries) and entry_is_empty(self.entries[idx]):
            QMessageBox.information(self, "提示", "当前条目已经为空")

    def _delete_entry(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx < 0 or idx >= len(self.entries):
            return
        if idx < ACT_ENTRY_COUNT:
            QMessageBox.information(
                self, "提示",
                f"原版条目 #{idx} 不能删除，只能使用清除功能。")
            return
        self._remove_extended_entry(idx)

    def _delete_current(self):
        self._delete_entry()

    # ── 保存/导出 ──

    def _save(self):
        if not self.act_path or not self.entries:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        if QMessageBox.question(self, "确认保存",
                f"保存 {len(self.entries)} 条到:\n{self.act_path}\n\n原文件将被覆盖 (生成 .bak).",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with open(self.act_path, 'rb') as s:
                with open(self.act_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
        try:
            self.status_var.setText("正在保存…")
            QApplication.processEvents()
            save_act(self.act_path, self.entries)
            self._dirty = False
            self.status_var.setText(f"已保存 → {self.act_path}")
            QMessageBox.information(self, "保存成功",
                                   f"已保存\n备份: {self.act_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出 TKAct.dat 为 .tksmod — 记录级增量（仅导出修改过的动画条目）"""
        if not self.entries or not self.act_path:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 序列化函数（用于差异比对）
        def entry_to_bytes(entry):
            buf = bytearray(ACT_ENTRY_SIZE)
            for d in range(4):
                buf[d*8:d*8+8] = bytes(v & 0xFF for v in entry['dirs'][d])
            struct.pack_into('<24h', buf, ACT_PARAM_OFFSET, *entry['param16'])
            for s in range(ACT_MAX_LAYER):
                lo = (s+1) * ACT_LAYER_SIZE
                struct.pack_into('<40h', buf, lo, *entry['layers'][s])
            struct.pack_into('<32h', buf, ACT_TAIL_OFFSET, *entry['tail'])
            return bytes(buf)

        cur_blocks = [entry_to_bytes(e) for e in self.entries]

        def _compute_stats(ref_dir):
            ref_path = os.path.join(ref_dir, "TKAct.dat")
            if not os.path.isfile(ref_path):
                return {"valid": False, "error": "目录中未找到 TKAct.dat"}
            try:
                ref_entries = load_act(ref_path)
            except Exception as e:
                return {"valid": False, "error": f"TKAct.dat 解析失败: {e}"}
            ref_blocks = [entry_to_bytes(e) for e in ref_entries]
            diff = diff_binary_blocks(ref_blocks, cur_blocks)
            targets = []
            if diff['modified'] or diff['appended'] or diff['deleted_indices']:
                targets.append({"name": "TKAct.dat",
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": len(diff['deleted_indices'])})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.act_path) if self.act_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_path = os.path.join(ref_dir, "TKAct.dat")
        if not os.path.isfile(ref_path):
            QMessageBox.warning(self, "参考文件不存在", f"在 {ref_dir} 中未找到 TKAct.dat")
            return
        try:
            ref_entries = load_act(ref_path)
        except Exception as e:
            QMessageBox.warning(self, "参考文件无效", str(e))
            return
        ref_blocks = [entry_to_bytes(e) for e in ref_entries]

        diff_result = diff_binary_blocks(ref_blocks, cur_blocks)
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前动画数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        crc = compute_crc32(ref_path)
        data_json = build_block_diff_json(target="TKAct.dat", block_type="act_entry",
            original_count=len(ref_entries), original_crc32=crc, diff_result=diff_result)
        components = [{"file": "data/TKAct.dat.json", "target": "TKAct.dat"}]
        mod_json = generate_mod_json(metadata, components)

        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKAct.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 新增{n_app}条)")
            QMessageBox.information(self, "导出成功",
                f"已导出 (记录级增量):\n{fp}\n\n参考: {ref_path}\n修改: {n_mod} 条动画记录\n新增: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到 TKAct 编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        if "TKAct.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 TKAct.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.act_path) if self.act_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, blocks = import_tksmod_blocks(
            fp, ref_dir, "TKAct.dat", block_type="act_entry")
        if blocks is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 TKAct.dat")
            return

        # 将块字节重新解析为 entries 结构
        new_entries = []
        for i, blk in enumerate(blocks):
            if len(blk) < ACT_ENTRY_SIZE:
                blk = blk + bytes(ACT_ENTRY_SIZE - len(blk))
            data = blk[:ACT_ENTRY_SIZE]
            dirs = [list(data[d*8:d*8+8]) for d in range(4)]
            param16 = list(struct.unpack_from('<24h', data, ACT_PARAM_OFFSET))
            layers = [list(struct.unpack_from('<40h', data, (s+1)*ACT_LAYER_SIZE))
                      for s in range(ACT_MAX_LAYER)]
            tail = list(struct.unpack_from('<32h', data, ACT_TAIL_OFFSET))
            new_entries.append({
                'index': i, 'dirs': dirs,
                'param16': param16, 'layers': layers, 'tail': tail,
            })

        self.entries = new_entries
        self._dirty = False

        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(new_entries)} 条动画记录")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(new_entries)} 条动画记录。\n"
            f"您现在可以继续编辑并重新导出。")

    # ── 编辑状态 ──

    def _set_edit_enabled(self, en):
        self.tabs.setEnabled(en)
        self._center_widget.setEnabled(en)

    def _on_greenscreen_toggle(self):
        self._greenscreen_remove = self.greenscreen_cb.isChecked()
        self._jvg_cache.clear()
        self._pil_cache.clear()
        self._preview_redraw()

    # ── 尾部数据 ──

    def _refresh_tail_file_lbl(self, pair_idx):
        if pair_idx >= len(self._tail_file_lbls) or pair_idx * 2 >= len(self._tail_vars):
            return
        lbl = self._tail_file_lbls[pair_idx]
        try:
            sid = int(self._tail_vars[pair_idx * 2].text() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            lbl.setText("(空位)")
            lbl.setProperty("probe", "empty")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        if self.sws_grp is None:
            lbl.setText(f"SWS#{sid:04d}  (未加载 TKS 目录)")
            lbl.setProperty("probe", "warn")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        info = self.sws_grp.wav_info(sid)
        if info is not None:
            ch, sr, bits, dur = info
            lbl.setText(f"SWS#{sid:03d}  {ch}ch {sr}Hz {bits}bit {dur:.2f}s")
            lbl.setProperty("probe", "ok")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        if sid >= self.sws_grp.section_count:
            lbl.setText(f"SWS#{sid}  X 超出段数({self.sws_grp.section_count})")
            lbl.setProperty("probe", "error")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        lbl.setText(f"SWS#{sid:03d}  (非 WAV 段)")
        lbl.setProperty("probe", "warn")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

    def _resolve_sound_path(self, sid):
        if sid <= 0 or self.sws_grp is None:
            return None
        return self.sws_grp.extract_to_temp(sid)

    def _on_tail_preview(self, pair_idx):
        try:
            sid = int(self._tail_vars[pair_idx * 2].text() or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            self.status_var.setText(f"尾部 #{pair_idx:02d}: sound_id=0 空位, 无音效")
            return
        if self.sws_grp is None:
            QMessageBox.information(self, "未加载音效源",
                                   "请先通过 文件 → 加载 TKS 目录 来定位 SWS.GRP")
            return
        p = self._resolve_sound_path(sid)
        if not p:
            self.status_var.setText(f"未找到音效 sid={sid} (SWS.GRP)")
            return
        alias = _mci_play_async(p)
        if alias is None:
            self.status_var.setText(f"播放失败: sid={sid}")
        else:
            self.status_var.setText(f"> sid={sid} (SWS)")

    # ============================================================
    # 动画预览
    # ============================================================

    def _preview_active_layers(self, direction):
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
            eff_dir = direction if (L[2] == 4 or L[0] < 3) else 0
            out.append((slot, eff_dir, L))
        return out

    def _preview_load_jvg(self):
        if not HAS_PIL:
            return False
        if _get_jvg_loader() is None:
            return False
        try:
            if self.aa_path and not self._aa_data:
                r = _LazyJvgReader(self.aa_path)
                if r.valid:
                    self._aa_data = r
                    self._aa_counts = r.frame_counts
            if self.af_path and not self._af_data:
                r = _LazyJvgReader(self.af_path)
                if r.valid:
                    self._af_data = r
                    self._af_counts = r.frame_counts
        except Exception:
            pass
        return (self._aa_data is not None) or (self._af_data is not None)

    def _preview_get_pil(self, src, block_idx, frame_idx):
        key = (src, block_idx, frame_idx)
        cached = self._pil_cache.get(key)
        if cached is not None:
            return cached
        jvg = self._aa_data if src == 'aa' else self._af_data
        if jvg is None or block_idx < 0 or block_idx >= jvg.block_count:
            return None
        blk = jvg.get_block(block_idx)
        if frame_idx < 0 or frame_idx >= blk.frame_count:
            return None
        f = blk.frames[frame_idx]
        if f.width <= 0 or f.height <= 0:
            return None
        pal_rgb = blk.palette.to_rgb888()
        no_green = self._greenscreen_remove
        if no_green:
            green_set = {i for i, e in enumerate(blk.palette.entries) if e == 0x07E0}
        rgba = bytearray(f.width * f.height * 4)
        for py in range(f.height):
            base = py * f.width
            for px in range(f.width):
                p = base + px
                if p < len(f.alpha) and f.alpha[p] == 0:
                    continue
                idx = f.pixels[p] if p < len(f.pixels) else 0
                if no_green and idx in green_set:
                    continue
                o = p * 4
                rgba[o] = pal_rgb[idx * 3]
                rgba[o + 1] = pal_rgb[idx * 3 + 1]
                rgba[o + 2] = pal_rgb[idx * 3 + 2]
                rgba[o + 3] = 255
        try:
            img = Image.frombytes('RGBA', (f.width, f.height), bytes(rgba))
            self._pil_cache[key] = img
            return img
        except Exception:
            return None

    def _compute_entry_bbox(self, entry):
        if self._aa_data is None and self._af_data is None:
            return None
        xs = [0, PREVIEW_ENEMY_X]
        ys = [0]
        for direction in range(4):
            order = [v for v in entry['dirs'][direction] if v]
            if not order:
                order = sorted(entry_active_layers(entry))
            for slot in order:
                if slot < 1 or slot > ACT_MAX_LAYER:
                    continue
                L = entry['layers'][slot - 1]
                if L[0] == 0:
                    continue
                src = 'aa' if L[0] == 1 else 'af'
                jvg = self._aa_data if src == 'aa' else self._af_data
                pk = L[1]
                if jvg is None or pk < 0 or pk >= jvg.block_count:
                    continue
                blk = jvg.get_block(pk)
                n = blk.frame_count
                if n <= 0:
                    continue
                eff_dir = direction if (L[2] == 4 or L[0] < 3) else 0
                ox = L[3 + eff_dir]
                oy = L[7 + eff_dir]
                base_x = PREVIEW_ENEMY_X if L[0] in (3, 4) else 0
                for fi in range(n):
                    f = blk.frames[fi]
                    if f.width <= 0 or f.height <= 0:
                        continue
                    l = f.x_off + ox + base_x
                    t = f.y_off + oy
                    r = l + f.width - 1
                    b = t + f.height - 1
                    xs.extend([l, r])
                    ys.extend([t, b])
        if len(xs) < 2 or len(ys) < 2:
            return None
        return (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + 10)

    def _preview_reload(self):
        self._preview_stop()
        if self._editing_idx < 0:
            return
        if not self._aa_data and not self._af_data:
            self._preview_load_jvg()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        self._preview_bbox = self._compute_entry_bbox(
            self.entries[self._editing_idx])
        self._preview_update_vis()
        self._preview_redraw()

    def _preview_update_vis(self):
        saved_vis = {slot: cb.isChecked() for slot, cb in self._preview_vis.items()}
        self._preview_vis.clear()

        # 清空可见性控件
        while self._vis_layout.count():
            item = self._vis_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._editing_idx < 0:
            return

        entry = self.entries[self._editing_idx]
        slots = entry_referenced_layers(entry) | entry_active_layers(entry)
        if not slots:
            return

        for slot in sorted(slots):
            t = entry['layers'][slot - 1][0]
            default_vis = saved_vis.get(slot, True)
            cb = QCheckBox(f"#{slot}(t={t})")
            cb.setChecked(default_vis)
            cb.stateChanged.connect(lambda state, s=slot: self._preview_redraw())
            self._vis_layout.addWidget(cb)
            self._preview_vis[slot] = cb

    # ── 播放控制 ──

    def _preview_play(self):
        if self._editing_idx < 0:
            return
        if not self._aa_data and not self._af_data:
            if not self._preview_load_jvg():
                return
        self._preview_stop()
        self._preview_tick_idx = 0
        self._preview_played_ticks = set()
        self._last_time = time.perf_counter()
        self._tick_accumulator = 0.0
        self._is_playing = True

        if self._play_timer is None:
            self._play_timer = QTimer(self)
            self._play_timer.timeout.connect(self._preview_tick_loop)
        self._play_timer.start(5)

    def _preview_stop(self):
        self._is_playing = False
        if self._play_timer:
            self._play_timer.stop()
        for a in list(self._preview_sfx_aliases):
            _mci_close(a)
        self._preview_sfx_aliases = []

    def _preview_tick_loop(self):
        if not self._is_playing:
            return

        cur = time.perf_counter()
        dt = cur - self._last_time
        self._last_time = cur

        tick_duration = max(10, self._speed_spin.value()) / 1000.0
        self._tick_accumulator += dt

        ticks_to_advance = 0
        while self._tick_accumulator >= tick_duration:
            ticks_to_advance += 1
            self._tick_accumulator -= tick_duration

        if ticks_to_advance > 0:
            old_tick = self._preview_tick_idx
            self._preview_tick_idx += ticks_to_advance

            for missed_tick in range(old_tick + 1, self._preview_tick_idx + 1):
                self._preview_sync_sfx_for_tick(missed_tick)

            all_stopped = self._preview_redraw()
            self._tl_tick_lbl.setText(f"tick: {self._preview_tick_idx}")
            self.timeline_widget.set_playhead(self._preview_tick_idx)

            if all_stopped:
                self._is_playing = False
                self._play_timer.stop()

    def _preview_sync_sfx_for_tick(self, tick):
        if self._editing_idx < 0 or self.sws_grp is None:
            return
        entry = self.entries[self._editing_idx]
        tail = entry.get('tail') or []
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0 or trig != tick:
                continue
            key = (i, tick)
            if key in self._preview_played_ticks:
                continue
            self._preview_played_ticks.add(key)
            path = self._resolve_sound_path(sid)
            if not path:
                continue
            alias = _mci_play_async(path)
            if alias:
                self._preview_sfx_aliases.append(alias)

    def _on_dir_changed(self, btn):
        self._preview_dir = self._dir_btns.id(btn)
        self._preview_redraw()

    def _preview_redraw(self):
        if self._editing_idx < 0:
            return False

        direction = self._dir_btns.checkedId()
        if direction < 0:
            direction = 0
        self._preview_dir = direction

        layers = self._preview_active_layers(direction)
        if not layers:
            self.preview_canvas.set_frame_data(
                None, 0, 0, [], (0, 0), (0, 0),
                [f"方向 {direction}: 无活跃图层"], False,
                self._preview_tick_idx, direction, 1.0, 0, 0, None)
            return False

        tick = self._preview_tick_idx
        sprites = []
        dyn_x, dyn_y = [], []
        n_stoppable = 0
        n_stopped = 0
        _layer_diag = []

        for slot, eff_dir, L in layers:
            cb = self._preview_vis.get(slot)
            if cb is not None and not cb.isChecked():
                _layer_diag.append(f"#{slot} 隐藏")
                continue

            src = 'aa' if L[0] == 1 else 'af'
            pk = L[1]
            jvg = self._aa_data if src == 'aa' else self._af_data
            if jvg is None or pk < 0 or pk >= jvg.block_count:
                _layer_diag.append(f"#{slot} JVG缺失")
                continue

            blk = jvg.get_block(pk)
            n_frames = blk.frame_count
            if n_frames <= 0:
                _layer_diag.append(f"#{slot} 0帧")
                continue

            cur_abs, stopped = _compute_layer_frame(L, tick)
            span = max(1, L[18] - L[17] + 1)
            delay = L[22]
            interval = max(1, L[21])
            eff_tick = max(0, tick - delay)
            frame_adv = eff_tick // interval

            if tick < delay:
                _layer_diag.append(f"#{slot} L={L[19]} 延迟中(delay={delay})")
                continue

            _layer_diag.append(
                f"#{slot} L={L[19]} fadv={frame_adv}/{span}"
                f"{' STOP' if stopped else ''}")

            if L[19] != -1:
                n_stoppable += 1
                if stopped:
                    n_stopped += 1
                    if L[19] == -2:
                        continue

            if L[2] == 4:
                cur_abs += L[16] * eff_dir
            cur_abs = cur_abs % n_frames if n_frames > 0 else 0
            frame = blk.frames[cur_abs]

            ox = L[3 + eff_dir]
            oy = L[7 + eff_dir]
            enemy_x = PREVIEW_ENEMY_X if L[0] in (3, 4) else 0
            spr_l = frame.x_off + ox + enemy_x
            spr_t = frame.y_off + oy
            spr_r = spr_l + frame.width - 1
            spr_b = spr_t + frame.height - 1
            dyn_x.extend([spr_l, spr_r, -ox - enemy_x])
            dyn_y.extend([spr_t, spr_b, -oy])
            sprites.append((slot, eff_dir, L, src, blk, cur_abs, frame,
                           ox, oy, spr_l, spr_t, spr_r, spr_b, False))

        if not sprites:
            self.preview_canvas.set_frame_data(
                None, 0, 0, [], (0, 0), (0, 0),
                [f"方向 {direction}: 无可渲染帧"], False,
                tick, direction, 1.0, 0, 0, None)
            return False

        # 包围盒
        if self._preview_bbox is not None:
            bbox_l, bbox_t, bbox_r, bbox_b = self._preview_bbox
        else:
            bbox_l = min(dyn_x)
            bbox_r = max(dyn_x)
            bbox_t = min(dyn_y)
            bbox_b = max(dyn_y)

        cw = self.preview_canvas.width()
        ch = self.preview_canvas.height()
        if cw < 10 or ch < 10:
            return False

        bw = max(bbox_r - bbox_l, 1)
        bh = max(bbox_b - bbox_t, 1)
        scale = 1.0  # 固定 100% 比例, 不随预览区大小缩放

        draw_w = bw * scale
        draw_h = bh * scale
        off_x = (cw - draw_w) / 2 - bbox_l * scale
        off_y = (ch - draw_h) / 2 - bbox_t * scale

        def to_cv(gx, gy):
            return (off_x + gx * scale, off_y + gy * scale)

        ox_c, oy_c = to_cv(0, 0)
        ex_c, ey_c = to_cv(PREVIEW_ENEMY_X, 0)

        # PIL 合成
        comp_w = max(1, int(bw * scale))
        comp_h = max(1, int(bh * scale))
        CANVAS_BG_RGB = (0x1a, 0x1e, 0x27)
        try:
            composite = Image.new('RGB', (comp_w, comp_h), CANVAS_BG_RGB)
        except Exception:
            composite = None
        comp_ox, comp_oy = to_cv(bbox_l, bbox_t)

        sprite_boxes = []
        slot_colors = SLOT_COLORS
        info = [f"方向{direction} | 可见{len(sprites)}图层 | Tick:{tick}"]

        for sp in sprites:
            (slot, eff_dir, L, src, blk, cur_abs, frame,
             ox, oy, spr_l, spr_t, spr_r, spr_b, stopped) = sp
            pk = L[1]
            blend_mode = L[11]
            blend_param = L[12]

            _bm_label = {
                0: '正常', 1: '染色', 2: '加法',
                3: '减法', 4: '亮度融合', 5: '翻转',
            }.get(blend_mode, f'?{blend_mode}')

            pil = self._preview_get_pil(src, pk, cur_abs)
            if pil is None:
                continue

            pil_blended = _apply_blend(pil, blend_mode, blend_param)
            if pil_blended is None:
                continue

            cx, cy = to_cv(spr_l, spr_t)
            nw = max(1, int(frame.width * scale))
            nh = max(1, int(frame.height * scale))

            try:
                if nw == frame.width and nh == frame.height:
                    final_img = pil_blended
                else:
                    final_img = pil_blended.resize((nw, nh), Image.NEAREST)
                if composite is not None:
                    dx = int(round((spr_l - bbox_l) * scale))
                    dy = int(round((spr_t - bbox_t) * scale))
                    if blend_mode == 2:
                        _composite_additive(composite, final_img, dx, dy, blend_param)
                    elif blend_mode == 3:
                        _composite_subtract(composite, final_img, dx, dy)
                    elif blend_mode == 4:
                        _composite_luma_alpha(composite, final_img, dx, dy)
                    else:
                        composite.paste(final_img, (dx, dy), final_img)
            except Exception:
                continue

            sprite_boxes.append((slot, eff_dir, cx, cy, cx + nw, cy + nh, ox, oy))

            info.append(
                f"  #{slot} src={src} blk={pk} t={L[0]} dir={eff_dir} "
                f"f={cur_abs+1}/{blk.frame_count} "
                f"off=({ox:+d},{oy:+d}) "
                f"blend={blend_mode}/{_bm_label}(p={blend_param}) "
                f"int={L[21]} delay={L[22]} "
                f"[{L[17]}..{L[18]}] loop={L[19]}"
                f"{' [STOP]' if stopped else ''}")

        # 转换 composite 为 QPixmap
        comp_pixmap = pil_to_qpixmap(composite) if composite else None

        all_stopped = n_stoppable > 0 and n_stopped >= n_stoppable
        info.append(f"loop=-2: {n_stopped}/{n_stoppable}")
        for diag in _layer_diag:
            info.append(diag)

        self.preview_canvas.set_frame_data(
            comp_pixmap, comp_ox, comp_oy,
            sprite_boxes, (ox_c, oy_c), (ex_c, ey_c),
            info, all_stopped,
            tick, direction, scale, off_x, off_y,
            self._preview_bbox)

        return all_stopped

    # ── 预览拖拽 ──

    def _preview_apply_drag(self, slot, eff_dir, gdx, gdy):
        if self._editing_idx < 0:
            return
        entry = self.entries[self._editing_idx]
        L = entry['layers'][slot - 1]
        new_ox = L[3 + eff_dir] + gdx
        new_oy = L[7 + eff_dir] + gdy
        L[3 + eff_dir] = max(-32768, min(32767, new_ox))
        L[7 + eff_dir] = max(-32768, min(32767, new_oy))
        self._dirty = True
        self._populate_layer(slot - 1, L)
        self._preview_redraw()

    def _preview_finish_drag(self):
        if self._editing_idx >= 0:
            entry = self.entries[self._editing_idx]
            self._populate_edit(entry)

    # ── 时间轴 ──

    def _tl_calc_duration(self, entry):
        max_tick = 0
        for s in range(ACT_MAX_LAYER):
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            delay = L[22]
            interval = max(1, L[21])
            first = L[17]
            last = L[18]
            span = max(1, last - first + 1)
            dur = delay + span * interval
            if dur > max_tick:
                max_tick = dur
        return max_tick

    def _tl_redraw(self):
        if self._editing_idx < 0:
            self.timeline_widget.set_data(0, [], [])
            self.thumb_strip.clear()
            return

        entry = self.entries[self._editing_idx]
        zoom = self.timeline_widget.zoom()

        layers_info = []
        for s in range(ACT_MAX_LAYER):
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            delay = L[22]
            interval = max(1, L[21])
            first = L[17]
            last = L[18]
            span = max(1, last - first + 1)
            play_ticks = span * interval
            layers_info.append((s, L[0], delay, play_ticks, L[19], L[21]))

        # 音效标记
        tail = entry.get('tail') or []
        sfx_markers = []
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0 or trig < 0:
                continue
            sfx_markers.append((0, 0, sid, trig, i))

        self.timeline_widget.set_data(self._preview_tick_idx, layers_info, sfx_markers)
        self._tl_refresh_thumbnails()

    def _tl_refresh_thumbnails(self):
        if self._editing_idx < 0 or not HAS_PIL:
            self.thumb_strip.clear()
            return

        if not self._tl_selected_layers:
            self.thumb_strip.clear()
            return

        if not self._aa_data and not self._af_data:
            self._preview_load_jvg()

        entry = self.entries[self._editing_idx]
        # 取选中图层中最小索引作为缩略图代表
        display_layer = min(self._tl_selected_layers)
        L = entry['layers'][display_layer]
        ltype = L[0]
        block_idx = L[1]
        if ltype == 0 or block_idx <= 0:
            self.thumb_strip.clear()
            return

        src = 'aa' if ltype == 1 else 'af'
        jvg = self._aa_data if src == 'aa' else self._af_data

        if jvg is None or block_idx >= jvg.block_count:
            self.thumb_strip.clear()
            return

        blk = jvg.get_block(block_idx)
        total_frames = blk.frame_count
        if total_frames == 0:
            self.thumb_strip.clear()
            return

        pixmaps = []
        thumb_h = 40
        for fi in range(total_frames):
            pil_img = self._preview_get_pil(src, block_idx, fi)
            if pil_img is None:
                pixmaps.append(None)
                continue
            w, h = pil_img.size
            if h <= 0:
                pixmaps.append(None)
                continue
            ratio = thumb_h / h
            tw = max(1, int(w * ratio))
            thumb = pil_img.resize((tw, thumb_h), Image.NEAREST)
            pixmaps.append(pil_to_qpixmap(thumb))

        self.thumb_strip.set_data(pixmaps, total_frames, L[17], L[18], L[16])

    def _on_timeline_clicked(self, tick):
        self._preview_stop()
        self._preview_tick_idx = tick
        self._tl_tick_lbl.setText(f"tick: {tick}")
        self._preview_redraw()

    def _on_thumb_range_changed(self, first, last):
        if self._editing_idx < 0 or not self._tl_selected_layers:
            return
        entry = self.entries[self._editing_idx]
        display_layer = min(self._tl_selected_layers)
        L = entry['layers'][display_layer]
        L[17] = first
        L[18] = last
        self._dirty = True
        self._populate_layer(display_layer, L)
        self._tl_redraw()
        self._preview_stop()
        self._preview_redraw()

    def _tl_goto_first(self):
        self._preview_stop()
        self._preview_tick_idx = 0
        self._tl_tick_lbl.setText("tick: 0")
        self.timeline_widget.set_playhead(0)
        self._preview_redraw()

    def _tl_goto_last(self):
        if self._editing_idx >= 0:
            entry = self.entries[self._editing_idx]
            dur = self._tl_calc_duration(entry)
        else:
            dur = 0
        self._preview_stop()
        self._preview_tick_idx = dur
        self._tl_tick_lbl.setText(f"tick: {dur}")
        self.timeline_widget.set_playhead(dur)
        self._preview_redraw()

    def _tl_step_prev(self):
        self._preview_stop()
        self._preview_tick_idx = max(0, self._preview_tick_idx - 1)
        self._tl_tick_lbl.setText(f"tick: {self._preview_tick_idx}")
        self.timeline_widget.set_playhead(self._preview_tick_idx)
        self._preview_redraw()

    def _tl_step_next(self):
        self._preview_stop()
        self._preview_tick_idx += 1
        self._tl_tick_lbl.setText(f"tick: {self._preview_tick_idx}")
        self.timeline_widget.set_playhead(self._preview_tick_idx)
        self._preview_redraw()

    def _tl_zoom_in(self):
        zoom = self.timeline_widget.zoom()
        self.timeline_widget.set_zoom(min(40, zoom + 2))
        self._tl_update_zoom_lbl()
        self._tl_redraw()

    def _tl_zoom_out(self):
        zoom = self.timeline_widget.zoom()
        self.timeline_widget.set_zoom(max(2, zoom - 2))
        self._tl_update_zoom_lbl()
        self._tl_redraw()

    def _tl_update_zoom_lbl(self):
        z = self.timeline_widget.zoom()
        if getattr(self, '_tl_zoom_lbl', None) is not None:
            self._tl_zoom_lbl.setText(f"×{z}")
        if getattr(self, '_tl_zoom_slider', None) is not None:
            self._tl_zoom_slider.blockSignals(True)
            self._tl_zoom_slider.setValue(z)
            self._tl_zoom_slider.blockSignals(False)

    def _tl_auto_zoom(self):
        """自动缩放使动画长度适配时间轴宽度 (2~40)"""
        if self._editing_idx < 0:
            return
        dur = self._tl_calc_duration(self.entries[self._editing_idx])
        if dur <= 0:
            return
        tw = self.timeline_widget
        avail = max(tw.width() - tw._margin * 2, 200)
        z = max(2, min(40, int(avail / dur)))
        tw.set_zoom(z)
        self._tl_update_zoom_lbl()
        self._tl_redraw()

    def _tl_zoom_slider_changed(self, val):
        self.timeline_widget.set_zoom(val)
        self._tl_update_zoom_lbl()
        self._tl_redraw()

    def _tl_reset_playhead(self):
        self._preview_stop()
        self._preview_tick_idx = 0
        self._tl_tick_lbl.setText("tick: 0")
        self.timeline_widget.set_playhead(0)
        self._preview_redraw()

    # ── 编辑模式 / 图层选择 ──

    def _toggle_edit_mode(self):
        en = self._edit_mode_cb.isChecked()
        self._set_timeline_interactive(en)
        self.status_var.setText(
            "编辑模式: 开启" if en else "编辑模式: 关闭 (预览优先)")

    def _set_timeline_interactive(self, en):
        self._tl_edit_enabled = en
        if not en:
            self._tl_selected_layers.clear()
            self._tl_refresh_thumbnails()
            self.timeline_widget.update()

    def _tl_select_layer(self, layer_idx):
        self._tl_selected_layers.clear()
        self._tl_selected_layers.add(layer_idx)
        self._tl_refresh_thumbnails()
        self.timeline_widget.update()

    def _tl_snap_tick(self, raw_tick, exclude_layer, threshold):
        if self._editing_idx < 0:
            return raw_tick
        entry = self.entries[self._editing_idx]
        points = [self.timeline_widget._playhead]
        for s in range(8):
            if s == exclude_layer:
                continue
            L = entry['layers'][s]
            if L[0] == 0:
                continue
            points.append(L[22])
            first = L[17]
            last = L[18]
            interval = max(1, L[21])
            span = max(1, last - first + 1)
            points.append(L[22] + span * interval)
        best = min(points, key=lambda p: abs(p - raw_tick))
        return best if abs(best - raw_tick) <= threshold else raw_tick

    def _tl_handle_drag(self, ds, x, y, shift):
        tick = self.timeline_widget._tick_at(x)
        SNAP = 2
        if self._editing_idx < 0:
            return
        entry = self.entries[self._editing_idx]

        if ds[0] == 'sfx':
            sfx_idx = ds[1]
            tail = entry.get('tail') or []
            if sfx_idx * 2 + 1 < len(tail):
                tail[sfx_idx * 2 + 1] = max(0, tick)
                self._dirty = True
                self.timeline_widget.update()
            return

        if ds[0] == 'batch_move':
            start_tick, orig_delays = ds[1], ds[2]
            delta_tick = tick - start_tick
            min_orig = min(orig_delays.values())
            if min_orig + delta_tick < 0:
                delta_tick = -min_orig
            if shift:
                layer_idx, _, _ = self.timeline_widget._hit_test(x, y)
                if layer_idx is not None:
                    anchor_orig = orig_delays.get(layer_idx)
                    if anchor_orig is not None:
                        anchor_raw = anchor_orig + delta_tick
                        snapped = max(0, self._tl_snap_tick(anchor_raw, -1, SNAP))
                        delta_tick = snapped - anchor_orig
            for sel, orig_delay in orig_delays.items():
                L = entry['layers'][sel]
                L[22] = orig_delay + delta_tick
                sd = self._layer_vars[sel].get('start_delay')
                if isinstance(sd, QLineEdit):
                    sd.blockSignals(True)
                    sd.setText(str(L[22]))
                    sd.blockSignals(False)
            self._dirty = True
            self.timeline_widget.update()
            return

        dlayer_idx, dhit = ds
        L = entry['layers'][dlayer_idx]
        if dhit == 'right_edge':
            delay = L[22]
            interval = max(1, L[21])
            first = L[17]
            play_ticks = max(0, tick - delay)
            new_span = max(1, play_ticks // interval)
            new_end = max(first, first + new_span - 1)
            if shift:
                new_end = self._tl_snap_tick(new_end, dlayer_idx, SNAP)
                new_end = max(first, new_end)
            L[18] = new_end
        elif dhit == 'left_edge':
            t = tick
            if shift:
                t = self._tl_snap_tick(t, dlayer_idx, SNAP)
            L[22] = max(0, t)
        self._dirty = True
        vr = self._layer_vars[dlayer_idx]
        fl = vr.get('_frame_lbl')
        if fl is not None:
            fl.setText(f"[{L[17]}..{L[18]}]")
        sd = vr.get('start_delay')
        if isinstance(sd, QLineEdit):
            sd.blockSignals(True)
            sd.setText(str(L[22]))
            sd.blockSignals(False)
        self.timeline_widget.update()

    def _tl_handle_release(self, was_sfx):
        if self._editing_idx >= 0:
            entry = self.entries[self._editing_idx]
            if was_sfx:
                tail = entry.get('tail') or []
                for k in range(32):
                    if k < len(self._tail_vars):
                        self._tail_vars[k].setText(str(tail[k]))
            self._populate_edit(entry)

    def _quick_toggle_vis(self, layer_idx):
        cb = self._preview_vis.get(layer_idx + 1)
        if cb is not None:
            cb.setChecked(not cb.isChecked())
            self._preview_redraw()
            self.timeline_widget.update()

    def _quick_set_blend(self, layer_idx, mode_val):
        if self._editing_idx < 0:
            return
        L = self.entries[self._editing_idx]['layers'][layer_idx]
        L[11] = mode_val
        self._dirty = True
        self._populate_layer(layer_idx, L)
        self._preview_redraw()

    def _quick_clear_layer(self, layer_idx):
        if self._editing_idx < 0:
            return
        if QMessageBox.question(self, "确认",
                f"确定清空图层 #{layer_idx + 1} 的所有数据?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        L = self.entries[self._editing_idx]['layers'][layer_idx]
        for i in range(len(L)):
            L[i] = 0
        self._dirty = True
        self._tl_selected_layers.discard(layer_idx)
        self._tl_refresh_thumbnails()
        self._populate_layer(layer_idx, L)
        self._tl_redraw()
        self._preview_redraw()
        self.status_var.setText(f"图层 #{layer_idx + 1} 已清空")

    def _play_sound_preview(self, sid):
        if self.sws_grp is None:
            return
        p = self._resolve_sound_path(sid)
        if p:
            alias = _mci_play_async(p)
            self.status_var.setText(f"试听 sid={sid}")
        else:
            self.status_var.setText(f"未找到音效 sid={sid}")

    # ── NLE 快捷键 (J/K/L/Space/Up/Down) ──

    def _install_nle_shortcuts(self):
        for seq, cb in [
            ("J", self._nle_play_reverse),
            ("K", self._preview_stop),
            ("L", self._nle_play_forward),
            ("Space", self._nle_toggle_playback),
            ("Up", self._nle_track_up),
            ("Down", self._nle_track_down),
        ]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(cb)

    def _nle_play_reverse(self):
        self._preview_stop()
        self._tl_step_prev()

    def _nle_play_forward(self):
        if not self._is_playing:
            self._preview_play()

    def _nle_toggle_playback(self):
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QSpinBox, EditorComboBox, QTextEdit)):
            return
        if self._is_playing:
            self._preview_stop()
        else:
            self._preview_play()

    def _nle_track_up(self):
        if not self._tl_edit_enabled or self._editing_idx < 0:
            return
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QSpinBox, EditorComboBox, QTextEdit)):
            return
        entry = self.entries[self._editing_idx]
        current = (min(self._tl_selected_layers)
                   if self._tl_selected_layers else ACT_MAX_LAYER)
        for s in range(current - 1, -1, -1):
            if entry['layers'][s][0] != 0:
                self._tl_select_layer(s)
                return

    def _nle_track_down(self):
        if not self._tl_edit_enabled or self._editing_idx < 0:
            return
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QSpinBox, EditorComboBox, QTextEdit)):
            return
        entry = self.entries[self._editing_idx]
        current = (max(self._tl_selected_layers)
                   if self._tl_selected_layers else -1)
        for s in range(current + 1, ACT_MAX_LAYER):
            if entry['layers'][s][0] != 0:
                self._tl_select_layer(s)
                return

    # ── 帮助 ──

    # 逆向参考: sub_4434BC (动画运行时核心函数)
    def _show_field_ref(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("字段参考")
        dlg.resize(760, 640)

        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))

        lines = [
            "TKAct.dat 字段说明",
            "",
            f"【文件结构】原版 {ACT_ENTRY_COUNT} 条 × {ACT_ENTRY_SIZE} 字节 = "
            f"{ACT_DECOMPRESSED} 字节；编辑器支持读取/保存 650 条以上的扩展文件",
            "  每条 = 方向表[32B] + 条目级参数[48B] + 8图层×80B + 尾部[64B]",
            "",
            "【方向表 (bytes 0-31)】",
            "  4 方向 × 8 字节, 每字节 = 1-based 图层号 (0=空)",
            "",
            "【条目级参数 (bytes 32-79, int16[16..39])】",
            "  [18] 动画总时长; [19] 当前播放时间（自动）; [20..27] 第1~8次飘字",
            "  已填写的飘字触发时间数量决定伤害或恢复数值的分段数；最多8次",
            "  飘字触发时间应按先后顺序递增且小于[18]；[19]由原版运行时自动维护",
            "",
            "【图层 × 8 (各 80 字节, 40 int16)】",
        ]
        for grp_name, fields in FIELD_GROUPS:
            lines.append(f"  — {grp_name} —")
            for (fn, idx, label, _, comment) in fields:
                lines.append(f"    [{idx:2d}] {fn:<18s} {label}")
                for cl in comment.split('\n'):
                    lines.append(f"         {cl}")
            lines.append("")
        lines.append("【尾部 (bytes 720-783)】")
        lines.append("  16 对 (sound_id, trigger_tick) = 音效触发表")

        text.setPlainText('\n'.join(lines))
        layout.addWidget(text)

        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("✕ 关闭", clicked=dlg.close))
        layout.addLayout(bl)
        dlg.exec()

    # 逆向参考: sub_4434BC, sub_42FEE0, sub_451780, sub_458D08

    # ── 窗口关闭 ──

    def closeEvent(self, event):
        self._preview_stop()
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            _cleanup_sws_tempfiles()
            event.accept()


# ============================================================
# 入口
# ============================================================

def main():
    run_editor(ActEditorV2, "TKAct Editor")


if __name__ == '__main__':
    main()
