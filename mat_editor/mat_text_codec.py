# -*- coding: utf-8 -*-
"""mat_editor_v2 文本编解码层 — TKT 字节流解码 / TKD 脚本读写与 DEFINE 解析。
从 mat_editor_v2.py 原样迁出, 无业务逻辑 (§工程化拆分)。"""
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mat_constants import _CONTROL_TAGS, _LINE_SEP, DEFAULT_TKT_FCOLOR, GAME_COLORS


def decode_tkt_bytes(data):
    """将原始 TKT 字节流解码为含 <TAG,n> 标记的 UTF 文本。
    依据 tkt_editor.py decode_line() — 控制字节 → <TAG,n>, Big5 → UTF"""
    out = []
    buf = bytearray()
    i, n = 0, len(data)
    def flush():
        if buf:
            try: out.append(buf.decode('big5', errors='replace'))
            except: out.append(buf.decode('gbk', errors='replace'))
            buf.clear()
    while i < n:
        b = data[i]
        if b in _CONTROL_TAGS:
            tag_name, dlen = _CONTROL_TAGS[b]
            if i + dlen < n:
                flush()
                if dlen == 1:
                    out.append(f'<{tag_name},{data[i+1]}>')
                elif dlen == 2:
                    val = data[i+1] | (data[i+2] << 8)
                    out.append(f'<{tag_name},{val}>')
                else:  # dlen==3: FCOLORD
                    out.append(f'<{tag_name},{data[i+1]},{data[i+2]},{data[i+3]}>')
                i += 1 + dlen
                continue
        if b == _LINE_SEP:
            flush()
            out.append('\n')
            i += 1
            continue
        if b < 0x20:
            flush()
            out.append(f'<RAW,0x{b:02X}>')
            i += 1
            continue
        if b >= 0x80 and i + 1 < n:
            buf.append(b)
            buf.append(data[i+1])
            i += 2
        else:
            buf.append(b)
            i += 1
    flush()
    return ''.join(out)

_TKT_TAG_RE = re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')

def parse_tkt_colored_segments(text):
    """将含 <FCOLOR,n>/<FCOLORD,r,g,b>/<FRESET,n> 的 TKT 文本解析为 [(text, color_hex), ...]。
    忽略字体控制标签 (FSIZE/FTYPE/NAME 等), 只处理颜色。"""
    segments = []
    cur_color = DEFAULT_TKT_FCOLOR
    prev_color = cur_color
    buf = []
    i, n = 0, len(text)

    def flush():
        if buf:
            segments.append((''.join(buf), cur_color))
            buf.clear()

    while i < n:
        m = _TKT_TAG_RE.match(text, i)
        if m:
            flush()
            tag_name = m.group(1)
            val_str = m.group(2)
            if tag_name == 'FCOLOR':
                try:
                    val = int(val_str)
                    if 1 <= val <= 32:
                        prev_color = cur_color
                        cur_color = GAME_COLORS[val]
                except ValueError: pass
            elif tag_name == 'FCOLORD':
                parts = val_str.split(',')
                if len(parts) == 3:
                    try:
                        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                            prev_color = cur_color
                            cur_color = f'#{r:02X}{g:02X}{b:02X}'
                    except ValueError: pass
            elif tag_name == 'FRESET':
                try:
                    val = int(val_str)
                    if val == 1:
                        cur_color = DEFAULT_TKT_FCOLOR
                    elif val == 2:
                        cur_color = prev_color
                except ValueError: pass
            # 其他标签 (TEXT/VARNUM/VARTXT/NAME/FSIZE/FTYPE) 作为文本保留
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

class TktLazyDict:
    """延迟解析 TKT 文本：只在第一次用到某条文本时才执行耗时的 decode_tkt_bytes"""
    def __init__(self, raw_dict):
        self.raw = raw_dict
        self.cache = {}

    def get(self, eid, default=''):
        if eid in self.cache:
            return self.cache[eid]
        if eid in self.raw:
            txt = decode_tkt_bytes(self.raw[eid])
            self.cache[eid] = txt
            return txt
        return default

    def __getitem__(self, eid):
        return self.get(eid, '')

    def __contains__(self, eid):
        return eid in self.raw

def load_tkt_raw(tkt_path):
    """仅提取字节流块 — 委托给 editor_utils.tkt_loader"""
    from editor_utils.tkt_loader import load_tkt_raw as _load
    return _load(tkt_path)

# TKD.dat 脚本 I/O (来自 script_editor.py)
# ============================================================

_TKT_XOR_TABLE = bytes([i ^ 0xFF for i in range(256)])  # XOR 密钥表, load_tkd/save_tkd 用

def load_tkd(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    decoded = data.translate(_TKT_XOR_TABLE)
    try:
        text = decoded.decode('big5', errors='replace')
    except Exception:
        text = decoded.decode('gbk', errors='replace')
    return text

def save_tkd(filepath, text):
    try:
        encoded = text.encode('big5')
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = text.encode('gbk', errors='replace')
    encrypted = encoded.translate(_TKT_XOR_TABLE)
    with open(filepath, 'wb') as f:
        f.write(encrypted)

def parse_defines(text):
    lines = text.split('\n')
    defines = []
    current = None
    header_lines = []
    pending_prefix = []
    seen_first_define = False
    for i, line in enumerate(lines):
        raw_line = line.rstrip('\r')
        stripped = raw_line.strip()
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            define_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if not seen_first_define: seen_first_define = True
            current = {'define_id': define_id, 'comment': '',
                       'prefix_lines': list(pending_prefix), 'body_lines': [],
                       'line_start': i, 'line_end': -1, 'header_line': raw_line}
            pending_prefix = []
        elif stripped.startswith('};') and current is not None:
            current['line_end'] = i
            current['comment'] = stripped[2:].replace(' end', '').strip()
            current['body_lines'].append(raw_line)
            defines.append(current)
            current = None
        elif current is not None:
            current['body_lines'].append(raw_line)
        else:
            if not seen_first_define and stripped and not stripped.startswith('//'):
                header_lines.append(raw_line)
            elif not seen_first_define and stripped.startswith('////'):
                header_lines.append(raw_line)
            else:
                pending_prefix.append(raw_line)
    return defines, '\n'.join(header_lines)

def rebuild_text(defines, header):
    parts = []
    if header:
        for hl in header.split('\n'): parts.append(hl)
    for d in defines:
        for pl in d.get('prefix_lines', []): parts.append(pl)
        parts.append(d['header_line'])
        for bl in d['body_lines']: parts.append(bl)
    parts.append('')
    parts.append('')
    return '\r\n'.join(parts)
