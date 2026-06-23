"""
MOD 加载器 — 扫描 mods/ 目录、解析 .tksmod、依赖排序、冲突检测、数据合并
==========================================================================
核心流程:
  1. scan_mods(mods_dir) -> List[ModInfo]          扫描目录
  2. resolve_dependencies(mods) -> List[ModInfo]   拓扑排序
  3. detect_conflicts(mods) -> List[Conflict]      冲突检测
  4. merge_mods(mods, game_dir) -> MergedData      合并差异
  5. apply_mod_data(merged, game_dir)              写入文件
  6. restore_originals(game_dir)                   恢复原始文件
"""
import os
import json
import struct
import shutil
import zipfile
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .lzss import lzss_decompress, lzss_compress


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class ModInfo:
    """解析后的 MOD 元数据"""
    path: str = ""
    mod_id: str = ""
    name: str = ""
    version: str = "1.0.0"
    author: str = ""
    description: str = ""
    mod_type: str = "data"
    mode: str = "mixed"
    load_order: int = 100
    dependencies: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    id_ranges: Dict[str, Dict[str, int]] = field(default_factory=dict)
    warpc_expand: int = 0
    components: List[Dict[str, str]] = field(default_factory=list)
    resources: List[Dict[str, str]] = field(default_factory=list)
    # 加载后的数据
    data_files: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Conflict:
    """冲突记录"""
    mod1_id: str = ""
    mod2_id: str = ""
    conflict_type: str = ""  # "id_range" | "field_overlap" | "resource" | "explicit"
    target: str = ""
    detail: str = ""


@dataclass
class MergedData:
    """合并后的数据"""
    # 目标文件 -> 合并后的记录数据 (解压后的完整字节流)
    file_data: Dict[str, bytes] = field(default_factory=dict)
    # 需要备份的原始文件列表
    backed_up: List[str] = field(default_factory=list)
    # WarPC 需要扩展到的数量
    warpc_expand_count: int = 0
    # 资源文件替换: {target_name: source_path_in_zip}
    resource_replacements: Dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# 1. 扫描 MOD 目录
# ═══════════════════════════════════════════════════════════════

def scan_mods(mods_dir: str, log_func=None) -> List[ModInfo]:
    """扫描 mods/ 目录中所有 .tksmod 文件，返回 ModInfo 列表"""
    log = log_func or (lambda x: None)
    mods = []

    if not os.path.isdir(mods_dir):
        log(f"  MOD 目录不存在: {mods_dir}")
        return mods

    for fname in sorted(os.listdir(mods_dir)):
        if not fname.lower().endswith('.tksmod'):
            continue
        fpath = os.path.join(mods_dir, fname)
        try:
            mod = _load_single_mod(fpath, log)
            if mod:
                mods.append(mod)
                log(f"  [OK] 加载 MOD: {mod.name} v{mod.version} ({fname})")
        except Exception as e:
            log(f"  [WARN] 加载 {fname} 失败: {e}")

    log(f"  共发现 {len(mods)} 个 MOD 文件")
    return mods


def _load_single_mod(mod_path: str, log_func=None) -> Optional[ModInfo]:
    """从 .tksmod (ZIP) 文件中解析 ModInfo"""
    log = log_func or (lambda x: None)

    with zipfile.ZipFile(mod_path, 'r') as zf:
        # 读取 mod.json
        if "mod.json" not in zf.namelist():
            log(f"    缺少 mod.json")
            return None

        mod_json_str = zf.read("mod.json").decode('utf-8')
        mj = json.loads(mod_json_str)

        # 验证格式
        if mj.get("format") != "TKSMOD":
            log(f"    无效格式: {mj.get('format')}")
            return None

        mod = ModInfo(
            path=mod_path,
            mod_id=mj.get("id", ""),
            name=mj.get("name", ""),
            version=mj.get("version", "1.0.0"),
            author=mj.get("author", ""),
            description=mj.get("description", ""),
            mod_type=mj.get("type", "data"),
            mode=mj.get("mode", "mixed"),
            load_order=mj.get("load_order", 100),
            dependencies=mj.get("dependencies", []),
            conflicts=mj.get("conflicts", []),
            id_ranges=mj.get("id_ranges", {}),
            warpc_expand=mj.get("warpc_expand", 0),
            components=mj.get("components", []),
            resources=mj.get("resources", []),
        )

        # 预加载数据文件
        for comp in mod.components:
            internal_path = comp.get("file", "")
            if internal_path in zf.namelist():
                content = zf.read(internal_path).decode('utf-8')
                mod.data_files[internal_path] = json.loads(content)

        return mod


# ═══════════════════════════════════════════════════════════════
# 2. 依赖解析与拓扑排序
# ═══════════════════════════════════════════════════════════════

def resolve_dependencies(mods: List[ModInfo], log_func=None) -> List[ModInfo]:
    """按依赖关系和 load_order 排序 MOD 列表"""
    log = log_func or (lambda x: None)

    # 先过滤启用的 MOD
    active = [m for m in mods if m.enabled]

    # 按 load_order 排序
    active.sort(key=lambda m: m.load_order)

    # 简单拓扑排序（基于 dependencies）
    id_map = {m.mod_id: m for m in active}
    visited = set()
    result = []

    def visit(mod_id: str):
        if mod_id in visited:
            return
        visited.add(mod_id)
        if mod_id in id_map:
            mod = id_map[mod_id]
            for dep in mod.dependencies:
                if dep in id_map:
                    visit(dep)
            result.append(mod)

    for m in active:
        visit(m.mod_id)

    # 检查缺失依赖
    all_ids = set(m.mod_id for m in active)
    for m in active:
        for dep in m.dependencies:
            if dep not in all_ids:
                log(f"  [WARN] MOD '{m.name}' 依赖 '{dep}' 未找到")

    return result


# ═══════════════════════════════════════════════════════════════
# 3. 冲突检测
# ═══════════════════════════════════════════════════════════════

def detect_conflicts(mods: List[ModInfo], log_func=None) -> List[Conflict]:
    """检测 MOD 之间的冲突"""
    log = log_func or (lambda x: None)
    conflicts = []

    for i in range(len(mods)):
        for j in range(i + 1, len(mods)):
            m1, m2 = mods[i], mods[j]

            # 显式冲突声明
            if m2.mod_id in m1.conflicts or m1.mod_id in m2.conflicts:
                conflicts.append(Conflict(
                    mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                    conflict_type="explicit",
                    detail=f"'{m1.name}' 与 '{m2.name}' 显式声明冲突"))

            # ID 范围冲突
            for key in m1.id_ranges:
                if key in m2.id_ranges:
                    r1 = m1.id_ranges[key]
                    r2 = m2.id_ranges[key]
                    if r1.get("start", 0) <= r2.get("end", 0) and \
                       r2.get("start", 0) <= r1.get("end", 0):
                        conflicts.append(Conflict(
                            mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                            conflict_type="id_range", target=key,
                            detail=f"{key} ID 范围重叠: "
                                   f"{m1.name}[{r1.get('start')}-{r1.get('end')}] "
                                   f"vs {m2.name}[{r2.get('start')}-{r2.get('end')}]"))

            # 资源文件冲突
            targets1 = set(r.get("target", "") for r in m1.resources)
            targets2 = set(r.get("target", "") for r in m2.resources)
            overlap = targets1 & targets2
            for t in overlap:
                conflicts.append(Conflict(
                    mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                    conflict_type="resource", target=t,
                    detail=f"资源文件 '{t}' 被多个 MOD 替换"))

    if conflicts:
        log(f"  检测到 {len(conflicts)} 个冲突")
        for c in conflicts:
            log(f"    [{c.conflict_type}] {c.detail}")
    else:
        log(f"  无冲突")

    return conflicts


# ═══════════════════════════════════════════════════════════════
# 4. MOD 数据合并
# ═══════════════════════════════════════════════════════════════

# DAT 文件元信息
DAT_FILE_INFO = {
    "WarPC.dat":    {"rec_size": 1054, "field_type": "int16", "field_count": 527, "orig_count": 143, "lzss": True},
    "TKSkill.dat":  {"rec_size": 94,   "field_type": "int16", "field_count": 47,  "orig_count": 350, "lzss": True},
    "TKItem.dat":   {"rec_size": 64,   "field_type": "int16", "field_count": 32,  "orig_count": 600, "lzss": True},
    "TKShop.dat":   {"rec_size": 8,    "field_type": "mixed", "field_count": 4,   "orig_count": 240, "lzss": True},
    "TKKon.dat":    {"rec_size": 40,   "field_type": "int16", "field_count": 20,  "orig_count": 650, "lzss": True},
    "TKMat.Dat":    {"rec_size": 384,  "field_type": "int32", "field_count": 96,  "orig_count": 6000, "lzss": False},
    "TKDefUnit.Dat":{"rec_size": 16,   "field_type": "uint16","field_count": 8,   "orig_count": 5000, "lzss": False},
}


def _is_text_diff(diff_data: dict) -> bool:
    """判断差异数据是否为文本级别差异 (TKD.dat 类型)

    文本差异的特征: modified 是 dict (而非 list), 且有 deleted 字段
    """
    modified = diff_data.get("modified")
    has_deleted = "deleted" in diff_data
    has_no_record_size = "record_size" not in diff_data
    return isinstance(modified, dict) and has_deleted and has_no_record_size


def merge_mods(mods: List[ModInfo], game_dir: str, log_func=None) -> MergedData:
    """合并所有 MOD 的数据差异，生成合并后的完整数据"""
    log = log_func or (lambda x: None)
    merged = MergedData()

    # 收集需要处理的目标文件
    targets: Dict[str, List[Tuple[ModInfo, dict]]] = {}
    for mod in mods:
        for comp in mod.components:
            target = comp.get("target", "")
            internal = comp.get("file", "")
            if target and internal in mod.data_files:
                if target not in targets:
                    targets[target] = []
                targets[target].append((mod, mod.data_files[internal]))

        # 资源替换
        for res in mod.resources:
            target = res.get("target", "")
            if target:
                merged.resource_replacements[target] = (mod.path, res.get("file", ""))

        # WarPC 扩展需求
        if mod.warpc_expand > merged.warpc_expand_count:
            merged.warpc_expand_count = mod.warpc_expand

    # 对每个目标文件进行合并
    for target, mod_diffs in targets.items():
        target_path = os.path.join(game_dir, target)
        if not os.path.isfile(target_path):
            log(f"  [WARN] 目标文件不存在: {target_path}")
            continue

        # 检测差异数据格式并分派到对应处理器
        first_diff_data = mod_diffs[0][1] if mod_diffs else {}
        patch_type = first_diff_data.get("patch_type", "")

        if patch_type == "block_diff":
            # GRP/JVG 块级二进制差异
            # 备份原始 GRP 和 IDX 文件
            orig_path = target_path + ".mod_orig"
            if os.path.isfile(target_path) and not os.path.isfile(orig_path):
                shutil.copy2(target_path, orig_path)
                merged.backed_up.append(target_path)
                log(f"  备份: {target} → {target}.mod_orig")
            # 备份 IDX 文件
            for ext in ['.IDX', '.idx']:
                idx_candidate = str(Path(target_path).with_suffix(ext))
                if os.path.exists(idx_candidate):
                    idx_orig = idx_candidate + ".mod_orig"
                    if not os.path.isfile(idx_orig):
                        shutil.copy2(idx_candidate, idx_orig)
                        merged.backed_up.append(idx_candidate)
                        log(f"  备份: {os.path.basename(idx_candidate)} → {os.path.basename(idx_candidate)}.mod_orig")
                    break
            # 合并并直接写入
            result = _merge_block_file(target_path, target, mod_diffs, log)
            if result == "direct_write":
                log(f"  写入: {target} (块级合并完成)")

        elif _is_text_diff(first_diff_data):
            # TKD.dat 文本脚本差异
            result = _merge_text_file(target_path, target, mod_diffs, log)
            if result is not None:
                merged.file_data[target] = result

        else:
            # 定长记录 DAT 文件
            info = DAT_FILE_INFO.get(target)
            if info:
                result = _merge_dat_file(target_path, target, info, mod_diffs, log)
                if result is not None:
                    merged.file_data[target] = result
            else:
                log(f"  [WARN] 未知文件类型: {target}")

    return merged


def _merge_dat_file(file_path: str, target_name: str, info: dict,
                    mod_diffs: List[Tuple[ModInfo, dict]], log_func=None) -> Optional[bytes]:
    """合并定长记录类 DAT 文件"""
    log = log_func or (lambda x: None)
    rec_size = info["rec_size"]
    field_count = info["field_count"]
    field_type = info["field_type"]
    orig_count = info["orig_count"]
    use_lzss = info["lzss"]

    # 加载原始数据
    with open(file_path, 'rb') as f:
        raw = f.read()

    if use_lzss:
        dec = lzss_decompress(raw)
    else:
        dec = raw

    actual_count = len(dec) // rec_size
    log(f"  合并 {target_name}: {actual_count} 条记录, {len(mod_diffs)} 个 MOD 差异")

    # 解析为可变数组
    records = bytearray(dec)

    # 确定最大记录数（可能因追加而增加）
    max_count = actual_count
    for mod, diff_data in mod_diffs:
        for app in diff_data.get("appended", []):
            idx = app.get("index", 0)
            if idx >= max_count:
                max_count = idx + 1

    # 如果需要扩展，填充到新大小
    if max_count > actual_count:
        records.extend(b'\x00' * ((max_count - actual_count) * rec_size))

    # 按顺序应用每个 MOD 的差异
    for mod, diff_data in mod_diffs:
        # 应用修改
        for entry in diff_data.get("modified", []):
            idx = entry.get("index", -1)
            if idx < 0 or idx >= max_count:
                continue
            fields = entry.get("fields", {})
            _apply_fields_to_record(records, idx, rec_size, field_type, field_count, fields)

        # 应用追加
        for entry in diff_data.get("appended", []):
            idx = entry.get("index", -1)
            if idx < 0 or idx >= max_count:
                continue
            fields = entry.get("fields", {})
            _apply_fields_to_record(records, idx, rec_size, field_type, field_count, fields)

        log(f"    应用 MOD '{mod.name}': {len(diff_data.get('modified', []))} 修改, "
            f"{len(diff_data.get('appended', []))} 追加")

    result = bytes(records[:max_count * rec_size])

    # 压缩回写
    if use_lzss:
        result = lzss_compress(result)

    return result


def _apply_fields_to_record(buf: bytearray, index: int, rec_size: int,
                            field_type: str, field_count: int, fields: dict):
    """将字段差异应用到记录缓冲区"""
    base_off = index * rec_size

    for field_key, value in fields.items():
        # 解析字段索引: "f0", "f1", ...
        if not field_key.startswith('f'):
            continue
        try:
            fi = int(field_key[1:])
        except ValueError:
            continue
        if fi < 0 or fi >= field_count:
            continue

        if field_type == "int16":
            off = base_off + fi * 2
            if off + 2 <= len(buf):
                struct.pack_into('<h', buf, off, int(value))
        elif field_type == "uint16":
            off = base_off + fi * 2
            if off + 2 <= len(buf):
                struct.pack_into('<H', buf, off, int(value) & 0xFFFF)
        elif field_type == "int32":
            off = base_off + fi * 4
            if off + 4 <= len(buf):
                struct.pack_into('<i', buf, off, int(value))


# ═══════════════════════════════════════════════════════════════
# 4b. TKD.dat 文本脚本差异合并
# ═══════════════════════════════════════════════════════════════

_TKD_XOR_TABLE = bytes([i ^ 0xFF for i in range(256)])


def _load_tkd_text(file_path: str) -> str:
    """加载 TKD.dat: XOR 0xFF 解密 + Big5 解码"""
    with open(file_path, 'rb') as f:
        data = f.read()
    decoded = data.translate(_TKD_XOR_TABLE)
    try:
        return decoded.decode('big5', errors='replace')
    except Exception:
        return decoded.decode('gbk', errors='replace')


def _save_tkd_text(file_path: str, text: str):
    """保存 TKD.dat: Big5 编码 + XOR 0xFF 加密"""
    try:
        encoded = text.encode('big5')
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = text.encode('gbk', errors='replace')
    encrypted = encoded.translate(_TKD_XOR_TABLE)
    with open(file_path, 'wb') as f:
        f.write(encrypted)


def _parse_tkd_defines(text: str) -> tuple:
    """解析 TKD.dat 为 DEFINE 块字典 + 文件头"""
    lines = text.split('\n')
    defines = {}  # {define_id_str: full_text_of_block}
    header_lines = []
    current_id = None
    current_lines = []
    seen_first_define = False

    for line in lines:
        raw = line.rstrip('\r')
        stripped = raw.strip()
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            define_id = parts[1] if len(parts) > 1 else "0"
            if not seen_first_define:
                seen_first_define = True
            if current_id is not None:
                # 保存前一个 (未正常闭合的 DEFINE)
                defines[current_id] = '\r\n'.join(current_lines)
            current_id = define_id
            current_lines = [raw]
        elif stripped.startswith('};') and current_id is not None:
            current_lines.append(raw)
            defines[current_id] = '\r\n'.join(current_lines)
            current_id = None
            current_lines = []
        elif current_id is not None:
            current_lines.append(raw)
        else:
            if not seen_first_define:
                header_lines.append(raw)
            # 块间空行忽略

    # 最后一个未闭合的块
    if current_id is not None:
        defines[current_id] = '\r\n'.join(current_lines)

    return defines, '\r\n'.join(header_lines)


def _rebuild_tkd_text(defines: dict, header: str) -> str:
    """重组 TKD.dat 完整文本"""
    parts = []
    if header:
        parts.append(header)
    for did in sorted(defines.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        parts.append(defines[did])
    parts.append('')
    parts.append('')
    return '\r\n'.join(parts)


def _merge_text_file(file_path: str, target_name: str,
                     mod_diffs: List[Tuple['ModInfo', dict]], log_func=None) -> Optional[bytes]:
    """合并文本脚本/文本表文件 (TKD.dat / TKT.dat)"""
    log = log_func or (lambda x: None)

    # 根据目标文件名分派
    lower_name = target_name.lower()
    if lower_name == "tkd.dat":
        return _merge_tkd_file(file_path, target_name, mod_diffs, log)
    elif lower_name == "tkt.dat":
        return _merge_tkt_file(file_path, target_name, mod_diffs, log)
    else:
        log(f"  [WARN] 不支持的文本差异文件类型: {target_name}")
        return None


def _merge_tkd_file(file_path: str, target_name: str,
                    mod_diffs: List[Tuple['ModInfo', dict]], log_func=None) -> Optional[bytes]:
    """合并 TKD.dat 脚本文件"""
    log = log_func or (lambda x: None)

    # 加载原始文本
    text = _load_tkd_text(file_path)
    defines, header = _parse_tkd_defines(text)
    log(f"  合并 {target_name}: {len(defines)} 个 DEFINE 块, {len(mod_diffs)} 个 MOD 差异")

    # 按顺序应用每个 MOD 的文本差异
    for mod, diff_data in mod_diffs:
        modified = diff_data.get("modified", {})
        appended = diff_data.get("appended", [])
        deleted = diff_data.get("deleted", [])

        # 应用修改
        for did, content in modified.items():
            defines[did] = content

        # 应用追加
        if isinstance(appended, list):
            for content in appended:
                # 从内容中提取 DEFINE ID
                for line in content.split('\n'):
                    stripped = line.strip().rstrip('\r')
                    if stripped.startswith('DEFINE'):
                        parts = stripped.split(None, 1)
                        if len(parts) > 1:
                            defines[parts[1]] = content
                        break
        elif isinstance(appended, dict):
            for did, content in appended.items():
                defines[did] = content

        # 应用删除
        for did in deleted:
            defines.pop(did, None)

        log(f"    应用 MOD '{mod.name}': {len(modified)} 修改, "
            f"{len(appended) if isinstance(appended, (list, dict)) else 0} 追加, "
            f"{len(deleted)} 删除")

    # 重组文本
    new_text = _rebuild_tkd_text(defines, header)

    # 编码为游戏格式 (Big5 + XOR)
    try:
        encoded = new_text.encode('big5')
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = new_text.encode('gbk', errors='replace')
    encrypted = encoded.translate(_TKD_XOR_TABLE)
    return encrypted


# ═══════════════════════════════════════════════════════════════
# 4b-2. TKT.dat 文本表差异合并
# ═══════════════════════════════════════════════════════════════

import re as _re
_TKT_TAG_PATTERN = _re.compile(r'<([A-Z]+),(\d+(?:,\d+)*)>')
_TKT_CONTROL_TAGS = {
    0x01: ("FRESET",  1, 1, 4),
    0x02: ("FCOLOR",  1, 1, 32),
    0x04: ("FSIZE",   1, 12, 48),
    0x05: ("FTYPE",   1, 1, 8),
    0x14: ("TEXT",    2, 1, 32767),
    0x15: ("VARNUM",  1, 1, 255),
    0x16: ("VARTXT",  1, 1, 255),
    0x1D: ("NAME",    1, 1, 2),
}
_TKT_TAG_NAME_MAP = {v[0]: (code, v[1], v[2], v[3])
                     for code, v in _TKT_CONTROL_TAGS.items()}
_TKT_XOR_KEY = 0xFF
_TKT_ENTRY_TERMINATOR = 0x00
_TKT_LINE_SEPARATOR = 0x1E


def _tkt_encode_line(text: str) -> bytes:
    """将带 <TAG,val> 标签的文本行编码回 TKT 二进制字节"""
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        m = _TKT_TAG_PATTERN.match(text, i)
        if m:
            tag_name = m.group(1)
            val_str = m.group(2)
            if tag_name in _TKT_TAG_NAME_MAP:
                code, data_len, min_val, max_val = _TKT_TAG_NAME_MAP[tag_name]
                val = int(val_str)
                if min_val <= val <= max_val:
                    out.append(code)
                    out.append(val & 0xFF)
                    if data_len == 2:
                        out.append((val >> 8) & 0xFF)
                    i = m.end()
                    continue
            for ch in text[i:m.end()]:
                out.extend(ch.encode('big5', errors='replace'))
            i = m.end()
            continue

        if text[i] == '<' and i + 6 < n:
            rm = _re.match(r'<RAW,0x([0-9A-Fa-f]{2})>', text[i:])
            if rm:
                out.append(int(rm.group(1), 16))
                i += rm.end()
                continue

        ch = text[i]
        try:
            encoded = ch.encode('big5')
        except (UnicodeEncodeError, UnicodeDecodeError):
            encoded = ch.encode('gbk', errors='replace')
        out.extend(encoded)
        i += 1
    return bytes(out)


def _tkt_decode_entry(blob: bytes) -> str:
    """解码 TKT 条目的原始字节为带标签的文本"""
    lines = blob.split(bytes([_TKT_LINE_SEPARATOR]))
    decoded = []
    for line_bytes in lines:
        out = []
        buf = bytearray()
        def flush():
            if buf:
                try:
                    out.append(buf.decode('big5', errors='replace'))
                except Exception:
                    out.append(buf.decode('gbk', errors='replace'))
                buf.clear()
        i = 0
        n = len(line_bytes)
        while i < n:
            b = line_bytes[i]
            if b in _TKT_CONTROL_TAGS:
                tag_name, data_len, _, _ = _TKT_CONTROL_TAGS[b]
                if i + data_len < n:
                    flush()
                    if data_len == 1:
                        val = line_bytes[i + 1]
                    elif data_len == 2:
                        val = line_bytes[i + 1] | (line_bytes[i + 2] << 8)
                    else:
                        val = 0
                    out.append(f'<{tag_name},{val}>')
                    i += 1 + data_len
                    continue
                else:
                    flush()
                    out.append(f'<RAW,0x{b:02X}>')
                    i += 1
                    continue
            if b < 0x20:
                flush()
                out.append(f'<RAW,0x{b:02X}>')
                i += 1
                continue
            if b >= 0x80 and i + 1 < n:
                buf.append(b)
                buf.append(line_bytes[i + 1])
                i += 2
            else:
                buf.append(b)
                i += 1
        flush()
        decoded.append(''.join(out))
    return '\n'.join(decoded)


def _merge_tkt_file(file_path: str, target_name: str,
                    mod_diffs: List[Tuple['ModInfo', dict]], log_func=None) -> Optional[bytes]:
    """合并 TKT.dat 文本表文件"""
    log = log_func or (lambda x: None)

    # 读取原始文件
    with open(file_path, 'rb') as f:
        raw = f.read()

    if len(raw) < 8:
        log(f"  [WARN] {target_name} 文件过小")
        return None

    total_size = struct.unpack_from('<I', raw, 0)[0]
    record_count = struct.unpack_from('<I', raw, 4)[0]

    # XOR 解密
    enc = raw[8:8 + total_size]
    xor_table = bytes([i ^ _TKT_XOR_KEY for i in range(256)])
    dec = enc.translate(xor_table)

    id_table_size = record_count * 4
    text_base = id_table_size * 2

    # 解析所有条目为 {id: text} 字典
    entries = {}  # {int_id: decoded_text}
    entry_order = []  # 保持原始顺序
    for i in range(record_count):
        entry_id = struct.unpack_from('<i', dec, i * 4)[0]
        text_offset = struct.unpack_from('<I', dec, id_table_size + i * 4)[0]
        abs_off = text_base + text_offset

        if abs_off >= len(dec):
            blob = b''
        else:
            end = abs_off
            while end < len(dec) and dec[end] != _TKT_ENTRY_TERMINATOR:
                end += 1
            blob = dec[abs_off:end]

        text = _tkt_decode_entry(blob)
        entries[entry_id] = text
        entry_order.append(entry_id)

    log(f"  合并 {target_name}: {len(entries)} 条文本, {len(mod_diffs)} 个 MOD 差异")

    # 按顺序应用每个 MOD 差异
    for mod, diff_data in mod_diffs:
        modified = diff_data.get("modified", {})
        appended = diff_data.get("appended", {})
        deleted = diff_data.get("deleted", [])

        # 应用修改
        for id_str, text in modified.items():
            eid = int(id_str)
            entries[eid] = text
            if eid not in entry_order:
                entry_order.append(eid)

        # 应用追加
        if isinstance(appended, dict):
            for id_str, text in appended.items():
                eid = int(id_str)
                entries[eid] = text
                if eid not in entry_order:
                    entry_order.append(eid)
        elif isinstance(appended, list):
            for text in appended:
                pass  # TKT 不应有 list 类型追加

        # 应用删除
        for id_str in deleted:
            eid = int(id_str)
            entries.pop(eid, None)
            if eid in entry_order:
                entry_order.remove(eid)

        log(f"    应用 MOD '{mod.name}': {len(modified)} 修改, "
            f"{len(appended) if isinstance(appended, dict) else 0} 追加, "
            f"{len(deleted)} 删除")

    # 重建二进制格式
    new_record_count = len(entry_order)
    text_blob = bytearray()
    id_table = bytearray()
    offset_table = bytearray()

    for eid in entry_order:
        text = entries.get(eid, '')
        lines = text.split('\n')
        entry_bytes = bytearray()
        for li, line in enumerate(lines):
            if li > 0:
                entry_bytes.append(_TKT_LINE_SEPARATOR)
            entry_bytes.extend(_tkt_encode_line(line))
        entry_bytes.append(_TKT_ENTRY_TERMINATOR)

        current_offset = len(text_blob)
        text_blob.extend(entry_bytes)
        id_table.extend(struct.pack('<i', eid))
        offset_table.extend(struct.pack('<I', current_offset))

    data = bytes(id_table) + bytes(offset_table) + bytes(text_blob)
    new_total_size = len(data)

    # XOR 加密
    encrypted = data.translate(xor_table)

    # 组装最终文件
    result = bytearray()
    result.extend(struct.pack('<I', new_total_size))
    result.extend(struct.pack('<I', new_record_count))
    result.extend(encrypted)
    return bytes(result)


# ═══════════════════════════════════════════════════════════════
# 4c. GRP/JVG 块级二进制差异合并
# ═══════════════════════════════════════════════════════════════

def _load_grp_sections(file_path: str) -> Optional[tuple]:
    """加载 GRP 文件及其 IDX, 返回 (sections_list, idx_path)"""
    if not os.path.isfile(file_path):
        return None

    with open(file_path, 'rb') as f:
        data = f.read()

    # 查找配套 IDX 文件
    idx_path = None
    for ext in ['.IDX', '.idx']:
        candidate = str(Path(file_path).with_suffix(ext))
        if os.path.exists(candidate):
            idx_path = candidate
            break

    if not idx_path or not os.path.isfile(idx_path):
        return None

    with open(idx_path, 'rb') as f:
        idx_data = f.read()

    if len(idx_data) < 8 or len(idx_data) % 4 != 0:
        return None

    offsets = [struct.unpack_from('<I', idx_data, i)[0]
               for i in range(0, len(idx_data), 4)]

    sections = []
    for i in range(len(offsets) - 1):
        start = offsets[i]
        end = offsets[i + 1]
        if start <= end <= len(data):
            sections.append(data[start:end])
        else:
            sections.append(b'')

    return sections, idx_path


def _save_grp_sections(sections: list, grp_path: str, idx_path: str):
    """将区段列表重建为 GRP + IDX 文件"""
    # 构建 IDX: 从 0 开始的偏移量序列
    offsets = [0]
    for sec in sections:
        offsets.append(offsets[-1] + len(sec))

    # 写入 IDX
    idx_data = b''.join(struct.pack('<I', off) for off in offsets)
    with open(idx_path, 'wb') as f:
        f.write(idx_data)

    # 写入 GRP (拼接所有区段)
    with open(grp_path, 'wb') as f:
        for sec in sections:
            f.write(sec)


def _merge_block_file(file_path: str, target_name: str,
                      mod_diffs: List[Tuple['ModInfo', dict]], log_func=None) -> Optional[str]:
    """合并 GRP 类块级二进制文件, 返回标记 (实际文件由此函数直接写入)

    注意: 此函数直接操作 GRP + IDX 两个文件, 不通过 merged.file_data 返回。
    返回 'direct_write' 标记表示已处理。
    """
    log = log_func or (lambda x: None)

    result = _load_grp_sections(file_path)
    if result is None:
        log(f"  [WARN] 无法加载 {target_name} 的区段结构 (需要配套 IDX 文件)")
        return None

    sections, idx_path = result
    log(f"  合并 {target_name}: {len(sections)} 个区段, {len(mod_diffs)} 个 MOD 差异")

    # 按顺序应用每个 MOD 的块差异
    for mod, diff_data in mod_diffs:
        modified_blocks = diff_data.get("modified", [])
        appended_blocks = diff_data.get("appended", [])
        deleted_indices = diff_data.get("deleted_indices", [])

        # 应用修改
        for entry in modified_blocks:
            idx = entry.get("index", -1)
            data_b64 = entry.get("data_b64", "")
            if 0 <= idx < len(sections) and data_b64:
                sections[idx] = base64.b64decode(data_b64)

        # 应用追加
        for entry in appended_blocks:
            idx = entry.get("index", -1)
            data_b64 = entry.get("data_b64", "")
            if data_b64:
                block_data = base64.b64decode(data_b64)
                # 扩展到指定索引
                while len(sections) <= idx:
                    sections.append(b'')
                sections[idx] = block_data

        # 处理删除 (将删除的区段置为空, 保持索引对齐)
        for idx in sorted(deleted_indices, reverse=True):
            if 0 <= idx < len(sections):
                sections[idx] = b''

        log(f"    应用 MOD '{mod.name}': {len(modified_blocks)} 修改, "
            f"{len(appended_blocks)} 追加, {len(deleted_indices)} 删除")

    # 直接写入 GRP + IDX
    _save_grp_sections(sections, file_path, idx_path)
    return "direct_write"


# ═══════════════════════════════════════════════════════════════
# 5. 写入合并后的文件
# ═══════════════════════════════════════════════════════════════

def apply_mod_data(merged: MergedData, game_dir: str, log_func=None):
    """将合并后的数据写入游戏目录（先备份原始文件）"""
    log = log_func or (lambda x: None)

    # 写入数据文件
    for target_name, data in merged.file_data.items():
        target_path = os.path.join(game_dir, target_name)
        orig_path = target_path + ".mod_orig"

        # 备份原始文件
        if os.path.isfile(target_path) and not os.path.isfile(orig_path):
            shutil.copy2(target_path, orig_path)
            merged.backed_up.append(target_path)
            log(f"  备份: {target_name} → {target_name}.mod_orig")

        # 写入合并数据
        with open(target_path, 'wb') as f:
            f.write(data)
        log(f"  写入: {target_name} ({len(data)} 字节)")

    # 处理资源文件替换
    for target_name, (mod_path, internal_path) in merged.resource_replacements.items():
        target_path = os.path.join(game_dir, target_name)
        orig_path = target_path + ".mod_orig"

        # 备份原始文件
        if os.path.isfile(target_path) and not os.path.isfile(orig_path):
            shutil.copy2(target_path, orig_path)
            merged.backed_up.append(target_path)
            log(f"  备份资源: {target_name} → {target_name}.mod_orig")

        # 从 ZIP 中提取资源文件
        try:
            with zipfile.ZipFile(mod_path, 'r') as zf:
                if internal_path in zf.namelist():
                    with zf.open(internal_path) as src:
                        with open(target_path, 'wb') as dst:
                            dst.write(src.read())
                    log(f"  替换资源: {target_name}")
        except Exception as e:
            log(f"  [ERROR] 替换资源 {target_name} 失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 6. 恢复原始文件
# ═══════════════════════════════════════════════════════════════

def restore_originals(game_dir: str, log_func=None):
    """恢复所有 .mod_orig 备份文件"""
    log = log_func or (lambda x: None)
    restored = 0

    for fname in os.listdir(game_dir):
        if fname.endswith('.mod_orig'):
            orig_path = os.path.join(game_dir, fname)
            target_name = fname[:-len('.mod_orig')]
            target_path = os.path.join(game_dir, target_name)
            try:
                shutil.copy2(orig_path, target_path)
                os.remove(orig_path)
                restored += 1
            except Exception as e:
                log(f"  [ERROR] 恢复 {target_name} 失败: {e}")

    if restored > 0:
        log(f"  已恢复 {restored} 个原始文件")
    return restored
