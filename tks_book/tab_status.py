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

from editor_utils.game_defs import STATUS_DESCRIPTIONS
from book_loader import (
    get_packed_byte, tkt_first_line,
)
from tab_common import BookTabBase


# ═══════════════════════════════════════════════════════════════
# 状态功能描述 (来源: 游戏原始状态说明表 + 反编译验证)
#   元组: (category, duration, description)
#   category: "增益" = 有利状态 / "减益" = 不利状态
#   duration: 作用回合数; -1 = 持续 (直到被解除)
#     默认回合数表 byte_4EB790[2*idx] (内存转储已逐项核对, 0xFFFF=持续)
#   反编译确认的结构:
#     sub_4188D4 — 图标渲染: 活跃状态数组 f[43..50], 帧=icon_id+241
#     sub_41E40C — 物品解除: cure_mask1(28)/cure_mask2(29), bit=1<<(icon_id-1)
#     sub_42234C — 属性重算: f[11/12]=攻, f[13/14]=防, f[15/16]=命中,
#                  f[17/18]=闪避, f[19/20]=速度(上限100), f[7/8]=HP, f[9/10]=MP
#     sub_422BBC — 技能增益: 百分比修正 f[12]+=v6[25]*f[11]/100 (Type1)
#   状态标志数组: byte_9E048E[32*角色 + idx] (sub_442D44 写入已证实)
#     数值系数以真实战斗函数 sub_4400DC 汇编为准 (sub_43E980 是 AI 伤害
#     评估副本, 破兵/麻痹/虚弱的系数与真实战斗不一致, 属原版 AI 端 bug)
# ═══════════════════════════════════════════════════════════════
class StatusTab(BookTabBase):
    """状态查看页: 31 种异常状态图标/名称/功能/来源"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent, placeholder="搜索状态名称或类型")
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
            widths={0: 40, 1: 40, 3: 80, 4: 56}, stretch_col=2)
        self.clear_detail()
        self.finish_detail()

    # ── 详情 ──

    def show_detail(self, idx):
        if not (0 <= idx < len(STATUS_NAMES)):
            return
        self.clear_detail()
        name = STATUS_NAMES[idx]
        cat, duration, desc = STATUS_DESCRIPTIONS[idx]

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
        cat_color = "BookOk" if cat == "增益" else "BookBad"
        cat_lbl = QLabel(f"类型: {cat}")
        cat_lbl.setProperty("class", cat_color)
        cat_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(cat_lbl)
        dur_str = "持续" if duration < 0 else f"{duration}回合"
        dur_color = "BookMeta"
        dur_lbl = QLabel(f"作用回合: {dur_str}")
        dur_lbl.setProperty("class", dur_color)
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
        seen = set()
        bit_lo = 1 << status_idx if status_idx < 16 else 0
        bit_hi = 1 << (status_idx - 16) if status_idx >= 16 else 0
        # 角色: WarPC f[67]=mask_lo, f[68]=mask_hi (攻击附加状态)
        for rec in self.data.warpc_recs:
            f = rec['fields']
            if (f[67] & 0xFFFF & bit_lo) or (f[68] & 0xFFFF & bit_hi):
                name = self.data.char_name(rec) or f"角色#{rec['index']}"
                key = ("角色", name, None)
                if key not in seen:
                    seen.add(key)
                    causes.append(("角色", name, None))
        # 物品: vals[26]=cause_lo, vals[27]=cause_hi
        for rec in self.data.item_recs:
            vals = rec['vals']
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            if (vals[26] & bit_lo) or (vals[27] & bit_hi):
                name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
                name = name.strip()
                key = ("物品", name, vals[4])
                if key not in seen:
                    seen.add(key)
                    causes.append(("物品", name, vals[4]))
        return causes

    def _find_cures(self, status_idx):
        """扫描全部物品/技能的解除状态掩码, 返回 [(来源类型, 名称, sprite_idx?)]"""
        cures = []
        seen = set()
        bit_lo = 1 << status_idx if status_idx < 16 else 0
        bit_hi = 1 << (status_idx - 16) if status_idx >= 16 else 0
        # 物品: vals[28]=cure_lo, vals[29]=cure_hi
        for rec in self.data.item_recs:
            vals = rec['vals']
            if vals[0] in (0, 1) or vals[2] <= 0:
                continue
            if (vals[28] & bit_lo) or (vals[29] & bit_hi):
                name = tkt_first_line(self.data.tkt, vals[2]) or f"物品#{vals[0]}"
                name = name.strip()
                key = ("物品", name, vals[4])
                if key not in seen:
                    seen.add(key)
                    cures.append(("物品", name, vals[4]))
        # 技能: vals[34]=immunity_lo, vals[35]=immunity_hi (免疫=可解除)
        for rec in self.data.skill_recs:
            vals = rec['vals']
            if (vals[34] & bit_lo) or (vals[35] & bit_hi):
                name = self.data.skill_name(rec['index']) or f"技能#{rec['index']}"
                name = name.strip()
                key = ("技能", name, None)
                if key not in seen:
                    seen.add(key)
                    cures.append(("技能", name, None))
        return cures

    def _find_resists(self, status_idx):
        """扫描全部角色的状态抵抗, 返回 [(角色名, 抵抗%)] (仅>0)"""
        resists = []
        seen = set()
        for rec in self.data.warpc_recs:
            name = self.data.char_name(rec)
            if not name:
                continue
            val = get_packed_byte(rec['fields'], 51, status_idx)
            if val > 0:
                key = (name, val)
                if key not in seen:
                    seen.add(key)
                    resists.append((name, val))
        return resists

    # ── 辅助渲染 ──

    def _build_source_list(self, body, sources, css_class):
        """来源列表: FlowLayout 横向排列 (类型标签 + 图标? + 名称)"""
        if not sources:
            self.add_text_block(body, "(无)", "StatusHint")
            return
        w = QWidget()
        w.setObjectName("TransparentBg")
        flow = FlowLayout(w, margin=0, spacing=4)
        type_color = "BookMeta"
        for src_type, name, sprite_idx in sources:
            chip = QWidget()
            chip.setProperty("class", "Chip")
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(1, 0, 3, 0)
            cl.setSpacing(3)
            tl = QLabel(src_type)
            tl.setProperty("class", type_color)
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
        w.setObjectName("TransparentBg")
        flow = FlowLayout(w, margin=0, spacing=4)
        val_color = "BookOk"
        for name, val in resists:
            chip = QWidget()
            chip.setProperty("class", "Chip")
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(1, 0, 3, 0)
            cl.setSpacing(3)
            nl = QLabel(name)
            nl.setProperty("class", "StatusRemove")
            nl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(nl, 0, Qt.AlignVCenter)
            vl = QLabel(f"{val}%")
            vl.setProperty("class", val_color)
            vl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(vl, 0, Qt.AlignVCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            flow.addWidget(chip)
        body.addWidget(w)

    def _is_dark_theme(self):
        w = self.window()
        return bool(getattr(w, 'is_dark_theme', True))
