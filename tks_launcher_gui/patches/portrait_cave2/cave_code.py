# -*- coding: utf-8 -*-
"""
自定义队伍头像（未选中） (portrait_cave2) — cave 带注释机器码源

队伍头像 PATH2 — 非选中队员头像

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# 队伍头像 PATH2: 非选中队员头像查询
# hook 点原指令: add dx, 0xD3; push edx (6 字节)
# 进入时 eax = char_idx * 527, dx = portrait原始值
# 计算: eax*2 = char_idx*1054 = 记录字节偏移 (正确!)
CAVE_CODE = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x85, 0xC0,                                        # test eax, eax
    0x7E, 0x1A,                                        # jle .default (+26)
    0x3D, 0x00, 0x00, 0x02, 0x00,                      # cmp eax, 0x20000
    0x77, 0x13,                                        # ja .default (+19)
    0x03, 0xC0,                                        # add eax, eax (char_idx*1054)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x0A, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x20A]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x07,                                        # jnz .has_custom (+7)
    # .default:
    0x66, 0x81, 0xC2, 0xD3, 0x00,                      # add dx, 0xD3
    0xEB, 0x03,                                        # jmp .done (+3)
    # .has_custom:
    0x66, 0x89, 0xCA,                                  # mov dx, cx
    # .done:
    0x59, 0x58,                                        # pop ecx, pop eax
    0x87, 0x14, 0x24,                                  # xchg [esp], edx
    0xFF, 0xE2,                                        # jmp edx
])
