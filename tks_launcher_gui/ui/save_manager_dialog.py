"""存档管理对话框 — 备份/恢复游戏存档 + 补丁状态快照

功能:
  - 选择游戏目录 (自动记忆, 兼容开发/打包环境)
  - 创建备份: 将 game_dir/Save/ 全量压缩为 .zip (最高压缩比),
    同时记录当前补丁/模组/工具勾选状态到 backup_meta.json
  - 恢复备份: 从 .zip 还原存档文件, 可选恢复补丁状态
  - 恢复前自动创建当前存档的安全备份 (防止误操作)
  - 删除备份
"""
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)

from core.save_manager import (
    BackupInfo, create_backup, delete_backup, get_last_game_dir,
    list_backups, restore_save_files, set_last_game_dir, validate_backup,
)

# 备份列表各列索引
_COL_NAME = 0
_COL_TIME = 1
_COL_FILES = 2
_COL_PATCHES = 3
_COL_MODS = 4
_COL_TOOL = 5
_COLUMNS = ["备份名称", "备份时间", "存档文件数", "补丁数", "模组数", "辅助工具"]


class SaveManagerDialog(QDialog):
    """存档管理对话框

    参数:
        launcher_dir: 启动器根目录 (backups/ 与 save_manager_state.json 的父目录)
        get_current_state: 返回当前 GuiState 的回调 (patches/mods/tool)
        apply_state: 应用 GuiState 到 UI 的回调 (用于恢复补丁状态)
        is_game_running: 返回游戏是否正在运行的回调
    """

    def __init__(self, launcher_dir: str, parent=None,
                 get_current_state=None, apply_state=None,
                 is_game_running=None):
        super().__init__(parent)
        self.setWindowTitle("存档管理")
        self.resize(760, 560)
        self._launcher_dir = launcher_dir
        self._backups_dir = os.path.join(launcher_dir, "backups")
        self._game_dir: str = ""
        self._get_current_state = get_current_state
        self._apply_state = apply_state
        self._is_game_running = is_game_running or (lambda: False)

        self._build_ui()
        self._load_game_dir()

    # ────────────────────────────────────────────────
    # UI 构建
    # ────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- 游戏目录选择 ----
        game_group = QGroupBox("游戏目录")
        game_lay = QHBoxLayout(game_group)
        self._edit_game_dir = QLineEdit()
        self._edit_game_dir.setReadOnly(True)
        self._edit_game_dir.setPlaceholderText("点击「浏览…」选择 TKS.exe 所在目录")
        game_lay.addWidget(self._edit_game_dir, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._on_browse_game_dir)
        game_lay.addWidget(btn_browse)
        layout.addWidget(game_group)

        # ---- 备份列表 ----
        list_group = QGroupBox("备份列表")
        list_lay = QVBoxLayout(list_group)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(_COL_TIME, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_FILES, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_PATCHES, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_MODS, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_TOOL, QHeaderView.ResizeToContents)
        self._table.doubleClicked.connect(self._on_restore)
        list_lay.addWidget(self._table)

        # 列表操作按钮
        btn_row = QHBoxLayout()
        self._btn_restore = QPushButton("📦 恢复选中备份")
        self._btn_restore.setObjectName("btnPack")
        self._btn_restore.clicked.connect(self._on_restore)
        btn_row.addWidget(self._btn_restore)

        self._btn_delete = QPushButton("🗑️ 删除选中备份")
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        btn_row.addStretch()
        btn_refresh = QPushButton("🔄 刷新列表")
        btn_refresh.clicked.connect(self._refresh_list)
        btn_row.addWidget(btn_refresh)
        list_lay.addLayout(btn_row)

        layout.addWidget(list_group)

        # ---- 创建备份 ----
        create_group = QGroupBox("创建新备份")
        create_lay = QVBoxLayout(create_group)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("备份名称:"))
        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("输入备份名称 (留空则用日期时间)")
        name_row.addWidget(self._edit_name, 1)
        self._btn_create = QPushButton("💾 创建备份")
        self._btn_create.setObjectName("btnPack")
        self._btn_create.clicked.connect(self._on_create)
        name_row.addWidget(self._btn_create)
        create_lay.addLayout(name_row)

        # 当前状态预览
        self._state_label = QLabel()
        self._state_label.setWordWrap(True)
        self._state_label.setStyleSheet("color: gray; font-size: 11px;")
        create_lay.addWidget(self._state_label)

        layout.addWidget(create_group)

        # ---- 日志 ----
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(90)
        self._log.setPlaceholderText("操作日志将显示在这里...")
        layout.addWidget(self._log)

        # ---- 关闭按钮 ----
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._update_state_preview()

    # ────────────────────────────────────────────────
    # 游戏目录
    # ────────────────────────────────────────────────

    def _load_game_dir(self):
        """从持久化记录加载上次使用的游戏目录"""
        self._game_dir = get_last_game_dir(self._launcher_dir)
        self._edit_game_dir.setText(self._game_dir)
        self._refresh_list()

    def _on_browse_game_dir(self):
        """选择 TKS.exe 来确定游戏目录"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 TKS.exe", self._game_dir or os.getcwd(),
            "可执行文件 (*.exe);;所有文件 (*)"
        )
        if not path:
            return
        game_dir = os.path.dirname(os.path.abspath(path))
        self._game_dir = game_dir
        self._edit_game_dir.setText(game_dir)
        set_last_game_dir(self._launcher_dir, game_dir)
        self._log_msg(f"游戏目录已设置: {game_dir}")
        self._refresh_list()

    # ────────────────────────────────────────────────
    # 备份列表
    # ────────────────────────────────────────────────

    def _refresh_list(self):
        """刷新备份列表"""
        self._table.setRowCount(0)
        backups = list_backups(self._backups_dir)
        for b in backups:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._set_cell(row, _COL_NAME, b.name)
            self._set_cell(row, _COL_TIME, b.time)
            self._set_cell(row, _COL_FILES, str(b.save_file_count))
            self._set_cell(row, _COL_PATCHES, str(len(b.patch_state)))
            self._set_cell(row, _COL_MODS, str(len(b.mod_state)))
            self._set_cell(row, _COL_TOOL, b.tool or "无")
        self._log_msg(f"已加载 {len(backups)} 个备份")

    def _set_cell(self, row: int, col: int, text: str):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, col, item)

    def _get_selected_backup(self) -> BackupInfo | None:
        """获取当前选中的备份, 无选中返回 None"""
        items = self._table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        backups = list_backups(self._backups_dir)
        # 列表已按时间倒序, 表格行顺序与之一致
        if 0 <= row < len(backups):
            return backups[row]
        return None

    # ────────────────────────────────────────────────
    # 创建备份
    # ────────────────────────────────────────────────

    def _on_create(self):
        """创建存档备份"""
        if not self._game_dir or not os.path.isdir(self._game_dir):
            QMessageBox.warning(self, "提示", "请先选择有效的游戏目录")
            return
        if self._is_game_running():
            QMessageBox.warning(self, "游戏运行中",
                "游戏正在运行, 请先关闭游戏再创建备份")
            return

        save_dir = os.path.join(self._game_dir, "Save")
        if not os.path.isdir(save_dir):
            ret = QMessageBox.question(self, "存档目录不存在",
                f"游戏目录下未找到 Save\\ 存档目录:\n{save_dir}\n\n"
                "是否仍要创建空存档备份?",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        name = self._edit_name.text().strip()
        if not name:
            name = datetime.now().strftime("存档备份_%Y%m%d_%H%M%S")
        self._edit_name.clear()

        # 获取当前补丁/模组状态
        patch_state: dict[str, bool] = {}
        mod_state: dict[str, bool] = {}
        tool = ""
        if self._get_current_state:
            state = self._get_current_state()
            patch_state = state.patches
            mod_state = state.mods
            tool = state.tool

        try:
            zip_path = create_backup(
                self._backups_dir, self._game_dir, name,
                patch_state, mod_state, tool)
        except Exception as e:
            QMessageBox.critical(self, "备份失败", f"创建备份时出错:\n{e}")
            return

        self._log_msg(f"备份已创建: {os.path.basename(zip_path)}")
        self._refresh_list()

    # ────────────────────────────────────────────────
    # 恢复备份
    # ────────────────────────────────────────────────

    def _on_restore(self):
        """恢复选中的备份"""
        backup = self._get_selected_backup()
        if backup is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一个备份")
            return
        if not self._game_dir or not os.path.isdir(self._game_dir):
            QMessageBox.warning(self, "提示", "请先选择有效的游戏目录")
            return
        if self._is_game_running():
            QMessageBox.warning(self, "游戏运行中",
                "游戏正在运行, 请先关闭游戏再恢复存档")
            return

        # 校验备份完整性
        ok, err = validate_backup(backup.path)
        if not ok:
            QMessageBox.critical(self, "备份损坏",
                f"备份文件校验失败:\n{err}")
            return

        # 恢复前自动备份当前存档 (安全网)
        save_dir = os.path.join(self._game_dir, "Save")
        auto_name = f"_auto_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.isdir(save_dir) and os.listdir(save_dir):
            try:
                cur_state = self._get_current_state() if self._get_current_state else None
                create_backup(
                    self._backups_dir, self._game_dir, auto_name,
                    cur_state.patches if cur_state else {},
                    cur_state.mods if cur_state else {},
                    cur_state.tool if cur_state else "")
                self._log_msg(f"恢复前已自动备份当前存档: {auto_name}")
            except Exception as e:
                self._log_msg(f"⚠ 自动备份失败 (继续恢复): {e}")

        # 恢复存档文件
        try:
            count = restore_save_files(backup.path, self._game_dir)
        except Exception as e:
            QMessageBox.critical(self, "恢复失败",
                f"恢复存档文件时出错:\n{e}")
            return

        self._log_msg(f"已恢复 {count} 个存档文件")

        # 询问是否恢复补丁状态
        if self._apply_state and (backup.patch_state or backup.mod_state):
            # 检测是否有差异
            has_diff = self._has_state_diff(backup)
            if has_diff:
                ret = QMessageBox.question(self, "恢复补丁状态",
                    "备份中记录的补丁/模组状态与当前不同。\n\n"
                    "是否同时恢复补丁状态?\n"
                    "(恢复后下次启动游戏将使用备份时的补丁组合)",
                    QMessageBox.Yes | QMessageBox.No)
                if ret == QMessageBox.Yes:
                    self._apply_state({
                        "patches": backup.patch_state,
                        "mods": backup.mod_state,
                        "tool": backup.tool,
                    })
                    self._log_msg("补丁状态已恢复")
                    self._update_state_preview()

        QMessageBox.information(self, "恢复完成",
            f"存档恢复完成 ({count} 个文件)\n\n"
            "可以启动游戏载入恢复后的存档了")

    def _has_state_diff(self, backup: BackupInfo) -> bool:
        """检查备份的补丁状态与当前是否有差异"""
        if not self._get_current_state:
            return True
        cur = self._get_current_state()
        if cur.patches != backup.patch_state:
            return True
        if cur.mods != backup.mod_state:
            return True
        if cur.tool != backup.tool:
            return True
        return False

    # ────────────────────────────────────────────────
    # 删除备份
    # ────────────────────────────────────────────────

    def _on_delete(self):
        """删除选中的备份"""
        backup = self._get_selected_backup()
        if backup is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一个备份")
            return

        ret = QMessageBox.question(self, "确认删除",
            f"确定要删除备份「{backup.name}」吗?\n"
            f"(备份时间: {backup.time})\n\n"
            "此操作不可撤销",
            QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        if delete_backup(backup.path):
            self._log_msg(f"已删除备份: {backup.name}")
            self._refresh_list()
        else:
            QMessageBox.warning(self, "删除失败", "删除备份文件失败")

    # ────────────────────────────────────────────────
    # 辅助
    # ────────────────────────────────────────────────

    def _update_state_preview(self):
        """更新当前补丁状态预览"""
        if not self._get_current_state:
            self._state_label.setText("")
            return
        state = self._get_current_state()
        patches_on = sum(1 for v in state.patches.values() if v)
        mods_on = sum(1 for v in state.mods.values() if v)
        tool = state.tool or "无"
        self._state_label.setText(
            f"当前状态: 补丁 {patches_on}/{len(state.patches)} 个启用, "
            f"模组 {mods_on}/{len(state.mods)} 个启用, "
            f"辅助工具: {tool}")

    def _log_msg(self, msg: str):
        """追加一行日志"""
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"[{ts}] {msg}")
