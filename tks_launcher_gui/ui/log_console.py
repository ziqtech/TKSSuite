"""日志终端 — 只读 QTextEdit, 自动滚动, 彩色日志

颜色策略:
  每行日志都通过 HTML <span style="color:..."> 显式指定颜色,
  完全绕开 QPalette / QSS 干扰, 避免颜色泄漏和主题不生效问题。
"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt


class LogConsole(QTextEdit):
    # 日志级别专属颜色 (深色/浅色各一套)
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
    # 默认文字色 — QSS 中已移除 color 属性, 完全由此处控制
    _DEFAULT_FG_DARK = '#dcdcdc'   # 与全局主题白色一致
    _DEFAULT_FG_LIGHT = '#333333'  # 深色文字适合浅色背景

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._colors = self._LEVEL_COLORS_DARK
        self._default_fg = self._DEFAULT_FG_DARK
        self._lines: list[str] = []  # 储存原始日志文本, 用于主题切换时重新渲染

    def set_dark_mode(self, dark: bool):
        self._colors = self._LEVEL_COLORS_DARK if dark else self._LEVEL_COLORS_LIGHT
        self._default_fg = self._DEFAULT_FG_DARK if dark else self._DEFAULT_FG_LIGHT
        # 主题切换后重新渲染已有日志
        self._rerender()

    def _pick_color(self, text: str) -> str | None:
        """根据日志级别标记选择颜色; 返回 None 表示使用默认色"""
        if "[ERROR]" in text or "[FATAL]" in text:
            return self._colors['error']
        if "[WARN]" in text:
            return self._colors['warn']
        if "[OK]" in text:
            return self._colors['ok']
        if "[INFO]" in text:
            return self._colors['info']
        return None

    def append_log(self, text: str):
        """追加一行日志并自动滚动到底部

        每行都通过 HTML <span style="color:..."> 包裹,
        确保颜色绝对可控, 不受 QPalette / QSS 干扰。
        """
        self._lines.append(text)
        color = self._pick_color(text) or self._default_fg
        safe = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        self.append(f'<span style="color:{color}">{safe}</span>')
        # 滚动到底部
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _rerender(self):
        """用当前主题色重新渲染所有已存储的日志行"""
        if not self._lines:
            return
        parts = []
        for line in self._lines:
            color = self._pick_color(line) or self._default_fg
            safe = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            parts.append(f'<span style="color:{color}">{safe}</span>')
        # 清空后一次性设置全部 HTML, 避免逐行 append 的性能开销
        self.clear()
        self.setHtml('<br>'.join(parts))
        # 滚动到底部
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def clear_log(self):
        self._lines.clear()
        self.clear()
