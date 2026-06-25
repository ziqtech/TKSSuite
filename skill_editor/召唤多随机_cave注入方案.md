# 召唤多随机 — 代码洞注入方案

> 目标：让 224~231（8 种野兽召唤）支持"召唤时从 N 个候选里随机一个"。
> 手段：在 `sub_444BB0` 召唤选择路径注入一个通用代码洞（cave），复用游戏自带 rand 函数 `sub_452AC0`。
> 性质：纯内存补丁，不修改 TKS.exe，关闭游戏即失效，与现有启动器补丁框架一致。
>
> 验证源：`反编译产物` 内存转储 `memory/00401000--00481000.txt` + 反编译 `decompile/444BB0.c` + `decompile/452AC0.c`
> 关联文档：`召唤技能目标角色映射_逆向分析.md`
> 最后更新：2026-06-25

---

## 一、为什么必须改代码（不能只改数据）

`sub_444BB0` 中三条召唤路径的随机性各不相同：

| 技能 | 选择逻辑 | 是否调用 rand | 仅改数据能否多随机 |
|---|---|---|---|
| 222 虎威震南天 | `i = 58`（立即数） | ❌ | ❌ |
| **224~231** 8种野兽 | `i = stru_4EB6F0[idx]`（查 1 字节） | ❌ | ❌ |
| 251 閃閃生光 | `if(rand(100)>=50) i=98 else i=96` | ✅ | 已是 2 随机 |

224~231 路径无任何 rand 调用，查表结果是单一固定字节。启动器现有 `patch_summon_table` 只把该字节/立即数改写为另一个固定值（`patch_engine.py: apply_summon_table`），写入的是**定值**，运行时不可能随机。

要支持多随机，必须让游戏代码在召唤时调用 rand 并在多个候选间挑选 → **必须注入代码**。启动器已有 `cave_hook` 框架（用于战场形象/头像补丁），本方案在其上扩展。

---

## 二、关键事实核对（机器码级）

### 2.1 rand 函数

`sub_452AC0` @ `0x452AC0`（`decompile/452AC0.c`）：

```c
int __cdecl sub_452AC0(unsigned __int16 a1) {
    if (!a1) return 0;
    do v2 = sub_452968();
    while (v2 >= a1 * (0xFFFF / a1));
    return v2 % a1;           // 返回 0..a1-1 均匀随机
}
```

- 调用约定 `__cdecl`，参数 16 位压栈，调用方清栈。
- 返回值 `0..N-1`。
- VA `0x452AC0` 固定（TKS.exe 无 ASLR），可硬编码绝对地址调用。

### 2.2 召唤选择段机器码（来自内存转储）

`sub_444BB0` 内 0x444C66 起（与 `444BB0.c:35-54` 伪代码、现有 `summon_table.json` RVA 三方对齐）：

```
444C66: 66 81 3D 7C 6C 9D 00 E0 00   cmp word[9D6C7C], 224
444C6F: 7C 1F                         jl  ->444C90
444C71: 66 81 3D 7C 6C 9D 00 E7 00   cmp word[9D6C7C], 231
444C7A: 7F 14                         jg  ->444C90
444C7C: 0F BF 05 7C 6C 9D 00         movsx eax, word[9D6C7C]         ; eax = 技能索引
444C83: 0F BE 90 F0 B6 4E 00         movsx edx, byte[eax+0x4EB6F0]   ; ★查表 i = stru_4EB6F0[idx]
444C8A: 66 89 55 FE                   mov [ebp-2], dx                 ; i 存入局部变量
444C8E: EB 3E                         jmp ->444CCE(汇合)
; --- 222 分支 ---
444C90: 66 81 3D 7C 6C 9D 00 DE 00   cmp word[9D6C7C], 222
444C99: 75 08                         jne ->444CA3
444C9B: 66 C7 45 FE 3A 00             mov word[ebp-2], 58             ; i=58 祝融夫人  ← skill_222 @0x44CA0
444CA1: EB 2B                         jmp ->444CCE
; --- 251 分支(自带rand) ---
444CA3: 66 81 3D 7C 6C 9D 00 FB 00   cmp word[9D6C7C], 251
444CAC: 0F 85 1C 03 00 00             jne ->return
444CB2: 6A 64                         push 100
444CB4: E8 06 DE 00 00               call 0x452AC0                    ; rand(100)
444CB9: 59                            pop ecx                         ; cdecl 清栈
444CBA: 66 83 F8 32                   cmp ax, 50
444CBE: 73 08                         jae ->444CC8
444CC0: 66 C7 45 FE 60 00             mov word[ebp-2], 96             ; ← skill_251_a @0x44CC5
444CC6: EB 06                         jmp ->444CCE
444CC8: 66 C7 45 FE 62 00             mov word[ebp-2], 98             ; ← skill_251_b @0x44CCCC
444CCE: ...                           ; 汇合, 后续用 [ebp-2] 调 sub_431094
```

核对：现有 `skill_222 @0x44CA0`、`skill_251_a @0x44CC5`、`skill_251_b @0x44CCD` 与上述字节完全吻合。

> **注**：`summon_table.json` 中 `skill_251_b` 标注 `@0x44CC9+4`，实际字节落在 `0x44CCC`（`66 C7 45 FE 62` 的立即数 `62` 在指令首字节 `0x44CC8` +4 = `0x44CCC`）。这是 JSON 注释里的笔误，不影响逻辑（启动器按 `rva` 字段定位，`tks_patches.json` 里 `skill_251_b` 的 rva 需以实现时的精确偏移为准，见阶段一备注）。

### 2.3 注入点选择

**Hook 点：`0x444C83`**，指令 `0F BE 90 F0 B6 4E 00`（7 字节，查表指令）。

替换为 `E8 rel32`（call cave，5 字节）+ `90 90`（2 NOP）= 7 字节，精确覆盖。

- 前一条 `movsx eax,[9D6C7C]`（0x444C7C）保留执行，eax=技能索引。
- 后一条 `mov [ebp-2],dx`（0x444C8A）保留：cave 把结果放 `edx`，由该指令自然写入 `[ebp-2]`。
- `jmp 0x444CCE`（0x444C8E）保留，流程不变。

**寄存器安全性**：0x444CCE 汇合后，`eax`/`ecx` 被后续 `0F BF 4D 08` 等指令重写，`edx` 不再被使用（`i` 已存 `[ebp-2]`）。cave 破坏 caller-saved 寄存器无副作用。cave 以 `call` 进入（未改 ebp），`[ebp-2]` 可寻址，但本方案 cave 不直接写 `[ebp-2]`，结果经 `edx` 由原指令写入，更稳妥。

### 2.4 Hook 模式（版本无关扫描）

`0F BE 90 F0 B6 4E 00 66 89 55 FE`（11 字节，含后续 `mov [ebp-2],dx` 提高唯一性）

- `expect_count = 1`
- `hook_size = 7`（仅覆盖查表指令 7 字节，保留后续 mov/jmp）

---

## 三、Cave 代码设计

单一通用 cave。hook 点 `call` 进入，cave 末尾 `ret` 回 `0x444C8A`。

### 3.1 汇编规范

```asm
summon_cave:
    push ebx
    push esi
    ; 1. 读技能索引
    movsx ebx, word [0x9D6C7C]          ; 固定 VA, 无需重定位
    ; 2. 映射到 entry 下标: 224..231 -> 0..7
    sub  ebx, 0xE0                      ; ⚠ 必须 imm32 (81 EB E0 00 00 00)
                                        ;   若用 imm8 (83 EB E0), 0xE0 符号扩展为 -32,
                                        ;   实际变成 ebx+32 -> 索引越界 -> rand(垃圾值) 死循环=卡死
    ; 3. entry 指针 = TABLE_BASE + ebx*9   (TABLE_BASE 为动态占位符)
    imul ebx, ebx, 9
    add  ebx, TABLE_BASE                ; ⚠ 必须 ADD EBX,imm32 (81 C3)
                                        ;   若用 ADD EBX,[imm32] (03 1D), 会解引用 TABLE_BASE
                                        ;   处内存(=count字节3)而非加地址 -> esi 指向 0x27 -> 访问违例=卡死
    mov esi, ebx
    mov esi, ebx
    ; 4. count = entry[0]
    movzx ecx, byte [esi]
    test ecx, ecx
    jz   .default                       ; count=0 -> 走原查表(向后兼容)
    cmp  ecx, 1
    jbe  .single                        ; count=1 -> 直接取 cand[0]
    ; 5. rand(count)
    push ecx                            ; arg N
    mov  eax, 0x452AC0                  ; sub_452AC0 固定 VA, 硬编码
    call eax                            ; eax = r ∈ [0,count)
    pop  ecx                            ; cdecl 清栈
    movzx edx, byte [esi+1+eax]         ; i = candidates[r]
    jmp  .done
.single:
    movzx edx, byte [esi+1]             ; i = candidates[0]
    jmp  .done
.default:                               ; 未配置多随机 -> 还原原查表
    movsx eax, word [0x9D6C7C]
    movsx edx, byte [eax+0x4EB6F0]      ; 原始 stru_4EB6F0[idx]
.done:
    pop  esi
    pop  ebx
    ret
```

> **实现备忘（2026-06-25 实测踩坑）**：首版 cave 用 `83 EB E0`（SUB EBX, imm8）实现 `sub ebx, 0xE0`，但 imm8 `0xE0` 被 CPU 符号扩展为 `-32`，实际执行 `ebx = ebx + 32`。技能 228 时索引变成 260，远超 72 字节候选表，读到的 `count` 是随机大值，`sub_452AC0(count)` 内 `do-while` 循环条件恒真 → **死循环 = 游戏卡死**。修复为 imm32 编码 `81 EB E0 00 00 00`。cave 总长 74 → 77 字节。
>
> **实现备忘2（2026-06-25 实测踩坑）**：第二版 cave 用 `03 1D <addr>`（ADD EBX, [mem]）实现"加候选表地址"，但这是**内存解引用**——读 addr 处 4 字节作为值相加，而非加地址本身。占位符替换后变成 `add ebx, [table_abs]`，执行 `ebx = 36 + *(uint32*)table_abs = 36 + 3(count字节)` = 39，`esi=39` → `movzx ecx,[esi]` 读地址 0x27 → **访问违例 = 卡死**。修复为 `81 C3 <addr>`（ADD EBX, imm32，立即数加法）。两个 bug 同样表现"卡死"，但根因不同：前者是 rand 死循环，后者是非法内存访问。

### 3.2 设计要点

1. **向后兼容**：`count=0` 分支走原查表 `stru_4EB6F0[idx]`，未在 JSON 配置列表的技能行为与原版一字节不差。
2. **绝对地址调用 rand**：`mov eax,0x452AC0; call eax`，避开 rel32 动态重定位（0x452AC0 固定无 ASLR）。
3. **唯一动态重定位点**：`TABLE_BASE`（候选表地址），占位符 `0x52414E44`（"RAND"）。该值不会在指令字节中自然出现，`replace_addr_in_bytes` 替换无误伤风险。
4. **结果经 edx 传递**：cave 不碰 `[ebp-2]`，由原 `mov [ebp-2],dx` 指令写入，降低对栈帧的依赖。
5. **代码体量**：约 65~75 字节（实际字节码在实现阶段产出并自检反汇编）。

> 字节码生成与自检在 B 阶段（实现）完成；本文档只锁定汇编规范与寄存器/栈约定。

---

## 四、候选表数据布局

存放于 cave 内存（地址动态，由 `TABLE_BASE` 指向）。定长 entry，每技能 9 字节：

```
struct entry { uint8 count; uint8 cand[8]; }   // 9 字节
entry[0] = 技能224
entry[1] = 技能225
...
entry[7] = 技能231
共 72 字节
```

| count 值 | 行为 |
|---|---|
| 0 | 走原查表（默认/未配置） |
| 1 | 固定 `cand[0]`（等价单值覆盖） |
| N (2≤N≤8) | `sub_452AC0(N)` 随机选 `cand[0..N-1]` |

`cand[k]` 存的是 i 值（= WarPC 索引 − 36），与 `sub_431094` 入参一致。

---

## 五、JSON 配置格式扩展

`summon_table.json` 增加列表型键（与现有单值键并存，列表优先）：

```json
"skill_228_random_说明": "技能228 召喚麒麟 → 三选一随机(麒麟/金龍/金翅鳥)。值为 WarPC 索引, 1~8 个",
"skill_228_random": [138, 134, 132],

"skill_230_random": [134, 132]
```

- 值为 WarPC 索引列表（启动器换算 i = WarPC − 36，与现有单值键一致）。
- 存在 `skill_XXX_random` → 写入对应 entry（count=len, cand=列表换算后的 i）。
- 不存在 → count=0（默认原查表）。
- 列表与单值键 `skill_XXX` 同时存在时，**列表优先**（单值键对该技能失效）。
- 校验：列表长度 1~8，每个值经现有 `_warpc_i` 值域校验（36..max_count）。

---

## 六、启动器改动点

| 文件 | 改动 |
|---|---|
| `workers/patcher_worker.py:344` | cave 内存 `512` → `1024`（容纳新 cave 代码 + 候选表） |
| `core/patch_engine.py` | 新增 `CAVE_SUMMON_RANDOM` 模板字节码；`build_cave_template` 注册 `"summon_random"` |
| `core/patch_engine.py` | `apply_summon_table` 扩展：读 `*_random` 列表 → 构造 72 字节候选表 → 写入 cave（`cave_addr+table_offset`）→ 写 cave 代码（`cave_addr+cave_offset`）→ 重定位 `TABLE_BASE` 占位符 → 写 hook（`0x444C83` 处 7 字节） |
| `tks_patches.json` | `patch_summon_table` 条目增加 `random_hook` 子配置：`hook_pattern / hook_size / cave_offset / table_offset / placeholder` |

### 6.1 cave 内存布局（1024 字节）

| 偏移 | 用途 | 已用 |
|---|---|---|
| 0 | awk_sprite cave | ✓ 现有 |
| 64 | portrait1 cave | ✓ 现有 |
| 128 | portrait2 cave | ✓ 现有 |
| 192 | archive_portrait cave | ✓ 现有 |
| 256 | history_text cave | ✓ 现有 |
| **320** | **summon_random cave 代码**（~70 字节，到 ~390） | 新增 |
| **448** | **召唤候选表**（72 字节，到 520） | 新增 |

1024 字节充足。

---

## 七、风险与回退

| 风险 | 缓解 |
|---|---|
| hook 模式在目标版本不唯一 | `expect_count=1`，不匹配则跳过该补丁（启动器已有机制），不影响其他补丁 |
| cave 代码 bug 导致崩溃 | 纯内存补丁，关闭游戏即失效，无永久风险；可先单技能（如 228）小范围验证 |
| 候选 i 越界（WarPC 索引无效） | 复用 `_warpc_i` 值域校验，越界拒绝写入并告警 |
| 寄存器/栈破坏 | cave 保存 ebx/esi；`sub_452AC0` cdecl 清栈已处理；结果经 edx 由原指令写入 |
| 与 222/251 imm16 补丁冲突 | 阶段一不动 222/251，互不干涉 |
| cave 内存不足 | 512→1024，布局见 6.1 |

---

## 八、分阶段实施

### 阶段一（本方案主体）
224~231 通用多随机 cave + JSON 列表配置。最小可用。

### 阶段二（可选扩展）
222 纳入同一 cave：
- hook `0x444C9B`（`66 C7 45 FE 3A 00`，6 字节 mov）→ `call cave` + 1 NOP（或与下方 jmp 合并处理）。
- 候选表增加 entry[8] = 技能222，cave 内 idx 映射 `0xDE(222)→8`。
- 与 224~231 共用 cave 代码，仅多一个 hook 点。

### 阶段三（可选扩展）
251 扩展为 >2 候选：
- 251 自带 50/50 rand，要支持 N>2 需 hook `0x444CC0`/`0x444CC8` 两条 mov，并接管 rand 分支。
- 251 本身已 2 随机，优先级低。

---

## 九、验证清单（B 阶段实现后）

1. **字节码自检**：cave 字节码反汇编与 3.1 汇编规范逐指令一致。
2. **占位符唯一性**：`0x52414E44` 在 cave 代码中仅出现 1 次（TABLE_BASE 引用）。
3. **hook 覆盖精确**：`0x444C83` 起 7 字节 = `E8 rel32 90 90`，rel32 指向 `cave_addr+320`。
4. **向后兼容**：JSON 不配任何 `*_random` → 游戏内 224~231 行为与原版一致（count 全 0，走 default 分支）。
5. **单技能验证**：仅配 `skill_228_random:[138,134,132]`，游戏内多次施放召喚麒麟，统计三角色出现概率≈1/3。
6. **值域校验**：配越界值（如 999）→ 启动器告警跳过，不写脏数据。
7. **回退**：取消勾选 `summon_table` 补丁 → 不注入，游戏原版行为。
