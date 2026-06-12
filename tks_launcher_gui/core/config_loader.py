"""补丁配置加载 — 从 tks_launcher.py 提取"""
import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class PatchDef:
    type: str = ""
    id: str = ""
    desc: str = ""
    pattern: str = ""
    value_offset: int = 0
    expect_value: int = 0
    new_value_expr: str = ""
    replace: Dict[str, int] = field(default_factory=dict)
    expect_count: int = 0
    cave_template: str = ""
    cave_offset: int = 0
    hook_size: int = 0
    hook_verify_pattern: str = ""
    hook_pattern: str = ""
    hook_expect_count: int = 0
    value_scan: bool = False
    optional: bool = False
    _pre_scanned_hits: List[int] = field(default_factory=list, repr=False)

@dataclass
class PatchConfig:
    variables: Dict[str, int] = field(default_factory=dict)
    patches: List[PatchDef] = field(default_factory=list)

def load_config(path: str, log_func=None) -> Optional[PatchConfig]:
    log = log_func or (lambda x: None)
    if not os.path.isfile(path):
        log(f"  [WARN] 配置文件 {path} 不存在")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 JSON 配置失败: {e}")
        return None

    config = PatchConfig()

    if "variables" in raw:
        for k, v in raw["variables"].items():
            if isinstance(v, dict):
                if "fallback" in v:
                    fbv = v["fallback"]
                    if isinstance(fbv, str) and fbv.lower().startswith("0x"):
                        config.variables[k] = int(fbv, 16)
                    else:
                        config.variables[k] = int(fbv)
            elif isinstance(v, str):
                if v.lower().startswith("0x"):
                    config.variables[k] = int(v, 16)
                else:
                    config.variables[k] = int(v)
            elif isinstance(v, bool):
                config.variables[k] = 1 if v else 0
            else:
                config.variables[k] = int(v)

    def _parse_maybe_hex(val):
        if isinstance(val, str):
            if val.lower().startswith("0x"):
                return int(val, 16)
            return int(val)
        return int(val)

    def _parse_replace_val(val):
        if isinstance(val, str):
            return int(val, 16)
        return int(val)

    if "patches" in raw:
        for pr in raw["patches"]:
            d = PatchDef()
            d.type = pr.get("type", "")
            d.id = pr.get("id", "")
            d.desc = pr.get("desc", "")
            d.pattern = pr.get("pattern", "")
            d.value_offset = pr.get("value_offset", 0)
            d.expect_value = _parse_maybe_hex(pr.get("expect_value", 0))
            d.new_value_expr = str(pr.get("new_value", ""))
            d.expect_count = pr.get("expect_count", 0)
            d.hook_size = pr.get("hook_size", 0)
            d.cave_offset = pr.get("cave_offset", 0)
            d.cave_template = pr.get("cave_template", "")
            d.hook_verify_pattern = pr.get("hook_verify", "")
            d.hook_pattern = pr.get("hook_pattern", "")
            d.hook_expect_count = pr.get("hook_expect_count", 0)
            d.value_scan = pr.get("value_scan", False)
            d.optional = pr.get("optional", False)
            if "replace" in pr:
                for rk, rv in pr["replace"].items():
                    d.replace[rk] = _parse_replace_val(rv)
            config.patches.append(d)

    log(f"  已加载配置: {len(config.variables)} 个变量, {len(config.patches)} 个补丁")
    return config

def resolve_var(expr: str, variables: Dict[str, int], log_func=None) -> Optional[int]:
    """解析变量引用。strict 模式下未定义变量返回 None"""
    log = log_func or (lambda x: None)
    if expr is None:
        return 0
    if expr.startswith('{') and expr.endswith('}'):
        vn = expr[1:-1]
        if vn in variables:
            return variables[vn]
        log(f"  [WARN] 未定义变量: {vn}")
        return None
    if expr.lower().startswith('0x'):
        return int(expr[2:], 16)
    return int(expr)
