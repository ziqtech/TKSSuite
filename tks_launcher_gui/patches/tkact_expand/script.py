"""External script patch: TKAct.dat >650 entry expansion.

The original game hard-codes the TKAct buffer at 0x9539CA and rejects files
larger than 509600 bytes. This patch allocates a larger buffer, copies the
expanded TKAct.dat into it, then redirects the loader call and the three
runtime addressing sites to the new buffer.

Reverse evidence:
  - 411624.c:124  sub_452544(aTkactDat, &unk_9539CA, 509600)
  - 452544.c:20   rejects file sizes > 509600
  - 4434BC.c:67/71/122 use 0x9539CA as the entry base
"""

import ctypes
import os

from core.memory import (
    i32b,
    write_pm,
    vp_ex,
    PAGE_EXECUTE_READWRITE,
    PAGE_READWRITE,
    PROCESS_VM_READ,
    PROCESS_VM_WRITE,
    PROCESS_VM_OPERATION,
    MEM_COMMIT,
    MEM_RESERVE,
    _OpenProcess,
    _CloseHandle,
    _VirtualAllocEx,
)
from core.scanner import value_scan

TKACT_OLD_BASE = 0x9539CA
TKACT_OLD_SIZE = 509600
TKACT_REC_SIZE = 784
TKACT_TEMP_FILE = "TKAct.dat.expanded"


def _in_extra(ctx, addr):
    profile = getattr(ctx, "exe_profile", None)
    ranges = getattr(profile, "extra_section_ranges", None) if profile else None
    if not ranges:
        return False
    for start, end in ranges:
        if start <= addr < end:
            return True
    return False


def apply(ctx):
    log = ctx.log
    log("\\n--- [tkact_expand] TKAct 动画条目扩容 ---")

    orig_size = ctx.settings.tkact_orig_size
    rec_size = ctx.settings.tkact_rec_size
    old_base = ctx.settings.tkact_base

    full_path = TKACT_TEMP_FILE
    if not os.path.isfile(full_path):
        full_path = "TKAct.dat"
    if not os.path.isfile(full_path):
        log(f"  [SKIP] {full_path} not found")
        return True
    new_size = os.path.getsize(full_path)
    if new_size <= orig_size:
        log(f"  [SKIP] {full_path} size {new_size} <= original {orig_size}")
        return True
    if new_size % rec_size:
        log(f"  [ERROR] {full_path} size {new_size} is not a multiple of {rec_size}")
        return False

    new_count = new_size // rec_size
    orig_count = orig_size // rec_size
    log(f"  [OK] source={full_path} {orig_count} -> {new_count} entries "
        f"({orig_size} -> {new_size} bytes)")

    try:
        with open(full_path, "rb") as f:
            full = f.read()
    except OSError as e:
        log(f"  [ERROR] read TKAct.dat failed: {e}")
        return False

    hp = _OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
        False, ctx.target_pid)
    if not hp:
        log("  [ERROR] OpenProcess failed")
        return False

    try:
        alloc = _VirtualAllocEx(hp, None, new_size,
                                MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not alloc:
            log("  [ERROR] VirtualAllocEx failed")
            return False
        new_buf = ctypes.cast(alloc, ctypes.c_void_p).value or 0
        if not new_buf:
            log("  [ERROR] invalid new buffer address")
            return False
        log(f"  [OK] new buffer 0x{new_buf:08X} ({new_size} bytes)")

        nw = write_pm(hp, new_buf, full)
        if nw != new_size:
            log(f"  [ERROR] write expanded data failed ({nw}/{new_size})")
            return False

        code = ctx.code_buf
        start = ctx.code_start_addr

        base_hits = []
        for off in value_scan(bytes(code), old_base):
            abs_addr = start + off
            if _in_extra(ctx, abs_addr):
                continue
            base_hits.append((off, abs_addr))

        if base_hits:
            new_base_le = i32b(new_buf)
            patched_base = 0
            for off, abs_addr in base_hits:
                op = vp_ex(hp, abs_addr, 4, PAGE_EXECUTE_READWRITE)
                w = write_pm(hp, abs_addr, new_base_le)
                vp_ex(hp, abs_addr, 4, op)
                if w == 4:
                    code[off:off + 4] = new_base_le
                    patched_base += 1
                else:
                    log(f"  [FAIL] base ref @0x{abs_addr:08X}")
            log(f"  [OK] patched {patched_base}/{len(base_hits)} base refs "
                f"(0x{old_base:08X} -> 0x{new_buf:08X})")
        else:
            log(f"  [WARN] no TKAct base refs found (0x{old_base:08X})")

        size_hits = []
        for off in value_scan(bytes(code), orig_size):
            abs_addr = start + off
            if _in_extra(ctx, abs_addr):
                continue
            size_hits.append((off, abs_addr))

        if size_hits:
            new_size_le = i32b(new_size)
            patched_size = 0
            for off, abs_addr in size_hits:
                op = vp_ex(hp, abs_addr, 4, PAGE_EXECUTE_READWRITE)
                w = write_pm(hp, abs_addr, new_size_le)
                vp_ex(hp, abs_addr, 4, op)
                if w == 4:
                    code[off:off + 4] = new_size_le
                    patched_size += 1
                else:
                    log(f"  [FAIL] size ref @0x{abs_addr:08X}")
            log(f"  [OK] patched {patched_size}/{len(size_hits)} size refs "
                f"({orig_size} -> {new_size})")
        else:
            log(f"  [WARN] no TKAct size ref found ({orig_size}); "
                "assuming loader already accepts expanded size")

        if not base_hits or not size_hits:
            log("  [WARN] some expected TKAct references were not patched")
        return True
    finally:
        _CloseHandle(hp)
