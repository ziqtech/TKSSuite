"""补丁配置加载 — 从 tks_launcher.py 提取"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class PatchDef:
    type: str = ""
    id: str = ""
    name: str = ""       # 补丁显示名称 (纯中文, 供启动器补丁列表展示)
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
    hook_offset: int = 0
    hook_verify_pattern: str = ""
    hook_pattern: str = ""
    hook_expect_count: int = 0
    value_scan: bool = False
    optional: bool = False
    default_checked: bool = True  # 可选补丁默认是否勾选 (仅 optional=True 时有效, 默认 True)
    # 第三方 MOD 兼容字段
    profile_rules: Dict[str, str] = field(default_factory=dict)  # {profile_name: "apply"|"skip"}
    hook_conflict_action: str = "override"  # hook 点已被占用时: "override" | "skip"
    exclude_extra_sections: bool = True  # value_scan 时是否排除额外段
    fallback_rva: int = 0  # 模式扫描失败时的回退 RVA (用于 MOD 版本)
    patterns: List[Dict] = field(default_factory=list)  # patch_bytes 多模式: [{pattern, replace, expect_count}]
    # patch_summon_table 专用字段
    json_file: str = ""                       # 召唤表 JSON 路径 (load_config 解析为绝对路径)
    script_path: str = ""                     # 外置脚本补丁路径 (type=script, 已解析为绝对路径)
    script_source: str = ""                   # ZIP 型 .tkspatch 内嵌脚本源码 (type=script)
    data_rva: int = 0                         # .data 召唤表 8 字节的 RVA
    data_keys: List[str] = field(default_factory=list)   # .data 8 字节顺序对应的 JSON 键名
    code_addrs: List[Dict] = field(default_factory=list)  # 代码段 imm16 直接地址写入 [{rva, key}]
    # patch_summon_table 多随机 cave 注入字段 (224~231 *_random 列表)
    # data_keys 顺序即 entry 顺序 (224~231 -> entry 0~7); 列表型 JSON 键名 = data_keys[k] + "_random"
    random_hook_pattern: str = ""             # hook 点模式 (定位 0x444C84 查表指令)
    random_hook_size: int = 0                 # 覆盖字节数 (=7: E8 rel32 + 2 NOP)
    random_hook_expect_count: int = 0         # 预期匹配数
    random_cave_offset: int = 0               # 224~231 cave 代码 (entry_224, 77字节) 偏移
    random_table_offset: int = 0              # 候选表 (90字节: entry0~7=224~231, 8=222, 9=251) 偏移
    # 222/251 多随机: 合并 cave 代码 (entry_222+entry_251+shared, 63字节) + 多 hook
    random2_cave_offset: int = 0             # 222/251 合并 cave 代码偏移
    random2_hooks: List[Dict] = field(default_factory=list)  # [{pattern,hook_size,expect_count,entry_offset,json_key,entry_idx}]
    _pre_scanned_hits: List[int] = field(default_factory=list, repr=False)

    # Phase 6: Cave 布局模式
    # True (默认): 启动器自动分配 cave 偏移, .tkspatch 无需声明
    # False:        沿用 .tkspatch 硬编码的 cave_offset / random_*_offset (旧模式)
    autolayout_cave: bool = True

@dataclass
class PatchConfig:
    variables: Dict[str, int] = field(default_factory=dict)
    patches: List[PatchDef] = field(default_factory=list)


def resolve_config_path(base_path: str, rel: str) -> str:
    """解析补丁定义中声明的相对 json_file 路径。

    候选目录依次为: 配置文件所在目录, 启动器根目录, 启动器上级目录。
    开发模式下 configs/ 位于启动器上级目录 (configs);
    打包模式下 configs/ 与 exe 同级 (发行目录 configs/)。
    """
    if os.path.isabs(rel):
        return rel
    base_dir = os.path.dirname(os.path.abspath(base_path)) if base_path else os.getcwd()
    cur = base_dir
    candidates = []
    for _ in range(3):
        candidates.append(os.path.join(cur, rel))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for c in candidates:
        if os.path.isfile(c):
            return c
    # 无命中时返回启动器根目录下的路径 (保持原有日志提示行为)
    return candidates[1] if len(candidates) > 1 else candidates[0]


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
        # Phase 8: 委托给 parse_patch_dict 统一字段映射
        from .tkspatch_loader import parse_patch_dict
        # 兼容: launcher_config.json 等可能用 patches.enabled 列表式而非数组
        # 若 patches 是 list, 才是真正的补丁定义数组
        if isinstance(raw["patches"], list):
            for pr in raw["patches"]:
                if isinstance(pr, dict):
                    d = parse_patch_dict(pr, path, script_resolve_mode="config_path")
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
