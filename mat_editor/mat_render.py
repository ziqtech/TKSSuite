# -*- coding: utf-8 -*-
"""mat_editor 渲染层 — JVG 精灵帧提取、PIL 图像混合合成、SC.GRP 背景加载。
从 mat_editor.py 原样迁出 (含各帧缓存), 无业务逻辑 (§工程化拆分)。"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from PySide6.QtGui import QPixmap, QImage

try:
    from PIL import Image, ImageChops, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

_JVG_CACHE = {}  # filepath -> JVGFile
_SPRITE_CACHE = {}  # (jvg_id, block_idx, frame_idx) -> PIL.Image


# ============================================================
# JVG 精灵帧辅助
# ============================================================
def _get_jvg(filepath):
    """加载 JVG 文件 (缓存) — 从 editor_utils.jvg_data 共享模块导入"""
    if filepath in _JVG_CACHE: return _JVG_CACHE[filepath]
    if not os.path.exists(filepath): return None
    try:
        from editor_utils.jvg_data import load_jvg
        jvg = load_jvg(filepath)
        _JVG_CACHE[filepath] = jvg
        return jvg
    except ImportError:
        return None

def _get_jvg_frame(jvg, global_idx):
    """按全局索引获取 JVG (block, frame_in_block)"""
    if not jvg or global_idx < 0: return None, None, None
    for blk in jvg.blocks:
        if global_idx < blk.frame_count:
            return blk, blk.frames[global_idx], global_idx
        global_idx -= blk.frame_count
    return None, None, None

def _extract_rgba_from_frame(frame, palette):
    """提取 JVG 帧的像素并转为 RGBA bytes，消除冗余的像素遍历代码。
    遍历 frame.pixels/frame.alpha: al[p]==0 的像素留透明(0,0,0,0)，
    其余按调色板查色写 RGB + alpha=255。空尺寸返回 None。"""
    if frame.width <= 0 or frame.height <= 0:
        return None
    pr = palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x
            off = p * 4
            if p < len(al) and al[p] == 0:
                continue
            ci = px[p] if p < len(px) else 0
            rgba[off] = pr[ci*3]
            rgba[off+1] = pr[ci*3+1]
            rgba[off+2] = pr[ci*3+2]
            rgba[off+3] = 255
    return bytes(rgba)

def _jvg_sprite_to_pil(jvg, block_idx, frame_idx=0):
    """从 JVG 的 block[block_idx].frames[frame_idx] 提取 PIL Image (缓存)"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _SPRITE_CACHE: return _SPRITE_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    rgba_bytes = _extract_rgba_from_frame(frame, blk.palette)
    if not rgba_bytes: return None
    img = Image.frombytes('RGBA', (frame.width, frame.height), rgba_bytes)
    _SPRITE_CACHE[key] = img
    return img

_SHADOW_CACHE = {}  # (jvg_id, block_idx, frame_idx) → PIL.Image (减法混合近似)

def _make_subtractive_shadow(jvg, block_idx, frame_idx):
    """将 JVG 阴影帧转为减法混合近似: 黑底 + alpha=src亮度
    sub_45871C: dst=max(dst-src,0) → Canvas alpha 近似: dst*(1-L/255)"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _SHADOW_CACHE: return _SHADOW_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    pr = blk.palette.to_rgb888()
    rgba = bytearray(frame.width * frame.height * 4)
    px, al = frame.pixels, frame.alpha
    for y in range(frame.height):
        for x in range(frame.width):
            p = y * frame.width + x
            off = p * 4
            if p < len(al) and al[p] == 0: continue
            ci = px[p] if p < len(px) else 0
            r, g, b = pr[ci*3], pr[ci*3+1], pr[ci*3+2]
            L = int(0.299*r + 0.587*g + 0.114*b)  # NTSC 亮度
            rgba[off] = 0
            rgba[off+1] = 0
            rgba[off+2] = 0
            rgba[off+3] = L
    img = Image.frombytes('RGBA', (frame.width, frame.height), bytes(rgba))
    _SHADOW_CACHE[key] = img
    return img

_BLEND_CACHE = {}  # (jvg_id, blk_idx, frame_idx, mode, param) → PIL.Image

def _get_blended_sprite(jvg, block_idx, frame_idx, mode=0, param=0):
    """取 JVG 精灵帧并按混合模式处理，带缓存。
    mode: 0=正常 1=染色 2=加法发光 3=减法压暗 4=亮度alpha 5=水平翻转"""
    if mode == 0:
        return _jvg_sprite_to_pil(jvg, block_idx, frame_idx)
    key = (id(jvg), block_idx, frame_idx, mode, param)
    if key in _BLEND_CACHE: return _BLEND_CACHE[key]
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    rgba_bytes = _extract_rgba_from_frame(frame, blk.palette)
    if not rgba_bytes: return None
    img = Image.frombytes('RGBA', (frame.width, frame.height), rgba_bytes)
    if mode == 5:
        img = ImageOps.mirror(img)
    elif mode == 1:
        # 染色: 按 param 颜色值乘入 RGB 通道 (sub_454D24)
        r_tint = (param >> 10) & 0x1F
        g_tint = (param >> 5) & 0x1F
        b_tint = param & 0x1F
        if param > 0 and param <= 31:
            sf_r = r_tint / 31.0
            sf_g = g_tint / 31.0
            sf_b = b_tint / 31.0
            r_ch, g_ch, b_ch, a_ch = img.split()
            r_ch = r_ch.point(lambda v: int(v * sf_r))
            g_ch = g_ch.point(lambda v: int(v * sf_g))
            b_ch = b_ch.point(lambda v: int(v * sf_b))
            img = Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))
    elif mode == 2:
        # 加法发光近似: 白色半透明叠加 (sub_4559D0)
        # param=0或>31 → scale=1.0; 0<param<=31 → scale=param/32
        scale = 1.0 if param == 0 or param > 31 else param / 32.0
        if scale > 0:
            r_ch, g_ch, b_ch, a_ch = img.split()
            # 像素越亮 → 加法贡献越大; alpha = 亮度 * scale
            lum = r_ch.point(lambda v: int(v * 0.299)) if False else r_ch

            lum = ImageChops.add(
                ImageChops.add(
                    r_ch.point(lambda v: int(v * 0.299)),
                    g_ch.point(lambda v: int(v * 0.587))),
                b_ch.point(lambda v: int(v * 0.114)))
            new_a = lum.point(lambda v: int(min(255, v * scale)))
            white = Image.new('L', img.size, 255)
            img = Image.merge('RGBA', (white, white, white, new_a))
    elif mode == 3:
        # 减法压暗: 同阴影处理 — 黑底+亮度为alpha (sub_45871C)
        px_new = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = px_new[x, y]
                if a == 0: continue
                L = int(0.299*r + 0.587*g + 0.114*b)
                px_new[x, y] = (0, 0, 0, L)
    elif mode == 4:
        # 亮度 alpha: 按 src 亮度修改 alpha 通道 (sub_459854)
        r_ch, g_ch, b_ch, a_ch = img.split()

        lum = ImageChops.add(
            ImageChops.add(
                r_ch.point(lambda v: int(v * 0.299)),
                g_ch.point(lambda v: int(v * 0.587))),
            b_ch.point(lambda v: int(v * 0.114)))
        # 亮度 0~255 → 5-bit (0~31) → alpha 0~255
        new_a = lum.point(lambda v: int(v * 31 / 255) * 8)
        img = Image.merge('RGBA', (r_ch, g_ch, b_ch, new_a))
    _BLEND_CACHE[key] = img
    return img

def _get_dir_frame(blk, d13, d16, d53, anim_cycle=0):
    """按朝向计算 JVG block 内的帧索引。
    sub_4077E4: [14] = [17] + [52] + [16] * dir_mult
    [16] 是 sub_4540E8 返回的总帧数, 需按方向数折算 fpd (frames_per_direction)
    帧在 block 内按方向分组: [dir0_f0..dir0_fn][dir1_f0..dir1_fn]... """
    if not blk or blk.frame_count == 0: return 0, 1
    if d53 == 4:
        fpd = max(1, blk.frame_count // 4)
        dir_grp = max(0, min(3, (d13 - 1) >> 1))
    elif d53 == 8:
        fpd = max(1, blk.frame_count // 8)
        dir_grp = max(0, min(7, d13 - 1))
    else:
        fpd = blk.frame_count
        dir_grp = 0
    base = dir_grp * fpd
    frame = base + (anim_cycle % fpd)
    if frame >= blk.frame_count: frame = base
    return frame, fpd

# ============================================================
# PIL 图像合成 (sub_406864 switch d24 → 严格按逆向实现)
# ============================================================
_RGBA_CACHE = {}  # (jvg_id, block_idx, frame_idx) → PIL.Image(RGBA)

def _get_jvg_frame_rgba(jvg, block_idx, frame_idx):
    """取 JVG 帧为 PIL RGBA Image (缓存), 供合成函数使用"""
    key = (id(jvg), block_idx, frame_idx)
    if key in _RGBA_CACHE: return _RGBA_CACHE[key].copy()
    if not jvg or block_idx < 0 or block_idx >= jvg.block_count: return None
    blk = jvg.blocks[block_idx]
    if frame_idx < 0 or frame_idx >= blk.frame_count: return None
    frame = blk.frames[frame_idx]
    if frame.width <= 0 or frame.height <= 0: return None
    rgba_bytes = _extract_rgba_from_frame(frame, blk.palette)
    if not rgba_bytes: return None
    img = Image.frombytes('RGBA', (frame.width, frame.height), rgba_bytes)
    _RGBA_CACHE[key] = img.copy()
    return img

def _pil_normal(composite, rgba_src, dx, dy):
    """mode 0: 正常 alpha 贴图"""
    if composite is None or rgba_src is None: return
    try:
        composite.paste(rgba_src, (dx, dy), rgba_src)
    except Exception:
        pass

def _pil_tint(rgba_src, param):
    """mode 1: 染色 — sub_454D24 按 param 5-bit RGB 分量缩放通道。
    param=0 或 >31 → 不变; 0<param<=31 → R*=r/31, G*=g/31, B*=b/31"""
    if rgba_src is None: return None
    if param <= 0 or param > 31: return rgba_src
    r_tint = (param >> 10) & 0x1F
    g_tint = (param >> 5) & 0x1F
    b_tint = param & 0x1F
    r_ch, g_ch, b_ch, a_ch = rgba_src.split()
    r_ch = r_ch.point(lambda v: int(v * r_tint / 31))
    g_ch = g_ch.point(lambda v: int(v * g_tint / 31))
    b_ch = b_ch.point(lambda v: int(v * b_tint / 31))
    return Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))

def _pil_additive(composite, rgba_src, dx, dy, param):
    """mode 2: 加法饱和混合 — sub_4559D0/sub_4573A0
    param=0或>31 → full min(dst+src, 255); 0<param<=31 → min(dst+src*param/32, 255)"""
    if composite is None or rgba_src is None: return
    try:

        sw, sh = rgba_src.size
        cw, ch = composite.size
        l = max(0, dx)
        t = max(0, dy)
        r = min(cw, dx + sw)
        b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        if 0 < param <= 31:
            factor = param / 32.0
            masked = masked.point(lambda v, f=factor: int(v * f))
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.add(dst_crop, masked)  # saturated: min(a+b, 255)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

def _pil_subtract(composite, rgba_src, dx, dy):
    """mode 3: 减法饱和混合 — sub_45871C
    dst.RGB = max(dst - src, 0) 逐通道独立"""
    if composite is None or rgba_src is None: return
    try:

        sw, sh = rgba_src.size
        cw, ch = composite.size
        l = max(0, dx)
        t = max(0, dy)
        r = min(cw, dx + sw)
        b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        zero_bg = Image.new('RGB', sub.size, (0, 0, 0))
        masked = Image.composite(src_rgb, zero_bg, alpha)
        dst_crop = composite.crop((l, t, r, b))
        blended = ImageChops.subtract(dst_crop, masked)  # saturated: max(a-b, 0)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

def _pil_luma_alpha(composite, rgba_src, dx, dy):
    """mode 4: 按 src 亮度做 alpha blend — sub_459854
    α = NTSC_luma_5bit(src); α=0跳过; α>28覆盖; else dst*(32-α)/32+src*α/32"""
    if composite is None or rgba_src is None: return
    try:

        sw, sh = rgba_src.size
        cw, ch = composite.size
        l = max(0, dx)
        t = max(0, dy)
        r = min(cw, dx + sw)
        b = min(ch, dy + sh)
        if r <= l or b <= t: return
        sl, st = l - dx, t - dy
        sr, sb = r - dx, b - dy
        sub = rgba_src.crop((sl, st, sr, sb))
        if sub.mode != 'RGBA': sub = sub.convert('RGBA')
        src_alpha = sub.split()[3]
        src_rgb = sub.convert('RGB')
        luma = src_rgb.convert('L')  # ITU-R 601-2: 0.299R+0.587G+0.114B (游戏用 0.30/0.59/0.11, 差<0.2%)
        mask_luma = luma.point(lambda v: 0 if v == 0 else (255 if v > 224 else v))
        alpha_bin = src_alpha.point(lambda v: 255 if v > 0 else 0)
        mask = ImageChops.multiply(mask_luma, alpha_bin)
        dst_crop = composite.crop((l, t, r, b))
        blended = Image.composite(src_rgb, dst_crop, mask)
        composite.paste(blended, (l, t))
    except Exception:
        try: composite.paste(rgba_src, (dx, dy), rgba_src)
        except Exception: pass

# ============================================================
# SC.GRP 场景背景加载
# ============================================================
def load_scene_background(sc_grp_path, sc_idx_path, scene_id):
    """加载 SC.GRP 中原始 section 索引对应的背景图。
    SC.GRP 中 image+data 混排 (206图像+8数据=214段),
    必须按原始索引映射, 不能直接用 grp.sections 数组下标。"""
    if not os.path.exists(sc_grp_path): return None
    try:
        from editor_utils.grp_data import load_grp, _decode_section_a
    except ImportError:
        return None

    try:
        grp = load_grp(sc_grp_path, sc_idx_path)
        if not grp: return None
        idx_map = {sec.index: sec for sec in grp.sections}
        sec = idx_map.get(scene_id)
        if not sec or sec.width <= 0 or sec.height <= 0: return None

        _decode_section_a(grp, sec)
        if not sec.pixels: return None

            # PIL C 引擎直接解码 RGB565 字节流，替代纯 Python 的 225 万次位移循环
        img = Image.frombytes('RGB', (sec.width, sec.height), sec.pixels, 'raw', 'BGR;16')
        return img
    except Exception:
        return None


def load_scene_background_from_bytes(section_data: bytes):
    """从原始 GRP section 字节数据直接解码场景背景图。
    用于从内存中的 _sc_grp_pending 数据渲染场景。"""
    if not section_data or len(section_data) < 12:
        return None
    try:
        from editor_utils.grp_data import lzss_decompress as grp_lzss_decompress
    except ImportError:
        return None

    try:
        w, h, comp_a, comp_b = struct.unpack_from('<HHII', section_data, 0)
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            return None
        if 12 + comp_a + comp_b > len(section_data):
            return None
        # 解压 frame A: 前4字节为未压缩大小，其余为 LZSS 数据
        fa_data = section_data[12:12 + comp_a]
        if len(fa_data) < 4:
            return None
        uncomp_sz = struct.unpack_from('<I', fa_data, 0)[0]
        lzss_data = fa_data[4:]
        target_size = w * h * 2
        pixels = grp_lzss_decompress(lzss_data, min(uncomp_sz, target_size))
        if len(pixels) < target_size:
            pixels = pixels + b'\x00' * (target_size - len(pixels))
        img = Image.frombytes('RGB', (w, h), pixels[:target_size], 'raw', 'BGR;16')
        return img
    except Exception:
        return None


# ============================================================
# GRP Frame B 双层 (前景遮挡 L1 / 地形碰撞 L2) — 逆向 sub_411308/sub_42FA50/sub_459F78
#   L1 = 前景遮挡深度 (逐像素): 精灵像素仅当 L1[世界] < 实体深度 时绘制
#   L2 = 地形碰撞类型 (逐像素): 实体深度 = 脚下包围盒内 L2 最小值>1 (sub_406E50)
# ============================================================


def _decode_section_b_layers(section_data):
    """从原始 GRP section 字节直接解码 Frame B → (L1, L2, w, h)。失败返回 (None,None,0,0)。"""
    if not section_data or len(section_data) < 12:
        return None, None, 0, 0
    try:
        from editor_utils.grp_data import rle_bp_decompress, rle_bp_probe
    except ImportError:
        return None, None, 0, 0
    try:
        w, h, comp_a, comp_b = struct.unpack_from('<HHII', section_data, 0)
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            return None, None, 0, 0
        if 12 + comp_a + comp_b > len(section_data) or comp_b < 4:
            return None, None, 0, 0
        fb_off = 12 + comp_a
        declared = struct.unpack_from('<I', section_data, fb_off)[0]
        comp = section_data[fb_off + 4: fb_off + comp_b]
        total_px = w * h
        if not rle_bp_probe(comp, declared):
            return None, None, w, h
        raw = rle_bp_decompress(comp, declared)
        l1 = raw[:total_px]
        l2 = raw[total_px:total_px * 2] if (declared == total_px * 2 and len(raw) >= total_px * 2) else None
        return l1, l2, w, h
    except Exception:
        return None, None, 0, 0


def load_scene_layers(sc_grp_path, sc_idx_path, scene_id):
    """加载 SC.GRP 场景的 Frame B 双层 (L1 前景遮挡深度 / L2 地形碰撞类型)。
    返回 (layer1_bytes, layer2_bytes, width, height); 失败返回 (None, None, 0, 0)。"""
    if not os.path.exists(sc_grp_path):
        return None, None, 0, 0
    try:
        from editor_utils.grp_data import load_grp, _decode_section_b
    except ImportError:
        return None, None, 0, 0
    try:
        grp = load_grp(sc_grp_path, sc_idx_path)
        if not grp:
            return None, None, 0, 0
        idx_map = {sec.index: sec for sec in grp.sections}
        sec = idx_map.get(scene_id)
        if not sec or sec.width <= 0 or sec.height <= 0:
            return None, None, 0, 0
        _decode_section_b(grp, sec)
        return sec.layer1, sec.layer2, sec.width, sec.height
    except Exception:
        return None, None, 0, 0


def load_scene_layers_from_bytes(section_data):
    """从内存 GRP section 字节解码 Frame B 双层 (供 _sc_grp_pending 路径)。"""
    return _decode_section_b_layers(section_data)


def load_scene_background_and_layers(sc_grp_path, sc_idx_path, scene_id):
    """一次性加载场景背景图(Frame A) + Frame B 双层(L1/L2), 仅解析一次 GRP。
    返回 (bg_pil_or_None, l1_bytes, l2_bytes, width, height)。"""
    if not os.path.exists(sc_grp_path):
        return None, None, None, 0, 0
    try:
        from editor_utils.grp_data import load_grp, _decode_section_a, _decode_section_b
    except ImportError:
        return None, None, None, 0, 0
    try:
        grp = load_grp(sc_grp_path, sc_idx_path)
        if not grp:
            return None, None, None, 0, 0
        idx_map = {sec.index: sec for sec in grp.sections}
        sec = idx_map.get(scene_id)
        if not sec or sec.width <= 0 or sec.height <= 0:
            return None, None, None, 0, 0
        _decode_section_a(grp, sec)
        bg = None
        if sec.pixels:
            bg = Image.frombytes('RGB', (sec.width, sec.height), sec.pixels, 'raw', 'BGR;16')
        _decode_section_b(grp, sec)
        return bg, sec.layer1, sec.layer2, sec.width, sec.height
    except Exception:
        return None, None, None, 0, 0


def make_layer_image(layer_bytes, w, h):
    """逐像素层字节 → PIL 'L' 灰度图 (供遮挡采样/深度计算); 失败返回 None。"""
    if not layer_bytes or w <= 0 or h <= 0:
        return None
    try:
        buf = layer_bytes
        if len(buf) < w * h:
            buf = buf + b'\x00' * (w * h - len(buf))
        return Image.frombytes('L', (w, h), bytes(buf[:w * h]))
    except Exception:
        return None


def entity_occlusion_depth(l2_img, w, h, bx, by, bw, bh):
    """逆向 sub_406E50: 实体深度 = 脚下碰撞盒内 L2 的最小值(>1); 无则为 1。
    l2_img 为 L2 的 PIL 'L' 图。越界/无数据返回 1 (走简单渲染, 不遮挡)。"""
    if l2_img is None or bw <= 0 or bh <= 0:
        return 1
    l = max(0, bx); t = max(0, by)
    r = min(w, bx + bw); b = min(h, by + bh)
    if r <= l or b <= t:
        return 1
    try:
        hist = l2_img.crop((l, t, r, b)).histogram()
        for v in range(2, 256):
            if hist[v]:
                return v
    except Exception:
        pass
    return 1


def composite_occluded(composite, sprite_rgba, dx, dy, depth, l1_img, w, h):
    """逆向 sub_459F78 前景遮挡: 精灵像素仅当 L1[世界像素] < depth 时绘制。
    仅在 depth>1 时调用。l1_img=L1 前景深度 'L' 图 (世界坐标对齐背景左上)。"""
    if composite is None or sprite_rgba is None:
        return
    try:
        sw, sh = sprite_rgba.size
        occ = Image.new('L', (sw, sh), 255)  # 默认可绘 (网格外无前景)
        l = max(0, dx); t = max(0, dy)
        r = min(w, dx + sw); b = min(h, dy + sh)
        if l1_img is not None and r > l and b > t:
            sub = l1_img.crop((l, t, r, b))
            mask = sub.point(lambda v, d=depth: 255 if v < d else 0)
            occ.paste(mask, (l - dx, t - dy))
        alpha = sprite_rgba.split()[3]
        final_mask = ImageChops.multiply(alpha, occ)
        composite.paste(sprite_rgba, (dx, dy), final_mask)
    except Exception:
        try:
            composite.paste(sprite_rgba, (dx, dy), sprite_rgba)
        except Exception:
            pass


# ============================================================
# PIL → QPixmap 转换工具
# ============================================================
def _pil_to_qpixmap(pil_img):
    """将 PIL Image (RGBA/RGB) 转换为 QPixmap (不依赖 numpy)"""
    if pil_img is None:
        return QPixmap()
    if pil_img.mode != 'RGBA':
        pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    w, h = pil_img.size
    qimg = QImage(data, w, h, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())

