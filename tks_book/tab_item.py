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

        # 头部: 图标 + 名称 + 核心属性
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
        name_box.setSpacing(0)
        name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl, 0, Qt.AlignVCenter)
        top_row.addLayout(name_box, 1)
        hv.addLayout(top_row)
        # 说明文本 (同人物页: 放在 PreviewFrame 内部, PreviewDesc 样式, 去除原数据换行)
        desc = tkt_full_text(self.data.tkt, vals[3])
        if desc:
            desc_lbl = QLabel(" ".join(desc.split()))
            desc_lbl.setProperty("class", "PreviewDesc")
            desc_lbl.setWordWrap(True)
            desc_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            desc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hv.addWidget(desc_lbl)
        self.detail_layout.addWidget(header)

        # 有值属性 (零值不显示, 同人物页装备物品布局: 6列grid, 标签在上值在下)
        body = self.add_group("属性")
        pairs = []
        for key, off, label, kind in ITEM_VIEW_FIELDS:
            v = vals[off // 2]
            if v == 0:
                continue
            if kind == 'val1000':
                pairs.append((label, val1000_text(v)))
            elif kind == 'combat_flag':
                names = flag_names(v, COMBAT_FLAG_NAMES)
                pairs.append((label, "、".join(names) if names else str(v)))
            elif kind == 'extra_flags':
                names = flag_names(v, EXTRA_FLAG_NAMES)
                pairs.append((label, "、".join(names) if names else str(v)))
            elif kind == 'skill':
                name_s = self.data.skill_name(abs(v)) or f"技能#{v}"
                pairs.append((label, name_s))
            elif kind == 'mask_lo':
                is_cause = key.startswith('cause_')
                chips = self._build_status_chips(v, hi=False, is_cause=is_cause)
                if chips:
                    pairs.append((label, chips))
            elif kind == 'mask_hi':
                is_cause = key.startswith('cause_')
                chips = self._build_status_chips(v, hi=True, is_cause=is_cause)
                if chips:
                    pairs.append((label, chips))
            else:
                pairs.append((label, str(v)))
        if pairs:
            attr_grid = QGridLayout()
            attr_grid.setHorizontalSpacing(8)
            attr_grid.setVerticalSpacing(4)
            cols = 6
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
                if isinstance(val, list):
                    val_w = self._make_chips_widget(val)
                    cell.addWidget(val_w, 1)
                else:
                    val_lbl = self._val_label(val, True)
                    cell.addWidget(val_lbl, 1)
                attr_grid.addWidget(cell_w, r, c, Qt.AlignTop)
            # 末列空白占位, 防止列宽不均
            last_row_count = len(pairs) % cols
            if last_row_count != 0:
                last_row = len(pairs) // cols
                for c in range(last_row_count, cols):
                    spacer = QWidget()
                    attr_grid.addWidget(spacer, last_row, c)
            for c in range(cols):
                attr_grid.setColumnStretch(c, 1)
            body.addLayout(attr_grid)
        else:
            self.add_text_block(body, "(无属性数值)", "StatusHint")

        # 获得途径 (TKD脚本/TKMat宝箱/TKShop商店/WarPC掉落/WarData战场宝物 反向索引)
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

    # ── 辅助 ──

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))

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

    def _val_label(self, text, equipped=True):
        """创建属性值标签: 无padding, 颜色适配主题"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignLeft)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        green = "#55b572" if self._is_dark_theme() else "#178a39"
        gray = "#888" if self._is_dark_theme() else "#777"
        lbl.setStyleSheet(f"color: {green if equipped else gray}; padding: 0px;")
        return lbl
