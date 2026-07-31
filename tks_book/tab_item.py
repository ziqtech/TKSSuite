# -*- coding: utf-8 -*-
"""tks_book 物品标签页 — 图标/名称/说明文本/有值属性 (零值不显示)"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QFrame, QHBoxLayout, QVBoxLayout

from editor_utils.jvg_loader import get_sprite_pixmap

from book_loader import (
    ITEM_VIEW_FIELDS, PAGE_NAMES, COMBAT_FLAG_NAMES, EXTRA_FLAG_NAMES,
    tkt_first_line, tkt_full_text, status_mask_names, flag_names, val1000_text,
)
from tab_common import BookTabBase


class ItemTab(BookTabBase):
    """物品查看页: 全部物品列表 + 名称/说明/非零属性"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}

    def populate(self):
        self._icon_cache.clear()
        items = []
        for rec in self.data.item_recs:
            vals = rec['vals']
            # 空槽判定与 item_editor.is_empty_item 一致
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            name = tkt_first_line(self.data.tkt, vals[2])
            if not name:
                continue
            page = PAGE_NAMES.get(vals[1], "")
            text = f"{rec['index']:>3}  {name}"
            if page:
                text += f"  [{page}]"
            icon = None
            pix = get_sprite_pixmap(self.data.mu_sprites, vals[4], (24, 24),
                                    self._icon_cache)
            if pix:
                icon = QIcon(pix)
            items.append((rec['index'], text, icon))
        self.set_list_items(items)
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

        # 头部: 图标 + 名称 + 分类/价格
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 12, 8, 12)
        hl.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(64, 64)
        icon_lbl.setAlignment(Qt.AlignCenter)
        pix = get_sprite_pixmap(self.data.mu_sprites, vals[4], (64, 64),
                                self._icon_cache)
        if pix:
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setText("(无图标)")
        hl.addWidget(icon_lbl)
        name_box = QVBoxLayout()
        name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl)
        page = PAGE_NAMES.get(vals[1], f"页面{vals[1]}")
        meta_lbl = QLabel(f"{page}    价格 {vals[31]}    物品ID {vals[0]}    记录 #{idx}")
        meta_lbl.setProperty("class", "PreviewMeta")
        name_box.addWidget(meta_lbl)
        name_box.addStretch()
        hl.addLayout(name_box, 1)
        self.detail_layout.addWidget(header)

        # 说明文本 (desc_id = 字节偏移 6 → int16 idx 3)
        body = self.add_group("说明文本")
        self.add_text_block(body, tkt_full_text(self.data.tkt, vals[3]))

        # 有值属性 (零值不显示)
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
                pairs.append((label, "、".join(status_mask_names(v, hi=False)) or str(v)))
            elif kind == 'mask_hi':
                pairs.append((label, "、".join(status_mask_names(v, hi=True)) or str(v)))
            else:
                pairs.append((label, str(v)))
        if pairs:
            self.add_kv_grid(body, pairs, cols=3)
        else:
            self.add_text_block(body, "(无属性数值)", "StatusHint")

        # 获得途径 (TKD脚本/TKMat宝箱/TKShop商店/WarPC掉落/WarData战场宝物 反向索引)
        body = self.add_group("获得途径")
        sources = self.data.item_sources.get(vals[0], [])
        if sources:
            lines = []
            for kind, desc in sources:
                lines.append(f"【{kind}】{desc}")
            self.add_text_block(body, "\n".join(lines))
        else:
            hints = []
            if vals[1] == 5:
                hints.append("特殊/剧情物品 (页面5) — 不会出现在任何商店")
            hints.append("未在 商店/宝箱/剧情脚本/敌人掉落/战场宝物 中检索到来源"
                         " (可能为初始装备或未使用物品)")
            self.add_text_block(body, "\n".join(hints), "StatusHint")

        self.finish_detail()
