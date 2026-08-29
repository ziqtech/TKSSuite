# -*- coding: utf-8 -*-
"""
召唤物经验JP累加修复 (summon_exp_jp_accumulation_fix) — cave 带注释机器码源

让召唤物击杀敌人时沿用原版共享经验与JP累加路径，由队伍成员获得奖励；召唤物自身不进入经验/JP结算

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
CAVE_CODE = bytes([
    0x0F, 0xBE, 0x81, 0x61, 0xF7, 0x9D, 0x00,   # 0000  movsx eax, byte ptr [ecx + 0x9df761]
    0x83, 0xF8, 0x14,                           # 0007  cmp eax, 0x14
    0x75, 0x05,                                 # 000A  jne 0x11
    0xB8, 0x64, 0x00, 0x00, 0x00,               # 000C  mov eax, 0x64
    0xC3,                                       # 0011  ret 
])
