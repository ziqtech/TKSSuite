# -*- coding: utf-8 -*-
"""统一搜索输入框。

输入内容非空时, 输入框内部右侧显示一个清除按钮 (主题感知的灰色 ✕,
悬停有背景反馈, 比原生 setClearButtonEnabled 的深色实心圆更大更柔和)；
清空后按钮自动消失。

附加交互约定:
* Esc 清空输入；已为空时移出焦点 (桌面搜索框的通行做法)；
* 占位文案由调用方传入，默认 "搜索…"。
* 图标经 xmark / xmark-light 成对约定随主题切换 (PaletteChange 刷新)。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QToolButton

from editor_utils import theme_manager


class SearchInput(QLineEdit):
    """带框内清除按钮的搜索输入框 (QLineEdit 的即插即用子类)。"""

    _BTN_SIZE = 24   # 命中区域 (含悬停背景)
    _ICON_SIZE = 18  # ✕ 字形尺寸
    _RIGHT_PAD = 4   # 按钮距输入框右缘

    def __init__(self, placeholder: str = "搜索…", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)

        self._clear_btn = QToolButton(self)
        self._clear_btn.setObjectName("SearchClearButton")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setFocusPolicy(Qt.NoFocus)
        self._clear_btn.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        self._clear_btn.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self._clear_clicked)

        self.textChanged.connect(self._sync_clear_button)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetShortcut)
        esc.activated.connect(self._escape)

        self._refresh_icon()
        self._reposition()

    # ── 清除按钮 ──

    def _sync_clear_button(self, text: str):
        self._clear_btn.setVisible(bool(text))

    def _clear_clicked(self):
        self.clear()
        self.setFocus()

    def _escape(self):
        if self.text():
            self.clear()
        else:
            self.clearFocus()

    def _refresh_icon(self):
        self._clear_btn.setIcon(
            theme_manager.themed_icon("xmark", self._current_theme_id()))

    def _current_theme_id(self) -> str:
        """从祖先窗口读取当前主题 (EditorTabPane 同款向上查找)。"""
        widget = self.parentWidget()
        while widget is not None:
            theme_id = getattr(widget, "_theme_id", None)
            if theme_id is not None and str(theme_id) in theme_manager.THEMES:
                return str(theme_id)
            widget = widget.parentWidget()
        return theme_manager.load_initial_theme()

    # ── 几何 ──

    def _reposition(self):
        """把按钮贴到输入框内部右侧, 并为文本预留空间。"""
        self.setTextMargins(0, 0, self._BTN_SIZE + self._RIGHT_PAD + 2, 0)
        self._clear_btn.move(
            self.width() - self._BTN_SIZE - self._RIGHT_PAD,
            (self.height() - self._BTN_SIZE) // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def changeEvent(self, event):
        super().changeEvent(event)
        # 主题应用会向全部子控件传播调色板变化, 借此换深浅成对图标
        if event.type() == QEvent.Type.PaletteChange:
            self._refresh_icon()
