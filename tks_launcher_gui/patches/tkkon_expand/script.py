"""External script patch: TKKon.dat >650 entry expansion.

The original game loads TKKon.dat into the fixed buffer 0x9D0698 and rejects
files whose decompressed size is larger than 26000 bytes. This patch allocates
a larger buffer, writes the full decompressed TKKon data into it, then
redirects all 0x9D0698 references and the 26000 load-size constant to the
new buffer.

Reverse evidence:
  - 4173F8.c:22  sub_45343C(aTkkonDat, &unk_9D0698, 26000)
  - 45343C.c     rejects decompressed size > a3
  - 452B14.c     writes decompressed data directly into a2
"""

import ctypes
import os

from core.lzss import lzss_decompress
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

TKKON_OLD_BASE = 0x9D0698
TKKON_OLD_SIZE = 26000
TKKON_REC_SIZE = 40


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
    log("\n--- [tkkon_expand] TKKon 动画/效果记录扩容 ---")

    orig_size = int(ctx.variables.get("tkkon_orig_size", TKKON_OLD_SIZE))
    rec_size = int(ctx.variables.get("tkkon_rec_size", TKKON_REC_SIZE))
    old_base = int(ctx.variables.get("tkkon_base", TKKON_OLD_BASE))

    if not os.path.isfile("TKKon.dat"):
        log("  [SKIP] TKKon.dat not found")
        return True
    try:
        with open("TKKon.dat", "rb") as f:
            raw = f.read()
    except OSError as e:
        log(f"  [ERROR] read TKKon.dat failed: {e}")
        return False

    full = lzss_decompress(raw)
    if len(full) <= orig_size:
        log(f"  [SKIP] TKKon.dat decompressed size {len(full)} <= original {orig_size}")
        return True
    if len(full) % rec_size:
        log(f"  [ERROR] TKKon.dat decompressed size {len(full)} is not a multiple of {rec_size}")
        return False

    new_size = len(full)
    new_count = new_size // rec_size
    orig_count = orig_size // rec_size
    log(f"  [OK] {orig_count} -> {new_count} records "
        f"({orig_size} -> {new_size} bytes)")

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
            log(f"  [WARN] no TKKon base refs found (0x{old_base:08X})")

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
            log(f"  [WARN] no TKKon size ref found ({orig_size}); "
                "assuming loader already accepts expanded size")

        if not base_hits or not size_hits:
            log("  [WARN] some expected TKKon references were not patched")
        return True
    finally:
        _CloseHandle(hp)
