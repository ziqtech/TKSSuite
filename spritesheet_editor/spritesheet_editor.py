#!/usr/bin/env python3
"""
Spritesheet Editor - 精灵表编辑器
==================================
功能:
  1. 导入多张图片, 设置 columns/rows/padding, 拼成 Spritesheet
  2. 按 columns/rows/padding 拆分导入的 Spritesheet
  3. 拖拽调整序列帧顺序 / 整行上下排序 / 整列左右排序
  4. 选中多个帧后预览动画, 也可预览整个 Spritesheet
  5. 导出时选择 PNG 像素格式: RGBA8888 / RGB888 / RGB565 / RGBA4444 / RGBA5551

用法: python spritesheet_editor.py [spritesheet.png]
"""

from __future__ import annotations
import os, sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List, Optional, Set, Tuple

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    pass

# ── 像素格式定义 ──────────────────────────────────────────────
PIXEL_FORMATS: dict[str, str] = {
    "RGBA8888": "32-bit RGBA (8 bits/channel)",
    "RGB888":   "24-bit RGB, no alpha",
    "RGB565":   "16-bit RGB (5R 6G 5B)",
    "RGBA5551": "16-bit RGBA (5R 5G 5B 1A)",
    "RGBA4444": "16-bit RGBA (4 bits/channel)",
    "PNG-8 (256色)": "8-bit 索引调色板 (最多 256 色)",
}

# 纹理格式 → 可用的像素格式列表
TEXTURE_FORMATS: dict[str, List[str]] = {
    "PNG-32": ["RGBA8888", "RGB888", "RGB565", "RGBA5551", "RGBA4444"],
    "PNG-8":  ["PNG-8 (256色)"],
}

# 像素格式详细说明 (面板中展示)
PIXEL_FORMAT_DESC: dict[str, str] = {
    "RGBA8888": "32-bit RGBA，每通道 8 位。完整色彩 + Alpha，最高质量，文件较大。",
    "RGB888":   "24-bit RGB，无 Alpha。不支持透明像素。",
    "RGB565":   "16-bit RGB (5R 6G 5B)。色彩量化，文件更小，无 Alpha。",
    "RGBA5551": "16-bit RGBA (5R 5G 5B 1A)。1 位 Alpha，仅支持透明/不透明。",
    "RGBA4444": "16-bit RGBA，每通道 4 位。色彩 + Alpha 都量化，体积较小。",
    "PNG-8 (256色)": "8-bit 索引调色板，最多 256 色，文件最小，仅支持 1 位透明。",
}

# Alpha 处理模式
ALPHA_MODES: List[str] = ["无", "清除透明像素", "减少边界伪影", "预乘 Alpha"]

ALPHA_MODE_DESC: dict[str, str] = {
    "无":       "透明像素从精灵复制到精灵表而不做任何更改。如果将其他信息存储在透明像素的颜色值中，请选择此模式以确保不会损坏。",
    "清除透明像素": "透明像素的颜色值设置为 0 (透明黑色)。可以有更好的压缩率。",
    "减少边界伪影": "透明像素获得最邻近的实心像素的颜色值。如果在缩放/旋转后在精灵的边框处观察到黑色阴影，请选择此模式。",
    "预乘 Alpha":   "所有颜色值都与 Alpha 值相乘。某些框架需要这样才能更快地渲染纹理。",
}

HEADER_ROW_H = 28   # 列头高度
HEADER_COL_W = 36   # 行头宽度
DRAG_THRESHOLD = 5  # 拖拽阈值 (像素)
DEFAULT_FPS = 12


# ── 像素格式转换 ──────────────────────────────────────────────
def _quantize_rgb565(img: Image.Image) -> Image.Image:
    """量化为 RGB565 并保存为 RGB PNG"""
    img = img.convert("RGBA")
    w, h = img.size
    result = Image.new("RGB", (w, h))
    sp, dp = img.load(), result.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            if a < 128:
                r = g = b = 0
            dp[x, y] = ((r >> 3) << 3, (g >> 2) << 2, (b >> 3) << 3)
    return result


def _quantize_rgba5551(img: Image.Image) -> Image.Image:
    """量化为 RGBA5551"""
    img = img.convert("RGBA")
    w, h = img.size
    result = Image.new("RGBA", (w, h))
    sp, dp = img.load(), result.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            dp[x, y] = ((r >> 3) << 3, (g >> 3) << 3, (b >> 3) << 3, 255 if a >= 128 else 0)
    return result


def _quantize_rgba4444(img: Image.Image) -> Image.Image:
    """量化为 RGBA4444"""
    img = img.convert("RGBA")
    w, h = img.size
    result = Image.new("RGBA", (w, h))
    sp, dp = img.load(), result.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            dp[x, y] = ((r >> 4) << 4, (g >> 4) << 4, (b >> 4) << 4, (a >> 4) << 4)
    return result


def _quantize_png8(img: Image.Image) -> Image.Image:
    """量化为 PNG-8 索引调色板 (最多 256 色，保留 1 位透明)"""
    img = img.convert("RGBA")
    w, h = img.size
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    # 留出 index 255 作为透明索引
    try:
        q = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=0)
    except Exception:
        q = rgb.quantize(colors=255)
    q_data = list(q.getdata())
    a_data = list(alpha.getdata())
    new_data = [255 if a_data[i] < 128 else q_data[i] for i in range(w * h)]
    pal = list(q.getpalette() or [])
    while len(pal) < 768:
        pal.append(0)
    result = Image.new("P", (w, h))
    result.putpalette(pal)
    result.putdata(new_data)
    result.info["transparency"] = 255
    return result


def convert_pixel_format(img: Image.Image, fmt: str) -> Image.Image:
    """按指定格式转换图像像素"""
    if fmt == "RGBA8888":
        return img.convert("RGBA")
    elif fmt == "RGB888":
        return img.convert("RGB")
    elif fmt == "RGB565":
        return _quantize_rgb565(img)
    elif fmt == "RGBA5551":
        return _quantize_rgba5551(img)
    elif fmt == "RGBA4444":
        return _quantize_rgba4444(img)
    elif fmt == "PNG-8 (256色)":
        return _quantize_png8(img)
    return img


# ── Alpha 处理 ─────────────────────────────────────
def _alpha_clear_transparent(img: Image.Image) -> Image.Image:
    """将 alpha=0 的像素 RGB 清零"""
    img = img.convert("RGBA")
    w, h = img.size
    result = img.copy()
    px = result.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                px[x, y] = (0, 0, 0, 0)
    return result


def _alpha_premultiply(img: Image.Image) -> Image.Image:
    """对 RGB 预乘 alpha"""
    img = img.convert("RGBA")
    w, h = img.size
    result = img.copy()
    px = result.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 255:
                f = a / 255.0
                px[x, y] = (int(r * f), int(g * f), int(b * f), a)
    return result


def _alpha_reduce_border(img: Image.Image, iterations: int = 4) -> Image.Image:
    """透明像素从附近不透明像素扩散取色 (减少缩放边界黑阴影)"""
    img = img.convert("RGBA")
    w, h = img.size
    data = list(img.getdata())
    for _ in range(max(1, iterations)):
        new_data = list(data)
        changed = False
        for y in range(h):
            for x in range(w):
                idx = y * w + x
                r, g, b, a = data[idx]
                if a != 0:
                    continue
                rsum = gsum = bsum = 0
                n = 0
                for dy in (-1, 0, 1):
                    ny = y + dy
                    if ny < 0 or ny >= h:
                        continue
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx = x + dx
                        if nx < 0 or nx >= w:
                            continue
                        nr, ng, nb, na = data[ny * w + nx]
                        if na != 0:
                            rsum += nr
                            gsum += ng
                            bsum += nb
                            n += 1
                if n > 0:
                    new_data[idx] = (rsum // n, gsum // n, bsum // n, 0)
                    changed = True
        data = new_data
        if not changed:
            break
    result = Image.new("RGBA", (w, h))
    result.putdata(data)
    return result


def apply_alpha_mode(img: Image.Image, mode: str) -> Image.Image:
    """应用 Alpha 处理模式"""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    if mode == "无":
        return img
    if mode == "清除透明像素":
        return _alpha_clear_transparent(img)
    if mode == "减少边界伪影":
        return _alpha_reduce_border(img)
    if mode == "预乘 Alpha":
        return _alpha_premultiply(img)
    return img


# ── 数据模型 ──────────────────────────────────────────────────
class SpriteSheetModel:
    """精灵表数据模型"""

    def __init__(self):
        self.frames: List[Optional[Image.Image]] = []
        self.columns: int = 4
        self.rows: int = 4
        self.padding: int = 1
        self.cell_width: int = 64
        self.cell_height: int = 64

    @property
    def total_cells(self) -> int:
        return self.columns * self.rows

    @property
    def frame_count(self) -> int:
        return sum(1 for f in self.frames if f is not None)

    def normalize(self) -> None:
        """确保 frame 数量与网格匹配"""
        total = self.total_cells
        while len(self.frames) < total:
            self.frames.append(None)
        self.frames = self.frames[:total]

    def auto_detect_cell_size(self) -> None:
        """从已有帧中自动检测 cell 大小"""
        valid = [f for f in self.frames if f is not None]
        if valid:
            self.cell_width = max(f.width for f in valid)
            self.cell_height = max(f.height for f in valid)

    def build_spritesheet(self) -> Image.Image:
        """从帧列表生成合并的精灵表"""
        self.normalize()
        w = self.columns * (self.cell_width + self.padding) - self.padding
        h = self.rows * (self.cell_height + self.padding) - self.padding
        if w <= 0 or h <= 0:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        ss = Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
        for i, frame in enumerate(self.frames):
            if frame is None:
                continue
            r, c = divmod(i, self.columns)
            x = c * (self.cell_width + self.padding)
            y = r * (self.cell_height + self.padding)
            resized = frame.resize((self.cell_width, self.cell_height), Image.LANCZOS)
            ss.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
        return ss

    def split_spritesheet(self, img: Image.Image) -> None:
        """将精灵表按网格拆分为帧"""
        if self.columns <= 0 or self.rows <= 0:
            return
        total_w = self.columns * (self.cell_width + self.padding) - self.padding
        total_h = self.rows * (self.cell_height + self.padding) - self.padding
        self.frames = []
        for r in range(self.rows):
            for c in range(self.columns):
                x = c * (self.cell_width + self.padding)
                y = r * (self.cell_height + self.padding)
                if x + self.cell_width <= img.width and y + self.cell_height <= img.height:
                    frame = img.crop((x, y, x + self.cell_width, y + self.cell_height))
                    self.frames.append(frame.copy())
                else:
                    self.frames.append(None)

    def swap_frames(self, idx_a: int, idx_b: int) -> None:
        """交换两个帧"""
        self.normalize()
        n = len(self.frames)
        if 0 <= idx_a < n and 0 <= idx_b < n:
            self.frames[idx_a], self.frames[idx_b] = self.frames[idx_b], self.frames[idx_a]

    def swap_rows(self, r1: int, r2: int) -> None:
        """交换两行"""
        self.normalize()
        cols = self.columns
        if not (0 <= r1 < self.rows and 0 <= r2 < self.rows):
            return
        for c in range(cols):
            i1, i2 = r1 * cols + c, r2 * cols + c
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]

    def swap_cols(self, c1: int, c2: int) -> None:
        """交换两列"""
        self.normalize()
        cols, rows = self.columns, self.rows
        if not (0 <= c1 < cols and 0 <= c2 < cols):
            return
        for r in range(rows):
            i1, i2 = r * cols + c1, r * cols + c2
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]

    def get_frame(self, idx: int) -> Optional[Image.Image]:
        self.normalize()
        if 0 <= idx < len(self.frames):
            return self.frames[idx]
        return None


# ── 主画布 (Canvas) ───────────────────────────────────────────
class SpriteSheetCanvas(tk.Canvas):
    """精灵表画布: 显示网格、支持拖拽排序、多选"""

    def __init__(self, parent, model: SpriteSheetModel, editor, **kw):
        super().__init__(parent, bg="#3a3a3a", highlightthickness=0, **kw)
        self.model = model
        self.editor = editor  # SpriteSheetEditor 引用
        self._photos: dict[tuple, ImageTk.PhotoImage] = {}
        self.selection: Set[int] = set()  # 选中的帧索引集合
        self._drag_info: Optional[dict] = None
        self._header_drag: Optional[dict] = None
        self._last_click_idx: int = -1
        self._drawing_size: Tuple[int, int] = (0, 0)
        # 缩放 (仅影响画布显示, 不改变 model 实际 cell 尺寸)
        self._zoom: float = 1.0

        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Control-Button-1>", self._on_ctrl_click)
        self.bind("<Shift-Button-1>", self._on_shift_click)
        self.bind("<MouseWheel>", self._on_mousewheel)

    # ── 缩放 ───────────────────────────────────────
    def _eff_size(self) -> Tuple[int, int, int]:
        """按当前缩放计算画布上的 (cell_w, cell_h, padding)"""
        z = max(0.05, float(self._zoom))
        cw = max(1, int(round(self.model.cell_width * z)))
        ch = max(1, int(round(self.model.cell_height * z)))
        p = max(0, int(round(self.model.padding * z)))
        return cw, ch, p

    def set_zoom(self, z: float) -> None:
        z = max(0.5, min(5.0, float(z)))
        if abs(z - self._zoom) < 0.001:
            return
        self._zoom = z
        self.redraw()
        # 同步缩放指示标签 (若存在)
        try:
            self.editor._zoom_label.config(text=f"{int(z * 100)}%")
        except Exception:
            pass

    def zoom_step(self, delta: float) -> None:
        self.set_zoom(self._zoom + delta)

    def zoom_reset(self) -> None:
        self.set_zoom(1.0)

    # ── 坐标计算 ───────────────────────────────────
    def _cell_bbox(self, row: int, col: int) -> Tuple[int, int, int, int]:
        cw, ch, p = self._eff_size()
        x = HEADER_COL_W + col * (cw + p)
        y = HEADER_ROW_H + row * (ch + p)
        return x, y, x + cw, y + ch

    def _row_header_bbox(self, row: int) -> Tuple[int, int, int, int]:
        _, y, _, _ = self._cell_bbox(row, 0)
        cw, ch, p = self._eff_size()
        return 0, y, HEADER_COL_W, y + ch

    def _col_header_bbox(self, col: int) -> Tuple[int, int, int, int]:
        x, _, _, _ = self._cell_bbox(0, col)
        cw, ch, p = self._eff_size()
        return x, 0, x + cw, HEADER_ROW_H

    def _total_size(self) -> Tuple[int, int]:
        m = self.model
        cw, ch, p = self._eff_size()
        w = HEADER_COL_W + m.columns * (cw + p) - p
        h = HEADER_ROW_H + m.rows * (ch + p) - p
        return max(w, 100), max(h, 100)

    def _idx_at_pos(self, x: int, y: int) -> int:
        """返回鼠标位置对应的帧索引, 无匹配返回 -1"""
        cw, ch, p = self._eff_size()
        # canvasx/y 返回 float, 必须强转 int, 否则 selection 允许存 float 会引发 range/下标报错
        col = int((x - HEADER_COL_W) // (cw + p))
        row = int((y - HEADER_ROW_H) // (ch + p))
        # 检查是否在 cell 内部 (不在 padding 区域)
        cx = x - HEADER_COL_W - col * (cw + p)
        cy = y - HEADER_ROW_H - row * (ch + p)
        if 0 <= row < self.model.rows and 0 <= col < self.model.columns and cx < cw and cy < ch:
            return row * self.model.columns + col
        return -1

    def _header_at_pos(self, x: int, y: int) -> Optional[Tuple[str, int]]:
        """检测是否点击了 row/col header, 返回 ('row', r) 或 ('col', c) 或 None"""
        cw, ch, p = self._eff_size()
        # 行头区域
        if x < HEADER_COL_W and y >= HEADER_ROW_H:
            row = int((y - HEADER_ROW_H) // (ch + p))
            cy = y - HEADER_ROW_H - row * (ch + p)
            if 0 <= row < self.model.rows and cy < ch:
                return ("row", row)
        # 列头区域
        if y < HEADER_ROW_H and x >= HEADER_COL_W:
            col = int((x - HEADER_COL_W) // (cw + p))
            cx = x - HEADER_COL_W - col * (cw + p)
            if 0 <= col < self.model.columns and cx < cw:
                return ("col", col)
        return None

    # ── 绘制 ───────────────────────────────────────────────
    def redraw(self) -> None:
        self.delete("all")
        self._photos.clear()
        m = self.model
        m.normalize()
        tw, th = self._total_size()
        self._drawing_size = (tw, th)
        self.config(scrollregion=(0, 0, tw, th))

        p, cw, ch = m.padding, m.cell_width, m.cell_height
        cols, rows = m.columns, m.rows
        # 画布实际使用缩放后的尺寸 (cw/ch/p 为逻辑尺寸, eff_* 为画布像素)
        eff_cw, eff_ch, eff_p = self._eff_size()
        self.create_rectangle(0, 0, tw, th, fill="#3a3a3a", outline="", tags="bg")

        for i, frame in enumerate(m.frames):
            r, c = divmod(i, cols)
            x, y, x2, y2 = self._cell_bbox(r, c)

            # 单元格背景
            fill = "#4a4a4a" if i % 2 == 0 else "#444444"
            if i in self.selection:
                fill = "#5a6a8a"
            tags = f"cell_bg_{i}"
            self.create_rectangle(x, y, x2, y2, fill=fill, outline="#555555", tags=tags)

            if frame is not None:
                try:
                    photo = ImageTk.PhotoImage(
                        frame.resize((eff_cw, eff_ch), Image.NEAREST))
                    self._photos[(r, c)] = photo
                    self.create_image(x, y, image=photo, anchor="nw",
                                      tags=f"img_{i}")
                except Exception:
                    pass
            else:
                # 空帧标记
                self.create_line(x, y, x2, y2, fill="#555555", tags=f"empty_{i}")
                self.create_line(x2, y, x, y2, fill="#555555", tags=f"empty_{i}")

            # 序号文字
            self.create_text(x + 4, y + 2, text=str(i), anchor="nw",
                             fill="#cccccc", font=("", 7), tags=f"label_{i}")

        # 选中边框 (画在顶层)
        for idx in self.selection:
            r, c = divmod(idx, cols)
            x, y, x2, y2 = self._cell_bbox(r, c)
            self.create_rectangle(x, y, x2, y2, outline="#80c0ff", width=2, tags="sel_border")

        # 单选时高亮整行/整列
        if len(self.selection) == 1:
            sel_idx = next(iter(self.selection))
            sr, sc = divmod(sel_idx, cols)
            cw_e, ch_e, p_e = self._eff_size()
            tw = self._total_size()[0]
            th = self._total_size()[1]
            # 高亮行
            ry = HEADER_ROW_H + sr * (ch_e + p_e)
            self.create_rectangle(HEADER_COL_W, ry, tw, ry + ch_e,
                                  outline="#a0d0ff", width=1, dash=(2, 2), tags="row_hl")
            # 高亮列
            cx = HEADER_COL_W + sc * (cw_e + p_e)
            self.create_rectangle(cx, HEADER_ROW_H, cx + cw_e, th,
                                  outline="#a0d0ff", width=1, dash=(2, 2), tags="col_hl")
            # 行头高亮
            rhx, rhy, rhx2, rhy2 = self._row_header_bbox(sr)
            self.create_rectangle(rhx, rhy, rhx2, rhy2,
                                  fill="#607080", outline="#80c0ff", tags="row_hdr_hl")
            # 列头高亮
            chx, chy, chx2, chy2 = self._col_header_bbox(sc)
            self.create_rectangle(chx, chy, chx2, chy2,
                                  fill="#607080", outline="#80c0ff", tags="col_hdr_hl")

        # 行头
        for r in range(rows):
            x, y, x2, y2 = self._row_header_bbox(r)
            hdr_fill = "#505050" if self._header_drag and self._header_drag[0] == "row" \
                        and self._header_drag[1] == r else "#404040"
            self.create_rectangle(x, y, x2, y2, fill=hdr_fill, outline="#606060",
                                  tags=f"row_hdr_{r}")
            self.create_text(x + HEADER_COL_W // 2, y + (eff_ch) // 2,
                             text=f"R{r}", fill="#aaaaaa", font=("", 8),
                             tags=f"row_hdr_{r}")

        # 列头
        for c in range(cols):
            x, y, x2, y2 = self._col_header_bbox(c)
            hdr_fill = "#505050" if self._header_drag and self._header_drag[0] == "col" \
                        and self._header_drag[1] == c else "#404040"
            self.create_rectangle(x, y, x2, y2, fill=hdr_fill, outline="#606060",
                                  tags=f"col_hdr_{c}")
            self.create_text(x + eff_cw // 2, y + HEADER_ROW_H // 2,
                             text=f"C{c}", fill="#aaaaaa", font=("", 8),
                             tags=f"col_hdr_{c}")

        # 左上角装饰
        self.create_rectangle(0, 0, HEADER_COL_W, HEADER_ROW_H,
                              fill="#303030", outline="#606060", tags="corner")

    # ── 鼠标事件 ───────────────────────────────────────────
    def _row_at_y(self, y: float) -> int:
        """根据 y 坐标确定所在行 (返回 -1 表示不在任何行中)"""
        cw, ch, p = self._eff_size()
        ri = int((y - HEADER_ROW_H) // (ch + p))
        ry = y - HEADER_ROW_H - ri * (ch + p)
        if 0 <= ri < self.model.rows and 0 <= ry < ch:
            return ri
        return -1

    def _col_at_x(self, x: float) -> int:
        """根据 x 坐标确定所在列 (返回 -1 表示不在任何列中)"""
        cw, ch, p = self._eff_size()
        ci = int((x - HEADER_COL_W) // (cw + p))
        cx = x - HEADER_COL_W - ci * (cw + p)
        if 0 <= ci < self.model.columns and 0 <= cx < cw:
            return ci
        return -1

    def _on_press(self, event):
        # 若修饰键按下, 由专用 handler 处理 (避免 double-fire 破坏拖拽状态)
        if (event.state & 0x0004) or (event.state & 0x0001):
            return
        x, y = self.canvasx(event.x), self.canvasy(event.y)

        # 检测 header 点击
        hdr = self._header_at_pos(x, y)
        if hdr:
            self._header_drag = (hdr[0], hdr[1], x, y)
            self.redraw()
            return

        idx = self._idx_at_pos(x, y)
        if idx < 0:
            if self.selection:
                self.selection.clear()
                if hasattr(self.editor, "image_list"):
                    self.editor.image_list._selected_idx = -1
                self.redraw()
            if hasattr(self.editor, "_on_selection_changed"):
                self.editor._on_selection_changed()
            return

        # 普通点击 → 可能开始拖拽
        self._drag_info = {"from_idx": idx, "start_x": x, "start_y": y,
                           "moved": False}
        self._last_click_idx = idx
        if idx not in self.selection:
            self.selection = {idx}
        # 同步 image_list 主选中 (供 "上移/下移" 按钮依赖)
        if hasattr(self.editor, "image_list"):
            self.editor.image_list._selected_idx = idx
        self.redraw()
        if hasattr(self.editor, "_on_selection_changed"):
            self.editor._on_selection_changed()

    def _on_ctrl_click(self, event):
        """Ctrl+点击: 切换选中 (不会触发 _on_press)"""
        x, y = self.canvasx(event.x), self.canvasy(event.y)
        # 先清除可能残留的 drag 状态
        self._drag_info = None
        idx = self._idx_at_pos(x, y)
        if idx >= 0:
            if idx in self.selection:
                self.selection.discard(idx)
            else:
                self.selection.add(idx)
            self._last_click_idx = idx
            # 同步 image_list 主选中 (选中集中选择主帧)
            if hasattr(self.editor, "image_list"):
                if self.selection:
                    primary = idx if idx in self.selection else min(self.selection)
                    self.editor.image_list._selected_idx = primary
                else:
                    self.editor.image_list._selected_idx = -1
            self.redraw()
            if hasattr(self.editor, "_on_selection_changed"):
                self.editor._on_selection_changed()

    def _on_shift_click(self, event):
        """Shift+点击: 范围选中 (不会触发 _on_press)"""
        x, y = self.canvasx(event.x), self.canvasy(event.y)
        self._drag_info = None
        idx = self._idx_at_pos(x, y)
        if idx >= 0 and self._last_click_idx >= 0:
            lo, hi = min(self._last_click_idx, idx), max(self._last_click_idx, idx)
            self.selection = set(range(lo, hi + 1))
            # 同步 image_list 主选中 → 末帧
            if hasattr(self.editor, "image_list"):
                self.editor.image_list._selected_idx = idx
            self.redraw()
            if hasattr(self.editor, "_on_selection_changed"):
                self.editor._on_selection_changed()

    def _on_drag(self, event):
        x, y = self.canvasx(event.x), self.canvasy(event.y)

        # Header 拖拽
        if self._header_drag:
            dx = abs(x - self._header_drag[2])
            dy = abs(y - self._header_drag[3])
            if dx > DRAG_THRESHOLD or dy > DRAG_THRESHOLD:
                self._show_header_drag_indicator(self._header_drag[0],
                                                 self._header_drag[1], x, y)
            return

        # 帧拖拽
        if not self._drag_info:
            return
        dx = abs(x - self._drag_info["start_x"])
        dy = abs(y - self._drag_info["start_y"])
        if not self._drag_info["moved"] and (dx > DRAG_THRESHOLD or dy > DRAG_THRESHOLD):
            self._drag_info["moved"] = True
            self._drag_info["from_idx"] = self._drag_info.get("from_idx",
                                                              self._last_click_idx)
        if self._drag_info["moved"]:
            self._show_frame_drag_indicator(x, y)

    def _on_release(self, event):
        x, y = self.canvasx(event.x), self.canvasy(event.y)

        # Header 释放 (用 _row_at_y / _col_at_x 检测目标, 允许光标在画布内)
        if self._header_drag:
            hdr_type, hdr_idx = self._header_drag[0], self._header_drag[1]
            self._header_drag = None
            if hdr_type == "row":
                target = self._row_at_y(y)
            else:
                target = self._col_at_x(x)
            if target >= 0 and target != hdr_idx:
                cols = self.model.columns
                old_sel = set(self.selection)
                new_sel: Set[int] = set()
                for si in old_sel:
                    sr, sc = divmod(si, cols)
                    if hdr_type == "row":
                        if sr == hdr_idx:
                            sr = target
                        elif sr == target:
                            sr = hdr_idx
                    else:
                        if sc == hdr_idx:
                            sc = target
                        elif sc == target:
                            sc = hdr_idx
                    new_sel.add(sr * cols + sc)
                if hdr_type == "row":
                    self.model.swap_rows(hdr_idx, target)
                else:
                    self.model.swap_cols(hdr_idx, target)
                self.selection = new_sel
                self.editor._on_model_changed()
            else:
                self.redraw()
            return

        # 帧释放
        if self._drag_info:
            if self._drag_info.get("moved"):
                to_idx = self._idx_at_pos(x, y)
                from_idx = self._drag_info["from_idx"]
                if to_idx >= 0 and to_idx != from_idx:
                    self.model.swap_frames(from_idx, to_idx)
                    self.selection = {to_idx}
                    # 同步列表选中
                    if hasattr(self.editor, "image_list"):
                        self.editor.image_list._selected_idx = to_idx
                    self._drag_info = None
                    self.editor._on_model_changed()
                    return
            self._drag_info = None
            self.redraw()

    def _show_frame_drag_indicator(self, cx: int, cy: int) -> None:
        """绘制帧拖拽目标指示器 (仅更新指示器, 不重建全部)"""
        self.delete("drag_target")
        to_idx = self._idx_at_pos(cx, cy)
        if to_idx >= 0:
            r, c = divmod(to_idx, self.model.columns)
            x, y, x2, y2 = self._cell_bbox(r, c)
            self.create_rectangle(x, y, x2, y2, outline="#ffcc00", width=3,
                                  dash=(4, 2), tags="drag_target")

    def _show_header_drag_indicator(self, hdr_type: str, hdr_idx: int,
                                     cx: int, cy: int) -> None:
        """绘制行/列拖拽目标指示器 (仅更新指示器, 不重建全部)"""
        self.delete("hdr_target")
        if hdr_type == "row":
            target = self._row_at_y(cy)
            if target >= 0 and target != hdr_idx:
                _, y, _, y2 = self._row_header_bbox(target)
                tw = self._total_size()[0]
                self.create_rectangle(0, y, tw, y2, outline="#ffcc00", width=2,
                                      dash=(4, 2), tags="hdr_target")
        else:
            target = self._col_at_x(cx)
            if target >= 0 and target != hdr_idx:
                x, _, x2, _ = self._col_header_bbox(target)
                th = self._total_size()[1]
                self.create_rectangle(x, 0, x2, th, outline="#ffcc00", width=2,
                                      dash=(4, 2), tags="hdr_target")

    def _on_mousewheel(self, event):
        # Ctrl+滾轮 = 缩放
        if event.state & 0x4:
            delta = 0.25 if event.delta > 0 else -0.25
            self.zoom_step(delta)
            return "break"
        # Shift+滾轮 = 水平滚动, 其他 = 垂直滚动
        if event.state & 0x1:
            self.xview_scroll(int(-1 * (event.delta / 120)), "units")
        else:
            self.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── 公开方法 ────────────────────────────────────────────
    def update_model(self) -> None:
        self.selection.clear()
        self.redraw()

    def select_all(self) -> None:
        self.model.normalize()
        self.selection = set(range(len(self.model.frames)))
        self.redraw()

    def select_none(self) -> None:
        self.selection.clear()
        self.redraw()

    def delete_selected(self) -> None:
        """删除选中的帧 (替换为空)"""
        for idx in list(self.selection):
            if 0 <= idx < len(self.model.frames):
                self.model.frames[idx] = None
        self.selection.clear()
        self.editor._on_model_changed()
        self.redraw()

    def move_selected_left(self) -> None:
        """选中帧左移一个位置"""
        moved = []
        for idx in sorted(self.selection):
            if idx > 0 and (idx - 1) not in self.selection:
                self.model.swap_frames(idx, idx - 1)
                moved.append(idx - 1)
            else:
                moved.append(idx)
        self.selection = set(moved)
        self.editor._on_model_changed()
        self.redraw()

    def move_selected_right(self) -> None:
        """选中帧右移一个位置"""
        moved = []
        for idx in sorted(self.selection, reverse=True):
            if idx < len(self.model.frames) - 1 and (idx + 1) not in self.selection:
                self.model.swap_frames(idx, idx + 1)
                moved.append(idx + 1)
            else:
                moved.append(idx)
        self.selection = set(moved)
        self.editor._on_model_changed()
        self.redraw()

    def move_selected_up(self) -> None:
        """选中帧上移一个位置 (delta = -columns)"""
        cols = max(1, int(self.model.columns))
        moved = []
        # 正序遍历: 先移动靠上的, 避免覆盖
        for idx in sorted(self.selection):
            target = idx - cols
            if target >= 0 and target not in self.selection:
                self.model.swap_frames(idx, target)
                moved.append(target)
            else:
                moved.append(idx)
        self.selection = set(moved)
        self.editor._on_model_changed()
        self.redraw()

    def move_selected_down(self) -> None:
        """选中帧下移一个位置 (delta = +columns)"""
        cols = max(1, int(self.model.columns))
        total = len(self.model.frames)
        moved = []
        # 逆序遍历: 先移动靠下的, 避免覆盖
        for idx in sorted(self.selection, reverse=True):
            target = idx + cols
            if target < total and target not in self.selection:
                self.model.swap_frames(idx, target)
                moved.append(target)
            else:
                moved.append(idx)
        self.selection = set(moved)
        self.editor._on_model_changed()
        self.redraw()


# ── 左侧图片列表面板 ───────────────────────────────────────
class ImageListPanel(ttk.Frame):
    """左侧面板: 精灵/精灵组列表. 不闪烁 + 小缩略图 + 支持 Ctrl/Shift/拖拽排序"""

    NORMAL_BG = "#ffffff"
    SELECTED_BG = "#cfe2ff"      # 更醒目的蓝
    DRAG_OVER_BG = "#fff3bf"     # 拖拽悬停黄
    THUMB_SZ = 20                # 略比字体大即可

    def __init__(self, parent, editor):
        super().__init__(parent, width=220)
        self.editor = editor
        self._thumbs: List[ImageTk.PhotoImage] = []
        self._image_paths: List[str] = []
        # id(PIL.Image) -> 源文件路径, 跟随帧对象身份移动, 交换后仍能正确显示名字
        self._path_by_id: dict = {}

        # 行部件缓存: [{mi, row_frame, text_col, thumb_lbl, name_lbl, size_lbl}]
        self._rows: List[dict] = []
        # 上次 rebuild 时的帧对象快照, 用于判断是否需要重建
        self._last_snapshot: List[int] = []

        self._selected_idx: int = -1  # 主选中 (模型索引)
        self._anchor_idx: int = -1    # shift 范围选的锚点

        # 拖拽状态
        self._drag_from_mi: int = -1
        self._drag_started: bool = False
        self._drag_over_mi: int = -1
        self._press_x_root: int = 0
        self._press_y_root: int = 0

        self._title_var = tk.StringVar(value="导入的精灵")
        self._list_frame: Optional[tk.Frame] = None
        self._list_canvas: Optional[tk.Canvas] = None
        self._build()

    def set_title(self, title: str):
        self._title_var.set(title)

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(header, textvariable=self._title_var,
                  font=("", 9, "bold")).pack(side="left")
        # 清空 / 下移 / 上移 — 按 pack(side="right") 顺序在右侧从右向左排列
        ttk.Button(header, text="清空", command=self._clear_all, width=4).pack(
            side="right", padx=1)
        ttk.Button(header, text="▼下移",
                   command=lambda: self.editor.canvas.move_selected_right(),
                   width=5).pack(side="right", padx=1)
        ttk.Button(header, text="▲上移",
                   command=lambda: self.editor.canvas.move_selected_left(),
                   width=5).pack(side="right", padx=1)

        list_container = ttk.Frame(self)
        list_container.pack(fill="both", expand=True, padx=2, pady=2)

        canvas = tk.Canvas(list_container, highlightthickness=0, bg=self.NORMAL_BG)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical",
                                   command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        self._list_frame = tk.Frame(canvas, bg=self.NORMAL_BG)
        canvas.create_window((0, 0), window=self._list_frame, anchor="nw",
                             tags="inner")
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._list_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfigure("inner", width=e.width))

        def _mw(ev):
            canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._list_canvas = canvas

        self._info_var = tk.StringVar(value="未导入图片")
        ttk.Label(self, textvariable=self._info_var, foreground="#888888",
                  font=("", 8)).pack(side="bottom", fill="x", padx=4, pady=2)

    # ── 数据入口 ───────────────────────
    def _clear_all(self):
        if self.editor.model.frame_count > 0:
            if not messagebox.askyesno("确认", "确定清空所有已导入的图片?"):
                return
        self.editor.model.frames.clear()
        self._image_paths.clear()
        self._path_by_id.clear()
        self._selected_idx = -1
        self._anchor_idx = -1
        self.editor.canvas.selection.clear()
        self.editor._on_model_changed()

    def set_images(self, images: List[Image.Image], paths: List[str]):
        self._image_paths = list(paths)
        self._path_by_id = {}
        for img, p in zip(images, paths):
            if img is not None:
                self._path_by_id[id(img)] = p
        self._rebuild_list(list(self.editor.model.frames))

    # ── 行渲染 ─────────────────────────
    def _rebuild_list(self, images: List[Optional[Image.Image]]):
        """images 为 model.frames (可能含 None). 仅在数据变更时调用, 避免闪烁"""
        if self._list_frame is None:
            return
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._thumbs.clear()

        sz = self.THUMB_SZ
        shown = 0
        for mi, img in enumerate(images):
            if img is None:
                continue

            row = tk.Frame(self._list_frame, bg=self.NORMAL_BG, cursor="hand2",
                           highlightthickness=0, height=sz + 4)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)

            # 缩略图 - 正方形居中裁剪
            thumb_lbl = None
            try:
                w, h = img.size
                sq = min(w, h)
                left = (w - sq) // 2
                top = (h - sq) // 2
                crop = img.crop((left, top, left + sq, top + sq))
                crop.thumbnail((sz, sz), Image.LANCZOS)
                photo = ImageTk.PhotoImage(crop)
                self._thumbs.append(photo)
                thumb_lbl = tk.Label(row, image=photo, borderwidth=0,
                                      bg=self.NORMAL_BG)
                thumb_lbl.image = photo
                thumb_lbl.pack(side="left", padx=(4, 4))
            except Exception:
                thumb_lbl = tk.Label(row, text="?", bg=self.NORMAL_BG,
                                      font=("", 8), width=2)
                thumb_lbl.pack(side="left", padx=(4, 4))

            # 文字 (名称 + 尺寸, 横向单行)
            text_col = tk.Frame(row, bg=self.NORMAL_BG)
            text_col.pack(side="left", fill="x", expand=True)

            raw_path = self._path_by_id.get(id(img), "")
            name = Path(raw_path).name if raw_path else f"#{mi}"
            display_name = name if len(name) <= 22 else name[:20] + "..."

            name_lbl = tk.Label(text_col, text=display_name, anchor="w",
                                 font=("", 9), bg=self.NORMAL_BG)
            name_lbl.pack(side="left", padx=(0, 6))
            size_lbl = tk.Label(text_col, text=f"{img.width}×{img.height}",
                                 anchor="w", font=("", 8), fg="#888888",
                                 bg=self.NORMAL_BG)
            size_lbl.pack(side="left")

            info = {
                "mi": mi, "row_frame": row, "text_col": text_col,
                "thumb_lbl": thumb_lbl, "name_lbl": name_lbl, "size_lbl": size_lbl,
            }
            self._rows.append(info)

            # 绑定事件, 支持点击/Ctrl/Shift 选中 + 拖拽排序
            self._bind_row_events(info)

            shown += 1

        self._last_snapshot = [id(im) for im in images]
        total = self.editor.model.total_cells
        self._info_var.set(
            f"{shown} 张 | 网格 {self.editor.model.columns}×{self.editor.model.rows}={total}")
        self._refresh_bg()

    def _bind_row_events(self, info: dict):
        mi = info["mi"]
        widgets = [info["row_frame"], info["text_col"],
                   info["thumb_lbl"], info["name_lbl"], info["size_lbl"]]
        for w in widgets:
            if w is None:
                continue
            try:
                w.bind("<ButtonPress-1>", lambda e, m=mi: self._on_row_press(e, m))
                w.bind("<B1-Motion>", lambda e, m=mi: self._on_row_drag(e, m))
                w.bind("<ButtonRelease-1>", lambda e, m=mi: self._on_row_release(e, m))
                w.bind("<Control-Button-1>", lambda e, m=mi: self._on_row_ctrl(e, m))
                w.bind("<Shift-Button-1>", lambda e, m=mi: self._on_row_shift(e, m))
            except Exception:
                pass

    def _refresh_bg(self):
        """仅根据选中/拖拽状态更新每行的背景色, 不重建部件 → 消除闪烁"""
        sel = self.editor.canvas.selection
        for info in self._rows:
            mi = info["mi"]
            is_sel = mi in sel
            is_drag = (mi == self._drag_over_mi and self._drag_started)
            bg = (self.DRAG_OVER_BG if is_drag
                  else (self.SELECTED_BG if is_sel else self.NORMAL_BG))
            for w in (info["row_frame"], info["text_col"],
                       info["thumb_lbl"], info["name_lbl"], info["size_lbl"]):
                if w is None:
                    continue
                try:
                    w.configure(bg=bg)
                except Exception:
                    pass

    # ── 选中操作 ─────────────────────────
    def _apply_selection(self, sel: Set[int], primary: int):
        """写回 canvas.selection + 同步内部状态, 触发内嵌预览联动"""
        self.editor.canvas.selection = set(sel)
        self.editor.canvas._last_click_idx = primary
        self._selected_idx = primary
        self.editor.canvas.redraw()
        self._refresh_bg()
        # 联动单帧/动画预览
        if hasattr(self.editor, "_on_selection_changed"):
            self.editor._on_selection_changed()

    def _on_blank_click(self):
        """列表空白区域被点击→取消选中 (仅列表本身, 不从行部件冒泡)"""
        self._anchor_idx = -1
        self._apply_selection(set(), -1)

    def _on_row_press(self, event, mi: int):
        # 再次点击同一个已唯一选中的行 → 取消选中 (联动到预览区)
        sel = set(self.editor.canvas.selection)
        if sel == {mi}:
            self._anchor_idx = -1
            self._drag_from_mi = -1
            self._drag_started = False
            self._drag_over_mi = -1
            self._apply_selection(set(), -1)
            return "break"
        self._anchor_idx = mi
        self._drag_from_mi = mi
        self._drag_started = False
        self._drag_over_mi = -1
        self._press_x_root = event.x_root
        self._press_y_root = event.y_root
        self._apply_selection({mi}, mi)
        return "break"  # 阻止冲击到 canvas 空白点击处理

    def _on_row_shift(self, event, mi: int):
        """Shift 点击: 从 anchor 到 mi 的范围选 (基于非空帧位置)"""
        frames = list(self.editor.model.frames)
        valid = [i for i, f in enumerate(frames) if f is not None]
        if not valid:
            return "break"
        anchor = self._anchor_idx if self._anchor_idx in valid else valid[0]
        try:
            pa = valid.index(anchor)
            pm = valid.index(mi)
        except ValueError:
            return "break"
        lo, hi = min(pa, pm), max(pa, pm)
        sel = set(valid[lo:hi + 1])
        self._apply_selection(sel, mi)
        return "break"

    def _on_row_ctrl(self, event, mi: int):
        """Ctrl 点击: 切换单项选中"""
        sel = set(self.editor.canvas.selection)
        if mi in sel:
            sel.discard(mi)
        else:
            sel.add(mi)
        primary = mi if mi in sel else (max(sel) if sel else -1)
        self._anchor_idx = mi
        self._apply_selection(sel, primary)
        return "break"

    # ── 拖拽排序 ──────────────────────────
    def _mi_at_y_root(self, y_root: int) -> int:
        """根据屏幕绝对 y 坐标查找目标行的 mi"""
        if self._list_frame is None:
            return -1
        lf_y = self._list_frame.winfo_rooty()
        y_in_lf = y_root - lf_y
        for info in self._rows:
            rf = info["row_frame"]
            ry = rf.winfo_y()
            rh = rf.winfo_height()
            if ry <= y_in_lf < ry + rh:
                return info["mi"]
        return -1

    def _on_row_drag(self, event, mi: int):
        if self._drag_from_mi < 0:
            return
        if not self._drag_started:
            dx = abs(event.x_root - self._press_x_root)
            dy = abs(event.y_root - self._press_y_root)
            if dx + dy < DRAG_THRESHOLD:
                return
            self._drag_started = True
        target = self._mi_at_y_root(event.y_root)
        if target != self._drag_over_mi:
            self._drag_over_mi = target
            self._refresh_bg()

    def _on_row_release(self, event, mi: int):
        src = self._drag_from_mi
        dst = self._drag_over_mi
        started = self._drag_started
        self._drag_from_mi = -1
        self._drag_over_mi = -1
        self._drag_started = False

        if not started or src < 0 or dst < 0 or src == dst:
            self._refresh_bg()
            return

        frames = list(self.editor.model.frames)
        if not (0 <= src < len(frames)) or frames[src] is None:
            self._refresh_bg()
            return
        if not (0 <= dst < len(frames)):
            self._refresh_bg()
            return

        # 从 src pop 后再 insert 到 dst (标准 reorder 语义)
        item = frames.pop(src)
        dst_adj = dst if dst < src else dst - 1
        dst_adj = max(0, min(dst_adj, len(frames)))
        frames.insert(dst_adj, item)
        self.editor.model.frames = frames

        new_mi = dst_adj
        self._selected_idx = new_mi
        self._anchor_idx = new_mi
        self.editor.canvas.selection = {new_mi}
        self.editor.canvas._last_click_idx = new_mi
        self.editor._on_model_changed()

    # ── 公共 API ─────────────────────────
    def selected_image_idx(self) -> int:
        return self._selected_idx

    def remove_selected(self) -> bool:
        """删除当前主选中图片 (从模型 pop)"""
        if self._selected_idx < 0:
            return False
        frames = list(self.editor.model.frames)
        mi = self._selected_idx
        if not (0 <= mi < len(frames)) or frames[mi] is None:
            return False
        removed = frames.pop(mi)
        self._path_by_id.pop(id(removed), None)
        self.editor.model.frames = frames

        self._selected_idx = -1
        for i in range(mi, len(frames)):
            if frames[i] is not None:
                self._selected_idx = i
                break
        if self._selected_idx < 0:
            for i in range(min(mi - 1, len(frames) - 1), -1, -1):
                if frames[i] is not None:
                    self._selected_idx = i
                    break
        self._anchor_idx = self._selected_idx
        if self._selected_idx >= 0:
            self.editor.canvas.selection = {self._selected_idx}
        else:
            self.editor.canvas.selection.clear()
        self.editor._on_model_changed()
        return True

    def move_selected(self, delta: int) -> bool:
        """在所有非空帧中将选中帧移动 delta 个位置"""
        if self._selected_idx < 0:
            return False
        frames = list(self.editor.model.frames)
        mi = self._selected_idx
        if not (0 <= mi < len(frames)) or frames[mi] is None:
            return False
        non_none = [i for i, f in enumerate(frames) if f is not None]
        try:
            pos = non_none.index(mi)
        except ValueError:
            return False
        new_pos = pos + delta
        if not (0 <= new_pos < len(non_none)):
            return False
        new_mi = non_none[new_pos]
        frames[mi], frames[new_mi] = frames[new_mi], frames[mi]
        self._selected_idx = new_mi
        self._anchor_idx = new_mi
        self.editor.model.frames = frames
        self.editor.canvas.selection = {new_mi}
        self.editor.canvas._last_click_idx = new_mi
        self.editor._on_model_changed()
        return True

    def refresh_values(self):
        """模型变更后调用. 判断是否真需重建 (帧的对象身份变更) → 避免单纯选中的重建闪烁"""
        current = list(self.editor.model.frames)
        curr_snap = [id(im) for im in current]
        if curr_snap != self._last_snapshot:
            self._rebuild_list(current)
        else:
            self._refresh_bg()


# ── 右侧设置面板 ──────────────────────────────────────────
class SettingsPanel(ttk.Frame):
    """右侧面板: 网格参数设置, 实时更新预览"""

    def __init__(self, parent, model: SpriteSheetModel, editor):
        super().__init__(parent, width=260)
        self.model = model
        self.editor = editor
        self._build()

    def _build(self):
        # ── 网格设置 ──
        grid_frame = ttk.LabelFrame(self, text="网格设置", padding=8)
        grid_frame.pack(fill="x", padx=4, pady=4)

        row1 = ttk.Frame(grid_frame)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="列数 (cols):", width=10).pack(side="left")
        self._cols_var = tk.IntVar(value=self.model.columns)
        ttk.Spinbox(row1, from_=1, to=64, width=6,
                    textvariable=self._cols_var,
                    command=self._on_param_changed).pack(side="left", padx=4)

        row2 = ttk.Frame(grid_frame)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="行数 (rows):", width=10).pack(side="left")
        self._rows_var = tk.IntVar(value=self.model.rows)
        ttk.Spinbox(row2, from_=1, to=64, width=6,
                    textvariable=self._rows_var,
                    command=self._on_param_changed).pack(side="left", padx=4)

        row3 = ttk.Frame(grid_frame)
        row3.pack(fill="x", pady=3)
        ttk.Label(row3, text="间距 (padding):", width=10).pack(side="left")
        self._pad_var = tk.IntVar(value=self.model.padding)
        ttk.Spinbox(row3, from_=0, to=32, width=6,
                    textvariable=self._pad_var,
                    command=self._on_param_changed).pack(side="left", padx=4)

        ttk.Separator(grid_frame, orient="horizontal").pack(fill="x", pady=6)

        row4 = ttk.Frame(grid_frame)
        row4.pack(fill="x", pady=3)
        ttk.Label(row4, text="Cell 宽:", width=10).pack(side="left")
        self._cw_var = tk.IntVar(value=self.model.cell_width)
        ttk.Spinbox(row4, from_=1, to=4096, width=6,
                    textvariable=self._cw_var,
                    command=self._on_param_changed).pack(side="left", padx=4)

        row5 = ttk.Frame(grid_frame)
        row5.pack(fill="x", pady=3)
        ttk.Label(row5, text="Cell 高:", width=10).pack(side="left")
        self._ch_var = tk.IntVar(value=self.model.cell_height)
        ttk.Spinbox(row5, from_=1, to=4096, width=6,
                    textvariable=self._ch_var,
                    command=self._on_param_changed).pack(side="left", padx=4)

        ttk.Button(grid_frame, text="自动检测 Cell 大小",
                   command=self._auto_detect).pack(fill="x", pady=4)

        # 拆分模式下可用: 使用当前参数重新拆分已导入的 Spritesheet
        self._btn_resplit = ttk.Button(grid_frame, text="重新拆分",
                                        command=self.editor._resplit)
        self._btn_resplit.pack(fill="x", pady=2)
        try: self._btn_resplit.state(["disabled"])
        except Exception: pass

        # ── 输出信息 ──
        info_frame = ttk.LabelFrame(self, text="输出信息", padding=8)
        info_frame.pack(fill="x", padx=4, pady=4)

        self._output_info = tk.Text(info_frame, height=5, width=28, bg="#2a2a2a",
                                     fg="#aaaaaa", font=("Consolas", 9), state="disabled",
                                     relief="flat", borderwidth=0)
        self._output_info.pack(fill="x")

        # ── 行/列操作 ──
        ops_frame = ttk.LabelFrame(self, text="行/列排序", padding=8)
        ops_frame.pack(fill="x", padx=4, pady=4)

        btn_row1 = ttk.Frame(ops_frame)
        btn_row1.pack(fill="x", pady=2)
        ttk.Label(btn_row1, text="行:", width=4).pack(side="left")
        ttk.Button(btn_row1, text="↑ 上移", command=lambda: self._move_row(-1),
                   width=7).pack(side="left", padx=1)
        ttk.Button(btn_row1, text="↓ 下移", command=lambda: self._move_row(1),
                   width=7).pack(side="left", padx=1)

        btn_row2 = ttk.Frame(ops_frame)
        btn_row2.pack(fill="x", pady=2)
        ttk.Label(btn_row2, text="列:", width=4).pack(side="left")
        ttk.Button(btn_row2, text="← 左移", command=lambda: self._move_col(-1),
                   width=7).pack(side="left", padx=1)
        ttk.Button(btn_row2, text="→ 右移", command=lambda: self._move_col(1),
                   width=7).pack(side="left", padx=1)

        ttk.Label(ops_frame, text="提示: 画布上拖拽行头/列头也可排序",
                  foreground="#666666", font=("", 8)).pack(anchor="w", pady=(4, 0))

        # ── 导出设置 ──
        export_frame = ttk.LabelFrame(self, text="导出", padding=8)
        export_frame.pack(fill="x", padx=4, pady=4)

        # 纹理格式 (决定像素格式的可选项)
        row_tex = ttk.Frame(export_frame)
        row_tex.pack(fill="x", pady=2)
        ttk.Label(row_tex, text="纹理格式:", width=8).pack(side="left")
        self._tex_fmt_var = tk.StringVar(value="PNG-32")
        tex_combo = ttk.Combobox(row_tex, textvariable=self._tex_fmt_var,
                                  values=list(TEXTURE_FORMATS.keys()),
                                  state="readonly", width=12)
        tex_combo.pack(side="left", fill="x", expand=True)
        tex_combo.bind("<<ComboboxSelected>>",
                       lambda e: self._on_tex_fmt_changed())

        # 像素格式 (根据纹理格式动态更新)
        row_pix = ttk.Frame(export_frame)
        row_pix.pack(fill="x", pady=2)
        ttk.Label(row_pix, text="像素格式:", width=8).pack(side="left")
        self._fmt_var = tk.StringVar(value="RGBA8888")
        self._fmt_combo = ttk.Combobox(row_pix, textvariable=self._fmt_var,
                                        values=TEXTURE_FORMATS["PNG-32"],
                                        state="readonly", width=12)
        self._fmt_combo.pack(side="left", fill="x", expand=True)
        self._fmt_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._refresh_export_info())

        # 透明处理 (Alpha 处理)
        row_alpha = ttk.Frame(export_frame)
        row_alpha.pack(fill="x", pady=2)
        ttk.Label(row_alpha, text="透明处理:", width=8).pack(side="left")
        self._alpha_mode_var = tk.StringVar(value="清除透明像素")
        alpha_combo = ttk.Combobox(row_alpha, textvariable=self._alpha_mode_var,
                                    values=ALPHA_MODES,
                                    state="readonly", width=12)
        alpha_combo.pack(side="left", fill="x", expand=True)
        alpha_combo.bind("<<ComboboxSelected>>",
                         lambda e: self._refresh_export_info())

        # 格式说明 (像素格式 + Alpha 模式详细说明)
        ttk.Label(export_frame, text="格式说明:", font=("", 8)).pack(anchor="w", pady=(4, 0))
        self._fmt_desc = tk.Text(export_frame, height=5, width=28, bg="#2a2a2a",
                                  fg="#cccccc", font=("", 8), state="disabled",
                                  relief="flat", borderwidth=0, wrap="word")
        self._fmt_desc.pack(fill="x", pady=(0, 2))

        # 格式预览 (预估导出尺寸 / 大小)
        ttk.Label(export_frame, text="格式预览:", font=("", 8)).pack(anchor="w", pady=(2, 0))
        self._fmt_preview = tk.Text(export_frame, height=4, width=28, bg="#2a2a2a",
                                     fg="#aaccff", font=("Consolas", 8), state="disabled",
                                     relief="flat", borderwidth=0)
        self._fmt_preview.pack(fill="x", pady=(0, 4))

        ttk.Button(export_frame, text="保存图集...",
                   command=self._save_current_fmt).pack(fill="x", pady=1)
        # 批量导出每一帧 (组合 / 拆分模式都可用, 按当前排序导出)
        self._btn_export_each = ttk.Button(export_frame,
                                            text="导出全部 (每帧)",
                                            command=self.editor._export_all_frames)
        self._btn_export_each.pack(fill="x", pady=1)

        # 实时更新输出信息 / 导出面板
        self._update_output_info()
        self._refresh_export_info()

    def _on_param_changed(self):
        """参数变更实时应用到模型并刷新预览"""
        try:
            self.model.columns = self._cols_var.get()
            self.model.rows = self._rows_var.get()
            self.model.padding = self._pad_var.get()
            self.model.cell_width = self._cw_var.get()
            self.model.cell_height = self._ch_var.get()
        except Exception:
            return
        self.editor._on_model_changed()
        self._update_output_info()
        try:
            self._refresh_export_info()
        except Exception:
            pass

    def _auto_detect(self):
        self.model.auto_detect_cell_size()
        self._cw_var.set(self.model.cell_width)
        self._ch_var.set(self.model.cell_height)
        self._on_param_changed()

    def _move_row(self, delta: int):
        sel = self.editor.canvas.selection
        if not sel:
            if self.model.frame_count == 0:
                return
            # 自动选择第一个非空帧
            for i, f in enumerate(self.model.frames):
                if f is not None:
                    sel = {i}
                    self.editor.canvas.selection = sel
                    break
        if not sel:
            return
        cols = max(1, int(self.model.columns))
        idx = min(sel)
        r = idx // cols
        target = r + delta
        if 0 <= target < self.model.rows:
            self.model.swap_rows(r, target)
            # 同步选中帧指示位: r ↔ target 行的帧位置随之互换
            new_sel = set()
            for s in sel:
                sr, sc = divmod(s, cols)
                if sr == r:
                    new_sel.add(target * cols + sc)
                elif sr == target:
                    new_sel.add(r * cols + sc)
                else:
                    new_sel.add(s)
            self.editor.canvas.selection = new_sel
            self.editor._on_model_changed()
            self._update_output_info()
            try:
                self.editor.canvas.redraw()
            except Exception:
                pass

    def _move_col(self, delta: int):
        sel = self.editor.canvas.selection
        if not sel:
            if self.model.frame_count == 0:
                return
            for i, f in enumerate(self.model.frames):
                if f is not None:
                    sel = {i}
                    self.editor.canvas.selection = sel
                    break
        if not sel:
            return
        cols = max(1, int(self.model.columns))
        idx = min(sel)
        c = idx % cols
        target = c + delta
        if 0 <= target < self.model.columns:
            self.model.swap_cols(c, target)
            # 同步选中帧指示位: c ↔ target 列的帧位置随之互换
            new_sel = set()
            for s in sel:
                sr, sc = divmod(s, cols)
                if sc == c:
                    new_sel.add(sr * cols + target)
                elif sc == target:
                    new_sel.add(sr * cols + c)
                else:
                    new_sel.add(s)
            self.editor.canvas.selection = new_sel
            self.editor._on_model_changed()
            self._update_output_info()
            try:
                self.editor.canvas.redraw()
            except Exception:
                pass

    def _on_tex_fmt_changed(self):
        """纹理格式切换: 更新像素格式可选项并回默认值"""
        tex = self._tex_fmt_var.get()
        options = TEXTURE_FORMATS.get(tex, ["RGBA8888"])
        self._fmt_combo.configure(values=options)
        # 当前像素格式不在新纹理格式的选项内 → 重置为第一项
        if self._fmt_var.get() not in options:
            self._fmt_var.set(options[0])
        self._refresh_export_info()

    def _refresh_export_info(self):
        """更新格式说明 + 格式预览"""
        fmt = self._fmt_var.get()
        alpha_mode = self._alpha_mode_var.get()
        # 格式说明: 像素格式 → Alpha 模式
        pix_desc = PIXEL_FORMAT_DESC.get(fmt, "")
        alpha_desc = ALPHA_MODE_DESC.get(alpha_mode, "")
        desc = f"【{fmt}】\n{pix_desc}\n\n【{alpha_mode}】\n{alpha_desc}"
        self._fmt_desc.configure(state="normal")
        self._fmt_desc.delete("1.0", "end")
        self._fmt_desc.insert("1.0", desc)
        self._fmt_desc.configure(state="disabled")

        # 格式预览: 尺寸 / 位深 / 预估大小
        lines: List[str] = []
        m = self.model
        try:
            ss = m.build_spritesheet()
            w, h = ss.size
            # 位深估算
            bpp_map = {
                "RGBA8888": 32, "RGB888": 24,
                "RGB565": 16, "RGBA5551": 16, "RGBA4444": 16,
                "PNG-8 (256色)": 8,
            }
            bpp = bpp_map.get(fmt, 32)
            raw_kb = w * h * bpp // 8 // 1024
            lines.append(f"尺寸: {w} × {h} px")
            lines.append(f"纹理格式: {self._tex_fmt_var.get()}")
            lines.append(f"像素格式: {fmt} ({bpp}-bit)")
            lines.append(f"预估原始: ~{raw_kb} KB (PNG 压缩后更小)")
        except Exception:
            lines.append("(无数据)")
        self._fmt_preview.configure(state="normal")
        self._fmt_preview.delete("1.0", "end")
        self._fmt_preview.insert("1.0", "\n".join(lines))
        self._fmt_preview.configure(state="disabled")

    def _save_current_fmt(self):
        """按当前面板的纹理/像素/Alpha 设置保存完整精灵表"""
        m = self.model
        if m.frame_count == 0:
            messagebox.showinfo("提示", "没有帧数据可导出")
            return
        ss = m.build_spritesheet()
        alpha_mode = self._alpha_mode_var.get()
        ss = apply_alpha_mode(ss, alpha_mode)
        fmt = self._fmt_var.get()
        converted = convert_pixel_format(ss, fmt)
        fp = filedialog.asksaveasfilename(
            title=f"保存图集 ({self._tex_fmt_var.get()} / {fmt})",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")])
        if not fp:
            return
        converted.save(fp, "PNG")
        self.editor._status_var.set(
            f"已保存 ({self._tex_fmt_var.get()} / {fmt} / {alpha_mode}): {Path(fp).name}")
        self._update_output_info()

    def _update_output_info(self):
        """更新输出信息文本框"""
        self._output_info.configure(state="normal")
        self._output_info.delete("1.0", "end")
        m = self.model
        try:
            ss = m.build_spritesheet()
            w, h = ss.size
            est_kb = w * h * 4 // 1024
            lines = [
                f"输出尺寸: {w} × {h} px",
                f"预估大小: ~{est_kb} KB (RGBA)",
                f"网格: {m.columns}列 × {m.rows}行",
                f"Cell: {m.cell_width}×{m.cell_height}",
                f"Padding: {m.padding}px",
                f"帧: {m.frame_count}/{m.total_cells}",
            ]
            self._output_info.insert("1.0", "\n".join(lines))
        except Exception:
            pass
        self._output_info.configure(state="disabled")

    def refresh_values(self):
        """从 model 同步设置值到 UI"""
        self._cols_var.set(self.model.columns)
        self._rows_var.set(self.model.rows)
        self._pad_var.set(self.model.padding)
        self._cw_var.set(self.model.cell_width)
        self._ch_var.set(self.model.cell_height)
        self._update_output_info()
        try:
            self._refresh_export_info()
        except Exception:
            pass


# ── 预览窗口 ──────────────────────────────────────────────
class InlinePreviewView(ttk.Frame):
    """中间区域的内嵌预览 — 单帧/动画两种模式共用一套 UI

    - 单帧模式: 强制暂停, 显示当前主选中帧 (无选中时显示第一帧)
    - 动画模式: 可播放, FPS/循环/往返, 范围 = 全部 or 当前选中
    """

    def __init__(self, parent, editor):
        super().__init__(parent)
        self.editor = editor
        self._frames: List[Image.Image] = []
        self._current = 0
        self._playing = False
        self._direction = 1
        self._job: Optional[str] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._mode: str = "single"   # "single" | "anim"

        self._fps_var = tk.IntVar(value=DEFAULT_FPS)
        self._loop_var = tk.BooleanVar(value=True)
        self._pingpong_var = tk.BooleanVar(value=False)
        # 预览范围 (仅动画模式生效)
        self._range_var = tk.StringVar(value="all")
        # 缩放 (单帧/动画模式均生效, 参考 jvg_editor)
        self._zoom_var = tk.DoubleVar(value=1.0)
        # 时间轴缩略图缓存
        self._tl_photos: List[ImageTk.PhotoImage] = []
        self._tl_cell: int = 44  # timeline cell size

        self._build()

    def _build(self):
        self._ctrl = ttk.Frame(self)
        self._ctrl.pack(side="top", fill="x", padx=4, pady=2)

        self._btn_play = ttk.Button(self._ctrl, text="▶ 播放", width=8,
                                     command=self._toggle_play)
        self._btn_play.pack(side="left", padx=2)
        ttk.Button(self._ctrl, text="⏮", width=3, command=self._go_first).pack(
            side="left", padx=1)
        ttk.Button(self._ctrl, text="◀", width=3, command=self._prev_frame).pack(
            side="left", padx=1)
        ttk.Button(self._ctrl, text="▶", width=3, command=self._next_frame).pack(
            side="left", padx=1)
        ttk.Button(self._ctrl, text="⏭", width=3, command=self._go_last).pack(
            side="left", padx=1)

        ttk.Label(self._ctrl, text="  FPS:").pack(side="left", padx=(10, 2))
        # 监听箭头 / 键盘 / 焦点 / 写入 四种事件, 任一种都能实时刷新播放延迟
        self._fps_var.trace_add("write", lambda *a: self._on_fps_change())
        self._fps_spin = ttk.Spinbox(self._ctrl, from_=1, to=120, width=4,
                                      textvariable=self._fps_var,
                                      command=self._on_fps_change)
        self._fps_spin.bind("<KeyRelease>", lambda e: self._on_fps_change())
        self._fps_spin.bind("<FocusOut>", lambda e: self._on_fps_change())
        self._fps_spin.pack(side="left", padx=2)

        self._loop_cb = ttk.Checkbutton(self._ctrl, text="循环",
                                         variable=self._loop_var)
        self._loop_cb.pack(side="left", padx=(8, 2))
        self._pingpong_cb = ttk.Checkbutton(self._ctrl, text="往返",
                                             variable=self._pingpong_var)
        self._pingpong_cb.pack(side="left", padx=2)

        ttk.Separator(self._ctrl, orient="vertical").pack(
            side="left", fill="y", padx=6, pady=2)
        ttk.Label(self._ctrl, text="范围:").pack(side="left", padx=(2, 2))
        self._range_all = ttk.Radiobutton(self._ctrl, text="全部",
                                           variable=self._range_var, value="all",
                                           command=self._on_range_change)
        self._range_all.pack(side="left", padx=2)
        self._range_sel = ttk.Radiobutton(self._ctrl, text="选中",
                                           variable=self._range_var, value="sel",
                                           command=self._on_range_change)
        self._range_sel.pack(side="left", padx=2)

        self._counter_var = tk.StringVar(value="0/0")
        ttk.Label(self._ctrl, textvariable=self._counter_var,
                  width=10).pack(side="right", padx=4)

        # 底部: 时间轴 + 进度条 (先 pack 进度条, 再 pack 时间轴 → timeline 在进度条上方)
        self._scale = ttk.Scale(self, from_=0, to=1, orient="horizontal",
                                 command=self._on_scale)
        self._scale.pack(side="bottom", fill="x", padx=4, pady=2)

        # 时间轴 (仅动画模式可见)
        tl_frame = ttk.Frame(self)
        self._timeline_frame = tl_frame
        self._timeline = tk.Canvas(tl_frame, bg="#222222", height=self._tl_cell + 14,
                                    highlightthickness=0)
        tl_scroll = ttk.Scrollbar(tl_frame, orient="horizontal",
                                   command=self._timeline.xview)
        self._timeline.configure(xscrollcommand=tl_scroll.set)
        tl_scroll.pack(side="bottom", fill="x")
        self._timeline.pack(side="top", fill="x")
        self._timeline.bind("<MouseWheel>",
            lambda e: self._timeline.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        # 默认不显示, 由 set_mode 控制

        # 中间: 显示区 (最后 pack, 填充剩余空间)
        self._disp = tk.Label(self, bg="#1a1a1a")
        self._disp.pack(fill="both", expand=True, padx=4, pady=2)
        # 监听 _disp 的第一次有效尺寸 → 重新 prerender (避免首次切换时由于 widget 未布局导致预渲染偏小)
        self._last_disp_size: Tuple[int, int] = (0, 0)
        self._disp.bind("<Configure>", self._on_disp_configure)
        # Ctrl+滚轮 = 缩放 (参考 jvg_editor)
        self._disp.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<MouseWheel>", self._on_mousewheel)

    def _on_disp_configure(self, event):
        """显示区尺寸变化时重新预渲染 (避免首次切换时由于小尺寸预渲染后看起来变大)"""
        new_size = (event.width, event.height)
        # 变化足够大才重新渲染, 避免频繁重建
        if not self._frames:
            self._last_disp_size = new_size
            return
        ow, oh = self._last_disp_size
        if abs(new_size[0] - ow) < 8 and abs(new_size[1] - oh) < 8:
            return
        self._last_disp_size = new_size
        self._prerender()
        self._show_frame(self._current)

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "single":
            self.stop()
            for w in (self._btn_play, self._loop_cb, self._pingpong_cb,
                       self._range_all, self._range_sel):
                try: w.state(["disabled"])
                except Exception: pass
            # 单帧模式: 隐藏时间轴
            try: self._timeline_frame.pack_forget()
            except Exception: pass
        else:
            for w in (self._btn_play, self._loop_cb, self._pingpong_cb,
                       self._range_all, self._range_sel):
                try: w.state(["!disabled"])
                except Exception: pass
            # 动画模式: 显示时间轴 (在进度条上方)
            try:
                self._timeline_frame.pack(side="bottom", fill="x",
                                           before=self._disp, padx=4, pady=(0, 2))
            except Exception:
                try: self._timeline_frame.pack(side="bottom", fill="x", padx=4, pady=(0, 2))
                except Exception: pass
            self._rebuild_timeline()

    def set_frames(self, frames: List[Image.Image], keep_idx: bool = True):
        """预渲染所有帧 (jvg_editor 风格), 避免动画时 resize"""
        old_idx = self._current
        self._frames = [f for f in frames if f is not None]
        n = len(self._frames)
        if n == 0:
            self._current = 0
        elif keep_idx:
            self._current = min(old_idx, n - 1)
        else:
            self._current = 0
        try:
            self._scale.configure(to=max(n - 1, 1))
        except Exception:
            pass
        # 强制完成布局后再取 _disp 尺寸 → 避免首次切换预渲染偏小
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._last_disp_size = (self._disp.winfo_width(), self._disp.winfo_height())
        # 预渲染: 确定统一显示尺寸, 一次性 resize 所有帧
        self._prerender()
        self._show_frame(self._current)
        # 重建时间轴 (仅动画模式可见)
        if self._mode == "anim":
            self._rebuild_timeline()

    def _prerender(self):
        """预渲染所有帧为 PhotoImage 缓存 (1:1 = 原图像素)"""
        self._rendered: List[Optional[ImageTk.PhotoImage]] = []
        n = len(self._frames)
        if n == 0:
            return
        try:
            zoom = max(0.5, float(self._zoom_var.get()))
        except Exception:
            zoom = 1.0
        # 缩放基准 = 原图 100%, 不再适应窗口 (zoom=1.0 即 1像素:1像素)
        scale = max(zoom, 0.05)
        for f in self._frames:
            fw = max(1, int(f.width * scale))
            fh = max(1, int(f.height * scale))
            if fw == f.width and fh == f.height:
                disp_img = f
            else:
                disp_img = f.resize((fw, fh), Image.NEAREST)
            self._rendered.append(ImageTk.PhotoImage(disp_img))

    def _show_frame(self, idx: int):
        n = len(self._frames)
        if n == 0:
            try:
                self._disp.configure(image="")
            except Exception:
                pass
            self._photo = None
            self._counter_var.set("0/0")
            return
        idx = max(0, min(idx, n - 1))
        self._current = idx
        if hasattr(self, "_rendered") and idx < len(self._rendered):
            self._photo = self._rendered[idx]
            self._disp.configure(image=self._photo)
        self._counter_var.set(f"{idx + 1}/{n}")
        try:
            self._scale.set(idx)
        except Exception:
            pass
        # 时间轴高亮更新
        self._update_timeline_highlight()

    def _toggle_play(self):
        if self._mode != "anim":
            return
        if self._playing:
            self.stop()
        else:
            if not self._frames:
                return
            self._playing = True
            self._btn_play.configure(text="⏸ 暂停")
            self._animate()

    def stop(self):
        self._playing = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        try:
            self._btn_play.configure(text="▶ 播放")
        except Exception:
            pass

    def _animate(self):
        if not self._playing or not self._frames:
            return
        n = len(self._frames)
        if self._pingpong_var.get():
            nxt = self._current + self._direction
            if nxt >= n:
                self._direction = -1
                nxt = n - 2 if n >= 2 else 0
            elif nxt < 0:
                self._direction = 1
                nxt = 1 if n >= 2 else 0
            nxt = max(0, min(nxt, n - 1))
            self._show_frame(nxt)
        else:
            nxt = self._current + 1
            if nxt >= n:
                if self._loop_var.get():
                    nxt = 0
                else:
                    self.stop()
                    return
            self._show_frame(nxt)
        try:
            fps = max(1, int(self._fps_var.get()))
        except Exception:
            fps = DEFAULT_FPS
        delay = max(5, int(1000 / fps))
        self._job = self.after(delay, self._animate)

    def _on_fps_change(self):
        """FPS 变更 → 立即重新调度当前等待中的动画帧"""
        if not self._playing:
            return
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        try:
            fps = max(1, int(self._fps_var.get()))
        except Exception:
            return
        delay = max(5, int(1000 / fps))
        self._job = self.after(delay, self._animate)

    def _on_range_change(self):
        if hasattr(self.editor, "_refresh_inline_preview"):
            self.editor._refresh_inline_preview(keep_idx=False)

    def _on_scale(self, val):
        try:
            self._show_frame(int(float(val)))
        except Exception:
            pass

    def _go_first(self):
        self._show_frame(0)

    def _go_last(self):
        self._show_frame(len(self._frames) - 1)

    def _prev_frame(self):
        self._show_frame(self._current - 1)

    def _next_frame(self):
        self._show_frame(self._current + 1)

    # ── 缩放 ──────────────────────────────
    def _zoom_step(self, delta: float):
        try:
            z = float(self._zoom_var.get())
        except Exception:
            z = 1.0
        z = max(0.5, min(5.0, z + delta))
        self._zoom_var.set(z)
        try:
            self.editor._zoom_label.config(text=f"{int(z * 100)}%")
        except Exception:
            pass
        if self._frames:
            self._prerender()
            self._show_frame(self._current)

    def _zoom_reset(self):
        self._zoom_var.set(1.0)
        try:
            self.editor._zoom_label.config(text="100%")
        except Exception:
            pass
        if self._frames:
            self._prerender()
            self._show_frame(self._current)

    def _on_mousewheel(self, ev):
        # Ctrl+滚轮 = 缩放
        if ev.state & 0x4:
            delta = 0.25 if ev.delta > 0 else -0.25
            self._zoom_step(delta)
            return "break"
        return None

    # ── 时间轴 ────────────────────────────
    def _rebuild_timeline(self):
        """重建时间轴缩略图 (动画模式下调用)"""
        self._timeline.delete("all")
        self._tl_photos = []
        n = len(self._frames)
        if n == 0:
            self._timeline.configure(scrollregion=(0, 0, 0, 0))
            return
        sz = self._tl_cell
        gap = 2
        y0 = 6
        for i, f in enumerate(self._frames):
            x0 = 4 + i * (sz + gap)
            tag = f"tl_{i}"
            # 单元格背景
            self._timeline.create_rectangle(x0, y0, x0 + sz, y0 + sz,
                                             fill="#2a2a2a", outline="#555555",
                                             tags=(tag,))
            # 缩略图
            try:
                ratio = min(sz / max(f.width, 1), sz / max(f.height, 1))
                tw = max(1, int(f.width * ratio))
                th = max(1, int(f.height * ratio))
                thumb = f.resize((tw, th), Image.NEAREST)
                photo = ImageTk.PhotoImage(thumb)
                self._tl_photos.append(photo)
                px = x0 + (sz - tw) // 2
                py = y0 + (sz - th) // 2
                self._timeline.create_image(px, py, image=photo, anchor="nw",
                                             tags=(tag,))
            except Exception:
                pass
            # 序号
            self._timeline.create_text(x0 + 2, y0 + 1, text=str(i),
                                        anchor="nw", fill="#cccccc",
                                        font=("", 7), tags=(tag,))
            # 点击跳转
            self._timeline.tag_bind(tag, "<Button-1>",
                lambda e, idx=i: self._on_timeline_click(idx))
        total_w = 4 + n * (sz + gap) + 4
        total_h = sz + 14
        self._timeline.configure(scrollregion=(0, 0, total_w, total_h))
        self._update_timeline_highlight()

    def _update_timeline_highlight(self):
        """仅更新当前帧高亮框, 避免全重建"""
        try:
            self._timeline.delete("tl_hl")
        except Exception:
            return
        if self._mode != "anim" or not self._frames:
            return
        n = len(self._frames)
        if self._current >= n:
            return
        sz = self._tl_cell
        gap = 2
        x0 = 4 + self._current * (sz + gap)
        y0 = 6
        self._timeline.create_rectangle(x0 - 1, y0 - 1, x0 + sz + 1, y0 + sz + 1,
                                         outline="#ffcc00", width=2, tags="tl_hl")
        # 自动滚动使当前帧可见
        try:
            total = 4 + n * (sz + gap) + 4
            vw = self._timeline.winfo_width()
            if vw > 0 and total > vw:
                center = x0 + sz / 2
                frac = max(0, min(1, (center - vw / 2) / max(1, total - vw)))
                self._timeline.xview_moveto(frac)
        except Exception:
            pass

    def _on_timeline_click(self, idx: int):
        if 0 <= idx < len(self._frames):
            self.stop()
            self._show_frame(idx)



# ── 主编辑器窗口 ─────────────────────────────────────────────
class SpriteSheetEditor(tk.Tk):
    """Spritesheet 编辑器主窗口"""

    def __init__(self, filepath: Optional[str] = None):
        super().__init__()
        self.title("Spritesheet Editor - 精灵表编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.iconbitmap(default=ico)
        self.geometry("1180x740")
        self.model = SpriteSheetModel()
        self._filepath: Optional[str] = None

        # 工作模式: "merge" (组合/合并) | "split" (拆分)
        self._workflow_mode = tk.StringVar(value="merge")
        # 预览模式: "grid" (网格) | "single" (单帧) | "anim" (动画)
        self._preview_mode = tk.StringVar(value="grid")

        self._build_layout()   # 创建 toolbar + 三栏布局
        self._build_menu()
        self._apply_workflow_mode()  # 首次应用文案

        if filepath:
            self._load_spritesheet(Path(filepath))
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        x = (sw - 1180) // 2; y = (sh - 740) // 2
        self.geometry(f'1180x740+{x}+{y}')

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="导入图片(合并)", command=self._import_images)
        file_menu.add_command(label="导入图集(拆分)", command=self._import_spritesheet)
        file_menu.add_separator()
        file_menu.add_command(label="新建空白", command=self._new)
        file_menu.add_separator()
        file_menu.add_command(label="保存图集", command=self._save, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="全选", command=self.canvas.select_all,
                              accelerator="Ctrl+A")
        edit_menu.add_command(label="取消选择", command=self.canvas.select_none,
                              accelerator="Escape")
        edit_menu.add_separator()
        edit_menu.add_command(label="删除选中帧", command=self.canvas.delete_selected,
                              accelerator="Delete")
        edit_menu.add_separator()
        edit_menu.add_command(label="选中帧左移", command=self.canvas.move_selected_left,
                              accelerator="Ctrl+Left")
        edit_menu.add_command(label="选中帧右移", command=self.canvas.move_selected_right,
                              accelerator="Ctrl+Right")
        edit_menu.add_command(label="选中帧上移", command=self.canvas.move_selected_up,
                              accelerator="Ctrl+Up")
        edit_menu.add_command(label="选中帧下移", command=self.canvas.move_selected_down,
                              accelerator="Ctrl+Down")
        edit_menu.add_separator()
        edit_menu.add_command(label="当前列左移", command=lambda: self.settings._move_col(-1),
                              accelerator="Shift+Left")
        edit_menu.add_command(label="当前列右移", command=lambda: self.settings._move_col(1),
                              accelerator="Shift+Right")
        edit_menu.add_command(label="当前行上移", command=lambda: self.settings._move_row(-1),
                              accelerator="Shift+Up")
        edit_menu.add_command(label="当前行下移", command=lambda: self.settings._move_row(1),
                              accelerator="Shift+Down")
        menubar.add_cascade(label="编辑", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="预览选中帧", command=self._preview_selected)
        view_menu.add_command(label="预览全部", command=self._preview_all)
        menubar.add_cascade(label="预览", menu=view_menu)

        self.config(menu=menubar)

        # 快捷键
        self.bind_all("<Control-s>", lambda e: self._save())
        self.bind_all("<Control-a>", lambda e: self.canvas.select_all())
        self.bind_all("<Escape>", lambda e: self.canvas.select_none())
        self.bind_all("<Delete>", lambda e: self.canvas.delete_selected())
        # 选中帧 ←→↑↓ 移动 (Ctrl+方向键)
        self.bind_all("<Control-Left>", lambda e: self._shortcut_move(e, self.canvas.move_selected_left))
        self.bind_all("<Control-Right>", lambda e: self._shortcut_move(e, self.canvas.move_selected_right))
        self.bind_all("<Control-Up>", lambda e: self._shortcut_move(e, self.canvas.move_selected_up))
        self.bind_all("<Control-Down>", lambda e: self._shortcut_move(e, self.canvas.move_selected_down))
        # 当前行 / 当前列移动 (Shift+方向键)
        self.bind_all("<Shift-Left>", lambda e: self._shortcut_move(e, lambda: self.settings._move_col(-1)))
        self.bind_all("<Shift-Right>", lambda e: self._shortcut_move(e, lambda: self.settings._move_col(1)))
        self.bind_all("<Shift-Up>", lambda e: self._shortcut_move(e, lambda: self.settings._move_row(-1)))
        self.bind_all("<Shift-Down>", lambda e: self._shortcut_move(e, lambda: self.settings._move_row(1)))

    def _shortcut_move(self, event, func):
        """方向键移动快捷键统一入口: 在输入控件中不劫持文本编辑行为"""
        try:
            w = event.widget
            # Entry / Spinbox / Text / Combobox 等输入元素 → 放行默认行为
            if isinstance(w, (tk.Entry, tk.Text, tk.Spinbox, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
                return None
        except Exception:
            pass
        try:
            func()
        except Exception:
            pass
        return "break"

    def _build_layout(self):
        """构建整体布局: 工具栏(上) + 三栏主区域(下)"""
        # ── 工具栏 (顶部, 先 pack 确保位置) ──
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=2, pady=2)

        # ── 主区域 (占满剩余空间) ──
        main = ttk.Frame(self)
        main.pack(side="top", fill="both", expand=True, padx=2, pady=2)

        # ── 左侧: 图片列表 ──
        self.image_list = ImageListPanel(main, self)
        self.image_list.pack(side="left", fill="y")

        # ── 中间: 画布 / 内嵌预览 (stack 切换) ──
        center = ttk.Frame(main)
        center.pack(side="left", fill="both", expand=True)

        # 中间顶部: 预览模式切换栏
        preview_bar = ttk.Frame(center)
        preview_bar.pack(side="top", fill="x", padx=2, pady=(0, 2))
        ttk.Label(preview_bar, text="显示:").pack(side="left", padx=(2, 4))
        for val, text in (("grid", "网格"), ("single", "单帧"), ("anim", "动画")):
            ttk.Radiobutton(preview_bar, text=text, value=val,
                             variable=self._preview_mode,
                             command=self._on_preview_mode_changed).pack(
                side="left", padx=2)

        # 共享缩放控件 (网格 / 单帧 / 动画 三模式共用)
        self._zoom_label = ttk.Label(preview_bar, text="100%", width=5)
        self._zoom_label.pack(side="right", padx=2)
        ttk.Button(preview_bar, text="+", width=2,
                   command=lambda: self._shared_zoom_step(0.25)).pack(side="right", padx=1)
        ttk.Button(preview_bar, text="−", width=2,
                   command=lambda: self._shared_zoom_step(-0.25)).pack(side="right", padx=1)
        ttk.Button(preview_bar, text="1:1", width=3,
                   command=self._shared_zoom_reset).pack(side="right", padx=1)
        ttk.Label(preview_bar, text="缩放:", foreground="#888888").pack(
            side="right", padx=(8, 2))

        # stack 容器: 承载 grid_container 与 preview_view (互斥显示)
        self._center_stack = ttk.Frame(center)
        self._center_stack.pack(side="top", fill="both", expand=True)

        # ─ 网格视图 ─
        self._grid_container = ttk.Frame(self._center_stack)

        h_scroll = ttk.Scrollbar(self._grid_container, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        v_scroll = ttk.Scrollbar(self._grid_container, orient="vertical")
        v_scroll.pack(side="right", fill="y")

        self.canvas = SpriteSheetCanvas(self._grid_container, self.model, self,
                                        xscrollcommand=h_scroll.set,
                                        yscrollcommand=v_scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        h_scroll.configure(command=self.canvas.xview)
        v_scroll.configure(command=self.canvas.yview)

        # ─ 内嵌预览视图 ─
        self.preview_view = InlinePreviewView(self._center_stack, self)

        # 默认显示网格
        self._grid_container.pack(fill="both", expand=True)

        hint = ttk.Label(center, text="操作: 点击选帧 | Ctrl+多选 | Shift+范围选 | 拖拽帧/行头/列头排序",
                         foreground="#888888", font=("", 8))
        hint.pack(anchor="w", side="bottom", padx=2)

        # ── 右侧: 设置面板 ──
        self.settings = SettingsPanel(main, self.model, self)
        self.settings.pack(side="right", fill="y")

        # ── 填充工具栏按钮 (canvas 已存在) ──
        ttk.Label(toolbar, text="模式:").pack(side="left", padx=(2, 4))
        ttk.Radiobutton(toolbar, text="组合", value="merge",
                        variable=self._workflow_mode,
                        command=self._on_workflow_mode_changed).pack(
            side="left", padx=1)
        ttk.Radiobutton(toolbar, text="拆分", value="split",
                        variable=self._workflow_mode,
                        command=self._on_workflow_mode_changed).pack(
            side="left", padx=1)
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=4, pady=2)

        ttk.Button(toolbar, text="新建", command=self._new).pack(side="left", padx=2)
        self._btn_import_merge = ttk.Button(toolbar, text="导入图片",
                                             command=self._import_images)
        self._btn_import_merge.pack(side="left", padx=2)
        self._btn_import_split = ttk.Button(toolbar, text="导入图集",
                                             command=self._import_spritesheet)
        self._btn_import_split.pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=4, pady=2)
        ttk.Button(toolbar, text="预览选中", command=self._preview_selected).pack(
            side="left", padx=2)
        ttk.Button(toolbar, text="预览全部", command=self._preview_all).pack(
            side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=4, pady=2)
        ttk.Button(toolbar, text="删除", command=self._delete_from_list).pack(
            side="left", padx=2)

        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(toolbar, textvariable=self._status_var, foreground="#888888").pack(
            side="right", padx=16)

        # 点击右栏外任意位置 → 取消右栏控件焦点 (避免 Spinbox 抢快捷键)
        self.bind("<Button-1>", self._on_defocus_click, add=True)

    def _on_defocus_click(self, event):
        """点击右栏外任意位置 → 取消右栏内控件焦点, 保证快捷键生效"""
        w = event.widget
        while w is not None:
            if w is self.settings:
                return
            w = w.master
        self.focus_set()

    def _on_model_changed(self):
        """模型变更后刷新所有视图"""
        self.canvas.redraw()
        self.image_list.refresh_values()
        self._update_status()
        # 若当前处于内嵌预览, 同步刷新帧数据
        if hasattr(self, "_preview_mode") and self._preview_mode.get() != "grid":
            self._refresh_inline_preview(keep_idx=True)

    def _update_status(self):
        m = self.model
        self._status_var.set(
            f"帧: {m.frame_count}/{m.total_cells}  "
            f"网格: {m.columns}x{m.rows}  "
            f"Cell: {m.cell_width}x{m.cell_height}  "
            f"Padding: {m.padding}"
        )

    # ── 导入操作 ──────────────────────────────────────────────
    def _new(self):
        """新建空白 Spritesheet"""
        if self.model.frame_count > 0:
            if not messagebox.askyesno("确认", "当前内容将被清除，确定新建吗?"):
                return
        self.model = SpriteSheetModel()
        self.canvas.model = self.model
        self.settings.model = self.model
        self.image_list._image_paths.clear()
        self.image_list._path_by_id.clear()
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_var.set("新建空白 Spritesheet")

    def _import_images(self):
        """导入多张图片直接拼成 Spritesheet (无弹窗, 自动网格)"""
        files = filedialog.askopenfilenames(
            title="选择要导入的图片",
            filetypes=[("图片文件", "*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp"),
                       ("所有文件", "*.*")])
        if not files:
            return

        images = []
        for fp in files:
            try:
                img = Image.open(fp).convert("RGBA")
                images.append(img)
            except Exception as e:
                messagebox.showwarning("警告", f"无法读取 {Path(fp).name}: {e}")

        if not images:
            return

        # 自动计算网格: 尽量接近正方形
        n = len(images)
        cols = max(1, int(n ** 0.5 + 0.5))
        rows = (n + cols - 1) // cols

        self.model.frames = list(images)
        self.model.columns = cols
        self.model.rows = rows
        self.model.padding = self.settings._pad_var.get()
        self.model.auto_detect_cell_size()
        # 重置选中和拖拽状态, 避免残留旧数据
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.image_list._selected_idx = -1
        self.image_list.set_images(list(images), list(files))
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_var.set(f"已导入 {len(images)} 张图片 → {cols}×{rows} 网格")

    def _delete_from_list(self):
        """删除选中图片: 优先使用画布多选(批量), 其次 image_list 单选"""
        if self.canvas.selection:
            self.canvas.delete_selected()

    def _import_spritesheet(self):
        """导入图集并拆分"""
        fp = filedialog.askopenfilename(
            title="选择图集图片",
            filetypes=[("PNG 图片", "*.png"), ("所有图片", "*.png *.bmp *.jpg"),
                       ("所有文件", "*.*")])
        if not fp:
            return
        self._load_spritesheet(Path(fp))

    def _load_spritesheet(self, path: Path):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("错误", f"无法读取图片: {e}")
            return

        self._filepath = str(path)
        self._source_sheet = img  # 保留原图, 方便后续按新参数 “重新拆分”

        # 基于图片尺寸 + 当前 cols/rows/padding 自动计算 cell 大小
        m = self.model
        cols = max(1, int(m.columns))
        rows = max(1, int(m.rows))
        pad = max(0, int(m.padding))
        iw, ih = img.size
        cell_w = max(1, (iw - max(0, cols - 1) * pad) // cols)
        cell_h = max(1, (ih - max(0, rows - 1) * pad) // rows)
        m.cell_width = cell_w
        m.cell_height = cell_h

        # 使用右侧栏参数直接拆分 (取消拆分弹窗)
        m.split_spritesheet(img)
        # 重置路径追踪和选中: 拆分后的帧没有独立源文件路径
        self.image_list._image_paths = []
        self.image_list._path_by_id = {}
        self.image_list._selected_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.settings.refresh_values()  # 回写 cell_w/cell_h 到右栏
        self._on_model_changed()
        self._status_var.set(
            f"已拆分: {path.name} → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _resplit(self):
        """按当前右侧 cols/rows/padding 重新计算 cell 并拆分"""
        img = getattr(self, "_source_sheet", None)
        if img is None:
            messagebox.showinfo("提示", "请先通过《导入拆分》加载一张 Spritesheet")
            return
        if self.model.frame_count > 0:
            if not messagebox.askyesno("确认",
                    "重新拆分将丢弃当前排序和删除, 确定继续吗?"):
                return

        m = self.model
        cols = max(1, int(m.columns))
        rows = max(1, int(m.rows))
        pad = max(0, int(m.padding))
        iw, ih = img.size
        cell_w = max(1, (iw - max(0, cols - 1) * pad) // cols)
        cell_h = max(1, (ih - max(0, rows - 1) * pad) // rows)
        m.cell_width = cell_w
        m.cell_height = cell_h

        m.split_spritesheet(img)
        self.image_list._image_paths = []
        self.image_list._path_by_id = {}
        self.image_list._selected_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.settings.refresh_values()  # 回写 cell_w/cell_h 到右栏
        self._on_model_changed()
        self._status_var.set(
            f"已重新拆分 → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _export_all_frames(self):
        """批量导出每一帧 — 有选中则导出选中, 没有则导出全部"""
        m = self.model
        if m.frame_count == 0:
            messagebox.showinfo("提示", "没有帧数据可导出")
            return
        sel = self.canvas.selection
        if sel:
            indices = sorted(i for i in sel if 0 <= i < len(m.frames) and m.frames[i] is not None)
        else:
            indices = [i for i, f in enumerate(m.frames) if f is not None]
        if not indices:
            messagebox.showinfo("提示", "没有可导出的帧")
            return
        outdir = filedialog.askdirectory(title="选择导出目录")
        if not outdir:
            return
        fmt = self.settings._fmt_var.get()
        alpha_mode = self.settings._alpha_mode_var.get()
        tex_fmt = self.settings._tex_fmt_var.get()
        count = 0
        for idx in indices:
            f = m.get_frame(idx)
            if f is None:
                continue
            try:
                processed = apply_alpha_mode(f, alpha_mode)
                converted = convert_pixel_format(processed, fmt)
                fp = Path(outdir) / f"frame_{idx:03d}.png"
                converted.save(fp, "PNG")
                count += 1
            except Exception as e:
                print(f"导出失败 #{idx}: {e}")
        self._status_var.set(
            f"已导出 {count}/{len(indices)} 帧 → {outdir} ({tex_fmt} / {fmt} / {alpha_mode})")

    # ── 工作模式 / 预览模式 ──────────────────────────────────
    def _apply_workflow_mode(self):
        """应用当前 workflow 模式: 左侧标题 + 按钮启用状态"""
        mode = self._workflow_mode.get()
        if mode == "merge":
            self.image_list.set_title("导入的精灵")
            try:
                self._btn_import_merge.state(["!disabled"])
                self._btn_import_split.state(["disabled"])
            except Exception:
                pass
            # 合并模式: 仅禁用重新拆分
            try: self.settings._btn_resplit.state(["disabled"])
            except Exception: pass
        else:
            self.image_list.set_title("导入的精灵组")
            try:
                self._btn_import_merge.state(["disabled"])
                self._btn_import_split.state(["!disabled"])
            except Exception:
                pass
            # 拆分模式: 启用 重新拆分
            try: self.settings._btn_resplit.state(["!disabled"])
            except Exception: pass

    def _on_workflow_mode_changed(self):
        """工作模式切换: 若有数据则提示用户是否清空"""
        if self.model.frame_count > 0:
            if not messagebox.askyesno("确认",
                    "切换模式将清空当前数据, 确定继续吗?"):
                # 还原变量
                self._workflow_mode.set(
                    "split" if self._workflow_mode.get() == "merge" else "merge")
                return
            # 复用 _new 的清理逻辑, 但跳过二次确认
            self.model = SpriteSheetModel()
            self.canvas.model = self.model
            self.settings.model = self.model
            self.image_list._image_paths.clear()
            self.image_list._path_by_id.clear()
            self.image_list._selected_idx = -1
            self.canvas.selection.clear()
            self.canvas._drag_info = None
            self.canvas._header_drag = None
            self.canvas._last_click_idx = -1
            self.settings.refresh_values()
            self._on_model_changed()
        self._apply_workflow_mode()
        # 切回网格
        self._preview_mode.set("grid")
        self._on_preview_mode_changed()
        self._status_var.set(
            "已切换到组合模式" if self._workflow_mode.get() == "merge"
            else "已切换到拆分模式")

    # ── 共享缩放 (网格/单帧/动画 三模式共用一套控件) ──────
    def _shared_zoom_step(self, delta: float):
        if self._preview_mode.get() == "grid":
            self.canvas.zoom_step(delta)
        else:
            self.preview_view._zoom_step(delta)

    def _shared_zoom_reset(self):
        if self._preview_mode.get() == "grid":
            self.canvas.zoom_reset()
        else:
            self.preview_view._zoom_reset()

    def _on_preview_mode_changed(self):
        """预览模式切换: grid / single / anim"""
        mode = self._preview_mode.get()
        prev_mode = self._prev_display_mode if hasattr(self, '_prev_display_mode') else 'grid'
        self._prev_display_mode = mode

        # 缩放同步: 切换模式时把当前缩放比例带到目标模式
        if prev_mode == "grid" and mode != "grid":
            # grid → preview: 同步 canvas 缩放到 preview
            try:
                self.preview_view._zoom_var.set(self.canvas._zoom)
            except Exception:
                pass
        elif prev_mode != "grid" and mode == "grid":
            # preview → grid: 同步 preview 缩放到 canvas
            try:
                self.canvas.set_zoom(float(self.preview_view._zoom_var.get()))
            except Exception:
                pass

        # 互斥 pack
        self._grid_container.pack_forget()
        self.preview_view.pack_forget()
        if mode == "grid":
            self.preview_view.stop()
            self._grid_container.pack(fill="both", expand=True)
            # 同步缩放标签
            self._zoom_label.config(text=f"{int(self.canvas._zoom * 100)}%")
        else:
            self.preview_view.pack(fill="both", expand=True)
            self.preview_view.set_mode("single" if mode == "single" else "anim")
            self._refresh_inline_preview(keep_idx=False)
            # 同步缩放标签
            try:
                z = float(self.preview_view._zoom_var.get())
                self._zoom_label.config(text=f"{int(z * 100)}%")
            except Exception:
                pass
    def _refresh_inline_preview(self, keep_idx: bool = True):
        """根据当前预览模式 & 范围收集帧, 喂给 InlinePreviewView"""
        mode = self._preview_mode.get()
        if mode == "grid":
            return
        if mode == "single":
            # 单帧: 只显示当前主选中帧 (若无则显示第一帧)
            sel = self.canvas.selection
            if sel:
                idx = self.canvas._last_click_idx
                if idx < 0 or idx not in sel:
                    idx = min(sel)
                frame = self.model.get_frame(idx)
                frames = [frame] if frame is not None else []
            else:
                frames = [f for f in self.model.frames if f is not None][:1]
        else:  # anim
            rng = getattr(self.preview_view, "_range_var", None)
            rng_val = rng.get() if rng is not None else "all"
            if rng_val == "sel" and self.canvas.selection:
                frames = [self.model.get_frame(i)
                          for i in sorted(self.canvas.selection)]
                frames = [f for f in frames if f is not None]
            else:
                frames = [f for f in self.model.frames if f is not None]
        self.preview_view.set_frames(frames, keep_idx=keep_idx)

    def _on_selection_changed(self):
        """供 canvas / image_list 在选中变化时调用"""
        # 同步左侧列表高亮 (canvas 选中 → 左侧列表背景色)
        try:
            self.image_list._refresh_bg()
        except Exception:
            pass
        mode = self._preview_mode.get()
        if mode == "grid":
            return
        # 单帧: 总是刷新; 动画: 仅当范围=选中 时刷新
        if mode == "single":
            self._refresh_inline_preview(keep_idx=False)
        else:
            rng = getattr(self.preview_view, "_range_var", None)
            if rng is not None and rng.get() == "sel":
                self._refresh_inline_preview(keep_idx=False)

    # ── 预览 ────────────────────────────────────────────────
    def _preview_selected(self):
        """预览选中的帧 → 切换到动画模式, 范围=选中"""
        frames = self._get_selected_frames()
        if not frames:
            messagebox.showinfo("提示", "请先在画布上选择要预览的帧\n"
                                        "(点击选择, Ctrl+点击多选, Shift+点击范围选择)")
            return
        try:
            self.preview_view._range_var.set("sel")
        except Exception:
            pass
        self._preview_mode.set("anim")
        self._on_preview_mode_changed()

    def _preview_all(self):
        """预览全部帧 → 切换到动画模式, 范围=全部"""
        self.model.normalize()
        frames = [f for f in self.model.frames if f is not None]
        if not frames:
            messagebox.showinfo("提示", "没有可预览的帧")
            return
        try:
            self.preview_view._range_var.set("all")
        except Exception:
            pass
        self._preview_mode.set("anim")
        self._on_preview_mode_changed()

    def _get_selected_frames(self) -> List[Image.Image]:
        frames = []
        for idx in sorted(self.canvas.selection):
            frame = self.model.get_frame(idx)
            if frame is not None:
                frames.append(frame.copy())
        return frames

    # ── 保存 ─────────────────────────────────────────────────
    def _save(self):
        """保存图集 (使用右侧面板的纹理/像素/Alpha 设置)"""
        self.settings._save_current_fmt()


# ── 导入合并对话框 ──────────────────────────────────────────
class ImportMergeDialog(tk.Toplevel):
    """导入多张图片合并为 Spritesheet 时的参数设置"""

    def __init__(self, parent, image_count: int, images: List[Image.Image]):
        super().__init__(parent)
        self.title("合并图片为 Spritesheet")
        self.images = images
        self.result: Optional[Tuple[int, int, int]] = None  # (cols, rows, padding)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text=f"已选择 {image_count} 张图片", font=("", 10, "bold")).pack(
            padx=16, pady=(16, 8))

        settings = ttk.LabelFrame(self, text="网格参数", padding=8)
        settings.pack(fill="x", padx=16, pady=4)

        # 自动计算建议值
        n = image_count
        suggest_cols = max(1, int(n ** 0.5 + 0.5))
        suggest_rows = (n + suggest_cols - 1) // suggest_cols

        row1 = ttk.Frame(settings)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="列数 (columns):").pack(side="left", padx=4)
        self._cols_var = tk.IntVar(value=suggest_cols)
        ttk.Spinbox(row1, from_=1, to=64, width=6,
                    textvariable=self._cols_var).pack(side="left", padx=4)
        ttk.Label(row1, text="行数 (rows):").pack(side="left", padx=12)
        self._rows_var = tk.IntVar(value=suggest_rows)
        ttk.Spinbox(row1, from_=1, to=64, width=6,
                    textvariable=self._rows_var).pack(side="left", padx=4)

        row2 = ttk.Frame(settings)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="间距 (padding):").pack(side="left", padx=4)
        self._pad_var = tk.IntVar(value=1)
        ttk.Spinbox(row2, from_=0, to=32, width=6,
                    textvariable=self._pad_var).pack(side="left", padx=4)
        ttk.Button(row2, text="自动排列", command=self._auto_arrange).pack(
            side="left", padx=12)

        self._preview_var = tk.StringVar()
        ttk.Label(settings, textvariable=self._preview_var,
                  foreground="#aaaaaa").pack(anchor="w", pady=4)
        self._update_preview()

        for var in [self._cols_var, self._rows_var, self._pad_var]:
            var.trace("w", lambda *a: self._update_preview())

        # 图片尺寸信息
        sizes = set((img.width, img.height) for img in images)
        size_info = ttk.LabelFrame(self, text="图片信息", padding=4)
        size_info.pack(fill="x", padx=16, pady=4)
        if len(sizes) == 1:
            w, h = sizes.pop()
            ttk.Label(size_info, text=f"所有图片尺寸一致: {w}×{h} px").pack(anchor="w")
        else:
            ttk.Label(size_info,
                      text=f"图片尺寸不一致 ({len(sizes)} 种), 将使用最大尺寸").pack(anchor="w")
            max_w = max(img.width for img in images)
            max_h = max(img.height for img in images)
            ttk.Label(size_info, text=f"最大尺寸: {max_w}×{max_h} px").pack(anchor="w")

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=16, pady=16)
        ttk.Button(btn_frame, text="确认合并", command=self._on_ok).pack(
            side="right", padx=4)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side="right", padx=4)

    def _auto_arrange(self):
        n = len(self.images)
        cols = max(1, int(n ** 0.5 + 0.5))
        rows = (n + cols - 1) // cols
        self._cols_var.set(cols)
        self._rows_var.set(rows)

    def _update_preview(self):
        try:
            cols = self._cols_var.get()
            rows = self._rows_var.get()
            total = cols * rows
            n = len(self.images)
            fill = "刚好填满" if total == n else ("多出" if total > n else "不足")
            diff = abs(total - n)
            self._preview_var.set(
                f"网格: {cols}×{rows} = {total} 格, 图片: {n} 张 ({fill} {diff} 格)")
        except Exception:
            self._preview_var.set("参数错误")

    def _on_ok(self):
        self.result = (self._cols_var.get(), self._rows_var.get(),
                       self._pad_var.get())
        self.destroy()


# ── 拆分设置对话框 ──────────────────────────────────────────
class SplitDialog(tk.Toplevel):
    """导入 Spritesheet 时的拆分参数设置"""

    def __init__(self, parent, img: Image.Image):
        super().__init__(parent)
        self.title("拆分设置")
        self.img = img
        self.result: Optional[Tuple[int, int, int, int, int]] = None
        self.transient(parent)
        self.grab_set()

        # 显示原始图片信息
        info = ttk.LabelFrame(self, text="原始图片", padding=8)
        info.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(info, text=f"尺寸: {img.width} x {img.height} px").pack(anchor="w")

        # 参数设置
        settings = ttk.LabelFrame(self, text="拆分参数", padding=8)
        settings.pack(fill="x", padx=16, pady=4)

        row1 = ttk.Frame(settings)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="列数 (cols):").pack(side="left", padx=4)
        self._cols_var = tk.IntVar(value=4)
        ttk.Spinbox(row1, from_=1, to=128, width=6,
                    textvariable=self._cols_var).pack(side="left", padx=4)
        ttk.Label(row1, text="行数 (rows):").pack(side="left", padx=12)
        self._rows_var = tk.IntVar(value=4)
        ttk.Spinbox(row1, from_=1, to=128, width=6,
                    textvariable=self._rows_var).pack(side="left", padx=4)

        row2 = ttk.Frame(settings)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="间距 (padding):").pack(side="left", padx=4)
        self._pad_var = tk.IntVar(value=0)
        ttk.Spinbox(row2, from_=0, to=32, width=6,
                    textvariable=self._pad_var).pack(side="left", padx=4)
        ttk.Button(row2, text="自动计算", command=self._auto_calc).pack(
            side="left", padx=12)

        row3 = ttk.Frame(settings)
        row3.pack(fill="x", pady=3)
        ttk.Label(row3, text="Cell 宽:").pack(side="left", padx=4)
        self._cw_var = tk.IntVar(value=64)
        ttk.Spinbox(row3, from_=1, to=4096, width=6,
                    textvariable=self._cw_var).pack(side="left", padx=4)
        ttk.Label(row3, text="Cell 高:").pack(side="left", padx=12)
        self._ch_var = tk.IntVar(value=64)
        ttk.Spinbox(row3, from_=1, to=4096, width=6,
                    textvariable=self._ch_var).pack(side="left", padx=4)

        self._preview_var = tk.StringVar()
        ttk.Label(settings, textvariable=self._preview_var,
                  foreground="#aaaaaa").pack(anchor="w", pady=4)
        self._update_preview()

        # 实时更新预览
        for var in [self._cols_var, self._rows_var, self._pad_var,
                     self._cw_var, self._ch_var]:
            var.trace("w", lambda *a: self._update_preview())

        # 按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=16, pady=16)
        ttk.Button(btn_frame, text="确认拆分", command=self._on_ok).pack(
            side="right", padx=4)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side="right", padx=4)

    def _auto_calc(self):
        """根据图片尺寸和设置的 cols/rows 自动计算 padding 和 cell size"""
        cols = self._cols_var.get()
        rows = self._rows_var.get()
        if cols <= 0 or rows <= 0:
            return
        w, h = self.img.width, self.img.height
        cw = w // cols
        ch = h // rows
        # 从整除结果推测 padding
        remain_w = w - cw * cols
        remain_h = h - ch * rows
        pad = 0
        if remain_w > 0 and cols > 1:
            pad = remain_w // (cols - 1)
        if remain_h > 0 and rows > 1:
            pad = max(pad, remain_h // (rows - 1))
        self._pad_var.set(min(pad, 32))
        self._cw_var.set(cw)
        self._ch_var.set(ch)

    def _update_preview(self):
        try:
            cols = self._cols_var.get()
            rows = self._rows_var.get()
            pad = self._pad_var.get()
            cw = self._cw_var.get()
            ch = self._ch_var.get()
            total_w = cols * (cw + pad) - pad
            total_h = rows * (ch + pad) - pad
            ok = total_w <= self.img.width and total_h <= self.img.height
            mark = "✓" if ok else "✗"
            self._preview_var.set(
                f"计算结果: {total_w}x{total_h}  {mark}  "
                f"(原图 {self.img.width}x{self.img.height})")
        except Exception:
            self._preview_var.set("参数错误")

    def _on_ok(self):
        self.result = (self._cols_var.get(), self._rows_var.get(),
                       self._pad_var.get(), self._cw_var.get(),
                       self._ch_var.get())
        self.destroy()


# ── 入口 ──────────────────────────────────────────────────────
def main():
    if not HAS_PIL:
        print("错误: 需要安装 Pillow 库")
        print("  pip install Pillow")
        sys.exit(1)

    app = SpriteSheetEditor()
    app.mainloop()


if __name__ == "__main__":
    main()
