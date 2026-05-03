#!/usr/bin/env python3
"""
GRP 资源包编辑器 — 浏览/预览/编辑/导出三国群侠传 .grp 格式资源包
=================================================================
格式依据: sub_451600 (GRP加载), sub_411308 (地图加载), sub_410E18 (Frame B RLE)
          sub_452B14 (LZSS), 分析报告 09_GXP_JVG_GRP格式深度对比分析.md

区段类型:
  - 图像区段: Frame A (RGB565 LZSS) + Frame B (RLE byte-pair)
    · Layer 1 = 前景遮挡深度; Layer 2 = 地形碰撞类型 (按值独立着色)
  - 音频区段: WAV 原始数据 (SSF/SWS/SMG.grp)
  - 数据区段: 索引/元数据 (SC.grp 内嵌导航表等)

用法: python grp_editor.py [file.grp]
"""

from __future__ import annotations
import os, sys, struct, zlib, wave, tempfile, subprocess, shutil, io, math, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List, Optional, Tuple
from collections import Counter

HAS_PIL = False
try:    from PIL import Image, ImageTk, ImageDraw; HAS_PIL = True
except ImportError: pass

# ── 常量 ──────────────────────────────────────────────────
RING_SIZE, RING_INIT, RING_INIT_VAL, MIN_MATCH_LZ, MAX_MATCH_LZ = 4096, 4078, 0x20, 3, 18

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
# 伪彩色映射表 (LUT) - 用于在PS中直观编辑 Layer1 / Layer2
# ═══════════════════════════════════════════════════════════
_L1_VAL2RGB = {}; _L1_RGB2VAL = {}
_L2_VAL2RGB = {}; _L2_RGB2VAL = {}

def _distinct_color(val: int, seed: int) -> tuple:
    """为 0~255 生成高对比且视觉离散的 RGB 颜色 (金色角分布)"""
    if val == 0: return (0, 0, 0)
    hue = ((val * 137.508 + seed * 47) % 360)
    h_sector = hue / 60.0
    x = int(255 * (1 - abs(h_sector % 2 - 1)))
    r, g, b = [(255, x, 0), (x, 255, 0), (0, 255, x),
               (0, x, 255), (x, 0, 255), (255, 0, x)][int(h_sector) % 6]
    return (r, g, b)

for _v in range(256):
    # Layer 1 (深度): 离散高对比色 — 每个深度值一个独立颜色, 视觉可区分
    c1 = _distinct_color(_v, seed=31)
    # 确保唯一 (reserved seed 确保不会有碰撞, 但安全起见)
    while c1 in _L1_RGB2VAL: c1 = ((c1[0] + 1) % 256, c1[1], c1[2])
    _L1_VAL2RGB[_v] = c1; _L1_RGB2VAL[c1] = _v

    # Layer 2 (碰撞): 优先复用 _COLLISION_COLORS, 其他用离散色
    if _v == 0:
        c2 = (0, 0, 0)
    elif _v in _COLLISION_COLORS:
        r, g, b, _a = _COLLISION_COLORS[_v]; c2 = (r, g, b)
    else:
        c2 = _distinct_color(_v, seed=73)
    while c2 in _L2_RGB2VAL: c2 = ((c2[0] + 1) % 256, c2[1], c2[2])
    _L2_VAL2RGB[_v] = c2; _L2_RGB2VAL[c2] = _v


def _nearest_color(rgb: tuple, lut_rev: dict) -> int:
    """在 LUT 中查找最近似颜色, 兜底反锯齿/色彩空间偏移"""
    if rgb in lut_rev: return lut_rev[rgb]
    r, g, b = rgb
    best_val, best_dist = 0, 999999
    for color, val in lut_rev.items():
        cr, cg, cb = color
        dist = (r - cr)**2 + (g - cg)**2 + (b - cb)**2
        if dist < best_dist: best_val, best_dist = val, dist
    return best_val


# ═══════════════════════════════════════════════════════════
# LZSS & RLE 引擎
# ═══════════════════════════════════════════════════════════

def lzss_decompress(data: bytes, target_size: int) -> bytes:
    ring = bytearray([RING_INIT_VAL] * RING_SIZE); ring_pos, pos = RING_INIT, 0
    out = bytearray()
    while pos < len(data) and len(out) < target_size:
        flag = data[pos]; pos += 1
        for bit in range(8):
            if pos >= len(data) or len(out) >= target_size: break
            if flag & (1 << bit):
                b = data[pos]; pos += 1; out.append(b)
                ring[ring_pos % RING_SIZE] = b; ring_pos += 1
            else:
                if pos + 2 > len(data): break
                b1, b2 = data[pos], data[pos + 1]; pos += 2
                offset = b1 | ((b2 & 0xF0) << 4); length = (b2 & 0x0F) + 3
                for k in range(length):
                    b = ring[(offset + k) % RING_SIZE]; out.append(b)
                    ring[ring_pos % RING_SIZE] = b; ring_pos += 1
    return bytes(out[:target_size])

def _hash_2b(a: int, b: int) -> int: return ((a << 8) | b) & 0xFFF

def lzss_compress(data: bytes) -> bytes:
    n = len(data)
    if n == 0: return b""
    hh, hn = [-1] * 4096, [-1] * n
    for i in range(n - 1, -1, -1):
        if i + 1 < n: h = _hash_2b(data[i], data[i + 1]); hn[i] = hh[h]; hh[h] = i
    buf, entries = bytearray(), []
    def flush():
        if not entries: return
        flag = 0
        for i, (is_lit, _) in enumerate(entries):
            if is_lit: flag |= (1 << i)
        buf.append(flag)
        for _, d in entries: buf.extend(d)
        entries.clear()
    pos = 0
    while pos < n:
        bl, bo = 0, 0
        if n - pos >= 2:
            chain = hh[_hash_2b(data[pos], data[pos + 1])]; steps = 0
            while chain >= 0 and steps < 64:
                if pos - chain > RING_SIZE: break
                if chain < pos:
                    ml = 0
                    while ml < min(n - pos, MAX_MATCH_LZ) and data[chain + ml] == data[pos + ml]: ml += 1
                    if ml > bl: bl, bo = ml, pos - chain
                    if ml == MAX_MATCH_LZ: break
                chain = hn[chain]; steps += 1
        if bl >= MIN_MATCH_LZ:
            rp = (RING_INIT + pos) % RING_SIZE; ao = (rp - bo) % RING_SIZE
            entries.append((False, bytes([ao & 0xFF, ((ao >> 4) & 0xF0) | ((bl - 3) & 0x0F)]))); pos += bl
        else: entries.append((True, bytes([data[pos]]))); pos += 1
        if len(entries) >= 8: flush()
    flush(); return bytes(buf)

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
# RGB565 转换
# ═══════════════════════════════════════════════════════════

_RGB565_LUT = bytearray(65536 * 3)
for _v in range(65536):
    r5, g6, b5 = (_v >> 11) & 0x1F, (_v >> 5) & 0x3F, _v & 0x1F
    _RGB565_LUT[_v * 3] = (r5 << 3) | (r5 >> 2)
    _RGB565_LUT[_v * 3 + 1] = (g6 << 2) | (g6 >> 4)
    _RGB565_LUT[_v * 3 + 2] = (b5 << 3) | (b5 >> 2)

def rgb565_to_rgba(raw: bytes, w: int, h: int) -> bytearray:
    total = w * h; rgba = bytearray(total * 4)
    for i in range(min(total, len(raw) // 2)):
        lo, hi = raw[i * 2], raw[i * 2 + 1]; off3 = (lo | (hi << 8)) * 3; off4 = i * 4
        rgba[off4:off4 + 3] = _RGB565_LUT[off3:off3 + 3]; rgba[off4 + 3] = 255
    return rgba

def rgba_to_rgb565(rgba_bytes: bytes, w: int, h: int) -> bytes:
    raw = bytearray(w * h * 2)
    for i in range(w * h):
        off4 = i * 4; r5 = (rgba_bytes[off4] >> 3) & 0x1F
        g6 = (rgba_bytes[off4+1] >> 2) & 0x3F; b5 = (rgba_bytes[off4+2] >> 3) & 0x1F
        val = (r5 << 11) | (g6 << 5) | b5; raw[i*2] = val & 0xFF; raw[i*2+1] = (val >> 8) & 0xFF
    return bytes(raw)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class GRPSection:
    """图像区段 — 保留原始压缩数据用于未修改区段的原样保存"""
    def __init__(self, index: int, offset: int, width: int, height: int,
                 comp_a: int, comp_b: int):
        self.index = index; self.offset = offset
        self.width = width; self.height = height; self.comp_a = comp_a; self.comp_b = comp_b
        self.uncomp_a = width * height * 2
        self._pixels: Optional[bytes] = None; self._decoded_a = False
        self._layer1: Optional[bytes] = None; self._layer2: Optional[bytes] = None
        self._decoded_b = False; self.has_layer2 = False
        # 原始压缩数据 (用于未修改区段的原样保存)
        self._orig_frame_a: Optional[bytes] = None
        self._orig_frame_b: Optional[bytes] = None
        self._orig_fb_declared: int = 0
        self._modified_a = False; self._modified_b = False

    @property
    def pixels(self) -> Optional[bytes]: return self._pixels
    @property
    def layer1(self) -> Optional[bytes]: return self._layer1
    @property
    def layer2(self) -> Optional[bytes]: return self._layer2
    @property
    def is_decoded_a(self) -> bool: return self._decoded_a
    @property
    def is_decoded_b(self) -> bool: return self._decoded_b
    @property
    def type_label(self) -> str: return f"IMG {self.width}×{self.height}"

class GRPAudioSection:
    """音频区段"""
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index; self.offset = offset; self.size = size; self._raw = raw_data
        self._wav_info = ""; self._duration = 0.0; self._samples: Optional[list] = None

    @property
    def raw(self) -> Optional[bytes]: return self._raw
    @raw.setter
    def raw(self, v): self._raw = v

    @property
    def type_label(self) -> str:
        if self._wav_info:
            return f"AUD {self._wav_info} {self._duration:.1f}s"
        return f"AUD {self.size}B"

    @property
    def has_samples(self) -> bool: return self._samples is not None

    def parse_wav(self):
        if not self._raw or len(self._raw) < 44: return
        try:
            f = io.BytesIO(self._raw)
            with wave.open(f, 'rb') as wf:
                ch, sr, sw, nf = wf.getnchannels(), wf.getframerate(), wf.getsampwidth(), wf.getnframes()
                self._wav_info = f"{ch}ch {sr}Hz {sw*8}bit"
                self._duration = nf / sr if sr > 0 else 0
                # 读取全部采样用于 Premiere 风格波形
                if nf > 0 and sw > 0:
                    frames = wf.readframes(nf)
                    if sw == 1: fmt, n_per = f"<{len(frames)}b", len(frames)
                    elif sw == 2: fmt, n_per = f"<{len(frames)//2}h", len(frames)//2
                    else: fmt, n_per = f"<{len(frames)//sw}i", len(frames)//sw
                    raw = struct.unpack(fmt, frames[:struct.calcsize(fmt)])
                    # 如果立体声, 合并为单声道取平均幅度
                    if ch == 2:
                        raw = [(raw[i] + raw[i+1]) // 2 for i in range(0, len(raw)-1, 2)]
                    self._samples = list(raw)
        except Exception: pass

class GRPDataSection:
    """数据区段 (索引/元数据 — 非图像非音频)"""
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index; self.offset = offset; self.size = size; self._raw = raw_data

    @property
    def raw(self) -> Optional[bytes]: return self._raw
    @property
    def type_label(self) -> str:
        return f"DATA {self.size}B"


class GRPFile:
    def __init__(self):
        self.sections: List[GRPSection] = []
        self.audio_sections: List[GRPAudioSection] = []
        self.data_sections: List[GRPDataSection] = []
        self.idx_offsets: List[int] = []
        self.filepath: Optional[str] = None; self.idx_path: Optional[str] = None
        self._raw_data: bytes = b""

    @property
    def total_sections(self) -> int:
        return len(self.sections) + len(self.audio_sections) + len(self.data_sections)

    def all_sorted(self) -> list:
        """按 index 排序的所有 section"""
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

    # 加载 IDX
    if idx_path is None:
        for ext in ['.IDX', '.idx']:
            c = str(Path(filepath).with_suffix(ext))
            if os.path.exists(c): idx_path = c; break
    if idx_path and os.path.exists(idx_path):
        idata = Path(idx_path).read_bytes()
        if len(idata) >= 8 and len(idata) % 4 == 0:
            offs = [struct.unpack_from("<I", idata, i)[0] for i in range(0, len(idata), 4)]
            if offs and offs[-1] == fsize: grp.idx_offsets = offs; grp.idx_path = idx_path

    # 边界
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

    # 分类每个 section
    for idx, (so, eo) in enumerate(boundaries):
        sz = eo - so
        # 尝试按图像头解析
        if sz >= 12:
            w, h, ca, cb = struct.unpack_from("<HHII", data, so)
            # 有效图像: 合理尺寸 + header size 匹配
            if (1 <= w <= 4096 and 1 <= h <= 4096 and
                12 + ca + cb == sz and ca > 0 and cb > 0):
                sec = GRPSection(idx, so, w, h, ca, cb)
                # 保存原始压缩数据 (修改时才重新编码)
                fa_off = so + 12; fb_off = fa_off + ca
                sec._orig_frame_a = data[fa_off:fa_off + ca]
                sec._orig_frame_b = data[fb_off:fb_off + cb]
                if cb >= 4:
                    sec._orig_fb_declared = struct.unpack_from("<I", data, fb_off)[0]
                grp.sections.append(sec)
                continue
        # 尝试音频: 以 RIFF 头开头
        if sz >= 12 and data[so:so+4] == b"RIFF":
            asec = GRPAudioSection(idx, so, sz, data[so:eo])
            asec.parse_wav(); grp.audio_sections.append(asec)
            continue
        # 其他: 数据区段
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
    """保存 GRP — 未修改的区段原样写入, 已修改的重新编码后写入"""
    buf = bytearray(); offsets = []
    for kind, idx, obj in grp.all_sorted():
        offsets.append(len(buf))  # 当前 section 起始偏移
        if kind == 'IMG':
            sec = obj
            # ── 确定 Frame A 数据 ──
            if sec._modified_a and sec._pixels:
                fa_body = lzss_compress(sec._pixels)
                comp_a = len(fa_body) + 4  # +4 for uncompressed size header
                fa_data = struct.pack("<I", sec.uncomp_a) + fa_body
            else:
                comp_a = sec.comp_a
                fa_data = sec._orig_frame_a if sec._orig_frame_a else (
                    struct.pack("<I", sec.uncomp_a) + b"\x00" * (sec.comp_a - 4))

            # ── 确定 Frame B 数据 ──
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

            # ── 写入 header + Frame A + Frame B ──
            buf += struct.pack("<HHII", sec.width, sec.height, comp_a, comp_b)
            buf += fa_data
            buf += fb_data

        elif kind == 'AUD':
            if obj._raw: buf += obj._raw
        else:  # DATA
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

def export_png_rgba(w: int, h: int, rgba: bytes, path: str):
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    stride = w * 4; raw = bytearray(h * (stride + 1))
    for row in range(h):
        out = row * (stride + 1); raw[out] = 0
        raw[out + 1:out + 1 + stride] = rgba[row * stride:(row + 1) * stride]
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)); png += _png_chunk(b"IEND", b"")
    Path(path).write_bytes(png)


# ═══════════════════════════════════════════════════════════
# GUI 编辑器
# ═══════════════════════════════════════════════════════════

class GRPEditor:
    def __init__(self, root: tk.Tk, filepath: Optional[str] = None):
        self.root = root; self.root.title("GRP 资源包编辑器"); self.root.geometry("1360x900")
        self.grp: Optional[GRPFile] = None
        self._sel_idx = -1; self._sel_layer = "A"
        self._zoom = tk.DoubleVar(value=1.0)
        self._pan_x, self._pan_y = 0, 0; self._pan_start = None
        self._tk_img = None; self._pil_img = None
        self._audio_playing = False; self._audio_proc = None; self._audio_tmp = None
        self._wave_anim_job = None; self._wave_start_time: float = 0

        self._setup_menu(); self._setup_ui()
        if filepath and os.path.exists(filepath): self._open(filepath)
        else: self._new_empty()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._bind_events)

    # ── Menu ──────────────────────────────────────────
    def _setup_menu(self):
        mb = tk.Menu(self.root)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="打开 GRP... Ctrl+O", command=self._open_dlg)
        fm.add_command(label="保存 Ctrl+S", command=self._save)
        fm.add_command(label="另存为... Ctrl+Shift+S", command=self._save_as)
        fm.add_separator(); fm.add_command(label="退出", command=self._on_close)
        mb.add_cascade(label="文件", menu=fm)
        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="原始大小", command=lambda: self._set_zoom(1.0))
        vm.add_command(label="适合窗口", command=self._fit_to_window)
        vm.add_command(label="放大", command=lambda: self._zoom_step(0.25))
        vm.add_command(label="缩小", command=lambda: self._zoom_step(-0.25))
        mb.add_cascade(label="视图", menu=vm)
        mb.add_cascade(label="帮助", menu=tk.Menu(mb, tearoff=0))
        self.root.config(menu=mb)
        for k, cb in [("<Control-o>", self._open_dlg), ("<Control-s>", self._save),
                       ("<Control-Shift-s>", self._save_as)]:
            self.root.bind(k, lambda e, f=cb: f())

    # ── UI Layout ─────────────────────────────────────
    def _setup_ui(self):
        # Toolbar
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Button(tb, text="打开 GRP", command=self._open_dlg).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="保存", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        self._btn_a = ttk.Button(tb, text="○ Frame A", command=lambda: self._switch_layer("A"))
        self._btn_a.pack(side=tk.LEFT, padx=1)
        self._btn_l1 = ttk.Button(tb, text="○ Layer 1", command=lambda: self._switch_layer("L1"))
        self._btn_l1.pack(side=tk.LEFT, padx=1)
        self._btn_l2 = ttk.Button(tb, text="○ Layer 2", command=lambda: self._switch_layer("L2"))
        self._btn_l2.pack(side=tk.LEFT, padx=1)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        ttk.Button(tb, text="替换当前层", command=self._replace_layer).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="导出当前层", command=self._export_layer).pack(side=tk.LEFT, padx=2)
        self._btn_play = ttk.Button(tb, text="▶ 播放", command=self._toggle_audio)
        self._btn_play.pack(side=tk.LEFT, padx=2)
        self._btn_replace_aud = ttk.Button(tb, text="替换音频", command=self._replace_audio)
        self._btn_replace_aud.pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        
        # [新增] 伪彩色工作流按钮
        ttk.Button(tb, text="伪彩导出", command=self._export_pseudo).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="伪彩导入", command=self._import_pseudo).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        ttk.Button(tb, text="−", width=2, command=lambda: self._zoom_step(-0.25)).pack(side=tk.LEFT, padx=1)
        self._zlbl = ttk.Label(tb, text="100%", width=5); self._zlbl.pack(side=tk.LEFT)
        ttk.Button(tb, text="+", width=2, command=lambda: self._zoom_step(0.25)).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="⊡", width=2, command=self._fit_to_window).pack(side=tk.LEFT, padx=2)
        self._pixel_lbl = ttk.Label(tb, text="", foreground="#666"); self._pixel_lbl.pack(side=tk.RIGHT, padx=8)
        self._info_lbl = ttk.Label(tb, text=""); self._info_lbl.pack(side=tk.RIGHT, padx=8)

        # Main layout
        pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL); pw.pack(fill=tk.BOTH, expand=True)
        self._pw = pw

        # ── LEFT: light theme ──────────────────────────
        lf = ttk.Frame(pw, width=280); pw.add(lf, weight=0)
        lh = ttk.Frame(lf); lh.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(lh, text="区段列表", font=("", 10, "bold")).pack(side=tk.LEFT)
        self._sec_count_lbl = ttk.Label(lh, text=""); self._sec_count_lbl.pack(side=tk.RIGHT)

        lsf = ttk.Frame(lf); lsf.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._sec_list = tk.Listbox(lsf, exportselection=False, font=("Consolas", 9),
                                     activestyle='none', highlightthickness=1)
        sl_sb = tk.Scrollbar(lsf, orient=tk.VERTICAL, command=self._sec_list.yview,
                              width=14)  # 加宽确保可抓取
        self._sec_list.configure(yscrollcommand=sl_sb.set)
        self._sec_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._sec_list.bind("<<ListboxSelect>>", self._on_section_select)
        self._sec_list.bind("<MouseWheel>", lambda e: self._sec_list.yview_scroll(-e.delta//120, "units"))

        self._sec_detail = tk.Text(lf, height=5, state=tk.DISABLED, font=("Consolas", 8),
                                    wrap=tk.NONE, padx=4, pady=2)
        self._sec_detail.pack(fill=tk.X, padx=4, pady=(2, 4))

        # ── RIGHT: Canvas ──────────────────────────────
        rf = ttk.Frame(pw); pw.add(rf, weight=1)
        cf = ttk.Frame(rf); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 0))
        self._canvas = tk.Canvas(cf, bg="#eee", highlightthickness=0, cursor="crosshair")
        vsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self._canvas.yview)
        hsb = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew"); vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew"); cf.grid_rowconfigure(0, weight=1)
        cf.grid_columnconfigure(0, weight=1)

        sf = ttk.Frame(rf); sf.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._status_lbl = ttk.Label(sf, text="就绪 — 打开 GRP 文件", foreground="#888")
        self._status_lbl.pack(side=tk.LEFT)
        ttk.Label(sf, text="Ctrl+滚轮=缩放 | 拖拽=平移", foreground="#aaa").pack(side=tk.RIGHT)
        self._update_buttons()

    def _bind_events(self):
        self._canvas.bind("<Configure>", lambda e: self._refresh_view())
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        for ev, cb in [("<ButtonPress-2>", self._pan_s), ("<B2-Motion>", self._pan_m),
                        ("<ButtonRelease-2>", self._pan_e), ("<ButtonPress-1>", self._pan_s),
                        ("<B1-Motion>", self._pan_m), ("<ButtonRelease-1>", self._pan_e)]:
            self._canvas.bind(ev, cb)
        self._canvas.bind("<Motion>", self._on_mouse_move)

    # ── Button state ──────────────────────────────────
    def _update_buttons(self):
        is_img = self._is_img(); is_aud = self._is_aud()
        s = tk.NORMAL; d = tk.DISABLED
        for b in [self._btn_a, self._btn_l1, self._btn_l2]: b.configure(state=s if is_img else d)
        self._btn_play.configure(state=s if is_aud else d)
        self._btn_replace_aud.configure(state=s if is_aud else d)
        for b, t in [(self._btn_a, "A"), (self._btn_l1, "L1"), (self._btn_l2, "L2")]:
            b.configure(text=f"{'●' if is_img and self._sel_layer == t else '○'} {t.replace('A','Frame A')}")

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

    # ── Section list ──────────────────────────────────
    def _sync_list(self):
        self._sec_list.delete(0, tk.END)
        if not self.grp: return
        for kind, idx, obj in self.grp.all_sorted():
            self._sec_list.insert(tk.END, f"[{kind}] #{idx:03d}  {obj.type_label}")
        self._sec_count_lbl.config(text=f"{self.grp.total_sections} sections")
        if self.grp.total_sections > 0:
            self._sec_list.selection_set(0)
            self._sel_idx = self.grp.all_sorted()[0][1]
            self._refresh_view(); self._update_detail(); self._update_buttons()

    def _on_section_select(self, ev=None):
        sel = self._sec_list.curselection()
        if not self.grp or not sel: return
        items = self.grp.all_sorted()
        if sel[0] < len(items):
            self._sel_idx = items[sel[0]][1]
            sec = self._get_sec()
            if isinstance(sec, GRPSection): self._sel_layer = "A"
            self._stop_audio(); self._pil_img = None; self._tk_img = None
            self._pan_x = self._pan_y = 0
            if isinstance(sec, GRPSection): self._fit_to_window()
            self._refresh_view(); self._update_detail(); self._update_buttons()

    def _update_detail(self):
        self._sec_detail.config(state=tk.NORMAL); self._sec_detail.delete(1.0, tk.END)
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
                    items = []
                    for v,c in vals2[:8]:
                        clr = _collision_color(v)
                        items.append(f'#{v}({c}px)')
                    info += '  ' + ', '.join(items)
                    if len(vals2) > 8: info += f' ...共{len(vals2)}种'
                    info += '\n'
            info += f"A:{'OK' if sec.is_decoded_a else '待解码'} B:{'OK' if sec.is_decoded_b else '待解码'}\n"
            info += "\n导出: Layer1/Layer2 为精确值灰度图, 带 .txt 值域说明"
        elif isinstance(sec, GRPAudioSection):
            info = f"区段 #{sec.index:03d} — 音频\n大小: {sec.size}B"
            if sec._wav_info: info += f"\n格式: {sec._wav_info}\n时长: {sec._duration:.2f}s"
        elif isinstance(sec, GRPDataSection):
            info = f"区段 #{sec.index:03d} — 数据\n大小: {sec.size}B\n(索引/元数据, 不可编辑)"
        else: info = "(无选中)"
        self._sec_detail.insert(tk.END, info); self._sec_detail.config(state=tk.DISABLED)

    # ── File ops ──────────────────────────────────────
    def _new_empty(self):
        self.grp = GRPFile(); self._sync_list(); self._sel_idx = -1; self._refresh_view()
        self.root.title("GRP 编辑器 — [新建]")

    def _open_dlg(self):
        p = filedialog.askopenfilename(title="打开 GRP", filetypes=[("GRP", "*.grp *.GRP"), ("All", "*.*")])
        if p: self._open(p)

    def _open(self, p: str):
        try:
            self._status_lbl.config(text=f"加载中: {Path(p).name}..."); self.root.update()
            self._stop_audio(); self.grp = load_grp(p)
            self._sel_idx = -1; self._sel_layer = "A"
            self._sync_list()
            self._refresh_view()
            ni, na, nd = len(self.grp.sections), len(self.grp.audio_sections), len(self.grp.data_sections)
            extra = f"  ({ni}IMG + {na}AUD" + (f" + {nd}DATA" if nd else "") + ")"
            id_info = f"  |  IDX: {Path(self.grp.idx_path).name}" if self.grp.idx_path else ""
            self._status_lbl.config(text=f"已加载: {Path(p).name}  |  {self.grp.total_sections} sections{extra}{id_info}")
            self.root.title(f"GRP 编辑器 — {os.path.basename(p)}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e)); import traceback; traceback.print_exc()

    def _save(self):
        if not self.grp: return
        if self.grp.filepath: self._do_save(self.grp.filepath, self.grp.idx_path)
        else: self._save_as()

    def _save_as(self):
        p = filedialog.asksaveasfilename(title="保存 GRP", defaultextension=".grp", filetypes=[("GRP", "*.grp")])
        if p: self._do_save(p, str(Path(p).with_suffix('.idx')))

    def _do_save(self, grp_path: str, idx_path: Optional[str] = None):
        try:
            self._status_lbl.config(text="压缩中..."); self.root.update()
            save_grp(self.grp, grp_path, idx_path)
            self.grp.filepath = grp_path; self.grp.idx_path = idx_path
            self._status_lbl.config(text=f"已保存: {Path(grp_path).name} ({os.path.getsize(grp_path)/1024:.1f}KB)")
        except Exception as e: messagebox.showerror("保存失败", str(e))

    def _on_close(self): self._stop_audio(); self.root.destroy()

    # ── Layer switching ───────────────────────────────
    def _switch_layer(self, layer: str):
        if not self._is_img(): return
        self._sel_layer = layer; self._pil_img = None; self._tk_img = None
        self._update_buttons(); self._refresh_view(); self._update_detail()

    # ── Layer RGBA ────────────────────────────────────
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
                vals = [b for b in data]; vmin = min(vals) if vals else 0
                vmax = max(vals) if vals else 255; rng = max(vmax - vmin, 1)
                for i in range(min(len(data), total)):
                    v = int((data[i] - vmin) * 255 / rng)
                    rgba[i*4:i*4+3] = bytes([v]*3); rgba[i*4+3] = 0 if data[i] == 0 else 200
            else:
                for i in range(min(len(data), total)):
                    rgba[i*4:i*4+4] = bytes(_collision_color(data[i]))
            return rgba
        return None

    # ── Canvas refresh ────────────────────────────────
    _MAX_DISPLAY_DIM = 1200  # 预览最大尺寸 (像素), 超过则自动缩放

    def _refresh_view(self):
        self._canvas.delete("all")
        sec = self._get_sec()
        if not sec: return

        if isinstance(sec, GRPDataSection):
            cw = self._canvas.winfo_width() or 400; ch = self._canvas.winfo_height() or 300
            self._canvas.create_text(cw//2, ch//2, text="数据区段 (不可预览)", fill="#666", font=("", 14))
            return

        if isinstance(sec, GRPAudioSection):
            self._draw_audio_view(sec); return

        if isinstance(sec, GRPSection):
            w, h = sec.width, sec.height
            # 自动解码
            rgba = self._get_layer_rgba(sec, self._sel_layer)
            if rgba is None:
                cw = self._canvas.winfo_width() or 400; ch = self._canvas.winfo_height() or 300
                self._canvas.create_text(cw//2, ch//2, text="Layer 2 不可用 (单层遮罩)", fill="#666", font=("", 12))
                return

            # 构建 PIL 图像 (首次) 或复用缓存
            if self._pil_img is None and HAS_PIL:
                self._pil_img = Image.frombytes("RGBA", (w, h), bytes(rgba))
            if self._pil_img is None: return

            # 显示缩放: 大图自动缩小到 _MAX_DISPLAY_DIM 以内
            z = self._zoom.get()
            max_dim = max(w, h)
            auto_scale = min(1.0, self._MAX_DISPLAY_DIM / max_dim) if max_dim > self._MAX_DISPLAY_DIM else 1.0
            disp_scale = z * auto_scale
            sw, sh = max(1, int(w * disp_scale)), max(1, int(h * disp_scale))
            display = self._pil_img if disp_scale == 1.0 else self._pil_img.resize((sw, sh), Image.NEAREST)
            self._tk_img = ImageTk.PhotoImage(display)

            cw = self._canvas.winfo_width() or 400; ch = self._canvas.winfo_height() or 300
            x = max(0, (cw - sw) // 2) + self._pan_x; y = max(0, (ch - sh) // 2) + self._pan_y
            self._canvas.create_image(x, y, anchor=tk.NW, image=self._tk_img, tags=("img",))
            self._canvas.configure(scrollregion=(0, 0, max(cw, sw + 40), max(ch, sh + 40)))
            self._zlbl.config(text=f"{int(z*100)}%")
            names = {"A": "Frame A", "L1": "Layer 1 (遮挡)", "L2": "Layer 2 (碰撞)"}
            self._info_lbl.config(text=f"#{sec.index:03d} {w}x{h} | {names.get(self._sel_layer,'')}")

    def _draw_audio_view(self, sec: GRPAudioSection):
        """Premiere 风格波形: 全宽填充波形 + 时间轴 + 播放头"""
        # 清除之前的波形元素 (避免 _stop_audio 重绘时叠加)
        self._canvas.delete("wave", "prog", "prog_overlay", "wave_bg")
        cw = self._canvas.winfo_width() or 400; ch = self._canvas.winfo_height() or 300
        margin_l, margin_r = 60, 40
        wave_w = cw - margin_l - margin_r

        # ── 顶部信息条 ──
        info = f"音频 #{sec.index:03d}  |  {sec.size}B"
        if sec._wav_info: info += f"  |  {sec._wav_info}"
        if sec._duration > 0: info += f"  |  {sec._duration:.2f}s"
        self._canvas.create_text(cw//2, 16, text=info, fill="#444", font=("", 9))

        # ── 波形区域 ──
        wave_top, wave_h = 40, ch - 100
        wave_mid = wave_top + wave_h // 2
        wx, wy = margin_l, wave_top

        # 背景
        self._canvas.create_rectangle(wx, wy, wx + wave_w, wy + wave_h,
                                       fill="#1a1a1a", outline="#444", tags=("wave_bg",))

        if sec.has_samples and sec._samples:
            samples = sec._samples; n = len(samples)
            max_val = max(abs(min(samples)), abs(max(samples)), 1)
            half_h = wave_h // 2 - 6

            # 降采样以匹配画布宽度 (每个像素列取 min/max)
            px_per_col = max(1, n / wave_w)
            cols_data = []  # [(col_min, col_max), ...]
            for col in range(wave_w):
                si = int(col * px_per_col)
                ei = min(n, int((col + 1) * px_per_col))
                if si >= n: break
                seg = samples[si:ei]
                if seg:
                    cols_data.append((min(seg), max(seg)))
                else:
                    cols_data.append((0, 0))

            # 绘制填充波形 (每个像素列从 min 到 max 画竖线)
            played_cols = 0
            if self._audio_playing and sec._duration > 0:
                elapsed = __import__('time').time() - self._wave_start_time
                played_cols = int(min(elapsed / sec._duration, 1.0) * len(cols_data))

            for ci, (vmin, vmax) in enumerate(cols_data):
                x = wx + ci
                y_top = wave_mid - int((vmax / max_val) * half_h)
                y_bot = wave_mid - int((vmin / max_val) * half_h)
                if y_top == y_bot: y_top -= 1  # 静音显示细线
                color = "#4a9eff" if ci <= played_cols else "#607890"
                self._canvas.create_line(x, y_top, x, y_bot, fill=color, tags=("wave",))

            # 中线
            self._canvas.create_line(wx, wave_mid, wx + wave_w, wave_mid,
                                      fill="#555", dash=(2, 6), tags=("wave",))

            # ── 时间轴 ──
            timeline_y = wy + wave_h + 8
            self._canvas.create_line(wx, timeline_y, wx + wave_w, timeline_y, fill="#666")
            for tick_sec in range(0, int(sec._duration) + 2):
                tx = wx + int((tick_sec / sec._duration) * wave_w) if sec._duration > 0 else wx
                if tx <= wx + wave_w:
                    self._canvas.create_line(tx, timeline_y, tx, timeline_y + 6, fill="#888")
                    self._canvas.create_text(tx, timeline_y + 16, text=f"{tick_sec}s",
                                              fill="#888", font=("", 7))
        else:
            self._canvas.create_text(wx + wave_w//2, wave_mid, text="无波形数据",
                                      fill="#555", font=("", 10))

        # ── 播放头 ──
        if self._audio_playing and sec._duration > 0 and sec.has_samples:
            elapsed = __import__('time').time() - self._wave_start_time
            progress = min(elapsed / sec._duration, 1.0) if sec._duration > 0 else 0
            px = wx + int(progress * wave_w)
            px = min(px, wx + wave_w)
            # 播放头红线
            self._canvas.create_line(px, wy, px, wy + wave_h, fill="#ff3040", width=2, tags=("prog",))
            # 播放头顶部三角
            self._canvas.create_polygon(px-5, wy, px+5, wy, px, wy+8,
                                         fill="#ff3040", outline="#ff3040", tags=("prog",))
            self._wave_anim_job = self.root.after(40, lambda: self._draw_audio_progress(sec))

    def _draw_audio_progress(self, sec: GRPAudioSection):
        if not self._audio_playing: return
        self._draw_audio_view(sec)

    # ── Zoom & Pan ────────────────────────────────────
    def _set_zoom(self, z: float):
        self._zoom.set(max(0.25, min(5.0, z))); self._tk_img = None; self._refresh_view()
    def _zoom_step(self, delta: float): self._set_zoom(self._zoom.get() + delta)
    def _fit_to_window(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection): return
        cw = (self._canvas.winfo_width() or 800) - 40; ch = (self._canvas.winfo_height() or 600) - 40
        z = min(2.0, cw / max(sec.width, 1), ch / max(sec.height, 1))
        self._set_zoom(max(0.25, z)); self._pan_x = self._pan_y = 0

    def _pan_s(self, ev): self._pan_start = (ev.x, ev.y)
    def _pan_m(self, ev):
        if self._pan_start is None: return
        dx = ev.x - self._pan_start[0]; dy = ev.y - self._pan_start[1]
        self._pan_x += dx; self._pan_y += dy; self._pan_start = (ev.x, ev.y); self._refresh_view()
    def _pan_e(self, ev): self._pan_start = None
    def _on_mousewheel(self, ev):
        if ev.state & 0x4: self._zoom_step(0.25 if ev.delta > 0 else -0.25)
        elif ev.state & 0x1: self._canvas.xview_scroll(-ev.delta // 120, "units")
        else: self._canvas.yview_scroll(-ev.delta // 120, "units")

    def _on_mouse_move(self, ev):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection): self._pixel_lbl.config(text=""); return
        w, h = sec.width, sec.height; z = self._zoom.get()
        sw, sh = int(w * z), int(h * z)
        cw = self._canvas.winfo_width() or 800; ch = self._canvas.winfo_height() or 600
        ox = max(0, (cw - sw) // 2) + self._pan_x; oy = max(0, (ch - sh) // 2) + self._pan_y
        px = int((ev.x - ox) / z); py = int((ev.y - oy) / z)
        if 0 <= px < w and 0 <= py < h:
            idx = py * w + px
            if self._sel_layer == "A" and sec.is_decoded_a and sec.pixels and idx * 2 + 1 < len(sec.pixels):
                lo, hi = sec.pixels[idx*2], sec.pixels[idx*2+1]; v = lo | (hi << 8)
                r5, g6, b5 = (v>>11)&0x1F, (v>>5)&0x3F, v&0x1F
                self._pixel_lbl.config(text=f"({px},{py}) #565=0x{v:04X} RGB=({r5<<3},{g6<<2},{b5<<3})")
            elif self._sel_layer == "L1" and sec.layer1 and idx < len(sec.layer1):
                self._pixel_lbl.config(text=f"({px},{py}) 深度={sec.layer1[idx]}")
            elif self._sel_layer == "L2" and sec.layer2 and idx < len(sec.layer2):
                self._pixel_lbl.config(text=f"({px},{py}) 碰撞类型={sec.layer2[idx]}")
            else: self._pixel_lbl.config(text=f"({px},{py})")
        else: self._pixel_lbl.config(text="")

    # ── Replace / Export ──────────────────────────────
    def _replace_layer(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPSection): return
        if self._sel_layer == "A": self._replace_frame_a(sec)
        elif self._sel_layer in ("L1", "L2"): self._replace_layer_byte(sec, self._sel_layer)

    def _replace_frame_a(self, sec: GRPSection):
        p = filedialog.askopenfilename(title="替换主图", filetypes=[("图片", "*.png *.bmp *.jpg")])
        if not p: return
        try:
            img = Image.open(p).convert("RGBA")
            if img.size != (sec.width, sec.height):
                if not messagebox.askyesno("尺寸不匹配",
                    f"导入 {img.size[0]}×{img.size[1]} ≠ 原 {sec.width}×{sec.height}。缩放?"): return
                img = img.resize((sec.width, sec.height), Image.LANCZOS)
            sec._pixels = rgba_to_rgb565(img.tobytes(), sec.width, sec.height)
            sec._decoded_a = True; sec._modified_a = True
            self._pil_img = None; self._tk_img = None
            self._refresh_view(); self._status_lbl.config(text=f"Frame A 已替换 → {Path(p).name}")
        except Exception as e: messagebox.showerror("替换失败", str(e))

    def _replace_layer_byte(self, sec: GRPSection, layer: str):
        """导入 Layer: 读取原始灰度值作为精确的游戏数据字节。

        Layer1: 每个像素的灰度值 = 遮挡深度 (0~255)
        Layer2: 每个像素的灰度值 = 碰撞类型ID (0=可行走, 1~N=各类型)

        支持 PNG (灰度/索引/RGB) 和 BMP 格式。
        导入时自动转为灰度读取精确字节, 不会做拉伸或颜色映射。
        """
        p = filedialog.askopenfilename(
            title=f"替换 {layer} (灰度图, 像素值=游戏数据值)",
            filetypes=[("图片", "*.png *.bmp *.jpg")])
        if not p: return
        try:
            img = Image.open(p)
            # 如果是索引模式 (Layer2 导出后直接编辑), 转为灰度保留索引值
            if img.mode == "P":
                # 索引 PNG: 每个像素的 palette index 就是碰撞类型
                data = img.tobytes()
            else:
                img = img.convert("L")
                data = img.tobytes()
            if img.size != (sec.width, sec.height):
                if not messagebox.askyesno("尺寸不匹配",
                    f"导入 {img.size[0]}×{img.size[1]} ≠ 原 {sec.width}×{sec.height}。缩放?"): return
                img = Image.frombytes("L", img.size, data) if img.mode != "P" else img
                img = img.resize((sec.width, sec.height), Image.NEAREST)
                if img.mode == "P": data = img.tobytes()
                else: data = img.tobytes()
            if layer == "L1": sec._layer1 = data
            else: sec._layer2 = data; sec.has_layer2 = True
            sec._decoded_b = True; sec._modified_b = True
            self._pil_img = None; self._tk_img = None
            self._refresh_view(); self._update_detail()
            self._status_lbl.config(text=f"{layer} 已替换 → {Path(p).name} (精确值映射)")
        except Exception as e: messagebox.showerror("替换失败", str(e))

    def _export_layer(self):
        """导出当前层。

        Frame A: 真彩 RGBA PNG (可直接查看)
        Layer 1: 原始灰度 PNG (像素值 = 遮挡深度) + 值域说明文件
        Layer 2: 索引色 PNG (palette index = 碰撞类型) 或灰度 PNG + 值域说明文件
        """
        sec = self._get_sec()
        if sec is None: return
        if isinstance(sec, GRPAudioSection): self._export_audio(sec); return
        if isinstance(sec, GRPDataSection):
            p = filedialog.asksaveasfilename(title="导出原始数据", defaultextension=".bin",
                                              initialfile=f"sec{sec.index:03d}_data.bin")
            if p and sec._raw: Path(p).write_bytes(sec._raw)
            return
        if not isinstance(sec, GRPSection): return

        w, h = sec.width, sec.height
        suffix = {"A": "frameA", "L1": "layer1", "L2": "layer2"}.get(self._sel_layer, "layer")
        p = filedialog.asksaveasfilename(title=f"导出 {self._sel_layer}", defaultextension=".png",
                                          filetypes=[("PNG", "*.png")],
                                          initialfile=f"sec{sec.index:03d}_{suffix}.png")
        if not p: return

        if self._sel_layer == "A":
            rgba = self._get_layer_rgba(sec, "A")
            if rgba is None: return
            export_png_rgba(w, h, bytes(rgba), p)

        elif self._sel_layer == "L1":
            if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
            data = sec.layer1
            if not data: return
            # 原始灰度 PNG: 像素值 = 实际遮挡深度 (不拉伸)
            img = Image.frombytes("L", (w, h), data[:w*h])
            img.save(p, "PNG")
            # 写入值域说明文件
            self._export_value_legend(p, data, "Layer 1 — 前景遮挡深度")

        elif self._sel_layer == "L2":
            if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
            data = sec.layer2
            if not data: return
            # 构建索引调色板: palette[i] = 碰撞类型 i 的显示颜色
            pal = bytearray(768)
            for v in range(256):
                c = _collision_color(v)
                pal[v*3] = c[0]; pal[v*3+1] = c[1]; pal[v*3+2] = c[2]
            img = Image.frombytes("P", (w, h), data[:w*h])
            img.putpalette(bytes(pal))
            img.save(p, "PNG")
            # 写入值域说明文件
            self._export_value_legend(p, data, "Layer 2 — 地形碰撞类型")

        self._status_lbl.config(text=f"已导出: {Path(p).name}")

    def _export_value_legend(self, png_path: str, data: bytes, title: str):
        """导出值域说明文件, 方便用户知道每个灰度值代表什么"""
        legend_path = str(Path(png_path).with_suffix('.txt'))
        vals = sorted(Counter(data).items())
        lines = [f"# {title}", f"# 像素值 → 含义", ""]
        for v, cnt in vals:
            if v == 0:
                lines.append(f"  {v:3d} (共{cnt:6d}px) = 空白/无数据")
            elif title.startswith("Layer 1"):
                lines.append(f"  {v:3d} (共{cnt:6d}px) = 遮挡深度等级 {v}")
            else:
                lines.append(f"  {v:3d} (共{cnt:6d}px) = 碰撞类型 #{v}  ({_collision_color(v)[:3]})")
        lines.append("")
        lines.append("# 编辑指南:")
        if title.startswith("Layer 1"):
            lines.append("#   - 在图片编辑器中使用灰度值 0~255 的铅笔/画笔工具")
            lines.append("#   - 灰度值 0 = 无遮挡 (透明区域)")
            lines.append("#   - 灰度值 N = 深度等级 N (值越大, 遮挡优先级越高)")
        else:
            lines.append("#   - 在图片编辑器中使用索引色模式 (保留调色板)")
            lines.append("#   - 或用铅笔工具涂特定灰度值 (0=可行走, 1~N=碰撞类型)")
            lines.append("#   - 保存为 PNG 索引色格式以保留碰撞类型ID")
        Path(legend_path).write_text('\n'.join(lines), encoding='utf-8')

    # ── [新增] 伪彩色导入/导出逻辑 ──────────────────────
    def _export_pseudo(self):
        """导出当前层的伪彩图及配套吸色板"""
        sec = self._get_sec()
        if not isinstance(sec, GRPSection) or self._sel_layer not in ("L1", "L2"):
            messagebox.showinfo("提示", "请先选中 Layer 1 (遮挡) 或 Layer 2 (碰撞)！")
            return

        if not sec.is_decoded_b: _decode_section_b(self.grp, sec)
        data = sec.layer1 if self._sel_layer == "L1" else sec.layer2
        if not data: return

        p = filedialog.asksaveasfilename(
            title=f"导出 {self._sel_layer} 伪彩图", 
            defaultextension=".png", 
            filetypes=[("PNG", "*.png")],
            initialfile=f"sec{sec.index:03d}_{self._sel_layer}_Color.png"
        )
        if not p: return

        try:
            lut = _L1_VAL2RGB if self._sel_layer == "L1" else _L2_VAL2RGB
            
            # 1. 导出主图 (RGB模式)
            rgb_bytes = bytearray(sec.width * sec.height * 3)
            for i, val in enumerate(data[:sec.width * sec.height]):
                c = lut.get(val, (0,0,0))
                rgb_bytes[i*3] = c[0]; rgb_bytes[i*3+1] = c[1]; rgb_bytes[i*3+2] = c[2]
            
            img = Image.frombytes("RGB", (sec.width, sec.height), bytes(rgb_bytes))
            img.save(p, "PNG")

            # 2. 导出"配套吸色板" (只列出当前图层使用到的值，方便PS吸色)
            if HAS_PIL:
                pal_size = 24  # 每个色块的大小
                vals = sorted(set(data[:sec.width * sec.height]))
                cols = min(16, len(vals))
                rows = (len(vals) - 1) // 16 + 1
                pal_img = Image.new("RGB", (max(1, cols) * pal_size, max(1, rows) * pal_size), "black")
                draw = ImageDraw.Draw(pal_img)
                
                for idx, val in enumerate(vals):
                    x = (idx % 16) * pal_size; y = (idx // 16) * pal_size
                    draw.rectangle([x, y, x + pal_size - 1, y + pal_size - 1], fill=lut.get(val, (0,0,0)))
                
                pal_path = str(Path(p).with_name(Path(p).stem + "_Palette.png"))
                pal_img.save(pal_path, "PNG")

            self._status_lbl.config(text=f"已导出伪彩图及配套吸色板: {Path(p).name}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _import_pseudo(self):
        """导入在外部编辑好的伪彩图，精准还原为数据字节"""
        sec = self._get_sec()
        if not isinstance(sec, GRPSection) or self._sel_layer not in ("L1", "L2"):
            messagebox.showinfo("提示", "请先选中 Layer 1 或 Layer 2！")
            return

        p = filedialog.askopenfilename(
            title=f"导入伪彩图以替换 {self._sel_layer}", 
            filetypes=[("PNG", "*.png"), ("图片", "*.bmp")]
        )
        if not p: return

        try:
            # 强制转换为 RGB (24-bit)，自动去除透明度通道，确保引擎兼容性
            img = Image.open(p).convert("RGB")
            if img.size != (sec.width, sec.height):
                if not messagebox.askyesno("尺寸不匹配", f"尺寸不一致，强制缩放？"): return
                img = img.resize((sec.width, sec.height), Image.NEAREST)

            lut_rev = _L1_RGB2VAL if self._sel_layer == "L1" else _L2_RGB2VAL
            pixels = img.getdata()

            # 精确查表 + 最近邻 fallback (处理反锯齿/色彩空间偏移)
            out_bytes = bytes([_nearest_color(p, lut_rev) for p in pixels])

            if self._sel_layer == "L1": sec._layer1 = out_bytes
            else: sec._layer2 = out_bytes; sec.has_layer2 = True

            sec._decoded_b = True; sec._modified_b = True
            self._pil_img = None; self._tk_img = None
            self._refresh_view(); self._update_detail()
            self._status_lbl.config(text=f"{self._sel_layer} 伪彩图已导入并解析为精确数据！")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    # ── Audio ─────────────────────────────────────────
    def _toggle_audio(self):
        if self._audio_playing: self._stop_audio(); return
        sec = self._get_sec()
        if not isinstance(sec, GRPAudioSection) or not sec._raw or len(sec._raw) < 44: return
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False); tmp.close()
            Path(tmp.name).write_bytes(sec._raw)
            self._audio_tmp = tmp.name
            import time
            self._wave_start_time = time.time()

            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(tmp.name, winsound.SND_ASYNC | winsound.SND_FILENAME)
                self._audio_playing = True; self._btn_play.configure(text="■ 停止")
                # 立即绘制带播放头的波形, 启动动画循环
                self._draw_audio_view(sec)
                self._poll_audio_done(sec)
            else:
                player = 'aplay' if shutil.which('aplay') else ('afplay' if sys.platform == 'darwin' else 'paplay')
                self._audio_proc = subprocess.Popen([player, tmp.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._audio_playing = True; self._btn_play.configure(text="■ 停止")
                self._draw_audio_view(sec)
                self.root.after(int(sec._duration * 1000) + 200, self._stop_audio)
        except Exception as e:
            self._status_lbl.config(text=f"播放失败: {e}")

    def _poll_audio_done(self, sec: GRPAudioSection):
        """轮询 winsound 异步播放状态 (使用 wall-clock 时间)"""
        if not self._audio_playing: return
        try:
            elapsed = __import__('time').time() - self._wave_start_time
            dur = sec._duration if sec._duration > 0 else 1.0
            if elapsed >= dur + 0.15:  # 超时停止 (留 150ms 余量)
                self._stop_audio()
            else:
                self.root.after(80, lambda: self._poll_audio_done(sec))
        except:
            self._stop_audio()

    def _stop_audio(self):
        if not self._audio_playing: return
        try:
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            elif self._audio_proc:
                self._audio_proc.terminate(); self._audio_proc = None
        except: pass
        self._audio_playing = False; self._btn_play.configure(text="▶ 播放")
        if self._wave_anim_job: self.root.after_cancel(self._wave_anim_job); self._wave_anim_job = None
        # 只删除进度元素, 保留波形
        self._canvas.delete("prog", "prog_overlay")
        if self._audio_tmp:
            try: os.unlink(self._audio_tmp)
            except: pass; self._audio_tmp = None
        # 重绘波形 (不带播放头)
        sec = self._get_sec()
        if isinstance(sec, GRPAudioSection):
            self._draw_audio_view(sec)

    def _replace_audio(self):
        sec = self._get_sec()
        if not isinstance(sec, GRPAudioSection): return
        p = filedialog.askopenfilename(title="替换 WAV", filetypes=[("WAV", "*.wav"), ("All", "*.*")])
        if not p: return
        try:
            raw = Path(p).read_bytes()
            sec._raw = raw; sec._samples = None; sec.parse_wav()
            self._sync_list(); self._update_detail(); self._refresh_view()
            self._status_lbl.config(text=f"音频已替换 → {Path(p).name} ({len(raw)}B)")
        except Exception as e: messagebox.showerror("替换失败", str(e))

    def _export_audio(self, sec: GRPAudioSection):
        p = filedialog.asksaveasfilename(title="导出音频", defaultextension=".wav",
                                          filetypes=[("WAV", "*.wav")],
                                          initialfile=f"sec{sec.index:03d}_audio.wav")
        if not p: return
        if sec._raw: Path(p).write_bytes(sec._raw); self._status_lbl.config(text=f"已导出: {Path(p).name}")


# ═══════════════════════════════════════════════════════════

def main():
    root = tk.Tk(); fp = sys.argv[1] if len(sys.argv) > 1 else None
    GRPEditor(root, fp); root.mainloop()

if __name__ == "__main__":
    if not HAS_PIL: print("需要 Pillow: pip install Pillow"); sys.exit(1)
    main()