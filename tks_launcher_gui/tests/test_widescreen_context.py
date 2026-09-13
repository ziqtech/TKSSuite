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
        self.assertEqual(len(getattr(wide, "sites", [])), 767)
        refs = {site.get("ref") for site in getattr(wide, "sites", [])}
        self.assertIn("map_camera", refs)
        self.assertIn("settle_shift", refs)
        self.assertIn("gxp_pad_decide", refs)
        self.assertIn("gxp_upload", refs)
        self.assertIn("init_stride", refs)

    def test_generated_cave_matches_patch_json(self):
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("_widescreen_cave", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.build_cave_block().hex(" "), raw["cave_code"])


class SettleShiftLayoutTests(unittest.TestCase):
    """settle_shift 的行内变换: 640 内容 -> 居中 [108,748), 两侧补黑。"""

    W, PITCH = 856, 856 * 2

    def _shift_row(self, row: bytearray) -> None:
        for i in range(320):                     # 反向拷贝 320 dwords
            src, dst = 1276 - 4 * i, 1492 - 4 * i
            row[dst:dst + 4] = row[src:src + 4]
        row[0:216] = b"\x00" * 216
        row[1496:1712] = b"\x00" * 216

    def test_row_is_centered_with_black_bands(self):
        import struct
        row = bytearray(self.PITCH)
        for x in range(640):
            struct.pack_into("<H", row, x * 2, 1000 + x)
        self._shift_row(row)
        vals = struct.unpack_from("<%dH" % self.W, row, 0)
        self.assertEqual(vals[108], 1000)        # 内容左边界
        self.assertEqual(vals[747], 1639)        # 内容右边界
        self.assertTrue(all(v == 0 for v in vals[:108]))
        self.assertTrue(all(v == 0 for v in vals[748:]))

    def test_source_survives_until_copy_completes(self):
        """左带必须在拷贝之后清黑, 否则源 [0,108) 会被一起抹掉 (实测裁切根因)。"""
        import struct
        row = bytearray(self.PITCH)
        for x in range(640):
            struct.pack_into("<H", row, x * 2, 1000 + x)
        self._shift_row(row)
        vals = struct.unpack_from("<%dH" % self.W, row, 0)
        self.assertEqual(vals[108], 1000, "原 x=0 的内容必须落在 x=108")


class SettlementSpriteModeTests(unittest.TestCase):
    """结算页精灵不得再带 mode|0x80 的 +108 标记。

    该标记是"逐个元素居中"时代的产物 (处理器入口 test al,0x80 -> X+=108)。
    现在居中由 settle_shift 整帧完成, 若标记还在, 这些精灵会被位移两次
    (实测: 升级头像框落在 +216 而非 +108)。
    """

    HOOKS = ("spr_bt43B3AC", "spr_bt43B3E6", "spr_bt43B436", "spr_bt43B46D",
             "spr_bt43B5B5", "spr_bt43B6D4", "spr_bt43BDE9")

    def test_no_management_marker_left(self):
        import importlib.util
        import struct
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_modes", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        for name in self.HOOKS:
            off = module.CAVE_ENTRIES[name]
            self.assertEqual(blob[off], 0xBA, f"{name}: 期望 mov edx,imm32 跳板")
            mode = struct.unpack_from("<I", blob, off + 1)[0]
            self.assertFalse(mode & 0x80, f"{name}: mode=0x{mode:X} 仍带 0x80 位移标记")


if __name__ == "__main__":
    unittest.main()
