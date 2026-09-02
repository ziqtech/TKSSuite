#!/usr/bin/env python3
"""
TKS Configs Editor — 配置文件可视化编辑器
为 configs/ 目录下的 JSON 配置文件提供面向普通用户的可视化编辑工具。
"""
import os
import struct
import sys
from functools import partial
from pathlib import Path

# ── runtime bootstrap (必须在 PySide6 导入前) ──
_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_EDITOR_DIR, '..'))  # 
sys.path.insert(0, _EDITOR_DIR)                       # configs_editor/
from editor_utils.runtime_bootstrap import bootstrap
bootstrap()

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox,
    QStatusBar, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction

from editor_utils.theme_switcher import toggle_theme_in_family
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.ui_helpers import confirm_close, update_path_labels
from editor_utils.lzss import lzss_decompress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.version import format_title
from editor_utils.shared_state import pick_tks_directory
from editor_utils.jvg_loader import load_mu_sprites
from editor_utils.mod_exporter import (
    generate_mod_json, pack_tksmod, ModMetadataDialog, safe_mod_filename,
)

from panels import PANEL_REGISTRY

# 允许通过 MOD 包携带的启动器配置文件白名单 (与 mod_loader.MOD_ALLOWED_CONFIGS 一致)
_CONFIGS_ALLOWED_IN_MOD = {"summon_table", "drop_probability"}

# 主窗口默认尺寸。
# 高度需容纳最高的「动画速度」面板全部分组: 内容 744px + 窗口装饰
# (菜单栏 29 + 工具栏 + 标签栏 38 + 状态栏 22 + 各处边距) 154px ≈ 898px,
# 再留 22px 余量以应对字体/DPI 差异。宽度不影响内容高度 (面板为纵向布局),
# 取 960 已远超内容所需的最小宽度 (约 500px)。
DEFAULT_WINDOW_WIDTH = 960
DEFAULT_WINDOW_HEIGHT = 920


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
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % WARPC_REC_SIZE == 0 and (len(dec) == 0 or len(dec) % WARPC_REC_SIZE != 0):
        dec = raw
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
    参照 skill_editor.py 的 SKILL_REC=94, SKILL_CNT=350 格式。
    """
    with open(skill_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % SKILL_REC == 0 and (len(dec) == 0 or len(dec) % SKILL_REC != 0):
        dec = raw
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


class ConfigsEditorWindow(EditorMainWindow):
    """主窗口 — 菜单栏 + 工具栏 + EditorTabWidget + 状态栏"""

    EDITOR_KEY = "configs_editor"
    DEFAULT_SIZE = (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    MIN_SIZE = (700, 500)

    HELP_TEXT = (
        "为 TKS 游戏配置文件提供可视化编辑工具。\n"
        "支持: 掉落概率、装备类型标签、召唤表")

    def _init_data(self):
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

        # 面板列表
        self._panels = []

    def _after_build(self):
        self._load_panels()
        self._update_window_title()

        # 应用主题
        self._apply_theme()

        # 居中须在 UI 构建完成后调用: 此时平台窗口已创建,
        # frameGeometry() 才能拿到真实的标题栏+边框高度, 否则会偏低半个标题栏 (约 16px)。
        self._center_window()

    def _center_window(self):
        """将窗口居中到主屏幕可用区域 (排除任务栏)。

        用 frameGeometry() 而非 geometry(), 使含标题栏与边框的整个窗口居中;
        availableGeometry().center() 自带屏幕原点偏移, 多屏且主屏不在 (0,0) 时同样正确。
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(screen.availableGeometry().center())
        self.move(geo.topLeft())

    # ── UI 构建 ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

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
        act_export_mod = QAction("导出为 MOD (.tksmod)…", self)
        act_export_mod.triggered.connect(self._export_tksmod)
        file_menu.addAction(act_export_mod)

        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        self.add_standard_menus(menubar)

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

        # ── 通用编辑器标签页 ──
        self._tab_widget = EditorTabWidget(
            flat=True,
            object_name="ConfigsEditorTabs",
        )
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
        """扫描 PANEL_REGISTRY，实例化面板并加入 EditorTabWidget。"""
        self._tab_widget.clear()
        self._panels = []

        for panel_cls in PANEL_REGISTRY:
            panel = panel_cls(self)
            panel.modified.connect(partial(self._on_panel_modified, panel))
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

    # ── MOD 导出 ──

    def _export_tksmod(self):
        """将白名单内的配置文件 (summon_table, drop_probability) 导出为 .tksmod。
        MOD 包中携带的配置文件优先级最高，覆盖 configs/ 目录同名文件。
        """
        # 收集已加载的白名单配置面板
        exportable = []
        for panel in self._panels:
            if panel.is_loaded and panel.config_name in _CONFIGS_ALLOWED_IN_MOD:
                exportable.append(panel)

        if not exportable:
            QMessageBox.warning(self, "无法导出",
                "没有可导出的配置文件。\n"
                "仅 summon_table 和 drop_probability 可通过 MOD 包携带，\n"
                "请确保对应配置文件已加载。")
            return

        # 收集配置数据
        config_files = {}   # {internal_path: dict_content}
        configs_meta = []   # [{"file": ..., "name": ...}]
        names_summary = []
        for panel in exportable:
            data = panel.get_current_data()
            if data is None:
                continue
            internal = f"configs/{panel.config_name}.json"
            config_files[internal] = data
            configs_meta.append({"file": internal, "name": panel.config_name})
            names_summary.append(panel.config_name)

        if not config_files:
            QMessageBox.warning(self, "无法导出", "未能收集到任何配置数据。")
            return

        # 弹出元数据对话框
        dlg = ModMetadataDialog(self, defaults={
            "id": f"configs_{len(config_files)}",
            "name": f"配置MOD ({', '.join(names_summary)})",
        })
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        metadata = dlg.get_metadata()

        # 选择保存路径
        default_name = safe_mod_filename(metadata.get("name", "configs_mod"),
                                         metadata.get("id", "configs_mod"))
        default_path = os.path.join(os.path.expanduser("~"), f"{default_name}.tksmod")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 MOD", default_path, "TKS MOD (*.tksmod)")
        if not save_path:
            return
        if not save_path.lower().endswith(".tksmod"):
            save_path += ".tksmod"

        # 生成 mod.json (无数据组件, 无资源, 仅配置文件)
        mod_json = generate_mod_json(
            metadata, components=[], resources=None, configs=configs_meta)

        # 打包
        try:
            pack_tksmod(save_path, mod_json, data_files={},
                        config_files=config_files,
                        preview_image_path=metadata.get("preview_image_path") or None)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"打包 .tksmod 失败:\n{e}")
            return

        QMessageBox.information(self, "导出成功",
            f"已导出 MOD:\n  {save_path}\n"
            f"  包含配置: {', '.join(names_summary)}\n"
            f"  MOD 包中配置文件优先级最高，将覆盖 configs/ 目录同名文件。")

    # ── TKS 目录加载 ──

    def load_tks_directory(self):
        """加载 TKS 游戏目录: WarPC.dat + TKT.dat + Fa.JVG。"""
        d = pick_tks_directory(self)
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
            self.setWindowTitle(format_title("configs_editor", f"[{self._tks_dir}]"))
        else:
            self.setWindowTitle(format_title("configs_editor", f"[{self._configs_dir}]"))

    # ── 主题 ──

    def _toggle_theme(self):
        toggle_theme_in_family(self)
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


def main():
    run_editor(ConfigsEditorWindow, "TKS Configs Editor")


if __name__ == "__main__":
    main()
