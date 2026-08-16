"""External script patch: disable companion process launch for Xiaotan MOD."""

import struct

from core.memory import (
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

_COMPANION_SHELLEXEC_VA = 0x4E57C2
_COMPANION_ANCHOR = bytes([0x68, 0xD0, 0xE0, 0xA7, 0x00, 0x6A, 0x00, 0xE8])
_COMPANION_CALL_OFF = 7
_COMPANION_REPL = bytes([0x83, 0xC4, 0x18, 0x90, 0x90])


def apply(ctx):
    log = ctx.log
    ranges = getattr(ctx.exe_profile, "extra_section_ranges", None) if ctx.exe_profile else None
    log("\n--- [xiaotan_disable_companion] disable companion process launch ---")
    if not ranges:
        log("  [SKIP] no MOD extra sections")
        return True

    hp = _OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
        False, ctx.target_pid)
    if not hp:
        log("  [ERROR] OpenProcess failed")
        return False

    patched = 0
    try:
        for start, end in ranges:
            size = end - start
            if size <= 0 or size > 0x100000:
                continue
            buf, nr = read_pm(hp, start, size)
            if nr <= 0:
                continue
            idx = buf.find(_COMPANION_ANCHOR)
            while idx != -1:
                call_off = idx + _COMPANION_CALL_OFF
                rel = struct.unpack_from("<i", bytes(buf[call_off + 1:call_off + 5]))[0]
                call_va = start + call_off
                target = (call_va + 5 + rel) & 0xFFFFFFFF
                if target == _COMPANION_SHELLEXEC_VA:
                    op = vp_ex(hp, call_va, len(_COMPANION_REPL), PAGE_EXECUTE_READWRITE)
                    nw = write_pm(hp, call_va, _COMPANION_REPL)
                    vp_ex(hp, call_va, len(_COMPANION_REPL), op)
                    if nw == len(_COMPANION_REPL):
                        patched += 1
                        log(f"  [OK] @0x{call_va:08X}: ShellExecuteA call skipped")
                    else:
                        log(f"  [FAIL] @0x{call_va:08X}: write failed ({nw}/{len(_COMPANION_REPL)})")
                idx = buf.find(_COMPANION_ANCHOR, idx + 1)
        if patched == 0:
            log("  [WARN] ShellExecuteA companion call not found, skip")
        return True
    finally:
        _CloseHandle(hp)
