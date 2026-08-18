# -*- coding: utf-8 -*-
"""
二进制文件对比工具

提供:
- 字节级差异定位
- 连续差异区间合并
- E9 (JMP rel32) 指令 Hook 查找
- 文件级 IAT Hook 扫描
"""
import struct
from typing import List, Dict, Tuple, Optional


def find_diff_offsets(base: bytes, other: bytes,
                      start: int = 0, end: Optional[int] = None) -> List[int]:
    """
    找出两个缓冲区在 [start, end) 范围内的所有不同字节位置

    Args:
        base: 基础字节数据
        other: 对比字节数据
        start: 起始偏移
        end: 结束偏移, None 表示到较短文件末尾

    Returns:
        差异位置列表 (绝对偏移)
    """
    if end is None:
        end = min(len(base), len(other))
    return [i for i in range(start, end) if i < len(base) and i < len(other) and base[i] != other[i]]


def merge_diff_ranges(offsets: List[int]) -> List[Tuple[int, int]]:
    """
    将分散的差异位置合并为连续区间

    Returns:
        [(start, end), ...] 每个区间是闭区间 [start, end]
    """
    if not offsets:
        return []
    ranges = []
    s = e = offsets[0]
    for p in offsets[1:]:
        if p == e + 1:
            e = p
        else:
            ranges.append((s, e))
            s = e = p
    ranges.append((s, e))
    return ranges


def find_e9_hooks(ext_data: bytes, text_section: Dict,
                   target_section: Optional[Dict] = None) -> List[Dict]:
    """
    在 .text 节区中查找所有 E9 (JMP rel32) 指令, 并解析跳转目标

    用于检测 IAT Hook: 修改版在 .text 某位置写入了 E9 ?? ?? ?? ?? (5字节),
    跳转到目标节区 (通常是 .test) 中的 Thunk 代码

    Args:
        ext_data: 修改版文件完整数据
        text_section: .text 节区字典
        target_section: 可选, 跳转目标节区 (如 .test), 若指定则过滤目标在该节区内的 Hook

    Returns:
        list of dict:
            - rva:           Hook 位置的 RVA
            - file_offset:   Hook 位置的文件偏移
            - target_rva:    JMP 目标 RVA
            - target_in_section: 目标是否在 target_section 中
    """
    hooks = []
    text_start = text_section['raw_offset']
    text_size = text_section['raw_size']
    text_vaddr = text_section['virtual_address']

    for i in range(text_size - 4):
        file_offset = text_start + i
        if file_offset >= len(ext_data):
            break
        if ext_data[file_offset] != 0xE9:
            continue

        # 读取 4 字节相对偏移
        rel = struct.unpack_from('<i', ext_data, file_offset + 1)[0]
        target_rva = (text_vaddr + i + 5 + rel) & 0xFFFFFFFF

        target_in_section = False
        if target_section:
            ts = target_section
            target_in_section = (ts['virtual_address'] <= target_rva <
                                 ts['virtual_address'] + max(ts['virtual_size'], ts['raw_size']))

        hooks.append({
            'rva': text_vaddr + i,
            'file_offset': file_offset,
            'target_rva': target_rva,
            'target_in_section': target_in_section,
        })

    return hooks


def find_modified_to_e9(base_data: bytes, ext_data: bytes,
                        text_section: Dict) -> List[Dict]:
    """
    找出基础版 vs 修改版的所有差异, 且修改版在差异位置是 E9 指令

    Args:
        base_data: 基础版文件完整数据
        ext_data: 修改版文件完整数据
        text_section: .text 节区字典

    Returns:
        同 find_e9_hooks, 但只包含基础版原字节非 E9 的 Hook
    """
    text_start = text_section['raw_offset']
    text_size = text_section['raw_size']

    diffs = find_diff_offsets(base_data, ext_data, text_start, text_start + text_size)
    hooks = []
    for off in diffs:
        if ext_data[off] == 0xE9:
            rel = struct.unpack_from('<i', ext_data, off + 1)[0]
            target_rva = (text_section['virtual_address'] + (off - text_start) + 5 + rel) & 0xFFFFFFFF
            orig_byte = base_data[off] if off < len(base_data) else None
            hooks.append({
                'rva': text_section['virtual_address'] + (off - text_start),
                'file_offset': off,
                'target_rva': target_rva,
                'original_byte': orig_byte,
            })
    return hooks


def get_context_bytes(data: bytes, offset: int, before: int = 16,
                      after: int = 32) -> Tuple[int, bytes]:
    """
    读取指定偏移处的代码上下文

    Returns:
        (actual_start, bytes) 实际起始偏移 + 字节数据
    """
    start = max(0, offset - before)
    end = min(len(data), offset + after)
    return start, data[start:end]


def common_prefix_length(a: bytes, b: bytes) -> int:
    """两个缓冲区相同的前缀长度"""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def file_diff_summary(base_path: str, ext_path: str) -> Dict:
    """
    文件级差异汇总

    Returns:
        dict: {
            'base_size': int, 'ext_size': int,
            'common_prefix': int, 'size_diff': int,
            'diff_count_in_common': int
        }
    """
    with open(base_path, 'rb') as f:
        base = f.read()
    with open(ext_path, 'rb') as f:
        ext = f.read()

    n = min(len(base), len(ext))
    diffs = sum(1 for i in range(n) if base[i] != ext[i])

    return {
        'base_size': len(base),
        'ext_size': len(ext),
        'common_prefix': common_prefix_length(base, ext),
        'size_diff': len(ext) - len(base),
        'diff_count_in_common': diffs,
    }