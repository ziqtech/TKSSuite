# -*- coding: utf-8 -*-
"""宽屏光标问题诊断 v2: 运行时cave校验 + scratch边界精测 + 鼠标移动观测。"""
import ctypes, struct, sys, time

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32 = ctypes.WinDLL('user32', use_last_error=True)

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

    # 1. 运行时 cave 与构建块逐字节比对
    sys.path.insert(0, r'tks_launcher_gui\patches\widescreen_16_9')
    import cave_code
    site = r.read(0x411D4A, 5)
    rel = struct.unpack('<i', site[1:5])[0]
    cave = 0x411D4A + 5 + rel
    print('cursor_scratch cave @', hex(cave))
    off = cave_code.CAVE_ENTRIES['cursor_scratch']
    built = cave_code.build_cursor_scratch()
    runtime = r.read(cave, len(built))
    if runtime == built:
        print('RUNTIME CAVE == BUILT (%d bytes)' % len(built))
    else:
        for i in range(len(built)):
            if runtime[i] != built[i]:
                print(f'CAVE DIFF at +{i:#x}: runtime {runtime[i]:02X} built {built[i]:02X}')
                break
        # 也校验整个 cave 块
        all_built = cave_code.build_cave_block()
        cbase = cave - off
        all_rt = r.read(cbase, len(all_built))
        diffs = [i for i in range(len(all_built)) if all_rt[i] != all_built[i]]
        print(f'full cave block diff count: {len(diffs)}', ('first @'+hex(diffs[0])) if diffs else '')

    # 2. scratch 边界精测 (多次采样)
    for sample in range(3):
        sc = r.read(0x660878, 0x96000)
        if not sc:
            print('scratch read FAILED'); return
        px = struct.unpack('<307200H', sc)
        # 找最后一行含哨兵的行号 & 全零行数
        sent_rows = [y for y in range(480) if any(px[y*640+x] == 0xFE1F for x in range(0, 640, 8))]
        zero_rows = sum(1 for y in range(480) if all(px[y*640+x] == 0 for x in range(0, 640, 8)))
        nz = sum(1 for p in px if p != 0 and p != 0xFE1F)
        sent = sum(1 for p in px if p == 0xFE1F)
        last_sent_row = max(sent_rows) if sent_rows else -1
        print(f'sample{sample}: sentinel_px={sent} nonzero={nz} zero_rows={zero_rows} last_sent_row={last_sent_row}')
        if sample < 2:
            time.sleep(0.25)

    # 3. 鼠标状态
    print('mouse raw:', r.u32(0x824278), r.u32(0x82427C),
          'PAGE_X:', r.u32(0x660840), 'frame:', r.u32(0x8242D4),
          'CUR_CX0..1:', r.u32(0x660864), r.u32(0x660868),
          'CUR_CY0..1:', r.u32(0x66086C), r.u32(0x660870))

if __name__ == '__main__':
    main()
