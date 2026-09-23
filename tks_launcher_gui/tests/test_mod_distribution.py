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
        self.baseline = self.root / "baseline"
        self.packages = self.root / "packages"
        self.game.mkdir()
        self.baseline.mkdir()
        self.packages.mkdir()
        self.source = self.game / "TKS.exe"
        self.source.write_bytes(b"MZ-original-executable")
        shutil.copyfile(self.source, self.baseline / "TKS.exe")
        (self.game / "WarPC.dat").write_bytes(lzss_compress_dat(bytes(1054 * 2)))
        (self.game / "TKSkill.dat").write_bytes(lzss_compress_dat(bytes(94 * 2)))
        (self.game / "TKT.dat").write_bytes(text_data({1: "Old", 2: "Keep"}))
        (self.game / "SC.GRP").write_bytes(b"aabb")
        (self.game / "SC.IDX").write_bytes(struct.pack("<III", 0, 2, 4))
        (self.game / "FONT9696").write_bytes(b"old-font")
        (self.game / "Sound").mkdir()
        (self.game / "Sound" / "theme.mp3").write_bytes(b"old-music")
        (self.game / "unrelated.bin").write_bytes(b"do-not-copy")
        self.base_files = {"WarPC.dat", "TKSkill.dat", "TKT.dat", "SC.GRP", "SC.IDX",
                           "FONT9696", "Sound/theme.mp3"}
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

    def workspace(self, mods=(), output=None, allowed=None, baseline=None):
        work = ModBuildWorkspace(str(self.source), str(output or self.output), list(mods),
                                 allowed_configs=allowed, log_func=self.logs.append,
                                 baseline_dir=str(self.baseline if baseline is None else baseline))
        self.addCleanup(work.cleanup)
        return work

    def copy_baseline(self):
        shutil.copytree(self.game, self.baseline, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("dist"))

    def assert_products(self, work, differences):
        directory = Path(work.output_exe).parent
        self.assertEqual(work.files, set(differences))
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), set(differences) | {Path(work.output_exe).name})
        return {str(directory / name) for name in manifest["files"] + [MANIFEST]}

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

    def test_current_game_data_is_published_without_selected_mods(self):
        template = self.game / "WarPC.dat.tksx"
        template.write_bytes(b"edited-skill-state")
        before = tree(self.game)
        work = self.workspace()
        self.build(work)
        work.publish([])
        for name in ("WarPC.dat", "WarPC.dat.tksx", "TKSkill.dat", "TKT.dat",
                     "SC.GRP", "SC.IDX", "FONT9696", "Sound/theme.mp3"):
            with self.subTest(name=name):
                self.assertEqual((self.output.parent / name).read_bytes(),
                                 (self.game / name).read_bytes())
        self.assertEqual(tree(self.game, exclude_dist=True), before)

    def test_existing_edits_remain_under_mod_diff_and_editor_backups_are_ignored(self):
        self.copy_baseline()
        baseline_before = tree(self.baseline)
        existing = bytearray(2 * 1054)
        struct.pack_into("<h", existing, 0, 91)
        struct.pack_into("<h", existing, 4, 123)
        baseline = lzss_compress_dat(existing)
        (self.game / "WarPC.dat").write_bytes(baseline)
        (self.game / "WarPC.dat.bak").write_bytes(b"older-editor-backup")
        (self.game / "WarPC.dat.tksx").write_bytes(b"current-template")
        (self.game / "WarPC.dat.tksx.bak").write_bytes(b"older-template")
        before = tree(self.game)
        diff = {"record_size": 1054, "field_type": "int16",
                "modified": [{"index": 0, "fields": {"f1": 456}}]}
        work = self.workspace([self.mod(diffs={"WarPC.dat": diff})])
        self.build(work)
        work.publish([])
        result = lzss_decompress_dat((self.output.parent / "WarPC.dat").read_bytes())
        self.assertEqual(struct.unpack_from("<hhh", result), (91, 456, 123))
        self.assertEqual((self.output.parent / "WarPC.dat.tksx").read_bytes(), b"current-template")
        self.assert_products(work, {"WarPC.dat", "WarPC.dat.tksx"})
        self.assertFalse(any(name.endswith(".bak") for name in tree(self.output.parent)))
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_collects_runtime_formats_but_not_saves_caches_backups_or_editor_files(self):
        included = {"TKObj.dat", "DEFCMD.LST", "Title.avi", "FONT9696.chs", "FONT9696.cht",
                    "image.dll", "ddraw.ini", "Check.GRP", "TKDef.txt", "TKTalk.txt",
                    "script.srp", "pic_h01.pcx", "00.gxp", "Aa.JVG", "Sound/voice.wav",
                    "Movie/ending.avi"}
        excluded = {"Save/1.sav", "Save/data.dat", "sav.dat", "tmp.dat", "tmp_TKD.dat",
                    "TKAct.dat.bak", "Mu-Bak.JVG", "launcher_cache/data.dat", "cache/map.gxp",
                    "dist/TKSkill.dat", "mods/base.dat", "tools/data.dat", "docs/TKD.dat",
                    "backups/WarPC.dat", "备份/SC.GRP", "projects/map.gxp", "editor/work.dat",
                    "说明.txt", "scene.json", "CFace.exe", "TKS_MOD.exe", "run.log"}
        for name in included | excluded:
            path = self.game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode("utf-8"))
        before = tree(self.game)
        work = self.workspace(output=self.root / "package" / "launcher.exe")
        self.build(work)
        self.assertEqual(work.files, self.base_files | included)
        work.publish([])
        for name in work.files:
            self.assertEqual((Path(work.output_exe).parent / name).read_bytes(),
                             (self.game / name).read_bytes())
        self.assertEqual(tree(self.game), before)
        self.assertTrue(any("重建 TKD.dat" in line for line in self.logs))
        self.assertTrue(any("重建 TKT.dat" in line for line in self.logs))

    def test_selected_tool_overrides_baseline_and_mod_like_launcher(self):
        (self.game / "ddraw.dll").write_bytes(b"baseline-dll")
        (self.game / "ddraw.ini").write_bytes(b"baseline-config")
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "ddraw.dll").write_bytes(b"selected-dll")
        (tools / "ddraw.ini").write_bytes(b"selected-config")
        before = tree(self.game)
        mod = self.mod(resources={"ddraw.ini": b"mod-config"})
        work = self.workspace([mod])
        self.build(work)
        work.publish([], str(tools))
        self.assertEqual((self.output.parent / "ddraw.dll").read_bytes(), b"selected-dll")
        self.assertEqual((self.output.parent / "ddraw.ini").read_bytes(), b"selected-config")
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(Path(work.resolve_file("ddraw.ini")).read_bytes(), b"mod-config")

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
        self.assertEqual((self.output.parent / "FONT9696").read_bytes(), b"old-font")
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
        self.copy_baseline()
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
        staged = Path(work.resolve_file("WarPC.dat"))
        self.assertNotEqual(staged, self.game / "WarPC.dat")
        self.assertEqual(staged.read_bytes(), (self.game / "WarPC.dat").read_bytes())
        self.assertIsNone(work.resolve_file("only-in-dist.bin"))
        self.assertEqual(Path(work.resolve_file("FONT9696")).read_bytes(), b"font")
        with self.assertRaises(ValueError):
            work.resolve_file("dist/WarPC.dat")
        (self.game / "WarPC.dat.orig").write_bytes(b"leftover")
        self.assertEqual(Path(work.resolve_file("WarPC.dat")), staged)
        with self.assertRaisesRegex(ValueError, "运行残留"):
            self.workspace().prepare()

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
        directory = Path(same_name.output_exe).parent
        self.assertEqual({p.name for p in directory.glob("*.exe")}, {"tks.EXE"})
        self.assertEqual(set(json.loads((directory / MANIFEST).read_text())["files"]),
                         self.base_files | {"tks.EXE"})

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
        for name in ("LAUNCHER.exe", MANIFEST, "file.orig", "TKS.exe"):
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
        self.assertEqual(set(json.loads((self.output.parent / MANIFEST).read_text())["files"]),
                         self.base_files | {"launcher.exe", "new.bin"})

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
        self.copy_baseline()
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace([self.mod(resources={"shared.bin": b"after", "new/nested.bin": b"new"})])
        self.build(work, b"MZ-after")
        prepared_files = set(work.files)
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
        self.assertEqual(work.files, prepared_files)
        self.assertEqual(tree(self.baseline), baseline_before)
        work.publish([])
        self.assert_products(work, {"shared.bin", "new/nested.bin"})
        self.assertEqual(self.output.read_bytes(), b"MZ-after")
        self.assertFalse((self.output.parent / "a-old.bin").exists())
        self.assertFalse((self.output.parent / "WarPC.dat").exists())
        self.assertEqual(tree(self.baseline), baseline_before)

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
            ModBuildWorkspace("relative.exe", str(self.output), [], baseline_dir=str(self.baseline))

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
        self.assertEqual(work.files, self.base_files | {"TKAct.dat"})
        self.assertEqual(Path(work.resolve_file("TKAct.dat")).read_bytes(), bytes([3]) * 784)
        work.publish([])
        self.assertEqual(tree(self.game, exclude_dist=True), original)

    def test_full_grp_requires_original_or_selected_idx(self):
        mod = self.mod(resources={"new.GRP": b"new"})
        self.assert_failed_prepare([mod], "配套索引")
        with_idx = self.mod(resources={"new.GRP": b"new", "new.IDX": struct.pack("<II", 0, 3)})
        work = self.workspace([with_idx])
        work.prepare()
        self.assertEqual(work.files, self.base_files | {"new.GRP", "new.IDX"})

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

    def test_identical_baseline_keeps_full_staging_but_only_publishes_exe_and_manifest(self):
        self.copy_baseline()
        output = self.output.with_name("TKS_MOD.exe")
        (self.baseline / output.name).write_bytes(self.source.read_bytes())
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace(output=output)
        self.build(work, self.source.read_bytes())
        self.assertEqual(work.baseline_dir, str(self.baseline))
        self.assertEqual(work.files, set())
        self.assertEqual(set(work._targets.values()), self.base_files)
        for name in self.base_files:
            staged = Path(work.resolve_file(name.swapcase()))
            self.assertEqual(staged.read_bytes(), (self.game / name).read_bytes())
            self.assertTrue(staged.is_relative_to(work.directory))
        result = work.publish([])
        self.assertEqual(set(result), self.assert_products(work, set()))
        self.assertEqual(set(tree(output.parent)), {"TKS_MOD.exe", MANIFEST})
        self.assertTrue(all(Path(name).is_absolute() and Path(name).is_file() for name in result))
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)
        self.assertTrue(any("新增 0，变化 0，跳过相同 7" in line for line in self.logs))

    def test_existing_edits_new_tksx_and_bytes_not_timestamps_determine_differences(self):
        self.copy_baseline()
        (self.baseline / "FONT9696").rename(self.baseline / "font9696")
        edited = bytearray(1054 * 2)
        struct.pack_into("<h", edited, 0, 91)
        (self.game / "WarPC.dat").write_bytes(lzss_compress_dat(edited))
        (self.game / "WarPC.dat.tksx").write_bytes(b"new-template")
        font = self.game / "FONT9696"
        baseline_stat = (self.baseline / "font9696").stat()
        font.write_bytes(b"NEW-font")
        os.utime(font, ns=(baseline_stat.st_atime_ns, baseline_stat.st_mtime_ns))
        music = self.game / "Sound/theme.mp3"
        music_stat = music.stat()
        os.utime(music, ns=(music_stat.st_atime_ns, music_stat.st_mtime_ns + 10_000_000_000))
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace()
        self.build(work)
        expected = {"WarPC.dat", "WarPC.dat.tksx", "FONT9696"}
        self.assertEqual(work.files, expected)
        self.assertEqual(set(work.publish([])), self.assert_products(work, expected))
        self.assertFalse((self.output.parent / "Sound/theme.mp3").exists())
        for name in expected:
            self.assertEqual((self.output.parent / name).read_bytes(), (self.game / name).read_bytes())
            self.assertIn(f"  [最终差异] {name}", self.logs)
        self.assertTrue(any("新增 1，变化 2，跳过相同 5" in line for line in self.logs))
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_mod_reverting_game_edit_to_baseline_is_not_output(self):
        self.copy_baseline()
        edited = bytearray(1054 * 2)
        struct.pack_into("<h", edited, 0, 91)
        (self.game / "WarPC.dat").write_bytes(lzss_compress_dat(edited))
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace([self.mod(diffs={"WarPC.dat": record_diff(0)})])
        self.build(work)
        self.assertEqual(Path(work.resolve_file("WarPC.dat")).read_bytes(),
                         (self.baseline / "WarPC.dat").read_bytes())
        self.assertEqual(work.files, set())
        work.publish([])
        self.assert_products(work, set())
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_baseline_can_be_game_but_only_mod_differences_are_output(self):
        before = tree(self.game)
        work = self.workspace(baseline=self.game)
        self.build(work)
        self.assertEqual(work.files, set())
        work.publish([])
        self.assert_products(work, set())
        modded = self.workspace([self.mod(diffs={"WarPC.dat": record_diff(88)})], baseline=self.game)
        self.build(modded)
        self.assertEqual(modded.files, {"WarPC.dat"})
        modded.publish([])
        self.assert_products(modded, {"WarPC.dat"})
        self.assertEqual(tree(self.game, exclude_dist=True), before)

    def test_grp_change_does_not_emit_identical_idx(self):
        self.copy_baseline()
        before, baseline_before = tree(self.game), tree(self.baseline)
        mods = [self.mod(resources={"SC.GRP": b"ccdd"}),
                self.mod(diffs={"SC.GRP": {"patch_type": "block_diff",
                                          "modified": [block_entry(0, b"cc")]}})]
        for mod in mods:
            with self.subTest(mod=mod.path):
                work = self.workspace([mod])
                self.build(work)
                self.assertEqual(work.files, {"SC.GRP"})
                self.assertEqual(Path(work.resolve_file("SC.IDX")).read_bytes(),
                                 (self.game / "SC.IDX").read_bytes())
                work.publish([])
                self.assert_products(work, {"SC.GRP"})
                self.assertFalse((self.output.parent / "SC.IDX").exists())
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_publish_recompares_all_staging_after_tools_or_expansion_edit_it(self):
        self.copy_baseline()
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace([self.mod(resources={"FONT9696": b"mod-font"})])
        self.build(work)
        self.assertEqual(work.files, {"FONT9696"})
        Path(work.resolve_file("FONT9696")).write_bytes((self.baseline / "FONT9696").read_bytes())
        music = Path(work.resolve_file("Sound/theme.mp3"))
        unchanged_stat = music.stat()
        music.write_bytes(b"new-music")
        os.utime(music, ns=(unchanged_stat.st_atime_ns, unchanged_stat.st_mtime_ns))
        work.publish([])
        self.assert_products(work, {"Sound/theme.mp3"})
        self.assertFalse((self.output.parent / "FONT9696").exists())
        music.write_bytes((self.baseline / "Sound/theme.mp3").read_bytes())
        os.utime(music, ns=(unchanged_stat.st_atime_ns, unchanged_stat.st_mtime_ns))
        work.publish([])
        self.assert_products(work, set())
        self.assertFalse((self.output.parent / "Sound/theme.mp3").exists())
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_resources_and_tools_are_filtered_after_final_override(self):
        self.copy_baseline()
        (self.baseline / "patch.bin").write_bytes(b"patch")
        (self.baseline / "tool.bin").write_bytes(b"tool")
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "font9696").write_bytes((self.baseline / "FONT9696").read_bytes())
        (tools / "tool.bin").write_bytes(b"tool")
        (tools / "patch.bin").write_bytes(b"patch")
        (tools / "ddraw.ini").write_bytes(b"new-config")
        (tools / "Sound").mkdir()
        (tools / "Sound/theme.mp3").write_bytes(b"new-music")
        patch_source = self.root / "patch.bin"
        patch_source.write_bytes(b"overridden-patch")
        same_source = self.root / "same.bin"
        same_source.write_bytes(b"patch")
        (self.baseline / "same.bin").write_bytes(b"patch")
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace([self.mod(resources={"FONT9696": b"mod-font"})])
        self.build(work)
        self.assertEqual(work.files, {"FONT9696"})
        result = work.publish([("patch.bin", str(patch_source)), ("same.bin", str(same_source))], str(tools))
        self.assertEqual(set(result), self.assert_products(work, {"ddraw.ini", "Sound/theme.mp3"}))
        self.assertEqual(set(tree(self.output.parent)),
                         {self.output.name, MANIFEST, "ddraw.ini", "Sound", "Sound/theme.mp3"})
        self.assertTrue(any("新增 1，变化 1，跳过相同 9" in line for line in self.logs))
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_previous_full_manifest_is_pruned_but_unknown_files_survive(self):
        old = self.workspace()
        self.build(old)
        old.publish([])
        self.assert_products(old, self.base_files)
        unknown = self.output.parent / "unknown.dat"
        unknown.write_bytes(b"keep-me")
        (self.output.parent / "user-folder").mkdir()
        self.copy_baseline()
        before, baseline_before = tree(self.game, exclude_dist=True), tree(self.baseline)
        work = self.workspace()
        self.build(work)
        result = work.publish([])
        self.assertEqual(set(result), self.assert_products(work, set()))
        for name in self.base_files:
            self.assertFalse((self.output.parent / name).exists())
        self.assertEqual(unknown.read_bytes(), b"keep-me")
        self.assertTrue((self.output.parent / "user-folder").is_dir())
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_baseline_only_files_are_not_data_sources_or_deletion_instructions(self):
        self.copy_baseline()
        (self.baseline / "missing.dat").write_bytes(b"baseline-only")
        (self.baseline / "TKS.exe.orig").write_bytes(b"not-a-purity-check")
        before, baseline_before = tree(self.game), tree(self.baseline)
        work = self.workspace()
        self.build(work)
        self.assertEqual(work.source_exe, str(self.source))
        self.assertIsNone(work.resolve_file("missing.dat"))
        work.publish([])
        self.assert_products(work, set())
        self.assertEqual(set(tree(self.output.parent)), {self.output.name, MANIFEST})
        self.assertEqual(tree(self.game, exclude_dist=True), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_baseline_is_required_keyword_only_absolute_directory_with_exe(self):
        with self.assertRaises(TypeError):
            ModBuildWorkspace(str(self.source), str(self.output), [])
        with self.assertRaises(TypeError):
            ModBuildWorkspace(str(self.source), str(self.output), [], None, None, str(self.baseline))
        empty = self.root / "empty"
        empty.mkdir()
        invalid = (None, "", "relative", str(self.root / "missing"), str(self.source), str(empty))
        for baseline in invalid:
            with self.subTest(baseline=baseline):
                with self.assertRaises(ValueError):
                    ModBuildWorkspace(str(self.source), str(self.output), [], baseline_dir=baseline)
        (empty / "TKS.exe").mkdir()
        with self.assertRaises(ValueError):
            self.workspace(baseline=empty)
        (self.baseline / "TKS.exe").rename(self.baseline / "tks.EXE")
        work = self.workspace()
        work.prepare()
        self.assertEqual(work.baseline_dir, str(self.baseline))
        self.assertFalse(self.output.parent.exists())

    def test_output_cannot_be_in_independent_baseline_or_its_ancestors(self):
        baseline = self.root / "reference" / "original"
        baseline.mkdir(parents=True)
        shutil.copyfile(self.source, baseline / "TKS.exe")
        before = tree(self.root)
        for directory in (baseline, baseline.parent, baseline / "dist", baseline / "dist/nested",
                          baseline / "other"):
            with self.subTest(directory=directory):
                with self.assertRaisesRegex(ValueError, "基准"):
                    self.workspace(output=directory / "new.exe", baseline=baseline)
        self.assertEqual(tree(self.root), before)

    def test_linked_baseline_source_and_output_roots_are_rejected(self):
        baseline_alias = self.root / "baseline-alias"
        source_alias = self.root / "game-alias"
        self.symlink(self.baseline, baseline_alias, True)
        self.symlink(self.game, source_alias, True)
        with self.assertRaises(ValueError):
            self.workspace(baseline=baseline_alias)
        with self.assertRaises(ValueError):
            ModBuildWorkspace(str(source_alias / "TKS.exe"), str(self.output), [],
                              baseline_dir=str(self.baseline))
        with self.assertRaises(ValueError):
            self.workspace(output=baseline_alias / "dist/new.exe")
        # 即使被链接的是基准目录的祖先也不能通过。
        parent_alias = self.root / "parent-alias"
        self.symlink(self.root, parent_alias, True)
        with self.assertRaises(ValueError):
            self.workspace(baseline=parent_alias / "baseline")

    def test_baseline_exe_and_identical_data_links_are_rejected(self):
        self.copy_baseline()
        for name in ("TKS.exe", "FONT9696", "Sound"):
            with self.subTest(name=name):
                path = self.baseline / name
                saved = self.baseline / (name + "-saved")
                path.rename(saved)
                self.symlink(saved, path, saved.is_dir())
                try:
                    if name == "TKS.exe":
                        with self.assertRaises(ValueError):
                            self.workspace()
                    else:
                        self.assert_failed_prepare([], "链接")
                finally:
                    path.unlink()
                    saved.rename(path)

    def test_identical_source_and_output_member_links_cannot_be_skipped(self):
        self.copy_baseline()
        font = self.game / "FONT9696"
        font.unlink()
        self.symlink(self.baseline / "FONT9696", font)
        self.assert_failed_prepare([], "链接")
        font.unlink()
        shutil.copyfile(self.baseline / "FONT9696", font)
        work = self.workspace()
        self.build(work)
        self.assertEqual(work.files, set())
        self.output.parent.mkdir()
        self.symlink(self.game / "Sound", self.output.parent / "Sound", True)
        with self.assertRaisesRegex(ValueError, "链接"):
            work.publish([])
        self.assertFalse(self.output.exists())

    def test_identical_patch_and_tool_links_cannot_be_skipped(self):
        self.copy_baseline()
        (self.baseline / "same.bin").write_bytes(b"same")
        external = self.root / "external"
        external.mkdir()
        (external / "same.bin").write_bytes(b"same")
        alias = self.root / "external-alias"
        self.symlink(external, alias, True)
        linked_file = self.root / "linked.bin"
        self.symlink(external / "same.bin", linked_file)
        work = self.workspace()
        self.build(work)
        for source in (linked_file, alias / "same.bin"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "链接"):
                    work.publish([("same.bin", str(source))])
        with self.assertRaisesRegex(ValueError, "链接"):
            work.publish([], str(alias))
        tools = self.root / "tools"
        tools.mkdir()
        self.symlink(external / "same.bin", tools / "same.bin")
        with self.assertRaisesRegex(ValueError, "链接"):
            work.publish([], str(tools))
        self.assertFalse(self.output.parent.exists())

    def test_changed_real_roots_abort_prepare_resolve_and_publish(self):
        old = self.workspace()
        self.build(old)
        old.publish([])
        before, baseline_before = tree(self.game), tree(self.baseline)
        realpath = os.path.realpath
        for root in (self.game, self.baseline, self.output.parent):
            with self.subTest(root=root):
                fresh = self.workspace()

                def changed(path, *args, **kwargs):
                    if distribution._key(path) == distribution._key(root):
                        return str(self.root / "changed-root")
                    return realpath(path, *args, **kwargs)

                with patch.object(distribution.os.path, "realpath", side_effect=changed):
                    with self.assertRaisesRegex(ValueError, "真实路径已改变"):
                        fresh.prepare()
                    with self.assertRaisesRegex(ValueError, "真实路径已改变"):
                        old.resolve_file("WarPC.dat")
                    with self.assertRaisesRegex(ValueError, "真实路径已改变"):
                        old.publish([])
        self.assertEqual(tree(self.game), before)
        self.assertEqual(tree(self.baseline), baseline_before)

    def test_unreadable_identical_candidates_and_baseline_leave_previous_output_untouched(self):
        old = self.workspace()
        self.build(old)
        old.publish([])
        self.copy_baseline()
        (self.baseline / "same.bin").write_bytes(b"same")
        external = self.root / "same.bin"
        external.write_bytes(b"same")
        tools = self.root / "tools"
        tools.mkdir()
        tool = tools / "same.bin"
        tool.write_bytes(b"same")
        work = self.workspace()
        self.build(work)
        before, baseline_before = tree(self.game), tree(self.baseline)
        real_open = open
        unreadable_files = (self.baseline / "FONT9696", Path(work.resolve_file("FONT9696")),
                            external, tool)
        for unreadable in unreadable_files:
            with self.subTest(unreadable=unreadable):
                def fail_read(path, *args, **kwargs):
                    if distribution._key(path) == distribution._key(unreadable):
                        raise PermissionError("模拟相同文件不可读")
                    return real_open(path, *args, **kwargs)

                with patch("builtins.open", side_effect=fail_read):
                    with self.assertRaisesRegex(PermissionError, "相同文件不可读"):
                        work.publish([("same.bin", str(external))],
                                     str(tools) if unreadable == tool else "")
                self.assertEqual(tree(self.game), before)
                self.assertEqual(tree(self.baseline), baseline_before)
                self.assertEqual(work.files, set())
        unreadable = self.baseline / "FONT9696"
        with patch("builtins.open", side_effect=fail_read):
            self.assert_failed_prepare([], "相同文件不可读")

    def test_streaming_comparison_reads_past_first_chunk_and_propagates_late_errors(self):
        large = self.game / "large.dat"
        large.write_bytes(b"a" * (2 * 1024 * 1024 + 5))
        self.copy_baseline()
        work = self.workspace()
        self.build(work)
        self.assertEqual(work.files, set())
        staged = Path(work.resolve_file("large.dat"))
        with staged.open("r+b") as stream:
            stream.seek(-1, os.SEEK_END)
            stream.write(b"b")
        work.publish([])
        self.assert_products(work, {"large.dat"})
        before, baseline_before = tree(self.game), tree(self.baseline)
        real_open = open

        def fail_late(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            if distribution._key(path) == distribution._key(self.baseline / "large.dat"):
                real_read = stream.read

                def read(size=-1):
                    self.assertLessEqual(size, 1024 * 1024)
                    if stream.tell() >= 1024 * 1024:
                        raise OSError("模拟基准后续块不可读")
                    return real_read(size)

                stream.read = read
            return stream

        with patch("builtins.open", side_effect=fail_late):
            with self.assertRaisesRegex(OSError, "后续块不可读"):
                work.publish([])
        self.assertEqual(tree(self.game), before)
        self.assertEqual(tree(self.baseline), baseline_before)
        self.assertEqual(work.files, {"large.dat"})


if __name__ == "__main__":
    unittest.main()
