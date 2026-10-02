"""仅检查补丁计划和静态产物，不启动或模拟游戏流程。"""
import copy
import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editor_utils.lzss import lzss_compress_dat
from tks_launcher_gui.core.config_loader import patch_metadata
from tks_launcher_gui.core.patch_plan import (
    build_patch_plan, link_patch_operations, migrate_patch_states,
)
from tks_launcher_gui.core.tkspatch_loader import (
    load_cave_module, load_patch_directory, load_tkspatch_file, parse_patch_dict,
)
from tks_launcher_gui.patcher.build_patches import build_all_patches, build_single_patch


PATCHES = Path(__file__).resolve().parents[1] / "tks_launcher_gui" / "patches"
BUNDLE_IDS = {"tkskill_size", "tkskill_expand", "tksave_expand"}
BASELINE_SHA256 = "4df3263849aa9a92b8b749097a6cdc3346aa2ac6dd484e7142fa3a905e061808"


class PatchBundleChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = load_patch_directory(str(PATCHES)).patches

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)

    def write_data(self, count=351):
        for name, size in (("TKSkill.dat", count * 94), ("WarPC.dat", 500 * 1054)):
            (self.game / name).write_bytes(lzss_compress_dat(bytes(size)))

    def plan(self, selected=None, disabled=None, patches=None):
        return build_patch_plan(
            self.patches if patches is None else patches,
            selected=set() if selected is None else selected,
            disabled=disabled, resolve_file=lambda name: str(self.game / name))

    def test_only_three_public_package_definitions(self):
        ids = {p.id for p in self.patches}
        self.assertTrue(BUNDLE_IDS <= ids)
        self.assertFalse(ids & {"skill_ext_learn_state", "skill_ext_effect_resolver",
                                "skill_scan_bound", "skill_menu_cap",
                                "save_entry_check_fix", "save_stream_error_fix"})
        self.assertTrue(patch_metadata(next(p for p in self.patches
                                           if p.id == "tkskill_size"), "internal"))

    def test_baseline_protections_remain_without_extension(self):
        plan = self.plan()
        ids = {p.id for p in plan.patches}
        self.assertTrue({"tkskill_expand.baseline_scan", "tkskill_expand.baseline_menu",
                         "tksave_expand.stream"} <= ids)
        self.assertFalse(ids & {"tkskill_expand.state", "tkskill_size.length",
                                "tksave_expand.reopen_stream"})

    def test_expanded_data_enables_complete_dependencies(self):
        self.write_data()
        plan = self.plan()
        self.assertTrue(BUNDLE_IDS <= plan.ids)
        self.assertIn("tkskill_expand", plan.auto_enabled)
        self.assertIn("tkskill_size", plan.effective.required_by)
        self.assertFalse(any("baseline_" in p.id for p in plan.patches))

    def test_linked_cave_preserves_committed_baseline(self):
        self.write_data()
        state = next(p for p in self.plan().patches if p.id == "tkskill_expand.state")
        self.assertEqual(hashlib.sha256(state._cave_code_bytes).hexdigest(), BASELINE_SHA256)
        self.assertEqual((len(state.sites), len(state.cave_entries),
                          len(state.globals_relocations)), (52, 41, 116))
        enemy = next(s for s in state.sites if int(s["rva"], 0) == 0x30D24)
        self.assertEqual(enemy["ref"], "record_battle_map_player")
        self.assertEqual(patch_metadata(state, "owners"), ["tksave_expand", "tkskill_expand"])

    def test_length_has_one_owner_and_preserves_capacity(self):
        self.write_data()
        operations = {p.id: p for p in self.plan().patches}
        self.assertEqual(operations["tkskill_size.length"].new_value_expr, "65536")
        self.assertFalse(patch_metadata(operations["tkskill_expand.table"], "redirect_size"))
        self.assertEqual(patch_metadata(operations["tkskill_expand.table"], "front_pad"), 94)
        self.assertEqual(operations["tksave_expand.buffer"].new_value_expr, str(9200 + 500 * 1054))
        self.assertEqual(operations["tksave_expand.buffer"].expect_count, 0)

    def test_skill_table_negative_slot_is_zero_without_shifting_records(self):
        from tks_launcher_gui.core import patch_engine
        from tks_launcher_gui.core.config_loader import PatchRuntimeState, PatchSettings

        for count in (350, 351, 697):
            with self.subTest(count=count):
                self.write_data(count)
                content = b"\x12" * 94 + bytes((count - 2) * 94) + b"\xA5" * 94
                (self.game / "TKSkill.dat").write_bytes(lzss_compress_dat(content))
                definition = next(p for p in self.plan({"tkskill_expand"}).patches
                                  if p.id == "tkskill_expand.table")
                allocation = bytearray(94 + 65536)
                base = 0x2000000
                code = bytearray(b"\x68" + struct.pack("<I", 32900)
                                 + b"\x68" + struct.pack("<I", 0x7861CA))

                def write(_handle, address, payload):
                    if address >= base:
                        offset = address - base
                        self.assertLessEqual(offset + len(payload), len(allocation))
                        allocation[offset:offset + len(payload)] = payload
                    return len(payload)

                context = patch_engine.PatchContext(
                    definition, 0, 0, 0x400000, code, 0x401000, 0, 0,
                    PatchSettings(), PatchRuntimeState())
                with patch.object(patch_engine, "_VirtualAllocEx", return_value=base) as alloc, \
                        patch.object(patch_engine, "write_pm", side_effect=write), \
                        patch.object(patch_engine, "vp_ex", return_value=0x40):
                    self.assertTrue(patch_engine._apply_patch_data_expand(definition, context))
                if count == 350:
                    alloc.assert_not_called()
                    self.assertEqual(struct.unpack_from("<I", code, 6)[0], 0x7861CA)
                    continue
                self.assertEqual(alloc.call_args.args[2], 94 + 65536)
                table = struct.unpack_from("<I", code, 6)[0]
                self.assertEqual(table, base + 94)
                self.assertEqual(allocation[:94], bytes(94))
                self.assertEqual(allocation[94:94 + len(content)], content)
                for field in (22, 24, 30, 32):
                    offset = table - base - 94 + 2 * field
                    self.assertEqual(struct.unpack_from("<h", allocation, offset)[0], 0)

    def test_legacy_selection_and_advanced_option_migrate(self):
        self.write_data(350)
        plan = self.plan({"skill_ext_learn_state", "save_entry_check_fix"})
        self.assertIn("tkskill_expand", plan.ids)
        self.assertTrue(any(p.id == "tksave_expand.reopen_stream" for p in plan.patches))
        self.assertFalse(any(p.id == "tkskill_size.length" for p in plan.patches))
        states = migrate_patch_states(self.patches, {
            "skill_ext_learn_state": True, "tkskill_expand": False,
            "save_entry_check_fix": True, "tksave_expand.reopen_stream": False,
        })
        self.assertEqual(states, {"tkskill_expand": False, "tksave_expand.reopen_stream": False})

    def test_missing_or_disabled_dependency_rejects_plan(self):
        self.write_data()
        with self.assertRaises(ValueError):
            self.plan(disabled={"tksave_expand"})
        with self.assertRaises(ValueError):
            self.plan(patches=[p for p in self.patches if p.id != "tkskill_size"])

    def test_record_boundaries_are_checked_before_operations(self):
        self.write_data(697)
        self.assertIn("tkskill_expand", self.plan().ids)
        self.write_data(698)
        with self.assertRaises(ValueError):
            self.plan()
        (self.game / "TKSkill.dat").write_bytes(lzss_compress_dat(b"invalid"))
        with self.assertRaises(ValueError):
            self.plan()

    def test_template_enables_extension_and_declares_deployment_resource(self):
        self.write_data(350)
        (self.game / "WarPC.dat.tksx").write_bytes(b"template")
        plan = self.plan()
        self.assertIn("tkskill_expand", plan.auto_enabled)
        self.assertEqual(plan.resources, [("WarPC.dat.tksx", str(self.game / "WarPC.dat.tksx"))])

    def test_linker_rejects_missing_overlapping_or_foreign_fragments(self):
        paths = [PATCHES / "tkskill_expand" / "state.json",
                 PATCHES / "tksave_expand" / "persistence.json"]
        parts = [parse_patch_dict(json.loads(path.read_text(encoding="utf-8")), str(path))
                 for path in paths]
        with self.assertRaises(ValueError):
            link_patch_operations(parts[:1])
        overlapping = copy.deepcopy(parts)
        overlapping[1]._extra["cave_fragments"][0]["offset"] = 0
        with self.assertRaises(ValueError):
            link_patch_operations(overlapping)
        foreign_entry = copy.deepcopy(parts)
        foreign_entry[1].cave_entries["foreign"] = 0
        with self.assertRaises(ValueError):
            link_patch_operations(foreign_entry)

    def test_leftover_backups_are_restored_before_planning(self):
        from tks_launcher_gui.core.warpc_expander import restore_prepared_dats

        self.write_data(350)
        backup = self.game / "TKSkill.dat.orig"
        backup.write_bytes(lzss_compress_dat(bytes(351 * 94)))
        restore_prepared_dats(str(self.game))
        self.assertFalse(backup.exists())
        self.assertTrue(any(p.id == "tkskill_size.length" for p in self.plan().patches))

    def test_restore_mod_merge_plan_and_truncation_order(self):
        from tks_launcher_gui.core import launcher_pipeline, tkspatch_loader
        from tks_launcher_gui.core.config_loader import PatchConfig

        pipeline = launcher_pipeline.PatcherPipeline(
            launcher_pipeline.PipelineConfig("unused", str(self.game)), log=lambda _: None)
        events = []
        with patch.object(launcher_pipeline.os, "chdir"), \
                patch.object(tkspatch_loader, "load_patch_directory", return_value=PatchConfig(self.patches)), \
                patch.object(launcher_pipeline, "restore_prepared_dats", side_effect=lambda **_: events.append("restore")), \
                patch.object(launcher_pipeline, "restore_tkact_for_game", side_effect=lambda **_: events.append("restore_tkact")), \
                patch.object(launcher_pipeline, "ensure_save_directory_healthy"), \
                patch.object(pipeline, "_load_mods", side_effect=lambda _: events.append("mods")), \
                patch.object(launcher_pipeline, "build_patch_plan", side_effect=lambda *_, **__: events.append("plan")), \
                patch.object(launcher_pipeline, "prepare_warpc_for_game", side_effect=lambda **_: (events.append("truncate") or False, None, {})), \
                patch.object(launcher_pipeline, "prepare_tkact_for_game", return_value=False):
            self.assertFalse(pipeline.run_pre_launch().error)
        self.assertEqual(events, ["restore", "restore_tkact", "mods", "plan", "truncate"])

    def test_tkact_restored_before_runtime_data_expansion(self):
        from tks_launcher_gui.core import launcher_pipeline, patch_engine, tkact_expander
        from tks_launcher_gui.core.config_loader import PatchRuntimeState, PatchSettings

        self.write_data()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.game)
        for count in (650, 654):
            with self.subTest(count=count):
                full = b"\x12" * (650 * 784) + b"\xA5" * ((count - 650) * 784)
                path = self.game / "TKAct.dat"
                path.write_bytes(full)
                definition = next(p for p in self.plan().patches if p.id == "tkact_expand")
                pipeline = launcher_pipeline.PatcherPipeline(
                    launcher_pipeline.PipelineConfig("unused", str(self.game)), log=lambda _: None)
                pipeline._tkact_expanded = tkact_expander.prepare_tkact_for_game()
                self.assertEqual(path.stat().st_size, 650 * 784)
                pipeline._restore_truncated_dats()
                self.assertEqual(path.read_bytes(), full)
                self.assertFalse((self.game / tkact_expander.TKACT_TEMP_FILE).exists())
                code = bytearray(b"\x68" + struct.pack("<I", 509600)
                                 + b"\x68" + struct.pack("<I", 0x9539CA))
                writes = {}

                def write(_handle, address, payload):
                    writes[address] = bytes(payload)
                    return len(payload)

                context = patch_engine.PatchContext(
                    definition, 0, 0, 0x400000, code, 0x401000, 0, 0,
                    PatchSettings(), PatchRuntimeState())
                with patch.object(patch_engine, "_VirtualAllocEx", return_value=0x2000000), \
                        patch.object(patch_engine, "write_pm", side_effect=write), \
                        patch.object(patch_engine, "vp_ex", return_value=0x40):
                    self.assertTrue(patch_engine._apply_patch_data_expand(definition, context))
                self.assertEqual(writes[0x2000000], full)
                self.assertEqual(struct.unpack_from("<I", code, 6)[0], 0x2000000)

    def test_missing_write_handle_blocks_pipeline(self):
        from tks_launcher_gui.core import launcher_pipeline

        pipeline = launcher_pipeline.PatcherPipeline(
            launcher_pipeline.PipelineConfig("unused", str(self.game)), log=lambda _: None)
        with patch.object(launcher_pipeline, "_OpenProcess", return_value=0):
            self.assertFalse(pipeline._apply_patches(0, bytearray(), 0, 0, 0, None))
        self.assertTrue(pipeline.runtime.blocked_error)

    def test_failed_expanded_buffer_never_publishes_a_base(self):
        from tks_launcher_gui.core import launcher_pipeline, memory

        for failure in ("handle", "allocation", "write"):
            pipeline = launcher_pipeline.PatcherPipeline(
                launcher_pipeline.PipelineConfig("unused", str(self.game)), log=lambda _: None)
            pipeline._warpc_expanded = True
            pipeline._warpc_full_data = bytes(144 * 1054)
            with self.subTest(failure=failure), \
                    patch.object(launcher_pipeline.os.path, "isfile", return_value=False), \
                    patch.object(launcher_pipeline, "_OpenProcess", return_value=0 if failure == "handle" else 1), \
                    patch.object(launcher_pipeline, "_VirtualAllocEx", return_value=0 if failure == "allocation" else 0x30000000), \
                    patch.object(launcher_pipeline, "_CloseHandle"), \
                    patch.object(memory, "write_pm", return_value=0):
                pipeline._allocate_warpc_buffer(0)
            self.assertTrue(pipeline.runtime.blocked_error)
            self.assertEqual(pipeline._warpc_new_buf, 0)

    def test_partial_baseline_cave_writes_fail(self):
        from tks_launcher_gui.core import patch_engine
        from tks_launcher_gui.core.config_loader import PatchRuntimeState, PatchSettings

        definition = next(p for p in self.plan().patches if p.id == "tkskill_expand.baseline_menu")
        original = bytearray(b"\x90" * 64)
        for failure in ("cave", "first_hook", "second_hook"):
            code = bytearray(original)
            calls = []

            def write(_handle, _address, payload):
                calls.append(bytes(payload))
                failed = len(calls) == {"cave": 1, "first_hook": 2, "second_hook": 3}[failure]
                return len(payload) - 1 if failed else len(payload)

            with self.subTest(failure=failure), patch.object(patch_engine, "write_pm", side_effect=write), \
                    patch.object(patch_engine, "vp_ex", return_value=0x40):
                self.assertFalse(patch_engine.apply_cave_hook(
                    definition, [0, 16], code, 0x401000, 1, 0x20000000, 0x757F08,
                    PatchSettings(), PatchRuntimeState()))
            if failure != "second_hook":
                self.assertEqual(code, original)
            else:
                self.assertEqual(code[16:], original[16:])

    def test_build_ignores_directories_without_a_manifest(self):
        source = self.game / "source"
        (source / "notes").mkdir(parents=True)
        (source / "demo").mkdir()
        (source / "notes" / "reference.txt").write_text("not a patch", encoding="utf-8")
        (source / "demo" / "patch.json").write_text(json.dumps({
            "type": "patch_bytes", "id": "demo", "pattern": "90", "replace": {"0": 144},
        }), encoding="utf-8")
        output = self.game / "packages"
        self.assertTrue(build_all_patches(str(source), str(output)))
        self.assertEqual([p.id for p in load_patch_directory(str(output)).patches], ["demo"])
        self.assertTrue((source / "notes" / "reference.txt").is_file())

    def test_fixed_layout_generators_load_from_zip_resources(self):
        for definition in self.patches:
            if definition.type != "fixed_layout_cave":
                continue
            with self.subTest(patch=definition.id):
                output = self.game / f"{definition.id}.tkspatch"
                self.assertTrue(build_single_patch(PATCHES / definition.id, output))
                loaded = load_tkspatch_file(str(output))
                self.assertIsNotNone(loaded)
                self.assertFalse(Path(loaded.cave_code_file).exists())
                self.assertEqual(load_cave_module(definition).build_cave_block(0x400000, 4),
                                 load_cave_module(loaded).build_cave_block(0x400000, 4))

    def test_zip_and_directory_build_the_same_operations(self):
        self.write_data()
        zipped = []
        for patch in self.patches:
            if patch.id not in BUNDLE_IDS:
                zipped.append(patch)
                continue
            output = self.game / f"{patch.id}.tkspatch"
            self.assertTrue(build_single_patch(PATCHES / patch.id, output))
            loaded = load_tkspatch_file(str(output))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.package_files, patch.package_files)
            zipped.append(loaded)
        source_plan, zip_plan = self.plan(), self.plan(patches=zipped)
        self.assertEqual(source_plan.ids, zip_plan.ids)
        self.assertEqual(source_plan.resources, zip_plan.resources)
        for left, right in zip(source_plan.patches, zip_plan.patches, strict=True):
            self.assertEqual((left.id, left.type, left.new_value_expr, left._extra),
                             (right.id, right.type, right.new_value_expr, right._extra))
            self.assertEqual(left._cave_code_bytes, right._cave_code_bytes)


if __name__ == "__main__":
    unittest.main()
