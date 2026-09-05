"""阶段 0 冒烟测试 —— 编辑器主题安全网。

目的（见 docs/PySide6样式体系整改方案.md 阶段 0）：
  1. 18 个 GUI 入口（16 编辑器 + tks_book + 启动器）的主窗口可在 offscreen
     模式下实例化、并对 4 个主题逐个执行 apply_theme_to_window 而不崩溃；
  2. 每个主题的 QSS 均可加载（非空）且真实应用到窗口；
  3. 颜色一致性断言（专治病灶 1）：
     QSS 中 QGraphicsView 的 background-color 必须与
     theme_manager.canvas_background() 一致；QPalette 必须与
     theme_manager._PALETTE_COLORS 一致。

运行方式（项目根目录）：
    python -m unittest tests.test_editor_smoke -v

已知事项：
  * 单实例锁/翻译器/图标安装属于 main() 样板，测试不经过 main()，不触发；
  * 构造期间的阻塞式弹窗被替换为自动应答（question→No，其余→None），
    防止 offscreen 下模态框挂死；
  * 某编辑器若因缺少本地数据文件无法构造，应在本文件的 _KNOWN_SKIP
    中登记并注明原因，不得静默放行。
"""
import os

# 必须在任何 PySide6 导入之前设置离屏平台，避免测试期间弹出真实窗口
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib  # noqa: E402
import importlib.util  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editor_utils import theme_manager  # noqa: E402
from editor_utils.theme_switcher import THEME_ATTR, apply_theme_to_window  # noqa: E402

# ── 入口清单：条目名 / 模块文件(相对根目录) / 窗口类名 ──────────────
# 启动器例外：走包导入 ui.main_window（其模块内以 tks_launcher_gui 为根
# 做 `from core... import` / `from ui... import`）。
_EDITOR_ENTRIES = [
    ("act_editor", "act_editor/act_editor.py", "ActEditorV2"),
    ("configs_editor", "configs_editor/configs_editor.py", "ConfigsEditorWindow"),
    ("font_editor", "font_editor/font_editor.py", "FontEditorWindow"),
    ("grp_editor", "grp_editor/grp_editor.py", "GRPEditor"),
    ("gxp_editor", "gxp_editor/gxp_editor.py", "GXPEditor"),
    ("item_editor", "item_editor/item_editor.py", "ItemEditorApp"),
    ("jvg_editor", "jvg_editor/jvg_editor.py", "JVGEditor"),
    ("kon_editor", "kon_editor/kon_editor.py", "KonEditor"),
    ("mat_editor", "mat_editor/mat_editor.py", "MatEditorApp"),
    ("save_editor", "save_editor/save_editor.py", "SaveEditorApp"),
    ("shop_editor", "shop_editor/shop_editor.py", "ShopEditorWindow"),
    ("skill_editor", "skill_editor/skill_editor.py", "SkillEditorApp"),
    ("spritesheet_editor", "spritesheet_editor/spritesheet_editor.py",
     "SpriteSheetEditorWindow"),
    ("tkt_editor", "tkt_editor/tkt_editor.py", "TktEditor"),
    ("wardata_editor", "wardata_editor/wardata_editor.py", "WarDataEditorV2"),
    ("warpc_editor", "warpc_editor/warpc_editor.py", "WarpcEditorV2"),
    ("tks_book", "tks_book/tks_book.py", "TksBookViewer"),
]

_LAUNCHER_ENTRY = ("tks_launcher_gui", None, "MainWindow")

# 因环境原因允许失败的条目：条目名 -> 原因（留空表示无豁免）
_KNOWN_SKIP: dict[str, str] = {}


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
    return app


def _load_editor_module(entry_name: str, rel_path: str):
    """按"脚本运行"的路径约定加载编辑器模块（根目录与编辑器目录均在 path 上）。"""
    file_path = _ROOT / rel_path
    editor_dir = str(file_path.parent)
    if editor_dir not in sys.path:
        sys.path.insert(0, editor_dir)
    mod_name = f"_smoke_{entry_name}"
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _load_launcher_module():
    launcher_dir = str(_ROOT / "tks_launcher_gui")
    if launcher_dir not in sys.path:
        sys.path.insert(0, launcher_dir)
    return importlib.import_module("ui.main_window")


def _make_window_factory():
    """返回 (构造函数, 条目名) 列表；模块导入失败就地抛出。"""
    factories = []
    for entry_name, rel_path, win_cls in _EDITOR_ENTRIES:
        module = _load_editor_module(entry_name, rel_path)
        factories.append((entry_name, getattr(module, win_cls)))
    launcher_mod = _load_launcher_module()
    factories.append((_LAUNCHER_ENTRY[0], getattr(launcher_mod, _LAUNCHER_ENTRY[2])))
    return factories


class _SilenceDialogs:
    """构造期间把阻塞式弹窗替换为自动应答，防止 offscreen 测试挂死。"""

    _METHODS = ("information", "warning", "critical", "question")

    def __enter__(self):
        self._saved = {}
        for name in self._METHODS:
            self._saved[name] = getattr(QMessageBox, name)
            if name == "question":
                answer = QMessageBox.StandardButton.No
                setattr(QMessageBox, name,
                        staticmethod(lambda *a, _r=answer, **k: _r))
            else:
                setattr(QMessageBox, name,
                        staticmethod(lambda *a, _r=None, **k: _r))
        return self

    def __exit__(self, *exc):
        for name, fn in self._saved.items():
            setattr(QMessageBox, name, fn)
        return False


class ThemeConsistencyTests(unittest.TestCase):
    """不依赖任何窗口的主题数据源一致性断言。"""

    def test_qss_loads_for_all_themes(self):
        for tid in theme_manager.THEME_ORDER:
            with self.subTest(theme=tid):
                qss = theme_manager.stylesheet(tid)
                self.assertTrue(
                    qss.strip(),
                    f"主题 {tid} 的 QSS 加载结果为空")
                self.assertNotIn(
                    "{{", qss,
                    f"主题 {tid} 的 QSS 存在未替换的模板槽位")

    def test_qss_canvas_background_matches_canvas_table(self):
        """QSS 的 QGraphicsView 底色必须与 canvas_background() 一致（病灶 1 检测）。"""
        for tid in theme_manager.THEME_ORDER:
            with self.subTest(theme=tid):
                qss = theme_manager.stylesheet(tid)
                block = re.search(r"QGraphicsView\s*\{[^}]*\}", qss)
                self.assertIsNotNone(
                    block, f"{tid}: QSS 中未找到 QGraphicsView 规则")
                bg = re.search(
                    r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})",
                    block.group(0))
                self.assertIsNotNone(
                    bg, f"{tid}: QGraphicsView 规则缺少 background-color")
                self.assertEqual(
                    bg.group(1).lower(),
                    theme_manager.canvas_background(tid).lower(),
                    f"{tid}: QSS 画布底色与 canvas_background() 不一致")

    def test_tab_pane_border_colors_are_parseable(self):
        """EditorTabPane 自绘边框色必须是 QColor 可解析的裸色值。

        bd_regular 槽位存的是完整 CSS 边框串 ("1px solid #xxx")，直接整串
        喂给 QColor 会静默退化成纯黑画笔 (2026-09-06 修复的 flat 标签页
        三边纯黑边框根因)，此处防回归。
        """
        from PySide6.QtGui import QColor

        from editor_utils.tab_widget import EditorTabPane
        for key, value in EditorTabPane._BORDER_COLORS.items():
            with self.subTest(border=key, value=value):
                self.assertTrue(
                    QColor(value).isValid(),
                    f"{key}: {value!r} 不是 QColor 可解析的颜色值")

    def test_palette_matches_definitions(self):
        """theme_manager.palette() 必须逐角色还原 theme_tokens.PALETTE 定义。"""
        from PySide6.QtGui import QPalette

        from editor_utils import theme_tokens
        from editor_utils.theme_manager import _PALETTE_ROLE_MAP
        for tid, colors in theme_tokens.PALETTE.items():
            pal = theme_manager.palette(tid)
            for role_name, expected in colors.items():
                with self.subTest(theme=tid, role=role_name):
                    self.assertEqual(
                        pal.color(_PALETTE_ROLE_MAP[role_name]).name().lower(),
                        expected.lower(),
                        f"{tid} 主题 QPalette.{role_name} 与定义不一致")


class EditorSmokeTests(unittest.TestCase):
    """18 个入口的主窗口：实例化 + 4 主题应用均不崩溃且 QSS 真实生效。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _ensure_app()

    def test_all_windows_survive_all_themes(self):
        factories = _make_window_factory()
        self.assertEqual(len(factories), 18,
                         "入口数量变化时请同步更新 _EDITOR_ENTRIES")
        failures = []
        for entry_name, window_cls in factories:
            reason = _KNOWN_SKIP.get(entry_name)
            if reason:
                self.skipTest(f"{entry_name}: {reason}")
            window = None
            try:
                with _SilenceDialogs():
                    window = window_cls()
                self.assertTrue(
                    window.objectName(),
                    f"{entry_name}: objectName 为空（QSS 选择器目标可能丢失）")
                for tid in theme_manager.THEME_ORDER:
                    with self.subTest(editor=entry_name, theme=tid):
                        apply_theme_to_window(window, tid, persist=False)
                        self.assertTrue(
                            window.styleSheet().strip(),
                            f"{entry_name}@{tid}: 窗口样式表为空")
                        self.assertEqual(
                            getattr(window, THEME_ATTR, None), tid,
                            f"{entry_name}@{tid}: 主题属性未同步")
                        self.app.processEvents()
            except unittest.SkipTest:
                raise
            except Exception as exc:  # noqa: BLE001 - 收集后统一断言
                failures.append(f"{entry_name}: {exc.__class__.__name__}: {exc}")
            finally:
                if window is not None:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
        if failures:
            self.fail("以下入口冒烟失败:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
