"""
TKKon 名称动态解析器 — 替代静态 tkkon_names.csv
===================================================
通过读取游戏 .dat 文件实时构建 TKKon 索引 → 显示名称的映射，
使 MOD 修改技能分配后名称自动更新。

数据来源:
  WarPC.dat  → 角色→技能→TKKon 映射 (fields[273+技能编号]) 与角色名
  WarPC.dat.tksx → 扩展技能 (350..696) 的角色级 TKKon 稀疏覆盖
  TKSkill.dat → 技能名称 (经由 TKT.dat, 条数按文件大小动态推导)
  TKItem.dat → 物品→TKKon 映射 (tkkon_index field)
  TKT.dat     → 显示文本 (Big5)
  TKKon.dat   → TKKon 条目自身字段 (tkact_id, exec_flags)

名称优先级:
  1. 角色技能: "角色名《技能名》" (via WarPC→TKSkill→TKT;
     扩展技能 via WarPC.dat.tksx 稀疏覆盖)
  2. 物品使用: "物品名" (via TKItem→TKT, 需 exec_flags bit1=1)
  3. 动画引用: "动画#N" (via tkact_id)
  4. 空槽位:   "空槽-#N"

扩展技能默认效果: 技能 350..696 无角色覆盖时统一指向
  TKKon 590 (GAME_EXTENDED_TKKON_DEFAULT), 该条目显示为
  "扩展技能默认效果(技能350..N)"。存档内的角色级覆盖无法
  在仅加载游戏目录的编辑器中体现。
"""

import os
import re
import struct

from editor_utils.lzss import lzss_decompress_dat
from editor_utils.skill_extension import (
    GAME_EXTENDED_TKKON_DEFAULT,
    GAME_SKILL_BASE,
    parse_skill_extension,
)
from editor_utils.tkt_loader import load_tkt_simple

# ── 格式常量 (与各编辑器保持一致) ──
WARPC_REC = 1054         # WarPC.dat 每条记录字节数
WARPC_FIELD_COUNT = 527  # WarPC 每条记录的 int16 字段数

# WarPC 技能效果区 (引擎协议: 按技能编号直接寻址, 见
# docs/技能扩展与存档兼容设计方案.md §2.4):
#   字索引 273..524 ↔ 常规技能 0..251
#   字索引 525      → 普攻(技能344)特殊读取, 不走 273+编号 公式
#   字索引 526      → 战斗精灵索引, 不是技能效果字段
WARPC_EFFECT_BASE = 273
WARPC_LEGACY_SKILL_MAX = 251
WARPC_NORMAL_ATTACK_FIELD = 525
NORMAL_ATTACK_SKILL = 344  # 普攻 (TKSkill type=0 列表末位, 名称固定"攻擊")

SKILL_REC = 94           # TKSkill.dat 每条记录字节数 (条数动态, tkskill_expand 后含 350+ 扩展技能)

ITEM_REC = 64            # TKItem.dat 每条记录字节数

KON_REC = 40             # TKKon.dat 每条记录字节数
KON_CNT = 650            # TKKon 原版记录数 (tkkon_expand 补丁可扩容, 实际条数按文件大小动态推导)

# ── 硬编码陷阱映射 (sub_434C0C: word_9D6C7A = byte_9DFA92[5*a3] + 551) ──
# 陷阱类型 1-6 + 551 = TKKon 552-557, 名称来自 wardata_editor 注释
TRAP_NAMES: dict[int, str] = {
    552: "山崩陷阱",
    553: "泥沼陷阱",
    554: "漩渦陷阱",
    555: "火焰陷阱",
    556: "滾木陷阱",
    557: "瘴氣陷阱",
}

# ── 主角武器攻击映射 (sub_4307CC: weapon_type → TKKon 0-6) ──
# switch(v25): type 1→1(刀), 32→2(大刀), 16→3(弓), 8→4(矛), 4→5(槍), 2→6(劍), 其他→0(空手)
PROTAGONIST_ATTACK_NAMES: dict[int, str] = {
    0: "主角《空手攻擊》",
    1: "主角《刀攻擊》",
    2: "主角《大刀攻擊》",
    3: "主角《弓攻擊》",
    4: "主角《矛攻擊》",
    5: "主角《槍攻擊》",
    6: "主角《劍攻擊》",
}

# ── 软默认名称 (原版未使用槽位, MOD 匹配到数据时优先覆盖) ──
DEFAULT_NAMES: dict[int, str] = {
    409: "南蠻女將《攻擊》（原版未完成）",
    428: "銀骥《攻擊》（原版未完成）",
    443: "黃巾道眾《落石》（原版未完成）",
    459: "未知",
    510: "未知",
    511: "未知",
    512: "未知",
    526: "麒麟《仙術》",
    558: "未知",
    559: "未知",
    560: "未知",
    561: "未知",
    642: "未知",
}


class KonNameResolver:
    """TKKon 索引动态名称解析器。

    用法:
        resolver = KonNameResolver("/path/to/tks/game/dir")
        name = resolver.get_name(42)  # → "主角《金曦》"
        all_names = resolver.get_all_names()  # → {0: "主角《空手攻击》", ...}
    """

    def __init__(self, tks_dir: str):
        """初始化解析器，加载所有 .dat 文件并构建名称映射。

        Args:
            tks_dir: TKS 游戏根目录 (包含 WarPC.dat, TKSkill.dat, TKT.dat 等)
        """
        self._names: dict[int, str] = {}       # 完整名称
        self._kon_cnt = KON_CNT                # TKKon 实际条数 (按 TKKon.dat 大小动态推导)
        self._tks_dir = tks_dir
        self._build(tks_dir)

    # ── 公开接口 ──

    def get_name(self, kon_index: int, compact_threshold: int = 0) -> str:
        """获取指定 TKKon 索引的显示名称。

        Args:
            kon_index: TKKon 条目索引 (原版 0-649, 补丁扩容后随文件条数扩展)
            compact_threshold: 精简阈值。当名称中角色引用数超过此值时，
                              仅返回技能名（如 "《集中》"）。0 表示不精简。
        """
        name = self._names.get(kon_index, f"空槽-#{kon_index}")
        if compact_threshold > 0:
            name = self._apply_compact(name, compact_threshold)
        return name

    def get_all_names(self, compact_threshold: int = 0) -> dict[int, str]:
        """返回完整的 {TKKon索引: 显示名称} 字典。

        Args:
            compact_threshold: 精简阈值，0 表示不精简。

        适用于需要 dict 语义的调用方 (如 TkkonPickerDialog 接收名称字典)。
        """
        if compact_threshold <= 0:
            return dict(self._names)
        return {
            k: self._apply_compact(v, compact_threshold)
            for k, v in self._names.items()
        }

    # ── 精简显示 ──

    @staticmethod
    def _apply_compact(name: str, threshold: int) -> str:
        """当名称中角色引用数超过 threshold 时，仅保留技能名。

        例: "角色A《集中》 角色B《集中》 角色C《集中》 角色D《集中》"
          threshold=3 → "《集中》"
        """
        count = name.count('《')
        if count <= threshold:
            return name
        m = re.search(r'《([^》]+)》', name)
        if m:
            return f'《{m.group(1)}》'
        return name

    # ── 内部构建逻辑 ──

    def _build(self, tks_dir: str):
        """主构建流程: 加载所有数据源并建立映射。"""
        # 1. 加载 TKT 文本 (基础依赖)
        tkt = self._load_tkt(tks_dir)

        # 2. 加载 TKSkill — 获取技能名称和类型 (需要 type==0 过滤指令技能)
        skill_names, skill_types = self._load_skill_data(tks_dir, tkt)

        # 3. 加载 TKKon — 获取 exec_flags / tkact_id
        kon_entries = self._load_kon(tks_dir)

        # 4. 主角武器攻击硬编码 (sub_4307CC: weapon_type → 0-6)
        #    必须在 WarPC 之前填充，0-6 不参与其他解析逻辑
        self._resolve_protagonist_attacks()

        # 5. 加载 WarPC — 角色→指令技能→TKKon 映射
        #    (旧版 fields[273+i] 槽位 + WarPC.dat.tksx 扩展技能稀疏覆盖)
        self._resolve_from_warpc(tks_dir, tkt, skill_names, skill_types, kon_entries)

        # 6. 加载 TKItem — 物品→TKKon 映射 (补充)
        self._resolve_from_items(tks_dir, tkt, kon_entries)

        # 7. 陷阱硬编码映射 (sub_434C0C: trap_type + 551)
        self._resolve_traps()

        # 8. 软默认名称 (原版未使用槽位, 仅当未被 WarPC/Item 解析时填充)
        self._resolve_defaults()

        # 9. 剩余空槽: 用动画引用或空槽标记填充
        self._fill_remaining(kon_entries)

    # ── 数据加载 ──

    def _load_tkt(self, tks_dir: str) -> dict[int, str]:
        """加载 TKT.dat 文本。"""
        path = os.path.join(tks_dir, 'TKT.dat')
        if os.path.exists(path):
            return load_tkt_simple(path, skip_range=None)
        return {}

    def _load_skill_data(self, tks_dir: str, tkt: dict[int, str]):
        """加载 TKSkill.dat 并解析所有技能的名称和类型。

        Returns: (names, types)
          names: {skill_index: skill_name}
          types: {skill_index: type_value}   (0=指令, 1=主动, 2=被动, 3=移动)

        与 warpc_editor.py _load_skill_names() 保持一致: 条数按解压后
        大小动态推导 (tkskill_expand 后含 350..696 扩展技能),
        不再限于原版 350 条。
        """
        path = os.path.join(tks_dir, 'TKSkill.dat')
        if not os.path.exists(path):
            return {}, {}

        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % SKILL_REC == 0 and (len(dec) == 0 or len(dec) % SKILL_REC != 0):
                dec = raw
        except Exception:
            return {}, {}

        names: dict[int, str] = {}
        types: dict[int, int] = {}
        for i in range(len(dec) // SKILL_REC):
            off = i * SKILL_REC
            if off + 6 > len(dec):
                break
            name_id = struct.unpack_from('<h', dec, off)[0]
            stype = struct.unpack_from('<h', dec, off + 4)[0]
            types[i] = stype

            if name_id > 0 and name_id in tkt:
                names[i] = tkt[name_id].split('\n')[0].strip()
            elif name_id < 0 and -name_id in tkt:
                names[i] = tkt[-name_id].split('\n')[0].strip()
            elif name_id:
                names[i] = f'文本#{name_id}'
        return names, types

    def _load_kon(self, tks_dir: str) -> list[dict]:
        """加载 TKKon.dat 条目。

        Returns: [{index, tkact_id, exec_flags, ...}, ...]

        与 kon_editor.py 的 load_kon 保持一致: 条数按解压后大小动态推导
        (tkkon_expand 补丁可将 TKKon.dat 扩容到 650 条以上), 不足原版
        650 条时补空槽位。
        """
        path = os.path.join(tks_dir, 'TKKon.dat')
        if not os.path.exists(path):
            return []

        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % KON_REC == 0 and (len(dec) == 0 or len(dec) % KON_REC != 0):
                dec = raw
        except Exception:
            return []

        # 动态条数: 扩容文件取实际条数, 截断文件至少补齐原版 650 条
        self._kon_cnt = max(len(dec) // KON_REC, KON_CNT)

        entries = []
        for i in range(self._kon_cnt):
            off = i * KON_REC
            if off + KON_REC > len(dec):
                # 部分条目缺失 — 补空
                entries.append({
                    'index': i, 'tkact_id': -1, 'exec_flags': 0,
                    'exec_mode': 0, 'target_param': 0,
                })
                continue
            vals = struct.unpack_from('<' + 'h' * 20, dec, off)
            entries.append({
                'index': i,
                'exec_mode': vals[0],
                'target_param': vals[1],
                'target_filter': vals[2],
                'tkact_id': vals[3],
                'hp_damage': vals[4],
                'mp_damage': vals[5],
                'accuracy': vals[6],
                'extra_damage': vals[7],
                'hp_restore': vals[8],
                'mp_restore': vals[9],
                'inflict_status_lo': vals[10],
                'inflict_status_hi': vals[11],
                'remove_status_lo': vals[12],
                'remove_status_hi': vals[13],
                'timing_mod': vals[14],
                # vals[15..18] = unused15..unused18 (始终为0)
                'exec_flags': vals[19],   # 字节偏移 38
            })
        return entries

    # ── WarPC 解析: 角色技能 → TKKon ──

    def _resolve_from_warpc(self, tks_dir: str, tkt: dict[int, str],
                            skill_names: dict[int, str],
                            skill_types: dict[int, int],
                            kon_entries: list[dict]):
        """从 WarPC.dat 解析角色→指令技能→TKKon 的映射链。

        对于 WarPC 每条记录:
          fields[0] = 角色名 TKT ID
          fields[273+技能编号] = 常规技能 0..251 的 TKKon ID (直接寻址)
          fields[525] = 普攻(技能344)特殊读取字段
          扩展技能 350..696 走 WarPC.dat.tksx 稀疏覆盖 (默认 TKKon 590)

        同一 TKKon 可能被多个指令技能引用（例如张辽的攻击、引导射击、
        散箭射击都指向同一个 TKKon）。此方法会收集所有技能名，
        用顿号连接："张辽《攻击、引导射击、散箭射击》"。

        扩展技能 (350..696) 不走旧版槽位: 其 TKKon 映射来自
        WarPC.dat.tksx 扩展块的稀疏角色覆盖 (语义见 skill_extension),
        与旧版引用合并进同一份名称聚合。

        与 warpc_editor.py load_warpc() +
        _build_skill_effect_section 保持一致。
        """
        path = os.path.join(tks_dir, 'WarPC.dat')
        if not os.path.exists(path):
            return

        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % WARPC_REC == 0 and (len(dec) == 0 or len(dec) % WARPC_REC != 0):
                dec = raw
        except Exception:
            return

        if len(dec) % WARPC_REC != 0:
            return

        # 获取所有 type=0 指令技能的索引列表 (按索引升序)
        # 引擎按 273+技能编号 直接寻址, 只有常规技能 0..251 占用旧版
        # 字段; 扩展技能 (350+) 走 TKSX 覆盖层, 344 由字索引 525 特殊
        # 读取, 均不进入此列表
        active_indices = sorted(
            i for i, t in skill_types.items()
            if t == 0 and i <= WARPC_LEGACY_SKILL_MAX
        )
        if not active_indices:
            # 无 skill_types 信息时回退: 使用所有有名称的技能索引
            active_indices = sorted(
                i for i in skill_names if i <= WARPC_LEGACY_SKILL_MAX)

        char_count = len(dec) // WARPC_REC

        # ── 第一遍: 收集所有 (角色, 技能) → TKKon 映射 ──
        # TKKon ID → {char_name: [skill_name1, skill_name2, ...]}
        kon_refs: dict[int, dict[str, list[str]]] = {}
        char_names: dict[int, str] = {}

        for ci in range(char_count):
            off = ci * WARPC_REC
            char_name_id = struct.unpack_from('<h', dec, off)[0]
            if ci == 0:
                char_name = "主角"
            elif ci == 36:
                char_name = "主角[敌]"
            else:
                char_name = self._resolve_tkt_name(char_name_id, tkt, f"角色#{ci}")
            char_names[ci] = char_name
            if not char_name:
                continue

            for skill_idx in active_indices:
                field_off = off + (WARPC_EFFECT_BASE + skill_idx) * 2
                if field_off + 2 > len(dec):
                    continue
                kon_id = struct.unpack_from('<h', dec, field_off)[0]

                if kon_id < 0 or kon_id >= self._kon_cnt:
                    continue

                skill_name = skill_names.get(skill_idx, f"技能#{skill_idx}")
                if kon_id not in kon_refs:
                    kon_refs[kon_id] = {}
                char_skills = kon_refs[kon_id]
                if char_name not in char_skills:
                    char_skills[char_name] = []
                char_skills[char_name].append(skill_name)

            # 普攻覆盖: 字索引 525 特殊读取 (不走 273+编号 公式)
            field_off = off + WARPC_NORMAL_ATTACK_FIELD * 2
            if field_off + 2 <= len(dec):
                kon_id = struct.unpack_from('<h', dec, field_off)[0]
                if 0 <= kon_id < self._kon_cnt:
                    if kon_id not in kon_refs:
                        kon_refs[kon_id] = {}
                    char_skills = kon_refs[kon_id]
                    if char_name not in char_skills:
                        char_skills[char_name] = []
                    char_skills[char_name].append("攻擊")

        # ── TKSX 扩展块: 稀疏角色覆盖 (技能350..696) → TKKon ──
        # 扩展技能默认统一指向 TKKon 590, 仅与默认不同的覆盖才存入
        # 稀疏表; 指向默认值的覆盖不产生独立命名
        extension = self._load_tksx_extension(path)
        if extension is not None:
            for entry in extension.overrides:
                if entry.tkkon_id == GAME_EXTENDED_TKKON_DEFAULT:
                    continue
                char_name = (char_names.get(entry.actor_id)
                             or f"角色#{entry.actor_id}")
                skill_name = skill_names.get(
                    entry.skill_id, f"技能#{entry.skill_id}")
                skills = kon_refs.setdefault(
                    entry.tkkon_id, {}).setdefault(char_name, [])
                if skill_name not in skills:
                    skills.append(skill_name)

        # ── 第二遍: 合并同角色多技能用顿号, 不同角色用空格 ──
        for kon_id, char_skills in kon_refs.items():
            # 已通过 WarPC 以外的途径解析过 (主角武器攻击 0-6, 但做防御)
            if kon_id in self._names:
                continue

            parts: list[str] = []
            for char_name, skill_list in char_skills.items():
                # 去重并保持原始顺序
                seen: set[str] = set()
                unique_skills: list[str] = []
                for s in skill_list:
                    if s not in seen:
                        seen.add(s)
                        unique_skills.append(s)
                skill_str = '、'.join(unique_skills)
                parts.append(f"{char_name}《{skill_str}》")

            # 不同角色用空格拼接: 殭屍《攻擊》 殭屍兵《攻擊》
            self._names[kon_id] = ' '.join(parts)

        # ── 扩展技能默认效果: 技能350+ 无角色覆盖时统一指向 TKKon 590 ──
        # 依据 tkskill_expand 补丁: 旧技能 <350 保持 WarPC 偏移,
        # 技能 350..696 默认 TKKon 590 (可由稀疏角色覆盖)。
        # 若该条目已被旧版 WarPC 映射命名, 保留更具体的旧版名称。
        ext_max = max(
            (i for i in skill_types if i >= GAME_SKILL_BASE), default=-1)
        if (ext_max >= GAME_SKILL_BASE
                and GAME_EXTENDED_TKKON_DEFAULT not in self._names):
            self._names[GAME_EXTENDED_TKKON_DEFAULT] = (
                f"扩展技能默认效果(技能{GAME_SKILL_BASE}..{ext_max})")

    def _load_tksx_extension(self, warpc_path: str):
        """加载 WarPC.dat.tksx 旁车扩展块 (扩展技能状态与 TKKon 覆盖)。

        与 warpc_editor 模板模式一致: 扩展块存放在 WarPC.dat 同目录
        的 .tksx 旁车文件; 缺失或解析失败按无扩展块处理, 不阻断
        名称构建。
        """
        sidecar = warpc_path + '.tksx'
        if not os.path.exists(sidecar):
            return None
        try:
            with open(sidecar, 'rb') as f:
                return parse_skill_extension(f.read())
        except Exception:
            return None

    # ── TKItem 解析: 物品 → TKKon ──

    def _resolve_from_items(self, tks_dir: str, tkt: dict[int, str],
                            kon_entries: list[dict]):
        """从 TKItem.dat 解析物品→TKKon 映射。

        TKItem 每条记录:
          offset 0:  item_id  (int16)
          offset 4:  name_id  (int16, TKT ID)
          offset 12: tkkon_index (int16, TKKon 引用)

        如果 TKKon 条目的 exec_flags bit1=1 (物品类型),
        且该 TKKon 条目尚未被 WarPC 链路解析，
        则用物品名填充名称。
        """
        path = os.path.join(tks_dir, 'TKItem.dat')
        if not os.path.exists(path):
            return

        try:
            with open(path, 'rb') as f:
                raw = f.read()
            dec = lzss_decompress_dat(raw)
            if len(raw) % ITEM_REC == 0 and (len(dec) == 0 or len(dec) % ITEM_REC != 0):
                dec = raw
        except Exception:
            return

        # 收集所有物品引用: kon_id → [物品名列表]
        # 一个 kon 可能被多个物品引用 (如 小續命丹、續命丹、大續命丹)
        # 按实际记录数解析 (tkitem_expand 后可超过原版 600 条)
        item_kon_map: dict[int, list[str]] = {}
        for i in range(len(dec) // ITEM_REC):
            off = i * ITEM_REC
            if off + 14 > len(dec):
                break
            item_id = struct.unpack_from('<h', dec, off)[0]
            if item_id <= 0:
                continue
            name_id = struct.unpack_from('<h', dec, off + 4)[0]
            tkkon_index = struct.unpack_from('<h', dec, off + 12)[0]
            if tkkon_index < 0 or tkkon_index >= self._kon_cnt:
                continue

            item_name = self._resolve_tkt_name(name_id, tkt, "")
            if not item_name:
                continue

            if tkkon_index not in item_kon_map:
                item_kon_map[tkkon_index] = []
            # 去重
            if item_name not in item_kon_map[tkkon_index]:
                item_kon_map[tkkon_index].append(item_name)

        # 填充到 _names (仅对未被 WarPC 解析的条目), 多个物品用顿号连接
        for kon_id, name_list in item_kon_map.items():
            if kon_id not in self._names:
                self._names[kon_id] = '、'.join(name_list)

    # ── 陷阱硬编码: sub_434C0C L14 → trap_type + 551 = TKKon 552-557 ──

    def _resolve_traps(self):
        """填充硬编码的陷阱 TKKon 条目名称。

        游戏源码 (sub_434C0C):
          word_9D6C7A = byte_9DFA92[5 * a3] + 551;
        陷阱类型 1-6 分别对应 TKKon 552-557。
        """
        for kon_id, name in TRAP_NAMES.items():
            if kon_id not in self._names:
                self._names[kon_id] = name

    # ── 主角武器攻击: sub_4307CC L122-156 → weapon_type → TKKon 0-6 ──

    def _resolve_protagonist_attacks(self):
        """填充硬编码的主角武器攻击 TKKon 条目名称。

        游戏源码 (sub_4307CC):
          主角 (WarPC[0]) 的装备类型 → weapon_type → TKKon 0-6
          switch(v25): type 1→1(刀), 32→2(大刀), 16→3(弓),
                       8→4(矛), 4→5(槍), 2→6(劍), 其他→0(空手)
        """
        for kon_id, name in PROTAGONIST_ATTACK_NAMES.items():
            if kon_id not in self._names:
                self._names[kon_id] = name

    # ── 软默认名称 ──

    def _resolve_defaults(self):
        """填充原版未使用槽位的默认名称。

        仅在 WarPC/TKItem/陷阱 均未解析到时才填充。
        MOD 若为这些槽位配置了角色或物品，会被前面的步骤优先匹配。
        """
        for kon_id, name in DEFAULT_NAMES.items():
            if kon_id not in self._names:
                self._names[kon_id] = name

    # ── 剩余填充 ──

    def _fill_remaining(self, kon_entries: list[dict]):
        """对于未被 WarPC/Item 解析到的 TKKon 条目, 用动画引用或空槽标记填充。"""
        for entry in kon_entries:
            idx = entry['index']
            if idx in self._names:
                continue

            # 检查是否是空条目
            has_data = any(
                entry[k] != 0 for k in [
                    'exec_mode', 'target_param', 'target_filter',
                    'tkact_id', 'hp_damage', 'mp_damage',
                    'hp_restore', 'mp_restore', 'exec_flags',
                ]
            )
            if not has_data:
                self._names[idx] = f"空槽-#{idx}"
                continue

            # 有数据的条目: 用动画引用
            cid = entry.get('tkact_id', 0)
            if cid > 0:
                self._names[idx] = f"动画#{cid}"
            else:
                self._names[idx] = f"空槽-#{idx}"

    # ── 辅助 ──

    @staticmethod
    def _resolve_tkt_name(name_id: int, tkt: dict[int, str],
                          fallback: str) -> str:
        """通过 TKT ID 获取名称文本。"""
        if name_id > 0 and name_id in tkt:
            return tkt[name_id].split('\n')[0].strip()
        if name_id < 0 and -name_id in tkt:
            return tkt[-name_id].split('\n')[0].strip()
        return fallback

