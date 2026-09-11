# -*- coding: utf-8 -*-
"""宽屏光标诊断 v4: 等菜单出现后 dump 解码器全局残留 + scratch 状态。"""
import ctypes, struct, time, sys

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

def find_pid():
    import subprocess
    out = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        'Get-Process | Where-Object { $_.ProcessName -eq "TKS" } | Select-Object -ExpandProperty Id'],
        text=True).strip()
    return int(out.splitlines()[0]) if out else None

class R:
    def __init__(self, pid):
        self.h = k32.OpenProcess(0x410, False, pid)
        if not self.h:
            raise OSError('OpenProcess failed')
    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size); got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(h := self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
        return buf.raw[:got.value] if ok and got.value == size else None
    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None

def main():
    pid = find_pid()
    if not pid:
        print('NO TKS PROCESS'); return
    r = R(pid)
    print('PID', pid)
    # 轮询等待 DD 初始化 (g_stride != 0) — 菜单已开始渲染
    deadline = time.time() + 60
    while time.time() < deadline:
        s = r.u32(0x660800)
        if s:
            print('g_stride =', s, '— 游戏已进入渲染循环')
            break
        time.sleep(0.05)
    else:
        print('60s 内未进入渲染'); return

    for trial in range(3):
        print(f'--- trial {trial} ---')
        for name, va in [('g_stride', 0x660800), ('g_end', 0x66083C),
                         ('A5AEB0 inner', 0xA5AEB0), ('A5AEB4 写指针', 0xA5AEB4),
                         ('A5AEB8 调色板', 0xA5AEB8), ('A5AEBC RLE指针', 0xA5AEBC),
                         ('A5AEC4 fd', 0xA5AEC4)]:
            v = r.u32(va)
            print(f'  {name:14s} = {hex(v) if v is not None else None}')
        rec = r.read(0xA5AECA, 2)
        p = r.u32(0x4ED840)
        print(f'  A5AECA 记录数 = {struct.unpack("<H", rec)[0] if rec else None}  4ED840 p = {hex(p) if p is not None else None}')
        print('  mouseX/Y:', r.u32(0x824278), r.u32(0x82427C), ' frame:', r.u32(0x8242D4))
        # 写指针相对 scratch 的位置
        wp = r.u32(0xA5AEB4)
        if wp:
            print(f'  写指针 - SCRATCH(0x660878) = {hex(wp - 0x660878)} (行 {hex((wp-0x660878)//1280)}, 列 {((wp-0x660878)%1280)//2})')
            # 写指针前后 32 字节
            b = r.read(wp - 16, 48)
            print('  写指针附近:', b.hex(' ') if b else None)
        # scratch 锚点区
        sc = r.read(0x660878 + 238 * 1280, 40 * 1280)
        if sc:
            px = struct.unpack('<25600H', sc)
            sent = sum(1 for p_ in px if p_ == 0xFE1F)
            zero = sum(1 for p_ in px if p_ == 0)
            print(f'  锚点区: 哨兵={sent} 零={zero} 其他={25600-sent-zero}')
        # scratch 下边界外 (前 0x800)
        below = r.read(0x660878 - 0x800, 0x800)
        if below:
            nz = sum(1 for i in range(0, 0x800, 2) if below[i:i+2] != b'\x00\x00')
            print(f'  scratch下方2KB非零像素: {nz}')
        time.sleep(0.15)

if __name__ == '__main__':
    main()
