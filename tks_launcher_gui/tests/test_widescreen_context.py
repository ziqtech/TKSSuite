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
        self.assertEqual(len(getattr(wide, "sites", [])), 829)
        refs = {site.get("ref") for site in getattr(wide, "sites", [])}
        self.assertIn("map_camera", refs)
        self.assertIn("settle_shift", refs)
        self.assertIn("gxp_pad_decide", refs)
        self.assertIn("gxp_upload", refs)
        self.assertIn("init_stride", refs)
        self.assertNotIn("wrap_page_42539C", refs)

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


class MiniGameMouseTests(unittest.TestCase):
    """小游戏命中判定必须读 MG_MOUSE(raw-108), 不能读 raw [0x824278]。

    按钮是画在"原坐标+108"处的, 命中矩形仍是 640 坐标。若命中判定读到的是
    窗口原始坐标, 可点区域就会比看到的按钮整体偏移 108px (实测骰子小游戏)。
    """

    # 7 个小游戏函数体 (428F40/429DA8/42AED4/42B330/42D538/42DF1C/42E5A8/42EED4)
    # 里 [0x824278] 的全部读点 —— 由扫描原版 exe 的 disp32 得到, 一个都不能漏。
    MINI_GAME_READS = (0x28F7E, 0x2924B, 0x29DC8, 0x2A064, 0x2AEF1, 0x2B378,
                       0x2D566, 0x2D610, 0x2D653, 0x2D8AC, 0x2DF2B, 0x2E043,
                       0x2E5C8, 0x2E650, 0x2E72D, 0x2EEE3, 0x2F020)

    def test_every_mini_game_read_redirected(self):
        """小游戏命中判定必须读 MG_MOUSE(raw-108), 不能读 raw [0x824278]。

        按钮/瓷砖画在"原坐标+108"处、命中矩形仍是 640 坐标; 读到窗口原始坐标
        时可点区域就整体偏移 108px (骰子 429DA8 实测, 旋转拼图 42D538 同病)。
        """
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        got = {}
        for site in raw["sites"]:
            rva = int(site["rva"], 0) if isinstance(site.get("rva"), str) else int(site["rva"])
            got[rva] = (site.get("replace") or "").upper()
        want = ("8B 0D 50 69 70 00", "8B 15 50 69 70 00", "A1 50 69 70 00")
        for rva in self.MINI_GAME_READS:
            self.assertIn(rva, got, f"{rva:#X}: 小游戏鼠标读点未重定向, 可点区域偏移 108px")
            # 5B `A1` 形态只需改 disp32, 6B `8B modrm` 形态整体改
            self.assertIn(got[rva], want,
                          f"{rva:#X}: 仍读原始鼠标坐标 (期望 MG_MOUSE)")


class MiniGameSelectBoxTests(unittest.TestCase):
    """小游戏"点选高亮框"(GDI 白框) 必须与 +108 的瓷砖同源位移。

    白框画在显示表面 dword_A2B98C 的 DC 上, 坐标取自 640 布局数组 (原坐标);
    瓷砖却按 mode|0x80 → x+108 画在 856 画布上。不位移时白框整体比被点选的
    瓷砖左偏 108px (旋转拼图实测反馈)。

    修法: 挂在框函数内的 `call SelectObject` 位点, 帧内 X 局部位于 [esp+0x10]
    (42D234 的 GetDC 缓冲在帧 +8, 故 X 在 +0xC → [esp+0x18]), 加 108 后尾调原
    SelectObject —— 参数/栈平衡/返回地址语义不变。

    7 个小游戏的全部 6 条框函数 (4298A4/429990 八阵图, 42D234 MG_WA, 42DB20
    旋转拼图, 42EAA0 MG_reverse, 42F358 MG_44 — 与 `_UI_HOOKS` 的 6 个 GDI
    MoveToEx 位点一一对应) 都必须挂上, 否则该游戏的选中框仍会左偏 108px。
    """

    # 位点 -> (cave 入口, SelectObject 调用原字节)
    SITES = {
        0x298E8: ("setbox_shift", "E8 11 BA 0B 00"),
        0x299D4: ("setbox_shift", "E8 25 B9 0B 00"),
        0x2D2E9: ("setbox_shift_deep", "E8 10 80 0B 00"),
        0x2DB66: ("setbox_shift", "E8 93 77 0B 00"),
        0x2EAE4: ("setbox_shift", "E8 15 68 0B 00"),
        0x2F39C: ("setbox_shift", "E8 5D 5F 0B 00"),
    }
    # X 局部相对 cave 入口 esp 的偏移: [esp+0x10] / [esp+0x18]
    WRAPPERS = {"setbox_shift": 0x10, "setbox_shift_deep": 0x18}

    def test_all_box_sites_hooked(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        got = {int(s["rva"], 0): s for s in raw["sites"]}
        for rva, (entry, expect) in self.SITES.items():
            site = got.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 选中框位移位点缺失")
            self.assertEqual(site.get("kind"), "call", f"{rva:#X}: 必须是 call 钩子")
            self.assertEqual(site.get("ref"), entry, f"{rva:#X}: cave 入口不对")
            self.assertEqual((site.get("expect") or "").upper(), expect,
                             f"{rva:#X}: 位点不是该框函数的 SelectObject 调用")

    def test_wrappers_add_x_offset(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_sbx", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        for entry, off in self.WRAPPERS.items():
            want = (b"\x81\x44\x24" + bytes([off]) + (108).to_bytes(4, "little")
                    + b"\xB8" + (0x4E52FE).to_bytes(4, "little") + b"\xFF\xE0")
            start = module.CAVE_ENTRIES[entry]
            got = blob[start:start + len(want)]
            self.assertEqual(got, want,
                             f"{entry}: 必须是 add [esp+{off:#x}],108 + 尾调 SelectObject")


class PickupMappingTests(unittest.TestCase):
    """拾取缓冲 (实体/出入口命中) 必须与 856 画布同空间。

    word_78E276 是 640x480 静态 BSS (614400B, 尾部紧贴 824276 起的鼠标全局, 不可
    扩容; 搬运方案实测读档卡死已回退)。实体渲染 sub_406864 用屏幕坐标写它、鼠标侧
    sub_410B74 用 [0x824278] 读它; 856 画布下实体屏幕坐标整体 +108, 若不做处理,
    原版可见区的实体一旦落到 x>=640 就没有缓冲内容、读侧读到边缘列 → 悬停闪烁、
    点不动 (实测洛阳市集实体 #780)。

    修法: 写入侧 X-=108 + 读取侧改读 PAGE_X(= clamp(raw-108,0,639)) → 缓冲列 ==
    原版 640 视图列; 屏幕左右边带 (raw-108 ∉ [0,640)) 在**缓冲读取指令处**只把读出的
    id 换成 -1 (真实实体 id 恒 >= 0), 这样 sub_410B74 内 a1==2 分支的世界坐标 bbox +
    标志 + 掩码兜底照常执行 —— 实测: 若改成"读函数入口直接 return -1", 兜底就被跳过,
    洛阳市集最右侧出入点会失去悬停效果。map_camera cave 重建视口后同步重算
    824280/824284 (bbox 兜底的输入)。
    """

    # (位点 -> (cave 入口, 原字节))
    CALL_SITES = {
        0x6CBD: ("pickup_shift", "E8 82 DC 04 00"),
        0x10B77: ("pickup_read_sync", "A1 78 42 82 00"),
        0x10BAF: ("pickup_oob", "0F BF 14 55 76 E2 78 00"),
    }
    READ_SITE = 0x10B77

    def _sites(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        return {int(s["rva"], 0): s for s in raw["sites"]}

    def test_read_site_uses_page_x_and_world_sync(self):
        site = self._sites().get(self.READ_SITE)
        self.assertIsNotNone(site, "拾取读点 X 位点缺失")
        self.assertEqual((site.get("expect") or "").upper(), "A1 78 42 82 00")
        self.assertEqual(site.get("kind"), "call", "拾取读点必须接入同步 cave")
        self.assertEqual(site.get("ref"), "pickup_read_sync",
                         "拾取读点必须先同步世界坐标, 再读 PAGE_X")

    def test_write_and_oob_sites_hooked(self):
        got = self._sites()
        for rva, (entry, expect) in self.CALL_SITES.items():
            site = got.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 拾取位点缺失")
            self.assertEqual(site.get("kind"), "call", f"{rva:#X}: 必须是 call 钩子")
            self.assertEqual(site.get("ref"), entry, f"{rva:#X}: cave 入口不对")
            self.assertEqual((site.get("expect") or "").upper(), expect,
                             f"{rva:#X}: 位点原字节不符")
        # 不得再有"读函数入口短路"位点 (那会跳掉 bbox 兜底)
        oob = [rva for rva, s in got.items() if s.get("ref") == "pickup_oob"]
        self.assertEqual(oob, [0x10BAF], "pickup_oob 只能挂在缓冲读取指令处")

    def test_pickup_caves_bytes(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_pk", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()

        shift = (b"\x81\x6C\x24\x08" + (108).to_bytes(4, "little")     # sub [esp+8],108 (X)
                 + b"\xB8" + (0x454944).to_bytes(4, "little") + b"\xFF\xE0")
        start = module.CAVE_ENTRIES["pickup_shift"]
        self.assertEqual(blob[start:start + len(shift)], shift,
                         "pickup_shift 必须是 X-=108 + 尾调 454944")

        sync = (b"\x59"
                + b"\xA1" + (0x8242A8).to_bytes(4, "little")
                + b"\x03\x05" + (0x824278).to_bytes(4, "little")
                + b"\xA3" + (0x824280).to_bytes(4, "little")
                + b"\x8B\x15" + (0x8242AC).to_bytes(4, "little")
                + b"\x03\x15" + (0x82427C).to_bytes(4, "little")
                + b"\x89\x15" + (0x824284).to_bytes(4, "little")
                + b"\xA1" + module._g_page_x()
                + b"\xFF\xE1")
        start = module.CAVE_ENTRIES["pickup_read_sync"]
        self.assertEqual(blob[start:start + len(sync)], sync,
                         "pickup_read_sync 必须先算当前世界坐标, 再装载 PAGE_X")

        # pickup_oob: 边带(出界) 把读出的 id 换成 -1, 中心区执行原读取指令, 再跳回 site+8
        start = module.CAVE_ENTRIES["pickup_oob"]
        oob = blob[start:start + len(module.build_pickup_oob())]
        self.assertTrue(oob.startswith(b"\x59\x89\x0D" + module._g_ret()),
                        "pickup_oob 必须先保存返回地址 (site+8)")
        guard = (b"\xA1" + (0x824278).to_bytes(4, "little")     # mov eax,[0x824278] 原始 X
                 + b"\x2D" + (108).to_bytes(4, "little")        # sub eax,108
                 + b"\x85\xC0")                                 # test eax,eax
        self.assertIn(guard, oob, "pickup_oob 必须按 原始X-108 判断是否在边带")
        self.assertIn(b"\x0F\xBF\x14\x55" + (0x78E276).to_bytes(4, "little"), oob,
                      "pickup_oob 中心区必须保留原缓冲读取指令")
        self.assertIn(b"\xBA\xFF\xFF\xFF\xFF", oob, "pickup_oob 边带必须给出 -1 id")
        self.assertTrue(oob.endswith(b"\x8B\x0D" + module._g_ret() + b"\xFF\xE1"),
                        "pickup_oob 必须返回 site+8 (不能跳过 bbox 兜底)")

    def test_map_camera_recomputes_mouse_world(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_mc", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        want = (b"\xA1" + (0x8242A8).to_bytes(4, "little")    # mov eax,[8242A8] viewX
                + b"\x03\x05" + (0x824278).to_bytes(4, "little")   # add eax,[824278]
                + b"\xA3" + (0x824280).to_bytes(4, "little")       # mov [824280],eax
                + b"\xA1" + (0x8242AC).to_bytes(4, "little")
                + b"\x03\x05" + (0x82427C).to_bytes(4, "little")
                + b"\xA3" + (0x824284).to_bytes(4, "little"))
        start = module.CAVE_ENTRIES["map_camera"]
        self.assertIn(want, blob[start:start + 400],
                      "map_camera 重建视口后必须重算 824280/824284 (鼠标世界坐标)")


class PrimitiveTwinCoverageTests(unittest.TestCase):
    """绘制原语"孪生"覆盖: 45AA8C 与 45B20C 是同一裁剪结构的孪生体 (间距 0x780)。

    45AA8C 的每个步长/宽度位点在 45B20C 都有孪生位点 (+0x780)。历史提交只补了 5 个,
    漏了 9 个 (其中 0x5B630 是 `add eax,0x95b00` = 479*1280 这类**非 640 立即数**,
    靠"640 立即数扫描"发现不了 —— 只能靠孪生比对) → 该原语在 856 画布上仍按 640
    换行/裁剪, 走它的精灵会逐行漂 216px。
    """

    PAIRS = {
        0x5AB98: 0x5B318, 0x5AC0E: 0x5B38E, 0x5AC76: 0x5B3F6, 0x5AC97: 0x5B417,
        0x5AE6A: 0x5B5EA, 0x5AEB0: 0x5B630, 0x5AF7A: 0x5B6FA, 0x5AF84: 0x5B704,
        0x5AFA5: 0x5B725, 0x5B001: 0x5B781, 0x5B00B: 0x5B78B, 0x5B015: 0x5B795,
        0x5B036: 0x5B7B6, 0x5B07F: 0x5B7FF,
    }

    def test_twin_sites_all_present(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        got = {int(s["rva"], 0): s for s in raw["sites"]}
        for src, twin in self.PAIRS.items():
            self.assertIn(src, got, f"{src:#X}: 参考位点缺失")
            self.assertIn(twin, got, f"{twin:#X}: 孪生位点缺失 (= 该原语仍按 640 步长)")
            self.assertEqual(got[twin].get("kind"), got[src].get("kind"),
                             f"{twin:#X}: 孪生位点的钩子类型与 {src:#X} 不一致")
            self.assertEqual(got[twin].get("ref"), got[src].get("ref"),
                             f"{twin:#X}: 孪生位点的 cave 入口与 {src:#X} 不一致")


class NameInputPageTests(unittest.TestCase):
    """姓名输入页必须按 856 直接绘制, 且绘制/命中坐标统一居中。

    42539C 不像普通页面状态机那样先 grab 到 640 缓冲再 push; 它直接把精灵和
    文字画到 856 后备表面。若套页面 640 步长包装, 每行会按 640 回卷 (固定
    横向拉丝), 且所有 X 仍停在左侧 640 区域。正确语义是:
      - 42539C 保持游戏态 856 步长, 不做页面包装;
      - 本页 13 个绘制 X +108;
      - 4258F0/425DB0 的 8 个点击 X 读 PAGE_REC_X(raw X-108);
      - 头像 211、按钮 hover 207/208、按下 209/210 走 RLE 处理器。
    """

    X_SHIFT_SITES = {
        0x25528: "6A 6C",             # 44E49C text x 0 -> 108 (push imm8)
        0x2554A: "68 41 01 00 00",   # 4544EC sprite x 213 -> 321
        0x2555F: "68 25 01 00 00",   # 4258A4 IME text x 185 -> 293
        0x25586: "68 9C 01 00 00",   # text x 304 -> 412
        0x255AC: "68 E0 01 00 00",   # text x 372 -> 480
        0x255D4: "68 9C 01 00 00",
        0x255FA: "68 E0 01 00 00",
        0x2570B: "68 9C 01 00 00",
        0x25733: "68 E0 01 00 00",
        0x2577C: "68 BA 01 00 00",   # sprite x 334 -> 442
        0x257BF: "68 FC 01 00 00",   # sprite x 400 -> 508
        0x257F6: "68 BA 01 00 00",
        0x25826: "68 FC 01 00 00",
    }

    HIT_X_SITES = {
        0x25C69: "8B 0D 44 08 66 00",
        0x25C77: "A1 44 08 66 00",
        0x25C95: "8B 0D 44 08 66 00",
        0x25CA7: "A1 44 08 66 00",
        0x25DCD: "8B 0D 44 08 66 00",
        0x25DDB: "A1 44 08 66 00",
        0x25DEB: "8B 15 44 08 66 00",
        0x25DF9: "8B 0D 44 08 66 00",
    }

    HOVER_X_SITES = {
        0x25E31: "8B 0D 40 08 66 00",
        0x25E3F: "A1 40 08 66 00",
        0x25E4F: "8B 15 40 08 66 00",
        0x25E5D: "8B 0D 40 08 66 00",
    }

    AVATAR_HOOK = (0x25550, "spr_ui25550", "E8 97 EF 02 00")
    BUTTON_HOVER_HOOKS = (
        (0x257FC, "spr_ui257FC", "E8 EB EC 02 00"),  # frame207, left hover
        (0x2582C, "spr_ui2582C", "E8 BB EC 02 00"),  # frame208, right hover
    )
    BUTTON_CLICK_HOOKS = (
        (0x25782, "spr_ui25782", "E8 65 ED 02 00"),  # frame209, left click
        (0x257C5, "spr_ui257C5", "E8 22 ED 02 00"),  # frame210, right click
    )

    def _sites(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        return {int(s["rva"], 0): s for s in raw["sites"]}

    def test_direct_render_x_shifted(self):
        sites = self._sites()
        for rva, replacement in self.X_SHIFT_SITES.items():
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 姓名页绘制 X 位点缺失")
            self.assertEqual((site.get("replace") or "").upper(), replacement,
                             f"{rva:#X}: 姓名页绘制 X 未加 108")

    def test_page_stride_wrapper_removed(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_name_page", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertNotIn("wrap_page_42539C", module.CAVE_ENTRIES,
                         "姓名页必须保持 856 步长直接绘制, 不能再套 640 页面包装")
        self.assertNotIn(0xD434, self._sites(),
                         "0xD434 的页面包装 call 位点必须撤掉")

    def test_hit_tests_read_page_x(self):
        sites = self._sites()
        for rva, replacement in self.HIT_X_SITES.items():
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 姓名页点击 X 读点缺失")
            self.assertEqual((site.get("replace") or "").upper(), replacement,
                             f"{rva:#X}: 姓名页点击命中仍读 raw X")

    def test_hover_hit_uses_page_x(self):
        sites = self._sites()
        for rva, replacement in self.HOVER_X_SITES.items():
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 姓名页 hover X 读点缺失")
            self.assertEqual((site.get("replace") or "").upper(), replacement,
                             f"{rva:#X}: 姓名页 hover 命中仍读 raw X")

    def test_avatar_uses_rle_handler(self):
        rva, entry, expect = self.AVATAR_HOOK
        site = self._sites().get(rva)
        self.assertIsNotNone(site, f"{rva:#X}: 姓名页头像调用位点缺失")
        self.assertEqual(site.get("kind"), "call", f"{rva:#X}: 头像必须走 cave 处理器")
        self.assertEqual(site.get("ref"), entry, f"{rva:#X}: 头像 cave 入口不对")
        self.assertEqual((site.get("expect") or "").upper(), expect,
                         f"{rva:#X}: 位点不是姓名页头像 4544EC 调用")

    def test_button_hover_uses_rle_handler(self):
        sites = self._sites()
        for rva, entry, expect in self.BUTTON_HOVER_HOOKS:
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 按钮悬停调用位点缺失")
            self.assertEqual(site.get("kind"), "call", f"{rva:#X}: 悬停按钮必须走 cave 处理器")
            self.assertEqual(site.get("ref"), entry, f"{rva:#X}: 悬停按钮 cave 入口不对")
            self.assertEqual((site.get("expect") or "").upper(), expect,
                             f"{rva:#X}: 位点不是悬停按钮 4544EC 调用")

    def test_button_click_uses_rle_handler(self):
        sites = self._sites()
        for rva, entry, expect in self.BUTTON_CLICK_HOOKS:
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 按钮点击调用位点缺失")
            self.assertEqual(site.get("kind"), "call", f"{rva:#X}: 点击按钮必须走 cave 处理器")
            self.assertEqual(site.get("ref"), entry, f"{rva:#X}: 点击按钮 cave 入口不对")
            self.assertEqual((site.get("expect") or "").upper(), expect,
                             f"{rva:#X}: 位点不是点击按钮 4544EC 调用")


class BattleCurtainExitTests(unittest.TestCase):
    """43A8D8 入场末帧与出场首帧必须使用同一组 856 居中坐标。"""

    EXIT_LITERAL_SITES = {
        0x3B009: ("66 81 C1 E6 00", "66 81 C1 52 01"),  # 34*j+230 -> +338
        0x3B07F: ("66 05 55 01", "66 05 C1 01"),  # 24*j+341 -> +449
        0x3B0F4: ("66 81 C2 BC 01", "66 81 C2 28 02"),  # 14*j+444 -> +552
    }
    FIRST_X_HOOK = (
        0x3AF94,
        "curtain_exit_first_x",
        "66 83 C2 74 66 89 54 24 0A",  # add dx,116 + mov [esp+0xA],dx
    )

    def test_exit_curtain_starts_where_entry_finishes(self):
        import json
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        raw = json.loads((patch_dir / "patch.json").read_text(encoding="utf-8"))
        sites = {int(s["rva"], 0): s for s in raw["sites"]}
        rva, entry, expect = self.FIRST_X_HOOK
        site = sites.get(rva)
        self.assertIsNotNone(site, f"{rva:#X}: 幕帘第一组 X 位点缺失")
        self.assertEqual(site.get("kind"), "call")
        self.assertEqual(site.get("ref"), entry)
        self.assertEqual((site.get("expect") or "").upper(), expect)
        for rva, (expect, replacement) in self.EXIT_LITERAL_SITES.items():
            site = sites.get(rva)
            self.assertIsNotNone(site, f"{rva:#X}: 幕帘出场坐标位点缺失")
            self.assertEqual((site.get("expect") or "").upper(), expect)
            self.assertEqual((site.get("replace") or "").upper(), replacement,
                             f"{rva:#X}: 出场首帧未与入场末帧同加 108")

    def test_first_curtain_x_cave_replays_store(self):
        import importlib.util
        patch_dir = ROOT / "tks_launcher_gui" / "patches" / "widescreen_16_9"
        spec = importlib.util.spec_from_file_location("_ws_curtain_x", patch_dir / "cave_code.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = module.build_cave_block()
        want = (b"\x59"
                + b"\x66\x81\xC2\xE0\x00"
                + b"\x66\x89\x54\x24\x0A"
                + b"\xFF\xE1")
        start = module.CAVE_ENTRIES["curtain_exit_first_x"]
        self.assertEqual(blob[start:start + len(want)], want)


if __name__ == "__main__":
    unittest.main()
