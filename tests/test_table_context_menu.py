"""表格右键菜单 (复制单元格/所选行/整表 + 导出 CSV): 默认关闭。

背景 (2026-09-14, 用户反馈): 启动器里两个表格的右键菜单出现了
"复制单元格 / 复制所选行 / 导出所选行为 CSV / 复制整表 / 导出整表为 CSV"。
它们来自**共用控件** `editor_utils.adaptive_table.AdaptiveTableWidget` ——
该控件的构造函数历史上无条件调用 `enable_copy_menu()`; 启动器只是展示型表格,
复用同一控件, 于是也被带上。

修法 (按用户要求"默认关闭"): 构造函数改成 `copy_menu=False` 默认值 —— 想要该能力
的表格必须显式声明, 不做任何默认施加。启动器两张表不传参数, 因此没有菜单;
其余消费方同样按默认值走 (需要时由调用方自行传 `copy_menu=True`)。

本文件锁死三件事:
① 默认值确实是"关";
② 显式传 `copy_menu=True` 时该能力仍然可用 (没被写死);
③ 启动器两张表没有该菜单 (含真实右键事件不触发)。

运行: python -m unittest tests.test_table_context_menu -v
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER = _ROOT / "tks_launcher_gui"
for _p in (str(_ROOT), str(_LAUNCHER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editor_utils.adaptive_table import AdaptiveTableWidget  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from ui.mod_list import ModListWidget  # noqa: E402
from ui.patch_list import PatchListWidget  # noqa: E402

_APP = None


def _qt_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class TableContextMenuTests(unittest.TestCase):
    def setUp(self):
        self.app = _qt_app()

    def test_default_is_off(self):
        """默认关闭 —— 这是 2026-09-14 用户明确要求的默认值。"""
        t = AdaptiveTableWidget(1, 2)
        self.assertNotEqual(t.contextMenuPolicy(),
                            Qt.ContextMenuPolicy.CustomContextMenu)

    def test_flag_enables_copy_menu(self):
        """想用就显式打开 (编辑器数据表都这么做)。"""
        t = AdaptiveTableWidget(1, 2, copy_menu=True)
        self.assertEqual(t.contextMenuPolicy(),
                         Qt.ContextMenuPolicy.CustomContextMenu)

    def test_launcher_patch_table_has_no_copy_menu(self):
        patches = list(load_patch_directory(str(_LAUNCHER / "patches"),
                                            log_func=lambda *_a: None).patches)
        w = PatchListWidget(patches, initial_states={})
        try:
            self.assertEqual(w._table.objectName(), "LauncherPatchTable")
            self.assertNotEqual(w._table.contextMenuPolicy(),
                                Qt.ContextMenuPolicy.CustomContextMenu)
            self.assertEqual(self._right_click_calls(w._table), 0,
                             "启动器补丁表右键不应弹出复制/导出菜单")
        finally:
            w.close()
            w.deleteLater()

    def test_launcher_mod_table_has_no_copy_menu(self):
        w = ModListWidget(str(_LAUNCHER / "mods"), initial_states={})
        try:
            self.assertEqual(w._table.objectName(), "LauncherModTable")
            self.assertNotEqual(w._table.contextMenuPolicy(),
                                Qt.ContextMenuPolicy.CustomContextMenu)
            self.assertEqual(self._right_click_calls(w._table), 0,
                             "启动器模组表右键不应弹出复制/导出菜单")
        finally:
            w.close()
            w.deleteLater()

    def test_editor_table_still_reacts_to_right_click(self):
        """对照组: 显式开启的表格右键确实会走复制菜单处理 (证明上面的 0 有意义)。"""
        t = AdaptiveTableWidget(1, 2, copy_menu=True)
        t.show()
        try:
            self.assertGreaterEqual(self._right_click_calls(t), 1)
        finally:
            t.close()
            t.deleteLater()

    def test_launcher_call_sites_do_not_opt_in(self):
        """启动器侧不得出现 copy_menu=True (它只要默认的关闭行为)。"""
        launcher = _LAUNCHER / "ui"
        offenders = []
        for path in sorted(launcher.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            if "copy_menu=True" in src:
                offenders.append(str(path.relative_to(_ROOT)))
        self.assertEqual(offenders, [], f"启动器表格不应开启复制/导出菜单: {offenders}")

    def _right_click_calls(self, table) -> int:
        """给表格发真实右键事件, 统计复制菜单处理函数被调用次数。"""
        calls = []
        orig = AdaptiveTableWidget._show_copy_menu
        AdaptiveTableWidget._show_copy_menu = lambda self, pos: calls.append(pos)
        try:
            pos = table.rect().center()
            ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos,
                                   table.mapToGlobal(pos))
            QApplication.sendEvent(table.viewport(), ev)
            self.app.processEvents()
        finally:
            AdaptiveTableWidget._show_copy_menu = orig
        return len(calls)


if __name__ == "__main__":
    unittest.main()
