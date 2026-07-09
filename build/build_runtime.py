"""
build_runtime.py — 构建共享运行时归档 (.lib)
==============================================
从已安装的 PySide6/PIL/shiboken6 包中提取必要文件，
分别打包为 ZIP 归档（.lib 扩展名）。

用法:
    python build/build_runtime.py              # 构建全部归档
    python build/build_runtime.py --only QtCore  # 仅构建指定归档

输出目录: dist/TKSEditors/
"""
import argparse
import importlib
import os
import sys
import time
import zipfile
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent
仓库根目录 = BUILD_DIR.parent
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"


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

def build_archive(name: str, spec: dict, output_dir: Path) -> Path:
    """构建单个归档"""
    output_path = output_dir / name
    pyside6_dir = _get_package_dir("PySide6")

    print(f"\n  构建: {name}")
    print(f"  描述: {spec.get('description', '')}")

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

        # 1. 包含 shiboken6 整个包
        if spec.get("shiboken6"):
            shiboken6_dir = _get_package_dir("shiboken6")
            for item in shiboken6_dir.rglob("*"):
                if item.is_file() and "__pycache__" not in str(item):
                    arcname = "shiboken6/" + str(item.relative_to(shiboken6_dir))
                    zf.write(item, arcname)
                    file_count += 1
                    total_size += item.stat().st_size

        # 2. 包含 PySide6 的 Python 文件 (__init__.py 等)
        if spec.get("pyside6_py"):
            for item in pyside6_dir.iterdir():
                if item.is_file() and item.suffix == '.py':
                    arcname = "PySide6/" + item.name
                    zf.write(item, arcname)
                    file_count += 1
                    total_size += item.stat().st_size

        # 3. 包含指定的 PySide6 文件 (dll/pyd)
        for filename in spec.get("pyside6_files", []):
            filepath = pyside6_dir / filename
            if filepath.exists():
                arcname = "PySide6/" + filename
                zf.write(filepath, arcname)
                file_count += 1
                total_size += filepath.stat().st_size
            else:
                print(f"    [WARN] 文件不存在: {filepath}")

        # 4. 包含 PySide6 插件子目录
        for plugin_dir_name in spec.get("pyside6_plugins", []):
            plugin_dir = pyside6_dir / "plugins" / plugin_dir_name
            if plugin_dir.exists():
                for item in plugin_dir.rglob("*"):
                    if item.is_file():
                        arcname = "PySide6/plugins/" + plugin_dir_name + "/" + str(item.relative_to(plugin_dir))
                        zf.write(item, arcname)
                        file_count += 1
                        total_size += item.stat().st_size
            else:
                print(f"    [WARN] 插件目录不存在: {plugin_dir}")

        # 5. 包含整个 PIL 包
        if spec.get("pil"):
            pil_dir = _get_package_dir("PIL")
            for item in pil_dir.rglob("*"):
                if item.is_file() and "__pycache__" not in str(item):
                    arcname = "PIL/" + str(item.relative_to(pil_dir))
                    zf.write(item, arcname)
                    file_count += 1
                    total_size += item.stat().st_size

        # 6. 包含 Python ABI3 DLL (python3.dll, abi3 扩展模块依赖此 DLL)
        if spec.get("python_dlls"):
            python_dir = Path(sys.executable).parent
            for dll_name in ["python3.dll"]:
                dll_path = python_dir / dll_name
                if dll_path.exists():
                    zf.write(dll_path, dll_name)
                    file_count += 1
                    total_size += dll_path.stat().st_size
                    print(f"    [OK] 包含 {dll_name} ({dll_path})")
                else:
                    print(f"    [WARN] {dll_name} 不存在: {dll_path}")

    compressed_size = output_path.stat().st_size
    ratio = compressed_size / total_size * 100 if total_size > 0 else 0
    print(f"    文件数: {file_count}")
    print(f"    原始大小: {total_size / 1024 / 1024:.1f} MB")
    print(f"    压缩大小: {compressed_size / 1024 / 1024:.1f} MB ({ratio:.0f}%)")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="构建共享运行时归档")
    parser.add_argument("--only", type=str, help="仅构建指定归档 (不含扩展名)")
    parser.add_argument("--output", type=str, help="输出目录 (默认: dist/TKSEditors/)")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else RELEASE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  TKS Editors — 运行时归档构建")
    print("=" * 60)
    print(f"  PySide6: {_get_package_dir('PySide6')}")
    print(f"  shiboken6: {_get_package_dir('shiboken6')}")
    print(f"  PIL: {_get_package_dir('PIL')}")
    print(f"  输出目录: {output_dir}")

    t0 = time.time()

    if args.only:
        key = args.only if args.only.endswith(".lib") else args.only + ".lib"
        if key not in ARCHIVES:
            print(f"\n  [ERROR] 未知归档: {key}")
            print(f"  可用: {', '.join(ARCHIVES.keys())}")
            sys.exit(1)
        build_archive(key, ARCHIVES[key], output_dir)
    else:
        for name, spec in ARCHIVES.items():
            build_archive(name, spec, output_dir)

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
