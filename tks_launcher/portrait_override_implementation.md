# 战斗头像覆盖功能实现文档

## 概述

在 TKS 游戏战斗和队伍菜单中，通过 WarPC.dat 的 WORD[261] 字段为角色指定自定义头像精灵 ID。当 WORD[261] != 0 时，使用该值作为头像精灵；否则沿用原始逻辑（WORD[1] + 211）。

本文档记录从逆向工程分析到最终实现完毕的完整过程。

---

## 1. 背景知识

### 1.1 数据结构

| 数据 | 地址/偏移 | 说明 |
|---|---|---|
| WarPC 基址 | `0x757F08` | 143 条记录，每条 1054 字节 |
| WORD[1] | WarPC + 2 | 原始头像值（精灵 ID = 此值 + 211）— **不可修改** |
| WORD[260] | WarPC + 520 | 战斗形象自定义（AwkSprite） |
| WORD[261] | WarPC + 522 | 头像覆盖值（本功能使用） |
| 队伍数组 | `0x75688C` | 6 个 WORD，存储当前队伍的角色 ID |

### 1.2 关键函数

- **`sub_41762C`**（VA `0x41762C`）：角色属性/头像渲染函数，被 `sub_42131C` 和 `sub_4240B8` 调用
- **`sub_4307CC`**：AwkSprite 战斗形象渲染函数

### 1.3 头像渲染代码（已验证）

**PATH1（选中队员，大图）：**
```
VA 0x417A48: mov ax, [ecx*2 + 0x757F0A]   ; 加载原始头像值 WORD[1]
VA 0x417A50: add ax, 0xD3                 ; +211 → 精灵 ID
VA 0x417A54: push eax                     ; 压栈传递参数（共 5 字节）
```
RVA = VA - 0x400000 = **0x17A50**，共 5 字节。

**PATH2（非选中队员，小图）：**
```
VA 0x417E14: mov dx, [eax*2 + 0x757F0A]   ; 加载原始头像值
VA 0x417E1A: add dx, 0xD3                 ; +211 → 精灵 ID
VA 0x417E1F: push edx                     ; 压栈传递参数（共 6 字节）
```
RVA = **0x17E1A**，共 6 字节。

### 1.4 寄存器语义（已验证）

| Hook 点 | 寄存器 | 值 |
|---|---|---|
| PATH1 `0x17A50` | `AX` | 原始头像值（WORD[1]） |
| PATH1 `0x17A50` | `ECX` | `角色索引 × 527`（ECX×2 = charID×1054） |
| PATH2 `0x17E1A` | `DX` | 原始头像值 |
| PATH2 `0x17E1A` | `EAX` | `角色索引 × 527` |

> **推导**：`527 = 1054/2`。ECX×2 = charID×527×2 = charID×1054 = WarPC 记录字节偏移。

---

## 2. 最终实现方案

### 2.1 方案概述

使用**内联 Cave** 在每个 `add ax/dx, 0xD3` 指令处 hook，动态读取 WORD[261]：
- WORD[261] != 0 → 直接作为精灵 ID
- WORD[261] == 0 → 执行原始 `+211` 逻辑

**关键设计**：两个路径（normal / override）使用**完全相同的出口代码**，消除路径差异。

### 2.2 PortraitCave1（PATH1, 41 字节）

Hook 地址：RVA `0x17A50`，替换 `66 05 D3 00 50`（5B）。

```asm
push eax                     ; [esp+0] = raw portrait
push ecx                     ; [esp+4] = char_idx * 527
push edx                     ; [esp+8] = scratch

; Compute WarPC record address from ECX
mov eax, ecx                 ; eax = char_idx * 527
add eax, eax                 ; eax = char_idx * 1054
add eax, 0x757F08            ; eax = WarPC record base

; Read WORD[261] at offset 0x20A (522)
movzx eax, word [eax+0x20A]
test ax, ax
jnz .shared_exit             ; WORD[261] != 0 → use as result

; === Normal path (WORD[261] == 0) ===
mov eax, [esp+8]             ; read raw portrait from saved_eax slot
add ax, 0xD3                 ; +211

; === Shared exit (both paths identical) ===
.shared_exit:
add esp, 8                   ; discard edx, ecx
pop edx                      ; discard saved_eax
xchg eax, [esp]              ; [esp]=result, eax=ret_addr
jmp eax                      ; return, no stack leak
```

**字节序列：**
```
50 51 52 8B C1 03 C0 05 08 7F 75 00 0F B7 80 0A 02 00 00
66 85 C0 75 08 8B 44 24 08 66 05 D3 00 83 C4 08 5A 87 04 24 FF E0
```

### 2.3 PortraitCave2（PATH2, 42 字节）

Hook 地址：RVA `0x17E1A`，替换 `66 81 C2 D3 00 52`（6B）。Patch 为 `E8 <off32> 90`（5B call + 1B NOP）。

```asm
push edx                     ; [esp+0] = raw portrait
push ecx                     ; [esp+4] = scratch
push eax                     ; [esp+8] = char_idx * 527

; Compute WarPC record address from EAX
add eax, eax                 ; eax = char_idx * 1054
add eax, 0x757F08            ; eax = WarPC record base

movzx eax, word [eax+0x20A]  ; WORD[261]
test ax, ax
jnz .shared_exit             ; WORD[261] != 0 → use as result

; === Normal path ===
mov eax, [esp+8]             ; read raw portrait from saved_edx slot
add ax, 0xD3                 ; +211

; === Shared exit ===
.shared_exit:
movzx edx, ax                ; edx = result (zero-extend for PATH2)
add esp, 8                   ; discard eax, ecx
pop ecx                      ; discard saved_edx
xchg edx, [esp]              ; [esp]=result, edx=ret_addr
jmp edx                      ; return, no stack leak
```

**字节序列：**
```
52 51 50 03 C0 05 08 7F 75 00 0F B7 80 0A 02 00 00
66 85 C0 75 08 8B 44 24 08 66 05 D3 00 0F B7 D0 83 C4 08 59 87 14 24 FF E2
```

### 2.4 Cave 内存布局

```
cave + 0   : AwkSprite Cave    (51 字节)
cave + 64  : PortraitCave1     (41 字节)
cave + 128 : PortraitCave2     (42 字节)
总分配      : 256 字节
```

### 2.5 数据注入

`InjectWarPCData` 仅注入 WORD[260] 和 WORD[261] 到 WarPC 内存，**不修改 WORD[1]**。Cave 在运行时动态读取 WORD[261]。

| 字段 | WarPC 偏移 | 游戏内存地址 | 条件 |
|---|---|---|---|
| WORD[260] | +520 | `0x757F08 + i*1054 + 520` | 非零 |
| WORD[261] | +522 | `0x757F08 + i*1054 + 522` | 非零 |

---

## 3. 补丁总览

| # | RVA | 类型 | 大小 | 说明 |
|---|---|---|---|---|
| 1 | 0xDA15 | 静态 | 2B | TeamMember: cmp 0x1E→0xC8, jg→ja |
| 2 | 0xE6C1 | 静态 | 2B | CheckTeam: cmp 0x1E→0xC8, jle→jbe |
| 3 | 0x31165 | 静态 | 1B | AwkSprite PATH2: +12→+0 |
| 4 | cave+0 | 动态 | 51B | AwkSprite PATH1 cave |
| 5 | 0x309A6 | 动态 | 5B | AwkSprite hook→cave |
| 6 | cave+64 | 动态 | 41B | PortraitCave1 (selected) |
| 7 | 0x17A50 | 动态 | 5B | Portrait PATH1 hook |
| 8 | cave+128 | 动态 | 42B | PortraitCave2 (non-selected) |
| 9 | 0x17E1A | 动态 | 6B | Portrait PATH2 hook (call 5B + NOP 1B) |

---

## 4. 踩坑记录

### 4.1 错误的 RVA 地址

**错误**：最初使用 RVA `0x37A50` / `0x37E1A`。

**验证**：通过内存 dump `00401000--004E6000.txt` 查看：
```
VA 0x437A50: 66 83 3D 1A 09 9E 00 08  → cmp word [0x9E091A], 8
```
完全不是 `add ax, 0xD3`。Hook 在完全不相关的代码上。

**正确地址**：搜索特征码 `66 05 D3 00 50` 找到：
```
VA 0x417A50 → RVA 0x17A50 ✓
VA 0x417E1A → RVA 0x17E1A ✓
```

### 4.2 PATH2 字节长度错误

**错误**：PATH2 hook 写 5 字节，但原始代码 6 字节（`66 81 C2 D3 00` + `52`）。

**后果**：残留 `52`（push edx）在 cave 返回后执行，栈破坏 → 战斗卡死。

**修复**：补 NOP → `E8 <off32> 90`（6 字节）。

### 4.3 寄存器倍率错误

**错误**：假设 ECX/EAX = 角色索引，使用 `imul eax, 1054`。

**实际**：ECX/EAX = 角色索引 × 527。

**后果**：对已缩放的 ECX 再 ×1054 → 地址超出 WarPC 数组 → 读垃圾数据。

**修复**：用 `add eax, eax`（×2）替代 `imul eax, 1054`，因为 ECX×2 已等于 charID×1054。

### 4.4 栈泄漏（push/push/ret 模式）

**错误**：normal path 使用 `push eax; push ecx; ret` 返回，每次调用在栈上残留 4 字节。

**后果**：队伍菜单渲染多个角色后栈溢出 → 黑屏。

**修复**：改用 `xchg eax, [esp]; jmp eax` 模式，零栈泄漏。

### 4.5 路径出口不一致

**错误**：normal 和 override 两条路径的出口代码不同：
```
Normal:   3 pops → add → xchg → jmp
Override: add esp,8 → pop → xchg → jmp
```

**后果**：入口栈相同但出口操作不同，导致 normal path 异常（黑屏），override path 正常。

**修复**：重构为共享出口。Normal path 不 pop 恢复 eax，而是从 `[esp+8]` 读取原始 portrait。两条路径使用完全相同的 `add esp,8; pop; xchg; jmp` 出口。

### 4.6 失败的方案：数据注入 WORD[1]

尝试过直接修改 WORD[1] = WORD[261] - 211（利用原始 +211 还原），但 WORD[1] 有自身正确的业务逻辑，不可修改。此方案被否决。

---

## 5. 验证方法

### 5.1 日志解读

`tks_launcher.log` 关键项：

```
awk_cave=[50-51-...] awk_hook=[E8-...]
p1_cave=[50-51-52-8B-C1-03-C0-...] p1_hook=[E8-...]
p2_cave=[52-51-50-03-C0-...] p2_hook=[E8-...-90]
W261[85]=0x0041 W261[86]=0x0042
team=[0,1,-1,-1,-1,-1,]
patches=9 inject_w260=2 w261=2
```

- `p2_hook` 末字节 `90` → PATH2 NOP 补齐正确
- `W261[85]=0x0041` → WORD[261] 注入成功
- `patches=9` → 全部 9 个补丁应用

### 5.2 DIAG 预补丁转储

打补丁前输出 hook 点原始字节，用于确认正确的指令地址：
```
[DIAG] PATH1@0x17A50 pre: [66-05-D3-00-50-...]
[DIAG] PATH2@0x17E1A pre: [66-81-C2-D3-00-52-...]
```

---

## 6. 相关文件

| 文件 | 说明 |
|---|---|
| `tks_launcher.cs` | C# 启动器（主要实现） |
| `TKSLauncher.exe` | 编译后可执行文件 |
| `runtime_patcher.py` | Python 等效实现 |
| `portrait_override_implementation.md` | 本文档 |

## 7. 参考的反编译源

| 文件 | 内容 |
|---|---|
| `disassembly/` | 函数级反汇编 |
| `decompile/41762C.c` | sub_41762C 反编译 |
| `memory/00401000--004E6000.txt` | .text 段内存 dump |
| `function_index.txt` | 函数索引导航 |
