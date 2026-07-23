#!/usr/bin/env python3
"""
TKSkill.dat 可视化编辑器 (PySide6 最终完美 Godot 风格版)
=============================================================
修复了布局对齐、去除了冗余线框，并 100% 还原了 Godot 4.6 滚动条及主题样式。
"""

import math
import os
import struct
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMenuBar, QMessageBox, QPushButton,
    QGraphicsScene, QGraphicsView, QScrollArea, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.jvg_loader import get_sprite_pixmap, load_mu_sprites
from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat
from editor_utils.mod_exporter import (
    ModExportPreviewDialog, ModImportPreviewDialog, ModMetadataDialog,
    build_data_diff_json, compute_crc32, diff_records, generate_mod_json,
    get_tksmod_info, import_tksmod_records, load_reference_dat_fields,
    pack_tksmod, safe_mod_filename,
)
from editor_utils.picker_dialogs import (
    STATUS_ICON_BASE, STATUS_NAMES, StatusPickerDialog, TktPickerDialog
)
from editor_utils.theme_manager import ThemeManager
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.ui_helpers import (
    confirm_close, make_fake_input, themed_messagebox,
    update_path_labels, NoWheelComboBox,
)
from editor_utils.version import format_title, format_about_header
from editor_utils.window_theme import apply_godot_theme

# ── 本地别名: 保持向后兼容 ──


def lzss_decompress(data):
    return lzss_decompress_dat(data)


def lzss_compress(data):
    return lzss_compress_dat(data)


def load_tkt(tkt_path):
    return load_tkt_simple(tkt_path)


def load_tkt_full(tkt_path):
    return load_tkt_simple(tkt_path, full_strip=True)

SKILL_REC = 94
SKILL_CNT = 350
SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_VALUES = [f"{k}-{v}" for k, v in sorted(SKILL_TYPES.items())]
ATK_TYPE_VALUES = ["-1-近战攻击", "0-物理攻击", "1-术法攻击", "10-召唤攻击"]

# STATUS_NAMES / STATUS_ICON_BASE 由 editor_utils.picker_dialogs 提供 (本地别名见下方导入)

SPECIAL_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻"), (1, "飙行", "移动范围扩大"),
    (2, "搜宝", "获得额外宝物"), (3, "解陷", "自动解除陷阱"),
]

BASIC_FIELDS = [
    ("skill_text_id", 0, "名称文本ID", 'tkt', "技能名称 TKT 文本ID"),
    ("skill_desc_id", 2, "说明文本ID", 'tkt', "技能说明 TKT 文本ID = skill_text_id + 400"),
    ("type", 4, "技能类型", 'type', "0=指令 1=主动 2=被动 3=移动"),
    ("jp_cost", 6, "技能点数", 'int', "学习技能所需点数 (JP)"),
]

TREE_FIELDS = []
for i in range(8):
    TREE_FIELDS.append(("ref_skill%d" % i, 8 + i*4, f"目标技能{i}", 'skill_pick', "受影响的目标技能索引"))
    TREE_FIELDS.append(("ref_type%d" % i, 10 + i*4, f"技能进度{i}", 'int', "累加进度权重(>=10可学), 20=归组"))

EFFECT_FIELDS = [
    ("timing", 40, "时序值Delay", 'int', "技能行动时序值"),
    ("hp_pct", 42, "生命加成%", 'int', "HP%加成"),
    ("heal_move", 44, "移步回血%", 'int', "自癒1=2 自癒2=3"),
    ("mp_pct", 46, "内力加成%", 'int', "MP%加成"),
    ("mp_move", 48, "移步回气%", 'int', "回气1=2 回气2=3"),
    ("atk_pct", 50, "攻击加成%", 'int', "攻击%加成"),
    ("def_pct", 52, "防御加成%", 'int', "防御%加成"),
    ("hit_pct", 54, "命中加成%", 'int', "命中%加成"),
    ("eva_pct", 56, "闪避加成%", 'int', "闪避%加成"),
    ("spd_pct", 58, "速度加成%", 'int', "速度%加成"),
    ("move_up", 60, "增加移动", 'int', "移动+1=2, 移动+2=3"),
    ("atk_count", 62, "增攻次数", 'int', "二連=2 三連=3"),
    ("special_flags",64,"特殊标志", 'flags', "飘浮/飙行等掩码"),
    ("mp_reduce", 66, "内息消耗减%", 'int', "施展指令技能内息减少%"),
]

IMMUNE_FIELDS = [
    ("immunity1", 68, "状态免疫 1-16", 'mask', "状态免疫位掩码 (状态 1-16)"),
    ("immunity2", 70, "状态免疫 17-32", 'mask', "状态免疫位掩码 (状态 17-32)"),
    ("exp_bonus", 72, "战后经验增加%", 'int', "战斗经验值增加% (鬼才)"),
    ("jp_bonus", 74, "战后技点增加%", 'int', "战斗技能点增加% (天才)"),
    ("magic_def", 76, "所受法伤减少%", 'int', "减少法术伤害% (抗魔)"),
    ("cost_gold", 78, "消耗金钱", 'int', "技能消耗金钱"),
    ("cost_res2", 80, "耗费兽元", 'int', "召唤技能兽元消耗"),
]

ADVANCED_FIELDS = [
    ("cost_res3", 82, "耗费灵魂", 'int', "幻灵技能灵魂消耗"),
    ("turn_shift", 84, "调整时序", 'int', "敌人行动时序偏移"),
    ("mp_cost", 86, "耗费内力", 'int', "技能消耗内力值"),
    ("trigger_prob",88, "触发概率", 'int', "状态免疫等级/被动技能触发概率"),
    ("sub_count", 90, "子技能数量", 'int', "技能组头子技能数 (-1=独立)"),
    ("atk_type", 92, "攻击类型", 'atk_type', "攻击伤害类别 (-1近战 0物理 1术法 10召唤)"),
]

ALL_FIELDS = (BASIC_FIELDS + EFFECT_FIELDS + IMMUNE_FIELDS + list(ADVANCED_FIELDS) + TREE_FIELDS)

TYPE_HINT_LABELS = {
    1: "主动技能: 百分比属性加成 → 角色战斗属性",
    2: "被动技能: 触发概率 → 角色反应系统",
    3: "移动技能: 特殊标志 + 移动能力 → 角色地图能力",
    0: "指令技能: 技能组根节点, 含子技能列表",
}

def skill_name(rec, tkt):
    sid = rec.get('skill_text_id', 0)
    if sid and sid in tkt: return tkt[sid].split('\n')[0].strip()
    if sid and -sid in tkt: return tkt[-sid].split('\n')[0].strip()
    return f"Skill#{sid}" if sid else f"(空-#{rec['index']})"

def load_skills(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % SKILL_REC == 0 and (len(dec) == 0 or len(dec) % SKILL_REC != 0):
        dec = raw
    recs = []
    for i in range(SKILL_CNT):
        off = i * SKILL_REC
        if off + SKILL_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h' * 47, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_skills(fp, recs):
    buf = bytearray(SKILL_CNT * SKILL_REC)
    for rec in recs[:SKILL_CNT]:
        i = rec['index']
        off = i * SKILL_REC
        for k, fo, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True

# ============================================================
# 弹窗选择器 (技能)
# ============================================================

class SkillPickerDialog(QDialog):
    def __init__(self, parent, records, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(600, 550)
        self.selected_index = None
        self.records = records
        self.tkt_dict = tkt_dict

        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        search_layout.addWidget(self.search_box)
        search_layout.addWidget(QLabel("类型:"))
        self.type_box = NoWheelComboBox()
        self.type_box.addItems(["全部"] + SKILL_TYPE_VALUES)
        self.type_box.currentIndexChanged.connect(self._refresh)
        search_layout.addWidget(self.type_box)
        layout.addLayout(search_layout)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称'])
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("清空选择")
        btn_clear.clicked.connect(self._clear_selection)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._accept_selection)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        self._refresh()

    def _refresh(self):
        query = self.search_box.text().strip().lower()
        ft = self.type_box.currentText()
        self.table.setRowCount(0)
        row = 0
        for r in self.records:
            if r['skill_text_id'] == 0: continue
            idx = r['index']
            sid = r['skill_text_id']
            st = r['type']
            sn = skill_name(r, self.tkt_dict)
            if query and query not in f"{idx} {sid} {sn}".lower(): continue
            if ft != "全部":
                try:
                    ft_val = int(ft.split('-')[0])
                except:
                    ft_val = None
                if st != ft_val: continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(str(sid)))
            self.table.setItem(row, 2, QTableWidgetItem(SKILL_TYPES.get(st, str(st))))
            self.table.setItem(row, 3, QTableWidgetItem(sn))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

    def _clear_selection(self):
        self.selected_index = 0
        self.accept()

# ============================================================
# 技能链拓扑图查看器
# ============================================================

class SkillGraphView(QGraphicsView):
    """可缩放 / 拖拽平移的技能拓扑图视图 (滚轮缩放, 双击节点回调)。"""

    def __init__(self, on_node_double_clicked=None):
        super().__init__()
        self._on_dbl = on_node_double_clicked
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

    def _node_idx_at(self, view_pos):
        item = self.itemAt(view_pos)
        while item is not None:
            data = item.data(0)
            if data is not None:
                return int(data)
            item = item.parentItem()
        return None

    def mouseDoubleClickEvent(self, event):
        idx = self._node_idx_at(event.position().toPoint())
        if idx is not None and self._on_dbl:
            self._on_dbl(idx)
            return
        super().mouseDoubleClickEvent(event)


class SkillTreeDialog(QDialog):
    """技能链拓扑图 — 只展示与选中技能直接相关的技能链 (向上全部前置 + 向下全部解锁),
    以节点-连线拓扑图呈现, 而非整张关系网。

    技能树引用表语义 (逆向 sub_41E248):
      源技能.ref_skill[i] = 目标技能索引; 源技能.ref_type[i] = 学会该源技能后累加给目标的进度权重。
      目标累计进度 ≥10 即可学习; 权重 10 = 自足解锁; 20 = 归组标记。
      因此 A→B 表示 A 是 B 的前置, B 是学会 A 后可解锁的技能; 箭头由前置指向解锁。
    """

    NODE_W = 168
    NODE_H = 50
    HGAP = 44
    VGAP = 104

    def __init__(self, parent, records, tkt_dict, focus_idx, is_dark=True):
        super().__init__(parent)
        self.records = records
        self.tkt_dict = tkt_dict
        self.focus_idx = focus_idx
        self.is_dark = is_dark
        self._fitted = False
        self._mode = 'all'  # all=前置+解锁 · down=仅向下(解锁链) · up=仅向上(前置链)
        self._show_group = True  # 是否显示归组(ref_type==20)关系

        self.resize(920, 720)
        self._build_graph()
        self._build_ui()
        self._render_graph()

    # ── 引用关系图构建 ──
    def _build_graph(self):
        """遍历全部技能, 构建父/子关系图与目标累计进度权重。"""
        self.children = {}   # a -> [(b, weight, pair)]  学会 a 后为 b 贡献 weight 进度
        self.parents = {}    # b -> [(a, weight, pair)]  b 由 a 贡献 weight 进度
        self.total_in = {}   # b -> 累计进度权重合计
        n = len(self.records)
        for rec in self.records:
            if rec.get('skill_text_id', 0) == 0:
                continue
            a = rec['index']
            for i in range(8):
                b = rec.get('ref_skill%d' % i, 0)
                w = rec.get('ref_type%d' % i, 0)
                if w == 0 or b <= 0 or b >= n or b == a:
                    continue
                if self.records[b].get('skill_text_id', 0) == 0:
                    continue
                self.children.setdefault(a, []).append((b, w, i))
                self.parents.setdefault(b, []).append((a, w, i))
                self.total_in[b] = self.total_in.get(b, 0) + w

    # ── 关联范围: 仅当前技能自身的技能链 (向上全部前置 + 向下全部解锁) ──
    def _reach(self, start, adj):
        """从 start 出发, 沿单方向 (parents 或 children) 传递闭包可达集 (不含 start)。"""
        seen = set()
        stack = [start]
        while stack:
            n = stack.pop()
            for (m, w, _i) in adj.get(n, []):
                if not self._show_group and w == 20:
                    continue
                if m != start and m not in seen:
                    seen.add(m)
                    stack.append(m)
        return seen

    def _related_nodes(self):
        # 按显示范围过滤: 仅向下只保留解锁链, 仅向上只保留前置链
        anc = set() if self._mode == 'down' else self._reach(self.focus_idx, self.parents)
        desc = set() if self._mode == 'up' else self._reach(self.focus_idx, self.children)
        nodes = anc | desc | {self.focus_idx}
        return nodes, anc, desc

    def _sub_edges(self, nodes):
        """仅保留两端均在链内的引用边 (a → b, w=进度权重)。"""
        edges = []
        for a in nodes:
            for (b, w, _i) in self.children.get(a, []):
                if not self._show_group and w == 20:
                    continue
                if b in nodes:
                    edges.append((a, b, w))
        return edges

    def _compute_ranks(self, nodes, edges):
        """按最长路径分层: 无前置节点 rank=0, 越靠下游 rank 越大 (环用访问栈兑底)。"""
        pin = {n: [] for n in nodes}
        for (a, b, _w) in edges:
            pin[b].append(a)
        rank = {}
        visiting = set()

        def rk(n):
            if n in rank:
                return rank[n]
            if n in visiting:
                return 0
            visiting.add(n)
            r = 0
            for a in pin[n]:
                r = max(r, rk(a) + 1)
            visiting.discard(n)
            rank[n] = r
            return r

        for n in nodes:
            rk(n)
        return rank

    def _layout(self, nodes, rank):
        rows = {}
        for n in nodes:
            rows.setdefault(rank[n], []).append(n)
        pos = {}
        for r, ns in rows.items():
            ns.sort()
            total_w = len(ns) * self.NODE_W + (len(ns) - 1) * self.HGAP
            x0 = -total_w / 2.0
            for i, n in enumerate(ns):
                pos[n] = (x0 + i * (self.NODE_W + self.HGAP), r * (self.NODE_H + self.VGAP))
        return pos

    # ── 界面 ──
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.lbl_head = QLabel("")
        self.lbl_head.setProperty("class", "RecordHeader")
        self.lbl_head.setWordWrap(True)
        layout.addWidget(self.lbl_head)

        legend = QLabel(
            "箭头方向 = 前置 → 解锁; 连线标签为累加进度权重 (+N), 目标累计 ≥10 或标注 [自足] 即可学习, "
            "[归组] 为技能组标记 (紫色虚线)。滚轮缩放 · 拖拽平移 · 双击节点重新聚焦。")
        legend.setWordWrap(True)
        legend.setProperty("class", "PropLabel")
        layout.addWidget(legend)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("显示范围:"))
        self.mode_box = NoWheelComboBox()
        self.mode_box.addItems(["全部关联 (前置 + 解锁)", "仅向下 (解锁链)", "仅向上 (前置链)"])
        self.mode_box.setCurrentIndex({'all': 0, 'down': 1, 'up': 2}[self._mode])
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_box)
        mode_row.addSpacing(16)
        self.chk_group = QCheckBox("显示归组")
        self.chk_group.setChecked(self._show_group)
        self.chk_group.toggled.connect(self._on_group_toggled)
        mode_row.addWidget(self.chk_group)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.scene = QGraphicsScene(self)
        self.view = SkillGraphView(self._on_node_double_clicked)
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(
            QBrush(QColor("#161a22") if self.is_dark else QColor("#f7f8fa")))
        layout.addWidget(self.view, 1)

        btn_row = QHBoxLayout()
        for label, slot in (
            ("适应窗口", self._fit),
            ("放大", lambda: self.view.scale(1.2, 1.2)),
            ("缩小", lambda: self.view.scale(1 / 1.2, 1 / 1.2)),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _type_color(self, tv):
        if self.is_dark:
            return QColor({0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db"}.get(tv, "#dcdcdc"))
        return QColor({0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8"}.get(tv, "#222222"))

    def _node_tooltip(self, idx):
        rec = self.records[idx]
        name = skill_name(rec, self.tkt_dict)
        lines = [f"{name}  #{idx}  [{SKILL_TYPES.get(rec.get('type', 0), '')}]"]
        plist = self.parents.get(idx, [])
        if plist:
            lines.append("前置 (往上):")
            for (a, w, _i) in plist:
                lines.append(f"  · {skill_name(self.records[a], self.tkt_dict)} #{a} → {w:+d}")
            lines.append(f"  前置合计 {self.total_in.get(idx, 0)} (≥10 可学习)")
        clist = self.children.get(idx, [])
        if clist:
            lines.append("解锁 (往下):")
            for (b, w, _i) in clist:
                lines.append(f"  · {skill_name(self.records[b], self.tkt_dict)} #{b} → {w:+d}")
        return "\n".join(lines)

    # ── 绘制 ──
    def _draw_edge(self, a_xy, b_xy, w):
        ax, ay = a_xy
        bx, by = b_xy
        p1 = QPointF(ax + self.NODE_W / 2, ay + self.NODE_H)  # 前置底部中点
        p2 = QPointF(bx + self.NODE_W / 2, by)                # 解锁顶部中点
        is_group = (w == 20)
        if is_group:
            color = QColor("#c58af0") if self.is_dark else QColor("#8e44ad")  # 归组: 紫色
        else:
            color = QColor("#7f8aa3") if self.is_dark else QColor("#8894a8")
        pen = QPen(color, 1.8 if is_group else 1.6)
        if is_group:
            pen.setStyle(Qt.DashLine)
        path = QPainterPath(p1)
        path.lineTo(p2)
        edge = self.scene.addPath(path, pen)
        edge.setZValue(1)
        self._draw_arrow(p1, p2, color)
        self._draw_edge_label((p1 + p2) / 2.0, w)

    def _draw_arrow(self, p1, p2, color):
        ang = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        size = 10
        left = QPointF(p2.x() - size * math.cos(ang - math.pi / 7),
                       p2.y() - size * math.sin(ang - math.pi / 7))
        right = QPointF(p2.x() - size * math.cos(ang + math.pi / 7),
                        p2.y() - size * math.sin(ang + math.pi / 7))
        arrow = self.scene.addPolygon(QPolygonF([p2, left, right]), QPen(color, 1), QBrush(color))
        arrow.setZValue(2)

    def _draw_edge_label(self, mid, w):
        if w == 20:
            txt = "归组"
        elif w >= 10:
            txt = "自足"
        else:
            txt = f"+{w}"
        label = self.scene.addSimpleText(txt)
        f = label.font()
        f.setPointSize(8)
        label.setFont(f)
        label.setBrush(QBrush(QColor("#e0b060") if self.is_dark else QColor("#8a5a00")))
        br = label.boundingRect()
        chip = self.scene.addRect(
            0, 0, br.width() + 8, br.height() + 2,
            QPen(Qt.NoPen),
            QBrush(QColor("#202531") if self.is_dark else QColor("#e8ecf1")))
        chip.setPos(mid.x() - br.width() / 2 - 4, mid.y() - br.height() / 2 - 1)
        chip.setZValue(3)
        label.setPos(mid.x() - br.width() / 2, mid.y() - br.height() / 2)
        label.setZValue(4)

    def _draw_node(self, idx, xy):
        x, y = xy
        rec = self.records[idx]
        tv = rec.get('type', 0)
        name = skill_name(rec, self.tkt_dict)
        tcol = self._type_color(tv)
        is_focus = (idx == self.focus_idx)

        if is_focus:
            fill = QColor("#3a3320") if self.is_dark else QColor("#fff6d6")
            border = QColor("#ffcc66") if self.is_dark else QColor("#a15c00")
            pen_w = 3
        else:
            fill = QColor("#252a36") if self.is_dark else QColor("#ffffff")
            border = tcol
            pen_w = 2

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.NODE_W, self.NODE_H), 9, 9)
        node = self.scene.addPath(path, QPen(border, pen_w), QBrush(fill))
        node.setPos(x, y)
        node.setZValue(5)
        node.setData(0, idx)
        node.setToolTip(self._node_tooltip(idx))

        name_t = self.scene.addSimpleText(name)
        nf = name_t.font()
        nf.setPointSize(11)
        nf.setBold(True)
        name_t.setFont(nf)
        name_t.setBrush(QBrush(tcol))
        nb = name_t.boundingRect()
        name_t.setPos(x + (self.NODE_W - nb.width()) / 2, y + 6)
        name_t.setZValue(6)
        name_t.setData(0, idx)

        sub_t = self.scene.addSimpleText(f"#{idx} · {SKILL_TYPES.get(tv, tv)}")
        sf = sub_t.font()
        sf.setPointSize(8)
        sub_t.setFont(sf)
        sub_t.setBrush(QBrush(QColor("#9aa4b8") if self.is_dark else QColor("#5a6472")))
        sbb = sub_t.boundingRect()
        sub_t.setPos(x + (self.NODE_W - sbb.width()) / 2, y + 28)
        sub_t.setZValue(6)
        sub_t.setData(0, idx)

    def _render_graph(self):
        self.scene.clear()
        nodes, anc, desc = self._related_nodes()
        edges = self._sub_edges(nodes)
        rank = self._compute_ranks(nodes, edges)
        pos = self._layout(nodes, rank)

        fname = skill_name(self.records[self.focus_idx], self.tkt_dict)
        mode_label = {'all': '全部关联', 'down': '仅向下·解锁链', 'up': '仅向上·前置链'}[self._mode]
        self.setWindowTitle(f"技能链拓扑图 — {fname} (#{self.focus_idx}) · {mode_label}")
        if len(nodes) <= 1:
            empty_hint = {'all': "无前置技能, 也不解锁其它技能",
                          'down': "不解锁任何下游技能",
                          'up': "无前置技能"}[self._mode]
            self.lbl_head.setText(f"「{fname}」#{self.focus_idx}  [{mode_label}] — {empty_hint}。")
        else:
            parts = []
            if self._mode != 'down':
                parts.append(f"前置(往上) {len(anc)} 个")
            if self._mode != 'up':
                parts.append(f"解锁(往下) {len(desc)} 个")
            self.lbl_head.setText(
                f"以「{fname}」#{self.focus_idx} 为中心  [{mode_label}] · "
                + " · ".join(parts) + f" · 共 {len(nodes)} 个节点")

        for (a, b, w) in edges:
            self._draw_edge(pos[a], pos[b], w)
        for n in nodes:
            self._draw_node(n, pos[n])

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))
        if self._fitted:
            self._fit()

    def _fit(self):
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if not rect.isEmpty():
            self.view.fitInView(rect, Qt.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self._fit()

    def _on_node_double_clicked(self, idx):
        if idx != self.focus_idx and 0 <= idx < len(self.records):
            self.focus_idx = idx
            self._render_graph()

    def _on_mode_changed(self, index):
        self._mode = {0: 'all', 1: 'down', 2: 'up'}.get(index, 'all')
        self._render_graph()
        self._fit()

    def _on_group_toggled(self, checked):
        self._show_group = checked
        self._render_graph()
        self._fit()

# ============================================================
# GUI 核心编辑器
# ============================================================

class SkillEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(format_title("skill_editor"))
        self.resize(1260, 820)
        self.setMinimumSize(1000, 650)

        # 补全：精准加载原版要求的图标文件 TKS.ico
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        apply_godot_theme(self, self._is_dark)

        self.skill_path = self.tkt_path = None
        self.records = []
        self.tkt = {}
        self.tkt_full = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None

        self.mu_path = None
        self._mu_sprites = []
        self._icon_pixmaps = {}

        self.widget_map = {}
        self.extra_map = {}

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("新建技能", QKeySequence("Ctrl+N"), self._new_skill)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)

        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("关于编辑器", self._show_about)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)

        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar.addWidget(btn_search)

        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar.addWidget(btn_clear)

        toolbar.addSpacing(15)
        toolbar.addWidget(QLabel("类型:"))
        self.type_filter = NoWheelComboBox()
        self.type_filter.addItems(["全部类型"] + SKILL_TYPE_VALUES)
        self.type_filter.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_filter)

        toolbar.addSpacing(15)
        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)

        toolbar.addStretch()

        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)

        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # --- Main Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # --- Left Pane (Table) ---
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称', '技能点数', '耗费内力'])
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(4, 70)
        self.table.setColumnWidth(5, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.splitter.addWidget(self._create_dock("技能列表", self.table))

        # --- Right Pane (Inspector) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)

        # 顶部行：记录标签 + 操作按钮
        header_row = QHBoxLayout()
        self.lbl_rec_idx = QLabel("未选中")
        self.lbl_rec_idx.setProperty("class", "RecordHeader")
        header_row.addWidget(self.lbl_rec_idx)
        header_row.addStretch()
        btn_apply = QPushButton("✅ 应用")
        btn_apply.clicked.connect(self._apply_edit)
        btn_reset = QPushButton("🔄 重置")
        btn_reset.clicked.connect(self._reset_edit)
        header_row.addWidget(btn_apply)
        header_row.addWidget(btn_reset)
        right_layout.addLayout(header_row)

        # Scroll Area for properties (Godot Style Layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.edit_inner = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_inner)
        self.edit_layout.setContentsMargins(4, 4, 16, 4)

        # =======================================================
        # Preview Panel (Godot 资源检查器头部风格)
        # =======================================================
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(8, 12, 8, 12)
        pl.setSpacing(6)

        # 1. 技能名称 (大标题)
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        pl.addWidget(self.preview_name)

        # 2. 技能元数据 (类型、点数、内力)
        self.preview_type = QLabel("")
        self.preview_type.setProperty("class", "PreviewMeta")
        self.preview_type.setWordWrap(True)
        pl.addWidget(self.preview_type)

        # 3. 技能描述 (替换掉丑陋的 QTextEdit，改用自动撑高的 QLabel)
        self.preview_desc = QLabel("请在左侧列表中选择一项技能。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextInteractionFlags(Qt.TextSelectableByMouse) # 允许鼠标选中文本复制
        pl.addWidget(self.preview_desc)

        # 4. 子技能高亮提示
        self.preview_sub = QLabel("")
        self.preview_sub.setProperty("class", "PreviewSubMeta")
        self.preview_sub.setWordWrap(True)
        pl.addWidget(self.preview_sub)

        self.edit_layout.addWidget(preview_frame)

        # Properties (No wireframes, Godot inspector grid alignment)
        self._build_field_group("基础属性", BASIC_FIELDS, 4)
        self._build_field_group("效果加成 (主动技能核心)", EFFECT_FIELDS, 4)
        self._build_field_group("状态免疫", IMMUNE_FIELDS, 4)
        self._build_field_group("高级属性", ADVANCED_FIELDS, 4)
        self._build_field_group("技能树引用表 (8组: 目标/进度)", TREE_FIELDS, 4)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)

        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setSizes([440, 820])

        # Bottom Path
        path_layout = QHBoxLayout()
        self.lbl_skill_path = QLabel("TKSkill.dat: 未加载")
        self.lbl_tkt_path = QLabel("TKT.dat: 未加载")
        self.lbl_mu_path = QLabel("Mu.JVG: 未加载")
        path_layout.addWidget(self.lbl_skill_path)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt_path)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_mu_path)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_field_group(self, title, fields, cols):
        """字段分组：标签在上、输入框在下 (对齐 warpc_editor_v2 布局)"""
        group_widget = QWidget()
        v_layout = QVBoxLayout(group_widget)
        v_layout.setContentsMargins(0, 4, 0, 4)
        v_layout.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "InspectorTitle")
        v_layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(15)
        grid.setContentsMargins(10, 0, 0, 0)

        for fi, (fn, fo, fl, ft, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, fn, fo, fl, ft, cmt)

        for c in range(cols):
            grid.setColumnStretch(c, 1)
        v_layout.addLayout(grid)
        self.edit_layout.addWidget(group_widget)

    def _build_field(self, grid, row, col, fn, fo, fl, ft, cmt):
        """单字段控件：标签在上、输入框在下"""
        cell = QVBoxLayout()
        cell.setSpacing(2)

        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        if ft == 'tkt' or ft == 'skill_pick':
            box = QFrame()
            box.setObjectName("FakeInputBox")
            container = QHBoxLayout(box)
            container.setSpacing(0)
            container.setContentsMargins(0, 0, 0, 0)

            inp = QLineEdit()
            inp.setMaximumWidth(50)
            btn = QPushButton("...")
            btn.setFixedWidth(28)
            btn.setCursor(Qt.PointingHandCursor)

            container.addWidget(inp)
            container.addStretch()
            container.addWidget(btn)
            cell.addWidget(box)

            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)

            self.widget_map[fn] = inp
            self.extra_map[fn] = extra
            if ft == 'tkt': btn.clicked.connect(lambda _, f=fn: self._pick_tkt(f))
            else: btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))

        elif ft == 'type' or ft == 'atk_type':
            cb = NoWheelComboBox()
            if ft == 'type': cb.addItems(SKILL_TYPE_VALUES)
            else: cb.addItems(ATK_TYPE_VALUES)
            cell.addWidget(make_fake_input(combo=cb))
            self.widget_map[fn] = cb

        elif ft == 'mask' or ft == 'flags':
            inp = QLineEdit()
            inp.setVisible(False)

            btn = QPushButton("配置免疫状态…" if ft == 'mask' else "配置特殊标志…")
            btn.setCursor(Qt.PointingHandCursor)

            box = QFrame()
            box.setObjectName("FakeInputBox")
            container = QHBoxLayout(box)
            container.setSpacing(0)
            container.setContentsMargins(0, 0, 0, 0)
            container.addWidget(btn, 1)
            cell.addWidget(box)

            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)

            self.widget_map[fn] = inp
            self.extra_map[fn] = extra
            if ft == 'mask':
                btn.clicked.connect(lambda _, f=fn: self._pick_status(f))
            else:
                btn.clicked.connect(lambda _, f=fn: self._pick_flags(f))
        else:
            inp = QLineEdit()
            cell.addWidget(make_fake_input(line_edit=inp))
            self.widget_map[fn] = inp

        grid.addLayout(cell, row, col, Qt.AlignTop)

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        apply_godot_theme(self, self._is_dark)

    def _apply_theme(self):
        qss = ThemeManager.dark_qss() if self._is_dark else ThemeManager.light_qss()
        self.setStyleSheet(qss)
        self._update_paths()

    def _update_paths(self):
        update_path_labels([
            (self.lbl_skill_path, self.skill_path, "TKSkill.dat"),
            (self.lbl_tkt_path, self.tkt_path, "TKT.dat"),
            (self.lbl_mu_path, self.mu_path, "Mu.JVG"),
        ], self._is_dark)

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        sk = os.path.join(d, "TKSkill.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(sk):
            QMessageBox.warning(self, "文件缺失", "未找到 TKSkill.dat")
            return
        self.skill_path = sk
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        self._reload()

    def _reload(self):
        if not self.skill_path: return
        self.status_var.setText("加载中…")
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()
        try:
            self.records = load_skills(self.skill_path)
            self._dirty = False
            # MOD 导出使用原始字节序 (word index = byte_offset // 2)，与启动器 _apply_fields_to_record 一致
            self._original_records = []
            for rec in self.records:
                row = [0] * (SKILL_REC // 2)
                for k, fo, _, _, _ in ALL_FIELDS:
                    row[fo // 2] = rec[k]
                self._original_records.append(row)
            nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
            self.status_var.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    def _set_edit_enabled(self, en):
        self.edit_inner.setEnabled(en)

    def _apply_filter(self):
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        ftype = self.type_filter.currentText()
        for rec in self.records:
            if rec['skill_text_id'] == 0: continue
            if ftype and not ftype.startswith("全部"):
                if rec['type'] != int(ftype.split('-')[0]): continue
            if q:
                nm = skill_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['skill_text_id']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _clear_filter(self):
        self.search_entry.clear()
        self.type_filter.setCurrentIndex(0)
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            stype = SKILL_TYPES.get(r['type'], f"#{r['type']}")
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 1, QTableWidgetItem(str(r['skill_text_id'])))
            self.table.setItem(row, 2, QTableWidgetItem(stype))
            self.table.setItem(row, 3, QTableWidgetItem(skill_name(r, self.tkt)))
            self.table.setItem(row, 4, QTableWidgetItem(str(r['jp_cost'])))
            self.table.setItem(row, 5, QTableWidgetItem(str(r['mp_cost'])))

            # ==== 核心改造：为所有 4 种技能类型分配高辨识度专属颜色 ====
            if self._is_dark:
                # 深色模式高亮配色
                if r['type'] == 0:   color = QColor("#478cbf") # 指令: 引擎蓝
                elif r['type'] == 1: color = QColor("#e27d60") # 主动: 珊瑚橙 (极高辨识度)
                elif r['type'] == 2: color = QColor("#55b572") # 被动: 翠绿
                elif r['type'] == 3: color = QColor("#b988db") # 移动: 柔和紫
                else:                color = QColor("#dcdcdc") # 未知: 默认白灰
            else:
                # 浅色模式需要更深的颜色才能在白底上压住视觉
                if r['type'] == 0:   color = QColor("#28638f") # 深蓝
                elif r['type'] == 1: color = QColor("#bd5739") # 深橙红
                elif r['type'] == 2: color = QColor("#2d8046") # 深绿
                elif r['type'] == 3: color = QColor("#8a5bb8") # 深紫
                else:                color = QColor("#222222") # 未知: 默认黑

            for c in range(6):
                self.table.item(row, c).setForeground(color)

        self.table.blockSignals(False)

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._populate_edit(self.records[idx])

    def _show_table_context_menu(self, pos):
        """技能列表右键菜单: 任意技能均可查看其完整技能树。"""
        item = self.table.itemAt(pos)
        if item is None:
            return
        idx_item = self.table.item(item.row(), 0)
        if idx_item is None:
            return
        try:
            idx = int(idx_item.text())
        except ValueError:
            return
        menu = QMenu(self)
        act_tree = menu.addAction("🌳 查看技能树")
        act_tree.triggered.connect(lambda: self._show_skill_tree(idx))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_skill_tree(self, idx):
        """弹出技能树窗口: 以该技能为中心双向关联展开。"""
        if not self.records or idx < 0 or idx >= len(self.records):
            return
        dlg = SkillTreeDialog(self, self.records, self.tkt, idx, self._is_dark)
        dlg.exec()

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        stype = SKILL_TYPES.get(rec['type'], f"#{rec['type']}")
        self.lbl_rec_idx.setText(f"技能 #{rec['index']}  文本ID={rec['skill_text_id']}  类型={stype}")

        nid = rec.get('skill_text_id', 0)
        n_txt = self.tkt.get(nid, "") if nid > 0 else ""
        # 加上前缀增加仪式感，空名称处理也更加优雅
        self.preview_name.setText(n_txt.split('\n')[0].strip() if n_txt else "未命名技能")

        did = nid + 400
        d_txt = self.tkt_full.get(did, "") if did > 0 else ""
        # 改用 setText，因为组件已经换成了 QLabel
        self.preview_desc.setText(d_txt if d_txt else "暂无关于该技能的详细描述。")

        hint = TYPE_HINT_LABELS.get(rec['type'], "")

        # ==== 检查器预览区类型同步高亮 ====
        if self._is_dark:
            type_color = {0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db"}.get(rec['type'], "#dcdcdc")
        else:
            type_color = {0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8"}.get(rec['type'], "#222222")

        # 使用 HTML 富文本进行局部着色，完美保留 QSS 的边框与排版
        self.preview_type.setText(
            f'<span style="color: {type_color}; font-weight: bold;">【{stype}】</span> '
            f'| 点数={rec["jp_cost"]} | 内力={rec["mp_cost"]} | {hint}'
        )
        sc = rec.get('sub_count', -1)
        self.preview_sub.setText(f"子技能: {sc} 个 (ID {rec['index']+1} - {rec['index']+sc})" if sc >= 0 else "")

        for fn, fo, fl, ft, _ in ALL_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if not w: continue

            if ft == 'type' or ft == 'atk_type':
                for i in range(w.count()):
                    if w.itemText(i).startswith(f"{val}-"):
                        w.setCurrentIndex(i)
                        break
            else:
                w.setText(str(val))

            if ft == 'tkt':
                nid = int(val) if val else 0
                txt = self.tkt.get(nid, "") if nid > 0 else ""
                t = txt.split('\n')[0] if txt else ""
                self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            elif ft == 'mask':
                self._update_mask_label(fn, int(val) if val else 0)
            elif ft == 'flags':
                self._update_flags_label(fn, int(val) if val else 0)
            elif ft == 'skill_pick':
                sidx = int(val) if val else 0
                if 0 < sidx < len(self.records) and self.records[sidx]['skill_text_id'] != 0:
                    nm = skill_name(self.records[sidx], self.tkt)
                    self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)
                else:
                    self.extra_map[fn].setText("")

    def _update_mask_label(self, fn, mask):
        base = 0 if fn == 'immunity1' else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_flags_label(self, fn, val):
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in SPECIAL_FLAG_BITS if mask & (1 << bit)]
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_tkt(self, fn):
        if not self.tkt: return
        dlg = TktPickerDialog(self, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            self.widget_map[fn].setText(str(dlg.selected_id))
            txt = self.tkt.get(dlg.selected_id, "")
            t = txt.split('\n')[0] if txt else ""
            self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            if fn == 'skill_text_id': self.preview_name.setText(txt.split('\n')[0].strip() if txt else "(无)")

    def _pick_skill(self, fn):
        if not self.records: return
        dlg = SkillPickerDialog(self, self.records, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = skill_name(self.records[dlg.selected_index], self.tkt) if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)

    def _pick_status(self, fn):
        base = 0 if fn == 'immunity1' else 16
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = StatusPickerDialog(self, "选择免疫状态 (位掩码)", STATUS_NAMES,
                                 cur, base, self._get_icon_pixmap, False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_mask_label(fn, dlg.selected_mask & 0xFFFF)

    def _pick_flags(self, fn):
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = QDialog(self)
        dlg.setWindowTitle("选择特殊标志")
        dlg.resize(300, 200)
        layout = QVBoxLayout(dlg)
        checkboxes = []
        for bit, name, desc in SPECIAL_FLAG_BITS:
            cb = QCheckBox(f"{name} ({desc})")
            cb.setChecked(bool(cur & (1 << bit)))
            checkboxes.append((bit, cb))
            layout.addWidget(cb)

        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("全清")
        btn_clear.clicked.connect(lambda: [cb.setChecked(False) for _, cb in checkboxes])
        btn_ok = QPushButton("确定")
        def _ok():
            m = 0
            for bit, cb in checkboxes:
                if cb.isChecked(): m |= (1 << bit)
            if m >= 0x8000: m -= 0x10000
            self.widget_map[fn].setText(str(m))
            self._update_flags_label(fn, m)
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _apply_edit(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, _ in ALL_FIELDS:
            w = self.widget_map.get(fn)
            if not w: continue
            try:
                if ft == 'type' or ft == 'atk_type':
                    v = int(w.currentText().split('-')[0])
                else:
                    v = int(w.text() or 0)
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                rec[fn] = v
            except ValueError:
                rec[fn] = 0

        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == rec['index']:
                self.table.selectRow(r)
                break
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存)")

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _new_skill(self):
        if not self.records: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                rec['skill_text_id'] = rec['index'] + 1
                rec['type'] = 1
                rec['jp_cost'] = 1
                rec['sub_count'] = -1
                rec['atk_type'] = -1
                self._dirty = True
                self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r)
                        break
                self._populate_edit(rec)
                self.status_var.setText(f"已创建新技能 → 槽位 #{rec['index']}")
                return
        QMessageBox.warning(self, "槽位已满", f"所有 {SKILL_CNT} 个槽位均已占用")

    def _copy_record(self):
        if self._editing_idx is None: return
        src = self.records[self._editing_idx]
        if src['skill_text_id'] == 0: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True
                self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r)
                        break
                self._populate_edit(rec)
                return

    def _clear_current(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        if rec['skill_text_id'] == 0: return
        reply = QMessageBox.question(self, "确认", f"确定清空记录 #{rec['index']}?")
        if reply == QMessageBox.Yes:
            for k, fo, _, _, _ in ALL_FIELDS:
                rec[k] = 0
            rec['sub_count'] = -1
            self._dirty = True
            self._apply_filter()
            self._populate_edit(rec)

    def _save(self):
        if not self.skill_path or not self.records: return
        reply = QMessageBox.question(self, "确认保存", f"将覆盖保存并生成.bak:\n{self.skill_path}")
        if reply == QMessageBox.Yes:
            try:
                with open(self.skill_path, 'rb') as s:
                    with open(self.skill_path + ".bak", 'wb') as d:
                        d.write(s.read())
            except: pass
            try:
                save_skills(self.skill_path, self.records)
                self._dirty = False
                QMessageBox.information(self, "成功", "保存成功！")
                self.status_var.setText(f"已保存 → {self.skill_path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        if not self.records or not self._original_records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 构建原始字节序字段数组 (word index = byte_offset // 2)，与启动器一致
        current_fields = []
        for rec in self.records:
            row = [0] * (SKILL_REC // 2)
            for k, fo, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)
        diff_result = diff_records(
            self._original_records, current_fields, field_count, len(self._original_records))

        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        crc = compute_crc32(self.skill_path) if self.skill_path else "0x00000000"
        data_json = build_data_diff_json(
            target="TKSkill.dat", record_size=SKILL_REC, field_type="int16",
            field_count=field_count, original_count=len(self._original_records),
            original_crc32=crc, diff_result=diff_result)

        components = [{"file": "data/TKSkill.dat.json", "target": "TKSkill.dat"}]
        mod_json = generate_mod_json(metadata, components)

        default_name = f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod"
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", default_name, "TKS MOD (*.tksmod)")
        if not fp: return

        try:
            pack_tksmod(fp, mod_json, {"data/TKSkill.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(self, "导出成功", f"已导出 MOD 文件:\n{fp}\n\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 预构建当前字段
        current_fields = []
        for rec in self.records:
            row = [0] * (SKILL_REC // 2)
            for k, fo, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)

        def _compute_stats(ref_dir):
            ref_records = load_reference_dat_fields(ref_dir, "TKSkill.dat",
                rec_size=SKILL_REC, field_count=field_count, field_fmt='h', use_lzss=True)
            if ref_records is None:
                return {"valid": False, "error": "目录中未找到 TKSkill.dat"}
            diff = diff_records(ref_records, current_fields, field_count, len(ref_records))
            targets = []
            if diff['modified'] or diff['appended']:
                targets.append({"name": "TKSkill.dat",
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": 0})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.skill_path) if self.skill_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_records = load_reference_dat_fields(ref_dir, "TKSkill.dat",
            rec_size=SKILL_REC, field_count=field_count, field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKSkill.dat")
            return
        diff_result = diff_records(ref_records, current_fields, field_count, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        crc = compute_crc32(os.path.join(ref_dir, "TKSkill.dat"))
        data_json = build_data_diff_json(target="TKSkill.dat", record_size=SKILL_REC, field_type="int16",
            field_count=field_count, original_count=len(ref_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKSkill.dat.json", "target": "TKSkill.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKSkill.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
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

        if "TKSkill.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 TKSkill.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.skill_path) if self.skill_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, records = import_tksmod_records(
            fp, ref_dir, "TKSkill.dat",
            rec_size=SKILL_REC, field_count=len(ALL_FIELDS),
            field_fmt='h', use_lzss=True
        )
        if records is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 TKSkill.dat")
            return

        new_records = []
        for i, fields in enumerate(records):
            rec = {'index': i}
            for k, fo, _, _, _ in ALL_FIELDS:
                word_idx = fo // 2
                rec[k] = fields[word_idx] if word_idx < len(fields) else 0
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
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(self.records)} 条技能")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 条记录。\n"
            f"您现在可以继续编辑并重新导出。")

    def _show_help(self):
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            "功能: 编辑《三国群侠传》技能数据\n"
            "数据: 350 条 × 94 字节 = 32,900 字节\n\n"
            "特性:\n"
            "  · Godot 4.6 级别布局与纯净控件约束\n"
            "  · 分页编辑: 基础/效果/免疫/进阶/技能树\n"
            "  · 自动关联 TKT.dat 显示技能名称")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('skill_editor'))

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()

def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    editor = SkillEditorApp()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()