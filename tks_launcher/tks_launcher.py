r"""
TKS Launcher - 自动运行时内存补丁启动器 (Python版)

本启动器针对 TKS.exe 游戏进程进行运行时内存修补，突破以下硬编码限制:

[补丁一] 入队数量限制 (sub_40DA00 / sub_40E65C)
  原始限制: 队伍最多容纳 30 人 (cmp 0x1E, jg/jle)
  修补效果: 扩展为最多 200 人 (cmp 0xC8, ja/jbe), 同时将有符号比较改为无符号比较

[补丁二] 战场角色形象 (AwkSprite PATH1/PATH2 + cave)
  原始问题: 新角色 (idx>=36) 战场形象从 WORD[260] 自定义字段读取, 但默认回退逻辑
           用 +12 偏移导致超出精灵表范围, 显示错乱
  修补效果: PATH2 偏移改为 +0; PATH1 通过动态 cave 检查 WORD[260], 非零时使用自定义值

[补丁三] 队伍头像显示 (PortraitCave1 / PortraitCave2)
  原始问题: 头像计算公式固定为 portrait_idx + 0xD3, 新角色无自定义头像时显示错误
  修补效果: 通过动态 cave 检查 WORD[261], 非零时直接使用该值作为 GRP 帧索引,
           否则回退到原始 add 0xD3 逻辑

[补丁四] 战斗经验回写 (sub_43BF20)
  原始问题: 战斗结束回写函数用 movsx 读取 byte_9DF888 (参战角色索引), 当角色索引
           >= 128 时, 符号扩展为负数, 与 word_75688C (队伍索引) 比较永远不等,
           导致新角色经验/等级不被写回 WarPC 缓冲区
  修补效果: 将 movsx 改为 movzx (无符号扩展), 使索引 128~255 的角色正确回写

[补丁五] WarPC 缓冲区动态扩展 (突破 143 角色限制)
  原始问题: 游戏在 BSS 段预分配 143*1054=150722 字节 WarPC 缓冲区 (word_757F08),
           代码中 29 处引用基址 0x757F08, 5 处引用大小 150722, 无法容纳更多角色
  修补效果: 动态分配新缓冲区 (VirtualAllocEx), 写入完整 WarPC 数据, 修补所有代码
           引用 (基址 + 字段级偏移 + 大小常量) 指向新缓冲区

[补丁六] 存档/读档缓冲区扩展 (配合补丁五)
  原始问题: sub_410ED4 (存档) 和 sub_41103C (读档) 中硬编码 159922 字节缓冲区
           (= 3432 队伍/金币 + 5768 状态 + 150722 WarPC), 当 WarPC 扩展后,
           写入超出缓冲区, 栈上队伍数组/金币/地图等数据被破坏
  修补效果: 扫描代码段中所有 159922 常量, 改为 9200+newSize

[补丁七] .dat 文件大小常量修补 (TKMat / TKItem / TKSkill / TKShop / TKKon)
  原始问题: sub_4173F8 和 sub_412688 中硬编码各 .dat 文件大小, 若文件被扩展,
           sub_45343C 的大小检查失败, 导致数据加载被跳过
  修补效果: 启动前检测各 .dat 文件实际大小, 若超过原始值则创建截断版本;
           运行时扫描代码段中原始大小常量并替换为实际值

[补丁八] 新角色数据备份与旧存档兼容
  原始问题: 加载旧存档 (扩展前保存) 时, sub_41103C 中已修补为 newSize 的 memcpy
           会越过解压数据末尾读取栈上垃圾, 覆盖新角色 WarPC 槽位
  修补效果: 分配独立备份缓冲区存储新角色区段数据; 存档加载后由备份恢复新角色默认值
           新存档 (扩展后保存) 不受影响 — Frame 2 已包含完整数据

[补丁九] 索引文件截断警告
  原始问题: sub_41CE10 写入存档索引时用 char* 逐字节写入队伍 ID,
           角色 ID >= 256 时高字节截断, 存档列表显示异常
  修补效果: 检测角色 ID 范围并输出警告

[补丁十] 存档目录与索引文件健康检查 (修复"6个相同主角头像"显示异常)
  原始问题: 当 save\ 目录不存在或 sub_41CE10 写入流程失败时, 索引文件
           (save\N.sav, 28字节) 可能被遗留为 0 字节空文件。再次进入读档
           界面时, sub_41B1A8 成功打开 0 字节文件, ReadFile 不修改 buffer,
           buffer 保留 BSS 初始 0 值, 渲染函数 sub_41AB94 把全 0 解释为:
             - 6 个角色 0 头像 (主角头像 × 6)
             - Lv 0 × 6
             - 时间戳 0 → 1970/01/01 08:00:00 (UTC+8)
             - 场景 0 → "大地图"
  修补效果: 启动游戏前 (1) 创建 save\ 子目录 (若不存在);
           (2) 扫描 save\*.sav 删除 0 字节损坏文件 → 让游戏读档时
               正确显示"空槽位", 用户可重新存档生成有效文件。

[补丁十一] WarPC 缓冲区前预留 GUARD 区 (修复索引文件被截断问题)
  原始问题: sub_41CE10 写入存档索引时, 需读取 6 个队员的等级
           (word_757F0C[527 * *v6])。当队员 ID = -1 (空槽位) 时, 计算
           地址 = newBuf+4-1054 = newBuf-1050。启动器重定向后 newBuf 之前
           是未分配内存, 访问触发页错误 → sub_41DAC4 的 SEH 截断写入
           流 → 索引文件 (save\N.sav) 被截断为 14 或 20 字节 (预期 28)
           → 读档界面显示"6 个相同主角头像 + Lv0 + 70年初一"异常。
  修补效果: 在 newBuf 前预留 64 KB GUARD 区 (常量 GUARD_SIZE), 让负偏移
           访问落在合法已分配区内 (默认填 0)。sub_41DAC4 能完整读取
           并写入文件, 索引写满 28 字节。同时对 sub_40DA00/sub_40E88C/
           sub_417F84/sub_41A080/sub_43CA64 中的同类负偏移访问也一并修复。

[补丁十二] sub_4C33FC "已打开"检查修复 (修复读档列表全 0 问题)
  原始问题: sub_41B1A8 循环 9 次復用同一个 v24 文件结构, sub_4C33FC 入口
           检查 "if (a1+12) return 0" 在第 1 次循环后拒绝后续打开。
           但 sub_41C984 关闭流后 v24+12 未被清零 → 第 2..9 次循环全部返回 0
           → 读取失败 → buffer 保留 BSS 初始 0 值 → sub_41AB94 渲染出
           "6 个主角头像 + Lv0 + 70/01/01 + 大地图"异常 (仅槽位 1 正常)。
  修补效果: 扫描 sub_4C33FC 入口前 32 字节 "cmp byte [reg+0Ch], 0" + "je/jne"
           指令，将 je short 改为 jmp short 或将 jne short 改为 NOP NOP,
           让 sub_4C33FC 总是跳到 continue 重新打开文件。

[补丁十三] sub_41C120 stream error 检查修复 (修复中间空槽位后的读取失败)
  原始问题: 补丁十二生效后, 若存在中间空槽位 (如 slot 4-6 不存在),
           sub_41B1A8 中 sub_4C352C 失败进入 if (!v1) 分支 "stream+8 |= 4"
           设置 EOF 错误标志。之后槽位 (slot 7-9) 即使文件存在,
           sub_41BF48/sub_41C2B8 调用 sub_41C120 检查发现错误标志返回 false
           → 跳过读取 → buffer 保留 0 → 同样渲染"6 个主角头像"异常。
  修补效果: 将 sub_41C120 入口 "cmp dword [reg+8], 0" 改为同长的
           "and dword [reg+8], 0" (83 7X 08 00 → 83 6X 08 00),
           这样每次检查前都强制清零 stream+8 错误标志,
           后续 je/jne 依然按 ZF=1 走正确分支, slot 7-9 能重新读取。

[补丁十四] 存档界面新角色队伍头像显示修复
  原始问题: sub_41AB94 渲染存档列表队伍头像时:
             sub_4544EC(..., *(char *)(...) + 211, ...);
           二重问题: 一是 signed char ID 在 ID >= 128 时被 sign-extend 为负数
           (如 ID=143 → (char)=-113, +211=98, 帧位错位); 二是新角色 (143-145)
           应当使用 WarPC 中的 WORD[261] 作为自定义头像帧, 不是 ID+211。
  修补效果: 扫描 sub_41AB94 函数体内所有 "add eax, 0xD3" (5字节 05 D3 00 00 00)
           指令, 替换为 call 到 ArchivePortraitCave (动态分配 44 字节)。
           cave 内部: (1) movzx 将 signed ID 转为 unsigned (修复 sign-extend);
           (2) 读取 WarPC[ID].WORD[261]; (3) 非零使用 WORD[261] 作 frame,
           否则 fallback 到 unsigned ID + 211。与队伍头像 cave 逻辑一致。

[补丁十五] sub_4189BC 可装备技能列表扫描上限修正 (修复新角色技能列表 "啊！")
  原始问题: sub_4189BC 构建"可装备技能列表"时按 v12 < 350 扫描全部 350 条
           TKSkill 记录, 但有效记录只有 344 (idx 0~343), 末尾 idx 344~349
           是空记录 (name_id=0, type=0)。这本来对原 143 个角色无影响, 因为
           它们的 WarPC.skill_learn[344..349] = 0 (在 [10,40) 区间外)。
           **但 skill_learn 字节范围 byte[176..519] 总共 344 个字节,
             sub_4189BC 访问 skill_learn[v12] 即 byte[176+v12], 当 v12 ∈
             [344, 349] 时访问 byte[520..525] = WarPC field[260..262]**, 这正是
           补丁二/补丁三新角色的 awk_sprite_id 和 portrait_menu_id 字段!
           新角色 (143/144/145) 一旦设置自定义战场形象或队伍头像, 其值 byte
           若落在 [20, 39] 区间 ("20-组技能学会" 或 "30-子技能学会" 范围),
           就会被 sub_4189BC 误判为已学会 TKSkill[344..349], 加入装备列表 →
           sub_418C90 调用 sub_4067E8(0) 查 TKT 找不到 → 兜底返回 TKT 字符串
           首条 "啊！" → 列表中显示 "啊！" 字样。
  修补效果: 将 sub_4189BC 中两处 "cmp word [ebp-04], 0x015E" (66 81 7D FC 5E 01)
           的立即数 0x015E (=350) 改为 0x0158 (=344), 让扫描严格止于 idx 343,
           从此 byte[520+] 永远不被视为 skill_learn, 与 WarPC field[260+]
           的字段语义不再冲突。
           位置: RVA 0x18BB5 (主循环) + RVA 0x18C3F (第二段翻页判定), 各改 1 字节
                 5E → 58。

[补丁十六] 历史文本 ID 自定义 (sub_41A080)
  原始问题: 角色界面「历史」标签页的文本 ID 由硬编码公式计算:
            TKT_ID = word_75688C[char_idx] + 9050
            新角色 (143+) 无法自定义历史文本 ID, 只能使用公式推导值
            如角色#143 颜良的历史 ID = 9050+143 = 9193
  修补效果: 通过动态 cave 检查 WarPC[char_idx].WORD[262] (offset 0x20C=524),
            非零时直接使用该值作为 TKT ID, 否则回退到原公式 +9050。
            与 warpc_editor.py v1.6 的 history_text_id 字段配合使用。
            Hook 位置: RVA 0x1A749 (sub_41A080 中 add edx, 0x235A 指令)

[补丁十七] 金钱上限扩展 (30000→65535) + 存档界面显示修复
  原始问题: 游戏中金钱上限硬编码为 30000 (0x7530), 存储在 word_756882
            多处代码检查 `if (30000 - word_756882 >= amount)` 或
            `word_756882 = 30000` 限制金钱不超过 30000
            另外, 存档界面显示金钱时使用 signed short (__int16),
            当金钱 >= 32768 时会被解释为负数 (如 65500 → -36)
  修补效果: (1) 扫描代码段中所有 30000 (0x7530) 的立即数引用, 替换为
                65535 (0xFFFF), 使金钱上限扩展为 16 位最大值
            (2) 修复 sub_41AB94 中 movsx→movzx, 确保金钱显示为无符号值
            涉及函数: sub_40CE30 (金钱添加), sub_411E84 (秘籍),
            sub_424FE4 (购买检查), sub_43CA64 (战斗奖励),
            sub_41AB94 (存档界面显示)

用法: 把 tks_launcher.py 和 tks_patches.json 放到游戏目录，运行即可
      python tks_launcher.py [--exe TKS.exe] [--wait 30] [--minimal] [--no-cave] [--only-portrait] [--only-awk] [--help]
"""

import os
import sys
import json
import struct
import time
import ctypes
from ctypes import wintypes
import threading
import tkinter as tk
from typing import List, Dict, Tuple, Optional, Any

# ============================================================
# 辅助函数: C# BitConverter 等价物
# ============================================================

def _i32b(val: int) -> bytes:
    """int→4字节 LE (等价 BitConverter.GetBytes(int))"""
    return struct.pack('<i', val)

def _i16b(val: int) -> bytes:
    """int→2字节 LE (等价 BitConverter.GetBytes(short))"""
    return struct.pack('<h', val)

def _b2i32(data: bytes, off: int = 0) -> int:
    """bytes→int32 LE (等价 BitConverter.ToInt32)"""
    return struct.unpack_from('<i', data, off)[0]

def _b2i16(data: bytes, off: int = 0) -> int:
    """bytes→int16 LE (等价 BitConverter.ToInt16)"""
    return struct.unpack_from('<h', data, off)[0]

def _b2u16(data: bytes, off: int = 0) -> int:
    """bytes→uint16 LE"""
    return struct.unpack_from('<H', data, off)[0]

def _b2u32(data: bytes, off: int = 0) -> int:
    """bytes→uint32 LE"""
    return struct.unpack_from('<I', data, off)[0]

def _bhex(data: bytes, off: int = 0, length: int = -1) -> str:
    """字节转十六进制字符串 (等价 BitConverter.ToString), 格式: 'AB-CD-EF'"""
    if length < 0:
        length = len(data) - off
    return '-'.join(f'{b:02X}' for b in data[off:off + length])

# ============================================================
# Win32 API ctypes 绑定
# ============================================================

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# kernel32 函数签名
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

# user32 函数签名
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

# gdi32 函数签名
_GetDC = user32.GetDC
_GetDC.restype = wintypes.HDC
_GetDC.argtypes = [wintypes.HWND]

_ReleaseDC = user32.ReleaseDC
_ReleaseDC.restype = ctypes.c_int
_ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

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
# Win32 结构体定义
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
        ("th32ProcessID", wintypes.DWORD),         ("th32DefaultHeapID", wintypes.WPARAM),
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

# WarPC 常量
WARPC_BASE = 0x757F08          # BSS 中 WarPC 缓冲区基址 (word_757F08)
WARPC_REC_SIZE = 1054           # 每个角色记录 1054 字节
WARPC_ORIG_COUNT = 143          # 原始角色数量
WARPC_ORIG_SIZE = 150722        # = 143 * 1054 = 0x24CE2
WARPC_TOTAL_ORIG_SIZE = 159922  # = 9200 + 150722 = 0x270D2

TKMAT_ORIG_SIZE   = 2304000   # TKMat.dat
TKITEM_ORIG_SIZE  = 38400     # TKItem.dat
TKSKILL_ORIG_SIZE = 32900     # TKSkill.dat
TKSHOP_ORIG_SIZE  = 1920      # TKShop.dat
TKKON_ORIG_SIZE   = 26000     # TKKon.dat

DATA_FILE_ORIG_SIZES = {
    "TKMat.dat": TKMAT_ORIG_SIZE, "TKItem.dat": TKITEM_ORIG_SIZE,
    "TKSkill.dat": TKSKILL_ORIG_SIZE, "TKShop.dat": TKSHOP_ORIG_SIZE,
    "TKKon.dat": TKKON_ORIG_SIZE,
}

LOG_PATH = "tks_launcher.log"
CONFIG_PATH = "tks_patches.json"

# ============================================================
# 日志系统 — 同时写控制台和 tks_launcher.log
# ============================================================

_log_writer = None
_log_lock = threading.Lock()

def log_init():
    global _log_writer
    try:
        _log_writer = open(LOG_PATH, 'w', encoding='utf-8')
        _log_writer.write(f"=== TKS Launcher 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _log_writer.flush()
    except Exception:
        _log_writer = None

def log_close():
    global _log_writer
    with _log_lock:
        if _log_writer:
            try:
                _log_writer.flush()
                _log_writer.close()
            except Exception:
                pass
            _log_writer = None

def log(msg: str):
    print(msg)
    with _log_lock:
        if _log_writer:
            try:
                _log_writer.write(msg + '\n')
                _log_writer.flush()
            except Exception:
                pass

def log_file(msg: str):
    with _log_lock:
        if _log_writer:
            try:
                _log_writer.write(msg + '\n')
            except Exception:
                pass

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
    write_pm(h_proc, addr, _i16b(val))
    vp_ex(h_proc, addr, 2, old)

def replace_addr_in_bytes(data: bytearray, old_addr: int, new_addr: int):
    """替换字节数组中所有 4 字节 LE 地址(优化版)"""
    old_le = _i32b(old_addr)
    new_le = _i32b(new_addr)
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
        return _b2i32(h) if len(h) >= 4 else -1
    except Exception:
        return -1

# ============================================================
# 模式扫描引擎
# ============================================================

def parse_pattern(hex_str: str) -> Tuple[bytes, List[bool]]:
    parts = hex_str.split()
    pat = bytearray(len(parts))
    wc = [False] * len(parts)
    for i, p in enumerate(parts):
        if p in ('**', '??'):
            pat[i] = 0
            wc[i] = True
        else:
            pat[i] = int(p, 16)
    return bytes(pat), wc

def pattern_scan(data: bytes, pattern: bytes, wildcard: List[bool]) -> List[int]:
    """模式扫描(优化版): 用 bytes.find 定位首个非通配字节, 再验证完整模式"""
    results = []
    if not pattern or len(data) < len(pattern):
        return results
    pl = len(pattern)
    end = len(data) - pl
    # 找第一个非通配符字节作为锚点
    anchor_idx = -1
    for j in range(pl):
        if not wildcard[j]:
            anchor_idx = j
            break
    if anchor_idx < 0:
        # 全通配符 → 返回所有可能位置(极少发生)
        return list(range(end + 1))
    anchor_byte = pattern[anchor_idx:anchor_idx + 1]
    pos = 0
    while pos <= end:
        pos = data.find(anchor_byte, pos)
        if pos == -1 or pos > end:
            break
        start = pos - anchor_idx
        if start < 0:
            pos += 1
            continue
        # 验证完整模式
        match = True
        for j in range(pl):
            if not wildcard[j] and data[start + j] != pattern[j]:
                match = False
                break
        if match:
            results.append(start)
            pos = start + pl  # 跳过已匹配区域
        else:
            pos += 1
    return results

def value_scan(data: bytes, value: int) -> List[int]:
    """在字节数组中扫描指定 4 字节 LE 值(优化版: bytes.find + slice compare)"""
    results = []
    target = _i32b(value)
    pos = 0
    end = len(data) - 4
    # 用 bytes.find 快速定位首个字节，再验证完整 4 字节
    first = target[0:1]
    while pos <= end:
        pos = data.find(first, pos)
        if pos == -1 or pos > end:
            break
        if data[pos:pos + 4] == target:
            results.append(pos)
            pos += 4
        else:
            pos += 1
    return results

def discover_warpc_base(code_buf: bytes, code_start_addr: int, fallback: int) -> int:
    """
    自动发现 WarPC BSS 基址
    原理: 扫描代码中 150722 (0x24CE2) 的出现, 回溯找附近 BSS 地址
    """
    log("\n--- WarPC BSS 基址自动发现 ---")
    size_hits = value_scan(code_buf, WARPC_ORIG_SIZE)
    log(f"  扫描 150722 (0x{WARPC_ORIG_SIZE:X}): 找到 {len(size_hits)} 处")
    for off in size_hits:
        log(f"    偏移 0x{off:X} (abs 0x{code_start_addr + off:08X})")

    if not size_hits:
        log(f"  [WARN] 未找到 150722, 使用 fallback 0x{fallback:X}")
        return fallback

    candidates: Dict[int, int] = {}
    for off in size_hits:
        for i in range(max(0, off - 24), min(len(code_buf) - 4, off + 8) + 1):
            val = _b2i32(code_buf, i)
            if 0x700000 <= val < 0x800000 and (val & 3) == 0 and val != WARPC_ORIG_SIZE:
                candidates[val] = candidates.get(val, 0) + 1

    best_val, best_cnt = fallback, 0
    for v, c in candidates.items():
        log(f"  候选 0x{v:08X}: 出现 {c} 次")
        if c > best_cnt:
            best_val, best_cnt = v, c

    if best_cnt > 0:
        log(f"  发现 WarPC 基址: 0x{best_val:08X} (出现 {best_cnt} 次)")
    else:
        log(f"  [WARN] 未找到候选, 使用 fallback 0x{fallback:X}")
    return best_val

# ============================================================
# JSON 配置解析
# ============================================================

class PatchDef:
    __slots__ = ('type', 'id', 'desc', 'pattern', 'value_offset', 'expect_value',
                 'new_value_expr', 'replace', 'expect_count', 'cave_template',
                 'cave_offset', 'hook_size', 'hook_verify_pattern', 'hook_pattern',
                 'hook_expect_count', '_pre_scanned_hits', 'value_scan')
    def __init__(self):
        self.type: str = ""
        self.id: str = ""
        self.desc: str = ""
        self.pattern: str = ""
        self.value_offset: int = 0
        self.expect_value: int = 0
        self.new_value_expr: str = ""
        self.replace: Dict[str, int] = {}
        self.expect_count: int = 0
        self.cave_template: str = ""
        self.cave_offset: int = 0
        self.hook_size: int = 0
        self.hook_verify_pattern: str = ""
        self.hook_pattern: str = ""
        self.hook_expect_count: int = 0
        self._pre_scanned_hits: List[int] = []
        self.value_scan: bool = False

class PatchConfig:
    def __init__(self):
        self.variables: Dict[str, int] = {}
        self.patches: List[PatchDef] = []

def load_config(path: str) -> Optional[PatchConfig]:
    if not os.path.isfile(path):
        log(f"  [WARN] 配置文件 {path} 不存在, 使用内置默认配置")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 JSON 配置失败: {e}")
        return None

    config = PatchConfig()
    if "variables" in raw:
        for k, v in raw["variables"].items():
            if isinstance(v, dict):
                # 嵌套对象如 {"auto_discover": true, "fallback": "0x757F08"}
                # 仅提取 fallback 值 (auto_discover 由 DiscoverWarpcBase 处理)
                if "fallback" in v:
                    fbv = v["fallback"]
                    if isinstance(fbv, str) and fbv.lower().startswith("0x"):
                        config.variables[k] = int(fbv, 16)
                    else:
                        config.variables[k] = int(fbv)
                # 否则跳过 (未知的对象结构)
            elif isinstance(v, str):
                if v.lower().startswith("0x"):
                    config.variables[k] = int(v, 16)
                else:
                    config.variables[k] = int(v)
            elif isinstance(v, bool):
                config.variables[k] = 1 if v else 0
            else:
                config.variables[k] = int(v)

    # 辅助: 解析可能是 hex 字符串或整数的值
    def _parse_maybe_hex(val):
        if isinstance(val, str):
            if val.lower().startswith("0x"):
                return int(val, 16)
            return int(val)
        return int(val)

    def _parse_replace_val(val):
        """replace 值始终是 hex 字符串 (如 'C8', 'B6')，或已经是整数"""
        if isinstance(val, str):
            return int(val, 16)
        return int(val)

    if "patches" in raw:
        for pr in raw["patches"]:
            d = PatchDef()
            d.type = pr.get("type", "")
            d.id = pr.get("id", "")
            d.desc = pr.get("desc", "")
            d.pattern = pr.get("pattern", "")
            d.value_offset = pr.get("value_offset", 0)
            d.expect_value = _parse_maybe_hex(pr.get("expect_value", 0))
            d.new_value_expr = str(pr.get("new_value", ""))
            d.expect_count = pr.get("expect_count", 0)
            d.hook_size = pr.get("hook_size", 0)
            d.cave_offset = pr.get("cave_offset", 0)
            d.cave_template = pr.get("cave_template", "")
            d.hook_verify_pattern = pr.get("hook_verify", "")
            d.hook_pattern = pr.get("hook_pattern", "")
            d.hook_expect_count = pr.get("hook_expect_count", 0)
            d.value_scan = pr.get("value_scan", False)
            if "replace" in pr:
                for rk, rv in pr["replace"].items():
                    d.replace[rk] = _parse_replace_val(rv)
            config.patches.append(d)

    log(f"  已加载配置: {len(config.variables)} 个变量, {len(config.patches)} 个补丁")
    return config

def resolve_var(expr: str, variables: Dict[str, int], strict: bool = False) -> Optional[int]:
    """解析变量引用。strict=True 时，未定义变量返回 None（等价 C# long.MinValue 哨兵）"""
    if expr is None:
        return 0
    if expr.startswith('{') and expr.endswith('}'):
        vn = expr[1:-1]
        if vn in variables:
            return variables[vn]
        log(f"  [WARN] 未定义变量: {vn}")
        return None if strict else 0
    if expr.lower().startswith('0x'):
        return int(expr[2:], 16)
    return int(expr)

# ============================================================
# LZSS 压缩/解压 — 与游戏 sub_452B14 配对
# ============================================================

def lzss_decompress(data: bytes) -> bytes:
    """最小化 LZSS 解压 (匹配 sub_452B14)"""
    if len(data) < 12:
        return b''
    total_size = _b2i32(data, 0)
    block_size = _b2i32(data, 4)
    window = bytearray([0x20] * 4096)
    wp = 4078
    output = bytearray(total_size)
    flags, pos, bc, out_pos = 0, 12, 4, 0

    while bc < block_size and out_pos < total_size:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1; bc += 1
        if (flags & 1) != 0:
            if pos >= len(data):
                break
            b = data[pos]; pos += 1; bc += 1
            output[out_pos] = b; out_pos += 1
            window[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            b1, b2 = data[pos], data[pos+1]
            pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1
            rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                if out_pos >= total_size:
                    break
                b = window[(j + ro) & 0xFFF]
                output[out_pos] = b; out_pos += 1
                window[wp] = b; wp = (wp + 1) & 0xFFF

    return bytes(output[:total_size])

def lzss_compress(data: bytes) -> bytes:
    """LZSS 压缩(优化版: 哈希表 O(n) — 与游戏 sub_452B14 配对, 用于截断文件生成)"""
    sl = len(data)
    hf: List[int] = []
    td: List[int] = []
    pos = 0

    # 哈希表: 3 字节键 → 最近出现位置 (在 data 坐标中)
    ht: Dict[int, int] = {}

    while pos < sl:
        ms = min(18, sl - pos)
        blen, boff = 0, 0

        # 哈希表快速匹配 (替代原始 O(n²) 反向扫描)
        if ms >= 3 and pos >= 3:
            hk = (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
            prev = ht.get(hk, -1)
            if prev >= 0 and pos - prev <= 4096:
                # 找到候选, 向前扩展找最长匹配
                ml = 0
                while (ml < ms and data[prev + ml] == data[pos + ml]):
                    ml += 1
                if ml >= 3:
                    blen = ml
                    boff = prev  # data 坐标

        # 更新哈希表 (当前位置)
        if pos + 2 < sl:
            hk = (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
            ht[hk] = pos

        if blen >= 3:
            # boff 是 data 坐标, 转为 flat 坐标 (data 在 flat 中偏移 4096)
            flat_off = boff + 4096
            bo = (flat_off - 18) & 0xFFF
            hf.append(0)
            td.append(bo & 0xFF)
            td.append(((bo >> 4) & 0xF0) | ((blen - 3) & 0x0F))
            # 更新匹配范围内每个位置的哈希
            for j in range(1, blen):
                if pos + j + 2 < sl:
                    hk = (data[pos + j] << 16) | (data[pos + j + 1] << 8) | data[pos + j + 2]
                    ht[hk] = pos + j
            pos += blen
        else:
            hf.append(1)
            td.append(data[pos])
            pos += 1

    stream: List[int] = []
    hi, tp = 0, 0
    while hi < len(hf):
        fb, be = 0, min(hi + 8, len(hf))
        for i in range(hi, be):
            if hf[i]: fb |= (1 << (i - hi))
        stream.append(fb)
        for i in range(hi, be):
            if hf[i]:
                stream.append(td[tp]); tp += 1
            else:
                stream.append(td[tp]); stream.append(td[tp+1]); tp += 2
        hi = be

    lzss_block = bytearray(4 + len(stream))
    lzss_block[0:4] = _i32b(sl)
    lzss_block[4:] = bytes(stream)

    result = bytearray(8 + len(lzss_block))
    result[0:4] = _i32b(sl)
    result[4:8] = _i32b(len(lzss_block))
    result[8:] = lzss_block

    test_dec = lzss_decompress(bytes(result))
    if len(test_dec) != sl:
        raise IOError(f"LZSS 压缩回写验证失败: 长�? {len(test_dec)} != {sl}")
    for i in range(sl):
        if test_dec[i] != data[i]:
            raise IOError(f"LZSS 压缩回写验证失败: 偏移 {i} 不匹配")

    return bytes(result)

# ============================================================
# 静态补丁定义
# ============================================================

class Patch:
    def __init__(self, rva: int, data: bytes, desc: str):
        self.rva = rva; self.data = data; self.desc = desc

STATIC_PATCHES = [
    Patch(0xDA15, bytes([0xC8, 0x87]),
          "TeamMember: cmp 0x1E->0xC8, jg->ja (sub_40DA00)"),
    Patch(0xE6C1, bytes([0xC8, 0x76]),
          "CheckTeam: cmp 0x1E->0xC8, jle->jbe (sub_40E65C)"),
    Patch(0x31165, bytes([0x00]),
          "AwkSprite PATH2: +12->+0"),
    # [补丁四] 战斗经验回写 (sub_43BF20)
    # 修补: movsx (0F BE) -> movzx (0F B6), 无符号扩展
    Patch(0x3BF5C, bytes([0xB6]),
          "BattleWriteback: movsx->movzx byte_9DF888 (fix idx>=128 exp writeback)"),
    # [补丁十五] sub_4189BC 扫描上限 350->344
    Patch(0x18BB5, bytes([0x58]),
          "SkillList scan upper bound 350->344 (sub_4189BC main loop)"),
    Patch(0x18C3F, bytes([0x58]),
          "SkillList scan upper bound 350->344 (sub_4189BC page check)"),
]

# ============================================================
# Cave 模板 (x86 机器码, 原样复制自 C#)
# ============================================================

# [补丁二] 战场角色形象 PATH1 动态 Cave (51 字节)
CAVE_TEMPLATE = bytes([
    0x50, 0x51, 0x0F, 0xBF, 0x45, 0xFA, 0x66, 0x85,
    0xC0, 0x74, 0x25, 0x69, 0xC0, 0x1E, 0x04, 0x00,
    0x00, 0x05, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7,
    0x88, 0x08, 0x02, 0x00, 0x00, 0x66, 0x85, 0xC9,
    0x75, 0x04, 0x85, 0xC0, 0xEB, 0x0A, 0x83, 0xE9,
    0x06, 0x66, 0x89, 0x4D, 0xFA, 0x66, 0x85, 0xC9,
    0x59, 0x58, 0xC3,
])

# [补丁三] 队伍头像 PATH1 Cave (41 字节)
PORTRAIT_CAVE1 = bytes([
    0x50, 0x51, 0x52, 0x8B, 0xC1, 0x03, 0xC0, 0x05,
    0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x80, 0x0A,
    0x02, 0x00, 0x00, 0x66, 0x85, 0xC0, 0x75, 0x08,
    0x8B, 0x44, 0x24, 0x08, 0x66, 0x05, 0xD3, 0x00,
    0x83, 0xC4, 0x08, 0x5A, 0x87, 0x04, 0x24, 0xFF,
    0xE0,
])

# [补丁十四] 存档界面队伍头像 Cave (48 字节)
ARCHIVE_PORTRAIT_CAVE = bytes([
    0x52, 0x51, 0x0F, 0xB6, 0xC0, 0x8B, 0xC8, 0x69,
    0xC0, 0x1E, 0x04, 0x00, 0x00, 0x05, 0x08, 0x7F,
    0x75, 0x00, 0x0F, 0xB7, 0x90, 0x0A, 0x02, 0x00,
    0x00, 0x66, 0x85, 0xD2, 0x75, 0x09, 0x8B, 0xC1,
    0x05, 0xD3, 0x00, 0x00, 0x00, 0xEB, 0x02, 0x8B,
    0xC2, 0x59, 0x5A, 0x87, 0x04, 0x24, 0xFF, 0xE0,
])

# [补丁十六] 历史文本 ID Cave (38 字节)
HISTORY_TEXT_CAVE = bytes([
    0x52, 0x69, 0xD2, 0x1E, 0x04, 0x00, 0x00, 0x81,
    0xC2, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x82,
    0x0C, 0x02, 0x00, 0x00, 0x85, 0xC0, 0x75, 0x08,
    0x5A, 0x81, 0xC2, 0x5A, 0x23, 0x00, 0x00, 0xC3,
    0x8B, 0xD0, 0x83, 0xC4, 0x04, 0xC3,
])

# [补丁三] 队伍头像 PATH2 Cave (38 字节)
PORTRAIT_CAVE2 = bytes([
    0x50, 0x51, 0x03, 0xC0, 0x05, 0x08, 0x7F, 0x75,
    0x00, 0x0F, 0xB7, 0x88, 0x0A, 0x02, 0x00, 0x00,
    0x66, 0x85, 0xC9, 0x75, 0x07, 0x66, 0x81, 0xC2,
    0xD3, 0x00, 0xEB, 0x03, 0x66, 0x89, 0xCA, 0x59,
    0x58, 0x87, 0x14, 0x24, 0xFF, 0xE2,
])

# ============================================================
# Cave 模板构建
# ============================================================

def build_cave_template(name: str, warpc_base: int) -> Optional[bytes]:
    if name == "awk_sprite":
        c = bytearray(CAVE_TEMPLATE)
        replace_addr_in_bytes(c, WARPC_BASE, warpc_base)
        return bytes(c)
    elif name == "portrait1":
        c = bytearray(PORTRAIT_CAVE1)
        replace_addr_in_bytes(c, WARPC_BASE, warpc_base)
        return bytes(c)
    elif name == "portrait2":
        c = bytearray(PORTRAIT_CAVE2)
        log(f"    [DBG] p2 before: [{_bhex(c, 4, 8)}]")
        log(f"    [DBG] replacing {WARPC_BASE:X} -> {warpc_base:X}")
        replace_addr_in_bytes(c, WARPC_BASE, warpc_base)
        log(f"    [DBG] p2 after:  [{_bhex(c, 4, 8)}]")
        return bytes(c)
    elif name == "archive_portrait":
        c = bytearray(ARCHIVE_PORTRAIT_CAVE)
        replace_addr_in_bytes(c, WARPC_BASE, warpc_base)
        return bytes(c)
    elif name == "history_text":
        c = bytearray(HISTORY_TEXT_CAVE)
        replace_addr_in_bytes(c, WARPC_BASE, warpc_base)
        return bytes(c)
    return None

# ============================================================
# 全局状态
# ============================================================

_overlay = None
_overlay_thread = None
_warpc_expanded = False
_warpc_full_data = None
_warpc_new_buf = 0
_truncated_files: Dict[str, bytes] = {}
_archive_portrait_cave_addr = 0

# ============================================================
# 游戏内叠加窗口 (tkinter + Win32 layered)
# ============================================================

class OverlayForm:
    def __init__(self, game_hwnd: int):
        self.game_hwnd = game_hwnd
        self._text = "正在加载..."
        self._ok = False
        self.root = tk.Tk()
        self.root.title("")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg='black')
        self.w, self.h = 280, 40
        self.root.geometry(f"{self.w}x{self.h}")
        hwnd = int(self.root.frame(), 16)
        ex = _GetWindowLongW(hwnd, GWL_EXSTYLE)
        _SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        _SetLayeredWindowAttributes(hwnd, 0x000000, 200, 2)
        self.label = tk.Label(self.root, text=self._text,
                              font=("Microsoft YaHei", 11, "bold"),
                              fg="white", bg="black", anchor="e", padx=18)
        self.label.pack(fill=tk.BOTH, expand=True)
        self._update_pos()
        self._tick()

    def _tick(self):
        self._update_pos()
        self.root.after(100, self._tick)

    def _update_pos(self):
        if self.game_hwnd:
            r = RECT()
            if _GetWindowRect(self.game_hwnd, ctypes.byref(r)):
                self.root.geometry(f"+{r.Right - self.w - 15}+{r.Bottom - self.h - 15}")

    def set_status(self, text: str, ok: bool = False):
        self._text = text; self._ok = ok
        self.label.config(text=text, fg="lime" if ok else "white")

    def show(self):
        self.root.deiconify()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    @property
    def is_handle_created(self):
        return self.root.winfo_exists()

def show_overlay(game_hwnd: int):
    global _overlay, _overlay_thread
    def _run():
        global _overlay
        _overlay = OverlayForm(game_hwnd)
        _overlay.show()
        _overlay.root.mainloop()
    _overlay_thread = threading.Thread(target=_run, daemon=True)
    _overlay_thread.start()
    for _ in range(40):
        if _overlay and _overlay.is_handle_created:
            break
        time.sleep(0.05)

def update_overlay(status: str, ok: bool = False):
    if _overlay and _overlay.is_handle_created:
        _overlay.root.after(0, lambda: _overlay.set_status(status, ok))

def close_overlay():
    if _overlay and _overlay.is_handle_created:
        try:
            _overlay.root.after(0, _overlay.close)
        except Exception:
            pass

# ============================================================
# 存档健康检查 + WarPC 准备
# ============================================================

def ensure_save_directory_healthy():
    r"""补丁十: 确保 save\ 目录存在并清理 0 字节损坏文件"""
    log("\n--- 存档目录健康检查 ---")
    save_dir = "save"
    if not os.path.isdir(save_dir):
        try:
            os.makedirs(save_dir, exist_ok=True)
            log("  已创建 save\\ 目录")
        except Exception as e:
            log(f"  [WARN] 创建 save\\ 失败: {e}")
            return
    else:
        log("  save\\ 目录已存在")

    del_idx, del_dat = 0, 0
    for i in range(1, 10):
        ip = os.path.join(save_dir, f"{i}.sav")
        dp = os.path.join(save_dir, f"sav.{i}")
        if os.path.isfile(ip):
            sz = os.path.getsize(ip)
            if sz == 0:
                try:
                    os.remove(ip)
                    log(f"  删除损坏的索引文件: {ip} (0 字节)")
                    del_idx += 1
                    if os.path.isfile(dp) and os.path.getsize(dp) < 16:
                        os.remove(dp)
                        log(f"  删除对应的损坏数据文件: {dp}")
                        del_dat += 1
                except Exception as e:
                    log(f"  [WARN] 删除 {ip} 失败: {e}")
            elif sz != 28:
                log(f"  [WARN] {ip} 大小异常: {sz} 字节 (预期 28)")

    if del_idx > 0 or del_dat > 0:
        log(f"  共清理 {del_idx} 个 0 字节索引文件 + {del_dat} 个损坏数据文件")
        log("  读档界面将正确显示空槽位, 请重新存档生成有效存档")
    else:
        log("  未发现损坏存档文件")

def prepare_warpc_for_game():
    """游戏启动前: 检测 .dat 文件大小, 创建截断版本"""
    global _warpc_expanded, _warpc_full_data, _truncated_files
    import shutil

    for fname in DATA_FILE_ORIG_SIZES:
        bp = fname + ".orig"
        if os.path.isfile(bp):
            shutil.copy2(bp, fname); os.remove(bp)
            log(f"  检测到上次未恢复的 {bp}, 已自动恢复")

    wp = "WarPC.dat"
    if os.path.isfile(wp):
        with open(wp, 'rb') as f:
            comp = f.read()
        dec = lzss_decompress(comp)
        cnt = len(dec) // WARPC_REC_SIZE
        if cnt > WARPC_ORIG_COUNT:
            _warpc_expanded = True; _warpc_full_data = dec
            log(f"  WarPC.dat 检测到扩展数据: {cnt} 角色 (原始 {WARPC_ORIG_COUNT})")
            tr = dec[:WARPC_ORIG_SIZE]
            tc = lzss_compress(tr)
            bp = wp + ".orig"
            if not os.path.isfile(bp):
                shutil.copy2(wp, bp)
            _truncated_files[wp] = comp
            with open(wp, 'wb') as f:
                f.write(tc)
            log(f"  已创建截断版 WarPC.dat ({WARPC_ORIG_COUNT} 角色), 备份为 .orig")

    for fname, osz in DATA_FILE_ORIG_SIZES.items():
        if fname == "WarPC.dat" or not os.path.isfile(fname):
            continue
        asz = get_decompressed_size(fname)
        if asz > osz:
            log(f"  [WARN] {fname} 解压大小 {asz} > 原始 {osz}")
            log(f"         当前将创建截断版本({osz}B)供游戏加载")
            with open(fname, 'rb') as f:
                comp = f.read()
            dec = lzss_decompress(comp)
            tr = dec[:min(len(dec), osz)]
            tc = lzss_compress(tr)
            bp = fname + ".orig"
            if not os.path.isfile(bp):
                shutil.copy2(fname, bp)
            _truncated_files[fname] = comp
            with open(fname, 'wb') as f:
                f.write(tc)
            log(f"  已创建截断版 {fname} ({osz}B), 备份为 .orig")
        elif asz >= 0:
            log(f"  {fname}: 解压大小 {asz} = 原始值, OK")

# ============================================================
# 扫描并修补 4 字节常量
# ============================================================

def scan_and_patch_const(h_proc: int, scan_start: int, scan_size: int,
                          old_val: int, new_val: int) -> Tuple[int, List[int]]:
    """扫描并修补 4 字节常量(优化版: bytes.find + slice compare)"""
    pr: List[int] = []
    ole = _i32b(old_val); nle = _i32b(new_val)
    buf, nr = read_pm(h_proc, scan_start, scan_size)
    if nr <= 0:
        return 0, []
    cnt = 0
    pos = 0
    end = min(nr, scan_size) - 4
    first = ole[0:1]
    while pos <= end:
        pos = buf.find(first, pos)
        if pos == -1 or pos > end:
            break
        if buf[pos:pos+4] == ole:
            aa = scan_start + pos
            op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
            nw = write_pm(h_proc, aa, nle)
            vp_ex(h_proc, aa, 4, op)
            if nw == 4:
                cnt += 1; pr.append(aa)
            pos += 4
        else:
            pos += 1
    return cnt, pr

def patch_data_file_sizes(h_proc: int, base_addr: int, scan_start: int, scan_size: int):
    """补丁七: 修补 .dat 文件大小常量"""
    log("\n--- 数据文件大小常量修补 ---")
    import shutil
    for fname, osz in DATA_FILE_ORIG_SIZES.items():
        asz = get_decompressed_size(fname)
        if asz <= osz:
            continue
        bp = fname + ".orig"
        if not os.path.isfile(bp):
            continue
        shutil.copy2(bp, fname); os.remove(bp)
        log(f"  已恢复原始 {fname}")
        patched, rvas = scan_and_patch_const(h_proc, scan_start, scan_size, osz, asz)
        if patched > 0:
            log(f"  [OK] {fname}: {osz} -> {asz}, 修补 {patched} 处")
            for a in rvas:
                log(f"        RVA 0x{a - base_addr:X} (abs 0x{a:08X})")
        else:
            log(f"  [WARN] {fname}: 未找到 {osz} (0x{osz:X}) 引用")

# ============================================================
# 配置驱动的补丁应用引擎
# ============================================================

def apply_patch_bytes(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       h_proc: int) -> bool:
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

def apply_patch_imm32_by_value(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                h_proc: int, vars: Dict[str, int]) -> bool:
    ov = defn.expect_value; nv = resolve_var(defn.new_value_expr, vars, strict=True)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True  # 不是失败, 仅是跳过
    hits = value_scan(bytes(code_buf), ov)
    log(f"    扫描值 {ov} (0x{ov:X}) -> 匹配 {len(hits)} 处 (预期 {defn.expect_count})")
    log(f"    替换为 {nv} (0x{nv:X})")
    if defn.expect_count > 0 and len(hits) != defn.expect_count:
        log(f"  [WARN] 匹配数 {len(hits)} != 预期 {defn.expect_count}")
    nle = _i32b(nv); ptd = 0
    for off in hits:
        aa = code_start_addr + off
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if off + 4 <= len(code_buf):
            code_buf[off:off+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    if ptd == 0 and defn.expect_count > 0:
        log(f"  [FAIL] 未找到值 {ov} (0x{ov:X})")
        return False
    return True

def apply_patch_imm32_by_pattern(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                  h_proc: int, vars: Dict[str, int]) -> bool:
    pat, wc = parse_pattern(defn.pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    模式: [{defn.pattern}] -> 匹配 {len(hits)} 处 (预期 {defn.expect_count})")
    nv = resolve_var(defn.new_value_expr, vars, strict=True); ov = defn.expect_value
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    nle = _i32b(nv); ptd = 0
    for off in hits:
        io = off + defn.value_offset
        if io + 4 <= len(code_buf):
            act = _b2i32(bytes(code_buf), io)
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
    if ptd == 0 and defn.expect_count > 0:
        log("  [FAIL] 未找到匹配模式")
        return False
    return True

def apply_cave_hook_with_hits(defn: PatchDef, hits: List[int], code_buf: bytearray,
                               code_start_addr: int, h_proc: int, cave_addr: int,
                               warpc_base: int, vars: Dict[str, int]) -> bool:
    global _archive_portrait_cave_addr
    if not hits:
        log("    [WARN] 未找到 hook 点")
        return False

    cd = build_cave_template(defn.cave_template, warpc_base)
    if cd is None:
        log(f"    [WARN] 未知 cave 模板: {defn.cave_template}")
        return False

    ct = cave_addr + defn.cave_offset
    write_pm(h_proc, ct, cd)
    if defn.cave_template == "archive_portrait":
        _archive_portrait_cave_addr = ct
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")

    ptd = 0
    for off in hits:
        ha = code_start_addr + off
        co = (ct - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(defn.hook_size)
        ci[0] = 0xE8
        ci[1:5] = _i32b(co)
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

def apply_config_patches(config: PatchConfig, code_buf: bytearray, code_start_addr: int,
                          h_proc: int, warpc_base: int, cave_addr: int,
                          minimal_mode: bool, no_cave_mode: bool,
                          only_portrait: bool, only_awk: bool) -> bool:
    all_ok = True; pidx = 0; pch: List[PatchDef] = []

    for defn in config.patches:
        pidx += 1
        tag = f"[{pidx}/{len(config.patches)}] {defn.id}"
        log(f"\n  {tag}: {defn.desc}")

        if defn.type == "patch_bytes":
            all_ok &= apply_patch_bytes(defn, code_buf, code_start_addr, h_proc)
        elif defn.type == "cave_hook":
            hp = defn.hook_pattern or defn.pattern
            hpat, hwc = parse_pattern(hp or "")
            hh = pattern_scan(bytes(code_buf), hpat, hwc)
            if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
                log(f"  [{pidx}] {defn.id}: Hook 模式匹配 {len(hh)} 处 (预期 {defn.hook_expect_count}), 跳过")
                continue
            defn._pre_scanned_hits = hh
            pch.append(defn)
        elif defn.type == "patch_imm32":
            if defn.value_scan:
                nv = resolve_var(defn.new_value_expr, config.variables, strict=True)
                if nv is None:
                    log(f"    -> 变量未定义, 跳过")
                    continue
                if defn.expect_value != 0 and nv == defn.expect_value:
                    log(f"    -> 值未变化 ({defn.expect_value}), 跳过")
                    continue
                all_ok &= apply_patch_imm32_by_value(defn, code_buf, code_start_addr, h_proc, config.variables)
            else:
                all_ok &= apply_patch_imm32_by_pattern(defn, code_buf, code_start_addr, h_proc, config.variables)
        elif defn.type == "patch_warpc_addr":
            log(f"    -> 由 WarPC 扩展流程处理 (base=0x{warpc_base:08X})")
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
            all_ok &= apply_cave_hook_with_hits(defn, defn._pre_scanned_hits, code_buf,
                                                  code_start_addr, h_proc, cave_addr,
                                                  warpc_base, config.variables)
    return all_ok

# ============================================================
# WarPC 缓冲区动态扩展 (补丁五/六/七/八/十一)
# ============================================================

def expand_warpc_buffer(child_pid: int, base_addr: int, module_size: int,
                          cave_addr: int, code_buf: bytearray, code_start_addr: int):
    global _warpc_expanded, _warpc_full_data, _warpc_new_buf
    if not _warpc_expanded or _warpc_new_buf == 0:
        return

    ns = len(_warpc_full_data)
    access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    hp = _OpenProcess(access, False, child_pid)
    if not hp:
        log("  [ERROR] 无法打开进程进行 WarPC 扩展")
        return

    diag: List[str] = []
    nb = _warpc_new_buf
    log(f"  修补代码引用: 缓冲区 0x{nb:08X}, 大小 {ns}")

    nal = _i32b(nb); nsl = _i32b(ns)
    ap, sp, fp, a0p = 0, 0, 0, 0
    ss = code_start_addr; ssz = len(code_buf)

    # WarPC 基址修补
    for off in value_scan(bytes(code_buf), WARPC_BASE):
        write_pm(hp, ss + off, nal)
        code_buf[off:off+4] = nal; ap += 1
        diag.append(f"[OK] WarPC base RVA 0x{off:X} (abs 0x{ss + off:08X})")
    log(f"  WarPC 基址 0x{WARPC_BASE:08X} 扫描: 找到 {ap} 处")

    # word_757F0C 修补
    w0c = WARPC_BASE + 4; n0c = _i32b(nb + 4)
    for off in value_scan(bytes(code_buf), w0c):
        aa = ss + off
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(hp, aa, n0c)
        vp_ex(hp, aa, 4, op)
        code_buf[off:off+4] = n0c; a0p += 1
    log(f"  word_757F0C 修补: {a0p} 处")

    # 字段基址修补(优化版): 用 bytes.find 定位 WarPC 地址范围
    # 范围 0x00757F08-0x00758326, LE 编码高两字节恒为 0x75 0x00
    rs, re = WARPC_BASE, WARPC_BASE + WARPC_REC_SIZE
    pos = 0
    end = ssz - 4
    marker = b'\x75\x00'  # WarPC 地址的高两字节 (LE)
    while pos <= end:
        pos = bytes(code_buf).find(marker, pos)
        if pos == -1 or pos > end:
            break
        # marker 在偏移 pos+2, pos+3 处, 读取完整的 4 字节地址
        read_pos = pos - 2
        if read_pos >= 0:
            v = _b2i32(bytes(code_buf), read_pos)
            if rs <= v < re:
                ofs = v - WARPC_BASE; nv = nb + ofs
                write_pm(hp, ss + read_pos, _i32b(nv))
                code_buf[read_pos:read_pos+4] = _i32b(nv); fp += 1; pos += 4
            else:
                pos += 1
        else:
            pos += 1
    log(f"  字段基址修补: {fp} 处 (范围 0x{rs:08X}-0x{re:08X})")

    # 大小常量修补
    for off in value_scan(bytes(code_buf), WARPC_ORIG_SIZE):
        aa = ss + off
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        wok = write_pm(hp, aa, nsl)
        vp_ex(hp, aa, 4, op)
        if wok == 4: sp += 1
    log(f"  WarPC 大小常量修补: {sp} 处")

    # [补丁六] 存档/读档缓冲区大小修补 (优化: 使用 value_scan 替代逐字节扫描)
    tos = WARPC_TOTAL_ORIG_SIZE; tns = 9200 + ns
    tnl = _i32b(tns)
    tp = 0
    for off in value_scan(bytes(code_buf), tos):
        aa = ss + off; rva = aa - base_addr
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        wok = write_pm(hp, aa, tnl)
        vp_ex(hp, aa, 4, op)
        if wok == 4:
            tp += 1
            log(f"  [OK] 存档缓冲区 RVA 0x{rva:X}: {tos} -> {tns}")

    # [补丁七] 其他 .dat
    patch_data_file_sizes(hp, base_addr, ss, ssz)

    # [补丁八] 新角色备份
    es = WARPC_ORIG_COUNT * WARPC_REC_SIZE; exs = ns - es
    bbp = 0
    if exs > 0:
        bpv = _VirtualAllocEx(hp, None, exs, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if bpv:
            bbp = ctypes.cast(bpv, ctypes.c_void_p).value or 0
            write_pm(hp, bbp, _warpc_full_data[es:es+exs])
            log(f"  新角色备份: 0x{bbp:08X} ({exs} 字节, 角色 {WARPC_ORIG_COUNT}-{len(_warpc_full_data)//WARPC_REC_SIZE-1})")
        else:
            log("  [WARN] 无法分配新角色备份缓冲区")

    _CloseHandle(hp)
    log(f"  已修补: {ap}个基址(08) + {a0p}个基址(0C) + {fp}个字段基址 + {sp}个大小常量")
    log(f"  扫描范围: 0x{ss:08X}-0x{ss+ssz:08X}, 新buf=0x{nb:08X}, 新size={ns}")
    if bbp:
        log(f"  备份buf=0x{bbp:08X}, 额外角色={exs//WARPC_REC_SIZE}")
    log(f"warpc_expand=1 new_buf=0x{nb:08X} new_size={ns} addr08={ap} addr0C={a0p} field={fp} size={sp} save_buf={tp} new_total_size={tns} backup_buf=0x{bbp:08X} extra_size={exs}")
    log_file("--- ExpandWarPcBuffer DIAG ---")
    log_file("\n".join(diag))

# ============================================================
# 数据注入 (WORD[260]/WORD[261])
# ============================================================

def inject_warpc_data(child_pid: int, warpc_base: int):
    global _warpc_expanded
    if _warpc_expanded:
        log("  Data inject: 已通过 ExpandWarPcBuffer 完成")
        return

    wp = "WarPC.dat"
    if not os.path.isfile(wp):
        log("  [WARN] WarPC.dat not found, skip data inject")
        return
    with open(wp, 'rb') as f:
        comp = f.read()
    dec = lzss_decompress(comp)
    if len(dec) < WARPC_ORIG_SIZE:
        log("  [WARN] WarPC.dat decompressed size mismatch")
        return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, child_pid)
    if not hp:
        return

    wc, pc = 0, 0
    cnt = min(len(dec)//WARPC_REC_SIZE, WARPC_ORIG_COUNT)
    for i in range(cnt):
        bo = i * WARPC_REC_SIZE
        w260 = _b2i16(dec, bo + 520)
        if w260:
            write_mem16(hp, warpc_base + bo + 520, w260); wc += 1
        w261 = _b2i16(dec, bo + 522)
        if w261:
            write_mem16(hp, WARPC_BASE + bo + 522, w261); pc += 1

    _CloseHandle(hp)
    log(f"  Data inject: {wc} W260, {pc} W261")
    log(f"patches=9 inject_w260={wc} w261={pc}")

# ============================================================
# [补丁十二] sub_4C33FC 入口检查修补
# ============================================================

def patch_4c33fc(cpid: int, base: int):
    """修补 sub_4C33FC '已打开'检查, 让循环复用文件结构正常工作"""
    sr = 0xC33FC
    log("\n--- [补丁十二] sub_4C33FC 入口检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 32:
        log(f"  [ERROR] 读取 sub_4C33FC@0x{av:08X} 失败"); _CloseHandle(hp); return

    log(f"  sub_4C33FC@0x{av:08X} 入口 64 字节: [{_bhex(buf, 0, min(nr,64))}]")

    co, cmr = -1, 0
    for i in range(min(nr, 32) - 4):
        if buf[i]==0x80 and (buf[i+1]&0xF8)==0x78 and buf[i+2]==0x0C and buf[i+3]==0x00:
            co, cmr = i, buf[i+1]; break

    if co < 0:
        log("  [WARN] 未找到 cmp [reg+0Ch],0 模式, 跳过"); _CloseHandle(hp); return

    log(f"  找到 cmp byte ptr [reg(modrm=0x{cmr:02X})+0Ch], 0 位于偏移 +0x{co:X}")
    bo, bo2 = buf[co+4], buf[co+5]; ba = av + co + 4

    if bo == 0x74:
        pb = bytes([0xEB, bo2]); pd = f"je short -> jmp short +0x{bo2:02X}"
    elif bo == 0x75:
        pb = bytes([0x90, 0x90]); pd = f"jne short -> NOP NOP"
    elif bo == 0x0F and bo2 == 0x84:
        imm = _b2i32(buf, co+6)
        pb = bytearray(6); pb[0]=0xE9; pb[1:5]=_i32b(imm+1); pb[5]=0x90
        pd = f"je near -> jmp near + NOP"
    elif bo == 0x0F and bo2 == 0x85:
        pb = bytes([0x90]*6); pd = "jne near -> NOP x 6"
    else:
        log(f"  [WARN] 未识别 je/jne, 跳过"); _CloseHandle(hp); return

    log(f"  识别到: {pd}")
    op = vp_ex(hp, ba, len(pb), PAGE_EXECUTE_READWRITE)
    nw = write_pm(hp, ba, pb)
    vp_ex(hp, ba, len(pb), op)
    if nw == len(pb):
        log(f"  [OK] sub_4C33FC+0x{co+4:X} 修补成功 ({pd})")
        vb, _ = read_pm(hp, ba, len(pb))
        log(f"  验证: [{_bhex(vb)}]")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十三] sub_41C120 stream error 检查修补
# ============================================================

def patch_41c120(cpid: int, base: int):
    """修补 sub_41C120: 每次调用前强制清零 stream+8"""
    sr = 0x1C120
    log("\n--- [补丁十三] sub_41C120 stream error 检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 16:
        log(f"  [ERROR] 读取 sub_41C120@0x{av:08X} 失败"); _CloseHandle(hp); return

    log(f"  sub_41C120@0x{av:08X} 入口: [{_bhex(buf, 0, min(nr,64))}]")

    lo = -1
    for i in range(min(nr, 32) - 5):
        if buf[i]==0x8B and buf[i+1]==0x4A and buf[i+2]==0x08 and buf[i+3]==0x85 and buf[i+4]==0xC9:
            lo = i; break

    if lo < 0:
        log("  [WARN] 未找到模式, 跳过"); _CloseHandle(hp); return

    log(f"  找到 mov ecx,[edx+8];test ecx,ecx 位于 +0x{lo:X}")
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
        vb, _ = read_pm(hp, pa, 13)
        log(f"  验证: [{_bhex(vb)}]")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十四] 存档界面队伍头像 hook
# ============================================================

def patch_archive_portrait(cpid: int, base: int):
    """修补 sub_41AB94 内 add ax,0xD3+push eax 为 call archive_portrait cave"""
    global _archive_portrait_cave_addr
    sr = 0x1AB94; ssz = 0x500
    log("\n--- [补丁十四] 存档界面队伍头像 hook ---")
    if _archive_portrait_cave_addr == 0:
        log("  [WARN] ArchivePortraitCave 未分配, 跳过"); return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, ssz)
    if nr < 64:
        log(f"  [ERROR] 读取 sub_41AB94@0x{av:08X} 失败"); _CloseHandle(hp); return

    log(f"  sub_41AB94@0x{av:08X} 函数体扫描 {nr} 字节")
    log(f"  ArchivePortraitCave: 0x{_archive_portrait_cave_addr:08X}")

    ptd = 0
    for i in range(nr - 5):
        if buf[i]==0x66 and buf[i+1]==0x05 and buf[i+2]==0xD3 and buf[i+3]==0x00 and buf[i+4]==0x50:
            hrva = sr + i; ha = base + hrva
            co = (_archive_portrait_cave_addr - (ha + 5)) & 0xFFFFFFFF
            cd = bytearray(5); cd[0]=0xE8; cd[1:5]=_i32b(co)
            op = vp_ex(hp, ha, 5, PAGE_EXECUTE_READWRITE)
            nw = write_pm(hp, ha, bytes(cd))
            vp_ex(hp, ha, 5, op)
            if nw == 5:
                ptd += 1
                log(f"    [OK] RVA 0x{hrva:X}: hook add ax,0xD3+push eax -> cave")

    log(f"  共 hook {ptd} 处")
    if ptd == 0:
        log("  [WARN] 未找到 66 05 D3 00 50 模式")
    _CloseHandle(hp)

# ============================================================
# [补丁十七] 存档界面金钱显示修复
# ============================================================

def patch_gold_display(cpid: int, base: int):
    """修补 movsx->movzx 修复 signed short 金钱显示"""
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
                log(f"    [OK] RVA 0x{sr + i:05X}: movsx->movzx [ecx+eax*2+0x2D4]")

    log(f"  共修补 {ptd} 处")
    if ptd == 0:
        log("  [WARN] 未找到金钱显示 movsx 模式")
    _CloseHandle(hp)

# ============================================================
# 主入口
# ============================================================

def main():
    global _warpc_expanded, _warpc_full_data, _warpc_new_buf, _truncated_files

    # 确定启动器目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    if not exe_dir:
        exe_dir = os.getcwd()

    log_init()
    log_file(f"启动器目录: {exe_dir}")
    log_file(f"工作目录: {os.getcwd()}")

    tks_path = "TKS.exe"
    wait_timeout = 30
    minimal_mode = False
    no_cave_mode = False
    only_portrait = False
    only_awk = False
    game_dir = None

    # 解析命令行参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--exe" and i + 1 < len(args):
            i += 1; tks_path = args[i]
        elif a == "--wait" and i + 1 < len(args):
            i += 1; wait_timeout = int(args[i])
        elif a == "--cwd" and i + 1 < len(args):
            i += 1; game_dir = os.path.abspath(args[i])
        elif a == "--minimal":
            minimal_mode = True
        elif a == "--no-cave":
            no_cave_mode = True
        elif a == "--only-portrait":
            only_portrait = True
        elif a == "--only-awk":
            only_awk = True
        elif a == "--help":
            log("TKS Launcher - 自动运行时补丁启动器 (Python版)")
            log("用法: python tks_launcher.py [选项]")
            log("  --exe <路径>      指定 TKS.exe 路径 (默认 ./TKS.exe)")
            log("  --cwd <目录>      指定游戏工作目录 (默认当前目录)")
            log("  --wait <秒>       等待游戏就绪超时 (默认 30)")
            log("  --minimal         最小模式, 跳过 WarPC 扩展")
            log("  --no-cave         跳过 cave hook")
            log("  --only-portrait   仅应用头像补丁")
            log("  --only-awk        仅应用战场形象补丁")
            log("  --help            显示此帮助")
            log("")
            log("示例:")
            log("  python tks_launcher.py --cwd D:\\Games\\TKS --exe TKS.exe")
            log("  python tks_launcher.py --exe ../TKS/TKS.exe")
            return 0
        i += 1

    # 切换到游戏工作目录
    if game_dir:
        os.chdir(game_dir)
        log(f"  工作目录切换到: {game_dir}")
        # 若 --exe 未指定且 cwd 中有 TKS.exe, 自动补全
        if tks_path == "TKS.exe" and os.path.isfile(os.path.join(game_dir, "TKS.exe")):
            tks_path = os.path.join(game_dir, "TKS.exe")

    log("========================================")
    log("TKS Launcher - 自动运行时补丁启动器 (模式扫描版) (Python)")
    log("========================================")

    # 加载配置
    config_path = os.path.join(exe_dir, CONFIG_PATH)
    log(f"配置文件: {config_path} (存在={os.path.isfile(config_path)})")
    config = load_config(config_path)
    if config is None:
        log("[ERROR] 无法加载补丁配置, 退出")
        try:
            import tkinter.messagebox as mb
            mb.showerror("TKS Launcher",
                         f"无法加载补丁配置:\n{config_path}\n\n请确认 tks_patches.json 与启动器在同一目录。")
        except Exception:
            pass
        log_close()
        return 1

    # 启动前检查
    ensure_save_directory_healthy()
    prepare_warpc_for_game()

    log(f"\n启动 {tks_path}...")
    try:
        import subprocess
        tks_proc = subprocess.Popen(tks_path, cwd=os.path.dirname(os.path.abspath(tks_path)) or os.getcwd())
    except Exception as e:
        log(f"[ERROR] 无法启动 {tks_path}: {e}")
        log("按任意键退出...")
        try:
            input()
        except Exception:
            pass
        return 1
    log(f"  TKS.exe PID = {tks_proc.pid}")

    # 查找游戏窗口
    game_hwnd = 0
    for _ in range(20):
        time.sleep(0.25)
        game_hwnd = _FindWindowW("TForm1", None)
        if not game_hwnd:
            game_hwnd = _FindWindowW(None, "TK")
        if game_hwnd:
            break

    if game_hwnd:
        log(f"  游戏窗口: 0x{game_hwnd:08X}")
        show_overlay(game_hwnd)
        update_overlay("正在等待游戏加载...")
    else:
        log("  [WARN] 未找到游戏窗口, 叠加提示不可用")

    log(f"等待游戏进程就绪 (最多 {wait_timeout} 秒)...")
    target_pid = 0
    direct_mode = False
    version_label = ""
    st = time.time()
    tpid = tks_proc.pid

    # 智能进程检测: 适配 TKS 加密版(子进程) 和 未加密版(主进程)
    while (time.time() - st) < wait_timeout:
        retcode = tks_proc.poll()
        if retcode is not None:
            log(f"  TKS.exe 已退出 (code={retcode})")
            break

        children = get_child_processes(tpid)
        if children:
            target_pid = children[0].th32ProcessID
            version_label = "TKS 加密版 (子进程模式)"
            en = children[0].szExeFile.decode('ascii', errors='replace')
            log(f"  检测到子进程: PID={target_pid} Name={en} -> {version_label}")
            update_overlay("正在加载游戏补丁...")
            time.sleep(3)
            break

        elapsed = time.time() - st
        if elapsed > 3.0 and not direct_mode:
            tb = get_module_base(tpid)
            if tb:
                ht = _OpenProcess(PROCESS_VM_READ, False, tpid)
                if ht:
                    psig, nr = read_pm(ht, tb, 2)
                    if nr == 2 and psig[0]==0x4D and psig[1]==0x5A:
                        target_pid = tpid; direct_mode = True
                        version_label = "TKS 未加密版 (主进程模式)"
                        log(f"  游戏模块已加载到主进程: base=0x{tb:08X} PID={target_pid} -> {version_label}")
                        update_overlay("正在加载游戏补丁...")
                    _CloseHandle(ht)
                if direct_mode:
                    break

        time.sleep(0.5)

    if target_pid == 0:
        log("[ERROR] 超时，未检测到游戏进程")
        if tks_proc.poll() is None:
            tks_proc.kill()
        log("按任意键退出...")
        try:
            input()
        except Exception:
            pass
        return 1

    log(f"  版本: {version_label}")
    log(f"  目标 PID: {target_pid}, 直接模式: {direct_mode}")

    base_addr = get_module_base(target_pid)
    if base_addr == 0:
        log(f"[ERROR] 无法获取目标进程 {target_pid} 的模块信息")
        if tks_proc.poll() is None:
            tks_proc.kill()
        log("按任意键退出...")
        try:
            input()
        except Exception:
            pass
        return 1
    log(f"  模块基址: 0x{base_addr:08X}")

    # Pre-patch diagnostic
    hdiag = _OpenProcess(PROCESS_VM_READ, False, target_pid)
    if hdiag:
        p1p, nr = read_pm(hdiag, base_addr + 0x17A50, 16)
        log(f"  [DIAG] PATH1@0x17A50 pre: [{_bhex(p1p, 0, min(nr, 16))}]")
        p2p, nr = read_pm(hdiag, base_addr + 0x17E1A, 16)
        log(f"  [DIAG] PATH2@0x17E1A pre: [{_bhex(p2p, 0, min(nr, 16))}]")
        _CloseHandle(hdiag)

    mod_size = get_module_size(target_pid)
    log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")

    # 读取代码段
    code_start = base_addr + 0x1000
    code_size = min(mod_size - 0x1000, 0x700000 - code_start)
    code_buf = bytearray(code_size)
    hr = _OpenProcess(PROCESS_VM_READ, False, target_pid)
    if not hr:
        log("[ERROR] 无法打开进程读取代码段")
        if tks_proc.poll() is None:
            tks_proc.kill()
        log_close()
        return 1
    raw_buf, nr = read_pm(hr, code_start, code_size)
    _CloseHandle(hr)
    if nr <= 0:
        log("[ERROR] 无法读取代码段")
        if tks_proc.poll() is None:
            tks_proc.kill()
        log_close()
        return 1
    code_buf[:nr] = raw_buf
    log(f"  代码段: 0x{code_start:08X}-0x{code_start + nr:08X} ({nr} bytes)")

    # 自动发现 WarPC BSS 基址
    fallback_base = config.variables.get("warpc_base", WARPC_BASE)
    discovered_base = discover_warpc_base(bytes(code_buf), code_start, int(fallback_base))
    config.variables["warpc_base"] = discovered_base

    # 诊断: dump 已知补丁位置
    log("\n--- 已知补丁位置字节 dump ---")
    known_rvas = [0xDA12]
    for rva in known_rvas:
        off = rva - 0x1000
        if 0 <= off + 16 <= len(code_buf):
            log(f"  RVA 0x{rva:05X}: [{_bhex(bytes(code_buf), off, 16)}]")

    # 诊断: cmp 30 搜索
    for p in ["1E 7E 26 0F BF 55", "0C 1E 7E 26"]:
        pat, wc = parse_pattern(p)
        hits = pattern_scan(bytes(code_buf), pat, wc)
        log(f"  诊断: [{p}] 出现 {len(hits)} 次")
        for off in hits:
            log(f"    偏移 0x{off:X} (abs 0x{code_start + off:08X})")

    # 诊断: 所有 cmp ?, 30
    for p in ["3C 1E", "80 F8 1E", "80 F9 1E", "80 FA 1E", "80 FB 1E", "83 F8 1E", "3D 1E 00 00 00"]:
        pat, wc = parse_pattern(p)
        hits = pattern_scan(bytes(code_buf), pat, wc)
        if hits:
            log(f"  诊断: [{p}] 出现 {len(hits)} 次")
            for off in hits:
                ctx = bytes(code_buf)[max(0,off-2):max(0,off-2)+16]
                log(f"    偏移 0x{off:X} (abs 0x{code_start + off:08X}) ctx=[{_bhex(ctx)}]")

    # 若 WarPC 扩展, 分配缓冲区
    warpc_base_for_caves = 0
    if _warpc_expanded and _warpc_full_data:
        import shutil
        wp = "WarPC.dat"; bp = wp + ".orig"
        if os.path.isfile(bp):
            shutil.copy2(bp, wp); os.remove(bp)
            log("  已恢复原始 WarPC.dat")

        ns = len(_warpc_full_data)
        hw = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
        if hw:
            # [补丁十一] GUARD 区: 64 KB 安全垫
            GUARD_SIZE = 0x10000
            total_alloc = ns + GUARD_SIZE
            ab = _VirtualAllocEx(hw, None, total_alloc, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
            if ab:
                abv = ctypes.cast(ab, ctypes.c_void_p).value or 0
                nb = abv + GUARD_SIZE
                write_pm(hw, nb, _warpc_full_data)
                _warpc_new_buf = nb; warpc_base_for_caves = nb
                log(f"  WarPC 缓冲区: 0x{nb:08X} ({ns} 字节, {ns // WARPC_REC_SIZE} 角色)")
                log(f"  GUARD 安全垫: 0x{abv:08X}-0x{abv + GUARD_SIZE:08X} ({GUARD_SIZE} 字节)")
            _CloseHandle(hw)

    # 恢复其他被截断的 .dat
    import shutil
    for k in list(_truncated_files.keys()):
        if k == "WarPC.dat":
            continue
        bp = k + ".orig"
        if os.path.isfile(bp):
            shutil.copy2(bp, k); os.remove(bp)
            log(f"  已恢复原始 {k}")

    # 设置配置变量
    if _warpc_expanded and _warpc_full_data:
        ns = len(_warpc_full_data)
        config.variables["warpc_new_size"] = ns
        config.variables["save_new_size"] = 9200 + ns
    else:
        config.variables["warpc_new_size"] = WARPC_ORIG_SIZE
        config.variables["save_new_size"] = WARPC_TOTAL_ORIG_SIZE

    for fname in DATA_FILE_ORIG_SIZES:
        # 变量名: "TKItem.dat" → "tkitem_actual_size" (去掉扩展名)
        basename = os.path.splitext(fname)[0]
        vn = basename.lower() + "_actual_size"
        actual = get_decompressed_size(fname)
        config.variables[vn] = actual if actual > 0 else DATA_FILE_ORIG_SIZES[fname]

    # 分配 cave 内存
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
    cave_addr = 0
    if hp:
        ca = _VirtualAllocEx(hp, None, 512, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if ca:
            cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
        _CloseHandle(hp)
    if cave_addr:
        log(f"  Cave 内存: 0x{cave_addr:08X} (512 bytes)")
    else:
        log("  [WARN] VirtualAllocEx failed, caves skipped")

    # 应用配置补丁
    log("\n=== 应用配置补丁 (模式扫描) ===")
    update_overlay("正在应用内存补丁...")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
    ok = False
    if hp:
        try:
            ok = apply_config_patches(config, code_buf, code_start, hp,
                warpc_base_for_caves if warpc_base_for_caves else discovered_base,
                cave_addr, minimal_mode, no_cave_mode, only_portrait, only_awk)
        except Exception as ex:
            log(f"[ERROR] ApplyConfigPatches 异常: {ex}")
            import traceback
            log(traceback.format_exc())
        _CloseHandle(hp)

    # 验证补丁
    hver = _OpenProcess(PROCESS_VM_READ, False, target_pid)
    if hver:
        log("\n--- 补丁验证 ---")
        crvs = [0xDA14, 0xE6C0, 0x31165, 0x3BF5B, 0x18BB5]
        cdsc = ["team_limit(C8,87)", "check_team(C8,76)", "awk_sprite(00)", "battle_wb(B6)", "skill_scan(58)"]
        for j in range(len(crvs)):
            vb, nr = read_pm(hver, base_addr + crvs[j], 4)
            log(f"  RVA 0x{crvs[j]:05X} [{cdsc[j]}]: [{_bhex(vb, 0, min(nr, 4))}]")
        _CloseHandle(hver)

    # WarPC 代码引用修补
    if not minimal_mode:
        update_overlay("正在扩展 WarPC 缓冲区...")
        expand_warpc_buffer(target_pid, base_addr, mod_size, cave_addr, code_buf, code_start)

    # [补丁十二~十四、十七] 运行时动态修补
    if not minimal_mode:
        patch_4c33fc(target_pid, base_addr)
        patch_41c120(target_pid, base_addr)
        patch_archive_portrait(target_pid, base_addr)
        patch_gold_display(target_pid, base_addr)
        inject_warpc_data(target_pid, discovered_base)

    # 验证 cave + hooks + 数据
    vlog = f"ok={ok} cave=0x{cave_addr:08X} base=0x{base_addr:08X}"
    hv = _OpenProcess(PROCESS_VM_READ, False, target_pid)
    if hv:
        # AwkSprite
        abuf, _ = read_pm(hv, cave_addr, 51)
        vlog += f" awk_cave=[{_bhex(abuf, 0, min(20, len(abuf)))}]..."
        hb, _ = read_pm(hv, base_addr + 0x309A6, 5)
        vlog += f" awk_hook=[{_bhex(hb)}]"
        # Portrait PATH1
        p1b, _ = read_pm(hv, cave_addr + 64, 41)
        vlog += f" p1_cave=[{_bhex(p1b, 0, min(20, len(p1b)))}]..."
        hb, _ = read_pm(hv, base_addr + 0x17A50, 5)
        vlog += f" p1_hook=[{_bhex(hb)}]"
        # Portrait PATH2
        p2b, _ = read_pm(hv, cave_addr + 128, 42)
        vlog += f" p2_cave=[{_bhex(p2b, 0, min(20, len(p2b)))}]..."
        p2hb, _ = read_pm(hv, base_addr + 0x17E1A, 6)
        vlog += f" p2_hook=[{_bhex(p2hb)}]"
        # WORD[261] for new characters
        wb, _ = read_pm(hv, _warpc_new_buf + 143*1054 + 522, 2) if _warpc_new_buf else (b'', 0)
        if wb: vlog += f" W261[143]=0x{_b2u16(wb):04X}"
        wb, _ = read_pm(hv, _warpc_new_buf + 144*1054 + 522, 2) if _warpc_new_buf else (b'', 0)
        if wb: vlog += f" W261[144]=0x{_b2u16(wb):04X}"
        # Team
        tb, _ = read_pm(hv, 0x75688C, 12)
        if tb:
            vlog += " team=[" + ",".join(str(_b2i16(tb, j*2)) for j in range(6)) + "]"
        # 金钱
        mb, _ = read_pm(hv, 0x756888, 2)
        if mb: vlog += f" money=0x{_b2u16(mb):04X}"

        # 存档索引诊断
        try:
            vi, zi, mi = 0, 0, 0
            for si in range(1, 10):
                p = f"save\\{si}.sav"
                if os.path.isfile(p):
                    sz = os.path.getsize(p)
                    if sz == 28: vi += 1
                    elif sz == 0: zi += 1
                else: mi += 1
            vlog += f" save_idx[ok={vi},zero={zi},miss={mi}]"
        except Exception:
            pass

        _CloseHandle(hv)

    log(vlog)

    # 存档索引文件内容 dump
    log("\n--- 存档索引文件内容详细 dump ---")
    from datetime import datetime, timezone, timedelta
    for si in range(1, 10):
        ip = f"save\\{si}.sav"; dp = f"save\\sav.{si}"
        if not os.path.isfile(ip):
            log(f"  slot {si}: 不存在"); continue
        try:
            with open(ip, 'rb') as f:
                idx = f.read()
            dsz = os.path.getsize(dp) if os.path.isfile(dp) else -1
            if len(idx) != 28:
                log(f"  slot {si}: 大小={len(idx)} (异常) hex=[{_bhex(idx)}]"); continue
            team = [struct.unpack('b', idx[k:k+1])[0] for k in range(6)]
            gt = _b2u16(idx, 6)
            uts = _b2i32(idx, 8)
            lvs = [_b2i16(idx, 12 + k*2) for k in range(6)]
            sc = _b2i32(idx, 24)
            tstime = datetime(1970,1,1, tzinfo=timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(uts,0)) + timedelta(hours=8)
            log(f"  slot {si}: idx=28B dat={dsz}B hex=[{_bhex(idx)}]")
            log(f"          team=[{','.join(str(t) for t in team)}] game_time={gt} unix_ts=0x{uts:08X}({tstime.strftime('%Y-%m-%d %H:%M:%S')}) scene={sc}")
            log(f"          levels=[{','.join('Lv'+str(l) for l in lvs)}]")
        except Exception as e:
            log(f"  slot {si}: 读取失败 {e}")
    log("")

    # 完成
    if ok:
        log("\n补丁已应用！游戏正在运行。")
        log("启动器即将退出，补丁在本次游戏会话中持续生效。")
        log("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。")
        update_overlay("补丁应用成功！游戏运行中", True)

        if _warpc_expanded:
            nc = len(_warpc_full_data) // WARPC_REC_SIZE
            log("\n--- 存档兼容性说明 ---")
            log(f"  WarPC 已扩展到 {nc} 角色 (原始 143)。")
            log("  新存档 (本次游戏保存): 完整支持, 所有角色数据正确存储。")
            log(f"  旧存档 (扩展前保存):   加载后新角色 ({WARPC_ORIG_COUNT}+) 从 WarPC.dat 恢复默认值。")
            log("\n  注意: 存档索引文件 (save\\N.sav) 队伍成员 ID 仅存储 1 字节。")
            log("        若角色 ID >= 256, 存档列表中该角色头像/名称将显示异常。")
            log(f"        当前角色 ID 范围: 0-{nc-1}, 状态: {'存在截断风险!' if nc > 256 else '安全'}")
            log("\n  注意: 新游戏初始化 (sub_412688) 会清零队伍/金币/统计区域。")
            log("        开局时队伍显示 [主角, 空, 空, 空, 空, 空] 是游戏设计行为, 非 bug。")
    else:
        log("\n[WARN] 部分补丁未应用成功")
        update_overlay("补丁应用失败！", False)

    # 延迟关闭叠加窗口
    time.sleep(2)
    close_overlay()
    time.sleep(0.5)

    log_close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
