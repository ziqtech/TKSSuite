#!/usr/bin/env python3
"""
TKT.dat 文本数据库编辑器 v5.0 (PySide6 最终完美融合版)
=============================
融合了 V2 原版极高精度的文字测算渲染、Godot QSS/滚动条样式、文件图标加载逻辑，
并加入了 V4 的安全空槽边界扫描、联合渲染视口与智能分仓功能。
"""

import os
import re
import struct
import sys
import json
import argparse
from collections import OrderedDict

# ----------------- PySide6 Imports -----------------
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QPlainTextEdit, QTextEdit, QComboBox,
    QMessageBox, QFileDialog, QColorDialog, QDialog, QGridLayout,
    QFrame, QStackedWidget, QScrollArea, QTabWidget, QListWidget,
    QInputDialog
)
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QFont, QPixmap, QImage, QIcon,
    QTextCursor, QTextDocument
)
from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QTranslator

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    pass

# ============================================================
# 常量 (来自反编译)
# ============================================================
XOR_KEY = 0xFF                       
HDR_SIZE = 8                         
ENTRY_TERMINATOR = 0x00              
LINE_SEPARATOR = 0x1E                

CONTROL_TAGS = {
    0x01: ("FRESET",  1, 1, 4),
    0x02: ("FCOLOR",  1, 1, 32),
    0x04: ("FSIZE",   1, 12, 48),
    0x05: ("FTYPE",   1, 1, 8),
    0x14: ("TEXT",    2, 1, 32767),
    0x15: ("VARNUM",  1, 1, 255),
    0x16: ("VARTXT",  1, 1, 255),
    0x1D: ("NAME",    1, 1, 2),
}

TAG_NAME_MAP = {v[0]: (code, v[1], v[2], v[3]) for code, v in CONTROL_TAGS.items()}
TAG_PATTERN = re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')

_GAME_PALETTE_565 = [
    0x0000, 0x0000, 0x8410, 0x8000, 0x8400, 0x0400, 0x0410, 0x0010, 0x8010,
    0x8200, 0x8008, 0x4400, 0x0408, 0x4010, 0x0210, 0x0000, 0x0000,
    0xF79B, 0xC618, 0xF800, 0xFFE0, 0x07E0, 0x07FF, 0x001F, 0xF81F,
    0xFC08, 0xFA10, 0x87E8, 0x47F0, 0x821F, 0x441F, 0x31EA, 0xFFFF,
]

def _rgb565_to_hex(rgb565):
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
    1: ('字体1',),
    2: ('字体2',),
    3: ('字体3',),
    4: ('字体4',),
    5: ('字体5',),
    6: ('字体6',),
    7: ('字体7',),
    8: ('字体8',),
}

DEFAULT_FTYPE = 2
DEFAULT_FCOLOR = 32    
FTYPE_BY_FAMILY_NAME = {v[0]: k - 1 for k, v in GAME_FONT_FAMILIES.items()}

WORD_4EC810 = {
    0x20: 0xA140, 0x21: 0xA149, 0x22: 0xA1AA, 0x23: 0xA1AD, 0x24: 0xA243, 0x25: 0xA24D, 0x26: 0xA1AE, 0x27: 0xA1AC,
    0x28: 0xA15D, 0x29: 0xA15E, 0x2A: 0xA1B8, 0x2B: 0xA1DE, 0x2C: 0xA141, 0x2D: 0xA1DF, 0x2E: 0xA145, 0x2F: 0xA241,
    0x30: 0xA2AF, 0x31: 0xA2B0, 0x32: 0xA2B1, 0x33: 0xA2B2, 0x34: 0xA2B3, 0x35: 0xA2B4, 0x36: 0xA2B5, 0x37: 0xA2B6,
    0x38: 0xA2B7, 0x39: 0xA2B8, 0x3A: 0xA14A, 0x3B: 0xA146, 0x3C: 0xA1E0, 0x3D: 0xA1E2, 0x3E: 0xA1E1, 0x3F: 0xA148,
    0x40: 0xA249, 0x41: 0xA2CF, 0x42: 0xA2D0, 0x43: 0xA2D1, 0x44: 0xA2D2, 0x45: 0xA2D3, 0x46: 0xA2D4, 0x47: 0xA2D5,
    0x48: 0xA2D6, 0x49: 0xA2D7, 0x4A: 0xA2D8, 0x4B: 0xA2D9, 0x4C: 0xA2DA, 0x4D: 0xA2DB, 0x4E: 0xA2DC, 0x4F: 0xA2DD,
    0x50: 0xA2DE, 0x51: 0xA2DF, 0x52: 0xA2E0, 0x53: 0xA2E1, 0x54: 0xA2E2, 0x55: 0xA2E3, 0x56: 0xA2E4, 0x57: 0xA2E5,
    0x58: 0xA2E6, 0x59: 0xA2E7, 0x5A: 0xA2E8, 0x5B: 0xA165, 0x5C: 0xA242, 0x5D: 0xA166, 0x5E: 0xA173, 0x5F: 0xA1C5,
    0x60: 0xA1AB, 0x61: 0xA2E9, 0x62: 0xA2EA, 0x63: 0xA2EB, 0x64: 0xA2EC, 0x65: 0xA2ED, 0x66: 0xA2EE, 0x67: 0xA2EF,
    0x68: 0xA2F0, 0x69: 0xA2F1, 0x6A: 0xA2F2, 0x6B: 0xA2F3, 0x6C: 0xA2F4, 0x6D: 0xA2F5, 0x6E: 0xA2F6, 0x6F: 0xA2F7,
    0x70: 0xA2F8, 0x71: 0xA2F9, 0x72: 0xA2FA, 0x73: 0xA2FB, 0x74: 0xA2FC, 0x75: 0xA2FD, 0x76: 0xA2FE, 0x77: 0xA340,
    0x78: 0xA341, 0x79: 0xA342, 0x7A: 0xA343, 0x7B: 0xA161, 0x7C: 0xA155, 0x7D: 0xA162, 0x7E: 0xA1E3, 0x7F: 0xA1BD,
}

SEMANTIC_CATEGORIES = [
    {"name": "🌌 传送点文本", "type": "single", "ranges": [(100, 288)]},
    {"name": "🗺️ 剧情地图名称", "type": "single", "ranges": [(300, 513)]},
    {"name": "📜 剧情文本区块", "type": "single", "ranges": [(1000, 4509), (25000, 28849), (30000, 30000)]},
    {"name": "👥 队伍角色名称", "type": "single", "ranges": [(9000, 9030)]},
    {"name": "📚 历史文本", "type": "single", "ranges": [(9050, 9080)]},
    {"name": "⚔️ 技能数据 (名称+说明)", "type": "paired", "name_start": 9101, "name_end": 9444, "desc_start": 9501, "desc_end": 9844},
    {"name": "🧪 物品-药品 (名称+说明)", "type": "paired", "name_start": 10001, "name_end": 10025, "desc_start": 10601, "desc_end": 10625},
    {"name": "🎒 物品-道具 (名称+说明)", "type": "paired", "name_start": 10051, "name_end": 10110, "desc_start": 10651, "desc_end": 10710},
    {"name": "🗡️ 物品-武器 (名称+说明)", "type": "paired", "name_start": 10151, "name_end": 10242, "desc_start": 10751, "desc_end": 10842},
    {"name": "🛡️ 物品-防具 (名称+说明)", "type": "paired", "name_start": 10301, "name_end": 10348, "desc_start": 10901, "desc_end": 10948},
    {"name": "📿 物品-饰品 (名称+说明)", "type": "paired", "name_start": 10401, "name_end": 10458, "desc_start": 11001, "desc_end": 11058},
    {"name": "🔮 物品-特殊 (名称+说明)", "type": "paired", "name_start": 10501, "name_end": 10551, "desc_start": 11101, "desc_end": 11151},
    {"name": "📝 记事文本", "type": "single", "ranges": [(11201, 11260)]},
    {"name": "🏆 功绩文本", "type": "single", "ranges": [(11401, 11467)]},
    {"name": "🏟️ 战斗角色名称", "type": "single", "ranges": [(11601, 11800)]},
    {"name": "📦 空余槽", "type": "single", "ranges": [(11801, 24999)]},
]

# ============================================================
# GB2312 ↔ Big5 转换 (依据 V2 原版逻辑)
# ============================================================
_G2B_TABLE = None
_B2G_TABLE = None

def load_g2b_dat(g2b_path):
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
# TKT 文件 I/O (V2 原版逻辑)
# ============================================================
def load_tkt(tkt_path):
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    if len(raw) < HDR_SIZE:
        raise ValueError(f"TKT.dat 头部不足 8 字节")

    total_size = struct.unpack_from('<I', raw, 0)[0]
    record_count = struct.unpack_from('<I', raw, 4)[0]

    encrypted = raw[HDR_SIZE:HDR_SIZE + total_size]
    decrypted = bytes(b ^ XOR_KEY for b in encrypted)

    id_table_size = 4 * record_count
    offset_table_size = 4 * record_count
    text_base = id_table_size + offset_table_size

    entries = []
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', decrypted, i * 4)[0]         
        text_offset = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0] 
        abs_off = text_base + text_offset
        if abs_off >= len(decrypted):
            blob = b''
        else:
            end = abs_off
            while end < len(decrypted) and decrypted[end] != ENTRY_TERMINATOR:
                end += 1
            blob = decrypted[abs_off:end]

        raw_lines = blob.split(bytes([LINE_SEPARATOR]))
        decoded_lines = [decode_line(ln) for ln in raw_lines]
        text = '\n'.join(decoded_lines)
        entries.append(OrderedDict([('slot', i), ('id', entry_id), ('text', text)]))
    return entries

def decode_line(line_bytes):
    out = []
    buf = bytearray()
    def flush():
        if buf:
            try: out.append(buf.decode('big5', errors='replace'))
            except Exception: out.append(buf.decode('gbk', errors='replace'))
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
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        m = TAG_PATTERN.match(text, i)
        if m:
            tag_name = m.group(1)
            val_str = m.group(2)
            if tag_name in TAG_NAME_MAP:
                code, data_len, min_val, max_val = TAG_NAME_MAP[tag_name]
                val = int(val_str)
                if min_val <= val <= max_val:
                    out.append(code); out.append(val & 0xFF)
                    if data_len == 2:
                        out.append((val >> 8) & 0xFF)
                    i = m.end()
                    continue
            for ch in text[i:m.end()]:
                out.extend(ch.encode('big5', errors='replace'))
            i = m.end()
            continue
            
        if text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                out.append(int(rm.group(1), 16))
                i += rm.end()
                continue
                
        ch = text[i]
        try: encoded = ch.encode('big5')
        except (UnicodeEncodeError, UnicodeDecodeError): encoded = ch.encode('gbk', errors='replace')
        out.extend(encoded)
        i += 1
    return bytes(out)

def parse_styled_segments(text):
    segments = []
    current = {'fg': GAME_COLORS[DEFAULT_FCOLOR], 'size': DEFAULT_FONT_SIZE, 'family': GAME_FONT_FAMILIES[DEFAULT_FTYPE]}
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
            elif tag_name == 'TEXT': buf.append(f'[文本:{val_str}]')
            elif tag_name == 'VARNUM': buf.append(f'[數值變量:{val_str}]')
            elif tag_name == 'VARTXT': buf.append(f'[文本變量:{val_str}]')
            elif tag_name == 'NAME': buf.append('[姓]' if val_str == '1' else '[名]')
            else: buf.append(text[m.start():m.end()])
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
# FONT9696 解码与渲染 (完全恢复 V2 原版多行代码)
# ============================================================
class Font9696:
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

def _hex_to_rgb(h):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))

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

def _render_text_image(segments, font, line_spacing=4, use_traditional_font=False, bg_color='#313c52', scale_factor=1.0):
    if not segments:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        
    bg_rgb = _hex_to_rgb(bg_color)
    scaled_spacing = int(line_spacing * scale_factor)
    lines = [] 
    current_line_glyphs = []
    current_line_height = 0

    for text, style in segments:
        ftype = FTYPE_BY_FAMILY_NAME.get(style['family'][0], 0)
        size = max(int(style['size'] * scale_factor), 1)
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
        total_h += lh + scaled_spacing
    total_h -= scaled_spacing if lines else 0

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
        y += lh + scaled_spacing
        
    return canvas

def save_tkt(tkt_path, entries):
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
            if li > 0: entry_bytes.append(LINE_SEPARATOR)  
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

def pil_to_qimage(pil_image):
    if pil_image.mode != "RGBA": pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    return QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888).copy()

# ============================================================
# QSS 主题加载 (共享 editor_themes/ 目录)
# ============================================================
def _load_qss(theme: str) -> str:
    """从共享 editor_themes/ 目录加载 QSS 并解析 url() 为绝对路径"""
    themes_dir = os.path.join(os.path.dirname(__file__), '..', 'editor_themes')
    qss_path = os.path.join(themes_dir, f'{theme}.qss')
    if os.path.exists(qss_path):
        with open(qss_path, 'r', encoding='utf-8') as f:
            qss = f.read()
        themes_dir_abs = os.path.abspath(themes_dir).replace("\\", "/")
        qss = re.sub(r"url\(([^)]+)\)", lambda m: f"url({themes_dir_abs}/{m.group(1)})", qss)
        return qss
    return ''

GODOT_DARK_QSS = _load_qss('dark')
GODOT_LIGHT_QSS = _load_qss('light')

class DockHeader(QFrame):
    def __init__(self, title, right_layout=None):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)
        if right_layout: layout.addLayout(right_layout)

class TktEditor(QMainWindow):
    def __init__(self, initial_path=None):
        super().__init__()
        self.setWindowTitle("TKT.dat 语义化智能维护编辑器 - 引擎级界面")
        self.resize(1350, 850)

        # --- 还原图标加载 ---
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        self.font_mono = QFont('Consolas', 10)
        self.tkt_path = None
        self.entries = []          
        self.entry_by_id = {}      
        self.filtered_indices = [] 
        self.font9696 = None       
        self.font_path = None
        self._dirty = False
        self._current_idx = None   
        
        # 用于在加载文件时记录未受污染的原始文本状态，格式为 { (ID, 文本) } 元组集合
        # 使用 set 而非 dict，彻底免疫原版文件中重复 ID（废弃数据）导致的快照覆盖误判
        self.original_entry_snapshot = set()
        
        self._zoom_level = 150
        self._sort_col = -1
        self._sort_state = 0  
        self._last_focused_input = None

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        # 应用 Godot 风格窗口标题栏 (与 editor_themes 主题一致)
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

        if app_inst:
            app_inst.focusChanged.connect(self._on_focus_changed)

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

        if initial_path and os.path.exists(initial_path):
            self._load_file(initial_path)

    def _create_dock(self, title, widget_content, header_layout=None):
        """恢复原版的 DockBody 包裹模式以完美显示引擎边框"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(DockHeader(title, header_layout))
        
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

        # --- 菜单栏 (还原全部项) ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件(F)")
        file_menu.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        file_menu.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        file_menu.addAction("另存为…", self._save_as)
        file_menu.addSeparator()
        file_menu.addAction("导入增量 MOD 文件…", QKeySequence("Ctrl+I"), self._import_mod)
        file_menu.addAction("导出增量 MOD 文件…", QKeySequence("Ctrl+E"), self._export_mod)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        edit_menu = menu_bar.addMenu("编辑(E)")
        edit_menu.addAction("新增条目", QKeySequence("Ctrl+N"), self._new_entry)
        edit_menu.addAction("删除当前条目", QKeySequence("Delete"), self._delete_entry)
        edit_menu.addSeparator()
        edit_menu.addAction("查找…", QKeySequence("Ctrl+F"), self._focus_search)
        
        help_menu = menu_bar.addMenu("帮助(H)")
        help_menu.addAction("关于", self._show_about)

        self.main_tabs = QTabWidget()
        
        # Tab 栏右上角角部控件
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        
        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setStyleSheet("color: #e27d60; font-weight: bold;")
        corner_layout.addWidget(self.lbl_dirty)
        
        corner_layout.addSpacing(10)
        self.chk_traditional = QCheckBox("系统繁体字渲染")
        self.chk_traditional.toggled.connect(self._on_font_toggle)
        corner_layout.addWidget(self.chk_traditional)
        
        corner_layout.addSpacing(10)
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        btn_theme.setStyleSheet("padding: 2px 8px; border-radius: 2px;")
        corner_layout.addWidget(btn_theme)
        
        self.main_tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)
        
        main_layout.addWidget(self.main_tabs, 1)

        # ==================== WORKSPACE 1: 原始全局线性维护 ====================
        w1_widget = QWidget()
        w1_layout = QVBoxLayout(w1_widget)
        w1_layout.setContentsMargins(4, 4, 4, 4)

        # 工具栏 (还原 Emoji)
        toolbar_layout = QHBoxLayout()
        self.search_entry = QLineEdit(); self.search_entry.setPlaceholderText("关键词/ID搜索..."); self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_entry)
        
        btn_search = QPushButton("🔍 搜索"); btn_search.clicked.connect(self._apply_filter); toolbar_layout.addWidget(btn_search)
        btn_clear = QPushButton("🧹 清除"); btn_clear.clicked.connect(self._clear_filter); toolbar_layout.addWidget(btn_clear)
        
        toolbar_layout.addWidget(QLabel("  区间:"))
        self.filter_from = QLineEdit(); self.filter_from.setFixedWidth(50); toolbar_layout.addWidget(self.filter_from)
        toolbar_layout.addWidget(QLabel("-"))
        self.filter_to = QLineEdit(); self.filter_to.setFixedWidth(50); toolbar_layout.addWidget(self.filter_to)
        btn_filter = QPushButton("🪄 过滤"); btn_filter.clicked.connect(self._apply_filter); toolbar_layout.addWidget(btn_filter)
        
        toolbar_layout.addSpacing(15)
        btn_new_entry = QPushButton("➕ 新增条目"); btn_new_entry.clicked.connect(self._new_entry); toolbar_layout.addWidget(btn_new_entry)
        toolbar_layout.addStretch()
        w1_layout.addLayout(toolbar_layout)

        w1_splitter = QSplitter(Qt.Horizontal); w1_splitter.setHandleWidth(7)
        w1_layout.addWidget(w1_splitter, 1)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['#', 'ID', '文本内容 Preview'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 50); self.table.setColumnWidth(1, 70)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        w1_splitter.addWidget(self._create_dock("低级全局数据表", self.table))

        w1_right_splitter = QSplitter(Qt.Vertical); w1_right_splitter.setHandleWidth(7)
        w1_splitter.addWidget(w1_right_splitter)

        inspector_widget = QWidget(); ins_layout = QVBoxLayout(inspector_widget); ins_layout.setContentsMargins(0,0,0,0)
        self._build_tag_toolbar(ins_layout)
        
        self.text_widget = QPlainTextEdit(); self.text_widget.setFont(self.font_mono); self.text_widget.textChanged.connect(self._on_text_modified)
        ins_layout.addWidget(self.text_widget, 1)
        
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("✅ 应用修改"); btn_apply.clicked.connect(self._apply_edit); btn_layout.addWidget(btn_apply)
        btn_reset = QPushButton("🔄 重置"); btn_reset.clicked.connect(self._reset_edit); btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        btn_del_this = QPushButton("❌ 删除"); btn_del_this.clicked.connect(self._delete_entry); btn_layout.addWidget(btn_del_this)
        ins_layout.addLayout(btn_layout)
        w1_right_splitter.addWidget(self._create_dock("检查器 (属性/代码编辑)", inspector_widget))

        # 视口
        viewport_widget = QWidget(); vp_layout = QVBoxLayout(viewport_widget); vp_layout.setContentsMargins(0,0,0,0)
        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(0,0,0,0)
        btn_zoom_out = QPushButton("➖"); btn_zoom_out.setFixedSize(22, 22); btn_zoom_out.setStyleSheet("padding: 0px; font-size: 12px;"); btn_zoom_out.clicked.connect(self._zoom_out)
        self.lbl_zoom = QLabel("150%"); self.lbl_zoom.setAlignment(Qt.AlignCenter); self.lbl_zoom.setFixedWidth(40); self.lbl_zoom.setStyleSheet("font-size: 11px; background-color: transparent;")
        btn_zoom_in = QPushButton("➕"); btn_zoom_in.setFixedSize(22, 22); btn_zoom_in.setStyleSheet("padding: 0px; font-size: 12px;"); btn_zoom_in.clicked.connect(self._zoom_in)
        zoom_layout.addWidget(btn_zoom_out); zoom_layout.addWidget(self.lbl_zoom); zoom_layout.addWidget(btn_zoom_in)

        self.preview_stack = QStackedWidget()
        self.preview_scroll_area = QScrollArea(); self.preview_scroll_area.setWidgetResizable(True)
        scroll_content = QWidget(); scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content); scroll_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview_img = QLabel(); self.preview_img.setAlignment(Qt.AlignLeft | Qt.AlignTop); scroll_layout.addWidget(self.preview_img)
        self.preview_scroll_area.setWidget(scroll_content); self.preview_stack.addWidget(self.preview_scroll_area)
        self.preview_text = QTextEdit(); self.preview_text.setReadOnly(True); self.preview_stack.addWidget(self.preview_text)
        vp_layout.addWidget(self.preview_stack)
        w1_right_splitter.addWidget(self._create_dock("2D 视口渲染器", viewport_widget, header_layout=zoom_layout))
        
        w1_splitter.setSizes([350, 950]); w1_right_splitter.setSizes([400, 400])
        self.main_tabs.addTab(w1_widget, "🔍 全局文件系统 (线性模式)")

        # ==================== WORKSPACE 2: 游戏语义化模块分类编辑 ====================
        w2_widget = QWidget()
        w2_layout = QHBoxLayout(w2_widget)
        w2_layout.setContentsMargins(4, 4, 4, 4)

        self.comp_cat_list = QListWidget()
        self.comp_cat_list.setFixedWidth(200)
        for cat in SEMANTIC_CATEGORIES: self.comp_cat_list.addItem(cat['name'])
        self.comp_cat_list.currentRowChanged.connect(self._on_comp_category_changed)
        w2_layout.addWidget(self.comp_cat_list)

        self.w2_splitter = QSplitter(Qt.Horizontal); self.w2_splitter.setHandleWidth(7)
        self.w2_splitter.splitterMoved.connect(self._adjust_comp_columns)
        w2_layout.addWidget(self.w2_splitter, 1)

        comp_mid_widget = QWidget(); comp_mid_layout = QVBoxLayout(comp_mid_widget); comp_mid_layout.setContentsMargins(0,0,0,0)
        
        self.comp_table = QTableWidget(0, 4)
        self.comp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.comp_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.comp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comp_table.verticalHeader().setVisible(False)
        self.comp_table.itemSelectionChanged.connect(self._on_comp_table_select)
        comp_mid_layout.addWidget(self.comp_table, 1)
        self.w2_splitter.addWidget(comp_mid_widget)

        # --- 创建右侧垂直分割器 (用于存放检查器和独立视口) ---
        w2_right_splitter = QSplitter(Qt.Vertical)
        w2_right_splitter.setHandleWidth(7)
        self.w2_splitter.addWidget(w2_right_splitter)

        comp_right_widget = QWidget(); comp_right_layout = QVBoxLayout(comp_right_widget); comp_right_layout.setContentsMargins(0,0,0,0)
        
        # 复用工具栏，控制当前处于焦点的输入框（不显示槽位/ID信息）
        self._build_tag_toolbar(comp_right_layout, show_info=False)

        self.comp_box1_title = QLabel("名称 / 主文本内容 (ID: ---)")
        self.comp_box1_title.setStyleSheet("font-weight: bold; color: #478cbf;")
        comp_right_layout.addWidget(self.comp_box1_title)
        self.comp_text1 = QPlainTextEdit(); self.comp_text1.setFont(self.font_mono)
        self.comp_text1.textChanged.connect(self._on_comp_text_modified)
        comp_right_layout.addWidget(self.comp_text1, 1)
        
        self.comp_desc_container = QWidget()
        dc_layout = QVBoxLayout(self.comp_desc_container); dc_layout.setContentsMargins(0,0,0,0)
        self.comp_box2_title = QLabel("说明 / 描述文本内容 (ID: ---)")
        self.comp_box2_title.setStyleSheet("font-weight: bold; color: #55b572; padding-top: 10px;")
        dc_layout.addWidget(self.comp_box2_title)
        self.comp_text2 = QPlainTextEdit(); self.comp_text2.setFont(self.font_mono)
        self.comp_text2.textChanged.connect(self._on_comp_text_modified)
        dc_layout.addWidget(self.comp_text2, 1)
        comp_right_layout.addWidget(self.comp_desc_container)

        btn_comp_apply = QPushButton("✅ 保存本槽修改 (点击空槽直接输入即可扩展)")
        btn_comp_apply.setStyleSheet("font-weight:bold; padding:8px; margin-top: 10px;")
        btn_comp_apply.clicked.connect(self._apply_comp_edit)
        comp_right_layout.addWidget(btn_comp_apply)

        # 底部弹簧：将上方控件推向顶部，避免居中分布
        comp_right_layout.addStretch()

        w2_right_splitter.addWidget(self._create_dock("分类属性扩展区", comp_right_widget))

        # --- 将联合视口提取为独立分组 ---
        comp_preview_widget = QWidget()
        comp_preview_layout = QVBoxLayout(comp_preview_widget)
        comp_preview_layout.setContentsMargins(0,0,0,0)

        comp_preview_header = QHBoxLayout()
        comp_preview_header.setContentsMargins(0, 0, 0, 0)
        btn_comp_zoom_out = QPushButton("➖"); btn_comp_zoom_out.setFixedSize(22, 22); btn_comp_zoom_out.setStyleSheet("padding: 0px; font-size: 12px;"); btn_comp_zoom_out.clicked.connect(self._zoom_out)
        self.lbl_comp_zoom = QLabel("150%"); self.lbl_comp_zoom.setAlignment(Qt.AlignCenter); self.lbl_comp_zoom.setFixedWidth(40); self.lbl_comp_zoom.setStyleSheet("font-size: 11px; background-color: transparent;")
        btn_comp_zoom_in = QPushButton("➕"); btn_comp_zoom_in.setFixedSize(22, 22); btn_comp_zoom_in.setStyleSheet("padding: 0px; font-size: 12px;"); btn_comp_zoom_in.clicked.connect(self._zoom_in)
        comp_preview_header.addWidget(btn_comp_zoom_out); comp_preview_header.addWidget(self.lbl_comp_zoom); comp_preview_header.addWidget(btn_comp_zoom_in)

        self.comp_preview_scroll = QScrollArea()
        self.comp_preview_scroll.setWidgetResizable(True)
        sc_comp = QWidget(); sc_comp.setStyleSheet("background:transparent;")
        scl_comp = QVBoxLayout(sc_comp); scl_comp.setContentsMargins(4,4,4,4)
        self.comp_preview_img = QLabel(); self.comp_preview_img.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scl_comp.addWidget(self.comp_preview_img)
        self.comp_preview_scroll.setWidget(sc_comp)
        
        comp_preview_layout.addWidget(self.comp_preview_scroll)

        w2_right_splitter.addWidget(self._create_dock("2D 视口渲染器 (文本预览)", comp_preview_widget, header_layout=comp_preview_header))

        self.w2_splitter.setSizes([650, 450])
        w2_right_splitter.setSizes([400, 400])
        self.main_tabs.addTab(w2_widget, "📦 游戏数据分类编辑 (智能分舱扩展模式)")

        # --- 底部统一路径状态栏 ---
        status_layout = QHBoxLayout(); status_layout.setContentsMargins(4, 4, 4, 0)
        self.lbl_tkt = QLabel("(TKT未加载)"); status_layout.addWidget(self.lbl_tkt); status_layout.addWidget(self._make_v_sep())
        self.lbl_font = QLabel("(FONT未加载)"); status_layout.addWidget(self.lbl_font); status_layout.addWidget(self._make_v_sep())
        self.lbl_g2b = QLabel("(G2B未加载)"); status_layout.addWidget(self.lbl_g2b); status_layout.addStretch()
        main_layout.addLayout(status_layout)

        self._preview_timer = QTimer(self); self._preview_timer.setSingleShot(True); self._preview_timer.timeout.connect(self._render_preview)
        self._comp_preview_timer = QTimer(self); self._comp_preview_timer.setSingleShot(True); self._comp_preview_timer.timeout.connect(self._render_comp_previews)

    def _make_v_sep(self):
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFrameShadow(QFrame.Sunken); sep.setStyleSheet("color: #777;")
        return sep

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        self._render_preview()
        self._render_comp_previews()
        # 更新窗口标题栏颜色
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

    def _apply_theme(self):
        qss = GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS
        self.setStyleSheet(qss)
        preview_bg = '#1a1d24' if self._is_dark else '#313c52'
        if hasattr(self, 'preview_scroll_area'): self.preview_scroll_area.setStyleSheet(f"background-color: {preview_bg}; border: none;")
        if hasattr(self, 'preview_text'): self.preview_text.setStyleSheet(f"background-color: {preview_bg}; color: {GAME_COLORS[DEFAULT_FCOLOR]}; border: none;")
        if hasattr(self, 'comp_preview_scroll'): self.comp_preview_scroll.setStyleSheet(f"background-color: {preview_bg}; border: none;")
        self._update_paths()

    def _update_paths(self):
        cg, cr = ("color: #55b572;" if self._is_dark else "color: #178a39;"), ("color: #e27d60;" if self._is_dark else "color: #c93b16;")
        def _f(lb, p, l=''):
            if not p or not os.path.exists(p): lb.setText(f"({l} 未挂载)"); lb.setStyleSheet(cr)
            else: lb.setText(f"{l}: {p}"); lb.setStyleSheet(cg)
        _f(self.lbl_tkt, self.tkt_path, 'TKT')
        _f(self.lbl_font, self.font_path, 'FONT9696')
        if _B2G_TABLE is not None: self.lbl_g2b.setText("g2b.dat: 已挂载"); self.lbl_g2b.setStyleSheet(cg)
        else: self.lbl_g2b.setText("(g2b.dat 未挂载)"); self.lbl_g2b.setStyleSheet(cr)

    def _rebuild_id_map(self):
        self.entry_by_id = {e['id']: e for e in self.entries}

    def _set_edit_enabled(self, enabled):
        self.text_widget.setEnabled(enabled); self.id_entry.setEnabled(enabled)

    def _load_file(self, path):
        try:
            self.entries = load_tkt(path)
            self.tkt_path = path
            self._rebuild_id_map()
            
            self.original_entry_snapshot.clear()
            for entry in self.entries:
                self.original_entry_snapshot.add((entry['id'], entry['text']))
            
            font_path = os.path.join(os.path.dirname(path), "FONT9696")
            if HAS_PIL and os.path.exists(font_path):
                if self.font9696: self.font9696.close()
                self.font9696, self.font_path = Font9696(font_path), font_path
            
            self._dirty = False; self._current_idx = None
            self.lbl_dirty.setText("")
            self._populate_tree()
            self._set_edit_enabled(False)
            
            self.comp_cat_list.setCurrentRow(0)
            self._on_comp_category_changed(0)
            
            self.setWindowTitle(f"TKT.dat 编辑器 v5.0 - {os.path.basename(path)}")
            self._apply_theme()
        except Exception as e: QMessageBox.critical(self, "数据载入溃散", str(e))

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "挂载 TKS 游戏核心环境目录")
        if not d: return
        tkt_path = os.path.join(d, "TKT.dat")
        if not os.path.exists(tkt_path): QMessageBox.critical(self, "寻路失败", "目录内未检测到 TKT.dat"); return
        
        g2b_path = os.path.join(d, "g2b.dat")
        if os.path.exists(g2b_path): 
            try: load_g2b_dat(g2b_path)
            except: pass
        self._load_file(tkt_path)

    def _save(self):
        if not self.tkt_path: self._save_as()
        else: self._do_save(self.tkt_path)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "打包输出解密 TKT.dat", "", "TKT.dat (*.dat)")
        if path: self._do_save(path)

    def _do_save(self, path):
        self._apply_edit()
        try:
            save_tkt(path, self.entries)
            self.tkt_path = path; self._dirty = False; self.lbl_dirty.setText("")
            QMessageBox.information(self, "成功", "引擎级 TKT 打包回填写盘完毕。")
        except Exception as e: QMessageBox.critical(self, "构写失败", str(e))

    def _export_mod(self):
        # 1. 安全前置检查：确保当前内存中有数据环境
        if not self.tkt_path or not self.entries:
            QMessageBox.warning(self, "环境缺失", "当前未加载任何基础 TKT.dat 文件，无法进行差分导出。")
            return

        # 2. 强制收尾：将当前 UI 焦点文本框中正在输入的未保存文本同步回内存容器
        self._apply_edit()
        
        # 3. 核心差分扫描：对比当前内存状态与初始快照
        #    使用 (ID, 文本) 元组集合判定，彻底免疫原版文件重复 ID 导致的误判
        mod_entries = []
        for current_entry in self.entries:
            eid = current_entry['id']
            current_text = current_entry['text']
            
            # 直接判断当前的 (ID, 文本) 组合是否在原始集合中出现过
            if (eid, current_text) not in self.original_entry_snapshot:
                # 重新按 0, 1, 2 编排连续的 slot 槽位，防止底层二进制打包时偏移错位
                mod_entries.append(OrderedDict([
                    ('slot', len(mod_entries)), 
                    ('id', eid), 
                    ('text', current_text)
                ]))
        
        # 4. 若无任何脏数据，提前阻断
        if not mod_entries:
            QMessageBox.information(self, "无变动", "未检测到任何文本变动或新增条目，无需导出。")
            return
            
        # 5. 【核心细节】：弹出交互式对话框，让开发者自主选择导出格式
        format_options = [
            "1. JSON 明文核对格式 (*.json)",
            "2. 二进制加密补丁格式 (*.dat; *.tkt)"
        ]
        
        selected_format, ok = QInputDialog.getItem(
            self, 
            "选择 MOD 导出数据类型", 
            f"检测到共 {len(mod_entries)} 项变更。\n请选择保存类型（建议正式发布前先导出JSON核对）：", 
            format_options, 
            0,      # 默认选中第一项：JSON
            False   # 文本不可由用户任意编辑修改
        )
        
        # 用户点击了取消或关闭了弹窗，则安全中断
        if not ok or not selected_format:
            return

        # 6. 根据用户的格式选择，分流处理文件对话框的过滤器和底层写盘逻辑
        base_name = os.path.splitext(os.path.basename(self.tkt_path))[0]
        
        if "JSON" in selected_format:
            # --- 分流 A: 导出 JSON 明文纯文本 ---
            default_file_name = f"MOD_{base_name}_REVIEW.json"
            save_path, _ = QFileDialog.getSaveFileName(
                self, 
                "导出明文核对文件", 
                default_file_name, 
                "JSON Data Files (*.json)"
            )
            
            if save_path:
                try:
                    with open(save_path, 'w', encoding='utf-8') as json_file:
                        # ensure_ascii=False 确保中文汉字不被转义为 \\uXXXX
                        # indent=4 维持标准的漂亮排版格式，极大方便肉眼核对
                        json.dump(mod_entries, json_file, ensure_ascii=False, indent=4)
                    
                    QMessageBox.information(
                        self, 
                        "明文导出成功", 
                        f"JSON 核对文本已生成完毕！\n您可以直接使用文本编辑器打开：\n\n{save_path}"
                    )
                except Exception as e:
                    QMessageBox.critical(self, "JSON 导出失败", f"文件写入时发生异常:\n{str(e)}")
                    
        else:
            # --- 分流 B: 导出原版标准二进制加密数据文件 ---
            default_file_name = f"MOD_{base_name}.dat"
            save_path, _ = QFileDialog.getSaveFileName(
                self, 
                "导出二进制 MOD 补丁", 
                default_file_name, 
                "TKT Game Files (*.dat *.tkt)"
            )
            
            if save_path:
                try:
                    # 复用原脚本底层的反解/构建算法函数，输出被 XOR 0xFF 加密处理后的原始格式
                    save_tkt(save_path, mod_entries)
                    QMessageBox.information(
                        self, 
                        "二进制打包成功", 
                        f"增量 MOD 数据打包成功！\n共封装了 {len(mod_entries)} 条加密补丁数据。"
                    )
                except Exception as e:
                    QMessageBox.critical(self, "二进制打包失败", f"打包二进制文件时发生底层崩溃:\n{str(e)}")

    def _import_mod(self):
        # 1. 前置检查：必须先加载原版 TKT 作为"底包"
        if not self.tkt_path or not self.entries:
            QMessageBox.warning(self, "环境缺失", "请先加载原版 TKT.dat 文件作为底包，再导入 MOD 进行数据融合。")
            return

        # 2. 弹出文件选择框，支持双格式
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入增量 MOD 文件",
            "",
            "MOD 数据文件 (*.json *.dat *.tkt);;JSON 明文文件 (*.json);;二进制加密文件 (*.dat *.tkt)"
        )

        if not file_path:
            return

        try:
            imported_data = []
            
            # 3. 格式分流解析
            if file_path.lower().endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_data = json.load(f)
            else:
                # 复用底层的 load_tkt 函数，它可以完美解密标准的二进制补丁
                imported_data = load_tkt(file_path)

            if not imported_data:
                QMessageBox.information(self, "空文件", "选中的 MOD 文件中没有任何有效数据。")
                return

            # 4. 核心融合逻辑 (Base + Override)
            overwrite_count = 0
            append_count = 0

            for mod_entry in imported_data:
                eid = mod_entry['id']
                mod_text = mod_entry['text']

                if eid in self.entry_by_id:
                    # 场景 A：如果原版游戏底包中已有这个 ID，执行文本覆盖
                    if self.entry_by_id[eid]['text'] != mod_text:
                        self.entry_by_id[eid]['text'] = mod_text
                        overwrite_count += 1
                else:
                    # 场景 B：如果是一个全新扩展的 ID，执行追加插入
                    new_entry = OrderedDict([
                        ('slot', len(self.entries)), 
                        ('id', eid), 
                        ('text', mod_text)
                    ])
                    self.entries.append(new_entry)
                    self.entry_by_id[eid] = new_entry
                    append_count += 1

            # 5. 结果反馈
            if overwrite_count == 0 and append_count == 0:
                QMessageBox.information(self, "无变化", "导入的 MOD 数据与当前环境完全一致，未发生任何改变。")
                return

            # 6. 设置脏标记，提醒用户当前内存已被污染（已混入 MOD）
            self._dirty = True
            self.lbl_dirty.setText("[!] 已混入 MOD 补丁")
            
            # 7. 强制刷新所有的 UI 视图，确保刚导入的数据立刻显示
            self._populate_tree()  # 刷新全局线性表
            
            # 刷新分类视图 (如果此时处于分类 Tab，确保空槽状态被更新)
            cat_idx = self.comp_cat_list.currentRow()
            if cat_idx >= 0:
                self._on_comp_category_changed(cat_idx)
                
            QMessageBox.information(
                self, 
                "MOD 融合成功", 
                f"增量补丁已成功打入当前环境！\n\n"
                f"• 覆盖原有文本: {overwrite_count} 条\n"
                f"• 追加全新词条: {append_count} 条"
            )

        except Exception as e:
            QMessageBox.critical(self, "导入溃散", f"解析 MOD 文件时发生底层异常:\n{str(e)}")

    # ============================================================
    # 模块分类维护 (空槽边界扫描核心)
    # ============================================================
    def _get_all_category_starts(self):
        starts = []
        for c in SEMANTIC_CATEGORIES:
            if c['type'] == 'single':
                for r in c['ranges']: starts.append(r[0])
            else:
                starts.append(c['name_start'])
                starts.append(c['desc_start'])
        return sorted(list(set(starts)))
        
    def _get_safe_upper_bound(self, end_id, all_starts):
        for s in all_starts:
            if s > end_id:
                return s - 1
        return end_id + 100 
        
    def _on_comp_category_changed(self, index):
        if index < 0 or not self.entries: return
        cat = SEMANTIC_CATEGORIES[index]
        all_starts = self._get_all_category_starts()
        
        self.comp_table.blockSignals(True)
        self.comp_table.setRowCount(0)
        
        empty_color = QColor("#888888")
        
        if cat['type'] == "single":
            self.comp_desc_container.setVisible(False)
            self.comp_table.setColumnCount(2)
            self.comp_table.setHorizontalHeaderLabels(['条目 ID', '核心文本内容 Preview'])
            self.comp_table.setColumnWidth(0, 80)
            self.comp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            
            row = 0
            for rs, re in cat['ranges']:
                safe_end = self._get_safe_upper_bound(re, all_starts)
                for cur_id in range(rs, safe_end + 1):
                    e = self.entry_by_id.get(cur_id)
                    self.comp_table.insertRow(row)
                    self.comp_table.setItem(row, 0, self._make_center_item(str(cur_id)))
                    if e:
                        self.comp_table.setItem(row, 1, QTableWidgetItem(e['text'].replace('\n','↵')[:60]))
                    else:
                        empty_item = QTableWidgetItem("【安全空槽 - 可直接编辑扩展】")
                        empty_item.setForeground(empty_color)
                        self.comp_table.setItem(row, 1, empty_item)
                    row += 1
        else:
            self.comp_desc_container.setVisible(True)
            self.comp_table.setColumnCount(4)
            self.comp_table.setHorizontalHeaderLabels(['名称 ID', '当前名称', '说明 ID', '当前说明预览'])
            self.comp_table.setColumnWidth(0, 70); self.comp_table.setColumnWidth(2, 70)
            self.comp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
            self.comp_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            
            name_safe = self._get_safe_upper_bound(cat['name_end'], all_starts)
            desc_safe = self._get_safe_upper_bound(cat['desc_end'], all_starts)
            max_pairs = min(name_safe - cat['name_start'], desc_safe - cat['desc_start']) + 1
            
            row = 0
            for i in range(max_pairs):
                nid = cat['name_start'] + i
                did = cat['desc_start'] + i
                ne = self.entry_by_id.get(nid)
                de = self.entry_by_id.get(did)
                
                self.comp_table.insertRow(row)
                self.comp_table.setItem(row, 0, self._make_center_item(str(nid)))
                if ne:
                    self.comp_table.setItem(row, 1, QTableWidgetItem(ne['text'].replace('\n','↵')))
                else:
                    it = QTableWidgetItem("【名称空槽】")
                    it.setForeground(empty_color); self.comp_table.setItem(row, 1, it)
                    
                self.comp_table.setItem(row, 2, self._make_center_item(str(did)))
                if de:
                    self.comp_table.setItem(row, 3, QTableWidgetItem(de['text'].replace('\n','↵')[:50]))
                else:
                    it = QTableWidgetItem("【配套说明空槽】")
                    it.setForeground(empty_color); self.comp_table.setItem(row, 3, it)
                row += 1

        self.comp_table.blockSignals(False)
        self._clear_comp_inputs()
        self._adjust_comp_columns()

    def _clear_comp_inputs(self):
        self._comp_active_id1, self._comp_active_id2 = None, None
        self.comp_box1_title.setText("名称 / 主文本内容 (ID: ---)")
        self.comp_box2_title.setText("说明 / 描述文本内容 (ID: ---)")
        self.comp_text1.clear(); self.comp_text2.clear()
        self.comp_preview_img.clear()

    def _adjust_comp_columns(self):
        """调整分类表格列宽：当前名称:当前说明预览 = 1:4"""
        if self.comp_table.columnCount() != 4:
            return
        total_w = self.comp_table.viewport().width()
        fixed_w = 70 + 70  # 名称ID + 说明ID 固定宽度
        if total_w > fixed_w:
            remaining = total_w - fixed_w
            self.comp_table.setColumnWidth(1, remaining // 5)

    def _on_comp_table_select(self):
        selected = self.comp_table.selectedItems()
        if not selected: return
        row = selected[0].row()
        cat = SEMANTIC_CATEGORIES[self.comp_cat_list.currentRow()]
        self.comp_text1.blockSignals(True); self.comp_text2.blockSignals(True)
        
        if cat['type'] == "single":
            self._comp_active_id1 = int(self.comp_table.item(row, 0).text())
            self._comp_active_id2 = None
            self.comp_box1_title.setText(f"文本内容字段 (ID: {self._comp_active_id1})")
            self.comp_text1.setPlainText(self.entry_by_id.get(self._comp_active_id1, {}).get('text', ''))
            self.comp_text2.clear()
        else:
            self._comp_active_id1 = int(self.comp_table.item(row, 0).text())
            self._comp_active_id2 = int(self.comp_table.item(row, 2).text())
            self.comp_box1_title.setText(f"关联名称字段 (ID: {self._comp_active_id1})")
            self.comp_box2_title.setText(f"关联说明字段 (ID: {self._comp_active_id2})")
            self.comp_text1.setPlainText(self.entry_by_id.get(self._comp_active_id1, {}).get('text', ''))
            self.comp_text2.setPlainText(self.entry_by_id.get(self._comp_active_id2, {}).get('text', ''))

        self.comp_text1.blockSignals(False); self.comp_text2.blockSignals(False)
        self._render_comp_previews()

    def _on_comp_text_modified(self):
        self._dirty = True
        self.lbl_dirty.setText("[!] 未保存")
        self._comp_preview_timer.start(50)

    def _apply_comp_edit(self):
        if getattr(self, '_comp_active_id1', None) is None: return
        
        def _commit(eid, txt):
            if eid is None: return
            if eid in self.entry_by_id:
                self.entry_by_id[eid]['text'] = txt
            else:
                if not txt.strip(): return 
                ne = OrderedDict([('slot', len(self.entries)), ('id', eid), ('text', txt)])
                self.entries.append(ne)
                self.entry_by_id[eid] = ne

        _commit(self._comp_active_id1, self.comp_text1.toPlainText())
        if self._comp_active_id2 is not None:
            _commit(self._comp_active_id2, self.comp_text2.toPlainText())
            
        row = self.comp_table.currentRow()
        if row >= 0:
            txt1 = self.comp_text1.toPlainText().replace('\n','↵')
            txt2 = self.comp_text2.toPlainText().replace('\n','↵')[:50]
            
            i1 = QTableWidgetItem(txt1)
            i1.setForeground(QColor("#dcdcdc") if self._is_dark else QColor("#222222"))
            self.comp_table.setItem(row, 1, i1)
            
            if self._comp_active_id2 is not None:
                i2 = QTableWidgetItem(txt2)
                i2.setForeground(QColor("#dcdcdc") if self._is_dark else QColor("#222222"))
                self.comp_table.setItem(row, 3, i2)
        
        self._populate_tree() 

    def _render_comp_previews(self):
        if not HAS_PIL or not self.font9696: return
        bg = '#1a1d24' if self._is_dark else '#313c52'
        sc = self._zoom_level / 100.0
        ut = self.chk_traditional.isChecked()
        
        img1, img2 = None, None
        txt1 = self.comp_text1.toPlainText().strip()
        txt2 = self.comp_text2.toPlainText().strip()
        
        if self._comp_active_id1 is not None and txt1:
            try: img1 = _render_text_image(parse_styled_segments(txt1), self.font9696, use_traditional_font=ut, bg_color=bg, scale_factor=sc)
            except: pass
            
        if self._comp_active_id2 is not None and txt2:
            try: img2 = _render_text_image(parse_styled_segments(txt2), self.font9696, use_traditional_font=ut, bg_color=bg, scale_factor=sc)
            except: pass
            
        if not img1 and not img2:
            self.comp_preview_img.clear(); return
            
        w1, h1 = (img1.width, img1.height) if img1 else (0, 0)
        w2, h2 = (img2.width, img2.height) if img2 else (0, 0)
        
        spacing = 15 if (img1 and img2) else 0
        canvas_w = max(w1, w2)
        canvas_h = h1 + spacing + h2
        
        bg_rgb = _hex_to_rgb(bg)
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (*bg_rgb, 255))
        y = 0
        if img1:
            canvas.paste(img1, (0, y)); y += h1
        if img1 and img2:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            ly = y + spacing // 2
            draw.line([(10, ly), (canvas_w - 10, ly)], fill=(120, 120, 120, 150), width=1)
            y += spacing
        if img2:
            canvas.paste(img2, (0, y))
            
        self.comp_preview_img.setPixmap(QPixmap.fromImage(pil_to_qimage(canvas)))

    def _make_center_item(self, text):
        it = QTableWidgetItem(text); it.setTextAlignment(Qt.AlignCenter); return it

    # ============================================================
    # 原始全选表（线性模式维护）
    # ============================================================
    def _populate_tree(self):
        self.filtered_indices = list(range(len(self.entries)))
        self._apply_sort()

    def _set_table_row(self, row, e):
        pv = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
        i1, i2 = self._make_center_item(str(e['slot'])), self._make_center_item(str(e['id']))
        self.table.setItem(row, 0, i1); self.table.setItem(row, 1, i2); self.table.setItem(row, 2, QTableWidgetItem(pv))

    def _apply_filter(self):
        query = self.search_entry.text().strip().lower()
        try: id_from = int(self.filter_from.text()) if self.filter_from.text().strip() else None
        except: id_from = None
        try: id_to = int(self.filter_to.text()) if self.filter_to.text().strip() else None
        except: id_to = None

        self.filtered_indices = []
        for idx, e in enumerate(self.entries):
            if id_from is not None and e['id'] < id_from: continue
            if id_to is not None and e['id'] > id_to: continue
            if query and query not in e['text'].lower() and query not in str(e['id']): continue
            self.filtered_indices.append(idx)
        self._apply_sort()

    def _clear_filter(self):
        self.search_entry.clear(); self.filter_from.clear(); self.filter_to.clear()
        self._populate_tree()

    def _focus_search(self):
        self.search_entry.setFocus(); self.search_entry.selectAll()

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        self._load_entry_to_edit(self.filtered_indices[sel[0].row()])

    def _load_entry_to_edit(self, idx):
        if idx < 0 or idx >= len(self.entries): return
        self._current_idx = idx; e = self.entries[idx]
        self.lbl_info.setText(f"当前全项槽位置 slot={e['slot']}")
        self.id_entry.setText(str(e['id']))
        self._set_edit_enabled(True)
        self.text_widget.blockSignals(True); self.text_widget.setPlainText(e['text']); self.text_widget.blockSignals(False)
        self._render_preview()

    def _on_text_modified(self):
        self._dirty = True
        self.lbl_dirty.setText("[!] 未保存")
        self._preview_timer.start(50) 

    def _apply_edit(self):
        if self._current_idx is None: return
        try: nid = int(self.id_entry.text())
        except: QMessageBox.critical(self, "错误", "ID必须是整数"); return
        ntxt = self.text_widget.toPlainText()
        e = self.entries[self._current_idx]
        if e['id'] != nid or e['text'] != ntxt:
            e['id'], e['text'] = nid, ntxt
            self._dirty = True; self._rebuild_id_map()
            try: self._set_table_row(self.filtered_indices.index(self._current_idx), e)
            except: pass

    def _reset_edit(self):
        if self._current_idx is not None: self._load_entry_to_edit(self._current_idx)

    def _new_entry(self):
        if not self.entries: return
        mid = max(e['id'] for e in self.entries)
        ne = OrderedDict([('slot', len(self.entries)), ('id', mid + 1 if mid >= 0 else 1), ('text', '')])
        self.entries.append(ne); self._dirty = True; self._rebuild_id_map(); self._apply_filter()
        try:
            r = self.filtered_indices.index(len(self.entries) - 1)
            self.table.selectRow(r); self.table.scrollToItem(self.table.item(r,0))
        except: pass

    def _delete_entry(self):
        if self._current_idx is None: return
        if QMessageBox.question(self, "物理清空", "物理剥离该节点？", QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Cancel:
            return
        self.entries.pop(self._current_idx)
        for i, entry in enumerate(self.entries): entry['slot'] = i
        self._dirty = True; self._current_idx = None; self._rebuild_id_map(); self._populate_tree()
        self._set_edit_enabled(False); self.text_widget.clear()

    def _on_header_clicked(self, logical_index):
        if logical_index not in (0, 1): return
        if self._sort_col == logical_index: self._sort_state = (self._sort_state + 1) % 3
        else: self._sort_col = logical_index; self._sort_state = 1
        self._apply_sort()

    def _apply_sort(self):
        if self._sort_state == 0: self.filtered_indices.sort()
        else:
            rev = (self._sort_state == 2)
            if self._sort_col == 0: self.filtered_indices.sort(key=lambda x: self.entries[x]['slot'], reverse=rev)
            elif self._sort_col == 1: self.filtered_indices.sort(key=lambda x: self.entries[x]['id'], reverse=rev)
        self.table.blockSignals(True); self.table.setRowCount(0); self.table.setRowCount(len(self.filtered_indices))
        for r, idx in enumerate(self.filtered_indices): self._set_table_row(r, self.entries[idx])
        self.table.blockSignals(False)
        hd = ['#', 'ID', '文本内容 Preview']
        if self._sort_col != -1 and self._sort_state != 0: hd[self._sort_col] += (' ▲' if self._sort_state == 1 else ' ▼')
        self.table.setHorizontalHeaderLabels(hd)

    def _zoom_in(self):
        if self._zoom_level < 300: self._zoom_level += 25; self._apply_zoom()
    def _zoom_out(self):
        if self._zoom_level > 100: self._zoom_level -= 25; self._apply_zoom()
    def _apply_zoom(self):
        if hasattr(self, 'lbl_zoom'): self.lbl_zoom.setText(f"{self._zoom_level}%")
        if hasattr(self, 'lbl_comp_zoom'): self.lbl_comp_zoom.setText(f"{self._zoom_level}%")
        self._render_preview(); self._render_comp_previews()

    def _on_font_toggle(self, c): self._render_preview(); self._render_comp_previews()
    
    def _render_preview(self):
        t = self.text_widget.toPlainText()
        if not t.strip(): self.preview_stack.setCurrentIndex(1); self.preview_text.setPlainText('[空槽]'); return
        if HAS_PIL and self.font9696:
            try:
                seg = parse_styled_segments(t)
                img = _render_text_image(seg, self.font9696, use_traditional_font=self.chk_traditional.isChecked(), bg_color=('#1a1d24' if self._is_dark else '#313c52'), scale_factor=self._zoom_level / 100.0)
                self.preview_img.setPixmap(QPixmap.fromImage(pil_to_qimage(img)))
                self.preview_stack.setCurrentIndex(0); return
            except Exception as e: self.preview_stack.setCurrentIndex(1); self.preview_text.setPlainText(f'报错:\n{str(e)}'); return
        self.preview_stack.setCurrentIndex(1); self.preview_text.setPlainText(t)

    # ----------- TAG 核心工具栏 (100% 恢复 V2 原版包含的所有组件) -----------
    def _build_tag_toolbar(self, parent_layout, show_info=True):
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 5, 0, 5)

        cb_freset = QComboBox()
        cb_freset.addItems(["格式控制", "1-全部恢复", "2-恢复颜色", "3-重新初始化", "4-恢复字体"])
        cb_freset.currentIndexChanged.connect(lambda idx, cb=cb_freset: self._on_combo_freset(idx, cb))
        toolbar.addWidget(cb_freset)

        toolbar.addSpacing(10)
        for ci in [17, 19, 20, 23, 21]:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setStyleSheet(f"background-color: {GAME_COLORS[ci]}; border: 1px solid #777; border-radius: 10px;")
            btn.clicked.connect(lambda checked=False, c=ci: self._insert_fcolor(c))
            toolbar.addWidget(btn)
            
        btn_more_color = QPushButton("🎨")
        btn_more_color.clicked.connect(self._show_color_palette)
        toolbar.addWidget(btn_more_color)

        toolbar.addSpacing(10)
        cb_fsize = QComboBox()
        cb_fsize.addItems(["字号", "12", "16", "24", "32", "48"])
        cb_fsize.currentIndexChanged.connect(lambda idx, cb=cb_fsize: self._on_combo_fsize(idx, cb))
        toolbar.addWidget(cb_fsize)

        cb_ftype = QComboBox()
        cb_ftype.addItems(["字体", "1-字体1", "2-字体2", "3-字体3", "4-字体4", "5-字体5", "6-字体6", "7-字体7", "8-字体8"])
        cb_ftype.currentIndexChanged.connect(lambda idx, cb=cb_ftype: self._on_combo_ftype(idx, cb))
        toolbar.addWidget(cb_ftype)

        toolbar.addSpacing(10)
        btn_name = QPushButton("👤 姓名宏")
        btn_name.clicked.connect(lambda: self._insert_tag("<NAME,1><NAME,2>"))
        toolbar.addWidget(btn_name)

        toolbar.addStretch()
        
        if show_info:
            self.lbl_info = QLabel("未选中")
            toolbar.addWidget(self.lbl_info)
            
            toolbar.addSpacing(10)
            toolbar.addWidget(QLabel("绑定 ID:"))
            self.id_entry = QLineEdit()
            self.id_entry.setFixedWidth(70)
            toolbar.addWidget(self.id_entry)
        
        parent_layout.addLayout(toolbar)

    def _on_focus_changed(self, old, new):
        if new in (self.text_widget, self.comp_text1, self.comp_text2):
            self._last_focused_input = new

    def _insert_tag(self, op, cl=None):
        # 智能识别当前拥有焦点的文本框（优先用实时焦点，回退到最后追踪的输入框）
        target = self.text_widget
        fw = QApplication.focusWidget()
        if fw in (self.text_widget, self.comp_text1, self.comp_text2):
            target = fw
        elif self._last_focused_input is not None:
            target = self._last_focused_input
        elif self.main_tabs.currentIndex() == 1:
            target = self.comp_text1

        cursor = target.textCursor()
        selected_text = cursor.selectedText()
        if selected_text: 
            cursor.insertText(op + selected_text + (cl or ''))
        else: 
            cursor.insertText(op + (cl or ''))
        target.setFocus()
        
        if target == self.text_widget:
            self._on_text_modified()
        else:
            self._on_comp_text_modified()

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

    def _on_combo_freset(self, idx, cb):
        if idx == 0: return
        self._insert_tag(f"<FRESET,{int(cb.currentText().split('-')[0])}>")
        cb.setCurrentIndex(0)

    def _on_combo_fsize(self, idx, cb):
        if idx == 0: return
        self._insert_tag(f"<FSIZE,{int(cb.currentText())}>", "<FRESET,1>")
        cb.setCurrentIndex(0)

    def _on_combo_ftype(self, idx, cb):
        if idx == 0: return
        self._insert_tag(f"<FTYPE,{int(cb.currentText().split('-')[0])}>", "<FRESET,4>")
        cb.setCurrentIndex(0)
        
    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "TKT.dat 文本数据库编辑器 v5.0 (PySide6)\n\n"
            "基于逆向工程 sub_401E88/sub_4067E8/sub_4019D0 实现。\n"
            "支持加载/编辑/保存/新增 TKT.dat 条目。\n\n"
            "控制码:\n"
            "  <FRESET,n>  n∈[1,4]     <FCOLOR,n>  n∈[1,32]\n"
            "  <FSIZE,n>   n∈[12,48]   <FTYPE,n>   n∈[1,8]\n"
            "  <TEXT,n>    n∈[1,32767] (2字节)\n"
            "  <VARNUM,n>  n∈[1,255]   <VARTXT,n>  n∈[1,255]\n"
            "  <NAME,n>    n∈[1,2]"
        )

    def closeEvent(self, event):
        if self._dirty:
            if QMessageBox.question(self, "未保存", "直接退出？", QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Cancel:
                event.ignore()
                return
        if self.font9696: self.font9696.close()
        event.accept()

# ============================================================
# 无界面 CLI 核心调度 (专供 AI Agent 与自动化脚本使用)
# ============================================================
def run_cli(args):
    """处理所有的命令行逻辑，不启动任何 UI 组件"""
    try:
        # 1. 基础环境检验：加载底包并建立快照防重复体系
        if not args.input or not os.path.exists(args.input):
            print("Error: 必须通过 -i / --input 指定有效的 TKT.dat 底包文件。", file=sys.stderr)
            sys.exit(1)
            
        entries = load_tkt(args.input)
        entry_by_id = {e['id']: e for e in entries}
        
        # 建立初始快照 (免疫原版游戏同 ID 脏数据干扰)
        original_snapshot = set((e['id'], e['text']) for e in entries)
        
        print(f"Success: 成功加载底包 {args.input}，共 {len(entries)} 条数据。")

        # 2. 【全量导出】指令：给 AI 提供完整的游戏文本上下文阅读
        if args.dump_all:
            with open(args.dump_all, 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=4)
            print(f"Success: 全量底层数据已导出至 {args.dump_all}")

        # 3. 【导入增量 MOD】指令：支持 .json 与 .dat 自动推断
        if args.import_mod:
            if not os.path.exists(args.import_mod):
                print(f"Error: 找不到待导入的 MOD 文件 {args.import_mod}", file=sys.stderr)
                sys.exit(1)
                
            # 后缀名分流：JSON 文本或 二进制文件
            if args.import_mod.lower().endswith('.json'):
                with open(args.import_mod, 'r', encoding='utf-8') as f:
                    mod_data = json.load(f)
            else:
                mod_data = load_tkt(args.import_mod)
                
            overwrite_count = 0
            append_count = 0
            
            # 执行数据覆盖与追加融合
            for mod_entry in mod_data:
                eid = mod_entry['id']
                mod_text = mod_entry['text']
                
                if eid in entry_by_id:
                    if entry_by_id[eid]['text'] != mod_text:
                        entry_by_id[eid]['text'] = mod_text
                        overwrite_count += 1
                else:
                    new_entry = OrderedDict([
                        ('slot', len(entries)), 
                        ('id', eid), 
                        ('text', mod_text)
                    ])
                    entries.append(new_entry)
                    entry_by_id[eid] = new_entry
                    append_count += 1
                    
            print(f"Success: 成功打入 MOD 补丁 [{args.import_mod}]")
            print(f"Stats: 覆盖 {overwrite_count} 条，追加 {append_count} 条")

        # 4. 【导出增量 MOD】指令：自动计算差异，支持导出 .json 或 .dat
        if args.export_mod:
            mod_entries = []
            for current_entry in entries:
                eid = current_entry['id']
                current_text = current_entry['text']
                
                # 差分对比：仅提取新增或修改过的数据
                if (eid, current_text) not in original_snapshot:
                    mod_entries.append(OrderedDict([
                        ('slot', len(mod_entries)), 
                        ('id', eid), 
                        ('text', current_text)
                    ]))
            
            if not mod_entries:
                print("Info: 经过对比，未检测到任何改动，跳过增量 MOD 导出。")
            else:
                # 后缀名分流写入
                if args.export_mod.lower().endswith('.json'):
                    with open(args.export_mod, 'w', encoding='utf-8') as f:
                        json.dump(mod_entries, f, ensure_ascii=False, indent=4)
                else:
                    save_tkt(args.export_mod, mod_entries)
                print(f"Success: 增量 MOD 已提取并保存至 {args.export_mod} (共 {len(mod_entries)} 条改动)")

        # 5. 【输出完整游戏包】指令：保存带有完整槽位的全尺寸文件（进游戏测试用）
        if args.output:
            save_tkt(args.output, entries)
            print(f"Success: 完整合并后的游戏二进制文件已生成至 {args.output}")

        sys.exit(0)
            
    except Exception as e:
        print(f"Error: CLI 引擎执行期间发生致命崩溃:\n{str(e)}", file=sys.stderr)
        sys.exit(1)

def main():
    # 1. 挂载强化版的参数解析器
    parser = argparse.ArgumentParser(description="TKT.dat 文本数据库编辑器 v5.0 (支持全功能无头 CLI 模式)")
    
    # 定义 CLI 工作流参数
    parser.add_argument("--cli", action="store_true", help="启用无头命令行模式 (跳过 GUI 加载)")
    parser.add_argument("-i", "--input", help="指定基础的 TKT.dat 底包路径 (CLI模式必填)")
    parser.add_argument("--dump-all", help="将底包全量导出为 JSON 文件，用于阅读分析")
    parser.add_argument("--import-mod", help="导入增量 MOD 文件 (根据后缀自动识别 .json 或 .dat)")
    parser.add_argument("--export-mod", help="对比提取并导出增量 MOD (根据后缀自动识别 .json 或 .dat)")
    parser.add_argument("-o", "--output", help="将最终的完整数据流封装导出为 TKT.dat")
    
    # 兼容 GUI 拖拽打开
    parser.add_argument("gui_file", nargs="?", help="[GUI模式] 启动时直接打开的文件")

    # 2. 解析参数
    args, unknown = parser.parse_known_args()

    # 3. 路由分发
    if args.cli:
        run_cli(args)
    else:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        _t = QTranslator()
        _t.load("qtbase_zh_CN", os.path.join(os.path.dirname(__file__), '..', 'editor_utils'))
        app.installTranslator(_t)

        initial_file = args.gui_file if args.gui_file else None
        editor = TktEditor(initial_file)
        editor.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()
