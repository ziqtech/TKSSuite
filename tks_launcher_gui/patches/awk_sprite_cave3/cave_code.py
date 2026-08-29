# -*- coding: utf-8 -*-
"""
自定义战场形象（敌方初始） (awk_sprite_cave3) — cave 带注释机器码源

战场形象 PATH3 — 战斗开始时敌方角色形象加载

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# 战场形象 PATH3/PATH4: 敌方角色精灵块条件覆盖 (通用)
# 逆向依据: sub_4307CC 敌方循环 @0x430DAD 与 sub_444FD4 敌方增援 @0x44513D,
# 两处原指令均为 add word ptr [ebp-6], 12 (66 83 45 FA 0C)。
# hook 时 [ebp-6] = WarPC 数据记录号 (角色ID+35, 已在 qmemcpy 时确定),
# 直接用该记录号查 WORD[260], 与 PATH2 按记录号查表的语义一致。
# 逻辑: 若 WORD[260] != 0 → [ebp-6] = WORD[260] (直接使用自定义形象块)
#       若 WORD[260] == 0 → 保持原始 +12 逻辑 (主角特判 ==36 分支在 hook 之前, 不受影响)
CAVE_CODE = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x0F, 0xBF, 0x45, 0xFA,                            # movsx eax, word[ebp-6]
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
    0x66, 0x83, 0x45, 0xFA, 0x0C,                      # add word[ebp-6], 12 (原始行为)
    0xEB, 0x04,                                        # jmp .done (+4)
    # .use_custom:
    0x66, 0x89, 0x4D, 0xFA,                            # mov word[ebp-6], cx (自定义值)
    # .done:
    0x59, 0x58, 0xC3,                                  # pop ecx, pop eax, ret
])
