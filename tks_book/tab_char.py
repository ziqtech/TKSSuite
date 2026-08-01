# -*- coding: utf-8 -*-
"""tks_book 人物标签页 — 头像/名称/核心属性/装备/技能/可学习技能树/历史文本"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QVBoxLayout, QWidget, QFrame, QTreeWidget,
    QTreeWidgetItem, QTabWidget, QCheckBox,
)

from book_loader import (
    STAT_DEFS, CHAR_ATTR_DEFS, EQUIP_ID_IDX, EQUIP_SKILL_IDX,
    PASSIVE_SKILL_IDX, SKILL_LEARN_BASE, SKILL_LEARN_COUNT,
    SKILL_TYPES, get_packed_byte, pil_to_qpixmap,
)
from editor_utils.ui_helpers import NoWheelComboBox
from book_skill_graph import CharSkillGraph
from tab_common import BookTabBase


class CharTab(BookTabBase):
    """人物查看页: 左侧角色列表, 右侧详情"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._fa_pix_cache = {}
        self._skill_filter = None   # 可学习技能的学习状态筛选 (None=全部)
        self._graph_mode = False    # False=列表视图, True=拓扑图视图

    # ── 列表 ──

    def populate(self):
        self._fa_pix_cache.clear()
        rows = []
        for rec in self.data.warpc_recs:
            name = self.data.char_name(rec)
            if not name:
                continue  # 空槽不显示
            icon = None
            pix = self._fa_pixmap(rec['fields'][1] * 2 + 1, (24, 24))
            if pix:
                icon = QIcon(pix)
            f = rec['fields']
            hp = f"{f[5]}/{f[8]}" if (f[5] or f[8]) else ""
            mp = f"{f[6]}/{f[10]}" if (f[6] or f[10]) else ""
            role = f[3]
            role_str = ("未激活" if role == -1 else "已激活" if role == 0 else str(role))
            rows.append((rec['index'], [
                ("", icon), str(rec['index']), name,
                str(f[2]), role_str, hp, mp,
            ]))
        self.set_table_items(
            ["", "#", "角色名称", "等级", "身份", "HP", "MP"], rows,
            widths={0: 40, 1: 40, 3: 45, 4: 55, 5: 70, 6: 70},
            stretch_col=2)
        self.clear_detail()
        self.finish_detail()

    def _fa_pixmap(self, sprite_idx, size):
        key = (sprite_idx, size)
        if key in self._fa_pix_cache:
            return self._fa_pix_cache[key]
        sprites = self.data.fa_sprites
        pix = None
        if sprites and 0 <= sprite_idx < len(sprites) and sprites[sprite_idx] is not None:
            pix = pil_to_qpixmap(sprites[sprite_idx], size)
        self._fa_pix_cache[key] = pix
        return pix

    # ── 详情 ──

    def show_detail(self, idx):
        rec = None
        for r in self.data.warpc_recs:
            if r['index'] == idx:
                rec = r
                break
        if rec is None:
            return
        f = rec['fields']
        self.clear_detail()

        # 头部: 头像 + 名称/等级, 人物历史紧贴头像下方 (方便阅读)
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        portrait_lbl = QLabel()
        portrait_lbl.setFixedSize(96, 96)
        portrait_lbl.setAlignment(Qt.AlignCenter)
        pix = self._fa_pixmap(f[1] * 2, (96, 96))
        if pix:
            portrait_lbl.setPixmap(pix)
        else:
            portrait_lbl.setText("(无头像)")
        top_row.addWidget(portrait_lbl, 0, Qt.AlignTop)
        name_box = QVBoxLayout()
        name_lbl = QLabel(self.data.char_name(rec))
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl)
        meta_lbl = QLabel(f"等级 {f[2]}    升级所需经验 {f[4]}    记录 #{rec['index']}")
        meta_lbl.setProperty("class", "PreviewMeta")
        name_box.addWidget(meta_lbl)
        name_box.addStretch()
        top_row.addLayout(name_box, 1)
        hv.addLayout(top_row)
        history = self.data.char_history(rec)
        if history:
            hist_lbl = QLabel(history)
            hist_lbl.setProperty("class", "PreviewDesc")
            hist_lbl.setWordWrap(True)
            hist_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hv.addWidget(hist_lbl)
        self.detail_layout.addWidget(header)

        # 核心属性
        body = self.add_group("核心属性")
        pairs = [
            ("生命", f"{f[5]} / {f[8]}"),
            ("内力", f"{f[6]} / {f[10]}"),
        ]
        for label, base_i, cur_i in STAT_DEFS:
            base, cur = f[base_i], f[cur_i]
            pairs.append((label, f"{cur}" if cur == base else f"{cur} (基础 {base})"))
        for label, fi in CHAR_ATTR_DEFS:
            pairs.append((label, str(f[fi])))
        self.add_kv_grid(body, pairs, cols=3)

        # 装备物品
        body = self.add_group("装备物品")
        equips = []
        for slot, fi in enumerate(EQUIP_ID_IDX):
            iid = f[fi]
            if iid <= 0:
                continue
            name = self.data.item_name_by_id(iid) or f"物品ID#{iid}"
            equips.append((f"装备{slot + 1}", name))
        if equips:
            self.add_kv_grid(body, equips, cols=2)
        else:
            self.add_text_block(body, "(无装备)", "StatusHint")

        # 装备技能
        body = self.add_group("装备技能")
        skills = []
        for slot, fi in enumerate(EQUIP_SKILL_IDX):
            sid = f[fi]
            if sid > 0:
                skills.append((f"技能{slot + 1}", self._skill_label(sid)))
        for slot, fi in enumerate(PASSIVE_SKILL_IDX):
            sid = f[fi]
            if sid > 0:
                skills.append((f"被动{slot + 1}", self._skill_label(sid)))
        if skills:
            self.add_kv_grid(body, skills, cols=2)
        else:
            self.add_text_block(body, "(无装备技能)", "StatusHint")

        # 入队信息 (扫描 TKD 脚本 TeamMember 命令 + 前置条件)
        body = self.add_group("入队信息")
        self._build_join_info(body, rec)

        # 可学习技能 — 按技能类型 (指令/主动/被动/移动) 分标签页
        # 角落区: [拓扑图复选框] [学习状态下拉框]; 勾选拓扑图则内容由列表切换为拓扑图
        states_all = self._learn_states(f)
        body = self.add_group("可学习技能")
        if states_all:
            states = self._filter_by_state(states_all)
            builder = self._build_learn_graph if self._graph_mode else self._build_learn_list
            tabs = self._build_type_tabs(self._states_by_type(states), builder)
            self._attach_corner(tabs)
            body.addWidget(tabs)
        else:
            self.add_text_block(body, "(无已掌握或可学习的技能)", "StatusHint")

        self.finish_detail()

    # ── 可学习技能面板: 视图开关 (列表/拓扑图) + 学习状态筛选 ──

    def _attach_corner(self, tabs):
        """在类型标签页右侧角落挂 [拓扑图复选框] + [学习状态下拉框]"""
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        chk = QCheckBox("拓扑图")
        chk.setChecked(self._graph_mode)
        chk.setToolTip("勾选: 以技能树拓扑图显示; 取消: 列表显示")
        chk.toggled.connect(self._on_graph_toggled)
        h.addWidget(chk)

        combo = NoWheelComboBox()
        combo.addItems(
            ["全部状态", "可学习", "待学习", "已学习", "技能组学会", "子技能学会"])
        combo.setToolTip("按学习状态筛选")
        if self._skill_filter:
            i = combo.findText(self._skill_filter)
            if i >= 0:
                combo.setCurrentIndex(i)
        # 不强制宽度: 角落区宽=sizeHint(含文本+箭头), 强制超宽会溢出被裁
        combo.setSizeAdjustPolicy(NoWheelComboBox.AdjustToContents)
        combo.currentIndexChanged.connect(
            lambda idx, c=combo: self._on_filter_changed(idx, c))  # 设值后再连
        h.addWidget(combo)

        tabs.setCornerWidget(box, Qt.TopRightCorner)
        th = tabs.tabBar().sizeHint().height()
        if th > 0:
            chk.setFixedHeight(max(20, th - 2))
            combo.setFixedHeight(max(20, th - 2))

    def _on_graph_toggled(self, checked):
        self._graph_mode = checked
        self._rerender()

    def _on_filter_changed(self, index, combo):
        """筛选变更: index 0 = 全部 (不过滤)"""
        self._skill_filter = None if index <= 0 else combo.currentText()
        self._rerender()

    def _rerender(self):
        cur = self.list_widget.currentItem()
        if cur is not None:
            self.show_detail(cur.data(Qt.UserRole))

    def _filter_by_state(self, states):
        """按当前学习状态筛选 {idx: state}; 无筛选时原样返回"""
        if not self._skill_filter:
            return states
        return {si: st for si, st in states.items()
                if self._learn_state_text(st) == self._skill_filter}

    # ── 按技能类型分标签页 ──

    def _states_by_type(self, states):
        """{skill_idx: state} → {type(0-3): {idx: state}} (保留全部 4 类型键)"""
        by_idx = {r['index']: r for r in self.data.skill_recs}
        by_type = {0: {}, 1: {}, 2: {}, 3: {}}
        for si, st in states.items():
            rec = by_idx.get(si)
            tv = rec['vals'][2] if rec else 0
            by_type.setdefault(tv, {})[si] = st
        return by_type

    def _build_type_tabs(self, by_type, builder):
        """构建 指令/主动/被动/移动 四标签页; builder(type_states)→widget|None"""
        tabs = QTabWidget()
        for tv in (0, 1, 2, 3):
            tstates = by_type.get(tv, {})
            w = builder(tstates) if tstates else None
            if w is None:
                w = QLabel("(无此类可学习技能)")
                w.setProperty("class", "StatusHint")
                w.setAlignment(Qt.AlignCenter)
            tabs.addTab(w, f"{SKILL_TYPES[tv]} ({len(tstates)})")
        return tabs

    def _build_learn_graph(self, states):
        """单类型技能树拓扑图 (只读)。states 为空返回 None"""
        if not states:
            return None
        graph = CharSkillGraph(self.data, self._is_dark_theme())
        graph.setMinimumHeight(360)
        graph.set_skills(states)
        return graph

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))

    def _build_join_info(self, body, rec):
        """入队方式/条件: TeamMember 脚本事件 + 引擎硬性限制"""
        idx = rec['index']
        f = rec['fields']
        if idx == 0:
            self.add_text_block(body, "主角 — 初始队长 (队伍槽 0, 不可离队)")
            return

        lines = []
        joins = self.data.char_joins.get(idx, [])
        for ev in joins:
            parts = [f"📍 {ev['scene_text']}"]
            if ev['comment']:
                parts.append(f"「{ev['comment']}」")
            lines.append("  ".join(parts))
            if ev['conds']:
                for c in ev['conds']:
                    lines.append(f"     条件: {c}")
            else:
                lines.append("     条件: 无 (对话即可加入)")

        battles = self.data.enemy_battles.get(idx, [])
        if not joins:
            if battles:
                names = [self.data.battle_name(b) for b in battles[:4]]
                extra = f" 等{len(battles)}场" if len(battles) > 4 else ""
                lines.append("敌方角色 — 不可入队; 作为敌人出现于: "
                             + "、".join(names) + extra)
            else:
                lines.append("无入队脚本 — 原版剧情中不会加入队伍")

        # 引擎硬性限制 (逆向 sub_40DA00 / TeamMember补丁指南)
        limits = ["队伍上限 6 人 (槽0=主角), 满员时脚本入队会静默失败"]
        if idx > 30:
            limits.append(f"⚠ 角色ID {idx} > 30 — 原版引擎 TeamMember 上限 30, "
                          f"需启动器 TeamMember 补丁才能入队")
        role = f[3]
        limits.append("首次入队时初始化属性 (role=-1 未激活)" if role == -1
                      else "已激活 (role=0, 属性已初始化)")
        lines.append("引擎限制: " + "; ".join(limits))
        self.add_text_block(body, "\n".join(lines))

    # ── 辅助 ──

    def _skill_label(self, sid):
        name = self.data.skill_name(sid) or f"技能#{sid}"
        stype = None
        for rec in self.data.skill_recs:
            if rec['index'] == sid:
                stype = rec['vals'][2]
                break
        tname = SKILL_TYPES.get(stype, "")
        return f"{name} [{tname}]" if tname else name

    @staticmethod
    def _learn_state_text(v):
        """学习状态值 → 状态名 (区间语义同 warpc_editor)"""
        if 1 <= v <= 9:
            return "待学习"
        if 10 <= v <= 19:
            return "可学习"
        if 20 <= v <= 29:
            return "技能组学会"
        if 30 <= v <= 39:
            return "子技能学会"
        if v >= 40:
            return "已学习"
        return f"进度{v}"

    def _learn_states(self, fields):
        """角色可学习技能状态 {skill_idx: state(>0)} (不会的=0 不含在内)"""
        states = {}
        limit = min(SKILL_LEARN_COUNT, len(self.data.skill_recs) or SKILL_LEARN_COUNT)
        for si in range(limit):
            v = get_packed_byte(fields, SKILL_LEARN_BASE, si)
            if v > 0:
                states[si] = v
        return states

    def _build_learn_list(self, states):
        """可学习技能纯列表: 每个状态>0 的技能一行, 显示名称/类型/状态 (不挂子节点)"""
        if not states:
            return None

        skill_by_idx = {r['index']: r for r in self.data.skill_recs}
        tree = QTreeWidget()
        tree.setProperty("class", "CompactTree")  # 公共紧凑树样式 (同 mat_editor 场景列表)
        tree.setHeaderLabels(["技能", "类型", "状态"])
        tree.setColumnWidth(0, 220)
        tree.setColumnWidth(1, 80)
        tree.setRootIsDecorated(False)   # 纯列表: 无展开箭头/子节点缩进

        for si in sorted(states):
            rec = skill_by_idx.get(si)
            name = self.data.skill_name(si) or f"技能#{si}"
            tname = SKILL_TYPES.get(rec['vals'][2], "") if rec else ""
            tree.addTopLevelItem(
                QTreeWidgetItem([name, tname, self._learn_state_text(states[si])]))

        # 高度自适应内容 (在滚动区内展开显示, 避免嵌套滚动过深)
        row_h = tree.sizeHintForRow(0) if tree.topLevelItemCount() else 20
        n = tree.topLevelItemCount()
        tree.setFixedHeight(max(80, min(600, row_h * (n + 2))))
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return tree
