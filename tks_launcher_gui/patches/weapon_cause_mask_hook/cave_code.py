# -*- coding: utf-8 -*-
"""
武器附加状态修复 (weapon_cause_mask_hook) — cave 带注释机器码源

武器附加状态修复：读取函数参数[ebp+8]并验证==word_9D6F58，仅攻击者本人的普通攻击动画才触发武器cause_mask，排除反击/连击场景

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# Cave 模板: 武器 cause_mask -> TKKon inflict_status
# 逆向依据: 注入点 sub_4400DC @0x4400F6 (TKKon拷贝后, 状态队列推送前)
# hook: mov word [0x9E028A], 0 (9字节) -> E8 rel32 + 4xNOP
# cave 末尾 ret 回 hook+5, 经4xNOP到 hook+9 继续
# 逻辑:
#   0. ★ 检查 word_9D6C7C (当前技能索引), 不等于-1则跳过 (物品/技能/防御不触发武器附加)
#   1. ★ 读取 [ebp+8] (sub_4400DC 参数 a1 = 当前动画实体)
#   2. ★ 验证 a1 == word_9D6F58 (仅攻击者本人的动画才触发, 排除反击/连击)
#   3. WarPC[attacker].offset_69 -> 装备武器 item_index
#   4. TKItem[item_index].offset_26/27 -> cause_mask[1/2]
#   5. OR 进 word_9D6C3C / word_9D6C3E
#   6. 执行被替换指令 mov word [0x9E028A], 0
# BUG FIX v4: v3 读取全局 word_9D6F58 导致反击场景中用被攻击角色的武器判断状态
#             v4 改读函数参数 [ebp+8] 并验证 == word_9D6F58, 排除非攻击者动画
# ============================================================
CAVE_CODE = bytes([
    # 保存寄存器
    0x60,                                              #  0 pushad

    # ★ 检查当前技能索引: 仅普通攻击 (索引==-1) 时才应用武器附加状态
    # 逆向依据: sub_447DAC case 2000 设 word_9D6C7C=-1 表示普通攻击
    #           技能/物品使用时为 >=0 的技能ID, 防御=-2, 逃跑=-3
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,               #  1 movsx eax, [0x9D6C7C] (当前技能索引)
    0x83,0xF8,0xFF,                                    #  8 cmp eax, -1
    0x75,0x4A,                                         # 11 jne .done (+74) — 非普通攻击则跳过

    # ★ 读取 sub_4400DC 参数 a1 (当前动画实体, 即 sub_4434BC 传入的 entity)
    # 逆向依据: sub_4400DC 参数为当前播放动画的实体索引
    #   - 主攻击: sub_4434BC(word_9D6F58) -> a1 == word_9D6F58
    #   - 反击:   sub_4434BC(v26) -> a1 != word_9D6F58 (被排除)
    0x0F,0xBF,0x45,0x08,                               # 13 movsx eax, word ptr [ebp+8]

    # ★ 验证当前动画实体 == 回合攻击者 (排除反击/连击/群攻副动画)
    0x66,0x3B,0x05,0x58,0x6F,0x9D,0x00,               # 17 cmp ax, word ptr [0x9D6F58]
    0x75,0x3D,                                         # 24 jne .done (+61) — 非攻击者动画则跳过

    # 范围检查 (无符号比较: 负数视为超大正数, 与 >=143 一同拦截)
    0x3D,0x8F,0x00,0x00,0x00,                          # 26 cmp eax, 143
    0x73,0x36,                                         # 31 jae .done (+54) — 越界跳过

    # 计算 WarPC 字节偏移: eax * 1054
    0x69,0xC0,0x1E,0x04,0x00,0x00,                     # 33 imul eax, eax, 1054
    0x05,0x08,0x7F,0x75,0x00,                          # 39 add eax, WARPC_BASE (占位符, 自动重定位)

    # 读取装备武器 item_index (字偏移69=字节偏移138=0x8A)
    0x0F,0xBF,0x90,0x8A,0x00,0x00,0x00,               # 44 movsx edx, [eax + 138]

    # 检查武器是否存在 (index != -1)
    0x83,0xFA,0xFF,                                    # 51 cmp edx, -1
    0x74,0x1F,                                         # 54 je .done (+31)

    # 计算 TKItem 字节偏移: edx * 64
    0xC1,0xE2,0x06,                                    # 56 shl edx, 6

    # 读取 cause_mask[1] (TKItem[26]=字节偏移52), OR 进 word_9D6C3C
    0x66,0x8B,0x82,0xFE,0xCB,0x77,0x00,               # 59 mov ax, [edx + 0x77CBFE]
    0x66,0x09,0x05,0x3C,0x6C,0x9D,0x00,               # 66 or [0x9D6C3C], ax

    # 读取 cause_mask[2] (TKItem[27]=字节偏移54), OR 进 word_9D6C3E
    0x66,0x8B,0x82,0x00,0xCC,0x77,0x00,               # 73 mov ax, [edx + 0x77CC00]
    0x66,0x09,0x05,0x3E,0x6C,0x9D,0x00,               # 80 or [0x9D6C3E], ax

    # .done: 恢复寄存器 + 执行被替换指令 + 返回
    0x61,                                              # 87 popad
    0x66,0xC7,0x05,0x8A,0x02,0x9E,0x00,0x00,0x00,     # 88 mov word [0x9E028A], 0
    0xC3,                                              # 97 ret
])
