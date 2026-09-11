# -*- coding: utf-8 -*-
"""宽屏光标诊断 v3: 一次性 dump 解码器全局状态 + 对象图 + 位点字节, 定位解码不写入的原因。"""
import ctypes, struct, sys

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
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
        return buf.raw[:got.value] if ok and got.value == size else None
    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None

def main():
    pid = find_pid()
    if not pid:
        print('NO TKS PROCESS'); return
    print('PID', pid)
    r = R(pid)

    print('== 解码器全局 (上一次 sub_4544EC 调用后残留) ==')
    for name, va in [('A5AEB0 inner', 0xA5AEB0), ('A5AEB4 写指针', 0xA5AEB4),
                     ('A5AEB8 调色板', 0xA5AEB8), ('A5AEBC RLE指针', 0xA5AEBC),
                     ('A5AEC4 fd', 0xA5AEC4), ('A5AECA 记录数', 0xA5AECA),
                     ('4ED840 p计数', 0x4ED840)]:
        v = r.u32(va)
        print(f'  {name:14s} [{hex(va)}] = {hex(v) if v is not None else None}')

    print('== 鼠标/光标状态 ==')
    for name, va in [('mouseX', 0x824278), ('mouseY', 0x82427C), ('frame', 0x8242D4),
                     ('cursor_flag', 0x4E7CF0), ('g_stride', 0x660800), ('g_end', 0x66083C)]:
        print(f'  {name:12s} =', r.u32(va))

    print('== sub_4544EC 关键位点运行时字节 ==')
    for va, n, desc in [(0x45460A, 19, 'stride idiom'), (0x45467E, 2, 'jmp simple'),
                        (0x454676, 6, 'cmp bottom,480'), (0x4546F0, 4, 'records loop head'),
                        (0x454680, 12, 'skip 处理'), (0x4546AF, 16, 'run 写入')]:
        b = r.read(va, n)
        print(f'  {hex(va)} {desc}: {b.hex(" ") if b else None}')

    print('== 运行时对象图 ==')
    obj = r.u32(0x755AF8); frame = r.u32(0x8242D4)
    if not obj:
        print('  obj 为空!'); return
    print('  obj', hex(obj), 'frame', frame)
    a2c = r.u32(obj + 0xC); a28 = r.u32(obj + 8); base = r.u32(obj)
    print('  [obj]=', hex(base), ' [obj+8]=', hex(a28), ' [obj+C]=', hex(a2c),
          ' [obj+18]帧总数=', r.u32(obj + 0x18))
    V1 = struct.unpack('<H', r.read(a2c + frame * 2, 2))[0]
    v = struct.unpack('<H', r.read(a28 + frame * 2, 2))[0]
    inner = base + v * 64
    print('  V1=', V1, ' v=', v, ' inner=', hex(inner), ' inner[0]=', r.u32(inner))
    tbl = r.u32(inner + 0x28); fdata = r.u32(inner + 0x2C)
    off = r.u32(tbl + V1 * 4)
    fd = fdata + off
    print('  tbl=', hex(tbl), ' fdata=', hex(fdata), ' off=', off, ' fd=', hex(fd))
    hdr = r.read(fd, 32)
    print('  fd头32B:', hdr.hex(' '))
    xMax, yMax, w, h = struct.unpack_from('<hhHH', hdr, 0)
    rec = struct.unpack_from('<H', hdr, 14)[0]
    print(f'  xMax={xMax} yMax={yMax} w={w} h={h} records={rec}')
    idx = r.u32(inner + 0x3C)
    pal = r.u32(inner + idx * 4 + 8) if idx is not None else None
    print('  默认调色板 idx=', idx, ' pal=', hex(pal) if pal else None)
    if pal:
        print('  调色板前8色:', r.read(pal, 16).hex(' '))
    # RLE 前6条记录
    rle = fd + 16
    print('  RLE记录:')
    for i in range(min(6, rec)):
        skip, run = struct.unpack_from('<HH', r.read(rle, 4))
        print(f'    rec{i}: skip={skip} run={run} data={r.read(rle+4, min(run, 12)).hex(" ")}')
        rle += 4 + run

    print('== scratch 外围扫描: 0x660878 前后是否有光标像素写入 ==')
    below = r.read(0x660000, 0x878)
    if below:
        nz = [hex(0x660000 + i) for i in range(0, len(below) - 1, 2)
              if below[i:i+2] != b'\x00\x00' and i < 0x800]
        print('  下方非零(前10):', nz[:10])
    above = r.read(0x6FC878, 0x8000)
    if above:
        nzc = sum(1 for i in range(0, len(above) - 1, 2) if above[i:i+2] != b'\x00\x00')
        print('  上方(0x6FC878+32K)非零像素数:', nzc)

    print('== 光标解码期望锚点区 (scratch 行238..277) ==')
    sc = r.read(0x660878 + 238 * 1280, 40 * 1280)
    if sc:
        px = struct.unpack('<25600H', sc)
        sent = sum(1 for p in px if p == 0xFE1F)
        zero = sum(1 for p in px if p == 0)
        other = 25600 - sent - zero
        print(f'  哨兵={sent} 零={zero} 其他={other}')

if __name__ == '__main__':
    main()
