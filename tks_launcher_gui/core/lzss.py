"""LZSS 压缩/解压 — 与游戏 sub_452B14 配对, 从 tks_launcher.py 提取"""
from typing import Dict, List
from .memory import b2i32, i32b

def lzss_decompress(data: bytes) -> bytes:
    """最小化 LZSS 解压 (匹配 sub_452B14)"""
    if len(data) < 12:
        return b''
    total_size = b2i32(data, 0)
    block_size = b2i32(data, 4)
    window = bytearray([0x20] * 4096)
    wp = 4078
    output = bytearray(total_size)
    flags, pos, bc, out_pos = 0, 12, 4, 0

    while bc < block_size and out_pos < total_size:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1; bc += 1
        if (flags & 1) != 0:
            if pos >= len(data):
                break
            b = data[pos]; pos += 1; bc += 1
            output[out_pos] = b; out_pos += 1
            window[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            b1, b2 = data[pos], data[pos+1]
            pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1
            rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                if out_pos >= total_size:
                    break
                b = window[(j + ro) & 0xFFF]
                output[out_pos] = b; out_pos += 1
                window[wp] = b; wp = (wp + 1) & 0xFFF

    return bytes(output[:total_size])

def lzss_compress(data: bytes) -> bytes:
    """LZSS 压缩(优化版: 哈希表 O(n)) — 与游戏 sub_452B14 配对, 用于截断文件生成"""
    sl = len(data)
    hf: List[int] = []
    td: List[int] = []
    pos = 0
    ht: Dict[int, int] = {}

    while pos < sl:
        ms = min(18, sl - pos)
        blen, boff = 0, 0
        if ms >= 3 and pos >= 3:
            hk = (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
            prev = ht.get(hk, -1)
            if prev >= 0 and pos - prev <= 4096:
                ml = 0
                while (ml < ms and data[prev + ml] == data[pos + ml]):
                    ml += 1
                if ml >= 3:
                    blen = ml
                    boff = prev
        if pos + 2 < sl:
            hk = (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
            ht[hk] = pos
        if blen >= 3:
            flat_off = boff + 4096
            bo = (flat_off - 18) & 0xFFF
            hf.append(0)
            td.append(bo & 0xFF)
            td.append(((bo >> 4) & 0xF0) | ((blen - 3) & 0x0F))
            for j in range(1, blen):
                if pos + j + 2 < sl:
                    hk = (data[pos + j] << 16) | (data[pos + j + 1] << 8) | data[pos + j + 2]
                    ht[hk] = pos + j
            pos += blen
        else:
            hf.append(1)
            td.append(data[pos])
            pos += 1

    stream: List[int] = []
    hi, tp = 0, 0
    while hi < len(hf):
        fb, be = 0, min(hi + 8, len(hf))
        for i in range(hi, be):
            if hf[i]: fb |= (1 << (i - hi))
        stream.append(fb)
        for i in range(hi, be):
            if hf[i]:
                stream.append(td[tp]); tp += 1
            else:
                stream.append(td[tp]); stream.append(td[tp+1]); tp += 2
        hi = be

    lzss_block = bytearray(4 + len(stream))
    lzss_block[0:4] = i32b(sl)
    lzss_block[4:] = bytes(stream)

    result = bytearray(8 + len(lzss_block))
    result[0:4] = i32b(sl)
    result[4:8] = i32b(len(lzss_block))
    result[8:] = lzss_block

    # 自验证
    test_dec = lzss_decompress(bytes(result))
    if len(test_dec) != sl:
        raise IOError(f"LZSS 压缩回写验证失败: 长度 {len(test_dec)} != {sl}")
    for i in range(sl):
        if test_dec[i] != data[i]:
            raise IOError(f"LZSS 压缩回写验证失败: 偏移 {i} 不匹配")

    return bytes(result)
