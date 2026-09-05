"""模组拆分对话框 — 从 .tksmodpak 合集文件中提取原始模组"""
import os
import zipfile

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout,
)

from core.mod_packer import extract_tksmodpak
from editor_utils.task_runner import run_background, is_running


class ModSplitterDialog(QDialog):
    """模组拆分对话框 — 选择 .tksmodpak 合集文件，提取其中的原始模组。"""

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self.setWindowTitle("模组拆分")
        self.resize(520, 420)
        self._mods_dir = mods_dir
        self._pack_path: str = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- 合集包选择 ----
        pkg_group = QGroupBox("合集文件")
        pkg_layout = QVBoxLayout(pkg_group)

        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("合集文件:"))
        self.edit_pkg_path = QLineEdit()
        self.edit_pkg_path.setReadOnly(True)
        self.edit_pkg_path.setPlaceholderText("点击「打开」按钮选择 .tksmodpak 文件")
        pkg_row.addWidget(self.edit_pkg_path, 1)
        btn_open = QPushButton("打开…")
        btn_open.clicked.connect(self._on_open)
        pkg_row.addWidget(btn_open)
        pkg_layout.addLayout(pkg_row)

        # 内容预览
        self._preview_list = QListWidget()
        self._preview_list.setMinimumHeight(140)
        pkg_layout.addWidget(QLabel("包含的模组:"))
        pkg_layout.addWidget(self._preview_list)
        layout.addWidget(pkg_group)

        # ---- 输出目录 ----
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录:"))
        self.edit_out_dir = QLineEdit()
        self.edit_out_dir.setPlaceholderText("拆分后的 .tksmod 文件输出目录")
        out_row.addWidget(self.edit_out_dir, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._on_browse_out)
        out_row.addWidget(btn_browse)
        layout.addLayout(out_row)

        # ---- 日志 ----
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMaximumHeight(100)
        self._log_area.setPlaceholderText("拆分日志将显示在这里...")
        layout.addWidget(self._log_area)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_split = QPushButton("执行拆分")
        self._btn_split.setObjectName("btnPack")
        self._btn_split.setEnabled(False)
        self._btn_split.clicked.connect(self._on_split)
        btn_row.addWidget(self._btn_split)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    # ────────────────────────────────────────────────
    # 打开合集包
    # ────────────────────────────────────────────────

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 .tksmodpak 文件", self._mods_dir,
            "TKS 模组合集 (*.tksmodpak);;所有文件 (*)"
        )
        if not path:
            return
        self._load_package(path)

    def _load_package(self, path: str):
        self._pack_path = path
        self.edit_pkg_path.setText(path)
        self._preview_list.clear()
        self._log_area.clear()
        self._btn_split.setEnabled(False)

        try:
            with zipfile.ZipFile(path, 'r') as zf:
                mods = sorted(
                    n for n in zf.namelist()
                    if n.lower().endswith(".tksmod") and not n.endswith("/")
                )
                if not mods:
                    self._preview_list.addItem("（未找到 .tksmod 文件）")
                    return

                for entry in mods:
                    try:
                        info = zf.getinfo(entry)
                        size_kb = info.file_size / 1024
                        label = f"{os.path.basename(entry)}  ({size_kb:.1f} KB)"
                    except Exception:
                        label = entry
                    item = QListWidgetItem(label)
                    item.setToolTip(entry)
                    self._preview_list.addItem(item)

                self._btn_split.setEnabled(True)

                if not self.edit_out_dir.text().strip():
                    self.edit_out_dir.setText(self._mods_dir)

        except Exception as e:
            self._preview_list.addItem(f"读取失败: {e}")

    # ────────────────────────────────────────────────
    # 输出目录
    # ────────────────────────────────────────────────

    def _on_browse_out(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择输出目录",
            self.edit_out_dir.text() or self._mods_dir
        )
        if dir_path:
            self.edit_out_dir.setText(dir_path)

    # ────────────────────────────────────────────────
    # 执行拆分
    # ────────────────────────────────────────────────

    def _on_split(self):
        if not self._pack_path:
            QMessageBox.warning(self, "提示", "请先选择要拆分的合集包")
            return

        out_dir = self.edit_out_dir.text().strip()
        if not out_dir:
            out_dir = self._mods_dir
            self.edit_out_dir.setText(out_dir)

        self._log_area.clear()
        self._btn_split.setEnabled(False)

        def log(msg):
            self._log_area.append(msg)

        log(f"开始拆分: {os.path.basename(self._pack_path)}")
        log(f"输出目录: {out_dir}")
        log("")

        # 后台线程执行拆分 (P3-3): 日志经信号排队回 UI 线程
        pack_path = self._pack_path

        def work(w):
            return extract_tksmodpak(pack_path, out_dir, log_func=w.progress)

        self._split_worker = run_background(
            self, work,
            on_success=self._on_split_done,
            on_progress=log)

    def _on_split_done(self, result):
        self._btn_split.setEnabled(True)
        out_dir = self.edit_out_dir.text().strip() or self._mods_dir

        def log(msg):
            self._log_area.append(msg)

        if result["success"]:
            n = len(result["extracted"])
            log(f"\n✅ 拆分完成！已提取 {n} 个模组文件")
            QMessageBox.information(
                self, "拆分完成",
                f"已成功提取 {n} 个模组文件到:\n{out_dir}"
            )
        else:
            log(f"\n❌ 拆分失败: {result['error']}")
            QMessageBox.critical(self, "拆分失败", result["error"])
