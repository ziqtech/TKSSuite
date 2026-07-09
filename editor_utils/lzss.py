"""
LZSS 压缩/解压 — 统一模块 (逆向自游戏 sub_452B14 / sub_4530A8)

提供三种格式变体:
  - DAT 格式 (12字节头): TKItem/TKSkill/TKKon/WarPC/TKShop 等
  - Save 格式 (4字节头):  存档文件
  - Stream 格式 (无头):    GRP/GXP 等资源包内嵌流

所有变体共享相同的核心参数:
  窗口大小 4096, 初始填充 0x20, 起始位置 4078, 最小匹配 3, 最大匹配 18
"""
import struct

# ── 核心常量 ──
RING_SIZE = 4096
RING_INIT_VAL = 0x20
RING_INIT_POS = 4078  # FEE
MIN_MATCH = 3
MAX_MATCH = 18


# ═══════════════════════════════════════════════════════════════
# 内部: 共享解压核心
# ═══════════════════════════════════════════════════════════════

def _decompress_core(data: bytes, pos: int, total_size: int,
                     block_size: int | None = None) -> bytes:
    """共享 LZSS 解压核心 (LSB-first 标志位).

    Args:
        data: 压缩数据
        pos: 压缩流起始偏移
        total_size: 解压后大小
        block_size: 压缩块大小 (带 bc 跟踪器, DAT 格式用); None 则用 pos 边界
    """
    window = bytearray([RING_INIT_VAL] * RING_SIZE)
    wp = RING_INIT_POS
    out = bytearray()
    flags = 0
    bc = 4 if block_size is not None else 0

    while len(out) < total_size:
        if block_size is not None:
            if bc >= block_size:
                break
        elif pos >= len(data):
            break

        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1
            if block_size is not None:
                bc += 1

        if flags & 1:
            if pos >= len(data):
                break
            b = data[pos]
            pos += 1
            if block_size is not None:
                bc += 1
            out.append(b)
            window[wp] = b
            wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            b1, b2 = data[pos], data[pos + 1]
            pos += 2
            if block_size is not None:
                bc += 2
            offset = ((b2 & 0xF0) << 4) | b1
            length = (b2 & 0x0F) + 3
            for j in range(length):
                if len(out) >= total_size:
                    break
                b = window[(offset + j) & 0xFFF]
                out.append(b)
                window[wp] = b
                wp = (wp + 1) & 0xFFF

    return bytes(out[:total_size])


# ═══════════════════════════════════════════════════════════════
# 内部: 共享压缩核心 (rfind 优化版)
# ═══════════════════════════════════════════════════════════════

def _compress_core(data: bytes) -> list[tuple[bool, int, int]]:
    """共享 LZSS 压缩核心 — 使用 bytes.rfind 优化.

    返回 token 列表: [(is_literal, value/offset, length), ...]
    """
    src = data
    sl = len(src)
    flat = bytes(bytearray([RING_INIT_VAL] * RING_SIZE) + src)
    tokens: list[tuple[bool, int, int]] = []
    pos = 0

    while pos < sl:
        curr = RING_SIZE + pos
        ms = min(MAX_MATCH, sl - pos)
        best_len, best_off = 0, 0

        if ms >= MIN_MATCH:
            for length in range(ms, MIN_MATCH - 1, -1):
                pat = flat[curr:curr + length]
                end_idx = curr + length - 1
                start_idx = max(0, curr - RING_SIZE)
                idx = flat.rfind(pat, start_idx, end_idx)
                if idx != -1:
                    best_len = length
                    best_off = (idx - 18) & 0xFFF
                    break

        if best_len >= MIN_MATCH:
            tokens.append((False, best_off, best_len))
            pos += best_len
        else:
            tokens.append((True, src[pos], 0))
            pos += 1

    return tokens


def _tokens_to_stream(tokens: list[tuple[bool, int, int]]) -> bytes:
    """将 token 列表编码为 LZSS 比特流."""
    stream = bytearray()
    ti = 0
    while ti < len(tokens):
        fb = 0
        be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]:
                fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]:
                stream.append(tokens[i][1])
            else:
                off, length = tokens[i][1], tokens[i][2]
                el = length - 3
                stream.append(off & 0xFF)
                stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    return bytes(stream)


# ═══════════════════════════════════════════════════════════════
# 公开 API — DAT 格式 (12字节头: [ts][bs][ts][stream])
# ═══════════════════════════════════════════════════════════════

def lzss_decompress_dat(data: bytes) -> bytes:
    """解压 DAT 文件 (TKItem/TKSkill/TKKon/WarPC/TKShop).
    格式: [4B total_size][4B block_size][4B total_size][LZSS stream]
    """
    if len(data) < 12:
        return b''
    ts = struct.unpack_from('<I', data, 0)[0]
    bs = struct.unpack_from('<I', data, 4)[0]
    return _decompress_core(data, 12, ts, bs)


def lzss_compress_dat(data: bytes) -> bytes:
    """压缩为 DAT 文件格式.
    返回: [4B total_size][4B block_size][4B total_size][LZSS stream]
    """
    tokens = _compress_core(data)
    stream = _tokens_to_stream(tokens)
    ds = len(data)
    bd = struct.pack('<I', ds) + stream
    return struct.pack('<II', ds, len(bd)) + bd


# ═══════════════════════════════════════════════════════════════
# 公开 API — Save 格式 (4字节头: [ts][stream])
# ═══════════════════════════════════════════════════════════════

def lzss_decompress_save(data: bytes) -> bytes:
    """解压 SaveBufLZSS 块.
    格式: [4B total_size][LZSS stream]
    """
    if len(data) < 4:
        return b''
    ts = struct.unpack_from('<I', data, 0)[0]
    return _decompress_core(data, 4, ts)


def lzss_compress_save(data: bytes) -> bytes:
    """压缩为 SaveBufLZSS 块.
    返回: [4B total_size][LZSS stream]
    """
    tokens = _compress_core(data)
    stream = _tokens_to_stream(tokens)
    return struct.pack('<I', len(data)) + stream


# ═══════════════════════════════════════════════════════════════
# 公开 API — Stream 格式 (无头, 调用者管理 total_size)
# ═══════════════════════════════════════════════════════════════

def lzss_decompress_stream(data: bytes, target_size: int) -> bytes:
    """解压裸 LZSS 流 (GRP/GXP 等资源包内嵌).
    target_size 由调用者从文件头提供.
    """
    if not data or target_size <= 0:
        return b''
    return _decompress_core(data, 0, target_size)


def lzss_compress_stream(data: bytes) -> bytes:
    """压缩为裸 LZSS 流 (无头). 使用哈希链表优化 (O(n))."""
    n = len(data)
    if n == 0:
        return b''

    # 哈希链表索引
    hh, hn = [-1] * 4096, [-1] * n
    for i in range(n - 1, -1, -1):
        if i + 1 < n:
            h = ((data[i] << 8) | data[i + 1]) & 0xFFF
            hn[i] = hh[h]
            hh[h] = i

    buf, entries = bytearray(), []

    def flush():
        if not entries:
            return
        flag = 0
        for i, (is_lit, _) in enumerate(entries):
            if is_lit:
                flag |= (1 << i)
        buf.append(flag)
        for _, d in entries:
            buf.extend(d)
        entries.clear()

    pos = 0
    while pos < n:
        bl, bo = 0, 0
        if n - pos >= 2:
            chain = hh[((data[pos] << 8) | data[pos + 1]) & 0xFFF]
            steps = 0
            while chain >= 0 and steps < 64:
                if pos - chain > RING_SIZE:
                    break
                if chain < pos:
                    ml = 0
                    while (ml < min(n - pos, MAX_MATCH) and
                           data[chain + ml] == data[pos + ml]):
                        ml += 1
                    if ml > bl:
                        bl, bo = ml, pos - chain
                    if ml == MAX_MATCH:
                        break
                chain = hn[chain]
                steps += 1

        if bl >= MIN_MATCH:
            rp = (RING_INIT_POS + pos) % RING_SIZE
            ao = (rp - bo) % RING_SIZE
            enc = bytes([ao & 0xFF, ((ao >> 4) & 0xF0) | ((bl - 3) & 0x0F)])
            entries.append((False, enc))
            pos += bl
        else:
            entries.append((True, bytes([data[pos]])))
            pos += 1

        if len(entries) >= 8:
            flush()
    flush()
    return bytes(buf)
