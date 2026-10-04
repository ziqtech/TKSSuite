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
  - Nuitka 编译环境: 从 libs/ 子目录的 .lib 归档解压到 %LOCALAPPDATA%/TKSEditors/runtime/
  - 增量更新: 分层校验 (size+mtime 快判 → MD5 内容指纹确认), 仅解压内容真正变化的归档
  - 格式自动检测: zstd (新) / zip (旧) 向后兼容
  - 缓存清理: 升级归档时自动删除旧版本文件, 避免残留
  - 重装兼容: 重装/复制导致 mtime 变化但内容不变时, 通过 MD5 确认复用缓存
  - 进度提示: 解压时显示 Win32 提示窗口 (纯 ctypes, 无外部依赖)
"""
import hashlib
import json
import os
import sys
import tarfile
import threading
import zipfile


# ═══════════════════════════════════════════════════════════════
# 进度提示窗口 (纯 Win32 API, 无外部依赖, 仅在解压缓存时显示)
# ═══════════════════════════════════════════════════════════════

_splash_hwnd = None       # 提示窗口句柄
_splash_static = None     # 静态文本控件句柄
_splash_thread = None     # 后台线程
_splash_ready = threading.Event()
_splash_close = threading.Event()


def _splash_worker(title: str, text: str):
    """后台线程: 创建并运行提示窗口的消息循环"""
    global _splash_hwnd, _splash_static
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hinstance = kernel32.GetModuleHandleW(None)

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, ctypes.c_uint,
                                  wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == 0x0002:  # WM_DESTROY
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(wnd_proc)
    class_name = "TKSEditorsBootstrap"

    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinstance
    wc.hCursor = user32.LoadCursorW(None, 32512)
    wc.hbrBackground = 15  # COLOR_BTNFACE + 1
    wc.lpszClassName = class_name
    user32.RegisterClassW(ctypes.byref(wc))

    # 窗口居中
    width, height = 380, 110
    x = (user32.GetSystemMetrics(0) - width) // 2
    y = (user32.GetSystemMetrics(1) - height) // 2

    hwnd = user32.CreateWindowExW(
        0x00000008,  # WS_EX_TOPMOST
        class_name, title,
        0x80000000 | 0x00C00000,  # WS_POPUP | WS_CAPTION
        x, y, width, height,
        None, None, hinstance, None
    )
    if not hwnd:
        _splash_ready.set()
        return

    _splash_hwnd = hwnd

    # 静态文本控件
    _splash_static = user32.CreateWindowExW(
        0, "STATIC", text,
        0x40000000 | 0x10000000 | 0x00000001 | 0x00000200,  # WS_CHILD|WS_VISIBLE|SS_CENTER|SS_CENTERIMAGE
        10, 10, width - 40, height - 40,
        hwnd, 1, hinstance, None
    )
    # 设置系统默认 GUI 字体
    if _splash_static:
        user32.SendMessageW(_splash_static, 0x0030, user32.GetStockObject(17), 1)

    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.UpdateWindow(hwnd)
    _splash_ready.set()

    # 消息循环 (PeekMessage 非阻塞, 定期检查关闭信号)
    msg = wintypes.MSG()
    import time as _time
    while not _splash_close.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, 1):
            if msg.message == 0x0012:  # WM_QUIT
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            _time.sleep(0.016)

    user32.DestroyWindow(hwnd)
    _splash_hwnd = None
    _splash_static = None


def _show_progress(text="正在初始化运行时缓存，请稍候..."):
    """显示进度提示窗口 (仅 Windows 编译环境)"""
    global _splash_thread
    if sys.platform != "win32":
        return
    _splash_close.clear()
    _splash_ready.clear()
    _splash_thread = threading.Thread(target=_splash_worker,
                                      args=("TKS Editors", text), daemon=True)
    _splash_thread.start()
    _splash_ready.wait(timeout=2.0)


def _update_progress(text: str):
    """更新提示窗口文本 (WM_SETTEXT)"""
    if _splash_static and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.SendMessageW(_splash_static, 0x000C, 0, text)


def _close_progress():
    """关闭提示窗口"""
    global _splash_thread
    if _splash_thread is None:
        return
    _splash_close.set()
    if _splash_hwnd and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.PostMessageW(_splash_hwnd, 0x0010, 0, 0)  # WM_CLOSE
    _splash_thread.join(timeout=3.0)
    _splash_thread = None


def _detect_app_dir():
    """检测 exe 所在的发行目录 (包含 libs/ 子目录, 其中存放 .lib 归档)。

    Nuitka onefile 模式下 sys.executable 指向临时解压目录，
    需要通过其他方式定位原始 exe 所在目录。
    """
    # 方法1: Nuitka 2.0+ 提供 __nuitka_binary_dir (原始二进制所在目录)
    nuitka_dir = globals().get("__nuitka_binary_dir")
    if nuitka_dir and os.path.isdir(nuitka_dir):
        if os.path.isfile(os.path.join(nuitka_dir, "libs", "PySide6.lib")):
            return nuitka_dir

    # 方法2: sys.argv[0] 通常保留原始 exe 路径
    if sys.argv and sys.argv[0]:
        argv0_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.path.isfile(os.path.join(argv0_dir, "libs", "PySide6.lib")):
            return argv0_dir

    # 方法3: sys.executable (standalone 模式下有效)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.isfile(os.path.join(exe_dir, "libs", "PySide6.lib")):
        return exe_dir

    # 方法4: 从 sys.executable 向上查找 (兼容子目录场景)
    current = exe_dir
    for _ in range(5):
        parent = os.path.dirname(current)
        if parent == current:
            break
        if os.path.isfile(os.path.join(parent, "libs", "PySide6.lib")):
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

# .lib 归档所在目录 (libs/ 子文件夹)
_LIBS_DIR = os.path.join(_APP_DIR, "libs")


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


def _is_system_temp_path(path: str) -> bool:
    """判断路径是否落在系统临时目录，避免依赖被随机临时目录承载。"""
    try:
        candidate = os.path.normcase(os.path.abspath(path))
        temp_root = os.path.normcase(os.path.abspath(
            os.environ.get("TEMP") or os.environ.get("TMP") or ""
        ))
        return bool(temp_root and (
            candidate == temp_root or candidate.startswith(temp_root + os.sep)
        ))
    except OSError:
        return False


if _is_system_temp_path(_CACHE_DIR):
    raise RuntimeError(
        "TKS Editors 运行时缓存路径落在系统临时目录，已拒绝启动: "
        f"{_CACHE_DIR}"
    )

# manifest 文件 (记录已解压归档的状态 + 文件列表, 用于增量清理)
_MANIFEST = os.path.join(_CACHE_DIR, ".manifest.json")

from .runtime_manifest import (
    REQUIRED_RUNTIME_ARCHIVES,
    REQUIRED_RUNTIME_MEMBERS,
    RUNTIME_ARCHIVES,
)

_RUNTIME_LIBS = list(RUNTIME_ARCHIVES)


# ═══════════════════════════════════════════════════════════════
# 内容指纹
# ═══════════════════════════════════════════════════════════════

def _file_md5(path: str, chunk_size: int = 1 << 20) -> str:
    """计算文件 MD5 (1MB 分块读取, 适用于大文件)"""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


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

    # 薄 exe 必须从 exe 同级 libs/ 读取归档。若归档缺失，不要静默跳过后
    # 再让 PySide6 导入报一个难以定位的错误。onefile 已内嵌 PySide6/PIL，
    # 由 Nuitka 引导设置的 NUITKA_ONEFILE_PARENT 识别，不做此检查。
    if not os.environ.get("NUITKA_ONEFILE_PARENT"):
        libs_dir = os.path.join(_APP_DIR, "libs")
        missing = [name for name in REQUIRED_RUNTIME_ARCHIVES
                   if not os.path.isfile(os.path.join(libs_dir, name))]
        if missing:
            raise RuntimeError(
                "TKS Editors 运行时归档不完整，缺少: " + ", ".join(missing) + "。\n"
                f"请将完整 libs 目录放在程序同级目录: {_APP_DIR}"
            )

    # ── 确保缓存目录存在 ──
    os.makedirs(_CACHE_DIR, exist_ok=True)

    # ── 加载 manifest ──
    # manifest 结构: { "lib_name": {"size": N, "mtime_ns": N, "hash": "...", "files": [...]} }
    manifest = {}
    if os.path.isfile(_MANIFEST):
        try:
            with open(_MANIFEST, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            manifest = {}

    # ── 缓存完整性哨兵检查 ──
    # 如果 manifest 存在但关键文件被意外删除 (杀毒软件/手动清理), 强制重建
    _SENTINEL = os.path.join(_CACHE_DIR, "PySide6", "__init__.py")
    if manifest and not os.path.isfile(_SENTINEL):
        manifest = {}  # 清空 manifest, 触发全量重新解压
    for lib_name, members in REQUIRED_RUNTIME_MEMBERS.items():
        lib_path = os.path.join(_LIBS_DIR, lib_name)
        if not os.path.isfile(lib_path):
            continue
        cached_files = set((manifest.get(lib_name) or {}).get("files", []))
        missing_cached = [name for name in members
                          if name not in cached_files
                          or not os.path.isfile(os.path.join(_CACHE_DIR, name.replace("/", os.sep)))]
        if missing_cached:
            manifest.pop(lib_name, None)

    # ── 检查并解压有变化的归档 ──
    # 缓存校验策略 (分层):
    #   1. size + mtime 均未变 → 快速命中, 跳过 (零开销)
    #   2. size 未变但 mtime 变了 → 计算 MD5 确认内容是否真的变了
    #      (覆盖重装/复制导致 mtime 变化但内容不变的场景)
    #   3. size 变了 → 内容肯定变了, 直接重新解压
    # manifest 结构: {"lib_name": {"size": N, "mtime_ns": N, "hash": "...", "files": [...]}}
    updated = False
    manifest_dirty = False
    splash_shown = False
    total_libs = len(_RUNTIME_LIBS)

    for idx, lib_name in enumerate(_RUNTIME_LIBS, 1):
        lib_path = os.path.join(_LIBS_DIR, lib_name)
        if not os.path.isfile(lib_path):
            continue

        stat = os.stat(lib_path)
        lib_info = manifest.get(lib_name, {})

        # 向后兼容: 旧版 manifest 值是字符串或缺少新字段, 视为需要校验
        if isinstance(lib_info, str):
            lib_info = {}

        cached_size = lib_info.get("size")
        cached_mtime = lib_info.get("mtime_ns")
        cached_hash = lib_info.get("hash")

        # ── 快速路径: size + mtime 均未变 → 缓存有效 ──
        if cached_size == stat.st_size and cached_mtime == stat.st_mtime_ns:
            continue

        # ── size 未变但 mtime 变了: 计算 MD5 确认内容是否真的变化 ──
        need_extract = True
        if cached_size == stat.st_size and cached_hash:
            file_hash = _file_md5(lib_path)
            if file_hash == cached_hash:
                # 内容相同, 仅 mtime 变了 (重装/复制) → 更新 manifest 的 mtime, 不重新解压
                lib_info["mtime_ns"] = stat.st_mtime_ns
                manifest[lib_name] = lib_info
                manifest_dirty = True
                need_extract = False

        if not need_extract:
            continue

        # ── 内容确实变了: 清理旧文件 + 重新解压 ──
        # 首次需要解压时显示进度提示
        if not splash_shown:
            _show_progress(f"正在构建运行时缓存 ({idx}/{total_libs}) {lib_name} ...")
            splash_shown = True
        else:
            _update_progress(f"正在构建运行时缓存 ({idx}/{total_libs}) {lib_name} ...")

        old_files = lib_info.get("files", [])
        if old_files:
            _remove_stale_files(old_files, _CACHE_DIR)

        try:
            extracted_files = _extract_archive(lib_path, _CACHE_DIR)
            manifest[lib_name] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "hash": _file_md5(lib_path),
                "files": extracted_files,
            }
            updated = True
        except Exception as e:
            print(f"[TKSEditors] 警告: 解压 {lib_name} 失败: {e}", file=sys.stderr)

    # ── 关闭进度提示 ──
    if splash_shown:
        _close_progress()

    # ── 清理空目录 (升级后可能产生空目录) ──
    if updated:
        _cleanup_empty_dirs(_CACHE_DIR)

    # ── 保存 manifest ──
    if updated or manifest_dirty:
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
