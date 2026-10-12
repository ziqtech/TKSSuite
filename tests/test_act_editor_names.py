"""act_editor 名称列回归测试 — _build_act_names 的 TKAct 反向命名。

覆盖:
  - 扩展技能链路自动传导: TKSX 覆盖命名的 TKKon → 对应 TKAct 名称
  - 扩展技能默认效果标签 (TKKon 590) → 对应 TKAct 名称
  - "动画#N"/"空槽-#N" 兜底名不进入名称列 (与 kon_editor 一致),
    未接线的扩展 TKKon 条目不污染 act 名称
  - 原版规模数据行为不变
"""
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor_utils.lzss import lzss_compress_dat  # noqa: E402
from tests.test_kon_name_resolver import (  # noqa: E402
    _make_kon,
    _make_tkskill,
    _make_tksx,
    _make_tkt,
    _make_warpc,
    GAME_EXTENDED_TKKON_DEFAULT,
    GAME_SKILL_BASE,
)

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _load_module(rel_path: str, mod_name: str):
    """按"脚本运行"路径约定加载编辑器模块 (同 tests/test_editor_smoke.py)。"""
    file_path = ROOT / rel_path
    editor_dir = str(file_path.parent)
    if editor_dir not in sys.path:
        sys.path.insert(0, editor_dir)
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


class ActEditorNameTests(unittest.TestCase):
    """ActEditor._build_act_names — TKAct 索引 → 名称 反向映射。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.mod = _load_module("act_editor/act_editor.py",
                               "_test_act_editor")

    def _build_names(self, d: Path) -> dict[int, str]:
        # _build_act_names 不依赖实例状态, 以 unbound 方式调用
        return self.mod.ActEditorV2._build_act_names(None, str(d), 3)

    def _write_game_dir(self, d: Path, *, with_sidecar: bool,
                        kon590_act: int | None = None,
                        two_kons_same_act: bool = False) -> None:
        """合成含扩展技能 (350/351) 的游戏目录。

        kon 655: tkact_id=30, 有数据; TKSX 覆盖 劉備(角色1)技能350→655。
        two_kons_same_act: 追加 kon 656 (tkact_id=30, 關羽技能351覆盖),
        用于验证同 act 多来源名称的拼接格式。
        kon 590: tkact_id 按 kon590_act 设置 (默认效果条目)。
        """
        (d / 'TKT.dat').write_bytes(_make_tkt({
            1001: '劉備', 1002: '關羽', 3001: '火球術',
        }))
        (d / 'TKSkill.dat').write_bytes(_make_tkskill({
            350: (3001, 0), 351: (3001, 0),
        }))
        (d / 'WarPC.dat').write_bytes(_make_warpc(
            {1: {'name_id': 1001}, 2: {'name_id': 1002}}))
        kon_acts = {655: 30}
        if two_kons_same_act:
            kon_acts[656] = 30
        if kon590_act is not None:
            kon_acts[GAME_EXTENDED_TKKON_DEFAULT] = kon590_act
        # tkact 写在字节偏移 6 (tkact_id 字段); 另给这些条目非零
        # exec_mode 让它们成为"有数据"条目
        raw = bytearray((max(kon_acts) + 1) * 40)
        for idx, tkact in kon_acts.items():
            struct.pack_into('<h', raw, idx * 40 + 6, tkact)
            struct.pack_into('<h', raw, idx * 40, 0x0100)
        (d / 'TKKon.dat').write_bytes(lzss_compress_dat(bytes(raw)))
        if with_sidecar:
            overrides = [(1, GAME_SKILL_BASE, 655)]
            if two_kons_same_act:
                overrides.append((2, GAME_SKILL_BASE + 1, 656))
            (d / 'WarPC.dat.tksx').write_bytes(_make_tksx(
                actor_count=3, ext_skill_count=2, overrides=overrides))

    def test_extended_override_names_act(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_game_dir(d, with_sidecar=True)
            names = self._build_names(d)
            # 扩展技能覆盖链路: TKSX → kon 655 → act 30
            self.assertEqual(names.get(30), '劉備《火球術》')

    def test_multi_source_names_joined_single_line(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_game_dir(d, with_sidecar=True,
                                 two_kons_same_act=True)
            names = self._build_names(d)
            # 同 act 的两个来源: 空格连接成单行, 不换行
            self.assertEqual(names.get(30),
                             '劉備《火球術》 關羽《火球術》')
            self.assertNotIn('\n', names.get(30, ''))

    def test_unwired_extended_kon_pollutes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_game_dir(d, with_sidecar=False)
            names = self._build_names(d)
            # 无覆盖时 kon 655 兜底名 "动画#30" 被过滤, act 30 保持无名
            self.assertNotIn(30, names)

    def test_default_label_flows_to_act(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_game_dir(d, with_sidecar=True, kon590_act=7)
            names = self._build_names(d)
            self.assertEqual(names.get(7),
                             '扩展技能默认效果(技能350..351)')

    def test_original_scale_never_labels_or_pollutes(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_game_dir(d, with_sidecar=False, kon590_act=7)
            # TKSkill 未扩容: kon 590 是普通未引用条目 → 兜底名被过滤
            (d / 'TKSkill.dat').write_bytes(_make_tkskill({0: (0, 1)}))
            names = self._build_names(d)
            self.assertNotIn(7, names)
            self.assertNotIn(30, names)

    def test_original_data_names_unchanged(self):
        base = Path(os.environ.get("TKS_GAME_DIR", "."))
        if not (base / 'TKKon.dat').is_file():
            self.skipTest("需要原版游戏目录 (可用 TKS_GAME_DIR 指定)")
        names = self._build_names(base)
        # 原版数据零 "动画#" 噪声, 过滤后行为与旧版一致
        self.assertTrue(names)
        for act_idx, nm in names.items():
            self.assertNotIn('\n', nm, f"act {act_idx} 名称含换行: {nm!r}")
            self.assertFalse(nm.startswith(('空槽-', '动画#')),
                             f"act {act_idx} 出现兜底名: {nm!r}")
        # 抽查已知映射
        self.assertEqual(names.get(0), '主角《空手攻擊》')


class DisplayNameFallbackTests(unittest.TestCase):
    """ActEditor._display_name — 名称列兜底显示。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.mod = _load_module("act_editor/act_editor.py",
                               "_test_act_editor_display")

    def _dn(self, idx, resolved, has_data):
        return self.mod.ActEditorV2._display_name(idx, resolved, has_data)

    def test_resolved_name_passthrough(self):
        self.assertEqual(self._dn(644, '張繡《攻擊》', True), '張繡《攻擊》')
        self.assertEqual(self._dn(528, '鬼將《火 焰 術》', True),
                         '鬼將《火 焰 術》')

    def test_empty_entry_shows_placeholder(self):
        self.assertEqual(self._dn(100, '', False), '空槽')
        self.assertEqual(self._dn(100, '任意名', False), '空槽')

    def test_extended_entry_without_name(self):
        self.assertEqual(self._dn(650, '', True), '新增')
        self.assertEqual(self._dn(653, '', True), '新增')

    def test_original_unused_slots_keep_unknown(self):
        for idx in (640, 641, 642):
            self.assertEqual(self._dn(idx, '', True), '未知')

    def test_unreferenced_entry_gets_explicit_placeholder(self):
        """非空且未被任何 TKKon 引用的原版范围条目: 显示明确占位而非空白。

        回归背景: 用户在 ACT 645 放了新动画并接好 WarPC 普攻 → TKKon 645,
        但 TKKon 645 的 tkact_id 仍是模板默认 528, 名称列空白被误读为
        "大于649的数据名称解析失败"。
        """
        self.assertEqual(self._dn(645, '', True), '(未被TKKon引用)')
        self.assertEqual(self._dn(300, '', True), '(未被TKKon引用)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
