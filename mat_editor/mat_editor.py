#!/usr/bin/env python3
"""
TKMat.Dat 地图实体编辑器 — PySide6 Godot 风格版
=============================================================
逆向依据 (已通过 运行时转储 反编译源码逐字段验证):
  sub_412688:21: TKMat.Dat → dword_51AF40 (2304000B, 6000×384B, 96 DWORD/实体) ✓已验证
  sub_402E88: TKDefUnit.dat 加载 — 条数=dword_753504(原版 mov eax,5000), 缓冲区/读取/遍历皆 count<<4 派生; 每条 16B ✓已验证
  sub_405CBC: 实体类型分支渲染 (5/10/15/16/20/110/200) ✓已验证
  sub_4077E4: 朝向 [13] ✓已验证
  sub_407070: 坐标 [10][11], 碰撞盒 [18][19][20][21] ✓已验证
  sub_406864: 渲染混合 [24](switch 0-5), blend_param[25], 优先级[22], 精灵偏移[26][27], 阴影帧[55] ✓已验证
  sub_409618: 主Tick循环 — A链=自动(d33>0) B链=触发(交互), d4=Tick周期, d3=等待计时器 ✓已验证
  sub_4081F8: type=10 出入传送点 — d50条件, d51方向掩码, d52目标场景, d53/d54目标XY, d56朝向 ✓已验证
  sub_4084E0: type=16 随机战斗区 — d50条件, d51方向掩码, d52-d54战斗ID组(3连), d55-d57概率组(3连, v4[3]=*(v4+12B)对齐), d60冷却基准, d61冷却计时, d62等级同步(0固定/1追随队伍均级) ✓已验证
  sub_408704: type=20 事件对象 — 动画帧推进(d14/d17递增), d66循环等待, d67帧起点, d68终点, d69保留末帧, d71-d95音效事件对(偶数=音效ID/奇数=触发帧, 汇编: mov edx,[eax+0x140]传入PlaySound) ✓已验证
  type=5: 脚本对象 — sub_409618 显式跳过(无专用tick), 仅执行脚本(sub_40EBD4) ✓已验证
  sub_408E5C: 玩家点击交互 — B链触发, d34条件脚本 ✓已验证
  sub_408B30: 特殊机关(110) — d50帧计数器, d51帧偏移, d52行为模式(0/1/2), d53-d64物品组 ✓已验证
  sub_40EBD4: 脚本VM — d42=PC, d43=saved_PC, d30-d32=max链, d33-d35=cur链, End模式0xFFFF-0xFFFA ✓已验证
  sub_405CBC+sub_4077E4+sub_408E5C: type=200 NPC — d51立绘ID→d52句柄, d53方向模式(4/8), d55阴影帧, d56-d62寻路备份, d64行走动画, d70站桩/行走 ✓已验证

  验证方法: 反编译 .c 文件中 entity 指针偏移量 ÷ 4 = dword 索引, 与编辑器字段索引对照确认

用法:
  python mat_editor.py
"""

import base64
import csv
import json
import os
import re
import struct
import sys
import time
import traceback
from collections import Counter, OrderedDict, defaultdict
from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QTextEdit, QPlainTextEdit, QMessageBox, QFileDialog,
    QDialog, QGridLayout, QFrame, QScrollArea, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QSizePolicy, QStatusBar
)
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QFont, QIcon, QPixmap, QImage,
    QPainter, QTextCursor, QTextCharFormat, QSyntaxHighlighter
)
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QSize, QThread, Signal, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils import theme_manager
from editor_utils.theme_switcher import (
    apply_theme_to_window, create_theme_menu, toggle_theme_in_family,
)
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.lzss import lzss_decompress_dat as lzss_decompress, lzss_decompress_save, lzss_compress_save
from editor_utils.ui_helpers import confirm_close, themed_messagebox, EditorComboBox
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.version import format_title, format_about_header
from editor_utils.shared_state import pick_tks_directory
from editor_utils.mod_exporter import (
    diff_records, diff_text_defines, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, build_text_diff_json, ModMetadataDialog,
    load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, import_tksmod_text_defines,
    import_tksmod_blocks,
    ModImportPreviewDialog, ModExportPreviewDialog,
    diff_binary_blocks, build_block_diff_json, load_grp_raw_sections,
    safe_mod_filename,
)

from mat_constants import (
    REC_SIZE, REC_COUNT, FILE_SIZE, DWORD_COUNT, SCENE_NAME_TKT_BASE,
    DEFUNIT_REC_SIZE, DEFUNIT_REC_COUNT, DEFUNIT_FILE_SIZE,
    ENTITY_TYPES, TYPE_COLORS, TYPE_COLORS_RGBA, DISPLAY_MODES,
    _GAME_PALETTE_565, _rgb565_to_hex, GAME_COLORS, DEFAULT_TKT_FCOLOR,
    _CONTROL_TAGS, _LINE_SEP,
    BASIC_FIELDS, FLAG_FIELDS, POS_FIELDS, ANIM_FIELDS,
    SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS, ITEM_FIELDS, ALL_EDIT_FIELDS,
    _TYPE_LABELS, MAX_MAP_W, MAX_MAP_H,
    IDX_TYPE, IDX_SCENE_ID, IDX_FLAGS, IDX_WAIT, IDX_TICK, IDX_TICK_COUNTER,
    IDX_CURSOR_ID, IDX_ANIM_SET, IDX_POS_X, IDX_POS_Y, IDX_INTERACT_DIST,
    IDX_DIRECTION, IDX_FRAME_IDX, IDX_FRAME_COUNT, IDX_FRAME_CUR, IDX_PRIORITY,
    IDX_BOUND_X, IDX_BOUND_Y, IDX_BOUND_W, IDX_BOUND_H, IDX_BLEND_MODE,
    IDX_BLEND_PARAM, IDX_SPRITE_OFF_X, IDX_SPRITE_OFF_Y, IDX_TIMER,
    IDX_DIALOG_COLOR, IDX_MAX_A, IDX_MAX_B, IDX_MAX_C, IDX_CUR_A, IDX_CUR_B,
    IDX_CUR_C, IDX_HEAD_A, IDX_HEAD_B, IDX_HEAD_C, IDX_SCRIPT_PC, IDX_SAVED_PC,
    IDX_DEFUNIT_IDX, IDX_COND_ID, IDX_DIR_MASK, IDX_TARGET_SCENE, IDX_DIR_MODE,
    IDX_TARGET_Y, IDX_SHADOW_FRAME, IDX_TARGET_DIR, IDX_SAVED_Y, IDX_ALT_TELE_X,
    IDX_ALT_TELE_Y, IDX_SUB_MODEL, IDX_MOVING, IDX_HINT_ID,
    TYPE_SKIP_DWORDS,
)
HAS_PIL = False
try:
    from PIL import Image, ImageChops, ImageDraw, ImageOps
    HAS_PIL = True
except ImportError:
    pass

# ============================================================
# 常量
# ============================================================

# ============================================================
# 模块化拆分 (§工程化): 纯逻辑/数据/组件/线程已迁出, 主文件仅保留业务类
# ============================================================
from mat_text_codec import (
    load_tkd, save_tkd, parse_defines, rebuild_text, parse_tkt_colored_segments,
)
from mat_dat_io import (
    get_script_info, is_empty, has_data, scene_name,
    save_mat, save_defunit, load_mat_from_save, save_mat_to_save,
)
from mat_script_desc import SCRIPT_CMD_DESC, _CURSOR_BLOCKS, _tkt_text, _menu_options, format_cmd_params, _dir_name
from mat_render import (
    _SPRITE_CACHE, _SHADOW_CACHE, _BLEND_CACHE, _RGBA_CACHE,
    _get_dir_frame, _get_jvg_frame_rgba,
    _pil_normal, _pil_tint, _pil_additive, _pil_subtract, _pil_luma_alpha,
    _pil_to_qpixmap, load_scene_background, load_scene_background_from_bytes,
    load_scene_background_and_layers, load_scene_layers_from_bytes,
    make_layer_image, entity_occlusion_depth, composite_occluded,
)
from mat_widgets import CodeEditor, ScriptSyntaxHighlighter
from mat_script_templates import SCRIPT_TEMPLATES
from mat_threads import DataLoaderThread, JvgLoaderThread

# [28] 对话颜色字段的 dword 索引 (IDX_DIALOG_COLOR='d28' → 28), 供新增实体默认值判断 (§需求4)
_DIALOG_COLOR_IDX = int(IDX_DIALOG_COLOR[1:])
_FIELD_LABEL_MAX_WIDTH = 100
_TYPE_COMBO_MAX_WIDTH = 140
_COMBO_MAX_WIDTH = 120

class MapDataManager:
    """地图数据状态与装配层 (§5) — 从 MatEditorApp 拆出的纯数据职责。
    持有 records/defunit/tkt/tkd 等数据状态, 提供 load_from_result 装配与 reset 重置。
    MatEditorApp 通过 self._data 访问; SceneCanvasView 通过 self._data (editor._data
    的快捷引用) 访问, 同时保留 self._editor 反向引用编辑器回调。"""

    def __init__(self):
        # 文件路径
        self.dat_path = None
        self.tkt_path = None
        # 主数据
        self.records = []
        self.defunit_recs = []
        self.defunit_next = {}
        self.defunit_entity = {}
        self.tkd_defines = []
        self.tkd_header = ''
        self.tkd_define_map = {}
        self.tkt_all = {}
        self.tkt_scenes = {}
        self.item_names = {}
        self.filtered_indices = []
        # SC.GRP 待保存数据
        self._sc_grp_section_count = 0
        self._sc_grp_pending = None
        # 存档模式状态
        self._save_mode = False
        self._save_path = None
        self._save_slot = 0
        self._game_dir = None
        # 脏标记
        self._dirty = False

    def load_from_result(self, result):
        """从 DataLoaderThread 返回的结果装配全部数据状态"""
        self.tkt_scenes = result.get('tkt_scenes', {})
        self.tkt_all = result.get('tkt_all', {})
        self.defunit_recs = result.get('defunit_recs', [])
        self.defunit_next = result.get('defunit_next', {})
        self.defunit_entity = result.get('defunit_entity', {})
        self.tkd_defines = result.get('tkd_defines', [])
        self.tkd_header = result.get('tkd_header', '')
        self.tkd_define_map = result.get('tkd_define_map', {})
        self.item_names = result.get('item_names', {})
        self._sc_grp_section_count = result.get('sc_grp_section_count', 0)
        self.records = result.get('records', [])

    def reset(self):
        """重置全部数据状态到空"""
        self.__init__()


class SceneCanvasView(QGraphicsView):
    """场景画布视图 — 从 MatEditorApp 拆出的可视化渲染与交互层 (§4)。
    持有画布自有状态, 通过 self._editor 反向引用编辑器回调, 通过 self._data
    (editor._data 的快捷引用) 直接访问数据层, 避免迪米特法则链式访问。"""

    def __init__(self, editor, parent=None):
        scene = QGraphicsScene()
        super().__init__(scene, parent)
        self._editor = editor
        # 数据层快捷引用 (§4 进阶③) — 避免对 editor 数据层的链式访问,
        # 直接持有 MapDataManager 实例引用以遵循迪米特法则
        self._data = editor._data
        # 画布自有状态 (从 MatEditorApp.__init__ 迁出)
        self._vis_scene_id = 0
        self._vis_bg_pil = None
        self._vis_bg_pixmap = None
        # GRP Frame B 逐像素图层 (真实碰撞/前景数据, 逆向 sub_411308/sub_42FA50):
        #   L1 前景遮挡深度 (逐像素遮挡采样) / L2 地形碰撞类型 (实体深度源)
        self._vis_layer1_img = None       # L1 PIL 'L' (世界坐标对齐背景左上)
        self._vis_layer2_img = None       # L2 PIL 'L' (供 entity_occlusion_depth 实体深度)
        self._vis_layer_w = 0
        self._vis_layer_h = 0
        self._vis_entities = {}
        self._vis_hit_regions = {}
        self._vis_selected = None
        self._vis_drag = None
        self._vis_edit_mode = False
        # 撤销栈: [(描述, [(实体index, 记录快照dict), ...]), ...]
        # 覆盖 拖动移动 / 新增 / 复制 / 删除 四类操作, Ctrl+Z 逐步回退 (§需求3)
        self._undo_stack = []
        self._undo_limit = 100
        # 拖动前的完整记录快照, 在 mouseReleaseEvent 判定确有位移后才压栈
        self._drag_undo_snapshot = None
        self._vis_display_mode = "游戏默认"
        self._vis_anim_playing = False
        self._vis_anim_timer = None
        self._vis_anim_frame = {}
        self._vis_sel_anim_active = False
        self._vis_sel_anim_timer = None
        self._vis_gscene = scene
        self._vis_bg_item = None
        # QGraphicsView 属性配置 (原 _build_center_panel 中的设置)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def update_vis_background(self):
        """设置中间预览区 QGraphicsView 的背景色, 使深色区域填满整个预览区
        (对应 v1 tk.Canvas 的 bg)。场景矩形外的空白也以此色填充。"""
        # 与 editor_themes/*.qss 的 QGraphicsView background-color 一致
        bg = QColor('#1a1e27') if self._editor._is_dark else QColor('#ffffff')
        self.setBackgroundBrush(bg)


    @staticmethod
    def _vis_sort_key(r):
        """实体渲染排序键 — 逆向 sub_405CBC / sub_406444 排序逻辑:
          1) 主键 d29 图层 (原版数据恒为 0, 保留以兼容自定义 mod 的显式分层)
          2) 背景标志 d2&0x1000 → 组0 最先绘制(最底层)
             前景标志 d2&0x2000 → 组2 最后绘制(最顶层, 即"前景层"如树冠/屋檐)
             其余普通实体 → 组1, 按 pos_y(d11) 升序 = Y 排序(越靠下越后画/越靠前)
          注: d22(优先级)是运行时由碰撞网格求得的地形遮挡深度(sub_406E50),
              不参与排序, 故此处不用。type=10 用碰撞盒 Y(d19) 作占位排序。"""
        layer = r.get('d29', 0)
        flags = r.get('d2', 0)
        if flags & 0x1000:
            return (layer, 0, 0)
        if flags & 0x2000:
            return (layer, 2, 0)
        y = r['d19'] if r['d0'] == 10 else r['d11']
        return (layer, 1, y)

    def _vis_render_scene(self, ents, w, h):
        """PIL 预合成整个场景并显示到 QGraphicsView"""

        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')

        # Background — 匹配 QGraphicsView 的 QSS 主题背景色
        # 深色主题 #1a1e27 → (26, 30, 39), 浅色主题 #ffffff → (255, 255, 255)
        bg_color = (26, 30, 39) if self._editor._is_dark else (255, 255, 255)
        if self._vis_bg_pil:
            composite = self._vis_bg_pil.copy()
            if composite.width < w or composite.height < h:
                new_bg = Image.new('RGB', (w, h), bg_color)
                new_bg.paste(composite, (0, 0))
                composite = new_bg
        else:
            composite = Image.new('RGB', (w, h), bg_color)

        # ============================================================
        # Pass 1: 实体精灵合成 — 严格按游戏渲染顺序 (ents 已按 _vis_sort_key 排序)
        #   背景标志(d2&0x1000)最先绘制(最底) → 普通实体按 pos_y 升序(Y排序)
        #   → 前景标志(d2&0x2000)最后绘制(最顶), 复刻 sub_405CBC/sub_406444
        #   逐实体先绘阴影(减法)再绘精灵(按混合模式), 复刻 sub_406864
        # ============================================================
        had_jvg = set()   # 尝试过精灵渲染(有有效 JVG 块)的实体
        drawn = set()     # 成功合成了精灵的实体
        # 前景遮挡开关: L1 前景深度存在且开关开启时, 精灵按逐像素深度被景物遮挡
        occlude = getattr(self._editor, '_vis_occlusion_cb', None)
        occlude = (occlude.isChecked() if occlude is not None else True) \
            and self._vis_layer1_img is not None
        for r in ents:
            tval = r[IDX_TYPE]
            show = self._editor._type_filter_cbs.get(tval)
            if show and not show.isChecked():
                continue
            idx = r['index']
            x = r[IDX_POS_X]
            y = r[IDX_POS_Y]
            ox = r.get('d26', 0)
            oy = r.get('d27', 0)

            jvg = None
            blk_idx = 0
            should_animate = False
            if mode != 'wire':
                if mode == 'auto':
                    if tval == 200:
                        if r['d70'] == 1 and r['d64'] > 0 and self._editor._ani_jvg:
                            jvg = self._editor._ani_jvg
                            blk_idx = r['d64']
                            should_animate = True
                        elif r['d51'] > 0 and self._editor._cha_jvg:
                            jvg = self._editor._cha_jvg
                            blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._editor._ani_jvg:
                        jvg = self._editor._ani_jvg
                        blk_idx = r['d64']
                        should_animate = True
                elif mode == 'ani':
                    if tval in (200, 20, 110) and r['d64'] > 0 and self._editor._ani_jvg:
                        jvg = self._editor._ani_jvg
                        blk_idx = r['d64']
                        should_animate = True
                elif mode == 'cha':
                    if tval == 200 and r['d51'] > 0 and self._editor._cha_jvg:
                        jvg = self._editor._cha_jvg
                        blk_idx = r['d51']
                    elif tval in (20, 110) and r['d64'] > 0 and self._editor._ani_jvg:
                        jvg = self._editor._ani_jvg
                        blk_idx = r['d64']

            if not (jvg and blk_idx < jvg.block_count):
                continue
            had_jvg.add(idx)
            blk = jvg.blocks[blk_idx]
            if not blk.frames:
                continue
            if should_animate and idx not in self._vis_anim_frame:
                self._vis_anim_frame[idx] = 0
            anim = self._vis_anim_frame.get(idx, 0) if should_animate else 0
            fi, fpd = _get_dir_frame(blk, r['d13'], r['d16'], r['d53'], anim)
            if fi >= len(blk.frames):
                continue
            blend_mode = r.get('d24', 0)
            blend_param = r.get('d25', 0)
            sprite_rgba = _get_jvg_frame_rgba(jvg, blk_idx, fi)
            if not sprite_rgba:
                continue
            sx = x + ox + blk.frames[fi].x_off
            sy = y + oy + blk.frames[fi].y_off
            if blend_mode == 5:
                sprite_rgba = ImageOps.mirror(sprite_rgba)
            if blend_mode == 1:
                sprite_rgba = _pil_tint(sprite_rgba, blend_param)
            # 阴影(减法混合) — 复刻 sub_406864 精灵前先绘阴影帧
            shadow_fi = r.get('d55', 0)
            if shadow_fi > 0 and (tval == 200 or tval == 20) and jvg is self._editor._cha_jvg and jvg.block_count > 0:
                blk0 = jvg.blocks[0]
                if blk0.frames and shadow_fi < blk0.frame_count:
                    shadow_rgba = _get_jvg_frame_rgba(jvg, 0, shadow_fi)
                    _pil_subtract(composite, shadow_rgba,
                                  x + ox + jvg.blocks[0].frames[shadow_fi].x_off,
                                  y + oy + jvg.blocks[0].frames[shadow_fi].y_off)
            # 命中区 (碰撞盒优先, 退化到精灵尺寸)
            bx, by = r[IDX_BOUND_X], r[IDX_BOUND_Y]
            bw = r[IDX_BOUND_W] if r[IDX_BOUND_W] > 0 else sprite_rgba.width
            bh = r[IDX_BOUND_H] if r[IDX_BOUND_H] > 0 else sprite_rgba.height
            self._vis_hit_regions[idx] = (bx, by, bx + bw, by + bh)
            # 合成精灵 (按混合模式 d24)
            if blend_mode == 2:
                _pil_additive(composite, sprite_rgba, sx, sy, blend_param)
            elif blend_mode == 3:
                _pil_subtract(composite, sprite_rgba, sx, sy)
            elif blend_mode == 4:
                _pil_luma_alpha(composite, sprite_rgba, sx, sy)
            elif occlude:
                # 前景遮挡 (逆向 sub_406E50 + sub_459F78): 实体深度=脚下碰撞盒内 L2 最小值>1,
                # 精灵像素仅当 L1[世界] < 深度 时绘制, 否则被前景景物遮挡
                depth = entity_occlusion_depth(
                    self._vis_layer2_img, self._vis_layer_w, self._vis_layer_h,
                    r[IDX_BOUND_X], r[IDX_BOUND_Y], r[IDX_BOUND_W], r[IDX_BOUND_H])
                if depth > 1:
                    composite_occluded(composite, sprite_rgba, sx, sy, depth,
                                       self._vis_layer1_img,
                                       self._vis_layer_w, self._vis_layer_h)
                else:
                    _pil_normal(composite, sprite_rgba, sx, sy)
            else:
                _pil_normal(composite, sprite_rgba, sx, sy)
            drawn.add(idx)

        # ============================================================
        # Pass 2: 编辑标注 (碰撞盒/路径线/标签) — 绘制在精灵之上
        # ============================================================
        dr = ImageDraw.Draw(composite)
        for r in ents:
            tval = r[IDX_TYPE]
            show = self._editor._type_filter_cbs.get(tval)
            if show and not show.isChecked():
                continue
            idx = r['index']
            color = TYPE_COLORS_RGBA.get(tval, (128, 128, 128))

            # 精灵实体的碰撞/交互盒 (细线, 编辑标注)
            if idx in had_jvg:
                bx, by = r[IDX_BOUND_X], r[IDX_BOUND_Y]
                bw = r[IDX_BOUND_W] if r[IDX_BOUND_W] > 0 else 0
                bh = r[IDX_BOUND_H] if r[IDX_BOUND_H] > 0 else 0
                if bw > 0 and bh > 0:
                    dr.rectangle([bx, by, bx + bw, by + bh], outline=color, width=1)
            # 无精灵实体: 几何形状 (粗线) + 命中区, 始终显示以便选择
            if idx not in drawn:
                bx, by = r[IDX_BOUND_X], r[IDX_BOUND_Y]
                bw = r[IDX_BOUND_W] if r[IDX_BOUND_W] > 0 else 40
                bh = r[IDX_BOUND_H] if r[IDX_BOUND_H] > 0 else 40
                dr.rectangle([bx, by, bx + bw, by + bh], outline=color, width=2)
                self._vis_hit_regions[idx] = (bx, by, bx + bw, by + bh)

            # Label
            label = f"#{idx}"
            if tval == 10:
                d62 = r.get("d62", 0)
                label = f"T{idx}[锁]" if d62 > 0 else f"T{idx}"
            elif tval == 15: label = f"E{idx}"
            elif tval == 16: label = f"B{idx}"
            elif tval == 20: label = f"V{idx}"
            elif tval == 110: label = f"M{idx}"
            elif tval == 200: label = f"N{idx}"
            elif tval == 5: label = f"P{idx}"
            cur_a = r.get('d33', 0)
            cur_b = r.get('d34', 0)
            script_icon = ""
            if cur_a > 0: script_icon += "⚡"
            if cur_b > 0: script_icon += "👆"
            if script_icon: label = f"{label} {script_icon}"
            bx_c = r[IDX_BOUND_X] + r[IDX_BOUND_W] // 2
            dr.text((bx_c - len(label) * 3, r[IDX_BOUND_Y] - 12), label, fill=color)

            # type=10 路径/封锁线 (绿=开放路径 红=封锁, SetBlock 运行时碰撞标注)
            if tval == 10:
                d62 = r.get("d62", 0)
                lc = (255, 80, 80) if d62 > 0 else (80, 255, 80)
                segs = [
                    (r.get("d63", 0), r.get("d64", 0), r.get("d65", 0), r.get("d66", 0), r.get("d67", 0)),
                    (r.get("d68", 0), r.get("d69", 0), r.get("d70", 0), r.get("d71", 0), r.get("d72", 0)),
                    (r.get("d73", 0), r.get("d74", 0), r.get("d75", 0), r.get("d76", 0), r.get("d77", 0)),
                    (r.get("d78", 0), r.get("d79", 0), r.get("d80", 0), r.get("d81", 0), r.get("d82", 0)),
                    (r.get("d83", 0), r.get("d84", 0), r.get("d85", 0), r.get("d86", 0), r.get("d87", 0)),
                ]
                for en, x1, y1, x2, y2 in segs:
                    if en and x1 > 0 and y1 > 0 and x2 > 0 and y2 > 0:
                        dr.line([x1, y1, x2, y2], fill=lc, width=2)

        # Selected entity highlight
        if self._vis_selected is not None and self._vis_selected in self._vis_hit_regions:
            x1, y1, x2, y2 = self._vis_hit_regions[self._vis_selected]
            dr.rectangle([x1 - 2, y1 - 2, x2 + 2, y2 + 2], outline=(255, 215, 0), width=2)

        # Convert to QPixmap and display
        pixmap = _pil_to_qpixmap(composite)
        self._vis_bg_pixmap = pixmap
        self._vis_bg_item = self._vis_gscene.addPixmap(pixmap)
        self._vis_gscene.setSceneRect(0, 0, composite.width, composite.height)

    def _vis_redraw(self):
        sid = self._vis_scene_id
        self._vis_gscene.clear()
        self._vis_hit_regions = {}
        self._vis_bg_item = None
        if not self._data.records:
            return

        # 获取当前预览窗口视口的实际像素大小
        view_w = self.viewport().width()
        view_h = self.viewport().height()

        ents = [r for r in self._data.records if has_data(r) and r['d1'] == sid]
        bg_w = self._vis_bg_pil.width if self._vis_bg_pil else 0
        bg_h = self._vis_bg_pil.height if self._vis_bg_pil else 0
        if not ents:
            # 空场景: 如果有背景图也要渲染
            w = min(max(view_w, MAX_MAP_W, bg_w), 8192)
            h = min(max(view_h, MAX_MAP_H, bg_h), 8192)
            self._vis_render_scene(ents, w, h)
            return
        ents.sort(key=self._vis_sort_key)
        # 过滤垃圾废弃坐标 (>10000)，防止画布被撑到 8192 导致显卡卡死
        xs = [r['d10'] for r in ents if -10000 < r['d10'] < 10000]
        ys = [r['d11'] for r in ents if -10000 < r['d11'] < 10000]
        if not xs: xs = [0]
        if not ys: ys = [0]
        right = max(r['d18'] + r['d20'] for r in ents if r['d20'] > 0 and -10000 < r['d18'] < 10000) if any(r['d20'] > 0 and -10000 < r['d18'] < 10000 for r in ents) else max(xs)
        bottom = max(r['d19'] + r['d21'] for r in ents if r['d21'] > 0 and -10000 < r['d19'] < 10000) if any(r['d21'] > 0 and -10000 < r['d19'] < 10000 for r in ents) else max(ys)
        w = min(max(view_w, MAX_MAP_W, max(max(xs), right) + 300, bg_w), 8192)
        h = min(max(view_h, MAX_MAP_H, max(max(ys), bottom) + 300, bg_h), 8192)
        self._vis_render_scene(ents, w, h)

    # =========== 画布交互 ===========
    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)
        cx, cy = int(scene_pos.x()), int(scene_pos.y())
        self._vis_selected = None
        self._vis_drag = None
        self._drag_undo_snapshot = None
        found = None
        for idx, (x1, y1, x2, y2) in self._vis_hit_regions.items():
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                found = idx
        if found is not None:
            if self._vis_sel_anim_active and self._vis_selected != found:
                self._vis_stop_sel_anim()
            self._vis_selected = found
            rec = self._data.records[found]
            tname = ENTITY_TYPES.get(rec[IDX_TYPE], '?')
            pos_x, pos_y = rec[IDX_POS_X], rec[IDX_POS_Y]
            if self._vis_edit_mode:
                # 记录拖动前完整快照, 供 mouseReleaseEvent 判定确有位移后压入撤销栈 (§需求3)
                self._drag_undo_snapshot = (found, dict(rec))
                self._editor._vis_info_label.setText(f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖拽可移动")
                self._vis_drag = (found, cx, cy, pos_x, pos_y)
            else:
                self._editor._vis_info_label.setText(f"选中: #{found} [{tname}] 坐标({pos_x},{pos_y}) — 拖动已锁定")
            self._editor._sync_entity_list_select(found)
            self._editor._current_param_idx = found
            self._editor._show_record(rec)
        else:
            self._editor._vis_info_label.setText("")
        self._vis_redraw()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)
        self._editor._vis_coord_label.setText(f"坐标: ({int(scene_pos.x())}, {int(scene_pos.y())})")
        # Drag handling (仅左键按下时拖动, 对应原版 <B1-Motion> 行为)
        if self._vis_drag is None or not self._vis_edit_mode:
            return
        if not (event.buttons() & Qt.LeftButton):
            self._vis_drag = None
            return
        eidx, sx, sy, ox, oy = self._vis_drag
        cx, cy = int(scene_pos.x()), int(scene_pos.y())
        dx, dy = cx - sx, cy - sy
        new_x, new_y = ox + dx, oy + dy
        rec = self._data.records[eidx]
        old_d10, old_d11 = rec[IDX_POS_X], rec[IDX_POS_Y]
        rec[IDX_POS_X], rec[IDX_POS_Y] = new_x, new_y
        rec[IDX_BOUND_X] += new_x - old_d10
        rec[IDX_BOUND_Y] += new_y - old_d11
        self._data._dirty = True
        self._editor._vis_info_label.setText(f"移动: #{eidx} → ({new_x},{new_y})")
        self._vis_redraw()

    def mouseReleaseEvent(self, event):
        if self._vis_drag:
            eidx = self._vis_drag[0]
            rec = self._data.records[eidx]
            # 拖动结束: 若坐标较拖动前确有变化, 将拖动前快照压入撤销栈 (§需求3)
            if self._drag_undo_snapshot is not None:
                snap_idx, snap_rec = self._drag_undo_snapshot
                if snap_idx == eidx and (snap_rec.get('d10') != rec['d10']
                                         or snap_rec.get('d11') != rec['d11']):
                    self._append_undo(f"移动 #{eidx}", [(eidx, snap_rec)])
                self._drag_undo_snapshot = None
            pos = event.position().toPoint()
            scene_pos = self.mapToScene(pos)
            cx, cy = int(scene_pos.x()), int(scene_pos.y())
            px, py = rec[IDX_POS_X], rec[IDX_POS_Y]
            self._vis_drag = (eidx, cx, cy, px, py)
            # 拖动结束后同步刷新参数面板 (坐标X/Y、碰撞X/Y): _current_param_idx 存在于
            # editor 上, 此处须检查 self._editor 而非视图 self, 否则条件恒为 False 面板不更新
            if hasattr(self._editor, '_current_param_idx') and self._editor._current_param_idx == eidx:
                self._editor._show_record(rec)

    def contextMenuEvent(self, event):
        """预览区右键菜单: 命中实体时提供 复制/删除 (§需求2); 空白处提供 在此新增实体,
        落点为鼠标所在场景坐标 (§右键新增)。命中判定用 viewport→scene 坐标, 兼容各平台事件顺序。"""
        vp_pos = self.viewport().mapFromGlobal(event.globalPos())
        scene_pos = self.mapToScene(vp_pos)
        cx, cy = int(scene_pos.x()), int(scene_pos.y())
        found = None
        for idx, (x1, y1, x2, y2) in self._vis_hit_regions.items():
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                found = idx
        if found is None:
            # 空白处右键: 在鼠标所在坐标处新增实体 (§右键新增)
            if not self._data.records:
                return
            nx, ny = max(0, cx), max(0, cy)
            menu = QMenu(self)
            act_new = menu.addAction(f"➕ 在此新增实体 ({nx},{ny})")
            chosen = menu.exec(event.globalPos())
            if chosen == act_new:
                self._editor._new_record(pos=(nx, ny))
            return
        # 右键即选中该实体, 与左键点击保持一致的选中反馈
        if self._vis_selected != found:
            self._vis_selected = found
            self._editor._sync_entity_list_select(found)
            self._editor._current_param_idx = found
            self._editor._show_record(self._data.records[found])
            self._vis_redraw()
        menu = QMenu(self)
        act_copy = menu.addAction("📋 复制实体 (到旁边)")
        act_del = menu.addAction("🗑️ 删除实体")
        chosen = menu.exec(event.globalPos())
        if chosen == act_copy:
            self._editor._duplicate_entity(found, offset=True)
        elif chosen == act_del:
            self._editor._delete_entity(found, confirm=False)

    def _append_undo(self, description, snap_list):
        """将现成快照列表压入撤销栈 (拖动路径已在按下时抓取快照, 直接沿用)。"""
        self._undo_stack.append((description, snap_list))
        if len(self._undo_stack) > self._undo_limit:
            self._undo_stack.pop(0)

    def _push_undo(self, description, indices):
        """抓取 indices 当前记录的完整快照并压栈 (新增/复制/删除在改数据前调用)。"""
        snap = [(i, dict(self._data.records[i])) for i in indices]
        self._append_undo(description, snap)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ShiftModifier:
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta)
        else:
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta)

    # =========== 动画控制 ===========
    def _vis_toggle_anim(self):
        if self._vis_anim_playing:
            self._vis_stop_anim()
            self._vis_anim_playing = False
            self._editor._vis_play_btn.setText("▶️ 播放全部")
        else:
            self._vis_anim_playing = True
            self._vis_start_anim()
            self._editor._vis_play_btn.setText("⏸️ 暂停全部")

    def _vis_start_anim(self):
        if self._vis_anim_timer:
            return
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            return
        timer = QTimer(self)
        timer.timeout.connect(self._vis_anim_tick)
        timer.start(200)
        self._vis_anim_timer = timer

    def _vis_anim_tick(self):
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            self._vis_stop_anim()
            return
        for idx in list(self._vis_anim_frame.keys()):
            self._vis_anim_frame[idx] += 1
        self._vis_redraw()

    def _vis_stop_anim(self):
        if self._vis_anim_timer:
            self._vis_anim_timer.stop()
            self._vis_anim_timer = None

    def _vis_toggle_sel_anim(self):
        if self._vis_selected is None:
            self._editor._vis_info_label.setText("请先选中一个实体再播放动画")
            return
        if self._vis_anim_playing:
            self._editor._vis_info_label.setText("全局动画已开启，无需单独播放")
            return
        idx = self._vis_selected
        rec = self._data.records[idx]
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        tval = rec[IDX_TYPE]
        can_animate = False
        if mode in ('auto', 'ani'):
            if tval in (200, 20, 110) and rec[IDX_SUB_MODEL] > 0 and self._editor._ani_jvg:
                can_animate = True
        if not can_animate:
            tname = ENTITY_TYPES.get(tval, '?')
            self._editor._vis_info_label.setText(f"实体 #{idx} [{tname}] 不支持动画")
            return
        if self._vis_sel_anim_active:
            self._vis_stop_sel_anim()
        else:
            self._vis_start_sel_anim(idx)

    def _vis_start_sel_anim(self, idx):
        self._vis_sel_anim_active = True
        self._editor._vis_sel_anim_btn.setText("⏸️ 播放选中")
        self._vis_anim_frame[idx] = 0
        timer = QTimer(self)
        timer.timeout.connect(lambda: self._vis_sel_anim_tick(idx))
        timer.start(200)
        self._vis_sel_anim_timer = timer

    def _vis_sel_anim_tick(self, idx):
        if not self._vis_sel_anim_active:
            return
        mode = DISPLAY_MODES.get(self._vis_display_mode, 'auto')
        if mode in ('wire', 'cha'):
            self._vis_stop_sel_anim()
            return
        if idx in self._vis_anim_frame:
            self._vis_anim_frame[idx] += 1
        self._vis_redraw()

    def _vis_stop_sel_anim(self):
        self._vis_sel_anim_active = False
        if self._vis_sel_anim_timer:
            self._vis_sel_anim_timer.stop()
            self._vis_sel_anim_timer = None
        self._editor._vis_sel_anim_btn.setText("⏯️ 播放选中")

    def _on_display_mode_change(self):
        self._vis_stop_anim()
        self._vis_stop_sel_anim()
        self._vis_anim_playing = False
        self._editor._vis_play_btn.setText("▶️ 播放全部")
        self._vis_display_mode = self._editor._display_mode_combo.currentText()
        self._editor._vis_load_scene()

    def _on_edit_mode_change(self):
        self._vis_edit_mode = self._editor._vis_edit_cb.isChecked()
        if self._vis_edit_mode:
            self._editor._vis_info_label.setText("编辑模式已开启 — 可拖动实体")
        else:
            self._vis_drag = None
            self._editor._vis_info_label.setText("编辑模式已锁定 — 拖动已禁用")

    def _vis_canvas_undo(self):
        """撤销上一步操作 (Ctrl+Z / 工具栏按钮 / 编辑菜单) (§需求3)。
        从撤销栈弹出一项, 用快照整体恢复受影响记录, 覆盖 拖动/新增/复制/删除。"""
        if not self._undo_stack:
            self._editor._vis_info_label.setText("没有可撤销的操作")
            return
        description, snap = self._undo_stack.pop()
        cur = self._editor._current_param_idx
        touch_cur = False
        for i, snapshot in snap:
            rec = self._data.records[i]
            rec.clear()
            rec.update(snapshot)
            if i == cur:
                touch_cur = True
        self._data._dirty = True
        # 恢复的实体可能已不属于当前场景 (如撤销"新增到他场景"), 刷新列表与画布即可
        self._editor._apply_filter()
        self._editor._refresh_scene_counts()
        self._vis_redraw()
        if touch_cur and cur is not None:
            self._editor._show_record(self._data.records[cur])
        self._editor._vis_info_label.setText(f"已撤销: {description}")


class InspectorPanelBuilder:
    """属性面板构建工厂 (§4 进阶②) — 从 MatEditorApp 拆出的视图构建职责。
    持有 editor 各字典的快捷引用 (同对象), 构建的 widget 直接落入 editor 字典,
    使消费方 (_update_inspector/_sync_to_raw 等) 无需改动。"""

    def __init__(self, editor):
        self._editor = editor
        # 快捷引用 (与进阶③ self._data 同模式) — 字典为可变对象, 写入直接回传 editor
        self._edit_vars = editor._edit_vars
        self._raw_mirrors = editor._raw_mirrors
        self._type_vars = editor._type_vars
        self._type_frames = editor._type_frames

    def build_type_param_pages(self):
        """为每种实体类型构建独立的参数编辑页"""
        _TYPE_ORDER = [200, 10, 20, 110, 15, 16, 5]
        for tval in _TYPE_ORDER:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(4, 4, 16, 4)
            inner_layout.setSpacing(6)

            tvars = {}
            skip = TYPE_SKIP_DWORDS.get(tval, set())
            type_labels = _TYPE_LABELS.get(tval, {})

            # === 基础属性 ===
            self._build_type_basic_group(inner_layout, tvars, tval, type_labels)

            # === 显示/动画/位置 [8-28] ===
            GROUP_8_28 = []
            _seen8 = set()
            _skip_8_28 = {12, 17, 25, 26, 27}
            for fields in (BASIC_FIELDS, RUNTIME_FIELDS, POS_FIELDS, INTERACT_FIELDS, SCRIPT_FIELDS):
                for f in fields:
                    if 8 <= f[1] <= 28 and f[1] not in _seen8 and f[1] not in _skip_8_28:
                        GROUP_8_28.append(f)
                        _seen8.add(f[1])
            _order_8_28 = {13: 21.5, 15: 21.6}
            GROUP_8_28.sort(key=lambda f: _order_8_28.get(f[1], f[1]))
            GROUP_8_28 = [f for f in GROUP_8_28 if f[1] not in skip]
            if GROUP_8_28:
                self._build_field_group(inner_layout, "显示/动画/位置 [8-28]", GROUP_8_28, tvars, type_labels, 4, tval=tval)

            # === 交互/动画/物品 [50-70] ===
            GROUP_50_70 = []
            _seen50 = set()
            for fields in (INTERACT_FIELDS, RUNTIME_FIELDS, ANIM_FIELDS, ITEM_FIELDS):
                for f in fields:
                    if 50 <= f[1] <= 70 and f[1] not in _seen50:
                        GROUP_50_70.append(f)
                        _seen50.add(f[1])
            GROUP_50_70.sort(key=lambda f: f[1])
            GROUP_50_70 = [f for f in GROUP_50_70 if f[1] not in skip]
            if GROUP_50_70:
                self._build_field_group(inner_layout, "交互/动画/物品 [50-70]", GROUP_50_70, tvars, type_labels, 4, tval=tval)

            # === 音效事件 [71-95] (type=20 专用) ===
            if tval == 20 and type_labels:
                sound_events = [(di, type_labels[di][0], type_labels[di][1])
                               for di in range(71, 96) if di in type_labels and di not in skip]
                if sound_events:
                    snd_fields = [(f'snd_{di}', di, tl, tc) for di, tl, tc in sound_events]
                    self._build_field_group(inner_layout, "音效事件 [71-95]", snd_fields, tvars, type_labels, 4, tval=tval, is_sound=True)

            inner_layout.addStretch()
            scroll.setWidget(inner)
            self._type_frames[tval] = scroll
            self._type_vars[tval] = tvars

    def make_raw_edit(self, di):
        """为 dword di 创建一个独立的 QLineEdit 并登记到镜像表。
        v2 不再共享同一 QLineEdit 控件 (一个 QWidget 只能有一个父窗口, 会被
        后续 addWidget re-parent 走, 导致其余页变空壳); 改为每页各建一个,
        构建完成后用 _wire_raw_mirrors 双向同步, 等价于 v1 的 StringVar 互通。"""
        ev = QLineEdit()
        self._raw_mirrors.setdefault(di, []).append(ev)
        return ev

    def wire_raw_mirrors(self):
        """为每个 dword 的所有镜像 QLineEdit 接入 textChanged 双向同步。
        用 blockSignals 防回环。构建后过滤已被 Qt 回收的对象。"""
        for di in list(self._raw_mirrors):
            eds = self._raw_mirrors[di]
            # 过滤已被 Qt 回收的孤儿对象 (addWidget re-parent 后未保持强引用)
            alive = []
            for ed in eds:
                try:
                    _ = ed.text()
                    alive.append(ed)
                except RuntimeError:
                    pass
            self._raw_mirrors[di] = alive
            if len(alive) < 2:
                continue
            # 为每个控件分别创建 handler, 用 partial 预填 src 避免闭包捕获
            for src_ed in alive:
                src_ed.textChanged.connect(partial(self._on_mirror_changed, src_ed, alive))

    def _build_type_basic_group(self, parent_layout, tvars, tval, type_labels):
        """构建类型页面的基础属性组 (DockHeader + DockBody, 垂直单元格, 等宽列)"""
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader("基础属性"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 8, 8, 8)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)

        def _cell(lbl_widget, input_widget):
            """返回 (QWidget, QVBoxLayout) — QWidget 作为 grid 单元格, 保证内部控件有父"""
            cw = QWidget()
            cell = QVBoxLayout(cw)
            cell.setSpacing(2)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.addWidget(lbl_widget)
            input_widget.setMinimumHeight(24)
            cell.addWidget(input_widget)
            return cw

        # Type combobox
        lbl = QLabel("[00] 实体类型")
        lbl.setToolTip("[00] 实体类型: 5=脚本 10=出入传送 15=触发区 16=战斗区 20=事件 110=机关 200=NPC。源码: sub_405CBC")
        lbl.setProperty("class", "PropLabel")
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(_FIELD_LABEL_MAX_WIDTH)
        cb = EditorComboBox()
        cb.addItems([f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items())])
        cb.setMaximumWidth(_TYPE_COMBO_MAX_WIDTH)
        tvars['type'] = cb
        wrapper = QFrame()
        wrapper.setObjectName("FakeInputBox")
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(cb)
        grid.addWidget(_cell(lbl, wrapper), 0, 0, Qt.AlignTop)

        # Scene ID
        lbl2 = QLabel("[01] 场景ID")
        lbl2.setToolTip("[01] 所属场景 (-1=全局)。TKT_ID = scene_id + 300。源码: sub_405CBC")
        lbl2.setProperty("class", "PropLabel")
        lbl2.setWordWrap(True)
        lbl2.setMaximumWidth(_FIELD_LABEL_MAX_WIDTH)
        ev = self.make_raw_edit(1)
        tvars['scene_id'] = ev
        wrapper2 = QFrame()
        wrapper2.setObjectName("FakeInputBox")
        wl2 = QHBoxLayout(wrapper2)
        wl2.setContentsMargins(0, 0, 0, 0)
        wl2.addWidget(ev)
        scene_lbl = QLabel("")
        scene_lbl.setProperty("class", "ExtraPreviewText")
        wl2.addWidget(scene_lbl)
        tvars['_scene_label'] = scene_lbl
        grid.addWidget(_cell(lbl2, wrapper2), 0, 1, Qt.AlignTop)

        # Flags
        lbl3 = QLabel("[02] 标志位")
        lbl3.setToolTip("[02] 位域。bit0=启用 bit1=可见 bit2=可交互 bit3=提示 bit4=忙碌 bit5=恢复 bit8=已拾取 bit16=动画循环")
        lbl3.setProperty("class", "PropLabel")
        lbl3.setWordWrap(True)
        lbl3.setMaximumWidth(_FIELD_LABEL_MAX_WIDTH)
        ev2 = self.make_raw_edit(2)
        tvars['flags'] = ev2
        wrapper3 = QFrame()
        wrapper3.setObjectName("FakeInputBox")
        wl3 = QHBoxLayout(wrapper3)
        wl3.setContentsMargins(0, 0, 0, 0)
        wl3.addWidget(ev2)
        grid.addWidget(_cell(lbl3, wrapper3), 0, 2, Qt.AlignTop)

        # Flag checkboxes
        bit_attrs = [
            ("_bit_enable", "启用", 1), ("_bit_visible", "显示", 2),
            ("_bit_pickable", "可交互", 4), ("_bit_hint", "提示", 8),
            ("_bit_busy", "忙碌", 0x10), ("_bit_resume", "恢复", 0x20),
            ("_bit_taken", "已拾取", 0x100), ("_bit_animloop", "循环动画", 0x10000),
            ("_bit_ev12", "事件标志A", 0x1000), ("_bit_ev13", "事件标志B", 0x2000),
            ("_bit_ev14", "事件标志C", 0x4000),
        ]
        bit_vars = {}
        bit_cbs = []
        flags_frame = QWidget()
        flags_grid = QGridLayout(flags_frame)
        flags_grid.setContentsMargins(0, 0, 0, 0)
        flags_grid.setSpacing(2)
        for bi, (attr, text, mask) in enumerate(bit_attrs):
            cb_bit = QCheckBox(text)
            cb_bit.setToolTip(f"{attr}: mask=0x{mask:X}")
            bit_vars[attr] = cb_bit
            bit_cbs.append(cb_bit)
            r, c = divmod(bi, 4)
            flags_grid.addWidget(cb_bit, r, c)

        tvars['_bit_vars'] = bit_vars
        tvars['_bit_cbs'] = bit_cbs
        tvars['_bit_event_idxs'] = [i for i, (attr, _, _) in enumerate(bit_attrs)
                                     if attr in ('_bit_ev12', '_bit_ev13', '_bit_ev14')]

        # Wire up flag<->entry sync
        def _on_flags_changed(*_args):
            try:
                flags = int(ev2.text() or 0)
            except ValueError:
                return
            for attr, _text, mask in bit_attrs:
                bit_vars[attr].setChecked((flags & mask) != 0)

        def _on_cb_changed(*_args):
            flags = 0
            for attr, _text, mask in bit_attrs:
                if bit_vars[attr].isChecked():
                    flags |= mask
            ev2.setText(str(flags))

        ev2.textChanged.connect(_on_flags_changed)
        for bv in bit_vars.values():
            bv.stateChanged.connect(_on_cb_changed)

        grid.addWidget(flags_frame, 1, 0, 1, 3)

        for c in range(3):
            grid.setColumnStretch(c, 1)
        bl.addLayout(grid)
        gl.addWidget(body)
        parent_layout.addWidget(grp)

    def _build_field_group(self, parent_layout, title, fields, tvars, type_labels, cols, tval=0, is_sound=False):
        """构建通用字段组 (DockHeader + DockBody, 垂直单元格, 等宽列)"""
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(title))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 8, 8, 8)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)

        for fi, field_tuple in enumerate(fields):
            key, di, label, cmt = field_tuple
            r, c = divmod(fi, cols)

            # Label with type-specific override
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl_text = f"[{di:02d}] {tl}"
                tip = f"[{di:02d}] {tl}: {tc}" if tc else None
            else:
                lbl_text = f"[{di:02d}] {label}"
                tip = f"[{di:02d}] {cmt}" if cmt else None

            lbl = QLabel(lbl_text)
            if tip:
                lbl.setToolTip(tip)
            lbl.setProperty("class", "PropLabel")
            lbl.setWordWrap(True)
            lbl.setMaximumWidth(_FIELD_LABEL_MAX_WIDTH)
            if di in type_labels:
                lbl.setProperty("class", "TypeFieldLabel")

            # Input widget (组合框字段不创建 QLineEdit 镜像, 由"全部"页 raw_N 充当存储,
            # 经 _sync_type_cb_to_raw 单向同步; 文本类字段各自建镜像并双向同步)
            ev = None

            # Check if this needs a combobox
            if key == 'anim_set':
                cb = EditorComboBox()
                cb.addItems([
                    "0-无动画",
                    "1-Cha(角色)",
                    "4-Ani(动画)",
                    "5-Cur(光标)",
                ])
                cb.setMaximumWidth(_COMBO_MAX_WIDTH)
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                # Sync combobox to raw entry
                cb.currentIndexChanged.connect(partial(self._sync_type_cb_to_raw, tvars, di, cb))
            elif key == 'blend_mode':
                cb = EditorComboBox()
                cb.addItems(["0-正常", "1-染色", "2-加法发光", "3-减法压暗", "4-亮度alpha", "5-水平翻转"])
                cb.setMaximumWidth(_COMBO_MAX_WIDTH)
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(partial(self._sync_type_cb_to_raw, tvars, di, cb))
            elif key == 'shadow_frame':
                cb = EditorComboBox()
                cb.addItems(["0-无阴影", "1-小阴影(39×23)", "2-大阴影(65×33)"])
                cb.setMaximumWidth(_COMBO_MAX_WIDTH)
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(partial(self._sync_type_cb_to_raw, tvars, di, cb))
            elif key == 'cursor_id':
                cb = EditorComboBox()
                cb.addItems([f"{k}-{v}" for k, v in sorted(_CURSOR_BLOCKS.items())])
                cb.setMaximumWidth(_COMBO_MAX_WIDTH)
                tvars[key] = cb
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(cb)
                cb.currentIndexChanged.connect(partial(self._sync_type_cb_to_raw, tvars, di, cb))
            elif key == 'dialog_color':
                # 对话颜色选择器: FCOLOR 1-32 调色板
                dc_ev = self.make_raw_edit(di)
                tvars[key] = dc_ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setSpacing(2)
                wl.addWidget(dc_ev, 1)
                # Color swatch
                dc_swatch = QFrame()
                dc_swatch.setFixedSize(20, 20)
                dc_swatch.setProperty("class", "ColorSwatch")
                wl.addWidget(dc_swatch)
                tvars['_dialog_color_swatch'] = dc_swatch
                # Picker button
                dc_btn = QPushButton("选色")
                dc_btn.setFixedWidth(40)
                dc_btn.setCursor(Qt.PointingHandCursor)
                dc_btn.clicked.connect(partial(self._pick_dialog_color, dc_swatch, dc_ev, dc_btn))
                wl.addWidget(dc_btn)
                tvars['_dialog_color_btn'] = dc_btn
            elif key == 'dir_mask' and tval in (10, 15):
                # 方向掩码 checkbox 网格 (8个朝向) — 垂直布局: 数值输入在上, checkbox 在下
                dm_ev = self.make_raw_edit(di)
                dm_ev.setMaximumWidth(80)
                tvars[key] = dm_ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl_wrap = QVBoxLayout(wrapper)
                wl_wrap.setContentsMargins(4, 2, 4, 2)
                wl_wrap.setSpacing(2)
                wl_wrap.addWidget(dm_ev)
                # Direction checkboxes grid: 4行×2列
                dir_frame = QWidget()
                dir_grid = QGridLayout(dir_frame)
                dir_grid.setContentsMargins(0, 0, 0, 0)
                dir_grid.setSpacing(1)
                dir_labels = ["上", "右上", "右", "右下", "下", "左下", "左", "左上"]
                dir_bv = {}
                for bit_i in range(8):
                    bv_cb = QCheckBox(dir_labels[bit_i])
                    bv_cb.setProperty("class", "DirCheckBox")
                    dir_bv[bit_i] = bv_cb
                    r2, c2 = divmod(bit_i, 2)
                    dir_grid.addWidget(bv_cb, r2, c2)
                for bv_cb in dir_bv.values():
                    bv_cb.stateChanged.connect(partial(self._sync_dir_mask, dm_ev, dir_bv))
                tvars["_dir_bv"] = dir_bv
                wl_wrap.addWidget(dir_frame)
            else:
                ev = self.make_raw_edit(di)
                tvars[key] = ev
                wrapper = QFrame()
                wrapper.setObjectName("FakeInputBox")
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.addWidget(ev)

            cell_widget = QWidget()
            cell = QVBoxLayout(cell_widget)
            cell.setSpacing(2)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.addWidget(lbl)
            cell.addWidget(wrapper)
            # Hint label — 输入框外部下方, 与输入框左边线对齐
            if key == 'hint_id':
                hl = QLabel("")
                hl.setProperty("class", "FieldHint")
                hl.setWordWrap(True)
                cell.addWidget(hl)
                tvars['_hint_label'] = hl
            # Item name label — type=110 物品ID输入框下方 (显示方式参考 hint_id)
            # 注意: d53/d57/d61 在 GROUP_50_70 中已被 ANIM/RUNTIME 的 dir_mode/saved_y/alt_tele_y
            # 抢先占用 (按 di 去重), key 不会是 item_gN_id, 故按 di 判定 (与 mat_editor.py 一致)
            if tval == 110 and di in (53, 57, 61):
                _item_lbl_key = {53: '_item_g1_id_label', 57: '_item_g2_id_label', 61: '_item_g3_id_label'}[di]
                il = QLabel("")
                il.setProperty("class", "FieldHint")
                il.setWordWrap(True)
                cell.addWidget(il)
                tvars[_item_lbl_key] = il
            wrapper.setMinimumHeight(24)
            grid.addWidget(cell_widget, r, c, Qt.AlignTop)

        # 所有列等宽
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        # 填充末行空白占位, 防止列宽不均
        if fields:
            last_row_count = len(fields) % cols
            if last_row_count != 0:
                last_row = len(fields) // cols
                for c in range(last_row_count, cols):
                    grid.addWidget(QWidget(), last_row, c)

        # grid 必须关联父 QWidget, 否则内部 widget 无父 → 被 GC 回收
        grid_widget = QWidget()
        grid_widget.setLayout(grid)
        bl.addWidget(grid_widget)
        gl.addWidget(body)
        parent_layout.addWidget(grp)

    def _sync_type_cb_to_raw(self, tvars, di, cb_widget, *_args):
        """类型页面 Combobox 值同步到 raw_N"""
        try:
            v = int(cb_widget.currentText().split('-')[0])
            rk = f'raw_{di}'
            if rk in self._edit_vars:
                self._edit_vars[rk].setText(str(v))
        except ValueError:
            pass

    # ---- partial 槽函数 (原为闭包/lambda, §3 改造抽出) ----
    def _on_mirror_changed(self, src, eds, txt=""):
        """raw 镜像同步: src 改变时把文本广播给 eds 中其它编辑框。
        (textChanged 信号会传入 txt)"""
        for ed in eds:
            if ed is src:
                continue
            if ed.text() == txt:
                continue
            ed.blockSignals(True)
            ed.setText(txt)
            ed.blockSignals(False)

    def _pick_dialog_color(self, swatch, ev, btn, *_args):
        """对话颜色选色弹窗 (clicked 信号会传入 bool, *_args 吸收)"""
        menu = QMenu(self._editor)
        for i in range(32):
            hc = GAME_COLORS.get(i + 1, '#000')
            px = QPixmap(16, 16)
            px.fill(QColor(hc))
            act = menu.addAction(QIcon(px), f"  {i:2d}  FCOLOR({i+1:2d})")
            act.setData(i)
        chosen = menu.exec(btn.mapToGlobal(QPoint(0, btn.height())))
        if chosen:
            val = chosen.data()
            ev.setText(str(val))
            swatch.setStyleSheet(f"background-color: {GAME_COLORS.get(val+1,'#000')};")

    def _sync_dir_mask(self, ev, dir_bv, *_args):
        """方向掩码 checkbox 网格同步到数值输入 (stateChanged 信号会传入 int, *_args 吸收)"""
        mask = sum((1 << i) for i, cb in dir_bv.items() if cb.isChecked())
        ev.blockSignals(True)
        ev.setText(str(mask))
        ev.blockSignals(False)


class MatEditorApp(QMainWindow):
    """TKMat.Dat 地图实体编辑器 PySide6 版"""

    def __init__(self):
        super().__init__()
        self.setObjectName("EditorWindow")
        self.setWindowTitle(format_title("mat_editor"))
        self.resize(1560, 860)
        self.setMinimumSize(1340, 640)

        # 加载图标
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        # 主题初始化：跟随持久化选择，无存档时按系统深浅色取现代主题
        apply_theme_to_window(self, theme_manager.load_initial_theme(), persist=False)

        # 数据状态 (§5 — 已迁入 MapDataManager)
        self._data = MapDataManager()

        # 可视化模式状态 (画布自有状态已迁入 SceneCanvasView)
        self._vis_show_types = {t: True for t in [5, 10, 15, 16, 20, 110, 200]}
        self._ani_jvg = None
        self._cha_jvg = None
        self._cur_jvg = None
        self._preview_win = None
        self._preview_step = 0
        self._preview_cmds = []
        self._current_param_idx = None
        self._current_edit_define_id = None
        self._script_dirty = False
        self._script_baseline = {}  # {define_id_str: 去空白正文} 脚本删除检测基线 (载入/导入/保存后刷新)
        self._edit_debounce = None

        # 画布重绘防抖定时器，避免 resizeEvent 卡死主线程
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._do_resize_redraw)

        # 字段编辑组件映射
        self._edit_vars = {}  # key -> widget (canonical, 多为"全部"页持有)
        self._raw_mirrors = {}  # di -> [QLineEdit, ...] 同一字段在参数页/全部页的镜像控件
        self._type_vars = {}  # tval -> {key: widget}
        self._type_frames = {}  # tval -> QWidget
        # 属性面板构建工厂 (§4 进阶②) — 视图构建逻辑外置
        self._inspector = InspectorPanelBuilder(self)
        self._active_type = None
        self._param_labels = {}
        self._all_labels = {}
        self._sched_labels = {}

        # 构建 UI
        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    # =========== QSS 主题 ===========
    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._apply_theme()

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        self._update_path()
        self._update_entity_type_colors()
        self._canvas.update_vis_background()
        # 主题切换时，强制重绘 PIL 底图以匹配新背景色
        if hasattr(self, '_data') and self._data.records:
            self._canvas._vis_redraw()
        # 同步脚本编辑器语法高亮配色至当前主题
        if hasattr(self, '_script_highlighter') and self._script_highlighter:
            # set_dark() 内部会 rehighlight() 触发 textChanged, 同样需屏蔽信号避免误标脏 (§修复)
            self.script_text.blockSignals(True)
            self._script_highlighter.set_dark(self._is_dark)
            self.script_text.blockSignals(False)
        # 同步行预览面板配色至当前主题 (行预览仅在加载 DEFINE 时渲染一次,
        # 切换主题后须重渲染, 否则保留旧主题配色 — 旧浅色 #333 落在深色背景上呈暗灰)
        if hasattr(self, 'script_preview') and self._current_edit_define_id is not None:
            self._update_line_preview()
        self._refresh_table()

    def _update_entity_type_colors(self):
        """根据当前主题更新实体列表的类型颜色"""
        if self._is_dark:
            # 深色背景: 使用明亮色彩
            colors = {0: "#AAAAAA", 5: "#2196F3", 10: "#4CAF50", 15: "#FF9800",
                      16: "#795548", 20: "#9C27B0", 110: "#E91E63", 200: "#F44336"}
        else:
            # 白色背景: 使用深色彩以保证可读性
            colors = {0: "#777777", 5: "#1565C0", 10: "#2E7D32", 15: "#E65100",
                      16: "#5D4037", 20: "#6A1B9A", 110: "#AD1457", 200: "#C62828"}
        self._entity_type_colors = {tv: QColor(cl) for tv, cl in colors.items()}

    # =========== UI 构建 ===========
    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_dir)
        fm.addAction("加载存档 (从游戏目录)…", QKeySequence("Ctrl+Shift+O"), self._load_save_dir)
        fm.addAction("重载", self._reload)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("另存为…", self._save_as)
        fm.addSeparator()
        fm.addAction("导出场景…", self._export_scene)
        fm.addAction("导出场景为 MOD (.tksmod)…", self._export_scene_as_tksmod)
        fm.addAction("导入场景…", self._import_scene)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("撤销", QKeySequence("Ctrl+Z"), self._undo)
        em.addSeparator()
        em.addAction("新增记录", QKeySequence("Ctrl+N"), self._new_record)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)
        em.addSeparator()
        em.addAction("删除当前场景…", self._delete_scene)

        vm = menu_bar.addMenu("查看(V)")
        vm.addAction("统计信息", self._show_stats)
        vm.addMenu(create_theme_menu(self))

        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("字段说明", self._show_field_ref)
        hm.addAction("关于编辑器", self._show_about)

        # --- Main Splitter (三栏) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        main_layout.addWidget(self.splitter, 1)

        # Left pane
        self._build_left_panel()
        # Center pane
        self._build_center_panel()
        # Right pane
        self._build_right_panel()

        self.splitter.setSizes([460, 640, 550])
        # 左右面板拉伸因子=0, 中间=1: 窗口放大时多余空间全归中间, 左右保持初始宽度
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        # Bottom path bar
        path_layout = QHBoxLayout()
        self.lbl_path = QLabel("(未加载)")
        self.lbl_cha = QLabel("Cha")
        self.lbl_ani = QLabel("Ani")
        self.lbl_cur = QLabel("Cur")
        self.lbl_sc = QLabel("SC")
        path_layout.addWidget(self.lbl_path)
        path_layout.addSpacing(20)
        for lbl in [self.lbl_cha, self.lbl_ani, self.lbl_cur, self.lbl_sc]:
            path_layout.addWidget(lbl)
            path_layout.addSpacing(10)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

        # Status bar
        self._vis_info_label = QLabel("")
        self._vis_coord_label = QLabel("")
        sb = QStatusBar()
        sb.addWidget(self._vis_info_label, 1)
        sb.addPermanentWidget(self._vis_coord_label)
        self.setStatusBar(sb)

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    # =========== 左侧面板: 场景列表 + 实体列表 ===========
    def _build_left_panel(self):
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Splitter for scene list / entity list
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(6)

        # Scene list
        self.scene_tree = QTreeWidget()
        self.scene_tree.setHeaderLabels(["SC#", "场景名称", "实体"])
        self.scene_tree.setColumnWidth(0, 50)
        self.scene_tree.setColumnWidth(2, 45)
        self.scene_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)  # 场景名称列自动拉伸
        self.scene_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scene_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scene_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scene_tree.setRootIsDecorated(False)
        self.scene_tree.setUniformRowHeights(True)
        self.scene_tree.setProperty("class", "CompactTree")
        self.scene_tree.itemSelectionChanged.connect(self._on_vis_scene_select)
        left_splitter.addWidget(self._create_dock("场景列表 (SC.GRP)", self.scene_tree))

        # Entity list: 按钮在 body 内, 不在 DockHeader
        self.entity_tree = QTreeWidget()
        self.entity_tree.setHeaderLabels(["索引", "类型", "场景", "X", "Y", "脚本", "Tick"])
        self.entity_tree.setColumnWidth(0, 44)   # 索引
        self.entity_tree.setColumnWidth(1, 80)   # 类型
        self.entity_tree.setColumnWidth(3, 40)   # X
        self.entity_tree.setColumnWidth(4, 40)   # Y
        self.entity_tree.setColumnWidth(5, 62)   # 脚本
        self.entity_tree.setColumnWidth(6, 36)   # Tick
        self.entity_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)  # 场景列自动拉伸
        self.entity_tree.header().setMinimumSectionSize(18)
        self.entity_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.entity_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.entity_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entity_tree.setRootIsDecorated(False)
        self.entity_tree.setSortingEnabled(False)
        self.entity_tree.setUniformRowHeights(True)
        self.entity_tree.setProperty("class", "CompactTree")
        self.entity_tree.itemSelectionChanged.connect(self._on_select)
        # 点击列头排序
        self.entity_tree.header().setSortIndicatorShown(True)
        self.entity_tree.header().sectionClicked.connect(self._sort_entity_by_column)
        # 表格实体类型颜色 (根据主题切换)
        self._update_entity_type_colors()

        # 实体列表面板
        ent_panel = QWidget()
        ent_panel_layout = QVBoxLayout(ent_panel)
        ent_panel_layout.setContentsMargins(0, 0, 0, 0)
        ent_panel_layout.setSpacing(0)
        # 标题栏 (DockHeader)
        ent_panel_layout.addWidget(DockHeader("实体列表"))
        # Body 区域
        ent_body = QWidget()
        ent_body.setObjectName("DockBody")
        ent_body_layout = QVBoxLayout(ent_body)
        ent_body_layout.setContentsMargins(8, 8, 8, 8)
        ent_body_layout.setSpacing(4)
        # 新增/删除 + 筛选工具栏 (新增/删除置于原搜索位置)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(2)
        btn_new = QPushButton("➕ 新增")
        btn_new.clicked.connect(self._new_record)
        filter_row.addWidget(btn_new)
        btn_del = QPushButton("🗑️ 删除")
        btn_del.clicked.connect(self._clear_current)
        filter_row.addWidget(btn_del)
        # 分隔线
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.VLine)
        sep0.setFrameShadow(QFrame.Sunken)
        filter_row.addWidget(sep0)
        filter_row.addWidget(QLabel("类型:"))
        self.filter_type = EditorComboBox()
        self.filter_type.addItems(["全部"] + [f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items()) if k != 0])
        self.filter_type.currentIndexChanged.connect(self._apply_filter)
        self.filter_type.setFixedWidth(120)
        filter_row.addWidget(self.filter_type)
        # 分隔线
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setFrameShadow(QFrame.Sunken)
        filter_row.addWidget(sep3)
        self.show_empty_cb = QCheckBox("空槽")
        self.show_empty_cb.stateChanged.connect(self._apply_filter)
        filter_row.addWidget(self.show_empty_cb)
        self.show_global_cb = QCheckBox("全局")
        self.show_global_cb.setToolTip("显示 d1==-1 的全局实体 (不属于任何具体场景)")
        self.show_global_cb.stateChanged.connect(self._apply_filter)
        filter_row.addWidget(self.show_global_cb)
        filter_row.addStretch()
        ent_body_layout.addLayout(filter_row)
        # 实体搜索工具栏 — 按实体ID(索引)定位实体并查看其所属场景 (§实体搜索)
        search_row = QHBoxLayout()
        search_row.setSpacing(2)
        search_row.addWidget(QLabel("🔍 搜索:"))
        self.search_id_edit = QLineEdit()
        self.search_id_edit.setPlaceholderText("输入实体ID(索引), 回车定位并显示其所属场景")
        self.search_id_edit.setClearButtonEnabled(True)
        self.search_id_edit.returnPressed.connect(self._search_entity_by_id)
        search_row.addWidget(self.search_id_edit, 1)
        btn_search = QPushButton("定位")
        btn_search.setFixedWidth(48)
        btn_search.setToolTip("按实体ID(索引)搜索: 自动切换到该实体所属场景并在列表中选中")
        btn_search.clicked.connect(self._search_entity_by_id)
        search_row.addWidget(btn_search)
        ent_body_layout.addLayout(search_row)
        # 状态栏
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.status_var.setProperty("class", "StatusHint")
        ent_body_layout.addWidget(self.status_var)
        # 实体列表
        ent_body_layout.addWidget(self.entity_tree, 1)
        ent_panel_layout.addWidget(ent_body, 1)

        left_splitter.addWidget(ent_panel)
        left_splitter.setSizes([300, 400])

        left_layout.addWidget(left_splitter)
        left_widget.setMinimumWidth(340)
        self.splitter.addWidget(left_widget)

    # =========== 中间面板: 地图预览 ===========
    def _build_center_panel(self):
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)

        # 先创建画布: 工具栏的信号槽连接需要引用 self._canvas 上的方法 (§4)
        self._canvas = SceneCanvasView(self)

        # Top toolbar row 1
        top = QHBoxLayout()
        top.addWidget(QLabel("场景:"))
        self._vis_scene_combo = EditorComboBox()
        self._vis_scene_combo.setMinimumWidth(200)
        self._vis_scene_combo.currentIndexChanged.connect(self._on_vis_combo_select)
        top.addWidget(self._vis_scene_combo)
        top.addSpacing(10)
        top.addWidget(QLabel("显示:"))
        self._display_mode_combo = EditorComboBox()
        self._display_mode_combo.addItems(list(DISPLAY_MODES.keys()))
        self._display_mode_combo.currentIndexChanged.connect(self._canvas._on_display_mode_change)
        top.addWidget(self._display_mode_combo)
        top.addSpacing(10)
        self._vis_play_btn = QPushButton("▶️ 播放全部")
        self._vis_play_btn.setFixedWidth(80)
        self._vis_play_btn.setProperty("class", "CompactBtn")
        self._vis_play_btn.setToolTip("播放/暂停精灵动画")
        self._vis_play_btn.clicked.connect(self._canvas._vis_toggle_anim)
        top.addWidget(self._vis_play_btn)
        self._vis_sel_anim_btn = QPushButton("⏯️ 播放选中")
        self._vis_sel_anim_btn.setFixedWidth(80)
        self._vis_sel_anim_btn.setProperty("class", "CompactBtn")
        self._vis_sel_anim_btn.setToolTip("播放/暂停当前选中实体的动画")
        self._vis_sel_anim_btn.clicked.connect(self._canvas._vis_toggle_sel_anim)
        top.addWidget(self._vis_sel_anim_btn)
        top.addSpacing(10)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setFixedWidth(60)
        btn_refresh.setProperty("class", "CompactBtn")
        btn_refresh.clicked.connect(self._vis_load_scene)
        top.addWidget(btn_refresh)
        top.addSpacing(10)
        self._vis_edit_cb = QCheckBox("允许拖动")
        self._vis_edit_cb.stateChanged.connect(self._canvas._on_edit_mode_change)
        top.addWidget(self._vis_edit_cb)
        btn_undo = QPushButton("↩️ 撤销")
        btn_undo.setFixedWidth(72)
        btn_undo.setProperty("class", "CompactBtn")
        btn_undo.setToolTip("撤销上一步操作 (Ctrl+Z): 移动 / 新增 / 复制 / 删除")
        btn_undo.clicked.connect(self._undo)
        top.addWidget(btn_undo)
        top.addStretch()
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        top.addWidget(btn_theme)
        center_layout.addLayout(top)

        # Top toolbar row 2: type filters
        top2 = QHBoxLayout()
        top2.addWidget(QLabel("类型:"))
        self._type_filter_cbs = {}
        for tval in [5, 10, 15, 16, 20, 110, 200]:
            cb = QCheckBox(ENTITY_TYPES.get(tval, f"T{tval}"))
            cb.setChecked(True)
            cb.stateChanged.connect(self._canvas._vis_redraw)
            self._type_filter_cbs[tval] = cb
            top2.addWidget(cb)
        top2.addSpacing(12)
        # 前景遮挡开关: L1 前景遮挡深度逐像素遮挡精灵 (游戏真实"前景层"渲染, 默认开)
        self._vis_occlusion_cb = QCheckBox("前景遮挡")
        self._vis_occlusion_cb.setChecked(True)
        self._vis_occlusion_cb.setToolTip(
            "按 GRP 场景 Frame B Layer1 前景遮挡深度逐像素遮挡实体精灵\n"
            "(逆向 sub_406E50/sub_459F78: 精灵在前景景物如树冠/屋檐后被遮挡)")
        self._vis_occlusion_cb.stateChanged.connect(self._canvas._vis_redraw)
        top2.addWidget(self._vis_occlusion_cb)
        top2.addStretch()
        center_layout.addLayout(top2)

        # Map canvas — SceneCanvasView 已在方法顶部创建 (§4), 此处仅设置背景并加入布局
        self._canvas.update_vis_background()
        center_layout.addWidget(self._canvas, 1)
        center_widget.setMinimumWidth(400)
        self.splitter.addWidget(center_widget)

    # =========== 右侧面板: 编辑区 ===========
    def _build_right_panel(self):
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.lbl_title = QLabel("未选中")
        self.lbl_title.setProperty("class", "RecordHeader")
        right_layout.addWidget(self.lbl_title)

        # Notebook (通用编辑器标签页)
        self.notebook = EditorTabWidget(
            flat=True,
            object_name="MatEditorTabs",
        )
        right_layout.addWidget(self.notebook, 1)

        # Tab "参数"
        self.tab_param = QWidget()
        self.tab_param_layout = QVBoxLayout(self.tab_param)
        self.tab_param_layout.setContentsMargins(0, 0, 0, 0)
        self.notebook.addTab(self.tab_param, "参数")

        # Build per-type parameter pages
        self._inspector.build_type_param_pages()

        # Tab "脚本"
        self.tab_script = QWidget()
        self.notebook.addTab(self.tab_script, "脚本")
        self._build_script_tab()

        # Tab "全部"
        self.tab_all = QWidget()
        self.notebook.addTab(self.tab_all, "全部")
        self._build_all_tab()

        # 参数页 / 全部页的镜像 QLineEdit 双向同步 (等价 v1 StringVar 互通)
        self._inspector.wire_raw_mirrors()

        # Bottom buttons
        bf = QHBoxLayout()
        btn_apply = QPushButton("应用修改")
        btn_apply.clicked.connect(self._apply_edit)
        bf.addWidget(btn_apply)
        btn_reset = QPushButton("重置")
        btn_reset.clicked.connect(self._reset_edit)
        bf.addWidget(btn_reset)
        bf.addStretch()
        btn_goto = QPushButton("跳转到空槽…")
        btn_goto.clicked.connect(self._goto_empty)
        bf.addWidget(btn_goto)
        right_layout.addLayout(bf)

        self.edit_frame = right_widget
        right_widget.setMinimumWidth(460)
        self.splitter.addWidget(right_widget)

    # =========== 脚本标签页 ===========
    def _build_script_tab(self):
        """构建脚本编辑标签页"""
        layout = QVBoxLayout(self.tab_script)
        layout.setContentsMargins(4, 4, 4, 4)

        # Script splitter (vertical)
        script_splitter = QSplitter(Qt.Vertical)
        script_splitter.setHandleWidth(6)

        # Top: 脚本调度信息 + DefUnit链列表
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 调度信息
        sched_group = QFrame()
        sched_group.setObjectName("PreviewFrame")
        sched_layout = QGridLayout(sched_group)
        sched_layout.setContentsMargins(8, 8, 8, 8)
        sched_layout.setSpacing(4)

        sched_items = [
            ('enabled', '启用', 'flags bit0=启用'),
            ('pickable', '可交互', 'flags bit2=可交互'),
            ('tick', 'Tick周期', 'd4=Tick'),
            ('timer', '定时器', 'd3=定时器'),
            ('chain_a', 'A链(自动)', 'DEFINE链A = Tick自动执行'),
            ('chain_b', 'B链(触发)', 'DEFINE链B = 触发执行'),
            ('chain_c', 'C链(保留)', 'DEFINE链C = 保留链'),
            ('trigger', '触发方式', '基于实体类型'),
        ]
        for ri, (key, label, tip) in enumerate(sched_items):
            r, c = divmod(ri, 4)
            lbl = QLabel(f"{label}:")
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            val = QLabel("")
            val.setProperty("class", "ExtraPreviewText")
            sched_layout.addWidget(lbl, r, c * 2)
            sched_layout.addWidget(val, r, c * 2 + 1)
            self._sched_labels[key] = val
        top_layout.addWidget(sched_group)

        # DefUnit chain list
        chain_toolbar = QHBoxLayout()
        for text, chain in [("➕ A链", "A"), ("➕ B链", "B"), ("➕ C链", "C")]:
            btn = QPushButton(text)
            btn.setFixedWidth(65)
            btn.setProperty("class", "CompactBtn")
            btn.clicked.connect(partial(self._add_chain_entry, chain))
            chain_toolbar.addWidget(btn)
        btn_del_chain = QPushButton("🗑️ 删除")
        btn_del_chain.setFixedWidth(65)
        btn_del_chain.setProperty("class", "CompactBtn")
        btn_del_chain.clicked.connect(self._delete_chain_entry)
        chain_toolbar.addWidget(btn_del_chain)
        btn_refr = QPushButton("🔄 刷新")
        btn_refr.setFixedWidth(65)
        btn_refr.setProperty("class", "CompactBtn")
        btn_refr.clicked.connect(self._refresh_chain_list)
        chain_toolbar.addWidget(btn_refr)
        chain_toolbar.addStretch()
        self.chain_info_lbl = QLabel("")
        self.chain_info_lbl.setProperty("class", "PropLabel")
        chain_toolbar.addWidget(self.chain_info_lbl)
        top_layout.addLayout(chain_toolbar)

        self.chain_tree = QTreeWidget()
        self.chain_tree.setHeaderLabels(["子场景", "序号", "DefUnit#", "DEFINE ID", "f0", "标记"])
        self.chain_tree.setColumnWidth(0, 60)
        self.chain_tree.setColumnWidth(1, 35)
        self.chain_tree.setColumnWidth(2, 55)
        self.chain_tree.setColumnWidth(3, 70)
        self.chain_tree.setColumnWidth(4, 35)
        self.chain_tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        self.chain_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chain_tree.setRootIsDecorated(False)
        self.chain_tree.itemSelectionChanged.connect(self._on_chain_select)
        top_layout.addWidget(self.chain_tree, 1)

        script_splitter.addWidget(top_widget)

        # Bottom: 脚本编辑器 + 预览
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        # Script toolbar
        stb = QHBoxLayout()
        self.script_info_lbl = QLabel("(未选中 DEFINE)")
        self.script_info_lbl.setProperty("class", "PropLabel")
        stb.addWidget(self.script_info_lbl, 1)
        self._btn_fix_validate = QPushButton("🔧 修复验证")
        self._btn_fix_validate.setFixedWidth(104)
        self._btn_fix_validate.setToolTip("校验脚本中 SetPos 等语句的实体号/坐标/朝向是否与当前实体一致, 不一致可一键修复")
        self._btn_fix_validate.clicked.connect(self._show_fix_validate_menu)
        stb.addWidget(self._btn_fix_validate)
        self._btn_script_tpl = QPushButton("📋 脚本模板")
        self._btn_script_tpl.setFixedWidth(104)
        self._btn_script_tpl.setToolTip("从原版高频脚本写法中挑选模板, 一键填入脚本编辑框光标处")
        self._btn_script_tpl.clicked.connect(self._show_script_template_dialog)
        stb.addWidget(self._btn_script_tpl)
        btn_preview = QPushButton("▶ 预览")
        btn_preview.setFixedWidth(70)
        btn_preview.setToolTip("预览当前脚本执行流程")
        btn_preview.clicked.connect(self._preview_script)
        stb.addWidget(btn_preview)
        bot_layout.addLayout(stb)

        # Editor + preview (horizontal splitter)
        editor_splitter = QSplitter(Qt.Horizontal)
        editor_splitter.setHandleWidth(6)

        # Left: Script editor (CodeEditor)
        self.script_text = CodeEditor()
        self.script_text.setFont(QFont("Consolas", 10))
        self.script_text.setTabStopDistance(40)
        self.script_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.script_text.textChanged.connect(self._on_script_edit)
        # 语法高亮器 (逻辑对应 mat_editor.py _apply_syntax_highlight)
        self._script_highlighter = ScriptSyntaxHighlighter(self.script_text.document(), self._is_dark)
        editor_splitter.addWidget(self.script_text)

        # Right: Line preview
        self.script_preview = QPlainTextEdit()
        self.script_preview.setFont(QFont("Consolas", 10))
        self.script_preview.setReadOnly(True)
        self.script_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor_splitter.addWidget(self.script_preview)

        editor_splitter.setSizes([400, 400])
        bot_layout.addWidget(editor_splitter, 1)

        script_splitter.addWidget(bot_widget)
        script_splitter.setSizes([350, 400])
        layout.addWidget(script_splitter)

        # State
        self.script_text.setReadOnly(True)
        self._disable_scroll_sync = False

        # 滚动同步: 编辑器 <-> 行预览
        self._script_sb = self.script_text.verticalScrollBar()
        self._preview_sb = self.script_preview.verticalScrollBar()
        def _on_editor_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                self._disable_scroll_sync = True
                ratio = val / max(1, _es.maximum())
                _ps.setValue(int(ratio * max(1, _ps.maximum())))
                self._disable_scroll_sync = False
        def _on_preview_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                self._disable_scroll_sync = True
                ratio = val / max(1, _ps.maximum())
                _es.setValue(int(ratio * max(1, _es.maximum())))
                self._disable_scroll_sync = False
        self._script_sb.valueChanged.connect(_on_editor_scroll)
        self._preview_sb.valueChanged.connect(_on_preview_scroll)

    # =========== 全部标签页 ===========
    def _build_all_tab(self):
        """Tab '全部': 按 d0~d95 顺序展示全部 96 个字段"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QGridLayout(inner)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(4, 4, 4, 4)

        known = {}
        for fields in (BASIC_FIELDS, FLAG_FIELDS, POS_FIELDS, ANIM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)

        for di in range(96):
            r, c = divmod(di, 4)
            if di in known:
                name, label, cmt = known[di]
                key = f'raw_{di}'
                lbl_text = f"[{di:02d}] {label}"
            else:
                key = f'd{di}'
                label = f'd{di}'
                cmt = ""
                lbl_text = f"[{di:02d}] d{di}"

            lbl = QLabel(lbl_text)
            lbl.setProperty("class", "PropLabel")
            lbl.setWordWrap(True)
            lbl.setMaximumWidth(_FIELD_LABEL_MAX_WIDTH)
            if cmt:
                lbl.setToolTip(f"[{di:02d}] {cmt}")

            # "全部"页为每个字段创建独立 QLineEdit 并登记镜像。
            # canonical _edit_vars[key] 指向"全部"页控件; 参数页镜像双向同步。
            ev = self._inspector.make_raw_edit(di)
            self._edit_vars[key] = ev
            ev.setMaximumWidth(80)

            inner_layout.addWidget(lbl, r, c * 2, Qt.AlignRight | Qt.AlignVCenter)
            inner_layout.addWidget(ev, r, c * 2 + 1)
            self._all_labels[di] = lbl

        scroll.setWidget(inner)
        layout = QVBoxLayout(self.tab_all)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # =========== 编辑控件启用/禁用 ===========
    def _set_edit_enabled(self, en):
        self.edit_frame.setEnabled(en)



    # =========== 路径更新 ===========
    def _get_game_dir(self):
        """获取游戏资源目录 (TKMat.Dat/SC.GRP/JVG 等所在目录)。
        存档模式下返回 self._data._game_dir，普通模式返回 dat_path 的父目录。"""
        if self._data._save_mode and self._data._game_dir:
            return self._data._game_dir
        return os.path.dirname(self._data.dat_path) if self._data.dat_path else ''

    def _update_path(self):
        if not self._data.dat_path:
            self.lbl_path.setText("(未加载)")
            self.lbl_path.setProperty("status", "missing")
            self.lbl_path.setToolTip("")
        elif not os.path.exists(self._data.dat_path):
            self.lbl_path.setText(f"{os.path.basename(self._data.dat_path)} (不存在)")
            self.lbl_path.setProperty("status", "missing")
            self.lbl_path.setToolTip(os.path.normpath(self._data.dat_path))
        else:
            self.lbl_path.setText(os.path.basename(self._data.dat_path))
            self.lbl_path.setProperty("status", "loaded")
            self.lbl_path.setToolTip(os.path.normpath(self._data.dat_path))
        self.lbl_path.style().unpolish(self.lbl_path)
        self.lbl_path.style().polish(self.lbl_path)

        for lbl, jvg, name in [(self.lbl_cha, self._cha_jvg, "Cha.JVG"),
                                (self.lbl_ani, self._ani_jvg, "Ani.JVG"),
                                (self.lbl_cur, self._cur_jvg, "Cur.JVG")]:
            if jvg is not None:
                lbl.setText(f"{name}✓")
                lbl.setProperty("status", "loaded")
            elif self._data.dat_path and os.path.exists(self._data.dat_path):
                lbl.setText(f"{name}✗")
                lbl.setProperty("status", "missing")
            else:
                lbl.setText(name)
                lbl.setProperty("status", "unloaded")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        if self._data._sc_grp_section_count > 0:
            self.lbl_sc.setText(f"SC.GRP✓({self._data._sc_grp_section_count})")
            self.lbl_sc.setProperty("status", "loaded")
        elif self._data.dat_path and os.path.exists(self._data.dat_path):
            self.lbl_sc.setText("SC.GRP✗")
            self.lbl_sc.setProperty("status", "missing")
        else:
            self.lbl_sc.setText("SC.GRP")
            self.lbl_sc.setProperty("status", "unloaded")
        self.lbl_sc.style().unpolish(self.lbl_sc)
        self.lbl_sc.style().polish(self.lbl_sc)

    # =========== 筛选/列表 ===========
    def _apply_filter(self):
        ftype = self.filter_type.currentText()
        show_empty = self.show_empty_cb.isChecked()
        show_global = self.show_global_cb.isChecked()
        sid = self._canvas._vis_scene_id
        ftype_val = int(ftype.split('-')[0]) if ftype and ftype != "全部" else None
        self._data.filtered_indices = []
        for rec in self._data.records:
            if is_empty(rec):
                if not show_empty:
                    continue
            else:
                # 按当前选中场景联动筛选; 全局实体(d1==-1)仅在勾选「全局」时显示
                if rec['d1'] != sid and not (show_global and rec['d1'] == -1):
                    continue
                if ftype_val is not None and rec['d0'] != ftype_val:
                    continue
            self._data.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _refresh_table(self):
        sel_idx = None
        sel = self.entity_tree.selectedItems()
        if sel:
            sel_idx = int(sel[0].text(0))

        # 性能关键: 禁用排序+信号+更新, 批量添加
        self.entity_tree.setUpdatesEnabled(False)
        self.entity_tree.blockSignals(True)
        self.entity_tree.setSortingEnabled(False)
        self.entity_tree.clear()

        # 限制显示数量，避免实例化过多 QTreeWidgetItem 对象
        DISPLAY_LIMIT = 500
        show_indices = self._data.filtered_indices[:DISPLAY_LIMIT]

        # 批量构建所有 item 后一次性添加
        items = []
        for idx in show_indices:
            rec = self._data.records[idx]
            tval = rec['d0']
            sname = scene_name(self._data.tkt_scenes, rec['d1'])
            script_lbl, tick_lbl = get_script_info(rec)
            vals = [str(idx), f"{tval}-{ENTITY_TYPES.get(tval, '未知')}", sname,
                    str(rec['d10']), str(rec['d11']), script_lbl, tick_lbl]
            item = QTreeWidgetItem(vals)
            # Color by type
            color = self._entity_type_colors.get(tval)
            if color:
                for c in range(7):
                    item.setForeground(c, color)
            items.append(item)

        self.entity_tree.addTopLevelItems(items)

        # Restore selection
        if sel_idx is not None:
            for i in range(self.entity_tree.topLevelItemCount()):
                item = self.entity_tree.topLevelItem(i)
                if item and int(item.text(0)) == sel_idx:
                    self.entity_tree.setCurrentItem(item)
                    break

        self.entity_tree.setUpdatesEnabled(True)
        self.entity_tree.setSortingEnabled(True)
        self.entity_tree.blockSignals(False)

        if not self.entity_tree.selectedItems():
            self._current_param_idx = None
            self.lbl_title.setText("未选中")
            self._clear_form()

        # 截断提示
        if len(self._data.filtered_indices) > DISPLAY_LIMIT:
            self._vis_info_label.setText(f"列表已截断显示前 {DISPLAY_LIMIT}/{len(self._data.filtered_indices)} 条，使用筛选缩小范围")

    def _sort_entity_by_column(self, col):
        """点击列头排序实体列表"""
        # 列: 索引(0) 类型(1) 场景(2) X(3) Y(4) 脚本(5) Tick(6)
        key_map = {0: 'index', 1: 'd0', 2: 'd1', 3: 'd10', 4: 'd11', 6: 'd4'}
        key = key_map.get(col)
        if key is None:
            return  # 脚本/Tick 列不支持排序
        # 切换排序方向
        current_order = self.entity_tree.header().sortIndicatorOrder()
        reverse = (current_order == Qt.DescendingOrder)
        # 对 filtered_indices 排序并刷新
        self._data.filtered_indices.sort(
            key=lambda i: self._data.records[i].get(key, 0) if isinstance(self._data.records[i].get(key, 0), (int, float)) else 0,
            reverse=reverse)
        self._refresh_table()

    # =========== 实体搜索 ===========
    def _search_entity_by_id(self):
        """按实体ID(索引)搜索并定位实体, 自动切换到其所属场景 (§实体搜索)。

        实体列表默认按当前场景联动筛选, 无法直接查看某实体属于哪个场景;
        本方法读取搜索框中的实体ID(即列表「索引」列 = records 下标), 定位记录后:
          - 普通场景实体(d1>=0): 切换到其所属场景并同步场景列表/下拉框;
          - 全局实体(d1==-1): 勾选「全局」使其可见;
          - 空槽(未使用): 勾选「空槽」并提示该实体不属于任何场景;
        随后刷新列表、选中目标并在状态栏报告其所属场景。"""
        if not self._data.records:
            self.status_var.setText("请先通过 文件 → 加载 TKS 目录 打开数据")
            return
        txt = self.search_id_edit.text().strip()
        if not txt:
            return
        try:
            idx = int(txt)
        except ValueError:
            themed_messagebox(self, QMessageBox.Warning, "实体搜索",
                              f"请输入有效的实体ID(整数)，当前输入：「{txt}」")
            return
        max_idx = len(self._data.records) - 1
        if not (0 <= idx <= max_idx):
            themed_messagebox(self, QMessageBox.Warning, "实体搜索",
                              f"实体ID {idx} 超出范围 (有效范围 0 ~ {max_idx})")
            return
        rec = self._data.records[idx]
        sid = rec['d1']
        empty = is_empty(rec)
        sname = scene_name(self._data.tkt_scenes, sid)

        # 联动筛选条件, 确保目标实体不会被现有筛选器隐藏 (阻断信号避免重复刷新)
        self.filter_type.blockSignals(True)
        self.filter_type.setCurrentIndex(0)
        self.filter_type.blockSignals(False)
        if empty:
            self.show_empty_cb.blockSignals(True)
            self.show_empty_cb.setChecked(True)
            self.show_empty_cb.blockSignals(False)
        elif sid == -1:
            self.show_global_cb.blockSignals(True)
            self.show_global_cb.setChecked(True)
            self.show_global_cb.blockSignals(False)

        # 普通场景实体: 切换到其所属场景 (空槽/全局实体在任意场景下都可显示, 无需切换)
        if not empty and sid >= 0 and sid != self._canvas._vis_scene_id:
            self._canvas._undo_stack.clear()  # 跨场景撤销栈失效, 清空避免误撤销
            self._canvas._vis_scene_id = sid
            self._canvas._vis_stop_anim()
            # 同步场景列表 + 下拉框选中态 (阻断信号避免二次触发场景切换)
            self.scene_tree.blockSignals(True)
            for i in range(self.scene_tree.topLevelItemCount()):
                it = self.scene_tree.topLevelItem(i)
                if it and int(it.text(0)) == sid:
                    self.scene_tree.setCurrentItem(it)
                    self.scene_tree.scrollToItem(it)
                    break
            self.scene_tree.blockSignals(False)
            self._vis_scene_combo.blockSignals(True)
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_scene_combo.blockSignals(False)
            self._vis_load_scene()

        # 刷新列表并定位实体; 若因 500 条显示上限被截断, 置顶目标后重试确保可选中
        self._apply_filter()
        selected = self._sync_entity_list_select(idx)
        if not selected and idx in self._data.filtered_indices:
            self._data.filtered_indices.remove(idx)
            self._data.filtered_indices.insert(0, idx)
            self._refresh_table()
            selected = self._sync_entity_list_select(idx)
        if not selected:
            # 兜底: 列表未能选中(极端情况)也在右侧表单显示该记录
            self._current_param_idx = idx
            self._show_record(rec)

        # 状态栏报告实体所属场景
        tname = f"{rec['d0']}-{ENTITY_TYPES.get(rec['d0'], '未知')}"
        if empty:
            self.status_var.setText(f"实体 #{idx} 为空槽 (未使用, 不属于任何场景)")
        elif sid == -1:
            self.status_var.setText(f"实体 #{idx} 属于「全局(所有场景)」 — 类型 {tname}")
        else:
            self.status_var.setText(f"实体 #{idx} 属于场景 {sid}: {sname} — 类型 {tname}, 坐标({rec['d10']},{rec['d11']})")

    # =========== 选择事件 ===========
    def _on_select(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            self.lbl_title.setText("未选中")
            self._clear_form()
            return
        idx = int(sel[0].text(0))
        self._current_param_idx = idx
        rec = self._data.records[idx]
        self._show_record(rec)
        # Sync highlight on map
        if rec['d1'] == self._canvas._vis_scene_id:
            self._canvas._vis_selected = idx
            self._canvas._vis_redraw()
            tname = ENTITY_TYPES.get(rec['d0'], '?')
            self._vis_info_label.setText(f"选中: #{idx} [{tname}] 坐标({rec['d10']},{rec['d11']})")

    # =========== 场景选择 ===========
    def _on_vis_scene_select(self):
        sel = self.scene_tree.selectedItems()
        if not sel:
            return
        sid = int(sel[0].text(0))
        if sid != self._canvas._vis_scene_id:
            self._canvas._undo_stack.clear()  # 切换场景后撤销栈失效, 清空避免跨场景误撤销
        self._canvas._vis_scene_id = sid
        # Sync combo
        for i in range(self._vis_scene_combo.count()):
            if self._vis_scene_combo.itemText(i).startswith(f"{sid}:"):
                self._vis_scene_combo.setCurrentIndex(i)
                break
        self._canvas._vis_stop_anim()
        self._vis_load_scene()
        self._apply_filter()

    def _on_vis_combo_select(self):
        val = self._vis_scene_combo.currentText()
        try:
            sid = int(val.split(':')[0])
        except ValueError:
            return
        if sid != self._canvas._vis_scene_id:
            self._canvas._undo_stack.clear()  # 切换场景后撤销栈失效, 清空避免跨场景误撤销
        self._canvas._vis_scene_id = sid
        self._canvas._vis_stop_anim()
        self._vis_load_scene()
        self._apply_filter()

    def _sync_entity_list_select(self, idx):
        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item and int(item.text(0)) == idx:
                self.entity_tree.setCurrentItem(item)
                self.entity_tree.scrollToItem(item)
                return True
        return False

    # =========== 显示记录 ===========
    def _show_record(self, rec):
        idx = rec['index']
        tval = rec['d0']
        tname = ENTITY_TYPES.get(tval, f"未知({tval})")
        sname = scene_name(self._data.tkt_scenes, rec['d1'])
        self.lbl_title.setText(f"实体 #{idx} [{tname}] {sname} ({rec['d10']},{rec['d11']})")

        BLEND_MODES = {0: "正常", 1: "染色", 2: "加法发光", 3: "减法压暗", 4: "亮度alpha", 5: "水平翻转"}
        SHADOW_LABELS = {0: "无阴影", 1: "小阴影(39×23)", 2: "大阴影(65×33)"}

        # Fill all 96 raw fields
        for di in range(96):
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(str(rec[f'd{di}']))

        # Scene label
        sl = self._edit_vars.get('_scene_label')
        if isinstance(sl, QLabel):
            sl.setText(sname)

        # Hint label
        hl = self._edit_vars.get('_hint_label')
        if isinstance(hl, QLabel):
            hid = rec['d23']
            hl.setText("" if hid == 0 else self._data.tkt_scenes.get(hid, ""))

        # Item name labels
        for key, di in [('_item_g1_id_label', 53), ('_item_g2_id_label', 57), ('_item_g3_id_label', 61)]:
            lbl = self._edit_vars.get(key)
            if isinstance(lbl, QLabel):
                item_id = rec[f'd{di}']
                if item_id and item_id in self._data.item_names:
                    lbl.setText(self._data.item_names[item_id])
                elif item_id:
                    lbl.setText(f"物品 #{item_id}")
                else:
                    lbl.setText("")

        # Switch to correct type page
        self._update_param_labels(tval)

        # Fill active type page
        if tval in self._type_vars:
            tvars = self._type_vars[tval]
            for key, di, label, cmt in ALL_EDIT_FIELDS:
                val = rec[f'd{di}']
                w = tvars.get(key)
                if isinstance(w, EditorComboBox):
                    if key == 'type':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'anim_set':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'blend_mode':
                        bm = BLEND_MODES.get(val, '未知')
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'shadow_frame':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                    elif key == 'cursor_id':
                        for i in range(w.count()):
                            if w.itemText(i).startswith(f"{val}-"):
                                w.setCurrentIndex(i)
                                break
                elif isinstance(w, QLineEdit):
                    w.setText(str(val))

            for key, di, label, cmt in RUNTIME_FIELDS:
                w = tvars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(str(rec[f'd{di}']))

            # Scene label
            sl2 = tvars.get('_scene_label')
            if isinstance(sl2, QLabel):
                sl2.setText(sname)
            # Hint label
            hl2 = tvars.get('_hint_label')
            if isinstance(hl2, QLabel):
                hid = rec['d23']
                hl2.setText("" if hid == 0 else self._data.tkt_scenes.get(hid, ""))
            # Item labels
            for key, di in [('_item_g1_id_label', 53), ('_item_g2_id_label', 57), ('_item_g3_id_label', 61)]:
                lbl = tvars.get(key)
                if isinstance(lbl, QLabel):
                    item_id = rec[f'd{di}']
                    if item_id and item_id in self._data.item_names:
                        lbl.setText(self._data.item_names[item_id])
                    elif item_id:
                        lbl.setText(f"物品 #{item_id}")
                    else:
                        lbl.setText("")

            # Flag checkboxes
            flags = rec['d2']
            bit_vars = tvars.get('_bit_vars')
            if bit_vars:
                for attr, mask in [("_bit_enable", 1), ("_bit_visible", 2), ("_bit_pickable", 4),
                                    ("_bit_hint", 8), ("_bit_busy", 0x10), ("_bit_resume", 0x20),
                                    ("_bit_taken", 0x100), ("_bit_animloop", 0x10000),
                                    ("_bit_ev12", 0x1000), ("_bit_ev13", 0x2000), ("_bit_ev14", 0x4000)]:
                    cb = bit_vars.get(attr)
                    if cb:
                        cb.blockSignals(True)
                        cb.setChecked((flags & mask) != 0)
                        cb.blockSignals(False)

            # Dialog color swatch update
            dc_swatch = tvars.get('_dialog_color_swatch')
            if dc_swatch and isinstance(dc_swatch, QFrame):
                dc_val = rec['d28']
                dc_swatch.setStyleSheet(
                    f"background-color: {GAME_COLORS.get(dc_val + 1, '#000')};")

            # Direction mask checkboxes update
            dir_bv = tvars.get('_dir_bv')
            if dir_bv:
                d51_val = rec['d51']
                for bit_i in dir_bv:
                    dir_bv[bit_i].blockSignals(True)
                    dir_bv[bit_i].setChecked((d51_val & (1 << bit_i)) != 0)
                    dir_bv[bit_i].blockSignals(False)

            # Event flag checkbox visibility (bit12/13/14 only for type=20/200)
            self._update_type_flags_visibility(tvars, tval)

        # Update all tab labels
        self._update_all_tab_labels(tval)
        # Refresh chain list
        self._refresh_chain_list()
        # Update sched info
        self._update_sched_info(rec)

    def _update_param_labels(self, tval):
        """Switch to the correct type parameter page"""
        # Hide current
        if self._active_type and self._active_type in self._type_frames:
            self._type_frames[self._active_type].setVisible(False)
            # Remove from layout
            self.tab_param_layout.removeWidget(self._type_frames[self._active_type])
        # Show target
        if tval in self._type_frames:
            self.tab_param_layout.addWidget(self._type_frames[tval])
            self._type_frames[tval].setVisible(True)
            self._active_type = tval

    def _update_all_tab_labels(self, tval):
        """Update '全部' tab labels based on entity type"""
        type_labels = _TYPE_LABELS.get(tval, {})
        known = {}
        for fields in (BASIC_FIELDS, FLAG_FIELDS, POS_FIELDS, ANIM_FIELDS, ITEM_FIELDS, SCRIPT_FIELDS, INTERACT_FIELDS, RUNTIME_FIELDS):
            for name, di, label, cmt in fields:
                known[di] = (name, label, cmt)
        for di in range(96):
            if di not in self._all_labels:
                continue
            lbl = self._all_labels[di]
            if di in type_labels:
                tl, tc = type_labels[di]
                lbl.setText(f"[{di:02d}] {tl}")
                lbl.setProperty("class", "TypeFieldLabel")
            elif di in known:
                name, label, cmt = known[di]
                lbl.setText(f"[{di:02d}] {label}")
                lbl.setProperty("class", "PropLabel")
            else:
                lbl.setText(f"[{di:02d}] d{di}")
                lbl.setProperty("class", "UnknownFieldLabel")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _update_type_flags_visibility(self, tvars, tval):
        """根据实体类型显示/隐藏事件标志 checkbox (bit12/13/14)"""
        bit_event_idxs = tvars.get('_bit_event_idxs', [])
        bit_cbs = tvars.get('_bit_cbs', [])
        show = tval in (20, 200)
        for i in bit_event_idxs:
            if i < len(bit_cbs):
                bit_cbs[i].setVisible(show)

    def _update_flags_visibility(self, tval):
        """根据实体类型更新全局 flags 事件标志可见性"""
        # For type pages
        if tval in self._type_vars:
            self._update_type_flags_visibility(self._type_vars[tval], tval)

    def _clear_form(self):
        for key, var in self._edit_vars.items():
            if isinstance(var, QLineEdit):
                var.clear()
            elif isinstance(var, EditorComboBox):
                var.setCurrentIndex(0)
        for lbl_key in ('_scene_label', '_hint_label', '_item_g1_id_label', '_item_g2_id_label', '_item_g3_id_label'):
            lbl = self._edit_vars.get(lbl_key)
            if isinstance(lbl, QLabel):
                lbl.setText("")
        # Clear type pages
        for tval in self._type_vars:
            tvars = self._type_vars[tval]
            for key, var in tvars.items():
                if isinstance(var, QLineEdit):
                    var.clear()
                elif isinstance(var, EditorComboBox):
                    var.setCurrentIndex(0)
                elif isinstance(var, QCheckBox):
                    var.setChecked(False)
        # Clear script tab
        # 先提交当前脚本到内存 (避免丢改动), 再复位 define 并屏蔽信号清空 chain_tree:
        # chain_tree.clear() 会发出瞬时 itemSelectionChanged (Qt 行为) 误触 _on_chain_select,
        # 若脚本编辑器已清空而 _current_edit_define_id 未复位, 会把空内容写回原 DEFINE
        # 造成"切换回来脚本内容消失" (§修复)
        self._save_editor_to_define()
        self._current_edit_define_id = None
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self.script_preview.clear()
        self.chain_tree.blockSignals(True)
        self.chain_tree.clear()
        self.chain_tree.blockSignals(False)
        self._current_edit_define_id = None
        self._update_sched_info(None)

    # =========== 编辑操作 ===========
    def _read_form(self):
        vals = {}
        covered = set()
        # From active type page
        if self._active_type and self._active_type in self._type_vars:
            tvars = self._type_vars[self._active_type]
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for cb_key, cb_di, *_ in fields:
                    w = tvars.get(cb_key)
                    if isinstance(w, EditorComboBox):
                        try:
                            v = int(w.currentText().split('-')[0])
                            vals[f'd{cb_di}'] = v
                            covered.add(cb_di)
                        except ValueError:
                            pass
                    elif isinstance(w, QLineEdit) and cb_di not in covered:
                        try:
                            v = int(w.text())
                            vals[f'd{cb_di}'] = v
                            covered.add(cb_di)
                        except ValueError:
                            pass
        # From "全部" tab
        for di in range(96):
            if di in covered:
                continue
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    try:
                        v = int(w.text())
                        vals[f'd{di}'] = v
                        covered.add(di)
                        break
                    except ValueError:
                        return None
        # Fill remaining
        for di in range(96):
            if di not in covered:
                vals[f'd{di}'] = 0
        return vals

    def _apply_edit(self):
        sel = self.entity_tree.selectedItems()
        if sel:
            idx = int(sel[0].text(0))
        elif self._current_param_idx is not None:
            idx = self._current_param_idx
        else:
            return
        new_vals = self._read_form()
        if new_vals is None:
            QMessageBox.warning(self, "输入错误", "字段值必须是整数")
            return
        rec = self._data.records[idx]
        for key, val in new_vals.items():
            rec[key] = val
        self._data._dirty = True
        # 先把当前脚本编辑器内容提交到内存, 再刷新, 避免刷新链列表时丢失脚本改动 (§修复)
        self._save_editor_to_define()
        self._show_record(rec)
        self._apply_filter()
        self._sync_entity_list_select(idx)
        if rec['d1'] == self._canvas._vis_scene_id:
            self._canvas._vis_redraw()

    def _reset_edit(self):
        sel = self.entity_tree.selectedItems()
        if sel:
            idx = int(sel[0].text(0))
        elif self._current_param_idx is not None:
            idx = self._current_param_idx
        else:
            return
        self._show_record(self._data.records[idx])

    # =========== 新增/复制/清空 ===========
    def _compute_new_entity_center(self, sel_scene):
        """计算新增实体的落点坐标 (§需求1)。
        新增到当前预览场景时, 返回画布可视区中心对应的场景坐标 (clamp 到场景范围内);
        否则返回 None, 表示该场景未在预览、无可视中心可用, 由调用方回退到历史默认坐标。"""
        if sel_scene != self._canvas._vis_scene_id:
            return None
        vp = self._canvas.viewport()
        if vp.width() <= 0 or vp.height() <= 0:
            return None
        center = self._canvas.mapToScene(vp.rect().center())
        cx, cy = int(center.x()), int(center.y())
        rect = self._canvas._vis_gscene.sceneRect()
        if rect.width() > 0 and rect.height() > 0:
            cx = min(max(cx, 0), int(rect.width()))
            cy = min(max(cy, 0), int(rect.height()))
        else:
            cx = max(cx, 0)
            cy = max(cy, 0)
        return cx, cy

    def _new_record(self, pos=None):
        # pos: 右键空白处新增时的鼠标场景坐标 (x, y); 菜单/按钮经 Qt 信号可能误传 bool,
        # 故此处校验, 非法值一律视为 None (回退到可视区中心新增)
        if not isinstance(pos, (tuple, list)) or len(pos) != 2:
            pos = None
        if not self._data.records:
            return
        empty_idx = None
        for rec in self._data.records:
            if is_empty(rec):
                empty_idx = rec['index']
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"所有{REC_COUNT}条记录均已占用")
            return

        # Type/scene selection dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(f"新增实体 (落点 {int(pos[0])},{int(pos[1])})" if pos is not None else "新增实体")
        dlg.resize(400, 200)
        dl = QVBoxLayout(dlg)

        dl.addWidget(QLabel("实体类型:"))
        type_cb = EditorComboBox()
        type_cb.addItems([f"{k}-{v}" for k, v in sorted(ENTITY_TYPES.items()) if k != 0])
        type_cb.setCurrentIndex(6)  # 200-NPC角色
        dl.addWidget(type_cb)

        dl.addWidget(QLabel("场景 ID:"))
        scene_entry = QLineEdit(str(self._canvas._vis_scene_id))
        dl.addWidget(scene_entry)
        scene_lbl = QLabel(scene_name(self._data.tkt_scenes, self._canvas._vis_scene_id))
        dl.addWidget(scene_lbl)

        def _on_scene_change():
            try:
                sid = int(scene_entry.text())
                scene_lbl.setText(scene_name(self._data.tkt_scenes, sid))
            except ValueError:
                pass
        scene_entry.textChanged.connect(_on_scene_change)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        confirmed = [False]
        def _ok():
            confirmed[0] = True
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        dl.addLayout(btn_layout)

        if dlg.exec() != QDialog.Accepted or not confirmed[0]:
            return

        try:
            sel_type = int(type_cb.currentText().split('-')[0])
        except ValueError:
            return
        try:
            sel_scene = int(scene_entry.text())
        except ValueError:
            sel_scene = self._canvas._vis_scene_id

        # 撤销: 记录目标空槽的原始 (空) 状态, 供 Ctrl+Z 回退新增 (§需求3)
        self._canvas._push_undo(f"新增 #{empty_idx}", [empty_idx])

        rec = self._data.records[empty_idx]
        for di in range(DWORD_COUNT):
            rec[f'd{di}'] = 0
        rec['d0'] = sel_type
        rec['d1'] = sel_scene
        rec['d2'] = 3       # 启用+可见
        rec['d42'] = -1     # 执行位置·PC: -1=空闲
        rec['d43'] = -1     # 调用返回·SP: -1=空栈
        rec['d44'] = -1     # 当前DefUnit#: -1=未遍历
        rec['d8'] = 3 if sel_type == 10 else 0
        rec['_has_data'] = True
        rec['d20'] = 30 if sel_type == 110 else 40
        rec['d21'] = 30 if sel_type == 110 else 24
        # 落点: 右键空白处新增落到鼠标坐标; 否则新增到当前预览场景时放到可视区正中心 (§需求1/右键新增)
        if pos is not None and sel_scene == self._canvas._vis_scene_id:
            center = (max(0, int(pos[0])), max(0, int(pos[1])))
        else:
            center = self._compute_new_entity_center(sel_scene)
        if center is None:
            rec['d18'] = 400
            rec['d19'] = 384
            rec['d10'] = rec['d18'] + rec['d20'] // 2
            rec['d11'] = rec['d19'] + rec['d21'] // 2
        else:
            cx, cy = center
            rec['d10'] = cx
            rec['d11'] = cy
            rec['d18'] = max(0, cx - rec['d20'] // 2)
            rec['d19'] = max(0, cy - rec['d21'] // 2)
        if sel_type in (20, 200):
            rec['d9'] = 1
            rec['d55'] = 1
            if sel_type == 20:
                rec['d53'] = 0
            else:
                rec['d53'] = 4
                rec['d13'] = 4
        _d15_defaults = {200: 64, 20: 64, 10: 0, 16: 300, 110: 80, 15: 64, 5: 0}
        rec['d15'] = _d15_defaults.get(sel_type, 64)
        # 对话颜色: 若该类型在属性面板显示 [28] 对话颜色字段, 给默认色号 16 (§需求4)
        if _DIALOG_COLOR_IDX not in TYPE_SKIP_DWORDS.get(sel_type, set()):
            rec[IDX_DIALOG_COLOR] = 16

        self._data._dirty = True
        self._apply_filter()
        self._refresh_scene_counts()
        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item and int(item.text(0)) == empty_idx:
                self.entity_tree.setCurrentItem(item)
                self.entity_tree.scrollToItem(item)
                self._show_record(rec)
                break
        if sel_scene == self._canvas._vis_scene_id:
            self._canvas._vis_selected = empty_idx
            self._canvas._vis_redraw()

    def _find_empty_slot(self):
        """返回首个空槽的 index; 无空槽返回 None。"""
        for rec in self._data.records:
            if is_empty(rec):
                return rec['index']
        return None

    def _duplicate_entity(self, src_idx, offset=False):
        """复制 src_idx 实体到首个空槽 (§需求2)。
        offset=True 时副本坐标右下偏移一点, 避免与源实体完全重叠 (右键复制用)。
        成功返回新实体 index, 失败返回 None。全过程支持撤销。"""
        if not (0 <= src_idx < len(self._data.records)):
            return None
        src = self._data.records[src_idx]
        empty_idx = self._find_empty_slot()
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"所有{REC_COUNT}条记录均已占用")
            return None
        # 撤销: 记录目标空槽的原始 (空) 状态
        self._canvas._push_undo(f"复制 → #{empty_idx}", [empty_idx])
        dst = self._data.records[empty_idx]
        for di in range(DWORD_COUNT):
            dst[f'd{di}'] = src[f'd{di}']
        dst['index'] = empty_idx
        dst['_has_data'] = True
        if offset:
            OFF = 24  # "旁边一点" 的偏移像素, 右下方向
            dst['d10'] += OFF
            dst['d11'] += OFF
            dst['d18'] += OFF
            dst['d19'] += OFF
        self._data._dirty = True
        self._apply_filter()
        self._refresh_scene_counts()
        self._sync_entity_list_select(empty_idx)
        self._current_param_idx = empty_idx
        self._show_record(dst)
        if dst['d1'] == self._canvas._vis_scene_id:
            self._canvas._vis_selected = empty_idx
            self._canvas._vis_redraw()
        self._vis_info_label.setText(f"已复制: #{src_idx} → #{empty_idx}")
        return empty_idx

    def _delete_entity(self, idx, confirm=False):
        """删除 (清空) 指定实体 (§需求2)。confirm=True 时弹确认框 (菜单/工具栏),
        右键“删除”直接删 (confirm=False)。支持撤销。"""
        if not (0 <= idx < len(self._data.records)):
            return
        if confirm:
            if QMessageBox.question(self, "确认", f"清空实体 #{idx}? (type 设为 0)",
                                    QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
                return
        # 撤销: 记录删除前的完整数据
        self._canvas._push_undo(f"删除 #{idx}", [idx])
        rec = self._data.records[idx]
        for di in range(DWORD_COUNT):
            rec[f'd{di}'] = 0
        rec['_has_data'] = False
        self._data._dirty = True
        self._apply_filter()
        self._refresh_scene_counts()
        if self._current_param_idx == idx:
            self._show_record(rec)
        if self._canvas._vis_selected == idx:
            self._canvas._vis_selected = None
        self._canvas._vis_redraw()
        self._vis_info_label.setText(f"已删除: #{idx}")

    def _undo(self):
        """撤销上一步实体操作 (Ctrl+Z / 编辑菜单 / 画布按钮), 委托画布撤销栈 (§需求3)。"""
        self._canvas._vis_canvas_undo()

    def _copy_record(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            QMessageBox.information(self, "提示", "请先选择记录")
            return
        idx = int(sel[0].text(0))
        self._duplicate_entity(idx, offset=False)

    def _clear_current(self):
        sel = self.entity_tree.selectedItems()
        if not sel:
            return
        idx = int(sel[0].text(0))
        self._delete_entity(idx, confirm=True)

    def _goto_empty(self):
        for rec in self._data.records:
            if is_empty(rec):
                self.filter_type.setCurrentIndex(0)
                self.show_empty_cb.setChecked(True)
                self._apply_filter()
                for i in range(self.entity_tree.topLevelItemCount()):
                    item = self.entity_tree.topLevelItem(i)
                    if item and int(item.text(0)) == rec['index']:
                        self.entity_tree.setCurrentItem(item)
                        self.entity_tree.scrollToItem(item)
                        self._show_record(rec)
                        return
        QMessageBox.information(self, "提示", "无空槽")

    # =========== 可视化 ===========
    def _vis_load_scene(self):
        """加载场景到画布 (PIL 预合成)"""
        sid = self._canvas._vis_scene_id
        self._canvas._vis_gscene.clear()
        self._canvas._vis_entities.clear()
        self._canvas._vis_selected = None
        self._canvas._vis_drag = None
        self._canvas._vis_stop_sel_anim()
        self._canvas._vis_hit_regions = {}
        self._canvas._vis_anim_frame.clear()
        self._canvas._vis_bg_item = None

        # Limit caches
        for cache in (_SPRITE_CACHE, _SHADOW_CACHE, _BLEND_CACHE, _RGBA_CACHE):
            if len(cache) > 300:
                for k in list(cache.keys())[:len(cache) - 300]:
                    del cache[k]
        if not self._data.records:
            return

        # 获取当前预览窗口视口的实际像素大小
        view_w = self._canvas.viewport().width()
        view_h = self._canvas.viewport().height()

        # Background PIL Image + Frame B 逐像素图层 (L1 前景遮挡深度 / L2 地形碰撞类型)
        # 逆向: 背景(Frame A) 与碰撞/前景层(Frame B) 同属一个 GRP section, 一并加载。
        self._canvas._vis_bg_pil = None
        self._canvas._vis_layer1_img = None
        self._canvas._vis_layer2_img = None
        self._canvas._vis_layer_w = 0
        self._canvas._vis_layer_h = 0
        l1 = l2 = None
        lw = lh = 0
        # 优先从内存中的 _sc_grp_pending 加载（MOD 导入后尚未保存的数据）
        if self._data._sc_grp_pending is not None and 0 <= sid < len(self._data._sc_grp_pending):
            section_bytes = self._data._sc_grp_pending[sid]
            if section_bytes:
                try:
                    bg = load_scene_background_from_bytes(section_bytes)
                    if bg:
                        self._canvas._vis_bg_pil = bg
                    l1, l2, lw, lh = load_scene_layers_from_bytes(section_bytes)
                except Exception:
                    pass
        # 回退到从磁盘文件加载 (一次解析 GRP 同时取背景+双层)
        if self._canvas._vis_bg_pil is None and l1 is None and self._data.dat_path:
            d = self._get_game_dir()
            grp_path = os.path.join(d, "SC.GRP")
            idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path):
                try:
                    bg, l1, l2, lw, lh = load_scene_background_and_layers(grp_path, idx_path, sid)
                    if bg:
                        self._canvas._vis_bg_pil = bg
                except Exception:
                    pass
        # 构建图层图像 (L1 供逐像素前景遮挡, L2 供实体深度计算)
        if l1 and lw > 0 and lh > 0:
            self._canvas._vis_layer1_img = make_layer_image(l1, lw, lh)
            self._canvas._vis_layer_w = lw
            self._canvas._vis_layer_h = lh
            if l2:
                self._canvas._vis_layer2_img = make_layer_image(l2, lw, lh)

        ents = [r for r in self._data.records if has_data(r) and r['d1'] == sid]
        sname = scene_name(self._data.tkt_scenes, sid)
        if not ents:
            # 空场景: 如果有背景图也要渲染
            bg_w = self._canvas._vis_bg_pil.width if self._canvas._vis_bg_pil else 0
            bg_h = self._canvas._vis_bg_pil.height if self._canvas._vis_bg_pil else 0
            w = min(max(view_w, MAX_MAP_W, bg_w), 8192)
            h = min(max(view_h, MAX_MAP_H, bg_h), 8192)
            self._canvas._vis_render_scene(ents, w, h)
            self._vis_info_label.setText(f"SC.GRP #{sid}: {sname} — 无实体 (空场景)")
            return
        ents.sort(key=self._canvas._vis_sort_key)

        # 过滤垃圾废弃坐标 (>10000)，防止画布被撑到 8192 导致显卡卡死
        xs = [r['d10'] for r in ents if -10000 < r['d10'] < 10000]
        ys = [r['d11'] for r in ents if -10000 < r['d11'] < 10000]
        if not xs: xs = [0]
        if not ys: ys = [0]
        right = max(r['d18'] + r['d20'] for r in ents if r['d20'] > 0 and -10000 < r['d18'] < 10000) if any(r['d20'] > 0 and -10000 < r['d18'] < 10000 for r in ents) else max(xs)
        bottom = max(r['d19'] + r['d21'] for r in ents if r['d21'] > 0 and -10000 < r['d19'] < 10000) if any(r['d21'] > 0 and -10000 < r['d19'] < 10000 for r in ents) else max(ys)
        # 场景尺寸 = max(视口大小, 实体范围, 背景图尺寸, 最小尺寸)
        bg_w = self._canvas._vis_bg_pil.width if self._canvas._vis_bg_pil else 0
        bg_h = self._canvas._vis_bg_pil.height if self._canvas._vis_bg_pil else 0
        w = min(max(view_w, MAX_MAP_W, max(max(xs), right) + 300, bg_w), 8192)
        h = min(max(view_h, MAX_MAP_H, max(max(ys), bottom) + 300, bg_h), 8192)
        self._canvas._vis_render_scene(ents, w, h)
        self._vis_info_label.setText(f"SC.GRP #{sid}: {sname} — {len(ents)} 个实体")
        if self._canvas._vis_anim_playing:
            self._canvas._vis_start_anim()

    # =========== 数据加载 ===========
    def _load_dir(self):
        d = pick_tks_directory(self)
        if not d:
            return
        mat_p = os.path.join(d, "TKMat.Dat")
        tkt_p = os.path.join(d, "TKT.dat")
        if not os.path.exists(mat_p):
            QMessageBox.warning(self, "文件缺失", f"未找到 TKMat.Dat\n{d}")
            return
        self._data._save_mode = False
        self._data.dat_path = mat_p
        self._data.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        self._reload()

    def _load_save_dir(self):
        """从存档文件 sav.N 加载 TKMat 地图实体数据 (先选游戏目录, 再自动定位 save/)"""
        d = pick_tks_directory(self, "选择 TKS 游戏目录 (含 save 子文件夹)")
        if not d: return
        # 确认选中的是游戏目录 (包含 TKMat.Dat 或 TKT.dat)
        is_game_dir = os.path.exists(os.path.join(d, 'TKMat.Dat')) or os.path.exists(os.path.join(d, 'TKT.dat'))
        if not is_game_dir:
            # 用户可能选了 save/ 子文件夹，尝试向上修正
            parent = os.path.dirname(d.rstrip('/\\'))
            if os.path.exists(os.path.join(parent, 'TKMat.Dat')) or os.path.exists(os.path.join(parent, 'TKT.dat')):
                d = parent  # 自动修正到游戏目录
            else:
                QMessageBox.warning(self, "目录不正确",
                    f"所选目录不是 TKS 游戏目录 (未找到 TKMat.Dat/TKT.dat):\n{d}\n\n"
                    f"请选择包含 TKMat.Dat 和 save/ 文件夹的游戏根目录。")
                return
        game_dir = d
        # 在游戏目录下查找 save 子文件夹
        save_dir = os.path.join(d, 'save')
        if not os.path.exists(save_dir):
            save_dir = d  # 降级: 直接在游戏目录下找
        if not any(os.path.exists(os.path.join(save_dir, f'sav.{s}')) for s in range(1, 10)):
            QMessageBox.warning(self, "未找到存档",
                f"在游戏目录下未找到 save 文件夹或 sav.N 文件:\n{d}")
            return
        # 扫描可用槽位
        slots = []
        for s in range(1, 10):
            sp = os.path.join(save_dir, f'sav.{s}')
            if os.path.exists(sp):
                ip = os.path.join(save_dir, f'{s}.sav')
                summary = ""
                if os.path.exists(ip):
                    try:
                        idx_data = open(ip, 'rb').read()
                        if len(idx_data) >= 28:
                            import datetime as _dt
                            ts = struct.unpack_from('<I', idx_data, 8)[0]
                            dt_str = _dt.datetime.fromtimestamp(ts).strftime('%m/%d %H:%M')
                            gold = struct.unpack_from('<H', idx_data, 6)[0]
                            summary = f"{dt_str} | 金{gold}"
                    except Exception:
                        summary = "(索引异常)"
                slots.append((s, sp, summary))
        if not slots:
            QMessageBox.warning(self, "无可用槽位", "目录中没有存档数据")
            return
        # 槽位选择对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("选择存档槽位 — 加载 TKMat 数据")
        dlg.resize(450, 380)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"存档目录: {save_dir}"))
        table = AdaptiveTableWidget(
            len(slots), 3,
            stretch_columns={2},
            minimum_widths=[50, 150, 90],
        )
        table.setHorizontalHeaderLabels(['槽位', '文件', '摘要'])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, (s, sp, summary) in enumerate(slots):
            table.setItem(row, 0, QTableWidgetItem(str(s)))
            table.setItem(row, 1, QTableWidgetItem(os.path.basename(sp)))
            table.setItem(row, 2, QTableWidgetItem(summary))
        layout.addWidget(table, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(QPushButton("取消", clicked=dlg.reject))
        btn_row.addWidget(QPushButton("打开", clicked=dlg.accept))
        layout.addLayout(btn_row)
        if dlg.exec() != QDialog.Accepted: return
        sel = table.selectedItems()
        if not sel: return
        slot_num = slots[sel[0].row()][0]
        save_path = slots[sel[0].row()][1]
        # 设置存档模式
        self._data._save_mode = True
        self._data._save_path = save_path
        self._data._save_slot = slot_num
        self._data._game_dir = game_dir  # 直接存储游戏目录
        self._data.dat_path = save_path  # DataLoaderThread 从此路径加载附属文件 (TKD/TKDefUnit)
        tkt_p = os.path.join(game_dir, 'TKT.dat')
        self._data.tkt_path = tkt_p if os.path.exists(tkt_p) else None
        # 预加载 TKMat records (从存档 Frame1)
        self.status_var.setText(f"从存档加载 TKMat 数据 (槽位{slot_num})…")
        QApplication.processEvents()
        try:
            self._preloaded_records = load_mat_from_save(save_path)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法从存档读取 TKMat 数据:\n{e}")
            self._data._save_mode = False
            return
        self._reload()
        self.setWindowTitle(f"{format_title('mat_editor')} [存档模式 槽位{slot_num}]")

    def _reload(self):
        if not self._data.dat_path:
            return
        self.status_var.setText("后台高速解析结构中…")
        self._set_edit_enabled(False)
        # 清空贴图引用，防止切换目录时旧缓存残留
        self._ani_jvg = None
        self._cha_jvg = None
        self._cur_jvg = None
        self._update_path()
        # 存档模式下使用 game_dir 加载附属文件，并传入预加载的 TKMat records
        game_dir = self._data._game_dir if self._data._save_mode else os.path.dirname(self._data.dat_path)
        preloaded = getattr(self, '_preloaded_records', None) if self._data._save_mode else None
        self._loader_thread = DataLoaderThread(self._data.dat_path, self._data.tkt_path,
                                                game_dir=game_dir, preloaded_records=preloaded)
        self._loader_thread.finished_load.connect(self._on_load_success)
        self._loader_thread.error_load.connect(self._on_load_error)
        self._loader_thread.start()

    def _on_load_error(self, err_msg):
        """加载报错回调"""
        QMessageBox.critical(self, "加载失败", f"数据解析异常:\n{err_msg}")
        self._data.records = []
        self._set_edit_enabled(True)
        self.status_var.setText("加载失败")

    def _on_load_success(self):
        """加载完毕回调：应用数据并刷新 UI"""
        self.setUpdatesEnabled(False)
        result = self._loader_thread.result_data

        self._data.load_from_result(result)
        self._canvas._undo_stack.clear()  # 载入新数据后旧撤销栈失效, 清空避免误恢复

        # 保存原始快照用于 MOD 导出
        # 注意: defunit_recs 是跳过空记录的紧凑列表, 必须用文件位置对齐的完整列表,
        # 否则 diff 产生的 index 是数组下标而非文件位置, 启动器会写入错误位置
        self._original_mat_records = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self._data.records]
        self._original_defunit_recs = self._du_recs_to_full_fields()

        nonempty = sum(1 for r in self._data.records if has_data(r))
        scenes = set(r['d1'] for r in self._data.records if has_data(r))

        self._update_path()
        self._set_edit_enabled(True)
        self._apply_filter()
        self._vis_populate_scenes()

        # 延迟启动 JVG 贴图加载，让主线程先完成 UI 渲染，避免 GIL 锁竞争
        self.status_var.setText(
            f"{REC_COUNT}条 | 有效{nonempty} | TKMat场景{len(scenes)} | "
            f"SC.GRP {self._data._sc_grp_section_count}区段 (正在后台加载贴图…)")
        QTimer.singleShot(300, self._start_jvg_thread)

        # 自动选中首个有效场景 (静默信号，防止触发无意义的首次重绘)
        if self.scene_tree.topLevelItemCount() > 0:
            first = self.scene_tree.topLevelItem(1 if self.scene_tree.topLevelItemCount() > 1 else 0)
            self.scene_tree.blockSignals(True)
            self.scene_tree.setCurrentItem(first)
            self.scene_tree.blockSignals(False)
            sid = int(first.text(0))
            self._canvas._vis_scene_id = sid
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_load_scene()

        # 所有初始化完成后才重置脏标记，防止 UI 刷新链路误触
        self._data._dirty = False
        self._script_dirty = False
        self.setUpdatesEnabled(True)

    def _start_jvg_thread(self):
        """延迟触发的后台资源加载线程 (贴图+TKD+物品)"""
        game_dir = self._data._game_dir if self._data._save_mode else None
        self._jvg_thread = JvgLoaderThread(self._data.dat_path, self._data.tkt_all, game_dir=game_dir)
        self._jvg_thread.finished_jvg.connect(self._on_jvg_success)
        self._jvg_thread.start()

    def _on_jvg_success(self):
        """后台资源加载完毕回调 (贴图+TKD+物品)"""
        result = self._jvg_thread.jvg_result
        # 接收贴图
        self._ani_jvg = result.get('ani_jvg')
        self._cha_jvg = result.get('cha_jvg')
        self._cur_jvg = result.get('cur_jvg')

        # 接收 TKD 脚本与物品数据
        if 'tkd_defines' in result:
            self._data.tkd_defines = result['tkd_defines']
            self._data.tkd_header = result.get('tkd_header', '')
            self._data.tkd_define_map = result.get('tkd_define_map', {})
            self._data.item_names = result.get('item_names', {})
            # 保存 TKD 原始快照用于 MOD 导出 (dict: {define_id_str: full_text})
            self._original_tkd_defines = {
                str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                for dd in self._data.tkd_defines
            }
            # 同步刷新脚本删除检测基线 (以刚载入的脚本为基准)
            self._snapshot_script_baseline()
            # 刷新当前脚本预览
            if self._current_edit_define_id is not None:
                self._update_line_preview()

        self._update_path()
        cur = self.status_var.text()
        self.status_var.setText(cur.replace("(正在后台加载贴图…)", "(全部资源就绪)"))
        # 触发重绘让实体显示彩色立绘
        if hasattr(self, '_data') and self._data.records:
            self._canvas._vis_redraw()

    def _vis_populate_scenes(self):
        self.scene_tree.setUpdatesEnabled(False)
        self.scene_tree.blockSignals(True)
        self.scene_tree.clear()
        if not self._data.records:
            self.scene_tree.blockSignals(False)
            self.scene_tree.setUpdatesEnabled(True)
            return
        smap = defaultdict(list)
        for r in self._data.records:
            if has_data(r) and r['d1'] >= 0:
                smap[r['d1']].append(r['index'])
        total_scenes = max(self._data._sc_grp_section_count, max(smap.keys()) + 1 if smap else 0)
        combo_vals = []
        scene_items = []
        for sid in range(total_scenes):
            sname = scene_name(self._data.tkt_scenes, sid)
            cnt = len(smap.get(sid, []))
            is_virtual = self._data._sc_grp_section_count > 0 and sid >= self._data._sc_grp_section_count
            display_name = f"{sname} [虚拟场景]" if is_virtual else sname
            item = QTreeWidgetItem([str(sid), display_name, str(cnt)])
            if is_virtual:
                for c in range(3):
                    item.setForeground(c, QColor("#3366cc"))
            scene_items.append(item)
            combo_vals.append(f"{sid}: {sname} ({cnt}实体)")
        self.scene_tree.addTopLevelItems(scene_items)
        self.scene_tree.blockSignals(False)
        self.scene_tree.setUpdatesEnabled(True)
        # 阻止 combo 信号，避免 clear/addItems 触发 _on_vis_combo_select 导致 _vis_scene_id 被意外修改
        self._vis_scene_combo.blockSignals(True)
        self._vis_scene_combo.clear()
        self._vis_scene_combo.addItems(combo_vals)
        self._vis_scene_combo.blockSignals(False)

    def _refresh_scene_counts(self):
        """重建场景列表/下拉框以刷新各场景「实体」计数, 并恢复当前场景的选中态。
        新增/复制/删除/撤销实体后调用 — 恢复选中时阻断信号, 避免误触发场景切换
        (进而清空撤销栈)。"""
        cur_sid = self._canvas._vis_scene_id
        self._vis_populate_scenes()
        self.scene_tree.blockSignals(True)
        for i in range(self.scene_tree.topLevelItemCount()):
            item = self.scene_tree.topLevelItem(i)
            if item and int(item.text(0)) == cur_sid:
                self.scene_tree.setCurrentItem(item)
                self.scene_tree.scrollToItem(item)
                break
        self.scene_tree.blockSignals(False)
        self._vis_scene_combo.blockSignals(True)
        for i in range(self._vis_scene_combo.count()):
            if self._vis_scene_combo.itemText(i).startswith(f"{cur_sid}:"):
                self._vis_scene_combo.setCurrentIndex(i)
                break
        self._vis_scene_combo.blockSignals(False)

    # =========== 场景列表/实体列表 ===========
    def _vis_scene_tree_to_combo(self):
        """Sync scene tree selection to combo"""
        pass

    # =========== 脚本删除检测 (§防止切换实体误删脚本) ===========
    def _snapshot_script_baseline(self):
        """记录当前各 DEFINE 正文快照 (define_id_str → 去空白正文), 作为脚本删除检测基线。

        在载入完成、MOD 导入、每次保存成功后刷新, 使检测反映"相对上次落盘/载入状态"
        的脚本内容丢失, 避免对已知状态重复告警。"""
        self._script_baseline = {
            str(dd['define_id']): '\n'.join(dd.get('body_lines', [])).strip()
            for dd in self._data.tkd_defines
        }

    def _detect_deleted_scripts(self):
        """检测相对基线被删除或清空的脚本, 返回 [(define_id_str, entity_id, comment), ...]。

        判定为"删除/清空": 基线中该 DEFINE 正文非空, 而当前该 DEFINE 已不存在,
        或其正文已被清空 (常见于切换实体等操作导致的误删)。
        调用方应先 _save_editor_to_define() 提交编辑器未回写内容, 以免误报。"""
        baseline = getattr(self, '_script_baseline', None)
        if not baseline:
            return []
        current = {str(dd['define_id']): dd for dd in self._data.tkd_defines}
        result = []
        for did, orig_sig in baseline.items():
            if not orig_sig:
                continue  # 基线本就是空脚本, 不计入
            cur = current.get(did)
            cur_sig = '\n'.join(cur.get('body_lines', [])).strip() if cur else ''
            if cur_sig:
                continue  # 仍有内容 (可能被修改, 但未被删除)
            try:
                entity_id = int(did) >> 16
            except ValueError:
                entity_id = -1
            result.append((did, entity_id, cur.get('comment', '') if cur else ''))
        return result

    def _format_deleted_scripts(self, deleted, limit=15):
        """将删除脚本列表格式化为多行文本 (超出 limit 折叠计数)。"""
        lines = []
        for did, entity_id, comment in deleted[:limit]:
            tail = f" — {comment}" if comment else ""
            eid = f"实体 #{entity_id}" if entity_id >= 0 else "全局/未知实体"
            lines.append(f"  • DEFINE {did} ({eid}){tail}")
        if len(deleted) > limit:
            lines.append(f"  … 其余 {len(deleted) - limit} 个未列出")
        return '\n'.join(lines)

    def _confirm_with_script_deletion(self, title, base_msg):
        """确认对话框: 若检测到脚本被删除/清空, 先在弹窗内醒目提醒再请用户确认。

        返回 True 表示用户确认继续 (保存); False 表示取消。
        无脚本删除时行为等同普通 Ok/Cancel 确认框。"""
        deleted = self._detect_deleted_scripts()
        if not deleted:
            return QMessageBox.question(self, title, base_msg,
                                        QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok
        warn = (f"⚠ 检测到 {len(deleted)} 个脚本相对上次保存/载入已被删除或清空:\n\n"
                f"{self._format_deleted_scripts(deleted)}\n\n"
                f"这可能是切换实体等操作导致的误删。若非本意, 请点「取消」返回检查;\n"
                f"确认放弃这些脚本内容请点「确定」。\n"
                f"────────────────────\n"
                f"{base_msg}")
        box = QMessageBox(QMessageBox.Warning, title, warn,
                          QMessageBox.Ok | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Ok

    # =========== 保存 ===========
    def _save(self):
        if self._data._save_mode:
            self._save_to_save_file()
            return
        d = os.path.dirname(self._data.dat_path) if self._data.dat_path else None
        if not d:
            self._save_as()
            return
        self._save_editor_to_define()
        du_p = os.path.join(d, "TKDefUnit.Dat")
        tkd_p = os.path.join(d, "TKD.dat")
        has_sc_pending = self._data._sc_grp_pending is not None
        files_msg = f"TKMat.Dat: {self._data.dat_path}\nTKDefUnit.Dat: {du_p}\nTKD.dat: {tkd_p}"
        if has_sc_pending:
            files_msg += f"\nSC.GRP: {os.path.join(d, 'SC.GRP')}\nSC.IDX: {os.path.join(d, 'SC.IDX')}"
        file_count = 5 if has_sc_pending else 3
        if not self._confirm_with_script_deletion(f"确认保存 — 将写入以下 {file_count} 个文件", files_msg):
            return
        errors = []
        try:
            save_mat(self._data.dat_path, self._data.records)
        except Exception as e:
            errors.append(f"TKMat.Dat: {e}")
        try:
            save_defunit(du_p, self._data.defunit_recs)
        except Exception as e:
            errors.append(f"TKDefUnit.Dat: {e}")
        try:
            tkd_text = rebuild_text(self._data.tkd_defines, self._data.tkd_header)
            save_tkd(tkd_p, tkd_text)
        except Exception as e:
            errors.append(f"TKD.dat: {e}")
        # 保存待写入的 SC.GRP/SC.IDX
        if has_sc_pending:
            try:
                grp_path = os.path.join(d, "SC.GRP")
                idx_path = os.path.join(d, "SC.IDX")
                offsets = []
                grp_data = bytearray()
                for section in self._data._sc_grp_pending:
                    offsets.append(len(grp_data))
                    grp_data.extend(section)
                offsets.append(len(grp_data))  # 末尾哨兵
                with open(grp_path, 'wb') as f:
                    f.write(bytes(grp_data))
                with open(idx_path, 'wb') as f:
                    for off in offsets:
                        f.write(struct.pack('<I', off))
                self._data._sc_grp_pending = None  # 已写入，清除待保存标记
            except Exception as e:
                errors.append(f"SC.GRP/IDX: {e}")
        if errors:
            QMessageBox.critical(self, "保存失败", '\n'.join(errors))
        else:
            self._data._dirty = False
            self._script_dirty = False
            self._snapshot_script_baseline()  # 保存成功后刷新基线, 后续删除检测以此为准
            self.status_var.setText(f"已保存 — {file_count} 个文件")
            QMessageBox.information(self, "保存成功", f"已成功保存 {file_count} 个文件。")

    def _save_as(self):
        if self._data._save_mode:
            QMessageBox.information(self, "提示", "存档模式下不支持另存为")
            return
        fp, _ = QFileDialog.getSaveFileName(self, "另存 TKMat.Dat", "", "DAT 文件 (*.Dat *.dat);;所有文件 (*.*)")
        if not fp:
            return
        self._data.dat_path = fp
        self._save()

    def _save_to_save_file(self):
        """存档模式下保存 TKMat 数据回 sav.N，TKDefUnit/TKD 写入游戏目录"""
        if not self._data._save_path or not self._data.records:
            QMessageBox.information(self, "提示", "无存档数据")
            return
        self._save_editor_to_define()  # 先提交编辑器未回写内容, 保证保存与删除检测一致
        game_dir = self._data._game_dir or os.path.dirname(os.path.dirname(self._data._save_path))
        du_p = os.path.join(game_dir, "TKDefUnit.Dat")
        tkd_p = os.path.join(game_dir, "TKD.dat")
        files_msg = (f"存档 TKMat: {self._data._save_path} (槽位 {self._data._save_slot})\n"
                     f"TKDefUnit.Dat: {du_p}\nTKD.dat: {tkd_p}")
        has_sc = self._data._sc_grp_pending is not None
        if has_sc:
            files_msg += f"\nSC.GRP/SC.IDX: {game_dir}"
        if not self._confirm_with_script_deletion("确认保存到存档", files_msg):
            return
        errors = []
        try:
            save_mat_to_save(self._data._save_path, self._data.records)
        except Exception as e:
            errors.append(f"存档 TKMat: {e}")
        try:
            save_defunit(du_p, self._data.defunit_recs)
        except Exception as e:
            errors.append(f"TKDefUnit.Dat: {e}")
        try:
            tkd_text = rebuild_text(self._data.tkd_defines, self._data.tkd_header)
            save_tkd(tkd_p, tkd_text)
        except Exception as e:
            errors.append(f"TKD.dat: {e}")
        if has_sc:
            try:
                grp_path = os.path.join(game_dir, "SC.GRP")
                idx_path = os.path.join(game_dir, "SC.IDX")
                offsets = []
                grp_data = bytearray()
                for section in self._data._sc_grp_pending:
                    offsets.append(len(grp_data))
                    grp_data.extend(section)
                offsets.append(len(grp_data))
                with open(grp_path, 'wb') as f: f.write(bytes(grp_data))
                with open(idx_path, 'wb') as f:
                    for off in offsets: f.write(struct.pack('<I', off))
                self._data._sc_grp_pending = None
            except Exception as e:
                errors.append(f"SC.GRP/IDX: {e}")
        if errors:
            QMessageBox.critical(self, "保存失败", '\n'.join(errors))
        else:
            self._data._dirty = False
            self._script_dirty = False
            self._snapshot_script_baseline()  # 保存成功后刷新基线, 后续删除检测以此为准
            self.status_var.setText(f"已保存到存档 {self._data._save_path} 槽位{self._data._save_slot}")
            QMessageBox.information(self, "保存成功", f"已保存到存档 {self._data._save_path} 槽位 {self._data._save_slot}。")

    def _du_recs_to_full_fields(self):
        """将 defunit_recs 转换为与文件位置对齐的完整字段列表。

        DataLoaderThread 加载 TKDefUnit.Dat 时跳过了 f0==0 and f1==0 的空记录,
        导致 self._data.defunit_recs 是紧凑列表 (数组下标 ≠ 文件位置)。
        而 diff_records 按数组下标比较, 启动器 _merge_dat_file 又按下标 * rec_size
        写入文件。若直接用紧凑列表做 diff, 导出的 index 是数组下标而非文件位置,
        会导致启动器写入错误位置, 破坏 DefUnit 数据。

        此方法构建长度 DEFUNIT_REC_COUNT 的完整列表, 用 rec['index'] (真实文件位置)
        作为下标, 缺失位置填 [0]*8, 确保 diff 产生的 index 即为真实文件位置。
        """
        full = [[0] * 8 for _ in range(DEFUNIT_REC_COUNT)]
        for r in self._data.defunit_recs:
            idx = r.get('index', -1)
            if 0 <= idx < DEFUNIT_REC_COUNT:
                full[idx] = [r.get(f'f{i}', 0) for i in range(8)]
        return full

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件 (TKMat + TKDefUnit + TKD 三文件联动)"""
        if not self._data.records or not hasattr(self, '_original_mat_records'):
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        data_files = {}
        components = []

        # TKMat.Dat 差异
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self._data.records]
        mat_diff = diff_records(self._original_mat_records, current_mat, DWORD_COUNT, len(self._original_mat_records))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(self._data.dat_path) if self._data.dat_path else "0x00000000"
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(self._original_mat_records), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, '_original_defunit_recs') and hasattr(self, '_data'):
            current_du = self._du_recs_to_full_fields()
            du_diff = diff_records(self._original_defunit_recs, current_du, 8, len(self._original_defunit_recs))
            if du_diff['modified'] or du_diff['appended']:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=len(self._original_defunit_recs), original_crc32=crc, diff_result=du_diff)
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, '_original_tkd_defines') and hasattr(self, '_data'):
            self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
            current_tkd = {
                str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                for dd in self._data.tkd_defines
            }
            tkd_diff = diff_text_defines(self._original_tkd_defines, current_tkd)
            if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} ({len(components)}文件, {total}处变更)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n包含 {len(components)} 个数据文件")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对 (TKMat + TKDefUnit + TKD)"""
        if not self._data.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 先将编辑器中当前 DEFINE 的改动回写, 确保预览统计与实际导出一致
        self._save_editor_to_define()

        # 预构建当前 TKMat 字段
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self._data.records]

        def _compute_stats(ref_dir):
            ref_mat = load_reference_dat_fields(ref_dir, "TKMat.Dat",
                rec_size=REC_SIZE, field_count=DWORD_COUNT, field_fmt='i', use_lzss=False)
            if ref_mat is None:
                return {"valid": False, "error": "目录中未找到 TKMat.Dat"}
            mat_diff = diff_records(ref_mat, current_mat, DWORD_COUNT, len(ref_mat))
            targets = []
            if mat_diff['modified'] or mat_diff['appended']:
                targets.append({"name": "TKMat.dat",
                    "modified": len(mat_diff['modified']),
                    "appended": len(mat_diff['appended']),
                    "deleted": 0})
            # TKDefUnit.dat (如果可加载)
            du_path = os.path.join(ref_dir, "TKDefUnit.Dat")
            if os.path.isfile(du_path) and hasattr(self, '_data'):
                try:
                    ref_du = load_reference_dat_fields(ref_dir, "TKDefUnit.Dat",
                        rec_size=DEFUNIT_REC_SIZE, field_count=8, field_fmt='H', use_lzss=False)
                    if ref_du is not None:
                        cur_du = self._du_recs_to_full_fields()
                        du_diff = diff_records(ref_du, cur_du, 8, len(ref_du))
                        if du_diff['modified'] or du_diff['appended']:
                            targets.append({"name": "TKDefUnit.dat",
                                "modified": len(du_diff['modified']),
                                "appended": len(du_diff['appended']),
                                "deleted": 0})
                except Exception:
                    pass
            # TKD.dat 脚本差异 (与实际导出逻辑保持一致, 否则预览会漏报脚本改动)
            ref_tkd_path = os.path.join(ref_dir, "TKD.dat")
            if os.path.isfile(ref_tkd_path) and hasattr(self, '_data'):
                try:
                    ref_tkd_text = load_tkd(ref_tkd_path)
                    ref_tkd_defs, _ = parse_defines(ref_tkd_text)
                    ref_tkd_map = {
                        str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                        for dd in ref_tkd_defs
                    }
                    cur_tkd_map = {
                        str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                        for dd in self._data.tkd_defines
                    }
                    tkd_diff = diff_text_defines(ref_tkd_map, cur_tkd_map)
                    if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                        targets.append({"name": "TKD.dat",
                            "modified": len(tkd_diff['modified']),
                            "appended": len(tkd_diff['appended']),
                            "deleted": len(tkd_diff['deleted'])})
                except Exception:
                    pass
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=self._get_game_dir(),
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        # 加载参考目录中的 TKMat.Dat
        ref_mat = load_reference_dat_fields(ref_dir, "TKMat.Dat",
            rec_size=REC_SIZE, field_count=DWORD_COUNT, field_fmt='i', use_lzss=False)
        if ref_mat is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKMat.Dat")
            return

        data_files = {}
        components = []

        # TKMat.Dat 差异
        mat_diff = diff_records(ref_mat, current_mat, DWORD_COUNT, len(ref_mat))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(os.path.join(ref_dir, "TKMat.Dat"))
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(ref_mat), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, '_data'):
            ref_du = load_reference_dat_fields(ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8, field_fmt='H', use_lzss=False)
            if ref_du is not None:
                current_du = self._du_recs_to_full_fields()
                du_diff = diff_records(ref_du, current_du, 8, len(ref_du))
                if du_diff['modified'] or du_diff['appended']:
                    crc = compute_crc32(os.path.join(ref_dir, "TKDefUnit.Dat"))
                    du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE,
                        field_type="uint16", field_count=8, original_count=len(ref_du), original_crc32=crc, diff_result=du_diff)
                    data_files["data/TKDefUnit.dat.json"] = du_json
                    components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, '_data'):
            ref_tkd_path = os.path.join(ref_dir, "TKD.dat")
            if os.path.exists(ref_tkd_path):
                self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
                ref_tkd_text = load_tkd(ref_tkd_path)
                ref_tkd_defs, _ = parse_defines(ref_tkd_text)
                ref_tkd_map = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in ref_tkd_defs
                }
                current_tkd = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in self._data.tkd_defines
                }
                tkd_diff = diff_text_defines(ref_tkd_map, current_tkd)
                if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                    crc = compute_crc32(ref_tkd_path)
                    tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                    data_files["data/TKD.dat.json"] = tkd_json
                    components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n包含 {len(components)} 个数据文件, {total} 处变更")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_scene_as_tksmod(self):
        """导出当前场景为 .tksmod MOD 文件 — 直接导出选中场景全部数据（不判断差异）"""
        if not self._data.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        sid = self._canvas._vis_scene_id
        if sid < 0:
            QMessageBox.warning(self, "无效场景", "请先在可视化面板中选择一个场景")
            return

        # ── 1. 筛选属于本场景的实体 ──
        scene_entity_indices = [i for i, r in enumerate(self._data.records)
                                if has_data(r) and r['d1'] == sid]
        if not scene_entity_indices:
            QMessageBox.warning(self, "空场景", f"场景 {sid} 无实体数据")
            return

        # ── 2. 追踪 DefUnit 链 ──
        def find_du(idx):
            return next((r for r in self._data.defunit_recs if r['index'] == idx), None)

        all_defunit_indices = set()

        def collect_chain(head_idx):
            cur = head_idx
            visited = set()
            while cur >= 0 and cur not in visited:
                visited.add(cur)
                du = find_du(cur)
                if du is None:
                    break
                all_defunit_indices.add(cur)
                nxt = du.get('f6', 0)
                if nxt == 0 or nxt in visited:
                    break
                cur = nxt

        for eidx in scene_entity_indices:
            rec = self._data.records[eidx]
            for chain_di, max_di in [(39, 30), (40, 31), (41, 32)]:
                head = rec.get(f'd{chain_di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if head > 0 and mx > 0:
                    collect_chain(head)

        # ── 3. 追踪 TKD DEFINE 块 ──
        scene_define_ids = set()
        for du_idx in all_defunit_indices:
            du = find_du(du_idx)
            if du:
                did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                if did > 0:
                    scene_define_ids.add(str(did))

        # ── 4. 弹出 MOD 元数据对话框 ──
        sname = scene_name(self._data.tkt_scenes, sid).replace('/', '_').replace('\\', '_')
        defaults = getattr(self, '_last_mod_metadata', None) or {}
        if not defaults.get('id'):
            defaults['id'] = f"scene_{sid}_{sname}"
        if not defaults.get('name'):
            defaults['name'] = f"场景 {sname} (ID={sid})"
        if not defaults.get('type'):
            defaults['type'] = 'story'
        dlg = ModMetadataDialog(self, defaults)
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # ── 5. 直接导出 TKMat.Dat 场景实体（全量字段，不做差异比对）──
        data_files = {}
        components = []

        mat_entries = []
        for eidx in scene_entity_indices:
            rec = self._data.records[eidx]
            # 导出所有字段（含零值），确保导入时能完整覆盖目标槽位
            fields = {}
            for fi in range(DWORD_COUNT):
                fields[f"f{fi}"] = rec.get(f'd{fi}', 0)
            mat_entries.append({"index": eidx, "fields": fields})

        if mat_entries:
            crc = compute_crc32(self._data.dat_path) if self._data.dat_path else "0x00000000"
            original_count = len(self._data.records)
            mat_json = build_data_diff_json(
                target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=original_count,
                original_crc32=crc, diff_result={'modified': mat_entries, 'appended': []})
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # ── 6. 直接导出 TKDefUnit.Dat（全量字段，不做差异比对）──
        if hasattr(self, '_data') and all_defunit_indices:
            du_entries = []
            for du_idx in sorted(all_defunit_indices):
                du = find_du(du_idx)
                if du:
                    # 导出所有字段（含零值）
                    fields = {}
                    for fi in range(8):
                        fields[f"f{fi}"] = du.get(f'f{fi}', 0)
                    du_entries.append({"index": du_idx, "fields": fields})

            if du_entries:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                original_du_count = len(self._data.defunit_recs)
                du_json = build_data_diff_json(
                    target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=original_du_count,
                    original_crc32=crc, diff_result={'modified': du_entries, 'appended': []})
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # ── 7. 直接导出 TKD.dat 脚本（全量内容，不做差异比对）──
        if hasattr(self, '_data') and scene_define_ids:
            self._save_editor_to_define()
            tkd_modified = {}
            for dd in self._data.tkd_defines:
                did_str = str(dd['define_id'])
                if did_str in scene_define_ids:
                    tkd_modified[did_str] = '\r\n'.join([dd['header_line']] + dd['body_lines'])

            if tkd_modified:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc,
                    diff_result={'modified': tkd_modified, 'appended': [], 'deleted': []})
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        # ── 8. 直接导出 SC.GRP 场景区段（不做差异比对）──
        if self._data.dat_path:
            game_dir = self._get_game_dir()
            grp_path = os.path.join(game_dir, "SC.GRP")
            idx_path = os.path.join(game_dir, "SC.IDX")
            if os.path.exists(grp_path) and os.path.exists(idx_path):
                try:
                    with open(idx_path, 'rb') as f:
                        idata = f.read()
                    offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                    if sid < len(offs):
                        start = offs[sid]
                        end = offs[sid + 1] if sid + 1 < len(offs) else os.path.getsize(grp_path)
                        with open(grp_path, 'rb') as f:
                            f.seek(start)
                            section_data = f.read(end - start)
                        if section_data:
                            total_sections = len(offs) - 1 if len(offs) > 1 else len(offs)
                            sc_diff = {
                                'modified': [{'index': sid, 'data_b64': base64.b64encode(section_data).decode('ascii')}],
                                'appended': [],
                                'deleted_indices': [],
                            }
                            crc = compute_crc32(grp_path)
                            sc_json = build_block_diff_json(
                                target="SC.GRP", block_type="grp_section",
                                original_count=total_sections,
                                original_crc32=crc, diff_result=sc_diff)
                            data_files["data/SC.GRP.json"] = sc_json
                            components.append({"file": "data/SC.GRP.json", "target": "SC.GRP"})
                except Exception:
                    pass

        # ── 9. 最终打包 ──
        if not data_files:
            QMessageBox.information(self, "无数据",
                f"场景 {sid} 未收集到任何可导出数据。")
            return

        # 在 mod.json 中附加 scene_scope 字段
        metadata['scene_scope'] = [sid]
        mod_json = generate_mod_json(metadata, components)
        mod_json['scene_scope'] = [sid]
        mod_json['scene_name'] = scene_name(self._data.tkt_scenes, sid)

        fp, _ = QFileDialog.getSaveFileName(
            self, "导出场景为 MOD",
            f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod",
            "TKS MOD (*.tksmod);;所有文件 (*.*)")
        if not fp:
            return
        try:
            pack_tksmod(fp, mod_json, data_files)
            n_mat = len(mat_entries)
            n_du = len(data_files.get('data/TKDefUnit.dat.json', {}).get('modified', []))
            n_tkd = len(data_files.get('data/TKD.dat.json', {}).get('modified', {}))
            has_sc = 'data/SC.GRP.json' in data_files
            summary = (f"场景 {scene_name(self._data.tkt_scenes, sid)} (ID={sid})\n"
                       f"实体: {n_mat} 条\n"
                       f"DefUnit: {n_du} 条\n"
                       f"脚本: {n_tkd} 块\n"
                       f"SC.GRP: {'包含' if has_sc else '无'}\n\n"
                       f"已保存到:\n{fp}")
            self.status_var.setText(f"已导出场景 MOD: {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", summary)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    @staticmethod
    def _extract_define_id_from_text(text: str) -> str:
        """从 DEFINE 块文本中提取 define_id 字符串"""
        for line in text.split('\n'):
            stripped = line.strip().rstrip('\r')
            if stripped.startswith('DEFINE') and not stripped.startswith('//'):
                parts = stripped.split(None, 2)
                if len(parts) >= 2:
                    return parts[1]
        return ''

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器 (TKMat + TKDefUnit + TKD 三文件联动)"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        # 检查是否包含相关数据
        targets = info.get("targets", [])
        has_mat = "TKMat.Dat" in targets
        has_du = "TKDefUnit.Dat" in targets
        has_tkd = "TKD.dat" in targets
        has_sc = "SC.GRP" in targets
        if not has_mat and not has_du and not has_tkd and not has_sc:
            QMessageBox.warning(self, "不兼容",
                "此 MOD 不包含 TKMat/TKDefUnit/TKD/SC.GRP 的数据\n\n"
                f"包含的数据: {', '.join(targets)}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=self._get_game_dir())
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        imported_parts = []

        # 导入 TKMat.Dat
        if has_mat:
            mod_json, mat_records = import_tksmod_records(
                fp, ref_dir, "TKMat.Dat",
                rec_size=REC_SIZE, field_count=DWORD_COUNT,
                field_fmt='i', use_lzss=False
            )
            if mat_records is not None:
                new_records = []
                for i, fields in enumerate(mat_records):
                    rec = {'index': i}
                    for di in range(DWORD_COUNT):
                        rec[f'd{di}'] = fields[di] if di < len(fields) else 0
                    rec['_has_data'] = any(rec[f'd{di}'] for di in range(DWORD_COUNT))
                    new_records.append(rec)
                self._data.records = new_records
                self._original_mat_records = [list(row) for row in mat_records]
                imported_parts.append(f"TKMat ({len(mat_records)}条)")

        # 导入 TKDefUnit.Dat
        if has_du:
            _, du_records = import_tksmod_records(
                fp, ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8,
                field_fmt='H', use_lzss=False
            )
            if du_records is not None and hasattr(self, '_data'):
                new_du = []
                for i, fields in enumerate(du_records):
                    rec = {'index': i}
                    for fi in range(8):
                        rec[f'f{fi}'] = fields[fi] if fi < len(fields) else 0
                    new_du.append(rec)
                self._data.defunit_recs = new_du
                self._original_defunit_recs = [list(row) for row in du_records]
                imported_parts.append(f"TKDefUnit ({len(du_records)}条)")

        # 导入 TKD.dat
        if has_tkd:
            _, defines = import_tksmod_text_defines(fp, ref_dir)
            if defines is not None and hasattr(self, '_data'):
                # 将 defines dict 转化为编辑器内部 tkd_defines 格式
                new_tkd = []
                for did_str, content in sorted(defines.items(),
                        key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    lines = content.split('\r\n') if '\r\n' in content else content.split('\n')
                    header_line = lines[0] if lines else ''
                    body_lines = lines[1:] if len(lines) > 1 else []
                    new_tkd.append({
                        'define_id': int(did_str) if did_str.isdigit() else 0,
                        'header_line': header_line,
                        'body_lines': body_lines,
                    })
                self._data.tkd_defines = new_tkd
                self._data.tkd_define_map = {dd['define_id']: dd for dd in new_tkd}
                self._original_tkd_defines = dict(defines)
                imported_parts.append(f"TKD ({len(new_tkd)}块)")
                # 刷新脚本编辑器
                self._current_edit_define_id = None

        # 导入 SC.GRP（只存入内存，等用户保存时才写入文件）
        if has_sc:
            # 先加载原始块列表，再应用diff
            from editor_utils.mod_exporter import load_grp_raw_sections
            ref_sc_path = os.path.join(ref_dir, "SC.GRP")
            sc_blocks = load_grp_raw_sections(ref_sc_path)
            if sc_blocks is not None:
                # 检查 scene_scope 中是否有超出原始范围的场景索引
                scene_scope = info.get('scene_scope', [])
                if scene_scope:
                    max_idx = max(scene_scope)
                    # 扩展 sc_blocks 数组以容纳最大索引
                    while len(sc_blocks) <= max_idx:
                        sc_blocks.append(b'')  # 空区段占位

                # 现在应用 diff
                import base64 as b64
                import json
                import zipfile
                with zipfile.ZipFile(fp, 'r') as zf:
                    mod_json = json.loads(zf.read('mod.json'))
                    sc_diff_data = None
                    for comp in mod_json.get('components', []):
                        if comp.get('target') == 'SC.GRP':
                            internal = comp.get('file', '')
                            if internal:
                                sc_diff_data = json.loads(zf.read(internal))
                                break

                if sc_diff_data:
                    for entry in sc_diff_data.get('modified', []):
                        idx = entry.get('index', -1)
                        data_b64 = entry.get('data_b64', '')
                        if 0 <= idx < len(sc_blocks) and data_b64:
                            sc_blocks[idx] = b64.b64decode(data_b64)

                self._data._sc_grp_pending = sc_blocks
                self._data._sc_grp_section_count = len(sc_blocks)
                imported_parts.append(f"SC.GRP ({len(sc_blocks)}区段, 待保存)")

        if not imported_parts:
            QMessageBox.warning(self, "导入失败",
                "无法导入任何数据。\n请确认参考目录中包含有效的游戏文件")
            return

        self._data._dirty = bool(has_sc)  # 有 SC.GRP 待保存则标记为 dirty
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self._vis_populate_scenes()

        # 自动跳转到导入的场景 (scene_scope)
        scene_scope = info.get('scene_scope', [])
        if scene_scope:
            target_sid = scene_scope[0]
        else:
            target_sid = self._canvas._vis_scene_id  # 保持原场景

        if target_sid is not None and target_sid >= 0:
            self._canvas._vis_scene_id = target_sid
            # 同步 combo 和 tree 的选中状态（阻止信号避免触发 _on_vis_combo_select）
            self._vis_scene_combo.blockSignals(True)
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{target_sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_scene_combo.blockSignals(False)
            self.scene_tree.blockSignals(True)
            for i in range(self.scene_tree.topLevelItemCount()):
                item = self.scene_tree.topLevelItem(i)
                if item and item.text(0) == str(target_sid):
                    self.scene_tree.setCurrentItem(item)
                    break
            self.scene_tree.blockSignals(False)

        self._vis_load_scene()
        # 以导入后的脚本状态作为新的删除检测基线, 避免把本次导入误判为脚本删除
        self._snapshot_script_baseline()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{', '.join(imported_parts)}")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"导入内容: {', '.join(imported_parts)}\n\n"
            f"您现在可以继续编辑并重新导出。")

    # =========== 脚本编辑 ===========
    def _save_editor_to_define(self):
        if self._current_edit_define_id is None:
            return
        text = self.script_text.toPlainText()
        d = self._data.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            d = {'define_id': self._current_edit_define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': [], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {self._current_edit_define_id}'}
            for line in text.split('\n'):
                s = line.strip()
                if s.startswith('};'):
                    d['comment'] = s[2:].replace(' end', '').strip()
                    break
            self._data.tkd_defines.append(d)
            self._data.tkd_define_map[self._current_edit_define_id] = d
        d['body_lines'] = text.split('\n')
        for line in reversed(d['body_lines']):
            s = line.strip()
            if s.startswith('};'):
                d['comment'] = s[2:].replace(' end', '').strip()
                break

    def _load_define_to_editor(self, define_id):
        self._current_edit_define_id = define_id
        self.script_text.setReadOnly(False)
        # 阻止信号，避免 setPlainText 触发 _on_script_edit
        self.script_text.blockSignals(True)
        self.script_text.clear()
        d = self._data.tkd_define_map.get(define_id)
        if d:
            self.script_text.setPlainText('\n'.join(d.get('body_lines', [])))
            comment = d.get('comment', '')
            self.script_info_lbl.setText(f"DEFINE {define_id}" + (f" — {comment}" if comment else ""))
        else:
            self.script_text.setPlainText('{\nEnd(0)\n}; end\n')
            self.script_info_lbl.setText(f"DEFINE {define_id} (新建)")
        self.script_text.blockSignals(False)
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._script_dirty = False

    def _clear_script_editor(self):
        self._save_editor_to_define()
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self.script_preview.clear()
        self._current_edit_define_id = None
        self.script_info_lbl.setText("(未选中 DEFINE)")

    def _on_script_edit(self):
        self._script_dirty = True
        self._data._dirty = True  # 脚本编辑同属待保存修改, 防止切换链条目后丢失"未保存"判定 (§修复)
        if self._edit_debounce:
            self._edit_debounce.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._do_script_update)
        timer.start(150)
        self._edit_debounce = timer

    def _do_script_update(self):
        self._apply_syntax_highlight()

    def _apply_syntax_highlight(self):
        """语法高亮 — 逻辑对应 mat_editor.py _apply_syntax_highlight。
        实际逐行高亮由 ScriptSyntaxHighlighter 自动完成, 此处触发一次整文档重涂。"""
        if hasattr(self, '_script_highlighter') and self._script_highlighter:
            # rehighlight() 会触发 QPlainTextEdit.textChanged (Qt 行为), 必须屏蔽信号,
            # 否则会误触 _on_script_edit 并形成 "高亮→textChanged→防抖→高亮" 循环,
            # 令脏标记在保存后被反复置位, 导致退出时误报"有未保存的修改" (§修复)
            self.script_text.blockSignals(True)
            self._script_highlighter.rehighlight()
            self.script_text.blockSignals(False)

    def _update_line_preview(self):
        """更新右侧行功能预览 (带颜色分类) — 解析与着色逻辑对应 mat_editor.py _update_line_preview"""
        content = self.script_text.toPlainText()
        lines = content.split('\n')
        self.script_preview.clear()
        cursor = self.script_preview.textCursor()

        # 颜色格式 (对应 v1 的 pv_* tag); 灰色系在深色背景 #1a1e27 上对比度不足,
        # 深色模式提亮并复用本主题 QSS 既有灰阶 (#dcdcdc/#a5b0cb/#8a96b3), 浅色保持 v1 原值
        def mkfmt(color):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            return f
        dark = self._is_dark
        # 深色配色优化: 背景 #1a1e27 上彩色类提亮至对比度>=4.5:1 且与左侧高亮器色板语义一致
        # (白=普通命令, 紫=对话, 蓝=流程, 橙=分支, 红=道具, 绿=场景/队员); 灰阶类按
        # comment>block>raw 分层, 注释/未识别弱化以突出命令行
        fmt_cmd     = mkfmt('#333333' if not dark else '#dcdcdc')  # pv_cmd   普通命令(深色=白色)
        fmt_talk    = mkfmt('#7B30D0' if not dark else '#b884ff')  # pv_talk  对话
        fmt_flow    = mkfmt('#0066CC' if not dark else '#5b8aff')  # pv_flow  流程
        fmt_branch  = mkfmt('#CC6600' if not dark else '#e0a040')  # pv_branch 分支
        fmt_getitem = mkfmt('#CC0000' if not dark else '#ff7b7b')  # pv_getitem 道具
        fmt_scene   = mkfmt('#008800' if not dark else '#6ab04c')  # pv_scene  场景/队员
        fmt_comment = mkfmt('#AAA'    if not dark else '#6a7590')  # pv_comment 注释(弱化)
        fmt_block   = mkfmt('#BBB'    if not dark else '#7a86a8')  # pv_block  块/DEFINE
        fmt_raw     = mkfmt('#999'    if not dark else '#5a6480')  # pv_raw   未识别(最弱)

        def trunc(s, max_len=28):
            s = s.replace('\n', ' ').replace('\r', '')
            if len(s) <= max_len:
                return s
            return s[:max_len - 1] + '…'

        talk_cmds = {'TalkB', 'TalkA', 'SetTalkB', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'DoTalkB', 'MenuTalk', 'SetHint'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else', 'SetNowDef'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam', 'CheckMember',
                       'Switch', 'Random'}

        seen_cmds = []  # 累积已解析命令(cmd,args), 供 CheckResult 回溯配套 MenuTalk; DEFINE 边界重置
        for i, line in enumerate(lines):
            stripped = line.strip()
            if i > 0:
                cursor.insertText('\n')
            if not stripped:
                continue
            if stripped.startswith('//'):
                cursor.insertText(trunc(stripped), fmt_comment)
                continue
            if stripped in ('{', '}; end') or stripped.startswith('};'):
                if stripped.startswith('};'):
                    seen_cmds = []  # DEFINE 结束, 重置回溯作用域
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            if stripped.startswith('DEFINE'):
                seen_cmds = []  # 新 DEFINE, 重置回溯作用域
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                desc = self._format_cmd_desc(cmd_name, args)
                maxlen = 28
                # CheckResult: 回溯本 DEFINE 内配套 MenuTalk, 追加被判定的选项文本
                if cmd_name == 'CheckResult' and len(args) >= 2:
                    opt = self._resolve_menu_option(seen_cmds, len(seen_cmds), args[0], args[1])
                    if opt:
                        desc += f" →「{opt}」"
                        maxlen = 40
                seen_cmds.append((cmd_name, args))
                fmt = fmt_cmd
                if cmd_name in talk_cmds:
                    fmt = fmt_talk
                elif cmd_name in flow_cmds:
                    fmt = fmt_flow
                elif cmd_name in branch_cmds:
                    fmt = fmt_branch
                elif cmd_name == 'GetItem':
                    fmt = fmt_getitem
                elif cmd_name in ('TeamMember', 'ChangeScene'):
                    fmt = fmt_scene
                cursor.insertText(trunc(desc, maxlen), fmt)
            else:
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    cmd_name = m2.group(1)
                    desc = self._format_cmd_desc(cmd_name, [])
                    fmt = fmt_cmd
                    if cmd_name in talk_cmds:
                        fmt = fmt_talk
                    elif cmd_name in flow_cmds:
                        fmt = fmt_flow
                    elif cmd_name in branch_cmds:
                        fmt = fmt_branch
                    cursor.insertText(trunc(desc), fmt)
                else:
                    cursor.insertText(trunc(stripped, 40), fmt_raw)

    def _format_cmd_desc(self, cmd_name, args, tkt=None):
        desc_fn = SCRIPT_CMD_DESC.get(cmd_name)
        tkt = self._data.tkt_all if tkt is None else tkt
        if desc_fn:
            try:
                return desc_fn(args, tkt, self._data.item_names)
            except TypeError:
                try:
                    return desc_fn(args, tkt)
                except Exception:
                    pass
            except Exception:
                pass
        args_str = ', '.join(args) if args else ''
        return f"{cmd_name}({args_str})"

    def _resolve_menu_option(self, commands, idx, slot, expected):
        """CheckResult(变量槽, 期望值): 回溯 idx 之前最近的、写入同一变量槽的 MenuTalk,
        把期望值当作选项索引解析出对应的菜单选项文本。找不到匹配则返回 None。"""
        try:
            exp = int(expected)
        except (ValueError, TypeError):
            return None
        for pj in range(idx - 1, -1, -1):
            pc, pa = commands[pj][0], commands[pj][1]
            if pc == 'MenuTalk' and len(pa) >= 2 and pa[1] == slot:
                opts = _menu_options(self._data.tkt_all, pa[0])
                return opts[exp] if 0 <= exp < len(opts) else None
        return None

    # =========== DefUnit 链 ===========
    def _refresh_chain_list(self):
        # clear() 在清空过程中会瞬时选中其它行并发出 itemSelectionChanged (Qt 行为),
        # 误触 _on_chain_select 会把 _current_edit_define_id 覆盖成错误条目 → 刷新后跳错行。
        # 故先记录待保留的 DEFINE, 再屏蔽信号清空 (§修复: 应用修改后跳回第一条)
        preserve_define_id = self._current_edit_define_id
        self.chain_tree.blockSignals(True)
        self.chain_tree.clear()
        self.chain_tree.blockSignals(False)
        if not self._data.records:
            return
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self._data.records):
                rec = self._data.records[self._current_param_idx]
        if not rec or not has_data(rec):
            self._clear_script_editor()
            self._update_sched_info(None)
            return
        entity_id = rec['index']

        # 检测共享头指针: 若 headA/headB/headC 中有多者指向同一 DefUnit 节点,
        # 该节点会在多条链中重复显示 (数据异常, 如实体#44 headA==headB)。
        # 记录被共享的头节点索引 → 使用它的链名列表, 供下方在链头标注 ⚠共享头。
        _head_users = {}
        for _sn, _hd in (('A', 39), ('B', 40), ('C', 41)):
            _hv = rec.get(f'd{_hd}', 0)
            if _hv > 0:
                _head_users.setdefault(_hv, []).append(_sn)
        _shared_heads = {_hv: _sns for _hv, _sns in _head_users.items() if len(_sns) > 1}

        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            cur = rec.get(f'd{cur_di}', 0)
            if h <= 0 or mx <= 0:
                continue
            cur_str = f'当前={cur}' if cur > 0 else '未激活'
            # Group header (共享头节点追加 ⚠共享头 警示)
            _warn = ''
            if h in _shared_heads:
                _others = '/'.join(x for x in _shared_heads[h] if x != sub_name)
                _warn = f'  ⚠共享头(与{_others}链共用#{h})'
            group_item = QTreeWidgetItem([f'{sub_name}链', '', '', '', '', f'head=#{h} max={mx} {cur_str}{_warn}'])
            group_item.setForeground(0, QColor("#CC6600") if h in _shared_heads else QColor("#3366cc"))
            self.chain_tree.addTopLevelItem(group_item)
            # Traverse chain (with loop detection)
            idx = h
            visited_chain = set()
            for step in range(mx):
                if idx in visited_chain:
                    # 循环检测: 标记循环节点
                    loop_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'(循环→{idx})', '', '', '⚠循环'])
                    loop_item.setForeground(0, QColor("#CC0000"))
                    self.chain_tree.addTopLevelItem(loop_item)
                    break
                visited_chain.add(idx)
                du_rec = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                if du_rec is None:
                    # 空槽检测
                    empty_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'#{idx}(空槽)', '', '', '⚠断开'])
                    empty_item.setForeground(0, QColor("#CC6600"))
                    self.chain_tree.addTopLevelItem(empty_item)
                    break
                define_id = (du_rec['f1'] << 16) | du_rec['f0']
                marks = []
                if (step + 1) == cur:
                    marks.append('当前')
                if step == 0:
                    marks.append('链头')
                child = QTreeWidgetItem([f'  {sub_name}', str(step + 1), str(idx), str(define_id), str(du_rec['f0']), ','.join(marks)])
                self.chain_tree.addTopLevelItem(child)
                idx = du_rec['f6']
                if idx == 0:
                    break

        total = self.chain_tree.topLevelItemCount()
        self.chain_info_lbl.setText(f"entity={entity_id}, {total} 条节点")
        if total == 0:
            self._clear_script_editor()
            self.script_info_lbl.setText("(无关联 DEFINE)")
        else:
            # 刷新后优先恢复之前正在编辑的 DEFINE, 避免"应用修改"后跳回第一条 (§修复)
            target_item = None
            first_item = None
            for i in range(self.chain_tree.topLevelItemCount()):
                item = self.chain_tree.topLevelItem(i)
                if not (item.text(2).isdigit() and item.text(3).isdigit()):
                    continue
                if first_item is None:
                    first_item = item
                if preserve_define_id is not None and int(item.text(3)) == preserve_define_id:
                    target_item = item
                    break
            chosen = target_item or first_item
            if chosen is not None:
                # 阻断选择信号, 由下方显式调用 _on_chain_select 统一处理 (避免重复触发)
                self.chain_tree.blockSignals(True)
                self.chain_tree.setCurrentItem(chosen)
                self.chain_tree.blockSignals(False)
                self._on_chain_select()
        self._update_sched_info(rec)

    def _on_chain_select(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        define_id = int(define_str)
        du_idx = int(du_str)
        self._save_editor_to_define()
        self._load_define_to_editor(define_id)
        self.chain_info_lbl.setText(f"DefUnit #{du_idx} → DEFINE {define_id}")

    def _add_chain_entry(self, sub_scene, *_args):
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self._data.records):
                rec = self._data.records[self._current_param_idx]
        if not rec or not has_data(rec):
            return
        entity_id = rec['index']

        # Find empty DefUnit slot
        # 槽位 0 是保留的空/空指针哨兵 (head=0 表示"无链", f6=0 表示"链尾"),
        # 绝不可分配给真实条目, 否则首次新增会令 head=0 被 _refresh_chain_list
        # 判为空链而不刷新, 再次新增又会覆盖 head 导致槽位 0 记录与其 TKD 块成为孤块(数据损坏)。
        # 因此从 1 开始搜索。
        empty_idx = None
        for i in range(1, DEFUNIT_REC_COUNT):
            existing = next((r for r in self._data.defunit_recs if r['index'] == i), None)
            if existing is None:
                empty_idx = i
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"TKDefUnit.dat 所有 {DEFUNIT_REC_COUNT} 条记录均已占用")
            return

        existing_blocks = [r['f0'] for r in self._data.defunit_recs if r['f1'] == entity_id and r['f0'] >= 256]
        new_f0 = max(existing_blocks) + 1 if existing_blocks else 256
        if new_f0 > 266:
            new_f0 = max(existing_blocks) + 1
        define_id = (entity_id << 16) | new_f0

        new_rec = {'index': empty_idx, 'f0': new_f0, 'f1': entity_id,
                   'f2': 0, 'f3': 0, 'f4': 0, 'f5': 0, 'f6': 0, 'f7': 0}
        self._data.defunit_recs.append(new_rec)
        self._data.defunit_entity.setdefault(entity_id, []).append(empty_idx)

        h_di, mx_di, cur_di = {'A': (39, 30, 33), 'B': (40, 31, 34), 'C': (41, 32, 35)}[sub_scene]
        head = rec.get(f'd{h_di}', 0)
        mx = rec.get(f'd{mx_di}', 0)
        if head == 0 or mx == 0:
            rec[f'd{h_di}'] = empty_idx
            rec[f'd{mx_di}'] = 1
            rec[f'd{cur_di}'] = 1
        else:
            idx = head
            tail = head
            for _ in range(mx):
                du_r = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                if du_r is None or du_r['f6'] == 0:
                    break
                idx = du_r['f6']
                tail = idx
            du_tail = next((r for r in self._data.defunit_recs if r['index'] == tail), None)
            if du_tail:
                du_tail['f6'] = empty_idx
            rec[f'd{mx_di}'] = mx + 1

        if define_id not in self._data.tkd_define_map:
            d = {'define_id': define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': ['{', 'End(0)', '}; end'], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {define_id}'}
            self._data.tkd_defines.append(d)
            self._data.tkd_define_map[define_id] = d

        self._data._dirty = True
        self._script_dirty = True
        self._sync_form_dwords(rec, (h_di, mx_di, cur_di))
        self._refresh_chain_list()
        QMessageBox.information(self, "新增成功", f"DefUnit #{empty_idx} → DEFINE {define_id} ({sub_scene}场景)")

    def _delete_chain_entry(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        du_idx = int(du_str)
        define_id = int(define_str)
        du_rec = next((r for r in self._data.defunit_recs if r['index'] == du_idx), None)
        if du_rec is None:
            return
        entity_id = du_rec['f1']
        if QMessageBox.question(self, "确认删除",
                                f"删除 DefUnit #{du_idx} → DEFINE {define_id}?\n此操作同时从 TKD.dat 删除对应 DEFINE 块。",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return

        rec = self._data.records[self._current_param_idx]
        _modified_dis = []
        # 从 A/B/C 全部链中摘除该节点 (不能在首个匹配链后 break):
        # 若多条链共享同一头节点 (如实体#44 headA==headB 指向同一 DefUnit),
        # 只摘一条会残留悬空头指针 → 刷新后显示为 "空槽/断开" 且再也删不掉。
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            if h <= 0:
                continue
            prev = None
            idx = h
            for _ in range(mx):
                if idx == du_idx:
                    break
                prev = idx
                du_r = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                idx = du_r['f6'] if du_r else 0
            if idx != du_idx:
                continue
            if prev is None:
                rec[f'd{h_di}'] = du_rec['f6']
            else:
                prev_rec = next((r for r in self._data.defunit_recs if r['index'] == prev), None)
                if prev_rec:
                    prev_rec['f6'] = du_rec['f6']
            new_mx = max(0, mx - 1)
            rec[f'd{mx_di}'] = new_mx
            cur = rec.get(f'd{cur_di}', 0)
            if cur > new_mx:
                rec[f'd{cur_di}'] = new_mx
            _modified_dis.extend([h_di, mx_di, cur_di])

        du_rec['f0'] = du_rec['f1'] = du_rec['f6'] = 0
        self._data.defunit_recs = [r for r in self._data.defunit_recs if r['index'] != du_idx]
        if entity_id in self._data.defunit_entity and du_idx in self._data.defunit_entity[entity_id]:
            self._data.defunit_entity[entity_id].remove(du_idx)
        if define_id in self._data.tkd_define_map:
            d = self._data.tkd_define_map.pop(define_id)
            if d in self._data.tkd_defines:
                self._data.tkd_defines.remove(d)

        self._data._dirty = True
        self._script_dirty = True
        if _modified_dis:
            self._sync_form_dwords(rec, _modified_dis)
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self._current_edit_define_id = None
        self._refresh_chain_list()

    def _sync_form_dwords(self, rec, dis):
        for di in dis:
            val = str(rec[f'd{di}'])
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for key, f_di, label, cmt in fields:
                    if f_di == di and key in self._edit_vars:
                        w = self._edit_vars[key]
                        if isinstance(w, QLineEdit):
                            w.setText(val)
                        break
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(val)
                    break

    # =========== 脚本调度信息 ===========
    def _update_sched_info(self, rec):
        if rec is None or is_empty(rec):
            for key in self._sched_labels:
                self._sched_labels[key].setText("")
            return
        flags = rec.get('d2', 0)
        tval = rec.get('d0', 0)
        en = (flags & 1) != 0
        self._sched_labels['enabled'].setText("✓ 已启用" if en else "✗ 未启用")
        self._sched_labels['enabled'].setProperty("status", "loaded" if en else "missing")
        self._sched_labels['enabled'].style().unpolish(self._sched_labels['enabled'])
        self._sched_labels['enabled'].style().polish(self._sched_labels['enabled'])
        pk = (flags & 4) != 0
        self._sched_labels['pickable'].setText("✓ 可交互" if pk else "✗ 不可交互")
        tick = rec.get('d4', 0)
        self._sched_labels['tick'].setText(f"{tick} (越大越慢)" if tick > 0 else "0 (无Tick)")
        timer = rec.get('d3', 0)
        self._sched_labels['timer'].setText(f"{timer} (暂停中)" if timer > 0 else "0 (正常运行)")
        cur_a = rec.get('d33', 0)
        head_a = rec.get('d39', 0)
        max_a = rec.get('d30', 0)
        if head_a > 0 and max_a > 0:
            a_status = "⚡ 自动执行中" if cur_a > 0 else "已定义(未激活)"
            self._sched_labels['chain_a'].setText(f"✓ {a_status} [head=#{head_a},max={max_a},cur={cur_a}]")
        else:
            self._sched_labels['chain_a'].setText("— 无")
        cur_b = rec.get('d34', 0)
        head_b = rec.get('d40', 0)
        max_b = rec.get('d31', 0)
        if head_b > 0 and max_b > 0:
            b_status = "👆 交互触发" if cur_b > 0 else "已定义(未激活)"
            self._sched_labels['chain_b'].setText(f"✓ {b_status} [head=#{head_b},max={max_b},cur={cur_b}]")
        else:
            self._sched_labels['chain_b'].setText("— 无")
        cur_c = rec.get('d35', 0)
        head_c = rec.get('d41', 0)
        max_c = rec.get('d32', 0)
        if head_c > 0 and max_c > 0:
            c_status = "✱ 活跃" if cur_c > 0 else "已定义(未激活)"
            self._sched_labels['chain_c'].setText(f"✓ {c_status} [head=#{head_c},max={max_c},cur={cur_c}]")
        else:
            self._sched_labels['chain_c'].setText("— 无")
        trigger_map = {
            5: "仅脚本", 10: "接近传送", 15: "接近触发", 16: "接近遇敌",
            20: "点击对话", 110: "点击机关", 200: "点击对话",
        }
        trigger = trigger_map.get(tval, "未知")
        if cur_a > 0:
            trigger += " + A链自动(Tick)"
        self._sched_labels['trigger'].setText(trigger)

    # =========== 脚本模板 ===========
    def _show_script_template_dialog(self):
        """脚本模板选择器: 展示从原版 TKD.dat 高频写法归纳的模板, 选中后插入编辑框光标处。
        模板数据见 mat_script_templates.SCRIPT_TEMPLATES (按命令频率/骨架统计归纳)。"""
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "脚本模板", "请先在上方链列表选择一个 DEFINE 脚本块")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("脚本模板 — 常用脚本快速填充")
        dlg.resize(760, 540)
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            dlg.setWindowIcon(QIcon(ico))
        dlg_layout = QVBoxLayout(dlg)

        head = QLabel("挑选一个常用脚本模板, 双击或点击 [插入到光标处] 填入编辑框; "
                     "模板中的数字为占位值, 按首行注释替换为实际编号即可。")
        head.setProperty("class", "InfoTitle")
        head.setWordWrap(True)
        dlg_layout.addWidget(head)

        splitter = QSplitter(Qt.Horizontal)

        # 左: 模板树 (分类 → 模板)
        tree = QTreeWidget()
        tree.setHeaderLabels(["模板", "说明"])
        tree.setColumnWidth(0, 170)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setRootIsDecorated(True)
        for cat_name, items in SCRIPT_TEMPLATES:
            cat_item = QTreeWidgetItem([cat_name, ""])
            cf = cat_item.font(0)
            cf.setBold(True)
            cat_item.setFont(0, cf)
            cat_item.setFlags(Qt.ItemIsEnabled)  # 分类节点不可选中
            tree.addTopLevelItem(cat_item)
            for name, desc, body in items:
                it = QTreeWidgetItem([name, desc])
                it.setData(0, Qt.UserRole, body)
                it.setToolTip(1, desc)
                cat_item.addChild(it)
            cat_item.setExpanded(True)
        splitter.addWidget(tree)

        # 右: 模板内容预览 (只读, 复用脚本语法高亮)
        preview = QPlainTextEdit()
        preview.setFont(QFont("Consolas", 10))
        preview.setReadOnly(True)
        preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        preview.setPlaceholderText("← 选择左侧模板查看内容")
        self._tpl_preview_hl = ScriptSyntaxHighlighter(preview.document(), self._is_dark)
        splitter.addWidget(preview)
        splitter.setSizes([300, 440])
        dlg_layout.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_insert = QPushButton("插入到光标处")
        btn_insert.setDefault(True)
        btn_insert.setEnabled(False)
        btn_cancel = QPushButton("取消")
        btn_row.addWidget(btn_insert)
        btn_row.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_row)

        def _current_body():
            sel = tree.selectedItems()
            return sel[0].data(0, Qt.UserRole) if sel else None

        def _on_sel():
            body = _current_body()
            if body:
                preview.setPlainText(body)
                btn_insert.setEnabled(True)
            else:
                preview.clear()
                btn_insert.setEnabled(False)
        tree.itemSelectionChanged.connect(_on_sel)
        tree.itemDoubleClicked.connect(
            lambda item, col: dlg.accept() if item.data(0, Qt.UserRole) else None)
        btn_insert.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return
        body = _current_body()
        if body:
            self._insert_script_template(body)

    def _insert_script_template(self, body):
        """把模板 body 插入脚本编辑框光标处 (独占完整行), 随后刷新高亮/行预览并标记未保存。"""
        body = body.rstrip('\n')
        if not self.script_text.toPlainText().strip():
            self.script_text.setPlainText(body)
        else:
            cursor = self.script_text.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + body)
            cursor.endEditBlock()
            self.script_text.setTextCursor(cursor)
        self.script_text.setFocus()
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._save_editor_to_define()
        self._script_dirty = True
        self._data._dirty = True
        self.status_var.setText("已插入脚本模板 (请按首行注释替换占位数字)")

    # =========== 脚本修复验证 ===========
    def _show_fix_validate_menu(self):
        """弹出"修复验证"菜单, 选择要校验的脚本语句类型 (当前仅 SetPos, 预留扩展)"""
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "修复验证", "请先在上方链列表选择一个 DEFINE 脚本块")
            return
        menu = QMenu(self)
        act_setpos = menu.addAction("SetPos — 校验实体号 / 坐标 / 朝向")
        act_setpos.triggered.connect(self._fix_validate_setpos)
        btn = self._btn_fix_validate
        menu.exec(btn.mapToGlobal(QPoint(0, btn.height())))

    def _current_script_entity(self):
        """返回当前脚本所属实体记录 (由属性面板选中项决定, 与链列表同源)。无有效实体返回 None"""
        if self._current_param_idx is None:
            return None
        if not (0 <= self._current_param_idx < len(self._data.records)):
            return None
        rec = self._data.records[self._current_param_idx]
        return rec if has_data(rec) else None

    def _fix_validate_setpos(self):
        """校验当前脚本内所有 SetPos 的实体号/坐标/朝向是否与当前实体一致, 不一致时弹确认框修复。
        用途: 通用模板脚本(如"通用加入")复制到不同角色后, 一键把 SetPos 同步到当前实体实际值。"""
        rec = self._current_script_entity()
        if rec is None:
            QMessageBox.information(self, "SetPos 修复验证", "未找到当前脚本所属实体, 请先选中实体并选择 DEFINE")
            return
        ent_idx = rec['index']
        cur_x = rec.get('d10', 0)
        cur_y = rec.get('d11', 0)
        cur_dir = rec.get('d13', 0)

        lines = self.script_text.toPlainText().split('\n')
        setpos_re = re.compile(r'^(\s*)SetPos\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)(.*)$')
        total = 0
        mismatches = []  # (line_idx, indent, trailing, cur_stmt, new_stmt)
        for i, line in enumerate(lines):
            m = setpos_re.match(line)
            if not m:
                continue
            total += 1
            indent = m.group(1)
            e = int(m.group(2)); x = int(m.group(3)); y = int(m.group(4)); dd = int(m.group(5))
            trailing = m.group(6)
            # 目标: 显式实体号→当前实体索引; -1(上下文)/-2(自身) 相对引用保持不变; 坐标/朝向一律对齐当前实体
            tgt_e = e if e < 0 else ent_idx
            if tgt_e == e and x == cur_x and y == cur_y and dd == cur_dir:
                continue
            cur_stmt = f"SetPos({e},{x},{y},{dd})"
            new_stmt = f"SetPos({tgt_e},{cur_x},{cur_y},{cur_dir})"
            mismatches.append((i, indent, trailing, cur_stmt, new_stmt))

        if total == 0:
            QMessageBox.information(self, "SetPos 修复验证", "当前脚本未找到 SetPos 语句")
            return
        dir_txt = _dir_name(str(cur_dir), str(ent_idx))
        if not mismatches:
            QMessageBox.information(
                self, "SetPos 修复验证",
                f"当前脚本共 {total} 处 SetPos, 均与当前实体一致, 无需修复\n\n"
                f"当前实体 #{ent_idx} — 坐标({cur_x},{cur_y}) 朝向{cur_dir}({dir_txt})")
            return

        # 不一致 → 弹确认对话框 (逐条展示差异, 复选框默认全选, 用户确认后修复)
        dlg = QDialog(self)
        dlg.setWindowTitle("SetPos 修复验证")
        dlg.resize(660, 440)
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            dlg.setWindowIcon(QIcon(ico))
        dlg_layout = QVBoxLayout(dlg)

        head = QLabel(
            f"当前实体 #{ent_idx} — 坐标({cur_x},{cur_y}) 朝向{cur_dir}({dir_txt})\n"
            f"发现 {len(mismatches)} / {total} 处 SetPos 与当前实体不一致, 勾选需要修复的项后点击 [修复选中项]:")
        head.setProperty("class", "InfoTitle")
        head.setWordWrap(True)
        dlg_layout.addWidget(head)

        tree = QTreeWidget()
        tree.setHeaderLabels(["修复", "行", "当前语句", "建议修复为"])
        tree.setColumnWidth(0, 44)
        tree.setColumnWidth(1, 48)
        tree.setColumnWidth(2, 230)
        tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        tree.setRootIsDecorated(False)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        item_map = []  # (item, line_idx, indent, trailing, new_stmt)
        for (i, indent, trailing, cur_stmt, new_stmt) in mismatches:
            it = QTreeWidgetItem(["", str(i + 1), cur_stmt, new_stmt])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            it.setForeground(2, QColor("#CC0000"))
            it.setForeground(3, QColor("#2E9B57"))
            tree.addTopLevelItem(it)
            item_map.append((it, i, indent, trailing, new_stmt))
        dlg_layout.addWidget(tree, 1)

        btn_row = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        btn_fix = QPushButton("修复选中项")
        btn_fix.setDefault(True)
        btn_cancel = QPushButton("取消")
        btn_row.addWidget(btn_fix)
        btn_row.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_row)

        def _set_all(state):
            for entry in item_map:
                entry[0].setCheckState(0, state)
        btn_all.clicked.connect(lambda: _set_all(Qt.Checked))
        btn_none.clicked.connect(lambda: _set_all(Qt.Unchecked))
        btn_cancel.clicked.connect(dlg.reject)
        btn_fix.clicked.connect(dlg.accept)

        if dlg.exec() != QDialog.Accepted:
            return

        new_lines = list(lines)
        fixed = 0
        for (it, i, indent, trailing, new_stmt) in item_map:
            if it.checkState(0) == Qt.Checked:
                new_lines[i] = f"{indent}{new_stmt}{trailing}"
                fixed += 1
        if fixed == 0:
            QMessageBox.information(self, "SetPos 修复验证", "未勾选任何项, 未做修改")
            return

        self.script_text.blockSignals(True)
        self.script_text.setPlainText('\n'.join(new_lines))
        self.script_text.blockSignals(False)
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._save_editor_to_define()
        self._script_dirty = True
        self._data._dirty = True
        QMessageBox.information(self, "SetPos 修复验证", f"已修复 {fixed} 处 SetPos → 对齐实体 #{ent_idx} 坐标({cur_x},{cur_y}) 朝向{cur_dir}")

    # =========== 脚本预览 ===========
    def _preview_script(self):
        self._save_editor_to_define()
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "预览", "请先选择一个 DEFINE 脚本块")
            return
        d = self._data.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            QMessageBox.information(self, "预览", "未找到当前 DEFINE 数据")
            return
        body_lines = d.get('body_lines', [])
        commands = self._parse_script_commands(body_lines)
        if not commands:
            QMessageBox.information(self, "预览", "未解析到有效命令")
            return
        self._preview_cmds = commands
        self._preview_step = 0

        win = QDialog(self)
        win.setWindowTitle(f"脚本预览 — DEFINE {self._current_edit_define_id}")
        win.resize(780, 680)
        # 图标
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            win.setWindowIcon(QIcon(ico))
        main_layout = QVBoxLayout(win)

        # 顶部信息栏
        info_row = QHBoxLayout()
        comment = d.get('comment', '')
        info_text = f"DEFINE {self._current_edit_define_id}"
        if comment:
            info_text += f"  —  {comment}"
        info_text += f"  |  {len(commands)} 条命令"
        info_lbl = QLabel(info_text)
        info_lbl.setProperty("class", "InfoTitle")
        info_row.addWidget(info_lbl, 1)
        self._pv_info_lbl = QLabel("")
        info_row.addWidget(self._pv_info_lbl)
        main_layout.addLayout(info_row)

        # 命令列表 + 详情面板 (垂直分割)
        splitter = QSplitter(Qt.Vertical)

        # 命令列表 (带颜色标签)
        self._pv_tree = QTreeWidget()
        self._pv_tree.setHeaderLabels(["#", "命令", "描述"])
        self._pv_tree.setColumnWidth(0, 35)
        self._pv_tree.setColumnWidth(1, 110)
        self._pv_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self._pv_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pv_tree.setRootIsDecorated(False)

        # 填充命令 (带颜色分类)
        talk_cmds = {'TalkB', 'TalkA', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'SetTalkB', 'SetHint', 'DoTalkB', 'MenuTalk'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam',
                       'CheckMember', 'Switch', 'Random'}
        # 配色与右侧行预览 (_update_line_preview) 统一, 按主题切换深/浅色板
        dark = self._is_dark
        c_talk    = QColor('#7B30D0' if not dark else '#b884ff')   # 紫=对话
        c_flow    = QColor('#0066CC' if not dark else '#5b8aff')   # 蓝=流程
        c_branch  = QColor('#CC6600' if not dark else '#e0a040')   # 橙=分支
        c_getitem = QColor('#CC0000' if not dark else '#ff7b7b')   # 红=道具
        c_default = QColor('#333333' if not dark else '#dcdcdc')   # 普通命令(深色=白色)
        for si, (cmd_name, args, line_text, line_idx) in enumerate(commands):
            desc = self._format_cmd_desc(cmd_name, args)
            # CheckResult: 回溯配套 MenuTalk, 在描述后追加被判定的选项文本
            if cmd_name == 'CheckResult' and len(args) >= 2:
                opt = self._resolve_menu_option(commands, si, args[0], args[1])
                if opt:
                    desc += f" → 选中「{opt}」"
            item = QTreeWidgetItem([str(si + 1), cmd_name, desc])
            # 颜色分类
            if cmd_name in talk_cmds:
                color = c_talk
            elif cmd_name in flow_cmds:
                color = c_flow
            elif cmd_name in branch_cmds:
                color = c_branch
            elif cmd_name == 'GetItem':
                color = c_getitem
            else:
                color = c_default
            for c in range(3):
                item.setForeground(c, color)
            item.setData(0, Qt.UserRole, si)  # 存储步骤索引
            self._pv_tree.addTopLevelItem(item)

        splitter.addWidget(self._pv_tree)

        # 详情面板 (QTextEdit 支持富文本颜色)
        self._pv_detail = QTextEdit()
        self._pv_detail.setReadOnly(True)
        self._pv_detail.setFont(QFont("Consolas", 10))
        # 预配置 FCOLOR 1-32 颜色格式 (按主题调整对比度, 避免白字白底不可见)
        self._pv_color_formats = {}
        for ci in range(1, 33):
            fmt = QTextCharFormat()
            fmt.setForeground(self._readable_tkt_color(GAME_COLORS[ci]))
            self._pv_color_formats[f'tkt_c{ci}'] = fmt
        # 物品名红色格式
        self._pv_item_red_fmt = QTextCharFormat()
        self._pv_item_red_fmt.setForeground(QColor("#FF4444"))
        self._pv_item_red_fmt.setFontWeight(QFont.Bold)
        # 动态 FCOLORD 格式缓存
        self._pv_dynamic_color_tags = {}
        splitter.addWidget(self._pv_detail)
        splitter.setSizes([380, 200])
        main_layout.addWidget(splitter, 1)

        # 选中事件
        self._pv_tree.itemSelectionChanged.connect(self._preview_on_select)
        # 选中第一步
        if self._pv_tree.topLevelItemCount() > 0:
            self._pv_tree.setCurrentItem(self._pv_tree.topLevelItem(0))

        self._preview_win = win
        win.exec()

    def _preview_on_select(self):
        """预览窗口: 选中命令 → 更新详情面板"""
        sel = self._pv_tree.selectedItems()
        if not sel:
            return
        step = sel[0].data(0, Qt.UserRole)
        if step is None:
            return
        self._preview_step = step
        if 0 <= step < len(self._preview_cmds):
            cmd_name, args, line_text, _ = self._preview_cmds[step]
            self._pv_detail.clear()
            self._pv_detail.append(f"<b>原始:</b> {line_text}")
            self._pv_detail.append(f"<b>命令:</b> {cmd_name}({', '.join(args)})")
            # 参数逐项说明 (在"命令"下方, 方便开发者理解每个参数)
            param_lines = format_cmd_params(cmd_name, args, self._data.tkt_all, self._data.item_names)
            if param_lines:
                self._pv_detail.append("<b>参数:</b>")
                cur = self._pv_detail.textCursor()
                cur.movePosition(QTextCursor.End)
                cur.insertText("\n" + "\n".join("　　" + pl for pl in param_lines))
            # 描述: 对话类命令下方另有"TKT 对话文本"独立栏, 此处不重复正文, 避免冲突
            #       (树列/右侧行预览仍走默认路径, 保留内联文本)
            if cmd_name in ('TalkB', 'TalkA', 'SetTalkB', 'BlackTalk', 'ShowText', 'MenuTalk', 'SysTalk'):
                desc = self._format_cmd_desc(cmd_name, args, tkt={})   # 空表 → 描述内不含正文
                desc = re.sub(r'\(\s*\)', '', desc)          # 去空括号 (TalkA/SysTalk)
                desc = re.sub(r'\s*—\s*$', '', desc).rstrip()  # 去结尾悬空的 —
            else:
                desc = self._format_cmd_desc(cmd_name, args)
            self._pv_detail.append(f"<b>描述:</b> {desc}")
            # 对话命令: 解析 TKT 文本并用颜色渲染
            if cmd_name in ('TalkB', 'TalkA', 'SetTalkB', 'BlackTalk') and len(args) >= 2:
                text_idx = 0 if cmd_name == 'BlackTalk' else 1
                tkt_text = _tkt_text(self._data.tkt_all, args[text_idx], max_len=500)
                if tkt_text:
                    self._pv_detail.append(f"\n<b>━━━ TKT 对话文本 (ID={args[text_idx]}) ━━━</b>")
                    self._insert_colored_tkt(tkt_text)
            elif cmd_name in ('ShowText', 'MenuTalk', 'SysTalk') and args:
                tkt_text = _tkt_text(self._data.tkt_all, args[0], max_len=500)
                if tkt_text:
                    self._pv_detail.append(f"\n<b>━━━ TKT 对话文本 (ID={args[0]}) ━━━</b>")
                    self._insert_colored_tkt(tkt_text)
            # GetItem: 物品名称用红色显示
            if cmd_name == 'GetItem' and args and self._data.item_names:
                try:
                    item_id = int(args[0])
                    item_name = self._data.item_names.get(item_id, '')
                    if item_name:
                        self._pv_detail.append(f"\n<b>━━━ 物品名称 (ID={args[0]}) ━━━</b>")
                        cursor = self._pv_detail.textCursor()
                        cursor.movePosition(QTextCursor.End)
                        cursor.insertText("\n" + item_name, self._pv_item_red_fmt)
                except (ValueError, TypeError):
                    pass
            # CheckResult: 回溯配套 MenuTalk, 显示被判定的具体选项文本
            if cmd_name == 'CheckResult' and len(args) >= 2:
                opt = self._resolve_menu_option(self._preview_cmds, step, args[0], args[1])
                if opt:
                    self._pv_detail.append("\n<b>━━━ 菜单选择判断 ━━━</b>")
                    self._pv_detail.append(f"当 变量[{args[0]}] == {args[1]} 成立 → 玩家选择了「{opt}」")
            # 更新信息标签
            self._pv_info_lbl.setText(f"步骤 {step+1}/{len(self._preview_cmds)}")
        # 高亮当前步骤 (黄色背景)
        for i in range(self._pv_tree.topLevelItemCount()):
            item = self._pv_tree.topLevelItem(i)
            si = item.data(0, Qt.UserRole)
            if si == step:
                for c in range(3):
                    item.setBackground(c, QColor("#FFEE88") if not self._is_dark else QColor("#5a5520"))
            else:
                for c in range(3):
                    item.setBackground(c, QColor("transparent"))

    def _insert_colored_tkt(self, text):
        """将含 <FCOLOR,n> 等标签的 TKT 文本按颜色分段插入详情面板"""
        segments = parse_tkt_colored_segments(text)
        cursor = self._pv_detail.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("\n")  # 与上方"━━━ 标题 ━━━"分行
        for seg_text, color in segments:
            fmt = self._get_tkt_color_format(color)
            cursor.insertText(seg_text, fmt)

    def _readable_tkt_color(self, color_hex):
        """按主题调整游戏文字色对比度: 浅色主题压暗过亮色(白字→深灰), 深色主题提亮过暗色, 保证预览可读"""
        c = QColor(color_hex)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        if self._is_dark:
            if lum <= 30:            # 近黑, 深底不可见 → 浅灰
                return QColor('#c8c8c8')
            if lum < 70:
                return c.lighter(180)
            return c
        if lum >= 235:               # 近白/纯白(默认色), 浅底不可见 → 深灰
            return QColor('#333333')
        if lum > 180:                # 偏亮 → 压暗保留色相
            return c.darker(190)
        return c

    def _get_tkt_color_format(self, color_hex):
        """获取 TKT 颜色的 QTextCharFormat。FCOLOR 1-32 用预配置, FCOLORD 动态创建"""
        for ci in range(1, 33):
            if GAME_COLORS[ci] == color_hex:
                return self._pv_color_formats[f'tkt_c{ci}']
        # FCOLORD 动态颜色
        if color_hex not in self._pv_dynamic_color_tags:
            fmt = QTextCharFormat()
            fmt.setForeground(self._readable_tkt_color(color_hex))
            self._pv_dynamic_color_tags[color_hex] = fmt
        return self._pv_dynamic_color_tags[color_hex]

    def _parse_script_commands(self, body_lines):
        commands = []
        for i, line in enumerate(body_lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('//') or stripped.startswith('{') or stripped.startswith('}'):
                continue
            if stripped.startswith('DEFINE'):
                continue
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                commands.append((cmd_name, args, stripped, i))
            elif stripped and not stripped.startswith('//'):
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    commands.append((m2.group(1), [], stripped, i))
        return commands

    # =========== 删除场景 ===========
    def _delete_scene(self):
        sid = self._canvas._vis_scene_id
        sname = scene_name(self._data.tkt_scenes, sid)
        scene_entities = [r for r in self._data.records if has_data(r) and r['d1'] == sid]
        if not scene_entities:
            QMessageBox.information(self, "空场景", f"场景 {sname} (ID={sid}) 无实体, 无需删除")
            return
        n = len(scene_entities)
        if QMessageBox.question(self, "确认删除场景",
                                f"将删除场景 {sname} (ID={sid})\n\n  TKMat 实体: {n} 个\n\n此操作不可撤销!",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        all_du_indices = set()
        all_define_ids = set()
        for rec in scene_entities:
            for di in [39, 40, 41]:
                head = rec.get(f'd{di}', -1)
                if head < 0:
                    continue
                cur = head
                visited = set()
                while cur >= 0 and cur not in visited:
                    visited.add(cur)
                    du = next((r for r in self._data.defunit_recs if r['index'] == cur), None)
                    if du is None:
                        break
                    all_du_indices.add(cur)
                    did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                    if did > 0:
                        all_define_ids.add(did)
                    nxt = du.get('f6', 0)
                    if nxt == 0 or nxt in visited:
                        break
                    cur = nxt
        for did in all_define_ids:
            if did in self._data.tkd_define_map:
                d = self._data.tkd_define_map.pop(did)
                if d in self._data.tkd_defines:
                    self._data.tkd_defines.remove(d)
        self._data.defunit_recs = [r for r in self._data.defunit_recs if r['index'] not in all_du_indices]
        for rec in scene_entities:
            for di in range(DWORD_COUNT):
                rec[f'd{di}'] = 0
        self._data._dirty = True
        self._script_dirty = True
        self._apply_filter()
        self._vis_populate_scenes()
        self._vis_load_scene()
        QMessageBox.information(self, "删除完成",
                                f"已删除场景 {sname} (ID={sid})\n实体: {n} 个\nDefUnit: {len(all_du_indices)} 条\nDEFINE: {len(all_define_ids)} 个")

    # =========== 统计/导出/导入 ===========
    def _show_stats(self):
        if not self._data.records:
            return
        tc = Counter()
        sc = Counter()
        for r in self._data.records:
            if has_data(r):
                tc[r['d0']] += 1
                sc[r['d1']] += 1
        ne = sum(tc.values())
        msg = f"TKMat.Dat 统计\n{'─' * 40}\n总槽位:{REC_COUNT} | 有效:{ne} | 空:{REC_COUNT - ne}\n场景数:{len(sc)}\n\n类型分布:\n"
        for tval in sorted(tc.keys()):
            msg += f"  {tval}-{ENTITY_TYPES.get(tval, '?')}: {tc[tval]} ({tc[tval] / ne * 100:.1f}%)\n"
        QMessageBox.information(self, "统计信息", msg)

    # 逆向参考: sub_412688(加载入口, 行21)
    def _show_field_ref(self):
        msg = ("TKMat.Dat 实体表字段说明\n" + '─' * 50 + "\n\n"
               "数据结构: 6000 条 × 384 字节 (每条 96 个 32 位整数字段)\n\n"
               "常用字段说明:\n"
               "  [0] 类型      [1] 场景编号   [2] 标志位     [3] 计时器     [4] 周期\n"
               "  [10][11] 坐标X/Y    [13] 朝向        [18][19] 边界范围\n"
               "  [30-35] 子场景参数  [39-41] 链式触发  [42-43] 玩家角色  [44] 定义单位\n"
               "  [50] 条件角色  [51] 访问掩码   [52] 目标场景   [53-54] 目标坐标  [56] 目标朝向\n\n"
               "注意: [52-56] 字段的含义随实体类型变化\n"
               "  · 类型 10 (传送点): 作为传送目标参数\n"
               "  · 类型 200 (动画对象): 作为动画播放参数")
        themed_messagebox(self, QMessageBox.Information, "字段说明", msg)

    # 逆向参考: sub_412688, sub_405CBC, sub_4066F0, sub_40EBD4, sub_409618
    def _show_help(self):
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
                                "功能: 编辑《三国群侠传》地图实体数据\n\n"
                                "编辑模式:\n"
                                "  · 参数编辑 - 修改实体属性\n"
                                "  · 可视化预览 - 地图场景展示\n"
                                "  · 脚本编辑 - 编辑事件脚本\n"
                                "  · 脚本调度 - 管理脚本执行顺序\n\n"
                                "数据文件:\n"
                                "  · TKMat.dat - 实体表 (6000 条 × 384 字节)\n"
                                "  · TKDefUnit.dat - 定义单位 (原版 5000 条, 已扩展至 10000 条 × 16 字节)\n"
                                "  · TKD.dat - 脚本数据\n"
                                "  保存时一次性写入以上三个文件\n\n"
                                "脚本链类型:\n"
                                "  · A链 - 自动执行 (按周期触发)\n"
                                "  · B链 - 交互触发 (玩家操作时)\n"
                                "  · C链 - 其他类型")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
                                format_about_header('mat_editor'))

    def _export_scene(self):
        """导出当前场景: TKMat实体 + DefUnit链 + TKD脚本 → .tkmat JSON"""
        if not self._data.records:
            QMessageBox.warning(self, "无数据", "请先加载 TKS 目录")
            return
        sid = self._canvas._vis_scene_id
        if self._data._sc_grp_section_count > 0 and sid >= self._data._sc_grp_section_count:
            QMessageBox.warning(self, "虚拟场景", "虚拟场景没有对应的 SC.GRP 数据, 不允许导出。")
            return
        scene_entities = [r for r in self._data.records if has_data(r) and r['d1'] == sid]
        if not scene_entities:
            QMessageBox.warning(self, "空场景", f"场景 {sid} 无实体数据")
            return

        tkt_scene_text = None
        if self._data.tkt_all:
            tkt_id = sid + 300
            tkt_scene_text = self._data.tkt_all.get(tkt_id, '')

        sc_grp_section = None
        sc_idx_data = None
        if self._data.dat_path:
            d = self._get_game_dir()
            grp_path = os.path.join(d, "SC.GRP")
            idx_path = os.path.join(d, "SC.IDX")
            if os.path.exists(grp_path) and os.path.exists(idx_path):
                try:
                    with open(idx_path, 'rb') as f:
                        idata = f.read()
                    sc_idx_data = base64.b64encode(idata).decode('ascii')
                    offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                    if sid < len(offs):
                        start = offs[sid]
                        end = offs[sid + 1] if sid + 1 < len(offs) else os.path.getsize(grp_path)
                        with open(grp_path, 'rb') as f:
                            f.seek(start)
                            sc_grp_section = base64.b64encode(f.read(end - start)).decode('ascii')
                except Exception:
                    pass

        def find_du(idx):
            return next((r for r in self._data.defunit_recs if r['index'] == idx), None)

        all_defunit_indices = set()
        entity_exports = []

        def collect_chain(head_idx):
            indices = []
            cur = head_idx
            visited = set()
            while cur >= 0 and cur not in visited:
                visited.add(cur)
                du = find_du(cur)
                if du is None:
                    break
                indices.append(cur)
                all_defunit_indices.add(cur)
                nxt = du.get('f6', 0)
                if nxt == 0 or nxt in visited:
                    break
                cur = nxt
            return indices

        for rec in scene_entities:
            chains = {}
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                max_di = {39: 30, 40: 31, 41: 32}[di]
                head = rec.get(f'd{di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if head > 0 and mx > 0:
                    chains[chain_name] = collect_chain(head)
            entity_exports.append({
                'dwords': [rec.get(f'd{i}', 0) for i in range(96)],
                'defunit_chains': chains,
            })

        defunits = []
        for idx in sorted(all_defunit_indices):
            du = find_du(idx)
            if du:
                defunits.append({'index': idx, 'fields': [du.get(f'f{i}', 0) for i in range(8)]})

        defines_export = []
        seen_dids = set()
        for rec in scene_entities:
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                max_di = {39: 30, 40: 31, 41: 32}[di]
                head = rec.get(f'd{di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if not (head > 0 and mx > 0):
                    continue
                cur = head
                visited = set()
                while cur >= 0 and cur not in visited:
                    visited.add(cur)
                    du = find_du(cur)
                    if du is None:
                        break
                    did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                    if did > 0 and did not in seen_dids:
                        seen_dids.add(did)
                        d = self._data.tkd_define_map.get(did)
                        if d:
                            text = '\r\n'.join([d['header_line']] + d['body_lines'])
                            defines_export.append({'id': did, 'text': text})
                    nxt = du.get('f6', 0)
                    if nxt == 0 or nxt in visited:
                        break
                    cur = nxt

        export_data = {
            'format': 'tkmat_scene_export',
            'version': 1,
            'scene_id': sid,
            'scene_name': scene_name(self._data.tkt_scenes, sid),
            'tkt_scene_text': tkt_scene_text,
            'sc_grp_section': sc_grp_section,
            'sc_idx_data': sc_idx_data,
            'entity_count': len(entity_exports),
            'entities': entity_exports,
            'defunits': defunits,
            'defines': defines_export,
        }

        sname = scene_name(self._data.tkt_scenes, sid).replace('/', '_').replace('\\', '_')
        fp, _ = QFileDialog.getSaveFileName(
            self, f"导出场景 {sname}",
            f"scene_{sid}_{sname}.tkmat",
            "TKMat 场景导出 (*.tkmat);;所有文件 (*.*)")
        if not fp:
            return
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "导出完成",
                                f"场景 {sname} (ID={sid})\n实体: {len(entity_exports)} 个\n"
                                f"DefUnit记录: {len(defunits)} 条\n"
                                f"DEFINE块: {len(defines_export)} 个\n已保存到:\n{fp}")

    def _import_scene(self):
        """导入 .tkmat 文件: 作为全新场景追加"""
        if not self._data.records:
            QMessageBox.warning(self, "无数据", "请先加载 TKS 目录")
            return
        fp, _ = QFileDialog.getOpenFileName(self, "导入场景", "", "TKMat 场景导出 (*.tkmat);;所有文件 (*.*)")
        if not fp:
            return
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"无法解析文件:\n{e}")
            return
        if data.get('format') != 'tkmat_scene_export':
            QMessageBox.critical(self, "格式错误", "不是有效的 .tkmat 场景导出文件")
            return

        n_entities = len(data.get('entities', []))
        n_defunits = len(data.get('defunits', []))
        n_defines = len(data.get('defines', []))
        if QMessageBox.question(self, "确认导入",
                                f"将作为新场景导入:\n  实体: {n_entities} 个\n  DefUnit: {n_defunits} 条\n  DEFINE块: {n_defines} 个\n\n确定继续?",
                                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return

        empty_slots = sorted([i for i, r in enumerate(self._data.records) if r['d0'] == 0], reverse=True)
        empty_slots = sorted(empty_slots[:n_entities])
        if len(empty_slots) < n_entities:
            QMessageBox.critical(self, "空槽不足", f"需要 {n_entities} 个空槽, 但只有 {len(empty_slots)} 个")
            return

        # Build old_entity mapping
        old_entity_ids = []
        for ent in data['entities']:
            chains = ent.get('defunit_chains', {})
            for chain_indices in chains.values():
                if chain_indices:
                    for du_entry in data['defunits']:
                        if du_entry['index'] == chain_indices[0]:
                            old_entity_ids.append(du_entry['fields'][1])
                            break
                    break
        while len(old_entity_ids) < n_entities:
            old_entity_ids.append(-1)
        entity_old_to_new = {}
        for i, old_id in enumerate(old_entity_ids):
            if old_id >= 0:
                entity_old_to_new[old_id] = empty_slots[i]

        # Import DefUnit
        du_old_to_new = {}
        for du_entry in data['defunits']:
            old_du_idx = du_entry['index']
            new_du_idx = len(self._data.defunit_recs)
            du_old_to_new[old_du_idx] = new_du_idx
            fields = du_entry['fields']
            old_f1 = fields[1]
            new_f1 = entity_old_to_new.get(old_f1, old_f1)
            rec = {'index': new_du_idx}
            for fi in range(8):
                val = fields[fi] if fi < len(fields) else 0
                if fi == 1:
                    val = new_f1
                rec[f'f{fi}'] = val
            self._data.defunit_recs.append(rec)
        for du_entry in data['defunits']:
            new_du_idx = du_old_to_new[du_entry['index']]
            old_f6 = du_entry['fields'][6]
            if old_f6 in du_old_to_new:
                du_rec = next((r for r in self._data.defunit_recs if r['index'] == new_du_idx), None)
                if du_rec:
                    du_rec['f6'] = du_old_to_new[old_f6]

        # Import DEFINE
        for d_entry in data['defines']:
            old_did = d_entry['id']
            text = d_entry['text']
            new_did = old_did
            for du_entry in data['defunits']:
                fields = du_entry['fields']
                if (fields[1] << 16) | fields[0] == old_did:
                    new_f1 = entity_old_to_new.get(fields[1], fields[1])
                    new_f0 = fields[0]
                    new_did = (new_f1 << 16) | new_f0
                    break
            if new_did != old_did:
                text = text.replace(f'DEFINE {old_did}', f'DEFINE {new_did}', 1)
            lines = text.replace('\r\n', '\n').split('\n')
            header = ''
            body = []
            for line in lines:
                if line.strip().startswith('DEFINE') and not line.strip().startswith('//'):
                    header = line.rstrip('\r')
                elif header:
                    body.append(line.rstrip('\r'))
            define = {
                'define_id': new_did,
                'comment': '', 'prefix_lines': [],
                'body_lines': body if body else ['{', 'End(0)', '}; end'],
                'line_start': -1, 'line_end': -1,
                'header_line': header if header else f'DEFINE {new_did}',
            }
            self._data.tkd_defines.append(define)
            self._data.tkd_define_map[new_did] = define

        # Import entities
        existing_scenes = {r['d1'] for r in self._data.records if has_data(r) and r['d1'] >= 0}
        new_scene_id = max(existing_scenes) + 1 if existing_scenes else 0
        for i, ent in enumerate(data['entities']):
            slot = empty_slots[i]
            dwords = ent['dwords']
            chains = ent.get('defunit_chains', {})
            rec = self._data.records[slot]
            rec['index'] = slot
            for di in range(min(96, len(dwords))):
                rec[f'd{di}'] = dwords[di]
            rec['d1'] = new_scene_id
            rec['_has_data'] = any(rec[f'd{di}'] for di in range(DWORD_COUNT))
            for chain_name, di in [('A', 39), ('B', 40), ('C', 41)]:
                old_indices = chains.get(chain_name, [])
                if old_indices and old_indices[0] in du_old_to_new:
                    rec[f'd{di}'] = du_old_to_new[old_indices[0]]
                else:
                    rec[f'd{di}'] = -1

        self._data._dirty = True
        self._apply_filter()
        self._vis_populate_scenes()
        self._vis_load_scene()
        QMessageBox.information(self, "导入完成",
                                f"成功导入:\n  实体: {n_entities} 个\n  DefUnit: {n_defunits} 条\n  DEFINE: {n_defines} 个")

    # =========== 窗口缩放事件 ===========
    def resizeEvent(self, event):
        """窗口大小改变时，防抖触发自适应重绘"""
        super().resizeEvent(event)
        if hasattr(self, '_data') and self._data.records:
            self._resize_timer.start(100)

    def _do_resize_redraw(self):
        """防抖定时器触发的真正重绘逻辑"""
        if hasattr(self, '_data') and self._data.records:
            self._canvas._vis_redraw()

    # =========== 关闭事件 ===========
    def closeEvent(self, event):
        self._canvas._vis_stop_anim()
        self._canvas._vis_stop_sel_anim()
        # 退出前提交编辑器未回写内容并检测脚本删除/清空, 防止误删脚本被静默带走 (§防止切换实体误删脚本)
        self._save_editor_to_define()
        deleted = self._detect_deleted_scripts()
        if deleted:
            warn = (f"⚠ 检测到 {len(deleted)} 个脚本相对上次保存/载入已被删除或清空:\n\n"
                    f"{self._format_deleted_scripts(deleted)}\n\n"
                    f"这可能是切换实体等操作导致的误删。\n"
                    f"点「取消」返回检查; 确认放弃这些脚本并退出请点「确定」。")
            box = QMessageBox(QMessageBox.Warning, "脚本删除警告 — 确认退出", warn,
                              QMessageBox.Ok | QMessageBox.Cancel, self)
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                event.ignore()
                return
            event.accept()
            return
        if not confirm_close(self, self._data._dirty or self._script_dirty,
                             text="有未保存的修改 (含脚本), 确定退出?"):
            event.ignore()
            return
        event.accept()


# ============================================================
# 入口
# ============================================================
def main():
    from editor_utils.app_init import ensure_single_instance
    ensure_single_instance()
    from editor_utils.app_init import install_translator, setup_app_icon
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    editor = MatEditorApp()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
