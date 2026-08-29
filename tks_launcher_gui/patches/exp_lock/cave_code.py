# -*- coding: utf-8 -*-
"""
战斗经验锁定（压级） (exp_lock) — cave 带注释机器码源

注意: 本补丁类型为 patch_exp_lock, 引擎应用时按配置写入偏移 10 处 (cave_mask_offset) 的锁定掩码字节;
patch.json 的 cave_code 为掩码占位 0 的版本, 也是运行时唯一机器码来源 (引擎已不内置)。

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""

# 掩码占位字节偏移 (apply_exp_lock 按配置写入):
CAVE_EXP_LOCK_MASK_OFFSET = 10

# ============================================================
# Cave 模板: 战斗经验锁定（压级）
# 逆向依据: sub_43B7FC @0x43BAF3  (战后经验分配, 读取 v11 = *v19 处)
# hook 点: mov eax,[esp+1C]; mov dx,[eax] (7字节) -> E8 rel32 + 2 NOP
#   原始被偷指令在 cave 内重放; cave ret 回 0x43BAF8(NOP,NOP)→0x43BAFA(mov [esp+6],dx)
# 目标: 锁定槽位将 dword_9D6F20[slot](=*v19, 每槽获得经验累加器) 置 0 ——
#   既使结算屏显示 0 (sub_43B2D4 读 *v6=dword_9D6F20 显示),
#   又使随后 v11=*v19=0 → 不升级、经验不写回。
# 逻辑 (入口 esp 已因 call +4, 故 [esp+1C]→[esp+20], [esp]→[esp+04]):
#   1. mov eax,[esp+20h]      — 重放: eax = v19 (dword_9D6F20[slot] 指针)
#   2. movzx ecx,word[esp+4]  — ecx = v5 = 战斗队伍槽位 (0..5)
#   3. mov dl, MASK           — dl = 锁定掩码 (imm8, 由 apply_exp_lock 按配置写入; bit i=锁定槽 i)
#   4. shr dl, cl / test dl,1 — 测试槽位 slot 的锁定位
#   5. jz .keep               — 未锁定 → 不改动
#   6. mov dword[eax], 0      — 锁定 → dword_9D6F20[slot]=0 (显示与逻辑均为0)
#   7. mov dx, [eax]          — 重放被偷指令2: dx=*v19 (锁定则=0), 随后存入 v11
#   8. ret
# 仅用 eax/ecx/dx (返回后原代码均重载), 无 push/pop, 栈平衡不变
# ============================================================
CAVE_CODE = bytes([
    0x8B, 0x44, 0x24, 0x20,                            #  0 mov eax, [esp+20h]        ; eax = v19 指针
    0x0F, 0xB7, 0x4C, 0x24, 0x04,                      #  4 movzx ecx, word [esp+04h] ; ecx = 槽位 v5
    0xB2, 0x00,                                        #  9 mov dl, MASK             ; [10]=掩码占位, 补丁写入
    0xD2, 0xEA,                                        # 11 shr dl, cl               ; dl >>= 槽位
    0xF6, 0xC2, 0x01,                                  # 13 test dl, 1
    0x74, 0x06,                                        # 16 jz .keep (→ 24)          ; 未锁定→不改动
    0xC7, 0x00, 0x00, 0x00, 0x00, 0x00,                # 18 mov dword [eax], 0       ; 锁定→dword_9D6F20[slot]=0
    # .keep:
    0x66, 0x8B, 0x10,                                  # 24 mov dx, [eax]            ; 重放: dx=*v19 (锁定则0)
    0xC3,                                              # 27 ret
])
