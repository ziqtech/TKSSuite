import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel

from wardata_editor.wardata_editor import (
    WarDataEditorV2, build_record_bytes, load_wardata,
)
from kon_editor import kon_editor as kon


class WarDataFieldSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_enemy_facing_labels_and_round_trip(self):
        self.enterContext(patch.object(WarDataEditorV2, "_save_window_layout"))
        editor = WarDataEditorV2()
        try:
            self.assertEqual(editor.enemy_table.horizontalHeaderItem(9).text(), "朝向")
            self.assertIn("朝向", editor.ap_enemy_table.horizontalHeaderItem(7).text())
            self.assertIn("0=随机", editor.enemy_table.horizontalHeaderItem(9).toolTip())
            raw = bytearray(498)
            raw[196] = 5
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "WarData.dat"
                path.write_bytes(raw)
                record = load_wardata(str(path))[0]
            self.assertEqual(build_record_bytes(record), raw)
            editor.records = [record]
            editor._current_idx = 0
            editor._populate_enemy_tab(record)
            self.assertEqual(record["enemy_delay"][6], 5)
            editor.enemy_table.item(6, 9).setText("3")
            self.assertEqual(editor.ap_enemy_table.item(6, 7).text(), "3")
            editor._apply_enemy_tab(record)
            raw[196] = 3
            self.assertEqual(build_record_bytes(record), raw)
        finally:
            editor._dirty = False
            editor.close()
            self.app.processEvents()


class KonFieldSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.enterContext(patch.object(kon.KonEditor, "_save_window_layout"))
        self.editor = kon.KonEditor()
        self.addCleanup(self.close_editor)
        self.record = {name: 0 for name, _, _, _ in kon.KON_FIELDS}
        self.record["index"] = 0
        self.editor.records = [self.record]
        self.editor._editing_idx = 0

    def close_editor(self):
        self.editor._dirty = False
        self.editor.close()
        self.app.processEvents()

    def test_damage_encoding_boundaries_and_percentage_bases(self):
        for value, expected in ((1000, "固定基础值=1000"),
                                (2000, "目标当前生命×1000%"),
                                (3000, "攻击力+1000"),
                                (3100, "攻击力×200%")):
            with self.subTest(value=value):
                self.assertEqual(kon.describe_hp_damage(value), expected)
        self.assertEqual(kon.describe_resource_val(1000, "内力伤害", "目标当前内力"),
                         "固定内力伤害=1000")
        self.record.update(mp_damage=2010, hp_restore=2010, mp_restore=2010)
        self.editor._populate_edit(self.record)
        self.assertIn("目标当前内力×1010%", self.editor.preview_desc.text())
        self.assertIn("目标生命上限×1010%", self.editor.preview_desc.text())
        self.assertIn("目标内力上限×1010%", self.editor.preview_desc.text())

    def test_signed_area_and_disabled_expansion_descriptions(self):
        self.assertEqual(kon.describe_exec_mode(-256), "自身中心，免选点")
        self.assertEqual(kon.describe_target_param(-768), "全场目标")
        self.assertEqual(kon.describe_target_param(-512), "全场（排除目标中心）")
        self.assertIn("仅中心", kon.describe_target_param(0x0207))
        self.assertIn("范围关闭", kon.describe_exec_mode(0x037F))
        self.record.update(target_param=-512, tkact_id=-1)
        self.editor._populate_edit(self.record)
        self.assertEqual(self.editor.split_map["target_param"][0].text(), "-2")
        self.assertIn("继承普攻动画", self.editor.preview_name.text())
        self.assertNotIn("排除自身", self.editor.preview_desc.text())

    def test_apply_without_changes_preserves_all_record_bits(self):
        self.record.update(exec_mode=0x037F, target_param=-384,
                           target_filter=-21555, exec_flags=-32506,
                           inflict_status_lo=-32768, inflict_status_hi=-32768,
                           remove_status_lo=-32768, remove_status_hi=-32768,
                           unused14=17, unused15=19, unused18=-25)
        original = dict(self.record)
        self.editor._populate_edit(self.record)
        self.editor._apply_edit()
        self.assertEqual(self.record, original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "TKKon.dat"
            kon.save_kon(str(path), [self.record])
            self.assertEqual(kon.load_kon(str(path)), [original])

    def test_changing_known_flag_or_range_preserves_other_bits(self):
        self.record.update(exec_mode=0x037F, exec_flags=-32506)
        self.editor._populate_edit(self.record)
        self.editor.split_map["exec_mode"][0].setText("4")
        self.editor.split_map["exec_flags"][2].setChecked(False)
        self.editor._apply_edit()
        self.assertEqual(self.record["exec_mode"], 0x047F)
        self.assertEqual(self.record["exec_flags"], -32510)

    def test_high_status_bits_are_visible_and_preserved_by_picker(self):
        self.record.update(inflict_status_lo=-32768, inflict_status_hi=-32768)
        self.editor._populate_edit(self.record)
        for key, absolute_bit in (("inflict_status_lo", 15), ("inflict_status_hi", 31)):
            with self.subTest(field=key):
                labels = [label.text() for label in self.editor.extra_map[key].findChildren(QLabel)]
                self.assertTrue(any(f"{absolute_bit}." in label for label in labels))
                def accept(dialog):
                    # 空值槽位 (状态16/32) 已从弹窗移除, 仅剩 15 个有效复选框
                    self.assertEqual(len(dialog.checkboxes), 15)
                    self.assertNotIn(15, dict(dialog.checkboxes))
                    dialog._ok()
                    return QDialog.Accepted
                with patch.object(kon.StatusPickerDialog, "exec", accept):
                    self.editor._pick_status(key)
                self.assertEqual(self.editor.widget_map[key].text(), "-32768")
        self.editor._apply_edit()
        self.assertEqual(self.record["inflict_status_lo"], -32768)
        self.assertEqual(self.record["inflict_status_hi"], -32768)

    def test_zero_animation_and_status_effect_are_not_empty(self):
        self.record.update(tkact_id=0, inflict_status_lo=1, exec_flags=3)
        self.editor._populate_edit(self.record)
        self.editor._apply_filter()
        self.assertIn("动画#0", self.editor.preview_name.text())
        self.assertIn("施加=破兵", self.editor.preview_desc.text())
        self.assertIn("待机/特效绘制", self.editor.preview_type.text())
        self.assertIn("当前物品结算", self.editor.preview_type.text())
        self.assertNotIn("Buff/自身", self.editor.preview_type.text())
        self.assertNotIn("法术攻击", self.editor.preview_type.text())
        # 列表 5 列 (选点/作用范围/执行标志仅在右侧编辑面板展示);
        # tkact_id=0 的非空记录不被按空记录过滤, 行正常出现在列表
        self.assertEqual(self.editor.table.columnCount(), 5)
        self.assertEqual(self.editor.table.item(0, 1).text(), "0")


if __name__ == "__main__":
    unittest.main()
