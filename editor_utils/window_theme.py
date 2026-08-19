"""
Windows 窗口标题栏主题工具 — 通过 DWM API 设置深色标题栏和自定义颜色
兼容 Windows 10 1809+ (深色模式) 和 Windows 11 (自定义颜色)
颜色配置与 editor_themes/ 目录下的 QSS 主题保持一致
"""
import ctypes
import sys

# DWM 属性常量
DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Windows 10 1809+
DWMWA_BORDER_COLOR = 34             # Windows 11
DWMWA_CAPTION_COLOR = 35            # Windows 11
DWMWA_TEXT_COLOR = 36               # Windows 11

# 深色主题配色 (与 dark.qss 的 Godot 4.7 色板一致: chrome #292929)
DARK_COLORS = {
    'caption': 0x00292929,   # #292929 → BGR (灰阶 R=G=B)
    'border':  0x001b1b1b,   # 标题带同层 #1b1b1b → BGR
    'text':    0x00bfbfbf,   # #bfbfbf (白 75% 于 caption 的等效色)
    'dark_mode': 1,
}

# 浅色主题配色 (与 light.qss 的 Godot 4.7 色板一致: chrome #e6e6e6)
LIGHT_COLORS = {
    'caption': 0x00e6e6e6,   # #e6e6e6 → BGR
    'border':  0x00b7b7b7,   # 边框 #b7b7b7 → BGR
    'text':    0x00404040,   # #404040 (黑 75% 于 caption 的等效色)
    'dark_mode': 0,
}


def _set_attr(hwnd, attr, value):
    """设置 DWM 窗口属性"""
    if sys.platform != 'win32':
        return
    v = ctypes.c_int(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)
    )


def apply_godot_theme(widget, is_dark=True):
    """
    对 QWidget 应用 Godot 风格的窗口主题
    is_dark: True=深色主题(dark.qss), False=浅色主题(light.qss)
    """
    hwnd = int(widget.winId())
    colors = DARK_COLORS if is_dark else LIGHT_COLORS
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, colors['dark_mode'])
    _set_attr(hwnd, DWMWA_CAPTION_COLOR, colors['caption'])
    _set_attr(hwnd, DWMWA_BORDER_COLOR, colors['border'])
    _set_attr(hwnd, DWMWA_TEXT_COLOR, colors['text'])
