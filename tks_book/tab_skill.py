# -*- coding: utf-8 -*-
"""tks_book 技能标签页 — 技能名称/说明文本/有值属性 (零值不显示)"""
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout

from book_loader import (
    SKILL_VIEW_FIELDS, SKILL_TYPES, ATK_TYPES, SPECIAL_FLAG_NAMES,
    tkt_first_line, tkt_full_text, status_mask_names, flag_names,
)
from tab_common import BookTabBase


class SkillTab(BookTabBase):
    """技能查看页: 全部技能列表 + 名称/说明/非零属性"""

    def populate(self):
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

        # 头部: 名称 + 类型
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(8, 12, 8, 12)
        hl.setSpacing(6)
        name = tkt_first_line(self.data.tkt, vals[0]) or f"技能#{idx}"
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "PreviewName")
        hl.addWidget(name_lbl)
        tname = SKILL_TYPES.get(vals[2], f"类型{vals[2]}")
        meta_lbl = QLabel(f"{tname}    记录 #{idx}")
        meta_lbl.setProperty("class", "PreviewMeta")
        hl.addWidget(meta_lbl)
        self.detail_layout.addWidget(header)

        # 说明文本 (desc_id = 字节偏移 2 → int16 idx 1)
        body = self.add_group("说明文本")
        self.add_text_block(body, tkt_full_text(self.data.tkt, vals[1]))

        # 有值属性 (零值不显示)
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
                pairs.append((label, "、".join(status_mask_names(v, hi=False)) or str(v)))
            elif kind == 'mask_hi':
                pairs.append((label, "、".join(status_mask_names(v, hi=True)) or str(v)))
            elif kind == 'atk_type':
                pairs.append((label, ATK_TYPES.get(v, str(v))))
            else:
                pairs.append((label, str(v)))
        # atk_type=0 (物理攻击) 是有效值但被零值过滤, 指令/主动技能补充显示
        if vals[46] == 0 and vals[2] in (0, 1):
            pairs.append(("攻击类型", ATK_TYPES[0]))
        if pairs:
            self.add_kv_grid(body, pairs, cols=3)
        else:
            self.add_text_block(body, "(无属性数值)", "StatusHint")

        # 技能树关联 (ref_skill/ref_type 对, 零值不显示)
        tree_pairs = []
        for pi in range(8):
            ref_skill = vals[4 + pi * 2]
            ref_type = vals[5 + pi * 2]
            if ref_skill <= 0 or ref_type == 0:
                continue
            ref_name = self.data.skill_name(ref_skill) or f"技能#{ref_skill}"
            tree_pairs.append((f"目标技能", f"{ref_name}  (进度 +{ref_type})"))
        if tree_pairs:
            body = self.add_group("技能树关联")
            self.add_kv_grid(body, tree_pairs, cols=2)

        self.finish_detail()
