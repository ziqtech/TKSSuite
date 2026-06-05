#!/usr/bin/env python3
"""
TKT.dat 文本数据库编辑器 v4.0 (PySide6 空槽探索 + 联合视口版)
=============================
支持动态边界扫描，自动计算安全的扩展空槽，并在单一视口内联合渲染复合文本。
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
    QFrame, QStackedWidget, QScrollArea, QTabWidget, QListWidget
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
# 常量与配置
# ============================================================
XOR_KEY = 0xFF                       
HDR_SIZE = 8                         
ENTRY_TERMINATOR = 0x00              
LINE_SEPARATOR = 0x1E                

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

# 游戏语义化分类配置映射表
SEMANTIC_CATEGORIES = [
    {"name": " 传送点文本", "type": "single", "ranges": [(100, 288)]},
    {"name": "️ 剧情地图名称", "type": "single", "ranges": [(300, 513)]},
    {"name": " 剧情文本区块", "type": "single", "ranges": [(1000, 4509), (25000, 28849), (30000, 30000)]},
    {"name": " 队伍角色名称", "type": "single", "ranges": [(9000, 9030)]},
    {"name": " 历史文本", "type": "single", "ranges": [(9050, 9080)]},
    {"name": "⚔️ 技能数据 (名称+说明)", "type": "paired", "name_start": 9101, "name_end": 9444, "desc_start": 9501, "desc_end": 9844},
    {"name": " 物品-药品 (名称+说明)", "type": "paired", "name_start": 10001, "name_end": 10025, "desc_start": 10601, "desc_end": 10625},
    {"name": " 物品-道具 (名称+说明)", "type": "paired", "name_start": 10051, "name_end": 10110, "desc_start": 10651, "desc_end": 10710},
    {"name": "️ 物品-武器 (名称+说明)", "type": "paired", "name_start": 10151, "name_end": 10242, "desc_start": 10751, "desc_end": 10842},
    {"name": "️ 物品-防具 (名称+说明)", "type": "paired", "name_start": 10301, "name_end": 10348, "desc_start": 10901, "desc_end": 10948},
    {"name": " 物品-饰品 (名称+说明)", "type": "paired", "name_start": 10401, "name_end": 10458, "desc_start": 11001, "desc_end": 11058},
    {"name": " 物品-特殊 (名称+说明)", "type": "paired", "name_start": 10501, "name_end": 10551, "desc_start": 11101, "desc_end": 11151},
    {"name": " 记事文本", "type": "single", "ranges": [(11201, 11260)]},
    {"name": " 功绩文本", "type": "single", "ranges": [(11401, 11467)]},
    {"name": "️ 战斗角色名称", "type": "single", "ranges": [(11601, 11712)]},
]

_G2B_TABLE = None
_B2G_TABLE = None

def load_g2b_dat(g2b_path):
    global _G2B_TABLE, _B2G_TABLE
    with open(g2b_path, 'rb') as f: data = f.read()
    if len(data) != 0x20000: raise ValueError("g2b.dat 大小错误")
    _G2B_TABLE = data
    _B2G_TABLE = {}
    for gb_code in range(0x10000):
        idx = gb_code * 2
        if idx + 1 < len(data):
            b5_lo, b5_hi = data[idx], data[idx + 1]
            if b5_lo or b5_hi: _B2G_TABLE[(b5_lo << 8) | b5_hi] = gb_code
    return data

def load_tkt(tkt_path):
    with open(tkt_path, 'rb') as f: raw = f.read()
    if len(raw) < HDR_SIZE: raise ValueError("头部不足")
    total_size, record_count = struct.unpack_from('<II', raw, 0)
    decrypted = bytes(b ^ XOR_KEY for b in raw[HDR_SIZE:HDR_SIZE + total_size])
    
    id_table_size = 4 * record_count
    text_base = id_table_size * 2
    entries = []
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', decrypted, i * 4)[0]         
        text_offset = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0] 
        abs_off = text_base + text_offset
        if abs_off >= len(decrypted): blob = b''
        else:
            end = abs_off
            while end < len(decrypted) and decrypted[end] != ENTRY_TERMINATOR: end += 1
            blob = decrypted[abs_off:end]
        raw_lines = blob.split(bytes([LINE_SEPARATOR]))
        text = '\n'.join([decode_line(ln) for ln in raw_lines])
        entries.append(OrderedDict([('slot', i), ('id', entry_id), ('text', text)]))
    return entries

def decode_line(line_bytes):
    out, buf = [], bytearray()
    def flush():
        if buf:
            try: out.append(buf.decode('big5', errors='replace'))
            except: out.append(buf.decode('gbk', errors='replace'))
            buf.clear()
    i, n = 0, len(line_bytes)
    while i < n:
        b = line_bytes[i]
        if b in CONTROL_TAGS:
            tag_name, data_len, _, _ = CONTROL_TAGS[b]
            if i + data_len < n:
                flush()
                if data_len == 1: val = line_bytes[i + 1]
                elif data_len == 2: val = line_bytes[i + 1] | (line_bytes[i + 2] << 8)
                else: val = f"{line_bytes[i+1]},{line_bytes[i+2]},{line_bytes[i+3]}"
                out.append(f'<{tag_name},{val}>')
                i += 1 + data_len
                continue
        if b < 0x20 and b != LINE_SEPARATOR:
            flush(); out.append(f'<RAW,0x{b:02X}>'); i += 1; continue
        if b >= 0x80 and i + 1 < n:
            buf.append(b); buf.append(line_bytes[i + 1]); i += 2
        else: buf.append(b); i += 1
    flush()
    return ''.join(out)

def encode_line(text):
    out = bytearray()
    i, n = 0, len(text)
    while i < n:
        m = TAG_PATTERN.match(text, i)
        if m:
            tag_name, val_str = m.group(1), m.group(2)
            if tag_name in TAG_NAME_MAP:
                code, data_len, min_val, max_val = TAG_NAME_MAP[tag_name]
                if data_len == 3:
                    parts = val_str.split(',')
                    if len(parts) == 3:
                        out.append(code); out.extend([int(p) for p in parts]); i = m.end(); continue
                else:
                    val = int(val_str)
                    if min_val <= val <= max_val:
                        out.append(code); out.append(val & 0xFF)
                        if data_len == 2: out.append((val >> 8) & 0xFF)
                        i = m.end(); continue
            for ch in text[i:m.end()]: out.extend(ch.encode('big5', errors='replace'))
            i = m.end(); continue
        if text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm: out.append(int(rm.group(1), 16)); i += rm.end(); continue
        try: out.extend(text[i].encode('big5'))
        except: out.extend(text[i].encode('gbk', errors='replace'))
        i += 1
    return bytes(out)

def parse_styled_segments(text):
    segments = []
    current = {'fg': GAME_COLORS[DEFAULT_FCOLOR], 'size': DEFAULT_FONT_SIZE, 'family': GAME_FONT_FAMILIES[DEFAULT_FTYPE]}
    prev_color, prev_family = current['fg'], current['family']
    buf, i, n = [], 0, len(text)
    def flush():
        if buf: segments.append((''.join(buf), dict(current))); buf.clear()
    while i < n:
        m = TAG_PATTERN.match(text, i)
        if m:
            flush(); tag_name, val_str = m.group(1), m.group(2)
            if tag_name == 'FCOLOR' and 1 <= int(val_str) <= 32: prev_color = current['fg']; current['fg'] = GAME_COLORS[int(val_str)]
            elif tag_name == 'FCOLORD':
                p = val_str.split(',')
                if len(p) == 3: prev_color = current['fg']; current['fg'] = f'#{int(p[0]):02X}{int(p[1]):02X}{int(p[2]):02X}'
            elif tag_name == 'FSIZE' and int(val_str) in GAME_FONT_SIZES: current['size'] = int(val_str)
            elif tag_name == 'FTYPE' and 1 <= int(val_str) <= 8: prev_family = current['family']; current['family'] = GAME_FONT_FAMILIES[int(val_str)]
            elif tag_name == 'FRESET':
                v = int(val_str)
                if v in (1, 3): current['fg'] = GAME_COLORS[DEFAULT_FCOLOR]; current['size'] = DEFAULT_FONT_SIZE; current['family'] = GAME_FONT_FAMILIES[DEFAULT_FTYPE]
                elif v == 2: current['fg'] = prev_color
                elif v == 4: current['family'] = prev_family
            elif tag_name in ('TEXT', 'VARNUM', 'VARTXT'): buf.append(f'[{tag_name}:{val_str}]')
            elif tag_name == 'NAME': buf.append('[姓]' if val_str == '1' else '[名]')
            else: buf.append(text[m.start():m.end()])
            i = m.end()
        else: buf.append(text[i]); i += 1
    flush()
    return segments

class Font9696:
    GLYPHS_PER_SECTION = 14915
    GLYPH_BUF_SIZE = 1152
    def __init__(self, path):
        self._f = open(path, 'rb')
        self._index = list(struct.unpack('<%dI' % (8 * self.GLYPHS_PER_SECTION), self._f.read(8 * self.GLYPHS_PER_SECTION * 4)))
        self._cache = {} 
    def close(self):
        if self._f: self._f.close(); self._f = None
    def _char_index(self, char_code, ftype=0):
        if char_code < 0x80: return None
        high, low = (char_code >> 8) & 0xFF, char_code & 0xFF
        if high < 0xA1: return None
        li = low - 64 if 0x40 <= low <= 0x7E else (low - 98 if 0xA1 <= low <= 0xFE else None)
        if li is None: return None
        base = li + 157 * (high - 161)
        return base + self.GLYPHS_PER_SECTION * ftype if 0 <= base < self.GLYPHS_PER_SECTION else None
    def glyph_image(self, char_code, ftype=0, target_height=24, color='#FFFFFF'):
        cache_key = (char_code, ftype, target_height, color)
        if cache_key in self._cache: return self._cache[cache_key]
        idx = self._char_index(char_code, ftype)
        if idx is None or idx + 1 >= len(self._index): return self._empty_g(target_height, cache_key)
        off, next_off = self._index[idx], self._index[idx + 1]
        if off >= next_off: return self._empty_g(target_height, cache_key)
        self._f.seek(off); data = self._f.read(next_off - off)
        
        bitmap = bytearray(self.GLYPH_BUF_SIZE)
        bp, bit_p = 0, 7
        for i in range(0, len(data)-2, 3):
            b0, b1, b2 = data[i], data[i+1], data[i+2]
            runs = [b0 & 0x3F, (b0 >> 6) | ((b1 & 0xF) << 2), (b1 >> 4) | ((b2 & 0x3) << 4), b2 >> 2]
            for ri, rlen in enumerate(runs):
                if rlen == 0: continue
                is_black = (ri == 0 or ri == 2)
                for _ in range(rlen):
                    if bp >= self.GLYPH_BUF_SIZE: break
                    if is_black: bitmap[bp] |= (1 << bit_p)
                    bit_p -= 1
                    if bit_p < 0: bit_p = 7; bp += 1
        
        raw = bytes(b ^ 0xFF for b in bitmap)
        min_x, min_y, max_x, max_y = 96, 96, 0, 0
        for y in range(96):
            ro = y * 12
            for x in range(96):
                if raw[ro + (x // 8)] & (1 << (7 - (x % 8))):
                    min_x, min_y = min(min_x, x), min(min_y, y)
                    max_x, max_y = max(max_x, x), max(max_y, y)
        if min_x > max_x: return self._empty_g(target_height, cache_key)
        gw, gh = max_x - min_x + 1, max_y - min_y + 1
        gb = bytearray(gw * gh)
        for y in range(min_y, max_y + 1):
            ro = y * 12
            for x in range(min_x, max_x + 1):
                if raw[ro + (x // 8)] & (1 << (7 - (x % 8))): gb[(y - min_y) * gw + (x - min_x)] = 255
                
        gi = Image.frombytes('L', (gw, gh), bytes(gb))
        sc = target_height / 96.0
        nw, nh = max(int(gw * sc), 1), max(int(gh * sc), 1)
        gi = gi.resize((nw, nh), Image.LANCZOS)
        
        res = Image.new('RGBA', (target_height, target_height), (0,0,0,0))
        r, g, b = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
        cl = Image.new('RGBA', (target_height, target_height), (r,g,b,255))
        centered = Image.new('RGBA', (target_height, target_height), (0,0,0,0))
        centered.paste(gi, ((target_height - nw)//2, (target_height - nh)//2))
        res = Image.composite(cl, res, centered.split()[3])
        self._cache[cache_key] = (res, target_height)
        return (res, target_height)
    def _empty_g(self, h, k):
        w = max(h // 2, 1)
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        self._cache[k] = (img, w)
        return (img, w)

def _hex_to_rgb(h): return (int(h[1:3],16), int(h[3:5],16), int(h[5:7],16))
def _unicode_to_big5_code(ch):
    try:
        b = ch.encode('big5')
        return ((b[0] << 8) | b[1], True) if len(b) == 2 else (b[0], False)
    except:
        try:
            b = ch.encode('gbk')
            return ((b[0] << 8) | b[1], True) if len(b) == 2 else (b[0], False)
        except: return None, False

def _remap_ascii_for_font9696(a): return WORD_4EC810.get(a, 0xA140)
_SYS_FONT_CACHE = {}
def _get_sys_font(s, f, t=False):
    k = (s, f[0] if f else None, t)
    if k in _SYS_FONT_CACHE: return _SYS_FONT_CACHE[k]
    font = None
    for name in (list(f) if f else []) + (['MingLiU','SimSun'] if t else ['Microsoft YaHei','SimHei']):
        try: font = ImageFont.truetype(name, s); break
        except: continue
    if not font: font = ImageFont.load_default()
    _SYS_FONT_CACHE[k] = font
    return font

def _render_fallback_char(ch, s, col, f, hw=False, pt=False):
    if not HAS_PIL: return Image.new('RGBA', (1, 1, 0, 0)), 0
    fobj = _get_sys_font(s, f, pt)
    adv = max(s // 2, 1) if hw else s
    img = Image.new('RGBA', (adv, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    r, g, b = int(col[1:3],16), int(col[3:5],16), int(col[5:7],16)
    dr.text((0, 0), ch, fill=(r, g, b, 255), font=fobj)
    return img, adv

def _render_text_image(segments, font, line_spacing=4, use_traditional_font=False, bg_color='#313c52', scale_factor=1.0):
    if not segments: return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    bg_rgb = _hex_to_rgb(bg_color)
    scaled_spacing = int(line_spacing * scale_factor)
    lines, cur_glyphs, cur_h = [], [], 0
    for text, style in segments:
        ft = FTYPE_BY_FAMILY_NAME.get(style['family'][0], 0)
        sz = max(int(style['size'] * scale_factor), 1)
        col = style['fg']
        for ch in text:
            if ch == '\n':
                if cur_glyphs: lines.append((cur_h, cur_glyphs))
                cur_glyphs, cur_h = [], 0; continue
            code, is_cjk = _unicode_to_big5_code(ch)
            if code is not None and is_cjk:
                img, adv = (_render_fallback_char(ch, sz, col, style['family'], False, True) if use_traditional_font else font.glyph_image(code, ft, sz, col))
            elif code is not None and not is_cjk:
                if code == 0x20 and not use_traditional_font: adv = max(sz//2, 1); img = Image.new('RGBA', (adv, sz), (0,0,0,0))
                elif use_traditional_font: img, adv = _render_fallback_char(ch, sz, col, style['family'], True, True)
                else: img, _ = font.glyph_image(_remap_ascii_for_font9696(code), ft, sz, col); adv = max(sz//2, 1)
            else: img, adv = _render_fallback_char(ch, sz, col, style['family'], ord(ch)<=0x7F, use_traditional_font)
            cur_glyphs.append((img, adv)); cur_h = max(cur_h, sz)
    if cur_glyphs: lines.append((cur_h, cur_glyphs))
    if not lines: return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    th = sum(lh + scaled_spacing for lh, _ in lines) - scaled_spacing
    mw = max(sum(adv for _, adv in gl) for _, gl in lines)
    canvas = Image.new('RGBA', (max(mw + 20, 1), max(th + 20, 1)), (*bg_rgb, 255))
    y = 10
    for lh, gl in lines:
        x = 10
        for img, adv in gl:
            canvas.paste(img, (x, y + (lh - img.height)//2), img)
            x += adv
        y += lh + scaled_spacing
    return canvas

def save_tkt(tkt_path, entries):
    text_blob, id_table, offset_table = bytearray(), bytearray(), bytearray()
    for entry in entries:
        eb = bytearray()
        for li, ln in enumerate(entry['text'].split('\n')):
            if li > 0: eb.append(LINE_SEPARATOR)
            eb.extend(encode_line(ln))
        eb.append(ENTRY_TERMINATOR)
        offset_table.extend(struct.pack('<I', len(text_blob)))
        text_blob.extend(eb)
        id_table.extend(struct.pack('<i', entry['id']))
    data = bytes(id_table) + bytes(offset_table) + bytes(text_blob)
    encrypted = bytes(b ^ XOR_KEY for b in data)
    with open(tkt_path, 'wb') as f:
        f.write(struct.pack('<I', len(data)))
        f.write(struct.pack('<I', len(entries)))
        f.write(encrypted)

def pil_to_qimage(pil_image):
    if pil_image.mode != "RGBA": pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    return QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888).copy()

# ============================================================
# QSS 样式表表
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
QListWidget { background-color: #1a1e27; border: 1px solid #14171f; }
QListWidget::item:selected { background-color: #478cbf; color: white; }
QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #14171f; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #14171f; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QFrame#DockHeader { background-color: #14171f; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QLabel#DockTitle { color: #a5b0cb; font-weight: bold; background-color: transparent; }
QWidget#DockBody { background-color: #202531; border: 1px solid #14171f; border-top: none; }
QMenuBar { background-color: #202531; color: #dcdcdc; border-bottom: 1px solid #14171f; }
QMenuBar::item:selected { background-color: #3b445c; border-radius: 2px; }
QMenu { background-color: #202531; border: 1px solid #14171f; padding: 4px; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; border-radius: 2px; }
"""

GODOT_LIGHT_QSS = """
QWidget { background-color: #e0e4e8; color: #222222; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #ffffff; alternate-background-color: #f2f5f7; border: 1px solid #b0b5bd; selection-background-color: #478cbf; selection-color: #fff;}
QHeaderView::section { background-color: #d1d6dc; border: none; border-bottom: 1px solid #b0b5bd; padding: 4px; color: #222; }
QPlainTextEdit, QLineEdit, QTextEdit { background-color: #ffffff; border: 1px solid #b0b5bd; padding: 4px; border-radius: 2px;}
QPushButton { background-color: #cdd3d9; border: 1px solid #a6abb2; border-radius: 4px; padding: 5px 12px; color: #111;}
QPushButton:hover { background-color: #b8c0c7; }
QComboBox { background-color: #ffffff; border: 1px solid #b0b5bd; border-radius: 4px; padding: 4px; }
QListWidget { background-color: #ffffff; border: 1px solid #b0b5bd; }
QListWidget::item:selected { background-color: #478cbf; color: white; }
QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #b0b5bd; margin-left: 3px; margin-right: 3px; }
QFrame#DockHeader { background-color: #b0b5bd; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QLabel#DockTitle { color: #111; font-weight: bold; background-color: transparent; }
QWidget#DockBody { background-color: #e0e4e8; border: 1px solid #b0b5bd; border-top: none; }
QMenuBar { background-color: #e0e4e8; color: #222222; border-bottom: 1px solid #b0b5bd; }
QMenuBar::item:selected { background-color: #b8c0c7; border-radius: 2px; }
QMenu { background-color: #ffffff; border: 1px solid #b0b5bd; padding: 4px; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; border-radius: 2px; }
"""

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
        self.setWindowTitle("TKT.dat 语义化智能维护编辑器")
        self.resize(1350, 850)
        
        self.font_mono = QFont('Consolas', 10)
        self.tkt_path = None
        self.entries = []          
        self.entry_by_id = {}      
        self.filtered_indices = [] 
        self.font9696 = None       
        self.font_path = None
        self._dirty = False
        self._current_idx = None   
        
        self._zoom_level = 100
        self._sort_col = -1   
        self._sort_state = 0  

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

        if initial_path and os.path.exists(initial_path):
            self._load_file(initial_path)

    def _create_dock(self, title, widget_content, header_layout=None):
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
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- 菜单栏 ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件(F)")
        file_menu.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        file_menu.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        file_menu.addAction("另存为…", self._save_as)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)
        
        help_menu = menu_bar.addMenu("帮助(H)")
        help_menu.addAction("关于…", self._show_about)


        # 全局控制栏
        top_ctrl_layout = QHBoxLayout()
        self.chk_traditional = QCheckBox("系统繁体字渲染")
        self.chk_traditional.toggled.connect(self._on_font_toggle)
        top_ctrl_layout.addWidget(self.chk_traditional)
        top_ctrl_layout.addStretch()
        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setStyleSheet("color: #e27d60; font-weight: bold;")
        top_ctrl_layout.addWidget(self.lbl_dirty)
        btn_theme = QPushButton(" 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        top_ctrl_layout.addWidget(btn_theme)
        main_layout.addLayout(top_ctrl_layout)

        # --- 工作区双轨系统 (Tab 切换) ---
        self.main_tabs = QTabWidget()
        main_layout.addWidget(self.main_tabs, 1)

        # ==================== WORKSPACE 1: 原始全局线性维护 ====================
        w1_widget = QWidget()
        w1_layout = QVBoxLayout(w1_widget)
        w1_layout.setContentsMargins(2, 2, 2, 2)

        # 工具栏
        toolbar_layout = QHBoxLayout()
        self.search_entry = QLineEdit(); self.search_entry.setPlaceholderText("全局搜索..."); self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_entry)
        btn_search = QPushButton(" 搜索"); btn_search.clicked.connect(self._apply_filter); toolbar_layout.addWidget(btn_search)
        btn_clear = QPushButton("扫除"); btn_clear.clicked.connect(self._clear_filter); toolbar_layout.addWidget(btn_clear)
        toolbar_layout.addWidget(QLabel(" 区间:"))
        self.filter_from = QLineEdit(); self.filter_from.setFixedWidth(50); toolbar_layout.addWidget(self.filter_from)
        toolbar_layout.addWidget(QLabel("-"))
        self.filter_to = QLineEdit(); self.filter_to.setFixedWidth(50); toolbar_layout.addWidget(self.filter_to)
        btn_filter = QPushButton("过滤"); btn_filter.clicked.connect(self._apply_filter); toolbar_layout.addWidget(btn_filter)
        toolbar_layout.addSpacing(15)
        btn_new_entry = QPushButton("➕ 全局追加空条目"); btn_new_entry.clicked.connect(self._new_entry); toolbar_layout.addWidget(btn_new_entry)
        toolbar_layout.addStretch()
        w1_layout.addLayout(toolbar_layout)

        w1_splitter = QSplitter(Qt.Horizontal); w1_splitter.setHandleWidth(6)
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

        w1_right_splitter = QSplitter(Qt.Vertical); w1_right_splitter.setHandleWidth(6)
        w1_splitter.addWidget(w1_right_splitter)

        inspector_widget = QWidget(); ins_layout = QVBoxLayout(inspector_widget); ins_layout.setContentsMargins(0,0,0,0)
        info_layout = QHBoxLayout()
        self.lbl_info = QLabel("未选中"); info_layout.addWidget(self.lbl_info)
        info_layout.addStretch(); info_layout.addWidget(QLabel("绑定 ID:"))
        self.id_entry = QLineEdit(); self.id_entry.setFixedWidth(90); info_layout.addWidget(self.id_entry)
        ins_layout.addLayout(info_layout)
        
        self._build_tag_toolbar(ins_layout)
        self.text_widget = QPlainTextEdit(); self.text_widget.setFont(self.font_mono); self.text_widget.textChanged.connect(self._on_text_modified)
        ins_layout.addWidget(self.text_widget, 1)
        
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("✅ 应用修改"); btn_apply.clicked.connect(self._apply_edit); btn_layout.addWidget(btn_apply)
        btn_reset = QPushButton("重置"); btn_reset.clicked.connect(self._reset_edit); btn_layout.addWidget(btn_reset)
        btn_layout.addStretch(); btn_del_this = QPushButton("❌ 物理删除"); btn_del_this.clicked.connect(self._delete_entry); btn_layout.addWidget(btn_del_this)
        ins_layout.addLayout(btn_layout)
        w1_right_splitter.addWidget(self._create_dock("线性检查器 (底层代码逻辑)", inspector_widget))

        # 视口
        viewport_widget = QWidget(); vp_layout = QVBoxLayout(viewport_widget); vp_layout.setContentsMargins(0,0,0,0)
        zoom_layout = QHBoxLayout()
        btn_zoom_out = QPushButton("➖"); btn_zoom_out.setFixedSize(22, 22); btn_zoom_out.setStyleSheet("padding: 0px; font-size: 12px;"); btn_zoom_out.clicked.connect(self._zoom_out)
        self.lbl_zoom = QLabel("100%"); self.lbl_zoom.setAlignment(Qt.AlignCenter); self.lbl_zoom.setFixedWidth(40); self.lbl_zoom.setStyleSheet("font-size: 11px; background-color: transparent;")
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
        self.main_tabs.addTab(w1_widget, " 原始全项表 (线性模式)")

        # ==================== WORKSPACE 2: 游戏语义化模块分类编辑 ====================
        w2_widget = QWidget()
        w2_layout = QHBoxLayout(w2_widget)
        w2_layout.setContentsMargins(4, 4, 4, 4)

        self.comp_cat_list = QListWidget()
        self.comp_cat_list.setFixedWidth(200)
        for cat in SEMANTIC_CATEGORIES: self.comp_cat_list.addItem(cat['name'])
        self.comp_cat_list.currentRowChanged.connect(self._on_comp_category_changed)
        w2_layout.addWidget(self.comp_cat_list)

        w2_splitter = QSplitter(Qt.Horizontal); w2_splitter.setHandleWidth(6)
        w2_layout.addWidget(w2_splitter, 1)

        comp_mid_widget = QWidget(); comp_mid_layout = QVBoxLayout(comp_mid_widget); comp_mid_layout.setContentsMargins(0,0,0,0)
        
        self.comp_table = QTableWidget(0, 4)
        self.comp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.comp_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.comp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comp_table.verticalHeader().setVisible(False)
        self.comp_table.itemSelectionChanged.connect(self._on_comp_table_select)
        comp_mid_layout.addWidget(self.comp_table, 1)
        w2_splitter.addWidget(comp_mid_widget)

        # 右：分类专属复合属性修改面板（集成统一渲染）
        comp_right_widget = QWidget(); comp_right_layout = QVBoxLayout(comp_right_widget); comp_right_layout.setContentsMargins(0,0,0,0)
        
        self.comp_box1_title = QLabel("名称 / 主文本内容 (ID: ---)")
        self.comp_box1_title.setStyleSheet("font-weight: bold; color: #478cbf;")
        comp_right_layout.addWidget(self.comp_box1_title)
        self.comp_text1 = QPlainTextEdit(); self.comp_text1.setFont(self.font_mono); self.comp_text1.setMaximumHeight(80)
        self.comp_text1.textChanged.connect(self._on_comp_text_modified)
        comp_right_layout.addWidget(self.comp_text1)
        
        self.comp_desc_container = QWidget()
        dc_layout = QVBoxLayout(self.comp_desc_container); dc_layout.setContentsMargins(0,0,0,0)
        self.comp_box2_title = QLabel("说明 / 描述文本内容 (ID: ---)")
        self.comp_box2_title.setStyleSheet("font-weight: bold; color: #55b572; padding-top: 10px;")
        dc_layout.addWidget(self.comp_box2_title)
        self.comp_text2 = QPlainTextEdit(); self.comp_text2.setFont(self.font_mono); self.comp_text2.setMaximumHeight(120)
        self.comp_text2.textChanged.connect(self._on_comp_text_modified)
        dc_layout.addWidget(self.comp_text2)
        comp_right_layout.addWidget(self.comp_desc_container)

        btn_comp_apply = QPushButton("✅ 保存本槽修改 (点击空槽直接输入即可拓展)"); btn_comp_apply.setStyleSheet("font-weight:bold; padding:8px; margin-top: 10px;")
        btn_comp_apply.clicked.connect(self._apply_comp_edit)
        comp_right_layout.addWidget(btn_comp_apply)

        # 统一联合视口
        self.comp_preview_title = QLabel("️ 实时联合视口")
        self.comp_preview_title.setStyleSheet("font-weight: bold; color: #a5b0cb; padding-top: 15px;")
        comp_right_layout.addWidget(self.comp_preview_title)
        
        self.comp_preview_scroll = QScrollArea()
        self.comp_preview_scroll.setWidgetResizable(True)
        sc_comp = QWidget(); sc_comp.setStyleSheet("background:transparent;")
        scl_comp = QVBoxLayout(sc_comp); scl_comp.setContentsMargins(4,4,4,4)
        self.comp_preview_img = QLabel(); self.comp_preview_img.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scl_comp.addWidget(self.comp_preview_img)
        self.comp_preview_scroll.setWidget(sc_comp)
        comp_right_layout.addWidget(self.comp_preview_scroll, 1)

        w2_splitter.addWidget(self._create_dock("分类属性扩展及视窗", comp_right_widget))
        w2_splitter.setSizes([650, 450])
        self.main_tabs.addTab(w2_widget, " 游戏数据分类编辑 (智能分舱扩展模式)")

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
            
            self.setWindowTitle(f"TKT.dat 编辑器 v4.0 - {os.path.basename(path)}")
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

    # ============================================================
    # 模块分类维护 (空槽边界扫描核心)
    # ============================================================
    def _get_all_category_starts(self):
        """扫描全盘定义，捕获所有游戏数据定义的有效起始边界。"""
        starts = []
        for c in SEMANTIC_CATEGORIES:
            if c['type'] == 'single':
                for r in c['ranges']: starts.append(r[0])
            else:
                starts.append(c['name_start'])
                starts.append(c['desc_start'])
        return sorted(list(set(starts)))
        
    def _get_safe_upper_bound(self, end_id, all_starts):
        """计算指定段落上限与下一个已知段落起点之间的安全扩容空槽边界。"""
        for s in all_starts:
            if s > end_id:
                return s - 1
        return end_id + 100 # 当处于最后一段定义时，自动释放 100 个游离空槽
        
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
            self.comp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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

    def _clear_comp_inputs(self):
        self._comp_active_id1, self._comp_active_id2 = None, None
        self.comp_box1_title.setText("名称 / 主文本内容 (ID: ---)")
        self.comp_box2_title.setText("说明 / 描述文本内容 (ID: ---)")
        self.comp_text1.clear(); self.comp_text2.clear()
        self.comp_preview_img.clear()

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
        """应用集成检查器数据修改，智能识别空槽生成新节点"""
        if getattr(self, '_comp_active_id1', None) is None: return
        
        def _commit(eid, txt):
            if eid is None: return
            if eid in self.entry_by_id:
                self.entry_by_id[eid]['text'] = txt
            else:
                if not txt.strip(): return # 屏蔽全空操作
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
            
            # 清除原有的空槽变灰提示，恢复文本正常色彩
            i1 = QTableWidgetItem(txt1)
            i1.setForeground(QColor("#dcdcdc") if self._is_dark else QColor("#222222"))
            self.comp_table.setItem(row, 1, i1)
            
            if self._comp_active_id2 is not None:
                i2 = QTableWidgetItem(txt2)
                i2.setForeground(QColor("#dcdcdc") if self._is_dark else QColor("#222222"))
                self.comp_table.setItem(row, 3, i2)
        
        self._populate_tree() 

    def _render_comp_previews(self):
        """联合画布：将两条独立数据同时高精合成在单一视口内"""
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
            # 绘制联合视口居中的隔离分界线
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
        if QMessageBox.question(self, "物理清空", "物理剥离该节点？") == QMessageBox.No: return
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
            
        btn_more_color = QPushButton("")
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
        btn_name = QPushButton(" 姓名宏")
        btn_name.clicked.connect(lambda: self._insert_tag("<NAME,1><NAME,2>"))
        toolbar.addWidget(btn_name)

        toolbar.addSpacing(5)
        btn_rgb = QPushButton(" RGB色")
        btn_rgb.clicked.connect(self._insert_fcolord)
        toolbar.addWidget(btn_rgb)
        
        toolbar.addStretch()
        parent_layout.addLayout(toolbar)

    def _insert_tag(self, op, cl=None):
        c = self.text_widget.textCursor(); sel = c.selectedText()
        c.insertText(op + sel + (cl or ''))
        self.text_widget.setFocus(); self._on_text_modified()

    def _on_freset_select(self, index):
        if index == 0: return
        self._insert_tag(f"<FRESET,{int(self.cb_freset.currentText().split('-')[0])}>")
        self.cb_freset.setCurrentIndex(0)

    def _insert_fcolor(self, color_idx):
        self._insert_tag(f"<FCOLOR,{color_idx}>", "<FRESET,2>")

    def _insert_fcolord(self):
        """弹出系统取色器，插入 <FCOLORD,r,g,b> 标签。"""
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        r, g, b = color.red(), color.green(), color.blue()
        self._insert_tag(f"<FCOLORD,{r},{g},{b}>", "<FRESET,2>")

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
        QMessageBox.about(self, "关于",
            "TKT.dat 文本数据库编辑器 v4.0 (PySide6)\n\n"
            "基于逆向工程 sub_401E88/sub_4067E8/sub_4019D0 实现。\n"
            "支持加载/编辑/保存/新增 TKT.dat 条目。\n\n"
            "控制码:\n"
            "  <FRESET,n>  n∈[1,4]     <FCOLOR,n>  n∈[1,32]\n"
            "  <FCOLORD,r,g,b> r,g,b∈[0,255]\n"
            "  <FSIZE,n>   n∈[12,48]   <FTYPE,n>   n∈[1,8]\n"
            "  <TEXT,n>    n∈[1,32767] (2字节)\n"
            "  <VARNUM,n>  n∈[1,255]   <VARTXT,n>  n∈[1,255]\n"
            "  <NAME,n>    n∈[1,2]")

    def closeEvent(self, event):
        if self._dirty and QMessageBox.question(self, "未保存", "直接退出？") == QMessageBox.Cancel: event.ignore(); return
        if self.font9696: self.font9696.close()
        event.accept()

def main():
    app = QApplication(sys.argv); app.setStyle("Fusion")
    editor = TktEditor(sys.argv[1] if len(sys.argv) > 1 else None)
    editor.show(); sys.exit(app.exec())

if __name__ == "__main__": main()