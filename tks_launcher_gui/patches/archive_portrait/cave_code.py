# -*- coding: utf-8 -*-
"""
存档列表队伍头像修复 (archive_portrait) — cave 带注释机器码源

存档列表队伍头像 WORD[261] 优先查询 (cave_hook)

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# 逆向依据: sub_41AB94 @0x41AD00 (存档界面队伍头像绘制)
# 原指令: movsx eax,byte[ecx+eax*2+0x29E]; add ax,0xD3; push eax
# 修复要点:
#   1. movzx ecx,al 取无符号角色索引 (0..199=有效, 0xFF=空槽)
#   2. cmp cl,0xFF 空槽检查 → 跳过 WarPC 查询避免越界崩溃
#   3. imul eax,ecx,0x41E 三操作数形式, ECX=源, 避免原二操作数 imul 破坏索引
#   4. 默认头像 = 索引 + 0xD3, 自定义头像 = warpc[index].field_0x20A
CAVE_CODE = bytes([
    0x52,                                              # push edx
    0x51,                                              # push ecx
    0x0F, 0xB6, 0xC8,                                  # movzx ecx, al          (无符号索引)
    0x80, 0xF9, 0xFF,                                  # cmp cl, 0xFF           (空槽?)
    0x74, 0x17,                                        # je .default            (空槽→默认)
    0x69, 0xC1, 0x1E, 0x04, 0x00, 0x00,               # imul eax, ecx, 0x41E   (索引*sizeof)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE    (→&warpc[idx])
    0x0F, 0xB7, 0x90, 0x0A, 0x02, 0x00, 0x00,         # movzx edx, word[eax+0x20A] (自定义头像)
    0x66, 0x85, 0xD2,                                  # test dx, dx
    0x75, 0x09,                                        # jnz .use_custom
    # .default:
    0x8B, 0xC1,                                        # mov eax, ecx
    0x05, 0xD3, 0x00, 0x00, 0x00,                      # add eax, 0xD3          (默认头像)
    0xEB, 0x02,                                        # jmp .done
    # .use_custom:
    0x8B, 0xC2,                                        # mov eax, edx           (自定义头像)
    # .done:
    0x59,                                              # pop ecx                (恢复 ecx)
    0x5A,                                              # pop edx                (恢复 edx)
    0x59,                                              # pop ecx                (ecx=返回地址)
    0x50,                                              # push eax               (portrait值入栈)
    0xFF, 0xE1,                                        # jmp ecx                (返回)
])
