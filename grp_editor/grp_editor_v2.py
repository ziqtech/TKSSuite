#!/usr/bin/env python3
"""
GRP 资源包编辑器 v2 — PySide6 外部主题版
==========================================
格式依据: sub_451600 (GRP加载), sub_411308 (地图加载), sub_410E18 (Frame B RLE)
          sub_452B14 (LZSS), 分析报告 09_GXP_JVG_GRP格式深度对比分析.md

区段类型:
  - 图像区段: Frame A (RGB565 LZSS) + Frame B (RLE byte-pair)
    · Layer 1 = 前景遮挡深度; Layer 2 = 地形碰撞类型 (按值独立着色)
  - 音频区段: WAV 原始数据 (SSF/SWS/SMG.grp)
  - 数据区段: 索引/元数据 (SC.grp 内嵌导航表等)

用法: python grp_editor_v2.py [file.grp]
"""

from __future__ import annotations
import os, sys, struct, zlib, wave, tempfile, shutil, io, math, re, time, base64, subprocess
import winsound
from pathlib import Path
from typing import List, Optional, Tuple
from collections import Counter

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QFrame, QSplitter,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QListWidget,
    QListWidgetItem, QTextEdit, QToolBar, QStatusBar, QMenu, QMenuBar,
    QDialog, QSpinBox, QGridLayout, QSizePolicy, QGraphicsTextItem,
    QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QTranslator
from PySide6.QtGui import (
    QPixmap, QImage, QColor, QIcon, QPainter, QWheelEvent, QPen,
    QBrush, QKeySequence, QAction, QFont
)

HAS_PIL = False
try:    from PIL import Image, ImageDraw, ImageFont; HAS_PIL = True
except ImportError: pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader
from editor_utils.lzss import (lzss_decompress_stream as _lzss_decompress_stream,
                                lzss_compress_stream as _lzss_compress_stream,
                                RING_SIZE, RING_INIT_POS as RING_INIT,
                                RING_INIT_VAL, MIN_MATCH as MIN_MATCH_LZ,
                                MAX_MATCH as MAX_MATCH_LZ)
from editor_utils.rgb565 import rgb565_to_rgba, rgba_to_rgb565
from editor_utils.mod_exporter import (
    compute_crc32, generate_mod_json, pack_tksmod, ModMetadataDialog, safe_mod_filename,
    diff_binary_blocks, build_block_diff_json,
    load_grp_raw_sections,
    get_tksmod_info, import_tksmod_blocks, ModImportPreviewDialog, ModExportPreviewDialog,
)
from editor_utils.window_theme import apply_godot_theme
from editor_utils.ui_helpers import themed_messagebox

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data, target_size): return _lzss_decompress_stream(data, target_size)
def lzss_compress(data): return _lzss_compress_stream(data)

_COLLISION_COLORS = {
    0:(0,0,0,0), 1:(255,0,0,200), 2:(0,200,0,200), 3:(0,100,255,200),
    4:(255,200,0,200), 5:(255,0,255,200), 6:(0,200,200,200), 7:(200,100,0,200),
    8:(128,0,255,200), 9:(150,150,150,200), 10:(255,128,128,200),
}

def _collision_color(val: int):
    if val in _COLLISION_COLORS: return _COLLISION_COLORS[val]
    if val == 0: return (0,0,0,0)
    h = (val * 67 + 150) % 360; x = int(255 * (1 - abs((h / 60) % 2 - 1)))
    r,g,b = [(255,x,0),(x,255,0),(0,255,x),(0,x,255),(x,0,255),(255,0,x)][int(h//60)]
    return (r,g,b,200)

# ═══════════════════════════════════════════════════════════
# 伪彩色映射表 (LUT)
# ═══════════════════════════════════════════════════════════
_L1_VAL2RGB = {}; _L1_RGB2VAL = {}
_L2_VAL2RGB = {}; _L2_RGB2VAL = {}

def _distinct_color(val: int, seed: int) -> tuple:
    if val == 0: return (0, 0, 0)
    hue = ((val * 137.508 + seed * 47) % 360)
    h_sector = hue / 60.0
    x = int(255 * (1 - abs(h_sector % 2 - 1)))
    r, g, b = [(255, x, 0), (x, 255, 0), (0, 255, x),
               (0, x, 255), (x, 0, 255), (255, 0, x)][int(h_sector) % 6]
    return (r, g, b)

for _v in range(256):
    c1 = _distinct_color(_v, seed=31)
    while c1 in _L1_RGB2VAL: c1 = ((c1[0] + 1) % 256, c1[1], c1[2])
    _L1_VAL2RGB[_v] = c1; _L1_RGB2VAL[c1] = _v
    if _v == 0: c2 = (0, 0, 0)
    elif _v in _COLLISION_COLORS:
        r, g, b, _a = _COLLISION_COLORS[_v]; c2 = (r, g, b)
    else: c2 = _distinct_color(_v, seed=73)
    while c2 in _L2_RGB2VAL: c2 = ((c2[0] + 1) % 256, c2[1], c2[2])
    _L2_VAL2RGB[_v] = c2; _L2_RGB2VAL[c2] = _v

def _nearest_color(rgb: tuple, lut_rev: dict) -> int:
    if rgb in lut_rev: return lut_rev[rgb]
    r, g, b = rgb
    best_val, best_dist = 0, 999999
    for color, val in lut_rev.items():
        cr, cg, cb = color
        dist = (r - cr)**2 + (g - cg)**2 + (b - cb)**2
        if dist < best_dist: best_val, best_dist = val, dist
    return best_val


# ═══════════════════════════════════════════════════════════
# RLE 字节对引擎 (GRP 特有, 不提取到 editor_utils)
# ═══════════════════════════════════════════════════════════

def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    out = bytearray(); pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count, value = data[pos], data[pos + 1]; pos += 2; out.extend(bytes([value] * count))
    return bytes(out[:target_size])

def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    total, pos = 0, 0
    while pos + 1 < len(data): total += data[pos]; pos += 2
    return total == expected_size

def rle_bp_compress(data: bytes) -> bytes:
    if not data: return b""
    out = bytearray(); i = 0
    while i < len(data):
        v = data[i]; c = 1
        while i + c < len(data) and data[i + c] == v and c < 255: c += 1
        out.append(c); out.append(v); i += c
    return bytes(out)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class GRPSection:
    def __init__(self, index: int, offset: int, width: int, height: int,
                 comp_a: int, comp_b: int):
        self.index = index; self.offset = offset
        self.width = width; self.height = height; self.comp_a = comp_a; self.comp_b = comp_b
        self.uncomp_a = width * height * 2
        self._pixels: Optional[bytes] = None; self._decoded_a = False
        self._layer1: Optional[bytes] = None; self._layer2: Optional[bytes] = None
        self._decoded_b = False; self.has_layer2 = False
        self._orig_frame_a: Optional[bytes] = None
        self._orig_frame_b: Optional[bytes] = None
        self._orig_fb_declared: int = 0
        self._modified_a = False; self._modified_b = False

    @property
    def pixels(self): return self._pixels
    @property
    def layer1(self): return self._layer1
    @property
    def layer2(self): return self._layer2
    @property
    def is_decoded_a(self): return self._decoded_a
    @property
    def is_decoded_b(self): return self._decoded_b
    @property
    def type_label(self): return f"IMG {self.width}×{self.height}"

class GRPAudioSection:
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index; self.offset = offset; self.size = size; self._raw = raw_data
        self._wav_info = ""; self._duration = 0.0; self._samples: Optional[list] = None

    @property
    def raw(self): return self._raw
    @raw.setter
    def raw(self, v): self._raw = v
    @property
    def type_label(self):
        if self._wav_info: return f"AUD {self._wav_info} {self._duration:.1f}s"
        return f"AUD {self.size}B"
    @property
    def has_samples(self): return self._samples is not None

    def parse_wav(self):
        if not self._raw or len(self._raw) < 44: return
        try:
            f = io.BytesIO(self._raw)
            with wave.open(f, 'rb') as wf:
                ch, sr, sw, nf = wf.getnchannels(), wf.getframerate(), wf.getsampwidth(), wf.getnframes()
                self._wav_info = f"{ch}ch {sr}Hz {sw*8}bit"
                self._duration = nf / sr if sr > 0 else 0
                if nf > 0 and sw > 0:
                    frames = wf.readframes(nf)
                    if sw == 1: fmt, n_per = f"<{len(frames)}b", len(frames)
                    elif sw == 2: fmt, n_per = f"<{len(frames)//2}h", len(frames)//2
                    else: fmt, n_per = f"<{len(frames)//sw}i", len(frames)//sw
                    raw = struct.unpack(fmt, frames[:struct.calcsize(fmt)])
                    if ch == 2:
                        raw = [(raw[i] + raw[i+1]) // 2 for i in range(0, len(raw)-1, 2)]
                    self._samples = list(raw)
        except Exception: pass

class GRPDataSection:
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index; self.offset = offset; self.size = size; self._raw = raw_data

    @property
    def raw(self): return self._raw
    @property
    def type_label(self): return f"DATA {self.size}B"


class GRPFile:
    def __init__(self):
        self.sections: List[GRPSection] = []
        self.audio_sections: List[GRPAudioSection] = []
        self.data_sections: List[GRPDataSection] = []
        self.idx_offsets: List[int] = []
        self.filepath: Optional[str] = None; self.idx_path: Optional[str] = None
        self._raw_data: bytes = b""

    @property
    def total_sections(self):
        return len(self.sections) + len(self.audio_sections) + len(self.data_sections)

    def all_sorted(self):
        items = []
        for s in self.sections: items.append(('IMG', s.index, s))
        for a in self.audio_sections: items.append(('AUD', a.index, a))
        for d in self.data_sections: items.append(('DATA', d.index, d))
        items.sort(key=lambda x: x[1]); return items


# ═══════════════════════════════════════════════════════════
# 文件 I/O
# ═══════════════════════════════════════════════════════════

def load_grp(filepath: str, idx_path: Optional[str] = None) -> GRPFile:
    grp = GRPFile(); grp.filepath = filepath
    grp._raw_data = Path(filepath).read_bytes(); data = grp._raw_data; fsize = len(data)
    if idx_path is None:
        for ext in ['.IDX', '.idx']:
            c = str(Path(filepath).with_suffix(ext))
            if os.path.exists(c): idx_path = c; break
    if idx_path and os.path.exists(idx_path):
        idata = Path(idx_path).read_bytes()
        if len(idata) >= 8 and len(idata) % 4 == 0:
            offs = [struct.unpack_from("<I", idata, i)[0] for i in range(0, len(idata), 4)]
            if offs and offs[-1] == fsize: grp.idx_offsets = offs; grp.idx_path = idx_path
    if grp.idx_offsets:
        num = len(grp.idx_offsets) - 1
        boundaries = [(grp.idx_offsets[i], grp.idx_offsets[i + 1]) for i in range(num)]
    else:
        boundaries = []; off = 0
        while off + 12 <= fsize:
            w, h, ca, cb = struct.unpack_from("<HHII", data, off)
            if w == 0 or h == 0 or w > 4096 or h > 4096: break
            ss = 12 + ca + cb
            if off + ss > fsize: break
            boundaries.append((off, off + ss)); off += ss
        if boundaries: grp.idx_offsets = [b[0] for b in boundaries] + [boundaries[-1][1]]
    for idx, (so, eo) in enumerate(boundaries):
        sz = eo - so
        if sz >= 12:
            w, h, ca, cb = struct.unpack_from("<HHII", data, so)
            if (1 <= w <= 4096 and 1 <= h <= 4096 and
                12 + ca + cb == sz and ca > 0 and cb > 0):
                sec = GRPSection(idx, so, w, h, ca, cb)
                fa_off = so + 12; fb_off = fa_off + ca
                sec._orig_frame_a = data[fa_off:fa_off + ca]
                sec._orig_frame_b = data[fb_off:fb_off + cb]
                if cb >= 4: sec._orig_fb_declared = struct.unpack_from("<I", data, fb_off)[0]
                grp.sections.append(sec); continue
        if sz >= 12 and data[so:so+4] == b"RIFF":
            asec = GRPAudioSection(idx, so, sz, data[so:eo])
            asec.parse_wav(); grp.audio_sections.append(asec); continue
        grp.data_sections.append(GRPDataSection(idx, so, sz, data[so:eo]))
    return grp

def _decode_section_a(grp: GRPFile, sec: GRPSection):
    if sec._decoded_a: return
    data = grp._raw_data; fa_off = sec.offset + 12
    uncomp_sz = struct.unpack_from("<I", data, fa_off)[0]
    lzss_data = data[fa_off + 4:fa_off + sec.comp_a]
    sec._pixels = lzss_decompress(lzss_data, min(uncomp_sz, sec.uncomp_a))
    if len(sec._pixels) < sec.uncomp_a:
        sec._pixels = sec._pixels + b'\x00' * (sec.uncomp_a - len(sec._pixels))
    sec._decoded_a = True

def _decode_section_b(grp: GRPFile, sec: GRPSection):
    if sec._decoded_b: return
    data = grp._raw_data; fb_off = sec.offset + 12 + sec.comp_a
    if fb_off + 4 > len(data): return
    declared = struct.unpack_from("<I", data, fb_off)[0]
    cs, ce = fb_off + 4, fb_off + 4 + sec.comp_b - 4
    comp_data = data[cs:ce]; total_px = sec.width * sec.height
    if rle_bp_probe(comp_data, declared):
        raw = rle_bp_decompress(comp_data, declared)
        sec._layer1 = raw[:total_px]
        if declared == total_px * 2 and len(raw) >= total_px * 2:
            sec._layer2 = raw[total_px:total_px * 2]; sec.has_layer2 = True
    else:
        raw = lzss_decompress(comp_data, sec.uncomp_a)
        sec._layer1 = bytes(raw[i] for i in range(0, min(len(raw), total_px * 2), 2))
    sec._decoded_b = True

def save_grp(grp: GRPFile, filepath: str, idx_path: Optional[str] = None):
    buf = bytearray(); offsets = []
    for kind, idx, obj in grp.all_sorted():
        offsets.append(len(buf))
        if kind == 'IMG':
            sec = obj
            if sec._modified_a and sec._pixels:
                fa_body = lzss_compress(sec._pixels)
                comp_a = len(fa_body) + 4
                fa_data = struct.pack("<I", sec.uncomp_a) + fa_body
            else:
                comp_a = sec.comp_a
                fa_data = sec._orig_frame_a if sec._orig_frame_a else (
                    struct.pack("<I", sec.uncomp_a) + b"\x00" * (sec.comp_a - 4))
            if sec._modified_b:
                if sec.has_layer2 and sec._layer1 and sec._layer2:
                    fb_raw = (sec._layer1 + sec._layer2)[:sec.width * sec.height * 2]
                elif sec._layer1:
                    fb_raw = sec._layer1[:sec.width * sec.height]
                else: fb_raw = b""
                fb_body = rle_bp_compress(fb_raw)
                comp_b = len(fb_body) + 4
                fb_data = struct.pack("<I", len(fb_raw)) + fb_body
            else:
                comp_b = sec.comp_b
                fb_data = sec._orig_frame_b if sec._orig_frame_b else (
                    struct.pack("<I", sec._orig_fb_declared) + b"\x00" * (sec.comp_b - 4))
            buf += struct.pack("<HHII", sec.width, sec.height, comp_a, comp_b)
            buf += fa_data; buf += fb_data
        elif kind == 'AUD':
            if obj._raw: buf += obj._raw
        else:
            if obj._raw: buf += obj._raw
    offsets.append(len(buf))
    Path(filepath).write_bytes(bytes(buf))
    if idx_path is None: idx_path = str(Path(filepath).with_suffix('.idx'))
    idata = bytearray()
    for off in offsets: idata += struct.pack("<I", off)
    Path(idx_path).write_bytes(bytes(idata))


# ═══════════════════════════════════════════════════════════
# PNG 导出
# ═══════════════════════════════════════════════════════════

def _png_chunk(ct: bytes, d: bytes) -> bytes:
    c = ct + d; return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

def export_png_rgba(w, h, rgba, path):
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    stride = w * 4; raw = bytearray(h * (stride + 1))
    for row in range(h):
        out = row * (stride + 1); raw[out] = 0
        raw[out + 1:out + 1 + stride] = rgba[row * stride:(row + 1) * stride]
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)); png += _png_chunk(b"IEND", b"")
    Path(path).write_bytes(png)


# ═══════════════════════════════════════════════════════════
# GUI 组件
# ═══════════════════════════════════════════════════════════

class GRPGraphicsView(QGraphicsView):
    """支持 Ctrl+滚轮缩放、拖拽平移、鼠标位置跟踪的图像视图"""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.editor: Optional[GRPEditor] = None

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            step = 1 if event.angleDelta().y() > 0 else -1
            if self.editor: self.editor._zoom_step(step)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.editor:
            sp = self.mapToScene(event.position().toPoint())
            self.editor._update_pixel_info(sp.x(), sp.y())


# ═══════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════

class GRPEditor(QMainWindow):
    def __init__(self, filepath: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("GRP 资源包编辑器 v2")
        self.resize(1360, 900)

        ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'TKS.ico')
        if os.path.exists(ico_path): self.setWindowIcon(QIcon(ico_path))

        # 主题
        self.theme_manager = ThemeManager()
        app_inst = QApplication.instance()
        if app_inst:
            is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark
            self.theme_manager.current_theme = 'dark' if is_dark else 'light'
        self._is_dark = is_dark

        apply_godot_theme(self, is_dark)
        self._apply_theme()

        # 状态
        self.grp: Optional[GRPFile] = None
        self._sel_idx = -1; self._sel_layer = "A"
        self._zoom = 1.0
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._pil_img = None  # PIL cache
        self._audio_playing = False; self._audio_tmp = None
        self._wave_start_time = 0.0; self._wave_timer: Optional[QTimer] = None

        # 构建 UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()
        self._setup_statusbar()

        if filepath and os.path.exists(filepath): self._open(filepath)
        else: self._new_empty()

    def _apply_theme(self):
        self.setStyleSheet(self.theme_manager.get_stylesheet())

    # ── Menu ──────────────────────────────────────────────
    def _setup_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("打开 GRP... (Ctrl+O)", self._open_dlg, QKeySequence("Ctrl+O"))
        fm.addAction("保存 (Ctrl+S)", self._save, QKeySequence("Ctrl+S"))
        fm.addAction("另存为... (Ctrl+Shift+S)", self._save_as, QKeySequence("Ctrl+Shift+S"))
        fm.addSeparator()
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出选中区段为 MOD (.tksmod)…", self._export_selected_as_mod)
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("导出 L1 色板", lambda: self._export_color_swatch("L1"))
        fm.addAction("导出 L2 色板", lambda: self._export_color_swatch("L2"))
        fm.addSeparator()
        fm.addAction("新增区段...", self._add_section_menu)
        fm.addAction("删除当前区段", self._delete_section)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        vm = mb.addMenu("视图(&V)")
        vm.addAction("原始大小 (100%)", lambda: self._set_zoom(100))
        vm.addAction("适合窗口", self._fit_to_window)
        vm.addAction("放大 (+50%)", lambda: self._zoom_step(1))
        vm.addAction("缩小 (-50%)", lambda: self._zoom_step(-1))

        tm = mb.addMenu("主题(&T)")
        tm.addAction("切换深色/浅色", self._toggle_theme)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("伪彩工作流说明", self._show_pseudo_help)
        hm.addAction("关于 GRP 格式", self._show_about)

    def _toggle_theme(self):
        self.theme_manager.toggle_theme(); self._apply_theme()
        self._is_dark = self.theme_manager.current_theme == 'dark'
        apply_godot_theme(self, self._is_dark)

    # ── Toolbar ───────────────────────────────────────────
    def _setup_toolbar(self):
        tb = QToolBar("主工具栏"); self.addToolBar(tb)
        tb.addAction("📂 打开 GRP", self._open_dlg)
        tb.addAction("💾 保存", self._save)
        tb.addSeparator()

        self._btn_a = tb.addAction("主图", lambda: self._switch_layer("A"))
        self._btn_l1 = tb.addAction("前景层", lambda: self._switch_layer("L1"))
        self._btn_l2 = tb.addAction("碰撞层", lambda: self._switch_layer("L2"))
        tb.addSeparator()

        tb.addAction("🔄 替换当前层", self._replace_layer)
        tb.addAction("📤 导出当前层", self._export_layer)
        self._btn_play_act = tb.addAction("▶️ 播放", self._toggle_audio)
        tb.addAction("🔊 替换音频", self._replace_audio)
        tb.addSeparator()

        tb.addAction("🎨 伪彩导出", self._export_pseudo)
        tb.addAction("🎨 伪彩导入", self._import_pseudo)
        tb.addSeparator()

        tb.addAction("➕ 区段", self._add_section_menu)
        tb.addAction("➖ 区段", self._delete_section)
        tb.addSeparator()

        tb.addAction("🔍−", lambda: self._zoom_step(-1))
        self._zoom_lbl = QLabel(" 100% "); tb.addWidget(self._zoom_lbl)
        tb.addAction("🔍+", lambda: self._zoom_step(1))
        tb.addAction("🔲 适应", self._fit_to_window)
        tb.addSeparator()
        tb.addAction("🌗 切换主题", self._toggle_theme)

    # ── Main UI Layout ────────────────────────────────────
    def _setup_ui(self):
        splitter = QSplitter(Qt.Horizontal); self.setCentralWidget(splitter)

        # LEFT: 区段列表 + 详情
        left_w = QWidget(); left_lay = QVBoxLayout(left_w); left_lay.setContentsMargins(0,0,0,0)
        left_lay.addWidget(DockHeader("区段列表"))
        body = QWidget(); body.setObjectName("DockBody"); body_lay = QVBoxLayout(body)

        self._sec_list = QListWidget()
        self._sec_list.setFont(QFont("Consolas", 9))
        self._sec_list.currentRowChanged.connect(self._on_section_select)
        body_lay.addWidget(self._sec_list, 1)

        self._sec_detail = QTextEdit()
        self._sec_detail.setReadOnly(True)
        self._sec_detail.setFont(QFont("Consolas", 8))
        self._sec_detail.setFixedHeight(120)
        body_lay.addWidget(self._sec_detail)

        left_lay.addWidget(body, 1)
        splitter.addWidget(left_w)

        # RIGHT: 画布 + 色板
        right_w = QWidget(); right_lay = QVBoxLayout(right_w); right_lay.setContentsMargins(0,0,0,0)
        self._scene = QGraphicsScene()
        self._view = GRPGraphicsView(self._scene)
        self._view.editor = self
        right_lay.addWidget(self._view, 1)

        # 色板面板（默认隐藏）
        self._palette_panel = QWidget()
        self._palette_panel.setObjectName("PalettePanel")
        self._palette_panel.setVisible(False)
        palette_lay = QVBoxLayout(self._palette_panel)
        palette_lay.setContentsMargins(4, 4, 4, 4)
        palette_lay.setSpacing(2)
        
        self._palette_title = QLabel("色板")
        self._palette_title.setObjectName("DockTitle")
        palette_lay.addWidget(self._palette_title)
        
        self._palette_scroll = QScrollArea()
        self._palette_scroll.setWidgetResizable(True)
        self._palette_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._palette_container = QWidget()
        self._palette_grid = QGridLayout(self._palette_container)
        self._palette_grid.setSpacing(2)
        self._palette_grid.setContentsMargins(2, 2, 2, 2)
        self._palette_scroll.setWidget(self._palette_container)
        palette_lay.addWidget(self._palette_scroll)
        
        right_lay.addWidget(self._palette_panel)
        splitter.addWidget(right_w)

        splitter.setSizes([280, 1080])
        self._update_buttons()

    # ── Statusbar ─────────────────────────────────────────
    def _setup_statusbar(self):
        sb = self.statusBar()
        self._status_lbl = QLabel("就绪 — 打开 GRP 文件"); self._status_lbl.setObjectName("StatusLabel")
        self._pixel_lbl = QLabel(""); self._pixel_lbl.setObjectName("StatusPixel")
        self._info_lbl = QLabel(""); self._info_lbl.setObjectName("StatusInfo")
        self._hint_lbl = QLabel("Ctrl+滚轮=缩放 | 拖拽=平移"); self._hint_lbl.setObjectName("StatusInfo")
        sb.addWidget(self._status_lbl, 1)
        sb.addPermanentWidget(self._info_lbl)
        sb.addPermanentWidget(self._pixel_lbl)
        sb.addPermanentWidget(self._hint_lbl)

    # ── Button state ──────────────────────────────────────
    def _update_buttons(self):
        is_img = self._is_img(); is_aud = self._is_aud()
        self._btn_a.setEnabled(is_img); self._btn_l1.setEnabled(is_img); self._btn_l2.setEnabled(is_img)
        self._btn_play_act.setEnabled(is_aud)
        names = {"A": "主图", "L1": "前景层", "L2": "碰撞层"}
        for act, key in [(self._btn_a, "A"), (self._btn_l1, "L1"), (self._btn_l2, "L2")]:
            if is_img and self._sel_layer == key:
                act.setText(f"🟢 {names[key]}")
            elif is_img:
                act.setText(f"⚪ {names[key]}")
            else:
                act.setText(names[key])  # 禁用时仅显示文字

    def _is_img(self): return isinstance(self._get_sec(), GRPSection)
    def _is_aud(self): return isinstance(self._get_sec(), GRPAudioSection)

    def _get_sec(self):
        if not self.grp or self._sel_idx < 0: return None
        for s in self.grp.sections:
            if s.index == self._sel_idx: return s
        for a in self.grp.audio_sections:
            if a.index == self._sel_idx: return a
        for d in self.grp.data_sections:
            if d.index == self._sel_idx: return d
        return None

    # ── Section list ──────────────────────────────────────
    def _sync_list(self):
        self._sec_list.blockSignals(True)
        self._sec_list.clear()
        if not self.grp:
            self._sec_list.blockSignals(False); return
        for kind, idx, obj in self.grp.all_sorted():
            self._sec_list.addItem(f"[{kind}] #{idx:03d}  {obj.type_label}")
        if self.grp.total_sections > 0:
            self._sec_list.setCurrentRow(0)
            self._sel_idx = self.grp.all_sorted()[0][1]
            self._refresh_view(); self._update_detail(); self._update_buttons()
        self._sec_list.blockSignals(False)

    def _on_section_select(self, row: int):
        if not self.grp or row < 0: return
        items = self.grp.all_sorted()
        if row < len(items):
            self._sel_idx = items[row][1]
            sec = self._get_sec()
            if isinstance(sec, GRPSection): self._sel_layer = "A"
            self._stop_audio(); self._pil_img = None
            self._pixmap_item = None
            self._refresh_view(); self._update_detail(); self._update_buttons()
            self._update_palette()

    def _update_detail(self):
        sec = self._get_sec()
        if isinstance(sec, GRPSection):
            info = (f"区段 #{sec.index:03d} — 图像\n尺寸: {sec.width}x{sec.height}\n"
                    f"Frame A: {sec.comp_a}B  Frame B: {sec.comp_b}B\n")
            if sec.is_decoded_b:
                info += f"遮罩: {'RLE 双层' if sec.has_layer2 else 'RLE 单层'}\n"
                if sec.layer1:
                    vals = sorted(Counter(sec.layer1).items())
                    info += f"L1值域: {len(vals)}种\n"
                    info += '  ' + ', '.join(f'{v}={c}' for v,c in vals[:8])
                    if len(vals) > 8: info += f' ...共{len(vals)}种'
                    info += '\n'
                if sec.has_layer2 and sec.layer2:
                    vals2 = sorted(Counter(sec.layer2).items())
                    info += f"L2值域: {len(vals2)}种\n"
                    items_txt = [f'#{v}({c}px)' for v,c in vals2[:8]]
                    info += '  ' + ', '.join(items_txt)
                    if len(vals2) > 8: info += f' ...共{len(vals2)}种'
                    info += '\n'
            info += f"A:{'OK' if sec.is_decoded_a else '待解码'} B:{'OK' if sec.is_decoded_b else '待解码'}"
        elif isinstance(sec, GRPAudioSection):
            info = f"区段 #{sec.index:03d} — 音频\n大小: {sec.size}B"
            if sec._wav_info: info += f"\n格式: {sec._wav_info}\n时长: {sec._duration:.2f}s"
        elif isinstance(sec, GRPDataSection):
            info = f"区段 #{sec.index:03d} — 数据\n大小: {sec.size}B\n(索引/元数据, 不可编辑)"
        else: info = "(无选中)"
        self._sec_detail.setPlainText(info)

    # ── File ops ──────────────────────────────────────────
    def _new_empty(self):
        self.grp = GRPFile(); self._sync_list(); self._sel_idx = -1; self._refresh_view()
        self.setWindowTitle("GRP 编辑器 v2 — [新建]")

    def _open_dlg(self):
        p, _ = QFileDialog.getOpenFileName(self, "打开 GRP", "", "GRP (*.grp *.GRP);;All (*.*)")
        if p: self._open(p)

    def _open(self, p: str):
        try:
            self._status_lbl.setText(f"加载中: {Path(p).name}..."); QApplication.processEvents()
            self._stop_audio(); self.grp = load_grp(p)
            self._sel_idx = -1; self._sel_layer = "A"
            self._sync_list(); self._refresh_view()
            ni, na, nd = len(self.grp.sections), len(self.grp.audio_sections), len(self.grp.data_sections)
            extra = f"  ({ni}IMG + {na}AUD" + (f" + {nd}DATA" if nd else "") + ")"
            id_info = f"  |  IDX: {Path(self.grp.idx_path).name}" if self.grp.idx_path else ""
            self._status_lbl.setText(f"已加载: {Path(p).name}  |  {self.grp.total_sections} sections{extra}{id_info}")
            self.setWindowTitle(f"GRP 编辑器 v2 — {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e)); import traceback; traceback.print_exc()

    def _save(self):
        if not self.grp: return
        if self.grp.filepath: self._do_save(self.grp.filepath, self.grp.idx_path)
        else: self._save_as()

    def _save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "保存 GRP", "", "GRP (*.grp)")
        if p: self._do_save(p, str(Path(p).with_suffix('.idx')))

    def _do_save(self, grp_path, idx_path=None):
        try:
            self._status_lbl.setText("压缩中..."); QApplication.processEvents()
            save_grp(self.grp, grp_path, idx_path)
            self.grp.filepath = grp_path; self.grp.idx_path = idx_path
            self._status_lbl.setText(f"已保存: {Path(grp_path).name} ({os.path.getsize(grp_path)/1024:.1f}KB)")
        except Exception as e: QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出 GRP 为 .tksmod — 区段级增量（仅导出修改过的区段）"""
        if not self.grp or not self.grp.filepath:
            QMessageBox.information(self, "提示", "请先打开 GRP 文件"); return

        target_name = os.path.basename(self.grp.filepath)

        # 先保存当前到临时文件获取当前区段
        tmp_grp = tempfile.mktemp(suffix='.grp')
        tmp_idx = tempfile.mktemp(suffix='.idx')
        try:
            save_grp(self.grp, tmp_grp, tmp_idx)
            cur_sections = load_grp_raw_sections(tmp_grp, tmp_idx)
        finally:
            for p in [tmp_grp, tmp_idx]:
                if os.path.exists(p): os.remove(p)
        if cur_sections is None:
            QMessageBox.warning(self, "错误", "无法序列化当前 GRP 数据"); return

        def _compute_stats(ref_dir):
            ref_path = os.path.join(ref_dir, target_name)
            if not os.path.isfile(ref_path):
                return {"valid": False, "error": f"目录中未找到 {target_name}"}
            ref_idx = None
            for ext in ['.IDX', '.idx']:
                c = str(Path(ref_path).with_suffix(ext))
                if os.path.exists(c): ref_idx = c; break
            ref_sections = load_grp_raw_sections(ref_path, ref_idx)
            if ref_sections is None:
                return {"valid": False, "error": f"无法解析 {target_name}（需要配套 IDX 文件）"}
            diff = diff_binary_blocks(ref_sections, cur_sections)
            targets = []
            if diff['modified'] or diff['appended'] or diff['deleted_indices']:
                targets.append({"name": target_name,
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": len(diff['deleted_indices'])})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.grp.filepath) if self.grp and self.grp.filepath else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_path = os.path.join(ref_dir, target_name)
        if not os.path.isfile(ref_path):
            QMessageBox.warning(self, "参考文件不存在", f"在 {ref_dir} 中未找到 {target_name}"); return

        # 查找参考 IDX
        ref_idx = None
        for ext in ['.IDX', '.idx']:
            c = str(Path(ref_path).with_suffix(ext))
            if os.path.exists(c): ref_idx = c; break

        ref_sections = load_grp_raw_sections(ref_path, ref_idx)
        if ref_sections is None:
            QMessageBox.warning(self, "参考文件无效", f"无法解析 {target_name} 的区段结构（需要配套 IDX 文件）"); return

        # 保存当前到临时文件获取当前区段
        tmp_grp = tempfile.mktemp(suffix='.grp')
        tmp_idx = tempfile.mktemp(suffix='.idx')
        try:
            save_grp(self.grp, tmp_grp, tmp_idx)
            cur_sections = load_grp_raw_sections(tmp_grp, tmp_idx)
        finally:
            for p in [tmp_grp, tmp_idx]:
                if os.path.exists(p): os.remove(p)

        if cur_sections is None:
            QMessageBox.warning(self, "错误", "无法序列化当前 GRP 数据"); return

        # 计算区段级差异
        diff_result = diff_binary_blocks(ref_sections, cur_sections)
        if not diff_result['modified'] and not diff_result['appended'] and not diff_result['deleted_indices']:
            QMessageBox.information(self, "无差异", "当前 GRP 与参考文件相同，无需导出。"); return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata(); self._last_mod_metadata = metadata

        crc = compute_crc32(ref_path)
        data_json = build_block_diff_json(target=target_name, block_type="grp_section",
            original_count=len(ref_sections), original_crc32=crc, diff_result=diff_result)
        internal_path = f"data/{target_name}.json"
        components = [{"file": internal_path, "target": target_name}]
        mod_json = generate_mod_json(metadata, components)

        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {internal_path: data_json})
            n_mod = len(diff_result['modified']); n_app = len(diff_result['appended'])
            self._status_lbl.setText(f"已导出 MOD: {Path(fp).name} (修改{n_mod}区段, 新增{n_app}区段)")
            QMessageBox.information(self, "导出成功",
                f"已导出 (区段级增量):\n{fp}\n\n参考: {ref_path}\n修改: {n_mod} 个区段\n新增: {n_app} 个区段")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_selected_as_mod(self):
        """导出当前选中区段为 .tksmod — 块级增量模式，launcher 可正确合并到目标文件"""
        if not self.grp or self._sel_idx < 0:
            QMessageBox.information(self, "提示", "请先选中一个区段"); return

        sec = self._get_sec()
        if sec is None:
            QMessageBox.information(self, "提示", "请先选中一个区段"); return

        if not self.grp.filepath:
            QMessageBox.information(self, "提示",
                "请先打开一个 GRP 文件（需要原始文件名作为 MOD 合并目标）"); return

        # 步骤1: 序列化选中区段 → 临时 GRP → 提取原始区段字节
        tmp_grp = GRPFile()
        if isinstance(sec, GRPSection):
            new_sec = GRPSection(0, 0, sec.width, sec.height, sec.comp_a, sec.comp_b)
            new_sec._orig_frame_a = sec._orig_frame_a
            new_sec._orig_frame_b = sec._orig_frame_b
            new_sec._orig_fb_declared = sec._orig_fb_declared
            if sec._modified_a and sec._pixels:
                new_sec._pixels = sec._pixels
                new_sec._decoded_a = True
                new_sec._modified_a = True
            if sec._modified_b:
                new_sec._layer1 = sec._layer1
                new_sec._layer2 = sec._layer2
                new_sec.has_layer2 = sec.has_layer2
                new_sec._decoded_b = True
                new_sec._modified_b = True
            tmp_grp.sections.append(new_sec)
        elif isinstance(sec, GRPAudioSection):
            new_sec = GRPAudioSection(0, 0, sec.size, sec._raw)
            new_sec._wav_info = sec._wav_info
            new_sec._duration = sec._duration
            tmp_grp.audio_sections.append(new_sec)
        elif isinstance(sec, GRPDataSection):
            new_sec = GRPDataSection(0, 0, sec.size, sec._raw)
            tmp_grp.data_sections.append(new_sec)

        tmp_grp_path = tempfile.mktemp(suffix='.grp')
        tmp_idx_path = tempfile.mktemp(suffix='.idx')
        try:
            save_grp(tmp_grp, tmp_grp_path, tmp_idx_path)
            cur_sections = load_grp_raw_sections(tmp_grp_path, tmp_idx_path)
            if not cur_sections:
                QMessageBox.warning(self, "错误", "无法序列化选中区段"); return
            section_bytes = cur_sections[0]

            # 步骤2: 构建 block_diff — launcher 会加载游戏原文件并替换指定索引的区段
            target_name = os.path.basename(self.grp.filepath)
            diff_result = {
                "modified": [{"index": sec.index,
                              "data_b64": base64.b64encode(section_bytes).decode('ascii')}],
                "appended": [],
                "deleted_indices": [],
            }

            crc = compute_crc32(self.grp.filepath)
            data_json = build_block_diff_json(
                target=target_name, block_type="grp_section",
                original_count=self.grp.total_sections, original_crc32=crc,
                diff_result=diff_result)

            # 步骤3: MOD 元数据
            dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
            if dlg.exec() != QDialog.Accepted: return
            metadata = dlg.get_metadata(); self._last_mod_metadata = metadata

            internal_path = f"data/{target_name}.json"
            mod_json = generate_mod_json(metadata,
                [{"file": internal_path, "target": target_name}])

            fp, _ = QFileDialog.getSaveFileName(self, "导出选中区段为 MOD",
                f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
            if not fp: return

            pack_tksmod(fp, mod_json, {internal_path: data_json})

            self._status_lbl.setText(
                f"已导出 MOD: {Path(fp).name} (区段 #{sec.index:03d} → {target_name})")
            QMessageBox.information(self, "导出成功",
                f"已导出选中区段为 MOD (块级合并):\n{fp}\n\n"
                f"目标文件: {target_name}\n区段: #{sec.index:03d} ({sec.type_label})\n\n"
                f"Launcher 加载时将替换 {target_name} 的第 {sec.index} 个区段。")
        finally:
            for p in [tmp_grp_path, tmp_idx_path]:
                if os.path.exists(p): os.remove(p)

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到 GRP 编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件"); return

        # 查找 GRP 类型的 target
        grp_targets = [t for t in info.get("targets", []) if t.upper().endswith(".GRP")]
        if not grp_targets:
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 GRP 文件的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}"); return

        target_name = grp_targets[0]

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.grp.filepath) if self.grp and self.grp.filepath else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, blocks = import_tksmod_blocks(
            fp, ref_dir, target_name, block_type="grp_section")
        if blocks is None:
            QMessageBox.warning(self, "导入失败",
                f"无法导入 MOD 数据。\n请确认参考目录中包含有效的 {target_name}"); return

        # 将区段列表重建为临时 GRP+IDX 文件，然后重新加载
        tmp_grp = tempfile.mktemp(suffix='.grp')
        tmp_idx = tempfile.mktemp(suffix='.idx')
        try:
            # 重建 GRP: 拼接所有区段
            offsets = [0]
            for sec in blocks:
                offsets.append(offsets[-1] + len(sec))
            # 写入 IDX
            idx_data = b''.join(struct.pack('<I', off) for off in offsets)
            Path(tmp_idx).write_bytes(idx_data)
            # 写入 GRP
            with open(tmp_grp, 'wb') as f:
                for sec in blocks:
                    f.write(sec)

            self._stop_audio()
            self.grp = load_grp(tmp_grp, tmp_idx)
            self.grp.filepath = None
            self.grp.idx_path = None
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"重建 GRP 数据失败: {e}"); return
        finally:
            for p in [tmp_grp, tmp_idx]:
                if os.path.exists(p): os.remove(p)

        # 记住 MOD 元数据
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._sync_list()
        self._status_lbl.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{target_name}: {len(blocks)} 个区段")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"目标: {target_name}\n"
            f"区段数: {len(blocks)}\n\n"
            f"您现在可以继续编辑并重新导出。")

    def closeEvent(self, event):
        self._stop_audio(); super().closeEvent(event)

    # ── Layer switching ───────────────────────────────────
    def _switch_layer(self, layer: str):
        if not self._is_img(): return
        self._sel_layer = layer; self._pil_img = None; self._pixmap_item = None
        self._update_buttons(); self._refresh_view(); self._update_detail()
        self._update_palette()

    def _update_palette(self):
        """更新色板面板显示"""
        sec = self._get_sec()
        if not isinstance(sec, GRPSection) or self._sel_layer == "A":
            self._palette_panel.setVisible(False)
            return

        # 确保层数据已解码
        if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
        data = sec.layer1 if self._sel_layer == "L1" else sec.layer2
        if not data:
            self._palette_panel.setVisible(False)
            return

        # 统计当前图像中使用的值
        used_vals = sorted(Counter(data[:sec.width * sec.height]).keys())
        if not used_vals:
            self._palette_panel.setVisible(False)
            return

        # 更新标题
        layer_name = "前景层 (遮挡深度)" if self._sel_layer == "L1" else "碰撞层 (地形类型)"
        self._palette_title.setText(f"色板 — {layer_name} ({len(used_vals)}种值)")

        # 清空现有色板项
        while self._palette_grid.count():
            item = self._palette_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # 获取颜色映射
        lut = _L1_VAL2RGB if self._sel_layer == "L1" else _L2_VAL2RGB

        # 创建色板项
        cols = 8  # 每行8个色块
        for idx, val in enumerate(used_vals):
            row, col = divmod(idx, cols)
            
            # 创建色块容器
            item_w = QWidget()
            item_lay = QHBoxLayout(item_w)
            item_lay.setContentsMargins(2, 2, 2, 2)
            item_lay.setSpacing(4)
            
            # 色块
            color_label = QLabel()
            color_label.setFixedSize(24, 24)
            color = lut.get(val, (0, 0, 0))
            color_label.setProperty("class", "ColorSwatch")
            color_label.setStyleSheet(f"background-color: rgb({color[0]},{color[1]},{color[2]});")
            item_lay.addWidget(color_label)
            
            # 值标签
            val_label = QLabel(f"{val}")
            val_label.setFont(QFont("Consolas", 9, QFont.Bold))
            val_label.setAlignment(Qt.AlignCenter)
            val_label.setMinimumWidth(20)
            item_lay.addWidget(val_label)
            
            # 描述标签
            desc_text = ""
            if self._sel_layer == "L1":
                if val == 0: desc_text = "无遮挡"
                else: desc_text = f"深度{val}"
            else:
                if val == 0: desc_text = "类型0"
                else: desc_text = f"类型{val}"
            desc_label = QLabel(desc_text)
            desc_label.setFont(QFont("Microsoft YaHei", 8))
            item_lay.addWidget(desc_label, 1)
            
            self._palette_grid.addWidget(item_w, row, col)

        # 调整面板高度
        rows = (len(used_vals) - 1) // cols + 1
        self._palette_panel.setFixedHeight(min(200, rows * 36 + 40))
        self._palette_panel.setVisible(True)

    # ── Layer RGBA ────────────────────────────────────────
    def _get_layer_rgba(self, sec: GRPSection, layer: str) -> Optional[bytearray]:
        w, h = sec.width, sec.height; total = w * h
        if layer == "A":
            if not sec.is_decoded_a: _decode_section_a(self.grp, sec)
            if sec.pixels: return rgb565_to_rgba(sec.pixels, w, h)
            return bytearray(total * 4)
        elif layer in ("L1", "L2"):
            if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
            data = sec.layer1 if layer == "L1" else sec.layer2
            if not data: return None
            rgba = bytearray(total * 4)
            if layer == "L1":
                for i in range(min(len(data), total)):
                    c = _L1_VAL2RGB.get(data[i], (0, 0, 0))
                    rgba[i*4] = c[0]; rgba[i*4+1] = c[1]; rgba[i*4+2] = c[2]
                    rgba[i*4+3] = 220  # 所有颜色都使用相同的 alpha 值
            else:
                for i in range(min(len(data), total)):
                    c = _L2_VAL2RGB.get(data[i], (0, 0, 0))
                    rgba[i*4] = c[0]; rgba[i*4+1] = c[1]; rgba[i*4+2] = c[2]
                    rgba[i*4+3] = 220  # 所有颜色都使用相同的 alpha 值
            return rgba
        return None

    # ── Canvas refresh ────────────────────────────────────
    _MAX_DISPLAY_DIM = 1200

    def _refresh_view(self):
        self._scene.clear()
        self._pixmap_item = None
        sec = self._get_sec()
        if not sec: return

        if isinstance(sec, GRPDataSection):
            self._scene.addText("数据区段 (不可预览)")
            return

        if isinstance(sec, GRPAudioSection):
            self._draw_audio_view(sec); return

        if isinstance(sec, GRPSection):
            w, h = sec.width, sec.height
            rgba = self._get_layer_rgba(sec, self._sel_layer)
            if rgba is None:
                self._scene.addText("碰撞层不可用 (单层遮罩)")
                return

            img = QImage(bytes(rgba), w, h, w * 4, QImage.Format_RGBA8888)
            img = img.copy()
            pm = QPixmap.fromImage(img)

            z = self._zoom
            max_dim = max(w, h)
            auto_scale = min(1.0, self._MAX_DISPLAY_DIM / max_dim) if max_dim > self._MAX_DISPLAY_DIM else 1.0
            disp_scale = z * auto_scale
            sw, sh = max(1, int(w * disp_scale)), max(1, int(h * disp_scale))
            if disp_scale != 1.0:
                pm = pm.scaled(sw, sh, Qt.KeepAspectRatio, Qt.FastTransformation)

            self._pixmap_item = self._scene.addPixmap(pm)
            self._pixmap_item.setOffset(-sw // 2, -sh // 2)
            self._scene.setSceneRect(QRectF(-sw // 2 - 20, -sh // 2 - 20, sw + 40, sh + 40))

            # 为 L1/L2 层添加序号标注（每个连续区域标注一个数字）
            if self._sel_layer in ("L1", "L2"):
                font_size = 14  # 固定字号，不随图片尺寸/缩放变化
                text_pen = QPen(QColor(255, 255, 255, 240))
                shadow_pen = QPen(QColor(0, 0, 0, 200))

                # 获取层数据
                layer_data = sec.layer1 if self._sel_layer == "L1" else sec.layer2
                if layer_data:
                    # 记录已访问的像素
                    visited = bytearray(w * h)  # 使用 bytearray 提高性能
                    
                    # 存储所有需要标注的区域 [(val, center_x, center_y), ...]
                    annotations = []
                    
                    # 泛洪填充找连通区域
                    def flood_fill(start_x, start_y, target_val):
                        stack = [(start_x, start_y)]
                        region = []
                        while stack:
                            x, y = stack.pop()
                            if x < 0 or x >= w or y < 0 or y >= h:
                                continue
                            idx = y * w + x
                            if visited[idx]:
                                continue
                            if idx >= len(layer_data) or layer_data[idx] != target_val:
                                continue
                            visited[idx] = 1
                            region.append((x, y))
                            stack.extend([(x+1,y),(x-1,y),(x,y+1),(x,y-1)])
                        return region

                    # 遍历图像，找每个连续区域
                    min_region_size = max(16, int(64 / (disp_scale * z))) if (disp_scale * z) > 0 else 16
                    
                    for py in range(h):
                        for px in range(w):
                            idx = py * w + px
                            if visited[idx]:
                                continue
                            if idx >= len(layer_data):
                                visited[idx] = 1
                                continue
                            val = layer_data[idx]
                            if val == 0:  # 跳过空白区域
                                visited[idx] = 1
                                continue
                            
                            # 找到连续区域
                            region = flood_fill(px, py, val)
                            if len(region) < min_region_size:
                                continue  # 跳过太小的区域
                            
                            # 计算区域中心
                            cx = sum(p[0] for p in region) / len(region)
                            cy = sum(p[1] for p in region) / len(region)
                            
                            # 记录该区域的标注信息
                            annotations.append((val, cx, cy))

                    # 为每个区域添加标注
                    for val, cx, cy in annotations:
                        scene_x = (cx - w / 2) * disp_scale
                        scene_y = (cy - h / 2) * disp_scale

                        # 添加阴影文本（黑色描边效果）
                        for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1)]:
                            shadow = self._scene.addText(str(val))
                            shadow.setFont(QFont("Consolas", font_size, QFont.Bold))
                            shadow.setDefaultTextColor(shadow_pen.color())
                            shadow.setPos(scene_x + dx, scene_y + dy)

                        # 添加主文本
                        text_item = self._scene.addText(str(val))
                        text_item.setFont(QFont("Consolas", font_size, QFont.Bold))
                        text_item.setDefaultTextColor(text_pen.color())
                        text_item.setPos(scene_x, scene_y)

            self._zoom_lbl.setText(f" {int(z*100)}% ")
            names = {"A": "主图", "L1": "前景层 (遮挡)", "L2": "碰撞层 (地形)"}
            self._info_lbl.setText(f"#{sec.index:03d} {w}x{h} | {names.get(self._sel_layer,'')}")

    def _draw_audio_view(self, sec: GRPAudioSection):
        self._scene.clear()
        vw = self._view.viewport().width() or 400
        vh = self._view.viewport().height() or 300
        margin_l, margin_r = 10, 10  # 减小边距，靠左上对齐
        wave_w = vw - margin_l - margin_r
        wave_top, wave_h = 30, vh - 80
        wave_mid = wave_top + wave_h // 2

        info = f"音频 #{sec.index:03d}  |  {sec.size}B"
        if sec._wav_info: info += f"  |  {sec._wav_info}"
        if sec._duration > 0: info += f"  |  {sec._duration:.2f}s"
        txt = self._scene.addText(info)
        txt.setPos(margin_l, 5)  # 左对齐

        self._scene.addRect(margin_l, wave_top, wave_w, wave_h,
                            QPen(QColor("#444")), QBrush(QColor("#1a1a1a")))

        if sec.has_samples and sec._samples:
            samples = sec._samples; n = len(samples)
            max_val = max(abs(min(samples)), abs(max(samples)), 1)
            half_h = wave_h // 2 - 6
            px_per_col = max(1, n / wave_w)
            pen_normal = QPen(QColor("#607890")); pen_normal.setWidth(1)
            pen_played = QPen(QColor("#4a9eff")); pen_played.setWidth(1)

            played_cols = 0
            if self._audio_playing and sec._duration > 0:
                elapsed = time.time() - self._wave_start_time
                played_cols = int(min(elapsed / sec._duration, 1.0) * wave_w)

            cols_data = []
            for col in range(wave_w):
                si = int(col * px_per_col)
                ei = min(n, int((col + 1) * px_per_col))
                if si >= n: break
                seg = samples[si:ei]
                cols_data.append((min(seg), max(seg)) if seg else (0, 0))

            for ci, (vmin, vmax) in enumerate(cols_data):
                x = margin_l + ci
                y_top = wave_mid - int((vmax / max_val) * half_h)
                y_bot = wave_mid - int((vmin / max_val) * half_h)
                if y_top == y_bot: y_top -= 1
                pen = pen_played if ci <= played_cols else pen_normal
                self._scene.addLine(x, y_top, x, y_bot, pen)

            dash_pen = QPen(QColor("#555"), 1, Qt.DashLine)
            self._scene.addLine(margin_l, wave_mid, margin_l + wave_w, wave_mid, dash_pen)

            tl_y = wave_top + wave_h + 8
            self._scene.addLine(margin_l, tl_y, margin_l + wave_w, tl_y, QPen(QColor("#666")))
            if sec._duration > 0:
                for tick_sec in range(0, int(sec._duration) + 2):
                    tx = margin_l + int((tick_sec / sec._duration) * wave_w)
                    if tx <= margin_l + wave_w:
                        self._scene.addLine(tx, tl_y, tx, tl_y + 6, QPen(QColor("#888")))
                        t = self._scene.addText(f"{tick_sec}s")
                        t.setDefaultTextColor(QColor("#888")); t.setPos(tx - 8, tl_y + 8)

            if self._audio_playing and sec._duration > 0:
                elapsed = time.time() - self._wave_start_time
                progress = min(elapsed / sec._duration, 1.0)
                px = margin_l + int(progress * wave_w)
                red_pen = QPen(QColor("#ff3040"), 2)
                self._scene.addLine(px, wave_top, px, wave_top + wave_h, red_pen)
                self._scene.addPolygon(
                    [QPointF(px-5, wave_top), QPointF(px+5, wave_top), QPointF(px, wave_top+8)],
                    QPen(QColor("#ff3040")), QBrush(QColor("#ff3040")))
        
        # 设置场景矩形，确保音频内容靠左上角显示
        self._scene.setSceneRect(0, 0, vw, vh)

    def _update_pixel_info(self, sx: float, sy: float):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection):
            self._pixel_lbl.setText(""); return
        w, h = sec.width, sec.height; z = self._zoom
        max_dim = max(w, h)
        auto_scale = min(1.0, self._MAX_DISPLAY_DIM / max_dim) if max_dim > self._MAX_DISPLAY_DIM else 1.0
        disp_scale = z * auto_scale
        sw, sh = max(1, int(w * disp_scale)), max(1, int(h * disp_scale))
        px = int((sx + sw // 2) / disp_scale) if disp_scale > 0 else 0
        py = int((sy + sh // 2) / disp_scale) if disp_scale > 0 else 0
        if 0 <= px < w and 0 <= py < h:
            idx = py * w + px
            if self._sel_layer == "A" and sec.is_decoded_a and sec.pixels and idx * 2 + 1 < len(sec.pixels):
                lo, hi = sec.pixels[idx*2], sec.pixels[idx*2+1]; v = lo | (hi << 8)
                r5, g6, b5 = (v>>11)&0x1F, (v>>5)&0x3F, v&0x1F
                self._pixel_lbl.setText(f"({px},{py}) #565=0x{v:04X} RGB=({r5<<3},{g6<<2},{b5<<3})")
            elif self._sel_layer == "L1" and sec.layer1 and idx < len(sec.layer1):
                self._pixel_lbl.setText(f"({px},{py}) 深度={sec.layer1[idx]}")
            elif self._sel_layer == "L2" and sec.layer2 and idx < len(sec.layer2):
                self._pixel_lbl.setText(f"({px},{py}) 碰撞类型={sec.layer2[idx]}")
            else: self._pixel_lbl.setText(f"({px},{py})")
        else: self._pixel_lbl.setText("")

    # ── Zoom & Pan ────────────────────────────────────────
    def _set_zoom(self, pct: int):
        """设置缩放比例，对齐到 50% 步进，范围 50%~300%"""
        pct = int(pct)
        pct = max(50, min(300, pct))
        pct = round(pct / 50) * 50  # 对齐到最近的 50% 步进
        self._zoom = pct / 100.0; self._pil_img = None
        self._pixmap_item = None; self._refresh_view()

    def _zoom_step(self, step: int):
        """按整数百分比步进缩放 (step: ±1 表示 ±50%)"""
        current_pct = round(self._zoom * 100)
        self._set_zoom(current_pct + step * 50)

    def _fit_to_window(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection): return
        vw = (self._view.viewport().width() or 800) - 40
        vh = (self._view.viewport().height() or 600) - 40
        z = min(3.0, vw / max(sec.width, 1), vh / max(sec.height, 1))
        self._set_zoom(max(50, int(z * 100)))

    # ── Audio ─────────────────────────────────────────────
    def _toggle_audio(self):
        if self._audio_playing: self._stop_audio(); return
        sec = self._get_sec()
        if not isinstance(sec, GRPAudioSection) or not sec._raw or len(sec._raw) < 44: return
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False); tmp.close()
            Path(tmp.name).write_bytes(sec._raw)
            self._audio_tmp = tmp.name
            self._wave_start_time = time.time()
            if sys.platform == 'win32':
                winsound.PlaySound(tmp.name, winsound.SND_ASYNC | winsound.SND_FILENAME)
            else:
                player = 'aplay' if shutil.which('aplay') else ('afplay' if sys.platform == 'darwin' else 'paplay')
                self._audio_proc = subprocess.Popen([player, tmp.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._audio_playing = True; self._btn_play_act.setText("⏹ 停止")
            self._draw_audio_view(sec)
            self._start_wave_timer(sec)
        except Exception as e:
            self._status_lbl.setText(f"播放失败: {e}")

    def _start_wave_timer(self, sec: GRPAudioSection):
        if self._wave_timer: self._wave_timer.stop()
        self._wave_timer = QTimer(self)
        self._wave_timer.timeout.connect(lambda: self._wave_tick(sec))
        self._wave_timer.start(80)

    def _wave_tick(self, sec: GRPAudioSection):
        if not self._audio_playing:
            if self._wave_timer: self._wave_timer.stop(); self._wave_timer = None
            return
        dur = sec._duration if sec._duration > 0 else 1.0
        elapsed = time.time() - self._wave_start_time
        if elapsed >= dur + 0.15:
            self._stop_audio()
        else:
            self._draw_audio_view(sec)

    def _stop_audio(self):
        if not self._audio_playing: return
        try:
            if sys.platform == 'win32':
                winsound.PlaySound(None, winsound.SND_PURGE)
            elif hasattr(self, '_audio_proc') and self._audio_proc:
                self._audio_proc.terminate(); self._audio_proc = None
        except: pass
        self._audio_playing = False
        self._btn_play_act.setText("▶️ 播放")
        if self._wave_timer: self._wave_timer.stop(); self._wave_timer = None
        if self._audio_tmp:
            try: os.unlink(self._audio_tmp)
            except: pass
            self._audio_tmp = None
        sec = self._get_sec()
        if isinstance(sec, GRPAudioSection): self._draw_audio_view(sec)

    def _replace_audio(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPAudioSection): return
        p, _ = QFileDialog.getOpenFileName(self, "替换 WAV", "", "WAV (*.wav);;All (*.*)")
        if not p: return
        try:
            raw = Path(p).read_bytes()
            sec._raw = raw; sec._samples = None; sec.parse_wav()
            self._sync_list(); self._update_detail(); self._refresh_view()
            self._status_lbl.setText(f"音频已替换 → {Path(p).name} ({len(raw)}B)")
        except Exception as e: QMessageBox.critical(self, "替换失败", str(e))

    def _export_audio(self, sec: GRPAudioSection):
        p, _ = QFileDialog.getSaveFileName(self, "导出音频", f"sec{sec.index:03d}_audio.wav", "WAV (*.wav)")
        if not p: return
        if sec._raw: Path(p).write_bytes(sec._raw); self._status_lbl.setText(f"已导出: {Path(p).name}")

    # ── Replace / Export ──────────────────────────────
    def _replace_layer(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection): return
        if self._sel_layer == "A": self._replace_frame_a(sec)
        elif self._sel_layer in ("L1", "L2"): self._replace_layer_byte(sec, self._sel_layer)

    def _replace_frame_a(self, sec: GRPSection):
        p, _ = QFileDialog.getOpenFileName(self, "替换主图", "", "图片 (*.png *.bmp *.jpg)")
        if not p: return
        try:
            img = Image.open(p).convert("RGBA")
            if img.size != (sec.width, sec.height):
                if QMessageBox.question(self, "尺寸不匹配",
                    f"导入 {img.size[0]}×{img.size[1]} ≠ 原 {sec.width}×{sec.height}。缩放?") != QMessageBox.Yes: return
                img = img.resize((sec.width, sec.height), Image.LANCZOS)
            sec._pixels = rgba_to_rgb565(img.tobytes(), sec.width, sec.height)
            sec._decoded_a = True; sec._modified_a = True
            self._pil_img = None; self._pixmap_item = None
            self._refresh_view(); self._status_lbl.setText(f"Frame A 已替换 → {Path(p).name}")
        except Exception as e: QMessageBox.critical(self, "替换失败", str(e))

    def _replace_layer_byte(self, sec: GRPSection, layer: str):
        p, _ = QFileDialog.getOpenFileName(self,
            f"替换 {layer} (灰度图, 像素值=游戏数据值)", "", "图片 (*.png *.bmp *.jpg)")
        if not p: return
        try:
            img = Image.open(p)
            if img.mode == "P": data = img.tobytes()
            else:
                img = img.convert("L"); data = img.tobytes()
            if img.size != (sec.width, sec.height):
                if QMessageBox.question(self, "尺寸不匹配",
                    f"导入 {img.size[0]}×{img.size[1]} ≠ 原 {sec.width}×{sec.height}。缩放?") != QMessageBox.Yes: return
                img2 = Image.frombytes("L", img.size, data) if img.mode != "P" else img
                img2 = img2.resize((sec.width, sec.height), Image.NEAREST)
                data = img2.tobytes()
            if layer == "L1": sec._layer1 = data
            else: sec._layer2 = data; sec.has_layer2 = True
            sec._decoded_b = True; sec._modified_b = True
            self._pil_img = None; self._pixmap_item = None
            self._refresh_view(); self._update_detail()
            self._status_lbl.setText(f"{layer} 已替换 → {Path(p).name} (精确值映射)")
        except Exception as e: QMessageBox.critical(self, "替换失败", str(e))

    def _export_layer(self):
        sec = self._get_sec()
        if sec is None: return
        if isinstance(sec, GRPAudioSection): self._export_audio(sec); return
        if isinstance(sec, GRPDataSection):
            p, _ = QFileDialog.getSaveFileName(self, "导出原始数据", f"sec{sec.index:03d}_data.bin", "Bin (*.bin)")
            if p and sec._raw: Path(p).write_bytes(sec._raw)
            return
        if not isinstance(sec, GRPSection): return

        w, h = sec.width, sec.height
        suffix = {"A": "frameA", "L1": "layer1", "L2": "layer2"}.get(self._sel_layer, "layer")
        p, _ = QFileDialog.getSaveFileName(self, f"导出 {self._sel_layer}",
            f"sec{sec.index:03d}_{suffix}.png", "PNG (*.png)")
        if not p: return

        if self._sel_layer == "A":
            rgba = self._get_layer_rgba(sec, "A")
            if rgba is None: return
            export_png_rgba(w, h, bytes(rgba), p)

        elif self._sel_layer == "L1":
            if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
            data = sec.layer1
            if not data: return
            img = Image.frombytes("L", (w, h), data[:w*h])
            img.save(p, "PNG")
            self._export_value_legend(p, data, "Layer 1 — 前景遮挡深度")

        elif self._sel_layer == "L2":
            if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
            data = sec.layer2
            if not data: return
            pal = bytearray(768)
            for v in range(256):
                c = _L2_VAL2RGB.get(v, (0, 0, 0))
                pal[v*3] = c[0]; pal[v*3+1] = c[1]; pal[v*3+2] = c[2]
            img = Image.frombytes("P", (w, h), data[:w*h])
            img.putpalette(bytes(pal))
            img.save(p, "PNG")
            self._export_value_legend(p, data, "Layer 2 — 地形碰撞类型")

        self._status_lbl.setText(f"已导出: {Path(p).name}")

    def _export_value_legend(self, png_path, data, title):
        legend_path = str(Path(png_path).with_suffix('.txt'))
        vals = sorted(Counter(data).items())
        lines = [f"# {title}", f"# 像素值 → 含义", ""]
        for v, cnt in vals:
            if v == 0: lines.append(f"  {v:3d} (共{cnt:6d}px) = 空白/无数据")
            elif title.startswith("Layer 1"): lines.append(f"  {v:3d} (共{cnt:6d}px) = 遮挡深度等级 {v}")
            else: lines.append(f"  {v:3d} (共{cnt:6d}px) = 碰撞类型 #{v}  ({_L2_VAL2RGB.get(v, (0,0,0))})")
        lines.append("")
        lines.append("# 编辑指南:")
        if title.startswith("Layer 1"):
            lines.append("#   - 在图片编辑器中使用灰度值 0~255 的铅笔/画笔工具")
            lines.append("#   - 灰度值 0 = 无遮挡 (透明区域)")
            lines.append("#   - 灰度值 N = 深度等级 N (值越大, 遮挡优先级越高)")
        else:
            lines.append("#   - 在图片编辑器中使用索引色模式 (保留调色板)")
            lines.append("#   - 或用铅笔工具涂特定灰度值 (0=类型0, 1~N=碰撞类型)")
            lines.append("#   - 保存为 PNG 索引色格式以保留碰撞类型ID")
        Path(legend_path).write_text('\n'.join(lines), encoding='utf-8')

    # ── 伪彩色导入/导出 ──────────────────────────────────
    def _export_pseudo(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection) or self._sel_layer not in ("L1", "L2"):
            QMessageBox.information(self, "提示", "请先选中 Layer 1 或 Layer 2!"); return
        if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
        data = sec.layer1 if self._sel_layer == "L1" else sec.layer2
        if not data: return
        p, _ = QFileDialog.getSaveFileName(self, f"导出 {self._sel_layer} 伪彩图",
            f"sec{sec.index:03d}_{self._sel_layer}_Color.png", "PNG (*.png)")
        if not p: return
        try:
            lut = _L1_VAL2RGB if self._sel_layer == "L1" else _L2_VAL2RGB
            rgb_bytes = bytearray(sec.width * sec.height * 3)
            for i, val in enumerate(data[:sec.width * sec.height]):
                c = lut.get(val, (0,0,0))
                rgb_bytes[i*3] = c[0]; rgb_bytes[i*3+1] = c[1]; rgb_bytes[i*3+2] = c[2]
            img = Image.frombytes("RGB", (sec.width, sec.height), bytes(rgb_bytes))
            img.save(p, "PNG")

            if HAS_PIL:
                pal_size = 24
                vals = sorted(set(data[:sec.width * sec.height]))
                cols = min(16, len(vals)); rows = (len(vals) - 1) // 16 + 1
                pal_img = Image.new("RGB", (max(1, cols) * pal_size, max(1, rows) * pal_size), "black")
                draw = ImageDraw.Draw(pal_img)
                for idx2, val in enumerate(vals):
                    x = (idx2 % 16) * pal_size; y = (idx2 // 16) * pal_size
                    draw.rectangle([x, y, x + pal_size - 1, y + pal_size - 1], fill=lut.get(val, (0,0,0)))
                pal_path = str(Path(p).with_name(Path(p).stem + "_Palette.png"))
                pal_img.save(pal_path, "PNG")
            self._status_lbl.setText(f"已导出伪彩图及配套吸色板: {Path(p).name}")
        except Exception as e: QMessageBox.critical(self, "导出失败", str(e))

    def _import_pseudo(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection) or self._sel_layer not in ("L1", "L2"):
            QMessageBox.information(self, "提示", "请先选中 Layer 1 或 Layer 2!"); return
        p, _ = QFileDialog.getOpenFileName(self, f"导入伪彩图以替换 {self._sel_layer}", "", "PNG (*.png);;图片 (*.bmp)")
        if not p: return
        try:
            img = Image.open(p).convert("RGB")
            if img.size != (sec.width, sec.height):
                if QMessageBox.question(self, "尺寸不匹配", "尺寸不一致，强制缩放?") != QMessageBox.Yes: return
                img = img.resize((sec.width, sec.height), Image.NEAREST)
            lut_rev = _L1_RGB2VAL if self._sel_layer == "L1" else _L2_RGB2VAL
            pixels = img.getdata()
            out_bytes = bytes([_nearest_color(p, lut_rev) for p in pixels])
            if self._sel_layer == "L1": sec._layer1 = out_bytes
            else: sec._layer2 = out_bytes; sec.has_layer2 = True
            sec._decoded_b = True; sec._modified_b = True
            self._pil_img = None; self._pixmap_item = None
            self._refresh_view(); self._update_detail()
            self._status_lbl.setText(f"{self._sel_layer} 伪彩图已导入并解析为精确数据!")
        except Exception as e: QMessageBox.critical(self, "导入失败", str(e))

    def _export_color_swatch(self, layer: str):
        p, _ = QFileDialog.getSaveFileName(self, f"导出 {layer} 色板参考",
            f"{layer}_ColorSwatch.png", "PNG (*.png)")
        if not p: return
        try:
            lut = _L1_VAL2RGB if layer == "L1" else _L2_VAL2RGB
            cols, size = 16, 28; rows = 256 // cols
            w, h = cols * size, rows * size
            pal_img = Image.new("RGB", (w, h), "white")
            draw = ImageDraw.Draw(pal_img)
            font = None
            try:
                font = ImageFont.truetype("consola.ttf", 9)
            except: pass
            for v in range(256):
                r, c = v // cols, v % cols
                x, y = c * size, r * size
                color = lut[v]
                draw.rectangle([x, y, x + size - 1, y + size - 1], fill=color, outline="#333")
                brightness = color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114
                txt_color = "black" if brightness > 128 else "white"
                if font: draw.text((x + 2, y + 2), str(v), fill=txt_color, font=font)
                else: draw.text((x + 2, y + 2), str(v), fill=txt_color)
            pal_img.save(p, "PNG")

            txt_path = str(Path(p).with_suffix('.txt'))
            layer_name = "Layer 1 — 前景遮挡深度" if layer == "L1" else "Layer 2 — 地形碰撞类型"
            lines = [f"# {layer_name}  色板参考", "",
                     "# 用法: 在 PS/GIMP 中打开此 PNG, 用吸管取色, 然后在你的图片中涂色。",
                     "# 每个格子的数字 = 游戏中的实际值", "# 格子的颜色 = 该值对应的 RGB 颜色",
                     "# 0 = 空白/类型0 (黑色)", ""]
            for v in range(256):
                c = lut[v]; lines.append(f"  {v:3d}  RGB({c[0]:3d},{c[1]:3d},{c[2]:3d})")
            Path(txt_path).write_text('\n'.join(lines), encoding='utf-8')
            self._status_lbl.setText(f"色板已导出: {Path(p).name}  (+ .txt 值表)")
        except Exception as e: QMessageBox.critical(self, "导出失败", str(e))

    # ── Add / Delete Section ─────────────────────────
    def _add_section_menu(self):
        if not self.grp: return
        menu = QMenu(self)
        menu.addAction("新增图像区段...", self._add_image_section)
        menu.addAction("新增音频区段...", self._add_audio_section)
        menu.addAction("新增数据区段...", self._add_data_section)
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _next_index(self):
        max_idx = -1
        for s in self.grp.sections: max_idx = max(max_idx, s.index)
        for a in self.grp.audio_sections: max_idx = max(max_idx, a.index)
        for d in self.grp.data_sections: max_idx = max(max_idx, d.index)
        return max_idx + 1

    def _add_image_section(self):
        dlg = QDialog(self); dlg.setWindowTitle("新增图像区段")
        dlg.resize(320, 220)
        lay = QGridLayout(dlg)
        lay.addWidget(QLabel("宽度:"), 0, 0)
        w_spin = QSpinBox(); w_spin.setRange(1, 4096); w_spin.setValue(800); lay.addWidget(w_spin, 0, 1)
        lay.addWidget(QLabel("高度:"), 1, 0)
        h_spin = QSpinBox(); h_spin.setRange(1, 4096); h_spin.setValue(600); lay.addWidget(h_spin, 1, 1)
        png_lbl = QLabel(""); lay.addWidget(png_lbl, 2, 0, 1, 2)
        png_path_var = [""]
        def _choose():
            p, _ = QFileDialog.getOpenFileName(dlg, "选择PNG图片", "", "PNG (*.png);;All (*.*)")
            if p:
                png_path_var[0] = p; png_lbl.setText(os.path.basename(p))
                if HAS_PIL:
                    try:
                        img = Image.open(p); w_spin.setValue(img.width); h_spin.setValue(img.height)
                    except: pass
        btn_choose = QPushButton("选择PNG图片..."); btn_choose.clicked.connect(_choose)
        lay.addWidget(btn_choose, 2, 0, 1, 2)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("确定"); btn_ok.setObjectName("PrimaryButton")
        btn_cancel = QPushButton("取消")
        def _ok():
            w, h = w_spin.value(), h_spin.value()
            new_idx = self._next_index()
            ca = w * h * 2 + 4; cb = w * h * 2 + 4
            sec = GRPSection(new_idx, 0, w, h, ca, cb)
            sec._decoded_a = True; sec._modified_a = True
            sec._decoded_b = True; sec._modified_b = True
            pp = png_path_var[0]
            if HAS_PIL and pp and os.path.exists(pp):
                try:
                    img = Image.open(pp).convert("RGBA")
                    if img.size != (w, h): img = img.resize((w, h), Image.LANCZOS)
                    sec._pixels = rgba_to_rgb565(img.tobytes(), w, h)
                except: sec._pixels = b'\x00' * (w * h * 2)
            else: sec._pixels = b'\x00' * (w * h * 2)
            sec._layer1 = b'\x00' * (w * h)
            sec._orig_frame_a = struct.pack("<I", w*h*2) + lzss_compress(sec._pixels)
            sec.comp_a = len(sec._orig_frame_a)
            fb_raw = sec._layer1[:w*h]
            fb_body = rle_bp_compress(fb_raw)
            sec._orig_fb_declared = len(fb_raw)
            fb_data = struct.pack("<I", len(fb_raw)) + fb_body
            sec._orig_frame_b = fb_data; sec.comp_b = len(fb_data)
            self.grp.sections.append(sec)
            self._sync_list(); self._status_lbl.setText(f"已新增图像区段 #{new_idx} ({w}x{h})")
            dlg.accept()
        btn_ok.clicked.connect(_ok); btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_ok); btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row, 3, 0, 1, 2)
        dlg.exec()

    def _add_audio_section(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入 WAV 音频", "", "WAV (*.wav);;All (*.*)")
        if not p: return
        try:
            raw = Path(p).read_bytes()
            new_idx = self._next_index()
            sec = GRPAudioSection(new_idx, 0, len(raw), raw); sec.parse_wav()
            self.grp.audio_sections.append(sec)
            self._sync_list(); self._status_lbl.setText(f"已新增音频区段 #{new_idx} ({len(raw)}B)")
        except Exception as e: QMessageBox.critical(self, "导入失败", str(e))

    def _add_data_section(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入数据文件", "", "All (*.*)")
        if not p: return
        try:
            raw = Path(p).read_bytes()
            new_idx = self._next_index()
            self.grp.data_sections.append(GRPDataSection(new_idx, 0, len(raw), raw))
            self._sync_list(); self._status_lbl.setText(f"已新增数据区段 #{new_idx} ({len(raw)}B)")
        except Exception as e: QMessageBox.critical(self, "导入失败", str(e))

    def _delete_section(self):
        sec = self._get_sec()
        if sec is None: return
        idx = sec.index; label = sec.type_label
        if QMessageBox.question(self, "确认删除",
            f"删除区段 #{idx:03d} — {label}\n此操作不可恢复!") != QMessageBox.Yes: return
        self._stop_audio()
        if isinstance(sec, GRPSection): self.grp.sections.remove(sec)
        elif isinstance(sec, GRPAudioSection): self.grp.audio_sections.remove(sec)
        elif isinstance(sec, GRPDataSection): self.grp.data_sections.remove(sec)
        self._sel_idx = -1; self._pil_img = None; self._pixmap_item = None
        self._sync_list(); self._refresh_view()
        self._status_lbl.setText(f"已删除区段 #{idx:03d}")

    def _show_pseudo_help(self):
        themed_messagebox(self, QMessageBox.Information, "伪彩工作流说明",
            "=== 伪彩色导出/导入工作流 ===\n\n"
            "1. 选中 Layer1(遮挡深度) 或 Layer2(碰撞类型)\n"
            "2. 点击「伪彩导出」→ 得到带 RGB 颜色的 PNG\n"
            "3. 用「L1色板」/「L2色板」导出 256 色参考图\n"
            "4. 在 PS/GIMP 中:\n"
            "   - 打开色板 PNG, 用吸管取目标值的颜色\n"
            "   - 在伪彩图上用铅笔工具(禁用抗锯齿)涂色\n"
            "   - 保存为 PNG\n"
            "5. 点击「伪彩导入」→ 编辑器自动:\n"
            "   - 根据 RGB 颜色查表还原为整数值\n"
            "   - 轻微色差通过最近邻算法自动校正\n\n"
            "=== Layer1 深度值含义 ===\n"
            "  0 = 无遮挡(透明), 值越大遮挡优先度越高\n\n"
            "=== Layer2 碰撞类型含义 ===\n"
            "  0 = 类型0, 1~N = 各类地形障碍")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于 GRP 格式",
            "GRP — 三国群侠传 通用资源包\n\n"
            "格式特征:\n"
            "  - 无文件级魔数, 通过 .IDX 索引定位区段\n"
            "  - 图像: Frame A(RGB565 LZSS) + Frame B(RLE byte-pair)\n"
            "    Layer 1 = 前景遮挡深度值\n"
            "    Layer 2 = 地形碰撞类型值\n"
            "  - 音频: 原始 WAV 数据(SSF/SWS/SMG)\n"
            "  - 数据: 索引/元数据(不可编辑)\n\n"
            "逆向依据: sub_451600 / sub_411308 / sub_410E18 / sub_452B14")


# ═══════════════════════════════════════════════════════════

def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 使用 Fusion 样式，避免 Windows 原生样式覆盖 QSS
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    editor = GRPEditor(fp)
    editor.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    if not HAS_PIL: print("需要 Pillow: pip install Pillow"); sys.exit(1)
    main()
