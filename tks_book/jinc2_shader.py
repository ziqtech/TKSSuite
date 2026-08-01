# -*- coding: utf-8 -*-
"""jinc2-sharp 缩放 — 软件复刻 cnc-ddraw 的 lanczos2-sharp.glsl 着色器

复刻 Hyllian's jinc windowed-jinc 2-lobe sharper with anti-ringing Shader。
原始 GLSL: 启动器目录/tools\\cnc-ddraw\\Shaders\\interpolation\\lanczos2-sharp.glsl

实现策略:
  1. 主缩放: PIL LANCZOS (C 实现, 3-lobe sinc 窗, 与 jinc2 2-lobe 视觉接近)
  2. 抗振铃 (anti-ringing): 3×3 MinFilter/MaxFilter 确定最近邻值域,
     clamp 缩放结果到 [min, max], 然后以 0.8 强度混合 (JINC2_AR_STRENGTH)

GLSL 抗振铃逻辑:
  min_sample = min4(c11, c21, c12, c22)  // 4 最近邻最小值
  max_sample = max4(c11, c21, c12, c22)  // 4 最近邻最大值
  color = clamp(color, min_sample, max_sample)
  color = mix(aux, color, 0.8)           // 80% 抗振铃混合

PIL MinFilter(3)/MaxFilter(3) 使用 3×3 邻域 (9 像素, 包含 GLSL 的 4 邻居),
抗振铃范围略宽于 GLSL 2×2, 视觉上差异极小。

性能 (640×480 源):
  200% (1280×960):  ~34ms
  300% (1920×1440): ~67ms
  100% (640×480):    0ms (直接返回)
"""
from PIL import Image, ImageChops, ImageFilter

# GLSL 常量
JINC2_AR_STRENGTH = 0.8


def resize_jinc2_sharp(pil_img, out_w, out_h):
    """jinc2-sharp 风格缩放 (PIL LANCZOS + 抗振铃)

    Args:
        pil_img: PIL.Image (任意模式)
        out_w, out_h: 输出尺寸

    Returns:
        PIL.Image (同模式, 缩放后)
    """
    in_w, in_h = pil_img.size
    if (in_w, in_h) == (out_w, out_h):
        return pil_img.copy()
    if out_w <= 0 or out_h <= 0:
        return pil_img.copy()

    # 缩小 (downscale): 直接 LANCZOS, 不需要抗振铃 (缩小无振铃)
    if out_w <= in_w and out_h <= in_h:
        return pil_img.resize((out_w, out_h), Image.LANCZOS)

    # 放大: LANCZOS + 抗振铃
    main = pil_img.resize((out_w, out_h), Image.LANCZOS)

    # 原图 3×3 min/max → NEAREST 放大到输出尺寸
    # 每个输出像素获得其最近输入像素邻域的 min/max (抗振铃值域边界)
    orig_min = pil_img.filter(ImageFilter.MinFilter(3))
    orig_max = pil_img.filter(ImageFilter.MaxFilter(3))
    min_up = orig_min.resize((out_w, out_h), Image.NEAREST)
    max_up = orig_max.resize((out_w, out_h), Image.NEAREST)

    # clamp: result = min(max(main, min_up), max_up)
    clamped = ImageChops.darker(ImageChops.lighter(main, min_up), max_up)

    # mix(aux=main, clamped, JINC2_AR_STRENGTH)
    result = Image.blend(main, clamped, JINC2_AR_STRENGTH)
    return result
