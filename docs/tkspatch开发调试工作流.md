# TKS 启动器补丁开发调试工作流改进方案

**日期**: 2026-08-17  
**目标**: 从高级 Python 开发工程师和游戏启动器开发工程师的角度，设计便于开发调试的工作流

---

## 一、当前痛点分析

### 1.1 开发者视角的核心问题

从高级 Python 开发工程师的角度看：

❌ **缺少开发环境隔离**：
- 修改补丁需要直接操作 `patches/` 目录
- 测试失败的补丁会污染生产环境
- 无法同时维护多个版本的补丁（稳定版 vs 实验版）

❌ **调试反馈链路长**：
```
修改 .tkspatch → 保存文件 → 重启游戏 → 观察效果 → 回到编辑器
                  ↑___________________________↓
                         5-10 秒延迟
```

❌ **错误定位困难**：
- 补丁加载失败只有简单日志（`[WARN] 跳过无效文件`）
- 没有 JSON Schema 实时校验（只能运行时发现错误）
- Cave 越界、地址冲突等问题难以追踪

❌ **批量操作繁琐**：
- 57 个补丁文件逐个管理（没有 Makefile / 构建脚本）
- 修改全局变量需要编辑 `_variables.tkspatch`，影响所有补丁
- 没有批量校验工具（`validate_all_patches.py`）

### 1.2 游戏启动器开发视角

❌ **热重载缺失**：
- 修改补丁必须重启游戏进程（而非热重载补丁模块）
- 无法在游戏运行时动态启用/禁用补丁

❌ **调试信息不足**：
- 缺少详细的内存快照（补丁应用前后对比）
- 没有补丁依赖关系可视化（哪些补丁会互相影响）
- Cave 布局可视化缺失（无法直观看到内存分配）

❌ **版本控制混乱**：
- 57 个散装文件在 Git 中难以管理
- 无法追踪"哪些补丁属于同一个功能模块"
- 回滚困难（需要逐个文件还原）

---

## 二、改进方案：分层工作流架构

### 2.1 核心设计理念

```
【生产环境】patches/               ← 玩家使用，稳定版本
     ↑
     │ 发布流程（自动打包 + 校验）
     │
【预发布】patches_staging/         ← 测试通过，待发布
     ↑
     │ 验证流程（集成测试 + 冲突检测）
     │
【开发环境】patches_dev/           ← 开发者工作区，实验性修改
     ├── core_fixes/               ← 按模块组织
     ├── balance_tweaks/
     └── experimental/
```

**关键原则**：
1. **环境隔离**：开发 / 测试 / 生产三层分离
2. **模块化**：补丁按功能模块组织，便于批量操作
3. **快速反馈**：提供实时校验 + 热重载机制

### 2.2 开发环境设置

#### 工作区结构

```
tks_launcher_gui/
├── patches/                      # 生产环境（只读，玩家使用）
│   ├── core_fixes_v1.5.tkspatchpak
│   └── _variables.tkspatch
│
├── patches_dev/                  # 开发环境（Git 管理）
│   ├── modules.json              # 模块定义文件
│   ├── core_fixes/               # 核心修复模块
│   │   ├── broke_weapon_fix.tkspatch
│   │   ├── gold_limit.tkspatch
│   │   └── module.json           # 模块元数据
│   ├── balance_tweaks/           # 数值平衡模块
│   └── experimental/             # 实验性补丁
│
├── patches_staging/              # 预发布环境（CI 自动生成）
│   └── *.tkspatchpak
│
└── tools/                        # 开发工具集
    ├── patch_validator.py        # 批量校验工具
    ├── patch_builder.py          # 构建脚本
    ├── patch_hotreload.py        # 热重载工具
    └── cave_visualizer.py        # Cave 布局可视化
```

#### modules.json 示例

```json
{
  "modules": [
    {
      "id": "core_fixes",
      "name": "核心修复",
      "version": "1.5.0",
      "patches_dir": "core_fixes/",
      "description": "基础 BUG 修复，必须启用",
      "required": true,
      "dependencies": [],
      "priority": 100
    },
    {
      "id": "balance_tweaks",
      "name": "数值平衡",
      "version": "0.8.0",
      "patches_dir": "balance_tweaks/",
      "description": "游戏平衡性调整，可选",
      "required": false,
      "dependencies": ["core_fixes"],
      "priority": 200
    },
    {
      "id": "experimental",
      "name": "实验性功能",
      "version": "0.1.0",
      "patches_dir": "experimental/",
      "description": "未经充分测试，仅供开发",
      "required": false,
      "dependencies": [],
      "priority": 999
    }
  ]
}
```

### 2.3 开发工具集

#### 工具 1: 批量校验器（`tools/patch_validator.py`）

```python
"""补丁批量校验工具 — 快速发现格式错误"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from core.tkspatch_loader import load_tkspatch_file, validate_tkspatch_dict
import json

def validate_all_patches(patches_dir: str, verbose: bool = False):
    """扫描目录下所有 .tkspatch 文件并校验。
    
    返回: (总数, 成功数, 失败列表)
    """
    errors = []
    total = 0
    success = 0
    
    for path in Path(patches_dir).rglob("*.tkspatch"):
        if path.name == "_variables.tkspatch":
            continue
        total += 1
        
        try:
            # 尝试加载补丁
            defn = load_tkspatch_file(str(path), log_func=print if verbose else None)
            if defn is None:
                errors.append((str(path), "加载失败"))
            else:
                success += 1
                if verbose:
                    print(f"✅ {path.name} - {defn.name or defn.id}")
        except Exception as e:
            errors.append((str(path), str(e)))
    
    return total, success, errors

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="批量校验补丁文件")
    parser.add_argument("dir", nargs="?", default="patches_dev", 
                       help="要校验的目录（默认: patches_dev）")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="显示详细信息")
    args = parser.parse_args()
    
    total, success, errors = validate_all_patches(args.dir, args.verbose)
    
    print(f"\n{'='*60}")
    print(f"总计: {total} 个补丁")
    print(f"成功: {success} 个")
    print(f"失败: {len(errors)} 个")
    
    if errors:
        print(f"\n❌ 失败列表:")
        for path, err in errors:
            print(f"  - {path}")
            print(f"    {err}")
        sys.exit(1)
    else:
        print(f"\n✅ 所有补丁校验通过！")
        sys.exit(0)
```

**使用示例**：
```bash
# 开发时实时校验
python tools/patch_validator.py patches_dev -v

# CI 流程中批量校验（返回非零退出码表示失败）
python tools/patch_validator.py patches_staging
```

#### 工具 2: 模块构建器（`tools/patch_builder.py`）

```python
"""模块化构建工具 — 按模块打包补丁"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from pathlib import Path
from core.tkspatch_packer import create_tkspatchpak

def build_module(module_def: dict, dev_dir: str, output_dir: str):
    """根据模块定义构建 .tkspatchpak 文件。"""
    module_id = module_def["id"]
    patches_dir = Path(dev_dir) / module_def["patches_dir"]
    
    # 收集模块内所有补丁
    patch_files = list(patches_dir.glob("*.tkspatch"))
    if not patch_files:
        print(f"⚠️  模块 {module_id} 没有补丁文件，跳过")
        return False
    
    # 输出路径
    output_path = Path(output_dir) / f"{module_id}_v{module_def['version']}.tkspatchpak"
    
    # 打包
    metadata = {
        "id": module_id,
        "name": module_def["name"],
        "version": module_def["version"],
        "description": module_def["description"],
        "load_order": module_def.get("priority", 100),
    }
    
    success, msg = create_tkspatchpak(
        [str(p) for p in patch_files],
        str(output_path),
        metadata,
        log_func=print
    )
    
    if success:
        print(f"✅ 构建成功: {output_path.name} ({len(patch_files)} 个补丁)")
        return True
    else:
        print(f"❌ 构建失败: {msg}")
        return False

def build_all_modules(dev_dir: str = "patches_dev", output_dir: str = "patches_staging"):
    """根据 modules.json 构建所有模块。"""
    modules_file = Path(dev_dir) / "modules.json"
    if not modules_file.exists():
        print(f"❌ 找不到 {modules_file}")
        return False
    
    with open(modules_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    Path(output_dir).mkdir(exist_ok=True)
    
    success_count = 0
    for module in config["modules"]:
        if build_module(module, dev_dir, output_dir):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"构建完成: {success_count}/{len(config['modules'])} 个模块")
    return success_count == len(config["modules"])

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="模块化构建补丁")
    parser.add_argument("--dev", default="patches_dev", help="开发目录")
    parser.add_argument("--output", default="patches_staging", help="输出目录")
    parser.add_argument("--module", help="只构建指定模块（省略则构建全部）")
    args = parser.parse_args()
    
    if args.module:
        # 单模块构建（用于快速迭代）
        modules_file = Path(args.dev) / "modules.json"
        with open(modules_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        module = next((m for m in config["modules"] if m["id"] == args.module), None)
        if module:
            success = build_module(module, args.dev, args.output)
            sys.exit(0 if success else 1)
        else:
            print(f"❌ 找不到模块: {args.module}")
            sys.exit(1)
    else:
        # 全部构建
        success = build_all_modules(args.dev, args.output)
        sys.exit(0 if success else 1)
```

**使用示例**：
```bash
# 开发时快速构建单个模块
python tools/patch_builder.py --module core_fixes

# 发布前构建全部模块
python tools/patch_builder.py --dev patches_dev --output patches_staging
```

#### 工具 3: 热重载工具（`tools/patch_hotreload.py`）

```python
"""补丁热重载工具 — 无需重启游戏即可更新补丁"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from core.tkspatch_loader import load_tkspatch_file

class PatchFileHandler(FileSystemEventHandler):
    """监听补丁文件变化并触发重新加载。"""
    
    def __init__(self, target_pid: int):
        self.target_pid = target_pid
        self.last_reload = {}
    
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.tkspatch'):
            return
        
        # 防抖动（1 秒内只触发一次）
        now = time.time()
        if event.src_path in self.last_reload:
            if now - self.last_reload[event.src_path] < 1.0:
                return
        self.last_reload[event.src_path] = now
        
        print(f"\n[{time.strftime('%H:%M:%S')}] 检测到文件变化: {Path(event.src_path).name}")
        
        # 重新加载补丁
        try:
            defn = load_tkspatch_file(event.src_path, log_func=print)
            if defn:
                print(f"✅ 补丁校验通过: {defn.name or defn.id}")
                print(f"   提示: 需要重启游戏以应用补丁（未来版本将支持真正的热重载）")
            else:
                print(f"❌ 补丁加载失败，请检查格式")
        except Exception as e:
            print(f"❌ 错误: {e}")

def watch_patches(watch_dir: str, target_pid: int = None):
    """监听补丁目录的文件变化。"""
    print(f"开始监听: {watch_dir}")
    print(f"目标进程 PID: {target_pid or '未指定（仅校验模式）'}")
    print(f"按 Ctrl+C 停止...\n")
    
    event_handler = PatchFileHandler(target_pid)
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n已停止监听")
    
    observer.join()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="补丁热重载工具")
    parser.add_argument("dir", nargs="?", default="patches_dev",
                       help="要监听的目录（默认: patches_dev）")
    parser.add_argument("--pid", type=int, help="游戏进程 PID（未来用于真正的热重载）")
    args = parser.parse_args()
    
    watch_patches(args.dir, args.pid)
```

**使用示例**：
```bash
# 开发时启动文件监听（保持运行）
python tools/patch_hotreload.py patches_dev

# 修改任意 .tkspatch 文件，工具会自动校验并提示
```

#### 工具 4: Cave 布局可视化（`tools/cave_visualizer.py`）

```python
"""Cave 内存布局可视化工具"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tkspatch_loader import load_config_merged
from core.cave_layout import CaveLayout

def visualize_cave_layout(patches_dir: str, variables: dict):
    """生成 Cave 布局的 ASCII 可视化图。"""
    cave_addr = variables.get("cave_base", 0)
    cave_budget = variables.get("cave_total_size", 2048)
    
    if not cave_addr:
        print("❌ 未定义 cave_base，无法可视化")
        return
    
    config = load_config_merged(None, patches_dir, log_func=print)
    if not config:
        print("❌ 加载补丁配置失败")
        return
    
    # 构建布局
    layout = CaveLayout(base_addr=cave_addr, budget=cave_budget)
    
    # 收集每个补丁的 cave 需求
    allocations = []
    for defn in config.patches:
        if defn.type == "cave_hook":
            size = len(getattr(defn, '_cave_code_bytes', b'')) or 64  # 估算
            offset = defn.cave_offset
            allocations.append({
                "id": defn.id,
                "offset": offset,
                "size": size,
                "type": "cave_hook"
            })
    
    # ASCII 可视化
    print(f"\n{'='*70}")
    print(f"Cave 布局可视化 (Base: 0x{cave_addr:08X}, Size: {cave_budget} bytes)")
    print(f"{'='*70}\n")
    
    # 简化的条形图
    scale = 50  # 显示宽度
    for alloc in sorted(allocations, key=lambda a: a["offset"]):
        bar_start = int(alloc["offset"] / cave_budget * scale)
        bar_width = max(1, int(alloc["size"] / cave_budget * scale))
        bar = " " * bar_start + "█" * bar_width
        print(f"{alloc['id']:30s} │{bar}")
        print(f"{'':30s} │ 0x{alloc['offset']:04X} ~ 0x{alloc['offset']+alloc['size']:04X} ({alloc['size']} bytes)")
    
    # 使用率统计
    used = sum(a["size"] for a in allocations)
    print(f"\n{'='*70}")
    print(f"已使用: {used}/{cave_budget} bytes ({used/cave_budget*100:.1f}%)")
    print(f"剩余: {cave_budget - used} bytes")
    
    if used > cave_budget:
        print(f"\n❌ 警告: Cave 空间超出预算 {used - cave_budget} bytes！")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cave 布局可视化")
    parser.add_argument("dir", nargs="?", default="patches_dev",
                       help="补丁目录")
    args = parser.parse_args()
    
    # 读取全局变量
    from core.tkspatch_loader import load_variables_from_dir
    variables = load_variables_from_dir(args.dir)
    
    visualize_cave_layout(args.dir, variables)
```

**使用示例**：
```bash
python tools/cave_visualizer.py patches_dev

# 输出示例:
# ======================================================================
# Cave 布局可视化 (Base: 0x00AB0000, Size: 2048 bytes)
# ======================================================================
#
# broke_weapon_fix              │████
#                               │ 0x0000 ~ 0x0040 (64 bytes)
# summon_extend_v15             │      ████████████
#                               │ 0x0040 ~ 0x0200 (448 bytes)
# ...
```

---

## 三、完整的开发工作流

### 3.1 日常开发流程

```bash
# 1. 启动文件监听（后台运行）
python tools/patch_hotreload.py patches_dev &

# 2. 编辑补丁文件
vim patches_dev/core_fixes/gold_limit.tkspatch

# 3. 保存后自动触发校验（无需手动运行）
# [02:15:30] 检测到文件变化: gold_limit.tkspatch
# ✅ 补丁校验通过: 金钱上限调整

# 4. 快速构建单个模块（测试用）
python tools/patch_builder.py --module core_fixes

# 5. 可视化检查 Cave 布局（避免冲突）
python tools/cave_visualizer.py patches_dev
```

### 3.2 提交前流程（自动化）

创建 `Makefile`（或 `build.py`）：

```makefile
.PHONY: validate build test clean

# 批量校验所有补丁
validate:
	python tools/patch_validator.py patches_dev

# 构建所有模块
build:
	python tools/patch_builder.py --dev patches_dev --output patches_staging

# 运行测试（集成测试）
test:
	pytest tests/test_patch_loading.py -v

# 清理临时文件
clean:
	rm -rf patches_staging/*.tkspatchpak

# 完整流程：校验 → 构建 → 测试
all: validate build test
	@echo "✅ 所有检查通过，可以提交代码"
```

**使用示例**：
```bash
# 提交前运行完整检查
make all

# 或单独运行某个步骤
make validate
make build
```

### 3.3 CI/CD 流程（GitHub Actions 示例）

```yaml
# .github/workflows/patch_validation.yml
name: Patch Validation

on:
  push:
    paths:
      - 'tks_launcher_gui/patches_dev/**'
  pull_request:
    paths:
      - 'tks_launcher_gui/patches_dev/**'

jobs:
  validate:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd tks_launcher_gui
          pip install -r requirements.txt
      
      - name: Validate all patches
        run: |
          cd tks_launcher_gui
          python tools/patch_validator.py patches_dev
      
      - name: Build modules
        run: |
          cd tks_launcher_gui
          python tools/patch_builder.py
      
      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        with:
          name: patch-packages
          path: tks_launcher_gui/patches_staging/*.tkspatchpak
```

---

## 四、高级调试技巧

### 4.1 补丁加载追踪

在 `tkspatch_loader.py` 中添加详细日志：

```python
# 在 load_config_merged 开头添加
import logging
logging.basicConfig(
    filename='patch_loading.log',
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

def load_tkspatch_file(path: str, log_func=None) -> Optional[PatchDef]:
    log = log_func or (lambda x: None)
    logging.debug(f"开始加载: {path}")
    
    # ... 现有逻辑 ...
    
    if defn:
        logging.info(f"成功加载: {defn.id} ({defn.type})")
    else:
        logging.warning(f"加载失败: {path}")
    
    return defn
```

### 4.2 内存快照对比

创建 `tools/memory_snapshot.py`：

```python
"""在补丁应用前后对比内存快照"""
from core.memory import read_pm

def take_snapshot(h_proc: int, base_addr: int, size: int) -> bytes:
    """读取指定内存区域的快照。"""
    return read_pm(h_proc, base_addr, size)

def compare_snapshots(before: bytes, after: bytes) -> list:
    """对比两个快照，返回差异列表。"""
    diffs = []
    for i, (b1, b2) in enumerate(zip(before, after)):
        if b1 != b2:
            diffs.append((i, b1, b2))
    return diffs

# 使用示例（在 patch_engine.py 中插入）:
# before = take_snapshot(h_proc, code_start_addr, len(code_buf))
# apply_patch_bytes(...)  # 应用补丁
# after = take_snapshot(h_proc, code_start_addr, len(code_buf))
# diffs = compare_snapshots(before, after)
# for offset, old, new in diffs:
#     print(f"0x{offset:08X}: 0x{old:02X} → 0x{new:02X}")
```

### 4.3 补丁依赖关系图

创建 `tools/dependency_graph.py`：

```python
"""生成补丁依赖关系图（GraphViz 格式）"""
import json
from pathlib import Path

def generate_dependency_graph(modules_file: str, output_file: str):
    """生成 DOT 格式的依赖图。"""
    with open(modules_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    dot = ["digraph PatchDependencies {"]
    dot.append("  rankdir=LR;")
    dot.append("  node [shape=box, style=rounded];")
    
    for module in config["modules"]:
        mid = module["id"]
        label = f"{module['name']}\\nv{module['version']}"
        color = "lightblue" if module.get("required") else "lightgray"
        dot.append(f'  "{mid}" [label="{label}", fillcolor={color}, style=filled];')
        
        for dep in module.get("dependencies", []):
            dot.append(f'  "{dep}" -> "{mid}";')
    
    dot.append("}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(dot))
    
    print(f"依赖图已生成: {output_file}")
    print(f"可使用 Graphviz 渲染: dot -Tpng {output_file} -o deps.png")

if __name__ == "__main__":
    generate_dependency_graph(
        "patches_dev/modules.json",
        "patch_deps.dot"
    )
```

---

## 五、最佳实践建议

### 5.1 模块化组织原则

✅ **按功能分组**：
- `core_fixes/` - 必须启用的核心修复
- `balance/` - 数值平衡调整（可选）
- `ui_enhancements/` - UI 改进（可选）
- `experimental/` - 实验性功能（默认禁用）

✅ **模块独立性**：
- 每个模块有独立的 `module.json` 元数据
- 模块间依赖显式声明（`dependencies` 字段）
- 避免隐式依赖（如共享 Cave 偏移）

✅ **版本管理**：
- 模块版本独立迭代（`core_fixes v1.5` + `balance v0.8`）
- 使用语义化版本号（`major.minor.patch`）
- 每次发布更新 `CHANGELOG.md`

### 5.2 Git 工作流建议

```bash
# 分支策略
main              # 稳定版本，对应 patches/
  ├── develop     # 开发主分支，对应 patches_dev/
  │   ├── feature/gold-cap-increase    # 功能分支
  │   └── fix/broke-weapon-crash       # 修复分支
  └── release/v1.5                     # 发布分支

# 提交信息规范
git commit -m "fix(core_fixes): 修复破武器概率计算溢出"
git commit -m "feat(balance): 增加金钱上限至 999,999,999"
git commit -m "chore(tools): 添加 Cave 可视化工具"
```

### 5.3 代码审查检查清单

PR 提交前检查：
- [ ] 运行 `make validate` 通过
- [ ] 运行 `make build` 成功
- [ ] Cave 布局无冲突（`cave_visualizer.py`）
- [ ] 更新 `CHANGELOG.md`
- [ ] 补丁有对应的单元测试
- [ ] 文档已更新（如有新的补丁类型）

---

## 六、总结

### 核心改进点

1. **环境隔离**：`patches/` (生产) + `patches_dev/` (开发) + `patches_staging/` (预发布)
2. **模块化**：按功能分组，便于批量操作和版本管理
3. **自动化工具**：
   - `patch_validator.py` - 批量校验
   - `patch_builder.py` - 模块化构建
   - `patch_hotreload.py` - 文件监听 + 实时校验
   - `cave_visualizer.py` - 内存布局可视化
4. **快速反馈**：修改 → 自动校验 → 即时提示（< 1 秒）
5. **CI/CD 集成**：GitHub Actions 自动化检查和构建

### 预期效果

- ⏱️ **开发效率提升 3-5 倍**（批量操作 + 实时反馈）
- 🐛 **BUG 发现提前**（提交前批量校验，而非运行时崩溃）
- 📦 **分发便捷**（模块化打包，按需组合）
- 🔧 **维护成本降低**（Git 友好，版本清晰）

### 下一步行动

1. **立即可实施**：
   - 创建 `tools/patch_validator.py`（1 小时）
   - 创建 `tools/patch_builder.py`（2 小时）
   - 重组 `patches_dev/` 目录结构（30 分钟）

2. **短期规划**（1-2 周）：
   - 实现 `patch_hotreload.py` 文件监听
   - 添加 `cave_visualizer.py` 可视化工具
   - 编写 Makefile / CI 配置

3. **长期目标**（1-2 个月）：
   - 真正的热重载（无需重启游戏）
   - Web UI 管理界面（可视化编辑补丁）
   - 自动化回归测试（模拟游戏场景）

---

**附录：工具依赖清单**

```bash
# requirements_dev.txt
watchdog>=3.0.0      # 文件监听（hotreload）
graphviz>=0.20       # 依赖图生成
pytest>=7.0.0        # 单元测试
colorama>=0.4.6      # 终端彩色输出
```
