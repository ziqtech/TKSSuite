"""生成启动器对话框 — 选中补丁，烧录进原版 TKS.exe 生成独立修改版

支持的补丁类型：
  - cave_hook / patch_exp_lock: 代码洞注入（.test 节 + jmp hook）
  - fixed_layout_cave: 多 hook 固定布局 cave（cave_code.py build_cave_block）
  - patch_bytes: 模式搜索 + 字节替换
  - patch_imm32: 立即数修改（静态值）
  - 配置驱动型: drop_probability / font_config / animation_speed / summon_table
  - patch_data_expand: 数据段注入（参数声明在 patch.json）
  - patch_sites: 逐 RVA 位点表 + cave（16:9 宽屏；可带 globals 数据槽区）
"""
import os
import shutil
from types import SimpleNamespace
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)
from core.config_loader import PatchDef, patch_metadata
from core.mod_distribution import ModBuildWorkspace
from core.mod_loader import ModInfo, allowed_mod_configs
from core.exe_builder import (
    ExeBuilder, CavePatchItem, BytesPatchItem, BytesPatchEntry,
    Imm32PatchItem, Imm32PatchEntry, ConfigPatchItem, DataSectionPatchItem,
    FixedLayoutCave, SitesPatchItem,
)
from core.patch_plan import build_patch_plan, migrate_patch_states
from core.tkspatch_loader import get_external_cave_code, load_cave_module
from ui.patch_list import patch_type_label


def file_build_label(p: PatchDef) -> str | None:
    """判断补丁能否被"生成启动器"离线烧录；可烧录时返回列表用的类型标签。

    与 ExeBuilder 实际支持的补丁类型一一对应（含 patch_sites：逐 RVA 位点表，
    即 16:9 宽屏补丁使用的类型）。返回 None 表示当前不支持或缺少必需字段。
    bundle 在计划准备阶段展开为这些普通操作。
    """
    t = getattr(p, 'type', '')
    if t == 'bundle':
        return '组合补丁'
    if t in ('cave_hook', 'patch_exp_lock'):
        if p.hook_pattern and get_external_cave_code(p):
            return '代码注入'
        return None
    if t == 'fixed_layout_cave':
        if p.hooks and (p.cave_code_file or p.cave_layout_size):
            return '固定布局注入'
        return None
    if t == 'patch_bytes':
        if (p.pattern and p.replace) or p.patterns:
            return '字节替换'
        return None
    if t == 'patch_imm32':
        # 三种形态: 多模式表 / 单模式 / 值扫描。三种在 _get_selected_patches 里
        # 都能生成 Imm32PatchEntry —— 早期漏判了 patterns 形态, 导致 gold_limit
        # (三处锚定 + value_offset/value_size 各自不同) 被误报"暂不支持"。
        if not p.new_value_expr:
            return None
        if p.patterns:
            return '立即数(多模式)'
        if p.pattern:
            return '立即数'
        if p.value_scan and p.expect_value:
            return '立即数(值扫描)'
        return None
    if t in ('drop_probability', 'patch_drop_probability',
             'font_config', 'patch_font_config',
             'animation_speed', 'patch_animation_speed',
             'summon_table', 'patch_summon_table'):
        return '配置驱动' if p.json_file else None
    if t == 'patch_data_expand':
        if p.data_file and p.old_base and p.old_size:
            return '数据段注入'
        return None
    if t == 'patch_sites':
        sites = list(getattr(p, 'sites', None) or [])
        if not sites:
            return None
        # call / push_imm 型位点需要 cave 代码（外置文件或 patch.json 内嵌）
        need_cave = any(str(s.get('kind') or '') in ('call', 'push_imm')
                        for s in sites)
        if need_cave and not get_external_cave_code(p):
            return None
        return '位点表(宽屏)'
    return None


def expansion_logical_size(actual_size: int, cap: int = 0) -> int:
    """扩容缓冲区的逻辑容量 = max(实际数据, buffer_cap)。

    逻辑容量会写入游戏代码中的加载/存档大小常量，必须保持记录格式要求，
    不能混入 PE 节使用的 64 KiB 后备对齐。PE 对齐由 pad_section_data 在
    构建注入节时单独处理。
    """
    return max(actual_size, cap)


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


class _PrepareWorker(QThread):
    def __init__(self, workspace: ModBuildWorkspace):
        super().__init__()
        self.workspace = workspace
        self.error = ''

    def run(self):
        try:
            self.workspace.prepare()
        except Exception as exc:
            self.error = str(exc)


class _BuildWorker(QThread):
    completed = Signal(object)

    def __init__(self, builder: ExeBuilder, patch_items: tuple,
                 workspace: ModBuildWorkspace, resources: list, tool_dir: str):
        super().__init__()
        self._builder = builder
        self._patch_items = patch_items
        self._workspace = workspace
        self._resources = resources
        self._tool_dir = tool_dir
        self.output_files = []

    def run(self):
        from core.exe_builder import CaveBuildResult
        workspace = self._workspace
        result = None
        try:
            cave, byte, imm32, config, data, fixed, sites = self._patch_items
            if any(self._patch_items):
                result = self._builder.build(
                    cave, workspace.build_exe, bytes_patches=byte,
                    imm32_patches=imm32, config_patches=config,
                    data_section_patches=data, fixed_layouts=fixed,
                    sites_patches=sites)
            else:
                shutil.copy2(workspace.source_exe, workspace.build_exe)
                result = CaveBuildResult(success=True)
            if result.success:
                self.output_files = workspace.publish(self._resources, self._tool_dir)
            result.output_path = workspace.output_exe
        except Exception as exc:
            import traceback
            if result is None:
                result = CaveBuildResult(success=False)
            result.success = False
            result.output_path = workspace.output_exe
            result.error = str(exc)
            result.log.append(traceback.format_exc())
        self.completed.emit(result)


class GenerateExeDialog(QDialog):
    """将补丁与已选 MOD 生成为独立覆盖包。"""
    log_emitted = Signal(str)

    def __init__(self, patches: list[PatchDef], launcher_dir: str, parent=None,
                 patch_states: dict[str, bool] | None = None,
                 selected_tool: str = "", source_exe: str = "",
                 selected_mods: list[ModInfo] | None = None):
        super().__init__(parent)
        self.setWindowTitle('生成启动器 / 独立覆盖包')
        self.setMinimumSize(760, 700)
        self.resize(900, 760)
        self._patches = patches
        self._launcher_dir = launcher_dir
        self._patch_states = migrate_patch_states(self._patches, patch_states or {})
        self._selected_tool = selected_tool or ""
        self._source_exe = source_exe
        self._selected_mods = list(selected_mods or [])
        self._default_output = ''
        self._built_directory = ''
        self._busy = False
        self._workspace: ModBuildWorkspace | None = None
        self._prepare_worker: _PrepareWorker | None = None
        self._worker: _BuildWorker | None = None
        self._last_build_patch_ids: list[str] = []
        self._last_build_resources: list[tuple[str, str]] = []

        self._setup_ui()
        self.log_emitted.connect(self._log)
        self._populate_patch_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        hint = QLabel('从游戏目录提取数据并整合 MOD，与原版基准对比，仅输出新增或内容变化的文件。两个输入目录均只读。')
        hint.setWordWrap(True)
        hint.setObjectName('hintLabel')
        layout.addWidget(hint)

        self._paths_group = QGroupBox('1. 目录设置')
        paths = QGridLayout(self._paths_group)
        self._baseline_edit = QLineEdit()
        self._baseline_edit.setPlaceholderText('导出前手动选择原版游戏目录，作为差异对照')
        baseline_btn = QPushButton('选择基准…')
        baseline_btn.clicked.connect(self._browse_baseline)
        paths.addWidget(QLabel('基准目录'), 0, 0)
        paths.addWidget(self._baseline_edit, 0, 1)
        paths.addWidget(baseline_btn, 0, 2)
        self._game_edit = QLineEdit()
        self._game_edit.setPlaceholderText('当前游戏目录，可为原版或改版；从此目录读取 TKS.exe 与数据')
        game_btn = QPushButton('选择游戏…')
        game_btn.clicked.connect(self._browse_game)
        paths.addWidget(QLabel('游戏目录'), 1, 0)
        paths.addWidget(self._game_edit, 1, 1)
        paths.addWidget(game_btn, 1, 2)
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText('默认：游戏目录 / dist')
        out_btn = QPushButton('选择输出…')
        out_btn.clicked.connect(self._browse_out)
        paths.addWidget(QLabel('输出目录'), 2, 0)
        paths.addWidget(self._out_edit, 2, 1)
        paths.addWidget(out_btn, 2, 2)
        path_hint = QLabel('输出 TKS_MOD.exe 与差异文件，保持子目录结构；不包含相同文件、存档、备份和缓存。')
        path_hint.setWordWrap(True)
        path_hint.setObjectName('hintLabel')
        paths.addWidget(path_hint, 3, 1, 1, 2)

        self._copy_tool_cb = QCheckBox('附带画面兼容工具')
        self._tool_combo = QComboBox()
        tools_dir = os.path.join(self._launcher_dir, 'tools')
        if os.path.isdir(tools_dir):
            for name in sorted(d for d in os.listdir(tools_dir)
                               if os.path.isdir(os.path.join(tools_dir, d))
                               and not d.startswith(('_', '.'))):
                self._tool_combo.addItem(name)
        idx = self._tool_combo.findText(self._selected_tool)
        if idx < 0:
            idx = self._tool_combo.findText('cnc-ddraw')
        if idx >= 0:
            self._tool_combo.setCurrentIndex(idx)
        has_tool = self._tool_combo.count() > 0
        self._copy_tool_cb.setEnabled(has_tool)
        self._copy_tool_cb.setChecked(
            has_tool and bool(self._selected_tool)
            and self._tool_combo.findText(self._selected_tool) >= 0)
        self._tool_combo.setEnabled(self._copy_tool_cb.isChecked())
        self._copy_tool_cb.toggled.connect(self._tool_combo.setEnabled)
        self._tool_combo.setToolTip('默认沿用主窗口选择；未选择时保留游戏目录已有工具文件。宽屏建议使用 cnc-ddraw。')
        tool_row = QHBoxLayout()
        tool_row.addWidget(self._copy_tool_cb)
        tool_row.addWidget(self._tool_combo, 1)
        paths.addLayout(tool_row, 4, 1, 1, 2)
        paths.setColumnStretch(1, 1)
        layout.addWidget(self._paths_group)
        self._game_edit.textChanged.connect(self._update_default_output)
        if self._source_exe:
            self._game_edit.setText(os.path.dirname(os.path.abspath(self._source_exe)))

        splitter = QSplitter(Qt.Vertical)
        self._selection_tabs = QTabWidget()
        patch_page = QWidget()
        patch_layout = QVBoxLayout(patch_page)
        btn_row = QHBoxLayout()
        self._summary_label = QLabel('')
        btn_row.addWidget(self._summary_label, 1)
        btn_all = QPushButton('全选')
        btn_none = QPushButton('全不选')
        btn_all.setToolTip('勾选全部可选补丁；必选补丁始终勾选')
        btn_none.setToolTip('取消全部可选补丁；必选补丁不受影响')
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        patch_layout.addLayout(btn_row)
        self._patch_list = QListWidget()
        self._patch_list.setSelectionMode(QListWidget.SingleSelection)
        self._patch_list.setMinimumHeight(90)
        patch_layout.addWidget(self._patch_list, 1)
        self._patch_detail = QTextEdit()
        self._patch_detail.setReadOnly(True)
        self._patch_detail.setMaximumHeight(85)
        self._patch_detail.setPlaceholderText('选择补丁查看说明；高级选项沿用主窗口设置。')
        patch_layout.addWidget(self._patch_detail)
        self._patch_list.currentRowChanged.connect(self._on_patch_selected)
        self._selection_tabs.addTab(patch_page, '2. 烧录补丁')

        mod_page = QWidget()
        mod_layout = QVBoxLayout(mod_page)
        mod_hint = QLabel('已同步主窗口勾选的 MOD / 合集，按依赖和加载顺序整合。若需调整，请关闭此窗口后修改主窗口勾选。')
        mod_hint.setWordWrap(True)
        mod_layout.addWidget(mod_hint)
        self._mod_list = QListWidget()
        for mod in self._selected_mods:
            item = QListWidgetItem(f'{mod.name}  ·  v{mod.version}')
            targets = sorted({entry.get('target', '')
                              for entry in mod.components + mod.resources
                              if entry.get('target')})
            item.setToolTip('\n'.join(targets) or mod.description)
            self._mod_list.addItem(item)
        if not self._selected_mods:
            self._mod_list.addItem('未勾选 MOD，仍会比较游戏目录与基准目录，输出差异文件和补丁 EXE。')
        mod_layout.addWidget(self._mod_list)
        self._selection_tabs.addTab(mod_page, f'已选 MOD（{len(self._selected_mods)}）')
        splitter.addWidget(self._selection_tabs)

        log_group = QGroupBox('3. 生成进度与文件清单')
        log_layout = QVBoxLayout(log_group)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        log_layout.addWidget(self._progress)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet('QTextEdit { min-height: 90px; }')
        self._log_text.setPlaceholderText('先整合再与基准逐文件比较，全部成功后只发布差异覆盖包。')
        log_layout.addWidget(self._log_text)
        splitter.addWidget(log_group)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 140])
        layout.addWidget(splitter, 1)

        btn_layout = QHBoxLayout()
        self._status_label = QLabel('就绪')
        btn_layout.addWidget(self._status_label, 1)
        self._open_btn = QPushButton('打开输出目录')
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_output_directory)
        self._build_btn = QPushButton('生成独立覆盖包')
        self._build_btn.setDefault(True)
        self._build_btn.clicked.connect(self._start_build)
        self._close_btn = QPushButton('关闭')
        self._close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._open_btn)
        btn_layout.addWidget(self._build_btn)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    def _populate_patch_list(self):
        """填充可烧录的补丁列表，并显示不支持的补丁。"""
        unsupported = []
        supported_count = 0
        for p in self._patches:
            if patch_metadata(p, 'internal', False):
                continue
            label = file_build_label(p)
            if label:
                self._add_patch_item(p, label)
                supported_count += 1
            else:
                unsupported.append(p)

        if self._patch_list.count() == 0:
            self._patch_list.addItem('（未找到可烧录的补丁）')

        # 显示统计信息（内部依赖不单独列出，但仍参与完整计划）。
        unsupported_count = len(unsupported)
        total = supported_count + unsupported_count
        self._summary_label.setText(
            f'可烧录: {supported_count}/{total} 个补丁'
            + (f'（{unsupported_count} 个暂不支持）' if unsupported_count else '')
        )

        # 在日志中记录不支持的补丁
        for p in unsupported:
            reason = {
                'script': '脚本型补丁无法离线烧录, 请改写为 代码注入(cave_hook) / '
                          '固定布局注入(fixed_layout_cave) / 数据段注入(patch_data_expand)',
            }.get(p.type,
                  f'类型 {patch_type_label(p.type)} ({p.type}) 缺少文件级所需字段')
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
            # 玩家友好中文标签 + 原始内部名 (后者供进阶排查, 与补丁列表悬浮提示一致)
            f'类型: {patch_type_label(p.type)} ({p.type})',
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

    def _update_default_output(self, game_dir: str):
        default = (os.path.join(os.path.abspath(game_dir.strip()), 'dist')
                   if game_dir.strip() else '')
        if not self._out_edit.text().strip() or self._out_edit.text() == self._default_output:
            self._out_edit.setText(default)
        self._default_output = default

    def _browse_baseline(self):
        path = QFileDialog.getExistingDirectory(
            self, '选择原版游戏目录作为基准', self._baseline_edit.text() or self._game_edit.text())
        if path:
            self._baseline_edit.setText(path)

    def _browse_game(self):
        path = QFileDialog.getExistingDirectory(
            self, '选择用于提取数据的游戏目录', self._game_edit.text())
        if path:
            self._game_edit.setText(path)

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(
            self, '选择差异覆盖包输出目录', self._out_edit.text())
        if path:
            self._out_edit.setText(path)

    def _resolve_data_file(self, filename: str) -> str | None:
        if self._workspace is not None:
            return self._workspace.resolve_file(filename)
        game_dir = self._game_edit.text().strip()
        if not game_dir:
            return None
        path = os.path.join(game_dir, filename)
        return path if os.path.isfile(path) else None

    def _get_selected_patches(self) -> tuple:
        """统一准备完整补丁计划，再将展开、链接后的普通操作按类型分组。

        Returns:
            (cave_patches, bytes_patches, imm32_patches, config_patches,
             data_section_patches, fixed_layouts, sites_patches)

        准备或转换失败时抛出异常，由表单中止生成并显示原因。
        """
        self._last_build_patch_ids = []
        self._last_build_resources = []
        cave_patches = []
        bytes_patches = []
        imm32_patches = []
        config_patches = []
        data_section_patches = []
        fixed_layouts = []
        sites_patches = []

        checked_ids = set()
        for i in range(self._patch_list.count()):
            list_item = self._patch_list.item(i)
            p: PatchDef = list_item.data(Qt.UserRole)
            if p is not None and list_item.checkState() == Qt.Checked:
                checked_ids.add(p.id)
        for p in self._patches:
            for option in patch_metadata(p, 'options', []):
                option_id = option['id']
                enabled = bool(self._patch_states.get(
                    option_id, option.get('default', False)))
                if enabled:
                    checked_ids.add(option_id)
                self._log(f'[{p.id}] 高级选项 {option.get("name") or option_id} '
                          f'({option_id}): {"启用" if enabled else "关闭"}'
                          '（沿用主窗口设置，仅在所属补丁生效时应用）')

        overrides = self._workspace.config_overrides if self._workspace else {}
        used_configs = set()
        plan = build_patch_plan(
            self._patches, selected=checked_ids,
            resolve_file=self._resolve_data_file, log_func=self._log)
        if plan.effective.superseded:
            self._log('补丁替代: ' + ', '.join(
                f'{old}->{new}'
                for old, new in sorted(plan.effective.superseded.items())))

        for p in plan.patches:
            if not file_build_label(p):
                raise ValueError(f'[{p.id}] 无法烧录 {p.type} 操作：类型不支持或缺少必需字段/代码')
            # cave_hook / patch_exp_lock
            if p.type in ('cave_hook', 'patch_exp_lock'):
                cave_code = get_external_cave_code(p)
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
                fixed_layouts.append(self._build_fixed_layout(p))

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
                    raise ValueError(f'[{p.id}] new_value 无法解析为静态值: {p.new_value_expr}')
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
                config_name = os.path.splitext(os.path.basename(p.json_file or ''))[0]
                if p.mod_config_overridable and config_name in overrides:
                    cfg = overrides[config_name]
                    used_configs.add(config_name)
                    self._log(f'[{p.id}] 烧录 MOD 配置: {config_name}')
                else:
                    if not p.json_file or not os.path.isfile(p.json_file):
                        raise ValueError(f'[{p.id}] JSON 配置不存在: {p.json_file}')
                    try:
                        import json
                        with open(p.json_file, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                    except Exception as e:
                        raise ValueError(f'[{p.id}] 读取 JSON 失败: {e}') from e
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
                sites_patches.append(SitesPatchItem(
                    patch_id=p.id, name=p.name, sites=sites,
                    cave_code=cave_code, cave_entries=entries,
                    globals_ph_base=int(getattr(p, 'globals_ph_base', 0) or 0),
                    globals_rebase_span=int(getattr(p, 'globals_rebase_span', 0) or 0),
                    globals_alloc_size=int(getattr(p, 'globals_alloc_size', 0) or 0),
                    globals_extra_windows=list(getattr(p, 'globals_extra_windows', []) or []),
                    globals_relocations=p.globals_relocations,
                ))
            else:
                raise ValueError(f'[{p.id}] 计划包含未展开或不支持的操作: {p.type}')

        unused_configs = set(overrides) - used_configs
        if unused_configs:
            raise ValueError('以下 MOD 配置尚未烧录，请勾选对应配置补丁: '
                             + ', '.join(sorted(unused_configs)))
        self._validate_expansions(data_section_patches)
        self._last_build_patch_ids = sorted(plan.ids)
        self._last_build_resources = list(plan.resources)

        return (cave_patches, bytes_patches, imm32_patches, config_patches,
                data_section_patches, fixed_layouts, sites_patches)

    def _validate_expansions(self, selected_items):
        """离线包没有运行时扩容兜底，不能发布超出 EXE 容量的数据。"""
        selected_ids = {it.patch_id for it in selected_items}
        for p in self._patches:
            if p.type != 'patch_data_expand' or p.id in selected_ids:
                continue
            path = self._resolve_data_file(p.data_file)
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
                raise ValueError(f'{p.data_file} 已扩容 '
                                 f'({len(content)} > 原版 {p.old_size})，'
                                 f'请勾选 {p.name or p.id} 后重新生成')

    def _build_fixed_layout(self, p: PatchDef) -> FixedLayoutCave:
        """从 fixed_layout_cave 补丁定义构建 FixedLayoutCave。"""
        hooks = list(p.hooks or [])
        if not hooks:
            raise ValueError(f'[{p.id}] 未声明 hooks')

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
                        raise ValueError(f'[{p.id}] 未知替换变量: {v}')
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

        try:
            mod = load_cave_module(p)
            raw_fn = getattr(mod, 'build_cave_block', None)
            if not callable(raw_fn):
                raise ValueError('cave_code.py 缺少 build_cave_block')
            n = summon_limit
            build_fn = lambda base, _fn=raw_fn, _n=n: _fn(base, _n)
            if not layout_size:
                layout_size = max(len(raw_fn(0x400000, n)), 0x800)
        except Exception as e:
            raise ValueError(f'[{p.id}] 加载 cave_code.py 失败: {e}') from e

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
            raise ValueError(f'[{p.id}] patch_data_expand 字段不完整')

        path = self._resolve_data_file(data_file)
        if not path:
            raise ValueError(f'[{p.id}] 数据文件不存在: '
                             f'{data_file} (整合数据与原版目录均未找到)')
        self._log(f'[{p.id}] 数据文件: {path}')

        try:
            with open(path, 'rb') as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f'[{p.id}] 读取数据文件失败: {e}') from e

        if needs_lzss:
            try:
                from editor_utils.lzss import lzss_decompress_dat
                content = lzss_decompress_dat(content)
            except Exception as e:
                raise ValueError(f'[{p.id}] LZSS 解压失败: {e}') from e

        if getattr(p, 'activate_if_expanded', False) and len(content) <= old_size:
            self._log(f'[{p.id}] 数据仍为原版大小 {len(content)}，跳过扩容')
            return None

        # buffer_cap 声明后选中即注入, 缓冲区按下限建 (与生成时数据大小解耦):
        # 部署目录的数据文件在生成后才扩容 / exe 拷贝到其它目录均不受影响,
        # 只要运行时文件不超过缓冲区即可加载。
        extra = getattr(p, '_extra', {}) or {}
        cap = int(extra.get('buffer_cap', 0) or 0)
        aux_size = int(extra.get('aux_size', 0) or 0)
        front_pad = int(extra.get('front_pad', 0) or 0)
        aux_patches = list(extra.get('aux_patches', []) or [])
        if not cap and len(content) <= old_size:
            self._log(f'[{p.id}] 数据大小 {len(content)} <= 原始 {old_size}，跳过')
            return None

        logical_size = expansion_logical_size(len(content), cap)
        content = pad_section_data(content, min_size=logical_size)
        backing_size = len(content)
        if aux_size:
            content += b"\0" * aux_size
        self._log(f'[{p.id}] 注入 {len(content)} 字节 '
                  f'(前置垫 {front_pad} + 逻辑 {logical_size} + '
                  f'后备填充 {backing_size - logical_size} + 辅助 {aux_size})')

        bytes_items = []
        for bp in (p.bytes_patches or []):
            replace = {
                int(k): int(v)
                for k, v in (bp.get('replace') or {}).items()
            }
            bytes_items.append(BytesPatchEntry(
                pattern=bp.get('pattern', ''),
                replace=replace,
                expect_count=bp.get('expect_count', 0),
            ))

        return DataSectionPatchItem(
            patch_id=p.id, name=p.name,
            data=content,
            old_base=old_base,
            old_size=old_size,
            section_name=section_name or f'.{p.id[:6]}',
            redirect_base_span=int((getattr(p, '_extra', {}) or {})
                                   .get('redirect_base_span', 0) or 0),
            size_pattern=p.pattern,
            size_value_offset=p.value_offset,
            size_expect_count=p.expect_count,
            redirect_size=bool(extra.get('redirect_size', True)),
            logical_size=logical_size,
            backing_size=backing_size,
            aux_size=aux_size,
            front_pad=front_pad,
            aux_patches=aux_patches,
            bytes_patches=[BytesPatchItem(
                patch_id=p.id, name=p.name, entries=bytes_items)]
            if bytes_items else None,
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
                    actual_size = expansion_logical_size(actual_size, cap)
                    self._log(f'[{p.id}] {var_name} = {actual_size} '
                              f'(buffer_cap={cap}, 逻辑容量)')
                else:
                    self._log(f'[{p.id}] {var_name} = {actual_size} (从数据文件读取)')
                return actual_size
            raise ValueError(f'[{p.id}] 无法读取 {var_name}，不能确定加载容量')
        return None

    def _read_data_file_size(self, var_name: str) -> int | None:
        """从游戏数据目录读取实际文件大小。

        变量名映射到文件名：
          tkitem_actual_size → TKItem.dat 解压后大小
          tkmat_actual_size → TKMat.Dat 大小
          tkshop_actual_size → TKShop.dat 解压后大小
          warpc_new_size → WarPC.dat 解压后大小
          tkdefunit_new_count → TKDefUnit.dat 条数
        """
        # 变量名 → (文件名, 是否需要解压, 记录大小)
        file_map = {
            'tkitem_actual_size': ('TKItem.dat', True, 64),
            'tkmat_actual_size': ('TKMat.Dat', False, 384),
            'tkshop_actual_size': ('TKShop.dat', True, 8),
            'warpc_new_size': ('WarPC.dat', True, 1054),
            'tkdefunit_new_count': ('TKDefUnit.dat', False, 16),
        }

        if var_name not in file_map:
            return None

        filename, needs_decompress, rec_size = file_map[var_name]
        filepath = self._resolve_data_file(filename)
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

    def _set_build_busy(self, busy: bool):
        self._busy = busy
        for widget in (self._paths_group, self._selection_tabs,
                       self._build_btn, self._close_btn):
            widget.setEnabled(not busy)
        self._open_btn.setEnabled(not busy and bool(self._built_directory))
        self._progress.setVisible(busy)
        self._progress.setRange(0, 0)

    def _cleanup_workspace(self):
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None

    def _build_failed(self, message: str):
        self._cleanup_workspace()
        self._set_build_busy(False)
        self._status_label.setText('生成失败，请查看日志')
        self._log(f'生成失败: {message}')
        QMessageBox.critical(self, '生成失败', message)

    def _start_build(self):
        if self._busy:
            return
        baseline = self._baseline_edit.text().strip()
        game = self._game_edit.text().strip()
        out = self._out_edit.text().strip()
        if not baseline or not os.path.isdir(baseline):
            QMessageBox.warning(self, '错误', '请手动选择有效的原版游戏目录作为基准目录')
            return
        if not game or not os.path.isdir(game) or not os.path.isfile(os.path.join(game, 'TKS.exe')):
            QMessageBox.warning(self, '错误', '请选择包含 TKS.exe 的游戏目录（支持改版）')
            return
        if not out or (os.path.exists(out) and not os.path.isdir(out)):
            QMessageBox.warning(self, '错误', '请选择或填写有效的输出目录，而不是 EXE 文件路径')
            return
        self._log_text.clear()
        try:
            self._workspace = ModBuildWorkspace(
                os.path.join(os.path.abspath(game), 'TKS.exe'),
                os.path.join(os.path.abspath(out), 'TKS_MOD.exe'), self._selected_mods,
                allowed_configs=allowed_mod_configs(SimpleNamespace(patches=self._patches)),
                log_func=self.log_emitted.emit, baseline_dir=os.path.abspath(baseline))
        except Exception as exc:
            self._build_failed(str(exc))
            return
        self._set_build_busy(True)
        self._status_label.setText('正在整合并与基准目录比较…')
        self._log(f'基准目录（只读对照）: {os.path.abspath(baseline)}')
        self._log(f'游戏目录（提取数据）: {os.path.abspath(game)}')
        self._log('整合 MOD 后按内容比较，仅输出差异；基准和游戏目录均不修改。')
        self._prepare_worker = _PrepareWorker(self._workspace)
        self._prepare_worker.finished.connect(self._on_mods_prepared)
        self._prepare_worker.start()

    def _on_mods_prepared(self):
        if self._prepare_worker.error:
            self._build_failed(self._prepare_worker.error)
            return
        self._status_label.setText('正在准备补丁…')
        try:
            patch_items = self._get_selected_patches()
            builder = ExeBuilder(self._workspace.source_exe)
        except Exception as exc:
            self._build_failed(str(exc))
            return
        names = [item.name for group in patch_items for item in group]
        files = sorted(self._workspace.files)
        self._log('待烧录补丁: ' + (', '.join(names) or '无（保留当前游戏程序）'))
        for name in files:
            self._log(f'  [待输出差异] {name}')
        ret = QMessageBox.question(
            self, '确认生成差异覆盖包',
            f'将烧录 {len(names)} 个补丁操作，整合 {len(self._selected_mods)} 个 MOD / 合集。\n'
            f'整合数据中有 {len(files)} 个差异文件，附带工具与补丁资源后将再次比较。\n'
            f'基准目录：{self._workspace.baseline_dir}\n'
            f'输出目录：{os.path.dirname(self._workspace.output_exe)}\n'
            '输出程序固定为 TKS_MOD.exe；与基准内容相同的文件不输出。\n\n'
            '输出目录的同名文件会被覆盖，上次清单中不再需要的文件会被清理。\n'
            '其他已有文件保留，建议使用专用目录；基准与游戏目录均不修改。\n\n继续？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            self._cleanup_workspace()
            self._set_build_busy(False)
            self._status_label.setText('已取消生成')
            return
        tool_dir = ''
        if self._copy_tool_cb.isChecked():
            tool_dir = os.path.join(self._launcher_dir, 'tools', self._tool_combo.currentText())
        elif 'widescreen_16_9' in self._last_build_patch_ids:
            self._log('[提示] 未附带画面兼容工具，使用宽屏时请确认游戏目录已有 cnc-ddraw。')
        self._status_label.setText('正在烧录并输出文件…')
        self._worker = _BuildWorker(builder, patch_items, self._workspace,
                                    self._last_build_resources, tool_dir)
        self._worker.completed.connect(self._on_build_finished)
        self._worker.start()

    def _on_build_finished(self, result):
        self._worker.wait()
        for line in result.log:
            self._log(line)
        if not result.success:
            self._build_failed(result.error)
            return
        count = len(self._worker.output_files)
        differences = len(self._workspace.files)
        self._built_directory = os.path.dirname(result.output_path)
        self._cleanup_workspace()
        self._set_build_busy(False)
        self._status_label.setText(f'生成完成：{differences} 个差异文件 + EXE')
        self._log(f'差异覆盖包已生成: {self._built_directory}（共 {count} 个文件，含清单）')
        QMessageBox.information(
            self, '生成完成',
            f'已输出 {differences} 个差异文件、TKS_MOD.exe 和生成清单：\n{self._built_directory}\n\n'
            '将整套输出覆盖到与基准目录版本一致的原版游戏目录，'
            f'运行 {os.path.basename(result.output_path)}。\n'
            '相同文件已省略，这是差异覆盖包，不能在输出目录单独运行。')

    def _open_output_directory(self):
        if self._built_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._built_directory))

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
