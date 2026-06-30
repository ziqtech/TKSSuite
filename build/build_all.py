"""
build_all.py — TKS Editors 一键构建脚本 (Nuitka)
==================================================
使用 Nuitka 将所有编辑器打包为独立 onefile exe。
每个 exe 自包含全部依赖，无需 Python 环境、无外部 .pyd/.dll。

用法:
    python build_all.py                          # 构建全部
    python build_all.py --only TKSItemEditor     # 仅构建指定编辑器
    python build_all.py --list                   # 列出所有可构建编辑器
    python build_all.py --jobs 4                 # 并行构建 (默认串行)

前置条件:
    pip install nuitka ordered-set zstandard PySide6 Pillow
    需要 C 编译器: MSVC (推荐，VS Build Tools) 或 MinGW64

输出目录:
    dist/TKSEditors/
    ├── TKSItemEditor.exe
    ├── TKSWarpcEditor.exe
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
from concurrent.futures import ProcessPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════
# 编辑器配置表
# ═══════════════════════════════════════════════════════════════

# (打包名, 入口脚本相对于 仓库根目录 的路径, 是否需要 Pillow, 编辑器目录)
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

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"

# Nuitka 缓存目录 (避免重复编译共享模块)
NUITKA_CACHE_DIR = BUILD_DIR / "nuitka_cache"


def _build_nuitka_cmd(name: str, entry: str, needs_pillow: bool, editor_dir: str) -> list:
    """生成 Nuitka 构建命令行"""
    entry_path = 仓库根目录 / entry
    icon_path = 仓库根目录 / editor_dir / "TKS.ico"
    if not icon_path.exists():
        icon_path = 仓库根目录 / "item_editor" / "TKS.ico"

    cmd = [
        sys.executable, "-m", "nuitka",
        # ── 打包模式 ──
        "--onefile",
        "--assume-yes-for-downloads",    # 自动下载依赖 (如 ccache)

        # ── 输出控制 ──
        f"--output-dir={DIST_DIR}",
        f"--output-filename={name}.exe",

        # ── Windows 配置 ──
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={icon_path}",

        # ── PySide6 插件 ──
        "--enable-plugin=pyside6",

        # ── 包含数据文件 (主题/翻译/图标，烘焙进 exe) ──
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

        # ── 编译优化 ──
        "--lto=yes",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",

        # ── 清理构建中间产物 ──
        "--remove-output",
    ]

    # Pillow 支持
    if needs_pillow:
        cmd.append("--include-package=PIL")

    # 启动器额外数据文件
    if name == "TKSLauncher":
        cmd.extend([
            f"--include-data-files={仓库根目录 / 'tks_launcher_gui' / 'tks_patches.json'}=tks_patches.json",
            f"--include-data-files={仓库根目录 / 'tks_launcher_gui' / 'summon_table.json'}=summon_table.json",
        ])

    # 入口脚本 (必须是最后一个参数)
    cmd.append(str(entry_path))

    return cmd


def build_one(name: str, entry: str, needs_pillow: bool, editor_dir: str,
              verbose: bool = False) -> bool:
    """构建单个编辑器"""
    print(f"\n{'='*60}")
    print(f"  构建: {name}")
    print(f"  入口: {entry}")
    print(f"  模式: Nuitka --onefile")
    print(f"{'='*60}")

    cmd = _build_nuitka_cmd(name, entry, needs_pillow, editor_dir)

    if verbose:
        print(f"  命令: {' '.join(str(c) for c in cmd)}")

    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(仓库根目录))
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  [FAIL] {name} 构建失败 (exit code: {result.returncode}, {elapsed:.1f}s)")
        return False

    print(f"  [OK] {name} 构建成功 ({elapsed:.1f}s)")
    return True


def assemble_release():
    """将构建产物集中到发行目录"""
    print(f"\n{'='*60}")
    print(f"  组装发行目录: {RELEASE_DIR}")
    print(f"{'='*60}")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    assembled = 0
    for name, _, _, _ in EDITORS:
        exe_src = DIST_DIR / f"{name}.exe"
        if not exe_src.exists():
            print(f"  [SKIP] {name}.exe 不存在")
            continue
        shutil.copy2(str(exe_src), str(RELEASE_DIR / f"{name}.exe"))
        size_mb = exe_src.stat().st_size / (1024 * 1024)
        print(f"  [OK] {name}.exe ({size_mb:.1f} MB)")
        assembled += 1

    # 创建 configs/ 和 mods/ 目录
    configs_dir = RELEASE_DIR / "configs"
    mods_dir = RELEASE_DIR / "mods"
    configs_dir.mkdir(exist_ok=True)
    mods_dir.mkdir(exist_ok=True)

    # 复制基线配置文件
    src_configs = 仓库根目录 / "configs"
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(configs_dir / f.name))
            print(f"  [OK] 配置: {f.name}")

    # 汇总
    total_size = sum(
        (RELEASE_DIR / f"{n}.exe").stat().st_size
        for n, _, _, _ in EDITORS
        if (RELEASE_DIR / f"{n}.exe").exists()
    )
    print(f"\n  组装完成: {assembled} 个编辑器")
    print(f"  总计大小: {total_size / (1024*1024):.1f} MB")
    print(f"  发行目录: {RELEASE_DIR}")


def main():
    parser = argparse.ArgumentParser(description="TKS Editors 一键构建 (Nuitka)")
    parser.add_argument("--only", type=str, help="仅构建指定编辑器 (名称)")
    parser.add_argument("--list", action="store_true", help="列出所有可构建编辑器")
    parser.add_argument("--assemble-only", action="store_true", help="仅执行发行目录组装")
    parser.add_argument("--no-assemble", action="store_true", help="构建后不组装")
    parser.add_argument("--jobs", type=int, default=1, help="并行构建数 (默认 1)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.list:
        print("可构建编辑器:")
        for name, entry, pil, _ in EDITORS:
            tag = " [+PIL]" if pil else ""
            print(f"  {name:<24} {entry}{tag}")
        return

    if args.assemble_only:
        assemble_release()
        return

    # 确定构建目标
    if args.only:
        targets = [(n, e, p, d) for n, e, p, d in EDITORS if n == args.only]
        if not targets:
            print(f"[ERROR] 未找到编辑器: {args.only}")
            print(f"  可用: {', '.join(n for n, _, _, _ in EDITORS)}")
            sys.exit(1)
    else:
        targets = EDITORS

    # 确保输出目录存在
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    NUITKA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 设置 Nuitka 缓存目录 (通过环境变量)
    os.environ["NUITKA_CACHE_DIR"] = str(NUITKA_CACHE_DIR)

    # 构建
    success = []
    failed = []
    t_total = time.time()

    if args.jobs > 1 and len(targets) > 1:
        # 并行构建
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futures = {
                pool.submit(build_one, n, e, p, d, args.verbose): n
                for n, e, p, d in targets
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    ok = fut.result()
                    (success if ok else failed).append(name)
                except Exception as exc:
                    print(f"  [FAIL] {name}: {exc}")
                    failed.append(name)
    else:
        # 串行构建
        for name, entry, needs_pillow, editor_dir in targets:
            ok = build_one(name, entry, needs_pillow, editor_dir, args.verbose)
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
