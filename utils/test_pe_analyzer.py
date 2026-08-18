# -*- coding: utf-8 -*-
"""
测试 pe_analyzer 工具模块
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from utils import pe_utils, string_utils, disasm_utils
from utils import binary_diff, report_utils


def test_pe_utils():
    print("=" * 60)
    print("Test 1: pe_utils")
    print("=" * 60)
    exe_path = r"MOD文档/exe比对\TKS-颠动沧溟强化版2.0.exe"
    p = Path(exe_path)
    if not p.exists():
        print(f"  [SKIP] File not found: {exe_path}")
        return
    with open(p, 'rb') as f:
        data = f.read()
    sections = pe_utils.read_pe_sections(data)
    print(f"  Sections found: {len(sections)}")
    for sec in sections:
        print(f"    {report_utils.format_characteristics_short(sec['characteristics']):<5} "
              f"{sec['name']:<12} VAddr=0x{sec['virtual_address']:08X} Size={sec['raw_size']:,}")

    test_sec = pe_utils.find_section(sections, '.test')
    if test_sec:
        print(f"  .test section: 0x{test_sec['virtual_address']:08X}, {test_sec['raw_size']:,} bytes")

    entry_rva, entry_off = pe_utils.get_entry_point(data)
    print(f"  Entry: RVA=0x{entry_rva:08X}, FileOff=0x{entry_off:08X}")

    image_base = pe_utils.get_image_base(data)
    print(f"  ImageBase: 0x{image_base:08X}")
    print()


def test_string_utils():
    print("=" * 60)
    print("Test 2: string_utils")
    print("=" * 60)
    exe_path = r"MOD文档/exe比对\TKS-颠动沧溟强化版2.0.exe"
    p = Path(exe_path)
    if not p.exists():
        print(f"  [SKIP] File not found")
        return
    with open(p, 'rb') as f:
        data = f.read()
    sections = pe_utils.read_pe_sections(data)
    newdata = pe_utils.find_section(sections, '.Newdata')
    if not newdata:
        print(f"  [SKIP] .Newdata not found")
        return
    sec_data = pe_utils.extract_section_data(data, newdata)
    ascii_strs = string_utils.extract_ascii_strings(sec_data)
    print(f"  ASCII strings in .Newdata: {len(ascii_strs)}")
    for s in ascii_strs[:5]:
        print(f"    \"{s}\"")

    gbk = string_utils.extract_gbk_strings(sec_data)
    print(f"  GBK strings: {len(gbk)}")
    for off, s in gbk[:5]:
        print(f"    [0x{off:04X}] \"{s}\"")
    print()


def test_disasm_utils():
    print("=" * 60)
    print("Test 3: disasm_utils")
    print("=" * 60)
    exe_path = r"MOD文档/exe比对\TKS-颠动沧溟强化版2.0.exe"
    p = Path(exe_path)
    if not p.exists():
        print(f"  [SKIP] File not found")
        return
    with open(p, 'rb') as f:
        data = f.read()
    sections = pe_utils.read_pe_sections(data)
    test_sec = pe_utils.find_section(sections, '.test')
    if not test_sec:
        print(f"  [SKIP] .test not found")
        return
    sec_data = pe_utils.extract_section_data(data, test_sec)

    jumps = disasm_utils.find_jumps(sec_data, test_sec['virtual_address'])
    classified = disasm_utils.classify_jumps(jumps, test_sec['virtual_address'], test_sec['raw_size'])
    print(f"  Total jumps: {len(jumps)}")
    print(f"    Internal: {len(classified['inside'])}")
    print(f"    External: {len(classified['outside'])}")

    prologues = disasm_utils.find_function_prologues(sec_data)
    print(f"  Function prologues: {len(prologues)}")

    top = disasm_utils.top_opcodes(sec_data, 10)
    print(f"  Top 10 opcodes:")
    for b, c in top:
        print(f"    0x{b:02X}: {c}")
    print()


def test_binary_diff():
    print("=" * 60)
    print("Test 4: binary_diff")
    print("=" * 60)
    base_path = r"MOD文档/exe比对\TKS-2013强化版.exe"
    ext_path = r"MOD文档/exe比对\TKS-颠动沧溟强化版2.0.exe"
    bp, ep = Path(base_path), Path(ext_path)
    if not bp.exists() or not ep.exists():
        print(f"  [SKIP] Files not found")
        return

    summary = binary_diff.file_diff_summary(base_path, ext_path)
    print(f"  Base size: {summary['base_size']:,}")
    print(f"  Ext size:  {summary['ext_size']:,}")
    print(f"  Common prefix: {summary['common_prefix']:,}")
    print(f"  Diff bytes: {summary['diff_count_in_common']:,}")

    with open(ep, 'rb') as f:
        ext_data = f.read()
    ext_sec = pe_utils.read_pe_sections(ext_data)
    text_sec = pe_utils.find_section(ext_sec, '.text')
    test_sec = pe_utils.find_section(ext_sec, '.test')

    if text_sec and test_sec:
        hooks = binary_diff.find_e9_hooks(ext_data, text_sec, test_sec)
        print(f"  E9 JMP hooks targeting .test: {len(hooks)}")
        for h in hooks[:3]:
            print(f"    0x{h['rva']:08X} -> 0x{h['target_rva']:08X}")
    print()


if __name__ == '__main__':
    test_pe_utils()
    test_string_utils()
    test_disasm_utils()
    test_binary_diff()
    print("All tests passed!")