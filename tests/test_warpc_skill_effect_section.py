"""warpc_editor 技能效果判定区 (Tab 4) 构建回归测试。

回归背景: 89aabec 把构建过滤改成 skill_id < max_slots (254), 把原版第 252 槽
「普通攻击」(TKSkill#344 → 字段 525, 游戏普通攻击特殊路径 447DAC 的读取位)
误删。本文件锁定原版语义: 原版 350 条范围 + 位置槽寻址 (槽位 i → 字段 273+i),
与表格模式预设及 batch_skill_learn 的映射保持一致。
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EDITOR_DIR = ROOT / "warpc_editor"
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))


def _load_warpc_module():
    spec = importlib.util.spec_from_file_location(
        "_warpc_effect_section", EDITOR_DIR / "warpc_editor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_warpc_effect_section"] = module
    spec.loader.exec_module(module)
    return module


WARPC = _load_warpc_module()


def _original_like_types():
    """复刻原版 TKSkill.dat 类型分布: type0 = 0..251 与 344..349。"""
    return {i: (0 if (i <= 251 or i >= 344) else 1) for i in range(350)}


class SkillEffectSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = WARPC.WarpcEditorV2()
        self.addCleanup(self.win.deleteLater)
        self.win._skill_types = _original_like_types()
        self.win.skill_names = {}
        self.win.tkkon_names = {}
        self.parent = QWidget()
        QVBoxLayout(self.parent)
        self.addCleanup(self.parent.deleteLater)
        self.win._build_skill_effect_section(self.parent)

    def _name_labels(self):
        return self.parent.findChildren(QLabel)

    def test_normal_attack_present_at_slot_252(self):
        """原版数据下应构建 254 个控件, 槽位 252/253 为技能 344/345。"""
        widgets = self.win._skill_effect_widgets
        self.assertEqual(len(widgets), 254)
        self.assertEqual(
            [slot for slot, _ev in widgets],
            list(range(254)),
            "控件元组必须存位置槽位 (273+slot 寻址), 不是技能编号")
        self.assertEqual(widgets[252][0], 252)

    def test_normal_attack_maps_field_525(self):
        """普通攻击控件的 tooltip 必须指向字段 [525] (游戏特殊读取位)。"""
        hit = [lbl for lbl in self._name_labels()
               if lbl.toolTip().startswith("[525]")]
        self.assertTrue(
            hit, "槽位 252 的普通攻击控件缺失 (tooltip 应为 [525])")
        self.assertEqual(hit[0].text(), "普通攻击")
        first = [lbl for lbl in self._name_labels()
                 if lbl.toolTip().startswith("[273]")]
        self.assertTrue(first, "槽位 0 的 tooltip 应为 [273]")

    def test_extended_skills_not_in_legacy_section(self):
        """扩展指令技能 (>=350) 走附加技能效果判定层, 不进入本区。"""
        types = _original_like_types()
        types[400] = 0
        self.win._skill_types = types
        rebuild = QWidget()
        QVBoxLayout(rebuild)
        self.addCleanup(rebuild.deleteLater)
        self.win._build_skill_effect_section(rebuild)
        self.assertEqual(len(self.win._skill_effect_widgets), 254)

    def test_no_skill_data_placeholder(self):
        """未加载 TKSkill 数据时显示占位提示, 不新增控件 (保留已有控件)。"""
        self.win._skill_types = {}
        before = list(self.win._skill_effect_widgets)
        empty = QWidget()
        QVBoxLayout(empty)
        self.addCleanup(empty.deleteLater)
        self.win._build_skill_effect_section(empty)
        self.assertEqual(len(self.win._skill_effect_widgets), len(before))
        placeholders = [lbl for lbl in empty.findChildren(QLabel)
                        if "TKSkill" in lbl.text()]
        self.assertTrue(placeholders, "应显示 (需要加载 TKSkill.dat 数据) 占位")


if __name__ == "__main__":
    unittest.main()
