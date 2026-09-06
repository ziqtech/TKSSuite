"""PNG 编码 — 手写 IHDR/IDAT/IEND + zlib, 无新依赖 (纯数据模块, 无 Qt/PIL)。

输入为 RGBA 原始字节缓冲 (w*h*4), 逐行 0 号过滤 (None filter), zlib level 9 —
与此前 gxp/grp/jvg/pack_layers 四份本地实现逐字节一致的输出 (T7 四合一)。
"""
import struct
import zlib


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return (struct.pack(">I", len(data)) + chunk
            + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF))


def encode_png_rgba(w: int, h: int, rgba) -> bytes:
    """编码 32-bit RGBA PNG (IHDR color type 6)。rgba 为 w*h*4 字节缓冲。"""
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    stride = w * 4
    raw = bytearray(h * (stride + 1))
    for row in range(h):
        out = row * (stride + 1)
        raw[out] = 0
        raw[out + 1:out + 1 + stride] = rgba[row * stride:(row + 1) * stride]
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    return png


def encode_png_rgb(w: int, h: int, rgba) -> bytes:
    """编码 24-bit RGB PNG (IHDR color type 2), 从 RGBA 缓冲剥离透明通道
    (符合游戏引擎无透明背景要求)。rgba 为 w*h*4 字节缓冲。"""
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    stride_in = w * 4
    stride_out = w * 3
    raw = bytearray(h * (stride_out + 1))
    mv = memoryview(rgba)
    for row in range(h):
        out = row * (stride_out + 1)
        raw[out] = 0
        for col in range(w):
            in_idx = row * stride_in + col * 4
            out_idx = out + 1 + col * 3
            raw[out_idx:out_idx + 3] = mv[in_idx:in_idx + 3]
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    return png
