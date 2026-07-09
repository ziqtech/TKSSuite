"""
Mu.JVG 精灵加载器 — 供各编辑器统一使用 (物品图标 / 状态图标 等)

返回 PIL Image (RGBA) 列表; PIL 不可用或文件无效时返回 None。
图标原始值 + 130 = Mu.JVG 精灵索引 (item_editor 验证)。
"""
import os
import struct


def load_mu_sprites(mu_path):
    """加载 Mu.JVG 并返回 PIL Image 列表 (PIL 可用时) 或 None"""
    try:
        from PIL import Image
    except ImportError:
        return None
    if not mu_path or not os.path.exists(mu_path):
        return None
    with open(mu_path, 'rb') as f:
        data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG':
        return None
    bc = struct.unpack_from('<I', data, 8)[0]
    off = 32
    sprites = []
    for bi in range(bc):
        if off + 32 > len(data) or data[off:off + 4] != b'@JVM':
            break
        sc = struct.unpack_from('<I', data, off + 4)[0]
        ds = struct.unpack_from('<I', data, off + 12)[0]
        s1 = off + 32
        co = [struct.unpack_from('<I', data, s1 + j * 4)[0]
              for j in range(sc + 1)]
        po = s1 + (sc + 1) * 4
        pal_entries = []
        for j in range(256):
            e = struct.unpack_from('<H', data, po + j * 2)[0]
            r = ((e >> 11) & 0x1F) << 3
            g = ((e >> 5) & 0x3F) << 2
            b = (e & 0x1F) << 3
            pal_entries.extend([r, g, b])
        pal_bytes = bytes(pal_entries)
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]
            ws = struct.unpack_from('<8H', data, mo)
            w, h = ws[2], ws[3]
            if w <= 0 or h <= 0:
                sprites.append(None)
                continue
            eo = mo + 16
            ed = data[eo:eo + co[si + 1] - co[si] - 16]
            # RLE 解码 (对齐 jvg_editor _decode_rle)
            total = w * h
            px = bytearray(total)
            alpha = bytearray(total)
            recs = []
            rp = 0
            while rp + 4 <= len(ed):
                sk = struct.unpack_from('<H', ed, rp)[0]
                rw = struct.unpack_from('<H', ed, rp + 2)[0]
                rp += 4
                rw = min(rw, len(ed) - rp)
                rd = ed[rp:rp + rw] if rw > 0 else b''
                rp += rw
                recs.append((sk, rw, rd))
            if not recs:
                continue
            simple = (recs[0][0] == 0 and recs[0][1] == w
                      and all(r[1] == w for r in recs))
            if simple:
                for ri, (_, rw, rpix) in enumerate(recs):
                    if ri >= h:
                        break
                    tr = h - 1 - ri
                    for c in range(min(rw, len(rpix))):
                        px[tr * w + c] = rpix[rw - 1 - c]
                        alpha[tr * w + c] = 255
            else:
                scr_w = 640
                gap = max(scr_w - w, 0)
                bp = total - 1
                pg = 0
                for sa, rw, rpix in recs:
                    rem = sa - pg
                    pg = 0
                    if rem < 0:
                        rem = 0
                    while rem > 0 and bp >= 0:
                        col = (total - 1 - bp) % w
                        tb = w - col
                        if rem <= tb:
                            bp -= rem
                            rem = 0
                        else:
                            bp -= tb
                            rem -= tb + gap
                            rem = max(rem, 0)
                    cb = (total - 1 - bp) % w if bp >= 0 else 0
                    al = min(rw, len(rpix))
                    for k in range(al):
                        if 0 <= bp < total:
                            px[bp] = rpix[k]
                            alpha[bp] = 255
                        bp -= 1
                    pg = gap if al > 0 and cb + al >= w else 0
            # 创建 PIL Image (alpha 通道由 RLE 解码器提供, 不依赖 palette index 0)
            if w > 0 and h > 0:
                img = Image.frombytes('P', (w, h), bytes(px))
                img.putpalette(pal_bytes)
                rgba = img.convert('RGBA')
                a_img = Image.frombytes('L', (w, h), bytes(alpha))
                rgba.putalpha(a_img)
                sprites.append(rgba)
        off += 32 + (sc + 1) * 4 + 512 + ds
    return sprites


def get_sprite_pixmap(sprites, icon_val, size=(24, 24), cache=None):
    """将精灵索引转为 QPixmap (带缓存)。

    Args:
        sprites: load_mu_sprites 返回的 PIL Image 列表
        icon_val: 游戏原始图标值 (实际显示值 +130; item/skill 状态图标约定)
        size: 输出像素尺寸
        cache: 可选的 {cache_key: QPixmap} 字典, 传入则启用缓存
    """
    if not sprites: return None
    idx = icon_val + 130
    if idx < 0 or idx >= len(sprites):
        return None
    sprite = sprites[idx]
    if sprite is None: return None
    cache_key = (idx, size)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    try:
        from PIL import Image
        from PySide6.QtGui import QImage, QPixmap
        img = sprite.resize(size, Image.NEAREST).convert('RGBA')
        data = img.tobytes('raw', 'RGBA')
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        pix = QPixmap.fromImage(qimg)
        if cache is not None:
            cache[cache_key] = pix
        return pix
    except Exception:
        return None


def make_icon_pixmap_getter(sprites, cache):
    """返回一个与编辑器 `_get_icon_pixmap(self, icon_val, size)` 签名兼容的闭包。

    Args:
        sprites: load_mu_sprites 返回的 PIL Image 列表 (或 [])
        cache: QPixmap 缓存字典 (通常为 self._icon_pixmaps)

    用法::
        self._get_icon_pixmap = make_icon_pixmap_getter(self._mu_sprites, self._icon_pixmaps)
    """
    def getter(icon_val, size=(24, 24)):
        return get_sprite_pixmap(sprites, icon_val, size, cache)
    return getter
