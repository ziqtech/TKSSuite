"""生成启动器对话框 — 选中补丁，烧录进原版 TKS.exe 生成独立修改版

支持的补丁类型：
  - cave_hook / patch_exp_lock: 代码洞注入（.test 节 + jmp hook）
  - patch_bytes: 模式搜索 + 字节替换
  - patch_imm32: 立即数修改（静态值）
"""
import os
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)
from core.config_loader import PatchDef
from core.exe_builder import (
    ExeBuilder, CavePatchItem, BytesPatchItem, BytesPatchEntry,
    Imm32PatchItem, Imm32PatchEntry, ConfigPatchItem,
)
from core.tkspatch_loader import get_external_cave_code


class _BuildWorker(QThread):
    """后台构建线程。"""
    finished = Signal(object)  # CaveBuildResult

    def __init__(self, builder: ExeBuilder, cave_patches: list,
                 bytes_patches: list, imm32_patches: list,
                 config_patches: list, output_path: str):
        super().__init__()
        self._builder = builder
        self._cave_patches = cave_patches
        self._bytes_patches = bytes_patches
        self._imm32_patches = imm32_patches
        self._config_patches = config_patches
        self._output = output_path

    def run(self):
        result = self._builder.build(
            self._cave_patches, self._output,
            bytes_patches=self._bytes_patches,
            imm32_patches=self._imm32_patches,
            config_patches=self._config_patches,
        )
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
        self.setMinimumSize(750, 650)
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
        patch_group = QGroupBox('选择要烧录的补丁（支持代码注入/字节替换/立即数/配置驱动）')
        patch_layout = QVBoxLayout(patch_group)

        # 统计标签
        self._summary_label = QLabel('')
        self._summary_label.setStyleSheet('color: #888; font-size: 11px;')
        patch_layout.addWidget(self._summary_label)

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
        """填充可烧录的补丁列表，并显示不支持的补丁。"""
        unsupported = []
        supported_count = 0
        for p in self._patches:
            # cave_hook 型：需要 hook_pattern 和外置 cave 代码
            if p.type in ('cave_hook', 'patch_exp_lock'):
                if p.hook_pattern and get_external_cave_code(p):
                    self._add_patch_item(p, '代码注入')
                    supported_count += 1
                continue
            # patch_bytes 型：需要 pattern 和 replace
            if p.type == 'patch_bytes':
                if (p.pattern and p.replace) or p.patterns:
                    self._add_patch_item(p, '字节替换')
                    supported_count += 1
                continue
            # patch_imm32 型：需要 pattern 和 new_value_expr（静态值），或 value_scan 模式
            if p.type == 'patch_imm32':
                if p.pattern and p.new_value_expr:
                    self._add_patch_item(p, '立即数')
                    supported_count += 1
                elif p.value_scan and p.expect_value and p.new_value_expr:
                    self._add_patch_item(p, '立即数(值扫描)')
                    supported_count += 1
                continue
            # 配置驱动型
            if p.type in ('drop_probability', 'patch_drop_probability',
                          'font_config', 'patch_font_config',
                          'animation_speed', 'patch_animation_speed',
                          'summon_table', 'patch_summon_table'):
                if p.json_file:
                    self._add_patch_item(p, '配置驱动')
                    supported_count += 1
                continue
            # 不支持的类型
            unsupported.append(p)

        if self._patch_list.count() == 0:
            self._patch_list.addItem('（未找到可烧录的补丁）')

        # 显示统计信息
        total = len(self._patches)
        unsupported_count = len(unsupported)
        self._summary_label.setText(
            f'可烧录: {supported_count}/{total} 个补丁'
            + (f'（{unsupported_count} 个暂不支持：script 型需运行时内存操作）' if unsupported_count else '')
        )

        # 在日志中记录不支持的补丁
        for p in unsupported:
            reason = {
                'script': '需要运行时内存操作（VirtualAllocEx/WriteProcessMemory）',
                'patch_warpc_addr': '由 WarPC 扩展流程处理',
            }.get(p.type, '未知原因')
            self._log(f'[{p.id}] 类型 {p.type} 暂不支持文件级烧录: {reason}')

    def _add_patch_item(self, p: PatchDef, type_label: str):
        """添加一个补丁到列表。"""
        item = QListWidgetItem()
        item.setText(f'{p.name}  [{type_label}]')
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if p.default_checked else Qt.Unchecked)
        item.setData(Qt.UserRole, p)
        item.setData(Qt.UserRole + 1, type_label)
        self._patch_list.addItem(item)

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
        lines = [
            f'名称: {p.name}',
            f'ID: {p.id}',
            f'类型: {p.type}',
            f'描述: {p.desc}',
        ]
        if p.type in ('cave_hook', 'patch_exp_lock'):
            cave_code = get_external_cave_code(p)
            lines.append(f'hook_pattern: {p.hook_pattern}')
            lines.append(f'hook_size: {p.hook_size}')
            lines.append(f'cave 代码: {len(cave_code) if cave_code else 0} 字节')
            if p.fallback_rva:
                lines.append(f'fallback_rva: 0x{p.fallback_rva:X}')
        elif p.type == 'patch_bytes':
            if p.patterns:
                lines.append(f'多模式: {len(p.patterns)} 条规则')
                for i, entry in enumerate(p.patterns[:3]):
                    lines.append(f'  [{i}] pattern: {entry.get("pattern", "")[:40]}...')
            else:
                lines.append(f'pattern: {p.pattern[:50]}...' if len(p.pattern) > 50 else f'pattern: {p.pattern}')
                lines.append(f'replace: {p.replace}')
        elif p.type == 'patch_imm32':
            lines.append(f'new_value: {p.new_value_expr}')
            if p.patterns:
                lines.append(f'多模式: {len(p.patterns)} 条规则')
                for i, entry in enumerate(p.patterns[:3]):
                    lines.append(f'  [{i}] pattern: {entry.get("pattern", "")[:40]}...')
            elif p.pattern:
                lines.append(f'pattern: {p.pattern[:50]}...' if len(p.pattern) > 50 else f'pattern: {p.pattern}')
                lines.append(f'value_offset: {p.value_offset}')
        self._patch_detail.setPlainText('\n'.join(lines))

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

    def _get_selected_patches(self) -> tuple:
        """收集勾选的补丁，按类型分组返回。

        Returns:
            (cave_patches, bytes_patches, imm32_patches, config_patches)
        """
        cave_patches = []
        bytes_patches = []
        imm32_patches = []
        config_patches = []

        for i in range(self._patch_list.count()):
            list_item = self._patch_list.item(i)
            if list_item.checkState() != Qt.Checked:
                continue
            p: PatchDef = list_item.data(Qt.UserRole)
            if p is None:
                continue

            # cave_hook / patch_exp_lock
            if p.type in ('cave_hook', 'patch_exp_lock'):
                cave_code = get_external_cave_code(p)
                if not cave_code:
                    self._log(f'[{p.id}] 无外置 cave 代码，跳过')
                    continue
                try:
                    hook_pattern = bytes(int(t, 16) for t in p.hook_pattern.split())
                except (ValueError, AttributeError) as e:
                    self._log(f'[{p.id}] hook_pattern 解析失败: {e}')
                    continue
                cave_patches.append(CavePatchItem(
                    patch_id=p.id, name=p.name,
                    hook_pattern=hook_pattern,
                    hook_size=p.hook_size or 5,
                    cave_code=cave_code,
                    fallback_rva=p.fallback_rva,
                    expect_count=p.hook_expect_count or 1,
                ))

            # patch_bytes
            elif p.type == 'patch_bytes':
                entries = []
                if p.patterns:
                    for entry in p.patterns:
                        entries.append(BytesPatchEntry(
                            pattern=entry.get('pattern', ''),
                            replace={int(k): v for k, v in entry.get('replace', {}).items()},
                            expect_count=entry.get('expect_count', 0),
                        ))
                elif p.pattern and p.replace:
                    entries.append(BytesPatchEntry(
                        pattern=p.pattern,
                        replace={int(k): v for k, v in p.replace.items()},
                        expect_count=p.expect_count or 0,
                    ))
                if entries:
                    bytes_patches.append(BytesPatchItem(
                        patch_id=p.id, name=p.name, entries=entries,
                    ))

            # patch_imm32
            elif p.type == 'patch_imm32':
                new_value = self._resolve_imm32_value(p)
                if new_value is None:
                    self._log(f'[{p.id}] new_value 无法解析为静态值: {p.new_value_expr}')
                    continue
                entries = []
                if p.patterns:
                    for entry in p.patterns:
                        entries.append(Imm32PatchEntry(
                            pattern=entry.get('pattern', ''),
                            value_offset=entry.get('value_offset', p.value_offset),
                            expect_count=entry.get('expect_count', 1),
                            value_size=entry.get('value_size', p.value_size or 4),
                        ))
                elif p.pattern:
                    entries.append(Imm32PatchEntry(
                        pattern=p.pattern,
                        value_offset=p.value_offset,
                        expect_count=p.expect_count or 1,
                        value_size=p.value_size or 4,
                    ))
                elif p.value_scan and p.expect_value:
                    # value_scan 模式：搜索 expect_value 的字节表示
                    # 构造一个搜索模式
                    expect_bytes = p.expect_value.to_bytes(p.value_size or 4, 'little')
                    pattern_str = ' '.join(f'{b:02X}' for b in expect_bytes)
                    entries.append(Imm32PatchEntry(
                        pattern=pattern_str,
                        value_offset=0,
                        expect_count=0,  # 不限制匹配数
                        value_size=p.value_size or 4,
                    ))
                if entries:
                    imm32_patches.append(Imm32PatchItem(
                        patch_id=p.id, name=p.name,
                        new_value=new_value, entries=entries,
                    ))

            # 配置驱动型
            elif p.type in ('drop_probability', 'patch_drop_probability',
                            'font_config', 'patch_font_config',
                            'animation_speed', 'patch_animation_speed',
                            'summon_table', 'patch_summon_table'):
                if not p.json_file or not os.path.isfile(p.json_file):
                    self._log(f'[{p.id}] JSON 配置不存在: {p.json_file}')
                    continue
                try:
                    import json
                    with open(p.json_file, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                except Exception as e:
                    self._log(f'[{p.id}] 读取 JSON 失败: {e}')
                    continue
                config_patches.append(ConfigPatchItem(
                    patch_id=p.id, name=p.name,
                    patch_type=p.type, config=cfg,
                ))

        return cave_patches, bytes_patches, imm32_patches, config_patches

    def _resolve_imm32_value(self, p: PatchDef) -> int | None:
        """解析 patch_imm32 的 new_value_expr 为静态整数值。

        支持：
          - 纯数字: "0xFFFF" / "65535"
          - 变量引用: "{tkitem_actual_size}" → 从实际数据文件读取大小
        """
        expr = p.new_value_expr.strip()
        if not expr:
            return None
        # 纯数字
        try:
            if expr.startswith('0x') or expr.startswith('0X'):
                return int(expr, 16)
            return int(expr)
        except ValueError:
            pass
        # 变量引用 → 尝试从实际数据文件读取大小
        if '{' in expr and '}' in expr:
            var_name = expr.strip('{}')
            actual_size = self._read_data_file_size(var_name)
            if actual_size is not None:
                self._log(f'[{p.id}] {var_name} = {actual_size} (从数据文件读取)')
                return actual_size
            # 回退到 expect_value
            self._log(f'[{p.id}] 无法读取 {var_name}，使用 expect_value={p.expect_value}')
            return p.expect_value
        return None

    def _read_data_file_size(self, var_name: str) -> int | None:
        """从游戏数据目录读取实际文件大小。

        变量名映射到文件名：
          tkitem_actual_size → TKItem.dat 解压后大小
          tkmat_actual_size → TKMat.Dat 大小
          tkshop_actual_size → TKShop.dat 解压后大小
          tkskill_actual_size → TKSkill.dat 解压后大小
          warpc_new_size → WarPC.dat 解压后大小
          tkdefunit_new_count → TKDefUnit.dat 条数
        """
        src = self._src_edit.text().strip()
        if not src:
            return None
        game_dir = os.path.dirname(src)

        # 变量名 → (文件名, 是否需要解压, 记录大小)
        file_map = {
            'tkitem_actual_size': ('TKItem.dat', True, 64),
            'tkmat_actual_size': ('TKMat.Dat', False, 384),
            'tkshop_actual_size': ('TKShop.dat', True, 8),
            'tkskill_actual_size': ('TKSkill.dat', True, 94),
            'warpc_new_size': ('WarPC.dat', True, 1054),
            'tkdefunit_new_count': ('TKDefUnit.dat', False, 16),
        }

        if var_name not in file_map:
            return None

        filename, needs_decompress, rec_size = file_map[var_name]
        filepath = os.path.join(game_dir, filename)
        if not os.path.isfile(filepath):
            return None

        try:
            if needs_decompress:
                # LZSS 解压
                from editor_utils.lzss import lzss_decompress_dat
                with open(filepath, 'rb') as f:
                    raw = f.read()
                decompressed = lzss_decompress_dat(raw)
                if var_name == 'tkdefunit_new_count':
                    return len(decompressed) // rec_size
                return len(decompressed)
            else:
                # 直接读取文件大小
                size = os.path.getsize(filepath)
                if var_name == 'tkdefunit_new_count':
                    return size // rec_size
                return size
        except Exception as e:
            self._log(f'读取 {filename} 失败: {e}')
            return None

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

        cave_patches, bytes_patches, imm32_patches, config_patches = self._get_selected_patches()
        total = len(cave_patches) + len(bytes_patches) + len(imm32_patches) + len(config_patches)
        if total == 0:
            QMessageBox.warning(self, '错误', '请至少勾选一个补丁')
            return

        # 确认
        all_names = ([p.name for p in cave_patches] +
                     [p.name for p in bytes_patches] +
                     [p.name for p in imm32_patches] +
                     [p.name for p in config_patches])
        patch_names = ', '.join(all_names)
        ret = QMessageBox.question(
            self, '确认生成',
            f'将以下 {total} 个补丁烧录进 TKS.exe：\n\n{patch_names}\n\n'
            f'输出: {out}\n\n继续？',
            QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        self._build_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._log_text.clear()
        self._log(f'开始构建… (cave={len(cave_patches)}, bytes={len(bytes_patches)}, '
                  f'imm32={len(imm32_patches)}, config={len(config_patches)})')

        try:
            builder = ExeBuilder(src)
        except Exception as e:
            self._log(f'读取原版 exe 失败: {e}')
            QMessageBox.critical(self, '错误', f'读取原版 exe 失败:\n{e}')
            self._build_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        self._worker = _BuildWorker(builder, cave_patches, bytes_patches,
                                    imm32_patches, config_patches, out)
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
