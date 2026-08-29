# -*- coding: utf-8 -*-
"""
主角离队脚本路由 (team_member_routing) — cave 带注释机器码源

TeamMember 脚本路由: TeamMember(0,0)→清空全队(原版语义), TeamMember(0,-1)→主角离队, TeamMember(N,*)→不变

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 一致性核对: python .qoder/verify_patches.py (自动比对本文件 CAVE_CODE 与 patch.json)
"""
# ============================================================
# Cave 模板: 主角替换 — TeamMember 脚本路由
# 逆向依据: sub_40DA00 @0x40DA1C (TeamMember 入口条件判断)
# hook: cmp word [ebp+8], 0; jnz 0x40DA8D (7字节) -> E8 rel32 + 2xNOP
# 路由逻辑 (最大化兼容原版脚本):
#   TeamMember(N, *)   (N>0) → 正常入队/离队 (不变)
#   TeamMember(0, 1)          → 主角入队槽位0: 检查→必要时整体右移→写入→调加入代码 (不变)
#   TeamMember(0, -1)         → 主角离队 (走正常离队分支, 压缩移位; 自定义扩展语义)
#   TeamMember(0, 0/其它)     → 清空全队 (原版语义: a1=0 恒清空, 兼容原版 TeamMember(0,0) 脚本)
# 格式: 精确计算所有跳转偏移, 模板大小 158 bytes
# ============================================================
CAVE_CODE = bytes([
    # === Entry: 路由逻辑 ===
    0x66, 0x83, 0x7D, 0x08, 0x00,                      #  0 cmp [ebp+8], 0  ; a1==0?
    0x0F, 0x85, 0x89, 0x00, 0x00, 0x00,                #  5 jnz near .to_join_leave(148)
    0x66, 0x83, 0x7D, 0x0C, 0xFF,                      # 11 cmp [ebp+0Ch], -1  ; a2==-1?
    0x0F, 0x84, 0x7E, 0x00, 0x00, 0x00,                # 16 je near .to_join_leave(148)  ; a2==-1: 主角离队
    0x66, 0x83, 0x7D, 0x0C, 0x01,                      # 22 cmp [ebp+0Ch], 1  ; a2==1? 主角入队!
    0x0F, 0x84, 0x05, 0x00, 0x00, 0x00,                # 27 je near .proto_join(38)
    0xE9, 0x77, 0x00, 0x00, 0x00,                      # 33 jmp near .to_clear_all(157)  ; a2==0/其它: 清空全队(原版语义)

    # === .proto_join === (offset 38) 主角强制插入槽位0 ===
    0x66, 0x83, 0x3D, 0x8C, 0x68, 0x75, 0x00, 0x00,   # 38 cmp [0x75688C], 0  ; 已在槽位0?
    0x0F, 0x84, 0x57, 0x00, 0x00, 0x00,                # 46 je near .proto_return(139)
    0x66, 0x83, 0x3D, 0x8C, 0x68, 0x75, 0x00, 0xFF,   # 52 cmp [0x75688C], -1 ; 槽位0空?
    0x0F, 0x84, 0x30, 0x00, 0x00, 0x00,                # 60 je near .proto_set_slot0(114)
    0x33, 0xC9,                                        # 66 xor ecx, ecx  ; 查找第一个空位

    # === .find_empty === (offset 68) ===
    0x66, 0x83, 0x3C, 0x4D, 0x8C, 0x68, 0x75, 0x00, 0xFF,  # 68 cmp [ecx*2+0x75688C], -1
    0x74, 0x0B,                                        # 77 je short .found_empty(90)
    0x41,                                              # 79 inc ecx
    0x83, 0xF9, 0x06,                                  # 80 cmp ecx, 6
    0x7C, 0xEF,                                        # 83 jl short .find_empty(68)
    # 队伍已满 → 回退正常入队(会因满员失败)
    0xE9, 0x3A, 0x00, 0x00, 0x00,                      # 85 jmp near .to_join_leave(148)

    # === .found_empty === (offset 90) ecx=第一个空位索引 ===
    0x85, 0xC9,                                        # 90 test ecx, ecx
    0x74, 0x14,                                        # 92 jz short .proto_set_slot0(114) ; 槽位0本来就是空
    0x49,                                              # 94 dec ecx  ; 最后一个需右移的槽位

    # === .shift_loop === (offset 95) 整体右移: slot[i]→slot[i+1] ===
    0x66, 0x8B, 0x04, 0x4D, 0x8C, 0x68, 0x75, 0x00,   #  95 mov ax, [ecx*2+0x75688C]
    0x66, 0x89, 0x04, 0x4D, 0x8E, 0x68, 0x75, 0x00,   # 103 mov [ecx*2+0x75688E], ax
    0x49,                                              # 111 dec ecx
    0x79, 0xED,                                        # 112 jns short .shift_loop(95) ; ecx>=0继续

    # === .proto_set_slot0 === (offset 114) 放入主角, 跳到加入代码 ===
    0x66, 0xC7, 0x05, 0x8C, 0x68, 0x75, 0x00, 0x00, 0x00,  # 114 mov word [0x75688C], 0
    0xC7, 0x45, 0xFC, 0x00, 0x00, 0x00, 0x00,          # 123 mov dword [ebp-4], 0  ; v8=0
    0x83, 0xC4, 0x04,                                  # 130 add esp, 4  ; 丢弃CALL返回地址
    0x68, 0xBC, 0xDA, 0x40, 0x00,                      # 133 push 0x40DABC  ; 加入代码入口
    0xC3,                                              # 138 ret

    # === .proto_return === (offset 139) 主角已在槽位0, 直接返回 ===
    0x83, 0xC4, 0x04,                                  # 139 add esp, 4
    0x68, 0xED, 0xDB, 0x40, 0x00,                      # 142 push 0x40DBED  ; 函数尾声
    0xC3,                                              # 147 ret

    # === .to_join_leave === (offset 148) 正常入队/离队入口 ===
    0x83, 0xC4, 0x04,                                  # 148 add esp, 4
    0x68, 0x8D, 0xDA, 0x40, 0x00,                      # 151 push 0x40DA8D
    0xC3,                                              # 156 ret

    # === .to_clear_all === (offset 157) 清空全队 ===
    0xC3,                                              # 157 ret → 0x40DA21→NOP→NOP→0x40DA23
])
