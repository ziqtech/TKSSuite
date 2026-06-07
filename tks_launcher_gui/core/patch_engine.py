"""补丁应用引擎 — 从 tks_launcher.py 提取 & 重组"""
import struct
from typing import List, Dict, Optional
from .memory import (
    i32b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex,
    replace_addr_in_bytes,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    _OpenProcess, _CloseHandle,
)
from .scanner import parse_pattern, pattern_scan, value_scan
from .config_loader import PatchDef, PatchConfig, resolve_var

# ============================================================
# Cave 模板 (x86 机器码, 原样复制自 C#)
# ============================================================

CAVE_AWK_SPRITE = bytes([
    0x50, 0x51, 0x0F, 0xBF, 0x45, 0xFA, 0x66, 0x85,
    0xC0, 0x74, 0x25, 0x69, 0xC0, 0x1E, 0x04, 0x00,
    0x00, 0x05, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7,
    0x88, 0x08, 0x02, 0x00, 0x00, 0x66, 0x85, 0xC9,
    0x75, 0x04, 0x85, 0xC0, 0xEB, 0x0A, 0x83, 0xE9,
    0x06, 0x66, 0x89, 0x4D, 0xFA, 0x66, 0x85, 0xC9,
    0x59, 0x58, 0xC3,
])

CAVE_PORTRAIT1 = bytes([
    0x50, 0x51, 0x52, 0x8B, 0xC1, 0x03, 0xC0, 0x05,
    0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x80, 0x0A,
    0x02, 0x00, 0x00, 0x66, 0x85, 0xC0, 0x75, 0x08,
    0x8B, 0x44, 0x24, 0x08, 0x66, 0x05, 0xD3, 0x00,
    0x83, 0xC4, 0x08, 0x5A, 0x87, 0x04, 0x24, 0xFF,
    0xE0,
])

CAVE_PORTRAIT2 = bytes([
    0x50, 0x51, 0x03, 0xC0, 0x05, 0x08, 0x7F, 0x75,
    0x00, 0x0F, 0xB7, 0x88, 0x0A, 0x02, 0x00, 0x00,
    0x66, 0x85, 0xC9, 0x75, 0x07, 0x66, 0x81, 0xC2,
    0xD3, 0x00, 0xEB, 0x03, 0x66, 0x89, 0xCA, 0x59,
    0x58, 0x87, 0x14, 0x24, 0xFF, 0xE2,
])

CAVE_ARCHIVE_PORTRAIT = bytes([
    0x52, 0x51, 0x0F, 0xB6, 0xC0, 0x8B, 0xC8, 0x69,
    0xC0, 0x1E, 0x04, 0x00, 0x00, 0x05, 0x08, 0x7F,
    0x75, 0x00, 0x0F, 0xB7, 0x90, 0x0A, 0x02, 0x00,
    0x00, 0x66, 0x85, 0xD2, 0x75, 0x09, 0x8B, 0xC1,
    0x05, 0xD3, 0x00, 0x00, 0x00, 0xEB, 0x02, 0x8B,
    0xC2, 0x59, 0x5A, 0x87, 0x04, 0x24, 0xFF, 0xE0,
])

CAVE_HISTORY_TEXT = bytes([
    0x52, 0x69, 0xD2, 0x1E, 0x04, 0x00, 0x00, 0x81,
    0xC2, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x82,
    0x0C, 0x02, 0x00, 0x00, 0x85, 0xC0, 0x75, 0x08,
    0x5A, 0x81, 0xC2, 0x5A, 0x23, 0x00, 0x00, 0xC3,
    0x8B, 0xD0, 0x83, 0xC4, 0x04, 0xC3,
])

_WARPC_BASE_PLACEHOLDER = 0x757F08

# ============================================================
# Cave 模板构建
# ============================================================

def build_cave_template(name: str, warpc_base: int, log_func=None) -> Optional[bytes]:
    log = log_func or (lambda x: None)
    templates = {
        "awk_sprite": CAVE_AWK_SPRITE,
        "portrait1": CAVE_PORTRAIT1,
        "portrait2": CAVE_PORTRAIT2,
        "archive_portrait": CAVE_ARCHIVE_PORTRAIT,
        "history_text": CAVE_HISTORY_TEXT,
    }
    if name not in templates:
        log(f"    [WARN] 未知 cave 模板: {name}")
        return None
    c = bytearray(templates[name])
    replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
    return bytes(c)

# ============================================================
# 补丁类型: patch_bytes
# ============================================================

def apply_patch_bytes(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       h_proc: int, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    pat, wc = parse_pattern(defn.pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    模式: [{defn.pattern}] -> 匹配 {len(hits)} 处 (预期 {defn.expect_count})")
    if defn.expect_count > 0 and len(hits) != defn.expect_count:
        log(f"  [WARN] 匹配数 {len(hits)} != 预期 {defn.expect_count}")
    ptd = 0
    for off in hits:
        for rk, bv in defn.replace.items():
            ro = int(rk)
            aa = code_start_addr + off + ro
            op = vp_ex(h_proc, aa, 1, PAGE_EXECUTE_READWRITE)
            write_pm(h_proc, aa, bytes([bv & 0xFF]))
            vp_ex(h_proc, aa, 1, op)
            idx = off + ro
            if idx < len(code_buf):
                code_buf[idx] = bv & 0xFF
        log(f"    [OK] RVA 0x{off:X} (abs 0x{code_start_addr + off:08X})")
        ptd += 1
    if ptd == 0 and defn.expect_count > 0:
        log("  [FAIL] 未找到匹配模式")
        return False
    return True

# ============================================================
# 补丁类型: patch_imm32 (value_scan)
# ============================================================

def apply_patch_imm32_by_value(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                h_proc: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    ov = defn.expect_value
    nv = resolve_var(defn.new_value_expr, variables, log_func=log)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    hits = value_scan(bytes(code_buf), ov)
    log(f"    扫描值 {ov} (0x{ov:X}) -> 匹配 {len(hits)} 处")
    log(f"    替换为 {nv} (0x{nv:X})")
    nle = i32b(nv); ptd = 0
    for off in hits:
        aa = code_start_addr + off
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if off + 4 <= len(code_buf):
            code_buf[off:off+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    return True

# ============================================================
# 补丁类型: patch_imm32 (pattern scan)
# ============================================================

def apply_patch_imm32_by_pattern(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                  h_proc: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    pat, wc = parse_pattern(defn.pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    模式: [{defn.pattern}] -> 匹配 {len(hits)} 处")
    nv = resolve_var(defn.new_value_expr, variables, log_func=log); ov = defn.expect_value
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    nle = i32b(nv); ptd = 0
    for off in hits:
        io = off + defn.value_offset
        if io + 4 <= len(code_buf):
            act = b2i32(bytes(code_buf), io)
            if ov != 0 and act != ov:
                log(f"    [SKIP] RVA 0x{off:X}: 原值 0x{act:08X} != 预期 0x{ov:08X}")
                continue
        aa = code_start_addr + io
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if io + 4 <= len(code_buf):
            code_buf[io:io+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    return True

# ============================================================
# 补丁类型: cave_hook
# ============================================================

def apply_cave_hook(defn: PatchDef, hits: List[int], code_buf: bytearray,
                     code_start_addr: int, h_proc: int, cave_addr: int,
                     warpc_base: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    if not hits:
        log("    [WARN] 未找到 hook 点")
        return False

    cd = build_cave_template(defn.cave_template, warpc_base, log_func=log)
    if cd is None:
        return False

    ct = cave_addr + defn.cave_offset
    write_pm(h_proc, ct, cd)
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")

    ptd = 0
    for off in hits:
        ha = code_start_addr + off
        co = (ct - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(defn.hook_size)
        ci[0] = 0xE8
        ci[1:5] = i32b(co)
        for i in range(5, defn.hook_size):
            ci[i] = 0x90

        op = vp_ex(h_proc, ha, defn.hook_size, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, defn.hook_size, op)

        for i in range(min(defn.hook_size, len(code_buf) - off)):
            code_buf[off + i] = ci[i]

        log(f"    [OK] Hook RVA 0x{off:X} -> call 0x{ct:08X}")
        ptd += 1

    return ptd > 0

# ============================================================
# 配置补丁编排
# ============================================================

def apply_config_patches(config: PatchConfig, code_buf: bytearray, code_start_addr: int,
                          h_proc: int, warpc_base: int, cave_addr: int,
                          variables: Dict[str, int], log_func=None,
                          minimal_mode=False, no_cave_mode=False,
                          only_portrait=False, only_awk=False) -> bool:
    log = log_func or (lambda x: None)
    all_ok = True
    pch: List[PatchDef] = []

    for defn in config.patches:
        tag = f"[{defn.id}]"
        log(f"\n  {tag}: {defn.desc}")

        if defn.type == "patch_bytes":
            all_ok &= apply_patch_bytes(defn, code_buf, code_start_addr, h_proc, log_func=log)
        elif defn.type == "cave_hook":
            hp = defn.hook_pattern or defn.pattern
            hpat, hwc = parse_pattern(hp or "")
            hh = pattern_scan(bytes(code_buf), hpat, hwc)
            if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
                log(f"  {tag}: Hook 模式匹配 {len(hh)} 处 (预期 {defn.hook_expect_count}), 跳过")
                continue
            defn._pre_scanned_hits = hh
            pch.append(defn)
        elif defn.type == "patch_imm32":
            if defn.value_scan:
                nv = resolve_var(defn.new_value_expr, variables, log_func=log)
                if nv is None:
                    log(f"    -> 变量未定义, 跳过")
                    continue
                if defn.expect_value != 0 and nv == defn.expect_value:
                    log(f"    -> 值未变化 ({defn.expect_value}), 跳过")
                    continue
                all_ok &= apply_patch_imm32_by_value(defn, code_buf, code_start_addr, h_proc, variables, log_func=log)
            else:
                all_ok &= apply_patch_imm32_by_pattern(defn, code_buf, code_start_addr, h_proc, variables, log_func=log)
        elif defn.type == "patch_warpc_addr":
            log(f"    -> 由 WarPC 扩展流程处理 (base=0x{warpc_base:08X})")
        else:
            log(f"  [WARN] 未知补丁类型: {defn.type}")

    if pch and not minimal_mode and not no_cave_mode:
        hta = pch
        if only_portrait:
            hta = [h for h in pch if h.id in ("portrait_cave1", "portrait_cave2")]
        elif only_awk:
            hta = [h for h in pch if h.id == "awk_sprite_cave"]
        log(f"\n  应用 {len(hta)} 个 cave hooks...")
        for defn in hta:
            all_ok &= apply_cave_hook(defn, defn._pre_scanned_hits, code_buf,
                                       code_start_addr, h_proc, cave_addr,
                                       warpc_base, variables, log_func=log)
    return all_ok

# ============================================================
# [补丁十二] sub_4C33FC 入口检查修补
# ============================================================

def patch_4c33fc(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0xC33FC
    log("\n--- [补丁十二] sub_4C33FC 入口检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 32:
        log(f"  [ERROR] 读取 sub_4C33FC@0x{av:08X} 失败"); _CloseHandle(hp); return

    co, cmr = -1, 0
    for i in range(min(nr, 32) - 4):
        if buf[i]==0x80 and (buf[i+1]&0xF8)==0x78 and buf[i+2]==0x0C and buf[i+3]==0x00:
            co, cmr = i, buf[i+1]; break

    if co < 0:
        log("  [WARN] 未找到 cmp [reg+0Ch],0 模式, 跳过"); _CloseHandle(hp); return

    bo, bo2 = buf[co+4], buf[co+5]
    ba = av + co + 4

    if bo == 0x74:
        pb = bytes([0xEB, bo2]); pd = "je short -> jmp short"
    elif bo == 0x75:
        pb = bytes([0x90, 0x90]); pd = "jne short -> NOP NOP"
    elif bo == 0x0F and bo2 == 0x84:
        imm = b2i32(buf, co+6)
        pb = bytearray(6); pb[0]=0xE9; pb[1:5]=i32b(imm+1); pb[5]=0x90
        pd = "je near -> jmp near + NOP"
    elif bo == 0x0F and bo2 == 0x85:
        pb = bytes([0x90]*6); pd = "jne near -> NOP x 6"
    else:
        log(f"  [WARN] 未识别 je/jne, 跳过"); _CloseHandle(hp); return

    op = vp_ex(hp, ba, len(pb), PAGE_EXECUTE_READWRITE)
    nw = write_pm(hp, ba, pb)
    vp_ex(hp, ba, len(pb), op)
    if nw == len(pb):
        log(f"  [OK] sub_4C33FC+0x{co+4:X} 修补成功 ({pd})")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十三] sub_41C120 stream error 检查修补
# ============================================================

def patch_41c120(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0x1C120
    log("\n--- [补丁十三] sub_41C120 stream error 检查修补 ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, 64)
    if nr < 16:
        log(f"  [ERROR] 读取 sub_41C120@0x{av:08X} 失败"); _CloseHandle(hp); return

    lo = -1
    for i in range(min(nr, 32) - 5):
        if buf[i]==0x8B and buf[i+1]==0x4A and buf[i+2]==0x08 and buf[i+3]==0x85 and buf[i+4]==0xC9:
            lo = i; break

    if lo < 0:
        log("  [WARN] 未找到模式, 跳过"); _CloseHandle(hp); return

    if (lo+13>nr or buf[lo+5]!=0x0F or buf[lo+6]!=0x94 or buf[lo+7]!=0xC0
        or buf[lo+8]!=0x83 or buf[lo+9]!=0xE0 or buf[lo+10]!=0x01
        or buf[lo+11]!=0x84 or buf[lo+12]!=0xC0):
        log("  [WARN] sete/and/test 后续不匹配, 跳过"); _CloseHandle(hp); return

    pb = bytes([0xC7,0x42,0x08,0x00,0x00,0x00,0x00, 0xB0,0x01, 0x84,0xC0, 0x90,0x90])
    pa = av + lo
    op = vp_ex(hp, pa, 13, PAGE_EXECUTE_READWRITE)
    nw = write_pm(hp, pa, pb)
    vp_ex(hp, pa, 13, op)
    if nw == 13:
        log(f"  [OK] sub_41C120+0x{lo:X} 清零补丁成功")
    else:
        log(f"  [ERROR] WriteProcessMemory 失败")
    _CloseHandle(hp)

# ============================================================
# [补丁十四] 存档界面队伍头像 hook
# ============================================================

def patch_archive_portrait(cpid: int, base: int, cave_addr: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0x1AB94; ssz = 0x500
    log("\n--- [补丁十四] 存档界面队伍头像 hook ---")
    if cave_addr == 0:
        log("  [WARN] ArchivePortraitCave 未分配, 跳过"); return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, ssz)
    if nr < 64:
        log(f"  [ERROR] 读取 sub_41AB94@0x{av:08X} 失败"); _CloseHandle(hp); return

    ptd = 0
    for i in range(nr - 5):
        if buf[i]==0x66 and buf[i+1]==0x05 and buf[i+2]==0xD3 and buf[i+3]==0x00 and buf[i+4]==0x50:
            hrva = sr + i; ha = base + hrva
            co = (cave_addr - (ha + 5)) & 0xFFFFFFFF
            cd = bytearray(5); cd[0]=0xE8; cd[1:5]=i32b(co)
            op = vp_ex(hp, ha, 5, PAGE_EXECUTE_READWRITE)
            nw = write_pm(hp, ha, bytes(cd))
            vp_ex(hp, ha, 5, op)
            if nw == 5:
                ptd += 1
                log(f"    [OK] RVA 0x{hrva:X}: hook add ax,0xD3+push eax -> cave")

    log(f"  共 hook {ptd} 处")
    _CloseHandle(hp)

# ============================================================
# [补丁十七] 存档界面金钱显示修复
# ============================================================

def patch_gold_display(cpid: int, base: int, log_func=None):
    log = log_func or (lambda x: None)
    sr = 0x1AB94; ssz = 0x600
    log("\n--- [补丁十七] 存档界面金钱显示修复 (signed->unsigned) ---")
    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, cpid)
    if not hp:
        log("  [ERROR] OpenProcess 失败"); return

    av = base + sr
    buf, nr = read_pm(hp, av, ssz)
    if nr < 64:
        log(f"  [ERROR] 读取 sub_41AB94@0x{av:08X} 失败"); _CloseHandle(hp); return

    gp = bytes([0x0F,0xBF,0x84,0x41,0xD4,0x02,0x00,0x00])
    ptd = 0
    for i in range(nr - len(gp) + 1):
        if buf[i:i+len(gp)] == gp:
            ha = base + sr + i
            fix = bytes([0x0F, 0xB7])
            op = vp_ex(hp, ha, 2, PAGE_EXECUTE_READWRITE)
            nw = write_pm(hp, ha, fix)
            vp_ex(hp, ha, 2, op)
            if nw == 2:
                ptd += 1
                log(f"    [OK] RVA 0x{sr + i:05X}: movsx->movzx")

    log(f"  共修补 {ptd} 处")
    _CloseHandle(hp)
