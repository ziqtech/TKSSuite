"""
gen_entries.py — 自动生成各编辑器的薄入口脚本
=============================================
生成的入口脚本：
  1. 将 仓库根目录 和编辑器目录加入 sys.path
  2. 调用 bootstrap() 设置运行时路径 (需要 PySide6/PIL 的编辑器)
  3. 导入并运行实际的编辑器模块

使用单层模块名导入 (from item_editor import main) 而非包路径
(from item_editor.item_editor import main), 各编辑器目录无 __init__.py,
项目根下的同名目录仅构成 namespace package 片段, 解析优先级低于
编辑器目录内的同名 .py 主文件 (如 item_editor/item_editor.py)。

编辑器清单的单一事实来源见 editors_registry.py (T5 单源化)。

注: build/entries/ 下的生成产物刻意提交入库 (方案 A), 供查阅与增量构建
    mtime 判断; build_all.py 每次构建仍会重新生成, 手改会被静默覆盖。
"""
from pathlib import Path

from editors_registry import EDITORS

BUILD_DIR = Path(__file__).parent
ENTRIES_DIR = BUILD_DIR / "entries"

# 带 bootstrap 的模板 (依赖 PySide6/PIL 的编辑器)
# sys.path 顺序: [仓库根目录, editor_dir, ...]
# 仓库根目录 在前: configs_editor 被解析为包 (有 __init__.py), 点号路径生效
# editor_dir 在后: 裸包名导入 (from panels import) 仍能找到子包
TEMPLATE_BOOTSTRAP = '''\
"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 将编辑器目录加入 sys.path (裸包名导入如 from panels import, from core import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '{editor_dir}'))

# 确保 仓库根目录 在 path 中且优先级最高 (开发环境 + Nuitka 编译均适用)
# 必须在 editor_dir 之后插入, 使 仓库根目录 排在 sys.path[0]
# 这样 configs_editor 被解析为包 (有 __init__.py) 而非同名 .py 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 引导运行时 (必须在 PySide6/PIL 导入前) ──
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

# ── 导入并运行编辑器 ──
from {module} import main
main()
'''

# 无 bootstrap 的模板 (CLI / 无 PySide6 依赖的入口)
TEMPLATE_PLAIN = '''\
"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 将编辑器目录加入 sys.path (裸包名导入如 from panels import, from core import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '{editor_dir}'))

# 确保 仓库根目录 在 path 中且优先级最高 (开发环境 + Nuitka 编译均适用)
# 必须在 editor_dir 之后插入, 使 仓库根目录 排在 sys.path[0]
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 导入并运行 (无 PySide6/PIL 依赖, 跳过 runtime bootstrap) ──
from {module} import main
main()
'''


def main():
    ENTRIES_DIR.mkdir(exist_ok=True)
    written = 0
    for _name, filename, module, editor_dir, needs_bootstrap in EDITORS:
        template = TEMPLATE_BOOTSTRAP if needs_bootstrap else TEMPLATE_PLAIN
        content = template.format(module=module, editor_dir=editor_dir)
        path = ENTRIES_DIR / filename
        # 内容未变则不重写, 保留 mtime — 否则会使增量构建 (_should_skip_build) 每次都重编译
        if path.exists() and path.read_text(encoding='utf-8') == content:
            continue
        path.write_text(content, encoding='utf-8')
        written += 1
        tag = "" if needs_bootstrap else " [no-bootstrap]"
        print(f"  [OK] {filename}{tag}")

    print(f"\n  共 {len(EDITORS)} 个入口脚本 ({written} 个更新)")
    print(f"  位置: {ENTRIES_DIR}")


if __name__ == "__main__":
    main()
