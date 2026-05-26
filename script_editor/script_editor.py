#!/usr/bin/env python3
"""
TKD.dat 可视化脚本编辑器
=============================================================
逆向依据:
  - dat_decoder.py:302-318 — XOR 0xFF 解密, Big5 编码
  - tks_dat_decoder_re.py:921-935 — 同上
  - tks_dat_decoder_re.py:1530-1607 — DEFINE 块解析 (write_md_scripts)
  - 运行时转储/decompile/40EBD4.c — 脚本虚拟机 (65+7 操作码)
  - 运行时转储/decompile/452544.c — 文件加载器 (sub_452544)
  - 运行时转储/decompile/402BE8.c — DEFINE 解析器 (sub_402BE8)
  - 运行时转储/strings.txt:391,393 — "TKD.dat" 字符串引用

TKD.dat 格式:
  整个文件用 XOR 0xFF 加密, 解密后为 Big5 编码的纯文本脚本。
  包含 DEFINE 块定义的游戏事件、对话、战斗逻辑等。
  共约 59319 行, 1539 个 DEFINE 块。

用法:
  python script_editor.py
"""

import os, sys, re, tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# ============================================================
# 文件 I/O — XOR 0xFF + Big5
# 证据: dat_decoder.py:302-318, tks_dat_decoder_re.py:921-935
# ============================================================

def load_tkd(filepath):
    """加载 TKD.dat — XOR 0xFF 解密 → Big5 解码

    证据: dat_decoder.py:302-318
      with open(filepath, 'rb') as f: data = f.read()
      decoded = bytes([b ^ 0xFF for b in data])
      text = decoded.decode('big5', errors='replace')

    注意: 反编译结果 (运行时转储/decompile/*.c) 中未找到 aTkdDat 的加载函数,
    本实现基于对解密后文件结构 (DEFINE 块) 的观察验证。
    """
    with open(filepath, 'rb') as f:
        data = f.read()
    decoded = bytes([b ^ 0xFF for b in data])
    try:
        text = decoded.decode('big5', errors='replace')
    except Exception:
        text = decoded.decode('gbk', errors='replace')
    return text


def save_tkd(filepath, text):
    """保存 TKD.dat — Big5 编码 → XOR 0xFF 加密

    逆向保存: 编码为 Big5, 每字节 XOR 0xFF
    """
    try:
        encoded = text.encode('big5')
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = text.encode('gbk', errors='replace')
    encrypted = bytes([b ^ 0xFF for b in encoded])
    with open(filepath, 'wb') as f:
        f.write(encrypted)


# ============================================================
# TKT 文本加载
# 证据: skill_editor.py:92-132, TKT.dat 格式同 TKD.dat 一样用 XOR 0xFF
# ============================================================

def load_tkt(tkt_path):
    """加载 TKT.dat — 文本数据库 (14438 条: 对话、名称、描述)

    证据: skill_editor.py:92-111
    格式: XOR 0xFF 加密, [total_size:4][count:4][encrypted_data...]
    内部: [id_table: count*4][offset_table: count*4][text_blobs...]
    文本解码 Big5 (回退 GBK), 系统 ID 0-9 跳过
    """
    if not tkt_path or not os.path.exists(tkt_path):
        return {}
    with open(tkt_path, 'rb') as f:
        raw = f.read()
    import struct
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt * 4, cnt * 4
    lookup = {}
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
            except Exception:
                s = txt.decode('gbk', errors='replace')
            if s and s != '0':
                lookup[eid] = s.split('\n')[0].strip()
    return lookup


# ============================================================
# DEFINE 块解析
# 证据: tks_dat_decoder_re.py:1530-1560 (write_md_scripts)
# ============================================================

def parse_defines(text):
    """解析 DEFINE 块列表

    格式: "DEFINE <id>" 开始, "};<comment> end" 结束
    证据: tks_dat_decoder_re.py:1541-1559
      for i, line in enumerate(lines_raw):
          stripped = raw_line.strip()
          if stripped.startswith('DEFINE') and not stripped.startswith('//'):
              current_define = {'start': i, 'header': stripped, ...}
          elif stripped.startswith('};') and current_define:
              current_define['end'] = i
              comment = stripped[2:].replace(' end', '').strip()
    """
    lines = text.split('\n')
    defines = []
    current = None
    header_lines = []  # DEFINE 块之前的头部内容 (非注释/非空行)
    pending_prefix = []  # DEFINE 块之间的注释/空行
    seen_first_define = False

    for i, line in enumerate(lines):
        raw_line = line.rstrip('\r')
        stripped = raw_line.strip()

        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            # 提取 DEFINE ID
            parts = stripped.split(None, 1)
            define_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if not seen_first_define:
                seen_first_define = True
            current = {
                'define_id': define_id,
                'comment': '',
                'prefix_lines': list(pending_prefix),  # DEFINE 前的注释/空行
                'body_lines': [],
                'line_start': i,
                'line_end': -1,
                'header_line': raw_line,
            }
            pending_prefix = []
        elif stripped.startswith('};') and current is not None:
            current['line_end'] = i
            comment = stripped[2:].replace(' end', '').strip()
            current['comment'] = comment
            current['body_lines'].append(raw_line)
            defines.append(current)
            current = None
        elif current is not None:
            current['body_lines'].append(raw_line)
        else:
            if not seen_first_define and stripped and not stripped.startswith('//'):
                # 非空非注释行, 属于 header
                header_lines.append(raw_line)
            elif not seen_first_define and stripped.startswith('////'):
                # //// 开头的是文件头标记, 不是注释
                header_lines.append(raw_line)
            else:
                # 空行或注释行, 作为下一个 DEFINE 的 prefix
                pending_prefix.append(raw_line)

    # 文件末尾的空行丢弃, 不归入 header

    return defines, '\n'.join(header_lines)


def rebuild_text(defines, header):
    """从 DEFINE 块列表重建完整文本

    原始 TKD.dat 使用 \\r\\n 行尾, 重建时保持一致。
    parse_defines 中已 strip \\r, 此处重新加上。
    DEFINE 块之间的空行已包含在 prefix_lines 中, 不额外添加。
    """
    parts = []
    if header:
        for hl in header.split('\n'):
            parts.append(hl)
    for d in defines:
        # 包含 DEFINE 块前的注释/分隔行 (已含空行)
        for pl in d.get('prefix_lines', []):
            parts.append(pl)
        parts.append(d['header_line'])
        # body_lines 已包含 };... end 行
        for bl in d['body_lines']:
            parts.append(bl)
    # 原始文件以 \\r\\n\\r\\n 结尾, 添加尾部空行
    parts.append('')
    parts.append('')
    return '\r\n'.join(parts)


def define_display_name(d):
    """DEFINE 块显示名称"""
    comment = d.get('comment', '')
    if comment:
        return f"{d['define_id']}  {comment}"
    return f"{d['define_id']}"


# ============================================================
# 指令参考表 — 完整操作码映射
# 证据: 运行时转储/decompile/40EBD4.c (脚本虚拟机)
# ============================================================

COMMAND_REFERENCE = [
    # (opcode, command, args, handler, description)
    (0,  'End',          'mode',              'inline',      '结束/返回控制 — mode 选择子行为 (0-6, 0xFFFA-0xFFFF)'),
    (1,  'TalkB',        'entity_id,text_id,flags,extra', 'sub_40A220',  '对话+等待 — entity_id:说话实体(-1=当前,-2=调用者), text_id:TKT文本ID'),
    (2,  'TalkB',        'entity_id,text_id,flags,extra', 'sub_40A220',  '对话无等待 — 同TalkB但不阻塞'),
    (3,  'WaitInput',    '—',                  'sub_40AEF4',  '等待输入 — 阻塞直到玩家按键'),
    (4,  'SetNowDef',    'id,x,y',            'sub_40B520',  '切换当前定义 — 改变活动实体定义'),
    (5,  'MenuOp',       '6 args',            'sub_40B1B4',  '复杂菜单/对话操作'),
    (6,  'SetHint',      'id,x,y',            'sub_40B650',  '设置提示信息'),
    (7,  'SetScene',     'id,flag',           'sub_40B710',  '设置场景状态'),
    (8,  'SetWalk',      'id,x,y',            'sub_40BB70',  '设置行走目标 — 实体移动到指定坐标'),
    (9,  'WaitWalk',     'id,flag',           'sub_40BC10',  '等待行走完成 — 阻塞直到实体到达目标'),
    (10, 'CheckFlag',    'id,flag,mode',      'sub_40BCC0',  '条件判断(阻塞) — 检查标志位, false 时阻塞'),
    (11, 'SetEnabled',   'id,flag',           'sub_40BD84',  '启用/禁用实体'),
    (12, 'SetVisible',   'id,flag',           'sub_40BE30',  '设置实体可见性'),
    (13, 'SetWait',      'id,flag',           'sub_40BEDC',  '设置等待状态'),
    (14, 'SetPos',       'id,x,y,flag',       'sub_40BF88',  '设置位置+条件自检'),
    (15, 'Yield',        '—',                  'inline',      '让出控制权 — 保存执行位置并返回'),
    (16, 'Camera',       'x,y,z',             'sub_411BA4',  '镜头控制 — 移动游戏视角'),
    (17, 'FadeIn',       'r,g,b,fade',        'sub_409830',  '屏幕淡入效果'),
    (18, 'FadeOut',      'r,g,b,fade',        'sub_409830',  '屏幕淡出效果'),
    (19, 'ChangeScene',  'scene,x,y,dir',     'sub_40C044',  '切换场景 — 重新加载 TKDefUnit.dat'),
    (20, 'SetAni',       'id,anim,start,end,loop,speed,flag', 'sub_40C1A4', '设置动画序列'),
    (21, 'SetTick',      'id,flag',           'sub_40C388',  '设置 Tick 回调'),
    (22, 'SetShadow',    'id,flag',           'sub_40C428',  '设置阴影'),
    (23, 'SetPos',       'id,x,y,flag',       'sub_40C4D8',  '绝对位置设置'),
    (24, 'Disable',      'id',                'sub_40C5A4',  '禁用实体 — 从场景移除'),
    (25, 'Enable',       'id',                'sub_40C648',  '启用实体 — 添加到场景'),
    (26, 'SetPlayer',    'id',                'sub_40C6EC',  '设置玩家控制的实体'),
    (27, 'SetCamera',    'id',                'sub_40C7CC',  '设置镜头跟随目标'),
    (28, 'SetFlag',      'flag_id',           'sub_40C854',  '设置标志位'),
    (29, 'AddFlag',      'flag_id,value',     'sub_40C8E0',  '增加标志值'),
    (30, 'SetChaPic',    'id,x,y',            'sub_40C9E8',  '设置角色图片'),
    (31, 'SetGlobal',    'value',             'inline',      '设置全局变量 dword_755B60'),
    (32, 'SetFlag',      'flag_id,value',     'sub_40CB08',  '设置标志(带值)'),
    (33, 'AddFlag',      'flag_id,value',     'sub_40CB4C',  '增加标志(带值)'),
    (34, 'TalkA',        'entity_id,text_id,flags,extra,color', 'sub_40A220', '对话(扩展参数) — entity_id:说话实体, text_id:TKT文本ID'),
    (35, 'SetBlock',     'id,flag',           'sub_40CB90',  '设置阻挡状态'),
    (36, 'SetVar',       'slot,value',        'inline',      '写入变量槽 word_755E80[slot]'),
    (37, 'Random',       'slot,min,max',      'inline',      '随机数 → word_755E80[slot]'),
    (38, 'SetFlagVar',   'flag_id,slot',      'inline',      '标志值 → 变量槽'),
    (39, 'AddFlagVar',   'flag_id,slot',      'inline',      '标志累加 → 变量槽'),
    (40, 'CheckTeam',    'id,flag,1',         'sub_40CE30',  '检查队伍状态'),
    (41, 'ShowText',     'id,x,y,duration',   'sub_40B05C',  '显示文本叠加(带计时器)'),
    (42, 'CheckMember',  'id,flag',           'sub_40D0CC',  '检查队伍成员'),
    (43, 'Check43',      'id,flag',           'sub_40D2A0',  '未知检查'),
    (44, 'SceneFade',    'scene_id',          'sub_40D2D0',  '场景过渡(带淡入淡出)'),
    (45, 'Op45',         'id,flag',           'sub_40DA00',  '未知操作'),
    (46, 'Op46',         'id,flag',           'sub_40DBF4',  '未知操作'),
    (47, 'Op47',         'id,flag',           'sub_40DC1C',  '未知操作'),
    (48, 'SetPos48',     'id,x,y',            'sub_40E11C',  '未知位置设置'),
    (49, 'SetSwitch',    'slot,value',        'inline',      '写入开关槽 word_755E10[slot]'),
    (50, 'SetPosFade',   'id,x,y',            'sub_40D804',  '带淡入的位置设置'),
    (51, 'WaitTimer',    'count,delay',        'sub_451780',  '定时等待'),
    (52, 'Wait52',       '—',                  'sub_451D2C',  '未知等待'),
    (53, 'Music',        'id,flag',           'inline',      'BGM 音乐控制'),
    (54, 'SceneBGM',     'scene_id,bgm_flag', 'inline',      '场景 BGM 控制'),
    (55, 'SetWord',      'value',             'inline',      '设置 word_951940'),
    (56, 'Nop',          'padding',           'inline',      '空操作(NOP)'),
    (60, 'CheckResult',  'slot,value,offset', 'inline',      '条件跳转 — 检查变量槽结果'),
    (61, 'CheckFlag61',  'id,flag,offset',    'sub_40E40C',  '条件跳转(标志检查)'),
    (62, 'CheckFlag62',  'id,flag,offset',    'sub_40E4E4',  '条件跳转变体'),
    (63, 'CheckFlag63',  'id,flag,offset',    'sub_40E65C',  '条件跳转变体'),
    (64, 'MenuChoice',   'id,x,y,&result',    'sub_40E97C',  '菜单选择对话'),
    (65, 'Check65',      'id,x,y,offset',     'sub_40E88C',  '条件检查+跳转'),
    (66, 'Check66',      'id,offset',         'sub_40EB10',  '检查+跳转'),
    (82, 'Jump',         'offset',            'inline',      '无条件跳转'),
]

# 构建命令名集合 (用于语法高亮)
COMMAND_NAMES = sorted(set(c[1] for c in COMMAND_REFERENCE), key=lambda x: -len(x))

# 常用脚本命令 (在脚本文本中出现的名称, 可能与操作码名不同)
SCRIPT_COMMANDS = [
    'SetSwitch', 'End', 'CheckFlag', 'Enable', 'Disable', 'SetWalk',
    'WaitWalk', 'SetPos', 'TalkB', 'TalkA', 'War', 'ChangeScene',
    'FadeIn', 'FadeOut', 'PlayerAct', 'SetCursor', 'SetWait',
    'SetNowDef', 'SetFlag', 'AddFlag', 'SetVar', 'Random',
    'SetBlock', 'SetTick', 'SetShadow', 'SetAni', 'SetCamera',
    'SetPlayer', 'SetEnabled', 'SetVisible', 'SetHint', 'SetScene',
    'SetChaPic', 'SetGlobal', 'WaitInput', 'Camera', 'Music',
    'SceneBGM', 'SetWord', 'Nop', 'CheckResult', 'MenuChoice',
    'CheckTeam', 'CheckMember', 'ShowText', 'SceneFade', 'SetPosFade',
    'WaitTimer', 'Yield', 'Jump', 'Else', 'MiniGame', 'Note',
    'StopSound', 'BlackTalk', 'TalkA',
]

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
FONT_MONO = ('Consolas', 10)

# ============================================================
# GUI
# ============================================================

class ScriptEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKD.dat 脚本编辑器")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1280x860")
        self.root.minsize(1000, 650)

        self.tkd_path = None
        self.tkt_path = None
        self.tkt = {}
        self.full_text = ''
        self.header = ''
        self.defines = []
        self.filtered_indices = []
        self._dirty = False
        self._current_idx = -1
        self._cmd_panel_visible = True

        self._build_ui()
        self._set_edit_enabled(False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 1280, 860
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_define())
        self.root.bind('<Control-f>', lambda e: self._show_find())

    # --------------------------------------------------------
    # UI 构建
    # --------------------------------------------------------

    def _build_ui(self):
        # 菜单栏
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录 (Ctrl+O)", command=self._load_tks_dir)
        fm.add_command(label="保存 (Ctrl+S)", command=self._save)
        fm.add_separator()
        fm.add_command(label="导出当前 DEFINE 块...", command=self._export_current)
        fm.add_command(label="导出全部 DEFINE 块...", command=self._export_all)
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_close)
        mb.add_cascade(label="文件", menu=fm)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新增 DEFINE 块 (Ctrl+N)", command=self._new_define)
        em.add_command(label="删除当前 DEFINE 块", command=self._delete_define)
        em.add_separator()
        em.add_command(label="查找/替换 (Ctrl+F)", command=self._show_find)
        mb.add_cascade(label="编辑", menu=em)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)

        # 工具栏
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))

        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', lambda *a: self._apply_filter())
        se = ttk.Entry(tb, textvariable=self.search_var, width=30)
        se.pack(side=tk.LEFT, padx=(2, 10))

        self.status_var = tk.StringVar(value="未加载")
        ttk.Label(tb, textvariable=self.status_var).pack(side=tk.RIGHT)

        # 主面板
        pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧: DEFINE 块列表
        lf = ttk.Frame(pw)
        pw.add(lf, weight=1)

        cols = ('idx', 'id', 'comment', 'lines', 'cmds')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        self.tree.heading('idx', text='#', command=lambda: self._sort_by('idx'))
        self.tree.heading('id', text='DEFINE ID', command=lambda: self._sort_by('id'))
        self.tree.heading('comment', text='注释', command=lambda: self._sort_by('comment'))
        self.tree.heading('lines', text='行数', command=lambda: self._sort_by('lines'))
        self.tree.heading('cmds', text='指令数', command=lambda: self._sort_by('cmds'))
        self.tree.column('idx', width=45, minwidth=35, stretch=False)
        self.tree.column('id', width=100, minwidth=80)
        self.tree.column('comment', width=200, minwidth=100)
        self.tree.column('lines', width=50, minwidth=40)
        self.tree.column('cmds', width=50, minwidth=40)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(fill=tk.Y, side=tk.RIGHT)

        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 右侧: 编辑区
        rf = ttk.Frame(pw)
        pw.add(rf, weight=3)

        # 当前 DEFINE 信息
        info_frame = ttk.Frame(rf)
        info_frame.pack(fill=tk.X, pady=(0, 3))
        self.lbl_info = ttk.Label(info_frame, text="选择一个 DEFINE 块进行编辑",
                                   font=('Microsoft YaHei UI', 10, 'bold'))
        self.lbl_info.pack(side=tk.LEFT)

        # 文本编辑区
        edit_frame = ttk.Frame(rf)
        edit_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = tk.Text(edit_frame, wrap=tk.NONE, font=FONT_MONO,
                                    undo=True, tabs=('4c',))
        self.text_widget.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # 行号 + 滚动条
        sb_y = ttk.Scrollbar(edit_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=sb_y.set)
        sb_y.pack(fill=tk.Y, side=tk.RIGHT)

        sb_x = ttk.Scrollbar(rf, orient=tk.HORIZONTAL, command=self.text_widget.xview)
        self.text_widget.configure(xscrollcommand=sb_x.set)
        sb_x.pack(fill=tk.X)

        # 语法高亮标签
        self.text_widget.tag_configure('keyword', foreground='#0000FF')
        self.text_widget.tag_configure('comment', foreground='#008000')
        self.text_widget.tag_configure('number', foreground='#B07000')
        self.text_widget.tag_configure('string', foreground='#A31515')
        self.text_widget.tag_configure('command', foreground='#7B30D0')
        self.text_widget.tag_configure('block', foreground='#C00000')

        self.text_widget.bind('<KeyRelease>', self._on_text_change)

        # 底部按钮栏
        bb = ttk.Frame(rf)
        bb.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(bb, text="应用修改", command=self._apply_edit).pack(side=tk.LEFT, padx=2)
        ttk.Button(bb, text="重置为当前", command=self._reset_edit).pack(side=tk.LEFT, padx=2)

        # 指令参考面板 (可折叠)
        self._build_cmd_panel(rf)

        # 底部状态栏
        bf = ttk.LabelFrame(self.root, text="文件路径", padding=3)
        bf.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.lbl_tkd_path = ttk.Label(bf, text="TKD.dat: 未加载", foreground='gray')
        self.lbl_tkd_path.pack(side=tk.LEFT, padx=(0, 20))
        self.lbl_tkt_path = ttk.Label(bf, text="TKT.dat: 未加载", foreground='gray')
        self.lbl_tkt_path.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(bf, text="编码: Big5 | 加密: XOR 0xFF",
                  foreground='gray').pack(side=tk.RIGHT)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_cmd_panel(self, parent):
        """构建指令参考面板 (可折叠)"""
        self.cmd_frame = ttk.LabelFrame(parent, text="指令参考 (来自 sub_40EBD4.c 脚本虚拟机)", padding=3)

        # 折叠按钮
        toggle_frame = ttk.Frame(self.cmd_frame)
        toggle_frame.pack(fill=tk.X)
        self._cmd_toggle_text = tk.StringVar(value="▼ 收起指令参考")
        ttk.Button(toggle_frame, textvariable=self._cmd_toggle_text,
                   command=self._toggle_cmd_panel).pack(side=tk.LEFT)

        # 指令表格
        cmd_cols = ('opcode', 'command', 'args', 'handler', 'desc')
        self.cmd_tree = ttk.Treeview(self.cmd_frame, columns=cmd_cols,
                                      show='headings', height=8)
        self.cmd_tree.heading('opcode', text='操作码')
        self.cmd_tree.heading('command', text='指令')
        self.cmd_tree.heading('args', text='参数')
        self.cmd_tree.heading('handler', text='处理函数')
        self.cmd_tree.heading('desc', text='说明')
        self.cmd_tree.column('opcode', width=50, minwidth=40)
        self.cmd_tree.column('command', width=90, minwidth=70)
        self.cmd_tree.column('args', width=180, minwidth=100)
        self.cmd_tree.column('handler', width=100, minwidth=80)
        self.cmd_tree.column('desc', width=400, minwidth=200)

        cmd_sb = ttk.Scrollbar(self.cmd_frame, orient=tk.VERTICAL,
                                command=self.cmd_tree.yview)
        self.cmd_tree.configure(yscrollcommand=cmd_sb.set)
        self.cmd_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        cmd_sb.pack(fill=tk.Y, side=tk.RIGHT)

        # 填充指令数据
        for opcode, cmd, args, handler, desc in COMMAND_REFERENCE:
            self.cmd_tree.insert('', tk.END, values=(opcode, cmd, args, handler, desc))

        self.cmd_frame.pack(fill=tk.BOTH, expand=False, pady=(3, 0))

    def _toggle_cmd_panel(self):
        """切换指令参考面板显示/隐藏"""
        if self._cmd_panel_visible:
            self.cmd_frame.pack_forget()
            self._cmd_toggle_text.value = "▶ 展开指令参考"
            self._cmd_panel_visible = False
        else:
            self.cmd_frame.pack(fill=tk.BOTH, expand=False, pady=(3, 0))
            self._cmd_toggle_text.value = "▼ 收起指令参考"
            self._cmd_panel_visible = True

    # --------------------------------------------------------
    # 数据加载
    # --------------------------------------------------------

    def _load_tks_dir(self):
        """选择 TKS 游戏目录, 加载 TKD.dat 和 TKT.dat"""
        if self._dirty:
            if not messagebox.askyesno("未保存的修改", "当前有未保存的修改, 确定要重新加载吗?"):
                return

        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d:
            return

        tkd_path = os.path.join(d, "TKD.dat")
        tkt_path = os.path.join(d, "TKT.dat")

        if not os.path.exists(tkd_path):
            messagebox.showerror("文件不存在", f"未找到 TKD.dat:\n{tkd_path}")
            return

        self.tkd_path = tkd_path
        self.tkt_path = tkt_path if os.path.exists(tkt_path) else None
        self.tkt = load_tkt(self.tkt_path) if self.tkt_path else {}

        self._reload()
        self.lbl_tkd_path.config(text=f"TKD.dat: {tkd_path}", foreground='green')
        self.lbl_tkt_path.config(
            text=f"TKT.dat: {tkt_path}" if self.tkt_path else "TKT.dat: 未找到",
            foreground='green' if self.tkt_path else 'orange')

    def _reload(self):
        """重新加载 TKD.dat"""
        if not self.tkd_path:
            return
        self.full_text = load_tkd(self.tkd_path)
        self.defines, self.header = parse_defines(self.full_text)
        self._dirty = False
        self._current_idx = -1

        self._apply_filter()
        self.status_var.set(f"已加载 {len(self.defines)} 个 DEFINE 块")
        self._set_edit_enabled(False)
        self.text_widget.delete('1.0', tk.END)
        self.lbl_info.config(text="选择一个 DEFINE 块进行编辑")

    def _apply_filter(self):
        """应用搜索过滤"""
        q = self.search_var.get().strip().lower()
        self.filtered_indices = []
        for i, d in enumerate(self.defines):
            if q:
                searchable = f"{d['define_id']} {d['comment']}".lower()
                # 也在脚本内容中搜索
                body_text = '\n'.join(d['body_lines']).lower()
                if q not in searchable and q not in body_text:
                    continue
            self.filtered_indices.append(i)
        self._refresh_table()

    def _refresh_table(self):
        """刷新 Treeview"""
        self.tree.delete(*self.tree.get_children())
        for seq, i in enumerate(self.filtered_indices):
            d = self.defines[i]
            body = '\n'.join(d['body_lines'])
            cmd_count = len([l for l in d['body_lines']
                            if l.strip() and not l.strip().startswith('//')
                            and not l.strip().startswith('{') and not l.strip().startswith('}')
                            and '(' in l])
            line_count = len(d['body_lines'])
            self.tree.insert('', tk.END, iid=str(i),
                            values=(seq, d['define_id'], d['comment'], line_count, cmd_count))

    # --------------------------------------------------------
    # 编辑操作
    # --------------------------------------------------------

    def _on_tree_select(self, event=None):
        """Treeview 选择事件"""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])

        # 保存当前编辑中的内容
        if self._current_idx >= 0 and self._current_idx < len(self.defines):
            self._save_current_to_defines()

        self._current_idx = idx
        d = self.defines[idx]

        # 更新信息标签
        comment = d['comment']
        info = f"DEFINE {d['define_id']}"
        if comment:
            info += f"  —  {comment}"
        info += f"  (行 {d['line_start']+1}-{d['line_end']+1})"
        self.lbl_info.config(text=info)

        # 先启用编辑器, 再加载内容 (否则首次插入会被 disabled 状态拒绝)
        self._set_edit_enabled(True)

        # 加载脚本内容到文本编辑器
        self.text_widget.delete('1.0', tk.END)
        body = '\n'.join(d['body_lines'])
        self.text_widget.insert('1.0', body)

        self._apply_syntax_highlight()

    def _save_current_to_defines(self):
        """将文本编辑器中的内容保存回当前 defines"""
        if self._current_idx < 0 or self._current_idx >= len(self.defines):
            return
        body = self.text_widget.get('1.0', 'end-1c')
        lines = body.split('\n')
        # 去除末尾空行
        while lines and lines[-1] == '':
            lines.pop()
        self.defines[self._current_idx]['body_lines'] = lines
        self._dirty = True

    def _apply_edit(self):
        """应用当前编辑"""
        if self._current_idx < 0:
            return
        self._save_current_to_defines()
        self._refresh_table()
        # 重新选中当前项
        self.tree.selection_set(str(self._current_idx))
        self.tree.see(str(self._current_idx))
        messagebox.showinfo("已应用", "修改已应用到内存中的数据。\n请使用 文件→保存 写入磁盘。")

    def _reset_edit(self):
        """重置为当前 (重新加载磁盘数据)"""
        if self._current_idx < 0:
            return
        if self._dirty:
            if not messagebox.askyesno("确认重置", "确定要重置吗? 未保存的修改将丢失。"):
                return
        self._reload()

    def _on_text_change(self, event=None):
        """文本变化时更新语法高亮"""
        self._apply_syntax_highlight()

    def _apply_syntax_highlight(self):
        """应用语法高亮"""
        # 清除所有标签
        for tag in ('keyword', 'comment', 'number', 'string', 'command', 'block'):
            self.text_widget.tag_remove(tag, '1.0', tk.END)

        content = self.text_widget.get('1.0', tk.END)
        lines = content.split('\n')

        for i, line in enumerate(lines):
            line_num = i + 1
            stripped = line.strip()

            # 注释
            comment_start = line.find('//')
            if comment_start >= 0:
                start = f"{line_num}.{comment_start}"
                end = f"{line_num}.{len(line)}"
                self.text_widget.tag_add('comment', start, end)

            # 块标记 { }
            if stripped.startswith('{') or stripped.startswith('}'):
                self.text_widget.tag_add('block', f"{line_num}.0", f"{line_num}.{len(line)}")

            # 关键字 DEFINE/end
            if stripped.startswith('DEFINE'):
                self.text_widget.tag_add('keyword', f"{line_num}.0", f"{line_num}.{len(line)}")

            # 指令名 (函数调用形式)
            for cmd in SCRIPT_COMMANDS:
                idx = 0
                while True:
                    pos = line.find(cmd + '(', idx)
                    if pos < 0:
                        break
                    self.text_widget.tag_add('command', f"{line_num}.{pos}",
                                             f"{line_num}.{pos + len(cmd)}")
                    idx = pos + 1

            # 数字
            for m in re.finditer(r'-?\d+', line):
                # 排除在注释中的数字
                if comment_start >= 0 and m.start() >= comment_start:
                    continue
                self.text_widget.tag_add('number', f"{line_num}.{m.start()}",
                                         f"{line_num}.{m.end()}")

    # --------------------------------------------------------
    # 新增/删除 DEFINE 块
    # --------------------------------------------------------

    def _new_define(self):
        """新增 DEFINE 块"""
        if not self.defines:
            messagebox.showwarning("未加载", "请先加载 TKD.dat")
            return

        # 找一个未使用的 ID
        used_ids = {d['define_id'] for d in self.defines}
        new_id = 1
        while new_id in used_ids:
            new_id += 1

        comment = simpledialog.askstring("新增 DEFINE 块",
                                          "请输入注释 (可留空):",
                                          parent=self.root)
        if comment is None:
            return

        new_define = {
            'define_id': new_id,
            'comment': comment or '',
            'body_lines': ['{', '\t', '}; end'],
            'line_start': -1,
            'line_end': -1,
            'header_line': f"DEFINE {new_id}",
        }
        self.defines.append(new_define)
        self._dirty = True

        self.search_var.set('')      # 清除搜索过滤，确保新项可见
        self._apply_filter()
        # 选中新添加的项
        new_idx = len(self.defines) - 1
        self.tree.selection_set(str(new_idx))
        self.tree.see(str(new_idx))
        self.status_var.set(f"已添加 DEFINE {new_id}, 共 {len(self.defines)} 个块")

    def _delete_define(self):
        """删除当前选中的 DEFINE 块"""
        if self._current_idx < 0:
            return
        d = self.defines[self._current_idx]
        comment = d['comment']
        name = f"DEFINE {d['define_id']}"
        if comment:
            name += f" ({comment})"

        if not messagebox.askyesno("确认删除", f"确定要删除 {name} 吗?"):
            return

        del self.defines[self._current_idx]
        self._current_idx = -1
        self._dirty = True
        self._apply_filter()
        self.text_widget.delete('1.0', tk.END)
        self.lbl_info.config(text="选择一个 DEFINE 块进行编辑")
        self._set_edit_enabled(False)
        self.status_var.set(f"已删除, 剩余 {len(self.defines)} 个 DEFINE 块")

    # --------------------------------------------------------
    # 查找/替换
    # --------------------------------------------------------

    def _show_find(self):
        """显示查找/替换对话框"""
        dlg = tk.Toplevel(self.root)
        dlg.title("查找/替换")
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 400, 150)

        ttk.Label(dlg, text="查找:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        find_var = tk.StringVar()
        ttk.Entry(dlg, textvariable=find_var, width=30).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(dlg, text="替换:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        replace_var = tk.StringVar()
        ttk.Entry(dlg, textvariable=replace_var, width=30).grid(row=1, column=1, padx=5, pady=5)

        def do_find():
            self.text_widget.tag_remove('find_highlight', '1.0', tk.END)
            target = find_var.get()
            if not target:
                return
            start = '1.0'
            count = 0
            while True:
                pos = self.text_widget.search(target, start, tk.END)
                if not pos:
                    break
                end = f"{pos}+{len(target)}c"
                self.text_widget.tag_add('find_highlight', pos, end)
                start = end
                count += 1
            self.text_widget.tag_configure('find_highlight', background='yellow')
            if count == 0:
                messagebox.showinfo("查找", "未找到匹配项。", parent=dlg)
            else:
                messagebox.showinfo("查找", f"找到 {count} 个匹配项。", parent=dlg)

        def do_replace_all():
            target = find_var.get()
            replacement = replace_var.get()
            if not target:
                return
            content = self.text_widget.get('1.0', 'end-1c')
            new_content = content.replace(target, replacement)
            if new_content != content:
                self.text_widget.delete('1.0', tk.END)
                self.text_widget.insert('1.0', new_content)
                count = content.count(target)
                messagebox.showinfo("替换", f"已替换 {count} 处。", parent=dlg)
            else:
                messagebox.showinfo("替换", "未找到匹配项。", parent=dlg)

        bf = ttk.Frame(dlg)
        bf.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="查找全部", command=do_find).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="全部替换", command=do_replace_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="关闭", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # --------------------------------------------------------
    # 保存
    # --------------------------------------------------------

    def _save(self):
        """保存 TKD.dat"""
        if not self.tkd_path:
            messagebox.showwarning("未加载", "请先加载 TKD.dat")
            return

        # 保存当前编辑中的内容
        if self._current_idx >= 0:
            self._save_current_to_defines()

        if not messagebox.askyesno("确认保存",
                                    f"确定要保存到:\n{self.tkd_path}\n\n"
                                    f"共 {len(self.defines)} 个 DEFINE 块?"):
            return

        # 备份
        try:
            bak_path = self.tkd_path + '.bak'
            with open(self.tkd_path, 'rb') as s:
                with open(bak_path, 'wb') as d:
                    d.write(s.read())
        except Exception:
            pass

        # 重建文本并保存
        text = rebuild_text(self.defines, self.header)
        try:
            save_tkd(self.tkd_path, text)
            self._dirty = False
            messagebox.showinfo("保存成功",
                                f"已保存 {len(self.defines)} 个 DEFINE 块\n"
                                f"备份: {self.tkd_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    # --------------------------------------------------------
    # 导出
    # --------------------------------------------------------

    def _export_current(self):
        """导出当前 DEFINE 块"""
        if self._current_idx < 0:
            return
        self._save_current_to_defines()
        d = self.defines[self._current_idx]

        path = filedialog.asksaveasfilename(
            title="导出当前 DEFINE 块",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"DEFINE_{d['define_id']}.txt")
        if not path:
            return

        lines = [d['header_line']]
        lines.extend(d['body_lines'])
        comment = d['comment']
        lines.append(f"}};{comment} end" if comment else "}; end")

        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        messagebox.showinfo("导出成功", f"已导出到:\n{path}")

    def _export_all(self):
        """导出全部 DEFINE 块"""
        if not self.defines:
            return
        self._save_current_to_defines()

        path = filedialog.asksaveasfilename(
            title="导出全部 DEFINE 块",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="TKD_decoded.txt")
        if not path:
            return

        text = rebuild_text(self.defines, self.header)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        messagebox.showinfo("导出成功", f"已导出 {len(self.defines)} 个 DEFINE 块到:\n{path}")

    # --------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------

    def _set_edit_enabled(self, en):
        """启用/禁用编辑区"""
        state = 'normal' if en else 'disabled'
        self.text_widget.config(state=state)

    def _sort_by(self, col):
        """按列排序"""
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children()]
        try:
            items.sort(key=lambda t: int(t[0]))
        except ValueError:
            items.sort(key=lambda t: t[0])
        for i, (_, k) in enumerate(items):
            self.tree.move(k, '', i)

    def _center_dialog(self, dlg, w, h):
        """居中对话框"""
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

    def _show_about(self):
        """显示关于信息"""
        messagebox.showinfo("关于 TKD.dat 脚本编辑器",
                            "TKD.dat 脚本编辑器\n\n"
                            "基于游戏逆向工程:\n"
                            "  - 运行时转储/decompile/40EBD4.c (脚本虚拟机)\n"
                            "  - 运行时转储/decompile/452544.c (文件加载器)\n"
                            "  - 运行时转储/decompile/402BE8.c (DEFINE 解析器)\n\n"
                            "文件格式: XOR 0xFF 加密, Big5 编码\n"
                            f"指令数: {len(COMMAND_REFERENCE)} 个操作码\n\n"
                            "用法: 选择 TKS 游戏目录加载 TKD.dat")

    def _on_close(self):
        """关闭窗口"""
        if self._dirty:
            if not messagebox.askyesno("未保存的修改", "有未保存的修改, 确定要退出吗?"):
                return
        self.root.destroy()


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()
    ScriptEditor(root)
    root.mainloop()


if __name__ == '__main__':
    main()
