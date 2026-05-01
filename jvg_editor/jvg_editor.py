#!/usr/bin/env python3
"""
JVG 图集编辑器 — 浏览和编辑三国群侠传 .jvg 格式精灵图集
=============================================================

格式依据: PE逆向反编译 sub_453BD0 (JVG加载), sub_4544EC (RLE渲染)
严格遵循原游戏 @JVG/@JVM 二进制格式, 保证与原游戏兼容。

用法:
    python jvg_editor.py                     # 启动编辑器
    python jvg_editor.py <file.jvg>          # 打开指定文件
"""

from __future__ import annotations

import os
import sys
import struct
import io
import json
import zlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Optional

# Try Pillow for image handling; fall back to basic PNG parsing
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ============================================================================
# JVG 格式常量 (全部来自反编译 sub_453BD0 + sub_4544EC)
# ============================================================================

JVG_MAGIC   = b"@JVG"
JVM_MAGIC   = b"@JVM"
SCREEN_W    = 640     # sub_4544EC 硬编码屏幕宽度
HEADER_SIZE = 32      # @JVG + @JVM 各 32 字节


# ============================================================================
# JVG 数据模型
# ============================================================================

class PaletteRGB565:
    """256-entry RGB565 调色板"""
    def __init__(self):
        self.entries: List[int] = [0] * 256

    def to_rgb888(self) -> bytes:
        result = bytearray(768)
        for i, e in enumerate(self.entries):
            r5 = (e >> 11) & 0x1F
            g6 = (e >> 5) & 0x3F
            b5 = e & 0x1F
            result[i*3]   = (r5 << 3) | (r5 >> 2)
            result[i*3+1] = (g6 << 2) | (g6 >> 4)
            result[i*3+2] = (b5 << 3) | (b5 >> 2)
        return bytes(result)

    @classmethod
    def from_rgb888_list(cls, colors: List[Tuple[int,int,int]]) -> 'PaletteRGB565':
        p = cls()
        for i, (r, g, b) in enumerate(colors[:256]):
            r5 = (r >> 3) & 0x1F
            g6 = (g >> 2) & 0x3F
            b5 = (b >> 3) & 0x1F
            p.entries[i] = (r5 << 11) | (g6 << 5) | b5
        return p


class JVGFrame:
    """一帧精灵数据"""
    def __init__(self):
        self.x_max: int = 0      # 16-bit signed (虚拟屏幕右下X)
        self.y_max: int = 0      # 16-bit signed (虚拟屏幕右下Y)
        self.width: int = 0
        self.height: int = 0
        self.row_count: int = 0  # RLE段数
        self.pixels: bytes = b""       # 8-bit indexed
        self.alpha: bytes = b""        # per-pixel alpha (255=opaque)
        self.encoded_data: bytes = b"" # 原始编码数据

    @property
    def x_offset(self) -> int:
        """signed X offset = x_max - width + 1"""
        return self._u16_to_s16(self.x_max) - self.width + 1

    @property
    def y_offset(self) -> int:
        """signed Y offset = y_max - height + 1"""
        return self._u16_to_s16(self.y_max) - self.height + 1

    @staticmethod
    def _u16_to_s16(v: int) -> int:
        return v - 65536 if v >= 32768 else v


class JVMBlock:
    """一个 @JVM 分组 (动画组), 含共享调色板 + N 帧"""
    def __init__(self):
        self.name: str = ""
        self.frames: List[JVGFrame] = []
        self.palette: PaletteRGB565 = PaletteRGB565()

    @property
    def frame_count(self) -> int:
        return len(self.frames)


class JVGFile:
    """完整的 @JVG 文件"""
    def __init__(self):
        self.blocks: List[JVMBlock] = []
        self.filepath: Optional[str] = None

    @property
    def total_frames(self) -> int:
        return sum(b.frame_count for b in self.blocks)

    @property
    def block_count(self) -> int:
        return len(self.blocks)


# ============================================================================
# JVG 解码器 (复用已验证的格式逻辑)
# ============================================================================

def _u16_to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def _decode_rle(data: bytes, width: int, height: int) -> Tuple[bytes, bytes]:
    """解码 JVG RLE 像素数据 (来自 jvg_decoder.py 已验证逻辑)"""
    total = width * height
    output = bytearray(total)
    alpha = bytearray(total)

    # 解析 RLE 记录
    records = []
    pos = 0
    while pos + 4 <= len(data):
        skip = struct.unpack("<H", data[pos:pos+2])[0]
        run_width = struct.unpack("<H", data[pos+2:pos+4])[0]
        pos += 4
        if run_width > 0:
            end = min(pos + run_width, len(data))
            pixels = data[pos:end]
            pos = end
        else:
            pixels = b""
        records.append((skip, run_width, pixels))

    if not records:
        return bytes(output), bytes(alpha)

    is_simple = (records[0][0] == 0 and records[0][1] == width and
                 all(r[1] == width for r in records))

    if is_simple:
        for row_idx, (_skip, rw, pixels) in enumerate(records):
            if row_idx >= height:
                break
            target_row = height - 1 - row_idx
            for col in range(min(rw, len(pixels))):
                pos_out = target_row * width + col
                output[pos_out] = pixels[rw - 1 - col]
                alpha[pos_out] = 255
    else:
        gap = max(SCREEN_W - width, 0)
        buf_pos = total - 1
        pending_gap = 0

        for skip_adj, run_width, pixels in records:
            remaining = skip_adj - pending_gap
            if remaining < 0:
                remaining = 0

            while remaining > 0 and buf_pos >= 0:
                col = (total - 1 - buf_pos) % width
                to_boundary = width - col
                if remaining <= to_boundary:
                    buf_pos -= remaining
                    remaining = 0
                else:
                    buf_pos -= to_boundary
                    remaining -= to_boundary + gap
                    if remaining < 0:
                        remaining = 0

            col_before = (total - 1 - buf_pos) % width if buf_pos >= 0 else 0

            actual = min(run_width, len(pixels))
            for k in range(actual):
                if 0 <= buf_pos < total:
                    output[buf_pos] = pixels[k]
                    alpha[buf_pos] = 255
                buf_pos -= 1

            pending_gap = gap if (actual > 0 and (col_before + actual) >= width) else 0

    return bytes(output), bytes(alpha)


def load_jvg(filepath: str) -> JVGFile:
    """加载 .jvg 文件"""
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 32 or data[0:4] != JVG_MAGIC:
        raise ValueError("不是有效的 @JVG 文件")

    jvg = JVGFile()
    jvg.filepath = filepath

    block_count = struct.unpack("<I", data[8:12])[0]
    offset = HEADER_SIZE
    global_idx = 0

    for blk_i in range(block_count):
        if offset + 32 > len(data):
            break
        if data[offset:offset+4] != JVM_MAGIC:
            break

        sub_count = struct.unpack("<I", data[offset+4:offset+8])[0]
        data_size = struct.unpack("<I", data[offset+12:offset+16])[0]

        s1_offset = offset + 32
        cum_offsets = [struct.unpack("<I", data[s1_offset+j*4:s1_offset+j*4+4])[0]
                       for j in range(sub_count + 1)]

        pal_offset = s1_offset + (sub_count + 1) * 4
        block = JVMBlock()
        block.name = f"block_{blk_i:02d}"
        for j in range(256):
            block.palette.entries[j] = struct.unpack("<H",
                data[pal_offset+j*2:pal_offset+j*2+2])[0]

        data_region = pal_offset + 512
        for si in range(sub_count):
            sub_start = cum_offsets[si]
            sub_end = cum_offsets[si + 1]

            meta_off = data_region + sub_start
            words = struct.unpack("<8H", data[meta_off:meta_off+16])
            frame = JVGFrame()
            frame.x_max = words[0]
            frame.y_max = words[1]
            frame.width = words[2]
            frame.height = words[3]
            frame.row_count = words[7]

            enc_off = meta_off + 16
            enc_size = sub_end - sub_start - 16
            frame.encoded_data = data[enc_off:enc_off+enc_size]

            if frame.width > 0 and frame.height > 0:
                frame.pixels, frame.alpha = _decode_rle(
                    frame.encoded_data, frame.width, frame.height)

            block.frames.append(frame)
            global_idx += 1

        block_total = 32 + (sub_count+1)*4 + 512 + data_size
        offset += block_total
        jvg.blocks.append(block)

    return jvg


# ============================================================================
# JVG 编码器 (写入原游戏格式)
# ============================================================================

def _encode_rle_simple(pixels: bytes, width: int, height: int) -> bytes:
    """Simple mode RLE: full rows bottom-to-top, reversed"""
    buf = bytearray()
    for row in range(height - 1, -1, -1):
        row_start = row * width
        row_data = pixels[row_start:row_start + width]
        buf += struct.pack("<H", 0)              # skip = 0
        buf += struct.pack("<H", width)          # run_width
        buf += row_data[::-1]                     # reversed
    return bytes(buf)


def _encode_rle_complex(pixels: bytes, alpha: bytes,
                         width: int, height: int) -> bytes:
    """Complex mode RLE: sprite runs with background skip"""
    gap = max(SCREEN_W - width, 0)
    total = width * height
    buf = bytearray()
    pos = total - 1
    prev_crossings = 0

    while pos >= 0:
        # 跳过背景像素
        skip_count = 0
        row_crossings = 0
        start_pos = pos
        while pos >= 0 and (pos >= len(alpha) or alpha[pos] == 0):
            col = pos % width
            if col == width - 1 and pos > 0:
                row_crossings += 1
            pos -= 1
            skip_count += 1
        if start_pos != pos:
            buf += struct.pack("<H", skip_count + row_crossings * gap + prev_crossings)
            buf += struct.pack("<H", 0)
            prev_crossings = 0

        # 非背景像素
        run_start = pos
        run_crossings = 0
        while pos >= 0 and pos < len(alpha) and alpha[pos] != 0:
            col = pos % width
            if col == width - 1 and pos > 0:
                run_crossings += 1
            pos -= 1
        if run_start != pos:
            run_len = run_start - pos
            pixel_bytes = bytearray()
            for i in range(run_len):
                idx = run_start - i
                if idx < len(pixels):
                    pixel_bytes.append(pixels[idx])
            buf += struct.pack("<H", run_len)
            buf += bytes(pixel_bytes)
            prev_crossings = run_crossings * gap if run_crossings > 0 else 0

    # 末尾零长度标记
    buf += struct.pack("<H", 0) + struct.pack("<H", 0)
    return bytes(buf)


def _quantize_to_palette(pil_img: 'Image.Image') -> Tuple[bytes, bytes, List[Tuple[int,int,int]]]:
    """将 PIL 图像量化为调色板索引, 返回 (pixels, alpha, palette_rgb_list)"""
    if pil_img.mode != 'RGBA':
        pil_img = pil_img.convert('RGBA')
    w, h = pil_img.size
    pixels = bytearray(w * h)
    alpha = bytearray(w * h)

    color_map = {}
    palette = [(0, 0, 0)] * 256  # index 0 = black (transparent bg)
    next_idx = 1

    for y in range(h):
        for x in range(w):
            r, g, b, a = pil_img.getpixel((x, y))
            pos = y * w + x
            if a < 128:
                pixels[pos] = 0
                alpha[pos] = 0
            else:
                key = (r, g, b)
                if key not in color_map:
                    if next_idx >= 256:
                        # 找最近颜色
                        color_map[key] = min(range(1, 256),
                            key=lambda i: sum(abs(a-b) for a,b in zip(key, palette[i])))
                    else:
                        color_map[key] = next_idx
                        palette[next_idx] = key
                        next_idx += 1
                pixels[pos] = color_map[key]
                alpha[pos] = 255

    return bytes(pixels), bytes(alpha), palette


def save_jvg(jvg: JVGFile, filepath: str):
    """保存为原游戏兼容的 .jvg 格式 (Stream1 写 N+1 偏移, 与 sub_453BD0 一致)"""
    buf = bytearray()
    total_frames = jvg.total_frames
    # @JVG header (32 bytes)
    buf += JVG_MAGIC                                    # [0x00] magic
    buf += struct.pack("<I", len(jvg.blocks))            # [0x04] block_count
    buf += struct.pack("<I", len(jvg.blocks))            # [0x08] block_count
    buf += struct.pack("<I", 0)                           # [0x0C] data_size placeholder
    buf += struct.pack("<I", total_frames)                # [0x10] total sub-images
    buf += bytes(12)                                      # [0x14] padding

    for block in jvg.blocks:
        n = block.frame_count
        # @JVM header (32 bytes)
        header_start = len(buf)
        buf += JVM_MAGIC                                  # [0x00] magic
        buf += struct.pack("<I", n)                       # [0x04] sub_count
        buf += struct.pack("<I", 0)                       # [0x08] reserved
        data_size_pos = len(buf)
        buf += struct.pack("<I", 0)                       # [0x0C] data_size placeholder
        buf += bytes(16)                                   # [0x10] padding

        # Encode frames into bytearray, tracking cumulative offsets
        frame_data = bytearray()
        cum_offsets = [0]  # N+1 entries: cum_offsets[N] = total data_size

        for frame in block.frames:
            meta = struct.pack("<8H",
                frame.x_max & 0xFFFF,
                frame.y_max & 0xFFFF,
                frame.width,
                frame.height,
                0, 0, 0,                                    # reserved (6 bytes)
                0)                                          # row_count placeholder
            frame_data += meta

            # RLE encode: preserve original if available, else encode
            if frame.encoded_data:
                enc = frame.encoded_data
                # Update row_count from original RLE structure
                row_count = _count_rle_rows(enc, frame.width)
                struct.pack_into("<H", frame_data, len(frame_data) - 2, row_count)
            elif frame.pixels and frame.width > 0 and frame.height > 0:
                # Encode as simple mode (full rows) for imported images
                enc = _encode_rle_simple(frame.pixels, frame.width, frame.height)
                row_count = frame.height  # simple mode = one record per row
                struct.pack_into("<H", frame_data, len(frame_data) - 2, row_count)
            else:
                enc = b""

            frame_data += enc
            cum_offsets.append(cum_offsets[-1] + 16 + len(enc))

        data_size = cum_offsets[-1]

        # Stream1: cumulative offset table — MUST write N+1 entries (sub_453BD0 reads N+1)
        for off in cum_offsets:
            buf += struct.pack("<I", off)

        # Palette (RGB565, 512 bytes)
        for entry in block.palette.entries:
            buf += struct.pack("<H", entry & 0xFFFF)

        # Data region
        buf += frame_data

        # Fix up @JVM data_size
        struct.pack_into("<I", buf, data_size_pos, data_size)

    # Fix up @JVG total data size (bytes after header)
    total_data = len(buf) - HEADER_SIZE
    struct.pack_into("<I", buf, 12, total_data)

    with open(filepath, "wb") as f:
        f.write(bytes(buf))


def _count_rle_rows(data: bytes, frame_width: int) -> int:
    """统计简单模式 RLE 记录数 = 原始行数"""
    if not data or frame_width <= 0:
        return 0
    count = 0
    pos = 0
    while pos + 4 <= len(data):
        _skip = struct.unpack("<H", data[pos:pos+2])[0]
        run_w = struct.unpack("<H", data[pos+2:pos+4])[0]
        if run_w == frame_width:
            count += 1
        pos += 4 + run_w
    return count


def import_image_to_frame(filepath: str) -> Optional[JVGFrame]:
    """从图像文件导入为一帧"""
    if not HAS_PIL:
        messagebox.showerror("错误", "需要 Pillow 库: pip install Pillow")
        return None
    try:
        img = Image.open(filepath)
        frame = JVGFrame()
        frame.width, frame.height = img.size
        frame.pixels, frame.alpha, palette_rgb = _quantize_to_palette(img)
        # x_max = width-1 (left-aligned at origin), y_max = height-1 (top-aligned)
        s16 = lambda v: v if v < 32768 else v - 65536
        frame.x_max = s16(frame.width - 1)
        frame.y_max = s16(frame.height - 1)
        frame.row_count = 0  # will be computed during RLE encode
        return frame
    except Exception as e:
        messagebox.showerror("导入错误", f"无法读取 {filepath}: {e}")
        return None


# ============================================================================
# GUI 编辑器
# ============================================================================

class JVGEditor:
    def __init__(self, root: tk.Tk, filepath: Optional[str] = None):
        self.root = root
        self.root.title("JVG 图集编辑器")
        self.root.geometry("1200x750")
        self.root.minsize(900, 500)

        self.jvg: Optional[JVGFile] = None
        self.current_block_idx: int = -1
        self.current_frame_idx: int = 0
        self.view_mode: str = "tile"    # tile / single / anim
        self._anim_job: Optional[str] = None
        self._photo_cache: dict = {}

        self._setup_menu()
        self._setup_ui()

        if filepath and os.path.exists(filepath):
            self._open_file(filepath)
        else:
            self._new_file()

    # ----- Menu -----
    def _setup_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新建 (Ctrl+N)", command=self._new_file)
        file_menu.add_command(label="打开 (Ctrl+O)", command=self._open_dialog)
        file_menu.add_command(label="保存 (Ctrl+S)", command=self._save)
        file_menu.add_command(label="另存为...", command=self._save_as)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="平铺浏览", command=lambda: self._set_view("tile"))
        view_menu.add_command(label="逐帧浏览", command=lambda: self._set_view("single"))
        view_menu.add_command(label="动画预览", command=lambda: self._set_view("anim"))
        menubar.add_cascade(label="视图", menu=view_menu)
        self.root.config(menu=menubar)

        self.root.bind("<Control-n>", lambda e: self._new_file())
        self.root.bind("<Control-o>", lambda e: self._open_dialog())
        self.root.bind("<Control-s>", lambda e: self._save())

    # ----- UI Layout -----
    def _setup_ui(self):
        # Main paned window
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # -- Left panel: group list --
        left_frame = ttk.Frame(self.paned, width=220)
        self.paned.add(left_frame, weight=0)

        ttk.Label(left_frame, text="图集分组", font=("", 10, "bold")).pack(pady=(5, 2))

        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, padx=5)
        ttk.Button(btn_frame, text="+ 新增", command=self._add_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="- 删除", command=self._del_block).pack(side=tk.LEFT, padx=2)

        self.block_list = tk.Listbox(left_frame, exportselection=False)
        self.block_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.block_list.bind("<<ListboxSelect>>", self._on_block_select)

        ttk.Label(left_frame, text="图片操作:", font=("", 9)).pack(pady=(5, 2))
        op_frame = ttk.Frame(left_frame)
        op_frame.pack(fill=tk.X, padx=5)
        ttk.Button(op_frame, text="添加图片", command=self._add_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(op_frame, text="删除当前", command=self._del_frame).pack(side=tk.LEFT, padx=2)

        # -- Right panel: image viewer --
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=1)

        # Toolbar
        toolbar = ttk.Frame(right_frame)
        toolbar.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(toolbar, text="平铺", command=lambda: self._set_view("tile")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="逐帧", command=lambda: self._set_view("single")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="动画", command=lambda: self._set_view("anim")).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        self.info_label = ttk.Label(toolbar, text="")
        self.info_label.pack(side=tk.LEFT, padx=5)

        # Canvas with scroll
        self.canvas_frame = ttk.Frame(right_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#2a2a2a", highlightthickness=0)
        v_scroll = ttk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        self.canvas.bind("<Configure>", lambda e: self._refresh_view())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta//120, "units"))

        # Animation speed slider
        anim_ctrl = ttk.Frame(right_frame)
        anim_ctrl.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(anim_ctrl, text="动画速度(ms):").pack(side=tk.LEFT)
        self.anim_speed = tk.IntVar(value=120)
        ttk.Scale(anim_ctrl, from_=30, to=500, variable=self.anim_speed,
                  orient=tk.HORIZONTAL, length=150).pack(side=tk.LEFT, padx=5)
        ttk.Label(anim_ctrl, textvariable=self.anim_speed).pack(side=tk.LEFT)

        # Drop target setup (requires: pip install tkinterdnd2)
        self._dnd_enabled = False
        try:
            self.root.drop_target_register('DND_Files')
            self.root.dnd_bind('<<Drop>>', self._on_drop)
            self._dnd_enabled = True
        except Exception:
            pass  # tkinterdnd2 not available — use file picker instead

    # ----- File operations -----
    def _new_file(self):
        self.jvg = JVGFile()
        self._refresh_block_list()
        self.current_block_idx = -1
        self.current_frame_idx = 0
        self._refresh_view()
        self.root.title("JVG 图集编辑器 — [新建]")

    def _open_dialog(self):
        path = filedialog.askopenfilename(
            title="选择 JVG 文件",
            filetypes=[("JVG 文件", "*.jvg *.JVG"), ("所有文件", "*.*")])
        if path:
            self._open_file(path)

    def _open_file(self, path: str):
        try:
            self.jvg = load_jvg(path)
            self._refresh_block_list()
            if self.jvg.blocks:
                self.block_list.selection_set(0)
                self.current_block_idx = 0
                self.current_frame_idx = 0
            self._refresh_view()
            self.root.title(f"JVG 图集编辑器 — {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _save(self):
        if not self.jvg:
            return
        if self.jvg.filepath:
            self._do_save(self.jvg.filepath)
        else:
            self._save_as()

    def _save_as(self):
        if not self.jvg:
            return
        path = filedialog.asksaveasfilename(
            title="保存 JVG 文件",
            defaultextension=".jvg",
            filetypes=[("JVG 文件", "*.jvg"), ("所有文件", "*.*")])
        if path:
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            save_jvg(self.jvg, path)
            self.jvg.filepath = path
            self.root.title(f"JVG 图集编辑器 — {os.path.basename(path)}")
            messagebox.showinfo("保存成功", f"已保存 {len(self.jvg.blocks)} 个分组, "
                               f"{self.jvg.total_frames} 帧到:\n{path}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    # ----- Block management -----
    def _refresh_block_list(self):
        self.block_list.delete(0, tk.END)
        if not self.jvg:
            return
        for i, block in enumerate(self.jvg.blocks):
            self.block_list.insert(tk.END, f"[{i}] {block.name} ({block.frame_count}帧)")

    def _on_block_select(self, event=None):
        sel = self.block_list.curselection()
        if sel:
            self.current_block_idx = sel[0]
            self.current_frame_idx = 0
            self._kill_animation()
            self._refresh_view()

    def _add_block(self):
        if not self.jvg:
            self.jvg = JVGFile()
        name = simpledialog.askstring("新增分组", "分组名称:", parent=self.root)
        if name is None:
            return
        block = JVMBlock()
        block.name = name or f"block_{len(self.jvg.blocks):02d}"
        self.jvg.blocks.append(block)
        self._refresh_block_list()
        idx = len(self.jvg.blocks) - 1
        self.block_list.selection_clear(0, tk.END)
        self.block_list.selection_set(idx)
        self.current_block_idx = idx
        self._refresh_view()

    def _del_block(self):
        if not self.jvg or self.current_block_idx < 0:
            return
        if not messagebox.askyesno("确认删除",
            f"删除分组 [{self.current_block_idx}] 及其全部帧?"):
            return
        del self.jvg.blocks[self.current_block_idx]
        self._refresh_block_list()
        self.current_block_idx = min(self.current_block_idx,
                                     len(self.jvg.blocks) - 1)
        self._refresh_view()

    # ----- Frame management -----
    def _add_images(self):
        if not self.jvg or self.current_block_idx < 0:
            messagebox.showinfo("提示", "请先选择或创建一个分组")
            return
        paths = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[("图片文件", "*.png *.bmp *.jpg *.jpeg *.gif *.webp"),
                       ("所有文件", "*.*")])
        if not paths:
            return
        # Sort by filename
        paths = sorted(paths, key=lambda p: Path(p).name.lower())
        block = self.jvg.blocks[self.current_block_idx]
        added = 0
        for p in paths:
            frame = import_image_to_frame(p)
            if frame:
                block.frames.append(frame)
                added += 1
        self._refresh_block_list()
        self._refresh_view()
        self.info_label.config(text=f"添加了 {added} 帧")

    def _del_frame(self):
        if (not self.jvg or self.current_block_idx < 0 or
            self.current_block_idx >= len(self.jvg.blocks)):
            return
        block = self.jvg.blocks[self.current_block_idx]
        if self.current_frame_idx >= block.frame_count:
            return
        del block.frames[self.current_frame_idx]
        self.current_frame_idx = min(self.current_frame_idx,
                                     block.frame_count - 1)
        self._refresh_block_list()
        self._kill_animation()
        self._refresh_view()

    def _on_drop(self, event):
        """Handle drag-and-drop file import"""
        if not self.jvg or self.current_block_idx < 0:
            return
        files = self.root.tk.splitlist(event.data) if hasattr(event, 'data') else []
        # Clean up paths (tkinterdnd2 may wrap in {})
        clean_files = []
        for f in files:
            f = f.strip('{}').strip()
            if os.path.isfile(f):
                clean_files.append(f)
        if not clean_files:
            return
        clean_files.sort(key=lambda p: Path(p).name.lower())
        block = self.jvg.blocks[self.current_block_idx]
        added = 0
        for p in clean_files:
            ext = Path(p).suffix.lower()
            if ext in ('.png', '.bmp', '.jpg', '.jpeg', '.gif', '.webp'):
                frame = import_image_to_frame(p)
                if frame:
                    block.frames.append(frame)
                    added += 1
        if added:
            self._refresh_block_list()
            self._refresh_view()
            self.info_label.config(text=f"拖入 {added} 帧")

    # ----- View modes -----
    def _set_view(self, mode: str):
        self.view_mode = mode
        self._kill_animation()
        self._refresh_view()

    def _refresh_view(self):
        self.canvas.delete("all")
        self._photo_cache.clear()

        if not self.jvg or self.current_block_idx < 0:
            return
        if (self.current_block_idx >= len(self.jvg.blocks)):
            return
        block = self.jvg.blocks[self.current_block_idx]
        frames = block.frames
        if not frames:
            self.canvas.create_text(200, 100, text="(空分组 — 请添加图片)", fill="#888",
                                    font=("", 14))
            return

        palette_rgb = block.palette.to_rgb888()

        if self.view_mode == "tile":
            self._render_tile(frames, palette_rgb)
        elif self.view_mode == "single":
            self._render_single(frames, palette_rgb)
        elif self.view_mode == "anim":
            self._start_animation(frames, palette_rgb)

    def _frame_to_tk(self, frame: JVGFrame, palette_rgb: bytes,
                      scale: float = 1.0) -> tk.PhotoImage:
        """Convert a JVG frame to tkinter PhotoImage"""
        w, h = frame.width, frame.height
        if w <= 0 or h <= 0:
            return None

        # Build RGBA data
        from PIL import Image as PILImage
        rgba = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                pos = y * w + x
                off = pos * 4
                a = frame.alpha[pos] if pos < len(frame.alpha) else 0
                if a == 0:
                    rgba[off:off+4] = b'\x00\x00\x00\x00'
                else:
                    idx = frame.pixels[pos] if pos < len(frame.pixels) else 0
                    rgba[off]   = palette_rgb[idx * 3]
                    rgba[off+1] = palette_rgb[idx * 3 + 1]
                    rgba[off+2] = palette_rgb[idx * 3 + 2]
                    rgba[off+3] = 255

        pil_img = PILImage.frombytes('RGBA', (w, h), bytes(rgba))
        if scale != 1.0:
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            pil_img = pil_img.resize((nw, nh), PILImage.NEAREST)
        return ImageTk.PhotoImage(pil_img)

    def _render_tile(self, frames, palette_rgb):
        """平铺浏览: 所有帧按网格排列"""
        self.info_label.config(text=f"平铺浏览 — {len(frames)} 帧")
        x, y, row_h = 10, 10, 0
        max_w = 0

        # Find max width for wrapping
        cw = self.canvas.winfo_width()
        cols = max(1, (cw - 20) // 200)

        col = 0
        for fi, frame in enumerate(frames):
            if frame.width <= 0 or frame.height <= 0:
                continue
            img = self._frame_to_tk(frame, palette_rgb)
            if not img:
                continue
            self._photo_cache[fi] = img
            self.canvas.create_image(x, y, anchor=tk.NW, image=img)
            self.canvas.create_text(x + 2, y + 2, text=str(fi), fill="#0f0",
                                    font=("", 8), anchor=tk.NW)

            x += max(frame.width, 50) + 10
            row_h = max(row_h, frame.height)
            col += 1
            if col >= cols:
                x, col = 10, 0
                y += row_h + 30
                row_h = 0

        y += row_h + 20
        self.canvas.configure(scrollregion=(0, 0, max(cw, 600), y))

    def _render_single(self, frames, palette_rgb):
        """逐帧浏览: 显示当前帧"""
        if self.current_frame_idx >= len(frames):
            self.current_frame_idx = 0
        frame = frames[self.current_frame_idx]
        self.info_label.config(
            text=f"逐帧浏览 — {self.current_frame_idx + 1}/{len(frames)} "
                 f"({frame.width}x{frame.height})")

        img = self._frame_to_tk(frame, palette_rgb)
        if img:
            self._photo_cache[0] = img
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            self.canvas.create_image(cw//2, ch//2, anchor=tk.CENTER, image=img)
            self.canvas.configure(scrollregion=(0, 0, cw, ch))

        # Navigation buttons
        self.canvas.create_text(40, 30, text="◀ 上一帧", fill="#4af",
                                font=("", 11), tags=("nav_prev",))
        self.canvas.create_text(
            self.canvas.winfo_width() - 80, 30, text="下一帧 ▶", fill="#4af",
            font=("", 11), tags=("nav_next",))
        self.canvas.tag_bind("nav_prev", "<Button-1>",
                             lambda e: self._nav_frame(-1))
        self.canvas.tag_bind("nav_next", "<Button-1>",
                             lambda e: self._nav_frame(1))

    def _nav_frame(self, delta: int):
        if not self.jvg or self.current_block_idx < 0:
            return
        block = self.jvg.blocks[self.current_block_idx]
        self.current_frame_idx = (self.current_frame_idx + delta) % max(1, block.frame_count)
        self._refresh_view()

    def _start_animation(self, frames, palette_rgb):
        """动画预览: 循环播放所有帧"""
        self.info_label.config(text=f"动画预览 — {len(frames)} 帧")
        self._anim_frames = [(f, palette_rgb) for f in frames]
        self._anim_index = 0
        self._anim_next()

    def _anim_next(self):
        if self.view_mode != "anim":
            return
        if not self._anim_frames:
            return
        frame, palette_rgb = self._anim_frames[self._anim_index]
        self._anim_index = (self._anim_index + 1) % len(self._anim_frames)

        img = self._frame_to_tk(frame, palette_rgb)
        if img:
            self._photo_cache['_anim'] = img
            self.canvas.delete("all")
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            self.canvas.create_image(cw//2, ch//2, anchor=tk.CENTER, image=img)
            self.canvas.configure(scrollregion=(0, 0, cw, ch))
            self.canvas.create_text(cw//2, ch - 20,
                                    text=f"{self._anim_index}/{len(self._anim_frames)}",
                                    fill="#888", font=("", 10))

        delay = max(30, self.anim_speed.get())
        self._anim_job = self.root.after(delay, self._anim_next)

    def _kill_animation(self):
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        self._anim_frames = []


# ============================================================================
# 入口
# ============================================================================

def main():
    root = tk.Tk()
    root.title("JVG 图集编辑器")

    filepath = sys.argv[1] if len(sys.argv) > 1 else None
    app = JVGEditor(root, filepath)
    root.mainloop()


if __name__ == "__main__":
    main()
