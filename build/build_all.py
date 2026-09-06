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
    pip install -r build/requirements.txt
    需要 C 编译器: MSVC (VS Build Tools)

输出目录:
    dist/TKSEditors/
    ├── TKSItemEditor.exe     (~5-8MB 薄 / ~40-80MB 完整)
    ├── ...                   (不含 TKSLauncherCLI, 该 exe 仅输出到 Winlator 包)
    ├── libs/                 [薄模式] PySide6.lib, QtCore.lib, ...
    ├── configs/
    └── mods/

    dist/Winlator/            [Winlator 专用, 手机玩家部署包; TKSLauncherCLI 唯一发行位置]
    ├── TKSLauncherCLI.exe    CLI 启动器 (~5-10MB)
    ├── launcher_config.json  共享配置模板 (与 GUI 启动器同一文件)
    ├── patches/              补丁定义
    ├── configs/              基线配置 (font_config/summon_table 等)
    └── mods/                 空目录 (用户放置 MOD)

    dist/TKSLauncher/         [玩家精简包, 供不编辑 MOD 的普通玩家使用]
    ├── TKSLauncher.exe       GUI 启动器 (不含 TKSLauncherCLI, 防止启动错)
    ├── TKSConfigsEditor.exe  配置编辑器
    ├── TKSSaveEditor.exe     存档编辑器
    ├── libs/                 运行时归档 (薄 exe 依赖)
    ├── configs/  mods/  tools/
    ├── launcher_config.json  共享配置模板 (GUI 配置后可直接复制到 Winlator)
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

from markdown_it import MarkdownIt

from editors_registry import EDITORS as _ALL_EDITORS

# ═══════════════════════════════════════════════════════════════
# 编辑器配置表 — 单一事实来源见 editors_registry.py (T5 单源化)
# ═══════════════════════════════════════════════════════════════

# (打包名, 入口脚本, 编辑器目录)
EDITORS = [
    (name, f"build/entries/{entry_file}", editor_dir)
    for name, entry_file, _module, editor_dir, _needs_bootstrap in _ALL_EDITORS
]

# 需要 zhconv 数据文件 (zhcdict.json) 的编辑器 — Nuitka 不会自动打包 .json 数据文件
NEEDS_ZHCONV = {
    # search_utils.py: 简繁转换搜索数据
    "TKSItemEditor", "TKSWarpcEditor", "TKSSkillEditor", "TKSShopEditor",
    "TKSTktEditor", "TKSKonEditor", "TKSActEditor", "TKSWardataEditor",
    "TKSBook",
    # save_editor 的文本转换功能
    "TKSSaveEditor",
}

# 薄 exe 必须强制内嵌的 stdlib 模块 — PySide6/shiboken6/PIL 被 --nofollow-import-to
# 排除后由外部 runtime 归档加载, 但它们 import 期依赖的 stdlib 不会被 Nuitka 静态
# 追踪到 (exe 自身代码未引用), 缺失会导致运行时 ModuleNotFoundError (如 tempfile)。
# 清单来源: 扫描 site-packages 中 shiboken6/PySide6/PIL 所有 .py 的顶层 import。
THIN_STDLIB_HIDDEN_IMPORTS = [
    # shiboken6/__init__ + 内嵌 shibokensupport (signature 支持)
    "tempfile", "base64", "marshal", "keyword", "textwrap", "traceback",
    "zipfile", "struct", "contextlib", "typing", "inspect", "enum",
    "functools", "warnings", "pathlib",
    # PIL 各图像插件的惰性导入
    "array", "atexit", "binascii", "calendar", "colorsys", "copy",
    "fractions", "gzip", "itertools", "logging", "math", "mmap",
    "numbers", "operator", "random", "shlex", "shutil", "subprocess",
    "xml.etree.ElementTree", "zlib",
]

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"
WINLATOR_DIR = DIST_DIR / "Winlator"
# 玩家精简包目录 (TKSEditors 子集: 启动器 + 配置/存档编辑器, 供不编辑 MOD 的玩家)
LAUNCHER_DIR = DIST_DIR / "TKSLauncher"
# 玩家精简包包含的 exe (必须是 EDITORS 中的打包名)
LAUNCHER_PACKAGE_EXES = ["TKSLauncher", "TKSConfigsEditor", "TKSSaveEditor", "TKSBook"]
# Winlator 专属 exe: 只输出到 dist/Winlator/, 不进入 TKSEditors 完整包与
# TKSLauncher 精简包, 防止 PC 用户误启动 CLI 版本。
WINLATOR_ONLY_EXES = {"TKSLauncherCLI"}
# .lib 归档统一存放于 libs/ 子目录, 与 exe 分离
LIBS_DIR = RELEASE_DIR / "libs"
# Nuitka C 编译缓存 (其下含 clcache); 固定到仓库内, 避免依赖外部环境变量丢失缓存
NUITKA_CACHE_DIR = BUILD_DIR / "nuitka_cache"
# Nuitka onefile 默认把依赖解压到系统 TEMP 的随机目录。随机目录会导致
# 杀毒软件清理、权限变化或多版本并行启动时出现“找不到依赖”。统一改到
# 当前 Nuitka 版本要求绝对运行时变量只能出现在路径开头，不能把
# {PROGRAM} 放在 {CACHE_DIR} 后面。使用官方推荐模板，并让 PRODUCT
# 通过每个 exe 的唯一产品名隔离不同编辑器的 onefile 缓存。
ONEFILE_TEMP_DIR_SPEC = "{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}"

# onefile 体积优化：这些模块在当前 v2 编辑器和 TKSBook 之外均没有运行时
# 引用。保留 PySide6/PIL 主包，只排除明确不用的功能，避免误伤 Qt/Pillow
# 的基础依赖。若未来编辑器新增对应 import，应从这里移除该项。
ONEFILE_UNUSED_QT_MODULES = (
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtHelp",
    "PySide6.QtXml",
)

# v2 编辑器使用 QImage/QPixmap，不使用 Tkinter、Qt 图像桥接或 Pillow 的
# 文档/系统集成格式。排除这些惰性模块可减少 onefile 中重复的 Python 代码。
ONEFILE_UNUSED_PIL_MODULES = (
    "PIL.ImageTk",
    "PIL.ImageQt",
    "PIL.ImageCms",
    "PIL.ImageGrab",
    "PIL.ImageShow",
    "PIL.ImageWin",
    "PIL.PdfImagePlugin",
    "PIL.PdfParser",
    "PIL.PsdImagePlugin",
    "PIL.WmfImagePlugin",
)
# onefile 每个目标都会独立分析、编译、链接 PySide6/PIL。并发过高会让磁盘、
# 内存和链接器互相争抢，CPU 反而利用率下降；默认只并行 2 个目标。
_CPU_COUNT = os.cpu_count() or 4
_DEFAULT_THIN_PARALLEL = min(len(EDITORS), max(2, _CPU_COUNT // 2))
_DEFAULT_ONEFILE_PARALLEL = min(len(EDITORS), 2)


# ═══════════════════════════════════════════════════════════════
# Windows 版本资源 (降低杀毒软件误报)
# ═══════════════════════════════════════════════════════════════
# 无版本信息的"三无" exe 被杀毒启发式扫描标记的概率显著高于
# 带完整版本信息的 exe; 故为所有构建产物嵌入公司/产品/版本号/描述。

_COMPANY_NAME = "端木子青"
_PRODUCT_NAME = "TKS Editors"
_COPYRIGHT = "免费开源软件，仅供个人学习、研究使用，不得用于商业目的"


def _version_flags(name: str, editor_dir: str) -> list:
    """生成 Windows 版本资源参数 (CompanyName/FileDescription/FileVersion 等)

    版本号与显示名称从 editor_utils/version.py 统一登记表读取,
    读取失败时回退到默认值, 不阻断构建。
    """
    # editor_dir → version.py 中的 app_id (启动器目录名为 tks_launcher_gui)
    app_id = "launcher" if editor_dir == "tks_launcher_gui" else editor_dir
    version = "1.0.0"
    description = name
    try:
        if str(仓库根目录) not in sys.path:
            sys.path.insert(0, str(仓库根目录))
        from editor_utils.version import get_version
        ev = get_version(app_id)
        version = ev.version
        description = ev.app_name
        if name == "TKSLauncherCLI":
            description += " (命令行版)"
    except Exception:
        pass  # 版本表读取失败不阻断构建, 用默认值

    # Nuitka 要求 x.x.x.x 数字格式
    vparts = version.split(".")
    while len(vparts) < 4:
        vparts.append("0")
    win_version = ".".join(vparts[:4])

    return [
        f"--company-name={_COMPANY_NAME}",
        # PRODUCT 同时用于 Nuitka onefile 缓存路径，必须按编辑器隔离。
        f"--product-name={_PRODUCT_NAME}_{name}",
        f"--file-version={win_version}",
        f"--product-version={win_version}",
        f"--file-description={description}",
        f"--copyright={_COPYRIGHT}",
    ]


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
        f"--onefile-tempdir-spec={ONEFILE_TEMP_DIR_SPEC}",
        "--onefile-cache-mode=cached",
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
    ]

    # ── 版本资源 (降低杀毒误报) ──
    cmd.extend(_version_flags(name, editor_dir))

    # ── 强制内嵌外部运行时 (PySide6/shiboken6/PIL) import 期依赖的 stdlib ──
    # 这些模块 exe 自身代码未引用, Nuitka 静态追踪不到, 必须显式包含
    cmd.extend(f"--include-module={m}" for m in THIN_STDLIB_HIDDEN_IMPORTS)

    cmd.extend([
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
    ])

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
        f"--onefile-tempdir-spec={ONEFILE_TEMP_DIR_SPEC}",
        "--onefile-cache-mode=cached",
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

        # ── 排除明确不使用的 Qt/Pillow 功能，降低 onefile 体积 ──
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=scipy",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=unittest",
        *[f"--nofollow-import-to={m}" for m in ONEFILE_UNUSED_QT_MODULES],
        *[f"--nofollow-import-to={m}" for m in ONEFILE_UNUSED_PIL_MODULES],

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

    # ── 版本资源 (降低杀毒误报) ──
    cmd.extend(_version_flags(name, editor_dir))

    # TKSBook 依赖 PySide6.QtMultimedia (game_audio.py 音频复刻);
    # 显式包含确保模块及 multimedia 后端插件被打包
    if name == "TKSBook":
        cmd.append("--include-module=PySide6.QtMultimedia")

    # Pillow 支持 — onefile 模式下所有 GUI 编辑器都依赖 Pillow:
    #   · mat/act/warpc/wardata/tkt/jvg/grp/gxp/spritesheet/font 直接 import PIL
    #   · item/skill/shop/kon/save/configs 经共享工具 editor_utils.jvg_loader 间接依赖
    #   · GUI 启动器经 ui.custom_avatar_dialog 依赖
    # 本函数不用于 CLI 启动器 (CLI 走 _build_cli_cmd), 故无条件包含 PIL,
    # 确保 Pillow 惰性加载的图像插件与 _imaging 扩展被完整打包。
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
        f"--onefile-tempdir-spec={ONEFILE_TEMP_DIR_SPEC}",
        "--onefile-cache-mode=cached",
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
        # cli_launcher.py 以裸包名 `from core...` 导入, 且 tks_launcher_gui 无 __init__.py,
        # 故用顶层包名 core (与运行时 sys.path 上的导入路径一致), 而非 tks_launcher_gui.core。
        "--include-package=core",

        # 包含数据文件 (补丁配置; patches/ 目录由发行组装复制到 exe 同级)
        f"--include-data-files={仓库根目录 / 'configs' / 'summon_table.json'}=configs/summon_table.json",

        # 编译优化
        f"--jobs={jobs}",
        f"--lto={'yes' if release else 'no'}",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--remove-output",
    ]

    # ── 版本资源 (降低杀毒误报) ──
    cmd.extend(_version_flags(name, editor_dir))

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


def _validate_editor_registry() -> None:
    """构建前校验 EDITORS，避免漏打包或入口路径错误。"""
    names = [name for name, _, _ in EDITORS]
    if len(names) != len(set(names)):
        raise RuntimeError("EDITORS 中存在重复的编辑器名称")
    missing = []
    for name, entry, editor_dir in EDITORS:
        entry_path = 仓库根目录 / entry
        source_dir = 仓库根目录 / editor_dir
        if not entry_path.is_file():
            missing.append(f"{name}: 入口不存在 {entry_path}")
        if not source_dir.is_dir():
            missing.append(f"{name}: 编辑器目录不存在 {source_dir}")
    unknown_zhconv = NEEDS_ZHCONV.difference(names)
    if unknown_zhconv:
        missing.append(f"NEEDS_ZHCONV 包含未注册编辑器: {sorted(unknown_zhconv)}")
    cli_in_launcher = WINLATOR_ONLY_EXES.intersection(LAUNCHER_PACKAGE_EXES)
    if cli_in_launcher:
        missing.append(
            f"LAUNCHER_PACKAGE_EXES 不应包含 Winlator 专属 exe: {sorted(cli_in_launcher)}")
    if missing:
        raise RuntimeError("构建注册表校验失败:\n  " + "\n  ".join(missing))


def _validate_runtime_archives() -> None:
    """校验薄 exe 所需的运行时归档确实位于发行目录 libs/。"""
    required = ("PySide6.lib", "QtCore.lib", "QtGui.lib", "QtWidgets.lib", "PIL.lib")
    missing = [name for name in required if not (LIBS_DIR / name).is_file()]
    if missing:
        raise RuntimeError(
            "薄模式运行时归档不完整，缺少: " + ", ".join(missing) +
            f"\n期望目录: {LIBS_DIR}"
        )


def _copy_runtime_tools(destination: Path) -> int:
    """仅复制发行版允许携带的辅助工具资源。"""
    source = 仓库根目录 / "tks_launcher_gui" / "tools"
    if not source.is_dir():
        return 0

    # 严格白名单：发行包只携带这两个工具，明确不包含 ddraw。
    allowed_tools = {"cnc-ddraw", "ddraw-mod"}

    # 每次重新组装前清空目标目录，避免旧版本残留 ddraw 或其它工具。
    if destination.exists():
        shutil.rmtree(str(destination))
    destination.mkdir(parents=True, exist_ok=True)

    copied = 0
    for tool_name in sorted(allowed_tools):
        tool_source = source / tool_name
        if not tool_source.is_dir():
            continue
        for path in tool_source.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(source)
            if any(part == "__pycache__" or part.startswith(".") for part in rel.parts):
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(target))
            copied += 1
    return copied


def _markdown_to_plain_text(markdown: str) -> str:
    """使用 markdown-it-py 将 Markdown 转为适合玩家阅读的纯文本。"""
    tokens = MarkdownIt("commonmark").parse(markdown)
    lines: list[str] = []
    version_heading_seen = False

    def inline_text(token) -> str:
        """提取 inline token 的可读文字，忽略 Markdown 格式标记。"""
        if not token.children:
            return token.content
        parts = []
        for child in token.children:
            if child.type in {"softbreak", "hardbreak"}:
                parts.append("\n")
            elif child.type != "image":
                parts.append(child.content)
        return "".join(parts)

    def add_block(text: str = "") -> None:
        lines.extend(text.rstrip().splitlines() if text.strip() else [""])

    i = 0
    list_stack: list[tuple[str, int]] = []
    pending_list_marker = ""
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            level = int(token.tag[1:])
            inline = tokens[i + 1]
            text = inline_text(inline).strip()
            if level == 1:
                add_block(text)
                add_block()
                add_block("=" * 60)
            elif level == 2 and text.startswith("TKS") and "V" in text:
                if version_heading_seen:
                    while lines and not lines[-1].strip():
                        lines.pop()
                    lines.extend(("", "=" * 60))
                version_heading_seen = True
                add_block(text)
                add_block("=" * 60)
            elif level >= 3:
                add_block()
                add_block(f"【{text}】")
                add_block()
            else:
                add_block(text)
            i += 3
            continue
        if token.type == "paragraph_open":
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                text = inline_text(tokens[i + 1])
                # 版本日期作为独立信息行，与版本标题块留出视觉间距。
                if (
                    len(text.strip()) == 10
                    and text.strip()[4] == "."
                    and text.strip()[7] == "."
                    and text.strip()[:4].isdigit()
                    and text.strip()[5:7].isdigit()
                    and text.strip()[8:].isdigit()
                ):
                    add_block()
                add_block(pending_list_marker + text)
                pending_list_marker = ""
            i += 3
            continue
        if token.type == "blockquote_open":
            i += 1
            continue
        if token.type == "blockquote_close":
            add_block()
            i += 1
            continue
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            add_block()
            list_stack.append(("ordered" if token.type.startswith("ordered") else "bullet", 0))
            i += 1
            continue
        if token.type in {"bullet_list_close", "ordered_list_close"}:
            if list_stack:
                list_stack.pop()
            add_block()
            i += 1
            continue
        if token.type == "list_item_open":
            marker = "- "
            if list_stack and list_stack[-1][0] == "ordered":
                number = list_stack[-1][1] + 1
                list_stack[-1] = ("ordered", number)
                marker = f"{number}. "
            indent = "  " * max(0, len(list_stack) - 1)
            pending_list_marker = indent + marker
            i += 1
            continue
        if token.type == "fence":
            add_block(token.content.rstrip())
            i += 1
            continue
        i += 1

    output = []
    blank = False
    for line in lines:
        if line.strip():
            output.append(line.rstrip())
            blank = False
        elif not blank:
            output.append("")
            blank = True
    return "\n".join(output).strip() + "\n"


def _copy_release_notes(destination: Path) -> bool:
    """将 build/更新记录.md 转为发行目录中的 更新记录.txt。"""
    source = BUILD_DIR / "更新记录.md"
    if not source.is_file():
        print(f"  [WARN] 更新记录不存在: {source}")
        return False
    try:
        markdown = source.read_text(encoding="utf-8")
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "更新记录.txt").write_text(
            _markdown_to_plain_text(markdown), encoding="utf-8"
        )
        return True
    except OSError as exc:
        print(f"  [WARN] 更新记录生成失败: {exc}")
        return False


def _build_release_patches(destination: Path) -> bool:
    """将补丁源码构建为发行版 .tkspatch 文件。"""
    patches_src = 仓库根目录 / "tks_launcher_gui" / "patches"
    if not patches_src.is_dir():
        return False

    source_dirs = [
        p for p in patches_src.iterdir()
        if p.is_dir() and not p.name.startswith("_")
        and (p / "patch.json").is_file()
    ]
    if destination.exists():
        shutil.rmtree(str(destination))
    destination.mkdir(parents=True, exist_ok=True)

    if not source_dirs:
        for patch_file in patches_src.glob("*.tkspatch"):
            shutil.copy2(str(patch_file), str(destination / patch_file.name))
        return bool(list(destination.glob("*.tkspatch")))

    launcher_dir = str(仓库根目录 / "tks_launcher_gui")
    if launcher_dir not in sys.path:
        sys.path.insert(0, launcher_dir)
    try:
        from patcher.build_patches import build_all_patches
        return build_all_patches(str(patches_src), str(destination))
    except Exception as exc:
        print(f"  [ERROR] 补丁构建出错: {exc}")
        return False


def _copy_built_patches(destination: Path) -> bool:
    """复制 TKSEditors 已构建的生产版补丁到其他发行包。"""
    source = RELEASE_DIR / "patches"
    if not source.is_dir():
        return False
    if destination.exists():
        shutil.rmtree(str(destination))
    shutil.copytree(str(source), str(destination))
    return bool(list(destination.glob("*.tkspatch")))


def _should_skip_build(name: str, source_files: list) -> bool:
    """增量构建检查: 若发行目录 exe 比所有源文件新, 则跳过

    以发行目录 (RELEASE_DIR) 的 exe 作为增量标记 — 构建产物在 assemble
    阶段会从 dist/ 根目录移入发行目录, dist/ 根目录不再保留中间 exe。
    Winlator 专属 exe 的最终位置在 WINLATOR_DIR, 以其作为增量标记。
    """
    marker_dir = WINLATOR_DIR if name in WINLATOR_ONLY_EXES else RELEASE_DIR
    exe_path = marker_dir / f"{name}.exe"
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
    if not onefile and name != "TKSLauncherCLI":
        _validate_runtime_archives()
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
    # 固定 Nuitka/编译器缓存目录，保证增量 C 编译缓存稳定命中。
    env.setdefault("NUITKA_CACHE_DIR", str(NUITKA_CACHE_DIR))
    env.setdefault("CLCACHE_DIR", str(NUITKA_CACHE_DIR / "clcache"))
    env.setdefault("CCACHE_DIR", str(NUITKA_CACHE_DIR / "ccache"))

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


def build_runtime(force: bool = False):
    """构建运行时归档 (.lib)"""
    print(f"\n{'='*60}")
    print(f"  构建运行时归档")
    print(f"{'='*60}")
    cmd = [sys.executable, str(BUILD_DIR / "build_runtime.py"), "--output", str(LIBS_DIR)]
    if force:
        cmd.append("--force")
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

    # Winlator 专属 exe 不进入 TKSEditors 完整包; 清理旧版本遗留
    for name in sorted(WINLATOR_ONLY_EXES):
        stale = RELEASE_DIR / f"{name}.exe"
        if stale.exists():
            stale.unlink()
            print(f"  [清理] 移除旧版 {name}.exe (Winlator 专属, 仅输出到 dist/Winlator)")

    assembled = 0
    for name, _, _ in EDITORS:
        if name in WINLATOR_ONLY_EXES:
            # CLI 启动器由 assemble_winlator() 单独组装, 不出现在 TKSEditors
            print(f"  [WINLATOR] {name}.exe 仅输出到 Winlator 部署包")
            continue
        exe_src = DIST_DIR / f"{name}.exe"
        exe_dst = RELEASE_DIR / f"{name}.exe"
        if exe_src.exists():
            # 移动 (而非复制) 构建产物到发行目录, 避免 dist/ 根目录残留无法独立运行的中间 exe
            # (薄 exe 需与同级 libs/ 归档共存, 位于 dist/ 根目录时缺少 libs/ 无法启动)
            os.replace(str(exe_src), str(exe_dst))
            size_mb = exe_dst.stat().st_size / (1024 * 1024)
            print(f"  [OK] {name}.exe ({size_mb:.1f} MB)")
            assembled += 1
        elif exe_dst.exists():
            # 增量跳过: 中间产物已在上次构建时移入发行目录, 此处无需再处理
            size_mb = exe_dst.stat().st_size / (1024 * 1024)
            print(f"  [SKIP] {name}.exe ({size_mb:.1f} MB, 未变更)")
            assembled += 1
        else:
            print(f"  [SKIP] {name}.exe 不存在 (构建失败或未构建)")

    # configs/ 和 mods/ 和 libs/
    (RELEASE_DIR / "configs").mkdir(exist_ok=True)
    (RELEASE_DIR / "mods").mkdir(exist_ok=True)
    (RELEASE_DIR / "libs").mkdir(exist_ok=True)

    # 复制基线配置
    src_configs = 仓库根目录 / "configs"
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(RELEASE_DIR / "configs" / f.name))

    # 构建补丁；生产目录只保留 .tkspatch，不保留源码目录。
    patches_dst = RELEASE_DIR / "patches"
    print("  [构建] 开始构建补丁...")
    patch_ok = _build_release_patches(patches_dst)
    patch_count = len(list(patches_dst.glob("*.tkspatch"))) if patches_dst.is_dir() else 0
    if patch_ok:
        print(f"  [OK] patches/ ({patch_count} 个 .tkspatch)")
    else:
        print("  [WARN] 补丁构建失败，但不影响启动器运行")

    # 复制 launcher_config.json (GUI/CLI 共享配置模板)
    launcher_cfg_src = 仓库根目录 / "tks_launcher_gui" / "launcher_config.json"
    if launcher_cfg_src.exists():
        shutil.copy2(str(launcher_cfg_src), str(RELEASE_DIR / "launcher_config.json"))
        print(f"  [OK] launcher_config.json")

    # 复制 tools/ 辅助工具目录 (仅 cnc-ddraw / ddraw-mod)
    tools_src = 仓库根目录 / "tks_launcher_gui" / "tools"
    if tools_src.is_dir():
        tools_dst = RELEASE_DIR / "tools"
        file_count = _copy_runtime_tools(tools_dst)
        print(f"  [OK] tools/ ({file_count} 个文件)")

    if _copy_release_notes(RELEASE_DIR):
        print("  [OK] 更新记录.txt")

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


def assemble_winlator():
    """组装 Winlator 发行目录 (CLI 启动器 + 必要配置)

    此目录专为 Winlator (Wine on Android) 用户设计，包含:
    - TKSLauncherCLI.exe    无 GUI 的命令行启动器 (唯一发行位置)
    - launcher_config.json  共享配置模板 (与 PC 版 GUI 启动器同一文件)
    - patches/              补丁定义
    - configs/summon_table.json  召唤表
    - mods/                 MOD 目录 (空, 供用户放置)
    """
    print(f"\n{'='*60}")
    print(f"  组装 Winlator 发行目录: {WINLATOR_DIR}")
    print(f"{'='*60}")

    # CLI exe 来源: 本次构建产物 (dist/ 根目录); 增量跳过时沿用
    # Winlator 目录中的现有副本 (须在清空目录前抢救出来)
    cli_src = DIST_DIR / "TKSLauncherCLI.exe"
    if not cli_src.exists():
        old_cli = WINLATOR_DIR / "TKSLauncherCLI.exe"
        if old_cli.exists():
            shutil.copy2(str(old_cli), str(cli_src))

    # 清空并重建 Winlator 目录 (确保干净)
    if WINLATOR_DIR.exists():
        shutil.rmtree(str(WINLATOR_DIR))
    WINLATOR_DIR.mkdir(parents=True, exist_ok=True)

    assembled = []

    # 1. 复制 TKSLauncherCLI.exe
    if cli_src.exists():
        shutil.copy2(str(cli_src), str(WINLATOR_DIR / "TKSLauncherCLI.exe"))
        size_mb = cli_src.stat().st_size / (1024 * 1024)
        print(f"  [OK] TKSLauncherCLI.exe ({size_mb:.1f} MB)")
        assembled.append("TKSLauncherCLI.exe")
        # 最终产物已在 Winlator 目录; 清理 dist 根目录中间副本 (增量标记
        # 以 WINLATOR_DIR 为准, 无需保留)
        if cli_src != WINLATOR_DIR / "TKSLauncherCLI.exe":
            cli_src.unlink()
    else:
        print(f"  [WARN] TKSLauncherCLI.exe 不存在 (未构建或构建失败)")

    # 2. 复制 launcher_config.json (配置模板)
    launcher_cfg_src = 仓库根目录 / "tks_launcher_gui" / "launcher_config.json"
    if launcher_cfg_src.exists():
        shutil.copy2(str(launcher_cfg_src), str(WINLATOR_DIR / "launcher_config.json"))
        print(f"  [OK] launcher_config.json")
        assembled.append("launcher_config.json")

    # 3. 复制外置补丁目录 (CLI 同样使用 patches/ 的 ZIP 型 .tkspatch 作为唯一来源)
    if _copy_built_patches(WINLATOR_DIR / "patches"):
        patch_count = len(list((WINLATOR_DIR / "patches").glob("*.tkspatch")))
        print(f"  [OK] patches/ ({patch_count} 个 .tkspatch)")
        assembled.append("patches/")

    # 4. 复制全部基线配置 (configs/, 与发行目录一致)
    configs_dst = WINLATOR_DIR / "configs"
    configs_dst.mkdir(exist_ok=True)
    src_configs = 仓库根目录 / "configs"
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(configs_dst / f.name))
        print(f"  [OK] configs/")
        assembled.append("configs/")

    if _copy_release_notes(WINLATOR_DIR):
        print("  [OK] 更新记录.txt")
        assembled.append("更新记录.txt")

    # 5. 创建空 mods/ 目录 (供用户放置 MOD 文件)
    mods_dst = WINLATOR_DIR / "mods"
    mods_dst.mkdir(exist_ok=True)
    print(f"  [OK] mods/ (空目录, 供用户放置 .tksmod/.tksmodpak)")

    # 汇总
    total_size = sum(
        f.stat().st_size for f in WINLATOR_DIR.rglob("*")
        if f.is_file()
    )
    print(f"\n  Winlator 组装完成: {len(assembled)} 个文件")
    print(f"  总大小: {total_size / (1024*1024):.1f} MB")
    print(f"  目录: {WINLATOR_DIR}")


def assemble_launcher():
    """组装 TKSLauncher 玩家精简包 (TKSEditors 的子集)

    面向不编辑 MOD 的普通玩家, 仅保留日常使用的三个程序:
    - TKSLauncher.exe       GUI 启动器 (打补丁 / 应用 MOD / 启动游戏)
    - TKSConfigsEditor.exe  配置编辑器
    - TKSSaveEditor.exe     存档编辑器
    及其运行所需的支撑文件 (libs/ 运行时归档、configs/、tools/、补丁定义等)。
    """
    print(f"\n{'='*60}")
    print(f"  组装 TKSLauncher 玩家精简包: {LAUNCHER_DIR}")
    print(f"{'='*60}")

    # 清空并重建 (确保干净, 不残留旧版文件)
    if LAUNCHER_DIR.exists():
        shutil.rmtree(str(LAUNCHER_DIR))
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)

    assembled = []

    # 1. 复制精简包 exe (从发行目录复制, 保留 TKSEditors 完整版)
    for name in LAUNCHER_PACKAGE_EXES:
        exe_src = RELEASE_DIR / f"{name}.exe"
        if exe_src.exists():
            shutil.copy2(str(exe_src), str(LAUNCHER_DIR / f"{name}.exe"))
            size_mb = exe_src.stat().st_size / (1024 * 1024)
            print(f"  [OK] {name}.exe ({size_mb:.1f} MB)")
            assembled.append(f"{name}.exe")
        else:
            print(f"  [WARN] {name}.exe 不存在 (未构建或构建失败)")

    # 2. 复制 libs/ 运行时归档 (薄 exe 必需; 完整 onefile 模式下无此目录)
    if LIBS_DIR.is_dir():
        libs_dst = LAUNCHER_DIR / "libs"
        shutil.copytree(str(LIBS_DIR), str(libs_dst), dirs_exist_ok=True)
        lib_count = sum(1 for p in libs_dst.iterdir() if p.is_file())
        print(f"  [OK] libs/ ({lib_count} 个归档)")
        assembled.append("libs/")

    # 3. 复制 configs/ 基线配置
    src_configs = 仓库根目录 / "configs"
    configs_dst = LAUNCHER_DIR / "configs"
    configs_dst.mkdir(exist_ok=True)
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(configs_dst / f.name))
        print(f"  [OK] configs/")
        assembled.append("configs/")

    # 复制外置补丁目录 (与开发模式共用同一套 ZIP 型 .tkspatch)
    if _copy_built_patches(LAUNCHER_DIR / "patches"):
        patch_count = len(list((LAUNCHER_DIR / "patches").glob("*.tkspatch")))
        print(f"  [OK] patches/ ({patch_count} 个 .tkspatch)")
        assembled.append("patches/")

    # 4. 复制 tools/ 辅助工具 (启动器运行时按需注入游戏目录)
    tools_src = 仓库根目录 / "tks_launcher_gui" / "tools"
    if tools_src.is_dir():
        tools_dst = LAUNCHER_DIR / "tools"
        file_count = _copy_runtime_tools(tools_dst)
        print(f"  [OK] tools/ ({file_count} 个文件)")
        assembled.append("tools/")

    if _copy_release_notes(LAUNCHER_DIR):
        print("  [OK] 更新记录.txt")
        assembled.append("更新记录.txt")

    # 5. 复制启动器共享配置模板 (与 CLI/Winlator 包同一文件,
    #    玩家配置完成后可直接复制到 Winlator 游戏目录)
    for fname in ("launcher_config.json",):
        src = 仓库根目录 / "tks_launcher_gui" / fname
        if src.exists():
            shutil.copy2(str(src), str(LAUNCHER_DIR / fname))
            print(f"  [OK] {fname}")
            assembled.append(fname)

    # 6. 创建空 mods/ 目录 (玩家放置他人制作的 MOD, 由启动器应用)
    (LAUNCHER_DIR / "mods").mkdir(exist_ok=True)
    print(f"  [OK] mods/ (空目录, 供玩家放置 .tksmod/.tksmodpak)")

    # 汇总
    total_size = sum(
        f.stat().st_size for f in LAUNCHER_DIR.rglob("*")
        if f.is_file()
    )
    print(f"\n  TKSLauncher 组装完成: {len(assembled)} 项")
    print(f"  总大小: {total_size / (1024*1024):.1f} MB")
    print(f"  目录: {LAUNCHER_DIR}")


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
    per_job = args.nuitka_jobs or max(1, cpu_count // max_workers)

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
    parser.add_argument("--parallel", type=int, default=None,
                        help="并行构建 N 个编辑器；onefile 默认 2，薄模式默认按 CPU/2")
    parser.add_argument("--nuitka-jobs", type=int, default=None,
                        help="每个 Nuitka 进程使用的 C 编译任务数；默认按 CPU/进程数分配")
    parser.add_argument("--force", action="store_true",
                        help="强制全量构建, 跳过增量检查")
    args = parser.parse_args()

    try:
        _validate_editor_registry()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    if args.list:
        print("可构建编辑器:")
        for name, entry, _ in EDITORS:
            tag = " [CLI, 仅 Winlator 包]" if name in WINLATOR_ONLY_EXES else ""
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
        build_runtime(args.force)
        return

    # 薄模式默认总是先构建运行时归档再打包 exe (除非 --onefile 完整模式)
    # --all 标志向后兼容: 等同于默认薄模式行为
    if not args.onefile:
        if not build_runtime(args.force):
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

    # onefile 默认低目标并发、高单目标并行，避免多个大型 LTO 链接任务互相拖慢。
    if args.parallel is None:
        args.parallel = _DEFAULT_ONEFILE_PARALLEL if args.onefile else _DEFAULT_THIN_PARALLEL
    if args.nuitka_jobs is not None and args.nuitka_jobs < 1:
        print("[ERROR] --nuitka-jobs 必须大于 0")
        sys.exit(1)

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
        # 额外输出 Winlator 目录 (CLI 启动器 + 必要配置)
        assemble_winlator()
        # 额外输出 TKSLauncher 玩家精简包 (启动器 + 配置/存档编辑器)
        assemble_launcher()


if __name__ == "__main__":
    main()
