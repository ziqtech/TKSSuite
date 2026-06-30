# -*- mode: python ; coding: utf-8 -*-
"""
TKSKonEditor.spec — PyInstaller 构建配置
自动生成，请勿手动编辑。如需修改请编辑 gen_specs.py 后重新生成。
"""
import os
import sys

block_cipher = None

# 仓库根目录 根目录
BASE = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))

a = Analysis(
    [os.path.join(BASE, 'kon_editor/kon_editor_v2.py')],
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
        # 编辑器图标
        (os.path.join(BASE, 'kon_editor', 'TKS.ico'), '.'),
    ],
    hiddenimports=[
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
    ],
    hookspath=[],
    hooksconfig={},
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
    name='TKSKonEditor',
    icon=os.path.join(BASE, 'kon_editor', 'TKS.ico'),
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
    name='TKSKonEditor',
)
