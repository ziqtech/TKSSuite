#!/usr/bin/env python3
"""TeamMember 诊断工具 — 读取队伍槽数组，验证 TeamMember 是否生效"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import time

kernel32 = ctypes.windll.kernel32

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PAGE_EXECUTE_READWRITE = 0x40

# 关键内存地址（基于 IDA 分析 / ImageBase=0x00400000）
TEAM_ARRAY_RVA = 0x35688C   # word_75688C[6] — 队伍槽
CHAR_DATA_RVA  = 0x357F08   # word_757F08 — 角色属性数据
CHAR_LEVEL_RVA = 0x357F0C   # word_757F0C — 等级数据
CHAR_INIT_RVA  = 0x357F0E   # word_757F0E — 初始化标记
CHAR_STRIDE    = 527         # 每角色 int16 数

PATCH_RVAS = {
    0xDA15: (0xC8, "TeamMember 上限 sub_40DA00"),
    0xE6C1: (0xC8, "CheckTeam 上限 sub_40E65C"),
}


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD), ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]


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
                results.append({'pid': pe.th32ProcessID, 'name': name,
                                'parent_pid': pe.th32ParentProcessID})
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
                children.append({'pid': pe.th32ProcessID,
                                 'name': pe.szExeFile.decode('ascii', errors='replace')})
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)
    return children


def get_module_base(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return None
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)
    result = None
    if kernel32.Module32First(snap, ctypes.byref(me)):
        base = ctypes.addressof(me.modBaseAddr.contents) if me.modBaseAddr else 0
        result = {'name': me.szModule.decode('ascii', errors='replace'),
                  'path': me.szExePath.decode('ascii', errors='replace'), 'base': base}
    kernel32.CloseHandle(snap)
    return result


def read_mem(proc, addr, size):
    buf = ctypes.create_string_buffer(size)
    if kernel32.ReadProcessMemory(proc, ctypes.c_void_p(addr), buf, size,
                                  ctypes.byref(ctypes.c_size_t(0))):
        return buf.raw
    return None


def write_mem(proc, addr, data):
    """写入内存，自动处理保护属性"""
    old_prot = wt.DWORD()
    kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr), len(data),
                              PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot))
    buf = ctypes.create_string_buffer(data)
    result = kernel32.WriteProcessMemory(proc, ctypes.c_void_p(addr), buf,
                                         len(data), ctypes.byref(ctypes.c_size_t(0)))
    kernel32.VirtualProtectEx(proc, ctypes.c_void_p(addr), len(data),
                              old_prot, ctypes.byref(wt.DWORD()))
    return result != 0


def apply_patches(proc, base):
    """应用所有补丁"""
    for rva, (val, desc) in PATCH_RVAS.items():
        addr = base + rva
        old = read_mem(proc, addr, 1)
        if old and old[0] == val:
            print(f"  [=] RVA 0x{rva:08X}: 已是 0x{val:02X} ({desc})")
        else:
            if write_mem(proc, addr, bytes([val])):
                print(f"  [✓] RVA 0x{rva:08X}: 0x{old[0]:02X} → 0x{val:02X} ({desc})")
            else:
                print(f"  [✗] RVA 0x{rva:08X}: 写入失败 ({desc})")


def read_team(proc, base):
    """读取队伍槽数组"""
    addr = base + TEAM_ARRAY_RVA
    data = read_mem(proc, addr, 12)  # 6 × int16 = 12 bytes
    if not data:
        return None
    return [struct.unpack_from('<h', data, i)[0] for i in range(0, 12, 2)]


def read_char_summary(proc, base, char_id):
    """读取角色数据摘要"""
    char_off = CHAR_STRIDE * char_id
    addr = base + CHAR_DATA_RVA + char_off * 2  # int16 → byte offset
    data = read_mem(proc, addr, CHAR_STRIDE * 2)
    if not data:
        return None
    vals = struct.unpack_from('<' + 'h' * min(20, CHAR_STRIDE), data, 0)
    init_flag = struct.unpack_from('<h', data, 3 * 2)[0]  # offset 3
    level = struct.unpack_from('<h', data, 2 * 2)[0]      # offset 2
    return {
        'id': char_id,
        'level': level,
        'init_flag': init_flag,
        'hp': vals[5] if len(vals) > 5 else 0,
        'max_hp': vals[8] if len(vals) > 8 else 0,
        'first_bytes': vals[:10],
    }


def main():
    parser = argparse.ArgumentParser(description='TeamMember 诊断')
    parser.add_argument('--exe', default=r'游戏目录/TKS.exe')
    parser.add_argument('--pid', type=int, default=None)
    parser.add_argument('--wait', type=float, default=3000.0)
    parser.add_argument('--force-add', type=int, default=None,
                        help='直接写角色ID到队伍空槽，绕过TeamMember函数')
    args = parser.parse_args()

    child_pid = args.pid
    tks_process = None

    if not child_pid:
        print("启动 TKS.exe...")
        tks_dir = os.path.dirname(args.exe)
        tks_process = subprocess.Popen([args.exe], cwd=tks_dir)
        tks_pid = tks_process.pid
        print(f"  TKS.exe PID = {tks_pid}")

        print("等待子进程...")
        start = time.time()
        while time.time() - start < 15:
            children = get_child_processes(tks_pid)
            if children:
                child_pid = children[0]['pid']
                print(f"  子进程: PID={child_pid} Name={children[0]['name']}")
                time.sleep(2)
                break
            time.sleep(0.5)

    if not child_pid:
        print("[ERROR] 未找到子进程")
        return

    info = get_module_base(child_pid)
    if not info:
        print("[ERROR] 无法获取模块信息")
        return

    base = info['base']
    print(f"\n模块: {info['name']}  基址: 0x{base:08X}")

    # 打开进程
    access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    proc = kernel32.OpenProcess(access, False, child_pid)
    if not proc:
        print(f"[ERROR] 无法打开进程 {child_pid}")
        return

    # 应用补丁
    print("\n=== 应用补丁 ===")
    apply_patches(proc, base)

    # 读取当前队伍
    print("\n=== 当前队伍 ===")
    team = read_team(proc, base)
    if team:
        for i, m in enumerate(team):
            marker = " ← 主角" if i == 0 else " ← 空" if m == -1 else ""
            print(f"  槽[{i}]: {m:5d}{marker}")
            if m >= 0 and m != -1:
                info = read_char_summary(proc, base, m)
                if info:
                    print(f"         Lv={info['level']} HP={info['hp']}/{info['max_hp']} "
                          f"init={info['init_flag']}")

    # 直接写入模式
    if args.force_add is not None:
        char_id = args.force_add
        print(f"\n=== 直接写入队伍槽: 角色ID={char_id} ===")
        team = read_team(proc, base)
        if team:
            empty_slot = None
            for i, m in enumerate(team):
                if m == -1 and i > 0:  # 不占用主角槽位0
                    empty_slot = i
                    break
            if empty_slot is None:
                print("  [ERROR] 无空槽位 (队伍已满)")
                kernel32.CloseHandle(proc)
                return
            addr = base + TEAM_ARRAY_RVA + empty_slot * 2
            data = struct.pack('<h', char_id)
            if write_mem(proc, addr, data):
                print(f"  已写入: 槽[{empty_slot}] ← {char_id}")
                print(f"  请查看游戏内队伍界面是否出现角色 {char_id}")
                print(f"\n  如果角色出现 → 问题在 sub_40DA00 / 脚本触发")
                print(f"  如果角色不出现 → 问题在渲染层 / 角色数据")
            else:
                print(f"  [ERROR] 写入失败")
        kernel32.CloseHandle(proc)
        return

    # 监控模式
    print(f"\n=== 监控中 ({args.wait}秒) ===")
    print("请触发 TeamMember(85,1)，队伍变化会实时显示...")
    print("按 Ctrl+C 退出\n")

    last_team = team
    start_time = time.time()
    try:
        while time.time() - start_time < args.wait:
            team = read_team(proc, base)
            if team and team != last_team:
                print(f"\n[{time.time()-start_time:5.1f}s] *** 队伍变化! ***")
                for i, m in enumerate(team):
                    prev = last_team[i] if last_team and i < len(last_team) else '?'
                    marker = ""
                    if m != prev:
                        marker = f" ← 变化 (原: {prev})"
                    elif i == 0:
                        marker = " ← 主角"
                    elif m == -1:
                        marker = " ← 空"
                    print(f"  槽[{i}]: {m:5d}{marker}")
                    if m >= 0 and m != -1 and m != (last_team[i] if last_team else None):
                        info = read_char_summary(proc, base, m)
                        if info:
                            print(f"         Lv={info['level']} HP={info['hp']}/{info['max_hp']} "
                                  f"init={info['init_flag']}")
                last_team = team
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    # 最终状态
    print(f"\n=== 最终队伍 ===")
    team = read_team(proc, base)
    if team:
        for i, m in enumerate(team):
            print(f"  槽[{i}]: {m}")

    kernel32.CloseHandle(proc)

    if tks_process and tks_process.poll() is None:
        tks_process.terminate()

    print("\n完成。如果队伍槽中出现 85，说明 TeamMember 正常，问题在渲染层。")
    print("如果队伍槽中始终没有 85，说明 sub_40DA00 没有被调用或参数传递有误。")


if __name__ == '__main__':
    main()
