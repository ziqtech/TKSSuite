# -*- coding: utf-8 -*-
"""
主角等级检测重定向 (checkmember_level_redirect) — cave 带注释机器码源

CheckMember 主角等级重定向: CheckMember(0,0,LV,cmp)→读取槽位0成员等级 (sub_40E88C)

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# Cave 模板: 主角替换 — CheckMember 等级检查重定向
# 逆向依据: sub_40E88C @0x40E8CB (CheckMember a2==0 分支)
# hook: movsx edx, word [ebp+8] (5字节) -> E8 rel32
# 逻辑:
#   1. pop 掉 E8 call 多压的返回地址
#   2. 若 a1==0 (检查主角), 读取 word_75688C[0] (槽位0成员ID)
#   3. 若槽位0非空且非主角自身, 替换 a1 = 槽位0成员ID
#   4. 执行被替换指令 (movsx ecx, word [ebp+8]) 并 jmp 回 0x40E8D1
# ============================================================
CAVE_CODE = bytes([
    0x59,                                              #  0 pop ecx (丢弃 CALL 返回地址)
    0x50,                                              #  1 push eax
    0x66, 0x83, 0x7D, 0x08, 0x00,                      #  2 cmp word [ebp+8], 0        ; a1 == 0?
    0x75, 0x15,                                        #  7 jne .skip (→ 30)            ; a1 != 0 → 跳过
    0x66, 0xA1, 0x8C, 0x68, 0x75, 0x00,                #  9 mov ax, [0x75688C]         ; ax = word_75688C[0]
    0x66, 0x83, 0xF8, 0xFF,                            # 15 cmp ax, -1                  ; 槽位0为空?
    0x74, 0x09,                                        # 19 je .skip (→ 30)             ; 是 → 跳过
    0x66, 0x85, 0xC0,                                  # 21 test ax, ax                 ; 槽位0=主角自身?
    0x74, 0x04,                                        # 24 je .skip (→ 30)             ; 是 → 跳过
    0x66, 0x89, 0x45, 0x08,                            # 26 mov word [ebp+8], ax        ; 替换 a1 = 槽位0成员ID
    # 自然落入 .skip (无需 jmp, mov [ebp+8] 后紧跟 pop eax)
    # .skip:
    0x58,                                              # 30 pop eax                     ; 恢复 eax
    0x0F, 0xBF, 0x4D, 0x08,                            # 31 movsx ecx, word [ebp+8]    ; ecx = (可能修改后的) a1
    0x8B, 0xD1,                                        # 35 mov edx, ecx               ; edx = a1 (0x40E8D4 add/sub 需要!)
    0x68, 0xD1, 0xE8, 0x40, 0x00,                      # 37 push 0x40E8D1              ; 返回目标
    0xC3,                                              # 42 ret                         ; → 0x40E8D1
])
