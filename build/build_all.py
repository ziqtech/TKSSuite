"""
build_all.py — TKS Editors 一键构建脚本 (Nuitka 薄 exe + 共享运行时)
===========================================================
使用 Nuitka 将所有编辑器打包为薄 exe。
大型共享模块 (PySide6/PIL) 由 .lib 归档提供，不编译进 exe。

用法:
    python build/build_all.py                  # 构建全部薄 exe
    python build/build_all.py --only TKSItemEditor   # 仅构建指定编辑器
    python build/build_all.py --runtime        # 仅生成运行时归档 (.lib)
    python build/build_all.py --all            # 归档 + 全部 exe
    python build/build_all.py --list           # 列出所有可构建编辑器

前置条件:
    pip install nuitka ordered-set zstandard PySide6 Pillow
    需要 C 编译器: MSVC (VS Build Tools)

输出目录:
    dist/TKSEditors/
    ├── TKSItemEditor.exe     (~5-8MB, 薄 exe)
    ├── ...
    ├── PySide6.lib           (共享运行时归档)
    ├── QtCore.lib
    ├── ...
    ├── configs/
    └── mods/
"""
import os
import sys
import shutil
import argparse
import subprocess
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 编辑器配置表
# ═══════════════════════════════════════════════════════════════

# (打包名, 入口脚本, 编辑器目录)
EDITORS = [
    ("TKSItemEditor",        "build/entries/entry_item_editor.py",        "item_editor"),
    ("TKSWarpcEditor",       "build/entries/entry_warpc_editor.py",       "warpc_editor"),
    ("TKSSkillEditor",       "build/entries/entry_skill_editor.py",       "skill_editor"),
    ("TKSShopEditor",        "build/entries/entry_shop_editor.py",        "shop_editor"),
    ("TKSMatEditor",         "build/entries/entry_mat_editor.py",         "mat_editor"),
    ("TKSJvgEditor",         "build/entries/entry_jvg_editor.py",         "jvg_editor"),
    ("TKSGrpEditor",         "build/entries/entry_grp_editor.py",         "grp_editor"),
    ("TKSTktEditor",         "build/entries/entry_tkt_editor.py",         "tkt_editor"),
    ("TKSKonEditor",         "build/entries/entry_kon_editor.py",         "kon_editor"),
    ("TKSActEditor",         "build/entries/entry_act_editor.py",         "act_editor"),
    ("TKSWardataEditor",     "build/entries/entry_wardata_editor.py",     "wardata_editor"),
    ("TKSGxpEditor",         "build/entries/entry_gxp_editor.py",         "gxp_editor"),
    ("TKSSpritesheetEditor", "build/entries/entry_spritesheet_editor.py", "spritesheet_editor"),
    ("TKSSaveEditor",        "build/entries/entry_save_editor.py",        "save_editor"),
    ("TKSLauncher",          "build/entries/entry_launcher.py",           "tks_launcher_gui"),
]

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"


def _build_nuitka_cmd(name: str, entry: str, editor_dir: str) -> list:
    """生成 Nuitka 薄 exe 构建命令"""
    entry_path = 仓库根目录 / entry
    icon_path = 仓库根目录 / editor_dir / "TKS.ico"
    if not icon_path.exists():
        icon_path = 仓库根目录 / "item_editor" / "TKS.ico"

    cmd = [
        sys.executable, "-m", "nuitka",
        # ── 打包模式 ──
        "--onefile",
        "--assume-yes-for-downloads",

        # ── 输出控制 ──
        f"--output-dir={DIST_DIR}",
        f"--output-filename={name}.exe",

        # ── Windows 配置 ──
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={icon_path}",

        # ── 不使用 PySide6 插件 (不打包 Qt!) ──
        # PySide6/PIL/shiboken6 由外部 .lib 归档提供

        # ── 排除大型共享模块 (由 .lib 归档提供) ──
        "--nofollow-import-to=PySide6",
        "--nofollow-import-to=shiboken6",
        "--nofollow-import-to=PIL",

        # ── 允许运行时动态导入被排除的模块 (由 bootstrap 设置 sys.path) ──
        "--no-deployment-flag=excluded-module-usage",

        # ── 包含编辑器共享工具 (编译进 exe) ──
        "--include-package=editor_utils",

        # ── 包含数据文件 (主题/翻译/图标) ──
        f"--include-data-dir={仓库根目录 / 'editor_themes'}=editor_themes",
        f"--include-data-files={仓库根目录 / 'editor_utils' / 'qtbase_zh_CN.qm'}=editor_utils/qtbase_zh_CN.qm",
        f"--include-data-files={icon_path}=TKS.ico",

        # ── 排除其他无用模块 ──
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=scipy",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=unittest",

        # ── 编译优化 ──
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",

        # ── 清理 ──
        "--remove-output",

        # ── 入口脚本 ──
        str(entry_path),
    ]

    return cmd


def build_one(name: str, entry: str, editor_dir: str, verbose: bool = False) -> bool:
    """构建单个薄 exe"""
    print(f"\n{'='*60}")
    print(f"  构建: {name}")
    print(f"  入口: {entry}")
    print(f"  模式: Nuitka --onefile (薄 exe, 无 PySide6/PIL)")
    print(f"{'='*60}")

    cmd = _build_nuitka_cmd(name, entry, editor_dir)

    if verbose:
        print(f"  命令: {' '.join(str(c) for c in cmd)}")

    # 构建环境: 将编辑器目录加入 PYTHONPATH
    # 解决部分编辑器内部使用裸包名导入 (from ui.xxx, from core.xxx 等)
    env = os.environ.copy()
    extra_path = str(仓库根目录 / editor_dir)
    env["PYTHONPATH"] = extra_path + os.pathsep + env.get("PYTHONPATH", "")

    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(仓库根目录), env=env)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  [FAIL] {name} 构建失败 (exit code: {result.returncode}, {elapsed:.1f}s)")
        return False

    print(f"  [OK] {name} 构建成功 ({elapsed:.1f}s)")
    return True


def build_runtime():
    """构建运行时归档 (.lib)"""
    print(f"\n{'='*60}")
    print(f"  构建运行时归档")
    print(f"{'='*60}")
    cmd = [sys.executable, str(BUILD_DIR / "build_runtime.py"), "--output", str(RELEASE_DIR)]
    result = subprocess.run(cmd, cwd=str(仓库根目录))
    return result.returncode == 0


def assemble_release():
    """组装发行目录"""
    print(f"\n{'='*60}")
    print(f"  组装发行目录: {RELEASE_DIR}")
    print(f"{'='*60}")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    assembled = 0
    for name, _, _ in EDITORS:
        exe_src = DIST_DIR / f"{name}.exe"
        if not exe_src.exists():
            print(f"  [SKIP] {name}.exe 不存在")
            continue
        shutil.copy2(str(exe_src), str(RELEASE_DIR / f"{name}.exe"))
        size_mb = exe_src.stat().st_size / (1024 * 1024)
        print(f"  [OK] {name}.exe ({size_mb:.1f} MB)")
        assembled += 1

    # configs/ 和 mods/
    (RELEASE_DIR / "configs").mkdir(exist_ok=True)
    (RELEASE_DIR / "mods").mkdir(exist_ok=True)

    # 复制基线配置
    src_configs = 仓库根目录 / "configs"
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(RELEASE_DIR / "configs" / f.name))

    # 复制 tks_patches.json 到发行根目录 (补丁基础设施, 不在 configs/ 内)
    tks_patches_src = 仓库根目录 / "tks_launcher_gui" / "tks_patches.json"
    if tks_patches_src.exists():
        shutil.copy2(str(tks_patches_src), str(RELEASE_DIR / "tks_patches.json"))
        print(f"  [OK] tks_patches.json")

    # 汇总
    total_size = sum(
        f.stat().st_size for f in RELEASE_DIR.iterdir()
        if f.is_file()
    )
    print(f"\n  组装完成: {assembled} 个编辑器")
    print(f"  发行目录总大小: {total_size / (1024*1024):.1f} MB")
    print(f"  发行目录: {RELEASE_DIR}")


def main():
    parser = argparse.ArgumentParser(description="TKS Editors 一键构建")
    parser.add_argument("--only", type=str, help="仅构建指定编辑器")
    parser.add_argument("--runtime", action="store_true", help="仅生成运行时归档")
    parser.add_argument("--all", action="store_true", help="归档 + 全部 exe")
    parser.add_argument("--list", action="store_true", help="列出可构建编辑器")
    parser.add_argument("--no-assemble", action="store_true", help="不组装发行目录")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.list:
        print("可构建编辑器:")
        for name, entry, _ in EDITORS:
            print(f"  {name:<24} {entry}")
        return

    # 生成入口脚本 (确保最新)
    subprocess.run([sys.executable, str(BUILD_DIR / "gen_entries.py")],
                   cwd=str(仓库根目录), capture_output=True)

    if args.runtime:
        build_runtime()
        return

    if args.all:
        if not build_runtime():
            print("[ERROR] 运行时归档构建失败")
            sys.exit(1)

    # 确定构建目标
    if args.only:
        targets = [(n, e, d) for n, e, d in EDITORS if n == args.only]
        if not targets:
            print(f"[ERROR] 未找到编辑器: {args.only}")
            print(f"  可用: {', '.join(n for n, _, _ in EDITORS)}")
            sys.exit(1)
    else:
        targets = EDITORS

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 构建
    success = []
    failed = []
    t_total = time.time()

    for name, entry, editor_dir in targets:
        ok = build_one(name, entry, editor_dir, args.verbose)
        (success if ok else failed).append(name)

    elapsed_total = time.time() - t_total

    # 摘要
    print(f"\n{'='*60}")
    print(f"  构建摘要")
    print(f"{'='*60}")
    print(f"  成功: {len(success)}")
    if failed:
        print(f"  失败: {len(failed)} — {', '.join(failed)}")
    print(f"  总耗时: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")

    # 组装
    if not args.no_assemble and success:
        assemble_release()


if __name__ == "__main__":
    main()
