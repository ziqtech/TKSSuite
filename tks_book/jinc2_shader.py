# -*- coding: utf-8 -*-
"""图像缩放 + 抗振铃 — 贴近 cnc-ddraw lanczos2-sharp.glsl 的抗振铃部分

原始 GLSL: cnc-ddraw/Shaders/interpolation/lanczos2-sharp.glsl

抗振铃算法 (GLSL L197-200):
  c11 = pixel(floor(tc)), c21 = pixel(floor(tc)+1), c12, c22 同理
  min_sample = min4(c11, c21, c12, c22),  max_sample = max4(...)
  color = clamp(color, min_sample, max_sample)
  color = mix(aux, color, JINC2_AR_STRENGTH=0.8)

实现:
  - 放大: BICUBIC (4×4 核, 振铃远小于 LANCZOS 3-lobe) + 2×2 邻域抗振铃
  - 缩小: LANCZOS (缩小无振铃)
  - 所有缩放倍数走同一逻辑, 保证一致性
"""
from PIL import Image, ImageChops

# GLSL 常量 (lanczos2-sharp.glsl L26-28)
JINC2_AR_STRENGTH = 0.8


# ── 2×2 邻域 min/max (GLSL min4/max4) ──

def _min_2x2(img):
    """2×2 块最小值: min_2x2[i][j] = min(img[i,j], img[i+1,j], img[i,j+1], img[i+1,j+1])
    对应 GLSL min4(c11, c21, c12, c22) 其中 c11 = img[i,j]
    """
    sx = ImageChops.offset(img, 1, 0)    # img[i+1,j] → 位置 [i,j]
    sy = ImageChops.offset(img, 0, 1)    # img[i,j+1] → 位置 [i,j]
    sxy = ImageChops.offset(img, 1, 1)   # img[i+1,j+1] → 位置 [i,j]
    return ImageChops.darker(ImageChops.darker(img, sx),
                              ImageChops.darker(sy, sxy))


def _max_2x2(img):
    """2×2 块最大值 (对应 GLSL max4)"""
    sx = ImageChops.offset(img, 1, 0)
    sy = ImageChops.offset(img, 0, 1)
    sxy = ImageChops.offset(img, 1, 1)
    return ImageChops.lighter(ImageChops.lighter(img, sx),
                               ImageChops.lighter(sy, sxy))


def _anti_ringing(scaled, orig, out_w, out_h):
    """抗振铃: NEAREST 上采样 min_2x2/max_2x2, clamp 后 0.8 混合

    GLSL: color = clamp(color, min_sample, max_sample); color = mix(aux, color, 0.8)
    """
    orig_min = _min_2x2(orig)
    orig_max = _max_2x2(orig)
    min_up = orig_min.resize((out_w, out_h), Image.NEAREST)
    max_up = orig_max.resize((out_w, out_h), Image.NEAREST)
    clamped = ImageChops.darker(ImageChops.lighter(scaled, min_up), max_up)
    return Image.blend(scaled, clamped, JINC2_AR_STRENGTH)


# ── 主入口 ──

def resize_jinc2_sharp(pil_img, out_w, out_h):
    """缩放 + 抗振铃 (BICUBIC + 2×2 邻域 clamp)

    统一使用 BICUBIC + 抗振铃 (所有缩放倍数走同一路径, 保证一致性)。
    缩小: LANCZOS (缩小无振铃)。
    """
    in_w, in_h = pil_img.size
    if (in_w, in_h) == (out_w, out_h):
        return pil_img.copy()
    if out_w <= 0 or out_h <= 0:
        return pil_img.copy()

    # 缩小: 直接 LANCZOS (缩小无振铃)
    if out_w <= in_w and out_h <= in_h:
        return pil_img.resize((out_w, out_h), Image.LANCZOS)

    if pil_img.mode not in ('RGB', 'RGBA'):
        pil_img = pil_img.convert('RGB')

    # 统一 BICUBIC + 抗振铃
    result = pil_img.resize((out_w, out_h), Image.BICUBIC)
    result = _anti_ringing(result, pil_img, out_w, out_h)
    return result
