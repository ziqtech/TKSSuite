"""燃烧补丁的位点安全性、机器码语义及原版伤害路径回归。"""
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tks_launcher_gui.core import patch_engine
from tks_launcher_gui.core.config_loader import PatchSettings
from tks_launcher_gui.core.exe_builder import (
    CaveBuildResult, ExeBuilder, SitesPatchItem, parse_pe, rva_to_offset,
)
from tks_launcher_gui.core.scanner import parse_pattern, pattern_scan
from tks_launcher_gui.core.tkspatch_loader import load_patch_directory

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
        UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
    )
    HAS_EMULATOR = True
except ImportError:
    HAS_EMULATOR = False

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / "tks_launcher_gui" / "patches"
CODE_BASE = 0x401000
CODE_SIZE = 0x80000
CAVE_BASE = 0x70000000
BP = 0x2008000


def load_patch():
    return next(p for p in load_patch_directory(str(PATCHES)).patches
                if p.id == "burning_damage_fix")


def install(defn, code, writer, cave_base=CAVE_BASE):
    def write_memory(handle, address, data):
        writer(address, data)
        return len(data)

    ctx = SimpleNamespace(
        defn=defn, log=lambda _: None, cave_addr=cave_base,
        warpc_base=0, h_proc=0, code_start_addr=CODE_BASE, code_buf=code,
    )
    with patch.object(patch_engine, "write_pm", side_effect=write_memory), \
            patch.object(patch_engine, "vp_ex", return_value=0x20):
        return patch_engine._handle_patch_sites(ctx)


class BurningPatchDefinitionTests(unittest.TestCase):
    def test_definition_and_cave_layout(self):
        p = load_patch()
        self.assertEqual(p.type, "patch_sites")
        self.assertTrue(p.optional)
        self.assertTrue(p.default_checked)
        self.assertTrue(p.autolayout_cave)
        self.assertEqual(p.cave_entries, {"mp_damage": 0, "mp_evaluation": 26})
        self.assertEqual(len(p._cave_code_bytes), 62)
        self.assertEqual([int(s["rva"], 16) for s in p.sites], [0x420F3, 0x3F99F])

    def test_automatic_layout_with_existing_patches(self):
        cfg = load_patch_directory(str(PATCHES))
        layout = patch_engine._build_cave_layout(cfg, CAVE_BASE, PatchSettings(), lambda _: None)
        p = next(p for p in cfg.patches if p.id == "burning_damage_fix")
        slot = next(s for s in layout.slots if s.owner_id == p.id)
        self.assertFalse(getattr(p, "_layout_error", ""))
        self.assertEqual(slot.size, 62)
        self.assertEqual(slot.offset % 16, 0)
        self.assertEqual(p._resolved_cave_offset, slot.offset)
        for other in layout.slots:
            if other is not slot:
                self.assertTrue(other.offset >= slot.end() or other.end() <= slot.offset)
        writes = patch_engine._resolve_sites_writes(p, CAVE_BASE + slot.offset)
        for rva, _, replacement, tag in writes:
            target = 0x400000 + rva + 5 + struct.unpack_from("<i", replacement, 1)[0]
            self.assertIn(target, [CAVE_BASE + slot.offset + n for n in p.cave_entries.values()])

    def test_any_site_mismatch_leaves_both_hooks_untouched(self):
        p = load_patch()
        for bad_site in p.sites:
            with self.subTest(rva=bad_site["rva"]):
                code = bytearray(CODE_SIZE)
                for site in p.sites:
                    off = int(site["rva"], 16) - 0x1000
                    raw = bytes.fromhex(site["expect"])
                    code[off:off + len(raw)] = raw
                code[int(bad_site["rva"], 16) - 0x1000] ^= 1
                before = bytes(code)
                writes = []
                self.assertFalse(install(p, code, lambda a, b: writes.append((a, b))))
                self.assertEqual(bytes(code), before)
                self.assertTrue(all(a == CAVE_BASE for a, _ in writes))


@unittest.skipUnless(HAS_EMULATOR, "需要已安装的 unicorn 和 capstone")
class BurningMachineCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = os.environ.get("TKS_VANILLA_EXE")
        if not exe:
            raise unittest.SkipTest("用 TKS_VANILLA_EXE 指定原版 EXE；不会启动游戏")
        cls.exe = Path(exe)
        cls.raw = cls.exe.read_bytes()
        cls.pe = parse_pe(cls.raw)
        cls.defn = load_patch()
        cls.image = bytearray(cls.pe.size_of_image)
        for section in cls.pe.sections:
            start = section.virtual_addr
            cls.image[start:start + section.raw_size] = cls.raw[
                section.raw_offset:section.raw_offset + section.raw_size]
        for site in cls.defn.sites:
            rva = int(site["rva"], 16)
            expected = bytes.fromhex(site["expect"])
            if bytes(cls.image[rva:rva + len(expected)]) != expected:
                raise AssertionError(f"原版位点不符: {site['rva']}")

    def machine(self, patched=True, cave_base=CAVE_BASE):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0x400000, (len(self.image) + 0xFFF) & ~0xFFF)
        u.mem_write(0x400000, bytes(self.image))
        u.mem_write(0x9D0000, bytes(0x18000))
        u.mem_map(BP - 0x8000, 0x10000)
        u.mem_map(cave_base, 0x1000)
        u.reg_write(UC_X86_REG_EBP, BP)
        u.reg_write(UC_X86_REG_ESP, BP - 0x1000)
        if patched:
            code = bytearray(u.mem_read(CODE_BASE, CODE_SIZE))
            self.assertTrue(install(self.defn, code, u.mem_write, cave_base))
        return u

    def w16(self, u, address, value):
        u.mem_write(address, struct.pack("<H", value & 0xFFFF))

    def w32(self, u, address, value):
        u.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def r32(self, u, address):
        return struct.unpack("<i", u.mem_read(address, 4))[0]

    def execute(self, u, start, stop):
        u.emu_start(start, stop, count=20000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), stop)

    def damage(self, *, hp=0, mp=0, skill=64, category=1, flags=4,
               burning=(), targets=(10,), current=1000, resistance=0,
               weather=0, random_value=0, patched=True, segments=1):
        u = self.machine(patched)
        for address, value in ((0x9D6C30, hp), (0x9D6C32, mp),
                               (0x9D6C7C, skill), (0x9DFA8E, -1),
                               (0x9D7046, segments), (0x9D709A, 100)):
            self.w16(u, address, value)
        self.w16(u, BP + 8, 0)
        u.mem_write(0x9D6C78, bytes([category]))
        u.mem_write(0x9D6C4E, bytes([flags]))
        u.mem_write(0x95294D, bytes([weather]))
        u.mem_write(0x9D6FA4, bytes(targets))
        u.mem_write(0x9D6FC4, bytes([len(targets)]))
        for target in targets:
            for address in (0x9D7084, 0x9D7086, 0x9D708A):
                self.w16(u, address + 1054 * target, current)
            for address in (0x9D70C0, 0x9D7290):
                self.w16(u, address + 1054 * target, resistance)
        for target in burning:
            u.mem_write(0x9E04A4 + 32 * target, b"\x01")
        popups = []

        def external_call(uc, address, size, data):
            if address not in (0x452AC0, 0x433F04):
                return
            sp = uc.reg_read(UC_X86_REG_ESP)
            if address == 0x433F04:
                args = struct.unpack("<5I", uc.mem_read(sp, 20))
                popups.append((args[2] & 0xFFFF, args[3] & 0xFFFF, args[4]))
            uc.reg_write(UC_X86_REG_EAX, random_value if address == 0x452AC0 else 0)
            uc.reg_write(UC_X86_REG_EIP, self.r32(uc, sp))
            uc.reg_write(UC_X86_REG_ESP, sp + 4)

        u.hook_add(UC_HOOK_CODE, external_call)
        self.execute(u, 0x440914, 0x44221B)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), BP - 0x1000)
        remaining = [tuple(struct.unpack("<h", u.mem_read(a + 1054 * t, 2))[0]
                           for a in (0x9D7084, 0x9D7086)) for t in targets]
        return remaining, popups

    def test_original_and_patched_four_skills(self):
        cases = (
            (63, 1020, 0, 1, 4, (400, 0), (400, 0)),
            (64, 0, 1040, 1, 4, (0, 400), (0, 800)),
            (41, 1040, 0, 2, 0, (800, 0), (800, 0)),
            (42, 1030, 1030, 2, 0, (600, 300), (600, 600)),
        )
        for skill, hp, mp, category, flags, original, fixed in cases:
            for patched in (False, True):
                with self.subTest(skill=skill, patched=patched):
                    remaining, _ = self.damage(hp=hp, mp=mp, skill=skill,
                        category=category, flags=flags, burning=(10,), patched=patched)
                    expected = fixed if patched else original
                    self.assertEqual(remaining, [tuple(1000 - n for n in expected)])

    def test_no_burning_is_unchanged(self):
        for skill, hp, mp, category, flags in (
            (63, 1020, 0, 1, 4), (64, 0, 1040, 1, 4),
            (41, 1040, 0, 2, 0), (42, 1030, 1030, 2, 0),
        ):
            args = dict(skill=skill, hp=hp, mp=mp, category=category, flags=flags)
            self.assertEqual(self.damage(**args), self.damage(**args, patched=False))

    def test_mp_fixed_percentage_and_resistance(self):
        for category, flags in ((1, 4), (2, 0)):
            for param, current, resistance, expected in (
                (101, 1000, 25, 152), (1040, 999, 25, 600),
                (1040, 1000, 100, 0), (1040, 0, 0, 0),
                (101, 100, 0, 100), (0, 1000, 0, 0),
            ):
                with self.subTest(category=category, param=param, current=current):
                    remaining, _ = self.damage(mp=param, category=category,
                        flags=flags, current=current, resistance=resistance, burning=(10,))
                    self.assertEqual(remaining, [(current, current - expected)])

    def test_miss_and_caster_burning_do_not_double(self):
        remaining, popups = self.damage(mp=1040, burning=(10,), random_value=99)
        self.assertEqual(remaining, [(1000, 1000)])
        self.assertEqual(popups, [(10, 65535, 0x1F)])
        self.assertEqual(self.damage(mp=1040, burning=(0,))[0], [(1000, 600)])

    def test_each_target_and_popup_segments(self):
        remaining, popups = self.damage(mp=1040, burning=(10,),
                                       targets=(10, 11), segments=3)
        self.assertEqual(remaining, [(1000, 200), (1000, 600)])
        for target, total in ((10, 800), (11, 400)):
            parts = [value for t, value, color in popups if t == target and color == 0x1C]
            self.assertEqual(len(parts), 3)
            self.assertEqual(sum(parts), total)

    def test_hp_weather_and_burning_are_not_applied_twice(self):
        for skill, weather in ((41, 1), (42, 2)):
            args = dict(hp=1020, skill=skill, category=2, flags=0,
                        weather=weather, burning=(10,))
            self.assertEqual(self.damage(**args)[0], [(200, 1000)])
            self.assertEqual(self.damage(**args), self.damage(**args, patched=False))

    def test_ai_percentage_fixed_and_camp_branches(self):
        for target in (10, 31):
            for allied in (0, 1):
                for camp in (3, 100):
                    for percent in (0, 40):
                        for burning in (False, True):
                            for patched in (False, True):
                                with self.subTest(target=target, allied=allied, camp=camp,
                                                  percent=percent, burning=burning, patched=patched):
                                    u = self.machine(patched)
                                    self.w32(u, BP - 0x0C, target)
                                    self.w32(u, BP - 0x18, percent)
                                    self.w32(u, BP - 0x1C, allied)
                                    self.w32(u, BP - 0x14, 100)
                                    self.w16(u, 0x9D6C5A, 75)
                                    self.w16(u, 0x9D7086 + 1054 * target, 1000)
                                    u.mem_write(0x9DF761 + target, bytes([camp]))
                                    u.mem_write(0x9E04A4 + 32 * target, bytes([burning]))
                                    self.execute(u, 0x43F967, 0x43F9D8)
                                    amount = (400 if percent else 75) * (2 if patched and burning else 1)
                                    sign = 1 if bool(allied) != (camp >= 10) else -1
                                    self.assertEqual(self.r32(u, BP - 0x14), 100 + sign * amount)

    def test_hooks_preserve_registers_flags_and_stack(self):
        registers = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                     UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                     UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS)
        for cave_base in (CAVE_BASE, CAVE_BASE + 0x10000):
            for burning in (0, 1):
                for allied in (0, 1):
                    for carry in (0, 1):
                        for ai in (False, True):
                            results = []
                            for patched in (False, True):
                                u = self.machine(patched, cave_base)
                                for n, reg in enumerate(registers[:6]):
                                    u.reg_write(reg, 0x12340000 + n)
                                u.reg_write(UC_X86_REG_EFLAGS, 0x246 | carry)
                                self.w32(u, BP - (0x0C if ai else 0x10), 10)
                                self.w32(u, BP - 0x1C, allied)
                                damage_slot = BP - (0x2C if ai else 0x24)
                                self.w32(u, damage_slot, 123)
                                u.mem_write(0x9E04A4 + 320, bytes([burning]))
                                start = 0x43F99F if ai else 0x4420F3
                                stop = (0x43F9A5 if allied else 0x43F9B4) if ai else 0x4420F8
                                self.execute(u, start, stop)
                                self.assertEqual(self.r32(u, damage_slot),
                                                 246 if patched and burning else 123)
                                results.append(tuple(u.reg_read(reg) for reg in registers))
                            self.assertEqual(*results)

    def test_runtime_and_file_builder_use_identical_hook_bytes(self):
        item = SitesPatchItem(self.defn.id, self.defn.name, self.defn.sites,
                              self.defn._cave_code_bytes, self.defn.cave_entries)
        raw = bytearray(self.raw)
        result = CaveBuildResult(False)
        ExeBuilder(str(self.exe))._apply_sites_patch(
            raw, self.pe, item, CAVE_BASE, {id(item): 0}, [], result)
        self.assertFalse(result.error)
        u = self.machine()
        for site in self.defn.sites:
            rva = int(site["rva"], 16)
            size = len(bytes.fromhex(site["expect"]))
            off = rva_to_offset(self.pe, rva)
            self.assertEqual(raw[off:off + size], u.mem_read(0x400000 + rva, size))
        changed = {i for i, (before, after) in enumerate(zip(self.raw, raw)) if before != after}
        allowed = {rva_to_offset(self.pe, int(s["rva"], 16)) + n
                   for s in self.defn.sites for n in range(len(bytes.fromhex(s["expect"])))}
        self.assertTrue(changed <= allowed)
        instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(self.defn._cave_code_bytes, CAVE_BASE))
        self.assertEqual(sum(i.size for i in instructions), 62)

    def test_no_existing_declared_patch_overlaps_hooks(self):
        own = [(rva_to_offset(self.pe, int(s["rva"], 16)), len(bytes.fromhex(s["expect"])))
               for s in self.defn.sites]
        for other in load_patch_directory(str(PATCHES)).patches:
            if other.id == self.defn.id:
                continue
            spans = [(rva_to_offset(self.pe, int(str(s["rva"]), 0)),
                      len(bytes.fromhex(s["expect"]))) for s in other.sites]
            entries = list(other.patterns or []) + list(other.hooks or [])
            if other.pattern:
                entries.append({"pattern": other.pattern, "replace": other.replace})
            if other.hook_pattern:
                entries.append({"pattern": other.hook_pattern, "hook_size": other.hook_size,
                                "hook_offset": other.hook_offset})
            for entry in entries:
                text = entry.get("pattern") or entry.get("hook_pattern")
                if not text:
                    continue
                pattern, wildcards = parse_pattern(text)
                for hit in pattern_scan(self.raw, pattern, wildcards):
                    offsets = [int(k) for k in (entry.get("replace") or {})]
                    if offsets:
                        spans.append((hit + min(offsets), max(offsets) - min(offsets) + 1))
                    else:
                        spans.append((hit + entry.get("hook_offset", 0),
                                      entry.get("hook_size") or len(pattern)))
            for start, size in spans:
                for hook, length in own:
                    self.assertFalse(start < hook + length and hook < start + size,
                                     f"{other.id} 与燃烧挂钩重叠")


if __name__ == "__main__":
    unittest.main()
