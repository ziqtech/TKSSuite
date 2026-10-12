"""warpc_editor 记录级操作回归: 新增/复制/粘贴/清除/删除 + 列表右键菜单。

对齐 kon_editor / skill_editor 的交互语义:
  · 复制=存入内部剪贴板, 粘贴=覆盖目标角色 (草稿层, 「应用修改」提交);
  · 原版角色 (前 WARPC_ORIG_COUNT 条) 不可删除, 只能清除;
  · 删除扩展角色后记录序号前移, 扩展学习/效果矩阵同步前移;
  · 列表右键菜单: 行上=复制/粘贴/清除/删除(条件启用), 空白处=新增角色。

同时锁死扩展学习矩阵的行长度修复: 新增/导入角色时旧代码用
``bytes * skill_count`` 构造整行, 与矩阵 stride (固定容量) 不等长,
``with_actor_learn_bytes`` 直接抛 SkillExtensionFormatError, 角色加不进去。

运行: python -m unittest tests.test_warpc_record_ops -v
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editor_utils.skill_extension import (  # noqa: E402
    GAME_SKILL_BASE,
    SparseSkillOverride,
    SkillExtension,
    create_original_game_extension,
)


def _load_warpc_editor():
    file_path = ROOT / "warpc_editor" / "warpc_editor.py"
    editor_dir = str(file_path.parent)
    if editor_dir not in sys.path:
        sys.path.insert(0, editor_dir)
    spec = importlib.util.spec_from_file_location(
        "_test_warpc_record_ops", file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WARPC = _load_warpc_editor()
WarpcEditorV2 = WARPC.WarpcEditorV2

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _extension(skill_count=5):
    """与编辑器加载路径同形的扩展矩阵 (固定 500 角色容量)。"""
    return create_original_game_extension(
        actor_count=WARPC.GAME_ACTOR_CAPACITY,
        skill_count=skill_count, apply_defaults=False)


def _make_editor(record_count=WARPC.WARPC_ORIG_COUNT):
    """构造离屏编辑器: 注入 record_count 条最小记录 + 同步草稿层。"""
    window = WarpcEditorV2()
    window.records = [
        {'index': i, 'fields': [0] * WARPC.WARPC_FIELD_COUNT}
        for i in range(record_count)
    ]
    window._sync_draft_from_records()
    window._apply_filter()
    return window


def _close_editor(window):
    """静默关闭: 先丢弃待应用草稿与脏标记, 避免 closeEvent 弹模态框。"""
    window._sync_draft_from_records()
    window._dirty = False
    window.close()
    window.deleteLater()


class SkillExtensionRemoveActorTests(unittest.TestCase):
    """SkillExtension.remove_actor (删除角色时矩阵行前移)。"""

    def test_remove_actor_shifts_rows_and_overrides(self):
        ext = SkillExtension(
            actor_count=4, skill_base=GAME_SKILL_BASE, skill_count=2,
            learn=bytes([1, 2, 2, 3, 4, 5, 6, 7]),
            overrides=(
                SparseSkillOverride(actor_id=0, skill_id=350, tkkon_id=10),
                SparseSkillOverride(actor_id=1, skill_id=351, tkkon_id=11),
                SparseSkillOverride(actor_id=3, skill_id=350, tkkon_id=13),
            ))
        removed = ext.remove_actor(1)
        self.assertEqual(
            removed.learn, bytes([1, 2, 4, 5, 6, 7, 0, 0]),
            "被删行未移除或末行未清零")
        self.assertEqual(removed.actor_count, ext.actor_count)
        self.assertEqual(
            removed.overrides,
            (
                SparseSkillOverride(actor_id=0, skill_id=350, tkkon_id=10),
                SparseSkillOverride(actor_id=2, skill_id=350, tkkon_id=13),
            ),
            "被删角色的覆盖未丢弃, 或后续角色未前移")
        removed.validate()

    def test_remove_actor_out_of_range(self):
        ext = SkillExtension(
            actor_count=2, skill_base=GAME_SKILL_BASE, skill_count=2,
            learn=bytes(4))
        with self.assertRaises(Exception):
            ext.remove_actor(2)


class RecordOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.editor = _make_editor()
        # 弹窗一律自动确认, 并记录调用供断言
        self._questions = []
        self._orig_question = WARPC.themed_question
        WARPC.themed_question = (
            lambda *a, **k: self._questions.append(a[0]) or QMessageBox.Yes)
        self._infos = []
        self._orig_info = WARPC.QMessageBox.information
        WARPC.QMessageBox.information = (
            lambda *a, **k: self._infos.append(a) or QMessageBox.Ok)

    def tearDown(self):
        WARPC.themed_question = self._orig_question
        WARPC.QMessageBox.information = self._orig_info
        _close_editor(self.editor)

    # ── 新增 ──
    def test_add_new_fills_default_learn_row(self):
        """新增角色写入 stride 等长的默认学习行 (旧行为长度不匹配直接抛异常)。"""
        self.editor._skill_extension = \
            self.editor._draft_skill_extension = _extension()
        self.editor._add_new()
        self.assertEqual(len(self.editor.records), 144)
        ext = self.editor._draft_skill_extension
        self.assertEqual(ext.actor_count, WARPC.GAME_ACTOR_CAPACITY)
        row = ext.actor_learn_bytes(143)
        self.assertEqual(
            row[:ext.skill_count], bytes([1]) * ext.skill_count,
            "新增角色的已注册技能列应填默认等待学状态 1")
        self.assertEqual(
            row[ext.skill_count:], bytes(ext.stride - ext.skill_count),
            "容量富余列应保持 0")

    def test_add_new_without_extension(self):
        self.editor._add_new()
        self.assertEqual(len(self.editor.records), 144)
        self.assertEqual(
            self.editor.records[143]['fields'],
            self.editor._blank_actor_fields())

    def test_add_new_without_records_prompts(self):
        editor = _make_editor(record_count=0)
        try:
            editor._add_new()
            self.assertEqual(len(editor.records), 0)
            self.assertEqual(len(self._infos), 1, "空数据新增应有提示")
        finally:
            _close_editor(editor)

    # ── 复制/粘贴 ──
    def test_copy_paste_roundtrip_including_extension(self):
        editor = self.editor
        editor._skill_extension = editor._draft_skill_extension = _extension()
        editor.records[0]['fields'][2] = 77
        editor._sync_draft_from_records()
        editor._draft_skill_extension = (
            editor._draft_skill_extension
            .with_learn_state(0, 351, 9)
            .with_overrides([(0, 350, 123)]))

        editor._copy_record(0)
        self.assertIsNotNone(editor._clipboard)

        # 粘贴到空白角色: 不应弹确认框
        editor._paste_record(1)
        self.assertEqual(
            editor._draft_records[1]['fields'],
            editor._draft_records[0]['fields'])
        ext = editor._draft_skill_extension
        self.assertEqual(ext.actor_learn_bytes(1), ext.actor_learn_bytes(0))
        self.assertEqual(
            [(e.skill_id, e.tkkon_id) for e in ext.overrides
             if e.actor_id == 1],
            [(350, 123)], "覆盖未随粘贴转移到目标角色")

    def test_paste_onto_filled_record_confirms(self):
        editor = self.editor
        editor.records[0]['fields'][2] = 77
        editor._sync_draft_from_records()
        editor._copy_record(0)
        editor._paste_record(1)   # #1 全零 != 模板 → 需确认
        self.assertEqual(len(self._questions), 1)

    def test_paste_without_clipboard_is_noop(self):
        editor = self.editor
        editor._paste_record(0)
        self.assertEqual(len(self._questions), 0)
        self.assertEqual(
            editor._draft_records[0]['fields'],
            editor.records[0]['fields'])

    # ── 清除 ──
    def test_clear_record_resets_to_template(self):
        editor = self.editor
        editor._skill_extension = editor._draft_skill_extension = _extension()
        editor.records[5]['fields'][2] = 40
        editor._sync_draft_from_records()
        editor._draft_skill_extension = (
            editor._draft_skill_extension
            .with_learn_state(5, 350, 9)
            .with_overrides([(5, 350, 7)]))

        editor._clear_record(5)
        blank = editor._blank_actor_fields()
        self.assertEqual(editor._draft_records[5]['fields'], blank)
        self.assertNotEqual(editor.records[5]['fields'], blank,
                            "清除应停留在草稿层, 不直接改已应用值")
        ext = editor._draft_skill_extension
        self.assertEqual(ext.actor_learn_bytes(5), bytes(ext.stride))
        self.assertEqual(
            [e for e in ext.overrides if e.actor_id == 5], [])

    def test_clear_blank_record_prompts_nothing(self):
        editor = self.editor
        editor._draft_records[0]['fields'] = list(editor._blank_actor_fields())
        editor._clear_record(0)
        self.assertEqual(len(self._questions), 0, "空白角色清除不应弹确认")
        self.assertEqual(len(self._infos), 1, "空白角色清除应有已为空提示")

    # ── 删除 ──
    def test_delete_original_record_refused(self):
        editor = self.editor
        count = len(editor.records)
        editor._delete_record(5)
        self.assertEqual(len(editor.records), count)
        self.assertEqual(len(self._infos), 1)

    def test_delete_extended_record_shifts_everything(self):
        editor = _make_editor(record_count=145)
        try:
            editor._skill_extension = editor._draft_skill_extension = \
                _extension()
            editor._draft_skill_extension = (
                editor._draft_skill_extension
                .with_learn_state(144, 350, 9)
                .with_overrides([(144, 351, 99)]))
            # 草稿守卫: 模拟用户在"未应用修改"三选框里点「应用修改」
            editor._prompt_unapplied = lambda: QMessageBox.Apply
            editor._delete_record(143)
            self.assertEqual(len(editor.records), 144)
            self.assertEqual(
                [r['index'] for r in editor.records], list(range(144)))
            self.assertEqual(len(editor._draft_records), 144)
            ext = editor._draft_skill_extension
            # 原 #144 的扩展数据前移到 #143
            self.assertEqual(ext.learn_state(143, 350), 9)
            self.assertEqual(
                [(e.skill_id, e.tkkon_id) for e in ext.overrides
                 if e.actor_id == 143], [(351, 99)])
            self.assertEqual(editor._dirty, True)
        finally:
            _close_editor(editor)

    # ── 复制为新增 / 上移下移 ──
    def test_duplicate_record_copies_extension_row(self):
        editor = self.editor
        editor._skill_extension = editor._draft_skill_extension = _extension()
        editor.records[0]['fields'][2] = 77
        editor._sync_draft_from_records()
        editor._editing_idx = 0
        editor._duplicate_record()
        self.assertEqual(len(editor.records), 144)
        ext = editor._draft_skill_extension
        self.assertEqual(
            ext.actor_learn_bytes(143), ext.actor_learn_bytes(0))

    def test_move_record_shifts_extension_row(self):
        editor = _make_editor(record_count=145)
        try:
            editor._skill_extension = editor._draft_skill_extension = \
                _extension()
            editor._draft_skill_extension = (
                editor._draft_skill_extension.with_learn_state(143, 350, 9))
            editor._apply_filter()
            row = next(
                r for r in range(editor.table.rowCount())
                if editor.table.item(r, 0).text() == "143")
            editor.table.selectRow(row)
            self.app.processEvents()
            editor._move_record(1)
            self.assertEqual(
                editor._draft_skill_extension.learn_state(144, 350), 9,
                "扩展行数据未随角色交换下移")
            self.assertEqual(len(editor.records), 145)
        finally:
            _close_editor(editor)

    # ── 右键菜单 ──
    def test_context_menu_actions_and_enablement(self):
        editor = self.editor
        editor._copy_record(0)
        menu = editor._build_table_context_menu(0)
        try:
            actions = [(a.text(), a.isEnabled()) for a in menu.actions()
                       if a.text()]
            by_text = dict(actions)
            self.assertEqual(
                [t for t, _ in actions],
                ["复制", "粘贴", "清除", "删除", "复制为新增角色"])
            self.assertTrue(by_text["复制"])
            self.assertTrue(by_text["粘贴"], "已有剪贴板时粘贴应可用")
            self.assertFalse(by_text["删除"], "原版角色删除应禁用")
        finally:
            menu.close()
            menu.deleteLater()

        menu_ext = editor._build_table_context_menu(WARPC.WARPC_ORIG_COUNT)
        try:
            by_text = {a.text(): a.isEnabled() for a in menu_ext.actions()
                       if a.text()}
            self.assertTrue(by_text["删除"], "扩展角色删除应可用")
        finally:
            menu_ext.close()
            menu_ext.deleteLater()

    def test_context_menu_without_clipboard_disables_paste(self):
        editor = self.editor
        self.assertIsNone(editor._clipboard)
        menu = editor._build_table_context_menu(0)
        try:
            by_text = {a.text(): a.isEnabled() for a in menu.actions()
                       if a.text()}
            self.assertFalse(by_text["粘贴"])
        finally:
            menu.close()
            menu.deleteLater()

    def test_table_has_custom_context_menu_policy(self):
        from PySide6.QtCore import Qt
        self.assertEqual(
            self.editor.table.contextMenuPolicy(),
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.assertTrue(callable(self.editor._on_table_context_menu))


if __name__ == '__main__':
    unittest.main()
