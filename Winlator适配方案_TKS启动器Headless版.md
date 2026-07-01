# Winlator 适配方案：TKS Launcher Headless 版

## 1. 背景

### 1.1 现状

TKS Launcher GUI（`tks_launcher_gui/`）是目前唯一能让手机玩家受益的组件——它负责**启动游戏 + 注入内存补丁 + 合并 MOD**，是玩家在手机上玩 MOD 版游戏的核心工具。

但它无法在 Winlator 上运行，根因分析：

| 层次 | 问题 | 严重度 |
|------|------|--------|
| **GUI 层** | PySide6 依赖 Qt6 C++ DLL（Qt6Core/Gui/Widgets.dll），Wine 对 Qt6 渲染支持极差 | 致命 |
| **逻辑层** | `core/` 全部模块（memory/scanner/patch_engine/mod_loader/warpc_expander/lzss/mod_packer/config_loader）是纯 Python + ctypes，**不依赖 PySide6**，Winlator 中 Wine 对 kernel32/user32 API 都有实现 | 无问题 |
| **打包** | 当前 Nuitka 打包含 PySide6 的完整 exe 达 40-80MB，且运行时依赖 Qt DLL | 致命 |

**结论：问题仅出在 PySide6 GUI 层，核心逻辑层无需改动。**

### 1.2 玩家画像

手机玩家使用 Winlator（Wine on Android）运行 TKS.exe。他们需要：
- 启动游戏时自动应用内存补丁（队伍上限、头像修复、WarPC 扩容等）
- 自动合并 MOD 数据（美化包、功能 MOD）
- 不需要任何界面操作——配置在 PC 上提前做好

### 1.3 目标

构建一个 **Headless（无 GUI）启动器**，去掉 PySide6 依赖，打包为轻量级 exe（预计 5-10MB），可在 Winlator 内直接运行。

---

## 2. 架构设计

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────┐
│                 Winlator (Android)                    │
│                                                       │
│  游戏目录/ (如 D:\sanguo\)                            │
│  ├── TKSLauncherCLI.exe   ← 新建, 5-10MB             │
│  ├── launcher_config.json ← 新建, 配置文件             │
│  ├── tks_patches.json     ← 复用, 补丁定义             │
│  ├── summon_table.json    ← 复用, 召唤表               │
│  ├── mods/                ← 复用, MOD 文件             │
│  ├── TKS.exe              ← 游戏                      │
│  ├── save/                ← 存档                      │
│  └── *.dat                ← 游戏数据文件                │
│                                                       │
│  用户操作:                                             │
│    双击 TKSLauncherCLI.exe → 控制台自动执行 → 启动游戏  │
└─────────────────────────────────────────────────────┘
```

### 2.2 模块复用

```
tks_launcher_gui/core/          → 100% 复用，零修改
├── memory.py                   Win32 API ctypes 封装
├── scanner.py                  PE解析、模式/值扫描、版本指纹
├── config_loader.py            tks_patches.json 解析
├── patch_engine.py             补丁应用引擎 (含全部 x86 cave 模板)
├── warpc_expander.py           WarPC 缓冲区扩展 + .dat 管理
├── mod_loader.py               MOD 扫描/依赖/冲突/合并/回滚
├── mod_packer.py               MOD 打包/拆分 (.tksmod/.tksmodpak)
└── lzss.py                     LZSS 压缩/解压

editor_utils/                   
└── runtime_bootstrap.py        get_app_dir() — 仅用此函数定位exe目录
                                (bootstrap() 在 CLI 模式下不需要,
                                 因为没有 PySide6 .lib 要加载)
```

### 2.3 不复用的模块

| 模块 | 原因 |
|------|------|
| `tks_launcher_gui/ui/` 全部 | PySide6 依赖 |
| `tks_launcher_gui/workers/patcher_worker.py` | QThread + Signal 耦合，逻辑提取到新模块 |
| `tks_launcher_gui/main.py` | QApplication 入口 |
| `editor_utils/theme_manager.py` | QSS 主题 |
| `editor_utils/dock_components.py` | Qt Dock 组件 |
| `editor_utils/window_theme.py` | Windows DWM API |
| `tks_launcher_gui/ui/game_overlay.py` | Qt 悬浮窗 |

---

## 3. 新增文件清单

### 3.1 `tks_launcher_gui/cli_launcher.py` — 核心新文件

Headless 启动器入口，**从 patcher_worker.py 的 `_do_run()` 提取并简化**。

**关键改动（相比 patcher_worker.py）：**

| patcher_worker.py (原始) | cli_launcher.py (新) |
|--------------------------|----------------------|
| 继承 `QThread` | 普通类，无基类 |
| `self.log_emitted.emit(msg)` | `print(msg)` |
| `self.status_changed.emit(...)` | `print(f"[状态] ...")` |
| `self.finished.emit(ok, diag)` | `return ok, diag` |
| `self.game_window_found.emit(hwnd)` | 丢弃（无悬浮窗） |
| `self.overlay_update.emit(...)` | `print(...)` |
| `self.profile_detected.emit(...)` | `print(...)` |
| `self._is_running` 控制 | `_is_running` 保留（用于 Ctrl+C 中断） |

**模块结构：**

```python
# cli_launcher.py

class CliLauncher:
    """Headless 启动器 — 无 PySide6 依赖"""
    
    def __init__(self, config: LaunchConfig):
        # config 包含: exe_path, game_dir, enabled_patches, enabled_mod_ids
        ...
    
    def run(self) -> tuple[bool, dict]:
        """执行完整流程，返回 (success, diagnostics)"""
        # 完全复用 patcher_worker._do_run() 的逻辑
        # 1. 确定 exe 目录（直接 os.path.dirname(sys.argv[0])）
        # 2. 加载 tks_patches.json
        # 3. 存档健康检查
        # 4. MOD 扫描 → 排序 → 合并 → 写入
        # 5. WarPC/DAT 截断
        # 6. subprocess 启动 TKS.exe
        # 7. 检测进程 + 窗口
        # 8. 读取代码段
        # 9. 版本指纹
        # 10. 自动发现 WarPC 基址
        # 11. VirtualAllocEx + 应用全部补丁
        # 12. WarPC 缓冲区扩展
        # 13. 运行时补丁 (4c33fc/41c120/archive_portrait/gold_display)
        # 14. 存档加载 hook
        # 15. 看门狗守护 (等待游戏退出)
        # 16. 恢复 .mod_orig
        ...

def main():
    """CLI 入口：解析参数/配置，创建 CliLauncher，执行"""
    # 1. 解析命令行参数 (--config, --tks-exe, --game-dir 等)
    # 2. 如果没有 --config，自动查找同目录下的 launcher_config.json
    # 3. 创建 LaunchConfig
    # 4. CliLauncher(config).run()
    ...
```

**完整流程（与 patcher_worker._do_run() 一致）：**

```
启动
 ├── 1. 确定 exe 目录 (sys.argv[0])
 ├── 2. 加载 tks_patches.json 配置
 ├── 3. 存档目录健康检查
 ├── 4. MOD 加载流程
 │      ├── scan_mods(mods_dir)
 │      ├── 按 enabled_mod_ids 过滤
 │      ├── expand_pak_mods (展开 .tksmodpak)
 │      ├── resolve_dependencies (拓扑排序)
 │      ├── detect_conflicts
 │      ├── merge_mods
 │      └── apply_mod_data
 ├── 5. WarPC/DAT 预截断 (prepare_warpc_for_game)
 ├── 6. 启动 TKS.exe (subprocess.Popen)
 ├── 7. 查找窗口 / 检测子进程 (加密版兼容)
 ├── 8. 读取 .text 代码段 (ReadProcessMemory)
 ├── 9. EXE 版本指纹识别
 ├── 10. 自动发现 WarPC BSS 基址
 ├── 11. 定位存档加载 Move 调用点
 ├── 12. VirtualAllocEx 分配 WarPC 缓冲区
 ├── 13. 恢复 .dat 原始文件
 ├── 14. VirtualAllocEx 分配 cave 内存 (1024B)
 ├── 15. 应用全部补丁 (apply_config_patches)
 ├── 16. 扩展 WarPC 缓冲区 (expand_warpc_buffer)
 ├── 17. 运行时补丁 (sub_4C33FC/41C120/存档头像/金钱)
 ├── 18. inject_warpc_data
 ├── 19. 安装存档加载 portrait 重注入 hook
 ├── 20. 看门狗等待游戏退出 (含 portrait 哨兵重注入)
 └── 21. 恢复 .mod_orig 备份
```

### 3.2 `tks_launcher_gui/launcher_config.json` — 配置文件（模板）

```json
{
  "_说明": "TKS Launcher CLI 配置文件。在 PC 上编辑好，复制到手机游戏目录。",

  "tks_exe": {
    "_说明": "TKS.exe 路径。相对路径相对于启动器所在目录，也支持绝对路径。",
    "path": "TKS.exe"
  },

  "patches": {
    "_说明": "启用的可选补丁 ID 列表。必选补丁始终启用，无需列出。",
    "_可选补丁说明": {
      "summon_table":    "召唤表自定义 (224~231 召唤角色替换)",
      "gold_30000_fix":  "金钱上限 30000→65535",
      "enter_key_fix":   "禁用背包 ENTER 键 BUG 修复",
      "portrait_watchdog":"存档加载后头像数据自动恢复"
    },
    "enabled": [
      "summon_table",
      "gold_30000_fix",
      "enter_key_fix",
      "portrait_watchdog"
    ]
  },

  "mods": {
    "_说明": "启用的 MOD ID 列表。对应 mods/ 目录下的 .tksmod/.tksmodpak。",
    "_提示": "MOD ID 可在 PC 版 TKS Launcher GUI 中查看。留空则启用全部。",
    "enabled_ids": []
  },

  "game": {
    "_说明": "游戏目录。留空则自动检测（启动器所在目录或 TKS.exe 所在目录）。",
    "dir": ""
  },

  "advanced": {
    "wait_timeout": 30,
    "_说明_wait_timeout": "等待游戏就绪超时(秒)"
  }
}
```

### 3.3 `build/entries/entry_launcher_cli.py` — 构建入口（自动生成）

```python
"""TKS Launcher CLI 入口 — 自动生成"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tks_launcher_gui.cli_launcher import main
main()
```

### 3.4 `build/build_all.py` — 构建脚本修改

在 `EDITORS` 表中新增一项：

```python
("TKSLauncherCLI", "build/entries/entry_launcher_cli.py", "tks_launcher_gui"),
```

构建命令（**不含 PySide6 插件**）：

```python
def _build_cli_cmd(name: str, entry: str, editor_dir: str) -> list:
    """CLI 启动器专用: 无 PySide6, 无 Qt, 极简 exe"""
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--output-dir={DIST_DIR}",
        f"--output-filename={name}.exe",
        "--windows-console-mode=force",     # CLI 需要控制台
        f"--windows-icon-from-ico={icon_path}",

        # 不启用 PySide6 插件 —— 核心区别！
        
        # 排除所有 GUI 框架
        "--nofollow-import-to=PySide6",
        "--nofollow-import-to=shiboken6",
        "--nofollow-import-to=PIL",
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=PyQt5",
        "--nofollow-import-to=PyQt6",

        # 禁用 PySide6 插件的隐式导入检测
        "--no-deployment-flag=excluded-module-usage",

        # 包含 core 包 (编译器不会自动发现, 需显式包含)
        "--include-package=tks_launcher_gui.core",

        # 包含数据文件
        f"--include-data-files={仓库根目录 / 'tks_launcher_gui' / 'tks_patches.json'}=tks_patches.json",
        f"--include-data-files={仓库根目录 / 'tks_launcher_gui' / 'summon_table.json'}=summon_table.json",

        # 优化
        "--lto=yes",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--remove-output",

        str(entry_path),
    ]
    return cmd
```

**预计输出大小：5-10 MB**（仅标准库 + core 模块，无 Qt DLL）

### 3.5 `build/gen_entries.py` — 入口生成器修改

在 `EDITORS` 列表新增：

```python
("entry_launcher_cli.py", "tks_launcher_gui.cli_launcher"),
```

---

## 4. 目录发现与文件定位逻辑

CLI exe 运行时需要定位以下文件。定位策略：

```
exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

优先级:
1. 先在 exe_dir 下找（exe 所在目录）
2. 若找不到，在 os.getcwd() 下找（当前工作目录）

具体文件:
  tks_patches.json   → exe_dir 或 cwd
  summon_table.json  → exe_dir 或 cwd
  launcher_config.json → exe_dir 或 cwd (可选)
  mods/              → exe_dir/mods/ 或 cwd/mods/
  TKS.exe            → 先从 launcher_config.json 读取路径,
                       若未配置则 exe_dir/TKS.exe 或 cwd/TKS.exe
```

这确保了以下两种部署方式都能工作：
- **方式一**：CLI exe 放在游戏目录（和 TKS.exe 同级）
- **方式二**：CLI exe 放在独立目录，通过配置指向游戏目录

---

## 5. 用户使用流程

### 5.1 PC 端准备（一次性）

1. 在 PC 上使用 **TKS Launcher GUI** 配置好补丁和 MOD
2. 编辑 `launcher_config.json` 确认启用的补丁和 MOD
3. 准备好 `mods/` 目录

### 5.2 部署到手机

1. 将以下文件复制到 Winlator 容器中的游戏目录：
   - `TKSLauncherCLI.exe`
   - `launcher_config.json`
   - `tks_patches.json`
   - `summon_table.json`
   - `mods/` 目录（含所需的 .tksmod/.tksmodpak）

2. 确保 TKS.exe 在相同目录（或通过 launcher_config.json 指定路径）

### 5.3 手机上运行

1. 在 Winlator 中，**先运行 TKSLauncherCLI.exe**
2. 控制台窗口出现，显示补丁注入日志
3. 启动器自动启动 TKS.exe
4. 游戏运行期间，启动器保持在后台守护（看门狗）
5. 游戏退出后，启动器自动恢复原始文件并退出

**模板目录结构（部署后）：**

```
Winlator 容器 D:\sanguo\
├── TKSLauncherCLI.exe       ← 双击运行这个
├── launcher_config.json
├── tks_patches.json
├── summon_table.json
├── mods\
│   ├── 子青美化包.tksmodpak
│   └── [地图]剑庐地图.tksmod
├── TKS.exe                  ← 游戏主程序
├── save\                    ← 存档目录
├── WarPC.dat
├── TKItem.dat
├── TKSkill.dat
├── TKMat.dat
├── TKKon.dat
├── TKShop.dat
└── ...其他游戏文件
```

### 5.4 命令行参数

```
TKSLauncherCLI.exe --help

参数:
  --config PATH      指定配置文件路径 (默认: exe同目录/launcher_config.json)
  --tks-exe PATH     指定 TKS.exe 路径 (覆盖配置文件)
  --game-dir PATH    指定游戏目录 (覆盖配置文件)
  --no-mods          跳过 MOD 加载
  --timeout N        等待超时秒数 (默认 30)
```

所有参数都有合理默认值，**零参数也能直接运行**。

---

## 6. 构建集成

### 6.1 独立构建命令

```bash
# 仅构建 CLI 启动器
python build/build_all.py --only TKSLauncherCLI

# 构建全部 + CLI 启动器 (现有 --onefile 模式不含 Qt 排除, CLI 需要独立处理)
python build/build_all.py --cli
```

### 6.2 默认构建行为

将 `TKSLauncherCLI` 加入默认构建目标，与现有 15 个编辑器一起构建。

### 6.3 发行目录

```
dist/TKSEditors/
├── TKSLauncherCLI.exe       ← 新增 (~8MB)
├── launcher_config.json     ← 新增 (模板)
├── tks_patches.json         ← 已有
├── summon_table.json        ← 已有 (需确认当前是否复制)
├── mods/                    ← 已有
├── configs/                 ← 已有
├── TKSItemEditor.exe        ← 已有
├── TKSLauncher.exe          ← 已有 (GUI版)
└── ...                      ← 其他编辑器
```

注意：`assemble_release()` 当前已复制 `tks_patches.json`，需新增复制 `launcher_config.json`（模板）和 `summon_table.json`。

---

## 7. 风险与注意事项

### 7.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| Winlator 中 ctypes 调用 Win32 API 失败 | 中 | Wine 已完整实现 kernel32/user32 的 `OpenProcess`/`WriteProcessMemory`/`VirtualAllocEx` 等 API。若仍有问题，可在真机上调试后针对性适配 |
| Nuitka 编译后 core 模块导入失败 | 低 | `--include-package=tks_launcher_gui.core` 显式包含，且 core 模块间使用相对导入 `.memory` 等，编译后路径不变 |
| Winlator 不支持控制台窗口 | 低 | Winlator 通常支持控制台程序。备选方案：将日志输出到文件 |
| TKS.exe 路径在不同 Winlator 容器中不同 | 低 | 通过 launcher_config.json 可配置 |

### 7.2 设计约束

- **config_loader.py** 中 `json_file` 的相对路径解析依赖 `tks_patches.json` 所在目录。CLI 模式下 `tks_patches.json` 在 exe 同目录，需确认 `summon_table.json` 也被正确找到
- **mod_loader.py** 的 `game_dir` 参数在 CLI 模式下默认为 TKS.exe 同目录，与 GUI 模式一致
- **lzss.py** 沿用现有实现，不做修改

### 7.3 不可控因素

- **Winlator 版本差异**：不同版本的 Winlator 对 Wine 的实现程度不同，可能在旧版上部分 API 不可用
- **Android 权限限制**：Winlator 容器内的 Wine 进程可能受到 Android 进程管理策略影响（如后台进程被杀）
- **真机测试需求**：开发完成后需要在真实 Android 设备 + Winlator 上测试，PC 上的 Wine 测试只能作为参考

---

## 8. 实施清单

| # | 任务 | 文件 | 预计改动量 |
|---|------|------|-----------|
| 1 | 新建 Headless 启动器 | `tks_launcher_gui/cli_launcher.py` | ~300 行（从 patcher_worker.py 提取） |
| 2 | 新建配置模板 | `tks_launcher_gui/launcher_config.json` | ~30 行 |
| 3 | 新建构建入口 | `build/entries/entry_launcher_cli.py` | 自动生成 |
| 4 | 注册到入口生成器 | `build/gen_entries.py` | +1 行 |
| 5 | 注册到构建脚本 | `build/build_all.py` | ~40 行（新 build 函数 + EDITORS 条目） |
| 6 | 复制配置到发行目录 | `build/build_all.py` assemble_release() | +5 行 |
| 7 | 真机测试 | Winlator + 真机 | 验证完整流程 |

---

## 9. 与 PC 版 GUI 的关系

```
PC 端                              手机端
┌──────────────────────┐          ┌──────────────────────────┐
│ TKSLauncher.exe (GUI) │          │ TKSLauncherCLI.exe        │
│ ├── 补丁可视化勾选     │          │ ├── 读取配置 (自动应用)     │
│ ├── MOD 列表管理       │  配置导出  │ ├── 启动 TKS.exe           │
│ ├── MOD 打包/拆分      │ ───────→ │ ├── 注入补丁               │
│ ├── 日志终端           │  手动复制  │ ├── 合并 MOD               │
│ └── 游戏悬浮窗         │          │ └── 看门狗守护             │
└──────────────────────┘          └──────────────────────────┘
```

两个版本共存，各有分工：
- **GUI 版**：PC 玩家使用，提供完整的可视化管理和调试能力
- **CLI 版**：手机玩家使用，PC 上配置好，手机上自动执行
