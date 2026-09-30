import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESP


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.exe_builder import (  # noqa: E402
    BytesPatchEntry,
    BytesPatchItem,
    ExeBuilder,
    Imm32PatchEntry,
    Imm32PatchItem,
    SitesPatchItem,
)
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.lzss import (  # noqa: E402
    lzss_compress_dat,
    lzss_decompress_dat,
)
from ui.generate_exe_dialog import GenerateExeDialog  # noqa: E402


GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", "."))


class SkillExtBundleTests(unittest.TestCase):
    def _assert_skill_menu_pages(self, uc, warpc_base, skill_base, globals_base):
        ui = 0x02000000
        sp = 0x7FF08000
        stop = 0x00100000
        uc.mem_map(ui, 0x130000)
        uc.mem_write(globals_base + 0x58040, struct.pack("<H", 1))
        uc.mem_write(globals_base + 0x58044, struct.pack("<I", 351))
        for actor, extended in ((0, False), (200, True), (499, True)):
            for legacy_count in (0, 3, 12):
                for mode, category, state in ((0, 0, 10), (4, 0, 20),
                                               (6, 1, 20), (8, 2, 30), (9, 3, 30)):
                    with self.subTest(actor=actor, legacy_count=legacy_count,
                                      mode=mode):
                        expected = list(range(legacy_count))
                        if extended:
                            expected.append(350)
                        definitions = bytearray(65536)
                        for skill in range(352):
                            struct.pack_into("<h", definitions, skill * 94 + 4,
                                             category)
                        uc.mem_write(skill_base, bytes(definitions))
                        learn = bytes([state]) * legacy_count + bytes(344 - legacy_count)
                        uc.mem_write(warpc_base + actor * 1054 + 176,
                                     learn + bytes([state]) * 6)
                        uc.mem_write(globals_base + actor * 347,
                                     bytes([state if extended else 0, state]) + bytes(345))
                        uc.mem_write(ui + 0x12C3A4, struct.pack("<h", mode))
                        uc.mem_write(ui + 0x12C3EC, b"\0\0")
                        pages = max(1, (len(expected) + 9) // 10)
                        for page in list(range(pages)) + [0]:
                            uc.mem_write(ui + 0x12C3E8, struct.pack("<h", page))
                            uc.mem_write(sp, struct.pack("<III", stop, ui, actor))
                            uc.reg_write(UC_X86_REG_ESP, sp)
                            uc.emu_start(0x4189BC, stop, count=100_000)
                            self.assertEqual(uc.reg_read(UC_X86_REG_EIP), stop)
                            self.assertEqual(uc.reg_read(UC_X86_REG_ESP), sp + 4)
                            count = struct.unpack(
                                "<h", uc.mem_read(ui + 0x12C3B0, 2))[0] + 1
                            wanted = expected[page * 10:page * 10 + 10]
                            self.assertEqual(count, len(wanted))
                            actual = list(struct.unpack(
                                f"<{count}h", uc.mem_read(ui + 0x12C3B2, count * 2)))
                            self.assertEqual(actual, wanted)
                            self.assertEqual(
                                uc.mem_read(ui + 0x12C3AF, 1),
                                bytes([int((page + 1) * 10 < len(expected))]))

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKSkill.dat").is_file(),
        "需要原版 TKS.exe / TKSkill.dat 才能构建统一技能扩展",
    )
    def test_unified_bundle_builds_with_expanded_skill_table(self):
        cfg = load_patch_directory(
            str(LAUNCHER / "patches"), log_func=lambda *_a: None)
        learn = next(
            p for p in cfg.patches if p.id == "skill_ext_learn_state")
        expand = next(p for p in cfg.patches if p.id == "tkskill_expand")
        warpc_base = next(
            p for p in cfg.patches if p.id == "warpc_base_refs")
        warpc_size = next(
            p for p in cfg.patches if p.id == "warpc_size_refs")

        raw = json.loads(
            (LAUNCHER / "patches" / "skill_ext_learn_state" /
             "patch.json").read_text(encoding="utf-8"))
        cave = bytes.fromhex(raw["cave_code"].replace(" ", ""))
        entries = {
            key: int(value, 16) if isinstance(value, str) else int(value)
            for key, value in raw["cave_entries"].items()
        }

        expanded = lzss_decompress_dat(
            (GAME_DIR / "TKSkill.dat").read_bytes()) + b"\0" * 94
        expanded_warpc = b"\0" * (1054 * 500)

        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            (temp_dir / "TKSkill.dat").write_bytes(
                lzss_compress_dat(expanded))
            (temp_dir / "WarPC.dat").write_bytes(
                lzss_compress_dat(expanded_warpc))
            out_exe = temp_dir / "TKS_skill_bundle.exe"

            dialog = SimpleNamespace(
                _resolve_data_file=lambda name: str(temp_dir / name),
                _log=lambda _message: None,
            )
            data_section = GenerateExeDialog._build_data_section(
                dialog, expand)
            warpc_section = GenerateExeDialog._build_data_section(
                dialog, warpc_base)
            warpc_imm = Imm32PatchItem(
                patch_id=warpc_size.id,
                name=warpc_size.name,
                new_value=len(expanded_warpc),
                entries=[Imm32PatchEntry(
                    pattern=warpc_size.expect_value.to_bytes(4, "little").hex(" "),
                    value_offset=0,
                    expect_count=0,
                )],
            )
            state_patch = SitesPatchItem(
                patch_id=learn.id,
                name=learn.name,
                sites=learn.sites,
                cave_code=cave,
                cave_entries=entries,
                globals_ph_base=learn.globals_ph_base,
                globals_rebase_span=learn.globals_rebase_span,
                globals_alloc_size=learn.globals_alloc_size,
                globals_relocations=learn.globals_relocations,
            )

            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [],
                str(out_exe),
                imm32_patches=[warpc_imm],
                data_section_patches=[data_section, warpc_section],
                sites_patches=[state_patch],
            )
            self.assertTrue(result.success, "\n".join(result.log))

            pe = pefile.PE(data=out_exe.read_bytes(), fast_load=True)
            section_names = {
                section.Name.rstrip(b"\0").decode("ascii", "ignore")
                for section in pe.sections
            }
            self.assertIn(".tkskill", section_names)
            self.assertIn(".warpc", section_names)
            self.assertIn(".test", section_names)
            test_section = next(
                section for section in pe.sections
                if section.Name.rstrip(b"\0") == b".test")
            test_data = test_section.get_data()
            self.assertNotIn(
                (0x757F08).to_bytes(4, "little"), test_data)

            image = pe.get_memory_mapped_image()
            stack = 0x7FF00000
            sp = stack + 0x8000
            stop = 0x00100000
            globals_base = state_patch._globals_abs
            battle_map = globals_base + 0x58000
            cases = (
                (0x4128A3, stop,
                 b"\0" * 24 + struct.pack("<III", 0x11111111, 0x22222222, stop),
                 sp + 36),
                (0x411141, 0x411146, struct.pack("<I", 0x12345678), sp),
            )
            for entry, continuation, frame, expected_sp in cases:
                with self.subTest(entry=hex(entry)):
                    uc = Uc(UC_ARCH_X86, UC_MODE_32)
                    uc.mem_map(pe.OPTIONAL_HEADER.ImageBase,
                               (len(image) + 0xFFF) & ~0xFFF)
                    uc.mem_write(pe.OPTIONAL_HEADER.ImageBase, image)
                    uc.mem_map(stack, 0x10000)
                    for address in (0x4B1FC8, 0x4B2208, 0x4B1C3C):
                        uc.mem_write(address, bytes.fromhex("31 c0 c3"))
                    uc.mem_write(sp, frame)
                    uc.reg_write(UC_X86_REG_ESP, sp)
                    uc.emu_start(entry, continuation, count=20_000_000)
                    self.assertEqual(uc.reg_read(UC_X86_REG_EIP), continuation)
                    self.assertEqual(uc.reg_read(UC_X86_REG_ESP), expected_sp)
                    self.assertEqual(uc.mem_read(globals_base, 1), b"\x0a")
                    self.assertEqual(uc.mem_read(globals_base + 1, 499),
                                     b"\x01" * 499)
                    metadata = bytes(uc.mem_read(battle_map + 0x40, 8))
                    self.assertEqual(struct.unpack_from("<H", metadata)[0], 347)
                    self.assertEqual(struct.unpack_from("<I", metadata, 4)[0], 697)

                    # 保留生成的真实入口，只将含资源加载的函数体换成等价尾声。
                    uc.mem_write(0x4307D2, bytes.fromhex("8b e5 5d c3"))
                    uc.mem_write(sp, struct.pack("<I", stop))
                    uc.mem_write(battle_map, b"\xab" * 64)
                    uc.reg_write(UC_X86_REG_ESP, sp)
                    uc.emu_start(0x4307CC, stop, count=20_000)
                    self.assertEqual(uc.reg_read(UC_X86_REG_EIP), stop)
                    self.assertEqual(uc.reg_read(UC_X86_REG_ESP), sp + 4)
                    self.assertEqual(uc.mem_read(battle_map, 64), b"\0" * 64)
                    self.assertEqual(uc.mem_read(battle_map + 0x40, 8), metadata)

            sections = {s.Name.rstrip(b"\0"): pe.OPTIONAL_HEADER.ImageBase
                        + s.VirtualAddress for s in pe.sections}
            self._assert_skill_menu_pages(
                uc, sections[b".warpc"], sections[b".tkskill"], globals_base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
