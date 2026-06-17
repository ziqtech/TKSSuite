"""日志终端 — 只读 QTextEdit, 自动滚动, 彩色日志"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt


class LogConsole(QTextEdit):
    # 深色/浅色模式下的日志颜色方案
    _COLORS_DARK = {
        'error': '#E06C75',
        'warn':  '#E5C07B',
        'ok':    '#98C379',
    }
    _COLORS_LIGHT = {
        'error': '#C62828',
        'warn':  '#B8860B',
        'ok':    '#2E7D32',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        self.setFontFamily("Consolas")
        self.setFontPointSize(10)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._dark = True
        self._colors = self._COLORS_DARK

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._colors = self._COLORS_DARK if dark else self._COLORS_LIGHT

    def append_log(self, text: str):
        """追加一行日志并自动滚动到底部"""
        c = self._colors
        if "[ERROR]" in text or "[FATAL]" in text:
            self.append(f'<span style="color:{c["error"]}">{text}</span>')
        elif "[WARN]" in text:
            self.append(f'<span style="color:{c["warn"]}">{text}</span>')
        elif "[OK]" in text:
            self.append(f'<span style="color:{c["ok"]}">{text}</span>')
        else:
            self.append(text)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

    def clear_log(self):
        self.clear()
