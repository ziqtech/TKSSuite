# -*- coding: utf-8 -*-
"""左表"类型"列的中文映射覆盖度。

历史问题: `ui/patch_list.py` 的 `_TYPE_LABELS` 只覆盖了早期几种 type, 新类型
(fixed_layout_cave / patch_sites / patch_data_expand) 全部回退成英文内部名,
在启动器左侧表格里显示 `fixed_layout_cave` 这类下划线名, 与其它行的中文不一致。

回归防线: 这里断言"加载出来的每一种 type 都有中文标签", 并把真实控件建起来
逐行检查类型列不是 ASCII —— 以后再加新 type 忘了补标签会直接失败。
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tks_launcher_gui") not in sys.path:
    sys.path.insert(0, str(ROOT / "tks_launcher_gui"))

from core.tkspatch_loader import load_patch_directory          # noqa: E402
from ui.patch_list import PatchListWidget, _COL_TYPE, _TYPE_LABELS  # noqa: E402


def _load_patches():
    cfg = load_patch_directory(str(ROOT / "tks_launcher_gui" / "patches"),
                               log_func=lambda *_a: None)
    return list(cfg.patches)


def _is_ascii_word(s: str) -> bool:
    """下划线英文内部名 (如 fixed_layout_cave) 判定 —— 纯 ASCII 且含字母。"""
    return s.isascii() and any(c.isalpha() for c in s)


_APP = None       # 模块级强引用: 防止 QApplication 被回收导致控件析构崩溃


def _qt_app():
    global _APP
    from PySide6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


class PatchTypeLabelTests(unittest.TestCase):
    def test_every_loaded_type_has_label(self):
        patches = _load_patches()
        self.assertGreater(len(patches), 0)
        types = sorted({p.type for p in patches})
        missing = [t for t in types if t not in _TYPE_LABELS]
        self.assertEqual(missing, [],
                         f"这些 type 没有中文标签 (左表会显示英文): {missing}")
        for t in types:
            label = _TYPE_LABELS[t]
            self.assertTrue(label.strip(), f"{t} 的标签为空")
            self.assertFalse(_is_ascii_word(label),
                             f"{t} 的中文标签仍是英文: {label!r}")

    def test_all_engine_dispatched_types_covered(self):
        """patch_engine 实际分发的 type 必须全部有标签 (含当前补丁目录未用到的)。"""
        for t in ("cave_hook", "patch_bytes", "patch_imm32", "patch_data_expand",
                  "patch_sites", "fixed_layout_cave", "patch_exp_lock",
                  "patch_summon_table", "patch_drop_probability",
                  "patch_font_config", "patch_animation_speed",
                  "patch_extra_section", "script"):
            self.assertIn(t, _TYPE_LABELS, f"{t} 缺少中文标签")

    def test_type_column_renders_chinese(self):
        _qt_app()
        patches = _load_patches()
        widget = PatchListWidget(patches, initial_states={})
        try:
            table = widget._table
            self.assertEqual(table.rowCount(), len(patches))
            leaks = []
            for row in range(table.rowCount()):
                patch = widget._row_patch.get(row)
                self.assertIsNotNone(patch, f"第 {row} 行未绑定补丁")
                item = table.item(row, _COL_TYPE)
                self.assertIsNotNone(item, f"第 {row} 行类型列缺失")
                if _is_ascii_word(item.text()):
                    leaks.append((patch.id, item.text()))
            self.assertEqual(leaks, [], f"类型列仍显示英文内部名: {leaks}")
        finally:
            # 只销毁控件: 不 processEvents() (会触发已销毁控件的延迟布局回调)
            widget.close()
            widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
