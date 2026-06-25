"""补丁应用引擎 — 从 tks_launcher.py 提取 & 重组"""
import os
import json
import struct
from typing import List, Dict, Optional
from .memory import (
    i32b, i16b, b2i32, b2u16, bhex,
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
# Cave 模板: 召唤多随机 (224~231)
# 逆向依据: sub_444BB0 @0x444C83 查表指令; sub_452AC0 rand(n)->0..n-1
# hook 点 0x444C83 (movsx edx,byte[eax+0x4EB6F0], 7字节) -> E8 rel32 + 90 90
# cave 末尾 ret 回 0x444C8A (mov [ebp-2],dx 由原指令写回)
# count=0 走原查表 (向后兼容); count=N 调 sub_452AC0(N) 随机选 cand[0..N-1]
# 唯一动态重定位点: TABLE_BASE 占位符 0x52414E44 (cave 内出现 1 次)
# ============================================================

SUMMON_RANDOM_PLACEHOLDER = 0x52414E44   # "RAND", cave 内唯一, 指向 72 字节候选表

CAVE_SUMMON_RANDOM = bytes([
    0x53,                                              # 0  push ebx
    0x56,                                              # 1  push esi
    0x0F,0xBF,0x1D,0x7C,0x6C,0x9D,0x00,                # 2  movsx ebx, word[0x9D6C7C]
    0x81,0xEB,0xE0,0x00,0x00,0x00,                     # 9  sub ebx, 0xE0  (imm32! 避免 imm8 符号扩展, idx 224..231 -> 0..7)
    0x6B,0xDB,0x09,                                    # 15 imul ebx, ebx, 9       (entry 9 字节)
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 18 add ebx, TABLE_BASE   <- 占位符 (imm32 立即数加, 非[mem]解引用)
    0x8B,0xF3,                                         # 24 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 26 movzx ecx, byte[esi]   (count)
    0x85,0xC9,                                         # 29 test ecx, ecx
    0x74,0x1B,                                         # 31 jz  .default(60)
    0x83,0xF9,0x01,                                    # 33 cmp ecx, 1
    0x76,0x10,                                         # 36 jbe .single(54)
    0x51,                                              # 38 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 39 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 44 call eax               (rand(count))
    0x59,                                              # 46 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 47 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x14,                                         # 52 jmp .done(74)
    0x0F,0xB6,0x56,0x01,                               # 54 .single: movzx edx, byte[esi+1]
    0xEB,0x0E,                                         # 58 jmp .done(74)
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,                # 60 .default: movsx eax, word[0x9D6C7C]
    0x0F,0xBE,0x90,0xF0,0xB6,0x4E,0x00,                # 67 movsx edx, byte[eax+0x4EB6F0]  (原查表)
    0x5E,                                              # 74 .done: pop esi
    0x5B,                                              # 75 pop ebx
    0xC3,                                              # 76 ret
])

# ============================================================
# Cave 模板: 召唤多随机 阶段二/三 (222/251)
# 与阶段一区别: 222/251 hook 点之后不经 mov[ebp-2],dx, 故 cave 自行写 [ebp-2]
# 合并三段: entry_222(entry8) + entry_251(entry9) + shared(随机选 cand, 写[ebp-2])
# entry_222/entry_251 仅设 entry 常数后 jmp shared; shared 内 rand 选 cand -> [ebp-2]
# 仅在配了 skill_222_random/skill_251_random 时启用对应 hook (count>=1, 无 default 分支)
# ============================================================

CAVE_SUMMON_RANDOM_222_251 = bytes([
    # entry_222 @0  (hook 0x444C9C, ret->0x444CA2 jmp 0x444CCF)
    0x53,                                              # 0  push ebx
    0xBB,0x08,0x00,0x00,0x00,                          # 1  mov ebx, 8            (entry 8)
    0xEB,0x08,                                         # 6  jmp shared(16)
    # entry_251 @8  (hook 0x444CB3, ret->0x444CB8 NOP->0x444CCF)
    0x53,                                              # 8  push ebx
    0xBB,0x09,0x00,0x00,0x00,                          # 9  mov ebx, 9            (entry 9)
    0xEB,0x00,                                         # 14 jmp shared(16)
    # shared @16
    0x56,                                              # 16 push esi
    0x6B,0xDB,0x09,                                    # 17 imul ebx, ebx, 9
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 20 add ebx, TABLE_BASE   <- 占位符 (imm32)
    0x8B,0xF3,                                         # 26 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 28 movzx ecx, byte[esi]  (count, >=1)
    0x83,0xF9,0x01,                                    # 31 cmp ecx, 1
    0x76,0x10,                                         # 34 jbe .single(52)
    0x51,                                              # 36 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 37 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 42 call eax              (rand(count))
    0x59,                                              # 44 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 45 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x04,                                         # 50 jmp .write(56)
    0x0F,0xB6,0x56,0x01,                               # 52 .single: movzx edx, byte[esi+1]
    0x66,0x89,0x55,0xFE,                               # 56 .write: mov [ebp-2], dx
    0x5E,                                              # 60 pop esi
    0x5B,                                              # 61 pop ebx
    0xC3,                                              # 62 ret
])

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
# 补丁类型: patch_summon_table (召唤表自定义)
# 逆向依据: sub_444BB0 召唤角色选择; stru_4EB6F0 区域 .data 8字节 (技能224~231)
#           + sub_444BB0 内 3 处 imm16 立即数 (技能222/251_a/251_b)
# JSON 值为 WarPC 索引 (= i+36), 写入时换算 i = WarPC-36
# ============================================================

def apply_summon_table(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       base_addr: int, h_proc: int, variables: Dict[str, int],
                       log_func=None, cave_addr: int = 0) -> bool:
    log = log_func or (lambda x: None)
    all_ok = True

    # Step 0: 读取召唤表 JSON
    if not defn.json_file or not os.path.isfile(defn.json_file):
        log(f"    [WARN] 召唤表 JSON 不存在: {defn.json_file!r}, 跳过")
        return True
    try:
        with open(defn.json_file, 'r', encoding='utf-8') as f:
            summon = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析召唤表 JSON 失败: {e}")
        return False
    log(f"    JSON: {len(summon)} 个键")

    # Step 1: WarPC 记录数上限 (用于值域校验)
    rec_size = variables.get("warpc_rec_size", 1054)
    new_size = variables.get("warpc_new_size", 150722)
    max_count = new_size // rec_size if rec_size > 0 else 143

    def _warpc_i(warpc_idx, imm16):
        if not isinstance(warpc_idx, (int,)):
            return None, f"非整数: {warpc_idx!r}"
        if warpc_idx < 36 or warpc_idx >= max_count:
            return None, f"WarPC索引 {warpc_idx} 越界 (36..{max_count-1})"
        i = warpc_idx - 36
        limit = 65535 if imm16 else 255
        if i < 0 or i > limit:
            return None, f"i值 {i} 越界 (0..{limit})"
        return i, None

    # Step 2: 写 .data 8 字节 (技能 224~231) — .data 段通常 PAGE_READWRITE
    if defn.data_rva and defn.data_keys:
        tbl_abs = base_addr + defn.data_rva
        tbl_off = defn.data_rva - 0x1000
        if tbl_off < 0 or tbl_off + 8 > len(code_buf):
            log(f"  [ERROR] .data 偏移越界")
            all_ok = False
        else:
            cur = bytearray(code_buf[tbl_off:tbl_off + 8])
            changed = False
            for k, key in enumerate(defn.data_keys):
                if key not in summon:
                    continue
                i, err = _warpc_i(summon[key], imm16=False)
                if err:
                    log(f"    [WARN] {key}: {err}, 跳过")
                    continue
                if cur[k] != (i & 0xFF):
                    log(f"    {key}: i {cur[k]}->{i & 0xFF} (WarPC {cur[k]+36}->{summon[key]})")
                    changed = True
                cur[k] = i & 0xFF
            if changed:
                nw = write_pm(h_proc, tbl_abs, bytes(cur))
                code_buf[tbl_off:tbl_off + 8] = bytes(cur)
                log(f"    [OK] .data @0x{tbl_abs:08X} 写入{nw}/{len(cur)}字节")
                if nw != len(cur):
                    all_ok = False
            else:
                log(f"    -> .data 与默认值一致")

    # Step 3: 写代码段 imm16 — 自开进程句柄写入，不依赖传入的 h_proc
    _pid = variables.get("_target_pid", 0)
    if not _pid:
        log("  [WARN] 缺少 target_pid, 跳过 imm16 补丁")
        return all_ok
    _hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                        False, _pid)
    if not _hp:
        log(f"  [WARN] OpenProcess(PID={_pid}) 失败, 跳过 imm16 补丁")
        return all_ok

    for site in defn.code_addrs:
        key = site.get("key", "")
        rva_str = site.get("rva", "")
        if not key or not rva_str:
            continue
        rva = int(rva_str, 16) if isinstance(rva_str, str) else int(rva_str)
        abs_addr = base_addr + rva
        if key not in summon:
            continue
        i, err = _warpc_i(summon[key], imm16=True)
        if err:
            log(f"    [WARN] {key}: {err}, 跳过")
            continue
        imm = i16b(i)
        nw = write_pm(_hp, abs_addr, imm)
        if nw == 2:
            log(f"    [OK] {key} i={i} @abs 0x{abs_addr:08X}")
        else:
            log(f"  [FAIL] {key}: WriteProcessMemory 失败 @abs 0x{abs_addr:08X}")
            all_ok = False
        cb_off = abs_addr - code_start_addr
        if 0 <= cb_off + 2 <= len(code_buf):
            code_buf[cb_off:cb_off + 2] = imm

    # Step 4: 多随机 cave 注入 (skill_224~231 的 *_random 列表)
    # 复用 Step 3 自开句柄 _hp — 传入的 h_proc 在 patcher_worker 分配 cave 后已被 CloseHandle, 不可用
    # data_keys 顺序 = entry 顺序 (224~231 -> entry 0~7); 列表键名 = data_keys[k] + "_random"
    rnd_pat_str = defn.random_hook_pattern
    if rnd_pat_str and defn.random_cave_offset and defn.random_table_offset:
        if not cave_addr:
            log("  [WARN] 无 cave 内存, 跳过多随机注入")
        else:
            all_ok &= _apply_summon_random(defn, summon, code_buf, code_start_addr,
                                            _hp, cave_addr, _warpc_i, log)

    _CloseHandle(_hp)
    return all_ok


def _apply_summon_random(defn: PatchDef, summon: dict, code_buf: bytearray,
                         code_start_addr: int, h_proc: int, cave_addr: int,
                         warpc_i_fn, log_func=None) -> bool:
    """多随机 cave: 读 *_random 列表 -> 90字节候选表 + cave代码 + hooks
    阶段一: 224~231 (entry 0~7, entry_224 cave, hook 0x444C84, 结果->edx)
    阶段二: 222 (entry 8, 合并 cave entry_222, hook 0x444C9C, 结果->[ebp-2])
    阶段三: 251 (entry 9, 合并 cave entry_251, hook 0x444CB3, 结果->[ebp-2])"""
    log = log_func or (lambda x: None)

    # 4a. 收集候选列表 -> 90 字节候选表 (entry 0~7=224~231, 8=222, 9=251)
    table = bytearray(90)        # 10 entry x 9 字节
    any_random = False
    has_224 = False              # 224~231 任一配了 -> 需阶段一 cave+hook
    extra_hooks_to_apply = []    # 阶段二/三: [{entry_idx, ...hook_cfg}]

    def collect(rkey, entry_idx):
        nonlocal any_random, has_224
        lst = summon.get(rkey)
        if not isinstance(lst, list) or not lst:
            return False
        if len(lst) > 8:
            log(f"    [WARN] {rkey}: 候选 {len(lst)} > 8, 截断为 8")
            lst = lst[:8]
        cand = []
        for w in lst:
            ii, err = warpc_i_fn(w, imm16=False)   # i 值域 0..255 (byte 存储)
            if err:
                log(f"    [WARN] {rkey}: WarPC {w} {err}, 跳过该技能随机")
                return False
            cand.append(ii & 0xFF)
        table[entry_idx * 9] = len(cand)
        for j, c in enumerate(cand):
            table[entry_idx * 9 + 1 + j] = c
        any_random = True
        log(f"    {rkey}: {len(cand)} 候选 i={cand} (WarPC={[c + 36 for c in cand]})")
        return True

    # 阶段一: 224~231 (entry 0~7)
    for k, key in enumerate(defn.data_keys):
        if collect(key + "_random", k):
            has_224 = True

    # 阶段二/三: 222 (entry 8) / 251 (entry 9), 按 random2_hooks 配置收集
    for hk in defn.random2_hooks:
        jkey = hk.get("json_key", "")
        eidx = hk.get("entry_idx", 0)
        if collect(jkey, eidx):
            extra_hooks_to_apply.append(hk)

    if not any_random:
        log("    -> 无 *_random 配置, 跳过多随机 cave")
        return True

    # 4b. 写 90 字节候选表
    table_abs = cave_addr + defn.random_table_offset
    if write_pm(h_proc, table_abs, bytes(table)) != len(table):
        log(f"  [FAIL] 候选表写入失败 @0x{table_abs:08X}")
        return False
    log(f"    [OK] 候选表 @0x{table_abs:08X} (90 字节)")

    all_ok = True

    # 4c. 阶段一: entry_224 cave + hook 0x444C84 (结果->edx, 由原 mov[ebp-2],dx 写回)
    if has_224:
        all_ok &= _write_cave_and_hook(
            CAVE_SUMMON_RANDOM, defn.random_cave_offset, 0,           # cave 代码, 入口偏移 0
            defn.random_hook_pattern, defn.random_hook_size, defn.random_hook_expect_count,
            table_abs, code_buf, code_start_addr, h_proc, cave_addr,
            warpc_i_fn, log, tag="224~231")

    # 4d. 阶段二/三: 合并 cave (entry_222+entry_251+shared) + 各 hook
    if extra_hooks_to_apply:
        cave2_abs = cave_addr + defn.random2_cave_offset
        cave2_code = bytearray(CAVE_SUMMON_RANDOM_222_251)
        if cave2_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] 阶段二/三 cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave2_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        if write_pm(h_proc, cave2_abs, bytes(cave2_code)) != len(cave2_code):
            log(f"  [FAIL] 阶段二/三 cave 代码写入失败 @0x{cave2_abs:08X}")
            return False
        log(f"    [OK] 阶段二/三 cave @0x{cave2_abs:08X} ({len(cave2_code)} 字节)")
        for hk in extra_hooks_to_apply:
            all_ok &= _write_cave_and_hook(
                None, defn.random2_cave_offset, hk.get("entry_offset", 0),  # 复用已写 cave, 仅 hook
                hk.get("pattern", ""), hk.get("hook_size", 0), hk.get("expect_count", 0),
                table_abs, code_buf, code_start_addr, h_proc, cave_addr,
                warpc_i_fn, log, tag=hk.get("json_key", ""),
                prewritten_cave_abs=cave2_abs)

    return all_ok


def _write_cave_and_hook(cave_template: Optional[bytes], cave_offset: int, entry_offset: int,
                         hook_pattern: str, hook_size: int, expect_count: int,
                         table_abs: int, code_buf: bytearray, code_start_addr: int,
                         h_proc: int, cave_addr: int, warpc_i_fn, log_func,
                         tag: str = "", prewritten_cave_abs: int = 0) -> bool:
    """写 cave 代码 (若提供 template) + 写 hook. cave 入口 = cave_addr+cave_offset+entry_offset.
    prewritten_cave_abs>0 时跳过 cave 写入 (复用已写代码), 仅写 hook 指向该地址+entry_offset."""
    log = log_func or (lambda x: None)

    # 写 cave 代码 (阶段一); 阶段二/三复用已写合并代码
    if cave_template is not None:
        cave_code = bytearray(cave_template)
        if cave_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] [{tag}] cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        cave_abs = cave_addr + cave_offset
        if write_pm(h_proc, cave_abs, bytes(cave_code)) != len(cave_code):
            log(f"  [FAIL] [{tag}] cave 代码写入失败 @0x{cave_abs:08X}")
            return False
        log(f"    [OK] [{tag}] cave 代码 @0x{cave_abs:08X} ({len(cave_code)} 字节, TABLE_BASE->0x{table_abs:08X})")
    else:
        cave_abs = prewritten_cave_abs

    hook_target = cave_abs + entry_offset   # call 目标 (阶段二/三为合并 cave 内入口)

    # 写 hook: E8 rel32 + NOP 填充
    if not hook_pattern or not hook_size:
        log(f"  [WARN] [{tag}] 无 hook 配置, 跳过")
        return True
    pat, wc = parse_pattern(hook_pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    if expect_count > 0 and len(hits) != expect_count:
        log(f"  [WARN] [{tag}] hook 匹配 {len(hits)} 处 (预期 {expect_count}), 跳过")
        return False
    if not hits:
        log(f"  [WARN] [{tag}] hook 模式无匹配, 跳过")
        return False

    hsz = hook_size
    for off in hits:
        ha = code_start_addr + off
        co = (hook_target - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(hsz)
        ci[0] = 0xE8
        ci[1:5] = i32b(co)
        for i in range(5, hsz):
            ci[i] = 0x90
        op = vp_ex(h_proc, ha, hsz, PAGE_EXECUTE_READWRITE)
        nw = write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, hsz, op)
        if nw != hsz:
            log(f"  [FAIL] [{tag}] hook 写入失败 @RVA 0x{off:X}")
            return False
        for i in range(min(hsz, len(code_buf) - off)):
            code_buf[off + i] = ci[i]
        log(f"    [OK] [{tag}] hook @RVA 0x{off:X} (abs 0x{ha:08X}) -> cave 0x{hook_target:08X}")
    return True

# ============================================================
# 配置补丁编排
# ============================================================

def apply_config_patches(config: PatchConfig, code_buf: bytearray, code_start_addr: int,
                          base_addr: int, h_proc: int, warpc_base: int, cave_addr: int,
                          variables: Dict[str, int], log_func=None,
                          minimal_mode=False, no_cave_mode=False,
                          only_portrait=False, only_awk=False,
                          selected_patches: set = None) -> bool:
    log = log_func or (lambda x: None)
    all_ok = True
    pch: List[PatchDef] = []

    for defn in config.patches:
        tag = f"[{defn.id}]"
        log(f"\n  {tag}: {defn.desc}")

        if selected_patches is not None and defn.optional and defn.id not in selected_patches:
            log(f"    -> 用户取消勾选, 跳过")
            continue

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
        elif defn.type == "patch_summon_table":
            all_ok &= apply_summon_table(defn, code_buf, code_start_addr, base_addr,
                                          h_proc, variables, log_func=log,
                                          cave_addr=cave_addr)
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
