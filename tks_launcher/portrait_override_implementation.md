# 战斗头像覆盖功能实现文档

## 概述

在 TKS 游戏战斗中，通过 WarPC.dat 的 WORD[261] 字段允许为角色指定自定义头像精灵 ID。当 WORD[261] != 0 时，使用该值作为头像精灵；否则沿用原始逻辑（WORD[1] + 211）。

本文档记录从逆向工程分析到最终实现完毕的完整过程，包括踩坑记录和最终验证通过方案。

---

## 1. 背景知识

### 1.1 关键数据结构

| 数据 | 地址/偏移 | 说明 |
|---|---|---|
| WarPC 基址 | `0x757F08` | 143 条记录，每条 1054 字节 |
| WORD[1] | WarPC + 2 | 原始头像值（精灵 ID = 此值 + 211） |
| WORD[260] | WarPC + 520 | 战斗形象自定义（AwkSprite） |
| WORD[261] | WarPC + 522 | 头像覆盖值（本功能使用） |
| 头像缓存数组 | `0x757F0A` | 紧凑 WORD 数组，portrait[i] = `[0x757F0A + i*1054]` |
| 队伍数组 | `0x75688C` | 6 个 WORD，存储当前队伍的角色 ID |

### 1.2 关键函数

- `sub_41762C`（VA `0x41762C`）：角色属性/头像渲染函数
  - 被 `sub_42131C` 和 `sub_4240B8` 调用
  - 包含两个头像渲染路径
- `sub_4307CC`：AwkSprite 战斗形象渲染函数

### 1.3 头像渲染代码路径

**PATH1（选中队员，大图）：**
```
VA 0x417A48: mov ax, [ecx*2 + 0x757F0A]   ; 从头像缓存读取原始值
VA 0x417A50: add ax, 0xD3                 ; +211 得到精灵 ID
VA 0x417A54: push eax                     ; 压栈（5 字节）
```
RVA = VA - ImageBase(0x400000) = **0x17A50**

**PATH2（非选中队员，小图）：**
```
VA 0x417E14: mov dx, [eax*2 + 0x757F0A]   ; 从头像缓存读取原始值
VA 0x417E1A: add dx, 0xD3                 ; +211 得到精灵 ID
VA 0x417E1F: push edx                     ; 压栈（6 字节）
```
RVA = **0x17E1A**

### 1.4 寄存器语义（已验证）

| Hook 点 | 寄存器 | 含义 |
|---|---|---|
| PATH1 (0x17A50) | `AX` | 原始头像值（WORD[1]） |
| PATH1 (0x17A50) | `ECX` | **角色索引 × 527**（ECX×2 = charID×1054） |
| PATH2 (0x17E1A) | `DX` | 原始头像值 |
| PATH2 (0x17E1A) | `EAX` | **角色索引 × 527** |

> **关键推导**：`527 = 1054/2`。ECX×2 = charID×527×2 = charID×1054 = WarPC 记录字节偏移。

---

## 2. 实现方案

### 2.1 方案选型

| 方案 | 描述 | 结论 |
|---|---|---|
| 静态补丁 `add→add,0` | 将 +211 改为 +0，预注入 WORD[2] | **废弃**：该函数被多处调用，非 WarPC 数据源也走此路径 |
| Wrap Cave | hook `call sub_41762C`，调用前后 swap WORD[2] | 可行但 cave 过大（200+ 字节），栈传参复杂 |
| **内联 Cave（采用）** | 直接 hook `add ax/dx, 0xD3` 处，动态读取 WORD[261] | 简洁（46/47 字节），与 AwkSprite 模式一致 |

### 2.2 Cave 汇编实现

#### PATH1 Cave（46 字节）

```asm
; Hook at RVA 0x17A50, replaces: 66 05 D3 00 50 (5B)
; Entry: AX = raw portrait, ECX = char_idx * 527

push eax                     ; [esp+0] = raw portrait
push ecx                     ; [esp+4] = char_idx * 527
push edx                     ; [esp+8] = scratch

; Compute WarPC record address
mov eax, ecx                 ; eax = char_idx * 527
add eax, eax                 ; eax = char_idx * 1054
add eax, 0x757F08            ; eax = WarPC record base

; Read WORD[261] at offset 0x20A (522)
movzx eax, word [eax+0x20A]
test ax, ax
jnz .override               ; WORD[261] != 0 → use override

; === Normal path (WORD[261] == 0) ===
pop edx                      ; restore
pop ecx                      ; restore
pop eax                      ; restore raw portrait
xchg ecx, [esp]              ; ecx = ret_addr (steal from stack)
add ax, 0xD3                 ; original +211
push eax                     ; push result
push ecx                     ; push ret_addr
ret                          ; return, caller sees result at [esp]

; === Override path (WORD[261] != 0) ===
.override:
add esp, 8                   ; discard edx, ecx
pop edx                      ; discard saved eax
xchg eax, [esp]              ; eax = ret_addr, [esp] = WORD[261]
push eax                     ; push ret_addr
ret                          ; return, caller sees WORD[261] at [esp]
```

**字节序列：**
```
50 51 52 8B C1 03 C0 05 08 7F 75 00 0F B7 80 0A 02 00 00
66 85 C0 75 0D 5A 59 58 87 0C 24 66 05 D3 00 50 51 C3
83 C4 08 5A 87 04 24 50 C3
```

#### PATH2 Cave（47 字节）

```asm
; Hook at RVA 0x17E1A, replaces: 66 81 C2 D3 00 52 (6B)
; Patch: E8 <off32> 90 (call 5B + NOP 1B = 6B)
; Entry: DX = raw portrait, EAX = char_idx * 527

push edx                     ; [esp+0] = raw portrait
push ecx                     ; [esp+4] = scratch
push eax                     ; [esp+8] = char_idx * 527

; Compute WarPC record address from EAX
add eax, eax                 ; eax = char_idx * 1054
add eax, 0x757F08            ; eax = WarPC record base

movzx eax, word [eax+0x20A]  ; WORD[261]
test ax, ax
jnz .override

; === Normal path ===
pop eax                      ; restore char_idx*527
pop ecx                      ; restore scratch
pop edx                      ; restore raw portrait
xchg ecx, [esp]              ; ecx = ret_addr
add dx, 0xD3                 ; original +211
push edx                     ; push result
push ecx                     ; push ret_addr
ret

; === Override path ===
.override:
movzx edx, ax                ; edx = WORD[261] (zero-extend)
add esp, 8                   ; discard eax, ecx
pop ecx                      ; discard saved edx
xchg edx, [esp]              ; edx = ret_addr, [esp] = WORD[261]
push edx                     ; push ret_addr
ret
```

**字节序列：**
```
52 51 50 03 C0 05 08 7F 75 00 0F B7 80 0A 02 00 00
66 85 C0 75 0D 58 59 5A 87 0C 24 66 83 C2 D3 52 51 C3
0F B7 D0 83 C4 08 59 87 14 24 52 C3
```

### 2.3 Cave 内存布局

```
cave + 0   : AwkSprite Cave    (51 字节)
cave + 64  : PortraitCave1     (46 字节)
cave + 128 : PortraitCave2     (47 字节)
总分配大小  : 256 字节
```

### 2.4 数据注入

`InjectWarPCData` 函数将 WarPC.dat 中的以下字段写入游戏内存：

| 字段 | WarPC 偏移 | 游戏内存地址 |
|---|---|---|
| WORD[260] | +520 | `0x757F08 + i*1054 + 520` |
| WORD[261] | +522 | `0x757F08 + i*1054 + 522` |

仅注入非零值，不影响原始数据。

---

## 3. 踩坑记录

### 3.1 错误的 RVA 地址（致命）

**错误**：最初使用 RVA `0x37A50` / `0x37E1A`

**原因**：地址计算错误（来源不明）

**实际验证**：通过内存 dump `00401000--004E6000.txt` 查看：
```
VA 0x437A50: 66 83 3D 1A 09 9E 00 08  → cmp word [0x9E091A], 8
```
完全不是 `add ax, 0xD3`！

**正确地址**：搜索 `66 05 D3 00 50` 特征码找到：
```
VA 0x417A50: 66 05 D3 00 50  → RVA 0x17A50 ✓
VA 0x417E1A: 66 81 C2 D3 00 52  → RVA 0x17E1A ✓
```

**教训**：hook 前务必用运行时 DIAG dump 或反汇编验证原始指令字节。

### 3.2 PATH2 字节长度错误（卡死）

**错误**：PATH2 hook 写 5 字节（E8 + off32），但原始代码 6 字节

**后果**：残留 `52`（push edx）在 cave 返回后执行，栈破坏 → 战斗卡死

**修复**：补 NOP → `E8 <off32> 90`（6 字节）

### 3.3 寄存器倍率错误（黑屏）

**错误**：假设 ECX/EAX = 角色索引，直接 `imul eax, 1054`

**实际**：ECX/EAX = 角色索引 × 527

**推导过程**：
1. 反编译代码：`word_757F0A[527 * *i] + 211`
2. 对应汇编：`mov ax, [ecx*2 + 0x757F0A]`
3. `ecx*2 + 0x757F0A` 要等于 `0x757F0A + i*527*2`
4. ∴ `ecx = i * 527`

**后果**：对已缩放的 ECX 再 ×1054，地址 = `i*527*1054`，远超 WarPC 数组边界 → 读到垃圾数据 → 随机非零值触发错误 override → 黑屏

**修复**：用 `add eax, eax`（×2）替代 `imul eax, 1054`，因 `ecx*2` 已经等于 `i*1054`

### 3.4 栈平衡处理

Cave 替换了原始 `push eax/edx` 指令，必须在返回前保证：
- `[esp]` = 结果值（精灵 ID）
- `ret` 弹出返回地址后控制流正确

**实现方法**：
1. 弹出所有保存的寄存器
2. `xchg ecx, [esp]`：将 ret_addr 从栈顶换到 ECX
3. `push eax/edx`：压入结果
4. `push ecx`：压回 ret_addr
5. `ret`：弹出 ret_addr → 调用者看到结果在 `[esp]`

### 3.5 `js` 跳转偏移错误（早期版本）

在尝试队伍数组查找方案时，`js .no_override` 的跳转偏移计算错误（`0x1E` 应为 `0x18`），导致跳过 3 个 `pop` 指令直接执行 `add`，栈未恢复即返回 → 卡死。

**教训**：跳转偏移必须精确计算：`offset = target - (jmp_insn_addr + 2)`

---

## 4. 补丁总览

| # | RVA | 类型 | 大小 | 说明 |
|---|---|---|---|---|
| 1 | 0xDA15 | 静态 | 2B | TeamMember: cmp 0x1E→0xC8, jg→ja |
| 2 | 0xE6C1 | 静态 | 2B | CheckTeam: cmp 0x1E→0xC8, jle→jbe |
| 3 | 0x31165 | 静态 | 1B | AwkSprite PATH2: +12→+0 |
| 4 | cave+0 | 动态 | 51B | AwkSprite PATH1 cave |
| 5 | 0x309A6 | 动态 | 5B | AwkSprite hook→cave |
| 6 | cave+64 | 动态 | 46B | PortraitCave1 (selected) |
| 7 | 0x17A50 | 动态 | 5B | Portrait PATH1 hook |
| 8 | cave+128 | 动态 | 47B | PortraitCave2 (non-selected) |
| 9 | 0x17E1A | 动态 | 6B | Portrait PATH2 hook (call+NOP) |

---

## 5. 验证方法

### 5.1 日志解读

启动器输出 `tks_launcher.log`：
```
ok=True cave=0x... base=0x00400000
awk_cave=[50-51-...] awk_hook=[E8-...]
p1_cave=[50-51-52-8B-C1-03-C0-05-...] p1_hook=[E8-...]
p2_cave=[52-51-50-03-C0-05-...] p2_hook=[E8-...-90]
W261[85]=0x0041 W261[86]=0x0042
team=[0,-1,-1,-1,-1,-1,]
patches=9 inject_w260=2 w261=2
```

关键检查项：
- `awk_cave` 首字节 `50`、`p1_cave` 首字节 `50`、`p2_cave` 首字节 `52` → cave 正确写入
- `p2_hook` 末字节 `90` → PATH2 NOP 补齐正确
- `W261[85]` 等 → WORD[261] 注入成功
- `team=[...]` → 队伍配置正确

### 5.2 DIAG 预补丁转储

```csharp
// 打补丁前输出 hook 点原始字节
[DIAG] PATH1@0x17A50 pre: [66-05-D3-00-50-...]
[DIAG] PATH2@0x17E1A pre: [66-81-C2-D3-00-52-...]
```

确认首 5/6 字节与预期一致后再打补丁。

---

## 6. WarPC.dat 编辑方式

在 WarPC 编辑器中为角色设置 WORD[261]（头像覆盖）：
- 值为 0：使用默认头像（WORD[1] + 211）
- 值非 0：直接作为精灵 ID 使用

例如：设置 WORD[261] = 0x41（65），则战斗中将显示精灵 ID 65 对应的头像。

---

## 7. 相关文件

| 文件 | 说明 |
|---|---|
| `tks_launcher.cs` | C# 启动器（主要实现） |
| `TKSLauncher.exe` | 编译后可执行文件 |
| `runtime_patcher.py` | Python 等效实现 |
| `portrait_override_implementation.md` | 本文档 |

---

## 8. 参考的反编译源

| 文件 | 内容 |
|---|---|
| `decompile/41762C.c` | 头像渲染函数 sub_41762C |
| `memory/00401000--004E6000.txt` | .text 段内存 dump |
| `function_index.txt` | 函数索引 |

关键反编译代码（sub_41762C 第 68 行）：
```c
word_757F0A[527 * *i] + 211
```
验证了寄存器缩放因子 527（= 1054/2）的正确性。
