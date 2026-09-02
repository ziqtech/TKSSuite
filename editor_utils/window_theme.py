"""
Windows 窗口标题栏主题工具。

QSS 负责应用内部控件，Windows DWM 负责原生标题栏；两者按同一主题的
色板对齐。四个主题各自拥有一套标题栏配色（见 ``TITLEBAR_COLORS``）。
"""
import ctypes
import sys

from editor_utils import theme_tokens


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


# 标题栏色板值统一维护在 theme_tokens.TITLEBAR（单一事实来源），
# 此处转换为 DWM 使用的 0x00BBGGRR 整数。
def _build_titlebar_colors() -> dict:
    colors: dict = {}
    for tid, spec in theme_tokens.TITLEBAR.items():
        colors[tid] = {
            "caption": _hex_to_bgr(spec["caption"]),
            "border": _hex_to_bgr(spec["border"]),
            "text": _hex_to_bgr(spec["text"]),
            "dark_mode": spec["dark_mode"],
        }
    return colors


TITLEBAR_COLORS = _build_titlebar_colors()


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


def apply_titlebar_theme(widget, theme_id: str):
    """为 QWidget 应用与主题一致的 Windows 原生标题栏/边框配色。"""
    if sys.platform != "win32":
        return
    colors = TITLEBAR_COLORS.get(str(theme_id).strip().lower())
    if colors is None:
        return
    try:
        hwnd = int(widget.winId())
    except (AttributeError, TypeError, ValueError, OSError):
        return

    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, colors["dark_mode"])
    _set_attr(hwnd, DWMWA_CAPTION_COLOR, colors["caption"])
    _set_attr(hwnd, DWMWA_BORDER_COLOR, colors["border"])
    _set_attr(hwnd, DWMWA_TEXT_COLOR, colors["text"])
