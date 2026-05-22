#!/usr/bin/env python3
"""验证修复后的 SEG2 字段解析"""
import sys, os, struct

sys.path.insert(0, os.path.dirname(__file__))
from save_editor import load_save_data, SEG2_CORE_FIELDS

def verify(save_path):
    print(f"=== 修复验证: {save_path} ===")
    gs, seg1, seg2, seg3 = load_save_data(save_path)

    print(f"\nSEG2 队伍/经济字段 (修复后):")
    for key, off, size, label, fmt, cmt in SEG2_CORE_FIELDS:
        val = struct.unpack_from('<' + fmt, seg2, off)[0]
        print(f"  {label} @ +0x{off:04X} ({fmt}×{size}): {val}")

    # 团队
    print(f"\n团队 (word_75688C):")
    for i in range(6):
        tid = struct.unpack_from('<h', seg2, 0x0C + i*2)[0]
        print(f"  member[{i}]: {tid}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <sav.N 文件路径>")
        sys.exit(1)
    verify(sys.argv[1])
