# TKS 启动器配置与运行时状态重构方案

- **状态**：待实施方案
- **范围**：`tks_launcher_gui`
- **性质**：破坏性重构
- **兼容策略**：不兼容旧版
- **最后确认**：2026-08-17

## 1. 背景

当前 TKS 启动器同时使用多套配置和变量来源：

- 旧版 `tks_patches.json` 作为基础补丁配置；
- `patches/global_variables/patch.json` 作为全局变量补丁；
- `_variables.json` 与 `_variables.tkspatch` 作为外置变量来源；
- `PatchConfig.variables` 作为静态配置、运行时状态和临时参数的混合字典；
- `PatchContext.variables` 继续把这个混合字典暴露给补丁 handler 和外部脚本。

这种设计导致几个问题：

1. 静态配置与运行时计算结果没有类型和生命周期边界；
2. `warpc_new_size` 等关键值依赖字符串键传递；
3. GUI、CLI 和流水线都必须理解旧配置回退规则；
4. 旧配置和新 `.tkspatch` 目录同时存在时，补丁来源和优先级不直观；
5. 外部脚本可以读取任何变量，接口边界不明确。

本方案将配置定义、静态参数和运行时状态分离，并直接移除旧配置链。

## 2. 已确定的设计决策

### 2.1 WarPC 使用通用表达式方案

保留现有补丁定义形式：

```json
{
  "type": "patch_imm32",
  "id": "warpc_size_refs",
  "new_value": "{warpc_new_size}"
}
```

不新增 `patch_warpc_size` 专用类型。

变化仅发生在表达式解析来源：

```text
旧：resolve_var(expr, config.variables)
新：resolve_patch_value(expr, settings, runtime)
```

因此，现有 `{warpc_new_size}`、`{save_new_size}` 等表达式仍然有效，但不再从全局字典读取。

### 2.2 直接删除旧 `tks_patches.json`

旧 `tks_patches.json` 直接删除，不保留以下任何能力：

- 旧文件读取；
- 字段迁移；
- 兼容判断；
- 废弃警告；
- 缺失新配置时回退旧文件；
- 旧配置与新补丁目录合并；
- 旧配置中的 `variables` 提取。

旧版启动器和旧版补丁包不在本次重构的支持范围内。

### 2.3 直接删除全局变量补丁

直接删除：

```text
tks_launcher_gui/patches/global_variables/patch.json
```

不使用另一个 JSON 文件替代它，不保留 `global_variables` patch type。

### 2.4 不兼容旧外部脚本接口

仓库内脚本全部迁移到新的 `ctx.settings` 和 `ctx.runtime` 接口。

不保留：

```text
ctx.variables
```

第三方旧版脚本如果依赖 `ctx.variables`，需要按新接口改写后才能使用。

## 3. 最终配置模型

### 3.1 `PatchConfig`

`PatchConfig` 只保存补丁定义：

```python
@dataclass
class PatchConfig:
    patches: List[PatchDef] = field(default_factory=list)
```

删除：

```python
variables: Dict[str, int]
```

`PatchConfig` 的职责是描述“有哪些补丁”，不负责保存参数和运行时状态。

### 3.2 `PatchSettings`

新增不可变的静态配置对象，保存补丁执行所需的固定参数：

```python
@dataclass(frozen=True)
class PatchSettings:
    warpc_base_fallback: int = 0x757F08
    warpc_rec_size: int = 1054
    save_block_ab_size: int = 9200

    tkkon_orig_size: int = 26000
    tkkon_rec_size: int = 40
    tkkon_base: int = 0x9D0698

    tkact_orig_size: int = 509600
    tkact_rec_size: int = 784
    tkact_base: int = 0x9539CA

    tkdefunit_orig_count: int = 5000
    cave_total_size: int = 2048
```

字段含义：

| 字段 | 作用 |
|---|---|
| `warpc_base_fallback` | 自动发现 WarPC 基址失败时使用的备用值 |
| `warpc_rec_size` | WarPC 单条记录大小 |
| `save_block_ab_size` | 存档 AB 区中 WarPC 数据块前置大小 |
| `tkkon_orig_size` | TKKon 原始数据大小 |
| `tkkon_rec_size` | TKKon 单条记录大小 |
| `tkkon_base` | TKKon 原始基址 |
| `tkact_orig_size` | TKAct 原始数据大小 |
| `tkact_rec_size` | TKAct 单条记录大小 |
| `tkact_base` | TKAct 原始基址 |
| `tkdefunit_orig_count` | TKDefUnit 原始记录数 |
| `cave_total_size` | Cave 内存布局预算 |

以下值不再作为全局变量迁移：

- `warpc_orig_count`；
- `warpc_total_orig_size`；
- `tkmat_orig_size`；
- `tkitem_orig_size`；
- `tkskill_orig_size`；
- `tkshop_orig_size`；
- `tkkon_orig_count`；
- `tkact_orig_count`。

如果某个值是游戏布局的固定常量，应由对应核心模块中的已有常量提供；如果是实际运行数据，应进入 `PatchRuntimeState`。

### 3.3 `PatchRuntimeState`

新增可变运行时状态对象：

```python
@dataclass
class PatchRuntimeState:
    target_pid: int = 0

    warpc_base: int = 0
    warpc_new_base: int = 0
    warpc_new_size: int = 0
    save_new_size: int = 0

    tkmat_actual_size: int = 0
    tkitem_actual_size: int = 0
    tkskill_actual_size: int = 0
    tkshop_actual_size: int = 0
    tkkon_actual_size: int = 0
    tkact_new_size: int = 0
    tkdefunit_new_count: int = 0
```

运行时字段初始值使用 `0`，不使用旧尺寸作为隐式默认值。补丁执行前如果必需值仍为未初始化状态，应记录错误并跳过相关补丁。

## 4. 表达式解析设计

新增统一解析接口：

```text
resolve_patch_value(expression, settings, runtime, log_func=None)
```

解析规则：

| 表达式 | 来源 |
|---|---|
| `0xFFFF` | 直接解析为整数 |
| `1234` | 直接解析为整数 |
| `{warpc_rec_size}` | `settings.warpc_rec_size` |
| `{cave_total_size}` | `settings.cave_total_size` |
| `{warpc_new_size}` | `runtime.warpc_new_size` |
| `{save_new_size}` | `runtime.save_new_size` |
| `{tkitem_actual_size}` | `runtime.tkitem_actual_size` |
| `{tkdefunit_new_count}` | `runtime.tkdefunit_new_count` |

查找顺序固定为：

```text
1. PatchRuntimeState
2. PatchSettings
3. 都不存在时记录未定义参数并返回 None
```

不再接受 `Dict[str, int]` 作为表达式解析输入。

## 5. `PatchContext` 设计

`PatchContext` 增加两个明确字段：

```text
ctx.settings: PatchSettings
ctx.runtime: PatchRuntimeState
```

上下文中的核心数据关系：

```text
ctx.defn       当前补丁定义
ctx.settings   固定配置
ctx.runtime    本次启动的运行时状态
ctx.code_buf   代码段缓冲
ctx.h_proc     目标进程句柄
ctx.cave_addr  Cave 地址
ctx.warpc_base WarPC 当前基址
```

删除：

```text
ctx.variables
```

handler 和外部脚本必须根据字段性质选择来源：

```text
固定布局参数：ctx.settings.tkkon_rec_size
运行时扩容结果：ctx.runtime.warpc_new_size
```

## 6. 启动流水线数据流

### 6.1 启动前

```text
PatcherPipeline 初始化
    -> 创建 PatchSettings
    -> 创建 PatchRuntimeState
    -> 加载 patches/ 目录
    -> 加载 MOD
    -> 准备 WarPC 和 DAT 文件
```

### 6.2 目标进程启动后

```text
发现目标进程
    -> 设置 runtime.target_pid
    -> 扫描 WarPC 基址
    -> 设置 runtime.warpc_base
    -> 分配或确定 WarPC 新缓冲区
    -> 设置 runtime.warpc_new_base
    -> 计算 runtime.warpc_new_size
    -> 计算 runtime.save_new_size
    -> 计算其他 *_actual_size
    -> 应用补丁
```

### 6.3 WarPC 状态

未扩容时：

```text
runtime.warpc_new_size = WARPC_ORIG_SIZE
runtime.save_new_size = WARPC_TOTAL_ORIG_SIZE
```

扩容时：

```text
runtime.warpc_new_size = len(full_data)
runtime.save_new_size = settings.save_block_ab_size + runtime.warpc_new_size
```

`warpc_size_refs` 通过 `{warpc_new_size}` 获取该值，不改变补丁 JSON 的表达式格式。

## 7. 配置加载重构

### 7.1 唯一加载入口

新的加载流程只扫描 `patches/`：

```text
patches/
    ├── <patch_id>/patch.json
    ├── <patch_id>/script.py
    └── <patch_id>.tkspatch
```

允许的补丁来源：

- 目录型补丁的 `patch.json`；
- ZIP 型 `.tkspatch`；
- 补丁内嵌的 `script.py`；
- 受支持的外置补丁数据文件。

### 7.2 删除旧加载路径

从 `config_loader.py` 和 `tkspatch_loader.py` 删除：

- `tks_patches.json` 的加载；
- `load_config_merged()` 中的旧配置回退；
- `_variables.json` 的加载；
- `_variables.tkspatch` 的加载；
- `global_variables` 类型提取；
- `PatchConfig.variables` 更新；
- 旧配置路径的多级回退；
- “补丁目录为空则回退旧配置”的逻辑。

`load_config_merged()` 如果保留名称，也必须改成只加载补丁目录的无旧版语义；更推荐重命名为：

```text
load_patch_directory(patches_dir, log_func=None)
```

并同步修改所有调用方。

### 7.3 新的失败行为

当 `patches/` 不存在、为空或没有有效补丁时：

```text
记录错误
返回失败结果
停止启动流程
```

不得尝试读取旧 `tks_patches.json`。

## 8. 调用方调整

必须同步修改以下调用方：

```text
tks_launcher_gui/main.py
tks_launcher_gui/cli_launcher.py
tks_launcher_gui/ui/main_window.py
tks_launcher_gui/core/launcher_pipeline.py
```

它们不再拼接或传递：

```text
<exe_dir>/tks_patches.json
```

只传递：

```text
patches_dir
```

GUI 的补丁列表也必须直接从新的补丁目录加载，不再依赖旧配置文件才能显示列表。

## 9. 外部扩容脚本调整

### 9.1 `tkkon_expand`

旧代码从：

```text
ctx.variables
```

读取：

```text
tkkon_orig_size
tkkon_rec_size
tkkon_base
```

新代码从：

```text
ctx.settings.tkkon_orig_size
ctx.settings.tkkon_rec_size
ctx.settings.tkkon_base
```

读取。

脚本内用于兼容旧变量字典的 fallback 常量应删除。默认值由 `PatchSettings` 统一提供。

### 9.2 `tkact_expand`

同样改为：

```text
ctx.settings.tkact_orig_size
ctx.settings.tkact_rec_size
ctx.settings.tkact_base
```

不再读取 `ctx.variables`。

### 9.3 其他脚本

全仓库搜索以下模式并逐一处理：

```text
ctx.variables
config.variables
variables.get(
variables["
```

所有内部脚本和 handler 都必须迁移到 `settings` 或 `runtime`。

## 10. 构建与补丁工具调整

需要检查并修改：

```text
tks_launcher_gui/patcher/build_patches.py
tks_launcher_gui/patcher/migrate_patches.py
```

### 10.1 `build_patches.py`

删除对 `global_variables` 的特殊说明和特殊构建分支。普通补丁统一按目录型或 ZIP 型 `.tkspatch` 构建。

### 10.2 `migrate_patches.py`

旧迁移工具不再作为启动器运行链的一部分。由于本方案不兼容旧版：

- 不需要将 `_variables.tkspatch` 转换为 `global_variables`；
- 不需要将旧 `tks_patches.json` 转换为新目录；
- 不需要为旧发布目录提供迁移入口。

如果该脚本没有其他用途，应从发布流程中移除；是否删除脚本本身由实现阶段根据仓库其他调用关系决定。

## 11. 文件变更清单

### 11.1 必须修改

```text
tks_launcher_gui/core/config_loader.py
tks_launcher_gui/core/tkspatch_loader.py
tks_launcher_gui/core/launcher_pipeline.py
tks_launcher_gui/core/patch_engine.py
tks_launcher_gui/main.py
tks_launcher_gui/cli_launcher.py
tks_launcher_gui/ui/main_window.py
tks_launcher_gui/patches/tkkon_expand/script.py
tks_launcher_gui/patches/tkact_expand/script.py
```

### 11.2 必须删除

```text
tks_launcher_gui/tks_patches.json
tks_launcher_gui/patches/global_variables/patch.json
```

如果发行目录或其他源码目录存在同名旧配置，也必须一并确认并删除，避免构建时重新打包进去。

### 11.3 需要检查但不应无故修改

以下补丁定义继续使用 `{...}` 表达式，不需要改变字段格式：

```text
tks_launcher_gui/patches/warpc_size_refs/patch.json
tks_launcher_gui/patches/warpc_base_refs/patch.json
tks_launcher_gui/patches/tkmat_size/patch.json
tks_launcher_gui/patches/tkitem_expand/patch.json
tks_launcher_gui/patches/tkskill_size/patch.json
tks_launcher_gui/patches/tkshop_size/patch.json
tks_launcher_gui/patches/tkdefunit_count/patch.json
```

只在字段映射或路径确实受新加载器影响时修改。

## 12. 测试方案

### 12.1 配置模型测试

验证：

- `PatchConfig` 不再有 `variables` 属性；
- 补丁目录能加载所有有效补丁；
- 空补丁目录返回失败；
- 不存在旧 `tks_patches.json` 时流程不会报“回退旧配置”并继续；
- 存在旧 `tks_patches.json` 时也不会读取它。

### 12.2 静态设置测试

验证 `PatchSettings` 默认值与现有有效布局一致：

```text
warpc_base_fallback = 0x757F08
warpc_rec_size = 1054
save_block_ab_size = 9200
tkkon_orig_size = 26000
tkkon_rec_size = 40
tkkon_base = 0x9D0698
tkact_orig_size = 509600
tkact_rec_size = 784
tkact_base = 0x9539CA
tkdefunit_orig_count = 5000
cave_total_size = 2048
```

### 12.3 表达式测试

验证：

- 十六进制常量仍能解析；
- 十进制常量仍能解析；
- 静态字段从 `PatchSettings` 获取；
- 运行时字段从 `PatchRuntimeState` 获取；
- 未定义字段返回 `None` 并记录日志；
- `{warpc_new_size}` 解析结果不依赖任何字典。

### 12.4 WarPC 测试

未扩容场景：

```text
runtime.warpc_new_size == WARPC_ORIG_SIZE
runtime.save_new_size == WARPC_TOTAL_ORIG_SIZE
```

扩容场景：

```text
runtime.warpc_new_size == len(expanded_warpc_data)
runtime.save_new_size == 9200 + runtime.warpc_new_size
```

同时验证 `warpc_size_refs` 能正确应用到目标位置。

### 12.5 其他动态值测试

验证以下值均在对应补丁执行前正确填充：

```text
tkmat_actual_size
tkitem_actual_size
tkskill_actual_size
tkshop_actual_size
tkdefunit_new_count
tkact_new_size
```

### 12.6 脚本测试

验证：

- `tkkon_expand` 只使用 `ctx.settings`；
- `tkact_expand` 只使用 `ctx.settings`；
- 脚本不再访问 `ctx.variables`；
- 脚本参数缺失时不会静默使用旧变量字典。

### 12.7 启动路径测试

分别验证：

- GUI 启动；
- CLI 正常启动；
- CLI 诊断模式；
- 补丁目录正常；
- 补丁目录缺失；
- 补丁目录为空；
- 存在旧 `tks_patches.json` 但不应被读取。

### 12.8 静态搜索验收

实现完成后执行全仓库搜索，以下运行时代码引用必须为零：

```text
config.variables
ctx.variables
GLOBAL_VARIABLES_ID
GLOBAL_VARIABLES_TYPE
_variables.json
_variables.tkspatch
load_config_merged(... tks_patches.json ...)
```

以下旧文件也必须不存在：

```text
tks_patches.json
global_variables/patch.json
```

## 13. 实施顺序

### 阶段一：建立状态模型

1. 在核心配置模块定义 `PatchSettings`；
2. 在流水线模块或独立状态模块定义 `PatchRuntimeState`；
3. 确认默认值来自现有实际常量，不重新推测布局参数。

验收：状态对象可单独实例化，默认值测试通过。

### 阶段二：迁移表达式解析

1. 将 `resolve_var` 替换为 `resolve_patch_value`；
2. 修改 `patch_imm32`、cave 和其他需要动态值的 handler；
3. 保持补丁 JSON 中 `{...}` 表达式不变。

验收：静态表达式和运行时表达式测试通过。

### 阶段三：迁移流水线

1. `PatcherPipeline` 创建 `settings` 和 `runtime`；
2. WarPC 扫描结果写入 `runtime`；
3. WarPC 扩容结果写入 `runtime`；
4. DAT/TKAct/TKDefUnit 计算结果写入 `runtime`；
5. Cave 预算和固定布局参数从 `settings` 读取。

验收：流水线内部不再写入 `config.variables`。

### 阶段四：迁移上下文和脚本

1. `PatchContext` 接收 `settings` 和 `runtime`；
2. 所有 handler 删除变量字典参数；
3. `tkkon_expand` 和 `tkact_expand` 改用 `ctx.settings`；
4. 其他内部脚本和脚本测试同步修改。

验收：仓库内不再有 `ctx.variables`。

### 阶段五：删除旧加载链

1. 删除 `tks_patches.json` 的调用方参数；
2. 删除旧配置加载函数和 fallback；
3. 删除全局变量文件加载；
4. 将加载入口收敛为补丁目录；
5. 删除 `patches/global_variables/patch.json`；
6. 删除 `tks_launcher_gui/tks_patches.json`。

验收：只存在新补丁目录加载路径。

### 阶段六：验证和构建

1. 运行 Python 语法检查；
2. 运行已有测试；
3. 运行配置加载和表达式测试；
4. 运行 CLI 诊断流程；
5. 按项目构建规则重新构建 TKSLauncher；
6. 检查构建产物中没有旧配置文件。

## 14. 风险与处理

### 14.1 旧配置仍被构建脚本复制

处理：

- 搜索所有 `tks_patches.json` 的复制和打包规则；
- 删除构建清单中的旧文件；
- 构建后检查发行目录。

### 14.2 运行时状态填充顺序错误

处理：

- 所有动态补丁执行前确保对应字段已填充；
- 默认值使用 `0`；
- 对 WarPC 扩容结果增加明确日志；
- 不使用变量字典的隐式 fallback。

### 14.3 旧外部 `.tkspatch` 脚本无法运行

这是预期行为，不增加兼容层。发布说明需要明确：

```text
旧版脚本如果使用 ctx.variables，必须迁移到 ctx.settings / ctx.runtime。
```

### 14.4 静态参数散落在脚本中的重复常量

处理：

- 迁移到 `PatchSettings` 的字段必须由脚本统一读取；
- 删除脚本中的旧尺寸和基址 fallback；
- 不在本次重构中顺便重写无关的逆向常量。

## 15. 最终验收标准

只有同时满足以下条件，重构才算完成：

1. 旧 `tks_patches.json` 已删除；
2. `patches/global_variables/patch.json` 已删除；
3. 启动器不再读取、迁移或兼容旧配置；
4. `PatchConfig` 不再包含 `variables`；
5. `PatchContext` 不再暴露 `variables`；
6. 静态参数集中在 `PatchSettings`；
7. 运行时结果集中在 `PatchRuntimeState`；
8. `{warpc_new_size}` 仍通过通用表达式机制工作；
9. WarPC 未扩容和扩容场景的尺寸计算均正确；
10. TKKon/TKAct、DAT、TKDefUnit 相关补丁继续正常工作；
11. GUI、CLI 和共享流水线使用同一套加载路径和状态模型；
12. 构建产物中不包含旧配置文件和全局变量补丁；
13. 全仓库没有旧变量字典和旧配置回退逻辑的运行时代码引用。

## 16. 非目标

本次重构不包含：

- 新增 WarPC 专用 patch type；
- 修改现有 `{...}` 表达式语法；
- 修改游戏二进制布局；
- 修改 MOD 配置覆盖机制，除非其代码依赖被删除的变量字典；
- 为旧版配置或旧版脚本提供迁移工具；
- 重新设计所有补丁 JSON 字段；
- 清理与本次变量和配置重构无关的历史代码。
