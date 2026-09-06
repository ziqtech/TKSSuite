# PE Analyzer - 通用 PE 文件分析工具集

从 `docs/` 目录下的 12 个一次性分析脚本中提炼而来的通用工具，可用于：
- PE 文件结构分析
- 节区数据提取
- 字符串提取 (ASCII/GBK)
- 二进制 diff
- x86 简易反汇编
- IAT Hook 检测
- 嵌入式导入表解析（如 .Silvana 节区）

## 模块组成

| 模块 | 功能 | 主要函数 |
|------|------|----------|
| `pe_utils` | PE 结构解析 | `read_pe_sections`, `rva_to_file_offset`, `parse_import_directory`, `parse_silvana_imports` |
| `string_utils` | 字符串提取 | `extract_ascii_strings`, `extract_gbk_strings` |
| `binary_diff` | 二进制对比 | `find_e9_hooks`, `find_modified_to_e9`, `common_prefix_length` |
| `disasm_utils` | 简易反汇编 | `simple_disasm`, `find_jumps`, `find_function_prologues`, `find_api_patterns` |
| `report_utils` | 报告格式化 | `hex_dump`, `print_section_table`, `print_hook_list`, `diff_context` |
| `cli` | 命令行入口 | `analyze`, `strings`, `hooks` |

## 目录结构

```
utils/pe_analyzer/
├── __init__.py
├── pe_utils.py        # PE 文件结构解析
├── string_utils.py    # 字符串提取
├── binary_diff.py     # 二进制对比
├── disasm_utils.py    # 简易反汇编
├── report_utils.py    # 报告格式化
├── cli.py             # 命令行入口
├── test_pe_analyzer.py # 测试脚本
└── README.md          # 本文档
```

## Python API 使用

```python
import sys
sys.path.insert(0, r'仓库根目录')
from utils import pe_utils, string_utils, binary_diff, disasm_utils

# 1. 读取 PE 文件
with open('some.exe', 'rb') as f:
    data = f.read()

# 2. 解析节区
sections = pe_utils.read_pe_sections(data)
text_sec = pe_utils.find_section(sections, '.text')
test_sec = pe_utils.find_section(sections, '.test')

# 3. 提取节区数据
sec_data = pe_utils.extract_section_data(data, test_sec)

# 4. 字符串提取
ascii_strs = string_utils.extract_ascii_strings(sec_data)
gbk_strs = string_utils.extract_gbk_strings(sec_data)

# 5. 跳转指令分析
jumps = disasm_utils.find_jumps(sec_data, test_sec['virtual_address'])
classified = disasm_utils.classify_jumps(jumps, test_sec['virtual_address'], test_sec['raw_size'])
print(f"内部跳转: {len(classified['inside'])}")
print(f"外部跳转: {len(classified['outside'])}")

# 6. 找出所有 IAT Hook
hooks = binary_diff.find_e9_hooks(data, text_sec, test_sec)
real_hooks = [h for h in hooks if h['target_in_section']]
print(f"找到 {len(real_hooks)} 个 Hook")

# 7. 解析 .Silvana 嵌入式导入表
silvana = pe_utils.find_section(sections, '.Silvana')
imports = pe_utils.parse_silvana_imports(data, silvana)
for imp in imports:
    print(f"{imp['dll']} -> {imp['function']}")
```

## 命令行使用

```bash
# 设置路径
export PYTHONPATH="仓库根目录:$PYTHONPATH"

# 分析 PE 结构
python -m utils.cli analyze <exe_path>

# 提取节区字符串
python -m utils.cli strings <exe_path> <section_name>

# 对比找 Hook
python -m utils.cli hooks <base_exe> <ext_exe>
```

## 测试

```bash
python -m unittest utils.test_pe_analyzer
```

## 提炼来源

从以下 12 个一次性脚本中提炼（位于 `docs/` 目录）：

| 原脚本 | 提炼内容 |
|--------|---------|
| `analyze_new_sections.py` | `read_pe_sections`, `extract_section_data`, `decode_characteristics` |
| `analyze_strings.py` | `extract_ascii_strings`, `extract_gbk_strings` |
| `deep_analyze_sections.py` | `decode_characteristics` |
| `test_section_analysis.py` | `simple_disasm`, `find_jumps`, `find_function_prologues` |
| `test_section_deep_analysis.py` | `find_jumps` 增强, `find_api_patterns` |
| `hook_analysis.py` | `find_e9_hooks`, `find_modified_to_e9` |
| `detailed_hook_analysis.py` | `rva_to_file_offset`, `file_offset_to_rva` |
| `hook_detailed_analysis.py` | `find_indirect_iat_calls` |
| `hook_analysis_with_reverse.py` | `find_jumps` 分类 |
| `hook_function_analysis.py` | `top_opcodes` |
| `iat_hook_analysis.py` | `parse_import_directory` |
| `final_analysis.py` | `parse_import_directory` 改进 |

## 关键设计

1. **复用率高**：所有公共函数都被提取到对应模块
2. **类型注解**：完整的 type hints
3. **文档字符串**：每个函数都有详细的 docstring
4. **错误处理**：健壮的边界条件检查
5. **特殊格式支持**：
   - 标准 PE 导入表
   - `.Silvana` 嵌入式导入表（非标准格式）
   - 8+ 字符长节区名（`/xxxx` 格式）
   - 长江游戏特征（`kernel32.dll`/`SHELL32.dll` 辅助程序启动 API）
6. **测试覆盖**：所有模块都有测试用例

## 适用场景

- ✅ PE 文件结构分析
- ✅ IAT Hook 检测
- ✅ 自定义节区数据提取
- ✅ 简易反汇编
- ✅ 字符串提取
- ✅ 二进制对比
- ❌ 完整反汇编（请用 IDA Pro / Ghidra）
- ❌ 运行时调试（请用 x64dbg / WinDbg）
