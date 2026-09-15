# tks_launcher_gui 补丁全量验证报告

- **验证对象**：`tks_launcher_gui\patches` 目录下全部 58 个补丁（53 个 patch.json 声明式补丁 + 5 个脚本补丁）
- **逆向依据**：`反编译产物`（原版 decompile/disassembly）+ 原版 `逆向工作区/TKS.exe` 二进制
- **验证日期**：2026-08-25
- **配套工具**：`工作区/.qoder\verify_patches.py`（可复跑的全量特征码扫描脚本）、`patch_verify_report.txt`（扫描原始输出）

---

## 一、验证方法

1. **特征码全量重扫**：用原版 TKS.exe 重建内存映像（PE 段映射，模拟 code_buf = base+0x1000 起的 3MB 窗口），逐条重扫全部特征码（含 `**`/`??` 通配符），核对命中数与 `expect_count`；
2. **写入区间冲突检测**：汇总全部补丁（patch_bytes / cave_hook / patch_imm32 / 脚本补丁硬编码地址）的写入区间，做两两重叠检测；
3. **机器码级语义核对**：用 capstone 反汇编 + 反编译源码，逐条核对每个 cave 的指令编码、栈平衡、rel32 跳转目标、被替换指令的指令边界；
4. **Cave 布局模拟**：全补丁启用、autolayout、budget=2048 条件下模拟 CaveLayout 分配水位；
5. **引擎流程审查**：`patch_engine.py` / `launcher_pipeline.py` / `warpc_expander.py` / `cave_layout.py` 的应用顺序、fallback 语义、冲突检测、句柄管理。

**总体结论：补丁体系质量很高，未发现会导致崩溃或内存破坏的错误。发现 2 个应修正的准确性问题、3 个边界注意事项，已全部修复（见第六节修复记录）。**

---

## 二、发现的问题（均已修复，详见第六节）

### 🔴 P1：`save_stream_error_fix` 缺少 `expect_count`，特征码双命中

特征码 `8B 4A 08 85 C9 0F 94 C0 83 E0 01 84 C0` 在原版中有 **2 处命中**：

| 命中 VA | 所属函数 | 说明 |
|---|---|---|
| 0x41C12B | sub_41C120 | 补丁注释声明的目标 |
| 0x41D9B7 | **sub_41D9AC** | 注释未提及的姊妹函数 |

`apply_patch_bytes` 在 `expect_count=0` 时对**全部命中写入**。两函数均为 STL 流状态检查，改写后都变成"强制清零 iostate + 恒返回成功"。第二处会让 sub_41D9AC 的全部调用方（0x41D750、0x41DAC4）永远拿到"流正常"，掩盖真实流错误。

**建议**：若第二处是有意为之，补 `"expect_count": 2` 并在注释中写明；若不是，增加锚定字节排除 0x41D9B7。

**✅ 已修复**：逆向确认 sub_41D9AC 的调用链（sub_41D750/sub_41DAC4 ← sub_41CE10，与存档列表 sub_41AB94 共享调用方 0x42131C/0x426164）为**存档侧**流检查，与读档侧 sub_41C120 构成存/读档一对，双写属必要行为。已补 `expect_count: 2` 并在注释中写明两处目标的归属。

### 🟠 P2：3 个 `fallback_rva` 数值错误（VA 误写）

引擎按 **RVA** 解释 `fallback_rva`（`patch_engine.py` L2643：`fb - 0x1000` 得 code_buf 偏移）：

| 补丁 | 当前值 | 问题 | 正确值 |
|---|---|---|---|
| awk_sprite_cave | `0x43CA72` | 是 VA；且即使按 VA 解释也指向无关函数 sub_43CA64（战斗主循环），真实 hook 点 VA=0x4309A6（sub_4307CC 内） | `0x309A6` |
| awk_sprite_cave2 | `0x43CA8D` | 同上，真实 hook 点 VA=0x431162（sub_431094 内） | `0x31162` |
| war_mustchar_fallback | `0x430895` | 是 VA（对照：summon_exp_jp 的 `0x41832`、war_hp_mp_bars 的 `0x3A79C` 均为正确 RVA） | `0x30895` |

**后果**：原版特征码必然命中，无实际影响；但 MOD 版本特征码失效走回退路径时，会算出 >3MB 的偏移被判"越界跳过"，功能静默丢失。**建议改为正确 RVA。**

**✅ 已修复**：三处 fallback_rva 已改为 `0x309A6` / `0x31162` / `0x30895`，回归测试确认回退偏移落在 code_buf 范围内且字节与 hook_pattern 匹配。

### 🟠 P3：`gold_limit` 加法溢出回退仍钳制到 30000

sub_40CE30（AddItem 金钱）中 `if (30000 - gold >= a2)` 已正确锚定改为 65535，但 else 分支 `word_756882 = 30000`（实际指令为 16 位写入 `66 C7 05 82 68 75 00 30 75` @0x40CE5F）**未修改**。边界场景：金钱接近 65535 时再获得一笔导致溢出的金额，会回落到 30000 而非 65535。

**✅ 已修复**：新增第三锚点 `66 C7 05 82 68 75 00 30 75 EB`（后缀 EB 区分 sub_411E84 @0x412372 的**场景赠金**——后者为剧情设计，保持原版不改），并为引擎 `patch_imm32` 新增 `value_size` 字段支持 imm16 宽度写入（原固定写 4 字节会踩坏紧邻的 EB 跳转指令）。

### 🟡 P4：`gold_display` 缺 `expect_count`

当前仅 1 处命中无实害，但失去一致性保护（未来/MOD 版多命中时会盲写）。建议补 `"expect_count": 1`。

**✅ 已修复**：已补 `expect_count: 1`。

### 🟡 P5：`weapon_cause_mask_hook` 扩容 WarPC 后对新角色失效

cave 内 `cmp eax, 0x8F`（索引 ≤143）为写死值；`build_cave_template` 只对 awk_sprite/awk_sprite2 动态上调索引上限（idx_cap）。WarPC 扩容后新角色（>143）只是**跳过武器附加状态**（安全降级，不破坏），但与"扩容全兼容"预期有出入。可仿照 awk cave 的 idx_cap 机制处理。

**✅ 已修复**：`build_cave_template` 新增 `rec_count` 参数，对 weapon_cause_mask 的内置/外置 cave 自动将 `cmp eax,0x8F` 同长替换为 `cmp eax,记录数`（未扩容时 =143，与原版指令完全一致；扩容后 = 新 WarPC.dat 实际记录数）。模板长度不变，不影响 cave 布局。

---

## 三、逐类验证结果

### 3.1 特征码与地址（58/58 通过）

全部特征码在原版 .text 内**唯一命中或命中数与 expect_count 完全一致**，与补丁注释声明的地址逐一吻合。代表性核对：

| 补丁 | 命中 VA | 与注释声明 |
|---|---|---|
| battle_treasure_reveal / enemy_info_reveal | 0x4318A5 / 0x4318AC | ✅（sub_431428 战场初始化一次性写入） |
| exp_bonus / exp_cap / exp_lock | 0x43BA27 / 0x43BADF / 0x43BAF3 | ✅（sub_43B7FC 战后结算，互不重叠） |
| skill_menu_cap（双 hook） | 0x439049 / 0x447C6B | ✅（sub_438F28 / sub_447BA8） |
| summon_table hooks | 0x444C84 / 0x444C9C / 0x444CB3 | ✅（sub_444BB0 尾部分派区） |
| checkitem_unsigned_fix 4 处 | 0x40E60D/1D/2D/3D | ✅（sub_40E4E4 四比较分支） |
| disable_pface_jvg 5 处 | 0x40D354/40D557/40D88D/412CB4/43004E | ✅（5 个 pface.jvg 加载点） |
| team 系列 | 0x40DA11/DA1C/DA23/DB44 | ✅（sub_40DA00 内严格相邻，见 3.2） |

value_scan 类计数全部符合：warpc_size_refs（0x24CC2）5 处、tkmat_size（0x232800）3 处、tkact 基址 0x9539CA 4 处 + 大小 509600 1 处、tkkon 基址 0x9D0698 19 处 + 大小 26000 1 处 + 派生引用 1 处。`tkitem_expand` 为 `patch_data_expand`：基址 `0x77CBCA`、大小 38400、字段引用跨度 64、64KB 数据段（1024 槽），并附带 2 处记录数上限改写（共 3 个机器码位点）。`tkshop_expand` 同样为 `patch_data_expand`：基址 `0x9508A0`、大小 1920、字段引用跨度 8、4KB 数据段（512 槽），并附带 2 处记录数上限改写（共 4 个机器码位点）。

### 3.2 写入区间冲突检测：无跨补丁重叠

重点核查区域：

- **sub_40DA00 四补丁**：team_member_limit（0x40DA11..0x40DA1C）→ team_member_routing hook（0x40DA1C..0x40DA23）→ team_clear_slot0（0x40DA23 起）→ team_leave_slot0（0x40DB44 起），严格相邻零重叠；
- **经验区三连**：exp_bonus（0x43BA27+9）、exp_cap（仅改 0x43BAE7 一字节）、exp_lock（0x43BAF3+7），注释声明"零重叠"经实测成立；
- **summon_table random2_1 hook（28 字节）**：覆盖 0x444CB3..0x444CCF，反汇编确认终点精确落在指令边界；与 skill_251_a/b 的 imm16 写点（0x444CC5/0x444CCD）存在包含关系，但引擎按 Step3（imm16）→Step4（random hook）顺序执行，配置随机列表后固定值让位于候选表，语义自洽；
- **summon_extend 与其余补丁**：HOOK_3（0x43109A..0x4310BE）与 awk_sprite_cave2 hook（0x431162）同在 sub_431094 内但不重叠。

### 3.3 Cave 机器码语义核对（全部通过）

每个 cave_hook 的机器码用 capstone 解码后与反编译逐指令比对：

| 补丁 | 核对结论 |
|---|---|
| team_member_routing | 6 条分支全部验证：(N,*)→0x40DA8D 与原版 jne 目标一致；(0,-1)→借道离队分支；(0,1)→槽位下移+槽0 插主角（跳 0x40DABC/0x40DBED 均为真实指令边界）；(0,其他)→ret 回 0x40DA23 走原版清空。"pop 返回地址→push 目标→ret"栈技巧平衡正确 |
| checkmember_level_redirect | `0F BF 4D 08; 8B D1` 回放正确（8B /r 目的在 reg 域=edx），续行点 0x40E8D1 的 ×527 寻址链完好 |
| history_text | WORD[262] 自定义值优先、否则回放 `add edx,0x235A`，栈平衡正确 |
| archive_portrait / portrait1 / portrait2 | WORD[261] 查询 + "xchg [esp],reg; jmp reg" 惯例正确；索引钳位（char_idx×527 ≤ 0x20000）正确 |
| duel_counter_self_fix | 入口 hook 完整回放 8 字节序言（含 push esi/edi），条件判断（byte_9D6FA4==a1 且 a1≠word_9D6F58）与描述一致 |
| duel_self_target_fix | 自伤时改写返回地址跳 0x4460F7——该点正是原版自身 `test byte_9D6C78; jne 0x4460F7` 的目标，复用原语义 |
| war_mustchar_fallback | 回放 movsx+dec+`mov [ebp-6],ax` 后跳 0x43089D（真实边界）；队伍无主角时以槽0 顶替，槽0 空(-1)时 sub_4307CC 放置循环有 `*v18>=0` 防线，0x430BC3 idiv 除零场景被消除 |
| skill_menu_cap | 复现 `movsx ecx,byte[edx+eax*2+0xB0]` 后按 word_9D6C8A≥12 清零 ecx，与 12 项平行数组（word_9D6D1A 24B 等）尺寸一致 |
| exp_bonus_overflow_fix | 乘法前把 *v19 钳位 [0,30000]，回放 imul 链正确 |
| exp_lock | cave_mask_offset=10 精确落在 `B2 imm8`；`[esp]`=槽位号语义与 sub_43B7FC 栈布局一致 |
| summon_exp_jp_accumulation_fix | 召唤物状态 20→100 映射，回放 movsx 后交还原版 `cmp eax,0x64` 分支 |
| weapon_cause_mask_hook | hook 点 0x4400F6 位于 sub_4400DC 入口 `rep movsd`（cause_mask 快照）之后，OR 结果进入下一次快照，与设计自洽（索引上限问题见 P5） |
| awk_sprite / awk_sprite_cave2 | WORD[260] 查询与原版 `v26+=6`/`v7+12` 语义衔接正确（custom-6 后走 +6 分支）；无 custom 时用 `test eax,eax` 置 ZF 供后续 jnz，标志位处理正确 |

### 3.4 summon_extend 脚本专项复核（重点）

- 实际反汇编确认 sub_431094 序言为 `push ebp; mov ebp,esp; add esp,-8; movsx [9DF88E]; push esi; push edi`（push esi/edi 位于被替换的 36 字节内），尾声为 `pop edi; pop esi; pop ecx; pop ecx; pop ebp; ret`；
- cave_3 Phase 5（`popad; mov [esp],esi; push edi; jmp 0x4310DA`）的栈形重建**与序言/尾声精确匹配**（V14 的 `add esp,8` 已按 V15 注释移除，当前代码正确）；
- HOOK_1（0x436C6D，sub_436BD4）、HOOK_2（0x444BC8，sub_444BB0 满槽判定）、HOOK_4（0x43C73E，sub_43C734 释放，hook_size=42 精确覆盖双槽清理分支，跳 0x43C768 为真实边界）全部与字节一致；
- PATCH_5（0x445088，sub_444FD4 `add ax,2`→`add ax,N`）、PATCH_7（0x431417 `mov [ecx+9DF88E],dl`——反编译确认 v5≥2 时会越界写 byte_9DF890/9DF891，NOP 正确且 cave_3 已自行同步 [0/1]）；
- CAPACITY hook（0x445582，`cmp edx,6; jl; xor eax,eax`）：失败/成功目标 0x445589/0x44558E 经反汇编确认，容量计数=普通占用槽+byte_9DF887（鲁肃路径）与描述一致；
- cave 保留区 [0x680,0x800)、SLOTS_OFFSET=0x7A0、容量 cave 0x7B0 与 budget=2048 边界校验通过（脚本内亦有运行时校验）。

### 3.5 patch_bytes 语义抽查（全部符合原版逻辑）

| 补丁 | 结论 |
|---|---|
| broke_weapon_fix | LEA 链 ×2→×3→×5（30x/10=-300%）去末级变 6x/10=-30%，修复破兵不还击的负伤害 BUG，编码逐字节核对正确 |
| lusu_intel_duration_x4_fix | 两处替换编码复核：`lea→shl 2`、ModRM 0x82→0x8A（`mov [edx+disp],al→cl`）、0x80→0xA3（moffs16 dx→ax），地址表达式不变、仅值 ×5→×4 |
| checkitem_unsigned_fix | 4 处 jg/jge/jl/jle→ja/jae/jb/jbe，位移不变；[0,32767] 语义不变，仅修复 ≥32768 金钱判定 |
| team_member_limit / check_team / attribute_char_limit_unlock | 上限解除正确；attr 保留下界 jl（维持 a1=-1 全队递归并拦截非法负 ID），与注释的 0xC8 imm8 符号扩展行为一致 |
| no_enemy | NOP je → 恒走 `xor eax,eax; ret`，与 decompile `if (dword_755C80 & 4) return 0` 语义吻合 |
| skim_fst_dlg | rel32=0x60 精确落在 sub_403CC8（AVI 跳过/状态推进），递归推进至 Resume 线程，无死循环 |
| shanhai_map_unlock | 0x755B58（当前场景，sub_40C044 写入）→ 0x755B5C（事件场景，sub_40C7CC 写入），语义核实 |
| enter_key_item_fix | NOP 掉 sub ecx,13 后的 je，禁用背包 ENTER；孝谈版经 profile_rules skip |
| skill_scan_bound | 350→344，对应 WarPC 记录内技能熟练度字节区实际长度，3 处命中全改 |
| demon_general_effect | 仅改我方初始化循环 `*v4=0→0x4000`（sub_4307CC 第一循环），敌方循环不受影响 |
| battle_treasure_reveal / enemy_info_reveal | 一次性初始化写入（byte_952942=1 / byte_95294E=7），等价永久技能效果 |
| battle_writeback / gold_display | movsx→movzx，修复 ID≥128/金钱≥32768 的符号扩展问题 |
| disable_pface_jvg | 5 处 jle→jmp（位移不变），不触碰 sub_4524F0 本体 |
| tkdefunit_count | **关键核查**：缓冲区分配 `shl edx,4` 运行时从 dword_753504 派生（反汇编确认），扩容后 memset/读文件同步放大，**不存在堆溢出** |

### 3.6 脚本补丁

| 脚本 | 结论 |
|---|---|
| tkact_expand | value_scan 命中数核对无误（基址 4 处/大小 1 处）；失败即整体报错，不半程回退 |
| tkkon_expand | 基址 19 处、大小 1 处、派生引用仅 1 处（0x44353F，即 4434BC.c 的 word_9D069E 列引用，与注释一致）；E8/E9 rel32 巧合排除逻辑正确；基于补丁前快照扫描派生引用，避免误读已改写字节 |
| save_entry_check_fix | sub_4C33FC 实际入口字节 `80 7B 0C 00 | 74 07` 与脚本处理分支（je short→jmp short）吻合 |
| summon_extend | 见 3.4 |
| xiaotan_disable_companion | `call ShellExecuteA`→`add esp,0x18+2×NOP`，6 参数 cdecl 栈平衡正确；仅 xiaotansanguo3 profile 生效 |

### 3.7 孝谈版专属补丁（原版不可验证，编码审查通过）

- **xiaotan_defend_glow**：`mov dword[eax*2+0x9DF7C2],7530h`→`or dword[eax*2+0x9DF7C2],1000h`，9 字节同长，ModRM/SIB 编码正确；
- **xiaotan_gambling_unlock**：NOP×6 化 cave 内 `jz 进入等级门`，模式与注释声明的 0xA7D154 指令序列一致；
- 三者均由 profile_rules 控制（`_default: skip`），原版零影响。

---

## 四、运行时/长期稳定性评估（"运行时间长后失效"专项）

1. **Cave 内存不会被游戏踩坏**：cave 区是启动时对游戏进程一次性 VirtualAllocEx 的独立 RWX 页（budget=2048），游戏逻辑无任何写入该区的通路，不存在随时间失效的机制。全补丁启用时自动布局水位 **0x662**（与 summon_extend 注释声明一致），与保留区 [0x680,0x800) 不冲突。⚠️ **唯一约束：水位距 0x680 仅 30 字节余量，未来新增大体积自动布局 cave 补丁前必须复核**（summon_extend 为硬编码区，不参与 CaveLayout 仲裁）。
2. **旧模式（autolayout_cave=false）隐患**：war_hp_mp_bars 与 summon_exp_jp_accumulation_fix 无 `cave_offset`，旧模式下均落 0 与 awk_sprite 冲突；当前默认自动布局无此问题。
3. **句柄/内存泄漏**：全部脚本 OpenProcess 均成对 CloseHandle（finally）；VirtualAllocEx 缓冲（cave/WarPC/tkact/tkkon/新角色备份）生命周期=游戏进程，随进程退出由系统回收，属有意设计，无累积泄漏。
4. **重复应用安全**：补丁写入后原特征码即失效，重复应用走"匹配数≠预期→跳过"安全分支，不会二次破坏。
5. **WarPC 扩容与 cave 顺序正确**：`_allocate_warpc_buffer`（得到新基址）→ `_apply_patches`（cave 按新基址重定位 0x757F08 占位符）→ `expand_warpc_buffer`（改写代码引用）。新缓冲区前有 0x10000 保护页，兜住 history_text/awk 等 cave 的 WarPC[-1] 边界读取。
6. **Hook 冲突防护**：HookTable 内部登记 + E8/E9 外部 MOD 检测已就位；`hook_conflict_action`（override/skip）配置合理（war_hp_mp_bars 为 skip，其余 override）。
7. **value_scan 误伤防护**：WarPC/tkact/tkkon 重定位均排除 E8/E9 rel32 巧合匹配与 MOD 额外段；tkkon 派生引用扫描实测仅 1 处合理命中。

---

## 五、修复清单（全部已完成）

| # | 优先级 | 补丁 | 处理 | 状态 |
|---|---|---|---|---|
| 1 | 高 | save_stream_error_fix | 补 `expect_count: 2`，注释写明读档侧 sub_41C120 + 存档侧 sub_41D9AC 双目标依据 | ✅ |
| 2 | 中 | awk_sprite_cave / awk_sprite_cave2 / war_mustchar_fallback | fallback_rva 改为 `0x309A6` / `0x31162` / `0x30895` | ✅ |
| 3 | 低 | gold_display | 补 `expect_count: 1` | ✅ |
| 4 | 可选 | gold_limit | 新增第三锚点（imm16 宽度，后缀 EB 排除场景赠金）+ 引擎 `value_size` 支持 | ✅ |
| 5 | 可选 | weapon_cause_mask_hook | `build_cave_template` 新增 rec_count 动态索引上限（未扩容保持原版 143） | ✅ |
| 6 | 备忘 | 新增 cave 补丁时 | 自动布局水位 0x662 距 summon_extend 保留区 0x680 仅 30 字节余量，先核算再添加 | ⚠️ 长期约束 |

---

## 六、修复记录（2026-08-25）

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `patches/save_stream_error_fix/patch.json` | 补 `expect_count: 2`；注释/desc 写明双命中目标（读档侧 sub_41C120、存档侧 sub_41D9AC）及调用链依据 |
| `patches/awk_sprite_cave/patch.json` | fallback_rva `0x43CA72` → `0x309A6` |
| `patches/awk_sprite_cave2/patch.json` | fallback_rva `0x43CA8D` → `0x31162` |
| `patches/war_mustchar_fallback/patch.json` | fallback_rva `0x430895` → `0x30895` |
| `patches/gold_limit/patch.json` | 新增第三锚点 `66 C7 05 82 68 75 00 30 75 EB`（value_offset=7, value_size=2, expect_value=0x7530）；desc 同步更新 |
| `patches/gold_display/patch.json` | 补 `expect_count: 1` |
| `core/config_loader.py` | PatchDef 新增 `value_size: int = 4` 字段 |
| `core/tkspatch_loader.py` | 解析顶层与 patterns 条目内的 `value_size`；`_note` 纳入 _extra 保留键 |
| `core/patch_engine.py` | ① `apply_patch_imm32_by_pattern` 支持 value_size=2/4（imm16 用无符号 `<H` 打包，范围校验 0..0xFFFF）；② 新增 `_WEAPON_CAP_OLD` 常量，`build_cave_template` 增加 `rec_count` 参数，对 weapon_cause_mask 同长替换索引上限；③ `apply_cave_hook` 计算 rec_count（未扩容钳制 ≥143 保持原版语义）并传入 |

### 回归验证（tks_launcher_gui/test_fix_regression.py，针对真实原版 TKS.exe 映像）

1. 58/58 个 patch.json 全部可被 `parse_patch_dict` 正常解析；
2. save_stream_error_fix：命中 2 处（0x1C12B/0x1D9B7）与 `expect_count=2` 一致；
3. 三个修正后的 fallback_rva 均落在 code_buf 范围内，且回退位置字节与各自 hook_pattern 匹配；
4. gold_limit 在模拟进程写入下：3 处锚点各命中 1 次；第三锚点为 **2 字节**写入 @0x40CE66，写入后 `66 C7 05 82 68 75 00 FF FF EB` 的 EB 跳转完好；sub_411E84 @0x412372 场景赠金未被触碰；
5. weapon_cause_mask：rec_count=None/143/200/220 分别生成 `cmp eax,143/143/200/220`，模板长度恒为 98 字节（不影响 CaveLayout）；
6. 项目既有单测 23/23 通过（test_shot.py 为手动截图工具，非单测，其导入报错为历史遗留，与本次改动无关）。

### 修复过程新增的事实核查（未臆测，均有逆向依据）

- **sub_41D9AC 归属**：调用方 sub_41D750/sub_41DAC4 ← sub_41CE10；sub_41CE10 与存档列表渲染 sub_41AB94 共享调用方 0x42131C/0x426164，确认为存档侧流检查；
- **0x412372 处的 `mov word[756882],0x7530`**：位于 sub_411E84，前置条件为当前场景 dword_755B58 ∈ {0x12,0x19,0x1F}，属剧情场景赠金（重置为 30000），非上限钳制，**不修改**；
- **else 钳制指令实际为 imm16**（`66 C7 05 ... 30 75` @0x40CE5F），因此引擎必须支持 2 字节写入，否则 4 字节写会破坏紧邻的 `EB 16` 跳转。

---

## 附录：本次验证涉及的关键地址速查

| 函数 | 起始 VA | 相关补丁 |
|---|---|---|
| sub_40DA00 TeamMember | 0x40DA00 | team_member_limit / routing / clear_slot0 / leave_slot0 |
| sub_40E11C Attribute | 0x40E11C | attribute_char_limit_unlock |
| sub_40E4E4 CheckItem | 0x40E4E4 | checkitem_unsigned_fix / xiaotan_gambling_unlock |
| sub_40E65C CheckTeam | 0x40E65C | check_team |
| sub_40E88C CheckMember | 0x40E88C | checkmember_level_redirect |
| sub_40CE30 AddItem/金钱 | 0x40CE30 | gold_limit |
| sub_4307CC PlaceUnits | 0x4307CC | demon_general_effect / war_mustchar_fallback / awk_sprite |
| sub_431094 召唤分配 | 0x431094 | summon_extend / awk_sprite_cave2 |
| sub_43B7FC 战后结算 | 0x43B7FC | exp_bonus / exp_cap / exp_lock |
| sub_4400DC 战斗核心 | 0x4400DC | weapon_cause_mask_hook / hp_cmp_unsigned_fix / summon_exp_jp / drop_probability |
| sub_4434BC 动画执行 | 0x4434BC | duel_counter_self_fix |
| sub_4458B0 技能分派 | 0x4458B0 | duel_self_target_fix / lusu_intel_duration_x4_fix |
| sub_444BB0 召唤检查 | 0x444BB0 | summon_table / summon_extend |
