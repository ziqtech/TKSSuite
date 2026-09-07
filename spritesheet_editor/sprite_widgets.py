"""spritesheet_editor 控件层 — 列表/画布/时间轴/预览/设置面板 (T17 自主文件迁出)。"""
from functools import partial
from pathlib import Path
from typing import List, Optional, Set, Tuple

from PIL import Image
from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsTextItem,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QCheckBox, QRadioButton,
    QGroupBox, QTextEdit,
    QMenu, QDialog, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QButtonGroup,
    QListView, QAbstractItemView, QSlider, QSplitter, QLineEdit, QScrollArea,
)
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QPalette, QColor, QIcon, QAction,
    QKeySequence, QShortcut, QFont, QPen, QBrush, QWheelEvent, QMouseEvent,
    QContextMenuEvent,
)
from PySide6.QtCore import (
    Qt, QObject, Signal, QTimer, QSize, QRect, QPoint, QRectF, QPointF,
)

from editor_utils.ui_helpers import themed_question, EditorComboBox, set_themed_icon

from sprite_image_ops import (ALPHA_MODES, ALPHA_MODE_DESC, PIXEL_FORMAT_DESC, TEXTURE_FORMATS,
    apply_alpha_mode, convert_pixel_format, pil_to_qpixmap)
from sprite_model import SpriteSheetModel


# ── 画布视图常量 (原主文件头部) ──
HEADER_ROW_H = 28
HEADER_COL_W = 36
DRAG_THRESHOLD = 5
LONG_PRESS_DURATION = 1000
SELECTION_BOX_COLOR = "#4a9eff"
SELECTION_BOX_FILL = QColor(74, 158, 255, 40)
SELECTION_BORDER_COLOR = "#80c0ff"
LONG_PRESS_PENDING_COLOR = "#ffb347"
LONG_PRESS_ACTIVE_COLOR = "#39e58c"

# 画布固定色 — 图像编辑器惯例: 画布恒为深色系以保证精灵/透明区可见性,
# 不随 UI 主题变化 (阶段 2 豁免项, 见 docs/PySide6样式体系整改方案.md)。
CANVAS_SCENE_BG = "#3a3a3a"      # 场景底色
CELL_EVEN = "#4a4a4a"            # 透明棋盘格 (偶)
CELL_ODD = "#444444"             # 透明棋盘格 (奇)
CELL_SELECTED = "#5a6a8a"        # 选中单元格填充
GRID_LINE = "#555555"            # 单元格网格线 / 预览面板边框
CANVAS_TEXT = "#cccccc"          # 画布尺寸标注文字
HIGHLIGHT_DASH = "#a0d0ff"       # 行/列高亮虚线
HEADER_BG = "#404040"            # 行/列表头底色
HEADER_BG_DRAG = "#505050"       # 行/列表头拖拽中底色
HEADER_BORDER = "#606060"        # 行/列表头边框
HEADER_TEXT = "#aaaaaa"          # 行/列表头文字
HEADER_HOVER_FILL = "#607080"    # 行/列悬停高亮填充
CORNER_BG = "#303030"            # 左上角块底色
PREVIEW_PANEL_BG = "#2a2a2a"     # 预览面板底色
DRAG_INDICATOR = "#ffcc00"       # 拖拽落点指示虚线
DEFAULT_FPS = 12


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

    def _ask_confirm(self, title: str, msg: str) -> bool:
        return themed_question(self, title, msg) == QMessageBox.Yes



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
        self.setBackgroundBrush(QBrush(QColor(CANVAS_SCENE_BG)))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)

        self.selection: Set[int] = set()
        self._drag_info: Optional[dict] = None
        self._header_drag: Optional[tuple] = None
        self._last_click_idx: int = -1
        self._zoom: float = 1.0
        self._copied_frame: Optional[Image.Image] = None  # 兼容旧 API, 已弃用
        # 块级剪贴板: 每条 (dr, dc, frame_or_None), 锚点 = min(selection)
        self._copied_cells: List[Tuple[int, int, Optional[Image.Image]]] = []

        self._selection_box: Optional[QGraphicsRectItem] = None
        self._box_start: Optional[Tuple[float, float]] = None
        self._long_press_timer: Optional[QTimer] = None
        self._long_press_idx: int = -1
        self._long_press_pos: Optional[Tuple[float, float]] = None
        self._long_press_pending: bool = False
        self._long_press_active: bool = False

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
        bg.setBrush(QBrush(QColor(CANVAS_SCENE_BG)))
        bg.setPen(QPen(Qt.NoPen))
        self.scene.addItem(bg)

        # 帧
        for i, frame in enumerate(m.frames):
            r, c = divmod(i, cols)
            x, y, x2, y2 = self._cell_bbox(r, c)

            # 单元格背景
            fill = QColor(CELL_EVEN) if i % 2 == 0 else QColor(CELL_ODD)
            if i in self.selection:
                fill = QColor(CELL_SELECTED)
            cell_bg = QGraphicsRectItem(x, y, cw, ch)
            cell_bg.setBrush(QBrush(fill))
            cell_bg.setPen(QPen(QColor(GRID_LINE)))
            cell_bg.setData(0, i)  # 存储帧索引
            self.scene.addItem(cell_bg)

            if frame is not None:
                try:
                    fw, fh = frame.size
                    if fw == cw and fh == ch:
                        display = frame
                    else:
                        # 始终居中对齐，大尺寸帧使用负坐标偏移
                        display = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                        ox = (cw - fw) // 2
                        oy = (ch - fh) // 2
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
                line1 = self.scene.addLine(x, y, x2, y2, QPen(QColor(GRID_LINE)))
                line2 = self.scene.addLine(x2, y, x, y2, QPen(QColor(GRID_LINE)))
                line1.setData(0, i)
                line2.setData(0, i)

            # 序号
            txt = QGraphicsTextItem(str(i))
            txt.setPos(x + 2, y + 1)
            txt.setDefaultTextColor(QColor(CANVAS_TEXT))
            font = QFont()
            font.setPixelSize(9)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 选中边框
        border_color = SELECTION_BORDER_COLOR
        if self._long_press_active:
            border_color = LONG_PRESS_ACTIVE_COLOR
        elif self._long_press_pending:
            border_color = LONG_PRESS_PENDING_COLOR
        for idx in self.selection:
            r, c = divmod(idx, cols)
            x, y, _, _ = self._cell_bbox(r, c)
            border = QGraphicsRectItem(x, y, cw, ch)
            border.setPen(QPen(QColor(border_color), 3 if self._long_press_active else 2))
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
            rh.setPen(QPen(QColor(HIGHLIGHT_DASH), 1, Qt.DashLine))
            rh.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(rh)

            # 列高亮
            cx = HEADER_COL_W + sc * (cw + pad)
            chl = QGraphicsRectItem(cx, HEADER_ROW_H, cw, th2 - HEADER_ROW_H)
            chl.setPen(QPen(QColor(HIGHLIGHT_DASH), 1, Qt.DashLine))
            chl.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(chl)

            # 行头高亮
            rhx, rhy, rhx2, rhy2 = self._row_header_bbox(sr)
            rhh = QGraphicsRectItem(rhx, rhy, rhx2 - rhx, rhy2 - rhy)
            rhh.setBrush(QBrush(QColor(HEADER_HOVER_FILL)))
            rhh.setPen(QPen(QColor(SELECTION_BORDER_COLOR)))
            self.scene.addItem(rhh)

            # 列头高亮
            chx, chy, chx2, chy2 = self._col_header_bbox(sc)
            chh = QGraphicsRectItem(chx, chy, chx2 - chx, chy2 - chy)
            chh.setBrush(QBrush(QColor(HEADER_HOVER_FILL)))
            chh.setPen(QPen(QColor(SELECTION_BORDER_COLOR)))
            self.scene.addItem(chh)

        # 行头
        for r in range(rows):
            x, y, x2, y2 = self._row_header_bbox(r)
            hdr_fill = QColor(HEADER_BG_DRAG) if (self._header_drag and self._header_drag[0] == "row"
                        and self._header_drag[1] == r) else QColor(HEADER_BG)
            hdr = QGraphicsRectItem(x, y, x2 - x, y2 - y)
            hdr.setBrush(QBrush(hdr_fill))
            hdr.setPen(QPen(QColor(HEADER_BORDER)))
            self.scene.addItem(hdr)
            txt = QGraphicsTextItem(f"R{r}")
            txt.setPos(x + HEADER_COL_W // 2 - 10, y + (ch) // 2 - 8)
            txt.setDefaultTextColor(QColor(HEADER_TEXT))
            font = QFont()
            font.setPixelSize(10)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 列头
        for c in range(cols):
            x, y, x2, y2 = self._col_header_bbox(c)
            hdr_fill = QColor(HEADER_BG_DRAG) if (self._header_drag and self._header_drag[0] == "col"
                        and self._header_drag[1] == c) else QColor(HEADER_BG)
            hdr = QGraphicsRectItem(x, y, x2 - x, y2 - y)
            hdr.setBrush(QBrush(hdr_fill))
            hdr.setPen(QPen(QColor(HEADER_BORDER)))
            self.scene.addItem(hdr)
            txt = QGraphicsTextItem(f"C{c}")
            txt.setPos(x + cw // 2 - 10, y + HEADER_ROW_H // 2 - 8)
            txt.setDefaultTextColor(QColor(HEADER_TEXT))
            font = QFont()
            font.setPixelSize(10)
            txt.setFont(font)
            self.scene.addItem(txt)

        # 左上角
        corner = QGraphicsRectItem(0, 0, HEADER_COL_W, HEADER_ROW_H)
        corner.setBrush(QBrush(QColor(CORNER_BG)))
        corner.setPen(QPen(QColor(HEADER_BORDER)))
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
                self._cancel_selection_box()
                self.redraw()
                return

        idx = self._idx_at_pos(x, y)

        # Ctrl+点击: 切换选中
        if modifiers & Qt.ControlModifier:
            self._long_press_pending = False
            self._long_press_active = False
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
            self._long_press_pending = False
            self._long_press_active = False
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
            # 点击空白区域，清除选中并开始框选
            if self.selection:
                self.selection.clear()
                if hasattr(self.editor, "image_list"):
                    self.editor.image_list._selected_idx = -1
                self.update_selection_display()
                self.selectionChangedCustom.emit()
            self._box_start = (x, y)
            self._long_press_timer = None
            self._long_press_idx = -1
            self._long_press_pending = False
            self._long_press_active = False
            return

        # 点击帧，开始长按计时器
        self._box_start = (x, y)
        self._long_press_idx = idx
        self._long_press_pos = (x, y)
        self._last_click_idx = idx
        if idx not in self.selection:
            self.selection = {idx}
        self._long_press_pending = True
        self._long_press_active = False
        if hasattr(self.editor, "image_list"):
            self.editor.image_list._selected_idx = idx
        self.update_selection_display()
        self.selectionChangedCustom.emit()
        try:
            self.editor._status_label.setText("按住中… 长按 1 秒进入拖拽")
        except AttributeError:
            pass

        # 启动长按计时器
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._long_press_timer.start(LONG_PRESS_DURATION)

    def _on_long_press(self):
        """长按触发，取消框选并进入单帧拖拽模式"""
        self._long_press_timer = None
        self._long_press_pending = False
        self._long_press_active = True
        # 取消框选意图，转入拖拽模式
        self._box_start = None
        # 移除已绘制的框选矩形和临时高亮（如果有）
        if self._selection_box:
            try:
                self.scene.removeItem(self._selection_box)
            except RuntimeError:
                pass
            self._selection_box = None
        self._remove_temp_items("sel_preview")
        if self._long_press_idx >= 0:
            sx, sy = self._long_press_pos if self._long_press_pos else (0, 0)
            self._drag_info = {
                "from_idx": self._long_press_idx,
                "start_x": sx,
                "start_y": sy,
                "moved": False
            }
            self.redraw()
            try:
                self.editor._status_label.setText("长按成功，可拖动当前帧")
            except AttributeError:
                pass

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

        # 长按后的帧拖拽模式
        if self._drag_info and self._long_press_timer is None:
            dx = abs(x - self._drag_info["start_x"])
            dy = abs(y - self._drag_info["start_y"])
            if not self._drag_info["moved"] and (dx > DRAG_THRESHOLD or dy > DRAG_THRESHOLD):
                self._drag_info["moved"] = True
            if self._drag_info["moved"]:
                self._show_frame_drag_indicator(x, y)
            return

        # 框选模式
        if self._box_start is not None:
            # 用户开始移动并超过阈值，视为已进入框选，取消长按计时器
            if self._long_press_timer is not None:
                bdx = abs(x - self._box_start[0])
                bdy = abs(y - self._box_start[1])
                if bdx > DRAG_THRESHOLD or bdy > DRAG_THRESHOLD:
                    self._long_press_timer.stop()
                    self._long_press_timer = None
                    self._long_press_idx = -1
                    self._long_press_pos = None
                    self._long_press_pending = False
                    self._long_press_active = False
                    self.update_selection_display()
            self._update_selection_box(x, y)

    def _cancel_selection_box(self):
        """取消框选，清理临时对象"""
        self._remove_temp_items("sel_preview")
        if self._selection_box:
            try:
                self.scene.removeItem(self._selection_box)
            except RuntimeError:
                pass
            self._selection_box = None
        self._box_start = None
        self._long_press_pending = False
        self._long_press_active = False
        if self._long_press_timer:
            self._long_press_timer.stop()
            self._long_press_timer = None

    def _update_selection_box(self, end_x: float, end_y: float):
        """更新框选矩形和预览选中效果"""
        start_x, start_y = self._box_start
        sx, sy = min(start_x, end_x), min(start_y, end_y)
        w, h = abs(end_x - start_x), abs(end_y - start_y)

        if self._selection_box:
            try:
                self._selection_box.setRect(sx, sy, w, h)
            except RuntimeError:
                self._selection_box = None
        if not self._selection_box:
            self._selection_box = QGraphicsRectItem(sx, sy, w, h)
            self._selection_box.setPen(QPen(QColor(SELECTION_BOX_COLOR), 1))
            self._selection_box.setBrush(QBrush(SELECTION_BOX_FILL))
            self._selection_box.setZValue(999)
            self.scene.addItem(self._selection_box)

        # 预览选中效果
        self._remove_temp_items("sel_preview")
        sel_rect = QRectF(sx, sy, w, h)
        cols = self.model.columns
        for idx in range(len(self.model.frames)):
            r, c = divmod(idx, cols)
            fx, fy, fx2, fy2 = self._cell_bbox(r, c)
            if (fx < sel_rect.right() and fx2 > sel_rect.left() and
                fy < sel_rect.bottom() and fy2 > sel_rect.top()):
                rect_item = QGraphicsRectItem(fx, fy, fx2 - fx, fy2 - fy)
                rect_item.setPen(QPen(QColor(SELECTION_BOX_COLOR), 2))
                rect_item.setBrush(QBrush(QColor(74, 158, 255, 60)))
                rect_item.setZValue(998)
                rect_item.setData(0, "sel_preview")
                self.scene.addItem(rect_item)

    def _finish_selection_box(self, end_x: float, end_y: float):
        """完成框选，选中框内所有帧"""
        self._remove_temp_items("sel_preview")
        if self._selection_box:
            try:
                rect = self._selection_box.rect()
                cols = self.model.columns
                newly_selected: Set[int] = set()
                for idx in range(len(self.model.frames)):
                    r, c = divmod(idx, cols)
                    fx, fy, fx2, fy2 = self._cell_bbox(r, c)
                    # 线框与矩形相交即选中
                    if (fx < rect.right() and fx2 > rect.left() and
                        fy < rect.bottom() and fy2 > rect.top()):
                        newly_selected.add(idx)
                self.scene.removeItem(self._selection_box)
                self._selection_box = None
                if newly_selected:
                    self.selection = newly_selected
                    if hasattr(self.editor, "image_list"):
                        self.editor.image_list._selected_idx = min(newly_selected)
                    self.update_selection_display()
                    self.selectionChangedCustom.emit()
            except RuntimeError:
                self._selection_box = None

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
            self._long_press_pending = False
            self._long_press_active = False
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

        # 取消长按计时器
        if self._long_press_timer:
            self._long_press_timer.stop()
            self._long_press_timer = None

        # 长按触发的帧拖拽
        if self._drag_info and self._long_press_timer is None:
            if self._drag_info.get("moved"):
                to_idx = self._idx_at_pos(x, y)
                from_idx = self._drag_info["from_idx"]
                if to_idx >= 0 and to_idx != from_idx:
                    self.model.swap_frames(from_idx, to_idx)
                    self.selection = {to_idx}
                    if hasattr(self.editor, "image_list"):
                        self.editor.image_list._selected_idx = to_idx
                    self._drag_info = None
                    self._long_press_active = False
                    self.editor._on_model_changed()
                    return
            self._drag_info = None
            self._long_press_active = False
            self.update_selection_display()
            return

        # 框选模式释放
        if self._box_start is not None:
            self._finish_selection_box(x, y)
            self._box_start = None
            self._long_press_pending = False
            self.update_selection_display()

    def contextMenuEvent(self, event: QContextMenuEvent):
        pos = self.mapToScene(event.pos())
        idx = self._idx_at_pos(pos.x(), pos.y())
        if idx < 0:
            super().contextMenuEvent(event)
            return

        frame = self.model.get_frame(idx)
        # 命中点是否在 selection 内: 决定"作用对象 = selection" 还是 "作用对象 = 单格"
        in_selection = idx in self.selection and len(self.selection) > 0
        n = len(self.selection) if in_selection else 0

        menu = QMenu(self)
        copy_label = f"复制 ({n})" if in_selection and n > 1 else "复制"
        paste_label = f"粘贴 ({len(self._copied_cells)})" if self._copied_cells else "粘贴"
        act_copy = menu.addAction(copy_label)
        act_copy.setEnabled(frame is not None)
        act_paste = menu.addAction(paste_label)
        # 粘贴可用条件: 剪贴板非空, 且 (有 selection, 或命中点有效)
        act_paste.setEnabled(bool(self._copied_cells) and (in_selection or idx >= 0))
        menu.addSeparator()
        act_copy_row = menu.addAction("复制行")
        act_delete_row = menu.addAction("删除行")
        menu.addSeparator()
        act_copy_col = menu.addAction("复制列")
        act_delete_col = menu.addAction("删除列")
        menu.addSeparator()
        act_flip = menu.addAction("水平翻转")
        act_flip.setEnabled(frame is not None)
        menu.addSeparator()
        act_delete = menu.addAction("删除")
        act_delete.setEnabled(frame is not None)

        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            if in_selection and len(self.selection) > 1:
                n_copy = self.copy_selection()
                try:
                    self.editor._status_label.setText(f"已复制 {n_copy} 个单元格")
                except Exception:
                    pass
            else:
                self.copy_cell(idx)
        elif chosen is act_paste:
            if in_selection:
                pasted = self.paste_cells_to(set(self.selection))
                try:
                    self.editor._status_label.setText(
                        f"已粘贴 {len(pasted)} 个单元格 (越界 {len(self._copied_cells) - len(pasted)} 个已丢弃)"
                        if pasted else "粘贴未命中任何单元格")
                except Exception:
                    pass
            else:
                self.paste_cell(idx)
        elif chosen is act_copy_row:
            self.editor._copy_row()
        elif chosen is act_delete_row:
            self.editor._delete_row()
        elif chosen is act_copy_col:
            self.editor._copy_col()
        elif chosen is act_delete_col:
            self.editor._delete_col()
        elif chosen is act_flip:
            self.editor._flip_horizontal()
        elif chosen is act_delete:
            self.delete_selected()

    def _show_frame_drag_indicator(self, cx: float, cy: float) -> None:
        self._remove_temp_items("drag_tgt")
        to_idx = self._idx_at_pos(cx, cy)
        if to_idx >= 0:
            r, c = divmod(to_idx, self.model.columns)
            x, y, x2, y2 = self._cell_bbox(r, c)
            pen = QPen(QColor(DRAG_INDICATOR), 2, Qt.DashLine)
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
                pen = QPen(QColor(DRAG_INDICATOR), 2, Qt.DashLine)
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
                pen = QPen(QColor(DRAG_INDICATOR), 2, Qt.DashLine)
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
            # 单元格背景: QGraphicsRectItem, 无边框或边框色 GRID_LINE
            if isinstance(item, QGraphicsRectItem):
                pen_color = item.pen().color().name()
                # 跳过选中边框 (SELECTION_BORDER_COLOR) / 行高亮 (HIGHLIGHT_DASH) / 列高亮 / header 等
                if pen_color in (SELECTION_BORDER_COLOR.lower(),
                                 LONG_PRESS_PENDING_COLOR.lower(),
                                 LONG_PRESS_ACTIVE_COLOR.lower(),
                                 HIGHLIGHT_DASH.lower(), HEADER_BORDER.lower(),
                                 DRAG_INDICATOR.lower()):
                    continue
                if pen_color == GRID_LINE.lower() or item.pen().style() == Qt.NoPen:
                    r, c = divmod(idx, cols)
                    fill = QColor(CELL_SELECTED) if idx in self.selection else (
                        QColor(CELL_EVEN) if idx % 2 == 0 else QColor(CELL_ODD))
                    item.setBrush(QBrush(fill))

        # 选中边框 → 删除旧的, 按需重建 (轻量)
        for item in list(self.scene.items()):
            if (isinstance(item, QGraphicsRectItem) and
                    item.pen().color().name() in {
                        SELECTION_BORDER_COLOR.lower(),
                        LONG_PRESS_PENDING_COLOR.lower(),
                        LONG_PRESS_ACTIVE_COLOR.lower(),
                    }):
                self.scene.removeItem(item)
        # 行/列高亮 → 删除旧的
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsRectItem) and item.pen().color().name() == HIGHLIGHT_DASH.lower():
                self.scene.removeItem(item)

        # 重建选中边框
        for idx in self.selection:
            r, c = divmod(idx, cols)
            x = HEADER_COL_W + c * (cw + m.padding)
            y = HEADER_ROW_H + r * (ch + m.padding)
            border = QGraphicsRectItem(x, y, cw, ch)
            border_color = SELECTION_BORDER_COLOR
            border_width = 2
            if idx == self._long_press_idx and self._long_press_active:
                border_color = LONG_PRESS_ACTIVE_COLOR
                border_width = 3
            elif idx == self._long_press_idx and self._long_press_pending:
                border_color = LONG_PRESS_PENDING_COLOR
            border.setPen(QPen(QColor(border_color), border_width))
            border.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(border)

        # 单选时高亮整行/整列 (轻量)
        if len(self.selection) == 1:
            sel_idx = next(iter(self.selection))
            sr, sc = divmod(sel_idx, cols)
            tw, th = self._total_size()

            ry = HEADER_ROW_H + sr * (ch + m.padding)
            rh = QGraphicsRectItem(HEADER_COL_W, ry, tw - HEADER_COL_W, ch)
            rh.setPen(QPen(QColor(HIGHLIGHT_DASH), 1, Qt.DashLine))
            rh.setBrush(QBrush(Qt.NoBrush))
            self.scene.addItem(rh)

            cx = HEADER_COL_W + sc * (cw + m.padding)
            chl = QGraphicsRectItem(cx, HEADER_ROW_H, cw, th - HEADER_ROW_H)
            chl.setPen(QPen(QColor(HIGHLIGHT_DASH), 1, Qt.DashLine))
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
        with self.model.batch_update():
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
        with self.model.batch_update():
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
        with self.model.batch_update():
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
        with self.model.batch_update():
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

    def copy_cell(self, idx: int) -> None:
        frame = self.model.get_frame(idx)
        if frame is None:
            return
        self._copied_frame = frame.copy()
        # 块级剪贴板: 单格也走批量, 方便 paste_cell 走同一路径
        self._copied_cells = [(0, 0, frame.copy())]
        try:
            self.editor._status_label.setText(f"已复制单元格 #{idx}")
        except Exception:
            pass

    def paste_cell(self, idx: int) -> None:
        """单格粘贴保留: 优先用 _copied_frame 旧路径, 否则退化到 _copied_cells 的 1×1."""
        if self._copied_frame is not None:
            self.model.normalize()
            if not (0 <= idx < len(self.model.frames)):
                return
            self.model.frames[idx] = self._copied_frame.copy()
            self.selection = {idx}
            self._last_click_idx = idx
            if hasattr(self.editor, "image_list"):
                self.editor.image_list._selected_idx = idx
            self.editor._on_model_changed()
            try:
                self.editor._status_label.setText(f"已粘贴到单元格 #{idx}")
            except Exception:
                pass
            return
        # 退化到块级粘贴
        if not self._copied_cells:
            return
        pasted = self.paste_cells_to({idx})
        try:
            self.editor._status_label.setText(f"已粘贴到单元格 #{idx}")
        except Exception:
            pass

    # ── 块级复制/粘贴 ──────────────────────
    def copy_selection(self) -> int:
        """把当前 selection 装入 _copied_cells. 返回复制条目数."""
        sel = self.selection
        if not sel:
            return 0
        m = self.model
        m.normalize()
        cols = m.columns
        anchor = min(sel)
        ar, ac = divmod(anchor, cols)
        cells: List[Tuple[int, int, Optional[Image.Image]]] = []
        for idx in sorted(sel):
            r, c = divmod(idx, cols)
            f = m.frames[idx]
            cells.append((r - ar, c - ac, f.copy() if f is not None else None))
        self._copied_cells = cells
        # 兼容旧路径: 单帧时也填一下 _copied_frame
        self._copied_frame = cells[0][2].copy() if len(cells) == 1 and cells[0][2] is not None else None
        return len(cells)

    def shortcut_copy(self) -> None:
        """处理 Ctrl+C：优先复制多选块，否则复制当前帧。"""
        if len(self.selection) > 1:
            count = self.copy_selection()
        else:
            idx = next(iter(self.selection), self._last_click_idx)
            if idx < 0 or self.model.get_frame(idx) is None:
                return
            self.copy_cell(idx)
            count = 1
        try:
            self.editor._status_label.setText(f"已复制 {count} 个单元格")
        except AttributeError:
            pass

    def shortcut_paste(self) -> None:
        """处理 Ctrl+V：粘贴到选区锚点或当前帧。"""
        if not self._copied_cells:
            return
        target = set(self.selection)
        if not target and self._last_click_idx >= 0:
            target = {self._last_click_idx}
        if not target:
            return
        pasted = self.paste_cells_to(target)
        if pasted:
            try:
                self.editor._status_label.setText(f"已粘贴 {len(pasted)} 个单元格")
            except AttributeError:
                pass

    def paste_cells_to(self, target: Set[int]) -> Set[int]:
        """Excel 语义: target 只决定锚点(min), 剪贴板按形状铺, 越界丢弃.
        返回实际贴入的位置 (None 帧不算)."""
        if not self._copied_cells or not target:
            return set()
        m = self.model
        m.normalize()
        cols, rows = m.columns, m.rows
        anchor = min(target)
        ar, ac = divmod(anchor, cols)
        pasted: Set[int] = set()
        for dr, dc, f in self._copied_cells:
            tr, tc = ar + dr, ac + dc
            if not (0 <= tr < rows and 0 <= tc < cols):
                continue
            idx = tr * cols + tc
            m.frames[idx] = f.copy() if f is not None else None
            if f is not None:
                pasted.add(idx)
        # 粘贴后 selection = 实际贴入的位置
        self.selection = pasted
        self._last_click_idx = max(pasted) if pasted else -1
        if hasattr(self.editor, "image_list") and pasted:
            self.editor.image_list._selected_idx = max(pasted)
        self.editor._on_model_changed()
        return pasted


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
                painter.setPen(QPen(QColor(DRAG_INDICATOR), 2))
                painter.setBrush(QBrush(QColor(CANVAS_SCENE_BG)))
                painter.drawRect(x0 - 1, y0 - 1, sz + 2, sz + 2)
            else:
                painter.setPen(QPen(QColor(GRID_LINE)))
                painter.setBrush(QBrush(QColor(PREVIEW_PANEL_BG)))
                painter.drawRect(x0, y0, sz, sz)

            # 缩略图
            if i < len(self._thumbs):
                pm = self._thumbs[i]
                px = x0 + (sz - pm.width()) // 2
                py = y0 + (sz - pm.height()) // 2
                painter.drawPixmap(px, py, pm)

            # 序号
            painter.setPen(QColor(CANVAS_TEXT))
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

        self._btn_play = QPushButton("播放")
        self._btn_play.setProperty("class", "CompactBtn")
        self._btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self._btn_play)

        # P4-1: 播放控制四钮改用显式 SVG 图标 (原 ⏮◀▶⏭ emoji, 此前被误清为空串)
        for icon, slot in [("first", self._go_first), ("prev", self._prev_frame),
                           ("next", self._next_frame), ("last", self._go_last)]:
            btn = QPushButton("")
            set_themed_icon(btn, icon)
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
            self._btn_play.setText("暂停")
            self._schedule_next()

    def stop(self):
        self._playing = False
        self._timer.stop()
        self._btn_play.setText("播放")

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
    """右侧面板: 网格参数设置 + 导出 + 无损像素调节"""

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

        self._btn_shift_up.clicked.connect(partial(self._shift_pixels, 0, -1))
        self._btn_shift_down.clicked.connect(partial(self._shift_pixels, 0, 1))
        self._btn_shift_left.clicked.connect(partial(self._shift_pixels, -1, 0))
        self._btn_shift_right.clicked.connect(partial(self._shift_pixels, 1, 0))

        # — 拉伸 / 缩放 (无损化) —
        shift_layout.addWidget(QLabel("边缘操作 (无损防裁剪):"))

        mode_row = QHBoxLayout()
        self._radio_stretch = QRadioButton("向外拉伸 (变大)")
        self._radio_stretch.setChecked(True)
        self._radio_shrink = QRadioButton("向内收缩 (变小)")
        self._radio_stretch.toggled.connect(self._on_transform_mode_changed)
        mode_row.addWidget(self._radio_stretch)
        mode_row.addWidget(self._radio_shrink)
        shift_layout.addLayout(mode_row)

        scale_val_row = QHBoxLayout()
        scale_val_row.addWidget(QLabel("幅度(%):"))
        self._spin_scale_pct = QSpinBox()
        # 彻底移除负数，只填绝对比例，具体是变大还是变小由上方的单选框决定
        self._spin_scale_pct.setRange(1, 500)
        self._spin_scale_pct.setValue(10)
        self._spin_scale_pct.setToolTip("输入要调整的百分比 (例如 10 代表 10%)")
        scale_val_row.addWidget(self._spin_scale_pct)
        shift_layout.addLayout(scale_val_row)

        stretch_btn_grid = QGridLayout()
        stretch_btn_grid.setSpacing(4)
        self._btn_dir_up = QPushButton("上拉伸")
        self._btn_dir_down = QPushButton("下拉伸")
        self._btn_dir_left = QPushButton("左拉伸")
        self._btn_dir_right = QPushButton("右拉伸")
        self._btn_scale_up = QPushButton("中心放大")
        self._btn_scale_down = QPushButton("中心缩小")

        stretch_btn_grid.addWidget(self._btn_dir_up, 0, 0)
        stretch_btn_grid.addWidget(self._btn_dir_down, 0, 1)
        stretch_btn_grid.addWidget(self._btn_dir_left, 1, 0)
        stretch_btn_grid.addWidget(self._btn_dir_right, 1, 1)
        stretch_btn_grid.addWidget(self._btn_scale_up, 2, 0)
        stretch_btn_grid.addWidget(self._btn_scale_down, 2, 1)
        shift_layout.addLayout(stretch_btn_grid)

        self._btn_dir_up.clicked.connect(partial(self._directional_modify, 0, -1))
        self._btn_dir_down.clicked.connect(partial(self._directional_modify, 0, 1))
        self._btn_dir_left.clicked.connect(partial(self._directional_modify, -1, 0))
        self._btn_dir_right.clicked.connect(partial(self._directional_modify, 1, 0))
        self._btn_scale_up.clicked.connect(partial(self._center_scale, True))
        self._btn_scale_down.clicked.connect(partial(self._center_scale, False))

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

        # ── 导出设置 ──
        self._export_section = QWidget()
        export_layout = QVBoxLayout(self._export_section)

        tex_row = QHBoxLayout()
        tex_row.addWidget(QLabel("纹理格式:"))
        self._tex_combo = EditorComboBox()
        self._tex_combo.addItems(list(TEXTURE_FORMATS.keys()))
        self._tex_combo.currentTextChanged.connect(self._on_tex_fmt_changed)
        tex_row.addWidget(self._tex_combo)
        export_layout.addLayout(tex_row)

        pix_row = QHBoxLayout()
        pix_row.addWidget(QLabel("像素格式:"))
        self._fmt_combo = EditorComboBox()
        self._fmt_combo.addItems(TEXTURE_FORMATS["PNG-32"])
        self._fmt_combo.setCurrentText("RGBA8888")
        self._fmt_combo.currentTextChanged.connect(self._refresh_export_info)
        pix_row.addWidget(self._fmt_combo)
        export_layout.addLayout(pix_row)

        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("透明处理:"))
        self._alpha_combo = EditorComboBox()
        self._alpha_combo.addItems(ALPHA_MODES)
        self._alpha_combo.setCurrentText("无")
        self._alpha_combo.currentTextChanged.connect(self._refresh_export_info)
        alpha_row.addWidget(self._alpha_combo)
        export_layout.addLayout(alpha_row)

        export_layout.addWidget(QLabel("格式说明:"))
        self._fmt_desc = QTextEdit()
        self._fmt_desc.setReadOnly(True)
        self._fmt_desc.setMaximumHeight(80)
        self._fmt_desc.setProperty("class", "MonoText")
        export_layout.addWidget(self._fmt_desc)

        export_layout.addWidget(QLabel("格式预览:"))
        self._fmt_preview = QTextEdit()
        self._fmt_preview.setReadOnly(True)
        self._fmt_preview.setMaximumHeight(60)
        self._fmt_preview.setProperty("class", "MonoText")
        export_layout.addWidget(self._fmt_preview)

        btn_save = QPushButton("保存图集")
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
        return [
            ("网格设置", self._grid_section),
            ("像素调节", self._shift_section),
            ("输出信息", self._info_section),
            ("导出", self._export_section),
        ]

    # ── 核心无损化方法 ───────────────────────────
    def _get_or_init_lossless_state(self, frame: Image.Image) -> dict:
        """从 PIL 的 info 字典中提取或初始化无损状态数据"""
        if "lossless_content" not in frame.info:
            if frame.mode != "RGBA":
                frame = frame.convert("RGBA")
            bbox = frame.getbbox()
            if not bbox:
                bbox = (0, 0, frame.width, frame.height)
            l, t, r, b = bbox
            frame.info["lossless_content"] = frame.crop(bbox)
            frame.info["lossless_orig_W"] = frame.width
            frame.info["lossless_orig_H"] = frame.height
            # 记录精准的浮点数学边框 [left, top, width, height]
            frame.info["lossless_rect"] = [float(l), float(t), float(r - l), float(b - t)]
        return frame.info

    def _apply_lossless_render(self, idx: int, info: dict):
        """完全基于精准浮点状态系与原始素材，进行防损耗渲染并更新画布"""
        l, t, w, h = info["lossless_rect"]
        render_w, render_h = max(1, int(round(w))), max(1, int(round(h)))
        render_l, render_t = int(round(l)), int(round(t))

        # 核心：永远从"未被破坏的原图"进行唯一一次变形
        content = info["lossless_content"]
        resized = content.resize((render_w, render_h), Image.NEAREST)

        orig_W, orig_H = info["lossless_orig_W"], info["lossless_orig_H"]

        # 动态对称扩展画布 (防裁剪绝对约束)
        E_x = max(0, -render_l, render_l + render_w - orig_W)
        E_y = max(0, -render_t, render_t + render_h - orig_H)

        new_W = orig_W + 2 * E_x
        new_H = orig_H + 2 * E_y
        new_img = Image.new("RGBA", (new_W, new_H), (0, 0, 0, 0))

        paste_x = render_l + E_x
        paste_y = render_t + E_y

        new_img.paste(resized, (paste_x, paste_y))

        # 传递灵魂：把状态信息拷贝给新生成的帧，实现跨时代的无损溯源
        new_img.info = info.copy()
        self.model.frames[idx] = new_img

    # ── UI 事件回调 ───────────────────────────
    def _on_transform_mode_changed(self):
        if self._radio_stretch.isChecked():
            self._btn_dir_up.setText("上拉伸")
            self._btn_dir_down.setText("下拉伸")
            self._btn_dir_left.setText("左拉伸")
            self._btn_dir_right.setText("右拉伸")
        else:
            self._btn_dir_up.setText("上收缩")
            self._btn_dir_down.setText("下收缩")
            self._btn_dir_left.setText("左收缩")
            self._btn_dir_right.setText("右收缩")

    # ── 平移 ───────────────────────────
    def _shift_pixels(self, dx: int, dy: int):
        sel = self.editor.canvas.selection
        if not sel:
            current = getattr(self.editor.canvas, "timeline", None)
            if current and 0 <= current.current_index < len(self.model.frames):
                sel = {current.current_index}
        if not sel: return

        px = self._spin_shift_px.value()
        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None: continue

            info = self._get_or_init_lossless_state(frame)
            rect = info["lossless_rect"]

            # 【修复】必须创建全新的列表，切断 Python 浅拷贝带来的内存地址共享！
            # 否则平移其中一帧，会暗中破坏其他复制帧的坐标数据
            new_l = rect[0] + dx * px
            new_t = rect[1] + dy * px
            info["lossless_rect"] = [new_l, new_t, rect[2], rect[3]]

            self._apply_lossless_render(idx, info)

        self.editor._on_model_changed()
        self._update_output_info()

    # ── 边缘定向操作 ────────────────────────
    def _directional_modify(self, dx: int, dy: int):
        sel = self.editor.canvas.selection
        if not sel: return

        pct = self._spin_scale_pct.value()
        is_stretch = self._radio_stretch.isChecked()

        # 拉伸即放大(>1)，收缩即缩小(<1)
        ratio = 1.0 + (pct / 100.0) if is_stretch else max(0.01, 1.0 - (pct / 100.0))

        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None: continue

            info = self._get_or_init_lossless_state(frame)
            rect = info["lossless_rect"]
            l, t, w, h = rect

            # 单纯操控指定边缘，锚定对侧
            if dx > 0:   # 操作右侧 (固定左侧，只改变宽)
                w = w * ratio
            elif dx < 0: # 操作左侧 (固定右侧，改变宽，并且左边界发生位移)
                new_w = w * ratio
                l = l + w - new_w
                w = new_w
            elif dy > 0: # 操作下侧 (固定上方，只改变高)
                h = h * ratio
            elif dy < 0: # 操作上侧 (固定下方，改变高，并且上边界发生位移)
                new_h = h * ratio
                t = t + h - new_h
                h = new_h

            # 分配新列表确保切断浅拷贝引用
            info["lossless_rect"] = [l, t, w, h]
            self._apply_lossless_render(idx, info)

        self.editor._on_model_changed()
        self._update_output_info()

    # ── 全局中心等比缩放 ───────────────────────────
    def _center_scale(self, enlarge: bool):
        sel = self.editor.canvas.selection
        if not sel: return

        pct_val = self._spin_scale_pct.value()
        # 放大按钮直接放大，缩小按钮直接缩小 (不再受到符号或模式限制)
        ratio = 1.0 + (pct_val / 100.0) if enlarge else max(0.01, 1.0 - (pct_val / 100.0))

        for idx in sel:
            frame = self.model.frames[idx]
            if frame is None: continue

            info = self._get_or_init_lossless_state(frame)
            rect = info["lossless_rect"]
            l, t, w, h = rect

            cx, cy = l + w/2.0, t + h/2.0
            w, h = w * ratio, h * ratio
            l, t = cx - w/2.0, cy - h/2.0

            info["lossless_rect"] = [l, t, w, h]
            self._apply_lossless_render(idx, info)

        self.editor._on_model_changed()
        self._update_output_info()

    # (以下原有的通用参数绑定与检查器逻辑保持不变)
    def _on_param_changed(self):
        if self._suppress_changes: return
        sender = self.sender()
        if sender in (self._spin_cell_width, self._spin_cell_height):
            self.model._cell_size_set = True
        # 改列数需按行重排数据, 保持现有帧位置不变 (直接赋值会错位)
        self.model.set_columns(self._spin_columns.value())
        self.model.rows = self._spin_rows.value()
        self.model.padding = self._spin_padding.value()
        self.model.cell_width = self._spin_cell_width.value()
        self.model.cell_height = self._spin_cell_height.value()
        self.editor._on_model_changed()
        self._update_output_info()
        self._refresh_export_info()

    def _auto_detect(self):
        self.model.auto_detect_cell_size()
        self._suppress_changes = True
        self._spin_cell_width.setValue(self.model.cell_width)
        self._spin_cell_height.setValue(self.model.cell_height)
        self._suppress_changes = False
        self.model._cell_size_set = False
        self.editor._on_model_changed()
        self._update_output_info()
        self._refresh_export_info()

    def _move_row(self, delta: int):
        sel = self.editor.canvas.selection
        if not sel:
            if self.model.frame_count == 0: return
            for i, f in enumerate(self.model.frames):
                if f is not None:
                    sel = {i}
                    self.editor.canvas.selection = sel
                    break
        if not sel: return
        cols = max(1, int(self.model.columns))
        idx = min(sel)
        r = idx // cols
        target = r + delta
        if 0 <= target < self.model.rows:
            self.model.swap_rows(r, target)
            new_sel = set()
            for s in sel:
                sr, sc = divmod(s, cols)
                if sr == r: new_sel.add(target * cols + sc)
                elif sr == target: new_sel.add(r * cols + sc)
                else: new_sel.add(s)
            self.editor.canvas.selection = new_sel
            self.editor._on_model_changed()
            self._update_output_info()

    def _move_col(self, delta: int):
        sel = self.editor.canvas.selection
        if not sel:
            if self.model.frame_count == 0: return
            for i, f in enumerate(self.model.frames):
                if f is not None:
                    sel = {i}
                    self.editor.canvas.selection = sel
                    break
        if not sel: return
        cols = max(1, int(self.model.columns))
        idx = min(sel)
        c = idx % cols
        target = c + delta
        if 0 <= target < self.model.columns:
            self.model.swap_cols(c, target)
            new_sel = set()
            for s in sel:
                sr, sc = divmod(s, cols)
                if sc == c: new_sel.add(sr * cols + target)
                elif sc == target: new_sel.add(sr * cols + c)
                else: new_sel.add(s)
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

        lines: list[str] = []
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
        if not fp: return
        converted.save(fp, "PNG")
        self.editor._dirty = False
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
        except (AttributeError, ValueError):
            self._output_info.setPlainText("(无数据)")

    def refresh_values(self):
        self._suppress_changes = True
        self._spin_columns.setValue(self.model.columns)
        self._spin_rows.setValue(self.model.rows)
        self._spin_padding.setValue(self.model.padding)
        self._spin_cell_width.setValue(self.model.cell_width)
        self._spin_cell_height.setValue(self.model.cell_height)
        self._suppress_changes = False
        self._update_output_info()
        self._refresh_export_info()
