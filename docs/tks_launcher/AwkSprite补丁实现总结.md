# AwkSprite 补丁完整实现总结

## 概述

游戏引擎在 `sub_4307CC` 中硬编码了角色武器精灵块的计算公式：我方 `WarPC索引+6`，敌方 `WarPC记录号+12`。新增角色（如 WarPC 85 颜良、86 文丑）改为我方后，武器精灵块号与预期不符。本补丁通过 hook + 动态分配可执行内存的方式，使武器精灵块号可由 WarPC.dat 的 WORD[260] 字段配置。

---

## 一、问题分析

### 1.1 硬编码公式

| 路径 | 代码位置 | 公式 | 示例（颜良 WarPC 85） |
|------|---------|------|---------------------|
| PATH 1 (玩家) | `sub_4307CC:120` | `武器块 = WarPC索引 + 6` | 85+6=91（期望87） |
| PATH 2 (敌方) | `sub_4307CC:236` | `武器块 = WarPC记录号 + 12` | 85+12=97（作为敌方时） |

### 1.2 需求

将公式改为：如果 WarPC 角色的 WORD[260] 字段非零，使用该值作为武器精灵块号；否则回退原公式。

---

## 二、配置字段

### 2.1 字段选型

经过 527 WORD 完整覆盖分析 + 反编译引用检查 + 内存 dump 交叉验证：

| 候选 | 字节偏移 | 验证结果 |
|------|---------|---------|
| WORD[267] | 534 | 反编译零引用，内存 dump 全零 → 可用 |
| WORD[260] | 520 | 反编译零引用，内存 dump 全零 → 可用 |

最终选用 **WORD[260]（字节偏移 520）**，WORD[261-262] 保留扩展。

### 2.2 编辑器集成

`warpc_editor.py` v1.3 的"核心属性→基本信息"中新增：

```
字段名:  awk_sprite_id
偏移:    520 (WORD[260])
标签:    战场图集索引（补丁专用）
说明:    战斗中Awk.JVG/Awt.JVG块号 — 配合运行时补丁使用
         0=使用原硬编码公式
         非0=补丁直接使用此值作为武器精灵块
```

---

## 三、补丁设计

### 3.1 Hook 策略

选择 hook `sub_4307CC` 中的 `cmp [ebp-6], 0` 指令，理由：

1. **在 `call sub_432668` 之后**——装备初始化已完成，`[ebp-6]` 中是稳定的 WarPC 索引
2. **5 字节指令**——与 `call rel32` 等长，替换不破坏任何跳转目标
3. **紧邻 `jnz` 分支**——cave 通过设置 ZF 标志控制后续分支走向

Hook 地址：**RVA `0x309A6`**（绝对地址 `0x4309A6`）

```
原始指令:  66 83 7D FA 00    cmp word [ebp-6], 0
替换为:    E8 XX XX XX XX    call cave
```

### 3.2 Cave 代码（51 字节）

```asm
; Hook: cmp [ebp-6],0 → call cave
; 入参: [ebp-6] = WarPC 索引 (v26)
; 出参: [ebp-6] 调整后的值, ZF 标志供后续 jnz 分支

    push eax                        ; 50
    push ecx                        ; 51
    movsx eax, word [ebp-6]         ; 0F BF 45 FA  — eax = WarPC索引
    test ax, ax                     ; 66 85 C0
    jz   .done                      ; 74 25  — 主角(v26=0)→跳过,ZF=1→走武器类型映射
    imul eax, 0x41E                 ; 69 C0 1E 04 00 00  — eax *= 1054
    add  eax, 0x757F08              ; 05 08 7F 75 00  — eax = &WarPC[index]
    movzx ecx, word [eax+0x208]     ; 0F B7 88 08 02 00 00  — ecx = WORD[260]
    test cx, cx                     ; 66 85 C9
    jnz  .use_custom                ; 75 04  — WORD[260]≠0 → 使用自定义值
    test eax, eax                   ; 85 C0  — WORD[260]=0 → ZF=0 → 走原+6公式
    jmp  .done                      ; EB 0A
.use_custom:
    sub  ecx, 6                     ; 83 E9 06  — 补偿原公式的+6
    mov  word [ebp-6], cx           ; 66 89 4D FA  — v26 = WORD[260]-6
    test cx, cx                     ; 66 85 C9  — ZF=0 (v26≠0) → jnz→add+6 → 最终=WORD[260]
.done:
    pop  ecx                        ; 59
    pop  eax                        ; 58
    ret                             ; C3
```

**逻辑流程图：**

```
cave 入口
  │
  ├─ [ebp-6]==0 (主角) ──→ ZF=1 → jnz 不跳 → 走武器类型映射（原逻辑）
  │
  ├─ WORD[260]==0 ──→ ZF=0 → jnz 跳 → +6 → 原公式
  │
  └─ WORD[260]≠0 ──→ [ebp-6]=WORD[260]-6 → ZF=0 → jnz 跳 → +6 → =WORD[260] ✓
```

### 3.3 动态内存分配

由于游戏二进制中无足够可执行空闲空间，使用 `VirtualAllocEx` 在目标进程中动态分配 **64 字节 PAGE_EXECUTE_READWRITE** 内存存放 cave 代码。

### 3.4 数据注入

启动器补丁后，从 `WarPC.dat` 文件 LZSS 解压，读取所有 143 个角色的 WORD[260]，将非零值通过 `WriteProcessMemory` 写入游戏内存 `0x757F08 + charID*1054 + 520`，确保即使游戏加载 WarPC.dat 时的数据未被更新也能生效。

---

## 四、完整补丁列表

| # | RVA | 大小 | 说明 |
|---|-----|------|------|
| 1 | `0xDA15` | 2B | TeamMember 上限 30→200 |
| 2 | `0xE6C1` | 2B | CheckTeam 上限同步 |
| 3 | `0x31165` | 1B | PATH2 +12→+0（敌方精灵块=记录号） |
| 4 | 动态 | 51B | Cave 代码体（VirtualAllocEx 分配） |
| 5 | `0x309A6` | 5B | Hook: `cmp [ebp-6],0` → `call cave` |

---

## 五、踩坑记录

| 问题 | 原因 | 解决 |
|------|------|------|
| 战斗白屏 | Cave 放在 `.text` 段尾的零填充区，实际不在可执行段 | 改用 `VirtualAllocEx` 动态分配 |
| 仍白屏 | Cave 跳转偏移算错，跳入指令中间 | 逐字节重算 `jz`/`jnz`/`jmp` 偏移 |
| 仍白屏 | Hook 在 `add [ebp-6],6` 处，前面的 `EB 05` 跳入 call 中间 | 改 hook 点到 `cmp [ebp-6],0` |
| 补丁不生效（洞穴写入正确） | Hook RVA 用了绝对地址 `0x4309A6` 而非 RVA `0x309A6`，写到了错误地址 `0x8309A6` | 改为正确的 RVA |
| 补丁不生效（逻辑） | 最初 cave 内部调用 `sub_432668` 的偏移混用绝对/相对地址 | 改 hook 点到 `sub_432668` 调用之后，cave 不需要内部调原函数 |

---

## 六、涉及文件

| 文件 | 作用 |
|------|------|
| `warpc_editor/warpc_editor.py` (v1.3) | 新增"战场图集索引"字段 (WORD[260]) |
| `warpc_editor/AwkJVG战斗武器精灵映射分析.md` | 战斗武器精灵映射完整逆向分析 |
| `warpc_editor/WarPC未使用字段分析_WORD260.md` | WORD[260] 字段选型分析 |
| `warpc_editor/NPC离队后回原位机制分析.md` | NPC 离队机制分析 |
| `tks_launcher/tks_launcher.cs` | C# 启动器（含 LZSS 解压、VirtualAllocEx、数据注入） |
| `tks_launcher/patch_config.json` | Python 补丁配置 |
| `tks_launcher/awk_sprite_patch_design.md` | 补丁设计文档（早期 cave 方案） |
| `tks_launcher/TKSLauncher.exe` | 编译好的启动器 |
| `tks_launcher/runtime_patcher.py` | Python 补丁工具（现有已应用补丁） |

---

## 七、使用方式

1. 在 `warpc_editor` 中设置目标角色的"战场图集索引"字段（WORD[260]）为期望的 Awk.JVG 块号
   - 如：颜良(WarPC 85) 设为 87，文丑(WarPC 86) 设为 88
   - 设为 0 则使用原公式 (索引+6)
2. 保存 WarPC.dat
3. 将 `TKSLauncher.exe` 放到游戏目录，双击运行
4. 启动器自动：应用代码补丁 → 分配 cave → 注入 WORD[260] 数据 → 退出
5. 启动新游戏，招募角色，进入战斗验证
