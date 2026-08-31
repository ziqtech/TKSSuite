# -*- coding: utf-8 -*-
"""tks_book 特殊物品标签页 — TKD 脚本 Attribute(-1,11,N) 收集度来源统计。

逆向依据:
  Attribute(-1,11,N) → sub_40E11C case11: word_757F00 += N (特殊物品收集度)
  游戏状态界面按 100*word_757F00/84 显示收集度% (sub_41A080)
  物品本体双轨制 (docs/mat_editor/Attribute与GetItem双轨物品系统分析.md):
    type110 机关实体 → TKMat d53-d64 三组物品 (sub_408B30 交互掉落)
    其它实体         → 同块脚本 GetItem 命令 (sub_40CE30)
  Attribute 本身只累加收集度计数器, 不直接入物品栏。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel, QFrame, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton,
)

from editor_utils.jvg_loader import get_sprite_pixmap

from book_loader import tkt_first_line
from tab_item import ItemTab, render_item_header

# TKMat 实体类型 (sub_405CBC 分支, 同 mat_editor ENTITY_TYPES)
_ENTITY_TYPE_NAMES = {5: "脚本对象", 10: "出入传送", 15: "触发区",
                      16: "战斗区", 20: "事件对象", 110: "特殊机关",
                      200: "NPC"}


class SpecialItemTab(ItemTab):
    """特殊物品查看页: 按物品去重合并的收集度统计表格 + 物品详情"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        # 本页自有聚合逻辑, 隐藏 ItemTab 继承来的物品分类筛选
        self._filter_lbl.hide()
        self._filter_page.hide()

    def _on_filter_changed(self, *_args):
        pass   # 本页不参与分类筛选 (避免误覆盖表格)

    def populate(self):
        self._icon_cache.clear()
        entries = getattr(self.data, 'special_items', []) or []
        # 按物品ID去重合并: item_id → {'delta': 总增量, 'active': 有效增量, 'entries': [...]}
        self._groups = {}
        order = []
        for e in entries:
            ids = set()
            for id_min, id_max, _q0, _q1, _src in e['items']:
                ids.update(range(id_min, min(id_max, id_min + 10) + 1))
            for iid in sorted(ids):
                g = self._groups.get(iid)
                if g is None:
                    self._groups[iid] = g = {'delta': 0, 'active': 0, 'entries': []}
                    order.append(iid)
                g['delta'] += e['delta']
                if e.get('enabled', True):
                    g['active'] += e['delta']
                g['entries'].append(e)
        rows = []
        for iid in order:
            g = self._groups[iid]
            rec = self.data.item_by_id.get(iid)
            if rec is not None:
                name = tkt_first_line(self.data.tkt, rec['vals'][2]) or f"物品#{iid}"
                icon = None
                pix = get_sprite_pixmap(self.data.mu_sprites, rec['vals'][4],
                                        (24, 24), self._icon_cache)
                if pix:
                    icon = QIcon(pix)
            else:
                name, icon = f"物品#{iid}", None
            rows.append((iid, [(name, icon), f"{g['active']:+d}"]))
        self.set_table_items(["物品名称", "数量"], rows,
                             widths={1: 60}, stretch_col=0)
        self.clear_detail()
        if not rows:
            self.add_text_block(
                self.detail_layout,
                "未在 TKD.dat 脚本中检索到 Attribute(-1,11,N) 命令。\n"
                "请先通过 文件 → 加载 TKS 目录 加载含 TKD.dat 的游戏目录。",
                "StatusHint")
        else:
            total = sum(e['delta'] for e in entries)
            n_dis = sum(1 for e in entries if not e.get('enabled', True))
            dis_txt = f", 其中 {n_dis} 处未启用 (列表数量已扣除)" if n_dis else ""
            self.add_text_block(
                self.detail_layout,
                f"共 {len(rows)} 种特殊物品 ({len(entries)} 处来源{dis_txt}), "
                f"有效收集度合计 {total - sum(e['delta'] for e in entries if not e.get('enabled', True)):+d}\n"
                "逆向依据: Attribute(-1,11,N) → word_757F00 += N "
                "(sub_40E11C case11), 游戏状态界面按 100×收集度/84 显示%。",
                "StatusHint")
        self.finish_detail()

    def show_detail(self, key):
        g = getattr(self, '_groups', {}).get(key)
        if g is None:
            return
        self.clear_detail()
        rec = self.data.item_by_id.get(key)
        name = (tkt_first_line(self.data.tkt, rec['vals'][2]) if rec else "") \
            or f"物品#{key}"

        # ── 物品概览 (置顶: 图标/名称/元信息/说明) ──
        if rec is not None:
            render_item_header(self, rec)

        # ── 收集度汇总: 有效总数 + 来源数 ──
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(6)
        title = QLabel(f"{name}  —  有效收集度合计 {g['active']:+d}")
        title.setProperty("class", "PreviewName")
        hv.addWidget(title)
        dis = [e for e in g['entries'] if not e.get('enabled', True)]
        meta_txt = f"共 {len(g['entries'])} 处获取来源"
        if dis:
            meta_txt += (f", 其中 {len(dis)} 处未启用 "
                         f"({sum(e['delta'] for e in dis):+d}, TKMat d2 bit0=0 初始不可交互)")
        meta = QLabel(meta_txt)
        meta.setProperty("class", "PreviewDesc")
        hv.addWidget(meta)
        self.detail_layout.addWidget(header)

        # ── 获取地点表格 (地图/实体/增量/来源/操作) ──
        body = self.add_group("获取地点")
        tw = QTableWidget()
        headers = ["地图", "实体", "增量", "来源", "操作"]
        tw.setColumnCount(len(headers))
        tw.setHorizontalHeaderLabels(headers)
        tw.verticalHeader().setVisible(False)
        # QTableWidget 的 QSS item min-height 不会改变默认行高；操作列
        # 放的是实际 QPushButton，必须显式给出足够的行高，否则按钮会
        # 被表格视口上下边界裁掉。
        tw.verticalHeader().setDefaultSectionSize(44)
        tw.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tw.setSelectionMode(QAbstractItemView.NoSelection)
        tw.setRowCount(len(g['entries']))
        for r, e in enumerate(g['entries']):
            tname = _ENTITY_TYPE_NAMES.get(e['type'],
                                           f"类型{e['type']}" if e['type'] is not None
                                           else "未知类型")
            src_txt = "/".join(sorted({s for *_u, s in e['items']})) or "仅计数"
            if not e.get('enabled', True):
                src_txt += " ★未启用"
            cells = [
                e['scene_text'],
                f"#{e['entity_id']} {tname}",
                f"{e['delta']:+d}",
                src_txt,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if e['comment']:
                    item.setToolTip(f"脚本注释: {e['comment']}")
                tw.setItem(r, c, item)
            # 操作列: 查看 → 跳转地图页打开对应场景
            btn = QPushButton("查看")
            btn.setProperty("class", "CompactBtn")
            btn.setToolTip("在地图标签页中打开此地图")
            sid = e['scene']
            if sid is None or sid < 0:
                btn.setEnabled(False)
            else:
                btn.clicked.connect(lambda _=False, s=sid: self._goto_map(s))
            tw.setCellWidget(r, 4, btn)
        header = tw.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        tw.setColumnWidth(1, 150)
        tw.setColumnWidth(2, 60)
        tw.setColumnWidth(3, 190)
        tw.setColumnWidth(4, 64)
        # 高度自适应行数, 避免表格内部滚动 (外层已是滚动区)
        row_h = tw.verticalHeader().defaultSectionSize()
        tw.setFixedHeight(tw.horizontalHeader().height() +
                          row_h * tw.rowCount() + 4)
        body.addWidget(tw)

        self.detail_layout.addStretch(1)

    # ── 跳转 ──

    def _goto_map(self, sid):
        """切换到地图标签页并打开指定场景"""
        win = self.window()
        tab_map = getattr(win, 'tab_map', None)
        tabs = getattr(win, 'tabs', None)
        if tab_map is None or tabs is None:
            return
        tabs.setCurrentWidget(tab_map)
        tab_map.ensure_populated()
        tw = tab_map.list_widget
        for r in range(tw.rowCount()):
            it = tw.item(r, 0)
            if it is not None and it.data(Qt.UserRole) == sid:
                tw.setCurrentCell(r, 0)
                tw.scrollToItem(tw.item(r, 0))
                break
        tab_map.show_detail(sid)   # 强制刷新预览 (同位置重复点击也生效)
