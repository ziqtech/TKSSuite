"""
jvg_data — JVG 图集数据加载共享模块
====================================
从 jvg_editor_v2.py 提取的纯数据逻辑 (无 UI 依赖)。
供 mat_editor / item_editor 等编辑器共享使用。

依赖: editor_utils.lzss (通过延迟导入避免循环)
"""
import struct
from pathlib import Path
from typing import List, Optional, Tuple

JVG_MAGIC = b"@JVG"
JVM_MAGIC = b"@JVM"
SCREEN_W = 640
HEADER_SIZE = 32


# ── JVG 数据模型 ──────────────────────────────────────────
class PaletteRGB565:
    def __init__(self):
        self.entries: List[int] = [0] * 256

    def to_rgb888(self) -> bytes:
        r = bytearray(768)
        for i, e in enumerate(self.entries):
            r5, g6, b5 = (e >> 11) & 0x1F, (e >> 5) & 0x3F, e & 0x1F
            r[i * 3] = (r5 << 3) | (r5 >> 2)
            r[i * 3 + 1] = (g6 << 2) | (g6 >> 4)
            r[i * 3 + 2] = (b5 << 3) | (b5 >> 2)
        return bytes(r)


class JVGFrame:
    def __init__(self):
        self.x_max = 0
        self.y_max = 0
        self.width = 0
        self.height = 0
        self.row_count = 0
        self._pixels: Optional[bytes] = None
        self._alpha: Optional[bytes] = None
        self.encoded_data = b""
        self._palette: Optional[PaletteRGB565] = None
        # 帧头 8 个 uint16 中未被编辑器使用的保留字段，必须原样保存以免 MOD diff 误判
        self._hdr_unk4 = 0
        self._hdr_unk5 = 0
        self._hdr_unk6 = 0

    @property
    def pixels(self) -> bytes:
        if self._pixels is None and self.encoded_data and self.width > 0 and self.height > 0:
            self._pixels, self._alpha = _decode_rle(self.encoded_data, self.width, self.height)
        return self._pixels if self._pixels is not None else b""

    @pixels.setter
    def pixels(self, val: bytes):
        self._pixels = val

    @property
    def alpha(self) -> bytes:
        if self._alpha is None and self.encoded_data and self.width > 0 and self.height > 0:
            self._pixels, self._alpha = _decode_rle(self.encoded_data, self.width, self.height)
        return self._alpha if self._alpha is not None else b""

    @alpha.setter
    def alpha(self, val: bytes):
        self._alpha = val

    @property
    def x_off(self) -> int:
        v = self.x_max
        return (v - 65536 if v >= 32768 else v) - self.width + 1

    @property
    def y_off(self) -> int:
        v = self.y_max
        return (v - 65536 if v >= 32768 else v) - self.height + 1


class JVMBlock:
    def __init__(self, name: str = ""):
        self.name = name
        self.frames: List[JVGFrame] = []
        self.palette = PaletteRGB565()
        self._header_reserved = bytes(16)  # block头 [16:32] 保留字节，原样保存

    @property
    def frame_count(self) -> int:
        return len(self.frames)


class JVGFile:
    def __init__(self):
        self.blocks: List[JVMBlock] = []
        self.filepath: Optional[str] = None

    @property
    def total_frames(self) -> int:
        return sum(b.frame_count for b in self.blocks)

    @property
    def block_count(self) -> int:
        return len(self.blocks)


# ── JVG 解码器 ─────────────────────────────────────────
def _u16s(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def _decode_rle(data: bytes, w: int, h: int) -> Tuple[bytes, bytes]:
    total = w * h
    out = bytearray(total)
    alpha = bytearray(total)
    recs = []
    pos = 0
    while pos + 4 <= len(data):
        sk = struct.unpack("<H", data[pos:pos + 2])[0]
        rw = struct.unpack("<H", data[pos + 2:pos + 4])[0]
        pos += 4
        px = data[pos:pos + min(rw, len(data) - pos)] if rw > 0 else b""
        pos += len(px)
        recs.append((sk, rw, px))
    if not recs:
        return bytes(out), bytes(alpha)
    simple = (recs[0][0] == 0 and recs[0][1] == w and all(r[1] == w for r in recs))
    if simple:
        for ri, (_, rw, px) in enumerate(recs):
            if ri >= h:
                break
            tr = h - 1 - ri
            for c in range(min(rw, len(px))):
                out[tr * w + c] = px[rw - 1 - c]
                alpha[tr * w + c] = 255
    else:
        gap = max(SCREEN_W - w, 0)
        bp = total - 1
        pg = 0
        for sa, rw, px in recs:
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
            al = min(rw, len(px))
            for k in range(al):
                if 0 <= bp < total:
                    out[bp] = px[k]
                    alpha[bp] = 255
                bp -= 1
            pg = gap if al > 0 and cb + al >= w else 0
    return bytes(out), bytes(alpha)


# ── JVG 文件加载 ─────────────────────────────────────────
def load_jvg(filepath: str) -> JVGFile:
    """加载 JVG 文件，返回 JVGFile 对象"""
    data = Path(filepath).read_bytes()
    if len(data) < 32 or data[:4] != JVG_MAGIC:
        raise ValueError("不是有效的 @JVG 文件")
    jvg = JVGFile()
    jvg.filepath = filepath
    bc = struct.unpack("<I", data[8:12])[0]
    off = HEADER_SIZE
    for bi in range(bc):
        if off + 32 > len(data) or data[off:off + 4] != JVM_MAGIC:
            break
        sc = struct.unpack("<I", data[off + 4:off + 8])[0]
        ds = struct.unpack("<I", data[off + 12:off + 16])[0]
        s1 = off + 32
        co = [struct.unpack("<I", data[s1 + j * 4:s1 + j * 4 + 4])[0] for j in range(sc + 1)]
        po = s1 + (sc + 1) * 4
        blk = JVMBlock(f"block_{bi:02d}")
        for j in range(256):
            blk.palette.entries[j] = struct.unpack("<H", data[po + j * 2:po + j * 2 + 2])[0]
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]
            ws = struct.unpack("<8H", data[mo:mo + 16])
            f = JVGFrame()
            f.x_max = ws[0]
            f.y_max = ws[1]
            f.width = ws[2]
            f.height = ws[3]
            f.row_count = ws[7]
            f._hdr_unk4 = ws[4]
            f._hdr_unk5 = ws[5]
            f._hdr_unk6 = ws[6]
            eo = mo + 16
            f.encoded_data = data[eo:eo + co[si + 1] - co[si] - 16]
            blk.frames.append(f)
        blk._header_reserved = data[off + 16:off + 32]
        off += 32 + (sc + 1) * 4 + 512 + ds
        jvg.blocks.append(blk)
    return jvg
