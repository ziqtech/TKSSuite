"""生成启动器对话框 — 选中补丁，烧录进原版 TKS.exe 生成独立修改版

支持的补丁类型：
  - cave_hook / patch_exp_lock: 代码洞注入（.test 节 + jmp hook）
  - fixed_layout_cave: 多 hook 固定布局 cave（cave_code.py build_cave_block）
  - patch_bytes: 模式搜索 + 字节替换
  - patch_imm32: 立即数修改（静态值）
  - 配置驱动型: drop_probability / font_config / animation_speed / summon_table
  - patch_data_expand: 数据段注入（参数声明在 patch.json）
"""
import importlib.util
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
    Imm32PatchItem, Imm32PatchEntry, ConfigPatchItem, DataSectionPatchItem,
    FixedLayoutCave, SitesPatchItem,
)
from core.tkspatch_loader import get_external_cave_code


def expansion_buffer_size(actual_size: int, cap: int = 0,
                          align: int = 0x10000) -> int:
    """扩容缓冲区的最终大小 = max(实际数据, buffer_cap) 的 align 对齐。

    patch_data_expand 的注入节与配套 patch_imm32 的容量立即数必须用
    同一公式，否则加载检查值与实际缓冲区不一致。
    """
    target = max(actual_size, cap)
    return (target + align - 1) & ~(align - 1)


def resolve_data_file(out_exe_path: str, src_exe_path: str, filename: str) -> str | None:
    """数据文件解析: 优先输出 exe 所在目录, 回退原版 exe 所在目录。

    游戏从自身所在目录读取 .dat 文件, 生成的 exe 将在输出目录运行——
    部署目录里的数据文件 (可能是 MOD 合并/编辑后的扩容版) 才是运行时
    真正被加载的。若只按"原版 TKS.exe 目录"取数据, 部署目录的扩容文件
    会超出重定向后的缓冲区, 游戏报 FileRead ... buffer too small。
    """
    candidates = []
    if out_exe_path:
        d = os.path.dirname(out_exe_path)
        if d:
            candidates.append(os.path.join(d, filename))
    if src_exe_path:
        d = os.path.dirname(src_exe_path)
        if d:
            candidates.append(os.path.join(d, filename))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def pad_section_data(content: bytes, min_size: int = 0,
                     align: int = 0x10000) -> bytes:
    """把注入数据补零到 max(原长, min_size) 的 align (默认 64KB) 对齐。

    重定向后的缓冲区大小 = 注入数据长度。buffer_cap 声明的下限使缓冲区
    与生成时的数据文件大小解耦——部署目录的数据文件 (可能在生成后才被
    MOD 合并/编辑扩容, 或 exe 生成后另行拷贝过去) 只要不超过缓冲区即可
    加载 (FileRead 只要求 文件大小 <= 缓冲区大小, 未覆盖尾部保持补零)。
    """
    target = max(len(content), min_size)
    rounded = (target + align - 1) & ~(align - 1)
    if rounded > len(content):
        content = content.ljust(rounded, b'\x00')
    return content


class _BuildWorker(QThread):
    """后台构建线程。"""
    finished = Signal(object)  # CaveBuildResult

    def __init__(self, builder: ExeBuilder, cave_patches: list,
                 bytes_patches: list, imm32_patches: list,
                 config_patches: list, data_section_patches: list,
                 fixed_layouts: list, output_path: str,
                 sites_patches: list | None = None):
        super().__init__()
        self._builder = builder
        self._cave_patches = cave_patches
        self._bytes_patches = bytes_patches
        self._imm32_patches = imm32_patches
        self._config_patches = config_patches
        self._data_section_patches = data_section_patches
        self._fixed_layouts = fixed_layouts
        self._sites_patches = sites_patches or []
        self._output = output_path

    def run(self):
        try:
            result = self._builder.build(
                self._cave_patches, self._output,
                bytes_patches=self._bytes_patches,
                imm32_patches=self._imm32_patches,
                config_patches=self._config_patches,
                data_section_patches=self._data_section_patches,
                fixed_layouts=self._fixed_layouts,
                sites_patches=self._sites_patches,
            )
        except Exception:
            # 线程内异常若不接住, finished 信号永不发出, 弹窗会永远停在
            # "开始构建…" (已发生过的卡死事故); 转为失败结果在弹窗内展示
            import traceback
            from core.exe_builder import CaveBuildResult
            result = CaveBuildResult(success=False, output_path=self._output,
                                     error='构建异常: 见日志')
            result.log.append(traceback.format_exc())
        self.finished.emit(result)


class GenerateExeDialog(QDialog):
    """生成启动器对话框。

    流程：
      1. 选择原版 TKS.exe
      2. 勾选要烧录的 cave 型补丁
      3. 选择输出路径
      4. 点击生成
    """

    def __init__(self, patches: list[PatchDef], launcher_dir: str, parent=None,
                 patch_states: dict[str, bool] | None = None):
        super().__init__(parent)
        self.setWindowTitle('生成启动器 — 将补丁烧录进 TKS.exe')
        self.setMinimumSize(750, 650)
        self._patches = patches
        self._launcher_dir = launcher_dir
        # launcher 补丁列表的当前可选补丁勾选状态 (get_patch_states()),
        # 打开时原样镜像, 与 launcher 的必选/可选语义完全一致
        self._patch_states = patch_states or {}
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
        btn_all.setToolTip('勾选全部可选补丁 (必选补丁始终勾选)')
        btn_none.setToolTip('取消全部可选补丁 (必选补丁不受影响)')
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
            # fixed_layout_cave: 多 hook 固定布局
            if p.type == 'fixed_layout_cave':
                if p.hooks and (p.cave_code_file or p.cave_layout_size):
                    self._add_patch_item(p, '固定布局注入')
                    supported_count += 1
                else:
                    unsupported.append(p)
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
            # 数据段注入型 (参数声明在 patch.json)
            if p.type == 'patch_data_expand':
                if p.data_file and p.old_base and p.old_size:
                    self._add_patch_item(p, '数据段注入')
                    supported_count += 1
                else:
                    unsupported.append(p)
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
            + (f'（{unsupported_count} 个暂不支持）' if unsupported_count else '')
        )

        # 在日志中记录不支持的补丁
        for p in unsupported:
            reason = {
                'script': '请改写为 cave_hook / fixed_layout_cave / patch_data_expand',
            }.get(p.type, f'类型 {p.type} 缺少文件级所需字段')
            self._log(f'[{p.id}] {reason}')

    def _add_patch_item(self, p: PatchDef, type_label: str):
        """添加一个补丁到列表。

        勾选语义与 launcher 补丁列表完全一致:
          - 必选 (非 optional): 始终勾选且锁定 (复选框无 UserCheckable 标志);
          - 可选: 镜像 launcher 当前勾选状态, 无记录时回退 default_checked。
        """
        item = QListWidgetItem()
        if p.optional:
            checked = self._patch_states.get(p.id, p.default_checked)
            item.setText(f'{p.name}  [{type_label}]')
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        else:
            item.setText(f'{p.name}  [必选·{type_label}]')
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
        item.setData(Qt.UserRole, p)
        item.setData(Qt.UserRole + 1, type_label)
        self._patch_list.addItem(item)

    def _set_all(self, checked: bool):
        """全选/全不选: 仅作用于可选补丁 (必选始终勾选, 与 launcher 一致)。"""
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self._patch_list.count()):
            item = self._patch_list.item(i)
            p = item.data(Qt.UserRole)
            if p is not None and not p.optional:
                continue
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
            (cave_patches, bytes_patches, imm32_patches, config_patches,
             data_section_patches, fixed_layouts)
        """
        cave_patches = []
        bytes_patches = []
        imm32_patches = []
        config_patches = []
        data_section_patches = []
        fixed_layouts = []
        sites_patches = []

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
                if not p.hook_pattern:
                    self._log(f'[{p.id}] 无 hook_pattern，跳过')
                    continue
                cave_patches.append(CavePatchItem(
                    patch_id=p.id, name=p.name,
                    hook_pattern=p.hook_pattern,
                    hook_size=p.hook_size or 5,
                    cave_code=cave_code,
                    fallback_rva=p.fallback_rva,
                    expect_count=p.hook_expect_count or 1,
                    hook_offset=p.hook_offset or 0,
                    warpc_cap_adjust=bool(p.warpc_cap_adjust),
                    weapon_cap_adjust=bool(p.weapon_cap_adjust),
                ))

            # fixed_layout_cave
            elif p.type == 'fixed_layout_cave':
                fl = self._build_fixed_layout(p)
                if fl is not None:
                    fixed_layouts.append(fl)

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
                    expect_bytes = p.expect_value.to_bytes(p.value_size or 4, 'little')
                    pattern_str = ' '.join(f'{b:02X}' for b in expect_bytes)
                    entries.append(Imm32PatchEntry(
                        pattern=pattern_str,
                        value_offset=0,
                        expect_count=0,
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

            # 数据段注入型 (参数来自 patch.json)
            elif p.type == 'patch_data_expand':
                item = self._build_data_section(p)
                if item is not None:
                    data_section_patches.append(item)

            # 逐 RVA 位点表型 (16:9 宽屏)
            elif p.type == 'patch_sites':
                cave_code = get_external_cave_code(p) or b''
                entries = {k: int(v, 16) if isinstance(v, str) else int(v) for k, v in
                           (getattr(p, 'cave_entries', {}) or {}).items()}
                sites = list(getattr(p, 'sites', []) or [])
                if not sites:
                    self._log(f'[{p.id}] 无 sites 位点表，跳过')
                    continue
                sites_patches.append(SitesPatchItem(
                    patch_id=p.id, name=p.name, sites=sites,
                    cave_code=cave_code, cave_entries=entries,
                    globals_ph_base=int(getattr(p, 'globals_ph_base', 0) or 0),
                    globals_rebase_span=int(getattr(p, 'globals_rebase_span', 0) or 0),
                    globals_alloc_size=int(getattr(p, 'globals_alloc_size', 0) or 0),
                    globals_extra_windows=list(getattr(p, 'globals_extra_windows', []) or []),
                ))

        self._warn_unselected_expansions(data_section_patches)

        return (cave_patches, bytes_patches, imm32_patches, config_patches,
                data_section_patches, fixed_layouts, sites_patches)

    def _warn_unselected_expansions(self, selected_items):
        """数据文件已扩容但对应 patch_data_expand 未勾选时警告。

        生成的 exe 按旧容量加载部署目录的数据文件——WarPC.dat 这类已扩容
        文件会再次触发 FileRead buffer too small。launcher 运行时由
        warpc_expander 兜底, 生成的 exe 没有这层, 必须勾选扩容补丁。
        """
        selected_ids = {it.patch_id for it in selected_items}
        for p in self._patches:
            if p.type != 'patch_data_expand' or p.id in selected_ids:
                continue
            path = resolve_data_file(self._out_edit.text().strip(),
                                     self._src_edit.text().strip(), p.data_file)
            if not path:
                continue
            try:
                with open(path, 'rb') as f:
                    content = f.read()
                if p.needs_lzss:
                    from editor_utils.lzss import lzss_decompress_dat
                    content = lzss_decompress_dat(content)
            except Exception:
                continue
            if len(content) > p.old_size:
                self._log(f'[WARN] {p.data_file} 已扩容 '
                          f'({len(content)} > 原版 {p.old_size}) 但 '
                          f'{p.id} 未勾选——生成的 exe 将无法加载该文件, '
                          f'请勾选 {p.id} 后重新生成')

    def _build_fixed_layout(self, p: PatchDef) -> FixedLayoutCave | None:
        """从 fixed_layout_cave 补丁定义构建 FixedLayoutCave。"""
        hooks = list(p.hooks or [])
        if not hooks:
            self._log(f'[{p.id}] 未声明 hooks')
            return None

        summon_limit = 4
        extra = getattr(p, '_extra', {}) or {}
        if 'summon_limit' in extra:
            try:
                summon_limit = int(extra['summon_limit'])
            except (TypeError, ValueError):
                pass

        bytes_items = []
        for bp in (p.bytes_patches or []):
            replace = {}
            for k, v in (bp.get('replace') or {}).items():
                if isinstance(v, str) and v.startswith('$'):
                    # 声明式变量: "$summon_limit" → patch.json 的 summon_limit
                    var = v[1:]
                    if var == 'summon_limit':
                        iv = summon_limit
                    else:
                        self._log(f'[{p.id}] 未知替换变量: {v}')
                        continue
                else:
                    iv = int(v)
                replace[int(k)] = iv
            bytes_items.append(BytesPatchEntry(
                pattern=bp.get('pattern', ''),
                replace=replace,
                expect_count=bp.get('expect_count', 0),
            ))

        build_fn = None
        cave_block = None
        layout_size = p.cave_layout_size or 0

        if p.cave_code_file and os.path.isfile(p.cave_code_file):
            try:
                spec = importlib.util.spec_from_file_location(
                    f'_cave_{p.id}', p.cave_code_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                raw_fn = getattr(mod, 'build_cave_block', None)
                if raw_fn is None:
                    self._log(f'[{p.id}] cave_code.py 缺少 build_cave_block')
                    return None
                n = summon_limit
                build_fn = lambda base, _fn=raw_fn, _n=n: _fn(base, _n)
                if not layout_size:
                    # 用 image_base=0x400000 探测一次实际大小
                    layout_size = max(len(raw_fn(0x400000, n)), 0x800)
            except Exception as e:
                self._log(f'[{p.id}] 加载 cave_code.py 失败: {e}')
                return None
        else:
            self._log(f'[{p.id}] cave_code_file 不存在: {p.cave_code_file}')
            return None

        return FixedLayoutCave(
            patch_id=p.id, name=p.name,
            hooks=hooks,
            cave_block=cave_block,
            build_fn=build_fn,
            bytes_patches=[BytesPatchItem(
                patch_id=p.id, name=p.name, entries=bytes_items)]
            if bytes_items else None,
            cave_layout_size=layout_size,
        )

    def _build_data_section(self, p: PatchDef) -> DataSectionPatchItem | None:
        """从 patch_data_expand 补丁定义构建 DataSectionPatchItem。"""
        data_file = p.data_file
        old_base = p.old_base
        old_size = p.old_size
        section_name = p.section_name
        needs_lzss = p.needs_lzss

        if not data_file or not old_base or not old_size:
            self._log(f'[{p.id}] patch_data_expand 字段不完整')
            return None

        path = resolve_data_file(self._out_edit.text().strip(),
                                 self._src_edit.text().strip(), data_file)
        if not path:
            self._log(f'[{p.id}] 数据文件不存在: '
                      f'{data_file} (输出目录与原版目录均未找到)')
            return None
        self._log(f'[{p.id}] 数据文件: {path}')

        try:
            with open(path, 'rb') as f:
                content = f.read()
        except Exception as e:
            self._log(f'[{p.id}] 读取数据文件失败: {e}')
            return None

        if needs_lzss:
            try:
                from editor_utils.lzss import lzss_decompress_dat
                content = lzss_decompress_dat(content)
            except Exception as e:
                self._log(f'[{p.id}] LZSS 解压失败: {e}')
                return None

        # buffer_cap 声明后选中即注入, 缓冲区按下限建 (与生成时数据大小解耦):
        # 部署目录的数据文件在生成后才扩容 / exe 拷贝到其它目录均不受影响,
        # 只要运行时文件不超过缓冲区即可加载。
        cap = int((getattr(p, '_extra', {}) or {}).get('buffer_cap', 0) or 0)
        if not cap and len(content) <= old_size:
            self._log(f'[{p.id}] 数据大小 {len(content)} <= 原始 {old_size}，跳过')
            return None

        content = pad_section_data(content, min_size=cap)
        self._log(f'[{p.id}] 注入 {len(content)} 字节'
                  + (f' (buffer_cap={cap}, 64KB 对齐)' if cap else ' (64KB 对齐含余量)'))

        return DataSectionPatchItem(
            patch_id=p.id, name=p.name,
            data=content,
            old_base=old_base,
            old_size=old_size,
            section_name=section_name or f'.{p.id[:6]}',
            redirect_base_span=int((getattr(p, '_extra', {}) or {})
                                   .get('redirect_base_span', 0) or 0),
        )

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
                # buffer_cap: 容量立即数与 data_expand 注入节用同一公式,
                # 保证 加载检查值 == 实际缓冲区大小
                cap = int((getattr(p, '_extra', {}) or {})
                          .get('buffer_cap', 0) or 0)
                if cap:
                    actual_size = expansion_buffer_size(actual_size, cap)
                    self._log(f'[{p.id}] {var_name} = {actual_size} '
                              f'(buffer_cap={cap}, 64KB 对齐)')
                else:
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
        filepath = resolve_data_file(self._out_edit.text().strip(),
                                     self._src_edit.text().strip(), filename)
        if not filepath:
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

        (cave_patches, bytes_patches, imm32_patches, config_patches,
         data_section_patches, fixed_layouts, sites_patches) = self._get_selected_patches()
        total = (len(cave_patches) + len(bytes_patches) + len(imm32_patches) +
                 len(config_patches) + len(data_section_patches) +
                 len(fixed_layouts))
        if total == 0:
            QMessageBox.warning(self, '错误', '请至少勾选一个补丁')
            return

        # 确认
        all_names = ([p.name for p in cave_patches] +
                     [p.name for p in bytes_patches] +
                     [p.name for p in imm32_patches] +
                     [p.name for p in config_patches] +
                     [p.name for p in data_section_patches] +
                     [p.name for p in fixed_layouts])
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
                  f'imm32={len(imm32_patches)}, config={len(config_patches)}, '
                  f'data={len(data_section_patches)}, fixed={len(fixed_layouts)}, '
                  f'sites={len(sites_patches)})')

        try:
            builder = ExeBuilder(src)
        except Exception as e:
            self._log(f'读取原版 exe 失败: {e}')
            QMessageBox.critical(self, '错误', f'读取原版 exe 失败:\n{e}')
            self._build_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        self._worker = _BuildWorker(builder, cave_patches, bytes_patches,
                                    imm32_patches, config_patches,
                                    data_section_patches, fixed_layouts, out,
                                    sites_patches=sites_patches)
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
