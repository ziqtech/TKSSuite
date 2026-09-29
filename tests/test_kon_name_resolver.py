"""KonNameResolver 扩展技能命名回归测试。

覆盖:
  - TKSkill.dat 扩容后 (tkskill_expand, 技能 350..696) 名称按动态条数加载
  - WarPC.dat.tksx 稀疏角色覆盖 → "角色《技能名》" 命名
  - 无覆盖的扩展技能默认指向 TKKon 590 → "扩展技能默认效果" 标签
  - 扩展技能 (350+) 不占用旧版 WarPC fields[273+i] 槽位
  - 原版规模 TKSkill (350 条) 时 590 不打标签, 行为与旧版一致
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_utils.kon_name_resolver import KonNameResolver  # noqa: E402
from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from editor_utils.skill_extension import (  # noqa: E402
    GAME_EXTENDED_TKKON_DEFAULT,
    GAME_SKILL_BASE,
    create_skill_extension,
)

WARPC_REC = 1054
WARPC_FIELD_COUNT = 527
SKILL_REC = 94
KON_REC = 40
KON_CNT = 650


def _big5(text: str) -> bytes:
    return text.encode('big5')


def _make_tkt(entries: dict[int, str]) -> bytes:
    """合成 TKT.dat: [4B size][4B count][XOR(id表+偏移表+文本)]。"""
    ids = list(entries.keys())
    blob = bytearray()
    offsets = []
    for eid in ids:
        offsets.append(len(blob))
        blob += _big5(entries[eid]) + b'\x00'
    id_table = b''.join(struct.pack('<i', e) for e in ids)
    off_table = b''.join(struct.pack('<I', o) for o in offsets)
    payload = id_table + off_table + bytes(blob)
    enc = bytes(b ^ 0xFF for b in payload)
    return struct.pack('<II', len(payload), len(ids)) + enc


def _make_tkskill(entries: dict[int, tuple[int, int]]) -> bytes:
    """合成 TKSkill.dat。entries: {索引: (name_id, type)}; 未指定的记录补零。"""
    count = max(entries) + 1
    buf = bytearray(count * SKILL_REC)
    for idx, (name_id, stype) in entries.items():
        struct.pack_into('<h', buf, idx * SKILL_REC, name_id)
        struct.pack_into('<h', buf, idx * SKILL_REC + 4, stype)
    return lzss_compress_dat(bytes(buf))


def _make_warpc(records: dict[int, dict]) -> bytes:
    """合成 WarPC.dat。records: {角色索引: {'name_id': int, 'effects': {槽位: kon}}}"""
    count = max(records) + 1
    buf = bytearray(count * WARPC_REC)
    for ci, spec in records.items():
        off = ci * WARPC_REC
        struct.pack_into('<h', buf, off, spec.get('name_id', 0))
        for slot, kon_id in spec.get('effects', {}).items():
            struct.pack_into('<h', buf, off + (273 + slot) * 2, kon_id)
    return lzss_compress_dat(bytes(buf))


def _make_kon(count: int, tkact_ids: dict[int, int] | None = None) -> bytes:
    buf = bytearray(count * KON_REC)
    for idx, tkact in (tkact_ids or {}).items():
        struct.pack_into('<h', buf, idx * KON_REC + 6, tkact)
    return lzss_compress_dat(bytes(buf))


def _make_tksx(actor_count: int, ext_skill_count: int,
               overrides: list[tuple[int, int, int]]) -> bytes:
    ext = create_skill_extension(
        actor_count=actor_count, skill_count=ext_skill_count)
    ext = ext.with_overrides(overrides)
    return ext.to_bytes()


class KonNameResolverExtendedTests(unittest.TestCase):
    """扩展技能 (350+) 命名: TKSX 覆盖 + 默认 590 标签。"""

    def _build_dir(self, *, with_tksx: bool) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        self._d = d

        # TKT: 角色名 1001/1002, 原版技能名 2001/2002, 扩展技能名 3001/3002
        (d / 'TKT.dat').write_bytes(_make_tkt({
            1001: '劉備', 1002: '關羽',
            2001: '突刺', 2002: '橫掃',
            3001: '火球術', 3002: '雷擊術',
        }))
        # TKSkill: 原版 type=0 技能 0(突刺)/5(橫掃) 与 344(普攻特殊名);
        # 344 编号超出旧版字段上限 (527-273), 扩展 350/351 走 TKSX 层,
        # 三者都必须被排除在旧版 fields[273+技能编号] 寻址之外
        (d / 'TKSkill.dat').write_bytes(_make_tkskill({
            0: (2001, 0), 5: (2002, 0), 344: (2002, 0),
            350: (3001, 0), 351: (3002, 0),
        }))
        # WarPC: 40 条记录 (与 TKSX actor_count 一致)。
        # 直接寻址: 技能0 → fields[273], 技能5 → fields[278]
        effects = {0: 42, 5: 43}
        (d / 'WarPC.dat').write_bytes(_make_warpc({
            0: {'name_id': 0},
            1: {'name_id': 1001, 'effects': effects},
            2: {'name_id': 1002},
        }))
        # TKKon: 扩容到 661 条 (650 原版 + 11 扩展)
        (d / 'TKKon.dat').write_bytes(_make_kon(661, {655: 30, 660: 31}))
        if with_tksx:
            (d / 'WarPC.dat.tksx').write_bytes(_make_tksx(
                actor_count=40, ext_skill_count=2,
                overrides=[(1, 350, 655), (2, 351, 660),
                           (1, GAME_SKILL_BASE + 0, 655),
                           # 指向默认值的覆盖 → 不产生独立命名
                           (2, 350, GAME_EXTENDED_TKKON_DEFAULT)]))
        return tmp

    def test_sparse_override_names_tkkon_entry(self):
        self._build_dir(with_tksx=True)
        names = KonNameResolver(str(self._d)).get_all_names()
        # 角色覆盖: 劉備(角色1)技能350火球術 → TKKon 655
        self.assertEqual(names.get(655), '劉備《火球術》')
        # 角色覆盖: 關羽(角色2)技能351雷擊術 → TKKon 660
        self.assertEqual(names.get(660), '關羽《雷擊術》')

    def test_default_590_label_lists_extended_range(self):
        self._build_dir(with_tksx=True)
        names = KonNameResolver(str(self._d)).get_all_names()
        self.assertEqual(names.get(GAME_EXTENDED_TKKON_DEFAULT),
                         '扩展技能默认效果(技能350..351)')

    def test_extended_skills_do_not_shift_legacy_slots(self):
        self._build_dir(with_tksx=True)
        names = KonNameResolver(str(self._d)).get_all_names()
        # 旧版按 273+技能编号 直接寻址: 技能0(突刺)→42, 技能5(橫掃)→43。
        # 若 344/350/351 混入旧版列表, 名称会整体错位
        self.assertEqual(names.get(42), '劉備《突刺》')
        self.assertEqual(names.get(43), '劉備《橫掃》')

    def test_no_sidecar_still_labels_default(self):
        # 无旁车文件但 TKSkill 扩容: 游戏补丁语义仍把扩展技能默认指向 590
        self._build_dir(with_tksx=False)
        names = KonNameResolver(str(self._d)).get_all_names()
        self.assertEqual(names.get(GAME_EXTENDED_TKKON_DEFAULT),
                         '扩展技能默认效果(技能350..351)')
        # 无覆盖的扩展 TKKon 条目保持原有动画兜底命名
        self.assertEqual(names.get(655), '动画#30')

    def test_original_skill_size_never_labels_590(self):
        # 原版规模 TKSkill (350 条): 590 是普通条目, 不得打扩展标签
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / 'TKT.dat').write_bytes(_make_tkt({1001: '劉備', 2001: '突刺'}))
        (d / 'TKSkill.dat').write_bytes(_make_tkskill({0: (2001, 0)}))
        (d / 'WarPC.dat').write_bytes(_make_warpc(
            {1: {'name_id': 1001, 'effects': {0: 590}}}))
        (d / 'TKKon.dat').write_bytes(_make_kon(KON_CNT))
        names = KonNameResolver(str(d)).get_all_names()
        # 590 被旧版 WarPC 映射引用 → 正常角色命名, 而非扩展默认标签
        self.assertEqual(names.get(590), '劉備《突刺》')

    def test_legacy_name_wins_when_590_already_mapped(self):
        # TKSkill 扩容且 590 同时被旧版映射引用: 保留更具体的旧版名称
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / 'TKT.dat').write_bytes(_make_tkt({1001: '劉備', 2001: '突刺'}))
        (d / 'TKSkill.dat').write_bytes(_make_tkskill(
            {0: (2001, 0), 350: (2001, 0)}))
        (d / 'WarPC.dat').write_bytes(_make_warpc(
            {1: {'name_id': 1001, 'effects': {0: 590}}}))
        (d / 'WarPC.dat.tksx').write_bytes(_make_tksx(
            actor_count=2, ext_skill_count=1, overrides=[]))
        (d / 'TKKon.dat').write_bytes(_make_kon(KON_CNT))
        names = KonNameResolver(str(d)).get_all_names()
        self.assertEqual(names.get(590), '劉備《突刺》')


if __name__ == '__main__':
    unittest.main(verbosity=2)
