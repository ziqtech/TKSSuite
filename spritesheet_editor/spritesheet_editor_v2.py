#!/usr/bin/env python3
"""
Spritesheet Editor v2 - 精灵表编辑器 (PySide6)
================================================
功能:
  1. 导入多张图片, 设置 columns/rows/padding, 拼成 Spritesheet
  2. 按 columns/rows/padding 拆分导入的 Spritesheet
  3. 拖拽调整序列帧顺序 / 整行上下排序 / 整列左右排序
  4. 选中多个帧后预览动画, 也可预览整个 Spritesheet
  5. 导出时选择 PNG 像素格式: RGBA8888 / RGB888 / RGB565 / RGBA4444 / RGBA5551
  6. 深浅色主题切换

用法: python spritesheet_editor_v2.py [spritesheet.png]
"""

from __future__ import annotations
import os, sys, re
from pathlib import Path
from typing import List, Optional, Set, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsItem,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QComboBox, QCheckBox, QRadioButton,
    QGroupBox, QTextEdit, QScrollBar,
    QMenuBar, QMenu, QToolBar, QStatusBar, QDialog, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QButtonGroup,
    QListView, QAbstractItemView, QSlider, QSplitter, QLineEdit, QScrollArea,
)
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QPalette, QColor, QIcon, QAction,
    QKeySequence, QShortcut, QFont, QPen, QBrush, QWheelEvent, QMouseEvent,
    QFontMetrics,
)
from PySide6.QtCore import (
    Qt, QObject, Signal, QTimer, QSize, QRect, QPoint, QRectF, QPointF,
    QMimeData, QEvent, QTranslator,
)

HAS_PIL = False
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.window_theme import apply_godot_theme

# ── 像素格式定义 ──────────────────────────────────────────────
PIXEL_FORMATS: dict[str, str] = {
    "RGBA8888": "32-bit RGBA (8 bits/channel)",
    "RGB888":   "24-bit RGB, no alpha",
    "RGB565":   "16-bit RGB (5R 6G 5B)",
    "RGBA5551": "16-bit RGBA (5R 5G 5B 1A)",
    "RGBA4444": "16-bit RGBA (4 bits/channel)",
    "PNG-8 (256色)": "8-bit 索引调色板 (最多 256 色)",
}

TEXTURE_FORMATS: dict[str, List[str]] = {
    "PNG-32": ["RGBA8888", "RGB888", "RGB565", "RGBA5551", "RGBA4444"],
    "PNG-8":  ["PNG-8 (256色)"],
}

PIXEL_FORMAT_DESC: dict[str, str] = {
    "RGBA8888": "32-bit RGBA，每通道 8 位。完整色彩 + Alpha，最高质量，文件较大。",
    "RGB888":   "24-bit RGB，无 Alpha。不支持透明像素。",
    "RGB565":   "16-bit RGB (5R 6G 5B)。色彩量化，文件更小，无 Alpha。",
    "RGBA5551": "16-bit RGBA (5R 5G 5B 1A)。1 位 Alpha，仅支持透明/不透明。",
    "RGBA4444": "16-bit RGBA，每通道 4 位。色彩 + Alpha 都量化，体积较小。",
    "PNG-8 (256色)": "8-bit 索引调色板，最多 256 色，文件最小，仅支持 1 位透明。",
}

ALPHA_MODES: List[str] = ["无", "清除透明像素", "减少边界伪影", "预乘 Alpha"]

ALPHA_MODE_DESC: dict[str, str] = {
    "无":       "透明像素从精灵复制到精灵表而不做任何更改。如果将其他信息存储在透明像素的颜色值中，请选择此模式以确保不会损坏。",
    "清除透明像素": "透明像素的颜色值设置为 0 (透明黑色)。可以有更好的压缩率。",
    "减少边界伪影": "透明像素获得最邻近的实心像素的颜色值。如果在缩放/旋转后在精灵的边框处观察到黑色阴影，请选择此模式。",
    "预乘 Alpha":   "所有颜色值都与 Alpha 值相乘。某些框架需要这样才能更快地渲染纹理。",
}

HEADER_ROW_H = 28
HEADER_COL_W = 36
DRAG_THRESHOLD = 5
DEFAULT_FPS = 12


class NoWheelComboBox(QComboBox):
    """禁用鼠标滚轮切换选项的 QComboBox，防止误滚改变值"""
    def wheelEvent(self, event: QWheelEvent):
        event.ignore()


# ═══════════════════════════════════════════════════════════════
# PIL 像素格式转换 (原样保留)
# ═══════════════════════════════════════════════════════════════

def _quantize_rgb565(img: Image.Image) -> Image.Image:
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
    img = img.convert("RGBA")
    w, h = img.size
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    try:
        q = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=0)
    except Exception:
        q = rgb.quantize(colors=255)
    q_data = list(q.get_flattened_data())
    a_data = list(alpha.get_flattened_data())
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


# ── Alpha 处理 (原样保留) ─────────────────────────────────────

def _alpha_clear_transparent(img: Image.Image) -> Image.Image:
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
    img = img.convert("RGBA")
    w, h = img.size
    data = list(img.get_flattened_data())
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


# ═══════════════════════════════════════════════════════════════
# PIL → QPixmap 桥接
# ═══════════════════════════════════════════════════════════════

def pil_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    """将 PIL Image 转为 QPixmap (仅用于 UI 显示)

    注意: QImage 通过 bytes 构造时不拷贝数据, 仅持有指针。
    .copy() 确保 QPixmap 深拷贝一份独立内存, 避免 Python GC 回收
    bytes 后 Qt 渲染时访问悬空指针导致段错误。
    """
    if pil_image is None:
        return QPixmap()
    if pil_image.mode not in ("RGBA", "RGB"):
        pil_image = pil_image.convert("RGBA")
    raw_bytes = pil_image.tobytes("raw", "RGBA" if pil_image.mode == "RGBA" else "RGB")
    fmt = QImage.Format_RGBA8888 if pil_image.mode == "RGBA" else QImage.Format_RGB888
    qim = QImage(raw_bytes, pil_image.width, pil_image.height, fmt).copy()
    return QPixmap.fromImage(qim)



# ═══════════════════════════════════════════════════════════════
# 数据模型 (QObject + Signal)
# ═══════════════════════════════════════════════════════════════

class SpriteSheetModel(QObject):
    """精灵表数据模型 — 纯数据, 不包含 UI"""

    model_changed = Signal()

    def __init__(self):
        super().__init__()
        self.frames: List[Optional[Image.Image]] = []
        self.columns: int = 7
        self.rows: int = 4
        self.padding: int = 1
        self.cell_width: int = 64
        self.cell_height: int = 64
        self._cell_size_set: bool = False  # 用户是否手动设定过 cell 宽高
        # 像素调节：保存原图和累积缩放比例
        self._original_frames: dict[int, Image.Image] = {}
        self._scale_factors: dict[int, tuple[float, float]] = {}

    @property
    def total_cells(self) -> int:
        return self.columns * self.rows

    @property
    def frame_count(self) -> int:
        return sum(1 for f in self.frames if f is not None)

    def normalize(self) -> None:
        total = self.total_cells
        while len(self.frames) < total:
            self.frames.append(None)
        self.frames = self.frames[:total]

    def auto_detect_cell_size(self) -> None:
        valid = [f for f in self.frames if f is not None]
        if valid:
            self.cell_width = max(f.width for f in valid)
            self.cell_height = max(f.height for f in valid)

    def build_spritesheet(self) -> Image.Image:
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
            fw, fh = frame.size
            if fw == self.cell_width and fh == self.cell_height:
                display = frame
            else:
                # 帧与 cell 尺寸不一致时居中粘贴（不 resize），保持像素缩放效果
                display = Image.new("RGBA", (self.cell_width, self.cell_height), (0, 0, 0, 0))
                ox = (self.cell_width - fw) // 2
                oy = (self.cell_height - fh) // 2
                display.paste(frame, (ox, oy), frame if frame.mode == "RGBA" else None)
            ss.paste(display, (x, y), display if display.mode == "RGBA" else None)
        return ss

    def split_spritesheet(self, img: Image.Image) -> None:
        if self.columns <= 0 or self.rows <= 0:
            return
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
        self.model_changed.emit()

    def swap_frames(self, idx_a: int, idx_b: int) -> None:
        self.normalize()
        n = len(self.frames)
        if 0 <= idx_a < n and 0 <= idx_b < n:
            self.frames[idx_a], self.frames[idx_b] = self.frames[idx_b], self.frames[idx_a]
            self.model_changed.emit()

    def move_frame(self, src: int, dst: int) -> None:
        """将帧从 src 位置移动到 dst (pop+insert 语义)"""
        self.normalize()
        n = len(self.frames)
        if not (0 <= src < n) or self.frames[src] is None:
            return
        frame = self.frames.pop(src)
        dst_adj = dst if dst <= src else dst - 1
        dst_adj = max(0, min(dst_adj, len(self.frames)))
        self.frames.insert(dst_adj, frame)
        self.model_changed.emit()

    def swap_rows(self, r1: int, r2: int) -> None:
        self.normalize()
        cols = self.columns
        if not (0 <= r1 < self.rows and 0 <= r2 < self.rows):
            return
        for c in range(cols):
            i1, i2 = r1 * cols + c, r2 * cols + c
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]
        self.model_changed.emit()

    def swap_cols(self, c1: int, c2: int) -> None:
        self.normalize()
        cols, rows = self.columns, self.rows
        if not (0 <= c1 < cols and 0 <= c2 < cols):
            return
        for r in range(rows):
            i1, i2 = r * cols + c1, r * cols + c2
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]
        self.model_changed.emit()

    def copy_row(self, row_idx: int) -> None:
        self.normalize()
        if not (0 <= row_idx < self.rows):
            return
        cols = self.columns
        start = row_idx * cols
        end = start + cols
        copied = []
        for i in range(start, end):
            frame = self.frames[i]
            copied.append(frame.copy() if frame is not None else None)
        insert_pos = (row_idx + 1) * cols
        self.frames[insert_pos:insert_pos] = copied
        self.rows += 1
        self.model_changed.emit()

    def get_frame(self, idx: int) -> Optional[Image.Image]:
        self.normalize()
        if 0 <= idx < len(self.frames):
            return self.frames[idx]
        return None


# ═══════════════════════════════════════════════════════════════
# 左侧图片列表 (QListWidget)
# ═══════════════════════════════════════════════════════════════

class ImageListWidget(QListWidget):
    """左侧面板: 精灵列表, 原生支持多选与拖拽排序"""

    selectionChangedCustom = Signal()
    THUMB_SZ = 64

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self._image_paths: List[str] = []
        self._path_by_id: dict = {}
        self._selected_idx: int = -1
        self._anchor_idx: int = -1
        self._drag_src_mi: int = -1
        self._suppress_change: bool = False

        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(self.THUMB_SZ, self.THUMB_SZ))
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setMinimumWidth(220)

    # ── 数据入口 ───────────────────────
    def clear_all(self):
        if self.editor.model.frame_count > 0:
            if not self._ask_confirm("确认", "确定清空所有已导入的图片?"):
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
        self._rebuild(self.editor.model.frames)

    # ── 重建列表 ──────────────────────
    def _rebuild(self, frames: List[Optional[Image.Image]]):
        self._suppress_change = True
        self.clear()
        for mi, img in enumerate(frames):
            if img is None:
                continue
            pixmap = pil_to_qpixmap(img)
            # 生成缩略图
            if pixmap.width() > self.THUMB_SZ or pixmap.height() > self.THUMB_SZ:
                pixmap = pixmap.scaled(self.THUMB_SZ, self.THUMB_SZ,
                                       Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)

            raw_path = self._path_by_id.get(id(img), "")
            name = Path(raw_path).name if raw_path else f"#{mi}"
            display = name if len(name) <= 22 else name[:20] + "..."

            item = QListWidgetItem(QIcon(pixmap), display)
            item.setData(Qt.UserRole, mi)  # 存储模型索引
            item.setSizeHint(QSize(self.THUMB_SZ + 16, self.THUMB_SZ + 20))
            self.addItem(item)
        self._suppress_change = False
        self._refresh_highlight()

    def _refresh_highlight(self):
        """根据画布选中状态刷新列表高亮"""
        sel = self.editor.canvas.selection
        self._suppress_change = True
        for i in range(self.count()):
            item = self.item(i)
            mi = item.data(Qt.UserRole)
            if mi in sel:
                item.setSelected(True)
            else:
                item.setSelected(False)
        self._suppress_change = False

    def refresh_values(self):
        """模型变更后刷新列表"""
        current = self.editor.model.frames
        self._rebuild(current)

    # ── 选中同步 ──────────────────────
    def _on_item_clicked(self, item: QListWidgetItem):
        if self._suppress_change:
            return
        mi = item.data(Qt.UserRole)
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.ControlModifier:
            sel = set(self.editor.canvas.selection)
            if mi in sel:
                sel.discard(mi)
            else:
                sel.add(mi)
            primary = mi if mi in sel else (max(sel) if sel else -1)
            self._apply_canvas_selection(sel, primary)
        elif modifiers & Qt.ShiftModifier:
            anchor = self._anchor_idx if self._anchor_idx >= 0 else mi
            lo, hi = min(anchor, mi), max(anchor, mi)
            # 收集范围内所有非空帧索引
            sel = set()
            for i in range(lo, hi + 1):
                if 0 <= i < len(self.editor.model.frames) and self.editor.model.frames[i] is not None:
                    sel.add(i)
            self._apply_canvas_selection(sel, mi)
        else:
            # 普通点击: 若仅选中此项 → 取消选中; 否则单选此项
            sel = set(self.editor.canvas.selection)
            if sel == {mi}:
                self._anchor_idx = -1
                self._drag_src_mi = -1
                self._apply_canvas_selection(set(), -1)
            else:
                self._anchor_idx = mi
                self._apply_canvas_selection({mi}, mi)

    def _apply_canvas_selection(self, sel: Set[int], primary: int):
        self.editor.canvas.selection = sel
        self.editor.canvas._last_click_idx = primary
        self._selected_idx = primary
        self.editor.canvas.update_selection_display()
        self._refresh_highlight()
        self.selectionChangedCustom.emit()

    # ── 拖拽排序支持 ──────────────────
    def startDrag(self, supportedActions):
        """记录拖拽源"""
        item = self.currentItem()
        if item:
            self._drag_src_mi = item.data(Qt.UserRole)
        super().startDrag(supportedActions)

    def dropEvent(self, event):
        """重写 dropEvent 以同步模型帧顺序 — 委托 model.move_frame()"""
        src_mi = self._drag_src_mi
        self._drag_src_mi = -1

        # 在 super().dropEvent() 之前获取目标 (避免视觉重排干扰)
        drop_pos = event.position().toPoint()
        target_item = self.itemAt(drop_pos)
        dst_mi = target_item.data(Qt.UserRole) if target_item else -1

        super().dropEvent(event)

        if src_mi < 0 or dst_mi < 0 or src_mi == dst_mi:
            return

        # Model 统一处理 move + emit signal → editor._on_model_changed()
        self.editor.model.move_frame(src_mi, dst_mi)

        dst_adj = dst_mi if dst_mi <= src_mi else dst_mi - 1
        dst_adj = max(0, min(dst_adj, len(self.editor.model.frames) - 1))
        self._selected_idx = dst_adj
        self._anchor_idx = dst_adj
        self.editor.canvas.selection = {dst_adj}
        self.editor.canvas._last_click_idx = dst_adj
        # _on_model_changed 由 model_changed signal → editor 自动触发

    # ── 公共 API ──────────────────────
    def selected_image_idx(self) -> int:
        return self._selected_idx

    def remove_selected(self) -> bool:
        if self._selected_idx < 0:
            return False
        frames = self.editor.model.frames
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

    def _ask_confirm(self, title: str, msg: str) -> bool:
        return QMessageBox.question(self, title, msg) == QMessageBox.Yes



# ═══════════════════════════════════════════════════════════════
# 主画布 (QGraphicsView + QGraphicsScene)
# ═══════════════════════════════════════════════════════════════

class SpriteGraphicsView(QGraphicsView):
    """精灵表画布: 显示网格, 支持拖拽排序, 多选"""

    selectionChangedCustom = Signal()

    def __init__(self, model: SpriteSheetModel, editor):
        super().__init__()
        self.model = model
        self.editor = editor
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setBackgroundBrush(QBrush(QColor("#3a3a3a")))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)

        self.selection: Set[int] = set()
        self._drag_info: Optional[dict] = None
        self._header_drag: Optional[tuple] = None
        self._last_click_idx: int = -1
        self._zoom: float = 1.0

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

    # ── 缩放 ───────────────────────────
    def set_zoom(self, z: float) -> None:
        z = max(0.5, min(5.0, float(z)))
        if abs(z - self._zoom) < 0.001:
            return
        factor = z / self._zoom
        self.scale(factor, factor)
        self._zoom = z
        try:
            self.editor._zoom_label.setText(f"{int(z * 100)}%")
        except Exception:
            pass

    def zoom_step(self, delta: float) -> None:
        self.set_zoom(self._zoom + delta)

    def zoom_reset(self) -> None:
        self.set_zoom(1.0)

    # ── 坐标计算 (逻辑坐标, 不经缩放) ──
    def _cell_bbox(self, row: int, col: int) -> Tuple[int, int, int, int]:
        m = self.model
        x = HEADER_COL_W + col * (m.cell_width + m.padding)
        y = HEADER_ROW_H + row * (m.cell_height + m.padding)
        return x, y, x + m.cell_width, y + m.cell_height

    def _row_header_bbox(self, row: int) -> Tuple[int, int, int, int]:
        _, y, _, _ = self._cell_bbox(row, 0)
        return 0, y, HEADER_COL_W, y + self.model.cell_height

    def _col_header_bbox(self, col: int) -> Tuple[int, int, int, int]:
        x, _, _, _ = self._cell_bbox(0, col)
        return x, 0, x + self.model.cell_width, HEADER_ROW_H

    def _total_size(self) -> Tuple[int, int]:
        m = self.model
        w = HEADER_COL_W + m.columns * (m.cell_width + m.padding) - m.padding
        h = HEADER_ROW_H + m.rows * (m.cell_height + m.padding) - m.padding
        return max(w, 100), max(h, 100)

    def _idx_at_pos(self, x: float, y: float) -> int:
        m = self.model
        col = int((x - HEADER_COL_W) // (m.cell_width + m.padding))
        row = int((y - HEADER_ROW_H) // (m.cell_height + m.padding))
        cx = x - HEADER_COL_W - col * (m.cell_width + m.padding)
        cy = y - HEADER_ROW_H - row * (m.cell_height + m.padding)
        if 0 <= row < m.rows and 0 <= col < m.columns and cx < m.cell_width and cy < m.cell_height:
            return row * m.columns + col
        return -1

    def _header_at_pos(self, x: float, y: float) -> Optional[Tuple[str, int]]:
        m = self.model
        if x < HEADER_COL_W and y >= HEADER_ROW_H:
            row = int((y - HEADER_ROW_H) // (m.cell_height + m.padding))
            cy = y - HEADER_ROW_H - row * (m.cell_height + m.padding)
            if 0 <= row < m.rows and cy < m.cell_height:
                return ("row", row)
        if y < HEADER_ROW_H and x >= HEADER_COL_W:
            col = int((x - HEADER_COL_W) // (m.cell_width + m.padding))
            cx = x - HEADER_COL_W - col * (m.cell_width + m.padding)
            if 0 <= col < m.columns and cx < m.cell_width:
                return ("col", col)
        return None

    def _row_at_y(self, y: float) -> int:
        m = self.model
        ri = int((y - HEADER_ROW_H) // (m.cell_height + m.padding))
        ry = y - HEADER_ROW_H - ri * (m.cell_height + m.padding)
        if 0 <= ri < m.rows and 0 <= ry < m.cell_height:
            return ri
        return -1

    def _col_at_x(self, x: float) -> int:
        m = self.model
        ci = int((x - HEADER_COL_W) // (m.cell_width + m.padding))
        cx = x - HEADER_COL_W - ci * (m.cell_width + m.padding)
        if 0 <= ci < m.columns and 0 <= cx < m.cell_width:
            return ci
        return -1

    # ── 绘制 ───────────────────────────
    def redraw(self) -> None:
        self.scene.clear()
        m = self.model
        m.normalize()
        tw, th = self._total_size()
        self.scene.setSceneRect(0, 0, tw, th)

        cols, rows = m.columns, m.rows
        cw, ch, pad = m.cell_width, m.cell_height, m.padding

        # 背景
        bg = QGraphicsRectItem(0, 0, tw, th)
        bg.setBrush(QBrush(QColor("#3a3a3a")))
        bg.setPen(QPen(Qt.NoPen))
        self.scene.addItem(bg)

        # 帧
        for i, frame in enumerate(m.frames):
            r, c = divmod(i, cols)
            x, y, x2, y2 = self._cell_bbox(r, c)

            # 单元格背景
            fill = QColor("#4a4a4a") if i % 2 == 0 else QColor("#444444")
            if i in self.selection:
                fill = QColor("#5a6a8a")
            cell_bg = QGraphicsRectItem(x, y, cw, ch)
            cell_bg.setBrush(QBrush(fill))
            cell_bg.setPen(QPen(QColor("#555555")))
            cell_bg.setData(0, i)  # 存储帧索引
            self.scene.addItem(cell_bg)

            if frame is not None:
                try:
                    fw, fh = frame.size
                    if fw == cw and fh == ch:
                        display = frame
                    else:
                        # 帧小于cell时居中，大于cell时锚定左上角
                        display = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                        ox = (cw - fw) // 2 if fw <= cw else 0
                        oy = (ch - fh) // 2 if fh <= ch else 0
                        display.paste(frame, (ox, oy), frame if frame.mode == "RGBA" else None)
                    pixmap = pil_to_qpixmap(display)
                    pix_item = QGraphicsPixmapItem(pixmap)
                    pix_item.setPos(x, y)
                    pix_item.setData(0, i)
                    self.scene.addItem(pix_item)
                except Exception:
                    pass
            else:
                # 空帧 X 标记
                line1 = self.scene.addLine(x, y, x2, y2, QPen(QColor("#555555")))
                line2 = self.scene.addLine(x2, y, x, y2, QPen(QColor("#555555")))
                line1.setData(0, i)
                line2.setData(0, i)

            # 序号
            txt = QGraphicsTextItem(str(i))
            txt.setPos(x + 2, y + 1)
            txt.setDefaultTextColor(QColor("#cccccc"))
            font = QFont()
            font.setPixelSize(9)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 选中边框
        for idx in self.selection:
            r, c = divmod(idx, cols)
            x, y, _, _ = self._cell_bbox(r, c)
            border = QGraphicsRectItem(x, y, cw, ch)
            border.setPen(QPen(QColor("#80c0ff"), 2))
            border.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(border)

        # 单选时高亮整行/整列
        if len(self.selection) == 1:
            sel_idx = next(iter(self.selection))
            sr, sc = divmod(sel_idx, cols)
            tw2, th2 = self._total_size()

            # 行高亮
            ry = HEADER_ROW_H + sr * (ch + pad)
            rh = QGraphicsRectItem(HEADER_COL_W, ry, tw2 - HEADER_COL_W, ch)
            rh.setPen(QPen(QColor("#a0d0ff"), 1, Qt.DashLine))
            rh.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(rh)

            # 列高亮
            cx = HEADER_COL_W + sc * (cw + pad)
            chl = QGraphicsRectItem(cx, HEADER_ROW_H, cw, th2 - HEADER_ROW_H)
            chl.setPen(QPen(QColor("#a0d0ff"), 1, Qt.DashLine))
            chl.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(chl)

            # 行头高亮
            rhx, rhy, rhx2, rhy2 = self._row_header_bbox(sr)
            rhh = QGraphicsRectItem(rhx, rhy, rhx2 - rhx, rhy2 - rhy)
            rhh.setBrush(QBrush(QColor("#607080")))
            rhh.setPen(QPen(QColor("#80c0ff")))
            self.scene.addItem(rhh)

            # 列头高亮
            chx, chy, chx2, chy2 = self._col_header_bbox(sc)
            chh = QGraphicsRectItem(chx, chy, chx2 - chx, chy2 - chy)
            chh.setBrush(QBrush(QColor("#607080")))
            chh.setPen(QPen(QColor("#80c0ff")))
            self.scene.addItem(chh)

        # 行头
        for r in range(rows):
            x, y, x2, y2 = self._row_header_bbox(r)
            hdr_fill = QColor("#505050") if (self._header_drag and self._header_drag[0] == "row"
                        and self._header_drag[1] == r) else QColor("#404040")
            hdr = QGraphicsRectItem(x, y, x2 - x, y2 - y)
            hdr.setBrush(QBrush(hdr_fill))
            hdr.setPen(QPen(QColor("#606060")))
            self.scene.addItem(hdr)
            txt = QGraphicsTextItem(f"R{r}")
            txt.setPos(x + HEADER_COL_W // 2 - 10, y + (ch) // 2 - 8)
            txt.setDefaultTextColor(QColor("#aaaaaa"))
            font = QFont()
            font.setPixelSize(10)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 列头
        for c in range(cols):
            x, y, x2, y2 = self._col_header_bbox(c)
            hdr_fill = QColor("#505050") if (self._header_drag and self._header_drag[0] == "col"
                        and self._header_drag[1] == c) else QColor("#404040")
            hdr = QGraphicsRectItem(x, y, x2 - x, y2 - y)
            hdr.setBrush(QBrush(hdr_fill))
            hdr.setPen(QPen(QColor("#606060")))
            self.scene.addItem(hdr)
            txt = QGraphicsTextItem(f"C{c}")
            txt.setPos(x + cw // 2 - 10, y + HEADER_ROW_H // 2 - 8)
            txt.setDefaultTextColor(QColor("#aaaaaa"))
            font = QFont()
            font.setPixelSize(10)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 左上角
        corner = QGraphicsRectItem(0, 0, HEADER_COL_W, HEADER_ROW_H)
        corner.setBrush(QBrush(QColor("#303030")))
        corner.setPen(QPen(QColor("#606060")))
        self.scene.addItem(corner)

    # ── 鼠标事件 ───────────────────────
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        pos = self.mapToScene(event.position().toPoint())
        x, y = pos.x(), pos.y()
        modifiers = event.modifiers()

        # 检测 header 点击
        if not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier)):
            hdr = self._header_at_pos(x, y)
            if hdr:
                self._header_drag = (hdr[0], hdr[1], x, y)
                self.redraw()
                return

        idx = self._idx_at_pos(x, y)

        # Ctrl+点击: 切换选中
        if modifiers & Qt.ControlModifier:
            if idx >= 0:
                if idx in self.selection:
                    self.selection.discard(idx)
                else:
                    self.selection.add(idx)
                self._last_click_idx = idx
                if hasattr(self.editor, "image_list"):
                    if self.selection:
                        primary = idx if idx in self.selection else min(self.selection)
                        self.editor.image_list._selected_idx = primary
                    else:
                        self.editor.image_list._selected_idx = -1
                self.update_selection_display()
                self.selectionChangedCustom.emit()
            return

        # Shift+点击: 范围选中
        if modifiers & Qt.ShiftModifier:
            if idx >= 0 and self._last_click_idx >= 0:
                lo, hi = min(self._last_click_idx, idx), max(self._last_click_idx, idx)
                self.selection = set(range(lo, hi + 1))
                if hasattr(self.editor, "image_list"):
                    self.editor.image_list._selected_idx = idx
                self.update_selection_display()
                self.selectionChangedCustom.emit()
            return

        # 普通点击
        if idx < 0:
            if self.selection:
                self.selection.clear()
                if hasattr(self.editor, "image_list"):
                    self.editor.image_list._selected_idx = -1
                self.update_selection_display()
                self.selectionChangedCustom.emit()
            return

        self._drag_info = {"from_idx": idx, "start_x": x, "start_y": y, "moved": False}
        self._last_click_idx = idx
        if idx not in self.selection:
            self.selection = {idx}
        if hasattr(self.editor, "image_list"):
            self.editor.image_list._selected_idx = idx
        self.update_selection_display()
        self.selectionChangedCustom.emit()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = self.mapToScene(event.position().toPoint())
        x, y = pos.x(), pos.y()

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
            self._drag_info["from_idx"] = self._drag_info.get("from_idx", self._last_click_idx)
        if self._drag_info["moved"]:
            self._show_frame_drag_indicator(x, y)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        pos = self.mapToScene(event.position().toPoint())
        x, y = pos.x(), pos.y()

        # Header 释放
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
                    if hasattr(self.editor, "image_list"):
                        self.editor.image_list._selected_idx = to_idx
                    self._drag_info = None
                    self.editor._on_model_changed()
                    return
            self._drag_info = None
            self.update_selection_display()

    def _show_frame_drag_indicator(self, cx: float, cy: float) -> None:
        self._remove_temp_items("drag_tgt")
        to_idx = self._idx_at_pos(cx, cy)
        if to_idx >= 0:
            r, c = divmod(to_idx, self.model.columns)
            x, y, x2, y2 = self._cell_bbox(r, c)
            pen = QPen(QColor("#ffcc00"), 2, Qt.DashLine)
            rect = QGraphicsRectItem(x, y, x2 - x, y2 - y)
            rect.setPen(pen)
            rect.setBrush(QBrush(Qt.NoBrush))
            rect.setData(0, "drag_tgt")
            self.scene.addItem(rect)

    def _show_header_drag_indicator(self, hdr_type: str, hdr_idx: int,
                                     cx: float, cy: float) -> None:
        self._remove_temp_items("hdr_tgt")
        if hdr_type == "row":
            target = self._row_at_y(cy)
            if target >= 0 and target != hdr_idx:
                _, y, _, y2 = self._row_header_bbox(target)
                tw = self._total_size()[0]
                pen = QPen(QColor("#ffcc00"), 2, Qt.DashLine)
                rect = QGraphicsRectItem(0, y, tw, y2 - y)
                rect.setPen(pen)
                rect.setBrush(QBrush(Qt.NoBrush))
                rect.setData(0, "hdr_tgt")
                self.scene.addItem(rect)
        else:
            target = self._col_at_x(cx)
            if target >= 0 and target != hdr_idx:
                x, _, x2, _ = self._col_header_bbox(target)
                th = self._total_size()[1]
                pen = QPen(QColor("#ffcc00"), 2, Qt.DashLine)
                rect = QGraphicsRectItem(x, 0, x2 - x, th)
                rect.setPen(pen)
                rect.setBrush(QBrush(Qt.NoBrush))
                rect.setData(0, "hdr_tgt")
                self.scene.addItem(rect)

    def _remove_temp_items(self, tag: str) -> None:
        for item in self.scene.items():
            if item.data(0) == tag:
                self.scene.removeItem(item)

    # ── 增量选中更新 (避免全量重绘) ──────
    def update_selection_display(self) -> None:
        """仅更新选中高亮和行列指示线, 不重建图片图元 — O(n) 替代 O(n×PIL)"""
        m = self.model
        cols = m.columns
        cw, ch = m.cell_width, m.cell_height

        # 遍历场景图元, 区分背景 / 图片 / 选中边框并更新
        for item in self.scene.items():
            data = item.data(0)
            if not isinstance(data, int):
                continue
            idx = data
            # 单元格背景: QGraphicsRectItem, 无边框或边框色 #555555
            if isinstance(item, QGraphicsRectItem):
                pen_color = item.pen().color().name()
                # 跳过选中边框 (#80c0ff) / 行高亮 / 列高亮 / header 等
                if pen_color in ("#80c0ff", "#a0d0ff", "#606060", "#ffcc00"):
                    continue
                if pen_color == "#555555" or item.pen().style() == Qt.NoPen:
                    r, c = divmod(idx, cols)
                    fill = QColor("#5a6a8a") if idx in self.selection else (
                        QColor("#4a4a4a") if idx % 2 == 0 else QColor("#444444"))
                    item.setBrush(QBrush(fill))

        # 选中边框 → 删除旧的, 按需重建 (轻量)
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsRectItem) and item.pen().color().name() == "#80c0ff":
                self.scene.removeItem(item)
        # 行/列高亮 → 删除旧的
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsRectItem) and item.pen().color().name() == "#a0d0ff":
                self.scene.removeItem(item)

        # 重建选中边框
        for idx in self.selection:
            r, c = divmod(idx, cols)
            x = HEADER_COL_W + c * (cw + m.padding)
            y = HEADER_ROW_H + r * (ch + m.padding)
            border = QGraphicsRectItem(x, y, cw, ch)
            border.setPen(QPen(QColor("#80c0ff"), 2))
            border.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(border)

        # 单选时高亮整行/整列 (轻量)
        if len(self.selection) == 1:
            sel_idx = next(iter(self.selection))
            sr, sc = divmod(sel_idx, cols)
            tw, th = self._total_size()

            ry = HEADER_ROW_H + sr * (ch + m.padding)
            rh = QGraphicsRectItem(HEADER_COL_W, ry, tw - HEADER_COL_W, ch)
            rh.setPen(QPen(QColor("#a0d0ff"), 1, Qt.DashLine))
            rh.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(rh)

            cx = HEADER_COL_W + sc * (cw + m.padding)
            chl = QGraphicsRectItem(cx, HEADER_ROW_H, cw, th - HEADER_ROW_H)
            chl.setPen(QPen(QColor("#a0d0ff"), 1, Qt.DashLine))
            chl.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(chl)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            step = 0.25 if delta > 0 else -0.25
            self.zoom_step(step)
            event.accept()
        elif event.modifiers() & Qt.ShiftModifier:
            # Shift+滚轮 = 水平滚动
            delta = event.angleDelta().y()
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - delta)
        else:
            super().wheelEvent(event)

    # ── 公开方法 ───────────────────────
    def update_model(self) -> None:
        self.selection.clear()
        self.redraw()

    def select_all(self) -> None:
        self.model.normalize()
        self.selection = set(range(len(self.model.frames)))
        self.update_selection_display()

    def select_none(self) -> None:
        self.selection.clear()
        self.update_selection_display()

    def delete_selected(self) -> None:
        for idx in list(self.selection):
            if 0 <= idx < len(self.model.frames):
                self.model.frames[idx] = None
        self.selection.clear()
        self.editor._on_model_changed()
        self.redraw()

    def move_selected_left(self) -> None:
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
        cols = max(1, int(self.model.columns))
        moved = []
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
        cols = max(1, int(self.model.columns))
        total = len(self.model.frames)
        moved = []
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


# ═══════════════════════════════════════════════════════════════
# 时间轴小组件 (QWidget + paintEvent)
# ═══════════════════════════════════════════════════════════════

class TimelineWidget(QWidget):
    """动画时间轴: 缩略图 + 高亮当前帧, 支持点击跳转"""

    clicked = Signal(int)

    def __init__(self):
        super().__init__()
        self._frames: List[Image.Image] = []
        self._thumbs: List[QPixmap] = []
        self._current: int = 0
        self._cell: int = 44
        self._gap: int = 2
        self.setMinimumHeight(self._cell + 14)
        self.setMaximumHeight(self._cell + 20)
        self.setMouseTracking(True)

    def set_frames(self, frames: List[Image.Image]):
        self._frames = frames
        self._thumbs.clear()
        for f in frames:
            ratio = min(self._cell / max(f.width, 1), self._cell / max(f.height, 1))
            tw = max(1, int(f.width * ratio))
            th = max(1, int(f.height * ratio))
            thumb = f.resize((tw, th), Image.NEAREST)
            self._thumbs.append(pil_to_qpixmap(thumb))
        total_w = 4 + len(frames) * (self._cell + self._gap) + 4
        self.setMinimumWidth(total_w)
        self.resize(total_w, self.height())
        self.update()

    def set_current(self, idx: int):
        if 0 <= idx < len(self._frames):
            self._current = idx
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        n = len(self._frames)
        if n == 0:
            return

        sz, gap = self._cell, self._gap
        y0 = 6

        # 绘制可见范围的缩略图
        for i in range(n):
            x0 = 4 + i * (sz + gap)
            # 只绘制可见部分
            if x0 + sz < 0 or x0 > self.width():
                continue

            # 背景
            if i == self._current:
                painter.setPen(QPen(QColor("#ffcc00"), 2))
                painter.setBrush(QBrush(QColor("#3a3a3a")))
                painter.drawRect(x0 - 1, y0 - 1, sz + 2, sz + 2)
            else:
                painter.setPen(QPen(QColor("#555555")))
                painter.setBrush(QBrush(QColor("#2a2a2a")))
                painter.drawRect(x0, y0, sz, sz)

            # 缩略图
            if i < len(self._thumbs):
                pm = self._thumbs[i]
                px = x0 + (sz - pm.width()) // 2
                py = y0 + (sz - pm.height()) // 2
                painter.drawPixmap(px, py, pm)

            # 序号
            painter.setPen(QColor("#cccccc"))
            font = QFont()
            font.setPixelSize(9)
            painter.setFont(font)
            painter.drawText(x0 + 2, y0 + 1, sz - 4, 12, Qt.AlignLeft, str(i))

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().toPoint().x()
            sz, gap = self._cell, self._gap
            idx = (x - 4) // (sz + gap)
            if 0 <= idx < len(self._frames):
                self.clicked.emit(idx)


# ═══════════════════════════════════════════════════════════════
# 预览视图
# ═══════════════════════════════════════════════════════════════

class PreviewView(QWidget):
    """中间区域的内嵌预览 — 单帧/动画两种模式"""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self._frames: List[Image.Image] = []
        self._current: int = 0
        self._playing: bool = False
        self._direction: int = 1
        self._mode: str = "single"
        self._zoom: float = 1.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)

        self._build()

    def wheelEvent(self, event: QWheelEvent):
        """Ctrl+滚轮 = 缩放"""
        if event.modifiers() & Qt.ControlModifier:
            delta = 0.25 if event.angleDelta().y() > 0 else -0.25
            self.zoom_step(delta)
            event.accept()
        else:
            super().wheelEvent(event)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # ── 控制栏 ──
        ctrl = QHBoxLayout()

        self._btn_play = QPushButton("▶ 播放")
        self._btn_play.setProperty("class", "CompactBtn")
        self._btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self._btn_play)

        for text, slot in [("⏮", self._go_first), ("◀", self._prev_frame),
                            ("▶", self._next_frame), ("⏭", self._go_last)]:
            btn = QPushButton(text)
            btn.setProperty("class", "CompactBtn")
            btn.clicked.connect(slot)
            ctrl.addWidget(btn)

        ctrl.addSpacing(12)
        ctrl.addWidget(QLabel("FPS:"))

        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(1, 120)
        self._fps_spin.setValue(DEFAULT_FPS)
        self._fps_spin.setFixedWidth(50)
        self._fps_spin.valueChanged.connect(self._on_fps_change)
        ctrl.addWidget(self._fps_spin)

        self._loop_cb = QCheckBox("循环")
        self._loop_cb.setChecked(True)
        ctrl.addWidget(self._loop_cb)

        self._pingpong_cb = QCheckBox("往返")
        ctrl.addWidget(self._pingpong_cb)

        ctrl.addSpacing(8)
        ctrl.addWidget(QLabel("范围:"))

        self._range_all = QRadioButton("全部")
        self._range_all.setChecked(True)
        self._range_sel = QRadioButton("选中")
        self._range_all.toggled.connect(self._on_range_change)
        ctrl.addWidget(self._range_all)
        ctrl.addWidget(self._range_sel)

        ctrl.addStretch()
        self._counter_label = QLabel("0/0")
        self._counter_label.setFixedWidth(60)
        ctrl.addWidget(self._counter_label)

        layout.addLayout(ctrl)

        # ── 显示区 ──
        self._disp = QLabel()
        self._disp.setAlignment(Qt.AlignCenter)
        self._disp.setObjectName("GamePreview")
        self._disp.setMinimumSize(200, 150)
        self._disp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._disp.setScaledContents(False)
        layout.addWidget(self._disp, 1)

        # ── 时间轴 ── (水平滚动, 避免帧数多时 setMinimumWidth 撑爆父布局)
        self._timeline = TimelineWidget()
        self._timeline.clicked.connect(self._on_timeline_click)
        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidget(self._timeline)
        self._timeline_scroll.setWidgetResizable(False)
        self._timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._timeline_scroll.setVisible(False)
        layout.addWidget(self._timeline_scroll)

        # ── 进度条 ──
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderMoved.connect(self._on_slider)
        layout.addWidget(self._slider)

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "single":
            self.stop()
            self._btn_play.setEnabled(False)
            self._loop_cb.setEnabled(False)
            self._pingpong_cb.setEnabled(False)
            self._range_all.setEnabled(False)
            self._range_sel.setEnabled(False)
            self._timeline_scroll.setVisible(False)
        else:
            self._btn_play.setEnabled(True)
            self._loop_cb.setEnabled(True)
            self._pingpong_cb.setEnabled(True)
            self._range_all.setEnabled(True)
            self._range_sel.setEnabled(True)
            self._timeline_scroll.setVisible(True)

    def set_frames(self, frames: List[Image.Image], keep_idx: bool = True):
        old_idx = self._current
        self._frames = [f for f in frames if f is not None]
        n = len(self._frames)
        if n == 0:
            self._current = 0
        elif keep_idx:
            self._current = min(old_idx, n - 1)
        else:
            self._current = 0
        self._slider.setRange(0, max(n - 1, 0))
        self._show_frame(self._current)
        self._timeline.set_frames(self._frames)
        self._timeline.set_current(self._current)

    def _show_frame(self, idx: int):
        n = len(self._frames)
        if n == 0:
            self._disp.clear()
            self._counter_label.setText("0/0")
            return
        idx = max(0, min(idx, n - 1))
        self._current = idx
        frame = self._frames[idx]

        zoom = max(0.5, min(5.0, self._zoom))
        dw = max(1, int(frame.width * zoom))
        dh = max(1, int(frame.height * zoom))
        if dw == frame.width and dh == frame.height:
            pixmap = pil_to_qpixmap(frame)
        else:
            resized = frame.resize((dw, dh), Image.NEAREST)
            pixmap = pil_to_qpixmap(resized)
        self._disp.setPixmap(pixmap)
        self._counter_label.setText(f"{idx + 1}/{n}")
        self._slider.setValue(idx)
        self._timeline.set_current(idx)

    def _toggle_play(self):
        if self._playing:
            self.stop()
        else:
            if not self._frames:
                return
            self._playing = True
            self._btn_play.setText("⏸ 暂停")
            self._schedule_next()

    def stop(self):
        self._playing = False
        self._timer.stop()
        self._btn_play.setText("▶ 播放")

    def _schedule_next(self):
        if not self._playing:
            return
        fps = max(1, self._fps_spin.value())
        delay = max(5, int(1000 / fps))
        self._timer.start(delay)

    def _animate(self):
        if not self._playing or not self._frames:
            return
        self._timer.stop()
        n = len(self._frames)

        if self._pingpong_cb.isChecked():
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
                if self._loop_cb.isChecked():
                    nxt = 0
                else:
                    self.stop()
                    return
            self._show_frame(nxt)
        self._schedule_next()

    def _on_fps_change(self):
        if self._playing and self._timer.isActive():
            self._timer.stop()
            self._schedule_next()

    def _on_range_change(self):
        if hasattr(self.editor, "_refresh_inline_preview"):
            self.editor._refresh_inline_preview(keep_idx=False)

    def _on_slider(self, val: int):
        self._show_frame(val)

    def _go_first(self):
        self._show_frame(0)

    def _go_last(self):
        self._show_frame(len(self._frames) - 1)

    def _prev_frame(self):
        self._show_frame(self._current - 1)

    def _next_frame(self):
        self._show_frame(self._current + 1)

    def _on_timeline_click(self, idx: int):
        self.stop()
        self._show_frame(idx)

    # ── 缩放 ──────────────────────────
    def zoom_step(self, delta: float):
        self._zoom = max(0.5, min(5.0, self._zoom + delta))
        try:
            self.editor._zoom_label.setText(f"{int(self._zoom * 100)}%")
        except Exception:
            pass
        if self._frames:
            self._show_frame(self._current)

    def zoom_reset(self):
        self._zoom = 1.0
        try:
            self.editor._zoom_label.setText("100%")
        except Exception:
            pass
        if self._frames:
            self._show_frame(self._current)


# ═══════════════════════════════════════════════════════════════
# 右侧设置面板
# ═══════════════════════════════════════════════════════════════

class SettingsPanel(QWidget):
    """右侧面板: 网格参数设置 + 导出"""

    def __init__(self, model: SpriteSheetModel, editor):
        super().__init__()
        self.model = model
        self.editor = editor
        self._suppress_changes: bool = False
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── 网格设置 ──
        self._grid_section = QWidget()
        grid_layout = QVBoxLayout(self._grid_section)

        for label, attr, rng in [("列数 (cols):", "columns", (1, 64)),
                                   ("行数 (rows):", "rows", (1, 64)),
                                   ("间距 (padding):", "padding", (0, 32)),
                                   ("Cell 宽:", "cell_width", (1, 4096)),
                                   ("Cell 高:", "cell_height", (1, 4096))]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(rng[0], rng[1])
            spin.setValue(getattr(self.model, attr))
            spin.valueChanged.connect(self._on_param_changed)
            setattr(self, f"_spin_{attr}", spin)
            row.addWidget(spin)
            grid_layout.addLayout(row)

        btn_auto = QPushButton("自动检测 Cell 大小")
        btn_auto.clicked.connect(self._auto_detect)
        grid_layout.addWidget(btn_auto)

        self._btn_resplit = QPushButton("重新拆分")
        self._btn_resplit.clicked.connect(self.editor._resplit)
        self._btn_resplit.setEnabled(False)
        grid_layout.addWidget(self._btn_resplit)

        layout.addWidget(self._grid_section)

        # ── 像素调节 ──
        self._shift_section = QWidget()
        shift_layout = QVBoxLayout(self._shift_section)

        # — 平移 —
        shift_layout.addWidget(QLabel("平移:"))
        shift_val_row = QHBoxLayout()
        shift_val_row.addWidget(QLabel("像素值:"))
        self._spin_shift_px = QSpinBox()
        self._spin_shift_px.setRange(1, 4096)
        self._spin_shift_px.setValue(1)
        shift_val_row.addWidget(self._spin_shift_px)
        shift_layout.addLayout(shift_val_row)

        shift_btn_grid = QGridLayout()
        shift_btn_grid.setSpacing(4)
        self._btn_shift_up = QPushButton("上移")
        self._btn_shift_down = QPushButton("下移")
        self._btn_shift_left = QPushButton("左移")
        self._btn_shift_right = QPushButton("右移")
        shift_btn_grid.addWidget(self._btn_shift_up, 0, 0)
        shift_btn_grid.addWidget(self._btn_shift_down, 0, 1)
        shift_btn_grid.addWidget(self._btn_shift_left, 1, 0)
        shift_btn_grid.addWidget(self._btn_shift_right, 1, 1)
        shift_layout.addLayout(shift_btn_grid)

        self._btn_shift_up.clicked.connect(lambda: self._shift_pixels(0, -1))
        self._btn_shift_down.clicked.connect(lambda: self._shift_pixels(0, 1))
        self._btn_shift_left.clicked.connect(lambda: self._shift_pixels(-1, 0))
        self._btn_shift_right.clicked.connect(lambda: self._shift_pixels(1, 0))

        # — 拉伸 / 缩放 —
        shift_layout.addWidget(QLabel("拉伸 / 缩放:"))
        scale_val_row = QHBoxLayout()
        scale_val_row.addWidget(QLabel("比例(%):"))
        self._spin_scale_pct = QSpinBox()
        self._spin_scale_pct.setRange(1, 100)
        self._spin_scale_pct.setValue(10)
        scale_val_row.addWidget(self._spin_scale_pct)
        shift_layout.addLayout(scale_val_row)

        stretch_btn_grid = QGridLayout()
        stretch_btn_grid.setSpacing(4)
        self._btn_stretch_up = QPushButton("上拉伸")
        self._btn_stretch_down = QPushButton("下拉伸")
        self._btn_stretch_left = QPushButton("左拉伸")
        self._btn_stretch_right = QPushButton("右拉伸")
        self._btn_scale_up = QPushButton("放大")
        self._btn_scale_down = QPushButton("缩小")
        stretch_btn_grid.addWidget(self._btn_stretch_up, 0, 0)
        stretch_btn_grid.addWidget(self._btn_stretch_down, 0, 1)
        stretch_btn_grid.addWidget(self._btn_stretch_left, 1, 0)
        stretch_btn_grid.addWidget(self._btn_stretch_right, 1, 1)
        stretch_btn_grid.addWidget(self._btn_scale_up, 2, 0)
        stretch_btn_grid.addWidget(self._btn_scale_down, 2, 1)
        shift_layout.addLayout(stretch_btn_grid)

        self._btn_stretch_up.clicked.connect(lambda: self._stretch_pixels(0, -1))
        self._btn_stretch_down.clicked.connect(lambda: self._stretch_pixels(0, 1))
        self._btn_stretch_left.clicked.connect(lambda: self._stretch_pixels(-1, 0))
        self._btn_stretch_right.clicked.connect(lambda: self._stretch_pixels(1, 0))
        self._btn_scale_up.clicked.connect(lambda: self._scale_pixels(True))
        self._btn_scale_down.clicked.connect(lambda: self._scale_pixels(False))

        layout.addWidget(self._shift_section)

        # ── 输出信息 ──
        self._info_section = QWidget()
        info_layout = QVBoxLayout(self._info_section)
        self._output_info = QTextEdit()
        self._output_info.setReadOnly(True)
        self._output_info.setMaximumHeight(100)
        self._output_info.setProperty("class", "MonoText")
        info_layout.addWidget(self._output_info)
        layout.addWidget(self._info_section)

        # ── 行/列操作 ──
        # ── 导出设置 ──
        self._export_section = QWidget()
        export_layout = QVBoxLayout(self._export_section)

        # 纹理格式
        tex_row = QHBoxLayout()
        tex_row.addWidget(QLabel("纹理格式:"))
        self._tex_combo = NoWheelComboBox()
        self._tex_combo.addItems(list(TEXTURE_FORMATS.keys()))
        self._tex_combo.currentTextChanged.connect(self._on_tex_fmt_changed)
        tex_row.addWidget(self._tex_combo)
        export_layout.addLayout(tex_row)

        # 像素格式
        pix_row = QHBoxLayout()
        pix_row.addWidget(QLabel("像素格式:"))
        self._fmt_combo = NoWheelComboBox()
        self._fmt_combo.addItems(TEXTURE_FORMATS["PNG-32"])
        self._fmt_combo.setCurrentText("RGBA8888")  # 默认 32-bit RGBA
        self._fmt_combo.currentTextChanged.connect(self._refresh_export_info)
        pix_row.addWidget(self._fmt_combo)
        export_layout.addLayout(pix_row)

        # 透明处理
        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("透明处理:"))
        self._alpha_combo = NoWheelComboBox()
        self._alpha_combo.addItems(ALPHA_MODES)
        self._alpha_combo.setCurrentText("无")
        self._alpha_combo.currentTextChanged.connect(self._refresh_export_info)
        alpha_row.addWidget(self._alpha_combo)
        export_layout.addLayout(alpha_row)

        # 格式说明
        export_layout.addWidget(QLabel("格式说明:"))
        self._fmt_desc = QTextEdit()
        self._fmt_desc.setReadOnly(True)
        self._fmt_desc.setMaximumHeight(80)
        self._fmt_desc.setProperty("class", "MonoText")
        export_layout.addWidget(self._fmt_desc)

        # 格式预览
        export_layout.addWidget(QLabel("格式预览:"))
        self._fmt_preview = QTextEdit()
        self._fmt_preview.setReadOnly(True)
        self._fmt_preview.setMaximumHeight(60)
        self._fmt_preview.setProperty("class", "MonoText")
        export_layout.addWidget(self._fmt_preview)

        btn_save = QPushButton("保存图集...")
        btn_save.clicked.connect(self._save_current_fmt)
        export_layout.addWidget(btn_save)

        self._btn_export_each = QPushButton("导出全部 (每帧)")
        self._btn_export_each.clicked.connect(self.editor._export_all_frames)
        export_layout.addWidget(self._btn_export_each)

        layout.addWidget(self._export_section)
        layout.addStretch()

        self._update_output_info()
        self._refresh_export_info()

    def sections(self):
        """返回右侧面板各区域: [(标题, QWidget), ...]"""
        return [
            ("网格设置", self._grid_section),
            ("像素调节", self._shift_section),
            ("输出信息", self._info_section),
            ("导出", self._export_section),
        ]

    # ── 像素平移 ───────────────────────────
    def _shift_pixels(self, dx: int, dy: int):
        """将选中帧的像素内容按 (dx, dy) 方向平移，保留所有像素，智能裁剪透明区域"""
        sel = self.editor.canvas.selection
        # 如果没有选择，使用当前帧
        if not sel:
            current = self.editor.canvas.timeline.current_index
            if current >= 0 and current < len(self.model.frames):
                sel = {current}
        if not sel:
            return
        px = self._spin_shift_px.value()
        ox = dx * px
        oy = dy * px
        try:
            import numpy as np
            has_numpy = True
        except ImportError:
            has_numpy = False
        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None:
                continue
            if frame.mode != "RGBA":
                frame = frame.convert("RGBA")
            w, h = frame.size
            if has_numpy:
                arr = np.array(frame)
                # 计算透明边界
                alpha = arr[:, :, 3]
                # 左透明列数
                left_trans = 0
                for c in range(w):
                    if np.all(alpha[:, c] == 0):
                        left_trans += 1
                    else:
                        break
                # 右透明列数
                right_trans = 0
                for c in range(w - 1, -1, -1):
                    if np.all(alpha[:, c] == 0):
                        right_trans += 1
                    else:
                        break
                # 上透明行数
                top_trans = 0
                for r in range(h):
                    if np.all(alpha[r, :] == 0):
                        top_trans += 1
                    else:
                        break
                # 下透明行数
                bottom_trans = 0
                for r in range(h - 1, -1, -1):
                    if np.all(alpha[r, :] == 0):
                        bottom_trans += 1
                    else:
                        break
                # 处理水平偏移
                if ox > 0:  # 右移：可以裁剪右侧透明区域
                    trim = min(right_trans, ox)
                    if trim > 0:
                        arr = arr[:, :w - trim]
                        w = w - trim
                    # 扩展右侧
                    new_w = w + ox
                    new_arr = np.zeros((arr.shape[0], new_w, 4), dtype=np.uint8)
                    new_arr[:, ox:ox + arr.shape[1]] = arr
                    arr = new_arr
                elif ox < 0:  # 左移：可以裁剪左侧透明区域
                    trim = min(left_trans, -ox)
                    if trim > 0:
                        arr = arr[:, trim:]
                        w = w - trim
                    # 扩展左侧
                    new_w = w + abs(ox)
                    new_arr = np.zeros((arr.shape[0], new_w, 4), dtype=np.uint8)
                    new_arr[:, :arr.shape[1]] = arr
                    arr = new_arr
                # 处理垂直偏移
                h = arr.shape[0]
                if oy > 0:  # 下移：可以裁剪下侧透明区域
                    trim = min(bottom_trans, oy)
                    if trim > 0:
                        arr = arr[:h - trim, :]
                        h = h - trim
                    new_h = h + oy
                    new_arr = np.zeros((new_h, arr.shape[1], 4), dtype=np.uint8)
                    new_arr[oy:oy + arr.shape[0], :] = arr
                    arr = new_arr
                elif oy < 0:  # 上移：可以裁剪上侧透明区域
                    trim = min(top_trans, -oy)
                    if trim > 0:
                        arr = arr[trim:, :]
                        h = h - trim
                    new_h = h + abs(oy)
                    new_arr = np.zeros((new_h, arr.shape[1], 4), dtype=np.uint8)
                    new_arr[:arr.shape[0], :] = arr
                    arr = new_arr
                self.model.frames[idx] = Image.fromarray(arr)
            else:
                # 无 numpy 时简单裁剪方案
                new_w = w + abs(ox)
                new_h = h + abs(oy)
                new_img = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
                paste_x = ox if ox > 0 else 0
                paste_y = oy if oy > 0 else 0
                new_img.paste(frame, (paste_x, paste_y))
                self.model.frames[idx] = new_img
        self.editor._on_model_changed()

    # ── 像素拉伸 (单方向缩放) ──────────────────
    def _stretch_pixels(self, dx: int, dy: int):
        """单方向拉伸：向指定方向延伸，对侧锚定，基于原图累积计算"""
        sel = self.editor.canvas.selection
        # 如果没有选择，使用当前帧
        if not sel:
            current = self.editor.canvas.timeline.current_index
            if current >= 0 and current < len(self.model.frames):
                sel = {current}
        if not sel:
            return
        pct = self._spin_scale_pct.value()
        # 上/右 = 增大, 下/左 = 缩小
        enlarge = (dy < 0) or (dx > 0)
        ratio = 1 + pct / 100 if enlarge else max(0.01, 1 - pct / 100)
        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None:
                continue
            # 保存原图（首次）
            if idx not in self.model._original_frames:
                self.model._original_frames[idx] = frame.copy() if frame.mode == "RGBA" else frame.convert("RGBA").copy()
                self.model._scale_factors[idx] = (1.0, 1.0)
            # 更新累积比例
            sx, sy = self.model._scale_factors[idx]
            if dx != 0:  # 左/右拉伸 → 改变宽度
                sx *= ratio
            else:  # 上/下拉伸 → 改变高度
                sy *= ratio
            self.model._scale_factors[idx] = (sx, sy)
            # 基于原图计算新尺寸
            orig = self.model._original_frames[idx]
            ow, oh = orig.size
            new_w = max(1, round(ow * sx))
            new_h = max(1, round(oh * sy))
            # 直接保存缩放后的帧，不裁剪到 cell 尺寸
            self.model.frames[idx] = self._bilinear_minimap_resize(orig, new_w, new_h)
        self.editor._on_model_changed()
        self._update_output_info()

    # ── 像素缩放 (PIL / 百分比 / Bilinear Minimap) ─────────────────────
    @staticmethod
    def _bilinear_minimap_resize(img, target_w: int, target_h: int):
        """像素风格缩放：始终使用 NEAREST 保持像素锐利，大比例缩小时逐步减半以提高质量"""
        w, h = img.size
        # 放大或微小变化 → 直接 NEAREST
        if target_w >= w or target_h >= h:
            return img.resize((target_w, target_h), Image.NEAREST)
        # 缩小 → 逐步减半 + NEAREST（保持像素锐利）
        cur = img
        cw, ch = cur.size
        while cw > target_w * 2 and ch > target_h * 2:
            cw, ch = max(cw // 2, target_w), max(ch // 2, target_h)
            cur = cur.resize((cw, ch), Image.NEAREST)
        # 最后一步精确缩放到目标尺寸
        return cur.resize((target_w, target_h), Image.NEAREST)

    def _scale_pixels(self, enlarge: bool):
        """PIL 百分比等比缩放 — 基于原图累积计算

        两个维度共用同一个 ratio，比例完美保持。
        放大: ratio = 1 + pct/100
        缩小: ratio = 1 - pct/100
        始终基于原图缩放，避免累积像素损失。
        """
        sel = self.editor.canvas.selection
        # 如果没有选择，使用当前帧
        if not sel:
            current = self.editor.canvas.timeline.current_index
            if current >= 0 and current < len(self.model.frames):
                sel = {current}
        if not sel:
            return
        pct = self._spin_scale_pct.value()  # 1-100 百分比
        ratio = 1 + pct / 100 if enlarge else max(0.01, 1 - pct / 100)
        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None:
                continue
            # 保存原图（首次）
            if idx not in self.model._original_frames:
                self.model._original_frames[idx] = frame.copy() if frame.mode == "RGBA" else frame.convert("RGBA").copy()
                self.model._scale_factors[idx] = (1.0, 1.0)
            # 更新累积比例（等比缩放，两维度相同）
            sx, sy = self.model._scale_factors[idx]
            sx *= ratio
            sy *= ratio
            self.model._scale_factors[idx] = (sx, sy)
            # 基于原图计算新尺寸
            orig = self.model._original_frames[idx]
            ow, oh = orig.size
            new_w = max(1, round(ow * sx))
            new_h = max(1, round(oh * sy))
            self.model.frames[idx] = self._bilinear_minimap_resize(orig, new_w, new_h)
        # cell 尺寸保持不变 — 画布网格稳定，视图不随图片缩放
        self.editor._on_model_changed()
        self._update_output_info()

    # ── 回调 ──────────────────────────
    def _on_param_changed(self):
        if self._suppress_changes:
            return
        # 检测 cell 宽高是否被用户手动修改
        sender = self.sender()
        if sender in (self._spin_cell_width, self._spin_cell_height):
            self.model._cell_size_set = True
        try:
            self.model.columns = self._spin_columns.value()
            self.model.rows = self._spin_rows.value()
            self.model.padding = self._spin_padding.value()
            self.model.cell_width = self._spin_cell_width.value()
            self.model.cell_height = self._spin_cell_height.value()
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
        self._suppress_changes = True
        self._spin_cell_width.setValue(self.model.cell_width)
        self._spin_cell_height.setValue(self.model.cell_height)
        self._suppress_changes = False
        self.model._cell_size_set = False  # 自动检测不算手动设定
        self.editor._on_model_changed()
        self._update_output_info()
        try:
            self._refresh_export_info()
        except Exception:
            pass

    def _move_row(self, delta: int):
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
        r = idx // cols
        target = r + delta
        if 0 <= target < self.model.rows:
            self.model.swap_rows(r, target)
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

    def _on_tex_fmt_changed(self):
        tex = self._tex_combo.currentText()
        options = TEXTURE_FORMATS.get(tex, ["RGBA8888"])
        self._fmt_combo.clear()
        self._fmt_combo.addItems(options)
        if self._fmt_combo.currentText() not in options:
            self._fmt_combo.setCurrentIndex(0)
        self._refresh_export_info()

    def _refresh_export_info(self):
        fmt = self._fmt_combo.currentText()
        alpha_mode = self._alpha_combo.currentText()
        pix_desc = PIXEL_FORMAT_DESC.get(fmt, "")
        alpha_desc = ALPHA_MODE_DESC.get(alpha_mode, "")
        desc = f"【{fmt}】\n{pix_desc}\n\n【{alpha_mode}】\n{alpha_desc}"
        self._fmt_desc.setPlainText(desc)

        lines: List[str] = []
        m = self.model
        try:
            ss = m.build_spritesheet()
            w, h = ss.size
            bpp_map = {"RGBA8888": 32, "RGB888": 24, "RGB565": 16,
                       "RGBA5551": 16, "RGBA4444": 16, "PNG-8 (256色)": 8}
            bpp = bpp_map.get(fmt, 32)
            raw_kb = w * h * bpp // 8 // 1024
            lines.append(f"尺寸: {w} × {h} px")
            lines.append(f"纹理格式: {self._tex_combo.currentText()}")
            lines.append(f"像素格式: {fmt} ({bpp}-bit)")
            lines.append(f"预估原始: ~{raw_kb} KB (PNG 压缩后更小)")
        except Exception:
            lines.append("(无数据)")
        self._fmt_preview.setPlainText("\n".join(lines))

    def _save_current_fmt(self):
        m = self.model
        if m.frame_count == 0:
            QMessageBox.information(self, "提示", "没有帧数据可导出")
            return
        ss = m.build_spritesheet()
        alpha_mode = self._alpha_combo.currentText()
        ss = apply_alpha_mode(ss, alpha_mode)
        fmt = self._fmt_combo.currentText()
        converted = convert_pixel_format(ss, fmt)

        fp, _ = QFileDialog.getSaveFileName(
            self, f"保存图集 ({self._tex_combo.currentText()} / {fmt})",
            "", "PNG 图片 (*.png)")
        if not fp:
            return
        converted.save(fp, "PNG")
        self.editor._status_label.setText(
            f"已保存 ({self._tex_combo.currentText()} / {fmt} / {alpha_mode}): {Path(fp).name}")
        self._update_output_info()

    def _update_output_info(self):
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
            self._output_info.setPlainText("\n".join(lines))
        except Exception:
            pass

    def refresh_values(self):
        self._suppress_changes = True
        self._spin_columns.setValue(self.model.columns)
        self._spin_rows.setValue(self.model.rows)
        self._spin_padding.setValue(self.model.padding)
        self._spin_cell_width.setValue(self.model.cell_width)
        self._spin_cell_height.setValue(self.model.cell_height)
        self._suppress_changes = False
        self._update_output_info()
        try:
            self._refresh_export_info()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 导入合并对话框
# ═══════════════════════════════════════════════════════════════

class ImportMergeDialog(QDialog):
    def __init__(self, parent, image_count: int, images: List[Image.Image]):
        super().__init__(parent)
        self.setWindowTitle("合并图片为 Spritesheet")
        self.images = images
        self.result: Optional[Tuple[int, int, int]] = None
        self.setModal(True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"已选择 {image_count} 张图片"))

        # 自动计算建议值
        n = image_count
        suggest_cols = max(1, int(n ** 0.5 + 0.5))
        suggest_rows = (n + suggest_cols - 1) // suggest_cols

        settings = QGroupBox("网格参数")
        sl = QVBoxLayout(settings)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("列数 (columns):"))
        self._cols_spin = QSpinBox()
        self._cols_spin.setRange(1, 64)
        self._cols_spin.setValue(suggest_cols)
        row1.addWidget(self._cols_spin)
        row1.addWidget(QLabel("行数 (rows):"))
        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(1, 64)
        self._rows_spin.setValue(suggest_rows)
        row1.addWidget(self._rows_spin)
        sl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("间距 (padding):"))
        self._pad_spin = QSpinBox()
        self._pad_spin.setRange(0, 32)
        self._pad_spin.setValue(1)
        row2.addWidget(self._pad_spin)
        btn_auto = QPushButton("自动排列")
        btn_auto.clicked.connect(self._auto_arrange)
        row2.addWidget(btn_auto)
        sl.addLayout(row2)

        self._preview_label = QLabel()
        self._preview_label.setProperty("class", "StatusHint")
        sl.addWidget(self._preview_label)

        layout.addWidget(settings)

        # 图片信息
        sizes = set((img.width, img.height) for img in images)
        info = QGroupBox("图片信息")
        il = QVBoxLayout(info)
        if len(sizes) == 1:
            w, h = sizes.pop()
            il.addWidget(QLabel(f"所有图片尺寸一致: {w}×{h} px"))
        else:
            il.addWidget(QLabel(f"图片尺寸不一致 ({len(sizes)} 种), 将使用最大尺寸"))
            max_w = max(img.width for img in images)
            max_h = max(img.height for img in images)
            il.addWidget(QLabel(f"最大尺寸: {max_w}×{max_h} px"))
        layout.addWidget(info)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton("确认合并")
        btn_ok.clicked.connect(self._on_ok)
        btns.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        self._update_preview()
        for spin in [self._cols_spin, self._rows_spin, self._pad_spin]:
            spin.valueChanged.connect(self._update_preview)

    def _auto_arrange(self):
        n = len(self.images)
        cols = max(1, int(n ** 0.5 + 0.5))
        rows = (n + cols - 1) // cols
        self._cols_spin.setValue(cols)
        self._rows_spin.setValue(rows)

    def _update_preview(self):
        try:
            cols = self._cols_spin.value()
            rows = self._rows_spin.value()
            total = cols * rows
            n = len(self.images)
            fill = "刚好填满" if total == n else ("多出" if total > n else "不足")
            diff = abs(total - n)
            self._preview_label.setText(
                f"网格: {cols}×{rows} = {total} 格, 图片: {n} 张 ({fill} {diff} 格)")
        except Exception:
            self._preview_label.setText("参数错误")

    def _on_ok(self):
        self.result = (self._cols_spin.value(), self._rows_spin.value(),
                       self._pad_spin.value())
        self.accept()


# ═══════════════════════════════════════════════════════════════
# 拆分设置对话框
# ═══════════════════════════════════════════════════════════════

class SplitDialog(QDialog):
    def __init__(self, parent, img: Image.Image):
        super().__init__(parent)
        self.setWindowTitle("拆分设置")
        self.img = img
        self.result: Optional[Tuple[int, int, int, int, int]] = None
        self.setModal(True)

        layout = QVBoxLayout(self)

        info = QGroupBox("原始图片")
        il = QVBoxLayout(info)
        il.addWidget(QLabel(f"尺寸: {img.width} x {img.height} px"))
        layout.addWidget(info)

        settings = QGroupBox("拆分参数")
        sl = QVBoxLayout(settings)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("列数 (cols):"))
        self._cols_spin = QSpinBox()
        self._cols_spin.setRange(1, 128)
        self._cols_spin.setValue(4)
        row1.addWidget(self._cols_spin)
        row1.addWidget(QLabel("行数 (rows):"))
        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(1, 128)
        self._rows_spin.setValue(4)
        row1.addWidget(self._rows_spin)
        sl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("间距 (padding):"))
        self._pad_spin = QSpinBox()
        self._pad_spin.setRange(0, 32)
        self._pad_spin.setValue(0)
        row2.addWidget(self._pad_spin)
        btn_auto = QPushButton("自动计算")
        btn_auto.clicked.connect(self._auto_calc)
        row2.addWidget(btn_auto)
        sl.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Cell 宽:"))
        self._cw_spin = QSpinBox()
        self._cw_spin.setRange(1, 4096)
        self._cw_spin.setValue(64)
        row3.addWidget(self._cw_spin)
        row3.addWidget(QLabel("Cell 高:"))
        self._ch_spin = QSpinBox()
        self._ch_spin.setRange(1, 4096)
        self._ch_spin.setValue(64)
        row3.addWidget(self._ch_spin)
        sl.addLayout(row3)

        self._preview_label = QLabel()
        self._preview_label.setProperty("class", "StatusHint")
        sl.addWidget(self._preview_label)
        layout.addWidget(settings)

        for spin in [self._cols_spin, self._rows_spin, self._pad_spin,
                      self._cw_spin, self._ch_spin]:
            spin.valueChanged.connect(self._update_preview)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton("确认拆分")
        btn_ok.clicked.connect(self._on_ok)
        btns.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        self._update_preview()

    def _auto_calc(self):
        cols = self._cols_spin.value()
        rows = self._rows_spin.value()
        if cols <= 0 or rows <= 0:
            return
        w, h = self.img.width, self.img.height
        cw = w // cols
        ch = h // rows
        remain_w = w - cw * cols
        remain_h = h - ch * rows
        pad = 0
        if remain_w > 0 and cols > 1:
            pad = remain_w // (cols - 1)
        if remain_h > 0 and rows > 1:
            pad = max(pad, remain_h // (rows - 1))
        self._pad_spin.setValue(min(pad, 32))
        self._cw_spin.setValue(cw)
        self._ch_spin.setValue(ch)

    def _update_preview(self):
        try:
            cols = self._cols_spin.value()
            rows = self._rows_spin.value()
            pad = self._pad_spin.value()
            cw = self._cw_spin.value()
            ch = self._ch_spin.value()
            total_w = cols * (cw + pad) - pad
            total_h = rows * (ch + pad) - pad
            ok = total_w <= self.img.width and total_h <= self.img.height
            mark = "✓" if ok else "✗"
            self._preview_label.setText(
                f"计算结果: {total_w}x{total_h}  {mark}  "
                f"(原图 {self.img.width}x{self.img.height})")
        except Exception:
            self._preview_label.setText("参数错误")

    def _on_ok(self):
        self.result = (self._cols_spin.value(), self._rows_spin.value(),
                       self._pad_spin.value(), self._cw_spin.value(),
                       self._ch_spin.value())
        self.accept()


# ═══════════════════════════════════════════════════════════════
# 主编辑器窗口 (QMainWindow)
# ═══════════════════════════════════════════════════════════════

class SpriteSheetEditorWindow(QMainWindow):
    """Spritesheet 编辑器主窗口 (PySide6)"""

    def __init__(self, filepath: Optional[str] = None, is_dark: bool = True):
        super().__init__()
        self.setWindowTitle("Spritesheet Editor - 精灵表编辑器 (PySide6)")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        apply_godot_theme(self, is_dark)

        self.model = SpriteSheetModel()
        self._filepath: Optional[str] = None
        self._source_sheet: Optional[Image.Image] = None
        self._is_dark: bool = is_dark
        self._preview_mode: str = "grid"
        self._suppress_mode_change: bool = False

        self._build_layout()
        self._build_menu()
        self._build_shortcuts()

        # 初始画布背景色同步 (跟随 OS 主题)
        bg_color = QColor("#1a1d24") if self._is_dark else QColor("#313c52")
        self.canvas.setBackgroundBrush(QBrush(bg_color))
        self.preview_view._disp.setObjectName("GamePreview")
        self.preview_view._disp.style().unpolish(self.preview_view._disp)
        self.preview_view._disp.style().polish(self.preview_view._disp)

        if filepath:
            self._load_spritesheet(Path(filepath))

        self._fit_to_screen()

    def _fit_to_screen(self):
        """根据屏幕可用空间设定窗口尺寸并居中。"""
        screen_geo = QApplication.primaryScreen().availableGeometry()
        hint = self.sizeHint()
        w = min(hint.width(), int(screen_geo.width() * 0.92))
        h = min(hint.height(), int(screen_geo.height() * 0.88))
        self.resize(w, h)
        self.setMinimumSize(1200, 800)
        # 用 frameGeometry 居中（含窗口边框/标题栏），避免客户区与框架尺寸不一致
        fg = self.frameGeometry()
        fg.moveCenter(screen_geo.center())
        self.move(fg.topLeft())

    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(2)

        # ── 工具栏 ──
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("模式:"))

        self._mode_merge = QRadioButton("组合")
        self._mode_merge.setChecked(True)
        self._mode_split = QRadioButton("拆分")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._mode_merge)
        mode_group.addButton(self._mode_split)
        mode_group.buttonToggled.connect(self._on_workflow_mode_changed)

        toolbar.addWidget(self._mode_merge)
        toolbar.addWidget(self._mode_split)
        toolbar.addWidget(self._v_sep())

        btn_new = QPushButton("新建")
        btn_new.clicked.connect(self._new)
        toolbar.addWidget(btn_new)

        self._btn_import_merge = QPushButton("导入图片")
        self._btn_import_merge.clicked.connect(self._import_images)
        toolbar.addWidget(self._btn_import_merge)

        self._btn_import_split = QPushButton("导入图集")
        self._btn_import_split.clicked.connect(self._import_spritesheet)
        self._btn_import_split.setEnabled(False)
        toolbar.addWidget(self._btn_import_split)

        toolbar.addWidget(self._v_sep())

        btn_preview_sel = QPushButton("预览选中")
        btn_preview_sel.clicked.connect(self._preview_selected)
        toolbar.addWidget(btn_preview_sel)

        btn_preview_all = QPushButton("预览全部")
        btn_preview_all.clicked.connect(self._preview_all)
        toolbar.addWidget(btn_preview_all)

        toolbar.addWidget(self._v_sep())

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_from_list)
        toolbar.addWidget(btn_delete)

        toolbar.addWidget(self._v_sep())

        btn_copy_row = QPushButton("复制行")
        btn_copy_row.clicked.connect(self._copy_row)
        toolbar.addWidget(btn_copy_row)

        btn_flip = QPushButton("水平翻转")
        btn_flip.clicked.connect(self._flip_horizontal)
        toolbar.addWidget(btn_flip)

        toolbar.addWidget(self._v_sep())

        btn_row_up = QPushButton("行上移")
        btn_row_up.clicked.connect(lambda: self.settings._move_row(-1))
        toolbar.addWidget(btn_row_up)
        btn_row_down = QPushButton("行下移")
        btn_row_down.clicked.connect(lambda: self.settings._move_row(1))
        toolbar.addWidget(btn_row_down)
        btn_col_left = QPushButton("列左移")
        btn_col_left.clicked.connect(lambda: self.settings._move_col(-1))
        toolbar.addWidget(btn_col_left)
        btn_col_right = QPushButton("列右移")
        btn_col_right.clicked.connect(lambda: self.settings._move_col(1))
        toolbar.addWidget(btn_col_right)

        # 深浅色切换
        toolbar.addWidget(self._v_sep())
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)

        toolbar.addStretch()
        self._status_label = QLabel("就绪")
        self._status_label.setProperty("class", "StatusHint")
        toolbar.addWidget(self._status_label)

        main_layout.addLayout(toolbar)

        # ── 主内容区 (QSplitter + Dock 面板) ──
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(7)

        # ── 左侧: 精灵资产库 ──
        left_widget = QWidget()
        left_panel = QVBoxLayout(left_widget)
        left_panel.setContentsMargins(0, 0, 0, 0)
        left_header = QHBoxLayout()
        self._list_title = QLabel("导入的精灵")
        left_header.addWidget(self._list_title)
        btn_clear = QPushButton("清空")
        btn_clear.setProperty("class", "CompactBtn")
        btn_clear.clicked.connect(self._clear_list)
        left_header.addWidget(btn_clear)
        btn_up = QPushButton("▲上移")
        btn_up.setProperty("class", "CompactBtn")
        btn_up.clicked.connect(lambda: self.canvas.move_selected_left())
        left_header.addWidget(btn_up)
        btn_down = QPushButton("▼下移")
        btn_down.setProperty("class", "CompactBtn")
        btn_down.clicked.connect(lambda: self.canvas.move_selected_right())
        left_header.addWidget(btn_down)
        left_panel.addLayout(left_header)

        self.image_list = ImageListWidget(self)
        self.image_list.itemClicked.connect(self.image_list._on_item_clicked)
        left_panel.addWidget(self.image_list, 1)

        list_info = QLabel("未导入图片")
        list_info.setProperty("class", "StatusHint")
        self._list_info_label = list_info
        left_panel.addWidget(list_info)

        main_splitter.addWidget(self._create_dock("精灵资产库", left_widget))

        # ── 中间: 2D 渲染视口 ──
        center_widget = QWidget()
        center = QVBoxLayout(center_widget)
        center.setContentsMargins(0, 0, 0, 0)

        # 预览模式切换栏 + 缩放
        preview_bar = QHBoxLayout()
        preview_bar.addWidget(QLabel("显示:"))

        self._mode_grid = QRadioButton("网格")
        self._mode_grid.setChecked(True)
        self._mode_single = QRadioButton("单帧")
        self._mode_anim = QRadioButton("动画")
        mode_group2 = QButtonGroup(self)
        mode_group2.addButton(self._mode_grid)
        mode_group2.addButton(self._mode_single)
        mode_group2.addButton(self._mode_anim)
        mode_group2.buttonToggled.connect(self._on_preview_mode_changed)
        preview_bar.addWidget(self._mode_grid)
        preview_bar.addWidget(self._mode_single)
        preview_bar.addWidget(self._mode_anim)

        preview_bar.addStretch()

        preview_bar.addWidget(QLabel("缩放:"))
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setProperty("class", "CompactBtn")
        btn_zoom_out.clicked.connect(lambda: self._shared_zoom_step(-0.25))
        preview_bar.addWidget(btn_zoom_out)
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setProperty("class", "CompactBtn")
        btn_zoom_in.clicked.connect(lambda: self._shared_zoom_step(0.25))
        preview_bar.addWidget(btn_zoom_in)
        btn_zoom_1 = QPushButton("1:1")
        btn_zoom_1.setProperty("class", "CompactBtn")
        btn_zoom_1.clicked.connect(self._shared_zoom_reset)
        preview_bar.addWidget(btn_zoom_1)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(40)
        preview_bar.addWidget(self._zoom_label)

        center.addLayout(preview_bar)

        # 堆栈: 网格视图 / 预览视图
        self._stack = QWidget()
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        # 网格视图容器
        self._grid_container = QWidget()
        grid_layout = QVBoxLayout(self._grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = SpriteGraphicsView(self.model, self)
        grid_layout.addWidget(self.canvas)
        stack_layout.addWidget(self._grid_container)

        # 预览视图 (初始隐藏)
        self.preview_view = PreviewView(self)
        self.preview_view.setVisible(False)
        stack_layout.addWidget(self.preview_view)

        center.addWidget(self._stack, 1)

        hint = QLabel("操作: 点击选帧 | Ctrl+多选 | Shift+范围选 | 拖拽帧/行头/列头排序")
        hint.setProperty("class", "StatusHint")
        center.addWidget(hint)

        main_splitter.addWidget(self._create_dock("2D 渲染视口", center_widget))

        # ── 右侧: 检查器 (每个区域独立 Dock 面板, ScrollArea 应对小窗口) ──
        self.settings = SettingsPanel(self.model, self)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        for title, widget in self.settings.sections():
            right_layout.addWidget(self._create_dock(title, widget))
        right_layout.addStretch()
        right_scroll = QScrollArea()
        right_scroll.setWidget(right_container)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(260)
        main_splitter.addWidget(right_scroll)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([260, 600, 300])
        main_layout.addWidget(main_splitter, 1)

        # ── 信号/槽连接 (MVC 解耦) ──
        self.model.model_changed.connect(self._on_model_changed)
        self.canvas.selectionChangedCustom.connect(self._on_selection_changed)
        self.image_list.selectionChangedCustom.connect(self._on_selection_changed)

        # 初始渲染空网格
        self.canvas.redraw()

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    def _v_sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        return sep

    def _build_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("导入图片(合并)", self._import_images)
        file_menu.addAction("导入图集(拆分)", self._import_spritesheet)
        file_menu.addSeparator()
        file_menu.addAction("新建空白", self._new)
        file_menu.addSeparator()
        file_menu.addAction("保存图集\tCtrl+S", self._save)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        # 编辑菜单 — 仅显示快捷键提示, 实际绑定由 QShortcut 统一处理
        edit_menu = menubar.addMenu("编辑")
        edit_menu.addAction("全选\tCtrl+A", self.canvas.select_all)
        edit_menu.addAction("取消选择\tEscape", self.canvas.select_none)
        edit_menu.addSeparator()
        edit_menu.addAction("删除选中帧\tDelete", self.canvas.delete_selected)
        edit_menu.addSeparator()
        edit_menu.addAction("选中帧左移\tCtrl+←", self.canvas.move_selected_left)
        edit_menu.addAction("选中帧右移\tCtrl+→", self.canvas.move_selected_right)
        edit_menu.addAction("选中帧上移\tCtrl+↑", self.canvas.move_selected_up)
        edit_menu.addAction("选中帧下移\tCtrl+↓", self.canvas.move_selected_down)
        edit_menu.addSeparator()
        edit_menu.addAction("当前列左移\tShift+←", lambda: self.settings._move_col(-1))
        edit_menu.addAction("当前列右移\tShift+→", lambda: self.settings._move_col(1))
        edit_menu.addAction("当前行上移\tShift+↑", lambda: self.settings._move_row(-1))
        edit_menu.addAction("当前行下移\tShift+↓", lambda: self.settings._move_row(1))

        # 预览菜单
        view_menu = menubar.addMenu("预览")
        view_menu.addAction("预览选中帧", self._preview_selected)
        view_menu.addAction("预览全部", self._preview_all)

    def _build_shortcuts(self):
        """统一快捷键注册 — 仅 QShortcut (避免与 QAction 双重注册冲突)"""
        _w = self._shortcut_wrap
        # 基础快捷键 (不经过输入控件检测, 因其不与文本编辑冲突)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Ctrl+A"), self, self.canvas.select_all)
        QShortcut(QKeySequence("Escape"), self, self.canvas.select_none)
        QShortcut(QKeySequence("Delete"), self, self.canvas.delete_selected)
        # 方向键移动 — 必须经 _shortcut_wrap 避开输入控件焦点
        QShortcut(QKeySequence("Ctrl+Left"),  self, _w(self.canvas.move_selected_left))
        QShortcut(QKeySequence("Ctrl+Right"), self, _w(self.canvas.move_selected_right))
        QShortcut(QKeySequence("Ctrl+Up"),    self, _w(self.canvas.move_selected_up))
        QShortcut(QKeySequence("Ctrl+Down"),  self, _w(self.canvas.move_selected_down))
        # Shift+方向键 = 换行/换列
        QShortcut(QKeySequence("Shift+Left"),  self, _w(lambda: self.settings._move_col(-1)))
        QShortcut(QKeySequence("Shift+Right"), self, _w(lambda: self.settings._move_col(1)))
        QShortcut(QKeySequence("Shift+Up"),    self, _w(lambda: self.settings._move_row(-1)))
        QShortcut(QKeySequence("Shift+Down"),  self, _w(lambda: self.settings._move_row(1)))

    def _shortcut_wrap(self, func):
        """包装快捷键回调: SpinBox/TextEdit/ComboBox 获得焦点时不劫持文本编辑"""
        def wrapper():
            w = QApplication.focusWidget()
            if isinstance(w, (QLineEdit, QTextEdit, QSpinBox, QComboBox)):
                return
            func()
        return wrapper

    # ── 模型变更通知 ───────────────────
    def _on_model_changed(self):
        self.canvas.redraw()
        self.image_list.refresh_values()
        self._update_status()
        if self._preview_mode != "grid":
            self._refresh_inline_preview(keep_idx=True)

    def _update_status(self):
        m = self.model
        total = m.total_cells
        shown = sum(1 for f in m.frames if f is not None)
        self._status_label.setText(
            f"帧: {m.frame_count}/{total}  "
            f"网格: {m.columns}x{m.rows}  "
            f"Cell: {m.cell_width}x{m.cell_height}  "
            f"Padding: {m.padding}"
        )
        self._list_info_label.setText(
            f"{shown} 张 | 网格 {m.columns}×{m.rows}={total}")

    # ── 新建 ───────────────────────────
    def _new(self):
        if self.model.frame_count > 0:
            if QMessageBox.question(self, "确认", "当前内容将被清除，确定新建吗?") != QMessageBox.Yes:
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
        self._status_label.setText("新建空白 Spritesheet")

    # ── 导入 ───────────────────────────
    def _import_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要导入的图片", "",
            "图片文件 (*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp);;所有文件 (*.*)")
        if not files:
            return
        # 切换到组合模式 (若已有数据会弹出确认框, 用户取消则跳过加载)
        self._mode_merge.setChecked(True)
        if not self._mode_merge.isChecked():
            return

        # 按文件名排序（自然排序：数字按数值大小排）
        files = sorted(files, key=lambda f: [
            int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', Path(f).name)
        ])

        images = []
        for fp in files:
            try:
                img = Image.open(fp).convert("RGBA")
                images.append(img)
            except Exception as e:
                QMessageBox.warning(self, "警告", f"无法读取 {Path(fp).name}: {e}")

        if not images:
            return

        n = len(images)
        cols = max(1, int(n ** 0.5 + 0.5))
        rows = (n + cols - 1) // cols

        self.model.frames = list(images)
        self.model.columns = cols
        self.model.rows = rows
        self.model.padding = self.settings._spin_padding.value()
        self.model._cell_size_set = False  # 全新导入，重置手动设定标记
        self.model.auto_detect_cell_size()
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.image_list._selected_idx = -1
        self.image_list.set_images(list(images), list(files))
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_label.setText(f"已导入 {len(images)} 张图片 → {cols}×{rows} 网格")

    def _import_spritesheet(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择图集图片", "",
            "PNG 图片 (*.png);;所有图片 (*.png *.bmp *.jpg);;所有文件 (*.*)")
        if not fp:
            return
        # 切换到拆分模式 (若已有数据会弹出确认框, 用户取消则跳过加载)
        self._mode_split.setChecked(True)
        if self._mode_split.isChecked():
            self._load_spritesheet(Path(fp))

    def _load_spritesheet(self, path: Path):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法读取图片: {e}")
            return

        self._filepath = str(path)
        self._source_sheet = img

        m = self.model
        cols = max(1, int(m.columns))
        rows = max(1, int(m.rows))
        pad = max(0, int(m.padding))
        # 用户未手动设定 cell 宽高时自动反算；已手动设定则使用用户值
        if not m._cell_size_set:
            iw, ih = img.size
            m.cell_width = max(1, (iw - max(0, cols - 1) * pad) // cols)
            m.cell_height = max(1, (ih - max(0, rows - 1) * pad) // rows)
        m.split_spritesheet(img)
        self.image_list._image_paths = []
        self.image_list._path_by_id = {}
        self.image_list._selected_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_label.setText(
            f"已拆分: {path.name} → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _resplit(self):
        img = self._source_sheet
        if img is None:
            QMessageBox.information(self, "提示", "请先通过《导入拆分》加载一张 Spritesheet")
            return
        if self.model.frame_count > 0:
            if QMessageBox.question(self, "确认",
                    "重新拆分将丢弃当前排序和删除, 确定继续吗?") != QMessageBox.Yes:
                return

        m = self.model
        # 用户未手动设定 cell 宽高时自动反算；已手动设定则使用用户值
        if not m._cell_size_set:
            iw, ih = img.size
            cols = max(1, int(m.columns))
            rows = max(1, int(m.rows))
            pad = max(0, int(m.padding))
            m.cell_width = max(1, (iw - max(0, cols - 1) * pad) // cols)
            m.cell_height = max(1, (ih - max(0, rows - 1) * pad) // rows)
        m.split_spritesheet(img)
        self.image_list._image_paths = []
        self.image_list._path_by_id = {}
        self.image_list._selected_idx = -1
        self.canvas.selection.clear()
        self.canvas._drag_info = None
        self.canvas._header_drag = None
        self.canvas._last_click_idx = -1
        self.settings.refresh_values()
        self._on_model_changed()
        self._status_label.setText(
            f"已重新拆分 → {m.frame_count} 帧 "
            f"(cols={m.columns} rows={m.rows} "
            f"cell={m.cell_width}×{m.cell_height} pad={m.padding})")

    def _export_all_frames(self):
        m = self.model
        if m.frame_count == 0:
            QMessageBox.information(self, "提示", "没有帧数据可导出")
            return
        sel = self.canvas.selection
        if sel:
            indices = sorted(i for i in sel if 0 <= i < len(m.frames) and m.frames[i] is not None)
        else:
            indices = [i for i, f in enumerate(m.frames) if f is not None]
        if not indices:
            QMessageBox.information(self, "提示", "没有可导出的帧")
            return

        outdir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not outdir:
            return
        fmt = self.settings._fmt_combo.currentText()
        alpha_mode = self.settings._alpha_combo.currentText()
        tex_fmt = self.settings._tex_combo.currentText()
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
        self._status_label.setText(
            f"已导出 {count}/{len(indices)} 帧 → {outdir} ({tex_fmt} / {fmt} / {alpha_mode})")

    # ── 删除 / 复制行 / 翻转 ──────────
    def _delete_from_list(self):
        if self.canvas.selection:
            self.canvas.delete_selected()

    def _clear_list(self):
        self.image_list.clear_all()

    def _copy_row(self):
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要复制行中的任意帧")
            return
        idx = min(sel)
        row = idx // max(1, self.model.columns)
        self.model.copy_row(row)
        new_row = row + 1
        cols = self.model.columns
        new_start = new_row * cols
        self.canvas.selection = set(range(new_start, new_start + cols))
        self.settings._spin_rows.setValue(self.model.rows)
        self._on_model_changed()
        self._status_label.setText(f"已复制行 R{row} → R{new_row}")

    def _flip_horizontal(self):
        sel = self.canvas.selection
        if not sel:
            QMessageBox.information(self, "提示", "请先在画布上选中要翻转的帧")
            return
        for idx in sel:
            frame = self.model.get_frame(idx)
            if frame is not None:
                self.model.frames[idx] = frame.transpose(Image.FLIP_LEFT_RIGHT)
        self._on_model_changed()
        self._status_label.setText(f"已水平翻转 {len(sel)} 帧")

    # ── 工作模式 / 预览模式 ────────────
    def _on_workflow_mode_changed(self):
        if self._suppress_mode_change:
            return
        if self._mode_merge.isChecked():
            if self.model.frame_count > 0:
                if QMessageBox.question(self, "确认",
                        "切换模式将清空当前数据, 确定继续吗?") != QMessageBox.Yes:
                    self._suppress_mode_change = True
                    self._mode_split.setChecked(True)
                    self._suppress_mode_change = False
                    return
                self._reset_model()
            self._list_title.setText("导入的精灵")
            self._btn_import_merge.setEnabled(True)
            self._btn_import_split.setEnabled(False)
            self.settings._btn_resplit.setEnabled(False)
        else:
            if self.model.frame_count > 0:
                if QMessageBox.question(self, "确认",
                        "切换模式将清空当前数据, 确定继续吗?") != QMessageBox.Yes:
                    self._suppress_mode_change = True
                    self._mode_merge.setChecked(True)
                    self._suppress_mode_change = False
                    return
                self._reset_model()
            self._list_title.setText("导入的精灵组")
            self._btn_import_merge.setEnabled(False)
            self._btn_import_split.setEnabled(True)
            self.settings._btn_resplit.setEnabled(True)

        self._preview_mode = "grid"
        self._mode_grid.setChecked(True)
        self._show_grid_view()
        self._status_label.setText(
            "已切换到组合模式" if self._mode_merge.isChecked() else "已切换到拆分模式")

    def _reset_model(self):
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

    def _on_preview_mode_changed(self):
        if self._mode_grid.isChecked():
            self._preview_mode = "grid"
            self.preview_view.stop()
            self._show_grid_view()
            self._zoom_label.setText(f"{int(self.canvas._zoom * 100)}%")
        elif self._mode_single.isChecked():
            self._preview_mode = "single"
            self._show_preview_view()
            self.preview_view.set_mode("single")
            self._refresh_inline_preview(keep_idx=False)
            self._zoom_label.setText(f"{int(self.preview_view._zoom * 100)}%")
        else:
            self._preview_mode = "anim"
            self._show_preview_view()
            self.preview_view.set_mode("anim")
            self._refresh_inline_preview(keep_idx=False)
            self._zoom_label.setText(f"{int(self.preview_view._zoom * 100)}%")

    def _show_grid_view(self):
        self._grid_container.setVisible(True)
        self.preview_view.setVisible(False)
        self._relayout_viewport()

    def _show_preview_view(self):
        self._grid_container.setVisible(False)
        self.preview_view.setVisible(True)
        self._relayout_viewport()

    def _relayout_viewport(self):
        """强制整窗重排, 等效于"最大化→还原"触发的一次自顶向下 resize 级联。

        preview_view 构造起即隐藏, 首次 setVisible(True) 时其内部 QLabel
        仍持有隐藏期间缓存的几何; 仅 activate() 本层布局无法让父级
        (QSplitter / Dock) 重新分配空间, 故需沿父链逐层 invalidate+activate,
        再延迟一帧在显示事件处理完后重设 pixmap。
        """
        w = self._stack
        while w is not None:
            lay = w.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            w = w.parentWidget()
        QTimer.singleShot(0, self._refresh_preview_geometry)

    def _refresh_preview_geometry(self):
        if not self.preview_view.isVisible():
            return
        self.preview_view.updateGeometry()
        if self.preview_view._frames:
            self.preview_view._show_frame(self.preview_view._current)

    def _refresh_inline_preview(self, keep_idx: bool = True):
        if self._preview_mode == "grid":
            return
        if self._preview_mode == "single":
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
            if self.preview_view._range_sel.isChecked() and self.canvas.selection:
                frames = [self.model.get_frame(i) for i in sorted(self.canvas.selection)]
                frames = [f for f in frames if f is not None]
            else:
                frames = [f for f in self.model.frames if f is not None]
        self.preview_view.set_frames(frames, keep_idx=keep_idx)

    def _on_selection_changed(self):
        try:
            self.image_list._refresh_highlight()
        except Exception:
            pass
        if self._preview_mode == "grid":
            return
        if self._preview_mode == "single":
            self._refresh_inline_preview(keep_idx=False)
        elif self.preview_view._range_sel.isChecked():
            self._refresh_inline_preview(keep_idx=False)

    # ── 共享缩放 ───────────────────────
    def _shared_zoom_step(self, delta: float):
        if self._preview_mode == "grid":
            self.canvas.zoom_step(delta)
        else:
            self.preview_view.zoom_step(delta)

    def _shared_zoom_reset(self):
        if self._preview_mode == "grid":
            self.canvas.zoom_reset()
        else:
            self.preview_view.zoom_reset()

    # ── 预览 ───────────────────────────
    def _preview_selected(self):
        frames = self._get_selected_frames()
        if not frames:
            QMessageBox.information(self, "提示",
                "请先在画布上选择要预览的帧\n(点击选择, Ctrl+点击多选, Shift+点击范围选择)")
            return
        self.preview_view._range_sel.setChecked(True)
        self._mode_anim.setChecked(True)

    def _preview_all(self):
        self.model.normalize()
        frames = [f for f in self.model.frames if f is not None]
        if not frames:
            QMessageBox.information(self, "提示", "没有可预览的帧")
            return
        self.preview_view._range_all.setChecked(True)
        self._mode_anim.setChecked(True)

    def _get_selected_frames(self) -> List[Image.Image]:
        frames = []
        for idx in sorted(self.canvas.selection):
            frame = self.model.get_frame(idx)
            if frame is not None:
                frames.append(frame.copy())
        return frames

    # ── 保存 ───────────────────────────
    def _save(self):
        self.settings._save_current_fmt()

    # ── 主题切换 ───────────────────────
    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        app = QApplication.instance()
        if self._is_dark:
            ThemeManager.apply_dark_theme(app)
        else:
            ThemeManager.apply_light_theme(app)

        # 强制同步视口背景 (QSS 无法穿透 QGraphicsScene 底层)
        bg_color = QColor("#1a1d24") if self._is_dark else QColor("#313c52")
        self.canvas.setBackgroundBrush(QBrush(bg_color))
        self.preview_view._disp.setObjectName("GamePreview")
        self.preview_view._disp.style().unpolish(self.preview_view._disp)
        self.preview_view._disp.style().polish(self.preview_view._disp)
        self.canvas.redraw()
        apply_godot_theme(self, self._is_dark)


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main():
    if not HAS_PIL:
        print("错误: 需要安装 Pillow 库")
        print("  pip install Pillow")
        sys.exit(1)

    from editor_utils.app_init import install_translator, setup_app_icon
    app = QApplication(sys.argv)
    app.setApplicationName("Spritesheet Editor")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    # 设置应用默认字体 (用 pointSize 而非 pixelSize:
    # pixelSize 会使 font.pointSize() 返回 -1, 点击 QComboBox 弹出菜单时
    # Qt 内部以 font.pointSize() 调 setPointSize 触发 "Point size <= 0 (-1)" 警告;
    # 实际显示由 QSS 的 px 字号覆盖)
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)

    # 根据操作系统主题设定初始风格 (Qt6 原生检测)
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    if is_dark:
        ThemeManager.apply_dark_theme(app)
    else:
        ThemeManager.apply_light_theme(app)

    filepath = sys.argv[1] if len(sys.argv) > 1 else None
    window = SpriteSheetEditorWindow(filepath, is_dark=is_dark)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
