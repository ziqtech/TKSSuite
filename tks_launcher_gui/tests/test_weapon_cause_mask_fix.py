# -*- coding: utf-8 -*-
"""武器附加状态修复 (weapon_cause_mask_hook) — 根因、修法与消费点核验。

【用户反馈】只装备带状态的武器时普攻能附加状态; 一旦再装备衣服/饰品, 普攻再也不附加。

【根因 (2026-09-15 定位)】原版装备重算 `sub_42234C` @0x42234C 遍历 4 个装备槽
   (单位记录字偏移 69..72 = 字节 0x8A..0x90), 对每个非空槽取该装备 TKItem 的字
   26/27 (cause_mask 低/高, TKItem 字节 52/54), 写进单位记录字偏移 67/68 (字节 0x86/0x88):

     42263f  66 8b 41 34        mov ax, [ecx+0x34]      ; TKItem.cause_mask1
     422643  66 89 82 86 00..  mov [edx+0x86], ax      ; ★ 赋值 (不是 or)
     422650  66 8b 41 36        mov ax, [ecx+0x36]      ; TKItem.cause_mask2
     422654  66 89 82 88 00..  mov [edx+0x88], ax      ; ★ 赋值 (不是 or)
     42265b  66 ff 45 fc        inc word [ebp-4]        ; 下一槽

   于是『最后一个非空槽』覆盖前面所有槽的结果: 只装武器 → 掩码 = 武器; 再装衣服/饰品
   (槽 1/2) → 武器掩码被覆盖成它们自己的 (通常 0) → 普攻再也带不出武器附加状态。

【消费点 (为什么这个字段就是武器附加状态)】普攻 (word_9D6C7C == -1) 的命中附加状态在
   `sub_4400DC` @0x441C08~0x441C5B:

     441c08  66 83 7d 08 00           cmp word [ebp+8], 0
     441c0d  7c 54                    jl  441c63              ; 攻击者无效 → 跳过
     441c0f  66 83 3d 7c 6c 9d 00 ff  cmp word [0x9d6c7c], -1  ; 仅普攻
     441c17  75 4a                    jne 441c63
     441c2f  66 8b 14 45 02 71 9d 00  mov dx, [eax*2+0x9d7102] ; 单位记录字 68 = cause2
     441c48  66 8b 14 45 00 71 9d 00  mov dx, [eax*2+0x9d7100] ; 单位记录字 67 = cause1
     441c5b  e8 20 24 ff ff           call sub_434080         ; 入队附加状态

   `word_9D7100/9D7102` = 战斗单位数组 (0x9D707A) + 0x86/0x88 —— 正是 sub_42234C 写的那两个
   字段。sub_434080 里 `if (a6+a5+a4+a3)` 全 0 直接不入队, 所以被覆盖成 0 时连队列都进不去。

【修法】把 0x422643 / 0x422654 两条 `mov` 改成等长的 `or` (opcode 89 → 09):
   各装备槽的 cause_mask 取并集。单武器行为完全不变, 武器+衣服/饰品恢复正常。
   24 字节模式含相邻取值指令, 原版 exe 唯一命中 (文件 0x22043 = RVA 0x22643),
   全文件仅 2 字节变化。

本测试不依赖 exe 也能校验定义与语义; 找得到原版 exe 时再补做唯一命中/单字节差异/
消费点存在性/与其它补丁零重叠。
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

PATCH_ID = "weapon_cause_mask_hook"
PATCH_DIR = ROOT / "tks_launcher_gui" / "patches"
THIS_DIR = PATCH_DIR / PATCH_ID

TEXT_RVA, TEXT_RAW = 0x1000, 0xA00
RVA_ASSIGN_LO = 0x22643               # mov [edx+0x86], ax
RVA_ASSIGN_HI = 0x22654               # mov [edx+0x88], ax
OP_MOV_RM16_R16, OP_OR_RM16_R16 = 0x89, 0x09

# 装备重算里的取值来源: TKItem 字 26/27 = 字节 52/54 = cause_mask 低/高
TKITEM_CAUSE_LO_WORD, TKITEM_CAUSE_HI_WORD = 0x34, 0x36
UNIT_CAUSE_LO_BYTE, UNIT_CAUSE_HI_BYTE = 0x86, 0x88

# 消费点 (普攻命中附加状态) 的特征
PAT_NORMAL_ATTACK_GUARD = "66 83 7D 08 00 7C 54 66 83 3D 7C 6C 9D 00 FF 75 4A"
PAT_READ_UNIT_CAUSE_HI = "66 8B 14 45 02 71 9D 00"
PAT_READ_UNIT_CAUSE_LO = "66 8B 14 45 00 71 9D 00"

_EXE_CANDIDATES = (
    os.environ.get("TKS_VANILLA_EXE", ""),
    r"游戏目录（原版）/TKS.exe",
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


def _entries(p):
    """把 patch 定义统一成 [(pattern, replace, expect)]。"""
    if getattr(p, "patterns", None):
        return [(e.get("pattern", ""),
                 {int(k): v for k, v in (e.get("replace") or {}).items()},
                 e.get("expect_count", 0)) for e in p.patterns]
    return [(p.pattern, {int(k): v for k, v in (p.replace or {}).items()},
             p.expect_count)]


def _equip_accumulate(slots, assign: bool):
    """复刻 sub_42234C 装备槽循环 (字 67/68 = cause_mask 低/高)。"""
    lo = hi = 0
    for item in slots:                      # None = 空槽 (-1)
        if item is None:
            continue
        cause_lo, cause_hi = item
        if assign:                          # 原版: 赋值 → 最后一个非空槽胜出
            lo, hi = cause_lo, cause_hi
        else:                               # 修复: 并集
            lo |= cause_lo
            hi |= cause_hi
    return lo, hi


class WeaponCauseMaskFixTests(unittest.TestCase):

    def test_patch_definition(self):
        p = _load_patch()
        self.assertEqual(p.type, "patch_bytes",
                         "应改为直接修根因的字节补丁, 不再是 cave_hook")
        self.assertEqual(p.id, PATCH_ID)
        self.assertEqual(p.name, "武器附加状态修复")
        self.assertEqual(p.expect_count, 1)
        self.assertEqual({int(k): v for k, v in p.replace.items()},
                         {1: OP_OR_RM16_R16, 18: OP_OR_RM16_R16})
        self.assertFalse(p.optional, "该补丁是必选修复 (与原定义一致)")
        # 旧 cave 必须撤掉
        self.assertFalse(getattr(p, "cave_code", None), "不应再带 cave_code")
        self.assertFalse(getattr(p, "cave_code_file", None))
        self.assertFalse(getattr(p, "hook_pattern", None), "不应再有 hook")
        self.assertFalse((THIS_DIR / "cave_code.py").exists(),
                         "旧 cave 源文件应已移除")

    def test_pattern_targets_both_assignments(self):
        self.assertIsNotNone(_cs, "需要 capstone")
        p = _load_patch()
        raw = bytes.fromhex(p.pattern.replace(" ", ""))
        insns = _disasm(raw, 0x400000 + RVA_ASSIGN_LO)
        self.assertEqual(sum(i.size for i in insns), len(raw),
                         "模式必须按指令边界对齐")
        # 两条赋值指令 (mov r/m16, r16: 66 89 /r) —— 只挑写单位记录 0x86/0x88 的那两条
        want = ("word ptr [edx + 0x86], ax", "word ptr [edx + 0x88], ax")
        movs = [i for i in insns
                if i.mnemonic == "mov" and i.op_str in want]
        self.assertEqual([i.op_str for i in movs], list(want),
                         f"模式应含两条目标 mov, 实得 {[i.op_str for i in movs]}")
        # replace 偏移必须正好落在这两条指令的 opcode 上 (89 → 09 = mov → or)
        for off, ins in zip((1, 18), movs):
            self.assertEqual(raw[off], OP_MOV_RM16_R16)
            self.assertEqual(ins.bytes[1], OP_MOV_RM16_R16)
            self.assertEqual(ins.address - 0x400000,
                             RVA_ASSIGN_LO if ins is movs[0] else RVA_ASSIGN_HI)
        # 改完 = 同操作数的 or, 其余指令逐条不变
        patched = bytearray(raw)
        patched[1] = OP_OR_RM16_R16
        patched[18] = OP_OR_RM16_R16
        after = _disasm(bytes(patched), 0x400000 + RVA_ASSIGN_LO)
        self.assertEqual(sum(i.size for i in after), len(patched))
        ors = [i for i in after if i.mnemonic == "or" and "ax" in i.op_str]
        self.assertEqual([i.op_str for i in ors],
                         ["word ptr [edx + 0x86], ax",
                          "word ptr [edx + 0x88], ax"])
        self.assertEqual([f"{i.mnemonic} {i.op_str}" for i in after
                          if i.mnemonic not in ("mov", "or")],
                         [f"{i.mnemonic} {i.op_str}" for i in insns
                          if i.mnemonic not in ("mov", "or")])
        # 取值来源仍是 TKItem 字 27 (cause_mask 高); 字 26 的读取在模式起点之前一条,
        # 由 test_consumption_path_reads_the_same_field 在 exe 上整段核验
        text = "\n".join(f"{i.mnemonic} {i.op_str}" for i in insns).lower()
        self.assertIn(f"word ptr [ecx + {TKITEM_CAUSE_HI_WORD:#x}]", text)

    def test_consumption_path_reads_the_same_field(self):
        """锁定证据链: 普攻命中附加状态消费的就是被修的那两个字。"""
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        data = exe.read_bytes()
        expect = {
            "普攻守卫 (@0x441C08)": (PAT_NORMAL_ATTACK_GUARD, 0x41608),
            "读单位字 68 = cause2": (PAT_READ_UNIT_CAUSE_HI, 0x4162F),
            "读单位字 67 = cause1": (PAT_READ_UNIT_CAUSE_LO, 0x41648),
            "装备循环写 字67": ("66 8B 41 34 66 89 82 86 00 00 00", 0x2203F),
            "装备循环写 字68": ("66 8B 41 36 66 89 82 88 00 00 00", 0x22050),
            "装备循环初始化 字67=0": ("66 C7 80 86 00 00 00 00 00", 0x21E4E),
            "装备槽指针 lea +0x8A": ("8D 90 8A 00 00 00", 0x21E96),
        }
        for tag, (pat_s, want) in expect.items():
            pat, wc = parse_pattern(pat_s)
            hits = pattern_scan(data, pat, wc)
            self.assertEqual(hits, [want], f"{tag}: 命中位置不符 {[hex(h) for h in hits]}")
        # 0x9D707A + 0x86 == 0x9D7100 (消费点读的就是单位记录字 67)
        self.assertEqual(0x9D707A + UNIT_CAUSE_LO_BYTE, 0x9D7100)
        self.assertEqual(0x9D707A + UNIT_CAUSE_HI_BYTE, 0x9D7102)

    def test_semantic_model_reproduces_the_bug(self):
        """装备槽循环: 原版赋值 = 最后一个非空槽胜出; 修复取并集。"""
        weapon = (0x0002, 0x0000)          # 武器附加状态位
        armor = (0x0000, 0x0000)           # 衣服 (无 cause_mask)
        trinket = (0x0001, 0x0000)         # 饰品 (自己的 cause_mask)
        # 只带武器: 修前修后一致 (用户实测的"能触发"场景)
        self.assertEqual(_equip_accumulate([weapon], assign=True), weapon)
        self.assertEqual(_equip_accumulate([weapon], assign=False), weapon)
        # 武器 + 衣服: 原版被衣服 (0) 覆盖 → 状态丢失 (用户报告的 bug)
        self.assertEqual(_equip_accumulate([weapon, armor], assign=True), (0, 0))
        self.assertEqual(_equip_accumulate([weapon, armor], assign=False), weapon)
        # 武器 + 饰品: 原版变成饰品的掩码, 修复后是并集
        self.assertEqual(_equip_accumulate([weapon, trinket], assign=True), trinket)
        self.assertEqual(_equip_accumulate([weapon, trinket], assign=False),
                         (0x0003, 0x0000))
        # 空槽不参与, 与槽位顺序无关
        self.assertEqual(_equip_accumulate([None, weapon, armor, None], assign=False),
                         weapon)
        self.assertEqual(_equip_accumulate([weapon, None, None, None], assign=False),
                         weapon)

    def test_applies_as_two_byte_change(self):
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        p = _load_patch()
        data = bytearray(exe.read_bytes())
        before = bytes(data)
        for pat_s, repl, expect in _entries(p):
            pat, wc = parse_pattern(pat_s)
            hits = pattern_scan(bytes(data), pat, wc)
            self.assertEqual(len(hits), expect, f"模式应命中 {expect} 处, 实得 {hits}")
            for off in hits:
                for ro, val in repl.items():
                    data[off + ro] = val & 0xFF
        diff = [i for i in range(len(data)) if data[i] != before[i]]
        self.assertEqual(len(diff), 2, f"只允许改 2 个字节, 实得 {[hex(i) for i in diff]}")
        self.assertEqual({i - TEXT_RAW + TEXT_RVA for i in diff},
                         {RVA_ASSIGN_LO + 1, RVA_ASSIGN_HI + 1})
        self.assertEqual({before[i] for i in diff}, {OP_MOV_RM16_R16})
        self.assertEqual({data[i] for i in diff}, {OP_OR_RM16_R16})

    def test_no_other_patch_writes_into_the_same_range(self):
        exe = _vanilla_exe()
        if exe is None:
            self.skipTest("未找到原版 TKS.exe (可用 TKS_VANILLA_EXE 指定)")
        data = exe.read_bytes()
        p = _load_patch()
        ranges = []
        for pat_s, repl, _expect in _entries(p):
            pat, wc = parse_pattern(pat_s)
            for h in pattern_scan(data, pat, wc):
                ks = sorted(repl) or [0]
                ranges.append((h + ks[0], h + ks[-1] + 1))
        cfg = load_patch_directory(str(PATCH_DIR), log_func=lambda *_a: None)
        for other in cfg.patches:
            if other.id == PATCH_ID:
                continue
            if other.type == "patch_sites":
                for site in (getattr(other, "sites", None) or []):
                    rva = int(str(site["rva"]), 16)
                    ln = len(bytes.fromhex(str(site["expect"]).replace(" ", "")))
                    fo = rva - TEXT_RVA + TEXT_RAW
                    for lo, hi in ranges:
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
                for h in pattern_scan(data, op, owc):
                    ks = sorted(int(k) for k in repl.keys()) or [0]
                    s0, s1 = h + ks[0], h + ks[-1] + 1
                    for lo, hi in ranges:
                        self.assertFalse(s0 < hi and s1 > lo,
                                         f"{other.id} 的写入区间与本补丁重叠")


if __name__ == "__main__":
    unittest.main()
