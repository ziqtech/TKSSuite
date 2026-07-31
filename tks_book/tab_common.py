# -*- coding: utf-8 -*-
"""tks_book 标签页公共组件 — 左侧搜索列表 + 右侧详情滚动区 (Dock 风格)"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLineEdit, QListWidget,
    QListWidgetItem, QScrollArea, QLabel, QGridLayout, QPushButton,
)

from editor_utils.dock_components import DockHeader


class BookTabBase(QWidget):
    """查看器标签页基类: 左列表 (搜索过滤) + 右详情。

    子类实现:
      populate()          — 数据加载后重建列表 (调用 set_list_items)
      show_detail(key)    — 选中列表项后渲染右侧详情
    """

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data          # GameData (共享引用, 由主窗口加载)
        self._items = []          # [(key, display_text), ...] 全量
        self._build_ui()

    # ── UI 骨架 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        # 左: 搜索 + 列表
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索…")
        self.search_input.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_input, 1)
        btn_clear = QPushButton("✕")
        btn_clear.setProperty("class", "CompactBtn")  # 紧凑内边距, 避免 ✕ 被裁剪
        btn_clear.setToolTip("清除搜索")
        btn_clear.setFixedWidth(28)
        btn_clear.clicked.connect(self.search_input.clear)
        search_row.addWidget(btn_clear)
        ll.addLayout(search_row)
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(24, 24))
        self.list_widget.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list_widget, 1)
        splitter.addWidget(left)

        # 右: 详情滚动区
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self._detail_container = QWidget()
        self.detail_layout = QVBoxLayout(self._detail_container)
        self.detail_layout.setContentsMargins(8, 4, 8, 8)
        self.detail_layout.setSpacing(4)
        self.detail_layout.addStretch()
        self.detail_scroll.setWidget(self._detail_container)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([300, 720])
        self._splitter = splitter

    # ── 列表管理 ──

    def set_list_items(self, items):
        """items: [(key, display_text, icon_or_None), ...]"""
        self._items = items
        self._apply_filter()

    def _apply_filter(self):
        q = self.search_input.text().strip().lower()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for entry in self._items:
            key, text = entry[0], entry[1]
            icon = entry[2] if len(entry) > 2 else None
            if q and q not in text.lower():
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, key)
            if icon is not None:
                item.setIcon(icon)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _on_select(self, current, _previous=None):
        if current is None:
            return
        self.show_detail(current.data(Qt.UserRole))

    # ── 详情构建辅助 ──

    def clear_detail(self):
        """清空右侧详情区 (保留末尾 stretch)"""
        while self.detail_layout.count() > 0:
            it = self.detail_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def finish_detail(self):
        self.detail_layout.addStretch()

    def add_group(self, title):
        """添加 DockHeader + DockBody 分组, 返回 body 的 QVBoxLayout"""
        group_w = QWidget()
        gl = QVBoxLayout(group_w)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(title))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(4)
        gl.addWidget(body)
        self.detail_layout.addWidget(group_w)
        return bl

    def add_kv_grid(self, body_layout, pairs, cols=3):
        """在分组内添加 键: 值 网格。pairs: [(label, value_text), ...]"""
        grid = QGridLayout()
        grid.setVerticalSpacing(3)
        grid.setHorizontalSpacing(6)
        for i, (label, value) in enumerate(pairs):
            r, c = divmod(i, cols)
            lbl = QLabel(f"{label}")
            lbl.setProperty("class", "PropLabel")
            val = QLabel(str(value))
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setWordWrap(True)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lbl)
            cell.addWidget(val, 1)
            grid.addLayout(cell, r, c)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        body_layout.addLayout(grid)

    def add_text_block(self, body_layout, text, css_class="PreviewDesc"):
        lbl = QLabel(text if text else "(无)")
        lbl.setProperty("class", css_class)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body_layout.addWidget(lbl)
        return lbl

    # ── 子类接口 ──

    def populate(self):
        raise NotImplementedError

    def show_detail(self, key):
        raise NotImplementedError
