# -*- coding: utf-8 -*-
"""tks_book 地图标签页 — 场景名称列表 + 背景层预览 + 实体标注。

标注规则:
  #0 大地图: type 15 事件触发区 (黄色菱形)
  各地图:    特殊物品来源位置 (Attribute(-1,11,N) 关联实体, 坐标 TKMat d10/d11)
             文王卦籤=红色 ● / 晶礦=蓝色 ● / 機關圖=绿色 ●, 带数量;
             未启用来源 (d2 bit0=0) 画虚线空心圆。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QPixmap,
                           QPainterPath)
from PySide6.QtWidgets import QLabel, QApplication, QWidget, QVBoxLayout

from book_loader import pil_to_qpixmap
from tab_common import BookTabBase
from editor_utils.task_runner import run_background, is_running

# 特殊物品颜色: 已知物品名固定配色, 其它物品从调色板按出现顺序分配
# 地图标记色 — 领域常量 (阶段 2 豁免: 主题无关)
_KNOWN_ITEM_COLORS = {'文王卦籤': '#e53935',   # 红
                      '晶礦':     '#1e88e5',   # 蓝
                      '機關圖':   '#43a047'}   # 绿
_PALETTE = ['#e53935', '#1e88e5', '#43a047', '#fb8c00', '#8e24aa', '#00acc1']
_TRIGGER_COLOR = '#ffd54f'   # type 15 事件触发区 (黄)


class MapTab(BookTabBase):
    """地图查看页: 左侧场景列表 (同 TKMat 编辑器场景列表), 右侧背景预览+标注"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._pix_cache = {}       # sid → 背景 QPixmap (无标注)
        self._overlay_cache = {}   # sid → 叠加标注后的 QPixmap
        self._populated = False
        self._item_colors = {}     # 特殊物品ID → 颜色
        # 右侧预览: 图片标签 + 图例说明 (滚动区已由基类提供)
        self.detail_scroll.setWidgetResizable(False)
        self._detail_w = QWidget()
        vl = QVBoxLayout(self._detail_w)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)
        self._preview_lbl = QLabel("请从左侧选择地图")
        self._preview_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._legend_lbl = QLabel("")
        self._legend_lbl.setProperty("class", "PreviewDesc")
        self._legend_lbl.setWordWrap(True)
        self._legend_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vl.addWidget(self._preview_lbl, 0, Qt.AlignTop | Qt.AlignLeft)
        vl.addWidget(self._legend_lbl)
        vl.addStretch()
        self.detail_scroll.setWidget(self._detail_w)

    def populate(self):
        """惰性: SC.GRP 较大, 首次切到本页时才加载 (见 ensure_populated)"""
        self._populated = False
        self._pix_cache.clear()
        self._overlay_cache.clear()
        self._build_item_colors()
        self.set_table_items(["#", "场景", "特殊物品"], [],
                             widths={0: 50, 2: 80}, stretch_col=1)
        self._preview_lbl.setText("请从左侧选择地图")
        self._preview_lbl.adjustSize()
        self._legend_lbl.setText("")

    def _build_item_colors(self):
        """为每种特殊物品分配颜色: 已知名称固定配色, 其余按调色板顺序"""
        self._item_colors = {}
        used = set()
        for e in getattr(self.data, 'special_items', None) or []:
            for id_min, *_ in e['items']:
                if id_min in self._item_colors:
                    continue
                name = self.data.item_name_by_id(id_min)
                color = _KNOWN_ITEM_COLORS.get(name)
                if color is None:
                    color = next((c for c in _PALETTE if c not in used),
                                 _PALETTE[0])
                self._item_colors[id_min] = color
                used.add(color)

    def ensure_populated(self):
        if self._populated:
            return
        self._populated = True
        self._preview_lbl.setText("正在加载 SC.GRP…")
        self._preview_lbl.adjustSize()

        # 后台线程: SC.GRP 惰性加载/解码 (P3-3), 表格填充在回调
        def work(w):
            grp = self.data.sc_grp()
            # 场景 → 特殊物品有效总数 (Attribute(-1,11,N) 启用来源增量合计)
            spec_tot = {}
            for e in getattr(self.data, 'special_items', None) or []:
                if e.get('enabled', True):
                    spec_tot[e['scene']] = spec_tot.get(e['scene'], 0) + e['delta']
            rows = []
            if grp is not None:
                for sec in grp.sections:
                    if sec.width <= 0 or sec.height <= 0:
                        continue
                    sid = sec.index
                    rows.append((sid, [str(sid), self.data.scene_name(sid),
                                       str(spec_tot.get(sid, 0))]))
            return rows

        self._grp_worker = run_background(
            self, work, on_success=self._on_grp_loaded)

    def _on_grp_loaded(self, rows):
        self.set_table_items(["#", "场景", "特殊物品"], rows,
                             widths={0: 50, 2: 80}, stretch_col=1)
        if rows:
            self._preview_lbl.setText("请从左侧选择地图")
        else:
            self._preview_lbl.setText("未找到 SC.GRP / SC.IDX, 无法预览地图")
        self._preview_lbl.adjustSize()

    def show_detail(self, sid):
        pix = self._pix_cache.get(sid)
        if pix is None:
            if is_running(getattr(self, '_scene_worker', None)):
                return
            self._preview_lbl.setText(f"正在解码场景 {sid}…")
            self._preview_lbl.adjustSize()

            # 后台线程: 场景底图解码 (P3-3), 缓存与上屏在回调
            def work(w):
                return sid, pil_to_qpixmap(self.data.scene_background(sid))

            self._scene_worker = run_background(
                self, work,
                on_success=self._on_scene_decoded)
            return
        if pix is None:
            self._preview_lbl.setText(f"场景 {sid} 无背景图")
            self._legend_lbl.setText("")
        else:
            full = self._overlay_cache.get(sid)
            if full is None:
                full = self._compose(sid, pix)
                self._overlay_cache[sid] = full
            self._preview_lbl.setPixmap(full)
            self._legend_lbl.setText(self._legend_html(sid))
            self._preview_lbl.setToolTip(
                f"{self.data.scene_name(sid)}  ({pix.width()}×{pix.height()})")
            self._preview_lbl.adjustSize()
            self._detail_w.adjustSize()

    def _on_scene_decoded(self, result):
        sid, pix = result
        if pix is None:
            # 负缓存: 无背景图的场景不再反复解码
            self._pix_cache[sid] = None
            self._preview_lbl.setText(f"场景 {sid} 无背景图")
            self._legend_lbl.setText("")
            return
        self._pix_cache[sid] = pix
        full = self._overlay_cache.get(sid)
        if full is None:
            full = self._compose(sid, pix)
            self._overlay_cache[sid] = full
        self._preview_lbl.setPixmap(full)
        self._legend_lbl.setText(self._legend_html(sid))
        self._preview_lbl.setToolTip(
            f"{self.data.scene_name(sid)}  ({pix.width()}×{pix.height()})")
        self._preview_lbl.adjustSize()
        self._detail_w.adjustSize()

    # ── 标注渲染 ──

    def _scene_marks(self, sid):
        """场景 sid 的标注数据: (特殊物品源合并表, type15触发区列表)

        特殊物品源按 (物品ID, 坐标) 合并累计数量;
        type15 触发区仅在 #0 大地图标注。
        """
        ents = getattr(self.data, 'mat_entities', None) or {}
        spots = {}     # (iid, x, y) → {'qty', 'enabled'}
        for e in getattr(self.data, 'special_items', None) or []:
            if e['scene'] != sid:
                continue
            men = ents.get(e['entity_id'])
            if men is None or not e['items']:
                continue
            iid = e['items'][0][0]
            key = (iid, men['x'], men['y'])
            s = spots.setdefault(key, {'qty': 0, 'enabled': True})
            s['qty'] += e['delta']
            s['enabled'] = s['enabled'] and e.get('enabled', True)
        trigs = []
        if sid == 0:
            trigs = [en for en in ents.values()
                     if en['scene'] == sid and en['type'] == 15]
        return spots, trigs

    def _compose(self, sid, base):
        """在背景 QPixmap 上叠加特殊物品/type15 标注, 返回新 QPixmap

        数量文字钳制在地图范围内 (不出界); type15 按碰撞盒
        d18/d19 左上角 + d20/d21 宽高 画实际有效范围矩形
        (同 mat_editor 可视化渲染)。
        """
        if not self._item_colors:
            self._build_item_colors()
        spots, trigs = self._scene_marks(sid)
        if not spots and not trigs:
            return base
        pix = QPixmap(base)
        W, H = pix.width(), pix.height()
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(15)
        p.setFont(font)
        fm = p.fontMetrics()

        # 特殊物品来源: 实心圆 (启用) / 虚线空心圆 (未启用) + 数量
        for (iid, x, y), s in spots.items():
            color = QColor(self._item_colors.get(iid, _PALETTE[0]))
            if s['enabled']:
                p.setPen(QPen(QColor(255, 255, 255), 2))
                p.setBrush(QBrush(color))
            else:
                pen = QPen(color, 2)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(x - 8, y - 8, 16, 16)
            txt = f"×{s['qty']}"
            tw_px = fm.horizontalAdvance(txt)
            # 默认在圆点右上侧; 超出地图边界时翻转/钳制
            tx = x + 10
            if tx + tw_px > W:
                tx = x - 10 - tw_px          # 翻到左侧
                if tx < 0:
                    tx = 0                   # 仍放不下则贴边
            ty = y - 8
            if ty - fm.ascent() < 0:
                ty = y + 8 + fm.ascent()     # 顶部放不下则移到下方
            if ty + fm.descent() > H:
                ty = H - fm.descent()
            p.setPen(QColor(0, 0, 0))        # 黑色描边底字
            p.drawText(tx + 1, ty + 1, txt)
            p.setPen(QColor(255, 255, 255))
            p.drawText(tx, ty, txt)

        # type 15 事件触发区 (仅 #0 大地图): 碰撞盒矩形 = 实际有效范围
        for en in trigs:
            bx, by, bw, bh = en.get('box', (0, 0, 0, 0))
            p.setPen(QPen(QColor(_TRIGGER_COLOR), 2))
            fill = QColor(_TRIGGER_COLOR)
            fill.setAlpha(60)
            p.setBrush(QBrush(fill))
            if bw > 0 and bh > 0:
                p.drawRect(bx, by, bw, bh)
            else:
                # 无碰撞盒数据时退化为坐标点菱形
                x, y = en['x'], en['y']
                path = QPainterPath()
                path.moveTo(x, y - 9)
                path.lineTo(x + 9, y)
                path.lineTo(x, y + 9)
                path.lineTo(x - 9, y)
                path.closeSubpath()
                p.drawPath(path)

        p.end()
        return pix

    def _legend_html(self, sid):
        """图例: 本场景各特殊物品总量 + 触发区数量 (无标注返回空串)"""
        if not self._item_colors:
            self._build_item_colors()
        spots, trigs = self._scene_marks(sid)
        if not spots and not trigs:
            return ""
        totals = {}      # iid → [总数, 含未启用?]
        for (iid, _x, _y), s in spots.items():
            t = totals.setdefault(iid, [0, False])
            t[0] += s['qty']
            t[1] = t[1] or not s['enabled']
        parts = []
        for iid, (total, has_dis) in totals.items():
            name = self.data.item_name_by_id(iid) or f"物品#{iid}"
            c = self._item_colors.get(iid, _PALETTE[0])
            t = (f"<span style='color:{c}; font-size:14px;'>●</span> "
                 f"{name} ×{total}")
            if has_dis:
                t += " <span style='color:#999;'>(虚线=未启用)</span>"
            parts.append(t)
        if trigs:
            parts.append(
                f"<span style='color:{_TRIGGER_COLOR}; font-size:14px;'>▭</span> "
                f"事件触发区 ×{len(trigs)} (黄框=有效范围)")
        return "&nbsp;&nbsp;&nbsp;".join(parts)
