"""
统一主题管理器（四主题）。

主题 QSS 放在 ``editor_themes/`` 中，本模块负责主题注册表、资源定位、
QSS 加载缓存、QPalette 生成，以及主题选择的跨编辑器持久化
（QSettings，Windows 下写入注册表，所有编辑器共享同一键位）。

主题清单（THEME_ORDER 即菜单展示顺序）::

    gpt-dark       现代深色 (ChatGPT 风格)   modern 族
    gpt-light      现代浅色 (ChatGPT 风格)   modern 族
    classic-dark   经典深色 (Godot 风格)     classic 族
    classic-light  经典浅色 (Godot 风格)     classic 族

同族主题共享"深/浅快速切换"语义，跨族选择经由主题菜单完成。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPalette


def _themes_dir() -> Path:
    """返回开发环境或 PyInstaller 环境下的主题资源目录。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "editor_themes"
    return Path(__file__).resolve().parent.parent / "editor_themes"


_THEMES_DIR = _themes_dir()


@dataclass(frozen=True)
class ThemeSpec:
    id: str
    display_name: str
    qss_file: str
    is_dark: bool
    family: str


THEME_ORDER: tuple[str, ...] = ("gpt-dark", "gpt-light", "classic-dark", "classic-light")

THEMES: dict[str, ThemeSpec] = {
    "gpt-dark": ThemeSpec("gpt-dark", "现代深色", "gpt-dark.qss", True, "modern"),
    "gpt-light": ThemeSpec("gpt-light", "现代浅色", "gpt-light.qss", False, "modern"),
    "classic-dark": ThemeSpec("classic-dark", "经典深色", "classic-dark.qss", True, "classic"),
    "classic-light": ThemeSpec("classic-light", "经典浅色", "classic-light.qss", False, "classic"),
}

_FAMILIES: dict[str, tuple[str, str]] = {
    "modern": ("gpt-dark", "gpt-light"),
    "classic": ("classic-dark", "classic-light"),
}

_SETTING_ORG = "TKSSuite"
_SETTING_APP = "TKSSuite"
_SETTING_KEY = "theme"


def normalize_theme(theme_id: str) -> str:
    value = str(theme_id).strip().lower()
    if value not in THEMES:
        raise ValueError(f"不支持的主题 {theme_id!r}，可选值为: {'、'.join(THEME_ORDER)}")
    return value


def _load_qss(qss_file: str) -> str:
    """加载主题 QSS，并把相对资源路径转换为跨打包环境的绝对路径。"""
    qss_path = _THEMES_DIR / qss_file
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


_qss_cache: dict[str, str] = {}


def stylesheet(theme_id: str) -> str:
    """返回指定主题的 QSS（懒加载并缓存）。"""
    value = normalize_theme(theme_id)
    if value not in _qss_cache:
        _qss_cache[value] = _load_qss(THEMES[value].qss_file)
    return _qss_cache[value]


def svg_path(name: str) -> str:
    """返回 ``editor_themes/svg`` 中图标的绝对路径。"""
    if not name.endswith(".svg"):
        name += ".svg"
    return str((_THEMES_DIR / "svg" / name).resolve())


def svg_icon(name: str) -> QIcon:
    """从主题资源目录加载 SVG 图标。"""
    return QIcon(svg_path(name))


# Qt 原生控件（QSS 不覆盖的弹窗、滚动区域等）使用的调色板。
_PALETTE_COLORS: dict[str, dict] = {
    "gpt-dark": {
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
    },
    "gpt-light": {
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
    },
    "classic-dark": {
        QPalette.Window: "#202531",
        QPalette.WindowText: "#DCDCDC",
        QPalette.Base: "#1A1E27",
        QPalette.AlternateBase: "#252A35",
        QPalette.Text: "#DCDCDC",
        QPalette.Button: "#2E3548",
        QPalette.ButtonText: "#DCDCDC",
        QPalette.Highlight: "#478CBF",
        QPalette.HighlightedText: "#FFFFFF",
        QPalette.PlaceholderText: "#8A96B3",
        QPalette.ToolTipBase: "#1A1E27",
        QPalette.ToolTipText: "#DCDCDC",
    },
    "classic-light": {
        QPalette.Window: "#E0E4E8",
        QPalette.WindowText: "#222222",
        QPalette.Base: "#FFFFFF",
        QPalette.AlternateBase: "#F2F5F7",
        QPalette.Text: "#222222",
        QPalette.Button: "#CDD3D9",
        QPalette.ButtonText: "#111111",
        QPalette.Highlight: "#478CBF",
        QPalette.HighlightedText: "#FFFFFF",
        QPalette.PlaceholderText: "#888888",
        QPalette.ToolTipBase: "#222222",
        QPalette.ToolTipText: "#FFFFFF",
    },
}

_palettes: dict[str, QPalette] = {}


def palette(theme_id: str) -> QPalette:
    """返回指定主题的 QPalette（懒加载并缓存）。"""
    value = normalize_theme(theme_id)
    if value not in _palettes:
        pal = QPalette()
        for role, color in _PALETTE_COLORS[value].items():
            pal.setColor(role, QColor(color))
        _palettes[value] = pal
    return _palettes[value]


def is_dark(theme_id: str) -> bool:
    return THEMES[normalize_theme(theme_id)].is_dark


def family_of(theme_id: str) -> str:
    return THEMES[normalize_theme(theme_id)].family


def display_name(theme_id: str) -> str:
    return THEMES[normalize_theme(theme_id)].display_name


def family_toggle(theme_id: str) -> str:
    """返回同族内深/浅互换后的主题（族内快速切换）。"""
    value = normalize_theme(theme_id)
    deep, light = _FAMILIES[THEMES[value].family]
    return light if value == deep else deep


def saved_theme() -> str | None:
    """读取跨编辑器持久化的主题选择；无合法存档返回 None。"""
    raw = QSettings(_SETTING_ORG, _SETTING_APP).value(_SETTING_KEY, "")
    value = str(raw).strip().lower()
    return value if value in THEMES else None


def set_current_theme(theme_id: str) -> str:
    """校验并持久化当前主题选择，返回规范化后的主题 id。"""
    value = normalize_theme(theme_id)
    QSettings(_SETTING_ORG, _SETTING_APP).setValue(_SETTING_KEY, value)
    return value


def system_default_theme() -> str:
    """按系统深浅色给出默认主题（沿用原行为：无应用实例时默认深色）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "gpt-light"
    return "gpt-dark"


def load_initial_theme() -> str:
    """启动时调用：优先取持久化选择，否则跟随系统深浅色。"""
    return saved_theme() or system_default_theme()


def apply_theme(widget, theme_id: str):
    """将主题（QPalette + QSS）应用到 QApplication、QMainWindow 或任意 QWidget。"""
    value = normalize_theme(theme_id)
    # QSS 不覆盖的原生弹窗/控件仍能保持同一套底色和选中态。
    widget.setPalette(palette(value))
    qss = stylesheet(value)
    if qss:
        widget.setStyleSheet(qss)
    return widget
