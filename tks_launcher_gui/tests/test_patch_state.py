import unittest

from core.config_loader import (
    PatchRuntimeState,
    PatchSettings,
    resolve_patch_value,
)


class PatchStateTests(unittest.TestCase):
    def test_settings_expose_fixed_layout_values(self):
        settings = PatchSettings()

        self.assertEqual(settings.warpc_rec_size, 1054)
        self.assertEqual(settings.tkkon_base, 0x9D0698)
        self.assertEqual(settings.cave_total_size, 2048)

    def test_runtime_value_overrides_settings_value(self):
        settings = PatchSettings()
        runtime = PatchRuntimeState(warpc_new_size=321000)

        self.assertEqual(
            resolve_patch_value("{warpc_new_size}", settings, runtime),
            321000,
        )
        self.assertEqual(
            resolve_patch_value("{warpc_rec_size}", settings, runtime),
            1054,
        )

    def test_deferred_archive_portrait_reserves_its_baseline_cave_slot(self):
        from core.patch_engine import _build_cave_layout
        from core.config_loader import PatchConfig, PatchDef

        config = PatchConfig(patches=[
            PatchDef(id="archive_portrait", type="cave_hook"),
            PatchDef(id="another_cave", type="cave_hook"),
        ])

        layout = _build_cave_layout(config, 0x10000000, PatchSettings(), lambda _: None)
        archive_slot = next(slot for slot in layout.slots
                            if slot.owner_id == "archive_portrait")

        self.assertEqual(archive_slot.offset, 192)
        self.assertEqual(archive_slot.size, 50)
        self.assertTrue(all(
            slot.owner_id == "archive_portrait"
            or slot.end() <= archive_slot.offset
            or slot.offset >= archive_slot.end()
            for slot in layout.slots
        ))


if __name__ == "__main__":
    unittest.main()
