"""External script patch: sub_4C33FC entry check fix.

The old launcher kept this logic in core/patch_engine.py. It now lives in the
distributable patches/_scripts directory so the patch can be updated without
rebuilding the launcher.
"""

import struct

from core.memory import (
    b2i32,
    read_pm,
    write_pm,
    vp_ex,
    PAGE_EXECUTE_READWRITE,
    PROCESS_VM_READ,
    PROCESS_VM_WRITE,
    PROCESS_VM_OPERATION,
    _OpenProcess,
    _CloseHandle,
)


def apply(ctx):
    log = ctx.log
    hp = _OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
        False, ctx.target_pid)
    if not hp:
        log("  [ERROR] OpenProcess failed")
        return False
    try:
        sr = 0xC33FC
        av = ctx.base_addr + sr
        log(f"\n--- [save_entry_check_fix] sub_4C33FC entry fix @0x{av:08X} ---")
        buf, nr = read_pm(hp, av, 64)
        if nr < 32:
            log("  [WARN] read sub_4C33FC failed, skip")
            return True

        co = -1
        for i in range(min(nr, 32) - 4):
            if (buf[i] == 0x80 and (buf[i + 1] & 0xF8) == 0x78
                    and buf[i + 2] == 0x0C and buf[i + 3] == 0x00):
                co = i
                break
        if co < 0:
            log("  [WARN] cmp [reg+0Ch],0 pattern not found, skip")
            return True

        bo, bo2 = buf[co + 4], buf[co + 5]
        ba = av + co + 4
        if bo == 0x74:
            pb = bytes([0xEB, bo2])
            desc = "je short -> jmp short"
        elif bo == 0x75:
            pb = bytes([0x90, 0x90])
            desc = "jne short -> NOP NOP"
        elif bo == 0x0F and bo2 == 0x84:
            imm = b2i32(buf, co + 6)
            pb = bytearray(6)
            pb[0] = 0xE9
            pb[1:5] = struct.pack("<I", (imm + 1) & 0xFFFFFFFF)
            pb[5] = 0x90
            desc = "je near -> jmp near + NOP"
        elif bo == 0x0F and bo2 == 0x85:
            pb = bytes([0x90] * 6)
            desc = "jne near -> NOP x6"
        else:
            log("  [WARN] unknown branch after cmp, skip")
            return True

        op = vp_ex(hp, ba, len(pb), PAGE_EXECUTE_READWRITE)
        nw = write_pm(hp, ba, pb)
        vp_ex(hp, ba, len(pb), op)
        if nw == len(pb):
            log(f"  [OK] sub_4C33FC+0x{co + 4:X} patched ({desc})")
            return True
        log(f"  [ERROR] WriteProcessMemory failed ({nw}/{len(pb)})")
        return False
    finally:
        _CloseHandle(hp)
