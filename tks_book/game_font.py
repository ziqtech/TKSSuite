# -*- coding: utf-8 -*-
"""FONT9696 游戏字体渲染引擎 — 复刻 TKS.exe 字体管线, 与游戏渲染完全一致

管线 (反编译证据):
  sub_44B384 — Big5 码 → 字形索引 → 文件偏移 (256 槽 LRU 缓存, 复用 font9696_codec)
  sub_44B208 — RLE 解码 → 96×96 1bpp 位图
  sub_44B5A8 — 盒滤波降采样: 96/size 方块 popcount(byte_4EC1F8) → 覆盖度 LUT → alpha(0..32)
               合法字号 12/16/24/32/48 (sub_44B04C), 每字号一张 LUT (内存 dump 提取)
  sub_44E49C — 文本步进: 全角 +size, ASCII 半宽 +size/2 (字形 X 向隔列抽样, a1+65),
               0x1E 换行 +size
  sub_44D524 — 像素混合: alpha<31 → dst*(32-a)/32 + color*a/32 (byte_4EC2F8 = c*a/32),
               alpha≥31 → 纯色
  sub_44C6A4 — 阴影: alpha 图右 2px/下 2px 最大值膨胀, 以阴影色(调色板0=黑)画在 (x-1,y-1)
  sub_44ADB0 — 字体构造: 打开 FONT9696, 默认 24px; 菜单=FTYPE2@24 (sub_421B64),
               说明文字=FTYPE0@16 (sub_44AF7C(0,16,...))
"""
import os

from font_editor.font9696_codec import Font9696

try:
    import numpy as _np
except ImportError:
    _np = None

# 覆盖度 → alpha(0..32) LUT — TKS.exe 内存 dump 提取 (byte_4EC789/4EC7CA/4EC7EF/4EC800/4EC80A)
_LUT = {
    12: bytes([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10,
               11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18, 19, 19,
               20, 20, 21, 21, 22, 22, 23, 23, 24, 24, 25, 25, 26, 26, 27, 27, 28, 28,
               29, 29, 30, 30, 31, 31, 32]),
    16: bytes([0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 9, 10, 11, 12, 13, 14, 15, 16, 16,
               17, 18, 19, 20, 21, 22, 23, 24, 24, 25, 26, 27, 28, 29, 30, 31, 32]),
    24: bytes([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32]),
    32: bytes([0, 3, 7, 10, 14, 17, 21, 24, 28, 32]),
    48: bytes([0, 8, 16, 24, 32]),
}
_SIZES = (12, 16, 24, 32, 48)
_SHADOW = (0, 0, 0)   # 阴影色 = 调色板颜色0 黑 (sub_44ADB0: a1+12 = dword_A2C528[0])


class GameFont:
    """FONT9696 字体渲染器。glyph alpha 图带缓存, draw_text 直接操作 QImage 像素。"""

    def __init__(self, path):
        self.path = path
        self._fh = open(path, 'rb')
        self._index = Font9696.load_index(path)
        self._alpha_cache = {}   # (big5_code, ftype, size, half) → alpha 二维数据

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    # ── 字形 alpha (0..32) ──

    def _glyph_rle(self, glyph_idx):
        if glyph_idx is None or glyph_idx + 1 >= len(self._index):
            return b''
        off, nxt = self._index[glyph_idx], self._index[glyph_idx + 1]
        if off >= nxt:
            return b''
        self._fh.seek(off)
        return self._fh.read(nxt - off)

    def glyph_alpha(self, big5_code, ftype, size, half=False):
        """字形 → alpha 图 (size×size, 值0..32); ASCII 半宽为 size×(size/2) (隔列抽样)"""
        key = (big5_code, ftype, size, half)
        if key in self._alpha_cache:
            return self._alpha_cache[key]
        alpha = None
        idx = Font9696.big5_to_index(big5_code, ftype)
        rle = self._glyph_rle(idx)
        if rle:
            # 文件极性: bit=1 背景 / bit=0 笔画 → 反转后按笔画覆盖度降采样
            bitmap = Font9696.invert_polarity(Font9696.decode_rle(rle))
            alpha = self._downsample(bitmap, size)
            if half and alpha is not None:
                alpha = alpha[:, ::2] if _np is not None else [row[::2] for row in alpha]
        self._alpha_cache[key] = alpha
        return alpha

    @staticmethod
    def _downsample(bitmap, size):
        """sub_44B5A8: 96×96 1bpp → size×size alpha; cell=96/size 方块 popcount → LUT"""
        if size not in _LUT:
            size = 24
        cell = 96 // size
        lut = _LUT[size]
        if _np is not None:
            bits = _np.unpackbits(_np.frombuffer(bitmap, _np.uint8)).reshape(96, 96)
            cov = bits.reshape(size, cell, size, cell).sum(axis=(1, 3))
            return _np.frombuffer(lut, _np.uint8)[cov]
        # 纯 Python 兜底
        rows = []
        for by in range(size):
            row = bytearray(size)
            for bx in range(size):
                cov = 0
                for yy in range(by * cell, (by + 1) * cell):
                    base = yy * 12
                    for xx in range(bx * cell, (bx + 1) * cell):
                        if bitmap[base + (xx >> 3)] & (0x80 >> (xx & 7)):
                            cov += 1
                row[bx] = lut[cov]
            rows.append(bytes(row))
        return rows

    # ── 文本绘制 (QImage ARGB32, 内存序 BGRA) ──

    def draw_text(self, qimage, x, y, text, color, size=24, ftype=2, shadow=False):
        """复刻 sub_44E49C + sub_44D524 (+可选 sub_44C6A4 阴影) 在 QImage 上绘制文本"""
        w, h = qimage.width(), qimage.height()
        if _np is not None:
            buf = _np.frombuffer(qimage.bits(), _np.uint8)
            stride = qimage.bytesPerLine()
            img = buf.reshape(h, stride)[:, :w * 4].reshape(h, w, 4)
        else:
            img = None
        cx, cy = x, y
        for ch in text:
            if ch == '\n':
                cx = x
                cy += size
                continue
            try:
                bs = ch.encode('big5')
            except Exception:
                # 与游戏一致: 字库按 Big5 索引, 非法码 sub_44B384 返回 0 → 不画只步进
                cx += size
                continue
            if len(bs) == 1:
                code, half, adv = bs[0], True, size // 2
            else:
                code, half, adv = (bs[0] << 8) | bs[1], False, size
            alpha = self.glyph_alpha(code, ftype, size, half)
            if alpha is not None:
                if shadow:
                    self._blit_glyph(img, qimage, self._dilate(alpha, size),
                                     cx - 1, cy - 1, _SHADOW)
                self._blit_glyph(img, qimage, alpha, cx, cy, color)
            cx += adv
        return cx

    def draw_rich(self, qimage, x, y, data, palette, color_idx=16, size=24,
                  ftype=2, max_y=None, shadow=False):
        """复刻 sub_44E49C 完整控制码状态机, 渲染 TKT 原始字节流 (宏已展开)。

        控制码 (与游戏/tkt_editor 一致):
          0x01+n FRESET: 1=恢复色+字号+FTYPE / 2=恢复色 / 3=恢复字号 / 4=恢复FTYPE
          0x02+n FCOLOR: 存旧色, 切调色板色 n-1 (dword_A2C524+4n = A2C528[n-1])
          0x03+rgb     : 存旧色, 切直接 RGB 色 (sub_451F08)
          0x04+n FSIZE : 存旧字号, 切字号 n (合法 12/16/24/32/48, 否则 24)
          0x05+n FTYPE : 存旧区段, 切 FTYPE n-1 (>7 回退)
          0x1E         : 换行 (行高 = 当前字号)
          其余: ≥0x80 双字节 Big5 全角, <0x80 ASCII 半宽 (空格照常占位步进)

        Args:
            data: 原始字节流; palette: {0..31: (r,g,b)}
            max_y: 超出该 y 停止 (屏幕/面板裁剪)
        """
        w, h = qimage.width(), qimage.height()
        if _np is not None:
            buf = _np.frombuffer(qimage.bits(), _np.uint8)
            stride = qimage.bytesPerLine()
            img = buf.reshape(h, stride)[:, :w * 4].reshape(h, w, 4)
        else:
            img = None
        default = palette.get(16, (244, 242, 220))
        cur_color = palette.get(color_idx, default)
        saved_color = cur_color
        cur_size = size if size in _SIZES else 24
        restore_size = cur_size          # a1+32 (FSIZE 存入, FRESET 1/3 取出)
        cur_ft, saved_ft = ftype, ftype
        cx, cy = x, y
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b == 0x01 and i + 1 < n:
                sub = data[i + 1]
                if sub == 1:
                    cur_color = saved_color
                    cur_size = restore_size
                    cur_ft = saved_ft
                elif sub == 2:
                    cur_color = saved_color
                elif sub == 3:
                    cur_size = restore_size
                elif sub == 4:
                    cur_ft = saved_ft
                i += 2
                continue
            if b == 0x02 and i + 1 < n:
                saved_color = cur_color
                cur_color = palette.get(data[i + 1] - 1, cur_color)
                i += 2
                continue
            if b == 0x03 and i + 3 < n:
                saved_color = cur_color
                r5, g6, b5 = data[i + 1] >> 3, data[i + 2] >> 2, data[i + 3] >> 3
                cur_color = ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4),
                             (b5 << 3) | (b5 >> 2))
                i += 4
                continue
            if b == 0x04 and i + 1 < n:
                restore_size = cur_size
                cur_size = data[i + 1] if data[i + 1] in _SIZES else 24
                i += 2
                continue
            if b == 0x05 and i + 1 < n:
                saved_ft = cur_ft
                v = data[i + 1] - 1
                cur_ft = v if 0 <= v <= 7 else saved_ft
                i += 2
                continue
            if b == 0x1E:
                cx = x
                cy += cur_size
                i += 1
                if max_y is not None and cy >= max_y:
                    break
                continue
            if b < 0x20:
                i += 1   # 未知控制码: 游戏报 MakeText error, 查看器静默跳过
                continue
            if b >= 0x80 and i + 1 < n:
                code, half, adv = (b << 8) | data[i + 1], False, cur_size
                i += 2
            else:
                code, half, adv = b, True, cur_size // 2
                i += 1
            alpha = self.glyph_alpha(code, cur_ft, cur_size, half)
            if alpha is not None:
                if shadow:
                    self._blit_glyph(img, qimage, self._dilate(alpha, cur_size),
                                     cx - 1, cy - 1, _SHADOW)
                self._blit_glyph(img, qimage, alpha, cx, cy, cur_color)
            cx += adv
        return cy

    @staticmethod
    def _dilate(alpha, size):
        """sub_44C6A4: 右 2px / 下 2px 最大值膨胀 (阴影层)"""
        if _np is not None:
            gh, gw = alpha.shape
            buf = _np.zeros((gh + 2, gw + 2), _np.uint8)
            buf[:gh, :gw] = alpha
            for _ in range(2):
                buf[:, 1:] = _np.maximum(buf[:, 1:], buf[:, :-1])
            for _ in range(2):
                buf[1:, :] = _np.maximum(buf[1:, :], buf[:-1, :])
            return buf
        gh, gw = len(alpha), len(alpha[0])
        buf = [bytearray(gw + 2) for _ in range(gh + 2)]
        for yy in range(gh):
            buf[yy][:gw] = alpha[yy]
        for _ in range(2):
            for row in buf:
                for xx in range(gw + 1, 0, -1):
                    if row[xx - 1] > row[xx]:
                        row[xx] = row[xx - 1]
        for _ in range(2):
            for yy in range(gh + 1, 0, -1):
                for xx in range(gw + 2):
                    if buf[yy - 1][xx] > buf[yy][xx]:
                        buf[yy][xx] = buf[yy - 1][xx]
        return buf

    @staticmethod
    def _blit_glyph(img, qimage, alpha, x, y, color):
        """sub_44D524 混合: a≥31 → 纯色; 否则 dst*(32-a)/32 + color*a/32"""
        r, g, b = color
        if _np is not None:
            h, w = img.shape[0], img.shape[1]
            gh, gw = alpha.shape
            sx, sy = max(0, -x), max(0, -y)
            ex, ey = min(gw, w - x), min(gh, h - y)
            if ex <= sx or ey <= sy:
                return
            a = alpha[sy:ey, sx:ex].astype(_np.uint16)
            dst = img[y + sy:y + ey, x + sx:x + ex]
            mask = a > 0
            if not mask.any():
                return
            col = _np.array([b, g, r], _np.uint16)   # ARGB32 内存序 BGRA
            av = a[..., None]
            blended = ((dst[..., :3].astype(_np.uint16) * (32 - av) + col * av) >> 5)
            solid = (a >= 31)[..., None] & _np.array([True, True, True])
            out = _np.where(solid, col, blended).astype(_np.uint8)
            m3 = mask[..., None] & _np.array([True, True, True])
            dst[..., :3] = _np.where(m3, out, dst[..., :3])
            return
        # 纯 Python 兜底 (QImage setPixel, 慢)
        from PySide6.QtGui import qRgb
        h, w = qimage.height(), qimage.width()
        for yy, row in enumerate(alpha):
            py = y + yy
            if py < 0 or py >= h:
                continue
            for xx, a in enumerate(row):
                if a == 0:
                    continue
                px = x + xx
                if px < 0 or px >= w:
                    continue
                if a >= 31:
                    qimage.setPixel(px, py, qRgb(r, g, b))
                else:
                    p = qimage.pixel(px, py)
                    dr, dg, db = (p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF
                    qimage.setPixel(px, py, qRgb(
                        (dr * (32 - a) + r * a) >> 5,
                        (dg * (32 - a) + g * a) >> 5,
                        (db * (32 - a) + b * a) >> 5))


def load_game_font(game_dir_or_path):
    """加载游戏目录下的 FONT9696; 缺失或异常返回 None"""
    p = game_dir_or_path
    if os.path.isdir(p):
        p = os.path.join(p, "FONT9696")
    if not os.path.exists(p):
        return None
    try:
        return GameFont(p)
    except Exception:
        return None
