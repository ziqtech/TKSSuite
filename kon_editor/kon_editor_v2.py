#!/usr/bin/env python3
"""
TKKon.dat 可视化编辑器 (PySide6 — Godot 4.6 风格)
=============================================================
UI 样式完全对齐 skill_editor_v2.py / shop_editor_v2.py 的
FakeInputBox / InspectorTitle / PreviewFrame / DockHeader 体系。
主题从 themes/ 目录加载 QSS, 缺失时回退 QPalette。
底层 LZSS 引擎与 TKKon/TKT 二进制解析逻辑 100% 保留。
"""

import os
import struct
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QGroupBox, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar, QSizePolicy,
)
from PySide6.QtGui import QIntValidator, QColor, QFont, QIcon, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader
from editor_utils.ui_helpers import make_fake_input, update_path_labels, confirm_close, themed_messagebox, NoWheelComboBox
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
from editor_utils.version import format_title, format_about_header
from editor_utils.window_theme import apply_godot_theme
from editor_utils.kon_name_resolver import KonNameResolver

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
    # 兜底: LZSS 解压大小不匹配预期时, 检查是否已是未压缩 raw 数据
    if len(dec) != KON_DECOMPRESSED and len(raw) == KON_DECOMPRESSED:
        dec = raw
    if len(dec) != KON_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 26000")
    recs = []
    for i in range(KON_CNT):
        off = i * KON_REC
        vals = struct.unpack_from('<' + 'h' * KON_FIELD_COUNT, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _) in enumerate(KON_FIELDS):
            rec[fn] = vals[fi]
        recs.append(rec)
    return recs

def save_kon(fp, recs):
    buf = bytearray(KON_CNT * KON_REC)
    for rec in recs[:KON_CNT]:
        i = rec['index']
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
class FieldRefDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段参考")
        self.resize(700, 580)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        lines = ["TKKon.dat 字段映射", ""]
        lines.append(f"【记录布局】{KON_CNT} 条 × {KON_REC} 字节 = {KON_DECOMPRESSED} 字节")
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
        text.setPlainText('\n'.join(lines))
        layout.addWidget(text)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(btn_close)
        layout.addLayout(bl)

# ============================================================
# 主编辑器窗口
# ============================================================

class KonEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(format_title("kon_editor"))
        self.resize(1320, 820)
        self.setMinimumSize(1050, 650)

        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))

        app_inst = QApplication.instance()
        self.is_dark_theme = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        apply_godot_theme(self, self.is_dark_theme)
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

        self.widget_map = {}      # QLineEdit / QComboBox for direct value fields
        self.extra_map = {}       # QLabel for parsed description text
        self.split_map = {}       # (hi_w, lo_w) for split fields
        self.compact_names = True # 精简显示: >3角色时仅显示技能名

        self._build_ui()
        self._apply_theme()
        self._set_edit_enabled(False)
        self._center_window()

    # ============================================================
    # 主题
    # ============================================================

    def _apply_theme(self):
        ThemeManager.apply_theme(QApplication.instance(), "dark" if self.is_dark_theme else "light")

    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        self._apply_theme()
        self._refresh_table()
        apply_godot_theme(self, self.is_dark_theme)

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self):
        # -- 菜单栏 --
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录...", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新建条目", QKeySequence("Ctrl+N"), self._new_record)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)

        vm = mb.addMenu("视图(&V)")
        vm.addAction("切换 Godot 主题 (Dark/Light)\tF5", self._toggle_theme)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段参考", self._show_field_ref)
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于编辑器", self._show_about)

        QShortcut("F5", self).activated.connect(self._toggle_theme)

        # -- 工具栏 --
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setFixedWidth(160)
        self.search_input.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_input)

        btn_search = QPushButton("🔍 搜索")
        btn_search.clicked.connect(self._apply_filter)
        btn_clear = QPushButton("✕ 清除")
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

        btn_reload = QPushButton("🔄 重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)

        btn_theme = QPushButton("🌗 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        btn_theme.setToolTip("切换 Godot 深色/浅色主题 (F5)")
        toolbar.addWidget(btn_theme)
        toolbar.addStretch()

        self.btn_apply = QPushButton("✅ 应用修改")
        self.btn_apply.clicked.connect(self._apply_edit)
        self.btn_reset = QPushButton("🔄 撤销修改")
        self.btn_reset.clicked.connect(self._reset_edit)
        toolbar.addWidget(self.btn_apply)
        toolbar.addWidget(self.btn_reset)

        # -- 主布局 --
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(4)
        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        self._build_table(splitter)
        self._build_edit_panel(splitter)
        splitter.setSizes([480, 820])

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_kon = QLabel("TKKon.dat: 未加载")
        self.lbl_kon.setObjectName("hintLabel")
        self.lbl_tkt = QLabel("TKT.dat: 未加载")
        self.lbl_tkt.setObjectName("hintLabel")
        path_layout.addWidget(self.lbl_kon)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt)
        path_layout.addStretch()
        self.status_label = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.status_label.setObjectName("hintLabel")
        path_layout.addWidget(self.status_label)
        main_layout.addLayout(path_layout)

    # ----------- 左侧表格 -----------

    def _build_table(self, parent):
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["序号", "动画", "距离", "名称", "范围", "伤害", "目标", "类型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        col_widths = [38, 42, 42, 95, 52, 55, 55, 50]
        for i, w in enumerate(col_widths):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_table_select)
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

        # 预览面板 (PreviewFrame — 对齐 skill_editor_v2)
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
            lo_w = NoWheelComboBox()
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
            hi_w = NoWheelComboBox()
            hi_w.addItems(["全部", "仅角色", "仅空地"])
            lo_w = NoWheelComboBox()
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

    def _center_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _set_edit_enabled(self, en):
        self._edit_dock_body.setEnabled(en)

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
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
        self.status_label.setText("加载中…")
        QApplication.processEvents()
        if self.tkt_path: self.tkt = load_tkt(self.tkt_path)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()
        tks_dir = os.path.dirname(self.kon_path)
        try:
            self._resolver = KonNameResolver(tks_dir)
        except Exception:
            self._resolver = None
        try:
            self.records = load_kon(self.kon_path)
            self._dirty = False
            self._original_records = [[rec[fn] for fn, _, _, _ in KON_FIELDS] for rec in self.records]
            nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
            self.status_label.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _update_paths(self):
        update_path_labels([
            (self.lbl_kon, self.kon_path, "TKKon.dat"),
            (self.lbl_tkt, self.tkt_path, "TKT.dat"),
        ], self.is_dark_theme)

    # ----------- 筛选/表格 -----------

    def _apply_filter(self):
        q = self.search_input.text().strip().lower()
        show_empty = self.chk_show_empty.isChecked()
        self.compact_names = self.chk_compact.isChecked()
        self.filtered_indices = []
        for rec in self.records:
            if not show_empty:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
            if q:
                nm = kon_record_name(rec, self.tkt, self._resolver)
                search_text = f"{rec['index']} {rec['tkact_id']} {rec['exec_mode']} {nm} " \
                              f"{' '.join(str(rec[fn]) for fn,_,_,_ in KON_FIELDS)}".lower()
                if q not in search_text: continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        msg = f"显示 {len(self.filtered_indices)}/{KON_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_label.setText(msg)

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
                color = QColor("#CC3333")
            elif "未知" in nm:
                color = QColor("#CC8800")
            elif "空槽" in nm:
                color = QColor("#888888") if self.is_dark_theme else QColor("#AAAAAA")
            elif r['tkact_id'] == -1:
                color = QColor("#2266CC")
            elif has_data:
                color = QColor("#228B22") if self.is_dark_theme else QColor("#1a7a1a")
            else:
                color = QColor("#AAAAAA") if self.is_dark_theme else QColor("#999999")

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

    def _new_record(self):
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                rec['exec_mode'] = 0
                rec['target_param'] = 0
                rec['tkact_id'] = rec['index']
                rec['hp_damage'] = -1
                rec['exec_flags'] = 4
                self._dirty = True
                self._apply_filter()
                for row in range(self.table.rowCount()):
                    if int(self.table.item(row, 0).text()) == rec['index']:
                        self.table.selectRow(row)
                        break
                self._populate_edit(rec)
                self.status_label.setText(f"已创建新条目 → 槽位 #{rec['index']}")
                return
        QMessageBox.warning(self, "槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _copy_record(self):
        if self._editing_idx < 0: return
        src = self.records[self._editing_idx]
        if all(src[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            QMessageBox.information(self, "提示", "当前记录为空")
            return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                idx_bak = rec['index']
                for k, v in src.items():
                    if k != 'index': rec[k] = v
                rec['index'] = idx_bak
                self._dirty = True
                self._apply_filter()
                for row in range(self.table.rowCount()):
                    if int(self.table.item(row, 0).text()) == rec['index']:
                        self.table.selectRow(row)
                        break
                self._populate_edit(rec)
                self.status_label.setText(f"已复制 #{src['index']} → #{rec['index']}")
                return
        QMessageBox.warning(self, "槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _clear_current(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]
        if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            QMessageBox.information(self, "提示", "当前记录已经为空")
            return
        if QMessageBox.question(self, "确认清空", f"确定清空记录 #{rec['index']}?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = 0
        self._dirty = True
        self._apply_filter()
        self._populate_edit(rec)
        self.status_label.setText(f"已清空记录 #{rec['index']}")

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.kon_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        if QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.kon_path}\n\n原文件将被覆盖 (生成 .bak).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        try:
            with open(self.kon_path, 'rb') as s:
                with open(self.kon_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except:
            pass
        try:
            self.status_label.setText("正在保存…")
            QApplication.processEvents()
            save_kon(self.kon_path, self.records)
            self._dirty = False
            self.status_label.setText(f"已保存 → {self.kon_path}")
            QMessageBox.information(self, "保存成功", f"已保存\n备份: {self.kon_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

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

    def _show_field_ref(self):
        FieldRefDialog(self).exec()

    # 逆向参考: sub_43D53C, sub_43D8B0, sub_43E980, sub_4458B0, sub_4434BC, sub_4173F8
    def _show_help(self):
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            "功能: 编辑《三国群侠传》技能动画数据\n"
            "数据: 每条 20 个字段 × 16位整数\n\n"
            "特性:\n"
            "  · Godot 风格深/浅色主题切换\n"
            "  · 技能动画参数可视化编辑\n"
            "  · 伤害字段编码规则说明"
        )

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('kon_editor'))

# ============================================================
# 入口
# ============================================================

def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")
    app.setApplicationName("TKKon Editor")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))

    # 根据系统主题设置初始主题
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    if is_dark:
        ThemeManager.apply_dark_theme(app)
    else:
        ThemeManager.apply_light_theme(app)

    editor = KonEditor()
    editor.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
