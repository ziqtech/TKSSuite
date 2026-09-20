import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parent.parent
_ACT_DIR = _ROOT / 'act_editor'
if str(_ACT_DIR) not in sys.path:
    sys.path.insert(0, str(_ACT_DIR))

_spec = importlib.util.spec_from_file_location(
    'act_editor_float_logic', _ACT_DIR / 'act_editor.py')
_act_editor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _act_editor
_spec.loader.exec_module(_act_editor)


class ActFloatLogicTests(unittest.TestCase):
    def _entry(self, triggers):
        param16 = [0] * 24
        param16[2] = 30
        for i, tick in enumerate(triggers):
            param16[4 + i] = tick
        return {'index': 1, 'param16': param16}

    def _host(self, specs, float_type='hp_damage'):
        ns = types.SimpleNamespace(
            _float_specs=specs,
            _float_type=float_type,
        )
        ns._current_float_type = (
            lambda ft=None: _act_editor.ActEditorV2._current_float_type(ns, ft)
        )
        return ns

    def test_trigger_fields_and_damage_split(self):
        entry = self._entry([4, 12])
        specs = _act_editor.ActEditorV2._make_float_specs(None, entry)

        self.assertEqual(
            [(s['start_tick'], s['value'], s['color']) for s in specs],
            [(4, 500, 18), (12, 499, 23)])
        self.assertEqual(_act_editor.ActEditorV2._float_end_tick(entry), 30)

    def test_active_float_obeys_trigger_tick(self):
        entry = self._entry([4, 12])
        specs = _act_editor.ActEditorV2._make_float_specs(None, entry)
        host = self._host(specs)

        self.assertEqual(
            _act_editor.ActEditorV2._preview_active_floats(
                host, 3, 100, 200), [])
        self.assertEqual(
            len(_act_editor.ActEditorV2._preview_active_floats(
                host, 4, 100, 200)), 1)
        self.assertEqual(
            len(_act_editor.ActEditorV2._preview_active_floats(
                host, 12, 100, 200)), 2)

    def test_no_configured_trigger_means_no_float(self):
        entry = self._entry([])
        self.assertEqual(
            _act_editor.ActEditorV2._make_float_specs(None, entry), [])

    def test_mp_damage_uses_palette_28(self):
        entry = self._entry([4, 12])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'mp_damage')
        self.assertEqual([s['color'] for s in specs], [28, 28])
        self.assertEqual([s['value'] for s in specs], [500, 499])

        host = self._host(specs, 'mp_damage')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 4, 100, 200)
        self.assertEqual(actives[0]['color'], (128, 64, 255))
        self.assertEqual(actives[0]['text'], '500')

    def test_hp_heal_uses_palette_20(self):
        entry = self._entry([6])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'hp_heal')
        self.assertEqual(specs[0]['color'], 20)
        self.assertEqual(specs[0]['value'], 999)

        host = self._host(specs, 'hp_heal')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 6, 100, 200)
        self.assertEqual(actives[0]['color'], (0, 255, 0))

    def test_mp_heal_uses_palette_21(self):
        entry = self._entry([6])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'mp_heal')
        self.assertEqual(specs[0]['color'], 21)

        host = self._host(specs, 'mp_heal')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 6, 100, 200)
        self.assertEqual(actives[0]['color'], (0, 255, 255))

    def test_miss_type_shows_text_with_white(self):
        entry = self._entry([4, 12])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'miss')
        self.assertEqual([s['text'] for s in specs], ['Miss', 'Miss'])
        self.assertEqual([s['color'] for s in specs], [31, 31])
        self.assertIsNone(specs[0]['value'])

        host = self._host(specs, 'miss')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 4, 100, 200)
        self.assertEqual(actives[0]['text'], 'Miss')
        self.assertEqual(actives[0]['color'], (255, 255, 255))

    def test_status_text_uses_palette_26(self):
        entry = self._entry([8])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'status')
        self.assertEqual(specs[0]['text'], '定身')
        self.assertEqual(specs[0]['color'], 26)

        host = self._host(specs, 'status')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 8, 100, 200)
        self.assertEqual(actives[0]['color'], (128, 255, 64))

    def test_spell_reflect_text_uses_palette_29(self):
        entry = self._entry([5])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'spell_reflect')
        self.assertEqual(specs[0]['text'], '法術反彈')
        self.assertEqual(specs[0]['color'], 29)

        host = self._host(specs, 'spell_reflect')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 5, 100, 200)
        self.assertEqual(actives[0]['color'], (64, 128, 255))

    def test_float_type_map_defaults_to_damage(self):
        self.assertEqual(_act_editor.DEFAULT_FLOAT_TYPE, 'hp_damage')
        self.assertEqual(_act_editor.DEFAULT_FLOAT_TOTAL, 999)
        self.assertIn('hp_damage', _act_editor.FLOAT_TYPE_MAP)
        self.assertEqual(
            _act_editor.FLOAT_TYPE_MAP['hp_damage']['colors'], (18, 23))

    def test_preview_total_override_splits_custom_value(self):
        entry = self._entry([4, 12])
        specs = _act_editor.ActEditorV2._make_float_specs(
            None, entry, 'hp_damage', total=200)
        self.assertEqual([s['value'] for s in specs], [100, 100])
        self.assertEqual([s['color'] for s in specs], [18, 23])

        host = self._host(specs, 'hp_damage')
        actives = _act_editor.ActEditorV2._preview_active_floats(
            host, 4, 100, 200)
        self.assertEqual(actives[0]['text'], '100')


if __name__ == '__main__':
    unittest.main()
