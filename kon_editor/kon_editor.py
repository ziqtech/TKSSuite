#!/usr/bin/env python3
"""
TKKon.dat 可视化编辑器 (PySide6 — Godot 4.6 风格)
=============================================================
UI 样式完全对齐 skill_editor.py / shop_editor.py 的
FakeInputBox / InspectorTitle / PreviewFrame / DockHeader 体系。
主题从 themes/ 目录加载 QSS, 缺失时回退 QPalette。
底层 LZSS 引擎与 TKKon/TKT 二进制解析逻辑 100% 保留。
"""

import os
import struct
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QGroupBox, QDialog, QFileDialog, QMessageBox,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar, QSizePolicy,
    QMenu,
)
from PySide6.QtGui import QIntValidator, QColor, QIcon, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils import theme_manager
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.dock_components import DockHeader
from editor_utils.ui_helpers import themed_question, make_fake_input, update_path_labels, show_field_ref, EditorComboBox
from editor_utils.lzss import lzss_decompress_dat, lzss_compress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.picker_dialogs import StatusPickerDialog, STATUS_NAMES
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.mod_exporter import (
    diff_records, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, ModMetadataDialog, safe_mod_filename,
    load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, ModImportPreviewDialog, ModExportPreviewDialog,
)
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput
from editor_utils.kon_name_resolver import KonNameResolver
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.task_runner import run_background, is_running
from editor_utils.undo_stack import FieldUndoMixin

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data):
    return lzss_decompress_dat(data)
def lzss_compress(data):
    return lzss_compress_dat(data)
def load_tkt(tkt_path):
    return load_tkt_simple(tkt_path)

KON_REC = 40
KON_CNT = 650
KON_FIELD_COUNT = 20
KON_DECOMPRESSED = 26000

# STATUS_NAMES 由 editor_utils.picker_dialogs 提供 (见上方导入)

KON_FIELDS = [
    ("exec_mode",        0,  "执行模式",      "高字节=攻击距离(负=自身, 0=单格, 1-3=近战, 6+=远程); 低字节=范围开关"),
    ("target_param",     2,  "目标参数",      "高字节=效果面积(0=单体, 1+=菱形层数, -1/FF=全场, -2/FE=全场排除自身); 低字节=扩散开关"),
    ("target_filter",    4,  "目标过滤",      "高字节=目标格子(0=全部, 1=仅角色, 2=仅空地); 低字节=阵营匹配(0=对立, 1=同阵营, 2=任意)"),
    ("tkact_id",         6,  "TKAct动画索引", "TKAct.dat 条目索引 (0..649, -1=无)"),
    ("hp_damage",        8,  "生命伤害",      "(-1)=ATK; (0)=无; (1~999)=固定; (1001~1999)=目标生命%; (2001~2999)=ATK+; (3001+)=ATK×"),
    ("mp_damage",       10,  "内力伤害",      "(0)=无; (1~999)=固定内力伤; (1001~1999)=目标内力%"),
    ("accuracy",        12,  "附加命中",      "命中率加算值"),
    ("extra_damage",    14,  "附加伤害",      "附加伤害值 (极少使用)"),
    ("hp_restore",      16,  "生命回复",      "(0)=无; (1~999)=固定回复; (1001~1999)=最大生命%; 仅生命<25%时触发"),
    ("mp_restore",      18,  "内力回复",      "(0)=无; (1~999)=固定回复; (1001~1999)=最大内力%; 仅内力<25%时触发"),
    ("inflict_status_lo", 20, "导致状态1-16",  "施加状态位掩码低16位"),
    ("inflict_status_hi", 22, "导致状态17-32", "施加状态位掩码高16位"),
    ("remove_status_lo",  24, "解除状态1-16",  "移除状态位掩码低16位"),
    ("remove_status_hi",  26, "解除状态17-32", "移除状态位掩码高16位"),
    ("timing_mod",      28,  "时序修正",      "行动顺序修正值"),
    ("unused15",        30,  "未使用15",      "始终为0"),
    ("unused16",        32,  "未使用16",      "始终为0"),
    ("unused17",        34,  "未使用17",      "始终为0"),
    ("unused18",        36,  "未使用18",      "始终为0"),
    ("exec_flags",      38,  "执行标志",      "bit0=显示待机, bit1=物品, bit2=物理; 0=法术"),
]

ACTIVE_FIELDS = [f for f in KON_FIELDS if not f[0].startswith('unused')]

# ============================================================
# 描述解析函数
# ============================================================

def describe_exec_mode(val):
    if val < 0: return "自身目标"
    hi = (val >> 8) & 0xFF
    lo = val & 0xFF
    if hi == 0 and lo == 0: return "单格"
    parts = []
    range_text = "" if lo == 0 else "[范围禁用]"
    if hi > 0: parts.append(f"距离={hi}格")
    parts.append(range_text)
    return "  ".join(parts)

def describe_target_param(val):
    if val < 0:
        hi = (val >> 8) & 0xFF
        if hi == 255: return "全场目标"
        elif hi == 254: return "全场(排除自身)"
        return f"特殊({val})"
    hi = (val >> 8) & 0xFF
    lo = val & 0xFF
    if hi == 0 and lo == 0: return "无扩散(单体)"
    spread_text = "" if lo == 0 else "[扩散禁用]"
    parts = []
    if hi > 0: parts.append(f"面积={hi}格")
    parts.append(spread_text)
    return "  ".join(parts)

def describe_target_filter(val):
    lo = val & 0xFF
    hi = (val >> 8) & 0xFF
    target_map = {0: "全部", 1: "仅角色", 2: "仅空地"}
    faction_map = {0: "对立阵营", 1: "同阵营", 2: "任意阵营"}
    return f"{target_map.get(hi, f'目标{hi}')}  {faction_map.get(lo, f'阵营{lo}')}"

def describe_exec_flags(val):
    lo = val & 0xFF
    parts = ["显示待机" if (lo & 1) else "隐藏待机"]
    if lo & 2: parts.append("物品")
    parts.append("物理" if (lo & 4) else "法术")
    return "  ".join(parts)

def describe_hp_damage(val):
    if val == -1: return "单位攻击力"
    if val == 0: return "无伤害"
    if 1 <= val <= 999: return f"固定伤害={val}"
    if 1001 <= val <= 1999: return f"生命%伤害={val - 1000}%"
    if 2001 <= val <= 2999: return f"攻击力+{val - 2000}"
    if val >= 3001: return f"攻击力×{100 + val - 3000}%"
    return f"特殊({val})"

def describe_resource_val(val, resource_name):
    if val == 0: return f"无{resource_name}"
    if 1 <= val <= 999: return f"固定{resource_name}={val}"
    if 1001 <= val <= 1999: return f"{resource_name}%={val - 1000}%"
    return f"{resource_name}=({val})"

def kon_record_name(rec, tkt, resolver=None, compact_threshold=0):
    idx = rec['index']
    if resolver:
        name = resolver.get_name(idx, compact_threshold)
        if name and not name.startswith('空槽-') and not name.startswith('动画#'):
            return name
    cid = rec.get('tkact_id', 0)
    parts = []
    em = rec.get('exec_mode', 0)
    tp = rec.get('target_param', 0)
    if em < 0: parts.append("自身")
    elif em != 0:
        rh = (em >> 8) & 0xFF
        if rh > 0: parts.append(f"距{rh}")
    tp_hi = (tp >> 8) & 0xFF
    if tp_hi > 0: parts.append(f"面{tp_hi}")
    desc = " ".join(parts) if parts else ""
    if cid > 0: return f"动画#{cid} {desc}".strip()
    return f"空槽-#{idx}"

def load_kon(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: 解压结果无效时, 检查是否已是未压缩 raw 数据
    if (len(dec) == 0 or len(dec) % KON_REC) and len(raw) % KON_REC == 0:
        dec = raw
    if len(dec) == 0 or len(dec) % KON_REC:
        raise ValueError(
            f"解压后大小 {len(dec)} 不是 {KON_REC} 字节的整数倍, "
            "无法按 TKKon 记录解析")
    rec_count = len(dec) // KON_REC
    recs = []
    for i in range(rec_count):
        off = i * KON_REC
        vals = struct.unpack_from('<' + 'h' * KON_FIELD_COUNT, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _) in enumerate(KON_FIELDS):
            rec[fn] = vals[fi]
        recs.append(rec)
    return recs

def save_kon(fp, recs):
    buf = bytearray(len(recs) * KON_REC)
    for i, rec in enumerate(recs):
        rec['index'] = i
        off = i * KON_REC
        vals = [rec[fn] for fn, _, _, _ in KON_FIELDS]
        struct.pack_into('<' + 'h' * KON_FIELD_COUNT, buf, off, *vals)
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True

# ============================================================
# QTableWidget 排序子类
# ============================================================

class NumericTableItem(QTableWidgetItem):
    def __lt__(self, other):
        a = self.data(Qt.UserRole)
        b = other.data(Qt.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (ValueError, TypeError):
                pass
        return super().__lt__(other)




# ============================================================
# 对话框: 状态掩码多选 — 复用 editor_utils.picker_dialogs.StatusPickerDialog
# ============================================================

# ============================================================
# 对话框: 字段参考
# ============================================================

# 逆向参考: sub_43D53C(目标区域), sub_43D8B0(目标验证), sub_43E980(伤害计算),
# sub_4458B0(技能执行), sub_4434BC(动画运行时), sub_4173F8(TKKon加载)
def _build_field_ref_text():
    """TKKon 字段参考文本 (经 ui_helpers.show_field_ref 显示)。"""
    lines = ["TKKon.dat 字段映射", ""]
    lines.append(
        f"【记录布局】原版 {KON_CNT} 条 × {KON_REC} 字节 = "
        f"{KON_DECOMPRESSED} 字节；编辑器支持 650 条以上的扩展记录")
    lines.append(f"  每条 20 个字段 × 16位整数 = {KON_REC} 字节")
    lines.append("")
    lines.append("【字段语义说明】")
    lines.append("  field[0-2] 是战斗引擎操作参数，非TKT文本引用")
    lines.append("【字段详情】")
    for fn, fo, fl, cmt in KON_FIELDS:
        marker = " ● 未使用" if fn.startswith('unused') else ""
        lines.append(f"  [{fo:02d}] {fl:<10s}{marker}")
        lines.append(f"       {cmt}")
    lines.append("")
    lines.append("【字段功能说明】")
    lines.append("  [0-2]: 战斗操作参数 (目标区域/验证/伤害)")
    lines.append("  [3-5]: 动画播放参数")
    lines.append("  [6-9]: 显示效果 (特效/音效/画面)")
    lines.append("  [10-19]: 伤害与状态参数")
    lines.append("")
    lines.append("【伤害字段编码规则】")
    for s in ["0→无效果","1~999→固定值","1001~1999→最大值%(val-1000)",
               "-1→ATK","2001~2999→ATK+(val-2000)","3001+→ATK×(1+(val-3000)/100)"]:
        lines.append(f"  {s}")
    return '\n'.join(lines)

# ============================================================
# 主编辑器窗口
# ============================================================

class KonEditor(FieldUndoMixin, EditorMainWindow):
    EDITOR_KEY = "kon_editor"
    DEFAULT_SIZE = (1600, 900)
    MIN_SIZE = (1050, 650)

    HELP_TEXT = (
        "功能: 编辑《三国群侠传》技能动画数据\n"
        "数据: 每条 20 个字段 × 16位整数\n"
        "      原版 650 条 × 40 字节 = 26,000 字节\n"
        "      新建条目在列表末尾新增空记录；>650 为扩展记录，需扩容补丁\n\n"
        "特性:\n"
        "  · Godot 风格深/浅色主题切换\n"
        "  · 技能动画参数可视化编辑\n"
        "  · 伤害字段编码规则说明\n"
        "  · 每行右键: 复制 / 粘贴 / 清除；扩展记录另有删除\n"
        "  · 原版记录只能清除；扩展记录可清除或删除")

    def _init_data(self):
        self.kon_path = None
        self.tkt_path = None
        self.records = []
        self.tkt = {}
        self._resolver = None
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.mu_path = None
        self._mu_sprites = []
        self._icon_pixmaps = {}
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = -1
        self._clipboard = None

        self.widget_map = {}      # QLineEdit / EditorComboBox for direct value fields
        self.extra_map = {}       # QLabel for parsed description text
        self.split_map = {}       # (hi_w, lo_w) for split fields
        self.compact_names = True # 精简显示: >3角色时仅显示技能名
        self._init_undo()  # 撤销/重做 (P3-4)

    def _after_build(self):
        self._set_edit_enabled(False)
        self._center_window()

    # ============================================================
    # 主题
    # ============================================================

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        # kon 采用 QApplication 级样式表，让无父窗口的弹窗也继承主题
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        theme_manager.apply_theme(QApplication.instance(), self._theme_id)
        self._refresh_table()

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self):
        # -- 菜单栏 --
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录...", QKeySequence("Ctrl+O"), self._load_tks_dir)
        self.attach_recent_dirs_menu(fm)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("撤销", QKeySequence("Ctrl+Z"), self.undo)
        em.addAction("重做", QKeySequence("Ctrl+Y"), self.redo)
        em.addSeparator()
        em.addAction("新建条目", QKeySequence("Ctrl+N"), self._new_record)
        em.addAction("复制当前记录", self._copy_current)
        em.addAction("粘贴到当前记录", self._paste_current)
        em.addAction("清除当前记录", self._clear_current)
        em.addAction("删除当前记录", self._delete_current)

        vm = mb.addMenu("视图(&V)")
        self.add_theme_submenu(vm)
        vm.addAction("快速切换主题(&T)\tF5", self._toggle_theme)

        self.add_help_menu(mb)

        QShortcut("F5", self).activated.connect(self._toggle_theme)

        # -- 工具栏 --
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_input = SearchInput("搜索名称或ID")
        self.search_input.setMinimumWidth(160)
        self.search_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_input)

        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar.addWidget(btn_search)
        toolbar.addWidget(btn_clear)
        toolbar.addSpacing(8)

        self.chk_show_empty = QCheckBox("显示空槽")
        self.chk_show_empty.setChecked(True)
        self.chk_show_empty.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.chk_show_empty)

        self.chk_compact = QCheckBox("精简显示")
        self.chk_compact.setChecked(True)
        self.chk_compact.setToolTip("当同一技能效果被超过3个角色配置时，仅显示技能名称")
        self.chk_compact.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.chk_compact)
        toolbar.addSpacing(8)

        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)

        btn_theme = QPushButton("切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        btn_theme.setToolTip("切换 Godot 深色/浅色主题 (F5)")
        toolbar.addWidget(btn_theme)
        toolbar.addStretch()

        self.btn_apply = QPushButton("应用修改")
        self.btn_apply.clicked.connect(self._apply_edit)
        self.btn_reset = QPushButton("撤销修改")
        self.btn_reset.clicked.connect(self._reset_edit)
        toolbar.addWidget(self.btn_apply)
        toolbar.addWidget(self.btn_reset)

        # -- 主布局 --
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)
        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        self._build_table(splitter)
        self._build_edit_panel(splitter)
        splitter.setSizes([540, 756])
        self.splitter = splitter

        # 底部路径栏
        # 路径标签不设 objectName: 让 update_path_labels 写入的 [status] 属性生效着色
        # (绿=已加载 / 橙=缺失 / 灰=未加载)。若设 #hintLabel, ID 选择器优先级高于
        # [status] 会把状态色盖成灰色, 与 item/warpc 等主流编辑器不一致。
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_kon = QLabel("TKKon.dat: 未加载")
        self.lbl_tkt = QLabel("TKT.dat: 未加载")
        self.lbl_mu = QLabel("Mu.JVG: 未加载")
        path_layout.addWidget(self.lbl_kon)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_mu)
        path_layout.addStretch()
        # 右侧操作提示文字用 hintLabel (灰色小字)
        self.status_label = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.status_label.setObjectName("hintLabel")
        path_layout.addWidget(self.status_label)
        main_layout.addLayout(path_layout)

    # ----------- 左侧表格 -----------

    def _build_table(self, parent):
        self.table = AdaptiveTableWidget(
            0, 8,
            stretch_columns={3},
            minimum_widths=[46, 52, 52, 96, 72, 70, 72, 54],
            row_height=44,
        )
        self.table.setHorizontalHeaderLabels(["序号", "动画", "距离", "名称", "范围", "伤害", "目标", "类型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        parent.addWidget(self.table)

    # ----------- 右侧编辑面板 (Dock 风格) -----------

    def _build_edit_panel(self, parent):
        edit_content = QWidget()
        right_layout = QVBoxLayout(edit_content)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        edit_container = QWidget()
        self.edit_layout = QVBoxLayout(edit_container)
        self.edit_layout.setContentsMargins(4, 0, 4, 4)
        self.edit_layout.setSpacing(4)

        # 预览面板 (PreviewFrame — 对齐 skill_editor)
        preview = QFrame()
        preview.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(8, 12, 8, 12)
        pl.setSpacing(6)
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        pl.addWidget(self.preview_name)
        self.preview_type = QLabel("")
        self.preview_type.setProperty("class", "PreviewMeta")
        self.preview_type.setWordWrap(True)
        pl.addWidget(self.preview_type)
        self.preview_desc = QLabel("(空动作)")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        pl.addWidget(self.preview_desc)
        self.preview_sub = QLabel("")
        self.preview_sub.setProperty("class", "PreviewSubMeta")
        self.preview_sub.setWordWrap(True)
        pl.addWidget(self.preview_sub)
        self.edit_layout.addWidget(preview)

        # 字段组 — Dock 风格分组 (列数: 4, 4, 5, 5)
        self._build_field_group("战斗执行参数 (offset 0–6)", ACTIVE_FIELDS[:4], 4)
        self._build_field_group("伤害/回复参数 (offset 8–18)", ACTIVE_FIELDS[4:10], 4)
        self._build_field_group("状态位掩码 (offset 20–28)", ACTIVE_FIELDS[10:15], 4)
        # 执行标志
        self._build_field_group("执行标志 (offset 38)", [KON_FIELDS[-1]], 1)

        self.edit_layout.addStretch()
        scroll.setWidget(edit_container)
        right_layout.addWidget(scroll, 1)

        parent.addWidget(edit_content)
        self._edit_dock_body = edit_content

    def _build_field_group(self, title, fields, cols=4, force_last_row=False):
        """Dock 风格分组: DockHeader + DockBody + QGridLayout"""
        group_w = QWidget()
        group_lay = QVBoxLayout(group_w)
        group_lay.setContentsMargins(0, 0, 0, 0)
        group_lay.setSpacing(0)
        group_lay.addWidget(DockHeader(title))

        body = QWidget()
        body.setObjectName("DockBody")
        body_inner = QVBoxLayout(body)
        body_inner.setContentsMargins(8, 8, 8, 8)

        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        for c in range(cols):
            grid.setColumnStretch(c, 1)

        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            if force_last_row and fn == 'exec_flags':
                # 执行标志单独占一整行
                r = (fi // cols) + 1  # 下一行
                self._build_field(grid, r, 0, fn, fo, fl, cmt, span=cols)
            else:
                r, c = divmod(fi, cols)
                self._build_field(grid, r, c, fn, fo, fl, cmt)

        body_inner.addLayout(grid)
        group_lay.addWidget(body)
        self.edit_layout.addWidget(group_w)

    def _build_field(self, grid, row, col, fn, fo, fl, cmt, span=1):
        """单个字段: PropLabel 在上, FakeInputBox 在中, ExtraPreviewText 在下"""
        cell = QVBoxLayout()
        cell.setSpacing(2)

        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        is_unused = fn.startswith('unused')
        is_mask = 'status' in fn
        is_filter = fn == 'target_filter'
        is_split = fn in ('exec_mode', 'target_param')
        is_bitmask = fn == 'exec_flags'

        if is_bitmask:
            row_w = QWidget()
            h = QHBoxLayout(row_w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            cb0 = QCheckBox("显示待机动画")
            cb0.setToolTip("显示施法者待机动画 (bit0)")
            cb1 = QCheckBox("使用物品")
            cb1.setToolTip("物品触发逻辑 (bit1)")
            cb2 = QCheckBox("物理攻击")
            cb2.setToolTip("物理伤害公式 (bit2)")
            h.addWidget(cb0)
            h.addWidget(cb1)
            h.addWidget(cb2)
            h.addStretch()
            self.split_map[fn] = (cb0, cb1, cb2)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            cell.addWidget(row_w)
            cell.addWidget(extra, 0, Qt.AlignLeft | Qt.AlignTop)
            self.extra_map[fn] = extra

        elif is_split:
            hi_w = QLineEdit()
            hi_w.setValidator(QIntValidator(-128, 127))
            hi_w.setFixedWidth(48)
            lo_w = EditorComboBox()
            lo_w.addItems(["启用", "禁用"])
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(0)
            if fn == 'exec_mode':
                hi_label = "距离"
                lo_label = "范围"
            elif fn == 'target_param':
                hi_label = "面积"
                lo_label = "扩散"
            else:
                hi_label = ""
                lo_label = ""
            if hi_label:
                hl = QLabel(hi_label)
                hl.setProperty("class", "SplitFieldLabel")
                bh.addWidget(hl)
            bh.addWidget(hi_w)
            sep_lbl = QLabel(lo_label)
            sep_lbl.setProperty("class", "SplitFieldLabel")
            bh.addWidget(sep_lbl)
            bh.addWidget(lo_w, 1)
            self.split_map[fn] = (hi_w, lo_w)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell.addWidget(box)
            cell.addWidget(extra, 0, Qt.AlignLeft | Qt.AlignTop)
            self.extra_map[fn] = extra

        elif is_filter:
            hi_w = EditorComboBox()
            hi_w.addItems(["全部", "仅角色", "仅空地"])
            lo_w = EditorComboBox()
            lo_w.addItems(["对立阵营", "同阵营", "任意阵营"])
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(0)
            hl = QLabel("格子")
            hl.setProperty("class", "SplitFieldLabel")
            bh.addWidget(hl)
            bh.addWidget(hi_w)
            sep_lbl = QLabel("阵营")
            sep_lbl.setProperty("class", "SplitFieldLabel")
            bh.addWidget(sep_lbl)
            bh.addWidget(lo_w, 1)
            self.split_map[fn] = (hi_w, lo_w)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell.addWidget(box)
            cell.addWidget(extra, 0, Qt.AlignLeft | Qt.AlignTop)
            self.extra_map[fn] = extra

        elif is_mask:
            inf = fn.startswith('inflict')
            btn = QPushButton("选择导致状态…" if inf else "选择解除状态…")
            btn.setObjectName("StatusPickerButton")
            hidden = QLineEdit()
            hidden.hide()
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(0)
            bh.addWidget(btn, 1)
            self.widget_map[fn] = hidden
            status_frame = QWidget()
            self.extra_map[fn] = status_frame
            btn.clicked.connect(lambda checked, f=fn: self._pick_status(f))
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell.addWidget(box)
            cell.addWidget(status_frame, 0, Qt.AlignLeft | Qt.AlignTop)

        else:
            edit = QLineEdit()
            edit.setValidator(QIntValidator(-32768, 32767))
            if is_unused: edit.setEnabled(False)
            self.widget_map[fn] = edit
            box = make_fake_input(edit)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell.addWidget(box)
            if not is_unused:
                extra = QLabel("")
                extra.setProperty("class", "ExtraPreviewText")
                cell.addWidget(extra, 0, Qt.AlignLeft | Qt.AlignTop)
                self.extra_map[fn] = extra

        cell.addStretch()
        grid.addLayout(cell, row, col, 1, span)

    # ----------- 窗口控制 -----------

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_splitter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_splitter_width()

    def _sync_splitter_width(self):
        splitter = getattr(self, 'splitter', None)
        if splitter is None:
            return
        total = splitter.width()
        if total <= 0:
            return
        if total < 1296:
            left = max(420, int(total * 0.42))
        else:
            left = min(680, 540 + int((total - 1296) * 0.25))
        splitter.setSizes([left, max(1, total - left)])

    def _center_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _set_edit_enabled(self, en):
        self._edit_dock_body.setEnabled(en)

    # ----------- 数据加载 -----------

    def load_tks_dir(self, d):
        ko = os.path.join(d, "TKKon.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(ko):
            QMessageBox.warning(self, "文件缺失", "未找到 TKKon.dat")
            return
        self.kon_path = ko
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        self._reload()

    def _reload(self):
        if not self.kon_path: return
        if is_running(getattr(self, '_load_worker', None)): return
        self.status_label.setText("加载中…")
        kon_path, tkt_path, mu_path = self.kon_path, self.tkt_path, self.mu_path

        # 后台线程: 纯文件 IO/解码 (P3-3), UI 刷新在 _on_load_success
        def work(w):
            tkt = load_tkt(tkt_path) if tkt_path else {}
            mu = load_mu_sprites(mu_path) if mu_path else []
            try:
                resolver = KonNameResolver(os.path.dirname(kon_path))
            except Exception:
                resolver = None
            records = load_kon(kon_path)
            return tkt, mu or [], resolver, records

        self._load_worker = run_background(
            self, work,
            on_success=self._on_load_success,
            on_error=self._on_load_error)

    def _on_load_success(self, result):
        tkt, mu, resolver, records = result
        self.tkt = tkt
        self._mu_sprites = mu
        self._icon_pixmaps.clear()
        self._resolver = resolver
        self.records = records
        self.clear_undo()  # 数据整体重载, 旧变更集失效 (P3-4)
        self._dirty = False
        self._original_records = [[rec[fn] for fn, _, _, _ in KON_FIELDS] for rec in self.records]
        nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        self.status_label.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _on_load_error(self, err_msg):
        QMessageBox.critical(self, "加载失败", err_msg)
        self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _update_paths(self):
        # 深浅取自 apply_theme_to_window 无条件维护的 _is_dark 兼容属性
        # (原先引用的 self.is_dark_theme 全仓库无定义, 任何加载路径都会
        # AttributeError — 顺手修复的存量缺陷)
        update_path_labels([
            (self.lbl_kon, self.kon_path, "TKKon.dat"),
            (self.lbl_tkt, self.tkt_path, "TKT.dat"),
            (self.lbl_mu, self.mu_path, "Mu.JVG"),
        ], getattr(self, '_is_dark', True))

    # ----------- 筛选/表格 -----------

    def _apply_filter(self):
        q = self.search_input.text()
        show_empty = self.chk_show_empty.isChecked()
        self.compact_names = self.chk_compact.isChecked()
        self.filtered_indices = []
        for rec in self.records:
            if not show_empty:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
            if q:
                nm = kon_record_name(rec, self.tkt, self._resolver)
                if not search_match(
                    q,
                    rec['index'], rec['tkact_id'], rec['exec_mode'], nm,
                    *(rec[fn] for fn, _, _, _ in KON_FIELDS),
                ):
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        # 修改态由标题栏 * 标记呈现 (基类 _dirty property 同步 setWindowModified)
        self.status_label.setText(
            f"显示 {len(self.filtered_indices)}/{len(self.records)} (有效 {nonempty}) | Ctrl+S 保存")

    def _clear_filter(self):
        self.search_input.clear()
        self._apply_filter()

    def _refresh_table(self):
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            has_data = any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS)

            nm = kon_record_name(r, self.tkt, self._resolver, self._compact_threshold())

            # 颜色标记 (名称语义优先)
            if "原版未完成" in nm:
                color = QColor("#CC3333")  # 阶段 2 豁免: 状态领域色 (红)
            elif "未知" in nm:
                color = QColor("#CC8800")  # 阶段 2 豁免: 状态领域色 (橙)
            elif "空槽" in nm:
                color = QColor("#888888") if getattr(self, '_is_dark', True) else QColor("#AAAAAA")  # 主题感知: 深浅两档
            elif r['tkact_id'] == -1:
                color = QColor("#2266CC")  # 阶段 2 豁免: 状态领域色 (蓝)
            elif has_data:
                color = QColor("#228B22") if getattr(self, '_is_dark', True) else QColor("#1a7a1a")  # 主题感知: 深浅两档
            else:
                color = QColor("#AAAAAA") if getattr(self, '_is_dark', True) else QColor("#999999")  # 主题感知: 深浅两档

            em = r['exec_mode'] & 0xFFFF
            em_hi = (em >> 8) & 0xFF
            if em_hi >= 128: dist_str = "自身"
            elif em_hi == 0: dist_str = "单格"
            else: dist_str = f"{em_hi}格"

            tp = r['target_param'] & 0xFFFF
            tp_hi = (tp >> 8) & 0xFF
            if tp_hi == 255: area_str = "全场"
            elif tp_hi == 254: area_str = "排除自身"
            elif tp_hi > 0: area_str = f"{tp_hi}格"
            else: area_str = "单体"

            db = r['hp_damage']
            if db == -1: dmg_str = "攻击力"
            elif db == 0: dmg_str = "-"
            elif 1001 <= db <= 1999: dmg_str = f"{db-1000}%"
            elif 2001 <= db <= 2999: dmg_str = f"攻+{db-2000}"
            elif db >= 3001: dmg_str = f"攻×{100+db-3000}%"
            else: dmg_str = str(db)

            tf_val = r['target_filter']
            tf_lo = tf_val & 0xFF
            tf_hi = (tf_val >> 8) & 0xFF
            faction_map = {0: "敌", 1: "友", 2: "任意"}
            target_map = {0: "", 1: "仅人", 2: "仅地"}
            tf_str = f"{faction_map.get(tf_lo, '?')}{target_map.get(tf_hi, '')}"

            ef = r['exec_flags'] & 0xFF
            ef_str = "物理" if (ef & 4) else "法术"

            vals = [str(r['index']), str(r['tkact_id']), dist_str,
                    nm if nm else f"(空-#{idx})", area_str, dmg_str, tf_str, ef_str]
            sort_keys = [r['index'], r['tkact_id'], (em >> 8) & 0xFF,
                         None, (tp >> 8) & 0xFF, r['hp_damage'],
                         r['target_filter'], r['exec_flags'] & 0xFF]

            self.table.insertRow(row)
            for c_col, v in enumerate(vals):
                item = NumericTableItem(v)
                item.setData(Qt.UserRole, sort_keys[c_col])
                item.setForeground(color)
                if c_col in (0, 1): item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, c_col, item)

        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)

    def _compact_threshold(self) -> int:
        return 3 if self.compact_names else 0

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._editing_idx = idx
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        nm = kon_record_name(rec, self.tkt, self._resolver, self._compact_threshold())
        cid = rec.get('tkact_id', 0)
        em = rec.get('exec_mode', 0)
        tp = rec.get('target_param', 0)

        # 预览面板
        self.preview_name.setText(nm if nm else "空槽")
        info_parts = []
        em_desc = describe_exec_mode(em)
        if em_desc and em_desc != "单格": info_parts.append(f"攻击={em_desc}")
        tp_desc = describe_target_param(tp)
        if tp_desc and tp_desc != "无扩散(单体)": info_parts.append(f"效果={tp_desc}")
        tf_val = rec.get('target_filter', 0)
        if tf_val: info_parts.append(describe_target_filter(tf_val))
        db = rec.get('hp_damage', 0)
        if db: info_parts.append(f"伤害={describe_hp_damage(db)}")
        mpd = rec.get('mp_damage', 0)
        if mpd: info_parts.append(f"内伤={describe_resource_val(mpd, '内力伤害')}")
        hr = rec.get('hp_restore', 0)
        if hr: info_parts.append(f"回复={describe_resource_val(hr, '生命回复')}")
        mr = rec.get('mp_restore', 0)
        if mr: info_parts.append(f"回内={describe_resource_val(mr, '内力回复')}")
        ef_val = rec.get('exec_flags', 0)
        if ef_val: info_parts.append(describe_exec_flags(ef_val))
        self.preview_desc.setText(" | ".join(info_parts) if info_parts else "(空动作)")

        # 类型元数据
        ef = rec.get('exec_flags', 0) & 0xFF
        if ef & 4: type_str = "物理攻击"
        elif ef & 2: type_str = "物品使用"
        elif ef & 1: type_str = "Buff/自身"
        else: type_str = "法术攻击"
        timing = rec.get('timing_mod', 0)
        self.preview_type.setText(
            f"【{type_str}】 | 动画ID={cid} | 命中+{rec.get('accuracy', 0)} | 附加伤={rec.get('extra_damage', 0)}"
            + (f" | 时序{timing:+d}" if timing else "")
        )
        self.preview_sub.setText("")

        # 填充字段
        _dmg_desc = {
            'hp_damage': describe_hp_damage,
            'mp_damage': lambda v: describe_resource_val(v, '内力伤害'),
            'hp_restore': lambda v: describe_resource_val(v, '生命回复'),
            'mp_restore': lambda v: describe_resource_val(v, '内力回复'),
        }
        _split_desc = {
            'exec_mode': describe_exec_mode,
            'target_param': describe_target_param,
            'target_filter': describe_target_filter,
        }

        for fn, fo, fl, _ in KON_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if w: w.setText(str(val))

            if fn in self.extra_map:
                if fn in _dmg_desc:
                    self.extra_map[fn].setText(_dmg_desc[fn](int(val) if val else 0))
                elif fn in _split_desc:
                    self.extra_map[fn].setText(_split_desc[fn](val))
                elif fn == 'exec_flags':
                    self.extra_map[fn].setText(describe_exec_flags(val))
                elif 'status' in fn:
                    self._update_status_label(fn, int(val) if val else 0)
                else:
                    self.extra_map[fn].setText("")

        # 拆分字段
        for fn in ('exec_mode', 'target_param', 'target_filter'):
            val = rec.get(fn, 0)
            hi = (val >> 8) & 0xFF
            lo = val & 0xFF
            if fn not in self.split_map: continue
            w1, w2 = self.split_map[fn]
            if fn == 'exec_mode':
                if hi >= 128: hi -= 256
                w1.setText(str(hi))
                w2.setCurrentIndex(0 if lo == 0 else 1)
            elif fn == 'target_param':
                w1.setText(str(hi))
                w2.setCurrentIndex(0 if lo == 0 else 1)
            elif fn == 'target_filter':
                w1.setCurrentIndex(hi if hi < 3 else 0)
                w2.setCurrentIndex(lo if lo < 3 else 0)

        # exec_flags 复选框
        if 'exec_flags' in self.split_map:
            lo = rec.get('exec_flags', 0) & 0xFF
            cb0, cb1, cb2 = self.split_map['exec_flags']
            cb0.setChecked(bool(lo & 1))
            cb1.setChecked(bool(lo & 2))
            cb2.setChecked(bool(lo & 4))

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    def _pick_status(self, fn):
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        base = 0 if fn.endswith('_lo') else 16
        inf = fn.startswith('inflict')
        title = "选择导致状态 (位掩码)" if inf else "选择解除状态 (位掩码)"
        dlg = StatusPickerDialog(self, title, STATUS_NAMES, cur, base, self._get_icon_pixmap, inf)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            new_mask = dlg.selected_mask
            self.widget_map[fn].setText(str(new_mask))
            self._update_status_label(fn, new_mask & 0xFFFF)

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_lo') else 16
        inf = fn.startswith('inflict')
        status_class = "StatusInflict" if inf else "StatusRemove"
        frame = self.extra_map.get(fn)
        if not frame: return
        # 清除旧内容
        for c in frame.findChildren(QWidget):
            c.setParent(None)
        frame_layout = frame.layout()
        if not frame_layout:
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(0, 0, 0, 0)
            frame_layout.setSpacing(1)
        sel = [f"{base+i}.{STATUS_NAMES[base+i]}" for i in range(16)
               if (mask & (1 << i)) and base + i < len(STATUS_NAMES)]
        if sel:
            COLS = 3
            for si, nm in enumerate(sel):
                r, c = divmod(si, COLS)
                while frame_layout.count() <= r:
                    row_w = QWidget()
                    row_lay = QHBoxLayout(row_w)
                    row_lay.setContentsMargins(0, 0, 0, 0)
                    row_lay.setSpacing(6)
                    frame_layout.addWidget(row_w)
                row_w = frame_layout.itemAt(r).widget()
                row_lay = row_w.layout()
                lbl = QLabel(nm)
                lbl.setProperty("class", status_class)
                # 需要强制刷新 QSS class
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
                row_lay.addWidget(lbl)
        else:
            lbl = QLabel("(无)")
            lbl.setProperty("class", status_class)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            frame_layout.addWidget(lbl)

    def _apply_edit(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]
        undo_before = {fn: rec[fn] for fn, _, _, _ in KON_FIELDS}

        # 拆分字段
        for fn in ('exec_mode', 'target_param', 'target_filter'):
            if fn in self.split_map:
                w1, w2 = self.split_map[fn]
                try:
                    if fn == 'target_filter':
                        hi, lo = w1.currentIndex(), w2.currentIndex()
                    else:
                        hi = int(w1.text()) & 0xFF
                        lo = 0 if w2.currentIndex() == 0 else 1
                    combined = (hi << 8) | lo
                    if combined >= 0x8000: combined -= 0x10000
                    rec[fn] = combined
                except ValueError:
                    pass

        # exec_flags
        if 'exec_flags' in self.split_map:
            cb0, cb1, cb2 = self.split_map['exec_flags']
            lo = (1 if cb0.isChecked() else 0) | (2 if cb1.isChecked() else 0) | (4 if cb2.isChecked() else 0)
            rec['exec_flags'] = lo

        # 普通字段
        for fn, _, _, _ in KON_FIELDS:
            if fn.startswith('unused') or fn in self.split_map: continue
            w = self.widget_map.get(fn)
            if not w: continue
            try:
                v = int(w.text() or 0)
                if v > 32767: v = 32767
                if v < -32768: v = -32768
                rec[fn] = v
            except ValueError:
                rec[fn] = 0

        self.push_field_changes(
            rec['index'], self.field_diff(undo_before, rec, [fn for fn, _, _, _ in KON_FIELDS]),
            f"修改记录 #{rec['index']}")
        self._dirty = True
        self._apply_filter()
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == rec['index']:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                break
        self.status_label.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx >= 0:
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 编辑操作 -----------

    def _record_is_empty(self, rec):
        return all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS)

    def _select_record(self, idx):
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == idx:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                return True
        return False

    def _on_table_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.addAction("新增条目", self._new_record)
            menu.exec(self.table.viewport().mapToGlobal(pos))
            return
        row = item.row()
        idx = int(self.table.item(row, 0).text())
        rec = self.records[idx]
        self._editing_idx = idx
        self._populate_edit(rec)

        menu = QMenu(self)
        menu.addAction("复制", lambda: self._clipboard_copy(idx))
        paste_action = menu.addAction("粘贴", lambda: self._clipboard_paste(idx))
        paste_action.setEnabled(self._clipboard is not None)
        menu.addAction("清除", lambda: self._clear_record(idx))
        if idx >= KON_CNT:
            menu.addAction("删除", lambda: self._delete_record(idx))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_record(self, idx):
        if idx < KON_CNT or idx >= len(self.records):
            return
        if themed_question(
                self, "确认删除",
                f"确定删除扩展记录 #{idx} 吗？\n"
                "删除后后续记录序号会自动前移。") != QMessageBox.Yes:
            return
        self.records.pop(idx)
        for i, rec in enumerate(self.records):
            rec['index'] = i
        self._dirty = True
        self._editing_idx = -1
        self._apply_filter()
        self.status_label.setText(
            f"已删除扩展记录 #{idx} (共 {len(self.records)} 条, 已修改)")

    def _new_record(self, source=None):
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        idx = len(self.records)
        rec = {'index': idx}
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = 0
        self.records.append(rec)
        self._dirty = True
        self.search_input.clear()
        if not self.chk_show_empty.isChecked():
            self.chk_show_empty.setChecked(True)
        else:
            self._apply_filter()
        self._select_record(idx)
        self._populate_edit(rec)
        self.status_label.setText(
            f"已新增空记录 #{idx} (共 {len(self.records)} 条, 已修改)")

    def _clipboard_copy(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx < 0 or idx >= len(self.records):
            return
        src = self.records[idx]
        self._clipboard = {fn: src[fn] for fn, _, _, _ in KON_FIELDS}
        self.status_label.setText(
            f"已复制记录 #{idx} (可右键粘贴到任意记录)")

    def _copy_current(self):
        self._clipboard_copy()

    def _clipboard_paste(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if self._clipboard is None or idx < 0 or idx >= len(self.records):
            return
        rec = self.records[idx]
        if not self._record_is_empty(rec):
            if themed_question(
                    self, "确认覆盖",
                    f"粘贴将覆盖记录 #{idx} 的现有内容，是否继续？") != QMessageBox.Yes:
                return
        paste_before = {fn: rec[fn] for fn, _, _, _ in KON_FIELDS}
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = self._clipboard[fn]
        self.push_field_changes(
            idx, self.field_diff(paste_before, rec, [fn for fn, _, _, _ in KON_FIELDS]),
            f"粘贴到记录 #{idx}")
        self._dirty = True
        if self._record_is_empty(rec) and not self.chk_show_empty.isChecked():
            self.chk_show_empty.setChecked(True)
        else:
            self._apply_filter()
        self._select_record(idx)
        self._populate_edit(rec)
        self.status_label.setText(f"已粘贴到记录 #{idx}")

    def _paste_current(self):
        self._clipboard_paste()

    def _delete_record(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx < 0 or idx >= len(self.records):
            return
        if idx < KON_CNT:
            QMessageBox.information(
                self, "提示",
                f"原版记录 #{idx} 不能删除，只能使用清除功能。")
            return
        self._remove_record(idx)

    def _clear_record(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx < 0 or idx >= len(self.records):
            return
        rec = self.records[idx]
        if self._record_is_empty(rec):
            QMessageBox.information(self, "提示", "当前记录已经为空")
            return
        if themed_question(
                self, "确认清除",
                f"确定清除记录 #{idx} 的全部字段吗？\n"
                "是否继续？") != QMessageBox.Yes:
            return
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = 0
        self._dirty = True
        if not self.chk_show_empty.isChecked():
            self.chk_show_empty.setChecked(True)
        else:
            self._apply_filter()
        self._populate_edit(rec)
        self.status_label.setText(f"已清除记录 #{rec['index']}")

    def _delete_current(self):
        self._delete_record()

    def _clear_current(self):
        self._clear_record()

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.kon_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        if themed_question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.kon_path}\n\n原文件将被覆盖 (生成 .bak).") != QMessageBox.Yes: return
        if is_running(getattr(self, '_save_worker', None)): return
        kon_path = self.kon_path
        records = self.records

        # 后台线程: .bak 备份 + 压缩写盘 (P3-3)
        def work(w):
            try:
                with open(kon_path, 'rb') as s:
                    with open(kon_path + ".bak", 'wb') as d:
                        d.write(s.read())
            except Exception:
                pass
            save_kon(kon_path, records)
            return kon_path

        self.status_label.setText("正在保存…")
        self._save_worker = run_background(
            self, work,
            on_success=self._on_save_success,
            on_error=self._on_save_error)

    def _on_save_success(self, kon_path):
        self._dirty = False
        self.status_label.setText(f"已保存 → {kon_path}")
        QMessageBox.information(self, "保存成功", f"已保存\n备份: {kon_path}.bak")

    def _on_save_error(self, err_msg):
        QMessageBox.critical(self, "保存失败", err_msg)

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        if not self.records or not self._original_records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        current_fields = [[rec[fn] for fn, _, _, _ in KON_FIELDS] for rec in self.records]
        field_count = KON_FIELD_COUNT
        diff_result = diff_records(self._original_records, current_fields, field_count, len(self._original_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        crc = compute_crc32(self.kon_path) if self.kon_path else "0x00000000"
        data_json = build_data_diff_json(target="TKKon.dat", record_size=KON_REC, field_type="int16",
            field_count=field_count, original_count=len(self._original_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKKon.dat.json", "target": "TKKon.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKKon.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_label.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 预构建当前字段
        current_fields = [[rec[fn] for fn, _, _, _ in KON_FIELDS] for rec in self.records]

        def _compute_stats(ref_dir):
            ref_records = load_reference_dat_fields(ref_dir, "TKKon.dat",
                rec_size=KON_REC, field_count=KON_FIELD_COUNT, field_fmt='h', use_lzss=True)
            if ref_records is None:
                return {"valid": False, "error": "目录中未找到 TKKon.dat"}
            diff = diff_records(ref_records, current_fields, KON_FIELD_COUNT, len(ref_records))
            targets = []
            if diff['modified'] or diff['appended']:
                targets.append({"name": "TKKon.dat",
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": 0})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.kon_path) if self.kon_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_records = load_reference_dat_fields(ref_dir, "TKKon.dat",
            rec_size=KON_REC, field_count=KON_FIELD_COUNT, field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKKon.dat")
            return
        diff_result = diff_records(ref_records, current_fields, KON_FIELD_COUNT, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        crc = compute_crc32(os.path.join(ref_dir, "TKKon.dat"))
        data_json = build_data_diff_json(target="TKKon.dat", record_size=KON_REC, field_type="int16",
            field_count=KON_FIELD_COUNT, original_count=len(ref_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKKon.dat.json", "target": "TKKon.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKKon.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_label.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        if "TKKon.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 TKKon.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.kon_path) if self.kon_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, records = import_tksmod_records(
            fp, ref_dir, "TKKon.dat",
            rec_size=KON_REC, field_count=KON_FIELD_COUNT,
            field_fmt='h', use_lzss=True
        )
        if records is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 TKKon.dat")
            return

        new_records = []
        for i, fields in enumerate(records):
            rec = {'index': i}
            for fi, (fn, _, _, _) in enumerate(KON_FIELDS):
                rec[fn] = fields[fi] if fi < len(fields) else 0
            new_records.append(rec)

        self.records = new_records
        self._original_records = [list(row) for row in records]
        self._dirty = False

        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self.status_label.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(self.records)} 条记录")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 条记录。\n"
            f"您现在可以继续编辑并重新导出。")

    # ----------- 帮助 -----------

    def _extra_help_actions(self):
        """帮助菜单专属项: 字段参考 (挂在"帮助说明"之后)。"""
        return [("字段参考", self._show_field_ref)]

    def _show_field_ref(self):
        show_field_ref(self, _build_field_ref_text())

    # 逆向参考: sub_43D53C, sub_43D8B0, sub_43E980, sub_4458B0, sub_4434BC, sub_4173F8

# ============================================================
# 入口
# ============================================================

def main():
    run_editor(KonEditor, "TKKon Editor")

if __name__ == '__main__':
    main()
