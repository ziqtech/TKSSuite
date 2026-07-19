"""主窗口 — Godot 风格三面板布局 + 主题切换 + 启动逻辑"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QRadioButton, QSplitter, QStatusBar,
    QToolBar, QVBoxLayout, QWidget,
)

from core.config_loader import PatchDef, load_config
from core.save_manager import set_last_game_dir
from core.state_persistence import GuiState, load_gui_state, save_gui_state
from editor_utils.dock_components import DockHeader
from editor_utils.theme_manager import ThemeManager
from editor_utils.ui_helpers import themed_messagebox
from editor_utils.version import format_title, format_about_header
from editor_utils.window_theme import apply_godot_theme
from ui.custom_avatar_dialog import CustomAvatarDialog
from ui.custom_music_dialog import CustomMusicDialog
from ui.game_overlay import GameOverlay
from ui.log_console import LogConsole
from ui.mod_info_preview import ModInfoPreviewWidget
from ui.mod_list import ModListWidget
from ui.mod_meta_editor_dialog import ModMetaEditorDialog
from ui.mod_packer_dialog import ModPackerDialog
from ui.mod_editor_dialog import ModEditorDialog
from ui.mod_splitter_dialog import ModSplitterDialog
from ui.patch_list import PatchListWidget
from ui.save_manager_dialog import SaveManagerDialog
from workers.patcher_worker import PatcherWorker

# 确定启动器根目录（打包 exe 或开发模式）
if "__compiled__" in globals():
    from editor_utils.runtime_bootstrap import get_app_dir
    _LAUNCHER_DIR = get_app_dir()
else:
    _LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# GUI 勾选状态持久化文件路径 (与 launcher_config.json 同目录, 独立存储)
_STATE_PATH = os.path.join(_LAUNCHER_DIR, "launcher_setting.json")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(format_title("launcher"))
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

        # 加载 GUI 勾选状态 (补丁/模组/辅助工具的勾选记录)
        self._gui_state: GuiState = load_gui_state(_STATE_PATH) or GuiState()

        self._setup_menubar()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self.set_theme("dark" if self._dark_mode else "light")

        # 组件创建完成后, 连接状态变化信号实现自动保存
        self.patch_list.state_changed.connect(self._save_state)
        self.mod_list.state_changed.connect(self._save_state)
        self._tool_btn_group.buttonClicked.connect(self._save_state)

    def _setup_menubar(self):
        """顶部菜单栏 — 与其它编辑器保持一致风格"""
        menu_bar = self.menuBar()

        # 文件菜单: 启动 / 模组工具 / 退出
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("启动并注入…", QKeySequence("Ctrl+Return"), self._on_start)
        fm.addSeparator()
        fm.addAction("模组打包…", self._on_pack_mod)
        fm.addAction("模组拆分…", self._on_split_mod)
        fm.addAction("模组编辑…", self._on_edit_mod)
        fm.addAction("模组信息编辑…", self._on_edit_mod_meta)
        fm.addAction("自定义头像…", self._on_custom_avatar)
        fm.addAction("自定义音乐…", self._on_custom_music)
        fm.addAction("存档管理…", self._on_save_manager)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        # 视图菜单: 主题切换
        vm = menu_bar.addMenu("视图(V)")
        vm.addAction("切换主题", QKeySequence("Ctrl+T"), self._toggle_theme)

        # 帮助菜单: 使用说明 + 关于编辑器
        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于编辑器", self._show_about)

    def _show_help(self):
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            "TKS Mod Launcher — 三国群侠传 MOD 启动器\n\n"
            "1. 启动并注入 (Ctrl+Enter): 选择 TKS.exe, 启动游戏并注入勾选的补丁/模组\n"
            "2. 左侧「补丁列表」: 勾选需要应用的二进制补丁 (来自 tks_patches.json)\n"
            "3. 中间「模组列表」: 勾选要启用的 .tksmod 模组, 选中后下方显示模组详情\n"
            "4. 右侧「辅助工具」: 选择需要注入的辅助工具 (如 cnc-ddraw / ddraw)\n"
            "5. 模组打包: 将多个 .tksmod 文件打包为 .tksmodpak 合集\n"
            "6. 模组拆分: 从 .tksmodpak 合集文件中提取原始模组\n"
            "7. 模组编辑: 打开 .tksmod/.tksmodpak 添加/删除内部文件，原地保存\n"
            "8. 模组信息编辑: 编辑 .tksmod 的元数据 (标题/作者/描述等)\n"
            "9. 自定义头像: 上传图片并裁剪, 生成自定义头像 MOD\n"
            "10. 自定义音乐: 覆盖/新增 Sound 目录 BGM, 生成音乐 MOD\n"
            "11. 存档管理: 备份/恢复游戏存档及补丁状态快照\n"
            "12. 视图 → 切换主题 (Ctrl+T): 在深色/浅色主题间切换\n\n"
            "勾选状态会自动保存到 launcher_setting.json, 下次启动时自动恢复\n\n"
            "运行时基于内存补丁引擎 (runtime_patcher) 实现\n"
            "兼容 Winlator / Wine 环境 (通过 cli_launcher.py)")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('launcher'))

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

        self.btn_edit_mod = QPushButton("🔧 模组编辑")
        self.btn_edit_mod.setToolTip("打开 .tksmod/.tksmodpak，添加/删除内部文件，原地保存")
        self.btn_edit_mod.clicked.connect(self._on_edit_mod)
        toolbar.addWidget(self.btn_edit_mod)

        self.btn_edit_meta = QPushButton("✏️ 模组信息编辑")
        self.btn_edit_meta.setToolTip("加载 .tksmod 编辑元数据后保存（不改模组内容）")
        self.btn_edit_meta.clicked.connect(self._on_edit_mod_meta)
        toolbar.addWidget(self.btn_edit_meta)

        self.btn_avatar = QPushButton("🖼️ 自定义头像")
        self.btn_avatar.setToolTip("上传图片并裁剪，生成自定义头像 MOD")
        self.btn_avatar.clicked.connect(self._on_custom_avatar)
        toolbar.addWidget(self.btn_avatar)

        self.btn_music = QPushButton("🎵 自定义音乐")
        self.btn_music.setToolTip("管理游戏 BGM，覆盖/新增 Sound 曲目并生成 MOD")
        self.btn_music.clicked.connect(self._on_custom_music)
        toolbar.addWidget(self.btn_music)

        self.btn_save_mgr = QPushButton("💾 存档管理")
        self.btn_save_mgr.setToolTip("备份/恢复游戏存档及补丁状态")
        self.btn_save_mgr.clicked.connect(self._on_save_manager)
        toolbar.addWidget(self.btn_save_mgr)

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
        self.patch_list = PatchListWidget(self._patches,
                                          initial_states=self._gui_state.patches)
        self.patch_list.setMinimumWidth(300)
        splitter.addWidget(self.patch_list)

        # 中间: 模组列表 + 模组信息（垂直分割，互相独立）
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        self.mod_list = ModListWidget(mods_dir, initial_states=self._gui_state.mods)
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

        # 右侧: 日志控制台 + 辅助工具（垂直分割）
        self.log_console = LogConsole()
        log_wrap = QWidget()
        log_lay = QVBoxLayout(log_wrap)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)
        log_lay.addWidget(DockHeader("启动日志"))
        log_lay.addWidget(self.log_console, 1)

        # 辅助工具面板
        tools_panel = self._build_tools_panel()

        right = QSplitter(Qt.Vertical)
        right.setHandleWidth(4)
        right.setChildrenCollapsible(False)
        right.addWidget(log_wrap)
        right.addWidget(tools_panel)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        right.setSizes([600, 120])
        splitter.addWidget(right)

        # 中间/右侧可伸缩（窗口最大化时自适应），左侧按内容固定宽度
        splitter.setSizes([380, 570, 500])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

    def _build_tools_panel(self) -> QWidget:
        """构建辅助工具选择面板，根据 tools/ 子目录自动生成 RadioGroup。"""
        tools_dir = os.path.join(_LAUNCHER_DIR, "tools")
        # 扫描 tools/ 下的子文件夹作为可用工具
        self._available_tools: list[str] = []
        if os.path.isdir(tools_dir):
            self._available_tools = sorted(
                d for d in os.listdir(tools_dir)
                if os.path.isdir(os.path.join(tools_dir, d))
            )

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(DockHeader("辅助工具"))

        body = QWidget()
        body.setObjectName("DockBody")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(8, 6, 8, 6)
        body_lay.setSpacing(4)

        self._tool_btn_group = QButtonGroup(self)
        self._tool_btn_group.setExclusive(True)

        # 「无」选项 — 不注入任何辅助工具
        radio_none = QRadioButton("无")
        radio_none.setChecked(True)
        radio_none.setProperty("tool_name", "")
        self._tool_btn_group.addButton(radio_none)
        body_lay.addWidget(radio_none)

        for name in self._available_tools:
            rb = QRadioButton(name)
            rb.setProperty("tool_name", name)
            self._tool_btn_group.addButton(rb)
            body_lay.addWidget(rb)

        # 根据持久化状态恢复选中的辅助工具 (无匹配项时保持"无"选中)
        saved_tool = self._gui_state.tool
        if saved_tool:
            for btn in self._tool_btn_group.buttons():
                if btn.property("tool_name") == saved_tool:
                    btn.setChecked(True)
                    break

        body_lay.addStretch()
        outer.addWidget(body, 1)
        return container

    def _get_selected_tool(self) -> str:
        """返回当前选中的辅助工具名称（空字符串表示不注入）。"""
        btn = self._tool_btn_group.checkedButton()
        if btn:
            return btn.property("tool_name") or ""
        return ""

    def _save_state(self, *_):
        """收集所有列表勾选状态并保存到 launcher_setting.json (每次勾选变化时自动触发)。"""
        state = GuiState(
            patches=self.patch_list.get_patch_states(),
            mods=self.mod_list.get_mod_states(),
            tool=self._get_selected_tool(),
        )
        save_gui_state(_STATE_PATH, state)

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
        # 记忆游戏目录, 供存档管理器使用
        set_last_game_dir(_LAUNCHER_DIR, game_dir)

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
            selected_tool=self._get_selected_tool(),
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

    def _on_edit_mod(self):
        """打开模组编辑对话框，自动加载列表中选中的模组"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        selected = self.mod_list.get_selected_mod()
        initial_path = selected.path if selected else None
        dialog = ModEditorDialog(mods_dir=mods_dir, parent=self, initial_path=initial_path)
        dialog.exec()
        # 保存后刷新模组列表（内容可能已变更）
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

    def _on_custom_music(self):
        """打开自定义音乐对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = CustomMusicDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 导出后刷新模组列表
        self.mod_list.refresh_mods()

    def _on_save_manager(self):
        """打开存档管理对话框"""
        dialog = SaveManagerDialog(
            launcher_dir=_LAUNCHER_DIR,
            parent=self,
            get_current_state=self._get_current_gui_state,
            apply_state=self._apply_gui_state,
            is_game_running=self._is_game_running,
        )
        dialog.exec()

    def _get_current_gui_state(self) -> GuiState:
        """收集当前 UI 勾选状态为 GuiState (供存档管理器使用)"""
        return GuiState(
            patches=self.patch_list.get_patch_states(),
            mods=self.mod_list.get_mod_states(),
            tool=self._get_selected_tool(),
        )

    def _apply_gui_state(self, state: dict) -> None:
        """将备份中记录的补丁/模组/工具状态应用到 UI (用于存档恢复)

        state: {"patches": {id: bool}, "mods": {id: bool}, "tool": str}
        """
        patches = state.get("patches", {})
        if isinstance(patches, dict):
            self.patch_list.set_patch_states(
                {str(k): bool(v) for k, v in patches.items()})
        mods = state.get("mods", {})
        if isinstance(mods, dict):
            self.mod_list.set_mod_states(
                {str(k): bool(v) for k, v in mods.items()})
        tool = state.get("tool", "")
        if isinstance(tool, str):
            for btn in self._tool_btn_group.buttons():
                if (btn.property("tool_name") or "") == tool:
                    btn.setChecked(True)
                    break
        # 持久化已恢复的状态
        self._save_state()

    def _is_game_running(self) -> bool:
        """检查游戏是否正在运行 (PatcherWorker 仍在执行)"""
        return self._worker is not None and self._worker.isRunning()

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
