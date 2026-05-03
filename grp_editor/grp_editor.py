#!/usr/bin/env python3
"""
GRP 资源包编辑器 — 浏览/预览/编辑/导出三国群侠传 .grp 格式资源包
=================================================================
格式依据: sub_451600 (GRP加载), sub_411308 (地图加载), sub_410E18 (Frame B RLE)
          sub_452B14 (LZSS), 分析报告 09_GXP_JVG_GRP格式深度对比分析.md

GRP 资源包特征:
  - 多区块 (section): 无文件级魔数, 通过 .IDX 索引定位
  - 图像区块: Frame A (RGB565 LZSS 主图) + Frame B (RLE byte-pair 遮罩)
    · Layer 1 = 前景遮挡深度值
    · Layer 2 = 地形碰撞类型值 (每个唯一值代表一种地形)
  - 音频区块: 原始 WAV 数据 (SSF/SWS/SMG.grp)
  - 每个 Layer 可独立预览、替换、导出

用法: python grp_editor.py [file.grp]
"""

from __future__ import annotations
import os, sys, struct, zlib, wave, tempfile, subprocess, shutil, io, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List, Optional, Tuple
from collections import Counter

HAS_PIL = False
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass

# ── 常量 ──────────────────────────────────────────────────
SECTION_HEADER_SIZE = 12
RING_SIZE = 4096
RING_INIT = RING_SIZE - 18       # 4078
RING_INIT_VALUE = 0x20
MIN_MATCH_LZ = 3                 # (code)+3
MAX_MATCH_LZ = 18                # 15+3

# Layer 2 地形类型着色表 (可自定义)
_COLLISION_COLORS = {
    0:  (0, 0, 0, 0),         # 可行走 → 透明
    1:  (255, 0, 0, 200),     # 类型1 → 红色
    2:  (0, 200, 0, 200),     # 类型2 → 绿色
    3:  (0, 100, 255, 200),   # 类型3 → 蓝色
    4:  (255, 200, 0, 200),   # 类型4 → 金色
    5:  (255, 0, 255, 200),   # 类型5 → 品红
    6:  (0, 200, 200, 200),   # 类型6 → 青色
    7:  (200, 100, 0, 200),   # 类型7 → 橙色
    8:  (128, 0, 255, 200),   # 类型8 → 紫色
    9:  (150, 150, 150, 200), # 类型9 → 灰色
    10: (255, 128, 128, 200),
}

def _collision_color(val: int):
    if val in _COLLISION_COLORS: return _COLLISION_COLORS[val]
    if val == 0: return (0, 0, 0, 0)
    h = (val * 67 + 150) % 360
    x = int(255 * (1 - abs((h / 60) % 2 - 1)))
    r, g, b = [(255, x, 0), (x, 255, 0), (0, 255, x), (0, x, 255), (x, 0, 255), (255, 0, x)][int(h // 60)]
    return (r, g, b, 200)


# ═══════════════════════════════════════════════════════════
# LZSS 解压/压缩 (与 gxp_editor 共用引擎)
# ═══════════════════════════════════════════════════════════

def lzss_decompress(data: bytes, target_size: int) -> bytes:
    ring = bytearray([RING_INIT_VALUE] * RING_SIZE)
    ring_pos, pos = RING_INIT, 0
    out = bytearray()
    while pos < len(data) and len(out) < target_size:
        flag = data[pos]; pos += 1
        for bit in range(8):
            if pos >= len(data) or len(out) >= target_size: break
            if flag & (1 << bit):
                b = data[pos]; pos += 1
                out.append(b)
                ring[ring_pos % RING_SIZE] = b; ring_pos += 1
            else:
                if pos + 2 > len(data): break
                b1, b2 = data[pos], data[pos + 1]; pos += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3
                for k in range(length):
                    b = ring[(offset + k) % RING_SIZE]
                    out.append(b)
                    ring[ring_pos % RING_SIZE] = b; ring_pos += 1
    return bytes(out[:target_size])


def _hash_2b(a: int, b: int) -> int:
    return ((a << 8) | b) & 0xFFF

def lzss_compress(data: bytes) -> bytes:
    n = len(data)
    if n == 0: return b""
    hash_heads = [-1] * 4096
    hash_next = [-1] * n
    for i in range(n - 1, -1, -1):
        if i + 1 < n:
            h = _hash_2b(data[i], data[i + 1])
            hash_next[i] = hash_heads[h]; hash_heads[h] = i
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
        best_len, best_off = 0, 0
        if n - pos >= 2:
            chain = hash_heads[_hash_2b(data[pos], data[pos + 1])]
            steps = 0
            while chain >= 0 and steps < 64:
                if pos - chain > RING_SIZE: break
                if chain < pos:
                    ml = 0
                    while ml < min(n - pos, MAX_MATCH_LZ) and data[chain + ml] == data[pos + ml]:
                        ml += 1
                    if ml > best_len: best_len, best_off = ml, pos - chain
                    if ml == MAX_MATCH_LZ: break
                chain = hash_next[chain]; steps += 1
        if best_len >= MIN_MATCH_LZ:
            rp = (RING_INIT + pos) % RING_SIZE
            ao = (rp - best_off) % RING_SIZE
            entries.append((False, bytes([ao & 0xFF, ((ao >> 4) & 0xF0) | ((best_len - 3) & 0x0F)])))
            pos += best_len
        else:
            entries.append((True, bytes([data[pos]]))); pos += 1
        if len(entries) >= 8: flush()
    flush()
    return bytes(buf)


# ═══════════════════════════════════════════════════════════
# RLE byte-pair 解压/压缩 (Frame B, sub_410E18)
# ═══════════════════════════════════════════════════════════

def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    """RLE byte-pair 解压 — sub_410E18 逆向: count-value 对展开"""
    out = bytearray()
    pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count, value = data[pos], data[pos + 1]; pos += 2
        out.extend(bytes([value] * count))
    return bytes(out[:target_size])

def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    """探测是否为 RLE byte-pair: 累加 count 是否匹配期望大小"""
    total, pos = 0, 0
    while pos + 1 < len(data):
        total += data[pos]; pos += 2
    return total == expected_size

def rle_bp_compress(data: bytes) -> bytes:
    """RLE byte-pair 压缩 — 连续的相同字节编码为 (count, value) 对"""
    if not data: return b""
    out = bytearray()
    i = 0
    while i < len(data):
        v = data[i]; c = 1
        while i + c < len(data) and data[i + c] == v and c < 255:
            c += 1
        out.append(c); out.append(v)
        i += c
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
        lo, hi = raw[i * 2], raw[i * 2 + 1]
        off3 = (lo | (hi << 8)) * 3; off4 = i * 4
        rgba[off4:off4 + 3] = _RGB565_LUT[off3:off3 + 3]; rgba[off4 + 3] = 255
    return rgba

def rgba_to_rgb565(rgba_bytes: bytes, w: int, h: int) -> bytes:
    raw = bytearray(w * h * 2)
    for i in range(w * h):
        off4 = i * 4
        r5 = (rgba_bytes[off4] >> 3) & 0x1F
        g6 = (rgba_bytes[off4 + 1] >> 2) & 0x3F
        b5 = (rgba_bytes[off4 + 2] >> 3) & 0x1F
        val = (r5 << 11) | (g6 << 5) | b5
        raw[i * 2] = val & 0xFF; raw[i * 2 + 1] = (val >> 8) & 0xFF
    return bytes(raw)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class GRPSection:
    """图像区段: Frame A (RGB565 主图) + Frame B (RLE 遮罩)"""
    def __init__(self, index: int, offset: int, width: int, height: int,
                 comp_a: int, comp_b: int):
        self.index = index; self.offset = offset
        self.width = width; self.height = height
        self.comp_a = comp_a; self.comp_b = comp_b
        self.uncomp_a = width * height * 2
        self._pixels: Optional[bytes] = None          # Frame A RGB565 原始字节
        self._decoded_a = False
        self._layer1: Optional[bytes] = None           # Layer 1 字节数组
        self._layer2: Optional[bytes] = None           # Layer 2 字节数组 (可能为 None)
        self._decoded_b = False
        self.has_layer2 = False

    @property
    def is_decoded_a(self) -> bool: return self._decoded_a
    @property
    def is_decoded_b(self) -> bool: return self._decoded_b
    @property
    def pixels(self) -> Optional[bytes]: return self._pixels
    @property
    def layer1(self) -> Optional[bytes]: return self._layer1
    @property
    def layer2(self) -> Optional[bytes]: return self._layer2

    @property
    def type_label(self) -> str:
        return f"IMG {self.width}×{self.height}"

class GRPAudioSection:
    """音频区段: WAV 原始数据"""
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index; self.offset = offset; self.size = size
        self._raw = raw_data
        self._wav_header: Optional[bytes] = None

    @property
    def raw(self) -> Optional[bytes]: return self._raw
    @property
    def type_label(self) -> str:
        if self._wav_info:
            return f"AUD {self._wav_info}"
        return f"AUD {self.size}B"

    def parse_wav(self):
        """尝试用 wave 模块解析 WAV 头"""
        if not self._raw or len(self._raw) < 44: return
        try:
            f = io.BytesIO(self._raw)
            with wave.open(f, 'rb') as wf:
                self._wav_info = f"{wf.getnchannels()}ch {wf.getframerate()}Hz {wf.getsampwidth()*8}bit"
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# GRP 文件 I/O
# ═══════════════════════════════════════════════════════════

class GRPFile:
    def __init__(self):
        self.sections: List[GRPSection] = []
        self.audio_sections: List[GRPAudioSection] = []
        self.idx_offsets: List[int] = []
        self.filepath: Optional[str] = None
        self.idx_path: Optional[str] = None
        self._raw_data: bytes = b""
        self.is_image_grp = True

    @property
    def total_sections(self) -> int:
        return len(self.sections) + len(self.audio_sections)

    def has_audio(self) -> bool:
        return len(self.audio_sections) > 0


def _try_image_section(data: bytes, offset: int, next_offset: int) -> Optional[GRPSection]:
    """尝试按图像区段解析; 失败返回 None (可能是音频)"""
    if offset + SECTION_HEADER_SIZE > len(data): return None
    w, h, ca, cb = struct.unpack_from("<HHII", data, offset)
    section_size = next_offset - offset
    if w == 0 or h == 0 or w > 4096 or h > 4096: return None
    if SECTION_HEADER_SIZE + ca + cb != section_size: return None
    return GRPSection(-1, offset, w, h, ca, cb)

def load_grp(filepath: str, idx_path: Optional[str] = None) -> GRPFile:
    """加载 GRP + IDX — 自动检测图像/音频区段"""
    grp = GRPFile()
    grp.filepath = filepath
    grp._raw_data = Path(filepath).read_bytes()
    data = grp._raw_data
    fsize = len(data)

    # 尝试加载 IDX
    if idx_path is None:
        for ext in ['.IDX', '.idx']:
            candidate = str(Path(filepath).with_suffix(ext))
            if os.path.exists(candidate): idx_path = candidate; break
    if idx_path and os.path.exists(idx_path):
        idata = Path(idx_path).read_bytes()
        if len(idata) >= 8 and len(idata) % 4 == 0:
            offsets = [struct.unpack_from("<I", idata, i)[0] for i in range(0, len(idata), 4)]
            if offsets[-1] == fsize:
                grp.idx_offsets = offsets
                grp.idx_path = idx_path

    # 确定 section 边界
    if grp.idx_offsets:
        num = len(grp.idx_offsets) - 1
        boundaries = [(grp.idx_offsets[i], grp.idx_offsets[i + 1]) for i in range(num)]
    else:
        # 线性扫描
        boundaries = []; off = 0
        while off + SECTION_HEADER_SIZE <= fsize:
            w, h, ca, cb = struct.unpack_from("<HHII", data, off)
            if w == 0 or h == 0 or w > 4096 or h > 4096: break
            ss = SECTION_HEADER_SIZE + ca + cb
            if off + ss > fsize: break
            boundaries.append((off, off + ss))
            off += ss
        if boundaries:
            grp.idx_offsets = [b[0] for b in boundaries] + [boundaries[-1][1]]

    # 解析每个 section
    for idx, (so, eo) in enumerate(boundaries):
        sec = _try_image_section(data, so, eo)
        if sec:
            sec.index = idx
            grp.sections.append(sec)
        else:
            # 作为音频处理
            grp.audio_sections.append(GRPAudioSection(idx, so, eo - so, data[so:eo]))

    # 尝试解析音频 WAV 头
    for asec in grp.audio_sections:
        asec.parse_wav()
    if not grp.sections and grp.audio_sections:
        grp.is_image_grp = False

    return grp


def _decode_section_a(grp: GRPFile, sec: GRPSection):
    """解码 Frame A (LZSS)"""
    if sec._decoded_a: return
    data = grp._raw_data
    fa_off = sec.offset + SECTION_HEADER_SIZE
    uncomp_sz = struct.unpack_from("<I", data, fa_off)[0]
    lzss_data = data[fa_off + 4:fa_off + sec.comp_a]
    sec._pixels = lzss_decompress(lzss_data, min(uncomp_sz, sec.uncomp_a))
    if len(sec._pixels) < sec.uncomp_a:
        sec._pixels = sec._pixels + b'\x00' * (sec.uncomp_a - len(sec._pixels))
    sec._decoded_a = True

def _decode_section_b(grp: GRPFile, sec: GRPSection):
    """解码 Frame B (RLE byte-pair 或 LZSS fallback)"""
    if sec._decoded_b: return
    data = grp._raw_data
    fb_off = sec.offset + SECTION_HEADER_SIZE + sec.comp_a
    if fb_off + 4 > len(data): return
    declared = struct.unpack_from("<I", data, fb_off)[0]
    comp_start = fb_off + 4
    comp_data = data[comp_start:comp_start + sec.comp_b - 4]

    w, h = sec.width, sec.height
    total_px = w * h

    if rle_bp_probe(comp_data, declared):
        raw = rle_bp_decompress(comp_data, declared)
        sec._layer1 = raw[:total_px]
        if declared == total_px * 2 and len(raw) >= total_px * 2:
            sec._layer2 = raw[total_px:total_px * 2]
            sec.has_layer2 = True
    else:
        # LZSS fallback
        raw = lzss_decompress(comp_data, sec.uncomp_a)
        sec._layer1 = bytes(raw[i] for i in range(0, min(len(raw), total_px * 2), 2))
    sec._decoded_b = True


def save_grp(grp: GRPFile, filepath: str, idx_path: Optional[str] = None):
    """保存 GRP + IDX — 保持区段索引结构"""
    buf = bytearray()
    offsets = [0]
    total_img = len(grp.sections)
    total_aud = len(grp.audio_sections)

    # 合并所有 section 按 index 排序
    all_secs: list = []
    for s in grp.sections: all_secs.append(('img', s.index, s))
    for a in grp.audio_sections: all_secs.append(('aud', a.index, a))
    all_secs.sort(key=lambda x: x[1])

    for kind, idx, obj in all_secs:
        offsets.append(len(buf))
        if kind == 'img':
            sec = obj
            # Frame A: LZSS 压缩 RGB565
            if sec._pixels:
                lzss_data = lzss_compress(sec._pixels)
            else:
                lzss_data = b""
            comp_a = len(lzss_data) + 4
            # Frame B: RLE byte-pair
            if sec.has_layer2 and sec._layer1 and sec._layer2:
                l1 = sec._layer1[:sec.width * sec.height]
                l2 = sec._layer2[:sec.width * sec.height]
                fb_raw = l1 + l2
            elif sec._layer1:
                fb_raw = sec._layer1[:sec.width * sec.height]
            else:
                fb_raw = b""
            fb_enc = rle_bp_compress(fb_raw)
            comp_b = len(fb_enc) + 4

            buf += struct.pack("<HHII", sec.width, sec.height, comp_a, comp_b)
            buf += struct.pack("<I", sec.uncomp_a)
            buf += lzss_data
            buf += struct.pack("<I", len(fb_raw))
            buf += fb_enc
        else:
            asec = obj
            if asec._raw: buf += asec._raw

    offsets.append(len(buf))  # 末尾哨兵

    Path(filepath).write_bytes(bytes(buf))

    # 保存 IDX
    if idx_path is None:
        idx_path = str(Path(filepath).with_suffix('.idx'))
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
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    Path(path).write_bytes(png)


# ═══════════════════════════════════════════════════════════
# GUI 编辑器
# ═══════════════════════════════════════════════════════════

class GRPEditor:
    def __init__(self, root: tk.Tk, filepath: Optional[str] = None):
        self.root = root; self.root.title("GRP 资源包编辑器")
        self.root.geometry("1320x820")
        self.grp: Optional[GRPFile] = None
        self._sel_idx = -1              # 选中的 section index (按 all_secs 排序)
        self._sel_layer = "A"           # 当前预览层: "A", "L1", "L2"
        self._zoom = tk.DoubleVar(value=1.0)
        self._pan_x, self._pan_y = 0, 0; self._pan_start = None
        self._tk_img = None; self._pil_img = None
        self._audio_playing = False; self._audio_proc = None

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
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_close)
        mb.add_cascade(label="文件", menu=fm)
        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="原始大小 (100%)", command=lambda: self._set_zoom(1.0))
        vm.add_command(label="适合窗口", command=self._fit_to_window)
        vm.add_command(label="放大", command=lambda: self._zoom_step(0.25))
        vm.add_command(label="缩小", command=lambda: self._zoom_step(-0.25))
        mb.add_cascade(label="视图", menu=vm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="关于 GRP 格式", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.config(menu=mb)
        self.root.bind("<Control-o>", lambda e: self._open_dlg())
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-Shift-s>", lambda e: self._save_as())

    # ── UI Layout ─────────────────────────────────────
    def _setup_ui(self):
        # Toolbar
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Button(tb, text="打开 GRP", command=self._open_dlg).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="保存", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # 图层切换按钮
        self._btn_a = ttk.Button(tb, text="Frame A", command=lambda: self._switch_layer("A"))
        self._btn_a.pack(side=tk.LEFT, padx=1)
        self._btn_l1 = ttk.Button(tb, text="Layer 1", command=lambda: self._switch_layer("L1"))
        self._btn_l1.pack(side=tk.LEFT, padx=1)
        self._btn_l2 = ttk.Button(tb, text="Layer 2", command=lambda: self._switch_layer("L2"))
        self._btn_l2.pack(side=tk.LEFT, padx=1)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        ttk.Button(tb, text="替换当前层", command=self._replace_layer).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="导出当前层", command=self._export_layer).pack(side=tk.LEFT, padx=2)
        self._btn_play = ttk.Button(tb, text="▶ 播放", command=self._toggle_audio)
        self._btn_play.pack(side=tk.LEFT, padx=2)
        self._btn_replace_aud = ttk.Button(tb, text="替换音频", command=self._replace_audio)
        self._btn_replace_aud.pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        ttk.Button(tb, text="−", width=2, command=lambda: self._zoom_step(-0.25)).pack(side=tk.LEFT, padx=1)
        self._zlbl = ttk.Label(tb, text="100%", width=5); self._zlbl.pack(side=tk.LEFT)
        ttk.Button(tb, text="+", width=2, command=lambda: self._zoom_step(0.25)).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="⊡", width=2, command=self._fit_to_window).pack(side=tk.LEFT, padx=2)

        self._pixel_lbl = ttk.Label(tb, text="", foreground="#888"); self._pixel_lbl.pack(side=tk.RIGHT, padx=8)
        self._info_lbl = ttk.Label(tb, text=""); self._info_lbl.pack(side=tk.RIGHT, padx=8)

        # Main paned window
        self._pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL); self._pw.pack(fill=tk.BOTH, expand=True)

        # ── LEFT: Section list ────────────────────────
        lf = ttk.Frame(self._pw, width=260); self._pw.add(lf, weight=0)
        lh = ttk.Frame(lf); lh.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(lh, text="区段列表", font=("", 10, "bold")).pack(side=tk.LEFT)
        self._sec_count_lbl = ttk.Label(lh, text="", foreground="#888"); self._sec_count_lbl.pack(side=tk.RIGHT)

        # 列表 (带 scrollbar)
        lsf = ttk.Frame(lf); lsf.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._sec_list = tk.Listbox(lsf, exportselection=False, font=("Consolas", 9),
                                     bg="#252525", fg="#ccc", selectbackground="#2050a0")
        sl_sb = ttk.Scrollbar(lsf, orient=tk.VERTICAL, command=self._sec_list.yview)
        self._sec_list.configure(yscrollcommand=sl_sb.set)
        self._sec_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._sec_list.bind("<<ListboxSelect>>", self._on_section_select)

        # 选中区段信息
        self._sec_detail = tk.Text(lf, height=6, state=tk.DISABLED, font=("Consolas", 8),
                                    bg="#1e1e1e", fg="#999", wrap=tk.NONE, padx=4, pady=2)
        self._sec_detail.pack(fill=tk.X, padx=4, pady=(2, 4))

        # ── RIGHT: Canvas + Status ────────────────────
        rf = ttk.Frame(self._pw); self._pw.add(rf, weight=1)
        cf = ttk.Frame(rf); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 0))
        self._canvas = tk.Canvas(cf, bg="#1e1e1e", highlightthickness=0, cursor="crosshair")
        vsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self._canvas.yview)
        hsb = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns"); hsb.grid(row=1, column=0, sticky="ew")
        cf.grid_rowconfigure(0, weight=1); cf.grid_columnconfigure(0, weight=1)

        sf = ttk.Frame(rf); sf.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._status_lbl = ttk.Label(sf, text="就绪 — 打开 GRP 文件", foreground="#888")
        self._status_lbl.pack(side=tk.LEFT)
        ttk.Label(sf, text="Ctrl+滚轮=缩放 | 拖拽=平移", foreground="#555").pack(side=tk.RIGHT)

        self._update_buttons()

    def _bind_events(self):
        self._canvas.bind("<Configure>", lambda e: self._refresh_view())
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<ButtonPress-2>", self._pan_s)
        self._canvas.bind("<B2-Motion>", self._pan_m)
        self._canvas.bind("<ButtonRelease-2>", self._pan_e)
        self._canvas.bind("<ButtonPress-1>", self._pan_s)
        self._canvas.bind("<B1-Motion>", self._pan_m)
        self._canvas.bind("<ButtonRelease-1>", self._pan_e)
        self._canvas.bind("<Motion>", self._on_mouse_move)

    # ── Button state ──────────────────────────────────
    def _update_buttons(self):
        is_img = self._is_image_section()
        is_aud = self._is_audio_section()

        state_img = tk.NORMAL if is_img else tk.DISABLED
        state_aud = tk.NORMAL if is_aud else tk.DISABLED
        self._btn_a.configure(state=state_img)
        self._btn_l1.configure(state=state_img)
        self._btn_l2.configure(state=state_img)
        self._btn_play.configure(state=state_aud)
        self._btn_replace_aud.configure(state=state_aud)

        # 高亮当前层按钮
        for b, t in [(self._btn_a, "A"), (self._btn_l1, "L1"), (self._btn_l2, "L2")]:
            if is_img:
                b.configure(text=f"{'●' if self._sel_layer == t else '○'} {t.replace('A','Frame A')}")

    def _is_image_section(self) -> bool:
        sec = self._get_selected_section()
        return isinstance(sec, GRPSection)

    def _is_audio_section(self) -> bool:
        sec = self._get_selected_section()
        return isinstance(sec, GRPAudioSection)

    def _get_selected_section(self):
        if not self.grp or self._sel_idx < 0: return None
        for s in self.grp.sections:
            if s.index == self._sel_idx: return s
        for a in self.grp.audio_sections:
            if a.index == self._sel_idx: return a
        return None

    # ── Section list sync ─────────────────────────────
    def _sync_section_list(self):
        self._sec_list.delete(0, tk.END)
        if not self.grp: return
        all_secs = []
        for s in self.grp.sections: all_secs.append(('IMG', s.index, s))
        for a in self.grp.audio_sections: all_secs.append(('AUD', a.index, a))
        all_secs.sort(key=lambda x: x[1])
        for kind, idx, obj in all_secs:
            label = f"[{kind}] #{idx:03d}  {obj.type_label}"
            self._sec_list.insert(tk.END, label)
        self._sec_count_lbl.config(text=f"{len(all_secs)} sections")
        if all_secs:
            self._sec_list.selection_set(0)
            self._sel_idx = all_secs[0][1]
            self._sel_layer = "A"
            self._on_section_select()

    def _on_section_select(self, ev=None):
        sel = self._sec_list.curselection()
        if not self.grp or not sel: return
        all_secs = []
        for s in self.grp.sections: all_secs.append(('IMG', s.index, s))
        for a in self.grp.audio_sections: all_secs.append(('AUD', a.index, a))
        all_secs.sort(key=lambda x: x[1])
        if sel[0] < len(all_secs):
            self._sel_idx = all_secs[sel[0]][1]
            sec = self._get_selected_section()
            if isinstance(sec, GRPSection):
                self._sel_layer = "A"
            self._stop_audio()
            self._pil_img = None; self._tk_img = None
            self._pan_x = self._pan_y = 0
            self._fit_to_window()
            self._refresh_view()
            self._update_section_detail()
            self._update_buttons()

    def _update_section_detail(self):
        self._sec_detail.config(state=tk.NORMAL); self._sec_detail.delete(1.0, tk.END)
        sec = self._get_selected_section()
        if isinstance(sec, GRPSection):
            info = (
                f"区段 #{sec.index:03d} — 图像\n"
                f"尺寸: {sec.width}×{sec.height}\n"
                f"Frame A: {sec.comp_a}B @ {sec.offset + SECTION_HEADER_SIZE}\n"
                f"Frame B: {sec.comp_b}B @ {sec.offset + SECTION_HEADER_SIZE + sec.comp_a}\n"
            )
            if sec.is_decoded_b:
                if sec.has_layer2:
                    info += f"遮罩: RLE 双层 (Layer1 + Layer2)\n"
                else:
                    info += f"遮罩: RLE 单层\n"
                if sec.layer1:
                    vals = sorted(Counter(sec.layer1).items())
                    info += f"Layer1 值域: {len(vals)} 种 ({', '.join(f'{v}:{c}' for v,c in vals[:8])}{'...' if len(vals)>8 else ''})\n"
                if sec.has_layer2 and sec.layer2:
                    vals2 = sorted(Counter(sec.layer2).items())
                    info += f"Layer2 值域: {len(vals2)} 种 ({', '.join(f'{v}:{c}' for v,c in vals2[:8])}{'...' if len(vals2)>8 else ''})\n"
            info += f"Frame A: {'已解码' if sec.is_decoded_a else '未解码'}\n"
            info += f"Frame B: {'已解码' if sec.is_decoded_b else '未解码'}"
        elif isinstance(sec, GRPAudioSection):
            info = (f"区段 #{sec.index:03d} — 音频\n"
                    f"大小: {sec.size}B")
            if sec._wav_info:
                info += f"\n格式: {sec._wav_info}"
                try:
                    f = io.BytesIO(sec._raw)
                    with wave.open(f, 'rb') as wf:
                        dur = wf.getnframes() / wf.getframerate()
                        info += f"\n时长: {dur:.2f}s"
                except: pass
        else:
            info = "(无选中)"
        self._sec_detail.insert(tk.END, info); self._sec_detail.config(state=tk.DISABLED)

    # ── File ops ──────────────────────────────────────
    def _new_empty(self):
        self.grp = GRPFile(); self._sync_section_list()
        self._sel_idx = -1; self._refresh_view()
        self.root.title("GRP 编辑器 — [新建]")

    def _open_dlg(self):
        p = filedialog.askopenfilename(title="打开 GRP", filetypes=[("GRP", "*.grp *.GRP"), ("All", "*.*")])
        if p: self._open(p)

    def _open(self, p: str):
        try:
            self._status_lbl.config(text=f"加载中: {Path(p).name}..."); self.root.update()
            self._stop_audio()
            self.grp = load_grp(p)
            self._sync_section_list()
            self._sel_idx = -1; self._sel_layer = "A"
            if self.grp.total_sections > 0:
                self._sec_list.selection_set(0)
                self._on_section_select()
            self._refresh_view()
            id_info = f"  |  IDX: {Path(self.grp.idx_path).name}" if self.grp.idx_path else "  |  无 IDX"
            self._status_lbl.config(
                text=f"已加载: {Path(p).name}  |  {self.grp.total_sections} sections"
                f"  ({len(self.grp.sections)}IMG + {len(self.grp.audio_sections)}AUD){id_info}")
            self.root.title(f"GRP 编辑器 — {os.path.basename(p)}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _save(self):
        if not self.grp: return
        if self.grp.filepath: self._do_save(self.grp.filepath, self.grp.idx_path)
        else: self._save_as()

    def _save_as(self):
        p = filedialog.asksaveasfilename(title="保存 GRP", defaultextension=".grp",
                                          filetypes=[("GRP", "*.grp")])
        if p:
            idx_p = str(Path(p).with_suffix('.idx'))
            self._do_save(p, idx_p)

    def _do_save(self, grp_path: str, idx_path: Optional[str] = None):
        try:
            self._status_lbl.config(text="压缩中..."); self.root.update()
            save_grp(self.grp, grp_path, idx_path)
            self.grp.filepath = grp_path
            self.grp.idx_path = idx_path
            self._status_lbl.config(
                text=f"已保存: {Path(grp_path).name} ({os.path.getsize(grp_path)/1024:.1f}KB)"
                f"  +  {Path(idx_path).name if idx_path else '无IDX'}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _on_close(self):
        self._stop_audio(); self.root.destroy()

    # ── Layer switching ───────────────────────────────
    def _switch_layer(self, layer: str):
        if not self._is_image_section(): return
        self._sel_layer = layer
        self._pil_img = None; self._tk_img = None
        self._update_buttons(); self._refresh_view()
        self._update_section_detail()

    # ── View ──────────────────────────────────────────
    def _get_layer_rgba(self, sec: GRPSection, layer: str) -> Optional[bytearray]:
        """获取指定层的 RGBA 数据"""
        w, h = sec.width, sec.height; total = w * h
        if layer == "A":
            if not sec.is_decoded_a:
                _decode_section_a(self.grp, sec)
            if sec.pixels:
                return rgb565_to_rgba(sec.pixels, w, h)
            return bytearray(total * 4)
        elif layer in ("L1", "L2"):
            if not sec.is_decoded_b:
                _decode_section_b(self.grp, sec)
            data = sec.layer1 if layer == "L1" else sec.layer2
            if not data: return None
            rgba = bytearray(total * 4)
            if layer == "L1":
                # Layer 1: 灰度拉伸
                vmin = min(data) if data else 0
                vmax = max(data) if data else 255
                rng = max(vmax - vmin, 1)
                for i in range(min(len(data), total)):
                    v = int((data[i] - vmin) * 255 / rng)
                    rgba[i * 4:i * 4 + 3] = bytes([v, v, v])
                    rgba[i * 4 + 3] = 0 if data[i] == 0 else 200
            else:
                # Layer 2: 地形类型着色
                for i in range(min(len(data), total)):
                    c = _collision_color(data[i])
                    rgba[i * 4:i * 4 + 4] = bytes(c)
            return rgba
        return None

    def _refresh_view(self):
        self._canvas.delete("all")
        sec = self._get_selected_section()
        if not sec: return

        if isinstance(sec, GRPAudioSection):
            cw = self._canvas.winfo_width(); ch = self._canvas.winfo_height()
            self._canvas.create_text(cw // 2, ch // 2 - 20, text="🎵 音频区段", fill="#4af", font=("", 16))
            self._canvas.create_text(cw // 2, ch // 2 + 20, text=sec.type_label, fill="#888", font=("", 12))
            return

        if isinstance(sec, GRPSection):
            rgba = self._get_layer_rgba(sec, self._sel_layer)
            if rgba is None:
                # Layer 2 不存在
                cw = self._canvas.winfo_width(); ch = self._canvas.winfo_height()
                self._canvas.create_text(cw // 2, ch // 2, text="Layer 2 不可用 (单层遮罩)", fill="#666", font=("", 12))
                return

            w, h = sec.width, sec.height
            z = self._zoom.get()
            sw, sh = int(w * z), int(h * z)

            if self._pil_img is None and HAS_PIL:
                raw = bytes(rgba)
                self._pil_img = Image.frombytes("RGBA", (w, h), raw)
            if self._pil_img is None: return

            display = self._pil_img
            if z != 1.0:
                display = self._pil_img.resize((max(1, sw), max(1, sh)), Image.NEAREST)

            self._tk_img = ImageTk.PhotoImage(display)
            cw = self._canvas.winfo_width(); ch = self._canvas.winfo_height()
            x = max(0, (cw - sw) // 2) + self._pan_x
            y = max(0, (ch - sh) // 2) + self._pan_y
            self._canvas.create_image(x, y, anchor=tk.NW, image=self._tk_img, tags=("img",))
            self._canvas.configure(scrollregion=(0, 0, max(cw, sw + 40), max(ch, sh + 40)))

            self._zlbl.config(text=f"{int(z * 100)}%")
            layer_names = {"A": "Frame A (主图)", "L1": "Layer 1 (遮挡)", "L2": "Layer 2 (碰撞)"}
            self._info_lbl.config(text=f"#{sec.index:03d}  {w}×{h}  |  {layer_names.get(self._sel_layer, '')}")

    def _set_zoom(self, z: float):
        self._zoom.set(max(0.25, min(5.0, z)))
        self._tk_img = None; self._refresh_view()

    def _zoom_step(self, delta: float):
        self._set_zoom(self._zoom.get() + delta)

    def _fit_to_window(self):
        sec = self._get_selected_section()
        if not sec or isinstance(sec, GRPAudioSection): return
        cw = self._canvas.winfo_width() - 40 or 800
        ch = self._canvas.winfo_height() - 40 or 600
        z = min(2.0, cw / max(sec.width, 1), ch / max(sec.height, 1))
        self._set_zoom(max(0.25, z)); self._pan_x = self._pan_y = 0

    # ── Pan & Zoom ────────────────────────────────────
    def _pan_s(self, ev): self._pan_start = (ev.x, ev.y)
    def _pan_m(self, ev):
        if self._pan_start is None: return
        dx = ev.x - self._pan_start[0]; dy = ev.y - self._pan_start[1]
        self._pan_x += dx; self._pan_y += dy
        self._pan_start = (ev.x, ev.y); self._refresh_view()
    def _pan_e(self, ev): self._pan_start = None
    def _on_mousewheel(self, ev):
        if ev.state & 0x4: self._zoom_step(0.25 if ev.delta > 0 else -0.25)
        elif ev.state & 0x1: self._canvas.xview_scroll(-ev.delta // 120, "units")
        else: self._canvas.yview_scroll(-ev.delta // 120, "units")

    def _on_mouse_move(self, ev):
        sec = self._get_selected_section()
        if not isinstance(sec, GRPSection): return
        w, h = sec.width, sec.height; z = self._zoom.get()
        sw, sh = int(w * z), int(h * z)
        cw = self._canvas.winfo_width(); ch = self._canvas.winfo_height()
        ox = max(0, (cw - sw) // 2) + self._pan_x; oy = max(0, (ch - sh) // 2) + self._pan_y
        px = int((ev.x - ox) / z); py = int((ev.y - oy) / z)
        if 0 <= px < w and 0 <= py < h:
            idx = py * w + px
            if self._sel_layer == "A":
                if sec.is_decoded_a and sec.pixels and idx * 2 + 1 < len(sec.pixels):
                    lo, hi = sec.pixels[idx * 2], sec.pixels[idx * 2 + 1]
                    val565 = lo | (hi << 8)
                    r5, g6, b5 = (val565 >> 11) & 0x1F, (val565 >> 5) & 0x3F, val565 & 0x1F
                    self._pixel_lbl.config(text=f"({px},{py})  #565=0x{val565:04X}  RGB=({r5<<3},{g6<<2},{b5<<3})")
            elif self._sel_layer == "L1" and sec.layer1 and idx < len(sec.layer1):
                self._pixel_lbl.config(text=f"({px},{py})  L1深度={sec.layer1[idx]}")
            elif self._sel_layer == "L2" and sec.layer2 and idx < len(sec.layer2):
                self._pixel_lbl.config(text=f"({px},{py})  L2碰撞类型={sec.layer2[idx]}")
            else:
                self._pixel_lbl.config(text=f"({px},{py})")
        else:
            self._pixel_lbl.config(text="")

    # ── Layer replacement ─────────────────────────────
    def _replace_layer(self):
        sec = self._get_selected_section()
        if not isinstance(sec, GRPSection): return
        layer = self._sel_layer
        if layer == "A":
            self._replace_frame_a(sec)
        elif layer in ("L1", "L2"):
            self._replace_layer_byte(sec, layer)

    def _replace_frame_a(self, sec: GRPSection):
        """替换 Frame A: 导入 PNG → RGB565"""
        p = filedialog.askopenfilename(title="选择替换图片 (主图)", filetypes=[("图片", "*.png *.bmp *.jpg")])
        if not p: return
        try:
            img = Image.open(p).convert("RGBA")
            if img.size != (sec.width, sec.height):
                if not messagebox.askyesno("尺寸不匹配",
                    f"导入图片 {img.size[0]}×{img.size[1]} 与原尺寸 {sec.width}×{sec.height} 不一致。\n"
                    f"将自动缩放。是否继续?"):
                    return
                img = img.resize((sec.width, sec.height), Image.LANCZOS)
            rgba_data = img.tobytes()
            sec._pixels = rgba_to_rgb565(rgba_data, sec.width, sec.height)
            sec._decoded_a = True
            self._pil_img = None; self._tk_img = None
            self._refresh_view()
            self._status_lbl.config(text=f"Frame A 已替换 → {Path(p).name} ({sec.width}×{sec.height})")
        except Exception as e:
            messagebox.showerror("替换失败", str(e))

    def _replace_layer_byte(self, sec: GRPSection, layer: str):
        """替换 Layer 1/2: 导入 PNG → 灰度 → 字节数组"""
        p = filedialog.askopenfilename(title=f"选择替换图片 ({layer})", filetypes=[("PNG", "*.png"), ("BMP", "*.bmp")])
        if not p: return
        try:
            img = Image.open(p).convert("L")  # 灰度
            if img.size != (sec.width, sec.height):
                if not messagebox.askyesno("尺寸不匹配",
                    f"导入图片 {img.size[0]}×{img.size[1]} 与原尺寸 {sec.width}×{sec.height} 不一致。"
                    f"将自动缩放。是否继续?"):
                    return
                img = img.resize((sec.width, sec.height), Image.NEAREST)
            data = img.tobytes()
            if layer == "L1":
                sec._layer1 = data
            else:
                sec._layer2 = data
                sec.has_layer2 = True
            sec._decoded_b = True
            self._pil_img = None; self._tk_img = None
            self._refresh_view(); self._update_section_detail()
            self._status_lbl.config(text=f"{layer} 已替换 → {Path(p).name} (灰度值映射)")
        except Exception as e:
            messagebox.showerror("替换失败", str(e))

    # ── Layer export ──────────────────────────────────
    def _export_layer(self):
        sec = self._get_selected_section()
        if sec is None: return
        if isinstance(sec, GRPAudioSection):
            self._export_audio(sec); return
        if not isinstance(sec, GRPSection): return
        layer = self._sel_layer
        w, h = sec.width, sec.height
        rgba = self._get_layer_rgba(sec, layer)
        if rgba is None: return
        suffix = {"A": "frameA", "L1": "layer1", "L2": "layer2"}.get(layer, "layer")
        p = filedialog.asksaveasfilename(
            title=f"导出 {layer}", defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile=f"sec{sec.index:03d}_{suffix}.png")
        if not p: return
        export_png_rgba(w, h, bytes(rgba), p)
        self._status_lbl.config(text=f"已导出: {Path(p).name} ({w}×{h})")

    # ── Audio ─────────────────────────────────────────
    def _toggle_audio(self):
        if self._audio_playing:
            self._stop_audio(); return
        sec = self._get_selected_section()
        if not isinstance(sec, GRPAudioSection): return
        if not sec._raw or len(sec._raw) < 44: return
        try:
            # 写入临时 WAV 文件
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False); tmp.close()
            # 确保有 WAV 头
            if sec._raw[:4] == b"RIFF":
                Path(tmp.name).write_bytes(sec._raw)
            else:
                # 构造最小 WAV 头
                data_sz = len(sec._raw)
                hdr = bytearray(44)
                hdr[0:4] = b"RIFF"; struct.pack_into("<I", hdr, 4, data_sz + 36)
                hdr[8:16] = b"WAVEfmt \x10\x00\x00\x00"
                struct.pack_into("<HHIIHH", hdr, 16, 1, 1, 22050, 22050, 1, 8)
                hdr[36:40] = b"data"; struct.pack_into("<I", hdr, 40, data_sz)
                Path(tmp.name).write_bytes(bytes(hdr) + sec._raw)

            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(tmp.name, winsound.SND_ASYNC | winsound.SND_FILENAME)
                self._audio_playing = True
                self._audio_tmp = tmp.name
                self._btn_play.configure(text="■ 停止")
            else:
                # Linux/macOS fallback
                self._audio_proc = subprocess.Popen(['aplay', tmp.name] if shutil.which('aplay') else ['afplay', tmp.name],
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._audio_playing = True; self._audio_tmp = tmp.name
                self._btn_play.configure(text="■ 停止")
                self.root.after(500, self._check_audio_done)
        except Exception as e:
            self._status_lbl.config(text=f"播放失败: {e}")

    def _stop_audio(self):
        if not self._audio_playing: return
        try:
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            elif self._audio_proc:
                self._audio_proc.terminate(); self._audio_proc = None
        except: pass
        self._audio_playing = False
        self._btn_play.configure(text="▶ 播放")
        if hasattr(self, '_audio_tmp') and self._audio_tmp:
            try: os.unlink(self._audio_tmp)
            except: pass
            self._audio_tmp = None

    def _check_audio_done(self):
        if self._audio_proc and self._audio_proc.poll() is not None:
            self._stop_audio()
        elif self._audio_playing:
            self.root.after(500, self._check_audio_done)

    def _replace_audio(self):
        sec = self._get_selected_section()
        if not isinstance(sec, GRPAudioSection): return
        p = filedialog.askopenfilename(title="选择替换 WAV 文件", filetypes=[("WAV", "*.wav"), ("All", "*.*")])
        if not p: return
        try:
            raw = Path(p).read_bytes()
            # 验证 WAV 头
            if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
                if not messagebox.askyesno("格式警告", "文件不是标准 WAV 格式。是否仍以原始字节导入?"):
                    return
            sec._raw = raw
            sec.parse_wav()
            self._sync_section_list(); self._update_section_detail()
            self._status_lbl.config(text=f"音频已替换 → {Path(p).name} ({len(raw)}B)")
        except Exception as e:
            messagebox.showerror("替换失败", str(e))

    def _export_audio(self, sec: GRPAudioSection):
        p = filedialog.asksaveasfilename(title="导出音频", defaultextension=".wav",
                                          filetypes=[("WAV", "*.wav")],
                                          initialfile=f"sec{sec.index:03d}_audio.wav")
        if not p: return
        if sec._raw:
            Path(p).write_bytes(sec._raw)
            self._status_lbl.config(text=f"已导出: {Path(p).name} ({len(sec._raw)}B)")

    # ── About ──────────────────────────────────────────
    def _show_about(self):
        messagebox.showinfo("关于 GRP 格式",
            "GRP — 三国群侠传 通用资源包\n\n"
            "格式特征:\n"
            "  • 无文件级魔数, 通过 .IDX 索引定位区段\n"
            "  • 图像区段: Frame A (RGB565 LZSS) + Frame B (RLE byte-pair)\n"
            "    - Layer 1 = 前景遮挡深度值\n"
            "    - Layer 2 = 地形碰撞类型值\n"
            "  • 音频区段: 原始 WAV 数据 (SSF/SWS/SMG)\n"
            "  • 12 字节区段头 (W+H+compA+compB)\n\n"
            "操作提示:\n"
            "  Frame A / Layer1 / Layer2 — 切换预览层\n"
            "  替换当前层 — 导入 PNG 替换选中的层\n"
            "  导出当前层 — 导出为 PNG (含 Layer2 伪彩色)\n"
            "  ▶ 播放 — 播放/停止音频区段")

    def _start_audio_if_any(self):
        """打开文件后若有音频, 不自动播放"""
        pass


# ═══════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    GRPEditor(root, fp)
    root.mainloop()

if __name__ == "__main__":
    if not HAS_PIL:
        print("需要 Pillow: pip install Pillow")
        sys.exit(1)
    main()
