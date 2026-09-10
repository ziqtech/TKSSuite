"""生成启动器对话框 — 选中 cave 型补丁，烧录进原版 TKS.exe 生成独立修改版"""
import os
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)
from core.config_loader import PatchDef
from core.exe_builder import ExeBuilder, CavePatchItem


def _parse_hex_bytes(s: str) -> bytes:
    """将 '8B 44 24 1C' 转为 bytes。"""
    return bytes(int(p, 16) for p in s.split())


class _BuildWorker(QThread):
    """后台构建线程。"""
    finished = Signal(object)  # CaveBuildResult

    def __init__(self, builder: ExeBuilder, patches: list, output_path: str):
        super().__init__()
        self._builder = builder
        self._patches = patches
        self._output = output_path

    def run(self):
        result = self._builder.build(self._patches, self._output)
        self.finished.emit(result)


class GenerateExeDialog(QDialog):
    """生成启动器对话框。

    流程：
      1. 选择原版 TKS.exe
      2. 勾选要烧录的 cave 型补丁
      3. 选择输出路径
      4. 点击生成
    """

    def __init__(self, patches: list[PatchDef], launcher_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('生成启动器 — 将补丁烧录进 TKS.exe')
        self.setMinimumSize(700, 550)
        self._patches = patches
        self._launcher_dir = launcher_dir
        self._worker: _BuildWorker | None = None

        self._setup_ui()
        self._populate_patch_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 原版 exe 选择 ──
        src_group = QGroupBox('原版 TKS.exe')
        src_layout = QHBoxLayout(src_group)
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText('选择原版 TKS.exe 路径…')
        # 默认尝试常见位置
        default_exe = os.path.join(os.path.dirname(self._launcher_dir), 'TKS', 'TKS.exe')
        if os.path.isfile(default_exe):
            self._src_edit.setText(default_exe)
        src_btn = QPushButton('浏览…')
        src_btn.clicked.connect(self._browse_src)
        src_layout.addWidget(self._src_edit, 1)
        src_layout.addWidget(src_btn)
        layout.addWidget(src_group)

        # ── 补丁选择 ──
        patch_group = QGroupBox('选择要烧录的补丁（仅显示 cave 型）')
        patch_layout = QVBoxLayout(patch_group)

        btn_row = QHBoxLayout()
        btn_all = QPushButton('全选')
        btn_none = QPushButton('全不选')
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        patch_layout.addLayout(btn_row)

        self._patch_list = QListWidget()
        self._patch_list.setSelectionMode(QListWidget.NoSelection)
        patch_layout.addWidget(self._patch_list)

        self._patch_detail = QTextEdit()
        self._patch_detail.setReadOnly(True)
        self._patch_detail.setMaximumHeight(100)
        patch_layout.addWidget(self._patch_detail)

        self._patch_list.currentRowChanged.connect(self._on_patch_selected)
        layout.addWidget(patch_group, 1)

        # ── 输出路径 ──
        out_group = QGroupBox('输出路径')
        out_layout = QHBoxLayout(out_group)
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText('输出修改版 exe 路径…')
        out_btn = QPushButton('浏览…')
        out_btn.clicked.connect(self._browse_out)
        out_layout.addWidget(self._out_edit, 1)
        out_layout.addWidget(out_btn)
        layout.addWidget(out_group)

        # ── 进度与日志 ──
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        layout.addWidget(self._log_text)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        self._build_btn = QPushButton('生成')
        self._build_btn.clicked.connect(self._start_build)
        cancel_btn = QPushButton('关闭')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self._build_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _populate_patch_list(self):
        """填充 cave 型补丁列表。"""
        for p in self._patches:
            # 仅显示有 hook_pattern 和 cave_code 的补丁
            if not p.hook_pattern or not p.cave_template:
                continue
            item = QListWidgetItem()
            item.setText(f'{p.name}  ({p.id})')
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p.default_checked else Qt.Unchecked)
            item.setData(Qt.UserRole, p)
            self._patch_list.addItem(item)

        if self._patch_list.count() == 0:
            self._patch_list.addItem('（未找到 cave 型补丁）')

    def _set_all(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self._patch_list.count()):
            item = self._patch_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)

    def _on_patch_selected(self, row: int):
        item = self._patch_list.item(row)
        if item is None:
            return
        p = item.data(Qt.UserRole)
        if p is None:
            self._patch_detail.clear()
            return
        detail = (
            f'名称: {p.name}\n'
            f'ID: {p.id}\n'
            f'描述: {p.desc}\n'
            f'hook_pattern: {p.hook_pattern}\n'
            f'hook_size: {p.hook_size}\n'
            f'cave 长度: {len(_parse_hex_bytes(p.cave_template)) if p.cave_template else 0} 字节\n'
            f'fallback_rva: 0x{p.fallback_rva:X}' if p.fallback_rva else
            f'名称: {p.name}\n'
            f'ID: {p.id}\n'
            f'描述: {p.desc}\n'
            f'hook_pattern: {p.hook_pattern}\n'
            f'hook_size: {p.hook_size}\n'
            f'cave 长度: {len(_parse_hex_bytes(p.cave_template)) if p.cave_template else 0} 字节'
        )
        self._patch_detail.setPlainText(detail)

    def _browse_src(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择原版 TKS.exe', '', '可执行文件 (*.exe)')
        if path:
            self._src_edit.setText(path)
            # 自动填充输出路径
            if not self._out_edit.text():
                base, ext = os.path.splitext(path)
                self._out_edit.setText(f'{base}_MOD{ext}')

    def _browse_out(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '输出修改版 exe', '', '可执行文件 (*.exe)')
        if path:
            self._out_edit.setText(path)

    def _get_selected_patches(self) -> list[CavePatchItem]:
        """收集勾选的补丁，转为 CavePatchItem。"""
        items = []
        for i in range(self._patch_list.count()):
            list_item = self._patch_list.item(i)
            if list_item.checkState() != Qt.Checked:
                continue
            p: PatchDef = list_item.data(Qt.UserRole)
            if p is None:
                continue
            try:
                cave_code = _parse_hex_bytes(p.cave_template)
                hook_pattern = _parse_hex_bytes(p.hook_pattern)
            except (ValueError, AttributeError) as e:
                self._log(f'[{p.id}] 解析补丁数据失败: {e}')
                continue
            items.append(CavePatchItem(
                patch_id=p.id,
                name=p.name,
                hook_pattern=hook_pattern,
                hook_size=p.hook_size or 5,
                cave_code=cave_code,
                fallback_rva=p.fallback_rva,
                expect_count=p.hook_expect_count or 1,
            ))
        return items

    def _log(self, msg: str):
        self._log_text.append(msg)

    def _start_build(self):
        src = self._src_edit.text().strip()
        out = self._out_edit.text().strip()

        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, '错误', '请选择有效的原版 TKS.exe')
            return
        if not out:
            QMessageBox.warning(self, '错误', '请指定输出路径')
            return

        patches = self._get_selected_patches()
        if not patches:
            QMessageBox.warning(self, '错误', '请至少勾选一个 cave 型补丁')
            return

        # 确认
        patch_names = ', '.join(p.name for p in patches)
        ret = QMessageBox.question(
            self, '确认生成',
            f'将以下补丁烧录进 TKS.exe：\n\n{patch_names}\n\n'
            f'输出: {out}\n\n继续？',
            QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        self._build_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # 不确定进度
        self._log_text.clear()
        self._log('开始构建…')

        try:
            builder = ExeBuilder(src)
        except Exception as e:
            self._log(f'读取原版 exe 失败: {e}')
            QMessageBox.critical(self, '错误', f'读取原版 exe 失败:\n{e}')
            self._build_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        self._worker = _BuildWorker(builder, patches, out)
        self._worker.finished.connect(self._on_build_finished)
        self._worker.start()

    def _on_build_finished(self, result):
        self._build_btn.setEnabled(True)
        self._progress.setVisible(False)

        for line in result.log:
            self._log(line)

        if result.success:
            self._log('构建成功！')
            QMessageBox.information(
                self, '成功',
                f'修改版 exe 已生成：\n{result.output_path}\n\n'
                f'可直接分发给玩家，无需启动器。')
        else:
            self._log(f'构建失败: {result.error}')
            QMessageBox.critical(self, '失败', f'构建失败:\n{result.error}')
