"""
runtime_bootstrap — 运行时引导加载器
====================================
在 PySide6/PIL 导入前调用，从 .lib 归档解压共享运行时到本地缓存。

使用方式（在各编辑器入口最开头）:
    from editor_utils.runtime_bootstrap import bootstrap
    bootstrap()
    # 之后再导入 PySide6 等

支持:
  - 开发环境: 自动跳过（PySide6 已在 sys.path 中）
  - Nuitka 编译环境: 从 .lib 归档解压到 %LOCALAPPDATA%/TKSEditors/runtime/
  - 增量更新: 通过 mtime 对比, 仅解压有变化的归档
"""
import sys
import os
import json
import zipfile


def _detect_app_dir():
    """检测 exe 所在的发行目录 (包含 .lib 文件的目录)。

    Nuitka onefile 模式下 sys.executable 指向临时解压目录，
    需要通过其他方式定位原始 exe 所在目录。
    """
    # 方法1: Nuitka 2.0+ 提供 __nuitka_binary_dir (原始二进制所在目录)
    nuitka_dir = globals().get("__nuitka_binary_dir")
    if nuitka_dir and os.path.isdir(nuitka_dir):
        if os.path.isfile(os.path.join(nuitka_dir, "PySide6.lib")):
            return nuitka_dir

    # 方法2: sys.argv[0] 通常保留原始 exe 路径
    if sys.argv and sys.argv[0]:
        argv0_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.path.isfile(os.path.join(argv0_dir, "PySide6.lib")):
            return argv0_dir

    # 方法3: sys.executable (standalone 模式下有效)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.isfile(os.path.join(exe_dir, "PySide6.lib")):
        return exe_dir

    # 方法4: 从 sys.executable 向上查找 (兼容子目录场景)
    current = exe_dir
    for _ in range(5):
        parent = os.path.dirname(current)
        if parent == current:
            break
        if os.path.isfile(os.path.join(parent, "PySide6.lib")):
            return parent
        current = parent

    # 兜底: 优先使用 sys.argv[0] 目录 (在 Nuitka onefile 下保留原始 exe 路径)
    if sys.argv and sys.argv[0]:
        argv0_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.path.isdir(argv0_dir):
            return argv0_dir
    return exe_dir


# exe 所在目录 (发行目录)
_APP_DIR = _detect_app_dir()


def get_app_dir() -> str:
    """返回 exe 所在发行目录。

    编译环境: 使用 sys.argv[0] 定位原始 exe 路径 (Nuitka onefile/standalone 均保留)。
             不依赖 .lib 文件 — 即使运行时归档丢失也能正确找到 configs/ 和 mods/。
    开发环境: 返回值不可靠 (可能为 Python 安装目录), 调用者应自行用 __file__ 推算。
    """
    # sys.argv[0] 在 Nuitka 下保留原始 exe 路径, 比 sys.executable 更可靠
    # (sys.executable 在 onefile 模式下指向临时解压目录)
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return _APP_DIR


# 运行时缓存目录
_CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "TKSEditors", "runtime"
)

# manifest 文件 (记录已解压归档的状态)
_MANIFEST = os.path.join(_CACHE_DIR, ".manifest.json")

# 需要加载的归档列表 (按依赖顺序)
_RUNTIME_LIBS = [
    "PySide6.lib",
    "QtCore.lib",
    "QtGui.lib",
    "QtWidgets.lib",
    "QtSvg.lib",
    "PIL.lib",
]


def bootstrap():
    """引导加载共享运行时。必须在 PySide6/PIL 导入前调用。

    开发环境下自动跳过（检测到非编译模式且 PySide6 可导入）。
    """
    # ── 开发环境检测: 非编译模式直接跳过 ──
    is_compiled = (
        "__compiled__" in globals()
        or getattr(sys, 'frozen', False)
    )
    if not is_compiled:
        return

    # ── 确保缓存目录存在 ──
    os.makedirs(_CACHE_DIR, exist_ok=True)

    # ── 加载 manifest ──
    manifest = {}
    if os.path.isfile(_MANIFEST):
        try:
            with open(_MANIFEST, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            manifest = {}

    # ── 检查并解压有变化的归档 ──
    updated = False
    for lib_name in _RUNTIME_LIBS:
        lib_path = os.path.join(_APP_DIR, lib_name)
        if not os.path.isfile(lib_path):
            continue

        # 使用文件大小+mtime作为变更标识 (比纯 mtime 更可靠)
        stat = os.stat(lib_path)
        current_key = f"{stat.st_mtime_ns}_{stat.st_size}"

        if manifest.get(lib_name) != current_key:
            # 解压此归档到缓存
            try:
                with zipfile.ZipFile(lib_path, 'r') as zf:
                    zf.extractall(_CACHE_DIR)
                manifest[lib_name] = current_key
                updated = True
            except (zipfile.BadZipFile, OSError) as e:
                print(f"[TKSEditors] 警告: 解压 {lib_name} 失败: {e}", file=sys.stderr)

    # ── 保存 manifest ──
    if updated:
        try:
            with open(_MANIFEST, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
        except OSError:
            pass

    # ── 配置 Python 导入路径 ──
    if _CACHE_DIR not in sys.path:
        sys.path.insert(0, _CACHE_DIR)

    # ── 配置 DLL 搜索路径 (Windows) ──
    # 需要包含: shiboken6/ (shiboken6.abi3.dll), PySide6/ (Qt DLLs, pyside6.abi3.dll)
    shiboken6_dir = os.path.join(_CACHE_DIR, "shiboken6")
    pyside6_dir = os.path.join(_CACHE_DIR, "PySide6")

    # 将所有 DLL 目录加入 PATH (兼容旧版 Python)
    dll_dirs = [_CACHE_DIR, shiboken6_dir, pyside6_dir]
    extra_path = os.pathsep.join(d for d in dll_dirs if os.path.isdir(d))
    os.environ["PATH"] = extra_path + os.pathsep + os.environ.get("PATH", "")

    if hasattr(os, 'add_dll_directory'):
        for d in dll_dirs:
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass

    # ── 设置 Qt 插件路径 ──
    plugins_dir = os.path.join(pyside6_dir, "plugins")
    if os.path.isdir(plugins_dir):
        os.environ["QT_PLUGIN_PATH"] = plugins_dir
