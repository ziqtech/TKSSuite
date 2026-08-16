"""
.tkspatch 外置补丁加载器

文件格式: ZIP 容器, 扩展名 .tkspatch (旧版散装 JSON 兼容)
每个文件定义一个完整的补丁 (含 cave 机器码), 可独立分发替换。

新版 ZIP 格式 (类似 .tksmod):
  patch.json  — 补丁清单 (原散装 JSON 的全部字段)
  script.py   — type=script 时内嵌的外部脚本源码

旧版散装 JSON 仍可加载, 用于向后兼容。

优先级规则:
  patches/ 目录下的 .tkspatch 文件 (按 id) 覆盖 tks_patches.json 中同 id 的补丁。
  若 patches/ 目录不存在或为空, 完全回退到 tks_patches.json (向后兼容)。

Cave 机器码字段:
  cave_code: 空格分隔的十六进制字符串 (与 pattern 格式一致)
  例: "50 51 0F BF 45 FA 66 85 C0 ..."

外部脚本字段:
  script_file: 散装 JSON 指向 patches/_scripts 下的 .py; ZIP 型直接内嵌为 script.py

Cave hook 定位:
  hook_offset: hook 点相对 hook_pattern 起点的字节偏移 (默认 0)
"""

import json
import os
import zipfile
from typing import Any, Dict, List, Optional

from .config_loader import PatchDef, PatchConfig, load_config, resolve_config_path

FORMAT_VERSION = 1

# 旧版全局变量文件名，仅用于兼容迁移前的发行目录。
VARIABLES_FILE = "_variables.tkspatch"
GLOBAL_VARIABLES_ID = "global_variables"
GLOBAL_VARIABLES_TYPE = "global_variables"


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


def _parse_replace_int(val):
    """替换字典中的值: 字符串按十六进制解析, 整数原样。"""
    if isinstance(val, str):
        # 旧 .tkspatch 中 replace 值约定为十六进制字符串
        return int(val, 16)
    return int(val)


# Phase 12: 轻量级 .tkspatch JSON Schema 校验
# 不引入 jsonschema 依赖, 直接定义字段白名单 + 类型检查。
# 校验失败 → 记录 [WARN] 日志 + 返回 None (与 parse_patch_dict 失败行为一致)

_TKSPATCH_SCHEMA = {
    "required": ["type", "id"],
    "optional": [
        "name", "desc", "optional", "default_checked",
        # 第三方 MOD 兼容
        "profile_rules", "hook_conflict_action", "exclude_extra_sections", "fallback_rva",
        # patch_bytes / patch_extra_section
        "pattern", "replace", "expect_count", "patterns",
        # patch_imm32
        "value_scan", "expect_value", "new_value", "value_offset",
        # cave_hook
        "hook_pattern", "hook_size", "hook_offset", "hook_expect_count",
        "cave_template", "cave_offset", "hook_verify",
        # patch_summon_table
        "json_file", "script_file", "script_source",
        "data_rva", "data_keys", "code_addrs",
        "random_hook_pattern", "random_hook_size", "random_hook_expect_count",
        "random_cave_offset", "random_table_offset",
        "random2_cave_offset", "random2_hooks",
        # Phase 6
        "autolayout_cave",
        # cave_code
        "cave_code",
        # _extra
        "_group", "_comment", "_说明", "_mod_note",
        "original", "field_range", "new_base",
        "cave_mask_offset", "summon_cave_code", "summon_cave2_code",
        # 全局变量补丁
        "variables",
        # 版本
        "_format", "format", "format_version",
    ],
    "types": {
        "type": str,
        "id": str,
        "name": str,
        "desc": str,
        "optional": bool,
        "default_checked": bool,
        "profile_rules": dict,
        "hook_conflict_action": str,
        "exclude_extra_sections": bool,
        "fallback_rva": (int, str),
        "pattern": str,
        "replace": dict,
        "expect_count": int,
        "patterns": list,
        "value_scan": bool,
        "expect_value": (int, str),
        "new_value": (int, str),
        "value_offset": int,
        "hook_pattern": str,
        "hook_size": int,
        "hook_offset": int,
        "hook_expect_count": int,
        "cave_template": str,
        "cave_offset": int,
        "hook_verify": str,
        "json_file": str,
        "script_file": str,
        "script_source": str,
        "data_rva": (int, str),
        "data_keys": list,
        "code_addrs": list,
        "random_hook_pattern": str,
        "random_hook_size": int,
        "random_hook_expect_count": int,
        "random_cave_offset": int,
        "random_table_offset": int,
        "random2_cave_offset": int,
        "random2_hooks": list,
        "autolayout_cave": bool,
        "cave_code": str,
        "_format": int,
        "format": str,
        "format_version": int,
        "variables": dict,
    },
    "valid_hook_conflict_actions": {"override", "skip"},
}


def validate_tkspatch_dict(raw: dict, source_path: str = "",
                           log_func=None) -> List[str]:
    """Phase 12: 校验 .tkspatch JSON 字段。

    Args:
        raw:         已解析的 JSON dict
        source_path: 来源路径 (用于日志)
        log_func:    日志回调

    Returns:
        List[str] - 错误列表 (空列表表示通过)。
        调用方决定如何处理 (日志警告 / 返回 None / 抛异常)。
    """
    log = log_func or (lambda x: None)
    errors: List[str] = []

    if not isinstance(raw, dict):
        errors.append(f"根 JSON 不是 object, 得到 {type(raw).__name__}")
        return errors

    # 1. 必填字段
    for k in _TKSPATCH_SCHEMA["required"]:
        if k not in raw:
            errors.append(f"缺少必填字段: {k!r}")
        elif not isinstance(raw[k], str) or not raw[k]:
            errors.append(f"必填字段 {k!r} 必须是非空字符串, 得到 {raw[k]!r}")

    # 2. 未知字段警告 (不视为错误, 仅提醒)
    allowed = set(_TKSPATCH_SCHEMA["required"]) | set(_TKSPATCH_SCHEMA["optional"])
    unknown = set(raw.keys()) - allowed
    if unknown:
        log(f"  [WARN] {source_path}: 未知字段 {sorted(unknown)} (将忽略)")

    # 3. 类型检查 (有字段时)
    types_map = _TKSPATCH_SCHEMA["types"]
    for k, expected_type in types_map.items():
        if k not in raw:
            continue
        val = raw[k]
        if not isinstance(val, expected_type):
            type_name = (expected_type.__name__
                         if isinstance(expected_type, type)
                         else '/'.join(t.__name__ for t in expected_type))
            errors.append(
                f"字段 {k!r}: 期望 {type_name}, 得到 {type(val).__name__} "
                f"= {val!r}"
            )

    # 4. 枚举字段
    if "hook_conflict_action" in raw:
        if raw["hook_conflict_action"] not in _TKSPATCH_SCHEMA["valid_hook_conflict_actions"]:
            errors.append(
                f"hook_conflict_action 必须是 {_TKSPATCH_SCHEMA['valid_hook_conflict_actions']}, "
                f"得到 {raw['hook_conflict_action']!r}"
            )

    # 5. range 检查 (int 字段)
    for k in ("hook_size", "hook_offset", "hook_expect_count", "expect_count",
              "random_hook_size", "random_hook_expect_count", "cave_offset",
              "random_cave_offset", "random_table_offset", "random2_cave_offset",
              "value_offset", "fallback_rva", "data_rva"):
        if k in raw and isinstance(raw[k], int) and raw[k] < 0:
            errors.append(f"字段 {k!r} 不能为负, 得到 {raw[k]}")

    # 6. cave_code 十六进制字符串合法性
    if "cave_code" in raw:
        cc = raw["cave_code"]
        if isinstance(cc, str) and cc:
            tokens = cc.split()
            for t in tokens:
                t = t.strip()
                if not t or t in ('??', '**'):
                    continue
                try:
                    int(t, 16)
                except ValueError:
                    errors.append(f"cave_code 含非法十六进制 token: {t!r}")
                    break

    # 7. replace 字典值类型
    if "replace" in raw:
        for rk, rv in raw["replace"].items():
            if not isinstance(rv, (int, str)):
                errors.append(
                    f"replace[{rk!r}] 必须是 int 或 str, 得到 {type(rv).__name__}"
                )

    # 报告
    for e in errors:
        log(f"  [SCHEMA-ERR] {source_path}: {e}")

    return errors


# Phase 8: 统一字段映射 — 供 .tkspatch (ZIP/JSON) 与 tks_patches.json 共用
# 不同之处仅 script_file 路径解析策略 (tkspatch 用相对 .tkspatch 目录, config 用多级回退)
# json_file 与 fallback_rva 字段两者都用 resolve_config_path
def parse_patch_dict(raw: dict, source_path: str,
                     script_resolve_mode: str = "tkspatch_dir") -> PatchDef:
    """统一字段映射, 供 .tkspatch ZIP/JSON 和 tks_patches.json 共用。

    Args:
        raw:                   已解析的 JSON dict
        source_path:           配置文件路径 (用于解析 json_file/script_file 相对路径)
        script_resolve_mode:   "tkspatch_dir" — script_file 相对 .tkspatch 所在目录
                               "config_path"  — script_file 经 resolve_config_path 多级回退

    Returns:
        PatchDef 实例。raw 非 dict 时返回空的 PatchDef (避免崩溃)。
        """
    d = PatchDef()
    if not isinstance(raw, dict):
        return d
    d.type = raw.get("type", "")
    d.id = raw.get("id", "")
    d.name = raw.get("name", "")
    d.desc = raw.get("desc", "")
    d.optional = raw.get("optional", False)
    d.default_checked = raw.get("default_checked", True)

    # 第三方 MOD 兼容字段
    d.profile_rules = dict(raw.get("profile_rules", {}))
    d.hook_conflict_action = raw.get("hook_conflict_action", "override")
    d.exclude_extra_sections = raw.get("exclude_extra_sections", True)
    d.fallback_rva = _parse_maybe_hex(raw.get("fallback_rva", 0))

    # patch_bytes / patch_extra_section
    d.pattern = raw.get("pattern", "")
    d.expect_count = raw.get("expect_count", 0)
    if "replace" in raw:
        for rk, rv in raw["replace"].items():
            d.replace[rk] = _parse_replace_int(rv)
    if "patterns" in raw:
        for pe in raw["patterns"]:
            prepl = {}
            if "replace" in pe:
                for rk, rv in pe["replace"].items():
                    prepl[rk] = _parse_replace_int(rv)
            entry = {
                "pattern": pe.get("pattern", ""),
                "expect_count": pe.get("expect_count", 0),
                "replace": prepl,
            }
            if "value_offset" in pe:
                entry["value_offset"] = int(pe["value_offset"])
            if "expect_value" in pe:
                entry["expect_value"] = _parse_maybe_hex(pe["expect_value"])
            d.patterns.append(entry)

    # patch_imm32
    d.value_scan = raw.get("value_scan", False)
    d.expect_value = _parse_maybe_hex(raw.get("expect_value", 0))
    d.new_value_expr = str(raw.get("new_value", ""))
    d.value_offset = raw.get("value_offset", 0)

    # cave_hook
    d.hook_pattern = raw.get("hook_pattern", "")
    d.hook_size = raw.get("hook_size", 0)
    d.hook_offset = raw.get("hook_offset", 0)
    d.hook_expect_count = raw.get("hook_expect_count", 0)
    d.cave_template = raw.get("cave_template", "")
    d.cave_offset = raw.get("cave_offset", 0)
    d.hook_verify_pattern = raw.get("hook_verify", "")

    # patch_summon_table / 其他需要 json_file 的类型
    jf = raw.get("json_file", "")
    if jf and not os.path.isabs(jf):
        jf = resolve_config_path(source_path, jf)
    d.json_file = jf

    # 外置脚本补丁 (type=script)
    sf = raw.get("script_file", "")
    if sf and not os.path.isabs(sf):
        if script_resolve_mode == "tkspatch_dir":
            # .tkspatch: 相对 .tkspatch 所在目录
            sf = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(source_path)), sf))
        else:
            # tks_patches.json: 多级回退 (启动器根目录、上级目录)
            sf = resolve_config_path(source_path, sf)
    d.script_path = sf
    d.script_source = raw.get("script_source", "")

    # patch_summon_table 多随机 cave 注入字段
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

    # Phase 6: autolayout_cave (默认 True, 新模式; False = 沿用硬编码)
    d.autolayout_cave = raw.get("autolayout_cave", True)

    # ── 外置 cave 机器码 (核心新特性) ──
    cave_code_hex = raw.get("cave_code", "")
    cave_code_bytes = _parse_hex_bytes(cave_code_hex) if cave_code_hex else None
    d._cave_code_bytes = cave_code_bytes  # type: ignore

    # 额外字段 (类型特定, 原样保存)
    d._extra = {}  # type: ignore
    for key in ("_group", "_comment", "_说明", "_mod_note",
                "original", "field_range", "new_base",
                "cave_mask_offset", "summon_cave_code", "summon_cave2_code",
                "variables"):
        if key in raw:
            d._extra[key] = raw[key]  # type: ignore

    return d


def load_tkspatch_file(path: str, log_func=None) -> Optional[PatchDef]:
    """加载单个 .tkspatch (ZIP 或旧版 JSON), 返回 PatchDef。

    PatchDef 新增属性:
        _cave_code_bytes: Optional[bytes]  — 外置 cave 机器码 (若定义)
        _extra: dict                       — 额外类型特定字段
        script_source: str                 — ZIP 型 .tkspatch 内嵌脚本源码
    """
    log = log_func or (lambda x: None)
    if zipfile.is_zipfile(path):
        return _load_tkspatch_zip(path, log_func=log)
    return _load_tkspatch_json(path, log_func=log)


def _load_tkspatch_json(path: str, log_func=None,
                        raw: Optional[Dict[str, Any]] = None) -> Optional[PatchDef]:
    """加载旧版散装 JSON .tkspatch; raw 存在时复用解析逻辑。

    Phase 8: 委托给 parse_patch_dict, 统一字段映射。
    Phase 12: 先做 JSON Schema 校验, 失败则跳过 (返回 None)。
    """
    log = log_func or (lambda x: None)
    if raw is None:
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

    # Phase 12: JSON Schema 校验
    errors = validate_tkspatch_dict(raw, source_path=path, log_func=log)
    if errors:
        log(f"  [SCHEMA-FAIL] {path}: {len(errors)} 个字段错误, 跳过该补丁")
        return None

    return parse_patch_dict(raw, path, script_resolve_mode="tkspatch_dir")


def _load_tkspatch_zip(path: str, log_func=None) -> Optional[PatchDef]:
    """加载 ZIP 型 .tkspatch: patch.json + 可选 script.py。"""
    log = log_func or (lambda x: None)
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            names = set(zf.namelist())
            if "patch.json" not in names:
                log(f"  [WARN] .tkspatch ZIP 缺少 patch.json: {path}")
                return None
            raw = json.loads(zf.read("patch.json").decode('utf-8'))
            d = _load_tkspatch_json(path, log_func=log, raw=raw)
            if d is None:
                return None
            if d.type == "script":
                script_name = (raw.get("script_file") or "script.py").replace("\\", "/")
                script_name = script_name.lstrip("./")
                if script_name not in names:
                    script_name = "script.py"
                if script_name not in names:
                    log(f"  [WARN] .tkspatch ZIP 缺少 script.py: {path}")
                    return None
                d.script_source = zf.read(script_name).decode('utf-8')
                d.script_path = ""
            return d
    except Exception as e:
        log(f"  [WARN] 解析 .tkspatch ZIP 失败: {path} — {e}")
        return None


def _parse_variables(raw: Any, source_label: str, log_func=None) -> Dict[str, int]:
    """将全局变量清单解析为运行时整数值。"""
    log = log_func or (lambda x: None)
    vars_raw = raw.get("variables", {}) if isinstance(raw, dict) else {}
    if not isinstance(vars_raw, dict):
        log(f"  [WARN] {source_label} 缺少 variables 段")
        return {}

    variables: Dict[str, int] = {}
    for key, value in vars_raw.items():
        try:
            if isinstance(value, dict):
                value = value.get("fallback", 0)
            if isinstance(value, str):
                variables[key] = int(value, 16) if value.lower().startswith("0x") else int(value)
            elif isinstance(value, bool):
                variables[key] = 1 if value else 0
            else:
                variables[key] = int(value)
        except (ValueError, TypeError):
            log(f"  [WARN] {source_label} 变量 {key} 解析失败, 跳过")
    return variables


def load_variables_from_dir(patches_dir: str, log_func=None) -> Dict[str, int]:
    """读取旧版全局变量文件，作为新格式的兼容回退。

    开发目录使用可编辑的 ``_variables.json``；发行目录使用
    ``_variables.tkspatch``。迁移后两者可能同时存在，因此必须优先读取
    源码文件，否则修改开发文件不会生效。
    """
    log = log_func or (lambda x: None)
    source_path = os.path.join(patches_dir, "_variables.json")
    packaged_path = os.path.join(patches_dir, VARIABLES_FILE)
    if os.path.isfile(source_path):
        vpath = source_path
        source_label = "_variables.json"
    elif os.path.isfile(packaged_path):
        vpath = packaged_path
        source_label = VARIABLES_FILE
    else:
        log(f"  [WARN] 全局变量文件不存在: {packaged_path}")
        return {}
    try:
        with open(vpath, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 {source_label} 失败: {e}")
        return {}

    vars_raw = raw.get("variables", {})
    if not isinstance(vars_raw, dict):
        log(f"  [WARN] {source_label} 缺少 variables 段")
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
            log(f"  [WARN] {source_label} 变量 {k} 解析失败, 跳过")
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

    # 2. 加载统一格式的全局变量补丁；旧文件仅作回退。
    ext_patches = load_tkspatch_dir(patches_dir, log_func=log)
    variable_patches = [p for p in ext_patches if p.type == GLOBAL_VARIABLES_TYPE]
    if variable_patches:
        for variable_patch in variable_patches:
            variables = _parse_variables(
                {"variables": getattr(variable_patch, "_extra", {}).get("variables", {})},
                f"{GLOBAL_VARIABLES_ID}.tkspatch",
                log_func=log,
            )
            if variables:
                config.variables.update(variables)
                log(f"  [config] 全局变量: {len(variables)} 个 (来自 {GLOBAL_VARIABLES_ID}.tkspatch)")
        ext_patches = [p for p in ext_patches if p.type != GLOBAL_VARIABLES_TYPE]
    else:
        ext_vars = load_variables_from_dir(patches_dir, log_func=log)
        if ext_vars:
            config.variables.update(ext_vars)
            variable_source = "_variables.json" if os.path.isfile(os.path.join(patches_dir, "_variables.json")) else VARIABLES_FILE
            log(f"  [config] 全局变量: {len(ext_vars)} 个 (来自 {variable_source})")

    # 3. 外置补丁合并
    if ext_patches:
        config = merge_patches(config, ext_patches, log_func=log)

    return config


def load_tkspatch_dir(patches_dir: str, log_func=None) -> List[PatchDef]:
    """扫描目录加载所有 .tkspatch 文件或源码目录, 按文件名排序确保确定性。
    
    支持两种模式:
    1. 生产环境: patches/*.tkspatch 文件（统一 ZIP 格式；旧 JSON 仍兼容）
    2. 开发环境: patches/补丁名/ 源码目录（包含 patch.json）

    global_variables 类型会被返回给上层提取变量，但不会进入 UI 补丁列表。
    """
    log = log_func or (lambda x: None)
    if not os.path.isdir(patches_dir):
        return []

    results: List[PatchDef] = []
    
    entries = os.listdir(patches_dir)
    source_dirs = sorted(
        f for f in entries
        if os.path.isdir(os.path.join(patches_dir, f))
        and not f.startswith('_')
        and os.path.isfile(os.path.join(patches_dir, f, 'patch.json'))
    )
    files = sorted(f for f in entries if f.endswith('.tkspatch'))

    # 源码目录是开发入口，即使目录中还残留旧的 .tkspatch，也必须以源码为准。
    if source_dirs:
        log("  [DEV] 从补丁源码目录加载（源码优先于 .tkspatch）")
        for dirname in source_dirs:
            dir_path = os.path.join(patches_dir, dirname)
            patch_json = os.path.join(dir_path, 'patch.json')
            try:
                with open(patch_json, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                errors = validate_tkspatch_dict(raw, source_path=patch_json, log_func=log)
                if errors:
                    log(f"  [SCHEMA-FAIL] {patch_json}: 跳过")
                    continue
                defn = parse_patch_dict(raw, patch_json, script_resolve_mode="tkspatch_dir")
                if not defn.id:
                    log(f"  [WARN] 跳过无效补丁目录: {dirname}")
                    continue
                if defn.type == "script":
                    script_path = os.path.join(dir_path, raw.get("script_file") or "script.py")
                    if not os.path.isfile(script_path):
                        log(f"  [WARN] {dirname}: 缺少脚本文件")
                        continue
                    with open(script_path, 'r', encoding='utf-8') as sf:
                        defn.script_source = sf.read()
                    defn.script_path = ""
                if defn.json_file:
                    declared_name = raw.get("json_file", "")
                    candidate = os.path.join(dir_path, declared_name)
                    if declared_name and os.path.isfile(candidate):
                        defn.json_file = candidate
                results.append(defn)
                log(f"  [DEV] 加载源码补丁: {dirname} (id={defn.id})")
            except Exception as e:
                log(f"  [ERROR] 加载源码补丁失败 {dirname}: {e}")
    else:
        # 没有源码目录时，兼容发行目录中的 .tkspatch 文件。
        for fname in files:
            if fname == VARIABLES_FILE:
                continue
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
