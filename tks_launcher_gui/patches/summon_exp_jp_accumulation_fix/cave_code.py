# -*- coding: utf-8 -*-
"""
召唤物经验JP累加修复 (summon_exp_jp_accumulation_fix) — 固定布局 cave 生成器

让召唤物击杀敌人时沿用原版共享经验与JP累加路径，由队伍成员获得奖励；
召唤物自身不进入经验/JP结算，且其个人经验落点受保护。

【布局】 (与 patch.json hooks[].cave_entry_offset 一一对应)
  [0x00, 0x20)  gate   门槛放行   18B  hook @0x441832 (hook_size 7)
  [0x20, 0x40)  guard  落点保护   21B  hook @0x4418F8 (hook_size 14)

【栈约定】 引擎在 hook 点写 E8 call (patch_engine/exe_builder 一致)，
  进入 cave 时 [esp] = 返回地址 (hook+5)。两段 cave 均不 push/pop、
  以 ret 结尾, 栈严格平衡。

【gate 语义】 sub_4400DC 击杀结算门槛 @0x441832:
  重放 movsx eax, byte_9DF761[ecx] (ecx = movsx arg_0, 未被覆盖);
  恰为 0x14 (召唤物, sub_431094) 映射为 0x64 (队伍) 放行进入奖励块;
  其余原样交回原版 cmp eax,0x64 (0x441839, 未被覆盖)。ret 回 0x441837
  (2 NOP) → 0x441839, flags 由原版 cmp 重算。

【guard 语义】 个人经验累加 @0x4418F8 (原 14 字节 0F BF 4D 08 8B 45 B8 01 04 8D 20 6F 9D 00):
  dword_9D6F20 为队伍成员个人经验数组, 仅 6 槽 (0x9D6F20..0x9D6F37)。
  arg_0 ∈ [0,5] (队伍击杀): 重放 mov/add 与原版逐字节等价;
  arg_0 = -1 (陷阱): movsx 后 0xFFFFFFFF, 落点 0x9D6F1C = 金钱累计器 arglist;
  arg_0 >= 6 (召唤槽): 越界写入 dword_9D6F38 个人JP数组 / unk_9D6F50 升级旗标;
  两者一律 ret 跳过本条写入 (jb 无符号 <6 放行, 负值按无符号为巨值自然拦截)。
  与 trap_exp_jp_personal_fix 的 cave 语义相同, 两者同开时后应用者经
  fallback_rva (0x418F8) 重挂同语义 cave, 行为一致。
  跳过不影响 [ebp-0x48]: 0x441906 shl [ebp-0x48],1 与后续共享经验池
  (0x441919 dword_9D6F14)、JP 池 (0x441959 dword_9D6F18)、金钱
  (0x4419A2 arglist) 均按内存原值继续; cmp 残留标志无消费者 (shl 不读入)。

GATE_CAVE:
    0F BE 81 61 F7 9D 00   movsx eax, byte ptr [ecx + 0x9DF761]  ; 重放
    83 F8 14               cmp  eax, 0x14                        ; 召唤物?
    75 05                  jne  0x0012                           ; 非 → 原样返回
    B8 64 00 00 00         mov  eax, 0x64                        ; 召唤 → 映射为队伍
    C3                     ret                                   ; → 0x441839

GUARD_CAVE:
    0F BF 4D 08            movsx ecx, word ptr [ebp+8]           ; 重放: ecx = arg_0
    83 F9 06               cmp  ecx, 6                           ; (无符号) <6?
    72 01                  jb   0x000A                           ; 是 → 重放原累加
    C3                     ret                                   ; 否(-1/≥6) → 跳过
    8B 45 B8               mov  eax, dword ptr [ebp-0x48]        ; 重放: 个人经验值
    01 04 8D 20 6F 9D 00   add  dword ptr [ecx*4+0x9D6F20], eax  ; 重放: 原累加
    C3                     ret                                   ; → 0x441906
"""
from __future__ import annotations

GATE_CAVE = bytes([
    0x0F, 0xBE, 0x81, 0x61, 0xF7, 0x9D, 0x00,   # 0000  movsx eax, byte ptr [ecx + 0x9DF761]
    0x83, 0xF8, 0x14,                           # 0007  cmp  eax, 0x14
    0x75, 0x05,                                 # 000A  jne  0x0012
    0xB8, 0x64, 0x00, 0x00, 0x00,               # 000C  mov  eax, 0x64
    0xC3,                                       # 0011  ret
])

GUARD_CAVE = bytes([
    0x0F, 0xBF, 0x4D, 0x08,                     # 0000  movsx ecx, word ptr [ebp+8]
    0x83, 0xF9, 0x06,                           # 0004  cmp  ecx, 6
    0x72, 0x01,                                 # 0007  jb   0x000A
    0xC3,                                       # 0009  ret
    0x8B, 0x45, 0xB8,                           # 000A  mov  eax, dword ptr [ebp-0x48]
    0x01, 0x04, 0x8D, 0x20, 0x6F, 0x9D, 0x00,   # 000D  add  dword ptr [ecx*4+0x9D6F20], eax
    0xC3,                                       # 0014  ret
])

GATE_ENTRY = 0
GUARD_ENTRY = 32
BLOCK_SIZE = 64


def build_cave_block(cave_base: int, n: int = 4) -> bytes:
    """生成固定布局 cave 块 (cave_base/n 不参与编码, 保持 summon_limit 接口兼容)。"""
    block = bytearray(BLOCK_SIZE)
    block[GATE_ENTRY:GATE_ENTRY + len(GATE_CAVE)] = GATE_CAVE
    block[GUARD_ENTRY:GUARD_ENTRY + len(GUARD_CAVE)] = GUARD_CAVE
    return bytes(block)
