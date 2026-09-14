# -*- coding: utf-8 -*-
"""war_hp_mp_bars — unicorn 执行级验证 (现代化样式 + 运行时画布宽)。

两层验证:
  ① 执行级像素对照: 用 unicorn 真跑 cave 字节码, 把 640/856 两种画布下
     血条/内力条覆盖的每个像素与"按样式规格手算的期望图"逐点比较 ——
     描边 / 2px 圆角 / 10 格格线 / 三段配色 / 内力条更细且紧贴血条,
     任何 modrm/SIB/立即数/跳转/rep movsw 错误都会在此暴露。
  ② 16:9 兼容: 行距与右边界必须跟随运行时 [0x4E7CC8] (原版 640 / 宽屏 856),
     包括右缘单位在 856 下画得出、在 640 下按原版挡掉。
"""
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EDX

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "tks_launcher_gui" / "patches" / "war_hp_mp_bars" / "patch.json"

CAVE = 0x00400000
CANVAS = 0x01000000
GLOB_LOW = 0x004E0000      # 0x4E7CC8 (画布宽) 所在页
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

# ─── 样式规格 (与 tests/test_war_hp_mp_bars_cave.py 保持一致) ───
BAR_W = 52
BAR_X_OFF = 20
BAR_Y_OFF = 132
HP_H, MP_H = 6, 4
RADIUS = 2
CAP = 40
CELL = 5
INNER = 50
C_BORDER, C_EMPTY, C_SEP = 0x1082, 0x2945, 0x18E3
C_HP_HI, C_HP_MID, C_HP_LO = 0x4ECC, 0xFD80, 0xE1C6
C_MP = 0x4D5F


def cave_bytes() -> bytes:
    import json
    return bytes.fromhex(
        json.loads(PATCH.read_text(encoding="utf-8"))["cave_code"].replace(" ", "")
    )


def run(width: int, *, unit_x: int = 500, unit_y: int = 400,
        hp: int = 100, hp_max: int = 100, mp: int = 100, mp_max: int = 100,
        cam_x: int = 0, cam_y: int = 0, menu: int = 0):
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
    uc.mem_write(A_UNITCNT, bytes([1]))
    uc.mem_write(A_UNITLIST, bytes([0]))
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
    uc.mem_write(A_MENU, struct.pack("<h", menu))
    esp = STACK - 0x2000
    uc.mem_write(esp, struct.pack("<I", STOP))  # cave 的返回地址 (hook 用 call 进入)
    uc.reg_write(UC_X86_REG_ESP, esp)
    # 被 hook 函数的帧: [ebp+8] = 第 1 个参数 = 画布基址
    frame = STACK - 0x4000
    uc.mem_write(frame + 8, struct.pack("<I", CANVAS))
    uc.reg_write(UC_X86_REG_EBP, frame)
    uc.emu_start(CAVE, STOP)
    return uc.mem_read(CANVAS, width * 480 * 2), uc


def pixel(canvas: bytes, width: int, x: int, y: int) -> int:
    off = (y * width + x) * 2
    if off < 0 or off + 2 > len(canvas):
        return -1
    return struct.unpack_from("<H", canvas, off)[0]


# ─── 期望图 (按样式规格手算) ───

def template(fill: int, color: int) -> list:
    """50 像素内区模板: 10×(4 列填充/底色 + 1 列格线)。"""
    t = [C_EMPTY] * INNER
    n = fill
    for g in range(CAP // (CELL - 1)):
        base = g * CELL
        for k in range(CELL - 1):
            if n > 0:
                t[base + k] = color
                n -= 1
        t[base + CELL - 1] = C_SEP
    return t


def inset(row: int, h: int) -> int:
    return RADIUS - min(min(row, h - 1 - row), RADIUS)


def draw_expected(canvas: bytearray, width: int, x0: int, y0: int, h: int,
                  fill: int, color: int) -> None:
    """按样式规格手算期望图。

    首/末行 = 整段描边 (上下边框); 中间行 = 左描边 + 内区内容 + 右描边;
    每行左右按 ins(r) 内缩 → 2px 圆角 (环外角像素透明)。
    内区内容 template[i] 的落点 = x0+1+i (与 ins 无关)。
    """
    t = template(fill, color)
    for r in range(h):
        ins = inset(r, h)
        row = y0 + r
        if r == 0 or r == h - 1:
            for c in range(ins, BAR_W - ins):
                off = (row * width + x0 + c) * 2
                canvas[off:off + 2] = struct.pack("<H", C_BORDER)
        else:
            for c in (x0 + ins, x0 + BAR_W - 1 - ins):
                off = (row * width + c) * 2
                canvas[off:off + 2] = struct.pack("<H", C_BORDER)
            for i in range(ins, INNER - ins):
                off = (row * width + x0 + 1 + i) * 2
                canvas[off:off + 2] = struct.pack("<H", t[i])


def fill_for(cur: int, mx: int) -> int:
    if mx <= 0:
        return 0
    f = cur * CAP // mx
    return max(1, min(CAP, f))


def hp_color(fill: int) -> int:
    return C_HP_HI if fill >= 24 else (C_HP_MID if fill >= 12 else C_HP_LO)


def check(name: str, cond: bool, extra: str = "") -> bool:
    print(f"  {name}: {'[OK]' if cond else '[FAIL]' + extra}")
    return cond


def compare(name: str, got: bytes, exp: bytearray, width: int, ok: bool) -> bool:
    """逐像素比较 (期望图以外全零 → 同时验证不漏画也不多画)。"""
    diff = 0
    first = None
    for off in range(0, len(exp), 2):
        g = struct.unpack_from("<H", got, off)[0]
        e = struct.unpack_from("<H", exp, off)[0]
        if g != e:
            diff += 1
            if first is None:
                first = off // 2
    det = f" 首个差异 @({first % width},{first // width})" if first is not None else ""
    return check(f"{name}: 逐像素对照", diff == 0, f" {diff} 处不同{det}") & ok


def main() -> bool:
    ok = True
    print("=== war_hp_mp_bars 现代化样式 + 画布宽度自适应 ===")
    width = 640
    x0, y0 = 500 - BAR_X_OFF, 400 - BAR_Y_OFF

    # ① 满血 / 半血 / 残血: 640 画布逐像素对照 (含描边/圆角/格线/配色)
    for hp, hp_max, label in ((100, 100, "满血"), (50, 100, "半血"), (20, 100, "残血")):
        canvas, _ = run(width, unit_x=500, unit_y=400, hp=hp, hp_max=hp_max,
                        mp=100, mp_max=100)
        exp = bytearray(width * 480 * 2)
        f = fill_for(hp, hp_max)
        draw_expected(exp, width, x0, y0, HP_H, f, hp_color(f))
        draw_expected(exp, width, x0, y0 + HP_H, MP_H, CAP, C_MP)
        ok = compare(f"{label} ({hp}/{hp_max}, 填充 {f}/40)", canvas, exp, width, ok)

    canvas, _ = run(width, unit_x=500, unit_y=400)

    # ② 圆角: 角部不写像素 (透明), 逐行内缩 2,1,0,0,1,2
    corners = [(x0 + 0, y0 + 0), (x0 + 1, y0 + 0), (x0 + 0, y0 + 1),
               (x0 + 51, y0 + 0), (x0 + 50, y0 + 0), (x0 + 51, y0 + 1),
               (x0 + 0, y0 + 5), (x0 + 1, y0 + 5)]
    ok &= check("圆角: 角部像素透明 (未写)",
                all(pixel(canvas, width, x, y) == 0 for x, y in corners))
    ok &= check("圆角: 第 0 行从 x0+2 起",
                pixel(canvas, width, x0 + 2, y0) == C_BORDER
                and pixel(canvas, width, x0 + 1, y0) == 0)
    ok &= check("圆角: 第 1 行从 x0+1 起",
                pixel(canvas, width, x0 + 1, y0 + 1) == C_BORDER)
    ok &= check("圆角: 第 2 行铺满整宽",
                pixel(canvas, width, x0, y0 + 2) == C_BORDER
                and pixel(canvas, width, x0 + 51, y0 + 2) == C_BORDER)
    ok &= check("描边: 顶边为连续 1px 边框线 (x0+2..x0+49)",
                all(pixel(canvas, width, x0 + c, y0) == C_BORDER
                    for c in range(2, 50)))

    # ③ 10 格: 格线位置 = x0+5k (k=1..10), 格内 4 列为血条色
    seps = [x0 + 5 * k for k in range(1, 11)]
    ok &= check("10 格: 分隔线位置/颜色",
                all(pixel(canvas, width, sx, y0 + 3) == C_SEP for sx in seps))
    ok &= check("10 格: 每格 4 列填充",
                all(pixel(canvas, width, x0 + 5 * k + 1, y0 + 3) == C_HP_HI
                    for k in range(10)))

    # ④ 内力条更细且紧贴血条下方 (首末行是描边, 中间行才是条色)
    hp_rows = [y for y in range(y0 - 3, y0 + 14)
               if pixel(canvas, width, x0 + 3, y) == C_HP_HI]
    mp_rows = [y for y in range(y0 - 3, y0 + 14)
               if pixel(canvas, width, x0 + 3, y) == C_MP]
    ok &= check(f"内力条更细 (填充分行 {MP_H - 2} < 血条 {HP_H - 2}, "
                f"总高 {MP_H} < {HP_H})",
                len(hp_rows) == HP_H - 2 and len(mp_rows) == MP_H - 2,
                f" hp={len(hp_rows)} mp={len(mp_rows)}")
    ok &= check("内力条紧贴血条下方 (下边框与上边框相邻, 无缝隙)",
                bool(hp_rows and mp_rows and mp_rows[0] == hp_rows[-1] + 3
                     and pixel(canvas, width, x0 + 3, y0 + 5) == C_BORDER
                     and pixel(canvas, width, x0 + 3, y0 + 6) == C_BORDER),
                f" hp={hp_rows} mp={mp_rows}")
    ok &= check("内力条配色 = 亮蓝",
                pixel(canvas, width, x0 + 21, y0 + HP_H + 1) == C_MP)

    # ⑤ 扣血后未填充段显示底色 (不是透明, 也不是血条色)
    c2, _ = run(width, unit_x=500, unit_y=400, hp=10, hp_max=100)
    ok &= check("残血: 未填充段为底色 (扣血可见)",
                pixel(c2, width, x0 + 46, y0 + 2) == C_EMPTY
                and pixel(c2, width, x0 + 3, y0 + 2) == C_HP_LO)

    # ⑥ 16:9 兼容: 856 画布逐像素对照 + 无 640 步长残影
    width = 856
    c8, _ = run(width, unit_x=500, unit_y=400, hp=100, hp_max=100,
                mp=100, mp_max=100)
    exp = bytearray(width * 480 * 2)
    draw_expected(exp, width, x0, y0, HP_H, CAP, C_HP_HI)
    draw_expected(exp, width, x0, y0 + HP_H, MP_H, CAP, C_MP)
    ok = compare("宽 856: 血条/内力条落点", c8, exp, width, ok)
    ok &= check("宽 856: 无 640 步长残影",
                pixel(c8, width, x0 - 216, y0 + 1) != C_HP_HI)

    # ⑦ 右边界: x0 = 600 → 600+51 = 651
    c640, _ = run(640, unit_x=600 + BAR_X_OFF, unit_y=400)     # x0 = 600
    c856, _ = run(856, unit_x=600 + BAR_X_OFF, unit_y=400)
    ok &= check("窄画布(640): x0=600 (越界) 按原版挡掉",
                pixel(c640, 640, 600, 268) == 0)
    ok &= check("宽画布(856): x0=600 正常绘制",
                pixel(c856, 856, 600, 270) == C_BORDER)
    c856b, _ = run(856, unit_x=804 + BAR_X_OFF, unit_y=400)
    ok &= check("宽画布(856): 最右合法 x0=804 画得出右边框",
                pixel(c856b, 856, 855, 270) == C_BORDER)
    c640n, _ = run(640, unit_x=5, unit_y=400)      # x0 = -15
    c856n, _ = run(856, unit_x=5, unit_y=400)
    ok &= check("x0<0 不写入 (640)", pixel(c640n, 640, 0, 268) != C_BORDER)
    ok &= check("x0<0 不写入 (856)", pixel(c856n, 856, 0, 268) != C_BORDER)

    # ⑧ 存活但极低血: 至少 1 列 (原版此情形整条不画)
    c1, _ = run(640, unit_x=500, unit_y=400, hp=1, hp_max=1000)
    ok &= check("极低血 (hp=1/1000): 可见 1 列红条",
                pixel(c1, 640, x0 + 1, 270) == C_HP_LO)

    # ⑨ 已阵亡单位 (hp<=0) 不画; 无内力 (mp=0) 不画内力条
    cdead, _ = run(640, unit_x=500, unit_y=400, hp=0, hp_max=100)
    ok &= check("hp<=0 不画", pixel(cdead, 640, x0 + 2, 270) == 0)
    # hp 是 word: 0xFFFF = -1 (有符号) 也必须跳过 (movsx 语义, 与原版一致)
    cneg, _ = run(640, unit_x=500, unit_y=400, hp=0xFFFF, hp_max=100)
    ok &= check("hp=0xFFFF (-1) 有符号判定为死 → 不画",
                pixel(cneg, 640, x0 + 2, 270) == 0)
    cnomp, _ = run(640, unit_x=500, unit_y=400, hp=100, hp_max=100, mp=0)
    ok &= check("mp=0 不画内力条",
                pixel(cnomp, 640, x0 + 21, y0 + HP_H + 1) == 0)

    # ⑩ 可见性: 条必须完整落在屏幕内 (不再把越界的条钳到屏幕边缘)
    #    y0 = sy-132 → sy=132 是最上合法位置 (y0=0)
    cy0, _ = run(640, unit_x=500, unit_y=132)
    exp = bytearray(640 * 480 * 2)
    draw_expected(exp, 640, x0, 0, HP_H, CAP, C_HP_HI)
    draw_expected(exp, 640, x0, HP_H, MP_H, CAP, C_MP)
    ok = compare("y0=0 (sy=132): 最上合法位置", cy0, exp, 640, ok)

    cneg1, _ = run(640, unit_x=500, unit_y=131)      # y0 = -1
    ok &= check("y0=-1: 不画 (旧版钳到 y=0, 会钉在屏幕顶边)",
                pixel(cneg1, 640, x0 + 3, 0) == 0)
    coff, _ = run(640, unit_x=500, unit_y=-500)      # 角色滚到屏幕上方外
    ok = compare("单位滚出屏幕上方: 全屏无残留",
                 coff, bytearray(640 * 480 * 2), 640, ok)

    cbot, _ = run(640, unit_x=500, unit_y=602)       # y0 = 470
    ok &= check("y0=470: 最下合法位置画到第 479 行 (内力条下边框)",
                pixel(cbot, 640, x0 + 3, 479) == C_BORDER
                and pixel(cbot, 640, x0 + 3, 477) == C_MP)
    cbot2, _ = run(640, unit_x=500, unit_y=603)      # y0 = 471
    ok &= check("y0=471: 越过下边界 → 不画",
                pixel(cbot2, 640, x0 + 3, 0) == 0)

    # ⑪ 尾声: 恢复 edx = movsx word[0x9D6C88], 栈平衡返回
    _, uc = run(640, unit_x=500, unit_y=400, menu=0x0012)
    ok &= check("尾声: edx 重放 = movsx word[9D6C88]",
                uc.reg_read(UC_X86_REG_EDX) == 0x0012,
                f" edx={uc.reg_read(UC_X86_REG_EDX):#x}")
    ok &= check("尾声: esp 平衡 (ret 后回到入口)",
                uc.reg_read(UC_X86_REG_ESP) == STACK - 0x2000 + 4)

    print("[OK] war_hp_mp_bars unicorn 执行级验证通过"
          if ok else "[FAIL] 存在差异")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
