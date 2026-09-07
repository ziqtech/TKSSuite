#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TKS 游戏图鉴查看器 (PySide6 — Godot 风格)
=============================================================
只读查看器 (非编辑器): 加载 TKS 游戏目录后, 通过标签页浏览
图鉴 / 人物 / 技能 / 物品 / 地图 数据。
UI 样式对齐 kon_editor / skill_editor 的
PreviewFrame / DockHeader / DockBody 体系, 主题从 editor_themes/ 加载。
数据解析逻辑与各编辑器一致 (见 book_loader.py)。
"""
import os
import sys

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QMessageBox, QPushButton,
)
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))

from editor_utils import theme_manager
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.ui_helpers import update_path_labels
from editor_utils.version import format_title
from editor_utils.shared_state import pick_tks_directory
from editor_utils.task_runner import run_background, is_running

from book_loader import GameData
from tab_gallery import GalleryTab
from tab_char import CharTab
from tab_skill import SkillTab
from tab_item import ItemTab
from tab_status import StatusTab
from tab_map import MapTab
from tab_special import SpecialItemTab


class TksBookViewer(EditorMainWindow):
    EDITOR_KEY = "tks_book"
    DEFAULT_SIZE = (1320, 820)
    MIN_SIZE = (1000, 640)
    ABOUT_TITLE = "关于查看器"

    HELP_TEXT = (
        "TKS 游戏图鉴查看器 (只读, 不修改任何游戏文件)\n"
        "只读浏览 WarPC/TKSkill/TKItem/TKT/SC.GRP 数据, 不写入任何文件。\n\n"
        "1. 文件 → 加载 TKS 目录 (Ctrl+O), 选择游戏根目录\n"
        "2. 通过顶部标签页切换查看内容:\n"
        "   · 图鉴 — 游戏界面 1:1 复刻 (状态/技能/物品/装备/队伍/系统页)\n"
        "   · 人物 — 头像/核心属性/装备/技能/可学习技能树/历史\n"
        "   · 技能 — 名称/说明文本/有值属性/可学习角色\n"
        "   · 物品 — 图标/说明文本/有值属性/获得途径\n"
        "   · 状态 — 异常状态图标/名称/功能描述/来源与解除途径\n"
        "   · 地图 — 场景列表 + 背景预览 (首次切换时加载 SC.GRP)\n"
        "   · 特殊物品 — TKD 脚本 Attribute(-1,11,N) 收集度来源统计\n"
        "3. 左侧列表上方输入关键字可即时过滤\n"
        "4. F5 在深色/浅色主题间快速切换")

    def _init_data(self):
        self.data = GameData()
        self._loaded = False

    def _after_build(self):
        self._apply_theme()
        self._sync_corner_height()

    # ── 主题 ──

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        # tks_book 采用 QApplication 级样式表，让无父窗口的弹窗也继承主题
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)

    def _sync_corner_height(self):
        """角落按钮高度对齐标签栏 (QSS 生效后计算, 避免顶部被裁剪)"""
        h = self.tabs.tabBar().sizeHint().height()
        if h > 0:
            # Tab 线实际位于 TabBar 底部内侧，再留 1px 避免角落按钮覆盖它。
            bh = max(20, h - 3)
            self._btn_theme.setFixedHeight(bh)
            for btn in self._scale_buttons:
                btn.setFixedHeight(bh)

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)
        self._sync_corner_height()
        self._update_paths()
        # 技能树拓扑图配色随主题重绘 (重选当前角色即按新主题重建)
        cur = self.tab_char.list_widget.currentItem()
        if cur is not None:
            self.tab_char.show_detail(cur.data(Qt.UserRole))

    # ── UI ──

    def _build_ui(self):
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录", QKeySequence("Ctrl+O"), self._load_tks_dir)
        self.attach_recent_dirs_menu(fm)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        vm = mb.addMenu("视图(&V)")
        self.add_theme_submenu(vm)
        vm.addAction("快速切换主题(&T)\tF5", self._toggle_theme)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于查看器", self._show_about)

        QShortcut("F5", self).activated.connect(self._toggle_theme)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # 标签页
        self.tabs = EditorTabWidget(
            flat=True,
            object_name="TksBookTabs",
        )
        self.tab_gallery = GalleryTab(self.data)
        self.tab_char = CharTab(self.data)
        self.tab_skill = SkillTab(self.data)
        self.tab_item = ItemTab(self.data)
        self.tab_status = StatusTab(self.data)
        self.tab_map = MapTab(self.data)
        self.tab_special = SpecialItemTab(self.data)
        self.tabs.addTab(self.tab_gallery, "图鉴")
        self.tabs.addTab(self.tab_char, "人物")
        self.tabs.addTab(self.tab_skill, "技能")
        self.tabs.addTab(self.tab_item, "物品")
        self.tabs.addTab(self.tab_status, "状态")
        self.tabs.addTab(self.tab_map, "地图")
        self.tabs.addTab(self.tab_special, "特殊物品")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 标签页右侧按钮区: 缩放按钮 (仅图鉴页显示) + 切换主题
        self._scale_buttons = self.tab_gallery.scale_buttons()
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)
        for btn in self._scale_buttons:
            btn.setParent(corner)
            cl.addWidget(btn)
        self._btn_theme = QPushButton("切换主题")
        self._btn_theme.setToolTip("在深色/浅色主题间快速切换 (F5)")
        self._btn_theme.clicked.connect(self._toggle_theme)
        cl.addWidget(self._btn_theme)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        self._corner_scale_parent = corner

        # 初始: 图鉴页是第一个标签, 显示缩放按钮
        for btn in self._scale_buttons:
            btn.show()

        main_layout.addWidget(self.tabs, 1)

        # 底部路径栏 (与 item/warpc 等主流编辑器统一)
        # 路径标签不设 objectName: 让 update_path_labels 写入的 [status] 属性
        # 生效着色 (绿=已加载 / 橙=缺失 / 灰=未加载)。若设 #hintLabel,
        # ID 选择器优先级高于 [status] 会把状态色盖成灰色 (kon_editor 的旧问题)。
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_tkt = QLabel("TKT.dat: 未加载")
        self.lbl_warpc = QLabel("WarPC.dat: 未加载")
        self.lbl_skill = QLabel("TKSkill.dat: 未加载")
        self.lbl_item = QLabel("TKItem.dat: 未加载")
        self.lbl_grp = QLabel("SC.GRP: 未加载")
        path_labels = (self.lbl_tkt, self.lbl_warpc, self.lbl_skill,
                       self.lbl_item, self.lbl_grp)
        for i, lbl in enumerate(path_labels):
            if i > 0:
                path_layout.addSpacing(20)
            path_layout.addWidget(lbl)
        path_layout.addStretch()
        # 右侧操作提示文字用 hintLabel (灰色小字), 与各编辑器一致
        self.status_label = QLabel("请通过 文件 → 加载 TKS 目录 打开游戏数据")
        self.status_label.setObjectName("hintLabel")
        path_layout.addWidget(self.status_label)
        main_layout.addLayout(path_layout)

    # ── 数据加载 ──

    def _load_tks_dir(self):
        d = pick_tks_directory(self)
        if d:
            self.load_tks_dir(d)

    def load_tks_dir(self, d):
        # 主文件校验: 查看器至少需要 TKT.dat (所有名称/文本的来源)
        if not os.path.exists(os.path.join(d, "TKT.dat")):
            themed_messagebox(self, QMessageBox.Warning, "文件缺失",
                                f"所选目录未找到 TKT.dat:\n{d}\n\n"
                                f"请选择 TKS 游戏根目录。")
            return
        if is_running(getattr(self, '_load_worker', None)):
            return
        self.status_label.setText("加载中…")

        # 后台线程: 全量数据文件 IO/解码 (P3-3), UI 填充在回调
        def work(w):
            self.data.load(d)
            return d

        self._load_worker = run_background(
            self, work,
            on_success=self._on_load_success,
            on_error=self._on_load_error)

    def _on_load_success(self, d):
        self._loaded = True
        self.tab_gallery.populate()
        self.tab_char.populate()
        self.tab_skill.populate()
        self.tab_item.populate()
        self.tab_status.populate()
        self.tab_map.populate()
        self.tab_special.populate()
        if self.tabs.currentWidget() is self.tab_map:
            self.tab_map.ensure_populated()
        self._update_paths()
        self.setWindowTitle(format_title("tks_book", os.path.basename(d.rstrip('/\\'))))
        self.status_label.setText(
            f"角色 {sum(1 for r in self.data.warpc_recs if self.data.char_name(r))} | "
            f"技能 {len(self.data.skill_names)} | "
            f"物品 {len(self.data.item_by_id)} | "
            f"TKT {len(self.data.tkt)} 条")

    def _on_load_error(self, err_msg):
        themed_messagebox(self, QMessageBox.Critical, "加载失败", err_msg)

    def _on_tab_changed(self, _index):
        # 缩放按钮仅在图鉴页显示
        is_gallery = self.tabs.currentWidget() is self.tab_gallery
        for btn in self._scale_buttons:
            btn.setVisible(is_gallery)
        # 地图页惰性加载 SC.GRP (文件大, 避免拖慢初始加载)
        if self._loaded and self.tabs.currentWidget() is self.tab_map:
            self.tab_map.ensure_populated()
            self._update_paths()

    def _update_paths(self):
        d = self.data.game_dir

        def _p(name):
            return os.path.join(d, name) if d else None

        update_path_labels([
            (self.lbl_tkt, _p("TKT.dat"), "TKT.dat"),
            (self.lbl_warpc, _p("WarPC.dat"), "WarPC.dat"),
            (self.lbl_skill, _p("TKSkill.dat"), "TKSkill.dat"),
            (self.lbl_item, _p("TKItem.dat"), "TKItem.dat"),
            (self.lbl_grp, _p("SC.GRP"), "SC.GRP"),
        ], self._is_dark)

    # ── 帮助 ──


def main():
    run_editor(TksBookViewer, "TKS Book")


if __name__ == '__main__':
    main()
