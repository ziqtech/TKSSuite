#!/usr/bin/env python3
"""
TKShop.dat 可视化编辑器 (PySide6 重构版)

逆向依据:
  - sub_45343C: DAT 文件统一加载 (LZSS 解压, 8字节/条, 240条, 基址 unk_9508A0)
  - sub_452B14: LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_4244CC: 商店过滤 (*(a1+56) 匹配 area_id, condition 判定逻辑)
  - sub_4246D8: 商品信息读取 (word_77CBCC[32*item_ref] 取 TKItem ID)
  - sub_40EBD4 case 50: Shop(a1,a2,a3) 脚本指令, a3=area_id → sub_40D804 → sub_4233C4
  - sub_4233C4: a1[28]=a3, a2 作为缓存键

TKShop.dat 格式 (每条 8 字节, 共 240 条):
  [0:2] int16 area_id   — 商店库存表索引 (0=药店,1=道具,2=武器防具,3=杂货,4=饰品,9=无)
  [2:4] int16 item_ref  — TKItem 数组下标 (0-599)
  [4:6] int16 condition — 出现条件: 1=随机, >1=等级门槛, ≤0=始终
  [6]   byte  display   — 显示标志 (sub_4244CC: ==1 表示已显示/可购买)
  [7]   byte  reserved  — 保留

LZSS 文件头 (sub_45343C 读取):
  [0:4] uint32 decompressed_size  (1920 = 8×240)
  [4:8] uint32 block_size         (含下面4字节)
  [8:12] uint32 decompressed_size (重复)
  [12:] LZSS 压缩流

用法:
  python shop_editor_pyside6.py
"""

import struct
import os
import re
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLabel,
    QLineEdit, QComboBox, QSpinBox, QRadioButton, QButtonGroup, QTextEdit,
    QFileDialog, QMessageBox, QDialog, QFrame, QAbstractItemView
)
from PySide6.QtGui import (
    QColor, QFont, QAction, QKeySequence, QShortcut, QIcon, QPalette
)
from PySide6.QtCore import Qt


# ============================================================
# LZSS 解压 (逆向自 sub_452B14, sub_45343C)
# ============================================================

def lzss_decompress(data):
    """LZSS 解压 — 精确还原 sub_452B14 + sub_45343C

    sub_45343C 流程:
      fread(&v5, 4) → v5 = decompressed_size
      fread(&v5, 4) → v5 = block_size
      v4 = malloc(block_size)
      fread(v4, block_size)
      sub_452B14(v4, &v5, out)

    sub_452B14 算法:
      窗口: 4096 字节, 初始填充 0x20
      win_pos 起始: 4078 (0xFEE)
      flags: 8位标志, bit=1→字面量, bit=0→回溯引用
      回溯: 12bit offset + 4bit length
            实际复制长度 = (length编码 + 2) + 1 = length编码 + 3
    """
    if len(data) < 12:
        return b''

    target_size = struct.unpack_from('<I', data, 0)[0]
    block_size = struct.unpack_from('<I', data, 4)[0]

    window = bytearray([0x20] * 4096)
    win_pos = 4078   # sub_452B14: v16 = 4078
    out = bytearray()
    flags = 0
    pos = 12          # 跳过 [decomp_size:4][block_size:4][decomp_size:4]
    byte_count = 4    # 已计 block 内 4 字节头

    while byte_count < block_size:
        flags >>= 1
        if (flags & 0x100) == 0:
            if pos >= len(data):
                break
            flags = data[pos] | 0xFF00
            pos += 1
            byte_count += 1

        if flags & 1:
            # 字面量: 直接输出
            if pos >= len(data):
                break
            b = data[pos]
            pos += 1
            byte_count += 1
            out.append(b)
            window[win_pos] = b
            win_pos = (win_pos + 1) & 0xFFF
        else:
            # 回溯引用
            if pos + 1 >= len(data):
                break
            b1 = data[pos]
            b2 = data[pos + 1]
            pos += 2
            byte_count += 2
            ref_offset = ((b2 & 0xF0) << 4) | b1     # 12-bit offset
            ref_length = (b2 & 0x0F) + 2              # 4-bit length (+2 base)
            for j in range(ref_length + 1):           # 复制 length+1 字节
                b = window[(j + ref_offset) & 0xFFF]
                out.append(b)
                window[win_pos] = b
                win_pos = (win_pos + 1) & 0xFFF

    return bytes(out[:target_size])


# ============================================================
# LZSS 压缩 (逆向自 sub_452B14 的逻辑逆操作)
# ============================================================

def lzss_compress(data):
    """LZSS 压缩 — 与 sub_452B14 解压算法兼容

    算法:
      1. 窗口初始 0x20, 起始位置 4078
      2. 对每个输入字节, 在窗口中搜索最长匹配 (3-18 字节)
      3. 匹配长度≥3: 输出回溯引用 (2字节)
      4. 否则: 输出字面量 (1字节)
      5. 每 8 个 token 打包一个 flag 字节

    输出格式 (sub_45343C 兼容):
      [decompressed_size:4][block_size:4]
      [decompressed_size:4][lzss_compressed_stream...]
    """
    src = data
    src_len = len(src)

    window = bytearray([0x20] * 4096)
    win_pos = 4078

    # 输出缓冲区
    out_tokens = []  # (is_literal, value_or_offset_length)

    pos = 0
    while pos < src_len:
        best_len = 0
        best_offset = 0

        max_search = min(18, src_len - pos)
        min_match = 3

        for length in range(max_search, min_match - 1, -1):
            if best_len >= length:
                break
            pattern = src[pos:pos + length]
            for offset in range(4096):
                match = True
                for j in range(length):
                    if window[(offset + j) & 0xFFF] != pattern[j]:
                        match = False
                        break
                if match:
                    best_len = length
                    best_offset = offset
                    break
            if best_len >= length:
                break

        if best_len >= min_match:
            if win_pos <= best_offset + best_len:
                best_len = win_pos - best_offset
            if best_len >= min_match:
                out_tokens.append((False, best_offset, best_len))
                for j in range(best_len):
                    window[win_pos] = src[pos + j]
                    win_pos = (win_pos + 1) & 0xFFF
                pos += best_len
                continue
                
        b = src[pos]
        out_tokens.append((True, b, 0))
        window[win_pos] = b
        win_pos = (win_pos + 1) & 0xFFF
        pos += 1

    stream = bytearray()
    token_idx = 0
    while token_idx < len(out_tokens):
        flag_byte = 0
        batch_end = min(token_idx + 8, len(out_tokens))

        for i in range(token_idx, batch_end):
            is_lit = out_tokens[i][0]
            if is_lit:
                flag_byte |= (1 << (i - token_idx))

        stream.append(flag_byte)

        for i in range(token_idx, batch_end):
            is_lit = out_tokens[i][0]
            if is_lit:
                stream.append(out_tokens[i][1])
            else:
                offset = out_tokens[i][1]
                length = out_tokens[i][2]
                enc_len = length - 3
                b1 = offset & 0xFF
                b2 = ((offset >> 4) & 0xF0) | (enc_len & 0x0F)
                stream.append(b1)
                stream.append(b2)

        token_idx = batch_end

    decomp_size = src_len
    block_data = struct.pack('<I', decomp_size) + bytes(stream)
    block_size = len(block_data)

    result = struct.pack('<II', decomp_size, block_size) + block_data
    return result


# ============================================================
# TKItem 名称加载 (逆向自 sub_424A2C, sub_4067E8)
# ============================================================

def load_tkitem_with_tkt(item_dat_path, tkt_dat_path):
    """
    加载 TKItem 并关联 TKT 名称, 同时提取 equip_type 用于分类筛选
    field[0]=item_id, field[1]=tab_code, field[5]=equip_type (word_77CBD4, sub_41928C)
    """
    with open(item_dat_path, 'rb') as f:
        raw = f.read()
    decompressed = lzss_decompress(raw)
    REC_SIZE = 64

    items_raw = []
    for i in range(min(600, len(decompressed) // REC_SIZE)):
        off = i * REC_SIZE
        item_id = struct.unpack_from('<h', decompressed, off)[0]
        tab_code = struct.unpack_from('<h', decompressed, off + 2)[0]
        name_id = struct.unpack_from('<h', decompressed, off + 4)[0]
        equip_type = struct.unpack_from('<h', decompressed, off + 10)[0]  # field[5]
        items_raw.append((i, item_id, tab_code, name_id, equip_type))

    tkt_lookup = {}
    if tkt_dat_path and os.path.exists(tkt_dat_path):
        with open(tkt_dat_path, 'rb') as f:
            raw = f.read()
        total_size = struct.unpack_from('<I', raw, 0)[0]
        count = struct.unpack_from('<I', raw, 4)[0]
        encrypted = raw[8:8 + total_size]
        decrypted = bytes([b ^ 0xFF for b in encrypted])
        id_table_size = count * 4
        offset_table_size = count * 4
        
        # TKT ID 0-9 是系统消息 (sub_4067E8)
        SYSTEM_IDS = set(range(0, 10))

        for i in range(count):
            eid = struct.unpack_from('<i', decrypted, i * 4)[0]
            if eid in SYSTEM_IDS:
                continue
            off = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0]
            text_base = id_table_size + offset_table_size
            abs_off = text_base + off
            if abs_off < len(decrypted):
                end = abs_off
                while end < len(decrypted) and decrypted[end] != 0:
                    end += 1
                text = decrypted[abs_off:end].replace(b'\x1e', b'\n')
                try:
                    tkt_lookup[eid] = text.decode('big5', errors='replace')
                except:
                    tkt_lookup[eid] = text.decode('gbk', errors='replace')

    result = []
    for idx, item_id, tab_code, name_id, equip_type in items_raw:
        if name_id > 0 and name_id in tkt_lookup:
            name = tkt_lookup[name_id]
            if name and name != '0':
                name = name.split('\n')[0].strip()
            else:
                name = ""
        else:
            name = ""
        if not name or name == "0":
            name = f"Item#{item_id}" if item_id else f"(空-{idx})"
        result.append((idx, item_id, tab_code, name_id, equip_type, name))

    return result


# ============================================================
# TKShop 数据模型 (逆向自 sub_4244CC, sub_4246D8)
# ============================================================

AREA_NAMES = {0: "药店", 1: "道具", 2: "武器防具", 3: "杂货", 4: "饰品", 9: "无"}

def area_label(area_id):
    return AREA_NAMES.get(area_id, f"未知({area_id})")

REC_SIZE = 8

def load_shop_data(filepath):
    """加载 TKShop.dat (固定 240 条, sub_45343C a3=1920)"""
    with open(filepath, 'rb') as f:
        raw = f.read()

    decompressed = lzss_decompress(raw)
    FIXED_COUNT = 240
    records = []

    for i in range(FIXED_COUNT):
        offset = i * REC_SIZE
        if offset + REC_SIZE > len(decompressed):
            break
        area_id = struct.unpack_from('<h', decompressed, offset)[0]
        item_ref = struct.unpack_from('<h', decompressed, offset + 2)[0]
        condition = struct.unpack_from('<h', decompressed, offset + 4)[0]
        display = decompressed[offset + 6]
        reserved = decompressed[offset + 7]

        records.append({
            'index': i,
            'area_id': area_id,
            'item_ref': item_ref,
            'condition': condition,
            'display': display,
            'reserved': reserved,
        })

    return records

def save_shop_data(filepath, records):
    """保存 TKShop.dat (LZSS 压缩)

    sub_45343C 调用: sub_45343C("TKShop.dat", &unk_9508A0, 1920)
    第19行检查: if (decompressed_size <= 1920) ... else ERROR
    必须恰好 240 条记录 (1920 字节), 否则游戏拒绝加载!
    """
    FIXED_COUNT = 240
    buf = bytearray(FIXED_COUNT * REC_SIZE)
    for rec in records[:FIXED_COUNT]:
        i = rec['index']
        offset = i * REC_SIZE
        struct.pack_into('<h', buf, offset, rec['area_id'])
        struct.pack_into('<h', buf, offset + 2, rec['item_ref'])
        struct.pack_into('<h', buf, offset + 4, rec['condition'])
        buf[offset + 6] = rec['display']
        buf[offset + 7] = rec.get('reserved', 0)

    compressed = lzss_compress(bytes(buf))

    # Verify round-trip
    verify = lzss_decompress(compressed)
    if len(verify) != len(buf) or verify != bytes(buf):
        raise RuntimeError("压缩回写验证失败! 数据不一致.")

    with open(filepath, 'wb') as f:
        f.write(compressed)
    return True

# tab_code → 商店区域约束 (sub_4233C4 switch + sub_4246D8 过滤)
TAB_TO_SHOP = {
    0: [0, 3],       # 消耗品 → 药店, 杂货
    1: [1, 3],       # 书籍 → 道具店, 杂货
    2: [2],          # 武器 → 武器防具
    3: [2],          # 防具 → 武器防具
    4: [4],          # 饰品 → 饰品店
    5: [],           # 特殊 → 不显示在商店
}

# ============================================================
# 深浅色主题管理器 (来自 spritesheet_editor_v2.py)
# ============================================================

class ThemeManager:
    """QSS 主题管理器 — 优先从 themes/ 目录加载 Godot 风格 QSS，缺失时回退 QPalette"""

    @staticmethod
    def _themes_dir() -> str:
        return os.path.join(os.path.dirname(__file__), "..", "editor_themes")

    @staticmethod
    def _load_qss(theme: str) -> str:
        """读取 QSS 文件并将 url() 路径转为绝对路径"""
        qss_file = os.path.join(ThemeManager._themes_dir(), f"{theme}.qss")
        if not os.path.exists(qss_file):
            return ""
        with open(qss_file, "r", encoding="utf-8") as f:
            qss = f.read()
        themes_dir = os.path.dirname(qss_file).replace("\\", "/")
        qss = re.sub(r"url\(([^)]+)\)", lambda m: f"url({themes_dir}/{m.group(1)})", qss)
        return qss

    @staticmethod
    def apply_theme(widget, theme: str) -> None:
        """对指定 widget 应用主题 (dark / light)，QSS 缺失时自动回退 QPalette"""
        qss = ThemeManager._load_qss(theme)
        if qss:
            widget.setStyleSheet(qss)
        elif theme == "dark":
            widget.setStyleSheet("")
            widget.setPalette(ThemeManager._dark_palette())
        else:
            widget.setStyleSheet("")
            widget.setPalette(ThemeManager._light_palette())

    @staticmethod
    def apply_dark_theme(app: QApplication) -> None:
        ThemeManager.apply_theme(app, "dark")

    @staticmethod
    def apply_light_theme(app: QApplication) -> None:
        ThemeManager.apply_theme(app, "light")

    # ── QPalette 后备方案 ──────────────────────────────

    @staticmethod
    def _dark_palette() -> QPalette:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(30, 30, 30))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipBase, Qt.black)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        return palette

    @staticmethod
    def _light_palette() -> QPalette:
        return QApplication.style().standardPalette()


# ============================================================
# 物品选择对话框 (PySide6)
# ============================================================

class ItemPickerDialog(QDialog):
    def __init__(self, parent, items, item_names):
        super().__init__(parent)
        self.setWindowTitle("选择物品")
        self.resize(650, 520)
        self.setModal(True)
        
        self.items = items
        self.item_names = item_names
        self.selected_item_ref = -1

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部搜索
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self._refresh_list)
        top_layout.addWidget(self.search_input)
        layout.addLayout(top_layout)

        # 过滤选项
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("分类:"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(["全部分类", "消耗品", "书籍", "武器", "防具", "饰品", "特殊"])
        self.cat_combo.currentIndexChanged.connect(self._refresh_list)
        filter_layout.addWidget(self.cat_combo)

        filter_layout.addWidget(QLabel("商店:"))
        self.shop_combo = QComboBox()
        self.shop_combo.addItem("全部商店")
        for aid, aname in sorted(AREA_NAMES.items()):
            self.shop_combo.addItem(aname, userData=aid)
        self.shop_combo.currentIndexChanged.connect(self._refresh_list)
        filter_layout.addWidget(self.shop_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 列表
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["索引", "分类", "可用商店", "物品名称"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 140)
        self.table.cellDoubleClicked.connect(self._on_accept)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.lbl_count = QLabel()
        btn_layout.addWidget(self.lbl_count)
        btn_layout.addStretch()
        
        btn_ok = QPushButton("✔ 确定")
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.setMinimumWidth(90)
        btn_ok.clicked.connect(self._on_accept)
        btn_layout.addWidget(btn_ok)

        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.setMinimumWidth(90)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)

    def _cat_name(self, tab_code):
        return {0: "消耗品", 1: "书籍", 2: "武器", 3: "防具", 4: "饰品", 5: "特殊"}.get(tab_code, "其他")

    def _shops_for_tab(self, tab_code):
        area_ids = TAB_TO_SHOP.get(tab_code, [])
        if not area_ids:
            return "无"
        return ", ".join(AREA_NAMES.get(a, str(a)) for a in area_ids)

    def _refresh_list(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        
        q = self.search_input.text().strip().lower()
        cat_idx = self.cat_combo.currentIndex()
        cat_allowed = None if cat_idx == 0 else [cat_idx - 1]
        
        shop_idx = self.shop_combo.currentIndex()
        filter_aid = None if shop_idx == 0 else self.shop_combo.currentData()

        row_data = []
        for idx, item_id, tab_code, name_id, equip_type, name in self.items:
            if not name or name.startswith("(空") or name.startswith("Item#") or name == "0":
                continue
            if q and q not in name.lower():
                continue
            if cat_allowed is not None and tab_code not in cat_allowed:
                continue
            if filter_aid is not None:
                if filter_aid not in TAB_TO_SHOP.get(tab_code, []):
                    continue
            row_data.append((idx, self._cat_name(tab_code), self._shops_for_tab(tab_code), name))

        self.table.setRowCount(len(row_data))
        for r, data in enumerate(row_data):
            # 将索引存为整数格式以便正确排序
            idx_item = QTableWidgetItem()
            idx_item.setData(Qt.DisplayRole, data[0])
            self.table.setItem(r, 0, idx_item)
            
            self.table.setItem(r, 1, QTableWidgetItem(data[1]))
            self.table.setItem(r, 2, QTableWidgetItem(data[2]))
            self.table.setItem(r, 3, QTableWidgetItem(data[3]))

        self.table.setSortingEnabled(True)
        self.lbl_count.setText(f"共 {len(self.items)} 件物品 | 当前显示 {len(row_data)} 件")
        
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _on_accept(self):
        row = self.table.currentRow()
        if row >= 0:
            self.selected_item_ref = int(self.table.item(row, 0).data(Qt.DisplayRole))
            self.accept()



# ============================================================
# Dock 面板组件 (来自 tkt_editor_v5)
# ============================================================

class DockHeader(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)


# ============================================================
# GUI 编辑器 (PySide6)
# ============================================================

class ShopEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TKShop.dat 可视化编辑器 (PySide6)")
        self.resize(1100, 680)
        self.setMinimumSize(950, 550)

        # 窗口图标
        ico_path = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

        self.shop_path = None
        self.item_path = None
        self.tkt_path = None
        
        self.records = []
        self.items = []
        self.item_names = {}
        self.filtered_indices = []
        
        self._dirty = False
        self._editing_idx = -1

        app_inst = QApplication.instance()
        self._is_dark = app_inst.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_inst else True

        self._build_ui()
        self._update_path_labels()
        self._set_edit_enabled(False)
        
        self.sort_col = 0
        self.sort_reverse = False

    # ================================================================
    # UI 构建
    # ================================================================

    def _create_dock(self, title, widget_content):
        """Dock 面板包裹 — 与 tkt_editor_v5 完全一致"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(DockHeader(title))
        body = QWidget()
        body.setObjectName("DockBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.addWidget(widget_content)
        layout.addWidget(body, 1)
        return container

    def _build_ui(self):
        # ---- 菜单栏 ----
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        
        action_load = QAction("加载 TKS 目录…", self)
        action_load.setShortcut(QKeySequence("Ctrl+O"))
        action_load.triggered.connect(self._load_tks_dir)
        file_menu.addAction(action_load)
        
        file_menu.addSeparator()
        
        action_save = QAction("保存", self)
        action_save.setShortcut(QKeySequence("Ctrl+S"))
        action_save.triggered.connect(self._save)
        file_menu.addAction(action_save)
        
        action_export = QAction("导出 CSV…", self)
        action_export.triggered.connect(self._export_csv)
        file_menu.addAction(action_export)
        
        file_menu.addSeparator()
        action_exit = QAction("退出", self)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        help_menu = menubar.addMenu("帮助")
        action_help = QAction("使用说明", self)
        action_help.triggered.connect(self._show_help)
        help_menu.addAction(action_help)
        action_about = QAction("关于", self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)

        # ---- 中心部件 ----
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ---- 工具栏区域 ----
        toolbar_layout = QHBoxLayout()
        
        toolbar_layout.addWidget(QLabel("区域:"))
        self.area_filter_combo = QComboBox()
        self.area_filter_combo.addItem("全部")
        for k, v in AREA_NAMES.items():
            self.area_filter_combo.addItem(f"{k}-{v}", userData=k)
        self.area_filter_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar_layout.addWidget(self.area_filter_combo)

        toolbar_layout.addSpacing(10)
        toolbar_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setFixedWidth(150)
        self.search_input.returnPressed.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_input)
        
        btn_search = QPushButton("🔍 搜索")
        btn_search.clicked.connect(self._apply_filter)
        toolbar_layout.addWidget(btn_search)

        btn_clear = QPushButton("🧹 清除")
        btn_clear.clicked.connect(self._clear_filter)
        toolbar_layout.addWidget(btn_clear)

        # 分隔线
        vline1 = QFrame()
        vline1.setFrameShape(QFrame.VLine)
        vline1.setFrameShadow(QFrame.Sunken)
        toolbar_layout.addWidget(vline1)

        btn_add = QPushButton("➕ 新增记录")
        btn_add.clicked.connect(self._add_record)
        toolbar_layout.addWidget(btn_add)

        btn_reload = QPushButton("🔄 重新加载")
        btn_reload.clicked.connect(self._reload)
        toolbar_layout.addWidget(btn_reload)

        vline2 = QFrame()
        vline2.setFrameShape(QFrame.VLine)
        vline2.setFrameShadow(QFrame.Sunken)
        toolbar_layout.addWidget(vline2)

        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self._toggle_theme)
        toolbar_layout.addWidget(btn_theme)

        toolbar_layout.addStretch()
        
        self.lbl_status = QLabel("请通过 文件 → 加载 TKS 目录 打开数据")
        self.lbl_status.setStyleSheet("color: gray;")
        toolbar_layout.addWidget(self.lbl_status)
        
        main_layout.addLayout(toolbar_layout)

        # ---- 左右分栏 ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # 左侧: 表格
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["索引", "区域ID", "区域名称", "物品索引", "物品名称", "出现条件"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 70)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(5, 100)

        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_click)

        splitter.addWidget(self.table)

        # 右侧: 编辑面板
        self.edit_content = QWidget()
        edit_layout = QVBoxLayout(self.edit_content)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_rec_idx = QLabel("未选中")
        font_bold = QFont()
        font_bold.setBold(True)
        font_bold.setPointSize(11)
        self.lbl_rec_idx.setFont(font_bold)
        edit_layout.addWidget(self.lbl_rec_idx)

        # Area
        edit_layout.addWidget(QLabel("区域:"))
        self.edit_area_combo = QComboBox()
        for k, v in sorted(AREA_NAMES.items()):
            self.edit_area_combo.addItem(v, userData=k)
        self.edit_area_combo.currentIndexChanged.connect(self._on_area_changed)
        edit_layout.addWidget(self.edit_area_combo)
        
        self.lbl_compat = QLabel("")
        self.lbl_compat.setWordWrap(True)
        edit_layout.addWidget(self.lbl_compat)

        # Item
        edit_layout.addWidget(QLabel("物品:"))
        item_row = QHBoxLayout()
        self.lbl_editing_item_idx = QLabel("")
        self.lbl_editing_item_idx.setFont(font_bold)
        item_row.addWidget(self.lbl_editing_item_idx)
        
        self.lbl_item_name = QLabel("(未选择)")
        self.lbl_item_name.setStyleSheet("color: #4282DA; font-weight: bold;")
        item_row.addWidget(self.lbl_item_name, 1)
        
        btn_pick_item = QPushButton("📦 选择物品…")
        btn_pick_item.clicked.connect(self._pick_item)
        item_row.addWidget(btn_pick_item)
        edit_layout.addLayout(item_row)

        edit_layout.addSpacing(10)

        # Condition
        edit_layout.addWidget(QLabel("出现条件:"))
        cond_row = QHBoxLayout()
        self.cond_group = QButtonGroup(self)
        
        self.radio_random = QRadioButton("随机")
        self.radio_always = QRadioButton("始终")
        self.radio_custom = QRadioButton("幸运:")
        self.cond_group.addButton(self.radio_random)
        self.cond_group.addButton(self.radio_always)
        self.cond_group.addButton(self.radio_custom)
        self.cond_group.buttonClicked.connect(self._on_cond_mode)
        
        cond_row.addWidget(self.radio_random)
        cond_row.addWidget(self.radio_always)
        cond_row.addWidget(self.radio_custom)
        
        self.spin_cond = QSpinBox()
        self.spin_cond.setRange(-999, 999)
        self.spin_cond.valueChanged.connect(self._on_cond_changed)
        cond_row.addWidget(self.spin_cond)
        cond_row.addStretch()
        edit_layout.addLayout(cond_row)

        # Probability Table
        self.txt_cond_table = QTextEdit()
        self.txt_cond_table.setReadOnly(True)
        self.txt_cond_table.setMaximumHeight(160)
        self.txt_cond_table.setStyleSheet("font-family: Consolas, 'Microsoft YaHei UI'; font-size: 12px;")
        edit_layout.addWidget(self.txt_cond_table)

        edit_layout.addStretch()

        # Action Buttons
        btn_action_row = QHBoxLayout()
        btn_apply = QPushButton("✅ 应用修改")
        btn_apply.clicked.connect(self._apply_edit)
        btn_action_row.addWidget(btn_apply, 1)
        
        btn_delete = QPushButton("❌ 删除")
        btn_delete.clicked.connect(self._delete_record)
        btn_action_row.addWidget(btn_delete)
        edit_layout.addLayout(btn_action_row)

        splitter.addWidget(self._create_dock("编辑记录", self.edit_content))
        splitter.setSizes([700, 400])

        # ---- 底部: 文件路径 ----
        path_content = QWidget()
        path_layout = QHBoxLayout(path_content)
        path_layout.setContentsMargins(4, 4, 4, 0)

        self.lbl_shop_path = QLabel("(TKShop.dat 未挂载)")
        self.lbl_item_path = QLabel("(TKItem.dat 未挂载)")
        self.lbl_tkt_path = QLabel("(TKT.dat 未挂载)")

        path_layout.addWidget(self.lbl_shop_path)
        path_layout.addWidget(self._make_v_sep())
        path_layout.addWidget(self.lbl_item_path)
        path_layout.addWidget(self._make_v_sep())
        path_layout.addWidget(self.lbl_tkt_path)
        path_layout.addStretch()

        main_layout.addWidget(path_content)

    # ================================================================
    # 状态与主题管理
    # ================================================================

    def _set_edit_enabled(self, enabled):
        self.edit_content.setEnabled(enabled)

    def _make_v_sep(self):
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFrameShadow(QFrame.Sunken); sep.setStyleSheet("color: #777;")
        return sep

    def _update_path_labels(self):
        cg = ("color: #55b572;" if self._is_dark else "color: #178a39;")
        cr = ("color: #e27d60;" if self._is_dark else "color: #c93b16;")
        def _f(lb, path, label):
            if not path or not os.path.exists(path):
                lb.setText(f"({label} 未挂载)")
                lb.setStyleSheet(cr)
            else:
                lb.setText(f"{label}: {path}")
                lb.setStyleSheet(cg)
        _f(self.lbl_shop_path, self.shop_path, "TKShop.dat")
        _f(self.lbl_item_path, self.item_path, "TKItem.dat")
        _f(self.lbl_tkt_path, self.tkt_path, "TKT.dat")

    def _apply_theme(self):
        qss = ThemeManager._load_qss("dark" if self._is_dark else "light")
        if qss:
            self.setStyleSheet(qss)
        elif self._is_dark:
            self.setStyleSheet("")
            self.setPalette(ThemeManager._dark_palette())
        else:
            self.setStyleSheet("")
            self.setPalette(ThemeManager._light_palette())

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._apply_theme()
        self._update_path_labels()
        self._refresh_table()

    # ================================================================
    # 数据加载
    # ================================================================

    def _load_tks_dir(self):
        tks_dir = QFileDialog.getExistingDirectory(self, "选择 TKS 游戏目录 (包含 TKShop.dat / TKItem.dat / TKT.dat)")
        if not tks_dir:
            return

        shop = os.path.join(tks_dir, "TKShop.dat")
        item = os.path.join(tks_dir, "TKItem.dat")
        tkt  = os.path.join(tks_dir, "TKT.dat")

        missing = []
        for p, n in [(shop, "TKShop.dat"), (item, "TKItem.dat")]:
            if not os.path.exists(p):
                missing.append(n)

        if missing:
            QMessageBox.warning(self, "文件缺失", f"目录中未找到: {', '.join(missing)}\n\n请确认选择了正确的 TKS 目录。")
            return

        self.shop_path = shop
        self.item_path = item
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self._reload()

    def _reload(self):
        if not self.shop_path:
            return

        self.lbl_status.setText("加载中…")
        QApplication.processEvents()

        if self.item_path and os.path.exists(self.item_path):
            self.items = load_tkitem_with_tkt(self.item_path, self.tkt_path or "")
            self.item_names = {it[0]: it[5] for it in self.items}

        try:
            self.records = load_shop_data(self.shop_path)
            self._dirty = False
            self.lbl_status.setText(f"已加载 {len(self.records)} 条商店记录 + {len(self.items)} 个物品")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载 TKShop.dat:\n{e}")
            self.records = []

        self._update_path_labels()
        self._set_edit_enabled(True)
        self._apply_filter()

    # ================================================================
    # 过滤 & 表格
    # ================================================================

    def _apply_filter(self):
        area_filter_idx = self.area_filter_combo.currentIndex()
        search_text = self.search_input.text().strip().lower()

        self.filtered_indices = []
        for rec in self.records:
            if area_filter_idx > 0:
                fid = self.area_filter_combo.currentData()
                if rec['area_id'] != fid:
                    continue
            if search_text:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                cond_str = self._cond_str(rec['condition'])
                search_target = f"{rec['index']} {rec['area_id']} {area_label(rec['area_id'])} {rec['item_ref']} {iname} {cond_str}".lower()
                if search_text not in search_target:
                    continue
            self.filtered_indices.append(rec['index'])

        self._refresh_table()
        self.lbl_status.setText(f"显示 {len(self.filtered_indices)} / {len(self.records)} 条  |  文件 → 保存 (Ctrl+S) 写入磁盘")

    def _clear_filter(self):
        self.search_input.clear()
        self.area_filter_combo.setCurrentIndex(0)
        self._apply_filter()

    def _cond_str(self, cond):
        if cond == 1:
            return "随机抽选"
        return f"幸运{cond:+d}"

    def _refresh_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.filtered_indices))

        color_random = QColor("#D4883A") if self._is_dark else QColor("#CC6600")

        for r, idx in enumerate(self.filtered_indices):
            rec = self.records[idx]
            iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
            cond_str = self._cond_str(rec['condition'])

            item_idx = QTableWidgetItem()
            item_idx.setData(Qt.DisplayRole, rec['index'])
            item_idx.setData(Qt.UserRole, rec['index']) # 缓存原始索引
            
            item_aid = QTableWidgetItem()
            item_aid.setData(Qt.DisplayRole, rec['area_id'])
            
            item_aname = QTableWidgetItem(area_label(rec['area_id']))
            
            item_iref = QTableWidgetItem()
            item_iref.setData(Qt.DisplayRole, rec['item_ref'])
            
            item_iname = QTableWidgetItem(iname)
            item_cond = QTableWidgetItem(cond_str)
            
            # 条件着色
            if rec['condition'] == 1:
                for col_item in (item_idx, item_aid, item_aname, item_iref, item_iname, item_cond):
                    col_item.setForeground(color_random)

            self.table.setItem(r, 0, item_idx)
            self.table.setItem(r, 1, item_aid)
            self.table.setItem(r, 2, item_aname)
            self.table.setItem(r, 3, item_iref)
            self.table.setItem(r, 4, item_iname)
            self.table.setItem(r, 5, item_cond)

    def _on_header_click(self, logicalIndex):
        if self.sort_col == logicalIndex:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = logicalIndex
            self.sort_reverse = False

        keys = {0: 'index', 1: 'area_id', 2: 'area_id', 3: 'item_ref', 4: 'item_ref', 5: 'condition'}
        key = keys.get(logicalIndex, 'index')
        
        self.filtered_indices.sort(key=lambda i: self.records[i].get(key, 0), reverse=self.sort_reverse)
        self._refresh_table()

    # ================================================================
    # 右侧编辑面板
    # ================================================================

    def _on_table_select(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        
        # 从第一列的 UserRole 获取真正的记录 index
        idx = selected[0].data(Qt.UserRole)
        rec = self.records[idx]
        self._populate_edit(rec)

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        self.lbl_rec_idx.setText(f"记录 #{rec['index']}")
        
        # area
        idx = self.edit_area_combo.findData(rec['area_id'])
        if idx >= 0:
            self.edit_area_combo.setCurrentIndex(idx)
            
        # item
        self.lbl_editing_item_idx.setText(str(rec['item_ref']))
        iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
        self.lbl_item_name.setText(iname)
        self._update_compat_label(rec['area_id'], rec['item_ref'])
        
        # condition
        cond = rec['condition']
        self.spin_cond.blockSignals(True)
        self.spin_cond.setValue(cond)
        self.spin_cond.blockSignals(False)
        
        if cond == 1:
            self.radio_random.setChecked(True)
        elif cond <= -100:
            self.radio_always.setChecked(True)
        else:
            self.radio_custom.setChecked(True)
            
        self._on_cond_mode()

    def _get_item_tab(self, item_ref):
        for it in self.items:
            if it[0] == item_ref:
                return it[2]
        return -1

    def _update_compat_label(self, area_id, item_ref):
        item_tab = self._get_item_tab(item_ref)
        allowed = TAB_TO_SHOP.get(item_tab, [])
        
        color_ok = "#4CAF50" if self._is_dark else "#228B22"
        color_err = "#E57373" if self._is_dark else "#CC3333"

        if area_id in allowed:
            self.lbl_compat.setText("✓ 该物品可在此商店出现")
            self.lbl_compat.setStyleSheet(f"color: {color_ok};")
        elif not allowed:
            self.lbl_compat.setText("⚠ 该物品不会在任何商店出现")
            self.lbl_compat.setStyleSheet(f"color: {color_err};")
        else:
            shop_names = [AREA_NAMES.get(a, str(a)) for a in allowed]
            self.lbl_compat.setText(f"⚠ 不兼容! 该物品仅适用于: {', '.join(shop_names)}")
            self.lbl_compat.setStyleSheet(f"color: {color_err};")

    def _on_area_changed(self):
        if self._editing_idx < 0:
            return
        try:
            item_ref = int(self.lbl_editing_item_idx.text())
        except ValueError:
            return
        area_id = self.edit_area_combo.currentData()
        self._update_compat_label(area_id, item_ref)

    def _on_cond_mode(self):
        if self.radio_random.isChecked():
            self.spin_cond.setValue(1)
            self.spin_cond.setEnabled(False)
        elif self.radio_always.isChecked():
            self.spin_cond.setValue(-100)
            self.spin_cond.setEnabled(False)
        else:
            self.spin_cond.setEnabled(True)
        self._refresh_cond_table()

    def _on_cond_changed(self):
        if self.radio_custom.isChecked():
            self._refresh_cond_table()

    def _refresh_cond_table(self):
        offset = self.spin_cond.value()
        
        if offset == 1 and self.radio_random.isChecked():
            self.txt_cond_table.setPlainText(
                "  (随机抽选模式)\n  每次进入商店时随机判定\n  最多同时出现5件商品"
            )
            return

        if offset > 0:
            desc = f"队伍最大幸运 ＞ {offset} 时开始出现"
        elif offset == 0:
            desc = f"队伍最大幸运 ≥ 1 时开始出现"
        else:
            desc = f"队伍最大幸运 ≥ 0 时已有 {min(100, -offset)}% 概率"

        lines = [f"  {desc}", f"  每多1点幸运, 概率+1%", ""]
        
        for pct in [25, 50, 75, 100]:
            need_luk = offset + pct
            if need_luk >= 0:
                label = "必定出现" if pct >= 100 else ""
                lines.append(f"  幸运 ≥ {need_luk:>3d}  →  {pct:>3d}%  {label}")

        header = f"  条件值: {offset:+d}"
        self.txt_cond_table.setPlainText(header + '\n' + '\n'.join(lines))

    def _pick_item(self):
        dialog = ItemPickerDialog(self, self.items, self.item_names)
        if dialog.exec() == QDialog.Accepted:
            picked = dialog.selected_item_ref
            if picked >= 0:
                self.lbl_editing_item_idx.setText(str(picked))
                self.lbl_item_name.setText(self.item_names.get(picked, f"Item#{picked}"))
                self._on_area_changed() # 更新兼容性验证

    def _apply_edit(self):
        if self._editing_idx < 0:
            return
            
        rec = self.records[self._editing_idx]
        rec['area_id'] = self.edit_area_combo.currentData()
        rec['item_ref'] = int(self.lbl_editing_item_idx.text())
        rec['condition'] = self.spin_cond.value()
        
        self._dirty = True
        self._apply_filter()
        
        # 重新选中编辑行
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == rec['index']:
                self.table.selectRow(r)
                break
                
        self.lbl_status.setText(f"记录 #{rec['index']} 已修改 (内存, 未保存到磁盘)")

    def _delete_record(self):
        if self._editing_idx < 0:
            return
        if QMessageBox.question(self, "确认删除", f"确定要清空记录 #{self._editing_idx} 吗?\n\n记录将被重置为零值, 而非物理删除。") != QMessageBox.Yes:
            return
            
        self.records[self._editing_idx] = {
            'index': self._editing_idx, 'area_id': 0, 'item_ref': 0,
            'condition': 0, 'display': 0, 'reserved': 0
        }
        self._dirty = True
        self._apply_filter()

    def _add_record(self):
        FIXED_COUNT = 240
        while len(self.records) < FIXED_COUNT:
            self.records.append({
                'index': len(self.records), 'area_id': 0, 'item_ref': 0,
                'condition': 0, 'display': 0, 'reserved': 0
            })

        for rec in self.records[:FIXED_COUNT]:
            if rec['area_id'] == 0 and rec['item_ref'] == 0 and rec['condition'] == 0:
                self._dirty = True
                self._apply_filter()
                
                for r in range(self.table.rowCount()):
                    if self.table.item(r, 0).data(Qt.UserRole) == rec['index']:
                        self.table.selectRow(r)
                        self.table.scrollToItem(self.table.item(r, 0))
                        break
                        
                self.lbl_status.setText(f"选中空槽 #{rec['index']}, 请在右侧编辑后应用修改")
                return

        QMessageBox.warning(self, "已满", "240 条记录全部非空, 无法新增。\n请先删除一条旧记录腾出空槽。")

    # ================================================================
    # 保存 & 导出
    # ================================================================

    def _save(self):
        if not self.shop_path or not self.records:
            QMessageBox.information(self, "提示", "请先通过 文件 → 加载 TKS 目录 打开数据")
            return

        if QMessageBox.question(self, "确认保存", f"将保存 {len(self.records)} 条记录到:\n{self.shop_path}\n\n原文件将被覆盖。继续?") != QMessageBox.Yes:
            return

        try:
            with open(self.shop_path, 'rb') as src:
                with open(self.shop_path + ".bak", 'wb') as dst:
                    dst.write(src.read())
        except:
            pass

        try:
            save_shop_data(self.shop_path, self.records)
            self._dirty = False
            self.lbl_status.setText(f"已保存 {len(self.records)} 条记录 → {self.shop_path}")
            QMessageBox.information(self, "保存成功", f"已保存 {len(self.records)} 条记录\n备份: {self.shop_path}.bak")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _export_csv(self):
        if not self.records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "", "CSV files (*.csv)")
        if not path:
            return
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write("索引,区域ID,区域名称,物品索引,物品名称,出现条件(原始),出现条件(文本)\n")
            for rec in self.records:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                f.write(f"{rec['index']},{rec['area_id']},{area_label(rec['area_id'])},"
                        f"{rec['item_ref']},{iname},{rec['condition']},{self._cond_str(rec['condition'])}\n")
        self.lbl_status.setText(f"已导出 CSV: {path}")
        QMessageBox.information(self, "导出成功", f"已导出 {len(self.records)} 条")

    def _show_help(self):
        QMessageBox.information(self, "使用说明",
            "TKShop.dat 可视化编辑器\n\n"
            "1. 文件 → 加载 TKS 目录: 选择包含 TKShop.dat / TKItem.dat / TKT.dat 的目录\n"
            "2. 左侧表格: 单击行查看/编辑, 支持区域过滤和关键词搜索, 点击表头可排序\n"
            "3. 右侧面板: 修改区域/物品/出现条件/显示标志, 点「应用修改」保存到内存\n"
            "4. 文件 → 保存 (Ctrl+S): 将内存中的修改写入 TKShop.dat\n"
            "5. + 新增记录: 在240条中查找空槽位复用\n"
            "6. 出现条件 (基于队伍最高幸运 LUK):\n"
            "   - 随机: 每次进入商店时随机抽选 (最多5件)\n"
            "   - 始终: 设为-100, 任意幸运值都100%出现\n"
            "   - 幸运: 出现概率 = clamp(幸运 - 条件值, 0, 100)%\n"
            "7. 物品与区域有兼容性限制 (由游戏代码决定):\n"
            "   选择物品后区域下方会显示是否兼容及建议放置的商店")

    def _show_about(self):
        QMessageBox.information(self, "关于",
            "TKShop.dat 可视化编辑器 (PySide6 重构版)\n\n"
            "基于《三国群侠传》(TKS) 逆向工程\n"
            "支持 TKShop.dat 的加载、编辑、保存\n"
            "自动关联 TKItem.dat + TKT.dat 显示物品名称")

# ============================================================
# 入口
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("TKShop Editor")

    # 根据系统主题设置初始主题
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    if is_dark:
        ThemeManager.apply_dark_theme(app)
    else:
        ThemeManager.apply_light_theme(app)

    window = ShopEditorWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == '__main__':
    main()