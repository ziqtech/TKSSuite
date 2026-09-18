import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_ESP,
)


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.exe_builder import ExeBuilder, SitesPatchItem  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402


PATCH_DIR = LAUNCHER / "patches" / "skill_ext_effect_resolver"
PATCH_JSON = PATCH_DIR / "patch.json"
GAME_DIR = Path(r"游戏目录（原版）")

CAVE = 0x00400000
MAP = 0x00660000
MAP_SIZE = 0x00020000
STACK = 0x7FF00000
STOP = 0x00100000


def _load_cave():
    raw = json.loads(PATCH_JSON.read_text(encoding="utf-8"))
    entries = {
        key: int(value, 16) if isinstance(value, str) else int(value)
        for key, value in raw["cave_entries"].items()
    }
    return bytes.fromhex(raw["cave_code"].replace(" ", "")), entries


def _run_entry(entry_offset, *, eax=0, ecx=0, edx=0):
    cave, _entries = _load_cave()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE, 0x1000)
    uc.mem_map(MAP, MAP_SIZE)
    uc.mem_map(STACK - 0x10000, 0x20000)
    uc.mem_write(CAVE, cave)
    esp = STACK - 0x100
    uc.mem_write(esp, struct.pack("<I", STOP))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EAX, eax)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    uc.reg_write(UC_X86_REG_EDX, edx)
    uc.emu_start(CAVE + entry_offset, STOP)
    return uc


class SkillEffectResolverTests(unittest.TestCase):
    def test_player_and_ai_entries_resolve_skill_350(self):
        _cave, entries = _load_cave()

        uc = _run_entry(entries["player_entry"], ecx=350, edx=0)
        player_base = uc.reg_read(UC_X86_REG_EAX)
        self.assertEqual(player_base, MAP - 700)
        self.assertEqual(
            struct.unpack_from("<h", uc.mem_read(MAP, 2), 0)[0], 590)

        uc = _run_entry(entries["ai_first_entry"], eax=350, ecx=0)
        ai_first_base = uc.reg_read(UC_X86_REG_EDX)
        self.assertEqual(ai_first_base + 350 * 2 + 0x222, MAP)

        uc = _run_entry(entries["ai_second_entry"], edx=350, eax=0)
        ai_second_base = uc.reg_read(UC_X86_REG_ECX)
        self.assertEqual(ai_second_base + 350 * 2 + 0x222, MAP)

    def test_legacy_entries_keep_original_addresses(self):
        _cave, entries = _load_cave()

        uc = _run_entry(entries["player_entry"], ecx=349, edx=3)
        self.assertEqual(
            uc.reg_read(UC_X86_REG_EAX), 3 * 2 + 0x9D729C)

        uc = _run_entry(entries["ai_first_entry"], eax=349, ecx=3)
        self.assertEqual(
            uc.reg_read(UC_X86_REG_EDX), 3 * 2 + 0x9D707A)

        uc = _run_entry(entries["ai_second_entry"], edx=349, eax=3)
        self.assertEqual(
            uc.reg_read(UC_X86_REG_ECX), 3 * 2 + 0x9D707A)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file(),
        "需要原版 TKS.exe 才能验证位点构建",
    )
    def test_effect_resolver_builds_all_six_sites(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = next(p for p in cfg.patches
                     if p.id == "skill_ext_effect_resolver")
        cave, entries = _load_cave()
        item = SitesPatchItem(
            patch_id=patch.id,
            name=patch.name,
            sites=patch.sites,
            cave_code=cave,
            cave_entries=entries,
            globals_ph_base=patch.globals_ph_base,
            globals_rebase_span=patch.globals_rebase_span,
            globals_alloc_size=patch.globals_alloc_size,
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_skill_resolver.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out), sites_patches=[item])
            self.assertTrue(result.success, "\n".join(result.log))
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
