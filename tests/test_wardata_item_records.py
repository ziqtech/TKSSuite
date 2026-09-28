"""wardata_editor 物品记录加载回归测试 — 物品选择弹窗说明与 shop_editor 一致。"""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from editor_utils.tkt_loader import load_tkt_simple  # noqa: E402
from wardata_editor.wardata_editor import load_tkitem_records  # noqa: E402


def _make_tkt(entries):
    """构造 TKT.dat: entries = [(entry_id, 原始字节)], 控制字节直接内嵌"""
    ids = struct.pack('<' + 'i' * len(entries), *[e[0] for e in entries])
    texts = b''
    offs = []
    for _, tb in entries:
        offs.append(len(texts))
        texts += tb + b'\x00'
    off_bytes = struct.pack('<' + 'I' * len(entries), *offs)
    body = ids + off_bytes + texts
    return struct.pack('<II', len(body), len(entries)) + bytes(b ^ 0xFF for b in body)


def _make_tkitem(item_id=10, tab_code=2, name_id=100, desc_id=101):
    """构造单条 TKItem.dat 记录 (64 字节, 字段布局与 load_tkitem_records 一致)"""
    fields = [0] * 32
    fields[0], fields[1], fields[2] = item_id, tab_code, name_id
    fields[3], fields[4], fields[5] = desc_id, 0, 0
    fields[31] = 8000
    return struct.pack('<' + 'h' * 32, *fields)


class WarDataItemRecordsTests(unittest.TestCase):
    def test_desc_uses_full_multiline_tkt(self):
        # 名称带控制字节宏; 说明为完整两行 (色码 + FRESET + \x1e 换行)
        name_b = b'\x02\x0e' + '金烏劍'.encode('big5')
        desc_b = (b'\x02\x14' + '攻擊上升。'.encode('big5') + b'\x01\x01'
                  + b'\x1e' + '使用後消失。'.encode('big5'))
        with tempfile.TemporaryDirectory() as td:
            tkt_path = Path(td) / "TKT.dat"
            tkt_path.write_bytes(_make_tkt([(100, name_b), (101, desc_b)]))
            tkitem_path = Path(td) / "TKItem.dat"
            tkitem_path.write_bytes(lzss_compress_dat(_make_tkitem()))

            tkt_first = load_tkt_simple(str(tkt_path), first_line_only=True)
            tkt_full = load_tkt_simple(str(tkt_path), full_strip=True)

            recs = load_tkitem_records(str(tkitem_path), tkt_first, tkt_full=tkt_full)
            self.assertEqual(len(recs), 1)
            # 名称: 首行 (带宏, 选择弹窗名称列自行着色)
            self.assertEqual(recs[0]['name'], '\x02\x0e金烏劍')
            # 说明: 完整多行 (与 shop_editor 弹窗数据一致, 供分段着色/tooltip)
            self.assertEqual(recs[0]['desc'], '\x02\x14攻擊上升。\x01\x01\n使用後消失。')

            # 旧签名兼容: 不传 tkt_full 回退截断版
            recs2 = load_tkitem_records(str(tkitem_path), tkt_first)
            self.assertEqual(recs2[0]['desc'], tkt_first.get(101, ''))

    def test_missing_tkitem_returns_empty(self):
        self.assertEqual(load_tkitem_records('', {}), [])
        self.assertEqual(load_tkitem_records(str(Path('Z:/nope/TKItem.dat')), {}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
