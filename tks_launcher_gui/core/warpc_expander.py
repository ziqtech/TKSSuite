"""WarPC 缓冲区扩展与 .dat 文件管理 — 从 tks_launcher.py 提取"""
import ctypes
import os
import shutil
from typing import Dict, List, Optional, Tuple
from .memory import (
    i32b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex, write_mem16,
    get_decompressed_size, replace_addr_in_bytes,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE, PAGE_READWRITE,
    MEM_COMMIT, MEM_RESERVE,
    _OpenProcess, _CloseHandle, _VirtualAllocEx,
)
# LZSS (DAT 格式) 与编辑器共用同一实现 (T1 合并, 原 core/lzss.py 已删除)
from editor_utils.lzss import (
    lzss_compress_dat as lzss_compress,
    lzss_decompress_dat as lzss_decompress,
)
from .scanner import value_scan

# ============================================================
# WarPC 常量
# ============================================================

WARPC_BASE = 0x757F08
WARPC_REC_SIZE = 1054
WARPC_ORIG_COUNT = 143
WARPC_ORIG_SIZE = 150722        # 143 * 1054 = 0x24CE2
WARPC_TOTAL_ORIG_SIZE = 159922  # 9200 + 150722 = 0x270D2

DATA_FILE_ORIG_SIZES = {
    "TKMat.dat": 2304000,
    "TKItem.dat": 38400,
    "TKSkill.dat": 32900,
    "TKShop.dat": 1920,
    "TKKon.dat": 26000,
}

# ============================================================
# 存档健康检查
# ============================================================

def ensure_save_directory_healthy(log_func=None):
    r"""补丁十: 确保 save\ 目录存在并清理 0 字节损坏文件"""
    log = log_func or (lambda x: None)
    log("\n--- 存档目录健康检查 ---")
    save_dir = "save"
    if not os.path.isdir(save_dir):
        try:
            os.makedirs(save_dir, exist_ok=True)
            log("  已创建 save\\ 目录")
        except Exception as e:
            log(f"  [WARN] 创建 save\\ 失败: {e}")
            return
    else:
        log("  save\\ 目录已存在")

    del_idx, del_dat = 0, 0
    for i in range(1, 10):
        ip = os.path.join(save_dir, f"{i}.sav")
        dp = os.path.join(save_dir, f"sav.{i}")
        if os.path.isfile(ip):
            sz = os.path.getsize(ip)
            if sz == 0:
                try:
                    os.remove(ip)
                    log(f"  删除损坏的索引文件: {ip} (0 字节)")
                    del_idx += 1
                    if os.path.isfile(dp) and os.path.getsize(dp) < 16:
                        os.remove(dp)
                        log(f"  删除对应的损坏数据文件: {dp}")
                        del_dat += 1
                except Exception as e:
                    log(f"  [WARN] 删除 {ip} 失败: {e}")
            elif sz != 28:
                log(f"  [WARN] {ip} 大小异常: {sz} 字节 (预期 28)")

    if del_idx > 0 or del_dat > 0:
        log(f"  共清理 {del_idx} 个 0 字节索引文件 + {del_dat} 个损坏数据文件")
    else:
        log("  未发现损坏存档文件")

# ============================================================
# 游戏启动前: .dat 文件准备
# ============================================================

def prepare_warpc_for_game(log_func=None) -> Tuple[bool, Optional[bytes], Dict[str, bytes]]:
    """
    检测 .dat 文件大小，对扩展文件创建截断版本
    返回: (expanded, full_data, truncated_files)
    """
    log = log_func or (lambda x: None)

    # 恢复上次残留的 .orig 备份
    for fname in DATA_FILE_ORIG_SIZES:
        bp = fname + ".orig"
        if os.path.isfile(bp):
            shutil.copy2(bp, fname)
            os.remove(bp)
            log(f"  检测到上次未恢复的 {bp}, 已自动恢复")

    expanded = False
    full_data = None
    truncated_files: Dict[str, bytes] = {}

    # WarPC.dat 检测
    wp = "WarPC.dat"
    if os.path.isfile(wp):
        with open(wp, 'rb') as f:
            comp = f.read()
        dec = lzss_decompress(comp)
        cnt = len(dec) // WARPC_REC_SIZE
        if cnt > WARPC_ORIG_COUNT:
            expanded = True
            full_data = dec
            log(f"  WarPC.dat 检测到扩展数据: {cnt} 角色 (原始 {WARPC_ORIG_COUNT})")
            tr = dec[:WARPC_ORIG_SIZE]
            tc = lzss_compress(tr)
            bp = wp + ".orig"
            if not os.path.isfile(bp):
                shutil.copy2(wp, bp)
            truncated_files[wp] = comp
            with open(wp, 'wb') as f:
                f.write(tc)
            log(f"  已创建截断版 WarPC.dat ({WARPC_ORIG_COUNT} 角色), 备份为 .orig")

    # 其他 .dat 检测
    for fname, osz in DATA_FILE_ORIG_SIZES.items():
        if fname == "WarPC.dat" or not os.path.isfile(fname):
            continue
        asz = get_decompressed_size(fname)
        if asz > osz:
            log(f"  [WARN] {fname} 解压大小 {asz} > 原始 {osz}")
            with open(fname, 'rb') as f:
                comp = f.read()
            dec = lzss_decompress(comp)
            tr = dec[:min(len(dec), osz)]
            tc = lzss_compress(tr)
            bp = fname + ".orig"
            if not os.path.isfile(bp):
                shutil.copy2(fname, bp)
            truncated_files[fname] = comp
            with open(fname, 'wb') as f:
                f.write(tc)
            log(f"  已创建截断版 {fname} ({osz}B), 备份为 .orig")
        elif asz >= 0:
            log(f"  {fname}: 解压大小 {asz} = 原始值, OK")

    return expanded, full_data, truncated_files

# ============================================================
# 运行时内存操作
# ============================================================

def scan_and_patch_const(h_proc: int, scan_start: int, scan_size: int,
                          old_val: int, new_val: int) -> Tuple[int, List[int]]:
    """扫描并修补 4 字节常量"""
    pr: List[int] = []
    ole = i32b(old_val)
    nle = i32b(new_val)
    buf, nr = read_pm(h_proc, scan_start, scan_size)
    if nr <= 0:
        return 0, []
    cnt = 0
    pos = 0
    end = min(nr, scan_size) - 4
    first = ole[0:1]
    while pos <= end:
        pos = buf.find(first, pos)
        if pos == -1 or pos > end:
            break
        if buf[pos:pos+4] == ole:
            aa = scan_start + pos
            op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
            nw = write_pm(h_proc, aa, nle)
            vp_ex(h_proc, aa, 4, op)
            if nw == 4:
                cnt += 1
                pr.append(aa)
            pos += 4
        else:
            pos += 1
    return cnt, pr

def patch_data_file_sizes(h_proc: int, base_addr: int, scan_start: int,
                           scan_size: int, log_func=None):
    """补丁七: 修补 .dat 文件大小常量"""
    log = log_func or (lambda x: None)
    log("\n--- 数据文件大小常量修补 ---")
    for fname, osz in DATA_FILE_ORIG_SIZES.items():
        asz = get_decompressed_size(fname)
        if asz <= osz:
            continue
        bp = fname + ".orig"
        if not os.path.isfile(bp):
            continue
        shutil.copy2(bp, fname)
        os.remove(bp)
        log(f"  已恢复原始 {fname}")
        patched, rvas = scan_and_patch_const(h_proc, scan_start, scan_size, osz, asz)
        if patched > 0:
            log(f"  [OK] {fname}: {osz} -> {asz}, 修补 {patched} 处")
        else:
            log(f"  [WARN] {fname}: 未找到 {osz} (0x{osz:X}) 引用")

def expand_warpc_buffer(child_pid: int, base_addr: int, module_size: int,
                         cave_addr: int, code_buf: bytearray, code_start_addr: int,
                         new_buf: int, full_data: bytes, log_func=None,
                         exclude_ranges: list = None,
                         warpc_base: Optional[int] = None,
                         warpc_rec_size: Optional[int] = None) -> dict:
    """补丁五/六/七/八/十一: WarPC 缓冲区动态扩展

    Args:
        exclude_ranges: [(abs_start, abs_end), ...] 排除区域列表
                        (第三方 MOD 自有代码段, value_scan 时跳过)
    """
    log = log_func or (lambda x: None)
    ns = len(full_data)
    access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    hp = _OpenProcess(access, False, child_pid)
    if not hp:
        log("  [ERROR] 无法打开进程进行 WarPC 扩展")
        return {}

    diag: List[str] = []
    nb = new_buf
    if warpc_base is None:
        warpc_base = WARPC_BASE
    if warpc_rec_size is None:
        warpc_rec_size = WARPC_REC_SIZE
    log(f"  修补代码引用: 缓冲区 0x{nb:08X}, 大小 {ns}")

    nal = i32b(nb)
    nsl = i32b(ns)
    ap, sp, fp, a0p = 0, 0, 0, 0
    ss = code_start_addr
    ssz = len(code_buf)
    _excl = exclude_ranges or []

    def _in_exclude(off: int) -> bool:
        """检查偏移对应的绝对地址是否在排除区域内"""
        if not _excl:
            return False
        abs_a = ss + off
        for ex_start, ex_end in _excl:
            if ex_start <= abs_a < ex_end:
                return True
        return False

    # WarPC 基址修补
    # 安全排除: 跳过 E8/E9 指令的 rel32 偶然匹配 + MOD 额外段
    for off in value_scan(bytes(code_buf), warpc_base):
        if off >= 1 and code_buf[off - 1] in (0xE8, 0xE9):
            continue
        if _in_exclude(off):
            continue
        write_pm(hp, ss + off, nal)
        code_buf[off:off+4] = nal
        ap += 1
    log(f"  WarPC 基址 0x{warpc_base:08X} 扫描: 找到 {ap} 处")

    # word_757F0C 修补
    w0c = warpc_base + 4
    n0c = i32b(nb + 4)
    for off in value_scan(bytes(code_buf), w0c):
        if off >= 1 and code_buf[off - 1] in (0xE8, 0xE9):
            continue
        if _in_exclude(off):
            continue
        aa = ss + off
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        write_pm(hp, aa, n0c)
        vp_ex(hp, aa, 4, op)
        code_buf[off:off+4] = n0c
        a0p += 1
    log(f"  word_757F0C 修补: {a0p} 处")

    # 字段基址修补
    # 启发式扫描: 找到 \x75\x00 标记后回退 2 字节读 4 字节地址,
    # 判断是否落在 WarPC 第一条记录的字段范围内.
    # 安全排除: 如果 4 字节前一字节是 E8(call) 或 E9(jmp) 操作码,
    # 说明该 4 字节是相对偏移 (rel32) 而非地址引用, 必须跳过.
    rs, re = warpc_base, warpc_base + warpc_rec_size
    pos = 0
    end = ssz - 4
    marker = b'\x75\x00'
    code_bytes = bytes(code_buf)
    while pos <= end:
        pos = code_bytes.find(marker, pos)
        if pos == -1 or pos > end:
            break
        read_pos = pos - 2
        if read_pos >= 0:
            # 安全检查: read_pos - 1 为 E8/E9 则该 4 字节是 call/jmp 的 rel32, 跳过
            if read_pos >= 1 and code_buf[read_pos - 1] in (0xE8, 0xE9):
                pos += 1
                continue
            if _in_exclude(read_pos):
                pos += 1
                continue
            v = b2i32(code_bytes, read_pos)
            if rs <= v < re:
                ofs = v - warpc_base
                nv = nb + ofs
                write_pm(hp, ss + read_pos, i32b(nv))
                code_buf[read_pos:read_pos+4] = i32b(nv)
                fp += 1
                pos += 4
            else:
                pos += 1
        else:
            pos += 1
    log(f"  字段基址修补: {fp} 处")

    # 大小常量修补
    for off in value_scan(bytes(code_buf), WARPC_ORIG_SIZE):
        aa = ss + off
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        wok = write_pm(hp, aa, nsl)
        vp_ex(hp, aa, 4, op)
        if wok == 4: sp += 1
    log(f"  WarPC 大小常量修补: {sp} 处")

    # [补丁六] 存档/读档缓冲区
    tos = WARPC_TOTAL_ORIG_SIZE
    tns = 9200 + ns
    tnl = i32b(tns)
    tp = 0
    for off in value_scan(bytes(code_buf), tos):
        aa = ss + off
        op = vp_ex(hp, aa, 4, PAGE_EXECUTE_READWRITE)
        wok = write_pm(hp, aa, tnl)
        vp_ex(hp, aa, 4, op)
        if wok == 4:
            tp += 1
            log(f"  [OK] 存档缓冲区 RVA 0x{aa - base_addr:X}: {tos} -> {tns}")

    # [补丁七] 其他 .dat
    patch_data_file_sizes(hp, base_addr, ss, ssz, log_func=log)

    # [补丁八] 新角色备份
    es = WARPC_ORIG_COUNT * WARPC_REC_SIZE  # 备份偏移按原始记录大小计算
    exs = ns - es
    bbp = 0
    if exs > 0:
        bpv = _VirtualAllocEx(hp, None, exs, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if bpv:
            bbp = ctypes.cast(bpv, ctypes.c_void_p).value or 0
            write_pm(hp, bbp, full_data[es:es+exs])
            log(f"  新角色备份: 0x{bbp:08X} ({exs} 字节)")

    _CloseHandle(hp)
    log(f"  已修补: {ap}个基址(08) + {a0p}个基址(0C) + {fp}个字段基址 + {sp}个大小常量")
    return {
        "addr08": ap, "addr0C": a0p, "field": fp, "size": sp,
        "save_buf": tp, "backup_buf": bbp, "extra_size": exs
    }

def inject_warpc_data(child_pid: int, warpc_base: int, expanded: bool, log_func=None):
    """注入 WORD[260]/WORD[261] 自定义值"""
    log = log_func or (lambda x: None)
    if expanded:
        log("  Data inject: 已通过 ExpandWarPcBuffer 完成")
        return

    wp = "WarPC.dat"
    if not os.path.isfile(wp):
        log("  [WARN] WarPC.dat not found, skip data inject")
        return
    with open(wp, 'rb') as f:
        comp = f.read()
    dec = lzss_decompress(comp)
    if len(dec) < WARPC_ORIG_SIZE:
        log("  [WARN] WarPC.dat decompressed size mismatch")
        return

    hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, child_pid)
    if not hp:
        return

    wc, pc = 0, 0
    cnt = min(len(dec)//WARPC_REC_SIZE, WARPC_ORIG_COUNT)
    for i in range(cnt):
        bo = i * WARPC_REC_SIZE
        w260 = b2u16(dec, bo + 520)
        if w260 and write_mem16(hp, warpc_base + bo + 520, w260):
            wc += 1
        w261 = b2u16(dec, bo + 522)
        if w261 and write_mem16(hp, warpc_base + bo + 522, w261):
            pc += 1

    _CloseHandle(hp)
    log(f"  Data inject: {wc} W260, {pc} W261")
