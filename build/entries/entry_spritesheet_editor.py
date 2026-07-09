"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 确保 仓库根目录 在 path 中 (开发环境 + Nuitka 编译均适用)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 引导运行时 (必须在 PySide6/PIL 导入前) ──
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

# ── 导入并运行编辑器 ──
from spritesheet_editor.spritesheet_editor_v2 import main
main()
