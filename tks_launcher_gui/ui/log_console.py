"""日志终端 — 只读 QTextEdit, 自动滚动, 彩色日志"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt


class LogConsole(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFontFamily("Consolas")
        self.setFontPointSize(10)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

    def append_log(self, text: str):
        """追加一行日志并自动滚动到底部"""
        if "[ERROR]" in text or "[FATAL]" in text:
            self.append(f'<span style="color:#E06C75">{text}</span>')
        elif "[WARN]" in text:
            self.append(f'<span style="color:#E5C07B">{text}</span>')
        elif "[OK]" in text:
            self.append(f'<span style="color:#98C379">{text}</span>')
        else:
            self.append(text)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

    def clear_log(self):
        self.clear()
