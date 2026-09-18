import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.config_loader import (  # noqa: E402
    PatchSettings,
    resolve_effective_patches,
    validate_skill_table,
)
from core.patch_engine import _build_cave_layout, _resolve_sites_writes  # noqa: E402
from core.memory import rebase_globals  # noqa: E402
from core.launcher_pipeline import PatcherPipeline, PipelineConfig  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from unittest import mock  # noqa: E402


class PatchGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = load_patch_directory(
            str(LAUNCHER / "patches"),
            log_func=lambda *_args: None,
        ).patches

    def test_unified_extension_pulls_dependencies_and_supersedes_conflicts(self):
        effective = resolve_effective_patches(
            self.patches,
            selected={"skill_ext_learn_state"},
        )

        self.assertIn("skill_ext_learn_state", effective.ids)
        self.assertIn("tkskill_expand", effective.ids)
        self.assertIn("warpc_base_refs", effective.ids)
        self.assertIn("warpc_size_refs", effective.ids)
        self.assertNotIn("skill_scan_bound", effective.ids)
        self.assertNotIn("skill_menu_cap", effective.ids)
        self.assertNotIn("tkskill_size", effective.ids)
        self.assertNotIn("skill_ext_effect_resolver", effective.ids)

    def test_skill_table_validation_requires_unified_extension(self):
        without_unified = [
            patch for patch in self.patches
            if patch.id != "skill_ext_learn_state"
        ]
        with self.assertRaises(ValueError):
            validate_skill_table(351 * 94, without_unified)

        unified = [
            patch for patch in self.patches
            if patch.id in {"skill_ext_learn_state", "tkskill_expand"}
        ]
        self.assertTrue(validate_skill_table(351 * 94, unified))

    def test_code_sites_run_before_data_expansions(self):
        effective = resolve_effective_patches(
            self.patches,
            selected={"skill_ext_learn_state"},
        )
        order = [patch.id for patch in effective.patches]
        self.assertLess(
            order.index("skill_ext_learn_state"),
            order.index("warpc_base_refs"),
        )
        self.assertLess(
            order.index("skill_ext_learn_state"),
            order.index("tkskill_expand"),
        )
        self.assertEqual(
            effective.patches[-1].type,
            "patch_data_expand",
        )

    def test_skill_extension_and_widescreen_fit_effective_cave_budget(self):
        effective = resolve_effective_patches(
            self.patches,
            selected={
                "skill_ext_learn_state",
                "widescreen_16_9",
                "summon_extend",
            },
        )
        layout = _build_cave_layout(
            SimpleNamespace(patches=self.patches),
            0x700000,
            PatchSettings(),
            lambda *_args: None,
            active_patches=effective.patches,
        )
        owners = {slot.owner_id for slot in layout.slots}
        self.assertIn("skill_ext_learn_state", owners)
        self.assertIn("widescreen_16_9", owners)
        self.assertLessEqual(layout.used_bytes(), layout.budget)

    def test_explicit_globals_relocations_do_not_rewrite_push_opcodes(self):
        code = bytes.fromhex("6a 01 68 00 b0 68 00")
        for delta in (-0x400000, 0x1000, 0x500000):
            with self.subTest(delta=delta):
                rebased = rebase_globals(
                    code, [(0x660000, 0x60000)], delta, offsets=[3])
                self.assertEqual(rebased[:3], code[:3])
                self.assertEqual(int.from_bytes(rebased[3:], "little"),
                                 0x68B000 + delta)
        self.assertEqual(
            rebase_globals(code, [(0x660000, 0x60000)], 1, offsets=[]), code)
        for offset in (-1, 4, 2):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                rebase_globals(code, [(0x660000, 0x60000)], 1, offsets=[offset])

    def test_resolved_call_displacements_are_not_globals_addresses(self):
        patch = next(p for p in self.patches if p.id == "skill_ext_learn_state")
        cave_base = 0x418AE1 + 5 + 0x660000
        original = _resolve_sites_writes(patch, cave_base)
        rebased = _resolve_sites_writes(
            patch, cave_base, g_rebase=[(0x660000, 0x60000)], g_delta=0x500000)
        self.assertEqual(int.from_bytes(original[0][2][1:5], "little"), 0x660000)
        self.assertEqual(rebased, original)

    def test_extended_skill_table_auto_enables_unified_extension(self):
        pipeline = PatcherPipeline(
            PipelineConfig(exe_path="TKS.exe", exe_dir="."),
            log=lambda *_args: None,
        )
        pipeline.config = SimpleNamespace(patches=self.patches)
        pipeline.cfg.selected_patches = None

        with mock.patch(
                "core.launcher_pipeline.get_decompressed_size",
                return_value=351 * 94):
            pipeline._ensure_skill_extension_for_extended_table()

        self.assertIn(
            "skill_ext_learn_state", pipeline.cfg.selected_patches)


if __name__ == "__main__":
    unittest.main(verbosity=2)
