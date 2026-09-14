"""工具提示 (QToolTip) 的两个系统性缺陷 —— 回归测试。

背景 (2026-09-14, 用户实测反馈):

1. **方形 HWND 底色**: QSS 给 `QToolTip` 设了 border-radius, 但 Qt 的 tooltip
   是原生方形窗口 (`QTipLabel`), 圆角只是"在方形窗口里画了个圆角描边",
   四角仍露出窗口底色 → 看上去就是"提示框带一圈矩形背景"。
   项目早已有 `_round_popup_win11_corners` (Win11 DWM 系统圆角裁剪), 但全局
   过滤器只匹配 `Qt.Popup`, 而 **`QToolTip` 的 windowType() 是 `Qt.ToolTip`
   (=13 = Popup|Sheet), 不等于 `Qt.Popup`(=9)** → 工具提示被漏掉。

2. **换行阈值随屏幕变化**: Qt 只在文本宽度超过"屏幕宽度的一定比例"时才软换行
   (实测 800px 屏约 496px)。于是中等长度的说明在宽屏上是一条横贯屏幕的宽条,
   更长的文本反而会换行 —— 同一列表里两款补丁的表现不一致。
   修法: 用 `wrap_tooltip_text` 按固定像素宽度预换行。

运行: python -m unittest tests.test_tooltip_popup -v
"""
import os

# 必须在任何 PySide6 导入之前设置离屏平台, 避免测试期间弹出真实窗口
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from editor_utils import ui_helpers  # noqa: E402


def _app():
    app = QApplication.instance() or QApplication([])
    # 模块级强引用: 防止 QApplication 被回收导致控件析构崩溃
    _app.instance = app  # type: ignore[attr-defined]
    return app


class PopupCornerTests(unittest.TestCase):
    """DWM 系统圆角必须同时覆盖 Qt.Popup 与 Qt.ToolTip。"""

    def setUp(self):
        self.app = _app()
        self.calls = []
        self._orig = ui_helpers._round_popup_win11_corners
        ui_helpers._round_popup_win11_corners = self.calls.append
        self.filter = ui_helpers._DialogThemeFilter(self.app)
        self.app.installEventFilter(self.filter)
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.app.removeEventFilter(self.filter)
        ui_helpers._round_popup_win11_corners = self._orig

    def _show(self, flags):
        w = QLabel("提示")
        w.setWindowFlags(flags)
        w.show()
        self.app.processEvents()
        self.addCleanup(w.close)
        return w

    def test_qt_tooltip_window_type_is_not_qt_popup(self):
        """固化前提: 这正是当初漏判的原因 (类型值不同, 不能只判 == Popup)。"""
        self.assertNotEqual(int(Qt.WindowType.ToolTip), int(Qt.WindowType.Popup))
        self.assertEqual(int(Qt.WindowType.ToolTip), 13)
        self.assertEqual(int(Qt.WindowType.Popup), 9)

    def test_tooltip_window_gets_dwm_rounding(self):
        w = self._show(Qt.WindowType.ToolTip)
        # ToolTip 的 DWM 设值是延迟一拍做的 (Qt 会在 Show 处理中把它设回
        # ROUNDSMALL), 所以要让事件循环再跑一拍
        self.app.processEvents()
        self.app.processEvents()
        self.assertIn(w, self.calls,
                      "Qt.ToolTip 窗口必须走 DWM 圆角 (否则四角露方形底色)")

    def test_popup_window_still_gets_dwm_rounding(self):
        w = self._show(Qt.WindowType.Popup)
        self.assertIn(w, self.calls, "既有 Qt.Popup 行为不得回退")

    def test_ordinary_window_not_treated_as_popup(self):
        w = self._show(Qt.WindowType.Window)
        self.assertNotIn(w, self.calls,
                         "普通窗口不应被设为弹层圆角 (走标题栏主题分支)")


class TooltipWrapTests(unittest.TestCase):
    """长说明必须被预换行成固定阅读宽度。"""

    def setUp(self):
        self.app = _app()

    def _max_line_px(self, text: str) -> int:
        fm = QFontMetrics(self.app.font())
        return max((fm.horizontalAdvance(ln) for ln in text.split("\n")), default=0)

    def test_long_text_is_wrapped(self):
        desc = ("16:9 宽屏改造: 地图/战场画布由 640x480 拓宽到 856x480, "
                "只加宽横向可视范围, 画面保持像素比例不拉伸; "
                "菜单/存档等页面仍按 640 布局居中并补两侧黑边。"
                "镜头跟随、鼠标光标、文字与 UI 锚点、小游戏贴图全链适配。") * 3
        out = ui_helpers.wrap_tooltip_text(desc, max_px=480)
        self.assertGreater(out.count("\n"), 1, "超长说明必须换行")
        self.assertLessEqual(self._max_line_px(out), 480 + 1,
                             "每行不得超过目标宽度")
        self.assertEqual(out.replace("\n", ""), desc, "只允许插入换行, 不得改动内容")

    def test_paragraphs_preserved(self):
        out = ui_helpers.wrap_tooltip_text("第一段\n\n第二段", max_px=480)
        self.assertEqual(out, "第一段\n\n第二段")

    def test_short_and_empty_text_untouched(self):
        self.assertEqual(ui_helpers.wrap_tooltip_text("短说明"), "短说明")
        self.assertEqual(ui_helpers.wrap_tooltip_text(""), "")

    def test_launcher_patch_tooltip_is_wrapped(self):
        """端到端: 启动器补丁表里最长的说明必须已换行。"""
        launcher = _ROOT / "tks_launcher_gui"
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        if str(launcher) not in sys.path:
            sys.path.insert(0, str(launcher))
        from core.tkspatch_loader import load_patch_directory
        from ui.patch_list import PatchListWidget

        patches = list(load_patch_directory(
            str(launcher / "patches"), log_func=lambda *_a: None).patches)
        w = PatchListWidget(patches, initial_states={})
        try:
            worst = None
            for row in range(w._table.rowCount()):
                item = w._table.item(row, 1)
                if item is None:
                    continue
                desc = item.toolTip().split("\n\n")[0]
                if worst is None or len(desc) > len(worst):
                    worst = desc
            self.assertIsNotNone(worst)
            self.assertGreater(worst.count("\n"), 0,
                               f"最长说明未换行, 会拉成横贯屏幕的宽条: {worst[:60]}...")
            self.assertLessEqual(self._max_line_px(worst), 480 + 1)
        finally:
            w.close()
            w.deleteLater()


if __name__ == "__main__":
    unittest.main()
