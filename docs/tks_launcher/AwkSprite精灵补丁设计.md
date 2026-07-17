# Awk.JVG 武器精灵块 — 运行时补丁设计

> ⚠️ **本文为早期设计方案，已被 `AwkSprite补丁实现总结.md` 取代**。最终实现有两处关键变更：
> 1. **配置字段改为 WORD[260]（字节偏移 520 = `[eax+0x208]`）**，非本文的 WORD[267]/0x216（详见 `../warpc_editor/WarPC未使用字段分析_WORD260.md`：编辑器 `warpc_editor.py:90` 已落在 [260]）。
> 2. **改为单 cave + 单 hook**（hook 点 `cmp [ebp-6],0` @ RVA `0x309A6`，`VirtualAllocEx` 动态分配），而非本文的双 cave（0x30A37 / 0x31162）方案。
>
> 本文下述补丁**目标地址** `0x30A37`(+6) / `0x31162`(+12) 及字节 `66 83 45 FA 06` / `66 83 45 08 0C` 经反编译核对属实（对应 `4307CC.c:120/236`），仅"读哪个字段"与"cave 组织方式"被后续实现修订。

## 概述

将 `sub_4307CC` 中两处硬编码偏移（PATH1: +6, PATH2: +12）替换为从 WarPC 可配置字段读取的值（**本文按早期方案写作 WORD[267]；最终实现为 WORD[260]，见顶部说明**）。

---

## 一、补丁目标

| 路径 | 原始指令 | RVA | 原始字节 | 替换为 |
|------|---------|-----|---------|--------|
| PATH 1 (玩家) | `add word ptr [ebp-6], 6` | `0x30A37` | `66 83 45 FA 06` | `E8 XX XX XX XX` → call cave1 |
| PATH 2 (敌方) | `add word ptr [ebp+8], 12` | `0x31162` | `66 83 45 08 0C` | `E8 XX XX XX XX` → call cave2 |

## 二、代码 Cave 1 — PATH 1（玩家，默认 +6）

插在 [ebp-6] = v26 = WarPC 角色索引处。

```asm
cave_path1:
    push eax                        ; 50
    push ecx                        ; 51
    movsx eax, word ptr [ebp-6]     ; 0F BF 45 FA  — eax=WarPC索引(v26)
    imul eax, eax, 0x41E            ; 69 C0 1E 04 00 00  — eax*=1054
    add  eax, 0x757F08              ; 05 08 7F 75 00  — eax=WarPC记录基址
    movzx ecx, word ptr [eax+0x216] ; 0F B7 88 16 02 00 00  — cx=WORD[267]
    test cx, cx                     ; 66 85 C9
    jnz  .use_it                    ; 75 05
    mov  cx, 6                      ; 66 B9 06 00  — 默认+6
.use_it:
    add  word ptr [ebp-6], cx       ; 66 01 4D FA  — v26+=offset
    pop  ecx                        ; 59
    pop  eax                        ; 58
    ret                             ; C3
```

**总大小：40 字节**。Cave 地址 TBD（请在 IDA 中找 ≥40 字节的连续 `CC`/`00` 区域）。

`call` 指令字节计算：`E8 [cave_addr - (0x30A37 + 5)]`（小端 4 字节）。

## 三、代码 Cave 2 — PATH 2（敌方，默认 +12）

插在 [ebp+8] = v26 = WarPC 记录号处。

```asm
cave_path2:
    push eax                        ; 50
    push ecx                        ; 51
    movsx eax, word ptr [ebp+8]     ; 0F BF 45 08  — eax=WarPC记录号(v26)
    imul eax, eax, 0x41E            ; 69 C0 1E 04 00 00
    add  eax, 0x757F08              ; 05 08 7F 75 00
    movzx ecx, word ptr [eax+0x216] ; 0F B7 88 16 02 00 00
    test cx, cx                     ; 66 85 C9
    jnz  .use_it                    ; 75 05
    mov  cx, 12                     ; 66 B9 0C 00  — 默认+12
.use_it:
    add  word ptr [ebp+8], cx       ; 66 01 4D 08  — v26+=offset
    pop  ecx                        ; 59
    pop  eax                        ; 58
    ret                             ; C3
```

**总大小：40 字节**。

## 四、patch_config.json 条目（Cave 地址找到后填入）

```json
{
    "desc": "AwkSprite PATH1: call cave → 读 WarPC WORD[267] 替代 +6 (sub_4307CC:120)",
    "rva": "0x30A37",
    "data": "E8 XX XX XX XX"
},
{
    "desc": "AwkSprite cave1 代码体 (40 bytes)",
    "rva": "<cave1_addr>",
    "data": "50 51 0F BF 45 FA 69 C0 1E 04 00 00 05 08 7F 75 00 0F B7 88 16 02 00 00 66 85 C9 75 05 66 B9 06 00 66 01 4D FA 59 58 C3"
},
{
    "desc": "AwkSprite PATH2: call cave → 读 WarPC WORD[267] 替代 +12 (sub_4307CC:236)",
    "rva": "0x31162",
    "data": "E8 XX XX XX XX"
},
{
    "desc": "AwkSprite cave2 代码体 (40 bytes)",
    "rva": "<cave2_addr>",
    "data": "50 51 0F BF 45 08 69 C0 1E 04 00 00 05 08 7F 75 00 0F B7 88 16 02 00 00 66 85 C9 75 05 66 B9 0C 00 66 01 4D 08 59 58 C3"
}
```

## 五、IDA 操作指引

1. 在 IDA 中打开 dump 文件
2. 跳转到 `0x430A37`，确认显示 `add word ptr [ebp-6], 6`
3. 跳转到 `0x431162`，确认显示 `add word ptr [ebp+8], 12`
4. 搜索代码 cave 空间：`Search → Sequence of bytes...`，搜索 `CC CC CC CC CC CC`（INT3 填充）或大段 `00`
5. 找到两段 ≥40 字节的连续空闲空间，记录地址
6. 计算 `call` 偏移：
   - PATH1 call: `target = cave1_addr; offset = target - 0x430A3C; bytes = E8 [offset_le32]`
   - PATH2 call: `target = cave2_addr; offset = target - 0x431167; bytes = E8 [offset_le32]`
7. 填入 `patch_config.json` 中替换 `XX XX XX XX` 和 `<cave_addr>`

## 六、逻辑流程图

```
sub_4307CC 执行
  │
  ├── PATH 1 (遍历 team slots)
  │     v26 = WarPC_index (from word_75688C)
  │     if (v26 != 0):
  │         call cave1 ─────────────────────┐
  │         │                               ▼
  │         │              ecx = WarPC[v26].WORD[267]
  │         │              if (ecx != 0): v26 += ecx
  │         │              else:          v26 += 6 (default)
  │         │              ret ───────────────┘
  │     sprite_block = v26 → Awt.JVG/Awk.JVG 加载
  │
  ├── PATH 2 (遍历 battlefield enemies)
  │     v26 = *word_9537FA + 35 (WarPC record index)
  │     if (v26 != 36):
  │         call cave2 ─────────────────────┐
  │         │                               ▼
  │         │              ecx = WarPC[v26].WORD[267]
  │         │              if (ecx != 0): v26 += ecx
  │         │              else:          v26 += 12 (default)
  │         │              ret ───────────────┘
  │     sprite_block = v26 → Awt.JVG/Awk.JVG 加载
```

## 七、使用说明

1. 在 warpc_editor 中设置角色的"战场图集索引"字段（WORD[267]）
2. 值为 0：使用原硬编码公式（PATH1: +6, PATH2: +12）
3. 值非 0：补丁直接使用此值作为武器精灵块的偏移量
4. 示例：颜良 WarPC 85，设 WORD[267]=2 → 武器精灵块 = 85+2 = 87
