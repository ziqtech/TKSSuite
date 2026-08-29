# -*- coding: utf-8 -*-
"""
战斗技能菜单溢出保护 (skill_menu_cap) — cave 带注释机器码源

战斗技能菜单封顶 12 项：同一技能组已学子技能超过 12 个时只显示前 12 个, 不再溢出踩坏相邻数据 (sub_438F28 + sub_447BA8 双 hook), 修复战斗菜单错乱/崩溃

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# Cave: 战斗技能菜单封顶 12 项 (skill_menu_cap)
# 逆向依据: sub_438F28 @0x439049 / sub_447BA8 @0x447C6B (两处指令序列完全相同)
#
# 战斗技能菜单的 5 组平行数组均只有 12 项, 地址首尾相接:
#   word_9D6D1A[12]      技能索引   0x9D6D1A..0x9D6D32 (24B; memset(...,-1,0x18))
#   byte_9D6D32[12]      可用标志   0x9D6D32..0x9D6D3E (12B; memset(...,1,0xC))
#   unk_9D6D3E[12]       标志备份   0x9D6D3E..0x9D6D4A (12B; memcpy(...,0xC))
#   dword_9D6D4A[12][3]  技能名     0x9D6D4A..0x9D6DDA (144B = 12×12)
#   word_9D6DF8[12]      MP 消耗    0x9D6DF8..0x9D6E10 (24B)
# 构建循环以 word_9D6C8A (0x9D6C8A) 为下标写入并递增, 且无任何越界检查:
#   if (skill_learn >= 20) { word_9D6D1A[cnt]=..; 名称/MP/标志同写; ++cnt; }
# 同一指令技能组已学子技能超过 12 个时, 第 13 项起溢出踩坏相邻数组
# (可用标志/技能名/MP), 叠加菜单窗口高度 28×cnt 超屏 → 战斗菜单错乱。
# (物品菜单 sub_4391E0 有 `if (cnt == 10) break` 保护, 技能菜单独缺此防线。)
#
# 本 cave 接管被 hook 掉的 8 字节状态载入指令 movsx ecx, byte[edx+eax*2+0xB0]:
#   先原样复现该载入, 随后若 word_9D6C8A >= 12 则将 ecx 清零。
#   ecx=0 < 20 → 紧随其后未被改动的原始 `cmp ecx,14h` + `jl skip` 自然跳过本项,
#   计数器不再增长, 菜单稳定封顶 12 项 (等价于在 ++cnt 前加 if(cnt>=12) skip)。
# 仅改动 ecx (原指令自身的输出寄存器); 标志位随后即被原始 cmp 重设, 无副作用。
# 0x9D6C8A 位于战斗数据区 (.bss 静态地址), 不属于 WarPC 重定位范围, 可直接硬编码。
# ============================================================
CAVE_CODE = bytes([
    0x0F, 0xBE, 0x8C, 0x42, 0xB0, 0x00, 0x00, 0x00,  #  0 movsx ecx, byte [edx+eax*2+0B0h] ; 复现原指令
    0x66, 0x83, 0x3D, 0x8A, 0x6C, 0x9D, 0x00, 0x0C,  #  8 cmp  word [9D6C8Ah], 12         ; 菜单现有项数
    0x72, 0x02,                                      # 16 jb   .keep (→20)              ; <12 保留原状态
    0x33, 0xC9,                                      # 18 xor  ecx, ecx                  ; 已满→伪装未学会
    # .keep:
    0xC3,                                            # 20 ret
])
