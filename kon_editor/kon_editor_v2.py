#!/usr/bin/env python3
"""
TKKon.dat 可视化编辑器 v3.2 (PySide6 — Godot 4.6 风格)
=============================================================
UI 样式完全对齐 skill_editor_v2.py 的 FakeInputBox / InspectorTitle / PreviewFrame 体系。
底层 LZSS 引擎与 TKKon/TKT 二进制解析逻辑 100% 保留。
"""

import struct, os, sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel,
    QScrollArea, QGroupBox, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar,
)
from PySide6.QtGui import QIntValidator, QColor, QFont, QIcon, QShortcut
from PySide6.QtCore import Qt

# ============================================================
# QSS 样式表 (100% 对齐 skill_editor_v2.py 的 Godot 4.6 规范)
# ============================================================

GODOT_DARK_QSS = """
QWidget { background-color: #202531; color: #dcdcdc; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #1a1e27; alternate-background-color: #202531; border: 1px solid #14171f; selection-background-color: #478cbf; }
QHeaderView::section { background-color: #202531; border: none; border-bottom: 1px solid #14171f; padding: 4px; }

QPlainTextEdit, QTextEdit {
    background-color: #161923; border: 1px solid #0b0c12;
    border-radius: 4px; padding: 8px; color: #e0e4eb;
    font-family: 'Consolas', 'Segoe UI';
}

QLineEdit {
    background-color: #161923; border: 1px solid #0b0c12;
    padding: 4px 8px; border-radius: 4px; color: #e0e4eb;
}
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    background-color: #1a1e29; border: 1px solid #478cbf;
}
QLineEdit:disabled { background-color: #202531; color: #666; border: 1px dashed #2a303d; }

QPushButton {
    background-color: #2e3548; border: 1px solid #14171f;
    border-radius: 4px; padding: 5px 12px;
}
QPushButton:hover { background-color: #3b445c; }
QPushButton:pressed { background-color: #478cbf; color: #fff; }

QComboBox {
    background-color: #2e3548; border: 1px solid #14171f;
    border-radius: 4px; padding: 4px;
}
QComboBox::drop-down { border: none; }

QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #14171f; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #14171f; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }

QScrollBar:vertical { background: #1a1e27; width: 12px; }
QScrollBar::handle:vertical { background: #3b445c; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QCheckBox { spacing: 4px; }
QCheckBox::indicator { width: 15px; height: 15px; }

QMenuBar { background-color: #202531; color: #dcdcdc; border-bottom: 1px solid #14171f; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background-color: #3b445c; border-radius: 2px; }
QMenu { background-color: #202531; border: 1px solid #14171f; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #478cbf; color: #ffffff; }

QLabel[class="InspectorTitle"] { font-weight: bold; color: #a5b0cb; border-bottom: 1px solid #14171f; padding-bottom: 2px; margin-top: 8px; }
QLabel[class="PropLabel"] { color: #8a96b3; }
QScrollArea { border: none; background-color: transparent; }
QScrollArea > QWidget > QWidget { background-color: transparent; }

/* 预览区面板 */
QFrame#PreviewFrame {
    background-color: transparent; border: none;
    border-top: 2px solid #2b4f70; border-bottom: 1px solid #14171f;
    border-radius: 0px; margin-top: 4px; margin-bottom: 8px;
}
QLabel[class="PreviewName"] { color: #e0e4eb; font-size: 18px; font-weight: bold; font-family: 'Microsoft YaHei', 'Segoe UI'; }
QLabel[class="PreviewMeta"] { color: #8a96b3; font-size: 11px; border-bottom: 1px solid #2e3548; padding-bottom: 8px; margin-bottom: 4px; }
QLabel[class="PreviewDesc"] { color: #55b572; font-size: 13px; padding-top: 4px; }
QLabel[class="PreviewSubMeta"] { color: #e27d60; font-size: 12px; font-weight: bold; padding-top: 4px; }

/* FakeInputBox 内凹输入框外壳 */
QFrame#FakeInputBox {
    background-color: #161923; border: 1px solid #0b0c12; border-radius: 4px;
}
QFrame#FakeInputBox:hover, QFrame#FakeInputBox:focus-within {
    background-color: #1a1e29; border: 1px solid #478cbf;
}
QFrame#FakeInputBox > QLineEdit {
    background: transparent; border: none; padding: 4px 8px;
    color: #e0e4eb; font-family: 'Consolas', 'Segoe UI'; selection-background-color: #478cbf;
}
QFrame#FakeInputBox > QPushButton {
    background: transparent; border: none;
    border-left: 1px solid #202531; border-radius: 0px;
    padding: 4px 8px; margin: 0px; color: #8a96b3;
}
QFrame#FakeInputBox > QPushButton:hover { background-color: #2e3548; color: #ffffff; }
QFrame#FakeInputBox > QPushButton:first-child:hover { border-top-left-radius: 3px; border-bottom-left-radius: 3px; }
QLabel[class="ExtraPreviewText"] { padding: 4px 8px; color: #478cbf; font-size: 11px; }
QFrame#FakeInputBox > QComboBox {
    border: none; background: transparent; padding: 4px 8px; color: #e0e4eb;
}
QFrame#FakeInputBox > QComboBox::drop-down { border: none; }

/* 拆分字段内部标签 */
QLabel[class="SplitFieldLabel"] { color: #8a96b3; font-size: 11px; padding: 0 4px; }

QGroupBox {
    border: 1px solid #2a303d; border-radius: 4px;
    margin-top: 12px; padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; color: #9da5b4;
}
"""

GODOT_LIGHT_QSS = """
QWidget { background-color: #e0e4e8; color: #222222; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QTableWidget { background-color: #ffffff; alternate-background-color: #f2f5f7; border: 1px solid #b0b5bd; selection-background-color: #478cbf; selection-color: #fff; }
QHeaderView::section { background-color: #d1d6dc; border: none; border-bottom: 1px solid #b0b5bd; padding: 4px; color: #222; }

QPlainTextEdit, QTextEdit {
    background-color: #f7f9fa; border: 1px solid #c2c7ce;
    border-radius: 4px; padding: 8px; color: #222222; font-family: 'Consolas', 'Segoe UI';
}

QLineEdit {
    background-color: #f7f9fa; border: 1px solid #c2c7ce;
    padding: 4px 8px; border-radius: 4px; color: #222222;
}
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    background-color: #ffffff; border: 1px solid #478cbf;
}
QLineEdit:disabled { background-color: #f3f4f6; color: #9ca3af; border: 1px dashed #d1d5db; }

QPushButton {
    background-color: #cdd3d9; border: 1px solid #a6abb2;
    border-radius: 4px; padding: 5px 12px; color: #111;
}
QPushButton:hover { background-color: #b8c0c7; }
QPushButton:pressed { background-color: #8da4b8; }

QComboBox {
    background-color: #ffffff; border: 1px solid #b0b5bd;
    border-radius: 4px; padding: 4px;
}
QComboBox::drop-down { border: none; }

QSplitter::handle { image: none; background-color: transparent; }
QSplitter::handle:horizontal { border-left: 1px solid #b0b5bd; margin-left: 3px; margin-right: 3px; }
QSplitter::handle:vertical { border-top: 1px solid #b0b5bd; margin-top: 3px; margin-bottom: 3px; }
QSplitter::handle:horizontal:hover { border-left: 1px solid #478cbf; }
QSplitter::handle:vertical:hover { border-top: 1px solid #478cbf; }

QScrollBar:vertical { background: #f2f5f7; width: 12px; }
QScrollBar::handle:vertical { background: #b8c0c7; border-radius: 6px; min-height: 20px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QCheckBox { spacing: 4px; }
QCheckBox::indicator { width: 15px; height: 15px; }

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

QFrame#PreviewFrame {
    background-color: transparent; border: none;
    border-top: 2px solid #8caec7; border-bottom: 1px solid #b0b5bd;
    border-radius: 0px; margin-top: 4px; margin-bottom: 8px;
}
QLabel[class="PreviewName"] { color: #111111; font-size: 18px; font-weight: bold; font-family: 'Microsoft YaHei', 'Segoe UI'; }
QLabel[class="PreviewMeta"] { color: #666666; font-size: 11px; border-bottom: 1px solid #d8dce3; padding-bottom: 8px; margin-bottom: 4px; }
QLabel[class="PreviewDesc"] { color: #178a39; font-size: 13px; padding-top: 4px; }
QLabel[class="PreviewSubMeta"] { color: #c93b16; font-size: 12px; font-weight: bold; padding-top: 4px; }

QFrame#FakeInputBox {
    background-color: #f7f9fa; border: 1px solid #c2c7ce; border-radius: 4px;
}
QFrame#FakeInputBox:hover, QFrame#FakeInputBox:focus-within {
    background-color: #ffffff; border: 1px solid #478cbf;
}
QFrame#FakeInputBox > QLineEdit {
    background: transparent; border: none; padding: 4px 8px;
    color: #222222; font-family: 'Consolas', 'Segoe UI';
    selection-background-color: #478cbf; selection-color: #ffffff;
}
QFrame#FakeInputBox > QPushButton {
    background: transparent; border: none;
    border-left: 1px solid #d8dce3; border-radius: 0px;
    padding: 4px 8px; margin: 0px; color: #555555;
}
QFrame#FakeInputBox > QPushButton:hover { background-color: #e5e9f0; color: #111111; }
QFrame#FakeInputBox > QPushButton:first-child:hover { border-top-left-radius: 3px; border-bottom-left-radius: 3px; }
QLabel[class="ExtraPreviewText"] { padding: 4px 8px; color: #1a6b9c; font-size: 11px; }
QFrame#FakeInputBox > QComboBox {
    border: none; background: transparent; padding: 4px 8px; color: #222222;
}
QFrame#FakeInputBox > QComboBox::drop-down { border: none; }

QLabel[class="SplitFieldLabel"] { color: #666; font-size: 11px; padding: 0 4px; }

QGroupBox {
    border: 1px solid #b0b5bd; border-radius: 4px;
    margin-top: 12px; padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; color: #4b5563;
}
"""

# ============================================================
# 业务逻辑层 (严格保留原版算法)
# ============================================================

def lzss_decompress(data):
    if len(data) < 12: return b''
    ts = struct.unpack_from('<I', data, 0)[0]; bs = struct.unpack_from('<I', data, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078; out = bytearray(); flags = 0; pos = 12; bc = 4
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
                b = w[(j + ro) & 0xFFF]; out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out[:ts])

def lzss_compress(data):
    src = data; sl = len(src); flat = bytes(bytearray([0x20] * 4096) + src)
    tokens = []; pos = 0
    while pos < sl:
        curr = 4096 + pos; ms = min(18, sl - pos); bl, bo = 0, 0
        if ms >= 3:
            for length in range(ms, 2, -1):
                pat = flat[curr:curr + length]; end = curr + length - 1; start = max(0, curr - 4096)
                idx = flat.rfind(pat, start, end)
                if idx != -1: bl = length; bo = (idx - 18) & 0xFFF; break
        if bl >= 3: tokens.append((False, bo, bl)); pos += bl
        else: tokens.append((True, src[pos], 0)); pos += 1
    stream = bytearray(); ti = 0
    while ti < len(tokens):
        fb = 0; be = min(ti + 8, len(tokens))
        for i in range(ti, be):
            if tokens[i][0]: fb |= (1 << (i - ti))
        stream.append(fb)
        for i in range(ti, be):
            if tokens[i][0]: stream.append(tokens[i][1])
            else:
                off, length = tokens[i][1], tokens[i][2]; el = length - 3
                stream.append(off & 0xFF); stream.append(((off >> 4) & 0xF0) | (el & 0x0F))
        ti = be
    ds = sl; bd = struct.pack('<I', ds) + bytes(stream)
    return struct.pack('<II', ds, len(bd)) + bd

def load_tkt(tkt_path):
    if not tkt_path or not os.path.exists(tkt_path): return {}
    with open(tkt_path, 'rb') as f: raw = f.read()
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
            if s and s != '0': lookup[eid] = s
    return lookup

def load_tkkon_names(csv_path):
    names = {}
    if not csv_path or not os.path.exists(csv_path): return names
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = __import__('csv').reader(f); next(reader, None)
        for row in reader:
            if len(row) >= 2 and row[0].strip().isdigit():
                idx = int(row[0]); name = row[1].strip()
                if name: names[idx] = name
    return names

KON_REC = 40; KON_CNT = 650; KON_FIELD_COUNT = 20; KON_DECOMPRESSED = 26000

STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

KON_FIELDS = [
    ("exec_mode",        0,  "执行模式",      "高字节=攻击距离(负=自身, 0=单格, 1-3=近战, 6+=远程); 低字节=范围开关"),
    ("target_param",     2,  "目标参数",      "高字节=效果面积(0=单体, 1+=菱形层数, -1/FF=全场, -2/FE=全场排除自身); 低字节=扩散开关"),
    ("target_filter",    4,  "目标过滤",      "高字节=目标格子(0=全部, 1=仅角色, 2=仅空地); 低字节=阵营匹配(0=对立, 1=同阵营, 2=任意)"),
    ("tkact_id",         6,  "TKAct动画索引", "TKAct.dat 条目索引 (0..649, -1=无)"),
    ("hp_damage",        8,  "生命伤害",      "(-1)=ATK; (0)=无; (1~999)=固定; (1001~1999)=目标生命%; (2001~2999)=ATK+; (3001+)=ATK×"),
    ("mp_damage",       10,  "内力伤害",      "(0)=无; (1~999)=固定内力伤; (1001~1999)=目标内力%"),
    ("accuracy",        12,  "附加命中",      "命中率加算值"),
    ("extra_damage",    14,  "附加伤害",      "附加伤害值 (极少使用)"),
    ("hp_restore",      16,  "生命回复",      "(0)=无; (1~999)=固定回复; (1001~1999)=最大生命%; 仅生命<25%时触发"),
    ("mp_restore",      18,  "内力回复",      "(0)=无; (1~999)=固定回复; (1001~1999)=最大内力%; 仅内力<25%时触发"),
    ("inflict_status_lo", 20, "导致状态1-16",  "施加状态位掩码低16位"),
    ("inflict_status_hi", 22, "导致状态17-32", "施加状态位掩码高16位"),
    ("remove_status_lo",  24, "解除状态1-16",  "移除状态位掩码低16位"),
    ("remove_status_hi",  26, "解除状态17-32", "移除状态位掩码高16位"),
    ("timing_mod",      28,  "时序修正",      "行动顺序修正值"),
    ("unused15",        30,  "未使用15",      "始终为0"),
    ("unused16",        32,  "未使用16",      "始终为0"),
    ("unused17",        34,  "未使用17",      "始终为0"),
    ("unused18",        36,  "未使用18",      "始终为0"),
    ("exec_flags",      38,  "执行标志",      "bit0=显示待机, bit1=物品, bit2=物理; 0=法术"),
]

ACTIVE_FIELDS = [f for f in KON_FIELDS if not f[0].startswith('unused')]

# ============================================================
# 描述解析函数
# ============================================================

def describe_exec_mode(val):
    if val < 0: return "自身目标"
    hi = (val >> 8) & 0xFF; lo = val & 0xFF
    if hi == 0 and lo == 0: return "单格"
    parts = []; range_text = "" if lo == 0 else "[范围禁用]"
    if hi > 0: parts.append(f"距离={hi}格")
    parts.append(range_text)
    return "  ".join(parts)

def describe_target_param(val):
    if val < 0:
        hi = (val >> 8) & 0xFF
        if hi == 255: return "全场目标"
        elif hi == 254: return "全场(排除自身)"
        return f"特殊({val})"
    hi = (val >> 8) & 0xFF; lo = val & 0xFF
    if hi == 0 and lo == 0: return "无扩散(单体)"
    spread_text = "" if lo == 0 else "[扩散禁用]"
    parts = []
    if hi > 0: parts.append(f"面积={hi}格")
    parts.append(spread_text)
    return "  ".join(parts)

def describe_target_filter(val):
    lo = val & 0xFF; hi = (val >> 8) & 0xFF
    target_map = {0: "全部", 1: "仅角色", 2: "仅空地"}
    faction_map = {0: "对立阵营", 1: "同阵营", 2: "任意阵营"}
    return f"{target_map.get(hi, f'目标{hi}')}  {faction_map.get(lo, f'阵营{lo}')}"

def describe_exec_flags(val):
    lo = val & 0xFF
    parts = ["显示待机" if (lo & 1) else "隐藏待机"]
    if lo & 2: parts.append("物品")
    parts.append("物理" if (lo & 4) else "法术")
    return "  ".join(parts)

def describe_hp_damage(val):
    if val == -1: return "单位攻击力"
    if val == 0: return "无伤害"
    if 1 <= val <= 999: return f"固定伤害={val}"
    if 1001 <= val <= 1999: return f"生命%伤害={val - 1000}%"
    if 2001 <= val <= 2999: return f"攻击力+{val - 2000}"
    if val >= 3001: return f"攻击力×{100 + val - 3000}%"
    return f"特殊({val})"

def describe_resource_val(val, resource_name):
    if val == 0: return f"无{resource_name}"
    if 1 <= val <= 999: return f"固定{resource_name}={val}"
    if 1001 <= val <= 1999: return f"{resource_name}%={val - 1000}%"
    return f"{resource_name}=({val})"

def kon_record_name(rec, tkt, names=None):
    idx = rec['index']
    if names and idx in names and names[idx]: return names[idx]
    cid = rec.get('tkact_id', 0); parts = []
    em = rec.get('exec_mode', 0); tp = rec.get('target_param', 0)
    if em < 0: parts.append("自身")
    elif em != 0:
        rh = (em >> 8) & 0xFF
        if rh > 0: parts.append(f"距{rh}")
    tp_hi = (tp >> 8) & 0xFF
    if tp_hi > 0: parts.append(f"面{tp_hi}")
    desc = " ".join(parts) if parts else ""
    if cid >= 0: return f"动画#{cid} {desc}".strip()
    return f"空槽-#{idx}"

def load_kon(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    if len(dec) != KON_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 26000")
    recs = []
    for i in range(KON_CNT):
        off = i * KON_REC
        vals = struct.unpack_from('<' + 'h' * KON_FIELD_COUNT, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _) in enumerate(KON_FIELDS): rec[fn] = vals[fi]
        recs.append(rec)
    return recs

def save_kon(fp, recs):
    buf = bytearray(KON_CNT * KON_REC)
    for rec in recs[:KON_CNT]:
        i = rec['index']; off = i * KON_REC
        vals = [rec[fn] for fn, _, _, _ in KON_FIELDS]
        struct.pack_into('<' + 'h' * KON_FIELD_COUNT, buf, off, *vals)
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# QTableWidget 排序子类
# ============================================================

class NumericTableItem(QTableWidgetItem):
    def __lt__(self, other):
        a = self.data(Qt.UserRole); b = other.data(Qt.UserRole)
        if a is not None and b is not None:
            try: return float(a) < float(b)
            except (ValueError, TypeError): pass
        return super().__lt__(other)

# ============================================================
# 对话框: 状态掩码多选
# ============================================================

class StatusMaskDialog(QDialog):
    def __init__(self, title, current_mask, base_idx, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.setFixedSize(320, 520)
        self.checkboxes = []
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); vlay = QVBoxLayout(content)
        for i in range(16):
            idx = base_idx + i
            if idx >= len(STATUS_NAMES): break
            cb = QCheckBox(f"{idx}. {STATUS_NAMES[idx]}")
            cb.setChecked(bool(current_mask & (1 << i)))
            self.checkboxes.append(cb); vlay.addWidget(cb)
        vlay.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("全选"); btn_all.clicked.connect(lambda: [c.setChecked(True) for c in self.checkboxes])
        btn_clear = QPushButton("全清"); btn_clear.clicked.connect(lambda: [c.setChecked(False) for c in self.checkboxes])
        btn_ok = QPushButton("确定"); btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_all); btn_layout.addWidget(btn_clear)
        btn_layout.addStretch(); btn_layout.addWidget(btn_ok); btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def get_mask(self):
        m = sum((1 << i) for i, cb in enumerate(self.checkboxes) if cb.isChecked())
        return m if m < 0x8000 else m - 0x10000

# ============================================================
# 对话框: 字段参考
# ============================================================

class FieldRefDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段参考 v3.0 (逆向来源)"); self.resize(700, 580)
        layout = QVBoxLayout(self)
        text = QTextEdit(); text.setReadOnly(True); text.setFont(QFont("Consolas", 9))
        lines = ["TKKon.dat 字段映射 v3.0 (2026-05 语义修正)", ""]
        lines.append(f"【记录布局】{KON_CNT} 条 × {KON_REC} 字节 = {KON_DECOMPRESSED} 字节")
        lines.append(f"  20 × int16 (小端序) 共 {KON_REC} 字节/条")
        lines.append("")
        lines.append("【★ v3.0 修正: 字段语义完全重分析】")
        lines.append("  field[0-2] 是战斗引擎操作参数，非TKT文本引用")
        lines.append("【字段详情】")
        for fn, fo, fl, cmt in KON_FIELDS:
            marker = " ● 未使用" if fn.startswith('unused') else ""
            lines.append(f"  [{fo:02d}] {fl:<10s}{marker}")
            lines.append(f"       {cmt}")
        lines.append("")
        lines.append("【反编译函数引用】")
        for s in ["sub_43D53C: 目标区域标记","sub_43D8B0: 目标验证过滤","sub_43E980: 伤害计算核心",
                   "sub_4458B0: 技能执行主函数","sub_4434BC: 动画运行时","sub_4173F8: TKKon 加载入口",
                   "Maker.exe sub_4027FF: 解压后大小校验"]:
            lines.append(f"  {s}")
        lines.append("")
        lines.append("【伤害字段编码规则 (sub_43E980)】")
        for s in ["0→无效果","1~999→固定值","1001~1999→最大值%(val-1000)",
                   "-1→ATK","2001~2999→ATK+(val-2000)","3001+→ATK×(1+(val-3000)/100)"]:
            lines.append(f"  {s}")
        text.setPlainText('\n'.join(lines)); layout.addWidget(text)
        btn_close = QPushButton("关闭"); btn_close.clicked.connect(self.close)
        bl = QHBoxLayout(); bl.addStretch(); bl.addWidget(btn_close); layout.addLayout(bl)

# ============================================================
# 主编辑器窗口
# ============================================================

class KonEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKKon.dat 可视化编辑器 v3.2 - PySide6")
        self.resize(1320, 820); self.setMinimumSize(1050, 650)

        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))

        app_inst = QApplication.instance()
        self.is_dark_theme = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True
        self.kon_path = None; self.tkt_path = None
        self.records = []; self.tkt = {}; self.names = {}
        self.filtered_indices = []; self._dirty = False; self._editing_idx = -1

        self.widget_map = {}      # QLineEdit / QComboBox for direct value fields
        self.extra_map = {}       # QLabel for parsed description text
        self.split_map = {}       # (hi_w, lo_w) for split fields

        self._build_ui()
        self._apply_theme()
        self._set_edit_enabled(False)
        self._center_window()

    # ============================================================
    # 主题
    # ============================================================

    def _apply_theme(self):
        qss = GODOT_DARK_QSS if self.is_dark_theme else GODOT_LIGHT_QSS
        self.setStyleSheet(qss)

    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        self._apply_theme()
        self._refresh_table()

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self):
        # -- 菜单栏 --
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录...\tCtrl+O", self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("导出 CSV...", self._export_csv)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新建条目\tCtrl+N", self._new_record)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("清空当前记录", self._clear_current)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段参考 (逆向来源)", self._show_field_ref)
        hm.addAction("切换 Godot 主题 (Dark/Light)\tF5", self._toggle_theme)
        hm.addAction("关于", self._show_about)

        QShortcut("F5", self).activated.connect(self._toggle_theme)

        # -- 工具栏 (对齐原版, 仅增加切换主题按钮) --
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit(); self.search_input.setFixedWidth(160)
        self.search_input.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_input)

        btn_search = QPushButton("🔍 搜索"); btn_search.clicked.connect(self._apply_filter)
        btn_clear = QPushButton("✕ 清除"); btn_clear.clicked.connect(self._clear_filter)
        toolbar.addWidget(btn_search); toolbar.addWidget(btn_clear)
        toolbar.addSpacing(8)

        self.chk_show_empty = QCheckBox("显示空槽"); self.chk_show_empty.setChecked(True)
        self.chk_show_empty.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self.chk_show_empty)
        toolbar.addSpacing(8)

        btn_reload = QPushButton("🔄 重新加载"); btn_reload.clicked.connect(self._reload)
        toolbar.addWidget(btn_reload)

        btn_theme = QPushButton("🌗 切换主题"); btn_theme.clicked.connect(self._toggle_theme)
        btn_theme.setToolTip("切换 Godot 深色/浅色主题 (F5)")
        toolbar.addWidget(btn_theme)
        toolbar.addStretch()

        self.status_label = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.status_label.setStyleSheet("color: #888;")
        toolbar.addWidget(self.status_label)

        # -- 主布局 --
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(4)
        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        main_layout.addWidget(splitter, 1)

        self._build_table(splitter)
        self._build_edit_panel(splitter)
        splitter.setSizes([480, 820])

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_kon = QLabel("TKKon.dat: 未加载"); self.lbl_kon.setStyleSheet("color: #e27d60;")
        self.lbl_tkt = QLabel("TKT.dat: 未加载"); self.lbl_tkt.setStyleSheet("color: #e27d60;")
        path_layout.addWidget(self.lbl_kon); path_layout.addSpacing(20)
        path_layout.addWidget(self.lbl_tkt); path_layout.addStretch()
        main_layout.addLayout(path_layout)

    # ----------- 左侧表格 -----------

    def _build_table(self, parent):
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["序号", "动画", "距离", "名称", "范围", "伤害", "目标", "类型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        col_widths = [38, 42, 42, 95, 52, 55, 55, 50]
        for i, w in enumerate(col_widths): self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        parent.addWidget(self.table)

    # ----------- 右侧编辑面板 -----------

    def _build_edit_panel(self, parent):
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(4)

        # Inspector 标题
        self.lbl_inspector_title = QLabel("技能属性检查器 — 未选中")
        self.lbl_inspector_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #478cbf; padding: 2px 0;")
        right_layout.addWidget(self.lbl_inspector_title)

        # 应用/重置按钮
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("✅ 应用修改"); self.btn_apply.clicked.connect(self._apply_edit)
        self.btn_reset = QPushButton("🔄 撤销修改"); self.btn_reset.clicked.connect(self._reset_edit)
        btn_layout.addWidget(self.btn_apply); btn_layout.addWidget(self.btn_reset); btn_layout.addStretch()
        right_layout.addLayout(btn_layout)

        # 滚动区域
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        edit_container = QWidget()
        self.edit_layout = QVBoxLayout(edit_container)
        self.edit_layout.setContentsMargins(4, 4, 16, 4)
        self.edit_layout.setSpacing(2)

        # 预览面板 (PreviewFrame)
        preview = QFrame(); preview.setObjectName("PreviewFrame")
        pl = QVBoxLayout(preview); pl.setContentsMargins(8, 12, 8, 12); pl.setSpacing(6)
        self.preview_name = QLabel("(未选中)"); self.preview_name.setProperty("class", "PreviewName")
        self.preview_name.setWordWrap(True); pl.addWidget(self.preview_name)
        self.preview_type = QLabel(""); self.preview_type.setProperty("class", "PreviewMeta")
        self.preview_type.setWordWrap(True); pl.addWidget(self.preview_type)
        self.preview_desc = QLabel("(空动作)"); self.preview_desc.setProperty("class", "PreviewDesc")
        self.preview_desc.setWordWrap(True); pl.addWidget(self.preview_desc)
        self.preview_sub = QLabel(""); self.preview_sub.setProperty("class", "PreviewSubMeta")
        self.preview_sub.setWordWrap(True); pl.addWidget(self.preview_sub)
        self.edit_layout.addWidget(preview)

        # 字段组 (列数对齐原版: 4, 5, 5, 5)
        self._build_field_group("战斗执行参数 (offset 0–6)", ACTIVE_FIELDS[:4], 4)
        self._build_field_group("伤害/回复参数 (offset 8–18)", ACTIVE_FIELDS[4:10], 5)
        self._build_field_group("状态位掩码 (offset 20–28)", ACTIVE_FIELDS[10:15], 5)
        self._build_field_group("未使用字段 + 执行标志 (offset 30–38)", KON_FIELDS[15:], 5)

        self.edit_layout.addStretch()
        scroll.setWidget(edit_container)
        right_layout.addWidget(scroll, 1)
        parent.addWidget(right_widget)

    def _build_field_group(self, title, fields, cols=4):
        """原版布局: QGroupBox + QGridLayout, label 在上 input 在下"""
        group = QGroupBox(title)
        grid = QGridLayout(group)
        grid.setVerticalSpacing(4); grid.setHorizontalSpacing(8)

        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            self._build_field(grid, r, c, fn, fo, fl, cmt)

        self.edit_layout.addWidget(group)

    def _build_field(self, grid, row, col, fn, fo, fl, cmt):
        """单个字段: label 在上, 输入控件在下, 解析文本在最下"""
        cell = QVBoxLayout(); cell.setSpacing(2)

        lbl = QLabel(fl)
        lbl.setToolTip(f"[{fo:02d}] {cmt}")
        lbl.setStyleSheet("font-size: 11px; color: #8a96b3;")
        cell.addWidget(lbl)

        is_unused = fn.startswith('unused')
        is_mask = 'status' in fn
        is_filter = fn == 'target_filter'
        is_split = fn in ('exec_mode', 'target_param')
        is_bitmask = fn == 'exec_flags'

        if is_bitmask:
            row_w = QWidget(); h = QHBoxLayout(row_w); h.setContentsMargins(0,0,0,0); h.setSpacing(4)
            cb0 = QCheckBox("显示待机动画"); cb0.setToolTip("显示施法者待机动画 (bit0)")
            cb1 = QCheckBox("使用物品"); cb1.setToolTip("物品触发逻辑 (bit1)")
            cb2 = QCheckBox("物理攻击"); cb2.setToolTip("物理伤害公式 (bit2)")
            h.addWidget(cb0); h.addWidget(cb1); h.addWidget(cb2); h.addStretch()
            self.split_map[fn] = (cb0, cb1, cb2)
            extra = QLabel(""); extra.setStyleSheet("font-size: 11px; color: #55b572;")
            cell.addWidget(row_w); cell.addWidget(extra)
            self.extra_map[fn] = extra

        elif is_split:
            row_w = QWidget(); h = QHBoxLayout(row_w); h.setContentsMargins(0,0,0,0); h.setSpacing(2)
            if fn == 'exec_mode':
                hi_w = QLineEdit(); hi_w.setValidator(QIntValidator(-1, 127)); hi_w.setFixedWidth(48)
                lo_w = QComboBox(); lo_w.addItems(["启用", "禁用"]); lo_w.setFixedWidth(55)
                h.addWidget(QLabel("距离")); h.addWidget(hi_w)
                h.addWidget(QLabel("范围")); h.addWidget(lo_w)
            else:
                hi_w = QLineEdit(); hi_w.setValidator(QIntValidator(0, 127)); hi_w.setFixedWidth(48)
                lo_w = QComboBox(); lo_w.addItems(["启用", "禁用"]); lo_w.setFixedWidth(55)
                h.addWidget(QLabel("面积")); h.addWidget(hi_w)
                h.addWidget(QLabel("扩散")); h.addWidget(lo_w)
            h.addStretch()
            self.split_map[fn] = (hi_w, lo_w)
            extra = QLabel(""); extra.setStyleSheet("font-size: 11px; color: #55b572;")
            cell.addWidget(row_w); cell.addWidget(extra)
            self.extra_map[fn] = extra

        elif is_filter:
            row_w = QWidget(); h = QHBoxLayout(row_w); h.setContentsMargins(0,0,0,0); h.setSpacing(2)
            hi_w = QComboBox(); hi_w.addItems(["全部", "仅角色", "仅空地"])
            lo_w = QComboBox(); lo_w.addItems(["对立阵营", "同阵营", "任意阵营"])
            h.addWidget(QLabel("格子")); h.addWidget(hi_w)
            h.addWidget(QLabel("阵营")); h.addWidget(lo_w); h.addStretch()
            self.split_map[fn] = (hi_w, lo_w)
            extra = QLabel(""); extra.setStyleSheet("font-size: 11px; color: #55b572;")
            cell.addWidget(row_w); cell.addWidget(extra)
            self.extra_map[fn] = extra

        elif is_mask:
            row_w = QWidget(); h = QHBoxLayout(row_w); h.setContentsMargins(0,0,0,0); h.setSpacing(4)
            inf = fn.startswith('inflict')
            btn = QPushButton("选择导致状态…" if inf else "选择解除状态…")
            hidden = QLineEdit(); hidden.hide()
            h.addWidget(btn); h.addStretch()
            self.widget_map[fn] = hidden
            status_frame = QWidget()
            self.extra_map[fn] = status_frame
            btn.clicked.connect(lambda checked, f=fn: self._pick_status(f))
            cell.addWidget(row_w); cell.addWidget(status_frame)

        else:
            edit = QLineEdit()
            edit.setValidator(QIntValidator(-32768, 32767))
            if is_unused: edit.setEnabled(False)
            self.widget_map[fn] = edit
            cell.addWidget(edit)
            if not is_unused:
                extra = QLabel(""); extra.setStyleSheet("font-size: 11px; color: #8a96b3;")
                cell.addWidget(extra); self.extra_map[fn] = extra

        grid.addLayout(cell, row, col)

    # ----------- 窗口控制 -----------

    def _center_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _set_edit_enabled(self, en):
        self.edit_layout.parentWidget().parentWidget().setEnabled(en)

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存", "有未保存的修改, 确定退出?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: event.ignore(); return
        event.accept()

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        ko = os.path.join(d, "TKKon.dat"); tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(ko):
            QMessageBox.warning(self, "文件缺失", "未找到 TKKon.dat"); return
        self.kon_path = ko; self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.kon_path: return
        self.status_label.setText("加载中…"); QApplication.processEvents()
        if self.tkt_path: self.tkt = load_tkt(self.tkt_path)
        name_csv = os.path.join(os.path.dirname(__file__), 'tkkon_names.csv')
        self.names = load_tkkon_names(name_csv)
        try:
            self.records = load_kon(self.kon_path); self._dirty = False
            nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
            self.status_label.setText(f"{len(self.records)} 条 | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _update_paths(self):
        cg = "color: #55b572;" if self.is_dark_theme else "color: #178a39;"
        cr = "color: #e27d60;" if self.is_dark_theme else "color: #c93b16;"
        for lb, p in [(self.lbl_kon, self.kon_path), (self.lbl_tkt, self.tkt_path)]:
            key = "TKKon.dat" if lb is self.lbl_kon else "TKT.dat"
            if not p: lb.setText(f"{key}: 未加载"); lb.setStyleSheet(cr)
            elif not os.path.exists(p): lb.setText(f"{key}: (不存在) {p}"); lb.setStyleSheet(cr)
            else: lb.setText(f"{key}: {p}"); lb.setStyleSheet(cg)

    # ----------- 筛选/表格 -----------

    def _apply_filter(self):
        q = self.search_input.text().strip().lower()
        show_empty = self.chk_show_empty.isChecked()
        self.filtered_indices = []
        for rec in self.records:
            if not show_empty:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
            if q:
                nm = kon_record_name(rec, self.tkt, self.names)
                search_text = f"{rec['index']} {rec['tkact_id']} {rec['exec_mode']} {nm} " \
                              f"{' '.join(str(rec[fn]) for fn,_,_,_ in KON_FIELDS)}".lower()
                if q not in search_text: continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        msg = f"显示 {len(self.filtered_indices)}/{KON_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_label.setText(msg)

    def _clear_filter(self):
        self.search_input.clear(); self._apply_filter()

    def _refresh_table(self):
        self.table.setSortingEnabled(False); self.table.blockSignals(True)
        self.table.setRowCount(0)

        for row, idx in enumerate(self.filtered_indices):
            r = self.records[idx]
            has_data = any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS)

            # 颜色标记 (对齐原始 kon_editor.py: 有数据=绿, 空=灰, tkact_id=-1=蓝)
            if r['tkact_id'] == -1:
                color = QColor("#2266CC")
            elif has_data:
                color = QColor("#228B22") if self.is_dark_theme else QColor("#1a7a1a")
            else:
                color = QColor("#AAAAAA") if self.is_dark_theme else QColor("#999999")

            nm = kon_record_name(r, self.tkt, self.names)

            em = r['exec_mode'] & 0xFFFF; em_hi = (em >> 8) & 0xFF
            if em_hi >= 128: dist_str = "自身"
            elif em_hi == 0: dist_str = "单格"
            else: dist_str = f"{em_hi}格"

            tp = r['target_param'] & 0xFFFF; tp_hi = (tp >> 8) & 0xFF
            if tp_hi == 255: area_str = "全场"
            elif tp_hi == 254: area_str = "排除自身"
            elif tp_hi > 0: area_str = f"{tp_hi}格"
            else: area_str = "单体"

            db = r['hp_damage']
            if db == -1: dmg_str = "攻击力"
            elif db == 0: dmg_str = "-"
            elif 1001 <= db <= 1999: dmg_str = f"{db-1000}%"
            elif 2001 <= db <= 2999: dmg_str = f"攻+{db-2000}"
            elif db >= 3001: dmg_str = f"攻×{100+db-3000}%"
            else: dmg_str = str(db)

            tf_val = r['target_filter']; tf_lo = tf_val & 0xFF; tf_hi = (tf_val >> 8) & 0xFF
            faction_map = {0: "敌", 1: "友", 2: "任意"}
            target_map = {0: "", 1: "仅人", 2: "仅地"}
            tf_str = f"{faction_map.get(tf_lo, '?')}{target_map.get(tf_hi, '')}"

            ef = r['exec_flags'] & 0xFF; ef_str = "物理" if (ef & 4) else "法术"

            vals = [str(r['index']), str(r['tkact_id']), dist_str,
                    nm if nm else f"(空-#{idx})", area_str, dmg_str, tf_str, ef_str]
            sort_keys = [r['index'], r['tkact_id'], (em >> 8) & 0xFF,
                         None, (tp >> 8) & 0xFF, r['hp_damage'],
                         r['target_filter'], r['exec_flags'] & 0xFF]

            self.table.insertRow(row)
            for col, v in enumerate(vals):
                item = NumericTableItem(v); item.setData(Qt.UserRole, sort_keys[col])
                item.setForeground(color)
                if col in (0, 1): item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True); self.table.blockSignals(False)

    # ----------- 编辑 -----------

    def _on_table_select(self):
        sel = self.table.selectedItems()
        if not sel: return
        idx = int(self.table.item(sel[0].row(), 0).text())
        self._editing_idx = idx
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        nm = kon_record_name(rec, self.tkt, self.names)
        cid = rec.get('tkact_id', 0)
        em = rec.get('exec_mode', 0); tp = rec.get('target_param', 0)

        # Inspector 标题
        em_text = describe_exec_mode(em) if em != 0 else ""
        tp_text = describe_target_param(tp) if tp != 0 else ""
        detail = "  |  ".join(filter(None, [em_text, tp_text]))
        self.lbl_inspector_title.setText(
            f"◆ {nm}  (Index #{rec['index']} / AnimID={cid})"
            + (f"  [{detail}]" if detail else "")
        )

        # 预览面板
        self.preview_name.setText(nm if nm else "空槽")
        info_parts = []
        em_desc = describe_exec_mode(em)
        if em_desc and em_desc != "单格": info_parts.append(f"攻击={em_desc}")
        tp_desc = describe_target_param(tp)
        if tp_desc and tp_desc != "无扩散(单体)": info_parts.append(f"效果={tp_desc}")
        tf_val = rec.get('target_filter', 0)
        if tf_val: info_parts.append(describe_target_filter(tf_val))
        db = rec.get('hp_damage', 0)
        if db: info_parts.append(f"伤害={describe_hp_damage(db)}")
        mpd = rec.get('mp_damage', 0)
        if mpd: info_parts.append(f"内伤={describe_resource_val(mpd, '内力伤害')}")
        hr = rec.get('hp_restore', 0)
        if hr: info_parts.append(f"回复={describe_resource_val(hr, '生命回复')}")
        mr = rec.get('mp_restore', 0)
        if mr: info_parts.append(f"回内={describe_resource_val(mr, '内力回复')}")
        ef_val = rec.get('exec_flags', 0)
        if ef_val: info_parts.append(describe_exec_flags(ef_val))
        self.preview_desc.setText(" | ".join(info_parts) if info_parts else "(空动作)")

        # 类型元数据
        ef = rec.get('exec_flags', 0) & 0xFF
        if ef & 4: type_str = "物理攻击"
        elif ef & 2: type_str = "物品使用"
        elif ef & 1: type_str = "Buff/自身"
        else: type_str = "法术攻击"
        timing = rec.get('timing_mod', 0)
        self.preview_type.setText(
            f"【{type_str}】 | 动画ID={cid} | 命中+{rec.get('accuracy', 0)} | 附加伤={rec.get('extra_damage', 0)}"
            + (f" | 时序{timing:+d}" if timing else "")
        )
        self.preview_sub.setText("")

        # 填充字段
        _dmg_desc = {
            'hp_damage': describe_hp_damage,
            'mp_damage': lambda v: describe_resource_val(v, '内力伤害'),
            'hp_restore': lambda v: describe_resource_val(v, '生命回复'),
            'mp_restore': lambda v: describe_resource_val(v, '内力回复'),
        }
        _split_desc = {
            'exec_mode': describe_exec_mode,
            'target_param': describe_target_param,
            'target_filter': describe_target_filter,
        }

        for fn, fo, fl, _ in KON_FIELDS:
            val = rec.get(fn, 0)
            w = self.widget_map.get(fn)
            if w: w.setText(str(val))

            if fn in self.extra_map:
                if fn in _dmg_desc:
                    self.extra_map[fn].setText(_dmg_desc[fn](int(val) if val else 0))
                elif fn in _split_desc:
                    self.extra_map[fn].setText(_split_desc[fn](val))
                elif fn == 'exec_flags':
                    self.extra_map[fn].setText(describe_exec_flags(val))
                elif 'status' in fn:
                    self._update_status_label(fn, int(val) if val else 0)
                else:
                    self.extra_map[fn].setText("")

        # 拆分字段
        for fn in ('exec_mode', 'target_param', 'target_filter'):
            val = rec.get(fn, 0)
            hi = (val >> 8) & 0xFF; lo = val & 0xFF
            if fn not in self.split_map: continue
            w1, w2 = self.split_map[fn]
            if fn == 'exec_mode':
                if hi >= 128: hi -= 256
                w1.setText(str(hi)); w2.setCurrentIndex(0 if lo == 0 else 1)
            elif fn == 'target_param':
                w1.setText(str(hi)); w2.setCurrentIndex(0 if lo == 0 else 1)
            elif fn == 'target_filter':
                w1.setCurrentIndex(hi if hi < 3 else 0); w2.setCurrentIndex(lo if lo < 3 else 0)

        # exec_flags 复选框
        if 'exec_flags' in self.split_map:
            lo = rec.get('exec_flags', 0) & 0xFF
            cb0, cb1, cb2 = self.split_map['exec_flags']
            cb0.setChecked(bool(lo & 1)); cb1.setChecked(bool(lo & 2)); cb2.setChecked(bool(lo & 4))

    def _pick_status(self, fn):
        cur = int(self.widget_map[fn].text() or 0) & 0xFFFF
        base = 0 if fn.endswith('_lo') else 16
        inf = fn.startswith('inflict')
        title = "选择导致状态 (位掩码)" if inf else "选择解除状态 (位掩码)"
        dlg = StatusMaskDialog(title, cur, base, self)
        if dlg.exec() == QDialog.Accepted:
            new_mask = dlg.get_mask()
            self.widget_map[fn].setText(str(new_mask))
            self._update_status_label(fn, new_mask & 0xFFFF)

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_lo') else 16
        inf = fn.startswith('inflict')
        color = '#CC3333' if inf else '#3366cc'
        frame = self.extra_map.get(fn)
        if not frame: return
        # 清除旧内容
        for c in frame.findChildren(QWidget):
            c.setParent(None)
        frame_layout = frame.layout()
        if not frame_layout:
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(0,0,0,0); frame_layout.setSpacing(1)
        sel = [f"{base+i}.{STATUS_NAMES[base+i]}" for i in range(16)
               if (mask & (1 << i)) and base + i < len(STATUS_NAMES)]
        if sel:
            COLS = 3
            for si, nm in enumerate(sel):
                r, c = divmod(si, COLS)
                # 在 grid 中放入 label
                while frame_layout.count() <= r:
                    row_w = QWidget(); row_lay = QHBoxLayout(row_w)
                    row_lay.setContentsMargins(0,0,0,0); row_lay.setSpacing(6)
                    frame_layout.addWidget(row_w)
                row_w = frame_layout.itemAt(r).widget()
                row_lay = row_w.layout()
                lbl = QLabel(nm)
                lbl.setStyleSheet(f"font-size: 11px; color: {color};")
                row_lay.addWidget(lbl)
        else:
            lbl = QLabel("(无)")
            lbl.setStyleSheet(f"font-size: 11px; color: {color};")
            frame_layout.addWidget(lbl)

    def _apply_edit(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]

        # 拆分字段
        for fn in ('exec_mode', 'target_param', 'target_filter'):
            if fn in self.split_map:
                w1, w2 = self.split_map[fn]
                try:
                    if fn == 'target_filter':
                        hi, lo = w1.currentIndex(), w2.currentIndex()
                    else:
                        hi = int(w1.text()) & 0xFF
                        lo = 0 if w2.currentIndex() == 0 else 1
                    combined = (hi << 8) | lo
                    if combined >= 0x8000: combined -= 0x10000
                    rec[fn] = combined
                except ValueError: pass

        # exec_flags
        if 'exec_flags' in self.split_map:
            cb0, cb1, cb2 = self.split_map['exec_flags']
            lo = (1 if cb0.isChecked() else 0) | (2 if cb1.isChecked() else 0) | (4 if cb2.isChecked() else 0)
            rec['exec_flags'] = lo

        # 普通字段
        for fn, _, _, _ in KON_FIELDS:
            if fn.startswith('unused') or fn in self.split_map: continue
            w = self.widget_map.get(fn)
            if not w: continue
            try:
                v = int(w.text() or 0)
                if v > 32767: v = 32767
                if v < -32768: v = -32768
                rec[fn] = v
            except ValueError: rec[fn] = 0

        self._dirty = True; self._apply_filter()
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == rec['index']:
                self.table.selectRow(row); self.table.scrollToItem(self.table.item(row, 0)); break
        self.status_label.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if self._editing_idx >= 0:
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 编辑操作 -----------

    def _new_record(self):
        if not self.records: QMessageBox.information(self, "提示", "请先加载数据"); return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                rec['exec_mode'] = 0; rec['target_param'] = 0
                rec['tkact_id'] = rec['index']
                rec['hp_damage'] = -1; rec['exec_flags'] = 4
                self._dirty = True; self._apply_filter()
                for row in range(self.table.rowCount()):
                    if int(self.table.item(row, 0).text()) == rec['index']:
                        self.table.selectRow(row); break
                self._populate_edit(rec)
                self.status_label.setText(f"已创建新条目 → 槽位 #{rec['index']}"); return
        QMessageBox.warning(self, "槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _copy_record(self):
        if self._editing_idx < 0: return
        src = self.records[self._editing_idx]
        if all(src[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            QMessageBox.information(self, "提示", "当前记录为空"); return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                idx_bak = rec['index']
                for k, v in src.items():
                    if k != 'index': rec[k] = v
                rec['index'] = idx_bak
                self._dirty = True; self._apply_filter()
                for row in range(self.table.rowCount()):
                    if int(self.table.item(row, 0).text()) == rec['index']:
                        self.table.selectRow(row); break
                self._populate_edit(rec)
                self.status_label.setText(f"已复制 #{src['index']} → #{rec['index']}"); return
        QMessageBox.warning(self, "槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _clear_current(self):
        if self._editing_idx < 0: return
        rec = self.records[self._editing_idx]
        if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            QMessageBox.information(self, "提示", "当前记录已经为空"); return
        if QMessageBox.question(self, "确认清空", f"确定清空记录 #{rec['index']}?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        for fn, _, _, _ in KON_FIELDS: rec[fn] = 0
        self._dirty = True; self._apply_filter(); self._populate_edit(rec)
        self.status_label.setText(f"已清空记录 #{rec['index']}")

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.kon_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        if QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.kon_path}\n\n原文件将被覆盖 (生成 .bak).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        try:
            with open(self.kon_path, 'rb') as s:
                with open(self.kon_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_label.setText("正在保存…"); QApplication.processEvents()
            save_kon(self.kon_path, self.records); self._dirty = False
            self.status_label.setText(f"已保存 → {self.kon_path}")
            QMessageBox.information(self, "保存成功", f"已保存\n备份: {self.kon_path}.bak")
        except Exception as e: QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "", "CSV 文件 (*.csv)")
        if not p: return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['记录索引', '动画ID', '名称'] + [fn for fn, _, _, _ in KON_FIELDS]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
                row = [str(rec['index']), str(rec.get('tkact_id', '')),
                       kon_record_name(rec, self.tkt, self.names)]
                row += [str(rec[fn]) for fn, _, _, _ in KON_FIELDS]
                f.write(','.join(row) + '\n')
        self.status_label.setText(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        FieldRefDialog(self).exec()

    def _show_about(self):
        QMessageBox.about(self, "关于",
            "TKKon.dat 可视化编辑器 v3.2 (PySide6)\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "Godot 4.6 风格 UI · FakeInputBox 体系\n\n"
            "逆向来源:\n"
            "  sub_43D53C/43D8B0/43E980/4458B0/4434BC/4173F8"
        )

# ============================================================
# 入口
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    editor = KonEditor(); editor.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
