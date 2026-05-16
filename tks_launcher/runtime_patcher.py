#!/usr/bin/env python3
"""TKS.exe 运行时内存补丁工具

在 TKS.exe 解密并注入子进程后，通过 WriteProcessMemory 修改硬编码数值。

用法:
  python runtime_patcher.py                              # 自动启动 TKS.exe 并打补丁
  python runtime_patcher.py --pid 1234                   # 对已运行的进程打补丁
  python runtime_patcher.py --monitor                    # 仅监控，手动启动 TKS.exe
  python runtime_patcher.py --dump-config                # 生成补丁配置模板

补丁配置文件: patch_config.json（与脚本同目录）
"""

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import os
import time
import json
import subprocess
import threading
import argparse
from pathlib import Path

# ============================================================================
# Windows API 定义
# ============================================================================

kernel32 = ctypes.windll.kernel32

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000

# VirtualAllocEx / VirtualFreeEx for dynamic cave allocation
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
kernel32.VirtualFreeEx.restype = wt.BOOL
kernel32.VirtualFreeEx.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


# ============================================================================
# 进程工具
# ============================================================================

def find_process_by_name(name_pattern):
    results = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return results

    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            name = pe.szExeFile.decode('ascii', errors='replace').lower()
            if name_pattern.lower() in name:
                results.append({
                    'pid': pe.th32ProcessID,
                    'name': name,
                    'parent_pid': pe.th32ParentProcessID,
                })
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break

    kernel32.CloseHandle(snap)
    return results


def get_child_processes(parent_pid):
    children = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return children

    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            if pe.th32ParentProcessID == parent_pid:
                children.append({
                    'pid': pe.th32ProcessID,
                    'name': pe.szExeFile.decode('ascii', errors='replace'),
                })
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break

    kernel32.CloseHandle(snap)
    return children


def get_module_base(pid, module_name=None):
    """获取进程主模块的基址"""
    snap = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return None

    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)

    result = None
    if kernel32.Module32First(snap, ctypes.byref(me)):
        while True:
            mod_path = me.szExePath.decode('ascii', errors='replace')
            mod_name = me.szModule.decode('ascii', errors='replace')
            base = ctypes.addressof(me.modBaseAddr.contents) if me.modBaseAddr else 0

            if module_name is None:
                # 第一个模块即主模块
                result = {'name': mod_name, 'path': mod_path, 'base': base}
                break
            elif module_name.lower() in mod_name.lower():
                result = {'name': mod_name, 'path': mod_path, 'base': base}
                break

            if not kernel32.Module32Next(snap, ctypes.byref(me)):
                break

    kernel32.CloseHandle(snap)
    return result


# ============================================================================
# 内存补丁
# ============================================================================

def apply_patch(pid, base_address, patches, dry_run=False):
    """对指定进程应用内存补丁"""
    access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    proc = kernel32.OpenProcess(access, False, pid)
    if not proc:
        print(f"  [ERROR] 无法打开进程 {pid}: error {kernel32.GetLastError()}")
        return 0, len(patches), []

    results = []
    success = 0
    fail = 0

    for p in patches:
        rva = p['rva']
        new_data = p['data']
        desc = p.get('desc', '')
        addr = base_address + rva

        # 先读取原始数据
        old_buf = ctypes.create_string_buffer(len(new_data))
        bytes_read = ctypes.c_size_t(0)
        if not kernel32.ReadProcessMemory(proc, ctypes.c_void_p(addr),
                                          old_buf, len(new_data), ctypes.byref(bytes_read)):
            results.append({
                'rva': rva, 'addr': addr, 'desc': desc,
                'status': 'failed',
                'old': b'',
                'error': f'ReadProcessMemory failed: {kernel32.GetLastError()}',
            })
            fail += 1
            continue

        old_data = old_buf.raw[:bytes_read.value]

        if old_data == new_data:
            results.append({
                'rva': rva, 'addr': addr, 'desc': desc,
                'status': 'already_patched',
                'old': old_data, 'new': new_data,
            })
            success += 1
            continue

        if dry_run:
            results.append({
                'rva': rva, 'addr': addr, 'desc': desc,
                'status': 'would_patch',
                'old': old_data, 'new': new_data,
            })
            success += 1
            continue

        # VirtualProtectEx: 临时改为可写
        old_protect = wt.DWORD()
        if not kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                         len(new_data), PAGE_EXECUTE_READWRITE,
                                         ctypes.byref(old_protect)):
            results.append({
                'rva': rva, 'addr': addr, 'desc': desc,
                'status': 'failed',
                'old': old_data,
                'error': f'VirtualProtectEx failed: {kernel32.GetLastError()}',
            })
            fail += 1
            continue

        # 写入新数据
        new_buf = ctypes.create_string_buffer(new_data)
        bytes_written = ctypes.c_size_t(0)
        if kernel32.WriteProcessMemory(proc, ctypes.c_void_p(addr),
                                       new_buf, len(new_data),
                                       ctypes.byref(bytes_written)):
            # 恢复原保护属性
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      len(new_data), old_protect,
                                      ctypes.byref(wt.DWORD()))
            # 验证写入
            verify_buf = ctypes.create_string_buffer(len(new_data))
            kernel32.ReadProcessMemory(proc, ctypes.c_void_p(addr),
                                       verify_buf, len(new_data),
                                       ctypes.byref(ctypes.c_size_t(0)))
            verify_data = verify_buf.raw[:len(new_data)]
            if verify_data == new_data:
                results.append({
                    'rva': rva, 'addr': addr, 'desc': desc,
                    'status': 'patched',
                    'old': old_data, 'new': new_data,
                })
                success += 1
            else:
                results.append({
                    'rva': rva, 'addr': addr, 'desc': desc,
                    'status': 'failed',
                    'old': old_data,
                    'error': f'写入验证失败: 期望 {new_data.hex()} 实际 {verify_data.hex()}',
                })
                fail += 1
        else:
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      len(new_data), old_protect,
                                      ctypes.byref(wt.DWORD()))
            results.append({
                'rva': rva, 'addr': addr, 'desc': desc,
                'status': 'failed',
                'old': old_data,
                'error': f'WriteProcessMemory failed: {kernel32.GetLastError()}',
            })
            fail += 1

    kernel32.CloseHandle(proc)
    return success, fail, results


# ============================================================================
# LZSS 解压 (for WarPC.dat reading)
# ============================================================================

def lzss_decompress(data):
    """Minimal LZSS decompress matching sub_452B14."""
    if len(data) < 12:
        return b''
    total_size = struct.unpack_from('<I', data, 0)[0]
    block_size = struct.unpack_from('<I', data, 4)[0]
    window = bytearray([0x20] * 4096)
    wp = 4078
    output = bytearray()
    flags = 0
    pos = 12
    bc = 4
    while bc < block_size and len(output) < total_size:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1
            bc += 1
        if flags & 1:
            if pos >= len(data):
                break
            b = data[pos]
            pos += 1
            bc += 1
            output.append(b)
            window[wp] = b
            wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            b1, b2 = data[pos], data[pos + 1]
            pos += 2
            bc += 2
            ro = ((b2 & 0xF0) << 4) | b1
            rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = window[(j + ro) & 0xFFF]
                output.append(b)
                window[wp] = b
                wp = (wp + 1) & 0xFFF
    return bytes(output[:total_size])


# ============================================================================
# AwkSprite 动态补丁
# ============================================================================

# Cave 代码模板 (51 字节). Hook 在 cmp [ebp-6],0 之后 (RVA 0x309A6).
# 读取 WarPC WORD[260] (byte offset 520 = 0x208).
# 若 WORD[260]!=0: [ebp-6] = WORD[260]-6, 原 +6 后结果 = WORD[260].
CAVE_TEMPLATE = bytes([
    0x50, 0x51,                                           # push eax,ecx
    0x0F, 0xBF, 0x45, 0xFA,                               # movsx eax,[ebp-6]
    0x66, 0x85, 0xC0,                                     # test ax,ax
    0x74, 0x25,                                           # jz .done (v26==0 → ZF=1)
    0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,                   # imul eax,0x41E
    0x05, 0x08, 0x7F, 0x75, 0x00,                         # add eax,0x757F08
    0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,             # movzx ecx,[eax+0x208]
    0x66, 0x85, 0xC9,                                     # test cx,cx
    0x75, 0x04,                                           # jnz .use_custom
    0x85, 0xC0,                                           # test eax,eax (ZF=0)
    0xEB, 0x0A,                                           # jmp .done
    # .use_custom:
    0x83, 0xE9, 0x06,                                     # sub ecx,6
    0x66, 0x89, 0x4D, 0xFA,                               # mov [ebp-6],cx
    0x66, 0x85, 0xC9,                                     # test cx,cx (ZF based on v26)
    # .done:
    0x59, 0x58,                                           # pop ecx,eax
    0xC3,                                                  # ret
])

HOOK_RVA = 0x309A6  # cmp [ebp-6],0 at sub_4307CC


def build_awksprite_patches(base_addr, cave_addr):
    """Build the AwkSprite cave + hook patches.
    base_addr: module base (e.g. 0x400000)
    cave_addr: absolute address from VirtualAllocEx
    """
    patches = []
    # Cave code (51 bytes) — use RVA = cave - base so addr = base + RVA = cave
    cave_rva = cave_addr - base_addr
    patches.append({
        'rva': cave_rva,
        'data': CAVE_TEMPLATE,
        'desc': f'AwkSprite PATH1 cave@0x{cave_addr:08X}: read WarPC WORD[260] (51B)',
    })
    # Hook: replace cmp [ebp-6],0 with call cave
    # call offset = cave_abs - (base + HOOK_RVA + 5)
    hook_abs = base_addr + HOOK_RVA
    call_off = cave_addr - (hook_abs + 5)
    call_bytes = b'\xE8' + struct.pack('<i', call_off)
    patches.append({
        'rva': HOOK_RVA,
        'data': call_bytes,
        'desc': f'AwkSprite PATH1: hook cmp [ebp-6],0 -> cave@0x{cave_addr:08X}',
    })
    return patches


# PortraitCave1 (41B): hook at RVA 0x17A50 (add ax,0xD3; push eax).
# Verified: ECX = char_idx * 527, AX = portrait from [ecx*2+0x757F0A].
# Both paths share identical epilogue (add esp,8; pop; xchg; jmp).
PORTRAIT_CAVE1 = bytes([
    0x50,                               # push eax           ; save raw portrait
    0x51,                               # push ecx           ; save ecx*527
    0x52,                               # push edx           ; save scratch
    0x8B, 0xC1,                         # mov eax, ecx       ; eax = ecx
    0x03, 0xC0,                         # add eax, eax       ; eax = char_idx*1054
    0x05, 0x08, 0x7F, 0x75, 0x00,       # add eax, 0x757F08  ; eax = WarPC record
    0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00,  # movzx eax,[eax+0x20A] ; WORD[261]
    0x66, 0x85, 0xC0,                   # test ax, ax
    0x75, 0x08,                         # jnz .shared_exit   ; override→skip normal
    # Normal: read raw portrait from [esp+8] (saved_eax slot), add 0xD3
    0x8B, 0x44, 0x24, 0x08,             # mov eax, [esp+8]   ; eax = raw portrait
    0x66, 0x05, 0xD3, 0x00,             # add ax, 0xD3       ; eax = result
    # === Shared exit (both paths) ===
    0x83, 0xC4, 0x08,                   # add esp, 8         ; discard edx,ecx
    0x5A,                               # pop edx            ; discard saved eax
    0x87, 0x04, 0x24,                   # xchg eax, [esp]    ; eax=ret_addr, [esp]=result
    0xFF, 0xE0,                         # jmp eax
])

# PortraitCave2 (42B): hook at RVA 0x17E1A (add dx,0xD3; push edx).
# Verified: EAX = char_idx * 527, DX = portrait from [eax*2+0x757F0A].
PORTRAIT_CAVE2 = bytes([
    0x52,                               # push edx           ; save raw portrait
    0x51,                               # push ecx           ; save scratch
    0x50,                               # push eax           ; save eax (= char_idx*527)
    0x03, 0xC0,                         # add eax, eax       ; eax = char_idx*1054
    0x05, 0x08, 0x7F, 0x75, 0x00,       # add eax, 0x757F08  ; eax = WarPC record
    0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00,  # movzx eax,[eax+0x20A] ; WORD[261]
    0x66, 0x85, 0xC0,                   # test ax, ax
    0x75, 0x08,                         # jnz .shared_exit   ; override→skip normal
    # Normal: read raw portrait from [esp+8] (saved_edx slot), add 0xD3
    0x8B, 0x44, 0x24, 0x08,             # mov eax, [esp+8]   ; eax = raw portrait
    0x66, 0x05, 0xD3, 0x00,             # add ax, 0xD3       ; eax = result
    # === Shared exit (both paths) ===
    0x0F, 0xB7, 0xD0,                   # movzx edx, ax      ; edx = result
    0x83, 0xC4, 0x08,                   # add esp, 8         ; discard eax,ecx
    0x59,                               # pop ecx            ; discard saved edx
    0x87, 0x14, 0x24,                   # xchg edx, [esp]    ; edx=ret_addr, [esp]=result
    0xFF, 0xE2,                         # jmp edx
])

PORTRAIT_HOOK1_RVA = 0x17A50  # Verified: add ax,0xD3; push eax (5B)
PORTRAIT_HOOK2_RVA = 0x17E1A  # Verified: add dx,0xD3; push edx (6B)


def build_portrait_patches(base_addr, cave_base):
    """Build Portrait cave + hook patches. Caves at cave_base+64 and cave_base+128."""
    patches = []
    # PATH1 (selected) cave at cave_base+64. RVA 0x17A50, 5B original → 5B call
    pcave1 = cave_base + 64
    pcave1_rva = pcave1 - base_addr
    patches.append({
        'rva': pcave1_rva, 'data': PORTRAIT_CAVE1,
        'desc': f'Portrait PATH1 cave@0x{pcave1:08X} (selected, 41B)',
    })
    call1_off = pcave1 - (base_addr + PORTRAIT_HOOK1_RVA + 5)
    patches.append({
        'rva': PORTRAIT_HOOK1_RVA,
        'data': b'\xE8' + struct.pack('<i', call1_off),
        'desc': f'Portrait PATH1: hook add ax,0xD3 -> cave@0x{pcave1:08X}',
    })
    # PATH2 (non-selected) cave at cave_base+128. RVA 0x17E1A, 6B original → 6B (call+NOP)
    pcave2 = cave_base + 128
    pcave2_rva = pcave2 - base_addr
    patches.append({
        'rva': pcave2_rva, 'data': PORTRAIT_CAVE2,
        'desc': f'Portrait PATH2 cave@0x{pcave2:08X} (non-selected, 42B)',
    })
    call2_off = pcave2 - (base_addr + PORTRAIT_HOOK2_RVA + 5)
    patches.append({
        'rva': PORTRAIT_HOOK2_RVA,
        'data': b'\xE8' + struct.pack('<i', call2_off) + b'\x90',
        'desc': f'Portrait PATH2: hook add dx,0xD3 -> cave@0x{pcave2:08X}',
    })
    return patches


def inject_warpc_data(pid):
    """Inject WORD[260] values from WarPC.dat into game memory."""
    warpc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', '..', 'WarPC.dat')
    # Try alongside the exe too
    alt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'WarPC.dat')
    for p in [warpc_path, alt_path, 'WarPC.dat']:
        if os.path.exists(p):
            warpc_path = p
            break
    else:
        print("  [WARN] WarPC.dat not found for AwkSprite data inject")
        return

    with open(warpc_path, 'rb') as f:
        compressed = f.read()
    dec = lzss_decompress(compressed)
    if len(dec) < 143 * 1054:
        print("  [WARN] WarPC.dat decompressed size mismatch")
        return

    proc = kernel32.OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, pid)
    if not proc:
        print("  [WARN] Cannot open process for AwkSprite data inject")
        return

    WARPC_BASE = 0x757F08
    REC_SIZE = 1054

    w260_count = 0
    w261_count = 0
    for i in range(143):
        base_off = i * REC_SIZE
        # WORD[260] (AwkSprite)
        w260 = struct.unpack_from('<h', dec, base_off + 520)[0]
        if w260 != 0:
            addr = WARPC_BASE + base_off + 520
            data = struct.pack('<h', w260)
            old_protect = wt.DWORD()
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      2, PAGE_EXECUTE_READWRITE,
                                      ctypes.byref(old_protect))
            written = ctypes.c_size_t(0)
            buf = ctypes.create_string_buffer(data)
            kernel32.WriteProcessMemory(proc, ctypes.c_void_p(addr),
                                        buf, 2, ctypes.byref(written))
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      2, old_protect, ctypes.byref(wt.DWORD()))
            w260_count += 1
        # WORD[261] (portrait override)
        w261 = struct.unpack_from('<h', dec, base_off + 522)[0]
        if w261 != 0:
            addr = WARPC_BASE + base_off + 522
            data = struct.pack('<h', w261)
            old_protect = wt.DWORD()
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      2, PAGE_EXECUTE_READWRITE,
                                      ctypes.byref(old_protect))
            written = ctypes.c_size_t(0)
            buf = ctypes.create_string_buffer(data)
            kernel32.WriteProcessMemory(proc, ctypes.c_void_p(addr),
                                        buf, 2, ctypes.byref(written))
            kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr),
                                      2, old_protect, ctypes.byref(wt.DWORD()))
            w261_count += 1

    kernel32.CloseHandle(proc)
    print(f"  Data inject: {w260_count} W260, {w261_count} W261")


# ============================================================================
# 补丁配置
# ============================================================================

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'patch_config.json')


def load_patch_config(config_path=None):
    """加载补丁配置文件"""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        print(f"[ERROR] 补丁配置文件不存在: {config_path}")
        print(f"  使用 --dump-config 生成模板")
        return None

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    patches = []
    for entry in config.get('patches', []):
        rva_str = entry.get('rva', '')
        if isinstance(rva_str, str):
            rva = int(rva_str, 16)
        else:
            rva = rva_str

        # 支持多种输入格式
        if 'data' in entry:
            # 直接指定字节: "data": "B8 2A 00 00 00"
            hex_str = entry['data'].replace(' ', '')
            data = bytes.fromhex(hex_str)
        elif 'type' in entry and 'value' in entry:
            # 按类型编码: "type": "uint32", "value": 100
            data = encode_value(entry['type'], entry['value'])
        elif 'bytes' in entry:
            # 十进制字节列表: "bytes": [184, 42, 0, 0, 0]
            data = bytes(entry['bytes'])
        else:
            print(f"  [WARN] 补丁条目缺少 data/type+value/bytes: {entry}")
            continue

        patches.append({
            'rva': rva,
            'data': data,
            'desc': entry.get('desc', ''),
        })

    return patches


def encode_value(type_str, value):
    """将值编码为字节"""
    if type_str == 'uint8' or type_str == 'byte':
        return struct.pack('<B', value)
    elif type_str == 'uint16' or type_str == 'word':
        return struct.pack('<H', value)
    elif type_str == 'uint32' or type_str == 'dword':
        return struct.pack('<I', value)
    elif type_str == 'uint64' or type_str == 'qword':
        return struct.pack('<Q', value)
    elif type_str == 'int32':
        return struct.pack('<i', value)
    elif type_str == 'float':
        return struct.pack('<f', value)
    elif type_str == 'double':
        return struct.pack('<d', value)
    else:
        raise ValueError(f"不支持的类型: {type_str}")


def dump_config_template():
    """生成补丁配置模板"""
    template = {
        "_说明": (
            "TKS.exe 运行时补丁配置文件\n"
            "RVA = IDA中的地址 - ImageBase(0x00400000)\n"
            "支持三种值格式:\n"
            '  1. "data": "B8 2A 00 00 00" — 直接写十六进制字节\n'
            '  2. "type": "uint32", "value": 100 — 按类型编码\n'
            '  3. "bytes": [184, 42, 0, 0, 0] — 十进制字节列表\n'
            "类型: uint8, uint16, uint32, uint64, int32, float, double"
        ),
        "patches": [
            {
                "desc": "示例: 修改某个 uint32 常量",
                "rva": "0x12345",
                "type": "uint32",
                "value": 999,
            },
            {
                "desc": "示例: 直接指定字节序列",
                "rva": "0x67890",
                "data": "B8 2A 00 00 00 90",
            },
        ],
    }

    path = DEFAULT_CONFIG_PATH
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    print(f"补丁配置模板已生成: {path}")
    print(f"请在 IDA 中确定目标地址，计算 RVA = 地址 - 0x00400000，填入配置后运行本脚本")


# ============================================================================
# 主逻辑
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='TKS.exe 运行时内存补丁')
    parser.add_argument('--monitor', action='store_true',
                        help='仅监控模式，不自动启动 TKS.exe')
    parser.add_argument('--pid', type=int, default=None,
                        help='直接对指定 PID 的进程打补丁')
    parser.add_argument('--wait', type=float, default=15.0,
                        help='监控等待时间(秒)，默认15')
    parser.add_argument('--exe', type=str,
                        default=r'游戏目录/TKS.exe',
                        help='TKS.exe 路径')
    parser.add_argument('--config', type=str, default=None,
                        help='补丁配置文件路径（默认: patch_config.json）')
    parser.add_argument('--dump-config', action='store_true',
                        help='生成补丁配置模板文件')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅验证，不实际写入')
    parser.add_argument('--verify', action='store_true',
                        help='验证模式：仅读取并报告目标地址的当前值')
    parser.add_argument('--watch', action='store_true',
                        help='监控模式：补丁后持续监控内存值是否被回退')

    args = parser.parse_args()

    if args.dump_config:
        dump_config_template()
        return

    # 加载补丁配置
    patches = load_patch_config(args.config)
    if patches is None:
        return

    print("=" * 70)
    print("TKS.exe 运行时内存补丁工具")
    print("=" * 70)
    print(f"  补丁数量: {len(patches)}")
    for p in patches:
        hex_str = ' '.join(f'{b:02X}' for b in p['data'])
        print(f"    RVA=0x{p['rva']:08X}  bytes=[{hex_str}]  {p['desc']}")

    if args.dry_run:
        print(f"\n  *** DRY RUN 模式 — 不会实际修改内存 ***")
    if args.verify:
        print(f"  *** VERIFY 模式 — 仅读取当前值，不修改 ***")

    # 直接 pid 模式
    if args.pid:
        pid = args.pid
        print(f"\n■ 目标进程 PID={pid}")

        info = get_module_base(pid)
        if not info:
            print(f"  [ERROR] 无法获取进程 {pid} 的模块信息")
            return

        print(f"  主模块: {info['name']}  Base=0x{info['base']:08X}")
        if args.verify:
            success, fail, results = apply_patch(pid, info['base'], patches, dry_run=True)
            _print_verify(results)
        else:
            success, fail, results = apply_patch(pid, info['base'], patches, args.dry_run)
            _print_results(results, success, fail)
        return

    # 监控模式
    tks_dir = os.path.dirname(args.exe)
    tks_pid = None
    tks_process = None

    if not args.monitor:
        print(f"\n■ 启动 TKS.exe: {args.exe}")
        try:
            tks_process = subprocess.Popen(
                [args.exe], cwd=tks_dir)
            tks_pid = tks_process.pid
            print(f"  TKS.exe PID = {tks_pid}")
        except OSError as e:
            print(f"  [ERROR] 无法启动 TKS.exe: {e}")
            return
    else:
        print(f"\n■ 监控模式 — 请手动启动 TKS.exe")
        print(f"  等待检测到 TKS.exe 进程...")

    # 等待子进程出现
    print(f"\n■ 等待代码解密完成 (最多 {args.wait} 秒)...")
    child_pid = None
    start_time = time.time()

    while time.time() - start_time < args.wait:
        if not tks_pid:
            procs = find_process_by_name('tks')
            if procs:
                tks_pid = procs[0]['pid']
                print(f"  检测到 TKS.exe: PID={tks_pid}")

        if tks_pid:
            children = get_child_processes(tks_pid)
            if children:
                child_pid = children[0]['pid']
                print(f"  检测到子进程: PID={child_pid} Name={children[0]['name']}")
                # 再等一下确保代码注入完成
                time.sleep(2)
                break

        if tks_process and tks_process.poll() is not None:
            print(f"  TKS.exe 已退出 (code={tks_process.returncode})")
            break

        time.sleep(0.5)

    if not child_pid:
        print("  [ERROR] 超时，未检测到子进程")
        if tks_process:
            tks_process.terminate()
        return

    # 获取子进程模块基址
    info = get_module_base(child_pid)
    if not info:
        print(f"  [ERROR] 无法获取子进程 {child_pid} 的模块信息")
        if tks_process:
            tks_process.terminate()
        return

    print(f"\n■ 子进程信息:")
    print(f"  模块: {info['name']}")
    print(f"  基址: 0x{info['base']:08X}")
    print(f"  路径: {info['path']}")

    # 应用补丁
    if args.verify:
        print(f"\n■ 验证补丁地址当前值...")
        success, fail, results = apply_patch(child_pid, info['base'], patches, dry_run=True)
        _print_verify(results)
    elif args.watch:
        # 先打补丁
        print(f"\n■ 应用补丁...")
        success, fail, results = apply_patch(child_pid, info['base'], patches)
        _print_results(results, success, fail)
        if success > 0:
            # 持续监控
            watch_memory(child_pid, info['base'], patches, duration=60)
    else:
        print(f"\n■ 应用补丁 (config)...")
        success, fail, results = apply_patch(child_pid, info['base'], patches, args.dry_run)
        _print_results(results, success, fail)

        # ---- AwkSprite 动态补丁 ----
        if not args.dry_run and not args.verify:
            base = info['base']
            proc = kernel32.OpenProcess(
                PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                False, child_pid)
            cave_addr = 0
            if proc:
                cave_addr = kernel32.VirtualAllocEx(
                    proc, ctypes.c_void_p(0), 256,
                    MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                kernel32.CloseHandle(proc)
            if cave_addr:
                print(f"\n■ AwkSprite cave: 0x{cave_addr:08X} (dynamic alloc)")
                awk_patches = build_awksprite_patches(base, cave_addr)
                awk_success, awk_fail, awk_results = apply_patch(
                    child_pid, base, awk_patches)
                _print_results(awk_results, awk_success, awk_fail)
                success += awk_success
                fail += awk_fail
                # 注入 WarPC WORD[260]/WORD[261] 数据
                inject_warpc_data(child_pid)
                # Portrait 补丁
                portrait_patches = build_portrait_patches(base, cave_addr)
                p_success, p_fail, p_results = apply_patch(
                    child_pid, base, portrait_patches)
                _print_results(p_results, p_success, p_fail)
                success += p_success
                fail += p_fail
            else:
                print("  [WARN] VirtualAllocEx failed, AwkSprite patch skipped")

        if success > 0 and fail == 0:
            print(f"\n■ 验证补丁已写入内存...")
            v_success, v_fail, v_results = apply_patch(child_pid, info['base'], patches, dry_run=True)
            _print_verify(v_results)
            print(f"\n■ 补丁已应用！游戏正在运行，请现在测试修改效果。")
            print(f"  注意: 补丁仅在内存中生效，关闭游戏后失效。")
            print(f"  按 Enter 终止 TKS.exe 和子进程...")
            input()
        else:
            print(f"\n  [WARN] 补丁未完全应用，请检查配置")

    # 清理
    if tks_process and tks_process.poll() is None:
        tks_process.terminate()
        tks_process.wait(timeout=5)


def _print_results(results, success, fail):
    print(f"\n  结果: 成功 {success}, 失败 {fail}")
    for r in results:
        old_hex = ' '.join(f'{b:02X}' for b in r.get('old', b''))
        new_data = r.get('new')
        new_hex = ' '.join(f'{b:02X}' for b in new_data) if new_data else '(N/A)'
        status_icon = {
            'patched': '✓', 'already_patched': '=', 'would_patch': '~', 'failed': '✗'
        }.get(r['status'], '?')
        print(f"    [{status_icon}] 0x{r['addr']:08X} (RVA=0x{r['rva']:08X})")
        if r['status'] != 'failed':
            print(f"         {old_hex} → {new_hex}")
        if r.get('desc'):
            print(f"         {r['desc']}")
        if r['status'] == 'failed':
            print(f"         ERROR: {r.get('error', 'unknown')}")


def _print_verify(results):
    """打印验证结果，重点显示当前值 vs 期望值"""
    print(f"\n  验证结果:")
    all_match = True
    for r in results:
        old_hex = ' '.join(f'{b:02X}' for b in r['old']) if r['old'] else '(读取失败)'
        new_hex = ' '.join(f'{b:02X}' for b in r['new'])
        match = "✓ 已修改" if r['status'] == 'already_patched' else "✗ 未修改"
        if r['status'] != 'already_patched':
            all_match = False
        print(f"    [{match}] RVA=0x{r['rva']:08X}  当前值=[{old_hex}]  期望值=[{new_hex}]")
        if r['desc']:
            print(f"         {r['desc']}")
        if 'error' in r:
            print(f"         ERROR: {r['error']}")

    if all_match:
        print(f"\n  所有补丁已生效。")
    else:
        print(f"\n  部分补丁未生效 — 需要重新运行补丁。")


def watch_memory(pid, base_address, patches, duration=60):
    """持续监控补丁地址的内存值，检测是否被 CopyMem-II 回退"""
    access = PROCESS_VM_READ
    proc = kernel32.OpenProcess(access, False, pid)
    if not proc:
        print(f"  [ERROR] 无法打开进程 {pid}")
        return False

    track = {}
    for p in patches:
        addr = base_address + p['rva']
        track[p['rva']] = {
            'addr': addr, 'desc': p.get('desc', ''),
            'expected': p['data'], 'current': None, 'changes': [],
        }

    print(f"\n■ 监控内存值 (持续 {duration} 秒), 检测 CopyMem-II 回退...")
    start = time.time()
    tick = 0
    try:
        while time.time() - start < duration:
            for rva, t in track.items():
                buf = ctypes.create_string_buffer(len(t['expected']))
                if kernel32.ReadProcessMemory(proc, ctypes.c_void_p(t['addr']),
                                              buf, len(t['expected']),
                                              ctypes.byref(ctypes.c_size_t(0))):
                    val = buf.raw
                    if t['current'] is None:
                        t['current'] = val
                    elif val != t['current']:
                        t['changes'].append({
                            'time': time.time() - start,
                            'old': t['current'], 'new': val,
                        })
                        t['current'] = val
                        print(f"  [{time.time()-start:5.1f}s] RVA=0x{rva:08X}: "
                              f"{t['current'].hex().upper()} → {val.hex().upper()}  ← 被回退!")
            tick += 1
            if tick % 10 == 0:
                elapsed = int(time.time() - start)
                for rva, t in track.items():
                    hex_val = t['current'].hex().upper() if t['current'] else '?'
                    exp = t['expected'].hex().upper()
                    status = "OK" if t['current'] == t['expected'] else f"REVERTED (期望{exp})"
                    print(f"  [{elapsed:3d}s] RVA=0x{rva:08X}: {hex_val} ({status})")
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    print(f"\n■ 监控总结:")
    all_ok = True
    for rva, t in track.items():
        hex_val = t['current'].hex().upper() if t['current'] else '?'
        exp = t['expected'].hex().upper()
        if t['current'] == t['expected']:
            print(f"  RVA=0x{rva:08X}: {hex_val} = 补丁保持 ✓")
        else:
            print(f"  RVA=0x{rva:08X}: {hex_val} ≠ {exp} = 已回退 ✗")
            all_ok = False
            for ch in t['changes']:
                print(f"    @{ch['time']:.1f}s: {ch['old'].hex().upper()} → {ch['new'].hex().upper()}")
    kernel32.CloseHandle(proc)
    return all_ok


def verify_patches(pid, base_address, patches):
    """验证补丁是否已写入目标进程"""
    return apply_patch(pid, base_address, patches, dry_run=True)


if __name__ == '__main__':
    main()
