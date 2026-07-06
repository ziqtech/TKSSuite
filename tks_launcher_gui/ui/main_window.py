"""主窗口 — Godot 风格三面板布局 + 主题切换 + 启动逻辑"""
import os
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QSplitter, QPushButton,
    QStatusBar, QLabel, QFileDialog, QMessageBox, QWidget, QVBoxLayout,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from editor_utils.theme_manager import ThemeManager
from editor_utils.window_theme import apply_godot_theme

from core.config_loader import load_config, PatchDef
from ui.patch_list import PatchListWidget
from ui.mod_list import ModListWidget
from ui.mod_info_preview import ModInfoPreviewWidget
from ui.log_console import LogConsole
from ui.game_overlay import GameOverlay
from ui.mod_packer_dialog import ModPackerDialog
from ui.mod_meta_editor_dialog import ModMetaEditorDialog
from ui.mod_splitter_dialog import ModSplitterDialog
from ui.custom_avatar_dialog import CustomAvatarDialog
from workers.patcher_worker import PatcherWorker
from editor_utils.dock_components import DockHeader

# 确定启动器根目录（打包 exe 或开发模式）
if "__compiled__" in globals():
    from editor_utils.runtime_bootstrap import get_app_dir
    _LAUNCHER_DIR = get_app_dir()
else:
    _LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKS Mod Launcher")
        self.resize(1600, 900)
        self.setMinimumSize(800, 500)

        # 窗口图标
        icon_path = os.path.join(_LAUNCHER_DIR, "TKS.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._overlay: GameOverlay | None = None
        self._worker: PatcherWorker | None = None

        # 主题管理器（使用 editor_utils 的缓存式管理器）
        self._theme_mgr = ThemeManager()

        # 检测系统主题
        app_inst = QApplication.instance()
        self._dark_mode = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        # 加载配置用于补丁列表
        config_path = os.path.join(_LAUNCHER_DIR, "tks_patches.json")
        config = load_config(config_path)
        self._patches: list[PatchDef] = config.patches if config else []

        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self.set_theme("dark" if self._dark_mode else "light")

    def _setup_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.btn_start = QPushButton("🚀 启动并注入")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self._on_start)
        toolbar.addWidget(self.btn_start)

        self.btn_pack = QPushButton("📦 模组打包")
        self.btn_pack.setToolTip("将多个 .tksmod 文件打包为 .tksmodpak 合集文件")
        self.btn_pack.clicked.connect(self._on_pack_mod)
        toolbar.addWidget(self.btn_pack)

        self.btn_split = QPushButton("📂 模组拆分")
        self.btn_split.setToolTip("从 .tksmodpak 合集文件中提取原始模组")
        self.btn_split.clicked.connect(self._on_split_mod)
        toolbar.addWidget(self.btn_split)

        self.btn_edit_meta = QPushButton("✏️ 模组信息编辑")
        self.btn_edit_meta.setToolTip("加载 .tksmod 编辑元数据后保存（不改模组内容）")
        self.btn_edit_meta.clicked.connect(self._on_edit_mod_meta)
        toolbar.addWidget(self.btn_edit_meta)

        self.btn_avatar = QPushButton("🖼️ 自定义头像")
        self.btn_avatar.setToolTip("上传图片并裁剪，生成自定义头像 MOD")
        self.btn_avatar.clicked.connect(self._on_custom_avatar)
        toolbar.addWidget(self.btn_avatar)

        self.btn_theme = QPushButton("🌗 切换主题")
        self.btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self.btn_theme)

        toolbar.addSeparator()

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        toolbar.addWidget(self.status_label)

    def _setup_central(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # 左侧: 补丁列表
        self.patch_list = PatchListWidget(self._patches)
        self.patch_list.setMinimumWidth(300)
        splitter.addWidget(self.patch_list)

        # 中间: 模组列表 + 模组信息（垂直分割，互相独立）
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        self.mod_list = ModListWidget(mods_dir)
        self.mod_list.setMinimumWidth(400)
        self.mod_preview = ModInfoPreviewWidget()
        self.mod_preview.set_default_height(self.patch_list.optional_default_height)
        # 选中模组时更新预览
        self.mod_list.mod_selected.connect(self.mod_preview.show_mod)
        # 重复 ID 检测
        self.mod_list.duplicate_ids_detected.connect(self._on_duplicate_ids)
        # 初始加载已在构造中完成，此时信号尚未连接，需手动检查一次
        self._on_duplicate_ids(self.mod_list.has_duplicate_ids())

        middle = QSplitter(Qt.Vertical)
        middle.setHandleWidth(4)
        middle.setChildrenCollapsible(False)
        middle.addWidget(self.mod_list)
        middle.addWidget(self.mod_preview)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 0)
        middle.setSizes([1000, self.patch_list.optional_default_height])
        splitter.addWidget(middle)

        # 右侧: 日志控制台（带 DockHeader）
        self.log_console = LogConsole()
        log_wrap = QWidget()
        log_lay = QVBoxLayout(log_wrap)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)
        log_lay.addWidget(DockHeader("启动日志"))
        log_lay.addWidget(self.log_console, 1)
        splitter.addWidget(log_wrap)

        # 中间/右侧可伸缩（窗口最大化时自适应），左侧按内容固定宽度
        splitter.setSizes([380, 570, 500])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 请点击「启动并注入」选择游戏")

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self.set_theme("dark" if self._dark_mode else "light")

    def set_theme(self, theme: str):
        """应用主题：QSS 样式 + Windows 窗口框架主题"""
        self._dark_mode = (theme == "dark")
        self._theme_mgr.set_theme(theme)

        # 应用 QSS 样式表（从 ThemeManager 缓存中获取）
        ThemeManager.apply_theme(self, theme)

        # 应用 Windows 标题栏/边框主题
        apply_godot_theme(self, is_dark=self._dark_mode)

        # 更新日志控制台深色状态
        self.log_console.set_dark_mode(self._dark_mode)

    def _on_start(self):
        exe_path, _ = QFileDialog.getOpenFileName(
            self, "选择 TKS.exe", os.getcwd(),
            "Executable (*.exe);;All Files (*)"
        )
        if not exe_path:
            return

        game_dir = os.path.dirname(os.path.abspath(exe_path))

        self.btn_start.setEnabled(False)
        self.status_bar.showMessage("正在启动游戏...")
        self.log_console.clear_log()

        self._worker = PatcherWorker(
            exe_path=exe_path,
            game_dir=game_dir,
            wait_timeout=30,
            minimal_mode=False,
            selected_patches=self.patch_list.get_selected_patches(),
            enabled_mod_ids={m.mod_id for m in self.mod_list.get_enabled_mods()},
        )

        self._worker.log_emitted.connect(self.log_console.append_log)
        self._worker.status_changed.connect(self._on_status)
        self._worker.game_window_found.connect(self._on_game_window_found)
        self._worker.overlay_update.connect(self._on_overlay_update)
        self._worker.profile_detected.connect(self._on_profile_detected)
        self._worker.finished.connect(self._on_finished)

        self._worker.start()

    def _on_game_window_found(self, game_hwnd: int):
        """UI 线程: 创建悬浮窗. 游戏关闭后旧 overlay 已隐藏但引用仍在, 需重建."""
        if self._overlay is not None and not self._overlay.isVisible():
            self._overlay.close_overlay()
            self._overlay = None
        if self._overlay is None:
            self._overlay = GameOverlay(game_hwnd)

    def _on_status(self, text: str, ok: bool):
        self.status_label.setText(text)
        # 通过 objectName 切换状态样式, 颜色由 QSS 控制
        self.status_label.setObjectName("statusLabelOk" if ok else "statusLabelError")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _on_overlay_update(self, text: str, ok: bool):
        if self._overlay and self._overlay.isVisible():
            self._overlay.update_text(text, ok)

    def _on_profile_detected(self, display_name: str):
        """UI 线程: 显示检测到的第三方 MOD 版本信息"""
        self.status_bar.showMessage(
            f"⚠ 检测到第三方 MOD 版本: {display_name}，部分补丁已自动跳过"
        )

    def _on_finished(self, success: bool, diag: dict):
        self.btn_start.setEnabled(True)
        if success:
            self.status_bar.showMessage("补丁应用成功！游戏运行中")
            self.status_label.setText("✅ 补丁已生效")
            self.status_label.setObjectName("statusLabelOk")
        else:
            err = diag.get('error', 'unknown')
            self.status_bar.showMessage(f"失败: {err}")
            self.status_label.setText("❌ 补丁应用失败")
            self.status_label.setObjectName("statusLabelError")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _on_pack_mod(self):
        """打开模组打包器对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = ModPackerDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 打包完成后刷新模组列表
        self.mod_list.refresh_mods()

    def _on_split_mod(self):
        """打开模组拆分对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = ModSplitterDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 拆分完成后刷新模组列表
        self.mod_list.refresh_mods()

    def _on_edit_mod_meta(self):
        """打开模组元数据编辑对话框，自动加载列表中选中的模组"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        selected = self.mod_list.get_selected_mod()
        initial_path = selected.path if selected else None
        dialog = ModMetaEditorDialog(mods_dir=mods_dir, parent=self, initial_path=initial_path)
        dialog.exec()
        # 保存后刷新模组列表（元数据可能已变更）
        self.mod_list.refresh_mods()

    def _on_custom_avatar(self):
        """打开自定义头像对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = CustomAvatarDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 生成后刷新模组列表
        self.mod_list.refresh_mods()

    def _on_duplicate_ids(self, has_dup: bool):
        """模组列表刷新后根据重复 ID 情况更新状态标签和启动按钮"""
        if has_dup:
            self.status_label.setText("❌ 存在重复ID")
            self.status_label.setObjectName("statusLabelError")
            self.btn_start.setEnabled(False)
        else:
            self.status_label.setText("就绪")
            self.status_label.setObjectName("statusLabel")
            self.btn_start.setEnabled(True)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        if self._overlay:
            self._overlay.close_overlay()
        super().closeEvent(event)
