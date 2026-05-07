#!/usr/bin/env python3
"""
WarPC.dat 可视化编辑器 v1.0
=============================================================
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

字段布局 (仅列出反编译已验证的字段; 未验证字段标注 "未验证"):
  [0]   name_id      — 角色名称 TKT ID
  [1]   portrait     — 立绘/精灵索引 (+211=JVG资源)
  [2]   level        — 等级
  [3]   role         — 身份 (0=敌方 -1=我方)
  [4]   exp_to_next  — 升级所需经验 (大多数=100; 敌方版较高: 呂布5092 張角7292)

  [5]   cur_hp       — 当前生命 (cap at hp_max)
  [6]   cur_mp       — 当前内力 (cap at mp_max)
  [7]   hp_base      — 生命基础值
  [8]   hp_max       — 生命上限 (基础+装备)
  [9]   mp_base      — 内力基础值
  [10]  mp_max       — 内力上限 (基础+装备)

  8 通用属性 (基础/当前) — sub_42234C + sub_41E40C 验证:
  [11]  atk_base     — 攻击(基础)    [12]  atk_cur  — 攻击(当前)
  [13]  def_base     — 防御(基础)    [14]  def_cur  — 防御(当前)
  [15]  hit_base     — 命中(基础)    [16]  hit_cur  — 命中(当前)
  [17]  eva_base     — 闪避(基础)    [18]  eva_cur  — 闪避(当前)
  [19]  spd_base     — 速度(基础)    [20]  spd_cur  — 速度(当前)
  [21]  luk_base     — 幸运(基础)    [22]  luk_cur  — 幸运(当前)
  [23]  mov_base     — 移动(基础)    [24]  mov_cur  — 移动(当前)  ※TKItem[18]=vit
  [25]  wis_base     — 悟性(基础)    [26]  wis_cur  — 悟性(当前)  ※TKItem[17]=spi

  [31]  field_31     — 等级强相关 (r=0.992), 疑似技能点数/累计经验

  [268] jp_reward    — 战后JP点 (直接值, 无等级缩放; 盜賊嘍嘍=2 西羌王=100)
  [269] gold_reward  — 战后金钱基数 (实际获得 = 基数 × 2; 盜賊=20→40 小混混=25→50)

  [32]-[42] runtime  — 运行时状态 (sub_42234C 初始化, 非角色固有属性, 语义未验证)

  [51]-[66] skill_eff — 技能效果槽 (16个; sub_42234C 初始化为 0)

  [67]  cause_mask1  — 导致状态掩码1 (1-16; 来自装备 v9[26])
  [68]  cause_mask2  — 导致状态掩码2 (17-32; 来自装备 v9[27])

  [69]-[72] equip_idx —运行时装备索引缓存 (sub_4173F8 从 [73-76] 计算)
  [73]-[76] equip_id  — 装备物品 ID (DAT 原始; 查 TKItem.field[0])

  [82]-[87] equip_skill — 装备技能区 (6字段; Maker Frm_WarPC 暴露; sub_42234C/sub_422BBC 应用)
                         [82]=装备技能0 [83]=装备技能1 [84]=装备技能2 [85]=装备技能3
                         [86]=被动技能1 [87]=被动技能2
                         验证: 周倉 [82]=43武術 [83]=83輔助 [84]=273二連擊 [85]=279無隙1 [86]=303近戰反擊1 [87]=334飄浮

用法:
  python warpc_editor.py
"""

import struct, os, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# LZSS 编解码 (sub_452B14)
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

# ============================================================
# TKT 文本加载
# ============================================================

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

# ============================================================
# 常量
# ============================================================

WARPC_REC = 1054      # 527 × int16
WARPC_CNT = 143
WARPC_FIELD_COUNT = 527
WARPC_DECOMPRESSED = 150722

FONT = ('Microsoft YaHei UI', 9); FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 8

# ============================================================
# 字段定义 — 按功能分组, 基于反编译验证
# ============================================================

# 统计名称 (8 通用属性, sub_42234C + sub_41E40C 验证)
# TKItem[11-18] → WarPC[11-26]: 攻击/防御/命中/闪避/速度/幸运/悟性/移动
STAT_NAMES = ["攻击", "防御", "命中", "闪避", "速度", "幸运", "移动", "悟性"]
STAT_SHORTS = ["atk", "def", "hit", "eva", "spd", "luk", "mov", "wis"]

# 核心字段 — 已验证 (格式: key, offset, label, comment)
IDENTITY_FIELDS = [
    ("name_id",    0,  "名称TKT ID",  "角色名称 → TKT.dat (sub_4067E8)"),
    ("portrait",   2,  "立绘索引",    "立绘/精灵索引 (+211=JVG精灵资源)"),
    ("level",      4,  "等级",        "角色等级 (数值显示)"),
    ("role",       6,  "身份",        "0=敌方 -1=我方"),
    ("exp_to_next", 8,  "升级所需经验","升至下一级所需经验; 绝大多数角色=100, 敌方版较高(呂布5092 張角7292)"),
]

HPMP_FIELDS = [
    ("cur_hp",    10,  "当前HP",      "当前生命值 (cap at hp_max)"),
    ("cur_mp",    12,  "当前MP",      "当前内力值 (cap at mp_max)"),
    ("hp_base",   14,  "HP基础",      "HP基础值"),
    ("hp_max",    16,  "HP上限",      "HP上限 (基础+装备; sub_42234C)"),
    ("mp_base",   18,  "MP基础",      "MP基础值"),
    ("mp_max",    20,  "MP上限",      "MP上限 (基础+装备; sub_42234C)"),
]

# 8 属性对 (基础/当前) — sub_42234C L24-31/63-70 验证
STAT_FIELDS = []
STAT_BASE_OFFSETS = [22, 26, 30, 34, 38, 42, 46, 50]  # byte offsets for [11,13,15,17,19,21,23,25]
for i, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_BASE_OFFSETS)):
    STAT_FIELDS.append((f"{short}_base", bo, f"{name}(基础)",
                        f"{name}基础值 (sub_42234C: a2[{11+i*2}] initial)"))
    STAT_FIELDS.append((f"{short}_cur", bo + 2, f"{name}(当前)",
                        f"{name}当前值 (基础+装备; sub_42234C L63-70 a2[{12+i*2}]+=v9[{11+i}])"))

# 运行时状态 [32]-[42] — sub_42234C 初始化, 非角色固有属性
# 语义未验证, 旧名(反击/精算/连击/格挡)均为臆测, 标注为运行时状态
RUNTIME_STATE_FIELDS = [
    ("field_32",    64,  "运行时[32]",  "sub_42234C 初始化为 1 (行动标志) — 语义未验证"),
    ("field_33",    66,  "运行时[33]",  "装备特殊标志 OR (sub_42234C L73: a2[33]|=v9[20]) — 语义未验证"),
    ("field_34",    68,  "运行时[34]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_35",    70,  "运行时[35]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_36",    72,  "运行时[36]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_37",    74,  "运行时[37]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_38",    76,  "运行时[38]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_39",    78,  "运行时[39]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_40",    80,  "运行时[40]",  "sub_42234C 初始化为 0 — 语义未验证"),
    ("field_41",    82,  "运行时[41]",  "sub_422BBC type=2 写入反应组编号 — 语义未验证"),
    ("field_42",    84,  "运行时[42]",  "sub_422BBC v6[44] 写入触发概率 — 语义未验证"),
]

EQUIP_FIELDS = [
    ("equip_idx0", 138, "装备索引0",   "运行时装备索引缓存 (sub_4173F8 计算)"),
    ("equip_idx1", 140, "装备索引1",   "运行时装备索引缓存"),
    ("equip_idx2", 142, "装备索引2",   "运行时装备索引缓存"),
    ("equip_idx3", 144, "装备索引3",   "运行时装备索引缓存"),
    ("equip_id0",  146, "装备物品ID0", "装备物品 ID (DAT原始; 查 TKItem.field[0])"),
    ("equip_id1",  148, "装备物品ID1", "装备物品 ID"),
    ("equip_id2",  150, "装备物品ID2", "装备物品 ID"),
    ("equip_id3",  152, "装备物品ID3", "装备物品 ID"),
]

# 装备技能 [82]-[87] — Maker Frm_WarPC 暴露, sub_42234C/sub_422BBC 应用
# 周倉 验证: [82]=43武術 [83]=83輔助 [84]=273二連擊 [85]=279無隙1 [86]=303近戰反擊1 [87]=334飄浮
EQUIP_SKILL_FIELDS = [
    ("equip_skill0", 164, "装备技能0", "装备技能槽0 → TKSkill (sub_42234C v4 loop)"),
    ("equip_skill1", 166, "装备技能1", "装备技能槽1 → TKSkill"),
    ("equip_skill2", 168, "装备技能2", "装备技能槽2 → TKSkill (sub_42234C: a2[84])"),
    ("equip_skill3", 170, "装备技能3", "装备技能槽3 → TKSkill (sub_42234C: a2[85])"),
    ("passive1",     172, "被动技能1", "被动技能1 → TKSkill (sub_422BBC)"),
    ("passive2",     174, "被动技能2", "被动技能2 → TKSkill (sub_422BBC)"),
]

STATUS_FIELDS = [
    ("cause_mask1", 134, "状态掩码1",  "导致状态掩码1 (1-16; 来自装备 v9[26])"),
    ("cause_mask2", 136, "状态掩码2",  "导致状态掩码2 (17-32; 来自装备 v9[27])"),
]

# 战后奖励 — 实测验证: 盜賊嘍嘍 field[268]=2→JP=2, field[269]=20→Lv3 Gold=40
BATTLE_REWARD_FIELDS = [
    ("jp_reward",   536, "战后JP点",   "击败后获得技能点数 (直接值, 无等级缩放); 盜賊嘍嘍=2 西羌王=100"),
    ("gold_reward", 538, "战后金钱基数","击败后获得金钱基数; 实际获得=基数×2; 盜賊嘍嘍=20→40 小混混=25→50"),
]

# 成长率 [264]-[266] — 五爪金龍验证: 初期27 中期24 后期21
GROWTH_FIELDS = [
    ("growth_early", 528, "成长率初期", "成长率初期; 五爪金龍=27 西羌王=27 呂布=20"),
    ("growth_mid",   530, "成长率中期", "成长率中期; 五爪金龍=24 西羌王=24 呂布=25"),
    ("growth_late",  532, "成长率后期", "成长率后期; 五爪金龍=21 西羌王=21 呂布=25"),
]

# 可掉落物品 [270]-[272] — 五爪金龍验证: 顛海神珠(537) 金龍魂(234) 虎項龍紋鎧(8081)
DROP_ITEM_FIELDS = [
    ("drop_item0", 540, "掉落物品0",  "可掉落物品0 ID; 五爪金龍=顛海神珠(537)"),
    ("drop_item1", 542, "掉落物品1",  "可掉落物品1 ID; 五爪金龍=金龍魂(234)"),
    ("drop_item2", 544, "掉落物品2",  "可掉落物品2 ID; 五爪金龍=虎項龍紋鎧(8081)"),
]

# 技能效果槽 [51]-[66]
SKILL_EFF_FIELDS = []
for i in range(16):
    SKILL_EFF_FIELDS.append(
        (f"skill_eff{i}", 102 + i*2, f"技能效果{i}", f"技能效果槽{i} (sub_42234C 初始化为 0)"))

# 未验证字段 (偏移范围)
UNVERIFIED_RANGES = [
    ("未验证 27-31",  54, 5,  "字段 [27]-[31] — 无反编译直接引用, 示例值: 50,50,50,25,0"),
    ("未验证 43-50",  86, 8,  "字段 [43]-[50] — 无反编译直接引用, 示例全=-256"),
    ("未验证 77-81", 154, 5,  "字段 [77]-[81] — 无反编译直接引用; [78]装备相关,[79]装备类型位掩码"),
    ("未验证 88-101",176,14,  "字段 [88]-[101] — 无反编译直接引用; [88-89]部分角色有值"),
]

# 超出已验证范围的大段尾部
TAIL_START = 101  # int16 offset
TAIL_END = 527

# ============================================================
# 数据加载/保存
# ============================================================

def load_warpc(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    if len(dec) != WARPC_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 {WARPC_DECOMPRESSED} (Maker.exe sub_4027FF)")
    recs = []
    for i in range(WARPC_CNT):
        off = i * WARPC_REC
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, off)
        recs.append({'index': i, 'fields': list(vals)})
    return recs

def save_warpc(fp, recs):
    buf = bytearray(WARPC_CNT * WARPC_REC)
    for rec in recs[:WARPC_CNT]:
        i = rec['index']; off = i * WARPC_REC
        struct.pack_into('<' + 'h' * WARPC_FIELD_COUNT, buf, off, *rec['fields'])
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

def get_field(rec, byte_off):
    return rec['fields'][byte_off // 2]

def set_field(rec, byte_off, val):
    rec['fields'][byte_off // 2] = val

# ============================================================
# GUI
# ============================================================

class WarpcEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("WarPC.dat 可视化编辑器 v1.0")
        self.root.geometry("1320x820"); self.root.minsize(1050, 650)
        self.warpc_path = self.tkt_path = None
        self.records = []; self.tkt = {}; self.skill_names = {}; self._skill_types = {}; self.item_names = {}; self.item_idx_names = {}; self._idx_to_id = {}; self._id_to_idx = {}
        self.filtered_indices = []; self._dirty = False
        self._edit_vars = {}; self._edit_extras = {}; self._tab_grids = {}
        self._build_ui(); self._set_edit_enabled(False)

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root); self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator(); fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root); tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=22); e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned); paned.add(lf, weight=1)
        cols = ('index', 'name', 'level', 'role', 'hp', 'mp')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [
            ('index', '#', 40), ('name', '角色名称', 130), ('level', '等级', 45),
            ('role', '身份', 50), ('hp', 'HP', 70), ('mp', 'MP', 70),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # Right: Edit panel with Notebook tabs
        rf = ttk.Frame(paned); paned.add(rf, weight=3)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 4), padx=4)

        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: 核心属性
        tab1 = ttk.Frame(self.notebook); self.notebook.add(tab1, text="核心属性")
        t1_canvas = tk.Canvas(tab1, highlightthickness=0)
        t1_sb = ttk.Scrollbar(tab1, orient=tk.VERTICAL, command=t1_canvas.yview)
        t1_canvas.configure(yscrollcommand=t1_sb.set)
        self.t1_inner = ttk.Frame(t1_canvas)
        t1_canvas.create_window((0, 0), window=self.t1_inner, anchor='nw')
        t1_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t1_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1_inner.bind('<Configure>', lambda e: t1_canvas.configure(scrollregion=t1_canvas.bbox('all')))
        self._bind_mousewheel(t1_canvas)

        # Tab 2: 装备与技能
        tab2 = ttk.Frame(self.notebook); self.notebook.add(tab2, text="装备与技能")
        t2_canvas = tk.Canvas(tab2, highlightthickness=0)
        t2_sb = ttk.Scrollbar(tab2, orient=tk.VERTICAL, command=t2_canvas.yview)
        t2_canvas.configure(yscrollcommand=t2_sb.set)
        self.t2_inner = ttk.Frame(t2_canvas)
        t2_canvas.create_window((0, 0), window=self.t2_inner, anchor='nw')
        t2_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t2_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2_inner.bind('<Configure>', lambda e: t2_canvas.configure(scrollregion=t2_canvas.bbox('all')))
        self._bind_mousewheel(t2_canvas)

        # Tab 3: 全部字段 (raw grid)
        tab3 = ttk.Frame(self.notebook); self.notebook.add(tab3, text="全部字段")
        t3_canvas = tk.Canvas(tab3, highlightthickness=0)
        t3_sb = ttk.Scrollbar(tab3, orient=tk.VERTICAL, command=t3_canvas.yview)
        t3_canvas.configure(yscrollcommand=t3_sb.set)
        self.t3_inner = ttk.Frame(t3_canvas)
        t3_canvas.create_window((0, 0), window=self.t3_inner, anchor='nw')
        t3_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); t3_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3_inner.bind('<Configure>', lambda e: t3_canvas.configure(scrollregion=t3_canvas.bbox('all')))
        self._bind_mousewheel(t3_canvas)

        # Bottom buttons
        bf = ttk.Frame(rf); bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit, width=12).pack(side=tk.LEFT, padx=2)

        # Build tab contents
        self._build_tab1(self.t1_inner)
        self._build_tab2(self.t2_inner)
        self._build_tab3(self.t3_inner)

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载"); pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_warpc = ttk.Label(pf, text="", foreground="gray")
        self.lbl_warpc.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_item = ttk.Label(pf, text="", foreground="gray")
        self.lbl_item.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_skill = ttk.Label(pf, text="", foreground="gray")
        self.lbl_skill.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_tab1(self, parent):
        """核心属性 — 基本信息 + HP/MP + 8属性 + 战斗能力 + 状态掩码"""
        self._build_section(parent, "基本信息", IDENTITY_FIELDS, 0)
        self._build_section(parent, "HP / MP", HPMP_FIELDS, 1)
        # 八属性 — 一行八列紧凑布局
        self._build_stat_row(parent)
        self._build_section(parent, "运行时状态 [32]-[42] (sub_42234C 初始化, 语义未验证)", RUNTIME_STATE_FIELDS, 3)
        self._build_section(parent, "状态掩码 (来源于装备; sub_42234C L94-95)", STATUS_FIELDS, 4)
        self._build_section(parent, "未验证字段 [27]-[30] (无反编译引用)", [], 5)
        lf = ttk.LabelFrame(parent, text="未验证字段 [27]-[30] (无反编译直接引用)", padding=4)
        lf.grid(row=5, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        for j in range(4):
            off = 54 + j*2
            fn = f"field_{off//2}"
            self._build_field_widget(grid, j // 8, j % 8, fn, off, f"[{27+j}]", W_INPUT,
                                     "无反编译直接引用")
        # field[31] separately — strong level correlation
        self._build_section(parent, "field[31] (等级强相关 r=0.992, 疑似技能点数/累计经验)", [], 6)
        lf2 = ttk.LabelFrame(parent, text="field[31] (与等级高度相关 r=0.992)", padding=4)
        lf2.grid(row=6, column=0, sticky='ew', padx=2, pady=2)
        grid2 = ttk.Frame(lf2); grid2.pack(fill=tk.X)
        self._build_field_widget(grid2, 0, 0, "field_31", 62, "[31]", W_INPUT,
                                 "等级强相关; Lv1=0, Lv10=150, Lv20=265, Lv35=400; 疑似技能点数或累计经验")
        # 战后奖励 [268]-[269]
        self._build_section(parent, "成长率 [264]-[266] (五爪金龍: 初期27 中期24 后期21)", GROWTH_FIELDS, 7)
        self._build_section(parent, "战后奖励 [268]-[269] (Gold=基数×2; JP=直接值)", BATTLE_REWARD_FIELDS, 8)
        self._build_section(parent, "可掉落物品 [270]-[272] (五爪金龍验证: 顛海神珠/金龍魂/虎項龍紋鎧)", DROP_ITEM_FIELDS, 9, ft='item_pick')

    def _build_stat_row(self, parent):
        """八属性 — 一行八列, 每列(名称 + 基础 + 当前)"""
        lf = ttk.LabelFrame(parent, text="八属性 (基础/当前 = 基础+装备加成)", padding=4)
        lf.grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        for c in range(8):
            lf.columnconfigure(c, weight=1, minsize=90)

        for ci, (name, short, bo) in enumerate(zip(STAT_NAMES, STAT_SHORTS, STAT_BASE_OFFSETS)):
            col = ttk.Frame(lf); col.grid(row=0, column=ci, sticky='n', padx=3, pady=2)

            # 属性名
            lbl = ttk.Label(col, text=name, font=('', 9, 'bold'))
            lbl.pack(anchor=tk.CENTER)

            # 基础值
            fn_base = f"{short}_base"
            frm_b = ttk.Frame(col); frm_b.pack(fill=tk.X, pady=(2, 0))
            ttk.Label(frm_b, text="基础", font=FONT_S, foreground='#888').pack(side=tk.LEFT)
            ev_b = tk.StringVar(); self._edit_vars[fn_base] = ev_b
            ttk.Entry(frm_b, textvariable=ev_b, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_b, f"[{bo//2}] {name}基础值 (sub_42234C: a2[{11+ci*2}] initial)")

            # 当前值
            fn_cur = f"{short}_cur"
            frm_c = ttk.Frame(col); frm_c.pack(fill=tk.X)
            ttk.Label(frm_c, text="当前", font=FONT_S, foreground='#228B22').pack(side=tk.LEFT)
            ev_c = tk.StringVar(); self._edit_vars[fn_cur] = ev_c
            ttk.Entry(frm_c, textvariable=ev_c, width=5, font=FONT, justify='center').pack(side=tk.RIGHT)
            self._bind_tooltip(frm_c, f"[{bo//2+1}] {name}当前值 (基础+装备; sub_42234C L63-70)")

    def _build_tab2(self, parent):
        """装备与技能"""
        self._build_section(parent, "装备索引 [69]-[72] (TKItem数组下标; 运行时缓存)", EQUIP_FIELDS[:4], 0, ft='item_pick')
        self._build_section(parent, "装备物品 ID [73]-[76] (DAT原始; 查 TKItem.field[0])", EQUIP_FIELDS[4:], 1, ft='item_pick')
        self._build_section(parent, "装备技能 [82]-[87] (6字段; sub_42234C/sub_422BBC; Maker验证: 周倉)", EQUIP_SKILL_FIELDS, 2, ft='skill_pick')
        self._build_section(parent, "技能效果槽 [51]-[66] (16个; sub_42234C 初始化为 0)", SKILL_EFF_FIELDS, 3)
        # unverified ranges on tab2
        for row, (title, off, cnt, cmt) in enumerate(UNVERIFIED_RANGES, 4):
            lf = ttk.LabelFrame(parent, text=f"{title} ({cmt[:40]}...)", padding=4)
            lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
            grid = ttk.Frame(lf); grid.pack(fill=tk.X)
            for j in range(cnt):
                bo = off + j*2
                fn = f"field_{bo//2}"
                self._build_field_widget(grid, j // 8, j % 8, fn, bo, f"[{bo//2}]", 7, cmt)

    def _build_tab3(self, parent):
        """全部 527 字段的紧凑网格"""
        self._tab3_labels = []
        self._tab3_entries = []
        COLS = 8
        # Show all fields 0-526 in groups of 100
        for base in range(0, 527, 100):
            end = min(base + 100, 527)
            lf = ttk.LabelFrame(parent, text=f"字段 [{base}] — [{end-1}] (int16 偏移)", padding=4)
            lf.pack(fill=tk.X, padx=2, pady=2)
            grid = ttk.Frame(lf); grid.pack(fill=tk.X)
            for j in range(base, end):
                r, c = divmod(j - base, COLS)
                bo = j * 2
                fn = f"raw_{j}"
                frm = ttk.Frame(grid); frm.grid(row=r, column=c, sticky='w', padx=1, pady=1)
                lbl = ttk.Label(frm, text=f"[{j}]", font=('Consolas', 7), foreground='#888')
                lbl.pack(anchor=tk.W)
                ev = tk.StringVar(); self._edit_vars[fn] = ev
                ent = ttk.Entry(frm, textvariable=ev, width=6, font=('Consolas', 7))
                ent.pack(fill=tk.X)
                self._tab3_entries.append((j, fn, lbl))
            # configure grid columns
            for c in range(COLS):
                grid.columnconfigure(c, weight=1, minsize=90)

    def _build_section(self, parent, title, fields, row, cols=8, ft='int'):
        lf = ttk.LabelFrame(parent, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf); grid.pack(fill=tk.X)
        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            self._build_field_widget(grid, fi // cols, fi % cols, fn, fo, fl, W_INPUT, cmt, ft)

    def _build_field_widget(self, parent, row, col, fn, fo, fl, fw, cmt, ft='int'):
        frm = ttk.Frame(parent); frm.grid(row=row, column=col, sticky='nw', padx=2, pady=1)
        lbl = ttk.Label(frm, text=fl, font=FONT_S); lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo//2}] byte {fo}: {cmt}")
        ev = tk.StringVar(); self._edit_vars[fn] = ev
        if fn == 'role':
            cb = ttk.Combobox(frm, state='readonly', values=['-1-我方', '0-敌方'],
                              width=fw + 3, font=FONT)
            cb.pack(fill=tk.X)
            self._edit_extras[fn] = cb
        elif ft in ('skill_pick', 'item_pick'):
            pick_fn = self._pick_skill if ft == 'skill_pick' else self._pick_item
            box = ttk.Frame(frm); box.pack(fill=tk.X)
            ttk.Entry(box, textvariable=ev, width=fw, font=FONT).pack(side=tk.LEFT)
            ttk.Button(box, text='…', width=2,
                       command=lambda f=fn: pick_fn(f)).pack(side=tk.LEFT, padx=1)
            color = '#3366cc' if ft == 'skill_pick' else '#CC6633'
            self._edit_extras[fn] = ttk.Label(frm, text='', foreground=color,
                                               font=FONT_S, wraplength=150)
            self._edit_extras[fn].pack(anchor=tk.W)
        else:
            ttk.Entry(frm, textvariable=ev, width=fw, font=FONT).pack(fill=tk.X)

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']: return
            x = widget.winfo_rootx() + 10; y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget); w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=420, padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']: tip['win'].destroy(); tip['win'] = None
        widget.bind('<Enter>', _enter); widget.bind('<Leave>', _leave)

    def _bind_mousewheel(self, canvas):
        def _mw(e): canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        wp = os.path.join(d, "WarPC.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(wp):
            messagebox.showwarning("文件缺失", "未找到 WarPC.dat"); return
        self.warpc_path = wp
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _load_skill_names(self):
        """加载 TKSkill.dat → {skill_index: name} 查找表 + 类型表"""
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        sk_path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(sk_path):
            return {}, {}
        try:
            with open(sk_path, 'rb') as f:
                dec = lzss_decompress(f.read())
            name_lookup = {}; type_lookup = {}
            for i in range(350):
                off = i * 94
                if off + 6 > len(dec): break
                name_id = struct.unpack_from('<h', dec, off)[0]
                stype = struct.unpack_from('<h', dec, off + 4)[0]
                type_lookup[i] = stype
                if name_id > 0 and name_id in self.tkt:
                    name_lookup[i] = self.tkt[name_id].split('\n')[0].strip()[:20]
                elif name_id:
                    name_lookup[i] = f'#{name_id}'
            return name_lookup, type_lookup
        except Exception:
            return {}, {}

    def _load_item_names(self):
        """加载 TKItem.dat → {item_id: item_name} + {item_index: item_name}"""
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        it_path = os.path.join(tks_dir, 'TKItem.dat')
        if not os.path.exists(it_path):
            return {}, {}
        try:
            with open(it_path, 'rb') as f:
                dec = lzss_decompress(f.read())
            id_lookup = {}; idx_lookup = {}; idx_to_id = {}; id_to_idx = {}
            for i in range(600):
                off = i * 64
                if off + 10 > len(dec): break
                item_id = struct.unpack_from('<h', dec, off)[0]
                name_id = struct.unpack_from('<h', dec, off + 4)[0]
                if name_id > 0 and name_id in self.tkt:
                    nm = self.tkt[name_id].split('\n')[0].strip()[:25]
                elif item_id > 0:
                    nm = f'物品#{item_id}'
                else:
                    continue
                if item_id > 0:
                    id_lookup[item_id] = nm
                    idx_to_id[i] = item_id
                    id_to_idx[item_id] = i
                idx_lookup[i] = nm
            return id_lookup, idx_lookup, idx_to_id, id_to_idx
        except Exception:
            return {}, {}, {}, {}

    def _reload(self):
        if not self.warpc_path: return
        self.status_var.set("加载中…"); self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
        try:
            self.records = load_warpc(self.warpc_path); self._dirty = False
            self.skill_names, self._skill_types = self._load_skill_names()
            self.item_names, self.item_idx_names, self._idx_to_id, self._id_to_idx = self._load_item_names()
            nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
            self.status_var.set(
                f"{len(self.records)} 角色 (1054字节/角色) | 有效 {nonempty} | TKT {len(self.tkt)} 条 | 物品 {len(self.item_names)} 技能 {len(self.skill_names)}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e)); self.records = []
        self._update_paths(); self._set_edit_enabled(True); self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children():
            if isinstance(c, ttk.Frame):
                self._set_ws(c, en)

    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, (ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
                w.state(['!disabled'] if en else ['disabled'])
        except: pass
        for c in w.winfo_children(): self._set_ws(c, en)

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno("未保存", "有未保存的修改, 确定退出?"):
                return
        self.root.destroy()

    def _update_paths(self):
        g, r = "#228B22", "#CC3333"
        def _f(lb, p, label=''):
            if not p: lb.config(text=f"({label}未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=f"{label}: {p}" if label else p, foreground=g)
        _f(self.lbl_warpc, self.warpc_path, 'WarPC')
        _f(self.lbl_tkt, self.tkt_path, 'TKT')
        tks_dir = os.path.dirname(self.warpc_path) if self.warpc_path else ''
        it_path = os.path.join(tks_dir, 'TKItem.dat') if tks_dir else ''
        sk_path = os.path.join(tks_dir, 'TKSkill.dat') if tks_dir else ''
        _f(self.lbl_item, it_path if os.path.exists(it_path) else None, 'TKItem')
        _f(self.lbl_skill, sk_path if os.path.exists(sk_path) else None, 'TKSkill')

    # ----------- 筛选/列表 -----------

    def _char_name(self, rec):
        nid = rec['fields'][0]
        if nid > 0 and nid in self.tkt:
            return self.tkt[nid].split('\n')[0].strip()[:20]
        if nid < 0 and -nid in self.tkt:
            return self.tkt[-nid].split('\n')[0].strip()[:20]
        return f"#{nid}" if nid else f"(空-#{rec['index']})"

    def _apply_filter(self):
        q = self.sv.get().strip().lower(); self.filtered_indices = []
        for rec in self.records:
            if q:
                nm = self._char_name(rec)
                search_text = f"{rec['index']} {nm} {rec['fields'][2]} {rec['fields'][3]}".lower()
                if q not in search_text:
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records if any(v != 0 for v in r['fields']))
        msg = f"显示 {len(self.filtered_indices)}/{WARPC_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set(""); self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            f = r['fields']
            nm = self._char_name(r)
            hp_str = f"{f[5]}/{f[8]}" if f[5] or f[8] else ""
            mp_str = f"{f[6]}/{f[10]}" if f[6] or f[10] else ""
            role_str = '我方' if f[3] == -1 else ('敌方' if f[3] == 0 else str(f[3]))
            self.tree.insert('', 'end',
                             values=(r['index'], nm, f[2], role_str, hp_str, mp_str))

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'name':
            self.filtered_indices.sort(key=lambda i: self._char_name(self.records[i]).lower(), reverse=rev)
        elif col in ('level', 'role'):
            self.filtered_indices.sort(key=lambda i: self.records[i]['fields'][{'level':2,'role':3}[col]], reverse=rev)
        else:
            self.filtered_indices.sort(reverse=rev)
        self._sort_reverse = not rev; self._refresh_table()

    # ----------- 编辑 -----------

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        f = rec['fields']
        nm = self._char_name(rec)

        self.lbl_rec_idx.config(text=(
            f"角色 #{rec['index']}    {nm}    "
            f"等级={f[2]}  身份={'我方' if f[3]==-1 else ('敌方' if f[3]==0 else str(f[3]))}    "
            f"HP={f[5]}/{f[8]}  MP={f[6]}/{f[10]}"
        ))

        # Populate role combobox
        role_val = f[3]
        if 'role' in self._edit_extras:
            cb = self._edit_extras['role']
            for i, item in enumerate(cb['values']):
                if item.startswith(f'{role_val}-'):
                    cb.current(i); break

        # Populate all known fields
        all_named_fields = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS +
                           RUNTIME_STATE_FIELDS + EQUIP_FIELDS + EQUIP_SKILL_FIELDS +
                           STATUS_FIELDS + SKILL_EFF_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)
        for fn, fo, _, _ in all_named_fields:
            sv = str(f[fo // 2])
            if fn in self._edit_vars:
                self._edit_vars[fn].set(sv)

        # Unverified ranges
        for _, off, cnt, _ in UNVERIFIED_RANGES:
            for j in range(cnt):
                bo = off + j*2
                fn = f"field_{bo//2}"
                if fn in self._edit_vars:
                    self._edit_vars[fn].set(str(f[bo // 2]))

        # Resolve skill names for equip skill fields
        for fn, fo, _, _ in EQUIP_SKILL_FIELDS:
            sid = f[fo // 2]
            if fn in self._edit_extras:
                if sid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'skill_names') and sid in self.skill_names:
                    self._edit_extras[fn].config(text=self.skill_names[sid])
                else:
                    self._edit_extras[fn].config(text=f'技能#{sid}')

        # Resolve item names for equip_idx fields
        for fn, fo, _, _ in EQUIP_FIELDS[:4]:
            idx = f[fo // 2]
            if fn in self._edit_extras:
                if idx == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'item_idx_names') and idx in self.item_idx_names:
                    self._edit_extras[fn].config(text=self.item_idx_names[idx])
                else:
                    self._edit_extras[fn].config(text=f'物品#{idx}')

        # Resolve item names for drop item fields
        for fn, fo, _, _ in DROP_ITEM_FIELDS:
            iid = f[fo // 2]
            if fn in self._edit_extras:
                if iid == 0:
                    self._edit_extras[fn].config(text='(无)')
                elif hasattr(self, 'item_names') and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Resolve item names for equip_id fields
        for fn, fo, _, _ in EQUIP_FIELDS[4:]:
            iid = f[fo // 2]
            if fn in self._edit_extras:
                if iid == -1:
                    self._edit_extras[fn].config(text='(未装备)')
                elif hasattr(self, 'item_names') and iid in self.item_names:
                    self._edit_extras[fn].config(text=self.item_names[iid])
                else:
                    self._edit_extras[fn].config(text=f'物品#{iid}')

        # Additional unverified on tab1 (field [27]-[30])
        for j in range(4):
            bo = 54 + j*2
            fn = f"field_{bo//2}"
            if fn in self._edit_vars:
                self._edit_vars[fn].set(str(f[bo // 2]))
        # field[31]
        if "field_31" in self._edit_vars:
            self._edit_vars["field_31"].set(str(f[31]))

        # Tab 3: all raw fields
        for j in range(WARPC_FIELD_COUNT):
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                self._edit_vars[fn].set(str(f[j]))

    # ----------- 弹窗 -----------

    def _center_dialog(self, dlg, w, h):
        dlg.withdraw(); dlg.geometry(f'{w}x{h}'); dlg.update_idletasks()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        x = rx + (rw - w) // 2; y = ry + (rh - h) // 2
        dlg.geometry(f'+{x}+{y}'); dlg.deiconify()

    def _pick_skill(self, fn):
        """弹出技能选择对话框 — 加载 TKSkill.dat 显示技能名称"""
        if not self.records: return
        dlg = tk.Toplevel(self.root); dlg.title('选择技能')
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 550, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)

        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text='搜索:').pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)

        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree = ttk.Treeview(lf2, columns=('index', 'type', 'name'),
                            show='headings', selectmode='browse', height=20)
        tree.heading('index', text='技能#'); tree.column('index', width=55, anchor='center')
        tree.heading('type', text='类型'); tree.column('type', width=55, anchor='center')
        tree.heading('name', text='技能名称'); tree.column('name', width=400, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        type_names = {0: '指令', 1: '主动', 2: '被动', 3: '移动'}
        items = [(i, type_names.get(self._skill_types.get(i, -1), '?'),
                  self.skill_names.get(i, f'技能#{i}'))
                 for i in sorted(self.skill_names.keys())]

        def _refresh(q=''):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for idx, tp, nm in items:
                if ql and ql not in f'{idx} {tp} {nm}'.lower(): continue
                iid = tree.insert('', 'end', values=(idx, tp, nm))
                if idx == cur_val: tree.selection_set(iid); tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))

        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                sk_name = self.skill_names.get(int(v[0]), '')
                if fn in self._edit_extras:
                    self._edit_extras[fn].config(text=sk_name)
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text='清空', command=lambda: [
            self._edit_vars[fn].set('-1'),
            self._edit_extras[fn].config(text='(未装备)') if fn in self._edit_extras else None,
            dlg.destroy()
        ]).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text='确定', command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _pick_item(self, fn):
        """弹出物品选择对话框 — 装备索引(按TKItem下标)或装备ID"""
        if not self.records: return
        is_idx = fn.startswith('equip_idx')
        dlg = tk.Toplevel(self.root); dlg.title('选择物品')
        dlg.transient(self.root); dlg.grab_set()
        self._center_dialog(dlg, 550, 550)
        cur_val = int(self._edit_vars[fn].get() or 0)

        sf = ttk.Frame(dlg, padding=5); sf.pack(fill=tk.X)
        ttk.Label(sf, text='搜索:').pack(side=tk.LEFT)
        qv = tk.StringVar()
        ttk.Entry(sf, textvariable=qv, width=30, font=FONT).pack(side=tk.LEFT, padx=5)

        lf2 = ttk.Frame(dlg); lf2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        id_label = '物品#' if is_idx else '物品ID'
        tree = ttk.Treeview(lf2, columns=('key', 'name'),
                            show='headings', selectmode='browse', height=20)
        tree.heading('key', text=id_label); tree.column('key', width=80, anchor='center')
        tree.heading('name', text='物品名称'); tree.column('name', width=430, anchor='w')
        vsb = ttk.Scrollbar(lf2, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        lookup = self.item_idx_names if is_idx else self.item_names
        items = sorted(lookup.items(), key=lambda x: x[0])

        def _refresh(q=''):
            tree.delete(*tree.get_children())
            ql = q.strip().lower()
            for key_val, nm in items:
                if ql and ql not in f'{key_val} {nm}'.lower(): continue
                iid = tree.insert('', 'end', values=(key_val, nm))
                if key_val == cur_val: tree.selection_set(iid); tree.see(iid)
        _refresh()
        qv.trace_add('write', lambda *a: _refresh(qv.get()))

        def _sync_pair(key_val, nm):
            """双向同步: equip_idx ↔ equip_id"""
            slot = fn[-1]  # '0','1','2','3'
            if is_idx:
                pair_fn = f'equip_id{slot}'
                pair_val = self._idx_to_id.get(key_val, 0)
            else:
                pair_fn = f'equip_idx{slot}'
                pair_val = self._id_to_idx.get(key_val, -1)
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].set(str(pair_val))
            if pair_fn in self._edit_extras:
                if pair_val == -1:
                    self._edit_extras[pair_fn].config(text='(未装备)')
                elif is_idx:
                    self._edit_extras[pair_fn].config(
                        text=self.item_names.get(pair_val, f'物品#{pair_val}'))
                else:
                    self._edit_extras[pair_fn].config(
                        text=self.item_idx_names.get(pair_val, f'物品#{pair_val}'))

        def _sel():
            sel = tree.selection()
            if sel:
                v = tree.item(sel[0])['values']
                self._edit_vars[fn].set(str(v[0]))
                if fn in self._edit_extras:
                    self._edit_extras[fn].config(text=v[1] if v[1] else '')
                _sync_pair(v[0], v[1])
                dlg.destroy()
        tree.bind('<Double-1>', lambda e: _sel())
        clear_val = '-1' if is_idx else '0'
        clear_text = '(未装备)' if is_idx else ''
        def _clear():
            self._edit_vars[fn].set(clear_val)
            if fn in self._edit_extras:
                self._edit_extras[fn].config(text=clear_text)
            # also clear paired field
            slot = fn[-1]
            if is_idx:
                pair_fn = f'equip_id{slot}'
            else:
                pair_fn = f'equip_idx{slot}'
            if pair_fn in self._edit_vars:
                self._edit_vars[pair_fn].set('0' if is_idx else '-1')
            if pair_fn in self._edit_extras:
                self._edit_extras[pair_fn].config(text='' if is_idx else '(未装备)')
            dlg.destroy()
        bf = ttk.Frame(dlg, padding=5); bf.pack(fill=tk.X)
        ttk.Button(bf, text='清空', command=_clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text='确定', command=_sel).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    # ----------- 编辑应用 -----------

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        f = rec['fields']

        # Apply role combobox
        if 'role' in self._edit_extras:
            sv = self._edit_extras['role'].get()
            f[3] = int(sv.split('-', 1)[0]) if '-' in sv else int(sv)

        # Apply named fields
        all_named_fields = (IDENTITY_FIELDS + HPMP_FIELDS + STAT_FIELDS +
                           RUNTIME_STATE_FIELDS + EQUIP_FIELDS + EQUIP_SKILL_FIELDS +
                           STATUS_FIELDS + SKILL_EFF_FIELDS + GROWTH_FIELDS + BATTLE_REWARD_FIELDS + DROP_ITEM_FIELDS)
        for fn, fo, _, _ in all_named_fields:
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    f[fo // 2] = v
                except ValueError:
                    pass

        # Apply unverified
        for _, off, cnt, _ in UNVERIFIED_RANGES:
            for j in range(cnt):
                bo = off + j*2
                fn = f"field_{bo//2}"
                if fn in self._edit_vars:
                    try:
                        f[bo // 2] = int(self._edit_vars[fn].get())
                    except ValueError:
                        pass

        for j in range(4):
            fn = f"field_{(54+j*2)//2}"
            if fn in self._edit_vars:
                try: f[(54+j*2)//2] = int(self._edit_vars[fn].get())
                except ValueError: pass
        # field[31]
        if "field_31" in self._edit_vars:
            try: f[31] = int(self._edit_vars["field_31"].get())
            except ValueError: pass

        # Apply all raw fields from tab3
        for j in range(WARPC_FIELD_COUNT):
            fn = f"raw_{j}"
            if fn in self._edit_vars:
                try:
                    v = int(self._edit_vars[fn].get())
                    if v > 32767: v = 32767
                    if v < -32768: v = -32768
                    f[j] = v
                except ValueError:
                    pass

        self._dirty = True; self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child); self.tree.see(child); break
        self.status_var.set(f"角色 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.warpc_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据"); return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 个角色到:\n{self.warpc_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.warpc_path, 'rb') as s:
                with open(self.warpc_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.set("正在保存…"); self.root.update()
            save_warpc(self.warpc_path, self.records); self._dirty = False
            self.status_var.set(f"已保存 → {self.warpc_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.warpc_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['索引', '名称', '等级', '身份', '类型', 'HP当前', 'HP上限', 'MP当前', 'MP上限']
            for name in STAT_NAMES:
                hdr += [f'{name}(基础)', f'{name}(当前)']
            hdr += [f'field[{i}]' for i in range(27, 527)]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                fl = rec['fields']
                row = [str(rec['index']), self._char_name(rec),
                       str(fl[2]), str(fl[3]), str(fl[4]),
                       str(fl[5]), str(fl[8]), str(fl[6]), str(fl[10])]
                for i, bo in enumerate(STAT_BASE_OFFSETS):
                    row += [str(fl[bo//2]), str(fl[bo//2 + 1])]
                row += [str(fl[i]) for i in range(27, 527)]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = ["WarPC.dat 字段映射 (反编译依据):", ""]
        lines.append(f"【记录布局】{WARPC_CNT} 角色 × {WARPC_REC} 字节 = {WARPC_DECOMPRESSED} 字节")
        lines.append(f"  {WARPC_FIELD_COUNT} × int16 (小端序) 共 {WARPC_REC} 字节/角色")
        lines.append("")
        lines.append("【已验证字段 (反编译直接引用)】")
        for title, fields in [
            ("基本信息", IDENTITY_FIELDS), ("HP/MP", HPMP_FIELDS),
            ("八属性 (攻击/防御/命中/闪避/速度/幸运/悟性/移动)", STAT_FIELDS),
            ("运行时状态 [32]-[42] (语义未验证)", RUNTIME_STATE_FIELDS),
            ("装备索引", EQUIP_FIELDS[:4]), ("装备ID", EQUIP_FIELDS[4:]),
            ("装备技能 [82]-[87] (6字段; Maker验证: 周倉)", EQUIP_SKILL_FIELDS),
            ("状态掩码", STATUS_FIELDS),
            ("技能效果槽(16个)", SKILL_EFF_FIELDS),
            ("战后奖励 [268]-[269] (实测: 盜賊嘍嘍JP=2 Gold基数=20→Lv3得40)", BATTLE_REWARD_FIELDS),
        ]:
            lines.append(f"【{title}】")
            for fn, fo, fl, cmt in fields:
                lines.append(f"  [{fo//2:3d}] bo={fo:4d} {fl:<14s} {cmt}")
        lines.append("")
        lines.append("【未验证字段范围】")
        for title, off, cnt, cmt in UNVERIFIED_RANGES:
            lines.append(f"  [{off//2}-{(off+cnt*2)//2-1}] {title} ({cmt})")
        lines.append("")
        lines.append("【尾部未分析区域】")
        lines.append(f"  [{TAIL_START}-{TAIL_END-1}] (426 字段) — 无反编译引用")
        lines.append("")
        lines.append("【核心反编译函数】")
        lines.append("  sub_42234C  装备/技能/属性应用 (字段 [5-10]/[11-26]/[32-42]/[67-72]/[86-87])")
        lines.append("  sub_41E40C  物品使用效果")
        lines.append("  sub_422768  角色初始化")
        lines.append("  sub_422BBC  被动技能效果计算")
        lines.append("  sub_4173F8  装备ID→索引匹配 ([69-72]←[73-76])")

        dlg = tk.Toplevel(self.root); dlg.title("字段参考 v1.0 (逆向)")
        dlg.geometry("680x600"); dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines)); tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "WarPC.dat 可视化编辑器 v1.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "143 角色 × 1054 字节 (527×int16)\n\n"
            "逆向依据:\n"
            "  sub_42234C  装备/技能/属性应用\n"
            "  sub_41E40C  物品使用效果\n"
            "  sub_422BBC  被动技能效果计算\n"
            "  sub_4173F8  装备索引匹配\n"
            "  sub_45343C  DAT 统一加载\n"
            "  sub_452B14  LZSS 解压引擎"
        )


def main():
    root = tk.Tk(); WarpcEditor(root); root.mainloop()

if __name__ == '__main__':
    main()
