#!/usr/bin/env python3
"""
WarData.dat 可视化编辑器 (PySide6 — Godot 4.6 风格)
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
  [190-207] byte[18] enemy_delay — 敌方朝向: 0=随机, 1..4=四方向; sub_4307CC:242 / sub_444FD4:61
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

用法: python wardata_editor.py
"""

import os
import random
import re
import struct
import sys
from functools import partial
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar,
    QSpinBox, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsTextItem,
    QSizePolicy,
)
from PySide6.QtGui import (
    QColor, QFont, QIntValidator, QBrush, QPen, QPolygonF,
    QPainter, QPixmap, QImage, QAction, QKeySequence,
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTranslator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.dock_components import DockHeader
from editor_utils.ui_helpers import themed_question, make_fake_input, update_path_labels, confirm_close, themed_messagebox, EditorComboBox
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.task_runner import run_background, is_running
from editor_utils.lzss import lzss_decompress_stream as lzss_decompress
from editor_utils.lzss import lzss_decompress_dat
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.rgb565 import rgb565_to_rgba
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.shared_state import pick_tks_directory
from editor_utils.mod_exporter import (
    compute_crc32, generate_mod_json, pack_tksmod, ModMetadataDialog, safe_mod_filename,
    get_tksmod_info, read_tksmod, ModImportPreviewDialog, ModExportPreviewDialog,
)
from editor_utils.version import format_title
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput
from editor_utils.picker_dialogs import WarpcPickerDialog, ItemPickerDialog

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
SCENE_NAME_TKT_BASE = 300  # mat_editor: scene_id -> TKT 条目 ID
WAR_CMD_RE = re.compile(r'\bWar\s*\(\s*(\d+)\s*\)')

# 敌军特殊标志位 (enemy_flags, uint16)
ENEMY_FLAG_BITS = [
    (1,       "精英",    "生命值×2.5, 攻击力提升"),
    (2,       "特殊",    "特殊敌军标识"),
    (0x2000,  "阵营A",   ""),
    (0x4000,  "阵营B",   ""),
    (0x8000,  "特殊型",  ""),
]

# ═══════════════════════════════════════════════════════════
# RLE 字节对解压 (wardata 特有)
# ═══════════════════════════════════════════════════════════

RING_SIZE, RING_INIT, RING_INIT_VAL = 4096, 4078, 0x20

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


def load_warway_all(filepath: str) -> list:
    """加载完整 WarWay.dat 到内存, 返回 list[bytearray] (每条 1024 字节, 32x32网格)。

    网格编辑直接修改内存中的 bytearray, 保存时由 save_warway 写回。
    值语义 (sub_4355C4 + sub_431428):
      -1 (0xFF): 永久障碍 (sub_4355C4 更新循环跳过)
       0:        普通可通行地面
       1-5:      特殊区域/放置区
      <-1:       运行时临时障碍 (每回合+1直到0), 编辑器不产生此值
    """
    if not filepath or not os.path.exists(filepath):
        return []
    data = Path(filepath).read_bytes()
    count = len(data) // 1024
    return [bytearray(data[i * 1024:(i + 1) * 1024]) for i in range(count)]


def save_warway(filepath: str, grids: list):
    """保存全部 WarWay 网格到文件 (1024字节/条)"""
    buf = bytearray(len(grids) * 1024)
    for i, grid in enumerate(grids):
        off = i * 1024
        buf[off:off + 1024] = grid
    if os.path.exists(filepath):
        bak = filepath + '.bak'
        if not os.path.exists(bak):
            Path(filepath).rename(bak)
    Path(filepath).write_bytes(bytes(buf))


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


def build_record_bytes(rec) -> bytes:
    """根据 rec 的结构化字段重建 498 字节原始数据 (镜像 save_wardata 的单条逻辑)。

    以 _raw 为基底保留未引用/保留字节, 再覆盖所有已知字段。这样 _raw 始终与
    字段保持一致, MOD 导出的差异检测 (original[i]['_raw'] != cur['_raw']) 才能生效。
    """
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
    return bytes(chunk)


def save_wardata(filepath: str, records: list):
    buf = bytearray(len(records) * WAR_REC_SIZE)
    for rec in records:
        i = rec['index']
        off = i * WAR_REC_SIZE
        buf[off:off + WAR_REC_SIZE] = build_record_bytes(rec)
    if os.path.exists(filepath):
        bak = filepath + '.bak'
        if not os.path.exists(bak):
            Path(filepath).rename(bak)
    Path(filepath).write_bytes(bytes(buf))


def load_tkt(tkt_path: str) -> dict:
    """加载 TKT 文本 — 委托给 editor_utils.tkt_loader"""
    return load_tkt_simple(tkt_path, first_line_only=True)


def _scene_display_name(tkt: dict, scene_id: int) -> str:
    """SC.GRP 场景号 -> 地图名称 (TKT 条目 300 + scene_id)。"""
    if scene_id == -1:
        return "全局(所有场景)"
    txt = tkt.get(SCENE_NAME_TKT_BASE + scene_id, "")
    return txt.split('\n')[0].strip() if txt else f"场景{scene_id}"


def load_war_scene_names(game_dir: str, tkt: dict) -> dict:
    """WarData 战斗组序号 -> 触发战斗时所在 SC.GRP 场景名。

    关联链与 mat_editor 一致:
      TKMat 实体(d1=SC.GRP场景号) -> A/B/C 链 -> TKDefUnit
      -> DEFINE((f1<<16)|f0) -> TKD 脚本中的 War(战斗组ID)

    脚本没有引用该战斗组时, 回退到 type=16 随机战斗区实体
    (d52/d53/d54=三个战斗组ID), 其 d1 同样是触发场景。
    """
    if not game_dir:
        return {}

    mat_path = os.path.join(game_dir, 'TKMat.Dat')
    du_path = os.path.join(game_dir, 'TKDefUnit.dat')
    tkd_path = os.path.join(game_dir, 'TKD.dat')
    if not os.path.exists(mat_path) or not os.path.exists(du_path):
        return {}

    try:
        mat_dir = os.path.join(os.path.dirname(__file__), '..', 'mat_editor')
        if mat_dir not in sys.path:
            sys.path.insert(0, mat_dir)
        from mat_dat_io import load_mat
        records = load_mat(mat_path)
    except Exception:
        return {}

    defunits = {}
    try:
        with open(du_path, 'rb') as f:
            for i, fields in enumerate(struct.iter_unpack('<HHHHHHHH', f.read())):
                if fields[0] or fields[1]:
                    defunits[i] = (fields[0], fields[1], fields[6])
    except Exception:
        return {}

    define_map = {}
    if os.path.exists(tkd_path):
        try:
            from mat_text_codec import load_tkd, parse_defines
            defines, _ = parse_defines(load_tkd(tkd_path))
            define_map = {d['define_id']: d for d in defines}
        except Exception:
            define_map = {}

    script_scenes = {}
    random_scenes = {}
    define_war_ids = {}

    for rec in records:
        if not rec.get('_has_data'):
            continue
        scene_id = rec.get('d1', -1)

        if rec.get('d0') == 16:
            for di in (52, 53, 54):
                war_id = rec.get(f'd{di}', 0)
                if 0 <= war_id < WAR_REC_COUNT:
                    random_scenes.setdefault(war_id, set()).add(scene_id)

        if not define_map:
            continue
        seen_defunits = set()
        for head_di in (39, 40, 41):
            cur = rec.get(f'd{head_di}', 0)
            while cur > 0 and cur not in seen_defunits:
                seen_defunits.add(cur)
                du = defunits.get(cur)
                if du is None:
                    break
                define_id = (du[1] << 16) | du[0]
                if define_id not in define_war_ids:
                    war_ids = []
                    define = define_map.get(define_id)
                    if define:
                        for line in define.get('body_lines', []):
                            line = line.split('//', 1)[0]
                            for match in WAR_CMD_RE.finditer(line):
                                war_id = int(match.group(1))
                                if 0 <= war_id < WAR_REC_COUNT:
                                    war_ids.append(war_id)
                    define_war_ids[define_id] = war_ids
                for war_id in define_war_ids[define_id]:
                    script_scenes.setdefault(war_id, set()).add(scene_id)
                cur = du[2]

    names = {}
    for war_id in set(script_scenes) | set(random_scenes):
        scene_ids = script_scenes.get(war_id) or random_scenes.get(war_id)
        scene_names = []
        for scene_id in sorted(scene_ids):
            name = _scene_display_name(tkt, scene_id)
            if name not in scene_names:
                scene_names.append(name)
        names[war_id] = '、'.join(scene_names)
    return names


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


WARPC_FIELD_COUNT = 527
WARPC_REC_SIZE = 1054  # 527 × 2


def load_warpc_records(warpc_path: str):
    """加载 WarPC.dat，返回 list[dict]。
    每条: {'index': i, 'fields': [f0, f1, ...]}
    fields[0] = name_id, fields[1] = portrait
    """
    if not warpc_path or not os.path.exists(warpc_path):
        return []
    with open(warpc_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    # 兜底: LZSS 解压结果不对齐记录边界但原始文件对齐 → 未压缩 raw 数据
    if len(raw) % WARPC_REC_SIZE == 0 and (len(dec) == 0 or len(dec) % WARPC_REC_SIZE != 0):
        dec = raw
    if not dec or len(dec) % WARPC_REC_SIZE != 0:
        return []
    count = len(dec) // WARPC_REC_SIZE
    records = []
    for i in range(count):
        off = i * WARPC_REC_SIZE
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        records.append({'index': i, 'fields': list(vals)})
    return records


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


TKITEM_REC = 64  # 32 × int16
TKITEM_CNT = 600


def load_tkitem_records(tkitem_path: str, tkt: dict):
    """加载 TKItem.dat 完整记录，返回 list[dict]。
    每条: {'index', 'item_id', 'tab_code', 'name', 'desc', 'equip_type', 'icon', 'price'}
    """
    if not tkitem_path or not os.path.exists(tkitem_path):
        return []
    with open(tkitem_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    if len(raw) % TKITEM_REC == 0 and (len(dec) == 0 or len(dec) % TKITEM_REC != 0):
        dec = raw
    if not dec or len(dec) < TKITEM_REC:
        return []
    records = []
    for i in range(TKITEM_CNT):
        off = i * TKITEM_REC
        if off + TKITEM_REC > len(dec): break
        fields = struct.unpack_from('<' + 'h' * 32, dec, off)
        item_id = fields[0]
        tab_code = fields[1]
        name_id = fields[2]
        desc_id = fields[3]
        icon = fields[4]
        equip_type = fields[5]
        price = fields[31]
        if item_id <= 1:
            continue
        if name_id and name_id in tkt:
            name = tkt[name_id]
        elif name_id:
            name = f"Item#{item_id}"
        else:
            continue
        records.append({
            'index': i,
            'item_id': item_id,
            'tab_code': tab_code,
            'name': name,
            'desc': tkt.get(desc_id, "") if desc_id > 0 else "",
            'equip_type': equip_type,
            'icon': icon,
            'price': price,
        })
    return records


# ═══════════════════════════════════════════════════════════
# 陷阱名称常量
# ═══════════════════════════════════════════════════════════

TRAP_NAMES_MAP = {0: '0 无', 1: '1 山崩陷阱', 2: '2 泥沼陷阱', 3: '3 漩渦陷阱',
                  4: '4 火焰陷阱', 5: '5 滾木陷阱', 6: '6 瘴氣陷阱'}
TRAP_NAMES_SHORT = {1: '山崩', 2: '泥沼', 3: '漩渦', 4: '火焰', 5: '滾木', 6: '瘴氣'}

# ═══════════════════════════════════════════════════════════
# 主编辑器窗口
# ═══════════════════════════════════════════════════════════


# ── 战场地图绘制色 ──────────────────────────────────────────────────
# 领域语义色: 战场标记恒定配色, 不随 UI 主题变化 (阶段 2 豁免,
# 见 docs/PySide6样式体系整改方案.md)
TERRAIN_COLORS = [('障碍', '#553322'), ('临时障碍', '#665544'), ('区域1', '#aa6633'),
                  ('区域2', '#3366aa'), ('区域3', '#aa44aa'), ('区域4', '#33aa66'),
                  ('区域5', '#aaaa33')]
GRID_PEN = '#334422'          # 地形网格线 (普通)
OBSTACLE_PEN = '#332211'      # 永久障碍网格线
TEMP_OBSTACLE_PEN = '#443322' # 临时障碍网格线
TREASURE_FIXED = '#FF8C00'    # 固定宝箱: 橙
TREASURE_RANDOM = '#FFD700'   # 随机宝箱: 金
TRAP_COLORS = {1: '#FFD700', 2: '#8B4513', 3: '#4488FF',
               4: '#FF4444', 5: '#228B22', 6: '#FF69B4'}   # 陷阱类型色
TRAP_FALLBACK = '#FF0000'     # 未知陷阱类型
TRAP_TEXT_COLOR = '#FF4444'   # 陷阱标记文字
ENEMY_FIXED = '#9932CC'       # 固定敌人: 紫
ENEMY_RANDOM = '#cc3333'      # 随机敌人: 红
ENEMY_NAME_FIXED = '#BA55D3'  # 固定敌人名: 亮紫
ENEMY_NAME_RANDOM = '#ff6666' # 随机敌人名: 亮红
ALLY_FILL = '#3366cc'         # 我方已部署: 蓝
ALLY_FILL_ALT = '#228B22'     # 我方区域部署: 绿
ALLY_TEXT = '#66ccff'         # 我方名文字: 浅蓝
SELECT_OUTLINE = '#FFFF00'    # 选中多边形高亮: 黄
SCENE_BG = '#333333'          # 战场场景底色


class WarDataEditorV2(EditorMainWindow):
    EDITOR_KEY = "wardata_editor"
    DEFAULT_SIZE = (1600, 900)
    MIN_SIZE = (1100, 700)

    HELP_TEXT = (
        "功能: 编辑《三国群侠传》战场数据\n\n"
        "编辑内容:\n"
        "  · 敌方角色配置 (角色/等级/强化值/坐标)\n"
        "  · 我方出场配置 (坐标/朝向)\n"
        "  · 陷阱与宝箱设置\n"
        "  · 寻路网格数据 (WarWay.dat)\n"
        "  · 地图可视化预览\n\n"
        "特性:\n"
        "  · 32×32 网格地图可视化\n"
        "  · 深色/浅色主题切换")

    def _init_data(self):
        # 数据状态
        self.wardata_path = None
        self.warway_path = None
        self.wsc_grp_path = None
        self.wsc_idx_path = None
        self.tkt_path = None
        self.warpc_path = None
        self.warpc_names = {}
        self.warpc_records = []
        self.fa_path = None
        self.fa_sprites = []
        self.mu_path = None
        self.mu_sprites = []
        self._icon_pixmaps = {}
        self.tkitem_path = None
        self.tkitem_names = {}
        self.tkitem_names_by_id = {}
        self.tkitem_records = []
        self.records = []
        self.wsc_offsets = []
        self.tkt = {}
        self.war_scene_names = {}
        self._dirty = False
        self._warway_dirty = False
        self.warway_records = []  # 完整 WarWay.dat 内存网格 (list[bytearray], 编辑区格直接修改)
        self._current_idx = -1

        # 场景预览状态
        self._wsc_cache = {}
        self._wsc_res_cache = {}
        self._preview_zoom = 0.75
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

    def _after_build(self):
        self._set_edit_enabled(False)
        self._apply_theme()

    # ── 主题 ──
    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        self._update_paths()

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._update_paths()

    def _update_paths(self):
        update_path_labels([
            (self.lbl_wardata, self.wardata_path, 'WarData'),
            (self.lbl_warway, self.warway_path, 'WarWay'),
            (self.lbl_tkt, self.tkt_path, 'TKT'),
            (self.lbl_wsc, self.wsc_grp_path, 'WSC'),
            (self.lbl_fa, self.fa_path, 'Fa.JVG'),
            (self.lbl_mu, self.mu_path, 'Mu.JVG'),
        ], self._is_dark)
        extra_parts = []
        if self.warpc_path and os.path.exists(self.warpc_path):
            extra_parts.append(f"WarPC: {len(self.warpc_names)}人")
        if self.tkitem_path and os.path.exists(self.tkitem_path):
            extra_parts.append(f"TKItem: {len(self.tkitem_names)}件")
        if extra_parts:
            self.lbl_extra.setProperty("status", "loaded")
            self.lbl_extra.setText(" | ".join(extra_parts))
        else:
            self.lbl_extra.setProperty("status", "missing")
            self.lbl_extra.setText("(WarPC/TKItem: 未加载)")
        self.lbl_extra.style().unpolish(self.lbl_extra)
        self.lbl_extra.style().polish(self.lbl_extra)

    # ── UI 构建 ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # 菜单栏
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("加载 TKS 目录", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("另存为", self._save_as)
        fm.addAction("导出为 MOD (.tksmod)", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新增战场", QKeySequence("Ctrl+N"), self._new_battle)
        em.addAction("复制当前记录", self._copy_record)
        em.addAction("删除当前记录", self._delete_record)

        self.add_theme_submenu(mb)

        self.add_help_menu(mb)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_entry = SearchInput("输入关键字过滤")
        self.search_entry.setMinimumWidth(160)
        self.search_entry.textChanged.connect(self._apply_filter)
        self.search_entry.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self.search_entry)
        toolbar.addWidget(QPushButton("搜索", clicked=self._apply_filter))
        toolbar.addWidget(QPushButton("清除", clicked=self._clear_filter))
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("重新加载", clicked=self._reload))
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("应用修改", clicked=self._apply_and_refresh))
        toolbar.addWidget(QPushButton("切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()
        self.status_var = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        toolbar.addWidget(self.status_var)
        main_layout.addLayout(toolbar)

        # 主 Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # 左侧：战斗列表
        self.table = AdaptiveTableWidget(
            0, 9,
            stretch_columns={1, 7},
            minimum_widths=[58, 120, 140, 52, 52, 52, 76, 140, 68],
            row_height=40,
        )
        self.table.setHorizontalHeaderLabels(["序号", "地图名称", "分辨率", "敌军数", "宝物数", "陷阱数", "固定/随机", "参战人物", "参数"])
        # 左侧列表在默认 1600px 窗口中约占 860px。序号/分辨率保留足够内容宽度，
        # 剩余可变空间分配给地图名称和最容易截断的“参战人物”列。
        self.table.setMinimumWidth(760)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        splitter.addWidget(self.table)

        # 右侧：编辑面板
        right = QWidget()
        right.setObjectName("WarDataEditorRightPanel")
        # 右侧标签页中的明细表有较大的 sizeHint，若沿用该建议尺寸，QSplitter
        # 会把初始空间优先分给右侧，导致左侧退回最小宽度。让分隔条按设定的
        # 初始比例分配空间，明细内容不足时由各自表格处理横向滚动。
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.setSpacing(4)
        self.tabs = EditorTabWidget(
            flat=True,
            object_name="WarDataEditorTabs",
        )
        self._build_scene_tab()
        self._build_enemy_tab()
        self._build_ally_tab()
        self._build_drops_traps_tab()
        self._build_params_tab()
        self._build_allparams_tab()
        self._link_params_tabs()  # 双向同步 pvars/apvars 重叠字段, 防止 apply 时互相覆盖
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        # 默认 1600x900 窗口（扣除边距与分隔条后内容区约 1570px）下，
        # 左侧列表保持 ~860px 初始宽度，其余空间给右侧编辑面板。
        # 参战人物列拉伸受上限钳制，用户拖大分隔条后超出部分尾部留白。
        splitter.setSizes([860, 710])
        # 切换到场景标签页时自动刷新
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4, 2, 4, 2)
        self.lbl_wardata = QLabel()
        self.lbl_warway = QLabel()
        self.lbl_wsc = QLabel()
        self.lbl_tkt = QLabel()
        self.lbl_fa = QLabel()
        self.lbl_mu = QLabel()
        self.lbl_extra = QLabel()
        for w in [self.lbl_wardata, self.lbl_warway, self.lbl_wsc, self.lbl_tkt, self.lbl_fa, self.lbl_mu, self.lbl_extra]:
            path_layout.addWidget(w)
            path_layout.addSpacing(15)
        path_layout.addStretch()
        main_layout.addLayout(path_layout)

    def _set_edit_enabled(self, enabled):
        self.table.setEnabled(enabled)

    # ── 图标辅助 ──
    def _get_icon_pixmap(self, icon_val, size=(36, 36)):
        """将物品 icon 值转为 QPixmap (委托给 jvg_loader.get_sprite_pixmap)"""
        return get_sprite_pixmap(self.mu_sprites, icon_val, size, self._icon_pixmaps)

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

    def _get_battle_map_name(self, battle_id):
        """战斗组序号 -> 触发该战斗的 SC.GRP 场景名。"""
        return self.war_scene_names.get(battle_id, "未关联")

    def _trea_detail_str(self, rec):
        fixed = random_trea = 0
        for i in range(10):
            if rec['trea_sub'][i] <= 0: continue
            tx = rec['trap_xy'][i * 2]
            if tx >= 0: fixed += 1
            else: random_trea += 1
        return f"固{fixed}/随{random_trea}" if fixed or random_trea else "-"

    def _get_warway_grid(self, map_id):
        """获取指定 map_id 的可变 WarWay 网格 (bytearray, 32x32)。

        优先使用内存中的 warway_records (支持编辑); 若未加载则回退到磁盘读取 (只读)。
        返回 bytearray 或 None。网格索引: grid[gy*32+gx], signed int8 语义。
        """
        if self.warway_records:
            if 0 <= map_id < len(self.warway_records):
                return self.warway_records[map_id]
            return None
        # 回退: 未加载完整 WarWay 时从磁盘读单条 (只读 bytes, 不可编辑)
        data = load_warway(self.warway_path, map_id) if self.warway_path else None
        return bytearray(data) if data else None

    # ── 列表 ──
    def _tree_row_vals(self, rec):
        """计算左侧列表一行的显示文本 (供 _fill_tree_row 和 _update_tree_row 共用)"""
        enemy_count = sum(1 for eid in rec['enemy_ids'] if eid > 0)
        trea_count = sum(1 for i in range(10) if rec['trea_sub'][i] > 0)
        trap_count = sum(1 for i in range(28) if 1 <= self._trap_type_at(rec, i) <= 6)
        trea_detail = self._trea_detail_str(rec)
        mid = rec['map_id']
        res = self._get_wsc_resolution(mid)
        map_name = self._get_battle_map_name(rec['index'])
        resolution = f"{res[0]}x{res[1]}" if res else "-"
        enemy_names = []
        seen = set()
        for eid in rec['enemy_ids']:
            if eid > 0 and eid not in seen:
                seen.add(eid)
                enemy_names.append(self._enemy_name(eid))
        if enemy_names:
            names = [n[:4] for n in enemy_names[:3]]
            chars_info = ','.join(names)
            if len(enemy_names) > 3: chars_info += '等'
        else:
            chars_info = '-'
        flags = rec['flags']
        flag_parts = []
        if flags & 2: flag_parts.append('续')
        if flags & 4: flag_parts.append('随')
        flags_info = ','.join(flag_parts) if flag_parts else '-'
        return [str(rec['index']), map_name, resolution, str(enemy_count),
                str(trea_count), str(trap_count), trea_detail, chars_info, flags_info]

    def _fill_tree_row(self, rec):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for c, v in enumerate(self._tree_row_vals(rec)):
            item = QTableWidgetItem(v)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, c, item)

    def _update_tree_row(self, idx):
        """原地刷新左侧列表指定行的显示 (应用修改后调用, 保持选中状态不变)"""
        if idx < 0 or idx >= self.table.rowCount(): return
        rec = self.records[idx]
        self.table.blockSignals(True)
        for c, v in enumerate(self._tree_row_vals(rec)):
            item = self.table.item(idx, c)
            if item:
                item.setText(v)
            else:
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(idx, c, item)
        self.table.blockSignals(False)

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
        d = pick_tks_directory(self)
        if not d: return
        wd = os.path.join(d, 'WarData.dat')
        ww = os.path.join(d, 'WarWay.dat')
        wsc_g = os.path.join(d, 'WSC.GRP')
        wsc_i = os.path.join(d, 'WSC.IDX')
        tkt = os.path.join(d, 'TKT.dat')
        warpc = os.path.join(d, 'WarPC.dat')
        tkitem = os.path.join(d, 'TKItem.dat')
        missing = []
        for p, n in [(wd,'WarData.dat'),(ww,'WarWay.dat'),(wsc_g,'WSC.GRP'),
                      (wsc_i,'WSC.IDX'),(tkt,'TKT.dat'),(warpc,'WarPC.dat'),(tkitem,'TKItem.dat')]:
            if not os.path.exists(p): missing.append(n)
        if missing:
            if 'WarData.dat' in missing:
                QMessageBox.critical(self, "错误", "缺少必要文件 WarData.dat")
                return
            QMessageBox.warning(self, "警告", "以下文件未找到:\n  " + "\n  ".join(missing))
        self.wardata_path = wd
        self.warway_path = ww if os.path.exists(ww) else None
        self.wsc_grp_path = wsc_g if os.path.exists(wsc_g) else None
        self.wsc_idx_path = wsc_i if os.path.exists(wsc_i) else None
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self.warpc_path = warpc if os.path.exists(warpc) else None
        self.tkitem_path = tkitem if os.path.exists(tkitem) else None
        fa_path = os.path.join(d, 'Fa.JVG')
        self.fa_path = fa_path if os.path.exists(fa_path) else None
        self.records = load_wardata(self.wardata_path)
        self.wsc_offsets = load_wsc_idx(self.wsc_idx_path) if self.wsc_idx_path else []
        self.warway_records = load_warway_all(self.warway_path) if self.warway_path else []
        self.tkt = load_tkt(self.tkt_path) if self.tkt_path else {}
        self.war_scene_names = load_war_scene_names(d, self.tkt)
        self.warpc_names = load_warpc_names(self.warpc_path, self.tkt) if self.warpc_path else {}
        self.warpc_records = load_warpc_records(self.warpc_path) if self.warpc_path else []
        self.fa_sprites = load_mu_sprites(self.fa_path) if self.fa_path else []
        mu_path = os.path.join(d, 'Mu.JVG')
        self.mu_path = mu_path if os.path.exists(mu_path) else None
        self.mu_sprites = load_mu_sprites(self.mu_path) if self.mu_path else []
        self._icon_pixmaps.clear()
        if self.tkitem_path:
            self.tkitem_names, self.tkitem_names_by_id = load_tkitem_names(self.tkitem_path, self.tkt)
            self.tkitem_records = load_tkitem_records(self.tkitem_path, self.tkt)
        else:
            self.tkitem_names, self.tkitem_names_by_id, self.tkitem_records = {}, {}, []
        self._wsc_cache.clear()
        self._wsc_res_cache.clear()
        self._refresh_tree()
        self._set_edit_enabled(True)
        self._dirty = False
        self._warway_dirty = False
        self._update_paths()
        self.status_var.setText(f"已加载 {len(self.records)} 场战斗")

    def _save(self):
        if not self.wardata_path or not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        msg = f"保存 {len(self.records)} 条到:\n{self.wardata_path}\n\n原文件将被覆盖(生成.bak)."
        if self._warway_dirty and self.warway_path and self.warway_records:
            msg += f"\n\n检测到 WarWay 网格修改, 将一并保存到:\n{self.warway_path}"
        if themed_question(self, "确认保存", msg) != QMessageBox.Yes: return
        self._apply_current_edit()
        save_wardata(self.wardata_path, self.records)
        self._dirty = False
        # WarWay 网格保存 (仅在已修改且已加载完整网格时)
        if self._warway_dirty and self.warway_path and self.warway_records:
            save_warway(self.warway_path, self.warway_records)
            self._warway_dirty = False
        self.status_var.setText("已保存")

    def _save_as(self):
        fp, _ = QFileDialog.getSaveFileName(self, "另存 WarData.dat", "", "DAT files (*.dat);;All (*.*)")
        if fp:
            self._apply_current_edit()
            save_wardata(fp, self.records)
            self.wardata_path = fp
            self._dirty = False
            self.status_var.setText(f"已另存为 {fp}")

    def _apply_current_edit(self):
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        self._apply_params_tab(rec)
        self._apply_allparams_tab(rec)
        self._apply_enemy_tab(rec)
        self._apply_ally_tab(rec)
        self._apply_drops_tab(rec)
        self._apply_trap_tab(rec)
        self._sync_raw(rec)

    def _sync_raw(self, rec):
        """根据结构化字段重建 _raw, 保证 _raw 与字段一致。

        关键: MOD 导出用 _raw 字节比对检测差异, 若 _raw 不同步则修改现有记录
        无法被检测到 (历史 BUG)。保存 WarData 时也依赖 _raw 一致性。
        """
        rec['_raw'] = build_record_bytes(rec)

    def _sync_all_raw(self):
        """同步全部记录的 _raw — MOD 导出前调用, 确保差异检测覆盖所有记录。

        单元格直接编辑 (敌军表/宝物表/场景拖拽) 会修改 rec 字段但不经过 _apply_*,
        因此导出前需全量同步 _raw, 否则这些记录的修改不会被检测到。
        """
        for rec in self.records:
            self._sync_raw(rec)

    def _apply_filter(self):
        query = self.search_entry.text()
        self.table.setRowCount(0)
        for rec in self.records:
            enemy_names = []
            seen = set()
            for eid in rec['enemy_ids']:
                if eid > 0 and eid not in seen:
                    seen.add(eid)
                    enemy_names.append(self._enemy_name(eid))
            char_names = ','.join(enemy_names) if enemy_names else ''
            if not search_match(query, rec['index'], rec['map_id'],
                                self._get_battle_map_name(rec['index']), char_names):
                continue
            self._fill_tree_row(rec)

    def _clear_filter(self):
        self.search_entry.clear()
        self._refresh_tree()

    def _reload(self):
        if not self.wardata_path: return
        if is_running(getattr(self, '_load_worker', None)): return
        wardata_path, warway_path = self.wardata_path, self.warway_path
        tkt_path, warpc_path, tkitem_path = self.tkt_path, self.warpc_path, self.tkitem_path

        # 后台线程: 全部数据文件 IO/解码 (P3-3), UI 刷新在 _on_load_success
        def work(w):
            records = load_wardata(wardata_path)
            warway_records = load_warway_all(warway_path) if warway_path else []
            tkt = {}
            war_scene_names = {}
            warpc_names, warpc_records = {}, []
            tkitem_names, tkitem_names_by_id = {}, {}
            tkitem_records = []
            if tkt_path:
                tkt = load_tkt(tkt_path)
                if warpc_path:
                    warpc_names = load_warpc_names(warpc_path, tkt)
                    warpc_records = load_warpc_records(warpc_path)
                if tkitem_path:
                    tkitem_names, tkitem_names_by_id = load_tkitem_names(tkitem_path, tkt)
                    tkitem_records = load_tkitem_records(tkitem_path, tkt)
            war_scene_names = load_war_scene_names(os.path.dirname(wardata_path), tkt)
            return (records, warway_records, tkt, war_scene_names, warpc_names, warpc_records,
                    tkitem_names, tkitem_names_by_id, tkitem_records)

        self._load_worker = run_background(
            self, work,
            on_success=self._on_load_success,
            on_error=self._on_load_error)

    def _on_load_success(self, result):
        (records, warway_records, tkt, war_scene_names, warpc_names, warpc_records,
         tkitem_names, tkitem_names_by_id, tkitem_records) = result
        self.records = records
        self.warway_records = warway_records
        self.tkt = tkt
        self.war_scene_names = war_scene_names
        self.warpc_names = warpc_names
        self.warpc_records = warpc_records
        self.tkitem_names = tkitem_names
        self.tkitem_names_by_id = tkitem_names_by_id
        self.tkitem_records = tkitem_records
        self._icon_pixmaps.clear()
        self._refresh_tree()
        self._dirty = False
        self._warway_dirty = False
        self.status_var.setText("已重新加载")

    def _on_load_error(self, err_msg):
        QMessageBox.critical(self, "加载失败", err_msg)
        self.status_var.setText("加载失败")

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
            'battle_turn_limit':0,'_raw':bytearray(WAR_REC_SIZE)}
        self.records.append(rec)
        self._refresh_tree()
        self._dirty = True
        self.status_var.setText(f"已新增战场 #{new_idx}")
        # 自动选中新记录并填充编辑面板, 用户可立即编辑
        self.table.selectRow(new_idx)

    def _copy_record(self):
        if self._current_idx < 0: return
        import copy
        src = self.records[self._current_idx]
        new_idx = len(self.records)
        rec = copy.deepcopy(src)
        rec['index'] = new_idx
        rec['battle_id'] = new_idx
        rec['_raw'] = bytearray(src['_raw'])
        self.records.append(rec)
        self._refresh_tree()
        self._dirty = True
        self.status_var.setText(f"已复制 #{self._current_idx} -> #{new_idx}")
        self.table.selectRow(new_idx)

    def _delete_record(self):
        if self._current_idx < 0: return
        if themed_question(self,"确认删除",f"删除战场 #{self._current_idx}?") != QMessageBox.Yes: return
        del self.records[self._current_idx]
        for i, rec in enumerate(self.records):
            rec['index'] = i
        self._current_idx = -1
        self._refresh_tree()
        self._dirty = True
        self.status_var.setText("已删除战场")
        # 清除编辑面板 (无可选记录时禁用)
        if self.records:
            self.table.selectRow(0)
        else:
            self._set_edit_enabled(False)

    def _extra_help_actions(self):
        """帮助菜单专属项: 字段参考 (挂在"帮助说明"之后)。"""
        return [("字段参考", self._show_field_ref)]

    def _show_field_ref(self):
        themed_messagebox(self, QMessageBox.Information, "字段参考",
            "WarData.dat 战场数据字段参考\n\n"
            "基本设置:\n"
            "  [0] 标志位        [2-7] 必出角色      [30] 名称编号      [32] 地图编号\n\n"
            "敌方配置:\n"
            "  [34-69] 敌方角色 (最多18个)\n"
            "  [70-87] 敌方等级        [88-105] 敌方强化值\n"
            "  [106-141] 等级波动范围  [142-177] 敌方坐标\n"
            "  [190-207] 敌方朝向 (0随机, 1~4四方向)  [442-477] 敌方标志\n\n"
            "我方配置:\n"
            "  [178-189] 我方坐标      [208-213] 我方朝向\n\n"
            "陷阱与宝箱:\n"
            "  [214-269] 陷阱坐标 (最多28个)\n"
            "  [270-325] 陷阱威力      [386-441] 陷阱类型\n"
            "  [326-345] 宝箱子类型×10\n"
            "  [346-385] 宝箱数量×20\n\n"
            "其他:\n"
            "  [478] 等级下限  [480] 等级上限  [482] 回合限制\n\n"
            "WarWay.dat 寻路数据:\n"
            "  每条 1024 字节, 32×32 网格\n"
            "  -1 = 障碍物 (不可通行)\n"
            "   0 = 可通行区域\n"
            "  1~5 = 不同区域编号")

    # 关于信息: 编辑器基于 TKS.exe 反编译/逆向工程分析 (原始依据已从用户可见文本中移除)

    def _build_warway_diff_json(self, ref_dir):
        """构建 WarWay.dat 差异 JSON (与 ref_dir/WarWay.dat 比对)。

        WarWay.dat 是 1024 字节/条的 32x32 int8 地形网格。差异格式与统一 DAT 一致:
        field_type="int8", field_count=1024, fields 用 f0..f1023 引用每个网格字节。
        新增战场改 map_id 后必须导出对应 WarWay 网格, 否则游戏 sub_431428 的 mc>0
        断言失败 (战场记录要求单位放在区域N, 但地图里没有区域N的格)。
        返回 dict 或 None (无差异/无 WarWay 数据)。
        """
        if not self.warway_records:
            return None
        ref_ww = os.path.join(ref_dir, "WarWay.dat")
        if not os.path.isfile(ref_ww):
            return None
        try:
            orig_ww = load_warway_all(ref_ww)
        except Exception:
            return None
        modified = []
        for i in range(min(len(orig_ww), len(self.warway_records))):
            cur = self.warway_records[i]
            ref = orig_ww[i]
            if bytes(cur) == bytes(ref):
                continue
            # 只记录变化的格子 (f0..f1023 = 逐格 int8), 减小 MOD 体积
            fields = {}
            for j in range(1024):
                if cur[j] != ref[j]:
                    v = cur[j]
                    # int8 范围: 0x80-0xFF 视为负数 (-128..-1), 与游戏 sub_42FE70 一致
                    if v >= 0x80:
                        v -= 0x100
                    fields[f"f{j}"] = v
            modified.append({"index": i, "fields": fields})
        appended = []
        for i in range(len(orig_ww), len(self.warway_records)):
            cur = self.warway_records[i]
            fields = {}
            for j in range(1024):
                v = cur[j]
                if v >= 0x80:
                    v -= 0x100
                if v != 0:  # 跳过默认0, 减小体积
                    fields[f"f{j}"] = v
            appended.append({"index": i, "fields": fields})
        if not modified and not appended:
            return None
        crc = compute_crc32(ref_ww)
        return {"target": "WarWay.dat", "record_size": 1024, "field_type": "int8",
                "field_count": 1024, "original_count": len(orig_ww),
                "original_crc32": crc, "modified": modified, "appended": appended}

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件（WarData 完整记录级差异）"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # WarData 使用完整记录的 _raw 字节比对
        # 重新加载原始数据进行比对
        if not self.wardata_path:
            QMessageBox.warning(self, "错误", "无法确定原始文件路径")
            return
        original = load_wardata(self.wardata_path)
        self._apply_current_edit()
        self._sync_all_raw()

        modified = []
        for i in range(min(len(original), len(self.records))):
            if original[i]['_raw'] != self.records[i]['_raw']:
                # 记录所有非零/变化的字段
                rec = self.records[i]
                fields = {}
                for key in ['flags', 'battle_name_id', 'map_id', 'battle_turn_limit',
                            'lv_spread_lo', 'lv_spread_hi']:
                    fields[key] = rec[key]
                for key in ['must_chars', 'enemy_ids', 'enemy_lv', 'enemy_power',
                            'enemy_lv_range', 'enemy_xy', 'ally_xy', 'enemy_delay',
                            'ally_facing', 'trap_xy', 'trap_pwr', 'trea_sub',
                            'trea_quant', 'trap_type', 'enemy_flags']:
                    fields[key] = rec[key]
                modified.append({"index": i, "fields": fields})

        appended = []
        for i in range(len(original), len(self.records)):
            rec = self.records[i]
            fields = {}
            for key in ['flags', 'battle_name_id', 'map_id', 'battle_turn_limit',
                        'lv_spread_lo', 'lv_spread_hi']:
                fields[key] = rec[key]
            for key in ['must_chars', 'enemy_ids', 'enemy_lv', 'enemy_power',
                        'enemy_lv_range', 'enemy_xy', 'ally_xy', 'enemy_delay',
                        'ally_facing', 'trap_xy', 'trap_pwr', 'trea_sub',
                        'trea_quant', 'trap_type', 'enemy_flags']:
                fields[key] = rec[key]
            appended.append({"index": i, "fields": fields})

        # WarWay 地形网格差异 (新增战场改 map_id 后必须随 MOD 导出, 否则游戏找不到地图崩溃)
        warway_json = self._build_warway_diff_json(os.path.dirname(self.wardata_path))

        if not modified and not appended and not warway_json:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        crc = compute_crc32(self.wardata_path)
        data_json = {
            "target": "WarData.dat", "record_size": WAR_REC_SIZE,
            "field_type": "structured", "original_count": len(original),
            "original_crc32": crc, "modified": modified, "appended": appended
        }
        data_files = {"data/WarData.dat.json": data_json}
        mod_targets = [{"file": "data/WarData.dat.json", "target": "WarData.dat"}]
        if warway_json:
            data_files["data/WarWay.dat.json"] = warway_json
            mod_targets.append({"file": "data/WarWay.dat.json", "target": "WarWay.dat"})
        mod_json = generate_mod_json(metadata, mod_targets)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            ww_msg = f"\nWarWay 地图: {warway_json.get('modified', 0) if warway_json else 0} 条" if warway_json else ""
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} (修改{len(modified)}条, 追加{len(appended)}条)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n修改: {len(modified)} 条\n追加: {len(appended)} 条{ww_msg}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录的 WarData.dat 进行差异比对"""
        if not self.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        self._apply_current_edit()
        self._sync_all_raw()

        # 预构建当前记录（WarData 每条记录以 _raw 为标识）
        current_records = [r for r in self.records]

        def _compute_stats(ref_dir):
            ref_path = os.path.join(ref_dir, "WarData.dat")
            if not os.path.isfile(ref_path):
                return {"valid": False, "error": "目录中未找到 WarData.dat"}
            try:
                original = load_wardata(ref_path)
            except Exception:
                return {"valid": False, "error": "WarData.dat 解析失败"}
            modified = 0
            for i in range(min(len(original), len(current_records))):
                if original[i]['_raw'] != current_records[i]['_raw']:
                    modified += 1
            appended = max(0, len(current_records) - len(original))
            targets = []
            if modified or appended:
                targets.append({"name": "WarData.dat",
                    "modified": modified, "appended": appended, "deleted": 0})
            # 统计 WarWay 差异
            ref_ww = os.path.join(ref_dir, "WarWay.dat")
            if os.path.isfile(ref_ww):
                try:
                    orig_ww = load_warway_all(ref_ww)
                    ww_mod = 0
                    for i in range(min(len(orig_ww), len(self.warway_records))):
                        if bytes(orig_ww[i]) != bytes(self.warway_records[i]):
                            ww_mod += 1
                    ww_app = max(0, len(self.warway_records) - len(orig_ww))
                    if ww_mod or ww_app:
                        targets.append({"name": "WarWay.dat",
                            "modified": ww_mod, "appended": ww_app, "deleted": 0})
                except Exception:
                    pass
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=os.path.dirname(self.wardata_path) if self.wardata_path else "",
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        ref_path = os.path.join(ref_dir, "WarData.dat")
        if not os.path.isfile(ref_path):
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 WarData.dat")
            return

        original = load_wardata(ref_path)

        modified = []
        for i in range(min(len(original), len(self.records))):
            if original[i]['_raw'] != self.records[i]['_raw']:
                rec = self.records[i]
                fields = {}
                for key in ['flags', 'battle_name_id', 'map_id', 'battle_turn_limit', 'lv_spread_lo', 'lv_spread_hi']:
                    fields[key] = rec[key]
                for key in ['must_chars', 'enemy_ids', 'enemy_lv', 'enemy_power', 'enemy_lv_range',
                            'enemy_xy', 'ally_xy', 'enemy_delay', 'ally_facing', 'trap_xy', 'trap_pwr',
                            'trea_sub', 'trea_quant', 'trap_type', 'enemy_flags']:
                    fields[key] = rec[key]
                modified.append({"index": i, "fields": fields})
        appended = []
        for i in range(len(original), len(self.records)):
            rec = self.records[i]
            fields = {}
            for key in ['flags', 'battle_name_id', 'map_id', 'battle_turn_limit', 'lv_spread_lo', 'lv_spread_hi']:
                fields[key] = rec[key]
            for key in ['must_chars', 'enemy_ids', 'enemy_lv', 'enemy_power', 'enemy_lv_range',
                        'enemy_xy', 'ally_xy', 'enemy_delay', 'ally_facing', 'trap_xy', 'trap_pwr',
                        'trea_sub', 'trea_quant', 'trap_type', 'enemy_flags']:
                fields[key] = rec[key]
            appended.append({"index": i, "fields": fields})

        if not modified and not appended:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        crc = compute_crc32(ref_path)
        data_json = {"target": "WarData.dat", "record_size": WAR_REC_SIZE, "field_type": "structured",
            "original_count": len(original), "original_crc32": crc, "modified": modified, "appended": appended}
        # WarWay 地形网格差异 (与 WarData 同目录的 WarWay.dat 比对)
        warway_json = self._build_warway_diff_json(ref_dir)
        data_files = {"data/WarData.dat.json": data_json}
        mod_targets = [{"file": "data/WarData.dat.json", "target": "WarData.dat"}]
        if warway_json:
            data_files["data/WarWay.dat.json"] = warway_json
            mod_targets.append({"file": "data/WarWay.dat.json", "target": "WarWay.dat"})
        mod_json = generate_mod_json(metadata, mod_targets)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            ww_msg = f"\nWarWay 地图: {warway_json.get('modified', 0) if warway_json else 0} 条" if warway_json else ""
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n修改: {len(modified)} 条\n追加: {len(appended)} 条{ww_msg}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到 WarData 编辑器"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        if "WarData.dat" not in info.get("targets", []):
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 WarData.dat 的数据\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=os.path.dirname(self.wardata_path) if self.wardata_path else "")
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        ref_path = os.path.join(ref_dir, "WarData.dat")
        if not os.path.isfile(ref_path):
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 WarData.dat")
            return

        # 加载原始数据
        try:
            ref_records = load_wardata(ref_path)
        except Exception as e:
            QMessageBox.warning(self, "参考文件无效", str(e))
            return

        # 解析 MOD 差异数据
        mod_json, data_files = read_tksmod(fp)
        if mod_json is None:
            QMessageBox.warning(self, "导入失败", "无法解析 MOD 文件")
            return

        # 找到 WarData.dat 的差异数据
        diff_data = None
        for comp in mod_json.get("components", []):
            if comp.get("target", "").lower() == "wardata.dat":
                internal = comp.get("file", "")
                if internal in data_files:
                    diff_data = data_files[internal]
                    break
        if diff_data is None:
            QMessageBox.warning(self, "导入失败", "MOD 中找不到 WarData.dat 的差异数据")
            return

        # 应用差异到原始数据
        records = list(ref_records)  # 浅拷贝

        # 扩展记录到需要的大小
        max_idx = len(records) - 1
        for entry in diff_data.get("appended", []):
            idx = entry.get("index", 0)
            if idx > max_idx:
                max_idx = idx
        while len(records) <= max_idx:
            records.append({'index': len(records), 'battle_id': len(records),
                'flags': 0, 'must_chars': [0]*6, 'battle_name_id': 0, 'map_id': 0,
                'enemy_ids': [0]*18, 'enemy_lv': [0]*18, 'enemy_power': [0]*18,
                'enemy_lv_range': [0]*36, 'enemy_xy': [0]*36, 'ally_xy': [0]*12,
                'enemy_delay': [0]*18, 'ally_facing': [0]*6, 'trap_xy': [0]*56,
                'trap_pwr': [0]*56, 'trea_sub': [0]*10, 'trea_quant': [0]*20,
                'trap_type': [0]*28, 'enemy_flags': [0]*18,
                'lv_spread_lo': 0, 'lv_spread_hi': 0,
                'battle_turn_limit': 0, '_raw': bytes(bytearray(WAR_REC_SIZE))})

        # 应用修改和追加
        for entry in diff_data.get("modified", []) + diff_data.get("appended", []):
            idx = entry.get("index", -1)
            if idx < 0 or idx >= len(records): continue
            fields = entry.get("fields", {})
            for key, value in fields.items():
                if key in records[idx]:
                    records[idx][key] = value

        self.records = records
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
            f"{len(records)} 场战斗")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"共加载 {len(records)} 场战斗数据。\n"
            f"您现在可以继续编辑并重新导出。")

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty or self._warway_dirty):
            event.ignore()
        else:
            event.accept()

    # ═══════════════════════════════════════════════════════════
    # 战场参数标签页
    # ═══════════════════════════════════════════════════════════

    def _build_params_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4,4,12,4)
        layout.setSpacing(4)
        self.pvars = {}
        COLS = 6  # 统一 6 列，确保各分组输入框宽度一致

        def _add_spacers(g, row, used):
            """未满 6 列的尾列补空白占位, 防止拉伸不均"""
            for c in range(used, COLS):
                spacer = QWidget()
                g.addWidget(spacer, row, c)

        # ── 基本信息 ──
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader("基本信息"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        g1 = QGridLayout()
        g1.setHorizontalSpacing(8)
        g1.setVerticalSpacing(6)
        fields = [
            ("battle_id", "战场序号", "记录索引号(0-218)"),
            ("map_id", "地图编号", "[offset 32] WSC.GRP背景索引"),
            ("battle_name_id", "名称文本ID", "[offset 30] TKT文本ID"),
            ("battle_turn_limit", "回合限制", "[offset 482] >0时限制回合数"),
        ]
        for c, (key, label, tip) in enumerate(fields):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit()
            self.pvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            g1.addLayout(cell, 0, c, Qt.AlignTop)
        _add_spacers(g1, 0, len(fields))
        for c in range(COLS): g1.setColumnStretch(c, 1)
        bl.addLayout(g1)
        gl.addWidget(body)
        layout.addWidget(grp)

        # ── 参数标志 ──
        grp2 = QWidget()
        gl2 = QVBoxLayout(grp2)
        gl2.setContentsMargins(0,0,0,0)
        gl2.setSpacing(0)
        gl2.addWidget(DockHeader("参数标志 [offset 0]"))
        body2 = QWidget()
        body2.setObjectName("DockBody")
        bl2 = QVBoxLayout(body2)
        bl2.setContentsMargins(8,8,8,8)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(6)
        cell = QVBoxLayout()
        cell.setSpacing(2)
        lbl = QLabel("标志值")
        lbl.setProperty("class", "PropLabel")
        lbl.setToolTip("bit1(&2)=失败条件, bit2(&4)=随机敌军")
        cell.addWidget(lbl)
        self.pvars['flags'] = ev = QLineEdit()
        cell.addWidget(make_fake_input(line_edit=ev))
        g2.addLayout(cell, 0, 0, 1, 1, Qt.AlignTop)
        cb_cell = QVBoxLayout()
        cb_cell.setSpacing(4)
        cb_cell.addWidget(QLabel(""))
        self.flag_bit1 = QCheckBox("bit1: 失败后继续")
        self.flag_bit1.toggled.connect(self._on_flag_change)
        cb_cell.addWidget(self.flag_bit1)
        self.flag_bit2 = QCheckBox("bit2: 随机敌军数量")
        self.flag_bit2.toggled.connect(self._on_flag_change)
        cb_cell.addWidget(self.flag_bit2)
        g2.addLayout(cb_cell, 0, 1, 1, 5, Qt.AlignTop)
        for c in range(COLS): g2.setColumnStretch(c, 1)
        bl2.addLayout(g2)
        gl2.addWidget(body2)
        layout.addWidget(grp2)

        # ── 强制出战角色 ──
        grp3 = QWidget()
        gl3 = QVBoxLayout(grp3)
        gl3.setContentsMargins(0,0,0,0)
        gl3.setSpacing(0)
        gl3.addWidget(DockHeader("强制出战角色 [002-007] (6槽位, +1编码)"))
        body3 = QWidget()
        body3.setObjectName("DockBody")
        bl3 = QVBoxLayout(body3)
        bl3.setContentsMargins(8,8,8,8)
        g3 = QGridLayout()
        g3.setHorizontalSpacing(8)
        g3.setVerticalSpacing(6)
        self.pvars['must_chars'] = []
        self.must_char_labels = []
        for i in range(6):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(f"槽{i}")
            lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            var = QLineEdit()
            self.pvars['must_chars'].append(var)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            self.must_char_labels.append(extra)
            cell.addWidget(make_fake_input(line_edit=var))
            cell.addWidget(extra)
            g3.addLayout(cell, 0, i, Qt.AlignTop)
        for c in range(COLS): g3.setColumnStretch(c, 1)
        bl3.addLayout(g3)
        gl3.addWidget(body3)
        layout.addWidget(grp3)

        layout.addStretch()
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "战场参数")

    def _on_flag_change(self):
        flags = 0
        if self.flag_bit1.isChecked(): flags |= 2
        if self.flag_bit2.isChecked(): flags |= 4
        self.pvars['flags'].setText(str(flags))
        self._dirty = True

    def _populate_params_tab(self, rec):
        self.pvars['battle_id'].setText(str(rec['battle_id']))
        self.pvars['map_id'].setText(str(rec['map_id']))
        self.pvars['battle_name_id'].setText(str(rec['battle_name_id']))
        self.pvars['battle_turn_limit'].setText(str(rec['battle_turn_limit']))
        self.pvars['flags'].setText(str(rec['flags']))
        self.flag_bit1.blockSignals(True)
        self.flag_bit1.setChecked((rec['flags']&2)!=0)
        self.flag_bit1.blockSignals(False)
        self.flag_bit2.blockSignals(True)
        self.flag_bit2.setChecked((rec['flags']&4)!=0)
        self.flag_bit2.blockSignals(False)
        for i in range(6):
            v = rec['must_chars'][i]
            self.pvars['must_chars'][i].setText(str(v))
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4,4,12,4)
        layout.setSpacing(4)
        self.apvars = {}
        self.apflag_bit1 = None
        self.apflag_bit2 = None
        COLS = 6  # 统一 6 列

        def _add_spacers(g, row, used):
            for c in range(used, COLS):
                g.addWidget(QWidget(), row, c)

        # ── 基本信息 ──
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader("基本信息"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        g1 = QGridLayout()
        g1.setHorizontalSpacing(8)
        g1.setVerticalSpacing(6)
        fields = [
            ("battle_id", "战场序号", "记录索引号(0-218)"),
            ("map_id", "地图编号", "[offset 32] WSC.GRP背景索引"),
            ("battle_name_id", "名称文本ID", "[offset 30] TKT文本ID"),
            ("battle_turn_limit", "回合限制", "[offset 482] >0时限制回合数"),
        ]
        for c, (key, label, tip) in enumerate(fields):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit()
            self.apvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            g1.addLayout(cell, 0, c, Qt.AlignTop)
        _add_spacers(g1, 0, len(fields))
        for c in range(COLS): g1.setColumnStretch(c, 1)
        bl.addLayout(g1)
        gl.addWidget(body)
        layout.addWidget(grp)

        # ── 参数标志 ──
        grp2 = QWidget()
        gl2 = QVBoxLayout(grp2)
        gl2.setContentsMargins(0,0,0,0)
        gl2.setSpacing(0)
        gl2.addWidget(DockHeader("参数标志 [offset 0]"))
        body2 = QWidget()
        body2.setObjectName("DockBody")
        bl2 = QVBoxLayout(body2)
        bl2.setContentsMargins(8,8,8,8)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(6)
        cell = QVBoxLayout()
        cell.setSpacing(2)
        lbl = QLabel("标志值")
        lbl.setProperty("class", "PropLabel")
        lbl.setToolTip("bit1(&2)=失败条件, bit2(&4)=随机敌军")
        cell.addWidget(lbl)
        self.apvars['flags'] = ev = QLineEdit()
        cell.addWidget(make_fake_input(line_edit=ev))
        g2.addLayout(cell, 0, 0, 1, 1, Qt.AlignTop)
        cb_cell = QVBoxLayout()
        cb_cell.setSpacing(4)
        cb_cell.addWidget(QLabel(""))
        self.apflag_bit1 = QCheckBox("bit1: 失败后继续")
        self.apflag_bit1.toggled.connect(self._on_apflag_change)
        cb_cell.addWidget(self.apflag_bit1)
        self.apflag_bit2 = QCheckBox("bit2: 随机敌军数量")
        self.apflag_bit2.toggled.connect(self._on_apflag_change)
        cb_cell.addWidget(self.apflag_bit2)
        g2.addLayout(cb_cell, 0, 1, 1, 5, Qt.AlignTop)
        for c in range(COLS): g2.setColumnStretch(c, 1)
        bl2.addLayout(g2)
        gl2.addWidget(body2)
        layout.addWidget(grp2)

        # ── 强制出战角色 ──
        grp3 = QWidget()
        gl3 = QVBoxLayout(grp3)
        gl3.setContentsMargins(0,0,0,0)
        gl3.setSpacing(0)
        gl3.addWidget(DockHeader("强制出战角色 [002-007] (6槽位, +1编码)"))
        body3 = QWidget()
        body3.setObjectName("DockBody")
        bl3 = QVBoxLayout(body3)
        bl3.setContentsMargins(8,8,8,8)
        g3 = QGridLayout()
        g3.setHorizontalSpacing(8)
        g3.setVerticalSpacing(6)
        self.apvars['must_chars'] = []
        self.ap_must_char_labels = []
        for i in range(6):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(f"槽{i}")
            lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            var = QLineEdit()
            self.apvars['must_chars'].append(var)
            extra = QLabel("")
            extra.setProperty("class", "ExtraPreviewText")
            self.ap_must_char_labels.append(extra)
            cell.addWidget(make_fake_input(line_edit=var))
            cell.addWidget(extra)
            g3.addLayout(cell, 0, i, Qt.AlignTop)
        for c in range(COLS): g3.setColumnStretch(c, 1)
        bl3.addLayout(g3)
        gl3.addWidget(body3)
        layout.addWidget(grp3)

        # ── 敌军配置 ──
        grp_enemy = QWidget()
        gl_enemy = QVBoxLayout(grp_enemy)
        gl_enemy.setContentsMargins(0,0,0,0)
        gl_enemy.setSpacing(0)
        gl_enemy.addWidget(DockHeader("敌军配置 [034-177] ×18"))
        body_enemy = QWidget()
        body_enemy.setObjectName("DockBody")
        bl_enemy = QVBoxLayout(body_enemy)
        bl_enemy.setContentsMargins(8,8,8,8)
        tbl = AdaptiveTableWidget(
            18, 9,
            stretch_columns=set(range(9)),
            minimum_widths=[64, 64, 64, 64, 64, 64, 64, 75, 64],
        )
        tbl.setMinimumHeight(350)
        tbl.setHorizontalHeaderLabels(["ID\nu16\n034-069","Lv\nu8\n070-087","加成\nu8\n088-105","LvP1\ni8\n106-141","LvP2\ni8\n106-141","X\ni8\n142-177","Y\ni8\n142-177","朝向\nu8\n190-207","标志\nu16\n442-477"])
        tbl.horizontalHeaderItem(7).setToolTip("0=随机朝向；1~4=四个方向；5~127会导致形象取帧越界；128~255按有符号负值也走随机。不是出场延迟")
        self.ap_enemy_table = tbl
        bl_enemy.addWidget(tbl)
        gl_enemy.addWidget(body_enemy)
        layout.addWidget(grp_enemy)

        # ── 友军配置 ──
        grp_ally = QWidget()
        gl_ally = QVBoxLayout(grp_ally)
        gl_ally.setContentsMargins(0,0,0,0)
        gl_ally.setSpacing(0)
        gl_ally.addWidget(DockHeader("友军配置 [178-213] ×6"))
        body_ally = QWidget()
        body_ally.setObjectName("DockBody")
        bl_ally = QVBoxLayout(body_ally)
        bl_ally.setContentsMargins(8,8,8,8)
        atbl = AdaptiveTableWidget(
            6, 3,
            stretch_columns=set(range(3)),
            minimum_widths=[65, 65, 70],
        )
        atbl.setMinimumHeight(160)
        atbl.setHorizontalHeaderLabels(["X\ni8\n178-189","Y\ni8\n178-189","朝向\nu8\n208-213"])
        self.ap_ally_table = atbl
        bl_ally.addWidget(atbl)
        gl_ally.addWidget(body_ally)
        layout.addWidget(grp_ally)

        # ── 宝物/陷阱 ──
        grp_trea = QWidget()
        gl_trea = QVBoxLayout(grp_trea)
        gl_trea.setContentsMargins(0,0,0,0)
        gl_trea.setSpacing(0)
        gl_trea.addWidget(DockHeader("宝物/陷阱 [214-441] ×28"))
        body_trea = QWidget()
        body_trea.setObjectName("DockBody")
        bl_trea = QVBoxLayout(body_trea)
        bl_trea.setContentsMargins(8,8,8,8)
        ttbl = AdaptiveTableWidget(
            28, 8,
            stretch_columns=set(range(8)),
            minimum_widths=[70, 70, 65, 65, 65, 65, 70, 70],
        )
        ttbl.setMinimumHeight(500)
        ttbl.setHorizontalHeaderLabels(["陷阱类型\nu16\n386-441","副物品\nu16\n326-345","X\ni8\n214-269","Y\ni8\n214-269","威Min\nu8\n270-325","威Max\nu8\n270-325","QtMin\nu16\n346-385","QtMax\nu16\n346-385"])
        self.ap_trea_table = ttbl
        bl_trea.addWidget(ttbl)
        gl_trea.addWidget(body_trea)
        layout.addWidget(grp_trea)

        # ── 其他参数 ──
        grp4 = QWidget()
        gl4 = QVBoxLayout(grp4)
        gl4.setContentsMargins(0,0,0,0)
        gl4.setSpacing(0)
        gl4.addWidget(DockHeader("其他参数 [478-497]"))
        body4 = QWidget()
        body4.setObjectName("DockBody")
        bl4 = QVBoxLayout(body4)
        bl4.setContentsMargins(8,8,8,8)
        g4 = QGridLayout()
        g4.setHorizontalSpacing(8)
        g4.setVerticalSpacing(6)
        other_fields = [
            ("lv_spread_lo", "Lv浮动下限", "[offset 478]"),
            ("lv_spread_hi", "Lv浮动上限", "[offset 480]"),
        ]
        for c, (key, label, tip) in enumerate(other_fields):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            cell.addWidget(lbl)
            ev = QLineEdit()
            self.apvars[key] = ev
            cell.addWidget(make_fake_input(line_edit=ev))
            g4.addLayout(cell, 0, c, Qt.AlignTop)
        _add_spacers(g4, 0, len(other_fields))
        for c in range(COLS): g4.setColumnStretch(c, 1)
        bl4.addLayout(g4)
        gl4.addWidget(body4)
        layout.addWidget(grp4)
        layout.addWidget(QLabel("[484-497] (保留14字节 — 全零)"))

        layout.addStretch()
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "全部参数")

    def _on_apflag_change(self):
        flags = 0
        if self.apflag_bit1.isChecked(): flags |= 2
        if self.apflag_bit2.isChecked(): flags |= 4
        self.apvars['flags'].setText(str(flags))
        self._dirty = True

    def _link_params_tabs(self):
        """双向同步战场参数(pvars)与全部参数(apvars)标签页的重叠字段。

        两个标签页共享字段: battle_id/map_id/battle_name_id/battle_turn_limit/flags/must_chars[6]。
        若不同步, 用户在战场参数标签页修改后, _apply_allparams_tab 会用全部参数标签页的
        旧值覆盖新值 (历史 BUG: 战场参数修改无法成功应用)。
        同步策略: 任一标签页编辑时立即同步到另一个, 保证 apply 时两边值一致。
        """
        def _sync_text(src, dst, text):
            # 值不同才写回, 且 blockSignals 防止递归
            if dst.text() != text:
                dst.blockSignals(True)
                dst.setText(text)
                dst.blockSignals(False)
        def _sync_check(src, dst, state):
            if dst.isChecked() != src.isChecked():
                dst.blockSignals(True)
                dst.setChecked(src.isChecked())
                dst.blockSignals(False)
        # 标量字段双向同步
        for key in ['battle_id', 'map_id', 'battle_name_id', 'battle_turn_limit', 'flags']:
            ev1 = self.pvars[key]
            ev2 = self.apvars[key]
            ev1.textChanged.connect(partial(_sync_text, ev1, ev2))
            ev2.textChanged.connect(partial(_sync_text, ev2, ev1))
        # must_chars 列表字段双向同步
        for i in range(6):
            ev1 = self.pvars['must_chars'][i]
            ev2 = self.apvars['must_chars'][i]
            ev1.textChanged.connect(partial(_sync_text, ev1, ev2))
            ev2.textChanged.connect(partial(_sync_text, ev2, ev1))
        # flags checkbox 双向同步 (与 flags 文本框联动由 _on_flag_change/_on_apflag_change 完成)
        for b1, b2 in [(self.flag_bit1, self.apflag_bit1), (self.flag_bit2, self.apflag_bit2)]:
            b1.toggled.connect(partial(_sync_check, b1, b2))
            b2.toggled.connect(partial(_sync_check, b2, b1))
        # map_id 编辑完成 (Enter/失焦) 时检测空白地图并自动填充障碍覆盖整图。
        # 程序化 setText (选择记录时) 不触发 editingFinished, 故浏览记录不会误触发。
        self.pvars['map_id'].editingFinished.connect(self._on_map_id_committed)
        self.apvars['map_id'].editingFinished.connect(self._on_map_id_committed)

    def _auto_fill_obstacle_if_blank(self, new_id):
        """若 new_id 指向的 WarWay 网格为全零 (全新/未配置地图), 自动用 -1 (障碍)
        覆盖整张 32x32 地图, 与 #198 (map_id=19) 等模板一致, 便于后续雕刻可通行区域。

        返回是否执行了填充。由 _on_map_id_committed (字段提交) 和 _apply_and_refresh
        (应用修改按钮) 共同调用, 确保两条路径都能自动填充障碍。
        """
        grid = self._get_warway_grid(new_id)
        if grid is not None and not any(grid):  # 全零 = 全新空白地图
            for i in range(1024):
                grid[i] = 0xFF  # -1 障碍, 从左上角覆盖整张地图
            self._warway_dirty = True
            self._dirty = True
            self.status_var.setText(f"地图 #{new_id} 为空白, 已自动填充障碍覆盖整图 (可雕刻可通行区域)")
            return True
        return False

    def _on_map_id_committed(self):
        """map_id 字段编辑完成 (editingFinished) 时触发。

        若新 map_id 指向的 WarWay 网格为全零 (全新/未配置地图), 自动用 -1 (障碍)
        覆盖整张 32x32 地图, 与 #198 (map_id=19) 等模板一致, 便于后续雕刻可通行区域。
        仅在用户主动编辑并提交时触发; pvars/apvars 双标签页由 new_id==rec['map_id'] 去重。
        """
        if self._current_idx < 0: return
        try:
            new_id = int(self.pvars['map_id'].text() or 0) & 0xFFFF
        except ValueError:
            return
        rec = self.records[self._current_idx]
        if new_id == rec['map_id']:
            return  # 值未变化 (双标签页去重 / 程序化填充后回访)
        rec['map_id'] = new_id
        self._auto_fill_obstacle_if_blank(new_id)
        self._sync_raw(rec)
        self._redraw_scene()

    def _populate_allparams_tab(self, rec):
        self.apvars['battle_id'].setText(str(rec['battle_id']))
        self.apvars['map_id'].setText(str(rec['map_id']))
        self.apvars['battle_name_id'].setText(str(rec['battle_name_id']))
        self.apvars['battle_turn_limit'].setText(str(rec['battle_turn_limit']))
        self.apvars['flags'].setText(str(rec['flags']))
        self.apvars['lv_spread_lo'].setText(str(rec['lv_spread_lo']))
        self.apvars['lv_spread_hi'].setText(str(rec['lv_spread_hi']))
        self.apflag_bit1.blockSignals(True)
        self.apflag_bit1.setChecked((rec['flags']&2)!=0)
        self.apflag_bit1.blockSignals(False)
        self.apflag_bit2.blockSignals(True)
        self.apflag_bit2.setChecked((rec['flags']&4)!=0)
        self.apflag_bit2.blockSignals(False)
        for i in range(6):
            v = rec['must_chars'][i]
            self.apvars['must_chars'][i].setText(str(v))
            self.ap_must_char_labels[i].setText(self._char_name(v-1)[:12] if v and v!=255 else "")
        # 敌军表
        tbl = self.ap_enemy_table
        for i in range(18):
            vals = [str(rec['enemy_ids'][i]), str(rec['enemy_lv'][i]), str(rec['enemy_power'][i]),
                    str(rec['enemy_lv_range'][i*2]), str(rec['enemy_lv_range'][i*2+1]),
                    str(rec['enemy_xy'][i*2]), str(rec['enemy_xy'][i*2+1]),
                    str(rec['enemy_delay'][i]), str(rec['enemy_flags'][i])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(i, c, item)
        # 友军表
        atbl = self.ap_ally_table
        for i in range(6):
            for c, v in enumerate([str(rec['ally_xy'][i*2]), str(rec['ally_xy'][i*2+1]), str(rec['ally_facing'][i])]):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                atbl.setItem(i, c, item)
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
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                ttbl.setItem(i, c, item)

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
            item = tbl.item(r, c)
            return int(item.text()) if item and item.text() else 0
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(4)
        tbl = AdaptiveTableWidget(
            18, 11,
            stretch_columns={2, 10},
            minimum_widths=[30, 60, 180, 45, 70, 45, 45, 35, 35, 55, 70],
        )
        tbl.setHorizontalHeaderLabels(["槽","角色ID","角色名","等级","加成倍率","LvP1","LvP2","X","Y","朝向","特殊设定"])
        tbl.horizontalHeaderItem(9).setToolTip("0=随机朝向；1~4=四个方向；5~127会导致形象取帧越界；128~255按有符号负值也走随机。不是出场延迟")
        self.enemy_table = tbl
        self.enemy_name_labels = []
        for i in range(18):
            item = QTableWidgetItem(str(i))
            item.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(i, 0, item)
            name_lbl = QLabel("")
            name_lbl.setProperty("class","ExtraPreviewText")
            self.enemy_name_labels.append(name_lbl)
            tbl.setCellWidget(i, 2, name_lbl)
        tbl.cellChanged.connect(self._on_enemy_cell_changed)
        tbl.cellDoubleClicked.connect(self._on_enemy_cell_clicked)
        layout.addWidget(tbl)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "敌军配置")

    def _apply_and_refresh(self):
        """应用全部标签页修改到记录并刷新场景预览

        注意: 战场参数/全部参数标签页也必须应用, 否则用户修改的 map_id/flags/turn_limit
        等字段不会写回记录 (历史 BUG: 原实现仅应用敌军/友军/掉落/陷阱四个标签页)。
        """
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        old_map_id = rec['map_id']
        self._apply_params_tab(rec)
        self._apply_allparams_tab(rec)
        self._apply_enemy_tab(rec)
        self._apply_ally_tab(rec)
        self._apply_drops_tab(rec)
        self._apply_trap_tab(rec)
        # 检测 map_id 变化并自动填充障碍 (新增战场改地图编号后点"应用修改"时触发,
        # editingFinished 在按钮点击时不一定触发, 故在此显式处理确保场景与网格同步)
        new_map_id = rec['map_id']
        if new_map_id != old_map_id:
            self._auto_fill_obstacle_if_blank(new_map_id)
        self._sync_raw(rec)
        # 仅刷新名称和标志列 (避免完整 repopulate 触发 cellChanged 递归)
        tbl = self.enemy_table
        tbl.blockSignals(True)
        for i in range(18):
            eid = rec['enemy_ids'][i]
            self.enemy_name_labels[i].setText(self._enemy_name(eid)[:14] if eid else "(空)")
            f = rec['enemy_flags'][i]
            parts = []
            if f&1: parts.append('精英')
            if f&2: parts.append('特殊')
            if f&0x2000: parts.append('阵营A')
            if f&0x4000: parts.append('阵营B')
            if f&0x8000: parts.append('特殊型')
            tip_item = QTableWidgetItem('/'.join(parts) if parts else '')
            tip_item.setTextAlignment(Qt.AlignCenter)
            tip_item.setFlags(tip_item.flags() & ~Qt.ItemIsEditable)
            tbl.setItem(i, 10, tip_item)
        tbl.blockSignals(False)
        # 刷新左侧列表当前行 (地图/敌军数/参战人物等列随应用结果更新)
        self._update_tree_row(self._current_idx)
        self._redraw_scene(rerandomize=False)

    def _populate_enemy_tab(self, rec):
        tbl = self.enemy_table
        tbl.blockSignals(True)
        for i in range(18):
            eid = rec['enemy_ids'][i]
            for c, v in enumerate([str(eid), None, str(rec['enemy_lv'][i]),
                str(rec['enemy_power'][i]), str(rec['enemy_lv_range'][i*2]),
                str(rec['enemy_lv_range'][i*2+1]), str(rec['enemy_xy'][i*2]),
                str(rec['enemy_xy'][i*2+1]), str(rec['enemy_delay'][i]),
                str(rec['enemy_flags'][i])], 1):
                if v is None: continue
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(i, c, item)
            f = rec['enemy_flags'][i]
            parts = []
            if f&1: parts.append('精英')
            if f&2: parts.append('特殊')
            if f&0x2000: parts.append('阵营A')
            if f&0x4000: parts.append('阵营B')
            if f&0x8000: parts.append('特殊型')
            self.enemy_name_labels[i].setText(self._enemy_name(eid)[:14] if eid else "(空)")
            tip_item = QTableWidgetItem('/'.join(parts) if parts else '')
            tip_item.setTextAlignment(Qt.AlignCenter)
            tip_item.setFlags(tip_item.flags() & ~Qt.ItemIsEditable)
            tbl.setItem(i, 10, tip_item)
        tbl.blockSignals(False)

    # 敌军配置表 (enemy_table) 列号 → 全部参数表 (ap_enemy_table) 列号映射
    # 两表是同一敌军数据的双视图, 必须保持同步, 否则 _apply_allparams_tab 会用
    # stale 数据覆盖 _apply_enemy_tab/对话框已写入 rec 的值 (历史 BUG: 特殊设定消失)
    _ENEMY_COL_TO_AP = {1:0, 3:1, 4:2, 5:3, 6:4, 7:5, 8:6, 9:7, 10:8}

    def _sync_ap_enemy_cell(self, row, enemy_col, value):
        """将 enemy_table 的编辑同步到 ap_enemy_table 对应单元格 (数值视图)。

        enemy_table col10 (特殊设定) 存的是中文标签 ("精英/特殊"), 无法被
        _apply_enemy_tab 的 int() 解析; ap_enemy_table col8 存数值才是权威源。
        故对话框/手动编辑 enemy_table 后必须同步 ap_enemy_table, 避免应用时覆盖。
        """
        ap_col = self._ENEMY_COL_TO_AP.get(enemy_col)
        if ap_col is None: return
        atbl = self.ap_enemy_table
        atbl.blockSignals(True)
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignCenter)
        atbl.setItem(row, ap_col, item)
        atbl.blockSignals(False)

    def _on_enemy_cell_changed(self, row, col):
        """敌军表格单元格变更时同步写回记录并刷新名称"""
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        tbl = self.enemy_table
        item = tbl.item(row, col)
        if not item or not item.text(): return
        try: v = int(item.text() or 0)
        except ValueError: return  # 标志列文本非数字时跳过
        self._dirty = True
        if col == 1:   # 角色ID
            rec['enemy_ids'][row] = v
            self.enemy_name_labels[row].setText(self._enemy_name(v)[:14] if v else "(空)")
        elif col == 3: rec['enemy_lv'][row] = v & 0xFF
        elif col == 4: rec['enemy_power'][row] = v & 0xFF
        elif col == 5: rec['enemy_lv_range'][row*2] = v
        elif col == 6: rec['enemy_lv_range'][row*2+1] = v
        elif col == 7: rec['enemy_xy'][row*2] = v
        elif col == 8: rec['enemy_xy'][row*2+1] = v
        elif col == 9: rec['enemy_delay'][row] = v & 0xFF
        elif col == 10: rec['enemy_flags'][row] = v & 0xFFFF
        # 同步到全部参数表, 防止 _apply_allparams_tab 用 stale 数据覆盖 rec
        self._sync_ap_enemy_cell(row, col, v)

    def _on_enemy_cell_clicked(self, row, col):
        """双击角色ID列弹出WarPC选择器，双击特殊设定列弹出标志选择对话框"""
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        if col == 1:  # 角色ID — WarPC 选择器
            if not self.warpc_records:
                return  # 未加载 WarPC 记录，仅支持手动输入
            cur_eid = rec['enemy_ids'][row]
            cur_warpc_idx = cur_eid + 35
            dlg = WarpcPickerDialog(self, self.warpc_records, self.tkt,
                                   self.fa_sprites, multi_select=False,
                                   current_indices=[cur_warpc_idx])
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_indices:
                new_warpc_idx = dlg.selected_indices[0]
                new_eid = new_warpc_idx - 35
                rec['enemy_ids'][row] = new_eid
                self._dirty = True
                # 刷新表格中的角色ID和角色名
                tbl = self.enemy_table
                tbl.blockSignals(True)
                id_item = QTableWidgetItem(str(new_eid))
                id_item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(row, 1, id_item)
                tbl.blockSignals(False)
                self.enemy_name_labels[row].setText(self._enemy_name(new_eid)[:14] if new_eid else "(空)")
                # 同步到全部参数表 col0, 防止 _apply_allparams_tab 用 stale ID 覆盖
                self._sync_ap_enemy_cell(row, 1, new_eid)
                self._redraw_scene(rerandomize=False)
            return
        if col != 10: return
        rec = self.records[self._current_idx]
        cur = rec['enemy_flags'][row] & 0xFFFF
        dlg = QDialog(self)
        dlg.setWindowTitle(f"敌军槽{row} 特殊设定")
        dlg.resize(300, 220)
        layout = QVBoxLayout(dlg)
        checkboxes = []
        for bit, name, desc in ENEMY_FLAG_BITS:
            cb = QCheckBox(f"{name}" + (f" ({desc})" if desc else ""))
            cb.setChecked(bool(cur & bit))
            checkboxes.append((bit, cb))
            layout.addWidget(cb)
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [c.setChecked(True) for _, c in checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [c.setChecked(False) for _, c in checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("取消", clicked=dlg.reject))
        btn_ok = QPushButton("确定")
        def _ok():
            m = sum(bit for bit, cb in checkboxes if cb.isChecked())
            if m >= 0x8000: m -= 0x10000
            rec['enemy_flags'][row] = m & 0xFFFF
            self._dirty = True
            # 刷新标志列文本
            parts = []
            for bit, name, _ in ENEMY_FLAG_BITS:
                if m & bit: parts.append(name)
            tip_item = QTableWidgetItem('/'.join(parts) if parts else '')
            tip_item.setTextAlignment(Qt.AlignCenter)
            tip_item.setFlags(tip_item.flags() & ~Qt.ItemIsEditable)
            self.enemy_table.setItem(row, 10, tip_item)
            # 同步数值到全部参数表 col8, 否则 _apply_allparams_tab 会用 stale 值覆盖 rec
            self._sync_ap_enemy_cell(row, 10, m & 0xFFFF)
            dlg.accept()
        btn_ok.clicked.connect(_ok)
        bl.addWidget(btn_ok)
        layout.addLayout(bl)
        dlg.exec()

    def _apply_enemy_tab(self, rec):
        tbl = self.enemy_table
        def _g(r, c):
            item = tbl.item(r, c)
            return int(item.text()) if item and item.text() else 0
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(4)
        layout.addWidget(QLabel("友军坐标+朝向 (sub_431428:74 — int8字节对):"))
        tbl = AdaptiveTableWidget(
            6, 4,
            stretch_columns={3},
            minimum_widths=[35, 55, 55, 60],
        )
        tbl.setHorizontalHeaderLabels(["槽","X","Y","朝向"])
        self.ally_table = tbl
        for i in range(6):
            item = QTableWidgetItem(str(i))
            item.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(i, 0, item)
        layout.addWidget(tbl)
        layout.addWidget(QLabel("X,Y: int8(0-31), 0=不使用; 朝向: 0-7(八方), 255=无效"))
        layout.addStretch()
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "友军配置")

    def _populate_ally_tab(self, rec):
        tbl = self.ally_table
        for i in range(6):
            for c, v in enumerate([str(rec['ally_xy'][i*2]), str(rec['ally_xy'][i*2+1]), str(rec['ally_facing'][i])], 1):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(i, c, item)

    def _apply_ally_tab(self, rec):
        tbl = self.ally_table
        def _g(r, c):
            item = tbl.item(r, c)
            return int(item.text()) if item and item.text() else 0
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(4)
        layout.addWidget(QLabel("宝物和陷阱 (sub_431428:198-323) — 28槽位, 共享X/Y"))
        tbl = AdaptiveTableWidget(
            28, 10,
            stretch_columns={4, 7},
            minimum_widths=[30, 40, 40, 65, 80, 55, 55, 160, 55, 55],
        )
        tbl.setHorizontalHeaderLabels(["槽","X","Y","宝物ID","宝物名","数Min","数Max","陷阱类型","威Min","威Max"])
        self.dt_table = tbl
        self.dt_name_labels = []
        trap_items = list(TRAP_NAMES_MAP.values())
        for i in range(28):
            item = QTableWidgetItem(str(i))
            item.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(i, 0, item)
            name_lbl = QLabel("")
            name_lbl.setProperty("class","ExtraPreviewText")
            self.dt_name_labels.append(name_lbl)
            tbl.setCellWidget(i, 4, name_lbl)
            cb = EditorComboBox()
            cb.addItems(trap_items)
            tbl.setCellWidget(i, 7, cb)
        tbl.cellChanged.connect(self._on_dt_cell_changed)
        tbl.cellDoubleClicked.connect(self._on_dt_cell_clicked)
        layout.addWidget(tbl)
        layout.addWidget(QLabel("陷阱1-6→TKKon[552-557] | 宝物:trea_sub+trea_quant(slot0-9)"))
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "宝物和陷阱")

    def _populate_drops_tab(self, rec):
        tbl = self.dt_table
        tbl.blockSignals(True)
        for i in range(28):
            for c, v in enumerate([str(rec['trap_xy'][i*2]), str(rec['trap_xy'][i*2+1])], 1):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(i, c, item)
            tid = rec['trea_sub'][i] if i < 10 else 0
            item = QTableWidgetItem(str(tid))
            item.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(i, 3, item)
            if tid == 10000: self.dt_name_labels[i].setText("金钱")
            elif tid and tid in self.tkitem_names_by_id: self.dt_name_labels[i].setText(self.tkitem_names_by_id[tid][:12])
            elif tid: self.dt_name_labels[i].setText(f"Item#{tid}")
            else: self.dt_name_labels[i].setText("")
            if i < 10:
                for c, v in enumerate([str(rec['trea_quant'][i*2]), str(rec['trea_quant'][i*2+1])], 5):
                    item = QTableWidgetItem(v)
                    item.setTextAlignment(Qt.AlignCenter)
                    tbl.setItem(i, c, item)
        tbl.blockSignals(False)

    def _populate_trap_tab(self, rec):
        tbl = self.dt_table
        tbl.blockSignals(True)
        for i in range(28):
            ttype = rec['trap_type'][i]
            cb = tbl.cellWidget(i, 7)
            if cb:
                cb.blockSignals(True)
                idx = max(0, min(6, ttype)) if 0 <= ttype <= 6 else 0
                cb.setCurrentIndex(idx)
                cb.blockSignals(False)
            pmin, pmax = self._trap_power_at(rec, i)
            for c, v in enumerate([str(pmin), str(pmax)], 8):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(i, c, item)
        tbl.blockSignals(False)

    def _on_dt_cell_clicked(self, row, col):
        """双击宝物ID列弹出物品选择器"""
        if col != 3 or row >= 10 or self._current_idx < 0: return
        if not self.tkitem_records:
            return  # 未加载 TKItem 数据，仅支持手动输入
        rec = self.records[self._current_idx]
        cur_tid = rec['trea_sub'][row]
        dlg = ItemPickerDialog(self, self.tkitem_records,
                               icon_pixmap_fn=self._get_icon_pixmap,
                               current_value=cur_tid,
                               title=f"选择宝物 (槽{row})")
        if dlg.exec() and dlg.selected_value is not None:
            new_tid = dlg.selected_value
            rec['trea_sub'][row] = new_tid & 0xFFFF
            self._dirty = True
            # 刷新表格中的宝物ID和宝物名
            tbl = self.dt_table
            tbl.blockSignals(True)
            id_item = QTableWidgetItem(str(new_tid))
            id_item.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(row, 3, id_item)
            tbl.blockSignals(False)
            if new_tid == 10000: self.dt_name_labels[row].setText("金钱")
            elif new_tid and new_tid in self.tkitem_names_by_id: self.dt_name_labels[row].setText(self.tkitem_names_by_id[new_tid][:12])
            elif new_tid: self.dt_name_labels[row].setText(f"Item#{new_tid}")
            else: self.dt_name_labels[row].setText("")

    def _on_dt_cell_changed(self, row, col):
        """宝物/陷阱表格单元格变更时同步写回记录并刷新名称"""
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        tbl = self.dt_table
        item = tbl.item(row, col)
        if not item or not item.text(): return
        try: v = int(item.text() or 0)
        except ValueError: return
        self._dirty = True
        if col in (1, 2):  # X, Y — 所有28槽共用
            rec['trap_xy'][row*2 + (col-1)] = v
        elif col == 3 and row < 10:  # 宝物ID (仅前10槽)
            rec['trea_sub'][row] = v & 0xFFFF
            tid = v
            if tid == 10000: self.dt_name_labels[row].setText("金钱")
            elif tid and tid in self.tkitem_names_by_id: self.dt_name_labels[row].setText(self.tkitem_names_by_id[tid][:12])
            elif tid: self.dt_name_labels[row].setText(f"Item#{tid}")
            else: self.dt_name_labels[row].setText("")
        elif col == 5 and row < 10:  # 数Min
            rec['trea_quant'][row*2] = v & 0xFFFF
        elif col == 6 and row < 10:  # 数Max
            rec['trea_quant'][row*2+1] = v & 0xFFFF
        elif col in (8, 9):  # 威Min/威Max — 经 trap_power 查询表计算
            pass  # trap_power 由 trap_type 决定, 不可直接编辑

    def _apply_drops_tab(self, rec):
        tbl = self.dt_table
        def _g(r, c):
            item = tbl.item(r, c)
            return int(item.text()) if item and item.text() else 0
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
            item = tbl.item(r, c)
            return int(item.text()) if item and item.text() else 0
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
            rec['trap_pwr'][off] = pmin
            rec['trap_pwr'][off + 1] = pmax

    # ═══════════════════════════════════════════════════════════
    # 场景预览标签页
    # ═══════════════════════════════════════════════════════════

    def _build_scene_tab(self):
        """场景预览标签页 — QGraphicsView + 图层控制"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(2,2,2,2)
        layout.setSpacing(2)

        # 控制栏
        ctrl = QHBoxLayout()
        ctrl.setSpacing(4)
        ctrl.addWidget(QLabel("图层:"))
        self.show_bg = QCheckBox("背景")
        self.show_bg.setChecked(True)
        self.show_bg.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_bg)
        self.show_grid = QCheckBox("网格")
        self.show_grid.setChecked(True)
        self.show_grid.toggled.connect(self._redraw_scene)
        ctrl.addWidget(self.show_grid)
        ctrl.addWidget(QLabel("透明度:"))
        self.grid_alpha = EditorComboBox()
        self.grid_alpha.addItems(['0%','25%','50%','75%','100%'])
        self.grid_alpha.setCurrentText('25%')
        self.grid_alpha.currentTextChanged.connect(partial(self._redraw_scene))
        ctrl.addWidget(self.grid_alpha)
        ctrl.addStretch()
        ctrl.addWidget(QLabel("缩放:"))
        self.zoom_combo = EditorComboBox()
        self.zoom_combo.addItems(['25%','33%','50%','66%','75%','100%'])
        self.zoom_combo.setCurrentText('75%')
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_change)
        ctrl.addWidget(self.zoom_combo)
        ctrl.addWidget(QPushButton("刷新", clicked=lambda: self._redraw_scene(True)))
        self.edit_mode = QCheckBox("编辑")
        ctrl.addWidget(self.edit_mode)
        ctrl.addWidget(QLabel("画笔:"))
        self.zone_brush = EditorComboBox()
        # 索引顺序与 WarWay signed int8 值语义对应 (sub_4355C4/sub_431428)
        self._brush_items = [
            (-1, "障碍(-1)"), (0, "通行(0)"),
            (1, "区域1"), (2, "区域2"), (3, "区域3"), (4, "区域4"), (5, "区域5"),
        ]
        for val, label in self._brush_items:
            self.zone_brush.addItem(label, val)
        self.zone_brush.setCurrentIndex(1)  # 默认通行
        ctrl.addWidget(self.zone_brush)
        _lbl_bg_hint = QLabel("背景=map_id(WSC) | 编辑模式: 左键拖拽绘制矩形/点击单位拖拽")
        _lbl_bg_hint.setObjectName("hintLabel")
        ctrl.addWidget(_lbl_bg_hint)
        layout.addLayout(ctrl)

        # 第二行: 显示元素开关
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        row2.addWidget(QLabel("显示:"))
        self.show_units = QCheckBox("单位")
        self.show_units.setChecked(True)
        self.show_units.toggled.connect(self._redraw_scene)
        row2.addWidget(self.show_units)
        self.show_trea = QCheckBox("宝物")
        self.show_trea.setChecked(True)
        self.show_trea.toggled.connect(self._redraw_scene)
        row2.addWidget(self.show_trea)
        self.show_trap = QCheckBox("陷阱")
        self.show_trap.setChecked(True)
        self.show_trap.toggled.connect(self._redraw_scene)
        row2.addWidget(self.show_trap)
        self.show_obstacle = QCheckBox("障碍")
        self.show_obstacle.setChecked(True)
        self.show_obstacle.toggled.connect(self._redraw_scene)
        row2.addWidget(self.show_obstacle)
        self.show_temp_obstacle = QCheckBox("临时障碍")
        self.show_temp_obstacle.setChecked(True)
        self.show_temp_obstacle.toggled.connect(self._redraw_scene)
        row2.addWidget(self.show_temp_obstacle)
        self.show_zone = [QCheckBox(f"区域{i+1}") for i in range(5)]
        for z in self.show_zone:
            z.setChecked(True)
            z.toggled.connect(self._redraw_scene)
            row2.addWidget(z)
        row2.addStretch()
        layout.addLayout(row2)

        # 图例
        legend = QHBoxLayout()
        legend.setSpacing(6)
        terrain_colors = TERRAIN_COLORS
        for label, color in terrain_colors:
            f = QWidget()
            fl = QHBoxLayout(f)
            fl.setContentsMargins(0,0,0,0)
            fl.setSpacing(2)
            swatch = QLabel()
            swatch.setFixedSize(12,12)
            swatch.setProperty("class", "ColorSwatch")
            swatch.setStyleSheet(f"background-color:{color};")
            fl.addWidget(swatch)
            fl.addWidget(QLabel(label))
            legend.addWidget(f)
        legend.addStretch()
        self.scene_info_var = QLabel("")
        self.scene_info_var.setProperty("class","ExtraPreviewText")
        legend.addWidget(self.scene_info_var)
        layout.addLayout(legend)

        # QGraphicsView
        self.scene_gview = SceneGraphicsView(self)
        # 切换编辑模式时同步刷新悬停预览 (关闭时立即清除高亮)
        self.edit_mode.toggled.connect(self.scene_gview._update_hover_overlay)
        layout.addWidget(self.scene_gview, 1)
        self.tabs.addTab(tab, "场景预览")

    def _on_zoom_change(self, text):
        try: self._preview_zoom = int(text.rstrip('%')) / 100.0
        except: return
        self._wsc_cache.clear()
        self._redraw_scene()

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
        new_w = int(w * zoom)
        new_h = int(h * zoom)
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
        gv = self.scene_gview
        scene = gv.scene()
        scene.clear()
        # scene.clear() 销毁所有 QGraphicsItem 的 C++ 对象, 必须重置 Python 引用避免悬空
        # (否则后续 removeItem/访问会触发 RuntimeError: Internal C++ object already deleted)
        gv._hover_item = None
        gv._hover_label = None
        gv._rect_item = None
        if self._current_idx < 0: return
        rec = self.records[self._current_idx]
        zoom = self._preview_zoom
        tile_w = int(56 * zoom)
        tile_h = int(28 * zoom)
        bg_w = bg_h = 0

        # 背景
        if self.show_bg.isChecked() and HAS_PIL:
            wsc_idx = rec['map_id']
            if wsc_idx < 0 or wsc_idx >= len(self.wsc_offsets) - 1: wsc_idx = 0
            bg = self._load_wsc_background(wsc_idx)
            if bg:
                pixmap, bg_w, bg_h = bg
                scene.addPixmap(pixmap)

        warway = self._get_warway_grid(rec['map_id'])

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
                    pen = QPen(QColor(GRID_PEN), 1)
                    brush = QBrush(Qt.NoBrush)
                    if val == -1:  # WarWay -1 (0xFF) = 永久障碍
                        if not self.show_obstacle.isChecked(): continue
                        pen = QPen(QColor(OBSTACLE_PEN), 1)
                        brush = QBrush(QColor(85,51,34,alpha_val))
                    elif val < -1:  # WarWay < -1 = 临时障碍(sub_4355C4每回合+1直到0)
                        if not self.show_temp_obstacle.isChecked(): continue
                        pen = QPen(QColor(TEMP_OBSTACLE_PEN), 1)
                        brush = QBrush(QColor(102,85,68,alpha_val))
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
                fill_c = QColor(TREASURE_FIXED if i in fixed_trea_indices else TREASURE_RANDOM)
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addRect(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "固" if i in fixed_trea_indices else "随"
                t = scene.addText(tag)
                t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                label = self._trea_label(rec, i)
                if label:
                    lt = scene.addText(label)
                    lt.setDefaultTextColor(fill_c)
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
                    t = scene.addText(txt)
                    t.setDefaultTextColor(QColor(TREASURE_RANDOM))
                    t.setFont(QFont('', max(9, int(11*zoom))))
                    t.setPos(zr_x, bg_h - 15)
                    zr_x += t.boundingRect().width() + 10

        # ── 图层3b: 陷阱 (sub_431428:283-323) ──
        if self.show_trap.isChecked():
            for i, (gx, gy) in resolved_traps.items():
                ttype = self._trap_type_at(rec, i)
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(3, tile_h // 2)
                fc = QColor(TRAP_COLORS.get(ttype, TRAP_FALLBACK))
                # 画布陷阱轮廓绘制色豁免 (#888: 深色画布普通态描边, 非样式体系 UI 色, P3-6 核对)
                outline_c = QColor('white') if i in fixed_trap_indices else QColor('#888')
                pts = [QPointF(sx, sy-r), QPointF(sx-r, sy+r), QPointF(sx+r, sy+r)]
                scene.addPolygon(QPolygonF(pts), QPen(outline_c,1), QBrush(fc))
                tname = TRAP_NAMES_SHORT.get(ttype, '?') + '陷阱'
                tag = "固" if i in fixed_trap_indices else "随"
                t = scene.addText(tag)
                t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                lt = scene.addText(tname)
                lt.setDefaultTextColor(fc)
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
                    t = scene.addText(txt)
                    t.setDefaultTextColor(QColor(TRAP_TEXT_COLOR))
                    t.setFont(QFont('', max(9, int(11*zoom))))
                    t.setPos(zr_x, bg_h - 35)
                    zr_x += t.boundingRect().width() + 10

        # ── 图层4: 单位 (sub_431428 解析后位置) ──
        # 固定位置: 亮色; 区域放置: 暗色
        if self.show_units.isChecked():
            # 敌军 — 按 sub_431428 规则解析后的位置
            for i, (gx, gy) in resolved_enemies.items():
                eid = rec['enemy_ids'][i]
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(5, tile_h // 2)
                if i in fixed_enemy_slots: fill_c = QColor(ENEMY_FIXED)
                else: fill_c = QColor(ENEMY_RANDOM)
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addEllipse(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "固" if i in fixed_enemy_slots else "随"
                t = scene.addText(tag)
                t.setDefaultTextColor(QColor('white'))
                t.setFont(QFont('', max(7, int(9*zoom)), QFont.Bold))
                t.setPos(sx - t.boundingRect().width()/2, sy - t.boundingRect().height()/2)
                name = self._enemy_name(eid)
                nt = scene.addText(name)
                nt.setDefaultTextColor(QColor(ENEMY_NAME_FIXED if i in fixed_enemy_slots else ENEMY_NAME_RANDOM))
                nt.setFont(QFont('', max(8, int(10*zoom))))
                nt.setPos(sx - nt.boundingRect().width()/2, sy + r + 2)
            # 友军 — ally_xy [178-189] + 区域放置解析
            for i in range(6):
                if i in resolved_allies:
                    gx, gy = resolved_allies[i]
                    fill_c = QColor(ALLY_FILL)
                else:
                    ax = rec['ally_xy'][i*2]
                    ay = rec['ally_xy'][i*2+1]
                    if ax == 0 and ay == 0: continue
                    if ax < 0 or ay < 0 or ax >= 32 or ay >= 32: continue
                    gx, gy = ax, ay
                    fill_c = QColor(ALLY_FILL_ALT)
                sx, sy = self._grid_to_screen(gx, gy)
                r = max(5, tile_h // 2)
                rect = QRectF(sx-r, sy-r, r*2, r*2)
                scene.addEllipse(rect, QPen(QColor('white'),1), QBrush(fill_c))
                tag = "随" if i in resolved_allies else "固"
                t = scene.addText(tag)
                t.setDefaultTextColor(QColor('white'))
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
                    t = scene.addText(txt)
                    t.setDefaultTextColor(QColor('#ff6666'))
                    t.setFont(QFont('', max(9, int(11*zoom))))
                    t.setPos(ezr_x, 20)
                    ezr_x += t.boundingRect().width() + 10
            # 激活槽位提示
            if active_slots < 18:
                t = scene.addText(f"[激活槽位:0-{active_slots-1}]")
                t.setDefaultTextColor(QColor('#ff6666'))
                t.setFont(QFont('', max(8, int(9*zoom))))
                t.setPos(10, 40)
            # 强制出战角色名称 — must_chars [2-7]
            for i in range(6):
                cv = rec['must_chars'][i]
                if cv <= 0: continue
                name = self._char_name(cv-1)[:4]
                t = scene.addText(f"[{name}]")
                t.setDefaultTextColor(QColor(ALLY_TEXT))
                t.setFont(QFont('Microsoft YaHei UI', 9))
                t.setPos(10 + i*60, 5)

        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-50, -50, 50, 50))
        gv.horizontalScrollBar().setValue(0)
        gv.verticalScrollBar().setValue(0)
        # 场景清空后重建涂刷悬停预览叠加层 (编辑模式下)
        gv._update_hover_overlay()
        gv._update_rect_overlay()

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
            ax = rec['ally_xy'][i*2]
            ay = rec['ally_xy'][i*2+1]
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

    def _warway_value_at(self, gx, gy):
        """读取当前地图 (gx,gy) 的 WarWay signed int8 值, 无网格返回 None"""
        if self._current_idx < 0: return None
        rec = self.records[self._current_idx]
        grid = self._get_warway_grid(rec['map_id'])
        if not grid: return None
        raw = grid[gy * 32 + gx]
        return raw if raw < 128 else raw - 256

    def _paint_warway_cell(self, gx, gy, value):
        """用画笔值涂刷当前地图的 (gx,gy) 网格。

        value 为 signed int8 语义 (-1/0/1-5), 存储为 unsigned byte (-1→0xFF)。
        涂刷后标记 _warway_dirty 并局部重绘 (不重新随机放置)。
        多个战场共享同一 map_id 时, 修改会同步影响所有使用该地图的战场 (游戏数据结构如此)。
        """
        if self._current_idx < 0: return False
        rec = self.records[self._current_idx]
        grid = self._get_warway_grid(rec['map_id'])
        if not grid: return False
        if not (0 <= gx < 32 and 0 <= gy < 32): return False
        old = grid[gy * 32 + gx]
        new = value & 0xFF
        if old == new: return False
        grid[gy * 32 + gx] = new
        self._warway_dirty = True
        return True

    # ═══════════════════════════════════════════════════════════
    # SceneGraphicsView
    # ═══════════════════════════════════════════════════════════

class SceneGraphicsView(QGraphicsView):
    """自定义 QGraphicsView — 支持悬停信息、缩放、拖拽编辑、网格涂刷、右键平移

    编辑模式 (edit_mode 勾选) 左键交互:
      - 点击单位(敌军/友军) → 拖拽移动单位, 释放后写回 enemy_xy/ally_xy
      - 点击空格 + 拖拽 → 矩形绘制模式: 预览矩形区域, 释放时用画笔值批量填充
      - 点击空格 (无拖拽) → 单格涂刷 (矩形退化为 1x1)
    """
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QBrush(QColor(SCENE_BG)))
        self.setMouseTracking(True)
        self._drag_target = None
        self._pan_start = None
        self._painting = False
        # 涂刷悬停预览状态 — 编辑模式下叠绘画笔颜色, 直观提示目标格与即将涂刷的区域
        self._hover_grid = None    # (gx, gy) 当前悬停网格, None 表示不在网格内
        self._hover_item = None    # 悬停高亮多边形 (QGraphicsPolygonItem)
        self._hover_label = None   # 悬停画笔名称标签 (QGraphicsTextItem)
        # 矩形绘制状态 — 长按拖拽时预览矩形区域, 释放时批量填充
        self._rect_start = None    # (gx, gy) 矩形起点
        self._rect_end = None      # (gx, gy) 矩形终点
        self._rect_item = None     # 矩形预览多边形 (QGraphicsPolygonItem)

    def _brush_value(self):
        """当前画笔值 (signed int8 语义: -1/0/1-5)"""
        return self.editor.zone_brush.currentData()

    def _terrain_tag(self, val):
        """WarWay 值 → 中文标签 (用于悬停信息)"""
        if val is None: return ""
        if val == -1: return "障碍"
        if val == 0: return "通行"
        if 1 <= val <= 5: return f"区域{val}"
        if val < -1: return f"临时障碍{val}"
        return str(val)

    def _brush_fill_rgb(self, val):
        """画笔值 → 填充 RGB (与 _redraw_scene 网格配色一致), 用于悬停预览叠绘。

        0(通行)在网格绘制中不填充, 这里返回浅色仅作边框辅助, 实际叠绘时用 NoBrush。
        """
        return {
            -1: (85, 51, 34),
            0:  (220, 220, 220),
            1:  (170, 102, 51),
            2:  (51, 102, 170),
            3:  (170, 68, 170),
            4:  (51, 170, 102),
            5:  (170, 170, 51),
        }.get(val, (200, 200, 200))

    def _safe_remove(self, item):
        """安全移除 QGraphicsItem — scene.clear() 可能已销毁其 C++ 对象, 需防御性捕获"""
        if item is None: return
        try:
            self.scene().removeItem(item)
        except RuntimeError:
            pass  # C++ 对象已被 scene.clear() 销毁, 仅丢弃 Python 引用即可

    def _update_hover_overlay(self, *_):
        """更新涂刷悬停预览: 在当前悬停网格上叠绘画笔颜色 + 高亮边框 + 名称标签。

        编辑模式开启时, 鼠标悬停的网格会显示即将涂刷的颜色, 直观提示目标格与画笔类型,
        无需查看画笔下拉框即可知道当前要绘制的是哪个区域/颜色的色块。
        场景被 _redraw_scene 清空后由其末尾调用本方法重建叠加层; *_ 吸收 toggled 信号参数。
        """
        self._safe_remove(self._hover_item)
        self._hover_item = None
        self._safe_remove(self._hover_label)
        self._hover_label = None
        if self._hover_grid is None or not self.editor.edit_mode.isChecked():
            return
        if self.editor._current_idx < 0:
            return
        gx, gy = self._hover_grid
        zoom = self.editor._preview_zoom
        tile_w = int(56 * zoom)
        tile_h = int(28 * zoom)
        sx, sy = self.editor._grid_to_screen(gx, gy)
        pts = [QPointF(sx, sy - tile_h), QPointF(sx + tile_w, sy),
               QPointF(sx, sy + tile_h), QPointF(sx - tile_w, sy)]
        bval = self._brush_value()
        # 0(通行)用 NoBrush, 仅靠亮黄边框+标签提示; 其余按画笔颜色半透明填充
        if bval == 0:
            fill = QBrush(Qt.NoBrush)
        else:
            r, g, b = self._brush_fill_rgb(bval)
            fill = QBrush(QColor(r, g, b, 160))
        item = self.scene().addPolygon(QPolygonF(pts), QPen(QColor(SELECT_OUTLINE), 2), fill)
        item.setZValue(1000)
        self._hover_item = item
        name = self._terrain_tag(bval)
        label = self.scene().addText(f"▸{name}")
        label.setDefaultTextColor(QColor(SELECT_OUTLINE))
        label.setFont(QFont('', max(8, int(10 * zoom)), QFont.Bold))
        label.setZValue(1001)
        lw = label.boundingRect().width()
        label.setPos(sx - lw / 2, sy - tile_h - label.boundingRect().height())
        self._hover_label = label

    def _update_rect_overlay(self, *_):
        """更新矩形绘制预览: 从 _rect_start 到 _rect_end 的网格矩形区域。

        长按拖拽时实时显示半透明画笔色覆盖的矩形区域 + 虚线边框 + 尺寸标签,
        释放时批量填充。等距投影下网格矩形呈平行四边形, 用4角格的外顶点构成多边形。
        """
        self._safe_remove(self._rect_item)
        self._rect_item = None
        if self._rect_start is None or self._rect_end is None:
            return
        if not self.editor.edit_mode.isChecked() or self.editor._current_idx < 0:
            return
        gx1, gy1 = self._rect_start
        gx2, gy2 = self._rect_end
        minx, maxx = min(gx1, gx2), max(gx1, gx2)
        miny, maxy = min(gy1, gy2), max(gy1, gy2)
        zoom = self.editor._preview_zoom
        tile_w = int(56 * zoom)
        tile_h = int(28 * zoom)
        # 4角格中心 → 各自外顶点, 构成平行四边形覆盖整个网格矩形
        sx_tl, sy_tl = self.editor._grid_to_screen(minx, miny)
        sx_tr, sy_tr = self.editor._grid_to_screen(maxx, miny)
        sx_br, sy_br = self.editor._grid_to_screen(maxx, maxy)
        sx_bl, sy_bl = self.editor._grid_to_screen(minx, maxy)
        pts = [QPointF(sx_tl, sy_tl - tile_h),   # 上
               QPointF(sx_tr + tile_w, sy_tr),    # 右
               QPointF(sx_br, sy_br + tile_h),    # 下
               QPointF(sx_bl - tile_w, sy_bl)]    # 左
        bval = self._brush_value()
        r, g, b = self._brush_fill_rgb(bval)
        fill = QBrush(QColor(r, g, b, 70))
        item = self.scene().addPolygon(QPolygonF(pts), QPen(QColor(SELECT_OUTLINE), 2, Qt.DashLine), fill)
        item.setZValue(999)
        self._rect_item = item

    def leaveEvent(self, event):
        """鼠标离开视图时清除悬停预览, 避免残留高亮"""
        self._hover_grid = None
        self._update_hover_overlay()
        self._update_rect_overlay()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        """悬停显示网格信息 + 编辑拖拽/涂刷 + 右键平移"""
        # 右键拖拽平移
        if self._pan_start is not None and event.buttons() & Qt.RightButton:
            delta = event.position().toPoint() - self._pan_start
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            self._pan_start = event.position().toPoint()
            event.accept()
            return

        # 编辑模式拖拽单位: 拦截所有左键 move, 不传给基类
        if self._drag_target and event.buttons() & Qt.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            g = self.editor._scene_to_grid(sp.x(), sp.y())
            if g:
                gx, gy = g
                d_utype, d_uidx = self._drag_target
                rec = self.editor.records[self.editor._current_idx]
                if d_utype == 'enemy':
                    rec['enemy_xy'][d_uidx*2] = gx
                    rec['enemy_xy'][d_uidx*2+1] = gy
                    self.editor._last_resolved_enemies[d_uidx] = (gx, gy)
                else:
                    rec['ally_xy'][d_uidx*2] = gx
                    rec['ally_xy'][d_uidx*2+1] = gy
                    self.editor._last_resolved_allies[d_uidx] = (gx, gy)
                self.editor._dirty = True
                self.editor._redraw_scene(rerandomize=False)
            event.accept()
            return

        # 编辑模式矩形绘制: 左键拖拽时实时预览矩形区域 (不立即涂刷, 释放时批量填充)
        if self._painting and event.buttons() & Qt.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            g = self.editor._scene_to_grid(sp.x(), sp.y())
            if g:
                self._rect_end = g
                self._hover_grid = g
                self._update_rect_overlay()
                # 状态栏显示矩形尺寸
                gx1, gy1 = self._rect_start or g
                minx, maxx = min(gx1, g[0]), max(gx1, g[0])
                miny, maxy = min(gy1, g[1]), max(gy1, g[1])
                w, h = maxx - minx + 1, maxy - miny + 1
                self.editor.scene_info_var.setText(
                    f"矩形 ({minx},{miny})-({maxx},{maxy}) {w}x{h} | 画笔:{self._terrain_tag(self._brush_value())}")
            event.accept()
            return

        sp = self.mapToScene(event.position().toPoint())
        g = self.editor._scene_to_grid(sp.x(), sp.y())
        if g is None:
            self._hover_grid = None
            self._update_hover_overlay()
            self.editor.scene_info_var.setText("")
            return
        gx, gy = g
        # 更新悬停预览叠加层 (高效, 仅增删2个item, 不触发全场景重绘)
        self._hover_grid = (gx, gy)
        self._update_hover_overlay()
        ed = self.editor
        rec = ed.records[ed._current_idx] if ed._current_idx >= 0 else None

        # 悬停信息: 单位
        unit = ed._find_unit_at(gx, gy) if rec else None
        if unit:
            utype, uidx = unit
            terrain = self._terrain_tag(ed._warway_value_at(gx, gy))
            if utype == 'enemy':
                eid = rec['enemy_ids'][uidx]
                uname = ed._enemy_name(eid)
                orig_x = rec['enemy_xy'][uidx * 2]
                pos_tag = f"区域Z{abs(orig_x)}" if orig_x < 0 else "固定位置"
                ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}] 敌军:{uname} Lv.{rec['enemy_lv'][uidx]} [{pos_tag}]")
            else:
                ally_orig_x = rec['ally_xy'][uidx * 2]
                pos_tag = f"区域Z{abs(ally_orig_x)}" if ally_orig_x < 0 else "固定位置"
                ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}] 友军槽{uidx} [{pos_tag}]")
            return

        # 悬停信息: 宝物
        trea = ed._find_trea_at(gx, gy) if rec else None
        if trea:
            ti, is_fixed = trea
            terrain = self._terrain_tag(ed._warway_value_at(gx, gy))
            label = ed._trea_label(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}"
            if label: ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}] 宝物#{ti} {label} [{type_tag}]")
            else: ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}] 宝物槽#{ti} (空) [{type_tag}]")
            return

        # 悬停信息: 陷阱
        trap = ed._find_trap_at(gx, gy) if rec else None
        if trap:
            ti, is_fixed = trap
            terrain = self._terrain_tag(ed._warway_value_at(gx, gy))
            ttype = ed._trap_type_at(rec, ti)
            tname = TRAP_NAMES_SHORT.get(ttype, '?') + '陷阱'
            pmin, pmax = ed._trap_power_at(rec, ti)
            type_tag = "固定" if is_fixed else f"区域Z{abs(rec['trap_xy'][ti*2])}"
            ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}] 陷阱#{ti} {tname} 威力[{pmin},{pmax}] [{type_tag}]")
            return

        # 悬停信息: 纯地形 (编辑模式追加当前画笔, 便于不看下拉框确认即将涂刷的颜色)
        terrain = self._terrain_tag(ed._warway_value_at(gx, gy)) if rec else ""
        brush_tag = f" | 画笔:{self._terrain_tag(self._brush_value())}" if ed.edit_mode.isChecked() else ""
        if terrain:
            ed.scene_info_var.setText(f"({gx},{gy}) [{terrain}]{brush_tag}")
        else:
            ed.scene_info_var.setText(f"({gx},{gy}){brush_tag}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.editor.edit_mode.isChecked():
            # 编辑模式: 完全自行处理左键, 不传给基类
            sp = self.mapToScene(event.position().toPoint())
            g = self.editor._scene_to_grid(sp.x(), sp.y())
            if g:
                gx, gy = g
                unit = self.editor._find_unit_at(gx, gy)
                if unit:
                    # 拾取单位拖拽
                    self._drag_target = unit
                else:
                    # 矩形绘制模式: 记录起点, 拖拽预览矩形, 释放时批量填充
                    # 单击(无拖拽)时 start==end, 退化为单格涂刷
                    self._rect_start = (gx, gy)
                    self._rect_end = (gx, gy)
                    self._painting = True
                    self._update_rect_overlay()
            event.accept()
            return
        elif event.button() == Qt.RightButton:
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_target:
            self.editor._populate_fields(self.editor.records[self.editor._current_idx])
            self._drag_target = None
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._painting:
            # 矩形绘制: 释放时批量填充从 _rect_start 到 _rect_end 的所有格子
            if self._rect_start and self._rect_end and self.editor._current_idx >= 0:
                gx1, gy1 = self._rect_start
                gx2, gy2 = self._rect_end
                minx, maxx = min(gx1, gx2), max(gx1, gx2)
                miny, maxy = min(gy1, gy2), max(gy1, gy2)
                bval = self._brush_value()
                painted = False
                for gy in range(miny, maxy + 1):
                    for gx in range(minx, maxx + 1):
                        if self.editor._paint_warway_cell(gx, gy, bval):
                            painted = True
                if painted:
                    self.editor._redraw_scene(rerandomize=False)
                self.editor._sync_raw(self.editor.records[self.editor._current_idx])
                cnt = (maxx - minx + 1) * (maxy - miny + 1)
                self.editor.status_var.setText(
                    f"已涂刷 {cnt} 格 ({minx},{miny})-({maxx},{maxy}) [{self._terrain_tag(bval)}]")
            self._rect_start = None
            self._rect_end = None
            self._painting = False
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self._pan_start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """滚轮缩放 (不需要Ctrl)"""
        zooms = [0.25, 0.33, 0.5, 0.66, 0.75, 1.0]
        current = self.editor._preview_zoom
        if event.angleDelta().y() > 0:
            for z in zooms:
                if z > current:
                    self.editor._preview_zoom = z
                    break
        else:
            for z in reversed(zooms):
                if z < current:
                    self.editor._preview_zoom = z
                    break
        self.editor.zoom_combo.setCurrentText(f"{int(self.editor._preview_zoom*100)}%")
        self.editor._wsc_cache.clear()
        self.editor._redraw_scene()


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def main():
    run_editor(WarDataEditorV2)


if __name__ == '__main__':
    main()
