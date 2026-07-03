"""
build_all.py — TKS Editors 一键构建脚本 (Nuitka)
==================================================
支持两种打包模式:

  薄 exe (默认) — 大型共享模块 (PySide6/PIL) 由 .lib 归档提供，不编译进 exe
    python build/build_all.py                  # 构建全部薄 exe
    python build/build_all.py --only TKSItemEditor   # 仅构建指定编辑器
    python build/build_all.py --runtime        # 仅生成运行时归档 (.lib)
    python build/build_all.py --all            # 归档 + 全部 exe

  完整 exe (--onefile) — PySide6/PIL 烘焙进每个 exe，无外部 .lib 依赖
    python build/build_all.py --onefile                 # 调试模式: --lto=no --jobs=8 (快速)
    python build/build_all.py --onefile --release       # 发布模式: --lto=yes (链接时优化, 更小体积)
    python build/build_all.py --onefile --only TKSLauncher --release  # 仅构建指定 (发布)

  python build/build_all.py --list             # 列出所有可构建编辑器

前置条件:
    pip install nuitka ordered-set zstandard PySide6 Pillow
    需要 C 编译器: MSVC (VS Build Tools)

输出目录:
    dist/TKSEditors/
    ├── TKSItemEditor.exe     (~5-8MB 薄 / ~40-80MB 完整)
    ├── ...
    ├── [薄模式] PySide6.lib, QtCore.lib, ...
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
    ("TKSConfigsEditor",      "build/entries/entry_configs_editor.py",     "configs_editor"),
    ("TKSLauncher",          "build/entries/entry_launcher.py",           "tks_launcher_gui"),
    ("TKSLauncherCLI",       "build/entries/entry_launcher_cli.py",      "tks_launcher_gui"),
]

# 需要 Pillow 的编辑器 (onefile 模式用, 薄模式 PIL 由 PIL.lib 统一提供)
NEEDS_PILLOW = {"TKSJvgEditor", "TKSGrpEditor", "TKSGxpEditor", "TKSSpritesheetEditor"}

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"


def _build_thin_cmd(name: str, entry: str, editor_dir: str, release: bool = False) -> list:
    """生成 Nuitka 薄 exe 构建命令 (PySide6/PIL 由 .lib 提供, 不编译进 exe)"""
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
        "--jobs=8",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
    ]

    # ── 清理 ──
    cmd.extend([
        "--remove-output",

        # ── 入口脚本 ──
        str(entry_path),
    ])

    return cmd


def _build_onefile_cmd(name: str, entry: str, editor_dir: str, release: bool = False) -> list:
    """生成 Nuitka 完整 onefile 构建命令 (PySide6/PIL 编译进 exe)"""
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

        # ── PySide6 插件 (完整编译 Qt) ──
        "--enable-plugin=pyside6",

        # ── 包含数据文件 (主题/翻译/图标) ──
        f"--include-data-dir={仓库根目录 / 'editor_themes'}=editor_themes",
        f"--include-data-files={仓库根目录 / 'editor_utils' / 'qtbase_zh_CN.qm'}=editor_utils/qtbase_zh_CN.qm",
        f"--include-data-files={icon_path}=TKS.ico",

        # ── 包含 editor_utils 包 ──
        f"--include-package=editor_utils",

        # ── 排除无用模块 (减小体积) ──
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=scipy",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=unittest",
        "--nofollow-import-to=PySide6.QtQml",
        "--nofollow-import-to=PySide6.QtQuick",
        "--nofollow-import-to=PySide6.QtNetwork",
        "--nofollow-import-to=PySide6.QtWebEngine",

        # ── 允许运行时导入被排除模块 (意外导入链如 item_editor.py→tkinter 不会 crash) ──
        "--no-deployment-flag=excluded-module-usage",

        # ── 编译优化 ──
        "--jobs=8",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",

        # ── 清理 ──
        "--remove-output",
    ]

    # Pillow 支持
    if name in NEEDS_PILLOW:
        cmd.append("--include-package=PIL")

    # 入口脚本 (必须是最后一个参数)
    cmd.append(str(entry_path))

    return cmd


def _build_cli_cmd(name: str, entry: str, editor_dir: str, release: bool = False) -> list:
    """生成 CLI 启动器 Nuitka 构建命令 (无 PySide6, 无 Qt, 极简 exe)"""
    entry_path = 仓库根目录 / entry
    icon_path = 仓库根目录 / editor_dir / "TKS.ico"
    if not icon_path.exists():
        icon_path = 仓库根目录 / "item_editor" / "TKS.ico"

    tks_launcher_dir = 仓库根目录 / "tks_launcher_gui"

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--output-dir={DIST_DIR}",
        f"--output-filename={name}.exe",
        # CLI 需要控制台输出
        "--windows-console-mode=force",
        f"--windows-icon-from-ico={icon_path}",

        # 排除所有 GUI 框架 (避免 Nuitka 追踪到 PySide6)
        "--nofollow-import-to=PySide6",
        "--nofollow-import-to=shiboken6",
        "--nofollow-import-to=PIL",
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",

        # 禁用排除模块的隐式导入检测
        "--no-deployment-flag=excluded-module-usage",

        # 包含 core 包 (Nuitka 不会自动发现)
        "--include-package=tks_launcher_gui.core",

        # 包含数据文件 (补丁配置)
        f"--include-data-files={tks_launcher_dir / 'tks_patches.json'}=tks_patches.json",
        f"--include-data-files={tks_launcher_dir / 'summon_table.json'}=summon_table.json",

        # 编译优化
        "--jobs=8",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--remove-output",
    ]

    cmd.append(str(entry_path))
    return cmd


def build_one(name: str, entry: str, editor_dir: str,
              onefile: bool = False, verbose: bool = False,
              release: bool = False) -> bool:
    """构建单个 exe (薄模式或完整 onefile 模式)"""
    # CLI 启动器使用专用构建 (无 PySide6)
    is_cli = (name == "TKSLauncherCLI")
    if is_cli:
        mode_label = "CLI 极简 (无 PySide6/Qt)"
    elif onefile:
        mode_label = "完整 onefile (PySide6/PIL 内嵌)"
    else:
        mode_label = "薄 exe (无 PySide6/PIL)"
    lto_label = "LTO=yes" if release else "LTO=no (调试加速)"
    print(f"\n{'='*60}")
    print(f"  构建: {name}")
    print(f"  入口: {entry}")
    print(f"  模式: Nuitka --onefile ({mode_label}, {lto_label}, jobs=8)")
    print(f"{'='*60}")

    if is_cli:
        cmd = _build_cli_cmd(name, entry, editor_dir, release)
    elif onefile:
        cmd = _build_onefile_cmd(name, entry, editor_dir, release)
    else:
        cmd = _build_thin_cmd(name, entry, editor_dir, release)

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

    # 复制 launcher_config.json (CLI 启动器配置模板)
    launcher_cfg_src = 仓库根目录 / "tks_launcher_gui" / "launcher_config.json"
    if launcher_cfg_src.exists():
        shutil.copy2(str(launcher_cfg_src), str(RELEASE_DIR / "launcher_config.json"))
        print(f"  [OK] launcher_config.json")

    # 复制 summon_table.json (召唤表数据)
    summon_src = 仓库根目录 / "tks_launcher_gui" / "summon_table.json"
    if summon_src.exists():
        shutil.copy2(str(summon_src), str(RELEASE_DIR / "summon_table.json"))
        print(f"  [OK] summon_table.json")

    # 汇总
    total_size = sum(
        f.stat().st_size for f in RELEASE_DIR.iterdir()
        if f.is_file()
    )
    print(f"\n  组装完成: {assembled} 个编辑器")
    print(f"  发行目录总大小: {total_size / (1024*1024):.1f} MB")
    print(f"  发行目录: {RELEASE_DIR}")


def main():
    parser = argparse.ArgumentParser(description="TKS Editors 一键构建 (Nuitka)")
    parser.add_argument("--onefile", action="store_true",
                        help="完整单文件模式: PySide6/PIL 编译进 exe (无外部 .lib 依赖)")
    parser.add_argument("--only", type=str, help="仅构建指定编辑器")
    parser.add_argument("--runtime", action="store_true",
                        help="仅生成运行时归档 (仅薄模式)")
    parser.add_argument("--all", action="store_true",
                        help="归档 + 全部 exe (仅薄模式)")
    parser.add_argument("--list", action="store_true", help="列出所有可构建编辑器")
    parser.add_argument("--no-assemble", action="store_true", help="构建后不组装发行目录")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--release", action="store_true",
                        help="发布模式: --lto=yes (链接时优化, 更小体积, 构建更慢)")
    args = parser.parse_args()

    if args.list:
        print("可构建编辑器:")
        for name, entry, _ in EDITORS:
            tag = ""
            if not args.onefile and name in NEEDS_PILLOW:
                tag = " [+PIL]"
            print(f"  {name:<24} {entry}{tag}")
        return

    if args.onefile and (args.runtime or args.all):
        print("[WARN] --onefile 模式下 --runtime/--all 无效 (完整 exe 无需 .lib 归档)")
        args.runtime = False
        args.all = False

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
        ok = build_one(name, entry, editor_dir, args.onefile, args.verbose, args.release)
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
