# -*- coding: utf-8 -*-
"""tks_book 角色技能树拓扑图 (只读, 可嵌入) — 复刻 skill_editor 的分层拓扑布局。

展示角色「可学习技能」集合内部的 ref_skill/ref_type 关系:
  源技能.ref_skill[g] = 目标技能索引; ref_type[g] = 学会源后给目标累加的进度权重;
  权重 20 = 归组标记 (紫虚线); >=10 = 自足解锁 (箭头由前置指向解锁)。
数据源为 tks_book 的 skill_recs (每条 {'index','vals':47×int16}):
  type=vals[2]  ref_skill_g=vals[4+2g]  ref_type_g=vals[5+2g]
节点右上徽标显示该角色对此技能的实际学习状态 (待学/可学/已会)。
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsDropShadowEffect,
)

from book_loader import SKILL_TYPES


class SkillGraphView(QGraphicsView):
    """可缩放 / 拖拽平移的技能拓扑图视图 (滚轮缩放, 点阵网格背景)。"""

    def __init__(self, is_dark=True):
        super().__init__()
        self.is_dark = is_dark
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                            | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        grid = 28
        if rect.width() / grid * (rect.height() / grid) > 8000:
            return
        dot = QColor("#28303f") if self.is_dark else QColor("#dde3ee")
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


class CharSkillGraph(QWidget):
    """角色可学习技能拓扑图组件 (只读)。set_skills({idx: state}) 渲染。"""

    NODE_W = 168
    NODE_H = 56
    HGAP = 44
    VGAP = 100
    RADIUS = 11
    ACCENT_W = 11

    def __init__(self, data, is_dark=True, parent=None):
        super().__init__(parent)
        self.data = data
        self.is_dark = is_dark
        self._states = {}
        self._fitted = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        legend = QLabel(
            "左侧色条 = 类型: 蓝=指令 橙=主动 绿=被动 紫=移动。箭头 = 前置→解锁, "
            "标签为进度权重 (+N/自足/归组)。右上徽标 = 该角色学习状态。"
            "滚轮缩放 · 拖拽平移。")
        legend.setWordWrap(True)
        legend.setProperty("class", "PropLabel")
        lay.addWidget(legend)

        self.scene = QGraphicsScene(self)
        self.view = SkillGraphView(self.is_dark)
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(
            QBrush(QColor("#12151d") if self.is_dark else QColor("#f4f6fa")))
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.addStretch()
        for label, slot in (("适应窗口", self._fit),
                            ("放大", lambda: self.view.scale(1.2, 1.2)),
                            ("缩小", lambda: self.view.scale(1 / 1.2, 1 / 1.2))):
            b = QPushButton(label)
            b.setProperty("class", "CompactBtn")
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

    # ── 数据 ──

    def set_skills(self, learn_states):
        """learn_states: {skill_idx: state(>0)} — 角色可学习技能集合"""
        self._states = dict(learn_states)
        self._render()
        if self._fitted:
            self._fit()

    def _build_edges(self, nodes):
        by_idx = {r['index']: r for r in self.data.skill_recs}
        edges = []
        for a in nodes:
            rec = by_idx.get(a)
            if not rec:
                continue
            vals = rec['vals']
            for g in range(8):
                b = vals[4 + 2 * g]
                w = vals[5 + 2 * g]
                if w == 0 or b <= 0 or b == a or b not in nodes:
                    continue
                edges.append((a, b, w))
        return edges

    def _compute_ranks(self, nodes, edges):
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
            total = len(ns) * self.NODE_W + (len(ns) - 1) * self.HGAP
            x0 = -total / 2.0
            for i, n in enumerate(ns):
                pos[n] = (x0 + i * (self.NODE_W + self.HGAP),
                          r * (self.NODE_H + self.VGAP))
        return pos

    # ── 绘制辅助 ──

    def _type_color(self, tv):
        if self.is_dark:
            return QColor({0: "#4d90d0", 1: "#e8815f", 2: "#5cbf82",
                           3: "#b98adb"}.get(tv, "#9aa4b8"))
        return QColor({0: "#2f74b0", 1: "#cf6a49", 2: "#2f9457",
                       3: "#8a5bb8"}.get(tv, "#5a6472"))

    @staticmethod
    def _state_badge(state):
        """学习状态 → (短标签, 底色)"""
        if state >= 20:
            return "已会", QColor("#2f74b0")
        if state >= 10:
            return "可学", QColor("#1f9d55")
        return "待学", QColor("#7a4fc0")

    @staticmethod
    def _rounded_path(x, y, w, h, r, tl=True, tr=True, br=True, bl=True):
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

    def _draw_edge(self, a_xy, b_xy, w):
        ax, ay = a_xy
        bx, by = b_xy
        p1 = QPointF(ax + self.NODE_W / 2, ay + self.NODE_H)
        p2 = QPointF(bx + self.NODE_W / 2, by)
        is_group = (w == 20)
        if is_group:
            color = QColor("#c58af0") if self.is_dark else QColor("#8e44ad")
        else:
            color = QColor("#586274") if self.is_dark else QColor("#a9b2c2")
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if is_group:
            pen.setStyle(Qt.DashLine)
        off = max(30.0, abs(p2.y() - p1.y()) * 0.42)
        c2 = QPointF(p2.x(), p2.y() - off)
        path = QPainterPath(p1)
        path.cubicTo(QPointF(p1.x(), p1.y() + off), c2, p2)
        self.scene.addPath(path, pen).setZValue(1)
        self._draw_arrow(c2, p2, color)
        self._draw_edge_label((p1 + p2) / 2.0, w)

    def _draw_arrow(self, p_from, p_to, color):
        ang = math.atan2(p_to.y() - p_from.y(), p_to.x() - p_from.x())
        size, spread = 9, math.pi / 7
        left = QPointF(p_to.x() - size * math.cos(ang - spread),
                       p_to.y() - size * math.sin(ang - spread))
        right = QPointF(p_to.x() - size * math.cos(ang + spread),
                        p_to.y() - size * math.sin(ang + spread))
        self.scene.addPolygon(QPolygonF([p_to, left, right]),
                              QPen(color, 1), QBrush(color)).setZValue(3)

    def _draw_edge_label(self, mid, w):
        if w == 20:
            txt, fg, bg = "归组", QColor("#e6d2ff"), QColor("#392c4e")
        elif w >= 10:
            txt, fg, bg = "自足", QColor("#bff0cd"), QColor("#25402f")
        else:
            txt, fg, bg = f"+{w}", QColor("#f0d9a8"), QColor("#322f28")
        if not self.is_dark:
            fg = {"归组": QColor("#6a3d99"), "自足": QColor("#1f6b3a")}.get(
                txt, QColor("#8a5a00"))
            bg = {"归组": QColor("#efe4fb"), "自足": QColor("#e2f5e8")}.get(
                txt, QColor("#f2ecdf"))
        label = self.scene.addSimpleText(txt)
        f = label.font()
        f.setPointSize(8)
        f.setBold(True)
        label.setFont(f)
        label.setBrush(QBrush(fg))
        br = label.boundingRect()
        cw, ch = br.width() + 12, br.height() + 4
        chip = self.scene.addPath(
            self._rounded_path(0, 0, cw, ch, ch / 2.0), QPen(Qt.NoPen), QBrush(bg))
        chip.setPos(mid.x() - cw / 2.0, mid.y() - ch / 2.0)
        chip.setZValue(3)
        label.setPos(mid.x() - br.width() / 2.0, mid.y() - br.height() / 2.0)
        label.setZValue(4)

    def _draw_node(self, idx, xy):
        x, y = xy
        by_idx = {r['index']: r for r in self.data.skill_recs}
        rec = by_idx.get(idx)
        tv = rec['vals'][2] if rec else 0
        name = self.data.skill_name(idx) or f"技能#{idx}"
        tcol = self._type_color(tv)
        W, H, R, AW = self.NODE_W, self.NODE_H, self.RADIUS, self.ACCENT_W

        if self.is_dark:
            fill_col, border_col = QColor("#282f3e"), QColor("#3b4453")
            name_col, sub_col = QColor("#eef1f6"), QColor("#8b93a7")
            shadow_col = QColor(0, 0, 0, 90)
        else:
            fill_col, border_col = QColor("#ffffff"), QColor("#d9dfe8")
            name_col, sub_col = QColor("#1f2633"), QColor("#6b7385")
            shadow_col = QColor(70, 84, 110, 40)

        accent = self.scene.addPath(self._rounded_path(0, 0, W, H, R),
                                    QPen(Qt.NoPen), QBrush(tcol))
        accent.setPos(x, y)
        accent.setZValue(5.0)
        eff = QGraphicsDropShadowEffect()
        eff.setBlurRadius(11)
        eff.setColor(shadow_col)
        eff.setOffset(0, 2)
        accent.setGraphicsEffect(eff)

        body = self.scene.addPath(
            self._rounded_path(AW, 0, W - AW, H, R, tl=False, tr=True, br=True, bl=False),
            QPen(Qt.NoPen), QBrush(fill_col))
        body.setPos(x, y)
        body.setZValue(5.1)

        outline = self.scene.addPath(self._rounded_path(0, 0, W, H, R),
                                     QPen(border_col, 1.3))
        outline.setPos(x, y)
        outline.setZValue(5.2)
        outline.setToolTip(
            f"{name}  #{idx}  [{SKILL_TYPES.get(tv, '')}]\n"
            f"学习状态值: {self._states.get(idx, 0)}")

        name_t = self.scene.addSimpleText(name)
        nf = name_t.font()
        nf.setPointSize(11)
        nf.setBold(True)
        name_t.setFont(nf)
        name_t.setBrush(QBrush(name_col))
        nb = name_t.boundingRect()
        name_t.setPos(x + AW + (W - AW - nb.width()) / 2, y + 11)
        name_t.setZValue(6)

        sub_t = self.scene.addSimpleText(f"#{idx} · {SKILL_TYPES.get(tv, tv)}")
        sf = sub_t.font()
        sf.setPointSize(8)
        sub_t.setFont(sf)
        sub_t.setBrush(QBrush(sub_col))
        sbb = sub_t.boundingRect()
        sub_t.setPos(x + AW + (W - AW - sbb.width()) / 2, y + 34)
        sub_t.setZValue(6)

        self._draw_state_badge(idx, x, y)

    def _draw_state_badge(self, idx, x, y):
        label, col = self._state_badge(self._states.get(idx, 0))
        txt = self.scene.addSimpleText(label)
        f = txt.font()
        f.setPointSize(7)
        f.setBold(True)
        txt.setFont(f)
        br = txt.boundingRect()
        cw, ch = br.width() + 13, br.height() + 5
        cx, cy = x + self.NODE_W - cw - 8, y - ch / 2.0
        chip = self.scene.addPath(self._rounded_path(0, 0, cw, ch, ch / 2.0),
                                  QPen(col.darker(125), 1.1), QBrush(col))
        chip.setPos(cx, cy)
        chip.setZValue(7)
        txt.setBrush(QBrush(QColor("#ffffff")))
        txt.setPos(cx + (cw - br.width()) / 2.0, cy + (ch - br.height()) / 2.0)
        txt.setZValue(8)

    # ── 渲染 ──

    def _render(self):
        self.scene.clear()
        nodes = set(self._states.keys())
        if not nodes:
            return
        edges = self._build_edges(nodes)
        rank = self._compute_ranks(nodes, edges)
        pos = self._layout(nodes, rank)
        for (a, b, w) in edges:
            self._draw_edge(pos[a], pos[b], w)
        for n in nodes:
            self._draw_node(n, pos[n])
        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def _fit(self):
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if not rect.isEmpty():
            self.view.fitInView(rect, Qt.KeepAspectRatio)
            # 单节点时避免过度放大
            if self.view.transform().m11() > 1.4:
                self.view.resetTransform()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self._fit()
