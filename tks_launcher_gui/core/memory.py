"""Win32 API ctypes 封装 — 从 tks_launcher.py 提取"""
import os
import struct
import ctypes
from ctypes import wintypes
from typing import List, Tuple

# ============================================================
# 辅助函数: C# BitConverter 等价物
# ============================================================

def i32b(val: int) -> bytes:
    """int→4字节 LE"""
    return struct.pack('<i', val)

def i16b(val: int) -> bytes:
    """int→2字节 LE"""
    return struct.pack('<h', val)

def b2i32(data: bytes, off: int = 0) -> int:
    """bytes→int32 LE"""
    return struct.unpack_from('<i', data, off)[0]

def b2u16(data: bytes, off: int = 0) -> int:
    """bytes→uint16 LE"""
    return struct.unpack_from('<H', data, off)[0]

def b2u32(data: bytes, off: int = 0) -> int:
    """bytes→uint32 LE"""
    return struct.unpack_from('<I', data, off)[0]

def bhex(data: bytes, off: int = 0, length: int = -1) -> str:
    """字节转十六进制字符串, 格式: 'AB-CD-EF'"""
    if length < 0:
        length = len(data) - off
    return '-'.join(f'{b:02X}' for b in data[off:off + length])

# ============================================================
# Win32 API ctypes 绑定
# ============================================================

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# kernel32
_OpenProcess = kernel32.OpenProcess
_OpenProcess.restype = wintypes.HANDLE
_OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

_ReadProcessMemory = kernel32.ReadProcessMemory
_ReadProcessMemory.restype = wintypes.BOOL
_ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

_WriteProcessMemory = kernel32.WriteProcessMemory
_WriteProcessMemory.restype = wintypes.BOOL
_WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

_VirtualProtectEx = kernel32.VirtualProtectEx
_VirtualProtectEx.restype = wintypes.BOOL
_VirtualProtectEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

_VirtualAllocEx = kernel32.VirtualAllocEx
_VirtualAllocEx.restype = wintypes.LPVOID
_VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                             wintypes.DWORD, wintypes.DWORD]

_CloseHandle = kernel32.CloseHandle
_CloseHandle.restype = wintypes.BOOL
_CloseHandle.argtypes = [wintypes.HANDLE]

_CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
_CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

# user32
_FindWindowW = user32.FindWindowW
_FindWindowW.restype = wintypes.HWND
_FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

_GetWindowRect = user32.GetWindowRect
_GetWindowRect.restype = wintypes.BOOL
_GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]

_GetWindowLongW = user32.GetWindowLongW
_GetWindowLongW.restype = ctypes.c_long
_GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]

_SetWindowLongW = user32.SetWindowLongW
_SetWindowLongW.restype = ctypes.c_long
_SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

_SetLayeredWindowAttributes = user32.SetLayeredWindowAttributes
_SetLayeredWindowAttributes.restype = wintypes.BOOL
_SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF,
                                         wintypes.BYTE, wintypes.DWORD]

_GetDC = user32.GetDC
_GetDC.restype = wintypes.HDC
_GetDC.argtypes = [wintypes.HWND]

_ReleaseDC = user32.ReleaseDC
_ReleaseDC.restype = ctypes.c_int
_ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

# gdi32
_CreateCompatibleDC = gdi32.CreateCompatibleDC
_CreateCompatibleDC.restype = wintypes.HDC
_CreateCompatibleDC.argtypes = [wintypes.HDC]

_CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
_CreateCompatibleBitmap.restype = wintypes.HBITMAP
_CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

_SelectObject = gdi32.SelectObject
_SelectObject.restype = wintypes.HGDIOBJ
_SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]

_DeleteObject = gdi32.DeleteObject
_DeleteObject.restype = wintypes.BOOL
_DeleteObject.argtypes = [wintypes.HGDIOBJ]

_DeleteDC = gdi32.DeleteDC
_DeleteDC.restype = wintypes.BOOL
_DeleteDC.argtypes = [wintypes.HDC]

# ============================================================
# Win32 结构体
# ============================================================

class POINT(ctypes.Structure):
    _fields_ = [("X", ctypes.c_long), ("Y", ctypes.c_long)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_long), ("Top", ctypes.c_long),
                ("Right", ctypes.c_long), ("Bottom", ctypes.c_long)]

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", wintypes.WPARAM),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", wintypes.LPBYTE),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]

# ============================================================
# 常量
# ============================================================

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
SW_SHOWNOACTIVATE = 4

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# ============================================================
# 进程/模块工具
# ============================================================

def read_pm(h_proc: int, base: int, size: int) -> Tuple[bytes, int]:
    buf = ctypes.create_string_buffer(size)
    nr = ctypes.c_size_t(0)
    ok = _ReadProcessMemory(h_proc, ctypes.c_void_p(base), buf, size, ctypes.byref(nr))
    if not ok:
        return b'', 0
    return buf.raw[:nr.value], nr.value

def write_pm(h_proc: int, base: int, data: bytes) -> int:
    buf = ctypes.create_string_buffer(data)
    nw = ctypes.c_size_t(0)
    ok = _WriteProcessMemory(h_proc, ctypes.c_void_p(base), buf, len(data), ctypes.byref(nw))
    return nw.value if ok else 0

def vp_ex(h_proc: int, addr: int, size: int, newp: int) -> int:
    old = wintypes.DWORD(0)
    _VirtualProtectEx(h_proc, ctypes.c_void_p(addr), size, newp, ctypes.byref(old))
    return old.value

def write_mem16(h_proc: int, addr: int, val: int):
    old = vp_ex(h_proc, addr, 2, PAGE_EXECUTE_READWRITE)
    write_pm(h_proc, addr, i16b(val))
    vp_ex(h_proc, addr, 2, old)

def replace_addr_in_bytes(data: bytearray, old_addr: int, new_addr: int):
    """替换字节数组中所有 4 字节 LE 地址"""
    old_le = i32b(old_addr)
    new_le = i32b(new_addr)
    pos = 0
    end = len(data) - 4
    first = old_le[0:1]
    while pos <= end:
        pos = data.find(first, pos)
        if pos == -1 or pos > end:
            break
        if data[pos:pos+4] == old_le:
            data[pos:pos+4] = new_le
            pos += 4
        else:
            pos += 1

def get_child_processes(parent_pid: int) -> List[PROCESSENTRY32]:
    results = []
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return results
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            try:
                if pe.th32ParentProcessID == parent_pid:
                    results.append(pe)
            except Exception:
                pass
            nxt = PROCESSENTRY32()
            nxt.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if not kernel32.Process32Next(snap, ctypes.byref(nxt)):
                break
            pe = nxt
    _CloseHandle(snap)
    return results

def get_module_base(pid: int) -> int:
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return 0
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)
    result = 0
    if kernel32.Module32First(snap, ctypes.byref(me)):
        result = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0
    _CloseHandle(snap)
    return result

def get_module_size(pid: int) -> int:
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return 0
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)
    result = 0
    if kernel32.Module32First(snap, ctypes.byref(me)):
        result = me.modBaseSize
    _CloseHandle(snap)
    return result

def get_decompressed_size(path: str) -> int:
    if not os.path.isfile(path):
        return -1
    try:
        with open(path, 'rb') as f:
            h = f.read(4)
        return b2i32(h) if len(h) >= 4 else -1
    except Exception:
        return -1

def find_window(class_name: str | None, title: str | None) -> int:
    cn = class_name if class_name else None
    tn = title if title else None
    hwnd = _FindWindowW(cn, tn)
    return ctypes.cast(hwnd, ctypes.c_void_p).value or 0

def get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    r = RECT()
    if _GetWindowRect(hwnd, ctypes.byref(r)):
        return r.Left, r.Top, r.Right, r.Bottom
    return 0, 0, 0, 0
