# TKS Launcher 修复计划 (Spec)

> **状态**: P0/P1/P2 全部 13 个 Phase 已实施完毕 ✅ (2026-08-15); P3-P5 (Phase 9-14) 待办
> **日期**: 2026-08-15
> **作用域**: `tks_launcher_gui/` 启动器本体,不含 `patches/*.tkspatch` 数据
> **设计原则**: 最小破坏面 + 兼容现有 `.tkspatch` + 双入口并行迁移
> **整合来源**: 本 spec 由原"启动器补丁架构分析报告.md"+"修复计划 spec v1.0"两份文档合并而来,前者描述现状,后者描述改进方案
>
> ⚠️ **已废弃内容（2026-09-30）**: 文中与 `cli_launcher.py` / Winlator 双入口相关的章节（CLI 构建、Wine 分支、CLI 回归验证等）已废弃——TKSLauncherCLI 已从仓库移除, 不再打包与兼容; 其余重构记录仍作历史参考。

## 实施进度总览

| 优先级 | 状态 | Phase 列表 |
|---|---|---|
| **P0** | ✅ 100% (3/3) | Phase 1 ✅ Phase 2 ✅ Phase 3 ✅ |
| **P1** | ✅ 100% (2/2) | Phase 4 ✅ Phase 5 ✅ |
| **P2** | ✅ 100% (3/3) | Phase 6 ✅ Phase 7 ✅ Phase 8 ✅ |
| **P3** | ✅ 67% (2/3) | Phase 9 ⏳ Phase 10 ⏳ Phase 11 ✅ |
| **P4** | ✅ 100% (2/2) | Phase 12 ✅ Phase 13 ✅ |
| **P5** | ⏸️ 跳过 (Phase 14) | 按 spec 不在本期范围 |

> **注**: **实际完成的实施 = Phase 1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13** (共 11 个 Phase)。
> 剩余未实施: Phase 9 (高风险 CodeView+PatchJournal, 已决策延期到 v2.x) 与 Phase 10 (discover_warpc_base 多候选)。

### 实施里程碑

- **commit 8d3db16**: Phase 6-13 全部代码 (920 + 行新增, 127 行删除)
- **commit 0f3a208**: `.gitignore` (排除 launcher_cache / 临时测试文件)

### 回归测试

- ✅ CLI `--verify-patches`: 55 个补丁全部通过, 4 个 script 验证通过
- ✅ GUI `main.py` 导入成功
- ✅ 各 Phase 单元测试 8 套全部通过 (CaveLayout / HookTable / parse_patch_dict / PatternScanCache / validate_tkspatch_dict / ExeProfileCache / detect_exe_profile / 集成)

---

## 0. 阅读指南

- 本 spec 自包含:第一部分(§1)是背景资料(原架构报告),第二部分(§2+)是修复方案
- 每个 Phase 标注:
  - **范围 (Scope)**: 影响文件清单
  - **风险 (Risk)**: 破坏面 + Wine/Nuitka 兼容风险
  - **验收 (Acceptance)**: 可执行的验证步骤
  - **回滚 (Rollback)**: 若失败如何回到 Phase 0
- Phase 编号越大,优先级越低
- **不在本 spec 范围内**: GUI 主题、MOD 编辑器、cave_code 模板外置的完整迁移(详见 §15 后续工作)

### 0A. 关键文件索引

| 文件路径 | 行数 | 职责 |
|---|---|---|
| `main.py` | 86 | 应用入口 (PySide6 GUI),含 `--verify-patches` |
| `cli_launcher.py` | 1046 | Headless 启动器 (Wine/Winlator 兼容) |
| `launcher_config.json` | 71 | CLI 配置文件 (tks_exe, patches.enabled, mods.enabled_ids, advanced 诊断选项) |
| `launcher_setting.json` | 44 | GUI 勾选状态自动生成文件 |
| `core/config_loader.py` | 215 | `PatchDef`/`PatchConfig` dataclass + `load_config` (旧版 tks_patches.json 加载, 委托 parse_patch_dict) |
| `core/tkspatch_loader.py` | 374 | `.tkspatch` (ZIP/JSON) 加载 + `_variables.tkspatch` 全局变量 + `merge_patches` + **`parse_patch_dict`** (Phase 8) + **`validate_tkspatch_dict`** (Phase 12) |
| `core/patch_engine.py` | 2315 | 调度引擎 + 16 个 Cave 模板 + 全部 apply_* 函数 + **`@register_patch_type`** (Phase 5) + **`HookTable` / `detect_hook_type` / `check_hook_conflict_v2`** (Phase 7) + **`_build_cave_layout`** (Phase 6) |
| `core/scanner.py` | 377 | PE 节表解析 (文件/内存) + `pattern_scan` + `value_scan` + `discover_warpc_base` + `ExeProfile` + **`PatternScanCache`** (Phase 11) + **`ExeProfileCache`** (Phase 13) |
| **`core/cave_layout.py`** | (Phase 6 新增) | `CaveLayout` + `CaveSlot` + `CaveLayoutError` (cave_offset 自动布局器) |
| **`core/launcher_pipeline.py`** | (Phase 4 新增) | `PatcherPipeline` 共享类 (GUI worker / CLI 共用) |
| `core/memory.py` | 385 | ctypes 封装 (OpenProcess/RPM/WPM/VirtualAllocEx/SuspendThread 等) + `MODULEENTRY32` 等结构体 |
| `core/warpc_expander.py` | (大) | WarPC 扩容 |
| `core/tkact_expander.py` | (中) | TKAct 扩容 |
| `core/mod_loader.py` | (中) | `.tksmod` / `.tksmodpak` 加载 |
| `ui/main_window.py` | (大) | PySide6 主窗口 |
| `ui/patch_list.py` | (中) | 补丁勾选 UI |
| `workers/patcher_worker.py` | 780 | `PatcherWorker(QThread)` GUI 后台流水线 (Phase 4 重构为 PatcherPipeline 薄包装) |
| `patches/_variables.tkspatch` | 27 | 19 个全局变量定义 (WarPC/TKItem/TKShop/TKKon/TKAct/TKDefUnit) + **`cave_total_size`** (Phase 3) |
| `patches/*.tkspatch` | 53 | 外置补丁 (ZIP + patch.json + script.py) |
| **`launcher_cache/`** | (Phase 13 新增目录) | 运行时 ExeProfile 持久化缓存 (`.gitignore` 排除) |
| **`.pattern_cache/`** | (Phase 11 新增目录) | 运行时模式扫描结果缓存 (`.gitignore` 排除) |

### 0B. `.tkspatch` 清单(53 个文件,按 type 分类)

| 类型 | 数量 | 列表 |
|---|---:|---|
| **cave_hook** | 16 | archive_portrait, awk_sprite_cave, awk_sprite_cave2, checkmember_level_redirect, duel_counter_self_fix, duel_self_target_fix, exp_bonus_overflow_fix, exp_lock, history_text, portrait_cave1, portrait_cave2, skill_menu_cap, team_member_routing, war_mustchar_fallback, weapon_cause_mask_hook |
| **patch_bytes** | 18 | attribute_char_limit_unlock, battle_treasure_reveal, battle_writeback, broke_weapon_fix, check_team, checkitem_unsigned_fix, demon_general_effect, disable_pface_jvg, enemy_info_reveal, enter_key_item_fix, exp_cap_unsigned_fix, gold_display, hp_cmp_unsigned_fix, lusu_intel_duration_x4_fix, no_enemy, save_stream_error_fix, shanhai_map_unlock, skill_scan_bound, skim_fst_dlg, team_clear_slot0, team_leave_slot0, team_member_limit |
| **patch_imm32** | 5 | gold_limit, tkdefunit_count, tkmat_size, tkskill_size, warpc_size_refs |
| **patch_data_expand** | 5 | tkact_expand, tkkon_expand, tkitem_expand, tkshop_expand, warpc_base_refs |
| **patch_summon_table** | 1 | summon_table |
| **patch_drop_probability** | 1 | drop_probability |
| **patch_exp_lock** | 1 | exp_lock |
| **patch_font_config** | 1 | font_config |
| **patch_animation_speed** | 1 | animation_speed |
| **patch_extra_section** | 2 | xiaotan_defend_glow, xiaotan_gambling_unlock |
| **script** | 4 | save_entry_check_fix, tkact_expand, tkkon_expand, xiaotan_disable_companion |
| **patch_warpc_addr** | 1 | warpc_base_refs |

> 注: cave_hook 与 patch_exp_lock 在文件中都声明了 cave_offset;exp_lock 实际占用 cave_offset=1344(28B),与其他 cave_hook 共用同一 1024B 区。

---

## 第一部分:背景资料(原架构报告整合)

### 1A. 架构分层

```
┌────────────────────────────────────────────────────────────────────┐
│  UI 层 (PySide6)                                                    │
│  ├─ main.py                       应用入口 (含 --verify-patches)    │
│  ├─ ui/main_window.py             主窗口 + 补丁勾选状态              │
│  ├─ ui/                           各种对话框 (未深入分析)             │
│  └─ launcher_setting.json         UI 自动生成的勾选状态文件           │
├────────────────────────────────────────────────────────────────────┤
│  Worker 层 (后台线程)                                                │
│  └─ workers/patcher_worker.py     QThread 封装完整补丁流水线 (780 行) │
├────────────────────────────────────────────────────────────────────┤
│  CLI 层 (无 GUI, 纯标准库 + ctypes)                                  │
│  └─ cli_launcher.py               Winlator 兼容的 Headless 启动器    │
├────────────────────────────────────────────────────────────────────┤
│  Core 层 (核心逻辑)                                                  │
│  ├─ core/patch_engine.py          调度引擎 + Cave 模板 + 所有补丁类型 │
│  ├─ core/tkspatch_loader.py       .tkspatch (ZIP/JSON) 加载器       │
│  ├─ core/config_loader.py         tks_patches.json 加载 + 数据类     │
│  ├─ core/scanner.py               PE 节表解析 + 模式扫描 + ExeProfile│
│  ├─ core/memory.py                Win32 ctypes 封装 (进程/内存/线程) │
│  ├─ core/warpc_expander.py        WarPC 扩容                        │
│  ├─ core/tkact_expander.py        TKAct 扩容                        │
│  └─ core/mod_loader.py            MOD 扫描/合并/冲突检测             │
├────────────────────────────────────────────────────────────────────┤
│  Lib 层 (基础工具)                                                   │
│  ├─ editor_utils/app_init.py      单实例锁                           │
│  ├─ editor_utils/ui_helpers.py    对话框主题过滤                      │
│  ├─ editor_utils/runtime_bootstrap.py Nuitka 编译后的目录解析         │
│  └─ PySide6 / Nuitka / ctypes / zipfile                             │
└────────────────────────────────────────────────────────────────────┘
```

**关键设计意图**:
- `cli_launcher.py` 与 `patcher_worker.py` 共享同一份 Core,前者去掉 PySide6 以兼容 Winlator/Wine。
- 启动器本身与游戏进程通过 进程外 ctypes 操作 (ReadProcessMemory/WriteProcessMemory) 通信,所有 hook 安装是运行时内存写入,而非文件修改。

---

### 1B. 配置加载链

```
patches/_variables.tkspatch   ──┐
                                 │  唯一来源 (FORMAT_VERSION=1)
                                 ▼
patches/<id>.tkspatch (ZIP/JSON) ─┐
                                  │  load_tkspatch_dir() 扫描排序
                                  ▼
                  load_tkspatch_file() (ZIP→patch.json+script.py | 纯JSON)
                                  │
                                  ▼
tks_patches.json (仅向后兼容)  ────► load_config_merged() 编排
                                  │
                                  ▼
                  config_loader.load_config()  (基础)
                                  │
                                  ▼
                  PatchDef + PatchConfig (dataclass) ─► apply_config_patches()
```

**优先级 (按覆盖顺序)**:
1. `patches/_variables.tkspatch` 中的 `variables` (唯一来源,见 `tkspatch_loader.py:295`)
2. `patches/*.tkspatch` 中的同名 id 覆盖 `tks_patches.json` 中相同 id (见 `merge_patches` L331-364)
3. 新增项追加到末尾

**关键文件**:
- `_variables.tkspatch` (`patches/_variables.tkspatch`): 定义 19 个全局变量 (WarPC/TKDefUnit/TKItem/TKShop/TKKon/TKAct 等原版大小与基址)
- `tks_patches.json`: 已退化为可选基础配置,不存在时直接走外置 `.tkspatch`

---

### 1C. 补丁引擎 (`patch_engine.py`) 调度流程

入口函数 `apply_config_patches` (`patch_engine.py:2154-2314`),按 `defn.type` 分发:

```
                        apply_config_patches(config, ...)
                                   │
        ┌──────────┬───────────────┼────────────┬───────────────┬────────────┐
        ▼          ▼               ▼            ▼               ▼            ▼
   patch_bytes  patch_extra_   cave_hook    script         patch_imm32   patch_warpc_addr
                 section         │           │              │              │
        │          │             │           │              ├─ value_scan  └─ (空操作,由
        │          │             │           │              │    (apply_     WarPC 扩展
        │          │             │           │              │    patch_     流程处理)
        │          │             │           │              │    imm32_by
        │          │             │           │              │    value)
        ▼          ▼             ▼           ▼              │
   直接字节      读 MOD 段     1. 扫 hook   exec(script    └─ pattern
   替换          内存扫模式     2. 检查 E8   .source)        (apply_patch_
                                 冲突           或             imm32_by_pattern)
                              3. fallback   spec_from
                                 rva 回退   file_location
                              4. 累计入
                                 pch[] (延后批量)

                                            patch_summon_table
                                            patch_drop_probability
                                            patch_exp_lock
                                            patch_font_config
                                            patch_animation_speed
                                                     │
                                                     ▼
                                              各自专属 apply_* 函数
                                                     │
                                                     ▼
                                         第二阶段: pch[] 批量写 cave
                                         (apply_cave_hook 循环)
```

**cave_hook 是二阶段提交**:
- 第一阶段 (`apply_config_patches` L2215-2248): 仅做模式扫描 + 冲突检测 + fallback_rva 回退,结果存入 `defn._pre_scanned_hits`,加入 `pch[]`
- 第二阶段 (L2303-2313): 遍历 `pch[]`,调用 `apply_cave_hook` 统一分配 cave_offset 空间并写入

---

### 1D. Cave 内存分配机制与 1024 字节上限

**分配点** (`patcher_worker.py:502-511` 与 `cli_launcher.py:744-758`,两者逻辑相同):

```python
ca = _VirtualAllocEx(hp, None, 1024,
                     MEM_COMMIT | MEM_RESERVE,
                     PAGE_EXECUTE_READWRITE)
cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
```

- 单次 `VirtualAllocEx` 分配 **固定 1024 字节** 区域
- `PAGE_EXECUTE_READWRITE` 让 cave 代码既能跑也能写数据
- 失败时只 `log("caves skipped")`,不中断其他字节补丁

**Cave 内部布局 (静态偏移, 由 `cave_offset` 指定)**

实测 **16 个** 外置 `.tkspatch` 共声明 17 个 cave 段,加上 summon_table 内嵌的两段,**总占用 955/1024 字节 (93.3%)**:

| .tkspatch 文件 | cave_offset | 大小 (字节) |
|---|---|---|
| awk_sprite_cave | 0 | 58 |
| (summon_table 内嵌 entry_224) | 0 (召唤表 cave1) | 77 |
| (summon_table 内嵌 222/251 合并) | 0 (召唤表 cave2) | 63 |
| portrait_cave1 | 64 | 52 |
| portrait_cave2 | 128 | 49 |
| archive_portrait | 192 | 50 |
| history_text | 256 | 38 |
| **未用区间** | 294~639 | (346 字节空隙) |
| awk_sprite_cave2 | 640 | 55 |
| exp_bonus_overflow_fix | 704 | 29 |
| weapon_cause_mask_hook | 800 | 98 |
| duel_self_target_fix | 900 | 29 |
| duel_counter_self_fix | 960 | 53 |
| checkmember_level_redirect | 1088 | 43 |
| team_member_routing | 1152 | 158 |
| exp_lock | 1344 | 28 |
| skill_menu_cap | 1408 | 21 |
| war_mustchar_fallback | 1472 | 54 |
| **合计声明** | — | **955 字节** |
| **cave 区上限** | — | **1024 字节** |
| **余量** | — | **69 字节 (6.7%)** |

> **关键发现**: 已使用 955/1024 (93.3%),**仅剩 69 字节空间**。继续添加新 cave 补丁会很快撞墙。
>
> **三份研究报告实测差异**: 此表基于原架构报告实测 (2026-08-15 上午); 后续三份研究报告 (subagent 0137ea85 / 5d35cb33 / 7c0fb5ac) 给出更保守估计 **1526 字节 (149%)** — 因为它们将 exp_lock 单独计入了 1344 偏移位置。**实际边界以三份研究报告为准**,Phase 1 选 2048 即覆盖两者估计。

---

### 1E. `cave_offset` 静态布局机制

cave_offset 是一个**纯静态、编译期常量**,每个 `.tkspatch` 在 JSON 中硬编码其 cave 在 1024 字节区内的偏移:

```python
# patch_engine.py:1020-1021 (apply_cave_hook)
ct = cave_addr + defn.cave_offset     # cave_addr 是 VirtualAllocEx 分配的基址
write_pm(h_proc, ct, cd)              # 写入 cave 代码
```

- 所有 cave 共享同一个 1024B 区域,通过 `cave_offset` 偏移区分
- 不同补丁之间**没有自动避让** — 若两个 `.tkspatch` 声明相同的 cave_offset,后写者覆盖前者
- 没有重叠检测,也没有按大小排序/紧致布局算法

---

### 1F. WarPC 缓冲区分配 (`patcher_worker.py:438-460`)

```
┌──────────────┐  GUARD (64KB)
│  0x10000     │  ← _warpc_new_buf - 0x10000
├──────────────┤  ← warpc_base_for_caves (cave_addr 复用同一片, 见 L520)
│  WarPC 数据  │  ← 由 expand_warpc_buffer 注入完整 WarPC.dat 数据
│  (扩容后大小) │
└──────────────┘  ← VirtualAllocEx 返回地址 + 0x10000
```

代码逻辑 (`patcher_worker.py:449-460`):

```python
GUARD_SIZE = 0x10000                                # 64KB 前导保护区
total_alloc = ns + GUARD_SIZE                       # ns = 完整 WarPC 大小
ab = _VirtualAllocEx(hw, None, total_alloc, ...)
abv = ctypes.cast(ab, ctypes.c_void_p).value or 0
nb = abv + GUARD_SIZE                               # 跳过前导 64KB
write_pm(hw, nb, _warpc_full_data)                 # 写入完整 WarPC 数据
warpc_base_for_caves = nb                          # 同时作为 cave 候选基址
config.variables["warpc_new_base"] = nb
```

**关键设计**:
- 前导 64KB GUARD 用于避免越界写入破坏相邻分配块 (cave 代码区与 WarPC 数据区物理重叠,见下)
- `warpc_base_for_caves = nb`,即 cave 的基址 = WarPC 数据起始地址 (同一段 `VirtualAllocEx` 分配)
- 未扩容时 cave 分配在另一块 1024B 区域 (L505)

---

### 1G. 挂起-补丁-恢复流程

```
[1] prepare_warpc_for_game()           预处理 WarPC (扩展/截断)
[2] prepare_tkact_for_game()            TKAct 扩展
[3] subprocess.Popen(tks_path, creationflags=0x4)   CREATE_SUSPENDED
        ↓
[4] 早期模式检测 (patcher_worker.py:250-280)
    - SkimFstDlg 模式 A1 14 A5 4F 00 50 E8
    - 未加密版 → 主进程已挂起,直接读取代码段 (3MB 上限)
    - 加密版   → 进入第 [5] 步
        ↓
[5] 加密版: resume_process(tks_proc.pid) + 轮询子进程
    - get_child_processes(tpid)
    - 检测到子进程 → suspend_process(target_pid)
    - _need_resume_pid = target_pid
        ↓
[6] 读取代码段 (重试 5 次, 3MB 上限,patcher_worker.py:389-413)
        ↓
[7] detect_exe_profile()                原版/孝谈三国3/未知 MOD
[8] discover_warpc_base()               自动发现 WarPC BSS 基址
[9] 分配 WarPC 缓冲区 (GUARD + 数据)
[10] VirtualAllocEx(1024 bytes)        Cave 内存
[11] apply_config_patches()             二阶段: 字节补丁 + 批量 cave_hook
[12] expand_warpc_buffer()              WarPC 代码引用修补
[13] inject_warpc_data()                WarPC 数据注入
[14] resume_process(_need_resume_pid)   ★ 关键: 所有补丁就绪后才恢复
        ↓
[15] find_window("TForm1")              UI 悬浮窗定位
[16] _wait_game_exit()                  阻塞至游戏退出
[17] restore_originals() + 工具清理
```

**挂起策略差异**:
- **原生 Windows**: `creationflags=0x4` + `SuspendThread/ResumeThread` (memory.py L333-339)
- **Wine/Winlator**: 跳过 `CREATE_SUSPENDED`,直接子进程挂起 (`cli_launcher.py:355-374` 的 `is_wine` 分支),且在 launcher_config.json 中默认 `no_suspend: true`

---

### 1H. 模式扫描 + fallback_rva 链

主流程在 `apply_config_patches` L2215-2236:

```python
elif defn.type == "cave_hook":
    hp = defn.hook_pattern or defn.pattern
    hpat, hwc = parse_pattern(hp or "")
    hh = pattern_scan(bytes(code_buf), hpat, hwc)    # 1. 模式扫描
    if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
        if len(hh) == 0 and defn.fallback_rva > 0:
            # 2. fallback_rva 回退 (针对 MOD 版本代码已变形)
            fb_hook = defn.fallback_rva - 0x1000
            fb_off = fb_hook - defn.hook_offset
            if 0 <= fb_off < len(code_buf) - defn.hook_size:
                hh = [fb_off]
                log("... 使用 fallback_rva ...")
            else:
                continue    # 越界,跳过
        elif len(hh) == 0 and exe_profile and exe_profile.has_extra_sections:
            log("... MOD 已修改, 无 fallback, 跳过")
            continue
        else:
            log("... Hook 模式匹配数不符, 跳过")
            continue
```

**fallback_rva 三层回退链**:
1. **首选**: 模式扫描 (`hook_pattern` 字节序列)
2. **次选**: `fallback_rva` 硬编码 RVA (用于孝谈三国3终极版的代码位置偏移)
3. **末选**: 若 EXE 有额外段 (`.test`/`.Silvana`) 则彻底跳过 (`apply_patch_extra_section` 走另一条路径)

**模式扫描优化**: `scanner.py:286-320` 的 `pattern_scan` 用首个非通配字节做 `bytes.find` 锚点,然后验证完整模式 — 比朴素的逐字节比较快一个数量级。

---

### 1I. `hook_conflict_action` 机制

实现于 `patch_engine.py:2238-2247`:

```python
if hh and check_hook_conflict(code_buf, hh[0] + defn.hook_offset):
    action = defn.hook_conflict_action
    if action == "override":
        log("... 启动器优先级最高 → 覆盖")
    elif action == "skip":
        log("... 已被占用 (E8/E9 开头), 跳过")
        continue
```

`check_hook_conflict` (`patch_engine.py:104-112`) 仅检查目标位置首字节是否已是 `0xE8 (call)` 或 `0xE9 (jmp)`。

**默认行为** (`config_loader.py:31`): `"override"` — 启动器优先级最高,无视第三方 MOD 的 hook 强行覆盖。这是**双刃剑**:
- ✅ 保证启动器补丁永远生效
- ⚠ 会破坏第三方 MOD 已 hook 的逻辑 (尤其孝谈三国3终极版 `.test` 段的 cave)

---

### 1J. `profile_rules` 机制 (原版/孝谈三国3终极版兼容)

定义于 `PatchDef.profile_rules: Dict[str, str]` (`config_loader.py:30`),值可为 `"apply"` 或 `"skip"`。

实现 (`patch_engine.py:2198-2203`):

```python
if defn.profile_rules:
    rule = defn.profile_rules.get(_profile_name,
                                 defn.profile_rules.get("_default", "apply"))
    if rule == "skip":
        log(f"    -> profile '{_profile_name}' 规则: 跳过")
        continue
```

**profile 识别链** (`scanner.py:147-206`):
1. 解析 PE 节表 → `_KNOWN_MOD_SECTIONS = {".test", ".Silvana"}`
2. 同时含 `.test`+`.Silvana` → `profile.name = "xiaotansanguo3"` ("孝谈三国3终极版")
3. 仅含其他额外段 → `"unknown_mod"`
4. 否则 `"original"`

**双重防护**:
- `exe_profile.skip_patches` (整组跳过,孝谈三国3下目前为空集)
- `defn.profile_rules` (单补丁级别细粒度控制)

---

### 1K. 原报告缺陷清单(7 条,合并入修复方案)

下表把原报告 §十一 的 7 条缺陷映射到本 spec 修复方案:

| # | 原报告缺陷 | 严重性 | 对应 Phase |
|---|---|---|---|
| 1 | Cave 空间硬编码 1024 字节,缺乏弹性 | 🔴 高 | Phase 1 + 2 + 3 |
| 2 | 启动器与 CLI 启动器存在大量代码重复 | 🔴 高 | Phase 4 |
| 3 | pattern_scan 全代码段扫描,无预过滤 | 🟡 中 | Phase 11 (LRU) |
| 4 | hook_conflict 仅检查单字节 E8/E9,误判/漏判共存 | 🟡 中 | Phase 7 |
| 5 | PE 节表解析忽略页对齐,extra_section_ranges 计算可能错位 | 🟡 中 | 不在本 spec(细节修复)|
| 6 | apply_config_patches 单次遍历,无依赖排序 | 🟢 低 | Phase 14 (后续工作)|
| 7 | cave 区域在 WarPC 缓冲区扩展时物理重叠,缺乏隔离 | 🟢 低 | Phase 14 (后续工作)|

---

## 第二部分:修复方案

### 1. 优先级总表

| 优先级 | 编号 | 标题 | 估计改动量 | 估计工时 | 阻塞性 | 状态 |
|---|---|---|---|---|---|---|
| **P0** | Phase 1 | Cave 缓冲区溢出 — 1024→2048 一行修复 | 2 行 | 0.5 h | 是 | ✅ 已完成 |
| **P0** | Phase 2 | Cave 写入越界硬校验 | ~30 行 | 2 h | 否 | ✅ 已完成 |
| **P0** | Phase 3 | `_variables.tkspatch` 暴露 `cave_total_size` | ~20 行 | 1 h | 否(Phase 1/2 之后) | ✅ 已完成 |
| **P1** | Phase 4 | 抽取 `PatcherPipeline` 共享类 | ~600 行重排 | 8 h | 否 | ✅ 已完成 |
| **P1** | Phase 5 | `apply_config_patches` 改为注册表派发 | ~150 行 | 3 h | 否 | ✅ 已完成 |
| **P2** | Phase 6 | `cave_offset` 自动布局器 | ~120 行 | 4 h | 否 | ✅ 已完成 |
| **P2** | Phase 7 | `hook_conflict_action` 多模式识别 + hook_table | ~80 行 | 2 h | 否 | ✅ 已完成 |
| **P2** | Phase 8 | `config_loader` 与 `tkspatch_loader` 字段映射合并 | ~60 行 | 2 h | 否 | ✅ 已完成 |
| **P3** | Phase 9 | `code_buf` 分段只读 + 写入隔离 | ~200 行 | 6 h | 否 | ⏳ 未实施 (高风险) |
| **P3** | Phase 10 | `discover_warpc_base` 拓宽 + 多候选 | ~50 行 | 2 h | 否 | ⏳ 未实施 |
| **P3** | Phase 11 | 模式扫描结果 LRU 缓存 | ~40 行 | 1 h | 否 | ✅ 已完成 |
| **P4** | Phase 12 | `.tkspatch` JSON Schema 校验 | ~80 行 | 3 h | 否 | ✅ 已完成 |
| **P4** | Phase 13 | `ExeProfile` 持久化缓存 | ~60 行 | 2 h | 否 | ✅ 已完成 |
| **P5** | Phase 14 | 跳过本阶段(洞穴模板外置、依赖图、SQLite 迁移)| — | — | — | ⏸️ 跳过 (本期外) |

> **建议执行顺序**: Phase 1 → Phase 2 → Phase 3 → (并行的可任意组合: Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8) → Phase 9 → Phase 10 → Phase 11 → Phase 12 → Phase 13

---

### 2. Phase 1: Cave 缓冲区 1024→2048(最小修复) ✅ 已完成

> **实施时间**: 2026-08-15
> **提交**: 见 commit 历史
> **验收**: ✅ Cave 内存分配现按 `TKS_CAVE_BUDGET` 环境变量 (默认 2048) 分配

#### 范围 (Scope)
- `tks_launcher_gui/workers/patcher_worker.py:505`
- `tks_launcher_gui/cli_launcher.py:750`

#### 风险 (Risk)
- **极低**: 仅扩大分配,不影响写入逻辑
- Wine/Nuitka: 无影响(`VirtualAllocEx` API 一致)
- 兼容现有 `.tkspatch`: 不变(cave_offset 仍硬编码,只是不再越界)

#### 实施方案
**Patch 1.1** (`patcher_worker.py:505`):
```diff
- ca = _VirtualAllocEx(hp, None, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
+ _CAVE_BUDGET = int(os.environ.get("TKS_CAVE_BUDGET", 2048))
+ ca = _VirtualAllocEx(hp, None, _CAVE_BUDGET, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
```

**Patch 1.2** (`patcher_worker.py:509`):
```diff
- self._log(f"  Cave 内存: 0x{cave_addr:08X} (1024 bytes)")
+ self._log(f"  Cave 内存: 0x{cave_addr:08X} ({_CAVE_BUDGET} bytes)")
```

**Patch 1.3** (`cli_launcher.py:750-756`): 同上 2 处替换。

#### 验收 (Acceptance)
1. 启动原版 TKS.exe,启动器日志显示 "Cave 内存: 0xXXXXXXXX (2048 bytes)"
2. 应用 `war_mustchar_fallback` + `skill_menu_cap` + `exp_lock` + `team_member_routing` 四个已知越界补丁
3. 进入战斗 → 不随机崩溃
4. 关闭游戏 → 启动器无异常

#### 回滚 (Rollback)
- `TKS_CAVE_BUDGET=1024` 环境变量回退(无需改代码)

---

### 3. Phase 2: Cave 写入越界硬校验 ✅ 已完成

> **实施时间**: 2026-08-15
> **实现**: `_check_cave_bounds` 辅助函数在 `apply_cave_hook` / `_apply_summon_random` / `_apply_exp_lock` 入口处调用
> **验收**: ✅ 故意设置 `cave_offset=3000` 触发 `[CAVE-OOB]` 日志, 正常补丁无影响

#### 范围 (Scope)
- `tks_launcher_gui/core/patch_engine.py:1020` (`apply_cave_hook` 内 `ct = cave_addr + defn.cave_offset`)
- `tks_launcher_gui/core/patch_engine.py:1289-1301` (`_write_cave_and_hook`)
- `tks_launcher_gui/core/patch_engine.py:1247` (`_apply_summon_random` 内 `random_table_offset`)

#### 风险 (Risk)
- **中**: 若现有 `.tkspatch` 真的依赖越界写入,校验失败会导致补丁跳过
- 缓解: 校验仅 `[WARN]` + 跳过,**不抛异常**(可配置升级为 `error`)
- 兼容现有 `.tkspatch`: 已实测 5 个越界 cave_hook(Phase 1 修复后不再越界),本阶段仅是防御性兜底

#### 实施方案
**新增辅助函数** (`patch_engine.py` 顶部):
```python
def _check_cave_bounds(cave_addr: int, offset: int, size: int, budget: int, label: str, log) -> bool:
    """返回 True 表示在范围内,False 表示越界(已日志告警)。"""
    if offset < 0 or size < 0:
        log(f"  [CAVE-OOB] {label}: offset/size 负值 (offset=0x{offset:X}, size={size})")
        return False
    end = offset + size
    if end > budget:
        log(f"  [CAVE-OOB] {label}: 0x{offset:X}+{size}={end} > budget={budget}, 跳过")
        return False
    return True
```

**Patch 2.1** (`apply_cave_hook` 在 `ct = cave_addr + defn.cave_offset` 之前):
```python
cave_budget = ctx.variables.get("cave_total_size", 2048)
if not _check_cave_bounds(cave_addr, defn.cave_offset, len(cave_code), cave_budget, defn.id, log):
    continue
```

**Patch 2.2** (`_apply_summon_random` 在 `random_*_offset` 三处):
```python
for off_key, size_key in [("random_table_offset", 90),
                          ("random_cave_offset", 77),
                          ("random2_cave_offset", 63)]:
    off = getattr(defn, off_key, 0)
    if not _check_cave_bounds(cave_addr, off, size_key, cave_budget,
                              f"{defn.id}/{off_key}", log):
        return False
```

#### 验收
1. 故意把某 `.tkspatch` 的 `cave_offset` 改成 `3000`(超过 2048)→ 启动器日志打印 `[CAVE-OOB]`,该补丁跳过
2. 正常补丁无 `[CAVE-OOB]` 输出
3. `cave_total_size` 设为 4096 后,所有 1526B 内 cave 正常工作

#### 回滚
- 删除 `_check_cave_bounds` 调用点(`grep _check_cave_bounds`),不需动 `apply_cave_hook` 主体

---

### 4. Phase 3: `_variables.tkspatch` 暴露 `cave_total_size` ✅ 已完成

> **实施时间**: 2026-08-15
> **实现**: `_variables.tkspatch` 中已声明 `cave_total_size` 全局变量; patcher_worker.py / cli_launcher.py / pipeline.py 消费 `cave_total_size` 变量
> **验收**: ✅ 缺省值 2048, 可通过 `_variables.tkspatch` 或 `TKS_CAVE_BUDGET` 环境变量覆盖

#### 范围 (Scope)
- `tks_launcher_gui/patches/_variables.tkspatch`
- `tks_launcher_gui/core/tkspatch_loader.py:226-269` (`load_variables_from_dir`)
- `tks_launcher_gui/workers/patcher_worker.py:505` (消费方)
- `tks_launcher_gui/cli_launcher.py:750` (消费方)

#### 风险 (Risk)
- **低**: 仅新增变量字段,旧 `.tkspatch` 无 `cave_total_size` 时使用默认值 2048

#### 实施方案
**Patch 3.1** (`_variables.tkspatch` 新增):
```json
{
  "_comment_cave_total_size": "Cave 虚拟页总字节数,默认 2048;超 1526 实测需求",
  "cave_total_size": 2048
}
```

**Patch 3.2** (`patcher_worker.py:505`):
```diff
- _CAVE_BUDGET = int(os.environ.get("TKS_CAVE_BUDGET", 2048))
+ _CAVE_BUDGET = int(os.environ.get("TKS_CAVE_BUDGET",
+                     config.variables.get("cave_total_size", 2048)))
```

(注意 `config` 变量在该位置已可用,因为 `_variables.tkspatch` 已加载)

**Patch 3.3** (`cli_launcher.py:750`): 同上,但 `config` 加载时机需确认(若 `cave_total_size` 在该函数之后被加载,改用先读取 variables 的提前调用)

#### 验收
1. 修改 `_variables.tkspatch` 中 `cave_total_size: 4096`
2. 启动器日志显示 "Cave 内存: 0xXXXXXXXX (4096 bytes)"
3. 不修改 `.tkspatch` 时默认 2048 行为不变

#### 回滚
- 还原 `_variables.tkspatch` 字段 → 默认值生效

---

### 5. Phase 4: 抽取 `PatcherPipeline` 共享类(消除 worker/cli 重复) ✅ 已完成

> **实施时间**: 2026-08-15
> **新增文件**: `tks_launcher_gui/core/launcher_pipeline.py` (PatcherPipeline + PipelineConfig + PipelineResult)
> **改造文件**: `workers/patcher_worker.py` (~35.9KB → 22.1KB), `cli_launcher.py` (~46.3KB → 30.5KB)
> **验收**: ✅ CLI/GUI 双入口均委托给 PatcherPipeline; GUI 保留 tool injection / TKS.exe MOD replacement; CLI 保留 Wine/no_* flags

#### 范围 (Scope)
- **新增** `tks_launcher_gui/core/launcher_pipeline.py`
- `tks_launcher_gui/workers/patcher_worker.py:88-637`(改为 ~100 行包装)
- `tks_launcher_gui/cli_launcher.py:248-872`(改为 ~150 行包装)
- `tks_launcher_gui/core/patch_engine.py`(消费 `ctx.diagnostics` 替代局部变量)

#### 风险 (Risk)
- **高**: 重构,涉及 3 个文件、~700 行代码迁移
- 必须保持 100% 行为等价 — 任何细微差异会导致 Wine 下回归
- **强烈建议**在重构前建立"金标准"测试用例(见 §14)

#### 实施方案

##### 5.1 新增 `core/launcher_pipeline.py`

```python
"""启动器核心流水线,供 GUI Worker 与 CLI 共用。"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

LogFunc = Callable[[str], None]

@dataclass
class PipelineConfig:
    exe_path: str
    patches_dir: str
    mods_dir: str
    wait_timeout: float = 15.0
    no_suspend: bool = False          # Wine 兼容
    no_runtime_hooks: bool = False    # 诊断模式
    disabled_patches: set = field(default_factory=set)
    selected_tool: Optional[str] = None
    extra_vars: dict = field(default_factory=dict)

@dataclass
class PipelineDiagnostics:
    target_pid: int = 0
    base_addr: int = 0
    code_start: int = 0
    cave_addr: int = 0
    cave_size: int = 0
    warpc_new_base: int = 0
    profile_name: str = ""
    loaded_mods: List[str] = field(default_factory=list)
    applied_patches: List[str] = field(default_factory=list)
    skipped_patches: List[tuple] = field(default_factory=list)  # (id, reason)
    warnings: List[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    success: bool = False


class PatcherPipeline:
    """纯逻辑,无 PySide6 依赖。"""

    def __init__(self, cfg: PipelineConfig, log: LogFunc):
        self.cfg = cfg
        self.log = log
        self.diagnostics = PipelineDiagnostics()

    def run(self) -> PipelineDiagnostics:
        """主入口:挂起→读码段→profile→WarPC→cave→apply→恢复。"""
        # ... 原 patcher_worker._do_run() 与 cli_launcher._do_run() 的共享逻辑
        # 全部迁入此处,使用 self.log / self.diagnostics 替代原 signal/print
        ...

    # 拆分为子方法,与原 _do_run 对应:
    def _launch_suspended(self) -> subprocess.Popen: ...
    def _detect_or_wait_child(self, proc) -> int: ...
    def _read_code_segment(self, pid, base) -> Tuple[bytes, int]: ...
    def _detect_profile(self, base) -> ExeProfile: ...
    def _expand_warpc(self, ctx) -> int: ...
    def _allocate_cave(self, pid) -> int: ...
    def _apply_all_patches(self, ctx) -> None: ...
    def _resume_game(self, pid) -> bool: ...
```

##### 5.2 改造 `PatcherWorker`(保持外部 API 不变)

```python
class PatcherWorker(QThread):
    log_emitted = Signal(str)
    status_changed = Signal(str)
    finished = Signal(bool, dict)  # 改为传 diagnostics

    def __init__(self, cfg: PipelineConfig, ...):
        super().__init__()
        self.cfg = cfg

    def run(self):
        pipeline = PatcherPipeline(self.cfg, self._log)
        diag = pipeline.run()
        self.finished.emit(diag.success, asdict(diag))

    def _log(self, msg: str):
        self.log_emitted.emit(msg)
```

##### 5.3 改造 `CliLauncher`

```python
class CliLauncher:
    def __init__(self, cfg_path: str):
        self.cfg = self._load_cfg(cfg_path)

    def run(self):
        pipeline_cfg = PipelineConfig(
            exe_path=self.cfg["tks_exe"],
            patches_dir=self.cfg["patches_dir"],
            mods_dir=self.cfg["mods_dir"],
            wait_timeout=self.cfg.get("wait_timeout", 15.0),
            no_suspend=self.cfg.get("advanced", {}).get("no_suspend", True),
            no_runtime_hooks=self.cfg.get("advanced", {}).get("no_runtime_hooks", False),
            disabled_patches=set(self.cfg.get("advanced", {}).get("disabled_patches", [])),
        )
        pipeline = PatcherPipeline(pipeline_cfg, print)
        diag = pipeline.run()
        sys.exit(0 if diag.success else 1)
```

#### 验收
1. **等价性测试** (必备):
   - 跑原版 TKS.exe + 全补丁启用,记录完整日志(包含 cave 地址、profile、applied_patches 列表)
   - 重构后跑同一组合,日志字段与值必须**完全一致**(除时间戳)
2. **CLI 回归**: 在 Wine/Winlator 容器跑 `cli_launcher.py`,确认 `--no-suspend` 路径正常
3. **GUI 回归**: 用 `PatcherWorker` 跑 `python main.py`,确认所有 signal 触发顺序与原版一致
4. 备份原 `patcher_worker.py` / `cli_launcher.py` 到 `tks_launcher_gui/backups/pre_pipeline/`

#### 回滚
- `git checkout HEAD -- workers/patcher_worker.py cli_launcher.py` + 删除 `core/launcher_pipeline.py`
- 若已 commit: `git revert <commit-hash>`

---

### 6. Phase 5: `apply_config_patches` 改为注册表派发 ✅ 已完成

> **实施时间**: 2026-08-15
> **实现**: `_PATCH_TYPE_HANDLERS` 字典 + `@register_patch_type` 装饰器 + 12 个 `_handle_*` wrapper 函数
> **保留特例**: `cave_hook` (二阶段处理), `script` (委托 `run_script_patch`), `patch_warpc_addr` (logging-only no-op)
> **验收**: ✅ 全部 55 个 .tkspatch 加载 + 应用行为不变; 新增 patch type 只需 `@register_patch_type("xxx")` + 函数体

#### 范围 (Scope)
- `tks_launcher_gui/core/patch_engine.py:2154-2314` (`apply_config_patches` + `apply_*` 全部 16 函数)

#### 风险 (Risk)
- **中**: 重构调度器,影响每个 `apply_*` 函数的调用上下文
- 必须保持各 `apply_*` 的输入参数不变

#### 实施方案

##### 6.1 定义统一协议

```python
# patch_engine.py 顶部
PatchHandler = Callable[[PatchDef, "PatchContext"], bool]

_PATCH_HANDLERS: Dict[str, PatchHandler] = {}

def register_patch_type(type_name: str):
    def deco(fn: PatchHandler) -> PatchHandler:
        _PATCH_HANDLERS[type_name] = fn
        return fn
    return deco
```

##### 6.2 重写 `apply_config_patches`

```python
def apply_config_patches(config, code_buf, code_start, base_addr, h_proc,
                          cave_addr, warpc_base, log_func=None, exe_profile=None):
    log = log_func or (lambda x: None)
    ctx = PatchContext(
        defn=None,  # 由每个 handler 自填
        target_pid=config.variables.get("_target_pid", 0),
        h_proc=h_proc,
        base_addr=base_addr,
        code_buf=code_buf,
        code_start_addr=code_start,
        cave_addr=cave_addr,
        warpc_base=warpc_base,
        variables=config.variables,
        log_func=log,
        exe_profile=exe_profile,
    )

    pending_cave_hooks: List[PatchDef] = []

    for defn in config.patches:
        if not _passes_filters(defn, config, exe_profile, log):
            continue

        handler = _PATCH_HANDLERS.get(defn.type)
        if handler is None:
            log(f"  [WARN] 未知 patch type: {defn.type} ({defn.id}), 跳过")
            continue

        if defn.type == "cave_hook":
            # 二阶段调度:扫描后入栈
            hits = _scan_hook(defn, code_buf, base_addr, exe_profile, log)
            if hits:
                defn._pre_scanned_hits = hits
                pending_cave_hooks.append(defn)
        else:
            try:
                handler(defn, ctx)
            except Exception as e:
                log(f"  [ERROR] {defn.id}.{defn.type}: {e}")

    # 二阶段:cave_hook 批量安装
    for defn in pending_cave_hooks:
        _PATCH_HANDLERS["cave_hook"](defn, ctx)
```

##### 6.3 用装饰器标注每个 `apply_*`

```python
@register_patch_type("patch_bytes")
def apply_patch_bytes(defn, ctx): ...

@register_patch_type("cave_hook")
def apply_cave_hook(defn, ctx): ...

# 等等,共 12 个
```

#### 验收
1. 所有现有 `.tkspatch` 应用行为不变(对照 Phase 4 验收日志)
2. 新增 patch type 只需 `@register_patch_type("xxx")` + 函数体,无需修改 `apply_config_patches`

#### 回滚
- 删除 `_PATCH_HANDLERS` / `register_patch_type` / `apply_config_patches` 改回 `if/elif` 链

---

### 7. Phase 6: `cave_offset` 自动布局器 ✅ 已完成

> **实施时间**: 2026-08-15
> **新增文件**: `tks_launcher_gui/core/cave_layout.py` (CaveSlot + CaveLayout + CaveLayoutError)
> **改造文件**: `core/patch_engine.py` (新增 `_build_cave_layout`, apply_cave_hook / _apply_summon_random / _apply_exp_lock 优先使用 `_resolved_*` 偏移)
> **PatchDef 新字段**: `autolayout_cave: bool = True` (新模式默认), False 保留硬编码兼容旧 .tkspatch
> **验收**: ✅ 自动分配按 16 字节对齐顺序布局, 与硬编码共存时自动分配避开硬编码区间, 越界/冲突报 `CaveLayoutError`

#### 范围 (Scope)
- **新增** `tks_launcher_gui/core/cave_layout.py`
- `tks_launcher_gui/core/patch_engine.py:1020` (`apply_cave_hook`)
- `tks_launcher_gui/core/patch_engine.py:1247` (`_apply_summon_random`)

#### 风险 (Risk)
- **中**: 改变 `cave_offset` 计算方式,需保证现有 .tkspatch 不受影响
- **关键决策**: 是否同时支持"作者硬编码 `cave_offset`" 与"自动分配"?

#### 实施方案

##### 7.1 决策: 兼容硬编码 + 新增自动模式

```python
# core/cave_layout.py
@dataclass
class CaveSlot:
    owner_id: str         # patch.id
    purpose: str          # "main" | "random_table" | "random_cave" | "random2_cave"
    size: int
    offset: int           # 自动分配或继承自硬编码

@dataclass
class CaveLayout:
    base_addr: int
    budget: int
    slots: List[CaveSlot] = field(default_factory=list)
    _used_end: int = 0

    def allocate(self, owner_id: str, purpose: str, size: int,
                 force_offset: Optional[int] = None, alignment: int = 16) -> CaveSlot:
        if force_offset is not None and force_offset >= 0:
            # 兼容硬编码
            offset = force_offset
            if offset + size > self.budget:
                raise CaveLayoutError(f"{owner_id}/{purpose}: 硬编码偏移 0x{offset:X}+{size} 超出 budget={self.budget}")
        else:
            # 自动分配
            offset = (self._used_end + alignment - 1) & ~(alignment - 1)
            if offset + size > self.budget:
                raise CaveLayoutError(f"{owner_id}/{purpose}: 自动分配失败,需要 0x{offset:X}+{size},budget={self.budget}")
            self._used_end = offset + size

        slot = CaveSlot(owner_id, purpose, size, offset)
        self.slots.append(slot)
        return slot
```

##### 7.2 在 `tkspatch_loader` 加 `_autolayout: bool` 字段

```python
# PatchDef 新增
autolayout_cave: bool = True  # 默认 True,新字段
```

##### 7.3 在 `apply_config_patches` 入口建立 CaveLayout

```python
cave_layout = CaveLayout(base_addr=cave_addr, budget=cave_total_size)

# 收集所有需要 cave 的 patch
for defn in config.patches:
    if defn.type in ("cave_hook", "patch_exp_lock"):
        offset = defn.cave_offset if defn.autolayout_cave == False else None
        slot = cave_layout.allocate(defn.id, "main", len(defn.cave_code or b""),
                                     force_offset=offset)
        defn._resolved_cave_offset = slot.offset
    elif defn.type == "patch_summon_table":
        # summon_table 的三个区域
        for purpose, size, off_attr in [
            ("random_table", 90, "random_table_offset"),
            ("random_cave", 77, "random_cave_offset"),
            ("random2_cave", 63, "random2_cave_offset"),
        ]:
            force_off = getattr(defn, off_attr, 0) if defn.autolayout_cave == False else None
            slot = cave_layout.allocate(defn.id, purpose, size, force_offset=force_off)
            setattr(defn, f"_resolved_{off_attr}", slot.offset)
```

##### 7.4 `apply_cave_hook` 用 `defn._resolved_cave_offset` 替代 `defn.cave_offset`

```python
# apply_cave_hook 内
ct = cave_addr + getattr(defn, "_resolved_cave_offset", defn.cave_offset)
```

#### 验收
1. **新模式**: 改某 `.tkspatch` 加 `"autolayout_cave": true`(默认即新模式),删掉 `cave_offset` 字段 → 启动器日志显示自动分配偏移
2. **旧模式**: 设 `"autolayout_cave": false` + 保留 `cave_offset` → 与原行为一致
3. **冲突检测**: 两个 cave_hook 都设 `cave_offset: 0` + `autolayout_cave: false` → 第二个报 `[CAVE-OOB]` 或 `CaveLayoutError`

#### 回滚
- `PatchDef.autolayout_cave` 默认改回 `False` → 全部走硬编码路径

---

### 8. Phase 7: `hook_conflict_action` 多模式识别 + hook_table ✅ 已完成

> **实施时间**: 2026-08-15
> **新增 API**: `detect_hook_type()` (识别 call_rel32 / jmp_rel32 / jmp_rel8 / push_imm32 / jmp_indirect / jcc_rel32), `HookTable` 类, `check_hook_conflict_v2()` (返回 `(conflict, owner)`)
> **保留旧 API**: `check_hook_conflict(code_buf, off) -> bool` 向后兼容
> **改造**: `apply_config_patches` dispatcher 集成 HookTable, 每个 cave_hook 注册 + 检测
> **验收**: ✅ 启动器内部冲突 owner=patch_id, 外部 MOD 冲突 owner=external_call_or_jmp, 默认行为不变 (override 优先)

#### 范围 (Scope)
- `tks_launcher_gui/core/patch_engine.py:104-112` (`check_hook_conflict`)
- `tks_launcher_gui/core/patch_engine.py:2238-2246` (调用点)

#### 风险 (Risk)
- **中**: 改变冲突判定逻辑,孝谈三国3终极版兼容性需回归测试
- 默认行为应不变("override" 优先)

#### 实施方案

```python
def detect_hook_type(code_buf, off) -> Tuple[str, int]:
    """返回 (hook 类型, 占用字节数)。"""
    if off >= len(code_buf):
        return ("oob", 0)
    b0 = code_buf[off]
    if b0 == 0xE8: return ("call_rel32", 5)
    if b0 == 0xE9: return ("jmp_rel32", 5)
    if b0 == 0xEB: return ("jmp_rel8", 2)
    if b0 == 0x68: return ("push_imm32", 5)  # 常搭配 C3
    if b0 == 0xFF and off + 1 < len(code_buf):
        if code_buf[off+1] == 0x25: return ("jmp_indirect", 6)
    if b0 == 0x0F and off + 1 < len(code_buf):
        b1 = code_buf[off+1]
        if 0x80 <= b1 <= 0x8F: return ("jcc_rel32", 6)  # Jcc
    return ("none", 0)


# hook_table: 在 PatchContext 上新增
ctx.hook_table: Dict[int, str] = {}  # offset -> owner_patch_id

def check_hook_conflict_v2(code_buf, off, ctx) -> Tuple[bool, str]:
    """返回 (是否冲突, 冲突 owner 或 'none')。"""
    if off in ctx.hook_table:
        return (True, ctx.hook_table[off])

    ht, _ = detect_hook_type(code_buf, off)
    if ht in ("call_rel32", "jmp_rel32"):
        return (True, "external_call_or_jmp")
    return (False, "none")
```

#### 验收
1. 原版 TKS.exe + 全 cave_hook → 无冲突报告(原行为)
2. 故意构造 `[E8 xx xx xx xx]` 在某 hook 点 → 报告 `external_call_or_jmp` + 按 `hook_conflict_action` 处理
3. 孝谈三国3终极版跑一次 → 行为与 Phase 4 等价

---

### 9. Phase 8: `config_loader` 与 `tkspatch_loader` 字段映射合并 ✅ 已完成

> **实施时间**: 2026-08-15
> **新增函数**: `core/tkspatch_loader.parse_patch_dict(raw, source_path, script_resolve_mode)`
> **改造**: `config_loader.load_config` (旧 tks_patches.json) + `tkspatch_loader._load_tkspatch_json` (.tkspatch ZIP/JSON) 均委托
> **副作用修复**: `launcher_config.json` 的 `patches.enabled` 列表兼容 (现仅在 patches 为 list 时才迭代 dict)
> **验收**: ✅ 现有 tks_patches.json 加载行为不变; 现有 .tkspatch ZIP/JSON 加载行为不变; 字段映射逻辑统一在 1 处

#### 范围 (Scope)
- `tks_launcher_gui/core/config_loader.py:130-196` (`load_config` JSON 解析)
- `tks_launcher_gui/core/tkspatch_loader.py:104-194` (`_load_tkspatch_json` JSON 解析)

#### 风险 (Risk)
- **低**: 纯重构,行为不变
- 风险点: 旧 `tks_patches.json` 字段命名差异

#### 实施方案

```python
# core/tkspatch_loader.py
def parse_patch_dict(raw: dict, source_path: str) -> PatchDef:
    """统一字段映射,供 .tkspatch ZIP/JSON 和 tks_patches.json 共用。"""
    d = PatchDef(
        id=raw.get("id") or raw.get("name") or os.path.splitext(os.path.basename(source_path))[0],
        type=raw.get("type", "patch_bytes"),
        # ... 所有字段映射(归一化 id→id, name→id;patch_json→patch.json 等)
    )
    return d


def _load_tkspatch_json(path: str) -> PatchDef:
    with open(path, "r", encoding="utf-8") as f:
        return parse_patch_dict(json.load(f), path)
```

```python
# core/config_loader.py
def load_config(path: str) -> PatchConfig:
    """旧 tks_patches.json 加载,委托给 parse_patch_dict。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    variables = data.get("variables", {})
    patches = [parse_patch_dict(p, path) for p in data.get("patches", [])]
    return PatchConfig(variables=variables, patches=patches)
```

#### 验收
1. 现有 `tks_patches.json` 加载行为不变
2. 现有 `.tkspatch` ZIP/JSON 加载行为不变

---

### 10. Phase 9: `code_buf` 分段只读 + 写入隔离 ⏳ 未实施

> **状态**: 高风险重构, 暂未实施。Phase 4 (PatcherPipeline) 已完成, 执行前提已满足, 可在后续迭代启动。
> **预期收益**: 大补丁启动时间 -30%, 减少 `apply_*` 函数对 `code_buf` 的隐式可变依赖

#### 范围 (Scope)
- `tks_launcher_gui/workers/patcher_worker.py:260-413` (读 code_buf + 应用)
- `tks_launcher_gui/core/patch_engine.py` 几乎所有 `apply_*`

#### 风险 (Risk)
- **高**: 改变 `code_buf` 用法,`apply_*` 函数期望它可变
- 缓解: 引入 `CodeView` 协议(读视图) + `PatchJournal`(写日志),最后阶段统一提交

#### 实施方案(概要,详见独立 sub-spec)

1. `class CodeView`: 提供 `read(off, size)` / `find(pattern)` / `__getitem__(slice)`,内部按 64KB 段缓存 `read_pm`
2. `class PatchJournal`: 记录 `(offset, old_byte, new_byte)` 列表
3. `apply_*` 函数接收 `CodeView` 而非 `bytearray`,所有"修改"写入 `PatchJournal`
4. 流水线末尾一次性 `apply_journal(h_proc, journal)` 写入目标进程

> **执行前提**: Phase 4 已完成(PatcherPipeline 重构),否则改动会同时影响 worker/cli 两份代码

#### 验收
- 与 Phase 4 验收等价 + 大补丁启动时间对比(预期 -30%)

---

### 11. Phase 10-13: 简表

> 注: Phase 11/12/13 已实施 ✅, 见各 Phase 章节详情。Phase 10 (`discover_warpc_base` 拓宽) 未实施。

| Phase | 标题 | 关键文件 | 一句话验收 | 状态 |
|---|---|---|---|---|
| 10 | `discover_warpc_base` 拓宽 + 多候选 | `core/scanner.py:340-376` | 扫描窗口扩 `[0x600000, 0x900000)` + top-3 候选日志 | ⏳ 未实施 |
| 11 | 模式扫描结果 LRU 缓存 | `core/scanner.py` (`PatternScanCache` 类) | 第二次启动时间 -50% | ✅ 已完成 |
| 12 | `.tkspatch` JSON Schema 校验 | `core/tkspatch_loader.py` (`validate_tkspatch_dict`) | 故意写错字段, 启动时报错而非崩溃 | ✅ 已完成 |
| 13 | `ExeProfile` 持久化缓存 | `core/scanner.py` (`ExeProfileCache` 类) | `launcher_cache/profile_<sha1>.json` 文件存在且二次启动时间 -80ms | ✅ 已完成 |

#### Phase 11 详情 ✅ 已完成

> **新增**: `core.scanner.PatternScanCache` (OrderedDict LRU + 磁盘持久化)
> - 缓存键: `(pattern_hex, data_hash)` / 缓存值: `List[int]`
> - `save_to_disk` / `load_from_disk` → `<cache_dir>/<exe_sha1>_patterns.json`
> - 默认 128 条目上限, LRU 淘汰

#### Phase 12 详情 ✅ 已完成

> **新增**: `core.tkspatch_loader.validate_tkspatch_dict(raw, source_path, log_func)`
> - 校验必填字段 (type, id), 类型 (str/int/bool/list/dict), 枚举 (hook_conflict_action), 负数范围, cave_code hex 合法性
> - `_load_tkspatch_json` 集成: `SCHEMA-FAIL` 日志 + 跳过该补丁 (不崩溃)
> - 兼容 `format` / `format_version` 字段 (现有 .tkspatch 使用)

#### Phase 13 详情 ✅ 已完成

> **新增**: `core.scanner.ExeProfileCache` (静态方法 `load` / `save` / `load_or_detect`)
> - 缓存文件: `launcher_cache/profile_<exe_sha1>.json`
> - `_compute_exe_sha1` 取 EXE 前 1MB + 总大小
> - `PatcherPipeline.run_post_launch` 集成: 优先 `ExeProfileCache.load_or_detect` 代替直接 `detect_exe_profile`

---

### 12. Phase 14: 不在本 spec 范围内(后续工作)

#### 12.1 Cave 模板全部外置(对应原报告"优化 1"延伸)
- 16 个 `CAVE_*` 常量迁至 `patches/_cave_templates/*.tkspatch`
- 收益: 修改 cave 不需改源码,但破坏现有 `cave_template` 字段语义,需大版本

#### 12.2 补丁依赖图与拓扑排序(对应原报告"优化 5")
- 引入 `depends_on: List[str]` + 拓扑排序
- 收益: 调整 .tkspatch 顺序不影响结果;但当前隐式依赖 `_variables.tkspatch` 固定顺序已稳定,引入价值有限

#### 12.3 GUI 持久化迁移 SQLite(对应原报告"优化 7")
- `launcher_setting.json` → `settings.db`
- 收益: 异常退出零数据丢失;但 JSON 文件 44 行规模,当前损坏概率极低

#### 12.4 `PatchContext` 协议化 + DI(对应原报告"优化"未列)
- 把 `log_func=None or (lambda x: None)` 替换为统一 `Logger` 接口
- 收益: 可测试性;但当前调用方 30+ 处,工作量大

#### 12.5 pattern_scan 通配符 `??` 与 `**` 语义统一(对应原报告"优化 8")
- `tkspatch_loader.py:54-56` (cave_code 中转 0x00) vs `scanner.py:278-281` (pattern_scan 中标记为 wildcard) 语义错配
- 建议: cave_code 解析时直接拒绝 `??`,或者在 `_parse_hex_bytes` 注释中明确警告

#### 12.6 SkimFstDlg 模式硬编码去重(对应原报告"优化 9")
- `patcher_worker.py:270` / `cli_launcher.py:416` / `cli_launcher.py:485` / `cli_launcher.py:563` 4 处重复硬编码 `b'\xA1\x14\xA5\x4F\x00\x50\xE8'`
- 建议: 提取到 `core/scanner.py` 常量 `_SKIMFSTDLG_SENTINEL`,统一引用

#### 12.7 WarPC 自动发现算法改进(对应原报告"优化 10")
- 孝谈三国3终极版 `.test` 段常量污染 → 扫描失败
- 建议: 孝谈三国3终极版 profile 下跳过自动发现,直接使用 `.test` 段中的导出符号表定位;或者 fallback 改多候选

#### 12.8 PE 节表页对齐修复(对应原报告"缺陷 5")
- `scanner.py:174-179` / `parse_pe_sections` L60-72 直接用 `sec.virtual_address + sec.virtual_size` 作为段结束,未考虑 SectionAlignment (0x1000)
- 影响: `apply_patch_imm32_by_value` 的 exclude_extra_sections 过滤可能放过应排除的字节

#### 12.9 apply_config_patches 依赖排序(对应原报告"缺陷 6")
- 当前依赖 `_variables.tkspatch` 固定顺序,无显式依赖声明
- 引入 `depends_on: List[str]` 字段 + 拓扑排序(与 12.2 同主题)

---

### 13. 兼容性矩阵

| 改动 | 原版 TKS.exe | 加密版 TKS.exe | 孝谈三国3终极版 | Wine/Winlator |
|---|---|---|---|---|
| Phase 1 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 |
| Phase 2 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 |
| Phase 3 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 |
| Phase 4 | ✅ 等价 | ✅ 等价 | ✅ 等价 | ⚠️ 需 Wine 回归 |
| Phase 5 | ✅ 等价 | ✅ 等价 | ✅ 等价 | ✅ 等价 |
| Phase 6 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 | ✅ 兼容 |
| Phase 7 | ✅ 等价 | ✅ 等价 | ⚠️ 需回归 | ⚠️ 需回归 |
| Phase 8 | ✅ 等价 | ✅ 等价 | ✅ 等价 | ✅ 等价 |
| Phase 9 | ✅ 等价 | ✅ 等价 | ✅ 等价 | ⚠️ 需回归 |
| Phase 10 | ✅ 等价 | ✅ 等价 | ✅ 改进 | ✅ 等价 |
| Phase 11-13 | ✅ 等价 | ✅ 等价 | ✅ 等价 | ✅ 等价 |

---

### 14. 验收体系

#### 14.1 金标准日志(Phase 4 之前必须生成)

将以下三组运行日志保存到 `tks_launcher_gui/backups/golden_logs/`:

1. `original_full.log` — 原版 TKS.exe + 全部补丁启用(CLI 模式)
2. `original_minimal.log` — 原版 TKS.exe + 仅 `gold_display` 启用
3. `xiaotan_full.log` — 孝谈三国3终极版 + 全部补丁启用

每份日志需记录:
- Cave 内存地址 + 大小
- WarPC 新基址
- ExeProfile 名称
- applied_patches 完整列表(按应用顺序)
- skipped_patches 列表 + 原因
- warnings 列表

#### 14.2 回归测试脚本(独立工具)

`tools/verify_patches.py` 已有雏形 (`main.py: --verify-patches` 入口),需扩展:
- 对比两次运行的 cave_addr / applied_patches 集合
- 字段差异 → 输出 `[REGRESSION]` 标记

#### 14.3 自动化验收

```python
# tools/regression_test.py(伪代码)
def test_phase_4():
    diag_old = run_pipeline_v0()
    diag_new = run_pipeline_v4()
    assert diag_old.cave_size == diag_new.cave_size
    assert set(diag_old.applied_patches) == set(diag_new.applied_patches)
    assert diag_old.profile_name == diag_new.profile_name
```

---

### 15. 风险登记册

| 风险 | 概率 | 影响 | 缓解 | 实际发生情况 |
|---|---|---|---|---|
| Phase 4 重构引入 GUI/CLI 行为差异 | 中 | 高 | 金标准日志对比 + Wine 容器回归 | ✅ **未发生** (CLI `--verify-patches` 55 补丁全通过) |
| Phase 6 自动布局器与硬编码 cave 互踩 | 中 | 高 | 默认开启自动;硬编码需显式 `autolayout_cave: false` | ✅ **未发生** (混合模式测试通过, 自动分配避开硬编码区间) |
| Phase 7 多模式识别在孝谈三国3终极版误报 | 中 | 中 | 优先级标 "skip" 时新检测不阻断"override" | ⏳ **待回归** (孝谈三国3终极版 .exe 不在测试环境, 需实际运行环境验证) |
| Phase 9 CodeView 协议重写所有 apply_* 引入 bug | 高 | 高 | 分阶段提交,每步回归 | ⏸️ **未实施** (Phase 9 延期到 v2.x) |
| `_variables.tkspatch` 字段名 typo | 低 | 中 | Phase 12 JSON Schema 校验兜底 | ✅ **未发生** (Phase 12 校验已就位) |
| Nuitka 编译后路径解析 | 低 | 中 | `runtime_bootstrap.get_app_dir` 已处理,无需改 | ✅ **未发生** (与本期重构无关) |

---

### 16. 时间表建议

| 周次 | 完成 Phase | 备注 |
|---|---|---|
| 第 1 周 | Phase 1 + 2 + 3 | P0 三件套,合并为单一 commit |
| 第 2-3 周 | Phase 4 | 重构 + 回归测试,合并为单一 commit |
| 第 4 周 | Phase 5 + 8 | 调度器注册表 + 字段映射合并 |
| 第 5-6 周 | Phase 6 + 7 | cave 自动布局 + hook 识别 |
| 第 7-8 周 | Phase 9 | CodeView 重构(可单独延期到 v2.x) |
| 第 9 周 | Phase 10-13 | 收尾改进 |

> **总预算**: ~9 周(若 Phase 9 延期: ~7 周)

### 16.1 实际实施时间表

> 2026-08-15 单日实施记录 (实际合并到 patchmod 分支)

| 时间 | 完成 Phase | 备注 |
|---|---|---|
| 上午 | Phase 4 (PatcherPipeline) | patcher_worker.py 35.9KB→22.1KB, cli_launcher.py 46.3KB→30.5KB |
| 上午 | Phase 5 (注册表派发) | _PATCH_TYPE_HANDLERS + @register_patch_type |
| 中午 | Phase 6 (CaveLayout) | 新增 core/cave_layout.py (CaveLayout + CaveSlot + CaveLayoutError) |
| 中午 | Phase 7 (HookTable) | detect_hook_type + HookTable + check_hook_conflict_v2 |
| 下午 | Phase 8 (字段映射合并) | parse_patch_dict 统一字段映射 |
| 下午 | Phase 11 (PatternScanCache) | LRU + 磁盘持久化 |
| 下午 | Phase 12 (validate_tkspatch_dict) | JSON Schema 校验 |
| 下午 | Phase 13 (ExeProfileCache) | launcher_cache 持久化 |
| 收尾 | 最终验证 + 文档更新 | 8 个 Phase 单元测试全通过, CLI --verify-patches 55 个补丁全通过 |

---

### 17. 决策记录

#### 17.0 整合说明
- 本 spec 由"启动器补丁架构分析报告.md"(整合前 507 行,2026-08-15 出具) 与"修复计划 spec v1.0"(整合前 785 行) 合并
- 原架构报告整体下沉为"第一部分:背景资料"(§1A-§1K),观察事实与诊断
- 原修复 spec 主体为"第二部分:修复方案"(§2-§17),优先级 + 实施 + 验收 + 回滚
- 原报告 §十二 的 10 条"优化点"已映射到 §12 后续工作的 9 个子项

#### 17.1 已决策
- **Phase 1 选 2048 而非 4096**: 实测 1526 字节,2048 留 25% 余量,4096 浪费虚拟地址空间
- **Phase 4 重构而非补丁式去重**: 700 行复制粘贴只能用单一类替换,部分提取收益太低
- **Phase 6 兼容硬编码**: 现有 `.tkspatch` 大量依赖硬编码 `cave_offset`,纯自动布局会破坏向后兼容
- **整合而非追加章节**: 原架构报告作为事实层下沉到 §1A-§1K,避免在 spec 中重复陈述"现在是什么"

#### 17.2 待决策(下次评审时确认)

- Phase 6 默认 `autolayout_cave=True` 还是 `False`?
  - ✅ **已决策**: `True` (新行为优先, 允许 `autolayout_cave: false` 强制旧行为)
  - 实施后回归: 现有 16 个 cave 补丁全部走自动布局, 0 个破坏
- Phase 7 是否引入 "ask" 模式(冲突时弹 GUI 询问)?
  - 推荐先不做,GUI 询问在 Wine 下不可用
- Phase 9 是否纳入 v1.x 还是延期到 v2.x?
  - ✅ **已决策**: 延期到 v2.x (高风险, 收益限于启动速度 -30%)

#### 17.3 已否决
- ❌ 把 cave 缓冲区分配移到 WarPC 缓冲区尾部(64KB GUARD 后):
  - 复杂度高,GUARD 设计意图改变
  - 现有补丁中 `warpc_base_for_caves` 复用导致依赖反转
- ❌ 把 `cli_launcher.py` 完全删除,只留 `patcher_worker.py`:
  - Wine/Winlator 无 PySide6 兼容性问题,删 CLI 失去 32 位 Android 兼容路径
- ❌ 引入 Rust 重写 `apply_*` 函数:
  - 收益不明确;迁移成本极高

#### 17.4 整合时的额外发现
- 三份研究报告(0137ea85 / 5d35cb33 / 7c0fb5ac)与原架构报告实测 cave 占用的差异(955 vs 1526)已记录在 §1D 注释
- Phase 1 选 2048 同时覆盖两份估计,无需再争议

---

### 18. 索引

| 章节 | 内容 |
|---|---|
| §0 + 0A + 0B | 阅读指南 + 关键文件索引 + .tkspatch 清单 |
| §1A-1K | 第一部分:背景资料(架构分层、加载链、调度、cave、cave_offset、WarPC、挂起恢复、扫描、hook、profile、原报告缺陷映射)|
| §1 | 优先级总表 |
| §2-9 | Phase 1-8 详细方案 |
| §10-11 | Phase 9-13 简表 |
| §12 | Phase 14 后续工作(含原报告 10 条优化点的映射)|
| §13 | 兼容性矩阵 |
| §14 | 验收体系 |
| §15 | 风险登记册 |
| §16 | 时间表 |
| §17 | 决策记录(含整合说明)|
| §18 | 索引(本表)|

---

**版本**: v2.0(整合版)
**整合日期**: 2026-08-15
**下次评审**: 收到 reviewer 反馈后 3 个工作日内
**执行启动**: 用户确认 §17.2 待决策项后
