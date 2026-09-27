"""各编辑器 TKItem.dat 加载回归测试 — 按实际记录数加载, 扩展物品 (超过原版
600 条) 不再被截断, 与 shop_editor 的物品选择器行为一致。"""
import importlib.util
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

_APP = None

NAME_ID = 9001
TKT = {NAME_ID: "扩展物品九"}


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _load_module(rel_path: str, mod_name: str):
    """按"脚本运行"路径约定加载编辑器模块 (同 tests/test_editor_smoke.py)。"""
    file_path = ROOT / rel_path
    editor_dir = str(file_path.parent)
    if editor_dir not in sys.path:
        sys.path.insert(0, editor_dir)
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _write_expanded_tkitem(td: Path, n_records: int = 601) -> Path:
    """生成 n_records 条 TKItem.dat: 开头三条 + 末条 (index=n_records-1) 为
    有效物品 (item_id≥2 且带 name_id), 其余为全零空槽。"""
    raw = bytearray(n_records * 64)
    for i, item_id in ((0, 2), (1, 3), (2, 4), (n_records - 1, n_records)):
        struct.pack_into('<h', raw, i * 64, item_id)
        struct.pack_into('<h', raw, i * 64 + 4, NAME_ID)
    path = td / "TKItem.dat"
    path.write_bytes(lzss_compress_dat(bytes(raw)))
    return path


class WardataItemRecordsTests(unittest.TestCase):
    """wardata_editor.load_tkitem_records — 宝物选择弹窗数据源。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.mod = _load_module("wardata_editor/wardata_editor.py",
                               "_test_wardata_editor")

    def test_loads_records_beyond_600(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_expanded_tkitem(Path(td))
            records = self.mod.load_tkitem_records(str(path), TKT)
            # 空槽/占位记录在加载时被跳过, 仅有效物品保留
            self.assertEqual(len(records), 4)
            last = records[-1]
            self.assertEqual(last['index'], 600)
            self.assertEqual(last['item_id'], 601)
            self.assertEqual(last['name'], "扩展物品九")


class SaveEditorItemRecordsTests(unittest.TestCase):
    """save_editor._parse_item_dat — 新增物品选择弹窗 + 背包名称显示数据源。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.mod = _load_module("save_editor/save_editor.py", "_test_save_editor")

    def _make_window(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No), \
             patch.object(QMessageBox, "information", return_value=None), \
             patch.object(QMessageBox, "warning", return_value=None), \
             patch.object(QMessageBox, "critical", return_value=None):
            return self.mod.SaveEditorApp()

    def test_parses_records_beyond_600(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_expanded_tkitem(Path(td))
            window = self._make_window()
            try:
                window.tkt = dict(TKT)
                records, names = window._parse_item_dat(str(path))
                self.assertEqual(len(records), 601)
                self.assertEqual(records[600]['item_id'], 601)
                self.assertEqual(records[600]['name'], "扩展物品九")
                self.assertEqual(names.get(601), "扩展物品九")
            finally:
                window._dirty = False
                window.close()
                window.deleteLater()
                self.app.processEvents()


class TksBookLoadItemsTests(unittest.TestCase):
    """tks_book.book_loader.load_items — 查看器物品页签/装备显示数据源。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.mod = _load_module("tks_book/book_loader.py", "_test_book_loader")

    def test_loads_records_beyond_600(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_expanded_tkitem(Path(td))
            recs = self.mod.load_items(str(path))
            self.assertEqual(len(recs), 601)
            self.assertEqual(recs[-1]['index'], 600)
            self.assertEqual(recs[-1]['vals'][0], 601)


if __name__ == "__main__":
    unittest.main(verbosity=2)
