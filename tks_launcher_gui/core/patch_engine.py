"""补丁应用引擎 — 从 tks_launcher.py 提取 & 重组"""
import json
import importlib.util
import os
import struct
import types
from typing import Any, Dict, List, Optional, Tuple
from .memory import (
    i32b, i16b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex,
    replace_addr_in_bytes,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    _OpenProcess, _CloseHandle,
)
from .scanner import parse_pattern, pattern_scan, value_scan
from .config_loader import (
    PatchConfig,
    PatchDef,
    PatchRuntimeState,
    PatchSettings,
    resolve_patch_value,
)


def _check_cave_bounds(cave_addr: int, offset: int, size: int, budget: int,
                        label: str, log) -> bool:
    """Cave 越界硬校验。返回 True 表示在范围内, False 表示越界(已日志告警)。

    Phase 2 引入: 防止 .tkspatch 中 cave_offset/size 超出 cave_total_size 时静默
    越界写入损坏 WarPC 数据区或其他进程内存。仅日志告警, 不抛异常, 保持向后兼容。
    """
    if offset < 0 or size < 0:
        log(f"  [CAVE-OOB] {label}: offset/size 负值 "
            f"(offset=0x{offset:X}, size={size})")
        return False
    end = offset + size
    if end > budget:
        log(f"  [CAVE-OOB] {label}: 0x{offset:X}+{size}={end} > budget={budget}, 跳过")
        return False
    return True


class PatchContext:
    """外部脚本补丁的稳定运行上下文。

    Phase 5: 作为所有 patch_type handler 的统一入参 (原本仅用于 script 类型)。
    """
    def __init__(self, defn: PatchDef, target_pid: int, h_proc: int,
                 base_addr: int, code_buf: bytearray, code_start_addr: int,
                 cave_addr: int, warpc_base: int,
                 settings: PatchSettings, runtime: PatchRuntimeState,
                 log_func=None, exe_profile=None, config_overrides=None):
        self.defn = defn
        self.target_pid = target_pid
        self.h_proc = h_proc
        self.base_addr = base_addr
        self.code_buf = code_buf
        self.code_start_addr = code_start_addr
        self.cave_addr = cave_addr
        self.warpc_base = warpc_base
        self.settings = settings
        self.runtime = runtime
        self.log = log_func or (lambda x: None)
        self.exe_profile = exe_profile
        self.config_overrides = config_overrides


# ============================================================
# 补丁类型注册表 (Phase 5)
# ============================================================
#
# 将原本在 apply_config_patches 中的 if/elif 分派改为注册表派发:
# - 每种 patch_type 对应一个 handler, 接受统一的 PatchContext 入参
# - handler 通过 @register_patch_type("xxx") 装饰器注册
# - apply_config_patches 只需在字典中查找, 无需硬编码类型分派
# - 新增 patch_type 时只需实现并注册, 不再修改 dispatcher
#
# 特殊类型说明:
# - "cave_hook": 两阶段提交 (pre-scan 在 dispatcher, apply 在 patch 后),
#   由 dispatcher 显式处理, 不进入注册表。
# - "script": 通过 run_script_patch 间接调用外部 apply(ctx), 单独保留。
# - "patch_warpc_addr": 仅日志, 不实际应用 (由 WarPC 扩展流程处理)。
# - 未知类型: 记日志并跳过, 由 dispatcher 处理。

_PATCH_TYPE_HANDLERS: Dict[str, Any] = {}


def register_patch_type(type_name: str):
    """装饰器: 将 handler 函数注册到指定 patch_type。

    用法:
        @register_patch_type("patch_bytes")
        def _handle_patch_bytes(ctx: PatchContext) -> bool:
            ...
            return True

    Handler 签名: (ctx: PatchContext) -> bool
    返回 True 表示成功, False 表示失败。
    """
    def decorator(fn):
        if type_name in _PATCH_TYPE_HANDLERS:
            raise ValueError(
                f"patch_type '{type_name}' 已注册到 "
                f"{_PATCH_TYPE_HANDLERS[type_name].__name__}, "
                f"重复注册到 {fn.__name__}"
            )
        _PATCH_TYPE_HANDLERS[type_name] = fn
        return fn
    return decorator


def get_registered_handlers() -> Dict[str, Any]:
    """返回当前已注册的 patch_type handler 字典 (测试用)。"""
    return dict(_PATCH_TYPE_HANDLERS)


def run_script_patch(defn: PatchDef, ctx: PatchContext) -> bool:
    """加载并执行 .tkspatch ZIP 内嵌或 patches/_scripts 下的脚本。"""
    try:
        module = _load_script_module(defn, ctx.log)
        if module is None:
            return False
        fn = getattr(module, "apply", None)
        if not callable(fn):
            ctx.log(f"  [ERROR] 外部补丁脚本缺少 apply(ctx) 函数")
            return False
        return bool(fn(ctx))
    except Exception as e:
        ctx.log(f"  [ERROR] 外部补丁脚本执行失败: {e}")
        import traceback
        ctx.log(traceback.format_exc())
        return False


def _load_script_module(defn: PatchDef, log):
    """加载脚本模块，返回模块对象；失败时返回 None。"""
    source = getattr(defn, "script_source", "")
    if source:
        module = types.ModuleType(f"_tkspatch_script_{defn.id or 'zip'}")
        module.__file__ = f"{defn.id or 'patch'}.tkspatch/script.py"
        module.__package__ = ""
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        return module

    path = getattr(defn, "script_path", "")
    if not path or not os.path.isfile(path):
        log(f"  [WARN] 外部补丁脚本不存在: {path!r}, 跳过")
        return None
    spec = importlib.util.spec_from_file_location(
        f"_tkspatch_script_{defn.id or abs(hash(path))}", path)
    if spec is None or spec.loader is None:
        log(f"  [ERROR] 无法加载外部补丁脚本: {path}")
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_script_patch(defn: PatchDef, log_func=None) -> bool:
    """只验证脚本可加载且暴露 apply(ctx)，不执行补丁逻辑。"""
    log = log_func or (lambda x: None)
    try:
        module = _load_script_module(defn, log)
        if module is None:
            return False
        if not callable(getattr(module, "apply", None)):
            log(f"  [ERROR] 外部补丁脚本缺少 apply(ctx) 函数: {defn.id}")
            return False
        log(f"  [OK] 脚本补丁可执行: {defn.id}")
        return True
    except Exception as e:
        log(f"  [ERROR] 脚本补丁验证失败: {defn.id} — {e}")
        return False


# ============================================================
# 补丁类型 handler 注册 (Phase 5)
# ============================================================
#
# 每个 handler 接受 PatchContext, 返回 bool。
# 内部委托给已存在的 apply_* 函数, 不改变原函数行为。
# 注册表查找失败的类型由 dispatcher 走兜底分支 (warn)。


@register_patch_type("patch_bytes")
def _handle_patch_bytes(ctx: PatchContext) -> bool:
    return apply_patch_bytes(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, log_func=ctx.log,
    )


@register_patch_type("patch_extra_section")
def _handle_patch_extra_section(ctx: PatchContext) -> bool:
    return apply_patch_extra_section(
        ctx.defn, ctx.h_proc, ctx.exe_profile, log_func=ctx.log,
    )


@register_patch_type("patch_imm32")
def _handle_patch_imm32(ctx: PatchContext) -> bool:
    if ctx.defn.value_scan:
        nv = resolve_patch_value(
            ctx.defn.new_value_expr, ctx.settings, ctx.runtime, log_func=ctx.log
        )
        if nv is None:
            ctx.log(f"    -> 变量未定义, 跳过")
            return True
        if ctx.defn.expect_value != 0 and nv == ctx.defn.expect_value:
            ctx.log(f"    -> 值未变化 ({ctx.defn.expect_value}), 跳过")
            return True
        return apply_patch_imm32_by_value(
            ctx.defn, ctx.code_buf, ctx.code_start_addr,
            ctx.h_proc, ctx.settings, ctx.runtime, log_func=ctx.log,
            exclude_ranges=ctx.exe_profile.extra_section_ranges if ctx.exe_profile else None,
        )
    return apply_patch_imm32_by_pattern(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, ctx.settings, ctx.runtime, log_func=ctx.log,
    )


@register_patch_type("patch_summon_table")
def _handle_patch_summon_table(ctx: PatchContext) -> bool:
    _summon_override = None
    if ctx.config_overrides:
        _summon_override = ctx.config_overrides.get("summon_table")
    return apply_summon_table(
        ctx.defn, ctx.code_buf, ctx.code_start_addr, ctx.base_addr,
        ctx.h_proc, ctx.settings, ctx.runtime, log_func=ctx.log,
        cave_addr=ctx.cave_addr,
        config_override=_summon_override,
    )


@register_patch_type("patch_drop_probability")
def _handle_patch_drop_probability(ctx: PatchContext) -> bool:
    _drop_override = None
    if ctx.config_overrides:
        _drop_override = ctx.config_overrides.get("drop_probability")
    return apply_drop_probability(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, log_func=ctx.log,
        config_override=_drop_override,
    )


@register_patch_type("patch_exp_lock")
def _handle_patch_exp_lock(ctx: PatchContext) -> bool:
    _explock_override = None
    if ctx.config_overrides:
        _explock_override = ctx.config_overrides.get("exp_lock")
    return apply_exp_lock(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, ctx.cave_addr, log_func=ctx.log,
        config_override=_explock_override,
        cave_budget=ctx.settings.cave_total_size,
    )


@register_patch_type("patch_font_config")
def _handle_patch_font_config(ctx: PatchContext) -> bool:
    return apply_font_config(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, log_func=ctx.log,
    )


@register_patch_type("patch_animation_speed")
def _handle_patch_animation_speed(ctx: PatchContext) -> bool:
    return apply_animation_speed(
        ctx.defn, ctx.code_buf, ctx.code_start_addr,
        ctx.h_proc, log_func=ctx.log,
    )


# ============================================================
# Phase 6: Cave 布局
# ============================================================

def _build_cave_layout(config: 'PatchConfig', cave_addr: int,
                       settings: PatchSettings, log) -> Optional['CaveLayout']:
    """在主循环之前一次性为所有需要 cave 的补丁分配偏移。

    Args:
        config:      补丁配置
        cave_addr:   cave 区基址 (0 = 未分配, 跳过)
        settings:    固定补丁参数 (包含 cave_total_size)
        log:         日志回调

    Returns:
        CaveLayout 实例 (cave_addr=0 时返回 None)。
        解析后的偏移存到 defn._resolved_<key>, 供 apply_cave_hook/_apply_summon_random 使用。

    Raises:
        CaveLayoutError: 硬编码冲突或越界 (仅当严格模式)
    """
    if not cave_addr:
        return None
    from .cave_layout import CaveLayout, CaveLayoutError

    cave_budget = settings.cave_total_size
    layout = CaveLayout(base_addr=cave_addr, budget=cave_budget)

    # 1. 收集每个需要 cave 的补丁所需大小
    #    cave_hook / patch_exp_lock: 1 个 main 槽位
    #    patch_summon_table:         3 个槽位 (table + random_cave + random2_cave)
    for defn in config.patches:
        try:
            if defn.type == "cave_hook":
                # 必须按实际模板长度预留。固定 64 字节会让较长模板互相覆盖。
                ext_cave = getattr(defn, '_cave_code_bytes', None)
                if ext_cave:
                    size = len(ext_cave)
                else:
                    template = build_cave_template(
                        defn.cave_template, 0x70000000, log_func=log)
                    size = len(template) if template else 0
                if size <= 0:
                    log(f"  [CAVE-LAYOUT-ERR] {defn.id}: 无法确定 cave 模板大小")
                    continue
                force_off = None if getattr(defn, "autolayout_cave", True) else defn.cave_offset
                slot = layout.allocate(defn.id, "main", size, force_offset=force_off)
                defn._resolved_cave_offset = slot.offset

            elif defn.type == "patch_exp_lock":
                ext_cave = getattr(defn, '_cave_code_bytes', None)
                if not ext_cave:
                    log(f"  [CAVE-LAYOUT-ERR] {defn.id}: patch_exp_lock 需要外置 cave_code")
                    continue
                size = len(ext_cave)
                force_off = None if getattr(defn, "autolayout_cave", True) else defn.cave_offset
                slot = layout.allocate(defn.id, "main", size, force_offset=force_off)
                defn._resolved_cave_offset = slot.offset

            elif defn.type == "patch_summon_table":
                _autolayout = getattr(defn, "autolayout_cave", True)
                for purpose, size, off_attr in [
                    ("random_table", 90, "random_table_offset"),
                    ("random_cave",  77, "random_cave_offset"),
                    ("random2_cave", 63, "random2_cave_offset"),
                ]:
                    force_off = None if _autolayout else getattr(defn, off_attr, 0)
                    slot = layout.allocate(defn.id, purpose, size, force_offset=force_off)
                    setattr(defn, f"_resolved_{off_attr}", slot.offset)
        except CaveLayoutError as e:
            log(f"  [CAVE-LAYOUT-ERR] {e}")
            # 不抛异常, 而是标记该补丁的 _resolved 字段为 None, 让 apply_* 走默认路径
            # 这样保证向后兼容: 硬编码模式下若冲突, 启动器仍尝试运行 (行为退化为覆盖)

    # 启动器日志: 显示布局摘要
    log(f"  [CAVE-LAYOUT] {len(layout.slots)} 槽位, "
        f"已用 {layout.used_bytes()}/{layout.budget} "
        f"({100 * layout.used_bytes() / max(1, layout.budget):.1f}%)")
    return layout


# ============================================================
# Hook 冲突检测 (Phase 7)
# ============================================================
#
# Phase 7 引入:
# - detect_hook_type: 多模式识别 (call/jmp/jcc/push_imm32/jmp_indirect)
# - HookTable: 跟踪启动器内部多个 cave_hook 之间的占用关系
# - check_hook_conflict_v2: 联合识别 + 启动器内部 hook_table 查询
# - 原 check_hook_conflict 保留, 仅作为简化版 fallback (返回 bool, 不带 owner 信息)

# x86 Hook 类型识别 (基于首字节 + 必要的后续字节)
# 参考 IA-32 手册 Vol.2B Table A-2 (One-byte Opcode Map)
_HOOK_TYPE_TABLE: Dict[int, Tuple[str, int]] = {
    0xE8: ("call_rel32", 5),       # CALL rel32
    0xE9: ("jmp_rel32", 5),        # JMP rel32
    0xEB: ("jmp_rel8", 2),         # JMP rel8
    0x68: ("push_imm32", 5),       # PUSH imm32 (常搭配 C3 = ret 形成 hook stub)
}


def detect_hook_type(code_buf: bytearray, off: int) -> Tuple[str, int]:
    """识别 hook 点位置 (off) 的 x86 指令类型。

    返回 (类型名, 占用字节数):
    - ("call_rel32", 5)  E8 xx xx xx xx
    - ("jmp_rel32", 5)   E9 xx xx xx xx
    - ("jmp_rel8", 2)    EB xx
    - ("push_imm32", 5)  68 xx xx xx xx
    - ("jmp_indirect", 6)  FF 25 xx xx xx xx
    - ("jcc_rel32", 6)   0F 8x xx xx xx xx (Jcc long form)
    - ("none", 0)        非 hook 指令 (普通代码)
    - ("oob", 0)         越界

    Args:
        code_buf: 代码段缓冲
        off: hook 点在 code_buf 中的偏移
    """
    if off < 0 or off >= len(code_buf):
        return ("oob", 0)
    b0 = code_buf[off]
    if b0 in _HOOK_TYPE_TABLE:
        return _HOOK_TYPE_TABLE[b0]
    # FF /4 = JMP [mem32], 即 jmp_indirect
    if b0 == 0xFF and off + 1 < len(code_buf) and code_buf[off + 1] == 0x25:
        return ("jmp_indirect", 6)
    # 0F 80~0F 8F = Jcc rel32 (JE/JNE/JB/JAE/JBE/JA/JS/JNS/JP/JNP/JL/JGE/JLE/JG)
    if b0 == 0x0F and off + 1 < len(code_buf) and 0x80 <= code_buf[off + 1] <= 0x8F:
        return ("jcc_rel32", 6)
    return ("none", 0)


class HookTable:
    """启动器内部 hook 占用跟踪表。

    在主循环中, 每个 cave_hook 写码前会向 HookTable 注册其 hook 点位置,
    后续 cave_hook 检查冲突时, 优先查 HookTable (启动器内部冲突),
    再用 detect_hook_type 查外部 MOD 的 hook 指令。

    用途: 防止两个 cave_hook 写到同一位置 (原代码无此检查, 静默覆盖)。
    """

    def __init__(self):
        self._table: Dict[int, str] = {}  # off -> owner_patch_id

    def register(self, off: int, owner_id: str) -> None:
        """注册一个 hook 点占用。重复注册不抛异常 (覆盖)。"""
        self._table[off] = owner_id

    def owner_at(self, off: int) -> Optional[str]:
        """返回 off 位置的占用者 (启动器内 cave_hook id), 或 None。"""
        return self._table.get(off)

    def __len__(self) -> int:
        return len(self._table)

    def __contains__(self, off: int) -> bool:
        return off in self._table


def check_hook_conflict_v2(code_buf: bytearray, off: int,
                         hook_table: Optional['HookTable'] = None
                         ) -> Tuple[bool, str]:
    """检测 hook 点是否已被占用 (Phase 7: v2)。

    检测顺序:
    1. HookTable 查询 (启动器内部)
    2. detect_hook_type 外部 MOD 检测 (call_rel32 / jmp_rel32)

    Args:
        code_buf:   代码段缓冲
        off:        hook 点偏移
        hook_table: 启动器内部 hook 占用表 (可为 None)

    Returns:
        (是否冲突, 占用者 ID 或原因)
        - (True, "<patch_id>")     启动器内部冲突
        - (True, "external_call_or_jmp")  外部 MOD 占用 (call/jmp)
        - (False, "none")          无冲突
        - (False, "oob")           越界
    """
    # 1. HookTable (启动器内部)
    if hook_table is not None:
        owner = hook_table.owner_at(off)
        if owner is not None:
            return (True, owner)

    # 2. 外部 MOD 检测
    ht, _ = detect_hook_type(code_buf, off)
    if ht in ("call_rel32", "jmp_rel32"):
        return (True, "external_call_or_jmp")
    if ht == "oob":
        return (False, "oob")
    return (False, "none")


# 向后兼容: 旧 API 返回 bool, 简化版 fallback
def check_hook_conflict(code_buf: bytearray, off: int) -> bool:
    """[旧 API] 检测 hook 点是否已被其他 MOD 占用 (call/jmp 首字节)。

    Phase 7 保留此函数以兼容 Phase 6 之前的调用代码。
    推荐使用 check_hook_conflict_v2 (返回 (conflict, owner))。
    """
    if off < 0 or off >= len(code_buf):
        return False
    return code_buf[off] in (0xE8, 0xE9)

# ============================================================
# Cave 机制公共常量 (全部 cave 机器码已外置至 patches/)
# ============================================================
# cave_hook          → patch.json cave_code        (带注释源: 同目录 cave_code.py)
# patch_exp_lock     → patch.json cave_code + cave_mask_offset
# patch_summon_table → patch.json summon_cave_code / summon_cave2_code
# 引擎不再内置任何 cave 字节, 仅保留以下重定位占位符。

_WARPC_BASE_PLACEHOLDER = 0x757F08

# 召唤多随机 cave 内的占位符 ("RAND"), cave 内唯一, 指向 72 字节候选表
# (召唤 cave 机器码在 patches/summon_table/patch.json: summon_cave_code / summon_cave2_code)
SUMMON_RANDOM_PLACEHOLDER = 0x52414E44

# ============================================================
# Cave 模板构建
# ============================================================

# awk_sprite / awk_sprite2 cave 中索引上限检查指令 `cmp eax, 200` 的原始字节
# 该上限是硬编码安全阈值, 角色 WarPC 索引 >200 时补丁被跳过 (回退原始公式),
# 扩容 WarPC.dat 后需按实际记录数动态上调, 否则新角色 WORD[260] 不生效
_AWK_CAP_OLD = bytes([0x3D, 0xC8, 0x00, 0x00, 0x00])  # cmp eax, 200

# weapon_cause_mask cave 中 WarPC 索引检查指令 `cmp eax, 0x8F; jae 跳过` 的原始字节
# 0x8F=143 = 原版记录数 (150722/1054), 为排他上限 (索引 0..142 有效);
# 扩容后不上调则新角色 (>142) 的武器附加状态永不生效 (安全降级但功能丢失)
_WEAPON_CAP_OLD = bytes([0x3D, 0x8F, 0x00, 0x00, 0x00])  # cmp eax, 143

def build_cave_template(name: str, warpc_base: int, log_func=None,
                        idx_cap: Optional[int] = None,
                        external_code: Optional[bytes] = None,
                        rec_count: Optional[int] = None,
                        warpc_cap_adjust: bool = False,
                        weapon_cap_adjust: bool = False) -> Optional[bytes]:
    """构建 cave 机器码: 外置代码优先, 回退内置模板。

    上限动态调整触发条件 (声明式, 新增补丁无需改引擎):
      warpc_cap_adjust=True  或 name 命中旧白名单 (awk_sprite/awk_sprite2)
      weapon_cap_adjust=True 或 name == "weapon_cause_mask"
    """
    log = log_func or (lambda x: None)
    do_awk_cap = warpc_cap_adjust or name in ("awk_sprite", "awk_sprite2")
    do_weapon_cap = weapon_cap_adjust or name == "weapon_cause_mask"

    # 外置 cave 代码优先 (.tkspatch 文件提供)
    if external_code is not None:
        c = bytearray(external_code)
        replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
        # 动态调整战场形象类 cave 的 WarPC 索引上限 (声明式开关或旧白名单)
        if do_awk_cap and idx_cap is not None:
            pos = c.find(_AWK_CAP_OLD)
            if pos >= 0:
                c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', idx_cap & 0xFFFFFFFF)
        # 动态调整武器 cause_mask cave 的 WarPC 索引排他上限 (=记录数, 同长 5 字节)
        if do_weapon_cap and rec_count is not None:
            pos = c.find(_WEAPON_CAP_OLD)
            if pos >= 0:
                c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', rec_count & 0xFFFFFFFF)
        log(f"    Cave 来源: 外置 .tkspatch ({len(c)} bytes)")
        return bytes(c)

    # 回退: 内置模板 — 全部 cave 机器码已外置至 patches/, 引擎不再内置任何模板。
    # 未提供外置 cave_code 的补丁无法构建 (各补丁均已自带, 此分支仅为防御性提示)。
    log(f"    [WARN] 无内置 cave 模板 ({name!r}): 请在 patch.json 提供外置 cave_code")
    return None

# ============================================================
# 补丁类型: patch_bytes
# ============================================================

def apply_patch_bytes(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       h_proc: int, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    # 支持多模式 (patterns) 或单模式 (向后兼容)
    if defn.patterns:
        entries = defn.patterns
    else:
        entries = [{
            "pattern": defn.pattern, "expect_count": defn.expect_count,
            "replace": dict(defn.replace),
        }]
    all_ok = True
    for entry in entries:
        pat, wc = parse_pattern(entry["pattern"])
        hits = pattern_scan(bytes(code_buf), pat, wc)
        expect = entry.get("expect_count", 0)
        log(f"    模式: [{entry['pattern']}] -> 匹配 {len(hits)} 处 (预期 {expect})")
        if expect > 0 and len(hits) != expect:
            log(f"  [WARN] 匹配数 {len(hits)} != 预期 {expect}")
            # 命中数不符合定义时，继续写入会把模糊特征误应用到错误位置。
            all_ok = False
            continue
        ptd = 0
        for off in hits:
            for rk, bv in entry["replace"].items():
                ro = int(rk)
                idx = off + ro
                if idx < 0 or idx >= len(code_buf):
                    log(f"  [FAIL] 替换偏移越界: RVA 0x{idx:X} (缓冲区 0x0..0x{len(code_buf)-1:X})")
                    all_ok = False
                    continue
                aa = code_start_addr + idx
                op = vp_ex(h_proc, aa, 1, PAGE_EXECUTE_READWRITE)
                write_pm(h_proc, aa, bytes([bv & 0xFF]))
                vp_ex(h_proc, aa, 1, op)
                code_buf[idx] = bv & 0xFF
            log(f"    [OK] RVA 0x{off:X} (abs 0x{code_start_addr + off:08X})")
            ptd += 1
        if ptd == 0 and expect > 0:
            log("  [FAIL] 未找到匹配模式")
            all_ok = False
    return all_ok

# ============================================================
# 补丁类型: patch_extra_section (MOD 额外 PE 段字节修补)
# ============================================================

def apply_patch_extra_section(defn: PatchDef, h_proc: int, exe_profile, log_func=None) -> bool:
    """在 MOD 额外 PE 段 (.test/.Newdata/.Silvana) 内扫描并应用字节补丁。

    启动器常规补丁的扫描窗口为 code_buf (base+0x1000, 3MB), 第三方 MOD
    注入的新 PE 段 (如孝谈三国3终极版 .test 节 cave) 落在此窗口之外,
    无法被 patch_bytes 命中。本函数直接读取进程内存中 exe_profile 的
    extra_section_ranges, 在该范围内做 pattern 扫描 + 逐字节替换,
    流程与 apply_patch_bytes 一致 (vp_ex 切换页属性 + 写入 + 还原)。

    非 MOD 版 (无额外段) 或未命中时安全跳过: 未命中且 expect_count>0 时
    返回 False (供上层 all_ok 汇总), 其余情况返回 True。
    """
    log = log_func or (lambda x: None)
    ranges = getattr(exe_profile, "extra_section_ranges", None) if exe_profile else None
    if not ranges:
        log("    -> 无 MOD 额外段 (非第三方 MOD 版), 跳过")
        return True
    pat, wc = parse_pattern(defn.pattern)
    repl = dict(defn.replace)
    expect = defn.expect_count
    log(f"    模式: [{defn.pattern}] (额外段扫描)")
    patched = 0
    for (start, end) in ranges:
        size = end - start
        if size <= 0 or size > 0x100000:
            continue
        buf, nr = read_pm(h_proc, start, size)
        if nr <= 0:
            continue
        hits = pattern_scan(bytes(buf[:nr]), pat, wc)
        if hits:
            log(f"    段 0x{start:08X}-0x{end:08X}: 匹配 {len(hits)} 处")
        for off in hits:
            for rk, bv in repl.items():
                ro = int(rk)
                aa = start + off + ro
                if aa < start or aa >= end:
                    log(f"  [FAIL] 额外段替换偏移越界: 0x{aa:08X} "
                        f"(段范围 0x{start:08X}-0x{end:08X})")
                    continue
                op = vp_ex(h_proc, aa, 1, PAGE_EXECUTE_READWRITE)
                write_pm(h_proc, aa, bytes([bv & 0xFF]))
                vp_ex(h_proc, aa, 1, op)
            log(f"    [OK] @0x{start + off:08X} (段内偏移 0x{off:X})")
            patched += 1
    if patched == 0:
        if expect > 0:
            log(f"  [FAIL] 未找到匹配模式 (MOD 版本不同或已处理), 跳过")
            return False
        log("    未命中 (预期 0), 跳过")
    return True

# ============================================================
# 补丁类型: patch_imm32 (value_scan)
# ============================================================

def apply_patch_imm32_by_value(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                h_proc: int, settings: PatchSettings,
                                runtime: PatchRuntimeState, log_func=None,
                                exclude_ranges: list = None) -> bool:
    log = log_func or (lambda x: None)
    _excl = exclude_ranges or []
    ov = defn.expect_value
    nv = resolve_patch_value(defn.new_value_expr, settings, runtime, log_func=log)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    hits = value_scan(bytes(code_buf), ov)
    log(f"    扫描值 {ov} (0x{ov:X}) -> 匹配 {len(hits)} 处")
    expect = defn.expect_count
    if expect > 0 and len(hits) != expect:
        log(f"  [FAIL] 值扫描命中 {len(hits)} 处 (预期 {expect}), 跳过")
        return False
    log(f"    替换为 {nv} (0x{nv:X})")
    nle = i32b(nv)
    ptd = 0
    all_ok = True
    for off in hits:
        # 安全检查: 跳过 call/jmp 以及 0F 8x 条件跳转 rel32 的字节重叠
        if off >= 1 and code_buf[off - 1] in (0xE8, 0xE9, 0x0F):
            log(f"    [SKIP] RVA 0x{off:X}: 前字节为 E8/E9/0F (rel32 指令), 跳过")
            continue
        # 第三方 MOD 兼容: 排除额外段
        if _excl and defn.exclude_extra_sections:
            abs_a = code_start_addr + off
            skip = False
            for ex_start, ex_end in _excl:
                if ex_start <= abs_a < ex_end:
                    log(f"    [SKIP] RVA 0x{off:X}: 位于 MOD 额外段内")
                    skip = True
                    break
            if skip:
                continue
        aa = code_start_addr + off
        op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
        nw = write_pm(h_proc, aa, nle)
        vp_ex(h_proc, aa, 4, op)
        if nw != 4:
            log(f"    [FAIL] WriteProcessMemory 失败 @0x{aa:08X}")
            all_ok = False
            continue
        if off + 4 <= len(code_buf):
            code_buf[off:off+4] = nle
        log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
        ptd += 1
    if ptd == 0 and expect > 0:
        log("  [FAIL] 未写入任何匹配位置")
        all_ok = False
    return all_ok

# ============================================================
# 补丁类型: patch_imm32 (pattern scan)
# ============================================================

def apply_patch_imm32_by_pattern(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                                  h_proc: int, settings: PatchSettings,
                                  runtime: PatchRuntimeState, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    nv = resolve_patch_value(defn.new_value_expr, settings, runtime, log_func=log)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    if defn.patterns:
        entries = defn.patterns
    else:
        entries = [{
            "pattern": defn.pattern,
            "value_offset": defn.value_offset,
            "expect_count": defn.expect_count,
            "expect_value": defn.expect_value,
        }]
    all_ok = True
    for entry in entries:
        pat, wc = parse_pattern(entry.get("pattern", ""))
        hits = pattern_scan(bytes(code_buf), pat, wc)
        vo = int(entry.get("value_offset", defn.value_offset))
        exp = int(entry.get("expect_count", defn.expect_count))
        ov = int(entry.get("expect_value", defn.expect_value))
        # 立即数宽度: 默认 4 (imm32); imm16 指令 (如 66 C7 mov word) 必须只写 2 字节,
        # 否则会踩坏紧邻的后缀指令 (例: gold_limit 锚定模式后的 EB 跳转)
        vs = int(entry.get("value_size", getattr(defn, "value_size", 4)))
        if vs not in (2, 4):
            log(f"  [FAIL] 非法 value_size={vs}, 跳过")
            all_ok = False
            continue
        if vs == 2 and not (0 <= nv <= 0xFFFF):
            log(f"  [FAIL] 新值 0x{nv:X} 超出 imm16 范围, 跳过")
            all_ok = False
            continue
        nle = struct.pack('<H', nv & 0xFFFF) if vs == 2 else i32b(nv)
        log(f"    模式: [{entry.get('pattern')}] -> 匹配 {len(hits)} 处 (预期 {exp})")
        if exp > 0 and len(hits) != exp:
            log(f"  [FAIL] 匹配数 {len(hits)} != 预期 {exp}, 跳过")
            all_ok = False
            continue
        ptd = 0
        for off in hits:
            io = off + vo
            if io + vs <= len(code_buf):
                act = (b2u16(bytes(code_buf), io) if vs == 2
                       else b2i32(bytes(code_buf), io))
                if ov != 0 and act != ov:
                    log(f"    [SKIP] RVA 0x{off:X}: 原值 0x{act:08X} != 预期 0x{ov:08X}")
                    continue
            aa = code_start_addr + io
            op = vp_ex(h_proc, aa, vs, PAGE_EXECUTE_READWRITE)
            nw = write_pm(h_proc, aa, nle)
            vp_ex(h_proc, aa, vs, op)
            if nw != vs:
                log(f"    [FAIL] WriteProcessMemory 失败 @0x{aa:08X}")
                all_ok = False
                continue
            if io + vs <= len(code_buf):
                code_buf[io:io+vs] = nle
            log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X}, {vs}B)")
            ptd += 1
        if ptd == 0 and exp > 0:
            all_ok = False
    return all_ok

# ============================================================
# 补丁类型: cave_hook
# ============================================================

def apply_cave_hook(defn: PatchDef, hits: List[int], code_buf: bytearray,
                     code_start_addr: int, h_proc: int, cave_addr: int,
                     warpc_base: int, settings: PatchSettings,
                     runtime: PatchRuntimeState, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    if not hits:
        log("    [WARN] 未找到 hook 点")
        return False

    # WarPC 索引上限: 按扩容后的记录数计算 (默认模板硬编码 200,
    # 索引 >200 的新角色会导致 WORD[260] 自定义形象不生效)
    rec_size = settings.warpc_rec_size
    new_size = runtime.warpc_new_size or 150722
    rec_count = (new_size // rec_size) if rec_size > 0 else 143
    idx_cap = rec_count - 1
    if idx_cap < 200:
        idx_cap = 200
    # weapon_cause_mask 的排他上限保持原版语义: 未扩容时 =143 (与原指令 0x8F 一致)
    if rec_count < 143:
        rec_count = 143

    # 外置 cave 代码优先 (.tkspatch 提供), 回退到内置模板。
    # 变换开关优先取补丁声明字段 (getattr 兼容 script 型补丁的命名空间对象),
    # 旧白名单在 build_cave_template 内保留, 存量补丁零改动。
    ext_cave = getattr(defn, '_cave_code_bytes', None)
    cd = build_cave_template(defn.cave_template, warpc_base, log_func=log,
                             idx_cap=idx_cap, external_code=ext_cave,
                             rec_count=rec_count,
                             warpc_cap_adjust=getattr(defn, "warpc_cap_adjust", False),
                             weapon_cap_adjust=getattr(defn, "weapon_cap_adjust", False))
    if cd is None:
        return False

    # Phase 6: 优先使用 CaveLayout 解析的偏移; 旧模式回退到 defn.cave_offset
    cave_offset = getattr(defn, "_resolved_cave_offset", defn.cave_offset)

    # Phase 2: Cave 越界硬校验 — 防止 .tkspatch 声明超出 budget 的 offset/size
    cave_budget = settings.cave_total_size
    if not _check_cave_bounds(cave_addr, cave_offset, len(cd),
                              cave_budget, defn.id, log):
        return False

    ct = cave_addr + cave_offset
    write_pm(h_proc, ct, cd)
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")

    ptd = 0
    for off in hits:
        hook_off = off + defn.hook_offset
        if (hook_off < 0 or defn.hook_size <= 0 or
                hook_off + defn.hook_size > len(code_buf)):
            log(f"  [FAIL] {defn.id}: hook 写入越界 (RVA 0x{hook_off:X}, size={defn.hook_size})")
            continue
        ha = code_start_addr + hook_off
        co = (ct - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(defn.hook_size)
        ci[0] = 0xE8
        ci[1:5] = struct.pack('<I', co)
        for i in range(5, defn.hook_size):
            ci[i] = 0x90

        op = vp_ex(h_proc, ha, defn.hook_size, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, defn.hook_size, op)

        for i in range(min(defn.hook_size, len(code_buf) - hook_off)):
            code_buf[hook_off + i] = ci[i]

        log(f"    [OK] Hook RVA 0x{hook_off:X} -> call 0x{ct:08X}")
        ptd += 1

    return ptd > 0

# ============================================================
# 补丁类型: patch_summon_table (召唤表自定义)
# 逆向依据: sub_444BB0 召唤角色选择; stru_4EB6F0 区域 .data 8字节 (技能224~231)
#           + sub_444BB0 内 3 处 imm16 立即数 (技能222/251_a/251_b)
# JSON 值为 WarPC 索引 (= i+36), 写入时换算 i = WarPC-36
# ============================================================

def apply_summon_table(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                       base_addr: int, h_proc: int, settings: PatchSettings,
                       runtime: PatchRuntimeState,
                       log_func=None, cave_addr: int = 0,
                       config_override: Optional[dict] = None) -> bool:
    log = log_func or (lambda x: None)
    all_ok = True

    # Step 0: 读取召唤表 JSON
    # 优先使用 MOD 包提供的配置覆盖 (白名单内), 否则回退到 configs/ 目录
    if config_override is not None:
        summon = config_override
        log(f"    JSON (MOD 覆盖): {len(summon)} 个键")
    else:
        if not defn.json_file or not os.path.isfile(defn.json_file):
            log(f"    [WARN] 召唤表 JSON 不存在: {defn.json_file!r}, 跳过")
            return True
        try:
            with open(defn.json_file, 'r', encoding='utf-8') as f:
                summon = json.load(f)
        except Exception as e:
            log(f"  [ERROR] 解析召唤表 JSON 失败: {e}")
            return False
        log(f"    JSON: {len(summon)} 个键")

    # Step 1: WarPC 记录数上限 (用于值域校验)
    rec_size = settings.warpc_rec_size
    new_size = runtime.warpc_new_size or 150722
    max_count = new_size // rec_size if rec_size > 0 else 143

    def _warpc_i(warpc_idx, imm16):
        if not isinstance(warpc_idx, (int,)):
            return None, f"非整数: {warpc_idx!r}"
        if warpc_idx < 36 or warpc_idx >= max_count:
            return None, f"WarPC索引 {warpc_idx} 越界 (36..{max_count-1})"
        i = warpc_idx - 36
        limit = 65535 if imm16 else 255
        if i < 0 or i > limit:
            return None, f"i值 {i} 越界 (0..{limit})"
        return i, None

    # Step 2: 写 .data 8 字节 (技能 224~231) — .data 段通常 PAGE_READWRITE
    if defn.data_rva and defn.data_keys:
        tbl_abs = base_addr + defn.data_rva
        tbl_off = defn.data_rva - 0x1000
        if tbl_off < 0 or tbl_off + 8 > len(code_buf):
            log(f"  [ERROR] .data 偏移越界")
            all_ok = False
        else:
            cur = bytearray(code_buf[tbl_off:tbl_off + 8])
            changed = False
            for k, key in enumerate(defn.data_keys):
                if key not in summon:
                    continue
                i, err = _warpc_i(summon[key], imm16=False)
                if err:
                    log(f"    [WARN] {key}: {err}, 跳过")
                    continue
                if cur[k] != (i & 0xFF):
                    log(f"    {key}: i {cur[k]}->{i & 0xFF} (WarPC {cur[k]+36}->{summon[key]})")
                    changed = True
                cur[k] = i & 0xFF
            if changed:
                nw = write_pm(h_proc, tbl_abs, bytes(cur))
                code_buf[tbl_off:tbl_off + 8] = bytes(cur)
                log(f"    [OK] .data @0x{tbl_abs:08X} 写入{nw}/{len(cur)}字节")
                if nw != len(cur):
                    all_ok = False
            else:
                log(f"    -> .data 与默认值一致")

    # Step 3: 写代码段 imm16 — 使用独立句柄确保写入成功
    _pid = runtime.target_pid
    if not _pid:
        log("  [WARN] 缺少 target_pid, 跳过 imm16 补丁")
        return all_ok
    _hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                        False, _pid)
    if not _hp:
        log(f"  [WARN] OpenProcess(PID={_pid}) 失败, 跳过 imm16 补丁")
        return all_ok

    for site in defn.code_addrs:
        key = site.get("key", "")
        rva_str = site.get("rva", "")
        if not key or not rva_str:
            continue
        rva = int(rva_str, 16) if isinstance(rva_str, str) else int(rva_str)
        abs_addr = base_addr + rva
        if key not in summon:
            continue
        # 安全校验: code_addrs 指向 `mov word[ebp-2], imm16` (66 C7 45 FE ..) 的 imm16 操作数。
        # 第三方 MOD (如孝谈三国3终极版) 可能已把该指令整条替换为 JMP cave (E9 rel32),
        # 此时盲写 imm16 会覆盖 JMP 的相对偏移, 破坏 MOD 跳转目标导致崩溃。
        # 仅当目标前导字节确为该 mov 指令时才写入, 否则跳过 (版本无关, 对原版无副作用)。
        _goff = abs_addr - code_start_addr
        if not (4 <= _goff and _goff + 2 <= len(code_buf)
                and bytes(code_buf[_goff - 4:_goff]) == b"\x66\xC7\x45\xFE"):
            log(f"    [SKIP] {key}: @0x{abs_addr:08X} 非 mov word[ebp-2],imm16 "
                f"(疑似已被 MOD 改为 JMP cave), 跳过盲写以避免破坏 MOD")
            continue
        i, err = _warpc_i(summon[key], imm16=True)
        if err:
            log(f"    [WARN] {key}: {err}, 跳过")
            continue
        imm = i16b(i)
        nw = write_pm(_hp, abs_addr, imm)
        if nw == 2:
            log(f"    [OK] {key} i={i} @abs 0x{abs_addr:08X}")
        else:
            log(f"  [FAIL] {key}: WriteProcessMemory 失败 @abs 0x{abs_addr:08X}")
            all_ok = False
        cb_off = abs_addr - code_start_addr
        if 0 <= cb_off + 2 <= len(code_buf):
            code_buf[cb_off:cb_off + 2] = imm

    # Step 4: 多随机 cave 注入 (skill_224~231 的 *_random 列表)
    # 复用 Step 3 句柄 _hp (确保随机 cave 写入成功)
    # data_keys 顺序 = entry 顺序 (224~231 -> entry 0~7); 列表键名 = data_keys[k] + "_random"
    rnd_pat_str = defn.random_hook_pattern
    if rnd_pat_str and defn.random_cave_offset and defn.random_table_offset:
        if not cave_addr:
            log("  [WARN] 无 cave 内存, 跳过多随机注入")
        else:
            all_ok &= _apply_summon_random(defn, summon, code_buf, code_start_addr,
                                            _hp, cave_addr, _warpc_i, log,
                                            cave_budget=settings.cave_total_size)

    _CloseHandle(_hp)
    return all_ok


def _apply_summon_random(defn: PatchDef, summon: dict, code_buf: bytearray,
                         code_start_addr: int, h_proc: int, cave_addr: int,
                         warpc_i_fn, log_func=None,
                         cave_budget: int = 2048) -> bool:
    """多随机 cave: 读 *_random 列表 -> 90字节候选表 + cave代码 + hooks
    224~231 (entry 0~7, entry_224 cave, hook 0x444C84, 结果->edx)
    222 (entry 8, 合并 cave entry_222, hook 0x444C9C, 结果->[ebp-2])
    251 (entry 9, 合并 cave entry_251, hook 0x444CB3, 结果->[ebp-2])"""
    log = log_func or (lambda x: None)

    # Phase 6: 优先使用 CaveLayout 解析的偏移; 旧模式回退到 defn.<key>
    _ro = lambda k: getattr(defn, f"_resolved_{k}", getattr(defn, k, 0))

    # 外置 cave 代码必须 (.tkspatch 提供; 引擎已不内置模板)
    from .tkspatch_loader import _parse_hex_bytes
    _extra = getattr(defn, '_extra', {})
    _ext_cave1 = _parse_hex_bytes(_extra.get('summon_cave_code', '')) if _extra.get('summon_cave_code') else None
    _ext_cave2 = _parse_hex_bytes(_extra.get('summon_cave2_code', '')) if _extra.get('summon_cave2_code') else None
    if not _ext_cave1 or not _ext_cave2:
        log("  [FAIL] 缺少外置 summon_cave_code/summon_cave2_code, 跳过多随机注入")
        return False
    _cave_summon_random = _ext_cave1
    _cave_summon_222_251 = _ext_cave2

    # Phase 2: Cave 越界硬校验 — 在分配前一次性检查三块偏移 (尺寸按外置代码实际长度)
    if cave_addr:
        for off_key, size in [("random_table_offset", 90),
                              ("random_cave_offset", len(_cave_summon_random)),
                              ("random2_cave_offset", len(_cave_summon_222_251))]:
            off = _ro(off_key)
            if not _check_cave_bounds(cave_addr, off, size, cave_budget,
                                      f"{defn.id}/{off_key}", log):
                return False

    # 4a. 收集候选列表 -> 90 字节候选表 (entry 0~7=224~231, 8=222, 9=251)
    table = bytearray(90)        # 10 entry x 9 字节
    any_random = False
    has_224 = False              # 224~231 任一配了 -> 需 224~231 cave+hook
    extra_hooks_to_apply = []    # 222/251 hooks: [{entry_idx, ...hook_cfg}]

    def collect(rkey, entry_idx):
        nonlocal any_random, has_224
        lst = summon.get(rkey)
        if not isinstance(lst, list) or not lst:
            return False
        if len(lst) > 8:
            log(f"    [WARN] {rkey}: 候选 {len(lst)} > 8, 截断为 8")
            lst = lst[:8]
        cand = []
        for w in lst:
            ii, err = warpc_i_fn(w, imm16=False)   # i 值域 0..255 (byte 存储)
            if err:
                log(f"    [WARN] {rkey}: WarPC {w} {err}, 跳过该技能随机")
                return False
            cand.append(ii & 0xFF)
        table[entry_idx * 9] = len(cand)
        for j, c in enumerate(cand):
            table[entry_idx * 9 + 1 + j] = c
        any_random = True
        log(f"    {rkey}: {len(cand)} 候选 i={cand} (WarPC={[c + 36 for c in cand]})")
        return True

    # 224~231 (entry 0~7)
    for k, key in enumerate(defn.data_keys):
        if collect(key + "_random", k):
            has_224 = True

    # 222 (entry 8) / 251 (entry 9), 按 random2_hooks 配置收集
    for hk in defn.random2_hooks:
        jkey = hk.get("json_key", "")
        eidx = hk.get("entry_idx", 0)
        if collect(jkey, eidx):
            extra_hooks_to_apply.append(hk)

    if not any_random:
        log("    -> 无 *_random 配置, 跳过多随机 cave")
        return True

    # 4b. 写 90 字节候选表 (Phase 6: 优先 _resolved_random_table_offset)
    table_abs = cave_addr + _ro("random_table_offset")
    if write_pm(h_proc, table_abs, bytes(table)) != len(table):
        log(f"  [FAIL] 候选表写入失败 @0x{table_abs:08X}")
        return False
    log(f"    [OK] 候选表 @0x{table_abs:08X} (90 字节)")

    all_ok = True

    # 4c. 224~231: entry_224 cave + hook 0x444C84 (结果->edx, 由原 mov[ebp-2],dx 写回)
    if has_224:
        all_ok &= _write_cave_and_hook(
            _cave_summon_random, _ro("random_cave_offset"), 0,           # cave 代码, 入口偏移 0
            defn.random_hook_pattern, defn.random_hook_size, defn.random_hook_expect_count,
            table_abs, code_buf, code_start_addr, h_proc, cave_addr,
            warpc_i_fn, log, tag="224~231")

    # 4d. 222/251: 合并 cave (entry_222+entry_251+shared) + 各 hook
    if extra_hooks_to_apply:
        cave2_abs = cave_addr + _ro("random2_cave_offset")
        cave2_code = bytearray(_cave_summon_222_251)
        if cave2_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] 222/251 cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave2_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        if write_pm(h_proc, cave2_abs, bytes(cave2_code)) != len(cave2_code):
            log(f"  [FAIL] 222/251 cave 代码写入失败 @0x{cave2_abs:08X}")
            return False
        log(f"    [OK] 222/251 cave @0x{cave2_abs:08X} ({len(cave2_code)} 字节)")
        for hk in extra_hooks_to_apply:
            all_ok &= _write_cave_and_hook(
                None, _ro("random2_cave_offset"), hk.get("entry_offset", 0),  # 复用已写 cave, 仅 hook
                hk.get("pattern", ""), hk.get("hook_size", 0), hk.get("expect_count", 0),
                table_abs, code_buf, code_start_addr, h_proc, cave_addr,
                warpc_i_fn, log, tag=hk.get("json_key", ""),
                prewritten_cave_abs=cave2_abs)

    return all_ok


def _write_cave_and_hook(cave_template: Optional[bytes], cave_offset: int, entry_offset: int,
                         hook_pattern: str, hook_size: int, expect_count: int,
                         table_abs: int, code_buf: bytearray, code_start_addr: int,
                         h_proc: int, cave_addr: int, warpc_i_fn, log_func,
                         tag: str = "", prewritten_cave_abs: int = 0) -> bool:
    """写 cave 代码 (若提供 template) + 写 hook. cave 入口 = cave_addr+cave_offset+entry_offset.
    prewritten_cave_abs>0 时跳过 cave 写入 (复用已写代码), 仅写 hook 指向该地址+entry_offset."""
    log = log_func or (lambda x: None)

    # 写 cave 代码 (224~231); 222/251 复用已写合并代码
    if cave_template is not None:
        cave_code = bytearray(cave_template)
        if cave_code.count(SUMMON_RANDOM_PLACEHOLDER.to_bytes(4, 'little')) != 1:
            log(f"  [ERROR] [{tag}] cave 占位符次数异常, 中止")
            return False
        replace_addr_in_bytes(cave_code, SUMMON_RANDOM_PLACEHOLDER, table_abs)
        cave_abs = cave_addr + cave_offset
        if write_pm(h_proc, cave_abs, bytes(cave_code)) != len(cave_code):
            log(f"  [FAIL] [{tag}] cave 代码写入失败 @0x{cave_abs:08X}")
            return False
        log(f"    [OK] [{tag}] cave 代码 @0x{cave_abs:08X} ({len(cave_code)} 字节, TABLE_BASE->0x{table_abs:08X})")
    else:
        cave_abs = prewritten_cave_abs

    hook_target = cave_abs + entry_offset   # call 目标 (222/251 为合并 cave 内入口)

    # 写 hook: E8 rel32 + NOP 填充
    if not hook_pattern or not hook_size:
        log(f"  [WARN] [{tag}] 无 hook 配置, 跳过")
        return True
    pat, wc = parse_pattern(hook_pattern)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    if expect_count > 0 and len(hits) != expect_count:
        log(f"  [WARN] [{tag}] hook 匹配 {len(hits)} 处 (预期 {expect_count}), 跳过")
        return False
    if not hits:
        log(f"  [WARN] [{tag}] hook 模式无匹配, 跳过")
        return False

    hsz = hook_size
    for off in hits:
        ha = code_start_addr + off
        co = (hook_target - (ha + 5)) & 0xFFFFFFFF
        ci = bytearray(hsz)
        ci[0] = 0xE8
        ci[1:5] = i32b(co)
        for i in range(5, hsz):
            ci[i] = 0x90
        op = vp_ex(h_proc, ha, hsz, PAGE_EXECUTE_READWRITE)
        nw = write_pm(h_proc, ha, bytes(ci))
        vp_ex(h_proc, ha, hsz, op)
        if nw != hsz:
            log(f"  [FAIL] [{tag}] hook 写入失败 @RVA 0x{off:X}")
            return False
        for i in range(min(hsz, len(code_buf) - off)):
            code_buf[off + i] = ci[i]
        log(f"    [OK] [{tag}] hook @RVA 0x{off:X} (abs 0x{ha:08X}) -> cave 0x{hook_target:08X}")
    return True

# ============================================================
# 补丁类型: patch_drop_probability (物品掉落概率自定义)
# 逆向依据: sub_4400DC @ VA 0x441A24/0x441A97 (Path A 死亡掉落结算)
#
# Path A (sub_4400DC) 是实际的怪物死亡掉落结算, 在攻击动画期间运行:
#   触发条件: HP<=伤害, attacker_type==100(玩家), monster_type<10(敌人)
#   概率结构 (独立判定, 非互斥):
#     常规槽 word_9D7296: 非空且 cnt<64 → 必掉 (无随机检查, 100%)
#     普通槽 word_9D7298: 非空且 rand(1000)<200 (20%) 且 cnt<64 → 掉落 → jnb 跳过
#     稀有槽 word_9D729A: 非空且 rand(1000)<50  (5%)  且 cnt<64 → 掉落 → jnb 跳过
#   不清零槽位, 无物品查询/显示 (sub_42F8D4/sub_434188)
#
# 字节补丁策略 (不用 cave — 原版流程已正常工作):
#   常规槽: 已是 100%, 无法在不插入指令的情况下配置 (无随机检查点)
#   普通槽: 修改 0x41A2F 处的 cmp ax, 0xC8 (200) imm16 → pct*10
#   稀有槽: 修改 0x41AA2 处的 cmp ax, 0x32 (50, imm8 形式) → cmp ax, imm16 (同长度 4 字节)
#   JNB 指令保持原样 — 如果 rand < threshold 则跳过, 否则掉落
#   级联模式: 不支持 (原版 Path A 是独立结构, 不是级联)
# ============================================================

def apply_drop_probability(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                           h_proc: int, log_func=None,
                           config_override: Optional[dict] = None) -> bool:
    log = log_func or (lambda x: None)
    tag = f"[{defn.id}]"
    log(f"\n  {tag}: {defn.desc}")

    # 1. 读取 JSON 配置
    # 优先使用 MOD 包提供的配置覆盖 (白名单内), 否则回退到 configs/ 目录
    if config_override is not None:
        cfg = config_override
        log(f"    JSON (MOD 覆盖)")
    else:
        jf = defn.json_file
        if not jf or not os.path.isfile(jf):
            log(f"    [WARN] JSON 配置不存在: {jf!r}, 跳过")
            return True
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception as e:
            log(f"  [ERROR] 解析 drop_probability.json 失败: {e}")
            return True

    mode = cfg.get("mode", "independent")
    if mode == "cascade":
        log(f"    [WARN] cascade 模式需要代码重构, Path A 不支持级联. 使用 independent 模式代替.")
        mode = "independent"

    # 2. 验证百分值
    rare_pct = int(cfg.get("rare_pct", 100))
    normal_pct = int(cfg.get("normal_pct", 100))
    regular_pct = int(cfg.get("regular_pct", 100))
    for name, val in [("rare", rare_pct), ("normal", normal_pct), ("regular", regular_pct)]:
        if val < 0 or val > 100:
            log(f"  [ERROR] {name}_pct={val} 超出 0~100")
            return True

    log(f"    normal={normal_pct}%, rare={rare_pct}% (常规槽原版无随机, 100%不可降)")

    # 3. 构建补丁列表
    #    每个补丁: (rva, expected_bytes, new_bytes)
    patches = []

    # 普通槽阈值: VA 0x441A2F → RVA 0x41A2F, 原: 66 3D C8 00 (cmp ax, 0xC8=200)
    # sub_452AC0(1000) → [0, 999]. 跌落条件: rand(1000) < threshold. jnb 跳过.
    # 对于 pct%: threshold = pct * 10. 对于 100%: threshold=1000 (0x3E8), rand<1000 始终成立.
    norm_rva = 0x41A2F
    old_norm = bytes([0x66, 0x3D, 0xC8, 0x00])
    new_norm = bytes([0x66, 0x3D, (normal_pct * 10) & 0xFF, ((normal_pct * 10) >> 8) & 0xFF])
    patches.append((norm_rva, old_norm, new_norm))

    # 稀有槽阈值: VA 0x441AA2 → RVA 0x41AA2, 原: 66 83 F8 32 (cmp ax, imm8 0x32=50)
    # 替换为同长 4 字节的 imm16 形式: 66 3D XX XX (cmp ax, imm16)
    rare_rva = 0x41AA2
    old_rare = bytes([0x66, 0x83, 0xF8, 0x32])
    new_rare = bytes([0x66, 0x3D, (rare_pct * 10) & 0xFF, ((rare_pct * 10) >> 8) & 0xFF])
    patches.append((rare_rva, old_rare, new_rare))

    # 4. 应用字节补丁
    all_ok = True
    for rva, expected, new_bytes in patches:
        hook_off = rva - 0x1000
        if hook_off < 0 or hook_off + len(expected) > len(code_buf):
            log(f"    [ERROR] RVA 0x{rva:X} 越界")
            all_ok = False
            continue
        actual = bytes(code_buf[hook_off:hook_off + len(expected)])
        log(f"    验证 0x{rva:X}: code_buf={actual.hex()} (期望 {expected.hex()})")
        if actual != expected:
            log(f"    [ERROR] 字节不匹配! 可能已被其他 MOD 修改或版本不对, 跳过")
            continue

        ha = code_start_addr + hook_off
        verify_buf, nread = read_pm(h_proc, ha, len(expected))
        if nread == len(expected) and verify_buf != expected:
            log(f"    [ERROR] 进程内存与 code_buf 不一致, 跳过")
            continue

        op = vp_ex(h_proc, ha, len(new_bytes), PAGE_EXECUTE_READWRITE)
        nw = write_pm(h_proc, ha, new_bytes)
        vp_ex(h_proc, ha, len(new_bytes), op)
        if nw == len(new_bytes):
            log(f"    [OK] 0x{rva:X}: {expected.hex()} → {new_bytes.hex()} "
                f"(threshold={int.from_bytes(new_bytes[2:4],'little')})")
            code_buf[hook_off:hook_off + len(new_bytes)] = new_bytes
        else:
            log(f"  [FAIL] 写入失败 @ 0x{ha:08X}")
            all_ok = False

    return all_ok

# ============================================================
# 补丁类型: patch_exp_lock (战斗经验锁定 / 压级)
# 逆向依据: sub_43B7FC @0x43BAF3 (读取 v11=*v19); cave 机器码外置于 patch.json
# 配置: configs/exp_lock.json -> lock_slots[6] (bool); mask = Σ 1<<i (locked)
# ============================================================

def apply_exp_lock(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                   h_proc: int, cave_addr: int, log_func=None,
                   config_override: Optional[dict] = None,
                   cave_budget: int = 2048) -> bool:
    log = log_func or (lambda x: None)

    if cave_addr == 0:
        log(f"    [SKIP] Cave 未分配, 跳过")
        return True

    # 1. 读取 JSON 配置 (优先 MOD 覆盖)
    if config_override is not None:
        cfg = config_override
        log(f"    JSON (MOD 覆盖)")
    else:
        jf = defn.json_file
        if not jf or not os.path.isfile(jf):
            log(f"    [WARN] JSON 配置不存在: {jf!r}, 跳过")
            return True
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception as e:
            log(f"  [ERROR] 解析 exp_lock.json 失败: {e}")
            return True

    # 2. 计算锁定掩码 (bit i = 锁定槽位 i)
    slots = cfg.get("lock_slots", [])
    mask = 0
    for i in range(6):
        if i < len(slots) and slots[i]:
            mask |= (1 << i)
    if mask == 0:
        log(f"    -> 无锁定槽位 (mask=0), 跳过 (等同原版)")
        return True
    locked = [i for i in range(6) if mask & (1 << i)]
    log(f"    锁定槽位掩码 = 0x{mask:02X} (槽位 {locked})")

    # 3. 模式扫描 hook 点 (失败回退 fallback_rva)
    hpat, hwc = parse_pattern(defn.hook_pattern or "")
    hits = pattern_scan(bytes(code_buf), hpat, hwc)
    if defn.hook_expect_count > 0 and len(hits) != defn.hook_expect_count:
        if len(hits) == 0 and defn.fallback_rva > 0:
            fb_off = defn.fallback_rva - 0x1000
            if 0 <= fb_off < len(code_buf) - defn.hook_size:
                hits = [fb_off]
                log(f"    模式无匹配, 使用 fallback_rva 0x{defn.fallback_rva:X} (offset 0x{fb_off:X})")
            else:
                log(f"    fallback_rva 0x{defn.fallback_rva:X} 越界, 跳过")
                return True
        else:
            log(f"    Hook 模式匹配 {len(hits)} 处 (预期 {defn.hook_expect_count}), 跳过")
            return True

    # 4. 构建 cave (写入掩码 imm8) 并写到 cave 区
    # cave 机器码外置于 patch.json (引擎已不内置模板)
    ext_cave = getattr(defn, '_cave_code_bytes', None)
    if ext_cave is None:
        log(f"  [FAIL] exp_lock: 缺少外置 cave_code, 无法应用")
        return False
    cd = bytearray(ext_cave)
    # 从 _extra 获取掩码偏移 (patch.json cave_mask_offset), 默认 10 (与原内置模板同位)
    mask_off = getattr(defn, '_extra', {}).get('cave_mask_offset', 10)
    cd[mask_off] = mask & 0xFF
    # Phase 6: 优先使用 CaveLayout 解析的偏移
    cave_offset = getattr(defn, "_resolved_cave_offset", defn.cave_offset)
    # Phase 2: Cave 越界硬校验
    if not _check_cave_bounds(cave_addr, cave_offset, len(cd),
                              cave_budget, defn.id, log):
        return True
    ct = cave_addr + cave_offset
    write_pm(h_proc, ct, bytes(cd))
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, mask=0x{mask:02X})")

    # 5. 安装 hook (E8 rel32 + NOP 填充)
    off = hits[0]
    ha = code_start_addr + off
    co = (ct - (ha + 5)) & 0xFFFFFFFF
    ci = bytearray(defn.hook_size)
    ci[0] = 0xE8
    ci[1:5] = i32b(co)
    for i in range(5, defn.hook_size):
        ci[i] = 0x90
    op = vp_ex(h_proc, ha, defn.hook_size, PAGE_EXECUTE_READWRITE)
    write_pm(h_proc, ha, bytes(ci))
    vp_ex(h_proc, ha, defn.hook_size, op)
    for i in range(min(defn.hook_size, len(code_buf) - off)):
        code_buf[off + i] = ci[i]
    log(f"    [OK] Hook RVA 0x{off:X} -> call 0x{ct:08X}")
    return True

# ============================================================
# 补丁类型: patch_font_config (游戏默认字体自定义)
# 逆向依据: sub_411624 @0x411624 游戏启动时初始化全局渲染器
#   主文本渲染器 (dword_755B04): sub_44AF7C(v4, 1, 16, 1, 0, 1, 1)  — FTYPE=1, FSIZE=16
# sub_44AF7C 的 a2 参数 = FTYPE_raw (0-7), 决定 FONT9696 区段索引
# 字节模式: 6A a7 6A a6 6A a5 6A a4 6A fsize 6A ftype 8B 15 [ptr32] 52 E8
#   push 序列 (右到左): a7,a6,a5,a4,FSIZE,FTYPE; FTYPE 字节在模式偏移 11
#
# 菜单人物名称字体: 扫描所有 dword_755B08 的 FTYPE=2 调用 (6种寄存器变体, 共9处)
#   涉及函数: sub_41762C/sub_418E5C/sub_4195C4/sub_41A080/sub_41AB94/sub_421B64/sub_4233C4
#   排除 sub_411624 初始化 (a6=0) 和 sub_4252E8 姓名输入 (a7=1,a6=1)
#
# 说明弹出框字体: 扫描所有 dword_755B08 的 FTYPE=0 调用 (6种寄存器变体, 共4处)
#   涉及函数: sub_4195C4(物品说明)/sub_418E5C(角色技能)/sub_41A080(技能/角色描述)
# ============================================================

def apply_font_config(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                      h_proc: int, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    tag = f"[{defn.id}]"
    log(f"\n  {tag}: {defn.desc}")

    # 1. 读取 JSON 配置
    jf = defn.json_file
    if not jf or not os.path.isfile(jf):
        log(f"    [WARN] JSON 配置不存在: {jf!r}, 跳过")
        return True
    try:
        with open(jf, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 font_config.json 失败: {e}")
        return True

    renderers = cfg.get("renderers", {})
    all_ok = True

    # 保存原始字节快照 — outline patch 会修改 a7 字节, FTYPE patch 的排除条件
    # 需要用原始 a7/a6 值判断, 否则恢复态被 outline 改 a7 后会误判为姓名输入
    orig_code_buf = bytes(code_buf)

    # 1b. 描边 (outline) 处理 — 必须在 FTYPE 处理之前
    # a7 是 sub_44AF7C 的第 7 个参数 (存储在渲染器 offset+64), 1=启用描边, 0=禁用描边
    # 描边通过位图膨胀算法实现: 将字体位图向右下各膨胀2像素, 先用描边色(黑色)绘制, 再用前景色绘制
    # 修改对应渲染器所有调用点的 a7 字节为配置值
    # 在 FTYPE 处理之前执行, 以便用原始 FTYPE 值区分 menu_name_font(FTYPE=2) 和 tooltip_font(FTYPE=0)
    _OUTLINE_CONFIGS = [
        ("main",           0x04, None, False),  # dword_755B04, 不限定 FTYPE, 不排除
        ("menu_name_font", 0x08, 2,    True),   # dword_755B08, FTYPE=2, 排除 init/姓名输入
        ("tooltip_font",   0x08, 0,    False),  # dword_755B08, FTYPE=0, 不排除
    ]
    for rname, ptr_byte, orig_ftype, exclude_special in _OUTLINE_CONFIGS:
        rc = renderers.get(rname, {})
        outline = rc.get("outline", None)
        if outline is None:
            continue
        outline = int(outline)
        if outline not in (0, 1):
            log(f"    [ERROR] {rname} outline: value={outline} 超出 0~1")
            all_ok = False
            continue

        ft = f"{orig_ftype:02X}" if orig_ftype is not None else "??"
        ptr = f"{ptr_byte:02X} 5B 75 00"
        # 6种寄存器变体: (模式, a7偏移, a6偏移)
        outline_variants = [
            (f"8B 15 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 52 E8", 7, 9),
            (f"6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 15 {ptr} 52 E8", 1, 3),
            (f"A1 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 50 E8", 6, 8),
            (f"6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} A1 {ptr} 50 E8", 1, 3),
            (f"8B 0D {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 51 E8", 7, 9),
            (f"6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 0D {ptr} 51 E8", 1, 3),
        ]
        patched = 0
        for pat_str, a7_off, a6_off in outline_variants:
            pat, wc = parse_pattern(pat_str)
            hits = pattern_scan(bytes(code_buf), pat, wc)
            for h in hits:
                # menu_name_font: 排除 init (a6=0) 和姓名输入 (a7=1,a6=1,非O1)
                if exclude_special:
                    a7_val = code_buf[h + a7_off]
                    a6_val = code_buf[h + a6_off]
                    if a6_val == 0:
                        continue
                    if a7_val == 1 and a6_val == 1 and not pat_str.startswith("8B 15"):
                        continue
                a7_foff = h + a7_off
                actual = code_buf[a7_foff]
                if actual == outline:
                    continue
                ha = code_start_addr + a7_foff
                op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
                write_pm(h_proc, ha, bytes([outline & 0xFF]))
                vp_ex(h_proc, ha, 1, op)
                code_buf[a7_foff] = outline & 0xFF
                patched += 1
                log(f"    [OK] {rname} outline: a7 {actual} -> {outline} @RVA 0x{a7_foff:X}")
        log(f"    {rname} outline: 共 patch {patched} 处 a7 调用")

    # 2. 主文本渲染器 (sub_411624 中 sub_44AF7C 调用点)
    #    模式: 6A a7 6A a6 6A a5 6A a4 6A FSIZE 6A FTYPE 8B 15 [ptr32] 52 E8
    #    FTYPE 字节在模式偏移 11; dword 指针唯一区分
    renderer_specs = {
        "main": {
            "pattern": "6A ?? 6A 01 6A 00 6A 01 6A 10 6A 01 8B 15 04 5B 75 00",
            "original_ftype": 1,
            "ptr": "dword_755B04",
        },
    }

    FTYPE_OFFSET = 11  # FTYPE 字节在模式中的偏移

    for name, spec in renderer_specs.items():
        rc = renderers.get(name, {})
        new_ftype = int(rc.get("ftype", spec["original_ftype"]))

        # 验证 FTYPE 值域 (sub_44AF7C: >7 会重置为 0)
        if new_ftype < 1 or new_ftype > 8:
            log(f"    [ERROR] {name}: ftype={new_ftype} 超出 1~8")
            all_ok = False
            continue

        if new_ftype > 7:
            log(f"    [WARN] {name}: ftype={new_ftype} > 7, sub_44AF7C 将重置为 0")

        # 与原始值相同则跳过
        if new_ftype == spec["original_ftype"]:
            log(f"    {name}: ftype={new_ftype} (与原始一致, 跳过)")
            continue

        # 扫描模式
        pat, wc = parse_pattern(spec["pattern"])
        hits = pattern_scan(bytes(code_buf), pat, wc)
        log(f"    {name} ({spec['ptr']}): 模式扫描 -> {len(hits)} 处 (预期 1)")
        if len(hits) != 1:
            log(f"    [ERROR] {name}: 匹配数 != 1, 跳过")
            all_ok = False
            continue

        off = hits[0]
        ftype_off = off + FTYPE_OFFSET

        # 验证当前值
        actual = code_buf[ftype_off]
        if actual != spec["original_ftype"]:
            log(f"    [WARN] {name}: 当前值 {actual} != 预期 {spec['original_ftype']} (可能已被修改)")

        # 写入新 FTYPE
        ha = code_start_addr + ftype_off
        op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
        write_pm(h_proc, ha, bytes([new_ftype & 0xFF]))
        vp_ex(h_proc, ha, 1, op)
        code_buf[ftype_off] = new_ftype & 0xFF

        log(f"    [OK] {name}: FTYPE {actual} -> {new_ftype} @RVA 0x{ftype_off:X}")

    # 3. 菜单人物名称字体 (dword_755B08 的 FTYPE=2 调用点)
    #    菜单重绘路径中, 多个函数会调用 sub_44AF7C(dword_755B08, 2, 24, 1, 0, 1, 0) 设置/恢复 FTYPE=2。
    #    若只 patch sub_41762C, 鼠标移动触发其他函数重绘时 FTYPE 会被恢复回 2。
    #    方案: 扫描所有 FTYPE=2 + dword_755B08 的 sub_44AF7C 调用 (6种寄存器变体),
    #          排除 sub_411624 初始化 (a6=0) 和 sub_4252E8 姓名输入 (a7=1,a6=1),
    #          将剩余调用的 FTYPE 从 2 改为新值。
    #
    #    涉及 9 处调用点 (2处设置 + 7处恢复):
    #      sub_41762C 第30行 (设置)   sub_41762C 第71行 (恢复)
    #      sub_418E5C 第20行 (恢复)   sub_4195C4 第34行 (恢复)
    #      sub_41A080 第96行 (恢复)   sub_41A080 第107行 (恢复)
    #      sub_41AB94 第20行 (恢复)   sub_421B64 第11行 (恢复)
    #      sub_4233C4 第17行 (恢复)
    #
    #    6种寄存器变体 (mov edx/eax/ecx 在 push 序列前或后):
    #      O1: 8B 15 [ptr] 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 52 E8  (FTYPE@17, a7@7, a6@9)
    #      O2: 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 8B 15 [ptr] 52 E8  (FTYPE@11, a7@1, a6@3)
    #      O3: A1 [ptr] 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 50 E8      (FTYPE@16, a7@6, a6@8)
    #      O4: 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 A1 [ptr] 50 E8      (FTYPE@11, a7@1, a6@3)
    #      O5: 8B 0D [ptr] 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 51 E8  (FTYPE@17, a7@7, a6@9)
    #      O6: 6A a7 6A a6 6A a5 6A a4 6A 18 6A 02 8B 0D [ptr] 51 E8  (FTYPE@11, a7@1, a6@3)
    menu_rc = renderers.get("menu_name_font", {})
    menu_ftype = int(menu_rc.get("ftype", 2))

    if menu_ftype != 2:  # 2 是原始值, 不需要修改
        # 验证 FTYPE 值域
        if menu_ftype < 0 or menu_ftype > 7:
            log(f"    [ERROR] menu_name_font: ftype={menu_ftype} 超出 0~7")
            all_ok = False
        else:
            # 6种寄存器变体: (模式, FTYPE偏移, a7偏移, a6偏移)
            variants = [
                ("8B 15 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 52 E8", 17, 7, 9),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 8B 15 08 5B 75 00 52 E8", 11, 1, 3),
                ("A1 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 50 E8", 16, 6, 8),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 A1 08 5B 75 00 50 E8", 11, 1, 3),
                ("8B 0D 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 51 E8", 17, 7, 9),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 8B 0D 08 5B 75 00 51 E8", 11, 1, 3),
            ]

            patched_count = 0
            for pat_str, ftype_off, a7_off, a6_off in variants:
                pat, wc = parse_pattern(pat_str)
                hits = pattern_scan(bytes(code_buf), pat, wc)
                for h in hits:
                    # 用原始快照判断排除条件 — outline patch 可能已修改 a7 字节
                    a7_val = orig_code_buf[h + a7_off]
                    a6_val = orig_code_buf[h + a6_off]
                    # 排除 sub_411624 初始化 (a6=0) 和 sub_4252E8 姓名输入 (a7=1,a6=1)
                    if a6_val == 0:
                        continue
                    if a7_val == 1 and a6_val == 1:
                        # sub_41762C 第30行 (设置) 需要 patch; sub_4252E8 (姓名输入) 跳过
                        # sub_41762C 第30行是 O1 变体且全局唯一, sub_4252E8 是 O2 变体
                        # 通过变体区分: O1 (mov edx before) = sub_41762C 第30行
                        if not pat_str.startswith("8B 15"):
                            continue

                    foff = h + ftype_off
                    actual = code_buf[foff]
                    if actual != 2:
                        log(f"    [WARN] menu_name_font: 当前值 {actual} != 预期 2 @RVA 0x{foff:X}")

                    ha = code_start_addr + foff
                    op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
                    write_pm(h_proc, ha, bytes([menu_ftype & 0xFF]))
                    vp_ex(h_proc, ha, 1, op)
                    code_buf[foff] = menu_ftype & 0xFF
                    patched_count += 1
                    log(f"    [OK] menu_name_font: FTYPE {actual} -> {menu_ftype} @RVA 0x{foff:X}")

            log(f"    menu_name_font: 共 patch {patched_count} 处 FTYPE=2 调用 (预期 9)")

    # 4. 物品/技能/角色说明弹出框字体 (dword_755B08 的 FTYPE=0 调用点)
    #    弹出框浮在画面上, 跟随鼠标位置, 背景为精灵158。
    #    涉及4处 FTYPE=0 调用 (FSIZE=16):
    #      sub_4195C4 第22行 (物品说明), sub_418E5C 第17行 (角色技能)
    #      sub_41A080 第75行 (技能描述), sub_41A080 第103行 (角色描述)
    #    扫描6种寄存器变体, 将 FTYPE 从 0 改为新值。
    tooltip_rc = renderers.get("tooltip_font", {})
    tooltip_ftype = int(tooltip_rc.get("ftype", 0))

    if tooltip_ftype != 0:  # 0 是原始值, 不需要修改
        # 验证 FTYPE 值域
        if tooltip_ftype < 0 or tooltip_ftype > 7:
            log(f"    [ERROR] tooltip_font: ftype={tooltip_ftype} 超出 0~7")
            all_ok = False
        else:
            # 6种寄存器变体: (模式, FTYPE偏移, a7偏移, a6偏移)
            # FSIZE=16 (0x10), FTYPE=0 (0x00)
            tooltip_variants = [
                ("8B 15 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 52 E8", 17, 7, 9),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 8B 15 08 5B 75 00 52 E8", 11, 1, 3),
                ("A1 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 50 E8", 16, 6, 8),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 A1 08 5B 75 00 50 E8", 11, 1, 3),
                ("8B 0D 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 51 E8", 17, 7, 9),
                ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 8B 0D 08 5B 75 00 51 E8", 11, 1, 3),
            ]

            tooltip_patched_count = 0
            for pat_str, ftype_off, a7_off, a6_off in tooltip_variants:
                pat, wc = parse_pattern(pat_str)
                hits = pattern_scan(bytes(code_buf), pat, wc)
                for h in hits:
                    foff = h + ftype_off
                    actual = code_buf[foff]
                    if actual != 0:
                        log(f"    [WARN] tooltip_font: 当前值 {actual} != 预期 0 @RVA 0x{foff:X}")

                    ha = code_start_addr + foff
                    op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
                    write_pm(h_proc, ha, bytes([tooltip_ftype & 0xFF]))
                    vp_ex(h_proc, ha, 1, op)
                    code_buf[foff] = tooltip_ftype & 0xFF
                    tooltip_patched_count += 1
                    log(f"    [OK] tooltip_font: FTYPE {actual} -> {tooltip_ftype} @RVA 0x{foff:X}")

            log(f"    tooltip_font: 共 patch {tooltip_patched_count} 处 FTYPE=0 调用 (预期 4)")

    return all_ok

# ============================================================
# 补丁类型: patch_animation_speed (动画/移动速度自定义)
# 支持5类独立调整: 状态/攻击(技能)/移动/待机 战斗动画 + 剧情地图移动
#
# 逆向依据:
# 1. 状态动画: 6个函数硬编码 0x3C (60ms)
#    sub_433690/sub_433A38/sub_43339C/sub_434188/sub_434D7C/sub_445564
# 2. 攻击+技能动画: sub_4434BC 使用 v30+60 变量延迟
#    (技能动画通过 sub_447DAC→sub_4458B0→sub_4434BC 调用,与攻击共用)
# 3. 移动动画: sub_43DE90 硬编码 0x3C (60ms)
# 4. 待机动画: sub_43CA64 战场主循环帧率, 硬编码 0x3C (60ms)
#    (待机动画在战场主循环中持续播放)
# 5. 剧情地图移动: sub_412BE8 剧情地图主循环帧节流, 硬编码 0x3C (60ms/帧≈16.7fps)
#    实体更新(sub_409618)与渲染每帧节流一次, 主角按格移动, 速度与帧率成正比
#
# 通用 pattern: 2B C? 83 F8 3C (sub eax,reg; cmp eax, 0x3C)
# 用函数地址范围过滤,只修改目标函数中的 0x3C
# ============================================================

# 状态动画函数列表 (6个)
_STATUS_ANIM_FUNCS = [
    (0x43339C, "sub_43339C"),
    (0x433690, "sub_433690"),
    (0x433A38, "sub_433A38"),
    (0x434188, "sub_434188"),
    (0x434D7C, "sub_434D7C"),
    (0x445564, "sub_445564"),
]

# 移动动画函数 (1个)
_MOVE_ANIM_FUNCS = [
    (0x43DE90, "sub_43DE90"),
]

# 待机动画函数 (战场主循环,1个)
_IDLE_ANIM_FUNCS = [
    (0x43CA64, "sub_43CA64"),
]


def _patch_frame_delay_3c(frame_delay: int, func_list, code_buf: bytearray,
                           code_start_addr: int, h_proc: int, log_func,
                           all_hits=None, search_range: int = 512) -> bool:
    """修改硬编码 0x3C (60ms) 帧延迟常量

    用通用 pattern `2B ?? 83 F8 3C` 扫描,再用函数地址范围过滤。
    返回是否全部修改成功。
    """
    log = log_func
    ORIG = 60

    if frame_delay == ORIG:
        return True  # 与原始一致,无需修改

    if not (1 <= frame_delay <= 127):
        log(f"    [ERROR] frame_delay_ms={frame_delay} 超出 1~127")
        return False

    # 扫描通用 pattern (若调用者已提供则复用)
    if all_hits is None:
        pat, wc = parse_pattern("2B ?? 83 F8 3C")
        all_hits = pattern_scan(bytes(code_buf), pat, wc)

    new_byte = frame_delay & 0xFF
    all_ok = True
    modified = 0

    for func_va, func_name in func_list:
        func_rva = func_va - code_start_addr
        func_end = func_rva + search_range
        found = False
        for hit in all_hits:
            if func_rva <= hit < func_end:
                off_3c = hit + 4
                actual = code_buf[off_3c]
                if actual != ORIG:
                    log(f"    [WARN] {func_name}: 偏移 0x{off_3c:X} 处值=0x{actual:02X} (预期 0x3C), 跳过")
                    continue
                ha = code_start_addr + off_3c
                op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
                write_pm(h_proc, ha, bytes([new_byte]))
                vp_ex(h_proc, ha, 1, op)
                code_buf[off_3c] = new_byte
                log(f"    [OK] {func_name}: {actual}ms -> {frame_delay}ms @RVA 0x{off_3c:X}")
                modified += 1
                found = True
                break
        if not found:
            log(f"    [ERROR] {func_name}: 未找到帧延迟常量, 跳过")
            all_ok = False

    log(f"    共修改 {modified}/{len(func_list)} 个函数")
    return all_ok


def _patch_attack_animation(cfg: dict, code_buf: bytearray, code_start_addr: int,
                             h_proc: int, log_func) -> bool:
    """修改 sub_4434BC 的 v30+60 变量延迟 (攻击+技能动画)

    技能动画通过 sub_447DAC→sub_4458B0→sub_4434BC 调用,因此与攻击共用同一帧延迟。

    三个可调常量:
    1. base_frame_delay (60ms): add edx, 0x3C 中的 0x3C
    2. extra_segment_delay (120ms): mov word[ebp-2Ah], 0x78 中的 0x78
    3. extra_delay_decrement (30ms): add word[ebp-2Ah], -30 中的 0xE2
    """
    log = log_func
    ORIG_BASE = 60
    ORIG_EXTRA = 120
    ORIG_DECR = 30

    base = int(cfg.get("base_frame_delay_ms", ORIG_BASE))
    extra = int(cfg.get("extra_segment_delay_ms", ORIG_EXTRA))
    decr = int(cfg.get("extra_delay_decrement_ms", ORIG_DECR))

    # 值域验证
    if not (1 <= base <= 255):
        log(f"    [ERROR] attack base_frame_delay_ms={base} 超出 1~255")
        return False
    if not (1 <= extra <= 32767):
        log(f"    [ERROR] attack extra_segment_delay_ms={extra} 超出 1~32767")
        return False
    if not (1 <= decr <= 128):
        log(f"    [ERROR] attack extra_delay_decrement_ms={decr} 超出 1~128")
        return False

    # 安全约束: extra 必须能被 decr 整除 (否则 v30 变负导致死循环卡死)
    if extra % decr != 0:
        log(f"    [ERROR] extra_segment_delay_ms({extra}) 必须能被 extra_delay_decrement_ms({decr}) 整除")
        log(f"            否则 v30 递减后变负, 无符号比较导致死循环卡死")
        return False

    all_ok = True

    # 1. base_frame_delay: 0F BF 55 D6 8B 0D D0 7C 4E 00 83 C2 3C (偏移12 = 0x3C)
    if base != ORIG_BASE:
        pat_str = "0F BF 55 D6 8B 0D D0 7C 4E 00 83 C2 3C"
        pat, wc = parse_pattern(pat_str)
        hits = pattern_scan(bytes(code_buf), pat, wc)
        if len(hits) != 1:
            log(f"    [ERROR] attack base_frame_delay: 匹配 {len(hits)} 处 (预期 1), 跳过")
            all_ok = False
        else:
            off = hits[0] + 12
            actual = code_buf[off]
            new_byte = base & 0xFF
            ha = code_start_addr + off
            op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
            write_pm(h_proc, ha, bytes([new_byte]))
            vp_ex(h_proc, ha, 1, op)
            code_buf[off] = new_byte
            log(f"    [OK] attack base_frame_delay: {actual}ms -> {base}ms @RVA 0x{off:X}")
    else:
        log(f"    attack base_frame_delay: {base}ms (与原始一致, 跳过)")

    # 2. extra_segment_delay: 66 C7 45 D6 78 00 (偏移4-5 = 78 00 = 120)
    if extra != ORIG_EXTRA:
        pat_str = "66 C7 45 D6 78 00"
        pat, wc = parse_pattern(pat_str)
        hits = pattern_scan(bytes(code_buf), pat, wc)
        if len(hits) != 1:
            log(f"    [ERROR] attack extra_segment_delay: 匹配 {len(hits)} 处 (预期 1), 跳过")
            all_ok = False
        else:
            off = hits[0] + 4
            new_word = struct.pack('<h', extra)
            actual = struct.unpack_from('<h', code_buf, off)[0]
            ha = code_start_addr + off
            op = vp_ex(h_proc, ha, 2, PAGE_EXECUTE_READWRITE)
            write_pm(h_proc, ha, new_word)
            vp_ex(h_proc, ha, 2, op)
            code_buf[off:off+2] = new_word
            log(f"    [OK] attack extra_segment_delay: {actual}ms -> {extra}ms @RVA 0x{off:X}")
    else:
        log(f"    attack extra_segment_delay: {extra}ms (与原始一致, 跳过)")

    # 3. extra_delay_decrement: 66 83 45 D6 E2 (偏移4 = 0xE2 = -30)
    if decr != ORIG_DECR:
        pat_str = "66 83 45 D6 E2"
        pat, wc = parse_pattern(pat_str)
        hits = pattern_scan(bytes(code_buf), pat, wc)
        if len(hits) != 1:
            log(f"    [ERROR] attack extra_delay_decrement: 匹配 {len(hits)} 处 (预期 1), 跳过")
            all_ok = False
        else:
            off = hits[0] + 4
            actual_signed = struct.unpack_from('<b', code_buf, off)[0]
            new_signed = -decr
            new_byte = struct.pack('<b', new_signed)
            ha = code_start_addr + off
            op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
            write_pm(h_proc, ha, new_byte)
            vp_ex(h_proc, ha, 1, op)
            code_buf[off] = new_byte[0]
            log(f"    [OK] attack extra_delay_decrement: {-actual_signed}ms -> {new_signed}ms @RVA 0x{off:X}")
    else:
        log(f"    attack extra_delay_decrement: {decr}ms (与原始一致, 跳过)")

    return all_ok


def _patch_map_movement(cfg: dict, code_buf: bytearray, code_start_addr: int,
                        h_proc: int, log_func) -> bool:
    """修改 sub_412BE8 剧情地图主循环的帧节流常量 (主角地图移动速度)

    剧情地图主循环以 GetTickCount 节流: 每帧等待 0x3C(60ms), 即地图模式约 16.7fps。
    主角/实体按格移动, 每帧推进一次, 移动速度与帧率成正比 → 减小帧延迟即加速移动。

    汇编形态 (sub_412BE8 @0x412E20, .text 段唯一命中):
        call j_GetTickCount
        mov  edx,[dword_4E7CD0]   ; 8B 15 D0 7C 4E 00
        sub  eax,edx              ; 2B C2
        cmp  eax,0x3C             ; 83 F8 3C
        jb   rel32                ; 0F 82 (do-while 近跳回循环体顶部)

    注意: 同函数内标题界面循环(0x412D4F)的节流为短跳转 jb rel8(72 EE),
    以 0F 82 近跳转特征区分, 只改剧情地图循环, 不影响标题界面。
    """
    log = log_func
    ORIG = 60

    frame_delay = int(cfg.get("frame_delay_ms", ORIG))
    if frame_delay == ORIG:
        log(f"    map_movement: {frame_delay}ms (与原始一致, 跳过)")
        return True

    if not (1 <= frame_delay <= 127):
        log(f"    [ERROR] map_movement frame_delay_ms={frame_delay} 超出 1~127")
        return False

    pat_str = "8B 15 D0 7C 4E 00 2B C2 83 F8 3C 0F 82"
    pat, wc = parse_pattern(pat_str)
    hits = pattern_scan(bytes(code_buf), pat, wc)
    if len(hits) == 0:
        log(f"    [WARN] map_movement: 特征码无匹配 (地图主循环已被 MOD 改写?), 跳过")
        return True
    if len(hits) != 1:
        log(f"    [ERROR] map_movement: 匹配 {len(hits)} 处 (预期 1), 跳过")
        return False

    off = hits[0] + 10  # 0x3C 立即数字节偏移 (8B 15 xx4 / 2B C2 xx2 / 83 F8 [3C])
    actual = code_buf[off]
    if actual != ORIG:
        log(f"    [WARN] map_movement: 偏移 0x{off:X} 处值=0x{actual:02X} (预期 0x3C), 跳过")
        return False

    new_byte = frame_delay & 0xFF
    ha = code_start_addr + off
    op = vp_ex(h_proc, ha, 1, PAGE_EXECUTE_READWRITE)
    write_pm(h_proc, ha, bytes([new_byte]))
    vp_ex(h_proc, ha, 1, op)
    code_buf[off] = new_byte
    log(f"    [OK] map_movement: {actual}ms -> {frame_delay}ms @RVA 0x{off:X} "
        f"(地图速度 {ORIG / frame_delay:.1f}x)")
    return True


def apply_animation_speed(defn: PatchDef, code_buf: bytearray, code_start_addr: int,
                          h_proc: int, log_func=None) -> bool:
    log = log_func or (lambda x: None)
    tag = f"[{defn.id}]"
    log(f"\n  {tag}: {defn.desc}")

    # 1. 读取 JSON 配置
    jf = defn.json_file
    if not jf or not os.path.isfile(jf):
        log(f"    [WARN] JSON 配置不存在: {jf!r}, 跳过")
        return True
    try:
        with open(jf, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"  [ERROR] 解析 animation_speed.json 失败: {e}")
        return True

    # 2. 预扫描通用 pattern (状态/移动/技能动画共用)
    pat, wc = parse_pattern("2B ?? 83 F8 3C")
    all_hits = pattern_scan(bytes(code_buf), pat, wc)
    log(f"    通用 pattern 扫描: {len(all_hits)} 处匹配")

    all_ok = True

    # 3. 状态动画 (6个函数的 0x3C)
    status_cfg = cfg.get("status_animation", {})
    status_delay = int(status_cfg.get("frame_delay_ms", 60))
    log(f"  [状态动画] frame_delay_ms={status_delay}")
    if status_delay != 60:
        all_ok &= _patch_frame_delay_3c(status_delay, _STATUS_ANIM_FUNCS, code_buf,
                                          code_start_addr, h_proc, log, all_hits)

    # 4. 攻击+技能动画 (sub_4434BC 的 v30+60)
    attack_cfg = cfg.get("attack_animation", {})
    if attack_cfg:
        log(f"  [攻击+技能动画] base={attack_cfg.get('base_frame_delay_ms', 60)} "
            f"extra={attack_cfg.get('extra_segment_delay_ms', 120)} "
            f"decr={attack_cfg.get('extra_delay_decrement_ms', 30)}")
        all_ok &= _patch_attack_animation(attack_cfg, code_buf,
                                            code_start_addr, h_proc, log)

    # 5. 移动动画 (sub_43DE90 的 0x3C)
    move_cfg = cfg.get("move_animation", {})
    move_delay = int(move_cfg.get("frame_delay_ms", 60))
    log(f"  [移动动画] frame_delay_ms={move_delay}")
    if move_delay != 60:
        all_ok &= _patch_frame_delay_3c(move_delay, _MOVE_ANIM_FUNCS, code_buf,
                                          code_start_addr, h_proc, log, all_hits)

    # 6. 待机动画 (sub_43CA64 战场主循环的 0x3C)
    idle_cfg = cfg.get("idle_animation", {})
    idle_delay = int(idle_cfg.get("frame_delay_ms", 60))
    log(f"  [待机动画] frame_delay_ms={idle_delay}")
    if idle_delay != 60:
        all_ok &= _patch_frame_delay_3c(idle_delay, _IDLE_ANIM_FUNCS, code_buf,
                                          code_start_addr, h_proc, log, all_hits)

    # 7. 剧情地图移动速度 (sub_412BE8 剧情地图主循环的 0x3C 帧节流)
    map_cfg = cfg.get("map_movement", {})
    if map_cfg:
        map_delay = int(map_cfg.get("frame_delay_ms", 60))
        log(f"  [剧情地图移动] frame_delay_ms={map_delay}")
        all_ok &= _patch_map_movement(map_cfg, code_buf, code_start_addr,
                                       h_proc, log)

    return all_ok

# ============================================================
# 配置补丁编排
# ============================================================

def apply_config_patches(config: PatchConfig, code_buf: bytearray, code_start_addr: int,
                          base_addr: int, h_proc: int, warpc_base: int, cave_addr: int,
                          settings: PatchSettings, runtime: PatchRuntimeState,
                          log_func=None,
                          minimal_mode=False, no_cave_mode=False,
                          only_portrait=False, only_awk=False,
                          selected_patches: set = None,
                          exe_profile=None,
                          disabled_patches: set = None,
                          config_overrides: Optional[Dict[str, Any]] = None) -> bool:
    """配置补丁编排

    Args:
        exe_profile: ExeProfile 实例, 用于第三方 MOD 兼容检测。
                     若为 None 则按原版处理。
        config_overrides: MOD 包携带的启动器配置覆盖 (白名单内, 优先级最高)。
                          键为不含扩展名的配置名 (如 "summon_table"),
                          值为已解析的 dict。None 或空 dict 表示无覆盖。
        disabled_patches: 诊断/兼容模式下强制跳过的补丁 ID 集合。
    """
    log = log_func or (lambda x: None)
    all_ok = True
    pch: List[PatchDef] = []
    disabled_patches = disabled_patches or set()

    # 第三方 MOD 兼容: 从 profile 获取应跳过的补丁
    _profile_skip = set()
    _profile_name = "original"
    if exe_profile is not None:
        _profile_skip = exe_profile.skip_patches or set()
        _profile_name = exe_profile.name

    # ── Phase 6: Cave 布局 (在主循环之前一次性分配所有 cave 偏移) ──
    cave_layout = _build_cave_layout(config, cave_addr, settings, log)

    # ── Phase 7: Hook 占用跟踪表 (启动器内部多个 cave_hook 之间) ──
    hook_table = HookTable()

    def _verdict(defn, ok: bool) -> bool:
        """统一结果判定: 每个补丁必输出一行结果, 并置位 _applied 供统计。

        此前部分补丁 (尤其外置 cave_hook) 仅有描述行, 成败无法从日志确认。
        """
        defn._applied = bool(ok)
        if ok:
            log(f"    [OK] {defn.id}: 补丁已应用")
        else:
            log(f"    [ERROR] {defn.id}: 补丁应用失败")
        return bool(ok)

    for defn in config.patches:
        tag = f"[{defn.id}]"
        log(f"\n  {tag}: {defn.desc}")

        if selected_patches is not None and defn.optional and defn.id not in selected_patches:
            log(f"    -> [跳过] 用户取消勾选")
            continue

        if defn.id in disabled_patches:
            log(f"    -> [跳过] 诊断/兼容模式强制禁用")
            continue

        # 第三方 MOD 兼容: profile_rules 检查
        if defn.profile_rules:
            rule = defn.profile_rules.get(_profile_name,
                                         defn.profile_rules.get("_default", "apply"))
            if rule == "skip":
                log(f"    -> [跳过] profile '{_profile_name}' 规则禁用")
                continue

        # 第三方 MOD 兼容: profile skip_patches 检查
        if defn.id in _profile_skip:
            log(f"    -> [跳过] 第三方 MOD 版本自动禁用")
            continue

        if defn.type == "cave_hook":
            # Cave hook 是两阶段提交 (pre-scan 后批量 apply),
            # 在 dispatcher 中显式处理, 不进入通用注册表。
            hp = defn.hook_pattern or defn.pattern
            hpat, hwc = parse_pattern(hp or "")
            hh = pattern_scan(bytes(code_buf), hpat, hwc)
            if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
                # 模式匹配失败 — 尝试 fallback_rva 回退定位
                if len(hh) == 0 and defn.fallback_rva > 0:
                    fb_hook = defn.fallback_rva - 0x1000  # RVA -> code_buf offset
                    fb_off = fb_hook - defn.hook_offset
                    if 0 <= fb_off < len(code_buf) - defn.hook_size:
                        hh = [fb_off]
                        log(f"  {tag}: 模式无匹配, 使用 fallback_rva 0x{defn.fallback_rva:X} (offset 0x{fb_hook:X})")
                    else:
                        log(f"    [WARN] {tag}: fallback_rva 0x{defn.fallback_rva:X} 越界, 补丁未应用")
                        continue
                elif len(hh) == 0 and exe_profile and exe_profile.has_extra_sections:
                    log(f"    [WARN] {tag}: Hook 模式无匹配 (目标代码已被第三方 MOD 修改, 无 fallback), 补丁未应用")
                    continue
                else:
                    log(f"    [WARN] {tag}: Hook 模式匹配 {len(hh)} 处 (预期 {defn.hook_expect_count}), 补丁未应用")
                    continue
            # Hook 冲突检测 (Phase 7 v2): 同时检查启动器内部 + 外部 MOD
            hook_off_abs = hh[0] + defn.hook_offset
            conflicted, owner = check_hook_conflict_v2(code_buf, hook_off_abs, hook_table)
            if conflicted:
                action = defn.hook_conflict_action
                if owner == "external_call_or_jmp":
                    ht, _sz = detect_hook_type(code_buf, hook_off_abs)
                    log(f"  {tag}: Hook 点已被外部 MOD 占用 ({ht}), 启动器按 {action} 处理")
                else:
                    log(f"  {tag}: Hook 点已被启动器内部 {owner} 占用, 启动器按 {action} 处理")
                if action == "override":
                    log(f"  {tag}: 启动器优先级最高 → 覆盖")
                elif action == "skip":
                    log(f"    -> [跳过] 配置声明冲突时跳过此 hook")
                    continue
                else:
                    log(f"  {tag}: [WARN] 未知 action={action}, 仍尝试应用")
            # 注册 hook 点到 HookTable (即使冲突也注册, override 后以本补丁为准)
            hook_table.register(hook_off_abs, defn.id)
            defn._pre_scanned_hits = hh
            pch.append(defn)
            log(f"    预扫描命中 {len(hh)} 处 (RVA 0x{hh[0] + defn.hook_offset:X}), 等待应用阶段写入")
            continue

        # 构建统一 ctx, 委托给注册表 handler
        ctx = PatchContext(
            defn, runtime.target_pid, h_proc, base_addr,
            code_buf, code_start_addr, cave_addr, warpc_base, settings, runtime,
            log_func=log, exe_profile=exe_profile,
            config_overrides=config_overrides,
        )

        if defn.type == "script":
            # 脚本类型通过 run_script_patch 加载外部 apply(ctx)
            all_ok &= _verdict(defn, run_script_patch(defn, ctx))
            continue

        if defn.type == "patch_warpc_addr":
            # WarPC 地址由 WarPC 扩展流程统一处理, 此处仅日志
            log(f"    -> 由 WarPC 扩展流程处理 (base=0x{warpc_base:08X})")
            defn._applied = True
            continue

        # 注册表查找: 普通 patch_type
        handler = _PATCH_TYPE_HANDLERS.get(defn.type)
        if handler is None:
            log(f"    [ERROR] {tag}: 未知补丁类型 '{defn.type}', 补丁未应用")
            continue
        all_ok &= _verdict(defn, handler(ctx))

    if pch and not minimal_mode and not no_cave_mode:
        hta = pch
        if only_portrait:
            hta = [h for h in pch if h.id in ("portrait_cave1", "portrait_cave2")]
        elif only_awk:
            hta = [h for h in pch if h.id == "awk_sprite_cave"]
        if len(hta) != len(pch):
            for skipped in pch:
                if skipped not in hta:
                    log(f"    [WARN] {skipped.id}: cave hook 被当前启动模式过滤, 未应用")
        log(f"\n  应用 {len(hta)} 个 cave hooks...")
        for defn in hta:
            hook_ok = apply_cave_hook(defn, defn._pre_scanned_hits, code_buf,
                                       code_start_addr, h_proc, cave_addr,
                                       warpc_base, settings, runtime, log_func=log)
            all_ok &= _verdict(defn, hook_ok)
    elif pch:
        # minimal/no_cave 模式下预扫描通过但不写入
        for defn in pch:
            log(f"    [WARN] {defn.id}: cave hook 被当前启动模式禁用, 未应用")

    # 汇总: 成功数仅统计真正走过应用路径的补丁 (跳过的不计为失败)
    applied = sum(1 for p in config.patches if getattr(p, "_applied", False))
    log(f"\n  补丁应用汇总: {applied} 个成功 / 共 {len(config.patches)} 个补丁")
    return all_ok
