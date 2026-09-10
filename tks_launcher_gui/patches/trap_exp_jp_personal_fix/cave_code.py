# -*- coding: utf-8 -*-
"""
个人经验落点保护（陷阱/召唤） (trap_exp_jp_personal_fix) — cave 带注释机器码源

保护击杀奖励块的个人经验累加 @0x4418F8 落点：arg_0 ∈ [0,5]（队伍击杀）与原版
逐字节等价；arg_0 = -1（陷阱击杀，落点 dword_9D6F1C 金钱累计器）或 ≥6（召唤槽，
越界写入 dword_9D6F38 个人JP数组 / unk_9D6F50 升级旗标）一律跳过。
须与『陷阱击杀经验JP修复』(trap_exp_jp_kill_fix) 同开才有陷阱路径行为差异。

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: 比对本文件 CAVE_CODE 与 patch.json 的 cave_code 字段。

【hook 点】 sub_4400DC @0x4418F8 (RVA 0x418F8), 覆盖 14 字节原文:
  0F BF 4D 08              movsx ecx, word ptr [ebp+8]            ; arg_0 (攻击者单位号)
  8B 45 B8                 mov  eax, dword ptr [ebp-0x48]         ; var_48 = 本次击杀个人经验值
  01 04 8D 20 6F 9D 00     add  dword ptr [ecx*4+0x9D6F20], eax   ; 个人经验数组 dword_9D6F20[成员号]
  hook: E8 rel32 + 9x90    call cave + NOP
  进入时 [esp] = 0x4418FD (E8 返回地址, NOP 槽, 顺序执行落入 0x441906 shl [ebp-0x48],1)

【关键事实】 dword_9D6F20 为队伍成员个人经验数组 (6 槽, 0x9D6F20..0x9D6F37)。
  - 陷阱路径 arg_0=-1 → ecx*4 = -4 → 写入 0x9D6F1C = dword_9D6F20[-1],
    与金钱累计器 arglist (dword_9D6F1C, @0x4419A2 add arglist,eax) 重叠。
  - 召唤补丁放行的召唤槽 arg_0 ≥ 6 → 越界: 槽 6-11 落入 dword_9D6F38 个人JP数组
    (经 43B7FC.c:105/134 v18[26]+=*v20 变永久 JP 污染), 槽 ≥12 落入 unk_9D6F50
    升级旗标乃至 word_9D6F58。
  - 故本 cave 以 cmp ecx,6 / jb (无符号 <6) 门控: 仅 [0,5] 重放原累加;
    -1 (movsx 后 0xFFFFFFFF, 无符号巨值) 与 ≥6 一律 ret 跳过。
  - 其余共享经验池 (0x441919 dword_9D6F14)、JP 池 (0x441959 dword_9D6F18)、
    金钱 (0x4419A2 arglist) 均不受影响、按原版执行。
  - 与 summon_exp_jp_accumulation_fix 的 guard hook (同地址同 14 字节) 语义相同:
    两者同开时后应用者经 fallback_rva 0x418F8 重挂同语义 cave, 行为一致。
"""
CAVE_CODE = bytes([
    0x0F, 0xBF, 0x4D, 0x08,                     # 0000  movsx ecx, word ptr [ebp+8]  ; 重放: ecx = arg_0
    0x83, 0xF9, 0x06,                           # 0004  cmp ecx, 6                   ; (无符号) <6?
    0x72, 0x01,                                 # 0007  jb  0x000A                   ; [0,5] → 重放原累加
    0xC3,                                       # 0009  ret                          ; -1 / ≥6 → 跳过个人经验累加 (返回 0x4418FD)
    0x8B, 0x45, 0xB8,                           # 000A  mov eax, dword ptr [ebp-0x48] ; 重放: eax = 个人经验值
    0x01, 0x04, 0x8D, 0x20, 0x6F, 0x9D, 0x00,   # 000D  add dword ptr [ecx*4+0x9D6F20], eax ; 重放: 原个人经验累加
    0xC3,                                       # 0014  ret                          ; 返回 0x4418FD → 0x441906
])
