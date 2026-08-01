"""
font9696_codec.py — FONT9696 位图字体编解码器
================================================
逆向依据:
  - sub_44ADB0: 字体对象构造 (打开 font9696 文件)
  - sub_44B384: BIG5 字符码 → glyph 索引 → 文件偏移
  - sub_44B208: RLE 解码 (3字节组 → 4 个 6-bit 游程)

文件格式:
  +-----------------------------+
  | 索引表 (Index Table)        |  8 FTYPE × 14915 字形 × 4字节 uint32 LE = 477,280 字节
  +-----------------------------+
  | 字形数据区 (RLE 压缩)        |  变长, 紧接索引表之后
  +-----------------------------+

  - 无文件头/magic number
  - 每项 uint32 指向该字形 RLE 数据在文件中的绝对偏移
  - 字形数据长度 = index[i+1] - index[i]
  - 字形: 96×96, 1bpp, 共 1152 字节
  - 位图极性: bit=1 背景, bit=0 笔画 (渲染时需 XOR 0xFF)
  - RLE: 每 3 字节 → 4 个 6-bit 游程 (黑-白-黑-白 交替)
"""
from __future__ import annotations

import struct
from typing import Optional


class Font9696:
    """FONT9696 位图字体编解码器。

    支持:
      - 读取现有 FONT9696 文件并解码字形
      - 编码 96×96 1bpp 位图为 RLE 压缩数据
      - 从字形字典构建完整 FONT9696 文件
    """

    GLYPHS_PER_SECTION = 14915       # 每个 FTYPE 区段字形数 (157×95)
    SECTIONS = 8                     # FTYPE 区段数 (0-7)
    GLYPH_BUF_SIZE = 1152            # 96×96/8 单字形位图字节数
    INDEX_SIZE = SECTIONS * GLYPHS_PER_SECTION * 4   # 477,280 字节
    CANVAS_SIZE = 96                 # 字形画布尺寸

    # word_4EC810: ASCII (0x00-0x7F) → BIG5 全角码 重映射表
    # 逆向依据: sub_44B384 L37-38 (dword_4EC1EC < 0x80 时查表重映射为 BIG5)
    # 数据来源: TKS.exe 内存 dump @ 0x004EC810, 128 项 uint16 LE
    _ASCII_TO_BIG5 = list(struct.unpack('<128H',
        b'\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1'
        b'\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1'
        b'\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1'
        b'\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1\x40\xA1'
        b'\x40\xA1\x49\xA1\xAA\xA1\xAD\xA1\x43\xA2\x4D\xA2\xAE\xA1\xAC\xA1'
        b'\x5D\xA1\x5E\xA1\xB8\xA1\xDE\xA1\x41\xA1\xDF\xA1\x45\xA1\x41\xA2'
        b'\xAF\xA2\xB0\xA2\xB1\xA2\xB2\xA2\xB3\xA2\xB4\xA2\xB5\xA2\xB6\xA2'
        b'\xB7\xA2\xB8\xA2\x4A\xA1\x46\xA1\xE0\xA1\xE2\xA1\xE1\xA1\x48\xA1'
        b'\x49\xA2\xCF\xA2\xD0\xA2\xD1\xA2\xD2\xA2\xD3\xA2\xD4\xA2\xD5\xA2'
        b'\xD6\xA2\xD7\xA2\xD8\xA2\xD9\xA2\xDA\xA2\xDB\xA2\xDC\xA2\xDD\xA2'
        b'\xDE\xA2\xDF\xA2\xE0\xA2\xE1\xA2\xE2\xA2\xE3\xA2\xE4\xA2\xE5\xA2'
        b'\xE6\xA2\xE7\xA2\xE8\xA2\x65\xA1\x42\xA2\x66\xA1\x73\xA1\xC5\xA1'
        b'\xAB\xA1\xE9\xA2\xEA\xA2\xEB\xA2\xEC\xA2\xED\xA2\xEE\xA2\xEF\xA2'
        b'\xF0\xA2\xF1\xA2\xF2\xA2\xF3\xA2\xF4\xA2\xF5\xA2\xF6\xA2\xF7\xA2'
        b'\xF8\xA2\xF9\xA2\xFA\xA2\xFB\xA2\xFC\xA2\xFD\xA2\xFE\xA2\x40\xA3'
        b'\x41\xA3\x42\xA3\x43\xA3\x61\xA1\x55\xA1\x62\xA1\xE3\xA1\xBD\xA1'
    ))

    # ── BIG5 编码 → 字形索引 (sub_44B384) ──

    @staticmethod
    def big5_to_index(char_code: int, ftype: int = 0) -> Optional[int]:
        """BIG5 字符码 → glyph 索引。

        Args:
            char_code: BIG5 双字节码 (>= 0xA1A1), 或 ASCII 码 (< 0x80)
                       ASCII 码会通过 word_4EC810 重映射表转换为 BIG5 全角码
                       (逆向依据: sub_44B384 L37-38)
            ftype: FTYPE 区段 (0-7)

        Returns:
            glyph 索引, 或 None (非法码点)
        """
        if char_code < 0x80:
            # ASCII 字符: 通过 word_4EC810 重映射为 BIG5 全角码
            if char_code >= len(Font9696._ASCII_TO_BIG5):
                return None
            char_code = Font9696._ASCII_TO_BIG5[char_code]
        high = (char_code >> 8) & 0xFF
        low = char_code & 0xFF
        if high < 0xA1:
            return None
        if 0x40 <= low <= 0x7E:
            li = low - 64
        elif 0xA1 <= low <= 0xFE:
            li = low - 98   # 0xA1 - 98 = 63
        else:
            return None
        base = li + 157 * (high - 161)
        if base < 0 or base >= Font9696.GLYPHS_PER_SECTION:
            return None
        return base + Font9696.GLYPHS_PER_SECTION * ftype

    @staticmethod
    def index_to_big5(index: int) -> tuple[int, int]:
        """glyph 索引 → (BIG5 码, FTYPE)。

        逆向 big5_to_index, 用于遍历所有有效码点。
        """
        ftype = index // Font9696.GLYPHS_PER_SECTION
        base = index % Font9696.GLYPHS_PER_SECTION
        row = base // 157
        col = base % 157
        high = row + 0xA1
        low = (col + 64) if col < 63 else (col + 98)
        return ((high << 8) | low, ftype)

    @staticmethod
    def iter_all_big5_codes() -> list[tuple[int, int]]:
        """枚举所有有效 BIG5 码点及其索引 (单个 FTYPE 区段)。

        Returns:
            [(big5_code, index_in_section), ...] 共 14758 项 (94×157)
        """
        result = []
        for high in range(0xA1, 0xFF):   # 94 行
            for low in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):  # 63+94=157
                code = (high << 8) | low
                idx = Font9696.big5_to_index(code, 0)
                if idx is not None:
                    result.append((code, idx))
        return result

    # ── RLE 编解码 (sub_44B208) ──

    @staticmethod
    def decode_rle(data: bytes) -> bytes:
        """RLE 解码 → 1bpp 位图 1152 字节。

        3 字节组编码 4 个交替黑白游程, 每游程 6 bit (0-63)。
        游程序列固定为: 黑-白-黑-白 交替。
        位图极性: bit=1 为背景, bit=0 为笔画 (与文件格式一致)。

        初始化为全背景 (0xFF): RLE 数据未覆盖的尾部像素视为背景而非笔画,
        避免字形底部出现虚假横线 (法/拳/掌/功 等字 RLE 总游程 < 96×96)。
        """
        bitmap = bytearray(b'\xFF' * Font9696.GLYPH_BUF_SIZE)
        byte_pos, bit_pos = 0, 7
        i, n = 0, len(data)
        while i + 2 < n:
            b0, b1, b2 = data[i], data[i + 1], data[i + 2]
            i += 3
            runs = [
                b0 & 0x3F,
                (b0 >> 6) | ((b1 & 0xF) << 2),
                (b1 >> 4) | ((b2 & 0x3) << 4),
                b2 >> 2,
            ]
            for ri, rlen in enumerate(runs):
                if rlen == 0:
                    continue
                is_black = (ri == 0 or ri == 2)   # 黑=背景(bit=1) / 白=笔画(bit=0)
                for _ in range(rlen):
                    if byte_pos >= Font9696.GLYPH_BUF_SIZE:
                        return bytes(bitmap)
                    if is_black:
                        bitmap[byte_pos] |= (1 << bit_pos)
                    else:
                        bitmap[byte_pos] &= ~(1 << bit_pos)
                    bit_pos -= 1
                    if bit_pos < 0:
                        bit_pos = 7
                        byte_pos += 1
                    if byte_pos >= Font9696.GLYPH_BUF_SIZE:
                        return bytes(bitmap)
        return bytes(bitmap)

    @staticmethod
    def encode_rle(bitmap: bytes) -> bytes:
        """RLE 编码: 1bpp 位图 1152 字节 → 压缩数据。

        逆向 decode_rle。
        输入位图极性: bit=1 为黑(笔画), bit=0 为白(背景)。

        编码策略:
          - 扫描位图按 bit 序 (MSB 优先), 提取交替黑白游程
          - 每 4 个游程打包为 3 字节 (24 bit = 4×6 bit)
          - 若游程 > 63, 拆分为多个游程 (中间插入长度 0 的反色游程)

        numpy 加速版: 比纯 Python 快约 10 倍。
        """
        try:
            import numpy as np

            # 1. 展开为 bit 数组 (MSB first, bool)
            arr = np.frombuffer(bitmap, dtype=np.uint8)
            bits = np.unpackbits(arr)   # shape: (9216,), dtype: uint8

            # 2. 提取交替游程 (第一游程为黑色 bit=1)
            # 找到值变化的位置
            if len(bits) == 0:
                return b''

            # 第一个 bit 决定起始颜色
            # 如果 bits[0] == 0 (白色), 先插入一个长度为 0 的黑色游程
            runs_lengths = []   # 仅存长度, 颜色隐含交替 (黑/白/黑/白...)
            runs_colors = []   # True=黑, False=白

            # 用 numpy diff 找变化点
            diff = np.diff(bits)
            change_indices = np.nonzero(diff)[0]   # 变化点的索引 (最后一个相同值的索引)

            # 构建游程
            prev = 0
            current_is_black = True   # 第一游程必须是黑色

            # 如果位图以白色开头, 先插入 0 长度黑色游程
            if bits[0] == 0:
                runs_lengths.append(0)
                runs_colors.append(True)
                current_is_black = False

            for idx in change_indices:
                run_len = int(idx + 1 - prev)
                runs_lengths.append(run_len)
                runs_colors.append(current_is_black)
                current_is_black = not current_is_black
                prev = idx + 1

            # 最后一个游程
            run_len = int(len(bits) - prev)
            runs_lengths.append(run_len)
            runs_colors.append(current_is_black)

            # 3. 拆分 > 63 的游程
            split_lengths = []
            for length, is_black in zip(runs_lengths, runs_colors):
                if length <= 63:
                    split_lengths.append(length)
                else:
                    remaining = length
                    while remaining > 63:
                        split_lengths.append(63)
                        split_lengths.append(0)   # 0 长度反色游程
                        remaining -= 63
                    split_lengths.append(remaining)

            # 4. 补齐到 4 的倍数
            while len(split_lengths) % 4 != 0:
                split_lengths.append(0)

            # 5. 每 4 个游程打包为 3 字节 (numpy 批量处理)
            arr_runs = np.array(split_lengths, dtype=np.uint32)
            # reshape 为 (N/4, 4)
            arr_runs = arr_runs.reshape(-1, 4) & 0x3F

            # r0 | r1<<6 | r2<<12 | r3<<18
            packed = (arr_runs[:, 0] |
                      arr_runs[:, 1] << 6 |
                      arr_runs[:, 2] << 12 |
                      arr_runs[:, 3] << 18).astype(np.uint32)

            # 转为 3 字节 LE
            # packed shape: (N,), 每个 uint32 取低 24 位 → 3 字节
            out = bytearray()
            packed_bytes = packed.astype(np.uint32).tobytes()
            # 每个 uint32 取前 3 字节 (LE)
            for i in range(len(packed)):
                out.append(packed_bytes[i * 4])
                out.append(packed_bytes[i * 4 + 1])
                out.append(packed_bytes[i * 4 + 2])

            return bytes(out)

        except ImportError:
            # numpy 不可用时回退到纯 Python
            # 把位图展开为 bit 序列 (0/1 整数)
            bits = []
            for byte in bitmap:
                for shift in range(7, -1, -1):
                    bits.append((byte >> shift) & 1)

            # 提取交替游程: 第一游程为黑色 (bit=1)
            runs = []
            i = 0
            n = len(bits)
            current_is_black = True
            while i < n:
                target = 1 if current_is_black else 0
                run_len = 0
                while i < n and bits[i] == target:
                    run_len += 1
                    i += 1
                runs.append((current_is_black, run_len))
                current_is_black = not current_is_black

            while len(runs) % 4 != 0:
                runs.append((current_is_black, 0))
                current_is_black = not current_is_black

            split_runs = []
            for is_black, length in runs:
                if length <= 63:
                    split_runs.append((is_black, length))
                else:
                    remaining = length
                    while remaining > 63:
                        split_runs.append((is_black, 63))
                        split_runs.append((not is_black, 0))
                        remaining -= 63
                    split_runs.append((is_black, remaining))

            while len(split_runs) % 4 != 0:
                split_runs.append((current_is_black, 0))
                current_is_black = not current_is_black

            out = bytearray()
            for i in range(0, len(split_runs), 4):
                r0 = split_runs[i][1] & 0x3F
                r1 = split_runs[i + 1][1] & 0x3F
                r2 = split_runs[i + 2][1] & 0x3F
                r3 = split_runs[i + 3][1] & 0x3F
                v = r0 | (r1 << 6) | (r2 << 12) | (r3 << 18)
                out.append(v & 0xFF)
                out.append((v >> 8) & 0xFF)
                out.append((v >> 16) & 0xFF)

            return bytes(out)

    # ── 文件读写 ──

    @staticmethod
    def load_index(path: str) -> list[int]:
        """加载 FONT9696 文件的索引表 (119,320 项 uint32 LE)。"""
        with open(path, 'rb') as f:
            idx_bytes = f.read(Font9696.INDEX_SIZE)
        if len(idx_bytes) < Font9696.INDEX_SIZE:
            # 文件不完整, 用 0 补齐
            idx_bytes = idx_bytes + b'\x00' * (Font9696.INDEX_SIZE - len(idx_bytes))
        return list(struct.unpack_from('<%dI' % (Font9696.SECTIONS * Font9696.GLYPHS_PER_SECTION),
                                       idx_bytes, 0))

    @staticmethod
    def load_glyph_data(path: str, index: int, full_index: list[int]) -> bytes:
        """读取指定索引处的 RLE 字形数据。

        Args:
            path: FONT9696 文件路径
            index: 字形索引 (0 ~ 119319)
            full_index: 完整索引表 (load_index 返回值)
        Returns:
            RLE 压缩字节数据
        """
        if index + 1 >= len(full_index):
            return b''
        off = full_index[index]
        next_off = full_index[index + 1]
        if off >= next_off:
            return b''
        with open(path, 'rb') as f:
            f.seek(off)
            return f.read(next_off - off)

    @staticmethod
    def build_font9696(glyphs: dict[int, bytes]) -> bytes:
        """从字形字典构建完整 FONT9696 文件字节流。

        Args:
            glyphs: {glyph_index: rle_data} 字典
                    glyph_index ∈ [0, 8*14915-1]
                    rle_data 为 RLE 压缩字节 (encode_rle 返回值)

        Returns:
            完整 FONT9696 文件字节流 (索引表 + 字形数据区)
        """
        total_glyphs = Font9696.SECTIONS * Font9696.GLYPHS_PER_SECTION

        # 计算每个字形的偏移 (按索引顺序连续存放)
        offsets = [0] * (total_glyphs + 1)
        current_offset = Font9696.INDEX_SIZE  # 字形数据区起始
        for i in range(total_glyphs):
            offsets[i] = current_offset
            data = glyphs.get(i, b'')
            current_offset += len(data)
        offsets[total_glyphs] = current_offset  # 结束标记

        # 构建索引表 (uint32 LE, 仅前 total_glyphs 项)
        idx_bytes = struct.pack('<%dI' % total_glyphs, *offsets[:total_glyphs])

        # 构建字形数据区 (按索引顺序)
        data_bytes = bytearray()
        for i in range(total_glyphs):
            data = glyphs.get(i, b'')
            data_bytes.extend(data)

        return idx_bytes + bytes(data_bytes)

    # ── 字形位图工具 ──

    @staticmethod
    def invert_polarity(bitmap: bytes) -> bytes:
        """反转位图极性。

        FONT9696 文件中 bit=1 为背景, bit=0 为笔画;
        解码后通常需要 XOR 0xFF 反转为 bit=1 为笔画。
        """
        return bytes(b ^ 0xFF for b in bitmap)

    @staticmethod
    def render_glyph_from_bitmap(stroke_bitmap: bytes, color: tuple[int, int, int] = (255, 255, 255)) -> Optional[bytes]:
        """从笔画位图 (bit=1=笔画) 渲染 RGBA 像素 (96×96)。

        Args:
            stroke_bitmap: 1152 字节 1bpp 位图, bit=1 表示笔画
            color: (R, G, B) 笔画颜色

        Returns:
            96×96×4 字节 RGBA 数据, 或 None (输入长度不正确)
        """
        if len(stroke_bitmap) != Font9696.GLYPH_BUF_SIZE:
            return None
        r, g, b = color
        out = bytearray(Font9696.CANVAS_SIZE * Font9696.CANVAS_SIZE * 4)
        for y in range(Font9696.CANVAS_SIZE):
            row_off = y * 12
            for x in range(Font9696.CANVAS_SIZE):
                bi = row_off + (x // 8)
                if stroke_bitmap[bi] & (1 << (7 - (x % 8))):
                    pos = (y * Font9696.CANVAS_SIZE + x) * 4
                    out[pos] = r
                    out[pos + 1] = g
                    out[pos + 2] = b
                    out[pos + 3] = 255
        return bytes(out)
