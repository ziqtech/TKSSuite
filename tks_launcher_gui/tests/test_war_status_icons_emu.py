# -*- coding: utf-8 -*-
"""unicorn 执行级验证: 构造完整内存环境执行真实 cave 字节码。
这是对 cave 的最终审判 —— 任何编码错误都会在执行结果中暴露。
定位过 v7.5 双 bug: ①obj+8/obj+12 是指针非内联数组; ②总帧数在
obj+0x18 (a2[6] 下标语义) 而非 0x24。

v7.9 新增验证:
- 行1 居中布局: 图标位置由行内激活序号 k 决定 (空槽不占位),
  xx = x0 + offset1 + k*31, offset1 = (124-31*n1)>>1 (n1=1..4
  → 46/31/15/0); 行2 从左到右 xx = x0 + k*31。多状态集合用例:
  单状态居中 / 两状态占中两格 / 分散槽紧凑排列 / 三状态 / 满行 /
  行2 溢出 / 行1+行2 混合;
- 全行区域断言: 除图标矩形外整行 123px × 30px 全零
  (空槽透明 + 无幽灵块 + 步进正确三合一)。

v7.8 新增验证:
- 入口 edx = movsx word[9D6C88] 的值 (hook 点 0x43A7A6 位于该 movsx
  之后, popad 恢复后尾声用重放 cmp edx,0x2b 重新求值 bounds 分支);
- 尾部双路径: edx=0 (有效面板状态) → ret 落回 E8 返回地址原值;
  edx=0xFFFFFFFF (word_9D6C88=-1, 无菜单的 default 路径) → ret 落回
  返回地址+0x112 (0x43A7AB→0x43A8BD), 且两路径栈均平衡 (esp 恢复)。"""
import struct
import sys

sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

from test_war_status_icons_cave import cave_bytes
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_ESP,
                               UC_X86_REG_EDX)

CAVE, CANVAS, SCRATCH = 0x00400000, 0x01000000, 0x02000000
STACK = 0x7FF00000
A_CAMX, A_CAMY = 0x8242A8, 0x8242AC
A_POSX, A_POSY = 0x9DF802, 0x9DF804
A_MU2, A_FBASE = 0x755AF4, 0x9D6F76
A_GRID = 0x951D42


def run_frame(frame_idx: int, active: tuple = (0,)) -> tuple:
    """构造环境: 单位0 在指定 slot 集合带状态ID, 返回 (expect, canvas)。"""
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
    for s in active:
        uc.mem_write(0x9D707A + 0x56 + s * 2,
                     struct.pack("<H", frame_idx - 75))

    ebp = STACK - 0x1000
    esp = STACK - 0x2000
    uc.mem_write(ebp + 8, struct.pack("<I", CANVAS))
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, esp)
    # v7.8: hook 点 0x43A7A6 的入口 edx = movsx word[9D6C88] 结果。
    # 面板状态 0 (有效) → 尾声 jbe → 正常 ret 路径。
    uc.reg_write(UC_X86_REG_EDX, 0)
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
    expect = [[gt[H * ty // 30][W * tx // 30] for tx in range(30)]
              for ty in range(30)]
    return expect, bytes(uc.mem_read(CANVAS, 640 * 480 * 2)), W, H


def run_tail(edx_val: int, ret_addr: int, stop_addr: int) -> int:
    """最小环境 (无存活单位: HP=0) 执行 cave, 验证尾声分支与栈平衡。

    返回停止时的 esp (入口 esp + 4 = ret 弹出返回地址后严格平衡)。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE, 0x2000)
    uc.mem_map(CANVAS, 0x100000)
    uc.mem_map(SCRATCH, 0x500000)
    uc.mem_map(0x700000, 0x400000)
    uc.mem_map(STACK - 0x100000, 0x200000)
    code = bytes(cave_bytes())
    uc.mem_write(CAVE, code)
    # 全局区默认全零: Mu2 obj=0 (未加载跳过); 格网格值 0 = 单位 0,
    # 但记录 HP=0 → jle 跳过 → 无绘制, 直达尾声。
    ebp = STACK - 0x1000
    esp = STACK - 0x2000
    uc.mem_write(ebp + 8, struct.pack("<I", CANVAS))
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EDX, edx_val)
    uc.mem_write(esp, struct.pack("<I", ret_addr))
    uc.emu_start(CAVE, stop_addr)
    return uc.reg_read(UC_X86_REG_ESP)


def main() -> bool:
    ok = True
    # v7.9 几何: 30x30 图标, 2 行 × 4 槽 (从下往上):
    #   ytop = sy-194 (行2/顶行), 行1(底行) y = ytop+31 = sy-163
    #   x0 = sx-55 (行宽 4*31-1=123px, 行中心 sx+6.5)
    #   行1: xx = x0 + offset1 + k*31, offset1 = (124-31*n1)>>1
    #        (n1=1..4 → 46/31/15/0; k = 行内激活序号, 空槽不占位)
    #   行2: xx = x0 + k*31 (从左到右)
    #   yy = ytop+31-row*31 (row = slot>>2) 不变
    x0, ytop = 320 - 55, 240 - 194

    def check_set(fi: int, slots: tuple) -> bool:
        expect, canvas, W, H = run_frame(fi, slots)
        row1 = sorted(s for s in slots if s < 4)
        row2 = sorted(s for s in slots if s >= 4)
        n1 = len(row1)
        off1 = (124 - 31 * n1) >> 1
        # 期望图标矩形: (slot, xx, yy)
        boxes = [(s, x0 + off1 + k * 31, ytop + 31)
                 for k, s in enumerate(row1)]
        boxes += [(s, x0 + k * 31, ytop) for k, s in enumerate(row2)]
        bad = 0
        covered = set()
        # 1) 图标矩形逐像素对照 ground truth
        for s, xx, yy in boxes:
            for ty in range(30):
                for tx in range(30):
                    exp = expect[ty][tx]
                    got = struct.unpack_from(
                        "<H", canvas, ((yy + ty) * 640 + xx + tx) * 2)[0]
                    if exp is not None and got != exp:
                        bad += 1
                    if exp is None and got != 0:
                        bad += 1
                    covered.add((xx + tx, yy + ty))
        # 2) 全行区域 (123x30 × 两行) 除图标矩形外全零
        #    (空槽透明 + 无幽灵块 + 步进/居中偏移正确 三合一)
        for row in (0, 1):
            ys = ytop + 31 - row * 31
            for ty in range(30):
                for tx in range(123):
                    if (x0 + tx, ys + ty) in covered:
                        continue
                    v = struct.unpack_from(
                        "<H", canvas, ((ys + ty) * 640 + x0 + tx) * 2)[0]
                    if v != 0:
                        bad += 1
        desc = ",".join(str(s) for s in slots)
        status = "[OK]" if bad == 0 else f"[FAIL] {bad} 像素不符"
        print(f"  frame{fi} slots({desc}) n1={n1} off1={off1}: {status}")
        return bad == 0

    # ── v7.9 居中布局用例 ──────────────────────────────────────
    ok &= check_set(76, (0,))            # 行1 单状态 → 居中 (x0+46)
    ok &= check_set(76, (2,))            # 行1 单状态 (非首槽) → 仍居中
    ok &= check_set(76, (0, 1))          # 两状态 → 中两格 (31/62)
    ok &= check_set(76, (1, 3))          # 两状态分散 → 紧凑排到中两格
    ok &= check_set(76, (0, 1, 2))       # 三状态 → 居中 (15/46/77)
    ok &= check_set(76, (0, 1, 2, 3))    # 四状态 → 满行 (0/31/62/93)
    ok &= check_set(90, (4,))            # 行2 单状态 → 左起 (x0+0)
    ok &= check_set(90, (4, 6))          # 行2 两状态分散 → 紧凑左起
    ok &= check_set(90, (0, 4, 5))       # 混合: 行1 居中 + 行2 左起
    ok &= check_set(90, (0, 1, 2, 3, 4, 5, 6, 7))  # 满两行

    # ── v7.8 尾声双路径 (hook 0x43A7A6 = 面板 switch bounds-ja) ──
    # STOP 映射在 CANVAS 区 (已映射, 全零), 执行到即停。
    STOP = CANVAS + 0x1000
    entry_esp = STACK - 0x2000
    # 路径1: edx=0 (有效面板状态) → 原 ja 未取 → ret 落回返回地址原值
    esp_after = run_tail(0, STOP, STOP)
    p1 = esp_after == entry_esp + 4
    print(f"  尾声路径1 (edx=0, 正常返回): "
          f"{'[OK]' if p1 else '[FAIL] esp=' + hex(esp_after)}")
    ok &= p1
    # 路径2: edx=0xFFFFFFFF (word_9D6C88=-1) → 原 ja 取 → 返回地址
    # 被 add [esp],0x112 调整 → ret 落回 STOP (= 返回地址+0x112)
    esp_after = run_tail(0xFFFFFFFF, STOP - 0x112, STOP)
    p2 = esp_after == entry_esp + 4
    print(f"  尾声路径2 (edx=-1, default 路径 +0x112): "
          f"{'[OK]' if p2 else '[FAIL] esp=' + hex(esp_after)}")
    ok &= p2

    print("[OK] unicorn 执行级验证全部通过 (行1 居中布局 + 空槽透明 + 尾声双路径)"
          if ok else "[FAIL] 存在差异")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
