"""日志终端 — 只读 QTextEdit + QSyntaxHighlighter 动态着色

颜色策略:
  文本以纯文本存储在文档中, 无任何内联样式。
  LogHighlighter 在渲染时分两层着色:
    1. 行级基调 — 按级别标记 ([ERROR]/[WARN]/[OK]/[INFO]) 决定整行前景色;
    2. 段级覆盖 — 补丁 ID 标记 ([patch_id]:) 蓝色、级别标记加粗、
       十六进制地址青色。
  主题切换时调用 rehighlight() 即可立即重新着色全部行, 无需重建文档。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument,
    QSyntaxHighlighter,
)
from PySide6.QtWidgets import QTextEdit

# 补丁 ID 标记: [字母开头, 字母/数字/下划线/连字符]: — 如 "[war_status_icons]:"。
# 级别标记 ([ERROR] 等) 后不带冒号, 中文标记 ([跳过]) 首字符非字母, 均不会误匹配。
_ID_TAG_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9_-]*\]:")
# 十六进制地址: 0x + 至少 2 位十六进制
_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
# 级别标记本身 (加粗突出)
_LEVEL_TAG_RE = re.compile(r"\[(?:ERROR|FATAL|WARN|OK|INFO)\]")


class LogHighlighter(QSyntaxHighlighter):
    """日志着色器 — 行级基调 + 段级覆盖 (补丁 ID / 级别标记 / 地址)"""

    _LEVEL_COLORS_DARK = {
        'error': '#F87171',
        'warn':  '#F6C56B',
        'ok':    '#4ADE80',
        'info':  '#7AA2F7',
    }
    _LEVEL_COLORS_LIGHT = {
        'error': '#C62828',
        'warn':  '#9A6A00',
        'ok':    '#2E7D32',
        'info':  '#4F6FD6',
    }
    _DEFAULT_FG_DARK = '#ececec'
    _DEFAULT_FG_LIGHT = '#2d2d2d'
    # 补丁 ID 蓝 (区别于 info 蓝, 略亮以便在深色底上更清晰)
    _ID_COLOR_DARK = '#82AAFF'
    _ID_COLOR_LIGHT = '#1D4ED8'
    # 十六进制地址青
    _HEX_COLOR_DARK = '#2DD4BF'
    _HEX_COLOR_LIGHT = '#0D9488'

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

    @staticmethod
    def _make_fmt(color: str, bold: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def _build_formats(self):
        """构建 / 更新各级别与段级高亮的 QTextCharFormat"""
        colors = self._LEVEL_COLORS_DARK if self._dark else self._LEVEL_COLORS_LIGHT
        default_fg = self._DEFAULT_FG_DARK if self._dark else self._DEFAULT_FG_LIGHT

        self._fmt_error = self._make_fmt(colors['error'])
        self._fmt_warn = self._make_fmt(colors['warn'])
        self._fmt_ok = self._make_fmt(colors['ok'])
        self._fmt_info = self._make_fmt(colors['info'])
        self._fmt_default = self._make_fmt(default_fg)

        # 级别标记本体加粗 (与整行同色, 仅增字重)
        self._fmt_error_bold = self._make_fmt(colors['error'], bold=True)
        self._fmt_warn_bold = self._make_fmt(colors['warn'], bold=True)
        self._fmt_ok_bold = self._make_fmt(colors['ok'], bold=True)
        self._fmt_info_bold = self._make_fmt(colors['info'], bold=True)

        # 段级: 补丁 ID 蓝 / 地址青
        id_color = self._ID_COLOR_DARK if self._dark else self._ID_COLOR_LIGHT
        hex_color = self._HEX_COLOR_DARK if self._dark else self._HEX_COLOR_LIGHT
        self._fmt_patch_id = self._make_fmt(id_color)
        self._fmt_hex = self._make_fmt(hex_color)

    def highlightBlock(self, text: str):
        """对每个文本块 (行) 应用颜色: 先行级基调, 再段级覆盖"""
        if "[ERROR]" in text or "[FATAL]" in text:
            fmt, bold_fmt = self._fmt_error, self._fmt_error_bold
        elif "[WARN]" in text:
            fmt, bold_fmt = self._fmt_warn, self._fmt_warn_bold
        elif "[OK]" in text:
            fmt, bold_fmt = self._fmt_ok, self._fmt_ok_bold
        elif "[INFO]" in text:
            fmt, bold_fmt = self._fmt_info, self._fmt_info_bold
        else:
            fmt, bold_fmt = self._fmt_default, None

        # 1. 行级基调
        self.setFormat(0, len(text), fmt)

        # 2. 段级覆盖 (后设置的生效, 按覆盖优先级从低到高)
        for m in _HEX_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt_hex)
        for m in _ID_TAG_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt_patch_id)
        if bold_fmt is not None:
            for m in _LEVEL_TAG_RE.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), bold_fmt)


class LogConsole(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        # 按需显示滚动条: 空日志时不占轨道, 追加日志时 ensureCursorVisible 自动滚到底
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
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
