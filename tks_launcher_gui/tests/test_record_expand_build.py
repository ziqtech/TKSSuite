"""tkitem_expand / tkshop_expand 离线构建回归测试。

验证现有物品/商店扩容补丁已从“仅放行加载”升级为完整数据段扩容：
注入独立缓冲、重定向基址/大小/字段引用，并改写安全范围内的记录数上限。
"""
import os
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
from editor_utils.lzss import lzss_decompress_dat  # noqa: E402


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

        content = lzss_decompress_dat(
            (GAME_DIR / "TKItem.dat").read_bytes())
        content += b"\0" * 64
        content = content.ljust(65536, b"\0")
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

            self.assertEqual(tkitem.Misc_VirtualSize, 65536)
            self.assertEqual(
                text.count(bytes.fromhex("81 FA FF 03 00 00")), 2)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7C 24 02 FE 03")), 1)
            self.assertEqual(
                text.count(bytes.fromhex("81 FA 58 02 00 00")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("66 81 7C 24 02 2F 02")), 0)
            self.assertEqual(
                text.count(bytes.fromhex("68 00 00 01 00")), 1)

            new_base = (pe.OPTIONAL_HEADER.ImageBase
                        + tkitem.VirtualAddress)
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
