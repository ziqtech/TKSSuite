#!/usr/bin/env python3
"""
TKT.dat 文本数据库编辑器 v1.0 (PySide6 工业级完整版)
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
"""

import os
import re
import struct
import sys
from collections import OrderedDict

# ----------------- PySide6 Imports -----------------
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QPlainTextEdit, QTextEdit, QComboBox,
    QMessageBox, QFileDialog, QColorDialog, QDialog, QGridLayout,
    QFrame, QStackedWidget, QScrollArea
)
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QFont, QPixmap, QImage, QIcon,
    QTextCursor, QTextDocument
)
from PySide6.QtCore import Qt, QTimer, QUrl, QSize

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    pass

# ============================================================
# 常量 (全部来自反编译)
# ============================================================
XOR_KEY = 0xFF                       # sub_401E88: `*p = ~*p` 即 XOR 0xFF
HDR_SIZE = 8                         # 未加密头部: total_size(4) + record_count(4)
ENTRY_TERMINATOR = 0x00              # sub_401E88 行 336
LINE_SEPARATOR = 0x1E                # sub_401E88 行 320 (十进制 30)

# 控制字节映射 (sub_4019D0): code -> (name, data_bytes, min_val, max_val)
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

TAG_NAME_MAP = {v[0]: (code, v[1], v[2], v[3]) for code, v in CONTROL_TAGS.items()}
TAG_PATTERN = re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')

# ============================================================
# 游戏渲染参数 (sub_44E49C 文本绘制调度)
# ============================================================

# FCOLOR 1-32 调色板 (dword_A2C524[32], RGB565 LE)
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
GAME_FONT_SIZES = {12, 16, 24, 32, 48}
DEFAULT_FONT_SIZE = 16

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

DEFAULT_FTYPE = 2
DEFAULT_FCOLOR = 32    
PREVIEW_BG = '#1a1d24'  # 工业风深色视口背景
FTYPE_BY_FAMILY_NAME = {v[0]: k - 1 for k, v in GAME_FONT_FAMILIES.items()}

# ASCII → BIG5 重映射表 (word_4EC810)
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
# GB2312 ↔ Big5 转换 (依据 sub_45BB64/sub_45BCE4)
# ============================================================
_G2B_TABLE = None
_B2G_TABLE = None

def load_g2b_dat(g2b_path):
    """加载 g2b.dat 并构建双向转换表。"""
    global _G2B_TABLE, _B2G_TABLE
    with open(g2b_path, 'rb') as f:
        data = f.read()
    if len(data) != 0x20000:
        raise ValueError(f"g2b.dat 大小错误: 期望 131072 字节, 实际 {len(data)}")
    _G2B_TABLE = data

    _B2G_TABLE = {}
    for gb_code in range(0x10000):
        idx = gb_code * 2
        if idx + 1 < len(data):
            big5_lo = data[idx]
            big5_hi = data[idx + 1]
            if big5_lo or big5_hi: 
                big5_code = (big5_lo << 8) | big5_hi
                _B2G_TABLE[big5_code] = gb_code
    return data

def big5_to_gb(text):
    """将 Big5 编码文本转换为 GB2312 编码文本。"""
    if _B2G_TABLE is None:
        return text 

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
                    result.append(ch) 
            else:
                result.append(ch) 
        except (UnicodeEncodeError, UnicodeDecodeError):
            result.append(ch) 
    return ''.join(result)

# ============================================================
# TKT 文件 I/O (依据 sub_401E88)
# ============================================================
def load_tkt(tkt_path):
    """加载 TKT.dat, 返回 entries 列表 (OrderedDict)。"""
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

    # 切分三表
    id_table_size = 4 * record_count
    offset_table_size = 4 * record_count
    text_base = id_table_size + offset_table_size

    entries = []
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', decrypted, i * 4)[0]         
        text_offset = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0] 

        # 提取条目字节 (扫描 0x00 终止)
        abs_off = text_base + text_offset
        if abs_off >= len(decrypted):
            blob = b''
        else:
            end = abs_off
            while end < len(decrypted) and decrypted[end] != ENTRY_TERMINATOR:
                end += 1
            blob = decrypted[abs_off:end]

        # 按 0x1E 拆行
        raw_lines = blob.split(bytes([LINE_SEPARATOR]))
        decoded_lines = [decode_line(ln) for ln in raw_lines]
        text = '\n'.join(decoded_lines)

        entries.append(OrderedDict([
            ('slot', i),
            ('id', entry_id),
            ('text', text),
        ]))
    return entries

def decode_line(line_bytes):
    """把单行字节流解码为 UTF 文本, 控制字节转为 <TAG,n> 标记。"""
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
        # Big5 双字节 (sub_4019D0 行 45-51)
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
    """把一行 UTF 文本编码为二进制字节流 (Big5 + 控制字节)。"""
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

def parse_styled_segments(text):
    """将含 <TAG,n> 的 TKT 文本解析为 [(text, {style}), ...] 分段列表。"""
    segments = []
    current = {
        'fg': GAME_COLORS[DEFAULT_FCOLOR],
        'size': DEFAULT_FONT_SIZE,
        'family': GAME_FONT_FAMILIES[DEFAULT_FTYPE],
    }
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
                if val == 1: 
                    current['fg'] = GAME_COLORS[DEFAULT_FCOLOR]
                    current['size'] = DEFAULT_FONT_SIZE
                    current['family'] = GAME_FONT_FAMILIES[DEFAULT_FTYPE]
                elif val == 2: 
                    current['fg'] = prev_color
                elif val == 3: 
                    current['fg'] = GAME_COLORS[DEFAULT_FCOLOR]
                    current['size'] = DEFAULT_FONT_SIZE
                    current['family'] = GAME_FONT_FAMILIES[DEFAULT_FTYPE]
                elif val == 4: 
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
    字形: 96×96 最大, 1bpp, 3字节组RLE
    """
    GLYPHS_PER_SECTION = 14915
    GLYPH_BUF_SIZE = 1152

    def __init__(self, path):
        self._f = open(path, 'rb')
        idx_bytes = self._f.read(8 * self.GLYPHS_PER_SECTION * 4)
        self._index = list(struct.unpack_from('<%dI' % (8 * self.GLYPHS_PER_SECTION), idx_bytes, 0))
        self._cache = {} 

    def close(self):
        if self._f:
            self._f.close()
            self._f = None

    def _char_index(self, char_code, ftype=0):
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
        cache_key = (char_code, ftype, target_height, color)
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._glyph_raw(char_code, ftype)
        if not data:
            w = target_height // 2
            img = Image.new('RGBA', (max(w, 1), target_height), (0, 0, 0, 0))
            self._cache[cache_key] = (img, w)
            return (img, w)

        raw = self._decode_rle(data)
        raw = bytes(b ^ 0xFF for b in raw)

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

        glyph_bytes = bytearray(gw * gh)
        for y in range(min_y, max_y + 1):
            row_off = y * 12
            for x in range(min_x, max_x + 1):
                bi = row_off + (x // 8)
                if raw[bi] & (1 << (7 - (x % 8))):
                    glyph_bytes[(y - min_y) * gw + (x - min_x)] = 255

        glyph_img = Image.frombytes('L', (gw, gh), bytes(glyph_bytes))
        scale = target_height / 96.0
        new_w = max(int(gw * scale), 1)
        new_h = max(int(gh * scale), 1)
        glyph_img = glyph_img.resize((new_w, new_h), Image.LANCZOS)

        advance = target_height
        canvas_w = target_height
        canvas_h = target_height
        centered = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        x_offset = (canvas_w - new_w) // 2
        y_offset = (canvas_h - new_h) // 2
        centered.paste(glyph_img, (x_offset, y_offset), glyph_img)

        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        colored = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        alpha = centered.split()[3]
        colored.paste(centered, (0, 0), alpha)
        color_layer = Image.new('RGBA', (canvas_w, canvas_h), (r, g, b, 255))
        result = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        result = Image.composite(color_layer, result, alpha)

        self._cache[cache_key] = (result, advance)
        return (result, advance)

def _hex_to_rgb(hex_color):
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))

def _unicode_to_big5_code(ch):
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
    return WORD_4EC810.get(ascii_code, 0xA140) 

_SYS_FONT_CACHE = {}

def _get_sys_font(size, family_tuple, prefer_traditional=False):
    if not HAS_PIL:
        return None
    key = (size, family_tuple[0] if family_tuple else None, prefer_traditional)
    if key in _SYS_FONT_CACHE:
        return _SYS_FONT_CACHE[key]

    font = None
    candidates = list(family_tuple) if family_tuple else []
    if prefer_traditional:
        candidates.extend(['MingLiU', 'PMingLiU', 'DFKai-SB', 'Microsoft JhengHei', 'SimSun', 'SimHei', 'Arial'])
    else:
        candidates.extend(['Microsoft YaHei', 'SimHei', 'SimSun', 'MingLiU', 'PMingLiU', 'Arial'])

    for name in candidates:
        try:
            font = ImageFont.truetype(name, size)
            break
        except (OSError, IOError):
            continue

    if font is None:
        windir = os.environ.get('WINDIR', r'C:\Windows')
        fonts_dir = os.path.join(windir, 'Fonts')
        if prefer_traditional:
            font_files = ('mingliu.ttc', 'pmingliu.ttc', 'kaiu.ttf', 'msjh.ttc', 'simsun.ttc', 'simhei.ttf', 'arial.ttf')
        else:
            font_files = ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf', 'simsun.ttc', 'mingliu.ttc', 'arial.ttf')
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

def _render_fallback_char(ch, size, color, family_tuple, half_width=False, prefer_traditional=False):
    if not HAS_PIL:
        return Image.new('RGBA', (1, 1, 0, 0)), 0
        
    font_obj = _get_sys_font(size, family_tuple, prefer_traditional)
    
    if half_width:
        adv = max(size // 2, 1)
        if font_obj is None:
            return Image.new('RGBA', (adv, size), (0, 0, 0, 0)), adv
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        img = Image.new('RGBA', (adv, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
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

    if font_obj is None:
        w = max(size // 2, 1)
        return Image.new('RGBA', (w, size), (0, 0, 0, 0)), w

    try:
        bbox = font_obj.getbbox(ch)
    except Exception:
        bbox = None

    if bbox is None:
        w = max(size // 2, 1)
        return Image.new('RGBA', (w, size), (0, 0, 0, 0)), w

    x0, y0, x1, y1 = bbox
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)
    
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((-x0, -y0), ch, fill=(r, g, b, 255), font=font_obj)
    
    return img, w

def _render_text_image(segments, font, line_spacing=4, use_traditional_font=False):
    if not segments:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        
    bg_rgb = _hex_to_rgb(PREVIEW_BG)
    lines = [] 
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
                
            big5_code, is_cjk = _unicode_to_big5_code(ch)
            
            if big5_code is not None and is_cjk:
                if use_traditional_font:
                    img, adv = _render_fallback_char(ch, size, color, style['family'], half_width=False, prefer_traditional=True)
                else:
                    img, adv = font.glyph_image(big5_code, ftype, size, color)
            elif big5_code is not None and not is_cjk:
                if big5_code == 0x20 and not use_traditional_font:
                    adv = max(size // 2, 1)
                    img = Image.new('RGBA', (adv, size), (0, 0, 0, 0))
                elif use_traditional_font:
                    img, adv = _render_fallback_char(ch, size, color, style['family'], half_width=True, prefer_traditional=True)
                else:
                    remapped_code = _remap_ascii_for_font9696(big5_code)
                    img, _ = font.glyph_image(remapped_code, ftype, size, color)
                    adv = max(size // 2, 1)
            else:
                if use_traditional_font and ord(ch) > 0x7F:
                    img, adv = _render_fallback_char(ch, size, color, style['family'], half_width=False, prefer_traditional=True)
                else:
                    img, adv = _render_fallback_char(ch, size, color, style['family'], half_width=True, prefer_traditional=use_traditional_font)
                    
            current_line_glyphs.append((img, adv))
            current_line_height = max(current_line_height, size)

    if current_line_glyphs:
        lines.append((current_line_height, current_line_glyphs))
        
    if not lines:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))

    total_h = 0
    for lh, _glyphs in lines:
        total_h += lh + line_spacing
    total_h -= line_spacing if lines else 0

    max_w = 0
    for _lh, glyphs in lines:
        line_w = sum(adv for _img, adv in glyphs)
        max_w = max(max_w, line_w)

    canvas_w = max(max_w + 20, 1)
    canvas_h = max(total_h + 20, 1)
    
    canvas = Image.new('RGBA', (canvas_w, canvas_h), (*bg_rgb, 255))
    y = 10
    for lh, glyphs in lines:
        x = 10
        for img, adv in glyphs:
            y_off = (lh - img.height) // 2
            canvas.paste(img, (x, y + y_off), img)
            x += adv
        y += lh + line_spacing
        
    return canvas

def save_tkt(tkt_path, entries):
    """保存 entries 到 TKT.dat。"""
    record_count = len(entries)
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
                entry_bytes.append(LINE_SEPARATOR)  
            entry_bytes.extend(encode_line(line))
        entry_bytes.append(ENTRY_TERMINATOR)  

        current_offset = len(text_blob)
        text_blob.extend(entry_bytes)
        
        id_table.extend(struct.pack('<i', entry_id))
        offset_table.extend(struct.pack('<I', current_offset))

    data = bytes(id_table) + bytes(offset_table) + bytes(text_blob)
    total_size = len(data)
    
    encrypted = bytes(b ^ XOR_KEY for b in data)
    
    with open(tkt_path, 'wb') as f:
        f.write(struct.pack('<I', total_size))
        f.write(struct.pack('<I', record_count))
        f.write(encrypted)


# ============================================================
# QSS 主题配置 (Godot 风格 + MenuBar 悬停修复)
# ============================================================
GODOT_DARK_QSS = """
QWidget { background-color: #202531; color: #dcdcdc; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #1a1e27; alternate-background-color: #202531; border: 1px solid #14171f; selection-background-color: #478cbf; }
QHeaderView::section { background-color: #202531; border: none; border-bottom: 1px solid #14171f; padding: 4px; }
QPlainTextEdit, QLineEdit, QTextEdit { background-color: #1a1e27; border: 1px solid #14171f; padding: 4px; border-radius: 2px;}
QPushButton { background-color: #2e3548; border: 1px solid #14171f; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover { background-color: #3b445c; }
QPushButton:pressed { background-color: #478cbf; color: #fff; }
QComboBox { background-color: #2e3548; border: 1px solid #14171f; border-radius: 4px; padding: 4px; }
QComboBox::drop-down { border: none; }
/* 彻底隐藏默认背景，用 1 像素的 border 来画线 */
QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #14171f; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #14171f; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }
QScrollBar:vertical { background: #1a1e27; width: 12px; }
QScrollBar::handle:vertical { background: #3b445c; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QLabel#DockHeader { background-color: #14171f; color: #a5b0cb; font-weight: bold; padding: 6px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QWidget#DockBody { background-color: #202531; border: 1px solid #14171f; border-top: none; }

/* 修复菜单栏与下拉菜单的样式 */
QMenuBar { background-color: #202531; color: #dcdcdc; border-bottom: 1px solid #14171f; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background-color: #3b445c; border-radius: 2px; }
QMenuBar::item:pressed { background-color: #478cbf; color: #ffffff; }
QMenu { background-color: #202531; border: 1px solid #14171f; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 24px; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; border-radius: 2px; }
QMenu::separator { height: 1px; background: #14171f; margin: 4px 0px; }
"""

GODOT_LIGHT_QSS = """
QWidget { background-color: #e0e4e8; color: #222222; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #ffffff; alternate-background-color: #f2f5f7; border: 1px solid #b0b5bd; selection-background-color: #478cbf; selection-color: #fff;}
QHeaderView::section { background-color: #d1d6dc; border: none; border-bottom: 1px solid #b0b5bd; padding: 4px; color: #222; }
QPlainTextEdit, QLineEdit, QTextEdit { background-color: #ffffff; border: 1px solid #b0b5bd; padding: 4px; border-radius: 2px;}
QPushButton { background-color: #cdd3d9; border: 1px solid #a6abb2; border-radius: 4px; padding: 5px 12px; color: #111;}
QPushButton:hover { background-color: #b8c0c7; }
QPushButton:pressed { background-color: #8da4b8; }
QComboBox { background-color: #ffffff; border: 1px solid #b0b5bd; border-radius: 4px; padding: 4px; }
QComboBox::drop-down { border: none; }
/* 彻底隐藏默认背景，用 1 像素的 border 来画线 */
QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #b0b5bd; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #b0b5bd; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }
QScrollBar:vertical { background: #f2f5f7; width: 12px; }
QScrollBar::handle:vertical { background: #b8c0c7; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QLabel#DockHeader { background-color: #b0b5bd; color: #111; font-weight: bold; padding: 6px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QWidget#DockBody { background-color: #e0e4e8; border: 1px solid #b0b5bd; border-top: none; }

/* 修复菜单栏与下拉菜单的样式 */
QMenuBar { background-color: #e0e4e8; color: #222222; border-bottom: 1px solid #b0b5bd; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background-color: #b8c0c7; border-radius: 2px; }
QMenuBar::item:pressed { background-color: #8da4b8; color: #111; }
QMenu { background-color: #ffffff; border: 1px solid #b0b5bd; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 24px; color: #222; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; border-radius: 2px; }
QMenu::separator { height: 1px; background: #b0b5bd; margin: 4px 0px; }
"""


# ============================================================
# PySide6 GUI
# ============================================================
def pil_to_qimage(pil_image):
    if pil_image.mode != "RGBA": 
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qim = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return qim.copy()


class DockHeader(QLabel):
    """自定义 Godot 风格的面板标题栏"""
    def __init__(self, title):
        super().__init__(title)
        self.setObjectName("DockHeader")

class TktEditor(QMainWindow):
    def __init__(self, initial_path=None):
        super().__init__()
        self.setWindowTitle("TKT.dat 文本数据库编辑器 - 引擎级界面")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self.font_main = QFont('Microsoft YaHei UI', 9)
        self.font_s = QFont('Microsoft YaHei UI', 8)
        self.font_mono = QFont('Consolas', 10)
        
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path): 
            self.setWindowIcon(QIcon(ico_path))

        self.tkt_path = None
        self.entries = []          
        self.filtered_indices = [] 
        self.font9696 = None       
        self.font_path = None      
        self._dirty = False
        self._current_idx = None   
        self._is_dark = True

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

        if initial_path and os.path.exists(initial_path):
            self._load_file(initial_path)

    def _create_dock(self, title, widget_content):
        """生成 Godot 风格的面板组件"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(DockHeader(title))
        
        body = QWidget()
        body.setObjectName("DockBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.addWidget(widget_content)
        
        layout.addWidget(body, 1)
        return container

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # --- 菜单栏 ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件(F)")
        file_menu.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        file_menu.addSeparator()
        file_menu.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        file_menu.addAction("另存为…", self._save_as)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        edit_menu = menu_bar.addMenu("编辑(E)")
        edit_menu.addAction("新增条目", QKeySequence("Ctrl+N"), self._new_entry)
        edit_menu.addAction("删除当前条目", QKeySequence("Delete"), self._delete_entry)
        edit_menu.addSeparator()
        edit_menu.addAction("查找…", QKeySequence("Ctrl+F"), self._focus_search)
        
        help_menu = menu_bar.addMenu("帮助(H)")
        help_menu.addAction("关于", self._show_about)

        # --- 工具栏 ---
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 4)
        
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("关键词/ID搜索...")
        self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_entry)

        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar_layout.addWidget(btn_search)
        
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar_layout.addWidget(btn_clear)

        toolbar_layout.addWidget(QLabel("  区间:"))
        self.filter_from = QLineEdit()
        self.filter_from.setFixedWidth(50)
        toolbar_layout.addWidget(self.filter_from)
        toolbar_layout.addWidget(QLabel("-"))
        self.filter_to = QLineEdit()
        self.filter_to.setFixedWidth(50)
        toolbar_layout.addWidget(self.filter_to)

        btn_filter = QPushButton("过滤")
        btn_filter.clicked.connect(self._apply_filter)
        toolbar_layout.addWidget(btn_filter)

        toolbar_layout.addSpacing(15)
        btn_new_entry = QPushButton("＋ 新增条目")
        btn_new_entry.clicked.connect(self._new_entry)
        toolbar_layout.addWidget(btn_new_entry)

        self.chk_traditional = QCheckBox("系统繁体字渲染")
        self.chk_traditional.toggled.connect(self._on_font_toggle)
        toolbar_layout.addWidget(self.chk_traditional)

        toolbar_layout.addStretch()

        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar_layout.addWidget(btn_theme)

        main_layout.addLayout(toolbar_layout)

        # --- 主工作区 (水平 Splitter) ---
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(7)  # 设置水平分割线物理热区宽度为 7 像素
        main_layout.addWidget(main_splitter, 1)

        # 1. 左侧：资源列表面板
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['#', 'ID', '文本内容'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(1, 65)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        
        left_dock = self._create_dock("文件系统 (文本资源表)", self.table)
        main_splitter.addWidget(left_dock)

        # 2. 右侧：垂直 Splitter (检查器 + 视口)
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setHandleWidth(7) # 设置垂直分割线物理热区宽度为 7 像素
        main_splitter.addWidget(right_splitter)

        # 2.1 检查器 (属性编辑)
        inspector_widget = QWidget()
        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(0,0,0,0)

        # 信息/ID 栏
        info_layout = QHBoxLayout()
        self.lbl_info = QLabel("未选中")
        self.lbl_info.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.lbl_info)
        info_layout.addStretch()
        
        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setStyleSheet("color: #e27d60; font-weight: bold;")
        info_layout.addWidget(self.lbl_dirty)

        info_layout.addSpacing(20)
        info_layout.addWidget(QLabel("绑定 ID:"))
        self.id_entry = QLineEdit()
        self.id_entry.setFixedWidth(100)
        info_layout.addWidget(self.id_entry)
        inspector_layout.addLayout(info_layout)

        # Tag 工具栏
        self._build_tag_toolbar(inspector_layout)

        # 核心文本编辑器
        self.text_widget = QPlainTextEdit()
        self.text_widget.setFont(self.font_mono)
        self.text_widget.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_widget.textChanged.connect(self._on_text_modified)
        inspector_layout.addWidget(self.text_widget, 1)

        # 底部操作栏
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("✓ 应用修改")
        btn_apply.clicked.connect(self._apply_edit)
        btn_layout.addWidget(btn_apply)
        btn_reset = QPushButton("↺ 重置")
        btn_reset.clicked.connect(self._reset_edit)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        btn_del_this = QPushButton("✗ 删除")
        btn_del_this.clicked.connect(self._delete_entry)
        btn_layout.addWidget(btn_del_this)
        inspector_layout.addLayout(btn_layout)

        inspector_dock = self._create_dock("检查器 (属性/代码编辑)", inspector_widget)
        right_splitter.addWidget(inspector_dock)

        # 2.2 视口 (预览渲染)
        viewport_widget = QWidget()
        viewport_layout = QVBoxLayout(viewport_widget)
        viewport_layout.setContentsMargins(0,0,0,0)

        # 使用 StackedWidget 平滑切换 图片渲染 / 纯文本降级
        self.preview_stack = QStackedWidget()
        
        # Index 0: 图像容器 (绝对居中)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"background-color: {PREVIEW_BG}; border: none;")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview_img = QLabel()
        self.preview_img.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll_layout.addWidget(self.preview_img)
        scroll_area.setWidget(scroll_content)
        self.preview_stack.addWidget(scroll_area)

        # Index 1: 文本降级容器
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet(f"background-color: {PREVIEW_BG}; color: {GAME_COLORS[DEFAULT_FCOLOR]}; border: none;")
        self.preview_text.setPlainText("(请选择条目)")
        self.preview_stack.addWidget(self.preview_text)
        
        viewport_layout.addWidget(self.preview_stack)
        viewport_dock = self._create_dock("2D 视口 (游戏内实时预览)", viewport_widget)
        right_splitter.addWidget(viewport_dock)

        # 调整初始比例
        main_splitter.setSizes([350, 930])
        right_splitter.setSizes([400, 400])

        # --- 底部状态栏 ---
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 4, 0, 0)
        self.lbl_tkt = QLabel("(TKT未加载)")
        status_layout.addWidget(self.lbl_tkt)
        status_layout.addWidget(self._make_v_sep())
        self.lbl_font = QLabel("(FONT未加载)")
        status_layout.addWidget(self.lbl_font)
        status_layout.addWidget(self._make_v_sep())
        self.lbl_g2b = QLabel("(G2B未加载)")
        status_layout.addWidget(self.lbl_g2b)
        status_layout.addStretch()
        main_layout.addLayout(status_layout)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)

    def _make_v_sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #777;")
        return sep

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _apply_theme(self):
        qss = GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS
        self.setStyleSheet(qss)
        self._update_paths() 

    def _update_paths(self):
        color_green = "color: #55b572;" if self._is_dark else "color: #178a39;"
        color_red = "color: #e27d60;" if self._is_dark else "color: #c93b16;"

        def _f(lb, p, label=''):
            if not p or not os.path.exists(p):
                lb.setText(f"({label} 未挂载)")
                lb.setStyleSheet(color_red)
            else:
                lb.setText(f"{label}: {p}" if label else p)
                lb.setStyleSheet(color_green)
                
        _f(self.lbl_tkt, self.tkt_path, 'TKT')
        _f(self.lbl_font, self.font_path, 'FONT9696')
        
        if _B2G_TABLE is not None:
            self.lbl_g2b.setText("g2b.dat: 已挂载")
            self.lbl_g2b.setStyleSheet(color_green)
        elif _G2B_TABLE is not None:
            self.lbl_g2b.setText("g2b.dat: 挂载 (反向表失败)")
            self.lbl_g2b.setStyleSheet("color: #d19a3b;")
        else:
            self.lbl_g2b.setText("(g2b.dat 未挂载)")
            self.lbl_g2b.setStyleSheet(color_red)

    def _set_edit_enabled(self, enabled):
        self.text_widget.setEnabled(enabled)
        self.id_entry.setEnabled(enabled)

    def _render_preview(self):
        text = self.text_widget.toPlainText()
        
        if not text.strip():
            self.preview_stack.setCurrentIndex(1)
            self.preview_text.setPlainText('[空条目]')
            return

        use_traditional = self.chk_traditional.isChecked()

        if HAS_PIL and self.font9696:
            try:
                segments = parse_styled_segments(text)
                img = _render_text_image(segments, self.font9696, use_traditional_font=use_traditional)
                
                qim = pil_to_qimage(img)
                self.preview_img.setPixmap(QPixmap.fromImage(qim))
                self.preview_stack.setCurrentIndex(0)
                return
            except Exception as e:
                self.preview_stack.setCurrentIndex(1)
                self.preview_text.setPlainText(f'[PIL渲染报错]\n{str(e)}')
                return

        self.preview_stack.setCurrentIndex(1)
        self.preview_text.setPlainText(text)

    def _on_font_toggle(self, checked):
        self._render_preview()

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存", "场景有未保存的修改，是否在退出前保存？", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes: 
                self._save()
        if self.font9696:
            self.font9696.close()
            self.font9696 = None
        event.accept()

    # ----------- 文件与列表逻辑 -----------
    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "挂载 TKS 游戏目录", self._guess_tks_dir())
        if not d: return
        tkt_path = os.path.join(d, "TKT.dat")
        if not os.path.exists(tkt_path):
            QMessageBox.critical(self, "文件缺失", f"未找到 TKT.dat\n({d})")
            return

        font_path = os.path.join(d, "FONT9696")
        if os.path.exists(font_path) and HAS_PIL:
            try:
                if self.font9696: self.font9696.close()
                self.font9696, self.font_path = Font9696(font_path), font_path
            except: 
                self.font9696 = self.font_path = None
        else: 
            self.font9696 = self.font_path = None

        g2b_path = os.path.join(d, "g2b.dat")
        if os.path.exists(g2b_path):
            try: 
                load_g2b_dat(g2b_path)
            except: 
                pass

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

            font_path = os.path.join(os.path.dirname(path), "FONT9696")
            if HAS_PIL and not self.font9696 and os.path.exists(font_path):
                try: 
                    self.font9696, self.font_path = Font9696(font_path), font_path
                except: 
                    self.font9696 = self.font_path = None

            self._dirty = False
            self._current_idx = None
            self._populate_tree()
            self._set_edit_enabled(False)
            self.lbl_info.setText("未选中")
            self.id_entry.setText('')
            self.text_widget.clear()
            
            self._update_paths()
            self.setWindowTitle(f"TKT.dat 编辑器 - {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def _save(self):
        if not self.tkt_path: 
            self._save_as()
        else: 
            self._do_save(self.tkt_path)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存为 TKT.dat", self._guess_tks_dir(), "TKT 数据库 (*.dat);;所有文件 (*.*)")
        if path: 
            self._do_save(path)

    def _do_save(self, path):
        self._apply_edit()
        reply = QMessageBox.question(self, "确认", f"打包保存到 {os.path.basename(path)}？\n共 {len(self.entries)} 个节点")
        if reply == QMessageBox.No: return
        try:
            save_tkt(path, self.entries)
            self.tkt_path = path
            self._dirty = False
            self.lbl_dirty.setText("")
        except Exception as e: 
            QMessageBox.critical(self, "保存失败", str(e))

    def _populate_tree(self):
        self.table.setRowCount(0)
        self.filtered_indices = list(range(len(self.entries)))
        self.table.setRowCount(len(self.entries))
        for row, idx in enumerate(self.filtered_indices):
            self._set_table_row(row, self.entries[idx])

    def _set_table_row(self, row, e):
        preview = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
        i1, i2 = QTableWidgetItem(str(e['slot'])), QTableWidgetItem(str(e['id']))
        i1.setTextAlignment(Qt.AlignCenter)
        i2.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, i1)
        self.table.setItem(row, 1, i2)
        self.table.setItem(row, 2, QTableWidgetItem(preview))

    def _apply_filter(self):
        query = self.search_entry.text().strip().lower()
        try: 
            id_from = int(self.filter_from.text()) if self.filter_from.text().strip() else None
        except ValueError: 
            id_from = None
        try: 
            id_to = int(self.filter_to.text()) if self.filter_to.text().strip() else None
        except ValueError: 
            id_to = None

        self.table.setRowCount(0)
        self.filtered_indices = []
        row = 0
        for idx, e in enumerate(self.entries):
            if id_from is not None and e['id'] < id_from: continue
            if id_to is not None and e['id'] > id_to: continue
            if query and query not in e['text'].lower() and query not in str(e['id']): continue
            self.filtered_indices.append(idx)
            self.table.insertRow(row)
            self._set_table_row(row, e)
            row += 1

    def _clear_filter(self):
        self.search_entry.setText('')
        self.filter_from.setText('')
        self.filter_to.setText('')
        self._populate_tree()

    def _focus_search(self):
        self.search_entry.setFocus()
        self.search_entry.selectAll()

    def _on_table_select(self):
        selected = self.table.selectedItems()
        if not selected: return
        self._load_entry_to_edit(self.filtered_indices[selected[0].row()])

    def _load_entry_to_edit(self, idx):
        if idx < 0 or idx >= len(self.entries): return
        self._current_idx = idx
        e = self.entries[idx]
        self.lbl_info.setText(f"slot={e['slot']}")
        self.id_entry.setText(str(e['id']))
        self._set_edit_enabled(True)
        self.text_widget.blockSignals(True)
        self.text_widget.setPlainText(e['text'])
        self.text_widget.blockSignals(False)
        self.lbl_dirty.setText("")
        self._render_preview()

    def _on_text_modified(self):
        if self._current_idx is not None: self.lbl_dirty.setText("[!] 未保存")
        self._preview_timer.start(50) 

    def _apply_edit(self):
        if self._current_idx is None: return
        try: 
            new_id = int(self.id_entry.text())
        except ValueError:
            QMessageBox.critical(self, "参数错误", "ID必须是整数。")
            return
            
        new_text = self.text_widget.toPlainText()
        e = self.entries[self._current_idx]
        
        if e['id'] != new_id or e['text'] != new_text:
            e['id'], e['text'] = new_id, new_text
            self._dirty = True
            self.lbl_dirty.setText("")
            try: 
                self._set_table_row(self.filtered_indices.index(self._current_idx), e)
            except ValueError: 
                pass

    def _reset_edit(self):
        if self._current_idx is not None: 
            self._load_entry_to_edit(self._current_idx)

    def _new_entry(self):
        if not self.entries:
            QMessageBox.information(self, "提示", "请先挂载 TKT.dat")
            return
            
        max_id = max(e['id'] for e in self.entries)
        new_entry = OrderedDict([('slot', len(self.entries)), ('id', max_id + 1 if max_id >= 0 else 1), ('text', '')])
        self.entries.append(new_entry)
        self._dirty = True
        
        idx = len(self.entries) - 1
        self.filtered_indices.append(idx)
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_table_row(row, new_entry)
        
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 0))

    def _delete_entry(self):
        if self._current_idx is None: return
        e = self.entries[self._current_idx]
        if QMessageBox.question(self, "确认移除", f"移除节点 slot={e['slot']} ID={e['id']}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.No: return
        
        self.entries.pop(self._current_idx)
        self._dirty = True
        
        for i, entry in enumerate(self.entries): 
            entry['slot'] = i
            
        self._current_idx = None
        self._populate_tree()
        self._set_edit_enabled(False)
        self.lbl_info.setText("未选中")
        self.id_entry.setText('')
        self.text_widget.clear()

    # ----------- TAG 工具栏 -----------
    def _build_tag_toolbar(self, parent_layout):
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 5, 0, 5)

        self.cb_freset = QComboBox()
        self.cb_freset.addItems(["格式控制", "1-全部恢复", "2-恢复颜色", "3-重新初始化", "4-恢复字体"])
        self.cb_freset.currentIndexChanged.connect(self._on_freset_select)
        toolbar.addWidget(self.cb_freset)

        toolbar.addSpacing(10)
        for ci in [17, 19, 20, 23, 26]:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setStyleSheet(f"background-color: {GAME_COLORS[ci]}; border: 1px solid #777; border-radius: 10px;")
            btn.clicked.connect(lambda checked=False, c=ci: self._insert_fcolor(c))
            toolbar.addWidget(btn)
            
        btn_more_color = QPushButton("🎨")
        btn_more_color.setFixedSize(28, 28)
        btn_more_color.clicked.connect(self._show_color_palette)
        toolbar.addWidget(btn_more_color)

        toolbar.addSpacing(10)
        self.cb_fsize = QComboBox()
        self.cb_fsize.addItems(["字号", "12", "16", "24", "32", "48"])
        self.cb_fsize.currentIndexChanged.connect(self._on_fsize_select)
        toolbar.addWidget(self.cb_fsize)

        self.cb_ftype = QComboBox()
        self.cb_ftype.addItems(["字体", "1-细明", "2-明体", "3-楷体", "4-宋体", "5-微正黑", "6-黑体", "7-仿宋", "8-楷体2"])
        self.cb_ftype.currentIndexChanged.connect(self._on_ftype_select)
        toolbar.addWidget(self.cb_ftype)

        toolbar.addSpacing(10)
        btn_name = QPushButton("</> 姓名宏")
        btn_name.clicked.connect(lambda: self._insert_tag("<NAME,1><NAME,2>"))
        toolbar.addWidget(btn_name)
        
        toolbar.addStretch()
        parent_layout.addLayout(toolbar)

    def _insert_tag(self, opening, closing=None):
        cursor = self.text_widget.textCursor()
        selected_text = cursor.selectedText()
        if selected_text: 
            cursor.insertText(opening + selected_text + (closing or ''))
        else: 
            cursor.insertText(opening + (closing or ''))
        self.text_widget.setFocus()
        self._on_text_modified()

    def _on_freset_select(self, index):
        if index == 0: return
        self._insert_tag(f"<FRESET,{int(self.cb_freset.currentText().split('-')[0])}>")
        self.cb_freset.setCurrentIndex(0)

    def _insert_fcolor(self, color_idx):
        self._insert_tag(f"<FCOLOR,{color_idx}>", "<FRESET,2>")

    def _show_color_palette(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("调色板 (游戏内建32色)")
        dlg.setFixedSize(300, 150)
        layout = QGridLayout(dlg)
        for ci in range(1, 33):
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setStyleSheet(f"background-color: {GAME_COLORS[ci]}; border: 1px solid #555; border-radius: 4px;")
            def make_handler(color_id):
                def handler():
                    self._insert_fcolor(color_id)
                    dlg.accept()
                return handler
            btn.clicked.connect(make_handler(ci))
            layout.addWidget(btn, (ci - 1) // 8, (ci - 1) % 8)
        dlg.exec()

    def _on_fsize_select(self, index):
        if index == 0: return
        self._insert_tag(f"<FSIZE,{int(self.cb_fsize.currentText())}>", "<FRESET,1>")
        self.cb_fsize.setCurrentIndex(0)

    def _on_ftype_select(self, index):
        if index == 0: return
        self._insert_tag(f"<FTYPE,{int(self.cb_ftype.currentText().split('-')[0])}>", "<FRESET,4>")
        self.cb_ftype.setCurrentIndex(0)
        
    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "TKT.dat 文本数据库编辑器 v1.0 (PySide6)\n\n"
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

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    
    initial_path = None
    if len(sys.argv) > 1:
        initial_path = sys.argv[1]
        if not os.path.exists(initial_path):
            print(f"[ERROR] 文件不存在: {initial_path}", file=sys.stderr)
            return 1

    editor = TktEditor(initial_path)
    editor.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()