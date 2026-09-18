import struct
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path

from editor_utils.skill_extension import (
    HEADER_SIZE,
    MAGIC,
    SkillExtension,
    SkillExtensionFormatError,
    SkillExtensionVersionError,
    SparseSkillOverride,
    create_original_game_extension,
    create_skill_extension,
    migrate_for_original_game,
    migrate_skill_extension,
    mod_identity_crc32,
    parse_skill_extension,
)


class SkillExtensionTests(unittest.TestCase):
    def test_roundtrip_learn_state_and_sparse_override(self):
        extension = create_skill_extension(
            actor_count=3,
            skill_count=2,
            mod_id=mod_identity_crc32("demo.mod"),
            mapping_version=7,
            actor_capacity=200,
            skill_capacity=162,
            overrides=[
                SparseSkillOverride(
                    actor_id=2, skill_id=351, tkkon_id=584, flags=0),
            ],
        )
        extension = extension.with_learn_state(1, 350, 20)
        extension = extension.with_learn_state(2, 351, 10)

        encoded = extension.to_bytes()
        parsed = parse_skill_extension(encoded)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.actor_count, 3)
        self.assertEqual(parsed.skill_base, 350)
        self.assertEqual(parsed.skill_count, 2)
        self.assertEqual(parsed.learn_state(0, 350), 0)
        self.assertEqual(parsed.learn_state(1, 350), 20)
        self.assertEqual(parsed.learn_state(2, 351), 10)
        self.assertEqual(parsed.override_for(2, 351).tkkon_id, 584)
        self.assertEqual(parsed.mapping_version, 7)
        self.assertEqual(parsed.to_bytes(), encoded)

    def test_batch_override_update_adds_changes_and_removes(self):
        extension = create_skill_extension(2, 3)

        updated = extension.with_overrides([
            (0, 350, 584),
            (0, 351, 591),
            (1, 352, 600),
        ])
        self.assertEqual(updated.override_for(0, 350).tkkon_id, 584)
        self.assertEqual(updated.override_for(1, 352).tkkon_id, 600)

        updated = updated.with_overrides([(0, 350, None)])
        self.assertIsNone(updated.override_for(0, 350))
        self.assertEqual(updated.override_for(0, 351).tkkon_id, 591)
        self.assertEqual(updated.override_for(1, 352).tkkon_id, 600)

    def test_batch_override_update_enforces_global_limit(self):
        extension = create_skill_extension(1, 65, skill_capacity=65)
        with self.assertRaises(SkillExtensionFormatError):
            extension.with_overrides([
                (0, 350 + index, 1) for index in range(65)
            ])

    def test_override_accepts_expanded_tkkon_ids(self):
        extension = create_skill_extension(
            1,
            2,
            overrides=[
                SparseSkillOverride(0, 350, 650),
                SparseSkillOverride(0, 351, 32767),
            ],
        )
        self.assertEqual(extension.override_for(0, 350).tkkon_id, 650)
        self.assertEqual(extension.override_for(0, 351).tkkon_id, 32767)
        parsed = parse_skill_extension(extension.to_bytes())
        self.assertEqual(parsed.override_for(0, 350).tkkon_id, 650)
        self.assertEqual(parsed.override_for(0, 351).tkkon_id, 32767)

    def test_empty_tail_is_legacy_save(self):
        self.assertIsNone(parse_skill_extension(b""))

    def test_unknown_tail_is_rejected(self):
        with self.assertRaises(SkillExtensionFormatError):
            parse_skill_extension(b"not-a-tksx-block")

    def test_truncated_header_is_rejected(self):
        with self.assertRaises(SkillExtensionFormatError):
            parse_skill_extension(MAGIC + b"\0" * 8)

    def test_unsupported_version_is_rejected(self):
        extension = create_skill_extension(1, 1)
        encoded = bytearray(extension.to_bytes())
        struct.pack_into("<H", encoded, 4, 99)
        with self.assertRaises(SkillExtensionVersionError):
            parse_skill_extension(bytes(encoded))

    def test_crc_mismatch_is_rejected(self):
        extension = create_skill_extension(1, 1)
        encoded = bytearray(extension.to_bytes())
        encoded[-1] ^= 0x80
        with self.assertRaises(SkillExtensionFormatError):
            parse_skill_extension(bytes(encoded))

    def test_payload_count_mismatch_is_rejected(self):
        extension = create_skill_extension(2, 2)
        encoded = bytearray(extension.to_bytes())
        struct.pack_into("<H", encoded, 20, 3)
        struct.pack_into(
            "<I", encoded, 12,
            zlib.crc32(encoded[HEADER_SIZE:]) & 0xFFFFFFFF,
        )
        with self.assertRaises(SkillExtensionFormatError):
            parse_skill_extension(bytes(encoded))

    def test_duplicate_sparse_override_is_rejected(self):
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(
                2,
                1,
                overrides=[
                    SparseSkillOverride(1, 350, 10),
                    SparseSkillOverride(1, 350, 20),
                ],
            )

    def test_constructor_rejects_short_learn_matrix(self):
        with self.assertRaises(SkillExtensionFormatError):
            SkillExtension(
                actor_count=2,
                skill_base=350,
                skill_count=3,
                learn=b"\0" * 5,
            )

    def test_migration_extends_state_without_truncation(self):
        extension = create_skill_extension(2, 1)
        extension = extension.with_learn_state(1, 350, 20)

        migrated = migrate_skill_extension(
            extension,
            actor_count=3,
            skill_count=2,
        )

        self.assertEqual(migrated.actor_count, 3)
        self.assertEqual(migrated.skill_count, 2)
        self.assertEqual(migrated.learn_state(1, 350), 20)
        self.assertEqual(migrated.learn_state(1, 351), 0)
        self.assertEqual(migrated.learn_state(2, 350), 0)

    def test_original_game_migration_uses_fixed_capacity(self):
        extension = create_skill_extension(143, 1)
        extension = extension.with_learn_state(9, 350, 20)

        migrated = migrate_for_original_game(
            extension,
            actor_count=200,
            skill_count=51,
        )

        self.assertEqual(migrated.actor_count, 500)
        self.assertEqual(migrated.skill_count, 51)
        self.assertEqual(migrated.stride, 347)
        self.assertEqual(migrated.learn_state(9, 350), 20)
        self.assertEqual(migrated.learn[499 * migrated.stride + 346], 0)

    def test_migration_rejects_missing_saved_actors(self):
        extension = create_skill_extension(3, 1)
        with self.assertRaises(SkillExtensionFormatError):
            migrate_skill_extension(
                extension,
                actor_count=2,
                skill_count=1,
            )

    def test_migration_rejects_missing_saved_skills(self):
        extension = create_skill_extension(1, 2)
        with self.assertRaises(SkillExtensionFormatError):
            migrate_skill_extension(
                extension,
                actor_count=1,
                skill_count=1,
            )

    def test_migration_rejects_mod_identity_mismatch(self):
        extension = create_skill_extension(1, 1, mod_id=123)
        with self.assertRaises(SkillExtensionFormatError):
            migrate_skill_extension(
                extension,
                actor_count=1,
                skill_count=1,
                mod_id=456,
            )

    def test_original_game_rejects_game_limit_breaches(self):
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(501, 1)
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(1, 348)
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(
                1, 65, mapping_version=1,
                overrides=[
                    SparseSkillOverride(0, 350 + index, 1)
                    for index in range(65)
                ],
                skill_capacity=65,
            )
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(
                1, 1, mapping_version=1,
                overrides=[SparseSkillOverride(0, 350, -1)],
                skill_capacity=1,
            )
        with self.assertRaises(SkillExtensionFormatError):
            create_skill_extension(
                1, 1, mapping_version=1,
                overrides=[SparseSkillOverride(0, 350, 32768)],
                skill_capacity=1,
            )

    def test_reserved_header_word_is_checked(self):
        extension = create_skill_extension(1, 1, mapping_version=1)
        encoded = bytearray(extension.to_bytes())
        struct.pack_into("<H", encoded, 30, 1)
        with self.assertRaises(SkillExtensionFormatError):
            parse_skill_extension(bytes(encoded))

    def test_original_game_migration_rejects_nonzero_mod(self):
        extension = create_skill_extension(
            1, 1, mapping_version=1, mod_id=12345)
        with self.assertRaises(SkillExtensionFormatError):
            migrate_for_original_game(
                extension, actor_count=1, skill_count=1)

    def test_actor_swap_moves_states_and_overrides_together(self):
        extension = create_skill_extension(
            3,
            2,
            overrides=[
                SparseSkillOverride(0, 350, 10),
                SparseSkillOverride(1, 351, 11),
            ],
        )
        extension = extension.with_learn_state(0, 350, 1)
        extension = extension.with_learn_state(1, 351, 2)

        swapped = extension.swap_actor_learn_states(0, 1)
        swapped = swapped.swap_actor_overrides(0, 1)

        self.assertEqual(swapped.learn_state(0, 350), 0)
        self.assertEqual(swapped.learn_state(1, 350), 1)
        self.assertEqual(swapped.learn_state(1, 351), 0)
        self.assertIsNone(swapped.override_for(0, 350))
        self.assertEqual(swapped.override_for(0, 351).tkkon_id, 11)
        self.assertEqual(swapped.override_for(1, 350).tkkon_id, 10)

    def test_copy_actor_moves_row_and_overrides(self):
        extension = create_skill_extension(
            3,
            2,
            overrides=[SparseSkillOverride(0, 350, 10)],
        ).with_learn_state(0, 351, 20)

        copied = extension.copy_actor_extension(0, 2)

        self.assertEqual(copied.learn_state(2, 351), 20)
        self.assertEqual(copied.override_for(2, 350).tkkon_id, 10)

    def test_original_defaults_do_not_enable_unregistered_skills(self):
        extension = create_original_game_extension(
            actor_count=1, skill_count=2)

        self.assertEqual(extension.learn_state(0, 350), 10)
        self.assertEqual(extension.learn_state(0, 351), 10)
        self.assertEqual(extension.learn[extension.stride + 2], 0)
        self.assertEqual(extension.learn[extension.stride + 346], 0)

    def test_original_game_roundtrip_keeps_registered_count_and_full_stride(self):
        extension = create_original_game_extension(
            actor_count=1, skill_count=2)
        extension = extension.with_learn_state(0, 351, 20)

        parsed = parse_skill_extension(extension.to_bytes())

        self.assertEqual(parsed.skill_count, 2)
        self.assertEqual(parsed.skill_capacity, 347)
        self.assertEqual(len(parsed.learn), 500 * 347)
        self.assertEqual(parsed.learn_state(0, 351), 20)

    def test_replace_actor_overrides_keeps_other_actor_drafts(self):
        base = create_skill_extension(
            3,
            2,
            overrides=[
                SparseSkillOverride(0, 350, 10),
                SparseSkillOverride(1, 350, 11),
            ],
        )
        draft = replace(
            base,
            overrides=(
                SparseSkillOverride(0, 351, 99),
                SparseSkillOverride(2, 350, 12),
            ),
        )

        restored = draft.replace_actor_overrides_from(base, 0)

        self.assertEqual(restored.override_for(0, 350).tkkon_id, 10)
        self.assertIsNone(restored.override_for(0, 351))
        self.assertEqual(restored.override_for(2, 350).tkkon_id, 12)

    def test_editors_preserve_extension_tail(self):
        root = Path(__file__).resolve().parents[1]
        warpc_dir = str(root / "warpc_editor")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        if warpc_dir not in sys.path:
            sys.path.insert(0, warpc_dir)
        import importlib.util

        save_spec = importlib.util.spec_from_file_location(
            "_tks_save_editor_for_extension_test",
            root / "save_editor" / "save_editor.py",
        )
        save_module = importlib.util.module_from_spec(save_spec)
        assert save_spec.loader is not None
        save_spec.loader.exec_module(save_module)

        import warpc_editor as warpc_module

        extension = create_skill_extension(1, 1)
        extension = extension.with_learn_state(0, 350, 20)
        tail = extension.to_bytes()
        game_state = b"\0" * save_module.GAMESTATE_SIZE
        seg1 = b"\0" * save_module.SEG1_SIZE
        seg2 = b"\0" * save_module.SEG2_SIZE
        seg3 = bytearray(save_module.WARPC_REC)
        struct.pack_into(
            "<" + "h" * warpc_module.WARPC_FIELD_COUNT, seg3, 0,
            *([0] * warpc_module.WARPC_FIELD_COUNT))

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sav.1"
            save_module.save_save_data(
                str(path), game_state, seg1, seg2, seg3,
                extension_tail=tail)

            loaded = save_module.load_save_data(str(path), include_tail=True)
            self.assertEqual(loaded[4], tail)

            s1, s2, records, loaded_tail = warpc_module.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(loaded_tail, tail)

            records[0]["fields"][2] = 17
            warpc_module.save_warpc_to_save(
                str(path), s1, s2, records,
                extension_tail=loaded_tail)

            reloaded = warpc_module.load_warpc_from_save(
                str(path), include_tail=True)
            self.assertEqual(reloaded[3], tail)
            self.assertEqual(reloaded[2][0]["fields"][2], 17)


if __name__ == "__main__":
    unittest.main(verbosity=2)
