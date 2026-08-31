"""
grp_data — GRP 图集数据加载共享模块
====================================
从 grp_editor.py 提取的纯数据逻辑 (无 UI 依赖)。
供 mat_editor / item_editor 等编辑器共享使用。

依赖: editor_utils.lzss (LZSS 解压缩)
"""
import io
import os
import struct
import wave
from pathlib import Path
from typing import List, Optional

from editor_utils.lzss import lzss_decompress_stream


# ── LZSS 本地别名 (保持与 grp_editor 接口一致) ──
def lzss_decompress(data, target_size):
    return lzss_decompress_stream(data, target_size)


# ── RLE 字节对引擎 (GRP 特有) ──────────────────────────
def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    out = bytearray()
    pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count, value = data[pos], data[pos + 1]
        pos += 2
        out.extend(bytes([value] * count))
    return bytes(out[:target_size])


def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    total, pos = 0, 0
    while pos + 1 < len(data):
        total += data[pos]
        pos += 2
    return total == expected_size


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class GRPSection:
    def __init__(self, index: int, offset: int, width: int, height: int,
                 comp_a: int, comp_b: int):
        self.index = index
        self.offset = offset
        self.width = width
        self.height = height
        self.comp_a = comp_a
        self.comp_b = comp_b
        self.uncomp_a = width * height * 2
        self._pixels: Optional[bytes] = None
        self._decoded_a = False
        self._layer1: Optional[bytes] = None
        self._layer2: Optional[bytes] = None
        self._decoded_b = False
        self.has_layer2 = False
        self._orig_frame_a: Optional[bytes] = None
        self._orig_frame_b: Optional[bytes] = None
        self._orig_fb_declared: int = 0
        self._modified_a = False
        self._modified_b = False

    @property
    def pixels(self):
        return self._pixels

    @property
    def layer1(self):
        return self._layer1

    @property
    def layer2(self):
        return self._layer2

    @property
    def is_decoded_a(self):
        return self._decoded_a

    @property
    def is_decoded_b(self):
        return self._decoded_b

    @property
    def type_label(self):
        return f"IMG {self.width}×{self.height}"


class GRPAudioSection:
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index
        self.offset = offset
        self.size = size
        self._raw = raw_data
        self._wav_info = ""
        self._duration = 0.0
        self._samples: Optional[list] = None

    @property
    def raw(self):
        return self._raw

    @raw.setter
    def raw(self, v):
        self._raw = v

    @property
    def type_label(self):
        if self._wav_info:
            return f"AUD {self._wav_info} {self._duration:.1f}s"
        return f"AUD {self.size}B"

    @property
    def has_samples(self):
        return self._samples is not None

    def parse_wav(self):
        if not self._raw or len(self._raw) < 44:
            return
        try:
            f = io.BytesIO(self._raw)
            with wave.open(f, 'rb') as wf:
                ch, sr, sw, nf = wf.getnchannels(), wf.getframerate(), wf.getsampwidth(), wf.getnframes()
                self._wav_info = f"{ch}ch {sr}Hz {sw * 8}bit"
                self._duration = nf / sr if sr > 0 else 0
                if nf > 0 and sw > 0:
                    frames = wf.readframes(nf)
                    if sw == 1:
                        fmt, n_per = f"<{len(frames)}b", len(frames)
                    elif sw == 2:
                        fmt, n_per = f"<{len(frames) // 2}h", len(frames) // 2
                    else:
                        fmt, n_per = f"<{len(frames) // sw}i", len(frames) // sw
                    raw = struct.unpack(fmt, frames[:struct.calcsize(fmt)])
                    if ch == 2:
                        raw = [(raw[i] + raw[i + 1]) // 2 for i in range(0, len(raw) - 1, 2)]
                    self._samples = list(raw)
        except Exception:
            pass


class GRPDataSection:
    def __init__(self, index: int, offset: int, size: int, raw_data: Optional[bytes] = None):
        self.index = index
        self.offset = offset
        self.size = size
        self._raw = raw_data

    @property
    def raw(self):
        return self._raw

    @property
    def type_label(self):
        return f"DATA {self.size}B"


class GRPFile:
    def __init__(self):
        self.sections: List[GRPSection] = []
        self.audio_sections: List[GRPAudioSection] = []
        self.data_sections: List[GRPDataSection] = []
        self.idx_offsets: List[int] = []
        self.filepath: Optional[str] = None
        self.idx_path: Optional[str] = None
        self._raw_data: bytes = b""

    @property
    def total_sections(self):
        return len(self.sections) + len(self.audio_sections) + len(self.data_sections)

    def all_sorted(self):
        items = []
        for s in self.sections:
            items.append(('IMG', s.index, s))
        for a in self.audio_sections:
            items.append(('AUD', a.index, a))
        for d in self.data_sections:
            items.append(('DATA', d.index, d))
        items.sort(key=lambda x: x[1])
        return items


# ═══════════════════════════════════════════════════════════
# 文件 I/O
# ═══════════════════════════════════════════════════════════

def load_grp(filepath: str, idx_path: Optional[str] = None) -> GRPFile:
    """加载 GRP 文件，返回 GRPFile 对象"""
    grp = GRPFile()
    grp.filepath = filepath
    grp._raw_data = Path(filepath).read_bytes()
    data = grp._raw_data
    fsize = len(data)
    if idx_path is None:
        for ext in ['.IDX', '.idx']:
            c = str(Path(filepath).with_suffix(ext))
            if os.path.exists(c):
                idx_path = c
                break
    if idx_path and os.path.exists(idx_path):
        idata = Path(idx_path).read_bytes()
        if len(idata) >= 8 and len(idata) % 4 == 0:
            offs = [struct.unpack_from("<I", idata, i)[0] for i in range(0, len(idata), 4)]
            if offs and offs[-1] == fsize:
                grp.idx_offsets = offs
                grp.idx_path = idx_path
    if grp.idx_offsets:
        num = len(grp.idx_offsets) - 1
        boundaries = [(grp.idx_offsets[i], grp.idx_offsets[i + 1]) for i in range(num)]
    else:
        boundaries = []
        off = 0
        while off + 12 <= fsize:
            w, h, ca, cb = struct.unpack_from("<HHII", data, off)
            if w == 0 or h == 0 or w > 4096 or h > 4096:
                break
            ss = 12 + ca + cb
            if off + ss > fsize:
                break
            boundaries.append((off, off + ss))
            off += ss
        if boundaries:
            grp.idx_offsets = [b[0] for b in boundaries] + [boundaries[-1][1]]
    for idx, (so, eo) in enumerate(boundaries):
        sz = eo - so
        if sz >= 12:
            w, h, ca, cb = struct.unpack_from("<HHII", data, so)
            if (1 <= w <= 4096 and 1 <= h <= 4096 and
                    12 + ca + cb == sz and ca > 0 and cb > 0):
                sec = GRPSection(idx, so, w, h, ca, cb)
                fa_off = so + 12
                fb_off = fa_off + ca
                sec._orig_frame_a = data[fa_off:fa_off + ca]
                sec._orig_frame_b = data[fb_off:fb_off + cb]
                if cb >= 4:
                    sec._orig_fb_declared = struct.unpack_from("<I", data, fb_off)[0]
                grp.sections.append(sec)
                continue
        if sz >= 12 and data[so:so + 4] == b"RIFF":
            asec = GRPAudioSection(idx, so, sz, data[so:eo])
            asec.parse_wav()
            grp.audio_sections.append(asec)
            continue
        grp.data_sections.append(GRPDataSection(idx, so, sz, data[so:eo]))
    return grp


def _decode_section_a(grp: GRPFile, sec: GRPSection):
    """解码 GRP section 的 A 帧 (像素数据)"""
    if sec._decoded_a:
        return
    data = grp._raw_data
    fa_off = sec.offset + 12
    uncomp_sz = struct.unpack_from("<I", data, fa_off)[0]
    lzss_data = data[fa_off + 4:fa_off + sec.comp_a]
    sec._pixels = lzss_decompress(lzss_data, min(uncomp_sz, sec.uncomp_a))
    if len(sec._pixels) < sec.uncomp_a:
        sec._pixels = sec._pixels + b'\x00' * (sec.uncomp_a - len(sec._pixels))
    sec._decoded_a = True


def _decode_section_b(grp: GRPFile, sec: GRPSection):
    """解码 GRP section 的 B 帧 (逐像素双层遮罩数据)。

    逆向依据 sub_410E18 (RLE 字节对) + sub_42FA50:
      dword_824288 = 解压后首地址 = Layer1;  dword_82428C = dword_824288 + W*H = Layer2
      精灵资源 +28 (a1[7]) 指向 dword_824288 (=L1), 表明 L1 为逐像素遮挡采样图。
    语义:
      L1 = 前景遮挡深度 (sub_459F78: 精灵像素仅当 L1[世界像素] < 实体深度 时绘制)
      L2 = 地形碰撞类型 (sub_406E50: 实体深度=脚下包围盒内 L2 最小值>1)
    单层回退: 非 RLE 时按 LZSS 解压, 隔字节取 L1。"""
    if sec._decoded_b:
        return
    data = grp._raw_data
    fb_off = sec.offset + 12 + sec.comp_a
    if fb_off + 4 > len(data):
        return
    declared = struct.unpack_from("<I", data, fb_off)[0]
    cs, ce = fb_off + 4, fb_off + 4 + sec.comp_b - 4
    comp_data = data[cs:ce]
    total_px = sec.width * sec.height
    if rle_bp_probe(comp_data, declared):
        raw = rle_bp_decompress(comp_data, declared)
        sec._layer1 = raw[:total_px]
        if declared == total_px * 2 and len(raw) >= total_px * 2:
            sec._layer2 = raw[total_px:total_px * 2]
            sec.has_layer2 = True
    else:
        raw = lzss_decompress(comp_data, sec.uncomp_a)
        sec._layer1 = bytes(raw[i] for i in range(0, min(len(raw), total_px * 2), 2))
    sec._decoded_b = True
