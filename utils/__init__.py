"""
PE Analyzer - 通用 PE 文件分析工具集

包含以下子模块:
- pe_utils:     PE 文件结构解析 (节区、入口点、RVA 转换、导入表)
- string_utils: 字符串提取 (ASCII/GBK/通用)
- binary_diff:  二进制对比 (差异区域、E9 Hook 查找)
- disasm_utils: 简易反汇编 (指令识别、跳转/调用分析、函数开头)
- report_utils: 报告生成 (十六进制转储、格式化输出)

典型用法:
    from utils import pe_utils, string_utils, disasm_utils

    with open('some.exe', 'rb') as f:
        data = f.read()

    sections = pe_utils.read_pe_sections(data)
    test_sec = pe_utils.find_section(sections, '.test')
    sec_data = pe_utils.extract_section_data(data, test_sec)
    strings = string_utils.extract_ascii_strings(sec_data)
    jumps = disasm_utils.find_jumps(sec_data, test_sec['virtual_address'])
"""

__version__ = "1.0.0"