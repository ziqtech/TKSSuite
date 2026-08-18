# -*- coding: utf-8 -*-
"""
PE 文件结构解析工具

提供以下功能:
- 解析 PE 节表
- 提取节区原始数据
- RVA 与文件偏移互转
- 解析入口点
- 解析导入表 (DLL + 函数名)
- 解析节区特性标志

适用: PE32 (32-bit), 部分支持 PE32+
"""
import struct
from typing import List, Dict, Optional, Tuple


# IMAGE_SCN_* 节区特性常量
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_CNT_UNINITIALIZED_DATA = 0x00000080
IMAGE_SCN_MEM_DISCARDABLE = 0x02000000
IMAGE_SCN_MEM_NOT_CACHED = 0x04000000
IMAGE_SCN_MEM_NOT_PAGED = 0x08000000
IMAGE_SCN_MEM_SHARED = 0x10000000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000

CHARACTERISTICS_FLAGS = [
    (IMAGE_SCN_MEM_WRITE, "MEM_WRITE"),
    (IMAGE_SCN_MEM_READ, "MEM_READ"),
    (IMAGE_SCN_MEM_EXECUTE, "MEM_EXECUTE"),
    (IMAGE_SCN_MEM_SHARED, "MEM_SHARED"),
    (IMAGE_SCN_MEM_NOT_PAGED, "MEM_NOT_PAGED"),
    (IMAGE_SCN_MEM_NOT_CACHED, "MEM_NOT_CACHED"),
    (IMAGE_SCN_MEM_DISCARDABLE, "MEM_DISCARDABLE"),
    (IMAGE_SCN_CNT_UNINITIALIZED_DATA, "CNT_UNINITIALIZED_DATA"),
    (IMAGE_SCN_CNT_INITIALIZED_DATA, "CNT_INITIALIZED_DATA"),
    (IMAGE_SCN_CNT_CODE, "CNT_CODE"),
]


def read_pe_sections(data: bytes) -> List[Dict]:
    """
    解析 PE 文件的节表

    Returns:
        list of dict, 每个 dict 包含:
            - name (str):           节区名称
            - raw_name (bytes):     原始 8 字节名称
            - virtual_size (int):   虚拟大小
            - virtual_address (int): 虚拟地址 (RVA)
            - raw_size (int):       原始大小
            - raw_offset (int):     原始文件偏移
            - characteristics (int): 特性标志
    """
    if data[:2] != b'MZ':
        raise ValueError("Not a valid PE file (missing MZ signature)")

    pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
    if pe_offset + 4 > len(data) or data[pe_offset:pe_offset+4] != b'PE\x00\x00':
        raise ValueError(f"Not a valid PE file (missing PE signature at 0x{pe_offset:X})")

    coff_offset = pe_offset + 4
    num_sections = struct.unpack_from('<H', data, coff_offset + 2)[0]
    optional_header_size = struct.unpack_from('<H', data, coff_offset + 16)[0]
    section_table_offset = coff_offset + 20 + optional_header_size

    sections = []
    for i in range(num_sections):
        offset = section_table_offset + i * 40
        if offset + 40 > len(data):
            break

        raw_name = data[offset:offset+8]
        virtual_size = struct.unpack_from('<I', data, offset + 8)[0]
        virtual_address = struct.unpack_from('<I', data, offset + 12)[0]
        raw_size = struct.unpack_from('<I', data, offset + 16)[0]
        raw_offset = struct.unpack_from('<I', data, offset + 20)[0]
        characteristics = struct.unpack_from('<I', data, offset + 36)[0]

        # 处理节区名称
        if raw_name[0] == 0:
            # 超过 8 字符的扩展名称 (/xxxx)
            try:
                name_offset_val = struct.unpack_from('<I', raw_name[1:5], 0)[0]
                name = data[name_offset_val:name_offset_val+80].split(b'\x00')[0].decode('ascii', errors='replace')
            except Exception:
                name = raw_name.decode('latin-1', errors='replace')
        else:
            name = raw_name.rstrip(b'\x00').decode('latin-1', errors='replace')

        sections.append({
            'name': name,
            'raw_name': raw_name,
            'virtual_size': virtual_size,
            'virtual_address': virtual_address,
            'raw_size': raw_size,
            'raw_offset': raw_offset,
            'characteristics': characteristics,
        })

    return sections


def find_section(sections: List[Dict], name: str) -> Optional[Dict]:
    """按名称查找节区"""
    for sec in sections:
        if sec['name'] == name:
            return sec
    return None


def extract_section_data(data: bytes, section: Dict) -> bytes:
    """
    从原始文件中提取节区数据

    注意: 使用 raw_size 而非 virtual_size, virtual_size 可能大于文件中实际数据
    """
    raw_size = section['raw_size']
    if raw_size == 0:
        return b''
    raw_offset = section['raw_offset']
    if raw_offset >= len(data):
        return b''
    size = min(raw_size, len(data) - raw_offset)
    if size <= 0:
        return b''
    return data[raw_offset:raw_offset+size]


def rva_to_file_offset(rva: int, sections: List[Dict]) -> Optional[int]:
    """RVA 转文件偏移, 找不到时返回 None"""
    for sec in sections:
        sec_end = sec['virtual_address'] + max(sec['virtual_size'], sec['raw_size'])
        if sec['virtual_address'] <= rva < sec_end:
            return sec['raw_offset'] + (rva - sec['virtual_address'])
    return None


def file_offset_to_rva(file_offset: int, sections: List[Dict]) -> Optional[int]:
    """文件偏移转 RVA, 找不到时返回 None"""
    for sec in sections:
        sec_end = sec['raw_offset'] + sec['raw_size']
        if sec['raw_offset'] <= file_offset < sec_end:
            return sec['virtual_address'] + (file_offset - sec['raw_offset'])
    return None


def get_entry_point(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """
    读取 PE 入口点

    Returns:
        (entry_rva, entry_file_offset), 任一不存在时返回 None
    """
    if len(data) < 0x40:
        return None, None
    try:
        pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
        opt_offset = pe_offset + 24
        if opt_offset + 20 > len(data):
            return None, None
        entry_rva = struct.unpack_from('<I', data, opt_offset + 16)[0]
        sections = read_pe_sections(data)
        entry_offset = rva_to_file_offset(entry_rva, sections)
        return entry_rva, entry_offset
    except (struct.error, ValueError):
        return None, None


def get_image_base(data: bytes) -> int:
    """读取 ImageBase (PE32 默认 0x400000)"""
    try:
        pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
        opt_offset = pe_offset + 24
        if opt_offset + 28 > len(data):
            return 0x400000
        magic = struct.unpack_from('<H', data, opt_offset)[0]
        if magic == 0x10B:  # PE32
            return struct.unpack_from('<I', data, opt_offset + 28)[0]
        elif magic == 0x20B:  # PE32+
            return struct.unpack_from('<Q', data, opt_offset + 24)[0] & 0xFFFFFFFF
    except (struct.error, ValueError):
        pass
    return 0x400000


def decode_characteristics(flags: int) -> List[str]:
    """将节区特性标志解码为可读名称列表"""
    names = []
    for mask, name in CHARACTERISTICS_FLAGS:
        if flags & mask:
            names.append(name)
    return names


def parse_import_directory(data: bytes, sections: List[Dict],
                           max_dlls: int = 50,
                           start_offset: Optional[int] = None) -> List[Dict]:
    """
    解析 PE 导入表

    支持两种格式:
    1. 标准 PE 导入表 (通过 Optional Header[96] 定位) - 默认
    2. 嵌入式导入表 (通过 start_offset 指定文件偏移, 用于 .Silvana 等自定义节区)

    Args:
        data: 完整 PE 文件字节
        sections: read_pe_sections 返回的节区列表
        max_dlls: 最大解析 DLL 数量
        start_offset: 自定义起始文件偏移, 跳过标准 PE 导入表查找

    Returns:
        list of {module: str, functions: [str, ...]}
    """
    if start_offset is None:
        if len(data) < 0x40:
            return []

        try:
            pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
            coff_offset = pe_offset + 4
            optional_header_size = struct.unpack_from('<H', data, coff_offset + 16)[0]
            opt_offset = coff_offset + 20

            # PE32: Import Directory RVA 在 Optional Header[96]
            import_rva = struct.unpack_from('<I', data, opt_offset + 96)[0]
            import_size = struct.unpack_from('<I', data, opt_offset + 100)[0]
            if import_rva == 0:
                return []

            import_offset = rva_to_file_offset(import_rva, sections)
            if import_offset is None:
                return []
        except (struct.error, ValueError):
            return []
    else:
        import_offset = start_offset

    imports = []
    offset = import_offset
    while offset + 20 <= len(data) and len(imports) < max_dlls:
        # IMAGE_IMPORT_DESCRIPTOR: 5 个 DWORD (20字节)
        ilt_rva = struct.unpack_from('<I', data, offset)[0]
        name_rva = struct.unpack_from('<I', data, offset + 12)[0]

        if ilt_rva == 0 and name_rva == 0:
            break

        # 读取 DLL 名称
        if start_offset is not None:
            # 嵌入式导入表: name_rva 可能是文件偏移
            name_offset = name_rva if name_rva < len(data) else None
        else:
            name_offset = rva_to_file_offset(name_rva, sections)

        if name_offset is None or name_offset >= len(data):
            offset += 20
            continue
        module_name = data[name_offset:name_offset+100].split(b'\x00')[0].decode('ascii', errors='replace')
        if not module_name or not module_name.replace('.', '').replace('_', '').isalnum():
            offset += 20
            continue

        # 解析导入查找表 (ILT)
        if start_offset is not None:
            ilt_offset = ilt_rva if ilt_rva < len(data) else None
        else:
            ilt_offset = rva_to_file_offset(ilt_rva, sections) if ilt_rva else None

        func_names = []
        if ilt_offset:
            f = ilt_offset
            while f + 4 <= len(data):
                entry = struct.unpack_from('<I', data, f)[0]
                if entry == 0:
                    break
                if entry & 0x80000000:  # 按序号导入
                    func_names.append(f"Ordinal#{entry & 0x7FFFFFFF}")
                else:  # 按名称导入 (Hint/Name RVA 或文件偏移)
                    if start_offset is not None:
                        name_off = entry if entry < len(data) else None
                    else:
                        name_off = rva_to_file_offset(entry & 0x7FFFFFFF, sections)
                    if name_off and name_off + 2 < len(data):
                        try:
                            end = data.index(b'\x00', name_off + 2)
                            fn = data[name_off + 2:end].decode('ascii', errors='replace')
                            if fn:
                                func_names.append(fn)
                        except ValueError:
                            pass
                f += 4

        imports.append({'module': module_name, 'functions': func_names})
        offset += 20

    return imports


def parse_silvana_imports(data: bytes, section: Dict) -> List[Dict]:
    """
    解析 .Silvana 节区的嵌入式导入表

    .Silvana 节区使用自定义格式:
    - DLL名 (ASCII string) + 多个 \\x00 填充 (使其长度为 4 的倍数)
    - 函数名 (ASCII string) + \\x00 填充
    - 4 字节的函数指针 RVA

    真实例子 (TKS.exe):
        'kernel32\\x00\\x00\\x00WinExec\\x00'      -> \\x09\\xf0\\x67\\x00 (4字节指针)
        'kernel32.dll\\x00\\x00\\x00WinExec\\x00'  -> \\x28\\xf0\\x67\\x00
        'SHELL32.dll\\x00\\x00\\x00ShellExecuteA\\x00' -> \\x46\\xf0\\x67\\x00

    Returns:
        list of {dll: str, function: str, ptr_rva: int}
    """
    sec_data = extract_section_data(data, section)
    if not sec_data:
        return []

    results = []
    i = 0
    while i < len(sec_data) - 8:
        # 寻找 DLL 名字符串 (以 \\x00 结尾)
        dll_end = sec_data.find(b'\x00', i)
        if dll_end == -1 or dll_end - i > 30:
            i += 1
            continue

        dll_name = sec_data[i:dll_end].decode('ascii', errors='replace')
        if not (3 <= len(dll_name) <= 30):
            i = dll_end + 1
            continue

        # 看起来像 DLL 名称?
        is_dll = (dll_name.lower().endswith('.dll')
                  or dll_name.lower() in ('kernel32', 'shell32'))

        if not is_dll:
            i = dll_end + 1
            continue

        # 跳过 DLL 名后的所有 \\x00 填充 (到非 \\x00 为止)
        func_start = dll_end
        while func_start < len(sec_data) and sec_data[func_start] == 0:
            func_start += 1

        # 寻找函数名 (以 \\x00 结尾)
        func_end = sec_data.find(b'\x00', func_start)
        if func_end == -1 or func_end - func_start > 50 or func_end == func_start:
            i = dll_end + 1
            continue

        func_name = sec_data[func_start:func_end].decode('ascii', errors='replace')
        if not func_name or not func_name.isprintable():
            i = func_end + 1
            continue

        # 跳过函数名后的 \\x00 填充
        ptr_offset = func_end
        while ptr_offset < len(sec_data) and sec_data[ptr_offset] == 0:
            ptr_offset += 1

        # 期望接下来是 4 字节指针
        if ptr_offset + 4 > len(sec_data):
            break

        ptr_rva = struct.unpack_from('<I', sec_data, ptr_offset)[0]

        results.append({
            'dll': dll_name,
            'function': func_name,
            'ptr_rva': ptr_rva,
        })
        i = ptr_offset + 4

    return results


def section_summary(sec: Dict) -> str:
    """返回格式化的节区摘要字符串"""
    chars = decode_characteristics(sec['characteristics'])
    return (f"{sec['name']:<12} "
            f"VAddr=0x{sec['virtual_address']:08X} "
            f"ROffset=0x{sec['raw_offset']:08X} "
            f"VSize={sec['virtual_size']:>8,} "
            f"RSize={sec['raw_size']:>8,} "
            f"Char=0x{sec['characteristics']:08X} {'|'.join(chars)}")