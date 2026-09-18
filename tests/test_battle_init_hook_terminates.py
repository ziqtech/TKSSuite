"""Guard: init_battle_map hooks the PROLOGUE of sub_4307CC via an injected call.

A prologue hook that rebuilds the frame with `push ebp; mov ebp,esp` while the
injected call's synthesized return address still sits above the saved ebp
leaves [ebp+4] = that synthesized address, so sub_4307CC's own epilogue
(`mov esp,ebp; pop ebp; ret`) returns to the mid-function continuation instead
of the real caller -> the function body re-enters itself forever (the reported
enter-scene freeze with audio still playing).

This test runs the real init_battle_map cave bytes and asserts control returns
to the *caller* return address (terminates), and clears the battle map.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tks_launcher_gui"
for p in (str(ROOT), str(LAUNCHER)):
    if p not in sys.path:
        sys.path.insert(0, p)

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_32,  # noqa: E402
                     UC_HOOK_CODE)
from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_EBP  # noqa: E402

import json  # noqa: E402


CAVE_BASE = 0x001D0000
GLOBALS = 0x006b8000          # battle-map placeholder address used by the cave
STUB = 0x00401000             # fakes sub_4307CC's epilogue at the continuation
HALT = 0x00402000             # fake caller return address (emulator stop)
STACK = 0x00500000


def _load():
    d = json.loads((LAUNCHER / "patches" / "skill_ext_learn_state"
                    / "patch.json").read_text(encoding="utf-8"))
    cave = bytes.fromhex(d["cave_code"].replace(" ", ""))
    return cave, d["cave_entries"]["init_battle_map"]


class BattleInitHookTerminates(unittest.TestCase):
    def test_init_battle_map_returns_to_caller_not_self(self):
        cave, entry_off = _load()
        uc = Uc(UC_ARCH_X86, UC_MODE_32)

        def region(addr, data):
            page = addr & ~0xFFF
            end = (addr + len(data) + 0xFFF) & ~0xFFF
            try:
                uc.mem_map(page, end - page)
            except Exception:
                pass
            uc.mem_write(addr, data)

        region(CAVE_BASE, cave)
        region(GLOBALS, b"\xAB" * 0x800)
        region(STUB, bytes.fromhex("8be55dc3"))    # mov esp,ebp; pop ebp; ret
        region(HALT, b"\xcc")
        region(STACK, b"\x00" * 0x4000)

        # Model the stack the moment the prologue's injected call lands in the
        # cave: [esp]=continuation (synthesized return), [esp+4]=real caller ret.
        sp = STACK + 0x2000
        import struct
        uc.mem_write(sp, struct.pack("<II", STUB, HALT))
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_EBP, sp + 0x100)

        entry = CAVE_BASE + entry_off
        # `until` = the caller return address: reaching it means a clean ret.
        # A hard instruction cap turns the historical self-loop into a failure
        # instead of hanging the test process.
        reached = {"ok": False}

        def hook(u, addr, size, _):
            if addr == HALT:
                reached["ok"] = True
                u.emu_stop()

        uc.hook_add(UC_HOOK_CODE, hook, begin=HALT, end=HALT + 1)
        try:
            uc.emu_start(entry, HALT, count=20000)
        except Exception:
            pass

        eip = uc.reg_read(UC_X86_REG_EIP)
        self.assertTrue(
            reached["ok"] or eip == HALT,
            "init_battle_map did not return to the caller (EIP=0x%X); "
            "prologue-frame reconstruction likely loops back into the body"
            % eip)

        self.assertEqual(bytes(uc.mem_read(GLOBALS, 32 * 2)), b"\0" * (32 * 2))
        self.assertEqual(
            bytes(uc.mem_read(GLOBALS + 32 * 2, 0x800 - 32 * 2)),
            b"\xab" * (0x800 - 32 * 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
