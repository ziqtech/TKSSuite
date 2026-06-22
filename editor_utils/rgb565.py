"""
RGB565 颜色转换 — 统一模块 (供 GRP / GXP 编辑器使用)

提供 65536 条目查找表 + 批量转换函数, 与游戏渲染引擎一致.
"""
import struct

# ── 预计算查找表: 65536×3 bytes (RGB565 → RGB888) ──
_RGB565_LUT = bytearray(65536 * 3)
for _v in range(65536):
    r5 = (_v >> 11) & 0x1F
    g6 = (_v >> 5) & 0x3F
    b5 = _v & 0x1F
    off = _v * 3
    _RGB565_LUT[off] = (r5 << 3) | (r5 >> 2)
    _RGB565_LUT[off + 1] = (g6 << 2) | (g6 >> 4)
    _RGB565_LUT[off + 2] = (b5 << 3) | (b5 >> 2)


def rgb565_to_rgba(raw: bytes, w: int, h: int) -> bytearray:
    """将 RGB565 原始字节解码为 RGBA8888.

    Args:
        raw: RGB565 原始字节 (每像素 2 字节, little-endian)
        w: 图像宽度
        h: 图像高度
    Returns:
        RGBA bytearray (每像素 4 字节, Alpha=255)
    """
    total = w * h
    rgba = bytearray(total * 4)
    pixel_count = min(total, len(raw) // 2)

    for i in range(pixel_count):
        lo, hi = raw[i * 2], raw[i * 2 + 1]
        val = lo | (hi << 8)
        off3 = val * 3
        off4 = i * 4
        # 切片赋值 — 比逐个元素赋值更快
        rgba[off4:off4 + 3] = _RGB565_LUT[off3:off3 + 3]
        rgba[off4 + 3] = 255

    return rgba


def rgba_to_rgb565(rgba_bytes: bytes, w: int, h: int) -> bytes:
    """将 RGBA8888 字节编码为 RGB565.

    Args:
        rgba_bytes: RGBA 原始字节 (每像素 4 字节)
        w: 图像宽度
        h: 图像高度
    Returns:
        RGB565 字节 (每像素 2 字节, little-endian)
    """
    total = w * h
    raw = bytearray(total * 2)

    for i in range(total):
        off4 = i * 4
        r5 = (rgba_bytes[off4] >> 3) & 0x1F
        g6 = (rgba_bytes[off4 + 1] >> 2) & 0x3F
        b5 = (rgba_bytes[off4 + 2] >> 3) & 0x1F
        val = (r5 << 11) | (g6 << 5) | b5
        raw[i * 2] = val & 0xFF
        raw[i * 2 + 1] = (val >> 8) & 0xFF

    return bytes(raw)
