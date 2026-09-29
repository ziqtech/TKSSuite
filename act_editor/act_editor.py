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
  [32-79]   条目级参数区 (24 int16): [2] 动画总帧数,
             [4..11] word_9D03A2[8] 飘字/命中触发帧, 其余为预留/未知
  [80-719]  图层 × 8 (各 80 字节 = 40 int16)
  [720-783] 尾部 = 音效触发表 16 对 × (sound_id, trigger_tick) × int16

用法:
  python act_editor.py
"""

import collections
import os
import random
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
    QMenu, QAbstractSpinBox, QSizePolicy,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen,
    QPixmap, QAction, QShortcut, QKeySequence,
)
from PySide6.QtCore import (
    Qt, QTimer, QTranslator, Signal,
)

# ── editor_utils 公共模块 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import business_colors

from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.version import format_title
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput
from editor_utils.task_runner import run_background, is_running
from editor_utils.kon_name_resolver import KonNameResolver
from editor_utils.lzss import lzss_decompress_dat
from editor_utils.dock_components import DockHeader
from editor_utils.ui_helpers import (
    themed_question,
    make_fake_input, update_path_labels, EditorComboBox, set_themed_icon,
    backup_existing_file,
    show_field_ref,
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
    from PIL import Image
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


from sws_audio import _SWSGrp, _cleanup_sws_tempfiles, _mci_close, _mci_play_async
from act_codec import (
    BLOCK_SHADOW_BG, BLOCK_SHADOW_BORDER, GUIDE_BLUE, PEN_TRAJECTORY_GREEN,
    PEN_TRAJECTORY_RED, PREVIEW_CANVAS_BG, SELECT_RED, SLOT_COLORS,
    STMT_HAS_DATA_COLOR, STMT_INCOMPLETE_COLOR, STMT_NO_DATA_COLOR,
    STMT_UNKNOWN_COLOR,
    ACT_DECOMPRESSED, ACT_ENTRY_COUNT, ACT_ENTRY_SIZE, ACT_LAYER_SIZE,
    ACT_MAX_LAYER, ACT_PARAM_OFFSET, ACT_TAIL_OFFSET, ALL_FIELDS,
    BLEND_MODE_LABELS, DIRECTION_MODE_LABELS, DIRECTION_SHORT,
    FIELD_GROUPS, LAYER_TYPE_LABELS, LOOP_BEHAVIOR_LABELS, MOVE_MODE_LABELS,
    PARAM_FIELD_INFO, PREVIEW_ENEMY_X, READONLY_KEYS,
    entry_active_layers, entry_is_empty, entry_referenced_layers, entry_summary,
    infer_jvg_layout, load_act, save_act,
)
from act_composite import (
    _apply_blend, _composite_additive, _composite_luma_alpha, _composite_subtract,
    _compute_layer_frame, pil_to_qpixmap,
)
from act_font import FONT_COLORS, ActFont9696
from act_widgets import PreviewCanvas, ThumbnailStrip, TimelineWidget


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


class _NoWheelSpinBox(QSpinBox):
    """滚动面板时不改值的数字输入框。"""

    def wheelEvent(self, event):
        event.ignore()


_jvg_loader = None


# byte_4EB730[1..18]：伤害浮动 Y 曲线（逆向实证值）。
FLOAT_Y_CURVE = (
    0, -10, -30, -55, -35, -20, 0,
    -13, -22, -30, -25, -15, 0,
    -8, 0, -4, 0, -2, 0,
)

# 飘字效果类型（颜色索引与文案均来自原版逆向实证）。
# kind=number：按 TKAct 触发帧分摊 total，颜色按 colors 循环；
# kind=text：每个触发帧显示固定文案，使用 color_idx。
FLOAT_TYPES = (
    {
        'id': 'hp_damage',
        'label': '伤害飘字',
        'kind': 'number',
        'colors': (18, 23),
        'total': 999,
        'tooltip': (
            'HP伤害数字（默认）\n'
            '偶数段调色板18(红)、奇数段23(品红)\n'
            '依据 sub_4400DC / sub_433F04'),
    },
    {
        'id': 'mp_damage',
        'label': '内力伤害',
        'kind': 'number',
        'colors': (28,),
        'total': 999,
        'tooltip': (
            'MP/内力伤害数字\n'
            '调色板28(紫蓝)\n'
            '依据 sub_4400DC 4421A5'),
    },
    {
        'id': 'hp_heal',
        'label': '生命恢复',
        'kind': 'number',
        'colors': (20,),
        'total': 999,
        'tooltip': (
            'HP恢复数字（道具/治疗）\n'
            '调色板20(绿)\n'
            '依据 sub_4400DC 44046B'),
    },
    {
        'id': 'mp_heal',
        'label': '内力恢复',
        'kind': 'number',
        'colors': (21,),
        'total': 999,
        'tooltip': (
            'MP恢复数字（道具/治疗）\n'
            '调色板21(青)\n'
            '依据 sub_4400DC 4406EC'),
    },
    {
        'id': 'miss',
        'label': '未命中 Miss',
        'kind': 'text',
        'text': 'Miss',
        'color_idx': 31,
        'tooltip': (
            '未命中/无效\n'
            '白色调色板31，显示 Miss\n'
            '依据 sub_433D44：value<0 时走该分支'),
    },
    {
        'id': 'spell_reflect',
        'label': '法术反弹',
        'kind': 'text',
        'text': '法術反彈',
        'color_idx': 29,
        'tooltip': (
            '法术反弹提示\n'
            '调色板29(天蓝)\n'
            '依据 sub_4458B0 → sub_433A38(unk_4EBC2A, 29)'),
    },
    {
        'id': 'status',
        'label': '状态异常',
        'kind': 'text',
        'text': '定身',
        'color_idx': 26,
        'tooltip': (
            '状态异常提示（定身/沈睡等）\n'
            '调色板26(黄绿)\n'
            '依据 sub_43292C → sub_433A38(color 26)'),
    },
    {
        'id': 'action_fail',
        'label': '行动失败',
        'kind': 'text',
        'text': '行動失敗',
        'color_idx': 18,
        'tooltip': (
            '行动/指令失败提示\n'
            '调色板18(红)\n'
            '依据 sub_4458B0 → sub_433A38(unk_4EBBE5, 18)'),
    },
)

FLOAT_TYPE_MAP = {ft['id']: ft for ft in FLOAT_TYPES}
DEFAULT_FLOAT_TYPE = 'hp_damage'
DEFAULT_FLOAT_TOTAL = 999


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
        "  · 预览标注: 可隐藏攻击方/受击方标记, 受击方距离可调\n"
        "  · 预览敌方受击飘字（按数值出现时间分段，测试总值 999）\n"
        "  · 飘字效果可选：伤害/内力/恢复/Miss/法术反弹/状态等，颜色对齐原版\n"
        "  · 音效触发表编辑\n"
        "  · 每行右键: 复制 / 粘贴 / 清除；扩展条目另有删除\n"
        "  · 原版条目只能清除；扩展条目可清除或删除\n"
        "  · 深色/浅色主题切换")

    _LAYER_FIELD_TITLES = {
        'jvg_block_index': '素材编号',
        'first_frame': '开始帧',
        'last_frame': '结束帧',
        'tick_interval': '播放速度',
        'start_delay': '出场等待',
        'blend_param': '效果强度',
        'blend_param_step': '强度每帧变化',
        'dir_frame_offset': '朝向错开帧数',
        'step_value': '每次移动距离',
        'step_delta': '移动距离变化',
        'x_off_d0': '右上 左右位置',
        'x_off_d1': '右下 左右位置',
        'x_off_d2': '左下 左右位置',
        'x_off_d3': '左上 左右位置',
        'y_off_d0': '右上 上下位置',
        'y_off_d1': '右下 上下位置',
        'y_off_d2': '左下 上下位置',
        'y_off_d3': '左上 上下位置',
        '_rt_frame_base': '内部帧起点',
        '_rt_cur_frame': '内部当前帧',
        '_rt_20': '内部字段 20',
        '_rt_counter': '内部计数器',
        '_rt_dir_sign': '内部播放方向',
    }
    _LAYER_FIELD_TOOLTIPS = {
        'jvg_block_index': '从人物动作库或特效库里选择哪一组图片。',
        'first_frame': '从素材的第几帧开始播放。',
        'last_frame': '播放到素材的第几帧结束。',
        'tick_interval': '数值越大，每一帧停留越久，动画越慢。',
        'start_delay': '动画开始前先等待的时间，0 表示立即出场。',
        'blend_param': '控制闪烁、发光或压暗的强弱。',
        'blend_param_step': '每换一帧，效果强度增加或减少多少。',
        'dir_frame_offset': '人物朝向改变时，素材帧号按多少帧错开。',
        'move_mode': '让特效跟着角色走，或自动来回飘动。',
        'step_value': '自动移动时每次移动多少像素。',
        'step_delta': '自动移动时每次移动量怎样变化。',
    }
    _PARAM_FIELD_TITLES = {
        2: '动画总时长',
        4: '第 1 次数字出现',
        5: '第 2 次数字出现',
        6: '第 3 次数字出现',
        7: '第 4 次数字出现',
        8: '第 5 次数字出现',
        9: '第 6 次数字出现',
        10: '第 7 次数字出现',
        11: '第 8 次数字出现',
    }

    def _init_data(self):
        # 数据状态
        self.act_path = None
        self.aa_path = None
        self.af_path = None
        self.sws_grp = None
        self.font_path = None
        self._font = None
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
        # 受击方(假想敌)与攻击方原点的预览距离, 仅影响预览不写入数据
        self._preview_enemy_x = PREVIEW_ENEMY_X

        # 时间轴编辑状态
        self._tl_selected_layers = set()
        self._tl_edit_enabled = False
        self._marquee_start = None

        # 图层编辑变量
        self._layer_vars = [{} for _ in range(ACT_MAX_LAYER)]
        self._active_layer_idx = 0
        self._layer_slot_buttons = []
        self._layer_cards = []
        self._dir_vars = [[None]*8 for _ in range(4)]
        self._param_vars = []
        self._param_indices = []
        self._tail_vars = []
        self._tail_file_lbls = []
        self._float_specs = []
        self._float_effect_on = True  # 预览飘字效果开关 (工具栏 checkbox)
        self._float_type = DEFAULT_FLOAT_TYPE
        self._float_type_cb = None
        self._float_total = DEFAULT_FLOAT_TOTAL
        self._float_total_spin = None

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
        fm.addAction("加载 TKS 目录\tCtrl+O", self._load_tks_dir)
        self.attach_recent_dirs_menu(fm)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出为 MOD (.tksmod)", self._export_tksmod)
        fm.addAction("导入 MOD (.tksmod)", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新建条目", QKeySequence("Ctrl+N"), self._new_entry)
        em.addAction("复制当前条目", self._copy_current)
        em.addAction("粘贴到当前条目", self._paste_current)
        em.addAction("清除当前条目", self._clear_entry)
        em.addAction("删除当前条目", self._delete_entry)

        self.add_theme_submenu(mb)

        self.add_help_menu(mb)

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
        self.search_entry = SearchInput("搜索名称或编号")
        self.search_entry.setMinimumWidth(160)
        self.search_entry.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("清除", clicked=self._clear_filter))
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
        toolbar.addWidget(QPushButton("重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("切换主题", clicked=self._toggle_theme))
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
            0, 3,
            stretch_columns={1, 2},
            minimum_widths=[50, 90, 90],
            row_height=44,
        )
        self.table.setHorizontalHeaderLabels(["序号", "名称", "图层数"])
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

        # 右栏: 玩家视角分区 (画面 / 遮挡 / 数值 / 音效)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.setSpacing(4)
        right.setMinimumWidth(620)

        # 与 WarPC 主编辑区一致：标签栏和内容区共享连续的 flat Pane 边界。
        self.tabs = EditorTabWidget(
            flat=True,
            object_name="ActEditorTabs",
        )
        self._build_layer_cards_tab()
        self._build_direction_tab()
        self._build_param_tab()
        self._build_tail_tab()
        self.tabs.setCurrentIndex(0)  # 默认直接进入画面图层编辑

        # 右侧面板自带“应用/重置”，避免玩家改完参数后还要去中间栏找按钮。
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(4, 2, 4, 2)
        corner_layout.setSpacing(4)
        corner_layout.addWidget(QPushButton("应用修改", clicked=self._apply_edit))
        corner_layout.addWidget(QPushButton("重置", clicked=self._reset_edit))
        self.tabs.setCornerWidget(corner)

        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)

        # 左侧列表随窗口一起响应式拉伸（让出一部分增量），中央栏仍是主扩容区，
        # 右侧参数面板保持可读宽度。拉伸权重决定最大化时各栏分到的剩余空间比例。
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 720, 620])

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

        # 定宽: 飘字下拉框恰好显示 4 个中文字符 / 数值框恰好显示 4 位数字。
        # 必须在控件全部挂入窗口后计算 — ensurePolished 后字体才反映主题
        # QSS 的全局 font-size(13px), 构建中途测量会偏小导致截字。
        # 铬宽实测各主题一致: combo=46 (边框2+内边距16+箭头28) / spin=56
        # (边框+内边距+右侧箭头区, 含内嵌行编辑器自身边距)。主题 QSS 的
        # 输入类 padding 槽位若调整, 需同步这两个常量。
        # combo 最长的 "未命中 Miss" 一项超出 4 字宽会被裁切, 属预期取舍
        # (完整文案见各条目 tooltip)。
        self._float_type_cb.ensurePolished()
        self._float_type_cb.setFixedWidth(
            46 + self._float_type_cb.fontMetrics().horizontalAdvance("伤害飘字") + 2)
        self._float_total_spin.ensurePolished()
        self._float_total_spin.setFixedWidth(
            56 + self._float_total_spin.fontMetrics().horizontalAdvance("9999") + 2)

    def _build_scroll_tab(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(4, 4, 12, 4)
        inner.layout().setSpacing(4)
        inner.layout().setAlignment(Qt.AlignTop)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, name)
        return inner

    # ── Tab 1: 方向与绘制顺序 ──

    def _build_direction_tab(self):
        inner = self._build_scroll_tab("遮挡顺序")

        lbl = QLabel(
            "这里决定人物朝不同方向时，哪一层画面画在前面、哪一层画在后面。\n"
            "数字 1 到 8 对应“画面图层”页的图层槽位；0 表示这一格不用。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(4)

        # 表头
        head = QLabel("朝向")
        head.setProperty("class", "PropLabel")
        grid.addWidget(head, 0, 0)
        for s in range(8):
            lbl_z = QLabel(f"{s + 1}")
            lbl_z.setProperty("class", "PropLabel")
            lbl_z.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl_z, 0, s + 1)

        for d in range(4):
            lbl_dir = QLabel(DIRECTION_SHORT[d])
            lbl_dir.setProperty("class", "PropLabel")
            lbl_dir.setMinimumWidth(80)
            lbl_dir.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(lbl_dir, d + 1, 0)
            for i in range(8):
                spin = _NoWheelSpinBox()
                spin.setRange(0, ACT_MAX_LAYER)
                spin.setValue(0)
                spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
                spin.setFixedWidth(56)
                spin.setAlignment(Qt.AlignCenter)
                spin.setToolTip(
                    "0 表示不用；1~8 表示图层槽位。\n"
                    "可直接输入数字，也可用上下方向键调整。")
                self._dir_vars[d][i] = spin
                grid.addWidget(spin, d + 1, i + 1)

        for c in range(9):
            grid.setColumnStretch(c, 1 if c else 0)

        grid.setContentsMargins(0, 2, 0, 0)
        grid_container = QWidget()
        grid_container.setLayout(grid)
        inner.layout().addWidget(grid_container)

        actions = QHBoxLayout()
        btn_fill = QPushButton("按 1→8 排列", clicked=self._fill_direction_order)
        btn_reverse = QPushButton("反转各行", clicked=self._reverse_direction_order)
        actions.addWidget(btn_fill)
        actions.addWidget(btn_reverse)
        actions.addStretch()
        inner.layout().addLayout(actions)
        inner.layout().addStretch()

    def _fill_direction_order(self):
        for d in range(4):
            for i in range(8):
                self._set_editor_text(self._dir_vars[d][i], str(i + 1))

    def _reverse_direction_order(self):
        for d in range(4):
            for i in range(8):
                src = self._dir_vars[d][7 - i]
                self._set_editor_text(self._dir_vars[d][i], self._editor_text(src))

    # ── 中栏: 时间轴与预览 (统一视图) ──

    def _build_timeline_into(self, parent_layout):
        inner = QWidget()
        inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(0, 0, 0, 0)
        inner.layout().setSpacing(4)
        parent_layout.addWidget(inner, 1)

        # 控制栏分三行：单行会把中央栏的最小宽度推到 1000px 以上，
        # 进而在默认窗口下挤压左侧列表。第一行放播放/方向/周期，
        # 第二行放播放头和编辑操作，第三行放预览标注与受击方距离。
        ctrl = QVBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(2)

        playback_ctrl = QHBoxLayout()
        playback_ctrl.setSpacing(4)

        btn_first = QPushButton("", clicked=self._tl_goto_first)
        set_themed_icon(btn_first, "first")
        btn_first.setToolTip("跳至首帧 (Ctrl+◀◀)")
        playback_ctrl.addWidget(btn_first)

        btn_prev = QPushButton("", clicked=self._tl_step_prev)
        set_themed_icon(btn_prev, "prev")
        btn_prev.setToolTip("后退一帧 (J / ←)")
        playback_ctrl.addWidget(btn_prev)

        btn_play = QPushButton("", clicked=self._preview_play)
        set_themed_icon(btn_play, "play")
        btn_play.setToolTip("播放动画 (L)")
        playback_ctrl.addWidget(btn_play)

        btn_stop = QPushButton("", clicked=self._preview_stop)
        set_themed_icon(btn_stop, "stop")
        btn_stop.setToolTip("停止播放 (K)")
        playback_ctrl.addWidget(btn_stop)

        btn_last = QPushButton("", clicked=self._tl_goto_last)
        set_themed_icon(btn_last, "last")
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
        btn_zero = QPushButton("归零", clicked=self._tl_reset_playhead)
        btn_zero.setToolTip("播放头归零")
        edit_ctrl.addWidget(btn_zero)
        self._tl_tick_lbl = QLabel("tick: 0")
        edit_ctrl.addWidget(self._tl_tick_lbl)

        self._edit_mode_cb = QCheckBox("编辑模式")
        self._edit_mode_cb.setChecked(False)
        self._edit_mode_cb.stateChanged.connect(self._toggle_edit_mode)
        edit_ctrl.addWidget(self._edit_mode_cb)

        edit_ctrl.addSpacing(8)
        edit_ctrl.addWidget(QLabel("飘字效果预览:"))
        self._float_type_cb = QComboBox()
        for ft in FLOAT_TYPES:
            self._float_type_cb.addItem(ft['label'], ft['id'])
            tip = ft.get('tooltip', '')
            if tip:
                self._float_type_cb.setItemData(
                    self._float_type_cb.count() - 1, tip, Qt.ToolTipRole)
        default_idx = self._float_type_cb.findData(DEFAULT_FLOAT_TYPE)
        self._float_type_cb.setCurrentIndex(default_idx if default_idx >= 0 else 0)
        self._float_type = (
            self._float_type_cb.currentData() or DEFAULT_FLOAT_TYPE)
        self._float_type_cb.setToolTip(
            "选择预览时使用的飘字类型；颜色与文案对应原版战斗实际效果")
        self._float_type_cb.currentIndexChanged.connect(
            self._on_float_type_changed)
        edit_ctrl.addWidget(self._float_type_cb)

        edit_ctrl.addSpacing(4)
        edit_ctrl.addWidget(QLabel("数值:"))
        self._float_total_spin = QSpinBox()
        self._float_total_spin.setRange(1, 999999)
        self._float_total_spin.setValue(DEFAULT_FLOAT_TOTAL)
        self._float_total_spin.setSingleStep(1)
        self._float_total = DEFAULT_FLOAT_TOTAL
        self._float_total_spin.setToolTip(
            "数字类飘字的预览总值，按触发帧分摊后显示；"
            "默认 999，对应原版编辑器测试值")
        self._float_total_spin.valueChanged.connect(
            self._on_float_total_changed)
        edit_ctrl.addWidget(self._float_total_spin)
        self._float_effect_cb = QCheckBox("伤害飘字")
        self._float_effect_cb.setChecked(True)
        self._float_effect_cb.setToolTip(
            "开启或关闭预览中的飘字效果（伤害/恢复/Miss 等全部类型）；\n"
            "关闭时飘字类型下拉框与数值框一并不生效")
        self._float_effect_cb.stateChanged.connect(
            self._on_float_effect_toggled)
        edit_ctrl.addWidget(self._float_effect_cb)
        self._sync_float_total_enabled()

        edit_ctrl.addStretch()
        edit_ctrl.addWidget(QPushButton("应用修改", clicked=self._apply_edit))
        edit_ctrl.addWidget(QPushButton("重置", clicked=self._reset_edit))
        ctrl.addLayout(edit_ctrl)

        # 第三行: 预览标注 (攻击方/受击方) 显示隐藏 + 受击方距离。
        # 距离只影响预览定位 (图层类型 3/4 与飘字锚定受击方), 不写入文件。
        marker_ctrl = QHBoxLayout()
        marker_ctrl.setSpacing(4)
        marker_ctrl.addWidget(QLabel("标注:"))
        self._show_attacker_cb = QCheckBox("攻击方")
        self._show_attacker_cb.setChecked(True)
        self._show_attacker_cb.setToolTip("显示或隐藏预览区的攻击方原点十字标记")
        self._show_attacker_cb.stateChanged.connect(
            self._on_marker_vis_changed)
        marker_ctrl.addWidget(self._show_attacker_cb)
        self._show_defender_cb = QCheckBox("受击方")
        self._show_defender_cb.setChecked(True)
        self._show_defender_cb.setToolTip(
            "显示或隐藏预览区的受击方(假想敌)十字与人形标记")
        self._show_defender_cb.stateChanged.connect(
            self._on_marker_vis_changed)
        marker_ctrl.addWidget(self._show_defender_cb)

        marker_ctrl.addSpacing(8)
        marker_ctrl.addWidget(QLabel("受击方距离:"))
        self._enemy_dist_spin = _NoWheelSpinBox()
        self._enemy_dist_spin.setRange(0, 640)
        self._enemy_dist_spin.setValue(PREVIEW_ENEMY_X)
        # 与"周期"框同理: 主题 QSS 需要预留边框/内边距/箭头宽度,
        # 80px 保证三位数字可编辑。
        self._enemy_dist_spin.setFixedWidth(80)
        self._enemy_dist_spin.setToolTip(
            "受击方(假想敌)与攻击方原点的水平距离, 仅影响预览, 不写入文件。\n"
            "图层类型 3/4 的特效以受击方为基准定位, "
            "可调整此距离模拟实战站位 (默认 160 对应原版预览值)。")
        self._enemy_dist_spin.valueChanged.connect(
            self._on_enemy_dist_changed)
        marker_ctrl.addWidget(self._enemy_dist_spin)
        dist_slider = QSlider(Qt.Horizontal)
        dist_slider.setRange(0, 640)
        dist_slider.setValue(PREVIEW_ENEMY_X)
        dist_slider.setPageStep(16)
        dist_slider.setMaximumWidth(160)
        dist_slider.setToolTip(self._enemy_dist_spin.toolTip())
        dist_slider.valueChanged.connect(self._on_enemy_dist_changed)
        self._enemy_dist_slider = dist_slider
        marker_ctrl.addWidget(dist_slider)
        marker_ctrl.addStretch()
        ctrl.addLayout(marker_ctrl)
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
        """画面图层 Tab: 8 个槽位按钮 + 当前槽位的单卡片编辑。"""
        inner = self._build_scroll_tab("画面图层")
        self._card_inner = inner

        top = QHBoxLayout()
        top.setSpacing(6)
        hint = QLabel("选择图层：")
        hint.setProperty("class", "PropLabel")
        top.addWidget(hint)
        self._layer_slot_buttons = []
        for layer_idx in range(ACT_MAX_LAYER):
            btn = QPushButton(str(layer_idx + 1))
            btn.setCheckable(True)
            btn.setFixedWidth(38)
            btn.setToolTip(f"编辑图层 {layer_idx + 1}")
            btn.clicked.connect(
                lambda checked, li=layer_idx: self._select_layer_card(li))
            self._layer_slot_buttons.append(btn)
            top.addWidget(btn)
        top.addStretch()
        inner.layout().addLayout(top)

        self._build_layer_cards()
        self._select_layer_card(0)
        inner.layout().addStretch(1)

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

    @staticmethod
    def _editor_text(widget):
        """统一读取 QLineEdit / QSpinBox / EditorComboBox 的显示值。"""
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QSpinBox):
            return str(widget.value())
        if isinstance(widget, EditorComboBox):
            return widget.currentText()
        return ""

    @classmethod
    def _set_editor_text(cls, widget, text):
        """统一填充 QLineEdit / QSpinBox / EditorComboBox。"""
        if isinstance(widget, QLineEdit):
            widget.setText(text)
        elif isinstance(widget, QSpinBox):
            try:
                widget.setValue(int(text))
            except (TypeError, ValueError):
                widget.setValue(0)
        elif isinstance(widget, EditorComboBox):
            widget.setCurrentText(text)

    def _select_layer_card(self, layer_idx):
        """只显示当前图层卡片，避免 8 张长卡片造成的长距离滚动。"""
        if not 0 <= layer_idx < ACT_MAX_LAYER:
            return
        self._active_layer_idx = layer_idx
        for idx, card in enumerate(self._layer_cards):
            card.setVisible(idx == layer_idx)
        for idx, btn in enumerate(self._layer_slot_buttons):
            btn.setChecked(idx == layer_idx)

    def _build_layer_cards(self):
        """构建 8 个图层卡片，由槽位按钮控制可见性。"""
        self._layer_cards = []
        for s in range(ACT_MAX_LAYER):
            card = self._build_single_card(s)
            self._card_inner.layout().addWidget(card)
            self._layer_cards.append(card)
            card.setVisible(False)

    def _build_single_card(self, layer_idx):
        vars_row = self._layer_vars[layer_idx]
        COL = 3

        card = QFrame()
        card.setFrameShape(QFrame.NoFrame)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 8, 10, 10)
        cl.setSpacing(8)

        # ── 头部: 图层号 + 用途 + 素材检查 ──
        head = QHBoxLayout()
        head.setSpacing(6)
        lbl = QLabel(f"图层 {layer_idx + 1}")
        lbl.setObjectName("DockTitle")
        head.addWidget(lbl)
        vars_row['_card_label'] = lbl

        type_combo = self._no_wheel_combo(list(LAYER_TYPE_LABELS.values()))
        type_combo.setCurrentIndex(0)
        type_combo.setToolTip(
            "人物动作来自 Aa.jvg；特效和物件来自 Af.jvg。\n"
            "位置标记不会显示画面，只用于计算位置。")
        type_combo.currentIndexChanged.connect(
            lambda idx, li=layer_idx: self._on_layer_type_changed(li))
        head.addWidget(type_combo, 1)
        vars_row['_type_combo'] = type_combo

        frame_lbl = QLabel("可用帧 0..0")
        frame_lbl.setProperty("class", "ExtraPreviewText")
        frame_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(frame_lbl, 1)
        vars_row['_frame_lbl'] = frame_lbl
        cl.addLayout(head)

        # ── 常用设置: 标签在上，控件在下 ──
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)

        def _cell(label, widget, tooltip=""):
            c = QVBoxLayout()
            c.setSpacing(2)
            lb = QLabel(label)
            lb.setProperty("class", "PropLabel")
            if tooltip:
                lb.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            c.addWidget(lb)
            c.addWidget(widget)
            return c

        def _spin(key):
            spin = _NoWheelSpinBox()
            spin.setRange(-32768, 32767)
            spin.setValue(0)
            spin.setMinimumWidth(118)
            spin.setMaximumWidth(220)
            spin.valueChanged.connect(
                lambda value, li=layer_idx, f=key:
                self._on_layer_field_change(li, f))
            vars_row[key] = spin
            return spin

        def _cb(key, labels_dict, editable=False):
            cb = self._no_wheel_combo()
            for value, label in labels_dict.items():
                cb.addItem(label, value)
            cb.setMinimumWidth(118)
            cb.setMaximumWidth(220)
            if editable:
                cb.setEditable(True)
                cb.setInsertPolicy(QComboBox.NoInsert)
                cb.currentIndexChanged.connect(
                    lambda idx, combo=cb:
                    self._sync_editable_combo_value(combo, idx))
                self._sync_editable_combo_value(cb)
            vars_row[key] = cb
            return cb

        # 第一屏只保留玩家最容易理解、最常修改的字段。
        grid.addLayout(_cell(
            "素材编号", _spin("jvg_block_index"),
            self._LAYER_FIELD_TOOLTIPS['jvg_block_index']), 0, 0)
        bc = _cb("blend_mode", BLEND_MODE_LABELS)
        vars_row['_blend_combo'] = bc
        grid.addLayout(_cell(
            "画面效果", bc,
            "选择正常显示、发光、压暗、闪烁或镜像。"), 0, 1)
        lc = _cb("loop_behavior", LOOP_BEHAVIOR_LABELS, editable=True)
        vars_row['_loop_combo'] = lc
        grid.addLayout(_cell(
            "结束方式", lc,
            "-1 循环播放；-2 播完隐藏；数字表示播完跳回第几帧。"), 0, 2)

        grid.addLayout(_cell(
            "开始帧", _spin("first_frame"),
            self._LAYER_FIELD_TOOLTIPS['first_frame']), 1, 0)
        grid.addLayout(_cell(
            "结束帧", _spin("last_frame"),
            self._LAYER_FIELD_TOOLTIPS['last_frame']), 1, 1)
        grid.addLayout(_cell(
            "播放速度", _spin("tick_interval"),
            self._LAYER_FIELD_TOOLTIPS['tick_interval']), 1, 2)
        grid.addLayout(_cell(
            "出场等待", _spin("start_delay"),
            self._LAYER_FIELD_TOOLTIPS['start_delay']), 2, 0)
        grid.addLayout(_cell(
            "效果强度", _spin("blend_param"),
            self._LAYER_FIELD_TOOLTIPS['blend_param']), 2, 1)
        grid.addLayout(_cell(
            "强度每帧变化", _spin("blend_param_step"),
            self._LAYER_FIELD_TOOLTIPS['blend_param_step']), 2, 2)
        dm = _cb("direction_mode", DIRECTION_MODE_LABELS)
        grid.addLayout(_cell(
            "朝向处理", dm,
            "固定画面方向适合特效；跟随人物朝向适合人物动作。"), 3, 0)

        for c in range(COL):
            grid.setColumnStretch(c, 1)

        cl.addLayout(grid)

        # ── 素材检查结果 ──
        probe_lbl = QLabel("")
        probe_lbl.setProperty("class", "ExtraPreviewText")
        probe_lbl.setWordWrap(True)
        cl.addWidget(probe_lbl)
        vars_row['_probe_lbl'] = probe_lbl

        # ── 高级区域 (默认隐藏: 位置、自动运动、内部/保留字段) ──
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)

        SIMPLE_KEYS = {
            'layer_type', 'jvg_block_index', 'blend_mode', 'loop_behavior',
            'direction_mode', 'first_frame', 'last_frame', 'tick_interval',
            'start_delay', 'blend_param', 'blend_param_step',
        }
        MOTION_KEYS = {
            'dir_frame_offset', 'move_mode', 'step_value', 'step_delta',
            'x_off_d0', 'x_off_d1', 'x_off_d2', 'x_off_d3',
            'y_off_d0', 'y_off_d1', 'y_off_d2', 'y_off_d3',
        }

        def _detail_group(title, keys, col_count=3):
            group = QGroupBox(title)
            group_layout = QGridLayout(group)
            group_layout.setVerticalSpacing(6)
            group_layout.setHorizontalSpacing(10)
            widgets = []
            for fn, idx, label, width, comment in ALL_FIELDS:
                if fn not in keys:
                    continue
                tooltip = self._LAYER_FIELD_TOOLTIPS.get(fn, comment)
                title_text = self._LAYER_FIELD_TITLES.get(fn, label)
                if fn.startswith('_res_'):
                    title_text = "保留字段（原版未使用）"
                if fn == 'move_mode':
                    widget = _cb("move_mode", MOVE_MODE_LABELS)
                else:
                    widget = _spin(fn)
                    if fn in READONLY_KEYS:
                        widget.setEnabled(False)
                        tooltip = "原版运行时使用，文件里通常保持 0。"
                widgets.append((title_text, widget, tooltip))
            for pos, (title_text, widget, tooltip) in enumerate(widgets):
                r, c = divmod(pos, col_count)
                group_layout.addLayout(
                    _cell(title_text, widget, tooltip), r, c)
            if widgets:
                last_row = (len(widgets) - 1) // col_count
                for c in range(col_count):
                    group_layout.setColumnStretch(c, 1)
                if len(widgets) % col_count:
                    for c in range(len(widgets) % col_count, col_count):
                        group_layout.addWidget(QWidget(), last_row, c)
            return group

        dl.addWidget(_detail_group("位置与自动运动", MOTION_KEYS))
        remaining = {
            f[0] for f in ALL_FIELDS
            if f[0] not in SIMPLE_KEYS and f[0] not in MOTION_KEYS
        }
        dl.addWidget(_detail_group("底层字段（一般不用改）", remaining))

        detail.setVisible(False)
        cl.addWidget(detail)
        vars_row['_detail'] = detail

        # ── 展开/折叠 ──
        toggle_btn = QPushButton("高级参数")
        toggle_btn.setCheckable(True)
        toggle_btn.setFixedWidth(100)
        toggle_btn.toggled.connect(detail.setVisible)
        toggle_btn.toggled.connect(
            lambda checked: toggle_btn.setText(
                "收起高级" if checked else "高级参数"))
        cl.addWidget(toggle_btn)
        vars_row['_toggle_btn'] = toggle_btn
        cl.addStretch(1)

        return card

    def _toggle_card_detail(self, layer_idx):
        """兼容旧调用：切换当前卡片的高级区域。"""
        btn = self._layer_vars[layer_idx].get('_toggle_btn')
        if btn is not None:
            btn.setChecked(not btn.isChecked())

    # ── Tab 3: 数值出现时间 ──

    def _build_param_tab(self):
        inner = self._build_scroll_tab("数值出现时间")

        lbl = QLabel(
            "这里设置伤害或恢复数字什么时候冒出来。\n"
            "动画总时长是整个动画的播放时间；下面 8 个时间从早到晚填写，"
            "填几个就分几段显示。不用的时间保持 0。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(10)
        self._param_vars = []
        self._param_indices = []

        important_indices = [2, 4, 5, 6, 7, 8, 9, 10, 11]
        self._param_indices.extend(important_indices)
        for pos, idx in enumerate(important_indices):
            r, c = divmod(pos, 3)
            cell = QVBoxLayout()
            cell.setSpacing(2)

            label = self._PARAM_FIELD_TITLES.get(idx, PARAM_FIELD_INFO[idx][0])
            comment = PARAM_FIELD_INFO[idx][1]
            lbl_f = QLabel(label)
            lbl_f.setProperty("class", "PropLabel")
            lbl_f.setToolTip(comment)
            cell.addWidget(lbl_f)

            spin = _NoWheelSpinBox()
            spin.setRange(-32768, 32767)
            spin.setValue(0)
            spin.setMinimumWidth(100)
            spin.setToolTip(comment)
            self._param_vars.append(spin)
            cell.addWidget(spin)
            grid.addLayout(cell, r, c)

        for c in range(3):
            grid.setColumnStretch(c, 1)

        inner.layout().addLayout(grid)

        advanced = QGroupBox("高级与保留字段")
        advanced_layout = QGridLayout(advanced)
        advanced_layout.setVerticalSpacing(6)
        advanced_layout.setHorizontalSpacing(10)
        advanced_indices = [
            idx for idx in range(24) if idx not in important_indices
        ]
        self._param_indices.extend(advanced_indices)
        for pos, idx in enumerate(advanced_indices):
            r, c = divmod(pos, 4)
            label, comment = PARAM_FIELD_INFO[idx]
            if idx in self._PARAM_FIELD_TITLES:
                label = self._PARAM_FIELD_TITLES[idx]
            elif idx not in important_indices:
                label = "保留字段（原版未使用）"
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl_f = QLabel(label)
            lbl_f.setProperty("class", "PropLabel")
            lbl_f.setToolTip(comment)
            cell.addWidget(lbl_f)

            spin = _NoWheelSpinBox()
            spin.setRange(-32768, 32767)
            spin.setValue(0)
            spin.setMinimumWidth(88)
            spin.setToolTip(comment)
            self._param_vars.append(spin)
            cell.addWidget(spin)
            advanced_layout.addLayout(cell, r, c)

        if advanced_indices:
            last_row = (len(advanced_indices) - 1) // 4
            for c in range(4):
                advanced_layout.setColumnStretch(c, 1)
            if len(advanced_indices) % 4:
                for c in range(len(advanced_indices) % 4, 4):
                    advanced_layout.addWidget(QWidget(), last_row, c)

        advanced.setVisible(False)
        toggle = QPushButton("高级字段")
        toggle.setCheckable(True)
        toggle.setFixedWidth(100)
        toggle.toggled.connect(advanced.setVisible)
        toggle.toggled.connect(
            lambda checked: toggle.setText(
                "收起高级" if checked else "高级字段"))
        inner.layout().addWidget(advanced)
        inner.layout().addWidget(toggle)
        inner.layout().addStretch()

    # ── Tab 4: 音效安排 ──

    def _build_tail_tab(self):
        inner = self._build_scroll_tab("音效安排")

        lbl = QLabel(
            "动画播到指定时间时播放一个音效。最多可以安排 16 次；\n"
            "音效编号为 0 表示这一格不用。点击“试听”可以先检查声音。")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "PropLabel")
        inner.layout().addWidget(lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(8)
        headers = ["序号", "音效编号", "播放时间", "试听", "实际文件"]
        for c, title in enumerate(headers):
            head = QLabel(title)
            head.setProperty("class", "PropLabel")
            if c:
                head.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(head, 0, c)

        self._tail_vars = []
        self._tail_file_lbls = []

        for pair in range(16):
            r = pair + 1
            no = QLabel(f"{pair + 1:02d}")
            no.setAlignment(Qt.AlignCenter)
            grid.addWidget(no, r, 0)

            le_id = _NoWheelSpinBox()
            le_id.setRange(0, 32767)
            le_id.setValue(0)
            le_id.setFixedWidth(82)
            le_id.setToolTip("0 表示不用这一格。")
            grid.addWidget(le_id, r, 1)
            self._tail_vars.append(le_id)

            le_tick = _NoWheelSpinBox()
            le_tick.setRange(0, 32767)
            le_tick.setValue(0)
            le_tick.setFixedWidth(82)
            le_tick.setToolTip("动画播放到这个时间时播放声音。")
            grid.addWidget(le_tick, r, 2)
            self._tail_vars.append(le_tick)

            btn = QPushButton("试听")
            btn.setMinimumWidth(70)
            btn.setToolTip("试听此音效编号对应的游戏声音。")
            btn.clicked.connect(lambda checked, idx=pair: self._on_tail_preview(idx))
            grid.addWidget(btn, r, 3)

            fl = QLabel("")
            fl.setProperty("class", "ExtraPreviewText")
            fl.setWordWrap(True)
            fl.setMinimumWidth(180)
            grid.addWidget(fl, r, 4)
            self._tail_file_lbls.append(fl)

            le_id.valueChanged.connect(
                lambda value, idx=pair: self._refresh_tail_file_lbl(idx))

        grid.setColumnStretch(4, 1)
        inner.layout().addLayout(grid)
        inner.layout().addStretch()

    # ── 数据加载 ──

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
        font_path = os.path.join(d, "FONT9696")

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
        self.font_path = font_path if os.path.exists(font_path) else None
        self._font = ActFont9696(self.font_path or "")
        self._float_specs = []
        self._reload()

    def _reload(self):
        if not self.act_path:
            return
        if is_running(getattr(self, '_load_worker', None)):
            return
        self._preview_stop()
        self._aa_data = None
        self._af_data = None
        self._jvg_cache.clear()
        self._pil_cache.clear()
        self.status_var.setText("加载中…")
        act_path = self.act_path
        compact_threshold = self._compact_threshold()

        # 后台线程: 纯文件 IO/解码 (P3-3), UI 刷新在 _on_load_success
        def work(w):
            entries = load_act(act_path)
            names = self._build_act_names(
                os.path.dirname(act_path), compact_threshold)
            return entries, names

        self._load_worker = run_background(
            self, work,
            on_success=self._on_load_success,
            on_error=self._on_load_error)

    def _on_load_success(self, result):
        entries, names = result
        self.entries = entries
        self.names = names
        self._dirty = False
        nonempty = sum(1 for e in self.entries if not entry_is_empty(e))
        self.status_var.setText(
            f"{len(self.entries)} 条 (784 字节/条) | 非空 {nonempty}")
        self._set_edit_enabled(True)
        self._update_paths()
        self._apply_filter()

    def _on_load_error(self, err_msg):
        QMessageBox.critical(self, "加载失败", err_msg)
        self.entries = []
        self._set_edit_enabled(True)
        self._update_paths()
        self._apply_filter()

    def _build_act_names(self, tks_dir: str, compact_threshold: int = 3) -> dict[int, str]:
        """构建 TKAct 索引 → 名称 的反向映射。

        TKAct 条目被 TKKon.tkact_id 和 TKItem.tkkon_index→TKKon.tkact_id
        多对一引用。此方法收集所有引用源并合并显示。

        与 kon_editor.kon_record_name 一致: "空槽-#N" 与 "动画#N" 类
        解析器兜底名不作为名称 (动画#N 对 act 行是循环噪声, 扩展
        TKKon 条目未接线时尤其如此)。多来源名称用空格连接成单行,
        与解析器的跨角色拼接约定一致。
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
            if name and not name.startswith(('空槽-', '动画#')):
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
                        if kon_name and not kon_name.startswith(('空槽-', '动画#')):
                            if act_idx not in names:
                                names[act_idx] = []
                            if kon_name not in names[act_idx]:
                                names[act_idx].append(kon_name)
            except Exception:
                pass

        return {k: ' '.join(v) for k, v in names.items()}

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
            name_item = QTableWidgetItem(nm)
            # 长名称被列宽截断时悬浮看全文 (与 kon_editor 各格 tooltip 一致)
            name_item.setToolTip(nm)
            self.table.setItem(row, 1, name_item)
            n_layer = len(entry_active_layers(entry))
            self.table.setItem(row, 2, QTableWidgetItem(f"{n_layer} 个图层"))
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
            for ci in range(3):
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
            if themed_question(
                    self, "确认覆盖",
                    f"粘贴将覆盖条目 #{idx} 的现有内容，是否继续？") != QMessageBox.Yes:
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
        entry_index = entry['index']
        switched_entry = self._editing_idx != entry_index
        self._editing_idx = entry_index
        self._float_specs = self._make_float_specs(entry)
        active = sorted(entry_active_layers(entry))
        refd = sorted(entry_referenced_layers(entry))
        self.preview_canvas.set_entry_title(
            f"动画 #{entry['index']}  "
            f"活跃图层 {active if active else '(空)'}  "
            f"方向表引用 {refd if refd else '(无)'}")

        for d in range(4):
            for i in range(8):
                if self._dir_vars[d][i] is not None:
                    self._set_editor_text(
                        self._dir_vars[d][i], str(entry['dirs'][d][i]))

        for s in range(ACT_MAX_LAYER):
            self._populate_layer(s, entry['layers'][s])

        for k, param_idx in enumerate(self._param_indices):
            if k < len(self._param_vars):
                self._set_editor_text(
                    self._param_vars[k], str(entry['param16'][param_idx]))

        for k in range(len(self._tail_vars)):
            if k < len(self._tail_vars):
                self._set_editor_text(
                    self._tail_vars[k], str(entry['tail'][k]))

        # 更新卡片标签
        for s in range(ACT_MAX_LAYER):
            t = entry['layers'][s][0]
            lbl = self._layer_vars[s].get('_card_label')
            slot_btn = (
                self._layer_slot_buttons[s]
                if s < len(self._layer_slot_buttons) else None
            )
            if lbl:
                if t == 0:
                    lbl.setText(f"图层 {s+1}")
                else:
                    full = LAYER_TYPE_LABELS.get(t, str(t))
                    parts = full.split(' ', 1)
                    lab = parts[1].split('(')[0].strip() if len(parts) > 1 else full
                    lbl.setText(f"图层 {s+1}")
            if slot_btn is not None:
                if t == 0:
                    slot_btn.setToolTip(f"图层 {s+1}：目前不用")
                else:
                    slot_btn.setToolTip(f"图层 {s+1}：{lab}")

        if switched_entry:
            self._select_layer_card(active[0] - 1 if active else 0)

        # 刷新尾部文件标签
        for pair in range(16):
            self._refresh_tail_file_lbl(pair)

        self._preview_reload()
        self._tl_auto_zoom()

    def _on_float_type_changed(self, _index=None):
        if self._float_type_cb is None:
            return
        self._float_type = (
            self._float_type_cb.currentData() or DEFAULT_FLOAT_TYPE)
        ft = FLOAT_TYPE_MAP.get(self._float_type)
        if ft:
            self.status_var.setText(f"飘字效果: {ft['label']}")
        self._sync_float_total_enabled()
        self._refresh_float_specs()

    def _on_float_total_changed(self, value=None):
        if self._float_total_spin is None:
            return
        self._float_total = int(self._float_total_spin.value())
        self._refresh_float_specs()

    def _on_float_effect_toggled(self, state):
        """开关预览飘字效果: 关闭时同步置灰类型/数值控件并清空飘字数据。"""
        self._float_effect_on = bool(state)
        self._float_type_cb.setEnabled(self._float_effect_on)
        self._sync_float_total_enabled()
        self._refresh_float_specs()
        self.status_var.setText(
            "飘字效果: 开启" if self._float_effect_on else "飘字效果: 已关闭")

    def _sync_float_total_enabled(self):
        if self._float_total_spin is None:
            return
        ft = self._current_float_type()
        is_number = ft.get('kind') == 'number'
        self._float_total_spin.setEnabled(self._float_effect_on and is_number)
        if not self._float_effect_on:
            self._float_total_spin.setToolTip("飘字效果已关闭")
        else:
            self._float_total_spin.setToolTip(
                "数字类飘字的预览总值，按触发帧分摊后显示；默认 999"
                if is_number else
                "当前为文字类飘字，不使用数值分摊")

    def _preview_float_total(self, float_type=None):
        """返回数字类飘字的预览总值；文字类回退到类型默认值。"""
        if self is not None:
            spin = getattr(self, '_float_total_spin', None)
            if spin is not None:
                return int(spin.value())
            total = getattr(self, '_float_total', None)
            if isinstance(total, int) and total > 0:
                return total
        ft = ActEditorV2._current_float_type(self, float_type)
        return int(ft.get('total', DEFAULT_FLOAT_TOTAL))

    def _refresh_float_specs(self):
        if self._editing_idx >= 0 and self._editing_idx < len(self.entries):
            self._float_specs = self._make_float_specs(
                self.entries[self._editing_idx])
        else:
            self._float_specs = []
        self._preview_redraw()

    def _current_float_type(self, float_type=None):
        if float_type:
            return FLOAT_TYPE_MAP.get(
                float_type, FLOAT_TYPE_MAP[DEFAULT_FLOAT_TYPE])
        if self is not None:
            key = getattr(self, '_float_type', DEFAULT_FLOAT_TYPE)
        else:
            key = DEFAULT_FLOAT_TYPE
        return FLOAT_TYPE_MAP.get(key, FLOAT_TYPE_MAP[DEFAULT_FLOAT_TYPE])

    def _make_float_specs(self, entry, float_type=None, total=None):
        """对应 sub_433F04：按数值出现时间登记飘字并分摊总值。"""
        # 测试可能以 self=None 调用；始终经类方法解析类型。
        if self is not None and not self._float_effect_on:
            return []  # 预览飘字被工具栏开关关闭
        ft = ActEditorV2._current_float_type(self, float_type)
        triggers = [v for v in entry['param16'][4:12] if v > 0]
        if not triggers:
            return []
        rng = random.Random(entry['index'])
        specs = []
        if ft['kind'] == 'number':
            if total is None:
                total = ActEditorV2._preview_float_total(self, float_type)
            rem = int(total)
            if rem <= 0:
                rem = DEFAULT_FLOAT_TOTAL
            colors = ft['colors']
            segment_count = len(triggers)
            for i, start_tick in enumerate(triggers):
                div = segment_count - i
                value = rem // div + rem % div
                rem -= value
                color_idx = colors[i % len(colors)]
                off_x = rng.randrange(33) - 16
                if value >= 100:
                    off_x -= 20
                if value >= 1000:
                    off_x -= 20
                off_y = rng.randrange(25) - 12
                specs.append({
                    'start_tick': start_tick,
                    'value': value,
                    'text': str(value),
                    'color': color_idx,
                    'off_x': off_x,
                    'off_y': off_y,
                })
        else:
            text = ft.get('text', '')
            color_idx = ft['color_idx']
            for start_tick in triggers:
                off_x = rng.randrange(33) - 16
                off_y = rng.randrange(25) - 12
                specs.append({
                    'start_tick': start_tick,
                    'value': None,
                    'text': text,
                    'color': color_idx,
                    'off_x': off_x,
                    'off_y': off_y,
                })
        return specs

    @staticmethod
    def _float_end_tick(entry):
        """返回最后一个飘字 18 帧生命周期结束后的 tick。"""
        triggers = [v for v in entry['param16'][4:12] if v > 0]
        return max((v + 18 for v in triggers), default=0)

    def _preview_active_floats(self, tick: int, enemy_x: int, enemy_y: int):
        """对应 sub_433D44：触发后按原版 18 帧曲线绘制。"""
        active = []
        ft = (
            self._current_float_type()
            if hasattr(self, '_current_float_type')
            else ActEditorV2._current_float_type(self)
        )
        is_text = ft.get('kind') == 'text'
        # 原版：数字偏移 -12（sub_433D44），文字偏移 -60（sub_433A38）。
        x_base = enemy_x - (60 if is_text else 12)
        for spec in self._float_specs:
            stage = tick - spec['start_tick']
            if stage < 0 or stage >= len(FLOAT_Y_CURVE) - 1:
                continue
            x = spec['off_x'] + x_base
            # 预览没有单独的目标 Awt 帧；假想敌标记高 40，等价于帧高 + 30。
            y = spec['off_y'] + FLOAT_Y_CURVE[stage + 1] + enemy_y - 70
            text = spec.get('text')
            if not text and spec.get('value') is not None:
                text = str(spec['value'])
            color_idx = spec.get('color', 18)
            active.append({
                'x': x,
                'y': y,
                'text': text or '',
                'color': FONT_COLORS.get(color_idx, (255, 0, 0)),
                'ftype': 4,
                'size': 24,
                'outline': True,
            })
        return active
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
            elif isinstance(widget, QSpinBox):
                widget.blockSignals(True)
                widget.setValue(v)
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
            fl.setText(f"可用帧 {vals[17]}..{vals[18]}")

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
                elif isinstance(w, QSpinBox):
                    raw = str(w.value())
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
            lbl.setText("这个图层目前不使用。")
            return

        if ltype >= 4:
            name = {4: '位置标记', 5: '全屏特效'}.get(ltype, '不显示画面的标记')
            lbl.setText(f"{name}：不需要选择图片素材。")
            return

        if ltype == 1:
            src_name, counts = 'Aa.jvg', self._aa_counts
        else:
            src_name, counts = 'Af.jvg', self._af_counts

        if not counts:
            lbl.setText(f"素材 {src_name} #{blk}：尚未加载游戏资源，无法检查帧数。")
            return
        if blk < 0 or blk >= len(counts):
            lbl.setText(
                f"素材编号 {blk} 超出范围：{src_name} 里可用编号是 "
                f"0~{len(counts) - 1}。")
            return

        n_frames = counts[blk]
        _, _, is_std = infer_jvg_layout(n_frames)

        if dmode == 4:
            read_max = last + dfo * 3
            span_desc = f"跟随朝向播放：每个朝向错开 {dfo} 帧，最后读到第 {read_max} 帧"
        else:
            read_max = last
            span_desc = "固定画面方向：只读取当前这组帧"
        warn = ''
        if last >= n_frames or first < 0:
            warn = f"  注意：开始或结束帧超出素材可用范围 0~{n_frames-1}。"

        if warn:
            color = '#C33'
        elif is_std:
            color = '#093'
        else:
            color = '#AAA'

        lbl.setText(
            f"素材 {src_name} #{blk}：共 {n_frames} 帧，当前使用 {first}~{last}。\n"
            f"{span_desc}。{warn}")
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
            if isinstance(w, (QLineEdit, QSpinBox)):
                blk = int(self._editor_text(w) or '0')
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
            ('direction_mode', _enum_to_label(
                4 if dirs == 4 else 0, DIRECTION_MODE_LABELS)),
            ('first_frame', '0'),
            ('last_frame', str(per - 1)),
            ('dir_frame_offset', str(per)),
            ('loop_behavior', str(per - 1)),
        ]:
            w = vr.get(key)
            if isinstance(w, (QLineEdit, QSpinBox)):
                self._set_editor_text(w, val)
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
                    v = int(self._editor_text(self._dir_vars[d][i]) or 0)
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
                elif isinstance(w, QSpinBox):
                    raw = str(w.value())
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

        for k, param_idx in enumerate(self._param_indices):
            if k >= len(self._param_vars):
                continue
            v = int(self._editor_text(self._param_vars[k]) or 0)
            entry['param16'][param_idx] = max(-32768, min(32767, v))

        for k in range(len(self._tail_vars)):
            if k < len(self._tail_vars):
                v = int(self._editor_text(self._tail_vars[k]) or 0)
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
        if themed_question(
                self, "确认移除",
                f"确定移除扩展条目 #{idx} 吗？\n"
                "扩展区条目移除后，后续条目序号会自动前移。") != QMessageBox.Yes:
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
        if ask and themed_question(
                self, title,
                question_text or f"确定要清除条目 #{idx} 吗？\n此操作不可撤销。") != QMessageBox.Yes:
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
        if themed_question(self, "确认保存",
                f"保存 {len(self.entries)} 条到:\n{self.act_path}\n\n原文件将被覆盖 (生成 .bak).") != QMessageBox.Yes:
            return
        if is_running(getattr(self, '_save_worker', None)):
            return
        act_path = self.act_path
        entries = self.entries

        # 后台线程: .bak 备份 + 压缩写盘 (P3-3)
        def work(w):
            backup_existing_file(act_path)
            save_act(act_path, entries)
            return act_path

        self.status_var.setText("正在保存…")
        self._save_worker = run_background(
            self, work,
            on_success=self._on_save_success,
            on_error=self._on_save_error)

    def _on_save_success(self, act_path):
        self._dirty = False
        self.status_var.setText(f"已保存 → {act_path}")
        QMessageBox.information(self, "保存成功",
                                f"已保存\n备份: {act_path}.bak")

    def _on_save_error(self, err_msg):
        QMessageBox.critical(self, "保存失败", err_msg)

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
            sid = int(self._editor_text(self._tail_vars[pair_idx * 2]) or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            lbl.setText("(空位)")
            lbl.setProperty("probe", "empty")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        if self.sws_grp is None:
            lbl.setText(f"音效 #{sid:04d}  (未加载游戏数据目录)")
            lbl.setProperty("probe", "warn")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        info = self.sws_grp.wav_info(sid)
        if info is not None:
            ch, sr, bits, dur = info
            lbl.setText(
                f"音效 #{sid:03d}  {ch} 声道 {sr} 赫兹 {bits} 位 {dur:.2f} 秒")
            lbl.setProperty("probe", "ok")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        if sid >= self.sws_grp.section_count:
            lbl.setText(f"音效 #{sid}  超出段数({self.sws_grp.section_count})")
            lbl.setProperty("probe", "error")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            return
        lbl.setText(f"音效 #{sid:03d}  (非音频段)")
        lbl.setProperty("probe", "warn")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

    def _resolve_sound_path(self, sid):
        if sid <= 0 or self.sws_grp is None:
            return None
        return self.sws_grp.extract_to_temp(sid)

    def _on_tail_preview(self, pair_idx):
        try:
            sid = int(self._editor_text(self._tail_vars[pair_idx * 2]) or 0)
        except ValueError:
            sid = 0
        if sid <= 0:
            self.status_var.setText(f"尾部 #{pair_idx:02d}: 音效ID=0 空位, 无音效")
            return
        if self.sws_grp is None:
            QMessageBox.information(self, "未加载音效源",
                                   "请先通过 文件 → 加载 TKS 目录 来定位音效资源")
            return
        p = self._resolve_sound_path(sid)
        if not p:
            self.status_var.setText(f"未找到音效 音效ID={sid}")
            return
        alias = _mci_play_async(p)
        if alias is None:
            self.status_var.setText(f"播放失败: 音效ID={sid}")
        else:
            self.status_var.setText(f"> 音效ID={sid}")

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
        xs = [0, self._preview_enemy_x]
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
                base_x = self._preview_enemy_x if L[0] in (3, 4) else 0
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

            self._preview_redraw()
            self._tl_tick_lbl.setText(f"tick: {self._preview_tick_idx}")
            self.timeline_widget.set_playhead(self._preview_tick_idx)

            entry = self.entries[self._editing_idx]
            end_tick = self._tl_calc_duration(entry)
            if self._preview_tick_idx >= end_tick:
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

    def _on_marker_vis_changed(self):
        self.preview_canvas.set_marker_visibility(
            self._show_attacker_cb.isChecked(),
            self._show_defender_cb.isChecked())

    def _on_enemy_dist_changed(self, value):
        """同步滑杆/输入框; 包围盒含受击方位置, 需一并重算。"""
        self._preview_enemy_x = value
        for w in (self._enemy_dist_spin, self._enemy_dist_slider):
            if w.value() != value:
                w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(False)
        if self._editing_idx >= 0:
            self._preview_bbox = self._compute_entry_bbox(
                self.entries[self._editing_idx])
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
            self.preview_canvas.set_float_specs([])
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
            enemy_x = self._preview_enemy_x if L[0] in (3, 4) else 0
            spr_l = frame.x_off + ox + enemy_x
            spr_t = frame.y_off + oy
            spr_r = spr_l + frame.width - 1
            spr_b = spr_t + frame.height - 1
            dyn_x.extend([spr_l, spr_r, -ox - enemy_x])
            dyn_y.extend([spr_t, spr_b, -oy])
            sprites.append((slot, eff_dir, L, src, blk, cur_abs, frame,
                           ox, oy, spr_l, spr_t, spr_r, spr_b, False))

        if not sprites:
            self.preview_canvas.set_float_specs([])
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
        ex_c, ey_c = to_cv(self._preview_enemy_x, 0)

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

        active_floats = self._preview_active_floats(tick, ex_c, ey_c)
        if active_floats:
            ft = self._current_float_type()
            if ft.get('kind') == 'text':
                info.append(f"{ft['label']}: {ft.get('text', '')}")
            else:
                total = self._preview_float_total()
                info.append(f"{ft['label']}: {total} 分段显示")
        self.preview_canvas.set_float_specs(active_floats)
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
        # 原版主循环以条目 param16[2] 为总帧数；飘字可能晚于图层结束。
        max_tick = max(0, entry['param16'][2])
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
        return max(max_tick, self._float_end_tick(entry))

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
                if isinstance(sd, (QLineEdit, QSpinBox)):
                    sd.blockSignals(True)
                    self._set_editor_text(sd, str(L[22]))
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
            fl.setText(f"可用帧 {L[17]}..{L[18]}")
        sd = vr.get('start_delay')
        if isinstance(sd, (QLineEdit, QSpinBox)):
            sd.blockSignals(True)
            self._set_editor_text(sd, str(L[22]))
            sd.blockSignals(False)
        self.timeline_widget.update()

    def _tl_handle_release(self, was_sfx):
        if self._editing_idx >= 0:
            entry = self.entries[self._editing_idx]
            if was_sfx:
                tail = entry.get('tail') or []
                for k in range(32):
                    if k < len(self._tail_vars):
                        self._set_editor_text(
                            self._tail_vars[k], str(tail[k]))
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
        if themed_question(self, "确认",
                f"确定清空图层 #{layer_idx + 1} 的所有数据?") != QMessageBox.Yes:
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
            self.status_var.setText(f"试听 音效ID={sid}")
        else:
            self.status_var.setText(f"未找到音效 音效ID={sid}")

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
    def _extra_help_actions(self):
        """帮助菜单专属项: 字段参考 (挂在"帮助说明"之后)。"""
        return [("字段参考", self._show_field_ref)]

    def _show_field_ref(self):
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
            "【条目级参数 (bytes 32-79, int16[0..23])】",
            "  [2] 动画总帧数（word_9D039E, byte +36）",
            "  [4..11] 第1~8次飘字触发帧（word_9D03A2[0..7], byte +40..55）",
            "  已填写的飘字触发时间数量决定伤害或恢复数值的分段数；最多8次",
            "  飘字触发时间按原版规则应与总帧数范围配合使用",
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

        show_field_ref(self, '\n'.join(lines), size=(760, 640))

    # 逆向参考: sub_4434BC, sub_42FEE0, sub_451780, sub_458D08

    # ── 窗口关闭 ──

    def _extra_close_guard(self):
        """关闭前清理: 停预览播放 + 删除 SWS 音效临时文件 (基类确认退出后调用)。"""
        self._preview_stop()
        _cleanup_sws_tempfiles()


# ============================================================
# 入口
# ============================================================

def main():
    run_editor(ActEditorV2, "TKAct Editor")


if __name__ == '__main__':
    main()
