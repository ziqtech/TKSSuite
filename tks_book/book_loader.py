# -*- coding: utf-8 -*-
"""tks_book 数据加载层 — 只读解析游戏目录下各 .dat 文件。

解析逻辑与各编辑器保持一致 (LZSS 解压 + 未压缩兜底 + int16 小端解包):
  TKT.dat     → editor_utils.tkt_loader.load_tkt_simple (Big5, XOR 0xFF)
  WarPC.dat   → warpc_editor.load_warpc 同款 (1054B/条 = 527 int16)
  TKSkill.dat → skill_editor.load_skills 同款 (94B/条 × 350)
  TKItem.dat  → item_editor.load_items 同款 (64B/条 × 600)
  Fa.JVG / Mu.JVG → editor_utils.jvg_loader.load_mu_sprites (@JVG 通用)
  SC.GRP + SC.IDX → editor_utils.grp_data (地图背景, 仅 Frame A)

本模块自带记录布局常量 (与 kon_name_resolver 相同做法), 不跨编辑器目录导入。
"""
import os
import struct

from editor_utils.lzss import lzss_decompress_dat
from editor_utils.tkt_loader import load_tkt_simple
from editor_utils.jvg_loader import load_mu_sprites
from editor_utils.game_defs import STATUS_NAMES

# ═══════════════════════════════════════════════════════════════
# 记录布局常量
# ═══════════════════════════════════════════════════════════════

WARPC_REC = 1054
WARPC_FIELD_COUNT = 527
SKILL_LEARN_BASE = 88      # [88]-[259] 344技能×1byte 学习状态
SKILL_LEARN_COUNT = 344
HISTORY_TKT_BASE = 9050    # 历史文本 TKT ID = 9050 + 角色序号
HISTORY_FIELD_IDX = 262    # 补丁字段 [262] 非零时覆盖历史文本ID
SCENE_NAME_TKT_BASE = 300  # 场景名 TKT ID = 300 + 场景ID

SKILL_REC = 94
SKILL_CNT = 350
ITEM_REC = 64
ITEM_CNT = 600

SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
ATK_TYPES = {-1: "近战攻击", 0: "物理攻击", 1: "术法攻击", 10: "召唤攻击"}
SPECIAL_FLAG_NAMES = ["飘浮", "飙行", "搜宝", "解陷"]
COMBAT_FLAG_NAMES = ["战后JP×2~3", "战后全恢复+异常全解", "经验×2~3平分队友", "经验独得"]
EXTRA_FLAG_NAMES = ["遇敌率降低", "遇敌率大幅降低", "免遇敌",
                    "战斗时序加速", "银两×2~5", "战斗时序强效"]
PAGE_NAMES = {0: "药品", 1: "道具", 2: "武器", 3: "防具", 4: "饰品", 5: "特殊"}
SKILL_LEARN_LABELS = {1: "等待学", 10: "可以学", 20: "组技能学会", 30: "子技能学会"}

# 使用权限 (equip_type) 位掩码 → 可读文本 (语义同 item_editor, 供物品列表显示)
USE_RIGHT_OPTIONS = {
    0: [(1, "战斗"), (2, "非战斗")],                              # 药品
    1: [(1, "战斗"), (2, "非战斗"), (4, "主角限定")],              # 道具
    2: [(1, "刀"), (2, "剑"), (4, "枪"), (8, "矛"),
        (16, "弓"), (32, "大刀"), (64, "戟"), (128, "锤")],      # 武器
    3: [(1, "衣袍"), (2, "铠甲")],                                # 防具
    4: [(0, "通用")],                                             # 饰品
    5: [(0, "通用")],                                             # 特殊
}


def use_right_label(val, page):
    """根据页面号解析使用权限位掩码为可读文本"""
    opts = USE_RIGHT_OPTIONS.get(page, [])
    sel = [name for bit, name in opts if bit == 0 or (val & bit)]
    return ", ".join(sel) if sel else "(无)"

# 八属性 (基础 idx, 当前 idx)
STAT_DEFS = [
    ("攻击", 11, 12), ("防御", 13, 14), ("命中", 15, 16), ("闪避", 17, 18),
    ("速度", 19, 20), ("幸运", 21, 22), ("移动", 23, 24), ("悟性", 25, 26),
]
# 角色五维 (标签, int16 idx)
CHAR_ATTR_DEFS = [
    ("智慧", 27), ("仁德", 28), ("勇气", 29), ("医术", 30), ("技能点数", 31),
]
EQUIP_ID_IDX = [73, 74, 75, 76]          # 装备物品 ID (查 TKItem item_id)
EQUIP_SKILL_IDX = [82, 83, 84, 85]       # 装备技能 → TKSkill 索引
PASSIVE_SKILL_IDX = [86, 87]             # 被动技能 → TKSkill 索引

# ── TKSkill 显示字段 (键, 字节偏移, 标签, 类型) ──
# 类型: int / pct / flags(special) / mask(status) / atk_type
SKILL_VIEW_FIELDS = [
    ("jp_cost",      6,  "学习消耗技能点", 'int'),
    ("timing",       40, "时序值Delay",    'int'),
    ("hp_pct",       42, "生命加成%",      'pct'),
    ("heal_move",    44, "移步回血",       'int'),
    ("mp_pct",       46, "内力加成%",      'pct'),
    ("mp_move",      48, "移步回气",       'int'),
    ("atk_pct",      50, "攻击加成%",      'pct'),
    ("def_pct",      52, "防御加成%",      'pct'),
    ("hit_pct",      54, "命中加成%",      'pct'),
    ("eva_pct",      56, "闪避加成%",      'pct'),
    ("spd_pct",      58, "速度加成%",      'pct'),
    ("move_up",      60, "增加移动",       'int'),
    ("atk_count",    62, "增攻次数",       'int'),
    ("special_flags", 64, "特殊标志",      'flags'),
    ("mp_reduce",    66, "内息消耗减%",    'pct'),
    ("immunity1",    68, "状态免疫 1-16",  'mask_lo'),
    ("immunity2",    70, "状态免疫 17-32", 'mask_hi'),
    ("exp_bonus",    72, "战后经验增加%",  'pct'),
    ("jp_bonus",     74, "战后技点增加%",  'pct'),
    ("magic_def",    76, "所受法伤减少%",  'pct'),
    ("cost_gold",    78, "消耗金钱",       'int'),
    ("cost_res2",    80, "耗费兽元",       'int'),
    ("cost_res3",    82, "耗费灵魂",       'int'),
    ("turn_shift",   84, "调整时序",       'int'),
    ("mp_cost",      86, "耗费内力",       'int'),
    ("trigger_prob", 88, "触发概率%",      'int'),
    ("sub_count",    90, "子技能数量",     'int'),
    ("atk_type",     92, "攻击类型",       'atk_type'),
]

# ── TKItem 显示字段 (键, 字节偏移, 标签, 类型) ──
ITEM_VIEW_FIELDS = [
    ("hp_inc",      14, "增加生命",     'val1000'),
    ("hp_heal",     16, "恢复生命",     'val1000'),
    ("mp_inc",      18, "增加内力",     'val1000'),
    ("mp_heal",     20, "恢复内力",     'val1000'),
    ("atk",         22, "增加攻击",     'int'),
    ("def_",        24, "增加防御",     'int'),
    ("hit",         26, "增加命中",     'int'),
    ("dodge",       28, "增加闪避",     'int'),
    ("spd",         30, "增加速度",     'int'),
    ("luk",         32, "增加幸运",     'int'),
    ("spi",         34, "增加悟性",     'int'),
    ("vit",         36, "增加移动",     'int'),
    ("jp_bonus",    38, "增加技能点",   'int'),
    ("medicine",    50, "增加医术",     'int'),
    ("combat_flag", 40, "战斗结算效果", 'combat_flag'),
    ("extra_flags", 60, "额外标志",     'extra_flags'),
    ("attach_skill",   42, "附加技能",        'skill'),
    ("equip_learn",    44, "装备后学习技能",  'skill'),
    ("use_learn1",     46, "使用后学习技能1", 'skill'),
    ("use_learn2",     48, "使用后学习技能2", 'skill'),
    ("cause_mask1", 52, "导致状态 1-16",  'mask_lo'),
    ("cause_mask2", 54, "导致状态 17-32", 'mask_hi'),
    ("cure_mask1",  56, "解除状态 1-16",  'mask_lo'),
    ("cure_mask2",  58, "解除状态 17-32", 'mask_hi'),
    ("price",       62, "价格",           'int'),
]


# ═══════════════════════════════════════════════════════════════
# dat 解析 (与各编辑器 load_* 保持一致)
# ═══════════════════════════════════════════════════════════════

def _decompress_with_fallback(raw, rec_size):
    """LZSS 解压 + 未压缩兜底 (各编辑器通用模式)"""
    dec = lzss_decompress_dat(raw)
    if len(raw) % rec_size == 0 and (len(dec) == 0 or len(dec) % rec_size != 0):
        dec = raw
    return dec


def load_warpc(fp):
    """WarPC.dat → [{'index', 'fields': [527×int16]}, ...]"""
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = _decompress_with_fallback(raw, WARPC_REC)
    if len(dec) % WARPC_REC != 0:
        raise ValueError(f"WarPC 解压后大小 {len(dec)} 不是 {WARPC_REC} 的整数倍")
    recs = []
    for i in range(len(dec) // WARPC_REC):
        vals = struct.unpack_from('<' + 'h' * WARPC_FIELD_COUNT, dec, i * WARPC_REC)
        recs.append({'index': i, 'fields': list(vals)})
    return recs


def load_skills(fp):
    """TKSkill.dat → [{'index', 'vals': (47×int16)}, ...]"""
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = _decompress_with_fallback(raw, SKILL_REC)
    recs = []
    for i in range(SKILL_CNT):
        off = i * SKILL_REC
        if off + SKILL_REC > len(dec):
            break
        vals = struct.unpack_from('<' + 'h' * 47, dec, off)
        recs.append({'index': i, 'vals': vals})
    return recs


def load_items(fp):
    """TKItem.dat → [{'index', 'vals': (32×int16)}, ...]"""
    with open(fp, 'rb') as f:
        raw = f.read()
    dec = _decompress_with_fallback(raw, ITEM_REC)
    recs = []
    for i in range(ITEM_CNT):
        off = i * ITEM_REC
        if off + ITEM_REC > len(dec):
            break
        vals = struct.unpack_from('<' + 'h' * 32, dec, off)
        recs.append({'index': i, 'vals': vals})
    return recs


def get_packed_byte(fields, base_idx, byte_idx):
    """读取打包字节区第 byte_idx 个 byte (同 warpc_schema.get_packed_byte)"""
    fi = base_idx + byte_idx // 2
    return ((fields[fi] & 0xFFFF) >> (8 * (byte_idx % 2))) & 0xFF


# ═══════════════════════════════════════════════════════════════
# 名称/文本辅助
# ═══════════════════════════════════════════════════════════════

def tkt_first_line(tkt, tid):
    """TKT ID → 第一行文本 (负数取绝对值再查); 找不到返回空串"""
    if not tid:
        return ""
    txt = tkt.get(tid) or tkt.get(-tid) or ""
    return txt.split('\n')[0].strip()


def tkt_full_text(tkt, tid):
    """TKT ID → 完整多行文本"""
    if not tid:
        return ""
    return (tkt.get(tid) or tkt.get(-tid) or "").strip()


def status_mask_names(val, hi=False):
    """状态位掩码 → 状态名列表 (hi=True 为 17-32 段)"""
    names = []
    base = 16 if hi else 0
    for bit in range(16):
        if val & (1 << bit):
            idx = base + bit
            names.append(STATUS_NAMES[idx] if idx < len(STATUS_NAMES) else f"状态{idx + 1}")
    return names


def flag_names(val, table):
    """位掩码 → 名称列表 (table 为按 bit 序的名称表)"""
    return [n for bit, n in enumerate(table) if val & (1 << bit)]


def val1000_text(val):
    """≤1000 固定值 / >1000 百分比 (item hp/mp 字段编码)"""
    if val > 1000:
        return f"{val - 1000}%"
    return str(val)


# ═══════════════════════════════════════════════════════════════
# 游戏数据容器
# ═══════════════════════════════════════════════════════════════

class GameData:
    """一次性加载游戏目录下 tks_book 所需的全部数据 (SC.GRP 惰性加载)"""

    def __init__(self):
        self.game_dir = ""
        self.tkt = {}            # {id: 完整多行文本}
        self.warpc_recs = []
        self.skill_recs = []
        self.item_recs = []
        self.item_by_id = {}     # item_id → item rec
        self.skill_names = {}    # skill_index → 名称
        self.fa_sprites = []     # Fa.JVG 头像 (PIL RGBA)
        self.mu_sprites = []     # Mu.JVG 图标 (PIL RGBA)
        self.tkkon_names = {}    # TKKon索引 → 显示名称 (KonNameResolver)
        self.skill_types = {}    # skill_index → type (0指令/1主动/2被动/3移动)
        self.cmd_skill_slots = {}  # skill_index → 效果判定槽位i (仅type==0)
        self._sc_grp = None      # 惰性: GRPFile
        self._sc_grp_tried = False
        self.paths = {}          # 文件名 → 绝对路径 (存在的才记录)
        # 反向索引 (book_index.build_indexes 填充)
        self.item_sources = {}   # item_id → [(途径, 描述), ...]
        self.char_joins = {}     # warpc_idx → [入队事件, ...]
        self.battles = {}        # battle_id → WarData 简记录
        self.battle_scenes = {}  # battle_id → {场景ID}
        self.enemy_battles = {}  # warpc_idx → [battle_id]
        self.special_items = []  # Attribute(-1,11,N) 特殊物品收集度来源列表
        self.mat_entities = {}   # TKMat 轻量实体表 {实体ID: type/scene/flags/x/y/ext}
        # 存档索引 (sub_41B1A8 扫描 save\1.sav ~ save\9.sav)
        # save_slots[i] = {'team_ids','gold','timestamp','team_levels','scene_id'} 或 None (空槽)
        self.save_slots = []
        self.save_dir = ""

    # ── 加载 ──

    def load(self, game_dir):
        """同步加载游戏目录。缺失的文件跳过 (对应标签页显示为空)。"""
        self.game_dir = game_dir
        self.paths = {}
        self._sc_grp = None
        self._sc_grp_tried = False
        self._status_view_cache = None  # game_status_view 资源缓存 (换目录后重建)
        self._tkt_raw = None            # TKT 原始字节 (含控制码, 游戏视图富文本用)
        self.save_slots = []
        self.save_dir = ""
        self.tkkon_names = {}
        self.skill_types = {}
        self.cmd_skill_slots = {}

        def _p(name):
            fp = os.path.join(game_dir, name)
            if os.path.exists(fp):
                self.paths[name] = fp
                return fp
            return None

        tkt_p = _p("TKT.dat")
        self.tkt = load_tkt_simple(tkt_p, full_strip=True) if tkt_p else {}

        wp = _p("WarPC.dat")
        self.warpc_recs = load_warpc(wp) if wp else []

        sp = _p("TKSkill.dat")
        self.skill_recs = load_skills(sp) if sp else []
        self.skill_names = {}
        self.skill_types = {}
        for rec in self.skill_recs:
            nm = tkt_first_line(self.tkt, rec['vals'][0])
            if nm:
                self.skill_names[rec['index']] = nm
            self.skill_types[rec['index']] = rec['vals'][2]
        # 构建指令技能槽位映射: type==0 的技能按索引升序 → slot i
        active_indices = sorted(
            i for i, t in self.skill_types.items() if t == 0
        )
        self.cmd_skill_slots = {si: i for i, si in enumerate(active_indices)}

        # TKKon 名称解析 (供角色技能效果判定显示用)
        if _p("TKKon.dat"):
            try:
                import sys
                _eu = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                if _eu not in sys.path:
                    sys.path.insert(0, _eu)
                from editor_utils.kon_name_resolver import KonNameResolver
                resolver = KonNameResolver(game_dir)
                self.tkkon_names = resolver.get_all_names(compact_threshold=3)
            except Exception:
                self.tkkon_names = {}

        ip = _p("TKItem.dat")
        self.item_recs = load_items(ip) if ip else []
        self.item_by_id = {}
        for rec in self.item_recs:
            iid = rec['vals'][0]
            if iid > 1 and iid not in self.item_by_id:
                self.item_by_id[iid] = rec

        fa = _p("Fa.JVG")
        self.fa_sprites = (load_mu_sprites(fa) or []) if fa else []
        mu = _p("Mu.JVG")
        self.mu_sprites = (load_mu_sprites(mu) or []) if mu else []

        # SC.GRP/SC.IDX 仅登记路径, 首次预览地图时再加载
        _p("SC.GRP")
        _p("SC.IDX")

        # 游戏状态界面复刻资源 (game_status_view 惰性解码, 此处仅登记路径)
        _p("mb.gxp")
        _p("save.gxp")
        _p("TitleMenu.gxp")   # 标题界面背景 (系统页"离开"进入, sub_425EAC)
        _p("Cur.JVG")         # 光标/标题按钮高亮精灵池 (sub_426164 帧 116-118)
        _p("PFace.jvg")
        _p("FONT9696")
        # 音频复刻资源 (game_audio 惰性加载; SSF.GRP 为点击音效包, Sound 为 BGM mp3)
        _p("SSF.GRP")         # 菜单音效包 (PCM WAV, sub_451600 加载到 unk_A2C1D0)
        _p("SSF.IDX")
        _p("Sound")           # BGM mp3 目录 (sound\%04d.mp3, sub_44AC50)

        # 存档索引 (sub_41B1A8: 循环打开 save\1.sav ~ save\9.sav, 28 字节/文件)
        # Windows 文件系统不区分大小写, 实际目录可能写作 Save 或 save
        self.save_slots = []
        self.save_dir = ""
        for sd_name in ("Save", "save"):
            sd = os.path.join(game_dir, sd_name)
            if os.path.isdir(sd):
                self.save_dir = sd
                break
        if self.save_dir:
            for idx in range(1, 10):  # 1-9 号存档槽
                self.save_slots.append(self._load_save_index(
                    os.path.join(self.save_dir, f"{idx}.sav")))

        # 反向索引: 物品获得途径 / 人物入队事件 (TKD/TKMat/TKShop/WarData)
        try:
            from book_index import build_indexes
            build_indexes(self)
        except Exception:
            self.item_sources = {}
            self.char_joins = {}
            self.battles = {}
            self.battle_scenes = {}
            self.enemy_battles = {}
            self.special_items = []
            self.mat_entities = {}

    # ── 地图 ──

    def sc_grp(self):
        """惰性加载 SC.GRP (较大, 首次访问地图页时才读)"""
        if self._sc_grp_tried:
            return self._sc_grp
        self._sc_grp_tried = True
        grp_p = self.paths.get("SC.GRP")
        idx_p = self.paths.get("SC.IDX")
        if not grp_p or not idx_p:
            return None
        try:
            from editor_utils.grp_data import load_grp
            self._sc_grp = load_grp(grp_p, idx_p)
        except Exception:
            self._sc_grp = None
        return self._sc_grp

    def scene_name(self, sid):
        """场景名 = TKT[300+场景ID] 第一行 (同 mat_dat_io.scene_name)"""
        txt = tkt_first_line(self.tkt, SCENE_NAME_TKT_BASE + sid)
        return txt if txt else f"场景{sid}"

    @staticmethod
    def _load_save_index(path):
        """加载 N.sav 索引文件 (28 字节, sub_41B1A8/sub_41CE10)

        格式: [6×1B team_ids][2B gold][4B unix_timestamp][6×2B team_levels][4B scene_id]
        team_ids 中 0xFF = 空位 (-1); 文件不存在/过短 → None (空槽)
        """
        if not os.path.exists(path):
            return None
        try:
            data = bytearray(open(path, 'rb').read())
        except Exception:
            return None
        if len(data) < 28:
            return None
        team_ids = [data[i] if data[i] != 0xFF else -1 for i in range(6)]
        gold = struct.unpack_from('<H', data, 6)[0]
        timestamp = struct.unpack_from('<I', data, 8)[0]
        team_levels = [struct.unpack_from('<H', data, 12 + i * 2)[0] for i in range(6)]
        scene_id = struct.unpack_from('<i', data, 24)[0]
        return {'team_ids': team_ids, 'gold': gold, 'timestamp': timestamp,
                'team_levels': team_levels, 'scene_id': scene_id}

    def scene_background(self, sid):
        """场景背景 PIL Image (仅 Frame A, 不解码前景/碰撞层 Frame B)"""
        grp = self.sc_grp()
        if grp is None:
            return None
        try:
            from editor_utils.grp_data import _decode_section_a
            from PIL import Image
            idx_map = {sec.index: sec for sec in grp.sections}
            sec = idx_map.get(sid)
            if not sec or sec.width <= 0 or sec.height <= 0:
                return None
            _decode_section_a(grp, sec)
            if not sec._pixels:
                return None
            return Image.frombytes('RGB', (sec.width, sec.height),
                                   sec._pixels, 'raw', 'BGR;16')
        except Exception:
            return None

    # ── 人物 ──

    def char_name(self, rec):
        """角色显示名 (索引 0/36 硬编码, 与 warpc_editor 一致)"""
        idx = rec['index']
        if idx == 0:
            return "主角"
        if idx == 36:
            return "主角[敌]"
        return tkt_first_line(self.tkt, rec['fields'][0])

    def char_history(self, rec):
        """角色历史文本 (补丁字段 [262] 非零时覆盖, 否则 9050+序号)"""
        hid = rec['fields'][HISTORY_FIELD_IDX]
        if hid == 0:
            hid = HISTORY_TKT_BASE + rec['index']
        return tkt_full_text(self.tkt, hid)

    def item_name_by_id(self, item_id):
        """装备物品 ID → 物品名"""
        rec = self.item_by_id.get(item_id)
        if rec is None:
            return ""
        return tkt_first_line(self.tkt, rec['vals'][2])

    def skill_name(self, skill_idx):
        return self.skill_names.get(skill_idx, "")

    def skill_effect_judgment(self, rec, skill_idx):
        """角色指令技能的效果判定文本: 从f[273+slot]读取TKKon ID并解析名称;
        非指令技能返回\"—\"(无效果判定字段)"""
        f = rec['fields']
        stype = self.skill_types.get(skill_idx, -1)
        if stype == 0:
            slot = self.cmd_skill_slots.get(skill_idx)
            if slot is not None and (273 + slot) < len(f):
                kon_id = f[273 + slot]
                if kon_id >= 0:
                    return self.tkkon_names.get(kon_id, f"TKKon#{kon_id}")
                return "(未设置)"
            return "(未设置)"
        return "—"

    def tkt_raw_bytes(self, tid):
        """TKT 条目原始字节 (0x1E 分行 + 控制码原样保留; 游戏视图富文本渲染用)"""
        if self._tkt_raw is None:
            try:
                from editor_utils.tkt_loader import load_tkt_raw
                self._tkt_raw = load_tkt_raw(self.paths.get("TKT.dat"))
            except Exception:
                self._tkt_raw = {}
        return self._tkt_raw.get(tid, b'')

    def char_name_by_index(self, warpc_idx):
        """WarPC 花名册索引 → 角色名 (脚本 TeamMember/CheckTeam 参数用)"""
        if 0 <= warpc_idx < len(self.warpc_recs):
            name = self.char_name(self.warpc_recs[warpc_idx])
            if name:
                return name
        return f"角色#{warpc_idx}"

    def battle_name(self, battle_id):
        """WarData 战斗ID → "战斗名 (地图)"; 结合 battle_scenes 补充触发场景"""
        w = self.battles.get(battle_id)
        if w is None:
            return f"战斗#{battle_id}"
        name = tkt_first_line(self.tkt, w['name_id']) or f"战斗#{battle_id}"
        scenes = sorted(self.battle_scenes.get(battle_id, ()))
        if scenes:
            sname = self.scene_name(scenes[0])
            extra = f" 等{len(scenes)}处" if len(scenes) > 1 else ""
            return f"{name} ({sname}{extra})"
        return name


# ═══════════════════════════════════════════════════════════════
# PIL → QPixmap
# ═══════════════════════════════════════════════════════════════

def pil_to_qpixmap(pil_img, size=None):
    """PIL Image → QPixmap (可选 NEAREST 缩放); 失败返回 None"""
    if pil_img is None:
        return None
    try:
        from PIL import Image
        from PySide6.QtGui import QImage, QPixmap
        img = pil_img
        if size is not None:
            img = img.resize(size, Image.NEAREST)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        data = img.tobytes('raw', 'RGBA')
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None
