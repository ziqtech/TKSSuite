# -*- coding: utf-8 -*-
"""war_hp_mp_bars — unicorn 执行级验证: 绘制步长/右边界跟随运行时画布宽度。

背景: 本补丁早于 16:9 宽屏补丁, 原来把画布行距硬编码成 640、右边界硬编码 591。
宽屏补丁把画布拓宽到 856 后, 血条/内力条会按 640 换行 → 每行错位 216px (显示异常)。
修复: 行距改读 [0x4E7CC8] (视口/画布宽, 原版 640 / 宽屏 856),
      右边界改 `(无符号)(barX+49) <= [0x4E7CC8]` —— 与原版 `barX∈[0,591]` 等价。

本测试用 unicorn 真执行 cave 字节码, 对 640 与 856 两种画布宽度分别断言像素落点,
并验证右边界在宽画布下放宽、窄画布下仍按原版挡掉。
"""
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESP

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "tks_launcher_gui" / "patches" / "war_hp_mp_bars" / "patch.json"

CAVE = 0x00400000
CANVAS = 0x01000000
GLOB_LOW = 0x004E0000      # 0x4E7CC8 (视口/画布宽) 所在页
GLOB_LOW_SZ = 0x00100000
GLOB_HIGH = 0x00800000     # 0x8242xx / 0x9d6xxx / 0x9dfxxx
GLOB_HIGH_SZ = 0x00400000
STACK = 0x7FF00000
STOP = 0x00100000

A_UNITCNT = 0x9DF882       # 单位数 (byte)
A_UNITLIST = 0x9D705A      # 单位索引表 (byte[])
A_POSX = 0x9DF802          # word, 步进 4 (X)
A_POSY = 0x9DF804          # word, 步进 4 (Y)
A_WAR_REC_BASE = 0x9D707A  # 单位记录, 步进 0x41E
A_CAMX, A_CAMY = 0x8242A8, 0x8242AC
A_WIDTH = 0x4E7CC8         # 视口/画布宽
A_MENU = 0x9D6C88          # 尾声重放 movsx 的来源
REC_SIZE = 0x41E

HP_COLOR = 0xF800
MP_COLOR = 0x001F


def cave_bytes() -> bytes:
    import json
    return bytes.fromhex(json.loads(PATCH.read_text(encoding="utf-8"))["cave_code"].replace(" ", ""))


def run(width: int, *, unit_x: int = 500, unit_y: int = 400,
        hp: int = 100, hp_max: int = 100, mp: int = 100, mp_max: int = 100,
        cam_x: int = 0, cam_y: int = 0):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE, 0x10000)
    uc.mem_map(STOP, 0x1000)
    uc.mem_map(GLOB_LOW, GLOB_LOW_SZ)
    uc.mem_map(GLOB_HIGH, GLOB_HIGH_SZ)
    uc.mem_map(CANVAS, 0x200000)
    uc.mem_map(STACK - 0x100000, 0x200000)
    code = cave_bytes()
    uc.mem_write(CAVE, code)
    uc.mem_write(CAVE + len(code), b"\xC3")     # 兜底 ret
    # 全局环境
    uc.mem_write(A_UNITCNT, bytes([1]))
    uc.mem_write(A_UNITLIST, bytes([0]))        # 单位 0
    uc.mem_write(A_POSX, struct.pack("<h", unit_x))
    uc.mem_write(A_POSY, struct.pack("<h", unit_y))
    rec = A_WAR_REC_BASE
    uc.mem_write(rec + 0xA, struct.pack("<H", hp))
    uc.mem_write(rec + 0xC, struct.pack("<H", mp))
    uc.mem_write(rec + 0x10, struct.pack("<H", hp_max))
    uc.mem_write(rec + 0x14, struct.pack("<H", mp_max))
    uc.mem_write(A_CAMX, struct.pack("<I", cam_x))
    uc.mem_write(A_CAMY, struct.pack("<I", cam_y))
    uc.mem_write(A_WIDTH, struct.pack("<I", width))
    uc.mem_write(A_MENU, struct.pack("<h", 0))
    esp = STACK - 0x2000
    uc.mem_write(esp, struct.pack("<I", STOP))  # cave 的返回地址 (hook 用 call 进入)
    uc.reg_write(UC_X86_REG_ESP, esp)
    # 被 hook 函数的帧: [ebp+8] = 第 1 个参数 = 画布基址 (cave 的 esi 来源)
    frame = STACK - 0x4000
    uc.mem_write(frame + 8, struct.pack("<I", CANVAS))
    uc.reg_write(UC_X86_REG_EBP, frame)
    uc.emu_start(CAVE, STOP)
    return uc.mem_read(CANVAS, width * 480 * 2), uc


def pixel(canvas: bytes, width: int, x: int, y: int) -> int:
    off = (y * width + x) * 2
    return struct.unpack_from("<H", canvas, off)[0]


def check(name: str, cond: bool, extra: str = "") -> bool:
    print(f"  {name}: {'[OK]' if cond else '[FAIL]' + extra}")
    return cond


def main() -> bool:
    ok = True
    print("=== war_hp_mp_bars 画布宽度自适应 ===")
    # 静态回归: 不得再出现硬编码 640 步长 / 591 边界
    code = cave_bytes()
    assert bytes.fromhex("8BCFC1E709C1E10703F9") not in code, "仍有硬编码 y*640 步长"
    assert bytes.fromhex("81FA4F0200007F2D") not in code, "仍有硬编码右边界 591"
    assert code.count(bytes.fromhex("0FAF3DC87C4E00")) == 2, "两处行步长应读 [0x4E7CC8]"
    assert code.count(bytes.fromhex("A1C87C4E0083E83139C2772D")) == 2, "两处右边界应读 [0x4E7CC8]"
    print("  静态: 行步长/右边界均已改为运行时画布宽: [OK]")
    # 单位 WORLD(500,400), 视口原点 0 → 屏幕 (500,400);
    # barX = 500-19 = 481, HP barY = 400-132 = 268, MP barY = 400-126 = 274
    for width in (640, 856):
        canvas, _ = run(width, unit_x=500, unit_y=400)
        hp_ok = all(pixel(canvas, width, 481 + i, 268) == HP_COLOR for i in range(50))
        mp_ok = all(pixel(canvas, width, 481 + i, 274) == MP_COLOR for i in range(50))
        hp_rows = [all(pixel(canvas, width, 481 + i, 268 + r) == HP_COLOR for i in range(50))
                   for r in range(5)]
        ok &= check(f"宽 {width}: HP 条 50x5 落点", hp_ok and all(hp_rows),
                    f" hp={hp_ok} rows={hp_rows}")
        ok &= check(f"宽 {width}: MP 条 50x5 落点", mp_ok)
        # 若仍按 640 换行, 856 画布上第 2 行会落到 268*856+481-216 (=下一行左移 216)
        if width == 856:
            wrong = pixel(canvas, width, 481 - 216, 269)
            ok &= check("宽 856: 无 640 步长残影", wrong != HP_COLOR, f" got={wrong:#06x}")

    # 右边界: barX=600 → 600+49=649
    c640, _ = run(640, unit_x=619, unit_y=400)     # barX = 600
    c856, _ = run(856, unit_x=619, unit_y=400)
    ok &= check("窄画布(640): barX=600 仍按原版挡掉",
                pixel(c640, 640, 600, 268) == 0)
    ok &= check("宽画布(856): barX=600 正常绘制",
                pixel(c856, 856, 600, 268) == HP_COLOR)
    # 负 X (单位在视口左侧): 两种宽度都必须挡掉 (无符号比较兜住)
    c640n, _ = run(640, unit_x=5, unit_y=400)      # barX = -14
    c856n, _ = run(856, unit_x=5, unit_y=400)
    ok &= check("barX<0 不写入 (640)", pixel(c640n, 640, 0, 268) != HP_COLOR)
    ok &= check("barX<0 不写入 (856)", pixel(c856n, 856, 0, 268) != HP_COLOR)

    print("[OK] war_hp_mp_bars unicorn 执行级验证通过" if ok else "[FAIL] 存在差异")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
