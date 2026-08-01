# -*- coding: utf-8 -*-
"""tks_book 技能标签页 — 名称/类型/说明文本/有值属性 (零值不显示)"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
    QSizePolicy,
)

from editor_utils.jvg_loader import get_sprite_pixmap
from editor_utils.flow_layout import FlowLayout
from editor_utils.picker_dialogs import STATUS_NAMES, STATUS_ICON_BASE

from book_loader import (
    SKILL_VIEW_FIELDS, SKILL_TYPES, ATK_TYPES, SPECIAL_FLAG_NAMES,
    tkt_first_line, tkt_full_text, flag_names,
)
from tab_common import BookTabBase


class SkillTab(BookTabBase):
    """技能查看页: 全部技能列表 + 名称/说明/非零属性"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}

    def populate(self):
        self._icon_cache.clear()
        rows = []
        for rec in self.data.skill_recs:
            vals = rec['vals']
            name = tkt_first_line(self.data.tkt, vals[0])
            if not name:
                continue  # 空槽不显示
            tname = SKILL_TYPES.get(vals[2], str(vals[2]))
            rows.append((rec['index'], [
                str(rec['index']), str(vals[0]), tname, name,
                str(vals[3]), str(vals[43]),
            ]))
        self.set_table_items(
            ["技能ID", "文本ID", "类型", "技能名称", "技能点数", "耗费内力"],
            rows, widths={0: 60, 1: 60, 2: 80, 4: 70, 5: 70}, stretch_col=3)
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

        # 头部: 名称 + 类型 + 说明文本 (PreviewFrame 风格, 同 item/char 页)
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(8)
        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        name = tkt_first_line(self.data.tkt, vals[0]) or f"技能#{idx}"
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl, 0, Qt.AlignVCenter)
        meta_lbl = QLabel(f"{SKILL_TYPES.get(vals[2], f'类型{vals[2]}')}    记录 #{idx}")
        meta_lbl.setProperty("class", "PreviewMeta")
        name_box.addWidget(meta_lbl)
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

        # 有值属性 (零值不显示, 同 item/char 页: 6列grid, 标签在上值在下)
        body = self.add_group("属性")
        pairs = []
        for key, off, label, kind in SKILL_VIEW_FIELDS:
            v = vals[off // 2]
            if v == 0:
                continue
            if kind == 'flags':
                names = flag_names(v, SPECIAL_FLAG_NAMES)
                pairs.append((label, "、".join(names) if names else str(v)))
            elif kind == 'mask_lo':
                chips = self._build_status_chips(v, hi=False, is_immunity=True)
                if chips:
                    pairs.append((label, chips))
            elif kind == 'mask_hi':
                chips = self._build_status_chips(v, hi=True, is_immunity=True)
                if chips:
                    pairs.append((label, chips))
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

        # 技能树关联 (ref_skill/ref_type 对, 零值不显示, 6列grid, 标签在上值在下)
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
            attr_grid = QGridLayout()
            attr_grid.setHorizontalSpacing(8)
            attr_grid.setVerticalSpacing(4)
            cols = 6
            for slot, (label, val) in enumerate(tree_pairs):
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
            last_row_count = len(tree_pairs) % cols
            if last_row_count != 0:
                last_row = len(tree_pairs) // cols
                for c in range(last_row_count, cols):
                    spacer = QWidget()
                    attr_grid.addWidget(spacer, last_row, c)
            for c in range(cols):
                attr_grid.setColumnStretch(c, 1)
            body.addLayout(attr_grid)

        self.detail_layout.addStretch(1)

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
        green = "#55b572" if self._is_dark_theme() else "#178a39"
        gray = "#888" if self._is_dark_theme() else "#777"
        lbl.setStyleSheet(f"color: {green if equipped else gray}; padding: 0px;")
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
