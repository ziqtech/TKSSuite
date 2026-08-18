# -*- coding: utf-8 -*-
"""
报告格式化输出工具

提供:
- 十六进制+ASCII 转储 (类似 xxd / hexdump)
- 节区信息表格
- Hook 列表表格
- 代码上下文对比 (原版 vs 修改版)
"""
from typing import List, Dict, Tuple, Optional


def hex_dump(data: bytes, base_offset: int = 0,
             bytes_per_line: int = 16,
             max_lines: Optional[int] = None) -> str:
    """
    格式化的十六进制+ASCII 转储

    Args:
        data: 字节数据
        base_offset: 起始偏移 (用于显示)
        bytes_per_line: 每行字节数 (默认 16)
        max_lines: 最多显示的行数, None 表示全部

    Returns:
        多行字符串, 每行格式: "OFFSET  HEX (48 chars)  ASCII"
    """
    lines = []
    n = len(data)
    line_count = (n + bytes_per_line - 1) // bytes_per_line
    if max_lines is not None:
        line_count = min(line_count, max_lines)

    for line_idx in range(line_count):
        offset = line_idx * bytes_per_line
        chunk = data[offset:offset + bytes_per_line]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        # 补齐到固定宽度
        hex_str = f'{hex_str:<{bytes_per_line * 3 - 1}}'
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{base_offset + offset:08X}: {hex_str}  {ascii_str}')

    return '\n'.join(lines)


def print_section_table(sections: List[Dict]) -> str:
    """
    格式化输出节区表 (类似 dumpbin /headers)

    Returns:
        多行字符串
    """
    lines = []
    header = (f"{'#':<3} {'Name':<12} {'VirtAddr':>10} {'VirtSize':>10} "
              f"{'RawOffset':>12} {'RawSize':>10} {'Chars':<10}")
    lines.append(header)
    lines.append('-' * len(header))
    for i, sec in enumerate(sections):
        chars_short = format_characteristics_short(sec['characteristics'])
        lines.append(
            f"{i+1:<3} {sec['name']:<12} "
            f"0x{sec['virtual_address']:08X} "
            f"{sec['virtual_size']:>10,} "
            f"0x{sec['raw_offset']:08X} "
            f"{sec['raw_size']:>10,} "
            f"0x{sec['characteristics']:08X}"
        )
    return '\n'.join(lines)


def format_characteristics_short(flags: int) -> str:
    """返回简短特性标记 (CODE/DATA/EXEC/READ/WRITE)"""
    parts = []
    if flags & 0x40000000: parts.append('R')
    if flags & 0x80000000: parts.append('W')
    if flags & 0x20000000: parts.append('X')
    if flags & 0x00000020: parts.append('C')
    elif flags & 0x00000040: parts.append('D')
    elif flags & 0x00000080: parts.append('U')
    return ''.join(parts)


def print_hook_list(hooks: List[Dict], target_section_name: str = '.test') -> str:
    """
    格式化输出 Hook 列表

    Returns:
        多行字符串, 格式: "RVA  -> Target RVA  (in target section?)"
    """
    lines = [f"Found {len(hooks)} Hooks:"]
    lines.append(f"{'RVA':<12} {'Target':<12} {'In ' + target_section_name:<10} {'Original':<10}")
    lines.append('-' * 50)
    for h in hooks:
        in_target = h.get('target_in_section', False)
        orig = h.get('original_byte')
        orig_s = f'0x{orig:02X}' if orig is not None else 'N/A'
        lines.append(
            f"0x{h['rva']:08X}  0x{h['target_rva']:08X}  "
            f"{'YES' if in_target else 'NO':<10}  {orig_s:<10}"
        )
    return '\n'.join(lines)


def diff_context(base: bytes, ext: bytes, hook_offset: int,
                 before: int = 16, after: int = 32) -> str:
    """
    对比显示 Hook 处的基础版与修改版字节

    Args:
        base: 基础版数据
        ext: 修改版数据
        hook_offset: Hook 位置的文件偏移
        before: 之前字节数
        after: 之后字节数

    Returns:
        多行字符串, 包含 [BEFORE]/[AFTER] 标记
    """
    start = max(0, hook_offset - before)
    end = min(len(base), len(ext), hook_offset + after)

    base_chunk = base[start:end]
    ext_chunk = ext[start:end]

    out = []
    out.append(f"--- Context at 0x{hook_offset:08X} ---")
    out.append(f"BASE  [{start:08X}..{end:08X}]:")
    out.append(hex_dump(base_chunk, base_offset=start))
    out.append(f"MODIFIED [{start:08X}..{end:08X}]:")
    out.append(hex_dump(ext_chunk, base_offset=start))
    out.append("")

    # 标记差异字节
    diffs = [i for i in range(len(base_chunk)) if base_chunk[i] != ext_chunk[i]]
    if diffs:
        out.append(f"DIFFS: {len(diffs)} byte(s) differ at offsets: "
                  + ', '.join(f'0x{start + d:08X}' for d in diffs))

    return '\n'.join(out)


def format_jump_list(jumps: List[Dict], limit: Optional[int] = None) -> str:
    """格式化跳转指令列表"""
    shown = jumps[:limit] if limit else jumps
    lines = [f"{'Type':<5} {'Addr':<12} {'Target':<12}",
             '-' * 30]
    for j in shown:
        lines.append(f"{j['type']:<5} 0x{j['addr']:08X}  0x{j['target']:08X}")
    if limit and len(jumps) > limit:
        lines.append(f"... and {len(jumps) - limit} more")
    return '\n'.join(lines)