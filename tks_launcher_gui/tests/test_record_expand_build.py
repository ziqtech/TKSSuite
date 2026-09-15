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
)
from core.patch_engine import _apply_patch_data_expand  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.lzss import (  # noqa: E402
    lzss_compress_dat, lzss_decompress_dat,
)


GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))


class RecordExpandBuildTests(unittest.TestCase):
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
            ("tkitem_expand", "TKItem.dat"),
            ("tkshop_expand", "TKShop.dat"),
        ):
            patch_def = next(p for p in cfg.patches if p.id == patch_id)
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
        patch_def = next(p for p in cfg.patches if p.id == "tkitem_expand")

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

        aux_base = 0x20000000 + 65536
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
        patch = next(p for p in cfg.patches if p.id == "tkitem_expand")
        self.assertEqual(patch.type, "patch_data_expand")
        self.assertEqual(patch.old_base, 0x77CBCA)
        self.assertEqual(patch.old_size, 38400)
        self.assertEqual(patch._extra.get("buffer_cap"), 65536)
        self.assertEqual(patch._extra.get("aux_size"), 1024)

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

            self.assertEqual(tkitem.Misc_VirtualSize, 65536 + 1024)
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
                        + tkitem.VirtualAddress)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
