"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 将编辑器目录加入 sys.path (裸包名导入如 from panels import, from core import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tks_launcher_gui'))

# 确保 仓库根目录 在 path 中且优先级最高 (开发环境 + Nuitka 编译均适用)
# 必须在 editor_dir 之后插入, 使 仓库根目录 排在 sys.path[0]
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 导入并运行 (无 PySide6/PIL 依赖, 跳过 runtime bootstrap) ──
from cli_launcher import main
main()
