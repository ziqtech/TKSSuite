# -*- coding: utf-8 -*-
"""战斗中物品图标跟随 Mu.JVG 帧表 (tkitem_expand.battle_icon) — 带注释机器码源

【问题】菜单/商店的物品图标取自 Mu.JVG 的 `图标值 + 130` 帧, 而战斗内的
三处物品图标绘制全部取自战斗初始化载入的 **Mu2.JVG** 对象, 帧号 = 图标值:

  0x434188 sub_434188  战场地面掉落物图标   frame = *(WORD*)(item + 8)
  0x439750 sub_439750  战斗道具菜单详情图标 frame = word_9DF8AC[4*槽] (436AD0 从 item+8 抄录)
  0x43B648 sub_43B648  战斗结算页物品图标   frame = item[4] (sub_42F8D4 查到的记录)

Mu2.JVG (57 块 / 107 帧) 帧号语义 (逐字节比对 Mu.JVG 实测, 见 docs/战斗中物品图标扩展支持.md):
  帧 0..75   = Mu.JVG 帧 130..205  → 物品图标 (图标值 0..75, 逐帧完全一致)
  帧 76..106 = 状态图标 1..31 (word_9D6F76 = sub_45408C(Mu2, 44) = 76)
               ≈ Mu 帧 242..272, 但 Mu2[86]/[87] (状态 11/12) 与 Mu[253]/[252]
               次序相反 (其余 29 帧完全一致) —— 战斗面板 (sub_437664)、战场
               头顶 (war_status_icons 用 76+(st-1)) 都按 Mu2 取帧。
即战斗内只有 0..75 号物品图标可解析 (原版 TKItem.dat 图标值恰为 0..75, 最大 75)。
MOD 把扩展图标追加到 Mu.JVG (图标值 ≥ 144 → Mu 帧 ≥ 274) 后, 菜单/商店正常
(帧 = 图标值 + 130), 战斗内帧号越界 (>= 107) 被 sub_4544EC 的
`if (a5 < a2[6])` 挡下 → 图标空白。

【修复】把战斗初始化刚载入的 Mu2 对象**原地重载为 Mu.JVG**, 并把 JVG 对象的
帧表整体前移 130 帧, 使对象内帧号重新等于"菜单帧号 - 130" = 图标值:

  [obj+8]  (帧→块表指针) += 130*2
  [obj+0xC](帧→子帧表指针) += 130*2
  [obj+0x18](总帧数)      -= 130

之后帧号 v → Mu.JVG 帧 v+130, 与菜单/商店**完全同源**:
  图标值 0..75   → Mu 130..205   (原版图标, 与 Mu2 帧 0..75 逐像素相同)
  图标值 76..143 → Mu 206..273   (菜单里同样是这些非图标帧, 语义一致)
  图标值 ≥ 144   → Mu 274+       (MOD 追加的扩展图标)
状态图标基准同步改为 Mu 帧 242 - 130 = 112 (word_9D6F76), 三处状态绘制
(sub_433690 硬编码 a2=21..30 / sub_437664 面板) 帧号公式不变。
另外**成对交换对象内帧 122/123 的表项** (即 Mu 帧 252/253), 抵消 Mu 与 Mu2
之间状态 11/12 的次序差异 → 31 个状态图标与 Mu2 原版逐像素一致, 补丁对
状态图标零影响 (见 STATUS_ORDER_SWAP_FRAME)。

【为什么不改绘制点】替换对象后三处物品绘制与三处状态绘制自动同时正确;
若改为"另建对象 + 三处改址", 需在三处 6 字节立即数位点上写运行时地址,
且状态图标仍从 Mu2 取, 反而引入两套帧号语义。

【对象所有权】对象本身由战斗初始化 `operator new(0x28)` 分配、战斗结束
sub_436DC0 用 sub_45388C(obj,3) 释放, 我们只重载其内容 (sub_453BD0 内部
先 sub_4538B4 释放旧块/关旧文件), 所有内部缓冲均由游戏自己的加载器分配,
释放路径与原生完全一致 —— 无新增内存、无泄漏、无悬垂指针。

【hook 点】0x430218 `mov edx,[0x755AF8]` (6 字节, 全 exe 唯一):
位于 42FEE0 战斗初始化内 `word_9D6F76 = sub_45408C(Mu2obj, 44)` (0x43020F)
之后, 因此 cave 里改写 word_9D6F76 不会被随后的初始化覆盖; 又是
`word_9D6F78 = sub_45408C(wm.JVG, 11)` 的取对象指令, 必须原样重放 (edx)。
cave 入口 = hook 点 -> E8 call; 结尾 ret 回到 0x43021E 继续原流程。

【安全】Mu.JVG 不存在/非 JVG 时 sub_453BD0 返回 0 且**未触碰对象**
(魔数检查在 sub_4538B4 之前) → test al,al 直接放弃, 战斗行为等于原版
(帧表位移与状态次序交换都在成功路径内, 失败路径一个字节都不改)。
Mu.JVG 帧数异常少时总帧数变负 (无符号比较恒不成立) → 只画不出图标, 不崩。

【寄存器/栈】pushad/popad 全保存; cld 明确方向标志; 调用按 cdecl 清栈
(add esp,N); 栈与调用方完全平衡, 只改 JVG 对象内部字段与两个全局字。

机器码 (141 字节):
  偏移 字节                        汇编                                   注释
  0000 60                          pushad
  0001 FC                          cld
  0002 A1 F4 5A 75 00               mov  eax, [0x755AF4]                   ; Mu2 对象
  0007 85 C0                       test eax, eax
  0009 74 7A                       jz   .done                             ; 未载入 → 收尾
  000B 68 12 79 4E 00               push 0x4E7912                          ; 第二参 "Mu.jvg"
  0010 A1 F4 5A 75 00               mov  eax, [0x755AF4]
  0015 50                          push eax                               ; 第一参 obj
  0016 B8 D0 3B 45 00               mov  eax, 0x453BD0                     ; sub_453BD0
  001B FF D0                       call eax
  001D 83 C4 08                    add  esp, 8
  0020 84 C0                       test al, al
  0022 74 61                       jz   .done                             ; 载入失败 → Mu2 原样
  0024 6A 00                       push 0                                 ; 第三参
  0026 6A FF                       push -1                                ; 第二参
  0028 A1 F4 5A 75 00               mov  eax, [0x755AF4]
  002D 50                          push eax                               ; 第一参 obj
  002E B8 0C 41 45 00               mov  eax, 0x45410C                     ; sub_45410C
  0033 FF D0                       call eax
  0035 83 C4 0C                    add  esp, 12
  0038 A1 F4 5A 75 00               mov  eax, [0x755AF4]
  003D 8B 48 08                    mov  ecx, [eax + 8]                    ; 帧→块表指针
  0040 81 C1 04 01 00 00            add  ecx, 260                          ; +130 项 (2B/项)
  0046 89 48 08                    mov  [eax + 8], ecx
  0049 8B 48 0C                    mov  ecx, [eax + 0xC]                  ; 帧→子帧表指针
  004C 81 C1 04 01 00 00            add  ecx, 260
  0052 89 48 0C                    mov  [eax + 0xC], ecx
  0055 81 68 18 82 00 00 00         sub  dword ptr [eax + 0x18], 130       ; 总帧数 -130
  005C 8B 48 08                    mov  ecx, [eax + 8]                    ; 状态次序还原:
  005F 81 C1 F4 00 00 00            add  ecx, 244                          ; 帧→块表 帧122/123
  0065 8B 11                       mov  edx, [ecx]                        ; 一次读两条表项
  0067 C1 C2 10                    rol  edx, 16                           ; 高低 16 位互换
  006A 89 11                       mov  [ecx], edx
  006C 8B 48 0C                    mov  ecx, [eax + 0xC]                  ; 帧→子帧表同样处理
  006F 81 C1 F4 00 00 00            add  ecx, 244
  0075 8B 11                       mov  edx, [ecx]
  0077 C1 C2 10                    rol  edx, 16
  007A 89 11                       mov  [ecx], edx
  007C 66 C7 05 76 6F 9D 00 70 00   mov  word ptr [0x9D6F76], 112          ; 状态基准帧
  0085 61                          popad
  0086 8B 15 F8 5A 75 00            mov  edx, [0x755AF8]                   ; 重放被替换指令
  008C C3                          ret                                    ; → 0x43021E
⚠ 编码铁律 (本 cave 三条都踩过, 由 unicorn 用例 test_tkitem_battle_icon 抓出):
  1) cdecl 参数逆序入栈: 被调用函数读 [esp+4] 为第一参 —— 原版调用点
     0x430148/0x43015B 即先 push 文件名 / push 0 / push -1, 最后 push 对象;
     顺序写反会把文件名指针当对象、对象指针当文件名。
  2) 立即数 > 127 必须用 imm32 形式 (81 /5): `83 68 18 82` 的 imm8 0x82 会按
     有符号扩展成 -126, 变成"总帧数 +126"; 同理 244 (0xF4) / 260 (0x104) 的
     表偏移也只能用 `81 C1 imm32`。
  3) 表项交换必须**成对**读改写 (32 位读 + rol 16 + 32 位写): 帧→块表与
     帧→子帧表都要交换, 只换一张表会把两个状态图标指向同一张图。

一致性核对: python tks_launcher_gui/patches/tkitem_expand/icon_cave.py
           (比对本文件生成的字节与 icon.json 的 cave_code)
"""
from __future__ import annotations

import json
import os

# ── 逆向常量 ────────────────────────────────────────────────
MU2_OBJ = 0x00755AF4          # 战斗初始化载入的 JVG 对象全局 (原为 Mu2.JVG)
MU_FILENAME = 0x004E7912      # exe 内已有的 "Mu.jvg" 字符串字面量
LOAD_JVG = 0x00453BD0         # char sub_453BD0(obj, char *filename)
LOAD_ALL_BLOCKS = 0x0045410C  # int sub_45410C(obj, int block, int a3)
REPLAY_INSN_ADDR = 0x00755AF8  # 重放的 mov edx,[0x755AF8]
STATUS_BASE = 0x009D6F76      # word_9D6F76: 状态图标基准帧
ICON_SHIFT = 130              # 图标值 + 130 = Mu.JVG 帧 (菜单侧同一约定)
STATUS_BASE_SHIFTED = 242 - ICON_SHIFT   # 112: Mu 帧 242 (状态图标 1) - 130

# Mu 帧 252/253 (状态 11/12) 与 Mu2 帧 86/87 次序相反 (逐字节比对实测:
# Mu2[86]==Mu[253], Mu2[87]==Mu[252]; 其余 29 帧 Mu2[76..106] 与 Mu[242..272]
# 完全一致)。重定位后对象内帧 122/123 = Mu 帧 252/253, 交换这两条表项即可
# 让战斗状态图标与原版 Mu2 逐像素一致。
STATUS_ORDER_SWAP_FRAME = 252
SWAP_ENTRY_OFFSET = (STATUS_ORDER_SWAP_FRAME - ICON_SHIFT) * 2   # 244: 对象内帧 122

# hook: 0x430218 的 6 字节 mov edx,[0x755AF8]
HOOK_PATTERN = "66 A3 76 6F 9D 00 83 C4 08 8B 15 F8 5A 75 00 6A 0B 52"
HOOK_OFFSET = 9               # pattern 起点 0x43020F -> hook 0x430218
HOOK_SIZE = 6


class _Asm:
    """极小标签汇编器 (仅本 cave 需要的编码)。"""

    def __init__(self):
        self.buf = bytearray()
        self.labels = {}
        self._fixups = []

    def label(self, name):
        self.labels[name] = len(self.buf)

    def emit(self, *values):
        self.buf.extend(values)

    def _rel8(self, opcode, target):
        self.buf.append(opcode)
        self._fixups.append((len(self.buf), target))
        self.buf.append(0)

    def jz(self, target):
        self._rel8(0x74, target)

    def finish(self):
        for pos, target in self._fixups:
            delta = self.labels[target] - (pos + 1)
            if not -128 <= delta <= 127:
                raise ValueError(f"rel8 越界: {target} -> {delta}")
            self.buf[pos] = delta & 0xFF
        return bytes(self.buf)


def build_cave() -> bytes:
    """生成 cave 机器码 (见模块 docstring 的逐字节清单)。"""
    a = _Asm()
    a.emit(0x60)                                  # pushad
    a.emit(0xFC)                                  # cld
    a.emit(0xA1, *MU2_OBJ.to_bytes(4, "little"))  # mov eax,[0x755AF4]
    a.emit(0x85, 0xC0)                            # test eax,eax
    a.jz("done")
    a.emit(0x68, *MU_FILENAME.to_bytes(4, "little"))   # push "Mu.jvg" (第二参)
    a.emit(0xA1, *MU2_OBJ.to_bytes(4, "little"))  # mov eax,[0x755AF4]
    a.emit(0x50)                                  # push eax (obj, 第一参)
    a.emit(0xB8, *LOAD_JVG.to_bytes(4, "little"))      # mov eax,sub_453BD0
    a.emit(0xFF, 0xD0)                            # call eax
    a.emit(0x83, 0xC4, 0x08)                      # add esp,8
    a.emit(0x84, 0xC0)                            # test al,al
    a.jz("done")
    a.emit(0x6A, 0x00)                            # push 0    (第三参)
    a.emit(0x6A, 0xFF)                            # push -1   (第二参)
    a.emit(0xA1, *MU2_OBJ.to_bytes(4, "little"))  # mov eax,[0x755AF4]
    a.emit(0x50)                                  # push eax (obj, 第一参)
    a.emit(0xB8, *LOAD_ALL_BLOCKS.to_bytes(4, "little"))
    a.emit(0xFF, 0xD0)                            # call eax
    a.emit(0x83, 0xC4, 0x0C)                      # add esp,12
    a.emit(0xA1, *MU2_OBJ.to_bytes(4, "little"))  # mov eax,[0x755AF4]
    a.emit(0x8B, 0x48, 0x08)                      # mov ecx,[eax+8]
    a.emit(0x81, 0xC1, *(ICON_SHIFT * 2).to_bytes(4, "little"))
    a.emit(0x89, 0x48, 0x08)                      # mov [eax+8],ecx
    a.emit(0x8B, 0x48, 0x0C)                      # mov ecx,[eax+0xC]
    a.emit(0x81, 0xC1, *(ICON_SHIFT * 2).to_bytes(4, "little"))
    a.emit(0x89, 0x48, 0x0C)                      # mov [eax+0xC],ecx
    a.emit(0x81, 0x68, 0x18, *ICON_SHIFT.to_bytes(4, "little"))  # sub [eax+0x18],130
    # 状态图标次序还原 (见 STATUS_ORDER_SWAP_FRAME 注释): 交换对象内帧 122/123
    # 的 (块, 子帧) 表项, 使状态 11/12 与 Mu2 原版一致。
    for table in (0x08, 0x0C):
        a.emit(0x8B, 0x48, table)                 # mov ecx,[eax+table]
        a.emit(0x81, 0xC1, *SWAP_ENTRY_OFFSET.to_bytes(4, "little"))
        a.emit(0x8B, 0x11)                        # mov edx,[ecx]  (两条相邻表项)
        a.emit(0xC1, 0xC2, 0x10)                  # rol edx,16     (高低 16 位互换)
        a.emit(0x89, 0x11)                        # mov [ecx],edx
    a.emit(0x66, 0xC7, 0x05, *STATUS_BASE.to_bytes(4, "little"),
           *STATUS_BASE_SHIFTED.to_bytes(2, "little"))   # mov word[9D6F76],112
    a.label("done")
    a.emit(0x61)                                  # popad
    a.emit(0x8B, 0x15, *REPLAY_INSN_ADDR.to_bytes(4, "little"))  # 重放
    a.emit(0xC3)                                  # ret
    return a.finish()


def build_operation() -> dict:
    """生成 icon.json 的 cave_hook 操作定义。"""
    return {
        "_format": 1,
        "_group": "── 战斗中物品图标 ──",
        "type": "cave_hook",
        "id": "tkitem_expand.battle_icon",
        "name": "战斗物品图标跟随 Mu.JVG",
        "desc": "战斗道具菜单/地面掉落/结算页的物品图标改用 Mu.JVG 帧表 "
                "(帧号 = 图标值 + 130 的重定位视图), 使 MOD 追加的扩展图标与 "
                "菜单/商店一致; 状态图标经表项交换与原版 Mu2 逐像素一致; "
                "仅当物品表出现 ≥ Mu2 总帧数的图标值且 Mu.JVG 存在时注入",
        "hook_pattern": HOOK_PATTERN,
        "hook_offset": HOOK_OFFSET,
        "hook_size": HOOK_SIZE,
        "hook_expect_count": 1,
        "cave_template": "tkitem_battle_icon",
        "cave_code": " ".join(f"{b:02X}" for b in build_cave()),
        "format": "TKSPATCH",
        "format_version": 1,
    }


def cave_code_hex() -> str:
    return " ".join(f"{b:02X}" for b in build_cave())


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "icon.json"), "r", encoding="utf-8") as stream:
        on_disk = json.load(stream)
    built = build_operation()
    same = on_disk.get("cave_code") == built["cave_code"]
    print(f"cave: {len(build_cave())} bytes")
    print(f"icon.json cave_code 一致: {same}")
    if not same:
        print("  icon.json:", on_disk.get("cave_code"))
        print("  生成     :", built["cave_code"])
        raise SystemExit(1)
    for key in ("hook_pattern", "hook_offset", "hook_size",
                "hook_expect_count", "type", "id"):
        if on_disk.get(key) != built[key]:
            print(f"  [不一致] {key}: {on_disk.get(key)!r} != {built[key]!r}")
            raise SystemExit(1)
    print("hook 字段一致: True")
