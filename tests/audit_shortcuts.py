"""快捷键审计 —— 全窗口快捷键冲突检测 + 真实按键模拟验证。

背景（2026-09-05 修复 launcher Ctrl+T 失效）：同一窗口出现两个相同按键的
快捷键时，Qt 判定为歧义快捷键，两者都不会触发。本脚本对 18 个入口逐一：

  1. 枚举真实生效的快捷键（QShortcut + 已挂到窗口/菜单/工具栏的 QAction，
     未挂载的 QAction 快捷键不生效、不计入），按键重复即报告；
  2. 模拟 Ctrl+T 按键，断言主题真的切换（P3-8 全编辑器统一行为），
     并捕获按键触发的槽内未处理异常；
  3. 抽查文案承诺过的按键：kon / tks_book 的 F5、gxp 的 Ctrl+0。

运行（项目根目录）：
    python tests/audit_shortcuts.py

审计期间 theme_manager.set_current_theme 被替换为 no-op，
不会改动用户注册表里的主题持久化设置。
"""

import io
import os

# 必须在任何 PySide6 导入之前设置离屏平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from contextlib import redirect_stderr  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import shiboken6  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QMenu, QToolBar  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from editor_utils import theme_manager  # noqa: E402
from editor_utils.theme_switcher import THEME_ATTR  # noqa: E402
from tests.test_editor_smoke import (  # noqa: E402
    _SilenceDialogs,
    _ensure_app,
    _make_window_factory,
)

# Ctrl+T 模拟走用户显式切换路径 (persist=True)，替换为 no-op 防止污染注册表
theme_manager.set_current_theme = lambda value: None

# 文案承诺过、但不在 Ctrl+T 统一行为内的按键: (条目, 键, 修饰键, 说明)
_EXTRA_PROMISED_KEYS = [
    ("kon_editor", Qt.Key_F5, Qt.KeyboardModifier.NoModifier, "F5 切换主题"),
    ("tks_book", Qt.Key_F5, Qt.KeyboardModifier.NoModifier, "F5 切换主题"),
    ("gxp_editor", Qt.Key_0, Qt.KeyboardModifier.ControlModifier,
     "Ctrl+0 原始大小"),
]


def _registered_shortcuts(window):
    """枚举窗口内真实生效的快捷键: [(来源描述, 按键序列)]。

    右键菜单等瞬时 QMenu 可能在构造期间已被销毁 (Python 包装尚在),
    访问前一律用 shiboken6.isValid 过滤。
    """
    entries = []
    for sc in window.findChildren(QShortcut):
        if not shiboken6.isValid(sc) or sc.parent() is None:
            continue
        entries.append((f"QShortcut @{type(sc.parent()).__name__}",
                        sc.key().toString()))

    seen = set()

    def _from_action(act, where):
        if id(act) in seen or not shiboken6.isValid(act):
            return
        seen.add(id(act))
        sub = act.menu()
        if sub is not None and shiboken6.isValid(sub):
            for a in sub.actions():
                _from_action(a, sub.title())
        if not act.shortcut().isEmpty():
            entries.append((f"QAction[{where}] {act.text().strip()[:16]}",
                            act.shortcut().toString()))

    for menu in window.findChildren(QMenu):
        if not shiboken6.isValid(menu):
            continue
        for act in menu.actions():
            _from_action(act, menu.title())
    for tb in window.findChildren(QToolBar):
        if not shiboken6.isValid(tb):
            continue
        for act in tb.actions():
            _from_action(act, "工具栏")
    for act in window.actions():
        _from_action(act, "窗口")
    return entries


def _find_duplicates(entries):
    counts = {}
    for _src, key in entries:
        counts[key] = counts.get(key, 0) + 1
    return {k: n for k, n in counts.items() if n > 1}


def _press(app, window, key, mods):
    """模拟按键，返回期间 stderr 输出（捕获槽内未处理异常的回溯）。"""
    window.show()
    window.activateWindow()
    app.processEvents()
    err = io.StringIO()
    with redirect_stderr(err):
        QTest.keyClick(window, key, mods)
        app.processEvents()
    return err.getvalue()


def _last_traceback_line(noise):
    return noise.strip().splitlines()[-1] if noise.strip() else ""


def main() -> int:
    app = _ensure_app()
    factories = _make_window_factory()
    problems = []

    for entry, window_cls in factories:
        window = None
        try:
            with _SilenceDialogs():
                window = window_cls()

            entries = _registered_shortcuts(window)
            dups = _find_duplicates(entries)
            if dups:
                detail = "; ".join(f"{k} ×{n}" for k, n in sorted(dups.items()))
                owners = [src for src, key in entries if key in dups]
                problems.append(f"{entry}: 歧义快捷键 [{detail}] ← "
                                + " | ".join(dict.fromkeys(owners)))

            before = getattr(window, THEME_ATTR, None)
            noise = _press(app, window, Qt.Key_T,
                           Qt.KeyboardModifier.ControlModifier)
            if "Traceback" in noise:
                problems.append(f"{entry}: Ctrl+T 触发槽异常: "
                                f"{_last_traceback_line(noise)}")
            if getattr(window, THEME_ATTR, None) == before:
                problems.append(f"{entry}: Ctrl+T 未生效 (主题停在 {before})")

            for name, key, mods, label in _EXTRA_PROMISED_KEYS:
                if name != entry:
                    continue
                if "原始大小" in label:
                    calls = []
                    window._set_zoom = lambda f, _c=calls: _c.append(f)
                    before = None
                else:
                    before = getattr(window, THEME_ATTR, None)
                noise = _press(app, window, key, mods)
                if "原始大小" in label:
                    if 1.0 not in calls:
                        problems.append(f"{entry}: {label} 未生效")
                elif getattr(window, THEME_ATTR, None) == before:
                    problems.append(f"{entry}: {label} 未生效")
                if "Traceback" in noise:
                    problems.append(f"{entry}: {label} 触发槽异常: "
                                    f"{_last_traceback_line(noise)}")
        except Exception as exc:  # noqa: BLE001 - 收集后统一报告
            problems.append(
                f"{entry}: 构造/审计异常 {exc.__class__.__name__}: {exc}")
        finally:
            if window is not None:
                window.close()
                window.deleteLater()
                app.processEvents()

    print(f"审计窗口数: {len(factories)}")
    if problems:
        print("发现问题:")
        for p in problems:
            print("  -", p)
        return 1
    print("全部通过: 无歧义快捷键, Ctrl+T 全部可达, 承诺按键均生效, 无槽异常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
