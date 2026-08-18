# -*- coding: utf-8 -*-
"""
x86 简易反汇编工具 (32-bit)

特点:
- 识别常见指令 (mov/call/jmp/push/pop/ret/add/sub/cmp/test/nop 等)
- 解析跳转/调用目标地址
- 查找函数开头模式
- 查找 API 调用模式 (FF 15 / push-call)

适用: 简易代码分析, 不替代专业反汇编器 (IDA Pro / Ghidra)
"""
import struct
from typing import List, Dict, Tuple, Optional


# 常见 x86 操作码表 (1字节 + 部分2字节前缀)
X86_OPCODES = {
    0x50: ('push eax', 1), 0x51: ('push ecx', 1), 0x52: ('push edx', 1),
    0x53: ('push ebx', 1), 0x54: ('push esp', 1), 0x55: ('push ebp', 1),
    0x56: ('push esi', 1), 0x57: ('push edi', 1),
    0x58: ('pop eax', 1), 0x59: ('pop ecx', 1), 0x5A: ('pop edx', 1),
    0x5B: ('pop ebx', 1), 0x5C: ('pop esp', 1), 0x5D: ('pop ebp', 1),
    0x5E: ('pop esi', 1), 0x5F: ('pop edi', 1),
    0x90: ('nop', 1),
    0xC3: ('ret', 1),
    0xC2: ('ret imm16', 3),
    0xE8: ('call rel32', 5),
    0xE9: ('jmp rel32', 5),
    0xEB: ('jmp rel8', 2),
    0x74: ('je rel8', 2), 0x75: ('jne rel8', 2),
    0x7C: ('jl rel8', 2), 0x7D: ('jge rel8', 2),
    0x7E: ('jle rel8', 2), 0x7F: ('jg rel8', 2),
    0x83: ('arith reg,imm8', 3),
    0x81: ('arith reg,imm32', 6),
    0x8B: ('mov reg,r/m', 2),
    0x89: ('mov r/m,reg', 2),
    0x6A: ('push imm8', 2),
    0x68: ('push imm32', 5),
    0xA1: ('mov eax,[imm32]', 5),
    0xA3: ('mov [imm32],eax', 5),
    0x01: ('add r/m32,r32', 2),
    0x29: ('sub r/m32,r32', 2),
    0x31: ('xor r/m32,r32', 2),
    0x39: ('cmp r/m32,r32', 2),
    0x66: ('operand-size prefix', 1),
    0x67: ('address-size prefix', 1),
}


def simple_disasm(data: bytes, base_addr: int = 0,
                  max_instr: int = 500) -> List[Dict]:
    """
    简易反汇编, 返回指令列表

    Args:
        data: 字节数据
        base_addr: 起始虚拟地址 (用于显示地址)
        max_instr: 最多反汇编的指令数

    Returns:
        list of dict:
            - offset:   在 data 中的偏移
            - addr:     虚拟地址 = base_addr + offset
            - opcode:   首字节
            - size:     指令字节数
            - mnemonic: 助记符
    """
    instructions = []
    i = 0
    while i < len(data) and len(instructions) < max_instr:
        offset = i
        opcode = data[i]

        if opcode in X86_OPCODES:
            mnemonic, size = X86_OPCODES[opcode]
        elif opcode == 0xFF:
            # FF 系列: call/jmp/push 间接
            modrm = data[i + 1] if i + 1 < len(data) else 0
            reg = (modrm >> 3) & 7
            if reg == 2:
                mnemonic = 'call [r/m]'
            elif reg == 4:
                mnemonic = 'jmp [r/m]'
            elif reg == 6:
                mnemonic = 'push [r/m]'
            else:
                mnemonic = f'ff /{reg}'
            # 区分是否有 SIB/disp
            mod = modrm >> 6
            rm = modrm & 7
            if mod == 0 and rm == 5:  # [disp32]
                size = 6
            elif mod == 1:
                size = 3 if rm != 4 else 4
            elif mod == 2:
                size = 6 if rm != 4 else 7
            else:
                size = 2 if rm != 4 else 3
        elif opcode == 0x0F:
            # 两字节操作码
            opcode2 = data[i + 1] if i + 1 < len(data) else 0
            if opcode2 == 0x84:
                mnemonic = 'je rel32'
                size = 6
            elif opcode2 == 0x85:
                mnemonic = 'jne rel32'
                size = 6
            elif opcode2 == 0xBF:
                mnemonic = 'mov edi,edi (nop)'
                size = 2
            else:
                mnemonic = f'0F {opcode2:02X}'
                size = 2
        else:
            mnemonic = f'db 0x{opcode:02X}'
            size = 1

        instructions.append({
            'offset': offset,
            'addr': base_addr + offset,
            'opcode': opcode,
            'size': size,
            'mnemonic': mnemonic,
        })
        i += size

    return instructions


def find_jumps(data: bytes, base_addr: int = 0) -> List[Dict]:
    """
    查找所有跳转/调用指令

    识别:
        - E8 (call rel32)
        - E9 (jmp rel32)
        - EB (jmp rel8)
        - 74/75 (je/jne rel8)
        - 0F 84/85 (je/jne rel32)

    Returns:
        list of dict:
            - type:    'CALL' / 'JMP' / 'JE' / 'JNE' / 'JL' / 'JGE' / 'JLE' / 'JG'
            - offset:  在 data 中的偏移
            - addr:    虚拟地址
            - target:  跳转目标虚拟地址
    """
    jumps = []
    i = 0
    while i < len(data) - 1:
        op = data[i]
        if op == 0xE8 and i + 4 < len(data):
            rel = struct.unpack_from('<i', data, i + 1)[0]
            target = (base_addr + i + 5 + rel) & 0xFFFFFFFF
            jumps.append({'type': 'CALL', 'offset': i, 'addr': base_addr + i, 'target': target})
            i += 5
        elif op == 0xE9 and i + 4 < len(data):
            rel = struct.unpack_from('<i', data, i + 1)[0]
            target = (base_addr + i + 5 + rel) & 0xFFFFFFFF
            jumps.append({'type': 'JMP', 'offset': i, 'addr': base_addr + i, 'target': target})
            i += 5
        elif op == 0xEB:
            rel = struct.unpack_from('<b', data, i + 1)[0]
            target = (base_addr + i + 2 + rel) & 0xFFFFFFFF
            jumps.append({'type': 'JMP', 'offset': i, 'addr': base_addr + i, 'target': target})
            i += 2
        elif op == 0x74:
            rel = struct.unpack_from('<b', data, i + 1)[0]
            target = (base_addr + i + 2 + rel) & 0xFFFFFFFF
            jumps.append({'type': 'JE', 'offset': i, 'addr': base_addr + i, 'target': target})
            i += 2
        elif op == 0x75:
            rel = struct.unpack_from('<b', data, i + 1)[0]
            target = (base_addr + i + 2 + rel) & 0xFFFFFFFF
            jumps.append({'type': 'JNE', 'offset': i, 'addr': base_addr + i, 'target': target})
            i += 2
        elif op == 0x0F and i + 5 < len(data):
            op2 = data[i + 1]
            if op2 == 0x84:
                rel = struct.unpack_from('<i', data, i + 2)[0]
                target = (base_addr + i + 6 + rel) & 0xFFFFFFFF
                jumps.append({'type': 'JE', 'offset': i, 'addr': base_addr + i, 'target': target})
                i += 6
            elif op2 == 0x85:
                rel = struct.unpack_from('<i', data, i + 2)[0]
                target = (base_addr + i + 6 + rel) & 0xFFFFFFFF
                jumps.append({'type': 'JNE', 'offset': i, 'addr': base_addr + i, 'target': target})
                i += 6
            else:
                i += 2
        else:
            i += 1
    return jumps


def find_function_prologues(data: bytes) -> List[int]:
    """
    查找常见的函数开头模式

    Returns:
        匹配位置列表 (在 data 中的偏移)
    """
    patterns = [
        b'\x55\x8B\xEC',          # push ebp; mov ebp, esp
        b'\x83\xEC',              # sub esp, imm8
        b'\x81\xEC',              # sub esp, imm32
        b'\x53\x8B\x5C\x24',     # push ebx; mov ebx, [esp+x]
        b'\x56\x8B\x74\x24',     # push esi; mov esi, [esp+x]
        b'\x57\x8B\x7C\x24',     # push edi; mov edi, [esp+x]
    ]
    found = set()
    for pat in patterns:
        pos = 0
        while True:
            pos = data.find(pat, pos)
            if pos == -1:
                break
            found.add(pos)
            pos += 1
    return sorted(found)


def find_api_patterns(data: bytes) -> Dict[str, List[int]]:
    """
    查找 API 调用相关模式

    Returns:
        dict: {
            'push_imm8':   [offsets],     # 0x6A push imm8 (参数)
            'push_imm32':  [offsets],     # 0x68 push imm32 (参数)
            'call_indirect':   [offsets], # FF 15 call [imm32] (IAT 调用)
            'call_eax':    [offsets],     # FF D0 call eax
            'call_edi':    [offsets],     # FF D7 call edi
        }
    """
    results = {
        'push_imm8': [],
        'push_imm32': [],
        'call_indirect': [],
        'call_eax': [],
        'call_edi': [],
    }
    for i in range(len(data) - 1):
        if data[i] == 0x6A:
            results['push_imm8'].append(i)
        elif data[i] == 0x68:
            results['push_imm32'].append(i)
        elif i + 1 < len(data) and data[i] == 0xFF and data[i+1] == 0x15:
            results['call_indirect'].append(i)
        elif i + 1 < len(data) and data[i] == 0xFF and data[i+1] == 0xD0:
            results['call_eax'].append(i)
        elif i + 1 < len(data) and data[i] == 0xFF and data[i+1] == 0xD7:
            results['call_edi'].append(i)
    return results


def find_indirect_iat_calls(data: bytes, iat_range: Tuple[int, int]) -> List[Dict]:
    """
    查找间接调用 IAT 的指令 (FF 15 [addr])

    Args:
        data: 代码数据
        iat_range: (iat_low, iat_high) IAT 地址范围

    Returns:
        list of {offset, addr_in_iat, addr}
    """
    iat_low, iat_high = iat_range
    calls = []
    for i in range(len(data) - 5):
        if data[i] == 0xFF and data[i+1] == 0x15:
            addr = struct.unpack_from('<I', data, i + 2)[0]
            if iat_low <= addr <= iat_high:
                calls.append({'offset': i, 'addr_in_iat': addr})
    return calls


def top_opcodes(data: bytes, top_n: int = 15) -> List[Tuple[int, int]]:
    """
    统计最常出现的字节值 (用于代码特征分析)

    Returns:
        [(byte_value, count), ...] 按出现次数降序
    """
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    indexed = [(i, counts[i]) for i in range(256)]
    indexed.sort(key=lambda x: -x[1])
    return indexed[:top_n]


def classify_jumps(jumps: List[Dict], section_vaddr: int,
                  section_size: int) -> Dict[str, List]:
    """
    将跳转列表分类为内部跳转和外部跳转

    Returns:
        {'inside': [jumps], 'outside': [jumps]}
    """
    inside = []
    outside = []
    for j in jumps:
        if section_vaddr <= j['target'] < section_vaddr + section_size:
            inside.append(j)
        else:
            outside.append(j)
    return {'inside': inside, 'outside': outside}