# -*- coding: utf-8 -*-
"""
死战反击自伤修复 (duel_counter_self_fix) — cave 带注释机器码源

死战强制反击自伤修复：反击者目标被错误设为自身时，修正为原始攻击者(word_9D6F58)，确保反击正常还击而非自伤

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# 补丁: 死战反击自伤修复 (duel_counter_self_fix)
# ============================================================
# 问题: sub_4458B0 AI强制反击段, sub_43D8B0从反击者自身坐标定位目标,
#       导致 byte_9D6FA4[0] == v26 (自身进入目标列表, 攻击自己)
#       现有 duel_self_target_fix 比较 word_9D6F58(原攻击者≠v26)无法拦截
# ============================================================
# 方案: Hook 在 sub_4434BC 入口 (0x4434BC), 替换前8字节函数头
#       hook 使用 E8 (call) 会在栈上多压一个返回地址,
#       因此 cave 开头先 pop edx 移除多余返回地址并暂存,
#       使栈布局还原为原始函数期望的 [ebp+4]=调用者返回地址
#       然后执行原序言并检查 byte_9D6FA4[0]==a1 (目标==施法者自身)
#       且 a1!=word_9D6F58 (反击场景, 非主攻击者)
#       若满足反击自伤条件: 将 byte_9D6FA4[0] 修正为 word_9D6F58
#       (原始攻击者), 使反击者正常攻击原攻击者而非自己
#       不影响主攻击者自伤(已有补丁)和治疗自愈(a1==word_9D6F58不过滤)
# ============================================================
CAVE_CODE = bytes([
    # === 修复栈帧: pop 掉 E8 call 多压的返回地址 ===
    0x5A,                                              #  0 pop edx (edx = 0x4434C4, 暂存)
    # 现在栈布局与原始函数一致: [esp]=orig_ret, [esp+4]=a1

    # === 执行被替换的序言 (8 bytes) ===
    0x55,                                              #  1 push ebp
    0x8B, 0xEC,                                        #  2 mov ebp, esp (→ [ebp+4]=orig_ret, [ebp+8]=a1)
    0x83, 0xC4, 0x9C,                                  #  4 add esp, -64h
    0x56,                                              #  7 push esi
    0x57,                                              #  8 push edi

    # === 保存寄存器 ===
    0x50,                                              #  9 push eax
    0x51,                                              # 10 push ecx

    # === 检查 byte_9D6FA4[0] == a1 (自身目标?) ===
    0x0F, 0xBE, 0x05, 0xA4, 0x6F, 0x9D, 0x00,         # 11 movsx eax, byte [0x9D6FA4]
    0x0F, 0xBF, 0x4D, 0x08,                            # 18 movsx ecx, word [ebp+8] (a1)
    0x3B, 0xC1,                                        # 22 cmp eax, ecx
    0x75, 0x17,                                        # 24 jne .continue (+23) — 非自身, 正常执行

    # === 自身目标: 检查是否反击场景 (a1 != word_9D6F58) ===
    0x0F, 0xBF, 0x0D, 0x58, 0x6F, 0x9D, 0x00,         # 26 movsx ecx, word [0x9D6F58]
    0x66, 0x3B, 0x4D, 0x08,                            # 33 cmp cx, [ebp+8]
    0x74, 0x0A,                                        # 37 je .continue (+10) — 主攻击者, 已有补丁处理

    # === 反击自伤: 将目标修正为原始攻击者 ===
    0xA0, 0x58, 0x6F, 0x9D, 0x00,                      # 39 mov al, [0x9D6F58] (原始攻击者ID)
    0xA2, 0xA4, 0x6F, 0x9D, 0x00,                      # 44 mov [0x9D6FA4], al (修正第一目标)

    # === .continue: 正常继续 sub_4434BC ===
    0x59,                                              # 49 pop ecx
    0x58,                                              # 50 pop eax
    0x52,                                              # 51 push edx (0x4434C4, 之前暂存的)
    0xC3,                                              # 52 ret → 跳转到 0x4434C4 继续执行
])
