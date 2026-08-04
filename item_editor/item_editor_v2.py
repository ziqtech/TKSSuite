#!/usr/bin/env python3
"""
TKItem.dat 可视化编辑器 (PySide6 — Godot 4.6 风格)
===========================================================
基于反编译源码 + Maker 文案 + 实测数据验证, 使用 PySide6 重写 UI 层。
保留全部逆向分析、字段定义、LZSS 编解码、JVG 图标加载逻辑。
支持深色/浅色主题切换 (默认跟随系统), 共享 editor_themes/ 主题。

【字段语义】基于反编译源码 (sub_41E40C/sub_42234C/sub_422BBC) + Maker 文案 + 实测数据验证:
  1. 字段 [22] offset 44: "装备后学习技能" (v15[22] -> char+176+v15[22]=10, 装备时学会)
     ※实测验证: 蟬翼刀#178 [22]=135=技能"蟬翼刀"; 虎紋刀#177 [22]=134=技能"虎紋刀"
  2. 字段 [23] offset 46: "使用后学习技能1" (v15[23] -> byte_757FB8[1054*a2+v15[23]]=10, 使用时)
     ※实测验证: 遁甲天書#79 [23]=24=技能"瀚力術"
  3. 字段 [24] offset 48: "使用后学习技能2"
     ※实测验证: 遁甲天書#79 [24]=25=技能"遲緩術"
  4. 字段 [26] offset 52: "导致状态 1-16" (Maker UI 标签)
     ※实测验证: 紅顏知己[27]=0x1000 bit12=28迷恋; 大骨鎚[27]=0xC bit2/3=18禁制+19定身
     (反编译 a2[67]=v9[26] 只是保存, 战斗时读取作状态 mask 使用)
  5. 字段 [27] offset 54: "导致状态 17-32"
  6. 字段 [28] offset 56: "解除状态 1-16"
  7. 字段 [29] offset 58: "解除状态 17-32"
  8. 字段 [25] offset 50: "增加医术" (Maker UI 文案; word_75688A += v15[25])
  9. 使用权限 (equip_type) 位掩码语义 (2026-05 全面重分析):
     0=通用/饰品(110条): 坐骑/饰品/任务物品, 0b0=无限制
     1=刀/道具/轻衣(39条): 刀类武器+消耗品+轻便衣物/披风/袍, 0b1=bit0
     2=剑/书籍/铠甲(97条): 剑类武器+书籍+重甲防具, 0b10=bit1
     3=药品/食物(26条): 治疗物品, 刀剑通用 0b11=bit0|bit1
     4=枪/秘笈(18条): 枪类武器+特殊秘笈/法宝, 0b100=bit2
     8=矛(8条), 16=弓弩(12条), 32=大刀(12条), 64=戟(6条), 128=锤(6条)
     (基于 sub_41928C/sub_41F318/sub_4307CC 逆向+全600条实测验证)
 10. 记录数硬限制: 600 条 (sub_45343C 加载 38400 字节 = 600x64; sub_42F8D4 遍历 < 600)
 11. 空槽 (40 条可新增物品): #560-#599, item_id=0 & name_id=0 & desc_id=600

用法:
  python item_editor_v2.py
"""

import csv
import json
import os
import struct
import sys

from PySide6.QtCore import QSize, Qt, QTranslator
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMenuBar, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.flow_layout import FlowLayout
from editor_utils.jvg_loader import get_sprite_pixmap, load_mu_sprites
from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat
from editor_utils.shared_state import pick_tks_directory
from editor_utils.mod_exporter import (
    ModExportPreviewDialog, ModImportPreviewDialog, ModMetadataDialog,
    build_data_diff_json, compute_crc32, diff_records, generate_mod_json,
    get_tksmod_info, import_tksmod_records, load_reference_dat_fields,
    pack_tksmod, safe_mod_filename,
)
from editor_utils.picker_dialogs import (
    STATUS_ICON_BASE, STATUS_NAMES, StatusPickerDialog, TktPickerDialog
)
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.theme_manager import ThemeManager
from editor_utils.ui_helpers import (
    confirm_close, make_fake_input, resolve_config_path,
    themed_messagebox, update_path_labels, NoWheelComboBox,
)
from editor_utils.version import format_title, format_about_header
from editor_utils.window_theme import apply_godot_theme

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data):
    return lzss_decompress_dat(data)
def lzss_compress(data):
    return lzss_compress_dat(data)

def load_tkt(tkt_path):
    """加载 TKT 文本 (仅第一行)"""
    return load_tkt_simple(tkt_path, first_line_only=True)

def load_tkt_full(tkt_path):
    """加载 TKT 全部文本 (保留完整多行内容)"""
    return load_tkt_simple(tkt_path, full_strip=True)

def load_tkskill_names(sp, tkt):
    if not sp or not os.path.exists(sp): return {}
    with open(sp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    REC = 94
    names = {}
    # 兜底: 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % REC == 0 and (len(dec) == 0 or len(dec) % REC != 0):
        dec = raw
    for i in range(min(350, len(dec)//REC)):
        sid = struct.unpack_from('<h', dec, i*REC)[0]
        n = tkt.get(sid,"") or tkt.get(-sid,"") or f"Skill#{sid}"
        names[i] = n
    return names

# ============================================================
# 常量 (Maker.exe TksModify.dll 文案 + TKS.exe 反编译)
# ============================================================
# 31 种状态 (bit 0..30; Maker UI 状态列表) — STATUS_NAMES / STATUS_ICON_BASE
# 由 editor_utils.picker_dialogs 统一提供 (见下方导入)
# 战斗结算效果 (combat_flag, field [20]) — sub_42234C: a2[33] |= v9[20]; 战斗结算时按位检查
COMBAT_FLAG_BITS = [
    (1, "JP×2~3",              "战后技能点数×2~3 (無方戒; bit0)"),
    (2, "战后全恢复+异常全解",  "战斗结束HP/MP全恢复+清除异常 (無雙戒; bit1)"),
    (4, "经验×2~3平分队友",    "战斗经验×2~3并平分队友 (無嗔戒; bit2)"),
    (8, "经验独得",            "战斗经验归一人独享 (無道戒; bit3)"),
]
EXTRA_FLAG_BITS = [
    (0, "遇敌率降低",     "随机阈值140→遇敌率↓; 战斗时序+30% (偽裝戒指)"),  # sub_4084E0 bit0
    (1, "遇敌率大幅降低", "随机阈值200→遇敌率↓↓; 战斗时序+50% (隱藏戒指)"),  # sub_4084E0 bit1
    (2, "免遇敌",         "完全跳过随机战斗 (虛無戒指)"),  # sub_4084E0 bit2
    (3, "战斗时序加速",   "敌方计时条额外扣减(每回合) (無常戒)"),  # sub_431E70 bit3
    (4, "银两×2~5",      "物品描述声称此效果, 实际未实现 (無心戒)"),  # 逆向未找到实现
    (5, "战斗时序强效",   "敌方计时条强制扣减(更强效) (六無玄冥石)"),  # sub_431E70 bit5
]

# 使用权限 (equip_type) — 多选位掩码，选项根据页面号动态切换
#  sub_41928C: word_77CBD4[32*idx] & word_757FA4[527*char] → 权限位与校验
USE_RIGHT_OPTIONS = {
    0: [(1, "战斗"), (2, "非战斗")],                              # 药品
    1: [(1, "战斗"), (2, "非战斗"), (4, "主角限定")],              # 道具
    2: [(1, "刀"), (2, "剑"), (4, "枪"), (8, "矛"),
        (16, "弓"), (32, "大刀"), (64, "戟"), (128, "锤")],      # 武器
    3: [(1, "衣袍"), (2, "铠甲")],                                # 防具
    4: [(0, "通用")],                                             # 饰品
    5: [(0, "通用")],                                             # 特殊
}

def _use_right_label(val, page, opts=None):
    """根据页面号解析使用权限为可读文本 (opts 为空时回退到内置默认)"""
    if opts is None:
        opts = USE_RIGHT_OPTIONS.get(page, [])
    sel = [name for bit, name in opts if bit == 0 or (val & bit)]
    return ", ".join(sel) if sel else "(无)"

# 页面号 (tab_code, Maker UI 未显示; 商店分页, 0-5)
PAGE_NAMES = {0:"药品", 1:"道具", 2:"武器", 3:"防具", 4:"饰品", 5:"特殊"}
PAGE_VALUES = [f"{k}-{v}" for k,v in sorted(PAGE_NAMES.items())]

ITEM_REC = 64
ITEM_CNT = 600  # 游戏硬编码: sub_45343C(aTkitemDat, word_77CBCA, 38400)
W_INPUT = 12

# ============================================================
# 字段定义 - 严格按 Maker UI 文案 + 反编译证据
# (键, 字节偏移, UI标签, 类型, 宽度, 反编译注释)
# ============================================================
# 顶部基础属性网格 (Maker UI 可见字段 22 条; 技能/状态在下方分组)
GRID_FIELDS = [
    ("item_id",      0, "物品代码",       'int',       W_INPUT, "物品唯一标识，全游戏查找主键 (v15[0])"),
    ("name_id",      4, "名称代码",       'tkt',       W_INPUT, "TKT 文本数据库 ID，用于物品显示名称 (v15[2])"),
    ("desc_id",      6, "说明代码",       'tkt',       W_INPUT, "TKT 文本数据库 ID，用于物品描述文本 (v15[3])"),
    ("icon",         8, "形象",           'icon',      W_INPUT, "背包/商店显示图标的精灵索引，实际值 +130 (v15[4])"),
    ("equip_type",  10, "使用权限",       'use_right', W_INPUT, "角色武器专精位掩码，控制谁可装备/使用此物品 (v15[5])"),
    ("tkkon_index", 12, "TKKon索引",       'int',       W_INPUT, "TKKon.dat 记录索引 (0-649). 战斗使用物品时: Item→TKKon→cond_id→TKAct动画 (v15[6])"),
    ("hp_inc",      14, "增加生命",       'int',       W_INPUT, "永久增加生命上限，≤1000固定值，>1000为百分比加成 (v15[7])"),
    ("hp_heal",     16, "恢复生命",       'int',       W_INPUT, "使用后回复当前 HP，≤1000固定值，>1000为百分比回复 (v15[8])"),
    ("mp_inc",      18, "增加内力",       'int',       W_INPUT, "永久增加内力上限，≤1000固定值，>1000为百分比加成 (v15[9])"),
    ("mp_heal",     20, "恢复内力",       'int',       W_INPUT, "使用后回复当前 MP，≤1000固定值，>1000为百分比回复 (v15[10])"),
    ("atk",         22, "增加攻击",       'int',       W_INPUT, "武力(STR)永久加成，同时增加基础值和当前值 (v15[11])"),
    ("def_",        24, "增加防御",       'int',       W_INPUT, "智力(INT)永久加成，同时增加基础值和当前值 (v15[12])"),
    ("hit",         26, "增加命中",       'int',       W_INPUT, "统御(CMD)永久加成，同时增加基础值和当前值 (v15[13])"),
    ("dodge",       28, "增加闪避",       'int',       W_INPUT, "敏捷(AGI)永久加成，同时增加基础值和当前值 (v15[14])"),
    ("spd",         30, "增加速度",       'int',       W_INPUT, "速度(SPD)永久加成，上限100 (v15[15])"),
    ("luk",         32, "增加幸运",       'int',       W_INPUT, "运气(LUK)永久加成，商店物品出现条件的基准值 (v15[16])"),
    ("spi",         34, "增加悟性",       'int',       W_INPUT, "精神(SPI)悟性永久加成 (v15[17])"),
    ("vit",         36, "增加移动",       'int',       W_INPUT, "体力(VIT)移动永久加成 (v15[18])"),
    ("jp_bonus",    38, "增加技能点",     'int',       W_INPUT, "技能点数(JP); 使用时增加, 学习技能时消耗, 判定技能可用性 (v15[19])"),  # sub_41E40C, sub_41E248, sub_4189BC
    ("combat_flag", 40, "战斗结算效果",   'combat_flag', W_INPUT, "战斗结算位掩码; 战斗结束后按位触发奖励效果 (v15[20])"),  # sub_42234C: a2[33]|=v9[20]
    ("medicine",    50, "增加医术",       'int',       W_INPUT, "使用后获得的医术点数，累加到全局医术计数 (v15[25])"),
    ("price",       62, "价格",           'int',       W_INPUT, "物品买卖价格，商店卖出时折半 (v15[31])"),
]

# 技能组 (4 个字段; 全部对应全局技能等级表)
SKILL_FIELDS = [
    ("attach_skill",    42, "附加技能",         "装备后直接施加技能被动效果(属性加成等)，不写入技能栏 (v15[21])"),
    ("equip_learn",     44, "装备后学习技能",   "⚠ 仅升级已有技能(1-19→10级)，不会从零教会！未习得技能无效果 (v15[22])"),
    ("use_learn1",      46, "使用后学习技能1",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[23])"),
    ("use_learn2",      48, "使用后学习技能2",  "使用时学会技能(10级)；负数索引可从零教会全局技能 (v15[24])"),
]

# 导致状态 (装备/命中时让目标进入异常状态; 干將莫邪[26]=0x03=破兵+碎甲; 紅顏知己[27]=0x1000=迷恋)
CAUSE_MASK_FIELDS = [
    ("cause_mask1", 52, "导致状态 1-16",  "装备/命中时让目标进入的状态位掩码，每位对应状态表第 i 项 (v15[26])"),
    ("cause_mask2", 54, "导致状态 17-32", "装备/命中时让目标进入的状态位掩码，每位对应状态表第 16+i 项 (v15[27])"),
]

# 解除状态 (使用物品时按位清除角色异常状态)
CURE_MASK_FIELDS = [
    ("cure_mask1", 56, "解除状态 1-16",  "使用物品时解除的状态位掩码，每位对应状态表第 i 项 (v15[28])"),
    ("cure_mask2", 58, "解除状态 17-32", "使用物品时解除的状态位掩码，每位对应状态表第 16+i 项 (v15[29])"),
]

# 隐含字段 (TKItem 记录占用但 Maker UI 未显示，读写透传保留原始数据)
HIDDEN_FIELDS = [
    ("tab_code",     2, "页面号",       'page', W_INPUT, "物品在商店中的分页编号 (0=药品,1=道具,2=武器,3=防具,4=饰品,5=特殊)"),
    ("extra_flags", 60, "额外标志",     'extra_flags', W_INPUT, "地图/战斗全局标志 (v15[30])"),  # sub_41F784 OR到dword_755C80
]

ALL_FIELDS = (GRID_FIELDS + HIDDEN_FIELDS +
              [(k,o,l,'skill',W_INPUT,c) for k,o,l,c in SKILL_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CAUSE_MASK_FIELDS] +
              [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CURE_MASK_FIELDS])

# ============================================================
# 空槽/显示名辅助
# ============================================================
def is_empty_item(rec, tkt=None):
    """严格空槽: item_id in (0,1) 或 name_id<=0 或 tkt 中无对应名称.
    - #560-#599 真空槽: id=0 & name_id=0 (可新增物品复用)
    - id=1 占位: 约 225 条游戏保留记录 (#550-559 等)
    - 无 TKT 名: 孤立记录, 无法显示
    """
    if rec.get('item_id', 0) in (0, 1): return True
    if rec.get('name_id', 0) <= 0: return True
    if tkt is not None:
        nm = tkt.get(rec['name_id'], "")
        if not nm or not nm.strip(): return True
    return False

def is_pure_empty_slot(rec):
    """真·空槽 (可作新增物品起始模板): item_id==0 AND name_id==0."""
    return rec.get('item_id', 0) == 0 and rec.get('name_id', 0) == 0

def item_display_name(rec, tkt):
    if is_empty_item(rec, tkt):
        return f"(空槽 #{rec['index']})"
    nid = rec['name_id']
    if nid > 0 and nid in tkt:
        return tkt[nid]
    return f"ID#{rec['item_id']}"

# ============================================================
# 数据加载/保存
# ============================================================
def load_items(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % ITEM_REC == 0 and (len(dec) == 0 or len(dec) % ITEM_REC != 0):
        dec = raw
    recs = []
    for i in range(ITEM_CNT):
        off = i * ITEM_REC
        if off + ITEM_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h'*32, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _, _ in ALL_FIELDS:
            rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_items(fp, recs):
    buf = bytearray(ITEM_CNT * ITEM_REC)
    # 空槽模板 (#560-#599 原始值: name_id=0, desc_id=600) 在保存时保持 desc_id=600
    for rec in recs[:ITEM_CNT]:
        i = rec['index']
        off = i * ITEM_REC
        for k, fo, _, _, _, _ in ALL_FIELDS:
            struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True

class SkillPickerDialog(QDialog):
    def __init__(self, parent, skill_names, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(460, 550)
        self.selected_index = None
        self.skill_names = skill_names
        layout = QVBoxLayout(self)
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['索引', '技能名称'])
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("清空选择", clicked=self._clear))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept_selection))
        layout.addLayout(bl)
        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower()
        self.table.setRowCount(0)
        row = 0
        for idx in sorted(self.skill_names.keys()):
            nm = self.skill_names[idx]
            if q and q not in f"{idx} {nm}".lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(nm[:60]))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

    def _clear(self):
        self.selected_index = 0
        self.accept()

class IconPickerDialog(QDialog):
    def __init__(self, parent, mu_sprites, get_pixmap_fn, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择图标 (索引 = 游戏值 + 130)")
        self.resize(780, 560)
        self.selected_value = None
        self.mu_sprites = mu_sprites
        self.get_pixmap_fn = get_pixmap_fn
        self.cur_val = cur_val
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setSpacing(2)
        COLS = 12
        for si in range(len(mu_sprites)):
            if mu_sprites[si] is None: continue
            game_idx = si - 130
            r, c = divmod(si, COLS)
            btn = QPushButton()
            btn.setFixedSize(52, 56)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("selected", "true" if game_idx == cur_val else "false")
            pix = get_pixmap_fn(game_idx, (40, 40))
            if pix:
                btn.setIcon(QIcon(pix))
                btn.setIconSize(pix.size())
            btn.setText(str(game_idx))
            btn.setToolTip(f"精灵索引: {si}\n游戏值: {game_idx}")
            btn.clicked.connect(lambda checked, v=game_idx: self._select(v))
            self.grid.addWidget(btn, r, c)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QLabel("点击图标选择，索引 = 游戏精灵索引 - 130"))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        layout.addLayout(bl)

    def _select(self, v):
        self.selected_value = v
        self.accept()

class FlagPickerDialog(QDialog):
    """通用位标志选择弹窗 (combat_flag / extra_flags)"""
    def __init__(self, parent, title, flag_bits, cur_val, use_bit_shift=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 280)
        self.selected_mask = None
        self.use_bit_shift = use_bit_shift
        layout = QVBoxLayout(self)
        self.checkboxes = []
        for bit, name, desc in flag_bits:
            row = QHBoxLayout()
            mask = (1 << bit) if use_bit_shift else bit
            cb = QCheckBox(f"{name}" + (f" (bit{bit})" if use_bit_shift else ""))
            cb.setChecked(bool(cur_val & mask))
            self.checkboxes.append((mask, cb))
            row.addWidget(cb)
            row.addWidget(QLabel(desc), 1)
            layout.addLayout(row)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._ok)
        bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _ok(self):
        m = 0
        for mask, cb in self.checkboxes:
            if cb.isChecked():
                m |= mask
        if m >= 0x8000:
            m -= 0x10000
        self.selected_mask = m
        self.accept()

class UseRightPickerDialog(QDialog):
    def __init__(self, parent, opts, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择使用权限 (多选位掩码)")
        self.resize(320, 90 + max(len(opts), 2) * 28)
        self.selected_mask = None
        layout = QVBoxLayout(self)
        # 手动输入框: MOD 可能使用超出内置预定义的位掩码，允许直接输入任意数值
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("当前值:"))
        self.manual_edit = QLineEdit(str(cur_val))
        self.manual_edit.setPlaceholderText("可直接输入任意数值 (含 MOD 扩展位)")
        manual_row.addWidget(self.manual_edit, 1)
        layout.addLayout(manual_row)
        self.checkboxes = []
        for bit, name in opts:
            cb = QCheckBox(f"{bit}-{name}" if bit != 0 else name)
            cb.setChecked(bool(cur_val & bit) if bit != 0 else False)
            cb.toggled.connect(self._sync_from_boxes)
            self.checkboxes.append((bit, cb))
            layout.addWidget(cb)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._ok)
        bl.addWidget(btn_ok)
        layout.addLayout(bl)

    def _sync_from_boxes(self):
        """勾选框变动时同步到手动输入框"""
        m = 0
        for bit, cb in self.checkboxes:
            if cb.isChecked():
                m |= bit
        self.manual_edit.setText(str(m))

    def _ok(self):
        try:
            m = int(self.manual_edit.text().strip() or 0)
        except ValueError:
            m = 0
        m &= 0xFFFF                      # equip_type 为 16 位字段
        if m >= 0x8000:
            m -= 0x10000      # 转有符号
        self.selected_mask = m
        self.accept()

# ============================================================
# GUI 核心编辑器
# ============================================================
class ItemEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(format_title("item_editor"))
        self.resize(1360, 860)
        self.setMinimumSize(1120, 700)

        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True
        apply_godot_theme(self, self._is_dark)

        self.item_path = self.tkt_path = self.skill_path = self.mu_path = None
        self.records = []
        self.tkt = {}
        self.tkt_full = {}
        self.skill_names = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self._mu_sprites = []
        self._icon_pixmaps = {}
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = None
        self._sort_reverse = False
        self._guard_right_reset = False
        # 使用权限选项运行时副本 (启动时自动从 configs/ 加载)
        self._use_right_options = {p: list(opts) for p, opts in USE_RIGHT_OPTIONS.items()}
        # 启动时自动从 configs/ 加载 equip_type_labels.json
        self._auto_load_use_right_config()

        self.widget_map = {}
        self.extra_map = {}

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        self.setStyleSheet(ThemeManager.dark_qss() if self._is_dark else ThemeManager.light_qss())
        self._update_paths()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        self._refresh_table()
        apply_godot_theme(self, self._is_dark)

    def _create_dock(self, title, widget_content):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content)

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)
        em = mb.addMenu("编辑(&E)")
        em.addAction("新建物品 (填充空槽)\tCtrl+N", self._new_item)
        em.addAction("复制当前到空槽", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)
        hm = mb.addMenu("帮助(&H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("字段来源 (逆向+Maker)", self._show_field_ref)
        hm.addAction("关于编辑器", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("页面号:"))
        self.filter_page = NoWheelComboBox()
        self.filter_page.addItems(["全部页面"] + PAGE_VALUES)
        self.filter_page.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_page)
        toolbar.addSpacing(6)
        toolbar.addWidget(QLabel("权限:"))
        self.filter_right = NoWheelComboBox()
        self.filter_right.addItems(["全部权限"])
        self.filter_right.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_right)
        toolbar.addSpacing(6)
        self.filter_empty = QCheckBox("仅非空")
        self.filter_empty.setChecked(True)
        self.filter_empty.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_empty)
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("新建物品", clicked=self._new_item))
        toolbar.addWidget(QPushButton("重新加载", clicked=self._reload))
        toolbar.addStretch()
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主分割窗口
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # 左侧: 物品列表 (列顺序与原版一致: 图标在最前)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['图标', '#', 'ID', '页面', '物品名称', '权限', '价格'])
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 40)
        self.table.setColumnWidth(2, 50)
        self.table.setColumnWidth(3, 50)
        self.table.setColumnWidth(4, 160)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 50)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(36, 36))
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by)
        self.splitter.addWidget(self._create_dock("物品列表", self.table))

        # 右侧: 编辑器
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 顶部行: 记录标签 + 操作按钮
        header_row = QHBoxLayout()
        self.lbl_rec_idx = QLabel("未选中")
        self.lbl_rec_idx.setProperty("class", "RecordHeader")
        header_row.addWidget(self.lbl_rec_idx)
        header_row.addStretch()
        header_row.addWidget(QPushButton("✅ 应用", clicked=self._apply_edit))
        header_row.addWidget(QPushButton("📋 复制到空槽", clicked=self._copy_record))
        header_row.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit))
        header_row.addWidget(QPushButton("🗑 清空", clicked=self._clear_current))
        right_layout.addLayout(header_row)

        # 滚动编辑区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.edit_inner = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_inner)
        self.edit_layout.setContentsMargins(4, 4, 16, 4)
        self.edit_layout.setSpacing(4)

        # 预览面板
        self._build_preview()

        # 基础属性网格
        self._build_field_group("基础属性", GRID_FIELDS, 5)
        # 技能组
        self._build_field_group("技能", [(k,o,l,'skill',W_INPUT,c) for k,o,l,c in SKILL_FIELDS], 5)
        # 状态组
        status_fields = [(k,o,l,'mask',W_INPUT,c) for k,o,l,c in CAUSE_MASK_FIELDS + CURE_MASK_FIELDS]
        self._build_field_group("状态位掩码 (导致/解除)", status_fields, 5)
        # 隐含字段
        self._build_field_group("隐含数据 (保留原始数据)", HIDDEN_FIELDS, 5)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)
        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setSizes([560, 800])

        # 底部路径栏
        path_layout = QHBoxLayout()
        self.lbl_item = QLabel("TKItem.dat: 未加载")
        self.lbl_tkt = QLabel("TKT.dat: 未加载")
        self.lbl_skill = QLabel("TKSkill.dat: 未加载")
        self.lbl_mu = QLabel("Mu.JVG: 未加载")
        path_layout.addWidget(self.lbl_item)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_skill)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_mu)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_preview(self):
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(8, 12, 8, 12)
        pl.setSpacing(6)

        # 名称 + 图标
        top_row = QHBoxLayout()
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        top_row.addWidget(self.preview_name, 1)
        self.preview_icon = QLabel()
        top_row.addWidget(self.preview_icon)
        pl.addLayout(top_row)

        # 元数据
        self.preview_meta = QLabel("")
        self.preview_meta.setProperty("class", "PreviewMeta")
        self.preview_meta.setWordWrap(True)
        pl.addWidget(self.preview_meta)

        # 说明
        self.preview_desc = QLabel("请在左侧列表中选择物品。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.preview_desc)

        # 技能预览 (4列)
        skill_row = QHBoxLayout()
        skill_labels = ["附加技能", "装备后学习", "使用后学习1", "使用后学习2"]
        self._preview_skills = []
        for slbl in skill_labels:
            col = QVBoxLayout()
            lbl_t = QLabel(f"{slbl}:")
            lbl_t.setProperty("class", "PropLabel")
            col.addWidget(lbl_t)
            lbl_v = QLabel("—")
            lbl_v.setProperty("class", "PreviewDesc")
            lbl_v.setWordWrap(True)
            col.addWidget(lbl_v)
            self._preview_skills.append(lbl_v)
            skill_row.addLayout(col)
        pl.addLayout(skill_row)

        # 状态预览 (4列, QGridLayout 确保标题和内容行对齐)
        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(8)
        status_grid.setVerticalSpacing(2)
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_labels = ["导致状态 1-16", "导致状态 17-32", "解除状态 1-16", "解除状态 17-32"]
        self._preview_status_containers = []
        for si, slbl in enumerate(status_labels):
            lbl_t = QLabel(f"{slbl}:")
            lbl_t.setProperty("class", "PropLabel")
            status_grid.addWidget(lbl_t, 0, si, Qt.AlignTop)
            container = QWidget()
            container_layout = FlowLayout(margin=0, spacing=2)
            container.setLayout(container_layout)
            status_grid.addWidget(container, 1, si, Qt.AlignTop)
            self._preview_status_containers.append(container)
        for si in range(4):
            status_grid.setColumnStretch(si, 1)
        pl.addLayout(status_grid)

        self.edit_layout.addWidget(preview_frame)

    def _build_field_group(self, title, fields, cols):
        group_widget = QWidget()
        v_layout = QVBoxLayout(group_widget)
        v_layout.setContentsMargins(0, 4, 0, 4)
        v_layout.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "InspectorTitle")
        v_layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(8)
        grid.setContentsMargins(10, 0, 0, 0)

        for fi, field_def in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, field_def)

        # 所有列等宽
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        # 填充末行空白占位，防止列宽不均
        if fields:
            last_row_count = len(fields) % cols
            if last_row_count != 0:
                last_row = len(fields) // cols
                for c in range(last_row_count, cols):
                    spacer = QWidget()
                    grid.addWidget(spacer, last_row, c)

        v_layout.addLayout(grid)
        self.edit_layout.addWidget(group_widget)

    def _build_field(self, grid, row, col, field_def):
        fn, fo, fl = field_def[0], field_def[1], field_def[2]
        ft = field_def[3] if len(field_def) > 3 else 'int'
        cmt = field_def[5] if len(field_def) > 5 else (field_def[4] if len(field_def) > 4 else "")

        cell = QVBoxLayout()
        cell.setSpacing(2)
        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        if ft == 'page':
            cb = NoWheelComboBox()
            cb.addItems(PAGE_VALUES)
            cell.addWidget(make_fake_input(combo=cb))
            self.widget_map[fn] = cb
            self.extra_map[fn] = None
        elif ft in ('tkt', 'icon', 'use_right', 'combat_flag', 'extra_flags', 'skill'):
            inp = QLineEdit()
            btn = QPushButton("...")
            btn.setFixedWidth(28)
            btn.setCursor(Qt.PointingHandCursor)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            box = make_fake_input(line_edit=inp, button=btn, stretch=False)
            cell.addWidget(box)
            cell.addWidget(extra)
            self.widget_map[fn] = inp
            self.extra_map[fn] = extra
            if ft == 'tkt':
                btn.clicked.connect(lambda _, f=fn: self._pick_tkt(f))
            elif ft == 'icon':
                btn.clicked.connect(lambda _, f=fn: self._pick_icon(f))
            elif ft == 'use_right':
                btn.clicked.connect(lambda _, f=fn: self._pick_use_right(f))
            elif ft == 'combat_flag':
                btn.clicked.connect(lambda _, f=fn: self._pick_combat_flags(f))
            elif ft == 'extra_flags':
                btn.clicked.connect(lambda _, f=fn: self._pick_extra_flags(f))
            elif ft == 'skill':
                btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))
        elif ft == 'mask':
            is_cause = fn.startswith('cause_')
            btn = QPushButton("选择导致状态…" if is_cause else "选择解除状态…")
            hidden = QLineEdit()
            hidden.hide()
            box = QFrame()
            box.setObjectName("FakeInputBox")
            box.setFixedHeight(28)
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            bh.addWidget(btn, 1)
            self.widget_map[fn] = hidden
            status_frame = QWidget()
            status_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.extra_map[fn] = status_frame
            btn.clicked.connect(lambda _, f=fn: self._pick_status(f))
            cell.addWidget(box)
            cell.addWidget(status_frame, 1)
        else:
            inp = QLineEdit()
            cell.addWidget(make_fake_input(line_edit=inp))
            self.widget_map[fn] = inp
            self.extra_map[fn] = None

        grid.addLayout(cell, row, col, Qt.AlignTop)

    # ── 启用/禁用编辑 ──
    def _set_edit_enabled(self, en):
        self.edit_inner.setEnabled(en)

    def _update_paths(self):
        update_path_labels([
            (self.lbl_item, self.item_path, 'TKItem'),
            (self.lbl_tkt, self.tkt_path, 'TKT'),
            (self.lbl_skill, self.skill_path, 'TKSkill'),
            (self.lbl_mu, self.mu_path, 'Mu.JVG'),
        ], self._is_dark)

    # ── 数据加载 ──
    def _load_tks_dir(self):
        d = pick_tks_directory(self)
        if not d: return
        it = os.path.join(d, "TKItem.dat")
        tk_ = os.path.join(d, "TKT.dat")
        sk = os.path.join(d, "TKSkill.dat")
        if not os.path.exists(it):
            QMessageBox.warning(self, "文件缺失", "未找到 TKItem.dat")
            return
        self.item_path = it
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.skill_path = sk if os.path.exists(sk) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        if not os.path.exists(self.mu_path):
            self.mu_path = None
        self._reload()

    def _reload(self):
        if not self.item_path: return
        self.status_var.setText("加载中…")
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        else:
            self.tkt_full = {}
        if self.skill_path:
            self.skill_names = load_tkskill_names(self.skill_path, self.tkt)
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()
        try:
            self.records = load_items(self.item_path)
            self._dirty = False
            # MOD 导出使用原始字节序 (word index = byte_offset // 2)，与启动器 _apply_fields_to_record 一致
            self._original_records = []
            for rec in self.records:
                row = [0] * 32
                for k, fo, _, _, _, _ in ALL_FIELDS:
                    row[fo // 2] = rec[k]
                self._original_records.append(row)
            self.status_var.setText(f"{len(self.records)} 条 | TKT {len(self.tkt)} 条 | 技能 {len(self.skill_names)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    # ── 图标 ──
    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    # ── 筛选/列表 ──
    def _update_right_options(self, page_filter_text):
        """根据页面筛选值动态填充权限下拉框选项"""
        if page_filter_text.startswith("全部"):
            seen = set()
            all_opts = []
            for page in sorted(self._use_right_options):
                for bit, name in self._use_right_options[page]:
                    key = (bit, name)
                    if key not in seen:
                        seen.add(key)
                        all_opts.append(f"{bit}-{name}")
        else:
            page = int(page_filter_text.split('-')[0])
            opts = self._use_right_options.get(page, [])
            all_opts = [f"{bit}-{name}" for bit, name in opts]
        new_vals = ["全部权限"] + all_opts
        current_vals = [self.filter_right.itemText(i) for i in range(self.filter_right.count())]
        if new_vals != current_vals:
            self._guard_right_reset = True
            self.filter_right.clear()
            self.filter_right.addItems(new_vals)
            self.filter_right.setCurrentIndex(0)  # 重置为"全部权限"
            self._guard_right_reset = False

    def _apply_filter(self):
        if self._guard_right_reset: return
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        fpg = self.filter_page.currentText()
        self._update_right_options(fpg)
        frg = self.filter_right.currentText()
        for rec in self.records:
            if self.filter_empty.isChecked() and is_empty_item(rec, self.tkt): continue
            if fpg and not fpg.startswith("全部"):
                if rec['tab_code'] != int(fpg.split('-')[0]): continue
            if frg and not frg.startswith("全部"):
                bit = int(frg.split('-')[0])
                if bit == 0:
                    if rec['equip_type'] != 0: continue
                else:
                    if (rec['equip_type'] & bit) == 0: continue
            if q:
                nm = item_display_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['item_id']} {rec['tab_code']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        empty_cnt = sum(1 for r in self.records if is_pure_empty_slot(r))
        self.status_var.setText(
            f"显示 {len(self.filtered_indices)}/{len(self.records)} | 真空槽剩余 {empty_cnt}/40 | Ctrl+S 保存")

    def _clear_filter(self):
        self.search_entry.clear()
        self.filter_page.setCurrentIndex(0)
        self.filter_right.setCurrentIndex(0)
        self.filter_empty.setChecked(True)
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            et = r['equip_type']
            rt = _use_right_label(et, r.get('tab_code', 0), self._use_right_options.get(r.get('tab_code', 0))) if et or et == 0 else "—"
            self.table.insertRow(row)
            # 列顺序: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
            icon_item = QTableWidgetItem()
            pix = self._get_icon_pixmap(r['icon'], (36, 36))
            if pix:
                icon_item.setIcon(QIcon(pix))
            self.table.setItem(row, 0, icon_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 2, QTableWidgetItem(str(r['item_id'])))
            self.table.setItem(row, 3, QTableWidgetItem(PAGE_NAMES.get(r['tab_code'], '?')))
            self.table.setItem(row, 4, QTableWidgetItem(item_display_name(r, self.tkt)))
            self.table.setItem(row, 5, QTableWidgetItem(rt))
            self.table.setItem(row, 6, QTableWidgetItem(str(r['price'])))
        self.table.blockSignals(False)

    def _sort_by(self, col):
        """按列排序"""
        # 列: 图标(0) #(1) ID(2) 页面(3) 物品名称(4) 权限(5) 价格(6)
        km = {2:'item_id', 3:'tab_code', 5:'equip_type', 6:'price'}
        key = km.get(col, 'index')
        self.filtered_indices.sort(key=lambda i: self.records[i].get(key, 0), reverse=self._sort_reverse)
        self._sort_reverse = not self._sort_reverse
        self._refresh_table()

    # ── 编辑 ──
    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 1).text())  # 列1=索引 (列0=图标)
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        """填充编辑区字段"""
        self._editing_idx = rec['index']
        self.lbl_rec_idx.setText(
            f"记录 #{rec['index']}   物品代码={rec['item_id']}   "
            f"页面号={PAGE_NAMES.get(rec['tab_code'],'?')}   "
            f"名称={item_display_name(rec, self.tkt)}")

        # 预览
        nid = rec.get('name_id', 0) or 0
        did = rec.get('desc_id', 0) or 0
        n_txt = self.tkt.get(int(nid), "") if nid > 0 else ""
        self.preview_name.setText(n_txt if n_txt else "(无 / TKT 未提供)")
        d_txt = self.tkt_full.get(int(did), "") if did > 0 else ""
        self.preview_desc.setText(d_txt if d_txt else "(无 / TKT 未提供)")

        # 元数据
        page_str = PAGE_NAMES.get(rec['tab_code'], '?')
        et_label = _use_right_label(rec.get('equip_type', 0), rec.get('tab_code', 0), self._use_right_options.get(rec.get('tab_code', 0)))
        self.preview_meta.setText(f"页面={page_str}  |  权限={et_label}  |  价格={rec['price']}  |  图标={rec.get('icon',0)}")

        # 图标预览
        pix = self._get_icon_pixmap(rec.get('icon', 0), (40, 40))
        if pix:
            self.preview_icon.setPixmap(pix)
        else:
            self.preview_icon.clear()

        # 技能预览
        skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
        for si, sk in enumerate(skill_keys):
            sid = int(rec.get(sk, 0)) if rec.get(sk, 0) else -1
            if sid > 0:
                nm = self.skill_names.get(sid, f"技能#{sid}")
                self._preview_skills[si].setText(nm)
            else:
                self._preview_skills[si].setText("—")

        # 状态预览
        status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
        for si, sk in enumerate(status_keys):
            mask = int(rec.get(sk, 0)) if rec.get(sk, 0) else 0
            base = 0 if sk.endswith('_mask1') else 16
            sel = [(base+i, STATUS_NAMES[base+i]) for i in range(16) if mask & (1 << i) and base+i < len(STATUS_NAMES)]
            self._update_preview_status(si, sel)

        # 填充字段
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            val = rec[fn]
            sv = str(val)
            w = self.widget_map.get(fn)
            if not w: continue
            if ft == 'page':
                for i in range(w.count()):
                    if w.itemText(i).startswith(f"{val}-"):
                        w.setCurrentIndex(i)
                        break
            else:
                w.setText(sv)

            if ft == 'tkt':
                tid = int(val) if val else 0
                txt = self.tkt.get(tid, "") if tid > 0 else ""
                t = txt.split('\n')[0] if txt else ""
                self.extra_map[fn].setText((t[:12]+'...') if len(t) > 12 else t)
            elif ft == 'use_right':
                page = rec.get('tab_code', 0)
                self.extra_map[fn].setText(_use_right_label(int(val) if val else 0, page, self._use_right_options.get(page)))
            elif ft == 'combat_flag':
                self._update_flag_label(fn, int(val) if val else 0, COMBAT_FLAG_BITS)
            elif ft == 'extra_flags':
                self._update_flag_label(fn, int(val) if val else 0, EXTRA_FLAG_BITS, use_bit_shift=True)
            elif ft == 'skill':
                sid = int(val) if val else -1
                nm = self.skill_names.get(sid, "(无)") if sid > 0 else "(无)"
                self.extra_map[fn].setText(nm[:30] if sid > 0 else "(无)")
            elif ft == 'mask':
                self._update_status_label(fn, int(val) if val else 0)
            elif ft == 'icon':
                ival = int(val) if val else 0
                self.extra_map[fn].setText(f"[图标 {ival}]")

    def _update_flag_label(self, fn, val, flag_bits, use_bit_shift=False):
        """更新标志位的标签显示"""
        mask = val & 0xFFFF
        sel = []
        for bit, name, _ in flag_bits:
            if use_bit_shift:
                if mask & (1 << bit):
                    sel.append(name)
            else:
                if mask & bit:
                    sel.append(name)
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_status_label(self, fn, mask):
        """更新状态标签显示 — 复用已有 layout，避免 deleteLater 引发的重复布局警告"""
        base = 0 if fn.endswith('_mask1') else 16
        is_cause = fn.startswith('cause_')
        status_class = "StatusInflict" if is_cause else "StatusRemove"
        frame = self.extra_map.get(fn)
        if not frame: return
        # 获取或创建 layout（只创建一次，后续复用）
        frame_layout = frame.layout()
        if not frame_layout:
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(0,0,0,0)
            frame_layout.setSpacing(1)
            frame_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # 清除所有子控件（保留 layout 本身）
        while frame_layout.count():
            item = frame_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        sel = [f"{base+i}.{STATUS_NAMES[base+i]}" for i in range(16)
               if (mask & (1 << i)) and base + i < len(STATUS_NAMES)]
        lbl = QLabel("  ".join(sel) if sel else "(无)")
        lbl.setWordWrap(True)
        lbl.setProperty("class", status_class)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
        frame_layout.addWidget(lbl)
        frame.updateGeometry()

    def _update_preview_status(self, si, sel):
        """更新预览区中单个状态列 (FlowLayout 左右排列，超出换行)"""
        container = self._preview_status_containers[si]
        # 清除旧内容
        layout = container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not sel:
            lbl = QLabel("—")
            lbl.setProperty("class", "PreviewDesc")
            layout.addWidget(lbl)
            return
        for idx, nm in sel:
            chip = QWidget()
            chip_lay = QHBoxLayout(chip)
            chip_lay.setContentsMargins(2, 1, 4, 1)
            chip_lay.setSpacing(2)
            # 始终为图标预留固定 16x16 空间
            il = QLabel()
            il.setFixedSize(16, 16)
            pix = self._get_icon_pixmap(STATUS_ICON_BASE + idx - 130, (16, 16))
            if pix:
                il.setPixmap(pix)
            chip_lay.addWidget(il)
            lbl = QLabel(nm)
            lbl.setProperty("class", "ChipLabel")
            chip_lay.addWidget(lbl)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            layout.addWidget(chip)

    # ── 弹窗: TKT ──
    def _pick_tkt(self, fn):
        """弹窗选择 TKT 文本"""
        if not self.tkt: return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = TktPickerDialog(self, self.tkt, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            self.widget_map[fn].setText(str(dlg.selected_id))
            txt = self.tkt.get(dlg.selected_id, "")
            t = txt.split('\n')[0] if txt else ""
            self.extra_map[fn].setText((t[:12]+'...') if len(t) > 12 else t)
            if fn == 'name_id':
                self.preview_name.setText(txt if txt else "(无)")
            elif fn == 'desc_id':
                d_txt = self.tkt_full.get(dlg.selected_id, "")
                self.preview_desc.setText(d_txt if d_txt else "(无 / TKT 未提供)")

    # ── 弹窗: 技能 ──
    def _pick_skill(self, fn):
        """弹窗选择技能"""
        if not self.skill_names: return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = SkillPickerDialog(self, self.skill_names, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = self.skill_names.get(dlg.selected_index, "") if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText(nm[:20] if nm else "(无)")
            skill_keys = ['attach_skill', 'equip_learn', 'use_learn1', 'use_learn2']
            if fn in skill_keys:
                self._preview_skills[skill_keys.index(fn)].setText(nm if nm else "—")

    # ── 弹窗: 图标 ──
    def _pick_icon(self, fn):
        """弹窗选择物品图标"""
        if not self._mu_sprites:
            QMessageBox.information(self, "提示", "未加载 Mu.JVG 图标文件")
            return
        cur_val = int(self.widget_map[fn].text() or 0)
        dlg = IconPickerDialog(self, self._mu_sprites, self._get_icon_pixmap, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_value is not None:
            self.widget_map[fn].setText(str(dlg.selected_value))
            self.extra_map[fn].setText(f"[图标 {dlg.selected_value}]")
            pix = self._get_icon_pixmap(dlg.selected_value, (40, 40))
            if pix:
                self.preview_icon.setPixmap(pix)
            else:
                self.preview_icon.clear()

    # ── 弹窗: 状态 mask ──
    def _pick_status(self, fn):
        """弹窗选择状态 mask 多选"""
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        base = 0 if fn.endswith('_mask1') else 16
        cur_mask = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = StatusPickerDialog(self, title, STATUS_NAMES, cur_mask, base, self._get_icon_pixmap, is_cause)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_status_label(fn, dlg.selected_mask & 0xFFFF)
            status_keys = ['cause_mask1', 'cause_mask2', 'cure_mask1', 'cure_mask2']
            if fn in status_keys:
                si = status_keys.index(fn)
                sel = [(base+i, STATUS_NAMES[base+i]) for i in range(16) if (dlg.selected_mask & 0xFFFF) & (1 << i) and base+i < len(STATUS_NAMES)]
                self._update_preview_status(si, sel)

    # ── 弹窗: 战斗结算效果 ──
    def _pick_combat_flags(self, fn):
        """弹窗选择战斗结算效果 (位掩码多选)"""
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = FlagPickerDialog(self, "选择战斗结算效果 (位掩码)", COMBAT_FLAG_BITS, cur_val, use_bit_shift=False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_flag_label(fn, dlg.selected_mask, COMBAT_FLAG_BITS)

    # ── 弹窗: 额外标志 ──
    def _pick_extra_flags(self, fn):
        """弹窗选择额外标志位"""
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = FlagPickerDialog(self, "选择额外标志 (位掩码)", EXTRA_FLAG_BITS, cur_val, use_bit_shift=True)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self._update_flag_label(fn, dlg.selected_mask, EXTRA_FLAG_BITS, use_bit_shift=True)

    # ── 弹窗: 使用权限 ──
    def _pick_use_right(self, fn):
        """弹窗选择使用权限 (根据当前页面号动态切换选项)"""
        if not self.records or self._editing_idx is None: return
        page = self.records[self._editing_idx].get('tab_code', 0)
        opts = self._use_right_options.get(page, [])
        # 仅有一个值为0的选项时，直接设为0
        if len(opts) == 1 and opts[0][0] == 0:
            self.widget_map[fn].setText("0")
            self.extra_map[fn].setText(_use_right_label(0, page, opts))
            return
        cur_val = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = UseRightPickerDialog(self, opts, cur_val)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            self.widget_map[fn].setText(str(dlg.selected_mask))
            self.extra_map[fn].setText(_use_right_label(dlg.selected_mask, page, opts))

    # ── 自动加载使用权限配置 ──
    def _auto_load_use_right_config(self):
        """启动时自动从 configs/equip_type_labels.json 加载使用权限标签。

        加载成功后整页替换内置默认；文件缺失或解析失败时静默回退到内置默认。
        支持开发环境和打包环境的路径解析。
        """
        path = resolve_config_path('equip_type_labels.json')
        if not path:
            return  # 配置文件不存在，使用内置默认
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return  # 解析失败，使用内置默认
        new_opts = {}
        try:
            for page_key, items in data.items():
                try:
                    page = int(page_key)
                except (ValueError, TypeError):
                    continue  # 跳过非整型键 (如 "_说明" 注释字段)
                pairs = [(int(it[0]), str(it[1])) for it in items]
                if pairs:
                    new_opts[page] = pairs
        except (TypeError, IndexError, ValueError):
            return  # 格式错误，使用内置默认
        if new_opts:
            self._use_right_options.update(new_opts)

    # ── 编辑应用 ──
    def _apply_edit(self):
        """应用编辑到记录"""
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
            try:
                w = self.widget_map.get(fn)
                if not w: continue
                if ft == 'page':
                    sv = w.currentText()
                    rec[fn] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)
                else:
                    v = int(w.text() or 0)
                    if v > 32767:
                        v = 32767
                    if v < -32768:
                        v = -32768
                    rec[fn] = v
            except ValueError:
                rec[fn] = 0
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 1).text()) == rec['index']:
                self.table.selectRow(r)
                break
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        """重置编辑区为当前记录"""
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _clear_current(self):
        """把当前选中记录清为空槽模板 (恢复 #560-599 原始值)."""
        if self._editing_idx is None:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return
        reply = QMessageBox.question(self, "确认清空",
            f"将记录 #{self._editing_idx} 清为空槽模板 (item_id=0, name_id=0, desc_id=600).\n确定?")
        if reply != QMessageBox.Yes: return
        rec = self.records[self._editing_idx]
        for fn, _, _, _, _, _ in ALL_FIELDS:
            rec[fn] = 0
        rec['desc_id'] = 600
        self._dirty = True
        self._apply_filter()
        self._populate_edit(rec)
        self.status_var.setText(f"记录 #{self._editing_idx} 已清空")

    def _copy_record(self):
        if self._editing_idx is None:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return
        src = self.records[self._editing_idx]
        for i, rec in enumerate(self.records):
            if is_pure_empty_slot(rec):
                for fn, fo, fl, ft, fw, cmt in ALL_FIELDS:
                    rec[fn] = src[fn]
                rec['index'] = i
                self._dirty = True
                self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 1).text()) == i:
                        self.table.selectRow(r)
                        break
                self.status_var.setText(f"已复制到空槽 #{i}")
                return
        QMessageBox.warning(self, "已满", "无真·空槽 (id=0 的记录) 可复制到.\n可先使用『清空此记录』释放一个槽位.")

    def _new_item(self):
        """新增物品: 在空槽 #560-#599 中找第一条 item_id=0 的记录, 填入默认值并选中.
        游戏硬编码限制 600 条, 无法扩容; 但 #560-#599 40 条空槽可用.
        """
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载 TKItem.dat")
            return
        target = None
        for rec in self.records:
            if is_pure_empty_slot(rec):
                target = rec
                break
        if target is None:
            # sub_45343C 硬编码 38400 字节
            QMessageBox.warning(self, "已满",
                "600 条记录上限已满\n无空槽 (id=0) 可用.")
            return
        # 填入默认值 (参考 #560-599 原始模板)
        for fn, _, _, _, _, _ in ALL_FIELDS:
            target[fn] = 0
        # 估算一个未占用的 item_id (避免碰撞)
        used_ids = {r['item_id'] for r in self.records if r['item_id'] > 0}
        new_id = 600
        while new_id in used_ids and new_id < 9999:
            new_id += 1
        target['item_id'] = new_id
        target['desc_id'] = 600  # 模板默认
        target['price'] = 1
        target['tab_code'] = 0
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 1).text()) == target['index']:
                self.table.selectRow(r)
                break
        # 选中新记录
        self._populate_edit(target)
        QMessageBox.information(self, "新建物品",
            f"已在空槽 #{target['index']} 创建新物品\n"
            f"初始 item_id={new_id} (请改为你想要的值)\n"
            f"请填写 名称代码/说明代码/其他属性, 然后 Ctrl+S 保存.")
        self.status_var.setText(f"新建物品: #{target['index']} item_id={new_id}")

    # ── 保存/导出 ──
    def _save(self):
        if not self.item_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        reply = QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.item_path}\n\n原文件将被覆盖 (生成 .bak).")
        if reply != QMessageBox.Yes: return
        try:
            with open(self.item_path, 'rb') as s:
                with open(self.item_path + ".bak", 'wb') as d:
                    d.write(s.read())
        except: pass
        try:
            self.status_var.setText("正在保存…")
            save_items(self.item_path, self.records)
            self._dirty = False
            self.status_var.setText(f"已保存 → {self.item_path}")
            QMessageBox.information(self, "保存成功", f"已保存\n备份: {self.item_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        if not self.records or not self._original_records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 构建原始字节序字段数组 (word index = byte_offset // 2)，与启动器一致
        current_fields = []
        for rec in self.records:
            row = [0] * 32
            for k, fo, _, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)
        diff_result = diff_records(self._original_records, current_fields, field_count, len(self._original_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        crc = compute_crc32(self.item_path) if self.item_path else "0x00000000"
        data_json = build_data_diff_json(target="TKItem.dat", record_size=64, field_type="int16",
            field_count=field_count, original_count=len(self._original_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKItem.dat.json", "target": "TKItem.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKItem.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 预构建当前字段数组
        current_fields = []
        for rec in self.records:
            row = [0] * 32
            for k, fo, _, _, _, _ in ALL_FIELDS:
                row[fo // 2] = rec[k]
            current_fields.append(row)
        field_count = len(ALL_FIELDS)

        def _compute_stats(ref_dir):
            ref_records = load_reference_dat_fields(ref_dir, "TKItem.dat",
                rec_size=64, field_count=32, field_fmt='h', use_lzss=True)
            if ref_records is None:
                return {"valid": False, "error": "目录中未找到 TKItem.dat"}
            diff = diff_records(ref_records, current_fields, field_count, len(ref_records))
            targets = []
            if diff['modified'] or diff['appended']:
                targets.append({"name": "TKItem.dat",
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": 0})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.item_path) if self.item_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        # 从参考目录加载并计算差异
        ref_records = load_reference_dat_fields(ref_dir, "TKItem.dat",
            rec_size=64, field_count=32, field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKItem.dat")
            return
        diff_result = diff_records(ref_records, current_fields, field_count, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        crc = compute_crc32(os.path.join(ref_dir, "TKItem.dat"))
        data_json = build_data_diff_json(target="TKItem.dat", record_size=64, field_type="int16",
            field_count=field_count, original_count=len(ref_records), original_crc32=crc, diff_result=diff_result)
        mod_json = generate_mod_json(metadata, [{"file": "data/TKItem.dat.json", "target": "TKItem.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/TKItem.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        if "TKItem.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 TKItem.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.item_path) if self.item_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        mod_json, records = import_tksmod_records(
            fp, ref_dir, "TKItem.dat",
            rec_size=64, field_count=len(ALL_FIELDS),
            field_fmt='h', use_lzss=True
        )
        if records is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 TKItem.dat")
            return

        # 将导入的字段数组（原始字节序）转化为编辑器内部记录格式
        new_records = []
        for i, fields in enumerate(records):
            rec = {'index': i}
            for k, fo, _, _, _, _ in ALL_FIELDS:
                word_idx = fo // 2
                rec[k] = fields[word_idx] if word_idx < len(fields) else 0
            new_records.append(rec)

        self.records = new_records
        self._original_records = [list(row) for row in records]
        self._dirty = False

        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(self.records)} 条物品")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 条记录。\n"
            f"您现在可以继续编辑并重新导出。")

    # ── 帮助 ──
    # 逆向参考: sub_45343C(数据载入), sub_41E40C(物品使用), sub_42234C(装备应用),
    # sub_422BBC(附加技能效果), sub_42F8D4(物品查找), sub_424A2C(背包/商店显示)
    def _show_field_ref(self):
        lines = ["TKItem.dat 字段映射:", ""]
        lines.append("【基础属性 (Maker UI 可见字段 22 条)】")
        for fn, fo, fl, ft, fw, cmt in GRID_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【技能 (Maker UI 4 字段)】")
        for fn, fo, fl, cmt in SKILL_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【导致状态 (Maker UI; 战斗时读取角色 a2[67]/a2[68])】")
        for fn, fo, fl, cmt in CAUSE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【解除状态 (使用物品时清除)】")
        for fn, fo, fl, cmt in CURE_MASK_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【隐含数据 (Maker UI 未显示, 但 TKItem 记录占用)】")
        for fn, fo, fl, ft, fw, cmt in HIDDEN_FIELDS:
            lines.append(f"  [{fo:02d}] {fl:<12s}  {cmt}")
        lines.append("")
        lines.append("【使用权限 (equip_type) 实测值】")
        for page, opts in sorted(USE_RIGHT_OPTIONS.items()):
            lines.append(f"  页面{page}({PAGE_NAMES.get(page,'?')}): {opts}")
        lines.append("")
        lines.append("【记录数硬限制】")
        lines.append("  600 条 x 64 字节 = 38400 字节 (游戏固定加载量)")
        lines.append("  物品数量上限为 600 条 (游戏内部限制)")
        lines.append("  #560-#599 (40条) 为空槽位, 可用于新增物品 (item_id=0, name_id=0)")
        dlg = QDialog(self)
        dlg.setWindowTitle("字段来源")
        dlg.resize(820, 580)
        layout = QVBoxLayout(dlg)
        from PySide6.QtWidgets import QTextEdit
        tx = QTextEdit()
        tx.setReadOnly(True)
        tx.setPlainText('\n'.join(lines))
        tx.setProperty("class", "MonoText")
        layout.addWidget(tx)
        dlg.exec()

    # 逆向参考: sub_45343C(数据载入), sub_41E40C(物品使用), sub_42234C(装备应用),
    # sub_422BBC(附加技能效果), sub_42F8D4(物品查找), sub_424A2C(背包/商店显示)
    def _show_help(self):
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            "功能: 编辑《三国群侠传》物品数据\n"
            "数据: 600 条记录 × 32 个字段 = 64 字节/条\n\n"
            "特性:\n"
            "  · 可视化编辑物品属性 (名称/价格/效果等)\n"
            "  · 自动关联 TKT.dat 显示物品名称\n"
            "  · 支持物品分类筛选和搜索\n"
            "  · 深色/浅色主题切换")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('item_editor'))

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()


def main():
    from editor_utils.app_init import install_translator, setup_app_icon
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")
    _t = install_translator(app)
    setup_app_icon(app, os.path.dirname(__file__))
    editor = ItemEditorApp()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
