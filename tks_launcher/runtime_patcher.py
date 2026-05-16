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
        print(f"\n■ 应用补丁...")
        success, fail, results = apply_patch(child_pid, info['base'], patches, args.dry_run)
        _print_results(results, success, fail)
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
        old_hex = ' '.join(f'{b:02X}' for b in r['old'])
        new_hex = ' '.join(f'{b:02X}' for b in r['new'])
        status_icon = {
            'patched': '✓', 'already_patched': '=', 'would_patch': '~', 'failed': '✗'
        }.get(r['status'], '?')
        print(f"    [{status_icon}] 0x{r['addr']:08X} (RVA=0x{r['rva']:08X})")
        print(f"         {old_hex} → {new_hex}")
        if r['desc']:
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
