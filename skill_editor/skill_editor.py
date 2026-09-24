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
    QBrush, QColor, QIntValidator, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog,
    QFileDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QMenuBar, QMessageBox,
    QPushButton, QGraphicsScene, QGraphicsView, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.dock_components import DockHeader
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.jvg_loader import get_sprite_pixmap, load_mu_sprites
from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat
from editor_utils.theme_manager import business_colors

# 播种徽标底色 — 深饱和色配白字保证对比, 深浅主题一致 (阶段 2 豁免: 主题无关领域色)
SEED_GROUP_COLOR = "#7a4fc0"   # 组头: 紫
SEED_ENTRY_COLOR = "#1f9d55"   # 入口: 绿
SEED_DOWN_COLOR = "#526073"    # 下游: 灰蓝
# 子技能溢出警示红 — 领域警示色 (阶段 2 豁免: 主题无关)
SUB_OVERFLOW_COLOR = "#e0533d"
from editor_utils.mod_exporter import (
    RecordModSpec, export_records_mod, import_records_mod,
)
from editor_utils.picker_dialogs import (
    STATUS_ICON_BASE, STATUS_NAMES, SkillPickerDialog, StatusPickerDialog,
    TktPickerDialog,
)
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.skill_extension import (
    GAME_SKILL_BASE,
    GAME_SKILL_CAPACITY,
)
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.ui_helpers import (
    backup_existing_file, make_fake_input, mark_invalid,
    form_edits_pending, themed_question, set_themed_icon,
    update_path_labels, EditorComboBox,
)
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput
from editor_utils.undo_stack import FieldUndoMixin

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
SKILL_ORIG_CNT = 350
SKILL_CNT = SKILL_ORIG_CNT  # backward-compatible name
SKILL_MAX_CNT = GAME_SKILL_BASE + GAME_SKILL_CAPACITY
SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_VALUES = [f"{k}-{v}" for k, v in sorted(SKILL_TYPES.items())]
ATK_TYPE_VALUES = {-1: "普攻式结算", 0: "非术法指令", 1: "术法指令", 10: "召唤分支"}

# 状态第16/32位语义未明，不能当作空槽丢弃；仅在本编辑器内补全名称。
RESISTANCE_STATUS_NAMES = [
    STATUS_NAMES[i] if i < len(STATUS_NAMES) and i not in (15, 31)
    else f"未知状态位 {i + 1}"
    for i in range(32)
]

SPECIAL_FLAG_BITS = [
    (0, "飘浮", "避开陷阱"), (1, "飙行", "额外移动机会"),
    (2, "搜宝", "检查沿途宝物"), (3, "解陷", "处理沿途陷阱"),
]

BASIC_FIELDS = [
    ("skill_text_id", 0, "名称文本ID", 'tkt', "技能名称 TKT 文本ID"),
    ("skill_desc_id", 2, "说明文本ID", 'tkt', "技能说明的独立 TKT 文本ID；原版直接读取此值，不由名称文本ID推算"),
    ("type", 4, "技能类型", 'type', "0=指令 1=主动（装备属性加成，非战斗菜单主动施放） 2=被动（由技能编号303..330等选择反应） 3=移动；新增类型2不会自动生成任意反应"),
    ("jp_cost", 6, "学习技能点", 'int', "学习技能点；实际消耗 = 学习技能点 * (250 - 角色当前悟性) / 200 (sub_41E248)"),
]

TREE_FIELDS = []
for i in range(8):
    TREE_FIELDS.append(("ref_skill%d" % i, 8 + i*4, f"目标技能{i}", 'skill_pick', "受影响的目标技能索引"))
    TREE_FIELDS.append(("ref_type%d" % i, 10 + i*4, f"进度权重{i}", 'int', "学会源技能后，仅向学习状态为1..9的目标累加权重低字节，累计>=10可学；权重20还将源技能学习状态设为30，不是所有引用都直接归组"))

EFFECT_FIELDS = [
    ("timing", 40, "行动时序值", 'int', "加入累计行动值，原版再按阈值和技能特判换算；不是毫秒延迟"),
    ("hp_pct", 42, "生命上限加成%", 'int', "生命上限百分比加成，不是当前生命回复"),
    ("heal_move", 44, "移步回血%", 'int', "移动回复生命 = 起终点曼哈顿距离 × 生命上限 × 本值 / 100，不按实际途经格数计算"),
    ("mp_pct", 46, "内力上限加成%", 'int', "内力上限百分比加成，不是当前内力回复"),
    ("mp_move", 48, "移步回气%", 'int', "移动回复内力 = 起终点曼哈顿距离 × 内力上限 × 本值 / 100，不按实际途经格数计算"),
    ("atk_pct", 50, "攻击加成%", 'int', "相对基础攻击的百分比加成"),
    ("def_pct", 52, "防御加成%", 'int', "相对基础防御的百分比加成"),
    ("hit_pct", 54, "命中加成%", 'int', "相对基础命中的百分比加成"),
    ("eva_pct", 56, "闪避加成%", 'int', "相对基础闪避的百分比加成"),
    ("spd_pct", 58, "速度加成%", 'int', "相对基础速度的百分比加成"),
    ("move_up", 60, "移动增加", 'int', "直接增加移动力：1=+1，2=+2"),
    ("atk_count", 62, "普攻次数增加", 'int', "基础普攻次数为1：1=二连，2=三连；实际执行还受技能/反应限制"),
    ("special_flags",64,"特殊标志", 'flags', "飘浮=避开陷阱；飙行=额外移动机会；搜宝=检查沿途宝物；解陷=处理沿途陷阱；保留未知高位"),
    ("mp_reduce", 66, "内息消耗减%", 'int', "施展指令技能内息减少%"),
]

IMMUNE_FIELDS = [
    ("immunity1", 68, "状态抗性1–16", 'mask', "选择状态1–16的抗性写入位置，配合抗性档位（offset88）使用，勾选不等于免疫；未知第16位保留原值"),
    ("immunity2", 70, "状态抗性17–32", 'mask', "选择状态17–32的抗性写入位置，配合抗性档位（offset88）使用，勾选不等于免疫；未知第32位保留原值"),
    ("exp_bonus", 72, "战后经验增加%", 'int', "战斗经验值增加% (鬼才)"),
    ("jp_bonus", 74, "战后技点增加%", 'int', "战斗技能点增加% (天才)"),
    ("magic_def", 76, "术法类伤害减免%", 'int', "减少术法类HP/MP伤害；按运行类别>=2及物品例外处理，不是单凭TKKon物理执行标志判断"),
    ("cost_gold", 78, "消耗金钱", 'int', "原版技能执行消耗的金钱，不限于召唤或幻灵技能"),
    ("cost_res2", 80, "耗费兽元", 'int', "原版技能执行消耗的兽元，不限于召唤技能"),
]

ADVANCED_FIELDS = [
    ("cost_res3", 82, "耗费灵魂", 'int', "原版技能执行消耗的灵魂，不限于幻灵技能"),
    ("turn_shift", 84, "目标时序系数", 'int', "正数：本值 × (260 - 目标速度)；负数：本值 × 目标速度；伤害路径还检查实际伤害，并非仅对敌人的固定时序偏移"),
    ("mp_cost", 86, "耗费内力", 'int', "基础内力消耗；实际值受减耗及状态影响，基础非0时调整后最低为1"),
    ("trigger_prob",88, "抗性档位／被动参数", 'int', "主动技能：将低字节写入掩码指定状态的抗性；50/75/100有特殊分支，100禁止附加，并非任意百分比。被动技能：完整WORD作为反应参数，含义依原版反应编号而异，不统一代表触发概率"),
    ("sub_count", 90, "连续子项数／归组标记", 'int', "0=顶层直接执行；正数N=展开后续N条；-1=非组头归组/学习恢复标记，不能作为顶层独立指令（原版会空展开）；类型0不一定是组头"),
    ("atk_type", 92, "技能结算分支", 'atk_type', "原版读取低字节+1得到运行类别0/1/2/11，对应-1/0/1/10；距离由TKKon另定，物理命中/防御由TKKon执行标志0x04另定。10仅有原版编号222、224..231、251等召唤分发支持，新增技能仅改10不保证能召唤；未知16位值原样保留"),
]

ALL_FIELDS = (BASIC_FIELDS + EFFECT_FIELDS + IMMUNE_FIELDS + list(ADVANCED_FIELDS) + TREE_FIELDS)

WARPC_EXTENSION_SKILL_START = 344
WARPC_EXTENSION_SKILL_END = SKILL_ORIG_CNT
WARPC_EXTENSION_SKILL_MESSAGE = (
    "编号 #344..349 已被 WarPC 补丁扩展字段占用：\n"
    "战场图集索引、队伍头像 ID、历史文本 ID、地图实体 ID。\n\n"
    "这些槽位不能作为技能编辑，新增技能会从 #350 开始。"
)


def blank_skill_record(index):
    record = {'index': index}
    for key, _, _, _, _ in ALL_FIELDS:
        record[key] = 0
    record['sub_count'] = -1
    return record


def is_warpc_extension_skill_index(index):
    return WARPC_EXTENSION_SKILL_START <= index < WARPC_EXTENSION_SKILL_END


def clear_warpc_extension_skill_slots(records):
    """Clear protected WarPC extension slots and return the affected indices."""
    cleared = []
    for record in records:
        index = record.get('index')
        if not isinstance(index, int) or not is_warpc_extension_skill_index(index):
            continue
        if any(record.get(key, 0) != 0 for key, _, _, _, _ in ALL_FIELDS):
            cleared.append(index)
        blank = blank_skill_record(index)
        record.clear()
        record.update(blank)
    return cleared


TYPE_HINT_LABELS = {
    1: "主动技能: 装备后的属性加成与状态抗性，不代表战斗菜单中可主动施放",
    2: "被动技能: 由原版编号303..330等选择反应；参数依编号而异，新增类型2不会自动生成任意反应",
    3: "移动技能: 移动力增量、移动回复与特殊标志；飙行提供额外移动机会而非增加范围",
    0: "指令技能: 按连续子项数决定执行方式；类型0不一定是组头",
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
    if not dec or len(dec) % SKILL_REC:
        raise ValueError(
            f"解压后大小 {len(dec)} 不是技能记录大小 {SKILL_REC} 的整数倍")
    recs = []
    count = len(dec) // SKILL_REC
    for i in range(count):
        off = i * SKILL_REC
        fields = struct.unpack_from('<' + 'h' * 47, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_skills(fp, recs):
    count = len(recs)
    if count > SKILL_MAX_CNT:
        raise ValueError(
            f"技能记录数 {count} 超过原版扩展上限 {SKILL_MAX_CNT} 条")
    buf = bytearray(count * SKILL_REC)
    for rec in recs:
        i = rec['index']
        if not 0 <= i < count:
            raise ValueError(f"技能记录索引越界: {i}")
        off = i * SKILL_REC
        for k, fo, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    # 压缩回写校验 — 与 item/shop/warpc/kon 编辑器保持一致, 防止压缩流损坏数据
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True

# ============================================================
# 技能链拓扑图查看器
# ============================================================

class SkillGraphView(QGraphicsView):
    """可缩放 / 拖拽平移的技能拓扑图视图 (滚轮缩放, 双击节点回调, 点阵网格背景)。"""

    def __init__(self, on_node_double_clicked=None, theme_id="gpt-dark"):
        super().__init__()
        self._on_dbl = on_node_double_clicked
        self.theme_id = theme_id
        self._pal = business_colors("skill_graph", theme_id)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                            | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)   # 先绘制背景色
        grid = 28
        # 缩得太小时不绘点阵, 避免大量绘制卡顿
        if rect.width() / grid * (rect.height() / grid) > 8000:
            return
        dot = QColor(self._pal["grid_dot"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(dot))
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        gx = left
        while gx < rect.right():
            gy = top
            while gy < rect.bottom():
                painter.drawEllipse(QPointF(gx, gy), 1.1, 1.1)
                gy += grid
            gx += grid

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
      源技能.ref_skill[i] = 目标技能索引; 学会源技能后，仅对学习状态1..9的目标累加ref_type低字节。
      目标累计进度 ≥10 即可学习; 权重20还将源技能学习状态设为30，并非所有引用都直接归组。
      A→B 表示 A 对 B 的学习进度贡献；静态图不代表角色当前已经满足学习条件。
    """

    NODE_W = 190
    NODE_H = 64
    HGAP = 52
    VGAP = 120
    RADIUS = 12
    ACCENT_W = 12

    def __init__(self, parent, records, tkt_dict, focus_idx, theme_id="gpt-dark"):
        super().__init__(parent)
        self.records = records
        self.tkt_dict = tkt_dict
        self.focus_idx = focus_idx
        self.theme_id = theme_id
        self._pal = business_colors("skill_graph", theme_id)
        self._fitted = False
        self._mode = 'all'  # all=前置+解锁 · down=仅向下(解锁链) · up=仅向上(前置链)
        self._show_group = True  # 是否显示归组关联

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
                self.total_in[b] = self.total_in.get(b, 0) + (w & 0xFF)

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
            "卡片左侧色条 = 技能类型: 蓝=指令 · 橙=主动 · 绿=被动 · 紫=移动。"
            "箭头方向 = 前置 → 目标; 学会源技能后，仅对学习状态1..9的目标累加权重低字节 (+N)，累计 ≥10 可学。"
            "紫色虚线表示归组。"
            "节点右上徽标 = WarPC 技能学习表建议初始状态（非实际学习状态）: "
            "入口(绿)→可以学(10) · 下游(灰蓝)→等待学(1) · 组头(紫，连续子项数>0的指令)→等待学(1)。"
            "滚轮缩放 · 拖拽平移 · 双击节点重新聚焦。")
        legend.setWordWrap(True)
        legend.setProperty("class", "PropLabel")
        layout.addWidget(legend)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("显示范围:"))
        self.mode_box = EditorComboBox()
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
        self.view = SkillGraphView(self._on_node_double_clicked, self.theme_id)
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(
            QBrush(QColor(business_colors("skill_graph", self.theme_id)["canvas_bg"])))
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
        types = self._pal["type_graph"]
        return QColor(types.get(tv, types["_"]))

    @staticmethod
    def _rounded_path(x, y, w, h, r, tl=True, tr=True, br=True, bl=True):
        """构造可分别控制四角圆角的圆角矩形路径 (用于卡片与左侧强调条无缝拼合)。"""
        p = QPainterPath()
        p.moveTo(x + (r if tl else 0), y)
        p.lineTo(x + w - (r if tr else 0), y)
        if tr:
            p.quadTo(x + w, y, x + w, y + r)
        p.lineTo(x + w, y + h - (r if br else 0))
        if br:
            p.quadTo(x + w, y + h, x + w - r, y + h)
        p.lineTo(x + (r if bl else 0), y + h)
        if bl:
            p.quadTo(x, y + h, x, y + h - r)
        p.lineTo(x, y + (r if tl else 0))
        if tl:
            p.quadTo(x, y, x + r, y)
        p.closeSubpath()
        return p

    def _node_tooltip(self, idx):
        rec = self.records[idx]
        name = skill_name(rec, self.tkt_dict)
        lines = [f"{name}  #{idx}  [{SKILL_TYPES.get(rec.get('type', 0), '')}]"]
        role, state, _ = self._seed_role(idx)
        lines.append(f"WarPC 建议初始状态: {role} → {state}")
        lines.append("仅对学习状态1..9的目标累加进度；权重20会追加+20，并使源技能自动学会。")
        plist = self.parents.get(idx, [])
        if plist:
            lines.append("前置 (往上):")
            for (a, w, _i) in plist:
                lines.append(f"  · {skill_name(self.records[a], self.tkt_dict)} #{a} → +{w & 0xFF} (原值{w})")
            lines.append(f"  潜在进度合计 {self.total_in.get(idx, 0)} (实际累计≥10可学习，非当前角色状态)")
        clist = self.children.get(idx, [])
        if clist:
            lines.append("解锁 (往下):")
            for (b, w, _i) in clist:
                lines.append(f"  · {skill_name(self.records[b], self.tkt_dict)} #{b} → +{w & 0xFF} (原值{w})")
        return "\n".join(lines)

    # ── 绘制 ──
    def _draw_edge(self, a, b, a_xy, b_xy, w):
        ax, ay = a_xy
        bx, by = b_xy
        p1 = QPointF(ax + self.NODE_W / 2, ay + self.NODE_H)  # 前置底部中点
        p2 = QPointF(bx + self.NODE_W / 2, by)                # 解锁顶部中点
        is_group = (w == 20)  # 归组
        is_focus_edge = (a == self.focus_idx or b == self.focus_idx)
        if is_group:
            color = QColor(self._pal["edge_regroup"])   # 归组: 紫色
        elif is_focus_edge:
            color = QColor(self._pal["edge_focus"])     # 与聚焦相连: 琥珀
        else:
            color = QColor(self._pal["edge_normal"])
        pen = QPen(color, 2.4 if is_focus_edge else 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if is_group:
            pen.setStyle(Qt.DashLine)
        # 竖直方向三次贝塞尔 S 曲线, 更柔和专业
        off = max(30.0, abs(p2.y() - p1.y()) * 0.42)
        c2 = QPointF(p2.x(), p2.y() - off)
        path = QPainterPath(p1)
        path.cubicTo(QPointF(p1.x(), p1.y() + off), c2, p2)
        edge = self.scene.addPath(path, pen)
        edge.setZValue(2 if is_focus_edge else 1)
        self._draw_arrow(c2, p2, color, is_focus_edge)
        self._draw_edge_label((p1 + p2) / 2.0, w)

    def _draw_arrow(self, p_from, p_to, color, emphasized=False):
        ang = math.atan2(p_to.y() - p_from.y(), p_to.x() - p_from.x())
        size = 11 if emphasized else 9
        spread = math.pi / 7
        left = QPointF(p_to.x() - size * math.cos(ang - spread),
                       p_to.y() - size * math.sin(ang - spread))
        right = QPointF(p_to.x() - size * math.cos(ang + spread),
                        p_to.y() - size * math.sin(ang + spread))
        arrow = self.scene.addPolygon(QPolygonF([p_to, left, right]),
                                      QPen(color, 1), QBrush(color))
        arrow.setZValue(3)

    @staticmethod
    def _weight_label(w):
        if w == 20:
            return "归组"
        if (w & 0xFF) >= 10:
            return "自足"
        return f"+{w & 0xFF}"

    def _draw_edge_label(self, mid, w):
        if w == 20:
            fg, bg = (QColor(c) for c in self._pal["edge_label_regroup"])
        elif (w & 0xFF) >= 10:
            fg, bg = (QColor(c) for c in self._pal["edge_label_self"])
        else:
            fg, bg = (QColor(c) for c in self._pal["edge_label_plus"])
        txt = self._weight_label(w)
        label = self.scene.addSimpleText(txt)
        f = label.font()
        f.setPointSize(8)
        f.setBold(True)
        label.setFont(f)
        label.setBrush(QBrush(fg))
        br = label.boundingRect()
        cw, ch = br.width() + 12, br.height() + 4
        chip_path = QPainterPath()
        chip_path.addRoundedRect(QRectF(0, 0, cw, ch), ch / 2.0, ch / 2.0)
        chip = self.scene.addPath(chip_path, QPen(Qt.NoPen), QBrush(bg))
        chip.setPos(mid.x() - cw / 2.0, mid.y() - ch / 2.0)
        chip.setZValue(3)
        label.setPos(mid.x() - br.width() / 2.0, mid.y() - br.height() / 2.0)
        label.setZValue(4)

    def _seed_role(self, idx):
        """按 warpc 播种规则给出该技能在角色技能学习表中的建议初始状态:
        组头(连续子项数>0的指令技能) → 等待学(1);
        入口(无任何前置) → 可以学(10);
        下游(有前置)   → 等待学(1, 满足进度条件后可学习)。
        徽标底色为深饱和色 (配白字保证明暗对比), 三色区分明显; 深浅主题一致。"""
        rec = self.records[idx]
        if rec.get('type', 0) == 0 and rec.get('sub_count', -1) > 0:
            return ("组头", "等待学(1)", QColor(SEED_GROUP_COLOR))   # 紫
        if self.total_in.get(idx, 0) == 0:
            return ("入口", "可以学(10)", QColor(SEED_ENTRY_COLOR))  # 绿
        return ("下游", "等待学(1)", QColor(SEED_DOWN_COLOR))       # 灰蓝

    def _draw_seed_badge(self, idx, x, y):
        """在节点右上角骑顶边绘制建议初始状态徽标药丸 (入口/下游/组头)。"""
        label, _state, col = self._seed_role(idx)
        txt = self.scene.addSimpleText(label)
        f = txt.font()
        f.setPointSize(7)
        f.setBold(True)
        txt.setFont(f)
        br = txt.boundingRect()
        cw, ch = br.width() + 13, br.height() + 5
        cx = x + self.NODE_W - cw - 9
        cy = y - ch / 2.0
        chip_path = QPainterPath()
        chip_path.addRoundedRect(QRectF(0, 0, cw, ch), ch / 2.0, ch / 2.0)
        chip = self.scene.addPath(chip_path, QPen(col.darker(125), 1.1), QBrush(col))
        chip.setPos(cx, cy)
        chip.setZValue(7)
        chip.setData(0, idx)
        txt.setBrush(QBrush(QColor("#ffffff")))  # 白字 (深饱和底), 主题无关
        txt.setPos(cx + (cw - br.width()) / 2.0, cy + (ch - br.height()) / 2.0)
        txt.setZValue(8)
        txt.setData(0, idx)

    def _draw_node(self, idx, xy):
        x, y = xy
        rec = self.records[idx]
        tv = rec.get('type', 0)
        name = skill_name(rec, self.tkt_dict)
        tcol = self._type_color(tv)
        is_focus = (idx == self.focus_idx)
        W, H, R, AW = self.NODE_W, self.NODE_H, self.RADIUS, self.ACCENT_W

        fill_col = QColor(self._pal["node_fill_focus"] if is_focus
                          else self._pal["node_fill"])
        border_col, name_col, sub_col = (
            QColor(self._pal[k]) for k in ("node_border", "node_name", "node_sub"))
        shadow_col = QColor(*self._pal["node_shadow"])
        focus_border = QColor(self._pal["focus_border"])
        focus_glow = QColor(*self._pal["focus_glow"])

        # 底层: 类型强调色 (完整圆角矩形, 承载卡片轻投影; 左侧 AW=R 宽度露出, 完美贴合左圆角)
        accent = self.scene.addPath(self._rounded_path(0, 0, W, H, R), QPen(Qt.NoPen), QBrush(tcol))
        accent.setPos(x, y)
        accent.setZValue(5.0)
        accent.setData(0, idx)
        eff = QGraphicsDropShadowEffect()
        if is_focus:
            eff.setBlurRadius(22)
            eff.setColor(focus_glow)
            eff.setOffset(0, 0)
        else:
            eff.setBlurRadius(11)
            eff.setColor(shadow_col)
            eff.setOffset(0, 2)
        accent.setGraphicsEffect(eff)

        # 中层: 卡片主体 (扁平纯色填充; 左侧直角贴合强调条, 右侧圆角)
        body = self.scene.addPath(
            self._rounded_path(AW, 0, W - AW, H, R, tl=False, tr=True, br=True, bl=False),
            QPen(Qt.NoPen), QBrush(fill_col))
        body.setPos(x, y)
        body.setZValue(5.1)
        body.setData(0, idx)

        # 顶层: 整卡描边 (聚焦=琥珀描边)
        outline = self.scene.addPath(
            self._rounded_path(0, 0, W, H, R),
            QPen(focus_border, 2.3) if is_focus else QPen(border_col, 1.3))
        outline.setPos(x, y)
        outline.setZValue(5.2)
        outline.setData(0, idx)
        outline.setToolTip(self._node_tooltip(idx))

        # 名称 (中性高对比色, 类型已由强调条表达) + 副标题
        name_t = self.scene.addSimpleText(name)
        nf = name_t.font()
        nf.setPointSize(12)
        nf.setBold(True)
        name_t.setFont(nf)
        name_t.setBrush(QBrush(name_col))
        nb = name_t.boundingRect()
        name_t.setPos(x + AW + (W - AW - nb.width()) / 2, y + 13)
        name_t.setZValue(6)
        name_t.setData(0, idx)

        sub_t = self.scene.addSimpleText(f"#{idx} · {SKILL_TYPES.get(tv, tv)}")
        sf = sub_t.font()
        sf.setPointSize(8)
        sub_t.setFont(sf)
        sub_t.setBrush(QBrush(sub_col))
        sbb = sub_t.boundingRect()
        sub_t.setPos(x + AW + (W - AW - sbb.width()) / 2, y + 38)
        sub_t.setZValue(6)
        sub_t.setData(0, idx)

        self._draw_seed_badge(idx, x, y)

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
            self._draw_edge(a, b, pos[a], pos[b], w)
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

class SkillEditorApp(FieldUndoMixin, EditorMainWindow):
    EDITOR_KEY = "skill_editor"
    DEFAULT_SIZE = (1360, 820)
    MIN_SIZE = (1100, 650)

    HELP_TEXT = (
        "功能: 编辑《三国群侠传》技能数据\n"
        "数据: 原版 350 条 × 94 字节；支持追加扩展技能\n\n"
        "特性:\n"
        "  · Godot 4.6 级别布局与纯净控件约束\n"
        "  · 分组编辑: 基础/效果/抗性/进阶/技能树\n"
        "  · 按独立文本ID关联 TKT.dat 显示技能名称与说明\n"
        "  · 每行右键: 复制 / 粘贴 / 清除 / 删除 / 查看技能树\n"
        "  · 原版技能只能清除；扩展技能可删除")

    def _init_data(self):
        self.skill_path = self.tkt_path = None
        self.records = []
        self.tkt = {}
        self.tkt_full = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None
        self._clipboard = None

        self.mu_path = None
        self._mu_sprites = []
        self._icon_pixmaps = {}

        self.widget_map = {}
        self.extra_map = {}
        self._init_undo()  # 撤销/重做 (P3-4)

    def _after_build(self):
        self._set_edit_enabled(False)
        self._apply_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_splitter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_splitter_width()

    def _sync_splitter_width(self):
        """保持列表在窄窗口下仍能显示完整表头，放大时仅小幅增加列表占比。"""
        splitter = getattr(self, "splitter", None)
        if splitter is None:
            return
        total = splitter.width()
        if total <= 0:
            return
        if total < 1296:
            left = max(480, int(total * 0.45))
        else:
            left = min(680, 540 + int((total - 1296) * 0.25))
        splitter.setSizes([left, max(1, total - left)])

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录", QKeySequence("Ctrl+O"), self._load_tks_dir)
        self.attach_recent_dirs_menu(fm)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("撤销", QKeySequence("Ctrl+Z"), self.undo)
        em.addAction("重做", QKeySequence("Ctrl+Y"), self.redo)
        em.addSeparator()
        em.addAction("新建技能", QKeySequence("Ctrl+N"), self._new_skill)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("粘贴到当前记录", self._paste_current)
        em.addAction("清除当前记录", self._clear_current)
        em.addAction("删除当前记录", self._delete_current)

        self.add_standard_menus(menu_bar)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = SearchInput("搜索技能名称或ID")
        self.search_entry.setMinimumWidth(160)
        self.search_entry.textChanged.connect(self._apply_filter)
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
        self.type_filter = EditorComboBox()
        self.type_filter.addItems(["全部类型"] + SKILL_TYPE_VALUES)
        self.type_filter.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_filter)

        toolbar.addSpacing(15)
        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)

        toolbar.addStretch()

        btn_theme = QPushButton("切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)

        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # --- Main Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        main_layout.addWidget(self.splitter, 1)

        # --- Left Pane (Table) ---
        self.table = AdaptiveTableWidget(
            0, 6,
            stretch_columns={3},
            minimum_widths=[62, 72, 90, 112, 82, 84],
            row_height=44,
        )
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称', '学习技能点', '耗费内力'])
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.splitter.setChildrenCollapsible(False)
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
        btn_apply = QPushButton("应用")
        btn_apply.clicked.connect(self._apply_edit)
        btn_reset = QPushButton("重置")
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
        self._build_field_group("效果加成 (主动／移动技能)", EFFECT_FIELDS, 4)
        self._build_field_group("状态抗性／战后加成／消耗", IMMUNE_FIELDS, 4)
        self._build_field_group("高级属性／被动技能参数／指令结算", ADVANCED_FIELDS, 4)
        self._build_field_group("技能树引用表 (8组: 目标/进度权重)", TREE_FIELDS, 4)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)

        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([540, 796])

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
        """字段分组：标签在上、输入框在下 (对齐 warpc_editor 布局)"""
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
            btn = QPushButton()
            set_themed_icon(btn, "picker")
            btn.setObjectName("FakeInputRightButton")
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
            cb = EditorComboBox()
            values = SKILL_TYPES if ft == 'type' else ATK_TYPE_VALUES
            for value, label in sorted(values.items()):
                cb.addItem(f"{value}-{label}", value)
            cell.addWidget(make_fake_input(combo=cb))
            self.widget_map[fn] = cb

        elif ft == 'mask' or ft == 'flags':
            inp = QLineEdit()
            inp.setVisible(False)

            btn = QPushButton("配置状态抗性" if ft == 'mask' else "配置特殊标志")
            btn.setToolTip(f"[{fo:02d}] {cmt}")
            if ft == 'mask':
                btn.setObjectName("StatusPickerButton")
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
            # 数值字段: 限制只能输入 int16 范围内整数 (防非法/越界输入静默归零)
            inp.setValidator(QIntValidator(-32768, 32767, inp))
            cell.addWidget(make_fake_input(line_edit=inp))
            self.widget_map[fn] = inp

        self.widget_map[fn].setToolTip(f"[{fo:02d}] {cmt}")
        grid.addLayout(cell, row, col, Qt.AlignTop)

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._update_paths()

    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        self._update_paths()

    def _update_paths(self):
        update_path_labels([
            (self.lbl_skill_path, self.skill_path, "TKSkill.dat"),
            (self.lbl_tkt_path, self.tkt_path, "TKT.dat"),
            (self.lbl_mu_path, self.mu_path, "Mu.JVG"),
        ], self._is_dark)

    def load_tks_dir(self, d):
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
            cleared = clear_warpc_extension_skill_slots(self.records)
            self.clear_undo()  # 数据整体重载, 旧变更集失效 (P3-4)
            self._dirty = bool(cleared)
            # MOD 导出使用原始字节序 (word index = byte_offset // 2)，与启动器 _apply_fields_to_record 一致
            self._original_records = []
            for rec in self.records:
                row = [0] * (SKILL_REC // 2)
                for k, fo, _, _, _ in ALL_FIELDS:
                    row[fo // 2] = rec[k]
                self._original_records.append(row)
            nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
            status = (
                f"{len(self.records)} 条 | 有效 {nonempty} | "
                f"TKT {len(self.tkt)} 条"
            )
            if cleared:
                status += f" | 已强制清空扩展字段冲突槽 {cleared}"
            self.status_var.setText(status)
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
        q = self.search_entry.text()
        self.filtered_indices = []
        ftype = self.type_filter.currentText()
        for rec in self.records:
            if (ftype and not ftype.startswith("全部")
                    and rec['skill_text_id'] != 0):
                if rec['type'] != int(ftype.split('-')[0]): continue
            if q:
                nm = skill_name(rec, self.tkt)
                if not search_match(q, rec['index'], rec['skill_text_id'], nm):
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
        disabled_color = QColor(
            business_colors("launcher", self._theme_id)["placeholder_gray"]
        )
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            protected = is_warpc_extension_skill_index(r['index'])
            stype = SKILL_TYPES.get(r['type'], f"#{r['type']}")
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 1, QTableWidgetItem(str(r['skill_text_id'])))
            self.table.setItem(
                row, 2,
                QTableWidgetItem("禁用" if protected else stype),
            )
            self.table.setItem(
                row, 3,
                QTableWidgetItem("禁用" if protected else skill_name(r, self.tkt)),
            )
            self.table.setItem(row, 4, QTableWidgetItem(str(r['jp_cost'])))
            self.table.setItem(row, 5, QTableWidgetItem(str(r['mp_cost'])))

            # ==== 核心改造：为所有 4 种技能类型分配高辨识度专属颜色 ====
            # 技能类型高亮配色 (语义表: theme_tokens.SKILL_GRAPH.type_detail)
            types = business_colors("skill_graph", self._theme_id)["type_detail"]
            color = QColor(types.get(r['type'], types["_"]))

            for c in range(6):
                item = self.table.item(row, c)
                if protected:
                    item.setForeground(disabled_color)
                    item.setFlags(
                        item.flags() & ~(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    )
                    item.setToolTip(WARPC_EXTENSION_SKILL_MESSAGE)
                else:
                    item.setForeground(color)

        self.table.blockSignals(False)
        self.table.fit_columns_to_viewport()

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        if is_warpc_extension_skill_index(idx):
            return
        if idx == self._editing_idx:
            return  # 回到当前编辑记录 (含取消切换后的恢复), 不重填
        if self._unapplied_edits_guard(idx):
            return
        self._populate_edit(self.records[idx])

    def _unapplied_edits_guard(self, new_idx):
        """切换记录前检测未点「应用修改」的表单修改; 有则提示。

        返回 True 表示用户取消切换 (选中已恢复到原记录)。
        """
        if self._editing_idx is None or self._editing_idx == new_idx:
            return False
        rec = self.records[self._editing_idx]
        combo_keys = {'type', 'atk_type'}
        if not form_edits_pending(self.widget_map, rec,
                                  [f[0] for f in ALL_FIELDS], combo_keys):
            return False
        reply = themed_question(
            self, "未应用的修改",
            f"记录 #{rec['index']} 有未点「应用修改」的表单修改。\n\n"
            "切换将丢弃这些修改，是否继续？")
        if reply == QMessageBox.Yes:
            return False
        for r in range(self.table.rowCount()):  # 恢复选中到原记录
            if int(self.table.item(r, 0).text()) == self._editing_idx:
                self.table.selectRow(r)
                break
        return True

    def _show_table_context_menu(self, pos):
        """技能列表右键菜单: 行操作与技能树查看。"""
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
        if is_warpc_extension_skill_index(idx):
            return

        self.table.selectRow(item.row())
        current_row = self.table.currentRow()
        if current_row < 0:
            return
        current_item = self.table.item(current_row, 0)
        if current_item is None or int(current_item.text()) != idx:
            return
        if self._editing_idx != idx:
            self._populate_edit(self.records[idx])

        menu = self._build_table_context_menu(idx)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _build_table_context_menu(self, idx):
        """构建单行操作菜单，便于右键入口与测试共用。"""
        menu = QMenu(self)
        menu.addAction("复制", lambda: self._clipboard_copy(idx))
        paste_action = menu.addAction("粘贴", lambda: self._clipboard_paste(idx))
        paste_action.setEnabled(self._clipboard is not None)
        menu.addAction("清除", lambda: self._clear_record(idx))
        delete_action = menu.addAction("删除", lambda: self._delete_record(idx))
        delete_action.setEnabled(idx >= SKILL_ORIG_CNT)
        if idx < SKILL_ORIG_CNT:
            delete_action.setToolTip("原版技能不能删除，请使用清除功能")
        menu.addSeparator()
        menu.addAction("查看技能树", lambda: self._show_skill_tree(idx))
        return menu

    def _show_skill_tree(self, idx):
        """弹出技能树窗口: 以该技能为中心双向关联展开。"""
        if not self.records or idx < 0 or idx >= len(self.records):
            return
        dlg = SkillTreeDialog(self, self.records, self.tkt, idx, self._theme_id)
        dlg.exec()

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        stype = SKILL_TYPES.get(rec['type'], f"#{rec['type']}")
        self.lbl_rec_idx.setText(f"技能 #{rec['index']}  文本ID={rec['skill_text_id']}  类型={stype}")

        nid = rec.get('skill_text_id', 0)
        n_txt = self.tkt.get(nid, "") if nid > 0 else ""
        # 加上前缀增加仪式感，空名称处理也更加优雅
        self.preview_name.setText(n_txt.split('\n')[0].strip() if n_txt else "未命名技能")

        self._update_desc_preview(rec.get('skill_desc_id', 0))

        hint = TYPE_HINT_LABELS.get(rec['type'], "")

        # ==== 检查器预览区类型同步高亮 ====
        types = business_colors("skill_graph", self._theme_id)["type_detail"]
        type_color = types.get(rec['type'], types["_"])

        # 使用 HTML 富文本进行局部着色，完美保留 QSS 的边框与排版
        self.preview_type.setText(
            f'<span style="color: {type_color}; font-weight: bold;">【{stype}】</span> '
            f'| 学习技能点={rec["jp_cost"]} | 内力={rec["mp_cost"]} | {hint}'
        )
        self.preview_type.setToolTip(self.widget_map['trigger_prob'].toolTip())
        sc = rec.get('sub_count', -1)
        if sc > 0:
            sub_txt = f"连续子项: {sc} 个 (ID {rec['index']+1} - {rec['index']+sc})"
            if sc > 12:
                sub_txt += (f'<br><span style="color:{SUB_OVERFLOW_COLOR}; font-weight:bold;">'
                            '原版战斗菜单最多12项；本组同时已学子技能（学习状态≥20）超过12个会越界，'
                            '当前扩展补丁会限制列入数量；不是限制可学习（状态10）的技能数。</span>')
            self.preview_sub.setText(sub_txt)
        elif sc == 0:
            self.preview_sub.setText("直接技能：作为顶层指令时直接执行，不展开后续子项。")
        elif sc == -1:
            self.preview_sub.setText("非组头归组／学习恢复标记：不能作为顶层独立指令（原版会空展开）。")
        else:
            self.preview_sub.setText(f"连续子项数／归组标记：未知值 {sc}，保留原值。")

        for fn, fo, fl, ft, _ in ALL_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if not w: continue

            if ft == 'type' or ft == 'atk_type':
                unknown_role = Qt.UserRole + 1
                for i in range(w.count() - 1, -1, -1):
                    if w.itemData(i, unknown_role):
                        w.removeItem(i)
                idx = w.findData(val)
                if idx < 0:
                    w.addItem(f"{val}-未知", val)
                    idx = w.count() - 1
                    w.setItemData(idx, True, unknown_role)
                w.setCurrentIndex(idx)
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

    def _update_desc_preview(self, did):
        txt = self.tkt_full.get(did, "") if did > 0 else ""
        self.preview_desc.setText(txt if txt else "暂无关于该技能的详细描述。")
        self.preview_desc.setToolTip(f"说明文本ID={did}；独立 TKT 编号，不由名称文本ID推算。")

    def _update_mask_label(self, fn, mask):
        base = 0 if fn == 'immunity1' else 16
        sel = []
        for i in range(16):
            if mask & (1 << i):
                sel.append(RESISTANCE_STATUS_NAMES[base + i])
        self.extra_map[fn].setText("抗性状态: " + (", ".join(sel) if sel else "(无)"))
        self.extra_map[fn].setToolTip(self.widget_map['trigger_prob'].toolTip())

    def _update_flags_label(self, fn, val):
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in SPECIAL_FLAG_BITS if mask & (1 << bit)]
        unknown = mask & ~sum(1 << bit for bit, _, _ in SPECIAL_FLAG_BITS)
        if unknown:
            sel.append(f"未知位 0x{unknown:04X}")
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
            elif fn == 'skill_desc_id': self._update_desc_preview(dlg.selected_id)

    def _pick_skill(self, fn):
        if not self.records: return
        rows = [(r['index'],
                 (str(r['index']), str(r['skill_text_id']),
                  SKILL_TYPES.get(r['type'], str(r['type'])), skill_name(r, self.tkt)),
                 r['type'])
                for r in self.records if r['skill_text_id'] != 0]
        dlg = SkillPickerDialog(
            self, rows, ('技能ID', '文本ID', '类型', '技能名称'),
            stretch_columns={3}, minimum_widths=[68, 72, 92, 60], size=(600, 550),
            type_filter=[(k, f"{k}-{v}") for k, v in sorted(SKILL_TYPES.items())])
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = skill_name(self.records[dlg.selected_index], self.tkt) if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)

    def _pick_status(self, fn):
        base = 0 if fn == 'immunity1' else 16
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = StatusPickerDialog(self, f"选择状态抗性 ({base + 1}–{base + 16})",
                                 RESISTANCE_STATUS_NAMES, cur, base,
                                 self._get_icon_pixmap, False)
        for bit, cb in dlg.checkboxes:
            cb.setText(f"{base + bit + 1}. {RESISTANCE_STATUS_NAMES[base + bit]}")
            if bit == 15:
                cb.setEnabled(False)
                cb.setToolTip("此状态位语义未明，保留原值，不随全选/全清修改。")
                cb.toggled.connect(lambda _, box=cb: box.setChecked(bool(cur & 0x8000)))
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            mask = (dlg.selected_mask & 0x7FFF) | (cur & 0x8000)
            value = mask if mask < 0x8000 else mask - 0x10000
            self.widget_map[fn].setText(str(value))
            self._update_mask_label(fn, mask)

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
        btn_clear = QPushButton("清除已知标志")
        btn_clear.setToolTip("仅清除已知四位，保留未知高位。")
        btn_clear.clicked.connect(lambda: [cb.setChecked(False) for _, cb in checkboxes])
        btn_ok = QPushButton("确定")
        def _ok():
            m = cur & ~sum(1 << bit for bit, _, _ in SPECIAL_FLAG_BITS)
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
        if is_warpc_extension_skill_index(rec['index']):
            return
        undo_before = {fn: rec[fn] for fn, fo, fl, ft, _ in ALL_FIELDS}
        for fn, fo, fl, ft, _ in ALL_FIELDS:
            w = self.widget_map.get(fn)
            if not w: continue
            if ft == 'type' or ft == 'atk_type':
                v = self._combo_field_value(w, rec.get(fn, 0))
            # 数值字段: 校验失败/越界即时红框反馈 (不再静默归零)
            elif isinstance(w, QLineEdit):
                mark_invalid(w, False)
                try:
                    v = int(w.text() or 0)
                except ValueError:
                    mark_invalid(w, True)
                    v = 0
                if v > 32767:
                    mark_invalid(w, True)
                    v = 32767
                elif v < -32768:
                    mark_invalid(w, True)
                    v = -32768
            else:
                v = int(w.text() or 0)
            rec[fn] = v

        self.push_field_changes(
            rec['index'],
            self.field_diff(undo_before, rec, [fn for fn, fo, fl, ft, _ in ALL_FIELDS]),
            f"修改记录 #{rec['index']}")
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == rec['index']:
                self.table.selectRow(r)
                break
        self._populate_edit(rec)
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存)")

    @staticmethod
    def _combo_field_value(widget, fallback=0):
        """Read int payload from a combo without relying on display text."""
        data = widget.currentData()
        if data is not None:
            try:
                return int(data)
            except (TypeError, ValueError):
                pass
        text = widget.currentText().strip()
        if text:
            head = text.split('-', 1)[0].strip()
            try:
                return int(head)
            except ValueError:
                pass
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return 0

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _new_skill(self):
        if not self.records: return
        rec = next(
            (item for item in self.records
             if item['skill_text_id'] == 0
             and not is_warpc_extension_skill_index(item['index'])),
            None,
        )
        if rec is None and len(self.records) >= SKILL_MAX_CNT:
            QMessageBox.warning(
                self,
                "技能容量已满",
                f"原版扩展补丁最多支持 {SKILL_MAX_CNT} 条技能。",
            )
            return
        if rec is None:
            while len(self.records) < WARPC_EXTENSION_SKILL_END:
                self.records.append(blank_skill_record(len(self.records)))
            rec = blank_skill_record(len(self.records))
            self.records.append(rec)
        else:
            index = rec['index']
            rec.clear()
            rec.update(blank_skill_record(index))
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
        self.status_var.setText(
            f"已创建新技能 → 槽位 #{rec['index']} (共 {len(self.records)} 条)")

    def _record_is_empty(self, rec):
        blank = blank_skill_record(rec.get('index', 0))
        return all(rec.get(key, 0) == blank[key] for key, _, _, _, _ in ALL_FIELDS)

    def _select_record(self, idx):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == str(idx):
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return True
        return False

    def _clipboard_copy(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx is None or idx < 0 or idx >= len(self.records):
            return
        if is_warpc_extension_skill_index(idx):
            return
        src = self.records[idx]
        self._clipboard = {
            key: src.get(key, 0) for key, _, _, _, _ in ALL_FIELDS
        }
        self.status_var.setText(f"已复制记录 #{idx} (可粘贴到任意技能记录)")

    def _copy_record(self):
        if self._editing_idx is None:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return
        self._clipboard_copy()

    def _clipboard_paste(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if (self._clipboard is None or idx is None
                or idx < 0 or idx >= len(self.records)):
            return
        if is_warpc_extension_skill_index(idx):
            return
        rec = self.records[idx]
        if not self._record_is_empty(rec):
            if themed_question(
                    self, "确认覆盖",
                    f"粘贴将覆盖记录 #{idx} 的现有内容，是否继续？"
            ) != QMessageBox.Yes:
                return

        keys = [key for key, _, _, _, _ in ALL_FIELDS]
        paste_before = {key: rec[key] for key in keys}
        for key in keys:
            rec[key] = self._clipboard.get(key, 0)
        changes = self.field_diff(paste_before, rec, keys)
        if changes:
            self.push_field_changes(idx, changes, f"粘贴到记录 #{idx}")
            self._dirty = True
        self._apply_filter()
        self._select_record(idx)
        self._populate_edit(rec)
        self.status_var.setText(f"已粘贴到记录 #{idx}")

    def _paste_current(self):
        self._clipboard_paste()

    def _remove_record(self, idx):
        if idx < SKILL_ORIG_CNT or idx >= len(self.records):
            return
        if themed_question(
                self, "确认删除",
                f"确定删除扩展技能 #{idx} 吗？\n"
                "删除后后续记录序号会自动前移。") != QMessageBox.Yes:
            return
        self.records.pop(idx)
        for i, rec in enumerate(self.records):
            rec['index'] = i
        self._dirty = True
        self._editing_idx = None
        self.clear_undo()
        self._apply_filter()
        self.status_var.setText(
            f"已删除扩展技能 #{idx} (共 {len(self.records)} 条, 已修改)")

    def _delete_record(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx is None or idx < 0 or idx >= len(self.records):
            return
        if idx < SKILL_ORIG_CNT:
            QMessageBox.information(
                self, "提示",
                f"原版技能 #{idx} 不能删除，只能使用清除功能。")
            return
        self._remove_record(idx)

    def _clear_record(self, idx=None):
        if idx is None:
            idx = self._editing_idx
        if idx is None or idx < 0 or idx >= len(self.records):
            return
        if is_warpc_extension_skill_index(idx):
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

        keys = [key for key, _, _, _, _ in ALL_FIELDS]
        clear_before = {key: rec[key] for key in keys}
        blank = blank_skill_record(idx)
        for key in keys:
            rec[key] = blank[key]
        changes = self.field_diff(clear_before, rec, keys)
        if changes:
            self.push_field_changes(idx, changes, f"清除记录 #{idx}")
        self._dirty = True
        self._apply_filter()
        self._select_record(idx)
        self._populate_edit(rec)
        self.status_var.setText(f"已清除记录 #{idx}")

    def _delete_current(self):
        self._delete_record()

    def _clear_current(self):
        self._clear_record()

    def _save(self):
        if not self.skill_path or not self.records: return
        cleared = clear_warpc_extension_skill_slots(self.records)
        if cleared:
            self._dirty = True
        reply = themed_question(self, "确认保存", f"将覆盖保存并生成.bak:\n{self.skill_path}")
        if reply == QMessageBox.Yes:
            backup_existing_file(self.skill_path)
            try:
                save_skills(self.skill_path, self.records)
                self._dirty = False
                QMessageBox.information(self, "成功", "保存成功！")
                status = f"已保存 → {self.skill_path}"
                if cleared:
                    status += f" | 已清空冲突槽 {cleared}"
                self.status_var.setText(status)
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    # ── MOD 导出/导入编排 (T10 收敛: 编排在 mod_exporter, 此处仅声明数据差异) ──

    @staticmethod
    def _fields_from_records(records):
        """构建原始字节序字段数组 (word index = byte_offset // 2)，与启动器一致"""
        rows = []
        for rec in records:
            row = [0] * (SKILL_REC // 2)
            for k, fo, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            rows.append(row)
        return rows

    _MOD_SPEC = RecordModSpec(
        dat_name="TKSkill.dat", rec_size=SKILL_REC, field_type="int16",
        field_count=len(ALL_FIELDS),
        to_fields=lambda records: SkillEditorApp._fields_from_records(records),
        from_fields=lambda field_rows: [
            {**{'index': i},
             **{k: (fields[fo // 2] if fo // 2 < len(fields) else 0)
                for k, fo, _, _, _ in ALL_FIELDS}}
            for i, fields in enumerate(field_rows)
        ],
        path_attr="skill_path", status_attr="status_var",
        refresh_attr="_apply_filter", noun="条技能")

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        self._enforce_warpc_extension_slot_policy("导出前")
        export_records_mod(self, self._MOD_SPEC)

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        self._enforce_warpc_extension_slot_policy("导出前")
        export_records_mod(self, self._MOD_SPEC, ref_mode=True)

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        import_records_mod(self, self._MOD_SPEC)
        self._enforce_warpc_extension_slot_policy("导入后")

    def _enforce_warpc_extension_slot_policy(self, phase):
        """Remove data occupying WarPC extension-field slots."""
        cleared = clear_warpc_extension_skill_slots(self.records)
        if not cleared:
            return
        self._dirty = True
        self._apply_filter()
        self.status_var.setText(
            f"{phase}已强制清空扩展字段冲突槽：{cleared}"
        )

def main():
    run_editor(SkillEditorApp)


if __name__ == '__main__':
    main()
