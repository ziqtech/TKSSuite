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
        self.assertEqual(len(getattr(wide, "sites", [])), 774)
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


class CenteredBlitClampTests(unittest.TestCase):
    """居中类背景 Blt 必须把源宽钳到 856-108=748。

    GXP 表面被 pad 到 856 后, 若仍按 856 取矩形, dst.right = 856+108 = 964
    超出后备表面 → DDERR_INVALIDRECT, Blt 每帧失败: 背景停在错误的水平位置,
    而文字/精灵仍是 +108 → 表现为"字体位置不正确" (实测小游戏页)。
    """

    def test_center_helpers_clamp_to_748(self):
        import importlib.util
        import struct
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_clamp", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        cmp_748 = b"\x3d" + struct.pack("<I", 748)
        cmp_856 = b"\x3d" + struct.pack("<I", 856)
        starts = sorted(set(module.CAVE_ENTRIES.values()))
        for name in ("gxp_blt_fix", "mg_blt_left"):
            off = module.CAVE_ENTRIES[name]
            nxt = next(v for v in starts if v > off)
            window = blob[off:nxt]          # 只看该块自身, 不越界到相邻块
            self.assertIn(cmp_748, window, f"{name}: 缺少 748 宽度钳制")
            self.assertNotIn(cmp_856, window, f"{name}: 仍按 856 钳制")


class MiniGameTextTests(unittest.TestCase):
    """小游戏文字: 画布宽必须跟随表面(856), 换行边界必须跟随文本位移(+108)。

    - `sub_44AFF4(font,0,W,480)` 写的是字体对象 +0x28 = 文字画布宽, 同时是字形
      写入的行距; 目标表面 856 宽, 若改回 640 每行步进错位 → 文字碎成像素点
      (实测)。故这 8 个位点必须保持 856。
    - 帮助文本画在 x=346、换行边界是另一个字段 +0x34 = 590 (见 42A32C)。
      文本 X 被 mg_text_shift 平移 +108 后, 边界若不一起平移, 每行可用宽度会从
      244 变成 136, 换行与位置就和原版对不上。故 7 处 590 必须变 698。
    """

    CANVAS = (0x28EEB, 0x29D53, 0x2ADDB, 0x2D4E3, 0x2DEC7, 0x2E553, 0x2EE7F, 0x302A4)
    WRAP = (0x293F8, 0x2A337, 0x2B0B8, 0x2D984, 0x2E108, 0x2E7F8, 0x2F0F4)

    def _sites(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        out = {}
        for site in raw["sites"]:
            rva = int(site["rva"], 0) if isinstance(site.get("rva"), str) else int(site["rva"])
            out[rva] = site
        return out

    def test_font_canvas_width_follows_surface(self):
        sites = self._sites()
        for rva in self.CANVAS:
            self.assertIn(rva, sites, f"{rva:#X}: 字体画布宽位点缺失 (会碎字)")
            self.assertEqual(sites[rva].get("replace"), "68 58 03 00 00",
                             f"{rva:#X}: 字体画布宽必须为 856")

    def test_wrap_boundary_moves_with_text(self):
        sites = self._sites()
        for rva in self.WRAP:
            self.assertIn(rva, sites, f"{rva:#X}: 换行边界位点缺失")
            self.assertEqual(sites[rva].get("expect"), "4E 02 00 00", f"{rva:#X}: 期望原值 590")
            self.assertEqual(sites[rva].get("replace"), "BA 02 00 00", f"{rva:#X}: 换行边界应为 698")


class TextShiftWrapperTests(unittest.TestCase):
    """位移 wrapper 必须是 ADD, 不能是 MOV。

    `C7 44 24 0C imm32` 是 mov dword [esp+0xC],108 —— 会把文本 X 直接覆盖成
    108, 导致所有被挂的文本挤到同一个左端位置 (实测小游戏页全部文字落在 x≈108)。
    正确编码是 `81 44 24 0C imm32` = add dword [esp+0xC],108。
    """

    WRAPPERS = ("mg_text_shift", "text_shift_ralign", "text_shift_wrap")

    def test_wrappers_add_offset(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_shift", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        for name in self.WRAPPERS:
            off = module.CAVE_ENTRIES[name]
            self.assertEqual(blob[off], 0x81,
                             f"{name}: 应为首字节 0x81 (add r/m32,imm32), 实际 0x{blob[off]:02X}")
            self.assertNotEqual(blob[off], 0xC7, f"{name}: 仍是 mov, 会覆盖 X")


if __name__ == "__main__":
    unittest.main()
