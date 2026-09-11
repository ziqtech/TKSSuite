# -*- coding: utf-8 -*-
"""光标自擦除验证 v3: 心跳判别菜单态 (进菜单即停点击) → 光标 A/B 残留判定。"""
import ctypes, struct, time, subprocess

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

def find_pid():
    for _ in range(90):
        try:
            out = subprocess.check_output(['powershell', '-NoProfile', '-Command',
                'Get-Process TKS -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],
                text=True).strip()
            if out:
                return int(out.splitlines()[0])
        except Exception:
            pass
        time.sleep(1)
    return None

class R:
    def __init__(self, pid):
        self.h = k32.OpenProcess(0x1F0FFF, False, pid)
    def read(self, a, n):
        b = ctypes.create_string_buffer(n); g = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(a), b, n, ctypes.byref(g))
        return b.raw[:g.value] if ok and g.value == n else None
    def write(self, a, data):
        b = ctypes.create_string_buffer(data); g = ctypes.c_size_t()
        return bool(k32.WriteProcessMemory(self.h, ctypes.c_void_p(a), b, len(data), ctypes.byref(g)))
    def u32(self, a):
        b = self.read(a, 4)
        return struct.unpack('<I', b)[0] if b else None

def main():
    pid = find_pid()
    if not pid:
        print('NO TKS'); return
    r = R(pid)
    print('PID', pid)
    deadline = time.time() + 60
    while time.time() < deadline:
        if r.u32(0xB10000):
            break
        time.sleep(0.05)
    else:
        print('globals 未初始化'); return
    print('渲染循环启动')

    # 等菜单: 心跳一动 = 标题循环每帧节拍 (点击推进由外部真实鼠标完成)
    menu = False
    t0 = time.time()
    while time.time() - t0 < 150:
        hb0 = r.u32(0x4E7CD0)
        time.sleep(0.3)
        hb1 = r.u32(0x4E7CD0)
        if hb1 != hb0:
            menu = True
            break
    print('菜单态:', menu)
    if not menu:
        print('未进入标题循环'); return
    time.sleep(0.8)

    pitch = struct.unpack('<I', r.read(0xA2ACD8, 4))[0]
    bs = r.u32(0xA2ACEC)
    print('lPitch =', pitch, ' lpSurface =', hex(bs) if bs else None)
    if not bs:
        print('无法取后备表面'); return

    def snapshot(cx, cy, half=48):
        rows = []
        for y in range(max(0, cy-half), min(480, cy+half)):
            row = r.read(bs + y*pitch + max(0, cx-half)*2, half*4)
            rows.append(row)
        return b''.join(rows)

    # A 放光标
    r.write(0x824278, struct.pack('<II', 200, 200))
    time.sleep(0.3)
    a_with = snapshot(200, 200)
    # 移到 B
    r.write(0x824278, struct.pack('<II', 500, 200))
    time.sleep(0.3)
    a_after = snapshot(200, 200)
    b_with = snapshot(500, 200)
    # 移到 C
    r.write(0x824278, struct.pack('<II', 350, 300))
    time.sleep(0.3)
    b_after = snapshot(500, 200)

    a_ok = a_with != a_after
    b_ok = b_with != b_after
    print(f'A(200,200) 移走后恢复背景: {a_ok}')
    print(f'B(500,200) 移走后恢复背景: {b_ok}')
    print('=> 判定:', '自擦除生效 ✓ 无拖影' if (a_ok and b_ok) else '仍有残留 ✗')
    # BK 槽位
    G = 0xB10000
    print('BK_VALID', r.u32(G+0x7C), 'BK_X0', r.u32(G+0x88), 'BK_Y0', r.u32(G+0x8C),
          'BK_W', r.u32(G+0x90), 'BK_H', r.u32(G+0x94), 'PX', r.u32(G+0x74), 'PY', r.u32(G+0x78))

if __name__ == '__main__':
    main()
