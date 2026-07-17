# TeamMember 角色 ID 上限分析

## 问题

在 WarPC 编辑器中新增游戏角色（WarPC 索引 85），在脚本中使用 `TeamMember(85,1)` 无法生效。

## 结论

**`TeamMember(85,1)` 不生效的直接原因：`85 > 0x1E (30)`，超出游戏引擎硬编码的角色 ID 上限，`sub_40DA00` 在第一行有效代码处即跳过整个函数体。**

---

## 一、脚本命令映射

| 脚本命令 | opcode | 实现函数 | 说明 |
|----------|--------|----------|------|
| `TeamMember(a1, a2)` | 45 | `sub_40DA00` | a1=角色ID, a2=1加入/a2=0移除/a2=0清除全部 |
| `CheckTeam(a1, a2, a3)` | 63 | `sub_40E65C` | a1=检查类型, a2=比较值, a3=比较操作符 |

来源：`decompile/40EBD4.c`（脚本命令派发器）

- case 45 → `sub_40DA00`
- case 63 → `sub_40E65C`

---

## 二、TeamMember 实现分析 (`sub_40DA00`)

### 函数签名

```c
unsigned __int16 __cdecl sub_40DA00(unsigned __int16 a1, __int16 a2)
```

- `a1` — 角色 ID（unsigned 16-bit）
- `a2` — 操作模式：
  - `1` — 加入队伍
  - `≠1` — 从队伍移除指定角色
  - `a1=0` — 清空全部队伍成员

### 关键校验（line 20）

```c
// decompile/40DA00.c, line 20
if ( a1 <= 0x1Eu )   // 0x1E = 30
{
    if ( a1 )
    {
        if ( a2 == 1 )
        {
            // ... 在 word_75688C[0..5] 中找空位，加入角色 ...
        }
        else
        {
            // ... 在 word_75688C[0..5] 中查找并移除角色 ...
        }
    }
    else  // a1 == 0
    {
        // ... 清空 word_75688C[1..5] 全部队伍成员 ...
    }
}
return result;
```

**`if (a1 <= 0x1Eu)` 是函数第一条执行语句。当 a1=85 时，`85 > 30`，条件为 false，整个函数体被跳过，不执行任何操作。**

### 加入队伍逻辑（a2 == 1）

```c
// decompile/40DA00.c, lines 26-44
v8 = 0;
v5 = word_75688C;          // 队伍数组起始地址
do
{
    if ( *v5 == -1 )        // 找到空槽 (-1 = 空)
        break;
    ++v8;
    ++v5;
}
while ( v8 < 6 );           // 最多 6 个槽位
result = v8;
if ( v8 != 6 )              // 未满
{
    if ( word_757F0E[527 * (__int16)a1] == -1 )
        sub_410674(&word_757F08[527 * (__int16)a1], word_757F0C[527 * (__int16)a1]);
    sub_422A5C(&unk_82444C, 1, a1);
    word_75688C[v8] = a1;   // 写入队伍槽
    return v8;
}
```

流程：
1. 在 `word_75688C[6]`（6 槽队伍数组）中找第一个空位 (`-1`)
2. 若队伍已满（6人），直接返回
3. 若角色数据未初始化（`word_757F0E[527*a1] == -1`），调用 `sub_410674` 初始化角色属性
4. 调用 `sub_422A5C` 应用装备/被动技能
5. 将角色 ID 写入队伍槽

### 移除队伍逻辑（a2 ≠ 1）

```c
// decompile/40DA00.c, lines 47-70
v9 = 1;
v4 = &word_75688E;          // 从第2个槽位开始查找
do
{
    result = *v4;
    if ( *v4 == a1 )         // 找到匹配角色
        break;
    ++v9;
    ++v4;
}
while ( v9 < 6 );
if ( v9 != 6 )               // 找到了
{
    sub_422A5C(&unk_82444C, -1, a1);  // 卸除装备效果
    sub_40C648(word_758116[527 * word_75688C[v9]]); // 启用实体
    for ( i = (_WORD *)(2 * v9 + 7694478); v9 < 5; ++i )
    {
        *(i - 1) = *i;        // 后续队员前移
        ++v9;
    }
    word_75688C[v9] = -1;     // 最后一个槽置空
    return v9;
}
```

### 清空全部队伍（a1 == 0）

```c
// decompile/40DA00.c, lines 73-90
v7 = 1;
v6 = &word_75688E;          // 从槽位 1 开始
do
{
    result = (unsigned __int16)v6;
    if ( *v6 > 0 )            // 槽位有角色
    {
        sub_422A5C(&unk_82444C, -1, *v6);
        result = (unsigned __int16)sub_40C648(word_758116[527 * *v6]);
        *v6 = -1;             // 清空槽位
    }
    ++v7;
    ++v6;
}
while ( v7 < 6 );
```

注意：清空操作从槽位 1 开始（`&word_75688E = word_75688C + 1`），**槽位 0（主角）不会被清除**。

---

## 三、CheckTeam 同样的限制 (`sub_40E65C`)

```c
// decompile/40E65C.c, lines 17-25
switch ( a1 )
{
    case 1:
        if ( a2 > 0x1Eu )   // 仅接受 0-30
        {
            sub_452478(0, "[%d] event CheckTeam [%d][%d] error !!", 
                       dword_75350C, a1, (__int16)a2);
            return 0;
        }
        v8 = 0;
        v5 = word_75688C;
        // ... 在 6 槽中搜索角色 a2 ...
}
```

`CheckTeam(type=1, id, op)` 用于检查某角色是否在队伍中，同样限制 ID ≤ 30。

CheckTeam 检查类型（a1）：
| a1 | 含义 |
|----|------|
| 1 | 检查特定角色 (a2) 是否在队伍中 |
| 2-4 | 检查特定槽位值 |
| 5 | 统计队伍非空人数 |
| 6 | 检查特定槽位值 |
| 10-15 | 其他数据检查 |

比较操作符（a3）：
| a3 | 含义 |
|----|------|
| -2 | < |
| -1 | ≤ |
| 0 | == |
| 1 | ≥ |
| 2 | > |
| 3 | ≠ |

---

## 四、内存数据结构

### 队伍槽数组

```
word_75688C[6] — 6 个 int16 槽位
  槽 0: 主角（不会被清空操作移除）
  槽 1-5: 可加入/移除的队员
  空槽值: -1 (0xFFFF)
```

### 角色属性数据

```
word_757F08[527 × N] — 每角色 527 int16 (1054 字节)，= WarPC 记录起始 (field[0])
word_757F0C[527 × N] — 角色等级 (field[2]，= word_757F08+4)
word_757F0E[527 × N] — current_exp / 初始化标记 (field[3]，= word_757F08+6；值 -1 表示"未初始化"，sub_40DA00 第39行据此决定是否调用 sub_410674)
```

与 WarPC.dat 格式完全相同（527 int16 × 143 角色 = 150722 字节）。

来源：`decompile/403F94.c`

```c
v2 = 150722;    // = 143 角色 × 1054 字节
v3 = sub_4530A8(&word_757F08, &v2, 0);  // 分配内存
// ... 从文件加载数据到 word_757F08 ...
```

注意：**内存中加载了全部 143 个角色的数据（索引 0-142）**。数据层面，索引 85 的角色数据完整存在于内存中。`0x1E` 的限制纯粹是 `sub_40DA00` 中的逻辑限制。

### 角色初始化 (`sub_410674`)

```c
// decompile/410674.c
_WORD *__cdecl sub_410674(_WORD *a1, unsigned __int8 a2)
{
    // a1 = &word_757F08[527 * member_id] (角色属性指针)
    // a2 = 等级
    // 按等级缩放 HP/MP/攻击/防御/命中/闪避/速度
    a1[2] = a2;           // 设定等级
    a1[3] = 0;            // current_exp=0 (脱离 -1 "未激活" 哨兵)
    a1[4] = 8*a2*a2 + 92; // 升级经验
    sub_42234C(&unk_82444C, a1);  // 应用装备/技能
    a1[5] = a1[8];        // HP = HP上限
    a1[6] = a1[10];       // MP = MP上限
}
```

### 装备/属性应用 (`sub_422768`)

```c
// decompile/422768.c
__int16 __cdecl sub_422768(int a1, __int16 a2)
{
    return sub_42234C(a1, &word_757F08[527 * a2]);
}
```

---

## 五、完整脚本派发器映射 (`sub_40EBD4`)

从 `decompile/40EBD4.c` 提取的脚本 opcode 对照表：

| Opcode | 实现函数 | 参数量 | 脚本命令（推断） |
|--------|---------|--------|-----------------|
| 0 | — | 1 | End |
| 1 | sub_40A220 | 5 | TalkB? |
| 2 | sub_40A220 | 5 | TalkA? |
| 3 | — | 1 | Nop |
| 4 | sub_40B520 | 4 | SetSwitch |
| 5 | sub_40B1B4 | 7 | ? |
| 6 | sub_40B650 | 4 | ? |
| 7 | sub_40B710 | 3 | MenuTalk |
| 8 | sub_40BB70 | 3 | ? |
| 9 | sub_40BC10 | 4 | ? |
| 10 | sub_40BCC0 | 3 | 条件跳转 |
| 11 | sub_40BD84 | 3 | ? |
| 12 | sub_40BE30 | 3 | ? |
| 13 | sub_40BEDC | 3 | SetVisible? |
| 14 | sub_40BF88 | 4 | ? |
| 15 | — | 1 | Return |
| 16 | sub_411BA4→sub_411C0C | 4 | ChangeScene |
| 17 | sub_409830→... | 5 | ? |
| 18 | sub_409830→... | 5 | ? |
| 19 | sub_40C044 | 5 | ? |
| 20 | sub_40C1A4 | 8 | ? |
| 21 | sub_40C388 | 3 | ? |
| 22 | sub_40C428 | 3 | ? |
| 23 | sub_40C4D8 | 5 | SetPos |
| 24 | sub_40C5A4 | 2 | Disable |
| 25 | sub_40C648 | 2 | Enable |
| 26 | sub_40C6EC | 2 | ? |
| 27 | sub_40C7CC | 2 | SetWalk? |
| 28 | sub_40C854 | 2 | SetAni? |
| 29 | sub_40C8E0 | 3 | ? |
| 30 | sub_40C9E8 | 4 | ? |
| 31 | — | 2 | SetGlobal |
| 32 | sub_40CB08 | 3 | SetFlag |
| 33 | sub_40CB4C | 3 | AddFlag |
| 34 | sub_40A220 | 6 | ? |
| 35 | sub_40CB90 | 3 | ? |
| 36 | — | 3 | SetVar (max 0xF9=249) |
| 37 | sub_452AC0 | 4 | Random |
| 38 | sub_40CB08 | 3 | SetFlagVar |
| 39 | sub_40CB4C | 3 | AddFlagVar |
| 40 | sub_40CE30 | 3 | SetBlock? |
| 41 | sub_40B05C | 5 | ? |
| 42 | sub_40D0CC | 3 | ? |
| 43 | sub_40D2A0 | 3 | ? |
| 44 | sub_40D2D0→sub_409830 | 3 | Camera? |
| **45** | **sub_40DA00** | **3** | **TeamMember** |
| 46 | sub_40DBF4 | 3 | Note? |
| 47 | sub_40DC1C | 3 | ? |
| 48 | sub_40E11C | 4 | Attribute? |
| 49 | — | 3 | SetSwitch (max 0x20=32) |
| 50 | sub_40D804→sub_409830 | 4 | FadeOut |
| 51 | sub_451780→sub_451C38 | 3 | ? |
| 52 | sub_451D2C | 2 | ? |
| 53 | sub_44AC50→sub_44AC90 | 3 | PlayMusic |
| 54 | — | 3 | SetMusic (max 0x100=256) |
| 55 | — | 1 | Scene jump |
| 56 | — | 2 | Nop |
| 60 | — | 4+ | CheckResult |
| 61 | sub_40E40C | 5 | CheckFlag |
| 62 | sub_40E4E4 | 5 | CheckMember? |
| **63** | **sub_40E65C** | **5** | **CheckTeam** |
| 64 | sub_40E97C | 5 | MenuChoice? |
| 65 | sub_40E88C | 6 | ? |
| 66 | sub_40EB10 | 3 | MiniGame? |
| 82 | — | 2 | Else/Jump |

---

## 六、游戏内置脚本中的 TeamMember 使用

### 英雄亭外（决战后加入）

```cpp
{;1 #Define
TalkB(-2,25591,1,-1)
MenuTalk(25594,0)
CheckResult(0,0)
{
 CheckTeam(5,6,-2)        // 队伍人数 < 6 ?
 {
  TalkB(-2,25592,1,-1)
  FadeOut(0,0,0,100)
  TeamMember(29,1)         // ID=29 加入队伍 ✓
  Disable(-2)
  FadeIn(0,0,0,100)
  End(0)
 }
 // ...
}
};1 #Define end
```

### 许褚加入

```cpp
// Entity 4292 脚本
CheckTeam(5,6,-2)          // 队伍人数 < 6 ?
{
    TeamMember(5,1)         // ID=5 (许褚) 加入队伍 ✓
    FadeOut(0,0,0,70)
    Disable(4292)
    SetPos(4292,380,456,1)
    FadeIn(0,0,0,70)
    End(0)
}
```

**两个内置脚本使用的 ID 均 ≤ 30：`TeamMember(29,1)` 和 `TeamMember(5,1)`。**

---

## 七、总结

```
TeamMember(85,1) 执行流程：

parse → opcode 45 → sub_40DA00(a1=85, a2=1)
                           │
                           ▼
                  if (a1 <= 0x1E)   ← 85 > 30 → FALSE
                           │
                           ▼
                    函数直接返回，未执行任何操作
                           │
                           ▼
                   word_75688C[] 未修改 → 角色未加入队伍
```

### 关键数值

| 项目 | 值 | 备注 |
|------|-----|------|
| 角色 ID 上限 | 0x1E = 30 | sub_40DA00 硬编码, 已通过运行时补丁改为 200 |
| 队伍槽数 | 6 | word_75688C[6] |
| 角色数据总量 | 143 条 × 1054 字节 = 150722 字节 | word_757F08[] |
| 角色数据格式 | 527 int16 = WarPC.dat 格式 | 完全一致 |

### 根因

`sub_40DA00`（TeamMember 处理器）硬编码了角色 ID 上限为 `0x1E`（30）。由于 `85 > 30`，校验失败，函数体被完全跳过。

### 解决方案 — 运行时内存补丁

修改两处比较指令，每处 2 字节：

| # | 地址 (RVA) | 函数 | 原始指令 | 修改为 | 说明 |
|---|-----------|------|---------|--------|------|
| 1 | `0xDA15` | `sub_40DA00` | `1E` `0F 8F` | `C8` `0F 87` | `cmp imm8 30→200` + `jg→ja` |
| 2 | `0xE6C1` | `sub_40E65C` | `1E` `7E` | `C8` `76` | `cmp imm8 30→200` + `jle→jbe` |

补丁文件: `逆向工作区/patch_config.json`  
补丁工具: `逆向工作区/runtime_patcher.py`

用法:
```bash
python runtime_patcher.py    # 自动启动 TKS.exe 并打补丁
python runtime_patcher.py --pid <子进程PID>    # 对已运行的进程打补丁
```

#### 技术细节：83h 操作码的符号扩展陷阱

`83h` 操作码配合 `66h`（16位操作数前缀）时，imm8 会被**符号扩展**到 16 位：

```
66 83 7D 08 C8    →  cmp word [ebp+8], 0xFFC8    ← 实际比较 -56（不是 200）
```

`0xC8` 的 bit7=1，符号扩展后变 `0xFFC8`（-56）。因此必须同步修改条件跳转指令：有符号 `jg`/`jle` → 无符号 `ja`/`jbe`。
