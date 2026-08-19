"""
主题管理器 — 从 editor_themes/ 目录加载 QSS，统一管理深色/浅色主题
支持两种用法:
  1. 实例模式: tm = ThemeManager(); tm.get_stylesheet()
  2. 静态模式: ThemeManager.apply_dark_theme(app)
"""
import os
import re
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor

# 打包环境: Nuitka/PyInstaller 将 editor_themes/ 烘焙进 exe
# Nuitka: __file__ 始终指向正确位置 (无论 onefile/standalone)
# PyInstaller: 通过 sys._MEIPASS 访问
# 开发环境: 相对于当前文件的上级目录
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _THEMES_DIR = os.path.join(sys._MEIPASS, 'editor_themes')
else:
    # Nuitka 编译 和 开发环境 均通过 __file__ 相对路径定位
    _THEMES_DIR = os.path.join(os.path.dirname(__file__), '..', 'editor_themes')


def _load_qss(theme: str) -> str:
    """从 editor_themes/ 加载 QSS 并将 url() 相对路径转为绝对路径"""
    qss_path = os.path.join(_THEMES_DIR, f'{theme}.qss')
    if not os.path.exists(qss_path):
        return ''
    with open(qss_path, 'r', encoding='utf-8') as f:
        qss = f.read()
    abs_dir = os.path.abspath(_THEMES_DIR).replace("\\", "/")
    return re.sub(r'url\(([^)]+)\)', lambda m: f'url({abs_dir}/{m.group(1)})', qss)


def _make_palette(dark: bool) -> QPalette:
    """QPalette 后备方案 — 色板与 Godot 4.7 预设保持一致 (Default / Light)"""
    p = QPalette()
    if dark:
        p.setColor(QPalette.Window, QColor('#292929'))
        p.setColor(QPalette.WindowText, QColor('#bfbfbf'))
        p.setColor(QPalette.Base, QColor('#1c1c1c'))
        p.setColor(QPalette.AlternateBase, QColor('#2f2f2f'))
        p.setColor(QPalette.Text, QColor('#bfbfbf'))
        p.setColor(QPalette.Button, QColor('#424242'))
        p.setColor(QPalette.ButtonText, QColor('#bfbfbf'))
        p.setColor(QPalette.Highlight, QColor('#569eff'))
        p.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    else:
        p.setColor(QPalette.Window, QColor('#e6e6e6'))
        p.setColor(QPalette.WindowText, QColor('#404040'))
        p.setColor(QPalette.Base, QColor('#f5f5f5'))
        p.setColor(QPalette.AlternateBase, QColor('#dedede'))
        p.setColor(QPalette.Text, QColor('#404040'))
        p.setColor(QPalette.Button, QColor('#cacaca'))
        p.setColor(QPalette.ButtonText, QColor('#323232'))
        p.setColor(QPalette.Highlight, QColor('#2e80ff'))
        p.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    return p


# 预加载 QSS 缓存
_DARK_QSS = _load_qss('dark')
_LIGHT_QSS = _load_qss('light')


class ThemeManager:
    """实例模式主题管理器"""

    def __init__(self):
        self.current_theme = 'dark'

    def get_stylesheet(self) -> str:
        return _DARK_QSS if self.current_theme == 'dark' else _LIGHT_QSS

    def toggle_theme(self):
        self.current_theme = 'light' if self.current_theme == 'dark' else 'dark'

    def set_theme(self, theme: str):
        self.current_theme = theme

    @staticmethod
    def apply_theme(widget, theme: str):
        """对 widget 应用指定主题 ('dark' 或 'light')"""
        qss = _DARK_QSS if theme == 'dark' else _LIGHT_QSS
        if qss:
            widget.setStyleSheet(qss)
        else:
            widget.setPalette(_make_palette(theme == 'dark'))

    @staticmethod
    def apply_dark_theme(widget):
        ThemeManager.apply_theme(widget, 'dark')

    @staticmethod
    def apply_light_theme(widget):
        ThemeManager.apply_theme(widget, 'light')

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


