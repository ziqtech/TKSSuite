# -*- coding: utf-8 -*-
"""tks_book 人物标签页 — 头像/名称/核心属性/装备/技能/可学习技能树/历史文本"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QVBoxLayout, QWidget, QFrame, QTreeWidget,
    QTreeWidgetItem, QCheckBox, QGridLayout, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton,
)

from book_loader import (
    EQUIP_ID_IDX, EQUIP_SKILL_IDX,
    PASSIVE_SKILL_IDX, SKILL_LEARN_BASE, SKILL_LEARN_COUNT,
    SKILL_TYPES, get_packed_byte, pil_to_qpixmap, use_right_label,
    SPECIAL_FLAG_NAMES, flag_names,
)
from editor_utils.ui_helpers import EditorComboBox
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.jvg_loader import get_sprite_pixmap
from editor_utils.flow_layout import FlowLayout
from editor_utils.picker_dialogs import STATUS_NAMES, STATUS_ICON_BASE, GrowthTableDialog
from editor_utils.adaptive_table import AdaptiveTableWidget
from book_skill_graph import CharSkillGraph
from tab_common import BookTabBase


class CharTab(BookTabBase):
    """人物查看页: 左侧角色列表, 右侧详情"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._fa_pix_cache = {}
        self._icon_cache = {}
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
            ["", "#", "角色名称", "等级", "状态", "HP", "MP"], rows,
            widths={0: 50, 1: 44, 3: 58, 4: 70, 5: 78, 6: 78},
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
        self._cur_detail_rec = rec
        f = rec['fields']
        self.clear_detail()

        # 头部: 头像 + 名称/等级 + 核心属性
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
        name_box.setSpacing(4)
        # 名称 + 成长数据按钮 (左右布局)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_lbl = QLabel(self.data.char_name(rec))
        name_lbl.setProperty("class", "PreviewName")
        name_row.addWidget(name_lbl)
        name_row.addStretch()
        btn_growth = QPushButton("成长数据")
        btn_growth.setProperty("class", "CompactBtn")
        btn_growth.setToolTip("查看 1-60 级逐级成长数据表 (成长除数越小成长越快)")
        btn_growth.clicked.connect(lambda: self._show_growth_dialog(rec))
        name_row.addWidget(btn_growth)
        name_box.addLayout(name_row)
        # 语义色 class 定义 (颜色统一维护于 editor_themes 的 Book* 规则)
        blue, green, red, purple = "BookInfo", "BookOk", "BookBad", "BookSpecial"
        # 核心属性 (7列, 紧贴姓名下方): 前5个蓝色, 后9个绿色
        blue_pairs = [
            ("等级", str(f[2])), ("生命", f"{f[5]}/{f[8]}"), ("内力", f"{f[6]}/{f[10]}"),
            ("经验", str(f[4])), ("升级", str(f[7])),
        ]
        green_pairs = [
            ("攻击", str(f[12])), ("防御", str(f[14])),
            ("命中", str(f[16])), ("闪避", str(f[18])),
            ("速度", str(f[20])), ("幸运", str(f[22])),
            ("悟性", str(f[26])), ("移动", str(f[24])),
            ("技能点数", str(f[31])),
        ]
        stat_pairs = blue_pairs + green_pairs
        stat_colors = [blue] * len(blue_pairs) + [green] * len(green_pairs)
        stat_grid = QGridLayout()
        stat_grid.setHorizontalSpacing(10)
        stat_grid.setVerticalSpacing(4)
        cols = 7
        for i, ((label, val), color) in enumerate(zip(stat_pairs, stat_colors)):
            r, c = divmod(i, cols)
            lbl = QLabel(label)
            lbl.setProperty("class", color)
            val_lbl = QLabel(val)
            val_lbl.setProperty("class", color)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lbl)
            cell.addWidget(val_lbl, 1)
            stat_grid.addLayout(cell, r, c)
        for c in range(cols):
            stat_grid.setColumnStretch(c, 1)
        name_box.addLayout(stat_grid)
        # 五维属性 + 成长除数 (智慧/仁德/勇气/医术 红色, 成长除数初/中/后期 紫色, 7列对齐)
        virtue_extra = [
            ("智慧", str(f[27]), red), ("仁德", str(f[28]), red),
            ("勇气", str(f[29]), red), ("医术", str(f[30]), red),
            ("初期除数", str(f[264]), purple), ("中期除数", str(f[265]), purple),
            ("后期除数", str(f[266]), purple),
        ]
        virtue_grid = QGridLayout()
        virtue_grid.setHorizontalSpacing(10)
        virtue_grid.setVerticalSpacing(4)
        vcols = 7
        for i, (label, val, color) in enumerate(virtue_extra):
            lbl = QLabel(label)
            lbl.setProperty("class", color)
            val_lbl = QLabel(val)
            val_lbl.setProperty("class", color)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lbl)
            cell.addWidget(val_lbl, 1)
            virtue_grid.addLayout(cell, 0, i)
        for c in range(len(virtue_extra), vcols):
            spacer = QWidget()
            spacer.setObjectName("TransparentBg")
            virtue_grid.addWidget(spacer, 0, c)
        for c in range(vcols):
            virtue_grid.setColumnStretch(c, 1)
        name_box.addLayout(virtue_grid)
        name_box.addStretch()
        top_row.addLayout(name_box, 1)
        hv.addLayout(top_row)
        # 人物说明 (去除原数据换行, 单行流式)
        history = self.data.char_history(rec)
        if history:
            hist_lbl = QLabel(" ".join(history.split()))
            hist_lbl.setProperty("class", "PreviewDesc")
            hist_lbl.setWordWrap(True)
            hist_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            hist_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hv.addWidget(hist_lbl)
        self.detail_layout.addWidget(header)

        # 装备物品 (参考warpc_editor: 独立分组, 6列等宽, 标签在上值在下, 值自动换行, 末2列空白占位保列宽)
        body = self.add_group("装备物品")
        equip_grid = QGridLayout()
        equip_grid.setHorizontalSpacing(8)
        equip_grid.setVerticalSpacing(4)
        equip_labels = ["武器", "防具", "饰品", "饰品"]
        for slot, fi in enumerate(EQUIP_ID_IDX):
            iid = f[fi]
            cell_w = QWidget()
            cell_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell = QVBoxLayout(cell_w)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            lbl = QLabel(equip_labels[slot])
            lbl.setProperty("class", "PropLabel")
            lbl.setAlignment(Qt.AlignLeft)
            cell.addWidget(lbl)
            if iid > 0:
                name = (self.data.item_name_by_id(iid) or f"物品ID#{iid}").strip()
                val_lbl = self._val_label(name, True)
            else:
                val_lbl = self._val_label("(未装备)", False)
            cell.addWidget(val_lbl, 1)
            equip_grid.addWidget(cell_w, 0, slot, Qt.AlignTop)
        # 末2列空白占位, 防止列宽不均 (同warpc_editor _build_section)
        for c in range(len(EQUIP_ID_IDX), 6):
            spacer = QWidget()
            equip_grid.addWidget(spacer, 0, c)
        for c in range(6):
            equip_grid.setColumnStretch(c, 1)
        body.addLayout(equip_grid)

        # 装备技能 (参考warpc_editor: 独立分组, 6列等宽, 标签在上值在下, 值自动换行)
        body = self.add_group("装备技能")
        skill_grid = QGridLayout()
        skill_grid.setHorizontalSpacing(8)
        skill_grid.setVerticalSpacing(4)
        skill_labels = ["指令技能", "指令技能", "主动技能", "主动技能", "被动技能", "移动技能"]
        all_slots = list(zip(skill_labels, list(EQUIP_SKILL_IDX) + list(PASSIVE_SKILL_IDX)))
        for slot, (label, fi) in enumerate(all_slots):
            sid = f[fi]
            cell_w = QWidget()
            cell_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell = QVBoxLayout(cell_w)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setAlignment(Qt.AlignLeft)
            cell.addWidget(lbl)
            if sid > 0:
                val_lbl = self._val_label(self._skill_label(sid), True)
            else:
                val_lbl = self._val_label("(未装备)", False)
            cell.addWidget(val_lbl, 1)
            skill_grid.addWidget(cell_w, 0, slot, Qt.AlignTop)
        for c in range(6):
            skill_grid.setColumnStretch(c, 1)
        body.addLayout(skill_grid)

        # 入队信息
        body = self.add_group("入队信息")
        self._build_join_info(body, rec)

        # 可掉落物品 + 战后奖励 (水平并排)
        drop_body, reward_body = self.add_group_pair("可掉落物品", "战后奖励")
        self._build_drops(drop_body, rec)
        self._build_battle_rewards(reward_body, rec)

        # 物品装备权限 (f[77]-f[81], 位掩码)
        body = self.add_group("物品装备权限")
        self._build_use_rights(body, rec)

        # 技能加成 (f[32]-f[40], 来自装备/技能的加成)
        body = self.add_group("技能加成")
        self._build_skill_bonuses(body, rec)

        # 攻击导致状态 (f[67]/f[68], 位掩码)
        body = self.add_group("攻击导致状态")
        self._build_attack_status(body, rec)

        # 状态抵抗 (f[51]-f[66], 32字节打包, 每状态1字节=抵抗率%)
        body = self.add_group("状态抵抗")
        self._build_status_resist(body, rec)

        # 可学习技能
        states_all = self._learn_states(f)
        body = self.add_group("可学习技能", stretch=1)
        if states_all:
            states = self._filter_by_state(states_all)
            builder = self._build_learn_graph if self._graph_mode else self._build_learn_list
            tabs = self._build_type_tabs(self._states_by_type(states), builder)
            self._attach_corner(tabs)
            body.addWidget(tabs, 1)
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

        combo = EditorComboBox()
        combo.addItems(
            ["全部状态", "可学习", "待学习", "已学习", "技能组学会", "子技能学会"])
        combo.setToolTip("按学习状态筛选")
        if self._skill_filter:
            i = combo.findText(self._skill_filter)
            if i >= 0:
                combo.setCurrentIndex(i)
        # 不强制宽度: 角落区宽=sizeHint(含文本+箭头), 强制超宽会溢出被裁
        combo.setSizeAdjustPolicy(EditorComboBox.AdjustToContents)
        combo.currentIndexChanged.connect(
            lambda idx, c=combo: self._on_filter_changed(idx, c))  # 设值后再连
        h.addWidget(combo)

        tabs.setCornerWidget(box, Qt.TopRightCorner)
        th = tabs.tabBar().sizeHint().height()
        if th > 0:
            # 角落控件底部避开 Tab 线，保持附加内容略微上移。
            corner_h = max(20, th - 3)
            chk.setFixedHeight(corner_h)
            combo.setFixedHeight(corner_h)

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
        tabs = EditorTabWidget(
            flat=True,
            object_name="TksBookCharTabs",
        )
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
        graph = CharSkillGraph(self.data, theme_id=self._theme_id())
        graph.setMinimumHeight(360)
        graph.set_skills(states)
        return graph

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))

    def _theme_id(self):
        w = self.window()
        return str(getattr(w, '_theme_id', 'gpt-dark'))

    def _val_label(self, text, equipped=True):
        """创建装备/技能值标签: 无padding, 颜色适配主题"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignLeft)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setProperty("class", "BookOk" if equipped else "BookMuted")
        return lbl

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

    def _build_drops(self, body, rec):
        """可掉落物品: WarPC[270]/[271]/[272] 对应 100%/20%/5%"""
        f = rec['fields']
        slot_probs = [
            (f[270], "必掉 (100%)"),
            (f[271], "高概率 (20%)"),
            (f[272], "低概率 (5%)"),
        ]
        pairs = []
        for iid, prob in slot_probs:
            if iid <= 0:
                continue
            name = self.data.item_name_by_id(iid) or f"物品ID#{iid}"
            sprite_idx = None
            item_rec = self.data.item_by_id.get(iid)
            if item_rec is not None:
                sprite_idx = item_rec['vals'][4]
            pairs.append((prob, name.strip(), sprite_idx))
        if pairs:
            row = QHBoxLayout()
            row.setSpacing(8)
            for prob, name, sprite_idx in pairs:
                cell = QHBoxLayout()
                cell.setSpacing(3)
                lbl = QLabel(prob)
                lbl.setProperty("class", "PropLabel")
                cell.addWidget(lbl)
                if sprite_idx is not None:
                    icon_lbl = QLabel()
                    icon_lbl.setFixedSize(16, 16)
                    icon_lbl.setAlignment(Qt.AlignCenter)
                    pix = get_sprite_pixmap(self.data.mu_sprites, sprite_idx,
                                            (16, 16), self._icon_cache)
                    if pix:
                        icon_lbl.setPixmap(pix)
                    cell.addWidget(icon_lbl, 0, Qt.AlignVCenter)
                val_lbl = self._val_label(name, True)
                cell.addWidget(val_lbl, 1)
                row.addLayout(cell, 1)
            body.addLayout(row)
        else:
            self.add_text_block(body, "(无掉落物品配置)", "StatusHint")

    def _show_growth_dialog(self, rec):
        """打开成长数据表弹窗"""
        char_name = self.data.char_name(rec)
        dlg = GrowthTableDialog(self, rec, char_name, theme_id=self._theme_id())
        dlg.exec()

    def _build_battle_rewards(self, body, rec):
        """战后奖励: JP技能点数 + 金钱 (实际=基数×2)"""
        f = rec['fields']
        jp = f[268]
        gold_base = f[269]
        gold_actual = gold_base * 2
        pairs = [
            ("技能点", str(jp) if jp > 0 else "0"),
            ("金钱", f"{gold_actual} (×2={gold_base})" if gold_base > 0 else "0"),
        ]
        reward_color = "BookGold"
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, val in pairs:
            cell = QHBoxLayout()
            cell.setSpacing(3)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            val_lbl = QLabel(val)
            val_lbl.setProperty("class", reward_color)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            cell.addWidget(lbl)
            cell.addWidget(val_lbl, 1)
            row.addLayout(cell, 1)
        body.addLayout(row)

    def _build_use_rights(self, body, rec):
        """物品装备权限: 药品/道具/武器/防具/饰品 (f[77]-f[81], 位掩码) — 单行水平排列"""
        f = rec['fields']
        right_defs = [
            ("药品", f[77], 0),
            ("道具", f[78], 1),
            ("武器", f[79], 2),
            ("防具", f[80], 3),
            ("饰品", f[81], 4),
        ]
        right_color = "BookMeta"
        row = QHBoxLayout()
        row.setSpacing(10)
        for i, (label, val, page) in enumerate(right_defs):
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            text = use_right_label(val, page)
            val_lbl = QLabel(text)
            val_lbl.setProperty("class", right_color)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val_lbl.setWordWrap(True)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lbl)
            cell.addWidget(val_lbl, 1)
            row.addLayout(cell, 1)
        body.addLayout(row)

    def _build_skill_bonuses(self, body, rec):
        """技能加成区 f[32]-f[40]: 攻击次数/特殊标志/百分比加成/移动标志"""
        f = rec['fields']
        cyan, yellow = "BookMeta", "BookGold"
        atk_count = f[32]
        special_flag = f[33] & 0xFFFF
        mp_reduce = f[34]
        magic_def = f[35]
        exp_bonus = f[36]
        jp_bonus = f[37]
        move_flags = f[38] & 0xFFFF
        heal_move = f[39]
        mp_move = f[40]
        pairs = [
            ("攻击次数", f"+{atk_count - 1}" if atk_count > 1 else str(atk_count), yellow),
        ]
        sf_names = flag_names(special_flag, SPECIAL_FLAG_NAMES)
        pairs.append(("特殊能力", "、".join(sf_names) if sf_names else "(无)", cyan))
        for label, val in [("内耗减%", mp_reduce), ("法伤减%", magic_def),
                           ("经验+%", exp_bonus), ("技点+%", jp_bonus)]:
            pairs.append((label, f"{val}%" if val != 0 else "0%", cyan))
        mf_names = flag_names(move_flags, SPECIAL_FLAG_NAMES)
        pairs.append(("移动特效", "、".join(mf_names) if mf_names else "(无)", cyan))
        for label, val in [("移步回血%", heal_move), ("移步回气%", mp_move)]:
            pairs.append((label, f"{val}%" if val != 0 else "0%", cyan))
        cols = 5
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        # 计算标签固定宽度 (以最长标签"移步回血%"为基准)
        _tmpl = QLabel("移步回血%")
        _tmpl.setProperty("class", "PropLabel")
        lw = QFontMetrics(_tmpl.font()).horizontalAdvance("移步回血%") + 4
        for i, (label, val, color) in enumerate(pairs):
            r, c = divmod(i, cols)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setFixedWidth(lw)
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            val_lbl = QLabel(val)
            val_lbl.setProperty("class", color)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val_lbl.setWordWrap(True)
            val_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lbl)
            cell.addWidget(val_lbl, 1)
            grid.addLayout(cell, r, c)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        body.addLayout(grid)

    def _build_attack_status(self, body, rec):
        """攻击导致状态: f[67]=mask_lo(1-16), f[68]=mask_hi(17-32), 位掩码"""
        f = rec['fields']
        mask_lo = f[67] & 0xFFFF
        mask_hi = f[68] & 0xFFFF
        chips = self._build_status_chips(mask_lo, hi=False, is_cause=True)
        chips += self._build_status_chips(mask_hi, hi=True, is_cause=True)
        if chips:
            body.addWidget(self._make_chips_widget(chips))
        else:
            self.add_text_block(body, "(无攻击附加状态)", "StatusHint")

    def _build_status_resist(self, body, rec):
        """状态抵抗: f[51]-f[66] 32字节打包, 每字节=抵抗率% (0=无抵抗)"""
        f = rec['fields']
        STATUS_RESIST_BASE = 51
        chips = []
        for i in range(32):
            val = get_packed_byte(f, STATUS_RESIST_BASE, i)
            if val <= 0:
                continue
            if i < len(STATUS_NAMES):
                name = STATUS_NAMES[i]
                sprite_idx = STATUS_ICON_BASE + i - 130
                chips.append((f"{name} {val}%", sprite_idx, "StatusRemove"))
        if chips:
            body.addWidget(self._make_chips_widget(chips))
        else:
            self.add_text_block(body, "(无状态抵抗)", "StatusHint")

    def _build_status_chips(self, mask, hi=False, is_cause=True):
        """构建状态图标chips数据: [(name, sprite_idx, css_class), ...]"""
        chips = []
        base = 16 if hi else 0
        css_class = "StatusInflict" if is_cause else "StatusRemove"
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

    # ── 辅助 ──

    def _skill_label(self, sid):
        return (self.data.skill_name(sid) or f"技能#{sid}").strip()

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
        """可学习技能纯列表: 每个状态>0 的技能一行, 显示名称/效果判定/类型/状态"""
        if not states:
            return None

        skill_by_idx = {r['index']: r for r in self.data.skill_recs}
        items = [(si, skill_by_idx.get(si)) for si in sorted(states)]
        n = len(items)

        table = AdaptiveTableWidget(
            n, 4,
            stretch_columns={0, 1},
            minimum_widths=[80, 100, 90, 60],
        )
        table.setHorizontalHeaderLabels(["技能", "效果判定", "类型", "状态"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)

        # 获取当前角色记录 (用于效果判定查询)
        rec = getattr(self, '_cur_detail_rec', None)
        for row, (si, _skrec) in enumerate(items):
            name = self.data.skill_name(si) or f"技能#{si}"
            tname = SKILL_TYPES.get(_skrec['vals'][2], "") if _skrec else ""
            state_text = self._learn_state_text(states[si])
            effect = self.data.skill_effect_judgment(rec, si) if rec else ""
            for col, txt in enumerate((name, effect, tname, state_text)):
                it = QTableWidgetItem(txt)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, col, it)

        # 垂直扩展填满可用空间 (最大化窗口时表格随之变高)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return table
