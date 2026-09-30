# .tkspatch 外部脚本与补丁外置方案

> 目标：`patches/` 目录是玩家收到的补丁更新唯一来源。修改补丁逻辑或参数时，
> 只分发新的 `.tkspatch` 单文件，不需要重编启动器。

## 现状

`tks_launcher_gui/patches/` 下的 `.tkspatch` 已覆盖全部补丁，包括原先后写在
`core/patch_engine.py` 尾部的运行时补丁：

| 补丁 ID | 类型 | 说明 |
|---|---|---|
| `save_entry_check_fix` | `script` | 存档入口检查 |
| `save_stream_error_fix` | `patch_bytes` | 存档 stream error |
| `archive_portrait` | `cave_hook` | 存档列表队伍头像 |
| `gold_display` | `patch_bytes` | 存档界面金钱显示 |
| `xiaotan_defend_glow` | `patch_extra_section` | 防御误触发发光 |
| `xiaotan_disable_companion` | `script` | 禁用伴随进程 |

## ZIP 容器格式

`.tkspatch` 现在是类似 `.tksmod` 的 ZIP 容器：

```text
save_entry_check_fix.tkspatch
├── patch.json   # 补丁清单，原散装 JSON 的全部字段
└── script.py    # type=script 时内嵌的脚本源码
```

普通数据补丁只包含 `patch.json`；脚本补丁把 `script.py` 一起打包，
因此单个 `.tkspatch` 即可独立分发。

`patches/_variables.tkspatch` 仍保持散装 JSON，它是全局变量文件，
不属于补丁，不参与补丁 ZIP 化。

## 外置脚本补丁

需要在补丁内写条件判断或自定义扫描流程时，使用 `type: "script"`：

```json
{
  "_format": 1,
  "type": "script",
  "id": "example",
  "name": "示例补丁",
  "script_file": "script.py"
}
```

`patch.json` 位于 ZIP 内，`script_file` 指向同 ZIP 内的 `script.py`。
旧版散装 JSON 仍可加载，此时 `script_file` 指向 `patches/_scripts/`。
脚本必须暴露：

```python
def apply(ctx):
    return True
```

`ctx` 提供：

- `defn`：当前 `PatchDef`
- `target_pid`、`h_proc`、`base_addr`、`code_buf`、`code_start_addr`
- `cave_addr`、`warpc_base`、`variables`
- `exe_profile`、`config_overrides`
- `log(message)`：写入启动器日志

脚本可以直接使用 `core.memory`、`core.scanner` 等内置 API。

## cave hook 的 hook_offset

当 `hook_pattern` 比真正写入 hook 的指令长（例如前面带了唯一上下文特征码）时，
用 `hook_offset` 声明 hook 起点相对 pattern 起点的偏移：

```json
{
  "type": "cave_hook",
  "hook_pattern": "0F BE 84 41 9E 02 00 00 66 05 D3 00 50",
  "hook_offset": 8,
  "hook_size": 5
}
```

## 更新流程

1. 解包或编辑 `patches/*.tkspatch`，更新 `patch.json`。
2. 脚本补丁同时更新 ZIP 内的 `script.py`。
3. 重新打包为单个 `.tkspatch`，只分发该文件并覆盖旧文件。
4. 启动器加载时自动发现新补丁，无需重编 GUI/CLI。

`tools/pack_tkspatch.py` 可以把旧版散装 JSON 批量转成 ZIP 型 `.tkspatch`。

构建后的启动器可用以下命令快速验证补丁加载和脚本可执行性（原 CLI 版命令 `TKSLauncherCLI.exe --verify-patches` 已废弃，2026-09-30 起仅 GUI 版提供；GUI 版无控制台窗口，验证输出见日志文件）：

```text
TKSLauncher.exe --verify-patches
```

该模式不启动游戏，只检查 `patches/` 目录下的 ZIP 补丁是否全部可加载、
`script.py` 是否能编译并暴露 `apply(ctx)`。GUI 版无控制台窗口，
验证结果会写入 exe 同目录的 `verify_patches_result.txt`。

## 注意

外部脚本与 `cave_code` 一样属于可执行内容，只会从玩家自己目录中的
`patches/*.tkspatch` ZIP 内加载，且最终由玩家决定是否覆盖。CLI 的 `no_runtime_hooks`、
`no_save_entry_stream_fixes`（旧名 `no_4c33fc_41c120` 仍兼容）、
`no_archive_portrait`、`no_gold_display` 诊断开关仍然有效，
它们通过 `disabled_patches` 在引擎层跳过对应补丁 ID。
