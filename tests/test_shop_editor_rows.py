"""shop_editor 扩展物品、追加记录和行级剪贴板回归测试。"""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from shop_editor.shop_editor import (  # noqa: E402
    ItemPickerDialog, ShopEditorWindow, load_shop_data,
    load_tkitem_with_tkt, save_shop_data,
)


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class ShopEditorRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_item_picker_loads_records_beyond_600(self):
        with tempfile.TemporaryDirectory() as td:
            raw = bytearray(601 * 64)
            for i in range(601):
                struct.pack_into('<h', raw, i * 64, i + 1)
                struct.pack_into('<h', raw, i * 64 + 2, 1)
            path = Path(td) / "TKItem.dat"
            path.write_bytes(lzss_compress_dat(bytes(raw)))

            items = load_tkitem_with_tkt(str(path), "")
            self.assertEqual(len(items), 601)
            self.assertEqual(items[-1][0], 600)
            self.assertEqual(items[-1][1], 601)

            rows = [{
                'index': idx, 'item_id': item_id, 'tab_code': tab_code,
                'name': name, 'equip_type': equip_type, 'icon': icon,
                'price': price, 'desc': desc,
            } for idx, item_id, tab_code, _nid, equip_type,
                   name, icon, price, desc in items]
            dlg = ItemPickerDialog(None, rows, return_key='index')
            try:
                # 无 TKT 时全部为 Item# 占位名, 关闭"仅非空"后扩展记录可见
                dlg._nonempty_cb.setChecked(False)
                self.app.processEvents()
                self.assertEqual(dlg._table.rowCount(), 601)
                self.assertEqual(dlg._table.item(600, 1).text(), "600")
            finally:
                dlg.close()
                dlg.deleteLater()

    def test_item_picker_nonempty_filter_hides_placeholders(self):
        """默认"仅非空"须与 item_editor.is_empty_item 一致:
        隐藏 id=0/1 与 Item#/物品# 占位记录, 保留有效物品。"""
        def _row(idx, item_id, name):
            return {'index': idx, 'item_id': item_id, 'tab_code': 0,
                    'name': name, 'equip_type': 0, 'icon': 0,
                    'price': 0, 'desc': ''}

        rows = [
            _row(0, 1, 'Item#1'),    # id=1 游戏占位记录
            _row(1, 0, '(空-1)'),    # 真空槽
            _row(2, 5, 'Item#5'),    # TKT 缺名占位名
            _row(3, 6, '物品#6'),    # warpc/save 风格占位名
            _row(4, 7, '金创药'),     # 有效物品
        ]
        dlg = ItemPickerDialog(None, rows, return_key='index')
        try:
            self.assertTrue(dlg._nonempty_cb.isChecked())
            self.assertEqual(dlg._table.rowCount(), 1)
            self.assertEqual(dlg._table.item(0, 4).text(), '金创药')

            dlg._nonempty_cb.setChecked(False)
            self.app.processEvents()
            self.assertEqual(dlg._table.rowCount(), 5)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_shop_save_load_preserves_expanded_rows(self):
        records = [{
            'index': i, 'area_id': i % 5, 'item_ref': i,
            'condition': 0, 'display': 0, 'reserved': 0,
        } for i in range(241)]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKShop.dat"
            save_shop_data(str(path), records)
            loaded = load_shop_data(str(path))
            self.assertEqual(len(loaded), 241)
            self.assertEqual(loaded[-1]['index'], 240)
            self.assertEqual(loaded[-1]['item_ref'], 240)

    def test_add_copy_paste_delete_row_operations(self):
        window = ShopEditorWindow()
        try:
            window.records = [window._make_empty_record(i) for i in range(240)]
            window.records[0].update({
                'area_id': 3, 'item_ref': 123, 'condition': -100,
                'display': 1, 'reserved': 2,
            })
            window._apply_filter()

            window._add_record()
            self.assertEqual(len(window.records), 241)
            self.assertEqual(window.records[-1], window._make_empty_record(240))
            self.assertEqual(window._editing_idx, 240)

            window._copy_row(0)
            window._paste_row(1)
            self.assertEqual(window.records[1]['index'], 1)
            for key in ('area_id', 'item_ref', 'condition', 'display', 'reserved'):
                self.assertEqual(window.records[1][key], window.records[0][key])

            with patch("shop_editor.shop_editor.themed_question",
                       return_value=QMessageBox.Yes):
                window._delete_row(1)
            self.assertEqual(window.records[1], window._make_empty_record(1))
        finally:
            window._dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
