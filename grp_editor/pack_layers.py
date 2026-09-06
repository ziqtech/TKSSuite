#!/usr/bin/env python3
"""
伪彩图层 → RGBA 通道打包工具
=============================
将伪彩导出的 Layer1.png 和 Layer2.png 合并为一张 RGBA 通道图,
供现代游戏引擎 (Unity/Unreal) 直接使用。

通道布局 (参考 grp_decoder_v3.py save_packed_rgba_png):
  R = Layer 1 前景遮挡深度值
  G = Layer 2 地形碰撞类型值
  B = 0 (保留)
  A = 可行走遮罩 (碰撞值 > 0 → 255, 否则 0)

用法: python pack_layers.py --l1 layer1.png --l2 layer2.png [-o output.png]
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.image_io import encode_png_rgba

HAS_PIL = False
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    pass

# ── 伪彩色反向映射表 (与 grp_editor.py 完全一致) ──────────

def _distinct_color(val: int, seed: int) -> tuple:
    if val == 0: return (0, 0, 0)
    hue = ((val * 137.508 + seed * 47) % 360)
    h_sector = hue / 60.0
    x = int(255 * (1 - abs(h_sector % 2 - 1)))
    r, g, b = [(255, x, 0), (x, 255, 0), (0, 255, x),
               (0, x, 255), (x, 0, 255), (255, 0, x)][int(h_sector) % 6]
    return (r, g, b)

_L1_RGB2VAL = {}
_L2_RGB2VAL = {}

# L1 颜色表 (seed=31, 与编辑器同步)
for _v in range(256):
    c1 = _distinct_color(_v, seed=31)
    while c1 in _L1_RGB2VAL:
        c1 = ((c1[0] + 1) % 256, c1[1], c1[2])
    _L1_RGB2VAL[c1] = _v

# L2 颜色表 (seed=73, 优先复用碰撞色)
_COLLISION_COLORS = {
    0:(0,0,0,0), 1:(255,0,0,200), 2:(0,200,0,200), 3:(0,100,255,200),
    4:(255,200,0,200), 5:(255,0,255,200), 6:(0,200,200,200), 7:(200,100,0,200),
    8:(128,0,255,200), 9:(150,150,150,200), 10:(255,128,128,200),
}
for _v in range(256):
    if _v == 0:
        c2 = (0, 0, 0)
    elif _v in _COLLISION_COLORS:
        r, g, b, _a = _COLLISION_COLORS[_v]
        c2 = (r, g, b)
    else:
        c2 = _distinct_color(_v, seed=73)
    while c2 in _L2_RGB2VAL:
        c2 = ((c2[0] + 1) % 256, c2[1], c2[2])
    _L2_RGB2VAL[c2] = _v


def _nearest_color(rgb: tuple, lut: dict) -> int:
    """精确查表 + 最近邻 fallback"""
    if rgb in lut: return lut[rgb]
    r, g, b = rgb
    best_val, best_dist = 0, 999999
    for color, val in lut.items():
        cr, cg, cb = color
        dist = (r - cr)**2 + (g - cg)**2 + (b - cb)**2
        if dist < best_dist:
            best_val, best_dist = val, dist
    return best_val


def pseudo_to_bytes(img_path: str, lut: dict) -> bytes:
    """将伪彩 PNG 转回原始 byte 值数组"""
    img = Image.open(img_path).convert("RGB")
    pixels = list(img.getdata())
    return bytes([_nearest_color(p, lut) for p in pixels])


# ── PNG 编码 ──────────────────────────────────────────────

def save_packed_rgba(w: int, h: int, l1: bytes, l2: bytes, path: str):
    """打包 R=L1, G=L2, B=0, A=(L2>0?255:0)"""
    total = w * h
    l1 = l1[:total].ljust(total, b'\x00')
    l2 = l2[:total].ljust(total, b'\x00')

    rgba = bytearray(total * 4)
    for i in range(total):
        g = l2[i]
        rgba[i*4] = l1[i]             # R: 遮挡深度
        rgba[i*4+1] = g               # G: 碰撞类型
        rgba[i*4+2] = 0               # B: 保留
        rgba[i*4+3] = 255 if g > 0 else 0  # A: 可行走遮罩

    Path(path).write_bytes(encode_png_rgba(w, h, rgba))


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="伪彩 Layer1 + Layer2 → RGBA 通道打包")
    parser.add_argument("--l1", required=True, help="Layer1 伪彩 PNG")
    parser.add_argument("--l2", required=True, help="Layer2 伪彩 PNG")
    parser.add_argument("-o", "--output", default=None, help="输出 RGBA PNG (默认: packed_rgba.png)")
    args = parser.parse_args()

    if not HAS_PIL:
        print("需要 Pillow: pip install Pillow")
        sys.exit(1)

    # 读取 L1
    img1 = Image.open(args.l1)
    w1, h1 = img1.size
    l1_bytes = pseudo_to_bytes(args.l1, _L1_RGB2VAL)

    # 读取 L2
    img2 = Image.open(args.l2)
    w2, h2 = img2.size
    l2_bytes = pseudo_to_bytes(args.l2, _L2_RGB2VAL)

    if (w1, h1) != (w2, h2):
        print(f"尺寸不匹配: L1={w1}x{h1}, L2={w2}x{h2}")
        sys.exit(1)

    out = args.output or "packed_rgba.png"
    save_packed_rgba(w1, h1, l1_bytes, l2_bytes, out)
    print(f"已打包: {out} ({w1}x{h1})")
    print(f"  R = Layer1 前景遮挡深度 (0~255)")
    print(f"  G = Layer2 地形碰撞类型 (0~255)")
    print(f"  B = 0 (保留)")
    print(f"  A = 可行走遮罩 (碰撞>0 → 255)")

if __name__ == "__main__":
    main()
