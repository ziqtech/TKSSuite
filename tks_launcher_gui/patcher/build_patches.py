"""补丁构建工具 — 将源码目录打包为 .tkspatch 文件"""
import json
import zipfile
import shutil
from pathlib import Path

if __package__ and "." in __package__:
    from ..core import tkspatch_loader
else:
    # 兼容构建系统的 patcher 导入方式以及原有的直接脚本入口。
    if not __package__:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core import tkspatch_loader


def _report(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"))


def build_single_patch(src_dir: Path, output_file: Path) -> bool:
    """将单个补丁源码目录打包为 .tkspatch 文件。
    
    Args:
        src_dir: 补丁源码目录（如 patches/gold_limit/）
        output_file: 输出的 .tkspatch 文件路径
    
    Returns:
        成功返回 True
    """
    # 检查 patch.json 是否存在
    patch_json_path = src_dir / "patch.json"
    if not patch_json_path.exists():
        _report(f"  [WARN] 跳过: {src_dir.name}（缺少 patch.json）")
        return False
    
    # 与源码加载共用资源规则，写 ZIP 前完成全部读取及校验。
    try:
        source_root = src_dir.resolve()
        output_path = output_file.resolve()
        if output_path == source_root or source_root in output_path.parents:
            raise ValueError("输出文件必须位于补丁源码目录之外")
        package_files = tkspatch_loader.collect_package_files(src_dir)
        patch_data = json.loads(package_files["patch.json"].decode('utf-8'))
        errors = tkspatch_loader.validate_tkspatch_dict(
            patch_data, source_path=str(patch_json_path), log_func=_report)
        if errors:
            _report(f"  [ERROR] {src_dir.name}: patch.json 校验失败")
            return False
        tkspatch_loader.validate_bundle_resources(patch_data, package_files)

    except json.JSONDecodeError as e:
        _report(f"  [ERROR] {src_dir.name}: patch.json 格式错误 - {e}")
        return False
    except Exception as e:
        _report(f"  [ERROR] {src_dir.name}: 读取失败 - {e}")
        return False

    # 保留所有资源（包括 patch.json）的原始字节，确保目录与 ZIP 一致。
    try:
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in sorted(package_files.items()):
                zf.writestr(name, content)

        _report(f"  [OK] {src_dir.name} -> {output_file.name}")
        return True
    
    except Exception as e:
        _report(f"  [ERROR] {src_dir.name}: 打包失败 - {e}")
        return False

def build_all_patches(src_patches_dir: str, dst_patches_dir: str) -> bool:
    """构建所有补丁。
    
    Args:
        src_patches_dir: 源码补丁目录（如 patches/）
        dst_patches_dir: 输出目录（如 dist/patches/）
    
    Returns:
        全部成功返回 True
    """
    src_path = Path(src_patches_dir)
    dst_path = Path(dst_patches_dir)
    
    if not src_path.exists():
        _report(f"[ERROR] 源码目录不存在: {src_patches_dir}")
        return False
    
    # 创建输出目录
    dst_path.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    fail_count = 0
    
    # 所有补丁均按统一 ZIP 格式构建。
    # 遍历所有补丁目录
    patch_dirs = [d for d in src_path.iterdir()
                  if d.is_dir() and not d.name.startswith(("_", "."))
                  and (d / "patch.json").is_file()]
    
    if not patch_dirs:
        _report("[WARN] 没有找到补丁目录")
        return False
    
    _report(f"\n开始构建 {len(patch_dirs)} 个补丁...\n")
    
    for patch_dir in sorted(patch_dirs):
        output_file = dst_path / f"{patch_dir.name}.tkspatch"
        if build_single_patch(patch_dir, output_file):
            success_count += 1
        else:
            fail_count += 1
    
    # 总结
    _report(f"\n{'='*70}")
    _report("补丁构建完成:")
    _report(f"  [OK] 成功: {success_count} 个")
    _report(f"  [ERROR] 失败: {fail_count} 个")
    _report(f"  输出目录: {dst_patches_dir}")
    _report(f"{'='*70}\n")
    
    return fail_count == 0

if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="构建补丁为 .tkspatch 文件")
    parser.add_argument("--src", default="../patches", 
                       help="源码目录（默认: ../patches）")
    parser.add_argument("--dst", required=True,
                       help="输出目录")
    args = parser.parse_args()
    
    success = build_all_patches(args.src, args.dst)
    sys.exit(0 if success else 1)
