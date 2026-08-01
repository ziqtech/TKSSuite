# -*- coding: utf-8 -*-
"""tks_book 图鉴标签页 — 游戏状态界面 1:1 复刻 (状态/技能/物品/装备/队伍/系统页)

无左侧列表 / 无 DockHeader: 直接居中展示 640×480 游戏界面复刻。
加载游戏目录后自动构建视图并选中花名册第 0 条角色。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from game_status_view import GameStatusView


class GalleryTab(QWidget):
    """图鉴页: 直接展示游戏界面复刻"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self._roster_order = []
        self._game_view = None
        self._build_ui()

    def _build_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._show_placeholder("请通过 文件 → 加载 TKS 目录 打开游戏数据")

    # ── 内容区管理 ──

    def _clear_content(self):
        """清空内容区所有子项 (widget / 子 layout)"""
        while self._layout.count() > 0:
            it = self._layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = it.layout()
                if sub is not None:
                    self._clear_layout(sub)
        self._game_view = None

    @staticmethod
    def _clear_layout(layout):
        while layout.count() > 0:
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = it.layout()
                if sub is not None:
                    GalleryTab._clear_layout(sub)

    def _show_placeholder(self, text):
        tip = QLabel(text)
        tip.setProperty("class", "StatusHint")
        tip.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(tip, 1, Qt.AlignCenter)

    # ── 数据加载 ──

    def populate(self):
        """数据加载后构建游戏视图并自动选中花名册第 0 条角色"""
        self._clear_content()

        # 花名册 (与 tab_char 同序: 跳过空槽)
        roster = [rec['index'] for rec in self.data.warpc_recs
                  if self.data.char_name(rec)]
        self._roster_order = roster

        view = GameStatusView()
        view.set_data(self.data)
        if not view.available():
            view.deleteLater()
            self._show_placeholder("(缺少 mb.gxp 或 Mu.JVG 资源, 无法显示游戏界面)")
            return

        view.set_roster(roster)
        view.charClicked.connect(self._on_game_view_char)
        self._game_view = view

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(view)
        row.addStretch()
        self._layout.addLayout(row, 1)

        # 自动选中第 0 条角色
        if roster:
            view.show_char(roster[0])

    def _on_game_view_char(self, warpc_idx):
        """游戏视图内点击头像行 → 切换显示该角色 (保持页面/子页签状态)"""
        if self._game_view is not None:
            self._game_view.show_char(warpc_idx)
