# -*- coding: utf-8 -*-
"""
陷阱击杀经验JP修复 (trap_exp_jp_kill_fix) — cave 带注释机器码源

陷阱击杀敌方单位时，队伍按原版击杀结算获得经验与JP（金钱、物品掉落同原版击杀奖励）；
陷阱方不进入经验/JP分配，未击杀的陷阱伤害不给经验（与原版一致）

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: 比对本文件 CAVE_CODE 与 patch.json 的 cave_code 字段。

【hook 点】 sub_4400DC @0x44183C (RVA 0x4183C), 覆盖 6 字节 jnz loc_441AF0
  原文: 0F 85 AE 02 00 00   jnz 0x441AF0
  hook: E8 rel32 90         call cave + NOP
  进入时寄存器: eax = movsx byte_9DF761[arg_0] (0x441832 读出),
               ecx = movsx arg_0 (0x441827 读出, 陷阱/地图物件路径为 -1),
               [esp] = 0x441841 (E8 返回地址, 原 NOP 槽, 顺序执行落入 0x441842 奖励块)

【放行条件】 cmp eax,0x64 相等 (原版放行: 队伍成员=100, 召唤补丁映射后亦为 100)
             或 ecx == -1 (陷阱/地图物件伤害路径, sub_434C0C → sub_4434BC(-1))
【跳过路径】 add dword[esp],0x2AF: 0x441841 + 0x2AF = 0x441AF0 = 原 jnz 目标
"""
CAVE_CODE = bytes([
    0x83, 0xF8, 0x64,                           # 0000  cmp eax, 0x64            ; 重放原比较 (阵营字节==100?)
    0x74, 0x05,                                 # 0003  je 0x000A                ; 相等 → 原版放行 (ret 回 0x441841)
    0x83, 0xF9, 0xFF,                           # 0005  cmp ecx, -1              ; 陷阱/物件伤害路径 (arg_0 == -1)?
    0x75, 0x05,                                 # 0008  jne 0x000F               ; 非陷阱 → 按原 jnz 跳过奖励
    0xC3,                                       # 000A  ret                      ; 放行: 返回 0x441841(NOP) → 0x441842 奖励块
    0x90, 0x90, 0x90, 0x90,                     # 000B  nop x4 (填充, 不可达)
    0x81, 0x04, 0x24, 0xAF, 0x02, 0x00, 0x00,   # 000F  add dword ptr [esp], 0x2AF ; 返回地址 0x441841 → 0x441AF0 (原 jnz 目标)
    0xC3,                                       # 0016  ret                      ; 跳过: 与原版 jnz 0x441AF0 等价
])
