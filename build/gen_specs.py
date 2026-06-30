"""
gen_specs.py — 自动生成所有编辑器的 .spec 文件
================================================
运行: python build/gen_specs.py
将在 build/specs/ 下为每个编辑器生成对应的 .spec 文件。
"""
import os
import sys
from pathlib import Path

# 编辑器定义: (名称, 入口脚本, 需要PIL, 编辑器目录名)
EDITORS = [
    ("TKSItemEditor",        "item_editor/item_editor_v2.py",               False, "item_editor"),
    ("TKSWarpcEditor",       "warpc_editor/warpc_editor_v2.py",             False, "warpc_editor"),
    ("TKSSkillEditor",       "skill_editor/skill_editor_v2.py",             False, "skill_editor"),
    ("TKSShopEditor",        "shop_editor/shop_editor_v2.py",               False, "shop_editor"),
    ("TKSMatEditor",         "mat_editor/mat_editor_v2.py",                 False, "mat_editor"),
    ("TKSJvgEditor",         "jvg_editor/jvg_editor_v2.py",                True,  "jvg_editor"),
    ("TKSGrpEditor",         "grp_editor/grp_editor_v2.py",                True,  "grp_editor"),
    ("TKSTktEditor",         "tkt_editor/tkt_editor_v2.py",                 False, "tkt_editor"),
    ("TKSKonEditor",         "kon_editor/kon_editor_v2.py",                 False, "kon_editor"),
    ("TKSActEditor",         "act_editor/act_editor_v2.py",                 False, "act_editor"),
    ("TKSWardataEditor",     "wardata_editor/wardata_editor_v2.py",         False, "wardata_editor"),
    ("TKSGxpEditor",         "gxp_editor/gxp_editor_v2.py",                True,  "gxp_editor"),
    ("TKSSpritesheetEditor", "spritesheet_editor/spritesheet_editor_v2.py", True,  "spritesheet_editor"),
    ("TKSSaveEditor",        "save_editor/save_editor_v2.py",               False, "save_editor"),
    ("TKSLauncher",          "tks_launcher_gui/main.py",                    False, "tks_launcher_gui"),
]

SPEC_TEMPLATE = '''\
# -*- mode: python ; coding: utf-8 -*-
"""
{name}.spec — PyInstaller 构建配置
自动生成，请勿手动编辑。如需修改请编辑 gen_specs.py 后重新生成。
"""
import os
import sys

block_cipher = None

# 仓库根目录 根目录 (SPECPATH = spec 文件所在目录, 即 build/specs/)
BASE = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

a = Analysis(
    [os.path.join(BASE, {entry!r})],
    pathex=[BASE],
    binaries=[],
    datas=[
        # 主题 QSS 文件
        (os.path.join(BASE, 'editor_themes', 'dark.qss'), 'editor_themes'),
        (os.path.join(BASE, 'editor_themes', 'light.qss'), 'editor_themes'),
        # 主题 SVG 图标
        (os.path.join(BASE, 'editor_themes', 'svg'), 'editor_themes/svg'),
        # 翻译文件
        (os.path.join(BASE, 'editor_utils', 'qtbase_zh_CN.qm'), 'editor_utils'),
        # 编辑器图标 (优先从编辑器目录, 回退到 item_editor)
        (os.path.join(BASE, {icon_dir!r}, 'TKS.ico'), '.'),{extra_datas}
    ],
    hiddenimports=[
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',{extra_imports}
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pytest',
        'IPython',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={name!r},
    icon=os.path.join(BASE, {icon_dir!r}, 'TKS.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name={name!r},
)
'''


def generate_spec(name: str, entry: str, needs_pillow: bool, editor_dir: str) -> str:
    """生成单个 .spec 文件内容"""
    extra_imports = ""
    if needs_pillow:
        extra_imports = "\n        'PIL',\n        'PIL.Image',\n        'PIL.ImageDraw',"

    extra_datas = ""
    # 启动器需要额外的数据文件
    if name == "TKSLauncher":
        extra_datas = """
        # 启动器专用: 补丁配置和召唤表
        (os.path.join(BASE, 'tks_launcher_gui', 'tks_patches.json'), '.'),
        (os.path.join(BASE, 'tks_launcher_gui', 'summon_table.json'), '.'),"""

    # 图标目录: 优先用编辑器自身目录, 没有则回退到 item_editor
    import os as _os
    base_path = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..'))
    if _os.path.isfile(_os.path.join(base_path, editor_dir, 'TKS.ico')):
        icon_dir = editor_dir
    else:
        icon_dir = 'item_editor'

    return SPEC_TEMPLATE.format(
        name=name,
        entry=entry,
        editor_dir=editor_dir,
        icon_dir=icon_dir,
        extra_imports=extra_imports,
        extra_datas=extra_datas,
    )


def main():
    specs_dir = Path(__file__).parent / "specs"
    specs_dir.mkdir(exist_ok=True)

    for name, entry, needs_pillow, editor_dir in EDITORS:
        content = generate_spec(name, entry, needs_pillow, editor_dir)
        spec_path = specs_dir / f"{name}.spec"
        with open(spec_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] 生成: {spec_path.name}")

    print(f"\n  共生成 {len(EDITORS)} 个 .spec 文件")
    print(f"  位置: {specs_dir}")


if __name__ == "__main__":
    main()
