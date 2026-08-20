"""主窗口 — Dock 风格三面板布局 + 主题切换 + 启动逻辑"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFileDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QRadioButton, QSplitter, QStatusBar, QTextBrowser,
    QToolBar, QWidget, QVBoxLayout, QHBoxLayout,
)

from core.config_loader import PatchDef
from core.tkspatch_loader import load_patch_directory
from core.save_manager import set_last_game_dir
from core.state_persistence import GuiState, load_gui_state, save_gui_state
from core.launch_context import LaunchContext
from core.recovery_snapshot import load_snapshot, recover_game_directory, manifest_changed
from editor_utils.dock_components import create_dock
from editor_utils.flow_layout import FlowLayout
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
from ui.mod_merger_dialog import ModMergerDialog
from ui.mod_editor_dialog import ModEditorDialog
from ui.mod_splitter_dialog import ModSplitterDialog
from ui.mode_card import ModeCardButton
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


# 启动状态语义级别 → 主题规范 objectName 映射在 _set_summary_status 内处理


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("LauncherWindow")
        self.setWindowTitle(format_title("launcher"))
        self.resize(1600, 900)
        self.setMinimumSize(800, 500)

        # 窗口图标
        icon_path = os.path.join(_LAUNCHER_DIR, "TKS.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._overlay: GameOverlay | None = None
        self._worker: PatcherWorker | None = None
        self._log_dialog: QDialog | None = None

        # 主题管理器（使用 editor_utils 的缓存式管理器）
        self._theme_mgr = ThemeManager()

        # 检测系统主题
        app_inst = QApplication.instance()
        self._dark_mode = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        # 加载配置用于补丁列表 (外置 .tkspatch 为唯一来源)
        patches_dir = os.path.join(_LAUNCHER_DIR, "patches")
        config = load_patch_directory(patches_dir)
        self._patches: list[PatchDef] = config.patches if config else []

        # 加载 GUI 勾选状态 (补丁/模组/辅助工具的勾选记录)
        self._gui_state: GuiState = load_gui_state(_STATE_PATH) or GuiState()

        # 状态栏主标签 (提前创建: 列表初始化期间可能触发状态更新)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")

        self._setup_menubar()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self.set_theme("dark" if self._dark_mode else "light")
        self._check_recovery_snapshot()

        # 组件创建完成后, 连接状态变化信号实现自动保存
        self.patch_list.state_changed.connect(self._save_state)
        self.mod_list.state_changed.connect(self._save_state)
        self._tool_btn_group.buttonClicked.connect(self._save_state)

    def _setup_menubar(self):
        """顶部菜单栏 — 与其它编辑器保持一致风格"""
        menu_bar = self.menuBar()

        # 文件菜单: 日常启动流程
        fm = menu_bar.addMenu("文件(F)")
        self._action_start = fm.addAction("启动游戏…", QKeySequence("Ctrl+Return"), self._on_start)
        self._action_choose_game = fm.addAction("选择游戏程序…", self._choose_game_path)
        self._action_refresh_mods = fm.addAction("刷新 MOD", self._refresh_mods)
        self._action_save_manager = fm.addAction("存档管理…", self._on_save_manager)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        mm = menu_bar.addMenu("MOD 工具(M)")
        mm.addAction("模组打包…", self._on_pack_mod)
        mm.addAction("模组合并…", self._on_merge_mod)
        mm.addAction("模组拆分…", self._on_split_mod)
        mm.addAction("模组编辑…", self._on_edit_mod)
        mm.addAction("模组信息编辑…", self._on_edit_mod_meta)
        mm.addAction("打包 TKS.exe 为 MOD…", self._on_pack_tks_exe)
        mm.addSeparator()
        mm.addAction("制作头像 MOD…", self._on_custom_avatar)
        mm.addAction("制作音乐 MOD…", self._on_custom_music)

        sm = menu_bar.addMenu("设置(S)")
        sm.addAction("启动模式设置", self._focus_mode)
        sm.addAction("查看详细日志", self._show_log_dialog)
        sm.addSeparator()
        vm = sm.addMenu("主题")
        vm.addAction("切换主题", QKeySequence("Ctrl+T"), self._toggle_theme)

        # 帮助菜单: 使用说明 + 关于编辑器
        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("使用说明", self._show_help)
        hm.addAction("标准模式与兼容模式", self._show_mode_help)
        hm.addAction("关于编辑器", self._show_about)

    def _show_mode_help(self):
        themed_messagebox(self, QMessageBox.Information, "标准模式与兼容模式",
            "标准模式\n"
            "使用启动器游戏功能，并加载已勾选的 MOD。推荐原版游戏使用。\n\n"
            "兼容模式\n"
            "不使用启动器游戏功能，只加载已勾选的 MOD。\n"
            "适合其他作者的游戏版本或其他启动器制作的 MOD。\n\n"
            "两种模式下 MOD 的勾选状态都会保留，切换模式不会清空你的选择。\n"
            "依赖启动器游戏功能的 MOD 在兼容模式下可能无法正常工作，"
            "请以 MOD 作者说明为准。")

    def _show_help(self):
        # 内容较长, 用可滚动对话框展示 (比 QMessageBox 可读性更好)
        text = (
            "TKS Mod Launcher — 三国群侠传 MOD 启动器\n\n"
            "1. 启动游戏 (Ctrl+Enter): 选择 TKS.exe, 按当前模式加载游戏功能和 MOD\n"
            "2. 左侧「补丁列表」: 勾选需要应用的启动器游戏功能, 标题栏右侧可切换 可选/必选 补丁\n"
            "3. 中间「MOD列表」: 勾选要启用的 .tksmod 模组, 右上显示模组详情\n"
            "4. 画面兼容工具: 设置 → 画面兼容工具, 选择需要注入的辅助工具 (如 cnc-ddraw)\n"
            "5. 模组打包: 将多个 .tksmod 文件打包为 .tksmodpak 合集\n"
            "6. 模组合并: 将多个 .tksmod 深度合并为一个 .tksmod (同一文件的不同帧/记录逐一合并)\n"
            "7. 模组拆分: 从 .tksmodpak 合集文件中提取原始模组\n"
            "8. 模组编辑: 打开 .tksmod/.tksmodpak 添加/删除内部文件，原地保存\n"
            "9. 模组信息编辑: 编辑 .tksmod 的元数据 (标题/作者/描述等)\n"
            "10. 自定义头像: 上传图片并裁剪, 生成自定义头像 MOD\n"
            "11. 自定义音乐: 覆盖/新增 Sound 目录 BGM, 生成音乐 MOD\n"
            "12. 存档管理: 备份/恢复游戏存档及补丁状态快照\n"
            "13. 设置 → 切换主题 (Ctrl+T): 在深色/浅色主题间切换\n\n"
            "勾选状态会自动保存到 launcher_setting.json, 下次启动时自动恢复\n\n"
            "运行时基于内存补丁引擎 (runtime_patcher) 实现\n"
            "兼容 Winlator / Wine 环境 (通过 cli_launcher.py)")
        dlg = QDialog(self)
        dlg.setWindowTitle("使用说明")
        dlg.resize(680, 520)
        layout = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setPlainText(text)
        layout.addWidget(view)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.close)
        layout.addWidget(close_btn)
        dlg.exec()

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('launcher'))

    def _check_recovery_snapshot(self):
        """启动时检查上次未完成的恢复任务。"""
        snapshot = load_snapshot(_LAUNCHER_DIR)
        if snapshot is None:
            return
        answer = QMessageBox.question(
            self,
            "检测到未完成恢复",
            "检测到上次启动未完成恢复。\n\n"
            f"游戏目录：{snapshot.game_dir}\n"
            "是否现在尝试恢复游戏文件？",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        changed = manifest_changed(snapshot.game_dir, snapshot.file_manifest)
        if changed:
            warning = "以下启动前已登记文件在外部发生变化，恢复可能覆盖修改：\n\n" + "\n".join(changed[:12])
            if len(changed) > 12:
                warning += f"\n…还有 {len(changed) - 12} 个文件"
            warning += "\n\n是否继续恢复？"
            if QMessageBox.question(self, "检测到外部修改", warning,
                                    QMessageBox.Cancel | QMessageBox.Yes,
                                    QMessageBox.Cancel) != QMessageBox.Yes:
                return
        ok = recover_game_directory(snapshot.game_dir)
        if ok:
            try:
                os.remove(os.path.join(_LAUNCHER_DIR, "launcher_recovery.json"))
            except OSError:
                pass
            self.status_bar.showMessage("已恢复上次启动留下的游戏文件")
        else:
            QMessageBox.warning(self, "恢复不完整", "部分文件恢复失败，请查看详细日志或手动检查游戏目录。")

    def _setup_toolbar(self):
        """顶部工具栏 — 启动操作突出，辅助操作保持轻量。"""
        toolbar = QToolBar()
        toolbar.setObjectName("LauncherToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.btn_start = QPushButton("▶ 启动游戏")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setToolTip("按当前模式加载游戏功能与 MOD 并启动游戏 (Ctrl+Enter)")
        self.btn_start.clicked.connect(self._on_start)
        toolbar.addWidget(self.btn_start)
        toolbar.addSeparator()

        self.btn_refresh_mods = QPushButton("↻ 刷新 MOD")
        self.btn_refresh_mods.setObjectName("toolbarSecondary")
        self.btn_refresh_mods.setToolTip("重新扫描 mods 目录")
        self.btn_refresh_mods.clicked.connect(self._refresh_mods)
        toolbar.addWidget(self.btn_refresh_mods)

        self.btn_save_mgr = QPushButton("💾 存档管理")
        self.btn_save_mgr.setObjectName("toolbarSecondary")
        self.btn_save_mgr.setToolTip("备份/恢复游戏存档及补丁状态")
        self.btn_save_mgr.clicked.connect(self._on_save_manager)
        toolbar.addWidget(self.btn_save_mgr)

        # 模式卡片按钮 (创建于此, 放置于顶部模式行; 样式走主题 #modeCard 规范)
        # 仍由 QButtonGroup 互斥管理, property("mode") 语义与原单选按钮一致
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._standard_mode = self._make_mode_card(
            "standard", "标准模式",
            "使用启动器游戏功能，并加载已勾选的 MOD（推荐原版游戏）",
            "使用左侧勾选的启动器游戏功能（内存补丁），并加载已勾选的 MOD。\n"
            "推荐原版 TKS.exe 使用。")
        self._compatible_mode = self._make_mode_card(
            "compatible", "兼容模式",
            "跳过启动器游戏功能，只加载已勾选的 MOD（适合其他版本）",
            "跳过启动器游戏功能，只加载已勾选的 MOD。\n"
            "适合其他作者的游戏版本或第三方启动器制作的 MOD。")
        (self._compatible_mode if self._gui_state.mode == "compatible" else self._standard_mode).setChecked(True)
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

    def _make_mode_card(self, mode: str, title: str, subtitle: str, tip: str) -> ModeCardButton:
        """创建分段式模式卡片按钮: 大号可选中按钮, 选中态由主题按 mode 属性着色。"""
        btn = ModeCardButton(title, subtitle)
        btn.setObjectName("modeCard")
        btn.setProperty("mode", mode)
        btn.setToolTip(tip)
        self._mode_group.addButton(btn)
        return btn

    def _setup_central(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("LauncherSplitter")
        splitter.setHandleWidth(8)
        root = QWidget()
        root.setObjectName("LauncherRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(10)

        # 模式行: 独立容器让两张模式卡片与下方工作区形成清晰层级
        mode_bar = QWidget()
        mode_bar.setObjectName("LauncherModeBar")
        mode_row = QHBoxLayout(mode_bar)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(10)
        mode_row.addWidget(self._standard_mode, 1)
        mode_row.addWidget(self._compatible_mode, 1)
        root_layout.addWidget(mode_bar)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        # 左侧: 补丁列表
        self.patch_list = PatchListWidget(self._patches,
                                          initial_states=self._gui_state.patches)
        self.patch_list.setObjectName("LauncherPatchPanel")
        self.patch_list.setMinimumWidth(300)
        splitter.addWidget(self.patch_list)

        # 中间: 模组列表 (全高)
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        self.mod_list = ModListWidget(mods_dir, initial_states=self._gui_state.mods)
        self.mod_list.setObjectName("LauncherModPanel")
        self.mod_list.setMinimumWidth(400)
        self.mod_preview = ModInfoPreviewWidget()
        self.mod_preview.setObjectName("LauncherPreviewPanel")
        self.mod_preview.set_default_height(self.patch_list.optional_default_height)
        # 选中模组时更新预览
        self.mod_list.mod_selected.connect(self.mod_preview.show_mod)
        # 重复 ID 检测
        self.mod_list.duplicate_ids_detected.connect(self._on_duplicate_ids)
        # 初始加载已在构造中完成，此时信号尚未连接，需手动检查一次
        self._on_duplicate_ids(self.mod_list.has_duplicate_ids())
        splitter.addWidget(self.mod_list)

        # 右侧: 模组信息 (上) + 启动状态 (中) + 画面兼容工具 (下)
        self.log_console = LogConsole()
        self._tools_panel = self._build_tools_panel()
        right = QSplitter(Qt.Vertical)
        right.setObjectName("LauncherRightSplitter")
        right.setHandleWidth(4)
        right.setChildrenCollapsible(False)
        right.addWidget(self.mod_preview)
        right.addWidget(self._build_status_panel())
        right.addWidget(self._tools_panel)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        right.setStretchFactor(2, 0)
        # 辅助工具面板高度取最小完整高度 = 标题栏 + 一行工具正好显示
        # (sizeHint 因 FlowLayout 的 height-for-width 特性会虚高, 故用 minimumSizeHint)
        tools_h = self._tools_panel.minimumSizeHint().height()
        right.setSizes([640, 280, tools_h])
        splitter.addWidget(right)

        # 中间/右侧可伸缩（窗口最大化时自适应），左侧补丁列表直接用最小宽度
        splitter.setSizes([self.patch_list.minimumWidth(), 570, 500])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self._update_mode_header()

    def _update_mode_header(self):
        compatible = self._get_mode() == "compatible"
        # 启动按钮带当前模式后缀并随模式换色, 防止带错误模式误启动
        if hasattr(self, "btn_start"):
            self.btn_start.setText(
                "▶ 启动游戏 · 兼容模式" if compatible else "▶ 启动游戏 · 标准模式")
            self.btn_start.setObjectName("btnStartCompat" if compatible else "btnStart")
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
        # 启动状态面板的当前模式值随模式着色
        if hasattr(self, "_summary_mode"):
            self._summary_mode.setObjectName("modeValueCompat" if compatible else "modeValueStd")
            self._summary_mode.style().unpolish(self._summary_mode)
            self._summary_mode.style().polish(self._summary_mode)
        if hasattr(self, "_enabled_mod_summary"):
            self._enabled_mod_summary.setText(
                f"已启用 MOD：{len(self.mod_list.get_enabled_mods())} 个")
        # 文档 §12: 兼容模式下游戏功能面板置灰保留勾选; 说明文案已由模式卡片副标题承载
        if hasattr(self, "patch_list"):
            self.patch_list.set_compatible_mode(compatible)

    def _build_status_panel(self) -> QWidget:
        """构建面向普通玩家的启动状态摘要面板。"""
        content = QWidget()
        content.setObjectName("LauncherSummaryContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        def _row(label_text: str, value: QLabel) -> None:
            row = QHBoxLayout()
            row.setSpacing(12)
            lab = QLabel(label_text)
            lab.setProperty("class", "PropLabel")
            lab.setFixedWidth(96)
            row.addWidget(lab)
            row.addWidget(value, 1)
            layout.addLayout(row)

        self._summary_mode = QLabel()
        self._summary_features = QLabel()
        self._summary_mods = QLabel()
        self._summary_tool = QLabel()
        for value in (self._summary_mode, self._summary_features,
                      self._summary_mods, self._summary_tool):
            value.setProperty("class", "SummaryValue")
        self._summary_status = QLabel()
        self._summary_status.setObjectName("statusLabel")

        _row("当前模式", self._summary_mode)
        _row("已启用游戏功能", self._summary_features)
        _row("已启用 MOD", self._summary_mods)
        _row("画面兼容工具", self._summary_tool)
        _row("启动状态", self._summary_status)

        self._summary_hint = QLabel()
        self._summary_hint.setObjectName("hintLabel")
        self._summary_hint.setWordWrap(True)
        layout.addWidget(self._summary_hint)
        self._btn_show_log = QPushButton("查看详细日志")
        self._btn_show_log.setObjectName("showLogButton")
        self._btn_show_log.clicked.connect(self._show_log_dialog)
        layout.addWidget(self._btn_show_log)

        panel = create_dock("启动状态", content, body_margins=(0, 0, 0, 0))
        panel.setObjectName("LauncherStatusPanel")
        self._update_summary()
        return panel

    def _update_summary(self):
        if not hasattr(self, "_summary_mode"):
            return
        compatible = self._get_mode() == "compatible"
        self._summary_mode.setText("兼容模式" if compatible else "标准模式")
        self._summary_features.setText(
            "不使用" if compatible else f"{len(self.patch_list.get_selected_patches())} 项")
        self._summary_mods.setText(f"{len(self.mod_list.get_enabled_mods())} 个")
        tool = self._get_selected_tool() if hasattr(self, "_tool_btn_group") else ""
        self._summary_tool.setText(tool or "未使用")
        self._set_summary_status("准备就绪", "idle")
        self._summary_hint.setText(
            "兼容模式下将跳过启动器游戏功能；依赖这些功能的 MOD 可能无法工作。"
            if compatible else "将使用启动器游戏功能，并加载已勾选的 MOD。")

    def _set_summary_status(self, text: str, level: str = "idle") -> None:
        """设置启动状态文本, 复用主题规范的状态标签样式 (statusLabel/Ok/Warn/Error)。"""
        self._summary_status.setText(text)
        name = {"ok": "statusLabelOk", "err": "statusLabelError",
                "warn": "statusLabelWarn"}.get(level, "statusLabel")
        self._summary_status.setObjectName(name)
        self._summary_status.style().unpolish(self._summary_status)
        self._summary_status.style().polish(self._summary_status)

    def _show_log_dialog(self):
        if self._log_dialog is None:
            self._log_dialog = QDialog(self)
            self._log_dialog.setWindowTitle("详细启动日志")
            self._log_dialog.resize(900, 600)
            layout = QVBoxLayout(self._log_dialog)
            layout.addWidget(self.log_console)
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self._log_dialog.close)
            layout.addWidget(close_btn)
        self._log_dialog.show()
        self._log_dialog.raise_()
        self._log_dialog.activateWindow()

    def _build_tools_panel(self) -> QWidget:
        """构建辅助工具选择面板，根据 tools/ 子目录自动生成 RadioGroup。"""
        tools_dir = os.path.join(_LAUNCHER_DIR, "tools")
        # 扫描 tools/ 下的子文件夹作为可用工具 (排除 __pycache__ 等无效目录)
        self._available_tools: list[str] = []
        if os.path.isdir(tools_dir):
            self._available_tools = sorted(
                d for d in os.listdir(tools_dir)
                if os.path.isdir(os.path.join(tools_dir, d))
                and not d.startswith(("_", "."))
            )

        content = QWidget()
        content.setObjectName("LauncherToolsContent")
        # 横向流式排列, 超出面板宽度自动换行 (工具数量少, 比纵向堆叠更紧凑)
        body_lay = FlowLayout(content, margin=0, spacing=8)

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

        panel = create_dock("画面兼容工具", content, body_margins=(10, 8, 10, 8))
        panel.setObjectName("LauncherToolsPanel")
        return panel

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
            mode=self._get_mode(),
            last_game_path=self._gui_state.last_game_path,
        )
        self._gui_state = state
        save_gui_state(_STATE_PATH, state, game_path=state.last_game_path)
        self._update_summary()
        self._update_mode_header()

    def _load_game_profile(self, game_path: str) -> None:
        """切换游戏程序时加载对应状态 profile，旧文件自动回退到全局状态。"""
        state = load_gui_state(_STATE_PATH, game_path=game_path) or GuiState(
            last_game_path=game_path)
        state.last_game_path = game_path
        self._gui_state = state
        self.patch_list.set_patch_states(state.patches)
        self.mod_list.set_mod_states(state.mods)
        for btn in self._tool_btn_group.buttons():
            if (btn.property("tool_name") or "") == state.tool:
                btn.setChecked(True)
                break
        self._mode_group.blockSignals(True)
        (self._compatible_mode if state.mode == "compatible" else self._standard_mode).setChecked(True)
        self._mode_group.blockSignals(False)
        self._update_summary()

    def _get_mode(self) -> str:
        button = self._mode_group.checkedButton()
        return (button.property("mode") if button else None) or "standard"

    def _on_mode_changed(self, button):
        # 兼容模式提示由状态栏常驻标签展示 (_update_mode_header), 此处不再重复弹临时消息
        self._save_state()
        self._update_summary()
        self._update_mode_header()

    def _refresh_mods(self):
        if hasattr(self, "mod_list"):
            self.mod_list.refresh_mods()

    def _choose_game_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 TKS.exe", self._gui_state.last_game_path or os.getcwd(),
            "Executable (*.exe);;All Files (*)")
        if path:
            self._load_game_profile(os.path.abspath(path))
            self._save_state()
            self.status_bar.showMessage(f"已选择游戏程序: {os.path.basename(path)}")

    def _focus_mode(self):
        if hasattr(self, "_standard_mode"):
            self._standard_mode.setFocus()

    def _set_running_state(self, running: bool):
        """锁定会影响本次启动快照的控件，避免运行中状态漂移。"""
        for widget in (
            self._standard_mode, self._compatible_mode,
            self.patch_list, self.mod_list, self._tools_panel,
            self.btn_refresh_mods, self.btn_save_mgr,
        ):
            widget.setEnabled(not running)
        self._action_start.setEnabled(not running)
        self._action_choose_game.setEnabled(not running)
        self._action_refresh_mods.setEnabled(not running)
        self._action_save_manager.setEnabled(not running)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("LauncherStatusBar")
        self.setStatusBar(self.status_bar)
        # 已启用 MOD 计数 (原模式行右侧, 现改为底部状态栏常驻显示)
        self._enabled_mod_summary = QLabel()
        self._enabled_mod_summary.setObjectName("enabledModSummary")
        self.status_bar.addPermanentWidget(self._enabled_mod_summary)
        self.status_bar.addPermanentWidget(self.status_label)
        self.status_bar.showMessage("就绪 — 请点击「启动游戏」")
        # MOD 计数标签在此创建, 补一次刷新使初始计数生效
        self._update_mode_header()

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self.set_theme("dark" if self._dark_mode else "light")

    def set_theme(self, theme: str):
        """应用主题：QSS 样式 + Windows 窗口框架主题"""
        self._dark_mode = (theme == "dark")
        self._theme_mgr.set_theme(theme)

        # 应用 QSS 样式表（从 ThemeManager 缓存中获取, 编辑器主题规范唯一来源）
        ThemeManager.apply_theme(self, theme)

        # 应用 Windows 标题栏/边框主题
        apply_godot_theme(self, is_dark=self._dark_mode)

        # 模式卡片为自绘组件, 主题色表需随主题同步
        for card in (self._standard_mode, self._compatible_mode):
            card.set_dark_mode(self._dark_mode)

        # 更新日志控制台深色状态
        self.log_console.set_dark_mode(self._dark_mode)

    def _on_start(self):
        remembered = self._gui_state.last_game_path
        if remembered and os.path.isfile(remembered):
            exe_path = remembered
        else:
            exe_path, _ = QFileDialog.getOpenFileName(
                self, "选择 TKS.exe", remembered or os.getcwd(),
                "Executable (*.exe);;All Files (*)"
            )
        if not exe_path:
            return

        game_dir = os.path.dirname(os.path.abspath(exe_path))
        if os.path.normcase(self._gui_state.last_game_path) != os.path.normcase(exe_path):
            self._load_game_profile(exe_path)
        self._gui_state.last_game_path = exe_path
        self._save_state()
        # 记忆游戏目录, 供存档管理器使用
        set_last_game_dir(_LAUNCHER_DIR, game_dir)

        self.btn_start.setEnabled(False)
        self._set_running_state(True)
        mode_label = "兼容模式" if self._get_mode() == "compatible" else "标准模式"
        enabled_mod_count = len(self.mod_list.get_enabled_mods())
        self.status_bar.showMessage(
            f"正在准备游戏：{mode_label}，将加载 {enabled_mod_count} 个 MOD")
        self.log_console.clear_log()

        context = LaunchContext(
            exe_path=exe_path,
            game_dir=game_dir,
            mode=self._get_mode(),
            selected_patches=frozenset(self.patch_list.get_selected_patches()),
            enabled_mod_ids=frozenset(m.mod_id for m in self.mod_list.get_enabled_mods()),
            selected_tool=self._get_selected_tool(),
        ).normalized()
        self._worker = PatcherWorker.from_context(context, wait_timeout=30)

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
        if hasattr(self, "_summary_status"):
            self._set_summary_status(text, "ok" if ok else "err")
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
            f"⚠ 检测到游戏版本：{display_name}，部分游戏功能已自动跳过")

    def _on_finished(self, success: bool, diag: dict):
        self.btn_start.setEnabled(True)
        self._set_running_state(False)
        mode = "兼容模式" if diag.get("mode") == "compatible" else "标准模式"
        patch_text, has_issue = self._format_patch_result(diag)
        mod_text, mod_issue = self._format_mod_result(diag)
        has_issue = has_issue or mod_issue
        if hasattr(self, "_summary_status"):
            if not success:
                self._set_summary_status("启动失败", "err")
            elif has_issue:
                self._set_summary_status("游戏已退出（部分内容未应用）", "warn")
            else:
                # finished 在游戏退出且清理完成后才发出, 此时不应再显示"运行中"
                self._set_summary_status("游戏已退出", "ok")
            self._summary_hint.setText(
                f"本次：游戏功能 {patch_text}，MOD {mod_text}\n"
                + ("如有异常请点击「查看详细日志」排查。" if has_issue
                   else "详细过程可在「查看详细日志」中查看。"))
        if success:
            # 游戏已退出: 状态栏给出本次会话的分项小结, 右下角回到就绪
            self.status_bar.showMessage(
                f"游戏已退出。本次：{mode}，游戏功能 {patch_text}，MOD {mod_text}")
            self.status_label.setText("就绪")
            self.status_label.setObjectName("statusLabel")
        else:
            self.status_bar.showMessage("启动失败，请查看详细日志了解原因")
            self.status_label.setText("启动失败")
            self.status_label.setObjectName("statusLabelError")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    @staticmethod
    def _format_patch_result(diag: dict) -> tuple[str, bool]:
        """补丁分项结果的玩家文案; 返回 (文案, 是否存在问题)。"""
        status = diag.get("patches_status", "not_started")
        if status == "skipped":
            return "未使用", False
        if status == "applied":
            return "已应用", False
        if status == "partial":
            return "部分未应用", True
        if status == "failed":
            return "应用失败", True
        return "未使用", False

    @staticmethod
    def _format_mod_result(diag: dict) -> tuple[str, bool]:
        """MOD 分项结果的玩家文案; 返回 (文案, 是否存在问题)。"""
        loaded = diag.get("mods_loaded_count", 0)
        failed = diag.get("mods_failed_count", 0)
        if failed > 0:
            return f"{loaded} 个成功，{failed} 个失败", True
        return f"{loaded} 个已加载", False

    def _on_pack_mod(self):
        """打开模组打包器对话框"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = ModPackerDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 打包完成后刷新模组列表
        self.mod_list.refresh_mods()

    def _on_pack_tks_exe(self):
        """将第三方 TKS.exe 打包为 .tksmod（复用 mod_exporter 框架）"""
        from editor_utils.mod_exporter import (
            ModMetadataDialog, generate_mod_json, pack_tksmod, safe_mod_filename,
        )

        # 1. 选择 TKS.exe
        exe_path, _ = QFileDialog.getOpenFileName(
            self, "选择第三方 TKS.exe", "",
            "TKS 启动器 (TKS.exe);;EXE 文件 (*.exe);;All Files (*)")
        if not exe_path:
            return

        # 2. 验证 MZ 头
        try:
            with open(exe_path, 'rb') as f:
                if f.read(2) != b'MZ':
                    QMessageBox.warning(self, "无效文件", "选择的文件不是有效的 EXE 文件 (缺少 MZ 头)")
                    return
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return

        # 3. 元数据对话框 (复用 mod_exporter 的 ModMetadataDialog)
        base_name = os.path.splitext(os.path.basename(exe_path))[0]
        defaults = {
            "name": f"{base_name} (TKS.exe 替换)",
            "description": f"第三方 TKS.exe 替换 (来源: {os.path.basename(exe_path)})",
            "load_order": 0,
        }
        dlg = ModMetadataDialog(self, defaults)
        dlg.setWindowTitle("打包 TKS.exe 为 MOD (.tksmod)")
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()

        # 4. 构建 mod.json (强制 type=tks_exe, load_order=0)
        metadata["type"] = "tks_exe"
        metadata["load_order"] = 0
        resources = [{"file": "resources/TKS.exe", "target": "TKS.exe"}]
        mod_json = generate_mod_json(metadata, components=[], resources=resources)

        # 5. 选择保存路径
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        default_name = f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod"
        fp, _ = QFileDialog.getSaveFileName(
            self, "保存 TKS.exe MOD", os.path.join(mods_dir, default_name),
            "TKS MOD (*.tksmod)")
        if not fp:
            return

        # 6. 打包
        try:
            resource_files = {"resources/TKS.exe": exe_path}
            pack_tksmod(fp, mod_json, data_files={}, resource_files=resource_files)
            file_size = os.path.getsize(fp)
            QMessageBox.information(self, "打包成功",
                f"已导出 TKS.exe MOD:\n{os.path.basename(fp)}\n\n"
                f"大小: {file_size / 1024:.1f} KB\n\n"
                f"请在模组列表中勾选启用它，启动游戏时将自动替换 TKS.exe。\n"
                f"游戏退出后会自动恢复原版 TKS.exe。")
            self.mod_list.refresh_mods()
        except Exception as e:
            QMessageBox.critical(self, "打包失败", str(e))

    def _on_merge_mod(self):
        """打开模组合并对话框 (深度合并为单个 .tksmod)"""
        mods_dir = os.path.join(_LAUNCHER_DIR, "mods")
        dialog = ModMergerDialog(mods_dir=mods_dir, parent=self)
        dialog.exec()
        # 合并完成后刷新模组列表
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
            mode=self._get_mode(),
            last_game_path=self._gui_state.last_game_path,
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
        mode = state.get("mode", "standard")
        if mode in {"standard", "compatible"}:
            target = self._compatible_mode if mode == "compatible" else self._standard_mode
            self._mode_group.blockSignals(True)
            target.setChecked(True)
            self._mode_group.blockSignals(False)
        last_game_path = state.get("last_game_path", "")
        if isinstance(last_game_path, str):
            self._gui_state.last_game_path = last_game_path
        # 持久化已恢复的状态
        self._save_state()
        self._update_summary()

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
