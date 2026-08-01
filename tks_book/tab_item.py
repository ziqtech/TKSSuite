# -*- coding: utf-8 -*-
"""tks_book 物品标签页 — 图标/名称/说明文本/有值属性 (零值不显示)"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout, QWidget,
    QSizePolicy,
)

from editor_utils.jvg_loader import get_sprite_pixmap
from editor_utils.flow_layout import FlowLayout
from editor_utils.picker_dialogs import STATUS_NAMES, STATUS_ICON_BASE

from book_loader import (
    ITEM_VIEW_FIELDS, PAGE_NAMES, COMBAT_FLAG_NAMES, EXTRA_FLAG_NAMES,
    EQUIP_ID_IDX,
    tkt_first_line, tkt_full_text, status_mask_names, flag_names, val1000_text,
    use_right_label,
)
from tab_common import BookTabBase


class ItemTab(BookTabBase):
    """物品查看页: 全部物品列表 + 名称/说明/非零属性"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}

    def populate(self):
        self._icon_cache.clear()
        rows = []
        for rec in self.data.item_recs:
            vals = rec['vals']
            # 空槽判定与 item_editor.is_empty_item 一致
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            name = tkt_first_line(self.data.tkt, vals[2])
            if not name:
                continue
            page = vals[1]
            icon = None
            pix = get_sprite_pixmap(self.data.mu_sprites, vals[4], (24, 24),
                                    self._icon_cache)
            if pix:
                icon = QIcon(pix)
            rows.append((rec['index'], [
                ("", icon), str(rec['index']), str(vals[0]),
                PAGE_NAMES.get(page, "?"), name,
                use_right_label(vals[5], page), str(vals[31]),
            ]))
        self.set_table_items(
            ["图标", "#", "ID", "分类", "物品名称", "权限", "价格"], rows,
            widths={0: 40, 1: 40, 2: 50, 3: 50, 5: 80, 6: 50},
            stretch_col=4)
        self.clear_detail()
        self.finish_detail()

    def show_detail(self, idx):
        rec = None
        for r in self.data.item_recs:
            if r['index'] == idx:
                rec = r
                break
        if rec is None:
            return
        vals = rec['vals']
        self.clear_detail()

        dark = self._is_dark_theme()
        blue = "#6699cc" if dark else "#3366cc"
        green = "#55b572" if dark else "#178a39"
        cyan = "#7ab8d4" if dark else "#2a6f8c"

        # 头部: 图标 + 名称 + 元信息 + 说明文本
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        pix = get_sprite_pixmap(self.data.mu_sprites, vals[4], (48, 48),
                                self._icon_cache)
        if pix:
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setText("(无图标)")
        top_row.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl, 0, Qt.AlignVCenter)
        # 元信息行: 页面 | 权限 | 价格 | TKKon
        page = vals[1]
        meta_parts = [
            f"分类: {PAGE_NAMES.get(page, '?')}",
            f"权限: {use_right_label(vals[5], page)}",
            f"价格: {vals[31]}",
        ]
        if vals[6] > 0:
            tkkon_name = self.data.tkkon_names.get(vals[6], "")
            if tkkon_name:
                meta_parts.append(f"效果: {tkkon_name}")
            else:
                meta_parts.append(f"TKKon: {vals[6]}")
        meta_lbl = QLabel(" | ".join(meta_parts))
        meta_lbl.setStyleSheet(f"color: {cyan}; padding: 0px;")
        meta_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        name_box.addWidget(meta_lbl)
        name_box.addStretch()
        top_row.addLayout(name_box, 1)
        hv.addLayout(top_row)
        # 说明文本 (放在 PreviewFrame 内部, PreviewDesc 样式, 去除原数据换行)
        desc = tkt_full_text(self.data.tkt, vals[3])
        if desc:
            desc_lbl = QLabel(" ".join(desc.split()))
            desc_lbl.setProperty("class", "PreviewDesc")
            desc_lbl.setWordWrap(True)
            desc_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            desc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hv.addWidget(desc_lbl)
        self.detail_layout.addWidget(header)

        # ── 基础属性 (纯数值: HP/MP/攻防/命中/闪避/速度/幸运/悟性/移动/技能点) ──
        body = self.add_group("基础属性")
        stat_pairs = []
        field_map = {f[0]: f for f in ITEM_VIEW_FIELDS}
        stat_fields = [
            ("hp_inc", "增加生命", 'val1000'),
            ("hp_heal", "恢复生命", 'val1000'),
            ("mp_inc", "增加内力", 'val1000'),
            ("mp_heal", "恢复内力", 'val1000'),
            ("atk", "增加攻击", 'int'),
            ("def_", "增加防御", 'int'),
            ("hit", "增加命中", 'int'),
            ("dodge", "增加闪避", 'int'),
            ("spd", "增加速度", 'int'),
            ("luk", "增加幸运", 'int'),
            ("spi", "增加悟性", 'int'),
            ("vit", "增加移动", 'int'),
            ("jp_bonus", "增加技能点", 'int'),
            ("medicine", "增加医术", 'int'),
        ]
        for key, label, kind in stat_fields:
            if key in field_map:
                off = field_map[key][1]
                v = vals[off // 2]
                if v == 0:
                    continue
                if kind == 'val1000':
                    stat_pairs.append((label, val1000_text(v)))
                else:
                    stat_pairs.append((label, str(v)))
        if stat_pairs:
            self._build_prop_grid(body, stat_pairs, cols=6)
        else:
            self.add_text_block(body, "(无基础属性数值)", "StatusHint")

        # ── 技能效果 (4列: 附加技能/装备后学习/使用后学习1/2) ──
        body = self.add_group("技能效果")
        skill_fields = [
            ("attach_skill", "附加技能"),
            ("equip_learn", "装备后学习"),
            ("use_learn1", "使用后学习1"),
            ("use_learn2", "使用后学习2"),
        ]
        skill_pairs = []
        for key, label in skill_fields:
            if key in field_map:
                off = field_map[key][1]
                v = vals[off // 2]
                if v == 0:
                    skill_pairs.append((label, "(无)", False))
                else:
                    name_s = self.data.skill_name(abs(v)) or f"技能#{v}"
                    skill_pairs.append((label, name_s, True))
        self._build_skill_grid(body, skill_pairs)

        # ── 状态效果 ──
        # 导致状态 / 解除状态 (两个 DockHeader 一行并排, 标题不带括号)
        cause_body, cure_body = self.add_group_pair("导致状态", "解除状态")
        cause_chips = []
        cause_chips += self._build_status_chips(vals[26], hi=False, is_cause=True)
        cause_chips += self._build_status_chips(vals[27], hi=True, is_cause=True)
        if cause_chips:
            cause_body.addWidget(self._make_chips_widget(cause_chips))
        else:
            self.add_text_block(cause_body, "(无导致状态)", "StatusHint")
        cure_chips = []
        cure_chips += self._build_status_chips(vals[28], hi=False, is_cause=False)
        cure_chips += self._build_status_chips(vals[29], hi=True, is_cause=False)
        if cure_chips:
            cure_body.addWidget(self._make_chips_widget(cure_chips))
        else:
            self.add_text_block(cure_body, "(无解除状态)", "StatusHint")

        # ── 特殊效果 ──
        body = self.add_group("特殊效果")
        special_pairs = []
        combat_flag = vals[20]
        if combat_flag != 0:
            names = flag_names(combat_flag, COMBAT_FLAG_NAMES)
            special_pairs.append(("战斗结算", "、".join(names) if names else str(combat_flag)))
        extra_flags = vals[30]
        if extra_flags != 0:
            names = flag_names(extra_flags, EXTRA_FLAG_NAMES)
            special_pairs.append(("额外标志", "、".join(names) if names else str(extra_flags)))
        if special_pairs:
            self._build_prop_grid(body, special_pairs, cols=3, color=cyan)
        else:
            self.add_text_block(body, "(无特殊效果)", "StatusHint")

        # ── 初始装备角色 ──
        body = self.add_group("初始装备角色")
        equipped_by = []
        iid = vals[0]
        for wrec in self.data.warpc_recs:
            wname = self.data.char_name(wrec)
            if not wname:
                continue
            wf = wrec['fields']
            for slot, fi in enumerate(EQUIP_ID_IDX):
                if wf[fi] == iid:
                    slot_names = ["武器", "防具", "饰品", "饰品"]
                    equipped_by.append(f"{wname}({slot_names[slot]})")
                    break
        if equipped_by:
            self.add_text_block(body, "、".join(equipped_by))
        else:
            self.add_text_block(body, "(无角色初始装备此物品)", "StatusHint")

        # ── 获得途径 (TKD脚本/TKMat宝箱/TKShop商店/WarPC掉落/WarData战场宝物 反向索引) ──
        body = self.add_group("获得途径")
        sources = self.data.item_sources.get(vals[0], [])
        if sources:
            lines = []
            for kind, desc in sources:
                lines.append(f"【{kind}】{desc}")
            src_lbl = self.add_text_block(body, "\n".join(lines))
            src_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        else:
            hints = []
            if vals[1] == 5:
                hints.append("特殊/剧情物品 (页面5) — 不会出现在任何商店")
            hints.append("未在 商店/宝箱/剧情脚本/敌人掉落/战场宝物 中检索到来源"
                         " (可能为初始装备或未使用物品)")
            src_lbl = self.add_text_block(body, "\n".join(hints), "StatusHint")
            src_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.detail_layout.addStretch(1)

    # ── 布局辅助 ──

    def _build_prop_grid(self, body, pairs, cols=6, color=None):
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
            val_lbl = self._val_label(val, True, color=color)
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

    def _build_skill_grid(self, body, pairs):
        """构建技能效果网格: 4列等宽, 标签在上值在下"""
        cols = 4
        attr_grid = QGridLayout()
        attr_grid.setHorizontalSpacing(8)
        attr_grid.setVerticalSpacing(4)
        for slot, (label, val, has_val) in enumerate(pairs):
            cell_w = QWidget()
            cell_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cell = QVBoxLayout(cell_w)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setAlignment(Qt.AlignLeft)
            cell.addWidget(lbl)
            val_lbl = self._val_label(val, has_val)
            cell.addWidget(val_lbl, 1)
            attr_grid.addWidget(cell_w, 0, slot, Qt.AlignTop)
        for c in range(cols):
            attr_grid.setColumnStretch(c, 1)
        body.addLayout(attr_grid)

    # ── 辅助 ──

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))

    def _val_label(self, text, equipped=True, color=None):
        """创建属性值标签: 无padding, 颜色适配主题"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignLeft)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if color is None:
            green = "#55b572" if self._is_dark_theme() else "#178a39"
            gray = "#888" if self._is_dark_theme() else "#777"
            color = green if equipped else gray
        lbl.setStyleSheet(f"color: {color}; padding: 0px;")
        return lbl

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
