"""模式扫描引擎 — 从 tks_launcher.py 提取"""
import json
import os
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .memory import b2i32, i32b, read_pm


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


# ============================================================
# Phase 13: ExeProfile 持久化缓存
# ============================================================
#
# 设计:
# - 缓存键: <exe_sha1> (前 1MB 文件内容的 SHA1)
# - 缓存文件: <cache_dir>/profile_<sha1>.json
# - 缓存内容: ExeProfile 的所有字段 (name, display_name, has_extra_sections, etc.)
# - 收益: 二次启动 -80ms (跳过 PE 节表解析 + 特征码扫描)
#
# 用法:
#     profile = ExeProfileCache.load_or_detect(exe_path, base_addr, log_func)

DEFAULT_PROFILE_CACHE_DIR = "launcher_cache"


def _compute_exe_sha1(exe_path: str, max_bytes: int = 1024 * 1024) -> str:
    """计算 EXE 前 1MB 的 SHA1 (足够识别, 避免大文件)。"""
    import hashlib
    h = hashlib.sha1()
    try:
        with open(exe_path, 'rb') as f:
            h.update(f.read(max_bytes))
        # 同时包含文件总大小, 区分前 1MB 相同但尾部不同的文件
        h.update(str(os.path.getsize(exe_path)).encode())
    except Exception:
        # 文件读取失败时返回占位 SHA1, 触发重新检测
        return "unreadable"
    return h.hexdigest()


def _profile_to_dict(profile: 'ExeProfile') -> dict:
    """ExeProfile → JSON 可序列化 dict。"""
    return {
        "name": profile.name,
        "display_name": profile.display_name,
        "has_extra_sections": profile.has_extra_sections,
        "extra_section_ranges": [list(r) for r in profile.extra_section_ranges],
        "skip_patches": list(profile.skip_patches),
        "hook_conflict_action": profile.hook_conflict_action,
        "warnings": list(profile.warnings),
    }


def _profile_from_dict(d: dict) -> 'ExeProfile':
    """JSON dict → ExeProfile。"""
    p = ExeProfile()
    p.name = d.get("name", "original")
    p.display_name = d.get("display_name", "原版")
    p.has_extra_sections = d.get("has_extra_sections", False)
    ranges_raw = d.get("extra_section_ranges", [])
    p.extra_section_ranges = [(int(s), int(e)) for s, e in ranges_raw]
    p.skip_patches = set(d.get("skip_patches", []))
    p.hook_conflict_action = d.get("hook_conflict_action", "skip")
    p.warnings = list(d.get("warnings", []))
    return p


class ExeProfileCache:
    """ExeProfile 检测结果持久化缓存 (Phase 13)。"""

    def __init__(self, cache_dir: str = DEFAULT_PROFILE_CACHE_DIR):
        self.cache_dir = cache_dir

    @staticmethod
    def load(exe_path: str, cache_dir: str = DEFAULT_PROFILE_CACHE_DIR,
             log_func=None) -> Optional['ExeProfile']:
        """从磁盘加载缓存的 ExeProfile。命中且 SHA1 一致时返回, 否则 None。"""
        log = log_func or (lambda x: None)
        try:
            sha1 = _compute_exe_sha1(exe_path)
            cache_file = os.path.join(cache_dir, f"profile_{sha1}.json")
            if not os.path.isfile(cache_file):
                return None
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("exe_sha1") != sha1:
                return None
            log(f"  [PROFILE-CACHE-HIT] {os.path.basename(exe_path)} -> {data.get('profile', {}).get('name', '?')}")
            return _profile_from_dict(data.get("profile", {}))
        except Exception:
            return None

    @staticmethod
    def save(exe_path: str, profile: 'ExeProfile',
             cache_dir: str = DEFAULT_PROFILE_CACHE_DIR,
             log_func=None) -> bool:
        """将 ExeProfile 持久化到磁盘。"""
        log = log_func or (lambda x: None)
        try:
            sha1 = _compute_exe_sha1(exe_path)
            if sha1 == "unreadable":
                return False
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, f"profile_{sha1}.json")
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "exe_sha1": sha1,
                    "version": 1,
                    "profile": _profile_to_dict(profile),
                }, f, ensure_ascii=False)
            log(f"  [PROFILE-CACHE-SAVE] {os.path.basename(exe_path)} -> {profile.name}")
            return True
        except Exception:
            return False

    @staticmethod
    def load_or_detect(exe_path: str, base_addr: int = 0x400000,
                       cache_dir: str = DEFAULT_PROFILE_CACHE_DIR,
                       log_func=None) -> 'ExeProfile':
        """优先加载磁盘缓存; 未命中 → 检测 + 自动保存。"""
        cached = ExeProfileCache.load(exe_path, cache_dir=cache_dir, log_func=log_func)
        if cached is not None:
            return cached
        profile = detect_exe_profile(exe_path, base_addr=base_addr, log_func=log_func)
        ExeProfileCache.save(exe_path, profile, cache_dir=cache_dir, log_func=log_func)
        return profile


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


# ============================================================
# Phase 11: 模式扫描结果 LRU 缓存
# ============================================================
#
# 设计:
# - 缓存键: (pattern_hex, data_hash)   pattern = "55 8B EC 83 EC 60"; data_hash = sha1(data)
# - 缓存值: List[int] (命中偏移列表)
# - 内存 LRU: OrderedDict 实现, max_entries 控制
# - 磁盘持久化: save_cache/load_cache, 路径 = cache_dir/<exe_sha1>_pattern_cache.json
#
# 用法:
#     cache = PatternScanCache(max_entries=128, exe_sha1=exe_sha1)
#     cache.load_from_disk()
#     hits = cache.get_or_scan(pattern_bytes, wildcard_list, data_bytes, pattern_scan_fn)
#
# 收益: 第二次启动时间 -50% (cache_dir 下文件存在即可命中)

class PatternScanCache:
    """模式扫描结果 LRU 缓存 (Phase 11)。"""

    DEFAULT_MAX_ENTRIES = 128
    DEFAULT_CACHE_DIR = ".pattern_cache"

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES,
                 exe_sha1: str = "", cache_dir: str = DEFAULT_CACHE_DIR):
        self.max_entries = max_entries
        self.exe_sha1 = exe_sha1
        self.cache_dir = cache_dir
        self._mem_cache: "OrderedDict[Tuple[str, str], List[int]]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _data_hash(data: bytes) -> str:
        """短哈希: 取前 64KB 的 SHA1 + 数据总长度, 避免对大文件计算完整 SHA1。"""
        import hashlib
        h = hashlib.sha1()
        h.update(str(len(data)).encode())
        # 只哈希前 64KB + 后 64KB (覆盖大部分模式扫描区间)
        if len(data) <= 131072:
            h.update(data)
        else:
            h.update(data[:65536])
            h.update(data[-65536:])
        return h.hexdigest()[:16]

    @staticmethod
    def _pattern_key(pattern: bytes, wildcard: List[bool]) -> str:
        """生成 pattern 缓存键 (含通配符信息, 避免纯字节冲突)。"""
        wc_str = ''.join('1' if w else '0' for w in wildcard)
        return f"{pattern.hex()}|{wc_str}"

    def get(self, pattern: bytes, wildcard: List[bool], data: bytes) -> Optional[List[int]]:
        """从缓存获取命中列表, 命中则移动到 LRU 末尾并返回, 否则 None。"""
        key = (self._pattern_key(pattern, wildcard), self._data_hash(data))
        if key in self._mem_cache:
            self._mem_cache.move_to_end(key)
            self._hits += 1
            return self._mem_cache[key]
        self._misses += 1
        return None

    def put(self, pattern: bytes, wildcard: List[bool], data: bytes, hits: List[int]) -> None:
        """写入缓存 (LRU 淘汰最旧条目)。"""
        key = (self._pattern_key(pattern, wildcard), self._data_hash(data))
        self._mem_cache[key] = hits
        self._mem_cache.move_to_end(key)
        if len(self._mem_cache) > self.max_entries:
            self._mem_cache.popitem(last=False)

    def get_or_scan(self, pattern: bytes, wildcard: List[bool], data: bytes,
                    scan_fn=None) -> List[int]:
        """统一入口: 缓存命中 → 返回; 未命中 → 调 scan_fn 扫描 + 写入缓存。"""
        cached = self.get(pattern, wildcard, data)
        if cached is not None:
            return cached
        if scan_fn is None:
            scan_fn = pattern_scan
        hits = scan_fn(data, pattern, wildcard)
        self.put(pattern, wildcard, data, hits)
        return hits

    def clear(self) -> None:
        """清空内存缓存。"""
        self._mem_cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def hit_rate(self) -> float:
        """缓存命中率。"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> str:
        """返回缓存统计字符串。"""
        return (f"PatternScanCache: {len(self._mem_cache)}/{self.max_entries} entries, "
                f"hits={self._hits}, misses={self._misses}, "
                f"hit_rate={self.hit_rate:.1%}")

    def save_to_disk(self) -> bool:
        """将内存缓存持久化到磁盘 (exe_sha1 缓存文件)。无 exe_sha1 时跳过。"""
        if not self.exe_sha1:
            return False
        if not self._mem_cache:
            return False
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cache_file = os.path.join(self.cache_dir, f"{self.exe_sha1}_patterns.json")
            # 转换 key tuple -> str (JSON 不支持 tuple)
            serializable = {
                f"{k[0]}|{k[1]}": v for k, v in self._mem_cache.items()
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "exe_sha1": self.exe_sha1,
                    "version": 1,
                    "entries": serializable,
                }, f, ensure_ascii=False)
            return True
        except Exception:
            return False

    def load_from_disk(self) -> bool:
        """从磁盘加载缓存 (exe_sha1 缓存文件)。无文件时静默返回 False。"""
        if not self.exe_sha1:
            return False
        cache_file = os.path.join(self.cache_dir, f"{self.exe_sha1}_patterns.json")
        if not os.path.isfile(cache_file):
            return False
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("exe_sha1") != self.exe_sha1:
                return False
            entries = data.get("entries", {})
            loaded = 0
            for k, v in entries.items():
                # 恢复 tuple key: "pattern_hex|wildcard_bits|data_hash"
                parts = k.rsplit("|", 2)
                if len(parts) != 3:
                    continue
                pat_hex, wc_bits, data_hash = parts
                pat_key = f"{pat_hex}|{wc_bits}"
                key = (pat_key, data_hash)
                self._mem_cache[key] = list(v)
                loaded += 1
            # 截断到 max_entries (按 JSON 写入顺序, 最新在末尾)
            while len(self._mem_cache) > self.max_entries:
                self._mem_cache.popitem(last=False)
            return loaded > 0
        except Exception:
            return False

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
