"""补丁构建工具 — 将源码目录打包为 .tkspatch 文件"""
import json
import zipfile
import shutil
from pathlib import Path


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
    
    # 读取并验证 patch.json
    try:
        with open(patch_json_path, 'r', encoding='utf-8') as f:
            patch_data = json.load(f)
        
        # 基本校验
        if "type" not in patch_data or "id" not in patch_data:
            _report(f"  [ERROR] {src_dir.name}: patch.json 缺少必填字段（type/id）")
            return False
        
    except json.JSONDecodeError as e:
        _report(f"  [ERROR] {src_dir.name}: patch.json 格式错误 - {e}")
        return False
    except Exception as e:
        _report(f"  [ERROR] {src_dir.name}: 读取失败 - {e}")
        return False
    
    # 打包为 ZIP
    try:
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 写入 patch.json
            zf.writestr("patch.json", json.dumps(patch_data, ensure_ascii=False, indent=2))
            
            # 写入其他文件（script.py, summon_table.json 等）
            for item in src_dir.iterdir():
                if item.name == "patch.json":
                    continue
                if item.is_file():
                    zf.write(item, item.name)
        
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
    
    # 所有补丁（包括 global_variables）均按统一 ZIP 格式构建。
    # 遍历所有补丁目录
    patch_dirs = [d for d in src_path.iterdir() 
                  if d.is_dir() and not d.name.startswith("_")]
    
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
