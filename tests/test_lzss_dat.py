"""editor_utils.lzss DAT 变体 round-trip 守护测试 (T1 合并后)。

历史背景: tks_launcher_gui/core/lzss.py 曾是同一算法的独立实现,
T1 已合并 (交叉等价性验证: 6 组样本双向解压一致)。本测试守护
共享实现的正确性 —— 压缩算法若被改动导致 round-trip 破坏即失败。
"""
import random
import unittest

from editor_utils.lzss import lzss_compress_dat, lzss_decompress_dat


class LzssDatTests(unittest.TestCase):
    def test_round_trip_samples(self):
        random.seed(20260906)
        samples = [
            b"",                                   # 空
            b"A",                                  # 单字节
            b"\x20" * 5000,                        # 全窗口初值 (大量自引用匹配)
            bytes(range(256)) * 40,                # 循环模式 (长距离匹配)
            bytes(random.randrange(256) for _ in range(50000)),  # 高熵
            (b"ABCDEF" * 3000)                     # 长距离重复
            + bytes(random.randrange(256) for _ in range(700))
            + b"ABCDEF" * 3000,
        ]
        for i, data in enumerate(samples):
            with self.subTest(sample=i):
                self.assertEqual(lzss_decompress_dat(lzss_compress_dat(data)), data)

    def test_header_layout(self):
        data = b"hello" * 100
        packed = lzss_compress_dat(data)
        self.assertEqual(len(packed[:12]), 12)
        ts = int.from_bytes(packed[0:4], "little")
        bs = int.from_bytes(packed[4:8], "little")
        self.assertEqual(ts, len(data))
        self.assertEqual(bs, len(packed) - 8)
        self.assertEqual(int.from_bytes(packed[8:12], "little"), len(data))


if __name__ == "__main__":
    unittest.main()
