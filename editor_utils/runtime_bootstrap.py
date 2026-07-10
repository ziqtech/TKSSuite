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
  - 增量更新: 通过 mtime+size 对比, 仅解压有变化的归档
  - 格式自动检测: zstd (新) / zip (旧) 向后兼容
  - 缓存清理: 升级归档时自动删除旧版本文件, 避免残留
"""
import json
import os
import sys
import tarfile
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

# manifest 文件 (记录已解压归档的状态 + 文件列表, 用于增量清理)
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


# ═══════════════════════════════════════════════════════════════
# 归档格式检测与解压
# ═══════════════════════════════════════════════════════════════

# zstd magic number: 28 b5 2f fd
_ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
# zip magic number: PK\x03\x04
_ZIP_MAGIC = b'PK\x03\x04'


def _detect_archive_format(path: str) -> str:
    """检测归档格式: 'zst' / 'zip' / 'unknown'"""
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
    except OSError:
        return 'unknown'
    if magic == _ZSTD_MAGIC:
        return 'zst'
    if magic == _ZIP_MAGIC:
        return 'zip'
    return 'unknown'


def _extract_archive(lib_path: str, cache_dir: str) -> list:
    """解压归档到缓存目录, 返回解压的文件列表 (arcname)

    自动检测 zst / zip 格式。
    """
    fmt = _detect_archive_format(lib_path)
    extracted_files = []

    if fmt == 'zip':
        with zipfile.ZipFile(lib_path, 'r') as zf:
            for member in zf.infolist():
                if not member.is_dir():
                    zf.extract(member, cache_dir)
                    # 统一用正斜杠
                    extracted_files.append(member.filename.replace("\\", "/"))

    elif fmt == 'zst':
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        with open(lib_path, 'rb') as f:
            with dctx.stream_reader(f) as reader:
                with tarfile.open(fileobj=reader, mode='r|') as tar:
                    for member in tar:
                        if member.isfile():
                            tar.extract(member, cache_dir)
                            extracted_files.append(member.name.replace("\\", "/"))
    else:
        raise ValueError(f"未知归档格式: {lib_path}")

    return extracted_files


def _remove_stale_files(old_files: list, cache_dir: str):
    """删除旧版本归档中的过期文件 (缓存清理)"""
    for arcname in old_files:
        file_path = os.path.join(cache_dir, arcname.replace("/", os.sep))
        try:
            os.remove(file_path)
        except OSError:
            pass  # 文件可能已被删除或不复存在


def _cleanup_empty_dirs(cache_dir: str):
    """清理缓存目录中的空目录"""
    for root, dirs, _ in os.walk(cache_dir, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            try:
                os.rmdir(dir_path)
            except OSError:
                pass  # 目录非空或不存在


# ═══════════════════════════════════════════════════════════════
# 主引导逻辑
# ═══════════════════════════════════════════════════════════════

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
    # manifest 结构: { "PySide6.lib": {"key": "...", "files": ["PySide6/...", ...]}, ... }
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

        lib_info = manifest.get(lib_name, {})
        # 向后兼容: 旧版 manifest 值是字符串 (直接为 key), 新版是字典 {"key":..., "files":[...]}
        # 检测到旧格式时强制重新解压, 并用新格式覆盖
        if isinstance(lib_info, str):
            lib_info = {}
        if lib_info.get("key") != current_key:
            # 清理旧版本文件 (缓存清理机制)
            old_files = lib_info.get("files", [])
            if old_files:
                _remove_stale_files(old_files, _CACHE_DIR)

            # 解压新归档
            try:
                extracted_files = _extract_archive(lib_path, _CACHE_DIR)
                manifest[lib_name] = {
                    "key": current_key,
                    "files": extracted_files,
                }
                updated = True
            except Exception as e:
                print(f"[TKSEditors] 警告: 解压 {lib_name} 失败: {e}", file=sys.stderr)

    # ── 清理空目录 (升级后可能产生空目录) ──
    if updated:
        _cleanup_empty_dirs(_CACHE_DIR)

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
