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

def load_tkitem_with_tkt(item_dat_path, tkt_dat_path):
    """
    加载 TKItem 并关联 TKT 名称, 同时提取 equip_type 用于分类筛选

    field[0]=item_id, field[1]=tab_code, field[5]=equip_type (word_77CBD4, sub_41928C)
    """
    # 先解压原始记录
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

    # 加载 TKT
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
        # TKT ID 0-9 是系统消息 (sub_4067E8):
        #   0=啊！1=虎牢關之役 2=你的智慧上升了！！3=你的仁德上升了！！
        #   4=你的勇氣上升了！！5=你的醫術上升了！！6=THE END 7=... 8=無法使用 9=得到銀兩
        # 这些不是物品名称, 必须跳过。
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
        # name_id<=0 是无效引用, TKT 中某些条目值为字面量 "0"
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

# area_id 标签 (来自 Maker.exe TksModify.dll Cbo_TKShop_Adr 下拉框)
AREA_NAMES = {0: "药店", 1: "道具", 2: "武器防具", 3: "杂货", 4: "饰品", 9: "无"}

def area_label(area_id):
    """返回 area_id 的人类可读名称"""
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

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

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

        columns = ('index', 'area_id', 'area_name', 'item_ref', 'item_name', 'condition')
        self.tree = ttk.Treeview(left_frame, columns=columns, show='headings', selectmode='browse')
        col_config = [
            ('index', '索引', 42), ('area_id', '区域ID', 45), ('area_name', '区域名称', 70),
            ('item_ref', '物品索引', 58), ('item_name', '物品名称', 195),
            ('condition', '出现条件', 72),
        ]
        for col_id, col_name, width in col_config:
            self.tree.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_by(c))
            self.tree.column(col_id, width=width, anchor='center', minwidth=width)

        vsb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure('random', foreground='#cc6600')
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧: 编辑面板 (weight=1)
        right_frame = ttk.LabelFrame(paned, text="编辑记录", padding=10)
        paned.add(right_frame, weight=1)

        self.edit_frame = right_frame  # for enable/disable

        # 记录索引显示
        self.lbl_rec_idx = ttk.Label(right_frame, text="未选中", font=('', 10, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 10))

        # area_id — 直接显示名称
        ttk.Label(right_frame, text="区域:").pack(anchor=tk.W)
        self._area_name_by_id = {v: k for k, v in AREA_NAMES.items()}   # "药店"→0
        area_names = [v for k, v in sorted(AREA_NAMES.items())]
        self.edit_area_combo = ttk.Combobox(right_frame, state='readonly', width=14, values=area_names)
        self.edit_area_combo.pack(fill=tk.X, pady=(0, 2))
        self.edit_area_combo.bind('<<ComboboxSelected>>', self._on_area_changed)
        # 兼容性警告标签
        self.lbl_compat = ttk.Label(right_frame, text="", foreground='#888888', wraplength=280)
        self.lbl_compat.pack(anchor=tk.W, pady=(0, 6))

        # item_ref — 按钮 + 弹窗选择
        ttk.Label(right_frame, text="物品:").pack(anchor=tk.W)
        item_frame = ttk.Frame(right_frame)
        item_frame.pack(fill=tk.X, pady=(0, 2))
        self._editing_item_idx = tk.StringVar(value="")
        ttk.Label(item_frame, textvariable=self._editing_item_idx, width=6,
                  font=('', 9, 'bold')).pack(side=tk.LEFT)
        self.lbl_item_name = ttk.Label(item_frame, text="(未选择)", foreground='blue', anchor=tk.W)
        self.lbl_item_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Button(item_frame, text="选择物品…", command=self._pick_item).pack(side=tk.RIGHT)
        ttk.Label(right_frame, text="", foreground='gray').pack(anchor=tk.W, pady=(0, 8))  # spacer

        # condition — 三模式: 随机抽选 / 始终显示 / 自定义偏移 + 实时概率表
        ttk.Label(right_frame, text="出现条件:").pack(anchor=tk.W)
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
            items_raw = load_tkitem_with_tkt(self.item_path, self.tkt_path or "")
            self.items = items_raw  # [(idx, item_id, tab_code, name_id, equip_type, name), ...]
            self.item_names = {it[0]: it[5] for it in items_raw}  # idx → name
            self.item_equip_types = {it[0]: it[4] for it in items_raw}  # idx → equip_type

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
        for child in self.edit_frame.winfo_children():
            self._set_widget_state(child, enabled)

    def _set_widget_state(self, widget, enabled):
        try:
            if isinstance(widget, (ttk.Entry, ttk.Spinbox)):
                widget.configure(state='normal' if enabled else 'disabled')
            elif isinstance(widget, ttk.Combobox):
                widget.configure(state='readonly' if enabled else 'disabled')
            elif isinstance(widget, ttk.Checkbutton):
                if enabled:
                    widget.state(['!disabled'])
                else:
                    widget.state(['disabled'])
            elif isinstance(widget, ttk.Radiobutton):
                if enabled:
                    widget.state(['!disabled'])
                else:
                    widget.state(['disabled'])
        except:
            pass
        for child in widget.winfo_children():
            self._set_widget_state(child, enabled)

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
            tags = ['random'] if rec['condition'] == 1 else []
            self.tree.insert('', 'end',
                             values=(rec['index'], rec['area_id'], area_label(rec['area_id']),
                                     rec['item_ref'], iname, self._cond_str(rec['condition'])),
                             tags=tags)

    def _sort_by(self, col):
        reverse = getattr(self, '_sort_reverse', False)
        km = {'index': 'index', 'area_id': 'area_id', 'item_ref': 'item_ref',
              'condition': 'condition'}
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
        # area
        self.edit_area_combo.set(AREA_NAMES.get(rec['area_id'], str(rec['area_id'])))
        # item
        self._editing_item_idx.set(str(rec['item_ref']))
        iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
        self.lbl_item_name.config(text=iname, foreground='blue')
        self._update_compat_label(rec['area_id'], rec['item_ref'])
        # condition
        cond = rec['condition']
        if cond == 1:
            self.cond_mode.set("random")
        elif cond <= -100:
            self.cond_mode.set("always")
        else:
            self.cond_mode.set("custom")
        self.edit_cond.set(str(cond))
        self._on_cond_mode()

    def _get_item_tab(self, item_ref):
        """获取物品的 tab_code (field[1])"""
        for it in self.items:
            if it[0] == item_ref:
                return it[2]
        return -1

    def _update_compat_label(self, area_id, item_ref):
        """更新区域兼容性标签 (sub_4246D8: tab_code 过滤)"""
        item_tab = self._get_item_tab(item_ref)
        allowed = self.TAB_TO_SHOP.get(item_tab, [])
        if area_id in allowed:
            self.lbl_compat.config(text="✓ 该物品可在此商店出现", foreground='#228B22')
        elif not allowed:
            self.lbl_compat.config(text="⚠ 该物品不会在任何商店出现", foreground='#CC3333')
        else:
            shop_names = [AREA_NAMES.get(a, str(a)) for a in allowed]
            self.lbl_compat.config(
                text=f"⚠ 不兼容! 该物品仅适用于: {', '.join(shop_names)}",
                foreground='#CC3333')

    def _on_area_changed(self, event=None):
        """区域下拉框变化 → 刷新兼容性提示"""
        if not hasattr(self, '_editing_idx'):
            return
        try:
            item_ref = int(self._editing_item_idx.get())
        except ValueError:
            return
        area_name = self.edit_area_combo.get()
        area_id = self._area_name_by_id.get(area_name, 0)
        self._update_compat_label(area_id, item_ref)

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
                "  (随机抽选模式)\n  每次进入商店时随机判定\n  最多同时出现5件商品")
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

    # 物品分类映射 (基于 field[1] tab_code, sub_4246D8 用此字段过滤商店)
    # word_77CBCC[32*item_ref] = item.tab_code → 与 a1[31+slot] 比较
    ITEM_CATEGORIES = {
        "全部": None,
        "消耗品": [0],
        "书籍": [1],
        "武器": [2],
        "防具": [3],
        "饰品": [4],
        "特殊": [5],
    }
    ITEM_CAT_ORDER = ["全部", "消耗品", "书籍", "武器", "防具", "饰品", "特殊"]

    # tab_code → 商店区域约束 (sub_4233C4 switch + sub_4246D8 过滤)
    TAB_TO_SHOP = {
        0: [0, 3],       # 消耗品 → 药店, 杂货
        1: [1, 3],       # 书籍 → 道具店, 杂货
        2: [2],          # 武器 → 武器防具
        3: [2],          # 防具 → 武器防具
        4: [4],          # 饰品 → 饰品店
        5: [],           # 特殊 → 不显示在商店
    }

    def _pick_item(self):
        """弹出物品选择对话框, 带搜索和分类筛选"""
        dialog = tk.Toplevel(self.root)
        dialog.title("选择物品")
        dialog.geometry("520x480")
        dialog.minsize(420, 360)
        dialog.transient(self.root)
        dialog.grab_set()

        result = tk.IntVar(value=-1)

        # 搜索 + 分类
        top_frame = ttk.Frame(dialog, padding=(8, 8, 8, 0))
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="搜索:").grid(row=0, column=0, sticky='w')
        search_var = tk.StringVar()
        search_entry = ttk.Entry(top_frame, textvariable=search_var, width=24)
        search_entry.grid(row=0, column=1, padx=5, sticky='we')
        ttk.Label(top_frame, text="分类:").grid(row=0, column=2, padx=(10, 0), sticky='w')
        cat_var = tk.StringVar(value="全部")
        cat_combo = ttk.Combobox(top_frame, textvariable=cat_var, state='readonly',
                                  values=self.ITEM_CAT_ORDER, width=12)
        cat_combo.grid(row=0, column=3, padx=5, sticky='w')
        top_frame.grid_columnconfigure(1, weight=1)
        search_entry.focus_set()

        # 列表
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)

        columns = ('idx', 'cat', 'name')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', selectmode='browse', height=18)
        tree.heading('idx', text='索引', command=lambda: self._sort_item_tree(tree, 'idx', False))
        tree.heading('cat', text='分类', command=lambda: self._sort_item_tree(tree, 'cat', False))
        tree.heading('name', text='物品名称', command=lambda: self._sort_item_tree(tree, 'name', False))
        tree.column('idx', width=42, anchor='center')
        tree.column('cat', width=72, anchor='center')
        tree.column('name', width=360, anchor='w')

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        tree.bind('<Double-1>', lambda e: [result.set(int(tree.item(tree.selection()[0])['values'][0])),
                                            dialog.destroy()] if tree.selection() else None)

        def _cat_name(tab_code):
            """tab_code → 分类名 (sub_4246D8: word_77CBCC[32*idx] = item.tab_code)"""
            return {0: "消耗品", 1: "书籍", 2: "武器", 3: "防具", 4: "饰品", 5: "特殊"}.get(tab_code, f"其他({tab_code})")

        def refresh_list(*args):
            tree.delete(*tree.get_children())
            q = search_var.get().strip().lower()
            cat = cat_var.get()
            allowed = self.ITEM_CATEGORIES.get(cat)
            for idx, item_id, tab_code, name_id, equip_type, name in self.items:
                # 跳过无效名称: TKT未填充的占位槽 (Item#1=item_id=1的225个占位, (空-N=全零槽)
                if not name or name.startswith("(空") or name.startswith("Item#") or name == "0":
                    continue
                if q and q not in name.lower():
                    continue
                if allowed is not None and tab_code not in allowed:
                    continue
                tree.insert('', 'end', values=(idx, _cat_name(tab_code), name))
            if tree.get_children():
                tree.selection_set(tree.get_children()[0])

        refresh_list()
        search_var.trace_add('write', refresh_list)
        cat_combo.bind('<<ComboboxSelected>>', refresh_list)

        # 按钮区
        btn_frame = ttk.Frame(dialog, padding=(8, 0, 8, 8))
        btn_frame.pack(fill=tk.X)
        ttk.Label(btn_frame, text=f"共 {len(self.items)} 件物品  |  双击行快速选择",
                  foreground='gray').pack(side=tk.LEFT, pady=6)
        ttk.Button(btn_frame, text="确定", width=8, command=lambda: [
            result.set(int(tree.item(tree.selection()[0])['values'][0])),
            dialog.destroy()
        ] if tree.selection() else None).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="取消", width=8, command=dialog.destroy).pack(side=tk.RIGHT, padx=2)

        dialog.wait_window()

        picked = result.get()
        if picked >= 0:
            self._editing_item_idx.set(str(picked))
            self.lbl_item_name.config(text=self.item_names.get(picked, f"Item#{picked}"), foreground='blue')

    @staticmethod
    def _sort_item_tree(tree, col, reverse):
        items = [(tree.set(child, col), child) for child in tree.get_children('')]
        try:
            items.sort(key=lambda x: int(x[0]), reverse=reverse)
        except ValueError:
            items.sort(key=lambda x: x[0], reverse=reverse)
        for i, (_, child) in enumerate(items):
            tree.move(child, '', i)
        tree.heading(col, command=lambda: ShopEditor._sort_item_tree(tree, col, not reverse))

    def _apply_edit(self):
        """应用右侧面板的修改到内存记录"""
        if not hasattr(self, '_editing_idx'):
            return
        try:
            rec = self.records[self._editing_idx]
            # area: 名称 → ID
            area_name = self.edit_area_combo.get()
            rec['area_id'] = self._area_name_by_id.get(area_name, 0)
            rec['item_ref'] = int(self._editing_item_idx.get())
            rec['condition'] = int(self.edit_cond.get())
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
            'condition': 0, 'display': 0, 'reserved': 0  # display 保持为0(运行时由 sub_4244CC 设置)
        }
        self._dirty = True
        self._apply_filter()

    def _add_record(self):
        """在 240 条中找空槽 (全为零) 复用; 没有空槽则提示已满

        sub_45343C 硬编码 1920 字节 (240 条): 不能超出此限制。
        """
        FIXED_COUNT = 240
        # 确保有 240 条
        while len(self.records) < FIXED_COUNT:
            self.records.append({
                'index': len(self.records), 'area_id': 0, 'item_ref': 0,
                'condition': 0, 'display': 0, 'reserved': 0
            })

        # 找空槽
        for rec in self.records[:FIXED_COUNT]:
            if rec['area_id'] == 0 and rec['item_ref'] == 0 and rec['condition'] == 0:
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self.status_var.set(f"选中空槽 #{rec['index']}, 请在右侧编辑后应用修改")
                return

        messagebox.showwarning("已满", "240 条记录全部非空, 无法新增。\n请先删除一条旧记录腾出空槽。")

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
            f.write("索引,区域ID,区域名称,物品索引,物品名称,出现条件(原始),出现条件(文本)\n")
            for rec in self.records:
                iname = self.item_names.get(rec['item_ref'], f"Item#{rec['item_ref']}")
                f.write(f"{rec['index']},{rec['area_id']},{area_label(rec['area_id'])},"
                        f"{rec['item_ref']},{iname},{rec['condition']},{self._cond_str(rec['condition'])}\n")
        self.status_var.set(f"已导出 CSV: {path}")
        messagebox.showinfo("导出成功", f"已导出 {len(self.records)} 条")

    def _show_help(self):
        messagebox.showinfo("使用说明",
            "TKShop.dat 可视化编辑器\n\n"
            "1. 文件 → 加载 TKS 目录: 选择包含 TKShop.dat / TKItem.dat / TKT.dat 的目录\n"
            "2. 左侧表格: 单击行查看/编辑, 支持区域过滤和关键词搜索\n"
            "3. 右侧面板: 修改区域/物品/出现条件/显示标志, 点「应用修改」保存到内存\n"
            "4. 文件 → 保存 (Ctrl+S): 将内存中的修改写入 TKShop.dat\n"
            "5. + 新增记录: 在240条中查找空槽位复用\n"
            "6. 出现条件:\n"
            "   - 随机: 每次进入商店时随机抽选 (最多5件)\n"
            "   - 始终: 设为-100, 任意等级都100%出现\n"
            "   - 偏移: 出现概率 = (等级 - 偏移值)%, 最高100%\n"
            "7. 物品与区域有兼容性限制 (由游戏代码决定):\n"
            "   选择物品后区域下方会显示是否兼容及建议放置的商店")

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKShop.dat 可视化编辑器 v1.0\n\n"
            "基于《三国群侠传》(TKS) 逆向工程\n"
            "支持 TKShop.dat 的加载、编辑、保存\n"
            "自动关联 TKItem.dat + TKT.dat 显示物品名称")


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    ShopEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
