"""
gen_entries.py — 自动生成各编辑器的薄入口脚本
=============================================
生成的入口脚本先调用 bootstrap() 设置运行时路径，
再导入并运行实际的编辑器模块。

这确保 PySide6 等模块在被导入前，sys.path 已正确配置。
"""
import os
from pathlib import Path

BUILD_DIR = Path(__file__).parent
ENTRIES_DIR = BUILD_DIR / "entries"

# (入口文件名, 实际编辑器模块路径, 是否有独立 main 函数)
EDITORS = [
    ("entry_item_editor.py",        "item_editor.item_editor_v2"),
    ("entry_warpc_editor.py",       "warpc_editor.warpc_editor_v2"),
    ("entry_skill_editor.py",       "skill_editor.skill_editor_v2"),
    ("entry_shop_editor.py",        "shop_editor.shop_editor_v2"),
    ("entry_mat_editor.py",         "mat_editor.mat_editor_v2"),
    ("entry_jvg_editor.py",         "jvg_editor.jvg_editor_v2"),
    ("entry_grp_editor.py",         "grp_editor.grp_editor_v2"),
    ("entry_tkt_editor.py",         "tkt_editor.tkt_editor_v2"),
    ("entry_kon_editor.py",         "kon_editor.kon_editor_v2"),
    ("entry_act_editor.py",         "act_editor.act_editor_v2"),
    ("entry_wardata_editor.py",     "wardata_editor.wardata_editor_v2"),
    ("entry_gxp_editor.py",         "gxp_editor.gxp_editor_v2"),
    ("entry_spritesheet_editor.py", "spritesheet_editor.spritesheet_editor_v2"),
    ("entry_save_editor.py",        "save_editor.save_editor_v2"),
    ("entry_configs_editor.py",     "configs_editor.configs_editor"),
    ("entry_launcher.py",           "tks_launcher_gui.main"),
    ("entry_launcher_cli.py",      "tks_launcher_gui.cli_launcher"),
]

TEMPLATE = '''\
"""TKS Editor 薄入口 — 自动生成，请勿手动编辑"""
import os
import sys

# 确保 仓库根目录 在 path 中 (开发环境 + Nuitka 编译均适用)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── 引导运行时 (必须在 PySide6/PIL 导入前) ──
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

# ── 导入并运行编辑器 ──
from {module} import main
main()
'''


def main():
    ENTRIES_DIR.mkdir(exist_ok=True)
    for filename, module in EDITORS:
        content = TEMPLATE.format(module=module)
        path = ENTRIES_DIR / filename
        path.write_text(content, encoding='utf-8')
        print(f"  [OK] {filename}")

    print(f"\\n  共生成 {len(EDITORS)} 个入口脚本")
    print(f"  位置: {ENTRIES_DIR}")


if __name__ == "__main__":
    main()
