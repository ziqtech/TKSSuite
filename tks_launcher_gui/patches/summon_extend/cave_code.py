# -*- coding: utf-8 -*-
"""召唤数量扩展 (summon_extend) — 固定布局 cave 生成器

文件级: build_cave_block(cave_base, n) → 完整 cave 块字节。
运行时: 同一函数以 ctx.cave_addr 为 cave_base 调用。

布局 (n=默认 4, 与 patch.json 的 cave_entry_offset 一一对应):
  [0x000, 0x680)  预留 (自动布局补丁可能占用)
  [0x680, 0x6A0)  cave1  init          32B
  [0x6A0, 0x6D0)  cave2  full_check    48B
  [0x6D0, 0x760)  cave3  alloc        144B
  [0x760, 0x7A0)  cave4  clear         64B
  [0x7A0, 0x7A0+n) slots  N 槽数组
  [0x7B0, ...)    capacity cave

栈约定: 引擎在 hook 点写 E8 call (patch_engine/exe_builder 一致),
进入 cave 时 [esp] = 返回地址 (hook+5)。
- cave3 (alloc) 以 `mov [esp],esi` 复用返回地址槽复刻原 push esi/edi 布局;
- capacity 两个出口显式 `add esp,4` 丢弃返回地址 (宿主 sub_445564 为 esp 帧,
  续接点 lea edx,[esp+4] 是 esp 相对寻址, 漂移会传错指针);
- cave1/2/4 结尾 popad 后直接 E9 跳回, 留下的 4 字节返回地址在其续接点
  (0x436C7B push×3+call+add esp、0x444C1B、0x43C768 mov [ebp-2]) 处无副作用:
  皆为 push/pop 对称或 ebp 相对寻址, 且宿主函数 436BD4/444BB0/43C734 均为
  ebp 帧 (55 8B EC), 尾部 mov esp,ebp 会复位 esp。勿改动其续接点语义。
"""
from __future__ import annotations

import struct

IMAGE_BASE = 0x400000

# === Cave 内存布局 ===
SLOTS_OFFSET = 0x7A0
CAVE_BASE_OFFSET = 0x680
CAVE_1_OFFSET = CAVE_BASE_OFFSET
CAVE_2_OFFSET = CAVE_BASE_OFFSET + 32
CAVE_3_OFFSET = CAVE_BASE_OFFSET + 80
CAVE_4_OFFSET = CAVE_BASE_OFFSET + 224
CAPACITY_CAVE_OFFSET = 0x7B0

# === Hook 点 (与 patch.json hooks 一致) ===
HOOK_1_ADDR = 0x436C6D
HOOK_1_SIZE = 14
HOOK_2_ADDR = 0x444BC8
HOOK_2_SIZE = 20
HOOK_3_ADDR = 0x43109A
HOOK_3_SIZE = 36
HOOK_4_ADDR = 0x43C73E
HOOK_4_SIZE = 42
CAPACITY_HOOK_ADDR = 0x445582
CAPACITY_HOOK_SIZE = 7
CAPACITY_FAIL_ADDR = 0x445589
CAPACITY_SUCCESS_ADDR = 0x44558E

# === Cave 跳转目标 ===
SUB_444BDC = 0x444BDC
SUB_444C1B = 0x444C1B
SUB_4310DA = 0x4310DA
SUB_43C768 = 0x43C768
ADDR_BYTE_9DF883 = 0x9DF883
ADDR_BYTE_9DF88E = 0x9DF88E
ADDR_BYTE_9DF88F = 0x9DF88F
ADDR_BYTE_9DF887 = 0x9DF887


def _rel32(from_va: int, to_va: int) -> bytes:
    return struct.pack('<i', to_va - (from_va + 5))


def _build_cave_init(cave_base: int, n: int) -> bytes:
    """Cave 1: N 槽数组 + byte_9DF88E[0/1] 初始化为 -1."""
    cave = bytearray()
    cave += b'\x60'  # pushad
    cave += b'\xBF' + struct.pack('<I', cave_base + SLOTS_OFFSET)
    cave += b'\xB0\xFF'
    cave += b'\xB9' + struct.pack('<I', n)
    cave += b'\xF3\xAA'
    cave += b'\x66\xC7\x05' + struct.pack('<I', ADDR_BYTE_9DF88E) + b'\xFF\xFF'
    cave += b'\x61'
    jmp_pos = len(cave)
    cave += b'\xE9' + _rel32(cave_base + CAVE_1_OFFSET + jmp_pos,
                             HOOK_1_ADDR + HOOK_1_SIZE)
    cave += b'\xCC' * (32 - len(cave))
    return bytes(cave)


def _build_cave_full_check(cave_base: int, n: int) -> bytes:
    """Cave 2: 扫 N 槽, ecx=0 → FULL, 否则 NOT_FULL."""
    cave = bytearray()
    cave += b'\x60'
    cave += b'\xBE' + struct.pack('<I', cave_base + SLOTS_OFFSET)
    cave += b'\xB9' + struct.pack('<I', n)
    cave += b'\x80\x7C\x0E\xFF\xFF'  # cmp byte [esi+ecx-1], FF
    cave += b'\x74\x02'
    cave += b'\xE2\xF7'
    cave += b'\x89\x4C\x24\x18\x61'  # mov [esp+18], ecx; popad
    cave += b'\x85\xC9'
    cave += b'\x75\x05'
    jmp_full = len(cave)
    cave += b'\xE9' + _rel32(cave_base + CAVE_2_OFFSET + jmp_full, SUB_444BDC)
    jmp_free = len(cave)
    cave += b'\xE9' + _rel32(cave_base + CAVE_2_OFFSET + jmp_free, SUB_444C1B)
    cave += b'\xCC' * (48 - len(cave))
    assert len(cave) == 48
    return bytes(cave)


def _build_cave_alloc(cave_base: int, n: int) -> bytes:
    """Cave 3: 找空槽 → 写 slot → 同步 byte_9DF88E[0/1] → 收尾栈."""
    cave_abs = cave_base + CAVE_3_OFFSET
    labels: dict[str, int] = {}
    jmps: list = []
    cave = bytearray()
    pos = [0]

    def emit(b: bytes) -> int:
        cave.extend(b)
        pos[0] += len(b)
        return pos[0] - len(b)

    def emit_short_fwd(lab: str) -> int:
        o = emit(b'\xEB\x00')
        jmps.append((o, 'short', lab))
        return o

    def emit_je_fwd(lab: str) -> int:
        o = emit(b'\x74\x00')
        jmps.append((o, 'short', lab))
        return o

    def emit_jne_fwd(lab: str) -> int:
        o = emit(b'\x75\x00')
        jmps.append((o, 'short', lab))
        return o

    def emit_jmp_near_abs(target: int) -> int:
        o = emit(b'\xE9\x00\x00\x00\x00')
        jmps.append((o, 'near_abs', target))
        return o

    def label(name: str) -> None:
        labels[name] = pos[0]

    emit(b'\x60')
    emit(b'\xBE' + struct.pack('<I', cave_base + SLOTS_OFFSET))
    emit(b'\xB9' + struct.pack('<I', n))
    emit(b'\x80\x7C\x0E\xFF\xFF')
    emit_je_fwd('found')
    emit(b'\xE2\xF7')
    emit(b'\x61')
    emit_jmp_near_abs(SUB_444BDC)
    label('found')
    emit(b'\x0F\xB6\x05' + struct.pack('<I', ADDR_BYTE_9DF883))
    emit(b'\x80\xE9\x01')
    emit(b'\x00\xC8')
    emit(b'\x66\x89\x45\xFC')
    emit(b'\x66\x89\x4D\xFA')
    emit(b'\x66\x83\x45\x08\x24')
    emit(b'\x88\x04\x0E')  # mov byte [esi+ecx], al
    emit(b'\x33\xD2')
    emit(b'\x8A\x04\x16')
    emit(b'\x3C\xFF')
    emit_jne_fwd('have_first')
    emit(b'\xC6\x05' + struct.pack('<I', ADDR_BYTE_9DF88E) + b'\xFF')
    emit_short_fwd('phase4')
    label('have_first')
    emit(b'\xA2' + struct.pack('<I', ADDR_BYTE_9DF88E))
    label('phase4')
    emit(b'\x42')
    emit(b'\x8A\x04\x16')
    emit(b'\x3C\xFF')
    emit_jne_fwd('have_second')
    emit(b'\xC6\x05' + struct.pack('<I', ADDR_BYTE_9DF88F) + b'\xFF')
    emit_short_fwd('phase5')
    label('have_second')
    emit(b'\xA2' + struct.pack('<I', ADDR_BYTE_9DF88F))
    label('phase5')
    emit(b'\x61')
    emit(b'\x89\x34\x24')
    emit(b'\x57')
    emit_jmp_near_abs(SUB_4310DA)

    for offset, kind, target in jmps:
        if kind == 'short':
            rel = labels[target] - (offset + 2)
            assert -128 <= rel <= 127, rel
            cave[offset + 1] = rel & 0xFF
        elif kind == 'near_abs':
            rel = target - (cave_abs + offset + 5)
            cave[offset + 1:offset + 5] = struct.pack('<i', rel)

    cave += b'\xCC' * (144 - len(cave))
    assert len(cave) == 144
    return bytes(cave)


def _build_cave_clear(cave_base: int, n: int) -> bytes:
    """Cave 4: 扫 N 槽找 a1, 清空 slot, 同步 byte_9DF88E[0/1]."""
    cave = bytearray()

    def emit_jmp_to(target: int) -> None:
        cave.append(0xE9)
        jmp_pos = len(cave) - 1
        rel = target - (cave_base + CAVE_4_OFFSET + jmp_pos + 5)
        cave.extend(struct.pack('<i', rel))

    cave += b'\x60'
    cave += b'\x0F\xBF\x45\x08'
    cave += b'\xBE' + struct.pack('<I', cave_base + SLOTS_OFFSET)
    cave += b'\xB9' + struct.pack('<I', n)
    cave += b'\x0F\xB6\x54\x0E\xFF'  # movzx edx, byte [esi+ecx-1]
    cave += b'\x39\xC2'
    cave += b'\x74\x08'
    cave += b'\xE2\xF5'
    cave += b'\x61'
    emit_jmp_to(SUB_43C768)
    cave += b'\xC6\x44\x0E\xFF\xFF'
    cave += b'\x33\xD2'
    cave += b'\x8A\x04\x16'
    cave += b'\xA2' + struct.pack('<I', ADDR_BYTE_9DF88E)
    cave += b'\x42'
    cave += b'\x8A\x04\x16'
    cave += b'\xA2' + struct.pack('<I', ADDR_BYTE_9DF88F)
    cave += b'\x61'
    emit_jmp_to(SUB_43C768)
    cave += b'\xCC' * (64 - len(cave))
    assert len(cave) == 64
    return bytes(cave)


def _build_capacity_cave(cave_base: int, n: int) -> bytes:
    """鲁肃路径容量检查: ordinary occupied + lusu >= N 时拒绝召唤.

    两个出口都先 `add esp,4` 丢弃 E8 压入的返回地址, 使回到
    sub_445564 时 esp 与原版一致 (该函数无 ebp 帧, 续接点
    lea edx,[esp+4] 为 esp 相对寻址, 漂移会传错缓冲区指针)。
    add 位于 jcc 之后, 不破坏 cmp eax,n 的标志位。
    """
    base = cave_base + CAPACITY_CAVE_OFFSET
    code = bytearray()
    code += b'\x60'
    code += b'\xBE' + struct.pack('<I', cave_base + SLOTS_OFFSET)
    code += b'\xB9' + struct.pack('<I', n)
    code += b'\x33\xC0'
    loop_start = len(code)
    code += b'\x80\x7C\x0E\xFF\xFF'
    code += b'\x74\x02'
    code += b'\x40'
    code += b'\xE2' + bytes([(loop_start - (len(code) + 2)) & 0xFF])
    code += b'\x0F\xB6\x15' + struct.pack('<I', ADDR_BYTE_9DF887)
    code += b'\x01\xD0'
    code += b'\x83\xF8' + bytes([n])
    code += b'\x61'
    code += b'\x0F\x83\x00\x00\x00\x00'
    jae_full = len(code) - 4
    # 成功路径: 丢弃返回地址后跳回 0x44558E
    code += b'\x83\xC4\x04'
    code += b'\xE9\x00\x00\x00\x00'
    success_jmp = len(code) - 5
    fail_jmp = len(code)
    # 失败路径: 丢弃返回地址, 重放 xor eax,eax, 跳回 0x445589
    code += b'\x83\xC4\x04'
    code += b'\x33\xC0'
    code += b'\xE9\x00\x00\x00\x00'
    fail_jmp_pos = len(code) - 5
    code[jae_full:jae_full + 4] = struct.pack(
        '<i', (base + fail_jmp) - (base + jae_full + 4))
    code[success_jmp + 1:success_jmp + 5] = struct.pack(
        '<i', CAPACITY_SUCCESS_ADDR - (base + success_jmp + 5))
    code[fail_jmp_pos + 1:fail_jmp_pos + 5] = struct.pack(
        '<i', CAPACITY_FAIL_ADDR - (base + fail_jmp_pos + 5))
    return bytes(code)


def build_cave_block(cave_base: int, n: int = 4) -> bytes:
    """生成完整固定布局 cave 块 (偏移 0 对齐到 .test 节起始)。"""
    if n < 2 or n > 8:
        raise ValueError(f'summon_limit={n} 超出 2..8')
    cave1 = _build_cave_init(cave_base, n)
    cave2 = _build_cave_full_check(cave_base, n)
    cave3 = _build_cave_alloc(cave_base, n)
    cave4 = _build_cave_clear(cave_base, n)
    capacity = _build_capacity_cave(cave_base, n)
    end = max(CAVE_4_OFFSET + 64, SLOTS_OFFSET + n,
              CAPACITY_CAVE_OFFSET + len(capacity))
    block = bytearray(end)
    block[CAVE_1_OFFSET:CAVE_1_OFFSET + 32] = cave1
    block[CAVE_2_OFFSET:CAVE_2_OFFSET + 48] = cave2
    block[CAVE_3_OFFSET:CAVE_3_OFFSET + 144] = cave3
    block[CAVE_4_OFFSET:CAVE_4_OFFSET + 64] = cave4
    block[CAPACITY_CAVE_OFFSET:CAPACITY_CAVE_OFFSET + len(capacity)] = capacity
    return bytes(block)
