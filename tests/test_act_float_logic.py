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
        host = types.SimpleNamespace(_float_specs=specs)

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


if __name__ == '__main__':
    unittest.main()
