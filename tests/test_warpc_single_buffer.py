import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LAUNCHER) not in sys.path:
    sys.path.insert(0, str(LAUNCHER))

from core.config_loader import PatchDef  # noqa: E402
from core import patch_engine  # noqa: E402
from core.tkspatch_loader import load_patch_directory  # noqa: E402
from editor_utils.lzss import lzss_compress_dat  # noqa: E402


class WarpcSingleBufferTests(unittest.TestCase):
    def test_runtime_expand_reuses_launcher_warpc_buffer(self):
        with tempfile.TemporaryDirectory() as td:
            data_path = Path(td) / "WarPC.dat"
            data_path.write_bytes(b"WARPC-EXT")
            defn = PatchDef(
                type="patch_data_expand",
                id="warpc_base_refs",
                data_file=str(data_path),
                old_base=patch_engine._WARPC_BASE_PLACEHOLDER,
                old_size=4,
                section_name=".warpc",
            )
            defn._extra = {"buffer_cap": 0x1000}
            code = bytearray(0x80)
            struct.pack_into(
                "<I", code, 0x10, patch_engine._WARPC_BASE_PLACEHOLDER)
            struct.pack_into("<I", code, 0x20, 4)
            logs = []
            ctx = SimpleNamespace(
                h_proc=1,
                code_buf=code,
                code_start_addr=0x401000,
                warpc_base=0x700000,
                log=logs.append,
            )

            def reject_alloc(*_args, **_kwargs):
                raise AssertionError(
                    "runtime must reuse the launcher-allocated WarPC buffer")

            original_alloc = patch_engine._VirtualAllocEx
            original_write = patch_engine.write_pm
            original_vp = patch_engine.vp_ex
            patch_engine._VirtualAllocEx = reject_alloc
            patch_engine.write_pm = lambda _handle, _addr, data: len(data)
            patch_engine.vp_ex = lambda *_args: 0
            try:
                self.assertTrue(
                    patch_engine._apply_patch_data_expand(defn, ctx),
                    "\n".join(logs))
            finally:
                patch_engine._VirtualAllocEx = original_alloc
                patch_engine.write_pm = original_write
                patch_engine.vp_ex = original_vp

            self.assertEqual(
                struct.unpack_from("<I", code, 0x10)[0], 0x700000)
            self.assertEqual(
                struct.unpack_from("<I", code, 0x20)[0], len(b"WARPC-EXT"))

    def test_runtime_warpc_expand_nops_tmp_dat_decompress(self):
        cfg = load_patch_directory(
            str(LAUNCHER / "patches"), log_func=lambda *_args: None)
        defn = next(
            patch for patch in cfg.patches
            if patch.id == "warpc_base_refs")
        self.assertEqual(len(defn.bytes_patches), 1)
        # The patch must target only the crashing decompression call, not the
        # whole function prologue (killing the entry skips deleting tmp.dat and
        # hangs the enter-game read-back handshake).
        self.assertEqual(
            defn.bytes_patches[0]["pattern"],
            "8B 55 C4 52 E8 49 EA 04 00")

        with tempfile.TemporaryDirectory() as td:
            data_path = Path(td) / "WarPC.dat"
            data_path.write_bytes(lzss_compress_dat(b"WARPC-EXT"))
            defn.data_file = str(data_path)
            code = bytearray(0x100)
            anchor = bytes.fromhex("8B55C452E849EA0400")
            code[0x40:0x40 + len(anchor)] = anchor
            struct.pack_into(
                "<I", code, 0x10, patch_engine._WARPC_BASE_PLACEHOLDER)
            struct.pack_into("<I", code, 0x20, 4)
            logs = []
            ctx = SimpleNamespace(
                h_proc=1,
                code_buf=code,
                code_start_addr=0x401000,
                warpc_base=0x700000,
                log=logs.append,
            )

            original = (
                patch_engine._VirtualAllocEx,
                patch_engine.write_pm,
                patch_engine.vp_ex,
            )
            patch_engine._VirtualAllocEx = lambda *_args, **_kwargs: None
            patch_engine.write_pm = lambda _handle, _addr, data: len(data)
            patch_engine.vp_ex = lambda *_args: 0
            try:
                self.assertTrue(
                    patch_engine._apply_patch_data_expand(defn, ctx),
                    "\n".join(logs))
            finally:
                (patch_engine._VirtualAllocEx,
                 patch_engine.write_pm,
                 patch_engine.vp_ex) = original

            # The call 0x452B14 bytes (offsets 4..8) become NOPs; the preceding
            # mov/push context and everything after are left intact so the
            # function still frees, closes, deletes tmp.dat and returns.
            self.assertEqual(code[0x40:0x44], bytes.fromhex("8B55C452"))
            self.assertEqual(code[0x44:0x49], b"\x90\x90\x90\x90\x90")


if __name__ == "__main__":
    unittest.main(verbosity=2)
