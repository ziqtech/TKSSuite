"""
build_runtime.py — 构建共享运行时归档 (.lib)
==============================================
从已安装的 PySide6/PIL/shiboken6 包中提取必要文件，
分别打包为 zstd 压缩的 tar 归档（.lib 扩展名）。

zstd 比 ZIP DEFLATE 解压速度快 2-5 倍, 显著加快首次启动。
runtime_bootstrap.py 自动检测 .lib 格式 (zst/zip), 向后兼容。

用法:
    python build/build_runtime.py              # 构建全部归档
    python build/build_runtime.py --only QtCore  # 仅构建指定归档

输出目录: dist/TKSEditors/libs/
"""
import argparse
import importlib
import io
import os
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import zstandard
except ImportError:
    print("[ERROR] 需要 zstandard: pip install zstandard")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent
仓库根目录 = BUILD_DIR.parent
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"
# .lib 归档统一输出到 libs/ 子目录, 与 exe 分离
LIBS_DIR = RELEASE_DIR / "libs"

# zstd 压缩级别 (3 = 平衡压缩率与速度; 解压速度与级别无关)
_ZSTD_LEVEL = 3


def _get_package_dir(package_name: str) -> Path:
    """获取已安装包的目录"""
    mod = importlib.import_module(package_name)
    return Path(mod.__file__).parent


# ═══════════════════════════════════════════════════════════════
# 归档定义
# ═══════════════════════════════════════════════════════════════

# 每个归档的内容定义
# "pyside6_files": 从 PySide6 目录中选择的文件 (glob 模式)
# "pyside6_plugins": 从 PySide6/plugins/ 中选择的子目录
# "shiboken6": 是否包含整个 shiboken6 包
# "pyside6_py": 是否包含 PySide6 的 .py 文件 (初始化等)
# "pil": 是否包含整个 PIL 包

ARCHIVES = {
    "PySide6.lib": {
        "description": "PySide6/shiboken6 核心 + VC 运行时 + Python ABI3 DLL",
        "shiboken6": True,
        "pyside6_py": True,  # __init__.py 等
        "python_dlls": True,  # python3.dll (abi3 扩展需要)
        "pyside6_files": [
            "pyside6.abi3.dll",
            # VC 运行时 (从 PySide6 目录)
            "concrt140.dll",
            "msvcp140.dll",
            "msvcp140_1.dll",
            "msvcp140_2.dll",
            "msvcp140_codecvt_ids.dll",
            "vcamp140.dll",
            "vccorlib140.dll",
            "vcomp140.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
        ],
    },
    "QtCore.lib": {
        "description": "Qt6Core + QtCore 绑定",
        "pyside6_files": ["Qt6Core.dll", "QtCore.pyd"],
    },
    "QtGui.lib": {
        "description": "Qt6Gui + QtGui 绑定 + OpenGL",
        "pyside6_files": [
            "Qt6Gui.dll",
            "Qt6OpenGL.dll",
            "QtGui.pyd",
            "QtNetwork.pyd",
            "Qt6Network.dll",
            "opengl32sw.dll",
        ],
    },
    "QtWidgets.lib": {
        "description": "Qt6Widgets + QtWidgets 绑定 + Qt 插件",
        "pyside6_files": [
            "Qt6Widgets.dll",
            "QtWidgets.pyd",
            "Qt6Pdf.dll",
        ],
        "pyside6_plugins": [
            "platforms",
            "styles",
            "imageformats",
            "iconengines",
        ],
    },
    "QtSvg.lib": {
        "description": "Qt6Svg + Qt6SvgWidgets 绑定",
        "pyside6_files": [
            "Qt6Svg.dll",
            "Qt6SvgWidgets.dll",
            "QtSvg.pyd",
            "QtSvgWidgets.pyd",
        ],
    },
    "PIL.lib": {
        "description": "Pillow 图像处理库",
        "pil": True,
    },
}


# ═══════════════════════════════════════════════════════════════
# 构建逻辑
# ═══════════════════════════════════════════════════════════════

def _collect_archive_entries(spec: dict) -> list:
    """收集归档中所有 (source_path, arcname) 条目

    延迟导入 PySide6/PIL — 只有需要时才导入。
    PIL.lib 构建时不依赖 PySide6 已安装。
    """
    entries = []  # [(Path, arcname), ...]

    # 1. 包含 shiboken6 整个包
    if spec.get("shiboken6"):
        shiboken6_dir = _get_package_dir("shiboken6")
        for item in shiboken6_dir.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                arcname = "shiboken6/" + str(item.relative_to(shiboken6_dir)).replace("\\", "/")
                entries.append((item, arcname))

    # 2. 包含 PySide6 的 Python 文件 (__init__.py 等)
    if spec.get("pyside6_py") or spec.get("pyside6_files") or spec.get("pyside6_plugins"):
        pyside6_dir = _get_package_dir("PySide6")

        if spec.get("pyside6_py"):
            for item in pyside6_dir.iterdir():
                if item.is_file() and item.suffix == '.py':
                    arcname = "PySide6/" + item.name
                    entries.append((item, arcname))

        # 3. 包含指定的 PySide6 文件 (dll/pyd)
        for filename in spec.get("pyside6_files", []):
            filepath = pyside6_dir / filename
            if filepath.exists():
                arcname = "PySide6/" + filename
                entries.append((filepath, arcname))
            else:
                print(f"    [WARN] 文件不存在: {filepath}")

        # 4. 包含 PySide6 插件子目录
        for plugin_dir_name in spec.get("pyside6_plugins", []):
            plugin_dir = pyside6_dir / "plugins" / plugin_dir_name
            if plugin_dir.exists():
                for item in plugin_dir.rglob("*"):
                    if item.is_file():
                        rel = str(item.relative_to(plugin_dir)).replace("\\", "/")
                        arcname = f"PySide6/plugins/{plugin_dir_name}/{rel}"
                        entries.append((item, arcname))
            else:
                print(f"    [WARN] 插件目录不存在: {plugin_dir}")

    # 5. 包含整个 PIL 包
    if spec.get("pil"):
        pil_dir = _get_package_dir("PIL")
        for item in pil_dir.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                arcname = "PIL/" + str(item.relative_to(pil_dir)).replace("\\", "/")
                entries.append((item, arcname))

    # 6. 包含 Python ABI3 DLL (python3.dll, abi3 扩展模块依赖此 DLL)
    if spec.get("python_dlls"):
        python_dir = Path(sys.executable).parent
        for dll_name in ["python3.dll"]:
            dll_path = python_dir / dll_name
            if dll_path.exists():
                entries.append((dll_path, dll_name))
                print(f"    [OK] 包含 {dll_name} ({dll_path})")
            else:
                print(f"    [WARN] {dll_name} 不存在: {dll_path}")

    return entries


def build_archive(name: str, spec: dict, output_dir: Path, force: bool = False) -> Path:
    """构建单个归档 (zstd 压缩的 tar)"""
    output_path = output_dir / name

    print(f"\n  构建: {name}")
    print(f"  描述: {spec.get('description', '')}")

    entries = _collect_archive_entries(spec)
    file_count = len(entries)
    total_size = sum(src.stat().st_size for src, _ in entries)

    # 增量: 归档已存在且比所有源文件 + 构建脚本新 -> 跳过重压
    if not force and output_path.exists():
        lib_mtime = output_path.stat().st_mtime
        script_mtime = (BUILD_DIR / "build_runtime.py").stat().st_mtime
        newest_src = max([script_mtime] + [src.stat().st_mtime for src, _ in entries])
        if lib_mtime >= newest_src:
            size_mb = output_path.stat().st_size / 1024 / 1024
            print(f"    [SKIP] {name} ({size_mb:.1f} MB, 源未变更)")
            return output_path

    # 用 zstd 压缩 tar 归档
    cctx = zstandard.ZstdCompressor(level=_ZSTD_LEVEL)

    with open(output_path, 'wb') as raw:
        with cctx.stream_writer(raw) as compressor:
            # 使用流式 tar 写入, 避免内存中构建完整 tar
            with tarfile.open(fileobj=compressor, mode='w|') as tar:
                for src, arcname in entries:
                    tar.add(str(src), arcname=arcname, recursive=False)

    compressed_size = output_path.stat().st_size
    ratio = compressed_size / total_size * 100 if total_size > 0 else 0
    print(f"    文件数: {file_count}")
    print(f"    原始大小: {total_size / 1024 / 1024:.1f} MB")
    print(f"    压缩大小: {compressed_size / 1024 / 1024:.1f} MB ({ratio:.0f}%)")

    return output_path


def build_archive_parallel(output_dir: Path, force: bool = False) -> list:
    """并行构建所有归档 (I/O+压缩密集, GIL 影响小)"""
    results = []
    with ThreadPoolExecutor(max_workers=min(len(ARCHIVES), 4)) as executor:
        futures = {
            executor.submit(build_archive, name, spec, output_dir, force): name
            for name, spec in ARCHIVES.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                path = future.result()
                results.append((name, path))
            except Exception as e:
                print(f"  [ERROR] {name} 构建失败: {e}")
                results.append((name, None))
    return results


def main():
    parser = argparse.ArgumentParser(description="构建共享运行时归档")
    parser.add_argument("--only", type=str, help="仅构建指定归档 (不含扩展名)")
    parser.add_argument("--output", type=str, help="输出目录 (默认: dist/TKSEditors/libs/)")
    parser.add_argument("--no-parallel", action="store_true",
                        help="禁用并行构建 (串行模式, 调试用)")
    parser.add_argument("--force", action="store_true",
                        help="强制重建全部归档, 跳过增量检查")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else LIBS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  TKS Editors — 运行时归档构建 (zstd)")
    print("=" * 60)

    # 延迟打印包路径 (只有需要时才导入)
    if not args.only or args.only.rstrip(".lib") in ("PySide6", "QtCore", "QtGui", "QtWidgets", "QtSvg"):
        print(f"  PySide6: {_get_package_dir('PySide6')}")
        print(f"  shiboken6: {_get_package_dir('shiboken6')}")
    if not args.only or args.only.rstrip(".lib") == "PIL":
        print(f"  PIL: {_get_package_dir('PIL')}")
    print(f"  输出目录: {output_dir}")
    print(f"  压缩格式: zstd (level={_ZSTD_LEVEL})")

    t0 = time.time()

    if args.only:
        key = args.only if args.only.endswith(".lib") else args.only + ".lib"
        if key not in ARCHIVES:
            print(f"\n  [ERROR] 未知归档: {key}")
            print(f"  可用: {', '.join(ARCHIVES.keys())}")
            sys.exit(1)
        build_archive(key, ARCHIVES[key], output_dir, args.force)
    elif args.no_parallel:
        for name, spec in ARCHIVES.items():
            build_archive(name, spec, output_dir, args.force)
    else:
        print(f"\n  并行构建 {len(ARCHIVES)} 个归档...")
        build_archive_parallel(output_dir, args.force)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"  完成! 耗时: {elapsed:.1f}s")
    print(f"  输出: {output_dir}")

    # 汇总
    total = sum(
        (output_dir / name).stat().st_size
        for name in ARCHIVES
        if (output_dir / name).exists()
    )
    print(f"  归档总大小: {total / 1024 / 1024:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
