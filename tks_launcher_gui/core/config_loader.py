"""补丁配置加载 — 从 tks_launcher.py 提取"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PatchSettings:
    """固定的补丁执行参数。"""
    warpc_base_fallback: int = 0x757F08
    warpc_rec_size: int = 1054
    save_block_ab_size: int = 9200
    tkkon_orig_size: int = 26000
    tkkon_rec_size: int = 40
    tkkon_base: int = 0x9D0698
    tkact_orig_size: int = 509600
    tkact_rec_size: int = 784
    tkact_base: int = 0x9539CA
    tkdefunit_orig_count: int = 5000
    cave_total_size: int = 2048


@dataclass
class PatchRuntimeState:
    """单次启动期间计算出的补丁运行时状态。"""
    target_pid: int = 0
    warpc_base: int = 0
    warpc_new_base: int = 0
    warpc_new_size: int = 0
    save_new_size: int = 0
    tkmat_actual_size: int = 0
    tkitem_actual_size: int = 0
    tkskill_actual_size: int = 0
    tkshop_actual_size: int = 0
    tkkon_actual_size: int = 0
    tkact_new_size: int = 0
    tkdefunit_new_count: int = 0


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
    value_size: int = 4  # patch_imm32 立即数宽度 (字节): 4=imm32(默认), 2=imm16
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
    patches: List[PatchDef] = field(default_factory=list)


def resolve_config_path(base_path: str, rel: str) -> str:
    """解析补丁定义中声明的相对 json_file 路径。

    候选目录依次为: 配置文件所在目录及其各级父目录, 启动器根目录, 启动器上级目录。
    开发模式下 configs/ 位于启动器上级目录 (configs);
    打包模式下 configs/ 与 exe 同级 (发行目录 configs/)。
    源码补丁 patch.json 位于 patches/<name>/ 下 (距启动器根目录两层),
    向上回溯需覆盖到启动器上级目录, 否则找不到 configs/。
    """
    if os.path.isabs(rel):
        return rel
    base_dir = os.path.dirname(os.path.abspath(base_path)) if base_path else os.getcwd()
    # 启动器根目录 = core/ 的上级目录 (不依赖 base_path 的嵌套深度)
    launcher_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    seen = set()
    candidates = []
    cur = base_dir
    for _ in range(4):
        c = os.path.join(cur, rel)
        if c not in seen:
            seen.add(c)
            candidates.append(c)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for root in (launcher_root, os.path.dirname(launcher_root)):
        c = os.path.join(root, rel)
        if c not in seen:
            seen.add(c)
            candidates.append(c)
    for c in candidates:
        if os.path.isfile(c):
            return c
    # 无命中时返回启动器根目录下的路径 (保持原有日志提示行为)
    return os.path.join(launcher_root, rel)


def resolve_patch_value(expr: str, settings: PatchSettings,
                        runtime: PatchRuntimeState, log_func=None) -> Optional[int]:
    """解析补丁表达式，运行时状态优先于固定设置。"""
    log = log_func or (lambda x: None)
    if expr is None:
        return 0
    if expr.startswith('{') and expr.endswith('}'):
        name = expr[1:-1]
        if hasattr(runtime, name):
            return int(getattr(runtime, name))
        if hasattr(settings, name):
            return int(getattr(settings, name))
        log(f"  [WARN] 未定义参数: {name}")
        return None
    if expr.lower().startswith('0x'):
        return int(expr[2:], 16)
    return int(expr)
