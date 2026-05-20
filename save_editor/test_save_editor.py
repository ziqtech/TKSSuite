#!/usr/bin/env python3
"""save_editor round-trip automated tests."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from save_editor import *


class TestLZSS(unittest.TestCase):
    """LZSS 压缩/解压 round-trip"""

    def test_roundtrip_random(self):
        """压缩随机数据→解压→验证一致性"""
        import random

        random.seed(42)
        original = bytes(random.randint(0, 255) for _ in range(1000))
        compressed = save_lzss_compress(original)
        decompressed = save_lzss_decompress(compressed)
        self.assertEqual(original, decompressed)


class TestWarPCFields(unittest.TestCase):
    """WarPC 字段读/写 round-trip"""

    def setUp(self):
        self.seg3 = bytearray(WARPC_REC * WARPC_CNT)

    def test_int16_fields(self):
        """get_warpc_field/set_warpc_field round-trip"""
        test_fields = [
            (0, 12345),  # name_id
            (10, 999),  # cur_hp
            (14, 500),  # hp_base
            (64, 3),  # atk_count
            (520, 42),  # awk_sprite_id
        ]
        for off, val in test_fields:
            set_warpc_field(self.seg3, 0, off, val)
            result = get_warpc_field(self.seg3, 0, off)
            self.assertEqual(
                result, val, f"Field at offset {off}: expected {val}, got {result}"
            )

    def test_status_slot(self):
        """Status slot round-trip"""
        set_warpc_status_slot(self.seg3, 0, 0, 5, 10)
        sid, dur = get_warpc_status_slot(self.seg3, 0, 0)
        self.assertEqual(sid, 5)
        self.assertEqual(dur, 10)

        # Test all 8 slots
        for slot in range(8):
            set_warpc_status_slot(self.seg3, 0, slot, slot + 1, slot * 2)
            sid, dur = get_warpc_status_slot(self.seg3, 0, slot)
            self.assertEqual(sid, slot + 1)
            self.assertEqual(dur, slot * 2)

    def test_status_resist(self):
        """Status resist round-trip"""
        for i in range(32):
            set_warpc_status_resist(self.seg3, 0, i, i * 2)
        for i in range(32):
            val = get_warpc_status_resist(self.seg3, 0, i)
            self.assertEqual(val, i * 2, f"Resist {i}: expected {i*2}, got {val}")

    def test_skill_learn(self):
        """Skill learn round-trip"""
        test_values = [(0, 0), (42, 30), (100, 10), (343, 20)]
        for skill_idx, val in test_values:
            set_warpc_skill_learn(self.seg3, 0, skill_idx, val)
            result = get_warpc_skill_learn(self.seg3, 0, skill_idx)
            self.assertEqual(
                result, val, f"Skill {skill_idx}: expected {val}, got {result}"
            )


class TestFieldDefinitions(unittest.TestCase):
    """字段定义正确性验证"""

    def test_field_count(self):
        """验证命名字段数量 >= 90"""
        groups = [
            WARPC_IDENTITY,
            WARPC_HPMP,
            WARPC_SKILL_BONUS,
            WARPC_CHAR_ATTR,
            WARPC_EQUIP,
            WARPC_GROWTH,
            WARPC_BATTLE_REWARD,
            WARPC_DROP,
            WARPC_REACTION_FIELDS,
            WARPC_STATUS_SLOT_FIELDS,
            WARPC_STATUS_RESIST_FIELDS,
            WARPC_CAUSE_MASK_FIELDS,
            WARPC_USE_RIGHT_FIELDS,
            WARPC_EQUIP_SKILL_FIELDS,
        ]
        total = sum(len(g) for g in groups)
        self.assertGreaterEqual(
            total, 90, f"Expected >= 90 named fields, got {total}"
        )

    def test_status_names_count(self):
        """验证 STATUS_NAMES 有 31 个"""
        self.assertEqual(len(STATUS_NAMES), 31)


if __name__ == "__main__":
    unittest.main()
