"""主窗口 — Godot 风格三面板布局 + 主题切换 + 启动逻辑"""
import os
import re
from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QSplitter, QPushButton,
    QStatusBar, QLabel, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from core.config_loader import load_config, PatchDef
from ui.patch_list import PatchListWidget
from ui.log_console import LogConsole
from ui.game_overlay import GameOverlay
from workers.patcher_worker import PatcherWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKS Mod Launcher")
        self.resize(1050, 720)
        self.setMinimumSize(800, 500)

        # 窗口图标
        icon_path = os.path.join(os.path.dirname(__file__), "..", "TKS.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._dark_mode = True
        self._overlay: GameOverlay | None = None
        self._worker: PatcherWorker | None = None

        # 加载配置用于补丁列表
        config = load_config("tks_patches.json")
        self._patches: list[PatchDef] = config.patches if config else []

        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()

    def _setup_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.btn_start = QPushButton("▶ 启动并注入")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self._on_start)
        toolbar.addWidget(self.btn_start)

        self.btn_theme = QPushButton("🌙 深色")
        self.btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self.btn_theme)

        toolbar.addSeparator()

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        toolbar.addWidget(self.status_label)

    def _setup_central(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.patch_list = PatchListWidget(self._patches)
        splitter.addWidget(self.patch_list)

        self.log_console = LogConsole()
        splitter.addWidget(self.log_console)

        splitter.setSizes([400, 650])

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 请点击「启动并注入」选择游戏")

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self.btn_theme.setText("🌙 深色" if self._dark_mode else "☀ 浅色")
        self.set_theme("dark" if self._dark_mode else "light")

    def set_theme(self, theme: str):
        qss_file = os.path.join(os.path.dirname(__file__), "themes", f"{theme}.qss")
        try:
            with open(qss_file, 'r', encoding='utf-8') as f:
                qss = f.read()
            # 将相对 url() 转为绝对路径，确保图片能被 Qt 找到
            themes_dir = os.path.dirname(qss_file).replace('\\', '/')
            qss = re.sub(r'url\(([^)]+)\)', lambda m: f'url({themes_dir}/{m.group(1)})', qss)
            self.setStyleSheet(qss)
            self._dark_mode = (theme == "dark")
            self.btn_theme.setText("🌙 深色" if self._dark_mode else "☀ 浅色")
        except Exception:
            pass

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
        )

        self._worker.log_emitted.connect(self.log_console.append_log)
        self._worker.status_changed.connect(self._on_status)
        self._worker.game_window_found.connect(self._on_game_window_found)
        self._worker.overlay_update.connect(self._on_overlay_update)
        self._worker.finished.connect(self._on_finished)

        self._worker.start()

    def _on_game_window_found(self, game_hwnd: int):
        """UI 线程: 创建悬浮窗"""
        if self._overlay is None:
            self._overlay = GameOverlay(game_hwnd)

    def _on_status(self, text: str, ok: bool):
        self.status_label.setText(text)
        color = "#98C379" if ok else "#E06C75"
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_overlay_update(self, text: str, ok: bool):
        if self._overlay and self._overlay.isVisible():
            self._overlay.update_text(text, ok)

    def _on_finished(self, success: bool, diag: dict):
        self.btn_start.setEnabled(True)
        if success:
            self.status_bar.showMessage("补丁应用成功！游戏运行中")
            self.status_label.setStyleSheet("color: #98C379; font-weight: bold;")
            self.status_label.setText("✅ 补丁已生效")
        else:
            err = diag.get('error', 'unknown')
            self.status_bar.showMessage(f"失败: {err}")
            self.status_label.setStyleSheet("color: #E06C75; font-weight: bold;")
            self.status_label.setText("❌ 补丁应用失败")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        if self._overlay:
            self._overlay.close_overlay()
        super().closeEvent(event)
