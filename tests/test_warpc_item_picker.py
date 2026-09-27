"""warpc_editor 物品选择弹窗回归测试 — 装备物品可选到扩展物品 (超过原版 600 条)。"""
import importlib.util  # noqa: E402
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from editor_utils.picker_dialogs import ItemPickerDialog  # noqa: E402


def _load_warpc_editor():
    """按"脚本运行"路径约定加载 warpc_editor 模块
    (其内部 `from warpc_schema import *` 依赖编辑器自身目录在 path 上,
    与 tests/test_editor_smoke.py 的 _load_editor_module 一致)。"""
    file_path = ROOT / "warpc_editor" / "warpc_editor.py"
    editor_dir = str(file_path.parent)
    if editor_dir not in sys.path:
        sys.path.insert(0, editor_dir)
    spec = importlib.util.spec_from_file_location("_test_warpc_editor", file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WarpcEditorV2 = _load_warpc_editor().WarpcEditorV2

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class WarpcItemPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_item_records_load_beyond_600(self):
        """_load_item_names 按实际记录数加载, 扩展物品进入选择器与联动表。"""
        NAME_ID = 9001
        with tempfile.TemporaryDirectory() as td:
            # 601 条记录: 前三条带有效 item_id, 末条 (index=600) 模拟扩展物品
            raw = bytearray(601 * 64)
            for i in (0, 1, 2, 600):
                struct.pack_into('<h', raw, i * 64, i + 1)
            struct.pack_into('<h', raw, 600 * 64 + 4, NAME_ID)
            (Path(td) / "TKItem.dat").write_bytes(lzss_compress_dat(bytes(raw)))

            window = WarpcEditorV2()
            try:
                # _get_tks_dir 取 warpc_path 所在目录
                window.warpc_path = str(Path(td) / "WarPC.dat")
                window._load_item_names({NAME_ID: "扩展物品九"})

                self.assertEqual(len(window._item_records), 601)
                last = window._item_records[-1]
                self.assertEqual(last['index'], 600)
                self.assertEqual(last['item_id'], 601)
                self.assertEqual(last['name'], "扩展物品九")
                # equip_idx ↔ equip_id 联动表覆盖扩展物品 (经返回值交调用方赋值)
                id_names, idx_names, idx_to_id, id_to_idx = window._load_item_names(
                    {NAME_ID: "扩展物品九"})
                self.assertEqual(idx_to_id.get(600), 601)
                self.assertEqual(id_to_idx.get(601), 600)
                self.assertEqual(idx_names.get(600), "扩展物品九")
                self.assertEqual(id_names.get(601), "扩展物品九")

                # 装备物品弹窗以 _item_records 为数据源, 扩展物品可见可选
                dlg = ItemPickerDialog(None, window._item_records,
                                       return_key='index')
                try:
                    dlg._nonempty_cb.setChecked(False)
                    self.app.processEvents()
                    self.assertEqual(dlg._table.rowCount(), 601)
                    self.assertEqual(dlg._table.item(600, 1).text(), "600")
                finally:
                    dlg.close()
                    dlg.deleteLater()
            finally:
                window._dirty = False
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
