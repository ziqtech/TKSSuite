# -*- coding: utf-8 -*-
"""war_hp_mp_bars v6 — cave 构建与校验 (现代化血条/内力条样式)。

【用户需求】血条/内力条从"纯红纯蓝矩形"改为现代样式:
  1. 带边框; 2. 至少 2px 圆角; 3. 一共分 10 个格子 (扣血时直观看出百分比);
  4. 内力条更细, 紧贴血条下方; 5. 现代游戏常见配色。

【几何】
  条宽 52px = 描边 + 50px 内区 + 描边 (1px 描边框)。
  内区 50 列 = 10 格 × 5 列 (每格 4 列填充 + 1 列格线), 满格 = 40 列填充。
  圆角半径 2px: 第 r 行左右各内缩 ins(r) = 2 - min(min(r, H-1-r), 2),
    血条 H=6 → ins = [2,1,0,0,1,2]; 内力条 H=4 → ins = [2,1,1,2]。
    圆角靠"行首尾不写像素"(透明) 实现, 不引入任何抠图/掩码。
  描边 = 闭合的 1px 环: 首行/末行整段描边色 (上下边), 中间行左右各 1px 描边,
    中段为内区内容 —— 圆角切掉的是环外的角像素, 环本身始终闭合。
  血条 52x6, x0 = sx-20 (与原 50 宽条 x0=sx-19 同一中心 sx+6), y0 = sy-132;
  内力条 52x4, x0 同, y0 = 血条底边 (y0+6) → 两条严格贴合。

【配色 (RGB565)】
  血条三段: ≥60% 绿 0x4ECC / ≥30% 琥珀 0xFD80 / 其余 红 0xE1C6
  内力条:   亮蓝 0x4D5F
  描边 0x1082 (近黑灰) / 空槽底 0x2945 (深灰) / 格线 0x18E3 (比底色更暗)

【16:9 兼容 (v5.1 起, 本版保留)】
  行距与右边界都读运行时 [0x4E7CC8] (视口/画布宽: 原版 640 / 宽屏补丁 856):
    - 行距 = 2*宽 (mov ecx,[0x4E7CC8] → V_WIDTH → imul eax,[ebp+V_WIDTH]);
    - 右边界 (无符号) x0 ≤ 宽-52。
  宽度写死会让宽屏下血条每行漂 216px 并丢掉右缘单位 → 必须运行时读。
  本版把两条的"行距/边界"合并到同一份例程 (原版两条各复制一份), 因此
  静态特征只剩 1 处 [0x4E7CC8] 读取, 宽屏正确性由 unicorn 执行级测试
  (test_war_hp_mp_bars_emu.py) 在 640/856 两种画布下逐像素验证。

【实现】每条先在栈上生成一行 50 像素"模板"(10 格: 填充/底色 + 格线),
  再逐行把模板的 [ins, 50-ins) 段用 rep movsw 拷进内区, 前后各补 1px 描边;
  首行/末行改为整段描边色 (rep stosw) 形成上下边框。

【为什么用 ebp 作帧基址】两条绘制共用一份 `call L_bar` 例程, call 会压栈,
  若沿用 [esp+slot] 寻址则被调方偏移全错 4 字节。故序言里读走 [ebp+8]
  (画布) 后立即 `mov ebp,esp` 改以 ebp 作帧基址, call/ret 不再影响局部变量。
  pushad 在尾声恢复原 ebp, 调用者帧不受影响。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    import capstone as _cs
except Exception:  # pragma: no cover
    _cs = None

# ─── 语义地址 (与原版 TKS.exe / 既有 cave 一致) ───
A_UNITCNT = 0x9DF882        # byte: 参战单位数
A_UNITLIST = 0x9D705A       # byte[]: 单位索引表
A_POSX = 0x9DF802           # word, 步进 4
A_POSY = 0x9DF804           # word, 步进 4
A_WAR_REC_BASE = 0x9D707A   # 单位战斗记录基址
A_CAMX, A_CAMY = 0x8242A8, 0x8242AC
A_WIDTH = 0x4E7CC8          # 视口/画布宽 (原版 640 / 宽屏 856)
A_MENU = 0x9D6C88           # 被替换指令的来源 (尾声重放)
REC_SIZE = 0x41E

# 战斗记录字段偏移
O_HP, O_MP, O_HPMAX, O_MPMAX = 0x0A, 0x0C, 0x10, 0x14

# ─── 几何 ───
BAR_W = 52                  # 1px 边 + 50px 内区 + 1px 边
BAR_X_OFF = 20              # x0 = sx - 20 (中心 sx+6, 与原 50 宽条一致)
BAR_Y_OFF = 132             # 血条顶 = sy - 132 (状态图标上方留 1px)
HP_H, MP_H = 6, 4
RADIUS = 2
CAP = 40                    # 满格填充列数 (10 格 × 4 列)
CELL = 5                    # 每格 5 列 = 4 列填充 + 1 列格线
INNER = CAP // (CELL - 1) * CELL    # 50 内区列数
assert INNER == 50 and INNER == (CAP // 4) * 5

# ─── 配色 (RGB565) ───
C_BORDER = 0x1082           # 描边 (近黑)
C_EMPTY = 0x2945            # 空槽底色 (深灰)
C_SEP = 0x18E3              # 格线 (比底色更暗)
C_HP_HI, C_HP_MID, C_HP_LO = 0x4ECC, 0xFD80, 0xE1C6   # 绿 / 琥珀 / 红
C_MP = 0x4D5F               # 亮蓝
HP_HI_FILL, HP_MID_FILL = 24, 12    # 60% / 30% (占 CAP=40 的阈值)

# ─── 栈局部 (帧基址 ebp) ───
V_CANVAS, V_WIDTH, V_CNT, V_IDX = 0x00, 0x04, 0x08, 0x0C
V_HP, V_MP, V_HPMX, V_MPMX = 0x10, 0x14, 0x18, 0x1C
V_FILL, V_COLOR, V_BH, V_YB = 0x20, 0x24, 0x28, 0x2C
V_ROW, V_X0, V_Y0, V_INS = 0x30, 0x34, 0x38, 0x3C
V_GRP = 0x40
TPL = 0x50                  # 50 words 模板 = 0x50 .. 0xB4
FRAME = 0xC0
assert TPL + INNER * 2 <= FRAME

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = 0, 1, 2, 3, 4, 5, 6, 7


class Asm:
    """仅覆盖本 cave 所需编码形式的微型汇编器。"""

    def __init__(self) -> None:
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fix32: list[tuple[int, str]] = []
        self.fix8: list[tuple[int, str]] = []

    def raw(self, *bs: int) -> None:
        self.code.extend(bs)

    def imm32(self, v: int) -> None:
        self.code += struct.pack("<i", v)

    def imm16(self, v: int) -> None:
        self.code += struct.pack("<H", v)

    def label(self, name: str) -> None:
        assert name not in self.labels, f"重复标签 {name}"
        self.labels[name] = len(self.code)

    def jmp(self, lab: str) -> None:
        self.raw(0xE9)
        self.fix32.append((len(self.code), lab))
        self.code += b"\x00" * 4

    def jmp8(self, lab: str) -> None:
        self.raw(0xEB)
        self.fix8.append((len(self.code), lab))
        self.code += b"\x00"

    def jcc(self, op: int, lab: str) -> None:
        self.raw(0x0F, op)
        self.fix32.append((len(self.code), lab))
        self.code += b"\x00" * 4

    def jcc8(self, op: int, lab: str) -> None:
        self.raw(op)
        self.fix8.append((len(self.code), lab))
        self.code += b"\x00"

    # ── [ebp+disp8] 形式 ──
    def mov_r_m_bp(self, reg: int, disp: int) -> None:      # mov r32,[ebp+disp8]
        assert 0 <= disp < 0x80
        self.raw(0x8B, 0x45 | (reg << 3), disp)

    def mov_m_r_bp(self, disp: int, reg: int) -> None:      # mov [ebp+disp8],r32
        assert 0 <= disp < 0x80
        self.raw(0x89, 0x45 | (reg << 3), disp)

    def mov_m_imm_bp(self, disp: int, val: int) -> None:    # mov dword[ebp+disp8],imm32
        assert 0 <= disp < 0x80
        self.raw(0xC7, 0x45, disp)
        self.imm32(val)

    def inc_m_bp(self, disp: int) -> None:                  # inc dword[ebp+disp8]
        self.raw(0xFF, 0x45, disp)

    def dec_m_bp(self, disp: int) -> None:                  # dec dword[ebp+disp8]
        self.raw(0xFF, 0x4D, disp)

    def add_r_m_bp(self, reg: int, disp: int) -> None:      # add r32,[ebp+disp8]
        self.raw(0x03, 0x45 | (reg << 3), disp)

    def imul_r_m_bp(self, reg: int, disp: int) -> None:     # imul r32,[ebp+disp8]
        self.raw(0x0F, 0xAF, 0x45 | (reg << 3), disp)

    def cmp_r_m_bp(self, reg: int, disp: int) -> None:      # cmp r32,[ebp+disp8]
        self.raw(0x3B, 0x45 | (reg << 3), disp)

    def lea_bp2(self, reg: int, idx: int, disp: int) -> None:   # lea reg,[ebp+idx*2+disp8]
        assert 0 <= disp < 0x80
        # mod=01 rm=100(SIB); SIB = scale×2 | index | base=ebp(101)
        self.raw(0x8D, 0x44 | (reg << 3), 0x40 | (idx << 3) | 0x05, disp)

    def lea_bp(self, reg: int, disp: int) -> None:          # lea reg,[ebp+disp8]
        assert 0 <= disp < 0x80
        self.raw(0x8D, 0x45 | (reg << 3), disp)

    # ── mov WORD PTR [edi], ax 等 ──
    def mov_ax_imm16(self, v: int) -> None:
        self.raw(0x66, 0xB8)
        self.imm16(v)

    def mov_mdi_ax(self) -> None:
        self.raw(0x66, 0x89, 0x07)

    def mov_mdi_disp_ax(self, disp: int) -> None:
        self.raw(0x66, 0x89, 0x47, disp)

    def resolve(self) -> bytes:
        out = bytearray(self.code)
        for pos, lab in self.fix32:
            out[pos:pos + 4] = struct.pack("<i", self.labels[lab] - (pos + 4))
        for pos, lab in self.fix8:
            rel = self.labels[lab] - (pos + 1)
            assert -128 <= rel <= 127, f"rel8 越界 ({lab}: {rel})"
            out[pos] = rel & 0xFF
        return bytes(out)


def build() -> bytes:
    a = Asm()
    r = a.raw

    # ════ 序言 ════
    r(0x60)                                   # pushad
    r(0x81, 0xEC); a.imm32(FRAME)             # sub esp,FRAME
    r(0xFC)                                   # cld
    r(0x8B, 0x45, 0x08)                       # mov eax,[ebp+8]   (原函数帧: 画布)
    r(0x89, 0xE5)                             # mov ebp,esp       (ebp 改作帧基址)
    a.mov_m_r_bp(V_CANVAS, RAX)
    r(0x8B, 0x0D); a.imm32(A_WIDTH)           # mov ecx,[0x4E7CC8] (运行时画布宽)
    a.mov_m_r_bp(V_WIDTH, RCX)
    r(0x0F, 0xB6, 0x0D); a.imm32(A_UNITCNT)   # movzx ecx,byte[0x9DF882]
    r(0x83, 0xF9, 0x20)                       # cmp ecx,0x20
    r(0x76, 0x02)                             # jbe +2
    r(0xB1, 0x20)                             # mov cl,0x20
    a.mov_m_r_bp(V_CNT, RCX)
    a.mov_m_imm_bp(V_IDX, 0)

    # ════ 单位循环 ════
    a.label("L_unit")
    a.mov_r_m_bp(RAX, V_IDX)
    a.mov_r_m_bp(RCX, V_CNT)
    r(0x39, 0xC8)                             # cmp eax,ecx
    a.jcc(0x8D, "L_done")                     # jge
    r(0x31, 0xD2)                             # xor edx,edx
    r(0x8A, 0x90); a.imm32(A_UNITLIST)        # mov dl,[eax+0x9D705A]
    r(0x83, 0xFA, 0x20)                       # cmp edx,0x20
    a.jcc(0x83, "L_next")                     # jae
    r(0x69, 0xC2); a.imm32(REC_SIZE)          # imul eax,edx,0x41E
    r(0x05); a.imm32(A_WAR_REC_BASE)          # add eax,0x9D707A
    # hp 用 movsx (有符号): 与原版一致 —— hp<=0 (含 0x8000..0xFFFF 垃圾值) 一律跳过
    r(0x0F, 0xBF, 0x48, O_HP)                 # movsx ecx,word[eax+0xA]
    a.mov_m_r_bp(V_HP, RCX)
    r(0x85, 0xC9)                             # test ecx,ecx
    a.jcc(0x8E, "L_next")                     # jle  (hp<=0: 非存活单位)
    r(0x0F, 0xB7, 0x48, O_MP)                 # movzx ecx,word[eax+0xC]
    a.mov_m_r_bp(V_MP, RCX)
    r(0x0F, 0xB7, 0x48, O_HPMAX)              # movzx ecx,word[eax+0x10]
    a.mov_m_r_bp(V_HPMX, RCX)
    r(0x0F, 0xB7, 0x48, O_MPMAX)              # movzx ecx,word[eax+0x14]
    a.mov_m_r_bp(V_MPMX, RCX)

    # x0 = movsx word[edx*4+POSX] - camx - 20
    r(0x0F, 0xBF, 0x04, 0x95); a.imm32(A_POSX)
    r(0x2B, 0x05); a.imm32(A_CAMX)            # sub eax,[0x8242A8]
    r(0x2D); a.imm32(BAR_X_OFF)               # sub eax,20
    a.mov_m_r_bp(V_X0, RAX)

    # y0 = movsx word[edx*4+POSY] - camy - 132  (负数钳 0)
    r(0x0F, 0xBF, 0x04, 0x95); a.imm32(A_POSY)
    r(0x2B, 0x05); a.imm32(A_CAMY)            # sub eax,[0x8242AC]
    r(0x2D); a.imm32(BAR_Y_OFF)               # sub eax,132
    r(0x79, 0x02)                             # jns +2
    r(0x31, 0xC0)                             # xor eax,eax
    a.mov_m_r_bp(V_Y0, RAX)

    # 水平: (unsigned)x0 <= 宽-52  (负 x0 亦被无符号比较挡掉)
    a.mov_r_m_bp(RCX, V_WIDTH)
    r(0x83, 0xE9, BAR_W)                      # sub ecx,BAR_W
    a.mov_r_m_bp(RAX, V_X0)
    r(0x39, 0xC8)                             # cmp eax,ecx
    a.jcc(0x87, "L_next")                     # ja
    # 垂直: y0 <= 480-(HP_H+MP_H)
    a.mov_r_m_bp(RAX, V_Y0)
    r(0x3D); a.imm32(480 - (HP_H + MP_H))     # cmp eax,470
    a.jcc(0x87, "L_next")                     # ja

    # ════ 生命条 ════
    a.mov_r_m_bp(RAX, V_HP)
    r(0x69, 0xC0); a.imm32(CAP)               # imul eax,eax,CAP
    a.mov_r_m_bp(RCX, V_HPMX)
    r(0x85, 0xC9)                             # test ecx,ecx
    a.jcc(0x8E, "L_mp")                       # hpmax<=0 → 不画血条
    r(0x31, 0xD2)                             # xor edx,edx
    r(0xF7, 0xF1)                             # div ecx  → eax = 填充列数
    r(0x85, 0xC0)                             # test eax,eax
    r(0x75, 0x05)                             # jnz +5
    r(0xB8); a.imm32(1)                       # 存活单位至少 1 列 (原版此处置 0 = 不画)
    r(0x83, 0xF8, CAP)                        # cmp eax,CAP
    r(0x76, 0x05)                             # jbe +5
    r(0xB8); a.imm32(CAP)
    a.mov_m_r_bp(V_FILL, RAX)
    # 三段配色
    r(0xB8); a.imm32(C_HP_HI)
    a.mov_r_m_bp(RCX, V_FILL)
    r(0x83, 0xF9, HP_HI_FILL)                 # cmp ecx,24
    a.jcc(0x83, "L_hpcol")                    # jae
    r(0xB8); a.imm32(C_HP_MID)
    r(0x83, 0xF9, HP_MID_FILL)                # cmp ecx,12
    a.jcc(0x83, "L_hpcol")                    # jae
    r(0xB8); a.imm32(C_HP_LO)
    a.label("L_hpcol")
    a.mov_m_r_bp(V_COLOR, RAX)
    a.mov_r_m_bp(RAX, V_Y0)
    a.mov_m_r_bp(V_YB, RAX)
    a.mov_m_imm_bp(V_BH, HP_H)
    r(0xE8); a.fix32.append((len(a.code), "L_bar")); a.code += b"\x00" * 4   # call L_bar

    # ════ 内力条 (更细, 紧贴血条下方) ════
    a.label("L_mp")
    a.mov_r_m_bp(RAX, V_MP)
    r(0x85, 0xC0)                             # test eax,eax
    a.jcc(0x8E, "L_next")                     # mp<=0 → 不画
    r(0x69, 0xC0); a.imm32(CAP)               # imul eax,eax,CAP
    a.mov_r_m_bp(RCX, V_MPMX)
    r(0x85, 0xC9)                             # test ecx,ecx
    a.jcc(0x8E, "L_next")                     # mpmax<=0 → 不画
    r(0x31, 0xD2)
    r(0xF7, 0xF1)                             # div ecx
    r(0x85, 0xC0)
    r(0x75, 0x05)
    r(0xB8); a.imm32(1)
    r(0x83, 0xF8, CAP)
    r(0x76, 0x05)
    r(0xB8); a.imm32(CAP)
    a.mov_m_r_bp(V_FILL, RAX)
    r(0xB8); a.imm32(C_MP)
    a.mov_m_r_bp(V_COLOR, RAX)
    a.mov_r_m_bp(RAX, V_Y0)
    r(0x05); a.imm32(HP_H)                    # add eax,6 → 顶边贴血条底边
    a.mov_m_r_bp(V_YB, RAX)
    a.mov_m_imm_bp(V_BH, MP_H)
    r(0xE8); a.fix32.append((len(a.code), "L_bar")); a.code += b"\x00" * 4   # call L_bar

    # ════ 下一条单位 ════
    a.label("L_next")
    a.inc_m_bp(V_IDX)
    a.jmp("L_unit")

    # ════ 尾声 (重放被替换的 movsx edx,[0x9D6C88]) ════
    a.label("L_done")
    r(0x81, 0xC4); a.imm32(FRAME)             # add esp,FRAME
    r(0x61)                                   # popad
    r(0x0F, 0xBF, 0x15); a.imm32(A_MENU)      # movsx edx,word[0x9D6C88]
    r(0xC3)                                   # ret

    # ════════ 画一条 (参数: V_YB=顶, V_BH=高, V_FILL, V_COLOR; x0 用 V_X0) ════════
    a.label("L_bar")
    # ① 生成一行 50 像素内区模板 (10 格 × (4 列填充 + 1 列格线))
    a.lea_bp(RDI, TPL)                        # lea edi,[ebp+TPL]
    a.mov_r_m_bp(RCX, V_FILL)                 # ecx = 剩余填充列数
    a.mov_m_imm_bp(V_GRP, 10)                 # 10 格
    a.label("L_grp")
    r(0xBA); a.imm32(CELL - 1)                # mov edx,4  (每格 4 列填充)
    a.label("L_fill")
    r(0x85, 0xC9)                             # test ecx,ecx
    a.jcc8(0x74, "L_empty")                   # jz
    a.mov_r_m_bp(RAX, V_COLOR)
    a.mov_mdi_ax()
    r(0x49)                                   # dec ecx
    a.jmp8("L_put")
    a.label("L_empty")
    a.mov_ax_imm16(C_EMPTY)
    a.mov_mdi_ax()
    a.label("L_put")
    r(0x83, 0xC7, 0x02)                       # add edi,2
    r(0x4A)                                   # dec edx
    a.jcc8(0x75, "L_fill")                    # jnz
    a.mov_ax_imm16(C_SEP)                     # 格线
    a.mov_mdi_ax()
    r(0x83, 0xC7, 0x02)                       # add edi,2
    a.dec_m_bp(V_GRP)
    a.jcc8(0x75, "L_grp")                     # jnz
    # ② 逐行绘制 (圆角 = 行首尾不写; 行距读运行时宽)
    a.mov_m_imm_bp(V_ROW, 0)
    a.label("L_row")
    # ins = 2 - min(min(row, H-1-row), 2)
    a.mov_r_m_bp(RAX, V_ROW)
    a.mov_r_m_bp(RCX, V_BH)
    r(0x49)                                   # dec ecx   → H-1
    r(0x29, 0xC1)                             # sub ecx,eax → H-1-row
    r(0x39, 0xC8)                             # cmp eax,ecx
    r(0x7E, 0x02)                             # jle +2
    r(0x89, 0xC8)                             # mov eax,ecx
    r(0x83, 0xF8, RADIUS)                     # cmp eax,2
    r(0x7E, 0x05)                             # jle +5
    r(0xB8); a.imm32(RADIUS)                  # mov eax,2
    r(0xB9); a.imm32(RADIUS)                  # mov ecx,2
    r(0x29, 0xC1)                             # sub ecx,eax → ins
    a.mov_m_r_bp(V_INS, RCX)
    # edi = canvas + 2*((yb+row)*宽 + x0 + ins)
    a.mov_r_m_bp(RAX, V_YB)
    a.add_r_m_bp(RAX, V_ROW)                  # add eax,[ebp+V_ROW]
    a.imul_r_m_bp(RAX, V_WIDTH)               # imul eax,[ebp+V_WIDTH]  ← 运行时宽
    a.add_r_m_bp(RAX, V_X0)
    r(0x03, 0xC1)                             # add eax,ecx
    a.mov_r_m_bp(RDX, V_CANVAS)
    r(0x8D, 0x3C, 0x42)                       # lea edi,[edx+eax*2]
    # 首行/末行 → 整段描边色 (上下边框); 其余 → 左右描边 + 内容
    a.mov_r_m_bp(RAX, V_ROW)
    r(0x85, 0xC0)                             # test eax,eax
    a.jcc8(0x74, "L_brow")                    # jz
    a.mov_r_m_bp(RAX, V_BH)
    r(0x48)                                   # dec eax
    a.cmp_r_m_bp(RAX, V_ROW)                  # cmp eax,[ebp+V_ROW]
    a.jcc8(0x74, "L_brow")                    # je
    # ── 中间行: 左描边 + 内容 + 右描边 ──
    a.mov_ax_imm16(C_BORDER)
    a.mov_mdi_ax()                            # 左描边 (x0+ins)
    r(0x83, 0xC7, 0x02)                       # add edi,2
    a.lea_bp2(RSI, RCX, TPL)                  # src = 模板 + ins*2 (ecx = ins)
    r(0xBA); a.imm32(INNER)                   # mov edx,50
    r(0x29, 0xCA)                             # sub edx,ecx
    r(0x29, 0xCA)                             # sub edx,ecx → 50-2*ins
    r(0x89, 0xD1)                             # mov ecx,edx
    r(0xF3, 0x66, 0xA5)                       # rep movsw
    a.mov_ax_imm16(C_BORDER)
    a.mov_mdi_ax()                            # 右描边 (edi 已指向 x0+51-ins)
    a.jmp8("L_rown")
    # ── 首行/末行: 整段描边色 (上下边框) ──
    a.label("L_brow")
    a.mov_ax_imm16(C_BORDER)
    r(0xBA); a.imm32(BAR_W)                   # mov edx,52
    r(0x29, 0xCA)                             # sub edx,ecx
    r(0x29, 0xCA)                             # sub edx,ecx
    r(0x89, 0xD1)                             # mov ecx,edx
    r(0xF3, 0x66, 0xAB)                       # rep stosw  (ecx = ins)
    a.label("L_rown")
    a.inc_m_bp(V_ROW)
    a.mov_r_m_bp(RAX, V_ROW)
    a.cmp_r_m_bp(RAX, V_BH)                   # cmp eax,[ebp+V_BH]
    a.jcc(0x82, "L_row")                      # jb (回边距离 > rel8)
    r(0xC3)                                   # ret

    return a.resolve()


def cave_bytes() -> bytes:
    return build()


def cave_hex() -> str:
    return cave_bytes().hex(" ").upper()


# ────────────────────────────────────────────────────────────────
# 校验
# ────────────────────────────────────────────────────────────────


def _disasm(code: bytes):
    md = _cs.Cs(_cs.CS_ARCH_X86, _cs.CS_MODE_32)
    return list(md.disasm(code, 0))


def test_disassemble_clean() -> None:
    assert _cs is not None, "需要 capstone"
    code = cave_bytes()
    insns = _disasm(code)
    covered = sum(i.size for i in insns)
    assert covered == len(code), f"存在无法对齐解码的字节 ({covered}/{len(code)})"
    assert insns[-1].mnemonic == "ret"


def test_key_semantics_present() -> None:
    assert _cs is not None, "需要 capstone"
    code = cave_bytes()
    text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in _disasm(code)).lower()
    for needle in (
        "pushal",                                   # capstone 渲染 pushad 为 pushal
        "popal",
        "mov ecx, dword ptr [0x4e7cc8]",            # 运行时画布宽
        "imul eax, dword ptr [ebp +",               # 行距 = 宽 * ...
        "word ptr [edx*4 + 0x9df802]",              # 坐标 ×4 寻址
        "word ptr [edx*4 + 0x9df804]",
        "dword ptr [0x8242a8]", "dword ptr [0x8242ac]",   # 相机 X/Y
        "0x9d707a",                                 # 记录基址
        "movsx ecx, word ptr [eax + 0xa]",          # hp 有符号读 (负数跳过)
        "div ecx",                                  # 百分比
        "rep movsw",                                # 行 blit
        "cmp eax, 0x1d6",                           # 垂直边界 y0 <= 470
        "movsx edx, word ptr [0x9d6c88]",           # 尾声重放被替换指令
        "ret",
    ):
        assert needle in text, needle
    # 三段配色立即数必须出现
    for c in (C_HP_HI, C_HP_MID, C_HP_LO, C_MP, C_BORDER, C_EMPTY, C_SEP):
        assert f"{c:#06x}" in text, f"缺失配色 {c:#06x}"
    # 10 格: 每格 4 列填充 (mov edx,4) + 10 次格线 (0x18e3) + 1 描边列
    assert text.count(f"mov ax, {C_SEP:#06x}") == 1
    assert text.count("mov edx, 4") == 1
    assert text.count(f"mov dword ptr [ebp + {V_GRP:#x}], 0xa") == 1


def test_no_hardcoded_width() -> None:
    """宽屏兼容红线: 不得出现 640 行距硬编码。"""
    assert _cs is not None, "需要 capstone"
    code = cave_bytes()
    text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in _disasm(code)).lower()
    assert "0x4e7cc8" in text, "必须读运行时画布宽"
    # 唯一的行距合成 = imul eax,[ebp + V_WIDTH] ([ebp+4], 由 [0x4E7CC8] 载入)
    assert text.count("imul eax, dword ptr [ebp + 4]") == 1, \
        "行距必须由运行时画布宽合成且只有一处"
    # 640 (0x280) 不得作为行距/边界立即数出现
    for bad in ("0x280", "0x27f", "0x270", "0x24f"):
        assert bad not in text, f"疑似 640 系硬编码 {bad}"
    assert "shl" not in text, "不应再有 y*640 的移位合成"


def test_frame_budget() -> None:
    code = cave_bytes()
    assert len(code) <= 1024, len(code)


def test_patch_json_matches_builder() -> None:
    import json
    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "patches" / "war_hp_mp_bars" / "patch.json").read_text("utf-8")
    )
    norm = lambda s: [t.upper() for t in s.split()]  # noqa: E731
    assert norm(raw["cave_code"]) == norm(cave_hex()), \
        "patch.json cave_code 与构建器输出不一致"
    assert raw["type"] == "cave_hook" and raw["id"] == "war_hp_mp_bars"
    assert raw["hook_pattern"] == "0F BF 15 88 6C 9D 00 83 FA 2B"
    assert raw["hook_size"] == 7 and raw["hook_expect_count"] == 1
    assert raw["hook_offset"] == 0


# ────────────────────────────────────────────────────────────────
# cave_code.py / patch.json 生成
# ────────────────────────────────────────────────────────────────

PATCH_DIR = Path(__file__).resolve().parents[1] / "patches" / "war_hp_mp_bars"

CAVE_PY_DOC = '''# -*- coding: utf-8 -*-
"""
战场头顶血条内力条 (war_hp_mp_bars) — cave 带注释机器码源

战场头顶血条内力条：所有存活单位头顶居中显示 52x6 血条(1px 描边环 + 2px 圆角 + 三段配色:
≥60% 绿 / ≥30% 琥珀 / 其余红) + 52x4 内力条(亮蓝, 更细且紧贴血条下方),
内区 50 列 = 10 格 × (4 列填充 + 1 列格线), 按当前待机帧精灵几何精确锚定头顶。

完整版本历史与逆向细节见 patch.json 的 _comment 字段。

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 由 tks_launcher_gui/tests/test_war_hp_mp_bars_cave.py --write 生成。

v6 (现代化样式): 由 50x5 纯红/纯蓝矩形改为 52x6(血) + 52x4(内力) 现代条 ——
  1px 描边 / 2px 圆角(逐行内缩 2,1,0,0,1,2 与 2,1,1,2) / 内分 10 格
  (每格 4 列填充 + 1 列格线, 满格 40 列) / 三段配色 + 亮蓝内力;
  HP 未满 1 格的存活单位至少保留 1 列 (原版此情形整条不画)。
v5.1 (16:9 兼容): 行步长与右边界改为运行时读取 [0x4E7CC8]
  (视口/画布宽: 原版 640 / 宽屏补丁 856)。宽度硬编码会让宽屏下每行漂 216px
  并丢掉右缘单位的条。
"""
'''

# patch.json 的 _comment / desc (与 cave 行为同步维护)
PATCH_COMMENT = (
    "战场单位头顶 HP/MP 比例条 v6 (cave_hook)。"
    "v6 (现代化样式): 由 50x5 纯红/纯蓝矩形改为描边+圆角+10 格分段条。"
    "几何: 条宽 52 = 1px 描边环 + 50px 内区; 内区 50 列 = 10 格 × (4 列填充 + 1 列格线), "
    "满格 40 列填充; 圆角半径 2px (逐行左右内缩 2,1,0,0,1,2), 圆角切掉的是环外角像素, "
    "描边环始终闭合 (首/末行整段描边色 = 上下边, 中间行左右各 1px)。"
    "血条 52x6 三段配色 (≥60% 绿 0x4ECC / ≥30% 琥珀 0xFD80 / 其余红 0xE1C6); "
    "内力条 52x4 (亮蓝 0x4D5F), 顶边 = 血条底边 (y0+6), 更细且紧贴; "
    "空槽底色 0x2945, 格线 0x18E3, 描边 0x1082。"
    "位置: x0 = sx-20 (中心 sx+6, 与原 50 宽条同一中心), 血条 y0 = sy-132, 总高 10px 与原版一致; "
    "y0<0 钳 0, y0>470 跳过; 右边界 (无符号) x0 ≤ 宽-52 (负 x0 一并挡掉)。"
    "等价性: hp>0 且 hpmax>0 才画血条, mp>0 且 mpmax>0 才画内力条 —— 与原版一致; "
    "唯一行为差异: 存活单位血条不足 1 格 (hp*40/hpmax == 0) 时保留 1 列, 原版此情形整条不画。"
    "v5.1 (16:9 兼容): 行步长与右边界改读运行时 [0x4E7CC8] (视口/画布宽: 原版 640 / 宽屏补丁 856) —— "
    "宽度写死会让宽屏下每行漂 216px 并丢掉右缘单位的条。"
    "实现: 序言读走 [ebp+8] (画布) 后 `mov ebp,esp` 改以 ebp 作帧基址, 使共用 `call L_bar` 例程"
    "不受 call 压栈影响 (旧版两条各复制一份, 本版合并); 先按填充数在栈上生成 50 像素模板, "
    "再逐行 `rep movsw` 拷内区 + 补左右描边, 首/末行 `rep stosw` 整段描边。"
    "层级: hook 回到 sub_43A050 @0x43A79C — 32x32 单位绘制循环 (阴影+身体精灵) 之后、"
    "面板 switch(word_9D6C88) 之前 → 条高于人物精灵、低于战斗菜单/信息面板/回合表; "
    "被替换 7 字节 0F BF 15 88 6C 9D 00, cave 尾部 popad 后重放。无 call 之外的控制流依赖, "
    "pushad/popad 保栈。"
    "验证: tests/test_war_hp_mp_bars_cave.py (capstone 全量解码 + 语义/配色/宽屏红线断言) + "
    "tests/test_war_hp_mp_bars_emu.py (unicorn 执行级逐像素对照: 640/856 双画布、三段配色、"
    "圆角/格线/内力条贴合、右缘与负坐标边界、hp<=0/mp=0 不画、尾声 edx/esp 平衡)。"
)
PATCH_DESC = (
    "战场头顶血条内力条：所有存活单位头顶居中显示 52x6 三段配色血条"
    "(≥60% 绿 / ≥30% 琥珀 / 其余红) + 52x4 亮蓝内力条(更细、紧贴血条下方), "
    "1px 描边 + 2px 圆角 + 内分 10 格 (每格 4 列填充 + 1 列格线), 扣血后空格显示底色, "
    "按当前待机帧精灵几何精确锚定头顶"
)


def render_cave_py(code: bytes, doc: str = CAVE_PY_DOC) -> str:
    assert _cs is not None
    lines = ["CAVE_CODE = bytes(["]
    off = 0
    for ins in _disasm(code):
        if ins.address != off:
            raise RuntimeError(f"解码在 {off:#x} 处中断")
        bs = ", ".join(f"0x{b:02X}" for b in ins.bytes)
        lines.append(f"    {bs},{' ' * max(1, 62 - len(bs))}"
                     f"# {off:04X}  {ins.mnemonic} {ins.op_str}".rstrip())
        off += ins.size
    if off != len(code):
        raise RuntimeError(f"尾部残留 {off:#x}")
    lines.append("])")
    return doc + "\n".join(lines) + "\n"


def render_patch_json_cave(code: bytes) -> str:
    return " ".join(f"{b:02x}" for b in code)


def write_all() -> None:
    import json
    code = cave_bytes()
    py = PATCH_DIR / "cave_code.py"
    py.write_text(render_cave_py(code), encoding="utf-8")
    pj = PATCH_DIR / "patch.json"
    raw = json.loads(pj.read_text(encoding="utf-8"))
    raw["cave_code"] = render_patch_json_cave(code)
    raw["_comment"] = PATCH_COMMENT
    raw["desc"] = PATCH_DESC
    pj.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n",
                  encoding="utf-8")
    print(f"已写入 {py.name} / {pj.name}  ({len(code)} bytes)")


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_all()
    code = cave_bytes()
    print(f"total {len(code)} bytes")
    test_disassemble_clean()
    test_key_semantics_present()
    test_no_hardcoded_width()
    test_frame_budget()
    test_patch_json_matches_builder()
    print("[OK] 解码 / 语义 / 宽屏红线 / patch.json 一致性通过")
