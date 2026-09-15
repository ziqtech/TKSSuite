# -*- coding: utf-8 -*-
"""生成启动器 (离线烧录) 对 16:9 宽屏补丁 (patch_sites) 的支持。

历史问题: `_populate_patch_list` 只枚举 cave_hook / fixed_layout_cave /
patch_bytes / patch_imm32 / 配置驱动 / patch_data_expand, **没有 patch_sites**,
于是宽屏补丁被判为"暂不支持"、根本不出现在列表里 (而收集侧 `_get_selected_patches`
其实早已支持) → 用户无法把 16:9 宽屏烧录进 exe。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tks_launcher_gui") not in sys.path:
    sys.path.insert(0, str(ROOT / "tks_launcher_gui"))

from core.tkspatch_loader import load_patch_directory          # noqa: E402
from ui.generate_exe_dialog import (                            # noqa: E402
    GenerateExeDialog, copy_tool_dir, file_build_label,
)


def _is_ascii_word(s: str) -> bool:
    return s.isascii() and any(c.isalpha() for c in s)


_QT_APP = None      # 模块级强引用: 防止 QApplication 被回收


def _qt_app():
    global _QT_APP
    from PySide6.QtWidgets import QApplication
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _load_patches():
    cfg = load_patch_directory(str(ROOT / "tks_launcher_gui" / "patches"),
                               log_func=lambda *_a: None)
    return list(cfg.patches)


class GenerateExeSupportTests(unittest.TestCase):
    """补丁能否被"生成启动器"离线烧录。"""

    def test_widescreen_patch_sites_supported(self):
        p = next(x for x in _load_patches() if x.id == "widescreen_16_9")
        self.assertEqual(p.type, "patch_sites")
        self.assertEqual(file_build_label(p), '位点表(宽屏)',
                         "16:9 宽屏 (patch_sites) 必须被列为可烧录")

    def test_patch_sites_without_cave_is_unsupported(self):
        class _Dummy:
            type = 'patch_sites'
            sites = [{"rva": "0x10", "expect": "90", "kind": "call", "ref": "x"}]
            cave_code = ""
            cave_code_file = None

            def __getattr__(self, name):     # 其余字段视为缺省
                return None

        self.assertIsNone(file_build_label(_Dummy()),
                          "带 call 位点但没有 cave 代码时不应列为可烧录")

    def test_imm32_multi_pattern_supported(self):
        """patch_imm32 的"多模式表"形态 (patterns 数组) 也必须可离线烧录。

        历史问题: `file_build_label` 只判了 `p.pattern` / `p.value_scan`, 漏了
        `p.patterns` —— 而 `_get_selected_patches` 一直支持多模式, 于是 gold_limit
        (三处锚定, 各自 value_offset/value_size 不同) 被误报"暂不支持"。
        """
        p = next(x for x in _load_patches() if x.id == "gold_limit")
        self.assertTrue(p.patterns and not p.pattern)
        self.assertEqual(file_build_label(p), '立即数(多模式)')
        # 单模式 / 值扫描 两种旧形态不受影响
        self.assertEqual(file_build_label(
            next(x for x in _load_patches() if x.id == "tkdefunit_count")), '立即数')
        self.assertEqual(file_build_label(
            next(x for x in _load_patches() if x.id == "tkitem_expand")),
            '数据段注入')
        self.assertEqual(file_build_label(
            next(x for x in _load_patches() if x.id == "tkshop_expand")),
            '数据段注入')

    def test_dialog_collects_gold_limit_and_detail_is_chinese(self):
        """对话框: gold_limit 进列表且可收集 3 条锚定; 每行详情"类型"是中文。"""
        from PySide6.QtCore import Qt
        _qt_app()
        patches = _load_patches()
        dlg = GenerateExeDialog(patches, str(ROOT / "tks_launcher_gui"),
                                patch_states={"gold_limit": True},
                                selected_tool="cnc-ddraw")
        try:
            # 列表里能找到且标注为 多模式
            hit = None
            for i in range(dlg._patch_list.count()):
                it = dlg._patch_list.item(i)
                p = it.data(Qt.UserRole)
                if p is not None and p.id == "gold_limit":
                    hit = it
                    break
            self.assertIsNotNone(hit, "gold_limit 必须出现在可烧录列表里")
            self.assertIn('立即数(多模式)', hit.text())
            self.assertEqual(dlg._summary_label.text().split('（')[0].strip(),
                             f'可烧录: {len(patches)}/{len(patches)} 个补丁')

            # 逐行详情: "类型"行必须带中文标签 (不再直接打印内部英文名)
            leaks = []
            for i in range(dlg._patch_list.count()):
                dlg._patch_list.setCurrentRow(i)
                lines = [ln for ln in dlg._patch_detail.toPlainText().splitlines()
                         if ln.startswith('类型')]
                self.assertTrue(lines, f'第 {i} 行详情缺『类型』行')
                label = lines[0].split(':', 1)[1].strip()
                if label.startswith('(') or _is_ascii_word(label.split('(')[0].strip()):
                    leaks.append((i, label))
            self.assertEqual(leaks, [], f"详情框仍在显示英文类型: {leaks}")

            # 收集结果: gold_limit 3 条锚定, value_offset/value_size 各自保留
            (_caves, _bytes, imm32, _cfg, _data, _fixed, _sites) = \
                dlg._get_selected_patches()
            gold = next(x for x in imm32 if x.patch_id == "gold_limit")
            self.assertEqual(gold.new_value, 0xFFFF)
            self.assertEqual([(e.value_offset, e.value_size) for e in gold.entries],
                             [(1, 4), (1, 4), (7, 2)])
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_dialog_lists_and_collects_widescreen(self):
        from PySide6.QtCore import Qt
        _qt_app()
        patches = _load_patches()
        dlg = GenerateExeDialog(patches, str(ROOT / "tks_launcher_gui"),
                                patch_states={"widescreen_16_9": True},
                                selected_tool="cnc-ddraw")
        try:
            hit = None
            for i in range(dlg._patch_list.count()):
                item = dlg._patch_list.item(i)
                p = item.data(Qt.UserRole)
                if p is not None and p.id == "widescreen_16_9":
                    hit = item
                    break
            self.assertIsNotNone(hit, "宽屏补丁必须出现在生成启动器列表中")
            self.assertIn('位点表', hit.text())
            self.assertEqual(hit.checkState(), Qt.Checked,
                             "launcher 已勾选的宽屏补丁应默认勾选")
            (caves, bytes_p, imm32, config, data, fixed, sites) = \
                dlg._get_selected_patches()
            ws = [s for s in sites if s.patch_id == "widescreen_16_9"]
            self.assertEqual(len(ws), 1, "勾选后必须收集到一条 sites 补丁")
            item = ws[0]
            self.assertGreater(len(item.sites), 0)
            self.assertGreater(len(item.cave_code), 0, "cave 代码必须随补丁一起带上")
            self.assertTrue(item.globals_ph_base and item.globals_alloc_size,
                            "globals 数据槽区声明必须透传 (宽屏 cave 依赖)")
        finally:
            # 只销毁对话框: 不 processEvents()——会触发全局主题/自适应列的延迟回调,
            # 在测试里对已销毁控件重新布局 (libshiboken RuntimeError)。
            dlg.close()
            dlg.deleteLater()

    @unittest.skipUnless(
        (GAME_DIR / "TKItem.dat").is_file()
        and (GAME_DIR / "TKShop.dat").is_file(),
        "需要原版 TKItem.dat / TKShop.dat 才能验证原版数据不触发扩容",
    )
    def test_original_data_does_not_activate_expansion(self):
        _qt_app()
        patches = _load_patches()
        dlg = GenerateExeDialog(patches, str(ROOT / "tks_launcher_gui"),
                                selected_tool="cnc-ddraw")
        try:
            dlg._out_edit.setText(str(GAME_DIR))
            dlg._src_edit.setText(str(GAME_DIR))
            for patch_id in ("tkitem_expand", "tkshop_expand"):
                patch = next(p for p in patches if p.id == patch_id)
                self.assertIsNone(
                    dlg._build_data_section(patch),
                    f"{patch_id} 不应改动原版大小数据")
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_copy_tool_dir(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "tools" / "cnc-ddraw"
            (src / "Shaders").mkdir(parents=True)
            (src / "ddraw.dll").write_bytes(b"NEW-DLL")
            (src / "ddraw.ini").write_text("cfg", encoding="utf-8")
            (src / "Shaders" / "x.glsl").write_text("shader", encoding="utf-8")
            out = Path(td) / "out"
            out.mkdir()
            (out / "ddraw.dll").write_bytes(b"OLD-DLL")     # 旧文件应被备份
            logs = []
            n = copy_tool_dir(str(src), str(out), log=logs.append)
            self.assertEqual(n, 3)
            self.assertEqual((out / "ddraw.dll").read_bytes(), b"NEW-DLL")
            self.assertEqual((out / "ddraw.dll.toolbak").read_bytes(), b"OLD-DLL")
            self.assertEqual((out / "Shaders" / "x.glsl").read_text(encoding="utf-8"),
                             "shader")
            # 再次复制: 内容相同则不再产生新备份
            logs2 = []
            copy_tool_dir(str(src), str(out), log=logs2.append)
            self.assertFalse(any('备份' in m for m in logs2),
                             "内容相同不应反复备份")


if __name__ == "__main__":
    unittest.main()
