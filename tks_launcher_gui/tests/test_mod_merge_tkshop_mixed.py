"""TKShop.dat (field_type=mixed) MOD 差异合并回归。

背景: _apply_fields_to_record 此前没有 mixed 分支, [商店] 子青版TKShop 的
3 条追加记录共 7 个非零字段全部写入失败, 合并产物变成 3 条全零记录
(area=0 恰为药店槽, 正是 tkshop_expand tail_fill=255 要防的毒槽)。
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat
from tks_launcher_gui.core.mod_loader import (
    DAT_FILE_INFO,
    TKSHOP_FIELD_LAYOUT,
    ModInfo,
    _apply_fields_to_record,
    _merge_dat_file,
)


def shop_bytes(count=240):
    buf = bytearray(count * 8)
    for i in range(count):
        struct.pack_into("<h", buf, i * 8, i % 5)
        struct.pack_into("<h", buf, i * 8 + 2, i)
        struct.pack_into("<h", buf, i * 8 + 4, 1)
    return bytes(buf)


def fields_of(record_bytes, index):
    base = index * 8
    return {
        "area_id": struct.unpack_from("<h", record_bytes, base)[0],
        "item_ref": struct.unpack_from("<h", record_bytes, base + 2)[0],
        "condition": struct.unpack_from("<h", record_bytes, base + 4)[0],
        "display": record_bytes[base + 6],
        "reserved": record_bytes[base + 7],
    }


class TestMixedFieldApply(unittest.TestCase):

    def test_layout_matches_shop_record(self):
        self.assertEqual(len(TKSHOP_FIELD_LAYOUT), DAT_FILE_INFO["TKShop.dat"]["field_count"])
        offsets = [off for off, _ in TKSHOP_FIELD_LAYOUT]
        sizes = [struct.calcsize(fmt) for _, fmt in TKSHOP_FIELD_LAYOUT]
        self.assertEqual(offsets, [0, 2, 4, 6])
        self.assertEqual(sum(sizes) + 1, 8)  # 4 字段 + 1 保留字节

    def test_apply_mixed_fields(self):
        rec = bytearray(8)
        skipped = _apply_fields_to_record(
            rec, 0, 8, "mixed", 4, {"f0": 3, "f1": 777, "f2": -1, "f3": 2})
        self.assertEqual(skipped, 0)
        self.assertEqual(fields_of(bytes(rec), 0),
                         {"area_id": 3, "item_ref": 777, "condition": -1,
                          "display": 2, "reserved": 0})

    def test_apply_out_of_range_value_skipped(self):
        rec = bytearray(8)
        skipped = _apply_fields_to_record(rec, 0, 8, "mixed", 4, {"f3": 300})
        self.assertEqual(skipped, 1)
        self.assertEqual(struct.unpack_from("<h", rec, 0)[0], 0)

    def test_apply_unknown_field_skipped(self):
        rec = bytearray(8)
        skipped = _apply_fields_to_record(rec, 0, 8, "mixed", 4, {"f9": 1})
        self.assertEqual(skipped, 1)


class TestMergeTkShopMod(unittest.TestCase):

    def test_appended_and_modified_records_written(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "TKShop.dat")
            Path(path).write_bytes(lzss_compress_dat(shop_bytes(240)))

            diff = {
                "modified": [{"index": 5, "fields": {"f0": 4, "f1": 300}}],
                "appended": [
                    {"index": 240, "fields": {"f0": 1, "f1": 600, "f2": 1}},
                    {"index": 241, "fields": {"f0": 2, "f1": 601}},
                    {"index": 242, "fields": {"f0": 0, "f1": 602, "f2": 1, "f3": 1}},
                ],
            }
            logs = []
            merged = _merge_dat_file(path, "TKShop.dat", dict(DAT_FILE_INFO["TKShop.dat"]),
                                     [(ModInfo(name="[商店] 子青版TKShop"), diff)],
                                     logs.append)

            self.assertNotIn("[WARN]", "\n".join(logs))
            dec = lzss_decompress_dat(merged)
            self.assertEqual(len(dec), 243 * 8)

            mod5 = fields_of(dec, 5)
            self.assertEqual((mod5["area_id"], mod5["item_ref"], mod5["condition"]), (4, 300, 1))

            self.assertEqual(fields_of(dec, 240),
                             {"area_id": 1, "item_ref": 600, "condition": 1,
                              "display": 0, "reserved": 0})
            self.assertEqual(fields_of(dec, 241),
                             {"area_id": 2, "item_ref": 601, "condition": 0,
                              "display": 0, "reserved": 0})
            self.assertEqual(fields_of(dec, 242),
                             {"area_id": 0, "item_ref": 602, "condition": 1,
                              "display": 1, "reserved": 0})

    def test_no_zero_record_when_every_field_fails(self):
        # 未知字段名的追加记录不得变成全零药店槽 (写入失败数须如实上报)
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "TKShop.dat")
            Path(path).write_bytes(lzss_compress_dat(shop_bytes(240)))

            diff = {"modified": [], "appended": [
                {"index": 240, "fields": {"bad": 1, "f99": 2}}]}
            logs = []
            merged = _merge_dat_file(path, "TKShop.dat", dict(DAT_FILE_INFO["TKShop.dat"]),
                                     [(ModInfo(name="x"), diff)], logs.append)

            self.assertIn("2 个字段写入失败", "\n".join(logs))
            dec = lzss_decompress_dat(merged)
            self.assertEqual(len(dec), 241 * 8)
            self.assertEqual(fields_of(dec, 240),
                             {"area_id": 0, "item_ref": 0, "condition": 0,
                              "display": 0, "reserved": 0})


if __name__ == "__main__":
    unittest.main()
