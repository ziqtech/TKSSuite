# -*- coding: utf-8 -*-
"""
陷阱击杀个人经验落点保护 (trap_exp_jp_personal_fix) — cave 带注释机器码源

陷阱击杀路径没有攻击者单位，跳过其个人经验累加，防止写入落点恰好覆盖金钱累计器
dword_9D6F1C；须与『陷阱击杀经验JP修复』(trap_exp_jp_kill_fix) 同开，单独开启时无任何效果

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: 比对本文件 CAVE_CODE 与 patch.json 的 cave_code 字段。

【hook 点】 sub_4400DC @0x4418F8 (RVA 0x418F8), 覆盖 14 字节原文:
  0F BF 4D 08              movsx ecx, word ptr [ebp+8]            ; arg_0 (攻击者单位号, 陷阱=-1)
  8B 45 B8                 mov  eax, dword ptr [ebp-0x48]         ; var_48 = 本次击杀个人经验值
  01 04 8D 20 6F 9D 00     add  dword ptr [ecx*4+0x9D6F20], eax   ; 个人经验数组 dword_9D6F20[成员号]
  hook: E8 rel32 + 9x90    call cave + NOP
  进入时 [esp] = 0x4418FD (E8 返回地址, NOP 槽, 顺序执行落入 0x441906 shl [ebp-0x48],1)

【关键事实】 dword_9D6F20 为队伍成员个人经验数组 (6 槽, 0x9D6F20..0x9D6F37)。
  陷阱路径 arg_0=-1 → ecx*4 = -4 → 写入 0x9D6F1C = dword_9D6F20[-1],
  与金钱累计器 arglist (dword_9D6F1C, @0x4419A2 add arglist,eax) 重叠。
  陷阱 (ecx==-1) 跳过本条累加; 其余共享经验池 (0x441919 dword_9D6F14)、
  JP 池 (0x441959 dword_9D6F18)、金钱 (0x4419A2 arglist) 均不受影响、按原版执行。
"""
CAVE_CODE = bytes([
    0x0F, 0xBF, 0x4D, 0x08,                     # 0000  movsx ecx, word ptr [ebp+8]  ; 重放: ecx = arg_0
    0x83, 0xF9, 0xFF,                           # 0004  cmp ecx, -1                  ; 陷阱/物件伤害路径?
    0x75, 0x01,                                 # 0007  jne 0x000A                   ; 非陷阱 → 重放原累加
    0xC3,                                       # 0009  ret                          ; 陷阱 → 跳过个人经验累加 (返回 0x4418FD)
    0x8B, 0x45, 0xB8,                           # 000A  mov eax, dword ptr [ebp-0x48] ; 重放: eax = 个人经验值
    0x01, 0x04, 0x8D, 0x20, 0x6F, 0x9D, 0x00,   # 000D  add dword ptr [ecx*4+0x9D6F20], eax ; 重放: 原个人经验累加
    0xC3,                                       # 0014  ret                          ; 返回 0x4418FD → 0x441906
])
