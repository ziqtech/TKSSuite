# -*- coding: utf-8 -*-
"""
强制出战主角缺失时槽0顶替 (war_mustchar_fallback) — cave 带注释机器码源

强制出战主角(ID 0)但主角已离队时, 由队伍槽0角色顶替出战 (sub_4307CC 强制名单解析 @0x430895), 避免 0 人出战触发 0x430BC3 idiv 除零卡死

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# Cave 模板: 强制出战主角缺失时槽0顶替 (war_mustchar_fallback)
# 逆向依据: sub_4307CC (PlaceUnits) 强制名单解析 @0x430895
#   hook 点: movsx eax,byte[ecx]; dec eax; (5字节) -> E8 rel32
#   原始被偷指令: eax = (char)*v16 - 1 (名单角色 0-based ID), 存入 v26
#
# 问题背景: 主角离队后, WarData must_chars 含主角(值1)的战斗在名单解析阶段
#   找不到主角 → v23 全 0 → 0 人出战 → 0x430BC3 `idiv cx` (cx=byte_9DF886=0)
#   除零崩溃 (EXCEPTION_INT_DIVIDE_BY_ZERO)。
#
# 本 cave 在重放 movsx/dec 后追加判断: 若 v26==0 (强制主角) 且队伍
#   word_75688C[0..5] 中无主角, 则把 v26 替换为队伍槽0角色 ID
#   (槽0空则为 -1, 内层循环不匹配任何槽, 与 checkmember_level_redirect
#   同一槽0顶替语义)。非主角强制角色不受影响。
# 栈: call 压入返回地址先 pop eax (随即被 movsx 覆盖); 扫描段 push/pop
#   ecx,edx 保护 (edx=0x430892 设置的 v23 指针, 0x4308A3 仍需使用)。
# 返回 0x43089D (mov word [ebp-4],0, 内层循环 v27=0 初始化)。
# ============================================================
CAVE_CODE = bytes([
    0x58,                                              #  0 pop  eax                    ; 丢弃 call 返回地址
    0x0F, 0xBE, 0x01,                                  #  1 movsx eax, byte [ecx]      ; 重放: eax = (char)*v16
    0x48,                                              #  4 dec  eax                    ; 重放: v26 = ID-1
    0x66, 0x83, 0xF8, 0x00,                            #  5 cmp  ax, 0                  ; v26 == 0 (强制主角)?
    0x75, 0x21,                                        #  9 jnz  .store (→2C)           ; 非主角 → 直接存
    0x51,                                              # 11 push ecx                    ; 保护 (扫描用)
    0x52,                                              # 12 push edx                    ; 保护 v23 指针
    0xB9, 0x06, 0x00, 0x00, 0x00,                      # 13 mov  ecx, 6                 ; 6 槽
    0xBA, 0x8C, 0x68, 0x75, 0x00,                      # 18 mov  edx, 0x75688C          ; 队伍
    # .scan:
    0x66, 0x83, 0x3A, 0x00,                            # 23 cmp  word [edx], 0          ; 槽 == 0 (主角在队)?
    0x74, 0x0D,                                        # 27 je   .found (→2A)           ; 有主角 → 保持 v26=0
    0x83, 0xC2, 0x02,                                  # 29 add  edx, 2                 ; 下一槽
    0x49,                                              # 32 dec  ecx
    0x75, 0xF4,                                        # 33 jnz  .scan (→23)
    0x0F, 0xBF, 0x05, 0x8C, 0x68, 0x75, 0x00,          # 35 movsx eax, word [0x75688C]  ; 无主角 → v26 = 槽0角色ID (7字节)
    # .found:
    0x5A,                                              # 42 pop  edx
    0x59,                                              # 43 pop  ecx
    # .store:
    0x66, 0x89, 0x45, 0xFA,                            # 44 mov  word [ebp-6], ax       ; v26 = ax (重放)
    0x68, 0x9D, 0x08, 0x43, 0x00,                      # 48 push 0x43089D               ; 返回: 内层循环初始化
    0xC3,                                              # 53 ret
])
