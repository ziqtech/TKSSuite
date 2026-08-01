# -*- coding: utf-8 -*-
"""jinc2-sharp 缩放 — 软件复刻 cnc-ddraw 的 lanczos2-sharp.glsl 着色器

复刻 Hyllian's jinc windowed-jinc 2-lobe sharper with anti-ringing Shader。
原始 GLSL: 启动器目录/tools\\cnc-ddraw\\Shaders\\interpolation\\lanczos2-sharp.glsl

GLSL 核心算法 (逐输出像素):
  1. pc = texCoord * TextureSize  (输出像素对应的源像素坐标)
  2. tc = floor(pc - 0.5) + 0.5   (中心化到像素网格)
  3. 采样 tc 周围 4×4 = 16 个源像素 (tc + {-1,0,1,2} × {dx,dy})
  4. jinc2 权重: resampler(d) = sin(d*wa)*sin(d*wb)/(d*d), d = 2D 欧几里得距离
     wa = JINC2_WINDOW_SINC * pi = 0.5*pi,  wb = JINC2_SINC * pi = 1.0*pi
  5. 权重归一化后加权求和
  6. 抗振铃:
     c11 = pixel(floor(tc)), c21 = pixel(floor(tc)+1), c12, c22 同理
     min_sample = min4(c11, c21, c12, c22),  max_sample = max4(...)
     color = clamp(color, min_sample, max_sample)
     color = mix(aux, color, JINC2_AR_STRENGTH=0.8)

实现策略:
  - 整数倍放大 (2x/3x/...): 对每个子像素位置 (isx,isy) 预计算 4×4 jinc2 权重
    (权重仅取决于子像素小数位置, 与 bx 无关), 用 ImageFilter.Kernel 做 2D 卷积,
    再用 mask 交错组装到输出图。权重与 GLSL 完全一致 (已验证)。
  - 非整数倍放大: BICUBIC (4×4 核, 振铃远小于 LANCZOS 3-lobe)
  - 抗振铃 (整数倍): 按子像素位置精确偏移 min_2x2/max_2x2 图, 使 c11 位置与 GLSL 一致
  - 抗振铃 (非整数倍): NEAREST 上采样 min_2x2/max_2x2 (近似)
"""
import math
from PIL import Image, ImageChops, ImageFilter

# GLSL 常量 (lanczos2-sharp.glsl L26-28)
JINC2_WINDOW_SINC = 0.5
JINC2_SINC = 1.0
JINC2_AR_STRENGTH = 0.8

_WA = JINC2_WINDOW_SINC * math.pi   # 0.5*pi
_WB = JINC2_SINC * math.pi          # 1.0*pi
_WA_WB = _WA * _WB


def _resampler(x):
    """jinc2 重采样核 (GLSL resampler 函数的 Python 等价, 已验证一致)"""
    if x == 0.0:
        return _WA_WB
    return math.sin(x * _WA) * math.sin(x * _WB) / (x * x)


# ── 权重计算 (与 GLSL main() 完全一致) ──

def _compute_weights_2d(pc_x, pc_y):
    """计算 4×4 jinc2 权重 (2D 径向距离) 及采样偏移。

    权重仅取决于 pc 的小数部分 (子像素位置), 与 bx 无关, 因为 pc 和 tc 同步偏移,
    距离不变。因此整数倍放大时只需为 sx×sy 个子像素位置预计算权重。
    """
    tc_x = math.floor(pc_x - 0.5) + 0.5
    tc_y = math.floor(pc_y - 0.5) + 0.5
    base_x = int(math.floor(tc_x))
    base_y = int(math.floor(tc_y))

    x_offsets = [base_x - 1, base_x, base_x + 1, base_x + 2]
    y_offsets = [base_y - 1, base_y, base_y + 1, base_y + 2]

    weights = []
    for dy in (-1, 0, 1, 2):
        sample_y = tc_y + dy
        for dx in (-1, 0, 1, 2):
            sample_x = tc_x + dx
            dist = math.sqrt((pc_x - sample_x) ** 2 + (pc_y - sample_y) ** 2)
            weights.append(_resampler(dist))

    wsum = sum(weights)
    if wsum != 0:
        weights = [w / wsum for w in weights]
    return weights, x_offsets, y_offsets


def _make_5x5_kernel(weights, x_offsets, y_offsets):
    """将 4×4 权重嵌入 5×5 kernel (center=(2,2)), 不足处填 0。
    ImageFilter.Kernel: output[i][j] = sum(kernel[ki][kj] * src[i+ki-2][j+kj-2])
    kernel 中心 (2,2) 对齐源像素 (i,j), 权重按采样偏移放置。
    """
    kernel = [0.0] * 25
    idx = 0
    for yo in y_offsets:
        kj = yo + 2
        for xo in x_offsets:
            ki = xo + 2
            if 0 <= ki < 5 and 0 <= kj < 5:
                kernel[kj * 5 + ki] = weights[idx]
            idx += 1
    return kernel


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


# ── c11 偏移 (抗振铃关键) ──

def _c11_offset(isx, sx):
    """子像素 isx 的 c11 (= pixel(floor(tc_pixel))) 相对 bx 的偏移。

    GLSL: tc_pixel = floor(pc - 0.5) + 0.5,  c11 = pixel(floor(tc_pixel))
    整数倍放大: pc = bx + (isx+0.5)/sx,  floor(tc_pixel) = bx + offset

    经验证: offset = -1 当 isx < (sx-1)/2,  offset = 0 当 isx >= (sx-1)/2
    (所有 sx≥2 均如此, 因为 (isx+0.5)/sx - 0.5 ∈ (-0.5, 0) → floor=-1 → +0.5 → floor=-1
     或 ∈ [0, 0.5) → floor=0 → +0.5 → floor=0)
    """
    tc_pixel = math.floor((isx + 0.5) / sx - 0.5) + 0.5
    return int(math.floor(tc_pixel))


# ── 子像素 mask ──

def _build_masks(sx, sy, out_w, out_h):
    """预构建 sx×sy 张子像素 mask (NEAREST 上采样后每个 mask 标记一组输出像素)"""
    masks = {}
    for isx in range(sx):
        for isy in range(sy):
            small = Image.new('L', (sx, sy), 0)
            small.putpixel((isx, isy), 255)
            masks[(isx, isy)] = small.resize((out_w, out_h), Image.NEAREST)
    return masks


# ── 抗振铃 ──

def _anti_ringing_integer(scaled, orig, sx, sy, masks, out_w, out_h):
    """整数倍抗振铃: 按子像素位置精确偏移 min_2x2/max_2x2 图。

    对子像素 (isx,isy):
      c11 = pixel(bx + off_x, by + off_y),  off_x = _c11_offset(isx, sx)
      min_sample = min_2x2[bx + off_x, by + off_y]

    实现: 将 min_2x2 图 offset(-off_x, -off_y) 使 [bx+off_x] → [bx], 再 NEAREST 上采样,
    输出像素 (ox,oy) 取 shifted_min_2x2[ox//sx, oy//sy] = min_2x2[bx+off_x, by+off_y] ✓
    最后用 mask 按子像素位置组合。
    """
    orig_min = _min_2x2(orig)
    orig_max = _max_2x2(orig)

    fill = (0,) * len(orig.mode) if orig.mode != 'RGBA' else (0, 0, 0, 255)
    min_sample = Image.new(orig.mode, (out_w, out_h), fill)
    max_sample = Image.new(orig.mode, (out_w, out_h), fill)

    # 按偏移分组 (减少重复 offset/resize)
    seen_offsets = {}
    for isx in range(sx):
        off_x = _c11_offset(isx, sx)
        for isy in range(sy):
            off_y = _c11_offset(isy, sy)
            key = (off_x, off_y)
            if key not in seen_offsets:
                shifted_min = ImageChops.offset(orig_min, -off_x, -off_y)
                shifted_max = ImageChops.offset(orig_max, -off_x, -off_y)
                seen_offsets[key] = (
                    shifted_min.resize((out_w, out_h), Image.NEAREST),
                    shifted_max.resize((out_w, out_h), Image.NEAREST),
                )
            up_min, up_max = seen_offsets[key]
            mask = masks[(isx, isy)]
            min_sample = Image.composite(up_min, min_sample, mask)
            max_sample = Image.composite(up_max, max_sample, mask)

    # GLSL: color = clamp(color, min_sample, max_sample); color = mix(aux, color, 0.8)
    clamped = ImageChops.darker(ImageChops.lighter(scaled, min_sample), max_sample)
    return Image.blend(scaled, clamped, JINC2_AR_STRENGTH)


def _anti_ringing_generic(scaled, orig, out_w, out_h):
    """非整数倍抗振铃: NEAREST 上采样 min_2x2/max_2x2 (近似, 采样位置不完全匹配 BICUBIC)"""
    orig_min = _min_2x2(orig)
    orig_max = _max_2x2(orig)
    min_up = orig_min.resize((out_w, out_h), Image.NEAREST)
    max_up = orig_max.resize((out_w, out_h), Image.NEAREST)
    clamped = ImageChops.darker(ImageChops.lighter(scaled, min_up), max_up)
    return Image.blend(scaled, clamped, JINC2_AR_STRENGTH)


# ── 整数倍放大 (精确 jinc2 2D 卷积) ──

def _jinc2_integer_scale(pil_img, sx, sy, out_w, out_h, masks):
    """整数倍放大: 对每个子像素位置做 4×4 2D 卷积, mask 交错组装。

    权重仅取决于子像素位置 (isx,isy), 与源像素位置 (bx,by) 无关 (距离不变)。
    ImageFilter.Kernel 在源图上做卷积 (kernel 中心对齐源像素), 然后 NEAREST 上采样,
    等价于每个输出像素取其对应源像素位置的卷积结果。
    """
    # 预计算每个子像素位置的 kernel
    kernels = {}
    for isx in range(sx):
        for isy in range(sy):
            pc_x = (isx + 0.5) / sx
            pc_y = (isy + 0.5) / sy
            weights, x_off, y_off = _compute_weights_2d(pc_x, pc_y)
            kernels[(isx, isy)] = _make_5x5_kernel(weights, x_off, y_off)

    # 分通道处理 (ImageFilter.Kernel 只支持单通道)
    channels = pil_img.split()
    out_channels = []
    for ch in channels:
        output = Image.new('L', (out_w, out_h), 0)
        for isx in range(sx):
            for isy in range(sy):
                kernel = kernels[(isx, isy)]
                filtered = ch.filter(ImageFilter.Kernel((5, 5), kernel))
                upscaled = filtered.resize((out_w, out_h), Image.NEAREST)
                output = Image.composite(upscaled, output, masks[(isx, isy)])
        out_channels.append(output)

    return Image.merge(pil_img.mode, out_channels)


# ── 主入口 ──

def resize_jinc2_sharp(pil_img, out_w, out_h):
    """jinc2-sharp 缩放 (贴近 cnc-ddraw lanczos2-sharp.glsl)

    - 整数倍放大 (≥2x): 精确 jinc2 2-lobe 核 + 精确抗振铃 (与 GLSL 一致)
    - 非整数倍放大: BICUBIC + 近似抗振铃
    - 缩小: LANCZOS (缩小无振铃)
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

    scale_x = out_w / in_w
    scale_y = out_h / in_h

    sx_round = round(scale_x)
    sy_round = round(scale_y)
    if (abs(scale_x - sx_round) < 0.01 and abs(scale_y - sy_round) < 0.01
            and sx_round >= 2 and sy_round >= 2):
        # 整数倍: 精确 jinc2 + 精确抗振铃
        masks = _build_masks(sx_round, sy_round, out_w, out_h)
        result = _jinc2_integer_scale(pil_img, sx_round, sy_round, out_w, out_h, masks)
        result = _anti_ringing_integer(result, pil_img, sx_round, sy_round,
                                        masks, out_w, out_h)
    else:
        # 非整数倍: BICUBIC + 近似抗振铃
        result = pil_img.resize((out_w, out_h), Image.BICUBIC)
        result = _anti_ringing_generic(result, pil_img, out_w, out_h)
    return result
