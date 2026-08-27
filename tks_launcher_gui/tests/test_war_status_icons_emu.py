# -*- coding: utf-8 -*-
"""unicorn 执行级验证: 构造完整内存环境执行真实 cave 字节码。
这是对 cave 的最终审判 —— 任何编码错误都会在执行结果中暴露。
定位过 v7.5 双 bug: ①obj+8/obj+12 是指针非内联数组; ②总帧数在
obj+0x18 (a2[6] 下标语义) 而非 obj+0x24。"""
import struct
import sys

sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

from test_war_status_icons_cave import cave_bytes
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_ESP)

CAVE, CANVAS, SCRATCH = 0x00400000, 0x01000000, 0x02000000
STACK = 0x7FF00000
A_CAMX, A_CAMY = 0x8242A8, 0x8242AC
A_POSX, A_POSY = 0x9DF802, 0x9DF804
A_MU2, A_FBASE = 0x755AF4, 0x9D6F76
A_GRID = 0x951D42


def run_frame(frame_idx: int) -> tuple:
    """构造环境: 单位0 带状态ID=frame_idx-75, 返回 (expect, canvas)。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE, 0x2000)
    uc.mem_map(CANVAS, 0x100000)
    uc.mem_map(SCRATCH, 0x500000)
    uc.mem_map(0x700000, 0x400000)
    uc.mem_map(STACK - 0x100000, 0x200000)
    code = bytes(cave_bytes())
    uc.mem_write(CAVE, code)

    d = open(r"逆向工作区/Mu2.JVG", "rb").read()
    # 解析全部块 → loader (sub_453BD0) 等价对象结构
    obj = SCRATCH + 0x0
    records = SCRATCH + 0x1000
    f2b_addr, f2sf_addr = SCRATCH + 0x30000, SCRATCH + 0x31000
    acc, p2 = 0, 32
    blk_info = {}
    for b in range(57):
        s2 = struct.unpack_from("<I", d, p2 + 4)[0]
        dz2 = struct.unpack_from("<I", d, p2 + 12)[0]
        l2 = p2 + 32
        # 块内布局: [tag4+头28=32B][偏移表(s2+1)*4][调色板512][数据dz2]
        # l2=块头结束(=偏移表起点); ot=偏移表; pal=调色板; ds=数据起点
        blk_info[b] = (l2, l2, l2 + (s2 + 1) * 4,
                       l2 + (s2 + 1) * 4 + 512, s2, dz2)
        acc += s2
        p2 = l2 + (s2 + 1) * 4 + 512 + dz2
    # obj: +0 records, +8/+12 表指针, +24(0x18) 总帧数
    uc.mem_write(obj, struct.pack("<I", records))
    uc.mem_write(obj + 8, struct.pack("<I", f2b_addr))
    uc.mem_write(obj + 12, struct.pack("<I", f2sf_addr))
    uc.mem_write(obj + 24, struct.pack("<I", acc))
    f2b, f2sf = b"", b""
    p2 = 32
    for b in range(57):
        s2 = struct.unpack_from("<I", d, p2 + 4)[0]
        for k in range(s2):
            f2b += struct.pack("<H", b)
            f2sf += struct.pack("<H", k)
        dz2 = struct.unpack_from("<I", d, p2 + 12)[0]
        p2 = p2 + 32 + (s2 + 1) * 4 + 512 + dz2
    uc.mem_write(f2b_addr, f2b)
    uc.mem_write(f2sf_addr, f2sf)
    # 每块记录 + 偏移表 + blob + 调色板
    for b, (l2, ot_off, pal_off, ds, s2, dz2) in blk_info.items():
        ot_addr = SCRATCH + 0x40000 + b * 0x400
        pal_addr = SCRATCH + 0x50000 + b * 0x400
        blob_addr = SCRATCH + 0x60000 + b * 0xC000
        rec = bytearray(64)
        struct.pack_into("<I", rec, 0, s2)
        struct.pack_into("<I", rec, 40, ot_addr)
        struct.pack_into("<I", rec, 44, blob_addr)
        struct.pack_into("<I", rec, 48, dz2)
        uc.mem_write(records + b * 64, bytes(rec))
        uc.mem_write(ot_addr, d[ot_off:ot_off + (s2 + 1) * 4])
        uc.mem_write(pal_addr, d[pal_off:pal_off + 512])
        uc.mem_write(blob_addr, d[ds:ds + dz2])
        uc.mem_write(records + b * 64 + 8, struct.pack("<I", pal_addr))
        uc.mem_write(records + b * 64 + 4, struct.pack("<I", pal_addr))

    # 全局/单位数据
    uc.mem_write(A_MU2, struct.pack("<I", obj))
    uc.mem_write(A_FBASE, struct.pack("<H", 76))
    uc.mem_write(A_CAMX, struct.pack("<i", 0))
    uc.mem_write(A_CAMY, struct.pack("<i", 0))
    uc.mem_write(A_GRID, b"\x00")
    uc.mem_write(A_POSX, struct.pack("<h", 320))
    uc.mem_write(A_POSY, struct.pack("<h", 240))
    uc.mem_write(0x9D707A + 0x0A, struct.pack("<h", 100))
    uc.mem_write(0x9D707A + 0x56, struct.pack("<H", frame_idx - 75))

    ebp = STACK - 0x1000
    esp = STACK - 0x2000
    uc.mem_write(ebp + 8, struct.pack("<I", CANVAS))
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.mem_write(esp, struct.pack("<I", CAVE + len(code)))
    uc.emu_start(CAVE, CAVE + len(code))

    # ground truth: 直接解码该帧
    b = struct.unpack_from("<H", d, f2b_addr - SCRATCH * 0 + 0)[0] if False else None
    # 从 f2b 表内容找 block/sf
    blk = struct.unpack_from("<H", f2b[frame_idx * 2:frame_idx * 2 + 2])[0]
    sf = struct.unpack_from("<H", f2sf[frame_idx * 2:frame_idx * 2 + 2])[0]
    l2, ot_off, pal_off, ds, s2, _dz = blk_info[blk]
    offs = [struct.unpack_from("<I", d, ot_off + i * 4)[0] for i in range(s2 + 1)]
    fo = ds + offs[sf]
    pal = [struct.unpack_from("<H", d, pal_off + i * 2)[0] for i in range(256)]
    _xm, _ym, W, H = struct.unpack_from("<hhHH", d, fo)
    rcnt = struct.unpack_from("<H", d, fo + 14)[0]
    gt = [[None] * W for _ in range(H)]
    src, p = fo + 16, 0
    for _ in range(rcnt):
        skip, run = struct.unpack_from("<HH", d, src)
        src += 4
        p += skip
        for k in range(run):
            r640, c640 = divmod(p, 640)
            if r640 < H and c640 < W:
                gt[H - 1 - r640][W - 1 - c640] = pal[d[src + k]]
            p += 1
        src += run
    expect = [[gt[H * ty // 10][W * tx // 10] for tx in range(10)]
              for ty in range(10)]
    return expect, bytes(uc.mem_read(CANVAS, 640 * 480 * 2)), W, H


def main() -> bool:
    ok = True
    for fi in (76, 80, 90, 100, 106):        # 跨块抽查 5 帧
        expect, canvas, W, H = run_frame(fi)
        x0, y0 = 320 - 37, 240 - 143
        bad = 0
        for ty in range(10):
            for tx in range(10):
                exp = expect[ty][tx]
                got = struct.unpack_from("<H", canvas, ((y0 + ty) * 640 + x0 + tx) * 2)[0]
                if exp is not None and got != exp:
                    bad += 1
                if exp is None and got != 0:
                    bad += 1
        status = "[OK]" if bad == 0 else f"[FAIL] {bad} 像素不符"
        print(f"  frame{fi}: {status}")
        ok &= bad == 0
    print("[OK] unicorn 执行级验证全部通过" if ok else "[FAIL] 存在差异")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
