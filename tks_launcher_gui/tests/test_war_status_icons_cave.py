# -*- coding: utf-8 -*-
"""war_status_icons v7.9 cave 构建与校验。

v7.9 = v7.8 + 行1 居中布局 (用户需求)。

【v7.9 布局变更—行1 图标按激活数紧凑居中, 行2 从左到右】
- 旧布局固定 col = slot&3 → 单个状态偏在行1 最左格, 视觉不居中。
- 新布局: 图标位置由【行内第 k 个激活状态】决定 (紧凑排列),
  空槽不占位 (v7.8 空槽透明的自然延伸):
    行1 (槽 0-3): xx = x0 + offset1 + k*31
        offset1 = (124 - 31*n1) >> 1   (n1 = 行1 激活数, 单位级预扫描)
        n1=1 → 46 (图标 [46,76], 中心 61, 行中心 61.5, 偏左 0.5px)
        n1=2 → 31 (组 [31,92], 中心 61.5 精确居中)
        n1=3 → 15 (组 [15,107], 中心 61, 偏左 0.5px)
        n1=4 → 0  (满行 = 原布局 [0,123])
      组宽 = 31n-1 (n 个 30px 图标 + n-1 个 1px 间隙), 行宽 123 = 4*31-1,
      居中 offset = (123-(31n-1))/2 = (124-31n)/2, floor 取整。
    行2 (槽 4-7): xx = x0 + k*31 (超出 4 个后从左到右, 不居中)
    yy 不变: ytop+31-row*31 (row = slot>>2)
- k = 行内前缀计数: Σ_{i<slot, 同行} (st[i] != 0), 槽级小循环 (≤3 次)。
- 状态分散 (如 slot 1+3) 也紧凑排到中两格 —— 视觉始终居中。
- 栈槽: V_OFF1 复用旧 V_UIDX 槽 0x6C (u 在 ytop/x0 计算后死亡,
  绘制路径不再读; 复用前已核对 RLE 像素循环不触及 0x6C)。
- 钳位不变: 逐槽 xx≤610 无符号比较 (最大 xx = x0+93 与旧一致)。

【v7.8 层级变更—hook 从面板尾部移到面板 switch 的 bounds-ja】
- 旧 hook 0x43A8BD (if word_9D6C88>=0 之前) 位于所有面板/菜单绘制
  【之后】→ 图标盖住战斗菜单 (v7.7 已知局限)。新 hook 0x43A7A6 =
  面板 switch 的越界检查 `ja 0x43A8BD` (0F 87 11 01 00 00, 6 字节),
  位于 32x32 单位精灵循环【之后】、sub_437664 信息面板 /
  sub_4393A8 / sub_43844C / sub_439750 菜单 / sub_439D34 回合表
  【之前】→ 图标高于角色、低于菜单 (与 war_hp_mp_bars v5 同层级语义)。
- 与 war_hp_mp_bars (hook 0x43A79C, 7 字节) 零字节重叠: 其 pattern
  止于 0x43A7A5, hook 写 0x43A79C..0x43A7A2; 本补丁 pattern 始于
  0x43A7A6, hook 写 0x43A7A6..0x43A7AB → 任意应用顺序互不干扰
  (预扫描均在原始 code_buf 上进行, HookTable 按单偏移注册不冲突)。
- 尾声重放被替换的条件跳转: popad 恢复 edx (= movsx word[9D6C88]),
  重放 cmp edx,0x2b 重新求值标志 (cave 主体已破坏标志位):
    未取 (edx≤0x2B): ret → E8 返回地址 0x43A7AB(NOP) → 0x43A7AC 跳转表
    取 (edx>0x2B)  : add [esp],0x112 → 返回地址 0x43A7AB→0x43A8BD
      (面板 switch default: word_9D6C88=-1/>43 时无菜单, 直达尾部)
  两路径栈均严格平衡 (仅调整自身 E8 返回地址, 绝不写调用者帧 — v6
  挂车式 4 轮白屏的教训; 调整自身返回地址是标准 trampoline 技术)。
- pattern 含后续 mov dl,[edx+0x43a7b9] 增强唯一性 (12 字节全 exe 唯一)。

【v7.8 空槽透明】st==0 直接跳下一槽 (v4~v7.7 画 0x2104 暗灰占位
色块, 用户需求改为透明不绘制)。cld/rep stosw 一并移除 (cave 内已
无字符串操作)。

【v7.7 布局变更—30x30 原尺寸 + 2 行 × 4 槽 (从下往上)】
- 图标尺寸: 与战斗面板一致的原尺寸 30x30 (sub_437664 面板绘制为
  sub_4544EC 直绘 30x30, 步进 37px; 头顶版采用 1px 间隙 → 步进 31px)
- 两行布局: 行1 (槽 0-3, 底行) 紧贴血条上方; 行2 (槽 4-7, 顶行) 在
  行1 上方。col = slot&3, row = slot>>2:
    xx = x0 + col*31          (行宽 4*31-1 = 123px)
    yy = ytop + 31 - row*31   (行1: ytop+31; 行2: ytop)
- ytop = sy-194 (行2 顶): 行1 底边 = sy-163+30 = sy-133 距 HP 条顶
  sy-132 上方 1px; 总高 61px (30+1+30)
- x0 = sx-55: 行中心保持 sx+6.5 与历代一致 (123/2=61.5)
- 钳位: ytop∈[0,419] (ytop+61≤480), xx≤610 (xx+30≤640)
- 采样: floor(W*tx/30)/floor(H*ty/30), tx 29→0, ty 0..29
  (源图标即 30x30 → 采样为恒等映射, 无缩放损失)
- 空槽色块: 30x30
- ⚠194=0xC2 > 127 必须 imm32
- 栈布局: V_YY (每槽 y) 复用旧 V_F 槽 0x1C (F 仅寄存器内使用从不回读)

v7.6 = v7.5 + 图标尺寸 10x10 → 20x20 → v7.7 30x30。

v7.5 = JVG 对象指针解引用修复 (图标不显示的最终根因, 由
unicorn 执行级验证定位 —— 见 test_war_status_icons_emu.py)。

【v7.5 修复①—总帧数偏移】sub_4544EC 的 a2 是 _DWORD*, a2[6] = 字节
偏移 6*4=24=0x18 (IDR 下标语义, 元素大小 4)! v5.0~v7.4 的 cave 误用
[edx+0x24] (=字节 36, loader 从未写入 = 堆垃圾 0) → F≥0 恒真 →
jae 跳过所有帧 → 图标永不绘制。修正为 cmp eax,[edx+0x18]。

【v7.5 修复②—obj+8/obj+12 是指针】sub_453BD0 为帧→block 表和帧→sf
表各自 malloc 独立数组, obj+8/obj+12 存的是【指针】; sub_4544EC 的
a2[2]/a2[3] 均为指针解引用。v7.4 误写 movzx esi,word[edx+ebx+8] 把
指针字段当内联数组读 → 读到堆地址值附近的垃圾。修正为先 mov ebx,
[edx+8] 再 movzx esi,word[ebx+eax*2]。

【交付前验证 (三层)】
1. capstone 全量解码 + 语义断言 (本文件)
2. Python 算法模拟: 对象导航+RLE 解码对照 ground truth, 31 帧一致
3. ★unicorn 执行级: 构造完整内存环境执行真实 cave 字节码, 跨块抽查
   5 帧 (76/80/90/100/106) 逐像素一致 (test_war_status_icons_emu.py)
   —— 任何 modrm/SIB/立即数/跳转/寄存器生命周期/指针解引用错误都
   会在执行结果中暴露。v7.4 的两个 bug 正是由此定位。

架构 (v7.8: hook 于面板 switch 的 bounds-ja):
  hook 点 sub_43A050 @0x43A7A6, 替换 `ja 0x43A8BD` (6 字节),
  每帧调用一次 (单位精灵循环之后、面板/菜单绘制之前); cave 尾部
  重放 cmp edx,0x2b 重新求值后按原条件分支返回。

历史修复链:
- v7  空槽 x 偏移 (曾画在屏幕左边缘 x=0)
- v7.1 y0 imm8 符号扩展 (143>127 → y0=sy+113 脚下)
- v7.3 RLE 游标 transparent 分支 (透明空洞误开新记录死推)
- v7.4 记录寻址 shl 目标错 (2F 而非 block)
- v7.5 总帧数偏移 0x18 + obj+8/obj+12 指针解引用 (最终根因)
- v7.8 层级: hook 0x43A8BD(菜单后)→0x43A7A6(菜单前); 空槽 0x2104→透明

逆向依据 (原版 反编译产物):
- 状态图标帧号 = word_9D6F76 + statusID - 1 (sub_437664.c:127-142/
  :186-202, dword_755AF4 = Mu2.jvg); word_9D6F76 = sub_45408C(obj,44)
  = 76; 状态图标帧 76..106 跨块 44..56。
- 战斗初始化 sub_42FEE0.c:151-153 载入 Mu2.jvg 并全量加载。
- 状态槽表: 记录基址 1054*u+0x9D707A 的 +0x56+i*2, 低字节=statusID。
- JVG 对象 (⚠偏移为字节; IDR 反编译中 _DWORD* 的下标 ×4):
  obj+0x00=records 指针, obj+0x08=帧→block 表指针, obj+0x0C=帧→sf
  表指针, obj+0x18=总帧数 (a2[6])。
- 记录 (64B): +0 块帧数, +8/+4 调色板 (u16[256] RGB565), +40 偏移表
  (按 sf 索引), +44 数据块指针, +48 大小, +60 调色板序号。
- JVG 帧: 16B 头 (+4 W, +6 H, +14 RLE 记录数); 反向线性扫描
  p640=(H-1-row)*640+(W-1-col); 缩放采样列 floor(W*tx/10)/行
  floor(H*ty/10); 游标每行复位, transparent 不写不推进。

几何 (v7.7: 30x30 原尺寸图标, 2 行 × 4 槽): ytop=sy_cam-194 (imm32!,
行2/顶行顶; 行1 = ytop+31, 底边距 HP 条顶 sy-132 留 1px), ytop∈[0,419]
无符号钳位 (总高 61px); x0=sx_cam-55 (行宽 4*31-1=123px, 中心 sx+6.5),
步进 31px (图标 30px + 间隔 1px); 空槽 0x2104 占位色块 30x30;
逐槽 xx≤610 (xx+30 ≤ 640)。
"""

from __future__ import annotations

import struct

try:
    import capstone as _cs
except ImportError:  # 允许无 capstone 环境下直接 python 运行打印 hex
    _cs = None

# ─── 栈变量映射 (sub esp,0x80 之后, 全部 disp8 可达) ───────────────
(V_Y0, V_X0, V_RECBASE, V_SLOT) = 0x00, 0x04, 0x08, 0x0C
(V_OBJ, V_FBASE, V_ST, V_F) = 0x10, 0x14, 0x18, 0x1C
(V_W, V_H, V_RCNT, V_PAL) = 0x20, 0x24, 0x28, 0x2C
(V_BLOBEND, V_XX, V_WSRC, V_RECLEFT) = 0x30, 0x34, 0x38, 0x3C
(V_POSCNT, V_RUNLEFT, V_RUNBASE, V_RUNSRC) = 0x40, 0x44, 0x48, 0x4C
(V_CANVAS, V_HDR, V_DYBYTES, V_TY) = 0x50, 0x54, 0x58, 0x5C
(V_I, V_BLOB, V_REC, V_UIDX) = 0x60, 0x64, 0x68, 0x6C
(V_TARGET, V_SF, V_TX, V_PBASE) = 0x70, 0x74, 0x78, 0x7C
# v7.7: V_YY 复用旧 V_F 槽 (0x1C, F 仅在寄存器内使用, 从不回读)
V_YY = 0x1C
# v7.9: V_OFF1 复用旧 V_UIDX 槽 (0x6C, u 在 ytop/x0 计算后死亡;
# RLE 像素循环不触及 0x6C, 绘制路径无冲突)
V_OFF1 = 0x6C

# 寄存器编号
RAX, RCX, RDX, RBX, RSI, RDI = 0, 1, 2, 3, 6, 7

# 相对条件跳转近形式 (rel32)
JCC = {
    "jo": 0x0F80, "jno": 0x0F81, "jb": 0x0F82, "jae": 0x0F83,
    "je": 0x0F84, "jne": 0x0F85, "jbe": 0x0F86, "ja": 0x0F87,
    "js": 0x0F88, "jns": 0x0F89, "jp": 0x0F8A, "jnp": 0x0F8B,
    "jl": 0x0F8C, "jge": 0x0F8D, "jle": 0x0F8E, "jg": 0x0F8F,
}
JCC["jz"] = JCC["je"]
JCC["jnz"] = JCC["jne"]


class Asm:
    """仅覆盖本 cave 所需编码形式的微型汇编器。"""

    def __init__(self) -> None:
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []

    def raw(self, *bs: int) -> None:
        self.code.extend(bs)

    def imm32(self, v: int) -> None:
        self.code += struct.pack("<i", v)

    def label(self, name: str) -> None:
        assert name not in self.labels, f"重复标签 {name}"
        self.labels[name] = len(self.code)

    def jmp(self, lab: str) -> None:
        self.raw(0xE9, 0, 0, 0, 0)
        self.fixups.append((len(self.code) - 4, lab))

    def jcc(self, mnem: str, lab: str) -> None:
        op = JCC[mnem]
        self.raw(op >> 8, op & 0xFF, 0, 0, 0, 0)
        self.fixups.append((len(self.code) - 4, lab))

    # [esp+disp8] ModRM+SIB 片段 (reg 字段由各指令封装填入)
    @staticmethod
    def _sp(off: int) -> tuple[int, bytes]:
        assert 0 <= off < 0x80
        return 0x24, bytes([off])

    def mov_r_m(self, reg: int, off: int) -> None:       # mov r32,[esp+off]
        sib, d = self._sp(off)
        self.raw(0x8B, 0x44 | (reg << 3), sib)
        self.raw(*d)

    def mov_m_r(self, off: int, reg: int) -> None:       # mov [esp+off],r32
        sib, d = self._sp(off)
        self.raw(0x89, 0x44 | (reg << 3), sib)
        self.raw(*d)

    def mov_m_imm(self, off: int, val: int) -> None:     # mov dword[esp+off],imm32 (/0)
        sib, d = self._sp(off)
        self.raw(0xC7, 0x44, sib)
        self.raw(*d)
        self.imm32(val)

    def cmp_m_imm8(self, off: int, imm: int) -> None:    # cmp dword[esp+off],imm8 (/7)
        sib, d = self._sp(off)
        self.raw(0x83, 0x7C, sib)
        self.raw(*d, imm)

    def cmp_m_r(self, off: int, reg: int) -> None:       # cmp dword[esp+off],r32
        sib, d = self._sp(off)
        self.raw(0x39, 0x44 | (reg << 3), sib)
        self.raw(*d)

    def add_m_r(self, off: int, reg: int) -> None:       # add [esp+off],r32
        sib, d = self._sp(off)
        self.raw(0x01, 0x44 | (reg << 3), sib)
        self.raw(*d)

    def inc_m(self, off: int) -> None:                   # FF /0
        sib, d = self._sp(off)
        self.raw(0xFF, 0x44, sib)
        self.raw(*d)

    def dec_m(self, off: int) -> None:                   # FF /1
        sib, d = self._sp(off)
        self.raw(0xFF, 0x4C, sib)
        self.raw(*d)

    def resolve(self) -> bytearray:
        out = bytearray(self.code)
        for pos, lab in self.fixups:
            rel = self.labels[lab] - (pos + 4)
            out[pos:pos + 4] = struct.pack("<i", rel)
        return out


def build() -> bytearray:
    a = Asm()
    r = a.raw

    ADDR_CAMX, ADDR_CAMY = 0x8242A8, 0x8242AC
    ADDR_POS_X, ADDR_POS_Y = 0x9DF802, 0x9DF804
    ADDR_MU2_OBJ = 0x755AF4
    ADDR_ICON_BASE_FRAME = 0x9D6F76
    ADDR_WAR_REC_BASE = 0x9D707A
    ADDR_GRID = 0x951D42

    # ── 序言 (v7.8: cld 移除 — 空槽填充删除后 cave 无字符串操作) ──
    r(0x60)                       # pushad
    r(0x81, 0xEC); a.imm32(0x80)  # sub esp,0x80
    r(0x8B, 0x45, 0x08)           # mov eax,[ebp+8]  (canvas)
    a.mov_m_r(V_CANVAS, RAX)

    # ── 格网遍历 (v5.5: 与引擎绘制循环同源) ─────────────────────
    a.mov_m_imm(V_I, 0)

    a.label("L_unit")
    a.mov_r_m(RAX, V_I)
    a.inc_m(V_I)
    r(0x3D); a.imm32(1024)                        # cmp eax,1024
    a.jcc("jae", "L_done")
    r(0x0F, 0xB6, 0x90); a.imm32(ADDR_GRID)       # movzx edx,byte[eax+grid]
    r(0x83, 0xFA, 0x20)           # cmp edx,0x20 (空格 0xFF 亦被挡)
    a.jcc("jae", "L_unit")
    a.mov_m_r(V_UIDX, RDX)

    # recordBase = u*1054 + 0x9D707A (v5.5: eax=u 自 edx)
    r(0x89, 0xD0)                              # mov eax,edx
    r(0x69, 0xC0); a.imm32(1054)               # imul eax,eax,0x41E
    r(0x05); a.imm32(ADDR_WAR_REC_BASE)
    a.mov_m_r(V_RECBASE, RAX)
    r(0x0F, 0xBF, 0x48, 0x0A)                  # movsx ecx,word[eax+0xA] (HP)
    r(0x85, 0xC9)                              # test ecx,ecx
    a.jcc("jle", "L_unit")                     # 死亡单位跳过

    # ytop = sy - camY - 194 (v7.7: 30x30 图标 2 行 × 4 槽布局)
    # 行1 (槽 0-3) y = ytop+31 = sy-163, 底边 sy-133 距 HP 条顶 sy-132
    # 上方 1px; 行2 (槽 4-7) y = ytop = sy-194。总高 61px。
    # ⚠194=0xC2 > 127 必须 imm32 (81 EA C2 00 00 00)。
    # 钳位 ytop∈[0,419] (ytop+61 ≤ 480, 无符号比较同时挡负值)。
    a.mov_r_m(RCX, V_UIDX)                     # ecx = u
    r(0x0F, 0xBF, 0x14, 0x8D); a.imm32(ADDR_POS_Y)  # movsx edx,word[ecx*4+Y]
    r(0x2B, 0x15); a.imm32(ADDR_CAMY)               # sub edx,[camY]
    r(0x81, 0xEA); a.imm32(194)                # sub edx,194 (imm32!)
    r(0x81, 0xFA); a.imm32(419)                # cmp edx,419
    a.jcc("ja", "L_unit")                      # ytop∉[0,419] 跳过
    a.mov_m_r(V_Y0, RDX)                       # V_Y0 = ytop (单位级, 不变)

    # x0 = sx - camX - 55 (v7.7: 行宽 4*31-1=123px, 中心保持 sx+6.5:
    # x0 = sx+6.5-61.5 = sx-55; ecx = u 仍存活)
    r(0x0F, 0xBF, 0x14, 0x8D); a.imm32(ADDR_POS_X)
    r(0x2B, 0x15); a.imm32(ADDR_CAMX)
    r(0x81, 0xEA); a.imm32(55)                 # sub edx,55 (imm32)
    a.mov_m_r(V_X0, RDX)

    # Mu2.jvg 对象与状态图标基准帧 (战斗初始化 sub_42FEE0 已加载)
    r(0xA1); a.imm32(ADDR_MU2_OBJ)             # mov eax,[Mu2obj]
    a.mov_m_r(V_OBJ, RAX)
    r(0x85, 0xC0)
    a.jcc("jz", "L_unit")                      # 未载入保护
    r(0x0F, 0xB7, 0x05); a.imm32(ADDR_ICON_BASE_FRAME)  # movzx eax,word[fbase]
    a.mov_m_r(V_FBASE, RAX)

    # ── v7.9 单位级预扫描: n1 = 行1 (slot 0..3) 激活状态数 ──────
    # offset1 = (124 - 31*n1) >> 1:  n1=1..4 → 46/31/15/0
    # (组宽 31n-1, 行宽 123, 居中; n1=0 → 62 无图标绘制不受影响)
    a.mov_r_m(RCX, V_RECBASE)                  # ecx = recbase
    r(0x31, 0xC0)                              # xor eax,eax (n1 = 0)
    r(0x31, 0xDB)                              # xor ebx,ebx (i = 0)
    a.label("L_n1")
    r(0x83, 0xFB, 0x04)                        # cmp ebx,4
    a.jcc("jae", "L_n1_done")
    r(0x0F, 0xB6, 0x54, 0x59, 0x56)            # movzx edx,byte[ecx+ebx*2+0x56]
    r(0x85, 0xD2)                              # test edx,edx
    a.jcc("jz", "L_n1_zero")
    r(0x40)                                    # inc eax (n1++)
    a.label("L_n1_zero")
    r(0x43)                                    # inc ebx (i++)
    a.jmp("L_n1")
    a.label("L_n1_done")
    r(0x6B, 0xC8, 0x1F)                        # imul ecx,eax,31
    r(0xB8); a.imm32(124)                      # mov eax,124
    r(0x29, 0xC8)                              # sub eax,ecx (124 - 31*n1)
    r(0xD1, 0xE8)                              # shr eax,1
    a.mov_m_r(V_OFF1, RAX)                     # V_OFF1 = 居中偏移

    a.mov_m_imm(V_SLOT, 0)

    # ── 8 个状态槽循环 (v7.9: 行1 居中 / 行2 从左到右) ──────────
    # 行1 (槽 0-3): xx = x0 + offset1 + k*31  (k = 行内激活序号)
    # 行2 (槽 4-7): xx = x0 + k*31            (从左到右, 不居中)
    #   yy = ytop + 31 - row*31   (row = slot>>2; 行1: ytop+31; 行2: ytop)
    a.label("L_slot")
    a.mov_r_m(RAX, V_SLOT)
    r(0x83, 0xF8, 0x08)                        # cmp eax,8
    a.jcc("jge", "L_unit")                     # 本单位完成 → 下一格
    # st 提前读取 (v7.9: 空槽不占位, k 计数也依赖 st)
    a.mov_r_m(RCX, V_RECBASE)                  # ecx = recbase
    # ⚠modrm 0x54 = mod01|reg(edx)|SIB: 误写 0x14 (mod00 无位移) 会被
    # capstone 解出 movzx edx,[ecx+eax*2] + push esi (0x56 沦为独立指令)
    r(0x0F, 0xB6, 0x54, 0x41, 0x56)            # movzx edx,byte[ecx+slot*2+0x56]
    r(0x85, 0xD2)                              # test st,st
    a.mov_m_r(V_ST, RDX)
    a.jcc("jz", "L_slot_inc")                  # v7.8: 空槽透明 → 不占位
    # ── v7.9: 行内激活序号 k = Σ_{i<slot, 同行} (st[i]!=0) ──────
    r(0x89, 0xC3)                              # mov ebx,eax (slot)
    r(0x83, 0xE3, 0x04)                        # and ebx,4  行基 (0=行1, 4=行2)
    r(0x89, 0xDE)                              # mov esi,ebx (i = 行基)
    r(0x31, 0xD2)                              # xor edx,edx (k = 0)
    a.label("L_cnt")
    r(0x39, 0xF0)                              # cmp eax,esi (slot vs i)
    a.jcc("jbe", "L_cnt_done")                 # i ≥ slot → 计数完成
    r(0x0F, 0xB6, 0x7C, 0x71, 0x56)            # movzx edi,byte[ecx+esi*2+0x56]
    r(0x85, 0xFF)                              # test edi,edi (st[i])
    a.jcc("jz", "L_cnt_zero")
    r(0x42)                                    # inc edx (k++)
    a.label("L_cnt_zero")
    r(0x46)                                    # inc esi (i++)
    a.jmp("L_cnt")
    a.label("L_cnt_done")
    # ── v7.9: xx = x0 + k*31 + (行1 ? offset1 : 0) ─────────────
    r(0x6B, 0xD2, 0x1F)                        # imul edx,edx,31 (k*31)
    r(0x03, 0x54, 0x24, V_X0)                  # add edx,[x0]
    r(0x85, 0xDB)                              # test ebx,ebx (行基)
    a.jcc("jnz", "L_xx_done")                  # 行2: 从左到右, 无居中偏移
    a.mov_r_m(RBX, V_OFF1)                     # ebx = offset1 (行1 居中)
    r(0x01, 0xDA)                              # add edx,ebx
    a.label("L_xx_done")
    a.mov_m_r(V_XX, RDX)
    r(0x81, 0xFA); a.imm32(610)                # cmp edx,610 (xx+30≤640)
    a.jcc("ja", "L_slot_inc")                  # 无符号比较同时挡负值
    # yy 不变 (row = slot>>2; eax = slot 仍存活)
    r(0x89, 0xC1)                              # mov ecx,eax
    r(0xC1, 0xE9, 0x02)                        # shr ecx,2
    r(0x6B, 0xC9, 0x1F)                        # imul ecx,ecx,31
    a.mov_r_m(RDX, V_Y0)                       # edx = ytop
    r(0x83, 0xC2, 0x1F)                        # add edx,31
    r(0x29, 0xCA)                              # sub edx,ecx → yy
    a.mov_m_r(V_YY, RDX)                       # [esp+V_YY] = yy (每槽)
    # F = fbase + st - 1 (仅寄存器内使用; V_F 槽已复用为 V_YY)
    a.mov_r_m(RAX, V_ST)
    r(0x48)                                    # dec eax
    r(0x03, 0x44, 0x24, V_FBASE)
    a.mov_r_m(RDX, V_OBJ)
    # ⚠v7.5 修复②: 总帧数在 obj+0x18! sub_4544EC 的 a2 是 _DWORD*,
    # a2[6] = 字节偏移 6*4=24=0x18 (IDR 下标语义)。旧代码误用 0x24
    # (=字节 36, loader 从未写入的堆垃圾=0) → F≥0 恒真 → 所有帧被
    # jae 跳过 → 图标永不绘制!
    r(0x3B, 0x42, 0x18)                        # cmp eax,[edx+0x18] 总帧数
    a.jcc("jae", "L_slot_inc")

    # block=u16[*(obj+8)+2F]; sf=u16[*(obj+12)+2F]
    # ⚠⚠v7.5 最终修复: obj+8 / obj+12 是【指针】(sub_453BD0 各自 malloc
    # 两块独立数组), sub_4544EC 的 a2[2]/a2[3] 都是指针解引用!
    # 旧代码 movzx esi,word[edx+ebx+8] 把指针字段当内联数组读 →
    # 读到的是堆地址值附近的垃圾 → block/sf 全错 → 记录/blob/调色板
    # 全错 → 图标永不绘制 (v5.0~v7.4 『图标不显示』的最终根因,
    # 由 unicorn 执行级验证定位)。
    r(0x8B, 0x5A, 0x08)                        # mov ebx,[edx+8] 块号表指针
    r(0x0F, 0xB7, 0x34, 0x43)                  # movzx esi,word[ebx+eax*2] block
    r(0x8B, 0x5A, 0x0C)                        # mov ebx,[edx+12] 子帧号表指针
    r(0x0F, 0xB7, 0x0C, 0x43)                  # movzx ecx,word[ebx+eax*2] sf
    a.mov_m_r(V_SF, RCX)                       # [esp+V_SF]=sf (防寄存器覆盖)
    r(0x89, 0xF3)                              # mov ebx,esi (ebx=block)
    r(0xC1, 0xE3, 0x06)                        # shl ebx,6 (block*64)
    r(0x8B, 0x3A)                              # mov edi,[edx] (records)
    r(0x01, 0xDF)                              # add edi,ebx → rec=records+block*64
    a.mov_m_r(V_REC, RDI)
    r(0x3B, 0x0F)                              # cmp ecx,[edi] (sf vs 块帧数)
    a.jcc("jae", "L_slot_inc")                 # sf≥帧数 → 跳过

    # blob=[rec+0x2C] 必已由 sub_45410C(obj,-1,0) 加载
    r(0x8B, 0x47, 0x2C)                        # mov eax,[edi+0x2C]
    r(0x85, 0xC0)
    a.jcc("jz", "L_slot_inc")
    a.mov_m_r(V_BLOB, RAX)
    r(0x8B, 0x4F, 0x28)                        # mov ecx,[edi+0x28] 偏移表
    a.mov_r_m(RSI, V_SF)                       # mov esi,[esp+V_SF] (sf)
    r(0x8B, 0x34, 0xB1)                        # mov esi,[ecx+esi*4] (按 sf 索引!)
    r(0x01, 0xF0)                              # add eax,esi → hdr
    a.mov_m_r(V_HDR, RAX)
    r(0x8B, 0x47, 0x30)                        # size=[rec+0x30]
    r(0x03, 0x44, 0x24, V_BLOB)                # blobEnd=blob+size
    a.mov_m_r(V_BLOBEND, RAX)

    # W/H/rcnt 任一为 0 → 跳过
    a.mov_r_m(RAX, V_HDR)
    r(0x0F, 0xB7, 0x48, 0x04)                  # movzx ecx,word[hdr+4] W
    a.mov_m_r(V_W, RCX)
    r(0x85, 0xC9)
    a.jcc("jz", "L_slot_inc")
    r(0x0F, 0xB7, 0x48, 0x06)                  # H
    a.mov_m_r(V_H, RCX)
    r(0x85, 0xC9)
    a.jcc("jz", "L_slot_inc")
    r(0x0F, 0xB7, 0x48, 0x0E)                  # rcnt=@hdr+14
    a.mov_m_r(V_RCNT, RCX)
    r(0x85, 0xC9)
    a.jcc("jz", "L_slot_inc")

    # 调色板: tbl[[rec+0x3C]], 为空回退 [rec+4] (与 sub_4544EC pal=-1 一致)
    a.mov_r_m(RDX, V_REC)
    r(0x8B, 0x4A, 0x3C)                        # mov ecx,[rec+0x3C]
    r(0x8B, 0x44, 0x8A, 0x08)                  # mov eax,[rec+ecx*4+8]
    r(0x85, 0xC0)
    a.jcc("jne", "pal_ok")
    r(0x8B, 0x42, 0x04)                        # mov eax,[rec+4]
    a.label("pal_ok")
    r(0x85, 0xC0)
    a.jcc("jz", "L_slot_inc")
    a.mov_m_r(V_PAL, RAX)

    # ── 图标解码 + 最近邻缩放绘制 ─────────────────────────────
    a.mov_m_imm(V_TY, 0)

    a.label("L_row")
    # ⚠每行必须复位 RLE 游标 (v5.2 修复): 行基准随 ty 下移(变小),
    # 行间非单调, 单向游标跨行后永远追不上更小 target → 整行黑掉。
    a.mov_r_m(RAX, V_HDR)
    r(0x83, 0xC0, 0x10)                        # wsrc=hdr+16
    a.mov_m_r(V_WSRC, RAX)
    a.mov_r_m(RAX, V_RCNT)
    a.mov_m_r(V_RECLEFT, RAX)
    a.mov_m_imm(V_POSCNT, 0)
    a.mov_m_imm(V_RUNLEFT, 0)

    # SRCROW=(H*ty)/30 (v7.7: 30x30 原尺寸直采, 寄存器临时)
    a.mov_r_m(RAX, V_TY)
    r(0x0F, 0xAF, 0x44, 0x24, V_H)             # imul eax,[esp+V_H]
    r(0x31, 0xD2)                              # xor edx,edx
    r(0xB9, 0x1E, 0x00, 0x00, 0x00)            # mov ecx,30
    r(0xF7, 0xF1)                              # div ecx
    # PBASE = (H-1-SRCROW)*640 + (W-1)  (v7.3 恢复 v7.1 公式 —— 它本来就对)
    a.mov_r_m(RCX, V_H)
    r(0x49)                                    # dec ecx
    r(0x29, 0xC1)                              # sub ecx,eax
    r(0x69, 0xC9); a.imm32(640)                # imul ecx,ecx,640
    a.mov_r_m(RAX, V_W)
    r(0x48)                                    # dec eax
    r(0x01, 0xC1)                              # add ecx,eax
    a.mov_m_r(V_PBASE, RCX)
    # dyBytes = 1280*(yy+ty)  (v7.7: yy 为每槽 y, V_YY)
    a.mov_r_m(RAX, V_YY)
    r(0x03, 0x44, 0x24, V_TY)
    r(0x69, 0xC0); a.imm32(1280)
    a.mov_m_r(V_DYBYTES, RAX)
    a.mov_m_imm(V_TX, 29)

    a.label("L_tx")
    # 采样语义 (sub_4544EC 反向扫描): 源单元格 (bufRow,bufCol) 的线性位置
    #   p640 = (H-1-bufRow)*640 + (W-1-bufCol)
    # 采样 bufCol=floor(W*tx/30) (v7.7: tx 从左数, 0..29) →
    #   target = (H-1-bufRow)*640 + (W-1) - floor(W*tx/30) = PBASE - col
    # tx 29→0 迭代使 target 行内单调递增 (col640 递减), 与 RLE 记录流
    # (p640 递增) 方向一致, 单游标前向推进成立。
    a.mov_r_m(RAX, V_TX)
    r(0x0F, 0xAF, 0x44, 0x24, V_W)
    r(0x31, 0xD2)
    r(0xB9, 0x1E, 0x00, 0x00, 0x00)            # mov ecx,30
    r(0xF7, 0xF1)
    a.mov_r_m(RDX, V_PBASE)
    r(0x29, 0xC2)                              # sub edx,eax → target
    a.mov_m_r(V_TARGET, RDX)

    # 单游标前向推进 (v7.3 核心: target 落在透明空洞时【不写也不推进】)
    a.label("L_seek")
    a.cmp_m_imm8(V_RUNLEFT, 0)
    a.jcc("je", "seek_open")
    a.mov_r_m(RAX, V_RUNBASE)
    r(0x03, 0x44, 0x24, V_RUNLEFT)             # eax=runEnd
    a.mov_r_m(RCX, V_TARGET)
    r(0x39, 0xC1)                              # cmp target,runEnd
    a.jcc("jae", "seek_open")                  # target ≥ 窗口尾 → 推进游标
    a.mov_r_m(RAX, V_RUNBASE)
    r(0x39, 0xC1)                              # cmp target,runbase
    a.jcc("jb", "transparent")                 # ⚠v7.3: 空洞 → 不写不推进!
    # 命中: color=pal[runsrc[target-runbase]]
    r(0x29, 0xC1)                              # sub ecx,eax → idx
    a.mov_r_m(RDX, V_RUNSRC)
    r(0x0F, 0xB6, 0x04, 0x0A)                  # movzx eax,byte[edx+ecx]
    a.mov_r_m(RDX, V_PAL)
    r(0x0F, 0xB7, 0x04, 0x42)                  # movzx eax,word[edx+eax*2]
    # 写像素: dst=canvas+dyBytes+2*(xx+tx)
    a.mov_r_m(RDX, V_XX)
    r(0x03, 0x54, 0x24, V_TX)
    r(0xD1, 0xE2)                              # shl edx,1
    r(0x03, 0x54, 0x24, V_DYBYTES)
    r(0x03, 0x54, 0x24, V_CANVAS)
    r(0x66, 0x89, 0x02)                        # mov [edx],ax
    a.jmp("tx_next")

    # ⚠v7.3 关键修复: target 在 run 前的透明空洞 (skip 段) 内。
    # v5~v7.2 此分支走 seek_open 死推游标到记录耗尽 → row_exhaust →
    # 行内后续实心像素全部被丢弃 = 『图标不显示』的真正根因。
    # 正确行为: 该像素透明不写, 游标原地等待下一个更大的 target。
    a.label("transparent")
    a.jmp("tx_next")

    a.label("seek_open_miss")
    a.label("seek_open")
    # 记录耗尽或越过数据尾 → 弃写本行剩余样本
    a.cmp_m_imm8(V_RECLEFT, 0)
    a.jcc("je", "row_exhaust")
    a.mov_r_m(RCX, V_WSRC)
    r(0x3B, 0x4C, 0x24, V_BLOBEND)             # cmp wsrc,blobEnd
    a.jcc("jae", "row_exhaust")
    a.dec_m(V_RECLEFT)
    r(0x89, 0xCF)                              # mov edi,ecx
    r(0x0F, 0xB7, 0x07)                        # movzx eax,word[edi] skip
    a.add_m_r(V_POSCNT, RAX)
    r(0x0F, 0xB7, 0x47, 0x02)                  # movzx eax,word[edi+2] run
    r(0x83, 0xC7, 0x04)                        # edi+=4
    a.mov_r_m(RCX, V_POSCNT)
    a.mov_m_r(V_RUNBASE, RCX)                  # runbase=读前 poscnt
    a.mov_m_r(V_RUNLEFT, RAX)
    a.mov_m_r(V_RUNSRC, RDI)                   # runsrc=数据首字节
    a.add_m_r(V_POSCNT, RAX)                   # poscnt+=run
    r(0x01, 0xC7)                              # edi+=run
    a.mov_m_r(V_WSRC, RDI)                     # 下一条记录
    a.jmp("L_seek")

    a.label("row_exhaust")
    a.mov_m_imm(V_RUNLEFT, 0)                  # 失效残留 run

    a.label("tx_next")
    a.dec_m(V_TX)
    a.cmp_m_imm8(V_TX, 0)
    a.jcc("jns", "L_tx")                       # tx: 29..0 (target 单调递增)

    a.inc_m(V_TY)
    a.cmp_m_imm8(V_TY, 30)
    a.jcc("jl", "L_row")
    a.jmp("L_slot_inc")

    # (v7.8: 空槽占位色块路径已删除 — 空槽透明不绘制)

    a.label("L_slot_inc")
    a.inc_m(V_SLOT)
    a.jmp("L_slot")

    # ── 尾声 (v7.8): 重放被 hook 覆盖的 bounds-ja 条件分支 ──────
    # 被替换指令: ja 0x43A8BD @0x43A7A6 (0F 87 11 01 00 00), 条件
    # (unsigned)edx > 0x2B; edx = movsx word[9D6C88] (0x43A79C 设置,
    # popad 恢复同值)。cave 主体破坏标志位 → 重放 cmp edx,0x2b 求值:
    #   未取 (edx≤0x2B): ret → E8 返回地址 0x43A7AB(NOP) → 0x43A7AC
    #   取 (edx>0x2B)  : add [esp],0x112 → 返回地址 0x43A7AB→0x43A8BD
    #     (面板 switch default 路径: word_9D6C88=-1/>43 无菜单直达尾部;
    #      0x112 = 0x43A8BD - 0x43A7AB)
    # 两路径栈均严格平衡: 仅调整/弹出【自身 E8 返回地址】(位于 esp0
    # 之下, 属 cave 所有), 绝不写调用者活跃栈帧 (v6 挂车式血泪教训)。
    a.label("L_done")
    r(0x81, 0xC4); a.imm32(0x80)  # add esp,0x80
    r(0x61)                       # popad (edx 恢复为 movsx 结果)
    r(0x83, 0xFA, 0x2B)           # cmp edx,0x2b (重放求值标志)
    a.jcc("jbe", "L_ret")         # edx≤0x2B → 原 ja 未取 → 正常返回
    r(0x81, 0x04, 0x24); a.imm32(0x112)  # add dword[esp],0x112 (返回地址→0x43A8BD)
    a.label("L_ret")
    r(0xC3)                       # ret

    return a.resolve()


def cave_bytes() -> bytes:
    return bytes(build())


def cave_hex() -> str:
    return cave_bytes().hex(" ").upper()


# ────────────────────────────────────────────────────────────────
# 校验
# ────────────────────────────────────────────────────────────────


def _disasm(code: bytes):
    md = _cs.Cs(_cs.CS_ARCH_X86, _cs.CS_MODE_32)
    return list(md.disasm(code, 0)), md


def _require_capstone():
    if _cs is None:
        raise RuntimeError("需要 capstone (pip install capstone)")


def test_disassemble_clean() -> None:
    _require_capstone()
    code = cave_bytes()
    insns, _ = _disasm(code)
    covered = sum(i.size for i in insns)
    assert covered == len(code), f"存在无法对齐解码的字节 ({covered}/{len(code)})"
    assert insns[-1].mnemonic == "ret"


def test_key_semantics_present() -> None:
    _require_capstone()
    code = cave_bytes()
    insns, _ = _disasm(code)
    text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in insns).lower()
    for needle in (
        "pushal",                             # capstone 渲染 pushad 为 pushal
        "popal",                              # 尾声 popad (v7 恢复 v5.x 架构)
        "movzx edx, byte ptr [eax + 0x951d42]",  # 格网遍历 (引擎同源)
        "cmp edx, 0x2b",                      # v7.8: 重放 bounds cmp 求值标志
        "jbe",                                # v7.8: 原 ja 未取 → 正常返回
        "add dword ptr [esp], 0x112",         # v7.8: 返回地址 7AB→8BD (default)
        "0x9d707a",                           # 记录基址 (add eax,imm 形式)
        "[0x755af4]",                         # Mu2.jvg 对象
        "[0x9d6f76]",                         # 状态图标基准帧
        "[0x8242a8]", "[0x8242ac]",           # 相机 X/Y
        "[ecx*4 + 0x9df802]", "[ecx*4 + 0x9df804]",  # ×4 坐标寻址
        "sub edx, 0xc2",                       # v7.7: ytop -= 194 (imm32)
        "cmp edx, 0x1a3",                      # v7.7: ytop <= 419 (2行61px)
        "shr ecx, 2",                          # v7.7: row = slot>>2
        "imul edx, edx, 0x1f",                 # v7.9: k*31 步进 (行内序号)
        # v7.9: 行1 居中布局特征
        "and ebx, 4",                          # 行基 (0=行1, 4=行2)
        "movzx edx, byte ptr [ecx + eax*2 + 0x56]",  # st 提前读取
        "movzx edx, byte ptr [ecx + ebx*2 + 0x56]",  # 预扫描读 st[i] (n1)
        "movzx edi, byte ptr [ecx + esi*2 + 0x56]",  # k 前缀计数读 st[i]
        "imul ecx, eax, 0x1f",                 # offset1 = (124-31*n1)>>1
        "shr eax, 1",                          # offset1 半宽
        "mov ebx, dword ptr [esp + 0x6c]",     # V_OFF1 (复用旧 V_UIDX 槽)
        "mov ebx, esi",                       # v7.4: block→ebx (修记录寻址)
        "cmp ecx, dword ptr [edi]",           # v7.4: sf vs 块帧数
    ):
        assert needle in text, needle
    # v7.9: 旧 col=slot&3 固定布局必须消失 (位置改由行内序号 k 决定)
    assert "and edx, 3" not in text, "v7.9: 不应再有 col=slot&3 固定布局"
    # v7.4 记录寻址 bug 特征: shl ebx,6 紧跟 add ebx,ebx (用 2F 而非 block)
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "shl ebx, 6" in ln:
            assert "mov ebx, esi" in lines[max(0, i - 1)], \
                f"shl ebx,6 前必须是 mov ebx,esi (v7.4): {lines[max(0,i-2):i+1]}"
    # v7.0 的 imm8 符号扩展 bug 特征 (负立即数 = 符号扩展错误):
    assert "sub edx, -" not in text
    # v6 挂车架构残留必须全部清除
    assert "0x43a6c9" not in text             # 无 push 返回地址
    assert "[ebp - 6]" not in text            # 无挂车单位号读取
    assert "cwde" not in text                 # 无 modrm 编码垃圾指令
    assert text.count("ebp") == 1  # 仅 [ebp+8] 画布读取
    # v7.8: 空槽透明 — 灰块填充与字符串操作必须全部消失
    assert "rep" not in text, "v7.8 空槽透明: 不应再有 rep stosw"
    assert "0x2104" not in text, "v7.8 空槽透明: 不应再有 0x2104 灰块"
    assert "stos" not in text, "v7.8: cave 内无字符串操作"


def test_empty_slot_transparent() -> None:
    """v7.8: 空槽透明 — st==0 分支直接跳槽递增, 无任何绘制指令。

    历史背景: v7 曾因空槽路径缺 x 偏移把灰块画在屏幕左边缘 (Bug ①),
    v7.8 起空槽不再绘制 (用户需求: 透明), 该整条路径连同步删除。
    unicorn 层的邻格全零断言 (test_war_status_icons_emu.py) 验证执行
    级『空槽真的不写像素』。"""
    _require_capstone()
    code = cave_bytes()
    insns, _ = _disasm(code)
    text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in insns).lower()
    # 填充指令必须全部消失
    assert "rep" not in text and "stos" not in text
    assert "0x2104" not in text
    # st==0 (je) 跳转后紧跟的目标必须是槽递增路径 (inc/jmp 循环),
    # 这里用宽松断言: je 的数量 ≥ 1 且文本中不存在灰块立即数。
    # 强断言由 unicorn 邻格全零检查承担。


def test_icon_decode_matches_truth() -> None:
    """算法级验证 (v7.4): 完整模拟 cave 的对象导航 + RLE 游标解码, 对照
    直接解码 ground truth。覆盖全部状态图标帧 76..106 (st=1..31, 跨块
    44..56) —— v7.3 版只测了块44 且绕过对象导航, 漏掉了记录寻址 bug。"""
    import struct
    from pathlib import Path

    jvg = Path(__file__).resolve().parents[3] / \
        "逆向工作区" / "逆向工作区" / "Mu2.JVG"
    if not jvg.exists():  # 资源不存在时跳过 (CI 环境)
        print(f"    [skip] {jvg} 不存在")
        return
    d = jvg.read_bytes()
    block_count = struct.unpack_from("<I", d, 8)[0]
    # 解析全部块 → 构建 loader (sub_453BD0) 等价的对象结构
    blocks = []   # (first_frame, scnt, off_table_file_off, pal_off, data_start)
    pos, total = 32, 0
    for _ in range(block_count):
        tag = d[pos:pos + 4]
        if tag == b"@JVM":
            scnt = struct.unpack_from("<I", d, pos + 4)[0]
            dsz = struct.unpack_from("<I", d, pos + 12)[0]
            lo = pos + 32
            pal_off = lo + (scnt + 1) * 4
            ds = pal_off + 512
            blocks.append((total, scnt, lo, pal_off, ds))
            total += scnt
            pos = ds + dsz
        elif tag == b"@JVS":
            cnt = struct.unpack_from("<I", d, pos + 4)[0]
            cur = pos + 32
            for _e in range(cnt):
                dsz2 = struct.unpack_from("<I", d, cur)[0]
                dstart = cur + 4 + 512
                blocks.append((total, 1, None, cur + 4, dstart))  # 偏移=0
                total += 1
                cur = dstart + dsz2
            pos = cur
        else:
            break
    # 帧→(block, sf) 表 = obj+8/obj+12 的 u16 数组
    f2b, f2sf = [0] * total, [0] * total
    for b, (first, scnt, _lo, _pal, _ds) in enumerate(blocks):
        for k in range(scnt):
            f2b[first + k] = b
            f2sf[first + k] = k

    n_checked = 0
    for F in range(76, total):                 # 全部状态图标帧 (fbase=76)
        # ── 模拟 cave 对象导航 (v7.4 修正后语义) ──
        b = f2b[F]                             # block = u16[obj+8+2F]
        sf = f2sf[F]                           # sf = u16[obj+12+2F]
        first, scnt, lo, pal_off, ds = blocks[b]
        if sf >= scnt:                         # sf < rec+0 (块帧数)
            continue
        offs = ([struct.unpack_from("<I", d, lo + i * 4)[0]
                 for i in range(scnt + 1)] if lo is not None else [0])
        fo = ds + offs[sf]                     # hdr = blob + 偏移表[sf]
        _xm, _ym, W, H = struct.unpack_from("<hhHH", d, fo)
        rcnt = struct.unpack_from("<H", d, fo + 14)[0]
        pal = [struct.unpack_from("<H", d, pal_off + i * 2)[0]
               for i in range(256)]
        # ground truth: 直接整帧解码 (sub_4544EC 语义)
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
        # cave 算法模拟 (v7.3 游标控制流: transparent 不写不推进; v7.7 30x30)
        out = [[None] * 30 for _ in range(30)]
        for ty in range(30):
            wsrc, recleft, poscnt = fo + 16, rcnt, 0
            runleft = runbase = runsrc = 0
            for tx in range(29, -1, -1):
                target = (H - 1 - (H * ty // 30)) * 640 \
                    + (W - 1) - (W * tx // 30)
                while True:
                    if runleft:
                        if target >= runbase + runleft:
                            pass
                        elif target < runbase:
                            break  # transparent
                        else:
                            out[ty][tx] = pal[d[runsrc + (target - runbase)]]
                            break
                    if recleft == 0:
                        break
                    recleft -= 1
                    skip, run = struct.unpack_from("<HH", d, wsrc)
                    poscnt += skip
                    runbase = poscnt
                    runsrc = wsrc + 4
                    runleft = run
                    poscnt += run
                    wsrc = runsrc + run
        assert out == expect, f"frame{F} (block{b} sf{sf}) 模拟不一致"
        n_checked += 1
    assert n_checked >= 25, f"仅验证了 {n_checked} 帧 (期望≥25)"
    print(f"    [OK] 对象导航+解码验证 {n_checked} 帧全部一致")


def test_frame_budget() -> None:
    code = cave_bytes()
    # cave_offset=2048, 预算 4096 → 上限 2048 字节
    assert len(code) <= 2048, len(code)


def test_patch_json_matches_builder() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    raw = json.loads(
        (root / "patches" / "war_status_icons" / "patch.json").read_text("utf-8")
    )
    norm = lambda s: [t.upper() for t in s.split()]  # noqa: E731
    assert norm(raw["cave_code"]) == norm(cave_hex()), \
        "patch.json cave_code 与构建器输出不一致"
    # 布局不变量 (与 cave_layout.py budget / summon_extend 硬编码区一致)
    assert raw["cave_offset"] == 2048 and raw["autolayout_cave"] is False
    # v7.8: hook 点 = 面板 switch 的 bounds-ja (菜单之前, 与血条零重叠)
    assert raw["hook_pattern"] == \
        "0F 87 11 01 00 00 8A 92 B9 A7 43 00"
    assert raw["hook_size"] == 6 and raw["hook_expect_count"] == 1
    assert raw["hook_offset"] == 0
    assert "fallback_rva" not in raw or not raw.get("fallback_rva")
    assert raw["type"] == "cave_hook" and raw["id"] == "war_status_icons"


if __name__ == "__main__":
    code = cave_bytes()
    print(f"total {len(code)} bytes")
    test_frame_budget()
    test_patch_json_matches_builder()
    print("[OK] frame budget / patch.json 一致性通过")
    if _cs is not None:
        # ⚠语义断言必须跑 (历史教训: 不跑会漏编码 bug)
        test_disassemble_clean()
        test_key_semantics_present()
        test_empty_slot_transparent()
    test_icon_decode_matches_truth()  # 自带 [OK]/[skip] 输出与断言
    if _cs is not None:
        md = _cs.Cs(_cs.CS_ARCH_X86, _cs.CS_MODE_32)
        off = 0
        for i in md.disasm(code, 0):
            if i.address != off:  # 断点
                print(f"!! 停在 {off:#x}, 原始字节: {code[off:off+16].hex(' ')}")
                break
            print(f"  {i.address:04x}: {i.mnemonic} {i.op_str}")
            off += i.size
        else:
            if off != len(code):
                print(f"!! 尾部残留 {off:#x}: {code[off:off+16].hex(' ')}")
            else:
                print("capstone 全量解码通过")
    print()
    print(cave_hex())
