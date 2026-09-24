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

    def test_reload_of_blank_protected_slots_stays_clean(self):
        """受保护槽已是空白形态时不算冲突: 加载后不得凭空置脏."""
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        # 编辑器自己保存过的文件: 344..349 是 blank_skill_record 形态
        # (sub_count=-1, 其余字段为 0), 并非真的被技能数据占用
        records = [self._make_record(i) for i in range(350)]
        for index in range(344, 350):
            records[index] = blank_skill_record(index)
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
                self.assertFalse(editor._dirty)
                self.assertNotIn(
                    "已强制清空扩展字段冲突槽", editor.status_var.text())
                self.assertEqual(editor.records[344]["sub_count"], -1)
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

    def test_edit_menu_contains_list_operations(self):
        from PySide6.QtWidgets import QApplication, QMenu

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        try:
            edit_menu = next(
                menu for menu in editor.findChildren(QMenu)
                if menu.title() == "编辑(E)"
            )
            texts = [action.text() for action in edit_menu.actions()]
            for label in (
                    "复制当前记录",
                    "粘贴到当前记录",
                    "清除当前记录",
                    "删除当前记录"):
                self.assertIn(label, texts)
        finally:
            editor.close()
            app.processEvents()

    def test_skill_context_menu_contains_row_operations(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        editor = SkillEditorApp()
        try:
            editor.records = [self._make_record(i) for i in range(351)]
            editor.tkt = {}
            actions = editor._build_table_context_menu(350).actions()
            self.assertEqual(
                [action.text() for action in actions[:4]],
                ["复制", "粘贴", "清除", "删除"],
            )
            self.assertFalse(actions[1].isEnabled())
            self.assertTrue(actions[3].isEnabled())
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_clipboard_paste_overwrites_target_and_preserves_index(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        try:
            source = self._make_record(0)
            source["jp_cost"] = 9
            source["ref_skill0"] = 2
            editor.records = [source, self._make_record(1)]
            editor.tkt = {}
            editor._editing_idx = 0

            editor._copy_record()
            with mock.patch.object(
                    skill_module, "themed_question",
                    return_value=QMessageBox.Yes):
                editor._clipboard_paste(1)

            target = editor.records[1]
            self.assertEqual(target["index"], 1)
            self.assertEqual(target["jp_cost"], 9)
            self.assertEqual(target["ref_skill0"], 2)
            self.assertTrue(editor._dirty)
            self.assertEqual(editor._undo_stack[-1][1], 1)
        finally:
            editor._dirty = False
            editor.close()
            app.processEvents()

    def test_delete_rejects_original_and_removes_extension(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import skill_editor.skill_editor as skill_module

        app = QApplication.instance() or QApplication([])
        editor = skill_module.SkillEditorApp()
        try:
            editor.records = [self._make_record(i) for i in range(352)]
            editor.tkt = {}
            editor._editing_idx = 100

            with mock.patch.object(
                    skill_module.QMessageBox, "information",
                    return_value=QMessageBox.Ok) as information:
                editor._delete_record()

            information.assert_called_once()
            self.assertEqual(len(editor.records), 352)

            editor._editing_idx = 350
            with mock.patch.object(
                    skill_module, "themed_question",
                    return_value=QMessageBox.Yes):
                editor._delete_record()

            self.assertEqual(len(editor.records), 351)
            self.assertEqual(editor.records[350]["index"], 350)
            self.assertEqual(editor.records[350]["skill_text_id"], 352)
            self.assertTrue(editor._dirty)
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

class SkillEditorFieldSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.enterContext(mock.patch.object(SkillEditorApp, "_save_window_layout"))
        self.editor = SkillEditorApp()
        self.record = blank_skill_record(0)
        self.record["skill_text_id"] = 1
        self.editor.records = [self.record]
        self.editor._populate_edit(self.record)

    def tearDown(self):
        self.editor._dirty = False
        self.editor.close()
        self.editor.deleteLater()
        self.app.processEvents()

    def test_settlement_choices_keep_explicit_numeric_values(self):
        expected = {-1: "普通攻击", 0: "物理技能", 1: "法术技能", 10: "召唤术"}
        combo = self.editor.widget_map["atk_type"]
        self.assertEqual(combo.count(), len(expected))
        for value, label in expected.items():
            with self.subTest(value=value):
                self.record["atk_type"] = value
                self.editor._populate_edit(self.record)
                self.assertEqual(combo.currentText(), f"{value}-{label}")
                self.assertEqual(combo.currentData(), value)
                self.editor._apply_edit()
                self.assertEqual(self.record["atk_type"], value)

    def test_unknown_enums_survive_apply_and_binary_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "TKSkill.dat")
            for value in (-32768, -2, 255, 256, 266, 32767):
                with self.subTest(value=value):
                    self.record.update(type=value, atk_type=value)
                    self.editor._populate_edit(self.record)
                    for key in ("type", "atk_type"):
                        combo = self.editor.widget_map[key]
                        self.assertEqual(combo.currentText(), f"{value}-未知")
                        self.assertEqual(combo.currentData(), value)
                        # 显示文案可以改变，回写必须依赖数值data。
                        combo.setItemText(combo.currentIndex(), f"未知原值 {value}")
                    self.editor._apply_edit()
                    self.assertEqual(self.record["type"], value)
                    self.assertEqual(self.record["atk_type"], value)
                    save_skills(path, self.editor.records)
                    self.assertEqual(load_skills(path), self.editor.records)

    def test_type_names_filter_and_preview_agree(self):
        from PySide6.QtWidgets import QLabel

        expected = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
        self.editor.records = []
        for value in expected:
            rec = blank_skill_record(value)
            rec.update(type=value, skill_text_id=value + 1)
            self.editor.records.append(rec)
        for value, label in expected.items():
            with self.subTest(value=value):
                self.editor._populate_edit(self.editor.records[value])
                self.editor.type_filter.setCurrentIndex(value + 1)
                self.assertEqual(self.editor.type_filter.currentText(), f"{value}-{label}")
                self.assertEqual(self.editor.filtered_indices, [value])
                self.assertEqual(self.editor.table.item(0, 2).text(), label)
                self.assertEqual(self.editor.widget_map["type"].currentText(), f"{value}-{label}")
                self.assertIn(label, self.editor.preview_type.text())
        titles = [label.text() for label in self.editor.findChildren(QLabel)
                  if label.property("class") == "InspectorTitle"]
        self.assertIn("效果加成 (主动／移动技能)", titles)
        self.assertFalse(any("属性技能" in title or "反应技能" in title or "免疫" in title
                             for title in titles))
        self.editor._populate_edit(self.editor.records[1])
        self.assertIn("不代表战斗菜单中可主动施放", self.editor.preview_type.text())
        self.editor._populate_edit(self.editor.records[2])
        self.assertIn("303..330", self.editor.preview_type.text())
        self.assertIn("不会自动生成", self.editor.preview_type.text())

    def test_skill_tree_dialog_accepts_theme_id(self):
        from skill_editor.skill_editor import SkillTreeDialog

        for theme_id in ("gpt-dark", "gpt-light", "classic-dark", "classic-light"):
            with self.subTest(theme_id=theme_id):
                rec = blank_skill_record(0)
                rec["skill_text_id"] = 1
                dialog = SkillTreeDialog(None, [rec], {1: "测试技能"}, 0, theme_id)
                try:
                    self.assertEqual(dialog.theme_id, theme_id)
                    self.assertEqual(dialog.view.theme_id, theme_id)
                    self.assertIn("grid_dot", dialog._pal)
                    self.assertIn("grid_dot", dialog.view._pal)
                finally:
                    dialog.close()
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_weight_20_edge_label_uses_plain_language(self):
        from skill_editor.skill_editor import SkillTreeDialog

        self.assertEqual(
            SkillTreeDialog._weight_label(20),
            "归组",
        )
        self.assertEqual(SkillTreeDialog._weight_label(10), "自足")
        self.assertEqual(SkillTreeDialog._weight_label(0x105), "+5")
        self.assertEqual(SkillTreeDialog._weight_label(5), "+5")

    def test_description_uses_independent_tkt_id_without_name_fallback(self):
        self.editor.tkt = {1: "技能名称"}
        self.editor.tkt_full = {401: "不能使用的名称推算说明", 900: "独立说明\n第二行"}
        for did, expected in ((900, "独立说明\n第二行"),
                              (0, "暂无关于该技能的详细描述。"),
                              (999, "暂无关于该技能的详细描述。")):
            with self.subTest(did=did):
                self.record["skill_desc_id"] = did
                self.editor._populate_edit(self.record)
                self.assertEqual(self.editor.preview_desc.text(), expected)
                self.assertIn(f"说明文本ID={did}", self.editor.preview_desc.toolTip())
                self.assertIn("独立", self.editor.widget_map["skill_desc_id"].toolTip())
                self.assertEqual(self.editor.preview_name.text(), "技能名称")

    def test_description_picker_and_apply_refresh_independent_preview(self):
        from PySide6.QtWidgets import QDialog
        import skill_editor.skill_editor as skill_module

        self.editor.tkt = {1: "技能名称", 900: "选择说明", 901: "手填说明"}
        self.editor.tkt_full = dict(self.editor.tkt)
        picker = SimpleNamespace(exec=lambda: QDialog.Accepted, selected_id=900)
        with mock.patch.object(skill_module, "TktPickerDialog", return_value=picker):
            self.editor._pick_tkt("skill_desc_id")
        self.assertEqual(self.editor.preview_desc.text(), "选择说明")
        self.editor.widget_map["skill_desc_id"].setText("901")
        self.editor._apply_edit()
        self.assertEqual(self.editor.preview_desc.text(), "手填说明")
        self.assertIn("901", self.editor.preview_desc.toolTip())
        self.assertEqual(self.record["skill_text_id"], 1)

    def test_sub_count_preview_distinguishes_group_direct_and_marker(self):
        for count, expected in ((-1, "不能作为顶层独立指令"),
                                (0, "直接技能"), (2, "ID 1 - 2"),
                                (13, "学习状态≥20"), (-2, "未知值 -2")):
            with self.subTest(count=count):
                self.record["sub_count"] = count
                self.editor._populate_edit(self.record)
                self.assertIn(expected, self.editor.preview_sub.text())
                if count <= 0:
                    self.assertNotIn("ID ", self.editor.preview_sub.text())
                self.editor._apply_edit()
                self.assertEqual(self.record["sub_count"], count)
        self.assertEqual(blank_skill_record(0)["sub_count"], -1)
        self.editor.widget_map["sub_count"].setText("0")
        self.editor._apply_edit()
        self.assertIn("直接技能", self.editor.preview_sub.text())

    def test_field_labels_and_hints_match_verified_engine_semantics(self):
        fields = {key: (offset, label, hint) for key, offset, label, _, hint in ALL_FIELDS}
        expected_labels = {
            "move_up": (60, "移动增加"), "atk_count": (62, "普攻次数增加"),
            "immunity1": (68, "状态抗性1–16"), "immunity2": (70, "状态抗性17–32"),
            "magic_def": (76, "术法类伤害减免%"), "turn_shift": (84, "目标时序系数"),
            "trigger_prob": (88, "触发概率"),
            "sub_count": (90, "子技能数量"), "atk_type": (92, "攻击类型"),
        }
        for key, expected in expected_labels.items():
            self.assertEqual(fields[key][:2], expected)
        expected_hints = {
            "jp_cost": ("250 -", "/ 200"), "hp_pct": ("生命上限",),
            "mp_pct": ("内力上限",), "heal_move": ("曼哈顿距离", "生命上限"),
            "mp_move": ("曼哈顿距离", "内力上限"), "move_up": ("1=+1", "2=+2"),
            "atk_count": ("次数为1", "1=二连", "2=三连", "技能/反应限制"),
            "trigger_prob": ("低字节", "50/75/100", "100禁止附加", "完整WORD", "依原版反应编号"),
            "turn_shift": ("260 - 目标速度", "负数：本值 × 目标速度", "实际伤害"),
            "atk_type": ("低字节+1", "0/1/2/11", "距离由TKKon", "0x04", "222", "224..231", "251", "不保证能召唤"),
            "magic_def": ("HP/MP", ">=2", "物品例外"),
            "cost_gold": ("原版", "不限于"),
            "cost_res2": ("原版技能执行消耗的兽元", "不限于"),
            "cost_res3": ("原版技能执行消耗的灵魂", "不限于"),
        }
        for key in ("atk_pct", "def_pct", "hit_pct", "eva_pct", "spd_pct"):
            expected_hints[key] = ("相对基础", "百分比")
        for index in range(8):
            expected_hints[f"ref_type{index}"] = ("1..9", "低字节", "源技能学习状态设为30")
        for key, fragments in expected_hints.items():
            with self.subTest(key=key):
                for fragment in fragments:
                    self.assertIn(fragment, self.editor.widget_map[key].toolTip())

    def test_special_flags_preserve_unknown_bits_when_toggling_or_clearing(self):
        from PySide6.QtWidgets import QCheckBox, QDialog, QPushButton

        for clear in (False, True):
            with self.subTest(clear=clear):
                self.record["special_flags"] = 0xC5A9 - 0x10000
                self.editor._populate_edit(self.record)

                def confirm(dlg):
                    boxes = dlg.findChildren(QCheckBox)
                    self.assertEqual([box.text() for box in boxes], [
                        "飘浮 (避开陷阱)", "飙行 (额外移动机会)",
                        "搜宝 (检查沿途宝物)", "解陷 (处理沿途陷阱)"])
                    if clear:
                        next(btn for btn in dlg.findChildren(QPushButton)
                             if btn.text() == "清除已知标志").click()
                    else:
                        boxes[0].setChecked(False)
                        boxes[1].setChecked(True)
                    next(btn for btn in dlg.findChildren(QPushButton)
                         if btn.text() == "确定").click()
                    return QDialog.Accepted

                with mock.patch.object(QDialog, "exec", confirm):
                    self.editor._pick_flags("special_flags")
                self.editor._apply_edit()
                expected = 0xC5A0 if clear else 0xC5AA
                self.assertEqual(self.record["special_flags"] & 0xFFFF, expected)
                self.assertIn("未知位 0xC5A0", self.editor.extra_map["special_flags"].text())

    def test_status_masks_show_and_preserve_unknown_sixteenth_bits(self):
        from PySide6.QtWidgets import QDialog, QPushButton
        import skill_editor.skill_editor as skill_module

        for key, last in (("immunity1", 16), ("immunity2", 32)):
            for high in (0, 0x8000):
                for action in ("toggle", "clear", "all"):
                    with self.subTest(key=key, high=high, action=action):
                        self.record[key] = 1 if high == 0 else -32767
                        self.editor._populate_edit(self.record)

                        def confirm(dlg):
                            self.assertIn("状态抗性", dlg.windowTitle())
                            self.assertEqual(len(dlg.checkboxes), 16)
                            boxes = dict(dlg.checkboxes)
                            self.assertEqual(boxes[15].text(), f"{last}. 未知状态位 {last}")
                            self.assertEqual(boxes[15].isChecked(), bool(high))
                            self.assertFalse(boxes[15].isEnabled())
                            if action == "toggle":
                                boxes[1].setChecked(True)
                            else:
                                dlg._set_all_checked(action == "all")
                            self.assertEqual(boxes[15].isChecked(), bool(high))
                            dlg._ok()
                            return QDialog.Accepted

                        with mock.patch.object(skill_module.StatusPickerDialog, "exec", confirm):
                            self.editor._pick_status(key)
                        self.editor._apply_edit()
                        low = {"toggle": 3, "clear": 0, "all": 0x7FFF}[action]
                        self.assertEqual(self.record[key] & 0xFFFF, high | low)
                        preview = self.editor.extra_map[key]
                        self.assertIn("抗性状态", preview.text())
                        if high:
                            self.assertIn(f"未知状态位 {last}", preview.text())
                        self.assertIn("100禁止附加", preview.toolTip())
        buttons = self.editor.findChildren(QPushButton, "StatusPickerButton")
        self.assertEqual([btn.text() for btn in buttons], ["配置状态抗性"] * 2)

    def test_reference_preview_counts_low_byte_without_mutating_records(self):
        from skill_editor.skill_editor import SkillTreeDialog

        records = [blank_skill_record(i) for i in range(3)]
        for rec in records:
            rec["skill_text_id"] = rec["index"] + 1
        records[0].update(ref_skill0=2, ref_type0=0x105)
        records[1].update(ref_skill0=2, ref_type0=20)
        graph = SimpleNamespace(records=records, tkt_dict={})
        graph._seed_role = lambda idx: SkillTreeDialog._seed_role(graph, idx)
        SkillTreeDialog._build_graph(graph)
        self.assertEqual(graph.total_in[2], 25)
        tooltip = SkillTreeDialog._node_tooltip(graph, 2)
        self.assertIn("1..9", tooltip)
        self.assertIn("源技能自动学会", tooltip)
        self.assertIn("+5 (原值261)", tooltip)
        self.assertEqual(records[0]["ref_type0"], 0x105)
        self.assertEqual(records[1]["ref_type0"], 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
