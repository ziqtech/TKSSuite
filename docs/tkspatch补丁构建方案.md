# TKS 启动器补丁构建方案（精简版）

**日期**: 2026-08-17  
**核心理念**: 开发环境为源码目录，构建时打包为 .tkspatch 文件

---

## 一、目录结构

### 开发环境（源码）
```
tks_launcher_gui/
├── patches/                          # 补丁源码目录
│   ├── _variables.json              # 全局变量源码
│   ├── broke_weapon_fix/            # 补丁源码目录
│   │   └── patch.json
│   ├── gold_limit/
│   │   └── patch.json
│   ├── summon_extend_v15/
│   │   ├── patch.json
│   │   └── summon_table.json
│   └── custom_logic/
│       ├── patch.json
│       └── script.py
│
└── patcher/                          # 补丁构建工具目录
    ├── __init__.py
    ├── build_patches.py             # 核心构建工具
    └── migrate_patches.py           # 迁移工具（可选）
```

### 生产环境（打包产物）
```
dist/TKSLauncher/                     # 或 TKSLauncherCLI/
├── tks_launcher.exe                 # 或 cli_launcher.exe
├── patches/                          # 打包后的补丁目录
│   ├── _variables.tkspatch
│   ├── broke_weapon_fix.tkspatch
│   ├── gold_limit.tkspatch
│   └── ...
└── ... (其他 Python 模块)
```

---

## 二、核心构建工具

### 2.1 `patcher/build_patches.py`

```python
"""补丁构建工具 — 将源码目录打包为 .tkspatch 文件"""
import json
import zipfile
import shutil
from pathlib import Path

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
        print(f"  ⚠️  跳过: {src_dir.name}（缺少 patch.json）")
        return False
    
    # 读取并验证 patch.json
    try:
        with open(patch_json_path, 'r', encoding='utf-8') as f:
            patch_data = json.load(f)
        
        # 基本校验
        if "type" not in patch_data or "id" not in patch_data:
            print(f"  ❌ {src_dir.name}: patch.json 缺少必填字段（type/id）")
            return False
        
    except json.JSONDecodeError as e:
        print(f"  ❌ {src_dir.name}: patch.json 格式错误 - {e}")
        return False
    except Exception as e:
        print(f"  ❌ {src_dir.name}: 读取失败 - {e}")
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
        
        print(f"  ✅ {src_dir.name} → {output_file.name}")
        return True
    
    except Exception as e:
        print(f"  ❌ {src_dir.name}: 打包失败 - {e}")
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
        print(f"❌ 源码目录不存在: {src_patches_dir}")
        return False
    
    # 创建输出目录
    dst_path.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    fail_count = 0
    
    # 处理 _variables.json
    vars_src = src_path / "_variables.json"
    vars_dst = dst_path / "_variables.tkspatch"
    if vars_src.exists():
        # _variables 直接复制（保持 JSON 格式）
        shutil.copy2(vars_src, vars_dst)
        print(f"  ✅ _variables.json → _variables.tkspatch")
    else:
        print(f"  ⚠️  未找到 _variables.json")
    
    # 遍历所有补丁目录
    patch_dirs = [d for d in src_path.iterdir() 
                  if d.is_dir() and not d.name.startswith("_")]
    
    if not patch_dirs:
        print(f"⚠️  没有找到补丁目录")
        return False
    
    print(f"\n开始构建 {len(patch_dirs)} 个补丁...\n")
    
    for patch_dir in sorted(patch_dirs):
        output_file = dst_path / f"{patch_dir.name}.tkspatch"
        if build_single_patch(patch_dir, output_file):
            success_count += 1
        else:
            fail_count += 1
    
    # 总结
    print(f"\n{'='*70}")
    print(f"补丁构建完成:")
    print(f"  ✅ 成功: {success_count} 个")
    print(f"  ❌ 失败: {fail_count} 个")
    print(f"  输出目录: {dst_patches_dir}")
    print(f"{'='*70}\n")
    
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
```

### 2.2 `patcher/__init__.py`

```python
"""补丁构建工具包"""
from .build_patches import build_all_patches

__all__ = ['build_all_patches']
```

---

## 三、集成到 build_all.py

### 3.1 修改 build_all.py

```python
# build/build_all.py

def build_tks_launcher_gui(is_cli=False):
    """构建 TKS 启动器（GUI 或 CLI 版本）
    
    Args:
        is_cli: True 表示构建 CLI 版本，False 表示 GUI 版本
    """
    import sys
    import os
    import shutil
    
    version = "GUI" if not is_cli else "CLI"
    print("\n" + "="*70)
    print(f"构建 TKS 启动器 ({version} 版本)")
    print("="*70)
    
    # === 1. 编译 C# 组件 ===
    print(f"\n[1/3] 编译 C# 启动器 ({version})...")
    
    launcher_src = "../仓库根目录/tks_launcher_gui/tks_launcher.cs"
    if is_cli:
        launcher_src = "../仓库根目录/tks_launcher_gui/cli_launcher.cs"
    
    launcher_exe = "tks_launcher.exe"
    if is_cli:
        launcher_exe = "cli_launcher.exe"
    
    # 编译 C# 代码（现有逻辑）
    compile_cmd = f'csc /target:winexe /out:{launcher_exe} {launcher_src}'
    if is_cli:
        compile_cmd = f'csc /target:exe /out:{launcher_exe} {launcher_src}'
    
    # ... 执行编译命令 ...
    
    # === 2. 复制 Python 模块 ===
    print(f"\n[2/3] 复制 Python 模块...")
    
    dist_dir = f"dist/TKSLauncher" if not is_cli else f"dist/TKSLauncherCLI"
    os.makedirs(dist_dir, exist_ok=True)
    
    # 复制 Python 代码（core/, ui/ 等）
    # ... 现有的文件复制逻辑 ...
    
    # === 3. 构建并复制补丁 ===
    print(f"\n[3/3] 构建补丁文件...")
    
    try:
        # 添加启动器路径到 sys.path
        launcher_dir = os.path.abspath("../仓库根目录/tks_launcher_gui")
        if launcher_dir not in sys.path:
            sys.path.insert(0, launcher_dir)
        
        # 导入构建工具
        from patcher.build_patches import build_all_patches
        
        # 执行构建
        src_patches = os.path.join(launcher_dir, "patches")
        dst_patches = os.path.join(dist_dir, "patches")
        
        success = build_all_patches(src_patches, dst_patches)
        
        if success:
            print(f"  ✅ 补丁构建完成")
        else:
            print(f"  ⚠️  补丁构建失败（但不影响启动器运行）")
    
    except ImportError as e:
        print(f"  ⚠️  无法导入补丁构建工具: {e}")
        print(f"  提示: 请确保 {launcher_dir}/patcher/build_patches.py 存在")
    except Exception as e:
        print(f"  ⚠️  补丁构建出错: {e}")
    
    print(f"\n✅ TKS 启动器 ({version}) 构建完成")
    print(f"输出目录: {dist_dir}/")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="TKS 项目构建脚本")
    parser.add_argument("--only", help="只构建指定项目（如 TKSLauncher, TKSLauncherCLI）")
    args = parser.parse_args()
    
    if args.only:
        if args.only == "TKSLauncher":
            build_tks_launcher_gui(is_cli=False)
        elif args.only == "TKSLauncherCLI":
            build_tks_launcher_gui(is_cli=True)
        else:
            print(f"未知项目: {args.only}")
    else:
        # 默认构建所有项目
        build_tks_launcher_gui(is_cli=False)
        build_tks_launcher_gui(is_cli=True)
        # ... 其他项目 ...

if __name__ == "__main__":
    main()
```

---

## 四、补丁源码示例

### 4.1 简单补丁示例

**目录**: `patches/gold_limit/`

**patch.json**:
```json
{
  "type": "patch_imm32",
  "id": "gold_limit",
  "name": "金钱上限调整",
  "desc": "将金钱上限从 99,999,999 调整为 999,999,999",
  "optional": false,
  "default_checked": true,
  
  "pattern": "81 7D F8 ?? ?? ?? 05",
  "replace": {
    "3": "new_gold_limit"
  },
  "expect_count": 1,
  "new_value": "0x3B9AC9FF"
}
```

### 4.2 脚本补丁示例

**目录**: `patches/custom_logic/`

**patch.json**:
```json
{
  "type": "script",
  "id": "custom_logic",
  "name": "自定义逻辑",
  "desc": "通过外部脚本实现复杂补丁逻辑",
  "optional": true,
  "default_checked": false,
  
  "script_file": "script.py"
}
```

**script.py**:
```python
def apply(ctx):
    """补丁应用函数"""
    ctx.log(f"正在应用自定义逻辑补丁...")
    
    # 访问上下文
    h_proc = ctx.h_proc
    base_addr = ctx.base_addr
    
    # 执行补丁逻辑
    from core.memory import write_pm
    # ... 你的代码 ...
    
    return True
```

### 4.3 数据补丁示例

**目录**: `patches/summon_extend_v15/`

**patch.json**:
```json
{
  "type": "patch_summon_table",
  "id": "summon_extend_v15",
  "name": "召唤表扩展 v15",
  "desc": "扩展召唤单位数量到 40 个",
  "optional": false,
  "default_checked": true,
  
  "json_file": "summon_table.json",
  "data_rva": "0x9D705A",
  "data_keys": ["id", "level", "hp", "mp", "attack", "defense"]
}
```

**summon_table.json**:
```json
[
  {"id": 1, "level": 10, "hp": 500, "mp": 100, "attack": 50, "defense": 30},
  {"id": 2, "level": 15, "hp": 800, "mp": 150, "attack": 70, "defense": 40}
]
```

---

## 五、使用流程

### 5.1 开发流程

```bash
# 1. 编辑补丁源码
cd tks_launcher_gui/patches/gold_limit
vim patch.json

# 2. 提交代码
git add patch.json
git commit -m "fix(gold_limit): 修复金钱上限溢出"
```

### 5.2 构建流程

```bash
# 方式 1: 只构建 GUI 版本
cd build
python build_all.py --only TKSLauncher

# 方式 2: 只构建 CLI 版本
python build_all.py --only TKSLauncherCLI

# 方式 3: 构建所有项目（包括两个版本的启动器）
python build_all.py
```

### 5.3 验证产物

```bash
cd dist/TKSLauncher/patches
ls -la
# 应该看到:
# _variables.tkspatch
# broke_weapon_fix.tkspatch
# gold_limit.tkspatch
# summon_extend_v15.tkspatch
# ...
```

---

## 六、迁移现有补丁（可选）

### 6.1 `patcher/migrate_patches.py`

```python
"""将现有的 .tkspatch 文件转换为源码目录格式"""
import json
import zipfile
import shutil
from pathlib import Path

def migrate_single_patch(tkspatch_file: Path, output_dir: Path) -> bool:
    """将单个 .tkspatch 文件转换为源码目录。"""
    try:
        # 检查是否为 ZIP 格式
        if zipfile.is_zipfile(tkspatch_file):
            # ZIP 格式：解压到目录
            with zipfile.ZipFile(tkspatch_file, 'r') as zf:
                zf.extractall(output_dir)
            print(f"  ✅ {tkspatch_file.name} → {output_dir.name}/ (ZIP)")
        else:
            # JSON 格式：复制为 patch.json
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tkspatch_file, output_dir / "patch.json")
            print(f"  ✅ {tkspatch_file.name} → {output_dir.name}/patch.json (JSON)")
        
        return True
    
    except Exception as e:
        print(f"  ❌ {tkspatch_file.name}: 迁移失败 - {e}")
        return False

def migrate_all_patches(src_dir: str, dst_dir: str) -> bool:
    """迁移所有现有的 .tkspatch 文件。"""
    src_path = Path(src_dir)
    dst_path = Path(dst_dir)
    
    if not src_path.exists():
        print(f"❌ 源目录不存在: {src_dir}")
        return False
    
    dst_path.mkdir(parents=True, exist_ok=True)
    
    # 处理 _variables.tkspatch
    vars_file = src_path / "_variables.tkspatch"
    if vars_file.exists():
        shutil.copy2(vars_file, dst_path / "_variables.json")
        print(f"  ✅ _variables.tkspatch → _variables.json")
    
    # 处理所有 .tkspatch 文件
    tkspatch_files = list(src_path.glob("*.tkspatch"))
    tkspatch_files = [f for f in tkspatch_files if f.name != "_variables.tkspatch"]
    
    if not tkspatch_files:
        print(f"⚠️  没有找到 .tkspatch 文件")
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
```

### 6.2 迁移步骤

```bash
# 1. 备份现有的 patches/ 目录
cd tks_launcher_gui
mv patches patches_old

# 2. 运行迁移脚本
python patcher/migrate_patches.py --src patches_old --dst patches

# 3. 测试构建
cd ../build
python build_all.py --only TKSLauncher
```

---

## 七、总结

### 核心要点

1. **开发环境**: `patches/` 为源码目录，每个补丁是一个子目录
2. **构建工具**: `patcher/build_patches.py` 负责打包
3. **集成构建**: `build_all.py --only TKSLauncher` 自动调用补丁构建
4. **产物输出**: `dist/TKSLauncher/patches/` 包含打包后的 .tkspatch 文件

### 目录结构对比

```
开发环境                          生产环境
────────────────────────────────────────────────
patches/                          dist/TKSLauncher/patches/
  ├── gold_limit/            →      ├── gold_limit.tkspatch
  │   └── patch.json                └── ...
  └── ...
```

### 构建命令

```bash
# 只构建 GUI 版本
python build_all.py --only TKSLauncher

# 只构建 CLI 版本
python build_all.py --only TKSLauncherCLI

# 构建所有项目
python build_all.py
```
