#!/usr/bin/env python3
"""
TKS Configs Editor — 配置文件可视化编辑器
为 configs/ 目录下的 JSON 配置文件提供面向普通用户的可视化编辑工具。
"""
import sys
import os
import struct
from pathlib import Path

# ── runtime bootstrap (必须在 PySide6 导入前) ──
_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_EDITOR_DIR, '..'))  # 
sys.path.insert(0, _EDITOR_DIR)                       # configs_editor/
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QFileDialog, QMessageBox,
    QStatusBar, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon

from editor_utils.theme_manager import ThemeManager
from editor_utils.ui_helpers import confirm_close, update_path_labels
from editor_utils.app_init import install_translator, setup_app_icon
from editor_utils.lzss import lzss_decompress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.jvg_loader import load_mu_sprites

from panels import PANEL_REGISTRY


# ── WarPC 数据加载 ──

WARPC_FIELD_COUNT = 527
WARPC_REC_SIZE = 1054  # 527 × 2


def load_warpc_records(warpc_path: str):
    """加载 WarPC.dat，返回 list[dict]。
    每条: {'index': i, 'fields': [f0, f1, ...]}
    fields[0] = name_id, fields[1] = portrait
    """
    with open(warpc_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    if not dec or len(dec) % WARPC_REC_SIZE != 0:
        return []
    count = len(dec) // WARPC_REC_SIZE
    records = []
    for i in range(count):
        off = i * WARPC_REC_SIZE
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        records.append({'index': i, 'fields': list(vals)})
    return records


SKILL_REC = 94  # TKSkill.dat 每条记录 94 字节 (47 × int16)


def load_skill_names(skill_path: str, tkt_names: dict) -> dict:
    """加载 TKSkill.dat，返回 {skill_num: skill_name}。
    参照 skill_editor_v2.py 的 SKILL_REC=94, SKILL_CNT=350 格式。
    """
    with open(skill_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    if not dec or len(dec) < SKILL_REC:
        return {}
    result = {}
    count = len(dec) // SKILL_REC
    for i in range(count):
        off = i * SKILL_REC
        vals = struct.unpack_from('<' + 'h' * 47, dec, off)
        text_id = vals[0]  # skill_text_id @ offset 0
        if text_id and text_id in tkt_names:
            result[i] = tkt_names[text_id]
        elif text_id:
            result[i] = f"技能{text_id}"
    return result


class ConfigsEditorWindow(QMainWindow):
    """主窗口 — 菜单栏 + 工具栏 + QTabWidget + 状态栏"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKS Configs Editor")
        self.resize(900, 650)
        self.setMinimumSize(700, 500)

        # 配置目录 — Nuitka onefile 下 __file__ 指向临时目录, 需用 exe 所在目录
        if getattr(sys, 'frozen', False) or "__compiled__" in globals():
            from editor_utils.runtime_bootstrap import get_app_dir
            self._configs_dir = Path(get_app_dir()) / "configs"
        else:
            self._configs_dir = Path(__file__).parent.parent / "configs"

        # 游戏数据
        self._war_pc_records = []
        self._tkt_names = {}
        self._fa_sprites = []
        self._skill_names = {}
        self._game_data_loaded = False
        self._tks_dir = None

        # 主题
        app_inst = QApplication.instance()
        self._is_dark = (app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark
                         if app_inst else True)

        # 面板列表
        self._panels = []

        self._build_ui()
        self._load_panels()
        self._update_window_title()

        # 应用主题
        self._apply_theme()

    # ── UI 构建 ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 菜单栏 ──
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")

        act_load = QAction("加载 TKS 目录…", self)
        act_load.setShortcut("Ctrl+O")
        act_load.triggered.connect(self.load_tks_directory)
        file_menu.addAction(act_load)

        act_save = QAction("保存", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.save_all)
        file_menu.addAction(act_save)

        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = menubar.addMenu("帮助(&H)")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

        # ── 工具栏 ──
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(8)

        # 配置目录标签
        self._config_dir_label = QLabel()
        self._config_dir_label.setObjectName("ConfigDirLabel")
        tb_layout.addWidget(self._config_dir_label)

        tb_layout.addSpacing(12)

        # 保存按钮
        self._btn_save = QPushButton("💾 保存")
        self._btn_save.clicked.connect(self.save_all)
        tb_layout.addWidget(self._btn_save)

        # 加载 TKS 目录按钮
        self._btn_load_tks = QPushButton("📂 加载TKS目录")
        self._btn_load_tks.clicked.connect(self.load_tks_directory)
        tb_layout.addWidget(self._btn_load_tks)

        tb_layout.addStretch()

        # 主题切换按钮
        self._btn_theme = QPushButton("🌗 切换主题")
        self._btn_theme.clicked.connect(self._toggle_theme)
        tb_layout.addWidget(self._btn_theme)

        layout.addWidget(toolbar)

        # ── QTabWidget ──
        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget, 1)

        # ── 状态栏 ──
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self._status_warpc = QLabel("WarPC.dat — ")
        self._status_warpc.setObjectName("StatusWarpcLabel")
        self._status_tkt = QLabel("TKT.dat — ")
        self._status_tkt.setObjectName("StatusTktLabel")
        self._status_fa = QLabel("Fa.JVG — ")
        self._status_fa.setObjectName("StatusFaLabel")
        self._status_skill = QLabel("TKSkill.dat — ")
        self._status_skill.setObjectName("StatusSkillLabel")
        for lbl in [self._status_warpc, self._status_tkt, self._status_fa, self._status_skill]:
            status_bar.addWidget(lbl)

        status_bar.addPermanentWidget(QLabel("TKS Configs Editor"))

        self._update_config_dir_label()
        self._update_status_bar()

    def _load_panels(self):
        """扫描 PANEL_REGISTRY，实例化面板并加入 QTabWidget。"""
        self._tab_widget.clear()
        self._panels = []

        for panel_cls in PANEL_REGISTRY:
            panel = panel_cls(self)
            panel.modified.connect(lambda p=panel: self._on_panel_modified(p))
            loaded = panel.load(self._configs_dir)
            self._panels.append(panel)

            tab_title = panel.tab_label
            if not loaded:
                tab_title += " (缺失)"
            self._tab_widget.addTab(panel, tab_title)

    def _on_panel_modified(self, panel):
        """面板内容修改时更新标签页标题。"""
        idx = self._panels.index(panel)
        if idx < 0:
            return
        tab_title = panel.tab_label
        if panel.is_modified():
            tab_title = f"{panel.tab_label} *"
        self._tab_widget.setTabText(idx, tab_title)

    def _update_tab_titles(self):
        """刷新所有标签页标题。"""
        for i, panel in enumerate(self._panels):
            tab_title = panel.tab_label
            if panel.is_modified():
                tab_title = f"{panel.tab_label} *"
            if not panel.is_loaded:
                tab_title = f"{panel.tab_label} (缺失)"
            self._tab_widget.setTabText(i, tab_title)

    # ── 保存 ──

    def save_all(self):
        """保存所有已修改的配置。"""
        saved = 0
        errors = []
        for panel in self._panels:
            if panel.is_loaded and panel.is_modified():
                if panel.save():
                    saved += 1
                else:
                    errors.append(panel.config_name)

        if errors:
            QMessageBox.critical(self, "保存失败", f"以下配置保存失败:\n{', '.join(errors)}")
        elif saved > 0:
            QMessageBox.information(self, "保存成功", f"已保存 {saved} 个配置文件")

        self._update_tab_titles()

    # ── TKS 目录加载 ──

    def load_tks_directory(self):
        """加载 TKS 游戏目录: WarPC.dat + TKT.dat + Fa.JVG。"""
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d:
            return

        warpc_path = os.path.join(d, "WarPC.dat")
        tkt_path = os.path.join(d, "TKT.dat")
        fa_path = os.path.join(d, "Fa.JVG")

        if not os.path.exists(warpc_path):
            QMessageBox.warning(self, "文件缺失", "未找到 WarPC.dat")
            return

        # 加载 WarPC.dat
        try:
            self._war_pc_records = load_warpc_records(warpc_path)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"WarPC.dat 加载失败:\n{e}")
            return

        # 加载 TKT.dat
        self._tkt_names = {}
        if os.path.exists(tkt_path):
            try:
                self._tkt_names = load_tkt_simple(tkt_path)
            except Exception:
                pass

        # 加载 Fa.JVG
        self._fa_sprites = []
        if os.path.exists(fa_path):
            try:
                self._fa_sprites = load_mu_sprites(fa_path) or []
            except Exception:
                pass

        # 加载 TKSkill.dat (技能名称)
        self._skill_names = {}
        skill_path = os.path.join(d, "TKSkill.dat")
        if os.path.exists(skill_path):
            try:
                self._skill_names = load_skill_names(skill_path, self._tkt_names)
            except Exception:
                pass

        self._game_data_loaded = bool(self._war_pc_records)
        self._tks_dir = d

        # 更新状态栏
        self._update_status_bar()

        # 传递给所有面板
        for panel in self._panels:
            panel.set_game_data(self._war_pc_records, self._tkt_names,
                                self._fa_sprites, self._skill_names)

        QMessageBox.information(self, "加载成功",
            f"已加载 TKS 目录:\n"
            f"  WarPC.dat: {len(self._war_pc_records)} 角色\n"
            f"  TKT.dat: {len(self._tkt_names)} 条文本\n"
            f"  Fa.JVG: {len(self._fa_sprites)} 个精灵\n"
            f"  TKSkill.dat: {len(self._skill_names)} 个技能名称")

    # ── 样式刷新 ──

    @staticmethod
    def _apply_label_status(label, status):
        """为 QLabel 设置 status 动态属性并刷新样式。
        status: 'loaded' | 'missing' | 'unloaded'
        """
        label.setProperty("status", status)
        label.style().unpolish(label)
        label.style().polish(label)

    # ── 状态栏更新 ──

    def _update_status_bar(self):
        """更新状态栏的游戏数据加载状态。"""
        if not self._tks_dir:
            self._status_warpc.setText("WarPC.dat — ")
            self._status_tkt.setText("TKT.dat — ")
            self._status_fa.setText("Fa.JVG — ")
            self._status_skill.setText("TKSkill.dat — ")
            for lbl in [self._status_warpc, self._status_tkt, self._status_fa, self._status_skill]:
                self._apply_label_status(lbl, "unloaded")
        else:
            warpc_path = os.path.join(self._tks_dir, "WarPC.dat")
            tkt_path = os.path.join(self._tks_dir, "TKT.dat")
            fa_path = os.path.join(self._tks_dir, "Fa.JVG")
            skill_path = os.path.join(self._tks_dir, "TKSkill.dat")

            self._set_status_label(self._status_warpc, "WarPC.dat", warpc_path)
            self._set_status_label(self._status_tkt, "TKT.dat", tkt_path)
            self._set_status_label(self._status_fa, "Fa.JVG", fa_path)
            self._set_status_label(self._status_skill, "TKSkill.dat", skill_path)

    def _set_status_label(self, label, name, path):
        if os.path.exists(path):
            label.setText(f"{name} ✓ ")
            self._apply_label_status(label, "loaded")
        else:
            label.setText(f"{name} ✗ ")
            self._apply_label_status(label, "missing")

    def _update_config_dir_label(self):
        """更新配置目录路径标签。"""
        if self._configs_dir.exists():
            self._config_dir_label.setText(f"📁 配置目录: {self._configs_dir}")
            self._apply_label_status(self._config_dir_label, "loaded")
        else:
            self._config_dir_label.setText(f"📁 配置目录: (不存在) {self._configs_dir}")
            self._apply_label_status(self._config_dir_label, "missing")

    def _update_window_title(self):
        if self._tks_dir:
            self.setWindowTitle(f"TKS Configs Editor - [{self._tks_dir}]")
        else:
            self.setWindowTitle(f"TKS Configs Editor - [{self._configs_dir}]")

    # ── 主题 ──

    def _apply_theme(self):
        ThemeManager.apply_theme(self, 'dark' if self._is_dark else 'light')
        from editor_utils.window_theme import apply_godot_theme
        apply_godot_theme(self, self._is_dark)

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        # 重新加载面板（刷新表格颜色等）
        for panel in self._panels:
            if hasattr(panel, '_refresh_table'):
                panel._refresh_table()

    # ── 关闭确认 ──

    def closeEvent(self, event):
        any_modified = any(p.is_loaded and p.is_modified() for p in self._panels)
        if any_modified:
            reply = QMessageBox.question(
                self, "未保存的修改",
                "有未保存的修改，确定退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()

    # ── 关于 ──

    def _show_about(self):
        QMessageBox.about(self, "关于",
            "TKS Configs Editor\n\n"
            "为 TKS 游戏配置文件提供可视化编辑工具。\n"
            "支持: 掉落概率、装备类型标签、召唤表")


def main():
    from editor_utils.app_init import install_translator, setup_app_icon

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("TKS Configs Editor")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))

    window = ConfigsEditorWindow()

    # 检测系统主题并应用
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    ThemeManager.apply_theme(window, 'dark' if is_dark else 'light')

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
