"""warpc_editor 存档模式: 扩展技能页可用性 + 原版存档格式保持。

覆盖两件事:
  1. 附加技能 / 附加技能效果判定两页在存档模式可见 (原版存档只读);
  2. 保存时仅当原存档本就带 TKSX 扩展块才回写尾部 —— 原版存档保持原版格式,
     不会被编辑器静默升级成"附加存档"。
"""
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QMessageBox, QSpinBox,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EDITOR_DIR = ROOT / "warpc_editor"
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))

from editor_utils.lzss import (  # noqa: E402
    lzss_compress_save,
)
from editor_utils.skill_extension import (  # noqa: E402
    create_original_game_extension,
)


def _load_warpc_module():
    spec = importlib.util.spec_from_file_location(
        "_warpc_save_mode", EDITOR_DIR / "warpc_editor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_warpc_save_mode"] = module
    spec.loader.exec_module(module)
    return module


WARPC = _load_warpc_module()


def _make_save(path: Path, tail: bytes = b"", record_count: int = 1):
    """构造最小可加载存档: Frame1(任意压缩块) + Frame2 + 可选扩展尾部。"""
    frame1_block = b"\x11" * 64
    seg1 = bytes(WARPC.SAVE_SEG1_SIZE)
    seg2 = bytes(WARPC.SAVE_SEG2_SIZE)
    seg3 = bytes(WARPC.WARPC_REC * record_count)
    comp2 = lzss_compress_save(seg1 + seg2 + seg3)
    path.write_bytes(
        struct.pack("<I", len(frame1_block)) + frame1_block +
        struct.pack("<I", len(comp2)) + comp2 + tail)
    return seg1, seg2


class SaveExtensionTailTests(unittest.TestCase):
    def test_vanilla_save_keeps_vanilla_format(self):
        """原版存档 (无扩展块) 保存后仍是原版格式, 不追加附加存档数据。"""
        extension = create_original_game_extension(actor_count=1, skill_count=1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "1.sav"
            seg1, seg2 = _make_save(path)
            _, _, records, tail = WARPC.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(tail, b"")
            WARPC.save_warpc_to_save(
                str(path), seg1, seg2, records,
                extension_tail=WARPC.resolve_save_extension_tail(False, extension))
            _, _, records2, tail2 = WARPC.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(tail2, b"", "原版存档被追加了扩展块")
            self.assertEqual(len(records2), len(records))

    def test_extended_save_keeps_extension_tail(self):
        """附加存档 (带扩展块) 保存后仍带扩展块, 且内容回读一致。"""
        extension = create_original_game_extension(actor_count=1, skill_count=1)
        tail_bytes = extension.to_bytes()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "2.sav"
            seg1, seg2 = _make_save(path, tail=tail_bytes)
            _, _, records, tail = WARPC.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(tail, tail_bytes)
            WARPC.save_warpc_to_save(
                str(path), seg1, seg2, records,
                extension_tail=WARPC.resolve_save_extension_tail(True, extension))
            _, _, _, tail2 = WARPC.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(tail2, tail_bytes)

    def test_resolve_tail_only_writes_for_extended_saves(self):
        extension = create_original_game_extension(actor_count=1, skill_count=1)
        self.assertEqual(WARPC.resolve_save_extension_tail(False, extension), b"")
        self.assertEqual(WARPC.resolve_save_extension_tail(True, None), b"")
        self.assertEqual(WARPC.resolve_save_extension_tail(True, extension),
                         extension.to_bytes())


class SaveModeUiTests(unittest.TestCase):
    """离屏构造编辑器, 校验存档模式下两页可见性与只读策略。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for name in ("information", "warning", "critical"):
            setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.No)

    def setUp(self):
        self.win = WARPC.WarpcEditorV2()
        self.addCleanup(self.win.deleteLater)
        self.win._skill_extension = create_original_game_extension(
            actor_count=1, skill_count=1)
        self.win._draft_skill_extension = self.win._skill_extension
        self.win.skill_names = {}

    def _refresh(self, save_mode, has_extension):
        self.win._save_mode = save_mode
        self.win._save_has_extension = has_extension
        self.win._refresh_learn_toolbar_mode()

    def test_extended_tabs_visible_in_both_modes(self):
        for save_mode, has_ext in ((False, False), (True, False), (True, True)):
            with self.subTest(save_mode=save_mode, has_extension=has_ext):
                self._refresh(save_mode, has_ext)
                self.assertTrue(
                    self.win.tabs.isTabVisible(self.win._extra_skill_tab_index))
                self.assertTrue(
                    self.win.tabs.isTabVisible(self.win._extra_effect_tab_index))

    def test_vanilla_save_locks_extended_widgets(self):
        self._refresh(True, False)
        self.assertTrue(self.win._ext_skill_learn_widgets, "扩展学习控件未构建")
        for _skill_idx, widget in self.win._ext_skill_learn_widgets:
            self.assertIsInstance(widget, QSpinBox)
            self.assertTrue(widget.isReadOnly(), "原版存档的扩展学习状态应只读")
        self.assertTrue(self.win._ext_skill_effect_widgets, "扩展效果控件未构建")
        for _skill_idx, widget in self.win._ext_skill_effect_widgets:
            self.assertTrue(widget.isReadOnly(), "原版存档的效果覆盖应只读")

    def test_extended_save_allows_editing(self):
        self._refresh(True, True)
        self.assertTrue(self.win._ext_skill_learn_widgets)
        for _skill_idx, widget in self.win._ext_skill_learn_widgets:
            self.assertFalse(widget.isReadOnly(), "附加存档的扩展学习状态应可编辑")
        for _skill_idx, widget in self.win._ext_skill_effect_widgets:
            self.assertFalse(widget.isReadOnly(), "附加存档的效果覆盖应可编辑")

    def test_template_mode_widgets_stay_editable(self):
        self._refresh(False, False)
        self.assertTrue(self.win._ext_skill_learn_widgets)
        for _skill_idx, widget in self.win._ext_skill_learn_widgets:
            # 模板模式用带语义下拉框, 不做只读锁定
            self.assertIsInstance(widget, QComboBox)
        for _skill_idx, widget in self.win._ext_skill_effect_widgets:
            self.assertFalse(widget.isReadOnly())


if __name__ == "__main__":
    unittest.main(verbosity=2)
