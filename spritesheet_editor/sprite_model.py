"""spritesheet_editor 数据层 — SpriteSheetModel (T17 自主文件迁出)。"""
from contextlib import contextmanager
from typing import List, Optional

from PIL import Image
from PySide6.QtCore import QObject, Signal

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
        self._change_batch_depth = 0
        self._change_pending = False

    def _emit_changed(self) -> None:
        if self._change_batch_depth:
            self._change_pending = True
        else:
            self.model_changed.emit()

    @contextmanager
    def batch_update(self):
        """合并多个连续修改，只通知界面刷新一次。"""
        self._change_batch_depth += 1
        try:
            yield
        finally:
            self._change_batch_depth -= 1
            if self._change_batch_depth == 0 and self._change_pending:
                self._change_pending = False
                self.model_changed.emit()

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
        self._emit_changed()

    def swap_frames(self, idx_a: int, idx_b: int) -> None:
        self.normalize()
        n = len(self.frames)
        if 0 <= idx_a < n and 0 <= idx_b < n:
            self.frames[idx_a], self.frames[idx_b] = self.frames[idx_b], self.frames[idx_a]
            self._emit_changed()

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
        self._emit_changed()

    def swap_rows(self, r1: int, r2: int) -> None:
        self.normalize()
        cols = self.columns
        if not (0 <= r1 < self.rows and 0 <= r2 < self.rows):
            return
        for c in range(cols):
            i1, i2 = r1 * cols + c, r2 * cols + c
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]
        self._emit_changed()

    def swap_cols(self, c1: int, c2: int) -> None:
        self.normalize()
        cols, rows = self.columns, self.rows
        if not (0 <= c1 < cols and 0 <= c2 < cols):
            return
        for r in range(rows):
            i1, i2 = r * cols + c1, r * cols + c2
            self.frames[i1], self.frames[i2] = self.frames[i2], self.frames[i1]
        self._emit_changed()

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
        self._emit_changed()

    def copy_rows(self, row_indices: List[int]) -> List[int]:
        """复制多行（按连续块插入到下方），返回插入块的起始行号"""
        self.normalize()
        sorted_rows = sorted(set(row_indices))
        if not sorted_rows or any(row < 0 or row >= self.rows for row in sorted_rows):
            return []
        cols = self.columns
        max_row = sorted_rows[-1]
        # 收集每行的副本
        copied: List[List[Optional[Image.Image]]] = []
        for row in sorted_rows:
            start = row * cols
            end = start + cols
            row_copy = []
            for i in range(start, end):
                frame = self.frames[i]
                row_copy.append(frame.copy() if frame is not None else None)
            copied.append(row_copy)
        # 在 max_row+1 处插入所有复制行
        insert_pos = (max_row + 1) * cols
        self.frames[insert_pos:insert_pos] = [f for row in copied for f in row]
        self.rows += len(sorted_rows)
        self._emit_changed()
        return list(range(max_row + 1, max_row + 1 + len(sorted_rows)))

    def delete_col(self, col_idx: int) -> None:
        """删除指定列, 后续列依次左移 (列数减 1, 行数不变)"""
        self.normalize()
        cols, rows = self.columns, self.rows
        if not (0 <= col_idx < cols) or cols <= 1:
            return
        new_frames: List[Optional[Image.Image]] = []
        for r in range(rows):
            row = self.frames[r * cols:(r + 1) * cols]
            del row[col_idx]
            new_frames.extend(row)
        self.frames = new_frames
        self.columns = cols - 1
        self._emit_changed()

    def delete_row(self, row_idx: int) -> None:
        """删除指定行, 后续行上移（行数减1）"""
        self.normalize()
        if not (0 <= row_idx < self.rows) or self.rows <= 1:
            return
        cols = self.columns
        start = row_idx * cols
        self.frames = self.frames[:start] + self.frames[start + cols:]
        self.rows -= 1
        self._emit_changed()

    def copy_col(self, col_idx: int) -> None:
        """复制指定列到右侧（列数加1）"""
        self.normalize()
        cols = self.columns
        if not (0 <= col_idx < cols):
            return
        new_frames = []
        for r in range(self.rows):
            row_start = r * cols
            row = self.frames[row_start:row_start + cols]
            col_copy = row[col_idx].copy() if row[col_idx] is not None else None
            row.insert(col_idx + 1, col_copy)
            new_frames.extend(row)
        self.frames = new_frames
        self.columns = cols + 1
        self._emit_changed()

    def copy_cols(self, col_indices: List[int]) -> List[int]:
        """复制多列（按连续块插入到右侧），返回插入块的列号列表"""
        self.normalize()
        sorted_cols = sorted(set(col_indices))
        if not sorted_cols or any(col < 0 or col >= self.columns for col in sorted_cols):
            return []
        cols = self.columns
        rows = self.rows
        max_col = sorted_cols[-1]
        # 按选中顺序复制每列
        copied_data: List[List[Optional[Image.Image]]] = []
        for col in sorted_cols:
            col_data = []
            for r in range(rows):
                idx = r * cols + col
                frame = self.frames[idx]
                col_data.append(frame.copy() if frame is not None else None)
            copied_data.append(col_data)
        # 重新构建 frames：在 max_col 后插入所有复制列
        new_frames: List[Optional[Image.Image]] = []
        for r in range(rows):
            row_start = r * cols
            row = self.frames[row_start:row_start + cols]
            insert_at = max_col + 1
            new_row = row[:insert_at]
            for col_data in copied_data:
                new_row.append(col_data[r])
            new_row.extend(row[insert_at:])
            new_frames.extend(new_row)
        self.frames = new_frames
        self.columns = cols + len(sorted_cols)
        self._emit_changed()
        # 返回插入块的列号列表
        return [max_col + 1 + i for i in range(len(sorted_cols))]

    def set_columns(self, new_cols: int) -> None:
        """改变列数但保持现有帧的网格位置不变

        直接改 columns 会使行优先的扁平索引重新洗牌 (帧错位),
        故按行重排: 加列时在每行末尾补空格, 减列时移除最右侧列。
        """
        self.normalize()
        old_cols = self.columns
        new_cols = max(1, int(new_cols))
        if new_cols == old_cols:
            return
        new_frames: List[Optional[Image.Image]] = []
        for r in range(self.rows):
            row = self.frames[r * old_cols:(r + 1) * old_cols]
            if new_cols > old_cols:
                row.extend([None] * (new_cols - old_cols))
            else:
                row = row[:new_cols]
            new_frames.extend(row)
        self.frames = new_frames
        self.columns = new_cols
        self._emit_changed()

    def get_frame(self, idx: int) -> Optional[Image.Image]:
        self.normalize()
        if 0 <= idx < len(self.frames):
            return self.frames[idx]
        return None
