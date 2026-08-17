"""召唤数量扩展补丁 v14 — 4 个 cave_hook + 3 个精确单点 patch. (V14 修复 V13 Phase 5 栈错位 bug)

逆向依据: sub_436BD4 / sub_444BB0 / sub_431094 / sub_43C734 / sub_444FD4 / sub_445564

V14 修复 (V13 仍卡死 闪闪生光 召唤后):
  V13 bug: Phase 5 的栈收尾逻辑有 8 字节错位.

    原始 sub_431094 prologue:
      push ebp           ; esp -= 4  (saved_ebp at [E_enter - 4])
      mov ebp, esp
      add esp, -8        ; esp -= 8  (locals [ebp-8] and [ebp-4])
      push esi           ; esp -= 4  (saved_esi at [E_enter - 16])
      push edi           ; esp -= 4  (saved_edi at [E_enter - 20])

    V13 Phase 5:
      popad              ; esp += 32
      mov [esp], esi     ; esi -> [esp]
      push edi           ; esp -= 4
      jmp SUB_4310DA     ; 跳到 body

    进入 Phase 5 时的 esp = E_call - 36 (pushad 后).
    popad 后 esp = E_call - 4.
    mov [esp], esi 后 esp 不变.
    push edi 后 esp = E_call - 8.

    E_call = E_enter_of_sub - 20. 所以 Phase 5 结束时 esp = E_enter_of_sub - 28.

    Body epilogue 期望 esp = E_enter_of_sub - 20 (从 saved_edi 开始).
    V13 让 esp = E_enter_of_sub - 28, 差 8 字节.

    Epilogue 顺序: pop edi, pop esi, pop ecx, pop ecx, pop ebp, ret.
    V13 下 pop 的 6 个值是:
      [E_enter_of_sub - 28] = edi (Phase 5 push 的)         ← pop edi ✓
      [E_enter_of_sub - 24] = esi (Phase 5 mov [esp] 的)    ← pop esi ✓
      [E_enter_of_sub - 20] = saved_edi (原版 push edi 的)   ← pop ecx (junk)
      [E_enter_of_sub - 16] = saved_esi (原版 push esi 的)   ← pop ecx (junk)
      [E_enter_of_sub - 12] = local (v5, v6 area, [ebp-6])   ← pop ebp (junk!)
      [E_enter_of_sub - 8]  = local (v6 = 24..27, [ebp-4])   ← ret to v6!

    ret 跳转到 v6 (= 24..27 = 0x18..0x1B) 这种非法地址 → CRASH/FREEZE!

  V14 修复: Phase 5 在 push edi 后加 `add esp, 8` (83 C4 08), 让 esp 从 E_call - 8
           回到 E_call - 4 (即 E_enter_of_sub - 24, 但 body body 部分会调整 esp 到
           期望的 E_enter_of_sub - 20).

    实际上, body 的 body 部分不会修改 esp (cdecl 调用清理 args 后 esp 恢复).
    所以 Phase 5 结束时 esp 必须是 body epilogue entry esp.

    Phase 5 V14:
      popad              ; esp = E_call - 4 = E_enter_of_sub - 24
      mov [esp], esi     ; [E_enter_of_sub - 24] = esi
      push edi           ; esp = E_enter_of_sub - 28, [E_enter_of_sub - 28] = edi
      add esp, 8         ; esp = E_enter_of_sub - 20 ← THE FIX
      jmp SUB_4310DA

    此时 esp = E_enter_of_sub - 20, body epilogue 读到:
      [E_enter_of_sub - 20] = saved_edi (原版 push edi 的)  ← pop edi ✓
      [E_enter_of_sub - 16] = saved_esi (原版 push esi 的)  ← pop esi ✓
      [E_enter_of_sub - 12] = local (v5, v6 area)           ← pop ecx (junk, OK)
      [E_enter_of_sub - 8]  = local (v6 area)               ← pop ecx (junk, OK)
      [E_enter_of_sub - 4]  = saved_ebp (原版 push ebp 的)   ← pop ebp ✓
      [E_enter_of_sub]      = ret addr to sub_444BB0         ← ret ✓

V13 修复 (V12 仍卡死 闪闪生光 召唤后):
  V12 bug: Phase 2.5 用 `mov byte [esi + ecx - 1], al` 写入 slot[v5] = v6.
    V7 引入这条指令时, Phase 1 的 loop 计数器 ecx = 1..N (slot 的 1-indexed 编号).
    V10 引入了 `sub cl, 1` 把 ecx 改为 0..N-1 (slot 的 0-indexed 编号) 用于 v5/v6 计算.
    但 Phase 2.5 没同步更新, 仍用 [esi + ecx - 1].
    当 slot[0] 是第一个空槽时, ecx = 1 → sub cl, 1 → ecx = 0 →
    Phase 2.5 写入 [esi + 0 - 1] = [esi - 1] = cave_addr + SLOTS_OFFSET - 1
                                   = cave_addr - 1 (越界!)
    这破坏了 cave_addr - 1 处的内存 (可能是其他 cave 或分配的 guard page).
    对于 N=4, 第一次召唤时 slot[0] 必然是第一个空槽, 所以每次召唤都会触发这个 bug.

  V13 修复: Phase 2.5 改为 `mov byte [esi + ecx], al` (3 字节, 无 -1 偏移).
    此时 ecx = 0..N-1, [esi + ecx] = slot[0..N-1], 正确写入对应 slot.

V12 修复 (V11 仍卡死 Phase 5 栈错位):
  V12 在 Phase 5 开头加 popad (0x61), 确保 esp 恢复到 pushad 之前的位置,
  让 mov [esp], esi 和 push edi 在正确的栈位置执行, epilogue 弹出正确的值.

V10/V11 修复 (V8/V9 Phase 5 v6 被覆盖 / V10 cave_2 总是跳 FULL):
  - V10 Phase 5 不再用 add esp, 4 + 两次 mov, 而是 popad + mov [esp], esi + push edi
  - V11 cave_2 修复 popad 后检查 ecx 是否为 0 (全满 → FULL, 否则 → NOT_FULL)

V6/V7/V8 修复 (V5 栈错位 / Phase 2.5 写入位置):
  - V6 Phase 5 改为 sub esp, 4 模拟 epilogue pop 顺序
  - V7 Phase 2.5 改为 mov byte [esi + ecx - 1] (在 V10 sub cl, 1 之前是对的, 后来变了)
  - V8 改回 add esp + push 模拟, 但 v6 被 push ecx 覆盖

V5 修复 (V4 跳过 sub_431094 后续逻辑):
  V4 cave 3 jmp SUB_43141D 跳过 1054 byte copy, byte_9D705A 更新等关键逻辑.
  V5 改为 jmp SUB_4310DA 让原版所有后续逻辑执行.
  同时 PATCH_7 NOP 掉 0x431417 防止 v5=2/3 破坏 byte_9DF890/byte_9DF891 全局.

V4 修复 (V3 栈错位):
  V3 cave 3 末尾栈平衡不对, popad + add esp, 12 + push ecx, ecx, esi, edi + jmp
  让 epilogue 从正确位置弹出.

核心设计:
  - N 槽数组 (cave_addr+0..cave_addr+N-1) 存角色索引 v6 (= byte_9DF883 + slot)
  - byte_9DF88E[0/1] 保持"两个最低非 -1 槽值"语义, 让原版 sub_444BB0/sub_43C734 工作
  - cave 3 跳过 slot 0/1 检查 (v5/v6 改由 cave 计算), jmp SUB_4310DA 让后续逻辑执行
  - cave 3 自己同步 byte_9DF88E[0/1] = slots[0/1]
  - patch_bytes NOP 0x431417 防止 v5=2/3 破坏 byte_9DF890/byte_9DF891 全局
  - cave 4 自己同步 byte_9DF88E[0/1] (因为 hook_size=42 跳过了原版清理逻辑)
"""

import struct

from core.memory import write_pm, vp_ex, PAGE_EXECUTE_READWRITE
from core.patch_engine import apply_cave_hook


# === 可调参数 ===
N = 4
ENEMY_MAX = 8 - N

# === Cave 内存布局 ===
# 槽数组必须与机器码分离。旧版本把两者都放在 cave_addr+0，随后
# 的初始化写入会覆盖 cave_1，第一次召唤后控制流即可能跳入被破坏的代码。
# 当前标准 cave 模板的已核验占用范围结束于 0x5F6；从 0x600 开始留出
# 本扩展的代码和槽位，避免与其它 cave_hook 互相覆盖。
SLOTS_OFFSET = 0x720       # cave_1..cave_4 位于 [0x600, 0x720)
CAVE_BASE_OFFSET = 0x600
CAVE_1_OFFSET = CAVE_BASE_OFFSET          # 32 bytes (init)
CAVE_2_OFFSET = CAVE_BASE_OFFSET + 32     # 48 bytes (full_check)
CAVE_3_OFFSET = CAVE_BASE_OFFSET + 80     # 144 bytes (alloc + sync)
CAVE_4_OFFSET = CAVE_BASE_OFFSET + 224    # 64 bytes (clear + sync)

# === Hook 点 ===
HOOK_1_ADDR = 0x436C6D
HOOK_1_SIZE = 14
HOOK_1_PATTERN = "C6 05 8E F8 9D 00 FF C6 05 8F F8 9D 00 FF"

HOOK_2_ADDR = 0x444BC8
HOOK_2_SIZE = 20  # V11: 覆盖完整 slot 检查 (mov + test + jl x 2)
HOOK_2_PATTERN = "8A 15 8E F8 9D 00 84 D2 7C 49 8A 0D 8F F8 9D 00 84 C9 7C 3F"

HOOK_3_ADDR = 0x43109A
HOOK_3_SIZE = 36
HOOK_3_PATTERN = "0F BE 05 8E F8 9D 00 56 57 66 83 45 08 24 40 75 13 0F BE 15 83 F8 9D 00 66 89 55 FC 66 C7 45 FA 00 00 EB 1C 0F BE 0D 8F F8 9D 00 41 75 12 0F BE 05 83 F8 9D 00 40 66 89 45 FC 66 C7 45 FA 01 00"

HOOK_4_ADDR = 0x43C73E
HOOK_4_SIZE = 42
HOOK_4_PATTERN = "0F BE 15 8E F8 9D 00 3B C2 75 09 C6 05 8E F8 9D 00 FF EB 16 0F BF 4D 08 0F BE 05 8F F8 9D 00 3B C8 75 07 C6 05 8F F8 9D 00 FF"

# === patch_bytes 目标 ===
PATCH_5_ADDR = 0x445088
PATCH_5_OLD = bytes.fromhex("66 83 C0 02")
PATCH_5_NEW = bytes.fromhex("66 83 C0 " + f"{N:02X}")

PATCH_6_ADDR = 0x445582
PATCH_6_OLD = bytes.fromhex("83 FA 06")
PATCH_6_NEW = bytes.fromhex("83 FA " + f"{ENEMY_MAX:02X}")

# V5 新增: NOP 掉 sub_431094 内部的 mov byte [ecx+0x9DF88E], dl
# 原版这条指令在 v5+2/v5+3 时会写到 byte_9DF890/byte_9DF891 (其他全局变量)
# 破坏其他数据导致卡死. cave 3 已手动同步 byte_9DF88E[0/1], 这条指令是多余的.
PATCH_7_ADDR = 0x431417
PATCH_7_OLD = bytes.fromhex("88 91 8E F8 9D 00")
PATCH_7_NEW = bytes.fromhex("90 90 90 90 90 90")  # 6 NOPs

# === Cave 跳转目标 ===
SUB_444BDC = 0x444BDC   # sub_444BB0 满槽错误分支入口
SUB_444C1B = 0x444C1B   # sub_444BB0 非满分支 (jl 0x444C1B)
SUB_4310DA = 0x4310DA   # sub_431094 中跳过 slot 0/1 检查后的位置 (movsx edx, word [ebp+8])
SUB_431414 = 0x431414   # sub_431094 中 'add esp, 8' (清理 sub_42F9C8 args)
SUB_431417 = 0x431417   # mov byte [ecx+0x9DF88E], dl (N>=3 时破坏 byte_9DF890/0x9DF891, 必须 NOP)
SUB_43141D = 0x43141D   # epilogue 起点 (mov ax, word [ebp-4])
SUB_43C768 = 0x43C768   # sub_43C734 hook+42 后 (i=0 重置)
ADDR_BYTE_9DF883 = 0x9DF883
ADDR_BYTE_9DF88E = 0x9DF88E
ADDR_BYTE_9DF88F = 0x9DF88F
IMAGE_BASE = 0x400000
_IMAGE_DELTA = 0


def _va(original_va):
    """Relocate an original-image VA to the loaded module."""
    return original_va + _IMAGE_DELTA


def _target_va(ctx, original_va):
    """将原版镜像 VA 转为当前进程 VA，保留原版 RVA 语义。"""
    return ctx.base_addr + (original_va - IMAGE_BASE)


def _jmp_to_abs(target_abs, jmp_pos, cave_abs):
    """JMP E9 rel32 = target_abs - (cave_abs + jmp_pos + 5)"""
    return struct.pack('<i', _va(target_abs) - (cave_abs + jmp_pos + 5))


def _build_cave_with_labels(cave_abs, builder_fn, size):
    """通用 label-driven assembler."""
    labels = {}
    jmps = []  # (cave_offset, kind, target)
    cave = bytearray()
    pos = [0]

    def emit(b):
        cave.extend(b)
        pos[0] += len(b)
        return pos[0] - len(b)

    def emit_short_fwd(label):
        o = emit(b"\xEB\x00"); jmps.append((o, 'short', label)); return o
    def emit_short_back(label):
        o = emit(b"\xEB\x00"); jmps.append((o, 'short_back', label)); return o
    def emit_je_fwd(label):
        o = emit(b"\x74\x00"); jmps.append((o, 'short', label)); return o
    def emit_jne_fwd(label):
        o = emit(b"\x75\x00"); jmps.append((o, 'short', label)); return o
    def emit_jl_back(label):
        o = emit(b"\x7C\x00"); jmps.append((o, 'short_back', label)); return o
    def emit_jmp_near_abs(target):
        o = emit(b"\xE9\x00\x00\x00\x00"); jmps.append((o, 'near_abs', target)); return o

    def label(name):
        labels[name] = pos[0]

    # Pass 1: build
    builder_fn(emit, emit_short_fwd, emit_short_back, emit_je_fwd, emit_jne_fwd,
               emit_jl_back, emit_jmp_near_abs, label)
    # Pass 2: fill jumps
    for offset, kind, target in jmps:
        if kind in ('short', 'short_back'):
            tgt_off = labels[target]
            rel = tgt_off - (offset + 2)
            assert -128 <= rel <= 127, f"short jmp out of range: {rel}"
            cave[offset + 1] = rel & 0xFF
        elif kind == 'near_abs':
            rel = _va(target) - (cave_abs + offset + 5)
            cave[offset + 1:offset + 5] = struct.pack('<i', rel)

    cave += b"\xCC" * (size - len(cave))
    return bytes(cave)


def _cave1_build(emit, esf, esb, eje, ejne, ejl, ejmp, label):
    """Cave 1: 初始化 N 槽数组为 -1."""
    emit(b"\x60")  # pushad
    emit(b"\xBF" + struct.pack('<I', 0))  # placeholder, fill below with cave_addr (slot array base)
    # 实际上 cave_addr 是外部传入, 在 _build_cave_init 里直接 build bytes 而不是调这个


def _build_cave_init(cave_addr):
    """Cave 1: N 槽数组 + byte_9DF88E[0/1] 初始化为 -1 (0xFF).

    V16 修复: 之前 cave_1 只初始化 N 槽数组, 未显式初始化 byte_9DF88E[0/1].
    虽然 cave_3/cave_4 会同步它们, 但若 cave_3 首次执行前 sub_43C734 先被调用
    (理论上 sync 顺序应能覆盖), 或任何其他路径读取 byte_9DF88E[0/1] 时, 值可能
    残留. 这里用 16-bit 写覆盖 0x9DF88E 和 0x9DF88F 两字节, 一次性设 -1.
    """
    cave = bytearray()
    cave += bytes.fromhex("60")
    cave += bytes.fromhex("BF") + struct.pack('<I', cave_addr + SLOTS_OFFSET)
    cave += bytes.fromhex("B0 FF")
    cave += bytes.fromhex("B9") + struct.pack('<I', N)
    cave += bytes.fromhex("F3 AA")
    # 16-bit 写 0xFFFF 到 0x9DF88E (覆盖 byte_9DF88E[0] 和 byte_9DF88F 两字节)
    cave += bytes.fromhex("66 C7 05") + struct.pack('<I', _va(ADDR_BYTE_9DF88E)) + b"\xFF\xFF"
    cave += bytes.fromhex("61")
    jmp_pos = len(cave)
    cave += bytes.fromhex("E9") + _jmp_to_abs(
        HOOK_1_ADDR + HOOK_1_SIZE, jmp_pos, cave_addr + CAVE_1_OFFSET)
    cave += b"\xCC" * (32 - len(cave))
    return bytes(cave)


def _build_cave_full_check(cave_addr):
    """Cave 2 V11: 检查 N 槽, 根据 ecx 跳转 FULL/NOT_FULL.

    V10 bug: 总是跳到 SUB_444BDC (full), 错误报告 slots 已满.
    V11 fix: popad 后检查 ecx 是否为 0,
             0 表示全满 (跳 SUB_444BDC),
             非 0 表示有空槽 (跳 SUB_444C1B).

    Slot 检查循环: 从 N-1 到 0 反向扫描, ecx 保留 1-indexed 第一个空槽,
                   或 0 表示所有槽都满.
    """
    cave = bytearray()
    cave += bytes.fromhex("60")  # pushad
    cave += bytes.fromhex("BE") + struct.pack('<I', cave_addr + SLOTS_OFFSET)
    cave += bytes.fromhex("B9") + struct.pack('<I', N)
    cave += bytes.fromhex("80 7C 0E FF FF")  # cmp byte [esi+ecx-1], 0xFF
    cave += bytes.fromhex("74 02")  # je +2 (found, skip dec)
    cave += bytes.fromhex("E2 F7")  # loop -9 (dec ecx, loop if ecx != 0)
    # 将循环结果写入 pushad 保存区的 ECX 槽，再恢复全部寄存器。
    # pushad 保存区中 ECX 位于 [ESP+0x1C]；[ESP+0x18] 是 EDX。
    cave += bytes.fromhex("89 4C 24 1C 61")
    cave += bytes.fromhex("85 C9")  # test ecx, ecx
    cave += bytes.fromhex("75 05")  # jnz +5 (skip jmp FULL)
    jmp_full_pos = len(cave)
    cave += bytes.fromhex("E9") + _jmp_to_abs(
        SUB_444BDC, jmp_full_pos, cave_addr + CAVE_2_OFFSET)
    jmp_free_pos = len(cave)
    cave += bytes.fromhex("E9") + _jmp_to_abs(
        SUB_444C1B, jmp_free_pos, cave_addr + CAVE_2_OFFSET)
    cave += b"\xCC" * (48 - len(cave))  # V11: 扩展 cave_2 budget 到 48 bytes
    assert len(cave) == 48
    return bytes(cave)


def _build_cave_alloc(cave_addr):
    """Cave 3 v14: 找空槽 → 写 N 槽数组 slot[index]=v6 → 同步 byte_9DF88E[0/1] →
    收尾栈 (popad + mov [esp], esi + push edi + add esp, 8 + jmp SUB_4310DA)."""
    cave_abs = cave_addr + CAVE_3_OFFSET
    labels = {}
    jmps = []
    cave = bytearray()
    pos = [0]

    def emit(b):
        cave.extend(b); pos[0] += len(b); return pos[0] - len(b)
    def emit_short_fwd(label):
        o = emit(b"\xEB\x00"); jmps.append((o, 'short', label)); return o
    def emit_je_fwd(label):
        o = emit(b"\x74\x00"); jmps.append((o, 'short', label)); return o
    def emit_jne_fwd(label):
        o = emit(b"\x75\x00"); jmps.append((o, 'short', label)); return o
    def emit_jl_back(label):
        o = emit(b"\x7C\x00"); jmps.append((o, 'short_back', label)); return o
    def emit_jmp_near_abs(target):
        o = emit(b"\xE9\x00\x00\x00\x00"); jmps.append((o, 'near_abs', target)); return o
    def label(name):
        labels[name] = pos[0]

    # Phase 1: 找空槽 (反向扫描 slot[N-1..0], 找到时 ecx = 1-indexed slot, 0..N-1)
    # Loop: ecx = N, 每次检查 slot[ecx-1], 找到空 (0xFF) → je found
    # 没找到 → loop back (dec ecx), 继续.
    # 最终:
    #   - 找到时 ecx = (1-indexed slot) = 1..N
    #   - 没找到时 ecx = 0 (loop 退出条件)
    emit(b"\x60")  # pushad
    emit(b"\xBE" + struct.pack('<I', cave_addr + SLOTS_OFFSET))
    emit(b"\xB9" + struct.pack('<I', N))
    emit(b"\x80\x7C\x0E\xFF\xFF")  # cmp byte [esi+ecx-1], 0xFF
    emit_je_fwd('found')
    emit(b"\xE2\xF7")  # loop back -9
    emit(b"\x61")
    emit_jmp_near_abs(SUB_444BDC)  # 没找到 = 满
    label('found')
    # 此时 ecx = 1..N (1-indexed slot)

    # Phase 2: 设 v6, v5, v7
    # eax = byte_9DF883 (来自原版 movzx eax, byte [0x9DF883] 的 hook 跳过部分)
    emit(b"\x0F\xB6\x05" + struct.pack('<I', _va(ADDR_BYTE_9DF883)))  # movzx eax, byte [0x9DF883]
    emit(b"\x80\xE9\x01")  # sub cl, 1 (cl: 1..N -> 0..N-1 = slot index 0-based)
    emit(b"\x00\xC8")      # add al, cl (v6 = byte_9DF883 + slot)
    emit(b"\x66\x89\x45\xFC")  # mov [ebp-4], ax (v6)
    emit(b"\x66\x89\x4D\xFA")  # mov [ebp-6], cx (v5 = 0..N-1)
    emit(b"\x66\x83\x45\x08\x24")  # add word [ebp+8], 0x24 (v7 = a1 + 36)

    # Phase 2.5: 写 N 槽数组 slot[v5] = v6 (al)
    # V13 修复: 之前 V12 用 `mov byte [esi + ecx - 1], al` (88 44 0E FF, 4 字节),
    #   这是 V7 写的, 当时 ecx = 1..N (loop 计数), ecx-1 = 0..N-1 是正确的 slot index.
    #   V10 引入了 `sub cl, 1` 把 ecx 改为 0..N-1, 但 Phase 2.5 没同步.
    #   结果: 当 slot[0] 是第一个空槽时, ecx = 0, [esi + ecx - 1] = [esi - 1]
    #   = cave_addr - 1 (越界!), 破坏 cave_addr - 1 处的内存.
    # V13 修复: 改为 `mov byte [esi + ecx], al` (88 04 0E, 3 字节, 无 -1 偏移).
    #   此时 ecx = 0..N-1, [esi + ecx] = slot[0..N-1], 正确.
    emit(bytes.fromhex("88 04 0E"))  # mov byte [esi + ecx], al (slot[v5] = v6, ecx = 0..N-1)

    # Phase 3: 同步 byte_9DF88E[0] = N 槽数组 slot[0]
    emit(b"\x33\xD2")      # xor edx, edx
    emit(b"\x8A\x04\x16")  # mov al, byte [esi+edx] (al = slot[0])
    emit(b"\x3C\xFF")      # cmp al, 0xFF
    emit_jne_fwd('have_first')
    # al = -1, slot[0] 空
    emit(b"\xC6\x05" + struct.pack('<I', _va(ADDR_BYTE_9DF88E)) + b"\xFF")  # mov byte [0x9DF88E], 0xFF
    emit_short_fwd('phase4_start')
    label('have_first')
    emit(b"\xA2" + struct.pack('<I', _va(ADDR_BYTE_9DF88E)))  # mov byte [0x9DF88E], al

    # Phase 4: 同步 byte_9DF88F = N 槽数组 slot[1]
    label('phase4_start')
    emit(b"\x42")  # inc edx (edx = 1, scan slot[1])
    emit(b"\x8A\x04\x16")  # mov al, byte [esi+edx] (al = slot[1])
    emit(b"\x3C\xFF")
    emit_jne_fwd('have_second')
    emit(b"\xC6\x05" + struct.pack('<I', _va(ADDR_BYTE_9DF88F)) + b"\xFF")  # mov byte [0x9DF88F], 0xFF
    emit_short_fwd('phase5')
    label('have_second')
    emit(b"\xA2" + struct.pack('<I', _va(ADDR_BYTE_9DF88F)))  # mov byte [0x9DF88F], al

    # Phase 5: 收尾栈
    # V12 修复: 开头加 popad (0x61) 恢复 esp 到 pushad 之前的位置.
    #   Phase 5 的 mov [esp], esi + push edi 需要 esp 在正确位置.
    #   没有 popad 时, esp 还在 pushad 之后 (= E_entry - 48), mov [esp] 写到错位位置.
    #
    # V14 修复 (V13 bug: 8 字节栈错位导致 ret 跳到 v6 = 0x18..0x1B 非法地址):
    #   V13 Phase 5 结束时 esp = E_entry - 28. body epilogue 期望 esp = E_entry - 20.
    #   差 8 字节, epilogue 读到的 6 个值错位:
    #     pop edi = edi (Phase 5 push 的) ✓
    #     pop esi = esi (Phase 5 mov [esp] 的) ✓
    #     pop ecx = saved_edi (junk)
    #     pop ecx = saved_esi (junk)
    #     pop ebp = local (v5/v6 area, [ebp-6])   ← junk for ebp
    #     ret to local (v6 area, [ebp-4])           ← v6 = 24..27 = 0x18..0x1B → CRASH!
    #
    #   V14 修复: 在 push edi 后加 `add esp, 8` (83 C4 08, 3 字节), 让 esp = E_entry - 20,
    #            与 body epilogue 期望一致.
    label('phase5')
    emit(b"\x61")             # popad (V12 fix: 8 个寄存器恢复)
    emit(b"\x89\x34\x24")     # mov [esp], esi   ([E_entry - 24] = esi, pop esi 读这里)
    emit(b"\x57")             # push edi         (esp = E_entry - 28, [E_entry - 28] = edi)
    # V14 bug: 此 add esp, 8 让 esp 从 E_call-20 变成 E_call-12, 错位 8 字节, epilogue ret 跳到 v6 非法地址 -> CRASH
    # V15: 不 emit 此指令, esp 正确为 E_call - 20, body epilogue 正确恢复
    pass  # emit(b"\x83\xC4\x08")  # V14 BUG: REMOVED in V15
    emit_jmp_near_abs(SUB_4310DA)

    # Pass 2: 填充跳转
    for offset, kind, target in jmps:
        if kind in ('short', 'short_back'):
            tgt = labels[target]
            rel = tgt - (offset + 2)
            assert -128 <= rel <= 127
            cave[offset + 1] = rel & 0xFF
        elif kind == 'near_abs':
            rel = target - (cave_abs + offset + 5)
            cave[offset + 1:offset + 5] = struct.pack('<i', rel)

    cave += b"\xCC" * (144 - len(cave))
    assert len(cave) == 144, f"cave_3 size wrong: {len(cave)}"
    return bytes(cave)


def _build_cave_clear(cave_addr):
    """Cave 4 v4: 扫 N 槽找 a1, 清空该 slot,
    同步 byte_9DF88E[0/1] = slot[0/1] (or -1 if empty).
    跳到 SUB_43C768 (跳过原版 byte_9DF88E[0/1] 清理逻辑).
    Cave 4 hook_size=42 跳过原版第 18-25 行的 byte_9DF88E[0/1] 清理,
    所以 cave 4 必须自己 sync byte_9DF88E[0/1].

    V16 修复 V13/V14/V15 遗留 bug:
    - V13/V14/V15 用 `je +2` 跳到 popad (而非 clear slot), slot[k] 永远不会被清空.
      这个 bug 导致 entity 死亡后 slot 仍然占着, 不会直接 freeze, 但召唤数会被
      错误占用, 玩家无法召唤新单位.
    - V13/V14/V15 用 `loop -9` 但 movzx 是 5 字节 (0F B6 54 0E FF), loop 偏移错.
      movzx 在 offset 0xF, cmp 在 0x14, je 在 0x16, loop 在 0x18.
      loop 末在 0x1A, 要回到 movzx 起始 (0xF) 需要 -11 (0xF5), 不是 -9 (0xF7).
    V16 fix:
      - `je` 改为 `74 08` (+8 跳过 loop+popad+jmp, 跳到 clear slot).
      - `loop` 改为 `E2 F5` (-11 跳回 movzx 起始).
    """
    cave = bytearray()

    def emit(b):
        cave.extend(b)
        return len(cave)

    def emit_jmp_to(target):
        """emit E9 <rel32>, jmp pos = len(cave) after adding E9"""
        cave.append(0xE9)
        jmp_pos = len(cave)  # E9 之前的 position (但 E9 已经加, 这是 E9 之后的 position)
        # 实际上 jmp_pos 应该是 E9 的 position = len(cave) - 1
        # rel32 公式: target - (cave_abs + jmp_pos + 5)
        # jmp_pos + 5 = len(cave) - 1 + 5 = len(cave) + 4
        # 但 rel32 在 len(cave) + 0..3 (cave_abs + len(cave) + 4 = next instruction)
        rel = _va(target) - (cave_addr + CAVE_4_OFFSET + (jmp_pos - 1) + 5)
        cave.extend(struct.pack('<i', rel))

    emit(bytes.fromhex("60"))  # pushad
    emit(bytes.fromhex("0F BF 45 08"))  # movsx eax, word [ebp+8] (a1)
    emit(b"\xBE" + struct.pack('<I', cave_addr + SLOTS_OFFSET))
    emit(bytes.fromhex("B9") + struct.pack('<I', N))
    # loop
    # V11 修复: 之前用 'cmp word [esi+ecx-1], ax' 是 16-bit 比较, 但 slot 是 8-bit,
    #   当 slot[k] 匹配 a1 但 slot[k+1] != 0 时会误判. 改用 movzx byte + cmp.
    emit(bytes.fromhex("0F B6 54 0E FF"))  # movzx edx, byte [esi+ecx-1] (slot value unsigned)
    emit(bytes.fromhex("39 C2"))           # cmp edx, eax
    emit(bytes.fromhex("74 08"))           # V16 fix: je +8 (跳到 clear slot, 跳过 loop+popad+jmp)
    emit(bytes.fromhex("E2 F5"))           # V16 fix: loop -11 (跳回 movzx 起始, 而非 movzx 中间)
    # not found
    emit(bytes.fromhex("61"))             # popad
    emit_jmp_to(SUB_43C768)
    # found: ecx = 1..N (loop counter)
    emit(bytes.fromhex("C6 44 0E FF FF"))  # mov byte [esi+ecx-1], 0xFF (clear slot)
    # 注: 这里 ecx = 1..N (loop 计数器), ecx-1 = 0..N-1 (slot index), 正确.
    # (cave_4 的 ecx 没有 sub cl, 1, 所以 [esi + ecx - 1] 是正确的.)

    # 重新读 slot[0]
    emit(bytes.fromhex("33 D2"))          # xor edx, edx
    emit(bytes.fromhex("8A 04 16"))       # mov al, byte [esi+edx]
    emit(b"\xA2" + struct.pack('<I', _va(ADDR_BYTE_9DF88E)))  # mov byte [0x9DF88E], al

    # 重新读 slot[1]
    emit(bytes.fromhex("42"))             # inc edx
    emit(bytes.fromhex("8A 04 16"))       # mov al, byte [esi+edx]
    emit(b"\xA2" + struct.pack('<I', _va(ADDR_BYTE_9DF88F)))  # mov byte [0x9DF88F], al

    emit(bytes.fromhex("61"))             # popad
    emit_jmp_to(SUB_43C768)

    cave += b"\xCC" * (64 - len(cave))
    assert len(cave) == 64, f"cave4 size wrong: {len(cave)}"
    return bytes(cave)


def _make_hook_defn(cid, hook_addr, hook_size, hook_pattern, cave_offset, cave_bytes):
    d = type('D', (), {})()
    d.type = "cave_hook"
    d.id = f"summon_extend_hook_{cid}"
    d.hook_pattern = hook_pattern
    d.hook_size = hook_size
    d.hook_offset = 0
    d.hook_expect_count = 1
    d.cave_template = "summon_extend_external"
    d.cave_offset = cave_offset
    d.autolayout_cave = False
    d._cave_code_bytes = cave_bytes
    d._explicit_hook_addr = hook_addr
    return d


def _write_patch_bytes_exact(ctx, addr, old_bytes, new_bytes, log):
    from core.memory import read_pm
    if len(old_bytes) != len(new_bytes):
        return False
    h_proc = ctx.h_proc
    addr = _target_va(ctx, addr)
    read_result = read_pm(h_proc, addr, len(old_bytes))
    if read_result is None:
        return False
    cur_bytes, n_read = read_result
    if n_read != len(old_bytes):
        return False
    if cur_bytes != old_bytes:
        log(f"    [ERROR] 0x{addr:08X} 旧字节不匹配:")
        log(f"      期望: {old_bytes.hex().upper()}")
        log(f"      实际: {cur_bytes.hex().upper()}")
        return False
    op = vp_ex(h_proc, addr, len(new_bytes), PAGE_EXECUTE_READWRITE)
    nw = write_pm(h_proc, addr, new_bytes)
    vp_ex(h_proc, addr, len(new_bytes), op)
    if nw != len(new_bytes):
        return False
    log(f"    [OK] 0x{addr:08X} {old_bytes.hex().upper()} -> {new_bytes.hex().upper()}")
    return True


def apply(ctx):
    global _IMAGE_DELTA
    _IMAGE_DELTA = ctx.base_addr - IMAGE_BASE
    log = ctx.log
    log(f"\n--- [summon_extend] v16 (N={N}, enemy_max={ENEMY_MAX}) ---")
    log(f"  V15 修复 V14 Phase 5 错位 add esp, 8 导致引擎后卡死的 bug")
    log(f"  V16 修复 V13/V14/V15 cave_4 遗留 bug:")
    log(f"    - `je +2` 错跳到 popad → 改为 `je +8` 跳到 clear slot")
    log(f"    - `loop -9` 错跳到 movzx 中间 → 改为 `loop -11` 跳回 movzx 起始")
    log(f"    (原 bug: entity 死亡后 slot[k] 永远不会被清空, 召唤数被错误占用)")
    log(f"  V16 还在 cave_1 追加 byte_9DF88E[0/1] = -1 初始化 (16-bit 写覆盖两字节)")

    cave_addr = ctx.cave_addr
    if not cave_addr:
        log("  [ERROR] cave_addr 为 0")
        return False
    if N < 1 or N > 7:
        log(f"  [ERROR] N={N} 越界")
        return False
    cave_total_size = ctx.settings.cave_total_size
    cave_end = max(CAVE_4_OFFSET + 64, SLOTS_OFFSET + N)
    if cave_end > cave_total_size:
        log(f"  [ERROR] cave 内存不足: 需要 {cave_end}, budget={cave_total_size}")
        return False
    log(f"  cave_addr=0x{cave_addr:08X}, cave_total_size={cave_total_size}")

    cave1 = _build_cave_init(cave_addr)
    cave2 = _build_cave_full_check(cave_addr)
    cave3 = _build_cave_alloc(cave_addr)
    cave4 = _build_cave_clear(cave_addr)

    hook1 = _make_hook_defn(1, HOOK_1_ADDR, HOOK_1_SIZE, HOOK_1_PATTERN, CAVE_1_OFFSET, cave1)
    hook2 = _make_hook_defn(2, HOOK_2_ADDR, HOOK_2_SIZE, HOOK_2_PATTERN, CAVE_2_OFFSET, cave2)
    hook3 = _make_hook_defn(3, HOOK_3_ADDR, HOOK_3_SIZE, HOOK_3_PATTERN, CAVE_3_OFFSET, cave3)
    hook4 = _make_hook_defn(4, HOOK_4_ADDR, HOOK_4_SIZE, HOOK_4_PATTERN, CAVE_4_OFFSET, cave4)

    all_ok = True
    from core.scanner import parse_pattern, pattern_scan
    for hook, name in [(hook1, "init"), (hook2, "full_check"),
                       (hook3, "alloc"), (hook4, "clear")]:
        pat, wc = parse_pattern(hook.hook_pattern)
        hits = pattern_scan(bytes(ctx.code_buf), pat, wc)
        if hook.hook_expect_count > 0 and len(hits) != hook.hook_expect_count:
            log(f"  [FAIL] hook_{name}: 模式匹配 {len(hits)} 处")
            all_ok = False
            continue
        log(f"  应用 hook_{name} @ 0x{hook._explicit_hook_addr:08X}")
        ok = apply_cave_hook(
            hook, hits, ctx.code_buf, ctx.code_start_addr,
            ctx.h_proc, cave_addr, ctx.warpc_base, ctx.settings, ctx.runtime,
            log_func=log,
        )
        if not ok:
            log(f"  [FAIL] hook_{name} 应用失败")
            all_ok = False

    log(f"  应用 patch_bytes_sub_444FD4_ax_add_N @ 0x{PATCH_5_ADDR:08X}")
    if not _write_patch_bytes_exact(ctx, PATCH_5_ADDR, PATCH_5_OLD, PATCH_5_NEW, log):
        all_ok = False
    abs_off = _target_va(ctx, PATCH_5_ADDR) - ctx.code_start_addr
    if 0 <= abs_off < len(ctx.code_buf) - len(PATCH_5_OLD):
        for i, b in enumerate(PATCH_5_NEW):
            ctx.code_buf[abs_off + i] = b

    log(f"  应用 patch_bytes_sub_445564_cmp_8_minus_N @ 0x{PATCH_6_ADDR:08X}")
    if not _write_patch_bytes_exact(ctx, PATCH_6_ADDR, PATCH_6_OLD, PATCH_6_NEW, log):
        all_ok = False
    abs_off = _target_va(ctx, PATCH_6_ADDR) - ctx.code_start_addr
    if 0 <= abs_off < len(ctx.code_buf) - len(PATCH_6_OLD):
        for i, b in enumerate(PATCH_6_NEW):
            ctx.code_buf[abs_off + i] = b

    # V5: NOP 掉 sub_431094 0x431417 (mov byte [ecx+0x9DF88E], dl)
    # 防止 N>=3 时 v5+2/v5+3 写入破坏 byte_9DF890/byte_9DF891 全局变量
    log(f"  应用 patch_bytes_sub_431094_nop_431417 @ 0x{PATCH_7_ADDR:08X}")
    if not _write_patch_bytes_exact(ctx, PATCH_7_ADDR, PATCH_7_OLD, PATCH_7_NEW, log):
        all_ok = False
    abs_off = _target_va(ctx, PATCH_7_ADDR) - ctx.code_start_addr
    if 0 <= abs_off < len(ctx.code_buf) - len(PATCH_7_OLD):
        for i, b in enumerate(PATCH_7_NEW):
            ctx.code_buf[abs_off + i] = b

    if not all_ok:
        return False

    init_bytes = bytes([0xFF]) * N
    abs_addr = cave_addr + SLOTS_OFFSET
    op = vp_ex(ctx.h_proc, abs_addr, N, PAGE_EXECUTE_READWRITE)
    nw = write_pm(ctx.h_proc, abs_addr, init_bytes)
    vp_ex(ctx.h_proc, abs_addr, N, op)
    if nw != N:
        return False

    log(f"  [OK] 召唤数量扩展 v14 完成")
    return True
