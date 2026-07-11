"""
build_all.py — TKS Editors 一键构建脚本 (Nuitka)
==================================================
支持两种打包模式:

  薄 exe (默认) — 大型共享模块 (PySide6/PIL) 由 .lib 归档提供，不编译进 exe
    python build/build_all.py                  # 构建运行时归档 + 全部薄 exe
    python build/build_all.py --only TKSItemEditor   # 仅构建指定编辑器 (含归档)
    python build/build_all.py --runtime        # 仅生成运行时归档 (.lib)
    python build/build_all.py --all            # 等同默认 (归档 + 全部 exe, 向后兼容)

  完整 exe (--onefile) — PySide6/PIL 烘焙进每个 exe，无外部 .lib 依赖
    python build/build_all.py --onefile                 # 调试模式: --lto=no --jobs=8 (快速)
    python build/build_all.py --onefile --release       # 发布模式: --lto=yes (链接时优化, 更小体积)
    python build/build_all.py --onefile --only TKSLauncher --release  # 仅构建指定 (发布)

  python build/build_all.py --list             # 列出所有可构建编辑器

构建优化:
    python build/build_all.py --parallel 3     # 并行构建 3 个 exe (加速总构建)
    python build/build_all.py --force          # 强制全量构建, 跳过增量检查

前置条件:
    pip install nuitka ordered-set zstandard PySide6 Pillow
    需要 C 编译器: MSVC (VS Build Tools)

输出目录:
    dist/TKSEditors/
    ├── TKSItemEditor.exe     (~5-8MB 薄 / ~40-80MB 完整)
    ├── ...
    ├── libs/                 [薄模式] PySide6.lib, QtCore.lib, ...
    ├── configs/
    └── mods/
"""
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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

# 需要 zhconv 数据文件 (zhcdict.json) 的编辑器 — Nuitka 不会自动打包 .json 数据文件
NEEDS_ZHCONV = {"TKSSaveEditor"}

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"
# .lib 归档统一存放于 libs/ 子目录, 与 exe 分离
LIBS_DIR = RELEASE_DIR / "libs"


def _build_thin_cmd(name: str, entry: str, editor_dir: str,
                    release: bool = False, jobs: int = 8) -> list:
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

        # ── 包含 zstandard (用于 .lib 归档解压) ──
        "--include-package=zstandard",

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
        f"--jobs={jobs}",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
    ]

    # zhconv 数据文件 (zhcdict.json) — 运行时按需加载, Nuitka 不会自动打包
    if name in NEEDS_ZHCONV:
        cmd.append("--include-package-data=zhconv")

    # ── 清理 ──
    cmd.extend([
        "--remove-output",

        # ── 入口脚本 ──
        str(entry_path),
    ])

    return cmd


def _build_onefile_cmd(name: str, entry: str, editor_dir: str,
                       release: bool = False, jobs: int = 8) -> list:
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
        f"--jobs={jobs}",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",

        # ── 清理 ──
        "--remove-output",
    ]

    # Pillow 支持
    if name in NEEDS_PILLOW:
        cmd.append("--include-package=PIL")

    # zhconv 数据文件 (zhcdict.json) — 运行时按需加载, Nuitka 不会自动打包
    if name in NEEDS_ZHCONV:
        cmd.append("--include-package-data=zhconv")

    # 入口脚本 (必须是最后一个参数)
    cmd.append(str(entry_path))

    return cmd


def _build_cli_cmd(name: str, entry: str, editor_dir: str,
                   release: bool = False, jobs: int = 8) -> list:
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
        f"--include-data-files={仓库根目录 / 'configs' / 'summon_table.json'}=configs/summon_table.json",

        # 编译优化
        f"--jobs={jobs}",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--remove-output",
    ]

    cmd.append(str(entry_path))
    return cmd


# ═══════════════════════════════════════════════════════════════
# 增量构建支持
# ═══════════════════════════════════════════════════════════════

def _collect_source_files(entry: str, editor_dir: str) -> list:
    """收集影响构建的源文件 (入口 + editor_utils + 编辑器目录 + 构建脚本)"""
    files = [仓库根目录 / entry]

    # editor_utils 整个包 (所有薄 exe 共享)
    utils_dir = 仓库根目录 / "editor_utils"
    if utils_dir.exists():
        files.extend(utils_dir.rglob("*.py"))

    # 编辑器目录所有 .py
    editor_path = 仓库根目录 / editor_dir
    if editor_path.exists():
        files.extend(editor_path.rglob("*.py"))

    # 构建脚本本身 (修改构建参数也应触发重建)
    files.append(BUILD_DIR / "build_all.py")
    files.append(BUILD_DIR / "gen_entries.py")

    return [f for f in files if f.exists()]


def _should_skip_build(name: str, source_files: list) -> bool:
    """增量构建检查: 若 exe 比所有源文件新, 则跳过"""
    exe_path = DIST_DIR / f"{name}.exe"
    if not exe_path.exists():
        return False
    exe_mtime = exe_path.stat().st_mtime
    for f in source_files:
        try:
            if f.stat().st_mtime > exe_mtime:
                return False
        except OSError:
            return False
    return True


# ═══════════════════════════════════════════════════════════════
# 构建逻辑
# ═══════════════════════════════════════════════════════════════

def build_one(name: str, entry: str, editor_dir: str,
              onefile: bool = False, verbose: bool = False,
              release: bool = False, force: bool = False,
              parallel: bool = False, nuitka_jobs: int = None,
              log_dir: Path = None) -> tuple:
    """构建单个 exe (薄模式或完整 onefile 模式)

    返回 (success: bool, elapsed: float)
    """
    # 增量构建检查
    if not force:
        source_files = _collect_source_files(entry, editor_dir)
        if _should_skip_build(name, source_files):
            print(f"  [SKIP] {name} (源文件未变更)")
            return True, 0.0

    # CLI 启动器使用专用构建 (无 PySide6)
    is_cli = (name == "TKSLauncherCLI")
    if is_cli:
        mode_label = "CLI 极简 (无 PySide6/Qt)"
    elif onefile:
        mode_label = "完整 onefile (PySide6/PIL 内嵌)"
    else:
        mode_label = "薄 exe (无 PySide6/PIL)"

    jobs = nuitka_jobs if nuitka_jobs else 8
    lto_label = "LTO=yes" if release else "LTO=no (调试加速)"
    print(f"\n{'='*60}")
    print(f"  构建: {name}")
    print(f"  入口: {entry}")
    print(f"  模式: Nuitka --onefile ({mode_label}, {lto_label}, jobs={jobs})")
    print(f"{'='*60}")

    if is_cli:
        cmd = _build_cli_cmd(name, entry, editor_dir, release, jobs)
    elif onefile:
        cmd = _build_onefile_cmd(name, entry, editor_dir, release, jobs)
    else:
        cmd = _build_thin_cmd(name, entry, editor_dir, release, jobs)

    if verbose:
        print(f"  命令: {' '.join(str(c) for c in cmd)}")

    # 构建环境: 将编辑器目录加入 PYTHONPATH
    # 解决部分编辑器内部使用裸包名导入 (from ui.xxx, from core.xxx 等)
    env = os.environ.copy()
    extra_path = str(仓库根目录 / editor_dir)
    env["PYTHONPATH"] = extra_path + os.pathsep + env.get("PYTHONPATH", "")

    t0 = time.time()

    # 并行模式下重定向输出到 log 文件, 避免输出交错
    if parallel and log_dir:
        log_path = log_dir / f"{name}.log"
        with open(log_path, 'w', encoding='utf-8') as log_file:
            result = subprocess.run(cmd, cwd=str(仓库根目录), env=env,
                                    stdout=log_file, stderr=subprocess.STDOUT)
        elapsed = time.time() - t0
        if result.returncode != 0:
            print(f"  [FAIL] {name} ({elapsed:.1f}s) — 日志: {log_path}")
            return False, elapsed
        print(f"  [OK] {name} ({elapsed:.1f}s)")
        return True, elapsed
    else:
        result = subprocess.run(cmd, cwd=str(仓库根目录), env=env)
        elapsed = time.time() - t0
        if result.returncode != 0:
            print(f"  [FAIL] {name} 构建失败 (exit code: {result.returncode}, {elapsed:.1f}s)")
            return False, elapsed
        print(f"  [OK] {name} 构建成功 ({elapsed:.1f}s)")
        return True, elapsed


def build_runtime():
    """构建运行时归档 (.lib)"""
    print(f"\n{'='*60}")
    print(f"  构建运行时归档")
    print(f"{'='*60}")
    cmd = [sys.executable, str(BUILD_DIR / "build_runtime.py"), "--output", str(LIBS_DIR)]
    result = subprocess.run(cmd, cwd=str(仓库根目录))
    return result.returncode == 0


# ═══════════════════════════════════════════════════════════════
# 构建信息生成
# ═══════════════════════════════════════════════════════════════

def _md5(path: Path, chunk_size: int = 65536) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _get_git_commit() -> str:
    """获取 Git commit hash (失败返回空字符串)"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(仓库根目录), capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def _get_nuitka_version() -> str:
    """获取 Nuitka 版本"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True, timeout=10
        )
        # Nuitka 版本信息在 stderr
        out = result.stderr.strip() or result.stdout.strip()
        return out.split('\n')[0] if out else "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _generate_build_info(onefile: bool, release: bool, success: list, failed: list):
    """生成构建信息文件 build_info.json"""
    info = {
        "build_time": datetime.now().isoformat(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "nuitka_version": _get_nuitka_version(),
        "git_commit": _get_git_commit(),
        "build_mode": "onefile" if onefile else "thin",
        "release": release,
        "editors_total": len(EDITORS),
        "editors_success": len(success),
        "editors_failed": len(failed),
        "failed_names": failed,
        "files": [],
    }

    # 记录发行目录所有文件
    if RELEASE_DIR.exists():
        for f in sorted(RELEASE_DIR.iterdir()):
            if f.is_file():
                stat = f.stat()
                info["files"].append({
                    "name": f.name,
                    "size": stat.st_size,
                    "md5": _md5(f),
                })
        # 扫描 libs/ 子目录 (.lib 归档)
        if LIBS_DIR.exists():
            for f in sorted(LIBS_DIR.iterdir()):
                if f.is_file():
                    stat = f.stat()
                    info["files"].append({
                        "name": f"libs/{f.name}",
                        "size": stat.st_size,
                        "md5": _md5(f),
                    })

    info_path = RELEASE_DIR / "build_info.json"
    import json
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    print(f"  [OK] build_info.json ({info['editors_success']}/{info['editors_total']} 编辑器)")


# ═══════════════════════════════════════════════════════════════
# 发行目录组装
# ═══════════════════════════════════════════════════════════════

def assemble_release(onefile: bool = False, release: bool = False,
                     success: list = None, failed: list = None):
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
        # 增量复制: 源和目标 mtime+size 一致则跳过
        exe_dst = RELEASE_DIR / f"{name}.exe"
        if exe_dst.exists():
            src_stat = exe_src.stat()
            dst_stat = exe_dst.stat()
            if src_stat.st_size == dst_stat.st_size and src_stat.st_mtime <= dst_stat.st_mtime:
                size_mb = dst_stat.st_size / (1024 * 1024)
                print(f"  [SKIP] {name}.exe ({size_mb:.1f} MB, 未变更)")
                assembled += 1
                continue
        shutil.copy2(str(exe_src), str(RELEASE_DIR / f"{name}.exe"))
        size_mb = exe_src.stat().st_size / (1024 * 1024)
        print(f"  [OK] {name}.exe ({size_mb:.1f} MB)")
        assembled += 1

    # configs/ 和 mods/ 和 libs/
    (RELEASE_DIR / "configs").mkdir(exist_ok=True)
    (RELEASE_DIR / "mods").mkdir(exist_ok=True)
    (RELEASE_DIR / "libs").mkdir(exist_ok=True)

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

    # summon_table.json 已由上方 configs/*.json glob 复制到 RELEASE_DIR/configs/

    # 汇总
    total_size = sum(
        f.stat().st_size for f in RELEASE_DIR.iterdir()
        if f.is_file()
    )
    # 包含 libs/ 子目录 (.lib 归档)
    if LIBS_DIR.exists():
        total_size += sum(
            f.stat().st_size for f in LIBS_DIR.iterdir()
            if f.is_file()
        )
    print(f"\n  组装完成: {assembled} 个编辑器")
    print(f"  发行目录总大小: {total_size / (1024*1024):.1f} MB")
    print(f"  发行目录: {RELEASE_DIR}")

    # 生成构建信息
    _generate_build_info(onefile, release, success or [], failed or [])


# ═══════════════════════════════════════════════════════════════
# 并行构建
# ═══════════════════════════════════════════════════════════════

def _build_parallel(targets: list, args) -> tuple:
    """并行构建多个 exe

    策略: 总 CPU 核心数 / 并发数 = 每个 Nuitka 的 jobs 数
    避免 CPU 过载。
    """
    cpu_count = os.cpu_count() or 8
    max_workers = min(args.parallel, len(targets))
    per_job = max(1, cpu_count // max_workers)

    log_dir = DIST_DIR / "build_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  并行构建: {max_workers} 并发 × {per_job} jobs/进程 "
          f"(共 {cpu_count} CPU 核心)")
    print(f"  构建日志: {log_dir}/<EditorName>.log\n")

    success = []
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                build_one, name, entry, editor_dir,
                args.onefile, args.verbose, args.release,
                args.force, True, per_job, log_dir
            ): name
            for name, entry, editor_dir in targets
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                ok, _ = future.result()
                (success if ok else failed).append(name)
            except Exception as e:
                print(f"  [ERROR] {name}: {e}")
                failed.append(name)

    return success, failed


def _build_serial(targets: list, args) -> tuple:
    """串行构建多个 exe"""
    success = []
    failed = []
    for name, entry, editor_dir in targets:
        ok, _ = build_one(name, entry, editor_dir, args.onefile, args.verbose,
                          args.release, args.force)
        (success if ok else failed).append(name)
    return success, failed


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="TKS Editors 一键构建 (Nuitka)")
    parser.add_argument("--onefile", action="store_true",
                        help="完整单文件模式: PySide6/PIL 编译进 exe (无外部 .lib 依赖)")
    parser.add_argument("--only", type=str, help="仅构建指定编辑器")
    parser.add_argument("--runtime", action="store_true",
                        help="仅生成运行时归档 (仅薄模式)")
    parser.add_argument("--all", action="store_true",
                        help="等同默认行为 (薄模式自动构建归档+exe, 向后兼容)")
    parser.add_argument("--list", action="store_true", help="列出所有可构建编辑器")
    parser.add_argument("--no-assemble", action="store_true", help="构建后不组装发行目录")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--release", action="store_true",
                        help="发布模式: --lto=yes (链接时优化, 更小体积, 构建更慢)")
    parser.add_argument("--parallel", type=int, default=0,
                        help="并行构建 N 个编辑器 (0=串行, 推荐 2-4)")
    parser.add_argument("--force", action="store_true",
                        help="强制全量构建, 跳过增量检查")
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

    # 生成入口脚本 (确保最新) — 检查返回码, 失败则中止
    gen_result = subprocess.run(
        [sys.executable, str(BUILD_DIR / "gen_entries.py")],
        cwd=str(仓库根目录), capture_output=True, text=True
    )
    if gen_result.returncode != 0:
        print(f"[ERROR] 入口脚本生成失败 (exit code: {gen_result.returncode})")
        print(f"  stdout: {gen_result.stdout}")
        print(f"  stderr: {gen_result.stderr}")
        sys.exit(1)

    if args.runtime:
        build_runtime()
        return

    # 薄模式默认总是先构建运行时归档再打包 exe (除非 --onefile 完整模式)
    # --all 标志向后兼容: 等同于默认薄模式行为
    if not args.onefile:
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
    t_total = time.time()

    if args.parallel > 0 and len(targets) > 1:
        success, failed = _build_parallel(targets, args)
    else:
        success, failed = _build_serial(targets, args)

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
        assemble_release(args.onefile, args.release, success, failed)


if __name__ == "__main__":
    main()
