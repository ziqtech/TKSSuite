import tempfile
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from skill_editor.skill_editor import (
    ALL_FIELDS,
    SKILL_REC,
    SkillEditorApp,
    blank_skill_record,
    load_skills,
    save_skills,
)
from editor_utils.skill_extension import (
    create_original_game_extension,
    parse_skill_extension,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SkillEditorDynamicTests(unittest.TestCase):
    def _make_record(self, index):
        record = {"index": index}
        for key, _, _, _, _ in ALL_FIELDS:
            record[key] = 0
        record["skill_text_id"] = index + 1
        record["type"] = 1
        record["sub_count"] = -1
        record["atk_type"] = -1
        return record

    def test_load_save_does_not_truncate_extended_skills(self):
        records = [self._make_record(i) for i in range(351)]
        records[350]["skill_text_id"] = 9350

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            save_skills(str(path), records)
            loaded = load_skills(str(path))

        self.assertEqual(len(loaded), 351)
        self.assertEqual(loaded[350]["index"], 350)
        self.assertEqual(loaded[350]["skill_text_id"], 9350)
        self.assertEqual(351 * SKILL_REC, 32994)

    def test_new_skill_apply_falls_back_when_combo_has_no_selection(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        try:
            record = self._make_record(0)
            record["skill_text_id"] = 1
            editor.records = [record]
            editor.filtered_indices = [0]
            editor._editing_idx = 0
            editor.tkt = {}
            editor.tkt_full = {}
            editor._populate_edit(record)

            editor._new_skill()
            editor.widget_map["type"].setCurrentIndex(-1)
            editor.widget_map["atk_type"].setCurrentIndex(-1)
            editor._apply_edit()

            self.assertEqual(len(editor.records), 351)
            self.assertEqual(editor.records[350]["index"], 350)
            self.assertEqual(editor.records[350]["type"], 1)
            self.assertEqual(editor.records[350]["atk_type"], -1)
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_save_creates_backup_and_writes_extended_records(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        records = [self._make_record(i) for i in range(351)]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            save_skills(str(path), records)
            editor.skill_path = str(path)
            editor.records = records
            editor._dirty = True
            try:
                with mock.patch.object(
                        skill_module, "themed_question",
                        return_value=QMessageBox.Yes), \
                     mock.patch.object(
                         skill_module.QMessageBox, "warning",
                         return_value=QMessageBox.Ok), \
                     mock.patch.object(
                         skill_module.QMessageBox, "information",
                         return_value=QMessageBox.Ok):
                    editor._save()

                self.assertTrue(Path(str(path) + ".bak").is_file())
                self.assertFalse(editor._dirty)
            finally:
                editor._dirty = False
                editor.close()
                app.processEvents()

    def test_new_skill_skips_protected_warpc_slots(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        records = [self._make_record(i) for i in range(350)]
        for index in range(345, 350):
            records[index]["skill_text_id"] = 0
        records[344]["skill_text_id"] = 0
        records[344]["type"] = 0
        editor.records = records
        editor.tkt = {}
        editor.tkt_full = {}
        try:
            editor._new_skill()

            self.assertEqual(len(editor.records), 351)
            self.assertEqual(editor.records[344]["skill_text_id"], 0)
            self.assertEqual(editor.records[349]["skill_text_id"], 0)
            self.assertEqual(editor.records[350]["index"], 350)
            self.assertEqual(editor.records[350]["skill_text_id"], 351)
            self.assertEqual(editor.records[350]["type"], 1)
            self.assertTrue(editor._dirty)
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_empty_slots_are_visible_in_all_types_view(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        try:
            valid = self._make_record(0)
            editor.records = [valid, blank_skill_record(1), blank_skill_record(2)]
            editor.tkt = {}
            editor.type_filter.setCurrentIndex(0)

            editor._apply_filter()

            self.assertEqual(editor.filtered_indices, [0, 1, 2])
            self.assertEqual(editor.table.rowCount(), 3)
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_protected_slots_are_cleared_before_save(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        records = [self._make_record(i) for i in range(350)]
        for index in range(345, 350):
            records[index]["skill_text_id"] = 0
        records[344]["skill_text_id"] = 0
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            save_skills(str(path), records)
            records[344]["skill_text_id"] = 345
            records[344]["type"] = 1
            editor.skill_path = str(path)
            editor.records = records
            editor._dirty = True
            try:
                with mock.patch.object(
                        skill_module, "themed_question",
                        return_value=QMessageBox.Yes), \
                     mock.patch.object(
                         skill_module.QMessageBox, "warning",
                         return_value=QMessageBox.Ok) as warning, \
                     mock.patch.object(
                         skill_module.QMessageBox, "information",
                         return_value=QMessageBox.Ok):
                    editor._save()

                warning.assert_not_called()
                loaded = load_skills(str(path))
                for index in range(344, 350):
                    self.assertEqual(loaded[index]["skill_text_id"], 0)
                    self.assertEqual(loaded[index]["type"], 0)
                self.assertFalse(editor._dirty)
                self.assertIn("已清空冲突槽", editor.status_var.text())
            finally:
                editor._dirty = False
                editor.close()
                app.processEvents()

    def test_reload_clears_protected_slots_and_marks_file_dirty(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        records = [self._make_record(i) for i in range(350)]
        records[344]["skill_text_id"] = 345
        records[344]["type"] = 1
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            save_skills(str(path), records)
            editor.skill_path = str(path)
            editor.tkt = {}
            editor.tkt_full = {}
            try:
                with mock.patch.object(
                        skill_module.QMessageBox, "warning",
                        return_value=QMessageBox.Ok) as warning:
                    editor._reload()

                warning.assert_not_called()
                self.assertEqual(editor.records[344]["skill_text_id"], 0)
                self.assertEqual(editor.records[344]["type"], 0)
                self.assertTrue(editor._dirty)
                self.assertIn("已强制清空扩展字段冲突槽", editor.status_var.text())
            finally:
                editor._dirty = False
                editor.close()
                app.processEvents()

    def test_protected_slot_cannot_be_applied_as_skill_data(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        records = [self._make_record(i) for i in range(350)]
        records[344]["skill_text_id"] = 0
        records[344]["type"] = 1
        editor.records = records
        editor._editing_idx = 344
        editor.tkt = {}
        editor.tkt_full = {}
        try:
            editor._populate_edit(records[344])
            editor.widget_map["skill_text_id"].setText("345")
            editor.widget_map["type"].setCurrentIndex(
                editor.widget_map["type"].findData(1))
            with mock.patch.object(
                    skill_module.QMessageBox, "warning",
                    return_value=QMessageBox.Ok) as warning:
                editor._apply_edit()

            warning.assert_not_called()
            self.assertEqual(records[344]["skill_text_id"], 0)
            self.assertEqual(records[344]["type"], 1)
            self.assertFalse(editor._dirty)
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_protected_rows_are_visibly_disabled(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from editor_utils.theme_tokens import business_colors

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        try:
            editor.records = [
                blank_skill_record(index) if index == 344
                else self._make_record(index)
                for index in range(350)
            ]
            editor.tkt = {}
            editor.type_filter.setCurrentIndex(0)

            editor._apply_filter()

            type_item = editor.table.item(344, 2)
            name_item = editor.table.item(344, 3)
            self.assertEqual(type_item.text(), "禁用")
            self.assertEqual(name_item.text(), "禁用")
            self.assertFalse(type_item.flags() & Qt.ItemIsEnabled)
            self.assertFalse(type_item.flags() & Qt.ItemIsSelectable)
            self.assertIn("战场图集索引", type_item.toolTip())
            disabled_color = business_colors(
                "launcher", editor._theme_id)["placeholder_gray"]
            for column in range(6):
                self.assertEqual(
                    editor.table.item(344, column).foreground().color().name(),
                    disabled_color,
                )
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_clicking_protected_row_does_not_show_message(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        try:
            editor.records = [blank_skill_record(i) for i in range(350)]
            editor.tkt = {}
            editor._apply_filter()
            editor.show()
            app.processEvents()

            with mock.patch.object(
                    skill_module.QMessageBox, "information",
                    return_value=QMessageBox.Ok) as information:
                rect = editor.table.visualItemRect(
                    editor.table.item(344, 0))
                QTest.mouseClick(
                    editor.table.viewport(), Qt.LeftButton,
                    pos=rect.center())
                app.processEvents()

            information.assert_not_called()
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_warpc_editor_loads_extended_skill_directory(self):
        root = Path(__file__).resolve().parents[1]
        warpc_dir = str(root / "warpc_editor")
        if warpc_dir not in sys.path:
            sys.path.insert(0, warpc_dir)
        import warpc_editor as warpc_module

        records = [self._make_record(i) for i in range(351)]
        records[350]["skill_text_id"] = 9350
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TKSkill.dat"
            save_skills(str(path), records)
            obj = SimpleNamespace(_get_tks_dir=lambda: td)
            names, types, _descs = \
                warpc_module.WarpcEditorV2._load_skill_names(obj, {})

        self.assertEqual(types.get(350), 1)
        self.assertEqual(names.get(350), "#9350")

    def test_warpc_editor_edits_extended_skill_state_matrix(self):
        from PySide6.QtWidgets import QApplication

        root = Path(__file__).resolve().parents[1]
        warpc_dir = str(root / "warpc_editor")
        if warpc_dir not in sys.path:
            sys.path.insert(0, warpc_dir)
        import warpc_editor as warpc_module

        app = QApplication.instance() or QApplication([])
        editor = warpc_module.WarpcEditorV2()
        try:
            titles = [editor.tabs.tabText(i)
                      for i in range(editor.tabs.count())]
            skill_pos = titles.index("技能学习")
            self.assertEqual(titles[skill_pos + 1], "技能效果判定")
            self.assertEqual(titles[skill_pos + 2], "附加技能")
            self.assertEqual(titles[skill_pos + 3], "附加技能效果判定")
            editor.records = [{
                'index': 0,
                'fields': [0] * warpc_module.WARPC_FIELD_COUNT,
            }]
            editor._draft_records = [{
                'index': 0,
                'fields': [0] * warpc_module.WARPC_FIELD_COUNT,
            }]
            editor.skill_names = {0: "原版技能", 350: "扩展技能350"}
            editor._skill_types = {0: 0, 350: 0}
            editor.tkkon_names = {584: "火球效果", 590: "默认扩展效果"}
            editor._save_mode = False
            editor._skill_extension = create_original_game_extension(
                actor_count=1, skill_count=1)
            editor._draft_skill_extension = editor._skill_extension
            editor._refresh_learn_toolbar_mode()
            editor._populate_extended_effect_grid()
            editor._editing_idx = 0
            editor._populate_edit(editor._draft_records[0])

            self.assertEqual(len(editor._ext_skill_learn_widgets), 1)
            widget = editor._ext_skill_learn_widgets[0][1]
            self.assertEqual(len(editor._ext_skill_effect_widgets), 1)
            effect_widget = editor._ext_skill_effect_widgets[0][1]
            self.assertEqual(effect_widget.text(), "590")
            editor._edit_snapshot = editor._capture_snapshot()
            editor._set_learn_widget_value(widget, 20)
            effect_widget.setText("32768")
            editor._flush_widgets_to_draft()
            self.assertIn(
                "TKKon 编号无效", editor._ext_effect_override_error)
            self.assertTrue(editor._validate_draft())
            effect_widget.setText("656")
            editor._flush_widgets_to_draft()
            self.assertIsNone(editor._ext_effect_override_error)
            self.assertEqual(
                editor._draft_skill_extension.learn_state(0, 350), 20)
            self.assertEqual(
                editor._draft_skill_extension.override_for(
                    0, 350).tkkon_id,
                656,
            )
            editor._commit_draft()
            self.assertEqual(
                editor._skill_extension.learn_state(0, 350), 20)
            self.assertEqual(
                editor._skill_extension.override_for(0, 350).tkkon_id,
                656,
            )
            parsed = parse_skill_extension(editor._skill_extension.to_bytes())
            self.assertEqual(parsed.override_for(0, 350).tkkon_id, 656)
            effect_widget.setText("590")
            editor._flush_widgets_to_draft()
            self.assertIsNone(
                editor._draft_skill_extension.override_for(0, 350))
            editor._commit_draft()
            self.assertIsNone(
                editor._skill_extension.override_for(0, 350))
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

if __name__ == "__main__":
    unittest.main(verbosity=2)
