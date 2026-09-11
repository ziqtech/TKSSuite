# -*- coding: utf-8 -*-
"""宽屏光标问题现场诊断: 读游戏进程内存核对 cursor_scratch 链路每一步。"""
import ctypes, ctypes.wintypes as wt, struct, sys, math

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

def find_pid(name_lower='tks.exe'):
    import subprocess
    out = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        f'Get-Process | Where-Object {{ $_.ProcessName -eq "{name_lower[:-4]}" }} | Select-Object -ExpandProperty Id'],
        text=True).strip()
    return int(out.splitlines()[0]) if out else None

class Reader:
    def __init__(self, pid):
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise OSError('OpenProcess failed')
    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
        return buf.raw[:got.value] if ok else None
    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None
    def u16(self, addr):
        b = self.read(addr, 2)
        return struct.unpack('<H', b)[0] if b else None

def main():
    pid = find_pid()
    if not pid:
        print('NO TKS PROCESS'); return
    print('PID', pid)
    r = Reader(pid)
    BASE = 0x400000

    # 1. 光标调用位点是否已打补丁
    site = r.read(BASE + 0x11D4A, 5)
    print('site 0x411D4A bytes:', site.hex(' ') if site else None)
    cave = None
    if site and site[0] == 0xE8:
        rel = struct.unpack('<i', site[1:5])[0]
        cave = BASE + 0x11D4A + 5 + rel
        print('cave cursor_scratch VA =', hex(cave))
        head = r.read(cave, 8)
        print('cave head:', head.hex(' ') if head else None, '(expect 53 56 57 55 = push ebx,esi,edi,ebp)')

    # 2. 全局状态
    for name, va in [('g_stride', 0x660800), ('g_off', 0x660828), ('g_end', 0x66083C),
                     ('PAGE_X', 0x660840), ('PAGE_REC_X', 0x660844),
                     ('mouse_raw_X', 0x824278), ('mouse_raw_Y', 0x82427C),
                     ('mouse_world_X', 0x824280), ('viewX', 0x8242A8),
                     ('cursor_flag', 0x4E7CF0), ('cur_obj', 0x755AF8),
                     ('cur_frame', 0x8242D4), ('cur_block', 0x8242C8),
                     ('cur_speed', 0x8242CC), ('cur_framecnt', 0x8242D8),
                     ('back_surface', 0xA2B998), ('ddsd_lPitch', 0xA2ACE8)]:
        print(f'{name:16s} [{hex(va)}] =', r.u32(va))

    # 3. CUR_* 瞬时槽 (cave 运行时写入)
    for name, va in [('CUR_W', 0x66084C), ('CUR_H', 0x660850), ('CUR_XO', 0x660854),
                     ('CUR_YO', 0x660858), ('CUR_SSV', 0x66085C), ('CUR_CX0', 0x660864),
                     ('CUR_CX1', 0x660868), ('CUR_CY0', 0x66086C), ('CUR_CY1', 0x660870)]:
        print(f'{name:16s} [{hex(va)}] =', r.u32(va))

    # 4. SCRATCH 内容: 哨兵占比 (0x660878, 640*480)
    sc = r.read(0x660878, 640*480*2)
    if sc:
        px = struct.unpack(f'<{640*480}H', sc)
        sent = sum(1 for p in px if p == 0xFE1F)
        print(f'SCRATCH: sentinel {sent}/{640*480} ({sent*100//(640*480)}%), nonzero-non-sentinel {sum(1 for p in px if p not in (0,0xFE1F))}')

    # 5. 后备表面鼠标周围像素
    bs = r.u32(0xA2B998)
    mx, my = r.u32(0x824278) or 0, r.u32(0x82427C) or 0
    pitch = r.u32(0xA2ACE8)
    print('back_surface', hex(bs) if bs else None, 'mouse', mx, my, 'lPitch@A2ACE8', pitch, 'lPitch@A2ACD8', r.u32(0xA2ACD8))
    if bs:
        # lPitch 实际在 ddsd+0x10, A2ACD8 指向 ddsd?
        lp = pitch or 1712
        region = r.read(bs + my*lp + max(0,mx-40)*2, 80*2)
        if region:
            px = struct.unpack('<80H', region)
            print('back surface pixels x[%d..%d] @y=%d:' % (mx-40, mx+39, my),
                  ' '.join(f'{p:04X}' for p in px[:40]))

if __name__ == '__main__':
    main()
