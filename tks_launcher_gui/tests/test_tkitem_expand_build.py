"""tkitem_expand 离线构建回归测试。

验证现有物品扩容补丁已从“仅放行加载”升级为完整数据段扩容：
注入 64KB 独立缓冲、重定向基址/大小/字段引用，并改写安全范围内的记录数上限。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.lzss import lzss_decompress_dat  # noqa: E402


GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))


class TkItemExpandBuildTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
