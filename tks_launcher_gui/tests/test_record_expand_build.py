"""tkitem_expand / tkshop_expand 离线构建回归测试。

验证现有物品/商店扩容补丁已从“仅放行加载”升级为完整数据段扩容：
注入独立缓冲、重定向基址/大小/字段引用，并改写安全范围内的记录数上限。
"""
import ctypes
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import pefile


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.exe_builder import (  # noqa: E402
    BytesPatchEntry, BytesPatchItem, DataSectionPatchItem, ExeBuilder,
    align_up,
)
from core.patch_engine import _apply_patch_data_expand  # noqa: E402
from core.patch_plan import build_patch_plan  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from ui.generate_exe_dialog import (  # noqa: E402
    GenerateExeDialog, expansion_logical_size,
)
from editor_utils.lzss import (  # noqa: E402
    lzss_compress_dat, lzss_decompress_dat,
)


GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))


def tkitem_table_operation(game_dir):
    """取 tkitem_expand 组合补丁内的"物品表扩容"操作。

    tkitem_expand 现为 bundle: 定义在包内 data_expand.json, 由 prepare.py 展开
    为计划里的普通 patch_data_expand 操作 (id = tkitem_expand.table)。
    """
    cfg = load_patch_directory(str(LAUNCHER / "patches"),
                               log_func=lambda *_a: None)
    plan = build_patch_plan(
        cfg.patches, selected={"tkitem_expand"},
        resolve_file=lambda name: str(Path(game_dir) / name))
    return next(op for op in plan.patches if op.id == "tkitem_expand.table")


class RecordExpandBuildTests(unittest.TestCase):
    def test_warpc_logical_size_excludes_pe_backing_padding(self):
        with tempfile.TemporaryDirectory() as td:
            wardata = Path(td) / "WarPC.dat"
            wardata.write_bytes(b"\0" * 527000)

            patch_def = SimpleNamespace(
                id="warpc_base_refs",
                name="WarPC 数据重定位",
                data_file="WarPC.dat",
                old_base=0x757F08,
                old_size=150722,
                section_name=".warpc",
                needs_lzss=False,
                activate_if_expanded=False,
                bytes_patches=[],
                pattern="",
                value_offset=0,
                expect_count=0,
                _extra={
                    "buffer_cap": 527000,
                    "aux_size": 0,
                    "front_pad": 0,
                    "aux_patches": [],
                },
            )
            dialog = SimpleNamespace(
                _resolve_data_file=lambda filename: str(Path(td) / filename),
                _log=lambda _msg: None,
            )

            item = GenerateExeDialog._build_data_section(dialog, patch_def)

            self.assertIsNotNone(item)
            self.assertEqual(item.logical_size, 527000)
            self.assertEqual(item.backing_size, 589824)
            self.assertEqual(len(item.data), 589824)

            value_patch = SimpleNamespace(
                id="warpc_size_refs",
                new_value_expr="{warpc_new_size}",
                expect_value=0,
                _extra={"buffer_cap": 527000},
            )
            dialog._read_data_file_size = lambda _name: 527000
            self.assertEqual(
                GenerateExeDialog._resolve_imm32_value(dialog, value_patch),
                527000,
            )

    def test_logical_size_helper_does_not_align(self):
        self.assertEqual(expansion_logical_size(527000, 527000), 527000)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "WarPC.dat").is_file(),
        "需要原版 TKS.exe / WarPC.dat 才能验证逻辑容量烧录",
    )
    def test_warpc_build_uses_logical_size_constant(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch_def = next(p for p in cfg.patches
                         if p.id == "warpc_base_refs")
        dialog = SimpleNamespace(
            _resolve_data_file=lambda filename: str(GAME_DIR / filename),
            _log=lambda _msg: None,
        )
        item = GenerateExeDialog._build_data_section(dialog, patch_def)
        self.assertIsNotNone(item)
        self.assertEqual(item.logical_size, 527000)
        self.assertEqual(item.backing_size, 589824)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_warpc_size.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out), data_section_patches=[item])
            self.assertTrue(result.success, "\n".join(result.log))

            original_pe = pefile.PE(str(GAME_DIR / "TKS.exe"),
                                    fast_load=True)
            original_text = next(
                s for s in original_pe.sections
                if s.Name.rstrip(b"\0") == b".text").get_data()
            built_pe = pefile.PE(data=out.read_bytes(), fast_load=True)
            built_text = next(
                s for s in built_pe.sections
                if s.Name.rstrip(b"\0") == b".text").get_data()

            old_size = struct.pack("<I", 150722)
            new_size = struct.pack("<I", 527000)
            offsets = []
            pos = 0
            while True:
                pos = original_text.find(old_size, pos)
                if pos < 0:
                    break
                offsets.append(pos)
                pos += 4
            self.assertEqual(len(offsets), 5)
            for off in offsets:
                self.assertEqual(built_text[off:off + 4], new_size)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKItem.dat").is_file()
        and (GAME_DIR / "TKShop.dat").is_file(),
        "需要原版数据文件才能验证运行时扩容门控",
    )
    def test_runtime_keeps_original_data_untouched(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        for patch_id, data_file in (
            ("tkitem_expand.table", "TKItem.dat"),
            ("tkshop_expand", "TKShop.dat"),
        ):
            patch_def = (tkitem_table_operation(GAME_DIR)
                         if patch_id == "tkitem_expand.table"
                         else next(p for p in cfg.patches if p.id == patch_id))
            logs = []
            ctx = SimpleNamespace(log=logs.append)
            with patch("core.patch_engine.os.path.isfile",
                       return_value=True), \
                    patch("builtins.open", mock_open(
                        read_data=(GAME_DIR / data_file).read_bytes())), \
                    patch("core.patch_engine._VirtualAllocEx") as alloc:
                self.assertTrue(
                    _apply_patch_data_expand(patch_def, ctx))
                alloc.assert_not_called()
            self.assertTrue(any("保持原版逻辑" in line for line in logs))

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKItem.dat").is_file(),
        "需要原版 TKItem.dat 才能验证运行时辅助数组重定向",
    )
    def test_runtime_redirects_transaction_quantity_array(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch_def = tkitem_table_operation(GAME_DIR)

        expanded = lzss_decompress_dat(
            (GAME_DIR / "TKItem.dat").read_bytes()) + b"\0" * 64
        compressed = lzss_compress_dat(expanded)

        code = bytearray(4096)
        struct.pack_into('<I', code, 0, patch_def.old_base)
        struct.pack_into('<I', code, 4, patch_def.old_size)
        pattern_sites = []
        pos = 64
        for entry in patch_def._extra["aux_patches"]:
            pattern = bytes.fromhex(entry["pattern"].replace(" ", ""))
            for _ in range(int(entry.get("expect_count", 1))):
                code[pos:pos + len(pattern)] = pattern
                pattern_sites.append((pos, entry, pattern))
                pos += len(pattern) + 16

        logs = []
        ctx = SimpleNamespace(
            log=logs.append, h_proc=1, code_buf=code,
            code_start_addr=0x400000)
        fake_alloc = ctypes.c_void_p(0x20000000)

        def fake_write(_proc, _addr, payload):
            return len(payload)

        with patch("core.patch_engine.os.path.isfile",
                   return_value=True), \
                patch("builtins.open", mock_open(read_data=compressed)), \
                patch("core.patch_engine._VirtualAllocEx",
                      return_value=fake_alloc), \
                patch("core.patch_engine.write_pm",
                      side_effect=fake_write), \
                patch("core.patch_engine.vp_ex", return_value=True), \
                patch("core.patch_engine.apply_patch_bytes",
                      return_value=True):
            self.assertTrue(
                _apply_patch_data_expand(patch_def, ctx),
                "\n".join(logs))

        aux_base = 0x20000000 + patch_def._extra["front_pad"] + 65536
        for off, entry, pattern in pattern_sites:
            patched = bytes(code[off:off + len(pattern)])
            for key, value in entry["replace"].items():
                self.assertEqual(patched[int(key)], int(value))
            aux_off = int(entry["aux_offset"])
            self.assertEqual(
                patched[aux_off:aux_off + 4],
                struct.pack('<I', aux_base))

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKItem.dat").is_file(),
        "需要原版 TKS.exe / TKItem.dat 才能执行离线构建验证",
    )
    def test_existing_patch_builds_complete_expansion(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = tkitem_table_operation(GAME_DIR)
        self.assertEqual(patch.type, "patch_data_expand")
        self.assertEqual(patch.old_base, 0x77CBCA)
        self.assertEqual(patch.old_size, 38400)
        self.assertEqual(patch._extra.get("buffer_cap"), 65536)
        self.assertEqual(patch._extra.get("aux_size"), 1024)
        self.assertEqual(patch._extra.get("front_pad"), 64)

        content = lzss_decompress_dat(
            (GAME_DIR / "TKItem.dat").read_bytes())
        content += b"\0" * 64
        content = content.ljust(65536, b"\0")
        logical_size = len(content)
        content += b"\0" * 1024
        entries = [
            BytesPatchEntry(
                pattern=bp["pattern"],
                replace={int(k): int(v)
                         for k, v in bp["replace"].items()},
                expect_count=bp["expect_count"],
            )
            for bp in patch.bytes_patches
        ]
        item = DataSectionPatchItem(
            patch_id=patch.id,
            name=patch.name,
            data=content,
            old_base=patch.old_base,
            old_size=patch.old_size,
            section_name=patch.section_name,
            redirect_base_span=64,
            logical_size=logical_size,
            aux_size=1024,
            front_pad=patch._extra.get("front_pad", 0),
            aux_patches=patch._extra.get("aux_patches", []),
            bytes_patches=[BytesPatchItem(
                patch_id=patch.id, name=patch.name, entries=entries)],
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_tkitem_expand.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out), data_section_patches=[item])
            self.assertTrue(result.success, "\n".join(result.log))

            built = out.read_bytes()
            pe = pefile.PE(data=built, fast_load=True)
            text = next(s for s in pe.sections
                        if s.Name.rstrip(b"\0") == b".text").get_data()
            tkitem = next(s for s in pe.sections
                          if s.Name.rstrip(b"\0") == b".tkitem")

            self.assertEqual(
                tkitem.Misc_VirtualSize, 65536 + 1024
                + patch._extra.get("front_pad", 0))
            # 无 tail_fill 的数据段保持 BSS 形态 (不占文件空间)
            self.assertEqual(tkitem.SizeOfRawData, 0)
            self.assertEqual(tkitem.PointerToRawData, 0)
            self.assertEqual(
                text.count(bytes.fromhex("81 FA FF 03 00 00")), 2)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7C 24 02 FE 03")), 1)
            self.assertEqual(
                text.count(bytes.fromhex("81 FA 58 02 00 00")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7C 24 02 2F 02")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D FE FE 03")), 2)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D FE 57 02")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("68 00 00 01 00")), 1)

            new_base = (pe.OPTIONAL_HEADER.ImageBase
                        + tkitem.VirtualAddress
                        + patch._extra.get("front_pad", 0))
            aux_base = new_base + logical_size
            self.assertGreaterEqual(
                text.count(new_base.to_bytes(4, "little")), 18)
            self.assertEqual(
                text.count((0x77CBCA).to_bytes(4, "little")), 0)
            for delta in range(1, 64):
                self.assertEqual(
                    text.count((0x77CBCA + delta).to_bytes(4, "little")),
                    0, f"旧 TKItem 字段锚 +0x{delta:X} 未重定向")
            self.assertEqual(
                text.count((38400).to_bytes(4, "little")), 0)
            aux_le = aux_base.to_bytes(4, "little")
            self.assertEqual(
                text.count(bytes.fromhex("8B 4D F4 0F BF 01 0F BE 0C 05")
                           + aux_le), 1)
            self.assertEqual(
                text.count(bytes.fromhex(
                    "8B 45 F4 0F BF 10 0F BF 0C 55 5A 75 75 00 "
                    "0F BE 14 0D") + aux_le), 1)
            self.assertEqual(
                text.count(bytes.fromhex("8D 0C 05") + aux_le), 1)
            self.assertEqual(
                text.count(bytes.fromhex("8D 14 0D") + aux_le), 1)
            self.assertEqual(
                text.count(bytes.fromhex("B8") + aux_le
                           + bytes.fromhex("89 45 F8 90")), 2)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKShop.dat").is_file(),
        "需要原版 TKS.exe / TKShop.dat 才能执行离线构建验证",
    )
    def test_existing_shop_patch_builds_complete_expansion(self):
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = next(p for p in cfg.patches if p.id == "tkshop_expand")
        self.assertEqual(patch.type, "patch_data_expand")
        self.assertEqual(patch.old_base, 0x9508A0)
        self.assertEqual(patch.old_size, 1920)
        self.assertEqual(patch._extra.get("buffer_cap"), 4096)

        content = lzss_decompress_dat(
            (GAME_DIR / "TKShop.dat").read_bytes())
        content += b"\0" * 8
        content = content.ljust(4096, b"\0")
        entries = [
            BytesPatchEntry(
                pattern=bp["pattern"],
                replace={int(k): int(v)
                         for k, v in bp["replace"].items()},
                expect_count=bp["expect_count"],
            )
            for bp in patch.bytes_patches
        ]
        item = DataSectionPatchItem(
            patch_id=patch.id,
            name=patch.name,
            data=content,
            old_base=patch.old_base,
            old_size=patch.old_size,
            section_name=patch.section_name,
            redirect_base_span=8,
            size_pattern=patch.pattern,
            size_value_offset=patch.value_offset,
            size_expect_count=patch.expect_count,
            bytes_patches=[BytesPatchItem(
                patch_id=patch.id, name=patch.name, entries=entries)],
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_tkshop_expand.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out), data_section_patches=[item])
            self.assertTrue(result.success, "\n".join(result.log))

            built = out.read_bytes()
            pe = pefile.PE(data=built, fast_load=True)
            text = next(s for s in pe.sections
                        if s.Name.rstrip(b"\0") == b".text").get_data()
            tkshop = next(s for s in pe.sections
                          if s.Name.rstrip(b"\0") == b".tkshop")

            self.assertEqual(tkshop.Misc_VirtualSize, 4096)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D DE FF 01")), 1)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D FC FF 01")), 3)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D DE F0 00")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7D FC F0 00")), 0)
            self.assertEqual(
                text.count((0x9508A0).to_bytes(4, "little")), 0)
            self.assertEqual(
                text.count((0x9508A6).to_bytes(4, "little")), 0)
            self.assertEqual(
                text.count((1920).to_bytes(4, "little")), 1,
                "VCL 中的非商店 1920 常量不应被误改")

            new_base = (pe.OPTIONAL_HEADER.ImageBase
                        + tkshop.VirtualAddress)
            self.assertEqual(
                text.count(b"\x68" + (4096).to_bytes(4, "little")
                           + b"\x68" + new_base.to_bytes(4, "little")), 1)
            self.assertGreaterEqual(
                text.count(new_base.to_bytes(4, "little")), 4)
            self.assertGreaterEqual(
                text.count((new_base + 6).to_bytes(4, "little")), 1)
            # 未声明 tail_fill 的数据段保持 BSS 形态 (不占文件空间)
            self.assertEqual(tkshop.SizeOfRawData, 0)
            self.assertEqual(tkshop.PointerToRawData, 0)

    @unittest.skipUnless(
        (GAME_DIR / "TKS.exe").is_file()
        and (GAME_DIR / "TKShop.dat").is_file(),
        "需要原版 TKS.exe / TKShop.dat 才能执行离线构建验证",
    )
    def test_shop_tail_fill_lands_in_built_exe(self):
        """tail_fill 数据段必须 raw-backed 落盘, 生成 EXE 中尾填真实存在。

        回归背景: 数据段默认 BSS (SizeOfRawData=0), item.data 内容副本从不
        写入文件, 尾填被加载器零初始化覆盖 → 生成 EXE 覆盖原版后药店仍刷
        #0 号 (ID 8037) 商品, 而 python main.py 运行时注入路径正常。
        """
        cfg = load_patch_directory(str(LAUNCHER / "patches"),
                                   log_func=lambda *_a: None)
        patch = next(p for p in cfg.patches if p.id == "tkshop_expand")

        content = lzss_decompress_dat(
            (GAME_DIR / "TKShop.dat").read_bytes())
        content += b"\0" * 8                      # 模拟 MOD 新增 1 条 → 241 条
        logical = max(len(content), patch._extra["buffer_cap"])
        content = content.ljust(logical, b"\xff")  # tail_fill=255 尾填
        data = content.ljust(0x10000, b"\0")       # 64KB 后备对齐 (补零)
        entries = [
            BytesPatchEntry(
                pattern=bp["pattern"],
                replace={int(k): int(v)
                        for k, v in bp["replace"].items()},
                expect_count=bp["expect_count"],
            )
            for bp in patch.bytes_patches
        ]
        item = DataSectionPatchItem(
            patch_id=patch.id,
            name=patch.name,
            data=data,
            old_base=patch.old_base,
            old_size=patch.old_size,
            section_name=patch.section_name,
            redirect_base_span=8,
            size_pattern=patch.pattern,
            size_value_offset=patch.value_offset,
            size_expect_count=patch.expect_count,
            logical_size=logical,
            backing_size=0x10000,
            tail_fill=255,
            bytes_patches=[BytesPatchItem(
                patch_id=patch.id, name=patch.name, entries=entries)],
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "TKS_tkshop_tailfill.exe"
            result = ExeBuilder(str(GAME_DIR / "TKS.exe")).build(
                [], str(out), data_section_patches=[item])
            self.assertTrue(result.success, "\n".join(result.log))
            self.assertTrue(
                any("raw-backed" in line for line in result.log))

            built = out.read_bytes()
            pe = pefile.PE(data=built, fast_load=True)
            tkshop = next(s for s in pe.sections
                          if s.Name.rstrip(b"\0") == b".tkshop")

            # raw-backed: raw 覆盖 front_pad+逻辑容量, VirtualSize 不变
            expected_raw = align_up(4096, pe.OPTIONAL_HEADER.FileAlignment)
            self.assertEqual(tkshop.SizeOfRawData, expected_raw)
            self.assertGreater(tkshop.PointerToRawData, 0)
            self.assertEqual(tkshop.Misc_VirtualSize, 0x10000)

            raw = tkshop.get_data()
            # raw 前 4096 字节 = 241 条记录 (1928) + 0xFF 尾填 (2168)
            self.assertEqual(raw[:4096], content)
            self.assertEqual(raw[1928:4096], b"\xff" * (4096 - 1928))

            # 游戏装载调用 push 4096 / push 新基址 仍各一处
            text = next(s for s in pe.sections
                        if s.Name.rstrip(b"\0") == b".text").get_data()
            new_base = (pe.OPTIONAL_HEADER.ImageBase
                        + tkshop.VirtualAddress)
            self.assertEqual(
                text.count(b"\x68" + (4096).to_bytes(4, "little")
                           + b"\x68" + new_base.to_bytes(4, "little")), 1)


    def test_runtime_tail_fill_covers_buffer_tail(self):
        """tail_fill=255: 数据未覆盖的缓冲区尾部必须填满声明字节。

        回归背景: TKShop 扩容段 241..510 槽保持 VirtualAlloc 零值时,
        零记录 (area=0 恰为药店 / item=0 引用 TKItem[0]) 会被商店扫描
        当成合法商品, 在药店刷出大量 #0 号 (ID 8037) 药品。
        """
        content = bytes(range(256)) * 4  # 1024 字节 > old_size 100
        code = bytearray(4096)
        old_base, old_size, cap = 0x500000, 100, 4096
        struct.pack_into('<I', code, 0, old_base)
        struct.pack_into('<I', code, 64, old_size)
        patch_def = SimpleNamespace(
            id="fake_expand", name="合成扩容", type="patch_data_expand",
            data_file="Fake.dat", old_base=old_base, old_size=old_size,
            section_name=".fake", needs_lzss=False,
            activate_if_expanded=True, bytes_patches=[],
            pattern="", value_offset=0, expect_count=0,
            _extra={"buffer_cap": cap, "aux_size": 0, "front_pad": 0,
                    "aux_patches": [], "tail_fill": 255},
        )
        logs = []
        ctx = SimpleNamespace(log=logs.append, h_proc=1, code_buf=code,
                              code_start_addr=0x400000)
        writes = []

        def fake_write(_proc, addr, payload):
            writes.append((addr, bytes(payload)))
            return len(payload)

        with patch("core.patch_engine.os.path.isfile", return_value=True), \
                patch("builtins.open", mock_open(read_data=content)), \
                patch("core.patch_engine._VirtualAllocEx",
                      return_value=ctypes.c_void_p(0x20000000)), \
                patch("core.patch_engine.write_pm", side_effect=fake_write), \
                patch("core.patch_engine.vp_ex", return_value=True):
            self.assertTrue(_apply_patch_data_expand(patch_def, ctx),
                            "\n".join(logs))

        self.assertEqual(writes[0], (0x20000000, content))
        self.assertEqual(writes[1], (0x20000000 + len(content),
                                     b"\xff" * (cap - len(content))))
        # 基址/大小引用重定向到扩容缓冲与逻辑容量
        self.assertIn((0x400000, struct.pack('<I', 0x20000000)), writes)
        self.assertIn((0x400040, struct.pack('<I', cap)), writes)
        self.assertTrue(any("尾部填充" in line for line in logs))

    def test_runtime_tail_fill_disabled_keeps_zero_tail(self):
        """未声明 tail_fill 的扩容补丁保持原行为 (尾部零填充), 不产生额外写入。"""
        content = bytes(range(256)) * 4
        code = bytearray(4096)
        old_base, old_size, cap = 0x500000, 100, 4096
        struct.pack_into('<I', code, 0, old_base)
        struct.pack_into('<I', code, 64, old_size)
        patch_def = SimpleNamespace(
            id="fake_expand", name="合成扩容", type="patch_data_expand",
            data_file="Fake.dat", old_base=old_base, old_size=old_size,
            section_name=".fake", needs_lzss=False,
            activate_if_expanded=True, bytes_patches=[],
            pattern="", value_offset=0, expect_count=0,
            _extra={"buffer_cap": cap, "aux_size": 0, "front_pad": 0,
                    "aux_patches": []},
        )
        ctx = SimpleNamespace(log=lambda _msg: None, h_proc=1,
                              code_buf=code, code_start_addr=0x400000)
        writes = []

        def fake_write(_proc, addr, payload):
            writes.append((addr, bytes(payload)))
            return len(payload)

        with patch("core.patch_engine.os.path.isfile", return_value=True), \
                patch("builtins.open", mock_open(read_data=content)), \
                patch("core.patch_engine._VirtualAllocEx",
                      return_value=ctypes.c_void_p(0x20000000)), \
                patch("core.patch_engine.write_pm", side_effect=fake_write), \
                patch("core.patch_engine.vp_ex", return_value=True):
            self.assertTrue(_apply_patch_data_expand(patch_def, ctx))

        self.assertEqual(writes[0], (0x20000000, content))
        self.assertFalse(any(
            addr == 0x20000000 + len(content) for addr, _p in writes))

    def test_data_section_tail_fill_offline(self):
        """离线生成 EXE 路径: tail_fill 覆盖逻辑容量缺口, 后备对齐区保持补零。"""
        content = bytes(range(256)) * 8  # 2048 字节, 模拟解压后的商店数据
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "Fake.dat").write_bytes(content)
            patch_def = SimpleNamespace(
                id="fake_expand", name="合成扩容", type="patch_data_expand",
                data_file="Fake.dat", old_base=0x9508A0, old_size=1920,
                section_name=".fake", needs_lzss=False,
                activate_if_expanded=True, bytes_patches=[],
                pattern="", value_offset=0, expect_count=0,
                _extra={"buffer_cap": 4096, "aux_size": 0, "front_pad": 0,
                        "aux_patches": [], "tail_fill": 255},
            )
            dialog = SimpleNamespace(
                _resolve_data_file=lambda filename: str(Path(td) / filename),
                _log=lambda _msg: None,
            )

            item = GenerateExeDialog._build_data_section(dialog, patch_def)

            self.assertIsNotNone(item)
            self.assertEqual(item.logical_size, 4096)
            self.assertEqual(len(item.data), 0x10000)
            self.assertEqual(item.data[:len(content)], content)
            self.assertEqual(item.data[len(content):4096],
                             b"\xff" * (4096 - len(content)))
            self.assertEqual(item.data[4096:], b"\x00" * (0x10000 - 4096))

            # 无 tail_fill: 尾部保持补零 (旧行为)
            patch_def._extra = {"buffer_cap": 4096, "aux_size": 0,
                                "front_pad": 0, "aux_patches": []}
            item = GenerateExeDialog._build_data_section(dialog, patch_def)
            self.assertEqual(item.data[len(content):4096],
                             b"\x00" * (4096 - len(content)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
