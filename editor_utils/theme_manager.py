"""
ChatGPT 风格主题管理器。

QSS 放在 ``editor_themes/`` 中，主题管理器只负责资源定位、缓存、应用和
Qt 原生调色板兜底。保留原有的实例模式与静态方法，旧编辑器无需改动即可
获得新的视觉主题。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette


def _themes_dir() -> Path:
    """返回开发环境或 PyInstaller 环境下的主题资源目录。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "editor_themes"
    return Path(__file__).resolve().parent.parent / "editor_themes"


_THEMES_DIR = _themes_dir()
_VALID_THEMES = frozenset(("dark", "light"))


def _load_qss(theme: str) -> str:
    """加载主题 QSS，并把相对资源路径转换为跨打包环境的绝对路径。"""
    qss_path = _THEMES_DIR / f"{theme}.qss"
    if not qss_path.is_file():
        return ""

    qss = qss_path.read_text(encoding="utf-8")
    resource_dir = _THEMES_DIR.resolve().as_posix()

    def replace_url(match: re.Match[str]) -> str:
        raw_path = match.group(1).strip()
        quote = raw_path[:1] if raw_path[:1] in {"'", '"'} else ""
        resource = raw_path.strip("'\"")
        if resource.startswith((":/", "qrc:", "file:", "http://", "https://")):
            return match.group(0)
        return f"url({quote}{resource_dir}/{resource}{quote})"

    return re.sub(r"url\(([^)]+)\)", replace_url, qss)


def svg_path(name: str) -> str:
    """返回 ``editor_themes/svg`` 中图标的绝对路径。"""
    if not name.endswith(".svg"):
        name += ".svg"
    return str((_THEMES_DIR / "svg" / name).resolve())


def svg_icon(name: str) -> QIcon:
    """从主题资源目录加载 SVG 图标。"""
    return QIcon(svg_path(name))


def _make_palette(dark: bool) -> QPalette:
    """生成 Qt 原生控件使用的 ChatGPT 风格调色板。"""
    if dark:
        colors = {
            QPalette.Window: "#212121",
            QPalette.WindowText: "#ECECEC",
            QPalette.Base: "#2F2F2F",
            QPalette.AlternateBase: "#262626",
            QPalette.Text: "#ECECEC",
            QPalette.Button: "#343434",
            QPalette.ButtonText: "#ECECEC",
            QPalette.Highlight: "#10A37F",
            QPalette.HighlightedText: "#FFFFFF",
            QPalette.PlaceholderText: "#8E8E8E",
            QPalette.ToolTipBase: "#2F2F2F",
            QPalette.ToolTipText: "#ECECEC",
        }
    else:
        colors = {
            QPalette.Window: "#FFFFFF",
            QPalette.WindowText: "#2D2D2D",
            QPalette.Base: "#FFFFFF",
            QPalette.AlternateBase: "#F7F7F8",
            QPalette.Text: "#2D2D2D",
            QPalette.Button: "#FFFFFF",
            QPalette.ButtonText: "#2D2D2D",
            QPalette.Highlight: "#10A37F",
            QPalette.HighlightedText: "#FFFFFF",
            QPalette.PlaceholderText: "#8E8EA0",
            QPalette.ToolTipBase: "#2D2D2D",
            QPalette.ToolTipText: "#FFFFFF",
        }

    palette = QPalette()
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    return palette


# 预加载 QSS，避免每次打开子窗口重复读盘。
_DARK_QSS = _load_qss("dark")
_LIGHT_QSS = _load_qss("light")


def _normalize_theme(theme: str) -> str:
    value = str(theme).strip().lower()
    if value not in _VALID_THEMES:
        raise ValueError(f"不支持的主题 {theme!r}，可选值为: dark、light")
    return value


class ThemeManager:
    """统一管理深色/浅色主题，兼容现有编辑器的调用方式。"""

    def __init__(self, theme: str = "dark"):
        self.current_theme = _normalize_theme(theme)

    @staticmethod
    def stylesheet(theme: str) -> str:
        """返回指定主题的 QSS。"""
        theme = _normalize_theme(theme)
        return _DARK_QSS if theme == "dark" else _LIGHT_QSS

    def get_stylesheet(self) -> str:
        return self.stylesheet(self.current_theme)

    def toggle_theme(self) -> str:
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        return self.current_theme

    def set_theme(self, theme: str) -> str:
        self.current_theme = _normalize_theme(theme)
        return self.current_theme

    @staticmethod
    def apply_theme(widget, theme: str):
        """将主题应用到 QApplication、QMainWindow 或任意 QWidget。"""
        theme = _normalize_theme(theme)
        is_dark = theme == "dark"

        # QSS 不覆盖的原生弹窗/控件仍能保持同一套底色和选中态。
        widget.setPalette(_make_palette(is_dark))
        qss = ThemeManager.stylesheet(theme)
        if qss:
            widget.setStyleSheet(qss)
        return widget

    @staticmethod
    def apply_dark_theme(widget):
        return ThemeManager.apply_theme(widget, "dark")

    @staticmethod
    def apply_light_theme(widget):
        return ThemeManager.apply_theme(widget, "light")

    @staticmethod
    def dark_qss() -> str:
        return _DARK_QSS

    @staticmethod
    def light_qss() -> str:
        return _LIGHT_QSS

    @staticmethod
    def dark_palette() -> QPalette:
        return _make_palette(True)

    @staticmethod
    def light_palette() -> QPalette:
        return _make_palette(False)
