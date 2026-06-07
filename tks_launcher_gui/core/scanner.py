"""模式扫描引擎 — 从 tks_launcher.py 提取"""
from typing import List, Tuple, Dict
from .memory import i32b, b2i32

def parse_pattern(hex_str: str) -> Tuple[bytes, List[bool]]:
    parts = hex_str.split()
    pat = bytearray(len(parts))
    wc = [False] * len(parts)
    for i, p in enumerate(parts):
        if p in ('**', '??'):
            pat[i] = 0
            wc[i] = True
        else:
            pat[i] = int(p, 16)
    return bytes(pat), wc

def pattern_scan(data: bytes, pattern: bytes, wildcard: List[bool]) -> List[int]:
    """模式扫描(优化版): 用 bytes.find 定位首个非通配字节, 再验证完整模式"""
    results = []
    if not pattern or len(data) < len(pattern):
        return results
    pl = len(pattern)
    end = len(data) - pl
    anchor_idx = -1
    for j in range(pl):
        if not wildcard[j]:
            anchor_idx = j
            break
    if anchor_idx < 0:
        return list(range(end + 1))
    anchor_byte = pattern[anchor_idx:anchor_idx + 1]
    pos = 0
    while pos <= end:
        pos = data.find(anchor_byte, pos)
        if pos == -1 or pos > end:
            break
        start = pos - anchor_idx
        if start < 0:
            pos += 1
            continue
        match = True
        for j in range(pl):
            if not wildcard[j] and data[start + j] != pattern[j]:
                match = False
                break
        if match:
            results.append(start)
            pos = start + pl
        else:
            pos += 1
    return results

def value_scan(data: bytes, value: int) -> List[int]:
    """在字节数组中扫描指定 4 字节 LE 值"""
    results = []
    target = i32b(value)
    pos = 0
    end = len(data) - 4
    first = target[0:1]
    while pos <= end:
        pos = data.find(first, pos)
        if pos == -1 or pos > end:
            break
        if data[pos:pos + 4] == target:
            results.append(pos)
            pos += 4
        else:
            pos += 1
    return results

def discover_warpc_base(code_buf: bytes, code_start_addr: int, fallback: int,
                         log_func=None) -> int:
    """
    自动发现 WarPC BSS 基址
    原理: 扫描代码中 150722 (0x24CE2) 的出现, 回溯找附近 BSS 地址
    """
    WARPC_ORIG_SIZE = 150722
    log = log_func or (lambda x: None)

    log("\n--- WarPC BSS 基址自动发现 ---")
    size_hits = value_scan(code_buf, WARPC_ORIG_SIZE)
    log(f"  扫描 150722 (0x{WARPC_ORIG_SIZE:X}): 找到 {len(size_hits)} 处")
    for off in size_hits:
        log(f"    偏移 0x{off:X} (abs 0x{code_start_addr + off:08X})")

    if not size_hits:
        log(f"  [WARN] 未找到 150722, 使用 fallback 0x{fallback:X}")
        return fallback

    candidates: Dict[int, int] = {}
    for off in size_hits:
        for i in range(max(0, off - 24), min(len(code_buf) - 4, off + 8) + 1):
            val = b2i32(code_buf, i)
            if 0x700000 <= val < 0x800000 and (val & 3) == 0 and val != WARPC_ORIG_SIZE:
                candidates[val] = candidates.get(val, 0) + 1

    best_val, best_cnt = fallback, 0
    for v, c in candidates.items():
        log(f"  候选 0x{v:08X}: 出现 {c} 次")
        if c > best_cnt:
            best_val, best_cnt = v, c

    if best_cnt > 0:
        log(f"  发现 WarPC 基址: 0x{best_val:08X} (出现 {best_cnt} 次)")
    else:
        log(f"  [WARN] 未找到候选, 使用 fallback 0x{fallback:X}")
    return best_val
