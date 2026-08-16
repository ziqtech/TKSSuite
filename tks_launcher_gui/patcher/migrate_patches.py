"""将现有的 .tkspatch 文件转换为源码目录格式"""
import json
import zipfile
import shutil
from pathlib import Path


def _report(message: str) -> None:
    """在 Windows 非 UTF-8 控制台中也能稳定输出迁移进度。"""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"))


def migrate_single_patch(tkspatch_file: Path, output_dir: Path) -> bool:
    """将单个 .tkspatch 文件转换为源码目录。"""
    try:
        # 旧版全局变量是根级 JSON，转换为统一的 global_variables 清单。
        if tkspatch_file.name == "_variables.tkspatch" and not zipfile.is_zipfile(tkspatch_file):
            raw = json.loads(tkspatch_file.read_text(encoding="utf-8"))
            raw["type"] = "global_variables"
            raw["id"] = "global_variables"
            raw.setdefault("name", "全局变量")
            raw.setdefault("desc", "所有补丁共用的变量定义")
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "patch.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _report(f"  [OK] {tkspatch_file.name} -> {output_dir.name}/patch.json (global_variables)")
            return True

        # 检查是否为 ZIP 格式
        if zipfile.is_zipfile(tkspatch_file):
            # ZIP 格式：解压到目录
            with zipfile.ZipFile(tkspatch_file, 'r') as zf:
                zf.extractall(output_dir)
            _report(f"  [OK] {tkspatch_file.name} -> {output_dir.name}/ (ZIP)")
        else:
            # JSON 格式：复制为 patch.json
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tkspatch_file, output_dir / "patch.json")
            _report(f"  [OK] {tkspatch_file.name} -> {output_dir.name}/patch.json (JSON)")
        
        return True
    
    except Exception as e:
        _report(f"  [ERROR] {tkspatch_file.name}: migration failed - {e}")
        return False

def migrate_all_patches(src_dir: str, dst_dir: str) -> bool:
    """迁移所有现有的 .tkspatch 文件。"""
    src_path = Path(src_dir)
    dst_path = Path(dst_dir)
    
    if not src_path.exists():
        _report(f"[ERROR] 源目录不存在: {src_dir}")
        return False
    
    dst_path.mkdir(parents=True, exist_ok=True)
    
    # 旧版变量文件迁移为普通补丁目录；新格式不以下划线开头。
    vars_file = src_path / "_variables.tkspatch"
    if vars_file.exists():
        migrate_single_patch(vars_file, dst_path / "global_variables")

    # 处理所有普通 .tkspatch 文件
    tkspatch_files = [
        f for f in src_path.glob("*.tkspatch")
        if f.name != "_variables.tkspatch"
    ]
    
    if not tkspatch_files:
        _report("[WARN] 没有找到 .tkspatch 文件")
        return False
    
    print(f"\n开始迁移 {len(tkspatch_files)} 个补丁...\n")
    
    success_count = 0
    for tkspatch_file in sorted(tkspatch_files):
        # 输出目录名：去掉 .tkspatch 扩展名
        dir_name = tkspatch_file.stem
        output_dir = dst_path / dir_name
        
        if migrate_single_patch(tkspatch_file, output_dir):
            success_count += 1
    
    print(f"\n{'='*70}")
    print(f"迁移完成: {success_count}/{len(tkspatch_files)} 个")
    print(f"输出目录: {dst_dir}")
    print(f"{'='*70}\n")
    
    return success_count == len(tkspatch_files)

if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="迁移现有 .tkspatch 为源码格式")
    parser.add_argument("--src", required=True,
                       help="原 .tkspatch 文件目录")
    parser.add_argument("--dst", default="../patches",
                       help="输出源码目录（默认: ../patches）")
    args = parser.parse_args()
    
    success = migrate_all_patches(args.src, args.dst)
    sys.exit(0 if success else 1)
