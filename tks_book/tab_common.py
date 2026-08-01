# -*- coding: utf-8 -*-
"""tks_book 标签页公共组件 — 左侧搜索表格 + 右侧详情滚动区 (Dock 风格)"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QLabel, QGridLayout, QPushButton,
)

import zhconv

from editor_utils.dock_components import DockHeader


class BookTabBase(QWidget):
    """查看器标签页基类: 左表格 (搜索过滤) + 右详情。

    子类实现:
      populate()          — 数据加载后重建表格 (调用 set_table_items)
      show_detail(key)    — 选中表格行后渲染右侧详情
    """

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data          # GameData (共享引用, 由主窗口加载)
        self._headers = []        # 列标题
        self._rows = []           # [(key, [cell, ...]), ...] 全量
        self._widths = None       # {col: pixel_width} 非拉伸列像素宽
        self._stretch_col = None  # 拉伸列索引 (占用剩余空间)
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
        self.list_widget = QTableWidget()
        self.list_widget.setIconSize(QSize(24, 24))
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.horizontalHeader().setStretchLastSection(True)
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
        splitter.setSizes([420, 780])
        self._splitter = splitter

    # ── 表格管理 ──

    def set_table_items(self, headers, rows, widths=None, stretch_col=None):
        """重建左侧表格。

        headers:    [str, ...] 列标题
        rows:       [(key, [cell, ...]), ...] 每行单元格;
                    cell 为 str (纯文本) 或 (text, icon_or_None) (带图标)
        widths:     可选 {col: pixel_width} 非拉伸列像素宽
        stretch_col: 可选列索引, 该列占用剩余空间 (Stretch 模式);
                     未指定时由末列撑满 (StretchLastSection)
        """
        self._headers = list(headers)
        self._rows = rows
        self._widths = widths
        self._stretch_col = stretch_col
        self._apply_filter()

    @staticmethod
    def _normalize_cell(cell):
        """单元格归一化: str → (str, None); (text, icon) 原样"""
        if isinstance(cell, tuple):
            return cell[0], cell[1]
        return cell, None

    def _apply_filter(self):
        q = self.search_input.text().strip().lower()
        # 将简体转为繁体以匹配游戏数据（Big5编码的繁体中文）
        q_tw = zhconv.convert(q, 'zh-tw') if q else ''
        tw = self.list_widget
        tw.blockSignals(True)
        tw.setRowCount(0)
        ncol = len(self._headers)
        tw.setColumnCount(ncol)
        tw.setHorizontalHeaderLabels(self._headers)
        for key, cells in self._rows:
            norms = [self._normalize_cell(c) for c in cells]
            texts = [n[0] for n in norms]
            if q and not any(q_tw in "".join((t or "").lower().split()) for t in texts):
                continue
            row = tw.rowCount()
            tw.insertRow(row)
            for col, (text, icon) in enumerate(norms):
                item = QTableWidgetItem(str(text) if text is not None else "")
                item.setData(Qt.UserRole, key)
                if icon is not None:
                    item.setIcon(icon)
                    item.setTextAlignment(Qt.AlignCenter)
                elif text and str(text).strip().lstrip("-").isdigit():
                    # 纯数字列右对齐 (# / ID 等)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tw.setItem(row, col, item)
        # 列宽 / 拉伸模式
        header = tw.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        if self._stretch_col is not None and self._stretch_col < ncol:
            header.setSectionResizeMode(self._stretch_col, QHeaderView.Stretch)
            header.setStretchLastSection(False)
        else:
            header.setStretchLastSection(True)
        if self._widths:
            for col, w in self._widths.items():
                if col < ncol:
                    tw.setColumnWidth(col, w)
        tw.blockSignals(False)

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

    def add_group(self, title, stretch=0):
        """添加 DockHeader + DockBody 分组, 返回 body 的 QVBoxLayout。
        stretch>0 时该分组在 detail_layout 中占用对应拉伸因子 (填满剩余空间)。
        """
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
        gl.addWidget(body, 1 if stretch else 0)
        self.detail_layout.addWidget(group_w, stretch)
        return bl

    def add_group_pair(self, title1, title2):
        """创建两个并排的 DockHeader 分组 (一行显示), 返回 (body1_layout, body2_layout)"""
        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(4)
        bodies = []
        for title in (title1, title2):
            gw = QWidget()
            gl = QVBoxLayout(gw)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
            gl.addWidget(DockHeader(title))
            bw = QWidget()
            bw.setObjectName("DockBody")
            bl = QVBoxLayout(bw)
            bl.setContentsMargins(8, 8, 8, 8)
            bl.setSpacing(4)
            gl.addWidget(bw, 1)
            row_l.addWidget(gw, 1)
            bodies.append(bl)
        self.detail_layout.addWidget(row_w)
        return tuple(bodies)

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
