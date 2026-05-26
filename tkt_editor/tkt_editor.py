#!/usr/bin/env python3
"""
TKT.dat 文本数据库编辑器 v1.0
=============================
加载/编辑/保存/新增 TKT.dat 文本数据库条目。

逆向依据:
  sub_401E88 (0x401e88): TKT.dat 加载/构建主函数
    - LOAD 模式 (lines 373-401): fread header(8B), malloc, fread data, XOR 0xFF 解密
    - BUILD 模式 (lines 85-371): 两遍扫描 TKTalk.txt, 编译标签, XOR 加密, 写 TKT.dat
    - 行 320: `*(_BYTE *)(dword_8242F8 + v31++) = 30;` → 0x1E 行分隔符 (仅第2行起)
    - 行 336: `*(_BYTE *)(dword_8242F8 + v31++) = 0;`  → 0x00 条目终止符
    - 行 343-348 / 397-401: XOR 加密/解密 `*v24 = ~*v24`
  sub_4067E8 (0x4067e8): 通过 ID 线性扫描查询文本
  sub_4019D0 (0x4019d0): `<TAG,n>` 控制标记编码器
    - v6=1 仅 TEXT 分支 (行 120): 写入 2 字节 (lo+hi)
    - 其余标签 v6=0: 写入 1 字节
  tkt_decoder.py: 权威解码器实现 (逆向工作区/)

用法:
  python tkt_editor.py [TKT.dat]
"""

import os
import re
import struct
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
from collections import OrderedDict

HAS_PIL = False
try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    pass

# ============================================================
# 常量 (全部来自反编译, 不可改)
# ============================================================
XOR_KEY = 0xFF                       # sub_401E88: `*p = ~*p` 即 XOR 0xFF
HDR_SIZE = 8                         # 未加密头部: total_size(4) + record_count(4)
ENTRY_TERMINATOR = 0x00              # sub_401E88 行 336
LINE_SEPARATOR = 0x1E                # sub_401E88 行 320 (十进制 30)

# 控制字节映射 (sub_4019D0): code -> (name, data_bytes, min_val, max_val)
# data_bytes: TEXT=2 (v6=1), 其余=1 (v6=0)
CONTROL_TAGS = {
    0x01: ("FRESET",  1, 1, 4),
    0x02: ("FCOLOR",  1, 1, 32),
    0x03: ("FCOLORD", 3, 0, 255),
    0x04: ("FSIZE",   1, 12, 48),
    0x05: ("FTYPE",   1, 1, 8),
    0x14: ("TEXT",    2, 1, 32767),
    0x15: ("VARNUM",  1, 1, 255),
    0x16: ("VARTXT",  1, 1, 255),
    0x1D: ("NAME",    1, 1, 2),
}

# 反向映射: tag_name -> (code, data_bytes, min_val, max_val)
TAG_NAME_MAP = {v[0]: (code, v[1], v[2], v[3]) for code, v in CONTROL_TAGS.items()}

# 标签编码正则: <TAG_NAME,number> 或 <FCOLORD,r,g,b>
TAG_PATTERN = re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_MONO = ('Consolas', 10)

# ============================================================
# 游戏渲染参数 (sub_44E49C 文本绘制调度)
# ============================================================

# FCOLOR 1-32 调色板 (dword_A2C524[32], RGB565 LE)
# 来源: sub_44E49C case 2, 内存 A2C528~A2C5A4
_GAME_PALETTE_565 = [
    0x0000,  # index 0 (unused)
    0x0000, 0x8410, 0x8000, 0x8400, 0x0400, 0x0410, 0x0010, 0x8010,
    0x8200, 0x8008, 0x4400, 0x0408, 0x4010, 0x0210, 0x0000, 0x0000,
    0xF79B, 0xC618, 0xF800, 0xFFE0, 0x07E0, 0x07FF, 0x001F, 0xF81F,
    0xFC08, 0xFA10, 0x87E8, 0x47F0, 0x821F, 0x441F, 0x31EA, 0xFFFF,
]


def _rgb565_to_hex(rgb565):
    """RGB565 → #RRGGBB (sub_451F08 case 15 色彩转换)"""
    r5 = (rgb565 >> 11) & 0x1F
    g6 = (rgb565 >> 5) & 0x3F
    b5 = rgb565 & 0x1F
    r8 = (r5 << 3) | (r5 >> 2)
    g8 = (g6 << 2) | (g6 >> 4)
    b8 = (b5 << 3) | (b5 >> 2)
    return f'#{r8:02X}{g8:02X}{b8:02X}'


GAME_COLORS = {i: _rgb565_to_hex(_GAME_PALETTE_565[i]) for i in range(1, 33)}

# FSIZE 有效值 (sub_44B04C: 12/16/24/32/48, 其他→24)
GAME_FONT_SIZES = {12, 16, 24, 32, 48}
# 默认字号 16 (依据 sub_411624 游戏主渲染器 dword_755B04: FSIZE=16)
DEFAULT_FONT_SIZE = 16

# FTYPE 1-8 近似字体 (Mu.jvg→细明体系; pface.jvg→黑体/UI体系)
# 游戏原字体来自 JVG 位图, 此处使用系统 CJK 字体近似
GAME_FONT_FAMILIES = {
    1: ('PMingLiU', 'MingLiU', 'SimSun', 'serif'),
    2: ('MingLiU', 'PMingLiU', 'SimSun', 'serif'),
    3: ('DFKai-SB', 'KaiTi', 'serif'),
    4: ('SimSun', 'NSimSun', 'MingLiU', 'serif'),
    5: ('Microsoft JhengHei', 'Microsoft YaHei', 'SimHei', 'sans-serif'),
    6: ('SimHei', 'Microsoft YaHei', 'Microsoft JhengHei', 'sans-serif'),
    7: ('FangSong', 'KaiTi', 'serif'),
    8: ('KaiTi', 'DFKai-SB', 'serif'),
}

# 默认 FTYPE=2 (依据 sub_411624 主渲染器 offset 0=1 即 FTYPE raw=2, ftype index 1=MingLiU)
DEFAULT_FTYPE = 2
DEFAULT_FCOLOR = 32    # 白色 (0xFFFF); 游戏初始 FCOLOR=0(黑色) 但暗色背景上需要白色
PREVIEW_BG = '#313c52'  # 模拟游戏对话框暗色背景

# FTYPE 反向映射: 字体族首名称 → 0-based ftype
FTYPE_BY_FAMILY_NAME = {v[0]: k - 1 for k, v in GAME_FONT_FAMILIES.items()}

# ASCII → BIG5 重映射表 (word_4EC810, 提取自 TKS.exe 运行时内存 dump)
# 依据 sub_44B384: ASCII 字符 (< 0x80) 在 FONT9696 索引前先通过此表重映射
# 控制字符 (0x00-0x1F) 映射到 0xA140 (全宽空格)
WORD_4EC810 = {
    0x20: 0xA140, 0x21: 0xA149, 0x22: 0xA1AA, 0x23: 0xA1AD,
    0x24: 0xA243, 0x25: 0xA24D, 0x26: 0xA1AE, 0x27: 0xA1AC,
    0x28: 0xA15D, 0x29: 0xA15E, 0x2A: 0xA1B8, 0x2B: 0xA1DE,
    0x2C: 0xA141, 0x2D: 0xA1DF, 0x2E: 0xA145, 0x2F: 0xA241,
    0x30: 0xA2AF, 0x31: 0xA2B0, 0x32: 0xA2B1, 0x33: 0xA2B2,
    0x34: 0xA2B3, 0x35: 0xA2B4, 0x36: 0xA2B5, 0x37: 0xA2B6,
    0x38: 0xA2B7, 0x39: 0xA2B8, 0x3A: 0xA14A, 0x3B: 0xA146,
    0x3C: 0xA1E0, 0x3D: 0xA1E2, 0x3E: 0xA1E1, 0x3F: 0xA148,
    0x40: 0xA249, 0x41: 0xA2CF, 0x42: 0xA2D0, 0x43: 0xA2D1,
    0x44: 0xA2D2, 0x45: 0xA2D3, 0x46: 0xA2D4, 0x47: 0xA2D5,
    0x48: 0xA2D6, 0x49: 0xA2D7, 0x4A: 0xA2D8, 0x4B: 0xA2D9,
    0x4C: 0xA2DA, 0x4D: 0xA2DB, 0x4E: 0xA2DC, 0x4F: 0xA2DD,
    0x50: 0xA2DE, 0x51: 0xA2DF, 0x52: 0xA2E0, 0x53: 0xA2E1,
    0x54: 0xA2E2, 0x55: 0xA2E3, 0x56: 0xA2E4, 0x57: 0xA2E5,
    0x58: 0xA2E6, 0x59: 0xA2E7, 0x5A: 0xA2E8, 0x5B: 0xA165,
    0x5C: 0xA242, 0x5D: 0xA166, 0x5E: 0xA173, 0x5F: 0xA1C5,
    0x60: 0xA1AB, 0x61: 0xA2E9, 0x62: 0xA2EA, 0x63: 0xA2EB,
    0x64: 0xA2EC, 0x65: 0xA2ED, 0x66: 0xA2EE, 0x67: 0xA2EF,
    0x68: 0xA2F0, 0x69: 0xA2F1, 0x6A: 0xA2F2, 0x6B: 0xA2F3,
    0x6C: 0xA2F4, 0x6D: 0xA2F5, 0x6E: 0xA2F6, 0x6F: 0xA2F7,
    0x70: 0xA2F8, 0x71: 0xA2F9, 0x72: 0xA2FA, 0x73: 0xA2FB,
    0x74: 0xA2FC, 0x75: 0xA2FD, 0x76: 0xA2FE, 0x77: 0xA340,
    0x78: 0xA341, 0x79: 0xA342, 0x7A: 0xA343, 0x7B: 0xA161,
    0x7C: 0xA155, 0x7D: 0xA162, 0x7E: 0xA1E3, 0x7F: 0xA1BD,
}


# ============================================================
# GB2312 ↔ Big5 转换 (依据 sub_45BB64/sub_45BCE4, 使用 g2b.dat)
# ============================================================

# 全局转换表
_G2B_TABLE = None      # GB2312 → Big5 (原始表)
_B2G_TABLE = None      # Big5 → GB2312 (反向表)


def load_g2b_dat(g2b_path):
    """加载 g2b.dat 并构建双向转换表。
    依据 sub_45BB64: 文件大小 0x20000 (131072 字节)。
    原始表: GB2312 码位 → Big5 码位
    反向表: Big5 码位 → GB2312 码位
    """
    global _G2B_TABLE, _B2G_TABLE
    with open(g2b_path, 'rb') as f:
        data = f.read()
    if len(data) != 0x20000:
        raise ValueError(f"g2b.dat 大小错误: 期望 131072 字节, 实际 {len(data)}")
    _G2B_TABLE = data

    # 构建反向表 (Big5 → GB2312)
    _B2G_TABLE = {}
    for gb_code in range(0x10000):
        idx = gb_code * 2
        if idx + 1 < len(data):
            big5_lo = data[idx]
            big5_hi = data[idx + 1]
            if big5_lo or big5_hi:  # 非零表示有效映射
                big5_code = (big5_lo << 8) | big5_hi
                _B2G_TABLE[big5_code] = gb_code
    return data


def big5_to_gb(text):
    """将 Big5 编码文本转换为 GB2312 编码文本。
    使用 g2b.dat 的反向映射表。
    """
    if _B2G_TABLE is None:
        return text  # 未加载转换表，原样返回

    result = []
    for ch in text:
        try:
            big5_bytes = ch.encode('big5')
            if len(big5_bytes) == 2:
                big5_code = (big5_bytes[0] << 8) | big5_bytes[1]
                if big5_code in _B2G_TABLE:
                    gb_code = _B2G_TABLE[big5_code]
                    gb_bytes = bytes([(gb_code >> 8) & 0xFF, gb_code & 0xFF])
                    try:
                        result.append(gb_bytes.decode('gb2312'))
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        result.append(gb_bytes.decode('gbk', errors='replace'))
                else:
                    result.append(ch)  # 无映射，保留原字符
            else:
                result.append(ch)  # 单字节，保留
        except (UnicodeEncodeError, UnicodeDecodeError):
            result.append(ch)  # 编码失败，保留原字符
    return ''.join(result)


# ============================================================
# TKT 文件 I/O (依据 sub_401E88)
# ============================================================

def load_tkt(tkt_path):
    """加载 TKT.dat, 返回 entries 列表 (OrderedDict)。
    依据 sub_401E88 LOAD 模式 (lines 373-401) + tkt_decoder.py。
    """
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    if len(raw) < HDR_SIZE:
        raise ValueError(f"TKT.dat 头部不足 8 字节: 实际 {len(raw)}")

    total_size = struct.unpack_from('<I', raw, 0)[0]
    record_count = struct.unpack_from('<I', raw, 4)[0]

    if len(raw) < HDR_SIZE + total_size:
        raise ValueError(f"TKT.dat 体积不足: 声明 {total_size}, 实际 {len(raw) - HDR_SIZE}")

    # XOR 0xFF 解密 (sub_401E88 行 397-401: `*n = ~*n`)
    encrypted = raw[HDR_SIZE:HDR_SIZE + total_size]
    decrypted = bytes(b ^ XOR_KEY for b in encrypted)

    # 切分三表 (sub_401E88 行 385-386: dword_8242F4 = base+4*cnt, dword_8242F8 = base+8*cnt)
    id_table_size = 4 * record_count
    offset_table_size = 4 * record_count
    text_base = id_table_size + offset_table_size

    entries = []
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', decrypted, i * 4)[0]          # int32 (sub_4067E8 *i 比较)
        text_offset = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0]  # uint32

        # 提取条目字节 (tkt_decoder.py slice_entry_bytes: 扫描 0x00 终止)
        abs_off = text_base + text_offset
        if abs_off >= len(decrypted):
            blob = b''
        else:
            end = abs_off
            while end < len(decrypted) and decrypted[end] != ENTRY_TERMINATOR:
                end += 1
            blob = decrypted[abs_off:end]

        # 按 0x1E 拆行 (sub_401E88 行 320)
        raw_lines = blob.split(bytes([LINE_SEPARATOR]))
        # 解码每行: Big5 解码, 控制字节保留为 <TAG,n> 标记
        decoded_lines = [decode_line(ln) for ln in raw_lines]
        text = '\n'.join(decoded_lines)

        entries.append(OrderedDict([
            ('slot', i),
            ('id', entry_id),
            ('text', text),
        ]))
    return entries


def decode_line(line_bytes):
    """把单行字节流解码为 UTF 文本, 控制字节转为 <TAG,n> 标记。
    依据 tkt_decoder.py decode_inline_tags()。
    """
    out = []
    buf = bytearray()

    def flush():
        if buf:
            try:
                out.append(buf.decode('big5', errors='replace'))
            except Exception:
                out.append(buf.decode('gbk', errors='replace'))
            buf.clear()

    i = 0
    n = len(line_bytes)
    while i < n:
        b = line_bytes[i]
        if b in CONTROL_TAGS:
            tag_name, data_len, _, _ = CONTROL_TAGS[b]
            if i + data_len < n:
                flush()
                if data_len == 1:
                    val = line_bytes[i + 1]
                    out.append(f'<{tag_name},{val}>')
                elif data_len == 2:
                    val = line_bytes[i + 1] | (line_bytes[i + 2] << 8)
                    out.append(f'<{tag_name},{val}>')
                else:
                    # data_len == 3 (FCOLORD: r,g,b)
                    r = line_bytes[i + 1]
                    g = line_bytes[i + 2]
                    b_val = line_bytes[i + 3]
                    out.append(f'<{tag_name},{r},{g},{b_val}>')
                i += 1 + data_len
                continue
            else:
                flush()
                out.append(f'<RAW,0x{b:02X}>')
                i += 1
                continue
        if b < 0x20 and b != LINE_SEPARATOR:
            flush()
            out.append(f'<RAW,0x{b:02X}>')
            i += 1
            continue
        # Big5 双字节 (sub_4019D0 行 45-51: `*a1 > 0x7F`)
        if b >= 0x80 and i + 1 < n:
            buf.append(b)
            buf.append(line_bytes[i + 1])
            i += 2
        else:
            buf.append(b)
            i += 1
    flush()
    return ''.join(out)


def encode_line(text):
    """把一行 UTF 文本编码为二进制字节流 (Big5 + 控制字节)。
    依据 sub_4019D0 编码逻辑。
    """
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        # 尝试匹配 <TAG,n> 或 <FCOLORD,r,g,b> 标记
        m = TAG_PATTERN.match(text, i)
        if m:
            tag_name = m.group(1)
            val_str = m.group(2)
            if tag_name in TAG_NAME_MAP:
                code, data_len, min_val, max_val = TAG_NAME_MAP[tag_name]
                if data_len == 3:
                    # FCOLORD: r,g,b
                    parts = val_str.split(',')
                    if len(parts) == 3:
                        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                            out.append(code)
                            out.append(r)
                            out.append(g)
                            out.append(b)
                            i = m.end()
                            continue
                else:
                    val = int(val_str)
                    if min_val <= val <= max_val:
                        out.append(code)
                        out.append(val & 0xFF)
                        if data_len == 2:
                            out.append((val >> 8) & 0xFF)
                        i = m.end()
                        continue
            # 无效标签, 原样输出
            for ch in text[i:m.end()]:
                out.extend(ch.encode('big5', errors='replace'))
            i = m.end()
            continue
        # 尝试匹配 <RAW,0xNN> 标记
        if text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                out.append(int(rm.group(1), 16))
                i += rm.end()
                continue
        ch = text[i]
        # Big5 双字节字符直接编码
        try:
            encoded = ch.encode('big5')
        except (UnicodeEncodeError, UnicodeDecodeError):
            encoded = ch.encode('gbk', errors='replace')
        out.extend(encoded)
        i += 1
    return bytes(out)


# ============================================================
# 预览区: 解析文本分段 (依据 sub_44E49C 渲染调度)
# ============================================================

def parse_styled_segments(text):
    """将含 <TAG,n> 的 TKT 文本解析为 [(text, {style}), ...] 分段列表。
    依据 sub_44E49C 控制码分发逻辑:
      FCOLOR → 查调色板 dword_A2C524
      FSIZE  → 字号 12/16/24/32/48
      FTYPE  → 0-based 字体索引
      FRESET → 部分/全部恢复
    """
    segments = []
    current = {
        'fg': GAME_COLORS[DEFAULT_FCOLOR],
        'size': DEFAULT_FONT_SIZE,
        'family': GAME_FONT_FAMILIES[DEFAULT_FTYPE],
    }
    # FRESET,2 恢复为"上一个颜色" (sub_44E49C a1+16)
    prev_color = current['fg']
    prev_family = current['family']
    buf = []
    i = 0
    n = len(text)

    def flush():
        if buf:
            segments.append((''.join(buf), dict(current)))
            buf.clear()

    while i < n:
        m = TAG_PATTERN.match(text, i)
        if m:
            flush()
            tag_name = m.group(1)
            val_str = m.group(2)
            if tag_name == 'FCOLOR':
                val = int(val_str)
                if 1 <= val <= 32:
                    prev_color = current['fg']
                    current['fg'] = GAME_COLORS[val]
            elif tag_name == 'FCOLORD':
                parts = val_str.split(',')
                if len(parts) == 3:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    prev_color = current['fg']
                    current['fg'] = f'#{r:02X}{g:02X}{b:02X}'
            elif tag_name == 'FSIZE':
                val = int(val_str)
                if val in GAME_FONT_SIZES:
                    current['size'] = val
            elif tag_name == 'FTYPE':
                val = int(val_str)
                if 1 <= val <= 8:
                    prev_family = current['family']
                    current['family'] = GAME_FONT_FAMILIES[val]
            elif tag_name == 'FRESET':
                val = int(val_str)
                if val == 1:  # 全部恢复
                    current['fg'] = GAME_COLORS[DEFAULT_FCOLOR]
                    current['size'] = DEFAULT_FONT_SIZE
                    current['family'] = GAME_FONT_FAMILIES[DEFAULT_FTYPE]
                elif val == 2:  # 恢复颜色
                    current['fg'] = prev_color
                elif val == 3:  # 重新初始化 (同全部恢复)
                    current['fg'] = GAME_COLORS[DEFAULT_FCOLOR]
                    current['size'] = DEFAULT_FONT_SIZE
                    current['family'] = GAME_FONT_FAMILIES[DEFAULT_FTYPE]
                elif val == 4:  # 恢复字体类型
                    current['family'] = prev_family
            elif tag_name == 'TEXT':
                buf.append(f'[文本:{val_str}]')
            elif tag_name == 'VARNUM':
                buf.append(f'[变量:{val_str}]')
            elif tag_name == 'VARTXT':
                buf.append(f'[文本变量:{val_str}]')
            elif tag_name == 'NAME':
                buf.append('[姓]' if val_str == '1' else '[名]')
            else:
                buf.append(text[m.start():m.end()])
            i = m.end()
        # <RAW,0xNN> 原样输出
        elif text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                flush()
                buf.append(f'[RAW:{rm.group(1)}]')
                i += rm.end()
                continue
            buf.append(text[i])
            i += 1
        else:
            buf.append(text[i])
            i += 1
    flush()
    return segments


# ============================================================
# FONT9696 位图字体解码器 (sub_44ADB0/sub_44B384/sub_44B208)
# ============================================================

class Font9696:
    """FONT9696 自定义位图字体解码器。
    格式: 8个FTYPE区段 × 14,915字形 × uint32偏移索引 + RLE压缩位图
    字形: 96×96 最大, 1bpp, 3字节组RLE (sub_44B208)
    索引: BIG5码 → 行列计算 (sub_44B384)
    """
    GLYPHS_PER_SECTION = 14915
    GLYPH_BUF_SIZE = 1152  # 96×96/8

    def __init__(self, path):
        self._f = open(path, 'rb')
        # 加载全部索引表: 8 × 14,915 = 119,320 个 uint32
        idx_bytes = self._f.read(8 * self.GLYPHS_PER_SECTION * 4)
        self._index = list(struct.unpack_from(
            '<%dI' % (8 * self.GLYPHS_PER_SECTION), idx_bytes, 0))
        self._cache = {}  # (char_code, ftype, target_h, color) → (PIL.Image, advance)

    def close(self):
        if self._f:
            self._f.close()
            self._f = None

    def _char_index(self, char_code, ftype=0):
        """BIG5字符码 → glyph索引。
        high ∈ [0xA1, 0xFF], low ∈ [0x40, 0x7E] ∪ [0xA1, 0xFE]
        """
        if char_code < 0x80:
            return None
        high = (char_code >> 8) & 0xFF
        low = char_code & 0xFF
        if high < 0xA1:
            return None
        if 0x40 <= low <= 0x7E:
            li = low - 64
        elif 0xA1 <= low <= 0xFE:
            li = low - 98
        else:
            return None
        base = li + 157 * (high - 161)
        if base < 0 or base >= self.GLYPHS_PER_SECTION:
            return None
        return base + self.GLYPHS_PER_SECTION * ftype

    def _glyph_raw(self, char_code, ftype=0):
        """获取RLE压缩字形数据"""
        idx = self._char_index(char_code, ftype)
        if idx is None or idx + 1 >= len(self._index):
            return b''
        off = self._index[idx]
        next_off = self._index[idx + 1]
        if off >= next_off:
            return b''
        self._f.seek(off)
        return self._f.read(next_off - off)

    def _decode_rle(self, data):
        """RLE解码 → 1bpp位图 1152字节 (sub_44B208)
        3字节组编码4个交替黑白游程, 每游程6bit (0-63)
        """
        bitmap = bytearray(self.GLYPH_BUF_SIZE)
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
                is_black = (ri == 0 or ri == 2)
                for _ in range(rlen):
                    if byte_pos >= self.GLYPH_BUF_SIZE:
                        return bytes(bitmap)
                    if is_black:
                        bitmap[byte_pos] |= (1 << bit_pos)
                    bit_pos -= 1
                    if bit_pos < 0:
                        bit_pos = 7
                        byte_pos += 1
                    if byte_pos >= self.GLYPH_BUF_SIZE:
                        return bytes(bitmap)
        return bytes(bitmap)

    def glyph_image(self, char_code, ftype=0, target_height=24, color='#FFFFFF'):
        """获取彩色字形PIL图像 + 水平步进宽度。
        结果缓存于 (char_code, ftype, target_height, color) 键。
        """
        cache_key = (char_code, ftype, target_height, color)
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._glyph_raw(char_code, ftype)
        if not data:
            # 无字形，返回半角空格
            w = target_height // 2
            img = Image.new('RGBA', (max(w, 1), target_height), (0, 0, 0, 0))
            self._cache[cache_key] = (img, w)
            return (img, w)

        raw = self._decode_rle(data)

        # FONT9696 位图极性: bit=1 为背景, bit=0 为笔画
        # 反转后 bit=1 为笔画 (前景), bit=0 为背景 (透明)
        raw = bytes(b ^ 0xFF for b in raw)

        # 找包围盒
        min_x, min_y, max_x, max_y = 96, 96, 0, 0
        for y in range(96):
            row_off = y * 12
            for x in range(96):
                bi = row_off + (x // 8)
                if raw[bi] & (1 << (7 - (x % 8))):
                    if x < min_x: min_x = x
                    if y < min_y: min_y = y
                    if x > max_x: max_x = x
                    if y > max_y: max_y = y

        if min_x > max_x:
            w = target_height // 2
            img = Image.new('RGBA', (max(w, 1), target_height), (0, 0, 0, 0))
            self._cache[cache_key] = (img, w)
            return (img, w)

        gw = max_x - min_x + 1
        gh = max_y - min_y + 1

        # 提取字形到bytes (PIL frombytes 用)
        glyph_bytes = bytearray(gw * gh)
        for y in range(min_y, max_y + 1):
            row_off = y * 12
            for x in range(min_x, max_x + 1):
                bi = row_off + (x // 8)
                if raw[bi] & (1 << (7 - (x % 8))):
                    glyph_bytes[(y - min_y) * gw + (x - min_x)] = 255

        glyph_img = Image.frombytes('L', (gw, gh), bytes(glyph_bytes))

        # 按比例从 96×96 字格缩放 (保持字形在字格中的相对大小)
        # 原逻辑: scale = target_height / gh → 所有字形填满高度, 标点会过大
        # 新逻辑: scale = target_height / 96 → 字形保持在字格中的原始比例
        scale = target_height / 96.0
        new_w = max(int(gw * scale), 1)
        new_h = max(int(gh * scale), 1)
        glyph_img = glyph_img.resize((new_w, new_h), Image.LANCZOS)

        # 依据 sub_44E49C: CJK 全宽字符 advance = char_width = 字号
        # 字形居中在全宽画布 (target_height × target_height) 中
        # 字形已按 96×96 字格比例缩放, 保持游戏原始视觉比例
        advance = target_height
        canvas_w = target_height
        canvas_h = target_height
        centered = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        x_offset = (canvas_w - new_w) // 2
        y_offset = (canvas_h - new_h) // 2
        centered.paste(glyph_img, (x_offset, y_offset), glyph_img)

        # 着色
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        colored = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        alpha = centered.split()[3]
        colored.paste(centered, (0, 0), alpha)
        # 使用 putalpha 方式着色: 先建立纯色层, 用 alpha 通道合成
        color_layer = Image.new('RGBA', (canvas_w, canvas_h), (r, g, b, 255))
        result = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        result = Image.composite(color_layer, result, alpha)

        self._cache[cache_key] = (result, advance)
        return (result, advance)


def _hex_to_rgb(hex_color):
    """#RRGGBB → (R, G, B)"""
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def _unicode_to_big5_code(ch):
    """Unicode 字符 → BIG5 编码码点。
    返回 (big5_code, is_cjk):
      big5_code: 双字节 BIG5 码 (>= 0x8000) 或单字节 ASCII 码 (< 0x80)
      is_cjk: 双字节 BIG5 字符为 True, ASCII 为 False
      (None, False): 无法编码
    依据 sub_44B384: FONT9696 使用 BIG5 编码索引字形。
    """
    try:
        big5_bytes = ch.encode('big5')
        if len(big5_bytes) == 2:
            return (big5_bytes[0] << 8) | big5_bytes[1], True
        elif len(big5_bytes) == 1:
            return big5_bytes[0], False
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    try:
        gbk_bytes = ch.encode('gbk')
        if len(gbk_bytes) == 2:
            return (gbk_bytes[0] << 8) | gbk_bytes[1], True
        elif len(gbk_bytes) == 1:
            return gbk_bytes[0], False
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return None, False


def _remap_ascii_for_font9696(ascii_code):
    """将 ASCII 码 (0x00-0x7F) 通过 word_4EC810 重映射为 FONT9696 BIG5 码。
    依据 sub_44B384: `if (char_code < 0x80) char_code = word_4EC810[char_code]`
    返回 BIG5 码 (>= 0xA100) 或 None (无映射表)。
    """
    return WORD_4EC810.get(ascii_code, 0xA140)  # 未知字符映射到全宽空格


# 系统字体缓存 (ASCII/无法映射字符的回退渲染)
_SYS_FONT_CACHE = {}


def _get_sys_font(size, family_tuple, prefer_traditional=False):
    """获取系统 TrueType 字体, 带缓存。
    用于 FONT9696 不包含的 ASCII/符号字符回退渲染。
    prefer_traditional: True 时优先使用繁体中文字体 (MingLiU)
    """
    if not HAS_PIL:
        return None
    key = (size, family_tuple[0] if family_tuple else None, prefer_traditional)
    if key in _SYS_FONT_CACHE:
        return _SYS_FONT_CACHE[key]

    font = None
    # 优先使用家族字体名, 回退到常见 CJK 字体
    candidates = list(family_tuple) if family_tuple else []
    if prefer_traditional:
        # 繁体优先: MingLiU > PMingLiU > 其他繁体 > 通用 CJK
        candidates.extend(['MingLiU', 'PMingLiU', 'DFKai-SB',
                           'Microsoft JhengHei', 'SimSun', 'SimHei', 'Arial'])
    else:
        # 默认: 按原游戏字体家族顺序
        candidates.extend(['Microsoft YaHei', 'SimHei', 'SimSun',
                           'MingLiU', 'PMingLiU', 'Arial'])

    for name in candidates:
        try:
            font = ImageFont.truetype(name, size)
            break
        except (OSError, IOError):
            continue

    if font is None:
        # 尝试 Windows 字体目录
        windir = os.environ.get('WINDIR', r'C:\Windows')
        fonts_dir = os.path.join(windir, 'Fonts')
        if prefer_traditional:
            font_files = ('mingliu.ttc', 'pmingliu.ttc', 'kaiu.ttf',
                          'msjh.ttc', 'simsun.ttc', 'simhei.ttf', 'arial.ttf')
        else:
            font_files = ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf',
                          'simsun.ttc', 'mingliu.ttc', 'arial.ttf')
        for fname in font_files:
            fpath = os.path.join(fonts_dir, fname)
            if os.path.exists(fpath):
                try:
                    font = ImageFont.truetype(fpath, size)
                    break
                except (OSError, IOError):
                    continue

    if font is None:
        try:
            font = ImageFont.load_default(size)
        except (TypeError, OSError):
            font = ImageFont.load_default()

    _SYS_FONT_CACHE[key] = font
    return font


def _render_fallback_char(ch, size, color, family_tuple, half_width=False,
                            prefer_traditional=False):
    """使用系统字体渲染单个字符, 作为 FONT9696 的回退。
    返回 (PIL.Image, advance_width) 元组。ASCII 和无法映射到 BIG5 的字符走此路径。
    依据 sub_44E49C: 游戏引擎对 ASCII 字符使用 word_4EC810 重映射后
    仍经 FONT9696 渲染, 但我们无此映射表, 故用系统字体近似。
    half_width: 是否半宽渲染 (sub_44E49C offset+66 模式, ASCII 用 size/2 宽度)
    prefer_traditional: True 时优先使用繁体字体 (MingLiU)
    """
    if not HAS_PIL:
        return Image.new('RGBA', (1, 1, 0, 0)), 0

    # 半宽模式: 游戏引擎用 size >> 1 作为 ASCII 字符宽度 (sub_44E49C offset+66)
    if half_width:
        adv = max(size // 2, 1)
        font_obj = _get_sys_font(size, family_tuple, prefer_traditional)
        if font_obj is None:
            img = Image.new('RGBA', (adv, size), (0, 0, 0, 0))
            return img, adv
        # 渲染到全高画布, 水平居中在半宽区域内
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        img = Image.new('RGBA', (adv, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 居中绘制: 使用偏移使字符水平居中于半宽区域
        try:
            bbox = font_obj.getbbox(ch)
            if bbox:
                x_off = -bbox[0] + max((adv - (bbox[2] - bbox[0])) // 2, 0)
                y_off = -bbox[1] + max((size - (bbox[3] - bbox[1])) // 2, 0)
            else:
                x_off = 0
                y_off = 0
        except Exception:
            x_off, y_off = 0, 0
        draw.text((x_off, y_off), ch, fill=(r, g, b, 255), font=font_obj)
        return img, adv

    font_obj = _get_sys_font(size, family_tuple, prefer_traditional)
    if font_obj is None:
        w = max(size // 2, 1)
        return Image.new('RGBA', (w, size), (0, 0, 0, 0)), w

    # 获取字符边界框
    try:
        bbox = font_obj.getbbox(ch)
    except Exception:
        w = max(size // 2, 1)
        return Image.new('RGBA', (w, size), (0, 0, 0, 0)), w

    if bbox is None:
        w = max(size // 2, 1)
        return Image.new('RGBA', (w, size), (0, 0, 0, 0)), w

    x0, y0, x1, y1 = bbox
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)

    # 渲染字符 (使用前景色)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((-x0, -y0), ch, fill=(r, g, b, 255), font=font_obj)

    return img, w


def _render_text_image(segments, font, line_spacing=4, use_traditional_font=False):
    """将 styled segments 渲染为单个 PIL RGBA Image。
    segments: [(text, {fg, size, family}), ...]
    font: Font9696 实例
    line_spacing: 行间额外像素
    use_traditional_font: True 时 CJK 字符用系统繁体字体渲染 (而非 FONT9696 简体位图)
    """
    if not segments:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))

    bg_rgb = _hex_to_rgb(PREVIEW_BG)

    # 第一遍: 收集所有字形, 计算行布局
    lines = []  # [(line_height, glyphs)]  where glyphs = [(img, advance)]
    current_line_glyphs = []
    current_line_height = 0

    for text, style in segments:
        ftype = FTYPE_BY_FAMILY_NAME.get(style['family'][0], 0)
        size = style['size']
        color = style['fg']

        for ch in text:
            if ch == '\n':
                if current_line_glyphs:
                    lines.append((current_line_height, current_line_glyphs))
                current_line_glyphs = []
                current_line_height = 0
                continue

            # Unicode → BIG5 编码转换
            # FONT9696 使用 BIG5 编码索引字形 (sub_44B384)
            # 注意: FONT9696 字体包含简体中文字形, Big5编码仅作索引方案
            big5_code, is_cjk = _unicode_to_big5_code(ch)

            if big5_code is not None and is_cjk:
                if use_traditional_font:
                    # 繁体字体模式: CJK 用系统繁体字体渲染, 全宽
                    img, adv = _render_fallback_char(ch, size, color, style['family'],
                                                      half_width=False,
                                                      prefer_traditional=True)
                else:
                    # FONT9696 渲染 (BIG5 双字节), 全宽
                    # 依据 sub_44E49C: CJK 字符使用完整 char_width (offset+28)
                    img, adv = font.glyph_image(big5_code, ftype, size, color)
            elif big5_code is not None and not is_cjk:
                # ASCII 字符: word_4EC810 重映射 → FONT9696 渲染
                # 依据 sub_44B384: char_code < 0x80 → word_4EC810[char_code] → FONT9696
                # 依据 sub_44E49C offset+66: 半宽前进 (char_width >> 1)
                # 空格不经过 FONT9696 — 游戏直接跳白不渲染字形 (sub_44E49C)
                if big5_code == 0x20 and not use_traditional_font:
                    adv = max(size // 2, 1)
                    img = Image.new('RGBA', (adv, size), (0, 0, 0, 0))
                elif use_traditional_font:
                    img, adv = _render_fallback_char(ch, size, color, style['family'],
                                                      half_width=True,
                                                      prefer_traditional=True)
                else:
                    remapped_code = _remap_ascii_for_font9696(big5_code)
                    img, _ = font.glyph_image(remapped_code, ftype, size, color)
                    adv = max(size // 2, 1)
            else:
                # 无法编码到 BIG5 的字符: 系统字体回退
                # 繁体模式下 CJK 类字符尝试全宽渲染
                if use_traditional_font and ord(ch) > 0x7F:
                    img, adv = _render_fallback_char(ch, size, color, style['family'],
                                                      half_width=False,
                                                      prefer_traditional=True)
                else:
                    img, adv = _render_fallback_char(ch, size, color, style['family'],
                                                      half_width=True,
                                                      prefer_traditional=use_traditional_font)

            current_line_glyphs.append((img, adv))
            current_line_height = max(current_line_height, size)

    if current_line_glyphs:
        lines.append((current_line_height, current_line_glyphs))

    if not lines:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))

    # 第二遍: 计算画布大小
    total_h = 0
    for lh, _glyphs in lines:
        total_h += lh + line_spacing
    total_h -= line_spacing if lines else 0

    max_w = 0
    for _lh, glyphs in lines:
        line_w = sum(adv for _img, adv in glyphs)
        max_w = max(max_w, line_w)

    canvas_w = max(max_w + 20, 1)  # 左右各留10px padding
    canvas_h = max(total_h + 20, 1)

    # 第三遍: 渲染
    canvas = Image.new('RGBA', (canvas_w, canvas_h), (*bg_rgb, 255))
    y = 10
    for lh, glyphs in lines:
        x = 10
        for img, adv in glyphs:
            # 垂直居中
            y_off = (lh - img.height) // 2
            canvas.paste(img, (x, y + y_off), img)
            x += adv
        y += lh + line_spacing

    return canvas


def save_tkt(tkt_path, entries):
    """保存 entries 到 TKT.dat。
    依据 sub_401E88 BUILD 模式 (lines 220-371):
      1. 构建 ID 表 (int32) + 偏移表 (uint32) + 文本区
      2. 文本区: 多行用 0x1E 连接 (第2行起前插), 条目末尾追加 0x00
      3. 整体 XOR 0xFF 加密
      4. 写入: header(8B) + encrypted_data
    """
    record_count = len(entries)
    # 构建文本区
    text_blob = bytearray()
    id_table = bytearray()
    offset_table = bytearray()

    for entry in entries:
        entry_id = entry['id']
        text = entry['text']
        lines = text.split('\n')
        entry_bytes = bytearray()
        for li, line in enumerate(lines):
            if li > 0:
                entry_bytes.append(LINE_SEPARATOR)  # sub_401E88 行 320: 0x1E
            entry_bytes.extend(encode_line(line))
        entry_bytes.append(ENTRY_TERMINATOR)  # sub_401E88 行 336: 0x00

        # 记录偏移 (当前 text_blob 长度)
        current_offset = len(text_blob)
        text_blob.extend(entry_bytes)

        # ID 表: int32 LE (sub_401E88 行 303: `*(_DWORD *)(dword_8242F0 + 4*v33) = v36`)
        id_table.extend(struct.pack('<i', entry_id))
        # 偏移表: uint32 LE (sub_401E88 行 304: `*(_DWORD *)(dword_8242F4 + 4*v33++) = v31`)
        offset_table.extend(struct.pack('<I', current_offset))

    # 组装数据区: ID表 + 偏移表 + 文本区 (sub_401E88 行 224-227)
    data = bytes(id_table) + bytes(offset_table) + bytes(text_blob)
    total_size = len(data)

    # XOR 0xFF 加密 (sub_401E88 行 343-348: `*v24 = ~*v24`)
    encrypted = bytes(b ^ XOR_KEY for b in data)

    # 写入文件: header(8B) + encrypted_data
    with open(tkt_path, 'wb') as f:
        f.write(struct.pack('<I', total_size))
        f.write(struct.pack('<I', record_count))
        f.write(encrypted)


# ============================================================
# GUI
# ============================================================

class TktEditor:
    def __init__(self, root, initial_path=None):
        self.root = root
        self.root.title("TKT.dat 文本数据库编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)

        self.tkt_path = None
        self.entries = []          # 当前所有条目
        self.filtered_indices = [] # 当前过滤后的索引
        self.font9696 = None       # FONT9696 字体实例
        self.font_path = None      # FONT9696 文件路径
        self._dirty = False
        self._current_idx = None   # 当前选中条目在 self.entries 中的索引

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1200) // 2
        y = (sh - 750) // 2
        self.root.geometry(f'1200x750+{x}+{y}')

        if initial_path and os.path.exists(initial_path):
            self._load_file(initial_path)

    def _build_ui(self):
        # 菜单栏
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="另存为…", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_quit)
        mb.add_cascade(label="文件", menu=fm)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新增条目", command=self._new_entry, accelerator="Ctrl+N")
        em.add_command(label="删除当前条目", command=self._delete_entry, accelerator="Delete")
        em.add_separator()
        em.add_command(label="查找…", command=self._focus_search, accelerator="Ctrl+F")
        mb.add_cascade(label="编辑", menu=em)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_entry())
        self.root.bind('<Control-f>', lambda e: self._focus_search())
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.search_var, width=20)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(tb, text="ID范围:").pack(side=tk.LEFT)
        self.filter_from = tk.StringVar()
        self.filter_to = tk.StringVar()
        ttk.Entry(tb, textvariable=self.filter_from, width=6).pack(side=tk.LEFT, padx=1)
        ttk.Label(tb, text="—").pack(side=tk.LEFT)
        ttk.Entry(tb, textvariable=self.filter_to, width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="过滤", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(tb, text="新增条目", command=self._new_entry).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # 繁简切换开关
        # FONT9696 字体文件包含简体中文字形 (Big5编码索引)，游戏实际显示简体。
        # 默认关闭: 使用 FONT9696 渲染 (= 游戏原始简体显示)
        # 开启: 使用系统繁体字体渲染 (= TKT.dat 原始繁体内容)
        self.use_traditional_font = tk.BooleanVar(value=False)
        self.chk_traditional = ttk.Checkbutton(tb, text="繁体字体", variable=self.use_traditional_font,
                                                 command=self._on_font_toggle)
        self.chk_traditional.pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # 主分栏
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧: 条目列表
        lf = ttk.Frame(paned)
        paned.add(lf, weight=2)
        cols = ('slot', 'id', 'preview')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        self.tree.heading('slot', text='#')
        self.tree.heading('id', text='ID')
        self.tree.heading('preview', text='文本预览')
        self.tree.column('slot', width=40, minwidth=30, anchor='center')
        self.tree.column('id', width=60, minwidth=40, anchor='center')
        self.tree.column('preview', width=200, minwidth=100, anchor='w')
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧: 编辑区
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)

        # 条目信息
        info_frame = ttk.Frame(rf)
        info_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        self.lbl_info = ttk.Label(info_frame, text="未选中", font=('', 11, 'bold'))
        self.lbl_info.pack(side=tk.LEFT)
        self.lbl_dirty = ttk.Label(info_frame, text="", foreground='red', font=FONT)
        self.lbl_dirty.pack(side=tk.RIGHT)

        # ID 输入
        id_frame = ttk.Frame(rf)
        id_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(id_frame, text="条目 ID:", font=FONT).pack(side=tk.LEFT)
        self.id_var = tk.StringVar()
        ttk.Entry(id_frame, textvariable=self.id_var, width=12, font=FONT).pack(side=tk.LEFT, padx=4)
        ttk.Label(id_frame, text="(int32, 可为负数)", font=FONT_S, foreground='#666').pack(side=tk.LEFT)

        # 文本编辑器
        edit_frame = ttk.LabelFrame(rf, text="文本内容 (支持多行, <TAG,n> 标记)", padding=4)
        edit_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # TAG 快捷输入工具栏
        self._build_tag_toolbar(edit_frame)
        ttk.Separator(edit_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=2, pady=(0, 2))

        ef = ttk.Frame(edit_frame)
        ef.pack(fill=tk.BOTH, expand=True)
        self.text_widget = tk.Text(ef, font=FONT_MONO, wrap=tk.NONE, undo=True,
                                   tabs=('4c',), bg='#fafafa')
        ssb_y = ttk.Scrollbar(ef, orient=tk.VERTICAL, command=self.text_widget.yview)
        ssb_x = ttk.Scrollbar(ef, orient=tk.HORIZONTAL, command=self.text_widget.xview)
        self.text_widget.configure(yscrollcommand=ssb_y.set, xscrollcommand=ssb_x.set)
        self.text_widget.grid(row=0, column=0, sticky='nsew')
        ssb_y.grid(row=0, column=1, sticky='ns')
        ssb_x.grid(row=1, column=0, sticky='ew')
        ef.rowconfigure(0, weight=1)
        ef.columnconfigure(0, weight=1)
        self.text_widget.bind('<KeyRelease>', self._on_text_modified)

        # 预览区 — FONT9696 PIL 渲染图像 (优先) / 纯文本回退
        preview_frame = ttk.LabelFrame(rf, text="游戏预览", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        pf_inner = ttk.Frame(preview_frame)
        pf_inner.pack(fill=tk.BOTH, expand=True)
        self.preview_text = tk.Text(pf_inner, bg=PREVIEW_BG, fg=GAME_COLORS[DEFAULT_FCOLOR],
                                    font=(GAME_FONT_FAMILIES[DEFAULT_FTYPE][0], DEFAULT_FONT_SIZE),
                                    wrap=tk.WORD, undo=False,
                                    padx=10, pady=6, bd=0, highlightthickness=0)
        pvsb = ttk.Scrollbar(pf_inner, orient=tk.VERTICAL, command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=pvsb.set)
        self.preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_text.insert('1.0', '(请选择条目)')

        # 控制码提示
        tip_frame = ttk.Frame(rf)
        tip_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
        tip_text = ("控制码: <FRESET,n> <FCOLOR,n> <FCOLORD,r,g,b> <FSIZE,n> <FTYPE,n> "
                    "<TEXT,n> <VARNUM,n> <VARTXT,n> <NAME,n>")
        ttk.Label(tip_frame, text=tip_text, font=FONT_S, foreground='#888').pack(anchor=tk.W)

        # 按钮栏
        bf = ttk.Frame(rf)
        bf.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置", command=self._reset_edit, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="删除此条目", command=self._delete_entry, width=12).pack(side=tk.RIGHT)

        # 底部状态栏 — 各文件路径
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_font = ttk.Label(pf, text="", foreground="gray")
        self.lbl_font.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_g2b = ttk.Label(pf, text="", foreground="gray")
        self.lbl_g2b.pack(side=tk.LEFT, padx=10, pady=2)

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p, label=''):
            if not p:
                lb.config(text=f"({label}未加载)", foreground=r)
            elif not os.path.exists(p):
                lb.config(text=f"(不存在) {p}", foreground=r)
            else:
                lb.config(text=f"{label}: {p}" if label else p, foreground=g)
        _f(self.lbl_tkt, self.tkt_path, 'TKT')
        _f(self.lbl_font, self.font_path, 'FONT9696')
        # g2b.dat 状态 (仅作为信息显示, 不再用于预览渲染)
        if _B2G_TABLE is not None:
            self.lbl_g2b.config(text="g2b.dat: 已加载", foreground=g)
        elif _G2B_TABLE is not None:
            self.lbl_g2b.config(text="g2b.dat: 已加载 (反向表构建失败)", foreground="#CC9900")
        else:
            self.lbl_g2b.config(text="(g2b.dat 未加载)", foreground=r)

    def _set_edit_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.text_widget.config(state=state)

    def _render_preview(self):
        """渲染预览: FONT9696 + PIL 优先, 回退纯文本
        
        FONT9696 字体包含简体中文位图 (以 Big5 编码索引),
        因此 FONT9696 渲染显示的是简体字形 (与游戏实际渲染一致)。
        开启"繁体字体"时, CJK 字符改用系统繁体字体渲染。
        """
        try:
            text = self.text_widget.get('1.0', 'end-1c')
        except Exception:
            text = ''

        pw = self.preview_text
        pw.delete('1.0', 'end')

        if not text.strip():
            pw.insert('end', '[空条目]')
            return

        # 繁体字体模式: CJK 字符用系统繁体字体渲染, 而非 FONT9696
        use_traditional = self.use_traditional_font.get()

        # FONT9696 PIL 渲染
        if HAS_PIL and self.font9696:
            try:
                segments = parse_styled_segments(text)
                img = _render_text_image(segments, self.font9696,
                                          use_traditional_font=use_traditional)
                self._preview_photo = ImageTk.PhotoImage(img)
                pw.image_create('end', image=self._preview_photo)
                return
            except Exception:
                pw.insert('end', '[PIL渲染失败]\n')

        # 回退纯文本
        pw.insert('end', text)

    def _on_font_toggle(self):
        """繁简字体切换开关回调"""
        self._render_preview()

    def _on_quit(self):
        if self._dirty:
            result = messagebox.askyesnocancel("未保存的修改", "有未保存的修改，是否保存？")
            if result is None:
                return
            if result:
                self._save()
        if self.font9696:
            self.font9696.close()
            self.font9696 = None
        self.root.quit()

    # ----------- 文件操作 -----------
    def _load_tks_dir(self):
        d = filedialog.askdirectory(
            title="选择 TKS 游戏目录",
            initialdir=self._guess_tks_dir()
        )
        if not d:
            return
        tkt_path = os.path.join(d, "TKT.dat")
        if not os.path.exists(tkt_path):
            messagebox.showerror("文件缺失", f"未找到 TKT.dat\n({d})")
            return

        # 加载 FONT9696 游戏字体 (用于预览)
        font_path = os.path.join(d, "FONT9696")
        if os.path.exists(font_path) and HAS_PIL:
            try:
                if self.font9696:
                    self.font9696.close()
                self.font9696 = Font9696(font_path)
                self.font_path = font_path
            except Exception as e:
                self.font9696 = None
                self.font_path = None
                print(f"[WARN] FONT9696 加载失败: {e}", file=sys.stderr)
        else:
            self.font9696 = None
            self.font_path = None

        # 加载 g2b.dat 简繁转换表 (依据 sub_45BB64)
        g2b_path = os.path.join(d, "g2b.dat")
        if os.path.exists(g2b_path):
            try:
                load_g2b_dat(g2b_path)
                print(f"[INFO] g2b.dat 已加载: {g2b_path}", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] g2b.dat 加载失败: {e}", file=sys.stderr)
        else:
            print(f"[WARN] g2b.dat 不存在: {g2b_path}", file=sys.stderr)

        self._load_file(tkt_path)
        self._update_paths()

    def _guess_tks_dir(self):
        here = os.path.dirname(os.path.abspath(__file__))
        tks_dir = os.path.normpath(os.path.join(here, "..", "..", "逆向工作区", "TKS"))
        return tks_dir if os.path.isdir(tks_dir) else here

    def _load_file(self, path):
        try:
            self.entries = load_tkt(path)
            self.tkt_path = path

            # 自动加载同目录下的 FONT9696 (如果尚未加载)
            font_path = os.path.join(os.path.dirname(path), "FONT9696")
            if HAS_PIL and not self.font9696 and os.path.exists(font_path):
                try:
                    self.font9696 = Font9696(font_path)
                    self.font_path = font_path
                except Exception:
                    self.font9696 = None
                    self.font_path = None

            self._dirty = False
            self._current_idx = None
            self._populate_tree()
            self._set_edit_enabled(False)
            self.lbl_info.config(text="未选中")
            self.id_var.set('')
            self.text_widget.delete('1.0', 'end')
            font_info = " + FONT9696" if self.font9696 else ""
            self.status_var.set(f"已加载: {os.path.basename(path)} ({len(self.entries)} 条目{font_info})")
            self._update_paths()
            self.root.title(f"TKT.dat 编辑器 - {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))

    def _save(self):
        if not self.tkt_path:
            self._save_as()
            return
        self._do_save(self.tkt_path)

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            title="另存为 TKT.dat",
            defaultextension=".dat",
            filetypes=[("TKT 数据库", "*.dat"), ("所有文件", "*.*")],
            initialdir=self._guess_tks_dir()
        )
        if path:
            self._do_save(path)

    def _do_save(self, path):
        if not messagebox.askyesno(
            "确认保存",
            f"确认保存到 {os.path.basename(path)}？\n共 {len(self.entries)} 条目"
        ):
            return
        try:
            save_tkt(path, self.entries)
            self.tkt_path = path
            self._dirty = False
            self.lbl_dirty.config(text="")
            self.status_var.set(f"已保存: {os.path.basename(path)} ({len(self.entries)} 条目)")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _reload(self):
        if not self.tkt_path:
            return
        if self._dirty:
            result = messagebox.askyesno("确认重新加载", "有未保存的修改，确认重新加载将丢失这些修改。")
            if not result:
                return
        self._load_file(self.tkt_path)

    # ----------- 列表操作 -----------
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = list(range(len(self.entries)))
        for idx in self.filtered_indices:
            e = self.entries[idx]
            preview = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
            self.tree.insert('', 'end', iid=str(idx),
                             values=(e['slot'], e['id'], preview))

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        try:
            id_from = int(self.filter_from.get()) if self.filter_from.get().strip() else None
        except ValueError:
            id_from = None
        try:
            id_to = int(self.filter_to.get()) if self.filter_to.get().strip() else None
        except ValueError:
            id_to = None

        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []
        for idx, e in enumerate(self.entries):
            if id_from is not None and e['id'] < id_from:
                continue
            if id_to is not None and e['id'] > id_to:
                continue
            if query:
                text_lower = e['text'].lower()
                id_str = str(e['id'])
                if query not in text_lower and query not in id_str:
                    continue
            self.filtered_indices.append(idx)
            preview = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
            self.tree.insert('', 'end', iid=str(idx),
                             values=(e['slot'], e['id'], preview))
        self.status_var.set(f"过滤结果: {len(self.filtered_indices)} / {len(self.entries)} 条目")

    def _clear_filter(self):
        self.search_var.set('')
        self.filter_from.set('')
        self.filter_to.set('')
        self._populate_tree()
        self.status_var.set(f"已加载: {os.path.basename(self.tkt_path or '')} ({len(self.entries)} 条目)")

    def _focus_search(self):
        # 聚焦到搜索框
        for w in self.root.winfo_children():
            if isinstance(w, ttk.Frame):
                for child in w.winfo_children():
                    if isinstance(child, ttk.Entry) and child.cget('textvariable') == str(self.search_var):
                        child.focus_set()
                        return

    # ----------- 条目选择/编辑 -----------
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._load_entry_to_edit(idx)

    def _load_entry_to_edit(self, idx):
        if idx < 0 or idx >= len(self.entries):
            return
        self._current_idx = idx
        e = self.entries[idx]
        self.lbl_info.config(text=f"slot={e['slot']}  ID={e['id']}")
        self.id_var.set(str(e['id']))
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', 'end')
        self.text_widget.insert('1.0', e['text'])
        self._set_edit_enabled(True)
        self.lbl_dirty.config(text="")
        self._render_preview()

    def _on_text_modified(self, event=None):
        if self._current_idx is not None:
            self.lbl_dirty.config(text="[未保存]")
        # 50ms 防抖: 连续输入时合并渲染请求
        if hasattr(self, '_preview_job') and self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(50, self._render_preview)

    def _apply_edit(self):
        if self._current_idx is None:
            return
        try:
            new_id = int(self.id_var.get())
        except ValueError:
            messagebox.showerror("ID 错误", "条目 ID 必须是整数。")
            return
        new_text = self.text_widget.get('1.0', 'end-1c')

        e = self.entries[self._current_idx]
        if e['id'] != new_id or e['text'] != new_text:
            e['id'] = new_id
            e['text'] = new_text
            self._dirty = True
            self.lbl_dirty.config(text="")

            # 更新列表显示
            iid = str(self._current_idx)
            if self.tree.exists(iid):
                preview = new_text.replace('\n', '↵').replace('\t', ' ')[:60]
                self.tree.item(iid, values=(e['slot'], new_id, preview))
            self.status_var.set(f"已修改条目 slot={e['slot']}")

    def _reset_edit(self):
        if self._current_idx is not None:
            self._load_entry_to_edit(self._current_idx)

    # ----------- 新增/删除 -----------
    def _new_entry(self):
        if not self.entries:
            messagebox.showinfo("提示", "请先加载 TKT.dat 文件。")
            return

        # 分配新 ID: 当前最大 ID + 1
        max_id = max(e['id'] for e in self.entries)
        new_id = max_id + 1 if max_id >= 0 else 1
        new_slot = len(self.entries)

        new_entry = OrderedDict([
            ('slot', new_slot),
            ('id', new_id),
            ('text', ''),
        ])
        self.entries.append(new_entry)
        self._dirty = True

        # 添加到列表末尾
        idx = len(self.entries) - 1
        self.filtered_indices.append(idx)
        self.tree.insert('', 'end', iid=str(idx),
                         values=(new_slot, new_id, ''))

        # 选中新条目
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        self.status_var.set(f"已新增条目 slot={new_slot}, ID={new_id}")

    def _delete_entry(self):
        if self._current_idx is None:
            return
        e = self.entries[self._current_idx]
        result = messagebox.askyesno(
            "确认删除",
            f"确认删除条目 slot={e['slot']} ID={e['id']}?\n"
            f"文本前 50 字: {e['text'][:50]!r}"
        )
        if not result:
            return

        # 从列表移除
        idx = self._current_idx
        self.entries.pop(idx)
        self._dirty = True

        # 重建 slot 编号
        for i, entry in enumerate(self.entries):
            entry['slot'] = i

        # 刷新列表
        self._current_idx = None
        self._populate_tree()
        self._set_edit_enabled(False)
        self.lbl_info.config(text="未选中")
        self.id_var.set('')
        self.text_widget.delete('1.0', 'end')
        self.status_var.set(f"已删除条目, 剩余 {len(self.entries)} 条目")

    # ----------- TAG 工具栏 -----------
    def _build_tag_toolbar(self, parent):
        """在文本编辑器上方构建 TAG 快捷输入工具栏。"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, padx=2, pady=2)
        self.tag_toolbar = toolbar

        # --- Group 1: 格式 (FRESET) ---
        g1 = ttk.Frame(toolbar)
        g1.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(g1, text="格式:", font=FONT_S).pack(side=tk.LEFT)
        self.freset_var = tk.StringVar()
        freset_cb = ttk.Combobox(g1, textvariable=self.freset_var, values=[
            "1-全部恢复", "2-恢复颜色", "3-重新初始化", "4-恢复字体"
        ], width=10, state='readonly', font=FONT_S)
        freset_cb.pack(side=tk.LEFT, padx=2)
        freset_cb.bind('<<ComboboxSelected>>', self._on_freset_select)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # --- Group 2: 颜色 (FCOLOR) ---
        g2 = ttk.Frame(toolbar)
        g2.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(g2, text="颜色:", font=FONT_S).pack(side=tk.LEFT)
        # 常用颜色按钮
        common_colors = [17, 19, 20, 23, 26]
        for ci in common_colors:
            hex_color = GAME_COLORS[ci]
            btn = tk.Button(g2, width=2, height=1, bg=hex_color,
                            activebackground=hex_color,
                            relief=tk.RAISED, bd=1,
                            command=lambda c=ci: self._insert_fcolor(c))
            btn.pack(side=tk.LEFT, padx=1)
        # 更多颜色按钮
        ttk.Button(g2, text="更多…", width=5,
                   command=self._show_color_palette).pack(side=tk.LEFT, padx=(2, 0))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # --- Group 3: 字体 (FSIZE / FTYPE) ---
        g3 = ttk.Frame(toolbar)
        g3.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(g3, text="字号:", font=FONT_S).pack(side=tk.LEFT)
        self.fsize_var = tk.StringVar()
        fsize_cb = ttk.Combobox(g3, textvariable=self.fsize_var,
                                values=["12", "16", "24", "32", "48"],
                                width=4, state='readonly', font=FONT_S)
        fsize_cb.pack(side=tk.LEFT, padx=2)
        fsize_cb.bind('<<ComboboxSelected>>', self._on_fsize_select)

        ttk.Label(g3, text="字体:", font=FONT_S).pack(side=tk.LEFT, padx=(4, 0))
        self.ftype_var = tk.StringVar()
        ftype_values = [f"{i}-{name}" for i, name in {
            1: "细明体", 2: "明体", 3: "楷体", 4: "宋体",
            5: "微正黑", 6: "黑体", 7: "仿宋", 8: "楷体2"
        }.items()]
        ftype_cb = ttk.Combobox(g3, textvariable=self.ftype_var,
                                values=ftype_values, width=8,
                                state='readonly', font=FONT_S)
        ftype_cb.pack(side=tk.LEFT, padx=2)
        ftype_cb.bind('<<ComboboxSelected>>', self._on_ftype_select)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # --- Group 4: 姓名 (NAME) ---
        g4 = ttk.Frame(toolbar)
        g4.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(g4, text="姓名", width=6,
                   command=self._insert_name_tag).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # --- Group 5: RGB 颜色 (FCOLORD) ---
        g5 = ttk.Frame(toolbar)
        g5.pack(side=tk.LEFT)
        ttk.Button(g5, text="RGB色", width=6,
                   command=self._insert_fcolord).pack(side=tk.LEFT)

    def _insert_tag(self, opening, closing=None):
        """在 text_widget 中插入标签，支持选区包裹。"""
        tw = self.text_widget
        tw.focus_set()
        try:
            sel_start, sel_end = tw.tag_ranges('sel')
        except ValueError:
            sel_start = sel_end = None

        if sel_start and sel_end:
            selected_text = tw.get(sel_start, sel_end)
            tw.delete(sel_start, sel_end)
            full = opening + selected_text + (closing or '')
            tw.insert(sel_start, full)
            new_end = tw.index(f"{sel_start} + {len(full)} chars")
            tw.tag_remove('sel', '1.0', 'end')
            tw.tag_add('sel', sel_start, new_end)
        else:
            tw.insert(tk.INSERT, opening + (closing or ''))

        self._on_text_modified()
        self._render_preview()

    def _on_freset_select(self, event=None):
        val = self.freset_var.get()
        if not val:
            return
        n = int(val.split('-')[0])
        self._insert_tag(f"<FRESET,{n}>")
        self.freset_var.set('')

    def _insert_fcolor(self, color_idx):
        self._insert_tag(f"<FCOLOR,{color_idx}>", "<FRESET,2>")

    def _show_color_palette(self):
        """弹出全部 32 色调色板。"""
        top = tk.Toplevel(self.root)
        top.title("选择颜色")
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)
        # 居中
        top.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - top.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - top.winfo_height()) // 2
        top.geometry(f"+{x}+{y}")

        f = ttk.Frame(top, padding=8)
        f.pack()
        ttk.Label(f, text="点击颜色插入 <FCOLOR,n> 标签", font=FONT).grid(row=0, column=0, columnspan=8, pady=(0, 6))
        for ci in range(1, 33):
            hex_color = GAME_COLORS[ci]
            btn = tk.Button(f, width=3, height=1, bg=hex_color,
                            activebackground=hex_color,
                            relief=tk.RAISED, bd=1,
                            command=lambda c=ci: (self._insert_fcolor(c), top.destroy()))
            btn.grid(row=1 + (ci - 1) // 8, column=(ci - 1) % 8, padx=2, pady=2)
            # 悬停提示颜色编号
            tk.ToolTip = lambda w, t: None  # 占位，不引入复杂tooltip

    def _on_fsize_select(self, event=None):
        val = self.fsize_var.get()
        if not val:
            return
        n = int(val)
        self._insert_tag(f"<FSIZE,{n}>", "<FRESET,1>")
        self.fsize_var.set('')

    def _on_ftype_select(self, event=None):
        val = self.ftype_var.get()
        if not val:
            return
        n = int(val.split('-')[0])
        self._insert_tag(f"<FTYPE,{n}>", "<FRESET,4>")
        self.ftype_var.set('')

    def _insert_name_tag(self):
        """插入 <NAME,1><NAME,2> 标签对"""
        self._insert_tag("<NAME,1><NAME,2>")

    def _insert_fcolord(self):
        color = colorchooser.askcolor(title="选择 RGB 颜色", parent=self.root)
        if not color or not color[0]:
            return
        r, g, b = int(color[0][0]), int(color[0][1]), int(color[0][2])
        self._insert_tag(f"<FCOLORD,{r},{g},{b}>", "<FRESET,2>")

    # ----------- 帮助 -----------
    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKT.dat 文本数据库编辑器 v1.0\n\n"
            "基于逆向工程 sub_401E88/sub_4067E8/sub_4019D0 实现。\n"
            "支持加载/编辑/保存/新增 TKT.dat 条目。\n\n"
            "控制码:\n"
            "  <FRESET,n>  n∈[1,4]     <FCOLOR,n>  n∈[1,32]\n"
            "  <FCOLORD,r,g,b> r,g,b∈[0,255]\n"
            "  <FSIZE,n>   n∈[12,48]   <FTYPE,n>   n∈[1,8]\n"
            "  <TEXT,n>    n∈[1,32767] (2字节)\n"
            "  <VARNUM,n>  n∈[1,255]   <VARTXT,n>  n∈[1,255]\n"
            "  <NAME,n>    n∈[1,2]"
        )


# ============================================================
# CLI
# ============================================================

def main():
    initial_path = None
    if len(sys.argv) > 1:
        initial_path = sys.argv[1]
        if not os.path.exists(initial_path):
            print(f"[ERROR] 文件不存在: {initial_path}", file=sys.stderr)
            return 1

    root = tk.Tk()
    TktEditor(root, initial_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
