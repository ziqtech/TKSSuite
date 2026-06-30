"""
build_all.py — TKS Editors 一键构建脚本
==========================================
使用 PyInstaller 将所有编辑器打包为独立 exe。

用法:
    python build_all.py              # 构建全部
    python build_all.py --only TKSItemEditor   # 仅构建指定编辑器
    python build_all.py --merge-only           # 仅合并已构建的 dist

前置条件:
    pip install pyinstaller PySide6 Pillow
"""
import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 编辑器配置表
# ═══════════════════════════════════════════════════════════════

# (打包名, 入口脚本相对于 仓库根目录 的路径, 是否需要 Pillow)
EDITORS = [
    ("TKSItemEditor",        "item_editor/item_editor_v2.py",               False),
    ("TKSWarpcEditor",       "warpc_editor/warpc_editor_v2.py",             False),
    ("TKSSkillEditor",       "skill_editor/skill_editor_v2.py",             False),
    ("TKSShopEditor",        "shop_editor/shop_editor_v2.py",               False),
    ("TKSMatEditor",         "mat_editor/mat_editor_v2.py",                 False),
    ("TKSJvgEditor",         "jvg_editor/jvg_editor_v2.py",                True),
    ("TKSGrpEditor",         "grp_editor/grp_editor_v2.py",                True),
    ("TKSTktEditor",         "tkt_editor/tkt_editor_v2.py",                 False),
    ("TKSKonEditor",         "kon_editor/kon_editor_v2.py",                 False),
    ("TKSActEditor",         "act_editor/act_editor_v2.py",                 False),
    ("TKSWardataEditor",     "wardata_editor/wardata_editor_v2.py",         False),
    ("TKSGxpEditor",         "gxp_editor/gxp_editor_v2.py",                True),
    ("TKSSpritesheetEditor", "spritesheet_editor/spritesheet_editor_v2.py", True),
    ("TKSSaveEditor",        "save_editor/save_editor_v2.py",               False),
    ("TKSLauncher",          "tks_launcher_gui/main.py",                    False),
]

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

BUILD_DIR = Path(__file__).parent                      # build/
仓库根目录 = BUILD_DIR.parent                         # 
SPECS_DIR = BUILD_DIR / "specs"
DIST_DIR = 仓库根目录 / "dist"
RELEASE_DIR = DIST_DIR / "TKSEditors"


def build_one(name: str, entry: str, needs_pillow: bool, verbose: bool = False):
    """构建单个编辑器"""
    spec_path = SPECS_DIR / f"{name}.spec"
    if not spec_path.exists():
        print(f"  [SKIP] {name}: spec 文件不存在 ({spec_path})")
        return False

    print(f"\n{'='*60}")
    print(f"  构建: {name}")
    print(f"  入口: {entry}")
    print(f"{'='*60}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        str(spec_path),
    ]

    result = subprocess.run(cmd, cwd=str(仓库根目录))
    if result.returncode != 0:
        print(f"  [FAIL] {name} 构建失败 (exit code: {result.returncode})")
        return False

    print(f"  [OK] {name} 构建成功")
    return True


def merge_release():
    """合并各编辑器的 dist 目录到统一发行目录 (共享 _internal/)"""
    print(f"\n{'='*60}")
    print(f"  合并发行目录: {RELEASE_DIR}")
    print(f"{'='*60}")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    internal_dir = RELEASE_DIR / "_internal"

    merged_count = 0
    for name, _, _ in EDITORS:
        editor_dist = DIST_DIR / name
        if not editor_dist.exists():
            print(f"  [SKIP] {name}: dist 不存在")
            continue

        # 复制 exe 到发行根目录
        exe_name = f"{name}.exe"
        exe_src = editor_dist / exe_name
        if exe_src.exists():
            shutil.copy2(str(exe_src), str(RELEASE_DIR / exe_name))
            print(f"  [OK] 复制 {exe_name}")
        else:
            # onedir 模式: exe 在子目录中
            for f in editor_dist.glob("*.exe"):
                shutil.copy2(str(f), str(RELEASE_DIR / f.name))
                print(f"  [OK] 复制 {f.name}")
                break

        # 合并 _internal/ 目录内容 (去重)
        src_internal = editor_dist / "_internal"
        if src_internal.exists():
            internal_dir.mkdir(exist_ok=True)
            for item in src_internal.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(src_internal)
                    dest = internal_dir / rel
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(dest))

        merged_count += 1

    # 创建 configs/ 和 mods/ 目录
    configs_dir = RELEASE_DIR / "configs"
    mods_dir = RELEASE_DIR / "mods"
    configs_dir.mkdir(exist_ok=True)
    mods_dir.mkdir(exist_ok=True)

    # 复制基线配置文件 (如果 configs/ 存在于源码中)
    src_configs = 仓库根目录 / "configs"
    if src_configs.exists():
        for f in src_configs.glob("*.json"):
            shutil.copy2(str(f), str(configs_dir / f.name))
            print(f"  [OK] 复制配置: {f.name}")

    print(f"\n  合并完成: {merged_count} 个编辑器")
    print(f"  发行目录: {RELEASE_DIR}")


def main():
    parser = argparse.ArgumentParser(description="TKS Editors 一键构建")
    parser.add_argument("--only", type=str, help="仅构建指定编辑器 (名称)")
    parser.add_argument("--merge-only", action="store_true", help="仅执行发行目录合并")
    parser.add_argument("--no-merge", action="store_true", help="构建后不合并")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.merge_only:
        merge_release()
        return

    # 构建
    success = []
    failed = []

    if args.only:
        # 仅构建指定编辑器
        targets = [(n, e, p) for n, e, p in EDITORS if n == args.only]
        if not targets:
            print(f"[ERROR] 未找到编辑器: {args.only}")
            print(f"  可用: {', '.join(n for n, _, _ in EDITORS)}")
            sys.exit(1)
    else:
        targets = EDITORS

    for name, entry, needs_pillow in targets:
        ok = build_one(name, entry, needs_pillow, args.verbose)
        (success if ok else failed).append(name)

    # 输出摘要
    print(f"\n{'='*60}")
    print(f"  构建摘要")
    print(f"{'='*60}")
    print(f"  成功: {len(success)}")
    if failed:
        print(f"  失败: {len(failed)} — {', '.join(failed)}")

    # 合并
    if not args.no_merge and success:
        merge_release()


if __name__ == "__main__":
    main()
