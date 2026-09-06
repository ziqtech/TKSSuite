"""spritesheet_editor 像素层 — 格式定义/量化/Alpha 处理 (T17 自主文件迁出)。"""
from typing import List

from PIL import Image
from PySide6.QtGui import QImage, QPixmap

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
