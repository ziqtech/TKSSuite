"""exe_builder — 将选中补丁烧录进原版 TKS.exe，生成独立可分发的修改版 exe

工作原理（参照 TKS_MOD.exe 的 .test 节补丁方式）：
  1. 读取原版 TKS.exe
  2. 在 PE 末尾追加 .test 节（代码洞）与 .Silvana 节（导入表扩展，可选）
  3. 将各补丁的 cave_code 写入 .test 节
  4. 在 .text 原始 hook 点写入 jmp rel32 跳转到 cave
  5. 更新 NumberOfSections / SizeOfImage
  6. 输出修改版 exe

限制：
  - 仅支持 cave_hook 型补丁（含 patch_exp_lock）
  - 需要 hook_pattern 在文件中唯一匹配
  - cave_code 中的绝对地址需已由启动器运行时解析（本模块使用文件 RVA 直接计算）
"""
import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


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


def find_pattern(data: bytes, pattern: bytes) -> List[int]:
    """在 data 中查找 pattern 的所有偏移。"""
    offsets = []
    start = 0
    while True:
        idx = data.find(pattern, start)
        if idx < 0:
            break
        offsets.append(idx)
        start = idx + 1
    return offsets


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
    hook_pattern: bytes          # 原始指令字节（用于定位 hook 点）
    hook_size: int               # 被覆盖的原始指令长度（jmp rel32 = 5，需 hook_size >= 5）
    cave_code: bytes             # cave 机器码
    fallback_rva: int = 0        # 模式匹配失败时的回退 RVA
    expect_count: int = 1


@dataclass
class CaveBuildResult:
    success: bool
    output_path: str = ''
    log: List[str] = field(default_factory=list)
    error: str = ''


class ExeBuilder:
    """将 cave 补丁烧录进原版 exe。"""

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

    def build(self, patches: List[CavePatchItem],
              output_path: str,
              section_name: str = '.test') -> CaveBuildResult:
        """构建修改版 exe。

        Args:
            patches: 待烧录的 cave 补丁列表
            output_path: 输出路径
            section_name: 新节名称（默认 .test）

        Returns:
            CaveBuildResult
        """
        log: List[str] = []
        result = CaveBuildResult(success=False, output_path=output_path, log=log)

        if not patches:
            result.error = '未选择任何 cave 型补丁'
            log.append(result.error)
            return result

        pe = self._pe
        data = bytearray(self._orig_data)

        # ── 1. 定位所有 hook 点 ──
        hook_targets = []  # (item, hook_file_offset)
        for item in patches:
            offsets = find_pattern(bytes(data), item.hook_pattern)
            if len(offsets) != item.expect_count:
                if item.fallback_rva:
                    off = rva_to_offset(pe, item.fallback_rva)
                    log.append(f'[{item.patch_id}] 模式匹配 {len(offsets)} 次，'
                               f'使用回退 RVA 0x{item.fallback_rva:X}')
                    hook_targets.append((item, off))
                else:
                    result.error = (f'[{item.patch_id}] hook_pattern 匹配 '
                                    f'{len(offsets)} 次，期望 {item.expect_count} 次')
                    log.append(result.error)
                    return result
            else:
                hook_targets.append((item, offsets[0]))
                log.append(f'[{item.patch_id}] hook 点 @ 文件偏移 0x{offsets[0]:X} '
                           f'(RVA 0x{offset_to_rva(pe, offsets[0]):X})')

        # ── 2. 计算 .test 节布局 ──
        # 每个补丁的 cave_code 按 16 字节对齐
        cave_blobs = []
        cave_total = 0
        for item, _ in hook_targets:
            aligned_off = align_up(cave_total, 16)
            cave_blobs.append((item, aligned_off))
            cave_total = aligned_off + len(item.cave_code)

        # jmp rel32 = 5 字节；hook_size 必须 >= 5
        for item, _ in hook_targets:
            if item.hook_size < 5:
                result.error = (f'[{item.patch_id}] hook_size={item.hook_size} < 5，'
                                f'无法写入 jmp rel32')
                log.append(result.error)
                return result

        # .test 节大小（文件对齐）
        test_raw_size = align_up(cave_total, pe.file_align)
        test_vsize = cave_total

        # ── 3. 计算新节的 RVA / 文件偏移 ──
        last_sec = pe.sections[-1]
        new_va = align_up(
            last_sec.virtual_addr + max(last_sec.virtual_size, last_sec.raw_size),
            pe.section_align)
        new_raw_off = align_up(len(data), pe.file_align)

        test_rva = new_va
        test_file_off = new_raw_off

        log.append(f'.test 节: RVA=0x{test_rva:X}, 文件偏移=0x{test_file_off:X}, '
                   f'大小=0x{test_raw_size:X} ({test_raw_size} 字节)')

        # ── 4. 在 data 末尾填充到 new_raw_off 并写入 cave 代码 ──
        if len(data) < new_raw_off:
            data.extend(b'\x00' * (new_raw_off - len(data)))

        cave_section = bytearray(test_raw_size)
        for item, cave_off in cave_blobs:
            cave_section[cave_off:cave_off + len(item.cave_code)] = item.cave_code
            log.append(f'[{item.patch_id}] cave 代码写入 .test+0x{cave_off:X} '
                       f'({len(item.cave_code)} 字节)')

        data.extend(cave_section)

        # ── 5. 在 hook 点写入 jmp rel32 ──
        for (item, hook_off), (_, cave_off) in zip(hook_targets, cave_blobs):
            hook_rva = offset_to_rva(pe, hook_off)
            cave_target_rva = test_rva + cave_off
            # jmp rel32: E9 xx xx xx xx
            # rel32 = target - (hook_rva + 5)
            rel32 = cave_target_rva - (hook_rva + 5)
            jmp_bytes = b'\xE9' + struct.pack('<i', rel32)
            # 用 NOP 填充 hook_size 剩余部分
            nop_fill = b'\x90' * (item.hook_size - 5)
            patch_bytes = jmp_bytes + nop_fill
            data[hook_off:hook_off + item.hook_size] = patch_bytes
            log.append(f'[{item.patch_id}] hook 0x{hook_off:X}: '
                       f'jmp 0x{cave_target_rva:X} (rel32=0x{rel32 & 0xFFFFFFFF:X})')

        # ── 6. 更新 PE 头 ──
        e_lfanew = pe.e_lfanew
        opt_off = e_lfanew + 24
        sec_table_off = e_lfanew + 24 + pe.opt_size

        # NumberOfSections
        new_num_sections = pe.num_sections + 1
        struct.pack_into('<H', data, e_lfanew + 6, new_num_sections)

        # SizeOfImage
        new_size_of_image = align_up(new_va + test_vsize, pe.section_align)
        struct.pack_into('<I', data, opt_off + 56, new_size_of_image)

        # 写入新节表项（追加在现有节表之后）
        new_sec_entry_off = sec_table_off + pe.num_sections * 40
        # 确保节表有空间（SizeOfHeaders 之前）
        if new_sec_entry_off + 40 > pe.size_of_headers:
            # 节表空间不足，需要扩展 headers（罕见情况）
            result.error = (f'节表空间不足: 需要 0x{new_sec_entry_off + 40:X}，'
                            f'但 SizeOfHeaders=0x{pe.size_of_headers:X}')
            log.append(result.error)
            return result

        # 构造节表项
        sec_name_bytes = section_name.encode('ascii')[:8].ljust(8, b'\x00')
        sec_entry = sec_name_bytes + struct.pack('<IIIIIIHHI',
            test_vsize,          # VirtualSize
            new_va,              # VirtualAddress
            test_raw_size,       # SizeOfRawData
            test_file_off,       # PointerToRawData
            0,                   # PointerToRelocations
            0,                   # PointerToLinenumbers
            0,                   # NumberOfRelocations
            0,                   # NumberOfLinenumbers
            self.SECTION_CHARS_CODE,  # Characteristics
        )
        data[new_sec_entry_off:new_sec_entry_off + 40] = sec_entry

        log.append(f'PE 头: NumberOfSections={new_num_sections}, '
                   f'SizeOfImage=0x{new_size_of_image:X}')

        # ── 7. 写入输出文件 ──
        with open(output_path, 'wb') as f:
            f.write(bytes(data))

        result.success = True
        log.append(f'输出: {output_path} ({len(data)} 字节)')
        return result
