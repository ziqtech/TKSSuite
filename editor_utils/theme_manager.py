"""
统一主题管理器（四主题）。

主题结构模板放在 ``editor_themes/templates/base.qss.tpl``（全套件唯一一份），
槽位颜色值集中在 ``editor_utils/theme_tokens.py``；本模块负责主题注册表、
资源定位、模板渲染（QSS 生成）、QPalette 生成，以及主题选择的跨编辑器持久化
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

from editor_utils import theme_tokens


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
    is_dark: bool
    family: str


THEME_ORDER: tuple[str, ...] = ("gpt-dark", "gpt-light", "classic-dark", "classic-light")

THEMES: dict[str, ThemeSpec] = {
    "gpt-dark": ThemeSpec("gpt-dark", "现代深色", True, "modern"),
    "gpt-light": ThemeSpec("gpt-light", "现代浅色", False, "modern"),
    "classic-dark": ThemeSpec("classic-dark", "经典深色", True, "classic"),
    "classic-light": ThemeSpec("classic-light", "经典浅色", False, "classic"),
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


_OPT_LINE = re.compile(r"^\{\{\?(\w+)\}\}$")
_INLINE = re.compile(r"\{\{(\w+)\}\}")


def _render_template(template: str, tokens: dict[str, str]) -> str:
    """把槽位值注入族模板生成 QSS。

    ``{{name}}`` 行内替换；独占一行的 ``{{?name}}`` 为可选行——
    槽位值为空时整行从结果中删除（用于两主题结构有差异的行）。
    """
    lines: list[str] = []
    for line in template.split("\n"):
        m = _OPT_LINE.fullmatch(line.strip())
        if m:
            value = tokens.get(m.group(1), "")
            if value:
                lines.append(value)
            continue
        lines.append(
            _INLINE.sub(lambda mo: tokens.get(mo.group(1), mo.group(0)), line))
    return "\n".join(lines)


def _load_qss(theme_id: str) -> str:
    """渲染指定主题的 QSS：单一结构模板 + theme_tokens 槽位值。"""
    tpl_path = _THEMES_DIR / "templates" / "base.qss.tpl"
    if not tpl_path.is_file():
        return ""
    template = tpl_path.read_text(encoding="utf-8")
    qss = _render_template(template, theme_tokens.tokens_for(theme_id))

    # 把相对资源路径转换为跨打包环境的绝对路径
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
        _qss_cache[value] = _load_qss(value)
    return _qss_cache[value]


# 各主题画布（QGraphicsView）背景色，与主题模板中 QGraphicsView 的
# background-color 保持一致，供 mat_editor 等编辑器的画布背景刷与
# PIL 合成底色取用（QSS 加载失败时按深浅回退通用底色）。


def canvas_background(theme_id: str) -> str:
    """返回指定主题的画布背景色（值见 theme_tokens.CANVAS_BG）。"""
    value = normalize_theme(theme_id)
    return theme_tokens.CANVAS_BG.get(value) or (
        "#1a1e27" if THEMES[value].is_dark else "#ffffff")


def business_colors(table: str, theme_id: str) -> dict:
    """返回业务控件族语义色板（按主题取值后的字典）。

    表名与键见 theme_tokens._BUSINESS（mode_card / log_console，随业务
    控件扩充）。自绘控件不得再内置主题色值。
    """
    return theme_tokens.business_colors(table, normalize_theme(theme_id))


def svg_path(name: str) -> str:
    """返回 ``editor_themes/svg`` 中图标的绝对路径。"""
    if not name.endswith(".svg"):
        name += ".svg"
    return str((_THEMES_DIR / "svg" / name).resolve())


def svg_icon(name: str) -> QIcon:
    """从主题资源目录加载 SVG 图标。"""
    return QIcon(svg_path(name))


# Qt 原生控件（QSS 不覆盖的弹窗、滚动区域等）使用的调色板。
# 颜色值集中在 theme_tokens.PALETTE，此处只做角色名 → QPalette 角色的映射。
_PALETTE_ROLE_MAP: dict[str, QPalette.ColorRole] = {
    "window": QPalette.ColorRole.Window,
    "window_text": QPalette.ColorRole.WindowText,
    "base": QPalette.ColorRole.Base,
    "alternate_base": QPalette.ColorRole.AlternateBase,
    "text": QPalette.ColorRole.Text,
    "button": QPalette.ColorRole.Button,
    "button_text": QPalette.ColorRole.ButtonText,
    "highlight": QPalette.ColorRole.Highlight,
    "highlighted_text": QPalette.ColorRole.HighlightedText,
    "placeholder_text": QPalette.ColorRole.PlaceholderText,
    "tooltip_base": QPalette.ColorRole.ToolTipBase,
    "tooltip_text": QPalette.ColorRole.ToolTipText,
}


_palettes: dict[str, QPalette] = {}


def palette(theme_id: str) -> QPalette:
    """返回指定主题的 QPalette（懒加载并缓存）。"""
    value = normalize_theme(theme_id)
    if value not in _palettes:
        pal = QPalette()
        for role_name, color in theme_tokens.PALETTE[value].items():
            pal.setColor(_PALETTE_ROLE_MAP[role_name], QColor(color))
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
