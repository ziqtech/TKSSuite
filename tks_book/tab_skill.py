# -*- coding: utf-8 -*-
"""tks_book 技能标签页 — 名称/类型/说明文本/有值属性 (零值不显示)"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
    QSizePolicy, QPushButton, QDialog, QMessageBox,
)

from editor_utils.jvg_loader import get_sprite_pixmap
from editor_utils.flow_layout import FlowLayout
from editor_utils.picker_dialogs import STATUS_NAMES, STATUS_ICON_BASE
from editor_utils.ui_helpers import themed_messagebox, EditorComboBox

from book_loader import (
    SKILL_VIEW_FIELDS, SKILL_TYPES, ATK_TYPES, SPECIAL_FLAG_NAMES,
    SKILL_LEARN_BASE, SKILL_LEARN_COUNT, get_packed_byte,
    tkt_first_line, tkt_full_text, flag_names,
)
from book_skill_graph import CharSkillGraph
from tab_common import BookTabBase


class SkillTab(BookTabBase):
    """技能查看页: 全部技能列表 + 名称/说明/非零属性"""

    _HEADERS = ["技能ID", "文本ID", "类型", "技能名称", "技能点数", "耗费内力"]
    _WIDTHS = {0: 66, 1: 72, 2: 88, 4: 82, 5: 84}

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}
        self._all_rows = []   # [(rec_index, cells, type), ...] 未筛选全量
        # 类型筛选 (同物品页分类筛选模式)
        self._filter_lbl = QLabel("类型")
        self._filter_lbl.setProperty("class", "PropLabel")
        self._filter_type = EditorComboBox()
        self._filter_type.addItems(
            ["全部类型"] + [SKILL_TYPES[i] for i in sorted(SKILL_TYPES)])
        self._filter_type.setToolTip("按技能类型筛选列表")
        self._filter_type.currentIndexChanged.connect(self._on_filter_changed)
        self._search_row_layout.addWidget(self._filter_lbl)
        self._search_row_layout.addWidget(self._filter_type)

    def populate(self):
        self._icon_cache.clear()
        self._all_rows = []
        for rec in self.data.skill_recs:
            vals = rec['vals']
            name = tkt_first_line(self.data.tkt, vals[0])
            if not name:
                continue  # 空槽不显示
            tname = SKILL_TYPES.get(vals[2], str(vals[2]))
            self._all_rows.append((rec['index'], [
                str(rec['index']), str(vals[0]), tname, name,
                str(vals[3]), str(vals[43]),
            ], vals[2]))
        self._on_filter_changed()

    def _on_filter_changed(self, *_args):
        """重建列表: 类型下拉 (0=全部, 其余=类型+1) + 基类文本搜索叠加"""
        sel = self._filter_type.currentIndex()
        rows = [(k, cells) for k, cells, t in self._all_rows
                if sel <= 0 or t == sel - 1]
        self.set_table_items(self._HEADERS, rows,
                             widths=self._WIDTHS, stretch_col=3)
        self.clear_detail()
        self.finish_detail()

    def show_detail(self, idx):
        rec = None
        for r in self.data.skill_recs:
            if r['index'] == idx:
                rec = r
                break
        if rec is None:
            return
        vals = rec['vals']
        self.clear_detail()

        # 头部: 名称 + 类型提示 + 说明文本 (PreviewFrame 风格)
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(8)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name = tkt_first_line(self.data.tkt, vals[0]) or f"技能#{idx}"
        # 名称行: 左侧名称 + 右侧技能树按钮 (左右布局)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        name_row.addWidget(name_lbl, 1, Qt.AlignVCenter)
        btn_tree = QPushButton("技能树")
        btn_tree.setProperty("class", "CompactBtn")
        btn_tree.setToolTip("弹窗查看此技能所在的技能树拓扑图")
        btn_tree.clicked.connect(lambda _=False, i=idx: self._show_skill_tree(i))
        name_row.addWidget(btn_tree, 0, Qt.AlignVCenter)
        name_box.addLayout(name_row)
        # 类型提示
        stype = vals[2]
        if stype in SKILL_TYPES:
            type_hints = {
                0: "指令技能: 技能组根节点, 含子技能列表",
                1: "主动技能: 百分比属性加成 → 角色战斗属性",
                2: "被动技能: 触发概率 → 角色反应系统",
                3: "移动技能: 特殊标志 + 移动能力 → 角色地图能力",
            }
            hint_lbl = QLabel(type_hints[stype])
            hint_lbl.setProperty("class", "PreviewDesc")
            name_box.addWidget(hint_lbl)
        hv.addLayout(name_box)
        # 说明文本 (放在 PreviewFrame 内部, PreviewDesc 样式, 去除原数据换行)
        desc = tkt_full_text(self.data.tkt, vals[1])
        if desc:
            desc_lbl = QLabel(" ".join(desc.split()))
            desc_lbl.setProperty("class", "PreviewDesc")
            desc_lbl.setWordWrap(True)
            desc_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            desc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hv.addWidget(desc_lbl)
        self.detail_layout.addWidget(header)

        # ── 属性 (零值不显示, 6列grid, mask类字段单独在状态免疫展示) ──
        body = self.add_group("属性")
        pairs = []
        for key, off, label, kind in SKILL_VIEW_FIELDS:
            if kind in ('mask_lo', 'mask_hi'):
                continue
            v = vals[off // 2]
            if v == 0:
                continue
            if kind == 'flags':
                names = flag_names(v, SPECIAL_FLAG_NAMES)
                pairs.append((label, "、".join(names) if names else str(v)))
            elif kind == 'atk_type':
                pairs.append((label, ATK_TYPES.get(v, str(v))))
            elif kind == 'pct':
                pairs.append((label, f"{v}%"))
            else:
                pairs.append((label, str(v)))
        # atk_type=0 (物理攻击) 是有效值但被零值过滤, 指令/主动技能补充显示
        if vals[46] == 0 and vals[2] in (0, 1):
            pairs.append(("攻击类型", ATK_TYPES[0]))
        if pairs:
            self._build_prop_grid(body, pairs, cols=6)
        else:
            self.add_text_block(body, "(无属性数值)", "StatusHint")

        # ── 状态免疫 (mask类字段用chips展示) ──
        body = self.add_group("状态免疫")
        immune_chips = []
        for key, off, label, kind in SKILL_VIEW_FIELDS:
            if kind not in ('mask_lo', 'mask_hi'):
                continue
            v = vals[off // 2]
            if v == 0:
                continue
            hi = kind == 'mask_hi'
            immune_chips += self._build_status_chips(v, hi=hi, is_immunity=True)
        if immune_chips:
            body.addWidget(self._make_chips_widget(immune_chips))
        else:
            self.add_text_block(body, "(无状态免疫)", "StatusHint")

        # ── 技能树关联 (8组 目标/进度) ──
        tree_pairs = []
        for pi in range(8):
            ref_skill = vals[4 + pi * 2]
            ref_type = vals[5 + pi * 2]
            if ref_skill <= 0 or ref_type == 0:
                continue
            ref_name = self.data.skill_name(ref_skill) or f"技能#{ref_skill}"
            tree_pairs.append(("目标技能", f"{ref_name}  (进度 +{ref_type})"))
        if tree_pairs:
            body = self.add_group("技能树关联")
            self._build_prop_grid(body, tree_pairs, cols=4)

        # ── 关联物品 (反向索引: 附加/装备学习/使用学习) ──
        # 技能#0 为默认空值: 物品关联字段 0=未设置, 不构成真实关联
        body = self.add_group("关联物品")
        if idx == 0:
            self.add_text_block(body,
                                "(技能#0 为默认空值, 物品关联字段 0=未设置)",
                                "StatusHint")
        else:
            related_items = []
            for irec in self.data.item_recs:
                ivals = irec['vals']
                iname = tkt_first_line(self.data.tkt, ivals[2])
                if not iname:
                    continue
                iid = ivals[0]
                if iid in (0, 1):
                    continue
                rels = []
                if ivals[21] == idx:
                    rels.append("附加技能")
                if ivals[22] == idx:
                    rels.append("装备后学习")
                if ivals[23] == idx:
                    rels.append("使用后学习1")
                if ivals[24] == idx:
                    rels.append("使用后学习2")
                if rels:
                    related_items.append(f"{iname}({'/'.join(rels)})")
            if related_items:
                self.add_text_block(body, "、".join(related_items))
            else:
                self.add_text_block(body, "(无物品关联此技能)", "StatusHint")

        # ── 可学习角色: 反向索引所有 warpc_recs 中学习状态 > 0 的角色 ──
        body = self.add_group("可学习角色")
        learners = []
        limit = min(SKILL_LEARN_COUNT, len(self.data.skill_recs) or SKILL_LEARN_COUNT)
        if idx < limit:
            for wrec in self.data.warpc_recs:
                wname = self.data.char_name(wrec)
                if not wname:
                    continue
                wf = wrec['fields']
                state = get_packed_byte(wf, SKILL_LEARN_BASE, idx)
                if state > 0:
                    learners.append(wname)
        if learners:
            self.add_text_block(body, "、".join(learners))
        else:
            self.add_text_block(body, "(无角色配置学习此技能)", "StatusHint")

        self.detail_layout.addStretch(1)

    # ── 技能树弹窗 ──

    def _skill_graph_adj(self):
        """构建有向引用图 (同 skill_editor_v2.SkillTreeDialog._build_graph):
        children: a→[(b,w)] 学会a后为b贡献w进度; parents: 反向。
        语义 (逆向 sub_41E248): A→B 表示 A 是 B 的前置, 箭头由前置指向解锁。
        """
        valid = {r['index'] for r in self.data.skill_recs}
        children, parents = {}, {}
        for rec in self.data.skill_recs:
            vals = rec['vals']
            a = rec['index']
            for g in range(8):
                b = vals[4 + 2 * g]
                w = vals[5 + 2 * g]
                if w == 0 or b <= 0 or b == a or b not in valid:
                    continue
                children.setdefault(a, []).append((b, w))
                parents.setdefault(b, []).append((a, w))
        return children, parents

    @staticmethod
    def _reach_chain(start, adj):
        """从 start 沿单方向 (parents/children) 的传递闭包可达集 (不含 start)"""
        seen = set()
        stack = [start]
        while stack:
            n = stack.pop()
            for m, _w in adj.get(n, []):
                if m != start and m not in seen:
                    seen.add(m)
                    stack.append(m)
        return seen

    def _collect_tree_nodes(self, idx):
        """此技能的技能链节点集 = 向上全部前置 + 向下全部解锁 + 自身
        (同 skill_editor_v2 拓扑图语义, 不含仅共享前置的兄弟分支)"""
        children, parents = self._skill_graph_adj()
        anc = self._reach_chain(idx, parents)
        desc = self._reach_chain(idx, children)
        return anc | desc | {idx}

    def _build_tree_dialog(self, idx):
        """构建技能树拓扑图对话框 (不 exec, 便于测试)"""
        nodes = self._collect_tree_nodes(idx)
        name = self.data.skill_name(idx) or f"技能#{idx}"
        dlg = QDialog(self.window())
        dlg.setWindowTitle(f"技能树 — {name} ({len(nodes)} 个节点)")
        dlg.resize(980, 660)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        graph = CharSkillGraph(self.data, is_dark=self._is_dark_theme(),
                               parent=dlg)
        # 无角色上下文: 学习状态统一置 0 (徽标显示为待学)
        graph.set_skills({n: 0 for n in nodes})
        lay.addWidget(graph, 1)
        return dlg

    def _show_skill_tree(self, idx):
        nodes = self._collect_tree_nodes(idx)
        if len(nodes) <= 1:
            name = self.data.skill_name(idx) or f"技能#{idx}"
            themed_messagebox(self, QMessageBox.Information, "技能树",
                              f"「{name}」没有技能树关联 "
                              f"(无前置/解锁的 ref_skill 边)。")
            return
        self._build_tree_dialog(idx).exec()

    # ── 布局辅助 ──

    def _build_prop_grid(self, body, pairs, cols=6):
        """构建属性网格: 标签在上值在下, 末列空白占位保列宽"""
        attr_grid = QGridLayout()
        attr_grid.setHorizontalSpacing(8)
        attr_grid.setVerticalSpacing(4)
        for slot, (label, val) in enumerate(pairs):
            r, c = divmod(slot, cols)
            cell_w = QWidget()
            cell_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell = QVBoxLayout(cell_w)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setAlignment(Qt.AlignLeft)
            cell.addWidget(lbl)
            val_lbl = self._val_label(val, True)
            cell.addWidget(val_lbl, 1)
            attr_grid.addWidget(cell_w, r, c, Qt.AlignTop)
        last_row_count = len(pairs) % cols
        if last_row_count != 0:
            last_row = len(pairs) // cols
            for c in range(last_row_count, cols):
                spacer = QWidget()
                attr_grid.addWidget(spacer, last_row, c)
        for c in range(cols):
            attr_grid.setColumnStretch(c, 1)
        body.addLayout(attr_grid)

    # ── 辅助 ──

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))

    def _val_label(self, text, equipped=True):
        """创建属性值标签: 无padding, 颜色适配主题"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignLeft)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setProperty("class", "BookOk" if equipped else "BookMuted")
        return lbl

    def _build_status_chips(self, mask, hi=False, is_immunity=True):
        """构建状态图标chips数据: [(name, sprite_idx, css_class), ...]"""
        chips = []
        base = 16 if hi else 0
        css_class = "StatusRemove" if is_immunity else "StatusInflict"
        for bit in range(16):
            if mask & (1 << bit):
                idx = base + bit
                if idx < len(STATUS_NAMES):
                    sprite_idx = STATUS_ICON_BASE + idx - 130
                    chips.append((STATUS_NAMES[idx], sprite_idx, css_class))
        return chips

    def _make_chips_widget(self, chips):
        """创建状态chips容器: FlowLayout中横向排列, 图标16x16+名称"""
        w = QWidget()
        flow = FlowLayout(w, margin=0, spacing=3)
        for name, sprite_idx, css_class in chips:
            chip = QWidget()
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(1, 0, 3, 0)
            cl.setSpacing(2)
            il = QLabel()
            il.setFixedSize(16, 16)
            il.setAlignment(Qt.AlignCenter)
            pix = get_sprite_pixmap(self.data.mu_sprites, sprite_idx, (16, 16),
                                   self._icon_cache)
            if pix:
                il.setPixmap(pix)
            cl.addWidget(il, 0, Qt.AlignVCenter)
            nl = QLabel(name)
            nl.setProperty("class", css_class)
            nl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(nl, 0, Qt.AlignVCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            flow.addWidget(chip)
        return w
