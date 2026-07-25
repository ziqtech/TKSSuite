"""自定义音乐对话框 — 管理游戏 BGM 覆盖/追加，导出/导入 .tksmod

游戏 BGM 直接放在 <游戏目录>/Sound/ 下即可生效 (0000.mp3 ~ 0028.mp3 为内置曲目)。
本对话框以三列表格管理这些曲目:
  1. 文件名     Sound/ 目录中的 .mp3 文件名
  2. 状态       蓝色「已修改」/ 灰色「未修改」
  3. 操作       播放 / 暂停 / 重置 / 修改 / 删除

基础曲目 0000~0028 不可删除, 只能修改覆盖 (删除=清空修改, 变回未修改);
新增曲目从 0101 开始编号, 可整条删除。
新增时若文件名本身为数字则保留原编号, 否则从 0101 自动分配。

设置完成后可导出为 .tksmod (通过 resources 机制将 .mp3 写入 Sound/),
也可从已有 .tksmod 导入并重新编辑。
"""
import ctypes
import json
import os
import re
import shutil
import tempfile
import zipfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from editor_utils.mod_exporter import (
    ModMetadataDialog, generate_mod_json, generate_short_uuid,
    pack_tksmod, safe_mod_filename,
)
from editor_utils.ui_helpers import themed_messagebox

# ── 常量 ──
# 游戏内置 (默认) BGM 编号: 0000~0028 与 0100, 均不可删除, 只能修改覆盖
BASE_SLOT_NUMBERS = tuple(range(0, 29)) + (100,)
ADDED_SLOT_START = 101     # 新增曲目起始编号 → 0101.mp3
SOUND_SUBDIR = "Sound"     # 游戏目录下的 BGM 子目录

MOD_NAME_DEFAULT = "[音乐] 自定义音乐"
MOD_AUTHOR_DEFAULT = "玩家自定义"
MOD_DESC_DEFAULT = "TKS子青启动器制作的自定义 BGM"
MOD_LOAD_ORDER_DEFAULT = 900

# 状态颜色
COLOR_MODIFIED = "#2f80ed"    # 蓝色 — 已修改
COLOR_UNMODIFIED = "#888888"  # 灰色 — 未修改

# 表格列
_COL_NAME = 0
_COL_STATUS = 1
_COL_OPS = 2
_COLUMNS = ["文件名", "状态", "操作"]

# 匹配 NNNN.mp3 (4 位数字) 的资源文件名
_MP3_NAME_RE = re.compile(r'^(\d{4})\.mp3$', re.IGNORECASE)


def _is_base_number(n: int) -> bool:
    """判断编号是否为游戏内置 (默认) 曲目 (不可删除, 只能修改覆盖)。"""
    return n in BASE_SLOT_NUMBERS


class MusicEntry:
    """单条音乐曲目的编辑状态。

    filename:      形如 "0000.mp3" 的文件名 (对应 Sound/ 下的目标文件)
    is_base:       是否为基础内置曲目 (0000~0028、0100, 不可删除)
    custom_path:   自定义 .mp3 的本地路径 (空 = 未修改)
    original_path: 基础曲目在 Sound/ 中的原始文件路径 (仅供试听, 可能为空)
    number:        4 位编号整数
    """

    __slots__ = ("filename", "is_base", "custom_path", "original_path", "number")

    def __init__(self, filename: str, is_base: bool,
                 custom_path: str = "", original_path: str = ""):
        self.filename = filename
        self.is_base = is_base
        self.custom_path = custom_path
        self.original_path = original_path
        m = _MP3_NAME_RE.match(filename)
        self.number = int(m.group(1)) if m else -1

    @property
    def is_modified(self) -> bool:
        return bool(self.custom_path)

    @property
    def play_source(self) -> str:
        """当前可播放的音频路径: 优先自定义, 其次基础曲目原始文件。"""
        if self.custom_path and os.path.isfile(self.custom_path):
            return self.custom_path
        if self.original_path and os.path.isfile(self.original_path):
            return self.original_path
        return ""


class _AudioPlayer:
    """基于 Windows MCI (winmm) 的轻量 mp3 播放器。

    仅依赖系统 winmm.dll, 不需要 QtMultimedia / FFmpeg 等外部后端,
    因此随 Nuitka 打包也能正常工作。非 Windows 或不可用时自动降级为空操作。
    支持: 加载 / 从头播放 / 暂停 / 恢复 / 停止 / 查询状态。
    """

    _ALIAS = "tksmusic"

    def __init__(self):
        self._loaded = False
        try:
            self._mci = ctypes.windll.winmm.mciSendStringW
        except Exception:
            self._mci = None

    @property
    def available(self) -> bool:
        return self._mci is not None

    def _send(self, command: str) -> int:
        if self._mci is None:
            return 1
        return self._mci(ctypes.c_wchar_p(command), None, 0, None)

    def load(self, path: str) -> bool:
        """打开音频文件 (自动关闭上一个)。成功返回 True。"""
        self.close()
        if self._mci is None:
            return False
        # 优先按 mpegvideo 打开 (mp3); 失败再让 MCI 自行推断类型
        if self._send(f'open "{path}" type mpegvideo alias {self._ALIAS}') != 0:
            if self._send(f'open "{path}" alias {self._ALIAS}') != 0:
                return False
        self._loaded = True
        return True

    def play_from_start(self):
        if self._loaded:
            self._send(f'seek {self._ALIAS} to start')
            self._send(f'play {self._ALIAS}')

    def resume(self):
        if self._loaded and self._send(f'resume {self._ALIAS}') != 0:
            self._send(f'play {self._ALIAS}')

    def pause(self):
        if self._loaded:
            self._send(f'pause {self._ALIAS}')

    def stop(self):
        if self._loaded:
            self._send(f'stop {self._ALIAS}')
            self._send(f'seek {self._ALIAS} to start')

    def mode(self) -> str:
        """返回播放状态: 'playing' / 'paused' / 'stopped' 等 (不可用时为空)。"""
        if not self._loaded or self._mci is None:
            return ""
        buf = ctypes.create_unicode_buffer(64)
        self._mci(ctypes.c_wchar_p(f'status {self._ALIAS} mode'), buf, 64, None)
        return buf.value or ""

    def close(self):
        if self._loaded:
            self._send(f'close {self._ALIAS}')
            self._loaded = False


class CustomMusicDialog(QDialog):
    """自定义音乐管理与导出/导入对话框。"""

    def __init__(self, mods_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义音乐")
        self.resize(820, 600)
        self._mods_dir = mods_dir

        self._entries: list[MusicEntry] = []
        self._sound_files: dict[str, str] = {}  # {lower_filename: full_path}
        self._temp_dirs: list[str] = []          # 导入时解压的临时目录
        self._export_meta: dict = {}             # 导入的元数据 → 作为下次导出默认值
        self._current_entry: MusicEntry | None = None
        self._cleaned = False

        # 音频播放器 (基于 Windows MCI, 无需 QtMultimedia, 可随打包运行)
        self._player = _AudioPlayer()
        self._current_source = ""        # 当前已载入的音频路径 (避免重复加载)
        self._poll_timer: QTimer | None = None  # 轮询播放状态, 更新标签

        # 不预设默认路径: 本工具面向各 MOD 开发者, Sound 目录由其自行浏览指定
        # (可选, 仅用于试听原版 BGM; 不指定也可正常编辑/导出)
        self._sound_dir = ""
        self._setup_ui()

        self._scan_sound_dir()
        self._build_base_entries()
        self._import_scanned_added_tracks()
        self._sort_entries()
        self._rebuild_table()

    # ────────────────────────────────────────────────
    # 初始化
    # ────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── 说明 ──
        hint = QLabel(
            "基础曲目 <b>0000–0028</b>、<b>0100</b> 为游戏内置 BGM，可「修改」覆盖但不可删除"
            "（对已修改项点「删除」= 清空修改）；「新增」曲目从 <b>0101</b> 起编号，用于扩展。"
            "<br/>新增时若文件名本身为数字则保留原编号，否则自动分配。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ── Sound 目录选择 ──
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        dir_row.addWidget(QLabel("Sound 目录:"))
        self._dir_edit = QLineEdit(self._sound_dir)
        self._dir_edit.setReadOnly(True)
        self._dir_edit.setPlaceholderText(
            "（可选）浏览到游戏 Sound 目录，仅用于试听原版 BGM")
        dir_row.addWidget(self._dir_edit, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._on_browse_sound_dir)
        dir_row.addWidget(btn_browse)
        btn_rescan = QPushButton("重新扫描")
        btn_rescan.clicked.connect(self._on_rescan)
        dir_row.addWidget(btn_rescan)
        layout.addLayout(dir_row)

        # ── 表格 ──
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(38)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_COL_OPS, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        # ── 底部操作 ──
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        btn_add = QPushButton("➕ 新增音效")
        btn_add.setToolTip(f"添加 .mp3 作为新曲目 (文件名为数字时保留原编号，否则从 {ADDED_SLOT_START:04d}.mp3 开始编号)")
        btn_add.clicked.connect(self._on_add)
        bottom.addWidget(btn_add)

        self._now_playing = QLabel("未播放")
        self._now_playing.setStyleSheet("color: #888;")
        bottom.addWidget(self._now_playing)

        bottom.addStretch()

        btn_import = QPushButton("📥 导入 .tksmod")
        btn_import.clicked.connect(self._on_import)
        bottom.addWidget(btn_import)
        btn_export = QPushButton("📤 导出为 .tksmod")
        btn_export.setObjectName("btnPack")
        btn_export.clicked.connect(self._on_export)
        bottom.addWidget(btn_export)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    # ────────────────────────────────────────────────
    # 扫描 / 条目构建
    # ────────────────────────────────────────────────

    def _scan_sound_dir(self):
        """扫描 Sound 目录中的所有 .mp3 文件。"""
        self._sound_files = {}
        if os.path.isdir(self._sound_dir):
            for fname in os.listdir(self._sound_dir):
                if fname.lower().endswith(".mp3"):
                    self._sound_files[fname.lower()] = os.path.join(self._sound_dir, fname)

    def _build_base_entries(self):
        """构建内置基础曲目 (0000~0028、0100), 保留已有的自定义修改。"""
        # 保留现有基础曲目的 custom_path (重新扫描时不丢失修改)
        prev_custom = {
            e.number: e.custom_path
            for e in self._entries if e.is_base and e.custom_path
        }
        base_entries = []
        for n in BASE_SLOT_NUMBERS:
            fname = f"{n:04d}.mp3"
            entry = MusicEntry(
                filename=fname, is_base=True,
                custom_path=prev_custom.get(n, ""),
                original_path=self._sound_files.get(fname.lower(), ""),
            )
            base_entries.append(entry)
        # 保留已有的新增曲目
        added = [e for e in self._entries if not e.is_base]
        self._entries = base_entries + added

    def _refresh_base_original_paths(self):
        """重新扫描后, 仅更新基础曲目的原始文件路径。"""
        for e in self._entries:
            if e.is_base:
                e.original_path = self._sound_files.get(e.filename.lower(), "")

    def _import_scanned_added_tracks(self):
        """将 Sound 目录中扫描到的非基础 .mp3 (如 0200.mp3) 载入为新增曲目。

        仅处理形如 NNNN.mp3 的文件; 已存在的条目不重复添加。
        这些文件本身即自定义音源, 其 custom_path 指向目录内的文件。
        """
        existing = {e.filename.lower() for e in self._entries}
        for lower_name, full_path in sorted(self._sound_files.items()):
            m = _MP3_NAME_RE.match(lower_name)
            if not m:
                continue
            num = int(m.group(1))
            if _is_base_number(num) or lower_name in existing:
                continue
            self._entries.append(MusicEntry(
                filename=f"{num:04d}.mp3", is_base=False, custom_path=full_path))
            existing.add(lower_name)

    def _sort_entries(self):
        """基础曲目在前 (按编号), 新增曲目在后 (按编号)。"""
        self._entries.sort(key=lambda e: (0 if e.is_base else 1, e.number))

    def _next_added_number(self) -> int:
        """返回下一个可用的新增编号 (>= 0200 且未被占用)。"""
        used = {e.filename.lower() for e in self._entries}
        n = ADDED_SLOT_START
        while f"{n:04d}.mp3" in used:
            n += 1
        return n

    # ────────────────────────────────────────────────
    # 表格渲染
    # ────────────────────────────────────────────────

    def _rebuild_table(self):
        """根据 self._entries 重建整张表格。"""
        self._table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            # 文件名
            name_item = QTableWidgetItem(entry.filename)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            tag = "内置" if entry.is_base else "新增"
            name_item.setToolTip(f"{entry.filename} ({tag})")
            self._table.setItem(row, _COL_NAME, name_item)

            # 状态
            self._table.setItem(row, _COL_STATUS, self._make_status_item(entry))

            # 操作
            self._table.setCellWidget(row, _COL_OPS, self._make_ops_widget(entry))

    def _make_status_item(self, entry: MusicEntry) -> QTableWidgetItem:
        modified = entry.is_modified
        item = QTableWidgetItem("已修改" if modified else "未修改")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(QColor(COLOR_MODIFIED if modified else COLOR_UNMODIFIED))
        return item

    def _make_ops_widget(self, entry: MusicEntry) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        def add_btn(text, tip, slot, enabled=True):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedHeight(26)
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(enabled)
            b.clicked.connect(lambda _=False, e=entry: slot(e))
            lay.addWidget(b)
            return b

        add_btn("播放", "试听该曲目", self._on_play)
        add_btn("暂停", "暂停播放", self._on_pause)
        add_btn("重置", "停止并回到开头", self._on_reset)
        add_btn("修改", "选择 .mp3 覆盖此曲目", self._on_modify)
        if not entry.is_base:
            add_btn("重命名", "修改此曲目的文件编号", self._on_rename)
        del_enabled = (not entry.is_base) or entry.is_modified
        del_tip = ("移除该新增曲目" if not entry.is_base
                   else "清空此曲目的修改 (变回未修改)")
        add_btn("删除", del_tip, self._on_delete, enabled=del_enabled)

        lay.addStretch()
        return w

    def _find_row(self, entry: MusicEntry) -> int:
        try:
            return self._entries.index(entry)
        except ValueError:
            return -1

    def _refresh_row(self, entry: MusicEntry):
        """仅刷新某条目的状态列与操作列 (修改/清空后)。"""
        row = self._find_row(entry)
        if row < 0:
            return
        self._table.setItem(row, _COL_STATUS, self._make_status_item(entry))
        self._table.setCellWidget(row, _COL_OPS, self._make_ops_widget(entry))

    # ────────────────────────────────────────────────
    # Sound 目录操作
    # ────────────────────────────────────────────────

    def _on_browse_sound_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 Sound 目录", self._sound_dir)
        if not d:
            return
        self._sound_dir = d
        self._dir_edit.setText(d)
        self._on_rescan()

    def _on_rescan(self):
        self._scan_sound_dir()
        self._refresh_base_original_paths()
        self._import_scanned_added_tracks()
        self._sort_entries()
        self._rebuild_table()

    # ────────────────────────────────────────────────
    # 播放控制
    # ────────────────────────────────────────────────

    def _on_play(self, entry: MusicEntry):
        src = entry.play_source
        if not src:
            themed_messagebox(
                self, QMessageBox.Information, "无法播放",
                f"「{entry.filename}」暂无可播放的音频。\n"
                "请先点「修改」添加自定义 .mp3，或确认 Sound 目录中存在原始曲目。")
            return
        if not self._player.available:
            themed_messagebox(
                self, QMessageBox.Information, "无法播放",
                "当前环境不支持音频播放 (缺少 Windows 多媒体支持)。")
            return
        if src != self._current_source:
            # 载入新音源并从头播放
            if not self._player.load(src):
                self._current_source = ""
                self._current_entry = None
                themed_messagebox(
                    self, QMessageBox.Warning, "播放失败",
                    f"无法加载音频：\n{src}")
                self._update_now_playing()
                return
            self._current_source = src
            self._current_entry = entry
            self._player.play_from_start()
        elif self._player.mode() == "paused":
            # 同一音源且暂停中 → 从当前位置恢复
            self._current_entry = entry
            self._player.resume()
        else:
            # 同一音源且已停止/播放中 → 从头播放
            self._current_entry = entry
            self._player.play_from_start()
        self._update_now_playing()

    def _on_pause(self, entry: MusicEntry):
        if self._current_entry is entry and self._player.mode() == "playing":
            self._player.pause()
            self._update_now_playing()

    def _on_reset(self, entry: MusicEntry):
        if self._current_entry is entry:
            self._player.stop()
            self._update_now_playing()

    def _update_now_playing(self):
        mode = self._player.mode()
        name = self._current_entry.filename if self._current_entry else ""
        if mode == "playing" and name:
            self._now_playing.setText(f"正在播放：{name}")
            self._now_playing.setStyleSheet(f"color: {COLOR_MODIFIED};")
        elif mode == "paused" and name:
            self._now_playing.setText(f"已暂停：{name}")
            self._now_playing.setStyleSheet("color: #888;")
        else:
            self._now_playing.setText("未播放")
            self._now_playing.setStyleSheet("color: #888;")

    # ────────────────────────────────────────────────
    # 修改 / 删除 / 新增
    # ────────────────────────────────────────────────

    def _pick_mp3(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "MP3 音频 (*.mp3);;所有文件 (*)")
        if not path:
            return ""
        if not path.lower().endswith(".mp3"):
            themed_messagebox(self, QMessageBox.Warning, "格式错误", "只能选择 .mp3 文件。")
            return ""
        return path

    def _on_modify(self, entry: MusicEntry):
        path = self._pick_mp3(f"选择覆盖「{entry.filename}」的 MP3")
        if not path:
            return
        entry.custom_path = path
        self._refresh_row(entry)

    def _on_delete(self, entry: MusicEntry):
        if entry.is_base:
            # 基础曲目: 清空修改, 变回未修改
            if not entry.is_modified:
                return
            # 若正在播放该曲目的自定义音频, 先关闭以释放文件占用
            if self._current_entry is entry:
                self._player.close()
                self._current_source = ""
                self._current_entry = None
            entry.custom_path = ""
            self._refresh_row(entry)
        else:
            # 新增曲目: 整条移除
            if self._current_entry is entry:
                self._player.close()
                self._current_source = ""
                self._current_entry = None
            self._entries.remove(entry)
            self._rebuild_table()

    def _on_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要新增的 MP3 音频（可多选）", "",
            "MP3 音频 (*.mp3);;所有文件 (*)")
        if not paths:
            return
        added = 0
        skipped = 0
        used = {e.filename.lower() for e in self._entries}
        for path in paths:
            if not path.lower().endswith(".mp3"):
                skipped += 1
                continue
            # 检查原始文件名 (不含扩展名) 是否为纯数字
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem.isdigit():
                # 文件名为数字 → 保留原编号
                n = int(stem)
                target_fname = f"{n:04d}.mp3"
                if target_fname.lower() in used:
                    # 编号已存在 → 视为修改已有条目
                    existing = next(
                        (e for e in self._entries
                         if e.filename.lower() == target_fname.lower()), None)
                    if existing:
                        existing.custom_path = path
                        added += 1
                        continue
                # 基础曲目编号 → 修改对应基础条目
                if _is_base_number(n):
                    existing = next(
                        (e for e in self._entries if e.number == n and e.is_base), None)
                    if existing:
                        existing.custom_path = path
                        added += 1
                        continue
            else:
                # 文件名非数字 → 从 ADDED_SLOT_START 自动分配
                n = self._next_added_number()
                target_fname = f"{n:04d}.mp3"
            self._entries.append(MusicEntry(
                filename=target_fname, is_base=False, custom_path=path))
            used.add(target_fname.lower())
            added += 1
        if added:
            self._sort_entries()
            self._rebuild_table()
        if skipped:
            themed_messagebox(
                self, QMessageBox.Warning, "部分文件已跳过",
                f"已忽略 {skipped} 个非 .mp3 文件。")

    def _on_rename(self, entry: MusicEntry):
        """重命名非基础曲目的文件编号。"""
        from PySide6.QtWidgets import QInputDialog
        current_num = str(entry.number) if entry.number >= 0 else ""
        new_num_str, ok = QInputDialog.getText(
            self, "重命名曲目",
            f"当前编号: {entry.filename}\n请输入新的编号 (纯数字):",
            text=current_num)
        if not ok or not new_num_str.strip():
            return
        new_num_str = new_num_str.strip()
        if not new_num_str.isdigit():
            themed_messagebox(
                self, QMessageBox.Warning, "编号无效",
                "编号必须为纯数字。")
            return
        new_num = int(new_num_str)
        new_fname = f"{new_num:04d}.mp3"
        # 检查冲突
        if new_fname.lower() == entry.filename.lower():
            return  # 未变化
        if any(e.filename.lower() == new_fname.lower() for e in self._entries):
            themed_messagebox(
                self, QMessageBox.Warning, "编号冲突",
                f"编号 {new_fname} 已被占用，请选择其他编号。")
            return
        # 更新
        entry.filename = new_fname
        entry.number = new_num
        self._sort_entries()
        self._rebuild_table()

    # ────────────────────────────────────────────────
    # 导出
    # ────────────────────────────────────────────────

    def _export_defaults(self) -> dict:
        """导出元数据的默认值 (导入过则沿用导入的元数据)。"""
        if self._export_meta:
            d = dict(self._export_meta)
            d.setdefault("load_order", MOD_LOAD_ORDER_DEFAULT)
            return d
        return {
            "id": generate_short_uuid(),
            "name": MOD_NAME_DEFAULT,
            "version": "1.0.0",
            "author": MOD_AUTHOR_DEFAULT,
            "description": MOD_DESC_DEFAULT,
            "load_order": MOD_LOAD_ORDER_DEFAULT,
        }

    def _on_export(self):
        # 收集所有已修改/新增曲目
        modified = [e for e in self._entries if e.is_modified]
        if not modified:
            themed_messagebox(
                self, QMessageBox.Information, "无内容可导出",
                "当前没有任何自定义音乐。\n请先「修改」覆盖内置曲目或「新增」曲目后再导出。")
            return

        # 校验源文件存在
        missing = [e.filename for e in modified if not os.path.isfile(e.custom_path)]
        if missing:
            themed_messagebox(
                self, QMessageBox.Warning, "源文件缺失",
                "以下曲目的 .mp3 源文件已不存在，请重新「修改」：\n" + "、".join(missing))
            return

        # 元数据对话框
        dlg = ModMetadataDialog(self, defaults=self._export_defaults())
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()

        # 构建 resources
        resources = []
        resource_files = {}
        for e in modified:
            internal = f"resources/{SOUND_SUBDIR}/{e.filename}"
            resources.append({"file": internal, "target": f"{SOUND_SUBDIR}/{e.filename}"})
            resource_files[internal] = e.custom_path

        # 输出路径
        default_name = safe_mod_filename(
            metadata.get("name", ""), metadata.get("id", "music")) + ".tksmod"
        out, _ = QFileDialog.getSaveFileName(
            self, "保存音乐 MOD", os.path.join(self._mods_dir, default_name),
            "TKS 模组 (*.tksmod);;所有文件 (*)")
        if not out:
            return
        if not out.lower().endswith(".tksmod"):
            out += ".tksmod"

        mod_json = generate_mod_json(metadata, components=[], resources=resources)
        try:
            pack_tksmod(
                out, mod_json, data_files={}, resource_files=resource_files,
                preview_image_path=metadata.get("preview_image_path", ""))
        except Exception as e:
            themed_messagebox(self, QMessageBox.Critical, "导出失败", f"打包 MOD 时出错：\n{e}")
            return

        # 记住元数据供再次导出
        self._export_meta = {
            "id": metadata.get("id", ""),
            "name": metadata.get("name", ""),
            "version": metadata.get("version", "1.0.0"),
            "author": metadata.get("author", ""),
            "description": metadata.get("description", ""),
            "load_order": metadata.get("load_order", MOD_LOAD_ORDER_DEFAULT),
        }

        base_cnt = sum(1 for e in modified if e.is_base)
        add_cnt = len(modified) - base_cnt
        themed_messagebox(
            self, QMessageBox.Information, "导出成功",
            f"音乐 MOD 已保存到：\n{out}\n\n"
            f"包含：{base_cnt} 条覆盖曲目、{add_cnt} 条新增曲目。")

    # ────────────────────────────────────────────────
    # 导入
    # ────────────────────────────────────────────────

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音乐 MOD", self._mods_dir,
            "TKS 模组 (*.tksmod);;所有文件 (*)")
        if not path:
            return

        # 若已有修改, 确认覆盖
        if any(e.is_modified for e in self._entries):
            ret = QMessageBox.question(
                self, "确认导入",
                "导入将替换当前所有编辑内容，是否继续？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        try:
            base_overrides, added_tracks, meta = self._read_music_mod(path)
        except Exception as e:
            themed_messagebox(self, QMessageBox.Critical, "导入失败", f"读取 MOD 时出错：\n{e}")
            return

        if not base_overrides and not added_tracks:
            themed_messagebox(
                self, QMessageBox.Information, "无音乐数据",
                "该 .tksmod 未包含任何 Sound/ 音乐资源。")
            return

        # 停止播放, 重置状态
        self._player.close()
        self._current_source = ""
        self._current_entry = None

        # 重建基础曲目 (先清空当前修改)
        self._entries = []
        self._build_base_entries()
        by_number = {e.number: e for e in self._entries if e.is_base}
        for num, temp_path in base_overrides.items():
            if num in by_number:
                by_number[num].custom_path = temp_path
        for num, temp_path in sorted(added_tracks.items()):
            self._entries.append(MusicEntry(
                filename=f"{num:04d}.mp3", is_base=False, custom_path=temp_path))

        self._sort_entries()
        self._export_meta = meta
        self._rebuild_table()

        themed_messagebox(
            self, QMessageBox.Information, "导入成功",
            f"已导入：{len(base_overrides)} 条覆盖曲目、{len(added_tracks)} 条新增曲目。\n"
            "可继续编辑后重新导出。")

    def _read_music_mod(self, mod_path: str):
        """从 .tksmod 读取音乐资源, 解压到临时目录。

        返回 (base_overrides, added_tracks, meta)
          base_overrides: {number: temp_mp3_path}  基础曲目覆盖 (0000~0028、0100)
          added_tracks:   {number: temp_mp3_path}  新增曲目 (非基础编号, 如 0200+)
          meta:           mod.json 元数据 (供再次导出)
        """
        tmp = tempfile.mkdtemp(prefix="tks_music_")
        self._temp_dirs.append(tmp)

        base_overrides: dict[int, str] = {}
        added_tracks: dict[int, str] = {}
        meta: dict = {}

        with zipfile.ZipFile(mod_path, 'r') as zf:
            names = set(zf.namelist())
            if "mod.json" not in names:
                raise ValueError("缺少 mod.json")
            mj = json.loads(zf.read("mod.json").decode('utf-8'))
            meta = {
                "id": mj.get("id", generate_short_uuid()),
                "name": mj.get("name", MOD_NAME_DEFAULT),
                "version": mj.get("version", "1.0.0"),
                "author": mj.get("author", MOD_AUTHOR_DEFAULT),
                "description": mj.get("description", MOD_DESC_DEFAULT),
                "load_order": mj.get("load_order", MOD_LOAD_ORDER_DEFAULT),
            }

            for res in mj.get("resources", []):
                target = str(res.get("target", "")).replace("\\", "/")
                internal = res.get("file", "")
                basename = os.path.basename(target)
                m = _MP3_NAME_RE.match(basename)
                if not m or internal not in names:
                    continue
                num = int(m.group(1))
                out_path = os.path.join(tmp, basename)
                with zf.open(internal) as src, open(out_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                if _is_base_number(num):
                    base_overrides[num] = out_path
                else:
                    added_tracks[num] = out_path

        return base_overrides, added_tracks, meta

    # ────────────────────────────────────────────────
    # 清理
    # ────────────────────────────────────────────────

    def _cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        if self._poll_timer is not None:
            self._poll_timer.stop()
        try:
            self._player.close()
        except Exception:
            pass
        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._temp_dirs.clear()

    def showEvent(self, event):
        super().showEvent(event)
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._update_now_playing)
        self._poll_timer.start(500)

    def hideEvent(self, event):
        if self._poll_timer is not None:
            self._poll_timer.stop()
        super().hideEvent(event)

    def done(self, result):
        self._cleanup()
        super().done(result)

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

