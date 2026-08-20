import json
import os
import tempfile
import unittest
import zipfile

from core.launcher_pipeline import PipelineConfig, PipelineResult
from core.state_persistence import GuiState, load_gui_state, save_gui_state
from core.mod_loader import expand_pak_mods, scan_mods
from editor_utils.mod_exporter import generate_mod_json
from core.launch_context import LaunchContext
from core.state_persistence import state_profile_key
from core.recovery_snapshot import begin_snapshot, finish_snapshot, load_snapshot, manifest_changed
from core.save_manager import create_backup, list_backups
from core.launcher_pipeline import PatcherPipeline, PipelineConfig
from core.mod_loader import ModInfo
from workers.patcher_worker import PatcherWorker


class LauncherModeTests(unittest.TestCase):
    def test_state_defaults_old_file_to_standard(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "launcher_setting.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"patches": {"p": True}, "mods": {}, "tool": ""}, handle)

            state = load_gui_state(path)

            self.assertEqual(state.mode, "standard")
            self.assertEqual(state.schema_version, 2)
            self.assertEqual(state.patches, {"p": True})

    def test_invalid_mode_is_safe_and_saved_as_standard(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "launcher_setting.json")
            state = GuiState(mode="invalid", last_game_path="C:/Games/TKS/TKS.exe")

            self.assertTrue(save_gui_state(path, state))
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)

            self.assertEqual(raw["mode"], "standard")
            self.assertEqual(raw["last_game_path"], "C:/Games/TKS/TKS.exe")

    def test_pipeline_config_normalizes_unknown_mode_in_result(self):
        from core.launcher_pipeline import PatcherPipeline

        pipeline = PatcherPipeline(
            PipelineConfig(exe_path="TKS.exe", exe_dir=".", mode="unknown"),
            log=lambda _: None,
        )

        self.assertEqual(pipeline.result.mode, "standard")

    def test_result_contains_structured_status_fields(self):
        result = PipelineResult(mode="compatible")
        data = result.as_dict()

        self.assertEqual(data["mode"], "compatible")
        self.assertEqual(data["patches_status"], "not_started")
        self.assertEqual(data["cleanup_status"], "pending")

    def test_mod_metadata_is_loaded_and_old_mod_defaults_to_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sample.tksmod")
            metadata = {
                "format": "TKSMOD",
                "id": "sample",
                "name": "Sample",
                "category": "avatar",
                "tags": ["avatar", "visual"],
                "compatibility": {"compatible": True},
                "requires_features": [],
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mod.json", json.dumps(metadata))

            mods = scan_mods(td)

            self.assertEqual(len(mods), 1)
            self.assertEqual(mods[0].category, "avatar")
            self.assertEqual(mods[0].tags, ["avatar", "visual"])
            self.assertIs(mods[0].compatibility["compatible"], True)

    def test_old_mod_metadata_is_not_marked_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "legacy.tksmod")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mod.json", json.dumps({
                    "format": "TKSMOD", "id": "legacy", "name": "Legacy",
                }))

            mods = scan_mods(td)

            self.assertEqual(mods[0].category, "other")
            self.assertNotIn("compatible", mods[0].compatibility)

    def test_old_mod_category_is_inferred_without_inventing_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "legacy.tksmod")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mod.json", json.dumps({
                    "format": "TKSMOD", "id": "legacy", "name": "Legacy",
                }))
                archive.writestr("resources/avatar/face.JVG", b"data")

            mod = scan_mods(td)[0]

            self.assertEqual(mod.category, "avatar")
            self.assertTrue(mod.inferred_metadata)
            self.assertNotIn("compatible", mod.compatibility)

    def test_explicit_category_wins_over_content_inference(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "declared.tksmod")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mod.json", json.dumps({
                    "format": "TKSMOD", "id": "declared", "name": "Declared",
                    "category": "music",
                }))
                archive.writestr("resources/avatar/face.JVG", b"data")

            mod = scan_mods(td)[0]

            self.assertEqual(mod.category, "music")
            self.assertFalse(mod.inferred_metadata)

    def test_pak_metadata_fills_missing_child_fields_without_overriding_explicit_values(self):
        with tempfile.TemporaryDirectory() as td:
            child_path = os.path.join(td, "child.tksmod")
            child_metadata = {
                "format": "TKSMOD", "id": "child", "name": "Child",
                "category": "avatar",
                "compatibility": {"compatible": False},
            }
            child_bytes_path = os.path.join(td, "child.bin")
            with zipfile.ZipFile(child_path, "w") as archive:
                archive.writestr("mod.json", json.dumps(child_metadata))
            with open(child_path, "rb") as handle:
                child_bytes = handle.read()

            pak_path = os.path.join(td, "bundle.tksmodpak")
            pak_metadata = {
                "format": "TKSMODPAK", "id": "bundle", "name": "Bundle",
                "category": "visual",
                "tags": ["resource"],
                "compatibility": {"compatible": True},
            }
            with zipfile.ZipFile(pak_path, "w") as archive:
                archive.writestr("mod.json", json.dumps(pak_metadata))
                archive.writestr("child.tksmod", child_bytes)

            expanded = expand_pak_mods(pak_path)

            self.assertEqual(len(expanded), 1)
            self.assertEqual(expanded[0].category, "avatar")
            self.assertEqual(expanded[0].tags, ["resource"])
            self.assertIs(expanded[0].compatibility["compatible"], False)

    def test_export_metadata_contains_new_fields(self):
        metadata = generate_mod_json({
            "id": "exported",
            "name": "Exported",
            "category": "music",
            "tags": ["music", "resource"],
            "compatibility": {"compatible": True},
            "requires_features": [],
            "notes": "resource only",
        }, components=[])

        self.assertEqual(metadata["category"], "music")
        self.assertEqual(metadata["tags"], ["music", "resource"])
        self.assertIs(metadata["compatibility"]["compatible"], True)
        self.assertEqual(metadata["notes"], "resource only")

    def test_state_profiles_are_isolated_by_game_path(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "launcher_setting.json")
            game_a = os.path.join(td, "A", "TKS.exe")
            game_b = os.path.join(td, "B", "TKS.exe")
            save_gui_state(path, GuiState(
                last_game_path=game_a, mode="compatible", mods={"a": True}), game_a)
            save_gui_state(path, GuiState(
                last_game_path=game_b, mode="standard", mods={"b": True}), game_b)

            state_a = load_gui_state(path, game_a)
            state_b = load_gui_state(path, game_b)

            self.assertEqual(state_a.mode, "compatible")
            self.assertEqual(state_a.mods, {"a": True})
            self.assertEqual(state_b.mode, "standard")
            self.assertEqual(state_b.mods, {"b": True})
            self.assertNotEqual(state_profile_key(game_a), state_profile_key(game_b))

    def test_state_preserves_unknown_fields_and_creates_legacy_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "launcher_setting.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "schema_version": 1,
                    "last_game_path": os.path.join(td, "TKS.exe"),
                    "future_setting": {"enabled": True},
                    "patches": {}, "mods": {}, "tool": "",
                }, handle)

            state = load_gui_state(path)
            self.assertEqual(state.extra["future_setting"], {"enabled": True})
            self.assertTrue(save_gui_state(path, state, state.last_game_path))

            with open(path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["future_setting"], {"enabled": True})
            self.assertTrue(os.path.isfile(path + ".legacy.bak"))

    def test_corrupt_state_fields_are_downgraded_individually(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "launcher_setting.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "mode": 123,
                    "patches": ["bad"],
                    "mods": "bad",
                    "tool": 456,
                }, handle)

            state = load_gui_state(path)

            self.assertEqual(state.mode, "standard")
            self.assertEqual(state.patches, {})
            self.assertEqual(state.mods, {})
            self.assertEqual(state.tool, "")

    def test_compatible_pipeline_skips_post_launch_patch_stage(self):
        pipeline = PatcherPipeline(
            PipelineConfig(exe_path="TKS.exe", exe_dir=".", mode="compatible"),
            log=lambda _message: None,
        )
        pipeline.config = object()

        result = pipeline.run_post_launch(
            target_pid=0, code_buf=bytearray(), code_start=0,
            base_addr=0, mod_size=0,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.patches_status, "skipped")

    def test_multiple_tks_exe_mods_are_rejected_before_file_changes(self):
        worker = PatcherWorker(exe_path="TKS.exe", game_dir=".")
        messages = []
        worker.log_emitted.connect(messages.append)
        mods = [
            ModInfo(mod_id="a", name="A", mod_type="tks_exe"),
            ModInfo(mod_id="b", name="B", mod_type="tks_exe"),
        ]

        self.assertFalse(worker._maybe_replace_tks_exe(mods, "."))
        self.assertTrue(worker._tks_exe_conflict)
        self.assertTrue(any("无法安全选择" in message for message in messages))

    def test_mod_list_renders_category_column(self):
        from PySide6.QtWidgets import QApplication
        from ui.mod_list import ModListWidget

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "visual.tksmod")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mod.json", json.dumps({
                    "format": "TKSMOD", "id": "visual", "name": "Visual",
                    "category": "avatar", "version": "2.0",
                }))
            widget = ModListWidget(td)
            category_cells = [
                widget._table.cellWidget(row, 2).text()
                for row in range(widget._table.rowCount())
                if widget._table.item(row, 1) is not None
                and widget._table.item(row, 1).text() == "Visual"
                and widget._table.cellWidget(row, 2) is not None
            ]
            self.assertEqual(category_cells, ["头像"])
            widget.close()

    def test_launch_context_is_immutable_and_normalizes_mode(self):
        context = LaunchContext(
            exe_path="TKS.exe", game_dir=".", mode="invalid",
            selected_patches=frozenset({"p"}), enabled_mod_ids=frozenset({"m"}),
        ).normalized()

        self.assertEqual(context.mode, "standard")
        self.assertEqual(context.selected_patches, frozenset({"p"}))
        with self.assertRaises(AttributeError):
            context.mode = "compatible"

    def test_recovery_snapshot_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            task_id = begin_snapshot(td, os.path.join(td, "game"), os.path.join(td, "game", "TKS.exe"))
            snapshot = load_snapshot(td)
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.task_id, task_id)
            self.assertTrue(finish_snapshot(td, task_id))
            self.assertIsNone(load_snapshot(td))

    def test_recovery_manifest_detects_external_change(self):
        with tempfile.TemporaryDirectory() as td:
            game_dir = os.path.join(td, "game")
            os.makedirs(game_dir)
            exe = os.path.join(game_dir, "TKS.exe")
            with open(exe, "wb") as handle:
                handle.write(b"original")
            task_id = begin_snapshot(td, game_dir, exe)
            with open(exe, "wb") as handle:
                handle.write(b"changed")
            snapshot = load_snapshot(td)
            self.assertEqual(manifest_changed(game_dir, snapshot.file_manifest), ["TKS.exe"])
            finish_snapshot(td, task_id)

    def test_backup_persists_mode_and_game_path(self):
        with tempfile.TemporaryDirectory() as td:
            game_dir = os.path.join(td, "game")
            os.makedirs(os.path.join(game_dir, "Save"))
            backup_path = create_backup(
                os.path.join(td, "backups"), game_dir, "snapshot",
                {"patch": True}, {"mod": False}, "tool",
                mode="compatible", game_path=os.path.join(game_dir, "TKS.exe"),
                state_schema_version=2,
            )
            backups = list_backups(os.path.join(td, "backups"))

            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].path, backup_path)
            self.assertEqual(backups[0].mode, "compatible")
            self.assertTrue(backups[0].game_path.endswith("TKS.exe"))
            self.assertEqual(backups[0].state_schema_version, 2)


if __name__ == "__main__":
    unittest.main()
