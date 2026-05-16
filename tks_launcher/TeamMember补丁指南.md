# TKS.exe 角色加入上限补丁 — 完整指南

## 概述

《三国赵云传》游戏引擎硬编码了 `TeamMember` 脚本命令的角色 ID 上限为 **30 (0x1E)**，导致 WarPC.dat 索引 31+ 的角色无法通过脚本加入队伍。

本文档记录从逆向分析、补丁开发、到最终用户分发的完整流程。

---

## 问题背景

### 现象

在 WarPC.dat 中新增角色（如索引 85），脚本中使用 `TeamMember(85,1)` 无法生效。而内置角色（如索引 5 许褚、索引 29）正常。

### 根因

两个函数硬编码了角色 ID 上限 `0x1E` (30)：

| 函数 | 地址 | 脚本命令 | 校验方式 |
|------|------|---------|---------|
| `sub_40DA00` | `0x40DA00` | TeamMember(ID, mode) | `if (a1 <= 0x1E)` — 入口校验 |
| `sub_40E65C` | `0x40E65C` | CheckTeam(type, ID, op) | `if (a2 > 0x1E)` — case 1 校验 |

`sub_40DA00` 入口校验为函数第一条可执行语句。`a1 > 0x1E` 时，整个函数体被跳过，不执行任何操作。

### 关键数据结构

| 项目 | 值 | 说明 |
|------|-----|------|
| 角色 ID 上限 | 0x1E (30) | 硬编码，已通过补丁改为 200 |
| 队伍槽数 | 6 | `word_75688C[6]`，槽 0 为主角 |
| 角色数据总量 | 143×1054=150722 字节 | `word_757F08[527×143]`，与 WarPC.dat 格式一致 |
| 空槽标记 | -1 (0xFFFF) | |

---

## 补丁方案

### 目标地址

需要修改两处比较指令，每处 2 字节：

| # | RVA | 函数 | 修改 | 说明 |
|---|-----|------|------|------|
| 1 | `0xDA15` | `sub_40DA00` | `1E 0F 8F` → `C8 0F 87` | `cmp imm8 30→200` + `jg→ja` |
| 2 | `0xE6C1` | `sub_40E65C` | `1E 7E` → `C8 76` | `cmp imm8 30→200` + `jle→jbe` |

### 核心技术细节：83h 操作码的符号扩展陷阱

x86 指令 `83h` 配合 `66h`（16 位操作数前缀）时，**imm8 会被符号扩展到 16 位**：

```
66 83 7D 08 C8    →  cmp word [ebp+8], 0xFFC8    ← 实际比较 -56！
```

`0xC8` 的 bit7=1，符号扩展后变成 `0xFFC8`（-56），而非预期的 `0x00C8`（200）。

对于 a1=85：`85 > -56` 为真 → `jg` 跳转 → 函数体被跳过。

**修复**：必须将条件跳转从有符号改为无符号：

| 指令 | 原值 | 改为 | 条件 |
|------|------|------|------|
| `jg` (有符号大于) | `0F 8F` | `0F 87` (`ja` 无符号大于) | `sub_40DA00` |
| `jle` (有符号小于等于) | `7E` | `76` (`jbe` 无符号小于等于) | `sub_40E65C` |

### 补丁后效果

- TeamMember 接受角色 ID 0–200（实际可用 0–142，对应 WarPC.dat 全部 143 个角色）
- CheckTeam 同步放宽至 200
- 队伍槽位仍为 6 个（独立限制，与 ID 上限无关）

---

## 使用方法

### 方式一：TKSLauncher.exe（推荐，无需 Python）

1. 将 `TKSLauncher.exe` 复制到游戏目录
2. 双击 `TKSLauncher.exe` 启动游戏
3. 启动器自动应用补丁后退出，游戏正常运行

**系统要求**：Windows 7+（.NET Framework 4.0 自带）

**编译**（从源码重建）：
```cmd
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /target:winexe /out:TKSLauncher.exe tks_launcher.cs
```

### 方式二：Python 脚本（开发/调试用）

**依赖**：Python 3.x（无需额外包）

```bash
# 自动启动 TKS.exe 并打补丁
python runtime_patcher.py

# 对已运行的进程打补丁（需先获取子进程 PID）
python runtime_patcher.py --pid <子进程PID>

# 验证补丁是否已生效（仅读取，不写入）
python runtime_patcher.py --verify

# 监控补丁是否被回退（检测 CopyMem-II 保护）
python runtime_patcher.py --watch
```

**补丁配置**：编辑 `patch_config.json`

```json
{
  "patches": [
    {
      "desc": "TeamMember: cmp 0x1E→0xC8, jg→ja (sub_40DA00)",
      "rva": "0xDA15",
      "data": "C8 87"
    },
    {
      "desc": "CheckTeam: cmp 0x1E→0xC8, jle→jbe (sub_40E65C)",
      "rva": "0xE6C1",
      "data": "C8 76"
    }
  ]
}
```

### 方式三：直接内存写入（诊断用）

```bash
# 验证角色数据和渲染是否正常
python team_diag.py --force-add 85

# 监控队伍数组变化
python team_diag.py
```

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `逆向工作区/runtime_patcher.py` | Python 运行时补丁工具 |
| `逆向工作区/runtime_dumper.py` | TKS.exe 内存 dump 工具（逆向用） |
| `逆向工作区/tks_launcher.cs` | C# 启动器源码 |
| `逆向工作区/TKSLauncher.exe` | 编译好的启动器（用户分发） |
| `逆向工作区/patch_config.json` | 补丁配置文件 |
| `逆向工作区/team_diag.py` | TeamMember 诊断工具 |
| `warpc_editor/TeamMember上限分析.md` | IDA 逆向分析文档 |
| `逆向工作区/runtime_dump/pe_dump_TKS.TMP0_pid11344_t2.exe` | 解密后的游戏 EXE dump |
| `运行时转储/` | IDA 反编译导出数据 |

---

## 技术细节

### 脚本派发流程

```
TKD.dat (文本) → sub_401E88 (MakeTalkText 编译器) → 字节码
                                                        ↓
                                                   dword_755A94
                                                        ↓
                                                  sub_40EBD4 (派发器)
                                                   case 45:
                                                        ↓
                                                  sub_40DA00 (TeamMember)
```

### 进程关系

```
TKS.exe (Armadillo 加密壳)
    ↓ CreateProcess
TKS.TMP0 (解密后的游戏进程)
    ↓ 代码注入 (Armadillo 循环解压)
完整游戏代码运行
```

- 补丁必须针对 **TKS.TMP0**（子进程），而非 TKS.exe
- 模块基址通常为 `0x00400000`
- 补丁地址 = 基址 + RVA

### CopyMem-II 说明

Armadillo 的 CopyMem-II 保护可能导致代码页在访问后重新加密，覆盖补丁。本游戏实测中，补丁写入后持续保持有效（60 秒监控无回退），确认无需重复打补丁。

### 队伍槽位限制

队伍槽位数组 `word_75688C[6]` 固定为 6 个，独立于角色 ID 上限。即使放宽 ID 上限，队伍仍最多容纳 6 人。如需增加队伍容量，需额外修改 `sub_40DA00` 中的 `while (v8 < 6)` 循环上限。

---

## 已知局限

1. **补丁在内存中生效**，关闭游戏后失效。每次启动需通过 Launcher 重新应用
2. **队伍槽位仍是 6 个**，放宽的只是角色 ID 范围
3. 补丁基于特定版本 dump 的 RVA。游戏版本更新后 RVA 可能变化，需重新确认地址
4. 如果后期发现其他硬编码限制（如 UI 渲染中的 ID 过滤），可追加补丁到 `patch_config.json`
