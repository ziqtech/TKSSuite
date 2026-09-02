# -*- coding: utf-8 -*-
"""mat_editor UI 组件 — 代码编辑器与脚本语法高亮。
从 mat_editor.py 原样迁出 (§工程化拆分)。"""
import re

from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QTextCursor
from PySide6.QtCore import Qt
from editor_utils.theme_manager import business_colors

from mat_script_desc import SCRIPT_COMMANDS

_CMD_SET = frozenset(SCRIPT_COMMANDS)   # 命令名集合 (供高亮整词匹配, 含无参命令如 Else)


class CodeEditor(QPlainTextEdit):
    """代码编辑器 — 支持 Tab 缩进、多行缩进/反缩进、自动换行等 VSCode 风格操作"""
    INDENT = "  "  # 2 空格缩进

    def keyPressEvent(self, event):
        # Tab 键: 插入缩进或多行缩进
        if event.key() == Qt.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_lines(cursor, indent=True)
            else:
                cursor.insertText(self.INDENT)
            return
        # Shift+Tab: 多行反缩进
        if event.key() == Qt.Key_Backtab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_lines(cursor, indent=False)
            return
        # Enter 键: 自动缩进 (保持上一行的缩进级别)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block = cursor.block()
            line_text = block.text()
            # 计算当前行的缩进
            indent = ""
            for ch in line_text:
                if ch == ' ':
                    indent += ' '
                elif ch == '\t':
                    indent += '  '
                else:
                    break
            # 如果上一行以 { 结尾，额外增加一级缩进
            stripped = line_text.rstrip()
            if stripped.endswith('{'):
                indent += self.INDENT
            cursor.insertText('\n' + indent)
            return
        super().keyPressEvent(event)

    def _indent_lines(self, cursor, indent=True):
        """对选中的多行进行缩进或反缩进"""
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.beginEditBlock()

        # 移动到选区起始行
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.StartOfBlock)
        start_block = cursor.block()

        # 移动到选区结束行
        cursor.setPosition(end)
        if cursor.atBlockStart() and end > start:
            # 如果选区正好在行首，不包含这一行
            cursor.movePosition(QTextCursor.PreviousBlock)
        cursor.movePosition(QTextCursor.EndOfBlock)
        end_block = cursor.block()

        # 遍历每一行
        block = start_block
        while True:
            line_text = block.text()
            if indent:
                # 缩进: 在行首插入2个空格
                cursor.setPosition(block.position())
                cursor.insertText(self.INDENT)
            else:
                # 反缩进: 删除行首最多2个空格
                if line_text.startswith(self.INDENT):
                    cursor.setPosition(block.position())
                    cursor.setPosition(block.position() + 2, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                elif line_text.startswith(' '):
                    cursor.setPosition(block.position())
                    cursor.setPosition(block.position() + 1, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()

            if block == end_block:
                break
            block = block.next()

        cursor.endEditBlock()


class ScriptSyntaxHighlighter(QSyntaxHighlighter):
    """脚本编辑器语法高亮 — 配色方案与 Godot 4.6 代码编辑器保持一致。
    优先级 (高→低): block > command > number > comment > keyword,
    按升序 setFormat 使高优先级后涂覆盖低优先级。"""
    # 配色取自 theme_tokens.MAT.editor_syntax (参考 Godot 4.6 编辑器主题)
    def __init__(self, document, theme_id="gpt-dark"):
        super().__init__(document)
        self.theme_id = theme_id
        self._is_dark = theme_id.endswith("dark")
        self._palette = business_colors("mat", theme_id)["editor_syntax"]
        self._build_formats()

    def _build_formats(self):
        def _fmt(key):
            f = QTextCharFormat()
            f.setForeground(QColor(self._palette[key]))
            return f
        self.fmt_keyword = _fmt('keyword')  # DEFINE
        self.fmt_comment = _fmt('comment')  # // 注释
        self.fmt_number  = _fmt('number')   # 数字
        self.fmt_command = _fmt('command')  # 命令名
        self.fmt_block   = _fmt('block')    # { } 块

    def set_theme(self, theme_id):
        """切换主题后重建格式并重涂"""
        if self.theme_id == theme_id:
            return
        self.theme_id = theme_id
        self._is_dark = theme_id.endswith("dark")
        self._palette = business_colors("mat", theme_id)["editor_syntax"]
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text):
        line = text
        stripped = line.strip()
        line_len = len(line)
        comment_start = line.find('//')
        # 1. keyword (最低优先级)
        if stripped.startswith('DEFINE'):
            self.setFormat(0, line_len, self.fmt_keyword)
        # 2. comment
        if comment_start >= 0:
            self.setFormat(comment_start, line_len - comment_start, self.fmt_comment)
        # 3. number (跳过注释内的数字)
        for m in re.finditer(r'-?\d+', line):
            if comment_start >= 0 and m.start() >= comment_start:
                continue
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)
        # 4. command: 命令名 (Cmd(...) 形式, 或无参命令如 Else/DoTalkB 单独成词均高亮)
        for m in re.finditer(r'\b[A-Za-z_]\w*\b', line):
            if comment_start >= 0 and m.start() >= comment_start:
                continue  # 跳过注释内的词
            if m.group(0) in _CMD_SET:
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_command)
        # 5. block (最高优先级, 整行)
        if stripped.startswith('{') or stripped.startswith('}'):
            self.setFormat(0, line_len, self.fmt_block)
