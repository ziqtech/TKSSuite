"""回归：skill_ext_learn_state 必须为敌方 WarPC 拷贝登记 battle map。

根因：sub_4307CC 存在我方(0x30987)/敌方(0x30D24)两处 `mov ecx,0x107` memcpy。
统一技能扩展的 learn_reader 在 skill<350 时读 WarPC[map[unit]-1]。
若敌方位点未挂钩，map[unit]=0 → 误读 WarPC[0] → 敌方技能组全部判未学会。
"""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH_JSON = ROOT / "tks_launcher_gui" / "patches" / "skill_ext_learn_state" / "patch.json"
GAME_EXE = Path(r"游戏目录（改版）/TKS.exe")
FALLBACK_EXE = Path(r"游戏目录/TKS.exe")
WARPC = Path(r"游戏目录（改版）/WarPC.dat")
TKSKILL = Path(r"游戏目录（改版）/TKSkill.dat")
REC = 1054
PLAYER_SITE = 0x30987
ENEMY_SITE = 0x30D24
MOV_ECX_107 = bytes.fromhex("B907010000")


def _load_patch() -> dict:
    return json.loads(PATCH_JSON.read_text(encoding="utf-8"))


def _sites_by_rva(patch: dict) -> dict[int, dict]:
    out = {}
    for site in patch.get("sites", []):
        raw = site.get("rva", 0)
        rva = int(raw, 16) if isinstance(raw, str) else int(raw)
        out[rva] = site
    return out


def _pe_text(data: bytes):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    opt_off = e_lfanew + 24
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    image_base = struct.unpack_from("<I", data, opt_off + 28)[0]
    nsections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    sec_off = opt_off + opt_size
    for i in range(nsections):
        off = sec_off + i * 40
        name = data[off : off + 8].split(b"\x00", 1)[0]
        _vsize, va, _rsize, raw = struct.unpack_from("<IIII", data, off + 8)
        if name == b".text":
            return image_base, va, raw
    raise AssertionError(".text section not found")


def _bytes_at_rva(data: bytes, rva: int, n: int) -> bytes:
    _ib, va, raw = _pe_text(data)
    return data[raw + (rva - va) : raw + (rva - va) + n]


def _lzss_decompress(path: Path) -> bytes:
    import sys

    sys.path.insert(0, str(ROOT))
    from editor_utils.lzss import lzss_decompress_dat

    return lzss_decompress_dat(path.read_bytes())


def _learn(buf: bytes, rec: int, skill: int) -> int:
    return buf[rec * REC + 176 + skill]


def _kon(buf: bytes, rec: int, skill: int) -> int:
    off = rec * REC + (273 + skill) * 2
    return int.from_bytes(buf[off : off + 2], "little", signed=True)


def _span(skill_buf: bytes, skill: int) -> int:
    off = skill * 94 + 45 * 2
    return int.from_bytes(skill_buf[off : off + 2], "little", signed=True)


def _ai_usable(warpc: bytes, skill_buf: bytes, rec: int, learn_from: int) -> int:
    equip = [
        int.from_bytes(warpc[rec * REC + i * 2 : rec * REC + i * 2 + 2], "little", signed=True)
        for i in (82, 83, 84, 85)
    ]
    total = 0
    for parent in equip:
        if parent < 0:
            continue
        sp = _span(skill_buf, parent)
        if sp > 0:
            for skill in range(parent + 1, min(parent + 1 + sp, 350)):
                if _learn(warpc, learn_from, skill) >= 20 and _kon(warpc, rec, skill) > 0:
                    total += 1
        else:
            if _kon(warpc, rec, parent) > 0:
                total += 1
    return total


class TestSkillExtEnemyBattleMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = _load_patch()
        cls.sites = _sites_by_rva(cls.patch)
        cls.entries = {k: int(v) for k, v in cls.patch.get("cave_entries", {}).items()}

    def test_enemy_memcpy_site_is_hooked(self):
        self.assertIn(
            ENEMY_SITE,
            self.sites,
            "skill_ext_learn_state 必须钩住敌方 memcpy 位点 0x30D24，否则敌方 map[unit] 恒为 0",
        )
        site = self.sites[ENEMY_SITE]
        self.assertEqual(site.get("kind"), "call")
        self.assertEqual(site.get("ref"), "record_battle_map_player")
        self.assertEqual(
            site.get("expect", "").replace(" ", "").upper(),
            MOV_ECX_107.hex().upper(),
        )

    def test_player_and_enemy_sites_share_map_cave(self):
        self.assertEqual(self.sites[PLAYER_SITE].get("ref"), "record_battle_map_player")
        self.assertEqual(self.sites[ENEMY_SITE].get("ref"), "record_battle_map_player")
        self.assertIn("record_battle_map_player", self.entries)

    def test_game_exe_contains_enemy_expect_bytes(self):
        exe = GAME_EXE if GAME_EXE.exists() else FALLBACK_EXE
        if not exe.exists():
            self.skipTest("游戏 EXE 不存在，跳过机器码锚点检查")
        data = exe.read_bytes()
        self.assertEqual(
            _bytes_at_rva(data, ENEMY_SITE, 5),
            MOV_ECX_107,
            f"{exe} RVA 0x{ENEMY_SITE:X} 应为 mov ecx,0x107",
        )
        self.assertEqual(_bytes_at_rva(data, PLAYER_SITE, 5), MOV_ECX_107)

    def test_enemy_ai_skills_collapse_without_map(self):
        if not WARPC.exists() or not TKSKILL.exists():
            self.skipTest("WarPC/TKSkill 数据不存在")
        warpc = _lzss_decompress(WARPC)
        skills = _lzss_decompress(TKSKILL)
        # rec36 是典型敌方模板，技能组装备齐全
        rec = 36
        correct = _ai_usable(warpc, skills, rec, learn_from=rec)
        broken = _ai_usable(warpc, skills, rec, learn_from=0)
        self.assertGreater(correct, 0, "map 正确时敌方应能展开出技能")
        self.assertEqual(
            broken,
            0,
            "map 丢失时误读 WarPC[0]，技能组应全部失效（这正是修复前的现象）",
        )

    def test_learn_reader_semantics_documented(self):
        """cave learn_reader：skill<350 必须走 WarPC[char_id]，依赖 map[unit]=char_id+1。"""
        code = bytes.fromhex(self.patch["cave_code"])
        # learn_reader 入口约在 0x1A00（由 read_menu_mapped 的 call 相对位决定）
        # 校验存在 `cmp edx,350` / `imul eax,eax,0x41E` / WarPC 字段 +0xB0 特征
        self.assertIn(bytes.fromhex("81FA5E010000"), code, "缺少 skill<350 判定 cmp edx,350")
        self.assertIn(bytes.fromhex("69C01E040000"), code, "缺少原版路径 imul eax,1054")
        self.assertIn(bytes.fromhex("05B0000000"), code, "缺少 skill_learn 偏移 +0xB0")


if __name__ == "__main__":
    unittest.main()
