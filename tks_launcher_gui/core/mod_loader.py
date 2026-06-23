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
from dataclasses import dataclass, field
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
