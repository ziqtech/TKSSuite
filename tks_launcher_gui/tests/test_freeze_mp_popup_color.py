# -*- coding: utf-8 -*-
"""冰冻(状态 23)扣内力飘字颜色补丁 — 定义与该修复的语义来源核验。

【现象】#37 冰雪术 命中后角色中 23 冰冻, 每回合扣的是**内力**, 飘字却是红色;
   灭灵击(#64)等内力伤害的飘字是紫色。

【逆向结论】飘字颜色 = 调色板索引:
   - 回合状态结算 `sub_43292C` 调 `sub_433690(单位, 图标id, 画图标, 数值, 颜色索引)`;
   - 技能/伤害结算 `sub_4400DC` 调 `sub_433F04(帧, 目标, 数值, 颜色索引)`;
   - 两者最终都走 `sub_44B028(textobj, 索引)` → 查 `dword_A2C528[索引]` (索引 < 0x20)。
   原版颜色词表 (由本测试从原版 exe 反汇编还原并锁定):
     0x12 物理/生命伤害(红)   0x17 物理伤害(奇数段)   0x14 生命恢复
     0x15 内力恢复            0x1C 内力伤害(紫)        0x1F 未命中

   `sub_43292C` 内 8 个状态扣减/恢复分支的 (状态, 颜色) 实测表:
     0x432C7B 状态 22 燃烧 扣 HP → 0x12
     0x432CFE 状态 23 冰冻 扣 MP → 0x12   ← **唯一错配**, 应为 0x1C
     0x432DB0 状态 27 中毒 扣 HP → 0x12
     0x432E4A 状态 27 中毒 扣 MP → 0x1C
     0x432F1B 状态 21 诅咒 扣 HP → 0x12
     0x432FAE 状态 21 诅咒 扣 MP → 0x1C
     0x43307B 状态 30 针灸 回 HP → 0x14
     0x433131 状态 30 针灸 回 MP → 0x15

   本测试不依赖 exe 也能校验补丁定义与它声称的语义一致 (模式 → 指令 / replace 偏移 →
   颜色立即数); 若能找到原版 exe, 再补做: 唯一命中、单字节差异、状态颜色表锁定、
   与其它补丁零重叠。
"""
import os
import sys
import unittest
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tks_launcher_gui")):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.exe_builder import pattern_scan                      # noqa: E402
from core.scanner import parse_pattern                         # noqa: E402
from core.tkspatch_loader import load_patch_directory          # noqa: E402

try:
    import capstone as _cs
except Exception:                                              # pragma: no cover
    _cs = None

PATCH_ID = "freeze_mp_popup_color"
PATCH_DIR = ROOT / "tks_launcher_gui" / "patches"

IMAGE_BASE = 0x400000
TEXT_RVA, TEXT_RAW = 0x1000, 0xA00          # .text: RVA 0x1000 ← 文件 0xA00

ADDR_STATUS_ROUTINE = 0x433690              # sub_433690(单位, 图标id, 画图标, 数值, 颜色)
ADDR_POPUP_QUEUE = 0x433F04                 # sub_433F04(帧, 目标, 数值, 颜色)
RVA_TARGET = 0x32CEA                        # 冰冻分支 push 颜色

COLOR_DMG_HP = 0x12                         # 物理/生命伤害 红
COLOR_DMG_MP = 0x1C                         # 内力伤害 紫 (灭灵击所用)
COLOR_HEAL_HP, COLOR_HEAL_MP = 0x14, 0x15
COLOR_MISS = 0x1F

ST_BURN, ST_FREEZE, ST_POISON, ST_CURSE, ST_ACUPUNCTURE = 22, 23, 27, 21, 30

# sub_43292C 内 8 个分支: (call 的 VA, 状态id, 颜色索引)。patch 前原版实测值。
STATUS_TABLE_PRE = (
    (0x432C7B, ST_BURN, COLOR_DMG_HP),
    (0x432CFE, ST_FREEZE, COLOR_DMG_HP),          # ← 待修 (扣内力却是红)
    (0x432DB0, ST_POISON, COLOR_DMG_HP),
    (0x432E4A, ST_POISON, COLOR_DMG_MP),
    (0x432F1B, ST_CURSE, COLOR_DMG_HP),
    (0x432FAE, ST_CURSE, COLOR_DMG_MP),
    (0x43307B, ST_ACUPUNCTURE, COLOR_HEAL_HP),
    (0x433131, ST_ACUPUNCTURE, COLOR_HEAL_MP),
)

# 技能侧 (sub_4400DC) 用到的飘字颜色: 只允许出现这几个词表项
SKILL_COLOR_VOCAB = {COLOR_DMG_HP, 0x17, COLOR_HEAL_HP, COLOR_HEAL_MP,
                     COLOR_DMG_MP, COLOR_MISS}

_EXE_CANDIDATES = (
    os.environ.get("TKS_VANILLA_EXE", ""),
)


def _load_patch():
    cfg = load_patch_directory(str(PATCH_DIR), log_func=lambda *_a: None)
    return next(p for p in cfg.patches if p.id == PATCH_ID)


def _vanilla_exe():
    for cand in _EXE_CANDIDATES:
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def _disasm(code: bytes, addr: int):
    md = _cs.Cs(_cs.CS_ARCH_X86, _cs.CS_MODE_32)
    return list(md.disasm(code, addr))


def _off_of_rva(rva: int) -> int:
    return rva - TEXT_RVA + TEXT_RAW


def _call_arg_pushes(insns, n: int, count: int):
    """从第 n 条指令往前收集最近的 count 个 push —— 即 cdecl 的实参 (逆序)。"""
    pushes = []
    for j in range(n - 1, max(0, n - 60), -1):
        if insns[j].mnemonic == "push":
            pushes.append(insns[j].op_str)
            if len(pushes) == count:
                break
    return pushes


def _status_branch_table(data: bytes):
    """还原 sub_43292C 的 (call VA, 状态id, 颜色) —— push 顺序 = 实参逆序。"""
    code = data[_off_of_rva(0x3292C):_off_of_rva(0x33400)]
    insns = _disasm(code, IMAGE_BASE + 0x3292C)
    table = []
    for n, ins in enumerate(insns):
        if ins.mnemonic != "call" or ins.op_str != f"{ADDR_STATUS_ROUTINE:#x}":
            continue
        pushes = _call_arg_pushes(insns, n, 5)
        if len(pushes) != 5:
            continue
        _unit, status, flag, _value, color = pushes      # a1..a5
        table.append((ins.address, int(status, 16), int(color, 16), flag))
    return table


def _skill_popup_colors(data: bytes):
    """还原 sub_4400DC 里 sub_433F04 的第 4 参 (颜色) 使用集合。"""
    code = data[_off_of_rva(0x400DC):_off_of_rva(0x42A00)]
    insns = _disasm(code, IMAGE_BASE + 0x400DC)
    colors = []
    for n, ins in enumerate(insns):
        if ins.mnemonic != "call" or ins.op_str != f"{ADDR_POPUP_QUEUE:#x}":
            continue
        pushes = _call_arg_pushes(insns, n, 4)
        if len(pushes) != 4:
            continue
        colors.append(int(pushes[3], 16))                # a4 = 颜色
    return colors


class FreezePopupColorPatchTests(unittest.TestCase):

    def test_patch_definition(self):
        p = _load_patch()
        self.assertEqual(p.type, "patch_bytes")
        self.assertEqual(p.expect_count, 1)
        self.assertEqual({int(k): v for k, v in p.replace.items()}, {1: COLOR_DMG_MP})
        self.assertTrue(p.optional, "应可在启动器里开关")
        self.assertTrue(p.default_checked, "默认勾选 (推荐)")
        self.assertIn(f"6A {ST_FREEZE:02X}", p.pattern.upper())   # 状态 23
        self.assertIn("58 6F 9D 00", p.pattern.upper())           # [0x9D6F58] 单位号

    def test_pattern_encodes_freeze_branch(self):
        self.assertIsNotNone(_cs, "需要 capstone")
        p = _load_patch()
        raw = bytes.fromhex(p.pattern.replace(" ", ""))
        insns = _disasm(raw, 0x432CEA)
        self.assertEqual(sum(i.size for i in insns), len(raw),
                         "模式必须按指令边界对齐 (不可切在指令中间)")
        self.assertEqual(raw[0], 0x6A, "首字节应是 push imm8 的 opcode")
        # ① 头 = push 颜色 (被替换的目标)
        self.assertEqual(insns[0].mnemonic, "push")
        self.assertEqual(insns[0].op_str, f"{COLOR_DMG_HP:#x}",
                         "原版此处是 0x12 (物理红) —— 正是要改的字节")
        # ② 尾 = 调用颜色/状态例程
        self.assertEqual(insns[-1].mnemonic, "call")
        self.assertEqual(insns[-1].op_str, f"{ADDR_STATUS_ROUTINE:#x}")
        # ③ 参数装配里含状态 23 与单位号 word_9D6F58
        text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in insns).lower()
        self.assertIn(f"push {ST_FREEZE:#x}", text)
        self.assertIn("[0x9d6f58]", text)
        # ④ replace 偏移指向那条 push 的立即数, 改后其余指令一字不动
        off = 1
        self.assertEqual(raw[off], COLOR_DMG_HP)
        patched = bytearray(raw)
        patched[off] = COLOR_DMG_MP
        after = _disasm(bytes(patched), 0x432CEA)
        self.assertEqual(sum(i.size for i in after), len(patched))
        self.assertEqual(after[0].mnemonic, "push")
        self.assertEqual(after[0].op_str, f"{COLOR_DMG_MP:#x}")
        self.assertEqual([f"{i.mnemonic} {i.op_str}" for i in after[1:]],
                         [f"{i.mnemonic} {i.op_str}" for i in insns[1:]])

    def test_status_color_table_locked(self):
        """锁定 sub_43292C 的 8 个分支颜色 —— 冰冻是唯一的『扣内力用红色』。"""
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        got = _status_branch_table(exe.read_bytes())
        self.assertEqual([(va, st, col) for va, st, col, _f in got],
                         list(STATUS_TABLE_PRE))
        self.assertTrue(all(f == "1" for *_x, f in got), "画图标标志应为 1")
        # 约定自检: 扣内力的分支里, 除冰冻外全部已是 0x1C
        mp_branches = [(va, st, col) for va, st, col, _f in got
                       if (va, st, col) in ((0x432E4A, ST_POISON, COLOR_DMG_MP),
                                            (0x432FAE, ST_CURSE, COLOR_DMG_MP))]
        self.assertEqual(mp_branches,
                         [(0x432E4A, ST_POISON, COLOR_DMG_MP),
                          (0x432FAE, ST_CURSE, COLOR_DMG_MP)])
        freeze = [t for t in got if t[1] == ST_FREEZE]
        self.assertEqual(freeze, [(0x432CFE, ST_FREEZE, COLOR_DMG_HP, "1")],
                         "冰冻扣内力仍是红色 —— 这就是本补丁要修的错配")

    def test_skill_side_uses_same_palette(self):
        """技能侧 (灭灵击等内力伤害) 用的就是 0x1C —— 修复目标色有据可依。"""
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        colors = _skill_popup_colors(exe.read_bytes())
        self.assertTrue(colors, "应能还原 sub_4400DC 的飘字颜色")
        self.assertTrue(set(colors) <= SKILL_COLOR_VOCAB,
                        f"出现词表外的颜色: {sorted(set(colors) - SKILL_COLOR_VOCAB)}")
        self.assertIn(COLOR_DMG_MP, colors, "内力伤害必须使用紫色 0x1C")
        self.assertIn(COLOR_DMG_HP, colors)
        self.assertNotIn(0x13, colors)

    def test_applies_as_single_byte_change(self):
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        p = _load_patch()
        data = bytearray(exe.read_bytes())
        pat, wc = parse_pattern(p.pattern)
        hits = pattern_scan(bytes(data), pat, wc)
        self.assertEqual(len(hits), 1, f"模式必须唯一命中, 实得 {hits}")
        hit = hits[0]
        self.assertEqual(hit + TEXT_RVA - TEXT_RAW, RVA_TARGET,
                         "命中位置应是冰冻分支 (RVA 0x32CEA)")
        before = bytes(data)
        for off, val in {int(k): v for k, v in p.replace.items()}.items():
            data[hit + off] = val & 0xFF
        diff = [i for i in range(len(data)) if data[i] != before[i]]
        self.assertEqual(diff, [hit + 1], "只允许改动 1 个字节")
        self.assertEqual((before[hit + 1], data[hit + 1]),
                         (COLOR_DMG_HP, COLOR_DMG_MP))
        # 打完补丁后颜色表唯一变化就是冰冻那一项
        post = _status_branch_table(bytes(data))
        expected_post = [(va, st, COLOR_DMG_MP if (va, st) == (0x432CFE, ST_FREEZE)
                           else col) for va, st, col in STATUS_TABLE_PRE]
        self.assertEqual([(va, st, col) for va, st, col, _f in post],
                         expected_post)
        self.assertEqual([c for c in _skill_popup_colors(bytes(data))],
                         _skill_popup_colors(before), "技能侧不应被改动")

    def test_no_other_patch_writes_into_the_same_range(self):
        """本补丁区间不得与任何现有补丁的写入范围重叠 (否则会互相踩)。"""
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        data = exe.read_bytes()
        p = _load_patch()
        pat, wc = parse_pattern(p.pattern)
        hit = pattern_scan(data, pat, wc)[0]
        lo, hi = hit, hit + len(pat)
        cfg = load_patch_directory(str(PATCH_DIR), log_func=lambda *_a: None)
        for other in cfg.patches:
            if other.id == PATCH_ID:
                continue
            if other.type == "patch_sites":
                for site in (getattr(other, "sites", None) or []):
                    rva = int(str(site["rva"]), 16)
                    ln = len(bytes.fromhex(str(site["expect"]).replace(" ", "")))
                    fo = _off_of_rva(rva)
                    self.assertFalse(fo < hi and fo + ln > lo,
                                     f"{other.id} 位点 0x{rva:X} 与本补丁区间重叠")
                continue
            entries = []
            if getattr(other, "pattern", ""):
                entries.append((other.pattern, other.replace or {}))
            for e in (getattr(other, "patterns", None) or []):
                entries.append((e.get("pattern", ""), e.get("replace") or {}))
            if getattr(other, "hook_pattern", ""):
                entries.append((other.hook_pattern, {}))
            for pat_s, repl in entries:
                if not pat_s:
                    continue
                op, owc = parse_pattern(pat_s)
                spans = [(h, h + len(op)) for h in pattern_scan(data, op, owc)]
                if repl:
                    ks = [int(k) for k in repl.keys()]
                    spans = [(h + min(ks), h + max(ks) + 1) for h, _e in spans]
                for s0, s1 in spans:
                    self.assertFalse(s0 < hi and s1 > lo,
                                     f"{other.id} 的写入区间与本补丁重叠")


if __name__ == "__main__":
    unittest.main()
