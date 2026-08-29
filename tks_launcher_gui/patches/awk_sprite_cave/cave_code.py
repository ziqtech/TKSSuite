# -*- coding: utf-8 -*-
"""
自定义战场形象（我方） (awk_sprite_cave) — cave 带注释机器码源

战场形象 PATH1 — 我方角色形象加载

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
CAVE_CODE = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x0F, 0xBF, 0x45, 0xFA,                            # movsx eax, word[ebp-6]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x7E, 0x2C,                                        # jle .done (+44) — 零或负数跳过
    0x3D, 0xC8, 0x00, 0x00, 0x00,                      # cmp eax, 200
    0x77, 0x25,                                        # ja .done (+37) — 超范围跳过
    0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,               # imul eax, eax, 0x41E
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x208]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x04,                                        # jnz .has_custom (+4)
    0x85, 0xC0,                                        # test eax, eax (ZF=0)
    0xEB, 0x0A,                                        # jmp .done (+10)
    # .has_custom:
    0x83, 0xE9, 0x06,                                  # sub ecx, 6
    0x66, 0x89, 0x4D, 0xFA,                            # mov word[ebp-6], cx
    0x66, 0x85, 0xC9,                                  # test cx, cx
    # .done:
    0x59, 0x58, 0xC3,                                  # pop ecx, pop eax, ret
])
