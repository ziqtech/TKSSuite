"""editor_utils.skill_table — TKSkill.dat 统一加载与各编辑器一致性。

重点覆盖:
  1. 记录/名称/类型/说明的解析规则 (含扩展技能 350..696);
  2. 全部调用方 (item / save / warpc / configs / kon / skill / tks_book)
     对同一份文件必须得到同一套名称, 不允许各编辑器再各写一套逻辑;
  3. 技能选择器行数据 (SkillPickerDialog) 能列出附加技能。
"""
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "item_editor", ROOT / "warpc_editor", ROOT / "save_editor",
           ROOT / "configs_editor", ROOT / "skill_editor", ROOT / "tks_book"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from editor_utils.skill_table import (  # noqa: E402
    DESC_ID_INDEX, SKILL_REC, SKILL_TYPES, SkillTable, load_skill_records,
    load_skill_table, load_skill_table_safe,
)

TOTAL = 351               # 350 原版 + 1 条附加技能 (索引 350)
EXTRA_INDEX = 350
EXTRA_TEXT_ID = 9350
EXTRA_DESC_ID = 9750


def _make_table_bytes(total=TOTAL):
    recs = bytearray()
    for i in range(total):
        r = bytearray(SKILL_REC)
        struct.pack_into('<h', r, 0, 1000 + i)      # 名称文本ID
        struct.pack_into('<h', r, 2, 5000 + i)      # 说明文本ID (独立字段)
        struct.pack_into('<h', r, 4, 0)             # 类型: 指令
        recs += r
    struct.pack_into('<h', recs, EXTRA_INDEX * SKILL_REC + 0, EXTRA_TEXT_ID)
    struct.pack_into('<h', recs, EXTRA_INDEX * SKILL_REC + 2, EXTRA_DESC_ID)
    struct.pack_into('<h', recs, EXTRA_INDEX * SKILL_REC + 4, 1)   # 主动
    return bytes(recs)


def _tkt():
    names = {1000 + i: f"技能{i}" for i in range(TOTAL)}
    names[EXTRA_TEXT_ID] = "附加技能示例"
    names[EXTRA_DESC_ID] = "附加技能说明示例"
    return names


def _write_table(directory: Path, raw: bool = False) -> Path:
    path = directory / "TKSkill.dat"
    data = _make_table_bytes()
    path.write_bytes(data if raw else lzss_compress_dat(data))
    return path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SkillTableCoreTests(unittest.TestCase):
    def test_reads_extended_records_with_names_types_descs(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_table(Path(td))
            table = load_skill_table(str(path), _tkt())
        self.assertEqual(len(table), TOTAL)
        self.assertEqual(table.names[EXTRA_INDEX], "附加技能示例")
        self.assertEqual(table.types[EXTRA_INDEX], 1)
        self.assertEqual(table.descs[EXTRA_INDEX], "附加技能说明示例")
        self.assertEqual(table.type_label(EXTRA_INDEX), SKILL_TYPES[1])

    def test_desc_comes_from_record_field_not_name_offset(self):
        """说明文本ID 是记录字段 [1], 不能按名称文本ID 推算。"""
        with tempfile.TemporaryDirectory() as td:
            path = _write_table(Path(td))
            table = load_skill_table(str(path), _tkt())
        self.assertEqual(table.descs[EXTRA_INDEX], "附加技能说明示例")

    def test_negative_text_id_and_fallbacks(self):
        records = [[-777, 0, 2]] + [[0, 0, 0]] + [[123456, 0, 3]]
        table = SkillTable(records, {-777: "负号文本"})
        self.assertEqual(table.names[0], "负号文本")
        self.assertEqual(table.names[1], "(空-#1)")
        self.assertEqual(table.names[2], "Skill#123456")

    def test_uncompressed_table_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_table(Path(td), raw=True)
            records = load_skill_records(str(path))
        self.assertEqual(len(records), TOTAL)

    def test_malformed_table_raises_and_safe_variant_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            path.write_bytes(b"\x00" * (SKILL_REC - 1))
            with self.assertRaises(ValueError):
                load_skill_records(str(path))
            self.assertIsNone(load_skill_table_safe(str(path), {}))
            self.assertIsNone(load_skill_table_safe(str(Path(td) / "missing.dat"), {}))

    def test_picker_rows_include_extended_skill(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_table(Path(td))
            table = load_skill_table(str(path), _tkt())
        rows = table.picker_rows()
        keys = [key for key, _cells, _tid in rows]
        self.assertIn(EXTRA_INDEX, keys)
        cells = next(c for k, c, _t in rows if k == EXTRA_INDEX)
        self.assertEqual(cells, (str(EXTRA_INDEX), SKILL_TYPES[1],
                                 "附加技能示例", "附加技能说明示例"))


class SkillTableConsumerConsistencyTests(unittest.TestCase):
    """同一份文件, 各编辑器的名称/类型必须一致 (统一实现, 不再各写一套)。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.path = _write_table(cls.dir)
        cls.tkt = _tkt()
        cls.ref = load_skill_table(str(cls.path), cls.tkt)
        cls.modules = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _module(self, key, rel_path):
        if key not in self.modules:
            self.modules[key] = _load_module(ROOT / rel_path, f"_skilltab_{key}")
        return self.modules[key]

    def test_item_editor_matches_shared_table(self):
        module = self._module("item", "item_editor/item_editor.py")
        names = module.load_tkskill_names(str(self.path), self.tkt)
        self.assertEqual(len(names), TOTAL)
        self.assertEqual(names[EXTRA_INDEX], self.ref.names[EXTRA_INDEX])

    def test_save_editor_matches_shared_table(self):
        module = self._module("save", "save_editor/save_editor.py")
        table = module.load_skill_table_safe(str(self.path), self.tkt)
        self.assertIsNotNone(table)
        self.assertEqual(len(table.names), TOTAL)
        self.assertEqual(table.names[EXTRA_INDEX], self.ref.names[EXTRA_INDEX])
        self.assertEqual(table.types[EXTRA_INDEX], self.ref.types[EXTRA_INDEX])

    def test_warpc_editor_matches_shared_table(self):
        module = self._module("warpc", "warpc_editor/warpc_editor.py")
        editor = module.WarpcEditorV2.__new__(module.WarpcEditorV2)
        editor._get_tks_dir = lambda: str(self.dir)
        table = editor._load_skill_table(self.tkt)
        names, types, descs = table.names, table.types, table.descs
        self.assertEqual(len(names), TOTAL)
        self.assertEqual(names[EXTRA_INDEX], self.ref.names[EXTRA_INDEX])
        self.assertEqual(types[EXTRA_INDEX], self.ref.types[EXTRA_INDEX])
        self.assertEqual(descs[EXTRA_INDEX], self.ref.descs[EXTRA_INDEX])

    def test_configs_editor_matches_shared_table(self):
        module = self._module("configs", "configs_editor/configs_editor.py")
        names = module.load_skill_names(str(self.path), self.tkt)
        self.assertEqual(len(names), TOTAL)
        self.assertEqual(names[EXTRA_INDEX], self.ref.names[EXTRA_INDEX])

    def test_kon_name_resolver_matches_shared_table(self):
        module = self._module("kon", "editor_utils/kon_name_resolver.py")
        resolver = module.KonNameResolver(str(self.dir))
        names, types = resolver._load_skill_data(str(self.dir), self.tkt)
        self.assertEqual(len(names), TOTAL)
        self.assertEqual(names[EXTRA_INDEX], self.ref.names[EXTRA_INDEX])
        self.assertEqual(types[EXTRA_INDEX], self.ref.types[EXTRA_INDEX])

    def test_skill_and_book_editors_load_all_records(self):
        skill_module = self._module("skill", "skill_editor/skill_editor.py")
        records = skill_module.load_skills(str(self.path))
        self.assertEqual(len(records), TOTAL)
        self.assertEqual(records[EXTRA_INDEX]["index"], EXTRA_INDEX)

        book_module = self._module("book", "tks_book/book_loader.py")
        book_records = book_module.load_skills(str(self.path))
        self.assertEqual(len(book_records), TOTAL)
        self.assertEqual(book_records[EXTRA_INDEX]["index"], EXTRA_INDEX)

    def test_no_editor_keeps_its_own_skill_table_parser(self):
        """防回归: 各编辑器不得再出现自建 TKSkill 解析循环/350 硬上限。"""
        sources = {
            "item_editor/item_editor.py": None,
            "save_editor/save_editor.py": None,
            "warpc_editor/warpc_editor.py": None,
            "configs_editor/configs_editor.py": None,
            "editor_utils/kon_name_resolver.py": None,
        }
        for rel in sources:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("range(min(350", text, rel)
            self.assertNotIn("range(350)", text, rel)
            self.assertNotIn("for i in range(len(dec) // SKILL_REC)", text, rel)


class SkillPickerDialogTests(unittest.TestCase):
    """选择器本体: 共享行数据可直接列出附加技能并支持类型筛选。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_and_filters_extended_skill(self):
        from editor_utils.picker_dialogs import SkillPickerDialog
        with tempfile.TemporaryDirectory() as td:
            path = _write_table(Path(td))
            table = load_skill_table(str(path), _tkt())
        dlg = SkillPickerDialog(
            None, table.picker_rows(), ("技能#", "类型", "名称", "技能说明"),
            type_filter=[(k, v) for k, v in sorted(SKILL_TYPES.items())])
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.table.rowCount(), TOTAL)
        dlg.search_box.setText(str(EXTRA_INDEX))
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg._row_keys[0], EXTRA_INDEX)
        dlg.search_box.setText("")
        dlg.type_box.setCurrentIndex(dlg.type_box.findData(1))   # 只看主动技能
        self.assertEqual(dlg._row_keys, [EXTRA_INDEX])


class SkillPickerWiringTests(unittest.TestCase):
    """选择器接线: 编辑器弹窗必须直接消费共享行数据 (含附加技能)。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication, QMessageBox
        cls.app = QApplication.instance() or QApplication([])
        for name in ("information", "warning", "critical"):
            setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.No)

    def test_item_editor_picker_rows_include_extended_skill(self):
        module = _load_module(ROOT / "item_editor" / "item_editor.py", "_skilltab_item_ui")
        captured = {}

        class _StubDialog:
            def __init__(self, parent, rows, headers, **kwargs):
                captured["rows"] = list(rows)
                captured["headers"] = headers

            def exec(self):
                return 0        # 直接取消, 不写回

        module.SkillPickerDialog = _StubDialog
        win = module.ItemEditorApp()
        self.addCleanup(win.deleteLater)
        with tempfile.TemporaryDirectory() as td:
            win._skill_table = load_skill_table(str(_write_table(Path(td))), _tkt())
        win.skill_names = win._skill_table.names
        win._pick_skill("attach_skill")
        keys = [key for key, _cells, _tid in captured["rows"]]
        self.assertIn(EXTRA_INDEX, keys)
        self.assertEqual(captured["headers"], ("技能#", "类型", "名称", "技能说明"))

    def test_save_editor_loads_skill_maps_for_embedded_panel(self):
        module = _load_module(ROOT / "save_editor" / "save_editor.py", "_skilltab_save_ui")
        win = module.SaveEditorApp()
        self.addCleanup(win.deleteLater)
        with tempfile.TemporaryDirectory() as td:
            game = Path(td) / "game"
            (game / "save").mkdir(parents=True)
            _write_table(game)
            win.tkt = _tkt()          # 临时目录无 TKT.dat, 直接注入文本表
            win.save_dir = str(game / "save")
            win._load_resources()
        # 内嵌武将面板注入依赖这两个属性 (修复前从未赋值 → AttributeError)
        self.assertEqual(win.skill_names.get(EXTRA_INDEX), "附加技能示例")
        self.assertEqual(win._skill_types.get(EXTRA_INDEX), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
