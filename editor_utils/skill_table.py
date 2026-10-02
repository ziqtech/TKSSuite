"""skill_table — TKSkill.dat 统一加载 (技能记录 / 名称 / 类型 / 说明)。

各编辑器的技能弹窗与技能名映射统一走这里, 不再各自维护一套解析。
历史上 item / save / warpc / configs / kon / tks_book / skill 七处各写一份,
其中 item 与 save 还把条数写死在原版 350 条, 导致扩展技能 (350..696) 选不到;
名称/说明/回退文案也各不相同。

数据格式 (原版 sub_4173F8, 94 字节/条, 47×int16):
  [0] 名称文本ID (TKT)      [1] 说明文本ID (TKT, 独立字段, 不由名称ID推算)
  [2] 技能类型 (0 指令 / 1 主动 / 2 被动 / 3 移动)

条数按解压后实际记录数推导: tkskill_expand 后可到 697 条 (SKILL_MAX_CNT)。
"""
import struct
from typing import Dict, List, Optional, Sequence, Tuple

from editor_utils.lzss import decompress_with_fallback

# ── 记录布局 ──
SKILL_REC = 94
SKILL_FIELD_COUNT = 47
TEXT_ID_INDEX = 0      # 名称文本ID (TKT)
DESC_ID_INDEX = 1      # 说明文本ID (TKT, 原版直接读取该字段)
TYPE_INDEX = 2         # 技能类型

# ── 条数 ──
SKILL_ORIG_CNT = 350   # 原版条数 (参考值; 加载按实际记录数)
SKILL_MAX_CNT = 697    # tkskill_expand 上限

# ── 显示标签 (技能弹窗/学习状态共用一份) ──
SKILL_TYPES = {0: "指令技能", 1: "主动技能", 2: "被动技能", 3: "移动技能"}
SKILL_TYPE_SHORT = {0: "指令", 1: "主动", 2: "被动", 3: "移动"}
SKILL_LEARN_STATES = ["0-不会", "1-等待学", "10-可以学", "20-组技能学会", "30-子技能学会"]


def skill_name_text(fields: Sequence[int], tkt: Dict[int, str]) -> str:
    """按记录字段解析技能名称文本; 无文本时返回空串。"""
    text_id = fields[TEXT_ID_INDEX]
    if not text_id:
        return ""
    raw = tkt.get(text_id) or tkt.get(-text_id)
    return raw.split('\n')[0].strip() if raw else ""


def skill_display_name(fields: Sequence[int], tkt: Dict[int, str],
                       index: Optional[int] = None) -> str:
    """技能显示名: TKT 文本 → Skill#文本ID → (空-#索引)。"""
    name = skill_name_text(fields, tkt)
    if name:
        return name
    text_id = fields[TEXT_ID_INDEX]
    if text_id:
        return f"Skill#{text_id}"
    return f"(空-#{index})" if index is not None else "(空)"


def skill_desc_text(fields: Sequence[int], tkt: Dict[int, str]) -> str:
    """按记录字段解析技能说明文本 (说明文本ID 独立于名称文本ID); 无则空串。"""
    desc_id = fields[DESC_ID_INDEX]
    if not desc_id:
        return ""
    return tkt.get(desc_id) or tkt.get(-desc_id) or ""


def load_skill_records(path) -> List[List[int]]:
    """读取 TKSkill.dat → 每条 47 个 int16 的列表 (条数按实际记录数)。

    文件不可读或记录不对齐时抛 ValueError (调用方决定是否容忍)。
    """
    with open(path, 'rb') as f:
        raw = f.read()
    dec = decompress_with_fallback(raw, SKILL_REC)
    if not dec or len(dec) % SKILL_REC:
        raise ValueError(
            f"TKSkill.dat 解压后大小 {len(dec)} 不是记录大小 {SKILL_REC} 的整数倍")
    return [list(struct.unpack_from('<' + 'h' * SKILL_FIELD_COUNT, dec, i * SKILL_REC))
            for i in range(len(dec) // SKILL_REC)]


def build_skill_maps(records: Sequence[Sequence[int]], tkt: Dict[int, str]
                     ) -> Tuple[Dict[int, str], Dict[int, int], Dict[int, str]]:
    """(names, types, descs) 三张映射, 键为技能索引。"""
    names: Dict[int, str] = {}
    types: Dict[int, int] = {}
    descs: Dict[int, str] = {}
    for idx, fields in enumerate(records):
        names[idx] = skill_display_name(fields, tkt, idx)
        types[idx] = fields[TYPE_INDEX]
        desc = skill_desc_text(fields, tkt)
        if desc:
            descs[idx] = desc
    return names, types, descs


class SkillTable:
    """TKSkill.dat 解析结果: 记录 + 名称/类型/说明映射 + 选择器行数据。"""

    __slots__ = ("records", "names", "types", "descs")

    def __init__(self, records: Sequence[Sequence[int]], tkt: Dict[int, str]):
        self.records = [list(f) for f in records]
        self.names, self.types, self.descs = build_skill_maps(self.records, tkt)

    def __len__(self) -> int:
        return len(self.records)

    def name(self, index: int, fallback: Optional[str] = None) -> str:
        return self.names.get(index, fallback if fallback is not None else f"技能#{index}")

    def type_label(self, index: int, short: bool = False) -> str:
        table = SKILL_TYPE_SHORT if short else SKILL_TYPES
        return table.get(self.types.get(index), str(self.types.get(index)))

    def picker_rows(self, *, with_text_id: bool = False, desc_limit: Optional[int] = None,
                    skip_empty: bool = True) -> List[tuple]:
        """构造 SkillPickerDialog 行数据 (key, cells, type_id)。

        skip_empty: 跳过名称文本ID 为 0 的空槽 (选择器不列空槽)。
        """
        rows = []
        for idx, fields in enumerate(self.records):
            text_id = fields[TEXT_ID_INDEX]
            if skip_empty and not text_id:
                continue
            desc = self.descs.get(idx, '')
            if desc_limit:
                desc = desc[:desc_limit]
            cells = [str(idx)]
            if with_text_id:
                cells.append(str(text_id))
            cells.append(self.type_label(idx))
            cells.append(self.names.get(idx, ''))
            cells.append(desc)
            rows.append((idx, tuple(cells), self.types.get(idx)))
        return rows


def load_skill_table(path, tkt: Dict[int, str]) -> SkillTable:
    """读取 TKSkill.dat 并构建 SkillTable (记录不对齐时抛 ValueError)。"""
    return SkillTable(load_skill_records(path), tkt)


def load_skill_records_safe(path) -> List[List[int]]:
    """容错版: 文件缺失或损坏时返回空列表。"""
    try:
        return load_skill_records(path)
    except (OSError, ValueError):
        return []


def load_skill_table_safe(path, tkt: Dict[int, str]) -> Optional[SkillTable]:
    """容错版: 文件缺失或损坏时返回 None (选择器/名称映射用)。"""
    try:
        return load_skill_table(path, tkt)
    except (OSError, ValueError):
        return None
