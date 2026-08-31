"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 将编辑器目录加入 sys.path (裸包名导入如 from panels import, from core import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'mat_editor'))

# 确保 仓库根目录 在 path 中且优先级最高 (开发环境 + Nuitka 编译均适用)
# 必须在 editor_dir 之后插入, 使 仓库根目录 排在 sys.path[0]
# 这样 configs_editor 被解析为包 (有 __init__.py) 而非同名 .py 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 引导运行时 (必须在 PySide6/PIL 导入前) ──
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

# ── 导入并运行编辑器 ──
from mat_editor import main
main()
