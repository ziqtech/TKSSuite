#!/usr/bin/env python3
"""
TKKon.dat 可视化编辑器 v3.0
=============================================================
逆向依据 (2026-05 v3.0 字段语义修正):
  - sub_45343C:     DAT 文件统一加载 (LZSS 解压, 40字节/条, 650条)
  - sub_452B14:     LZSS 解压引擎 (4096窗口, 0x20填充, 起始位4078)
  - sub_4173F8:     TKKon 加载入口 → &unk_9D0698, 26000
  - Maker.exe sub_4027FF: 校验解压后大小 26000 = 40 × 650

v3.0 语义修正 (基于 sub_43D53C/43D8B0/43E980/4458B0):
  - field[0-2] 不是 TKT 文本引用! 旧版通过TKT查表得到场景名称是虚假关联
  - field[0] = 执行模式 (高字节=攻击距离, 低字节=范围形状)
  - field[1] = 目标参数 (高字节=扩展范围, 低字节=扩展模式)
  - field[2] = 目标过滤 (高字节=目标格子类型[全部/仅角色/仅空地], 低字节=阵营匹配[对立/同阵营/任意])
  - field[4] = 生命伤害 (-1=ATK, 0=无, 1~999=固定, 1001~1999=HP%, 2001~2999=ATK+N, 3001+=ATK×倍率)
  - field[5] = 内力伤害 (同编码, >1000=内力%)    field[6] = 附加命中 (加算值)
  - field[8] = 生命回复 (同编码, >1000=生命%回复, 仅生命<25%时触发)
  - field[9] = 内力回复 (同编码, >1000=内力%回复, 仅内力<25%时触发)
  - field[19] = 执行标志 (bit0=隐藏施法者, bit2=物理/法术, 高字节未使用)

字段布局 (20 × int16, 40字节/条):
  [0]  exec_mode         — 执行模式/攻击范围 (高=距离, 低=形状)
  [1]  target_param      — 目标选择参数
  [2]  target_filter     — 目标过滤 (格子类型 + 阵营匹配)
  [3]  tkact_id          — TKAct.dat 动画索引 (0..649)
  [4]  hp_damage       — 生命伤害
  [5]  mp_damage         — 内力生命伤害
  [6]  accuracy          — 附加命中值
  [7]  extra_damage      — 附加伤害值
  [8]  hp_restore        — 生命回复基础值 (可能=对话ID→TKT)
  [9]  mp_restore        — 内力回复基础值 (可能=对话ID→TKT)
  [10] inflict_status_lo — 导致状态 1-16  (位掩码)
  [11] inflict_status_hi — 导致状态 17-32 (位掩码)
  [12] remove_status_lo  — 解除状态 1-16  (位掩码)
  [13] remove_status_hi  — 解除状态 17-32 (位掩码)
  [14] timing_mod        — 时序修正 (行动顺序增减)
  [15] unused15          — 未使用 (始终为0)
  [16] unused16          — 未使用 (始终为0)
  [17] unused17          — 未使用 (始终为0)
  [18] unused18          — 未使用 (始终为0)
  [19] exec_flags        — 执行标志 (bit0=施法者可见, bit2=物理伤害, 高字节未使用)

用法:
  python kon_editor.py
"""

import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ============================================================
# LZSS 编解码 (sub_452B14)
# ============================================================

def lzss_decompress(data):
    """LZSS 解压 — sub_452B14: 4096窗口, 0x20填充, 起始位4078"""
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
    """LZSS 压缩 — sub_452B14 逆向: 4096窗口, 0x20填充, 起始位4078"""
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
    ts = struct.unpack_from('<I', raw, 0)[0]
    cnt = struct.unpack_from('<I', raw, 4)[0]
    enc = raw[8:8 + ts]
    dec = bytes([b ^ 0xFF for b in enc])
    idsz, ofsz = cnt * 4, cnt * 4
    lookup = {}
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
# 常量 — 修正为 40 字节/条 × 650 条
# ============================================================

KON_REC = 40       # 20 × int16
KON_CNT = 650      # 26000 / 40
KON_FIELD_COUNT = 20
KON_DECOMPRESSED = 26000

# 31 种状态 (bit 0..30; 对应 TksModify.dll Maker UI 状态列表)
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]

FONT = ('Microsoft YaHei UI', 9)
FONT_S = ('Microsoft YaHei UI', 8)
W_INPUT = 12

# ============================================================
# 字段定义 (key, byte_offset, ui_label, comment)
# ============================================================

# exec_flags 源码验证 (sub_4434BC:355-391, sub_43E980:192):
#   0 (bit0=0，bit2=0): 隐藏施法者待机动画, 技能动画包含角色动作 — 法术攻击, 例 #7 治疗术
#   1 (bit0=1，bit2=0): 保持施法者待机动画, 技能动画仅特效 — Buff/自身技能, 例 #562 御风行
#   3 (bit0=1，bit1=1): 保持施法者待机动画, 物品使用逻辑 — 例 #551 霹雳车 #550 麒麟角
#   4 (bit0=0, bit2=1): 隐藏待机, 物理伤害公式 — 普通攻击, 例 #456 盗贼普攻

KON_FIELDS = [
    ("exec_mode",        0,  "执行模式",      "高字节=攻击距离(负=自身, 0=单格, 1-3=近战, 6+=远程); 低字节=范围开关(0=启用菱形, 1=禁用) — sub_43D53C:45-47"),
    ("target_param",     2,  "目标参数",      "高字节=效果面积(0=单体, 1+=菱形层数, -1/FF=全场, -2/FE=全场排除自身); 低字节=扩散开关(0=启用, 1=禁用) — sub_43D8B0:56-146"),
    ("target_filter",    4,  "目标过滤",      "高字节=目标格子(0=全部, 1=仅角色, 2=仅空地[召唤]); 低字节=阵营匹配(0=对立/敌方, 1=同阵营/友方, 2=任意/不分敌我) — sub_43D53C:127-155, sub_43D8B0:v17"),
    ("tkact_id",         6,  "TKAct动画索引",     "TKAct.dat 条目索引 (0..649, -1=无) — sub_4434BC: word_9D069E[20*i]"),
    ("hp_damage",      8,  "生命伤害",    "(-1)=ATK; (0)=无; (1~999)=固定; (1001~1999)=目标生命%(val-1000); (2001~2999)=ATK+(val-2000); (3001+)=ATK×(1+(val-3000)/100) — sub_43E980:77-161,273-276"),
    ("mp_damage",        10, "内力伤害",      "(0)=无; (1~999)=固定内力伤; (1001~1999)=目标内力%(val-1000) — sub_43E980:392-477, v38编码"),
    ("accuracy",         12, "附加命中",      "命中率加算值 (与目标闪避联合, L179: v35=accuracy+unit_accuracy) — sub_43E980:179"),
    ("extra_damage",     14, "附加伤害",      "附加伤害值 (极少使用) — sub_43E980 未直接使用此字段"),
    ("hp_restore",       16, "生命回复",       "(0)=无; (1~999)=固定回复; (1001~1999)=最大生命%(val-1000); 仅生命<25%时50%触发 — sub_43E980:479-515"),
    ("mp_restore",       18, "内力回复",       "(0)=无; (1~999)=固定回复; (1001~1999)=最大内力%(val-1000); 仅内力<25%时50%触发 — sub_43E980:517-553"),
    ("inflict_status_lo", 20, "导致状态1-16",  "施加状态位掩码低16位 (bit0=状态1,…,bit15=状态16; 84条使用)"),
    ("inflict_status_hi", 22, "导致状态17-32", "施加状态位掩码高16位 (bit0=状态17,…,bit15=状态32; 107条使用)"),
    ("remove_status_lo",  24, "解除状态1-16",  "移除状态位掩码低16位 (bit0=状态1,…,bit15=状态16; 26条使用)"),
    ("remove_status_hi",  26, "解除状态17-32", "移除状态位掩码高16位 (bit0=状态17,…,bit15=状态32; 62条使用)"),
    ("timing_mod",       28, "时序修正",      "行动顺序修正值 (负=加速/提前, 正=减速/延后; 7条使用) — sub_432314 + 4400DC.asm:4429EF"),
    ("unused15",         30, "未使用15",      "● 始终为0 (650条中0条非零)"),
    ("unused16",         32, "未使用16",      "● 始终为0 (650条中0条非零)"),
    ("unused17",         34, "未使用17",      "● 始终为0 (650条中0条非零)"),
    ("unused18",         36, "未使用18",      "● 始终为0 (650条中0条非零)"),
    ("exec_flags",       38, "执行标志",      "0=法术(隐藏待机), 1=Buff(保持待机), 3=物品(保持待机), 4=物理(隐藏待机); bit2=伤害类型 — sub_4434BC:355, sub_43E980:193"),
]

ACTIVE_FIELDS = [f for f in KON_FIELDS if not f[0].startswith('unused')]

# ============================================================
# 数据加载/保存
# ============================================================

def resolve_kon_val(field_name, val, tkt):
    """解析 int16 值 → 特殊标记 (已弃用TKT查表, 仅返回空)"""
    return ""

def load_tkkon_names(csv_path):
    """加载 TKKon ID→名称 配置表"""
    names = {}
    if not csv_path or not os.path.exists(csv_path):
        return names
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = __import__('csv').reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2 and row[0].strip().isdigit():
                idx = int(row[0])
                name = row[1].strip()
                if name:
                    names[idx] = name
    return names

def kon_record_name(rec, tkt, names=None):
    """生成记录的可读名称 — 优先使用配置表名称，其次动画索引"""
    idx = rec['index']
    # 优先使用配置表名称
    if names and idx in names and names[idx]:
        return names[idx]
    # 回退：动画索引+参数描述
    cid = rec.get('tkact_id', 0)
    parts = []
    em = rec.get('exec_mode', 0)
    tp = rec.get('target_param', 0)
    if em < 0:
        parts.append("自身")
    elif em != 0:
        rh = (em >> 8) & 0xFF
        if rh > 0:
            parts.append(f"距{rh}")
    tp_hi = (tp >> 8) & 0xFF
    if tp_hi > 0:
        parts.append(f"面{tp_hi}")
    desc = " ".join(parts) if parts else ""
    if cid >= 0:
        return f"动画#{cid} {desc}".strip()
    return f"空槽-#{idx}"

def describe_exec_mode(val):
    """解析 exec_mode → 可读描述 (高字节=攻击距离, 低字节=范围开关)"""
    if val < 0:
        return "自身目标"
    hi = (val >> 8) & 0xFF
    lo = val & 0xFF
    if hi == 0 and lo == 0:
        return "单格"
    range_text = "" if lo == 0 else "[范围禁用]"
    parts = []
    if hi > 0:
        parts.append(f"距离={hi}格")
    parts.append(range_text)
    return "  ".join(parts)

def describe_target_param(val):
    """解析 target_param → 可读描述 (高字节=攻击面积, 低字节=扩散开关)

    逆向依据 sub_43D8B0:56,65,78,142-146:
      v15 (高字节) >= 0: 正常模式, v15 为菱形扩散层数
      v15 = -1 (0xFF): 全场目标, 所有格均为候选 (L144)
      v15 = -2 (0xFE): 全场目标, 但排除中心格 (L145-146 中心置-1)
    """
    if val < 0:
        hi = (val >> 8) & 0xFF
        if hi == 255:  # -1
            return "全场目标"
        elif hi == 254:  # -2
            return "全场(排除自身)"
        return f"特殊({val})"
    hi = (val >> 8) & 0xFF
    lo = val & 0xFF
    if hi == 0 and lo == 0:
        return "无扩散(单体)"
    spread_text = "" if lo == 0 else "[扩散禁用]"
    parts = []
    if hi > 0:
        parts.append(f"面积={hi}格")
    parts.append(spread_text)
    return "  ".join(parts)

def describe_target_filter(val):
    """解析 target_filter → 可读描述 (高=目标格子类型, 低=阵营匹配)

    逆向依据 sub_43D53C (byte_9D6C2D=HI, byte_9D6C2C=LO):
      *v6 < 0 (空地): HI ∈ {0,2} 时标记
      *v6 >= 0 (活人): HI ∈ {0,1} 时按 LO 做阵营 switch
    sub_43D8B0 v17=byte_9D6C2C:
      LO=0 对立阵营, LO=1 同阵营, LO=2 任意(含特殊状态)
    """
    lo = val & 0xFF
    hi = (val >> 8) & 0xFF
    target_map = {0: "全部", 1: "仅角色", 2: "仅空地"}
    faction_map = {0: "对立阵营", 1: "同阵营", 2: "任意阵营"}
    t_text = target_map.get(hi, f"目标{hi}")
    f_text = faction_map.get(lo, f"阵营{lo}")
    return f"{t_text}  {f_text}"

def describe_exec_flags(val):
    """解析 exec_flags → 位掩码描述"""
    lo = val & 0xFF
    parts = []
    parts.append("显示待机" if (lo & 1) else "隐藏待机")
    if lo & 2: parts.append("物品")
    parts.append("物理" if (lo & 4) else "法术")
    return "  ".join(parts)

def describe_hp_damage(val):
    """解析 hp_damage → 可读描述 (sub_43E980:77-161,273-276)

    编码层级:
      -1      → 单位ATK + 技能特殊修正 (sub_43E980:77-145 各skill_id分支)
       0      → 无伤害 (sub_43E980:74 跳过)
     1~999    → 固定伤害值
    1001~1999 → 目标最大HP × (val-1000)%  (v37 = val-1000, L273-274)
    2001~2999 → ATK + (val-2000)          (L156)
    3001+     → ATK × (1 + (val-3000)/100) (L161)
    """
    if val == -1:
        return "单位攻击力"
    if val == 0:
        return "无伤害"
    if 1 <= val <= 999:
        return f"固定伤害={val}"
    if 1001 <= val <= 1999:
        return f"生命%伤害={val - 1000}%"
    if 2001 <= val <= 2999:
        return f"攻击力+{val - 2000}"
    if val >= 3001:
        return f"攻击力×{100 + val - 3000}%"
    return f"特殊({val})"

def describe_resource_val(val, resource_name):
    """解析 mp_damage/hp_restore/mp_restore → 可读描述 (sub_43E980:392-553)

    共享编码:
       0      → 无效果
     1~999    → 固定值
    1001~1999 → 最大值 × (val-1000)%
    """
    if val == 0:
        return f"无{resource_name}"
    if 1 <= val <= 999:
        return f"固定{resource_name}={val}"
    if 1001 <= val <= 1999:
        return f"{resource_name}%={val - 1000}%"
    return f"{resource_name}=({val})"

def load_kon(fp):
    with open(fp, 'rb') as f: raw = f.read()
    dec = lzss_decompress(raw)
    # 兜底: LZSS 解压大小不匹配预期时, 检查是否已是未压缩 raw 数据
    if len(dec) != KON_DECOMPRESSED and len(raw) == KON_DECOMPRESSED:
        dec = raw
    if len(dec) != KON_DECOMPRESSED:
        raise ValueError(f"解压后大小 {len(dec)} 不等于预期 26000 (Maker.exe sub_4027FF)")
    recs = []
    for i in range(KON_CNT):
        off = i * KON_REC
        vals = struct.unpack_from('<' + 'h' * KON_FIELD_COUNT, dec, off)
        rec = {'index': i}
        for fi, (fn, _, _, _) in enumerate(KON_FIELDS):
            rec[fn] = vals[fi]
        recs.append(rec)
    return recs

def save_kon(fp, recs):
    buf = bytearray(KON_CNT * KON_REC)
    for rec in recs[:KON_CNT]:
        i = rec['index']
        off = i * KON_REC
        vals = [rec[fn] for fn, _, _, _ in KON_FIELDS]
        struct.pack_into('<' + 'h' * KON_FIELD_COUNT, buf, off, *vals)
    compressed = lzss_compress(bytes(buf))
    if lzss_decompress(compressed) != bytes(buf):
        raise RuntimeError("压缩回写验证失败!")
    with open(fp, 'wb') as f: f.write(compressed)
    return True

# ============================================================
# GUI
# ============================================================

class KonEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TKKon.dat 可视化编辑器 v3.0")
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            self.root.iconbitmap(default=ico)
        self.root.geometry("1320x820")
        self.root.minsize(1050, 650)
        self.kon_path = self.tkt_path = None
        self.records = []
        self.tkt = {}
        self.names = {}
        self.filtered_indices = []
        self._dirty = False
        self._edit_split = {}  # split spinboxes / bitmask checkboxes
        self._build_ui()
        self._set_edit_enabled(False)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1320) // 2
        y = (sh - 820) // 2
        self.root.geometry(f'1320x820+{x}+{y}')

    # ----------- UI 构建 -----------

    def _build_ui(self):
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="加载 TKS 目录…", command=self._load_tks_dir, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="保存", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="导出 CSV…", command=self._export_csv)
        fm.add_separator()
        fm.add_command(label="退出", command=self.root.quit)
        mb.add_cascade(label="文件", menu=fm)
        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="新建条目", command=self._new_record, accelerator="Ctrl+N")
        em.add_command(label="复制当前记录", command=self._copy_record)
        em.add_command(label="清空当前记录", command=self._clear_current)
        mb.add_cascade(label="编辑", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="字段参考 (逆向来源)", command=self._show_field_ref)
        hm.add_command(label="关于", command=self._show_about)
        mb.add_cascade(label="帮助", menu=hm)
        self.root.bind('<Control-o>', lambda e: self._load_tks_dir())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-n>', lambda e: self._new_record())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Toolbar
        tb = ttk.Frame(self.root)
        tb.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(tb, text="搜索:").pack(side=tk.LEFT)
        self.sv = tk.StringVar()
        e_s = ttk.Entry(tb, textvariable=self.sv, width=22)
        e_s.pack(side=tk.LEFT, padx=2)
        e_s.bind('<Return>', lambda e: self._apply_filter())
        ttk.Button(tb, text="搜索", command=self._apply_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text="清除", command=self._clear_filter, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        # Filter toggle for empty records
        self.show_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="显示空槽", variable=self.show_empty,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tb, text="重新加载", command=self._reload).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="请通过 文件 → 加载 TKS 目录 打开数据")
        ttk.Label(tb, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT, padx=10)

        # Main PanedWindow
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: TreeView
        lf = ttk.Frame(paned)
        paned.add(lf, weight=1)
        cols = ('index', 'tkact_id', 'atk_range', 'tkt_name', 'atk_area', 'hp_damage', 'target_f', 'exec_f')
        self.tree = ttk.Treeview(lf, columns=cols, show='headings', selectmode='browse')
        cc = [
            ('index', '序号', 38),
            ('tkact_id', '动画', 42),
            ('atk_range', '距离', 42),
            ('tkt_name', '名称', 95),
            ('atk_area', '范围', 52),
            ('hp_damage', '伤害', 55),
            ('target_f', '目标', 55),
            ('exec_f', '类型', 50),
        ]
        for cid, cn, cw in cc:
            self.tree.heading(cid, text=cn, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=cw, anchor='center' if cid != 'tkt_name' else 'w', minwidth=cw)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.tag_configure('active', foreground='#228B22')  # 有内容的条件
        self.tree.tag_configure('empty', foreground='#AAAAAA')    # 空记录
        self.tree.tag_configure('tkact_minus1', foreground='#2266CC')  # tkact_id=-1

        # Right: Edit panel
        rf = ttk.Frame(paned)
        paned.add(rf, weight=4)
        self.edit_frame = rf

        self.lbl_rec_idx = ttk.Label(rf, text="未选中", font=('', 11, 'bold'))
        self.lbl_rec_idx.pack(anchor=tk.W, pady=(0, 4), padx=4)

        # Scrollable edit area
        middle = ttk.Frame(rf)
        middle.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(middle)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(middle, orient=tk.VERTICAL)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        bf = ttk.Frame(left_col)
        bf.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
        ttk.Button(bf, text="应用修改", command=self._apply_edit, width=12).pack(side=tk.LEFT)
        ttk.Button(bf, text="重置为当前", command=self._reset_edit, width=12).pack(side=tk.LEFT, padx=2)

        canvas = tk.Canvas(left_col, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.edit_inner = ttk.Frame(canvas)
        self.edit_inner.columnconfigure(0, weight=1)
        self.edit_inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self._canvas_win = canvas.create_window((0, 0), window=self.edit_inner, anchor='nw')
        canvas.bind('<Configure>', lambda e: self.edit_inner.columnconfigure(0, minsize=e.width))
        canvas.configure(yscrollcommand=sb.set)
        self._bind_mousewheel(canvas)

        self._edit_vars = {}
        self._edit_extras = {}

        # Preview panel
        pv_lf = ttk.LabelFrame(self.edit_inner, text="动作预览", padding=4)
        pv_lf.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        for c in range(4): pv_lf.columnconfigure(c, weight=1)
        LBL_CLR = '#666'

        ttk.Label(pv_lf, text="名称:", font=FONT_S, foreground=LBL_CLR).grid(
            row=0, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_name = ttk.Label(pv_lf, text="(未选中)", foreground='#3366cc',
                                       font=FONT, wraplength=700, justify='left')
        self.preview_name.grid(row=0, column=1, columnspan=3, sticky='ew', pady=1)

        ttk.Label(pv_lf, text="详情:", font=FONT_S, foreground=LBL_CLR).grid(
            row=1, column=0, sticky='nw', padx=(2, 4), pady=1)
        self.preview_info = ttk.Label(pv_lf, text="", foreground='#228B22',
                                       font=FONT_S, wraplength=700, justify='left')
        self.preview_info.grid(row=1, column=1, columnspan=3, sticky='ew', pady=1)

        # Field groups — active fields only, skip unused
        self._build_field_group("战斗执行参数 (offset 0–6)", ACTIVE_FIELDS[:4], 1, 4)
        self._build_field_group("伤害/回复参数 (offset 8–18)", ACTIVE_FIELDS[4:10], 2, 5)
        self._build_field_group("状态位掩码 (offset 20–28)", ACTIVE_FIELDS[10:15], 3, 5)
        self._build_field_group("未使用 (offset 30–36) + 执行标志", KON_FIELDS[15:], 4, 5)

        # Bottom path bar
        pf = ttk.LabelFrame(self.root, text="当前加载")
        pf.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.lbl_kon = ttk.Label(pf, text="", foreground="gray")
        self.lbl_kon.pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Separator(pf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_tkt = ttk.Label(pf, text="", foreground="gray")
        self.lbl_tkt.pack(side=tk.LEFT, padx=10, pady=2)

    def _build_field_group(self, title, fields, row, cols):
        lf = ttk.LabelFrame(self.edit_inner, text=title, padding=4)
        lf.grid(row=row, column=0, sticky='ew', padx=2, pady=2)
        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X)
        for fi, (fn, fo, fl, cmt) in enumerate(fields):
            r, c = divmod(fi, cols)
            is_unused = fn.startswith('unused')
            self._build_field(grid, r, c, fn, fo, fl, W_INPUT, cmt, readonly=is_unused)

    def _build_field(self, parent, row, col, fn, fo, fl, fw, cmt, readonly=False):
        frm = ttk.Frame(parent)
        frm.grid(row=row, column=col, sticky='nw', padx=3, pady=2)
        lbl = ttk.Label(frm, text=fl, font=FONT_S)
        if readonly:
            lbl.configure(foreground='#AAA')
        lbl.pack(anchor=tk.W)
        self._bind_tooltip(lbl, f"[{fo:02d}] {cmt}")

        is_mask = 'status' in fn
        is_split = fn in ('exec_mode', 'target_param', 'target_filter')
        is_bitmask = fn == 'exec_flags'
        if is_bitmask:
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            v_bit0 = tk.BooleanVar()
            v_bit1 = tk.BooleanVar()
            v_bit2 = tk.BooleanVar()
            cb0 = ttk.Checkbutton(box, text="显示待机动画", variable=v_bit0)
            cb0.pack(side=tk.LEFT, padx=(0, 4))
            cb1 = ttk.Checkbutton(box, text="使用物品", variable=v_bit1)
            cb1.pack(side=tk.LEFT, padx=(0, 4))
            cb2 = ttk.Checkbutton(box, text="物理攻击", variable=v_bit2)
            cb2.pack(side=tk.LEFT)
            self._bind_tooltip(cb0, "勾选时显示人物待机动画（默认不勾选，大部分攻击动画中已包含人物形象）")
            self._bind_tooltip(cb1, "由使用物品触发的动画")
            self._bind_tooltip(cb2, "使用物理伤害公式（计入防御力）")
            self._edit_split[fn] = (v_bit0, v_bit1, v_bit2)
            if not readonly:
                self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#228B22',
                                                   font=FONT_S, wraplength=220)
                self._edit_extras[fn].pack(anchor=tk.W)
        elif is_split:
            # 高/低字节拆分编辑
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            is_toggle = fn in ('exec_mode', 'target_param')
            is_filter = fn == 'target_filter'
            if fn == 'exec_mode':
                hi_label, hi_from, hi_to = "距离", -1, 127
                lo_label = "范围"
            elif fn == 'target_param':
                hi_label, hi_from, hi_to = "面积", 0, 127
                lo_label = "扩散"
            else:  # target_filter
                hi_label = "格子"
                lo_label = "阵营"
            hi_var = tk.StringVar(value="0")
            lo_var = tk.StringVar(value="0")
            if is_filter:
                hi_combo = ttk.Combobox(box, textvariable=hi_var,
                                         values=["全部", "仅角色", "仅空地"],
                                         state='readonly', width=6, font=FONT)
                lo_combo = ttk.Combobox(box, textvariable=lo_var,
                                         values=["对立阵营", "同阵营", "任意阵营"],
                                         state='readonly', width=8, font=FONT)
                ttk.Label(box, text=hi_label, font=FONT_S).pack(side=tk.LEFT)
                hi_combo.pack(side=tk.LEFT, padx=1)
                ttk.Label(box, text=lo_label, font=FONT_S).pack(side=tk.LEFT, padx=(6, 1))
                lo_combo.pack(side=tk.LEFT, padx=1)
                self._edit_split[fn] = (hi_combo, lo_combo, hi_var, lo_var)
            else:
                hi_spin = ttk.Spinbox(box, textvariable=hi_var, from_=hi_from, to=hi_to, width=5, font=FONT)
                ttk.Label(box, text=hi_label, font=FONT_S).pack(side=tk.LEFT)
                hi_spin.pack(side=tk.LEFT, padx=1)
                ttk.Label(box, text=lo_label, font=FONT_S).pack(side=tk.LEFT, padx=(6, 1))
                lo_combo = ttk.Combobox(box, textvariable=lo_var, values=["启用", "禁用"],
                                         state='readonly', width=5, font=FONT)
                lo_combo.pack(side=tk.LEFT, padx=1)
                self._edit_split[fn] = (hi_spin, lo_combo, hi_var, lo_var)
            # extras 标签 (分解显示)
            if not readonly:
                self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#228B22',
                                                   font=FONT_S, wraplength=180)
                self._edit_extras[fn].pack(anchor=tk.W)
        elif is_mask:
            # 状态位掩码: 按钮 + 状态名标签
            inf = fn.startswith('inflict')
            btn_text = "选择导致状态…" if inf else "选择解除状态…"
            color = '#CC3333' if inf else '#3366cc'
            ttk.Button(frm, text=btn_text, width=fw + 6,
                       command=lambda f=fn: self._pick_status(f)).pack(fill=tk.X)
            self._edit_vars[fn] = tk.StringVar()
            extras_frame = ttk.Frame(frm)
            extras_frame.pack(anchor=tk.W, fill=tk.X)
            self._edit_extras[fn] = (extras_frame, ttk.Label(extras_frame, text="(无)",
                                       foreground=color, font=FONT_S, wraplength=180))
            self._edit_extras[fn][1].pack(anchor=tk.W)
        else:
            box = ttk.Frame(frm)
            box.pack(fill=tk.X)
            ev = tk.StringVar()
            self._edit_vars[fn] = ev
            ent = ttk.Entry(box, textvariable=ev, width=fw, font=FONT)
            if readonly:
                ent.configure(state='readonly', foreground='#AAA')
            ent.pack(side=tk.LEFT)
            # TKT 文本解析显示 (for non-unused fields)
            if not readonly:
                self._edit_extras[fn] = ttk.Label(frm, text="", foreground='#3366cc',
                                                   font=FONT_S, wraplength=180)
                self._edit_extras[fn].pack(anchor=tk.W)

    def _bind_tooltip(self, widget, text):
        tip = {'win': None}
        def _enter(e):
            if tip['win']:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            ttk.Label(w, text=text, background='#FFFFE0', relief='solid', borderwidth=1,
                      font=FONT_S, wraplength=420, padding=3).pack()
            tip['win'] = w
        def _leave(e):
            if tip['win']:
                tip['win'].destroy()
                tip['win'] = None
        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _bind_mousewheel(self, canvas):
        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _center_dialog(self, dlg, w, h):
        dlg.withdraw()
        dlg.geometry(f"{w}x{h}")
        dlg.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()

    # ----------- 弹窗: 状态 mask 多选 -----------
    def _pick_status(self, fn):
        inf = fn.startswith('inflict')
        title = "选择导致状态 (位掩码)" if inf else "选择解除状态 (位掩码)"
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_dialog(dlg, 320, 520)
        base = 0 if fn.endswith('_lo') else 16
        cur_mask = int(self._edit_vars[fn].get() or 0) & 0xFFFF
        vars_ = []
        wrap = ttk.Frame(dlg, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)
        for i in range(16):
            idx = base + i
            if idx >= len(STATUS_NAMES): break
            v = tk.BooleanVar(value=bool(cur_mask & (1 << i)))
            ttk.Checkbutton(wrap, text=f"{idx}. {STATUS_NAMES[idx]}",
                            variable=v).pack(anchor=tk.W, pady=1)
            vars_.append(v)
        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=8, pady=8)
        def _ok():
            m = 0
            for i, v in enumerate(vars_):
                if v.get(): m |= (1 << i)
            if m >= 0x8000: m -= 0x10000
            self._edit_vars[fn].set(str(m))
            self._update_status_label(fn, m & 0xFFFF)
            dlg.destroy()
        ttk.Button(bf, text="全选", command=lambda: [v.set(True) for v in vars_]).pack(side=tk.LEFT)
        ttk.Button(bf, text="全清", command=lambda: [v.set(False) for v in vars_]).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="确定", command=_ok).pack(side=tk.RIGHT, padx=2)
        dlg.wait_window()

    def _update_status_label(self, fn, mask):
        base = 0 if fn.endswith('_lo') else 16
        inf = fn.startswith('inflict')
        color = '#CC3333' if inf else '#3366cc'
        sel = []
        for i in range(16):
            if mask & (1 << i) and base + i < len(STATUS_NAMES):
                sel.append((base + i, STATUS_NAMES[base + i]))
        extras_frame, txt_lbl = self._edit_extras[fn]
        for w in extras_frame.winfo_children():
            if w != txt_lbl: w.destroy()
        if sel:
            txt_lbl.config(text="")
            txt_lbl.pack_forget()
            COLS = 3
            for si, (idx, nm) in enumerate(sel):
                row, col = divmod(si, COLS)
                cell = ttk.Frame(extras_frame)
                cell.grid(row=row, column=col, sticky='w', padx=(0, 6), pady=1)
                ttk.Label(cell, text=nm, foreground=color, font=FONT_S).pack(side=tk.LEFT)
        else:
            txt_lbl.config(text="(无)")
            txt_lbl.pack(anchor=tk.W)

    # ----------- 数据加载 -----------

    def _load_tks_dir(self):
        d = filedialog.askdirectory(title="选择 TKS 游戏目录")
        if not d: return
        ko = os.path.join(d, "TKKon.dat")
        tk_ = os.path.join(d, "TKT.dat")
        if not os.path.exists(ko):
            messagebox.showwarning("文件缺失", "未找到 TKKon.dat")
            return
        self.kon_path = ko
        self.tkt_path = tk_ if os.path.exists(tk_) else None
        self._reload()

    def _reload(self):
        if not self.kon_path: return
        self.status_var.set("加载中…")
        self.root.update()
        if self.tkt_path:
            self.tkt = load_tkt(self.tkt_path)
        # 加载名称配置表
        name_csv = os.path.join(os.path.dirname(__file__), 'tkkon_names.csv')
        self.names = load_tkkon_names(name_csv)
        try:
            self.records = load_kon(self.kon_path)
            self._dirty = False
            nonempty = sum(1 for r in self.records
                          if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
            self.status_var.set(
                f"{len(self.records)} 条 (40字节/条) | 有效 {nonempty} | TKT {len(self.tkt)} 条")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            self.records = []
        self._update_paths()
        self._set_edit_enabled(True)
        self._apply_filter()

    def _set_edit_enabled(self, en):
        for c in self.edit_frame.winfo_children(): self._set_ws(c, en)

    def _set_ws(self, w, en):
        try:
            if isinstance(w, (ttk.Entry, ttk.Spinbox)):
                w.configure(state='normal' if en else 'disabled')
            elif isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if en else 'disabled')
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
        def _f(lb, p):
            if not p: lb.config(text="(未加载)", foreground=r)
            elif not os.path.exists(p): lb.config(text=f"(不存在){p}", foreground=r)
            else: lb.config(text=p, foreground=g)
        _f(self.lbl_kon, self.kon_path)
        _f(self.lbl_tkt, self.tkt_path)

    # ----------- 筛选/列表 -----------

    def _apply_filter(self):
        q = self.sv.get().strip().lower()
        self.filtered_indices = []
        for rec in self.records:
            if not self.show_empty.get():
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                    continue
            if q:
                nm = kon_record_name(rec, self.tkt, self.names)
                search_text = f"{rec['index']} {rec['tkact_id']} {rec['exec_mode']} {nm} " \
                              f"{' '.join(str(rec[fn]) for fn,_,_,_ in KON_FIELDS)}".lower()
                if q not in search_text:
                    continue
            self.filtered_indices.append(rec['index'])
        self._refresh_table()
        nonempty = sum(1 for r in self.records
                      if any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS))
        msg = f"显示 {len(self.filtered_indices)}/{KON_CNT} (有效 {nonempty}) | Ctrl+S 保存"
        if self._dirty: msg += " [已修改]"
        self.status_var.set(msg)

    def _clear_filter(self):
        self.sv.set("")
        self._apply_filter()

    def _refresh_table(self):
        for it in self.tree.get_children(): self.tree.delete(it)
        for idx in self.filtered_indices:
            r = self.records[idx]
            nm = kon_record_name(r, self.tkt, self.names)
            has_data = any(r[fn] != 0 for fn, _, _, _ in KON_FIELDS)
            tags = ['active'] if has_data else ['empty']
            if r['tkact_id'] == -1:
                tags = ['tkact_minus1']
            # 攻击距离: exec_mode 高字节
            em = r['exec_mode'] & 0xFFFF
            em_hi = (em >> 8) & 0xFF
            if em_hi >= 128:
                dist_str = "自身"
            elif em_hi == 0:
                dist_str = "单格"
            else:
                dist_str = f"{em_hi}格"
            # 攻击范围: target_param 高字节
            tp = r['target_param'] & 0xFFFF
            tp_hi = (tp >> 8) & 0xFF
            if tp_hi == 255:  # -1
                area_str = "全场"
            elif tp_hi == 254:  # -2
                area_str = "排除自身"
            elif tp_hi > 0:
                area_str = f"{tp_hi}格"
            else:
                area_str = "单体"
            # 生命伤害: 显示编码描述
            db = r['hp_damage']
            if db == -1:
                dmg_str = "攻击力"
            elif db == 0:
                dmg_str = "-"
            elif 1001 <= db <= 1999:
                dmg_str = f"{db-1000}%"
            elif 2001 <= db <= 2999:
                dmg_str = f"攻+{db-2000}"
            elif db >= 3001:
                dmg_str = f"攻×{100+db-3000}%"
            else:
                dmg_str = str(db)
            # 目标过滤: target_filter
            tf = r['target_filter']
            tf_lo = tf & 0xFF
            tf_hi = (tf >> 8) & 0xFF
            faction_map = {0: "敌", 1: "友", 2: "任意"}
            target_map = {0: "", 1: "仅人", 2: "仅地"}
            f_str = faction_map.get(tf_lo, "?")
            t_str = target_map.get(tf_hi, "")
            tf_str = f"{f_str}{t_str}" if t_str else f_str
            # 执行标志: exec_flags
            ef = r['exec_flags'] & 0xFF
            if ef & 4:
                ef_str = "物理"
            else:
                ef_str = "法术"
            self.tree.insert('', 'end',
                             values=(r['index'], r['tkact_id'], dist_str,
                                     nm if nm else f"(空-#{idx})",
                                     area_str, dmg_str, tf_str, ef_str),
                             tags=tags)

    def _sort_by(self, col):
        rev = getattr(self, '_sort_reverse', False)
        if col == 'tkt_name':
            self.filtered_indices.sort(
                key=lambda i: kon_record_name(self.records[i], self.tkt, self.names).lower(), reverse=rev)
        else:
            km = {'tkact_id': 'tkact_id', 'atk_range': 'exec_mode', 'atk_area': 'target_param',
                  'hp_damage': 'hp_damage', 'target_f': 'target_filter', 'exec_f': 'exec_flags'}
            self.filtered_indices.sort(
                key=lambda i: self.records[i].get(km.get(col, 'index'), 0), reverse=rev)
        self._sort_reverse = not rev
        self._refresh_table()

    # ----------- 编辑 -----------

    def _new_record(self):
        if not self.records:
            messagebox.showinfo("提示", "请先加载数据")
            return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                rec['exec_mode'] = 0
                rec['target_param'] = 0
                rec['tkact_id'] = rec['index']
                rec['hp_damage'] = -1
                rec['exec_flags'] = 4
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self._populate_edit(rec)
                self.status_var.set(f"已创建新条目 → 槽位 #{rec['index']} (ID={rec['tkact_id']})")
                return
        messagebox.showwarning("槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _copy_record(self):
        if not hasattr(self, '_editing_idx'): return
        src = self.records[self._editing_idx]
        if all(src[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            messagebox.showinfo("提示", "当前记录为空, 无需复制")
            return
        for rec in self.records:
            if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
                idx_bak = rec['index']
                rec.update({k: v for k, v in src.items() if k != 'index'})
                rec['index'] = idx_bak
                self._dirty = True
                self._apply_filter()
                for child in self.tree.get_children():
                    if int(self.tree.item(child)['values'][0]) == rec['index']:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        break
                self._populate_edit(rec)
                self.status_var.set(f"已复制 #{src['index']} → #{rec['index']}")
                return
        messagebox.showwarning("槽位已满", f"所有 {KON_CNT} 个记录槽位均已占用")

    def _clear_current(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS):
            messagebox.showinfo("提示", "当前记录已经为空")
            return
        if not messagebox.askyesno("确认清空", f"确定清空记录 #{rec['index']} 的所有字段?"):
            return
        for fn, _, _, _ in KON_FIELDS:
            rec[fn] = 0
        rec['index'] = rec['index']  # preserve index
        self._dirty = True
        self._apply_filter()
        self._populate_edit(rec)
        self.status_var.set(f"已清空记录 #{rec['index']}")

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0])['values'][0])
        self._populate_edit(self.records[idx])

    def _populate_edit(self, rec):
        self._editing_idx = rec['index']
        nm = kon_record_name(rec, self.tkt, self.names)
        em = rec.get('exec_mode', 0)
        cid = rec.get('tkact_id', 0)
        tp = rec.get('target_param', 0)

        em_text = describe_exec_mode(em) if em != 0 else ""
        tp_text = describe_target_param(tp) if tp != 0 else ""
        detail = "  |  ".join(filter(None, [em_text, tp_text]))

        self.lbl_rec_idx.config(text=(
            f"记录 #{rec['index']}    动画ID={cid}"
            + (f"    {detail}" if detail else "")
            + (f"    [{nm}]" if nm else "")
        ))

        # Preview
        self.preview_name.config(text=nm if nm else "(空槽)")
        info_parts = []
        # 攻击距离/面积分解
        em_desc = describe_exec_mode(em)
        if em_desc and em_desc != "单格":
            info_parts.append(f"攻击={em_desc}")
        tp = rec.get('target_param', 0)
        tp_desc = describe_target_param(tp)
        if tp_desc and tp_desc != "无扩散(单体)":
            info_parts.append(f"效果={tp_desc}")
        tf = rec.get('target_filter', 0)
        if tf: info_parts.append(describe_target_filter(tf))
        db = rec.get('hp_damage', 0)
        if db: info_parts.append(f"伤害={describe_hp_damage(db)}")
        mpd = rec.get('mp_damage', 0)
        if mpd: info_parts.append(f"内伤={describe_resource_val(mpd, '内力伤害')}")
        hr = rec.get('hp_restore', 0)
        if hr: info_parts.append(f"生命={describe_resource_val(hr, '生命回复')}")
        mr = rec.get('mp_restore', 0)
        if mr: info_parts.append(f"内力={describe_resource_val(mr, '内力回复')}")
        ef = rec.get('exec_flags', 0)
        if ef: info_parts.append(describe_exec_flags(ef))
        self.preview_info.config(text=" | ".join(info_parts) if info_parts else "(空动作)")

        # 填充编辑控件
        _damage_desc = {
            'hp_damage': describe_hp_damage,
            'mp_damage': lambda v: describe_resource_val(v, '内力伤害'),
            'hp_restore': lambda v: describe_resource_val(v, '生命回复'),
            'mp_restore': lambda v: describe_resource_val(v, '内力回复'),
        }
        for fn, fo, fl, _ in KON_FIELDS:
            val = rec.get(fn, 0)
            sv = str(val)
            self._edit_vars.get(fn, tk.StringVar()).set(sv)
            if fn in self._edit_extras:
                if 'status' in fn:
                    self._update_status_label(fn, int(val) if val else 0)
                elif fn in _damage_desc:
                    desc = _damage_desc[fn](int(val) if val else 0)
                    self._edit_extras[fn].config(text=desc, foreground='#228B22')
                else:
                    resolved = resolve_kon_val(fn, int(val) if val else 0, self.tkt)
                    self._edit_extras[fn].config(text=resolved, foreground='#3366cc')
        # 高/低字节拆分字段：赋值 spinbox + 显示分解描述
        _split_desc = {
            'exec_mode': describe_exec_mode,
            'target_param': describe_target_param,
            'target_filter': describe_target_filter,
        }
        for fn, desc_fn in _split_desc.items():
            val = rec.get(fn, 0)
            hi, lo = divmod(val & 0xFFFF, 256)
            if fn == 'exec_mode' and hi >= 128:
                hi = hi - 256  # 负值 → 自身
            if fn in self._edit_split:
                _, _, hi_var, lo_var = self._edit_split[fn]
                hi_var.set(str(hi))
                if fn in ('exec_mode', 'target_param'):
                    lo_var.set("启用" if lo == 0 else "禁用")
                elif fn == 'target_filter':
                    hi_var.set(["全部", "仅角色", "仅空地"][hi] if hi < 3 else str(hi))
                    lo_var.set(["对立阵营", "同阵营", "任意阵营"][lo] if lo < 3 else str(lo))
                else:
                    lo_var.set(str(lo))
            if fn in self._edit_extras:
                self._edit_extras[fn].config(text=desc_fn(val), foreground='#228B22')
        # exec_flags 位掩码复选框
        if 'exec_flags' in self._edit_split:
            lo = rec.get('exec_flags', 0) & 0xFF
            v0, v1, v2 = self._edit_split['exec_flags']
            v0.set(bool(lo & 1))
            v1.set(bool(lo & 2))
            v2.set(bool(lo & 4))
        if 'exec_flags' in self._edit_extras:
            self._edit_extras['exec_flags'].config(
                text=describe_exec_flags(rec.get('exec_flags', 0)),
                foreground='#228B22')

    # ----------- 编辑应用 -----------

    def _apply_edit(self):
        if not hasattr(self, '_editing_idx'): return
        rec = self.records[self._editing_idx]
        # 拆分字段: 从 spinbox 读 hi/lo 打包为 int16
        for fn in ('exec_mode', 'target_param', 'target_filter'):
            if fn in self._edit_split:
                _, _, hi_var, lo_var = self._edit_split[fn]
                try:
                    if fn == 'target_filter':
                        hi_map = {"全部": 0, "仅角色": 1, "仅空地": 2}
                        lo_map = {"对立阵营": 0, "同阵营": 1, "任意阵营": 2}
                        hi = hi_map.get(hi_var.get(), 0)
                        lo = lo_map.get(lo_var.get(), 0)
                    else:
                        hi = int(hi_var.get()) & 0xFF
                        if fn in ('exec_mode', 'target_param'):
                            lo = 0 if lo_var.get() == "启用" else 1
                        else:
                            lo = int(lo_var.get()) & 0xFF
                    combined = (hi << 8) | lo
                    if combined >= 0x8000:
                        combined -= 0x10000
                    rec[fn] = combined
                except ValueError:
                    pass
        # exec_flags 位掩码: 从复选框打包 (保留高字节)
        if 'exec_flags' in self._edit_split:
            v0, v1, v2 = self._edit_split['exec_flags']
            lo = (1 if v0.get() else 0) | (2 if v1.get() else 0) | (4 if v2.get() else 0)
            rec['exec_flags'] = lo
        for fn, fo, fl, _ in KON_FIELDS:
            if fn.startswith('unused') or fn in self._edit_split: continue
            try:
                v = int(self._edit_vars[fn].get())
                if v > 32767: v = 32767
                if v < -32768: v = -32768
                rec[fn] = v
            except ValueError:
                rec[fn] = 0
        self._dirty = True
        self._apply_filter()
        for child in self.tree.get_children():
            if int(self.tree.item(child)['values'][0]) == rec['index']:
                self.tree.selection_set(child)
                self.tree.see(child)
                break
        self.status_var.set(f"记录 #{rec['index']} 已修改 (内存, 未保存)")

    def _reset_edit(self):
        if hasattr(self, '_editing_idx'):
            self._populate_edit(self.records[self._editing_idx])

    # ----------- 保存/导出 -----------

    def _save(self):
        if not self.kon_path or not self.records:
            messagebox.showinfo("提示", "请先加载数据")
            return
        if not messagebox.askyesno("确认保存",
            f"保存 {len(self.records)} 条到:\n{self.kon_path}\n\n原文件将被覆盖 (生成 .bak)."):
            return
        try:
            with open(self.kon_path, 'rb') as s:
                with open(self.kon_path + ".bak", 'wb') as d: d.write(s.read())
        except: pass
        try:
            self.status_var.set("正在保存…")
            self.root.update()
            save_kon(self.kon_path, self.records)
            self._dirty = False
            self.status_var.set(f"已保存 → {self.kon_path}")
            messagebox.showinfo("保存成功", f"已保存\n备份: {self.kon_path}.bak")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _export_csv(self):
        if not self.records: return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        with open(p, 'w', encoding='utf-8-sig') as f:
            hdr = ['记录索引', '动画ID', 'TKT解析名称'] + [fn for fn, _, _, _ in KON_FIELDS]
            f.write(','.join(hdr) + '\n')
            for rec in self.records:
                if all(rec[fn] == 0 for fn, _, _, _ in KON_FIELDS): continue
                row = [str(rec['index']), str(rec.get('tkact_id', '')),
                       kon_record_name(rec, self.tkt, self.names)]
                row += [str(rec[fn]) for fn, _, _, _ in KON_FIELDS]
                f.write(','.join(row) + '\n')
        self.status_var.set(f"已导出: {p}")

    # ----------- 帮助 -----------

    def _show_field_ref(self):
        lines = ["TKKon.dat 字段映射 v3.0 (2026-05 语义修正)", ""]
        lines.append(f"【记录布局】{KON_CNT} 条 × {KON_REC} 字节 = {KON_DECOMPRESSED} 字节")
        lines.append(f"  20 × int16 (小端序) 共 {KON_REC} 字节/条")
        lines.append("")
        lines.append("【★ v3.0 修正: 字段语义完全重分析】")
        lines.append("  v2.0 错误: field[0-2] 被误判为 TKT 文本引用, 解析出场景名称")
        lines.append("  v3.0 修正: field[0-2] 是战斗引擎操作参数, 与TKT无关")
        lines.append("  证据: sub_43D53C/43D8B0/43E980 中的高/低字节分支判断")
        lines.append("")
        lines.append("【字段详情】")
        for fn, fo, fl, cmt in KON_FIELDS:
            marker = " ● 未使用" if fn.startswith('unused') else ""
            lines.append(f"  [{fo:02d}] {fl:<10s}{marker}")
            lines.append(f"       {cmt}")
        lines.append("")
        lines.append("【反编译函数引用】")
        lines.append("  sub_43D53C: 目标区域标记 (使用 field[0]低/高字节, field[2]低/高字节)")
        lines.append("  sub_43D8B0: 目标验证过滤 (使用 field[1]低/高字节, field[2]低字节)")
        lines.append("  sub_43E980: 伤害计算核心 (field[4-9] 编码解码)")
        lines.append("  sub_4458B0: 技能执行主函数 (field[0]高字节作为攻击距离判定)")
        lines.append("  sub_4434BC: 动画运行时 (field[3] → TKAct 动画条目)")
        lines.append("  sub_4173F8: TKKon 加载入口")
        lines.append("  Maker.exe sub_4027FF: 解压后大小校验 v19 == 26000")
        lines.append("")
        lines.append("【伤害字段编码规则 (sub_43E980)】")
        lines.append("  hp_damage / mp_damage / hp_restore / mp_restore 共享编码:")
        lines.append("    0       → 无效果")
        lines.append("    1~999   → 固定值")
        lines.append("    1001~1999 → 最大值的 (val-1000)% 百分比")
        lines.append("  hp_damage 独有:")
        lines.append("    -1      → 使用单位攻击力 (含技能特殊修正)")
        lines.append("    2001~2999 → 攻击力 + (val-2000) 固定加算")
        lines.append("    3001~32767 → 攻击力 × (1 + (val-3000)/100) 百分比乘算")
        lines.append("  hp_restore 特殊条件: 仅生命<25%时50%概率触发 (sub_43E980:491)")
        lines.append("  mp_restore 特殊条件: 仅内力<25%时50%概率触发 (sub_43E980:529)")

        dlg = tk.Toplevel(self.root)
        dlg.title("字段参考 v2.0 (修正版)")
        dlg.geometry("680x560")
        dlg.transient(self.root)
        tx = tk.Text(dlg, font=('Consolas', 9), wrap='word')
        sb1 = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tx.yview)
        tx.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        tx.pack(fill=tk.BOTH, expand=True)
        tx.insert('1.0', '\n'.join(lines))
        tx.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo("关于",
            "TKKon.dat 可视化编辑器 v3.0\n\n"
            "基于《三国群侠传》 TKS.exe 反编译\n"
            "2026-05 v3.0: 字段语义完全修正\n\n"
            "v3.0 修正:\n"
            "  field[0-2] = 战斗引擎操作参数 (非TKT文本!)\n"
            "  field[4-9] = 伤害/回复/命中基础值\n"
            "  field[19] = 执行标志 (含伤害类型)\n"
            "  TKT解析仅用于 hp_restore/mp_restore\n\n"
            "逆向来源:\n"
            "  sub_43D53C  目标区域标记\n"
            "  sub_43D8B0  目标过滤验证\n"
            "  sub_43E980  AI评估/伤害计算\n"
            "  sub_4458B0  技能执行\n"
            "  sub_4434BC  动画运行时\n"
            "  sub_4173F8  TKKon 加载"
        )


def main():
    root = tk.Tk()
    KonEditor(root)
    root.mainloop()

if __name__ == '__main__':
    main()
