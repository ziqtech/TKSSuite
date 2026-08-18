# -*- coding: utf-8 -*-
"""
二进制数据中的字符串提取工具

支持:
- ASCII 字符串 (32-126 可打印字符)
- GBK 中文字符串 (0x81-0xFE 起始字节)
- 通用可读字符串 (ASCII + GBK 混合)
"""
from typing import List, Tuple


def extract_ascii_strings(data: bytes, min_len: int = 4) -> List[str]:
    """
    提取可打印 ASCII 字符串 (32 <= byte < 127)

    Args:
        data: 输入字节数据
        min_len: 最小字符串长度, 短于此长度的字符串将被过滤

    Returns:
        字符串列表
    """
    strings = []
    current = []
    for b in data:
        if 32 <= b < 127:
            current.append(chr(b))
        else:
            if len(current) >= min_len:
                strings.append(''.join(current))
            current = []
    if len(current) >= min_len:
        strings.append(''.join(current))
    return strings


def extract_gbk_strings(data: bytes, min_chars: int = 2) -> List[Tuple[int, str]]:
    """
    提取 GBK 编码的中文字符串

    Args:
        data: 输入字节数据
        min_chars: 最少字符数

    Returns:
        [(offset, string), ...] offset 是该字符串在 data 中的起始位置
    """
    results = []
    i = 0
    while i < len(data) - 1:
        # GBK 第一字节范围 0x81-0xFE
        if 0x81 <= data[i] <= 0xFE:
            # 第二字节范围 0x40-0xFE (跳过 0x7F)
            if 0x40 <= data[i + 1] <= 0xFE and data[i + 1] != 0x7F:
                # 找连续的中文字符序列
                end = i + 2
                while end < len(data) - 1:
                    if 0x81 <= data[end] <= 0xFE and 0x40 <= data[end + 1] <= 0xFE and data[end + 1] != 0x7F:
                        end += 2
                    else:
                        break
                try:
                    text = data[i:end].decode('gbk', errors='ignore')
                    if len(text) >= min_chars and any('\u4e00' <= c <= '\u9fff' for c in text):
                        results.append((i, text))
                except Exception:
                    pass
                i = end
                continue
        i += 1
    return results


def extract_readable_strings(data: bytes, min_len: int = 3) -> List[str]:
    """
    提取所有可读字符串 (ASCII + GBK)

    比 extract_ascii_strings 更宽松, 包括 GBK 字节范围
    """
    strings = []
    current = []
    for b in data:
        if 32 <= b < 127:
            current.append(chr(b))
        elif b >= 0xA1:  # GBK 起始字节范围
            current.append(chr(b))
        else:
            if len(current) >= min_len:
                strings.append(''.join(current))
            current = []
    if len(current) >= min_len:
        strings.append(''.join(current))
    return strings


def extract_c_style_strings(data: bytes, min_len: int = 4) -> List[Tuple[int, str]]:
    """
    提取 C 风格以 \\0 结尾的字符串

    Returns:
        [(offset, string), ...]
    """
    results = []
    i = 0
    while i < len(data):
        if 32 <= data[i] < 127:
            end = i
            while end < len(data) and data[end] != 0:
                end += 1
            if end > i and end - i >= min_len:
                try:
                    s = data[i:end].decode('ascii', errors='replace')
                    results.append((i, s))
                except Exception:
                    pass
            i = end + 1
        else:
            i += 1
    return results


def count_non_zero(data: bytes) -> int:
    """统计非零字节数"""
    return sum(1 for b in data if b != 0)


def count_byte(data: bytes, byte_value: int) -> int:
    """统计指定字节值的出现次数"""
    return data.count(byte_value)