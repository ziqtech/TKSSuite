# -*- coding: utf-8 -*-
"""生成启动器 (离线烧录) 对 16:9 宽屏补丁 (patch_sites) 的支持。

历史问题: `_populate_patch_list` 只枚举 cave_hook / fixed_layout_cave /
patch_bytes / patch_imm32 / 配置驱动 / patch_data_expand, **没有 patch_sites**,
于是宽屏补丁被判为"暂不支持"、根本不出现在列表里 (而收集侧 `_get_selected_patches`
其实早已支持) → 用户无法把 16:9 宽屏烧录进 exe。
"""
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
GAME_DIR = Path(os.environ.get("TKS_GAME_DIR", r"游戏目录（原版）"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tks_launcher_gui") not in sys.path:
    sys.path.insert(0, str(ROOT / "tks_launcher_gui"))

from PySide6.QtCore import QEventLoop, QThread, QTimer, Qt        # noqa: E402
from PySide6.QtGui import QCloseEvent                            # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest                      # noqa: E402
from PySide6.QtWidgets import (                                 # noqa: E402
    QFileDialog, QLabel, QLineEdit, QMessageBox,
)
from core.config_loader import PatchDef                         # noqa: E402
from core.exe_builder import ExeBuilder                         # noqa: E402
from core.mod_distribution import ModBuildWorkspace             # noqa: E402
from core.mod_loader import ModInfo, allowed_mod_configs         # noqa: E402
from core.tkspatch_loader import load_patch_directory            # noqa: E402
from editor_utils.lzss import (                                 # noqa: E402
    lzss_compress_dat, lzss_decompress_dat,
)
from ui.generate_exe_dialog import (                            # noqa: E402
    GenerateExeDialog, file_build_label,
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
            dlg._game_edit.setText(str(GAME_DIR))
            for patch_id in ("tkitem_expand", "tkshop_expand"):
                patch = next(p for p in patches if p.id == patch_id)
                self.assertIsNone(
                    dlg._build_data_section(patch),
                    f"{patch_id} 不应改动原版大小数据")
        finally:
            dlg.close()
            dlg.deleteLater()


class GenerateDistributionDialogTests(unittest.TestCase):
    """仅使用合成 PE/MOD，覆盖真实异步整合、烧录、发布；绝不运行 EXE。"""

    def setUp(self):
        self.app = _qt_app()
        temporary = tempfile.TemporaryDirectory(prefix="tks_dialog_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original" / "TKS.exe"
        self.source.parent.mkdir()
        self.launcher = self.root / "launcher"
        self.launcher.mkdir()
        self.output = self.source.parent / "dist" / "TKS_MOD.exe"
        self.original_exe = self._minimal_pe()
        self.source.write_bytes(self.original_exe)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        (self.baseline / "TKS.exe").write_bytes(self.original_exe)
        (self.source.parent / "FONT9696").write_bytes(b"ORIGINAL-FONT")
        (self.source.parent / "untouched.dat").write_bytes(b"UNCHANGED")
        self.messages = {}
        for name in ("question", "information", "warning", "critical"):
            mocked = patch.object(QMessageBox, name, return_value=QMessageBox.Yes)
            self.messages[name] = mocked.start()
            self.addCleanup(mocked.stop)
        opener = patch("ui.generate_exe_dialog.QDesktopServices.openUrl")
        self.open_url = opener.start()
        self.addCleanup(opener.stop)
        self.addCleanup(self.open_url.assert_not_called)

    @staticmethod
    def _minimal_pe():
        """单 .text 节 PE32；0x220 的唯一模式供真实 ExeBuilder 匹配。"""
        data = bytearray(0x400)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<HHIIIHH", data, 0x84,
                         0x14C, 1, 0, 0, 0, 0xE0, 0x102)
        opt = 0x98
        struct.pack_into("<H", data, opt, 0x10B)
        struct.pack_into("<I", data, opt + 4, 0x200)
        struct.pack_into("<III", data, opt + 16, 0x1000, 0x1000, 0)
        struct.pack_into("<III", data, opt + 28, 0x400000, 0x1000, 0x200)
        struct.pack_into("<HH", data, opt + 40, 4, 0)
        struct.pack_into("<HH", data, opt + 48, 4, 0)
        struct.pack_into("<II", data, opt + 56, 0x2000, 0x200)
        struct.pack_into("<H", data, opt + 68, 3)
        struct.pack_into("<IIII", data, opt + 72,
                         0x100000, 0x1000, 0x100000, 0x1000)
        struct.pack_into("<I", data, opt + 92, 16)
        struct.pack_into("<8sIIIIIIHHI", data, opt + 0xE0,
                         b".text", 0x200, 0x1000, 0x200, 0x200,
                         0, 0, 0, 0, 0x60000020)
        data[0x220:0x226] = bytes.fromhex("B8 11 22 33 44 C3")
        return bytes(data)

    @staticmethod
    def _byte_patch():
        return PatchDef(
            id="synthetic_bytes", name="合成字节补丁", type="patch_bytes",
            pattern="B8 11 22 33 44 C3", replace={1: 0x66}, expect_count=1)

    def _make_mod(self, *, warpc=False, configs=None, resources=None):
        metadata = {
            "format": "TKSMOD", "id": "synthetic_mod", "name": "合成模组",
            "version": "1.2.3", "components": [],
            "resources": [{"file": "resources/FONT9696", "target": "FONT9696"}],
        }
        members = {"resources/FONT9696": b"MOD-FONT"}
        for target, content in (resources or {}).items():
            member = f"resources/{target}"
            metadata["resources"].append({"file": member, "target": target})
            members[member] = content
        if warpc:
            self.original_warpc = lzss_compress_dat(b"\0" * 1054)
            (self.source.parent / "WarPC.dat").write_bytes(self.original_warpc)
            metadata["components"].append({
                "file": "data/WarPC.json", "target": "WarPC.dat"})
            members["data/WarPC.json"] = json.dumps({
                "record_size": 1054, "field_type": "int16",
                "modified": [{"index": 0, "fields": {"f1": 17}}],
                "appended": [{"index": 2, "fields": {"f0": 234}}],
            })
        for name, config in (configs or {}).items():
            members[f"configs/{name}.json"] = json.dumps(config)
        archive = self.root / "synthetic.tksmod"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("mod.json", json.dumps(metadata))
            for name, content in members.items():
                stream.writestr(name, content)
        return ModInfo(
            path=str(archive), mod_id=metadata["id"], name=metadata["name"],
            version=metadata["version"], components=metadata["components"],
            resources=metadata["resources"])

    def _make_compatibility_tool(self):
        current_files = {"ddraw.dll": b"CURRENT-DLL", "ddraw.ini": b"renderer=current\n"}
        tool_files = {"ddraw.dll": b"NEW-TOOL-DLL", "ddraw.ini": b"renderer=new\n",
                      "Shaders/new.glsl": b"new synthetic shader"}
        for name, content in current_files.items():
            (self.source.parent / name).write_bytes(content)
        tool = self.launcher / "tools" / "cnc-ddraw"
        (tool / "Shaders").mkdir(parents=True)
        for name, content in tool_files.items():
            (tool / name).write_bytes(content)
        return current_files, tool_files

    def _dialog(self, patches=(), mods=(), *, fill_baseline=True, **kwargs):
        kwargs.setdefault("source_exe", str(self.source))
        dialog = GenerateExeDialog(
            list(patches), str(self.launcher), selected_mods=list(mods), **kwargs)
        self.addCleanup(self._dispose_dialog, dialog)
        if fill_baseline:
            dialog._baseline_edit.setText(str(self.baseline))
        return dialog

    def _dispose_dialog(self, dialog):
        # 超时或断言失败时也先收束真实线程，并在消息框 mock 撤销前排空信号。
        for name in ("_prepare_worker", "_worker"):
            worker = getattr(dialog, name)
            if worker is not None:
                self.assertTrue(worker.wait(5000), "测试线程未在超时内退出")
                self.app.processEvents()
        dialog._cleanup_workspace()
        dialog._set_build_busy(False)
        dialog.close()
        dialog.deleteLater()

    def _prepare_workspace(self, dialog):
        workspace = ModBuildWorkspace(
            str(Path(dialog._game_edit.text()) / "TKS.exe"),
            str(Path(dialog._out_edit.text()) / "TKS_MOD.exe"), dialog._selected_mods,
            allowed_configs=allowed_mod_configs(SimpleNamespace(patches=dialog._patches)),
            baseline_dir=dialog._baseline_edit.text())
        dialog._workspace = workspace
        workspace.prepare()
        return workspace

    def _assert_unlocked(self, dialog):
        self.assertFalse(dialog._busy)
        for widget in (dialog._paths_group, dialog._baseline_edit,
                       dialog._game_edit, dialog._out_edit, dialog._selection_tabs,
                       dialog._build_btn, dialog._close_btn):
            self.assertTrue(widget.isEnabled())
        self.assertTrue(dialog._progress.isHidden())
        self.assertEqual(dialog._open_btn.isEnabled(), bool(dialog._built_directory))

    def _run_build(self, dialog):
        output_dir = Path(dialog._out_edit.text())

        def input_bytes(directory):
            return {p.relative_to(directory).as_posix(): p.read_bytes()
                    for p in directory.rglob("*")
                    if p.is_file() and not p.is_relative_to(output_dir)}

        before = {directory: input_bytes(directory) for directory in {
            Path(dialog._baseline_edit.text()), Path(dialog._game_edit.text())}}
        dialog._start_build()
        self.assertTrue(dialog._busy, dialog._log_text.toPlainText())
        workspace = dialog._workspace
        staging = Path(workspace.directory)
        self.assertTrue(staging.is_dir())
        loop = QEventLoop()
        check = QTimer()
        check.timeout.connect(lambda: loop.quit() if not dialog._busy else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        check.start(10)
        deadline.start(30000)
        try:
            loop.exec()  # 真实 queued signals；不手动调用任何阶段完成回调。
        finally:
            check.stop()
            deadline.stop()
        self.assertFalse(dialog._busy, "异步构建超时：" + dialog._log_text.toPlainText())
        self.assertTrue(dialog._prepare_worker.isFinished())
        if dialog._worker is not None:
            self.assertTrue(dialog._worker.isFinished())
        self.assertIsNone(dialog._workspace)
        self.assertFalse(staging.exists(), "构建终止后必须清理临时工作区")
        self._assert_unlocked(dialog)
        for directory, content in before.items():
            self.assertEqual(input_bytes(directory), content,
                             f"基准与游戏目录的文件必须保持不变：{directory}")
        return workspace

    def _assert_distribution(self, dialog, workspace, differences):
        output_dir = Path(workspace.output_exe).parent
        self.assertEqual(workspace.files, differences)
        expected = differences | {"TKS_MOD.exe", "tks_build_manifest.json"}
        self.assertEqual({p.relative_to(output_dir).as_posix()
                          for p in output_dir.rglob("*") if p.is_file()}, expected)
        self.assertEqual({Path(p).relative_to(output_dir).as_posix()
                          for p in dialog._worker.output_files}, expected)
        manifest = json.loads((output_dir / "tks_build_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"], sorted(differences | {"TKS_MOD.exe"}))
        self.assertIsNot(dialog._prepare_worker, dialog._worker)
        self.messages["warning"].assert_not_called()
        self.messages["critical"].assert_not_called()
        self.messages["question"].assert_called_once()
        self.assertIn(workspace.baseline_dir, self.messages["question"].call_args.args[2])
        self.messages["information"].assert_called_once()
        message = self.messages["information"].call_args.args[2]
        self.assertIn(f"{len(differences)} 个差异文件", message)
        self.assertIn(f"{len(differences)} 个差异文件", dialog._status_label.text())
        for text in ("TKS_MOD.exe", "清单", str(output_dir), "覆盖到",
                     "与基准目录版本一致的原版", "不能在输出目录单独运行"):
            self.assertIn(text, message)

    def test_source_initializes_game_and_dist_but_not_baseline(self):
        dialog = self._dialog(fill_baseline=False)
        self.assertEqual(dialog._baseline_edit.text(), "")
        self.assertEqual(Path(dialog._game_edit.text()), self.source.parent)
        self.assertEqual(Path(dialog._out_edit.text()), self.output.parent)
        self.assertEqual(dialog._selection_tabs.count(), 2)
        self.assertIn("补丁", dialog._selection_tabs.tabText(0))
        self.assertIn("MOD", dialog._selection_tabs.tabText(1))
        self.assertIn("未勾选 MOD", dialog._mod_list.item(0).text())

    def test_paths_show_only_three_folder_fields_and_difference_guidance(self):
        dialog = self._dialog()
        paths = dialog._paths_group.layout()
        edits = (dialog._baseline_edit, dialog._game_edit, dialog._out_edit)
        self.assertEqual(set(dialog.findChildren(QLineEdit)), set(edits))
        self.assertFalse(hasattr(dialog, "_src_edit"))
        for row, (label, edit) in enumerate(zip(
                ("基准目录", "游戏目录", "输出目录"), edits)):
            widget = paths.itemAtPosition(row, 0).widget()
            self.assertIsInstance(widget, QLabel)
            self.assertEqual(widget.text(), label)
            self.assertIs(paths.itemAtPosition(row, 1).widget(), edit)
            self.assertNotIn("EXE", paths.itemAtPosition(row, 2).widget().text())
        self.assertIn("手动选择原版", dialog._baseline_edit.placeholderText())
        self.assertIn("当前游戏目录", dialog._game_edit.placeholderText())
        self.assertIn("dist", dialog._out_edit.placeholderText())
        self.assertIn("差异文件", paths.itemAtPosition(3, 1).widget().text())
        self.assertIn("仍会比较游戏目录与基准目录", dialog._mod_list.item(0).text())

    def test_omitted_source_leaves_paths_empty_despite_existing_legacy_game(self):
        legacy = self.root / "TKS" / "TKS.exe"
        legacy.parent.mkdir()
        legacy.write_bytes(self.original_exe)
        dialog = self._dialog(source_exe="", fill_baseline=False)
        self.assertEqual(dialog._game_edit.text(), "")
        self.assertEqual(dialog._out_edit.text(), "")
        self.assertEqual(dialog._baseline_edit.text(), "")
        dialog._game_edit.setText(str(legacy.parent))
        self.assertEqual(Path(dialog._out_edit.text()), legacy.parent / "dist")
        self.assertEqual(dialog._baseline_edit.text(), "", "基准始终需要手选")

    def test_editing_game_follows_default_but_preserves_baseline_and_custom_output(self):
        dialog = self._dialog()
        second = self.root / "second"
        dialog._game_edit.selectAll()
        QTest.keyClicks(dialog._game_edit, str(second))
        self.assertEqual(Path(dialog._out_edit.text()), second / "dist")
        self.assertEqual(Path(dialog._baseline_edit.text()), self.baseline)
        manual = self.root / "custom"
        dialog._out_edit.selectAll()
        QTest.keyClicks(dialog._out_edit, str(manual))
        dialog._game_edit.selectAll()
        QTest.keyClicks(dialog._game_edit, str(self.source.parent))
        self.assertEqual(Path(dialog._out_edit.text()), manual)
        dialog._game_edit.clear()
        self.assertEqual(Path(dialog._out_edit.text()), manual)
        dialog._out_edit.clear()
        QTest.keyClicks(dialog._game_edit, str(second))
        self.assertEqual(Path(dialog._out_edit.text()), second / "dist")
        dialog._game_edit.clear()
        self.assertEqual(dialog._out_edit.text(), "")
        self.assertEqual(Path(dialog._baseline_edit.text()), self.baseline)

    def test_three_directory_pickers_and_cancel_preserve_paths(self):
        dialog = self._dialog(fill_baseline=False)
        second = self.root / "second"
        second.mkdir()
        custom = self.root / "custom"
        custom.mkdir()
        edits = (dialog._baseline_edit, dialog._game_edit, dialog._out_edit)
        with patch.object(QFileDialog, "getExistingDirectory") as choose, \
                patch.object(QFileDialog, "getOpenFileName", return_value=("", "")) as open_file, \
                patch.object(QFileDialog, "getSaveFileName", return_value=("", "")) as save_file:
            for row, (edit, directory) in enumerate(zip(edits, (self.baseline, second, custom))):
                with self.subTest(row=row):
                    initial = edit.text() or dialog._game_edit.text()
                    choose.return_value = str(directory)
                    button = dialog._paths_group.layout().itemAtPosition(row, 2).widget()
                    button.click()
                    choose.assert_called_once()
                    self.assertIs(choose.call_args.args[0], dialog)
                    self.assertEqual(choose.call_args.args[2], initial)
                    self.assertEqual(Path(edit.text()), directory)
                    self.assertEqual(Path(dialog._baseline_edit.text()), self.baseline)
                    if row < 2:
                        self.assertEqual(Path(dialog._out_edit.text()),
                                         Path(dialog._game_edit.text()) / "dist")
                    choose.reset_mock()
                    before = tuple(field.text() for field in edits)
                    choose.return_value = ""
                    button.click()
                    choose.assert_called_once()
                    self.assertEqual(tuple(field.text() for field in edits), before)
                    choose.reset_mock()
            open_file.assert_not_called()
            save_file.assert_not_called()

    def test_invalid_directories_are_rejected_before_workspace_or_workers(self):
        empty_game = self.root / "empty_game"
        empty_game.mkdir()
        cases = (
            ("_baseline_edit", "", "基准目录"),
            ("_baseline_edit", "   ", "基准目录"),
            ("_baseline_edit", str(self.root / "missing_baseline"), "基准目录"),
            ("_baseline_edit", str(self.source), "基准目录"),
            ("_game_edit", "", "TKS.exe"),
            ("_game_edit", str(self.root / "missing_game"), "TKS.exe"),
            ("_game_edit", str(self.source), "TKS.exe"),
            ("_game_edit", str(empty_game), "TKS.exe"),
            ("_out_edit", "", "输出目录"),
            ("_out_edit", str(self.source), "输出目录"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                dialog = self._dialog()
                getattr(dialog, field).setText(value)
                self.messages["warning"].reset_mock()
                with patch("ui.generate_exe_dialog.ModBuildWorkspace") as factory, \
                        patch("ui.generate_exe_dialog._PrepareWorker") as prepare, \
                        patch("ui.generate_exe_dialog._BuildWorker") as build:
                    dialog._start_build()
                factory.assert_not_called()
                prepare.assert_not_called()
                build.assert_not_called()
                self.messages["warning"].assert_called_once()
                self.assertIn(message, self.messages["warning"].call_args.args[2])
                self.messages["question"].assert_not_called()
                self.messages["critical"].assert_not_called()
                self.assertIsNone(dialog._workspace)
                self.assertIsNone(dialog._prepare_worker)
                self.assertIsNone(dialog._worker)
                self._assert_unlocked(dialog)
                self.assertFalse(self.output.parent.exists())

    def test_baseline_directory_without_tks_exe_is_rejected_before_workers(self):
        empty_baseline = self.root / "empty_baseline"
        empty_baseline.mkdir()
        dialog = self._dialog()
        dialog._baseline_edit.setText(str(empty_baseline))
        with patch("ui.generate_exe_dialog._PrepareWorker") as prepare, \
                patch("ui.generate_exe_dialog._BuildWorker") as build:
            dialog._start_build()
        prepare.assert_not_called()
        build.assert_not_called()
        self.messages["critical"].assert_called_once()
        self.assertIn("基准目录", self.messages["critical"].call_args.args[2])
        self.assertIn("TKS.exe", self.messages["critical"].call_args.args[2])
        self.messages["question"].assert_not_called()
        self.assertIsNone(dialog._workspace)
        self.assertIsNone(dialog._prepare_worker)
        self.assertIsNone(dialog._worker)
        self._assert_unlocked(dialog)
        self.assertFalse(self.output.parent.exists())

    def test_selected_mod_names_versions_and_targets_are_displayed(self):
        mods = [self._make_mod(warpc=True), ModInfo(
            mod_id="second", name="第二模组", version="2.0", description="只有说明")]
        dialog = self._dialog(mods=mods)
        self.assertEqual(dialog._mod_list.count(), 2)
        self.assertIn("合成模组", dialog._mod_list.item(0).text())
        self.assertIn("1.2.3", dialog._mod_list.item(0).text())
        self.assertEqual(dialog._mod_list.item(0).toolTip().splitlines(),
                         ["FONT9696", "WarPC.dat"])
        self.assertIn("第二模组", dialog._mod_list.item(1).text())
        self.assertEqual(dialog._mod_list.item(1).toolTip(), "只有说明")
        self.assertIn("2", dialog._selection_tabs.tabText(1))

    def test_busy_disables_editing_and_blocks_reject_escape_and_close(self):
        dialog = self._dialog()
        dialog.show()
        rejected = QSignalSpy(dialog.rejected)
        dialog._built_directory = str(self.output.parent)
        dialog._set_build_busy(True)
        for widget in (dialog._paths_group, dialog._baseline_edit,
                       dialog._game_edit, dialog._out_edit,
                       dialog._selection_tabs, dialog._patch_list, dialog._mod_list,
                       dialog._build_btn, dialog._close_btn, dialog._open_btn):
            self.assertFalse(widget.isEnabled())
        self.assertFalse(dialog._progress.isHidden())
        dialog.reject()
        QTest.keyClick(dialog, Qt.Key_Escape)
        event = QCloseEvent()
        dialog.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(dialog.close())
        self.assertTrue(dialog.isVisible())
        self.assertEqual(rejected.count(), 0)
        with patch("ui.generate_exe_dialog.ModBuildWorkspace") as factory:
            dialog._start_build()
            factory.assert_not_called()
        dialog._set_build_busy(False)
        self._assert_unlocked(dialog)
        dialog.reject()
        self.assertEqual(rejected.count(), 1)
        self.assertFalse(dialog.isVisible())

    def test_resolver_reads_game_or_workspace_never_stale_output_or_baseline(self):
        dialog = self._dialog()
        source_data = self.source.parent / "TKMat.Dat"
        source_data.write_bytes(b"SOURCE")
        self.assertEqual(Path(dialog._resolve_data_file("TKMat.Dat")), source_data)
        self.output.parent.mkdir()
        stale = self.output.parent / "TKMat.Dat"
        stale.write_bytes(b"STALE")
        (self.baseline / "TKMat.Dat").write_bytes(b"BASELINE")
        (self.output.parent / "missing.dat").write_bytes(b"STALE-ONLY")
        (self.baseline / "missing.dat").write_bytes(b"BASELINE-ONLY")
        self.assertEqual(Path(dialog._resolve_data_file("TKMat.Dat")), source_data)
        self.assertIsNone(dialog._resolve_data_file("missing.dat"))
        dialog._game_edit.clear()
        self.assertIsNone(dialog._resolve_data_file("TKMat.Dat"))
        dialog._game_edit.setText(str(self.source.parent))
        workspace = self._prepare_workspace(dialog)
        resolved = Path(dialog._resolve_data_file("TKMat.Dat"))
        self.assertNotEqual(resolved, source_data)
        self.assertNotEqual(resolved, stale)
        self.assertTrue(resolved.is_relative_to(workspace.directory))
        self.assertEqual(resolved.read_bytes(), b"SOURCE")
        source_data.write_bytes(b"EDITED-AFTER-PREPARE")
        self.assertEqual(Path(dialog._resolve_data_file("TKMat.Dat")).read_bytes(), b"SOURCE")
        self.assertIsNone(dialog._resolve_data_file("missing.dat"))

    def _config_patch(self):
        config_path = self.launcher / "distribution_settings.json"
        config_path.write_text(json.dumps({"rare_pct": 10}), encoding="utf-8")
        return PatchDef(
            id="synthetic_config", name="合成配置", type="drop_probability",
            json_file=str(config_path), optional=True, mod_config_overridable=True)

    def test_whitelisted_workspace_config_overrides_local_config(self):
        config_patch = self._config_patch()
        override = {"rare_pct": 77}
        mod = self._make_mod(configs={
            "distribution_settings": override, "not_allowed": {"rare_pct": 99}})
        dialog = self._dialog([config_patch], [mod])
        self.assertEqual(dialog._get_selected_patches()[3][0].config, {"rare_pct": 10})
        workspace = self._prepare_workspace(dialog)
        self.assertEqual(workspace.config_overrides, {"distribution_settings": override})
        self.assertEqual(dialog._get_selected_patches()[3][0].config, override)
        self.assertEqual(json.loads(Path(config_patch.json_file).read_text(encoding="utf-8")),
                         {"rare_pct": 10})
        config_patch.mod_config_overridable = False
        with self.assertRaisesRegex(ValueError, "尚未烧录.*distribution_settings"):
            dialog._get_selected_patches()

    def test_unselected_config_patch_aborts_before_confirmation_and_cleans_up(self):
        config_patch = self._config_patch()
        mod = self._make_mod(configs={"distribution_settings": {"rare_pct": 77}})
        dialog = self._dialog([config_patch], [mod], patch_states={config_patch.id: False})
        self._run_build(dialog)
        self.messages["question"].assert_not_called()
        self.messages["critical"].assert_called_once()
        self.assertIn("distribution_settings", self.messages["critical"].call_args.args[2])
        self.assertIsNone(dialog._worker)
        self.assertFalse(self.output.parent.exists())

    def test_expansion_capacity_uses_merged_workspace_not_stale_dist(self):
        mod = self._make_mod(warpc=True)
        self.output.parent.mkdir()
        stale = lzss_compress_dat(b"\0" * (1054 * 7))
        (self.output.parent / "WarPC.dat").write_bytes(stale)
        data_patch = PatchDef(
            id="synthetic_data", name="合成扩容", type="patch_data_expand",
            data_file="WarPC.dat", old_base=0x757F08, old_size=1054,
            section_name=".warpc", needs_lzss=True, activate_if_expanded=True)
        data_patch._extra = {}  # 与 parse_patch_dict 载入后的定义一致。
        size_patch = PatchDef(
            id="synthetic_size", name="合成容量", type="patch_imm32",
            pattern="B8 11 22 33 44", value_offset=1, expect_count=1,
            new_value_expr="{warpc_new_size}")
        dialog = self._dialog([data_patch, size_patch], [mod])
        workspace = self._prepare_workspace(dialog)
        merged = Path(workspace.resolve_file("WarPC.dat"))
        self.assertNotEqual(merged.parent, self.output.parent)
        self.assertNotEqual(merged.parent, self.source.parent)
        items = dialog._get_selected_patches()
        self.assertEqual(dialog._read_data_file_size("warpc_new_size"), 1054 * 3)
        self.assertEqual(items[2][0].new_value, 1054 * 3)
        data = items[4][0]
        self.assertEqual(data.logical_size, 1054 * 3)
        self.assertEqual(data.backing_size, 0x10000)
        self.assertEqual(struct.unpack_from("<h", data.data, 2)[0], 17)
        self.assertEqual(struct.unpack_from("<h", data.data, 1054 * 2)[0], 234)
        self.assertEqual((self.output.parent / "WarPC.dat").read_bytes(), stale)
        self.assertEqual((self.source.parent / "WarPC.dat").read_bytes(), self.original_warpc)

    def test_shipped_skill_bundle_detects_merged_data_before_burning(self):
        mod = self._make_mod()
        original = lzss_compress_dat(bytes(350 * 94))
        (self.source.parent / "TKSkill.dat").write_bytes(original)
        (self.source.parent / "WarPC.dat").write_bytes(lzss_compress_dat(bytes(143 * 1054)))
        with zipfile.ZipFile(mod.path) as stream:
            members = {name: stream.read(name) for name in stream.namelist()}
        metadata = json.loads(members["mod.json"])
        metadata["components"].append({"target": "TKSkill.dat", "file": "data/skill.json"})
        members["mod.json"] = json.dumps(metadata).encode()
        members["data/skill.json"] = json.dumps({
            "record_size": 94, "field_type": "int16", "modified": [],
            "appended": [{"index": 350, "fields": {"f0": 123}}],
        }).encode()
        with zipfile.ZipFile(mod.path, "w") as stream:
            for name, data in members.items():
                stream.writestr(name, data)
        self.output.parent.mkdir()
        stale = lzss_compress_dat(bytes(698 * 94))
        (self.output.parent / "TKSkill.dat").write_bytes(stale)
        bundle_ids = {"tkskill_size", "tkskill_expand", "tksave_expand",
                      "warpc_base_refs", "warpc_size_refs"}
        patches = [p for p in _load_patches() if p.id in bundle_ids]
        dialog = self._dialog(patches, [mod],
                              patch_states=dict.fromkeys(bundle_ids, False))
        workspace = self._prepare_workspace(dialog)
        items = dialog._get_selected_patches()
        self.assertTrue(bundle_ids <= set(dialog._last_build_patch_ids))
        skill = next(p for p in items[4] if p.patch_id == "tkskill_expand.table")
        self.assertEqual(skill.logical_size, 65536)
        self.assertEqual(struct.unpack_from("<h", skill.data, 350 * 94)[0], 123)
        self.assertEqual(len(lzss_decompress_dat(Path(workspace.resolve_file("TKSkill.dat")).read_bytes())),
                         351 * 94)
        self.assertEqual((self.source.parent / "TKSkill.dat").read_bytes(), original)
        self.assertEqual((self.output.parent / "TKSkill.dat").read_bytes(), stale)

    def test_themes_keep_patch_list_and_log_readable_at_minimum_size(self):
        from editor_utils.theme_switcher import apply_theme_to_window
        dialog = self._dialog([self._byte_patch()])
        for theme in ("gpt-dark", "gpt-light", "classic-dark", "classic-light"):
            with self.subTest(theme=theme):
                apply_theme_to_window(dialog, theme, persist=False)
                dialog.resize(dialog.minimumSize())
                dialog.show()
                self.app.processEvents()
                self.assertGreaterEqual(dialog._patch_list.height(), 90)
                self.assertGreaterEqual(dialog._log_text.height(), 100)
                self.assertTrue(dialog._build_btn.isVisible())
                for row in range(3):
                    for column in range(3):
                        widget = dialog._paths_group.layout().itemAtPosition(row, column).widget()
                        self.assertTrue(widget.isVisible())
                        self.assertTrue(dialog.rect().contains(
                            widget.mapTo(dialog, widget.rect().topLeft())))
                        self.assertTrue(dialog.rect().contains(
                            widget.mapTo(dialog, widget.rect().bottomRight())))

    def test_cancel_after_prepare_unlocks_and_cleans_workspace(self):
        dialog = self._dialog([self._byte_patch()], [self._make_mod()])
        self.messages["question"].return_value = QMessageBox.No
        self._run_build(dialog)
        self.messages["question"].assert_called_once()
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_not_called()
        self.assertIsNone(dialog._worker)
        self.assertIn("取消", dialog._status_label.text())
        self.assertFalse(self.output.parent.exists())

    def test_prepare_failure_unlocks_and_cleans_workspace(self):
        mod = self._make_mod()
        Path(mod.path).write_bytes(b"not a zip archive")
        dialog = self._dialog([self._byte_patch()], [mod])
        self._run_build(dialog)
        self.messages["question"].assert_not_called()
        self.messages["critical"].assert_called_once()
        self.assertIsNone(dialog._worker)
        self.assertIn("失败", dialog._status_label.text())
        self.assertFalse(self.output.parent.exists())

    def test_real_qt_threads_build_patch_mod_data_resources_and_tool(self):
        mod = self._make_mod(warpc=True)
        tool = self.launcher / "tools" / "cnc-ddraw"
        (tool / "Shaders").mkdir(parents=True)
        tool_files = {"ddraw.dll": b"SYNTHETIC-DLL", "ddraw.ini": b"test=1",
                      "Shaders/x.glsl": b"synthetic shader"}
        for name, content in tool_files.items():
            (tool / name).write_bytes(content)
        dialog = self._dialog([self._byte_patch()], [mod], selected_tool="cnc-ddraw")
        logs = QSignalSpy(dialog.log_emitted)
        threads = {}
        real_prepare = ModBuildWorkspace.prepare
        real_build = ExeBuilder.build
        real_publish = ModBuildWorkspace.publish

        def prepare(workspace):
            threads["prepare"] = QThread.currentThread()
            return real_prepare(workspace)

        def build(builder, *args, **kwargs):
            threads["build"] = QThread.currentThread()
            return real_build(builder, *args, **kwargs)

        def publish(workspace, *args, **kwargs):
            threads["publish"] = QThread.currentThread()
            return real_publish(workspace, *args, **kwargs)

        def confirm(*_args):
            threads["confirm"] = QThread.currentThread()
            self.assertFalse(self.output.parent.exists(), "确认前不应发布任何文件")
            return QMessageBox.Yes

        def finished(*_args):
            threads["finished"] = QThread.currentThread()
            return QMessageBox.Ok

        self.messages["question"].side_effect = confirm
        self.messages["information"].side_effect = finished
        with patch.object(ModBuildWorkspace, "prepare", autospec=True, side_effect=prepare), \
                patch.object(ExeBuilder, "build", autospec=True, side_effect=build) as burner, \
                patch.object(ModBuildWorkspace, "publish", autospec=True, side_effect=publish) as publisher:
            self._run_build(dialog)
        burner.assert_called_once()
        publisher.assert_called_once()
        self.assertEqual(threads["prepare"], dialog._prepare_worker)
        self.assertEqual(threads["build"], dialog._worker)
        self.assertEqual(threads["publish"], dialog._worker)
        self.assertNotEqual(threads["prepare"], self.app.thread())
        self.assertNotEqual(threads["build"], self.app.thread())
        self.assertEqual(threads["confirm"], self.app.thread())
        self.assertEqual(threads["finished"], self.app.thread())
        self.assertGreater(logs.count(), 0)
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_called_once()
        expected = bytearray(self.original_exe)
        expected[0x221] = 0x66
        self.assertEqual(self.output.read_bytes(), bytes(expected))
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"MOD-FONT")
        merged = lzss_decompress_dat((self.output.parent / "WarPC.dat").read_bytes())
        self.assertEqual(len(merged), 1054 * 3)
        self.assertEqual(struct.unpack_from("<h", merged, 2)[0], 17)
        self.assertEqual(struct.unpack_from("<h", merged, 1054 * 2)[0], 234)
        self.assertEqual((self.source.parent / "WarPC.dat").read_bytes(), self.original_warpc)
        self.assertEqual({p.name for p in self.source.parent.iterdir() if p.name != "dist"},
                         {"TKS.exe", "FONT9696", "WarPC.dat", "untouched.dat"},
                         "原版目录不能产生 MOD 备份或其它运行残留")
        for name, content in tool_files.items():
            self.assertEqual((self.output.parent / name).read_bytes(), content)
        self.assertFalse((self.output.parent / "TKS.exe").exists())
        self.assertEqual((self.output.parent / "untouched.dat").read_bytes(), b"UNCHANGED")
        self.assertTrue(dialog._open_btn.isEnabled())
        self.assertIn("生成完成", dialog._status_label.text())

    def test_real_qt_threads_compare_merged_bytes_not_timestamps(self):
        added = {"assets/new.dat": b"MOD-ADDED"}
        mod = self._make_mod(warpc=True, resources=added)
        for source in self.source.parent.iterdir():
            baseline = self.baseline / source.name
            baseline.write_bytes(source.read_bytes())
            os.utime(baseline, (1_000_000_000, 1_000_000_000))
            os.utime(source, (1_000_000_100, 1_000_000_100))
        self.assertNotEqual((self.baseline / "untouched.dat").stat().st_mtime_ns,
                            (self.source.parent / "untouched.dat").stat().st_mtime_ns)
        baseline_data = self.baseline / "manual.dat"
        game_data = self.source.parent / "manual.dat"
        baseline_data.write_bytes(b"ORIGINAL")
        game_data.write_bytes(b"MODIFIED")
        for path in (baseline_data, game_data):
            os.utime(path, (1_000_000_000, 1_000_000_000))
        self.assertEqual(baseline_data.stat().st_size, game_data.stat().st_size)
        self.assertEqual(baseline_data.stat().st_mtime_ns, game_data.stat().st_mtime_ns)
        (self.baseline / "baseline_only.dat").write_bytes(b"NOT-GAME-DATA")
        dialog = self._dialog([self._byte_patch()], [mod])
        prepared_files = []

        def confirm(*_args):
            prepared_files.append(set(dialog._workspace.files))
            return QMessageBox.Yes

        self.messages["question"].side_effect = confirm
        workspace = self._run_build(dialog)
        differences = {"FONT9696", "WarPC.dat", "manual.dat", *added}
        self.assertEqual(prepared_files, [differences])
        self._assert_distribution(dialog, workspace, differences)
        expected_exe = bytearray(self.original_exe)
        expected_exe[0x221] = 0x66
        self.assertEqual(self.output.read_bytes(), bytes(expected_exe))
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"MOD-FONT")
        self.assertEqual((self.output.parent / "manual.dat").read_bytes(), b"MODIFIED")
        for name, content in added.items():
            self.assertEqual((self.output.parent / name).read_bytes(), content)
            self.assertFalse((self.source.parent / name).exists())
            self.assertFalse((self.baseline / name).exists())
        merged = lzss_decompress_dat((self.output.parent / "WarPC.dat").read_bytes())
        self.assertEqual(len(merged), 1054 * 3)
        self.assertEqual(struct.unpack_from("<h", merged, 2)[0], 17)
        self.assertEqual(struct.unpack_from("<h", merged, 1054 * 2)[0], 234)

    def test_same_baseline_and_game_without_mods_exports_only_exe_and_manifest(self):
        real_build = ExeBuilder.build
        for burn_patch in (False, True):
            with self.subTest(burn_patch=burn_patch):
                for message in self.messages.values():
                    message.reset_mock()
                dialog = self._dialog([self._byte_patch()] if burn_patch else [])
                dialog._baseline_edit.setText(str(self.source.parent))
                with patch.object(ExeBuilder, "build", autospec=True,
                                  side_effect=real_build) as burner:
                    workspace = self._run_build(dialog)
                self.assertEqual(burner.call_count, int(burn_patch))
                self.assertEqual(Path(workspace.baseline_dir), self.source.parent)
                self._assert_distribution(dialog, workspace, set())
                self.assertIn("0 个差异文件", self.messages["question"].call_args.args[2])
                expected_exe = bytearray(self.original_exe)
                if burn_patch:
                    expected_exe[0x221] = 0x66
                self.assertEqual(self.output.read_bytes(), bytes(expected_exe))

    def test_build_uses_edited_game_and_output_directories(self):
        game = self.root / "selected_game"
        game.mkdir()
        selected_exe = bytearray(self.original_exe)
        selected_exe[0x221] = 0x77
        (game / "TKS.exe").write_bytes(selected_exe)
        (game / "selected.dat").write_bytes(b"SELECTED-GAME")
        output = self.root / "custom_distribution"
        dialog = self._dialog(source_exe=str(self.source.parent / "other_selected.exe"))
        self.assertEqual(Path(dialog._game_edit.text()), self.source.parent)
        dialog._game_edit.selectAll()
        QTest.keyClicks(dialog._game_edit, str(game))
        dialog._out_edit.selectAll()
        QTest.keyClicks(dialog._out_edit, str(output))
        workspace = self._run_build(dialog)
        self.assertEqual(Path(workspace.source_exe), game / "TKS.exe")
        self.assertEqual(Path(workspace.output_exe), output / "TKS_MOD.exe")
        self.assertEqual(Path(workspace.baseline_dir), self.baseline)
        self._assert_distribution(dialog, workspace, {"selected.dat"})
        self.assertEqual((output / "TKS_MOD.exe").read_bytes(), bytes(selected_exe))
        self.assertEqual((output / "selected.dat").read_bytes(), b"SELECTED-GAME")
        self.assertFalse(self.output.parent.exists())
        self.assertEqual(self.source.read_bytes(), self.original_exe)

    def test_final_tool_comparison_updates_differences_and_success_count(self):
        _, tool_files = self._make_compatibility_tool()
        for source in self.source.parent.iterdir():
            (self.baseline / source.name).write_bytes(source.read_bytes())
        (self.baseline / "ddraw.dll").write_bytes(tool_files["ddraw.dll"])
        dialog = self._dialog(selected_tool="cnc-ddraw")
        prepared_files = []

        def confirm(*_args):
            prepared_files.append(set(dialog._workspace.files))
            return QMessageBox.Yes

        self.messages["question"].side_effect = confirm
        workspace = self._run_build(dialog)
        self.assertEqual(prepared_files, [{"ddraw.dll"}])
        self.assertIn("1 个差异文件", self.messages["question"].call_args.args[2])
        differences = {"ddraw.ini", "Shaders/new.glsl"}
        self._assert_distribution(dialog, workspace, differences)
        self.assertEqual(self.output.read_bytes(), self.original_exe)
        for name in differences:
            self.assertEqual((self.output.parent / name).read_bytes(), tool_files[name])

    def test_mod_only_build_outputs_unchanged_exe_and_mod_resource(self):
        dialog = self._dialog(mods=[self._make_mod()])
        with patch.object(ExeBuilder, "build", autospec=True) as burner:
            self._run_build(dialog)
        burner.assert_not_called()
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_called_once()
        self.assertEqual(self.output.read_bytes(), self.original_exe)
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"MOD-FONT")
        self.assertEqual((self.output.parent / "untouched.dat").read_bytes(), b"UNCHANGED")

    def test_pure_export_keeps_already_edited_data_and_excludes_backups(self):
        edited = {
            "WarPC.dat": lzss_compress_dat(b"\x11\x00" + bytes(1052)),
            "WarPC.dat.tksx": b"TKSX-ALREADY-EDITED\0\xff",
        }
        for name, content in edited.items():
            (self.source.parent / name).write_bytes(content)
            (self.source.parent / (name + ".bak")).write_bytes(b"BEFORE-EDIT")
        before = {p.name: p.read_bytes() for p in self.source.parent.iterdir()}
        dialog = self._dialog()
        with patch.object(ExeBuilder, "build", autospec=True) as burner:
            workspace = self._run_build(dialog)
        burner.assert_not_called()
        self.assertIsNotNone(dialog._worker)
        self.assertIsNot(dialog._prepare_worker, dialog._worker)
        self.messages["question"].assert_called_once()
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_called_once()
        self.assertEqual(self.output.read_bytes(), self.original_exe)
        self.assertEqual(workspace.files, set(edited) | {"FONT9696", "untouched.dat"})
        for name in workspace.files:
            self.assertEqual((self.output.parent / name).read_bytes(), before[name])
        for name in edited:
            self.assertFalse((self.output.parent / (name + ".bak")).exists())
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.source.parent.iterdir() if p.name != "dist"},
            before)

    def test_pure_export_without_selected_tool_keeps_current_dll_and_ini(self):
        current_files, _ = self._make_compatibility_tool()
        before = {p.name: p.read_bytes() for p in self.source.parent.iterdir()}
        dialog = self._dialog(selected_tool="")
        self.assertTrue(dialog._copy_tool_cb.isEnabled())
        self.assertEqual(dialog._tool_combo.currentText(), "cnc-ddraw")
        self.assertFalse(dialog._copy_tool_cb.isChecked())
        self.assertFalse(dialog._tool_combo.isEnabled())
        self._run_build(dialog)
        self.assertIsNotNone(dialog._worker)
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_called_once()
        self.assertEqual(self.output.read_bytes(), self.original_exe)
        for name, content in current_files.items():
            self.assertEqual((self.output.parent / name).read_bytes(), content)
        self.assertFalse((self.output.parent / "Shaders").exists())
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.source.parent.iterdir() if p.name != "dist"},
            before)

    def test_pure_export_with_selected_tool_defaults_to_final_tool_files(self):
        _, tool_files = self._make_compatibility_tool()
        before = {p.name: p.read_bytes() for p in self.source.parent.iterdir()}
        dialog = self._dialog(selected_tool="cnc-ddraw")
        self.assertTrue(dialog._copy_tool_cb.isChecked())
        self.assertTrue(dialog._tool_combo.isEnabled())
        self.assertEqual(dialog._tool_combo.currentText(), "cnc-ddraw")
        self._run_build(dialog)
        self.assertIsNotNone(dialog._worker)
        self.messages["critical"].assert_not_called()
        self.messages["information"].assert_called_once()
        self.assertEqual(self.output.read_bytes(), self.original_exe)
        for name, content in tool_files.items():
            self.assertEqual((self.output.parent / name).read_bytes(), content)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.source.parent.iterdir() if p.name != "dist"},
            before)

    def test_pattern_mismatch_never_publishes_or_changes_existing_dist(self):
        bad_patch = self._byte_patch()
        bad_patch.pattern = "DE AD BE EF"
        dialog = self._dialog([bad_patch], [self._make_mod()])
        self.output.parent.mkdir()
        self.output.write_bytes(b"PREVIOUS-EXE")
        (self.output.parent / "FONT9696").write_bytes(b"PREVIOUS-FONT")
        before = {p.name: p.read_bytes() for p in self.output.parent.iterdir()}
        with patch.object(ModBuildWorkspace, "publish", autospec=True) as publisher:
            self._run_build(dialog)
        publisher.assert_not_called()
        self.messages["critical"].assert_called_once()
        self.messages["information"].assert_not_called()
        self.assertIn("字节补丁应用失败", self.messages["critical"].call_args.args[2])
        self.assertEqual({p.name: p.read_bytes() for p in self.output.parent.iterdir()}, before)

    def test_publish_failure_unlocks_and_cleans_workspace(self):
        dialog = self._dialog([self._byte_patch()], [self._make_mod()])
        with patch.object(ModBuildWorkspace, "publish", autospec=True,
                          side_effect=OSError("合成发布失败")) as publisher:
            self._run_build(dialog)
        publisher.assert_called_once()
        self.messages["critical"].assert_called_once()
        self.assertIn("合成发布失败", self.messages["critical"].call_args.args[2])
        self.messages["information"].assert_not_called()
        self.assertFalse(self.output.parent.exists())


if __name__ == "__main__":
    unittest.main()
