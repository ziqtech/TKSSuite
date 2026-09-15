"""act_editor 渲染层 — 图层帧计算/混合模式/合成 (T16 自 act_editor.py 迁出)。"""
from PySide6.QtGui import (
    QColor, QFont, QIntValidator, QPainter, QPen, QBrush,
    QPixmap, QImage, QAction, QPalette, QFontMetrics, QMouseEvent,
    QWheelEvent, QKeyEvent, QShortcut, QKeySequence, QCursor,
)
from PIL import Image, ImageChops

# ============================================================
# PIL ↔ QPixmap 转换
# ============================================================

def pil_to_qpixmap(pil_image):
    """将 PIL RGBA Image 转换为 QPixmap"""
    if pil_image is None:
        return None
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')
    data = pil_image.tobytes('raw', 'RGBA')
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def pil_to_qimage(pil_image):
    """将 PIL RGBA Image 转换为 QImage"""
    if pil_image is None:
        return None
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')
    data = pil_image.tobytes('raw', 'RGBA')
    return QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)


# ============================================================
# 预览: JVG 帧提取 + 混合模式
# ============================================================

def _compute_layer_frame(L, tick):
    """按 sub_4434BC 语义计算当前帧号.
    返回 (cur_frame, stopped)"""
    start_delay = L[22]
    tick_interval = L[21]
    first = L[17]
    last = L[18]
    loop = L[19]

    if start_delay > 0:
        if tick < start_delay:
            return first, False
        tick -= start_delay

    step = max(1, tick_interval)
    frame_adv = tick // step
    span = max(1, last - first + 1)

    if loop == -1:
        return first + (frame_adv % span), False
    if loop == -2:
        if frame_adv >= span:
            return last, True
        return first + frame_adv, False
    if loop >= 0:
        if frame_adv < span:
            return first + frame_adv, False
        rem = frame_adv - span
        tail = max(1, last - loop + 1)
        return loop + (rem % tail), True
    return first + (frame_adv % span), False


def _apply_blend(pil_img, mode, param):
    """对 PIL RGBA 图像应用混合模式近似变换.
    注: mode=2/3/4 的混合必须访问 dst, 由合成阶段处理; 此处原样返回.
    """
    if pil_img is None:
        return None
    if mode == 0 or mode not in (1, 2, 3, 4, 5):
        return pil_img
    if mode in (2, 3, 4):
        return pil_img

    if mode == 5:
        try:
            return pil_img.transpose(Image.FLIP_LEFT_RIGHT)
        except Exception:
            return pil_img

    try:
        src = pil_img.tobytes()
    except Exception:
        return pil_img
    buf = bytearray(src)
    n = len(buf) // 4

    if mode == 1:
        p = int(param) & 0xFFFF
        if p == 0 or p > 31:
            return pil_img
        p &= 0x1F
        if p < 8:
            tr, tg, tb = 255, 0, 0
        elif p < 16:
            tr, tg, tb = 255, 255, 0
        elif p < 24:
            tr, tg, tb = 0, 255, 0
        else:
            tr, tg, tb = 0, 0, 255
        for i in range(n):
            o = i * 4
            if buf[o + 3] == 0:
                continue
            buf[o]     = (buf[o]     + tr) >> 1
            buf[o + 1] = (buf[o + 1] + tg) >> 1
            buf[o + 2] = (buf[o + 2] + tb) >> 1

    try:
        return Image.frombytes('RGBA', pil_img.size, bytes(buf))
    except Exception:
        return pil_img


def _composite_additive(composite, rgba_src, dx, dy, param):
    """Additive 加法饱和混合 (mode=2)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        try:
            p = int(param)
        except Exception:
            p = 0
        if 0 < p <= 31:
            factor = p / 32.0
            masked = masked.point(lambda v, f=factor: int(v * f))
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.add(dst_crop, masked)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


def _composite_subtract(composite, rgba_src, dx, dy):
    """减法饱和混合 (mode=3): dst.RGB = max(dst - src, 0)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.subtract(dst_crop, masked)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


def _composite_luma_alpha(composite, rgba_src, dx, dy):
    """按 src 亮度做 alpha blend (mode=4)."""
    if composite is None or rgba_src is None:
        return
    sw, sh = rgba_src.size
    cw, ch = composite.size
    l = max(0, dx)
    t = max(0, dy)
    r = min(cw, dx + sw)
    b = min(ch, dy + sh)
    if r <= l or b <= t:
        return
    sl, st = l - dx, t - dy
    sr, sb = r - dx, b - dy
    try:
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA':
            sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        luma = src_rgb.convert('L')
        mask_luma = luma.point(
            lambda v: 0 if v == 0 else (255 if v > 224 else v))
        alpha_bin = alpha.point(lambda v: 255 if v > 0 else 0)
        mask = ImageChops.multiply(mask_luma, alpha_bin)
        dst_crop = composite.crop((l, t, r, b))
        blended = Image.composite(src_rgb, dst_crop, mask)
        composite.paste(blended, (l, t))
    except Exception:
        try:
            composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception:
            pass


# ============================================================
