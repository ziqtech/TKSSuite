#!/usr/bin/env python3
"""
WarData.dat 可视化编辑器 v2.0 (PySide6 — Godot 4.6 风格)
=========================================================
逆向依据:
  - sub_42FDF8: WarData.dat 加载 (498字节/条, 219条, fopen/fread/fseek, 无LZSS)
  - sub_42FE70: WarWay.dat 加载 (1024字节/条, 100条, 32x32有符号字节网格)
  - sub_451600 + grp_editor: WSC.GRP 背景图加载 (RGB565 LZSS Frame A)
  - sub_4307CC: 战场初始化 — 解析 byte_9537D8 全部字段
  - sub_431428: 场景布置 — treasure放置/区域系统
  - sub_434D7C/sub_434188: 战场渲染 — 32x32网格遍历+地格特效
  - sub_4355C4: 网格更新循环 — -1永久障碍/0可通行/1-5特殊区域

WarData.dat 格式 (每条498字节, 219条, flat binary — sub_42FDF8):
  字段通过 TKS.exe反编译 + War.dll官方编辑器(战场编辑器v2.0) 双重验证:

  [0]     byte    flags       — sub_4307CC:200 &4=随机敌军; sub_43CA64:102 &2=失败条件
  [1]     byte    (reserved)  — 反编译未引用; 原误读为battle_id高字节, sub_436BD4:30 word_4EB728=a1实为函数参数
  [2-7]   byte[6] must_chars  — sub_4307CC:51 v20=&unk_9537DA (+1编码; 0/255=空)
  [8-29]  byte[22] (reserved) — 反编译未引用
  [30-31] uint16  name_id     — sub_43A8D8:39 word_9537F6→sub_4067E8(TKT)
  [32-33] uint16  map_id      — sub_42FE70:16; War.dll标签"地图编号"
  [34-69] uint16[18] enemy_id — sub_4307CC:219; War.dll标签"人物编号" (WarPC索引)
  [70-87] byte[18]  enemy_lv  — sub_4307CC:260; sub_444FD4:79; War.dll标签"等级范围"
  [88-105] byte[18] enemy_grp — sub_4307CC:217; sub_444FD4:26; 属性加成倍率(sub_4302D8:53); 0=普通士兵(可增援), >=1=将领(HP×N倍加成)
  [106-141] byte[36] enemy_lv_range — sub_4307CC:227; sub_444FD4:48; level params(18 pairs a3,a4)
                                18对X,Y(int8), X=106+2*i, Y=107+2*i
  [142-177] byte[36] enemy_xy — sub_431428:94-98 grid coords(18 pairs int8 X,Y); War.dll"敌人朝向"
  [178-189] byte[12] ally_xy  — sub_431428:74 unk_95388A; 6对X,Y(int8), 同enemy_xy格式
  [190-207] byte[18] enemy_del — sub_4307CC:242 v9[102]; sub_444FD4:61; War.dll标签"属性加成"
  [208-213] byte[6] ally_facing — War.dll标签"我方朝向"; 6个友军朝向值(byte)
  [214-269] byte[56] trap_xy  — sub_431428:204 (char*)v43-172/-171; 28组陷阱/宝物坐标(int8对, 共享)
  [270-325] byte[56] trap_pwr — sub_431428:296 (char*)v45-116/-115; 28组陷阱威力(min,max) byte
  [326-345] uint16[10] trea_sub — sub_431428:202; 10组宝物物品ID (TKItem, sub_431428:303)
  [346-385] uint16[20] trea_quant — sub_434510:36-37; 10对宝物数量(min,max) uint16
  [386-441] uint16[28] trap_type — sub_431428:199,295 unk_95395A; 28组陷阱类型 (1=山崩 2=泥沼 3=漩渦 4=火焰 5=滾木 6=瘴氣)
  ★ 已验证: offset 386-441 全为陷阱类型(1-6), 无TKItem ID; offset 270-325 全为陷阱威力(1-4)
    真正的宝物数据在 trea_sub(326-345) 和 trea_quant(346-385)
  [442-477] uint16[18] enemy_flg — sub_4307CC:263 v5[204]; sub_444FD4:81 word_953992
                                  bit0=精英, bit1=特殊, bit13/14=阵营标记
  [478]    byte    lv_spread_lo — sub_430578:17 byte_9539B6; 等级浮动下限, |hi-lo|→clamp(2,5)决定浮动幅度
  [479]    byte    (reserved)   — 反编译未引用; 全219条数据为零
  [480]    byte    lv_spread_hi — sub_430578:18 byte_9539B8; 等级浮动上限, 与lo的差值决定spread
  [481]    byte    (reserved)   — 反编译未引用; 全219条数据为零
  [482-483] uint16 turn_limit  — sub_43CA64:29 word_9539BA (>0时回合限制)
  [484-497] byte[14] (reserved) — 反编译未引用; 全219条数据为零

War.dll 官方编辑器(战场编辑器v2.0)证据:
  - sub_401DE5: 读取→UI填充, sub_4024B4: UI→保存回写
  - 编辑控件: a1+140(人物编号) a1+212(等级范围) a1+284(人物归属)
              a1+356(敌人位置) a1+428(敌人朝向) a1+500(我方位置)
              a1+572(属性加成) a1+644(我方朝向) a1+716(物品编号)
              a1+788(物品数量) a1+860(地图编号)
  - 记录访问: *(a3+880) + 498*(a2+1) — 1-based索引, 跳过文件首498字节
  - 69条战斗名称硬编码于DLL字符串表(0x66A8起)

WarWay.dat 格式 (每条1024字节, 共100条, 32x32有符号字节网格):
  值语义 (sub_4355C4 + sub_431428):
    -1 (0xFF): 障碍物/不可通行 — sub_4355C4更新循环跳过, 永久不变
     0 (0x00): 普通可通行地面 — 默认值, 不触发特效
     1-5:      特殊区域/放置区 — sub_431428:106取值分组, sub_434D7C:60触发地格特效

用法: python wardata_editor_v2.py
"""

import struct, os, sys, random
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar, QTabWidget,
    QSpinBox, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsTextItem,
    QSizePolicy,
)
from PySide6.QtGui import (
    QColor, QFont, QIcon, QIntValidator, QBrush, QPen, QPolygonF,
    QPainter, QPixmap, QImage, QAction, QKeySequence,
)
from PySide6.QtCore import Qt, QPointF, QRectF

HAS_PIL = False
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    pass

# ── 常量 ──────────────────────────────────────────────
WAR_REC_SIZE = 498
WAR_REC_COUNT = 219
WSC_ENTRIES = 84

# ═══════════════════════════════════════════════════════════
# LZSS 解压 (sub_452B14, 兼容 grp_editor 格式)
# ═══════════════════════════════════════════════════════════

RING_SIZE, RING_INIT, RING_INIT_VAL = 4096, 4078, 0x20

def lzss_decompress(data: bytes, target_size: int) -> bytes:
    ring = bytearray([RING_INIT_VAL] * RING_SIZE)
    ring_pos, pos = RING_INIT, 0
    out = bytearray()
    while pos < len(data) and len(out) < target_size:
        flag = data[pos]; pos += 1
        for bit in range(8):
            if pos >= len(data) or len(out) >= target_size:
                break
            if flag & (1 << bit):
                b = data[pos]; pos += 1; out.append(b)
                ring[ring_pos % RING_SIZE] = b; ring_pos += 1
            else:
                if pos + 2 > len(data): break
                b1, b2 = data[pos], data[pos + 1]; pos += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3
                for k in range(length):
                    b = ring[(offset + k) % RING_SIZE]; out.append(b)
                    ring[ring_pos % RING_SIZE] = b; ring_pos += 1
    return bytes(out[:target_size])

# RGB565 -> RGBA 查找表
_RGB565_LUT = bytearray(65536 * 3)
for _v in range(65536):
    r5 = (_v >> 11) & 0x1F; g6 = (_v >> 5) & 0x3F; b5 = _v & 0x1F
    _RGB565_LUT[_v * 3] = (r5 << 3) | (r5 >> 2)
    _RGB565_LUT[_v * 3 + 1] = (g6 << 2) | (g6 >> 4)
    _RGB565_LUT[_v * 3 + 2] = (b5 << 3) | (b5 >> 2)

def rgb565_to_rgba(raw: bytes, w: int, h: int) -> bytes:
    total = w * h; rgba = bytearray(total * 4)
    for i in range(min(total, len(raw) // 2)):
        lo = raw[i * 2]; hi = raw[i * 2 + 1]
        off3 = (lo | (hi << 8)) * 3; off4 = i * 4
        rgba[off4:off4 + 3] = _RGB565_LUT[off3:off3 + 3]
        rgba[off4 + 3] = 255
    return bytes(rgba)

def rle_bp_decompress(data: bytes, target_size: int) -> bytes:
    out = bytearray(); pos = 0
    while pos + 1 < len(data) and len(out) < target_size:
        count = data[pos]; value = data[pos + 1]; pos += 2
        out.extend(bytes([value] * count))
    return bytes(out[:target_size])

def rle_bp_probe(data: bytes, expected_size: int) -> bool:
    total, pos = 0, 0
    while pos + 1 < len(data):
        total += data[pos]; pos += 2
    return total == expected_size


# ═══════════════════════════════════════════════════════════
# WSC.GRP 战场背景图加载
# ═══════════════════════════════════════════════════════════

def load_wsc_idx(idx_path: str) -> list:
    data = Path(idx_path).read_bytes()
    count = len(data) // 4
    return [struct.unpack_from('<I', data, i * 4)[0] for i in range(count)]

def load_wsc_entry(grp_path: str, idx_offsets: list, entry_index: int):
    if not HAS_PIL:
        return None
    if entry_index < 0 or entry_index >= len(idx_offsets) - 1:
        return None
    data = Path(grp_path).read_bytes()
    offset = idx_offsets[entry_index]
    end_offset = idx_offsets[entry_index + 1]
    chunk = data[offset:end_offset]
    if len(chunk) < 12:
        return None
    w, h, ca, cb = struct.unpack_from('<HHII', chunk, 0)
    if w == 0 or h == 0 or w > 4096 or h > 4096:
        return None
    fa_off = 12
    if fa_off + 4 > len(chunk):
        return None
    uncomp_sz = struct.unpack_from('<I', chunk, fa_off)[0]
    lzss_data = chunk[fa_off + 4 : fa_off + ca]
    raw_a = lzss_decompress(lzss_data, min(uncomp_sz, w * h * 2))
    if len(raw_a) < w * h * 2:
        raw_a = raw_a + b'\x00' * (w * h * 2 - len(raw_a))
    rgba = rgb565_to_rgba(raw_a, w, h)
    return (w, h, rgba)


# ═══════════════════════════════════════════════════════════
# WarData.dat 加载/保存 (sub_42FDF8)
# ═══════════════════════════════════════════════════════════

def load_warway(filepath: str, map_id: int) -> bytes:
    if not filepath or not os.path.exists(filepath):
        return None
    data = Path(filepath).read_bytes()
    off = map_id * 1024
    if off + 1024 > len(data):
        return None
    return data[off:off + 1024]


def load_wardata(filepath: str) -> list:
    data = Path(filepath).read_bytes()
    count = len(data) // WAR_REC_SIZE
    records = []
    for i in range(count):
        off = i * WAR_REC_SIZE
        chunk = data[off:off + WAR_REC_SIZE]
        rec = {'index': i}
        rec['battle_id'] = i
        rec['flags'] = chunk[0]
        rec['must_chars'] = list(chunk[2:8])
        rec['battle_name_id'] = struct.unpack_from('<H', chunk, 30)[0]
        rec['map_id'] = struct.unpack_from('<H', chunk, 32)[0]
        rec['enemy_ids'] = list(struct.unpack_from('<' + 'H' * 18, chunk, 34))
        rec['enemy_lv'] = list(chunk[70:88])
        rec['enemy_power'] = list(chunk[88:106])
        rec['enemy_lv_range'] = list(struct.unpack_from('<' + 'b' * 36, chunk, 106))
        rec['enemy_xy'] = list(struct.unpack_from('<' + 'b' * 36, chunk, 142))
        rec['ally_xy'] = list(struct.unpack_from('<' + 'b' * 12, chunk, 178))
        rec['enemy_delay'] = list(chunk[190:208])
        rec['ally_facing'] = list(chunk[208:214])
        rec['trap_xy'] = list(struct.unpack_from('<' + 'b' * 56, chunk, 214))
        rec['trap_pwr'] = list(chunk[270:326])
        rec['trea_sub'] = list(struct.unpack_from('<' + 'H' * 10, chunk, 326))
        rec['trea_quant'] = list(struct.unpack_from('<' + 'H' * 20, chunk, 346))
        rec['trap_type'] = list(struct.unpack_from('<' + 'H' * 28, chunk, 386))
        rec['enemy_flags'] = list(struct.unpack_from('<' + 'H' * 18, chunk, 442))
        rec['lv_spread_lo'] = chunk[478]
        rec['lv_spread_hi'] = chunk[480]
        rec['battle_turn_limit'] = struct.unpack_from('<H', chunk, 482)[0]
        rec['_raw'] = chunk
        records.append(rec)
    return records


def save_wardata(filepath: str, records: list):
    buf = bytearray(len(records) * WAR_REC_SIZE)
    for rec in records:
        i = rec['index']
        off = i * WAR_REC_SIZE
        chunk = bytearray(rec['_raw'])
        chunk[0] = rec['flags'] & 0xFF
        for j in range(6):
            chunk[2 + j] = rec['must_chars'][j] & 0xFF
        struct.pack_into('<H', chunk, 30, rec['battle_name_id'])
        struct.pack_into('<H', chunk, 32, rec['map_id'])
        for j in range(18):
            struct.pack_into('<H', chunk, 34 + j * 2, rec['enemy_ids'][j])
            chunk[70 + j] = rec['enemy_lv'][j] & 0xFF
            chunk[88 + j] = rec['enemy_power'][j] & 0xFF
        for j in range(36):
            struct.pack_into('<b', chunk, 106 + j, rec['enemy_lv_range'][j])
        for j in range(36):
            struct.pack_into('<b', chunk, 142 + j, rec['enemy_xy'][j])
        for j in range(12):
            struct.pack_into('<b', chunk, 178 + j, rec['ally_xy'][j])
        for j in range(18):
            chunk[190 + j] = rec['enemy_delay'][j] & 0xFF
        for j in range(6):
            chunk[208 + j] = rec['ally_facing'][j] & 0xFF
        for j in range(56):
            struct.pack_into('<b', chunk, 214 + j, rec['trap_xy'][j])
        for j in range(56):
            chunk[270 + j] = rec['trap_pwr'][j] & 0xFF
        for j in range(10):
            struct.pack_into('<H', chunk, 326 + j * 2, rec['trea_sub'][j])
        for j in range(20):
            struct.pack_into('<H', chunk, 346 + j * 2, rec['trea_quant'][j])
        for j in range(28):
            struct.pack_into('<H', chunk, 386 + j * 2, rec['trap_type'][j])
        for j in range(18):
            struct.pack_into('<H', chunk, 442 + j * 2, rec['enemy_flags'][j])
        chunk[478] = rec['lv_spread_lo'] & 0xFF
        chunk[480] = rec['lv_spread_hi'] & 0xFF
        struct.pack_into('<H', chunk, 482, rec['battle_turn_limit'])
        buf[off:off + WAR_REC_SIZE] = chunk
    if os.path.exists(filepath):
        bak = filepath + '.bak'
        if not os.path.exists(bak):
            Path(filepath).rename(bak)
    Path(filepath).write_bytes(bytes(buf))


# ═══════════════════════════════════════════════════════════
# TKT 文本加载 (sub_4067E8)
# ═══════════════════════════════════════════════════════════

def load_tkt(tkt_path: str) -> dict:
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz = cnt * 4; ofsz = cnt * 4; lookup = {}
    SKIP = set(range(0, 10))
    for i in range(cnt):
        eid = struct.unpack_from('<i', dec, i * 4)[0]
        if eid in SKIP:
            continue
        off = struct.unpack_from('<I', dec, idsz + i * 4)[0]
        ao = idsz + ofsz + off
        if ao < len(dec):
            end = ao
            while end < len(dec) and dec[end] != 0:
                end += 1
            txt = dec[ao:end].replace(b'\x1e', b'\n')
            try:
                s = txt.decode('big5', errors='replace')
            except:
                s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.split('\n')[0].strip()
    return lookup


def load_warpc_names(warpc_path: str, tkt: dict) -> dict:
    if not warpc_path or not os.path.exists(warpc_path):
        return {}
    with open(warpc_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    bs = struct.unpack_from('<I', raw, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(raw): break
            flags = raw[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(raw): break
            b = raw[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(raw): break
            b1, b2 = raw[pos], raw[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    dec = bytes(out[:ts])
    WARPC_REC = 1054
    count = len(dec) // WARPC_REC
    names = {}
    for i in range(count):
        off = i * WARPC_REC
        name_id = struct.unpack_from('<h', dec, off)[0]
        if name_id and name_id in tkt:
            names[i] = tkt[name_id]
        elif name_id:
            names[i] = f"PC#{i}"
        else:
            names[i] = f"(空#{i})"
    return names


def load_tkitem_names(tkitem_path: str, tkt: dict) -> dict:
    if not tkitem_path or not os.path.exists(tkitem_path):
        return ({}, {})
    with open(tkitem_path, 'rb') as f:
        raw = f.read()
    ts = struct.unpack_from('<I', raw, 0)[0]
    bs = struct.unpack_from('<I', raw, 4)[0]
    w = bytearray([0x20] * 4096); wp = 4078
    out = bytearray(); flags = 0; pos = 12; bc = 4
    while bc < bs:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(raw): break
            flags = raw[pos] | 0xFF00; pos += 1; bc += 1
        if flags & 1:
            if pos >= len(raw): break
            b = raw[pos]; pos += 1; bc += 1
            out.append(b); w[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            if pos + 1 >= len(raw): break
            b1, b2 = raw[pos], raw[pos + 1]; pos += 2; bc += 2
            ro = ((b2 & 0xF0) << 4) | b1; rl = (b2 & 0x0F) + 2
            for j in range(rl + 1):
                b = w[(j + ro) & 0xFFF]; out.append(b)
                w[wp] = b; wp = (wp + 1) & 0xFFF
    dec = bytes(out[:ts])
    ITEM_REC = 64
    count = len(dec) // ITEM_REC
    by_index = {}
    by_item_id = {}
    for i in range(count):
        off = i * ITEM_REC
        item_id = struct.unpack_from('<h', dec, off)[0]
        name_id = struct.unpack_from('<h', dec, off + 4)[0]
        if item_id <= 1:
            continue
        if name_id and name_id in tkt:
            item_name = tkt[name_id]
        elif name_id:
            item_name = f"Item#{item_id}"
        else:
            continue
        by_index[i] = item_name
        by_item_id[item_id] = item_name
    return (by_index, by_item_id)


# ═══════════════════════════════════════════════════════════
# 主题加载
# ═══════════════════════════════════════════════════════════

def _load_qss(filename):
    """加载 themes/ 目录下的 QSS 文件"""
    qss_path = os.path.join(os.path.dirname(__file__), 'themes', filename)
    if os.path.exists(qss_path):
        with open(qss_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

GODOT_DARK_QSS = _load_qss('dark.qss')
GODOT_LIGHT_QSS = _load_qss('light.qss')

TRAP_NAMES_MAP = {0: '0 无', 1: '1 山崩陷阱', 2: '2 泥沼陷阱', 3: '3 漩渦陷阱',
                  4: '4 火焰陷阱', 5: '5 滾木陷阱', 6: '6 瘴氣陷阱'}
TRAP_NAMES_SHORT = {1: '山崩', 2: '泥沼', 3: '漩渦', 4: '火焰', 5: '滾木', 6: '瘴氣'}

# ═══════════════════════════════════════════════════════════
# Dock 面板组件 (对齐 warpc_editor_v2)
# ═══════════════════════════════════════════════════════════

class DockHeader(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(4)
        lbl = QLabel(title); lbl.setObjectName("DockTitle"); layout.addWidget(lbl, 1)

def make_fake_input(line_edit=None, combo=None, button=None, stretch=True):
    box = QFrame(); box.setObjectName("FakeInputBox")
    h = QHBoxLayout(box); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
    if line_edit: line_edit.setFrame(False); h.addWidget(line_edit)
    if combo: h.addWidget(combo, 1)
    if button: h.addWidget(button)
    if stretch: h.addStretch()
    return box

# ═══════════════════════════════════════════════════════════
# 主编辑器窗口
# ═══════════════════════════════════════════════════════════

class WarDataEditorV2(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WarData.dat 可视化编辑器 v2.0 - PySide6")
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)

        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        # 数据状态
        self.wardata_path = None
        self.warway_path = None
        self.wsc_grp_path = None
        self.wsc_idx_path = None
        self.tkt_path = None
        self.warpc_path = None
        self.warpc_names = {}
        self.tkitem_path = None
        self.tkitem_names = {}
        self.tkitem_names_by_id = {}
        self.records = []
        self.wsc_offsets = []
        self.tkt = {}
        self._dirty = False
        self._current_idx = -1

        # 场景预览状态
        self._wsc_cache = {}
        self._wsc_res_cache = {}
        self._preview_zoom = 0.5
        self._drag_target = None
        self._pan_start = None
        self._last_resolved_enemies = {}
        self._last_resolved_treas = {}
        self._last_resolved_allies = {}
        self._last_resolved_traps = {}
        self._last_fixed_trea_indices = set()
        self._last_fixed_enemy_slots = set()
        self._last_fixed_trap_indices = set()
        self._last_active_slots = 18
        self._last_enemy_zone_reqs = []
        self._last_trea_zone_reqs = []
        self._last_trap_zone_reqs = []

        self._build_ui()
        self._set_edit_enabled(False)
        self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        self.setStyleSheet(GODOT_DARK_QSS if self._is_dark else GODOT_LIGHT_QSS)
        self._update_paths()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _update_paths(self):
        cg = "color:#55b572;" if self._is_dark else "color:#178a39;"
        cr = "color:#e27d60;" if self._is_dark else "color:#c93b16;"
        for lb, p, key in [(self.lbl_wardata, self.wardata_path, 'WarData'),
                            (self.lbl_warway, self.warway_path, 'WarWay'),
                            (self.lbl_tkt, self.tkt_path, 'TKT')]:
            if not p:
                lb.setStyleSheet(cr); lb.setText(f"{key}: 未加载")
            elif not os.path.exists(p):
                lb.setStyleSheet(cr); lb.setText(f"{key}: (不存在){p}")
            else:
                lb.setStyleSheet(cg); lb.setText(f"{key}: {p}")
        if self.wsc_grp_path and os.path.exists(self.wsc_grp_path):
            self.lbl_wsc.setStyleSheet(cg); self.lbl_wsc.setText(f"WSC: {self.wsc_grp_path}")
        else:
            self.lbl_wsc.setStyleSheet(cr); self.lbl_wsc.setText("WSC: 未加载")
        extra_parts = []
        if self.warpc_path and os.path.exists(self.warpc_path):
            extra_parts.append(f"WarPC: {len(self.warpc_names)}人")
        if self.tkitem_path and os.path.exists(self.tkitem_path):
            extra_parts.append(f"TKItem: {len(self.tkitem_names)}件")
        if extra_parts:
            self.lbl_extra.setStyleSheet(cg); self.lbl_extra.setText(" | ".join(extra_parts))
        else:
            self.lbl_extra.setStyleSheet(cr); self.lbl_extra.setText("(WarPC/TKItem: 未加载)")

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4); main_layout.setSpacing(4)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录…\tCtrl+O", self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存\tCtrl+S", self._save)
        fm.addAction("另存为…", self._save_as)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新增战场\tCtrl+N", self._new_battle)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("删除当前记录", self._delete_record)

        hm = mb.addMenu("帮助(&H)")
        hm.addAction("字段参考 (逆向来源)", self._show_field_ref)
        hm.addAction("关于", self._show_about)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = QLineEdit(); self.search_entry.setFixedWidth(160)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("🔍 搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("🗑 清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("🔄 重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主 Splitter
        splitter = QSplitter(Qt.Horizontal); splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False); main_layout.addWidget(splitter, 1)

        # 左侧：战斗列表
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["序号", "地图", "敌军数", "宝物数", "陷阱数", "固定/随机", "参战人物", "参数"])
        self.table.setColumnWidth(0, 45); self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 50); self.table.setColumnWidth(3, 50)
        self.table.setColumnWidth(4, 50); self.table.setColumnWidth(5, 70)
        self.table.setColumnWidth(6, 180)  # 参战人物列加宽
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setColumnWidth(7, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        splitter.addWidget(self.table)

        # 右侧：编辑面板
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4); rl.setSpacing(4)
        self.tabs = QTabWidget()
        self._build_scene_tab()
        self._build_enemy_tab()
        self._build_ally_tab()
        self._build_drops_traps_tab()
        self._build_params_tab()
        self._build_allparams_tab()
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([380, 1020])
        # 切换到场景标签页时自动刷新
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 底部路径栏
        path_layout = QHBoxLayout(); path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_wardata = QLabel(); self.lbl_warway = QLabel()
        self.lbl_wsc = QLabel(); self.lbl_tkt = QLabel(); self.lbl_extra = QLabel()
        for w in [self.lbl_wardata, self.lbl_warway, self.lbl_wsc, self.lbl_tkt, self.lbl_extra]:
            path_layout.addWidget(w); path_layout.addSpacing(15)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _set_edit_enabled(self, enabled):
        self.table.setEnabled(enabled)

    # ── 名称辅助 ──
    def _char_name(self, warpc_idx):
        """WarPC角色索引 → 角色名称 (via WarPC.name_id → TKT)
        WarPC[0-34]=玩家/独特角色, WarPC[35-142]=敌军角色.
        must_chars 用 v-1 解码得到 0-34 的玩家索引。
        enemy_ids 需 +35 得到敌军索引, 调用方应使用 _enemy_name()."""
        if warpc_idx in self.warpc_names: return self.warpc_names[warpc_idx]
        return f"PC#{warpc_idx}" if warpc_idx >= 0 else "?"

    def _enemy_name(self, enemy_id):
        """敌军角色ID → 角色名称 (enemy_id + 35 = WarPC索引)"""
        return self._char_name(enemy_id + 35)

    def _battle_name(self, rec):
        """生成战斗名称 — 使用 battle_id 或 must_chars 推断"""
        bid = rec['battle_id']
        chars = [c for c in rec['must_chars'] if c > 0 and c != 255]
        if chars:
            names = []
            for c in chars[:3]:
                cid = c - 1  # +1编码解码
                names.append(self._char_name(cid))
            return f"#{bid} " + ",".join(names) if names else f"战场#{bid}"
        return f"战场#{bid}"

    def _trea_label(self, rec, i):
        """宝物槽的显示标签 (trea_sub TKItem ID)"""
        tid = rec['trea_sub'][i] if i < 10 else 0
        if tid == 10000: return "金钱"
        elif tid > 0: return self.tkitem_names_by_id.get(tid, f"Item#{tid}")[:8]
        return ""

    @staticmethod
    def _trap_type_at(rec, slot):
        """获取指定槽位的陷阱类型"""
        return rec['trap_type'][slot]

    @staticmethod
    def _trap_power_at(rec, slot):
        """获取指定槽位的陷阱威力 (min, max)"""
        off = slot * 2 if slot < 10 else 20 + (slot - 10) * 2
        return (rec['trap_pwr'][off], rec['trap_pwr'][off + 1])

    def _get_wsc_resolution(self, map_id):
        if map_id in self._wsc_res_cache: return self._wsc_res_cache[map_id]
        if not self.wsc_grp_path or not self.wsc_offsets: return None
        if map_id < 0 or map_id >= len(self.wsc_offsets) - 1: return None
        try:
            data = Path(self.wsc_grp_path).read_bytes()
            offset = self.wsc_offsets[map_id]
            if offset + 12 > len(data): return None
            w, h = struct.unpack_from('<HH', data, offset)
            if w == 0 or h == 0 or w > 4096 or h > 4096: return None
            self._wsc_res_cache[map_id] = (w, h)
            return (w, h)
        except: return None

    def _trea_detail_str(self, rec):
        fixed = random_trea = 0
        for i in range(10):
            if rec['trea_sub'][i] <= 0: continue
            tx = rec['trap_xy'][i * 2]
            if tx >= 0: fixed += 1
            else: random_trea += 1
        return f"固{fixed}/随{random_trea}" if fixed or random_trea else "-"

    # ── 列表 ──
    def _fill_tree_row(self, rec):
        enemy_count = sum(1 for eid in rec['enemy_ids'] if eid > 0)
        trea_count = sum(1 for i in range(10) if rec['trea_sub'][i] > 0)
        trap_count = sum(1 for i in range(28) if 1 <= self._trap_type_at(rec, i) <= 6)
        trea_detail = self._trea_detail_str(rec)
        mid = rec['map_id']; res = self._get_wsc_resolution(mid)
        map_info = f"{mid} ({res[0]}x{res[1]})" if res else str(mid)
        enemy_names = []; seen = set()
        for eid in rec['enemy_ids']:
            if eid > 0 and eid not in seen:
                seen.add(eid); enemy_names.append(self._enemy_name(eid))
        if enemy_names:
            names = [n[:4] for n in enemy_names[:3]]
            chars_info = ','.join(names)
            if len(enemy_names) > 3: chars_info += '等'
        else: chars_info = '-'
        flags = rec['flags']; flag_parts = []
        if flags & 2: flag_parts.append('续')
        if flags & 4: flag_parts.append('随')
        flags_info = ','.join(flag_parts) if flag_parts else '-'
        row = self.table.rowCount(); self.table.insertRow(row)
        vals = [str(rec['index']), map_info, str(enemy_count), str(trea_count),
                str(trap_count), trea_detail, chars_info, flags_info]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, c, item)

    def _refresh_tree(self):
        self.table.setRowCount(0)
        for rec in self.records: self._fill_tree_row(rec)

    def _on_table_select(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows: return
        idx = int(self.table.item(rows[0].row(), 0).text())
        self._current_idx = idx
        self._populate_fields(self.records[idx])

    def _populate_fields(self, rec):
        self._current_idx = rec['index']
        self._populate_params_tab(rec)
        self._populate_allparams_tab(rec)
        self._populate_enemy_tab(rec)
        self._populate_ally_tab(rec)
        self._populate_drops_tab(rec)
        self._populate_trap_tab(rec)
        self._redraw_scene()

    # ── 文件操作 ──
    def _load_tks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录")
        if not d: return
        wd = os.path.join(d, 'WarData.dat'); ww = os.path.join(d, 'WarWay.dat')
        wsc_g = os.path.join(d, 'WSC.GRP'); wsc_i = os.path.join(d, 'WSC.IDX')
        tkt = os.path.join(d, 'TKT.dat'); warpc = os.path.join(d, 'WarPC.dat')
        tkitem = os.path.join(d, 'TKItem.dat')
        missing = []
        for p, n in [(wd,'WarData.dat'),(ww,'WarWay.dat'),(wsc_g,'WSC.GRP'),
                      (wsc_i,'WSC.IDX'),(tkt,'TKT.dat'),(warpc,'WarPC.dat'),(tkitem,'TKItem.dat')]:
            if not os.path.exists(p): missing.append(n)
        if missing:
            if 'WarData.dat' in missing:
                QMessageBox.critical(self, "错误", "缺少必要文件 WarData.dat"); return
            QMessageBox.warning(self, "警告", "以下文件未找到:\n  " + "\n  ".join(missing))
        self.wardata_path = wd
        self.warway_path = ww if os.path.exists(ww) else None
        self.wsc_grp_path = wsc_g if os.path.exists(wsc_g) else None
        self.wsc_idx_path = wsc_i if os.path.exists(wsc_i) else None
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self.warpc_path = warpc if os.path.exists(warpc) else None
        self.tkitem_path = tkitem if os.path.exists(tkitem) else None
        self.records = load_wardata(self.wardata_path)
        self.wsc_offsets = load_wsc_idx(self.wsc_idx_path) if self.wsc_idx_path else []
        self.tkt = load_tkt(self.tkt_path) if self.tkt_path else {}
        self.warpc_names = load_warpc_names(self.warpc_path, self.tkt) if self.warpc_path else {}
        if self.tkitem_path:
            self.tkitem_names, self.tkitem_names_by_id = load_tkitem_names(self.tkitem_path, self.tkt)
        else: self.tkitem_names, self.tkitem_names_by_id = {}, {}
        self._wsc_cache.clear(); self._wsc_res_cache.clear()
        self._refresh_tree(); self._set_edit_enabled(True); self._dirty = False
        self._update_paths()
        self.status_var.setText(f"已加载 {len(self.records)} 场战斗")

    def _save(self):
        if not self.wardata_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据"); return
        if QMessageBox.question(self, "确认保存",
            f"保存 {len(self.records)} 条到:\n{self.wardata_path}\n\n原文件将被覆盖(生成.bak).",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        self._apply_current_edit()
        save_wardata(self.wardata_path, self.records)
        self._dirty = False; self.status_var.setText("已保存")

    def _save_as(self):
        fp, _ = QFileDialog.getSaveFileName(self, "另存 WarData.dat", "", "DAT files (*.dat);;All (*.*)")
        if fp:
            self._apply_current_edit(); save_wardata(fp, self.records)
            self.wardata_path = fp; self._dirty = False
            self.status_var.setText(f"已另存为 {fp}")

    def _apply_current_edit(self):
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        self._apply_params_tab(rec); self._apply_allparams_tab(rec)
        self._apply_enemy_tab(rec); self._apply_ally_tab(rec)
        self._apply_drops_tab(rec); self._apply_trap_tab(rec)

    def _apply_filter(self):
        query = self.search_entry.text().strip().lower()
        self.table.setRowCount(0)
        for rec in self.records:
            enemy_names = []; seen = set()
            for eid in rec['enemy_ids']:
                if eid > 0 and eid not in seen:
                    seen.add(eid); enemy_names.append(self._enemy_name(eid))
            char_names = ','.join(enemy_names) if enemy_names else ''
            if query and query not in str(rec['index']) and query not in str(rec['map_id']) \
               and query not in char_names.lower(): continue
            self._fill_tree_row(rec)

    def _clear_filter(self):
        self.search_entry.clear(); self._refresh_tree()

    def _reload(self):
        if not self.wardata_path: return
        self.records = load_wardata(self.wardata_path)
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
            self.warpc_names = load_warpc_names(self.warpc_path, self.tkt) if self.warpc_path else {}
            if self.tkitem_path:
                self.tkitem_names, self.tkitem_names_by_id = load_tkitem_names(self.tkitem_path, self.tkt)
        self._refresh_tree(); self._dirty = False; self.status_var.setText("已重新加载")

    # ── 记录管理 ──
    def _new_battle(self):
        if not self.records: return
        new_idx = len(self.records)
        rec = {'index':new_idx,'battle_id':new_idx,'flags':0,'must_chars':[0]*6,
            'battle_name_id':0,'map_id':0,'enemy_ids':[0]*18,'enemy_lv':[0]*18,
            'enemy_power':[0]*18,'enemy_lv_range':[0]*36,'enemy_delay':[0]*18,
            'enemy_xy':[0]*36,'ally_xy':[0]*12,'ally_facing':[0]*6,
            'trap_xy':[0]*56,'trap_pwr':[0]*56,'trea_sub':[0]*10,'trea_quant':[0]*20,
            'trap_type':[0]*28,'enemy_flags':[0]*18,'lv_spread_lo':0,'lv_spread_hi':0,
            'battle_turn_limit':0,'_raw':bytes(bytearray(WAR_REC_SIZE))}
        self.records.append(rec); self._refresh_tree(); self._dirty = True
        self.status_var.setText(f"已新增战场 #{new_idx}")

    def _copy_record(self):
        if self._current_idx < 0: return
        import copy
        src = self.records[self._current_idx]; new_idx = len(self.records)
        rec = copy.deepcopy(src); rec['index'] = new_idx; rec['battle_id'] = new_idx
        rec['_raw'] = bytearray(src['_raw']); self.records.append(rec)
        self._refresh_tree(); self._dirty = True
        self.status_var.setText(f"已复制 #{self._current_idx} -> #{new_idx}")

    def _delete_record(self):
        if self._current_idx < 0: return
        if QMessageBox.question(self,"确认删除",f"删除战场 #{self._current_idx}?",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        del self.records[self._current_idx]
        for i,rec in enumerate(self.records): rec['index'] = i
        self._current_idx = -1; self._refresh_tree(); self._dirty = True
        self.status_var.setText("已删除战场")

    def _show_field_ref(self):
        QMessageBox.information(self, "字段参考",
            "WarData.dat 字段参考\n\n[0] flags [2-7] must_chars [30] name_id [32] map_id\n"
            "[34-69] enemy_id×18 [70-87] enemy_lv [88-105] enemy_power\n"
            "[106-141] enemy_lv_range [142-177] enemy_xy [178-189] ally_xy\n"
            "[190-207] enemy_delay [208-213] ally_facing\n"
            "[214-269] trap_xy [270-325] trap_pwr [326-345] trea_sub×10\n"
            "[346-385] trea_quant×20 [386-441] trap_type×28 [442-477] enemy_flg×18\n"
            "[478] lv_spread_lo [480] lv_spread_hi [482] turn_limit\n\n"
            "WarWay.dat: 1024字节/条, 32x32网格, -1=障碍, 0=通行, 1-5=区域")

    def _show_about(self):
        QMessageBox.about(self, "关于", "WarData.dat 可视化编辑器 v2.0\n\nPySide6 版本\n基于游戏逆向工程 (TKS.exe 反编译)")

    def closeEvent(self, event):
        if self._dirty:
            r = QMessageBox.question(self,"未保存","有未保存的修改,是否保存后退出?",
                QMessageBox.Yes|QMessageBox.No|QMessageBox.Cancel)
            if r == QMessageBox.Yes: self._save()
            elif r == QMessageBox.Cancel: event.ignore(); return
        event.accept()

    # ═══════════════════════════════════════════════════════════
    # 战场参数标签页
    # ═══════════════════════════════════════════════════════════

    def _build_params_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        layout.setContentsMargins(4,4,12,4); layout.setSpacing(4)
        self.pvars = {}

        # ── 基本信息 ──
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader("基本信息"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(6)
        fields = [
            ("battle_id", "战场序号", "记录索引号(0-218)"),
            ("map_id", "地图编号", "[offset 32] WSC.GRP背景索引"),
            ("battle_name_id", "名称文本ID", "[offset 30] TKT文本ID"),
            ("battle_turn_limit", "回合限制", "[offset 482] >0时限制回合数"),
        ]
        for c, (key, label, tip) in enumerate(fields):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(label); lbl.setProperty("class", "PropLabel"); lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit(); self.pvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            grid.addLayout(cell, 0, c, Qt.AlignTop)
        for c in range(4): grid.setColumnStretch(c, 1)
        bl.addLayout(grid); gl.addWidget(body); layout.addWidget(grp)

        # ── 参数标志 ──
        grp2 = QWidget()
        gl2 = QVBoxLayout(grp2); gl2.setContentsMargins(0,0,0,0); gl2.setSpacing(0)
        gl2.addWidget(DockHeader("参数标志 [offset 0]"))
        body2 = QWidget(); body2.setObjectName("DockBody")
        bl2 = QVBoxLayout(body2); bl2.setContentsMargins(8,8,8,8)
        flag_grid = QGridLayout(); flag_grid.setHorizontalSpacing(8); flag_grid.setVerticalSpacing(6)
        cell = QVBoxLayout(); cell.setSpacing(2)
        lbl = QLabel("标志值"); lbl.setProperty("class", "PropLabel")
        lbl.setToolTip("bit1(&2)=失败条件, bit2(&4)=随机敌军")
        cell.addWidget(lbl)
        self.pvars['flags'] = ev = QLineEdit()
        cell.addWidget(make_fake_input(line_edit=ev))
        flag_grid.addLayout(cell, 0, 0, Qt.AlignTop)
        flag_grid.setColumnStretch(0, 1)
        cb_cell = QVBoxLayout(); cb_cell.setSpacing(4)
        cb_cell.addWidget(QLabel(""))  # spacer to align with input
        self.flag_bit1 = QCheckBox("bit1: 失败后继续"); self.flag_bit1.toggled.connect(self._on_flag_change)
        cb_cell.addWidget(self.flag_bit1)
        self.flag_bit2 = QCheckBox("bit2: 随机敌军数量"); self.flag_bit2.toggled.connect(self._on_flag_change)
        cb_cell.addWidget(self.flag_bit2)
        flag_grid.addLayout(cb_cell, 0, 1, Qt.AlignTop)
        flag_grid.setColumnStretch(1, 2)
        bl2.addLayout(flag_grid); gl2.addWidget(body2); layout.addWidget(grp2)

        # ── 强制出战角色 ──
        grp3 = QWidget()
        gl3 = QVBoxLayout(grp3); gl3.setContentsMargins(0,0,0,0); gl3.setSpacing(0)
        gl3.addWidget(DockHeader("强制出战角色 [002-007] (6槽位, +1编码)"))
        body3 = QWidget(); body3.setObjectName("DockBody")
        bl3 = QVBoxLayout(body3); bl3.setContentsMargins(8,8,8,8)
        mc_grid = QGridLayout(); mc_grid.setHorizontalSpacing(8); mc_grid.setVerticalSpacing(6)
        self.pvars['must_chars'] = []; self.must_char_labels = []
        for i in range(6):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(f"槽{i}"); lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            var = QLineEdit(); self.pvars['must_chars'].append(var)
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText")
            self.must_char_labels.append(extra)
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            var.setFrame(False); bh.addWidget(var); bh.addStretch()
            cell.addWidget(box)
            cell.addWidget(extra)
            mc_grid.addLayout(cell, 0, i, Qt.AlignTop)
        for c in range(6): mc_grid.setColumnStretch(c, 1)
        bl3.addLayout(mc_grid); gl3.addWidget(body3); layout.addWidget(grp3)

        layout.addStretch()
        scroll.setWidget(inner); self.tabs.addTab(scroll, "战场参数")

    def _on_flag_change(self):
        flags = 0
        if self.flag_bit1.isChecked(): flags |= 2
        if self.flag_bit2.isChecked(): flags |= 4
        self.pvars['flags'].setText(str(flags)); self._dirty = True

    def _populate_params_tab(self, rec):
        self.pvars['battle_id'].setText(str(rec['battle_id']))
        self.pvars['map_id'].setText(str(rec['map_id']))
        self.pvars['battle_name_id'].setText(str(rec['battle_name_id']))
        self.pvars['battle_turn_limit'].setText(str(rec['battle_turn_limit']))
        self.pvars['flags'].setText(str(rec['flags']))
        self.flag_bit1.blockSignals(True); self.flag_bit1.setChecked((rec['flags']&2)!=0); self.flag_bit1.blockSignals(False)
        self.flag_bit2.blockSignals(True); self.flag_bit2.setChecked((rec['flags']&4)!=0); self.flag_bit2.blockSignals(False)
        for i in range(6):
            v = rec['must_chars'][i]; self.pvars['must_chars'][i].setText(str(v))
            self.must_char_labels[i].setText(self._char_name(v-1)[:12] if v and v!=255 else "")

    def _apply_params_tab(self, rec):
        try: rec['battle_id'] = int(self.pvars['battle_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['map_id'] = int(self.pvars['map_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['battle_name_id'] = int(self.pvars['battle_name_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['battle_turn_limit'] = int(self.pvars['battle_turn_limit'].text() or 0) & 0xFFFF
        except: pass
        try: rec['flags'] = int(self.pvars['flags'].text() or 0) & 0xFF
        except: pass
        for i in range(6):
            try: rec['must_chars'][i] = int(self.pvars['must_chars'][i].text() or 0) & 0xFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 全部参数标签页
    # ═══════════════════════════════════════════════════════════

    def _build_allparams_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        layout.setContentsMargins(4,4,12,4); layout.setSpacing(4)
        self.apvars = {}; self.apflag_bit1 = None; self.apflag_bit2 = None

        # ── 基本信息 ──
        grp = QWidget()
        gl = QVBoxLayout(grp); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.addWidget(DockHeader("基本信息"))
        body = QWidget(); body.setObjectName("DockBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(8,8,8,8)
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(6)
        fields = [
            ("battle_id", "战场序号", "记录索引号(0-218)"),
            ("map_id", "地图编号", "[offset 32] WSC.GRP背景索引"),
            ("battle_name_id", "名称文本ID", "[offset 30] TKT文本ID"),
            ("battle_turn_limit", "回合限制", "[offset 482] >0时限制回合数"),
        ]
        for c, (key, label, tip) in enumerate(fields):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(label); lbl.setProperty("class", "PropLabel"); lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit(); self.apvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            grid.addLayout(cell, 0, c, Qt.AlignTop)
        for c in range(4): grid.setColumnStretch(c, 1)
        bl.addLayout(grid); gl.addWidget(body); layout.addWidget(grp)

        # ── 参数标志 ──
        grp2 = QWidget()
        gl2 = QVBoxLayout(grp2); gl2.setContentsMargins(0,0,0,0); gl2.setSpacing(0)
        gl2.addWidget(DockHeader("参数标志 [offset 0]"))
        body2 = QWidget(); body2.setObjectName("DockBody")
        bl2 = QVBoxLayout(body2); bl2.setContentsMargins(8,8,8,8)
        flag_grid = QGridLayout(); flag_grid.setHorizontalSpacing(8); flag_grid.setVerticalSpacing(6)
        cell = QVBoxLayout(); cell.setSpacing(2)
        lbl = QLabel("标志值"); lbl.setProperty("class", "PropLabel")
        lbl.setToolTip("bit1(&2)=失败条件, bit2(&4)=随机敌军")
        cell.addWidget(lbl)
        self.apvars['flags'] = ev = QLineEdit()
        cell.addWidget(make_fake_input(line_edit=ev))
        flag_grid.addLayout(cell, 0, 0, Qt.AlignTop)
        flag_grid.setColumnStretch(0, 1)
        cb_cell = QVBoxLayout(); cb_cell.setSpacing(4)
        cb_cell.addWidget(QLabel(""))  # spacer to align with input
        self.apflag_bit1 = QCheckBox("bit1: 失败后继续"); self.apflag_bit1.toggled.connect(self._on_apflag_change)
        cb_cell.addWidget(self.apflag_bit1)
        self.apflag_bit2 = QCheckBox("bit2: 随机敌军数量"); self.apflag_bit2.toggled.connect(self._on_apflag_change)
        cb_cell.addWidget(self.apflag_bit2)
        flag_grid.addLayout(cb_cell, 0, 1, Qt.AlignTop)
        flag_grid.setColumnStretch(1, 2)
        bl2.addLayout(flag_grid); gl2.addWidget(body2); layout.addWidget(grp2)

        # ── 强制出战角色 ──
        grp3 = QWidget()
        gl3 = QVBoxLayout(grp3); gl3.setContentsMargins(0,0,0,0); gl3.setSpacing(0)
        gl3.addWidget(DockHeader("强制出战角色 [002-007] (6槽位, +1编码)"))
        body3 = QWidget(); body3.setObjectName("DockBody")
        bl3 = QVBoxLayout(body3); bl3.setContentsMargins(8,8,8,8)
        mc_grid = QGridLayout(); mc_grid.setHorizontalSpacing(8); mc_grid.setVerticalSpacing(6)
        self.apvars['must_chars'] = []; self.ap_must_char_labels = []
        for i in range(6):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(f"槽{i}"); lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            var = QLineEdit(); self.apvars['must_chars'].append(var)
            extra = QLabel(""); extra.setProperty("class", "ExtraPreviewText")
            self.ap_must_char_labels.append(extra)
            box = QFrame(); box.setObjectName("FakeInputBox")
            bh = QHBoxLayout(box); bh.setContentsMargins(0,0,0,0); bh.setSpacing(0)
            var.setFrame(False); bh.addWidget(var); bh.addStretch()
            cell.addWidget(box)
            cell.addWidget(extra)
            mc_grid.addLayout(cell, 0, i, Qt.AlignTop)
        for c in range(6): mc_grid.setColumnStretch(c, 1)
        bl3.addLayout(mc_grid); gl3.addWidget(body3); layout.addWidget(grp3)

        # ── 敌军配置 ──
        grp_enemy = QWidget()
        gl_enemy = QVBoxLayout(grp_enemy); gl_enemy.setContentsMargins(0,0,0,0); gl_enemy.setSpacing(0)
        gl_enemy.addWidget(DockHeader("敌军配置 [034-177] ×18"))
        body_enemy = QWidget(); body_enemy.setObjectName("DockBody")
        bl_enemy = QVBoxLayout(body_enemy); bl_enemy.setContentsMargins(8,8,8,8)
        tbl = QTableWidget(18, 9); tbl.setMinimumHeight(350)
        tbl.setHorizontalHeaderLabels(["ID\nu16[034-069]","Lv\nu8[070-087]","加成\nu8[088-105]","LvP1\ni8[106-141]","LvP2\ni8[106-141]","X\ni8[142-177]","Y\ni8[142-177]","时序Delay\nu8[190-207]","标志\nu16[442-477]"])
        tbl.setColumnWidth(0,55); tbl.setColumnWidth(1,45); tbl.setColumnWidth(2,45)
        tbl.setColumnWidth(3,45); tbl.setColumnWidth(4,45); tbl.setColumnWidth(5,35)
        tbl.setColumnWidth(6,35); tbl.setColumnWidth(7,65); tbl.setColumnWidth(8,55)
        tbl.verticalHeader().setDefaultSectionSize(24)
        self.ap_enemy_table = tbl
        bl_enemy.addWidget(tbl); gl_enemy.addWidget(body_enemy); layout.addWidget(grp_enemy)

        # ── 友军配置 ──
        grp_ally = QWidget()
        gl_ally = QVBoxLayout(grp_ally); gl_ally.setContentsMargins(0,0,0,0); gl_ally.setSpacing(0)
        gl_ally.addWidget(DockHeader("友军配置 [178-213] ×6"))
        body_ally = QWidget(); body_ally.setObjectName("DockBody")
        bl_ally = QVBoxLayout(body_ally); bl_ally.setContentsMargins(8,8,8,8)
        atbl = QTableWidget(6, 3); atbl.setMinimumHeight(160)
        atbl.setHorizontalHeaderLabels(["X\ni8[178-189]","Y\ni8[178-189]","朝向\nu8[208-213]"])
        atbl.setColumnWidth(0,35); atbl.setColumnWidth(1,35); atbl.setColumnWidth(2,65)
        atbl.verticalHeader().setDefaultSectionSize(24)
        self.ap_ally_table = atbl
        bl_ally.addWidget(atbl); gl_ally.addWidget(body_ally); layout.addWidget(grp_ally)

        # ── 宝物/陷阱 ──
        grp_trea = QWidget()
        gl_trea = QVBoxLayout(grp_trea); gl_trea.setContentsMargins(0,0,0,0); gl_trea.setSpacing(0)
        gl_trea.addWidget(DockHeader("宝物/陷阱 [214-441] ×28"))
        body_trea = QWidget(); body_trea.setObjectName("DockBody")
        bl_trea = QVBoxLayout(body_trea); bl_trea.setContentsMargins(8,8,8,8)
        ttbl = QTableWidget(28, 8); ttbl.setMinimumHeight(500)
        ttbl.setHorizontalHeaderLabels(["陷阱类型\nu16[386-441]","副物品\nu16[326-345]","X\ni8[214-269]","Y\ni8[214-269]","威Min\nu8[270-325]","威Max\nu8[270-325]","QtMin\nu16[346-385]","QtMax\nu16[346-385]"])
        ttbl.setColumnWidth(0,65); ttbl.setColumnWidth(1,65); ttbl.setColumnWidth(2,35)
        ttbl.setColumnWidth(3,35); ttbl.setColumnWidth(4,45); ttbl.setColumnWidth(5,45)
        ttbl.setColumnWidth(6,55); ttbl.setColumnWidth(7,55)
        ttbl.verticalHeader().setDefaultSectionSize(24)
        self.ap_trea_table = ttbl
        bl_trea.addWidget(ttbl); gl_trea.addWidget(body_trea); layout.addWidget(grp_trea)

        # ── 其他参数 ──
        grp4 = QWidget()
        gl4 = QVBoxLayout(grp4); gl4.setContentsMargins(0,0,0,0); gl4.setSpacing(0)
        gl4.addWidget(DockHeader("其他参数 [478-497]"))
        body4 = QWidget(); body4.setObjectName("DockBody")
        bl4 = QVBoxLayout(body4); bl4.setContentsMargins(8,8,8,8)
        g3 = QGridLayout(); g3.setHorizontalSpacing(8); g3.setVerticalSpacing(6)
        other_fields = [
            ("lv_spread_lo", "Lv浮动下限", "[offset 478]"),
            ("lv_spread_hi", "Lv浮动上限", "[offset 480]"),
        ]
        for c, (key, label, tip) in enumerate(other_fields):
            cell = QVBoxLayout(); cell.setSpacing(2)
            lbl = QLabel(label); lbl.setProperty("class", "PropLabel"); lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit(); self.apvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            g3.addLayout(cell, 0, c, Qt.AlignTop)
        for c in range(3): g3.setColumnStretch(c, 1)
        bl4.addLayout(g3); gl4.addWidget(body4); layout.addWidget(grp4)
        layout.addWidget(QLabel("[484-497] (保留14字节 — 全零)"))

        layout.addStretch()
        scroll.setWidget(inner); self.tabs.addTab(scroll, "全部参数")

    def _on_apflag_change(self):
        flags = 0
        if self.apflag_bit1.isChecked(): flags |= 2
        if self.apflag_bit2.isChecked(): flags |= 4
        self.apvars['flags'].setText(str(flags)); self._dirty = True

    def _populate_allparams_tab(self, rec):
        self.apvars['battle_id'].setText(str(rec['battle_id']))
        self.apvars['map_id'].setText(str(rec['map_id']))
        self.apvars['battle_name_id'].setText(str(rec['battle_name_id']))
        self.apvars['battle_turn_limit'].setText(str(rec['battle_turn_limit']))
        self.apvars['flags'].setText(str(rec['flags']))
        self.apvars['lv_spread_lo'].setText(str(rec['lv_spread_lo']))
        self.apvars['lv_spread_hi'].setText(str(rec['lv_spread_hi']))
        self.apflag_bit1.blockSignals(True); self.apflag_bit1.setChecked((rec['flags']&2)!=0); self.apflag_bit1.blockSignals(False)
        self.apflag_bit2.blockSignals(True); self.apflag_bit2.setChecked((rec['flags']&4)!=0); self.apflag_bit2.blockSignals(False)
        for i in range(6):
            v = rec['must_chars'][i]; self.apvars['must_chars'][i].setText(str(v))
            self.ap_must_char_labels[i].setText(self._char_name(v-1)[:12] if v and v!=255 else "")
        # 敌军表
        tbl = self.ap_enemy_table
        for i in range(18):
            vals = [str(rec['enemy_ids'][i]), str(rec['enemy_lv'][i]), str(rec['enemy_power'][i]),
                    str(rec['enemy_lv_range'][i*2]), str(rec['enemy_lv_range'][i*2+1]),
                    str(rec['enemy_xy'][i*2]), str(rec['enemy_xy'][i*2+1]),
                    str(rec['enemy_delay'][i]), str(rec['enemy_flags'][i])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)
        # 友军表
        atbl = self.ap_ally_table
        for i in range(6):
            for c, v in enumerate([str(rec['ally_xy'][i*2]), str(rec['ally_xy'][i*2+1]), str(rec['ally_facing'][i])]):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); atbl.setItem(i, c, item)
        # 宝物表
        ttbl = self.ap_trea_table
        for i in range(28):
            vals = [str(rec['trap_type'][i]),
                    str(rec['trea_sub'][i]) if i < 10 else '',
                    str(rec['trap_xy'][i*2]), str(rec['trap_xy'][i*2+1]),
                    str(rec['trap_pwr'][i*2]), str(rec['trap_pwr'][i*2+1]),
                    str(rec['trea_quant'][i*2]) if i < 10 else '',
                    str(rec['trea_quant'][i*2+1]) if i < 10 else '']
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); ttbl.setItem(i, c, item)

    def _apply_allparams_tab(self, rec):
        try: rec['battle_id'] = int(self.apvars['battle_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['map_id'] = int(self.apvars['map_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['battle_name_id'] = int(self.apvars['battle_name_id'].text() or 0) & 0xFFFF
        except: pass
        try: rec['battle_turn_limit'] = int(self.apvars['battle_turn_limit'].text() or 0) & 0xFFFF
        except: pass
        try: rec['flags'] = int(self.apvars['flags'].text() or 0) & 0xFF
        except: pass
        try: rec['lv_spread_lo'] = int(self.apvars['lv_spread_lo'].text() or 0) & 0xFF
        except: pass
        try: rec['lv_spread_hi'] = int(self.apvars['lv_spread_hi'].text() or 0) & 0xFF
        except: pass
        for i in range(6):
            try: rec['must_chars'][i] = int(self.apvars['must_chars'][i].text() or 0) & 0xFF
            except: pass
        tbl = self.ap_enemy_table
        def _gi(tbl, r, c):
            item = tbl.item(r, c); return int(item.text()) if item and item.text() else 0
        for i in range(18):
            try: rec['enemy_ids'][i] = _gi(tbl, i, 0)
            except: pass
            try: rec['enemy_lv'][i] = _gi(tbl, i, 1) & 0xFF
            except: pass
            try: rec['enemy_power'][i] = _gi(tbl, i, 2) & 0xFF
            except: pass
            try: rec['enemy_lv_range'][i*2] = _gi(tbl, i, 3)
            except: pass
            try: rec['enemy_lv_range'][i*2+1] = _gi(tbl, i, 4)
            except: pass
            try: rec['enemy_xy'][i*2] = _gi(tbl, i, 5)
            except: pass
            try: rec['enemy_xy'][i*2+1] = _gi(tbl, i, 6)
            except: pass
            try: rec['enemy_delay'][i] = _gi(tbl, i, 7) & 0xFF
            except: pass
            try: rec['enemy_flags'][i] = _gi(tbl, i, 8) & 0xFFFF
            except: pass
        atbl = self.ap_ally_table
        for i in range(6):
            try: rec['ally_xy'][i*2] = _gi(atbl, i, 0)
            except: pass
            try: rec['ally_xy'][i*2+1] = _gi(atbl, i, 1)
            except: pass
            try: rec['ally_facing'][i] = _gi(atbl, i, 2) & 0xFF
            except: pass
        ttbl = self.ap_trea_table
        for i in range(28):
            try: rec['trap_type'][i] = _gi(ttbl, i, 0) & 0xFFFF
            except: pass
            if i < 10:
                try: rec['trea_sub'][i] = _gi(ttbl, i, 1) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2] = _gi(ttbl, i, 6) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2+1] = _gi(ttbl, i, 7) & 0xFFFF
                except: pass
            try: rec['trap_xy'][i*2] = _gi(ttbl, i, 2)
            except: pass
            try: rec['trap_xy'][i*2+1] = _gi(ttbl, i, 3)
            except: pass
            try: rec['trap_pwr'][i*2] = _gi(ttbl, i, 4) & 0xFF
            except: pass
            try: rec['trap_pwr'][i*2+1] = _gi(ttbl, i, 5) & 0xFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 敌军配置标签页
    # ═══════════════════════════════════════════════════════════

    def _build_enemy_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8); layout.setSpacing(4)
        tbl = QTableWidget(18, 11)
        tbl.setHorizontalHeaderLabels(["槽","角色ID","角色名","等级","加成倍率","LvP1","LvP2","X","Y","Delay","精英/特殊"])
        tbl.setColumnWidth(0,35); tbl.setColumnWidth(1,55); tbl.setColumnWidth(2,100)
        tbl.setColumnWidth(3,45); tbl.setColumnWidth(4,55); tbl.setColumnWidth(5,45)
        tbl.setColumnWidth(6,45); tbl.setColumnWidth(7,45); tbl.setColumnWidth(8,45)
        tbl.setColumnWidth(9,45); tbl.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)
        tbl.verticalHeader().setDefaultSectionSize(24)
        self.enemy_table = tbl; self.enemy_name_labels = []
        for i in range(18):
            item = QTableWidgetItem(str(i)); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, 0, item)
            name_lbl = QLabel(""); name_lbl.setProperty("class","ExtraPreviewText")
            self.enemy_name_labels.append(name_lbl); tbl.setCellWidget(i, 2, name_lbl)
        layout.addWidget(tbl); scroll.setWidget(inner); self.tabs.addTab(scroll, "敌军配置")

    def _populate_enemy_tab(self, rec):
        tbl = self.enemy_table
        for i in range(18):
            eid = rec['enemy_ids'][i]
            for c, v in enumerate([str(eid), None, str(rec['enemy_lv'][i]),
                str(rec['enemy_power'][i]), str(rec['enemy_lv_range'][i*2]),
                str(rec['enemy_lv_range'][i*2+1]), str(rec['enemy_xy'][i*2]),
                str(rec['enemy_xy'][i*2+1]), str(rec['enemy_delay'][i]),
                str(rec['enemy_flags'][i])], 1):
                if v is None: continue
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)
            f = rec['enemy_flags'][i]; parts = []
            if f&1: parts.append('精英')
            if f&2: parts.append('特殊')
            if f&0x2000: parts.append('阵营A')
            if f&0x4000: parts.append('阵营B')
            if f&0x8000: parts.append('特殊型')
            self.enemy_name_labels[i].setText(self._enemy_name(eid)[:14] if eid else "(空)")
            tip_item = QTableWidgetItem('/'.join(parts) if parts else '')
            tip_item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, 10, tip_item)

    def _apply_enemy_tab(self, rec):
        tbl = self.enemy_table
        def _g(r, c):
            item = tbl.item(r, c); return int(item.text()) if item and item.text() else 0
        for i in range(18):
            try: rec['enemy_ids'][i] = _g(i, 1)
            except: pass
            try: rec['enemy_lv'][i] = _g(i, 3) & 0xFF
            except: pass
            try: rec['enemy_power'][i] = _g(i, 4) & 0xFF
            except: pass
            try: rec['enemy_lv_range'][i*2] = _g(i, 5)
            except: pass
            try: rec['enemy_lv_range'][i*2+1] = _g(i, 6)
            except: pass
            try: rec['enemy_xy'][i*2] = _g(i, 7)
            except: pass
            try: rec['enemy_xy'][i*2+1] = _g(i, 8)
            except: pass
            try: rec['enemy_delay'][i] = _g(i, 9) & 0xFF
            except: pass
            try: rec['enemy_flags'][i] = _g(i, 10) & 0xFFFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 友军配置标签页
    # ═══════════════════════════════════════════════════════════

    def _build_ally_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8); layout.setSpacing(4)
        layout.addWidget(QLabel("友军坐标+朝向 (sub_431428:74 — int8字节对):"))
        tbl = QTableWidget(6, 4)
        tbl.setHorizontalHeaderLabels(["槽","X","Y","朝向"])
        tbl.setColumnWidth(0,35); tbl.setColumnWidth(1,55); tbl.setColumnWidth(2,55); tbl.setColumnWidth(3,55)
        tbl.verticalHeader().setDefaultSectionSize(24)
        self.ally_table = tbl
        for i in range(6):
            item = QTableWidgetItem(str(i)); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, 0, item)
        layout.addWidget(tbl)
        layout.addWidget(QLabel("X,Y: int8(0-31), 0=不使用; 朝向: 0-7(八方), 255=无效"))
        layout.addStretch()
        scroll.setWidget(inner); self.tabs.addTab(scroll, "友军配置")

    def _populate_ally_tab(self, rec):
        tbl = self.ally_table
        for i in range(6):
            for c, v in enumerate([str(rec['ally_xy'][i*2]), str(rec['ally_xy'][i*2+1]), str(rec['ally_facing'][i])], 1):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)

    def _apply_ally_tab(self, rec):
        tbl = self.ally_table
        def _g(r, c):
            item = tbl.item(r, c); return int(item.text()) if item and item.text() else 0
        for i in range(6):
            try: rec['ally_xy'][i*2] = _g(i, 1)
            except: pass
            try: rec['ally_xy'][i*2+1] = _g(i, 2)
            except: pass
            try: rec['ally_facing'][i] = _g(i, 3) & 0xFF
            except: pass

    # ═══════════════════════════════════════════════════════════
    # 宝物和陷阱标签页
    # ═══════════════════════════════════════════════════════════

    def _build_drops_traps_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8); layout.setSpacing(4)
        layout.addWidget(QLabel("宝物和陷阱 (sub_431428:198-323) — 28槽位, 共享X/Y"))
        tbl = QTableWidget(28, 10)
        tbl.setHorizontalHeaderLabels(["槽","X","Y","宝物ID","宝物名","数Min","数Max","陷阱类型","威Min","威Max"])
        tbl.setColumnWidth(0,30); tbl.setColumnWidth(1,45); tbl.setColumnWidth(2,45)
        tbl.setColumnWidth(3,55); tbl.setColumnWidth(4,90); tbl.setColumnWidth(5,50)
        tbl.setColumnWidth(6,50); tbl.setColumnWidth(7,90); tbl.setColumnWidth(8,50); tbl.setColumnWidth(9,50)
        tbl.verticalHeader().setDefaultSectionSize(24)
        self.dt_table = tbl; self.dt_name_labels = []
        trap_items = list(TRAP_NAMES_MAP.values())
        for i in range(28):
            item = QTableWidgetItem(str(i)); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, 0, item)
            name_lbl = QLabel(""); name_lbl.setProperty("class","ExtraPreviewText")
            self.dt_name_labels.append(name_lbl); tbl.setCellWidget(i, 4, name_lbl)
            cb = QComboBox(); cb.addItems(trap_items); tbl.setCellWidget(i, 7, cb)
        layout.addWidget(tbl)
        layout.addWidget(QLabel("陷阱1-6→TKKon[552-557] | 宝物:trea_sub+trea_quant(slot0-9)"))
        scroll.setWidget(inner); self.tabs.addTab(scroll, "宝物和陷阱")

    def _populate_drops_tab(self, rec):
        tbl = self.dt_table
        for i in range(28):
            for c, v in enumerate([str(rec['trap_xy'][i*2]), str(rec['trap_xy'][i*2+1])], 1):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)
            tid = rec['trea_sub'][i] if i < 10 else 0
            item = QTableWidgetItem(str(tid)); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, 3, item)
            if tid == 10000: self.dt_name_labels[i].setText("金钱")
            elif tid and tid in self.tkitem_names_by_id: self.dt_name_labels[i].setText(self.tkitem_names_by_id[tid][:12])
            elif tid: self.dt_name_labels[i].setText(f"Item#{tid}")
            else: self.dt_name_labels[i].setText("")
            if i < 10:
                for c, v in enumerate([str(rec['trea_quant'][i*2]), str(rec['trea_quant'][i*2+1])], 5):
                    item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)

    def _populate_trap_tab(self, rec):
        tbl = self.dt_table
        for i in range(28):
            ttype = rec['trap_type'][i]
            cb = tbl.cellWidget(i, 7)
            if cb:
                cb.blockSignals(True)
                idx = max(0, min(6, ttype)) if 0 <= ttype <= 6 else 0
                cb.setCurrentIndex(idx); cb.blockSignals(False)
            pmin, pmax = self._trap_power_at(rec, i)
            for c, v in enumerate([str(pmin), str(pmax)], 8):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter); tbl.setItem(i, c, item)

    def _apply_drops_tab(self, rec):
        tbl = self.dt_table
        def _g(r, c):
            item = tbl.item(r, c); return int(item.text()) if item and item.text() else 0
        for i in range(28):
            try: rec['trap_xy'][i*2] = _g(i, 1)
            except: pass
            try: rec['trap_xy'][i*2+1] = _g(i, 2)
            except: pass
            if i < 10:
                try: rec['trea_sub'][i] = _g(i, 3) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2] = _g(i, 5) & 0xFFFF
                except: pass
                try: rec['trea_quant'][i*2+1] = _g(i, 6) & 0xFFFF
                except: pass

    def _apply_trap_tab(self, rec):
        tbl = self.dt_table
        def _g(r, c):
            item = tbl.item(r, c); return int(item.text()) if item and item.text() else 0
        for i in range(28):
            cb = tbl.cellWidget(i, 7)
            ttype = cb.currentIndex() if cb else 0
            ttype = max(0, min(6, ttype))
            rec['trap_type'][i] = ttype
            try: pmin = _g(i, 8) & 0xFF
            except: pmin = 0
            try: pmax = _g(i, 9) & 0xFF
            except: pmax = 0
            off = i * 2 if i < 10 else 20 + (i - 10) * 2
            rec['trap_pwr'][off] = pmin; rec['trap_pwr'][off + 1] = pmax

    # ═══════════════════════════════════════════════════════════
    # 场景预览标签页
    # ═══════════════════════════════════════════════════════════

    def _build_scene_tab(self):
        """场景预览标签页 — QGraphicsView + 图层控制"""
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.setContentsMargins(2,2,2,2); layout.setSpacing(2)

        # 控制栏
        ctrl = QHBoxLayout(); ctrl.setSpacing(4)
        ctrl.addWidget(QLabel("图层:"))
        self.show_bg = QCheckBox("背景"); self.show_bg.setChecked(True); self.show_bg.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_bg)
        self.show_grid = QCheckBox("网格"); self.show_grid.setChecked(True); self.show_grid.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_grid)
        ctrl.addWidget(QLabel("透明度:"))
        self.grid_alpha = QComboBox(); self.grid_alpha.addItems(['0%','25%','50%','75%','100%'])
        self.grid_alpha.setCurrentText('25%'); self.grid_alpha.currentTextChanged.connect(lambda: self._redraw_scene())
        ctrl.addWidget(self.grid_alpha)
        self.show_units = QCheckBox("单位"); self.show_units.setChecked(True); self.show_units.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_units)
        self.show_trea = QCheckBox("宝物"); self.show_trea.setChecked(True); self.show_trea.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_trea)
        self.show_trap = QCheckBox("陷阱"); self.show_trap.setChecked(True); self.show_trap.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_trap)
        self.show_obstacle = QCheckBox("障碍"); self.show_obstacle.setChecked(True); self.show_obstacle.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_obstacle)
        self.show_temp_obstacle = QCheckBox("临时障碍"); self.show_temp_obstacle.setChecked(True); self.show_temp_obstacle.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_temp_obstacle)
        self.show_zone = [QCheckBox(f"区域{i+1}") for i in range(5)]
        for z in self.show_zone: z.setChecked(True); z.toggled.connect(self._redraw_scene); ctrl.addWidget(z)
        ctrl.addWidget(QLabel("缩放:"))
        self.zoom_combo = QComboBox(); self.zoom_combo.addItems(['25%','33%','50%','66%','75%','100%'])
        self.zoom_combo.setCurrentText('50%'); self.zoom_combo.currentTextChanged.connect(self._on_zoom_change)
        ctrl.addWidget(self.zoom_combo)
        ctrl.addWidget(QPushButton("🔄 刷新", clicked=lambda: self._redraw_scene(True)))
        self.edit_mode = QCheckBox("编辑"); ctrl.addWidget(self.edit_mode)
        ctrl.addWidget(QLabel("背景=map_id(WSC)", styleSheet='color:gray'))
        layout.addLayout(ctrl)

        # 图例
        legend = QHBoxLayout(); legend.setSpacing(6)
        terrain_colors = [('障碍','#553322'),('临时障碍','#665544'),('区域1','#aa6633'),
                          ('区域2','#3366aa'),('区域3','#aa44aa'),('区域4','#33aa66'),('区域5','#aaaa33')]
        for label, color in terrain_colors:
            f = QWidget(); fl = QHBoxLayout(f); fl.setContentsMargins(0,0,0,0); fl.setSpacing(2)
            swatch = QLabel(); swatch.setFixedSize(12,12)
            swatch.setStyleSheet(f"background-color:{color}; border:1px solid #444;")
            fl.addWidget(swatch); fl.addWidget(QLabel(label)); legend.addWidget(f)
        legend.addStretch()
        self.scene_info_var = QLabel(""); self.scene_info_var.setProperty("class","ExtraPreviewText")
        legend.addWidget(self.scene_info_var)
        layout.addLayout(legend)

        # QGraphicsView
        self.scene_gview = SceneGraphicsView(self)
        layout.addWidget(self.scene_gview, 1)
        self.tabs.addTab(tab, "场景预览")

    def _on_zoom_change(self, text):
        try: self._preview_zoom = int(text.rstrip('%')) / 100.0
        except: return
        self._wsc_cache.clear(); self._redraw_scene()

    def _grid_to_screen(self, gx, gy):
        """网格坐标 → 屏幕像素 (sub_42F9C8 等距投影)
        sx = 359 + 56*(gx-10) - 56*(gy-15)
        sy = 365 + 28*(gx-10) + 28*(gy-15)
        其中 359/365 为 dword_4E7DF0/dword_4E7DF4 编译时常量
        """
        zoom = self._preview_zoom
        sx = round((359 + 56*(gx-10) - 56*(gy-15)) * zoom)
        sy = round((365 + 28*(gx-10) + 28*(gy-15)) * zoom)
        return sx, sy

    def _scene_to_grid(self, sx, sy):
        """屏幕像素 → 网格坐标 (逆推 sub_42F9C8)
        逆公式: gx = (px/56 + py/28) / 2 + 10
                 gy = (py/28 - px/56) / 2 + 15
        其中 px, py 为WSC背景图像像素坐标 (= screen / zoom)
        """
        zoom = self._preview_zoom
        if zoom <= 0: return None
        px = sx / zoom - 359; py = sy / zoom - 365
        a = (px/56 + py/28) / 2; b = (py/28 - px/56) / 2
        gx = round(a + 10); gy = round(b + 15)
        if 0 <= gx < 32 and 0 <= gy < 32: return (gx, gy)
        return None

    def _load_wsc_background(self, wsc_idx):
        if not HAS_PIL or not self.wsc_grp_path or not self.wsc_offsets: return None
        if wsc_idx in self._wsc_cache: return self._wsc_cache[wsc_idx]
        result = load_wsc_entry(self.wsc_grp_path, self.wsc_offsets, wsc_idx)
        if result is None: return None
        w, h, rgba = result
        img = Image.frombuffer('RGBA', (w, h), rgba, 'raw', 'RGBA', 0, 1)
        zoom = self._preview_zoom
        new_w = int(w * zoom); new_h = int(h * zoom)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        # Convert PIL Image to QPixmap
        qimg = QImage(img.tobytes(), new_w, new_h, new_w * 4, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self._wsc_cache[wsc_idx] = (pixmap, new_w, new_h)
        return (pixmap, new_w, new_h)

    def _resolve_scene_placements(self, rec, warway):
        """根据 sub_431428 + sub_4307CC 的游戏规则解析场景布置

        sub_431428 放置顺序: 友军固定→敌军固定→区域放置(1-5)→宝物固定→宝物区域放置
        sub_4307CC:200-210 flags&4 时随机敌军槽位数
        sub_452AC0: RNG = rand() % n → Python random.randrange(n)

        返回: (resolved_enemies, resolved_treas, resolved_traps,
               enemy_zone_reqs, trea_zone_reqs, trap_zone_reqs,
               active_slots, fixed_enemy_slots, fixed_trea_indices, fixed_trap_indices,
               resolved_allies)
        """
        # ── 友军数 & 激活槽位数 (sub_4307CC:200-210) ──
        ally_count = sum(1 for c in rec['must_chars'] if c > 0 and c != 255)
        if ally_count < 1: ally_count = 1
        flags = rec['flags']
        if flags & 4:
            if random.randint(0, 999) >= 300:
                active_slots = random.randrange(max(1, 2*ally_count-2)) + 3
            else:
                active_slots = random.randrange(ally_count//2 + ally_count) + 1
        else: active_slots = 18
        active_slots = min(active_slots, 18)

        zone_cells = {1:[], 2:[], 3:[], 4:[], 5:[]}
        if warway:
            for gy in range(32):
                for gx in range(32):
                    raw = warway[gy*32+gx]; val = raw if raw < 128 else raw-256
                    if 1 <= val <= 5: zone_cells[val].append((gx, gy))

        occupied = set()
        resolved_enemies = {}; resolved_treas = {}; resolved_allies = {}
        fixed_enemy_slots = set(); fixed_trea_indices = set()
        enemy_zone_reqs = []; trea_zone_reqs = []

        # 1. 友军固定位置
        for i in range(6):
            ax = rec['ally_xy'][i*2]; ay = rec['ally_xy'][i*2+1]
            if ax > 0 and ay > 0 and 0 <= ax < 32 and 0 <= ay < 32: occupied.add((ax, ay))

        # 2. 敌军固定位置
        for i in range(active_slots):
            eid = rec['enemy_ids'][i]
            if eid <= 0: continue
            ex = rec['enemy_xy'][i*2]; ey = rec['enemy_xy'][i*2+1]
            if ex >= 0 and 0 <= ex < 32 and 0 <= ey < 32:
                resolved_enemies[i] = (ex, ey); fixed_enemy_slots.add(i); occupied.add((ex, ey))

        # 3. 区域放置
        zone_pool = {z: list(cells) for z, cells in zone_cells.items()}
        def _pick_from_zone(zone):
            candidates = [(x,y) for (x,y) in zone_pool[zone] if (x,y) not in occupied]
            if not candidates: return None
            gx, gy = random.choice(candidates); occupied.add((gx, gy))
            zone_pool[zone].remove((gx, gy)); return (gx, gy)

        for zone in range(1, 6):
            for i in range(18):
                eid = rec['enemy_ids'][i]
                if eid <= 0 or i in resolved_enemies or i >= active_slots: continue
                ex = rec['enemy_xy'][i*2]
                if ex != -zone: continue
                pos = _pick_from_zone(zone)
                if pos: resolved_enemies[i] = pos
                else: enemy_zone_reqs.append((zone, i, eid))
            for i in range(6):
                ax = rec['ally_xy'][i*2]
                if ax != -zone: continue
                pos = _pick_from_zone(zone)
                if pos: resolved_allies[i] = pos

        # 4. 陷阱 + 宝物
        resolved_traps = {}; fixed_trap_indices = set(); trap_zone_reqs = []
        for i in range(28):
            ttype = rec['trap_type'][i]; sub_id = rec['trea_sub'][i] if i < 10 else 0
            is_trap = 1 <= ttype <= 6; is_trea = sub_id > 0 and i < 10
            if not is_trap and not is_trea: continue
            tx = rec['trap_xy'][i*2]; ty = rec['trap_xy'][i*2+1]
            if tx >= 0 and 0 <= tx < 32 and 0 <= ty < 32:
                if is_trap: resolved_traps[i] = (tx, ty); fixed_trap_indices.add(i)
                if is_trea: resolved_treas[i] = (tx, ty); fixed_trea_indices.add(i)
                occupied.add((tx, ty))
        for zone in range(1, 6):
            for i in range(28):
                ttype = rec['trap_type'][i]; sub_id = rec['trea_sub'][i] if i < 10 else 0
                is_trap = 1 <= ttype <= 6 and i not in resolved_traps
                is_trea = sub_id > 0 and i not in resolved_treas and i < 10
                if not is_trap and not is_trea: continue
                tx = rec['trap_xy'][i*2]
                if tx != -zone: continue
                pos = _pick_from_zone(zone)
                if is_trap:
                    if pos: resolved_traps[i] = pos
                    else: trap_zone_reqs.append((zone, i, ttype))
                if is_trea:
                    if pos: resolved_treas[i] = pos
                    else: trea_zone_reqs.append((zone, i, self._trea_label(rec, i)))

        return (resolved_enemies, resolved_treas, resolved_traps,
                enemy_zone_reqs, trea_zone_reqs, trap_zone_reqs,
                active_slots, fixed_enemy_slots, fixed_trea_indices, fixed_trap_indices,
                resolved_allies)

    def _redraw_scene(self, rerandomize=True):
        """重绘场景 (背景 + 网格 + 单位 + 宝物)
        游戏坐标体系: sub_42F9C8 等距投影, 所有元素(WSC背景/网格/单位)共享同一坐标系
        敌军/宝物位置按照 sub_431428 游戏规则解析: 固定位置 + 区域随机放置
        rerandomize=False 时复用缓存的解析位置 (拖拽时不重新随机)
        """
        gv = self.scene_gview; scene = gv.scene()
        scene.clear()
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]; zoom = self._preview_zoom
        tile_w = int(56 * zoom); tile_h = int(28 * zoom)
        bg_w = bg_h = 0

        # 背景
        if self.show_bg.isChecked() and HAS_PIL:
            wsc_idx = rec['map_id']
            if wsc_idx < 0 or wsc_idx >= len(self.wsc_offsets) - 1: wsc_idx = 0
            bg = self._load_wsc_background(wsc_idx)
            if bg:
                pixmap, bg_w, bg_h = bg
                scene.addPixmap(pixmap)

        warway = load_warway(self.warway_path, rec['map_id']) if self.warway_path else None

        if rerandomize:
            (resolved_enemies, resolved_treas, resolved_traps,
             enemy_zone_reqs, trea_zone_reqs, trap_zone_reqs,
             active_slots, fixed_enemy_slots, fixed_trea_indices, fixed_trap_indices,
             resolved_allies) = self._resolve_scene_placements(rec, warway)
            self._last_resolved_enemies = resolved_enemies
            self._last_resolved_treas = resolved_treas
            self._last_resolved_traps = resolved_traps
            self._last_resolved_allies = resolved_allies
            self._last_fixed_trea_indices = fixed_trea_indices
            self._last_fixed_trap_indices = fixed_trap_indices
            self._last_active_slots = active_slots
            self._last_fixed_enemy_slots = fixed_enemy_slots
            self._last_enemy_zone_reqs = enemy_zone_reqs
            self._last_trea_zone_reqs = trea_zone_reqs
            self._last_trap_zone_reqs = trap_zone_reqs
        resolved_enemies = self._last_resolved_enemies
        resolved_treas = self._last_resolved_treas
        resolved_traps = getattr(self, '_last_resolved_traps', {})
        resolved_allies = self._last_resolved_allies
        fixed_enemy_slots = getattr(self, '_last_fixed_enemy_slots', set())
        fixed_trea_indices = getattr(self, '_last_fixed_trea_indices', set())
        fixed_trap_indices = getattr(self, '_last_fixed_trap_indices', set())
        active_slots = getattr(self, '_last_active_slots', 18)
        enemy_zone_reqs = getattr(self, '_last_enemy_zone_reqs', [])
        trea_zone_reqs = getattr(self, '_last_trea_zone_reqs', [])
        trap_zone_reqs = getattr(self, '_last_trap_zone_reqs', [])

        # grid原点由 _grid_to_screen 固定使用游戏常量 (dword_4E7DF0=359, dword_4E7DF4=365, 偏移10/15)
        # 这些是PE .data段编译时常量, 不随WSC分辨率变化, 所有战场通用

        # ── 图层2: WarWay 网格 (sub_42F9C8 等距投影) ──
        if self.show_grid.isChecked() and warway:
            alpha_map = {'0':0, '25':64, '50':128, '75':192, '100':255}
            alpha_val = alpha_map.get(self.grid_alpha.currentText().rstrip('%'), 128)
            for gy in range(32):
                for gx in range(32):
                    raw = warway[gy*32+gx]; val = raw if raw < 128 else raw-256
                    # sub_4355C4/sub_431428: 地形值为 signed int8
                    sx, sy = self._grid_to_screen(gx, gy)
                    # sub_42F9C8: isometric diamond at (sx,sy) with half-width tile_w, half-height tile_h
                    pts = [QPointF(sx, sy-tile_h), QPointF(sx+tile_w, sy),
                           QPointF(sx, sy+tile_h), QPointF(sx-tile_w, sy)]
                    poly = QPolygonF(pts)
                    pen = QPen(QColor('#334422'), 1)
                    brush = QBrush(Qt.NoBrush)
                    if val == -1:  # WarWay -1 (0xFF) = 永久障碍
                        if not self.show_obstacle.isChecked(): continue
                        pen = QPen(QColor('#332211'), 1); brush = QBrush(QColor(85,51,34,alpha_val))
                    elif val < -1:  # WarWay < -1 = 临时障碍(sub_4355C4每回合+1直到0)
                        if not self.show_temp_obstacle.isChecked(): continue
                        pen = QPen(QColor('#443322'), 1); brush = QBrush(QColor(102,85,68,alpha_val))
                    elif val == 0:  # WarWay 0 = 普通地面
                        brush = QBrush(Qt.NoBrush)
                    else:  # WarWay 1-5 = 特殊区域 (PlaceReq), 各区域不同颜色
                        if val-1 < len(self.show_zone) and not self.show_zone[val-1].isChecked(): continue
                        zone_rgba = {1:(51,34,17,170,102,51),2:(17,34,51,51,102,170),3:(51,34,51,170,68,170),
                                     4:(17,51,34,51,170,102),5:(51,51,17,170,170,51)}
                        zc = zone_rgba.get(val, (34,68,51,68,170,68))
                        pen = QPen(QColor(zc[3],zc[4],zc[5]), 1)
                        brush = QBrush(QColor(zc[0],zc[1],zc[2],alpha_val))
                    item = scene.addPolygon(poly, pen, brush)
                    item.setData(0, (gx, gy, val))

        # ── 图层3: 宝物 (trea_xy offset 214-269, sub_431428) ──
        # 固定位置: 亮色; 区域放置: 暗色
        if self.show_trea.isChecked():
            for i, (gx, gy) in resolved_treas.items():
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(3, tile_h // 2)
                fill_c = QColor('#FF8C00') if i in fixed_trea_indices else QColor('#FFD700')
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addRect(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "固" if i in fixed_trea_indices else "随"
                t = scene.addText(tag); t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                label = self._trea_label(rec, i)
                if label:
                    lt = scene.addText(label); lt.setDefaultTextColor(fill_c)
                    lt.setFont(QFont('', max(8, int(10*zoom))))
                    lt.setPos(sx - lt.boundingRect().width()/2, sy - r - lt.boundingRect().height())
            # 宝物区域请求标记(无法解析的, 画布底部)
            if trea_zone_reqs:
                zr_x = 10
                by_zone = {}
                for z, i, lbl in trea_zone_reqs:
                    by_zone.setdefault(z, []).append(lbl)
                for zone, labels in sorted(by_zone.items()):
                    txt = f"Z{zone}:" + ",".join(labels)
                    t = scene.addText(txt); t.setDefaultTextColor(QColor('#FFD700'))
                    t.setFont(QFont('', max(9, int(11*zoom)))); t.setPos(zr_x, bg_h - 15)
                    zr_x += t.boundingRect().width() + 10

        # ── 图层3b: 陷阱 (sub_431428:283-323) ──
        if self.show_trap.isChecked():
            TRAP_COLORS = {1:'#FFD700',2:'#8B4513',3:'#4488FF',4:'#FF4444',5:'#228B22',6:'#FF69B4'}
            for i, (gx, gy) in resolved_traps.items():
                ttype = self._trap_type_at(rec, i)
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(3, tile_h // 2)
                fc = QColor(TRAP_COLORS.get(ttype, '#FF0000'))
                outline_c = QColor('white') if i in fixed_trap_indices else QColor('#888')
                pts = [QPointF(sx, sy-r), QPointF(sx-r, sy+r), QPointF(sx+r, sy+r)]
                scene.addPolygon(QPolygonF(pts), QPen(outline_c,1), QBrush(fc))
                tname = TRAP_NAMES_SHORT.get(ttype, '?') + '陷阱'
                tag = "固" if i in fixed_trap_indices else "随"
                t = scene.addText(tag); t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                lt = scene.addText(tname); lt.setDefaultTextColor(fc)
                lt.setFont(QFont('', max(8, int(10*zoom))))
                lt.setPos(sx - lt.boundingRect().width()/2, sy - r - lt.boundingRect().height())
            # 区域陷阱无法解析的, 在底部提示
            if trap_zone_reqs:
                zr_x = 10
                by_zone = {}
                for z, i, ttype in trap_zone_reqs:
                    by_zone.setdefault(z, []).append(f'{TRAP_NAMES_SHORT.get(ttype,"?")}{i}')
                for zone, labels in sorted(by_zone.items()):
                    txt = f'⚠Z{zone}陷阱:' + ','.join(labels)
                    t = scene.addText(txt); t.setDefaultTextColor(QColor('#FF4444'))
                    t.setFont(QFont('', max(9, int(11*zoom)))); t.setPos(zr_x, bg_h - 35)
                    zr_x += t.boundingRect().width() + 10

        # ── 图层4: 单位 (sub_431428 解析后位置) ──
        # 固定位置: 亮色; 区域放置: 暗色
        if self.show_units.isChecked():
            # 敌军 — 按 sub_431428 规则解析后的位置
            for i, (gx, gy) in resolved_enemies.items():
                eid = rec['enemy_ids'][i]; sx, sy = self._grid_to_screen(gx, gy)
                r = max(5, tile_h // 2)
                if i in fixed_enemy_slots: fill_c = QColor('#9932CC')
                else: fill_c = QColor('#cc3333')
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addEllipse(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "固" if i in fixed_enemy_slots else "随"
                t = scene.addText(tag); t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                name = self._enemy_name(eid)
                nt = scene.addText(name); nt.setDefaultTextColor(QColor('#BA55D3' if i in fixed_enemy_slots else '#ff6666'))
                nt.setFont(QFont('', max(8, int(10*zoom))))
                nt.setPos(sx - nt.boundingRect().width()/2, sy + r + 2)
            # 友军 — ally_xy [178-189] + 区域放置解析
            for i in range(6):
                if i in resolved_allies: gx, gy = resolved_allies[i]; fill_c = QColor('#3366cc')
                else:
                    ax = rec['ally_xy'][i*2]; ay = rec['ally_xy'][i*2+1]
                    if ax == 0 and ay == 0: continue
                    if ax < 0 or ay < 0 or ax >= 32 or ay >= 32: continue
                    gx, gy = ax, ay; fill_c = QColor('#228B22')
                sx, sy = self._grid_to_screen(gx, gy); r = max(5, tile_h // 2)
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addEllipse(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "随" if i in resolved_allies else "固"
                t = scene.addText(tag); t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
            # 敌军区域请求标记(无法解析的, 画布顶部)
            if enemy_zone_reqs:
                ezr_x = 10
                by_zone = {}
                for z, i, eid in enemy_zone_reqs:
                    by_zone.setdefault(z, []).append(self._enemy_name(eid))
                for zone, labels in sorted(by_zone.items()):
                    txt = f"Z{zone}:" + ",".join(labels)
                    t = scene.addText(txt); t.setDefaultTextColor(QColor('#ff6666'))
                    t.setFont(QFont('', max(9, int(11*zoom)))); t.setPos(ezr_x, 20)
                    ezr_x += t.boundingRect().width() + 10
            # 激活槽位提示
            if active_slots < 18:
                t = scene.addText(f"[激活槽位:0-{active_slots-1}]"); t.setDefaultTextColor(QColor('#ff6666'))
                t.setFont(QFont('', max(8, int(9*zoom)))); t.setPos(10, 40)
            # 强制出战角色名称 — must_chars [2-7]
            for i in range(6):
                cv = rec['must_chars'][i]
                if cv <= 0: continue
                name = self._char_name(cv-1)[:4]
                t = scene.addText(f"[{name}]"); t.setDefaultTextColor(QColor('#66ccff'))
                t.setFont(QFont('Microsoft YaHei UI', 9)); t.setPos(10 + i*60, 5)

        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-50, -50, 50, 50))

    def _find_unit_at(self, gx, gy):
        if self._current_idx < 0: return None
        resolved = getattr(self, '_last_resolved_enemies', {})
        for i, (egx, egy) in resolved.items():
            if egx == gx and egy == gy: return ('enemy', i)
        resolved_ally = getattr(self, '_last_resolved_allies', {})
        for i, (agx, agy) in resolved_ally.items():
            if agx == gx and agy == gy: return ('ally', i)
        rec = self.records[self._current_idx]
        for i in range(6):
            ax = rec['ally_xy'][i*2]; ay = rec['ally_xy'][i*2+1]
            if ax == gx and ay == gy: return ('ally', i)
        return None

    def _find_trea_at(self, gx, gy):
        """查找解析后宝物位置, 返回 (trea_index, is_fixed) 或 None"""
        if self._current_idx < 0: return None
        resolved = getattr(self, '_last_resolved_treas', {})
        fixed = getattr(self, '_last_fixed_trea_indices', set())
        for i, (tgx, tgy) in resolved.items():
            if tgx == gx and tgy == gy: return (i, i in fixed)
        return None

    def _find_trap_at(self, gx, gy):
        """查找解析后陷阱位置, 返回 (trap_index, is_fixed) 或 None"""
        if self._current_idx < 0: return None
        resolved = getattr(self, '_last_resolved_traps', {})
        fixed = getattr(self, '_last_fixed_trap_indices', set())
        for i, (tgx, tgy) in resolved.items():
            if tgx == gx and tgy == gy: return (i, i in fixed)
        return None

    def _on_tab_changed(self, index):
        """切换到场景标签页时自动刷新"""
        if index == 0 and self._current_idx >= 0:  # 场景预览是第0个tab
            self._redraw_scene()

    # ═══════════════════════════════════════════════════════════
    # SceneGraphicsView
    # ═══════════════════════════════════════════════════════════

class SceneGraphicsView(QGraphicsView):
    """自定义 QGraphicsView — 支持悬停信息、缩放、拖拽编辑、右键平移"""
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QBrush(QColor('#333333')))
        self.setMouseTracking(True)
        self._drag_target = None
        self._pan_start = None

    def mouseMoveEvent(self, event):
        """悬停显示网格信息 + 编辑拖拽 + 右键平移"""
        # 右键拖拽平移
        if self._pan_start is not None and event.buttons() & Qt.RightButton:
            delta = event.position().toPoint() - self._pan_start
            hbar = self.horizontalScrollBar(); vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            self._pan_start = event.position().toPoint()
            event.accept(); return

        # 编辑模式拖拽: 拦截所有左键 move, 不传给基类
        if self._drag_target and event.buttons() & Qt.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            g = self.editor._scene_to_grid(sp.x(), sp.y())
            if g:
                gx, gy = g
                d_utype, d_uidx = self._drag_target
                rec = self.editor.records[self.editor._current_idx]
                if d_utype == 'enemy':
                    rec['enemy_xy'][d_uidx*2] = gx; rec['enemy_xy'][d_uidx*2+1] = gy
                    self.editor._last_resolved_enemies[d_uidx] = (gx, gy)
                else:
                    rec['ally_xy'][d_uidx*2] = gx; rec['ally_xy'][d_uidx*2+1] = gy
                    self.editor._last_resolved_allies[d_uidx] = (gx, gy)
                self.editor._dirty = True
                self.editor._redraw_scene(rerandomize=False)
            event.accept(); return

        sp = self.mapToScene(event.position().toPoint())
        g = self.editor._scene_to_grid(sp.x(), sp.y())
        if g is None:
            self.editor.scene_info_var.setText(""); return
        gx, gy = g
        ed = self.editor; rec = ed.records[ed._current_idx] if ed._current_idx >= 0 else None

        # 悬停信息: 单位
        unit = ed._find_unit_at(gx, gy) if rec else None
        if unit:
            utype, uidx = unit
            if utype == 'enemy':
                eid = rec['enemy_ids'][uidx]; uname = ed._enemy_name(eid)
                orig_x = rec['enemy_xy'][uidx * 2]
                pos_tag = f"区域Z{abs(orig_x)}" if orig_x < 0 else "固定位置"
                ed.scene_info_var.setText(f"({gx},{gy}) 敌军:{uname} Lv.{rec['enemy_lv'][uidx]} [{pos_tag}]")
            else:
                ally_orig_x = rec['ally_xy'][uidx * 2]
                pos_tag = f"区域Z{abs(ally_orig_x)}" if ally_orig_x < 0 else "固定位置"
                ed.scene_info_var.setText(f"({gx},{gy}) 友军槽{uidx} [{pos_tag}]")
            return

        # 悬停信息: 宝物
        trea = ed._find_trea_at(gx, gy) if rec else None
        if trea:
            ti, is_fixed = trea
            label = ed._trea_label(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}"
            if label: ed.scene_info_var.setText(f"({gx},{gy}) 宝物#{ti} {label} [{type_tag}]")
            else: ed.scene_info_var.setText(f"({gx},{gy}) 宝物槽#{ti} (空) [{type_tag}]")
            return

        # 悬停信息: 陷阱
        trap = ed._find_trap_at(gx, gy) if rec else None
        if trap:
            ti, is_fixed = trap
            ttype = ed._trap_type_at(rec, ti)
            tname = TRAP_NAMES_SHORT.get(ttype, '?') + '陷阱'
            pmin, pmax = ed._trap_power_at(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}"
            ed.scene_info_var.setText(f"({gx},{gy}) 陷阱#{ti} {tname} 威力[{pmin},{pmax}] [{type_tag}]")
            return

        ed.scene_info_var.setText(f"({gx},{gy})")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.editor.edit_mode.isChecked():
            # 编辑模式: 完全自行处理左键, 不传给基类
            sp = self.mapToScene(event.position().toPoint())
            g = self.editor._scene_to_grid(sp.x(), sp.y())
            if g:
                unit = self.editor._find_unit_at(g[0], g[1])
                if unit: self._drag_target = unit
            event.accept(); return
        elif event.button() == Qt.RightButton:
            self._pan_start = event.position().toPoint()
            event.accept(); return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_target:
            self.editor._populate_fields(self.editor.records[self.editor._current_idx])
            self._drag_target = None
            event.accept(); return
        if event.button() == Qt.RightButton:
            self._pan_start = None
            event.accept(); return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """滚轮缩放 (不需要Ctrl)"""
        zooms = [0.25, 0.33, 0.5, 0.66, 0.75, 1.0]
        current = self.editor._preview_zoom
        if event.angleDelta().y() > 0:
            for z in zooms:
                if z > current: self.editor._preview_zoom = z; break
        else:
            for z in reversed(zooms):
                if z < current: self.editor._preview_zoom = z; break
        self.editor.zoom_combo.setCurrentText(f"{int(self.editor._preview_zoom*100)}%")
        self.editor._wsc_cache.clear()
        self.editor._redraw_scene()


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    editor = WarDataEditorV2()
    editor.show()
    sys.exit(app.exec())
