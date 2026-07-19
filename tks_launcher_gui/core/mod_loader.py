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
import base64
import json
import os
import re as _re
import shutil
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .lzss import lzss_compress, lzss_decompress

# GRP 图层差分编解码 (与编辑器共用同一实现, 保证字节一致)
try:
    from editor_utils import grp_codec as _grp_codec
except ImportError:  # 兼容 cli_launcher 只把自身目录加入 sys.path 的情况
    import sys as _sys
    _ai_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ai_root not in _sys.path:
        _sys.path.insert(0, _ai_root)
    try:
        from editor_utils import grp_codec as _grp_codec
    except ImportError:
        _grp_codec = None


# ═══════════════════════════════════════════════════════════════
# 允许通过 MOD 包携带的启动器配置文件白名单
# 其它配置文件 (如 font_config.json) 只从 configs/ 目录读取
# MOD 包中携带的配置文件优先级最高，覆盖 configs/ 目录同名文件
# ═══════════════════════════════════════════════════════════════
MOD_ALLOWED_CONFIGS = {"summon_table", "drop_probability"}


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
    load_order: int = 100
    dependencies: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    id_ranges: Dict[str, Dict[str, int]] = field(default_factory=dict)
    warpc_expand: int = 0
    components: List[Dict[str, str]] = field(default_factory=list)
    resources: List[Dict[str, str]] = field(default_factory=list)
    # 加载后的数据
    data_files: Dict[str, Any] = field(default_factory=dict)
    # MOD 携带的启动器配置文件 (白名单内的): {config_name: parsed_dict}
    # config_name 为不含扩展名的文件名 (如 "summon_table")
    config_files: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    # .tksmodpak 合集：内含的 .tksmod 文件名列表（仅 pak 条目有值）
    pak_contents: List[str] = field(default_factory=list)
    # 合集内展开的 .tksmod 原始 ZIP 数据（内存中，不落盘），用于资源提取
    _data_raw: Optional[bytes] = None
    # 预览图文件名（在 ZIP 内的文件名，如 "preview.png"）
    preview_image: str = ""


@dataclass
class Conflict:
    """冲突记录"""
    mod1_id: str = ""
    mod2_id: str = ""
    conflict_type: str = ""  # "id_range" | "field_overlap" | "resource" | "explicit" | "grp_layer_overlap" | "record_overlap" | "text_overlap"
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
    # MOD 携带的启动器配置覆盖 (白名单内): {config_name: parsed_dict}
    # 后加载的 MOD 覆盖先加载的; 传递给 patch_engine 优先于 configs/ 目录
    config_overrides: Dict[str, Any] = field(default_factory=dict)


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
        ext = os.path.splitext(fname)[1].lower()
        fpath = os.path.join(mods_dir, fname)
        if ext == '.tksmod':
            try:
                mod = _load_single_mod(fpath, log)
                if mod:
                    mods.append(mod)
                    log(f"  [OK] 加载 MOD: {mod.name} v{mod.version} ({fname})")
            except Exception as e:
                log(f"  [WARN] 加载 {fname} 失败: {e}")
        elif ext == '.tksmodpak':
            try:
                mod = _load_pak_mod_info(fpath, log)
                if mod:
                    mods.append(mod)
                    log(f"  [OK] 加载合集: {mod.name} ({fname}) [{len(mod.pak_contents)} 个模组]")
            except Exception as e:
                log(f"  [WARN] 加载合集 {fname} 失败: {e}")

    log(f"  共发现 {len(mods)} 个模组/合集")
    return mods


def _load_mod_config_files(zf: zipfile.ZipFile, log_func=None) -> Dict[str, Any]:
    """从 ZIP 中加载白名单内的启动器配置文件。

    扫描 ZIP 内 configs/*.json 路径，仅加载名称在 MOD_ALLOWED_CONFIGS 白名单内
    的配置文件 (summon_table, drop_probability)。其余配置文件忽略，以 configs/
    目录中的为准。

    Returns:
        {config_name: parsed_dict} 如 {"summon_table": {...}}
    """
    log = log_func or (lambda x: None)
    result: Dict[str, Any] = {}
    for name in zf.namelist():
        # 匹配 configs/xxx.json (不匹配目录条目)
        if not name.startswith("configs/") or not name.endswith(".json"):
            continue
        if name.endswith("/"):
            continue
        # 提取配置名 (不含扩展名)
        basename = os.path.basename(name)
        config_name = os.path.splitext(basename)[0]
        if config_name not in MOD_ALLOWED_CONFIGS:
            log(f"    跳过非白名单配置: {name} (仅 {sorted(MOD_ALLOWED_CONFIGS)} 允许)")
            continue
        try:
            content = zf.read(name).decode('utf-8')
            result[config_name] = json.loads(content)
            log(f"    加载 MOD 配置: {config_name}")
        except Exception as e:
            log(f"    [WARN] 解析配置 {name} 失败: {e}")
    return result


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
            load_order=mj.get("load_order", 100),
            dependencies=mj.get("dependencies", []),
            conflicts=mj.get("conflicts", []),
            id_ranges=mj.get("id_ranges", {}),
            warpc_expand=mj.get("warpc_expand", 0),
            components=mj.get("components", []),
            resources=mj.get("resources", []),
            preview_image=mj.get("preview_image", ""),
        )

        # 预加载数据文件
        for comp in mod.components:
            internal_path = comp.get("file", "")
            if internal_path in zf.namelist():
                content = zf.read(internal_path).decode('utf-8')
                mod.data_files[internal_path] = json.loads(content)

        # 预加载白名单内的启动器配置文件
        mod.config_files = _load_mod_config_files(zf, log_func=log)

        return mod


def _load_pak_mod_info(pak_path: str, log_func=None) -> Optional[ModInfo]:
    """从 .tksmodpak 文件中读取合集元数据，创建 ModInfo 条目。

    仅读取 mod.json 获取合集概览信息，不解析内含的 .tksmod 文件内容。
    pak_contents 记录内含的 .tksmod 文件名列表。
    """
    log = log_func or (lambda x: None)

    with zipfile.ZipFile(pak_path, 'r') as zf:
        if "mod.json" not in zf.namelist():
            log(f"    .tksmodpak 缺少 mod.json")
            return None

        mj_str = zf.read("mod.json").decode('utf-8')
        mj = json.loads(mj_str)

        # 收集内含的 .tksmod 文件名
        pak_contents = sorted(
            n for n in zf.namelist()
            if n.lower().endswith(".tksmod") and not n.endswith("/")
        )

        mod = ModInfo(
            path=pak_path,
            mod_id=mj.get("id", ""),
            name=mj.get("name", ""),
            version=mj.get("version", "1.0.0"),
            author=mj.get("author", ""),
            description=mj.get("description", ""),
            load_order=mj.get("load_order", 100),
            dependencies=mj.get("dependencies", []),
            conflicts=mj.get("conflicts", []),
            pak_contents=pak_contents,
            preview_image=mj.get("preview_image", ""),
        )
        return mod


def expand_pak_mods(pak_path: str, log_func=None) -> List[ModInfo]:
    """展开 .tksmodpak 合集，将内含的每个 .tksmod 在内存中解析为独立 ModInfo。

    不落盘，与普通 .tksmod 加载方式一致。原始 ZIP 数据保存在 _data_raw 中，
    供 apply_mod_data 提取资源时使用。

    pak 根目录下的 configs/*.json (白名单内) 会被读取并注入到所有子 MOD 的
    config_files 中，作为合集级配置覆盖。
    """
    import io
    log = log_func or (lambda x: None)
    result = []

    with zipfile.ZipFile(pak_path, 'r') as zf:
        # 读取 pak 根目录下的白名单配置文件 (合集级配置覆盖)
        pak_config_files = _load_mod_config_files(zf, log_func=log)

        mod_entries = sorted(
            n for n in zf.namelist()
            if n.lower().endswith(".tksmod") and not n.endswith("/")
        )
        for entry in mod_entries:
            raw_data = zf.read(entry)
            with zipfile.ZipFile(io.BytesIO(raw_data), 'r') as izf:
                if "mod.json" not in izf.namelist():
                    continue
                mj = json.loads(izf.read("mod.json").decode('utf-8'))
                if mj.get("format") != "TKSMOD":
                    continue

                mod = ModInfo(
                    path=pak_path,
                    mod_id=mj.get("id", ""),
                    name=mj.get("name", ""),
                    version=mj.get("version", "1.0.0"),
                    author=mj.get("author", ""),
                    description=mj.get("description", ""),
                    load_order=mj.get("load_order", 100),
                    dependencies=mj.get("dependencies", []),
                    conflicts=mj.get("conflicts", []),
                    id_ranges=mj.get("id_ranges", {}),
                    warpc_expand=mj.get("warpc_expand", 0),
                    components=mj.get("components", []),
                    resources=mj.get("resources", []),
                    _data_raw=raw_data,
                )

                # 预加载数据文件（内存中）
                for comp in mod.components:
                    internal_path = comp.get("file", "")
                    if internal_path in izf.namelist():
                        mod.data_files[internal_path] = json.loads(
                            izf.read(internal_path).decode('utf-8'))

                # 预加载白名单内的启动器配置文件 (子 MOD 内部的)
                mod.config_files = _load_mod_config_files(izf, log_func=log)
                # 合并 pak 根目录的合集级配置 (子 MOD 内部配置优先，pak 根目录补充)
                for cfg_name, cfg_data in pak_config_files.items():
                    if cfg_name not in mod.config_files:
                        mod.config_files[cfg_name] = cfg_data

                result.append(mod)

    return result


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

def _collect_grp_layer_offsets(mod: 'ModInfo') -> dict:
    """收集某 MOD 的 GRP 图层差分改动位置: {(target_lower, section, plane): set(offsets)}。"""
    result = {}
    for comp in mod.components:
        internal = comp.get("file", "")
        target = comp.get("target", "")
        d = mod.data_files.get(internal)
        if not isinstance(d, dict) or d.get("patch_type") != "grp_layer_diff":
            continue
        modified = d.get("modified", {})
        if not isinstance(modified, dict):
            continue
        for sidx, entry in modified.items():
            planes = entry.get("planes") if isinstance(entry, dict) else None
            if not planes:
                continue
            for plane, spans in planes.items():
                offs = result.setdefault((target.lower(), str(sidx), plane), set())
                for start, vals in spans:
                    for j in range(len(vals)):
                        offs.add(start + j)
    return result


def _collect_record_indices(mod: 'ModInfo') -> dict:
    """收集某 MOD 的定长记录类改动位置: {target_lower: {index: set(field_keys)}}。

    覆盖以 modified/appended 列表 + index 描述的定长记录差异
    (TKMat/TKDefUnit/WarPC/TKItem/TKSkill/TKKon/TKShop/WarWay/WarData 等)。
    不含块级(block_diff/grp_layer_diff)与文本(TKD/TKT)差异——它们各有专门检测。
    """
    result: dict = {}
    for comp in mod.components:
        internal = comp.get("file", "")
        target = comp.get("target", "")
        d = mod.data_files.get(internal)
        if not isinstance(d, dict):
            continue
        if d.get("patch_type") in ("block_diff", "grp_layer_diff"):
            continue
        # 定长记录差异的 modified 为 list; 文本差异为 dict, 在此排除
        if not isinstance(d.get("modified"), list):
            continue
        idx_map = result.setdefault(target.lower(), {})
        for group in ("modified", "appended"):
            for entry in d.get(group, []):
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                if idx is None:
                    continue
                fields = entry.get("fields", {})
                keys = set(fields.keys()) if isinstance(fields, dict) else set()
                idx_map.setdefault(idx, set()).update(keys)
    return result


def _collect_text_entry_ids(mod: 'ModInfo') -> dict:
    """收集某 MOD 的文本(TKD/TKT)改动条目 id: {target_lower: set(id_str)}。

    TKD.dat: DEFINE 块 id; TKT.dat: 文本条目 id。
    modified 为 dict 视为文本差异; appended 兼容 dict(TKT) 与 DEFINE 全文 list(TKD)。
    """
    result: dict = {}
    for comp in mod.components:
        internal = comp.get("file", "")
        target = comp.get("target", "")
        d = mod.data_files.get(internal)
        if not isinstance(d, dict):
            continue
        modified = d.get("modified")
        if not isinstance(modified, dict):
            continue
        ids = {str(k) for k in modified.keys()}
        appended = d.get("appended")
        if isinstance(appended, dict):
            ids.update(str(k) for k in appended.keys())
        elif isinstance(appended, list):
            for content in appended:
                for line in str(content).split('\n'):
                    stripped = line.strip().rstrip('\r')
                    if stripped.startswith('DEFINE'):
                        parts = stripped.split(None, 1)
                        if len(parts) > 1:
                            ids.add(parts[1])
                        break
        if ids:
            result.setdefault(target.lower(), set()).update(ids)
    return result


def detect_conflicts(mods: List[ModInfo], log_func=None) -> List[Conflict]:
    """检测 MOD 之间的冲突"""
    log = log_func or (lambda x: None)
    conflicts = []

    # 预计算每个 MOD 的 GRP 图层差分改动位置 (用于像素级重叠检测)
    layer_maps = [_collect_grp_layer_offsets(m) for m in mods]

    # 预计算每个 MOD 的定长记录改动索引 与 文本条目 id (用于槽位/条目重复检测)
    record_maps = [_collect_record_indices(m) for m in mods]
    text_maps = [_collect_text_entry_ids(m) for m in mods]

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

            # GRP 图层差分: 同区段同平面同像素重叠 → 冲突 (不同像素自动共存)
            lm1, lm2 = layer_maps[i], layer_maps[j]
            for key in set(lm1) & set(lm2):
                inter = lm1[key] & lm2[key]
                if inter:
                    tgt, sidx, plane = key
                    conflicts.append(Conflict(
                        mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                        conflict_type="grp_layer_overlap", target=tgt,
                        detail=f"{tgt} 区段#{sidx} {plane}层 {len(inter)} 个像素被 "
                               f"'{m1.name}' 与 '{m2.name}' 同时修改"))

            # 定长记录槽位重复: 两 MOD 改同一文件的同一记录索引 (如 TKMat 实体槽/TKDefUnit 槽位)
            rm1, rm2 = record_maps[i], record_maps[j]
            for tgt in set(rm1) & set(rm2):
                shared_idx = set(rm1[tgt]) & set(rm2[tgt])
                if not shared_idx:
                    continue
                field_overlap = [ix for ix in shared_idx if rm1[tgt][ix] & rm2[tgt][ix]]
                sample = sorted(shared_idx)[:12]
                detail = (f"{tgt} 记录槽位 {sample}"
                          f"{' …等' if len(shared_idx) > 12 else ''} 被 "
                          f"'{m1.name}' 与 '{m2.name}' 同时写入 (共 {len(shared_idx)} 处)")
                if field_overlap:
                    detail += f"; 其中 {len(field_overlap)} 处字段直接覆盖, 后加载者生效"
                conflicts.append(Conflict(
                    mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                    conflict_type="record_overlap", target=tgt,
                    detail=detail))

            # 文本条目重复: 两 MOD 改同一 TKD DEFINE 块 / TKT 文本条目
            tm1, tm2 = text_maps[i], text_maps[j]
            for tgt in set(tm1) & set(tm2):
                shared_ids = tm1[tgt] & tm2[tgt]
                if not shared_ids:
                    continue
                sample = sorted(shared_ids, key=lambda s: (len(s), s))[:12]
                conflicts.append(Conflict(
                    mod1_id=m1.mod_id, mod2_id=m2.mod_id,
                    conflict_type="text_overlap", target=tgt,
                    detail=f"{tgt} 条目/DEFINE {sample}"
                           f"{' …等' if len(shared_ids) > 12 else ''} 被 "
                           f"'{m1.name}' 与 '{m2.name}' 同时修改 (共 {len(shared_ids)} 处)"))

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
    # WarWay.dat: 32x32 地形网格, 每格 int8 (-1障碍/0通行/1-5区域), 100条, flat binary 无LZSS
    # field_count=1024 对应 f0..f1023 (逐格引用), 与 wardata_editor 导出格式一致
    "WarWay.dat":   {"rec_size": 1024, "field_type": "int8",  "field_count": 1024,"orig_count": 100,  "lzss": False},
}


# WarData.dat 字段布局表
# 与 DAT_FILE_INFO 不同: WarData.dat 的字段类型异构 (uint8/int8/uint16 混合),
# 无法用统一的 field_type + 字段索引 (f0/f1/...) 描述, 因此通过字段名引用,
# 每个字段独立指定偏移/类型/元素数。
# field_layout: {field_name: (offset, item_size, struct_fmt, item_count)}
#   - item_size 仅用于校验
#   - struct_fmt: struct 单元素格式 ('<B' uint8, '<b' int8, '<H' uint16)
# 字段布局严格依据 wardata_editor_v2.py 中 sub_42FDF8 的逆向结果
# (WarData.dat: 498 字节/条, 219 条, flat binary, 无 LZSS)
WARDATA_FIELD_LAYOUT = {
    "flags":             (0,   1,  '<B', 1),    # byte: sub_4307CC:200 &4=随机敌军; &2=失败条件
    "must_chars":        (2,   1,  '<B', 6),    # byte[6]: sub_4307CC:51 (+1编码; 0/255=空)
    "battle_name_id":    (30,  2,  '<H', 1),    # uint16: sub_43A8D8:39 → TKT
    "map_id":            (32,  2,  '<H', 1),    # uint16: sub_42FE70:16
    "enemy_ids":         (34,  2,  '<H', 18),   # uint16[18]: sub_4307CC:219 (WarPC索引)
    "enemy_lv":          (70,  1,  '<B', 18),   # byte[18]: sub_4307CC:260
    "enemy_power":       (88,  1,  '<B', 18),   # byte[18]: sub_4307CC:217 (0=普通, >=1=将领)
    "enemy_lv_range":    (106, 1,  '<b', 36),   # int8[36]: sub_4307CC:227 (18对X,Y)
    "enemy_xy":          (142, 1,  '<b', 36),   # int8[36]: sub_431428:94 (18对X,Y)
    "ally_xy":           (178, 1,  '<b', 12),   # int8[12]: sub_431428:74 (6对X,Y)
    "enemy_delay":       (190, 1,  '<B', 18),   # byte[18]: sub_4307CC:242
    "ally_facing":       (208, 1,  '<B', 6),    # byte[6]
    "trap_xy":           (214, 1,  '<b', 56),   # int8[56]: sub_431428:204 (28组坐标)
    "trap_pwr":          (270, 1,  '<B', 56),   # byte[56]: sub_431428:296 (28对min,max)
    "trea_sub":          (326, 2,  '<H', 10),   # uint16[10]: sub_431428:202 (TKItem ID)
    "trea_quant":        (346, 2,  '<H', 20),   # uint16[20]: sub_434510:36 (10对min,max)
    "trap_type":         (386, 2,  '<H', 28),   # uint16[28]: sub_431428:199 (1-6 陷阱类型)
    "enemy_flags":       (442, 2,  '<H', 18),   # uint16[18]: sub_4307CC:263 (bit0=精英 bit1=特殊)
    "lv_spread_lo":      (478, 1,  '<B', 1),    # byte: sub_430578:17
    "lv_spread_hi":      (480, 1,  '<B', 1),    # byte: sub_430578:18
    "battle_turn_limit": (482, 2,  '<H', 1),    # uint16: sub_43CA64:29
}

# WarData.dat 元信息 (与 DAT_FILE_INFO 并列, 但因字段异构而使用 field_layout)
STRUCTURED_FILE_INFO = {
    "WarData.dat": {
        "rec_size": 498,
        "lzss": False,
        "field_layout": WARDATA_FIELD_LAYOUT,
    },
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
                merged.resource_replacements[target] = (mod.path, res.get("file", ""), mod._data_raw)

        # WarPC 扩展需求
        if mod.warpc_expand > merged.warpc_expand_count:
            merged.warpc_expand_count = mod.warpc_expand

        # 合并 MOD 携带的启动器配置覆盖 (白名单内)
        # 后加载的 MOD 覆盖先加载的; MOD 包中的配置优先级最高
        for cfg_name, cfg_data in mod.config_files.items():
            merged.config_overrides[cfg_name] = cfg_data
            log(f"  MOD '{mod.name}' 提供配置覆盖: {cfg_name}")

    # 对每个目标文件进行合并
    for target, mod_diffs in targets.items():
        target_path = os.path.join(game_dir, target)
        if not os.path.isfile(target_path):
            log(f"  [WARN] 目标文件不存在: {target_path}")
            continue

        # 检测差异数据格式并分派到对应处理器
        first_diff_data = mod_diffs[0][1] if mod_diffs else {}
        patch_type = first_diff_data.get("patch_type", "")

        if patch_type in ("block_diff", "grp_layer_diff"):
            # GRP/JVG 块级二进制差异 / GRP 图层差分
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
            # 合并并直接写入 (按补丁类型分派)
            if patch_type == "grp_layer_diff":
                result = _merge_grp_layer_diff(target_path, target, mod_diffs, log)
            else:
                result = _merge_block_file(target_path, target, mod_diffs, log)
            if result == "direct_write":
                log(f"  写入: {target} (合并完成)")

        elif _is_text_diff(first_diff_data):
            # TKD.dat 文本脚本差异
            result = _merge_text_file(target_path, target, mod_diffs, log)
            if result is not None:
                merged.file_data[target] = result

        elif first_diff_data.get("field_type") == "structured":
            # WarData.dat 结构化记录差异 (字段名引用 + 异构字段类型)
            info = STRUCTURED_FILE_INFO.get(target)
            if info:
                result = _merge_structured_file(target_path, target, info, mod_diffs, log)
                if result is not None:
                    merged.file_data[target] = result
            else:
                log(f"  [WARN] 未知结构化文件类型: {target}")

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

    # 确定最大记录数（可能因追加/修改超出当前文件而增加）
    # 注意: 编辑器 (mat_editor) 导出 TKDefUnit 扩容记录时, 因其 _du_recs_to_full_fields
    # 按 DEFUNIT_REC_COUNT 补齐, diff 会把 5000+ 的新记录归类为 "modified" 而非 "appended"。
    # 若仅依据 appended 扩展, 这些记录会因 idx >= max_count 被跳过而丢失。
    # 故此处对 appended 与 modified 一并取最高索引来决定扩展后的大小。
    max_count = actual_count
    for mod, diff_data in mod_diffs:
        for _key in ("appended", "modified"):
            for entry in diff_data.get(_key, []):
                idx = entry.get("index", 0)
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
        elif field_type == "int8":
            # WarWay.dat 逐格 int8: f0..f1023 直接映射到 32x32 网格的每个字节
            if base_off + fi < len(buf):
                struct.pack_into('<b', buf, base_off + fi, int(value))


# ═══════════════════════════════════════════════════════════════
# 4a-2. WarData.dat 结构化记录差异合并
# ═══════════════════════════════════════════════════════════════

def _merge_structured_file(file_path: str, target_name: str, info: dict,
                           mod_diffs: List[Tuple[ModInfo, dict]],
                           log_func=None) -> Optional[bytes]:
    """合并 WarData.dat 结构化记录差异 (字段名引用 + 异构字段类型)。

    与 _merge_dat_file 的区别:
      - DAT_FILE_INFO 使用统一的 field_type (int16/int32/uint16) + 字段索引 f0/f1/...
      - WarData.dat 字段类型异构 (uint8/int8/uint16 混合), 通过 WARDATA_FIELD_LAYOUT
        指定每个字段的偏移、类型、元素数
    """
    log = log_func or (lambda x: None)
    rec_size = info["rec_size"]
    use_lzss = info.get("lzss", False)
    field_layout = info["field_layout"]

    # 加载原始数据
    with open(file_path, 'rb') as f:
        raw = f.read()
    if use_lzss:
        dec = lzss_decompress(raw)
    else:
        dec = raw

    actual_count = len(dec) // rec_size
    log(f"  合并 {target_name}: {actual_count} 条记录, {len(mod_diffs)} 个 MOD 差异")

    records = bytearray(dec)

    # 确定最大记录数 (可能因追加而增加)
    max_count = actual_count
    for mod, diff_data in mod_diffs:
        for app in diff_data.get("appended", []):
            idx = app.get("index", 0)
            if idx >= max_count:
                max_count = idx + 1

    # 需要扩展时填充零字节
    if max_count > actual_count:
        records.extend(b'\x00' * ((max_count - actual_count) * rec_size))

    # 按顺序应用每个 MOD 的差异
    for mod, diff_data in mod_diffs:
        for entry in diff_data.get("modified", []):
            idx = entry.get("index", -1)
            if idx < 0 or idx >= max_count:
                continue
            fields = entry.get("fields", {})
            _apply_structured_fields(records, idx, rec_size, field_layout, fields)

        for entry in diff_data.get("appended", []):
            idx = entry.get("index", -1)
            if idx < 0 or idx >= max_count:
                continue
            fields = entry.get("fields", {})
            _apply_structured_fields(records, idx, rec_size, field_layout, fields)

        log(f"    应用 MOD '{mod.name}': {len(diff_data.get('modified', []))} 修改, "
            f"{len(diff_data.get('appended', []))} 追加")

    result = bytes(records[:max_count * rec_size])

    if use_lzss:
        result = lzss_compress(result)

    return result


def _apply_structured_fields(buf: bytearray, index: int, rec_size: int,
                             field_layout: dict, fields: dict):
    """将结构化字段差异应用到记录缓冲区。

    field_layout: {field_name: (offset, item_size, struct_fmt, item_count)}
    fields: {field_name: scalar_or_list}
      - 标量字段 (item_count == 1): 直接 pack 单个值
      - 数组字段 (item_count > 1): 接受 list, 逐元素 pack
    """
    base_off = index * rec_size
    # struct_fmt -> (元素字节数, 无符号掩码)
    # 无符号类型用掩码截断, 有符号类型由 struct 自行检查范围
    _FMT_INFO = {'<B': (1, 0xFF), '<b': (1, None),
                 '<H': (2, 0xFFFF), '<h': (2, None),
                 '<I': (4, 0xFFFFFFFF), '<i': (4, None)}

    for field_name, value in fields.items():
        layout = field_layout.get(field_name)
        if layout is None:
            continue
        offset, _item_size, pack_fmt, item_count = layout
        abs_off = base_off + offset
        elem_size, mask = _FMT_INFO.get(pack_fmt, (1, None))

        values = value if (item_count > 1 and isinstance(value, list)) else [value]
        for i, v in enumerate(values):
            if i >= item_count:
                break
            elem_off = abs_off + i * elem_size
            if elem_off + elem_size > len(buf):
                break
            try:
                iv = int(v)
                if mask is not None:
                    iv &= mask
                struct.pack_into(pack_fmt, buf, elem_off, iv)
            except (struct.error, ValueError, TypeError):
                pass


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


def _load_jvg_blocks(file_path: str) -> Optional[list]:
    """加载 JVG 文件中每个 @JVM 块的原始字节数据。

    JVG 是自包含块格式, 不需要外部 IDX 文件。
    返回 [block0_bytes, block1_bytes, ...] 或 None
    """
    if not os.path.isfile(file_path):
        return None
    with open(file_path, 'rb') as f:
        data = f.read()
    if len(data) < 32 or data[:4] != b'@JVG':
        return None

    block_count = struct.unpack_from('<I', data, 8)[0]
    blocks = []
    off = 32  # 跳过 @JVG 文件头

    for _ in range(block_count):
        if off + 32 > len(data) or data[off:off+4] != b'@JVM':
            break
        sprite_count = struct.unpack_from('<I', data, off + 4)[0]
        data_size = struct.unpack_from('<I', data, off + 12)[0]
        # 块总大小 = 块头(32B) + 偏移表((sprite_count+1)*4) + 调色板(512B) + 数据(data_size)
        block_size = 32 + (sprite_count + 1) * 4 + 512 + data_size
        block_bytes = data[off:off + block_size]
        blocks.append(block_bytes)
        off += block_size

    return blocks


def _load_fixed_record_blocks(file_path: str, record_size: int) -> Optional[list]:
    """加载定长记录的平坦二进制文件为块列表。

    用于 TKAct.dat 等无头部、无压缩的固定记录文件。
    每条记录作为一个独立的 block。

    Args:
        file_path: 文件路径
        record_size: 每条记录的字节数 (如 TKAct.dat = 784)

    返回 [record0_bytes, record1_bytes, ...] 或 None
    """
    if not os.path.isfile(file_path):
        return None
    with open(file_path, 'rb') as f:
        data = f.read()
    if len(data) == 0 or len(data) % record_size != 0:
        return None

    count = len(data) // record_size
    blocks = []
    for i in range(count):
        off = i * record_size
        blocks.append(data[off:off + record_size])
    return blocks


def _save_fixed_record_blocks(blocks: list, file_path: str):
    """将定长记录块列表拼接写回文件（无头部、无压缩）。"""
    with open(file_path, 'wb') as f:
        for blk in blocks:
            f.write(blk)


def _save_jvg_blocks(blocks: list, file_path: str):
    """将修改后的 @JVM 块列表重建为 JVG 文件。"""
    total_frames = 0
    total_data_size = 0
    for blk_data in blocks:
        if len(blk_data) >= 32 and blk_data[:4] == b'@JVM':
            sc = struct.unpack_from('<I', blk_data, 4)[0]
            ds = struct.unpack_from('<I', blk_data, 12)[0]
            total_frames += sc
            total_data_size += ds

    # 构建 @JVG 文件头 (32 bytes)
    buf = bytearray()
    buf += b'@JVG'
    buf += struct.pack('<I', len(blocks))   # block_count
    buf += struct.pack('<I', len(blocks))   # block_count (重复)
    buf += struct.pack('<I', total_data_size)
    buf += struct.pack('<I', total_frames)
    buf += bytes(12)  # 保留字节填满 32B

    # 拼接所有块
    for blk_data in blocks:
        buf += blk_data

    with open(file_path, 'wb') as f:
        f.write(bytes(buf))


# 定长记录文件的块大小映射
_FIXED_RECORD_SIZES = {
    "act_entry": 784,   # TKAct.dat: 650 条 × 784 字节
}


def _merge_block_file(file_path: str, target_name: str,
                      mod_diffs: List[Tuple['ModInfo', dict]], log_func=None) -> Optional[str]:
    """合并块级二进制文件, 返回标记 (实际文件由此函数直接写入)

    根据 block_type 区分:
      - "jvm_block":   JVG 自包含格式, 通过 @JVM 块头解析
      - "act_entry":   定长记录格式 (TKAct.dat 等), 无头部无压缩
      - "grp_section": GRP 区段格式, 需要配套 IDX 文件

    返回 'direct_write' 标记表示已处理。
    """
    log = log_func or (lambda x: None)

    # 从第一个 MOD 差异中获取 block_type
    first_diff = mod_diffs[0][1] if mod_diffs else {}
    block_type = first_diff.get("block_type", "grp_section")

    if block_type == "jvm_block":
        # JVG 文件: 自包含格式, 不需要 IDX
        sections = _load_jvg_blocks(file_path)
        if sections is None:
            log(f"  [WARN] 无法加载 {target_name} 的 @JVM 块结构 (不是有效的 @JVG 文件)")
            return None
        log(f"  合并 {target_name}: {len(sections)} 个 @JVM 块, {len(mod_diffs)} 个 MOD 差异")

    elif block_type in _FIXED_RECORD_SIZES:
        # 定长记录文件: TKAct.dat 等, 无头部无 IDX
        rec_size = _FIXED_RECORD_SIZES[block_type]
        sections = _load_fixed_record_blocks(file_path, rec_size)
        if sections is None:
            log(f"  [WARN] 无法加载 {target_name} 的定长记录结构 (record_size={rec_size})")
            return None
        log(f"  合并 {target_name}: {len(sections)} 条记录 (×{rec_size}B), {len(mod_diffs)} 个 MOD 差异")

    else:
        # GRP 文件: 需要 IDX
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

    # 写入文件
    if block_type == "jvm_block":
        _save_jvg_blocks(sections, file_path)
    elif block_type in _FIXED_RECORD_SIZES:
        _save_fixed_record_blocks(sections, file_path)
    else:
        _save_grp_sections(sections, file_path, idx_path)
    return "direct_write"


def _read_sections_with_idx(grp_path: str, idx_path: str) -> Optional[list]:
    """按给定 GRP + IDX 路径读取区段原始字节列表。"""
    if not os.path.isfile(grp_path) or not os.path.isfile(idx_path):
        return None
    with open(grp_path, 'rb') as f:
        data = f.read()
    with open(idx_path, 'rb') as f:
        idx_data = f.read()
    if len(idx_data) < 8 or len(idx_data) % 4 != 0:
        return None
    offsets = [struct.unpack_from('<I', idx_data, i)[0]
               for i in range(0, len(idx_data), 4)]
    sections = []
    for i in range(len(offsets) - 1):
        start, end = offsets[i], offsets[i + 1]
        sections.append(data[start:end] if start <= end <= len(data) else b'')
    return sections


def _merge_grp_layer_diff(file_path: str, target_name: str,
                          mod_diffs: List[Tuple['ModInfo', dict]],
                          log_func=None) -> Optional[str]:
    """合并 GRP 图层差分 (grp_layer_diff)。

    从纯净基准解码 A/L1/L2 三平面, 逐 MOD (load_order 升序) 叠加差分,
    只重压缩被改动的平面组 (未变平面复用原始压缩块), 再回写 GRP+IDX。
    不同像素自动共存; 同一像素按 load_order 取胜并告警。
    返回 'direct_write' 标记表示已处理。
    """
    log = log_func or (lambda x: None)
    if _grp_codec is None:
        log(f"  [WARN] grp_codec 不可用, 跳过 {target_name} 图层差分合并")
        return None

    # 定位可写 IDX (输出用)
    live_idx = None
    for ext in ['.IDX', '.idx']:
        c = str(Path(file_path).with_suffix(ext))
        if os.path.exists(c):
            live_idx = c
            break
    if not live_idx:
        log(f"  [WARN] {target_name} 缺少配套 IDX 文件, 无法图层合并")
        return None

    # 基准区段: 优先纯净备份 .mod_orig, 否则当前文件
    base_grp = file_path + ".mod_orig"
    base_idx = live_idx + ".mod_orig"
    if os.path.isfile(base_grp) and os.path.isfile(base_idx):
        base_sections = _read_sections_with_idx(base_grp, base_idx)
    else:
        base_sections = _read_sections_with_idx(file_path, live_idx)
    if base_sections is None:
        log(f"  [WARN] 无法加载 {target_name} 基准区段")
        return None

    log(f"  合并 {target_name}: {len(base_sections)} 个区段 (图层差分), "
        f"{len(mod_diffs)} 个 MOD 差异")

    sections = list(base_sections)
    decoded = {}   # sidx -> {'A','L1','L2','meta','touched'}
    writes = {}    # (sidx, plane, off) -> value
    n_conflict = 0

    # 预扫描: 统计每个区段被改动的平面, 用于跳过不必要的主图 LZSS 解压
    section_planes = {}
    for _mod, _diff in mod_diffs:
        _m = _diff.get("modified", {})
        if not isinstance(_m, dict):
            continue
        for _sidx_str, _entry in _m.items():
            _pl = _entry.get("planes") if isinstance(_entry, dict) else None
            if not _pl:
                continue
            try:
                _si = int(_sidx_str)
            except (ValueError, TypeError):
                continue
            section_planes.setdefault(_si, set()).update(_pl.keys())

    for mod, diff in mod_diffs:
        modified = diff.get("modified", {})
        # 兼容: 若混入旧 block_diff (modified 为 list), 按整段替换处理
        if isinstance(modified, list):
            for e in modified:
                idx = e.get("index", -1)
                b = e.get("data_b64", "")
                if 0 <= idx < len(sections) and b:
                    sections[idx] = base64.b64decode(b)
        else:
            for sidx_str, entry in modified.items():
                try:
                    sidx = int(sidx_str)
                except (ValueError, TypeError):
                    continue
                if 'planes' in entry:
                    if not (0 <= sidx < len(base_sections)):
                        continue
                    if sidx not in decoded:
                        need_a = 'A' in section_planes.get(sidx, ())
                        dec = _grp_codec.decode_section(base_sections[sidx], need_a=need_a)
                        if dec is None:
                            log(f"    [WARN] 区段 #{sidx} 无法解码, 跳过图层差分")
                            continue
                        decoded[sidx] = {
                            'A': bytearray(dec['A']) if dec['A'] is not None else None,
                            'L1': bytearray(dec['L1']),
                            'L2': bytearray(dec['L2']) if dec['L2'] is not None else None,
                            'meta': dec, 'touched': set(),
                        }
                    d = decoded[sidx]
                    for plane, spans in entry['planes'].items():
                        if plane == 'L2' and d['L2'] is None:
                            d['L2'] = bytearray(d['meta']['total_px'])
                            d['meta']['has_layer2'] = True
                        buf = d.get(plane)
                        if buf is None:
                            continue
                        for start, vals in spans:
                            for j, v in enumerate(vals):
                                off = start + j
                                nv = v & 0xFF
                                key = (sidx, plane, off)
                                if key in writes and writes[key] != nv:
                                    n_conflict += 1
                                writes[key] = nv
                                if 0 <= off < len(buf):
                                    buf[off] = nv
                        d['touched'].add('A' if plane == 'A' else 'B')
                elif 'data_b64' in entry:
                    if 0 <= sidx < len(sections):
                        sections[sidx] = base64.b64decode(entry['data_b64'])

        # 追加 / 删除 (与块级语义一致)
        _mod_blobs = None
        for e in diff.get("appended", []):
            idx = e.get("index", -1)
            raw = None
            if e.get("bin"):
                if _mod_blobs is None:
                    _src = getattr(mod, '_data_raw', None) or getattr(mod, 'path', None)
                    _mod_blobs = _grp_codec.read_blob_members(_src) if _src else {}
                raw = _mod_blobs.get(e["bin"])
            elif e.get("data_b64"):
                raw = base64.b64decode(e["data_b64"])
            if raw is not None and idx >= 0:
                while len(sections) <= idx:
                    sections.append(b'')
                sections[idx] = raw
        for idx in sorted(diff.get("deleted_indices", []), reverse=True):
            if 0 <= idx < len(sections):
                sections[idx] = b''

    # 重编码被改动的区段 (只重压缩变化的平面组)
    for sidx, d in decoded.items():
        meta = d['meta']
        touched = d['touched']
        reuse_fa = None if 'A' in touched else meta['fa_bytes']
        reuse_fb = None if 'B' in touched else meta['fb_bytes']
        try:
            sections[sidx] = _grp_codec.encode_section(
                meta['width'], meta['height'],
                bytes(d['A']) if d['A'] is not None else None, bytes(d['L1']),
                bytes(d['L2']) if d['L2'] is not None else None,
                meta['has_layer2'], reuse_fa=reuse_fa, reuse_fb=reuse_fb)
        except Exception as ex:
            log(f"    [WARN] 区段 #{sidx} 重编码失败: {ex}")

    if n_conflict:
        log(f"    [冲突] {n_conflict} 个像素被多个 MOD 同时修改, 已按 load_order 取胜")

    _save_grp_sections(sections, file_path, live_idx)
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
    import io as _io
    for target_name, (mod_path, internal_path, raw_data) in merged.resource_replacements.items():
        target_path = os.path.join(game_dir, target_name)
        orig_path = target_path + ".mod_orig"

        # 确保目标父目录存在 (支持子目录资源, 如 Sound/xxxx.mp3)
        parent_dir = os.path.dirname(target_path)
        if parent_dir and not os.path.isdir(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        existed = os.path.isfile(target_path)
        # 原文件存在: 备份为 .mod_orig (供游戏退出后恢复)
        if existed and not os.path.isfile(orig_path):
            shutil.copy2(target_path, orig_path)
            merged.backed_up.append(target_path)
            log(f"  备份资源: {target_name} → {target_name}.mod_orig")
        elif not existed:
            # 新增文件 (原游戏无此文件): 留下 .mod_new 标记, 游戏退出后删除
            try:
                with open(target_path + ".mod_new", 'w'):
                    pass
            except Exception:
                pass

        # 从 ZIP 中提取资源文件（支持内存数据或磁盘文件）
        try:
            if raw_data:
                zf = zipfile.ZipFile(_io.BytesIO(raw_data), 'r')
            else:
                zf = zipfile.ZipFile(mod_path, 'r')
            with zf:
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
    """恢复所有 .mod_orig 备份文件, 并清理 MOD 新增的文件 (.mod_new 标记)。

    递归遍历 game_dir (含子目录, 如 Sound/), 以支持子目录资源替换:
      - <file>.mod_orig : 覆盖类备份 → 还原原始文件并删除备份
      - <file>.mod_new  : 新增类标记 → 删除对应的新增文件并删除标记
    最后清理因新增而产生的空目录 (不会删除 game_dir 本身)。
    """
    log = log_func or (lambda x: None)
    restored = 0
    removed = 0

    orig_backups: List[str] = []
    new_markers: List[str] = []
    for root, _dirs, files in os.walk(game_dir):
        for fname in files:
            if fname.endswith('.mod_orig'):
                orig_backups.append(os.path.join(root, fname))
            elif fname.endswith('.mod_new'):
                new_markers.append(os.path.join(root, fname))

    # 还原被覆盖的原始文件
    for orig_path in orig_backups:
        target_path = orig_path[:-len('.mod_orig')]
        try:
            shutil.copy2(orig_path, target_path)
            os.remove(orig_path)
            restored += 1
        except Exception as e:
            log(f"  [ERROR] 恢复 {os.path.relpath(target_path, game_dir)} 失败: {e}")

    # 删除 MOD 新增的文件 (原游戏不存在的)
    empty_dir_candidates: set = set()
    for marker in new_markers:
        target_path = marker[:-len('.mod_new')]
        try:
            if os.path.isfile(target_path):
                os.remove(target_path)
                removed += 1
            os.remove(marker)
            empty_dir_candidates.add(os.path.dirname(target_path))
        except Exception as e:
            log(f"  [ERROR] 清理新增文件 {os.path.relpath(target_path, game_dir)} 失败: {e}")

    # 清理新增文件残留的空目录 (从深到浅, 保留 game_dir 本身)
    game_dir_abs = os.path.abspath(game_dir)
    for d in sorted(empty_dir_candidates, key=lambda p: p.count(os.sep), reverse=True):
        try:
            if (os.path.abspath(d) != game_dir_abs and os.path.isdir(d)
                    and not os.listdir(d)):
                os.rmdir(d)
        except Exception:
            pass

    if restored > 0:
        log(f"  已恢复 {restored} 个原始文件")
    if removed > 0:
        log(f"  已清理 {removed} 个新增文件")
    return restored
