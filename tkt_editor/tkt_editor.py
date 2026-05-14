#!/usr/bin/env python3
"""
TKT.dat 文本数据库编辑器 v1.0
=============================
加载/编辑/保存/新增 TKT.dat 文本数据库条目。

逆向依据:
  sub_401E88 (0x401e88): TKT.dat 加载/构建主函数
    - LOAD 模式 (lines 373-401): fread header(8B), malloc, fread data, XOR 0xFF 解密
    - BUILD 模式 (lines 85-371): 两遍扫描 TKTalk.txt, 编译标签, XOR 加密, 写 TKT.dat
    - 行 320: `*(_BYTE *)(dword_8242F8 + v31++) = 30;` → 0x1E 行分隔符 (仅第2行起)
    - 行 336: `*(_BYTE *)(dword_8242F8 + v31++) = 0;`  → 0x00 条目终止符
    - 行 343-348 / 397-401: XOR 加密/解密 `*v24 = ~*v24`
  sub_4067E8 (0x4067e8): 通过 ID 线性扫描查询文本
  sub_4019D0 (0x4019d0): `<TAG,n>` 控制标记编码器
    - v6=1 仅 TEXT 分支 (行 120): 写入 2 字节 (lo+hi)
    - 其余标签 v6=0: 写入 1 字节
  tkt_decoder.py: 权威解码器实现 (逆向工作区/)

用法:
  python tkt_editor.py [TKT.dat]
"""

import os
import re
import struct
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from collections import OrderedDict

# ============================================================
# 常量 (全部来自反编译, 不可改)
# ============================================================
XOR_KEY = 0xFF                       # sub_401E88: `*p = ~*p` 即 XOR 0xFF
HDR_SIZE = 8                         # 未加密头部: total_size(4) + record_count(4)
ENTRY_TERMINATOR = 0x00              # sub_401E88 行 336
LINE_SEPARATOR = 0x1E                # sub_401E88 行 320 (十进制 30)

# 控制字节映射 (sub_4019D0): code -> (name, data_bytes, min_val, max_val)
# data_bytes: TEXT=2 (v6=1), 其余=1 (v6=0)
CONTROL_TAGS = {
    0x01: ("FRESET", 1, 1, 4),
    0x02: ("FCOLOR", 1, 1, 32),
    0x04: ("FSIZE",  1, 12, 48),
    0x05: ("FTYPE",  1, 1, 8),
    0x14: ("TEXT",   2, 1, 32767),
    0x15: ("VARNUM", 1, 1, 255),
    0x16: ("VARTXT", 1, 1, 255),
    0x1D: ("NAME",   1, 1, 2),
}

# 反向映射: tag_name -> (code, data_bytes, min_val, max_val)
TAG_NAME_MAP = {v[0]: (code, v[1], v[2], v[3]) for code, v in CONTROL_TAGS.items()}

# 标签编码正则: <TAG_NAME,number>
TAG_PATTERN = re.compile(r'<([A-Z]+),(\d+)>')

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_MONO = ('Consolas', 10)


# ============================================================
# TKT 文件 I/O (依据 sub_401E88)
# ============================================================

def load_tkt(tkt_path):
    """加载 TKT.dat, 返回 entries 列表 (OrderedDict)。
    依据 sub_401E88 LOAD 模式 (lines 373-401) + tkt_decoder.py。
    """
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    if len(raw) < HDR_SIZE:
        raise ValueError(f"TKT.dat 头部不足 8 字节: 实际 {len(raw)}")

    total_size = struct.unpack_from('<I', raw, 0)[0]
    record_count = struct.unpack_from('<I', raw, 4)[0]

    if len(raw) < HDR_SIZE + total_size:
        raise ValueError(f"TKT.dat 体积不足: 声明 {total_size}, 实际 {len(raw) - HDR_SIZE}")

    # XOR 0xFF 解密 (sub_401E88 行 397-401: `*n = ~*n`)
    encrypted = raw[HDR_SIZE:HDR_SIZE + total_size]
    decrypted = bytes(b ^ XOR_KEY for b in encrypted)

    # 切分三表 (sub_401E88 行 385-386: dword_8242F4 = base+4*cnt, dword_8242F8 = base+8*cnt)
    id_table_size = 4 * record_count
    offset_table_size = 4 * record_count
    text_base = id_table_size + offset_table_size

    entries = []
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', decrypted, i * 4)[0]          # int32 (sub_4067E8 *i 比较)
        text_offset = struct.unpack_from('<I', decrypted, id_table_size + i * 4)[0]  # uint32

        # 提取条目字节 (tkt_decoder.py slice_entry_bytes: 扫描 0x00 终止)
        abs_off = text_base + text_offset
        if abs_off >= len(decrypted):
            blob = b''
        else:
            end = abs_off
            while end < len(decrypted) and decrypted[end] != ENTRY_TERMINATOR:
                end += 1
            blob = decrypted[abs_off:end]

        # 按 0x1E 拆行 (sub_401E88 行 320)
        raw_lines = blob.split(bytes([LINE_SEPARATOR]))
        # 解码每行: Big5 解码, 控制字节保留为 <TAG,n> 标记
        decoded_lines = [decode_line(ln) for ln in raw_lines]
        text = '\n'.join(decoded_lines)

        entries.append(OrderedDict([
            ('slot', i),
            ('id', entry_id),
            ('text', text),
        ]))
    return entries


def decode_line(line_bytes):
    """把单行字节流解码为 UTF 文本, 控制字节转为 <TAG,n> 标记。
    依据 tkt_decoder.py decode_inline_tags()。
    """
    out = []
    buf = bytearray()

    def flush():
        if buf:
            try:
                out.append(buf.decode('big5', errors='replace'))
            except Exception:
                out.append(buf.decode('gbk', errors='replace'))
            buf.clear()

    i = 0
    n = len(line_bytes)
    while i < n:
        b = line_bytes[i]
        if b in CONTROL_TAGS:
            tag_name, data_len, _, _ = CONTROL_TAGS[b]
            if i + data_len < n:
                flush()
                if data_len == 1:
                    val = line_bytes[i + 1]
                else:
                    val = line_bytes[i + 1] | (line_bytes[i + 2] << 8)
                out.append(f'<{tag_name},{val}>')
                i += 1 + data_len
                continue
            else:
                flush()
                out.append(f'<RAW,0x{b:02X}>')
                i += 1
                continue
        if b < 0x20 and b != LINE_SEPARATOR:
            flush()
            out.append(f'<RAW,0x{b:02X}>')
            i += 1
            continue
        # Big5 双字节 (sub_4019D0 行 45-51: `*a1 > 0x7F`)
        if b >= 0x80 and i + 1 < n:
            buf.append(b)
            buf.append(line_bytes[i + 1])
            i += 2
        else:
            buf.append(b)
            i += 1
    flush()
    return ''.join(out)


def encode_line(text):
    """把一行 UTF 文本编码为二进制字节流 (Big5 + 控制字节)。
    依据 sub_4019D0 编码逻辑。
    """
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        # 尝试匹配 <TAG,n> 标记
        m = TAG_PATTERN.match(text, i)
        if m:
            tag_name = m.group(1)
            val = int(m.group(2))
            if tag_name in TAG_NAME_MAP:
                code, data_len, min_val, max_val = TAG_NAME_MAP[tag_name]
                if min_val <= val <= max_val:
                    out.append(code)
                    out.append(val & 0xFF)
                    if data_len == 2:
                        out.append((val >> 8) & 0xFF)
                    i = m.end()
                    continue
            # 无效标签, 原样输出
            for ch in text[i:m.end()]:
                out.extend(ch.encode('big5', errors='replace'))
            i = m.end()
            continue
        # 尝试匹配 <RAW,0xNN> 标记
        if text[i] == '<' and i + 6 < n:
            rm = re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                out.append(int(rm.group(1), 16))
                i += rm.end()
                continue
        ch = text[i]
        # Big5 双字节字符直接编码
        try:
            encoded = ch.encode('big5')
        except (UnicodeEncodeError, UnicodeDecodeError):
            encoded = ch.encode('gbk', errors='replace')
        out.extend(encoded)
        i += 1
    return bytes(out)


def save_tkt(tkt_path, entries):
    """保存 entries 到 TKT.dat。
    依据 sub_401E88 BUILD 模式 (lines 220-371):
      1. 构建 ID 表 (int32) + 偏移表 (uint32) + 文本区
      2. 文本区: 多行用 0x1E 连接 (第2行起前插), 条目末尾追加 0x00
      3. 整体 XOR 0xFF 加密
      4. 写入: header(8B) + encrypted_data
    """
    record_count = len(entries)
    # 构建文本区
    text_blob = bytearray()
    id_table = bytearray()
    offset_table = bytearray()

    for entry in entries:
        entry_id = entry['id']
        text = entry['text']
        lines = text.split('\n')
        entry_bytes = bytearray()
        for li, line in enumerate(lines):
            if li > 0:
                entry_bytes.append(LINE_SEPARATOR)  # sub_401E88 行 320: 0x1E
            entry_bytes.extend(encode_line(line))
        entry_bytes.append(ENTRY_TERMINATOR)  # sub_401E88 行 336: 0x00

        # 记录偏移 (当前 text_blob 长度)
        current_offset = len(text_blob)
        text_blob.extend(entry_bytes)

        # ID 表: int32 LE (sub_401E88 行 303: `*(_DWORD *)(dword_8242F0 + 4*v33) = v36`)
        id_table.extend(struct.pack('<i', entry_id))
        # 偏移表: uint32 LE (sub_401E88 行 304: `*(_DWORD *)(dword_8242F4 + 4*v33++) = v31`)
        offset_table.extend(struct.pack('<I', current_offset))

    # 组装数据区: ID表 + 偏移表 + 文本区 (sub_401E88 行 224-227)
    data = bytes(id_table) + bytes(offset_table) + bytes(text_blob)
    total_size = len(data)

    # XOR 0xFF 加密 (sub_401E88 行 343-348: `*v24 = ~*v24`)
    encrypted = bytes(b ^ XOR_KEY for b in data)

    # 写入文件: header(8B) + encrypted_data
    with open(tkt_path, 'wb') as f:
        f.write(struct.pack('<I', total_size))
        f.write(struct.pack('<I', record_count))
        f.write(encrypted)


# ============================================================
# GUI
# ============================================================

class TktEditor:
    def __init__(self, root, initial_path=None):
        self.root = root
        self.root.title("TKT.dat 文本数据库编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)

        self.tkt_path = None
        self.entries = []          # 当前所有条目
        self.filtered_indices = [] # 当前过滤后的索引
        self._dirty = False
        self._current_idx = None   # 当前选中条目在 self.entries 中的索引

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1200) // 2
        y = (sh - 750) // 2
        self.root.geometry(f'1200x750+{x}+{y}')

        if initial_path and os.path.exists(initial_path):
            self._load_file(initial_path)

    def _build_ui(self):
        # 菜单栏
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="打开 TKT.dat…", command=self._open_file, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="另存为…", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_quit)
        mb.add_cascade(label="文件", menu=fm)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新增条目", command=self._new_entry, accelerator="Ctrl+N")
        em.add_command(label="删除当前条目", command=self._delete_entry, accelerator="Delete")
        em.add_separator()
        em.add_command(label="查找…", command=self._focus_search, accelerator="Ctrl+F")
        mb.add_cascade(label="编辑", menu=em)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        self.root.bind('<Control-o>', lambda e: self._open_file())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_entry())
        self.root.bind('<Control-f>', lambda e: self._focus_search())
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.search_var, width=20)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(tb, text="ID范围:").pack(side=tk.LEFT)
        self.filter_from = tk.StringVar()
        self.filter_to = tk.StringVar()
        ttk.Entry(tb, textvariable=self.filter_from, width=6).pack(side=tk.LEFT, padx=1)
        ttk.Label(tb, text="—").pack(side=tk.LEFT)
        ttk.Entry(tb, textvariable=self.filter_to, width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="过滤", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(tb, text="新增条目", command=self._new_entry).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="请通过 文件 → 打开 TKT.dat 加载数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # 主分栏
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧: 条目列表
        lf = ttk.Frame(paned)
        paned.add(lf, weight=2)
        cols = ('slot', 'id', 'preview')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        self.tree.heading('slot', text='#')
        self.tree.heading('id', text='ID')
        self.tree.heading('preview', text='文本预览')
        self.tree.column('slot', width=40, minwidth=30, anchor='center')
        self.tree.column('id', width=60, minwidth=40, anchor='center')
        self.tree.column('preview', width=200, minwidth=100, anchor='w')
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧: 编辑区
        rf = ttk.Frame(paned)
        paned.add(rf, weight=3)

        # 条目信息
        info_frame = ttk.Frame(rf)
        info_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        self.lbl_info = ttk.Label(info_frame, text="未选中", font=('', 11, 'bold'))
        self.lbl_info.pack(side=tk.LEFT)
        self.lbl_dirty = ttk.Label(info_frame, text="", foreground='red', font=FONT)
        self.lbl_dirty.pack(side=tk.RIGHT)

        # ID 输入
        id_frame = ttk.Frame(rf)
        id_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(id_frame, text="条目 ID:", font=FONT).pack(side=tk.LEFT)
        self.id_var = tk.StringVar()
        ttk.Entry(id_frame, textvariable=self.id_var, width=12, font=FONT).pack(side=tk.LEFT, padx=4)
        ttk.Label(id_frame, text="(int32, 可为负数)", font=FONT_S, foreground='#666').pack(side=tk.LEFT)

        # 文本编辑器
        edit_frame = ttk.LabelFrame(rf, text="文本内容 (支持多行, <TAG,n> 标记)", padding=4)
        edit_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        ef = ttk.Frame(edit_frame)
        ef.pack(fill=tk.BOTH, expand=True)
        self.text_widget = tk.Text(ef, font=FONT_MONO, wrap=tk.NONE, undo=True,
                                   tabs=('4c',), bg='#fafafa')
        ssb_y = ttk.Scrollbar(ef, orient=tk.VERTICAL, command=self.text_widget.yview)
        ssb_x = ttk.Scrollbar(ef, orient=tk.HORIZONTAL, command=self.text_widget.xview)
        self.text_widget.configure(yscrollcommand=ssb_y.set, xscrollcommand=ssb_x.set)
        self.text_widget.grid(row=0, column=0, sticky='nsew')
        ssb_y.grid(row=0, column=1, sticky='ns')
        ssb_x.grid(row=1, column=0, sticky='ew')
        ef.rowconfigure(0, weight=1)
        ef.columnconfigure(0, weight=1)
        self.text_widget.bind('<KeyRelease>', self._on_text_modified)

        # 控制码提示
        tip_frame = ttk.Frame(rf)
        tip_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
        tip_text = ("控制码: <FRESET,n> <FCOLOR,n> <FSIZE,n> <FTYPE,n> "
                    "<TEXT,n> <VARNUM,n> <VARTXT,n> <NAME,n>")
        ttk.Label(tip_frame, text=tip_text, font=FONT_S, foreground='#888').pack(anchor=tk.W)

        # 按钮栏
        bf = ttk.Frame(rf)
        bf.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置", command=self._reset_edit, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="删除此条目", command=self._delete_entry, width=12).pack(side=tk.RIGHT)

    def _set_edit_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.text_widget.config(state=state)

    def _on_quit(self):
        if self._dirty:
            result = messagebox.askyesnocancel("未保存的修改", "有未保存的修改，是否保存？")
            if result is None:
                return
            if result:
                self._save()
        self.root.quit()

    # ----------- 文件操作 -----------
    def _open_file(self):
        path = filedialog.askopenfilename(
            title="打开 TKT.dat",
            filetypes=[("TKT 数据库", "*.dat"), ("所有文件", "*.*")],
            initialdir=self._guess_tks_dir()
        )
        if path:
            self._load_file(path)

    def _guess_tks_dir(self):
        here = os.path.dirname(os.path.abspath(__file__))
        tks_dir = os.path.normpath(os.path.join(here, "..", "..", "逆向工作区", "TKS"))
        return tks_dir if os.path.isdir(tks_dir) else here

    def _load_file(self, path):
        try:
            self.entries = load_tkt(path)
            self.tkt_path = path
            self._dirty = False
            self._current_idx = None
            self._populate_tree()
            self._set_edit_enabled(False)
            self.lbl_info.config(text="未选中")
            self.id_var.set('')
            self.text_widget.delete('1.0', 'end')
            self.status_var.set(f"已加载: {os.path.basename(path)} ({len(self.entries)} 条目)")
            self.root.title(f"TKT.dat 编辑器 - {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))

    def _save(self):
        if not self.tkt_path:
            self._save_as()
            return
        self._do_save(self.tkt_path)

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            title="另存为 TKT.dat",
            defaultextension=".dat",
            filetypes=[("TKT 数据库", "*.dat"), ("所有文件", "*.*")],
            initialdir=self._guess_tks_dir()
        )
        if path:
            self._do_save(path)

    def _do_save(self, path):
        if not messagebox.askyesno(
            "确认保存",
            f"确认保存到 {os.path.basename(path)}？\n共 {len(self.entries)} 条目"
        ):
            return
        try:
            save_tkt(path, self.entries)
            self.tkt_path = path
            self._dirty = False
            self.lbl_dirty.config(text="")
            self.status_var.set(f"已保存: {os.path.basename(path)} ({len(self.entries)} 条目)")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _reload(self):
        if not self.tkt_path:
            return
        if self._dirty:
            result = messagebox.askyesno("确认重新加载", "有未保存的修改，确认重新加载将丢失这些修改。")
            if not result:
                return
        self._load_file(self.tkt_path)

    # ----------- 列表操作 -----------
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = list(range(len(self.entries)))
        for idx in self.filtered_indices:
            e = self.entries[idx]
            preview = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
            self.tree.insert('', 'end', iid=str(idx),
                             values=(e['slot'], e['id'], preview))

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        try:
            id_from = int(self.filter_from.get()) if self.filter_from.get().strip() else None
        except ValueError:
            id_from = None
        try:
            id_to = int(self.filter_to.get()) if self.filter_to.get().strip() else None
        except ValueError:
            id_to = None

        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []
        for idx, e in enumerate(self.entries):
            if id_from is not None and e['id'] < id_from:
                continue
            if id_to is not None and e['id'] > id_to:
                continue
            if query:
                text_lower = e['text'].lower()
                id_str = str(e['id'])
                if query not in text_lower and query not in id_str:
                    continue
            self.filtered_indices.append(idx)
            preview = e['text'].replace('\n', '↵').replace('\t', ' ')[:60]
            self.tree.insert('', 'end', iid=str(idx),
                             values=(e['slot'], e['id'], preview))
        self.status_var.set(f"过滤结果: {len(self.filtered_indices)} / {len(self.entries)} 条目")

    def _clear_filter(self):
        self.search_var.set('')
        self.filter_from.set('')
        self.filter_to.set('')
        self._populate_tree()
        self.status_var.set(f"已加载: {os.path.basename(self.tkt_path or '')} ({len(self.entries)} 条目)")

    def _focus_search(self):
        # 聚焦到搜索框
        for w in self.root.winfo_children():
            if isinstance(w, ttk.Frame):
                for child in w.winfo_children():
                    if isinstance(child, ttk.Entry) and child.cget('textvariable') == str(self.search_var):
                        child.focus_set()
                        return

    # ----------- 条目选择/编辑 -----------
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._load_entry_to_edit(idx)

    def _load_entry_to_edit(self, idx):
        if idx < 0 or idx >= len(self.entries):
            return
        self._current_idx = idx
        e = self.entries[idx]
        self.lbl_info.config(text=f"slot={e['slot']}  ID={e['id']}")
        self.id_var.set(str(e['id']))
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', 'end')
        self.text_widget.insert('1.0', e['text'])
        self._set_edit_enabled(True)
        self.lbl_dirty.config(text="")

    def _on_text_modified(self, event=None):
        if self._current_idx is not None:
            self.lbl_dirty.config(text="[未保存]")

    def _apply_edit(self):
        if self._current_idx is None:
            return
        try:
            new_id = int(self.id_var.get())
        except ValueError:
            messagebox.showerror("ID 错误", "条目 ID 必须是整数。")
            return
        new_text = self.text_widget.get('1.0', 'end-1c')

        e = self.entries[self._current_idx]
        if e['id'] != new_id or e['text'] != new_text:
            e['id'] = new_id
            e['text'] = new_text
            self._dirty = True
            self.lbl_dirty.config(text="")

            # 更新列表显示
            iid = str(self._current_idx)
            if self.tree.exists(iid):
                preview = new_text.replace('\n', '↵').replace('\t', ' ')[:60]
                self.tree.item(iid, values=(e['slot'], new_id, preview))
            self.status_var.set(f"已修改条目 slot={e['slot']}")

    def _reset_edit(self):
        if self._current_idx is not None:
            self._load_entry_to_edit(self._current_idx)

    # ----------- 新增/删除 -----------
    def _new_entry(self):
        if not self.entries:
            messagebox.showinfo("提示", "请先加载 TKT.dat 文件。")
            return

        # 分配新 ID: 当前最大 ID + 1
        max_id = max(e['id'] for e in self.entries)
        new_id = max_id + 1 if max_id >= 0 else 1
        new_slot = len(self.entries)

        new_entry = OrderedDict([
            ('slot', new_slot),
            ('id', new_id),
            ('text', ''),
        ])
        self.entries.append(new_entry)
        self._dirty = True

        # 添加到列表末尾
        idx = len(self.entries) - 1
        self.filtered_indices.append(idx)
        self.tree.insert('', 'end', iid=str(idx),
                         values=(new_slot, new_id, ''))

        # 选中新条目
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        self.status_var.set(f"已新增条目 slot={new_slot}, ID={new_id}")

    def _delete_entry(self):
        if self._current_idx is None:
            return
        e = self.entries[self._current_idx]
        result = messagebox.askyesno(
            "确认删除",
            f"确认删除条目 slot={e['slot']} ID={e['id']}?\n"
            f"文本前 50 字: {e['text'][:50]!r}"
        )
        if not result:
            return

        # 从列表移除
        idx = self._current_idx
        self.entries.pop(idx)
        self._dirty = True

        # 重建 slot 编号
        for i, entry in enumerate(self.entries):
            entry['slot'] = i

        # 刷新列表
        self._current_idx = None
        self._populate_tree()
        self._set_edit_enabled(False)
        self.lbl_info.config(text="未选中")
        self.id_var.set('')
        self.text_widget.delete('1.0', 'end')
        self.status_var.set(f"已删除条目, 剩余 {len(self.entries)} 条目")

    # ----------- 帮助 -----------
    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "TKT.dat 文本数据库编辑器 v1.0\n\n"
            "基于逆向工程 sub_401E88/sub_4067E8/sub_4019D0 实现。\n"
            "支持加载/编辑/保存/新增 TKT.dat 条目。\n\n"
            "控制码:\n"
            "  <FRESET,n> n∈[1,4]    <FCOLOR,n> n∈[1,32]\n"
            "  <FSIZE,n>  n∈[12,48]  <FTYPE,n>  n∈[1,8]\n"
            "  <TEXT,n>   n∈[1,32767] (2字节)\n"
            "  <VARNUM,n> n∈[1,255]  <VARTXT,n> n∈[1,255]\n"
            "  <NAME,n>   n∈[1,2]"
        )


# ============================================================
# CLI
# ============================================================

def main():
    initial_path = None
    if len(sys.argv) > 1:
        initial_path = sys.argv[1]
        if not os.path.exists(initial_path):
            print(f"[ERROR] 文件不存在: {initial_path}", file=sys.stderr)
            return 1

    root = tk.Tk()
    TktEditor(root, initial_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
