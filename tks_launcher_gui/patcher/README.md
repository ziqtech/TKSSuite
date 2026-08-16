# Patcher 补丁构建工具

这个目录包含用于构建 TKS 启动器补丁的工具。

## 目录结构

```
patcher/
├── __init__.py           # 包初始化文件
├── build_patches.py      # 核心构建工具
├── migrate_patches.py    # 迁移工具（将现有 .tkspatch 转为源码格式）
└── README.md            # 本文件
```

## 核心工具

### 1. build_patches.py

将补丁源码目录打包为 .tkspatch 文件。

**使用方式**：

```bash
cd tks_launcher_gui
python patcher/build_patches.py --src patches --dst ../../dist/TKSLauncher/patches
```

**功能**：
- 扫描 `patches/` 目录下的所有子目录
- 读取每个子目录中的 `patch.json`
- 打包为 ZIP 格式的 `.tkspatch` 文件
- 输出到指定目录

### 2. migrate_patches.py

将现有的 `.tkspatch` 文件转换为源码目录格式。

**使用方式**：

```bash
cd tks_launcher_gui
python patcher/migrate_patches.py --src patches_old --dst patches
```

**功能**：
- 扫描指定目录下的所有 `.tkspatch` 文件
- 解压 ZIP 格式的 `.tkspatch` 为源码目录
- 或将 JSON 格式的 `.tkspatch` 转为源码目录

## 集成到 build_all.py

构建工具已经集成到 `build/build_all.py` 中。

当执行以下命令时，会自动调用补丁构建：

```bash
# 只构建 GUI 版本启动器
python build_all.py --only TKSLauncher

# 只构建 CLI 版本启动器
python build_all.py --only TKSLauncherCLI

# 构建所有项目
python build_all.py
```

构建流程：
1. 编译 C# 启动器 exe
2. 复制 Python 模块
3. **自动调用 `build_patches.py` 构建补丁**
4. 复制配置文件和其他资源

## 补丁源码格式

### 开发环境（源码）

```
patches/
├── global_variables/            # 全局变量补丁源码目录
│   └── patch.json
├── gold_limit/                  # 补丁源码目录
│   └── patch.json
├── summon_extend_v15/
│   ├── patch.json
│   └── summon_table.json
└── custom_logic/
    ├── patch.json
    └── script.py
```

### 生产环境（打包产物）

```
dist/TKSLauncher/patches/
├── global_variables.tkspatch    # ZIP 格式
├── gold_limit.tkspatch          # ZIP 格式
├── summon_extend_v15.tkspatch
└── custom_logic.tkspatch
```

## 开发工作流

### 1. 编辑补丁

直接编辑源码目录中的文件：

```bash
cd tks_launcher_gui/patches/gold_limit
vim patch.json
```

### 2. 提交代码

```bash
git add patches/gold_limit/
git commit -m "fix(gold_limit): 修复金钱上限溢出"
```

### 3. 构建发布

```bash
cd build
python build_all.py --only TKSLauncher
```

构建完成后，`dist/TKSLauncher/patches/` 目录下会包含打包好的 `.tkspatch` 文件。

## 补丁示例

### 简单补丁（patch_imm32）

**目录**：`patches/gold_limit/`

**patch.json**：
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

### 脚本补丁（script）

**目录**：`patches/custom_logic/`

**patch.json**：
```json
{
  "type": "script",
  "id": "custom_logic",
  "name": "自定义逻辑",
  "script_file": "script.py"
}
```

**script.py**：
```python
def apply(ctx):
    ctx.log("正在应用自定义逻辑补丁...")
    # 补丁逻辑
    return True
```

### 数据补丁（patch_summon_table）

**目录**：`patches/summon_extend_v15/`

**patch.json**：
```json
{
  "type": "patch_summon_table",
  "id": "summon_extend_v15",
  "name": "召唤表扩展 v15",
  "json_file": "summon_table.json",
  "data_rva": "0x9D705A"
}
```

**summon_table.json**：
```json
[
  {"id": 1, "level": 10, "hp": 500, "mp": 100}
]
```

## 注意事项

1. **开发环境使用源码格式**：便于编辑和 Git 管理
2. **生产环境自动打包**：`build_all.py` 会自动调用构建工具
3. **补丁目录结构**：每个补丁是一个独立目录，必须包含 `patch.json`
4. **全局变量补丁**：`global_variables/patch.json` 与普通补丁一样打包为 `global_variables.tkspatch`

## 迁移现有补丁

如果你的 `patches/` 目录当前包含 `.tkspatch` 文件，可以使用迁移工具转换为源码格式：

```bash
cd tks_launcher_gui

# 备份现有目录
mv patches patches_old

# 运行迁移
python patcher/migrate_patches.py --src patches_old --dst patches

# 验证结果
ls -R patches/
```
