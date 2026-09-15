"""FONT9696 位图字体渲染助手（用于动画预览中的伤害飘字）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'font_editor'))

from font9696_codec import Font9696


# 原版 FONT9696 调色板索引（用于战斗飘字）。
FONT_COLORS = {
    18: (255, 0, 0),
    20: (0, 255, 0),
    21: (0, 255, 255),
    23: (255, 0, 255),
    24: (255, 128, 64),
    28: (128, 64, 255),
    31: (255, 255, 255),
}


class ActFont9696:
    """按 FTYPE/字号加载并渲染 FONT9696 位图字形。"""

    def __init__(self, path: str):
        self.path = path
        self._index = None
        self._pixmap_cache = {}

    @property
    def loaded(self):
        return self.path and os.path.exists(self.path)

    def _ensure_index(self):
        if self._index is None:
            self._index = Font9696.load_index(self.path)
        return self._index

    def _glyph_image(self, ch: str, color: tuple[int, int, int],
                     ftype: int, size: int):
        if not self.loaded:
            return None
        try:
            code = ord(ch)
            if code >= 0x80:
                big5 = ch.encode('big5')
                if len(big5) != 2:
                    return None
                code = (big5[0] << 8) | big5[1]
            idx = Font9696.big5_to_index(code, ftype)
            if idx is None:
                return None
            rle = Font9696.load_glyph_data(self.path, idx, self._ensure_index())
            if not rle:
                return None
            bitmap = Font9696.invert_polarity(Font9696.decode_rle(rle))
            rgba = Font9696.render_glyph_from_bitmap(bitmap, color=color)
            if not rgba:
                return None
            from PIL import Image

            img = Image.frombytes('RGBA', (96, 96), rgba)
            return img.resize((size, size), Image.Resampling.BOX)
        except Exception:
            return None

    def text_pixmap(self, text: str, color: tuple[int, int, int],
                    ftype: int = 4, size: int = 24,
                    outline: bool = True):
        key = (text, color, ftype, size, outline)
        if key in self._pixmap_cache:
            return self._pixmap_cache[key]
        if not self.loaded:
            return None
        from PIL import Image

        width = size * max(1, len(text))
        height = size
        img = Image.new('RGBA', (width, size), (0, 0, 0, 0))
        cx = 0
        for ch in text:
            glyph = self._glyph_image(ch, color, ftype, size)
            if glyph is not None:
                if outline:
                    outline_img = Image.new(
                        'RGBA', glyph.size, (0, 0, 0, 0))
                    outline_img.putalpha(glyph.getchannel('A'))
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            img.alpha_composite(outline_img, (cx + dx, dy))
                img.alpha_composite(glyph, (cx, 0))
            cx += size
        from PySide6.QtGui import QImage, QPixmap

        data = img.tobytes('raw', 'RGBA')
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self._pixmap_cache[key] = pixmap
        return pixmap
