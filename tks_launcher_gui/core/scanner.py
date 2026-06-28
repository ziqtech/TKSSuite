"""模式扫描引擎 — 从 tks_launcher.py 提取"""
import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from .memory import i32b, b2i32


# ============================================================
# PE 节表解析
# ============================================================

@dataclass
class PESection:
    """PE 文件节信息"""
    name: str = ""
    virtual_address: int = 0
    virtual_size: int = 0
    raw_size: int = 0
    characteristics: int = 0


def parse_pe_sections(exe_path: str, log_func=None) -> List[PESection]:
    """解析 PE 文件节表，返回节信息列表

    用于在启动前（进程外）快速判断 EXE 类型和内存布局。
    """
    log = log_func or (lambda x: None)
    sections = []
    try:
        with open(exe_path, 'rb') as f:
            # DOS header
            dos_sig = f.read(2)
            if dos_sig != b'MZ':
                log(f"  [WARN] 非 PE 文件: {exe_path}")
                return sections
            f.seek(0x3C)
            pe_offset = struct.unpack('<I', f.read(4))[0]

            # PE signature
            f.seek(pe_offset)
            pe_sig = f.read(4)
            if pe_sig != b'PE\x00\x00':
                log(f"  [WARN] 无效 PE 签名")
                return sections

            # COFF header
            f.read(2)  # Machine
            num_sections = struct.unpack('<H', f.read(2))[0]
            f.read(12)  # TimeDateStamp, PointerToSymbolTable, NumberOfSymbols
            optional_header_size = struct.unpack('<H', f.read(2))[0]
            f.read(2)  # Characteristics

            # Skip optional header
            f.seek(f.tell() + optional_header_size)

            # Section headers (40 bytes each)
            for _ in range(num_sections):
                sec_data = f.read(40)
                if len(sec_data) < 40:
                    break
                name_raw = sec_data[:8].rstrip(b'\x00').decode('ascii', errors='replace')
                vsize = struct.unpack_from('<I', sec_data, 8)[0]
                vaddr = struct.unpack_from('<I', sec_data, 12)[0]
                raw_size = struct.unpack_from('<I', sec_data, 16)[0]
                chars = struct.unpack_from('<I', sec_data, 36)[0]
                sections.append(PESection(
                    name=name_raw,
                    virtual_address=vaddr,
                    virtual_size=vsize,
                    raw_size=raw_size,
                    characteristics=chars,
                ))
    except Exception as e:
        log(f"  [ERROR] PE 解析失败: {e}")
    return sections


def parse_pe_sections_from_memory(h_proc: int, base_addr: int, log_func=None) -> List[PESection]:
    """从进程内存中解析 PE 节表

    用于运行时检测目标进程的节布局。
    """
    from .memory import read_pm
    log = log_func or (lambda x: None)
    sections = []
    try:
        # 读取 DOS header
        dos_hdr, nr = read_pm(h_proc, base_addr, 0x40)
        if nr < 0x40 or dos_hdr[:2] != b'MZ':
            return sections
        pe_offset = struct.unpack_from('<I', dos_hdr, 0x3C)[0]

        # 读取 PE header + section headers (足够大)
        pe_hdr, nr = read_pm(h_proc, base_addr + pe_offset, 1024)
        if nr < 24 or pe_hdr[:4] != b'PE\x00\x00':
            return sections

        num_sections = struct.unpack_from('<H', pe_hdr, 6)[0]
        optional_header_size = struct.unpack_from('<H', pe_hdr, 20)[0]

        # Section headers start after PE sig(4) + COFF(20) + optional header
        sec_start = 24 + optional_header_size
        for i in range(num_sections):
            off = sec_start + i * 40
            if off + 40 > nr:
                break
            name_raw = pe_hdr[off:off + 8].rstrip(b'\x00').decode('ascii', errors='replace')
            vsize = struct.unpack_from('<I', pe_hdr, off + 8)[0]
            vaddr = struct.unpack_from('<I', pe_hdr, off + 12)[0]
            raw_size = struct.unpack_from('<I', pe_hdr, off + 16)[0]
            chars = struct.unpack_from('<I', pe_hdr, off + 36)[0]
            sections.append(PESection(
                name=name_raw,
                virtual_address=vaddr,
                virtual_size=vsize,
                raw_size=raw_size,
                characteristics=chars,
            ))
    except Exception as e:
        log(f"  [ERROR] 进程内 PE 解析失败: {e}")
    return sections


# ============================================================
# EXE 版本指纹识别
# ============================================================

# 已知第三方 MOD 版本的非标准节名
_KNOWN_MOD_SECTIONS = {
    ".test",      # 孝谈三国3终极版
    ".Silvana",   # 孝谈三国3终极版
}


@dataclass
class ExeProfile:
    """EXE 版本识别结果"""
    name: str = "original"                        # "original" | "xiaotansanguo3" | ...
    display_name: str = "原版"                    # 用于 UI 显示
    has_extra_sections: bool = False              # 是否有额外代码段
    extra_section_ranges: List[Tuple[int, int]] = field(default_factory=list)
    # [(abs_start, abs_end), ...] 额外段的绝对地址范围
    skip_patches: set = field(default_factory=set)  # 应自动跳过的补丁 ID
    hook_conflict_action: str = "skip"            # hook 冲突时默认行为: "skip" | "chain"
    warnings: List[str] = field(default_factory=list)  # 检测过程中的警告


def detect_exe_profile(exe_path: str, base_addr: int = 0x400000,
                       log_func=None) -> ExeProfile:
    """通过 PE 节表和特征码检测 EXE 版本 profile

    Args:
        exe_path:  TKS.exe 文件路径
        base_addr: 模块基址 (默认 0x400000)
        log_func:  日志函数

    Returns:
        ExeProfile 识别结果
    """
    log = log_func or (lambda x: None)
    profile = ExeProfile()

    log("\n--- EXE 版本指纹识别 ---")
    sections = parse_pe_sections(exe_path, log_func=log)
    if not sections:
        log("  [WARN] 无法解析 PE 节表, 按原版处理")
        return profile

    sec_names = {s.name for s in sections}
    log(f"  节表: {[s.name for s in sections]}")

    # 检测额外段
    extra_secs = sec_names & _KNOWN_MOD_SECTIONS
    if extra_secs:
        profile.has_extra_sections = True
        for sec in sections:
            if sec.name in _KNOWN_MOD_SECTIONS:
                abs_start = base_addr + sec.virtual_address
                abs_end = abs_start + sec.virtual_size
                profile.extra_section_ranges.append((abs_start, abs_end))
                log(f"  发现 MOD 段: {sec.name} @ 0x{abs_start:08X}-0x{abs_end:08X}")

    # 根据节特征匹配已知 MOD 版本
    if '.test' in sec_names and '.Silvana' in sec_names:
        profile.name = "xiaotansanguo3"
        profile.display_name = "孝谈三国3终极版"
        # 启动器优先级最高: 不跳过任何补丁, 而是通过 fallback_rva + override 机制覆盖 MOD 已有 hook
        profile.skip_patches = set()  # 不跳过任何补丁
        profile.warnings.append(
            "检测到第三方 MOD 版本 (孝谈三国3终极版)，"
            "启动器补丁将以最高优先级覆盖 MOD 已有修改"
        )
        log(f"  识别为: {profile.display_name}")
        log(f"  策略: 启动器补丁优先级最高, 使用 fallback_rva + override")
    elif extra_secs:
        # 未知的 MOD 版本，但有额外段
        profile.name = "unknown_mod"
        profile.display_name = f"未知MOD版 (含段: {', '.join(extra_secs)})"
        profile.warnings.append(
            f"检测到非标准 PE 段 ({', '.join(extra_secs)})，"
            f"部分补丁可能不兼容"
        )
        log(f"  识别为: {profile.display_name}")
    else:
        log(f"  识别为: 原版 TKS.exe")

    return profile


def detect_exe_profile_runtime(h_proc: int, base_addr: int, module_size: int,
                               log_func=None) -> ExeProfile:
    """运行时从进程内存检测 EXE 版本 profile

    当无法通过文件路径检测时（如加密版子进程），使用此函数。
    """
    log = log_func or (lambda x: None)
    profile = ExeProfile()

    log("\n--- EXE 版本指纹识别 (运行时) ---")
    sections = parse_pe_sections_from_memory(h_proc, base_addr, log_func=log)
    if not sections:
        # Fallback: 通过模块大小粗略判断
        if module_size > 0x700000:  # 原版 ~0x660000, MOD版 ~0xA80000
            profile.name = "unknown_mod"
            profile.display_name = "未知MOD版 (模块过大)"
            profile.has_extra_sections = True
            profile.warnings.append(
                f"模块大小 0x{module_size:X} 超出原版范围，可能为 MOD 版本"
            )
            log(f"  模块大小 0x{module_size:X} 异常, 按 MOD 版处理")
        else:
            log(f"  模块大小正常, 按原版处理")
        return profile

    sec_names = {s.name for s in sections}
    log(f"  节表: {[s.name for s in sections]}")

    extra_secs = sec_names & _KNOWN_MOD_SECTIONS
    if extra_secs:
        profile.has_extra_sections = True
        for sec in sections:
            if sec.name in _KNOWN_MOD_SECTIONS:
                abs_start = base_addr + sec.virtual_address
                abs_end = abs_start + sec.virtual_size
                profile.extra_section_ranges.append((abs_start, abs_end))

    if '.test' in sec_names and '.Silvana' in sec_names:
        profile.name = "xiaotansanguo3"
        profile.display_name = "孝谈三国3终极版"
        profile.skip_patches = set()  # 启动器优先级最高, 不跳过任何补丁
        profile.warnings.append(
            "检测到第三方 MOD 版本 (孝谈三国3终极版)，启动器补丁将以最高优先级覆盖"
        )
        log(f"  识别为: {profile.display_name}")
    elif extra_secs:
        profile.name = "unknown_mod"
        profile.display_name = f"未知MOD版 (含段: {', '.join(extra_secs)})"
        profile.warnings.append(
            f"检测到非标准 PE 段，部分补丁可能不兼容"
        )
        log(f"  识别为: {profile.display_name}")
    else:
        log(f"  识别为: 原版 TKS.exe")

    return profile


def is_addr_in_extra_sections(addr: int, profile: ExeProfile) -> bool:
    """判断地址是否落在 MOD 额外段内"""
    for start, end in profile.extra_section_ranges:
        if start <= addr < end:
            return True
    return False

def parse_pattern(hex_str: str) -> Tuple[bytes, List[bool]]:
    parts = hex_str.split()
    pat = bytearray(len(parts))
    wc = [False] * len(parts)
    for i, p in enumerate(parts):
        if p in ('**', '??'):
            pat[i] = 0
            wc[i] = True
        else:
            pat[i] = int(p, 16)
    return bytes(pat), wc

def pattern_scan(data: bytes, pattern: bytes, wildcard: List[bool]) -> List[int]:
    """模式扫描(优化版): 用 bytes.find 定位首个非通配字节, 再验证完整模式"""
    results = []
    if not pattern or len(data) < len(pattern):
        return results
    pl = len(pattern)
    end = len(data) - pl
    anchor_idx = -1
    for j in range(pl):
        if not wildcard[j]:
            anchor_idx = j
            break
    if anchor_idx < 0:
        return list(range(end + 1))
    anchor_byte = pattern[anchor_idx:anchor_idx + 1]
    pos = 0
    while pos <= end:
        pos = data.find(anchor_byte, pos)
        if pos == -1 or pos > end:
            break
        start = pos - anchor_idx
        if start < 0:
            pos += 1
            continue
        match = True
        for j in range(pl):
            if not wildcard[j] and data[start + j] != pattern[j]:
                match = False
                break
        if match:
            results.append(start)
            pos = start + pl
        else:
            pos += 1
    return results

def value_scan(data: bytes, value: int) -> List[int]:
    """在字节数组中扫描指定 4 字节 LE 值"""
    results = []
    target = i32b(value)
    pos = 0
    end = len(data) - 4
    first = target[0:1]
    while pos <= end:
        pos = data.find(first, pos)
        if pos == -1 or pos > end:
            break
        if data[pos:pos + 4] == target:
            results.append(pos)
            pos += 4
        else:
            pos += 1
    return results

def discover_warpc_base(code_buf: bytes, code_start_addr: int, fallback: int,
                         log_func=None) -> int:
    """
    自动发现 WarPC BSS 基址
    原理: 扫描代码中 150722 (0x24CE2) 的出现, 回溯找附近 BSS 地址
    """
    WARPC_ORIG_SIZE = 150722
    log = log_func or (lambda x: None)

    log("\n--- WarPC BSS 基址自动发现 ---")
    size_hits = value_scan(code_buf, WARPC_ORIG_SIZE)
    log(f"  扫描 150722 (0x{WARPC_ORIG_SIZE:X}): 找到 {len(size_hits)} 处")
    for off in size_hits:
        log(f"    偏移 0x{off:X} (abs 0x{code_start_addr + off:08X})")

    if not size_hits:
        log(f"  [WARN] 未找到 150722, 使用 fallback 0x{fallback:X}")
        return fallback

    candidates: Dict[int, int] = {}
    for off in size_hits:
        for i in range(max(0, off - 24), min(len(code_buf) - 4, off + 8) + 1):
            val = b2i32(code_buf, i)
            if 0x700000 <= val < 0x800000 and (val & 3) == 0 and val != WARPC_ORIG_SIZE:
                candidates[val] = candidates.get(val, 0) + 1

    best_val, best_cnt = fallback, 0
    for v, c in candidates.items():
        log(f"  候选 0x{v:08X}: 出现 {c} 次")
        if c > best_cnt:
            best_val, best_cnt = v, c

    if best_cnt > 0:
        log(f"  发现 WarPC 基址: 0x{best_val:08X} (出现 {best_cnt} 次)")
    else:
        log(f"  [WARN] 未找到候选, 使用 fallback 0x{fallback:X}")
    return best_val
