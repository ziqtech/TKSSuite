"""
Windows 窗口标题栏主题工具。

QSS 负责应用内部控件，Windows DWM 负责原生标题栏；两者使用同一套
ChatGPT 风格的中性灰色与绿色强调色。保留 ``apply_godot_theme`` 作为
兼容别名，避免旧版编辑器启动时报导入错误。
"""
import ctypes
import sys


# Windows 10 1809+ / Windows 11 DWM 属性
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _hex_to_bgr(value: str) -> int:
    """将 ``#RRGGBB`` 转换为 DWM 使用的 ``0x00BBGGRR`` 整数。"""
    value = value.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (blue << 16) | (green << 8) | red


# 与 editor_themes/dark.qss、light.qss 对齐的标题栏色板。
DARK_COLORS = {
    "caption": _hex_to_bgr("#212121"),
    "border": _hex_to_bgr("#444444"),
    "text": _hex_to_bgr("#ECECEC"),
    "dark_mode": 1,
}

LIGHT_COLORS = {
    "caption": _hex_to_bgr("#FFFFFF"),
    "border": _hex_to_bgr("#D9D9E3"),
    "text": _hex_to_bgr("#2D2D2D"),
    "dark_mode": 0,
}


def _set_attr(hwnd, attr, value):
    """设置 DWM 窗口属性；在非 Windows 环境中静默跳过。"""
    if sys.platform != "win32":
        return
    try:
        value_ref = ctypes.c_int(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value_ref), ctypes.sizeof(value_ref)
        )
    except (AttributeError, OSError):
        # 旧版 Windows、Wine 或无 DWM 环境不应阻断编辑器启动。
        pass


def apply_chatgpt_theme(widget, is_dark: bool = True):
    """为 QWidget 应用 ChatGPT 风格的 Windows 原生标题栏主题。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except (AttributeError, TypeError, ValueError, OSError):
        return

    colors = DARK_COLORS if is_dark else LIGHT_COLORS
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, colors["dark_mode"])
    _set_attr(hwnd, DWMWA_CAPTION_COLOR, colors["caption"])
    _set_attr(hwnd, DWMWA_BORDER_COLOR, colors["border"])
    _set_attr(hwnd, DWMWA_TEXT_COLOR, colors["text"])


def apply_godot_theme(widget, is_dark: bool = True):
    """兼容旧版调用方；新代码请使用 :func:`apply_chatgpt_theme`。"""
    apply_chatgpt_theme(widget, is_dark)
