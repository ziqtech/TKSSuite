import unittest
import importlib.util
import sys
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
_ACT_DIR = _ROOT / 'act_editor'
if str(_ACT_DIR) not in sys.path:
    sys.path.insert(0, str(_ACT_DIR))

spec = importlib.util.spec_from_file_location(
    'act_composite', _ACT_DIR / 'act_composite.py')
act_composite = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = act_composite
spec.loader.exec_module(act_composite)

from act_composite import (
    _composite_additive,
    _composite_luma_alpha,
    _composite_subtract,
)


class ActCompositeTests(unittest.TestCase):
    def test_additive_blend_is_applied(self):
        composite = Image.new('RGB', (2, 1), (10, 10, 10))
        source = Image.new('RGBA', (2, 1), (30, 40, 50, 255))

        _composite_additive(composite, source, 0, 0, 0)

        self.assertEqual(composite.getpixel((0, 0)), (40, 50, 60))

    def test_subtract_blend_is_applied(self):
        composite = Image.new('RGB', (2, 1), (30, 30, 30))
        source = Image.new('RGBA', (2, 1), (10, 20, 25, 255))

        _composite_subtract(composite, source, 0, 0)

        self.assertEqual(composite.getpixel((0, 0)), (20, 10, 5))

    def test_luma_alpha_blend_is_applied(self):
        composite = Image.new('RGB', (2, 1), (20, 20, 20))
        source = Image.new('RGBA', (2, 1), (255, 0, 0, 255))

        _composite_luma_alpha(composite, source, 0, 0)

        self.assertNotEqual(composite.getpixel((0, 0)), (20, 20, 20))


if __name__ == '__main__':
    unittest.main()
