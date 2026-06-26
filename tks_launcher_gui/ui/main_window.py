"""主窗口 — Godot 风格三面板布局 + 主题切换 + 启动逻辑"""
import os
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QSplitter, QPushButton,
    QStatusBar, QLabel, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from editor_utils.theme_manager import ThemeManager
from editor_utils.window_theme import apply_godot_theme

from core.config_loader import load_config, PatchDef
from ui.patch_list import PatchListWidget
from ui.mod_list import ModListWidget
from ui.log_console import LogConsole
from ui.game_overlay import GameOverlay
from ui.mod_packer_dialog import ModPackerDialog
from workers.patcher_worker import PatcherWorker

# 确定启动器根目录（打包 exe 或开发模式）
if getattr(sys, 'frozen', False):
    _LAUNCHER_DIR = os.path.dirname(sys.executable)
else:
    _LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKS Mod Launcher")
        self.resize(1050, 720)
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

        self.btn_pack = QPushButton("📦 MOD 打包")
        self.btn_pack.setToolTip("将多个 .tksmod 文件合并为一个 MOD 包")
        self.btn_pack.clicked.connect(self._on_pack_mod)
        toolbar.addWidget(self.btn_pack)

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

        # 左侧面板: 补丁列表 + MOD 列表（垂直分割）
        left_splitter = QSplitter(Qt.Vertical)

        self.patch_list = PatchListWidget(self._patches)
        left_splitter.addWidget(self.patch_list)

        # 使用启动器目录下的 mods 目录
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        self.mod_list = ModListWidget(mods_dir)
        left_splitter.addWidget(self.mod_list)

        left_splitter.setSizes([360, 540])
        splitter.addWidget(left_splitter)

        self.log_console = LogConsole()
        splitter.addWidget(self.log_console)

        splitter.setSizes([580, 520])

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
        color = "#2E7D32" if ok else "#E06C75"
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_overlay_update(self, text: str, ok: bool):
        if self._overlay and self._overlay.isVisible():
            self._overlay.update_text(text, ok)

    def _on_finished(self, success: bool, diag: dict):
        self.btn_start.setEnabled(True)
        if success:
            self.status_bar.showMessage("补丁应用成功！游戏运行中")
            self.status_label.setStyleSheet("color: #2E7D32; font-weight: bold;")
            self.status_label.setText("✅ 补丁已生效")
        else:
            err = diag.get('error', 'unknown')
            self.status_bar.showMessage(f"失败: {err}")
            self.status_label.setStyleSheet("color: #E06C75; font-weight: bold;")
            self.status_label.setText("❌ 补丁应用失败")

    def _on_pack_mod(self):
        """打开 MOD 打包器对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = ModPackerDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 打包完成后刷新 MOD 列表
        self.mod_list.refresh_mods()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        if self._overlay:
            self._overlay.close_overlay()
        super().closeEvent(event)
