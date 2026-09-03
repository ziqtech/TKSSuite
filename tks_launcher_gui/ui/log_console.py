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

from editor_utils.theme_manager import business_colors

# 补丁 ID 标记: [字母开头, 字母/数字/下划线/连字符]: — 如 "[war_status_icons]:"。
# 级别标记 ([ERROR] 等) 后不带冒号, 中文标记 ([跳过]) 首字符非字母, 均不会误匹配。
_ID_TAG_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9_-]*\]:")
# 十六进制地址: 0x + 至少 2 位十六进制
_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
# 级别标记本身 (加粗突出)
_LEVEL_TAG_RE = re.compile(r"\[(?:ERROR|FATAL|WARN|OK|INFO)\]")


class LogHighlighter(QSyntaxHighlighter):
    """日志着色器 — 行级基调 + 段级覆盖 (补丁 ID / 级别标记 / 地址)

    颜色取自 theme_tokens.LOG_CONSOLE 语义色表, 随主题切换重建。
    """

    def __init__(self, document: QTextDocument, theme_id: str = "gpt-dark"):
        super().__init__(document)
        self._theme_id = theme_id
        self._build_formats()

    def set_theme(self, theme_id: str):
        if theme_id == self._theme_id:
            return
        self._theme_id = theme_id
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
        pal = business_colors("log_console", self._theme_id)

        self._fmt_default = self._make_fmt(pal["default_fg"])

        # 段级: 补丁 ID 蓝 / 地址青
        self._fmt_patch_id = self._make_fmt(pal["id_color"])
        self._fmt_hex = self._make_fmt(pal["hex_color"])

        # 级别标记 → (整行格式, 标记加粗格式) 查找表, 按检测优先级排列
        def pair(key: str):
            color = pal[key]
            return self._make_fmt(color), self._make_fmt(color, bold=True)

        self._level_fmts = {
            '[ERROR]': pair('error'),
            '[FATAL]': pair('error'),
            '[WARN]':  pair('warn'),
            '[OK]':    pair('ok'),
            '[INFO]':  pair('info'),
        }

    def highlightBlock(self, text: str):
        """对每个文本块 (行) 应用颜色: 先行级基调, 再段级覆盖"""
        # 1. 行级基调: 查找表按序取首个命中的标记
        fmt, bold_fmt = next(
            (self._level_fmts[m] for m in self._level_fmts if m in text),
            (self._fmt_default, None),
        )
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
    # 文档行数上限: 超出后从头部裁剪 (防止长跑会话内存无限增长)。
    # QTextEdit 无行数概念, 以块数近似 (每行一块)。
    MAX_BLOCKS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        # 按需显示滚动条: 空日志时不占轨道, 追加日志时 ensureCursorVisible 自动滚到底
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 用户向上翻阅历史时暂停自动滚动, 拉回底部后恢复
        self._autoscroll = True
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_moved)
        # 创建高亮器 (绑定到 document)
        self._highlighter = LogHighlighter(self.document(), theme_id="gpt-dark")

    def _on_scroll_moved(self, value):
        vbar = self.verticalScrollBar()
        at_bottom = value >= vbar.maximum() - 2
        self._autoscroll = at_bottom

    def set_theme(self, theme_id: str):
        # 保存滚动条位置，防止 rehighlight() 导致滚动跳动
        vbar = self.verticalScrollBar()
        pos = vbar.value()
        self._highlighter.set_theme(theme_id)
        vbar.setValue(pos)

    def append_log(self, text: str):
        """追加一行纯文本日志; 滚动条在底部时自动跟随, 否则保持当前位置"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if cursor.position() > 0:
            cursor.insertBlock()
        cursor.insertText(text)
        self._trim_document()
        if self._autoscroll:
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

    def _trim_document(self):
        """行数超限时裁剪最旧的块 (按 MAX_BLOCKS 的 10% 批量裁, 避免逐行裁)。"""
        doc = self.document()
        limit = self.MAX_BLOCKS
        if doc.blockCount() <= limit:
            return
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.Start)
        excess = doc.blockCount() - limit + max(1, limit // 10)
        for _ in range(excess):
            cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

    def export_log(self, parent=None) -> bool:
        """导出日志到文本文件; 返回是否已保存。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            parent or self, "导出日志", "launcher_log.txt", "文本文件 (*.txt)")
        if not path:
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.toPlainText())
        return True

    def clear_log(self):
        self.clear()
