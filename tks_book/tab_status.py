# -*- coding: utf-8 -*-
"""tks_book 状态标签页 — 异常状态图标/名称/功能描述/来源与解除途径

数据来源:
  状态名称/图标: editor_utils.picker_dialogs.STATUS_NAMES (31 种, bit 0..30)
                Mu.JVG 帧索引 = STATUS_ICON_BASE + idx (代码传参 STATUS_ICON_BASE+idx-130,
                                 get_sprite_pixmap 内部 +130 还原为帧索引)
  导致状态来源: WarPC[67]/[68] (角色攻击附加) + TKItem[26]/[27] (物品导致)
  解除状态来源: TKItem[28]/[29] (物品解除) + TKSkill[34]/[35] (技能免疫)
  状态抵抗:     WarPC[51..66] 32 字节打包, 每字节=抵抗率% (get_packed_byte)

状态图标渲染复刻自反编译 sub_4188D4: 帧 = icon_id + 241 (icon_id 1..31 ↔ idx 0..30)。
"""
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
    get_packed_byte, tkt_first_line,
)
from tab_common import BookTabBase


# ═══════════════════════════════════════════════════════════════
# 状态功能描述 (来源: 游戏原始状态说明表 + 反编译验证)
#   元组: (category, duration, description)
#   category: "增益" = 有利状态 / "减益" = 不利状态
#   duration: 作用回合数; -1 = 持续 (直到被解除)
#   反编译确认的结构:
#     sub_4188D4 — 图标渲染: 活跃状态数组 f[43..50], 帧=icon_id+241
#     sub_41E40C — 物品解除: cure_mask1(28)/cure_mask2(29), bit=1<<(icon_id-1)
#     sub_42234C — 属性重算: f[11/12]=攻, f[13/14]=防, f[15/16]=命中,
#                  f[17/18]=闪避, f[19/20]=速度(上限100), f[7/8]=HP, f[9/10]=MP
#     sub_422BBC — 技能增益: 百分比修正 f[12]+=v6[25]*f[11]/100 (Type1)
# ═══════════════════════════════════════════════════════════════
STATUS_DESCRIPTIONS = [
    # idx 0-7  (游戏编号 1-8)
    ("减益", 5,  "攻击下降30％。"),
    ("减益", 5,  "防御下降30％。"),
    ("减益", 5,  "命中下降30％。"),  # 昏眩: 官方说50%，实为30% (sub_43E980:181)
    ("减益", 5,  "闪避下降30％。"),  # 封锁: 官方说50%，实为30% (sub_43E980:196)
    ("减益", 5,  "移动－2，但至少为1。"),
    ("增益", 5,  "攻击上升30％。"),
    ("增益", 5,  "防御上升30％。"),
    ("增益", 5,  "命中上升30％。"),  # 集中: 官方说50%，实为30% (sub_43E980:183)
    # idx 8-15  (游戏编号 9-16)
    ("增益", 5,  "闪避上升30％。"),  # 云身: 官方说50%，实为30% (sub_43E980:198)
    ("增益", 5,  "移动＋2。"),
    ("增益", 3,  "在战斗中视为土石草木，而不会受到敌方攻击。一旦移动则此状态无效。"),
    ("增益", 3,  "伪装成敌人，敌人不会攻击角色，除了角色攻击，则状态解除。"),
    ("增益", 5,  "闪避上升10％，不受陷阱和地面法术伤害。"),
    ("增益", 2,  "与邻近人物进行攻击至死。"),
    ("增益", 5,  "施法所耗内力减半。"),
    ("增益", 5,  "施法所耗内力减半。"),
    # idx 16-23  (游戏编号 17-24)
    ("减益", 2,  "受此状态者每次移动时会向目标人物所在位置强制移动。"),
    ("减益", 2,  "反向攻击队友。"),
    ("减益", 2,  "无法使用任何指令技能。"),
    ("减益", 2,  "完全不能行动。"),
    ("减益", -1, "持续任何指令都有50％的失败率。"),
    ("减益", 3,  "无法使用任何法术，且每回合减少10％内力和生命。"),
    ("减益", 4,  "生命持续下降15％，期间任何伤害都会加倍。"),
    ("减益", 4,  "完全无法行动且内力持续下降25％。"),
    # idx 24-30  (游戏编号 25-31)
    ("减益", -1, "攻击下降15％，防御下降30％。"),  # 虚弱: 官方说攻击-30%，实为-15% (sub_43E980:172)
    ("减益", -1, "命中率下降15％，闪避下降15％。"),  # 麻痹: 官方说30%，实为15% (sub_43E980:185,200)
    ("减益", 4,  "完全无法行动，但受伤害就会解除。"),
    ("减益", -1, "生命和内力持续下降15％。"),
    ("减益", 2,  "受此状态的影响者，期间会向迷恋者移动，但不会攻击任何人，"
               "且防御上升40％，状态解除后，攻击上升30％，且对此状态免疫。"),
    ("增益", 3,  "不会受任何状态影响，除了之前有的。"),
    ("增益", 3,  "每次移动会恢复50％失去的生命和内力。"),
]


class StatusTab(BookTabBase):
    """状态查看页: 31 种异常状态图标/名称/功能/来源"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}

    def populate(self):
        self._icon_cache.clear()
        rows = []
        for idx, name in enumerate(STATUS_NAMES):
            icon = None
            pix = get_sprite_pixmap(self.data.mu_sprites,
                                    STATUS_ICON_BASE + idx - 130, (24, 24),
                                    self._icon_cache)
            if pix:
                icon = QIcon(pix)
            entry = STATUS_DESCRIPTIONS[idx] if idx < len(STATUS_DESCRIPTIONS) else None
            cat = entry[0] if entry else "?"
            dur = entry[1] if entry else 0
            dur_str = "持续" if dur < 0 else str(dur)
            rows.append((idx, [
                ("", icon), str(idx), name, cat, dur_str,
            ]))
        self.set_table_items(
            ["图标", "#", "状态名称", "类型", "回合"], rows,
            widths={0: 40, 1: 36, 3: 50, 4: 50}, stretch_col=2)
        self.clear_detail()
        self.finish_detail()

    # ── 详情 ──

    def show_detail(self, idx):
        if not (0 <= idx < len(STATUS_NAMES)):
            return
        self.clear_detail()
        name = STATUS_NAMES[idx]
        cat, duration, desc = STATUS_DESCRIPTIONS[idx]

        dark = self._is_dark_theme()
        # 头部: 大图标 + 名称 + 类型 + 作用回合
        header = QFrame()
        header.setObjectName("PreviewFrame")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(8, 12, 8, 12)
        hv.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        pix = get_sprite_pixmap(self.data.mu_sprites,
                                STATUS_ICON_BASE + idx - 130, (48, 48),
                                self._icon_cache)
        if pix:
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setText("(无图标)")
        top_row.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name_lbl = QLabel(f"{name}  (#{idx})")
        name_lbl.setProperty("class", "PreviewName")
        name_box.addWidget(name_lbl, 0, Qt.AlignVCenter)
        # 类型 + 作用回合 行: 增益绿 / 减益红, 作用回合蓝色
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        cat_color = "#55b572" if (cat == "增益" and dark) else \
                    ("#178a39" if cat == "增益" else
                     ("#cc6666" if dark else "#cc3333"))
        cat_lbl = QLabel(f"类型: {cat}")
        cat_lbl.setStyleSheet(f"color: {cat_color}; padding: 0px;")
        cat_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(cat_lbl)
        dur_str = "持续" if duration < 0 else f"{duration}回合"
        dur_color = "#6f9fc4" if dark else "#2a6f8c"
        dur_lbl = QLabel(f"作用回合: {dur_str}")
        dur_lbl.setStyleSheet(f"color: {dur_color}; padding: 0px;")
        dur_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(dur_lbl)
        info_row.addStretch()
        name_box.addLayout(info_row)
        name_box.addStretch()
        top_row.addLayout(name_box, 1)
        hv.addLayout(top_row)
        self.detail_layout.addWidget(header)

        # 功能描述
        body = self.add_group("影响效果")
        self.add_text_block(body, desc)

        # 导致此状态 (来源)
        causes = self._find_causes(idx)
        body = self.add_group(f"导致此状态 ({len(causes)})")
        self._build_source_list(body, causes, "StatusInflict")

        # 解除此状态 (途径)
        cures = self._find_cures(idx)
        body = self.add_group(f"解除此状态 ({len(cures)})")
        self._build_source_list(body, cures, "StatusRemove")

        # 角色抵抗
        resists = self._find_resists(idx)
        body = self.add_group(f"角色抵抗 ({len(resists)})")
        if resists:
            self._build_resist_chips(body, resists)
        else:
            self.add_text_block(body, "(无角色对此状态有抵抗)", "StatusHint")

        self.finish_detail()

    # ── 数据扫描: 导致/解除/抵抗 ──

    def _find_causes(self, status_idx):
        """扫描全部角色/物品的导致状态掩码, 返回 [(来源类型, 名称, sprite_idx?)]"""
        causes = []
        bit_lo = 1 << status_idx if status_idx < 16 else 0
        bit_hi = 1 << (status_idx - 16) if status_idx >= 16 else 0
        # 角色: WarPC f[67]=mask_lo, f[68]=mask_hi (攻击附加状态)
        for rec in self.data.warpc_recs:
            f = rec['fields']
            if (f[67] & 0xFFFF & bit_lo) or (f[68] & 0xFFFF & bit_hi):
                name = self.data.char_name(rec) or f"角色#{rec['index']}"
                causes.append(("角色", name, None))
        # 物品: vals[26]=cause_lo, vals[27]=cause_hi
        for rec in self.data.item_recs:
            vals = rec['vals']
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            if (vals[26] & bit_lo) or (vals[27] & bit_hi):
                name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
                causes.append(("物品", name.strip(), vals[4]))
        return causes

    def _find_cures(self, status_idx):
        """扫描全部物品/技能的解除状态掩码, 返回 [(来源类型, 名称, sprite_idx?)]"""
        cures = []
        bit_lo = 1 << status_idx if status_idx < 16 else 0
        bit_hi = 1 << (status_idx - 16) if status_idx >= 16 else 0
        # 物品: vals[28]=cure_lo, vals[29]=cure_hi
        for rec in self.data.item_recs:
            vals = rec['vals']
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            if (vals[28] & bit_lo) or (vals[29] & bit_hi):
                name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
                cures.append(("物品", name.strip(), vals[4]))
        # 技能: vals[34]=immunity_lo, vals[35]=immunity_hi (免疫=可解除)
        for rec in self.data.skill_recs:
            vals = rec['vals']
            if (vals[34] & bit_lo) or (vals[35] & bit_hi):
                name = self.data.skill_name(rec['index']) or f"技能#{rec['index']}"
                cures.append(("技能", name.strip(), None))
        return cures

    def _find_resists(self, status_idx):
        """扫描全部角色的状态抵抗, 返回 [(角色名, 抵抗%)] (仅>0)"""
        resists = []
        for rec in self.data.warpc_recs:
            name = self.data.char_name(rec)
            if not name:
                continue
            val = get_packed_byte(rec['fields'], 51, status_idx)
            if val > 0:
                resists.append((name, val))
        return resists

    # ── 辅助渲染 ──

    def _build_source_list(self, body, sources, css_class):
        """来源列表: FlowLayout 横向排列 (类型标签 + 图标? + 名称)"""
        if not sources:
            self.add_text_block(body, "(无)", "StatusHint")
            return
        w = QWidget()
        flow = FlowLayout(w, margin=0, spacing=4)
        dark = self._is_dark_theme()
        type_color = "#7ab8d4" if dark else "#2a6f8c"
        for src_type, name, sprite_idx in sources:
            chip = QWidget()
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(1, 0, 3, 0)
            cl.setSpacing(3)
            tl = QLabel(src_type)
            tl.setStyleSheet(f"color: {type_color}; padding: 0px;")
            tl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(tl, 0, Qt.AlignVCenter)
            if sprite_idx is not None:
                il = QLabel()
                il.setFixedSize(16, 16)
                il.setAlignment(Qt.AlignCenter)
                pix = get_sprite_pixmap(self.data.mu_sprites, sprite_idx,
                                        (16, 16), self._icon_cache)
                if pix:
                    il.setPixmap(pix)
                cl.addWidget(il, 0, Qt.AlignVCenter)
            nl = QLabel(name)
            nl.setProperty("class", css_class)
            nl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            nl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            cl.addWidget(nl, 0, Qt.AlignVCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            flow.addWidget(chip)
        body.addWidget(w)

    def _build_resist_chips(self, body, resists):
        """抵抗列表: 角色名 + 抵抗%, 按抵抗值降序"""
        resists.sort(key=lambda x: -x[1])
        w = QWidget()
        flow = FlowLayout(w, margin=0, spacing=4)
        dark = self._is_dark_theme()
        val_color = "#55b572" if dark else "#178a39"
        for name, val in resists:
            chip = QWidget()
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(1, 0, 3, 0)
            cl.setSpacing(3)
            nl = QLabel(name)
            nl.setProperty("class", "StatusRemove")
            nl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(nl, 0, Qt.AlignVCenter)
            vl = QLabel(f"{val}%")
            vl.setStyleSheet(f"color: {val_color}; padding: 0px;")
            vl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(vl, 0, Qt.AlignVCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            flow.addWidget(chip)
        body.addWidget(w)

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))
