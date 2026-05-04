#!/usr/bin/env python3
"""
TKShop.dat 可视化编辑器

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
  python shop_editor.py [TKShop.dat路径] [TKItem.dat路径]
"""

import struct
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

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
        # 在窗口中搜索最长匹配
        best_len = 0
        best_offset = 0

        max_search = min(18, src_len - pos)
        min_match = 3

        for length in range(max_search, min_match - 1, -1):
            if best_len >= length:
                break
            pattern = src[pos:pos + length]
            # 在窗口中线性搜索 (后续可优化为哈希)
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
            out_tokens.append((False, best_offset, best_len))
            for j in range(best_len):
                window[win_pos] = src[pos + j]
                win_pos = (win_pos + 1) & 0xFFF
            pos += best_len
        else:
            b = src[pos]
            out_tokens.append((True, b, 0))
            window[win_pos] = b
            win_pos = (win_pos + 1) & 0xFFF
            pos += 1

    # 打包 flag 字节 + 数据流
    stream = bytearray()
    token_idx = 0
    while token_idx < len(out_tokens):
        flag_byte = 0
        flag_positions = []
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
                enc_len = length - 3  # 实际长度 = enc_len + 3 → enc_len = length - 3
                b1 = offset & 0xFF
                b2 = ((offset >> 4) & 0xF0) | (enc_len & 0x0F)
                stream.append(b1)
                stream.append(b2)

        token_idx = batch_end

    # 构建文件格式
    decomp_size = src_len
    block_data = struct.pack('<I', decomp_size) + bytes(stream)
    block_size = len(block_data)

    result = struct.pack('<II', decomp_size, block_size) + block_data
    return result


# ============================================================
# TKItem 名称加载 (逆向自 sub_424A2C, sub_4067E8)
# ============================================================

def load_tkitem_names(item_dat_path):
    """
    从 TKItem.dat 加载物品名称列表

    TKItem 记录: 64 字节 (32×int16), 600条
    基址: word_77CBCA
    field[0] = item_id
    field[2] = name_id → TKT (word_77CBCE[32*idx], sub_4067E8)
    """
    with open(item_dat_path, 'rb') as f:
        raw = f.read()

    decompressed = lzss_decompress(raw)

    REC_SIZE = 64
    names = []
    for i in range(600):
        offset = i * REC_SIZE
        if offset + REC_SIZE > len(decompressed):
            break
        item_id = struct.unpack_from('<h', decompressed, offset)[0]
        name_id = struct.unpack_from('<h', decompressed, offset + 4)[0]
        # Try to load TKT if available, otherwise use IDs
        name = f"Item#{item_id}" if item_id else f"(空-{i})"
        names.append((i, item_id, name_id, name))

    return names


def load_tkitem_with_tkt(item_dat_path, tkt_dat_path):
    """
    加载 TKItem 并关联 TKT 名称
    TKT 结构 (sub_401E88):
      [total_size:4][count:4][ID表:count×4][偏移表:count×4][文本区]
      XOR 0xFF 加密
    """
    names = load_tkitem_names(item_dat_path)

    # Load TKT
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

        for i in range(count):
            eid = struct.unpack_from('<i', decrypted, i * 4)[0]
            off = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0]
            text_base = id_table_size + offset_table_size
            abs_off = text_base + off
            if abs_off < len(decrypted):
                end = abs_off
                while end < len(decrypted) and decrypted[end] != 0:
                    end += 1
                text = decrypted[abs_off:end]
                text = text.replace(b'\x1e', b'\n')
                try:
                    tkt_lookup[eid] = text.decode('big5', errors='replace')
                except:
                    tkt_lookup[eid] = text.decode('gbk', errors='replace')

    # Apply TKT names
    result = []
    for idx, item_id, name_id, fallback in names:
        if name_id and name_id in tkt_lookup:
            name = tkt_lookup[name_id]
            # Take first line only
            name = name.split('\n')[0].strip()
            if name and name != '0':
                result.append((idx, item_id, name_id, name))
                continue
        result.append((idx, item_id, name_id, fallback))

    return result


# ============================================================
# TKShop 数据模型 (逆向自 sub_4244CC, sub_4246D8)
# ============================================================

# area_id 标签 (来自 Maker.exe TksModify.dll Cbo_TKShop_Adr 下拉框)
AREA_NAMES = {0: "药店", 1: "道具", 2: "武器防具", 3: "杂货", 4: "饰品", 9: "无"}

def area_label(area_id):
    """返回 area_id 的人类可读名称"""
    return AREA_NAMES.get(area_id, f"未知({area_id})")

REC_SIZE = 8


def load_shop_data(filepath):
    """加载 TKShop.dat"""
    with open(filepath, 'rb') as f:
        raw = f.read()

    decompressed = lzss_decompress(raw)
    count = len(decompressed) // REC_SIZE
    records = []

    for i in range(count):
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
    """保存 TKShop.dat (LZSS 压缩)"""
    count = len(records)
    buf = bytearray(count * REC_SIZE)
    for rec in records:
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


# ============================================================
# GUI 编辑器
# ============================================================

class ShopEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKShop.dat 可视化编辑器")
        self.root.geometry("1050x620")
        self.root.minsize(900, 500)

        self.shop_path = None
        self.item_path = None
        self.tkt_path = None
        self.records = []
        self.items = []
        self.item_names = {}
        self.filtered_indices = []
        self._dirty = False        # 内存修改标记

        self._build_ui()
        self._update_path_labels()
        self._set_edit_enabled(False)

    # ================================================================
    # UI: 菜单栏 + 工具栏 + 左右分栏 + 底部状态
    # ================================================================

    def _build_ui(self):
        # ---- 菜单栏 ----
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="保存 (Ctrl+S)", command=self._save, accelerator="Ctrl+S")
        file_menu.add_command(label="导出 CSV…", command=self._export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())

        # ---- 工具栏 ----
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        ttk.Label(toolbar, text="区域:").pack(side=tk.LEFT)
        self.filter_area_var = tk.StringVar(value="全部")
        area_combo = ttk.Combobox(toolbar, textvariable=self.filter_area_var, width=12, state="readonly",
                                  values=["全部"] + [f"{k}-{v}" for k, v in AREA_NAMES.items()])
        area_combo.pack(side=tk.LEFT, padx=2)
        area_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_filter())

        ttk.Label(toolbar, text="搜索:").pack(side=tk.LEFT, padx=(10, 2))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=18)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(toolbar, text="搜索", command=self._apply_filter, width=4).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="清除", command=self._clear_filter, width=4).pack(side=tk.LEFT, padx=1)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="+ 新增记录", command=self._add_record).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(toolbar, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # ---- 左右分栏 ----
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧: 表格 (weight=3)
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=3)

        columns = ('index', 'area_id', 'area_name', 'item_ref', 'item_name', 'condition', 'display')
        self.tree = ttk.Treeview(left_frame, columns=columns, show='headings', selectmode='browse')
        col_config = [
            ('index', '索引', 42), ('area_id', '区域ID', 45), ('area_name', '区域名称', 70),
            ('item_ref', '物品索引', 58), ('item_name', '物品名称', 180),
            ('condition', '出现条件', 72), ('display', '显示', 36),
        ]
        for col_id, col_name, width in col_config:
            self.tree.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_by(c))
            self.tree.column(col_id, width=width, anchor='center', minwidth=width)

        vsb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure('active', background='#e6ffe6')
        self.tree.tag_configure('random', foreground='#cc6600')
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧: 编辑面板 (weight=1)
        right_frame = ttk.LabelFrame(paned, text="编辑记录", padding=10)
        paned.add(right_frame, weight=1)

        self.edit_frame = right_frame  # for enable/disable

        # 记录索引显示
        self.lbl_rec_idx = ttk.Label(right_frame, text="未选中", font=('', 10, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 10))

        # area_id
        ttk.Label(right_frame, text="区域ID (area_id):").pack(anchor=tk.W)
        self.edit_area = ttk.Combobox(right_frame, state='readonly', width=14,
                                       values=[f"{k}" for k in AREA_NAMES.keys()])
        self.edit_area.pack(fill=tk.X, pady=(0, 2))
        area_hint = " | ".join([f"{k}={v}" for k, v in sorted(AREA_NAMES.items())])
        ttk.Label(right_frame, text=area_hint, foreground='gray', wraplength=280).pack(anchor=tk.W, pady=(0, 8))

        # item_ref
        ttk.Label(right_frame, text="物品索引 (item_ref):").pack(anchor=tk.W)
        item_search_frame = ttk.Frame(right_frame)
        item_search_frame.pack(fill=tk.X, pady=(0, 2))
        self.edit_item = ttk.Entry(item_search_frame, width=8)
        self.edit_item.pack(side=tk.LEFT)
        self.edit_item_search = ttk.Entry(item_search_frame, width=18)
        self.edit_item_search.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(item_search_frame, text="🔍", foreground='gray').pack(side=tk.LEFT)
        self.edit_item_search.bind('<KeyRelease>', self._on_item_search)
        self.lbl_item_name = ttk.Label(right_frame, text="物品: (未选择)", foreground='blue', wraplength=280)
        self.lbl_item_name.pack(anchor=tk.W, pady=(0, 8))

        # condition — 三模式: 随机抽选 / 始终显示 / 自定义偏移 + 实时概率表
        ttk.Label(right_frame, text="出现条件 (condition, sub_4244CC):").pack(anchor=tk.W)
        self.cond_mode = tk.StringVar(value="custom")
        cond_mode_frame = ttk.Frame(right_frame)
        cond_mode_frame.pack(fill=tk.X, pady=(0, 2))
        ttk.Radiobutton(cond_mode_frame, text="随机", variable=self.cond_mode,
                        value="random", command=self._on_cond_mode).pack(side=tk.LEFT)
        ttk.Radiobutton(cond_mode_frame, text="始终", variable=self.cond_mode,
                        value="always", command=self._on_cond_mode).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(cond_mode_frame, text="偏移:", variable=self.cond_mode,
                        value="custom", command=self._on_cond_mode).pack(side=tk.LEFT, padx=(6, 0))
        self.edit_cond = ttk.Spinbox(cond_mode_frame, from_=-999, to=999, width=6,
                                      command=self._on_cond_changed)
        self.edit_cond.pack(side=tk.LEFT, padx=2)
        self.edit_cond.bind('<KeyRelease>', self._on_cond_changed)
        # 实时概率表
        self.cond_table_frame = ttk.Frame(right_frame)
        self.cond_table_frame.pack(fill=tk.X, pady=(4, 8))
        self.cond_table_text = tk.Text(self.cond_table_frame, height=6, width=32,
                                        font=('Consolas', 8), state='disabled',
                                        bg='#f8f8f8', relief='flat', borderwidth=0)
        self.cond_table_text.pack(fill=tk.X)

        # display
        ttk.Label(right_frame, text="显示标志 (display):").pack(anchor=tk.W)
        self.edit_display = tk.BooleanVar(value=False)
        ttk.Checkbutton(right_frame, text="可购买/已显示 (sub_4244CC: byte_9508A6)",
                        variable=self.edit_display).pack(anchor=tk.W, pady=(0, 12))

        # 操作按钮
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="应用修改", command=self._apply_edit).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(btn_frame, text="删除", command=self._delete_record).pack(side=tk.RIGHT, padx=(2, 0))

        # ---- 底部: 文件路径 + 区域代号 ----
        path_frame = ttk.LabelFrame(self.root, text="当前加载的数据文件")
        path_frame.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_shop_path = ttk.Label(path_frame, text="", foreground="gray")
        self.lbl_shop_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(path_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_item_path = ttk.Label(path_frame, text="", foreground="gray")
        self.lbl_item_path.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(path_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt_path = ttk.Label(path_frame, text="", foreground="gray")
        self.lbl_tkt_path.pack(side=tk.LEFT, padx=10, pady=2)

        # 快捷键
        self.root.bind('<Control-s>', lambda e: self._save())

    # ================================================================
    # 数据加载 (通过菜单 "加载 TKS 目录")
    # ================================================================

    def _load_tks_dir(self):
        """选择 TKS 目录, 自动加载目录下的 TKShop.dat / TKItem.dat / TKT.dat"""
        tks_dir = filedialog.askdirectory(title="选择 TKS 游戏目录 (包含 TKShop.dat / TKItem.dat / TKT.dat)")
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
            messagebox.showwarning("文件缺失", f"目录中未找到: {', '.join(missing)}\n\n请确认选择了正确的 TKS 目录。")
            return

        self.shop_path = shop
        self.item_path = item
        self.tkt_path = tkt if os.path.exists(tkt) else None
        self._reload()

    def _reload(self):
        """重新从文件加载数据"""
        if not self.shop_path:
            return

        self.status_var.set("加载中…")
        self.root.update()

        # 加载 TKItem + TKT
        if self.item_path and os.path.exists(self.item_path):
            self.items = load_tkitem_with_tkt(self.item_path, self.tkt_path or "")
            self.item_names = {idx: name for idx, item_id, name_id, name in self.items}

        # 加载 TKShop
        try:
            self.records = load_shop_data(self.shop_path)
            self._dirty = False
            self.status_var.set(f"已加载 {len(self.records)} 条商店记录 + {len(self.items)} 个物品")
        except Exception as e:
            messagebox.showerror("加载失败", f"无法加载 TKShop.dat:\n{e}")
            self.records = []

        self._update_path_labels()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _set_edit_enabled(self, enabled):
        """启用/禁用编辑面板"""
        state = 'readonly' if enabled else 'disabled'
        for child in self.edit_frame.winfo_children():
            self._set_widget_state(child, tk.NORMAL if enabled else tk.DISABLED)

    def _set_widget_state(self, widget, state):
        try:
            if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)):
                widget.configure(state=state)
            elif isinstance(widget, ttk.Checkbutton):
                if state == tk.DISABLED:
                    widget.state(['disabled'])
                else:
                    widget.state(['!disabled'])
        except:
            pass
        for child in widget.winfo_children():
            self._set_widget_state(child, state)

    def _update_path_labels(self):
        green, red = "#228B22", "#CC3333"
        def _fmt(label, path):
            if not path:
                label.config(text="(未加载)", foreground=red)
            elif not os.path.exists(path):
                label.config(text=f"(不存在) {path}", foreground=red)
            else:
                label.config(text=path, foreground=green)
        _fmt(self.lbl_shop_path, self.shop_path)
        _fmt(self.lbl_item_path, self.item_path)
        _fmt(self.lbl_tkt_path, self.tkt_path)

    # ================================================================
    # 过滤 & 表格
    # ================================================================

    def _apply_filter(self):
        area_filter = self.filter_area_var.get()
        search_text = self.search_var.get().strip().lower()

        self.filtered_indices = []
        for rec in self.records:
            if area_filter != "全部":
                fid = int(area_filter.split('-')[0])
                if rec['area_id'] != fid:
                    continue
            if search_text:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                if search_text not in f"{rec['index']} {rec['area_id']} {area_label(rec['area_id'])} {rec['item_ref']} {iname} {self._cond_str(rec['condition'])}".lower():
                    continue
            self.filtered_indices.append(rec['index'])

        self._refresh_table()
        self.status_var.set(f"显示 {len(self.filtered_indices)} / {len(self.records)} 条  |  文件 → 保存 (Ctrl+S) 写入磁盘")

    def _clear_filter(self):
        self.search_var.set("")
        self.filter_area_var.set("全部")
        self._apply_filter()

    def _cond_str(self, cond):
        """condition 显示文本 (逆向自 sub_4244CC 第95-109行)
        逻辑: v9=max(0, level-cond), 随机0-99 < v9 才显示
        cond=1 走独立随机抽选分支"""
        if cond == 1:
            return "随机抽选"
        # cond!=1: 显示概率 = clamp(level - cond, 0, 100)%
        return f"偏移{cond:+d}"

    def _refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx in self.filtered_indices:
            rec = self.records[idx]
            iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
            tags = []
            if rec['display'] == 1: tags.append('active')
            if rec['condition'] == 1: tags.append('random')
            self.tree.insert('', 'end',
                             values=(rec['index'], rec['area_id'], area_label(rec['area_id']),
                                     rec['item_ref'], iname, self._cond_str(rec['condition']), rec['display']),
                             tags=tags)

    def _sort_by(self, col):
        reverse = getattr(self, '_sort_reverse', False)
        km = {'index': 'index', 'area_id': 'area_id', 'item_ref': 'item_ref',
              'condition': 'condition', 'display': 'display'}
        self.filtered_indices.sort(key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=reverse)
        self._sort_reverse = not reverse
        self._refresh_table()

    # ================================================================
    # 右侧编辑面板
    # ================================================================

    def _on_tree_select(self, event):
        """表格选中行 → 右侧编辑面板同步"""
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        idx = int(item['values'][0])
        rec = self.records[idx]
        self._populate_edit(rec)

    def _populate_edit(self, rec):
        """将记录数据填入右侧编辑面板"""
        self._editing_idx = rec['index']
        self.lbl_rec_idx.config(text=f"记录 #{rec['index']}")
        self.edit_area.set(str(rec['area_id']))
        self.edit_item.delete(0, tk.END)
        self.edit_item.insert(0, str(rec['item_ref']))
        self.edit_item_search.delete(0, tk.END)
        iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
        self.lbl_item_name.config(text=f"物品: {iname}")
        # condition: 根据值推断模式
        cond = rec['condition']
        if cond == 1:
            self.cond_mode.set("random")
        elif cond <= -100:
            self.cond_mode.set("always")
        else:
            self.cond_mode.set("custom")
        self.edit_cond.set(str(cond))
        self._on_cond_mode()  # 刷新概率表
        self.edit_display.set(rec['display'] == 1)

    def _on_cond_mode(self):
        """条件模式切换: 随机→cond=1, 始终→cond=-100, 偏移→可输入"""
        mode = self.cond_mode.get()
        if mode == "random":
            self.edit_cond.delete(0, tk.END)
            self.edit_cond.insert(0, "1")
            self.edit_cond.configure(state='disabled')
        elif mode == "always":
            self.edit_cond.delete(0, tk.END)
            self.edit_cond.insert(0, "-100")
            self.edit_cond.configure(state='disabled')
        else:
            self.edit_cond.configure(state='normal')
        self._refresh_cond_table()

    def _on_cond_changed(self, event=None):
        """偏移值变化 → 实时刷新概率表"""
        self._refresh_cond_table()

    def _refresh_cond_table(self):
        """刷新条件概率表 (逆向自 sub_4244CC: 概率=clamp(等级-cond,0,100)%)"""
        self.cond_table_text.configure(state='normal')
        self.cond_table_text.delete('1.0', tk.END)

        try:
            offset = int(self.edit_cond.get())
        except ValueError:
            offset = 0

        if offset == 1:
            self.cond_table_text.insert('1.0',
                "  (随机抽选模式)\n  sub_4244CC: sub_452AC0(50000)\n  最多同时出现5件商品")
            self.cond_table_text.configure(state='disabled')
            return

        lines = []
        first_show = max(1, offset + 1)   # 首次有概率>0的等级
        full_show = offset + 100           # 达到100%的等级

        # 显示关键节点
        prev_prob = -1
        for lv in range(1, full_show + 2):
            prob = max(0, min(100, lv - offset))
            if prob != prev_prob and (prob % 25 == 0 or prob >= 100 or lv <= first_show + 5):
                lines.append(f"  Lv{lv:>3d} → {prob:>3d}%")
                prev_prob = prob
            if prob >= 100:
                break

        # 最多显示14行
        if len(lines) > 14:
            keep = set()
            for i, ln in enumerate(lines):
                if i == 0 or i == len(lines)-1 or i % max(1, len(lines)//12) == 0:
                    keep.add(i)
            lines = [ln for i, ln in enumerate(lines) if i in keep]

        header = f"  偏移={offset:+d}  |  概率=clamp(Lv{offset:+d},0,100)%"
        self.cond_table_text.insert('1.0', header + '\n' + '\n'.join(lines))
        self.cond_table_text.configure(state='disabled')

    def _on_item_search(self, event):
        """物品搜索框输入 → 实时匹配"""
        q = self.edit_item_search.get().strip().lower()
        if len(q) < 2:
            return
        matches = [(i, n) for i, n in self.item_names.items() if q in n.lower()]
        if matches:
            idx, name = matches[0]
            self.edit_item.delete(0, tk.END)
            self.edit_item.insert(0, str(idx))
            self.lbl_item_name.config(text=f"物品: {name}", foreground='blue')

    def _apply_edit(self):
        """应用右侧面板的修改到内存记录"""
        if not hasattr(self, '_editing_idx'):
            return
        try:
            rec = self.records[self._editing_idx]
            rec['area_id'] = int(self.edit_area.get())
            rec['item_ref'] = int(self.edit_item.get())
            rec['condition'] = int(self.edit_cond.get())
            rec['display'] = 1 if self.edit_display.get() else 0
            self._dirty = True
            self._refresh_cond_table()
            self._apply_filter()
            # 重新选中
            for child in self.tree.get_children():
                if int(self.tree.item(child)['values'][0]) == rec['index']:
                    self.tree.selection_set(child)
                    self.tree.see(child)
                    break
            self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存到磁盘)")
        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的整数值")

    def _delete_record(self):
        """删除当前选中的记录 (设为空值)"""
        if not hasattr(self, '_editing_idx'):
            return
        if not messagebox.askyesno("确认删除", f"确定要清空记录 #{self._editing_idx} 吗?\n\n记录将被重置为零值, 而非物理删除。"):
            return
        self.records[self._editing_idx] = {
            'index': self._editing_idx, 'area_id': 0, 'item_ref': 0,
            'condition': 0, 'display': 0, 'reserved': 0
        }
        self._dirty = True
        self._apply_filter()

    def _add_record(self):
        """在末尾新增一条空记录 (追加到 240 条之后)"""
        if len(self.records) >= 400:
            messagebox.showwarning("已达上限", "记录数已达 400 条上限")
            return
        new_idx = len(self.records)
        self.records.append({
            'index': new_idx, 'area_id': 0, 'item_ref': 0,
            'condition': 0, 'display': 0, 'reserved': 0
        })
        self._dirty = True
        self._apply_filter()
        # 选中新记录
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == new_idx:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self.status_var.set(f"已新增记录 #{new_idx} (共 {len(self.records)} 条)")

    # ================================================================
    # 保存 & 导出
    # ================================================================

    def _save(self):
        if not self.shop_path or not self.records:
            messagebox.showinfo("提示", "请先通过 文件 → 加载 TKS 目录 打开数据")
            return

        if not messagebox.askyesno("确认保存",
                                    f"将保存 {len(self.records)} 条记录到:\n{self.shop_path}\n\n原文件将被覆盖。继续?"):
            return

        # 备份
        try:
            with open(self.shop_path, 'rb') as src:
                with open(self.shop_path + ".bak", 'wb') as dst:
                    dst.write(src.read())
        except:
            pass

        try:
            save_shop_data(self.shop_path, self.records)
            self._dirty = False
            self.status_var.set(f"已保存 {len(self.records)} 条记录 → {self.shop_path}")
            messagebox.showinfo("保存成功", f"已保存 {len(self.records)} 条记录\n备份: {self.shop_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records:
            return
        path = filedialog.asksaveasfilename(title="导出 CSV", defaultextension=".csv",
                                             filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write("索引,区域ID,区域名称,物品索引,物品名称,出现条件(原始),出现条件(文本),显示标志\n")
            for rec in self.records:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                f.write(f"{rec['index']},{rec['area_id']},{area_label(rec['area_id'])},"
                        f"{rec['item_ref']},{iname},{rec['condition']},{self._cond_str(rec['condition'])},{rec['display']}\n")
        self.status_var.set(f"已导出 CSV: {path}")
        messagebox.showinfo("导出成功", f"已导出 {len(self.records)} 条")


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    ShopEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
