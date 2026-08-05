"""
.tkspatch 外置补丁加载器

文件格式: JSON, 扩展名 .tkspatch
每个文件定义一个完整的补丁 (含 cave 机器码), 可独立分发替换。

优先级规则:
  patches/ 目录下的 .tkspatch 文件 (按 id) 覆盖 tks_patches.json 中同 id 的补丁。
  若 patches/ 目录不存在或为空, 完全回退到 tks_patches.json (向后兼容)。

Cave 机器码字段:
  cave_code: 空格分隔的十六进制字符串 (与 pattern 格式一致)
  例: "50 51 0F BF 45 FA 66 85 C0 ..."
"""

import json
import os
from typing import Any, Dict, List, Optional

from .config_loader import PatchDef, PatchConfig, load_config

FORMAT_VERSION = 1

# 全局变量文件名 (位于 patches/ 目录)
VARIABLES_FILE = "_variables.tkspatch"


def _parse_hex_bytes(hex_str: str) -> Optional[bytes]:
    """解析空格分隔的十六进制字符串为 bytes。
    支持 ?? 占位 (转为 0x00, 通常不用于 cave_code)。
    """
    if not hex_str:
        return None
    try:
        tokens = hex_str.split()
        result = bytearray()
        for t in tokens:
            t = t.strip()
            if not t:
                continue
            if t == '??' or t == '**':
                result.append(0x00)
            else:
                result.append(int(t, 16))
        return bytes(result)
    except (ValueError, TypeError):
        return None


def _parse_maybe_hex(val):
    """解析可能是十六进制字符串或整数的值"""
    if isinstance(val, str):
        if val.lower().startswith("0x"):
            return int(val, 16)
        return int(val)
    return int(val)


def load_tkspatch_file(path: str, log_func=None) -> Optional[PatchDef]:
    """加载单个 .tkspatch 文件, 返回 PatchDef (含外置 cave 数据)。

    PatchDef 新增属性:
        _cave_code_bytes: Optional[bytes]  — 外置 cave 机器码 (若定义)
        _extra: dict                       — 额外类型特定字段
    """
    log = log_func or (lambda x: None)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        log(f"  [WARN] 解析 .tkspatch 失败: {path} — {e}")
        return None

    # 版本检查
    fmt_ver = raw.get("_format", 1)
    if fmt_ver > FORMAT_VERSION:
        log(f"  [WARN] .tkspatch 版本 {fmt_ver} > 支持版本 {FORMAT_VERSION}: {path}")
        return None

    d = PatchDef()
    d.type = raw.get("type", "")
    d.id = raw.get("id", "")
    d.name = raw.get("name", "")
    d.desc = raw.get("desc", "")
    d.optional = raw.get("optional", False)
    d.default_checked = raw.get("default_checked", True)
    d.profile_rules = dict(raw.get("profile_rules", {}))
    d.hook_conflict_action = raw.get("hook_conflict_action", "override")
    d.exclude_extra_sections = raw.get("exclude_extra_sections", True)

    # patch_bytes / patch_extra_section
    d.pattern = raw.get("pattern", "")
    d.expect_count = raw.get("expect_count", 0)
    if "replace" in raw:
        for rk, rv in raw["replace"].items():
            d.replace[rk] = int(rv, 16) if isinstance(rv, str) else int(rv)
    if "patterns" in raw:
        for pe in raw["patterns"]:
            prepl = {}
            if "replace" in pe:
                for rk, rv in pe["replace"].items():
                    prepl[rk] = int(rv, 16) if isinstance(rv, str) else int(rv)
            d.patterns.append({
                "pattern": pe.get("pattern", ""),
                "expect_count": pe.get("expect_count", 0),
                "replace": prepl,
            })

    # patch_imm32
    d.value_scan = raw.get("value_scan", False)
    d.expect_value = _parse_maybe_hex(raw.get("expect_value", 0))
    d.new_value_expr = str(raw.get("new_value", ""))
    d.value_offset = raw.get("value_offset", 0)

    # cave_hook
    d.hook_pattern = raw.get("hook_pattern", "")
    d.hook_size = raw.get("hook_size", 0)
    d.hook_expect_count = raw.get("hook_expect_count", 0)
    d.cave_template = raw.get("cave_template", "")
    d.cave_offset = raw.get("cave_offset", 0)
    d.fallback_rva = _parse_maybe_hex(raw.get("fallback_rva", 0))
    d.hook_verify_pattern = raw.get("hook_verify", "")

    # patch_warpc_addr
    # (original / field_range / new_base 作为 extra 保存)

    # patch_summon_table / 其他需要 json_file 的类型
    jf = raw.get("json_file", "")
    if jf and not os.path.isabs(jf):
        # 解析顺序: 1) 相对于 .tkspatch 文件目录  2) 上级目录 (launcher root)
        abs_path = os.path.abspath(path)
        patch_dir = os.path.dirname(abs_path)
        resolved = os.path.join(patch_dir, jf)
        if not os.path.isfile(resolved):
            parent_dir = os.path.dirname(patch_dir)
            if parent_dir and parent_dir != patch_dir:
                alt = os.path.join(parent_dir, jf)
                # 无论是否存在都使用上级目录路径 (configs/ 通常在 launcher root)
                resolved = alt
        jf = resolved
    d.json_file = jf
    d.data_rva = _parse_maybe_hex(raw.get("data_rva", 0))
    d.data_keys = list(raw.get("data_keys", []))
    d.code_addrs = list(raw.get("code_addrs", []))
    d.random_hook_pattern = raw.get("random_hook_pattern", "")
    d.random_hook_size = raw.get("random_hook_size", 0)
    d.random_hook_expect_count = raw.get("random_hook_expect_count", 0)
    d.random_cave_offset = raw.get("random_cave_offset", 0)
    d.random_table_offset = raw.get("random_table_offset", 0)
    d.random2_cave_offset = raw.get("random2_cave_offset", 0)
    d.random2_hooks = list(raw.get("random2_hooks", []))

    # ── 外置 cave 机器码 (核心新特性) ──
    cave_code_hex = raw.get("cave_code", "")
    cave_code_bytes = _parse_hex_bytes(cave_code_hex) if cave_code_hex else None
    d._cave_code_bytes = cave_code_bytes  # type: ignore

    # 额外字段 (类型特定, 原样保存)
    d._extra = {}  # type: ignore
    for key in ("_group", "_comment", "_说明", "_mod_note",
                "original", "field_range", "new_base",
                "cave_mask_offset", "summon_cave_code", "summon_cave2_code"):
        if key in raw:
            d._extra[key] = raw[key]  # type: ignore

    return d


def load_variables_from_dir(patches_dir: str, log_func=None) -> Dict[str, int]:
    """从 patches/_variables.tkspatch 读取全局变量 (唯一来源)。

    返回格式与 PatchConfig.variables 一致 (已解析为 int)。
    文件不存在或损坏时返回空 dict。
    """
    log = log_func or (lambda x: None)
    vpath = os.path.join(patches_dir, VARIABLES_FILE)
    if not os.path.isfile(vpath):
        log(f"  [WARN] 全局变量文件不存在: {vpath}")
        return {}
    try:
        with open(vpath, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 {VARIABLES_FILE} 失败: {e}")
        return {}

    vars_raw = raw.get("variables", {})
    if not isinstance(vars_raw, dict):
        log(f"  [WARN] {VARIABLES_FILE} 缺少 variables 段")
        return {}

    variables: Dict[str, int] = {}
    for k, v in vars_raw.items():
        try:
            if isinstance(v, dict):
                fbv = v.get("fallback", 0)
                if isinstance(fbv, str) and fbv.lower().startswith("0x"):
                    variables[k] = int(fbv, 16)
                else:
                    variables[k] = int(fbv)
            elif isinstance(v, str):
                if v.lower().startswith("0x"):
                    variables[k] = int(v, 16)
                else:
                    variables[k] = int(v)
            elif isinstance(v, bool):
                variables[k] = 1 if v else 0
            else:
                variables[k] = int(v)
        except (ValueError, TypeError):
            log(f"  [WARN] {VARIABLES_FILE} 变量 {k} 解析失败, 跳过")
    return variables


def load_config_merged(config_path: str, patches_dir: str,
                       log_func=None) -> Optional[PatchConfig]:
    """统一补丁配置加载入口 — 不依赖 tks_patches.json。

    加载顺序:
      1. 若 tks_patches.json 存在 → 加载为基础配置 (仅向后兼容, 不更新)
      2. 从 patches/_variables.tkspatch 读取全局变量 (覆盖 json 中的 variables)
      3. 加载 patches/*.tkspatch → 合并 (同 id 覆盖)

    返回 None 仅当 patches/ 目录不存在且 tks_patches.json 也不存在。
    """
    log = log_func or (lambda x: None)

    # 1. 基础配置: 优先 tks_patches.json (旧版兼容), 否则空配置
    config = None
    if os.path.isfile(config_path):
        config = load_config(config_path, log_func=log)
        if config is not None:
            log(f"  [config] 基础配置: {config_path}")
    if config is None:
        config = PatchConfig()

    # 2. 全局变量: 唯一来源 _variables.tkspatch
    ext_vars = load_variables_from_dir(patches_dir, log_func=log)
    if ext_vars:
        config.variables.update(ext_vars)
        log(f"  [config] 全局变量: {len(ext_vars)} 个 (来自 {VARIABLES_FILE})")

    # 3. 外置补丁合并
    ext_patches = load_tkspatch_dir(patches_dir, log_func=log)
    if ext_patches:
        config = merge_patches(config, ext_patches, log_func=log)

    return config


def load_tkspatch_dir(patches_dir: str, log_func=None) -> List[PatchDef]:
    """扫描目录加载所有 .tkspatch 文件, 按文件名排序确保确定性。"""
    log = log_func or (lambda x: None)
    if not os.path.isdir(patches_dir):
        return []

    results: List[PatchDef] = []
    files = sorted(f for f in os.listdir(patches_dir) if f.endswith('.tkspatch'))
    for fname in files:
        fpath = os.path.join(patches_dir, fname)
        defn = load_tkspatch_file(fpath, log_func=log)
        if defn is not None and defn.id:
            results.append(defn)
        elif defn is None:
            log(f"  [WARN] 跳过无效文件: {fname}")

    if results:
        log(f"  [tkspatch] 从 patches/ 加载 {len(results)} 个外置补丁")
    return results


def merge_patches(base_config: PatchConfig, external_patches: List[PatchDef],
                  log_func=None) -> PatchConfig:
    """将外置补丁合并到基础配置。

    规则:
      - 外置补丁 id 与基础配置重复 → 覆盖 (外置优先)
      - 外置补丁 id 不存在于基础配置 → 追加
      - 保持基础配置中的顺序 (覆盖时位置不变), 新增项追加到末尾
    """
    log = log_func or (lambda x: None)
    if not external_patches:
        return base_config

    ext_map = {p.id: p for p in external_patches}
    merged_ids = set()
    merged_patches: List[PatchDef] = []

    for defn in base_config.patches:
        if defn.id in ext_map:
            merged_patches.append(ext_map[defn.id])
            merged_ids.add(defn.id)
            log(f"  [tkspatch] 覆盖: {defn.id}")
        else:
            merged_patches.append(defn)

    # 追加新增的外置补丁
    for p in external_patches:
        if p.id not in merged_ids:
            merged_patches.append(p)
            merged_ids.add(p.id)
            log(f"  [tkspatch] 新增: {p.id}")

    base_config.patches = merged_patches
    return base_config


def get_external_cave_code(defn: PatchDef) -> Optional[bytes]:
    """从 PatchDef 获取外置 cave 机器码 (若存在)。

    用于 patch_engine.build_cave_template 的回退链:
      外置 cave_code > 内置 CAVE_* 模板
    """
    return getattr(defn, '_cave_code_bytes', None)
