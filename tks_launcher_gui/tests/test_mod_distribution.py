"""自造 ZIP 与二进制数据验证隔离整合，不依赖游戏安装或启动 CLI。"""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_utils.grp_codec import decode_section, encode_section
from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat
from tks_launcher_gui.core import mod_distribution as distribution
from tks_launcher_gui.core.mod_distribution import ModBuildWorkspace
from tks_launcher_gui.core.mod_loader import ModInfo


MANIFEST = "tks_build_manifest.json"


def zip_bytes(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, json.dumps(value) if isinstance(value, dict) else value)
    return output.getvalue()


def text_data(entries):
    ids, offsets, text = bytearray(), bytearray(), bytearray()
    for number, value in entries.items():
        ids.extend(struct.pack("<i", number))
        offsets.extend(struct.pack("<I", len(text)))
        text.extend(value.encode("big5") + b"\0")
    data = ids + offsets + text
    return struct.pack("<II", len(data), len(entries)) + bytes(v ^ 255 for v in data)


def read_text(data):
    size, count = struct.unpack_from("<II", data)
    plain = bytes(v ^ 255 for v in data[8:8 + size])
    result = {}
    for i in range(count):
        number = struct.unpack_from("<i", plain, i * 4)[0]
        offset = struct.unpack_from("<I", plain, count * 4 + i * 4)[0]
        result[number] = plain[count * 8 + offset:].split(b"\0", 1)[0].decode("big5")
    return result


def record_diff(value, index=0):
    return {"field_type": "int16", "record_size": 1054,
            "modified": [{"index": index, "fields": {"f0": value}}], "appended": []}


def block_entry(index, data):
    return {"index": index, "data_b64": base64.b64encode(data).decode("ascii")}


def tree(path, exclude_dist=False):
    result = {}
    if not path.exists():
        return result
    for item in path.rglob("*"):
        name = item.relative_to(path).as_posix()
        if exclude_dist and name.split("/")[0].lower() == "dist":
            continue
        result[name] = None if item.is_dir() else item.read_bytes()
    return result


class ModBuildWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="test_mod_distribution_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        self.packages = self.root / "packages"
        self.game.mkdir()
        self.packages.mkdir()
        self.source = self.game / "TKS.exe"
        self.source.write_bytes(b"MZ-original-executable")
        (self.game / "WarPC.dat").write_bytes(lzss_compress_dat(bytes(1054 * 2)))
        (self.game / "TKSkill.dat").write_bytes(lzss_compress_dat(bytes(94 * 2)))
        (self.game / "TKT.dat").write_bytes(text_data({1: "Old", 2: "Keep"}))
        (self.game / "SC.GRP").write_bytes(b"aabb")
        (self.game / "SC.IDX").write_bytes(struct.pack("<III", 0, 2, 4))
        (self.game / "FONT9696").write_bytes(b"old-font")
        (self.game / "Sound").mkdir()
        (self.game / "Sound" / "theme.mp3").write_bytes(b"old-music")
        (self.game / "unrelated.bin").write_bytes(b"do-not-copy")
        self.output = self.game / "dist" / "launcher.exe"
        self.logs = []
        self.serial = 0

    def mod(self, mod_id="mod", diffs=None, resources=None, configs=None,
            attributes=None, missing=(), extra=None):
        self.serial += 1
        members = {}
        metadata = {"format": "TKSMOD", "id": mod_id, "name": mod_id,
                    "components": [], "resources": []}
        for i, (target, diff) in enumerate((diffs or {}).items()):
            member = f"data/{i}.json"
            metadata["components"].append({"target": target, "file": member})
            members[member] = diff
        for i, (target, data) in enumerate((resources or {}).items()):
            member = f"resources/{i}.bin"
            metadata["resources"].append({"target": target, "file": member})
            members[member] = data
        for name, value in (configs or {}).items():
            members[f"configs/{name}.json"] = value
        metadata.update(attributes or {})
        members["mod.json"] = metadata
        members.update(extra or {})
        for name in missing:
            members.pop(name, None)
        path = self.packages / f"{self.serial}.tksmod"
        path.write_bytes(zip_bytes(members))
        return ModInfo(path=str(path), mod_id="stale-cache", config_files={"stale": 1})

    def workspace(self, mods=(), output=None, allowed=None):
        work = ModBuildWorkspace(str(self.source), str(output or self.output), list(mods),
                                 allowed_configs=allowed, log_func=self.logs.append)
        self.addCleanup(work.cleanup)
        return work

    def build(self, work, value=b"MZ-burned-executable"):
        work.prepare()
        Path(work.build_exe).write_bytes(value)

    def assert_failed_prepare(self, mods, pattern=None):
        before = tree(self.game)
        work = self.workspace(mods)
        with self.assertRaisesRegex(Exception, pattern or ".+"):
            work.prepare()
        self.assertEqual(work.files, set())
        self.assertEqual(work.config_overrides, {})
        with self.assertRaises(RuntimeError):
            work.publish([])
        with self.assertRaises(RuntimeError):
            work.resolve_file("WarPC.dat")
        self.assertEqual(tree(self.game), before)
        return work

    def test_compressed_text_grp_and_full_resources_publish_without_touching_original(self):
        original = tree(self.game)
        war = record_diff(321)
        war["appended"] = [{"index": 3, "fields": {"f2": 456}}]
        skill = record_diff(87, 2)
        skill["record_size"] = 94
        mod = self.mod(diffs={
            "WarPC.dat": war, "TKSkill.dat": skill,
            "TKT.dat": {"modified": {"1": "New"}, "appended": {"3": "Added"}, "deleted": ["2"]},
            "SC.GRP": {"patch_type": "block_diff", "block_type": "grp_section",
                       "modified": [block_entry(0, b"changed")],
                       "appended": [block_entry(2, b"new")], "deleted_indices": []},
        }, resources={"FONT9696": b"new-font", "Sound/theme.mp3": b"new-music",
                      "new/sub/resource.xyz": b"new-resource"})
        work = self.workspace([mod])
        self.assertFalse(self.output.parent.exists())
        self.assertEqual(list(Path(work.directory).iterdir()), [])
        self.build(work)
        self.assertEqual(tree(self.game), original)
        self.assertEqual(work.files, {"WarPC.dat", "TKSkill.dat", "TKT.dat", "SC.GRP", "SC.IDX",
                                      "FONT9696", "Sound/theme.mp3", "new/sub/resource.xyz"})
        war_data = lzss_decompress_dat(Path(work.resolve_file("warpc.DAT")).read_bytes())
        self.assertEqual(len(war_data), 1054 * 4)
        self.assertEqual(struct.unpack_from("<h", war_data)[0], 321)
        self.assertEqual(struct.unpack_from("<h", war_data, 1054 * 3 + 4)[0], 456)
        skill_data = lzss_decompress_dat(Path(work.resolve_file("TKSkill.dat")).read_bytes())
        self.assertEqual(len(skill_data), 94 * 3)
        self.assertEqual(struct.unpack_from("<h", skill_data, 94 * 2)[0], 87)
        self.assertEqual(read_text(Path(work.resolve_file("TKT.dat")).read_bytes()), {1: "New", 3: "Added"})
        self.assertEqual(Path(work.resolve_file("SC.GRP")).read_bytes(), b"changedbbnew")
        self.assertEqual(struct.unpack("<IIII", Path(work.resolve_file("SC.IDX")).read_bytes()), (0, 7, 9, 12))
        self.assertFalse((Path(work.directory) / "data" / "unrelated.bin").exists())
        output_files = work.publish([])
        self.assertTrue(all(os.path.isabs(n) for n in output_files))
        self.assertEqual(self.output.read_bytes(), b"MZ-burned-executable")
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"new-font")
        self.assertEqual((self.output.parent / "Sound/theme.mp3").read_bytes(), b"new-music")
        manifest = json.loads((self.output.parent / MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), work.files | {self.output.name})
        self.assertFalse(any(n.endswith((".orig", ".mod_orig", ".mod_new")) for n in tree(self.output.parent)))
        self.assertEqual(tree(self.game, exclude_dist=True), original)

    def test_full_resource_wins_after_differences_and_patch_resources(self):
        replacement = lzss_compress_dat(bytes([5]) * 1054)
        mod = self.mod(diffs={"WarPC.dat": record_diff(9)}, resources={"WarPC.dat": replacement})
        work = self.workspace([mod])
        self.build(work)
        self.assertEqual(Path(work.resolve_file("WarPC.dat")).read_bytes(), replacement)
        work.publish([("warpc.dat", str(self.root / "nonexistent"))])
        self.assertEqual((self.output.parent / "WarPC.dat").read_bytes(), replacement)
        self.assertTrue(any("暂存 MOD" in message for message in self.logs))

    def test_selected_only_reload_dependency_order_and_deselection(self):
        first = self.mod("base", resources={"same.bin": b"base"}, attributes={"load_order": 999})
        last = self.mod("dependent", resources={"SAME.bin": b"dependent"},
                        attributes={"dependencies": ["base"], "load_order": 0})
        ignored = self.mod("ignored", resources={"not-selected.bin": b"ignored"})
        ignored.enabled = False
        work = self.workspace([last, first, ignored])
        self.build(work)
        self.assertEqual(Path(work.resolve_file("same.bin")).read_bytes(), b"dependent")
        self.assertNotIn("not-selected.bin", work.files)
        self.assertTrue(any("后加载" in message for message in self.logs))
        work.publish([])
        work2 = self.workspace([first])
        self.build(work2)
        work2.publish([])
        self.assertEqual((self.output.parent / "same.bin").read_bytes(), b"base")
        self.assertIsNone(work2.resolve_file("not-selected.bin"))

    def test_load_order_and_config_whitelist_are_reloaded(self):
        early = self.mod("early", resources={"value.bin": b"early"},
                         configs={"custom": {"v": 1}, "drop_probability": {"v": 0}},
                         attributes={"load_order": 1})
        late = self.mod("late", resources={"value.bin": b"late"}, configs={"custom": {"v": 2}},
                        attributes={"load_order": 200})
        work = self.workspace([late, early], allowed={"custom"})
        work.prepare()
        self.assertEqual(work.config_overrides, {"custom": {"v": 2}})
        self.assertEqual(Path(work.resolve_file("value.bin")).read_bytes(), b"late")
        empty = self.workspace([early], allowed=set())
        empty.prepare()
        self.assertEqual(empty.config_overrides, {})

    def test_pak_expansion_resources_and_root_config(self):
        first = self.mod("pak-a", resources={"Sound/a.ogg": b"pak-a"}, configs={"custom": {"v": "child"}})
        second = self.mod("pak-b", resources={"FONT9696": b"pak-font"},
                          attributes={"dependencies": ["pak-a"]})
        pak = self.packages / "selected.tksmodpak"
        pak.write_bytes(zip_bytes({"mod.json": {"id": "pak"}, "a.tksmod": Path(first.path).read_bytes(),
                                   "b.tksmod": Path(second.path).read_bytes(),
                                   "configs/custom.json": {"v": "root"}}))
        work = self.workspace([ModInfo(path=str(pak))], allowed={"custom"})
        self.build(work)
        self.assertEqual(work.config_overrides, {"custom": {"v": "root"}})
        self.assertEqual(Path(work.resolve_file("Sound/a.ogg")).read_bytes(), b"pak-a")
        work.publish([])
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"pak-font")
        empty = self.workspace()
        self.build(empty)
        empty.publish([])
        self.assertFalse((self.output.parent / "FONT9696").exists())
        self.assertFalse((self.output.parent / "Sound/a.ogg").exists())

    def test_duplicate_missing_dependency_cycle_and_explicit_conflict_abort(self):
        cases = [
            [self.mod("same"), self.mod("same")],
            [self.mod("dependent", attributes={"dependencies": ["missing"]})],
            [self.mod("a", attributes={"dependencies": ["b"]}), self.mod("b", attributes={"dependencies": ["a"]})],
            [self.mod("x", attributes={"conflicts": ["y"]}), self.mod("y")],
        ]
        for mods in cases:
            with self.subTest(paths=[m.path for m in mods]):
                self.assert_failed_prepare(mods)

    def test_missing_components_resources_and_invalid_config_abort(self):
        cases = [
            self.mod(diffs={"WarPC.dat": record_diff(1)}, missing=["data/0.json"]),
            self.mod(resources={"new.bin": b"new"}, missing=["resources/0.bin"]),
            self.mod(configs={"drop_probability": b"not-json"}),
            self.mod(missing=["mod.json"]),
            self.mod(attributes={"components": [{"target": "WarPC.dat", "file": ""}]}),
        ]
        for mod in cases:
            with self.subTest(path=mod.path):
                self.assert_failed_prepare([mod])

    def test_pak_bad_child_cannot_partially_succeed(self):
        good = self.mod("good", resources={"valid.bin": b"valid"})
        pak = self.packages / "broken.tksmodpak"
        pak.write_bytes(zip_bytes({"mod.json": {}, "a.tksmod": Path(good.path).read_bytes(),
                                   "b.tksmod": zip_bytes({"mod.json": {"format": "WRONG"}})}))
        self.assert_failed_prepare([ModInfo(path=str(pak))])

    def test_missing_original_or_idx_is_fatal_even_with_replacement(self):
        for target in ("WarPC.dat", "TKSkill.dat", "SC.IDX"):
            with self.subTest(target=target):
                path = self.game / target
                saved = path.read_bytes()
                path.unlink()
                if target == "SC.IDX":
                    diffs = {"SC.GRP": {"patch_type": "block_diff", "modified": [block_entry(0, b"x")]}}
                else:
                    diffs = {target: record_diff(10)}
                self.assert_failed_prepare([self.mod(diffs=diffs, resources={target: b"replacement"})])
                path.write_bytes(saved)

    def test_unsafe_windows_targets_members_and_resolve_names_abort(self):
        names = ["../outside", "a/../../outside", "/absolute", "C:/absolute", "C:drive",
                 "\\\\server\\share", "Sound\\..\\escape", "a:stream", "NUL.txt", "COM1", "LPT¹.bin",
                 "a/CON/child", "file.", "file ", "a//b", "a/./b", "x\x00y", "bad?.bin",
                 "WarPC.dat.orig", "x.MOD_ORIG", "x.mod_new", "x.toolbak", "x.bak", MANIFEST]
        work = self.workspace()
        work.prepare()
        for name in names:
            with self.subTest(name=name):
                self.assert_failed_prepare([self.mod(resources={name: b"x"})])
                with self.assertRaises(ValueError):
                    work.resolve_file(name)
        self.assert_failed_prepare([self.mod(extra={"../unused.bin": b"unused"})])
        self.assert_failed_prepare([self.mod(attributes={"resources": [{"target": "safe.bin", "file": "../bad"}]})])

    def test_source_residual_markers_are_not_restored_or_deleted(self):
        mod = self.mod(diffs={"WarPC.dat": record_diff(1)})
        for target in ("TKS.exe", "WarPC.dat"):
            for suffix in (".orig", ".mod_orig", ".mod_new", ".toolbak", ".expanded"):
                with self.subTest(target=target, suffix=suffix):
                    marker = self.game / (target + suffix)
                    marker.write_bytes(b"recovery-data")
                    self.assert_failed_prepare([mod], "运行残留")
                    marker.unlink()
        grp = self.mod(diffs={"SC.GRP": {"patch_type": "block_diff", "modified": [block_entry(0, b"x")]}})
        (self.game / "SC.IDX.orig").write_bytes(b"backup")
        self.assert_failed_prepare([grp], "运行残留")

    def test_resolve_prefers_staging_then_original_never_existing_dist(self):
        self.output.parent.mkdir()
        (self.output.parent / "only-in-dist.bin").write_bytes(b"stale")
        (self.output.parent / "WarPC.dat").write_bytes(b"stale")
        work = self.workspace([self.mod(resources={"FONT9696": b"font"})])
        work.prepare()
        self.assertEqual(work.resolve_file("WarPC.dat"), str(self.game / "WarPC.dat"))
        self.assertIsNone(work.resolve_file("only-in-dist.bin"))
        self.assertEqual(Path(work.resolve_file("FONT9696")).read_bytes(), b"font")
        with self.assertRaises(ValueError):
            work.resolve_file("dist/WarPC.dat")
        (self.game / "WarPC.dat.orig").write_bytes(b"leftover")
        with self.assertRaisesRegex(ValueError, "运行残留"):
            work.resolve_file("WarPC.dat")

    def test_exe_replacement_is_build_input_not_unburned_distribution(self):
        original = tree(self.game)
        work = self.workspace([self.mod(resources={"TKS.exe": b"MZ-modded", "FONT9696": b"font"})])
        work.prepare()
        self.assertNotEqual(work.source_exe, str(self.source))
        self.assertEqual(Path(work.source_exe).read_bytes(), b"MZ-modded")
        self.assertNotIn("TKS.exe", work.files)
        self.assertNotEqual(work.source_exe, work.build_exe)
        Path(work.build_exe).write_bytes(b"MZ-patched-modded")
        work.publish([])
        self.assertFalse((self.output.parent / "TKS.exe").exists())
        self.assertEqual(self.output.read_bytes(), b"MZ-patched-modded")
        self.assertEqual(tree(self.game, exclude_dist=True), original)
        same_name = self.workspace([self.mod(resources={"TKS.exe": b"MZ-modded"})],
                                   output=self.game / "dist" / "named" / "tks.EXE")
        self.build(same_name)
        same_name.publish([])
        self.assertCountEqual(os.listdir(Path(same_name.output_exe).parent), ["tks.EXE", MANIFEST])

    def test_publish_patch_resources_and_recursive_tools(self):
        tool_dir = self.root / "tools"
        (tool_dir / "bin").mkdir(parents=True)
        (tool_dir / "bin/tool.exe").write_bytes(b"tool")
        (tool_dir / "settings.ini").write_bytes(b"settings")
        resource = self.root / "patch.dat"
        resource.write_bytes(b"patch-resource")
        original = tree(self.game)
        work = self.workspace()
        self.build(work)
        work.publish([("nested/patch.dat", str(resource))], str(tool_dir))
        self.assertEqual((self.output.parent / "bin/tool.exe").read_bytes(), b"tool")
        self.assertEqual((self.output.parent / "nested/patch.dat").read_bytes(), b"patch-resource")
        self.assertEqual(tree(self.game, exclude_dist=True), original)

    def test_mod_tool_exe_and_manifest_collisions_abort(self):
        collision = self.workspace([self.mod(resources={"launcher.exe": b"unburned"})])
        self.build(collision)
        with self.assertRaisesRegex(ValueError, "同名冲突"):
            collision.publish([])
        tools = self.root / "tools"
        tools.mkdir()
        work = self.workspace([self.mod(resources={"shared.bin": b"mod"})])
        self.build(work)
        for name in ("shared.bin", "LAUNCHER.exe", MANIFEST, "file.orig", "TKS.exe"):
            with self.subTest(name=name):
                path = tools / name
                path.write_bytes(b"tool")
                with self.assertRaises(ValueError):
                    work.publish([], str(tools))
                path.unlink()
        self.assertFalse(self.output.parent.exists())
        self.assert_failed_prepare([self.mod(resources={"a": b"x", "a/child": b"y"})])

    def test_republish_removes_only_previously_manifested_files(self):
        first = self.workspace([self.mod(resources={"old.bin": b"old", "Sound/generated.ogg": b"old"})])
        self.build(first)
        first.publish([])
        unrelated = self.output.parent / "user-save.dat"
        unrelated.write_bytes(b"unrelated")
        unknown_dir = self.output.parent / "user-folder"
        unknown_dir.mkdir()
        second = self.workspace([self.mod(resources={"new.bin": b"new"})])
        self.build(second, b"MZ-second")
        second.publish([])
        second.publish([])
        self.assertFalse((self.output.parent / "old.bin").exists())
        self.assertFalse((self.output.parent / "Sound/generated.ogg").exists())
        self.assertTrue(unknown_dir.is_dir())
        self.assertEqual(unrelated.read_bytes(), b"unrelated")
        self.assertEqual(self.output.read_bytes(), b"MZ-second")
        self.assertEqual(json.loads((self.output.parent / MANIFEST).read_text())["files"], ["launcher.exe", "new.bin"])

    def test_republish_preserves_requested_exe_case_and_removes_old_exe_name(self):
        first = self.workspace()
        self.build(first)
        first.publish([])
        renamed = self.workspace(output=self.output.with_name("LAUNCHER.exe"))
        self.build(renamed)
        renamed.publish([])
        self.assertIn("LAUNCHER.exe", os.listdir(self.output.parent))
        self.assertNotIn("launcher.exe", os.listdir(self.output.parent))
        other = self.workspace(output=self.output.with_name("other.exe"))
        self.build(other)
        other.publish([])
        self.assertFalse(self.output.exists())
        self.assertTrue((self.output.parent / "other.exe").exists())

    def test_old_manifest_windows_separators_are_normalized(self):
        first = self.workspace([self.mod(resources={"nested/old.bin": b"old"})])
        self.build(first)
        first.publish([])
        manifest = self.output.parent / MANIFEST
        manifest.write_text(json.dumps({"version": 1, "files": ["launcher.exe", "nested\\old.bin"]}))
        second = self.workspace()
        self.build(second)
        second.publish([])
        self.assertFalse((self.output.parent / "nested/old.bin").exists())

    def test_invalid_old_manifest_is_not_trusted(self):
        self.output.parent.mkdir()
        victim = self.game / "unrelated.bin"
        manifest = self.output.parent / MANIFEST
        work = self.workspace()
        self.build(work)
        for value in ({"version": 1, "files": ["../unrelated.bin"]},
                      {"version": 1, "files": [str(victim)]},
                      {"version": 1, "files": ["x.mod_new"]},
                      {"version": 1, "files": [MANIFEST]},
                      {"version": 1, "files": ["a", "A"]},
                      {"version": 1, "files": ["a", "a/b"]}, {"files": []}, []):
            with self.subTest(value=value):
                manifest.write_text(json.dumps(value))
                before = tree(self.game)
                with self.assertRaisesRegex(ValueError, "清单无效"):
                    work.publish([])
                self.assertEqual(tree(self.game), before)

    def test_copy_failures_do_not_modify_existing_dist(self):
        old = self.workspace()
        self.build(old)
        old.publish([])
        before = tree(self.game)
        work = self.workspace([self.mod(resources={"new.bin": b"new"})])
        self.build(work)
        with self.assertRaises(FileNotFoundError):
            work.publish([("missing.bin", str(self.root / "missing"))])
        self.assertEqual(tree(self.game), before)
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "bad.dll").write_bytes(b"bad")
        copyfile = shutil.copyfile

        def fail_tool(source, destination, *args, **kwargs):
            if Path(source).name == "bad.dll":
                raise OSError("模拟工具复制失败")
            return copyfile(source, destination, *args, **kwargs)

        with patch.object(distribution.shutil, "copyfile", side_effect=fail_tool):
            with self.assertRaisesRegex(OSError, "工具复制失败"):
                work.publish([], str(tools))
        self.assertEqual(tree(self.game), before)

    def test_tool_traversal_errors_and_unsafe_patch_paths_are_fatal(self):
        tools = self.root / "tools"
        tools.mkdir()
        work = self.workspace()
        self.build(work)

        def failed_walk(path, onerror):
            onerror(PermissionError("模拟工具目录不可读"))
            return iter(())

        with patch.object(distribution.os, "walk", side_effect=failed_walk):
            with self.assertRaisesRegex(PermissionError, "不可读"):
                work.publish([], str(tools))
        for name in ("../outside", "NUL", "resource:stream", MANIFEST, "x.mod_new", "launcher.exe", "TKS.exe"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    work.publish([(name, str(self.source))])
        self.assertFalse(self.output.parent.exists())

    def test_publish_failure_rolls_back_overwrites_deletions_and_created_directories(self):
        old = self.workspace([self.mod(resources={"a-old.bin": b"old", "shared.bin": b"before"})])
        self.build(old, b"MZ-before")
        old.publish([])
        (self.output.parent / "unknown.bin").write_bytes(b"unknown")
        before = tree(self.game)
        work = self.workspace([self.mod(resources={"shared.bin": b"after", "new/nested.bin": b"new"})])
        self.build(work, b"MZ-after")
        replace = os.replace
        failed = []

        def fail_manifest(source, destination):
            if Path(destination).name == MANIFEST and Path(source).name.startswith("new_") and not failed:
                failed.append(True)
                raise OSError("模拟清单发布失败")
            return replace(source, destination)

        with patch.object(distribution.os, "replace", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "清单发布失败"):
                work.publish([])
        self.assertTrue(failed)
        self.assertEqual(tree(self.game), before)
        work.publish([])
        self.assertEqual(self.output.read_bytes(), b"MZ-after")
        self.assertFalse((self.output.parent / "a-old.bin").exists())

    def test_first_publish_failure_removes_new_dist_directories(self):
        work = self.workspace(output=self.game / "dist" / "nested" / "launcher.exe")
        self.build(work)
        before = tree(self.game)
        replace = os.replace

        def fail_new(source, destination):
            if Path(source).name.startswith("new_"):
                raise OSError("模拟首次发布失败")
            return replace(source, destination)

        with patch.object(distribution.os, "replace", side_effect=fail_new):
            with self.assertRaises(OSError):
                work.publish([])
        self.assertEqual(tree(self.game), before)

    def test_original_hardlinks_are_never_written_through(self):
        self.output.parent.mkdir()
        os.link(self.source, self.output)
        os.link(self.game / "FONT9696", self.output.parent / "FONT9696")
        original = tree(self.game, exclude_dist=True)
        work = self.workspace([self.mod(resources={"FONT9696": b"new-font"})])
        self.build(work)
        work.publish([])
        self.assertEqual(tree(self.game, exclude_dist=True), original)
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"new-font")
        self.assertFalse(os.path.samefile(self.source, self.output))

    def test_output_location_checks_and_cleanup(self):
        for output in (self.source, self.game / "new.exe", self.root / "new.exe",
                       self.game / "Sound" / "new.exe", self.game / "DistOther/new.exe"):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    self.workspace(output=output)
        for output in (self.game / "dist/nested/new.exe", self.root / "separate/new.exe"):
            with self.subTest(output=output):
                work = self.workspace(output=output)
                directory = Path(work.directory)
                self.assertTrue(directory.is_dir())
                self.assertFalse(output.parent.exists())
                self.build(work)
                work.publish([])
                self.assertTrue(output.is_file())
                work.cleanup()
                self.assertFalse(directory.exists())
        with self.assertRaises(ValueError):
            ModBuildWorkspace("relative.exe", str(self.output), [])

    def symlink(self, source, destination, is_dir=False):
        try:
            os.symlink(source, destination, target_is_directory=is_dir)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"当前系统不允许创建链接：{exc}")

    def test_output_directory_link_back_to_original_is_rejected(self):
        alias = self.root / "alias"
        self.symlink(self.game, alias, True)
        with self.assertRaises(ValueError):
            self.workspace(output=alias / "unsafe.exe")
        self.symlink(self.game, self.game / "dist", True)
        with self.assertRaises(ValueError):
            self.workspace()

    def test_output_member_symlink_cannot_overwrite_or_delete_original(self):
        self.output.parent.mkdir()
        self.symlink(self.game / "Sound", self.output.parent / "Sound", True)
        work = self.workspace([self.mod(resources={"Sound/theme.mp3": b"new"})])
        self.build(work)
        with self.assertRaises(ValueError):
            work.publish([])
        self.assertEqual((self.game / "Sound/theme.mp3").read_bytes(), b"old-music")

    def test_source_data_link_to_existing_dist_is_rejected(self):
        self.output.parent.mkdir()
        stale = self.output.parent / "stale.bin"
        stale.write_bytes(b"stale")
        self.symlink(stale, self.game / "linked.bin")
        work = self.workspace()
        work.prepare()
        with self.assertRaises(ValueError):
            work.resolve_file("linked.bin")

    def test_real_merge_warning_and_swallowed_resource_error_abort(self):
        bad = record_diff(2)
        bad["modified"][0]["fields"] = {"f99999": 4}
        self.assert_failed_prepare([self.mod(diffs={"WarPC.dat": bad})], "WARN")
        mod = self.mod(resources={"new.bin": b"new"})
        original_open = zipfile.ZipFile.open

        def fail_resource(archive, name, *args, **kwargs):
            if name == "resources/0.bin":
                raise OSError("模拟资源读取失败")
            return original_open(archive, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", new=fail_resource):
            self.assert_failed_prepare([mod], "ERROR")

    def test_grp_layer_merge_and_silent_invalid_spans_are_checked(self):
        section = encode_section(2, 1, b"\0" * 4, b"\0\0", None, False)
        (self.game / "SC.GRP").write_bytes(section)
        (self.game / "SC.IDX").write_bytes(struct.pack("<II", 0, len(section)))
        diff = {"patch_type": "grp_layer_diff", "modified": {"0": {"planes": {"L1": [[0, [7]]]}}}}
        work = self.workspace([self.mod(diffs={"SC.GRP": diff})])
        work.prepare()
        self.assertEqual(decode_section(Path(work.resolve_file("SC.GRP")).read_bytes())["L1"], b"\7\0")
        diff["modified"]["0"]["planes"]["L1"] = [[2, [7]]]
        self.assert_failed_prepare([self.mod(diffs={"SC.GRP": diff})], "越界")
        diff["modified"] = {}
        diff["appended"] = [{"index": 1, "bin": "blobs/missing.bin"}]
        self.assert_failed_prepare([self.mod(diffs={"SC.GRP": diff})], "缺少")

    def test_grp_complete_resource_keeps_original_idx_and_act_direct_write(self):
        (self.game / "TKAct.dat").write_bytes(bytes(784))
        mod = self.mod(diffs={"TKAct.dat": {"patch_type": "block_diff", "block_type": "act_entry",
                                           "modified": [block_entry(0, bytes([3]) * 784)]}},
                       resources={"SC.GRP": b"ccdd"})
        original = tree(self.game)
        work = self.workspace([mod])
        self.build(work)
        self.assertEqual(work.files, {"TKAct.dat", "SC.GRP", "SC.IDX"})
        self.assertEqual(Path(work.resolve_file("TKAct.dat")).read_bytes(), bytes([3]) * 784)
        work.publish([])
        self.assertEqual(tree(self.game, exclude_dist=True), original)

    def test_full_grp_requires_original_or_selected_idx(self):
        mod = self.mod(resources={"new.GRP": b"new"})
        self.assert_failed_prepare([mod], "配套索引")
        with_idx = self.mod(resources={"new.GRP": b"new", "new.IDX": struct.pack("<II", 0, 3)})
        work = self.workspace([with_idx])
        work.prepare()
        self.assertEqual(work.files, {"new.GRP", "new.IDX"})

    def test_multiple_exe_replacements_are_rejected(self):
        mods = [self.mod("exe-a", resources={"TKS.exe": b"MZ-a"}),
                self.mod("exe-b", resources={"TKS.exe": b"MZ-b"})]
        self.assert_failed_prepare(mods, "多个 EXE")

    def test_publish_requires_prepared_workspace_and_nonempty_built_exe(self):
        work = self.workspace()
        with self.assertRaises(RuntimeError):
            work.publish([])
        work.prepare()
        with self.assertRaises(ValueError):
            work.publish([])
        Path(work.build_exe).write_bytes(b"")
        with self.assertRaises(ValueError):
            work.publish([])
        self.assertFalse(self.output.parent.exists())


if __name__ == "__main__":
    unittest.main()
