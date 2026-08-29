# -*- coding: utf-8 -*-
"""
召唤角色自定义 (summon_table) — 召唤多随机 cave 带注释机器码源

本补丁类型为 patch_summon_table, 运行时机器码来自 patch.json 的
summon_cave_code / summon_cave2_code (与本文件字节级一致),
引擎应用时将占位符 0x52414E44 ("RAND") 替换为运行时候选表地址。

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 对应字段字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件与 patch.json)
"""

SUMMON_RANDOM_PLACEHOLDER = 0x52414E44   # "RAND", cave 内唯一, 指向 72 字节候选表

# ============================================================
# Cave 模板: 召唤多随机 (224~231)
# 逆向依据: sub_444BB0 @0x444C83 查表指令; sub_452AC0 rand(n)->0..n-1
# hook 点 0x444C83 (movsx edx,byte[eax+0x4EB6F0], 7字节) -> E8 rel32 + 90 90
# cave 末尾 ret 回 0x444C8A (mov [ebp-2],dx 由原指令写回)
# count=0 走原查表 (向后兼容); count=N 调 sub_452AC0(N) 随机选 cand[0..N-1]
# 唯一动态重定位点: TABLE_BASE 占位符 0x52414E44 (cave 内出现 1 次)
# ============================================================
SUMMON_RANDOM_CODE = bytes([
    0x53,                                              # 0  push ebx
    0x56,                                              # 1  push esi
    0x0F,0xBF,0x1D,0x7C,0x6C,0x9D,0x00,                # 2  movsx ebx, word[0x9D6C7C]
    0x81,0xEB,0xE0,0x00,0x00,0x00,                     # 9  sub ebx, 0xE0  (imm32! 避免 imm8 符号扩展, idx 224..231 -> 0..7)
    0x6B,0xDB,0x09,                                    # 15 imul ebx, ebx, 9       (entry 9 字节)
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 18 add ebx, TABLE_BASE   <- 占位符 (imm32 立即数加, 非[mem]解引用)
    0x8B,0xF3,                                         # 24 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 26 movzx ecx, byte[esi]   (count)
    0x85,0xC9,                                         # 29 test ecx, ecx
    0x74,0x1B,                                         # 31 jz  .default(60)
    0x83,0xF9,0x01,                                    # 33 cmp ecx, 1
    0x76,0x10,                                         # 36 jbe .single(54)
    0x51,                                              # 38 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 39 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 44 call eax               (rand(count))
    0x59,                                              # 46 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 47 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x14,                                         # 52 jmp .done(74)
    0x0F,0xB6,0x56,0x01,                               # 54 .single: movzx edx, byte[esi+1]
    0xEB,0x0E,                                         # 58 jmp .done(74)
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,                # 60 .default: movsx eax, word[0x9D6C7C]
    0x0F,0xBE,0x90,0xF0,0xB6,0x4E,0x00,                # 67 movsx edx, byte[eax+0x4EB6F0]  (原查表)
    0x5E,                                              # 74 .done: pop esi
    0x5B,                                              # 75 pop ebx
    0xC3,                                              # 76 ret
])

# ============================================================
# Cave 模板: 召唤多随机 222/251
# 与 224~231 区别: 222/251 hook 点之后不经 mov[ebp-2],dx, 故 cave 自行写 [ebp-2]
# 合并三段: entry_222(entry8) + entry_251(entry9) + shared(随机选 cand, 写[ebp-2])
# entry_222/entry_251 仅设 entry 常数后 jmp shared; shared 内 rand 选 cand -> [ebp-2]
# 仅在配了 skill_222_random/skill_251_random 时启用对应 hook (count>=1, 无 default 分支)
# ============================================================
SUMMON_RANDOM_222_251_CODE = bytes([
    # entry_222 @0  (hook 0x444C9C, ret->0x444CA2 jmp 0x444CCF)
    0x53,                                              # 0  push ebx
    0xBB,0x08,0x00,0x00,0x00,                          # 1  mov ebx, 8            (entry 8)
    0xEB,0x08,                                         # 6  jmp shared(16)
    # entry_251 @8  (hook 0x444CB3, ret->0x444CB8 NOP->0x444CCF)
    0x53,                                              # 8  push ebx
    0xBB,0x09,0x00,0x00,0x00,                          # 9  mov ebx, 9            (entry 9)
    0xEB,0x00,                                         # 14 jmp shared(16)
    # shared @16
    0x56,                                              # 16 push esi
    0x6B,0xDB,0x09,                                    # 17 imul ebx, ebx, 9
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 20 add ebx, TABLE_BASE   <- 占位符 (imm32)
    0x8B,0xF3,                                         # 26 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 28 movzx ecx, byte[esi]  (count, >=1)
    0x83,0xF9,0x01,                                    # 31 cmp ecx, 1
    0x76,0x10,                                         # 34 jbe .single(52)
    0x51,                                              # 36 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 37 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 42 call eax              (rand(count))
    0x59,                                              # 44 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 45 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x04,                                         # 50 jmp .write(56)
    0x0F,0xB6,0x56,0x01,                               # 52 .single: movzx edx, byte[esi+1]
    0x66,0x89,0x55,0xFE,                               # 56 .write: mov [ebp-2], dx
    0x5E,                                              # 60 pop esi
    0x5B,                                              # 61 pop ebx
    0xC3,                                              # 62 ret
])
