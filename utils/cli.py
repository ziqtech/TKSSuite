# -*- coding: utf-8 -*-
"""
PE Analyzer 命令行入口

提供开箱即用的命令行分析工具, 演示 pe_analyzer 模块的功能

用法:
    python -m utils.cli analyze <exe_path>
    python -m utils.cli strings <exe_path> <section_name>
    python -m utils.cli hooks <base_exe> <ext_exe>
"""
import sys
import os
from pathlib import Path

# 设置 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 允许从 仓库根目录 目录直接运行
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils import pe_utils, string_utils, disasm_utils
from utils import binary_diff, report_utils


def cmd_analyze(exe_path: str) -> int:
    """分析 PE 文件结构"""
    if not os.path.exists(exe_path):
        print(f"File not found: {exe_path}")
        return 1

    with open(exe_path, 'rb') as f:
        data = f.read()

    print(f"File: {exe_path}")
    print(f"Size: {len(data):,} bytes")
    print()

    # 节区
    try:
        sections = pe_utils.read_pe_sections(data)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print("=== Sections ===")
    print(report_utils.print_section_table(sections))
    print()

    # 入口点
    entry_rva, entry_off = pe_utils.get_entry_point(data)
    if entry_rva is not None:
        print(f"Entry Point: RVA=0x{entry_rva:08X}, FileOffset=0x{entry_off or 0:08X}")
    print()

    # 标准导入表
    imports = pe_utils.parse_import_directory(data, sections)
    if imports:
        print(f"=== Standard Import Table ({len(imports)} DLLs) ===")
        for imp in imports:
            print(f"\n{imp['module']}:")
            for fn in imp['functions'][:10]:
                print(f"  - {fn}")
            if len(imp['functions']) > 10:
                print(f"  ... and {len(imp['functions']) - 10} more")

    # .Silvana 嵌入式导入表
    silvana = pe_utils.find_section(sections, '.Silvana')
    if silvana:
        silvana_imports = pe_utils.parse_silvana_imports(data, silvana)
        if silvana_imports:
            print(f"\n=== .Silvana Embedded Imports ({len(silvana_imports)}) ===")
            for imp in silvana_imports:
                print(f"  {imp['dll']} -> {imp['function']} (ptr=0x{imp['ptr_rva']:08X})")

    return 0


def cmd_strings(exe_path: str, section_name: str) -> int:
    """提取指定节区的字符串"""
    if not os.path.exists(exe_path):
        print(f"File not found: {exe_path}")
        return 1

    with open(exe_path, 'rb') as f:
        data = f.read()

    sections = pe_utils.read_pe_sections(data)
    sec = pe_utils.find_section(sections, section_name)
    if not sec:
        print(f"Section '{section_name}' not found")
        return 1

    sec_data = pe_utils.extract_section_data(data, sec)

    print(f"=== Strings in {section_name} ===")
    print(f"Section: VAddr=0x{sec['virtual_address']:08X} Size={sec['raw_size']:,}")
    print()

    # ASCII 字符串
    ascii_strs = string_utils.extract_ascii_strings(sec_data)
    print(f"-- ASCII Strings ({len(ascii_strs)}) --")
    for s in ascii_strs:
        print(f'  "{s}"')

    # GBK 中文字符串
    gbk_strs = string_utils.extract_gbk_strings(sec_data)
    if gbk_strs:
        print(f"\n-- GBK Chinese Strings ({len(gbk_strs)}) --")
        for off, s in gbk_strs:
            print(f'  [0x{off:04X}] "{s}"')

    return 0


def cmd_hooks(base_path: str, ext_path: str) -> int:
    """对比基础版和扩展版, 找出所有 Hook"""
    if not os.path.exists(base_path):
        print(f"Base file not found: {base_path}")
        return 1
    if not os.path.exists(ext_path):
        print(f"Ext file not found: {ext_path}")
        return 1

    with open(base_path, 'rb') as f:
        base_data = f.read()
    with open(ext_path, 'rb') as f:
        ext_data = f.read()

    base_sec = pe_utils.read_pe_sections(base_data)
    ext_sec = pe_utils.read_pe_sections(ext_data)

    text_sec = pe_utils.find_section(ext_sec, '.text')
    test_sec = pe_utils.find_section(ext_sec, '.test')
    if not text_sec:
        print(".text section not found")
        return 1

    # 找出修改版中的所有 E9 hooks, 目标在 .test 中
    hooks = binary_diff.find_e9_hooks(ext_data, text_sec, test_sec)
    print(report_utils.print_hook_list(hooks, '.test'))
    print()

    # 对比基础版, 找出真实的 Hook (原始不是 E9)
    real_hooks = binary_diff.find_modified_to_e9(base_data, ext_data, text_sec)
    if test_sec:
        # 过滤目标在 .test 中的
        real_hooks = [h for h in real_hooks
                      if test_sec['virtual_address'] <= h['target_rva']
                      < test_sec['virtual_address'] + test_sec['raw_size']]

    print(f"\n=== Real IAT Hooks (orig != 0xE9, target in .test): {len(real_hooks)} ===")
    for h in real_hooks[:5]:  # 只显示前5个详情
        print(report_utils.diff_context(base_data, ext_data, h['file_offset']))
        print()

    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  analyze <exe_path>               - 分析 PE 结构")
        print("  strings <exe_path> <section>     - 提取节区字符串")
        print("  hooks <base_exe> <ext_exe>       - 对比找 Hook")
        return 1

    cmd = sys.argv[1]
    if cmd == 'analyze' and len(sys.argv) >= 3:
        return cmd_analyze(sys.argv[2])
    elif cmd == 'strings' and len(sys.argv) >= 4:
        return cmd_strings(sys.argv[2], sys.argv[3])
    elif cmd == 'hooks' and len(sys.argv) >= 4:
        return cmd_hooks(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        return 1


if __name__ == '__main__':
    sys.exit(main())