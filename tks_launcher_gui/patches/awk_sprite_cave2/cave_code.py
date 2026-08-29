# -*- coding: utf-8 -*-
"""
自定义战场形象（敌方） (awk_sprite_cave2) — cave 带注释机器码源

战场形象 PATH2 — 敌方角色形象加载

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# 战场形象 PATH2: 敌方角色精灵块条件覆盖
# hook 点原指令: add word ptr [ebp+8], 12 (5 字节: 66 83 45 08 0C)
# 逻辑: 若 WORD[260] != 0 → [ebp+8] = WORD[260] (直接使用自定义值)
#       若 WORD[260] == 0 → 保持原始 +12 逻辑
CAVE_CODE = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x0F, 0xBF, 0x45, 0x08,                            # movsx eax, word[ebp+8]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x7E, 0x1E,                                        # jle .default (+30)
    0x3D, 0xC8, 0x00, 0x00, 0x00,                      # cmp eax, 200
    0x77, 0x17,                                        # ja .default (+23)
    0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,               # imul eax, eax, 0x41E
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x208]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x07,                                        # jnz .use_custom (+7)
    # .default:
    0x66, 0x83, 0x45, 0x08, 0x0C,                      # add word[ebp+8], 12 (原始行为)
    0xEB, 0x04,                                        # jmp .done (+4)
    # .use_custom:
    0x66, 0x89, 0x4D, 0x08,                            # mov word[ebp+8], cx (自定义值)
    # .done:
    0x59, 0x58, 0xC3,                                  # pop ecx, pop eax, ret
])
