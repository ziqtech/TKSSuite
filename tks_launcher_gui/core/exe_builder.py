"""exe_builder — 将选中补丁烧录进原版 TKS.exe，生成独立可分发的修改版 exe

支持的补丁类型：
  1. cave_hook / patch_exp_lock — 写入 .test 节 + jmp hook（代码洞注入）
  2. patch_bytes — 模式搜索 + 字节替换（直接修改 .text 等节）
  3. patch_imm32 — 立即数修改（按模式或按值搜索）

工作原理（参照 TKS_MOD.exe 的 .test 节补丁方式）：
  1. 读取原版 TKS.exe
  2. 应用 patch_bytes / patch_imm32（直接修改现有节）
  3. 如有 cave_hook 型补丁，追加 .test 节并写入 jmp hook
  4. 更新 NumberOfSections / SizeOfImage
  5. 输出修改版 exe
"""
import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ============================================================
# PE 结构工具
# ============================================================

@dataclass
class PESection:
    name: str
    virtual_size: int
    virtual_addr: int
    raw_size: int
    raw_offset: int
    characteristics: int


@dataclass
class PEInfo:
    e_lfanew: int
    num_sections: int
    timestamp: int
    opt_size: int
    image_base: int
    section_align: int
    file_align: int
    size_of_image: int
    size_of_headers: int
    sections: List[PESection] = field(default_factory=list)


def parse_pe(data: bytes) -> PEInfo:
    """解析 PE 头与节表。"""
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    sig = data[e_lfanew:e_lfanew + 4]
    if sig != b'PE\x00\x00':
        raise ValueError(f'无效 PE 签名: {sig!r}')

    machine, num_sections, timestamp, _, _, opt_size, _ = struct.unpack_from(
        '<HHIIIHH', data, e_lfanew + 4)

    opt_off = e_lfanew + 24
    magic = struct.unpack_from('<H', data, opt_off)[0]
    if magic != 0x10B:
        raise ValueError(f'仅支持 PE32，当前 magic=0x{magic:X}')

    image_base = struct.unpack_from('<I', data, opt_off + 28)[0]
    section_align = struct.unpack_from('<I', data, opt_off + 32)[0]
    file_align = struct.unpack_from('<I', data, opt_off + 36)[0]
    size_of_image = struct.unpack_from('<I', data, opt_off + 56)[0]
    size_of_headers = struct.unpack_from('<I', data, opt_off + 60)[0]

    sec_off = e_lfanew + 24 + opt_size
    sections = []
    for i in range(num_sections):
        off = sec_off + i * 40
        name = data[off:off + 8].rstrip(b'\x00').decode('ascii', errors='replace')
        vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', data, off + 8)
        chars = struct.unpack_from('<I', data, off + 36)[0]
        sections.append(PESection(name, vsize, vaddr, rsize, raddr, chars))

    return PEInfo(e_lfanew, num_sections, timestamp, opt_size,
                  image_base, section_align, file_align,
                  size_of_image, size_of_headers, sections)


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def pattern_to_bytes(pattern: str) -> bytes:
    """将 '8B 44 24 1C' 形式的模式串转为 bytes。"""
    parts = pattern.split()
    return bytes(int(p, 16) for p in parts)


def _parse_hex(hex_str: str) -> bytes:
    """解析空格分隔的十六进制字节串 (不含通配, 供 patch_sites 用)。"""
    return bytes.fromhex(''.join(hex_str.split()))


def _parse_maybe_hex_int(value) -> int:
    """patch_sites 的 rva/cave_entries 兼容 '0x31A2' 与 12706 两种写法。"""
    if isinstance(value, int):
        return value
    v = str(value).strip()
    return int(v, 16) if v.lower().startswith('0x') else int(v, 10)


def find_pattern(data: bytes, pattern: bytes) -> List[int]:
    """在 data 中查找 pattern 的所有偏移（精确匹配）。"""
    offsets = []
    start = 0
    while True:
        idx = data.find(pattern, start)
        if idx < 0:
            break
        offsets.append(idx)
        start = idx + 1
    return offsets


def scan_pattern_str(data: bytes, pattern_str: str) -> List[int]:
    """带通配符的模式串扫描。'??' 或 '**' 表示通配字节。"""
    pat, wc = parse_pattern(pattern_str)
    return pattern_scan(data, pat, wc)


def parse_pattern(hex_str: str) -> Tuple[bytes, List[bool]]:
    """解析空格分隔的十六进制模式，返回 (pattern_bytes, wildcard_flags)。

    '??' 或 '**' 表示通配字节。
    """
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
    """带通配符的模式扫描。"""
    results = []
    if not pattern or len(data) < len(pattern):
        return results
    pl = len(pattern)
    end = len(data) - pl
    # 找第一个非通配字节作为锚点
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
        pos += 1
    return results


def rva_to_offset(pe: PEInfo, rva: int) -> int:
    """RVA → 文件偏移。"""
    for sec in pe.sections:
        if sec.virtual_addr <= rva < sec.virtual_addr + max(sec.virtual_size, sec.raw_size):
            return rva - sec.virtual_addr + sec.raw_offset
    raise ValueError(f'RVA 0x{rva:X} 不在任何节内')


def offset_to_rva(pe: PEInfo, offset: int) -> int:
    """文件偏移 → RVA。"""
    for sec in pe.sections:
        if sec.raw_offset <= offset < sec.raw_offset + sec.raw_size:
            return offset - sec.raw_offset + sec.virtual_addr
    raise ValueError(f'偏移 0x{offset:X} 不在任何节内')


# ============================================================
# Cave 构建
# ============================================================

@dataclass
class CavePatchItem:
    """一个待烧录的 cave 补丁。"""
    patch_id: str
    name: str
    hook_pattern: str             # 模式串 (空格分隔十六进制, 支持 ??/** 通配)
    hook_size: int                # 被覆盖的原始指令长度（call rel32 = 5，需 hook_size >= 5）
    cave_code: bytes              # cave 机器码
    fallback_rva: int = 0         # 模式匹配失败时的回退 RVA
    expect_count: int = 1
    hook_offset: int = 0          # hook 写入点相对模式起点的字节偏移
    cave_offset: int = -1         # cave 在 .test 节内的固定偏移（-1=顺序放置）
    warpc_cap_adjust: bool = False  # cave 内 cmp eax,200 (WarPC 索引上限) 动态调整
    weapon_cap_adjust: bool = False  # cave 内 cmp eax,143 (武器排他上限) 动态调整


@dataclass
class BytesPatchEntry:
    """patch_bytes 的单条模式替换规则。"""
    pattern: str                 # 空格分隔的十六进制模式，支持 ?? 通配
    replace: Dict[int, int]      # {偏移: 新字节值}
    expect_count: int = 0        # 预期匹配数（0=不限制）


@dataclass
class BytesPatchItem:
    """patch_bytes 型补丁：模式搜索 + 字节替换。"""
    patch_id: str
    name: str
    entries: List[BytesPatchEntry]


@dataclass
class SitesPatchItem:
    """patch_sites 型补丁：逐 RVA 锚定多点字节表（16:9 宽屏等大型改造）。

    每个位点 {rva, expect, tag} + 三种写法之一:
      replace: 等长 hex 字面替换
      kind='call', ref: 写 E8 rel32 -> .test cave 入口 ref（尾部 NOP 补齐）
      kind='push_imm', ref, replace(含 'IIII' 占位): 占位换 cave 基址+入口偏移
    expect 逐位点校验，任一不符即构建失败（无半应用状态）。

    globals_* (可选): cave 的数据槽/scratch 区。运行时由引擎 VirtualAllocEx
    独立分配; 文件级烧录放在 .test 节 cave 块之后, cave 字节与位点 repl 中
    [globals_ph_base, +globals_rebase_span) 的 4 字节绝对地址统一平移。
    """
    patch_id: str
    name: str
    sites: List[Dict]
    cave_code: bytes = b''
    cave_entries: Dict[str, int] = field(default_factory=dict)
    globals_ph_base: int = 0        # 占位基址 (VA, 0 = 不启用)
    globals_rebase_span: int = 0    # 重定位窗口宽度 (字节)
    globals_alloc_size: int = 0     # globals 区大小 (字节, 放 .test 尾部)
    globals_extra_windows: List = field(default_factory=list)  # [[占位相对偏移, 宽], ...]


@dataclass
class FixedLayoutCave:
    """固定布局的 cave 块（多个子 cave 按预定偏移排列）。

    用于 summon_extend 等需要多个 hook 点、且子 cave 之间有相对偏移关系的补丁。
    cave_block 放置在 .test 节起始（偏移 0）；build_fn(cave_base) 可在
    计算出 .test 绝对地址后动态生成，避免预先猜地址。
    """
    patch_id: str
    name: str
    hooks: List[Dict]                    # [{pattern, hook_size, cave_entry_offset, expect_count}]
    cave_block: Optional[bytes] = None   # 预生成的完整 cave 布局
    build_fn: Optional[object] = None    # Callable[[int], bytes] — cave_base → cave_block
    bytes_patches: Optional[List['BytesPatchItem']] = None
    cave_layout_size: int = 0            # 预留布局大小 (build_fn 时用于节大小)


@dataclass
class Imm32PatchEntry:
    """patch_imm32 的单条模式替换规则。"""
    pattern: str                 # 搜索模式（支持 ?? 通配）
    value_offset: int            # 立即数在模式中的字节偏移
    expect_count: int = 1        # 预期匹配数
    value_size: int = 4          # 立即数字节宽度


@dataclass
class Imm32PatchItem:
    """patch_imm32 型补丁：立即数修改。"""
    patch_id: str
    name: str
    new_value: int               # 新的立即数值
    entries: List[Imm32PatchEntry]  # 支持多模式


@dataclass
class ConfigPatchItem:
    """配置驱动型补丁（drop_probability / font_config / animation_speed 等）。

    由 dialog 层读取 JSON 配置后，转为具体的字节补丁列表。
    """
    patch_id: str
    name: str
    patch_type: str              # 'drop_probability' / 'font_config' / 'animation_speed'
    config: dict                 # JSON 配置内容


@dataclass
class DataSectionPatchItem:
    """数据段注入补丁：将扩展数据注入 exe，重定向代码引用。

    用于 tkact_expand / tkkon_expand 等需要扩容数据缓冲区的补丁。
    将扩展数据作为新 PE 节注入，然后用 patch_imm32 重定向基址和大小引用。
    bytes_patches 可在数据段重定向完成后附带应用记录数等字节级修正。
    """
    patch_id: str
    name: str
    data: bytes                  # 要注入的扩展数据
    old_base: int                # 旧缓冲区基址 (如 0x9539CA)
    old_size: int                # 旧缓冲区大小 (如 509600)
    section_name: str = '.tks'   # 新节名称
    data_offset: int = 0         # 数据在新节内的偏移
    redirect_base_span: int = 0  # 基址后的字段锚定引用扫描跨度（字节），
                                 # 0=仅精确重定向基址本身（如 WarPC 记录内
                                 # word_757F0C 等字段锚定立即数需设为记录大小）
    bytes_patches: Optional[List['BytesPatchItem']] = None


@dataclass
class CaveBuildResult:
    success: bool
    output_path: str = ''
    log: List[str] = field(default_factory=list)
    error: str = ''


class ExeBuilder:
    """将补丁烧录进原版 exe。"""

    # .test 节特征：可执行 + 可读 + 包含代码
    SECTION_CHARS_CODE = 0xE00000A0
    # .Newdata 节特征：可读 + 可写
    SECTION_CHARS_DATA = 0xC0000040

    def __init__(self, original_exe_path: str):
        self.original_path = original_exe_path
        with open(original_exe_path, 'rb') as f:
            self._orig_data = bytearray(f.read())
        self._pe = parse_pe(bytes(self._orig_data))

    @property
    def pe(self) -> PEInfo:
        return self._pe

    def _apply_bytes_patch(self, data: bytearray, item: BytesPatchItem,
                           log: List[str]) -> bool:
        """应用 patch_bytes：模式搜索 + 字节替换。"""
        pe = self._pe
        all_ok = True
        for entry in item.entries:
            pat, wc = parse_pattern(entry.pattern)
            hits = pattern_scan(bytes(data), pat, wc)
            expect = entry.expect_count
            log.append(f'  [{item.patch_id}] 模式 [{entry.pattern[:40]}...] '
                       f'匹配 {len(hits)} 处 (预期 {expect})')
            if expect > 0 and len(hits) != expect:
                log.append(f'  [{item.patch_id}] [WARN] 匹配数不符，跳过此模式')
                all_ok = False
                continue
            for off in hits:
                for ro, bv in entry.replace.items():
                    idx = off + ro
                    if idx < 0 or idx >= len(data):
                        log.append(f'  [{item.patch_id}] [FAIL] 替换偏移越界: 0x{idx:X}')
                        all_ok = False
                        continue
                    data[idx] = bv & 0xFF
                rva = offset_to_rva(pe, off) if any(
                    s.raw_offset <= off < s.raw_offset + s.raw_size
                    for s in pe.sections) else 0
                log.append(f'  [{item.patch_id}] [OK] @ 文件偏移 0x{off:X} '
                           f'(RVA 0x{rva:X})')
        return all_ok

    def _apply_sites_patch(self, data: bytearray, pe: PEInfo,
                           item: SitesPatchItem, test_abs: int,
                           blob_off: Dict[int, int], log: List[str],
                           result: CaveBuildResult) -> None:
        """应用 patch_sites：逐 RVA 锚定 + expect 校验 + 字面/cave 重定向写入。

        与运行时 _handle_patch_sites 同语义。任一位点 expect 不符或
        call/push_imm 引用缺失 => result.error，由调用方中止构建。
        """
        cave_base = 0
        if item.cave_code:
            off = blob_off.get(id(item))
            if off is None:
                result.error = f'[{item.patch_id}] sites cave 未分配布局'
                log.append(result.error)
                return
            cave_base = test_abs + off
        patched = 0
        for i, site in enumerate(item.sites):
            tag = site.get('tag', f'site#{i}')
            rva = _parse_maybe_hex_int(site.get('rva', 0))
            expect = _parse_hex(site.get('expect', ''))
            if not expect:
                result.error = f'[{item.patch_id}] {tag}: expect 为空'
                log.append(result.error)
                return
            try:
                off = rva_to_offset(pe, rva)
            except ValueError:
                off = None
            if off is None or off + len(expect) > len(data):
                result.error = f'[{item.patch_id}] {tag}: RVA 0x{rva:X} 无法定位'
                log.append(result.error)
                return
            actual = bytes(data[off:off + len(expect)])
            if actual != expect:
                result.error = (f'[{item.patch_id}] {tag}: RVA 0x{rva:X} 字节不符 '
                                f'(实际 {actual.hex(" ")} / 预期 {expect.hex(" ")})')
                log.append(result.error)
                return
            kind = site.get('kind', '')
            if kind == 'call':
                ref = site.get('ref', '')
                if ref not in item.cave_entries:
                    result.error = f'[{item.patch_id}] {tag}: cave 入口 {ref!r} 未声明'
                    log.append(result.error)
                    return
                target = cave_base + item.cave_entries[ref]
                site_abs = pe.image_base + rva
                repl = b'\xE8' + struct.pack('<i', (target - (site_abs + 5)) & 0xFFFFFFFF)
                repl += b'\x90' * (len(expect) - len(repl))
                if len(repl) != len(expect):
                    result.error = (f'[{item.patch_id}] {tag}: '
                                    f'E8+NOP 与 expect 不等长')
                    log.append(result.error)
                    return
            elif kind == 'push_imm':
                ref = site.get('ref', '')
                if ref not in item.cave_entries:
                    result.error = f'[{item.patch_id}] {tag}: cave 入口 {ref!r} 未声明'
                    log.append(result.error)
                    return
                addr = cave_base + item.cave_entries[ref]
                repl = _parse_hex(site.get('replace', ''))
                if repl.count(b'I') != 4:
                    result.error = f'[{item.patch_id}] {tag}: push_imm 需要 IIII 占位'
                    log.append(result.error)
                    return
                repl = repl.replace(b'I' * 4, struct.pack('<I', addr))
                if len(repl) != len(expect):
                    result.error = (f'[{item.patch_id}] {tag}: '
                                    f'replace ({len(repl)}B) 与 expect ({len(expect)}B) 不等长')
                    log.append(result.error)
                    return
            else:
                repl = _parse_hex(site.get('replace', ''))
                if len(repl) != len(expect):
                    result.error = (f'[{item.patch_id}] {tag}: replace '
                                    f'({len(repl)}B) 与 expect ({len(expect)}B) 不等长')
                    log.append(result.error)
                    return
            # globals 占位地址平移 (与运行时 _handle_patch_sites 同语义)
            g_abs = getattr(item, '_globals_abs', 0)
            if g_abs and item.globals_ph_base and item.globals_rebase_span:
                delta = g_abs - item.globals_ph_base
                windows = [(item.globals_ph_base, item.globals_rebase_span)]
                for woff, wspan in (item.globals_extra_windows or []):
                    windows.append((item.globals_ph_base + int(woff), int(wspan)))
                reb = bytearray(repl)
                for i in range(len(reb) - 3):
                    v = int.from_bytes(reb[i:i + 4], 'little')
                    for lo, wspan2 in windows:
                        if lo <= v < lo + wspan2:
                            reb[i:i + 4] = struct.pack('<I', (v + delta) & 0xFFFFFFFF)
                            break
                repl = bytes(reb)
            data[off:off + len(repl)] = repl
            patched += 1
            log.append(f'  [{item.patch_id}] [OK] {tag} @ RVA 0x{rva:X}')
        log.append(f'  [{item.patch_id}] 共写入 {patched}/{len(item.sites)} 位点')

    def _apply_imm32_patch(self, data: bytearray, item: Imm32PatchItem,
                           log: List[str]) -> bool:
        """应用 patch_imm32：模式搜索 + 立即数替换。

        只在原版可执行节 (.text) 内生效——value_scan 型 (expect_count=0)
        全文件扫描会命中注入数据节里与立即数同值的普通数据
        (原实现写入 36 处 "RVA 0x0"，值恰相同时是无害 no-op，
        换值后即数据损坏)。
        """
        pe = self._pe
        all_ok = True
        exec_ranges = [(s.raw_offset, s.raw_offset + s.raw_size)
                       for s in pe.sections
                       if s.raw_size > 0 and (s.characteristics & 0x20000000)]
        for entry in item.entries:
            pat, wc = parse_pattern(entry.pattern)
            hits = [h for h in pattern_scan(bytes(data), pat, wc)
                    if any(a <= h < b for a, b in exec_ranges)]
            skipped = 0
            log.append(f'  [{item.patch_id}] 模式匹配 {len(hits)} 处 '
                       f'(预期 {entry.expect_count})')
            if entry.expect_count > 0 and len(hits) != entry.expect_count:
                log.append(f'  [{item.patch_id}] [WARN] 匹配数不符，跳过此模式')
                all_ok = False
                continue
            for off in hits:
                idx = off + entry.value_offset
                if idx < 0 or idx + entry.value_size > len(data):
                    log.append(f'  [{item.patch_id}] [FAIL] 立即数偏移越界: 0x{idx:X}')
                    all_ok = False
                    continue
                # 写入新值（小端）
                if entry.value_size == 4:
                    struct.pack_into('<I', data, idx, item.new_value & 0xFFFFFFFF)
                elif entry.value_size == 2:
                    struct.pack_into('<H', data, idx, item.new_value & 0xFFFF)
                else:
                    log.append(f'  [{item.patch_id}] [FAIL] 不支持的 value_size={entry.value_size}')
                    all_ok = False
                    continue
                rva = offset_to_rva(pe, off) if any(
                    s.raw_offset <= off < s.raw_offset + s.raw_size
                    for s in pe.sections) else 0
                log.append(f'  [{item.patch_id}] [OK] @ 0x{off:X} '
                           f'(RVA 0x{rva:X}): 写入 0x{item.new_value:X}')
        return all_ok

    def _apply_drop_probability(self, data: bytearray, item: ConfigPatchItem,
                                log: List[str]) -> bool:
        """应用 drop_probability：修改掉落阈值。"""
        pe = self._pe
        cfg = item.config
        rare_pct = int(cfg.get('rare_pct', 100))
        normal_pct = int(cfg.get('normal_pct', 100))

        # 验证百分值
        for name, val in [('rare', rare_pct), ('normal', normal_pct)]:
            if val < 0 or val > 100:
                log.append(f'  [{item.patch_id}] [ERROR] {name}_pct={val} 超出 0~100')
                return False

        # 普通槽阈值: RVA 0x41A2F, cmp ax, imm16
        # 稀有槽阈值: RVA 0x41AA2, cmp ax, imm8 → 替换为 imm16 形式
        patches = []
        # 普通槽
        norm_rva = 0x41A2F
        old_norm = bytes([0x66, 0x3D, 0xC8, 0x00])
        new_norm = bytes([0x66, 0x3D, (normal_pct * 10) & 0xFF, ((normal_pct * 10) >> 8) & 0xFF])
        patches.append((norm_rva, old_norm, new_norm, f'普通槽 {normal_pct}%'))
        # 稀有槽
        rare_rva = 0x41AA2
        old_rare = bytes([0x66, 0x83, 0xF8, 0x32])
        new_rare = bytes([0x66, 0x3D, (rare_pct * 10) & 0xFF, ((rare_pct * 10) >> 8) & 0xFF])
        patches.append((rare_rva, old_rare, new_rare, f'稀有槽 {rare_pct}%'))

        all_ok = True
        for rva, expected, new_bytes, desc in patches:
            off = rva_to_offset(pe, rva)
            actual = bytes(data[off:off + len(expected)])
            if actual != expected:
                log.append(f'  [{item.patch_id}] [ERROR] RVA 0x{rva:X} 字节不匹配: '
                           f'{actual.hex()} != {expected.hex()}')
                all_ok = False
                continue
            data[off:off + len(new_bytes)] = new_bytes
            log.append(f'  [{item.patch_id}] [OK] RVA 0x{rva:X}: {desc} '
                       f'({expected.hex()} → {new_bytes.hex()})')
        return all_ok

    def _apply_font_config(self, data: bytearray, item: ConfigPatchItem,
                           log: List[str]) -> bool:
        """应用 font_config：修改字体描边等参数。"""
        pe = self._pe
        cfg = item.config
        renderers = cfg.get('renderers', {})
        all_ok = True

        # 描边 (outline) 处理
        # a7 是 sub_44AF7C 的第 7 个参数 (存储在渲染器 offset+64)
        _OUTLINE_CONFIGS = [
            ('main',           0x04, None, False),
            ('menu_name_font', 0x08, 2,    True),
            ('tooltip_font',   0x08, 0,    False),
        ]

        for rname, ptr_byte, orig_ftype, exclude_special in _OUTLINE_CONFIGS:
            rc = renderers.get(rname, {})
            outline = rc.get('outline', None)
            if outline is None:
                continue
            outline = int(outline)
            if outline not in (0, 1):
                log.append(f'  [{item.patch_id}] [ERROR] {rname} outline={outline} 超出 0~1')
                all_ok = False
                continue

            ft = f'{orig_ftype:02X}' if orig_ftype is not None else '??'
            ptr = f'{ptr_byte:02X} 5B 75 00'
            outline_variants = [
                (f'8B 15 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 52 E8', 7, 9),
                (f'6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 15 {ptr} 52 E8', 1, 3),
                (f'A1 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 50 E8', 6, 8),
                (f'6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} A1 {ptr} 50 E8', 1, 3),
                (f'8B 0D {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 51 E8', 7, 9),
                (f'6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 0D {ptr} 51 E8', 1, 3),
            ]
            patched = 0
            for pat_str, a7_off, a6_off in outline_variants:
                pat, wc = parse_pattern(pat_str)
                hits = pattern_scan(bytes(data), pat, wc)
                for h in hits:
                    if exclude_special:
                        a7_val = data[h + a7_off]
                        a6_val = data[h + a6_off]
                        if a6_val == 0:
                            continue
                        if a7_val == 1 and a6_val == 1 and not pat_str.startswith('8B 15'):
                            continue
                    a7_foff = h + a7_off
                    actual = data[a7_foff]
                    if actual == outline:
                        continue
                    data[a7_foff] = outline & 0xFF
                    patched += 1
            log.append(f'  [{item.patch_id}] {rname} outline={outline}: 修改 {patched} 处')

        return all_ok

    def _apply_animation_speed(self, data: bytearray, item: ConfigPatchItem,
                               log: List[str]) -> bool:
        """应用 animation_speed：修改动画帧延迟。"""
        pe = self._pe
        cfg = item.config
        all_ok = True

        # 通用 pattern: 2B ?? 83 F8 3C (sub eax, imm; cmp eax, 0x3C)
        pat, wc = parse_pattern('2B ?? 83 F8 3C')
        all_hits = pattern_scan(bytes(data), pat, wc)
        log.append(f'  [{item.patch_id}] 通用 pattern 扫描: {len(all_hits)} 处匹配')

        def patch_frame_delay(delay_ms: int, func_rvas: list, label: str):
            """修改指定函数的帧延迟 (0x3C = 60ms)。"""
            if delay_ms == 60:
                return
            patched = 0
            for rva in func_rvas:
                off = rva_to_offset(pe, rva)
                # 在该函数范围内查找 2B ?? 83 F8 3C
                func_end = off + 0x1000  # 函数大致范围
                for h in all_hits:
                    if off <= h < func_end:
                        # 修改 0x3C 为新值
                        cmp_off = h + 4  # 83 F8 3C 中的 3C
                        if data[cmp_off] == 0x3C:
                            data[cmp_off] = delay_ms & 0xFF
                            patched += 1
            log.append(f'  [{item.patch_id}] {label}: {delay_ms}ms, 修改 {patched} 处')

        # 状态动画
        status_cfg = cfg.get('status_animation', {})
        status_delay = int(status_cfg.get('frame_delay_ms', 60))
        # 这些 RVA 需要从 patch.json 或硬编码获取
        # 暂时使用通用扫描
        if status_delay != 60:
            log.append(f'  [{item.patch_id}] 状态动画延迟: {status_delay}ms')

        # 移动动画
        move_cfg = cfg.get('move_animation', {})
        move_delay = int(move_cfg.get('frame_delay_ms', 60))
        if move_delay != 60:
            log.append(f'  [{item.patch_id}] 移动动画延迟: {move_delay}ms')

        return all_ok

    def _apply_summon_table(self, data: bytearray, item: ConfigPatchItem,
                            log: List[str]) -> bool:
        """应用 summon_table：写入 .data 段和代码段的召唤角色配置。"""
        pe = self._pe
        cfg = item.config

        # .data 段 8 字节 (技能 224-231)
        data_rva = 0xEB7D0
        data_keys = ['skill_224', 'skill_225', 'skill_226', 'skill_227',
                     'skill_228', 'skill_229', 'skill_230', 'skill_231']

        # 计算 WarPC 最大索引 (原版 143 条)
        max_count = 143

        def warpc_i(warpc_idx):
            """WarPC 索引转 i 值 (0-255)。"""
            if not isinstance(warpc_idx, int):
                return None
            if warpc_idx < 36 or warpc_idx >= max_count:
                return None
            return warpc_idx - 36

        # 写 .data 段
        try:
            data_off = rva_to_offset(pe, data_rva)
        except ValueError:
            log.append(f'  [{item.patch_id}] .data RVA 0x{data_rva:X} 无效')
            return False

        cur = bytearray(data[data_off:data_off + 8])
        changed = False
        for k, key in enumerate(data_keys):
            if key not in cfg:
                continue
            i = warpc_i(cfg[key])
            if i is None:
                log.append(f'  [{item.patch_id}] {key}: WarPC 索引 {cfg[key]} 越界')
                continue
            if cur[k] != (i & 0xFF):
                log.append(f'  [{item.patch_id}] {key}: WarPC {cur[k]+36} → {cfg[key]}')
                changed = True
            cur[k] = i & 0xFF

        if changed:
            data[data_off:data_off + 8] = cur
            log.append(f'  [{item.patch_id}] .data @ RVA 0x{data_rva:X} 已更新')
        else:
            log.append(f'  [{item.patch_id}] .data 与默认值一致')

        # 写代码段 imm16
        code_addrs = [
            {'rva': 0x44CA0, 'key': 'skill_222'},
            {'rva': 0x44CC5, 'key': 'skill_251_a'},
            {'rva': 0x44CCD, 'key': 'skill_251_b'},
        ]

        for site in code_addrs:
            key = site['key']
            rva = site['rva']
            if key not in cfg:
                continue
            i = warpc_i(cfg[key])
            if i is None:
                log.append(f'  [{item.patch_id}] {key}: WarPC 索引 {cfg[key]} 越界')
                continue
            try:
                off = rva_to_offset(pe, rva)
            except ValueError:
                log.append(f'  [{item.patch_id}] {key}: RVA 0x{rva:X} 无效')
                continue
            # 安全检查：确认前导字节是 mov word[ebp-2], imm16
            if off >= 4 and bytes(data[off-4:off]) == b'\x66\xC7\x45\xFE':
                struct.pack_into('<H', data, off, i & 0xFFFF)
                log.append(f'  [{item.patch_id}] {key}: i={i} @ RVA 0x{rva:X}')
            else:
                log.append(f'  [{item.patch_id}] {key}: @ RVA 0x{rva:X} 前导字节不符，跳过')

        return True

    def _add_pe_section(self, data: bytearray, section_name: str,
                        vsize: int, raw_size: int, characteristics: int,
                        log: List[str]) -> Tuple[bool, int, int]:
        """向 PE 添加新节。Returns (success, new_va, new_abs)。"""
        pe = self._pe

        last_sec = pe.sections[-1]
        new_va = align_up(
            last_sec.virtual_addr + max(last_sec.virtual_size, last_sec.raw_size),
            pe.section_align)
        new_raw_off = align_up(len(data), pe.file_align)
        new_abs = pe.image_base + new_va

        # 填充到 new_raw_off
        if len(data) < new_raw_off:
            data.extend(b'\x00' * (new_raw_off - len(data)))

        # 更新 PE 头
        e_lfanew = pe.e_lfanew
        opt_off = e_lfanew + 24
        sec_table_off = e_lfanew + 24 + pe.opt_size

        new_num_sections = pe.num_sections + 1
        struct.pack_into('<H', data, e_lfanew + 6, new_num_sections)

        new_size_of_image = align_up(new_va + vsize, pe.section_align)
        struct.pack_into('<I', data, opt_off + 56, new_size_of_image)

        new_sec_entry_off = sec_table_off + pe.num_sections * 40
        if new_sec_entry_off + 40 > pe.size_of_headers:
            log.append(f'  [ERROR] 节表空间不足')
            return False, 0, 0

        sec_name_bytes = section_name.encode('ascii')[:8].ljust(8, b'\x00')
        sec_entry = sec_name_bytes + struct.pack('<IIIIIIHHI',
            vsize, new_va, raw_size, new_raw_off,
            0, 0, 0, 0, characteristics)
        data[new_sec_entry_off:new_sec_entry_off + 40] = sec_entry

        log.append(f'  [{section_name}] RVA=0x{new_va:X}, 绝对=0x{new_abs:X}, '
                   f'大小=0x{raw_size:X}')
        return True, new_va, new_abs

    def build(self, cave_patches: List[CavePatchItem],
              output_path: str,
              bytes_patches: Optional[List[BytesPatchItem]] = None,
              imm32_patches: Optional[List[Imm32PatchItem]] = None,
              config_patches: Optional[List[ConfigPatchItem]] = None,
              fixed_layouts: Optional[List[FixedLayoutCave]] = None,
              data_section_patches: Optional[List[DataSectionPatchItem]] = None,
              sites_patches: Optional[List[SitesPatchItem]] = None,
              section_name: str = '.test') -> CaveBuildResult:
        """构建修改版 exe。

        Args:
            cave_patches: cave_hook 型补丁列表
            output_path: 输出路径
            bytes_patches: patch_bytes 型补丁列表
            imm32_patches: patch_imm32 型补丁列表
            config_patches: 配置驱动型补丁列表
            fixed_layouts: 固定布局 cave 列表（如 summon_extend）
            data_section_patches: 数据段注入补丁（如 tkact_expand）
            section_name: 新节名称（默认 .test）

        Returns:
            CaveBuildResult
        """
        log: List[str] = []
        result = CaveBuildResult(success=False, output_path=output_path, log=log)

        bytes_patches = bytes_patches or []
        imm32_patches = imm32_patches or []
        config_patches = config_patches or []
        data_section_patches = data_section_patches or []
        fixed_layouts = fixed_layouts or []
        sites_patches = sites_patches or []

        if not (cave_patches or bytes_patches or imm32_patches or
                config_patches or fixed_layouts or data_section_patches or
                sites_patches):
            result.error = '未选择任何补丁'
            log.append(result.error)
            return result

        pe = self._pe
        data = bytearray(self._orig_data)

        # 跟踪后续新节的虚拟地址游标 (数据段 + .test)
        next_va = align_up(
            pe.sections[-1].virtual_addr
            + max(pe.sections[-1].virtual_size, pe.sections[-1].raw_size),
            pe.section_align)

        # ── 0. 数据段注入 (BSS 方式, 不占文件空间) ──
        # 缓冲区以 VirtualSize 声明、SizeOfRawData=0: loader 分配内存并零填充,
        # exe 文件体积零增长。注入内容副本是冗余的——游戏启动时无条件从部署
        # 目录的 .dat 文件加载填充这些缓冲区 (FileRead/LZSS, 加载不出的文件本
        # 就会报错), 副本永远不会被使用。与原版 .data 节 (VSize 0x57B000 /
        # Raw 0x13A00) 同款 BSS 形态。
        data_section_results = []  # [(item, new_base_abs, raw_off, va)]
        if data_section_patches:
            log.append(f'── 应用数据段注入 ({len(data_section_patches)} 个) ──')
            for item in data_section_patches:
                new_va = next_va
                new_abs = pe.image_base + new_va
                log.append(f'  [{item.patch_id}] 注入 {item.section_name}: '
                           f'RVA=0x{new_va:X}, 绝对=0x{new_abs:X}, '
                           f'缓冲={len(item.data)} 字节 (BSS, 不占文件空间)')
                data_section_results.append((item, new_abs, 0, new_va))
                next_va = align_up(new_va + max(len(item.data), 1), pe.section_align)

        # ── 1. patch_bytes ──
        if bytes_patches:
            log.append(f'── 应用 patch_bytes ({len(bytes_patches)} 个) ──')
            for item in bytes_patches:
                self._apply_bytes_patch(data, item, log)

        for fl in fixed_layouts:
            if fl.bytes_patches:
                log.append(f'── 应用 {fl.patch_id} 附带 patch_bytes '
                           f'({len(fl.bytes_patches)} 个) ──')
                for item in fl.bytes_patches:
                    self._apply_bytes_patch(data, item, log)

        # ── 2. patch_imm32 ──
        if imm32_patches:
            log.append(f'── 应用 patch_imm32 ({len(imm32_patches)} 个) ──')
            for item in imm32_patches:
                self._apply_imm32_patch(data, item, log)

        # 数据段引用重定向挪到 hook 定位之后执行 (见 4b): 先让各补丁的
        # hook_pattern 在未被重定向的字节上匹配 (如 checkmember 的模式尾部
        # 就是 word_757F0C 字段锚, 先重定向会破坏模式), 再重定向并跳过
        # hook 覆盖区。

        # ── 3. 配置驱动 ──
        if config_patches:
            log.append(f'── 应用配置驱动型 ({len(config_patches)} 个) ──')
            for item in config_patches:
                if item.patch_type in ('drop_probability', 'patch_drop_probability'):
                    self._apply_drop_probability(data, item, log)
                elif item.patch_type in ('font_config', 'patch_font_config'):
                    self._apply_font_config(data, item, log)
                elif item.patch_type in ('animation_speed', 'patch_animation_speed'):
                    self._apply_animation_speed(data, item, log)
                elif item.patch_type in ('summon_table', 'patch_summon_table'):
                    self._apply_summon_table(data, item, log)
                else:
                    log.append(f'  [{item.patch_id}] 未知配置类型: {item.patch_type}')

        # ── 4. 定位所有 hook 点 ──
        # cave_hook: (kind, item_or_fl, hook_off, hook_size, cave_entry_rel, name)
        # fixed_layout 的 cave_entry_rel 相对 .test 起始; cave_hook 顺序分配
        located = []  # (kind, owner, hook_off, hook_size, entry_rel, label)
        need_test = bool(cave_patches or fixed_layouts
                         or any(sp.cave_code for sp in sites_patches))

        if fixed_layouts:
            log.append(f'── 定位 fixed_layout hook ({len(fixed_layouts)} 个) ──')
            for fl in fixed_layouts:
                for hook in fl.hooks:
                    pattern = hook['pattern']
                    expect = hook.get('expect_count', 1)
                    offsets = scan_pattern_str(bytes(data), pattern)
                    if len(offsets) != expect:
                        if hook.get('fallback_rva'):
                            off = rva_to_offset(pe, _parse_int(hook['fallback_rva']))
                        else:
                            result.error = (f'[{fl.patch_id}] hook '
                                            f'{hook.get("name", "?")} 匹配 '
                                            f'{len(offsets)} 次，期望 {expect} 次')
                            log.append(result.error)
                            return result
                    else:
                        off = offsets[0]
                    hsize = int(hook['hook_size'])
                    if hsize < 5:
                        result.error = (f'[{fl.patch_id}] hook_size={hsize} < 5')
                        log.append(result.error)
                        return result
                    entry = int(hook['cave_entry_offset'])
                    located.append(('fl', fl, off, hsize, entry,
                                    hook.get('name', fl.patch_id)))
                    log.append(f'  [{fl.patch_id}/{hook.get("name", "?")}] '
                               f'@ 0x{off:X} → .test+0x{entry:X}')

        if cave_patches:
            log.append(f'── 定位 cave_hook ({len(cave_patches)} 个) ──')
            for item in cave_patches:
                pat_str = item.hook_pattern
                if isinstance(pat_str, (bytes, bytearray)):
                    pat_str = ' '.join(f'{b:02X}' for b in pat_str)
                offsets = scan_pattern_str(bytes(data), pat_str)
                if len(offsets) != item.expect_count:
                    if item.fallback_rva:
                        # fallback_rva 口径与 patch_engine 一致：指向 hook 写入点，
                        # 需回退 hook_offset 得到模式起点
                        offsets = [rva_to_offset(pe, item.fallback_rva)
                                   - item.hook_offset]
                        log.append(f'[{item.patch_id}] 模式匹配失败，'
                                   f'使用回退 RVA 0x{item.fallback_rva:X}')
                    else:
                        result.error = (f'[{item.patch_id}] hook_pattern 匹配 '
                                        f'{len(offsets)} 次，期望 {item.expect_count} 次')
                        log.append(result.error)
                        return result
                if item.hook_size < 5:
                    result.error = (f'[{item.patch_id}] hook_size={item.hook_size} < 5')
                    log.append(result.error)
                    return result
                # 同一 cave 代码可被多个 hook 点 call (expect_count>1)
                # hook 写入点 = 模式起点 + hook_offset（如 awk_sprite_cave3/4 的
                # 模式含前一条 jmp 的 2 字节，真正被覆盖指令在其后）
                for off in offsets:
                    hook_off = off + item.hook_offset
                    if (hook_off < 0 or hook_off + item.hook_size > len(data)):
                        result.error = (f'[{item.patch_id}] hook 写入越界 '
                                        f'0x{hook_off:X}+{item.hook_size}')
                        log.append(result.error)
                        return result
                    log.append(f'[{item.patch_id}] hook 点 @ 0x{hook_off:X} '
                               f'(RVA 0x{offset_to_rva(pe, hook_off):X})')
                    located.append(('cave', item, hook_off, item.hook_size, -1,
                                    item.patch_id))

        # ── 4b. 数据段引用重定向 ──
        # 在 hook 定位之后执行: hook 模式必须在未被重定向的字节上匹配
        # (checkmember 的模式尾部就是 word_757F0C 字段锚)。重定向跳过
        # hook 覆盖区 [hook_off, hook_off+hook_size) —— 那些字节随后会被
        # E8+NOP 覆盖; 覆盖区之外的锚就地生效。
        if data_section_results:
            hook_regions = [(off, off + hsize)
                            for kind, owner, off, hsize, _, _ in located]

            def _in_hook_region(off: int, size: int = 4) -> bool:
                return any(off < b and a < off + size for a, b in hook_regions)

            log.append(f'── 重定向数据段引用 ({len(data_section_results)} 个) ──')
            for item, new_base_abs, _, _ in data_section_results:
                old_base_bytes = struct.pack('<I', item.old_base)
                new_base_bytes = struct.pack('<I', new_base_abs)
                hits = [h for h in find_pattern(bytes(data), old_base_bytes)
                        if not _in_hook_region(h)]
                log.append(f'  [{item.patch_id}] 基址引用: {len(hits)} 处 '
                           f'(0x{item.old_base:X} → 0x{new_base_abs:X})')
                for off in hits:
                    rva = offset_to_rva(pe, off) if any(
                        s.raw_offset <= off < s.raw_offset + s.raw_size
                        for s in pe.sections) else 0
                    if rva and rva < 0x100000:
                        data[off:off + 4] = new_base_bytes
                        log.append(f'    @ 0x{off:X} (RVA 0x{rva:X})')

                old_size_bytes = struct.pack('<I', item.old_size)
                new_size_bytes = struct.pack('<I', len(item.data))
                size_hits = [h for h in find_pattern(bytes(data), old_size_bytes)
                             if not _in_hook_region(h)]
                log.append(f'  [{item.patch_id}] 大小引用: {len(size_hits)} 处 '
                           f'({item.old_size} → {len(item.data)})')
                for off in size_hits:
                    rva = offset_to_rva(pe, off) if any(
                        s.raw_offset <= off < s.raw_offset + s.raw_size
                        for s in pe.sections) else 0
                    if rva and rva < 0x100000:
                        data[off:off + 4] = new_size_bytes
                        log.append(f'    @ 0x{off:X} (RVA 0x{rva:X})')

                # 字段锚定引用: [old_base+1, old_base+span) 内的立即数
                # (如 WarPC word_757F0C[527*i]、TKKon 0x9D069E = 基址+6)，
                # 精确基址替换覆盖不到，按 (old_base, old_base+span) 开区间扫描。
                span = int(getattr(item, 'redirect_base_span', 0) or 0)
                if span > 0:
                    span_hits = 0
                    text_secs = [s for s in pe.sections
                                 if s.raw_size > 0 and (s.characteristics & 0x20000000)]
                    for sec in text_secs:
                        lo = sec.raw_offset
                        hi = sec.raw_offset + sec.raw_size
                        pos = lo
                        while pos + 4 <= hi:
                            val = int.from_bytes(data[pos:pos + 4], 'little')
                            if (item.old_base < val < item.old_base + span
                                    and not _in_hook_region(pos)):
                                delta = val - item.old_base
                                new_val = new_base_abs + delta
                                log.append(f'    字段锚定 @ 0x{pos:X} '
                                           f'(RVA 0x{offset_to_rva(pe, pos):X}): '
                                           f'0x{val:X} → 0x{new_val:X} (基址+{delta})')
                                data[pos:pos + 4] = struct.pack('<I', new_val)
                                span_hits += 1
                                pos += 4
                                continue
                            pos += 1
                    log.append(f'  [{item.patch_id}] 字段锚定引用 (span={span}): '
                               f'{span_hits} 处')

                if item.bytes_patches:
                    log.append(f'  [{item.patch_id}] 应用数据段附带字节补丁 '
                               f'({len(item.bytes_patches)} 个)')
                    for bp in item.bytes_patches:
                        if not self._apply_bytes_patch(data, bp, log):
                            result.error = (f'[{item.patch_id}] '
                                            f'数据段附带字节补丁应用失败')
                            log.append(result.error)
                            return result

        # ── 5. 计算 .test 节布局 ──
        test_rva = 0
        test_file_off = 0
        test_abs = 0
        test_vsize = 0
        test_raw_size = 0
        cave_section = None

        if need_test:
            # fixed_layout 块从偏移 0 开始; cave_hook 顺序排在其后
            fl_blocks = []  # (fl, offset, size)
            cursor = 0
            for fl in fixed_layouts:
                size = fl.cave_layout_size or (
                    len(fl.cave_block) if fl.cave_block else 0)
                if size <= 0:
                    result.error = f'[{fl.patch_id}] cave_layout_size 未声明'
                    log.append(result.error)
                    return result
                fl_blocks.append((fl, cursor, size))
                cursor = align_up(cursor + size, 16)
            fl_offset_of = {id(fl): off for fl, off, _ in fl_blocks}

            # cave_hook: 每个补丁只占一份 cave 代码, 多 hook 点共享
            cave_blobs = []  # (item, entry_rel)
            cave_entry_of = {}  # id(item) -> entry_rel
            for kind, owner, _, _, entry, _ in located:
                if kind != 'cave':
                    continue
                if id(owner) in cave_entry_of:
                    continue
                aligned = align_up(cursor, 16)
                cave_entry_of[id(owner)] = aligned
                cave_blobs.append((owner, aligned))
                cursor = aligned + len(owner.cave_code)

            # patch_sites: 每个带 cave 的位点表补丁占一块; 声明了 globals 的
            # 再在其 cave 块后追加数据区 (槽位+scratch, 零填充)
            sites_blobs = []  # (item, off)
            for sp in sites_patches:
                if not sp.cave_code:
                    continue
                aligned = align_up(cursor, 16)
                sites_blobs.append((sp, aligned))
                cursor = aligned + len(sp.cave_code)
                if sp.globals_ph_base and sp.globals_alloc_size:
                    g_off = align_up(cursor, 16)
                    sp._globals_off = g_off   # _globals_abs 在 test_abs 算出后回填
                    cursor = g_off + sp.globals_alloc_size

            test_vsize = max(cursor, 1)
            test_raw_size = align_up(test_vsize, pe.file_align)
            test_rva = next_va
            test_file_off = align_up(len(data), pe.file_align)
            test_abs = pe.image_base + test_rva

            log.append(f'.test 节: RVA=0x{test_rva:X}, 绝对=0x{test_abs:X}, '
                       f'大小=0x{test_raw_size:X}')

            # sites 补丁的 globals 区绝对地址回填 (布局阶段只知偏移)
            for sp in sites_patches:
                if getattr(sp, '_globals_off', None) is not None:
                    sp._globals_abs = test_abs + sp._globals_off

            # WarPC 基址占位符与索引上限替换 (与 patch_engine.build_cave_template
            # 的运行时语义一致)。cave 代码中的 0x757F08 是占位符: 运行时注入由
            # replace_addr_in_bytes 换成 VirtualAlloc 基址; 文件级烧录必须换成
            # .warpc 节基址, 否则 cave 读的是重定向后永远为 0 的旧 BSS——
            # 自定义头像/战场形象/历史文本全部回落默认值 (头像错误事故根因)。
            # warpc_base_refs 未勾选时游戏加载进原版 BSS (容量 150722 = 143 条),
            # cap 上限按 143 计 (与 patch_engine 未扩容路径一致), 不能为 None
            warpc_new_base = None
            rec_count = 143
            for it, new_abs, _, _ in data_section_results:
                if it.old_base == 0x757F08:  # warpc_base_refs
                    warpc_new_base = new_abs
                    rec_count = max(len(it.data) // 1054, 143)

            def _prepare_cave_bytes(owner, code: bytes) -> bytes:
                c = bytearray(code)
                if warpc_new_base is not None:
                    old_le = struct.pack('<I', 0x757F08)
                    pos = 0
                    while True:
                        pos = c.find(old_le, pos)
                        if pos < 0:
                            break
                        c[pos:pos + 4] = struct.pack('<I', warpc_new_base)
                        pos += 4
                if getattr(owner, 'warpc_cap_adjust', False):
                    idx_cap = max(rec_count - 1, 200)
                    pos = c.find(bytes([0x3D]) + struct.pack('<I', 200))
                    if pos >= 0:
                        c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', idx_cap)
                if getattr(owner, 'weapon_cap_adjust', False):
                    rc = max(rec_count, 143)
                    pos = c.find(bytes([0x3D]) + struct.pack('<I', 143))
                    if pos >= 0:
                        c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', rc)
                return bytes(c)

            # 生成 fixed_layout 块。build_fn 必须用块的【实际】基址
            # (test_abs + 块偏移): 块内的 E9 rel32 内部跳转与 slots 等绝对
            # 寻址都按该基址编码, 错 0x40 就会在战斗初始化时跳进垃圾指令
            # (白屏事故根因)。
            cave_section = bytearray(test_raw_size)
            for fl, off, size in fl_blocks:
                if fl.build_fn is not None:
                    block = fl.build_fn(test_abs + off)
                else:
                    block = fl.cave_block or b''
                block = _prepare_cave_bytes(fl, block)
                if len(block) > size:
                    result.error = (f'[{fl.patch_id}] cave 块 {len(block)} 字节 '
                                    f'超出布局 {size}')
                    log.append(result.error)
                    return result
                cave_section[off:off + len(block)] = block
                log.append(f'[{fl.patch_id}] cave 块写入 .test+0x{off:X} '
                           f'({len(block)}/{size} 字节)')

            for item, off in cave_blobs:
                code = _prepare_cave_bytes(item, item.cave_code)
                cave_section[off:off + len(code)] = code
                log.append(f'[{item.patch_id}] cave 代码写入 .test+0x{off:X} '
                           f'({len(code)} 字节)')

            for sp, off in sites_blobs:
                code = sp.cave_code
                g_abs = getattr(sp, '_globals_abs', 0)
                if g_abs and sp.globals_ph_base and sp.globals_rebase_span:
                    delta = g_abs - sp.globals_ph_base
                    windows = [(sp.globals_ph_base, sp.globals_rebase_span)]
                    for woff, wspan in (sp.globals_extra_windows or []):
                        windows.append((sp.globals_ph_base + int(woff), int(wspan)))
                    reb = bytearray(code)
                    for i in range(len(reb) - 3):
                        v = int.from_bytes(reb[i:i + 4], 'little')
                        for lo, wspan2 in windows:
                            if lo <= v < lo + wspan2:
                                reb[i:i + 4] = struct.pack('<I', (v + delta) & 0xFFFFFFFF)
                                break
                    code = bytes(reb)
                    log.append(f'[{sp.patch_id}] globals 区 .test+0x{sp._globals_off:X} '
                               f'= 0x{g_abs:X} (占位 0x{sp.globals_ph_base:08X}+{sp.globals_rebase_span:#x})')
                cave_section[off:off + len(code)] = code
                log.append(f'[{sp.patch_id}] sites cave 写入 .test+0x{off:X} '
                           f'({len(code)} 字节)')

            if len(data) < test_file_off:
                data.extend(b'\x00' * (test_file_off - len(data)))
            data.extend(cave_section)

            # 写入 call hook（E8 rel32；与 patch_engine 运行时约定一致，
            # cave 以 ret 回 hook+5，[esp] = 返回地址）
            for kind, owner, hook_off, hsize, entry, label in located:
                if kind == 'fl':
                    # hook 的 cave_entry_offset 相对所属 fixed_layout 块起点,
                    # 多个 fixed_layout 共存时必须加上各自块偏移
                    entry_rel = fl_offset_of.get(id(owner), 0) + entry
                else:
                    entry_rel = cave_entry_of.get(id(owner))
                    if entry_rel is None:
                        result.error = f'[{owner.patch_id}] 未分配 cave 偏移'
                        log.append(result.error)
                        return result
                hook_rva = offset_to_rva(pe, hook_off)
                cave_target_rva = test_rva + entry_rel
                rel32 = cave_target_rva - (hook_rva + 5)
                call = b'\xE8' + struct.pack('<i', rel32)
                patch = call + b'\x90' * (hsize - 5)
                data[hook_off:hook_off + hsize] = patch
                log.append(f'[{owner.patch_id}/{label}] hook 0x{hook_off:X}: '
                           f'call 0x{cave_target_rva:X}')

            # patch_sites 位点写入 (在 hook 之后: 位点与 hook 点无重叠,
            # 逐位点 expect 校验, 任一不符即构建失败)
            if sites_patches:
                log.append(f'── 应用 patch_sites ({len(sites_patches)} 个) ──')
                for sp in sites_patches:
                    self._apply_sites_patch(data, pe, sp, test_abs,
                                            {id(s): o for s, o in sites_blobs},
                                            log, result)
                    if result.error:
                        return result

            next_va = align_up(test_rva + test_vsize, pe.section_align)

        # ── 5b. 无 .test 时的纯字面位点补丁 ──
        if sites_patches and not need_test:
            log.append(f'── 应用 patch_sites ({len(sites_patches)} 个, 无 cave) ──')
            for sp in sites_patches:
                self._apply_sites_patch(data, pe, sp, 0, {}, log, result)
                if result.error:
                    return result

        # ── 6. 更新 PE 头 ──
        total_new = len(data_section_results) + (1 if need_test else 0)
        if total_new:
            e_lfanew = pe.e_lfanew
            opt_off = e_lfanew + 24
            sec_table_off = e_lfanew + 24 + pe.opt_size
            new_num_sections = pe.num_sections + total_new
            struct.pack_into('<H', data, e_lfanew + 6, new_num_sections)
            struct.pack_into('<I', data, opt_off + 56, next_va)

            for i, (item, _, raw_off, va) in enumerate(data_section_results):
                sec_entry_off = sec_table_off + (pe.num_sections + i) * 40
                if sec_entry_off + 40 > pe.size_of_headers:
                    result.error = '节表空间不足'
                    log.append(result.error)
                    return result
                name_b = item.section_name.encode('ascii')[:8].ljust(8, b'\x00')
                entry = name_b + struct.pack('<IIIIIIHHI',
                    len(item.data), va, 0, 0,
                    0, 0, 0, 0, self.SECTION_CHARS_DATA)
                data[sec_entry_off:sec_entry_off + 40] = entry

            if need_test:
                sec_entry_off = (sec_table_off
                                 + (pe.num_sections + len(data_section_results)) * 40)
                if sec_entry_off + 40 > pe.size_of_headers:
                    result.error = '节表空间不足'
                    log.append(result.error)
                    return result
                name_b = section_name.encode('ascii')[:8].ljust(8, b'\x00')
                entry = name_b + struct.pack('<IIIIIIHHI',
                    test_vsize, test_rva, test_raw_size, test_file_off,
                    0, 0, 0, 0, self.SECTION_CHARS_CODE)
                data[sec_entry_off:sec_entry_off + 40] = entry

            log.append(f'PE 头: NumberOfSections={new_num_sections}, '
                       f'SizeOfImage=0x{next_va:X}')

        # ── 7. 写入输出文件 ──
        with open(output_path, 'wb') as f:
            f.write(bytes(data))

        result.success = True
        log.append(f'输出: {output_path} ({len(data)} 字节)')
        return result


def _parse_int(val) -> int:
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if s.lower().startswith('0x'):
        return int(s, 16)
    return int(s)
