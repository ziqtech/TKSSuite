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
from editor_utils.ui_helpers import EditorComboBox

from book_loader import (
    ITEM_VIEW_FIELDS, PAGE_NAMES, COMBAT_FLAG_NAMES, EXTRA_FLAG_NAMES,
    EQUIP_ID_IDX,
    tkt_first_line, tkt_full_text, flag_names, val1000_text,
    use_right_label,
)
from tab_common import BookTabBase


class ItemTab(BookTabBase):
    """物品查看页: 全部物品列表 + 名称/说明/非零属性"""

    _HEADERS = ["图标", "#", "ID", "分类", "物品名称", "权限", "价格"]
    # 物品名称是拉伸列: 配置下限同时抬高其初始宽与拉伸封顶 (基准×1.5+64)。
    # 下限按显示承诺设定: "#" 至少完整显示 4 位数字 (76), ID 至少 5 位
    # (88), 价格按 5 位对齐 (76), 图标容纳 24px。各列下限之和 (621) 低于
    # 默认左栏视口 (~630), 数字列在任何主题字体下都不触发收缩截断。
    _WIDTHS = {0: 48, 1: 52, 2: 64, 3: 58, 4: 125, 5: 100, 6: 76}

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._icon_cache = {}
        self._all_rows = []   # [(rec_index, cells, page), ...] 未筛选全量
        # 分类筛选 (参考 item_editor 页面号筛选; 查看器无空槽无需仅非空)
        self._filter_lbl = QLabel("分类")
        self._filter_lbl.setProperty("class", "PropLabel")
        self._filter_page = EditorComboBox()
        self._filter_page.addItems(
            ["全部分类"] + [PAGE_NAMES[i] for i in sorted(PAGE_NAMES)])
        self._filter_page.setToolTip("按物品分类 (页面号) 筛选列表")
        self._filter_page.currentIndexChanged.connect(self._on_filter_changed)
        self._search_row_layout.addWidget(self._filter_lbl)
        self._search_row_layout.addWidget(self._filter_page)

    def populate(self):
        self._icon_cache.clear()
        self._all_rows = []
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
            self._all_rows.append((rec['index'], [
                ("", icon), str(rec['index']), str(vals[0]),
                PAGE_NAMES.get(page, "?"), name,
                use_right_label(vals[5], page), str(vals[31]),
            ], page))
        self._on_filter_changed()

    def _on_filter_changed(self, *_args):
        """重建列表: 分类下拉 (0=全部, 其余=页面号+1) + 基类文本搜索叠加"""
        sel = self._filter_page.currentIndex()
        rows = [(k, cells) for k, cells, page in self._all_rows
                if sel <= 0 or page == sel - 1]
        self.set_table_items(self._HEADERS, rows,
                             widths=self._WIDTHS, stretch_col=4)
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
        self.clear_detail()
        render_item_detail(self, rec)
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
            cell_w.setObjectName("TransparentBg")
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
                spacer.setObjectName("TransparentBg")
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
            cell_w.setObjectName("TransparentBg")
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
            color = "BookOk" if equipped else "BookMuted"
        lbl.setProperty("class", color)
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
        w.setObjectName("TransparentBg")
        flow = FlowLayout(w, margin=0, spacing=3)
        for name, sprite_idx, css_class in chips:
            chip = QWidget()
            chip.setProperty("class", "Chip")
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


# ═══════════════════════════════════════════════════════════════
# 可复用物品详情渲染 (物品页 / 特殊物品页共用)
# ═══════════════════════════════════════════════════════════════

def render_item_header(view, rec):
    """渲染物品头部 (图标/名称/元信息/说明文本) 到 view.detail_layout。
    供只需头部概览的页面 (如特殊物品页) 单独调用。
    """
    vals = rec['vals']

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
    pix = get_sprite_pixmap(view.data.mu_sprites, vals[4], (48, 48),
                            view._icon_cache)
    if pix:
        icon_lbl.setPixmap(pix)
    else:
        icon_lbl.setText("(无图标)")
    top_row.addWidget(icon_lbl, 0, Qt.AlignVCenter)
    name_box = QVBoxLayout()
    name_box.setSpacing(4)
    name = tkt_first_line(view.data.tkt, vals[2]) or f"物品#{vals[0]}"
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
        tkkon_name = view.data.tkkon_names.get(vals[6], "")
        if tkkon_name:
            meta_parts.append(f"效果: {tkkon_name}")
        else:
            meta_parts.append(f"TKKon: {vals[6]}")
    meta_lbl = QLabel(" | ".join(meta_parts))
    meta_lbl.setProperty("class", "BookMeta")
    meta_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    name_box.addWidget(meta_lbl)
    name_box.addStretch()
    top_row.addLayout(name_box, 1)
    hv.addLayout(top_row)
    # 说明文本 (放在 PreviewFrame 内部, PreviewDesc 样式, 去除原数据换行)
    desc = tkt_full_text(view.data.tkt, vals[3])
    if desc:
        desc_lbl = QLabel(" ".join(desc.split()))
        desc_lbl.setProperty("class", "PreviewDesc")
        desc_lbl.setWordWrap(True)
        desc_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        desc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hv.addWidget(desc_lbl)
    view.detail_layout.addWidget(header)


def render_item_detail(view, rec, include_sources=True):
    """在 view (BookTabBase 子类) 的 detail_layout 中渲染单个物品详情。

    不含 clear_detail / 末尾 stretch, 由调用方控制;
    view 需提供 _icon_cache 及 add_group 等基类方法。
    include_sources=False 时跳过「获得途径」分组 (调用方已自带来源展示时避免重复)。
    """
    vals = rec['vals']

    cyan = "BookMeta"

    render_item_header(view, rec)

    field_map = {f[0]: f for f in ITEM_VIEW_FIELDS}

    # ── 基础属性 (数值加成) ──
    body = view.add_group("属性")
    stat_pairs = []
    stat_keys = [
        "hp_inc", "hp_heal", "mp_inc", "mp_heal",
        "atk", "def_", "hit", "dodge", "spd", "luk", "spi", "vit",
        "jp_bonus", "medicine",
    ]
    for key in stat_keys:
        if key not in field_map:
            continue
        off = field_map[key][1]
        label = field_map[key][2]
        kind = field_map[key][3]
        v = vals[off // 2]
        if v == 0:
            continue
        if kind == 'val1000':
            stat_pairs.append((label, val1000_text(v)))
        else:
            stat_pairs.append((label, str(v)))
    if stat_pairs:
        view._build_prop_grid(body, stat_pairs, cols=6)
    else:
        view.add_text_block(body, "(无属性数值)", "StatusHint")

    # ── 技能效果 (4列: 附加技能/装备后学习/使用后学习1/2) ──
    body = view.add_group("技能效果")
    skill_keys = ["attach_skill", "equip_learn", "use_learn1", "use_learn2"]
    skill_labels = ["附加技能", "装备后学习", "使用后学习1", "使用后学习2"]
    skill_pairs = []
    for key, label in zip(skill_keys, skill_labels):
        if key not in field_map:
            continue
        off = field_map[key][1]
        v = vals[off // 2]
        if v == 0:
            skill_pairs.append((label, "(无)", False))
        else:
            name_s = view.data.skill_name(abs(v)) or f"技能#{v}"
            skill_pairs.append((label, name_s, True))
    view._build_skill_grid(body, skill_pairs)

    # ── 导致状态 / 解除状态 (并排) ──
    cause_body, cure_body = view.add_group_pair("导致状态", "解除状态")
    cause_chips = []
    for key in ("cause_mask1", "cause_mask2"):
        if key in field_map:
            off = field_map[key][1]
            hi = key.endswith("2")
            cause_chips += view._build_status_chips(
                vals[off // 2], hi=hi, is_cause=True)
    if cause_chips:
        cause_body.addWidget(view._make_chips_widget(cause_chips))
    else:
        view.add_text_block(cause_body, "(无导致状态)", "StatusHint")

    cure_chips = []
    for key in ("cure_mask1", "cure_mask2"):
        if key in field_map:
            off = field_map[key][1]
            hi = key.endswith("2")
            cure_chips += view._build_status_chips(
                vals[off // 2], hi=hi, is_cause=False)
    if cure_chips:
        cure_body.addWidget(view._make_chips_widget(cure_chips))
    else:
        view.add_text_block(cure_body, "(无解除状态)", "StatusHint")

    # ── 特殊效果 ──
    body = view.add_group("特殊效果")
    special_pairs = []
    for key in ("combat_flag", "extra_flags"):
        if key not in field_map:
            continue
        off = field_map[key][1]
        label = field_map[key][2]
        v = vals[off // 2]
        if v == 0:
            continue
        if key == "combat_flag":
            names = flag_names(v, COMBAT_FLAG_NAMES)
        else:
            names = flag_names(v, EXTRA_FLAG_NAMES)
        special_pairs.append((label, "、".join(names) if names else str(v)))
    if special_pairs:
        view._build_prop_grid(body, special_pairs, cols=3, color=cyan)
    else:
        view.add_text_block(body, "(无特殊效果)", "StatusHint")

    # ── 初始装备角色 (反向索引) ──
    body = view.add_group("初始装备角色")
    equipped_by = []
    iid = vals[0]
    for wrec in view.data.warpc_recs:
        wname = view.data.char_name(wrec)
        if not wname:
            continue
        wf = wrec['fields']
        for slot, fi in enumerate(EQUIP_ID_IDX):
            if wf[fi] == iid:
                slot_names = ["武器", "防具", "饰品", "饰品"]
                equipped_by.append(f"{wname}({slot_names[slot]})")
                break
    if equipped_by:
        view.add_text_block(body, "、".join(equipped_by))
    else:
        view.add_text_block(body, "(无角色初始装备此物品)", "StatusHint")

    # ── 获得途径 (TKD脚本/TKMat宝箱/TKShop商店/WarPC掉落/WarData战场宝物 反向索引) ──
    if not include_sources:
        return
    body = view.add_group("获得途径")
    sources = view.data.item_sources.get(vals[0], [])
    if sources:
        lines = []
        for kind, desc in sources:
            lines.append(f"【{kind}】{desc}")
        src_lbl = view.add_text_block(body, "\n".join(lines))
        src_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    else:
        hints = []
        if vals[1] == 5:
            hints.append("特殊/剧情物品 (页面5) — 不会出现在任何商店")
        hints.append("未在 商店/宝箱/剧情脚本/敌人掉落/战场宝物 中检索到来源"
                     " (可能为初始装备或未使用物品)")
        src_lbl = view.add_text_block(body, "\n".join(hints), "StatusHint")
        src_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
