"""补丁应用引擎 — 从 tks_launcher.py 提取 & 重组"""
import os
import json
import struct
from typing import List, Dict, Optional
from .memory import (
    i32b, i16b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex,
    replace_addr_in_bytes,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    _OpenProcess, _CloseHandle,
)
from .scanner import parse_pattern, pattern_scan, value_scan
from .config_loader import PatchDef, PatchConfig, resolve_var

# ============================================================
# Hook 冲突检测
# ============================================================

def check_hook_conflict(code_buf: bytearray, off: int) -> bool:
    """检测 hook 点是否已被其他 MOD 占用

    若目标位置的第一字节已是 E8(call) 或 E9(jmp)，
    说明已被其他补丁/MOD hook，存在冲稁。
    """
    if off < 0 or off >= len(code_buf):
        return False
    return code_buf[off] in (0xE8, 0xE9)

# ============================================================
# Cave 模板 (x86 机器码, 原样复制自 C#)
# ============================================================

CAVE_AWK_SPRITE = bytes([
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

# 战场形象 PATH2: 敌方角色精灵块条件覆盖
# hook 点原指令: add word ptr [ebp+8], 12 (5 字节: 66 83 45 08 0C)
# 逻辑: 若 WORD[260] != 0 → [ebp+8] = WORD[260] (直接使用自定义值)
#       若 WORD[260] == 0 → 保持原始 +12 逻辑
CAVE_AWK_SPRITE2 = bytes([
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

# 队伍头像 PATH1: 选中队员头像查询
# hook 点原指令: add ax, 0xD3; push eax (5 字节)
# 进入时 ecx = char_idx * 527, ax = portrait原始值
# 计算: ecx*2 = char_idx*1054 = 记录字节偏移 (正确!)
CAVE_PORTRAIT1 = bytes([
    0x50, 0x51, 0x52,                                  # push eax, ecx, edx
    0x8B, 0xC1,                                        # mov eax, ecx
    0x85, 0xC0,                                        # test eax, eax
    0x7E, 0x1A,                                        # jle .default (+26)
    0x3D, 0x00, 0x00, 0x02, 0x00,                      # cmp eax, 0x20000
    0x77, 0x13,                                        # ja .default (+19)
    0x03, 0xC0,                                        # add eax, eax (char_idx*1054)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00,         # movzx eax, word[eax+0x20A]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x75, 0x08,                                        # jnz .converge (+8)
    # .default:
    0x8B, 0x44, 0x24, 0x08,                            # mov eax, [esp+8]
    0x66, 0x05, 0xD3, 0x00,                            # add ax, 0xD3
    # .converge:
    0x83, 0xC4, 0x08,                                  # add esp, 8
    0x5A,                                              # pop edx
    0x87, 0x04, 0x24,                                  # xchg [esp], eax
    0xFF, 0xE0,                                        # jmp eax
])

# 队伍头像 PATH2: 非选中队员头像查询
# hook 点原指令: add dx, 0xD3; push edx (6 字节)
# 进入时 eax = char_idx * 527, dx = portrait原始值
# 计算: eax*2 = char_idx*1054 = 记录字节偏移 (正确!)
CAVE_PORTRAIT2 = bytes([
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

# 逆向依据: sub_41AB94 @0x41AD00 (存档界面队伍头像绘制)
# 原指令: movsx eax,byte[ecx+eax*2+0x29E]; add ax,0xD3; push eax
# 修复要点:
#   1. movzx ecx,al 取无符号角色索引 (0..199=有效, 0xFF=空槽)
#   2. cmp cl,0xFF 空槽检查 → 跳过 WarPC 查询避免越界崩溃
#   3. imul eax,ecx,0x41E 三操作数形式, ECX=源, 避免原二操作数 imul 破坏索引
#   4. 默认头像 = 索引 + 0xD3, 自定义头像 = warpc[index].field_0x20A
CAVE_ARCHIVE_PORTRAIT = bytes([
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

CAVE_HISTORY_TEXT = bytes([
    0x52, 0x69, 0xD2, 0x1E, 0x04, 0x00, 0x00, 0x81,
    0xC2, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x82,
    0x0C, 0x02, 0x00, 0x00, 0x85, 0xC0, 0x75, 0x08,
    0x5A, 0x81, 0xC2, 0x5A, 0x23, 0x00, 0x00, 0xC3,
    0x8B, 0xD0, 0x83, 0xC4, 0x04, 0xC3,
])

# 经验加成乘法溢出保护 Cave
# 逆向依据: sub_43B7FC @0x43BA27 exp_bonus 计算
# hook 点: mov edx,[eax]; movsx eax,word[ecx+3Eh]; imul edx,eax (9字节)
# 原始指令被替换为 E8(call)+4xNOP, cave执行后 ret回 +9处 (add edx,99)
# 逻辑:
#   1. mov edx, [eax]              — 加载 *v19 (原始指令1)
#   2. cmp edx, 30000             — 上界检查
#   3. jle .cap_done              — 已在范围内则跳过
#   4. mov edx, 30000             — 钳位到上限 (防止乘法溢出)
#   5. test edx, edx              — 下界检查
#   6. jns .no_neg                — 非负则跳过
#   7. xor edx, edx               — 负值置零
#   8. movsx eax, word[ecx+3Eh]   — 加载 exp_bonus (原始指令2)
#   9. imul edx, eax              — 安全乘法 (max 30000*32767 < INT32_MAX)
#  10. ret                        — 返回到 "add edx, 99"
CAVE_EXP_BONUS_SAFE_MUL = bytes([
    0x8B, 0x10,                                        # mov edx, [eax]
    0x81, 0xFA, 0x30, 0x75, 0x00, 0x00,                # cmp edx, 7530h
    0x7E, 0x05,                                        # jle .cap_done (+5)
    0xBA, 0x30, 0x75, 0x00, 0x00,                      # mov edx, 7530h
    # .cap_done:
    0x85, 0xD2,                                        # test edx, edx
    0x79, 0x02,                                        # jns .no_neg (+2)
    0x33, 0xD2,                                        # xor edx, edx
    # .no_neg:
    0x0F, 0xBF, 0x41, 0x3E,                            # movsx eax, word[ecx+3Eh]
    0x0F, 0xAF, 0xD0,                                  # imul edx, eax
    0xC3,                                              # ret
])

_WARPC_BASE_PLACEHOLDER = 0x757F08

# ============================================================
# Cave 模板: 召唤多随机 (224~231)
# 逆向依据: sub_444BB0 @0x444C83 查表指令; sub_452AC0 rand(n)->0..n-1
# hook 点 0x444C83 (movsx edx,byte[eax+0x4EB6F0], 7字节) -> E8 rel32 + 90 90
# cave 末尾 ret 回 0x444C8A (mov [ebp-2],dx 由原指令写回)
# count=0 走原查表 (向后兼容); count=N 调 sub_452AC0(N) 随机选 cand[0..N-1]
# 唯一动态重定位点: TABLE_BASE 占位符 0x52414E44 (cave 内出现 1 次)
# ============================================================

SUMMON_RANDOM_PLACEHOLDER = 0x52414E44   # "RAND", cave 内唯一, 指向 72 字节候选表

CAVE_SUMMON_RANDOM = bytes([
    0x53,                                              # 0  push ebx
    0x56,                                              # 1  push esi
    0x0F,0xBF,0x1D,0x7C,0x6C,0x9D,0x00,                # 2  movsx ebx, word[0x9D6C7C]
    0x81,0xEB,0xE0,0x00,0x00,0x00,                     # 9  sub ebx, 0xE0  (imm32! 避免 imm8 符号扩展, idx 224..231 -> 0..7)
    0x6B,0xDB,0x09,                                    # 15 imul ebx, ebx, 9       (entry 9 字节)
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 18 add ebx, TABLE_BASE   <- 占位符 (imm32 立即数加, 非[mem]解引用)
    0x8B,0xF3,                                         # 24 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 26 movzx ecx, byte[esi]   (count)
    0x85,0xC9,                                         # 29 test ecx, ecx
    0x74,0x1B,                                         # 31 jz  .default(60)
    0x83,0xF9,0x01,                                    # 33 cmp ecx, 1
    0x76,0x10,                                         # 36 jbe .single(54)
    0x51,                                              # 38 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 39 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 44 call eax               (rand(count))
    0x59,                                              # 46 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 47 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x14,                                         # 52 jmp .done(74)
    0x0F,0xB6,0x56,0x01,                               # 54 .single: movzx edx, byte[esi+1]
    0xEB,0x0E,                                         # 58 jmp .done(74)
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,                # 60 .default: movsx eax, word[0x9D6C7C]
    0x0F,0xBE,0x90,0xF0,0xB6,0x4E,0x00,                # 67 movsx edx, byte[eax+0x4EB6F0]  (原查表)
    0x5E,                                              # 74 .done: pop esi
    0x5B,                                              # 75 pop ebx
    0xC3,                                              # 76 ret
])

# ============================================================
# Cave 模板: 召唤多随机 222/251
# 与 224~231 区别: 222/251 hook 点之后不经 mov[ebp-2],dx, 故 cave 自行写 [ebp-2]
# 合并三段: entry_222(entry8) + entry_251(entry9) + shared(随机选 cand, 写[ebp-2])
# entry_222/entry_251 仅设 entry 常数后 jmp shared; shared 内 rand 选 cand -> [ebp-2]
# 仅在配了 skill_222_random/skill_251_random 时启用对应 hook (count>=1, 无 default 分支)
# ============================================================

CAVE_SUMMON_RANDOM_222_251 = bytes([
    # entry_222 @0  (hook 0x444C9C, ret->0x444CA2 jmp 0x444CCF)
    0x53,                                              # 0  push ebx
    0xBB,0x08,0x00,0x00,0x00,                          # 1  mov ebx, 8            (entry 8)
    0xEB,0x08,                                         # 6  jmp shared(16)
    # entry_251 @8  (hook 0x444CB3, ret->0x444CB8 NOP->0x444CCF)
    0x53,                                              # 8  push ebx
    0xBB,0x09,0x00,0x00,0x00,                          # 9  mov ebx, 9            (entry 9)
    0xEB,0x00,                                         # 14 jmp shared(16)
    # shared @16
    0x56,                                              # 16 push esi
    0x6B,0xDB,0x09,                                    # 17 imul ebx, ebx, 9
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 20 add ebx, TABLE_BASE   <- 占位符 (imm32)
    0x8B,0xF3,                                         # 26 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 28 movzx ecx, byte[esi]  (count, >=1)
    0x83,0xF9,0x01,                                    # 31 cmp ecx, 1
    0x76,0x10,                                         # 34 jbe .single(52)
    0x51,                                              # 36 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 37 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 42 call eax              (rand(count))
    0x59,                                              # 44 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 45 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x04,                                         # 50 jmp .write(56)
    0x0F,0xB6,0x56,0x01,                               # 52 .single: movzx edx, byte[esi+1]
    0x66,0x89,0x55,0xFE,                               # 56 .write: mov [ebp-2], dx
    0x5E,                                              # 60 pop esi
    0x5B,                                              # 61 pop ebx
    0xC3,                                              # 62 ret
])

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
CAVE_WEAPON_CAUSE_MASK = bytes([
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

# Cave 模板: 死战状态决斗自我攻击修复
# 逆向依据: sub_4458B0 @0x445E99 (决斗循环入口, v24=byte_9D6FA4[0])
# hook: movsx ecx, byte ptr [0x9D6FA4] (7字节) -> E8 rel32 + 2xNOP
# 逻辑:
#   1. 执行被替换指令 (movsx ecx, byte [0x9D6FA4]) — 获取决斗目标实体
#   2. 读取 word_9D6F58 获取攻击者实体索引
#   3. 比较目标与攻击者: 相同则跳过决斗循环 (跳转到 0x4460F7)
#   4. 不同则正常返回执行决斗逻辑
# BUG 场景: 死战状态角色使用物品对自身后, 目标列表残留自身实体索引,
#           触发决斗循环导致角色自己攻击自己直到死去
# ============================================================
CAVE_DUEL_SELF_FIX = bytes([
    # 执行被替换指令: 获取决斗目标实体索引
    0x0F,0xBE,0x0D,0xA4,0x6F,0x9D,0x00,               #  0 movsx ecx, byte ptr [0x9D6FA4]

    # 读取攻击者实体索引并比较
    0x50,                                              #  7 push eax
    0x0F,0xBF,0x05,0x58,0x6F,0x9D,0x00,               #  8 movsx eax, word ptr [0x9D6F58]
    0x39,0xC1,                                         # 15 cmp ecx, eax
    0x58,                                              # 17 pop eax
    0x75,0x08,                                         # 18 jne .no_skip (+8) — 目标!=自身, 正常决斗

    # 目标==自身: 修改返回地址跳过决斗循环
    0xC7,0x04,0x24,0xF7,0x60,0x44,0x00,               # 20 mov dword ptr [esp], 0x4460F7
    0xC3,                                              # 27 ret → 跳到 skip_duel

    # .no_skip: 正常返回, 继续决斗
    0xC3,                                              # 28 ret
])

# ============================================================
# Cave 模板构建
# ============================================================

def build_cave_template(name: str, warpc_base: int, log_func=None) -> Optional[bytes]:
    log = log_func or (lambda x: None)
    templates = {
        "awk_sprite": CAVE_AWK_SPRITE,
        "awk_sprite2": CAVE_AWK_SPRITE2,
        "portrait1": CAVE_PORTRAIT1,
        "portrait2": CAVE_PORTRAIT2,
        "archive_portrait": CAVE_ARCHIVE_PORTRAIT,
        "history_text": CAVE_HISTORY_TEXT,
        "exp_bonus_safe_mul": CAVE_EXP_BONUS_SAFE_MUL,
        "weapon_cause_mask": CAVE_WEAPON_CAUSE_MASK,
        "duel_self_fix": CAVE_DUEL_SELF_FIX,
    }
    if name not in templates:
        log(f"    [WARN] 未知 cave 模板: {name}")
        return None
    c = bytearray(templates[name])
    replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
    return bytes(c)

# ============================================================
# 补丁类型: patch_bytes
# ============================================================

def apply_patch_bytes(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       h_proc: int, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    pat, wc = parse_pattern(defn.pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    模式: [{defn.pattern}] -> 匹配 {len(hits)} 处 (预期 {defn.expect_count})")
    if defn.expect_count > 0 and len(hits) != defn.expect_count:
        log(f"  [WARN] 匹配数 {len(hits)} != 预期 {defn.expect_count}")
    ptd = 0
    for off in hits:
        for rk, bv in defn.replace.items():
            ro = int(rk)
            aa = code_start_addr + off + ro
            op = vp_ex(h_proc, aa, 1, PAGE_EXECUTE_READWRITE)
            write_pm(h_proc, aa, bytes([bv & 0xFF]))
            vp_ex(h_proc, aa, 1, op)
            idx = off + ro
            if idx < len(code_buf):
                code_buf[idx] = bv & 0xFF
        log(f"    [OK] RVA 0x{off:X} (abs 0x{code_start_addr + off:08X})")
        ptd += 1
    if ptd == 0 and defn.expect_count > 0:
        log("  [FAIL] 未找到匹配模式")
        return False
    return True

# ============================================================
# 补丁类型: patch_imm32 (value_scan)
# ============================================================

def apply_patch_imm32_by_value(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                h_proc: int, variables: Dict[str, int], log_func=None,
                                exclude_ranges: list = None) -> bool:
    log = log_func or (lambda x: None)
    _excl = exclude_ranges or []
    ov = defn.expect_value
    nv = resolve_var(defn.new_value_expr, variables, log_func=log)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    hits = value_scan(bytes(code_buf), ov)
    log(f"    扫描值 {ov} (0x{ov:X}) -> 匹配 {len(hits)} 处")
    log(f"    替换为 {nv} (0x{nv:X})")
    nle = i32b(nv); ptd = 0
    for off in hits:
        # 安全检查: 跳过 call/jmp 指令的 rel32 偶然匹配, 避免破坏 hook 指令
        if off >= 1 and code_buf[off - 1] in (0xE8, 0xE9):
            log(f"    [SKIP] RVA 0x{off:X}: 前字节为 E8/E9 (call/jmp rel32), 跳过")
            continue
        # 第三方 MOD 兼容: 排除额外段
        if _excl and defn.exclude_extra_sections:
            abs_a = code_start_addr + off
            skip = False
            for ex_start, ex_end in _excl:
                if ex_start <= abs_a < ex_end:
                    log(f"    [SKIP] RVA 0x{off:X}: 位于 MOD 额外段内")
                    skip = True
                    break
            if skip:
                continue
        aa = code_start_addr + off
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if off + 4 <= len(code_buf):
            code_buf[off:off+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    return True

# ============================================================
# 补丁类型: patch_imm32 (pattern scan)
# ============================================================

def apply_patch_imm32_by_pattern(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                  h_proc: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    pat, wc = parse_pattern(defn.pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    模式: [{defn.pattern}] -> 匹配 {len(hits)} 处")
    nv = resolve_var(defn.new_value_expr, variables, log_func=log); ov = defn.expect_value
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    nle = i32b(nv); ptd = 0
    for off in hits:
        io = off + defn.value_offset
        if io + 4 <= len(code_buf):
            act = b2i32(bytes(code_buf), io)
            if ov != 0 and act != ov:
                log(f"    [SKIP] RVA 0x{off:X}: 原值 0x{act:08X} != 预期 0x{ov:08X}")
                continue
        aa = code_start_addr + io
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if io + 4 <= len(code_buf):
            code_buf[io:io+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    return True

# ============================================================
# 补丁类型: cave_hook
# ============================================================

def apply_cave_hook(defn: PatchDef, hits: List[int], code_buf: bytearray,
                     code_start_addr: int, h_proc: int, cave_addr: int,
                     warpc_base: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    if not hits:
        log("    [WARN] 未找到 hook 点")
        return False

    cd = build_cave_template(defn.cave_template, warpc_base, log_func=log)
    if cd is None:
        return False

    ct = cave_addr + defn.cave_offset
    write_pm(h_proc, ct, cd)
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")

    ptd = 0
    for off in hits:
        ha = code_start_addr + off
        co = (ct - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(defn.hook_size)
        ci[0] = 0xE8
        ci[1:5] = i32b(co)
        for i in range(5, defn.hook_size):
            ci[i] = 0x90

        op = vp_ex(h_proc, ha, defn.hook_size, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, defn.hook_size, op)

        for i in range(min(defn.hook_size, len(code_buf) - off)):
            code_buf[off + i] = ci[i]

        log(f"    [OK] Hook RVA 0x{off:X} -> call 0x{ct:08X}")
        ptd += 1

    return ptd > 0

# ============================================================
# 补丁类型: patch_summon_table (召唤表自定义)
# 逆向依据: sub_444BB0 召唤角色选择; stru_4EB6F0 区域 .data 8字节 (技能224~231)
#           + sub_444BB0 内 3 处 imm16 立即数 (技能222/251_a/251_b)
# JSON 值为 WarPC 索引 (= i+36), 写入时换算 i = WarPC-36
# ============================================================

def apply_summon_table(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       base_addr: int, h_proc: int, variables: Dict[str, int],
                       log_func=None, cave_addr: int = 0) -> bool:
    log = log_func or (lambda x: None)
    all_ok = True

    # Step 0: 读取召唤表 JSON
    if not defn.json_file or not os.path.isfile(defn.json_file):
        log(f"    [WARN] 召唤表 JSON 不存在: {defn.json_file!r}, 跳过")
        return True
    try:
        with open(defn.json_file, 'r', encoding='utf-8') as f:
            summon = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析召唤表 JSON 失败: {e}")
        return False
    log(f"    JSON: {len(summon)} 个键")

    # Step 1: WarPC 记录数上限 (用于值域校验)
    rec_size = variables.get("warpc_rec_size", 1054)
    new_size = variables.get("warpc_new_size", 150722)
    max_count = new_size // rec_size if rec_size > 0 else 143

    def _warpc_i(warpc_idx, imm16):
        if not isinstance(warpc_idx, (int,)):
            return None, f"非整数: {warpc_idx!r}"
        if warpc_idx < 36 or warpc_idx >= max_count:
            return None, f"WarPC索引 {warpc_idx} 越界 (36..{max_count-1})"
        i = warpc_idx - 36
        limit = 65535 if imm16 else 255
        if i < 0 or i > limit:
            return None, f"i值 {i} 越界 (0..{limit})"
        return i, None

    # Step 2: 写 .data 8 字节 (技能 224~231) — .data 段通常 PAGE_READWRITE
    if defn.data_rva and defn.data_keys:
        tbl_abs = base_addr + defn.data_rva
        tbl_off = defn.data_rva - 0x1000
        if tbl_off < 0 or tbl_off + 8 > len(code_buf):
            log(f"  [ERROR] .data 偏移越界")
            all_ok = False
        else:
            cur = bytearray(code_buf[tbl_off:tbl_off + 8])
            changed = False
            for k, key in enumerate(defn.data_keys):
                if key not in summon:
                    continue
                i, err = _warpc_i(summon[key], imm16=False)
                if err:
                    log(f"    [WARN] {key}: {err}, 跳过")
                    continue
                if cur[k] != (i & 0xFF):
                    log(f"    {key}: i {cur[k]}->{i & 0xFF} (WarPC {cur[k]+36}->{summon[key]})")
                    changed = True
                cur[k] = i & 0xFF
            if changed:
                nw = write_pm(h_proc, tbl_abs, bytes(cur))
                code_buf[tbl_off:tbl_off + 8] = bytes(cur)
                log(f"    [OK] .data @0x{tbl_abs:08X} 写入{nw}/{len(cur)}字节")
                if nw != len(cur):
                    all_ok = False
            else:
                log(f"    -> .data 与默认值一致")

    # Step 3: 写代码段 imm16 — 使用独立句柄确保写入成功
    _pid = variables.get("_target_pid", 0)
    if not _pid:
        log("  [WARN] 缺少 target_pid, 跳过 imm16 补丁")
        return all_ok
    _hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                        False, _pid)
    if not _hp:
        log(f"  [WARN] OpenProcess(PID={_pid}) 失败, 跳过 imm16 补丁")
        return all_ok

    for site in defn.code_addrs:
        key = site.get("key", "")
        rva_str = site.get("rva", "")
        if not key or not rva_str:
            continue
        rva = int(rva_str, 16) if isinstance(rva_str, str) else int(rva_str)
        abs_addr = base_addr + rva
        if key not in summon:
            continue
        i, err = _warpc_i(summon[key], imm16=True)
        if err:
            log(f"    [WARN] {key}: {err}, 跳过")
            continue
        imm = i16b(i)
        nw = write_pm(_hp, abs_addr, imm)
        if nw == 2:
            log(f"    [OK] {key} i={i} @abs 0x{abs_addr:08X}")
        else:
            log(f"  [FAIL] {key}: WriteProcessMemory 失败 @abs 0x{abs_addr:08X}")
            all_ok = False
        cb_off = abs_addr - code_start_addr
        if 0 <= cb_off + 2 <= len(code_buf):
            code_buf[cb_off:cb_off + 2] = imm

    # Step 4: 多随机 cave 注入 (skill_224~231 的 *_random 列表)
    # 复用 Step 3 句柄 _hp (确保随机 cave 写入成功)
    # data_keys 顺序 = entry 顺序 (224~231 -> entry 0~7); 列表键名 = data_keys[k] + "_random"
    rnd_pat_str = defn.random_hook_pattern
    if rnd_pat_str and defn.random_cave_offset and defn.random_table_offset:
        if not cave_addr:
            log("  [WARN] 无 cave 内存, 跳过多随机注入")
        else:
            all_ok &= _apply_summon_random(defn, summon, code_buf, code_start_addr,
                                            _hp, cave_addr, _warpc_i, log)

    _CloseHandle(_hp)
    return all_ok


def _apply_summon_random(defn: PatchDef, summon: dict, code_buf: bytearray,
                         code_start_addr: int, h_proc: int, cave_addr: int,
                         warpc_i_fn, log_func=None) -> bool:
    """多随机 cave: 读 *_random 列表 -> 90字节候选表 + cave代码 + hooks
    224~231 (entry 0~7, entry_224 cave, hook 0x444C84, 结果->edx)
    222 (entry 8, 合并 cave entry_222, hook 0x444C9C, 结果->[ebp-2])
    251 (entry 9, 合并 cave entry_251, hook 0x444CB3, 结果->[ebp-2])"""
    log = log_func or (lambda x: None)

    # 4a. 收集候选列表 -> 90 字节候选表 (entry 0~7=224~231, 8=222, 9=251)
    table = bytearray(90)        # 10 entry x 9 字节
    any_random = False
    has_224 = False              # 224~231 任一配了 -> 需 224~231 cave+hook
    extra_hooks_to_apply = []    # 222/251 hooks: [{entry_idx, ...hook_cfg}]

    def collect(rkey, entry_idx):
        nonlocal any_random, has_224
        lst = summon.get(rkey)
        if not isinstance(lst, list) or not lst:
            return False
        if len(lst) > 8:
            log(f"    [WARN] {rkey}: 候选 {len(lst)} > 8, 截断为 8")
            lst = lst[:8]
        cand = []
        for w in lst:
            ii, err = warpc_i_fn(w, imm16=False)   # i 值域 0..255 (byte 存储)
            if err:
                log(f"    [WARN] {rkey}: WarPC {w} {err}, 跳过该技能随机")
                return False
            cand.append(ii & 0xFF)
        table[entry_idx * 9] = len(cand)
        for j, c in enumerate(cand):
            table[entry_idx * 9 + 1 + j] = c
        any_random = True
        log(f"    {rkey}: {len(cand)} 候选 i={cand} (WarPC={[c + 36 for c in cand]})")
        return True

    # 224~231 (entry 0~7)
    for k, key in enumerate(defn.data_keys):
        if collect(key + "_random", k):
            has_224 = True

    # 222 (entry 8) / 251 (entry 9), 按 random2_hooks 配置收集
    for hk in defn.random2_hooks:
        jkey = hk.get("json_key", "")
        eidx = hk.get("entry_idx", 0)
        if collect(jkey, eidx):
            extra_hooks_to_apply.append(hk)

    if not any_random:
        log("    -> 无 *_random 配置, 跳过多随机 cave")
        return True

    # 4b. 写 90 字节候选表
    table_abs = cave_addr + defn.random_table_offset
    if write_pm(h_proc, table_abs, bytes(table)) != len(table):
        log(f"  [FAIL] 候选表写入失败 @0x{table_abs:08X}")
        return False
    log(f"    [OK] 候选表 @0x{table_abs:08X} (90 字节)")

    all_ok = True

    # 4c. 224~231: entry_224 cave + hook 0x444C84 (结果->edx, 由原 mov[ebp-2],dx 写回)
    if has_224:
        all_ok &= _write_cave_and_hook(
            CAVE_SUMMON_RANDOM, defn.random_cave_offset, 0,           # cave 代码, 入口偏移 0
            defn.random_hook_pattern, defn.random_hook_size, defn.random_hook_expect_count,
            table_abs, code_buf, code_start_addr, h_proc, cave_addr,
            warpc_i_fn, log, tag="224~231")

    # 4d. 222/251: 合并 cave (entry_222+entry_251+shared) + 各 hook
    if extra_hooks_to_apply:
        cave2_abs = cave_addr + defn.random2_cave_offset
        cave2_code = bytearray(CAVE_SUMMON_RANDOM_222_251)
        if cave2_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] 222/251 cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave2_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        if write_pm(h_proc, cave2_abs, bytes(cave2_code)) != len(cave2_code):
            log(f"  [FAIL] 222/251 cave 代码写入失败 @0x{cave2_abs:08X}")
            return False
        log(f"    [OK] 222/251 cave @0x{cave2_abs:08X} ({len(cave2_code)} 字节)")
        for hk in extra_hooks_to_apply:
            all_ok &= _write_cave_and_hook(
                None, defn.random2_cave_offset, hk.get("entry_offset", 0),  # 复用已写 cave, 仅 hook
                hk.get("pattern", ""), hk.get("hook_size", 0), hk.get("expect_count", 0),
                table_abs, code_buf, code_start_addr, h_proc, cave_addr,
                warpc_i_fn, log, tag=hk.get("json_key", ""),
                prewritten_cave_abs=cave2_abs)

    return all_ok


def _write_cave_and_hook(cave_template: Optional[bytes], cave_offset: int, entry_offset: int,
                         hook_pattern: str, hook_size: int, expect_count: int,
                         table_abs: int, code_buf: bytearray, code_start_addr: int,
                         h_proc: int, cave_addr: int, warpc_i_fn, log_func,
                         tag: str = "", prewritten_cave_abs: int = 0) -> bool:
    """写 cave 代码 (若提供 template) + 写 hook. cave 入口 = cave_addr+cave_offset+entry_offset.
    prewritten_cave_abs>0 时跳过 cave 写入 (复用已写代码), 仅写 hook 指向该地址+entry_offset."""
    log = log_func or (lambda x: None)

    # 写 cave 代码 (224~231); 222/251 复用已写合并代码
    if cave_template is not None:
        cave_code = bytearray(cave_template)
        if cave_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] [{tag}] cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        cave_abs = cave_addr + cave_offset
        if write_pm(h_proc, cave_abs, bytes(cave_code)) != len(cave_code):
            log(f"  [FAIL] [{tag}] cave 代码写入失败 @0x{cave_abs:08X}")
            return False
        log(f"    [OK] [{tag}] cave 代码 @0x{cave_abs:08X} ({len(cave_code)} 字节, TABLE_BASE->0x{table_abs:08X})")
    else:
        cave_abs = prewritten_cave_abs

    hook_target = cave_abs + entry_offset   # call 目标 (222/251 为合并 cave 内入口)

    # 写 hook: E8 rel32 + NOP 填充
    if not hook_pattern or not hook_size:
        log(f"  [WARN] [{tag}] 无 hook 配置, 跳过")
        return True
    pat, wc = parse_pattern(hook_pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    if expect_count > 0 and len(hits) != expect_count:
        log(f"  [WARN] [{tag}] hook 匹配 {len(hits)} 处 (预期 {expect_count}), 跳过")
        return False
    if not hits:
        log(f"  [WARN] [{tag}] hook 模式无匹配, 跳过")
        return False

    hsz = hook_size
    for off in hits:
        ha = code_start_addr + off
        co = (hook_target - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(hsz)
        ci[0] = 0xE8
        ci[1:5] = i32b(co)
        for i in range(5, hsz):
            ci[i] = 0x90
        op = vp_ex(h_proc, ha, hsz, PAGE_EXECUTE_READWRITE)
        nw = write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, hsz, op)
        if nw != hsz:
            log(f"  [FAIL] [{tag}] hook 写入失败 @RVA 0x{off:X}")
            return False
        for i in range(min(hsz, len(code_buf) - off)):
            code_buf[off + i] = ci[i]
        log(f"    [OK] [{tag}] hook @RVA 0x{off:X} (abs 0x{ha:08X}) -> cave 0x{hook_target:08X}")
    return True

# ============================================================
# 配置补丁编排
# ============================================================

def apply_config_patches(config: PatchConfig, code_buf: bytearray, code_start_addr: int,
                          base_addr: int, h_proc: int, warpc_base: int, cave_addr: int,
                          variables: Dict[str, int], log_func=None,
                          minimal_mode=False, no_cave_mode=False,
                          only_portrait=False, only_awk=False,
                          selected_patches: set = None,
                          exe_profile=None) -> bool:
    """配置补丁编排

    Args:
        exe_profile: ExeProfile 实例, 用于第三方 MOD 兼容检测。
                     若为 None 则按原版处理。
    """
    log = log_func or (lambda x: None)
    all_ok = True
    pch: List[PatchDef] = []

    # 第三方 MOD 兼容: 从 profile 获取应跳过的补丁
    _profile_skip = set()
    _profile_name = "original"
    if exe_profile is not None:
        _profile_skip = exe_profile.skip_patches or set()
        _profile_name = exe_profile.name

    for defn in config.patches:
        tag = f"[{defn.id}]"
        log(f"\n  {tag}: {defn.desc}")

        if selected_patches is not None and defn.optional and defn.id not in selected_patches:
            log(f"    -> 用户取消勾选, 跳过")
            continue

        # 第三方 MOD 兼容: profile_rules 检查
        if defn.profile_rules:
            rule = defn.profile_rules.get(_profile_name,
                                         defn.profile_rules.get("_default", "apply"))
            if rule == "skip":
                log(f"    -> profile '{_profile_name}' 规则: 跳过")
                continue

        # 第三方 MOD 兼容: profile skip_patches 检查
        if defn.id in _profile_skip:
            log(f"    -> 第三方 MOD 版本自动跳过")
            continue

        if defn.type == "patch_bytes":
            all_ok &= apply_patch_bytes(defn, code_buf, code_start_addr, h_proc, log_func=log)
        elif defn.type == "cave_hook":
            hp = defn.hook_pattern or defn.pattern
            hpat, hwc = parse_pattern(hp or "")
            hh = pattern_scan(bytes(code_buf), hpat, hwc)
            if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
                # 模式匹配失败 — 尝试 fallback_rva 回退定位
                if len(hh) == 0 and defn.fallback_rva > 0:
                    # fallback_rva 是相对于基址的偏移, 转为 code_buf 内偏移
                    fb_off = defn.fallback_rva - 0x1000  # RVA -> code_buf offset
                    if 0 <= fb_off < len(code_buf) - defn.hook_size:
                        hh = [fb_off]
                        log(f"  {tag}: 模式无匹配, 使用 fallback_rva 0x{defn.fallback_rva:X} (offset 0x{fb_off:X})")
                    else:
                        log(f"  {tag}: fallback_rva 0x{defn.fallback_rva:X} 越界, 跳过")
                        continue
                elif len(hh) == 0 and exe_profile and exe_profile.has_extra_sections:
                    log(f"  {tag}: Hook 模式无匹配 (MOD 已修改, 无 fallback), 跳过")
                    continue
                else:
                    log(f"  {tag}: Hook 模式匹配 {len(hh)} 处 (预期 {defn.hook_expect_count}), 跳过")
                    continue
            # Hook 冲突检测: 检查 hook 点是否已被占用
            if hh and check_hook_conflict(code_buf, hh[0]):
                action = defn.hook_conflict_action
                if action == "override":
                    log(f"  {tag}: Hook 点已被占用, 启动器优先级最高 → 覆盖")
                elif action == "skip":
                    log(f"  {tag}: Hook 点已被占用 (E8/E9 开头), 跳过")
                    continue
                else:
                    log(f"  {tag}: [WARN] Hook 点已被占用, 但仍尝试应用")
            defn._pre_scanned_hits = hh
            pch.append(defn)
        elif defn.type == "patch_imm32":
            if defn.value_scan:
                nv = resolve_var(defn.new_value_expr, variables, log_func=log)
                if nv is None:
                    log(f"    -> 变量未定义, 跳过")
                    continue
                if defn.expect_value != 0 and nv == defn.expect_value:
                    log(f"    -> 值未变化 ({defn.expect_value}), 跳过")
                    continue
                all_ok &= apply_patch_imm32_by_value(defn, code_buf, code_start_addr, h_proc, variables, log_func=log,
                                                       exclude_ranges=exe_profile.extra_section_ranges if exe_profile else None)
            else:
                all_ok &= apply_patch_imm32_by_pattern(defn, code_buf, code_start_addr, h_proc, variables, log_func=log)
        elif defn.type == "patch_warpc_addr":
            log(f"    -> 由 WarPC 扩展流程处理 (base=0x{warpc_base:08X})")
        elif defn.type == "patch_summon_table":
            all_ok &= apply_summon_table(defn, code_buf, code_start_addr, base_addr,
                                          h_proc, variables, log_func=log,
                                          cave_addr=cave_addr)
        elif defn.type == "runtime_watchdog":
            log(f"    -> 由运行时看门狗处理 (游戏运行期间持续监控)")
        else:
            log(f"  [WARN] 未知补丁类型: {defn.type}")

    if pch and not minimal_mode and not no_cave_mode:
        hta = pch
        if only_portrait:
            hta = [h for h in pch if h.id in ("portrait_cave1", "portrait_cave2")]
        elif only_awk:
            hta = [h for h in pch if h.id == "awk_sprite_cave"]
        log(f"\n  应用 {len(hta)} 个 cave hooks...")
        for defn in hta:
            all_ok &= apply_cave_hook(defn, defn._pre_scanned_hits, code_buf,
                                       code_start_addr, h_proc, cave_addr,
                                       warpc_base, variables, log_func=log)
    return all_ok

# ============================================================
# [补丁十二] sub_4C33FC 入口检查修补
# ============================================================

def patch_4c33fc(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0xC33FC
    log("\n--- [补丁十二] sub_4C33FC 入口检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 32:
        log(f"  [ERROR] 读取 sub_4C33FC@0x{av:08X} 失败"); _CloseHandle(hp); return

    co, cmr = -1, 0
    for i in range(min(nr, 32) - 4):
        if buf[i]==0x80 and (buf[i+1]&0xF8)==0x78 and buf[i+2]==0x0C and buf[i+3]==0x00:
            co, cmr = i, buf[i+1]; break

    if co < 0:
        log("  [WARN] 未找到 cmp [reg+0Ch],0 模式, 跳过"); _CloseHandle(hp); return

    bo, bo2 = buf[co+4], buf[co+5]
    ba = av + co + 4

    if bo == 0x74:
        pb = bytes([0xEB, bo2]); pd = "je short -> jmp short"
    elif bo == 0x75:
        pb = bytes([0x90, 0x90]); pd = "jne short -> NOP NOP"
    elif bo == 0x0F and bo2 == 0x84:
        imm = b2i32(buf, co+6)
        pb = bytearray(6); pb[0]=0xE9; pb[1:5]=i32b(imm+1); pb[5]=0x90
        pd = "je near -> jmp near + NOP"
    elif bo == 0x0F and bo2 == 0x85:
        pb = bytes([0x90]*6); pd = "jne near -> NOP x 6"
    else:
        log(f"  [WARN] 未识别 je/jne, 跳过"); _CloseHandle(hp); return

    op = vp_ex(hp, ba, len(pb), PAGE_EXECUTE_READWRITE)
    nw = write_pm(hp, ba, pb)
    vp_ex(hp, ba, len(pb), op)
    if nw == len(pb):
        log(f"  [OK] sub_4C33FC+0x{co+4:X} 修补成功 ({pd})")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十三] sub_41C120 stream error 检查修补
# ============================================================

def patch_41c120(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0x1C120
    log("\n--- [补丁十三] sub_41C120 stream error 检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 16:
        log(f"  [ERROR] 读取 sub_41C120@0x{av:08X} 失败"); _CloseHandle(hp); return

    lo = -1
    for i in range(min(nr, 32) - 5):
        if buf[i]==0x8B and buf[i+1]==0x4A and buf[i+2]==0x08 and buf[i+3]==0x85 and buf[i+4]==0xC9:
            lo = i; break

    if lo < 0:
        log("  [WARN] 未找到模式, 跳过"); _CloseHandle(hp); return

    if (lo+13>nr or buf[lo+5]!=0x0F or buf[lo+6]!=0x94 or buf[lo+7]!=0xC0
        or buf[lo+8]!=0x83 or buf[lo+9]!=0xE0 or buf[lo+10]!=0x01
        or buf[lo+11]!=0x84 or buf[lo+12]!=0xC0):
        log("  [WARN] sete/and/test 后续不匹配, 跳过"); _CloseHandle(hp); return

    pb = bytes([0xC7,0x42,0x08,0x00,0x00,0x00,0x00, 0xB0,0x01, 0x84,0xC0, 0x90,0x90])
    pa = av + lo
    op = vp_ex(hp, pa, 13, PAGE_EXECUTE_READWRITE)
    nw = write_pm(hp, pa, pb)
    vp_ex(hp, pa, 13, op)
    if nw == 13:
        log(f"  [OK] sub_41C120+0x{lo:X} 清零补丁成功")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十四] 存档界面队伍头像 hook
# ============================================================

def patch_archive_portrait(cpid: int, base: int, cave_addr: int, warpc_base: int, log_func=None):
    """独立于 cave_hook 系统: 自开句柄, 写洞穴代码 + hooks"""
    log = log_func or (lambda x: None)
    sr = 0x1AB94; ssz = 0x500
    log("\n--- [补丁十四] 存档界面队伍头像 hook ---")
    if cave_addr == 0:
        log("  [WARN] ArchivePortraitCave 未分配, 跳过"); return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    # Step 1: 写入洞穴代码
    cd = build_cave_template("archive_portrait", warpc_base, log_func=log)
    if cd:
        nw = write_pm(hp, cave_addr, cd)
        log(f"    Cave 写入: 0x{cave_addr:08X} ({nw}/{len(cd)} bytes)")

    # Step 2: 扫描 sub_41AB94 写入 hooks
    av = base + sr
    buf, nr = read_pm(hp, av, ssz)
    if nr < 64:
        log(f"  [ERROR] 读取 sub_41AB94@0x{av:08X} 失败"); _CloseHandle(hp); return

    ptd = 0
    for i in range(nr - 5):
        if buf[i]==0x66 and buf[i+1]==0x05 and buf[i+2]==0xD3 and buf[i+3]==0x00 and buf[i+4]==0x50:
            hrva = sr + i; ha = base + hrva
            co = (cave_addr - (ha + 5)) & 0xFFFFFFFF
            cd_hook = bytearray(5); cd_hook[0]=0xE8; cd_hook[1:5]=i32b(co)
            op = vp_ex(hp, ha, 5, PAGE_EXECUTE_READWRITE)
            nw = write_pm(hp, ha, bytes(cd_hook))
            vp_ex(hp, ha, 5, op)
            if nw == 5:
                ptd += 1
                log(f"    [OK] RVA 0x{hrva:X}: hook add ax,0xD3+push eax -> cave")

    log(f"  共 hook {ptd} 处")
    _CloseHandle(hp)

# ============================================================
# [补丁十七] 存档界面金钱显示修复
# ============================================================

def patch_gold_display(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0x1AB94; ssz = 0x600
    log("\n--- [补丁十七] 存档界面金钱显示修复 (signed->unsigned) ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, ssz)
    if nr < 64:
        log(f"  [ERROR] 读取 sub_41AB94@0x{av:08X} 失败"); _CloseHandle(hp); return

    gp = bytes([0x0F,0xBF,0x84,0x41,0xD4,0x02,0x00,0x00])
    ptd = 0
    for i in range(nr - len(gp) + 1):
        if buf[i:i+len(gp)] == gp:
            ha = base + sr + i
            fix = bytes([0x0F, 0xB7])
            op = vp_ex(hp, ha, 2, PAGE_EXECUTE_READWRITE)
            nw = write_pm(hp, ha, fix)
            vp_ex(hp, ha, 2, op)
            if nw == 2:
                ptd += 1
                log(f"    [OK] RVA 0x{sr + i:05X}: movsx->movzx")

    log(f"  共修补 {ptd} 处")
    _CloseHandle(hp)

# ============================================================
# [补丁十八] 存档加载后自动重注入头像数据
# ============================================================

# 重注入 Cave 在主 cave 内的偏移 (1024 字节总分配, 前 706 字节已使用)
REINJECT_CAVE_OFFSET = 768

def find_load_hook_points(code_buf: bytes, warpc_base: int,
                          warpc_size: int = 150722, log_func=None) -> List[int]:
    """
    定位游戏存档加载函数中 System.Move 将存档数据写入 WarPC BSS 的调用点。

    Delphi fastcall: Move(source: EAX, dest: EDX, count: ECX)
    模式:
      mov edx, warpc_base   (BA xx xx xx xx)
      ...                    (0-20 字节, 设置 EAX=source)
      mov ecx, warpc_size   (B9 xx xx xx xx)
      call @System.Move     (E8 xx xx xx xx)
      <hook_point>           ← 返回后的第一条指令

    返回所有匹配的 hook_point 的 RVA 列表 (code_buf 内偏移)。
    """
    log = log_func or (lambda x: None)
    log("\n--- [补丁十八] 定位存档加载 Move 调用 ---")

    base_le = warpc_base.to_bytes(4, 'little')
    size_le = struct.pack('<I', warpc_size)
    mov_ecx = bytes([0xB9]) + size_le       # B9 + size LE
    mov_edx = bytes([0xBA]) + base_le       # BA + base LE

    hook_points: List[int] = []
    pos = 0
    end = len(code_buf) - 15

    while pos < end:
        # 第一步: 找到 "mov ecx, warpc_size"
        idx = code_buf.find(mov_ecx, pos)
        if idx == -1 or idx >= end:
            break

        # 第二步: 紧跟其后应为 E8 (call) — 允许 0~2 字节间距
        call_pos = -1
        for delta in range(0, 3):
            check = idx + 5 + delta
            if check < len(code_buf) and code_buf[check] == 0xE8:
                call_pos = check
                break

        if call_pos == -1:
            pos = idx + 1
            continue

        # 第三步: 回溯 30 字节内寻找 "mov edx, warpc_base"
        found_edx = False
        for back in range(5, 35):
            cp = idx - back
            if cp < 0:
                break
            if code_buf[cp:cp + 5] == mov_edx:
                found_edx = True
                break

        if not found_edx:
            pos = idx + 1
            continue

        # hook 点 = call 指令之后 (call 是 5 字节: E8 + rel32)
        hp_rva = call_pos + 5
        hook_points.append(hp_rva)
        log(f"  找到 Load Move: RVA 0x{idx:X} (call@0x{call_pos:X}) → hook@0x{hp_rva:X}")
        pos = hp_rva

    if not hook_points:
        log("  [WARN] 未定位到 Move(*, warpc_base, size) 调用")
    else:
        log(f"  共定位 {len(hook_points)} 处候选 hook 点")
    return hook_points


def hook_save_load_portrait(cpid: int, base_addr: int, code_buf: bytearray,
                            code_start: int, cave_addr: int, warpc_base: int,
                            warpc_data: bytes, char_count: int,
                            hook_rvas: List[int], log_func=None):
    """
    在游戏存档加载函数返回处安装 hook, 自动从预存表重写 field_0x208/0x20A。

    参数:
        cpid:        游戏进程 PID
        base_addr:   模块基址
        code_buf:    代码段缓冲区 (已修补后的, 用于读取原始字节)
        code_start:  代码段起始地址
        cave_addr:   cave 内存基址 (VirtualAllocEx 分配的 1024 字节)
        warpc_base:  WarPC BSS 基址 (可能已重定位)
        warpc_data:  WarPC 完整解压数据 (从 .dat 读取的 mod 版本)
        char_count:  角色数量
        hook_rvas:   find_load_hook_points 返回的 hook 点 RVA 列表
        log_func:    日志函数
    """
    log = log_func or (lambda x: None)
    log("\n--- [补丁十八] 安装存档加载 portrait 重注入 hook ---")

    if not hook_rvas:
        log("  [SKIP] 无有效 hook 点")
        return
    if cave_addr == 0:
        log("  [SKIP] Cave 未分配")
        return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败")
        return

    # === 1. 分配并写入 portrait 表 ===
    # 每个角色 4 字节: [W260 uint16][W261 uint16] (小端序连续存放)
    WARPC_REC_SIZE = 1054
    table_size = char_count * 4
    alloc_size = max(table_size, 1024)  # 至少 1KB

    from .memory import MEM_COMMIT, MEM_RESERVE, PAGE_READWRITE, _VirtualAllocEx
    import ctypes as _ctypes
    tbl_ptr = _VirtualAllocEx(hp, None, alloc_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not tbl_ptr:
        log("  [ERROR] VirtualAllocEx (portrait table) 失败")
        _CloseHandle(hp)
        return
    table_addr = _ctypes.cast(tbl_ptr, _ctypes.c_void_p).value or 0
    log(f"  Portrait 表: 0x{table_addr:08X} ({char_count} 条, {table_size} 字节)")

    # 构建表数据
    table_data = bytearray(table_size)
    injected = 0
    for i in range(char_count):
        bo = i * WARPC_REC_SIZE
        if bo + 524 > len(warpc_data):
            break
        w260 = int.from_bytes(warpc_data[bo + 520:bo + 522], 'little')  # field_0x208
        w261 = int.from_bytes(warpc_data[bo + 522:bo + 524], 'little')  # field_0x20A
        dword_val = w260 | (w261 << 16)
        struct.pack_into('<I', table_data, i * 4, dword_val)
        if dword_val:
            injected += 1
    log(f"  有效条目: {injected}/{char_count}")

    write_pm(hp, table_addr, bytes(table_data))

    # === 2. 构建 reinject cave 代码 ===
    # Cave 逻辑: pushad; 遍历表写入 warpc[i].0x208; popad; 原始指令; jmp back
    cave_code_addr = cave_addr + REINJECT_CAVE_OFFSET

    # 对每个 hook 点安装独立 cave (由于 jmp-back 地址不同)
    # 使用 REINJECT_CAVE_OFFSET + i*64 避免重叠
    for hi, hook_rva in enumerate(hook_rvas):
        hook_abs = code_start + hook_rva
        this_cave_addr = cave_code_addr + hi * 64

        # 读取 hook 点处的 5 字节原始指令
        orig_bytes = bytes(code_buf[hook_rva:hook_rva + 5])

        # 构建 cave 机器码
        cave = bytearray()
        cave.append(0x60)                                    # pushad
        cave.append(0xBE); cave += struct.pack('<I', table_addr)    # mov esi, TABLE_ADDR
        cave.append(0xBF); cave += struct.pack('<I', warpc_base)   # mov edi, WARPC_BASE
        cave.append(0xB9); cave += struct.pack('<I', char_count)   # mov ecx, CHAR_COUNT
        # .loop:
        cave += bytes([0x8B, 0x06])                          # mov eax, [esi]
        cave += bytes([0x85, 0xC0])                          # test eax, eax
        cave += bytes([0x74, 0x06])                          # jz .skip (+6)
        cave += bytes([0x89, 0x87, 0x08, 0x02, 0x00, 0x00]) # mov [edi+0x208], eax
        # .skip:
        cave += bytes([0x83, 0xC6, 0x04])                    # add esi, 4
        cave += bytes([0x81, 0xC7, 0x1E, 0x04, 0x00, 0x00]) # add edi, 0x41E
        cave += bytes([0xE2, 0xE9])                          # loop .loop (rel8=-23)
        cave.append(0x61)                                    # popad
        cave += orig_bytes                                   # 原始覆盖指令
        # jmp back to hook_point + 5
        jmp_target = hook_abs + 5
        jmp_source = this_cave_addr + len(cave) + 5          # E9 指令之后的地址
        jmp_rel = (jmp_target - jmp_source) & 0xFFFFFFFF
        cave.append(0xE9); cave += struct.pack('<I', jmp_rel) # jmp back

        log(f"  Cave[{hi}]: 0x{this_cave_addr:08X} ({len(cave)} bytes)")

        # 写入 cave 代码
        write_pm(hp, this_cave_addr, bytes(cave))

        # === 3. 安装 hook (5 字节 jmp) ===
        jmp_to_cave_rel = (this_cave_addr - (hook_abs + 5)) & 0xFFFFFFFF
        hook_patch = bytearray(5)
        hook_patch[0] = 0xE9                                  # jmp rel32
        struct.pack_into('<I', hook_patch, 1, jmp_to_cave_rel)

        op = vp_ex(hp, hook_abs, 5, PAGE_EXECUTE_READWRITE)
        nw = write_pm(hp, hook_abs, bytes(hook_patch))
        vp_ex(hp, hook_abs, 5, op)

        if nw == 5:
            log(f"  [OK] Hook[{hi}] @ RVA 0x{hook_rva:X} (abs 0x{hook_abs:08X}) → cave 0x{this_cave_addr:08X}")
            # 更新本地 code_buf
            code_buf[hook_rva:hook_rva + 5] = hook_patch
        else:
            log(f"  [FAIL] Hook[{hi}] WriteProcessMemory 失败")

    _CloseHandle(hp)
    log(f"  存档加载 hook 安装完成: {len(hook_rvas)} 处")
