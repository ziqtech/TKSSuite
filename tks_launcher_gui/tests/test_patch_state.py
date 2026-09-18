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
        # 2026-09-10 起 fixed_layout 块 + 16:9 宽屏精灵解码重写块 (约 3.9KB)
        # 需要 8.8KB, 预算取 16384 (config_loader 注释为准; 旧断言 4096 已过时)
        self.assertEqual(settings.cave_total_size, 32768)

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

    def test_unknown_value_returns_none(self):
        messages = []

        value = resolve_patch_value(
            "{missing_value}", PatchSettings(), PatchRuntimeState(),
            log_func=messages.append,
        )

        self.assertIsNone(value)
        self.assertTrue(any("未定义参数" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
