#!/usr/bin/env python3
"""
GXP 图像编辑器 — 浏览/编辑/导出三国群侠传 .gxp 格式全屏背景图
==============================================================
格式依据: sub_450264 (GXP加载), sub_452B14 (LZSS解压)
GXP = 单张 RGB565 直接色图像, LZSS 压缩, 48 字节 "JGXP" 头

与 JVG 编辑器的关键区别:
  - 单张图 (无帧/块结构)   → 无需分组列表和帧管理
  - RGB565 直接色 (无调色板) → 无需调色板系统
  - LZSS 压缩 (非 RLE)      → 独立的压缩引擎
  - 全屏背景 (640×480)      → 典型的菜单/结局画面尺寸

用法: python gxp_editor.py [file.gxp]
"""

from __future__ import annotations
import os, sys, struct, zlib, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional, Tuple

HAS_PIL = False
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass

# ── GXP 格式常量 ──────────────────────────────────────────
GXP_MAGIC = b"JGXP"
GXP_HEADER_SIZE = 48

# LZSS 参数 (sub_452B14)
RING_SIZE = 4096
RING_INIT = RING_SIZE - 18       # 4078
MIN_MATCH = 3                     # 最小匹配 (sub_452B14: for v17<=v19, 实际=(code)+3)
MAX_MATCH = 18                    # 最大匹配 (4-bit code 15 + 3 = 18)
RING_INIT_VALUE = 0x20            # 环形缓冲区初始值 (空格)


# ═══════════════════════════════════════════════════════════
# LZSS 解压 (sub_452B14 逆向)
# ═══════════════════════════════════════════════════════════

def lzss_decompress(data: bytes, target_size: int) -> bytes:
    """LZSS 解压 — 4096 字节环形缓冲区, LSB-first 标志位"""
    ring = bytearray([RING_INIT_VALUE] * RING_SIZE)
    ring_pos = RING_INIT
    pos, out = 0, bytearray()

    while pos < len(data) and len(out) < target_size:
        flag = data[pos]; pos += 1
        for bit in range(8):
            if pos >= len(data) or len(out) >= target_size:
                break
            if flag & (1 << bit):
                b = data[pos]; pos += 1
                out.append(b)
                ring[ring_pos % RING_SIZE] = b
                ring_pos += 1
            else:
                if pos + 2 > len(data): break
                b1, b2 = data[pos], data[pos + 1]; pos += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3  # sub_452B14: for v17<=v19, 实际=(code)+3
                for k in range(length):
                    b = ring[(offset + k) % RING_SIZE]
                    out.append(b)
                    ring[ring_pos % RING_SIZE] = b
                    ring_pos += 1
    return bytes(out[:target_size])


# ═══════════════════════════════════════════════════════════
# LZSS 压缩 (编辑器用 — 与游戏解压器兼容)
# ═══════════════════════════════════════════════════════════

def _hash_2b(a: int, b: int) -> int:
    return ((a << 8) | b) & 0xFFF

def lzss_compress(data: bytes) -> bytes:
    """LZSS 压缩 — 与 sub_452B14 解压器完全兼容

    使用哈希链在 4096 字节窗口内搜索匹配, 输出游戏可读取的压缩流。
    将条目以 8 个为一组缓冲, 每组先写出标志字节, 再写出条目数据,
    确保与解压器的标志字节在先的预期一致。
    """
    n = len(data)
    if n == 0: return b""

    # 哈希表: 每个 2 字节前缀 → 最近出现位置
    hash_heads = [-1] * 4096
    hash_next = [-1] * n      # 冲突链

    # 构建哈希链 (从后向前, 使最近匹配优先)
    for i in range(n - 1, -1, -1):
        if i + 1 < n:
            h = _hash_2b(data[i], data[i + 1])
            hash_next[i] = hash_heads[h]
            hash_heads[h] = i

    buf = bytearray()
    # 条目缓冲: 每个条目为 (is_literal, data_bytes)
    #   is_literal=True  → data_bytes 是单字节
    #   is_literal=False → data_bytes 是引用对的 2 字节
    entries: list[tuple[bool, bytes]] = []

    def flush_group():
        """将缓冲的条目以 标志+条目 的格式写出"""
        if not entries:
            return
        flag = 0
        for i, (is_lit, _) in enumerate(entries):
            if is_lit:
                flag |= (1 << i)
        buf.append(flag)
        for _, data_bytes in entries:
            buf.extend(data_bytes)
        entries.clear()

    pos = 0
    while pos < n:
        best_len, best_off = 0, 0
        remaining = n - pos

        # 在哈希链中搜索最长匹配
        if remaining >= 2:
            h = _hash_2b(data[pos], data[pos + 1])
            chain = hash_heads[h]
            steps = 0
            while chain >= 0 and steps < 64:  # 限制搜索深度
                if pos - chain > RING_SIZE:
                    break
                if chain < pos:
                    ml = 0
                    while ml < min(remaining, MAX_MATCH) and data[chain + ml] == data[pos + ml]:
                        ml += 1
                    if ml > best_len:
                        best_len, best_off = ml, pos - chain
                        if ml == MAX_MATCH:
                            break
                chain = hash_next[chain]
                steps += 1

        if best_len >= MIN_MATCH:
            # 引用条目
            ring_pos_val = (RING_INIT + pos) % RING_SIZE
            actual_offset = (ring_pos_val - best_off) % RING_SIZE
            b1 = actual_offset & 0xFF
            b2 = ((actual_offset >> 4) & 0xF0) | ((best_len - 3) & 0x0F)
            entries.append((False, bytes([b1, b2])))
            pos += best_len
        else:
            # 字面量条目
            entries.append((True, bytes([data[pos]])))
            pos += 1

        # 满 8 条则刷新一组
        if len(entries) >= 8:
            flush_group()

    # 刷新剩余不足 8 条的组
    flush_group()

    return bytes(buf)


# ═══════════════════════════════════════════════════════════
# RGB565 ↔ RGBA 转换
# ═══════════════════════════════════════════════════════════

# 预计算 LUT
_RGB565_LUT = bytearray(65536 * 3)
for _v in range(65536):
    r5, g6, b5 = (_v >> 11) & 0x1F, (_v >> 5) & 0x3F, _v & 0x1F
    _RGB565_LUT[_v * 3] = (r5 << 3) | (r5 >> 2)
    _RGB565_LUT[_v * 3 + 1] = (g6 << 2) | (g6 >> 4)
    _RGB565_LUT[_v * 3 + 2] = (b5 << 3) | (b5 >> 2)


def rgb565_bytes_to_rgba(raw: bytes, w: int, h: int) -> bytearray:
    """RGB565 原始字节 → RGBA bytearray (使用 LUT 加速)"""
    total = w * h
    rgba = bytearray(total * 4)
    for i in range(min(total, len(raw) // 2)):
        lo, hi = raw[i * 2], raw[i * 2 + 1]
        val = lo | (hi << 8)
        off3 = val * 3
        off4 = i * 4
        rgba[off4] = _RGB565_LUT[off3]
        rgba[off4 + 1] = _RGB565_LUT[off3 + 1]
        rgba[off4 + 2] = _RGB565_LUT[off3 + 2]
        rgba[off4 + 3] = 255
    return rgba


def rgba_to_rgb565_bytes(rgba: bytes, w: int, h: int) -> bytes:
    """RGBA → RGB565 原始字节"""
    raw = bytearray(w * h * 2)
    for i in range(w * h):
        off4 = i * 4
        r, g, b = rgba[off4], rgba[off4 + 1], rgba[off4 + 2]
        r5 = (r >> 3) & 0x1F
        g6 = (g >> 2) & 0x3F
        b5 = (b >> 3) & 0x1F
        val = (r5 << 11) | (g6 << 5) | b5
        raw[i * 2] = val & 0xFF
        raw[i * 2 + 1] = (val >> 8) & 0xFF
    return bytes(raw)


# ═══════════════════════════════════════════════════════════
# GXP 文件 I/O
# ═══════════════════════════════════════════════════════════

class GXPImage:
    """GXP 图像数据模型"""
    def __init__(self):
        self.width: int = 0
        self.height: int = 0
        self.bpp: int = 16
        self.rgba: bytearray = bytearray()
        self.filepath: Optional[str] = None

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def size_str(self) -> str:
        return f"{self.width}×{self.height}"


def load_gxp(filepath: str) -> GXPImage:
    """加载 GXP 文件 (sub_450264 逆向)"""
    data = Path(filepath).read_bytes()
    if len(data) < GXP_HEADER_SIZE + 4:
        raise ValueError("文件太小, 不足 48 字节头 + 4 字节数据区")

    # 解析 48 字节头
    magic = data[0:4]
    if magic != GXP_MAGIC:
        raise ValueError(f"无效魔数: {magic!r} (期望 {GXP_MAGIC!r})")

    width_raw = struct.unpack_from("<i", data, 4)[0]
    height_raw = struct.unpack_from("<i", data, 8)[0]
    compressed_size = struct.unpack_from("<I", data, 12)[0]
    bpp = struct.unpack_from("<I", data, 16)[0]

    # 解码宽高: ~value → actual
    width = ~width_raw
    height = ~height_raw

    # 数据区: 4 字节解压大小 + LZSS 流
    uncompressed_size = struct.unpack_from("<I", data, GXP_HEADER_SIZE)[0]
    lzss_start = GXP_HEADER_SIZE + 4
    lzss_data = data[lzss_start:lzss_start + compressed_size - 4]

    # LZSS 解压
    raw_pixels = lzss_decompress(lzss_data, uncompressed_size)

    # RGB565 → RGBA
    img = GXPImage()
    img.width = width
    img.height = height
    img.bpp = bpp
    img.filepath = filepath
    img.rgba = rgb565_bytes_to_rgba(raw_pixels, width, height)
    return img


def save_gxp(img: GXPImage, filepath: str):
    """保存为 GXP 格式"""
    # RGBA → RGB565
    raw_rgb565 = rgba_to_rgb565_bytes(bytes(img.rgba), img.width, img.height)

    # LZSS 压缩
    compressed = lzss_compress(raw_rgb565)
    uncompressed_size = len(raw_rgb565)
    compressed_size = len(compressed) + 4  # +4 for uncompressed size header

    # 构建文件
    buf = bytearray()
    buf += GXP_MAGIC
    buf += struct.pack("<i", ~img.width)     # 宽度取反
    buf += struct.pack("<i", ~img.height)    # 高度取反
    buf += struct.pack("<I", compressed_size)
    buf += struct.pack("<I", img.bpp)
    buf += bytes(28)                          # 保留 (填充零)
    buf += struct.pack("<I", uncompressed_size)
    buf += compressed

    Path(filepath).write_bytes(bytes(buf))


def import_image(filepath: str, target_w: int = 0, target_h: int = 0) -> GXPImage:
    """从 PNG/BMP/JPG 导入, 转为 GXP 兼容格式"""
    pil = Image.open(filepath).convert("RGBA")

    # 尺寸处理
    if target_w > 0 and target_h > 0:
        pil = pil.resize((target_w, target_h), Image.LANCZOS)
    elif target_w > 0 or target_h > 0:
        # 保持宽高比的单维度调整
        ow, oh = pil.size
        if target_w > 0:
            ratio = target_w / ow
            pil = pil.resize((target_w, int(oh * ratio)), Image.LANCZOS)
        else:
            ratio = target_h / oh
            pil = pil.resize((int(ow * ratio), target_h), Image.LANCZOS)

    w, h = pil.size
    rgba = pil.tobytes()

    img = GXPImage()
    img.width = w
    img.height = h
    img.rgba = bytearray(rgba)
    return img


# ═══════════════════════════════════════════════════════════
# PNG 导出 (纯标准库, 不依赖 PIL)
# ═══════════════════════════════════════════════════════════

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def export_png(img: GXPImage, filepath: str):
    """导出 RGBA PNG"""
    w, h = img.width, img.height
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))

    stride = w * 4
    raw = bytearray(h * (stride + 1))
    mv = memoryview(img.rgba)
    for row in range(h):
        out = row * (stride + 1)
        raw[out] = 0  # 无过滤
        raw[out + 1:out + 1 + stride] = mv[row * stride:(row + 1) * stride]

    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    Path(filepath).write_bytes(png)


# ═══════════════════════════════════════════════════════════
# GUI 编辑器
# ═══════════════════════════════════════════════════════════

class GXPEditor:
    def __init__(self, root: tk.Tk, filepath: Optional[str] = None):
        self.root = root
        self.root.title("GXP 图像编辑器")
        self.root.geometry("1100x750")

        self.img: Optional[GXPImage] = None
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._pil_img: Optional[Image.Image] = None
        self._zoom = tk.DoubleVar(value=1.0)
        self._pan_x, self._pan_y = 0, 0
        self._pan_start = None

        self._setup_menu()
        self._setup_ui()

        if filepath and os.path.exists(filepath):
            self._open(filepath)
        else:
            self._new_empty()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 延迟绑定鼠标事件 (canvas 创建后)
        self.root.after(100, self._bind_canvas_events)

    # ── Menu ──────────────────────────────────────────

    def _setup_menu(self):
        mb = tk.Menu(self.root)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="新建 Ctrl+N", command=self._new_empty)
        fm.add_command(label="打开 Ctrl+O", command=self._open_dlg)
        fm.add_command(label="保存 Ctrl+S", command=self._save)
        fm.add_command(label="另存为... Ctrl+Shift+S", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="导入 PNG... Ctrl+I", command=self._import_dlg)
        fm.add_command(label="导出 PNG... Ctrl+E", command=self._export_dlg)
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_close)
        mb.add_cascade(label="文件", menu=fm)

        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="原始大小 (100%)", command=lambda: self._set_zoom(1.0))
        vm.add_command(label="适合窗口", command=self._fit_to_window)
        vm.add_command(label="放大 (+)", command=lambda: self._zoom_step(0.25))
        vm.add_command(label="缩小 (−)", command=lambda: self._zoom_step(-0.25))
        mb.add_cascade(label="视图", menu=vm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="关于 GXP 格式", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.config(menu=mb)
        self.root.bind("<Control-n>", lambda e: self._new_empty())
        self.root.bind("<Control-o>", lambda e: self._open_dlg())
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-Shift-s>", lambda e: self._save_as())
        self.root.bind("<Control-i>", lambda e: self._import_dlg())
        self.root.bind("<Control-e>", lambda e: self._export_dlg())
        self.root.bind("<Control-0>", lambda e: self._set_zoom(1.0))

    # ── UI Layout ─────────────────────────────────────

    def _setup_ui(self):
        # Toolbar
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=4, pady=(4, 2))

        ttk.Button(tb, text="打开", command=self._open_dlg).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="保存", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        ttk.Button(tb, text="导入", command=self._import_dlg).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="导出 PNG", command=self._export_dlg).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Zoom
        ttk.Button(tb, text="−", width=2, command=lambda: self._zoom_step(-0.25)).pack(side=tk.LEFT, padx=1)
        self._zoom_label = ttk.Label(tb, text="100%", width=6)
        self._zoom_label.pack(side=tk.LEFT)
        ttk.Button(tb, text="+", width=2, command=lambda: self._zoom_step(0.25)).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="⊡", width=2, command=self._fit_to_window).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # 尺寸信息
        self._size_label = ttk.Label(tb, text="")
        self._size_label.pack(side=tk.RIGHT, padx=6)

        # Status / pixel info
        self._pixel_label = ttk.Label(tb, text="", foreground="#888")
        self._pixel_label.pack(side=tk.RIGHT, padx=8)

        # Canvas area
        cf = ttk.Frame(self.root)
        cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self._canvas = tk.Canvas(cf, bg="#1e1e1e", highlightthickness=0, cursor="crosshair")
        vsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self._canvas.yview)
        hsb = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        cf.grid_rowconfigure(0, weight=1)
        cf.grid_columnconfigure(0, weight=1)

        # 状态栏
        sf = ttk.Frame(self.root)
        sf.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._status = ttk.Label(sf, text="就绪 — 打开或新建 GXP 文件", foreground="#888")
        self._status.pack(side=tk.LEFT)
        ttk.Label(sf, text="Ctrl+滚轮=缩放  |  拖拽=平移  |  右键=取色", foreground="#555").pack(side=tk.RIGHT)

    def _bind_canvas_events(self):
        self._canvas.bind("<Configure>", lambda e: self._refresh_view())
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        # Pan
        self._canvas.bind("<ButtonPress-2>", self._pan_start_fn)
        self._canvas.bind("<B2-Motion>", self._pan_move_fn)
        self._canvas.bind("<ButtonRelease-2>", self._pan_end_fn)
        self._canvas.bind("<ButtonPress-1>", self._pan_start_fn)
        self._canvas.bind("<B1-Motion>", self._pan_move_fn)
        self._canvas.bind("<ButtonRelease-1>", self._pan_end_fn)
        # Pixel info on move
        self._canvas.bind("<Motion>", self._on_mouse_move)

    # ── File Operations ───────────────────────────────

    def _new_empty(self):
        self.img = GXPImage()
        self.img.width, self.img.height = 640, 480
        self.img.rgba = bytearray(640 * 480 * 4)
        self._pil_img = None
        self._tk_img = None
        self._pan_x, self._pan_y = 0, 0
        self._zoom.set(1.0)
        self._refresh_view()
        self._status.config(text="新建空白 640×480 — 请导入图片或保存")
        self.root.title("GXP 编辑器 — [新建]")

    def _open_dlg(self):
        p = filedialog.askopenfilename(title="打开 GXP", filetypes=[("GXP", "*.gxp *.GXP"), ("All", "*.*")])
        if p: self._open(p)

    def _open(self, p: str):
        try:
            self._status.config(text=f"加载中: {Path(p).name} ...")
            self.root.update()
            self.img = load_gxp(p)
            self._pil_img = None
            self._tk_img = None
            self._pan_x, self._pan_y = 0, 0
            self._fit_to_window()
            self._refresh_view()
            self._status.config(
                text=f"已加载: {Path(p).name}  |  {self.img.size_str}"
                f"  |  RGB{self.img.bpp}  |  {os.path.getsize(p)/1024:.1f} KB")
            self.root.title(f"GXP 编辑器 — {os.path.basename(p)}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e))
            self._status.config(text="打开失败")

    def _save(self):
        if not self.img: return
        if self.img.filepath:
            self._do_save(self.img.filepath)
        else:
            self._save_as()

    def _save_as(self):
        p = filedialog.asksaveasfilename(
            title="保存 GXP", defaultextension=".gxp",
            filetypes=[("GXP", "*.gxp")])
        if p: self._do_save(p)

    def _do_save(self, p: str):
        try:
            self._status.config(text="压缩中...")
            self.root.update()
            save_gxp(self.img, p)
            self.img.filepath = p
            size_kb = os.path.getsize(p) / 1024
            ratio = size_kb * 1024 / max(self.img.pixel_count * 2, 1) * 100
            self._status.config(
                text=f"已保存: {Path(p).name}  |  {self.img.size_str}  |  "
                f"{size_kb:.1f} KB  |  压缩率 {ratio:.1f}%")
            self.root.title(f"GXP 编辑器 — {os.path.basename(p)}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _import_dlg(self):
        """从 PNG/BMP/JPG 导入图像"""
        p = filedialog.askopenfilename(
            title="导入图片", filetypes=[("图片", "*.png *.bmp *.jpg *.jpeg"), ("All", "*.*")])
        if not p: return

        try:
            self._status.config(text="导入中...")
            self.root.update()
            new_img = import_image(p, self.img.width if self.img and self.img.width > 0 else 0,
                                   self.img.height if self.img and self.img.height > 0 else 0)
            self.img = new_img
            self._pil_img = None
            self._tk_img = None
            self._pan_x, self._pan_y = 0, 0
            self._fit_to_window()
            self._refresh_view()
            self._status.config(text=f"已导入: {Path(p).name} → {self.img.size_str}")
            self.root.title(f"GXP 编辑器 — [导入] {os.path.basename(p)}")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _export_dlg(self):
        if not self.img or self.img.width <= 0: return
        p = filedialog.asksaveasfilename(
            title="导出 PNG", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("BMP", "*.bmp")])
        if not p: return

        try:
            export_png(self.img, p)
            self._status.config(text=f"已导出: {Path(p).name} ({self.img.size_str})")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _on_close(self):
        self.root.destroy()

    # ── View ──────────────────────────────────────────

    def _refresh_view(self):
        self._canvas.delete("all")
        if not self.img or self.img.width <= 0:
            self._canvas.create_text(300, 200, text="(无图像)", fill="#666", font=("", 14))
            return

        w, h = self.img.width, self.img.height
        z = self._zoom.get()
        sw, sh = int(w * z), int(h * z)

        # 构建或复用 PIL 图像
        if self._pil_img is None:
            self._pil_img = Image.frombytes("RGBA", (w, h), bytes(self.img.rgba))

        # 缩放
        display_img = self._pil_img
        if z != 1.0:
            display_img = self._pil_img.resize((max(1, sw), max(1, sh)), Image.NEAREST)

        self._tk_img = ImageTk.PhotoImage(display_img)
        # 居中放置 (或跟随 pan)
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        x = max(0, (cw - sw) // 2) + self._pan_x
        y = max(0, (ch - sh) // 2) + self._pan_y

        self._canvas.create_image(x, y, anchor=tk.NW, image=self._tk_img, tags=("img",))
        self._canvas.configure(scrollregion=(0, 0, max(cw, sw + 40), max(ch, sh + 40)))

        self._zoom_label.config(text=f"{int(z * 100)}%")
        self._size_label.config(text=f"{self.img.size_str}  |  RGB{self.img.bpp}")

    def _set_zoom(self, z: float):
        self._zoom.set(max(0.25, min(5.0, z)))
        self._pil_img = None  # 强制重建
        self._tk_img = None
        self._refresh_view()

    def _zoom_step(self, delta: float):
        self._set_zoom(self._zoom.get() + delta)

    def _fit_to_window(self):
        if not self.img or self.img.width <= 0: return
        cw = self._canvas.winfo_width() - 40 or 800
        ch = self._canvas.winfo_height() - 40 or 600
        z = min(1.0, cw / self.img.width, ch / self.img.height)
        self._set_zoom(max(0.25, z))
        self._pan_x, self._pan_y = 0, 0

    # ── Pan & Zoom ────────────────────────────────────

    def _pan_start_fn(self, ev):
        self._pan_start = (ev.x, ev.y)

    def _pan_move_fn(self, ev):
        if self._pan_start is None: return
        dx = ev.x - self._pan_start[0]
        dy = ev.y - self._pan_start[1]
        self._pan_x += dx
        self._pan_y += dy
        self._pan_start = (ev.x, ev.y)
        self._refresh_view()

    def _pan_end_fn(self, ev):
        self._pan_start = None

    def _on_mousewheel(self, ev):
        if ev.state & 0x4:  # Ctrl+滚轮 → 缩放
            self._zoom_step(0.25 if ev.delta > 0 else -0.25)
        elif ev.state & 0x1:  # Shift+滚轮 → 水平滚动
            self._canvas.xview_scroll(-ev.delta // 120, "units")
        else:
            self._canvas.yview_scroll(-ev.delta // 120, "units")

    def _on_mouse_move(self, ev):
        """显示鼠标位置的像素信息"""
        if not self.img or self.img.width <= 0: return

        w, h = self.img.width, self.img.height
        z = self._zoom.get()
        sw, sh = int(w * z), int(h * z)

        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        ox = max(0, (cw - sw) // 2) + self._pan_x
        oy = max(0, (ch - sh) // 2) + self._pan_y

        px = int((ev.x - ox) / z)
        py = int((ev.y - oy) / z)

        if 0 <= px < w and 0 <= py < h:
            idx = (py * w + px) * 4
            if idx + 3 < len(self.img.rgba):
                r, g, b, a = self.img.rgba[idx:idx + 4]
                # 同时显示 RGB565 值
                r5, g6, b5 = (r >> 3) & 0x1F, (g >> 2) & 0x3F, (b >> 3) & 0x1F
                val565 = (r5 << 11) | (g6 << 5) | b5
                self._pixel_label.config(
                    text=f"({px}, {py})  RGB=({r},{g},{b})  #565=0x{val565:04X}")
            else:
                self._pixel_label.config(text="")
        else:
            self._pixel_label.config(text="")

    # ── About ──────────────────────────────────────────

    def _show_about(self):
        messagebox.showinfo(
            "关于 GXP 格式",
            "GXP (JGXP) — 三国群侠传 全屏背景图格式\n\n"
            "格式特征:\n"
            "  • 48 字节文件头, 魔数 \"JGXP\"\n"
            "  • 宽高以按位取反 (~) 编码存储\n"
            "  • LZSS 压缩 (4096 窗口, 最小匹配 2B)\n"
            "  • RGB565 直接色 (16-bit 真彩色)\n"
            "  • 单张图像, 无调色板, 无透明\n\n"
            "逆向来源: sub_450264 / sub_452B14\n"
            "用途: 菜单背景、结局画面、小游戏背景")


# ═══════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    GXPEditor(root, fp)
    root.mainloop()


if __name__ == "__main__":
    if not HAS_PIL:
        print("需要 Pillow: pip install Pillow")
        sys.exit(1)
    main()
