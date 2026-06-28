"""日志终端 — 只读 QTextEdit + QSyntaxHighlighter 动态着色

颜色策略:
  文本以纯文本存储在文档中, 无任何内联样式。
  LogHighlighter 在渲染时根据每行内容动态应用前景色。
  主题切换时调用 rehighlight() 即可立即重新着色全部行, 无需重建文档。
"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import (
    QTextCursor, QTextCharFormat, QColor, QSyntaxHighlighter, QTextDocument,
)
from PySide6.QtCore import Qt


class LogHighlighter(QSyntaxHighlighter):
    """日志行级别着色器 — 根据行内容中的标记应用前景色"""

    _LEVEL_COLORS_DARK = {
        'error': '#E06C75',
        'warn':  '#E5C07B',
        'ok':    '#98C379',
        'info':  '#61AFEF',
    }
    _LEVEL_COLORS_LIGHT = {
        'error': '#C62828',
        'warn':  '#B8860B',
        'ok':    '#2E7D32',
        'info':  '#1565C0',
    }
    _DEFAULT_FG_DARK = '#dcdcdc'
    _DEFAULT_FG_LIGHT = '#333333'

    def __init__(self, document: QTextDocument, dark: bool = True):
        super().__init__(document)
        self._dark = dark
        self._build_formats()

    def set_dark_mode(self, dark: bool):
        if dark == self._dark:
            return
        self._dark = dark
        self._build_formats()
        self.rehighlight()

    def _build_formats(self):
        """ 构建 / 更新各级别的 QTextCharFormat"""
        colors = self._LEVEL_COLORS_DARK if self._dark else self._LEVEL_COLORS_LIGHT
        default_fg = self._DEFAULT_FG_DARK if self._dark else self._DEFAULT_FG_LIGHT

        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(QColor(colors['error']))

        self._fmt_warn = QTextCharFormat()
        self._fmt_warn.setForeground(QColor(colors['warn']))

        self._fmt_ok = QTextCharFormat()
        self._fmt_ok.setForeground(QColor(colors['ok']))

        self._fmt_info = QTextCharFormat()
        self._fmt_info.setForeground(QColor(colors['info']))

        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor(default_fg))

    def highlightBlock(self, text: str):
        """对每个文本块 (行) 应用颜色"""
        if "[ERROR]" in text or "[FATAL]" in text:
            fmt = self._fmt_error
        elif "[WARN]" in text:
            fmt = self._fmt_warn
        elif "[OK]" in text:
            fmt = self._fmt_ok
        elif "[INFO]" in text:
            fmt = self._fmt_info
        else:
            fmt = self._fmt_default
        self.setFormat(0, len(text), fmt)


class LogConsole(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        # 创建高亮器 (绑定到 document)
        self._highlighter = LogHighlighter(self.document(), dark=True)

    def set_dark_mode(self, dark: bool):
        # 保存滚动条位置，防止 rehighlight() 导致滚动跳动
        vbar = self.verticalScrollBar()
        pos = vbar.value()
        self._highlighter.set_dark_mode(dark)
        vbar.setValue(pos)

    def append_log(self, text: str):
        """追加一行纯文本日志并滚动到底部"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if cursor.position() > 0:
            cursor.insertBlock()
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def clear_log(self):
        self.clear()
