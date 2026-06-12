#!/usr/bin/env python3
"""
TKSkill.dat 可视化编辑器 (PySide6 最终完美 Godot 风格版)
=============================================================
修复了布局对齐、去除了冗余线框，并 100% 还原了 Godot 4.6 滚动条及主题样式。
"""

import struct, os, sys, csv
from collections import OrderedDict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QSplitter, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QCheckBox, QTextEdit, QComboBox, QMessageBox, QFileDialog,
    QDialog, QGridLayout, QFrame, QScrollArea
)
from PySide6.QtGui import QAction, QKeySequence, QColor, QFont, QIcon
from PySide6.QtCore import Qt

# ============================================================
# LZSS 编解码 & 业务数据常数 (100% 原始逻辑)
# ============================================================

def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]
    bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data): break
            flags = data[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(data): break
            b = data[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(data): break
            b1, b2 = data[pos], data[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

def lzss_compress(data):
    src = data; sl = len(src)
    flat = bytes(bytearray([0x20] * 4096) + src)
    tokens = []; pos = 0
    while pos < sl:
        curr = 4096 + pos; ms = min(18, sl - pos); bl, bo = 0, 0
        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat[curr:curr + length]
                end = curr + length - 1
                start = max(0, curr - 4096)
                idx = flat.rfind(pat, start, end)
                if idx != -1: bl = length; bo = (idx - 18) & 0xFFF; break
        if bl >= 3:
            tokens.append((False, bo, bl)); pos += bl
        else:
            tokens.append((True, src[pos], 0)); pos += 1
    stream = bytearray(); ti = 0
    while ti < len(tokens):
        fb = 0; be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]: fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]:
                stream.append(tokens[i][1])
            else:
                off, length = tokens[i][1], tokens[i][2]; el = length - 3
                stream.append(off & 0xFF)
                stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    ds = sl; bd = struct.pack('<I', ds) + bytes(stream)
    return struct.pack('<II', ds, len(bd)) + bd

def load_tkt_base(tkt_path, full_desc=False):
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path, 'rb') as f: raw = f.read()
    if len(raw) < 8: return {}
    ts = struct.unpack_from('<I', raw, 0)[0]; cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]; dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt * 4, cnt * 4; lookup = {}
    SKIP = set(range(0, 10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        if eid in SKIP: continue
        off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0: end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try: s = txt.decode('big5', errors='replace')
            except: s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.strip() if full_desc else s
    return lookup

def load_tkt(tkt_path): return load_tkt_base(tkt_path, False)
def load_tkt_full(tkt_path): return load_tkt_base(tkt_path, True)

SKILL_REC = 94; SKILL_CNT = 350
SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_VALUES = [f"{k}-{v}" for k, v in sorted(SKILL_TYPES.items())]
ATK_TYPE_VALUES = ["-1-近战攻击", "0-物理攻击", "1-术法攻击", "10-召唤攻击"]

STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

SPECIAL_FLAG_BITS = [
    (0, "飘浮", "地形通行无阻"), (1, "飙行", "移动范围扩大"),
    (2, "搜宝", "获得额外宝物"), (3, "解陷", "自动解除陷阱"),
]

BASIC_FIELDS = [
    ("skill_text_id", 0, "名称文本ID", 'tkt', "技能名称 TKT 文本ID"),
    ("skill_desc_id", 2, "说明文本ID", 'int', "技能说明 TKT 文本ID = skill_text_id + 400"),
    ("type", 4, "技能类型", 'type', "0=指令 1=主动 2=被动 3=移动"),
    ("jp_cost", 6, "技能点数", 'int', "学习技能所需点数 (JP)"),
]

TREE_FIELDS = []
for i in range(8):
    TREE_FIELDS.append(("ref_skill%d" % i, 8 + i*4, f"目标技能{i}", 'skill_pick', "受影响的目标技能索引"))
    TREE_FIELDS.append(("ref_type%d" % i, 10 + i*4, f"技能进度{i}", 'int', "累加进度权重(>=10可学), 20=归组"))

EFFECT_FIELDS = [
    ("timing", 40, "时序值Delay", 'int', "技能行动时序值"),
    ("hp_pct", 42, "生命加成%", 'int', "HP%加成"),
    ("heal_move", 44, "移步回血%", 'int', "自癒1=2 自癒2=3"),
    ("mp_pct", 46, "内力加成%", 'int', "MP%加成"),
    ("mp_move", 48, "移步回气%", 'int', "回气1=2 回气2=3"),
    ("atk_pct", 50, "攻击加成%", 'int', "攻击%加成"),
    ("def_pct", 52, "防御加成%", 'int', "防御%加成"),
    ("hit_pct", 54, "命中加成%", 'int', "命中%加成"),
    ("eva_pct", 56, "闪避加成%", 'int', "闪避%加成"),
    ("spd_pct", 58, "速度加成%", 'int', "速度%加成"),
    ("move_up", 60, "增加移动", 'int', "移动+1=2, 移动+2=3"),
    ("atk_count", 62, "增攻次数", 'int', "二連=2 三連=3"),
    ("special_flags",64,"特殊标志", 'flags', "飘浮/飙行等掩码"),
    ("mp_reduce", 66, "内息消耗减%", 'int', "施展指令技能内息减少%"),
]

IMMUNE_FIELDS = [
    ("immunity1", 68, "状态免疫 1-16", 'mask', "状态免疫位掩码 (状态 1-16)"),
    ("immunity2", 70, "状态免疫 17-32", 'mask', "状态免疫位掩码 (状态 17-32)"),
    ("exp_bonus", 72, "战后经验增加%", 'int', "战斗经验值增加% (鬼才)"),
    ("jp_bonus", 74, "战后技点增加%", 'int', "战斗技能点增加% (天才)"),
    ("magic_def", 76, "所受法伤减少%", 'int', "减少法术伤害% (抗魔)"),
    ("cost_gold", 78, "消耗金钱", 'int', "技能消耗金钱"),
    ("cost_res2", 80, "耗费兽元", 'int', "召唤技能兽元消耗"),
]

ADVANCED_FIELDS = [
    ("cost_res3", 82, "耗费灵魂", 'int', "幻灵技能灵魂消耗"),
    ("turn_shift", 84, "调整时序", 'int', "敌人行动时序偏移"),
    ("mp_cost", 86, "耗费内力", 'int', "技能消耗内力值"),
    ("trigger_prob",88, "触发概率", 'int', "状态免疫等级/被动技能触发概率"),
    ("sub_count", 90, "子技能数量", 'int', "技能组头子技能数 (-1=独立)"),
    ("atk_type", 92, "攻击类型", 'atk_type', "攻击伤害类别 (-1近战 0物理 1术法 10召唤)"),
]

ALL_FIELDS = (BASIC_FIELDS + EFFECT_FIELDS + IMMUNE_FIELDS + list(ADVANCED_FIELDS) + TREE_FIELDS)

TYPE_HINT_LABELS = {
    1: "主动技能: 百分比属性加成 → 角色战斗属性",
    2: "被动技能: 触发概率 → 角色反应系统",
    3: "移动技能: 特殊标志 + 移动能力 → 角色地图能力",
    0: "指令技能: 技能组根节点, 含子技能列表",
}

def skill_name(rec, tkt):
    sid = rec.get('skill_text_id', 0)
    if sid and sid in tkt: return tkt[sid].split('\n')[0].strip()
    if sid and -sid in tkt: return tkt[-sid].split('\n')[0].strip()
    return f"Skill#{sid}" if sid else f"(空-#{rec['index']})"

def load_skills(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw); recs = []
    for i in range(SKILL_CNT):
        off = i * SKILL_REC
        if off + SKILL_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h' * 47, dec, off)
        rec = {'index': i}
        for k, fo, _, _, _ in ALL_FIELDS: rec[k] = fields[fo // 2]
        recs.append(rec)
    return recs

def save_skills(fp, recs):
    buf = bytearray(SKILL_CNT * SKILL_REC)
    for rec in recs[:SKILL_CNT]:
        i = rec['index']; off = i * SKILL_REC
        for k, fo, _, _, _ in ALL_FIELDS: struct.pack_into('<h', buf, off + fo, rec[k])
    compressed = lzss_compress(bytes(buf))
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# QSS 样式表 (100% 对齐 Godot 4.6 规范与原版需求)
# ============================================================
GODOT_DARK_QSS = """
QWidget { background-color: #202531; color: #dcdcdc; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #1a1e27; alternate-background-color: #202531; border: 1px solid #14171f; selection-background-color: #478cbf; }
QHeaderView::section { background-color: #202531; border: none; border-bottom: 1px solid #14171f; padding: 4px; }
/* =======================================================
   大面积文本编辑区 (彻底消除色块突兀感)
======================================================= */
QPlainTextEdit, QTextEdit {
    background-color: #161923; /* 与 FakeInputBox 统一的微凹深色底 */
    border: 1px solid #0b0c12; /* 极暗边框，融入背景 */
    border-radius: 4px;
    padding: 8px;              /* 增加内边距，让文字有呼吸感 */
    color: #e0e4eb;
    font-family: 'Consolas', 'Segoe UI';
    line-height: 1.5;
}

/* 独立单行输入框 (非 FakeInputBox 内的) */
QLineEdit {
    background-color: #161923;
    border: 1px solid #0b0c12;
    padding: 4px 8px;
    border-radius: 4px;
    color: #e0e4eb;
}

/* 【关键魔法】：只有在鼠标点击输入时，才凸显它的存在 */
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    background-color: #1a1e29; /* 聚焦时微微提亮 */
    border: 1px solid #478cbf; /* 亮起 Godot 焦点蓝 */
}
QPushButton { background-color: #2e3548; border: 1px solid #14171f; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover { background-color: #3b445c; }
QPushButton:pressed { background-color: #478cbf; color: #fff; }
QComboBox { background-color: #2e3548; border: 1px solid #14171f; border-radius: 4px; padding: 4px; }
QComboBox::drop-down { border: none; }

/* 完美复刻原版滚动条与分割线 */
QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #14171f; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #14171f; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }

QScrollBar:vertical { background: #1a1e27; width: 12px; }
QScrollBar::handle:vertical { background: #3b445c; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QFrame#DockHeader { background-color: #14171f; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QWidget#DockBody { background-color: #202531; border: 1px solid #14171f; border-top: none; }
QLabel#DockTitle { background-color: transparent; color: #a5b0cb; font-weight: bold; }
QMenuBar { background-color: #202531; color: #dcdcdc; border-bottom: 1px solid #14171f; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background-color: #3b445c; border-radius: 2px; }
QMenu { background-color: #202531; border: 1px solid #14171f; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; }

/* Godot Inspector 级特定类 */
QLabel[class="InspectorTitle"] { font-weight: bold; color: #a5b0cb; border-bottom: 1px solid #14171f; padding-bottom: 2px; margin-top: 8px; }
QLabel[class="PropLabel"] { color: #8a96b3; }
QScrollArea { border: none; background-color: transparent; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
/* =======================================================
   预览区面板 (彻底透明，融入背景)
======================================================= */
QFrame#PreviewFrame {
    background-color: transparent;    /* 【关键魔法】：彻底透明化，消灭灰色色块 */
    border: none;                     /* 移除四周生硬的边框 */
    border-top: 2px solid #2b4f70;    /* 【核心改动】：变细，且换成极度暗沉的深灰蓝 */
    border-bottom: 1px solid #14171f; /* 底部加一条极暗的分割线，与下方属性区隔开 */
    border-radius: 0px;               /* 透明背景不需要圆角 */
    margin-top: 4px;
    margin-bottom: 8px;
}

/* 大标题：技能名称 */
QLabel[class="PreviewName"] {
    color: #e0e4eb;
    font-size: 18px; /* 加大字号 */
    font-weight: bold;
    font-family: 'Microsoft YaHei', 'Segoe UI';
}

/* 元数据：类型与消耗 */
QLabel[class="PreviewMeta"] {
    color: #8a96b3;
    font-size: 11px;
    border-bottom: 1px solid #2e3548; /* 用底边框做极细的优雅分割线 */
    padding-bottom: 8px;
    margin-bottom: 4px;
}

/* 描述文本 */
QLabel[class="PreviewDesc"] {
    color: #55b572; /* 延续你的原版绿色偏好 */
    font-size: 13px;
    padding-top: 4px;
}

/* 子技能警告/提示 */
QLabel[class="PreviewSubMeta"] {
    color: #e27d60;
    font-size: 12px;
    font-weight: bold;
    padding-top: 4px;
}

/* =======================================================
   综合输入框外壳 (EditorResourcePicker 风格)
======================================================= */
QFrame#FakeInputBox {
    background-color: #161923; /* 更柔和的高级内陷底色 */
    border: 1px solid #0b0c12; /* 极简的边缘阴影勾勒 */
    border-radius: 4px;        /* 稍微圆润一点 */
}

QFrame#FakeInputBox:hover, QFrame#FakeInputBox:focus-within {
    background-color: #1a1e29;
    border: 1px solid #478cbf; /* Godot 经典的焦点蓝 */
}

/* 内部输入框：完全去边框化，依靠外壳表现 */
QFrame#FakeInputBox > QLineEdit {
    background: transparent;
    border: none;
    padding: 4px 8px; /* 【关键修复】上下4px，左右8px，文字彻底告别贴边 */
    color: #e0e4eb;
    font-family: 'Consolas', 'Segoe UI'; /* ID 推荐使用等宽字体更好看 */
    selection-background-color: #478cbf;
}

/* 内部工具按钮：柔和的边界与无缝悬停 */
QFrame#FakeInputBox > QPushButton {
    background: transparent;
    border: none;
    border-left: 1px solid #202531; /* 极微弱的左侧分割线 */
    border-right: 1px solid #202531;/* 极微弱的右侧分割线 */
    border-radius: 0px;             /* 默认无圆角，融入整体 */
    padding: 4px 8px;
    margin: 0px;                    /* 【关键修复】取消margin，彻底贴合上下边缘 */
    color: #8a96b3;
}

QFrame#FakeInputBox > QPushButton:hover {
    background-color: #2e3548;
    color: #ffffff;
}
/* 如果按钮在最左边（如配置掩码按钮），悬停时应用左圆角 */
QFrame#FakeInputBox > QPushButton:first-child:hover {
    border-top-left-radius: 3px;
    border-bottom-left-radius: 3px;
}

/* 内部预览文本 (QLabel) */
QLabel[class="ExtraPreviewText"] {
    padding: 4px 8px;  /* 让预览文字也拥有舒适的边距 */
    color: #478cbf;
    font-size: 11px;
}

/* 下拉框去皮 */
QFrame#FakeInputBox > QComboBox {
    border: none;
    background: transparent;
    padding: 4px 8px; /* 同样补齐边距 */
    color: #e0e4eb;
}
QFrame#FakeInputBox > QComboBox::drop-down { border: none; }
"""

GODOT_LIGHT_QSS = """
QWidget { background-color: #e0e4e8; color: #222222; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #ffffff; alternate-background-color: #f2f5f7; border: 1px solid #b0b5bd; selection-background-color: #478cbf; selection-color: #fff;}
QHeaderView::section { background-color: #d1d6dc; border: none; border-bottom: 1px solid #b0b5bd; padding: 4px; color: #222; }
/* =======================================================
   大面积文本编辑区 (浅色清爽模式)
======================================================= */
QPlainTextEdit, QTextEdit {
    background-color: #f7f9fa; /* 极浅的微凹底色，告别突兀的深灰色补丁 */
    border: 1px solid #c2c7ce; /* 柔和的轮廓线 */
    border-radius: 4px;
    padding: 8px;
    color: #222222;
    font-family: 'Consolas', 'Segoe UI';
}

/* 独立单行输入框 */
QLineEdit {
    background-color: #f7f9fa;
    border: 1px solid #c2c7ce;
    padding: 4px 8px;
    border-radius: 4px;
    color: #222222;
}

/* 【关键魔法】：聚焦时变成纯白，让用户感觉"纸被抬起来了" */
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    background-color: #ffffff; /* 聚焦时背景变纯白，极其清爽 */
    border: 1px solid #478cbf; /* 亮起 Godot 焦点蓝 */
}
QPushButton { background-color: #cdd3d9; border: 1px solid #a6abb2; border-radius: 4px; padding: 5px 12px; color: #111;}
QPushButton:hover { background-color: #b8c0c7; }
QPushButton:pressed { background-color: #8da4b8; }
QComboBox { background-color: #ffffff; border: 1px solid #b0b5bd; border-radius: 4px; padding: 4px; }
QComboBox::drop-down { border: none; }

QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #b0b5bd; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #b0b5bd; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }

QScrollBar:vertical { background: #f2f5f7; width: 12px; }
QScrollBar::handle:vertical { background: #b8c0c7; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QFrame#DockHeader { background-color: #b0b5bd; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QWidget#DockBody { background-color: #e0e4e8; border: 1px solid #b0b5bd; border-top: none; }
QLabel#DockTitle { background-color: transparent; color: #111; font-weight: bold; }
QMenuBar { background-color: #e0e4e8; color: #222222; border-bottom: 1px solid #b0b5bd; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background-color: #b8c0c7; border-radius: 2px; }
QMenu { background-color: #ffffff; border: 1px solid #b0b5bd; padding: 4px; }
QMenu::item { padding: 6px 24px; color: #222; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; }

QLabel[class="InspectorTitle"] { font-weight: bold; color: #111; border-bottom: 1px solid #b0b5bd; padding-bottom: 2px; margin-top: 8px; }
QLabel[class="PropLabel"] { color: #444; }
QScrollArea { border: none; background-color: transparent; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
/* =======================================================
   预览区面板 (浅色透明模式)
======================================================= */
QFrame#PreviewFrame {
    background-color: transparent;    /* 彻底透明化 */
    border: none;
    border-top: 2px solid #8caec7;    /* 换成柔和的莫兰迪浅蓝灰 */
    border-bottom: 1px solid #b0b5bd; /* 底部浅色分割线 */
    border-radius: 0px;
    margin-top: 4px;
    margin-bottom: 8px;
}

QLabel[class="PreviewName"] {
    color: #111111;
    font-size: 18px;
    font-weight: bold;
    font-family: 'Microsoft YaHei', 'Segoe UI';
}

QLabel[class="PreviewMeta"] {
    color: #666666;
    font-size: 11px;
    border-bottom: 1px solid #d8dce3; /* 浅色分割线 */
    padding-bottom: 8px;
    margin-bottom: 4px;
}

QLabel[class="PreviewDesc"] {
    color: #178a39;
    font-size: 13px;
    padding-top: 4px;
}

QLabel[class="PreviewSubMeta"] {
    color: #c93b16;
    font-size: 12px;
    font-weight: bold;
    padding-top: 4px;
}

/* =======================================================
   综合输入框外壳 (浅色清爽模式)
======================================================= */
QFrame#FakeInputBox {
    background-color: #f7f9fa; /* 极浅的蓝白色作为凹陷输入区 */
    border: 1px solid #c2c7ce;
    border-radius: 4px;
}

QFrame#FakeInputBox:hover, QFrame#FakeInputBox:focus-within {
    background-color: #ffffff;
    border: 1px solid #478cbf;
}

QFrame#FakeInputBox > QLineEdit {
    background: transparent;
    border: none;
    padding: 4px 8px; /* 文字不再贴边 */
    color: #222222;
    font-family: 'Consolas', 'Segoe UI';
    selection-background-color: #478cbf;
    selection-color: #ffffff;
}

QFrame#FakeInputBox > QPushButton {
    background: transparent;
    border: none;
    border-left: 1px solid #d8dce3;
    border-right: 1px solid #d8dce3;
    border-radius: 0px;
    padding: 4px 8px;
    margin: 0px;
    color: #555555;
}

QFrame#FakeInputBox > QPushButton:hover {
    background-color: #e5e9f0;
    color: #111111;
}
QFrame#FakeInputBox > QPushButton:first-child:hover {
    border-top-left-radius: 3px;
    border-bottom-left-radius: 3px;
}

QLabel[class="ExtraPreviewText"] {
    padding: 4px 8px;
    color: #1a6b9c; /* 浅色模式下更深的蓝色，保证可读性 */
    font-size: 11px;
}

QFrame#FakeInputBox > QComboBox {
    border: none;
    background: transparent;
    padding: 4px 8px;
    color: #222222;
}
QFrame#FakeInputBox > QComboBox::drop-down { border: none; }
"""

class DockHeader(QFrame):
    def __init__(self, title, right_layout=None):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)
        if right_layout: layout.addLayout(right_layout)

# ============================================================
# 弹窗选择器 (TKT文本 & 技能)
# ============================================================

class TktPickerDialog(QDialog):
    def __init__(self, parent, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择 TKT 文本")
        self.resize(520, 550)
        self.selected_id = None
        self.tkt_items = sorted(tkt_dict.items(), key=lambda x: x[0])
        
        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)
        
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['ID', '文本'])
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._accept_selection)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        self._refresh()
        
    def _refresh(self):
        query = self.search_box.text().strip().lower()
        self.table.setRowCount(0)
        row = 0
        for eid, txt in self.tkt_items:
            if query and query not in txt.lower(): continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(eid)))
            self.table.setItem(row, 1, QTableWidgetItem(txt[:80].replace('\n', ' ')))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_id = int(self.table.item(sel[0].row(), 0).text())
            self.accept()

class SkillPickerDialog(QDialog):
    def __init__(self, parent, records, tkt_dict, cur_val):
        super().__init__(parent)
        self.setWindowTitle("选择技能")
        self.resize(600, 550)
        self.selected_index = None
        self.records = records
        self.tkt_dict = tkt_dict
        
        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._refresh)
        search_layout.addWidget(self.search_box)
        search_layout.addWidget(QLabel("类型:"))
        self.type_box = QComboBox()
        self.type_box.addItems(["全部"] + SKILL_TYPE_VALUES)
        self.type_box.currentIndexChanged.connect(self._refresh)
        search_layout.addWidget(self.type_box)
        layout.addLayout(search_layout)
        
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称'])
        self.table.setColumnWidth(0, 60); self.table.setColumnWidth(1, 60); self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("清空选择")
        btn_clear.clicked.connect(self._clear_selection)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self._accept_selection)
        btn_layout.addWidget(btn_cancel); btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        self._refresh()
        
    def _refresh(self):
        query = self.search_box.text().strip().lower()
        ft = self.type_box.currentText()
        self.table.setRowCount(0)
        row = 0
        for r in self.records:
            if r['skill_text_id'] == 0: continue
            idx = r['index']; sid = r['skill_text_id']; st = r['type']
            sn = skill_name(r, self.tkt_dict)
            if query and query not in f"{idx} {sid} {sn}".lower(): continue
            if ft != "全部":
                try: ft_val = int(ft.split('-')[0])
                except: ft_val = None
                if st != ft_val: continue
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.setItem(row, 1, QTableWidgetItem(str(sid)))
            self.table.setItem(row, 2, QTableWidgetItem(SKILL_TYPES.get(st, str(st))))
            self.table.setItem(row, 3, QTableWidgetItem(sn))
            row += 1

    def _accept_selection(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_index = int(self.table.item(sel[0].row(), 0).text())
            self.accept()
            
    def _clear_selection(self):
        self.selected_index = 0
        self.accept()

# ============================================================
# GUI 核心编辑器
# ============================================================

class SkillEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKSkill.dat 可视化编辑器 (PySide6)")
        self.resize(1260, 820)
        self.setMinimumSize(1000, 650)
        
        # 补全：精准加载原版要求的图标文件 TKS.ico
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        self.skill_path = self.tkt_path = None
        self.records = []; self.tkt = {}; self.tkt_full = {}
        self.filtered_indices = []; self._dirty = False
        self._editing_idx = None
        
        self.widget_map = {} 
        self.extra_map = {}  
        
        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    def _create_dock(self, title, widget_content, header_layout=None):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(DockHeader(title, header_layout))
        body = QWidget()
        body.setObjectName("DockBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.addWidget(widget_content)
        layout.addWidget(body, 1)
        return container

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        fm = menu_bar.addMenu("文件(F)")
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出 CSV…", self._export_csv)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = menu_bar.addMenu("编辑(E)")
        em.addAction("新建技能", QKeySequence("Ctrl+N"), self._new_skill)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)

        hm = menu_bar.addMenu("帮助(H)")
        hm.addAction("关于", self._show_about)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit()
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar.addWidget(btn_search)
        
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar.addWidget(btn_clear)
        
        toolbar.addSpacing(15)
        toolbar.addWidget(QLabel("类型:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型"] + SKILL_TYPE_VALUES)
        self.type_filter.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_filter)
        
        toolbar.addSpacing(15)
        btn_reload = QPushButton("重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)
        
        toolbar.addStretch()
        
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar.addWidget(btn_theme)
        
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # --- Main Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        main_layout.addWidget(self.splitter, 1)

        # --- Left Pane (Table) ---
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['技能ID', '文本ID', '类型', '技能名称', '技能点数', '耗费内力'])
        self.table.setColumnWidth(0, 60); self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(4, 70); self.table.setColumnWidth(5, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.splitter.addWidget(self._create_dock("技能列表", self.table))

        # --- Right Pane (Inspector) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)

        self.lbl_rec_idx = QLabel("未选中")
        self.lbl_rec_idx.setStyleSheet("font-size: 14px; font-weight: bold;")
        right_layout.addWidget(self.lbl_rec_idx)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("✅ 应用修改 (写入内存)")
        btn_apply.clicked.connect(self._apply_edit)
        btn_reset = QPushButton("🔄 重置为当前")
        btn_reset.clicked.connect(self._reset_edit)
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        right_layout.addLayout(btn_layout)

        # Scroll Area for properties (Godot Style Layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.edit_inner = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_inner)
        self.edit_layout.setContentsMargins(4, 4, 16, 4)
        
        # =======================================================
        # Preview Panel (Godot 资源检查器头部风格)
        # =======================================================
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(8, 12, 8, 12)
        pl.setSpacing(6)

        # 1. 技能名称 (大标题)
        self.preview_name = QLabel("(未选中)")
        self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True)
        pl.addWidget(self.preview_name)

        # 2. 技能元数据 (类型、点数、内力)
        self.preview_type = QLabel("")
        self.preview_type.setProperty("class", "PreviewMeta")
        self.preview_type.setWordWrap(True)
        pl.addWidget(self.preview_type)

        # 3. 技能描述 (替换掉丑陋的 QTextEdit，改用自动撑高的 QLabel)
        self.preview_desc = QLabel("请在左侧列表中选择一项技能。")
        self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextInteractionFlags(Qt.TextSelectableByMouse) # 允许鼠标选中文本复制
        pl.addWidget(self.preview_desc)

        # 4. 子技能高亮提示
        self.preview_sub = QLabel("")
        self.preview_sub.setProperty("class", "PreviewSubMeta")
        self.preview_sub.setWordWrap(True)
        pl.addWidget(self.preview_sub)

        self.edit_layout.addWidget(preview_frame)

        # Properties (No wireframes, Godot inspector grid alignment)
        self._build_field_group("基础属性", BASIC_FIELDS, 3)
        self._build_field_group("效果加成 (主动技能核心)", EFFECT_FIELDS, 3)
        self._build_field_group("状态免疫", IMMUNE_FIELDS, 3)
        self._build_field_group("高级属性", ADVANCED_FIELDS, 3)
        self._build_field_group("技能树引用表 (8组: 目标/进度)", TREE_FIELDS, 3)

        self.edit_layout.addStretch()
        scroll.setWidget(self.edit_inner)
        right_layout.addWidget(scroll, 1)

        self.splitter.addWidget(self._create_dock("检查器 (属性编辑)", right_widget))
        self.splitter.setSizes([450, 800])

        # Bottom Path
        path_layout = QHBoxLayout()
        self.lbl_skill_path = QLabel("TKSkill.dat: 未加载")
        self.lbl_tkt_path = QLabel("TKT.dat: 未加载")
        path_layout.addWidget(self.lbl_skill_path)
        path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt_path)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _build_field_group(self, title, fields, cols):
        """完全抹除嵌套 QFrame 线框，使用简洁的 Godot 标签对齐系统"""
        group_widget = QWidget()
        v_layout = QVBoxLayout(group_widget)
        v_layout.setContentsMargins(0, 4, 0, 4)
        v_layout.setSpacing(6)
        
        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "InspectorTitle")
        v_layout.addWidget(lbl_title)
        
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(15)
        grid.setContentsMargins(10, 0, 0, 0)
        
        for fi, (fn, fo, fl, ft, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, fn, fo, fl, ft, cmt)
            
        v_layout.addLayout(grid)
        self.edit_layout.addWidget(group_widget)

    def _build_field(self, grid, row, col, fn, fo, fl, ft, cmt):
        """现代化引擎 Inspector 对齐: 零边距外壳 + 内部软填充"""
        lbl = QLabel(f"{fl}")
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setProperty("class", "PropLabel")

        # 1. 创建联合输入框外壳
        input_wrapper = QFrame()
        input_wrapper.setObjectName("FakeInputBox")

        # 2. 彻底清空物理边距 (0,0,0,0)，让元素完全贴合外壳内壁
        container = QHBoxLayout(input_wrapper)
        container.setSpacing(0)
        container.setContentsMargins(0, 0, 0, 0)

        if ft == 'tkt' or ft == 'skill_pick':
            inp = QLineEdit()
            inp.setMaximumWidth(50)  # 稍微加宽一点，给 padding 留出空间

            btn = QPushButton("...")
            btn.setFixedWidth(28)
            btn.setCursor(Qt.PointingHandCursor)

            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText") # 赋予专属 class

            container.addWidget(inp)
            container.addWidget(btn)
            container.addWidget(extra, 1)

            self.widget_map[fn] = inp; self.extra_map[fn] = extra
            if ft == 'tkt': btn.clicked.connect(lambda _, f=fn: self._pick_tkt(f))
            else: btn.clicked.connect(lambda _, f=fn: self._pick_skill(f))

        elif ft == 'type' or ft == 'atk_type':
            cb = QComboBox()
            if ft == 'type': cb.addItems(SKILL_TYPE_VALUES)
            else: cb.addItems(ATK_TYPE_VALUES)
            container.addWidget(cb, 1)
            self.widget_map[fn] = cb

        elif ft == 'mask' or ft == 'flags':
            inp = QLineEdit()
            inp.setVisible(False)

            btn = QPushButton("配置")
            btn.setCursor(Qt.PointingHandCursor)
            # 配置按钮放在左侧时，约束它的最大宽度
            btn.setMaximumWidth(60)

            extra = QLabel("(无)")
            extra.setProperty("class", "ExtraPreviewText")
            extra.setWordWrap(False)

            container.addWidget(btn)
            container.addWidget(extra, 1)
            self.widget_map[fn] = inp; self.extra_map[fn] = extra

            if ft == 'mask':
                btn.clicked.connect(lambda _, f=fn: self._pick_status(f))
            else:
                btn.clicked.connect(lambda _, f=fn: self._pick_flags(f))
        else:
            inp = QLineEdit()
            container.addWidget(inp, 1)
            self.widget_map[fn] = inp

        grid.addWidget(lbl, row, col * 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(input_wrapper, row, col * 2 + 1)

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _apply_theme(self):
        qss = GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS
        self.setStyleSheet(qss)
        self._update_paths()

    def _update_paths(self):
        cg = "color: #55b572;" if self._is_dark else "color: #178a39;"
        cr = "color: #e27d60;" if self._is_dark else "color: #c93b16;"
        if self.skill_path: self.lbl_skill_path.setStyleSheet(cg); self.lbl_skill_path.setText(f"TKSkill.dat: {self.skill_path}")
        else: self.lbl_skill_path.setStyleSheet(cr); self.lbl_skill_path.setText("TKSkill.dat: 未加载")
        
        if self.tkt_path: self.lbl_tkt_path.setStyleSheet(cg); self.lbl_tkt_path.setText(f"TKT.dat: {self.tkt_path}")
        else: self.lbl_tkt_path.setStyleSheet(cr); self.lbl_tkt_path.setText("TKT.dat: 未加载")

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        sk = os.path.join(d, "TKSkill.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(sk):
            QMessageBox.warning(self, "文件缺失", "未找到 TKSkill.dat"); return
        self.skill_path = sk
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.skill_path: return
        self.status_var.setText("加载中…")
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.tkt_full = load_tkt_full(self.tkt_path)
        try:
            self.records = load_skills(self.skill_path); self._dirty = False
            nonempty = sum(1 for r in self.records if r['skill_text_id'] != 0)
            self.status_var.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _set_edit_enabled(self, en):
        self.edit_inner.setEnabled(en)

    def _apply_filter(self):
        q = self.search_entry.text().strip().lower()
        self.filtered_indices = []
        ftype = self.type_filter.currentText()
        for rec in self.records:
            if rec['skill_text_id'] == 0: continue
            if ftype and not ftype.startswith("全部"):
                if rec['type'] != int(ftype.split('-')[0]): continue
            if q:
                nm = skill_name(rec, self.tkt)
                if q not in f"{rec['index']} {rec['skill_text_id']} {nm}".lower():
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()

    def _clear_filter(self):
        self.search_entry.clear()
        self.type_filter.setCurrentIndex(0)
        self._apply_filter()

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            stype = SKILL_TYPES.get(r['type'], f"#{r['type']}")
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r['index'])))
            self.table.setItem(row, 1, QTableWidgetItem(str(r['skill_text_id'])))
            self.table.setItem(row, 2, QTableWidgetItem(stype))
            self.table.setItem(row, 3, QTableWidgetItem(skill_name(r, self.tkt)))
            self.table.setItem(row, 4, QTableWidgetItem(str(r['jp_cost'])))
            self.table.setItem(row, 5, QTableWidgetItem(str(r['mp_cost'])))

            # ==== 核心改造：为所有 4 种技能类型分配高辨识度专属颜色 ====
            if self._is_dark:
                # 深色模式高亮配色
                if r['type'] == 0:   color = QColor("#478cbf") # 指令: 引擎蓝
                elif r['type'] == 1: color = QColor("#e27d60") # 主动: 珊瑚橙 (极高辨识度)
                elif r['type'] == 2: color = QColor("#55b572") # 被动: 翠绿
                elif r['type'] == 3: color = QColor("#b988db") # 移动: 柔和紫
                else:                color = QColor("#dcdcdc") # 未知: 默认白灰
            else:
                # 浅色模式需要更深的颜色才能在白底上压住视觉
                if r['type'] == 0:   color = QColor("#28638f") # 深蓝
                elif r['type'] == 1: color = QColor("#bd5739") # 深橙红
                elif r['type'] == 2: color = QColor("#2d8046") # 深绿
                elif r['type'] == 3: color = QColor("#8a5bb8") # 深紫
                else:                color = QColor("#222222") # 未知: 默认黑

            for c in range(6):
                self.table.item(row, c).setForeground(color)

        self.table.blockSignals(False)

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        stype = SKILL_TYPES.get(rec['type'], f"#{rec['type']}")
        self.lbl_rec_idx.setText(f"技能 #{rec['index']}  文本ID={rec['skill_text_id']}  类型={stype}")

        nid = rec.get('skill_text_id', 0)
        n_txt = self.tkt.get(nid, "") if nid > 0 else ""
        # 加上前缀增加仪式感，空名称处理也更加优雅
        self.preview_name.setText(n_txt.split('\n')[0].strip() if n_txt else "未命名技能")

        did = nid + 400
        d_txt = self.tkt_full.get(did, "") if did > 0 else ""
        # 改用 setText，因为组件已经换成了 QLabel
        self.preview_desc.setText(d_txt if d_txt else "暂无关于该技能的详细描述。")
        
        hint = TYPE_HINT_LABELS.get(rec['type'], "")

        # ==== 检查器预览区类型同步高亮 ====
        if self._is_dark:
            type_color = {0: "#478cbf", 1: "#e27d60", 2: "#55b572", 3: "#b988db"}.get(rec['type'], "#dcdcdc")
        else:
            type_color = {0: "#28638f", 1: "#bd5739", 2: "#2d8046", 3: "#8a5bb8"}.get(rec['type'], "#222222")

        # 使用 HTML 富文本进行局部着色，完美保留 QSS 的边框与排版
        self.preview_type.setText(
            f'<span style="color: {type_color}; font-weight: bold;">【{stype}】</span> '
            f'| 点数={rec["jp_cost"]} | 内力={rec["mp_cost"]} | {hint}'
        )
        sc = rec.get('sub_count', -1)
        self.preview_sub.setText(f"子技能: {sc} 个 (ID {rec['index']+1} - {rec['index']+sc})" if sc >= 0 else "")

        for fn, fo, fl, ft, _ in ALL_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if not w: continue
            
            if ft == 'type' or ft == 'atk_type':
                for i in range(w.count()):
                    if w.itemText(i).startswith(f"{val}-"): w.setCurrentIndex(i); break
            else:
                w.setText(str(val))
                
            if ft == 'tkt':
                nid = int(val) if val else 0
                txt = self.tkt.get(nid, "") if nid > 0 else ""
                t = txt.split('\n')[0] if txt else ""
                self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            elif ft == 'mask':
                self._update_mask_label(fn, int(val) if val else 0)
            elif ft == 'flags':
                self._update_flags_label(fn, int(val) if val else 0)
            elif ft == 'skill_pick':
                sidx = int(val) if val else 0
                if 0 < sidx < len(self.records) and self.records[sidx]['skill_text_id'] != 0:
                    nm = skill_name(self.records[sidx], self.tkt)
                    self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)
                else:
                    self.extra_map[fn].setText("")

    def _update_mask_label(self, fn, mask):
        base = 0 if fn == 'immunity1' else 16
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append(STATUS_NAMES[base + i])
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _update_flags_label(self, fn, val):
        mask = val & 0xFFFF
        sel = [name for bit, name, _ in SPECIAL_FLAG_BITS if mask & (1 << bit)]
        self.extra_map[fn].setText(", ".join(sel) if sel else "(无)")

    def _pick_tkt(self, fn):
        if not self.tkt: return
        dlg = TktPickerDialog(self, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
            self.widget_map[fn].setText(str(dlg.selected_id))
            txt = self.tkt.get(dlg.selected_id, "")
            t = txt.split('\n')[0] if txt else ""
            self.extra_map[fn].setText((t[:8] + '...') if len(t) > 8 else t)
            if fn == 'skill_text_id': self.preview_name.setText(txt.split('\n')[0].strip() if txt else "(无)")

    def _pick_skill(self, fn):
        if not self.records: return
        dlg = SkillPickerDialog(self, self.records, self.tkt, int(self.widget_map[fn].text() or 0))
        if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
            self.widget_map[fn].setText(str(dlg.selected_index))
            nm = skill_name(self.records[dlg.selected_index], self.tkt) if dlg.selected_index > 0 else ""
            self.extra_map[fn].setText((nm[:8] + '...') if len(nm) > 8 else nm)

    def _pick_status(self, fn):
        base = 0 if fn == 'immunity1' else 16
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = QDialog(self)
        dlg.setWindowTitle("选择免疫状态")
        dlg.resize(360, 520)
        layout = QVBoxLayout(dlg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        c_layout = QVBoxLayout(content)
        checkboxes = []
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES): break
            cb = QCheckBox(f"{idx}. {STATUS_NAMES[idx]}")
            cb.setChecked(bool(cur & (1 << i)))
            checkboxes.append((i, cb))
            c_layout.addWidget(cb)
        c_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for _, cb in checkboxes])
        btn_none = QPushButton("全清")
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for _, cb in checkboxes])
        btn_ok = QPushButton("确定")
        def _ok():
            m = 0
            for i, cb in checkboxes:
                if cb.isChecked(): m |= (1 << i)
            if m >= 0x8000: m -= 0x10000
            self.widget_map[fn].setText(str(m))
            self._update_mask_label(fn, m & 0xFFFF)
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_layout.addWidget(btn_all); btn_layout.addWidget(btn_none); btn_layout.addStretch(); btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _pick_flags(self, fn):
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        dlg = QDialog(self)
        dlg.setWindowTitle("选择特殊标志")
        dlg.resize(300, 200)
        layout = QVBoxLayout(dlg)
        checkboxes = []
        for bit, name, desc in SPECIAL_FLAG_BITS:
            cb = QCheckBox(f"{name} ({desc})")
            cb.setChecked(bool(cur & (1 << bit)))
            checkboxes.append((bit, cb))
            layout.addWidget(cb)
            
        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("全清")
        btn_clear.clicked.connect(lambda: [cb.setChecked(False) for _, cb in checkboxes])
        btn_ok = QPushButton("确定")
        def _ok():
            m = 0
            for bit, cb in checkboxes:
                if cb.isChecked(): m |= (1 << bit)
            if m >= 0x8000: m -= 0x10000
            self.widget_map[fn].setText(str(m))
            self._update_flags_label(fn, m)
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        btn_layout.addWidget(btn_clear); btn_layout.addStretch(); btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _apply_edit(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        for fn, fo, fl, ft, _ in ALL_FIELDS:
            w = self.widget_map.get(fn)
            if not w: continue
            try:
                if ft == 'type' or ft == 'atk_type':
                    v = int(w.currentText().split('-')[0])
                else:
                    v = int(w.text() or 0)
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                rec[fn] = v
            except ValueError:
                rec[fn] = 0
                
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == rec['index']:
                self.table.selectRow(r); break
        self.status_var.setText(f"记录 #{rec['index']} 已修改 (内存)")

    def _reset_edit(self):
        if self._editing_idx is not None:
            self._populate_edit(self.records[self._editing_idx])

    def _new_skill(self):
        if not self.records: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                rec['skill_text_id'] = rec['index'] + 1
                rec['type'] = 1; rec['jp_cost'] = 1
                rec['sub_count'] = -1; rec['atk_type'] = -1
                self._dirty = True; self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r); break
                self._populate_edit(rec)
                self.status_var.setText(f"已创建新技能 → 槽位 #{rec['index']}")
                return
        QMessageBox.warning(self, "槽位已满", f"所有 {SKILL_CNT} 个槽位均已占用")

    def _copy_record(self):
        if self._editing_idx is None: return
        src = self.records[self._editing_idx]
        if src['skill_text_id'] == 0: return
        for rec in self.records:
            if rec['skill_text_id'] == 0:
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True; self._apply_filter()
                for r in range(self.table.rowCount()):
                    if int(self.table.item(r, 0).text()) == rec['index']:
                        self.table.selectRow(r); break
                self._populate_edit(rec)
                return

    def _clear_current(self):
        if self._editing_idx is None: return
        rec = self.records[self._editing_idx]
        if rec['skill_text_id'] == 0: return
        reply = QMessageBox.question(self, "确认", f"确定清空记录 #{rec['index']}?")
        if reply == QMessageBox.Yes:
            for k, fo, _, _, _ in ALL_FIELDS: rec[k] = 0
            rec['sub_count'] = -1
            self._dirty = True; self._apply_filter()
            self._populate_edit(rec)

    def _save(self):
        if not self.skill_path or not self.records: return
        reply = QMessageBox.question(self, "确认保存", f"将覆盖保存并生成.bak:\n{self.skill_path}")
        if reply == QMessageBox.Yes:
            try:
                with open(self.skill_path, 'rb') as s:
                    with open(self.skill_path + ".bak", 'wb') as d: d.write(s.read())
            except: pass
            try:
                save_skills(self.skill_path, self.records); self._dirty = False
                QMessageBox.information(self, "成功", "保存成功！")
                self.status_var.setText(f"已保存 → {self.skill_path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p, _ = QFileDialog.getSaveFileName(self, "导出CSV", "", "CSV (*.csv)")
        if not p: return
        with open(p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            hdr = ['索引', '名称', '类型'] + [fl for _, _, fl, _, _ in ALL_FIELDS]
            writer.writerow(hdr)
            for rec in self.records:
                if rec['skill_text_id'] == 0: continue
                row = [rec['index'], skill_name(rec, self.tkt), SKILL_TYPES.get(rec['type'], str(rec['type']))]
                row += [rec[fn] for fn, _, _, _, _ in ALL_FIELDS]
                writer.writerow(row)
        self.status_var.setText(f"已导出: {p}")

    def _show_about(self):
        QMessageBox.about(self, "关于", "TKSkill.dat PySide6 编辑器\n已应用 Godot 4.6 级别布局与纯净控件约束。")

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存", "有未保存的修改, 确定退出?")
            if reply == QMessageBox.No:
                event.ignore(); return
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    editor = SkillEditorApp()
    editor.show()
    sys.exit(app.exec())