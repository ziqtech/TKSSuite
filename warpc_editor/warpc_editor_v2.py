#!/usr/bin/env python3
"""
WarPC.dat 可视化编辑器 (PySide6 — Godot 4.6 风格)
===========================================================
逆向依据:
  - sub_45343C:     DAT 文件统一加载 (LZSS 解压, 1054字节/角色, 143角色)
  - sub_452B14:     LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_42234C:     装备/技能/属性应用 (字段 [5]-[10]/[11]-[26]/[32]-[42]/[67]-[72]/[86]-[87])
  - sub_41E40C:     物品使用效果 (字段 [11]-[26] 属性加成)
  - sub_422768:     角色初始化
  - sub_422BBC:     被动技能效果计算 (字段 [41]/[42]/[86]/[87])
  - sub_4173F8:     装备 ID→索引匹配 (字段 [69]-[72]←[73]-[76])
  - Maker.exe sub_4027FF: 校验解压后大小 150722 = 1054 × 143

WarPC.dat 格式 (每条 1054 字节, 共 143 角色):
  527 × int16 (小端序)

Tab 分区 (按字段索引顺序排列):
  Tab 1: 核心属性 [0]-[68]
  Tab 2: 装备与技能 [69]-[87] + [260]-[272]
  Tab 3: 技能学习状态 [88]-[259]
  Tab 4: 技能效果判定 [273]+
  Tab 5: 全部字段 (raw grid)

字段布局 (仅列出反编译已验证的字段; 未验证字段标注 "未验证"):
  [0]   name_id      — 角色名称 TKT ID
  [1]   portrait     — 头像索引 (×2=Fa.JVG大幅图, ×2+1=缩略图)
  [2]   level        — 等级
  [3]   role         — 身份 (-1=未激活 0=已激活(sub_410674 L40入队时置0))
  [4]   exp_to_next  — 升级所需经验 (大多数=100; BOSS版较高: 呂布5092 張角7292)
  [5]-[10]  HP/MP    — 当前/基础/上限
  [11]-[26] 8通用属性 — 攻击/防御/命中/闪避/速度/幸运/移动/悟性 (基础/当前)
  [27]-[31] 角色五维  — 智慧/仁德/勇气/医术/技能点数
  [32]-[40] 技能加成  — 来自 TKSkill 装备效果
  [41]-[42] 反应组    — 被动技能触发分类
  [43]-[50] 状态槽    — 8个状态效果槽
  [51]-[66] 状态抵抗  — 32状态×1byte
  [67]-[68] 导致状态  — 攻击导致状态掩码
  [69]-[76] 装备      — 索引缓存+装备ID
  [77]-[81] 使用权限  — 药品/道具/武器/防具/饰品
  [82]-[87] 装备技能  — 4装备技能+2被动技能
  [88]-[259] 技能学习 — 344技能×1byte
  [260]-[263] 补丁字段 — awk_sprite/portrait_menu/history_text/entity_link
  [264]-[266] 成长率   — 初期/中期/后期
  [268]-[269] 战后奖励 — JP/金
  [270]-[272] 掉落物品 — 3个物品ID
  [273]+     技能效果  — TKKon ID 映射表

用法:
  python warpc_editor_v2.py
"""

import json
import os
import struct
import sys
from functools import partial
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar, QTabWidget,
    QSpinBox, QSizePolicy, QMenu,
)
from PySide6.QtGui import QColor, QFont, QIcon, QIntValidator
from PySide6.QtCore import Qt, QTranslator, Signal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_manager import ThemeManager
from editor_utils.dock_components import DockHeader
from editor_utils.picker_dialogs import TktPickerDialog, StatusPickerDialog, STATUS_NAMES, ItemPickerDialog
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.ui_helpers import make_fake_input, update_path_labels, confirm_close, resolve_config_path, themed_messagebox, NoWheelComboBox
from editor_utils.version import format_title, format_about_header
from editor_utils.lzss import lzss_decompress_dat, lzss_compress_dat, lzss_decompress_save, lzss_compress_save
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.mod_exporter import (
    diff_records, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, ModMetadataDialog, safe_mod_filename,
    load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, ModImportPreviewDialog, ModExportPreviewDialog,
)
from editor_utils.window_theme import apply_godot_theme
from editor_utils.kon_name_resolver import KonNameResolver

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data):
    return lzss_decompress_dat(data)

def lzss_compress(data):
    return lzss_compress_dat(data)

def load_tkt(tkt_path):
    return load_tkt_simple(tkt_path)

def load_jvg_sprites(jvg_path):
    try:
        from PIL import Image
    except ImportError:
        return None
    if not jvg_path or not os.path.exists(jvg_path):
        return None
    with open(jvg_path, 'rb') as f:
        data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG':
        return None
    bc = struct.unpack_from('<I', data, 8)[0]
    off = 32
    sprites = []
    for bi in range(bc):
        if off + 32 > len(data) or data[off:off+4] != b'@JVM':
            break
        sc = struct.unpack_from('<I', data, off+4)[0]
        ds = struct.unpack_from('<I', data, off+12)[0]
        s1 = off + 32
        co = [struct.unpack_from('<I', data, s1+j*4)[0] for j in range(sc+1)]
        po = s1 + (sc+1)*4
        pal_entries = []
        for j in range(256):
            e = struct.unpack_from('<H', data, po+j*2)[0]
            r = ((e>>11)&0x1F)<<3; g = ((e>>5)&0x3F)<<2; b = (e&0x1F)<<3
            pal_entries.extend([r,g,b])
        pal_bytes = bytes(pal_entries)
        dr = po + 512
        for si in range(sc):
            mo = dr + co[si]
            ws = struct.unpack_from('<8H', data, mo)
            w, h = ws[2], ws[3]
            if w <= 0 or h <= 0:
                sprites.append(None)
                continue
            eo = mo + 16
            ed = data[eo:eo+co[si+1]-co[si]-16]
            total = w*h
            px = bytearray(total)
            alpha = bytearray(total)
            recs = []
            rp = 0
            while rp + 4 <= len(ed):
                sk = struct.unpack_from('<H', ed, rp)[0]; rw = struct.unpack_from('<H', ed, rp+2)[0]; rp += 4
                rw = min(rw, len(ed)-rp); rd = ed[rp:rp+rw] if rw>0 else b''; rp += rw
                recs.append((sk, rw, rd))
            if not recs:
                continue
            simple = (recs[0][0]==0 and recs[0][1]==w and all(r[1]==w for r in recs))
            if simple:
                for ri, (_, rw, rpix) in enumerate(recs):
                    if ri >= h:
                        break
                    tr = h-1-ri
                    for c in range(min(rw, len(rpix))):
                        px[tr*w+c] = rpix[rw-1-c]; alpha[tr*w+c] = 255
            else:
                scr_w = 640; gap = max(scr_w-w, 0); bp = total-1; pg = 0
                for sa, rw, rpix in recs:
                    rem = sa-pg; pg = 0
                    if rem < 0:
                        rem = 0
                    while rem > 0 and bp >= 0:
                        col = (total-1-bp)%w; tb = w-col
                        if rem <= tb: bp -= rem; rem = 0
                        else: bp -= tb; rem -= tb+gap; rem = max(rem, 0)
                    cb = (total-1-bp)%w if bp >= 0 else 0
                    al = min(rw, len(rpix))
                    for k in range(al):
                        if 0 <= bp < total: px[bp] = rpix[k]; alpha[bp] = 255
                        bp -= 1
                    pg = gap if al > 0 and cb+al >= w else 0
            if w > 0 and h > 0:
                img = Image.frombytes('P', (w, h), bytes(px)); img.putpalette(pal_bytes)
                rgba = img.convert('RGBA')
                a_img = Image.frombytes('L', (w, h), bytes(alpha)); rgba.putalpha(a_img)
                sprites.append(rgba)
        off += 32 + (sc+1)*4 + 512 + ds
    return sprites

# ═══════════════════════════════════════════════════════════════
# 常量 (100% 原始定义)
# ═══════════════════════════════════════════════════════════════

WARPC_REC = 1054
WARPC_FIELD_COUNT = 527
WARPC_ORIG_COUNT = 143
WARPC_ORIG_SIZE = 150722

# STATUS_NAMES 由 editor_utils.picker_dialogs 提供 (见上方导入)

COMBAT_FLAG_BITS = [
    (0, "JP×2~3", "战后技能点数×2~3"), (1, "战后全恢复+异常全解", "HP/MP全恢复+清除异常"),
    (2, "经验×2~3平分队友", "经验×2~3并平分队友"), (3, "经验独得", "经验归一人独享"),
]
MOVE_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻"), (1, "飙行", "移动范围扩大"),
    (2, "搜宝", "获得额外宝物"), (3, "解陷", "自动解除陷阱"),
]
FLAG_DEFS = {'special_flag': ("特殊能力标志", COMBAT_FLAG_BITS), 'move_flags': ("移动特殊标志", MOVE_FLAG_BITS)}

USE_RIGHT_DEFS = {
    'use_right_medicine': ("药品使用权限", [(1,"战斗"),(2,"非战斗")]),
    'use_right_item': ("道具使用权限", [(1,"战斗"),(2,"非战斗"),(4,"主角限定")]),
    'use_right_weapon': ("武器装备权限", [(1,"刀"),(2,"剑"),(4,"枪"),(8,"矛"),(16,"弓"),(32,"大刀"),(64,"戟"),(128,"锤")]),
    'use_right_armor': ("防具装备权限", [(1,"衣袍"),(2,"铠甲")]),
    'use_right_accessory': ("饰品使用权限", [(0,"通用")]),
}
# 页面号 → 权限字段名 (与 item_editor standard_config.json 的页面号语义一致)
# 页面 0=药品 1=道具 2=武器 3=防具 4=饰品 5=特殊; 5=特殊在 WarPC 中无对应字段，故不映射
USE_RIGHT_PAGE_TO_FIELD = {
    0: 'use_right_medicine', 1: 'use_right_item', 2: 'use_right_weapon',
    3: 'use_right_armor', 4: 'use_right_accessory',
}

SKILL_LEARN_COUNT = 344
SKILL_LEARN_STATES = ["0-不会","1-等待学","10-可以学","20-组技能学会","30-子技能学会"]

# 核心字段 — 已验证 (格式: key, offset, label, comment)
IDENTITY_FIELDS = [
    ("name_id",    0,  "名称TKT ID",  "角色名称 → TKT.dat"),  # sub_4067E8
    ("portrait",   2,  "头像索引",    "头像索引 ×2 = Fa.JVG 大幅图, ×2+1 = 缩略图"),
    ("level",      4,  "等级",        "角色等级 (数值显示)"),
    ("role",       6,  "身份",        "-1=未激活 0=已激活(入队时置0)"),  # sub_410674 L40
    ("exp_to_next", 8,  "升级所需经验","升至下一级所需经验; 绝大多数角色=100, BOSS版较高(呂布5092 張角7292)"),
]
# 补丁专用字段 [260]-[263] — 配合运行时补丁使用; 0=使用原硬编码公式
PATCH_FIELDS = [
    ("awk_sprite_id", 520, "战场图集索引（补丁专用）", "战斗中Awk.JVG/Awt.JVG块号; 0=使用原硬编码公式(PATH1:WarPC索引+6, PATH2:WarPC记录号+12); 非0=补丁直接使用此值"),
    ("portrait_menu_id", 522, "队伍头像ID（补丁专用）", "队伍菜单Mu.JVG精灵块号; 0=使用原公式(portrait+211); 非0=直接使用此值"),
    ("history_text_id", 524, "历史文本ID（补丁专用）", "角色界面「历史」标签页TKT文本ID; 0=使用原公式(9050+角色序号)"),  # sub_41A080:104
    ("entity_link", 526, "地图实体ID",  "离队后在地图上显示的NPC实体ID → TKMat.dat"),  # sub_41EEC0 → sub_40C648
]
HPMP_FIELDS = [
    ("cur_hp",    10,  "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",    12,  "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base",   14,  "HP基础",      "HP基础值"),
    ("hp_max",    16,  "HP上限",      "HP上限 (基础+装备)"),  # sub_42234C
    ("mp_base",   18,  "MP基础",      "MP基础值"),
    ("mp_max",    20,  "MP上限",      "MP上限 (基础+装备)"),  # sub_42234C
]

STAT_NAMES_CN = ["攻击","防御","命中","闪避","速度","幸运","移动","悟性"]
STAT_SHORTS = ["atk","def","hit","eva","spd","luk","mov","wis"]
STAT_BASE_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]
# 8 属性对 (基础/当前) — sub_42234C L24-31/63-70 验证
STAT_FIELDS = []
for i, (n, s, bo) in enumerate(zip(STAT_NAMES_CN, STAT_SHORTS, STAT_BASE_OFFSETS)):
    STAT_FIELDS.append((f"{s}_base", bo, f"{n}(基础)",
                        f"{n}基础值"))  # sub_42234C: a2[{11+i*2}]
    STAT_FIELDS.append((f"{s}_cur", bo+2, f"{n}(当前)",
                        f"{n}当前值 (基础+装备)"))  # sub_42234C L63-70 a2[{12+i*2}]+=v9[{11+i}]

# 技能加成区 [32]-[40] — sub_422BBC 应用 TKSkill 效果, sub_42234C 初始化
SKILL_BONUS_FIELDS = [
    ("atk_count",   64,  "攻击次数",       "攻击次数 (含TKSkill增加的攻击次数)"),  # sub_42234C=1; sub_422BBC L29: a2[32]+=v6[31]
    ("special_flag",66,  "特殊能力标志",   "来自装备 TKItem[20]"),  # sub_42234C L73: a2[33]|=v9[20]
    ("mp_reduce",   68,  "内力消耗减少%",  "内息百分比 来自主动技能 TKSkill[33]"),  # sub_422BBC L29: a2[34]+=v6[33]
    ("magic_def",   70,  "所受法伤减少%",  "抗魔百分比 来自主动技能 TKSkill[38]"),  # sub_422BBC L45: a2[35]+=v6[38]
    ("exp_bonus",   72,  "战斗经验增加%",  "鬼才百分比 来自主动技能 TKSkill[36]"),  # sub_422BBC L43: a2[36]+=v6[36]
    ("jp_bonus",    74,  "战斗技能点增加%","天才百分比 来自主动技能 TKSkill[37]"),  # sub_422BBC L44: a2[37]+=v6[37]
    ("move_flags",  76,  "移动特殊标志",   "来自移动技能 TKSkill[32]"),  # sub_422BBC L124: a2[38]|=v6[32]
    ("heal_move",   78,  "移动恢复生命%",  "自愈百分比 来自移动技能 TKSkill[22]"),  # sub_422BBC L125: a2[39]+=v6[22]
    ("mp_move",     80,  "移动恢复内力%",  "回气百分比 来自移动技能 TKSkill[24]"),  # sub_422BBC L126: a2[40]+=v6[24]
]
# 角色五维 [27]-[31] — 曹操验证: 智慧5 仁德-1 勇气10 医术0 技能点数400
CHAR_ATTR_FIELDS = [
    ("wisdom",      54,  "智慧",        "智慧值 (曹操=5 司马懿=20)"),
    ("benevolence", 56,  "仁德",        "仁德值 (曹操=-1 司马懿=-5)"),
    ("courage",     58,  "勇气",        "勇气值 (曹操=10 司马懿=0)"),
    ("medicine",    60,  "医术",        "医术值 (曹操=0 司马懿=10; 上限100)"),  # sub_40E11C case4→word_75688A
    ("jp_total",    62,  "技能点数",    "累计技能点数 (曹操=400 司马懿=300; 与等级相关)"),  # sub_422A5C 入队累加
]
# 反应组 [41]-[42] — 运行时字段, sub_422BBC type=2 写入, sub_42234C 初始化为0
REACTION_FIELDS = [
    ("reaction_group",  82,  "反应组",   "被动技能反应组编号 1-10 (初始化=0)"),  # sub_422BBC type=2
    ("reaction_trigger",84,  "触发概率", "被动技能触发概率 %%, 来自 TKSkill[44]"),  # sub_422BBC: a2[42]=v6[44]
]
REACTION_GROUP_VALUES = ["0-无","1-近戰反擊","2-遠程反擊","3-法術反彈","4-先發制人","5-時序回饋","6-損傷賠償","7-環境探索","8-國色天香","9-有福同享","10-國士無雙"]

# 身上状态槽 [43]-[50] — sub_41E40C 验证: 8个状态效果槽, 每槽(status_id:byte, duration:byte)
STATUS_SLOT_FIELDS = [
    (f"status_slot{i}", 86+i*2, f"状态槽{i}",
     f"身上状态效果槽{i}; 低字节=状态ID(1-32) 高字节=持续回合")  # sub_41E40C: v8+{i*2}
    for i in range(8)
]

EQUIP_FIELDS = [
    ("equip_idx0", 138, "装备索引0",   "运行时装备索引缓存"),  # sub_4173F8
    ("equip_idx1", 140, "装备索引1",   "运行时装备索引缓存"),
    ("equip_idx2", 142, "装备索引2",   "运行时装备索引缓存"),
    ("equip_idx3", 144, "装备索引3",   "运行时装备索引缓存"),
    ("equip_id0",  146, "装备物品ID0", "装备物品 ID (DAT原始; 查 TKItem.field[0])"),
    ("equip_id1",  148, "装备物品ID1", "装备物品 ID"),
    ("equip_id2",  150, "装备物品ID2", "装备物品 ID"),
    ("equip_id3",  152, "装备物品ID3", "装备物品 ID"),
]
# 装备技能 [82]-[87] — Maker Frm_WarPC 暴露, sub_42234C/sub_422BBC 应用
# 周倉 验证: [82]=43武術 [83]=83輔助 [84]=273二連擊 [85]=279無隙1 [86]=303近戰反擊1 [87]=334飄浮
EQUIP_SKILL_FIELDS = [
    ("equip_skill0", 164, "装备技能0", "装备技能槽0 → TKSkill"),  # sub_42234C v4 loop
    ("equip_skill1", 166, "装备技能1", "装备技能槽1 → TKSkill"),
    ("equip_skill2", 168, "装备技能2", "装备技能槽2 → TKSkill"),  # sub_42234C: a2[84]
    ("equip_skill3", 170, "装备技能3", "装备技能槽3 → TKSkill"),  # sub_42234C: a2[85]
    ("passive1",     172, "被动技能1", "被动技能1 → TKSkill"),  # sub_422BBC
    ("passive2",     174, "被动技能2", "被动技能2 → TKSkill"),  # sub_422BBC
]
# 角色使用/装备权限 [77]-[81] — sub_41928C: 按位与校验
CHAR_USE_RIGHT_FIELDS = [
    ("use_right_medicine",  154, "药品权限",   "药品使用权限位掩码 (待验证); 全143条原始值=0"),
    ("use_right_item",      156, "道具权限",   "道具使用权限位掩码 (1=战斗 2=非战斗 4=主角限定); 主角#0=7"),
    ("use_right_weapon",    158, "武器权限",   "武器装备权限位掩码 (1=刀 2=剑 4=枪 8=矛 16=弓 32=大刀 64=戟 128=锤); 主角#0=63"),
    ("use_right_armor",     160, "防具权限",   "防具装备权限位掩码 (1=衣袍 2=铠甲); 主角#0=3"),
    ("use_right_accessory", 162, "饰品权限",   "饰品装备权限位掩码 (待验证); 全143条原始值=0"),
]
STATUS_FIELDS_CAUSE = [
    ("cause_mask1", 134, "攻击导致状态 1-16",  "攻击/命中时让目标进入的状态位掩码 (bit0-15; 来自装备 v9[26])"),
    ("cause_mask2", 136, "攻击导致状态 17-32", "攻击/命中时让目标进入的状态位掩码 (bit16-31; 来自装备 v9[27])"),
]
# 战后奖励 — 实测验证: 盜賊嘍嘍 field[268]=2→JP=2, field[269]=20→Lv3 Gold=40
BATTLE_REWARD_FIELDS = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点数 (直接值, 无等级缩放); 盜賊嘍嘍=2 西羌王=100"),
    ("gold_reward", 538, "战后金钱基数","击败后获得金钱基数; 实际获得=基数×2; 盜賊嘍嘍=20→40 小混混=25→50"),
]
# 成长率 [264]-[266] — 五爪金龍验证: 初期27 中期24 后期21; 等级>=21中期, >=41后期
GROWTH_FIELDS = [
    ("growth_early", 528, "成长率初期", "成长率初期; 五爪金龍=27 西羌王=27 呂布=20"),
    ("growth_mid",   530, "成长率中期", "成长率中期; 五爪金龍=24 西羌王=24 呂布=25"),
    ("growth_late",  532, "成长率后期", "成长率后期; 五爪金龍=21 西羌王=21 呂布=25"),
]
# 可掉落物品 [270]-[272] — 双路径机制，详见 掉落物品概率分析.md
# 路径A（死亡掉落, sub_4400DC）: 独立 100/20/5; 路径B（探寶技能, action 239）: 级联 80/15/5
DROP_ITEM_FIELDS = [
    ("drop_item0", 540, "必掉落物品", "死亡掉落(路径A)中100%掉落; 探寶技能(路径B)中80%掉落; 仅此槽有物品时必掉"),
    ("drop_item1", 542, "高概率掉落", "死亡掉落(路径A)中20%掉落; 探寶技能(路径B)中15%掉落; 优先填第2槽"),
    ("drop_item2", 544, "低概率掉落", "死亡掉落(路径A)中5%掉落; 探寶技能(路径B)中5%掉落; 判定优先级最高"),
]

ALL_NAMED_FIELDS = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS + CHAR_ATTR_FIELDS +
    SKILL_BONUS_FIELDS + REACTION_FIELDS + STATUS_SLOT_FIELDS +
    STATUS_FIELDS_CAUSE + EQUIP_FIELDS + CHAR_USE_RIGHT_FIELDS +
    EQUIP_SKILL_FIELDS + PATCH_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)

# 装备与技能标签页字段 (Tab2) — 供跨角色复制/粘贴使用 (顺序与 _build_tab2 一致)
EQUIP_PANEL_FIELDS = (EQUIP_FIELDS + CHAR_USE_RIGHT_FIELDS + EQUIP_SKILL_FIELDS +
    PATCH_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)

# ═══════════════════════════════════════════════════════════════
# 数据加载/保存 (100% 原始逻辑)
# ═══════════════════════════════════════════════════════════════

def load_warpc(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % WARPC_REC == 0 and (len(dec) == 0 or len(dec) % WARPC_REC != 0):
        dec = raw
    if len(dec) % WARPC_REC != 0:
        raise ValueError(f"解压后大小 {len(dec)} 不是 {WARPC_REC} 的整数倍")
    recs = []
    cnt = len(dec) // WARPC_REC
    for i in range(cnt):
        off = i * WARPC_REC
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        recs.append({'index': i, 'fields': list(vals)})
    return recs

def save_warpc(fp, recs):
    count = len(recs)
    buf = bytearray(count * WARPC_REC)
    for i, rec in enumerate(recs):
        rec['index'] = i
        off = i * WARPC_REC
        struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, buf, off, *rec['fields'])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f:
        f.write(compressed)
    return True

# ── 存档文件常量 (来自 sub_410ED4 SaveTKMat / sub_41103C LoadTKMat) ──
SAVE_SEG1_SIZE = 3432    # 脚本全局变量
SAVE_SEG2_SIZE = 5768    # 背包/队伍/金币
SAVE_WARPC_OFFSET = 9200 # = SEG1 + SEG2

def load_warpc_from_save(save_path):
    """从存档文件 sav.N 读取 WarPC 数据。
    返回 (seg1_bytes, seg2_bytes, records) 其中 records 格式同 load_warpc()。"""
    with open(save_path, 'rb') as f:
        raw = f.read()
    offset = 0
    # 跳过 Frame 1 (TKMat, 2304000B)
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame1 大小")
    comp1 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4 + comp1
    # 读取 Frame 2
    if offset + 4 > len(raw):
        raise ValueError("文件太短: 无法读取 Frame2 大小")
    comp2 = struct.unpack_from('<I', raw, offset)[0]
    offset += 4
    if offset + comp2 > len(raw):
        raise ValueError("Frame2 数据不完整")
    frame2 = lzss_decompress_save(raw[offset:offset + comp2])
    if len(frame2) < SAVE_WARPC_OFFSET:
        raise ValueError(f"Frame2 解压大小不足: {len(frame2)} < {SAVE_WARPC_OFFSET}")
    seg1 = bytes(frame2[:SAVE_SEG1_SIZE])
    seg2 = bytes(frame2[SAVE_SEG1_SIZE:SAVE_WARPC_OFFSET])
    seg3 = bytes(frame2[SAVE_WARPC_OFFSET:])
    if len(seg3) % WARPC_REC != 0:
        raise ValueError(f"WarPC 段大小 {len(seg3)} 不是 {WARPC_REC} 的整数倍")
    recs = []
    cnt = len(seg3) // WARPC_REC
    for i in range(cnt):
        off = i * WARPC_REC
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, seg3, off)
        recs.append({'index': i, 'fields': list(vals)})
    return seg1, seg2, recs

def save_warpc_to_save(save_path, seg1, seg2, records):
    """将 WarPC records 写回存档文件 sav.N (保留 Frame 1 和 seg1/seg2 不变)。"""
    # 重新读取原文件获取 Frame 1 原始压缩数据
    with open(save_path, 'rb') as f:
        raw = f.read()
    # 提取 Frame 1 原始压缩块
    comp1 = struct.unpack_from('<I', raw, 0)[0]
    frame1_block = raw[4:4 + comp1]
    # 构建新 seg3
    seg3_buf = bytearray(len(records) * WARPC_REC)
    for i, rec in enumerate(records):
        off = i * WARPC_REC
        struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, seg3_buf, off, *rec['fields'])
    # 组装 Frame 2
    frame2 = bytes(seg1) + bytes(seg2) + bytes(seg3_buf)
    comp2 = lzss_compress_save(frame2)
    # 回读验证
    dec2 = lzss_decompress_save(comp2)
    if dec2 != frame2:
        raise RuntimeError("Frame2 压缩回写验证失败!")
    # 备份
    if os.path.exists(save_path):
        try:
            with open(save_path, 'rb') as s:
                with open(save_path + '.bak', 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass
    # 写入
    with open(save_path, 'wb') as f:
        f.write(struct.pack('<I', len(frame1_block)))
        f.write(frame1_block)
        f.write(struct.pack('<I', len(comp2)))
        f.write(comp2)
    return True

def get_field(rec, byte_off):
    """读取指定字节偏移处的 int16 字段值"""
    return rec['fields'][byte_off // 2]

def set_field(rec, byte_off, val):
    """写入指定字节偏移处的 int16 字段值"""
    rec['fields'][byte_off // 2] = val

# 尾部未分析区域
TAIL_START = 260  # int16 offset (技能学习状态结束于 [259])
TAIL_END = 527

# ═══════════════════════════════════════════════════════════════
# 弹窗选择器
# ═══════════════════════════════════════════════════════════════

class SkillPickerDialog(QDialog):
    def __init__(self, parent, skill_names, skill_types, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(550, 520)
        self.selected_index = None
        self.skill_names = skill_names
        self.skill_types = skill_types

        layout = QVBoxLayout(self)
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        sf.addWidget(self.search_box)
        layout.addLayout(sf)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["技能#","类型","名称"])
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 55)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        bl = QHBoxLayout()
        btn_clr = QPushButton("清空(-1)")
        btn_clr.clicked.connect(partial(self._clear))
        bl.addWidget(btn_clr)
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept))
        layout.addLayout(bl)

        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower()
        self.table.setRowCount(0)
        row = 0
        type_names = {0:"指令",1:"主动",2:"被动",3:"移动"}
        for idx in sorted(self.skill_names.keys()):
            nm = self.skill_names[idx]
            tp = type_names.get(self.skill_types.get(idx,-1),"?")
            if q and q not in f"{idx} {tp} {nm}".lower():
                continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(tp))
            self.table.setItem(row, 2, QTableWidgetItem(nm))
            row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

    def _clear(self):
        self.selected_index = -1
        self.accept()

class FlagsDialog(QDialog):
    def __init__(self, parent, title, bits, current_val):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 250)
        self.bits = bits
        self.vars = []
        layout = QVBoxLayout(self)
        for bit, name, desc in bits:
            cb = QCheckBox(f"bit{bit} {name}" if not desc else f"{name} ({desc})")
            cb.setChecked(bool(current_val & (1<<bit)))
            self.vars.append((bit, cb))
            layout.addWidget(cb)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [v.setChecked(True) for _,v in self.vars]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [v.setChecked(False) for _,v in self.vars]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self.accept))
        layout.addLayout(bl)

    def get_value(self):
        m = sum((1<<bit) for bit, cb in self.vars if cb.isChecked())
        return m if m < 0x8000 else m - 0x10000

class UseRightDialog(QDialog):
    def __init__(self, parent, title, opts, current_val):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 90+max(len(opts),2)*32)
        self.opts = opts
        self.vars = []
        layout = QVBoxLayout(self)
        # 手动输入框: MOD 可能使用超出内置预定义的位掩码，允许直接输入任意数值
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("当前值:"))
        self.manual_edit = QLineEdit(str(current_val & 0xFFFF))
        self.manual_edit.setPlaceholderText("可直接输入任意数值 (含 MOD 扩展位)")
        manual_row.addWidget(self.manual_edit, 1)
        layout.addLayout(manual_row)
        for bit, name in opts:
            cb = QCheckBox(f"{name}")
            cb.setChecked(bool(current_val & bit))
            cb.toggled.connect(self._sync_from_boxes)
            self.vars.append((bit, cb))
            layout.addWidget(cb)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [v.setChecked(True) for _,v in self.vars]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [v.setChecked(False) for _,v in self.vars]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self.accept))
        layout.addLayout(bl)

    def _sync_from_boxes(self):
        """勾选框变动时同步到手动输入框"""
        m = sum(bit for bit, cb in self.vars if cb.isChecked())
        self.manual_edit.setText(str(m))

    def get_value(self):
        try:
            m = int(self.manual_edit.text().strip() or 0)
        except ValueError:
            m = sum(bit for bit, cb in self.vars if cb.isChecked())
        m &= 0xFFFF
        return m if m < 0x8000 else m - 0x10000

class TkkonPickerDialog(QDialog):
    def __init__(self, parent, tkkon_names, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择 TKKon")
        self.resize(500, 500)
        self.selected_id = None
        layout = QVBoxLayout(self)
        sf = QHBoxLayout()
        sf.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        sf.addWidget(self.search_box)
        layout.addLayout(sf)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["TKKon#","名称"])
        self.table.setColumnWidth(0, 70)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("清空(-1)", clicked=lambda: (setattr(self,'selected_id',-1), self.accept())))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=self.reject))
        bl.addWidget(QPushButton("确定", clicked=self._accept))
        layout.addLayout(bl)
        self.items = sorted(tkkon_names.items(), key=lambda x: x[0]) if tkkon_names else []
        self._refresh()

    def _refresh(self):
        q = self.search_box.text().strip().lower()
        self.table.setRowCount(0)
        row = 0
        for idx, nm in self.items:
            if q and q not in f"{idx} {nm}".lower():
                continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(nm))
            row += 1

    def _accept(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_id = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

# 逆向参考函数: sub_42234C(装备/技能/属性应用), sub_41E40C(物品使用效果),
# sub_422BBC(被动技能效果), sub_4173F8(装备索引匹配), sub_45343C(DAT加载),
# sub_452B14(LZSS解压), sub_4307CC/sub_435D68(技能动画映射)
class FieldRefDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段参考")
        self.resize(700, 600)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        lines = ["WarPC.dat 字段说明:", ""]
        cnt = WARPC_ORIG_COUNT
        lines.append(f"【记录布局】{cnt} 角色 × {WARPC_REC} 字节 = {cnt*WARPC_REC} 字节")
        lines.append(f"  原游戏 143 角色 ({WARPC_ORIG_SIZE} 字节), 编辑器支持动态扩展")
        lines.append(f"  每条记录 {WARPC_FIELD_COUNT} 个字段 × 16位整数 = {WARPC_REC} 字节")
        lines.append("")
        lines.append("【已验证字段】")
        for title, fields in [
            ("基本信息 [0]-[4]", IDENTITY_FIELDS), ("HP/MP [5]-[10]", HPMP_FIELDS),
            ("八属性 [11]-[26] (攻击/防御/命中/闪避/速度/幸运/悟性/移动)", STAT_FIELDS),
            ("角色五维 [27]-[31]", CHAR_ATTR_FIELDS),
            ("技能加成 [32]-[40] (技能效果验证)", SKILL_BONUS_FIELDS),
            ("反应组 [41]-[42]", REACTION_FIELDS),
            ("身上状态 [43]-[50]", STATUS_SLOT_FIELDS),
            ("状态抵抗 [51]-[66] (32状态×1byte)", []),
            ("攻击导致状态 [67]-[68] (来自装备)", STATUS_FIELDS_CAUSE),
            ("装备索引 [69]-[72]", EQUIP_FIELDS[:4]), ("装备ID [73]-[76]", EQUIP_FIELDS[4:]),
            ("使用/装备权限 [77]-[81]", CHAR_USE_RIGHT_FIELDS),
            ("装备技能 [82]-[87] (已验证: 周倉)", EQUIP_SKILL_FIELDS),
            ("补丁专用字段 [260]-[263]", PATCH_FIELDS),
            ("成长率 [264]-[266]", GROWTH_FIELDS),
            ("战后奖励 [268]-[269]", BATTLE_REWARD_FIELDS),
            ("可掉落物品 [270]-[272]", DROP_ITEM_FIELDS),
        ]:
            lines.append(f"【{title}】")
            for field_tuple in fields:
                fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
                cmt = field_tuple[3] if len(field_tuple) > 3 else ''
                lines.append(f"  [{fo//2:3d}] bo={fo:4d} {fl:<14s} {cmt}")
        lines.append("")
        lines.append("【技能学习状态】")
        lines.append(f"  [88-259] 技能学习状态说明: 不会/等待学(1~9进展累积)/可以学(≥10)/父技学会(20)/独立技学会(30)")
        lines.append(f"  344技能×1byte (TKSkill #0-#343), 存储在172个int16的高低字节中")
        lines.append("")
        lines.append("【技能效果判定】")
        lines.append(f"  [273]-[273+count-1] 技能与动画对应: 技能→TKKon动画映射表")
        lines.append(f"  全部type=0指令技能(末尾为普通攻击); 每字段=int16 TKKon ID (0~649)")
        lines.append("")
        lines.append("【功能说明】")
        lines.append("  Tab 1: 核心属性 (生命/攻防/速度等)")
        lines.append("  Tab 2: 装备与技能配置")
        lines.append("  Tab 3: 技能学习进度 (0=未学, 1~9=学习中, ≥10=已学会)")
        lines.append("  Tab 4: 技能效果判定")
        lines.append("  Tab 5: 全部字段总览")
        text.setPlainText('\n'.join(lines))
        layout.addWidget(text)
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("关闭", clicked=self.close))
        layout.addLayout(bl)

# ═══════════════════════════════════════════════════════════════
# 成长数据表弹窗 (逆向来源: sub_410674 / sub_43066C / sub_4302D8)
# ═══════════════════════════════════════════════════════════════

class GrowthTableDialog(QDialog):
    """角色逐级成长数据表 — 基于反编译公式 (sub_410674/sub_43066C)

    成长公式 (每升一级):
      选择成长率除数:
        level < 21       → growth_early  (field[264], byte 528)
        21 ≤ level < 41  → growth_mid    (field[265], byte 530)
        level ≥ 41       → growth_late   (field[266], byte 532)
      stat += stat // divisor + 1   (hp/mp/atk/def/hit/eva)
      spd  += 1                     (固定)
      hp = min(hp, 9999);  mp = min(mp, 9999)

    等级上限: 60 (sub_43066C L13: if level < 60)

    敌方属性加成 (sub_4302D8:53-62, enemy_grp/enemy_power):
      HP  += grp × HP          (×(grp+1), cap 20000)
      MP  += grp × MP / 4      (cap 20000)
      ATK += grp × ATK / 8
      DEF += grp × DEF / 8
      HIT += grp × HIT / 12
      EVA += grp × EVA / 12
      SPD += grp × level / 10
    """

    STAT_CAP_HPMP = 9999
    STAT_CAP_HPMP_ENEMY = 20000
    MAX_LEVEL = 60

    # WarPC int16 字段索引 (byte_offset // 2)
    _IDX_HP   = 7    # hp_base
    _IDX_MP   = 9    # mp_base
    _IDX_ATK  = 11   # atk_base
    _IDX_DEF  = 13   # def_base
    _IDX_HIT  = 15   # hit_base
    _IDX_EVA  = 17   # eva_base
    _IDX_SPD  = 19   # spd_base (field[38//2])
    _IDX_GE   = 264  # growth_early
    _IDX_GM   = 265  # growth_mid
    _IDX_GL   = 266  # growth_late

    STAT_LABELS = ["HP", "MP", "攻击", "防御", "命中", "闪避", "速度"]

    def __init__(self, parent, rec, char_name, tkt_names=None, grp=0, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle(f"成长数据表 — {char_name}")
        self.resize(1100, 800)
        self._rec = rec
        self._char_name = char_name
        self._f = rec['fields']
        self._tkt = tkt_names or {}
        self._grp = grp

        # 应用主题样式表
        ThemeManager.apply_theme(self, 'dark' if is_dark else 'light')
        self._is_dark_init = is_dark

        # 主题颜色 (与 editor_themes 色板对齐)
        # 注: 当前等级行不再用白色文字+蓝底高亮 — QSS 的 ::item background-color
        # 会覆盖 item.setBackground(), 导致蓝底丢失、白字残留在浅色背景上不可读。
        # 改为仅用粗体字标记当前等级行。
        if is_dark:
            self._CLR_DELTA    = QColor("#55b572")   # Δ增量 (取自 dark.qss PreviewDesc)
            self._CLR_GRP      = QColor("#e8a040")   # grp最终属性
        else:
            self._CLR_DELTA    = QColor("#2d7a2d")   # Δ增量 (深绿)
            self._CLR_GRP      = QColor("#cc7a20")   # grp最终属性 (深橙)

        # 读取当前数据
        self._cur_level = max(1, self._f[2])
        self._cur_stats = [
            self._f[self._IDX_HP], self._f[self._IDX_MP],
            self._f[self._IDX_ATK], self._f[self._IDX_DEF],
            self._f[self._IDX_HIT], self._f[self._IDX_EVA],
            self._f[self._IDX_SPD],
        ]
        self._ge = self._f[self._IDX_GE]
        self._gm = self._f[self._IDX_GM]
        self._gl = self._f[self._IDX_GL]

        # 估算 1 级基础值 (二分搜索)
        self._base_stats = [self._estimate_base(cur, self._cur_level)
                            for cur in self._cur_stats]

        # 计算完整成长表 (1-60级)
        self._table_data = self._build_table()
        self._build_ui()
        self._update_grp_summary()

    def showEvent(self, event):
        super().showEvent(event)
        apply_godot_theme(self, self._is_dark_init)

    # ── 成长模拟 (对应 sub_410674 循环体) ──

    def _get_divisor(self, level):
        """获取指定等级段的成长率除数"""
        if level >= 41: return self._gl
        if level >= 21: return self._gm
        return self._ge

    def _simulate_stat(self, base, from_level, to_level):
        """模拟单项属性从 from_level 升至 to_level (sub_410674 循环体)"""
        val = base
        for lvl in range(from_level, to_level):
            d = self._get_divisor(lvl)
            if d > 0:
                val += val // d + 1
            else:
                val += 1
        return val

    def _simulate_spd(self, base_spd, from_level, to_level):
        """速度: 每级固定 +1 (sub_410674 L33: ++a1[19])"""
        return base_spd + (to_level - from_level)

    def _estimate_base(self, current_stat, current_level):
        """二分搜索估算 1 级时的属性基础值 (取最接近当前值的基点)"""
        if current_level <= 1:
            return current_stat
        # 对速度特殊处理 (固定+1/级)
        # 注意: 此函数不区分 stat 类型, 速度单独在 _build_table 处理
        lo, hi = 1, max(current_stat, 1)
        while lo < hi:
            mid = (lo + hi) // 2
            sim = self._simulate_stat(mid, 1, current_level)
            if sim < current_stat:
                lo = mid + 1
            else:
                hi = mid
        # lo = 最小 sim >= current 的 base; 检查 lo-1 是否更接近
        if lo > 1:
            sim_lo  = self._simulate_stat(lo, 1, current_level)
            sim_lo1 = self._simulate_stat(lo - 1, 1, current_level)
            if abs(sim_lo1 - current_stat) <= abs(sim_lo - current_stat):
                return lo - 1
        return lo

    def _build_table(self):
        """构建 1 至 MAX_LEVEL 级完整数据表"""
        data = []
        # 速度基础: spd_base 是当前的速度值 (含 +1/级), 1级基础 = cur - (level-1)
        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base = list(self._base_stats[:6]) + [spd_base]

        prev = list(base)
        for lvl in range(1, self.MAX_LEVEL + 1):
            if lvl == 1:
                stats = list(base)
            else:
                d = self._get_divisor(lvl - 1)
                stats = []
                for i in range(6):
                    v = prev[i]
                    stats.append(v + (v // d + 1) if d > 0 else v + 1)
                stats.append(prev[6] + 1)  # spd 固定 +1

            # HP/MP 上限 cap (sub_410674 L35-38 / sub_43066C L37-40)
            capped = list(stats)
            capped[0] = min(capped[0], self.STAT_CAP_HPMP)
            capped[1] = min(capped[1], self.STAT_CAP_HPMP)

            deltas = [capped[i] - prev[i] for i in range(7)] if lvl > 1 else [0] * 7
            divisor = self._get_divisor(lvl)

            data.append({
                'level': lvl, 'divisor': divisor, 'stats': capped,
                'deltas': deltas, 'is_current': (lvl == self._cur_level),
            })
            prev = capped
        return data

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 顶部: 公式说明 + 1级基础值
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.setSpacing(2)
        info_layout.addWidget(QLabel(
            f"<b>{self._char_name}</b>  (编号 #{self._rec['index']},  "
            f"当前等级 {self._cur_level})"))
        info_layout.addWidget(QLabel(
            f"成长率: 初期={self._ge} (Lv1-20) | "
            f"中期={self._gm} (Lv21-40) | "
            f"后期={self._gl} (Lv41-60)"))
        info_layout.addWidget(QLabel(
            f"公式: stat += stat // divisor + 1 "
            f"(来源 sub_410674/sub_43066C) | "
            f"速度: 每级固定+1 | HP/MP上限={self.STAT_CAP_HPMP}"))

        # 速度基础: 固定+1/级, 1级值 = 当前值 - (等级-1)
        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base_parts = [f"{l}={b}" for l, b in zip(self.STAT_LABELS[:6], self._base_stats[:6])]
        base_parts.append(f"速度={spd_base} (固定+1/级)")
        base_str = "  |  ".join(base_parts)
        base_lbl = QLabel(f"<b>估算 1 级基础值</b>: {base_str}")
        base_lbl.setWordWrap(True)
        info_layout.addWidget(base_lbl)
        layout.addWidget(info_frame)

        # ── grp 加成控制行 ──
        grp_frame = QFrame()
        grp_frame.setObjectName("DockBody")
        grp_row = QHBoxLayout(grp_frame)
        grp_row.setContentsMargins(8, 4, 8, 4)
        grp_row.addWidget(QLabel("属性加成倍率 (grp):"))
        self._grp_spin = QSpinBox()
        self._grp_spin.setRange(0, 10)
        self._grp_spin.setValue(self._grp)
        self._grp_spin.setToolTip(
            "敌方属性加成倍率 (sub_4302D8:53-62)\n"
            "0=普通士兵  1+=将领/Boss\n"
            "HP += grp×HP  MP += grp×MP/4\n"
            "ATK/DEF += grp×stat/8  HIT/EVA += grp×stat/12\n"
            "SPD += grp×level/10")
        self._grp_spin.valueChanged.connect(self._update_grp_summary)
        grp_row.addWidget(self._grp_spin)
        grp_row.addSpacing(20)
        self._grp_formula_lbl = QLabel(
            "<i>grp=0: 仅显示等级成长数据; 设为 1+ 可查看敌方加成后的最终属性</i>")
        self._grp_formula_lbl.setWordWrap(True)
        grp_row.addWidget(self._grp_formula_lbl, 1)
        layout.addWidget(grp_frame)

        # 表格 (16 基础列 + 7 grp 最终列)
        self._BASE_COLS = ["等级", "成长率", "HP", "Δ", "MP", "Δ",
                            "攻击", "Δ", "防御", "Δ", "命中", "Δ",
                            "闪避", "Δ", "速度", "Δ"]
        self._GRP_COLS = ["HP★", "MP★", "攻击★", "防御★",
                           "命中★", "闪避★", "速度★"]
        all_cols = self._BASE_COLS + self._GRP_COLS
        self._growth_table = QTableWidget(len(self._table_data), len(all_cols))
        self._growth_table.setHorizontalHeaderLabels(all_cols)
        self._growth_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._growth_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._growth_table.verticalHeader().setVisible(False)
        self._growth_table.setAlternatingRowColors(True)
        # 修复深色模式下交替行背景色 (QSS 不覆盖 palette 的 AlternateBase)
        self._growth_table.setProperty("class", "GrowthTable")
        self._growth_table.setFont(QFont("Consolas", 9))
        # 列宽
        for ci in range(len(all_cols)):
            self._growth_table.setColumnWidth(ci, 58 if ci >= 16 else (52 if ci > 0 else 45))
        # 初始隐藏 grp 列
        for ci in range(16, 23):
            self._growth_table.setColumnHidden(ci, True)
        self._populate_table()
        layout.addWidget(self._growth_table, 1)

        # 底部按钮
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("关闭", clicked=self.close))
        layout.addLayout(bl)

    def _populate_table(self):
        font_bold = QFont("Consolas", 9, QFont.Bold)
        for row, d in enumerate(self._table_data):
            is_cur = d['is_current']
            items = [str(d['level']), str(d['divisor'])]
            for si in range(7):
                items.append(str(d['stats'][si]))
                delta = d['deltas'][si]
                items.append(f"+{delta}" if delta > 0 else str(delta))
            for ci, txt in enumerate(items):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                if is_cur:
                    item.setFont(font_bold)
                if ci in (3, 5, 7, 9, 11, 13, 15) and d['level'] > 1:
                    item.setForeground(self._CLR_DELTA)
                self._growth_table.setItem(row, ci, item)
        # 滚动到当前等级
        for row, d in enumerate(self._table_data):
            if d['is_current']:
                self._growth_table.scrollToItem(
                    self._growth_table.item(row, 0))
                break

    # ── grp 加成计算 (sub_4302D8:53-62) ──

    def _update_grp_summary(self):
        """根据 grp 值切换成长表中的 grp 列并填充各级最终属性"""
        grp = self._grp_spin.value()

        # 显示/隐藏 grp 列 (col 16-22)
        for ci in range(16, 23):
            self._growth_table.setColumnHidden(ci, grp == 0)

        # 更新公式标签
        if grp > 0:
            cap = self.STAT_CAP_HPMP_ENEMY
            self._grp_formula_lbl.setText(
                f"<b>grp={grp}</b>: "
                f"★列 = 成长值 + grp加成  "
                f"HP×{grp+1}(cap {cap})  MP+{grp}×MP/4  "
                f"ATK/DEF+{grp}/8  HIT/EVA+{grp}/12  SPD+{grp}×Lv/10")
        else:
            self._grp_formula_lbl.setText(
                "<i>grp=0: 仅显示等级成长数据; "
                "设为 1+ 可查看敌方加成后的最终属性</i>")
            return  # grp=0 时不需要填充

        # 填充各级 grp 最终属性 (每行用该级自己的成长值 + 该级自己的 level)
        grp_divs = [1, 4, 8, 8, 12, 12, 0]
        cap = self.STAT_CAP_HPMP_ENEMY
        font_bold = QFont("Consolas", 9, QFont.Bold)

        for row, d in enumerate(self._table_data):
            lv = d['level']
            base = d['stats']
            for si in range(7):
                bonus = (grp * base[si] // grp_divs[si]
                         if grp_divs[si] > 0
                         else grp * lv // 10)
                final = base[si] + bonus
                if si < 2:
                    final = min(final, cap)
                item = QTableWidgetItem(str(final))
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(self._CLR_GRP)
                item.setFont(font_bold)
                self._growth_table.setItem(row, 16 + si, item)

# ═══════════════════════════════════════════════════════════════
# 主编辑器窗口
# ═══════════════════════════════════════════════════════════════


class WarpcEditorV2(QMainWindow):
    # 信号: 角色编辑已应用 (参数: 角色索引)
    record_applied = Signal(int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(format_title("warpc_editor"))
        self.resize(1400, 850)
        self.setMinimumSize(1100, 680)

        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True
        apply_godot_theme(self, self._is_dark)

        self.warpc_path = self.tkt_path = None
        self.records = []
        self.tkt = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.mu_path = None
        self._mu_sprites = []
        self._icon_pixmaps = {}
        self.skill_names = {}
        self._skill_types = {}
        self.tkkon_names = {}
        self.item_names = {}
        self.item_idx_names = {}
        self._idx_to_id = {}
        self._id_to_idx = {}
        self._item_records = []  # 完整物品记录 (供 ItemPickerDialog 使用)
        self.filtered_indices = []
        self._dirty = False
        self._editing_idx = -1

        # 存档模式状态
        self._save_mode = False   # True = 编辑的是 sav.N 中的 WarPC 数据
        self._save_path = None    # 当前存档文件路径
        self._save_slot = 0       # 当前槽位号
        self._seg1 = None         # Frame2 seg1 原始字节 (回写时需要)
        self._seg2 = None         # Frame2 seg2 原始字节 (回写时需要)
        self._game_dir = None     # 游戏资源目录 (TKT/TKItem/Fa.JVG 所在目录)

        self._edit_vars = {}
        self._edit_extras = {}
        self._status_widgets = []
        self._status_resist_widgets = []
        self._skill_learn_widgets = []
        self._skill_effect_widgets = []
        self._skill_effect_name_labels = []
        self._clip_skill_learn = None   # 跨角色复制粘贴: 技能学习数据
        self._clip_skill_effect = None  # 跨角色复制粘贴: 技能效果数据
        self._clip_equip = None         # 跨角色复制粘贴: 装备与技能数据
        self._tab_copy_kind = {}        # 标签页索引 → 复制类型 (learn/effect/equip)
        self._fa_sprites = []
        self._fa_photos = {}
        # 使用权限定义运行时副本 (启动时自动从 configs/ 加载)
        self._use_right_defs = {k: (t, list(o)) for k, (t, o) in USE_RIGHT_DEFS.items()}
        # 启动时自动从 configs/ 加载 equip_type_labels.json
        self._auto_load_use_right_defs()

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

    # ── 配置自动加载 ──
    def _auto_load_use_right_defs(self):
        """启动时自动从 configs/equip_type_labels.json 加载使用权限标签。

        将 JSON 中的页面号 (0-5) 通过 USE_RIGHT_PAGE_TO_FIELD 映射到
        WarPC 权限字段名，整项替换 _use_right_defs 中对应项。
        文件缺失或解析失败时静默回退到内置 USE_RIGHT_DEFS 默认值。
        """
        path = resolve_config_path('equip_type_labels.json')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        try:
            for page_key, items in data.items():
                try:
                    page = int(page_key)
                except (ValueError, TypeError):
                    continue  # 跳过非整型键 (如 "_说明" 注释字段)
                field_name = USE_RIGHT_PAGE_TO_FIELD.get(page)
                if not field_name:
                    continue  # 页面 5(特殊) 在 WarPC 中无对应字段
                pairs = [(int(it[0]), str(it[1])) for it in items]
                if pairs:
                    old_title = self._use_right_defs[field_name][0] if field_name in self._use_right_defs else ""
                    self._use_right_defs[field_name] = (old_title, pairs)
        except (TypeError, IndexError, ValueError):
            pass

    def _update_paths(self):
        tks_dir = self._get_tks_dir()
        if self._save_mode and self.warpc_path:
            warpc_display = f"{self.warpc_path} (槽位{self._save_slot})"
        else:
            warpc_display = self.warpc_path
        update_path_labels([
            (self.lbl_warpc, warpc_display, "WarPC"),
            (self.lbl_tkt, self.tkt_path, "TKT"),
            (self.lbl_item, os.path.join(tks_dir, 'TKItem.dat') if tks_dir else '', "TKItem"),
            (self.lbl_skill, os.path.join(tks_dir, 'TKSkill.dat') if tks_dir else '', "TKSkill"),
            (self.lbl_fa, os.path.join(tks_dir, 'Fa.JVG') if tks_dir else '', "Fa.JVG"),
        ], self._is_dark)

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8,8,8,4)
        main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…\tCtrl+O", self._load_tks_dir)
        fm.addAction("加载存档 (从游戏目录)…\tCtrl+Shift+O", self._load_save_dir)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新增角色\tCtrl+N", self._add_new)
        em.addAction("复制当前角色", self._copy_record)
        em.addAction("导出当前角色(.warpc)…", self._export_warpc)
        em.addAction("导入角色(.warpc)…", self._import_warpc)

        am = mb.addMenu("分析(&S)")
        am.addAction("成长数据表 (1-60级)", self._show_growth_table)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("帮助说明", self._show_help)
        hm.addAction("字段参考", self._show_field_ref)
        hm.addAction("关于编辑器", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("🔍 搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("🗑 清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("🔄 重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()
        toolbar.addWidget(QPushButton("✅ 应用修改", clicked=self._apply_edit))
        toolbar.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit))
        main_layout.addLayout(toolbar)

        # 主 Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # 左侧：角色列表
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#","角色名称","等级","身份","HP","MP"])
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 45)
        self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(4, 70)
        self.table.setColumnWidth(5, 70)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)

        # 左侧容器: 角色列表 + 排序按钮栏
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self.table, 1)

        order_bar = QHBoxLayout()
        order_bar.setContentsMargins(0, 0, 0, 0)
        self.btn_move_up = QPushButton("⬆ 上移")
        self.btn_move_up.setToolTip("将选中角色与上一条整体交换位置 (槽位号互换)")
        self.btn_move_up.clicked.connect(lambda: self._move_record(-1))
        self.btn_move_down = QPushButton("⬇ 下移")
        self.btn_move_down.setToolTip("将选中角色与下一条整体交换位置 (槽位号互换)")
        self.btn_move_down.clicked.connect(lambda: self._move_record(1))
        order_bar.addWidget(self.btn_move_up)
        order_bar.addWidget(self.btn_move_down)
        order_bar.addStretch()
        left_layout.addLayout(order_bar)

        splitter.addWidget(left_panel)

        # 右侧：编辑面板
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4,4,4,4)
        rl.setSpacing(4)

        # 预览头
        preview = QFrame()
        preview.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(8,8,8,8)
        pl.setSpacing(4)

        hdr_row = QHBoxLayout()
        self.preview_avatar = QLabel("")
        hdr_row.addWidget(self.preview_avatar)
        info_col = QVBoxLayout()
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        info_col.addWidget(self.preview_name)
        self.preview_meta = QLabel("")
        self.preview_meta.setProperty("class", "PreviewMeta")
        self.preview_meta.setWordWrap(True)
        info_col.addWidget(self.preview_meta)
        hdr_row.addLayout(info_col, 1)
        pl.addLayout(hdr_row)

        self.preview_desc = QLabel("请在左侧列表中选择角色。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        pl.addWidget(self.preview_desc)
        rl.addWidget(preview)

        # Tab 页
        self.tabs = QTabWidget()
        self._build_tab1()
        self._build_tab2()
        self._build_tab3()
        self._build_tab4()
        self._build_tab5()
        # 页签标题右键菜单 (在标签上右键即可复制/粘贴对应标签页数据)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._on_tab_bar_context_menu)
        rl.addWidget(self.tabs, 1)
        self._edit_panel = right  # 存储编辑面板引用, 供外部嵌入使用
        splitter.addWidget(right)
        splitter.setSizes([350, 1050])

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4,2,4,2)
        self.lbl_warpc = QLabel()
        self.lbl_tkt = QLabel()
        self.lbl_item = QLabel()
        self.lbl_skill = QLabel()
        self.lbl_fa = QLabel()
        for w in [self.lbl_warpc, self.lbl_tkt, self.lbl_item, self.lbl_skill, self.lbl_fa]:
            path_layout.addWidget(w)
            path_layout.addSpacing(15)
        path_layout.addStretch()
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        path_layout.addWidget(self.status_var)
        main_layout.addLayout(path_layout)

    def _build_scroll_tab(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(QVBoxLayout())
        inner.layout().setContentsMargins(4,4,12,4)
        inner.layout().setSpacing(4)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, name)
        return inner

    def _build_section(self, parent, title, fields, cols=6, field_ft='int'):
        """构建字段分组（统一列宽）"""
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(title))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        for fi, field_tuple in enumerate(fields):
            fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
            cmt = field_tuple[3] if len(field_tuple) > 3 else fl
            r, c = divmod(fi, cols)
            self._build_field_widget(grid, r, c, fn, fo, fl, field_ft, cmt)
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
        bl.addLayout(grid)
        gl.addWidget(body)
        parent.layout().addWidget(grp)

    def _build_field_widget(self, grid, r, c, fn, fo, fl, field_ft='int', cmt=''):
        """单个字段控件"""
        cell = QVBoxLayout()
        cell.setSpacing(2)
        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo//2}] byte {fo}: {cmt}")
        lbl.setProperty("class", "PropLabel")
        cell.addWidget(lbl)

        ev = QLineEdit()
        self._edit_vars[fn] = ev

        if fn == 'role':
            cb = NoWheelComboBox()
            cb.addItems(["-1-未激活", "0-已激活"])
            cell.addWidget(make_fake_input(combo=cb))
            self._edit_extras[fn] = cb
        elif fn == 'reaction_group':
            cb = NoWheelComboBox()
            cb.addItems(REACTION_GROUP_VALUES)
            cell.addWidget(make_fake_input(combo=cb))
            self._edit_extras[fn] = cb
        elif fn in FLAG_DEFS:
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev_hidden = QLineEdit()
            ev_hidden.hide()
            self._edit_vars[fn] = ev_hidden
            btn = QPushButton("配置…")
            btn.clicked.connect(lambda _, f=fn: self._pick_flags(f))
            bh.addWidget(btn, 1)
            cell.addWidget(box)
            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        elif fn in USE_RIGHT_DEFS:
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev_hidden = QLineEdit()
            ev_hidden.hide()
            self._edit_vars[fn] = ev_hidden
            btn = QPushButton("配置权限…")
            btn.clicked.connect(lambda _, f=fn: self._pick_use_right(f))
            bh.addWidget(btn, 1)
            cell.addWidget(box)
            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        elif fn.startswith('cause_mask'):
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev_hidden = QLineEdit()
            ev_hidden.hide()
            self._edit_vars[fn] = ev_hidden
            is_cause = fn.startswith('cause_')
            btn = QPushButton("选择导致状态…" if is_cause else "选择解除状态…")
            btn.clicked.connect(lambda _, f=fn: self._pick_status_mask(f))
            bh.addWidget(btn, 1)
            cell.addWidget(box)
            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        elif field_ft == 'skill_pick':
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev.setMinimumWidth(50)
            bh.addWidget(ev, 1)
            btn = QPushButton("…")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))
            bh.addWidget(btn)
            cell.addWidget(box)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        elif field_ft == 'item_pick':
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev.setMinimumWidth(50)
            bh.addWidget(ev, 1)
            btn = QPushButton("…")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, f=fn: self._pick_item(f))
            bh.addWidget(btn)
            cell.addWidget(box)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        elif fn == 'portrait':
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev.setMinimumWidth(50)
            bh.addWidget(ev, 1)
            btn = QPushButton("…")
            btn.setFixedWidth(28)
            btn.clicked.connect(partial(self._pick_portrait))
            bh.addWidget(btn)
            cell.addWidget(box)
        elif fn == 'history_text_id':
            cell.addWidget(make_fake_input(line_edit=ev, stretch=False))
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(True)
            cell.addWidget(extra)
            self._edit_extras[fn] = extra
        else:
            cell.addWidget(make_fake_input(line_edit=ev, stretch=False))

        grid.addLayout(cell, r, c, Qt.AlignTop)

    # ── Tab 构建 ──
    def _build_tab1(self):
        p = self._build_scroll_tab("核心属性")
        self._build_section(p, "基本信息 [0]-[8]", IDENTITY_FIELDS, 6)
        self._build_section(p, "HP / MP [10]-[20]", HPMP_FIELDS, 6)
        self._build_section(p, "八属性 [22]-[50]", STAT_FIELDS, 6)
        self._build_section(p, "角色五维 [54]-[62]", CHAR_ATTR_FIELDS, 6)
        self._build_section(p, "技能加成 [64]-[80] (来自TKSkill)", SKILL_BONUS_FIELDS, 6)
        self._build_section(p, "反应组 [82]-[84]", REACTION_FIELDS, 6)
        self._build_status_slots(p)
        self._build_status_resist(p)
        self._build_section(p, "攻击导致状态 [134]-[136]", STATUS_FIELDS_CAUSE, 6, 'mask')

    def _build_status_slots(self, parent):
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader("身上状态 [86]-[100] (8槽×2字节)"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        status_options = ["(无)"] + [f"{i+1}-{STATUS_NAMES[i]}" for i in range(len(STATUS_NAMES))]
        for si, field_tuple in enumerate(STATUS_SLOT_FIELDS):
            fn, fo, fl = field_tuple[0], field_tuple[1], field_tuple[2]
            cmt = field_tuple[3] if len(field_tuple) > 3 else fl
            r, c = divmod(si, 4)
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(f"状态槽{si}")
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(f"[{fo//2}] {cmt}")
            cell.addWidget(lbl)
            cb = NoWheelComboBox()
            cb.addItems(status_options)
            dur = QLineEdit("0")
            dur.setMinimumWidth(40)
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            lb2 = QLabel("持续:")
            lb2.setMinimumWidth(50)
            lb2.setAlignment(Qt.AlignCenter)
            lb2.setProperty("class", "PropLabel")
            bh.addWidget(lb2)
            bh.addWidget(dur)
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(1)
            sep.setProperty("class", "FakeInputSep")
            bh.addWidget(sep)
            bh.addWidget(cb, 1)
            cell.addWidget(box)
            self._status_widgets.append((fn, fo, cb, dur))
            ev_hidden = QLineEdit()
            ev_hidden.hide()
            self._edit_vars[fn] = ev_hidden
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid)
        gl.addWidget(body)
        parent.layout().addWidget(grp)

    def _build_status_resist(self, parent):
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader("状态抵抗 [102]-[132] (32状态×1byte)"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        grid.setHorizontalSpacing(4)
        for i in range(32):
            r, c = divmod(i, 16)
            sname = STATUS_NAMES[i] if i < len(STATUS_NAMES) else f"{i+1}"
            cell = QVBoxLayout()
            cell.setSpacing(1)
            lbl = QLabel(sname)
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(f"[51+{i//2}]")
            cell.addWidget(lbl)
            ev = QLineEdit("0")
            cell.addWidget(ev)
            self._status_resist_widgets.append((i, ev))
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid)
        gl.addWidget(body)
        parent.layout().addWidget(grp)

    def _build_tab2(self):
        p = self._build_scroll_tab("装备与技能")
        self._register_tab_copy(p, 'equip')
        self._build_section(p, "装备索引 [138]-[144]", EQUIP_FIELDS[:4], 6, 'item_pick')
        self._build_section(p, "装备物品ID [146]-[152]", EQUIP_FIELDS[4:], 6, 'item_pick')
        self._build_section(p, "使用/装备权限 [154]-[162]", CHAR_USE_RIGHT_FIELDS, 6)
        self._build_section(p, "装备技能 [164]-[174] (6字段)", EQUIP_SKILL_FIELDS, 6, 'skill_pick')
        self._build_section(p, "补丁字段 [520]-[526]", PATCH_FIELDS, 6)
        self._build_section(p, "成长率 [528]-[532]", GROWTH_FIELDS, 6)
        self._build_section(p, "战后奖励 [536]-[538]", BATTLE_REWARD_FIELDS, 6)
        self._build_section(p, "可掉落物品 [540]-[544]", DROP_ITEM_FIELDS, 6, 'item_pick')

    def _build_tab3(self):
        """技能学习状态 [176]-[518]"""
        p = self._build_scroll_tab("技能学习")
        self._register_tab_copy(p, 'learn')
        self._skill_learn_labels = []
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(f"技能学习状态 [176]-[518] ({SKILL_LEARN_COUNT}技能×1byte)"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        grid.setHorizontalSpacing(4)
        for i in range(SKILL_LEARN_COUNT):
            r, c = divmod(i, 8)
            sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
            if i == 343:
                sname = "普通攻击"
            cell = QVBoxLayout()
            cell.setSpacing(1)
            lbl = QLabel(sname[:12])
            lbl.setToolTip(f"[{88+i//2}] {sname}")
            lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            cb = NoWheelComboBox()
            cb.addItems(SKILL_LEARN_STATES)
            cell.addWidget(cb)
            self._skill_learn_widgets.append((i, cb))
            self._skill_learn_labels.append(lbl)
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid)
        gl.addWidget(body)
        p.layout().addWidget(grp)

    def _build_tab4(self):
        """技能效果判定"""
        p = self._build_scroll_tab("技能效果判定")
        self._register_tab_copy(p, 'effect')
        self._effect_inner = p

    def _build_skill_effect_section(self, parent):
        active_indices = [i for i in range(350) if self._skill_types.get(i)==0] if self._skill_types else []
        max_slots = WARPC_FIELD_COUNT - 273
        count = min(len(active_indices), max_slots)
        if count == 0:
            lbl = QLabel("(需要加载 TKSkill.dat 数据)")
            parent.layout().addWidget(lbl)
            return
        self._skill_effect_widgets = []
        self._skill_effect_name_labels = []
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(f"技能效果判定 [546]-[{546+(count-1)*2}] ({count}个指令技能→TKKon)"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        for col_i in range(8):
            grid.setColumnStretch(col_i, 1)
        for i in range(count):
            r, c = divmod(i, 8)
            skill_idx = active_indices[i]
            sname = "普通攻击" if skill_idx == 344 else self.skill_names.get(skill_idx, f"技能#{skill_idx}")
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(sname[:15])
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(f"[{273+i}] TKSkill#{skill_idx} → TKKon ID")
            cell.addWidget(lbl)
            box = QFrame()
            box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0,0,0,0)
            bh.setSpacing(0)
            ev = QLineEdit("-1")
            bh.addWidget(ev)
            bh.addStretch()
            btn = QPushButton("…")
            btn.setFixedWidth(26)
            btn.clicked.connect(lambda _, idx=i, sv=ev: self._pick_tkkon(idx, sv))
            bh.addWidget(btn)
            cell.addWidget(box)
            name_lbl = QLabel("(未设置)")
            name_lbl.setProperty("class", "ExtraPreviewText")
            name_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # 不撑宽
            cell.addWidget(name_lbl)
            self._skill_effect_widgets.append((i, ev))
            self._skill_effect_name_labels.append(name_lbl)
            ev.textChanged.connect(lambda _, idx=i, sv=ev: self._update_kon_label(idx, sv))
            grid.addLayout(cell, r, c, Qt.AlignTop)
        bl.addLayout(grid)
        gl.addWidget(body)
        parent.layout().addWidget(grp)

    # ── 技能数据跨角色复制/粘贴 ──
    def _register_tab_copy(self, inner, kind):
        """为标签页注册复制/粘贴右键菜单 (内容区 + 页签标题均可触发)"""
        self._tab_copy_kind[self.tabs.count() - 1] = kind
        inner.setContextMenuPolicy(Qt.CustomContextMenu)
        inner.customContextMenuRequested.connect(
            partial(self._on_skill_tab_context_menu, inner, kind))

    def _on_skill_tab_context_menu(self, widget, kind, pos):
        self._show_copy_menu(kind, widget.mapToGlobal(pos))

    def _on_tab_bar_context_menu(self, pos):
        """在页签标题上右键: 弹出对应标签页的复制/粘贴菜单"""
        bar = self.tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            return
        kind = self._tab_copy_kind.get(idx)
        if kind is None:
            return
        self._show_copy_menu(kind, bar.mapToGlobal(pos))

    def _show_copy_menu(self, kind, global_pos):
        menu = QMenu(self)
        act_copy = menu.addAction("复制数据")
        act_paste = menu.addAction("粘贴数据")
        clip = {'learn': self._clip_skill_learn,
                'effect': self._clip_skill_effect,
                'equip': self._clip_equip}.get(kind)
        act_paste.setEnabled(clip is not None)
        chosen = menu.exec(global_pos)
        if chosen is act_copy:
            if kind == 'learn':
                self._copy_skill_learn()
            elif kind == 'effect':
                self._copy_skill_effect()
            elif kind == 'equip':
                self._copy_equip()
        elif chosen is act_paste:
            if kind == 'learn':
                self._paste_skill_learn()
            elif kind == 'effect':
                self._paste_skill_effect()
            elif kind == 'equip':
                self._paste_equip()

    def _copy_skill_learn(self):
        if self._editing_idx < 0 or not self._skill_learn_widgets:
            self.status_var.setText("请先选择角色")
            return
        clip = []
        for skill_idx, cb in self._skill_learn_widgets:
            sv = cb.currentText()
            sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
            byte_val = int(sv[:sep]) if sep >= 0 else 0
            clip.append(byte_val)
        self._clip_skill_learn = clip
        self.status_var.setText(
            f"已复制技能学习数据 (角色 #{self._editing_idx}, {len(clip)} 项)")

    def _paste_skill_learn(self):
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if self._clip_skill_learn is None:
            self.status_var.setText("没有已复制的技能学习数据")
            return
        for (skill_idx, cb), byte_val in zip(self._skill_learn_widgets,
                                              self._clip_skill_learn):
            for vi in range(cb.count()):
                if cb.itemText(vi).startswith(f'{byte_val}-'):
                    cb.setCurrentIndex(vi)
                    break
        self._apply_edit()
        self.status_var.setText(
            f"已粘贴技能学习数据 → 角色 #{self._editing_idx}")

    def _copy_skill_effect(self):
        if self._editing_idx < 0 or not self._skill_effect_widgets:
            self.status_var.setText("请先选择角色")
            return
        clip = []
        for i, ev in self._skill_effect_widgets:
            try:
                clip.append(int(ev.text()))
            except (ValueError, TypeError):
                clip.append(-1)
        self._clip_skill_effect = clip
        self.status_var.setText(
            f"已复制技能效果数据 (角色 #{self._editing_idx}, {len(clip)} 项)")

    def _paste_skill_effect(self):
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if self._clip_skill_effect is None:
            self.status_var.setText("没有已复制的技能效果数据")
            return
        for (i, ev), val in zip(self._skill_effect_widgets,
                                self._clip_skill_effect):
            ev.setText(str(val))
        self._apply_edit()
        self.status_var.setText(
            f"已粘贴技能效果数据 → 角色 #{self._editing_idx}")

    def _copy_equip(self):
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        clip = {}
        for fn, *_ in EQUIP_PANEL_FIELDS:
            if fn in self._edit_vars:
                clip[fn] = self._edit_vars[fn].text()
        self._clip_equip = clip
        self.status_var.setText(
            f"已复制装备与技能数据 (角色 #{self._editing_idx}, {len(clip)} 项)")

    def _paste_equip(self):
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if not self._clip_equip:
            self.status_var.setText("没有已复制的装备与技能数据")
            return
        for fn, val in self._clip_equip.items():
            if fn in self._edit_vars:
                self._edit_vars[fn].setText(val)
        self._apply_edit()
        # 刷新装备/技能名称等额外显示 (物品名、技能名、权限标签)
        rec = (self._current_record
               if (hasattr(self, '_current_record') and self._current_record)
               else self.records[self._editing_idx])
        self._populate_edit(rec)
        self.status_var.setText(
            f"已粘贴装备与技能数据 → 角色 #{self._editing_idx}")

    def _build_tab5(self):
        p = self._build_scroll_tab("全部字段")
        self._tab5_inner = p

    def _build_raw_grid(self, parent):
        COLS = 16
        for base in range(0, WARPC_FIELD_COUNT, 100):
            end = min(base+100, WARPC_FIELD_COUNT)
            grp = QWidget()
            gl = QVBoxLayout(grp)
            gl.setContentsMargins(0,0,0,0)
            gl.setSpacing(0)
            gl.addWidget(DockHeader(f"字段 [{base}] — [{end-1}]"))
            body = QWidget()
            body.setObjectName("DockBody")
            bl = QVBoxLayout(body)
            bl.setContentsMargins(8,8,8,8)
            grid = QGridLayout()
            grid.setVerticalSpacing(1)
            grid.setHorizontalSpacing(2)
            for j in range(base, end):
                r, c = divmod(j-base, COLS)
                cell = QVBoxLayout()
                cell.setSpacing(1)
                lbl = QLabel(f"[{j}]")
                lbl.setProperty("class", "PropLabel")
                cell.addWidget(lbl)
                fn = f"raw_{j}"
                ev = QLineEdit()
                self._edit_vars[fn] = ev
                cell.addWidget(ev)
                grid.addLayout(cell, r, c, Qt.AlignTop)
            bl.addLayout(grid)
            gl.addWidget(body)
            parent.layout().addWidget(grp)

    # ── 数据加载 ──
    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d:
            return
        wp = os.path.join(d, "WarPC.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(wp):
            QMessageBox.warning(self, "文件缺失", "未找到 WarPC.dat")
            return
        self.warpc_path = wp
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self.mu_path = os.path.join(d, "Mu.JVG")
        self._save_mode = False  # 重置存档模式
        self._reload()

    def _load_save_dir(self):
        """从存档文件 sav.N 加载 WarPC 角色数据 (先选游戏目录, 再自动定位 save/)"""
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录 (含 save 子文件夹)")
        if not d:
            return
        # 确认选中的是游戏目录 (包含 WarPC.dat 或 TKT.dat)
        is_game_dir = os.path.exists(os.path.join(d, 'WarPC.dat')) or os.path.exists(os.path.join(d, 'TKT.dat'))
        if not is_game_dir:
            # 用户可能选了 save/ 子文件夹，尝试向上修正
            parent = os.path.dirname(d.rstrip('/\\'))
            if os.path.exists(os.path.join(parent, 'WarPC.dat')) or os.path.exists(os.path.join(parent, 'TKT.dat')):
                d = parent  # 自动修正到游戏目录
            else:
                QMessageBox.warning(self, "目录不正确",
                    f"所选目录不是 TKS 游戏目录 (未找到 WarPC.dat/TKT.dat):\n{d}\n\n"
                    f"请选择包含 WarPC.dat 和 save/ 文件夹的游戏根目录。")
                return
        game_dir = d
        # 在游戏目录下查找 save 子文件夹
        save_dir = os.path.join(d, 'save')
        if not os.path.exists(save_dir):
            save_dir = d  # 降级: 直接在游戏目录下找
        if not any(os.path.exists(os.path.join(save_dir, f'sav.{s}')) for s in range(1, 10)):
            QMessageBox.warning(self, "未找到存档",
                f"在游戏目录下未找到 save 文件夹或 sav.N 文件:\n{d}")
            return
        # 扫描可用槽位
        slots = []
        for s in range(1, 10):
            sp = os.path.join(save_dir, f'sav.{s}')
            if os.path.exists(sp):
                # 读取索引文件摘要
                ip = os.path.join(save_dir, f'{s}.sav')
                summary = ""
                if os.path.exists(ip):
                    try:
                        idx_data = open(ip, 'rb').read()
                        if len(idx_data) >= 28:
                            import datetime as _dt
                            ts = struct.unpack_from('<I', idx_data, 8)[0]
                            dt_str = _dt.datetime.fromtimestamp(ts).strftime('%m/%d %H:%M')
                            gold = struct.unpack_from('<H', idx_data, 6)[0]
                            summary = f"{dt_str} | 金{gold}"
                    except Exception:
                        summary = "(索引异常)"
                slots.append((s, sp, summary))
        if not slots:
            QMessageBox.warning(self, "无可用槽位", "目录中没有存档数据")
            return
        # 槽位选择对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("选择存档槽位")
        dlg.resize(450, 380)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"存档目录: {save_dir}"))
        table = QTableWidget(len(slots), 3)
        table.setHorizontalHeaderLabels(['槽位', '文件', '摘要'])
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 150)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, (s, sp, summary) in enumerate(slots):
            table.setItem(row, 0, QTableWidgetItem(str(s)))
            table.setItem(row, 1, QTableWidgetItem(os.path.basename(sp)))
            table.setItem(row, 2, QTableWidgetItem(summary))
        layout.addWidget(table, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(QPushButton("取消", clicked=dlg.reject))
        btn_row.addWidget(QPushButton("打开", clicked=dlg.accept))
        layout.addLayout(btn_row)
        if dlg.exec() != QDialog.Accepted:
            return
        sel = table.selectedItems()
        if not sel:
            return
        slot_num = slots[sel[0].row()][0]
        save_path = slots[sel[0].row()][1]
        # 加载数据
        self._save_mode = True
        self._save_path = save_path
        self._save_slot = slot_num
        self._game_dir = game_dir  # 直接存储游戏目录
        self.warpc_path = save_path  # 用于资源路径推导
        # game_dir 就是用户选择的游戏目录
        self.tkt_path = os.path.join(game_dir, 'TKT.dat') if os.path.exists(os.path.join(game_dir, 'TKT.dat')) else None
        self.mu_path = os.path.join(game_dir, 'Mu.JVG') if os.path.exists(os.path.join(game_dir, 'Mu.JVG')) else None
        self._reload()
        self.setWindowTitle(f"{format_title('warpc_editor')} [存档模式 槽位{slot_num}]")

    def _reload(self):
        if not self.warpc_path:
            return
        self.status_var.setText("加载中…")
        QApplication.processEvents()
        if self.mu_path:
            self._mu_sprites = load_mu_sprites(self.mu_path) or []
            self._icon_pixmaps.clear()

        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)

        # 加载 Fa.JVG 头像
        tks_dir = self._get_tks_dir()
        fa_path = os.path.join(tks_dir, 'Fa.JVG')
        self._fa_sprites = load_jvg_sprites(fa_path) or []
        self._fa_photos.clear()

        try:
            if self._save_mode:
                # 存档模式: 从 sav.N 加载 WarPC
                self.status_var.setText("从存档加载 WarPC 数据…")
                QApplication.processEvents()
                self._seg1, self._seg2, self.records = load_warpc_from_save(self.warpc_path)
            else:
                # 普通模式: 从 WarPC.dat 加载
                orig_path = self.warpc_path + ".orig"
                if os.path.exists(orig_path):
                    if QMessageBox.question(self, "检测到未恢复的备份",
                        "发现 WarPC.dat.orig, 是否从备份恢复?",
                        QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                        try:
                            bak = orig_path + ".editor_bak"
                            import shutil
                            if not os.path.exists(bak):
                                shutil.copy2(self.warpc_path, bak)
                            os.replace(orig_path, self.warpc_path)
                            self.status_var.setText("已从 .orig 备份恢复")
                        except Exception as e:
                            QMessageBox.critical(self, "恢复失败", str(e))
                self.records = load_warpc(self.warpc_path)
            self._dirty = False
            # 保存原始快照用于 MOD 导出差异比对
            self._original_records = [list(r['fields']) for r in self.records]
            self.skill_names, self._skill_types = self._load_skill_names()
            self.tkkon_names = self._load_tkkon_names()
            self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()

            # 更新技能学习标签
            if hasattr(self, '_skill_learn_labels') and self._skill_learn_labels:
                for i, lbl in enumerate(self._skill_learn_labels):
                    if i < len(self._skill_learn_labels):
                        sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
                        if i == 343:
                            sname = "普通攻击"
                        lbl.setText(sname[:12])

            # 重建技能效果判定
            if hasattr(self, '_effect_inner') and self._effect_inner:
                self._clear_layout(self._effect_inner.layout())
                self._build_skill_effect_section(self._effect_inner)

            # 重建全部字段
            if hasattr(self, '_tab5_inner') and self._tab5_inner:
                self._clear_layout(self._tab5_inner.layout())
                self._build_raw_grid(self._tab5_inner)

            nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
            tkkon_count = len(self.tkkon_names)
            self.status_var.setText(f"{len(self.records)} 角色 | 有效 {nonempty} | TKT {len(self.tkt)} 条 | 物品 {len(self.item_names)} 技能 {len(self.skill_names)} TKKon {tkkon_count}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _clear_layout(self, layout):
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _get_tks_dir(self):
        """获取游戏资源目录 (TKT.dat 所在目录)。存档模式下直接返回存储的游戏目录。"""
        if self._save_mode and self._game_dir:
            return self._game_dir
        return os.path.dirname(self.warpc_path) if self.warpc_path else ''

    def _load_skill_names(self):
        tks_dir = self._get_tks_dir()
        sk_path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path):
            return {}, {}
        try:
            with open(sk_path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress(raw)
            if len(raw) % 94 == 0 and (len(dec) == 0 or len(dec) % 94 != 0):
                dec = raw
            names, types = {}, {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec):
                    break
                name_id = struct.unpack_from('<h', dec, off)[0]
                stype = struct.unpack_from('<h', dec, off + 4)[0]
                types[i] = stype
                if name_id > 0 and name_id in self.tkt:
                    names[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
                elif name_id:
                    names[i] = f'#{name_id}'
            return names, types
        except:
            return {}, {}

    def _load_tkkon_names(self):
        """从游戏数据动态解析 TKKon 名称映射 (替代静态 tkkon_names.csv)。"""
        tks_dir = self._get_tks_dir()
        if not tks_dir:
            return {}
        try:
            resolver = KonNameResolver(tks_dir)
            return resolver.get_all_names(compact_threshold=3)
        except Exception:
            return {}

    def _load_item_names(self):
        tks_dir = self._get_tks_dir()
        it_path = os.path.join(tks_dir, 'TKItem.dat')
        if not os.path.exists(it_path):
            return {}, {}, {}, {}
        try:
            with open(it_path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress(raw)
            if len(raw) % 64 == 0 and (len(dec) == 0 or len(dec) % 64 != 0):
                dec = raw
            id_lookup, idx_lookup, idx_to_id, id_to_idx = {}, {}, {}, {}
            # 同时构建完整物品记录列表 (供 ItemPickerDialog 使用)
            item_records = []
            for i in range(600):
                off = i * 64
                if off + 10 > len(dec):
                    break
                item_id = struct.unpack_from('<h', dec, off)[0]
                tab_code = struct.unpack_from('<h', dec, off + 2)[0]
                name_id = struct.unpack_from('<h', dec, off + 4)[0]
                icon = struct.unpack_from('<h', dec, off + 8)[0]
                equip_type = struct.unpack_from('<h', dec, off + 10)[0]
                price = struct.unpack_from('<h', dec, off + 62)[0] if off + 64 <= len(dec) else 0
                if name_id > 0 and name_id in self.tkt:
                    nm = self.tkt[name_id].split('\n')[0].strip()[:25]
                elif item_id > 0:
                    nm = f'物品#{item_id}'
                else:
                    nm = ''
                if nm:
                    if item_id > 0:
                        id_lookup[item_id] = nm
                        idx_to_id[i] = item_id
                        id_to_idx[item_id] = i
                    idx_lookup[i] = nm
                item_records.append({
                    'index': i, 'item_id': item_id, 'tab_code': tab_code,
                    'name': nm, 'equip_type': equip_type,
                    'icon': icon, 'price': price,
                })
            self._item_records = item_records
            return id_lookup, idx_lookup, idx_to_id, id_to_idx
        except:
            self._item_records = []
            return {}, {}, {}, {}

    def _set_edit_enabled(self, en):
        self.tabs.setEnabled(en)

    # ── 筛选/列表 ──
    def _char_name(self, rec):
        f = rec['fields']
        nid = f[0]
        if nid > 0 and nid in self.tkt:
            return self.tkt[nid].split('\n')[0].strip()[:20]
        if nid < 0 and -nid in self.tkt:
            return self.tkt[-nid].split('\n')[0].strip()[:20]
        return f"#{nid}" if nid else f"(空-#{rec['index']})"

    def _apply_filter(self):
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        for rec in self.records:
            if q:
                nm = self._char_name(rec)
                if q not in f"{rec['index']} {nm} {rec['fields'][2]} {rec['fields'][3]}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
        msg = f"显示 {len(self.filtered_indices)}/{len(self.records)} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty:
            msg += " [已修改]"
        self.status_var.setText(msg)

    def _clear_filter(self):
        self.search_entry.clear()
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            f = r['fields']
            nm = self._char_name(r)
            hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
            mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
            role_val = f[3]
            role_str = '未激活' if role_val==-1 else ('已激活' if role_val==0 else str(role_val))
            tag_color = QColor("#2266CC") if role_val==-1 else QColor("#CC3333") if role_val==0 else QColor("#dcdcdc")
            self.table.insertRow(row)
            for ci, v in enumerate([str(r['index']), nm, str(f[2]), role_str, hp_str, mp_str]):
                item = QTableWidgetItem(v)
                item.setForeground(tag_color)
                if ci in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, ci, item)
        self.table.blockSignals(False)

    def _get_fa_photo(self, sprite_idx, size=(24,24)):
        if not self._fa_sprites:
            return None
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites):
            return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None:
            return None
        cache_key = (sprite_idx, size)
        if cache_key in self._fa_photos:
            return self._fa_photos[cache_key]
        try:
            from PIL import Image
            img = sprite.resize(size, Image.NEAREST).convert('RGBA')
            data = img.tobytes('raw', 'RGBA')
            from PySide6.QtGui import QImage, QPixmap
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg)
            self._fa_photos[cache_key] = pix
            return pix
        except:
            return None

    # ── 编辑 ──
    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel:
            # 清除视图
            self._editing_idx = -1
            self.preview_name.setText("(未选中)")
            self.preview_meta.setText("")
            self.preview_desc.setText("请在左侧列表中选择角色。")
            self.preview_avatar.clear()
            return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        f = rec['fields']
        nm = self._char_name(rec)

        # 预览
        self.preview_name.setText(f"{nm}  (编号 #{rec['index']})")
        role_str = '未激活' if f[3]==-1 else ('已激活' if f[3]==0 else str(f[3]))
        self.preview_meta.setText(
            f"等级={f[2]}  |  身份={role_str}  |  HP={f[5]}/{f[8]}  |  MP={f[6]}/{f[10]}")

        desc_parts = []
        for si, name in enumerate(STAT_NAMES_CN):
            base = f[STAT_BASE_OFFSETS[si]//2]
            cur = f[STAT_BASE_OFFSETS[si]//2+1]
            desc_parts.append(f"{name}={cur}")
        self.preview_desc.setText("  |  ".join(desc_parts))

        portrait = f[1]
        large_idx = portrait * 2 if portrait >= 0 else 0
        pix = self._get_fa_photo(large_idx, (72, 72))
        self.preview_avatar.setPixmap(pix) if pix else self.preview_avatar.clear()

        # 填充字段
        for fn, fo, _, *_ in ALL_NAMED_FIELDS:
            val = str(f[fo//2])
            if fn in self._edit_vars:
                w = self._edit_vars[fn]
                w.setText(val)
            if fn == 'role' and fn in self._edit_extras:
                cb = self._edit_extras[fn]
                for i in range(cb.count()):
                    if cb.itemText(i).startswith(f'{f[3]}-'):
                        cb.setCurrentIndex(i)
                        break
            if fn == 'reaction_group' and fn in self._edit_extras:
                cb = self._edit_extras[fn]
                for i in range(cb.count()):
                    if cb.itemText(i).startswith(f'{f[41]}-'):
                        cb.setCurrentIndex(i)
                        break

        # 状态槽
        if hasattr(self, '_status_widgets'):
            for fs_fn, fo, cb, ev_dur in self._status_widgets:
                v = f[fo//2]
                sid = v & 0xFF
                dur = (v>>8) & 0xFF
                if sid == 0 or sid > len(STATUS_NAMES):
                    cb.setCurrentIndex(0)
                else:
                    cb.setCurrentIndex(sid)
                ev_dur.setText(str(dur) if sid != 0 and dur != 0xFF else "0")

        # 状态抵抗
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                field_idx = 51 + byte_idx//2
                is_high = byte_idx%2
                unsigned = f[field_idx] & 0xFFFF
                byte_val = (unsigned>>(8*is_high)) & 0xFF
                ev.setText(str(byte_val))

        # 技能学习
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                field_idx = 88 + skill_idx//2
                is_high = skill_idx%2
                unsigned = f[field_idx] & 0xFFFF
                byte_val = (unsigned>>(8*is_high)) & 0xFF
                for vi, item in enumerate(cb.itemText(i) for i in range(cb.count())):
                    if item.startswith(f'{byte_val}-'):
                        cb.setCurrentIndex(vi)
                        break
            # 刷新技能名称标签 (嵌入模式下 skill_names 可能在 Tab 构建后才加载)
            if self.skill_names and hasattr(self, '_skill_learn_labels'):
                for i, lbl in enumerate(self._skill_learn_labels):
                    sname = self.skill_names.get(i, f"技能#{i}")
                    if i == 343:
                        sname = "普通攻击"
                    lbl.setText(sname[:12])
                    lbl.setToolTip(f"[{88+i//2}] {sname}")

        # 技能效果
        # 延迟构建: 嵌入模式下 Tab4 在首次选择时才构建
        # 条件: _effect_inner 存在 且 (尚无技能效果控件 或 控件列表为空)
        if hasattr(self, '_effect_inner') and self._effect_inner:
            needs_rebuild = (not hasattr(self, '_skill_effect_widgets')
                             or not self._skill_effect_widgets)
            if needs_rebuild and self._skill_types:
                self._clear_layout(self._effect_inner.layout())
                self._skill_effect_widgets = []
                self._skill_effect_name_labels = []
                self._build_skill_effect_section(self._effect_inner)
        if hasattr(self, '_skill_effect_widgets') and self._skill_effect_widgets:
            for i, ev in self._skill_effect_widgets:
                field_idx = 273 + i
                if field_idx < WARPC_FIELD_COUNT:
                    ev.setText(str(f[field_idx]))

        # 额外文本解析
        for fn, fo, _, *_ in EQUIP_SKILL_FIELDS:
            if fn in self._edit_extras:
                sid = f[fo//2]
                if sid == -1:
                    self._edit_extras[fn].setText('(未装备)')
                elif sid in self.skill_names:
                    self._edit_extras[fn].setText(self.skill_names[sid])
                else:
                    self._edit_extras[fn].setText(f'技能#{sid}')

        for fn, fo, _, *_ in EQUIP_FIELDS[:4]:
            if fn in self._edit_extras:
                idx = f[fo//2]
                if idx == -1:
                    self._edit_extras[fn].setText('(未装备)')
                elif idx in self.item_idx_names:
                    self._edit_extras[fn].setText(self.item_idx_names[idx])
                else:
                    self._edit_extras[fn].setText(f'物品#{idx}')

        for fn, fo, _, *_ in EQUIP_FIELDS[4:]:
            if fn in self._edit_extras:
                iid = f[fo//2]
                if iid == -1:
                    self._edit_extras[fn].setText('(未装备)')
                elif iid in self.item_names:
                    self._edit_extras[fn].setText(self.item_names[iid])
                else:
                    self._edit_extras[fn].setText(f'物品#{iid}')

        for fn, fo, _, *_ in DROP_ITEM_FIELDS:
            if fn in self._edit_extras:
                iid = f[fo//2]
                if iid == 0:
                    self._edit_extras[fn].setText('(无)')
                elif iid in self.item_names:
                    self._edit_extras[fn].setText(self.item_names[iid])
                else:
                    self._edit_extras[fn].setText(f'物品#{iid}')

        if 'history_text_id' in self._edit_extras:
            hid = f[524//2]
            if hid == 0:
                default_id = 9050 + rec['index']
                if default_id in self.tkt:
                    txt = self.tkt[default_id].split('\n')[0].strip()[:25]
                    self._edit_extras['history_text_id'].setText(f'默认→TKT#{default_id}: {txt}')
                else:
                    self._edit_extras['history_text_id'].setText(f'默认→TKT#{default_id} (未找到)')
            elif hid in self.tkt:
                txt = self.tkt[hid].split('\n')[0].strip()[:25]
                self._edit_extras['history_text_id'].setText(f'TKT#{hid}: {txt}')
            else:
                self._edit_extras['history_text_id'].setText(f'TKT#{hid} (未找到)')

        for fn in FLAG_DEFS:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].text())
                except:
                    val = 0
                _, bits = FLAG_DEFS[fn]
                mask = val & 0xFFFF
                sel = [name for bit, name, _ in bits if mask & (1<<bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

        for fn in self._use_right_defs:
            if fn in self._edit_extras and fn in self._edit_vars:
                try:
                    val = int(self._edit_vars[fn].text())
                except:
                    val = 0
                _, opts = self._use_right_defs[fn]
                mask = val & 0xFFFF
                sel = [name for bit, name in opts if (mask & bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

        for fn, *rest in STATUS_FIELDS_CAUSE:
            if fn in self._edit_extras:
                mask = f[134//2] if fn=='cause_mask1' else f[136//2]
                self._update_status_label(fn, mask & 0xFFFF)

        # 全部字段 Tab
        if hasattr(self, '_tab5_inner') and self._tab5_inner:
            has_raw = any(f"raw_{j}" in self._edit_vars for j in range(min(10, WARPC_FIELD_COUNT)))
            if not has_raw:
                self._clear_layout(self._tab5_inner.layout())
                self._build_raw_grid(self._tab5_inner)
        for j in range(WARPC_FIELD_COUNT):
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                self._edit_vars[fn].setText(str(f[j]))

    # ── 弹窗 ──
    def _pick_skill(self, fn):
        if not self.skill_names: return
        try:
            cur = int(self._edit_vars[fn].text() or 0)
        except:
            cur = 0
        dlg = SkillPickerDialog(self, self.skill_names, self._skill_types, cur)
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self._edit_vars[fn].setText(str(dlg.selected_index))
            if fn in self._edit_extras:
                nm = self.skill_names.get(dlg.selected_index, '')
                if dlg.selected_index == -1:
                    self._edit_extras[fn].setText('(未装备)')
                elif nm:
                    self._edit_extras[fn].setText(nm)
                else:
                    self._edit_extras[fn].setText(f'技能#{dlg.selected_index}')

    def _pick_item(self, fn):
        is_idx = fn.startswith('equip_idx')
        if not getattr(self, '_item_records', None): return
        try:
            cur = int(self._edit_vars[fn].text() or 0)
        except:
            cur = 0
        # equip_idx 模式: 返回数组索引; equip_id/drop_item 模式: 返回物品 ID
        return_key = 'index' if is_idx else 'item_id'
        clear_text = "清空(-1)" if is_idx else "清空(0)"
        # 转换 WarPC 权限定义格式 → ItemPickerDialog 所需格式
        use_right_opts = {}
        for page, field_name in USE_RIGHT_PAGE_TO_FIELD.items():
            if field_name in self._use_right_defs:
                use_right_opts[page] = self._use_right_defs[field_name][1]
        use_right_opts.setdefault(5, [(0, "通用")])
        dlg = ItemPickerDialog(
            self, self._item_records,
            use_right_options=use_right_opts,
            icon_pixmap_fn=self._get_icon_pixmap,
            current_value=cur,
            clear_text=clear_text,
            return_key=return_key,
        )
        if dlg.exec() == QDialog.Accepted and dlg.selected_value is not None:
            sel_val = dlg.selected_value
            self._edit_vars[fn].setText(str(sel_val))
            if fn in self._edit_extras:
                if is_idx:
                    nm = self.item_idx_names.get(sel_val, '')
                    self._edit_extras[fn].setText(nm if sel_val != -1 else '(未装备)')
                else:
                    nm = self.item_names.get(sel_val, '')
                    self._edit_extras[fn].setText(nm if sel_val != -1 and sel_val != 0 else '(未装备)')
            # 同步配对字段 (equip_idx ↔ equip_id)
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_id{slot}'
                pair_val = self._idx_to_id.get(sel_val, 0)
            else:
                pair_fn = f'equip_idx{slot}'
                pair_val = self._id_to_idx.get(sel_val, -1)
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].setText(str(pair_val))
            if pair_fn in self._edit_extras:
                if pair_val == -1:
                    self._edit_extras[pair_fn].setText('(未装备)')
                elif is_idx:
                    self._edit_extras[pair_fn].setText(self.item_names.get(pair_val, f'物品#{pair_val}'))
                else:
                    self._edit_extras[pair_fn].setText(self.item_idx_names.get(pair_val, f'物品#{pair_val}'))

    def _pick_flags(self, fn):
        if fn not in FLAG_DEFS: return
        title, bits = FLAG_DEFS[fn]
        try:
            cur = int(self._edit_vars[fn].text() or 0)
        except:
            cur = 0
        dlg = FlagsDialog(self, title, bits, cur & 0xFFFF)
        if dlg.exec() == QDialog.Accepted:
            val = dlg.get_value()
            self._edit_vars[fn].setText(str(val))
            if fn in self._edit_extras:
                mask = val & 0xFFFF
                sel = [name for bit, name, _ in bits if mask & (1<<bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_use_right(self, fn):
        if fn not in self._use_right_defs: return
        title, opts = self._use_right_defs[fn]
        try:
            cur = int(self._edit_vars[fn].text() or 0)
        except:
            cur = 0
        dlg = UseRightDialog(self, title, opts, cur & 0xFFFF)
        if dlg.exec() == QDialog.Accepted:
            val = dlg.get_value()
            self._edit_vars[fn].setText(str(val))
            if fn in self._edit_extras:
                mask = val & 0xFFFF
                sel = [name for bit, name in opts if (mask & bit)]
                self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _get_icon_pixmap(self, icon_val, size=(24,24)):
        return get_sprite_pixmap(self._mu_sprites, icon_val, size, self._icon_pixmaps)

    def _pick_status_mask(self, fn):
        try:
            cur = int(self._edit_vars[fn].text() or 0)
        except:
            cur = 0
        base = 0 if fn.endswith('_mask1') else 16
        is_cause = fn.startswith('cause_')
        title = "选择导致状态 (位掩码)" if is_cause else "选择解除状态 (位掩码)"
        dlg = StatusPickerDialog(self, title, STATUS_NAMES, cur & 0xFFFF, base, self._get_icon_pixmap, is_cause)
        if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
            new_mask = dlg.selected_mask
            self._edit_vars[fn].setText(str(new_mask))
            if fn in self._edit_extras:
                self._update_status_label(fn, new_mask & 0xFFFF)

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_mask1') else 16
        sel = [STATUS_NAMES[base+i] for i in range(16)
               if (mask & (1<<i)) and base+i < len(STATUS_NAMES)]
        if fn in self._edit_extras:
            self._edit_extras[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_portrait(self):
        if not self._fa_sprites: return
        fn = 'portrait'
        try:
            cur_val = int(self._edit_vars[fn].text() or 0)
        except:
            cur_val = 0
        dlg = QDialog(self)
        dlg.setWindowTitle("选择头像 (Fa.JVG)")
        dlg.resize(780, 560)
        layout = QVBoxLayout(dlg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(2)
        large_indices = [(si, si//2) for si in range(0, len(self._fa_sprites), 2) if self._fa_sprites[si] is not None]
        COLS = 8
        for sprite_idx, portrait_idx in large_indices:
            r, c = divmod(portrait_idx, COLS)
            btn = QPushButton()
            btn.setFixedSize(80, 90)
            btn.setCursor(Qt.PointingHandCursor)
            if portrait_idx == cur_val:
                btn.setProperty("selected", "true")
            else:
                btn.setProperty("selected", "false")
            pix = self._get_fa_photo(sprite_idx, (64, 64))
            if pix:
                btn.setIcon(QIcon(pix))
                btn.setIconSize(pix.size())
            btn.setText(str(portrait_idx))
            btn.clicked.connect(lambda checked, v=portrait_idx: (self._edit_vars[fn].setText(str(v)), dlg.accept()))
            grid.addWidget(btn, r, c)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=dlg.reject))
        layout.addLayout(bl)
        dlg.exec()

    def _pick_tkkon(self, idx, ev):
        if not self.tkkon_names: return
        try:
            cur = int(ev.text() or 0)
        except:
            cur = 0
        dlg = TkkonPickerDialog(self, self.tkkon_names, cur)
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            ev.setText(str(dlg.selected_id))

    def _update_kon_label(self, idx, ev):
        if idx >= len(self._skill_effect_name_labels): return
        try:
            kon_id = int(ev.text())
        except:
            return
        name = self.tkkon_names.get(kon_id, f"TKKon#{kon_id}") if kon_id >= 0 else "(未设置)"
        lbl = self._skill_effect_name_labels[idx]
        lbl.setToolTip(name)
        lbl.setText(name)

    # ── 应用编辑 ──
    def _apply_edit(self):
        if self._editing_idx < 0: return
        rec = self._current_record if hasattr(self, '_current_record') and self._current_record else self.records[self._editing_idx]
        f = rec['fields']

        # Role / Reaction group
        if 'role' in self._edit_extras:
            sv = self._edit_extras['role'].currentText()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                f[3] = int(sv[:sep]) if sep >= 0 else int(sv)
        if 'reaction_group' in self._edit_extras:
            sv = self._edit_extras['reaction_group'].currentText()
            if sv:
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                f[41] = int(sv[:sep]) if sep >= 0 else int(sv)

        # 状态槽
        if hasattr(self, '_status_widgets'):
            for fs_fn, fo, cb, ev_dur in self._status_widgets:
                sid = cb.currentIndex()
                if sid == 0:
                    v = -256
                else:
                    try:
                        dur = int(ev_dur.text())
                    except:
                        dur = 1
                    if dur < 0:
                        dur = 1
                    if dur > 255:
                        dur = 255
                    v = (sid & 0xFF) | ((dur & 0xFF) << 8)
                    if v >= 0x8000:
                        v -= 0x10000
                f[fo//2] = v

        # 状态抵抗
        if hasattr(self, '_status_resist_widgets'):
            for byte_idx, ev in self._status_resist_widgets:
                try:
                    byte_val = int(ev.text())
                except:
                    continue
                if byte_val < 0:
                    byte_val = 0
                if byte_val > 255:
                    byte_val = 255
                field_idx = 51 + byte_idx//2
                is_high = byte_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                new_val = (unsigned & 0x00FF) | (byte_val << 8) if is_high else (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000:
                    new_val -= 0x10000
                f[field_idx] = new_val

        # 技能学习
        if hasattr(self, '_skill_learn_widgets'):
            for skill_idx, cb in self._skill_learn_widgets:
                sv = cb.currentText()
                sep = sv.find('-', 1) if sv.startswith('-') else sv.find('-')
                byte_val = int(sv[:sep]) if sep >= 0 else 0
                field_idx = 88 + skill_idx//2
                is_high = skill_idx % 2
                unsigned = f[field_idx] & 0xFFFF
                new_val = (unsigned & 0x00FF) | (byte_val << 8) if is_high else (unsigned & 0xFF00) | byte_val
                if new_val >= 0x8000:
                    new_val -= 0x10000
                f[field_idx] = new_val

        # 技能效果
        if hasattr(self, '_skill_effect_widgets'):
            for i, ev in self._skill_effect_widgets:
                field_idx = 273 + i
                if field_idx >= WARPC_FIELD_COUNT: continue
                try:
                    v = int(ev.text())
                    f[field_idx] = max(-32768, min(32767, v))
                except:
                    pass

        # 命名字段
        for fn, fo, _, *_ in ALL_NAMED_FIELDS:
            if fn in self._edit_vars and fn not in ('role', 'reaction_group'):
                try:
                    v = int(self._edit_vars[fn].text())
                    f[fo//2] = max(-32768, min(32767, v))
                except:
                    pass

        # 全部字段 — 跳过已由命名字段+状态抵抗+技能学习+技能效果覆盖的
        named_indices = set(fo//2 for _, fo, *rest in ALL_NAMED_FIELDS)
        for j in range(51, 67):
            named_indices.add(j)
        for j in range(88, 260):
            named_indices.add(j)
        if hasattr(self, '_skill_effect_widgets'):
            for i, _ in self._skill_effect_widgets:
                named_indices.add(273 + i)
        for j in range(WARPC_FIELD_COUNT):
            if j in named_indices: continue
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].text())
                    f[j] = max(-32768, min(32767, v))
                except:
                    pass

        self._dirty = True
        # 同步回 records (独立模式需要)
        if self.records and self._editing_idx < len(self.records):
            self.records[self._editing_idx] = rec
        nm = self._char_name(rec)
        hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
        mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
        role_str = '未激活' if f[3]==-1 else ('已激活' if f[3]==0 else str(f[3]))
        if hasattr(self, 'table') and self.table.isVisible():
            self._refresh_table()
            for r in range(self.table.rowCount()):
                if int(self.table.item(r, 0).text()) == rec['index']:
                    self.table.selectRow(r)
                    break
        if hasattr(self, 'status_var'):
            self.status_var.setText(f"角色 #{rec['index']} 已修改 (内存, 未保存)")
        self.record_applied.emit(rec['index'])

    def _reset_edit(self):
        if self._editing_idx >= 0:
            rec = self._current_record if hasattr(self, '_current_record') and self._current_record else self.records[self._editing_idx]
            self._populate_edit(rec)

    # ── 新增/复制/导出/导入 ──
    def _add_new(self):
        if not self.records: return
        new_idx = len(self.records)
        fields = [0]*WARPC_FIELD_COUNT
        fields[3] = -1
        fields[4] = 100
        fields[2] = 1
        fields[5] = 50
        fields[6] = 25
        fields[7] = 50
        fields[8] = 50
        fields[9] = 25
        fields[10] = 25
        for si in range(8):
            fields[22+si*4] = 10
            fields[22+si*4+2] = 10
        fields[32] = 1
        for si in range(82, 88):
            fields[si] = -1
        self.records.append({'index': new_idx, 'fields': fields})
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == new_idx:
                self.table.selectRow(r)
                break
        self.status_var.setText(f"已新增角色 #{new_idx} (内存, 未保存)")

    def _copy_record(self):
        if self._editing_idx < 0: return
        src = self.records[self._editing_idx]
        new_idx = len(self.records)
        self.records.append({'index': new_idx, 'fields': list(src['fields'])})
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == new_idx:
                self.table.selectRow(r)
                break
        self.status_var.setText(f"已复制 #{self._editing_idx} → #{new_idx}")

    def _move_record(self, delta):
        """上移/下移选中角色: 与相邻角色整体交换数据。

        delta=-1 上移(与上一行交换), delta=+1 下移(与下一行交换)。
        交换两个槽位的全部字段(fields), 槽位号(index)保持不变——
        即 #164 下移后数据位于 #165, 原 #165 数据移到 #164, 选择跟随移动的角色。
        已到列表顶/底时静默忽略。
        """
        if not self.records:
            return
        sel = self.table.selectedItems()
        if not sel:
            self.status_var.setText("请先在左侧列表选择一条数据")
            return
        cur_row = sel[0].row()
        tgt_row = cur_row + delta
        if tgt_row < 0 or tgt_row >= self.table.rowCount():
            return  # 已到列表边界
        cur_idx = int(self.table.item(cur_row, 0).text())
        tgt_idx = int(self.table.item(tgt_row, 0).text())
        if cur_idx == tgt_idx:
            return
        # 整体交换两条记录的字段数据 (槽位号 index 不变, 数据互换位置)
        self.records[cur_idx]['fields'], self.records[tgt_idx]['fields'] = \
            self.records[tgt_idx]['fields'], self.records[cur_idx]['fields']
        self._dirty = True
        self._refresh_table()
        # 选择跟随数据: 选中目标行, 使被移动的角色保持选中
        self.table.selectRow(tgt_row)
        self.status_var.setText(f"已交换 #{cur_idx} ↔ #{tgt_idx} (内存, 未保存)")

    def _export_warpc(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]
        nm = self._char_name(rec)
        safe_name = "".join(c for c in nm if c not in r'\/:*?"<>|' and ord(c)>=32) or f"角色_{self._editing_idx}"
        fp, _ = QFileDialog.getSaveFileName(self, "导出角色", f"{safe_name}.warpc", "WarPC文件 (*.warpc)")
        if not fp: return
        magic = b'WPC1'
        raw = struct.pack('<' + 'h' * WARPC_FIELD_COUNT, *rec['fields'])
        with open(fp, 'wb') as f:
            f.write(magic + raw)
        self.status_var.setText(f"已导出: {os.path.basename(fp)}")

    def _import_warpc(self):
        if not self.records: return
        fp, _ = QFileDialog.getOpenFileName(self, "导入角色", "", "WarPC文件 (*.warpc)")
        if not fp: return
        try:
            with open(fp, 'rb') as f:
                data = f.read()
            if len(data) < 4 or data[:4] != b'WPC1':
                QMessageBox.critical(self, "格式错误", "不是有效的 .warpc 文件")
                return
            raw = data[4:]
            if len(raw) < WARPC_FIELD_COUNT*2:
                QMessageBox.critical(self, "格式错误", f"需要 {WARPC_FIELD_COUNT*2} 字节, 实际 {len(raw)}")
                return
            fields = list(struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, raw, 0))
            new_idx = len(self.records)
            self.records.append({'index': new_idx, 'fields': fields})
            self._dirty = True
            self._apply_filter()
            for r in range(self.table.rowCount()):
                if int(self.table.item(r, 0).text()) == new_idx:
                    self.table.selectRow(r)
                    break
            self.status_var.setText(f"已导入: {os.path.basename(fp)} → #{new_idx}")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    # ── 保存 ──
    def _save(self):
        if self._save_mode:
            self._save_to_save_file()
            return
        if not self.warpc_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        if QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 个角色到:\n{self.warpc_path}\n\n原文件将被覆盖 (生成 .bak).",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        try:
            with open(self.warpc_path, 'rb') as s:
                with open(self.warpc_path+".bak", 'wb') as d:
                    d.write(s.read())
        except:
            pass
        try:
            self.status_var.setText("正在保存…")
            QApplication.processEvents()
            save_warpc(self.warpc_path, self.records)
            self._dirty = False
            self.status_var.setText(f"已保存 → {self.warpc_path}")
            QMessageBox.information(self, "成功", f"已保存\n备份: {self.warpc_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _save_to_save_file(self):
        """存档模式下保存 WarPC 数据回 sav.N"""
        if not self._save_path or not self.records or self._seg1 is None or self._seg2 is None:
            QMessageBox.information(self, "提示", "无存档数据")
            return
        if QMessageBox.question(self, "确认保存",
            f"将 {len(self.records)} 个角色的 WarPC 数据写回存档:\n{self._save_path} (槽位 {self._save_slot})\n\n原存档将被备份为 .bak",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        try:
            self.status_var.setText("正在保存到存档…")
            QApplication.processEvents()
            save_warpc_to_save(self._save_path, self._seg1, self._seg2, self.records)
            self._dirty = False
            self.status_var.setText(f"已保存到存档 → {self._save_path} 槽位{self._save_slot}")
            QMessageBox.information(self, "成功", f"已保存到存档\n备份: {self._save_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件"""
        if not self.records or not self._original_records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 收集 MOD 元数据
        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 计算差异
        current_fields = [r['fields'] for r in self.records]
        diff_result = diff_records(
            self._original_records, current_fields,
            WARPC_FIELD_COUNT, len(self._original_records)
        )

        # 检查是否有差异
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        # 计算原始文件 CRC32
        crc = compute_crc32(self.warpc_path) if self.warpc_path else "0x00000000"

        # 构建数据差异 JSON
        data_json = build_data_diff_json(
            target="WarPC.dat",
            record_size=WARPC_REC,
            field_type="int16",
            field_count=WARPC_FIELD_COUNT,
            original_count=len(self._original_records),
            original_crc32=crc,
            diff_result=diff_result,
        )

        # 构建 ID 范围
        id_ranges = {}
        if diff_result['appended']:
            min_idx = min(r['index'] for r in diff_result['appended'])
            max_idx = max(r['index'] for r in diff_result['appended'])
            id_ranges["warpc"] = {"start": min_idx, "end": max_idx}

        # WarPC 扩展需求
        warpc_expand = 0
        if len(self.records) > WARPC_ORIG_COUNT:
            warpc_expand = len(self.records)

        metadata["id_ranges"] = id_ranges
        metadata["warpc_expand"] = warpc_expand

        # 组件列表
        components = [{"file": "data/WarPC.dat.json", "target": "WarPC.dat"}]

        # 生成 mod.json
        mod_json = generate_mod_json(metadata, components)

        # 选择保存路径
        default_name = f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod"
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出为 MOD", default_name, "TKS MOD (*.tksmod)")
        if not fp:
            return

        # 打包
        data_files = {"data/WarPC.dat.json": data_json}
        try:
            pack_tksmod(fp, mod_json, data_files)
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{n_mod}条, 追加{n_app}条)")
            QMessageBox.information(self, "导出成功",
                f"已导出 MOD 文件:\n{fp}\n\n"
                f"修改记录: {n_mod} 条\n追加记录: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对（适用于当前文件已被修改的情况）"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 预构建当前字段
        current_fields = [r['fields'] for r in self.records]

        def _compute_stats(ref_dir):
            ref_records = load_reference_dat_fields(ref_dir, "WarPC.dat",
                rec_size=WARPC_REC, field_count=WARPC_FIELD_COUNT, field_fmt='h', use_lzss=True)
            if ref_records is None:
                return {"valid": False, "error": "目录中未找到 WarPC.dat"}
            diff = diff_records(ref_records, current_fields, WARPC_FIELD_COUNT, len(ref_records))
            targets = []
            if diff['modified'] or diff['appended']:
                targets.append({"name": "WarPC.dat",
                    "modified": len(diff['modified']),
                    "appended": len(diff['appended']),
                    "deleted": 0})
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.warpc_path) if self.warpc_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        # 加载参考数据并计算差异
        ref_records = load_reference_dat_fields(ref_dir, "WarPC.dat",
            rec_size=WARPC_REC, field_count=WARPC_FIELD_COUNT, field_fmt='h', use_lzss=True)
        if ref_records is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 WarPC.dat")
            return
        diff_result = diff_records(ref_records, current_fields, WARPC_FIELD_COUNT, len(ref_records))
        if not diff_result['modified'] and not diff_result['appended']:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # 构建并导出
        crc = compute_crc32(os.path.join(ref_dir, "WarPC.dat"))
        data_json = build_data_diff_json(target="WarPC.dat", record_size=WARPC_REC,
            field_type="int16", field_count=WARPC_FIELD_COUNT,
            original_count=len(ref_records), original_crc32=crc, diff_result=diff_result)

        id_ranges = {}
        if diff_result['appended']:
            min_idx = min(r['index'] for r in diff_result['appended'])
            max_idx = max(r['index'] for r in diff_result['appended'])
            id_ranges["warpc"] = {"start": min_idx, "end": max_idx}
        warpc_expand = len(self.records) if len(self.records) > WARPC_ORIG_COUNT else 0
        metadata["id_ranges"] = id_ranges
        metadata["warpc_expand"] = warpc_expand

        mod_json = generate_mod_json(metadata, [{"file": "data/WarPC.dat.json", "target": "WarPC.dat"}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {"data/WarPC.dat.json": data_json})
            n_mod = len(diff_result['modified'])
            n_app = len(diff_result['appended'])
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (参考目录比对, 修改{n_mod}, 追加{n_app})")
            QMessageBox.information(self, "导出成功",
                f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {n_mod} 条\n追加: {n_app} 条")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        # 预览 MOD 信息
        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        # 检查是否包含 WarPC.dat
        if "WarPC.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 WarPC.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.warpc_path) if self.warpc_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        # 执行导入
        mod_json, records = import_tksmod_records(
            fp, ref_dir, "WarPC.dat",
            rec_size=WARPC_REC, field_count=WARPC_FIELD_COUNT,
            field_fmt='h', use_lzss=True
        )
        if records is None:
            QMessageBox.warning(self, "导入失败",
                "无法导入 MOD 数据。\n请确认参考目录中包含有效的 WarPC.dat")
            return

        # 将导入的数据填充到编辑器
        self.records = [{'index': i, 'fields': row} for i, row in enumerate(records)]
        self._original_records = [list(r['fields']) for r in self.records]
        self._dirty = False

        # 记住 MOD 元数据，方便再次导出
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        # 刷新 UI
        self._apply_filter()
        nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{len(self.records)} 角色 | 有效 {nonempty}")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 条记录。\n"
            f"您现在可以继续编辑并重新导出。")

    # ── 分析 ──
    def _show_growth_table(self):
        """打开成长数据表弹窗 (1-60级)"""
        if self._editing_idx < 0 or self._editing_idx >= len(self.records):
            QMessageBox.warning(self, "未选择角色",
                "请先在左侧列表中选择一个角色。")
            return
        rec = self.records[self._editing_idx]
        char_name = self._char_name(rec)
        dlg = GrowthTableDialog(self, rec, char_name, self.tkt,
                                 is_dark=self._is_dark)
        dlg.exec()

    # ── 帮助 ──
    def _show_field_ref(self):
        FieldRefDialog(self).exec()

    # 逆向参考: sub_42234C, sub_41E40C, sub_422BBC, sub_4173F8, sub_45343C, sub_452B14
    def _show_help(self):
        cnt = len(self.records) if self.records else WARPC_ORIG_COUNT
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            f"功能: 编辑《三国群侠传》战斗角色数据\n"
            f"数据: {cnt} 角色 × {WARPC_REC} 字节 (原游戏 {WARPC_ORIG_COUNT} 角色, 支持动态扩展)\n\n"
            f"特性:\n"
            f"  · Godot 风格深/浅色主题切换\n"
            f"  · 分页编辑: 核心属性 / 装备技能 / 技能学习 / 效果判定 / 全部字段\n"
            f"  · 自动关联 TKItem.dat 显示物品名称")

    def _show_about(self):
        themed_messagebox(self, QMessageBox.Information, "关于编辑器",
            format_about_header('warpc_editor'))

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
    app.setApplicationName("WarPC Editor")
    editor = WarpcEditorV2()
    editor.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
