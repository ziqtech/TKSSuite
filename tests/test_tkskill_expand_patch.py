import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pefile


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.exe_builder import (  # noqa: E402
    ExeBuilder,
)
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from core.scanner import value_scan, value_scan_excluding_rel32  # noqa: E402
from editor_utils.lzss import (  # noqa: E402
    lzss_compress_dat,
    lzss_decompress_dat,
)
from ui.generate_exe_dialog import GenerateExeDialog  # noqa: E402


GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))


class TkskillExpandPatchTests(unittest.TestCase):
    def test_rel32_false_positive_is_excluded(self):
        data = (
            b"\x0F\x84\x80\x00\x00\x00"
            + (32900).to_bytes(4, "little")
        )
        self.assertEqual(value_scan(data, 32900), [1, 6])
        self.assertEqual(value_scan_excluding_rel32(data, 32900), [6])

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKSkill.dat").is_file(),
        "需要原版 TKS.exe / TKSkill.dat 才能验证技能定义扩容",
    )
    def test_tkskill_expand_builds_to_standalone_section(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = next(p for p in cfg.patches if p.id == "tkskill_expand")
        self.assertEqual(patch.type, "patch_data_expand")
        self.assertEqual(patch.old_base, 0x7861CA)
        self.assertEqual(patch.old_size, 32900)
        self.assertEqual(patch.pattern, "68 84 80 00 00")
        self.assertEqual(patch.value_offset, 1)
        self.assertEqual(patch.expect_count, 1)
        self.assertEqual(patch._extra.get("buffer_cap"), 65536)
        self.assertEqual(patch._extra.get("redirect_base_span"), 94)

        expanded = lzss_decompress_dat(
            (GAME_DIR / "TKSkill.dat").read_bytes())
        expanded += b"\0" * 94
        compressed = lzss_compress_dat(expanded)

        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            skill_path = temp_dir / "TKSkill.dat"
            skill_path.write_bytes(compressed)
            out_exe = temp_dir / "TKS_skill_expand.exe"

            dialog = SimpleNamespace(
                _out_edit=SimpleNamespace(text=lambda: str(out_exe)),
                _src_edit=SimpleNamespace(text=lambda: str(GAME_DIR / "TKS.exe")),
                _log=lambda _msg: None,
            )
            item = GenerateExeDialog._build_data_section(dialog, patch)
            self.assertIsNotNone(item)
            self.assertGreaterEqual(item.logical_size, 65536)
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out_exe),
                data_section_patches=[item],
            )
            self.assertTrue(result.success, "\n".join(result.log))

            pe = pefile.PE(data=out_exe.read_bytes(), fast_load=True)
            text = next(
                s for s in pe.sections
                if s.Name.rstrip(b"\0") == b".text").get_data()
            section = next(
                s for s in pe.sections
                if s.Name.rstrip(b"\0") == b".tkskill")

            self.assertGreaterEqual(section.Misc_VirtualSize, 65536)
            self.assertEqual(
                text.count((32900).to_bytes(4, "little")), 9)
            self.assertEqual(
                int.from_bytes(text[0x1642A:0x1642E], "little"), 65536)
            self.assertEqual(text.count((0x7861CA).to_bytes(4, "little")), 0)
            for delta in range(1, 94):
                self.assertEqual(
                    text.count((0x7861CA + delta).to_bytes(4, "little")),
                    0,
                    f"old TKSkill field anchor +0x{delta:X} was not relocated",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
