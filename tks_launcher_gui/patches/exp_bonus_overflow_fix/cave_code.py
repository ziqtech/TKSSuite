# -*- coding: utf-8 -*-
"""
经验加成溢出保护 (exp_bonus_overflow_fix) — cave 带注释机器码源

经验加成乘法溢出保护 (乘法前将累积值钳位到[0,30000]防止int32溢出)

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# 经验加成乘法溢出保护 Cave
# 逆向依据: sub_43B7FC @0x43BA27 exp_bonus 计算
# hook 点: mov edx,[eax]; movsx eax,word[ecx+3Eh]; imul edx,eax (9字节)
# 原始指令被替换为 E8(call)+4xNOP, cave执行后 ret回 +9处 (add edx,99)
# 逻辑:
#   1. mov edx, [eax]              — 加载 *v19 (原始指令1)
#   2. cmp edx, 30000             — 上界检查
#   3. jle .cap_done              — 已在范围内则跳过
#   4. mov edx, 30000             — 钳位到上限 (防止乘法溢出)
#   5. test edx, edx              — 下界检查
#   6. jns .no_neg                — 非负则跳过
#   7. xor edx, edx               — 负值置零
#   8. movsx eax, word[ecx+3Eh]   — 加载 exp_bonus (原始指令2)
#   9. imul edx, eax              — 安全乘法 (max 30000*32767 < INT32_MAX)
#  10. ret                        — 返回到 "add edx, 99"
CAVE_CODE = bytes([
    0x8B, 0x10,                                        # mov edx, [eax]
    0x81, 0xFA, 0x30, 0x75, 0x00, 0x00,                # cmp edx, 7530h
    0x7E, 0x05,                                        # jle .cap_done (+5)
    0xBA, 0x30, 0x75, 0x00, 0x00,                      # mov edx, 7530h
    # .cap_done:
    0x85, 0xD2,                                        # test edx, edx
    0x79, 0x02,                                        # jns .no_neg (+2)
    0x33, 0xD2,                                        # xor edx, edx
    # .no_neg:
    0x0F, 0xBF, 0x41, 0x3E,                            # movsx eax, word[ecx+3Eh]
    0x0F, 0xAF, 0xD0,                                  # imul edx, eax
    0xC3,                                              # ret
])
