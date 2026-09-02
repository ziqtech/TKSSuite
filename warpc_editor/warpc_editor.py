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
  [267]       物理抵抗
  [268]-[269] 战后奖励 — JP/金
  [270]-[272] 掉落物品 — 3个物品ID
  [273]+     技能效果  — TKKon ID 映射表

用法:
  python warpc_editor.py
"""

import json
import os
import struct
import sys
from functools import partial
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar,
    QSpinBox, QSizePolicy, QMenu, QCompleter, QStackedWidget,
)
from PySide6.QtGui import (
    QColor, QFont, QIcon, QIntValidator, QKeySequence,
)
from PySide6.QtCore import Qt, QTranslator, Signal, QTimer, QSize
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils import theme_manager
from editor_utils.theme_manager import business_colors
from editor_utils.theme_switcher import (
    apply_theme_to_window, toggle_theme_in_family,
)
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.dock_components import DockHeader
from editor_utils.adaptive_table import AdaptiveTableWidget
from editor_utils.picker_dialogs import (
    TktPickerDialog, StatusPickerDialog, STATUS_NAMES, ItemPickerDialog,
    SkillPickerDialog, GrowthTableDialog,
)
from editor_utils.jvg_loader import load_mu_sprites, get_sprite_pixmap
from editor_utils.ui_helpers import make_fake_input, update_path_labels, confirm_close, resolve_config_path, show_field_ref, themed_messagebox, EditorComboBox, NoWheelSpinBox
from editor_utils.version import format_title
from editor_utils.lzss import lzss_decompress_dat, lzss_compress_dat, lzss_decompress_save, lzss_compress_save
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.shared_state import pick_tks_directory
from editor_utils.mod_exporter import (
    diff_records, compute_crc32, generate_mod_json,
    pack_tksmod, build_data_diff_json, ModMetadataDialog, safe_mod_filename,
    load_reference_dat_fields,
    get_tksmod_info, import_tksmod_records, ModImportPreviewDialog, ModExportPreviewDialog,
)
from editor_utils.tab_widget import EditorTabWidget
from editor_utils.search_utils import search_match
from editor_utils.kon_name_resolver import KonNameResolver
# 字段 Schema (唯一字段定义源): 常量/字段列表/FieldDef/打包字节编解码
# noqa: F401,F403 — 旧名称 (WARPC_REC/ALL_NAMED_FIELDS 等) 由 Schema 模块导出,
# 保持本模块命名空间兼容 (batch_skill_learn.py 等外部导入)
from warpc_schema import *  # noqa: F401,F403

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
# 常量与字段定义 — 已迁移至 warpc_schema.py (顶部 from warpc_schema import *)
# ═══════════════════════════════════════════════════════════════


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

# ═══════════════════════════════════════════════════════════════
# 弹窗选择器
# ═══════════════════════════════════════════════════════════════

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
        self.table = AdaptiveTableWidget(
            0, 2,
            stretch_columns={1},
            minimum_widths=[70, 90],
        )
        self.table.setHorizontalHeaderLabels(["TKKon#","名称"])
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
        q = self.search_box.text()
        self.table.setRowCount(0)
        row = 0
        for idx, nm in self.items:
            if not search_match(q, idx, nm):
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
def _build_field_ref_text():
    """WarPC 字段参考文本 (经 ui_helpers.show_field_ref 显示)。"""
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
        ("成长率/物理抵抗 [264]-[267]", GROWTH_FIELDS),
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
    lines.append(f"  全部type=0指令技能(末尾为普通攻击); 每字段=int16 TKKon ID (原版0~649, 补丁扩容后无上限)")
    lines.append("")
    lines.append("【功能说明】")
    lines.append("  Tab 1: 核心属性 (生命/攻防/速度等)")
    lines.append("  Tab 2: 装备与技能配置")
    lines.append("  Tab 3: 技能学习进度 (0=未学, 1~9=学习中, ≥10=已学会)")
    lines.append("  Tab 4: 技能效果判定")
    lines.append("  Tab 5: 全部字段总览")
    return '\n'.join(lines)

# ═══════════════════════════════════════════════════════════════
# 主编辑器窗口
# ═══════════════════════════════════════════════════════════════


class WarpcEditorV2(EditorMainWindow):
    # 信号: 角色编辑已应用 (参数: 角色索引)
    record_applied = Signal(int)

    EDITOR_KEY = "warpc_editor"
    DEFAULT_SIZE = (1400, 850)
    MIN_SIZE = (1100, 680)

    def _init_data(self):
        self.warpc_path = self.tkt_path = None
        self.records = []
        self._draft_records = []   # 共享草稿层: 表单/表格模式均编辑草稿, 「应用」才提交到 records
        self.tkt = {}
        self._original_records = []  # 原始快照，用于 MOD 导出
        self.mu_path = None
        self._mu_sprites = []
        self._icon_pixmaps = {}
        self.skill_names = {}
        self._skill_types = {}
        # 技能树引用图 (从 TKSkill.dat 解析, 语义同 skill_editor):
        #   _skill_children[a]=[(b,w)] 学会a给b累加w进度; _skill_parents[b]=[(a,w)];
        #   _skill_total_in[b]=组外合计入权; _skill_sub_count[a]=子技能数;
        #   _skill_group_heads=[指令技能组头索引]; _skill_group_of[m]=所属组头
        self._skill_children = {}
        self._skill_parents = {}
        self._skill_total_in = {}
        self._skill_sub_count = {}
        self._skill_group_heads = []
        self._skill_group_of = {}
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
        self._edit_snapshot = None      # 表单控件快照 (未应用修改守卫)
        self._field_locator = {}        # fn → (tab索引, 标签控件) 供字段搜索定位
        self._cur_tab_index = -1        # _build_scroll_tab 当前构建中的 tab 索引
        self._table_panel = None        # 表格编辑模式面板 (懒构建)
        self._status_widgets = []
        self._status_resist_widgets = []
        self._skill_learn_widgets = []
        self._suspend_overflow_check = False  # 批量填充技能学习时抑制溢出重算
        self._skill_overflow_label = None     # 技能组「学会超12」溢出提示标签
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

    def _after_build(self):
        self._set_edit_enabled(False)
        self._apply_theme()

    def _extra_help_actions(self):
        return [("字段参考", self._show_field_ref)]

    # ── 主题 ──
    def _apply_theme(self):
        apply_theme_to_window(self, self._theme_id, persist=False)
        self._update_paths()

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self._update_paths()
        self._refresh_table()
        if self._table_panel is not None:
            self._table_panel.apply_theme(self._is_dark)

    # ── 字段定位 / 编辑模式切换 ──
    def _locate_field(self):
        """工具栏字段搜索: 跳转到字段所在 Tab 并临时高亮标签"""
        text = self.field_search.text().strip()
        if not text:
            return
        key = self._field_search_map.get(text)
        if key is None:
            # 模糊包含匹配第一个
            low = text.lower()
            for disp in sorted(self._field_search_map.keys()):
                if low in disp.lower():
                    key = self._field_search_map[disp]
                    break
        if key is None or key not in self._field_locator:
            self.status_var.setText(f"未找到字段: {text}")
            return
        # 表格模式下先切回表单模式
        if self.btn_mode_toggle.isChecked():
            self.btn_mode_toggle.setChecked(False)
        tab_idx, lbl = self._field_locator[key]
        self.tabs.setCurrentIndex(tab_idx)
        scroll = self.tabs.widget(tab_idx)
        if isinstance(scroll, QScrollArea):
            scroll.ensureWidgetVisible(lbl, 50, 120)
        orig = lbl.property("class") or ""
        lbl.setProperty("class", "FlashHint")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

        def _restore_flash():
            lbl.setProperty("class", orig)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        QTimer.singleShot(1500, _restore_flash)

    def _toggle_edit_mode(self, checked):
        """表单模式 ↔ 表格模式切换 (共享 self.records 唯一数据源)"""
        if checked:
            if not self.records:
                self.btn_mode_toggle.blockSignals(True)
                self.btn_mode_toggle.setChecked(False)
                self.btn_mode_toggle.blockSignals(False)
                self.status_var.setText("请先加载 WarPC 数据")
                return
            # 进入表格模式前静默暂存表单控件值到草稿 (两模式共享草稿, 无需弹窗)
            if self._editing_idx >= 0:
                self._flush_widgets_to_draft()
            if self._table_panel is None:
                from warpc_table_mode import WarpcTablePanel
                self._table_panel = WarpcTablePanel(self)
                self._mode_stack.addWidget(self._table_panel)
            self._table_panel.refresh()
            self._mode_stack.setCurrentWidget(self._table_panel)
            self.btn_mode_toggle.setText("📝 表单模式")
        else:
            self._mode_stack.setCurrentIndex(0)
            self.btn_mode_toggle.setText("📊 表格模式")
            # 表格模式可能改动了草稿 → 从草稿刷新表单 (保持未应用状态同步)
            self._refresh_table()
            if 0 <= self._editing_idx < len(self._draft_records):
                self._populate_edit(self._draft_records[self._editing_idx])

    def _on_table_mode_edited(self, rec_idx):
        """表格模式单元格编辑后回调: 仅改草稿, 不置脏不提交"""
        self.status_var.setText(f"角色 #{rec_idx} 已修改 (草稿, 未应用 — 点「应用修改」提交)")

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
            (self.lbl_mu, self.mu_path, "Mu.JVG"),
        ], self._is_dark)

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
        fm.addAction("加载 TKS 目录…", QKeySequence("Ctrl+O"), self._load_tks_dir)
        fm.addAction("加载存档 (从游戏目录)…", QKeySequence("Ctrl+Shift+O"), self._load_save_dir)
        fm.addSeparator()
        fm.addAction("保存", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导出为 MOD (指定参考目录)…", self._export_tksmod_with_ref)
        fm.addSeparator()
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        em = mb.addMenu("编辑(&E)")
        em.addAction("新增角色", QKeySequence("Ctrl+N"), self._add_new)
        em.addAction("复制当前角色", self._copy_record)
        em.addAction("导出当前角色(.warpc)…", self._export_warpc)
        em.addAction("导入角色(.warpc)…", self._import_warpc)

        am = mb.addMenu("分析(&S)")
        am.addAction("成长数据表 (1-60级)", self._show_growth_table)

        self.add_standard_menus(mb)

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
        # 字段定位: 输入字段名/标签后回车跳转到对应 Tab 并高亮
        toolbar.addWidget(QLabel("定位字段:"))
        self.field_search = QLineEdit()
        self.field_search.setFixedWidth(160)
        self.field_search.setPlaceholderText("字段名称…")
        self._field_search_map = {}
        for _fd in FIELD_SCHEMA.values():
            self._field_search_map[f"{_fd.label} [{_fd.index}]"] = _fd.key
        completer = QCompleter(sorted(self._field_search_map.keys()))
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.field_search.setCompleter(completer)
        self.field_search.returnPressed.connect(self._locate_field)
        completer.activated.connect(lambda _t: QTimer.singleShot(0, self._locate_field))
        toolbar.addWidget(self.field_search)
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("🔄 重新加载", clicked=self._reload))
        toolbar.addWidget(QPushButton("🌗 切换主题", clicked=self._toggle_theme))
        toolbar.addStretch()
        # 编辑模式切换: 表单(单角色深度编辑) / 表格(跨角色批量编辑)
        self.btn_mode_toggle = QPushButton("📊 表格模式")
        self.btn_mode_toggle.setCheckable(True)
        self.btn_mode_toggle.setToolTip("在表单编辑与表格批量编辑之间切换")
        self.btn_mode_toggle.toggled.connect(self._toggle_edit_mode)
        toolbar.addWidget(self.btn_mode_toggle)
        toolbar.addSpacing(10)
        toolbar.addWidget(QPushButton("✅ 应用修改", clicked=self._apply_edit))
        toolbar.addWidget(QPushButton("🔄 重置", clicked=self._reset_edit))
        main_layout.addLayout(toolbar)

        # 主 Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        # 中央堆叠容器: page0=表单模式(splitter) page1=表格模式(懒构建)
        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(splitter)
        main_layout.addWidget(self._mode_stack, 1)

        # 左侧：角色列表
        self.table = AdaptiveTableWidget(
            0, 6,
            stretch_columns={1, 4, 5},
            minimum_widths=[44, 90, 44, 60, 55, 55],
            row_height=44,
        )
        self.table.setObjectName("WarpcCharacterTable")
        self.table.setHorizontalHeaderLabels(["#","角色名称","等级","身份","HP","MP"])
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 识别类字段按内容占宽，名称与数值列在剩余空间内受控拉伸。
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)

        # 左侧容器: 角色列表 + 排序按钮栏
        left_panel = QWidget()
        # 预留常见的 "1200/1200" HP/MP 文本宽度，恢复窗口大小后也不截断数值。
        left_panel.setMinimumWidth(420)
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
        self.tabs = EditorTabWidget(
            flat=True,
            object_name="WarpcEditorTabs",
        )
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
        # 主窗口变宽时，左侧列表按比例获得空间，避免只扩大右侧表单。
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 980])

        # 底部路径栏
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(4,2,4,2)
        self.lbl_warpc = QLabel()
        self.lbl_tkt = QLabel()
        self.lbl_item = QLabel()
        self.lbl_skill = QLabel()
        self.lbl_fa = QLabel()
        self.lbl_mu = QLabel()
        for w in [self.lbl_warpc, self.lbl_tkt, self.lbl_item, self.lbl_skill, self.lbl_fa, self.lbl_mu]:
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
        self._cur_tab_index = self.tabs.count() - 1  # 供字段定位注册
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
                    spacer.setObjectName("TransparentBg")
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
        self._field_locator[fn] = (self._cur_tab_index, lbl)  # 字段搜索定位

        ev = QLineEdit()
        self._edit_vars[fn] = ev

        if fn == 'role':
            cb = EditorComboBox()
            cb.addItems(["-1-未激活", "0-已激活"])
            cell.addWidget(make_fake_input(combo=cb))
            self._edit_extras[fn] = cb
        elif fn == 'reaction_group':
            cb = EditorComboBox()
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
            btn.setObjectName("StatusPickerButton")
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
            btn.setObjectName("StatusPickerButton")
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
            btn.setObjectName("StatusPickerButton")
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
            btn.setObjectName("FakeInputRightButton")
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
            btn.setObjectName("FakeInputRightButton")
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
            btn.setObjectName("FakeInputRightButton")
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
            self._field_locator[fn] = (self._cur_tab_index, lbl)  # 字段搜索定位
            cb = EditorComboBox()
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
        self._build_section(p, "成长率/物理抵抗 [528]-[534]", GROWTH_FIELDS, 6)
        self._build_section(p, "战后奖励 [536]-[538]", BATTLE_REWARD_FIELDS, 6)
        self._build_section(p, "可掉落物品 [540]-[544]", DROP_ITEM_FIELDS, 6, 'item_pick')

    def _build_tab3(self):
        """技能学习状态 [176]-[518]"""
        p = self._build_scroll_tab("技能学习")
        self._register_tab_copy(p, 'learn')
        self._skill_learn_labels = []
        self._skill_learn_widgets = []
        grp = QWidget()
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(0,0,0,0)
        gl.setSpacing(0)
        gl.addWidget(DockHeader(f"技能学习状态 [176]-[518] ({SKILL_LEARN_COUNT}技能×1byte)"))
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8,8,8,8)
        bl.addWidget(self._build_learn_toolbar())
        # 存档模式提示 (模板编排工具条隐藏时显示)
        self._learn_mode_hint = QLabel("")
        self._learn_mode_hint.setObjectName("learnModeHint")
        self._learn_mode_hint.setWordWrap(True)
        self._learn_mode_hint.setVisible(False)
        bl.addWidget(self._learn_mode_hint)
        # 技能组「待学习+可学习+已学习」>12 溢出实时提示 (逆向依据 sub_438F28: 战斗菜单共享 12 格固定数组)
        self._skill_overflow_label = QLabel("")
        self._skill_overflow_label.setObjectName("overflowBanner")
        self._skill_overflow_label.setWordWrap(True)
        self._skill_overflow_label.setVisible(False)
        bl.addWidget(self._skill_overflow_label)
        self._skill_learn_grid = QGridLayout()
        self._skill_learn_grid.setVerticalSpacing(2)
        self._skill_learn_grid.setHorizontalSpacing(4)
        bl.addLayout(self._skill_learn_grid)
        self._populate_learn_grid()
        gl.addWidget(body)
        p.layout().addWidget(grp)

    def _populate_learn_grid(self):
        """按当前模式重建技能学习单元格: 存档模式用数字框(手动输入原值 0~255),
        模板模式用带语义标签的下拉框。切换模式时会清空重建。"""
        grid = getattr(self, '_skill_learn_grid', None)
        if grid is None:
            return
        self._clear_layout(grid)
        self._skill_learn_labels = []
        self._skill_learn_widgets = []
        save_mode = bool(getattr(self, '_save_mode', False))
        for i in range(SKILL_LEARN_COUNT):
            r, c = divmod(i, 8)
            sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
            cell = QVBoxLayout()
            cell.setSpacing(1)
            lbl = QLabel(sname[:12])
            lbl.setToolTip(f"[{88+i//2}] {sname}")
            lbl.setProperty("class", "PropLabel")
            cell.addWidget(lbl)
            if save_mode:
                w = NoWheelSpinBox()
                w.setRange(0, 255)
                w.setToolTip("运行时学习进度原值: 0=不会  1~9=等待学  10~19=可以学(待学习)  20+=已学会")
                w.valueChanged.connect(self._check_skill_group_overflow)
            else:
                w = EditorComboBox()
                w.addItems(SKILL_LEARN_STATES)
                w.currentIndexChanged.connect(self._check_skill_group_overflow)
            cell.addWidget(w)
            self._skill_learn_widgets.append((i, w))
            self._skill_learn_labels.append(lbl)
            grid.addLayout(cell, r, c, Qt.AlignTop)
        self._skill_learn_by_idx = {i: w for i, w in self._skill_learn_widgets}


    def _build_learn_toolbar(self):
        """技能学习页顶部工具条 (仅模板模式显示): 技能组智能配置 / 精简当前配置。
        依据游戏机制: 入口技能设「可以学(10)」, 下游技能设「等待学(1)」,
        进游戏后随学习前置自动递进解锁, 避免把整组全设 10 导致列表臃肿且丢失递进关系。
        注: 这些均为「模板(WarPC.dat)编排」工具, 存档模式整体隐藏 (见 _refresh_learn_toolbar_mode)。"""
        self._learn_toolbar_widget = QWidget()
        row = QHBoxLayout(self._learn_toolbar_widget)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(6)
        row.addWidget(QLabel("技能组:"))
        self._skill_group_combo = EditorComboBox()
        self._skill_group_combo.setMinimumWidth(200)
        self._skill_group_combo.addItem("(未加载 TKSkill.dat)", -1)
        row.addWidget(self._skill_group_combo)
        btn_cancel = QPushButton("🚫 取消本组")
        btn_cancel.setToolTip("将本组全部技能设为「不会(0)」; 组外技能保持不变。")
        btn_cancel.clicked.connect(self._cancel_group)
        row.addWidget(btn_cancel)
        btn_cfg = QPushButton("🌱 智能配置本组")
        btn_cfg.setToolTip("入口技能→可以学(10), 下游技能→等待学(1); 组外保持不变。\n进游戏后学会前置会自动解锁下游技能。")
        btn_cfg.clicked.connect(self._smart_config_group)
        row.addWidget(btn_cfg)
        btn_simplify = QPushButton("🧹 精简当前配置")
        btn_simplify.setToolTip("把当前角色冗余的「可以学」(实为下游)降为「等待学」, 修复列表臃肿。\n已学会与未拥有的技能保持不变。")
        btn_simplify.clicked.connect(self._simplify_current_config)
        row.addWidget(btn_simplify)
        row.addStretch()
        return self._learn_toolbar_widget

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
            btn.setObjectName("FakeInputRightButton")
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
            clip.append(self._learn_widget_value(cb))
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
            self._set_learn_widget_value(cb, byte_val)
        self._flush_widgets_to_draft()
        self.status_var.setText(
            f"已粘贴技能学习数据 → 角色 #{self._editing_idx} (草稿, 未应用)")

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
        self._flush_widgets_to_draft()
        self.status_var.setText(
            f"已粘贴技能效果数据 → 角色 #{self._editing_idx} (草稿, 未应用)")

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
        self._flush_widgets_to_draft()
        # 刷新装备/技能名称等额外显示 (物品名、技能名、权限标签)
        self._populate_edit(self._draft_records[self._editing_idx])
        self.status_var.setText(
            f"已粘贴装备与技能数据 → 角色 #{self._editing_idx} (草稿, 未应用)")

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
        d = pick_tks_directory(self)
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
        d = pick_tks_directory(self, "选择 TKS 游戏目录 (含 save 子文件夹)")
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
        table = AdaptiveTableWidget(
            len(slots), 3,
            stretch_columns={2},
            minimum_widths=[50, 150, 90],
        )
        table.setHorizontalHeaderLabels(['槽位', '文件', '摘要'])
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
            # 重建共享草稿层 (与 records 一致, 无待应用修改)
            self._sync_draft_from_records()
            self.skill_names, self._skill_types = self._load_skill_names()
            self._build_skill_graph()
            self.tkkon_names = self._load_tkkon_names()
            self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()

            # 更新技能学习标签
            if hasattr(self, '_skill_learn_labels') and self._skill_learn_labels:
                for i, lbl in enumerate(self._skill_learn_labels):
                    if i < len(self._skill_learn_labels):
                        sname = self.skill_names.get(i, f"技能#{i}") if self.skill_names else f"技能#{i}"
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
            self._draft_records = []
        # 重载后旧的编辑上下文全部失效: 复位编辑状态。
        # 否则 _editing_idx 残留会让下次点选同一编号角色时跳过 populate,
        # 表单控件残留上一文件/槽位的值 (技能学习区为上一角色的值,
        # 技能效果区为重建后的默认值-1), 任何其它字段的修改都会把这些
        # 残留值连带写回, 造成「没改技能数据却被改」的数据损坏。
        self._editing_idx = -1
        self._edit_snapshot = None
        self.preview_name.setText("(未选中)")
        self.preview_meta.setText("")
        self.preview_desc.setText("")
        self.preview_avatar.clear()
        self._update_paths()
        self._set_edit_enabled(True)
        self._refresh_learn_toolbar_mode()
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

    def _build_skill_graph(self):
        """从 TKSkill.dat 解析技能树引用表, 构建进度图 (逆向依据 sub_41E248):
        源技能.ref_skill[i]=目标技能; ref_type[i]=学会源后累加给目标的进度权重;
        目标学习状态处于 [1,10) 时累加, 达≥≥10 即可学习。"""
        self._skill_children = {}
        self._skill_parents = {}
        self._skill_total_in = {}
        self._skill_sub_count = {}
        self._skill_group_heads = []
        self._skill_group_of = {}
        tks_dir = self._get_tks_dir()
        sk_path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path):
            self._refresh_group_combo()
            return
        try:
            with open(sk_path, 'rb') as fp:
                raw = fp.read()
            dec = lzss_decompress(raw)
            if len(raw) % 94 == 0 and (len(dec) == 0 or len(dec) % 94 != 0):
                dec = raw
            n = min(350, len(dec) // 94)
            for i in range(n):
                off = i * 94
                if off + 94 > len(dec):
                    break
                text_id = struct.unpack_from('<h', dec, off)[0]
                stype = struct.unpack_from('<h', dec, off + 4)[0]
                sub = struct.unpack_from('<h', dec, off + 90)[0]
                self._skill_sub_count[i] = sub
                if text_id == 0:
                    continue
                for g in range(8):
                    b = struct.unpack_from('<h', dec, off + 8 + g * 4)[0]
                    w = struct.unpack_from('<h', dec, off + 10 + g * 4)[0]
                    if w == 0 or b <= 0 or b >= n or b == i:
                        continue
                    self._skill_children.setdefault(i, []).append((b, w))
                    self._skill_parents.setdefault(b, []).append((i, w))
                    self._skill_total_in[b] = self._skill_total_in.get(b, 0) + w
                # 指令技能组头: type=0 且 sub_count>0
                if stype == 0 and sub > 0:
                    self._skill_group_heads.append(i)
                    for m in range(i, i + sub + 1):
                        if m < n:
                            self._skill_group_of[m] = i
        except Exception:
            pass
        self._refresh_group_combo()

    def _refresh_group_combo(self):
        """刷新技能学习页的「技能组」下拉框 (列出所有指令技能组头)。"""
        cb = getattr(self, '_skill_group_combo', None)
        if cb is None:
            return
        cb.blockSignals(True)
        cb.clear()
        if not self._skill_group_heads:
            cb.addItem("(未加载 TKSkill.dat)", -1)
            cb.setEnabled(False)
        else:
            cb.setEnabled(True)
            for h in self._skill_group_heads:
                name = self.skill_names.get(h, f"技能#{h}")
                sub = self._skill_sub_count.get(h, 0)
                cb.addItem(f"{name}  (#{h}, {sub}子技能)", h)
        cb.blockSignals(False)
        self._check_skill_group_overflow()  # 技能组数据就绪后刷新溢出提示

    def _skill_group_members(self, head):
        """技能组成员 = 指令技能结构成员 [head, head+sub_count] + 下游进度闭包
        (沿 children 边向下传递, 不吸收其它技能组的结构成员, 不超出可学习范围)。"""
        sub = self._skill_sub_count.get(head, 0)
        members = {head}
        for m in range(head + 1, head + 1 + max(0, sub)):
            if 0 <= m < SKILL_LEARN_COUNT:
                members.add(m)
        stack = list(members)
        while stack:
            a = stack.pop()
            for (b, w) in self._skill_children.get(a, []):
                if b in members or b >= SKILL_LEARN_COUNT:
                    continue
                owner = self._skill_group_of.get(b)
                if owner is not None and owner != head:
                    continue  # 属于其它技能组, 不吸收
                members.add(b)
                stack.append(b)
        return members

    def _compute_group_seed_states(self, members):
        """计算成员最优初始学习状态: 入口(无组内前置)→可学(10), 下游→等待学(1)。
        指令组头统一置 1 (学会成员后自动升级)。按游戏规则作可达性传播,
        无法仅靠组内前置解锁的下游技能列入 unreachable, 不写入 seed (保持原值, 仅提醒)。
        返回 (seed{idx:state}, roots[list], unreachable[list])。"""
        members = set(members)
        total_in = {m: 0 for m in members}
        for m in members:
            for (b, w) in self._skill_children.get(m, []):
                if b in members and w > 0:
                    total_in[b] += w
        seed = {}
        for m in members:
            if self._skill_sub_count.get(m, -1) > 0:
                seed[m] = 1          # 组头: 等待学 (学会成员后自动升级)
            elif total_in[m] == 0:
                seed[m] = 10         # 入口: 无前置 → 可以学
            else:
                seed[m] = 1          # 下游: 等待学
        # 按游戏规则传播 (状态处于 [1,10) 时累加), 验证下游可达性
        progress = dict(seed)
        learned = set()
        changed = True
        while changed:
            changed = False
            for m in members:
                if progress[m] >= 10 and m not in learned:
                    learned.add(m)
                    changed = True
                    for (b, w) in self._skill_children.get(m, []):
                        if b in members and 1 <= progress[b] < 10:
                            progress[b] += w
        unreachable = []
        for m in members:
            if progress[m] < 10 and self._skill_sub_count.get(m, -1) <= 0:
                unreachable.append(m)
                seed.pop(m, None)    # 无法仅靠组内前置解锁 → 保持原值, 仅提醒
        roots = [m for m in members if seed.get(m) == 10]
        return seed, roots, unreachable

    def _learn_item_label(self, byte_val):
        """为非常规学习值生成下拉项文本 (前缀保持 'N-' 供读写/复制/溢出检测解析)。
        游戏语义 (sub_41E248/sub_438F28): 1~9=等待学进度, 10~19=可以学(游戏技能栏显示待学习),
        20+=组技能学会, 30+=子技能学会; 学会前置技能会向下游累加权重, 故存档中常见 2~9/11~19/21 等中间值。"""
        if 1 <= byte_val <= 9:
            return f"{byte_val}-等待学(进度{byte_val})"
        if 10 <= byte_val <= 19:
            return f"{byte_val}-可以学(累积{byte_val})"
        if 20 <= byte_val <= 29:
            return f"{byte_val}-组技能学会(+{byte_val-20})"
        if 30 <= byte_val <= 39:
            return f"{byte_val}-子技能学会(+{byte_val-30})"
        return f"{byte_val}-非常规值"

    def _select_learn_value(self, cb, byte_val):
        """选中下拉框中 byte_val 对应项; 无匹配时按实际字节值动态追加。
        修复: 存档中的中间值 (如 11=可以学+累积) 以前因下拉框缺项被误显示为「0-不会」,
        且保存时会把原值破坏性清零。"""
        for vi in range(cb.count()):
            if cb.itemText(vi).startswith(f'{byte_val}-'):
                cb.setCurrentIndex(vi)
                return
        cb.addItem(self._learn_item_label(byte_val))
        cb.setCurrentIndex(cb.count() - 1)

    @staticmethod
    def _parse_learn_text(text):
        """从下拉文本解析学习字节值 (0~255)。
        兼容预设项「0-不会」与动态项「11-可以学(累积11)」。取起始连续数字, 非法回退 0。"""
        s = (text or '').strip()
        num = ''
        for ch in s:
            if ch.isdigit():
                num += ch
            else:
                break
        try:
            v = int(num) if num else 0
        except ValueError:
            v = 0
        return max(0, min(255, v))

    def _learn_widget_value(self, w):
        """读取学习控件当前值 (0~255)。兼容数字框(存档模式)与下拉框(模板模式)。"""
        if isinstance(w, QSpinBox):
            return int(w.value())
        return self._parse_learn_text(w.currentText())

    def _set_learn_widget_value(self, w, val):
        """写入学习控件。兼容数字框(直接置数)与下拉框(选中/动态追加规范标签)。"""
        val = max(0, min(255, int(val)))
        if isinstance(w, QSpinBox):
            w.setValue(val)
        else:
            self._select_learn_value(w, val)

    def _refresh_learn_toolbar_mode(self):
        """按模式切换技能学习页:
        - 存档模式: 单元格用数字框 (直接输入运行时原值), 整体隐藏模板编排工具条, 显示提示;
        - 模板模式: 单元格用带语义下拉框, 显示编排工具条。
        控件类型与模式不符时重建单元格, 并回填当前角色的值。"""
        if not hasattr(self, '_skill_learn_grid'):
            return
        save_mode = bool(getattr(self, '_save_mode', False))
        cur_is_spin = bool(self._skill_learn_widgets) and isinstance(self._skill_learn_widgets[0][1], QSpinBox)
        if (not self._skill_learn_widgets) or (cur_is_spin != save_mode):
            self._populate_learn_grid()
            # 重建后回填当前角色的学习值 (若正在编辑)
            if 0 <= self._editing_idx < len(self._draft_records):
                self._populate_edit(self._draft_records[self._editing_idx])
        tb = getattr(self, '_learn_toolbar_widget', None)
        if tb is not None:
            tb.setVisible(not save_mode)
        hint = getattr(self, '_learn_mode_hint', None)
        if hint is not None:
            if save_mode:
                hint.setText(
                    "存档模式: 每个技能直接输入运行时学习进度原值 (0~255)。\n"
                    "值含义:  0 = 不会  ·  1 = 等待学 (1~9 为进度累积)  ·  "
                    "10 = 可以学 (10~19 待学习)  ·  20 = 组技能学会  ·  30 = 子技能学会。\n"
                    "模板编排工具 (智能配置 / 精简) 仅在编辑 WarPC.dat 时可用。")
                hint.setVisible(True)
            else:
                hint.setVisible(False)

    def _set_learn_combo(self, skill_idx, state):
        """将技能学习控件设为指定状态值 (不立即写回, 需调用 _apply_edit)。
        走类型无关 helper: 下拉框选中/追加对应项, 数字框直接置数 (防御性, 通常仅模板模式可达)。"""
        w = getattr(self, '_skill_learn_by_idx', {}).get(skill_idx)
        if w is None:
            return False
        self._set_learn_widget_value(w, state)
        return True

    def _smart_config_group(self):
        """智能配置选中技能组: 入口→可以学(10), 下游→等待学(1), 组外保持不变。"""
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if not self._skill_group_heads:
            themed_messagebox(self, QMessageBox.Warning, "未加载技能树",
                "未能从 TKSkill.dat 解析技能树引用表。\n请确认游戏目录下存在 TKSkill.dat。")
            return
        head = self._skill_group_combo.currentData()
        if head is None or head < 0:
            return
        members = self._skill_group_members(head)
        seed, roots, unreachable = self._compute_group_seed_states(members)
        entry = sorted(m for m in members if seed.get(m) == 10)
        waiting = sorted(m for m in members if seed.get(m) == 1)
        gname = self.skill_names.get(head, f"#{head}")

        def nm(i):
            return self.skill_names.get(i, f"#{i}")

        lines = [f"技能组「{gname}」#{head} — 共 {len(members)} 个技能", "",
                 f"● 设为「可以学(10)」入口技能 {len(entry)} 个:",
                 "   " + "、".join(nm(i) for i in entry[:20]) + ("…" if len(entry) > 20 else ""), "",
                 f"● 设为「等待学(1)」下游技能 {len(waiting)} 个 (学会前置后自动解锁):",
                 "   " + "、".join(nm(i) for i in waiting[:30]) + ("…" if len(waiting) > 30 else "")]
        if unreachable:
            lines += ["", f"⚠ {len(unreachable)} 个技能无法仅靠组内前置解锁 → 保持原值不变 (仅提醒, 请手动确认):",
                      "   " + "、".join(nm(i) for i in sorted(unreachable)[:15]) + ("…" if len(unreachable) > 15 else "")]
        lines += ["", "组外技能保持不变。确定应用?"]
        if QMessageBox.question(self, "智能配置预览", "\n".join(lines),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for m, st in seed.items():
            self._set_learn_combo(m, st)
        self._apply_edit()
        kept = f", 保留{len(unreachable)}个仅提醒" if unreachable else ""
        self.status_var.setText(
            f"已智能配置「{gname}」: 入口{len(entry)} / 等待{len(waiting)}{kept} (共{len(members)}技能)")

    def _cancel_group(self):
        """取消选中技能组: 将本组全部技能设为「不会(0)」, 组外保持不变。"""
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if not self._skill_group_heads:
            themed_messagebox(self, QMessageBox.Warning, "未加载技能树",
                "未能从 TKSkill.dat 解析技能树引用表。\n请确认游戏目录下存在 TKSkill.dat。")
            return
        head = self._skill_group_combo.currentData()
        if head is None or head < 0:
            return
        members = self._skill_group_members(head)
        member_list = sorted(members)
        gname = self.skill_names.get(head, f"#{head}")

        def nm(i):
            return self.skill_names.get(i, f"#{i}")

        lines = [f"技能组「{gname}」#{head} — 共 {len(members)} 个技能", "",
                 "● 全部设为「不会(0)」:",
                 "   " + "、".join(nm(i) for i in member_list[:30]) + ("…" if len(member_list) > 30 else ""),
                 "", "组外技能保持不变。确定应用?"]
        if QMessageBox.question(self, "取消本组预览", "\n".join(lines),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for m in members:
            self._set_learn_combo(m, 0)
        self._apply_edit()
        self.status_var.setText(
            f"已取消「{gname}」: {len(members)} 个技能设为不会")

    def _simplify_current_config(self):
        """精简当前角色配置: 将处于学习态(1~19)的技能重新按入口→10/下游→1 规范化,
        把冗余的「可以学」(实为下游)降为「等待学」, 修复历史臃肿数据。
        已学会(20/30)与未拥有(0)的技能保持不变。"""
        if self._editing_idx < 0:
            self.status_var.setText("请先选择角色")
            return
        if not self._skill_children and not self._skill_total_in:
            themed_messagebox(self, QMessageBox.Warning, "未加载技能树",
                "未能解析 TKSkill.dat 技能树, 无法精简。")
            return
        cur = {}
        for skill_idx, cb in self._skill_learn_widgets:
            cur[skill_idx] = self._learn_widget_value(cb)
        tree = {i for i, v in cur.items() if 1 <= v < 20}
        if not tree:
            themed_messagebox(self, QMessageBox.Information, "无需精简",
                "当前角色没有处于「等待学/可以学」状态的技能。")
            return
        seed, roots, unreachable = self._compute_group_seed_states(tree)
        demote = [i for i in tree if cur[i] >= 10 and seed.get(i) == 1]     # 可学→等待
        promote = [i for i in tree if cur[i] < 10 and seed.get(i) == 10]    # 等待→可学(入口)
        changed = [i for i in tree if i in seed and cur[i] != seed[i]]
        if not changed:
            themed_messagebox(self, QMessageBox.Information, "无需精简",
                "当前配置已是最简形态 (入口=可学, 下游=等待学)。")
            return

        def nm(i):
            return self.skill_names.get(i, f"#{i}")

        lines = [f"分析当前角色 {len(tree)} 个在学技能:", "",
                 f"● {len(demote)} 个「可以学」实为下游 → 降为「等待学(1)」:",
                 "   " + "、".join(nm(i) for i in sorted(demote)[:20]) + ("…" if len(demote) > 20 else "")]
        if promote:
            lines += ["", f"● {len(promote)} 个入口技能 → 提升为「可以学(10)」:",
                      "   " + "、".join(nm(i) for i in sorted(promote)[:15])]
        if unreachable:
            lines += ["", f"⚠ {len(unreachable)} 个技能无法仅靠组内前置解锁 → 保持原值不变 (仅提醒):",
                      "   " + "、".join(nm(i) for i in sorted(unreachable)[:15]) + ("…" if len(unreachable) > 15 else "")]
        lines += ["", f"共 {len(changed)} 处改动。已学会(20/30)与未拥有(0)的技能保持不变。", "确定应用?"]
        if QMessageBox.question(self, "精简配置预览", "\n".join(lines),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for i in tree:
            if i in seed:
                self._set_learn_combo(i, seed[i])
        self._apply_edit()
        self.status_var.setText(
            f"已精简: {len(demote)}个降为等待学, 共{len(changed)}处改动")

    def _check_skill_group_overflow(self, *args):
        """实时检测: 同一指令技能组内「待学习(1~9)+可学习(10)+已学习(20/30)」的技能数是否超过 12。
        战斗技能菜单 (sub_438F28/sub_447BA8) 把本组已学子技能写入仅 12 格的固定数组 word_9D6D1A
        (memset 0x18=24字节=12项) 且无越界检查, 超过 12 个会溢出踩坏相邻数据 → 战斗菜单错乱。
        因待学习/可学习技能进游戏后会逐步变为已学习, 故按「非不会(≠0)」总数作前瞻性提示。"""
        lbl = getattr(self, '_skill_overflow_label', None)
        if lbl is None or getattr(self, '_suspend_overflow_check', False):
            return
        if self._editing_idx < 0 or not self._skill_group_heads or not self._skill_learn_widgets:
            lbl.setVisible(False)
            lbl.setText("")
            return
        # 读取当前 UI 各技能学习状态 (即时反映编辑中的改动)
        states = {}
        for skill_idx, cb in self._skill_learn_widgets:
            states[skill_idx] = self._learn_widget_value(cb)
        offenders = []
        for head in self._skill_group_heads:
            sub = self._skill_sub_count.get(head, 0)
            if sub <= 0:
                continue
            # 战斗子技能列表扫描范围 = [head+1, head+sub] (与 sub_438F28 一致, 不含组头)
            cnt = sum(1 for m in range(head + 1, head + 1 + sub)
                      if 0 <= m < SKILL_LEARN_COUNT and states.get(m, 0) != 0)
            if cnt > 12:
                gname = self.skill_names.get(head, f"#{head}")
                offenders.append(f"「{gname}」#{head}: {cnt}个")
        if offenders:
            lbl.setText("⚠ 以下技能组「待学习+可学习+已学习」已超过 12 个，"
                        "进入战斗后该组技能菜单会数据溢出 (仅能容纳 12 项)，请将其控制在 12 个以内：\n"
                        + "；".join(offenders))
            lbl.setVisible(True)
        else:
            lbl.setVisible(False)
            lbl.setText("")

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
        q = self.search_entry.text()
        self.filtered_indices = []
        for rec in self.records:
            if q:
                nm = self._char_name(rec)
                if not search_match(q, rec['index'], nm, rec['fields'][2], rec['fields'][3]):
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
            tag_color = QColor("#2266CC") if role_val==-1 else QColor("#CC3333") if role_val==0 else QColor("#dcdcdc")  # 阶段 2 豁免: 角色标记领域色
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
            self._edit_snapshot = None
            self.preview_name.setText("(未选中)")
            self.preview_meta.setText("")
            self.preview_desc.setText("请在左侧列表中选择角色。")
            self.preview_avatar.clear()
            return
        idx = int(self.table.item(sel[0].row(), 0).text())
        if idx == self._editing_idx and self._edit_snapshot is not None:
            return
        # 切换角色前静默暂存到草稿 (不弹窗, 统一由「应用修改」提交)
        if self._editing_idx >= 0:
            self._flush_widgets_to_draft()
        self._populate_edit(self._draft_records[idx])

    def _capture_snapshot(self):
        """抓取当前表单全部控件值的快照 (用于未应用修改检测)"""
        snap = {}
        for fn, w in self._edit_vars.items():
            snap[fn] = w.text()
        for fn in ('role', 'reaction_group'):
            if fn in self._edit_extras:
                snap['combo_' + fn] = self._edit_extras[fn].currentIndex()
        for fs_fn, fo, cb, dur in self._status_widgets:
            snap['slot_' + fs_fn] = (cb.currentIndex(), dur.text())
        for byte_idx, ev in self._status_resist_widgets:
            snap[f'resist_{byte_idx}'] = ev.text()
        for skill_idx, cb in self._skill_learn_widgets:
            # 必须用类型无关取值: 存档模式控件是 QSpinBox, 无 currentText()
            snap[f'learn_{skill_idx}'] = self._learn_widget_value(cb)
        for i, ev in getattr(self, '_skill_effect_widgets', []):
            snap[f'effect_{i}'] = ev.text()
        return snap

    def _has_unapplied_changes(self):
        return (self._edit_snapshot is not None
                and self._capture_snapshot() != self._edit_snapshot)

    # ── 共享草稿层 (表单/表格模式公用, 「应用修改」才提交到 records) ──
    def _sync_draft_from_records(self):
        """草稿重建为与 records 一致 (丢弃全部待应用修改)"""
        self._draft_records = [{'index': r['index'], 'fields': list(r['fields'])}
                               for r in self.records]

    def _has_pending_draft(self):
        """草稿中是否存在尚未应用到 records 的修改"""
        if len(self._draft_records) != len(self.records):
            return False
        return any(d['fields'] != r['fields']
                   for d, r in zip(self._draft_records, self.records))

    def _commit_draft(self):
        """将全部草稿修改提交到 records, 返回变更的角色编号列表"""
        changed = []
        for d, r in zip(self._draft_records, self.records):
            if d['fields'] != r['fields']:
                r['fields'] = list(d['fields'])
                changed.append(r['index'])
        if changed:
            self._dirty = True
            for i in changed:
                self.record_applied.emit(i)
        return changed

    def _ensure_draft_resolved(self):
        """保存/导出/结构操作前处理待应用草稿; 返回 False 表示用户取消"""
        self._flush_widgets_to_draft()
        if not self._has_pending_draft():
            return True
        ret = self._prompt_unapplied()
        if ret == QMessageBox.Cancel:
            return False
        if ret == QMessageBox.Apply:
            violations = self._validate_draft()
            if violations:
                self._show_draft_violations(violations)
                return False
            self._commit_draft()
        else:  # Discard: 草稿回退到已应用状态
            self._sync_draft_from_records()
            if 0 <= self._editing_idx < len(self._draft_records):
                self._populate_edit(self._draft_records[self._editing_idx])
            if self._table_panel is not None:
                self._table_panel.model.reload()
        return True

    def _validate_draft(self):
        """应用前终检: 校验待应用草稿的取值域 (仅检查用户改动过的值,
        文件自带的异常值不阻断)。返回 [(角色#, 名称, 字段, 当前值, 合法域)]"""
        violations = []
        enum_fields = []
        for fd in FIELD_SCHEMA.values():
            if fd.ftype == 'enum' and fd.enum_items:
                domain = set()
                for it in fd.enum_items:
                    try:
                        domain.add(parse_enum_value(it))
                    except ValueError:
                        pass
                enum_fields.append((fd, domain))
        for d, r in zip(self._draft_records, self.records):
            if d['fields'] == r['fields']:
                continue  # 无待应用修改
            f, rf = d['fields'], r['fields']
            nm = self._char_name(d)
            for fd, domain in enum_fields:
                v = f[fd.index]
                if v not in domain and v != rf[fd.index]:
                    dom_str = '/'.join(str(x) for x in sorted(domain))
                    violations.append((d['index'], nm, fd.label, v, dom_str))
            for i in range(8):
                sid = get_packed_byte(f, STATUS_SLOT_BASE, i * 2)
                if (sid > len(STATUS_NAMES)
                        and sid != get_packed_byte(rf, STATUS_SLOT_BASE, i * 2)):
                    violations.append((d['index'], nm, f'状态槽{i}状态ID', sid,
                                       f'0-{len(STATUS_NAMES)}'))
        return violations

    def _show_draft_violations(self, violations):
        lines = [f"#{i} {nm} — {label}: {v}  (合法值: {dom})"
                 for i, nm, label, v, dom in violations[:15]]
        if len(violations) > 15:
            lines.append(f"… 等共 {len(violations)} 处")
        QMessageBox.warning(self, "存在非法取值, 未应用",
            "以下字段的值超出合法范围, 请修正后再应用:\n\n" + '\n'.join(lines))
        self.status_var.setText(f"应用被阻止: {len(violations)} 处非法取值")

    def _prompt_unapplied(self):
        """弹出未应用修改三选框, 返回 QMessageBox.Apply/Discard/Cancel"""
        pend = sum(1 for d, r in zip(self._draft_records, self.records)
                   if d['fields'] != r['fields'])
        box = QMessageBox(self)
        box.setWindowTitle("未应用的修改")
        box.setText(f"有 {pend} 个角色的修改尚未应用。")
        box.setInformativeText("是否应用这些修改?")
        box.setStandardButtons(QMessageBox.Apply | QMessageBox.Discard | QMessageBox.Cancel)
        box.button(QMessageBox.Apply).setText("应用修改")
        box.button(QMessageBox.Discard).setText("放弃修改")
        box.button(QMessageBox.Cancel).setText("取消")
        box.setIcon(QMessageBox.Question)
        return box.exec()

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
            self._suspend_overflow_check = True   # 批量填充期间抑制逐项重算
            for skill_idx, cb in self._skill_learn_widgets:
                field_idx = 88 + skill_idx//2
                is_high = skill_idx%2
                unsigned = f[field_idx] & 0xFFFF
                byte_val = (unsigned>>(8*is_high)) & 0xFF
                self._set_learn_widget_value(cb, byte_val)
            self._suspend_overflow_check = False
            self._check_skill_group_overflow()   # 填充完毕后统一计算一次同组溢出提示
            # 刷新技能名称标签 (嵌入模式下 skill_names 可能在 Tab 构建后才加载)
            if self.skill_names and hasattr(self, '_skill_learn_labels'):
                for i, lbl in enumerate(self._skill_learn_labels):
                    sname = self.skill_names.get(i, f"技能#{i}")
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

        # 刷新快照 (未应用修改守卫基准)
        self._edit_snapshot = self._capture_snapshot()

    # ── 弹窗 ──
    def _make_skill_picker(self, parent):
        """构建技能选择弹窗 (表单模式/表格编辑模式共用)。"""
        type_names = {0: "指令", 1: "主动", 2: "被动", 3: "移动"}
        rows = []
        for idx in sorted(self.skill_names.keys()):
            tid = self._skill_types.get(idx, -1)
            rows.append((idx, (str(idx), type_names.get(tid, "?"), self.skill_names[idx]), tid))
        return SkillPickerDialog(
            parent, rows, ("技能#", "类型", "名称"),
            stretch_columns={2}, minimum_widths=[55, 55, 90],
            clear_value=-1, clear_label="清空(-1)", size=(550, 520))

    def _pick_skill(self, fn):
        if not self.skill_names: return
        dlg = self._make_skill_picker(self)
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
        inner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid = QGridLayout(inner)
        grid.setSpacing(2)
        large_indices = [(si, si//2) for si in range(0, len(self._fa_sprites), 2) if self._fa_sprites[si] is not None]
        COLS = 8
        for sprite_idx, portrait_idx in large_indices:
            r, c = divmod(portrait_idx, COLS)
            tile = QWidget()
            tile.setFixedSize(78, 94)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(2, 1, 2, 1)
            tile_layout.setSpacing(2)

            btn = QPushButton()
            btn.setObjectName("PortraitTile")
            btn.setFixedSize(74, 74)
            btn.setCursor(Qt.PointingHandCursor)
            if portrait_idx == cur_val:
                btn.setProperty("selected", "true")
            else:
                btn.setProperty("selected", "false")
            pix = self._get_fa_photo(sprite_idx, (70, 70))
            if pix:
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(70, 70))
            else:
                btn.setText("👤")
            btn.clicked.connect(lambda checked, v=portrait_idx: (self._edit_vars[fn].setText(str(v)), dlg.accept()))
            tile_layout.addWidget(btn)
            index_label = QLabel(str(portrait_idx))
            index_label.setObjectName("PortraitIndex")
            index_label.setAlignment(Qt.AlignCenter)
            tile_layout.addWidget(index_label)
            grid.addWidget(tile, r, c, Qt.AlignTop)
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
        """应用修改: 表单控件→草稿, 终检取值域, 再将全部待应用草稿提交到 records"""
        if not self.records:
            return
        self._flush_widgets_to_draft()
        violations = self._validate_draft()
        if violations:
            self._show_draft_violations(violations)
            return
        changed = self._commit_draft()
        cur = self._editing_idx
        if hasattr(self, 'table') and self.table.isVisible():
            self._refresh_table()
            for r in range(self.table.rowCount()):
                if int(self.table.item(r, 0).text()) == cur:
                    self.table.selectRow(r)
                    break
        if self._table_panel is not None:
            self._table_panel.model.reload()
        if hasattr(self, 'status_var'):
            if changed:
                self.status_var.setText(f"已应用 {len(changed)} 个角色的修改 (内存, 未保存)")
            else:
                self.status_var.setText("没有需要应用的修改")

    def _flush_widgets_to_draft(self):
        """表单控件当前值 → 当前角色草稿 (不提交到 records)"""
        if self._editing_idx < 0 or self._editing_idx >= len(self._draft_records):
            return
        # 控件未改动时跳过: 避免 populate/flush 往返将等价编码归一化
        # (如空状态槽 0 → -256) 产生幻影差异
        if not self._has_unapplied_changes():
            return
        rec = self._draft_records[self._editing_idx]
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
                byte_val = self._learn_widget_value(cb)
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

        # 刷新快照基准 (草稿已吸收控件值)
        self._edit_snapshot = self._capture_snapshot()

    def _reset_edit(self):
        """重置: 当前角色草稿回退为已应用值并刷新表单"""
        if 0 <= self._editing_idx < len(self.records):
            self._draft_records[self._editing_idx]['fields'] = \
                list(self.records[self._editing_idx]['fields'])
            self._populate_edit(self._draft_records[self._editing_idx])
            if self._table_panel is not None:
                self._table_panel.model.reload()
            self.status_var.setText(f"角色 #{self._editing_idx} 草稿已重置为已应用值")

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
        self._draft_records.append({'index': new_idx, 'fields': list(fields)})
        self._dirty = True
        self._apply_filter()
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == new_idx:
                self.table.selectRow(r)
                break
        self.status_var.setText(f"已新增角色 #{new_idx} (内存, 未保存)")

    def _copy_record(self):
        if self._editing_idx < 0: return
        # 以草稿为源 (复制用户当前看到/编辑中的状态)
        self._flush_widgets_to_draft()
        src = self._draft_records[self._editing_idx]
        new_idx = len(self.records)
        self.records.append({'index': new_idx, 'fields': list(src['fields'])})
        self._draft_records.append({'index': new_idx, 'fields': list(src['fields'])})
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
        # 交换前先静默暂存当前编辑: flush 必须落在交换前的正确槽位。
        # 若留到交换后由 selectRow 触发, 控件值会被写进对方角色的槽位,
        # 导致相邻角色整体被覆盖 (含技能学习/技能效果区)。
        if self._editing_idx >= 0:
            self._flush_widgets_to_draft()
        editing = self._editing_idx
        # 整体交换两条记录的字段数据 (槽位号 index 不变, 数据互换位置); 草稿同步交换
        self.records[cur_idx]['fields'], self.records[tgt_idx]['fields'] = \
            self.records[tgt_idx]['fields'], self.records[cur_idx]['fields']
        self._draft_records[cur_idx]['fields'], self._draft_records[tgt_idx]['fields'] = \
            self._draft_records[tgt_idx]['fields'], self._draft_records[cur_idx]['fields']
        # 编辑状态跟随数据移动: 控件仍显示被移动角色的值, 槽位指向数据新位置,
        # 避免后续 flush 写错槽位
        if editing == cur_idx:
            self._editing_idx = tgt_idx
        elif editing == tgt_idx:
            self._editing_idx = cur_idx
        self._dirty = True
        self._refresh_table()
        # 选择跟随数据: 选中目标行, 使被移动的角色保持选中
        self.table.selectRow(tgt_row)
        self.status_var.setText(f"已交换 #{cur_idx} ↔ #{tgt_idx} (内存, 未保存)")

    def _export_warpc(self):
        if self._editing_idx < 0: return
        # 导出当前草稿状态 (所见即所导)
        self._flush_widgets_to_draft()
        rec = self._draft_records[self._editing_idx]
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
            self._draft_records.append({'index': new_idx, 'fields': list(fields)})
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
        # 待应用草稿守卫: 保存前必须先应用或放弃
        if not self._ensure_draft_resolved():
            return
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
        # 待应用草稿守卫: MOD 差异基于 records, 导出前先应用或放弃
        if not self._ensure_draft_resolved():
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
        # 待应用草稿守卫: 差异基于 records
        if not self._ensure_draft_resolved():
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
        self._sync_draft_from_records()
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
        dlg = GrowthTableDialog(self, rec, char_name,
                                 theme_id=self._theme_id)
        dlg.exec()

    # ── 帮助 ──
    def _show_field_ref(self):
        show_field_ref(self, _build_field_ref_text(), size=(700, 600))

    # 逆向参考: sub_42234C, sub_41E40C, sub_422BBC, sub_4173F8, sub_45343C, sub_452B14
    # _show_help 为动态内容 (含当前记录数), 覆盖基类静态 HELP_TEXT 版本
    def _show_help(self):
        cnt = len(self.records) if self.records else WARPC_ORIG_COUNT
        themed_messagebox(self, QMessageBox.Information, "帮助说明",
            f"功能: 编辑《三国群侠传》战斗角色数据\n"
            f"数据: {cnt} 角色 × {WARPC_REC} 字节 (原游戏 {WARPC_ORIG_COUNT} 角色, 支持动态扩展)\n\n"
            f"特性:\n"
            f"  · Godot 风格深/浅色主题切换\n"
            f"  · 分页编辑: 核心属性 / 装备技能 / 技能学习 / 效果判定 / 全部字段\n"
            f"  · 自动关联 TKItem.dat 显示物品名称")

    def closeEvent(self, event):
        # 待应用草稿守卫 (含表单控件未暂存的修改)
        self._flush_widgets_to_draft()
        if self._has_pending_draft():
            ret = self._prompt_unapplied()
            if ret == QMessageBox.Cancel:
                event.ignore()
                return
            if ret == QMessageBox.Apply:
                violations = self._validate_draft()
                if violations:
                    self._show_draft_violations(violations)
                    event.ignore()
                    return
                self._commit_draft()
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()

def main():
    run_editor(WarpcEditorV2, "WarPC Editor")

if __name__ == '__main__':
    main()
