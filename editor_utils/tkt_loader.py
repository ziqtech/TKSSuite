"""
TKT.dat 文本数据库加载器 — 统一模块

提供三种加载模式:
  - load_tkt_simple:  轻量级 {id: text} 字典 (供 warpc/wardata/skill/kon/item/save 使用)
  - load_tkt_full:    完整解析含控制标签 (供 tkt_editor 使用)
  - load_tkt_raw:     原始字节块 (供 mat_editor 使用, 自行解析)

文件格式 (sub_45343C 加载):
  [4B total_size][4B record_count][XOR 0xFF 加密的文本数据块]
  文本数据块: [id_table(4B×N)][offset_table(4B×N)][text_data...]
"""
import os
import struct
from collections import OrderedDict

# ── 格式常量 ──
HDR_SIZE = 8
XOR_KEY = 0xFF
ENTRY_TERMINATOR = 0x00
LINE_SEPARATOR = 0x1E

# C 级 XOR 映射表: bytes.translate 用 (比逐字节循环快)
_XOR_TABLE = bytes([i ^ XOR_KEY for i in range(256)])

# ── 控制标签映射 (从 tkt_editor_v5 验证) ──
# 格式: {byte_code: (tag_name, data_len, min_val, max_val)}
_CONTROL_TAGS: dict[int, tuple[str, int, int, int]] = {
    0x01: ("FRESET",  1, 1, 4),
    0x02: ("FCOLOR",  1, 1, 32),
    0x04: ("FSIZE",   1, 12, 48),
    0x05: ("FTYPE",   1, 1, 8),
    0x14: ("TEXT",    2, 1, 32767),
    0x15: ("VARNUM",  1, 1, 255),
    0x16: ("VARTXT",  1, 1, 255),
    0x1D: ("NAME",    1, 1, 2),
}

# 反向查找: tag_name → byte_code
_TAG_BY_NAME: dict[str, int] = {v[0]: k for k, v in _CONTROL_TAGS.items()}


# ═══════════════════════════════════════════════════════════════
# 轻量级加载: {id: text} 字典
# ═══════════════════════════════════════════════════════════════

def load_tkt_simple(tkt_path: str, *,
                    skip_range: tuple[int, int] | None = (0, 10),
                    first_line_only: bool = False,
                    full_strip: bool = False) -> dict[int, str]:
    """加载 TKT.dat 为 {entry_id: text} 字典 (仅 Big5 解码, 无控制标签).

    Args:
        tkt_path: TKT.dat 文件路径
        skip_range: 跳过的 ID 范围 (start, end), None 不跳过. 默认跳过 0-9
        first_line_only: True 仅取第一行 (.split('\\n')[0].strip())
        full_strip: True 对完整文本做 .strip()
    """
    if not tkt_path or not os.path.exists(tkt_path):
        return {}

    with open(tkt_path, 'rb') as f:
        raw = f.read()

    if len(raw) < HDR_SIZE:
        return {}

    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]

    # XOR 解密
    enc = raw[HDR_SIZE:HDR_SIZE + ts]
    dec = enc.translate(_XOR_TABLE)

    idsz = cnt * 4
    lookup: dict[int, str] = {}

    skip_set: set[int] = set()
    if skip_range is not None:
        skip_set = set(range(skip_range[0], skip_range[1]))

    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        if eid in skip_set:
            continue
        off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
        ao = idsz * 2 + off
        if ao >= len(dec):
            continue

        # 扫描到 0x00 终止符
        end = ao
        while end < len(dec) and dec[end] != ENTRY_TERMINATOR:
            end += 1
        txt = dec[ao:end].replace(b'\x1e', b'\n')

        # Big5 解码
        try:
            s = txt.decode('big5', errors='replace')
        except Exception:
            s = txt.decode('gbk', errors='replace')

        if not s or s == '0':
            continue

        if first_line_only:
            s = s.split('\n')[0].strip()
        elif full_strip:
            s = s.strip()

        lookup[eid] = s

    return lookup


# ═══════════════════════════════════════════════════════════════
# 原始字节加载: {id: bytes} 字典
# ═══════════════════════════════════════════════════════════════

def load_tkt_raw(tkt_path: str) -> dict[int, bytes]:
    """加载 TKT.dat 为 {entry_id: raw_bytes} 字典 (不做文本解码).

    供 mat_editor 使用, 由其自行进行控制标签解析和渲染.
    """
    if not tkt_path or not os.path.exists(tkt_path):
        return {}

    with open(tkt_path, 'rb') as f:
        raw = f.read()

    if len(raw) < HDR_SIZE:
        return {}

    total_size, count = struct.unpack_from('<II', raw, 0)
    dec = raw[HDR_SIZE:HDR_SIZE + total_size].translate(_XOR_TABLE)

    id_sz = count * 4
    tb = id_sz * 2
    lookup: dict[int, bytes] = {}

    actual_count = min(count, (len(dec) - id_sz) // 4)
    if actual_count <= 0:
        return lookup

    # 批量 unpack ID 和偏移量
    ids = struct.unpack_from('<' + 'i' * actual_count, dec, 0)
    offs = struct.unpack_from('<' + 'I' * actual_count, dec, id_sz)

    for eid, off in zip(ids, offs):
        ao = tb + off
        if ao >= len(dec):
            continue
        end = dec.find(b'\x00', ao)
        if end == -1:
            end = len(dec)
        lookup[eid] = dec[ao:end]

    return lookup


# ═══════════════════════════════════════════════════════════════
# 完整解析: 含控制标签解码 (tkt_editor 家族)
# ═══════════════════════════════════════════════════════════════

def _decode_line(line_bytes: bytes) -> str:
    """解码一行 TKT 文本 (与 tkt_editor_v5 兼容).
    将控制字节转换为 <TAG,val> 标记, 支持 1/2 字节参数.
    """
    out: list[str] = []
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
        if b in _CONTROL_TAGS:
            tag_name, data_len, _, _ = _CONTROL_TAGS[b]
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


def load_tkt_full(tkt_path: str) -> list[OrderedDict]:
    """加载 TKT.dat 为完整条目列表 (含控制标签解析).

    返回: [OrderedDict([('slot', i), ('id', entry_id), ('text', text)]), ...]
    """
    if not tkt_path or not os.path.exists(tkt_path):
        return []

    with open(tkt_path, 'rb') as f:
        raw = f.read()

    if len(raw) < HDR_SIZE:
        return []

    total_size = struct.unpack_from('<I', raw, 0)[0]
    record_count = struct.unpack_from('<I', raw, 4)[0]

    encrypted = raw[HDR_SIZE:HDR_SIZE + total_size]
    decrypted = bytes(b ^ XOR_KEY for b in encrypted)

    id_table_size = 4 * record_count
    offset_table_size = 4 * record_count
    text_base = id_table_size + offset_table_size

    entries: list[OrderedDict] = []
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
        decoded_lines = [_decode_line(ln) for ln in raw_lines]
        text = '\n'.join(decoded_lines)
        entries.append(OrderedDict([('slot', i), ('id', entry_id), ('text', text)]))

    return entries
