# -*- coding: utf-8 -*-
"""
死战自我攻击修复 (duel_self_target_fix) — cave 带注释机器码源

死战状态自我攻击修复：决斗目标为自身时跳过决斗循环，修复使用物品后自我攻击致死BUG

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# Cave 模板: 死战状态决斗自我攻击修复
# 逆向依据: sub_4458B0 @0x445E99 (决斗循环入口, v24=byte_9D6FA4[0])
# hook: movsx ecx, byte ptr [0x9D6FA4] (7字节) -> E8 rel32 + 2xNOP
# 逻辑:
#   1. 执行被替换指令 (movsx ecx, byte [0x9D6FA4]) — 获取决斗目标实体
#   2. 读取 word_9D6F58 获取攻击者实体索引
#   3. 比较目标与攻击者: 相同则跳过决斗循环 (跳转到 0x4460F7)
#   4. 不同则正常返回执行决斗逻辑
# BUG 场景: 死战状态角色使用物品对自身后, 目标列表残留自身实体索引,
#           触发决斗循环导致角色自己攻击自己直到死去
# ============================================================
CAVE_CODE = bytes([
    # 执行被替换指令: 获取决斗目标实体索引
    0x0F,0xBE,0x0D,0xA4,0x6F,0x9D,0x00,               #  0 movsx ecx, byte ptr [0x9D6FA4]

    # 读取攻击者实体索引并比较
    0x50,                                              #  7 push eax
    0x0F,0xBF,0x05,0x58,0x6F,0x9D,0x00,               #  8 movsx eax, word ptr [0x9D6F58]
    0x39,0xC1,                                         # 15 cmp ecx, eax
    0x58,                                              # 17 pop eax
    0x75,0x08,                                         # 18 jne .no_skip (+8) — 目标!=自身, 正常决斗

    # 目标==自身: 修改返回地址跳过决斗循环
    0xC7,0x04,0x24,0xF7,0x60,0x44,0x00,               # 20 mov dword ptr [esp], 0x4460F7
    0xC3,                                              # 27 ret → 跳到 skip_duel

    # .no_skip: 正常返回, 继续决斗
    0xC3,                                              # 28 ret
])
