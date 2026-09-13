import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tks_launcher_gui"))

from core.tkspatch_loader import load_patch_directory


class WidescreenContextTests(unittest.TestCase):
    def test_only_real_widescreen_patch_is_loaded(self):
        cfg = load_patch_directory(ROOT / "tks_launcher_gui" / "patches")
        patches = {p.id: p for p in cfg.patches}
        self.assertIn("widescreen_16_9", patches)
        wide = patches["widescreen_16_9"]
        self.assertEqual(wide.type, "patch_sites")
        self.assertEqual(len(getattr(wide, "sites", [])), 764)
        refs = {site.get("ref") for site in getattr(wide, "sites", [])}
        self.assertIn("map_camera", refs)
        self.assertIn("init_stride", refs)

    def test_generated_cave_matches_patch_json(self):
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("_widescreen_cave", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.build_cave_block().hex(" "), raw["cave_code"])


if __name__ == "__main__":
    unittest.main()
