# -*- coding: utf-8 -*-
"""tks_book 图鉴标签页 — 游戏状态界面 1:1 复刻 (状态/技能/物品/装备/队伍/系统页)

无左侧列表 / 无 DockHeader: 直接居中展示 640×480 游戏界面复刻。
加载游戏目录后自动构建视图并选中花名册第 0 条角色。
支持等比例缩放: 100% / 200% / 300% / 自适应窗口。
缩放按钮由主窗口放置在标签栏右侧角落 (切换主题按钮左边)。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from game_status_view import GAME_H, GAME_W, GameStatusView


# 缩放模式
SCALE_100 = 1.0
SCALE_200 = 2.0
SCALE_300 = 3.0
SCALE_FIT = -1.0   # 自适应窗口


class GalleryTab(QWidget):
    """图鉴页: 直接展示游戏界面复刻"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self._roster_order = []
        self._game_view = None
        self._scale_mode = SCALE_FIT    # 默认自适应窗口
        self._scale_buttons = []       # 缩放按钮 (由主窗口放到角落区)
        self._build_scale_buttons()
        self._build_ui()

    def _build_scale_buttons(self):
        """创建缩放按钮 (不加入自身布局, 由主窗口放入标签栏角落)"""
        self._btn_100 = self._make_scale_btn("100%", SCALE_100)
        self._btn_200 = self._make_scale_btn("200%", SCALE_200)
        self._btn_300 = self._make_scale_btn("300%", SCALE_300)
        self._btn_fit = self._make_scale_btn("自适应", SCALE_FIT)
        self._scale_buttons = [self._btn_100, self._btn_200,
                               self._btn_300, self._btn_fit]
        self._update_scale_buttons()

    def scale_buttons(self):
        """返回缩放按钮列表, 供主窗口放入标签栏角落区"""
        return self._scale_buttons

    def _build_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        # 内容区 (游戏视图 / 占位提示)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._show_placeholder("请通过 文件 → 加载 TKS 目录 打开游戏数据")
        self._layout.addWidget(self._content, 1)

    def _make_scale_btn(self, text, mode):
        btn = QPushButton(text)
        btn.setProperty("class", "CompactBtn")
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self._set_scale_mode(mode))
        return btn

    def _update_scale_buttons(self):
        for btn, mode in ((self._btn_100, SCALE_100), (self._btn_200, SCALE_200),
                          (self._btn_300, SCALE_300), (self._btn_fit, SCALE_FIT)):
            btn.setChecked(self._scale_mode == mode)

    # ── 缩放 ──

    def _set_scale_mode(self, mode):
        self._scale_mode = mode
        self._update_scale_buttons()
        self._apply_scale()

    def _apply_scale(self):
        """按当前缩放模式调整视图大小"""
        if self._game_view is None:
            return
        if self._scale_mode == SCALE_FIT:
            scale = self._fit_scale()
        else:
            scale = self._scale_mode
        self._game_view.set_scale(scale)

    def _fit_scale(self):
        """计算自适应缩放: 等比例撑满内容区 (取宽高较小者, 保证不溢出)"""
        if self._game_view is None:
            return SCALE_100
        avail = self._content.rect()
        aw = avail.width() - 4    # 留少量边距避免贴边
        ah = avail.height() - 4
        if aw <= 0 or ah <= 0:
            return SCALE_100
        return max(0.1, min(aw / GAME_W, ah / GAME_H))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scale_mode == SCALE_FIT:
            self._apply_scale()

    def showEvent(self, event):
        super().showEvent(event)
        # 标签页首次显示时内容区尺寸才就绪, 补一次自适应计算
        if self._scale_mode == SCALE_FIT and self._game_view is not None:
            self._apply_scale()

    # ── 内容区管理 ──

    def _clear_content(self):
        """清空内容区所有子项 (包括嵌套 layout 及其子 widget)"""
        while self._content_layout.count() > 0:
            it = self._content_layout.takeAt(0)
            self._delete_item(it)
        self._game_view = None

    @staticmethod
    def _delete_item(item):
        """递归删除 QLayoutItem (widget 或子 layout)"""
        w = item.widget()
        if w is not None:
            w.deleteLater()
            return
        sub = item.layout()
        if sub is not None:
            while sub.count() > 0:
                GalleryTab._delete_item(sub.takeAt(0))
            sub.deleteLater()

    def _show_placeholder(self, text):
        self._clear_content()
        tip = QLabel(text)
        tip.setProperty("class", "StatusHint")
        tip.setAlignment(Qt.AlignCenter)
        self._content_layout.addWidget(tip, 1, Qt.AlignCenter)

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
        view.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._game_view = view

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(view)
        row.addStretch()
        self._content_layout.addLayout(row, 1)

        # 自动选中第 0 条角色
        if roster:
            view.show_char(roster[0])

        # 应用当前缩放
        self._apply_scale()

    def _on_game_view_char(self, warpc_idx):
        """游戏视图内点击头像行 → 切换显示该角色 (保持页面/子页签状态)"""
        if self._game_view is not None:
            self._game_view.show_char(warpc_idx)
