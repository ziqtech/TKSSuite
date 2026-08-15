"""补丁应用引擎 — 从 tks_launcher.py 提取 & 重组"""
import json
import importlib.util
import os
import struct
import types
from typing import Any, Dict, List, Optional
from .memory import (
    i32b, i16b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex,
    replace_addr_in_bytes,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    _OpenProcess, _CloseHandle,
)
from .scanner import parse_pattern, pattern_scan, value_scan
from .config_loader import PatchDef, PatchConfig, resolve_var


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
    """外部脚本补丁的稳定运行上下文。"""

    def __init__(self, defn: PatchDef, target_pid: int, h_proc: int,
                 base_addr: int, code_buf: bytearray, code_start_addr: int,
                 cave_addr: int, warpc_base: int, variables: Dict[str, int],
                 log_func=None, exe_profile=None, config_overrides=None):
        self.defn = defn
        self.target_pid = target_pid
        self.h_proc = h_proc
        self.base_addr = base_addr
        self.code_buf = code_buf
        self.code_start_addr = code_start_addr
        self.cave_addr = cave_addr
        self.warpc_base = warpc_base
        self.variables = variables
        self.log = log_func or (lambda x: None)
        self.exe_profile = exe_profile
        self.config_overrides = config_overrides


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
# Hook 冲突检测
# ============================================================

def check_hook_conflict(code_buf: bytearray, off: int) -> bool:
    """检测 hook 点是否已被其他 MOD 占用

    若目标位置的第一字节已是 E8(call) 或 E9(jmp)，
    说明已被其他补丁/MOD hook，存在冲稁。
    """
    if off < 0 or off >= len(code_buf):
        return False
    return code_buf[off] in (0xE8, 0xE9)

# ============================================================
# Cave 模板 (x86 机器码, 原样复制自 C#)
# ============================================================

CAVE_AWK_SPRITE = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x0F, 0xBF, 0x45, 0xFA,                            # movsx eax, word[ebp-6]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x7E, 0x2C,                                        # jle .done (+44) — 零或负数跳过
    0x3D, 0xC8, 0x00, 0x00, 0x00,                      # cmp eax, 200
    0x77, 0x25,                                        # ja .done (+37) — 超范围跳过
    0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,               # imul eax, eax, 0x41E
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x208]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x04,                                        # jnz .has_custom (+4)
    0x85, 0xC0,                                        # test eax, eax (ZF=0)
    0xEB, 0x0A,                                        # jmp .done (+10)
    # .has_custom:
    0x83, 0xE9, 0x06,                                  # sub ecx, 6
    0x66, 0x89, 0x4D, 0xFA,                            # mov word[ebp-6], cx
    0x66, 0x85, 0xC9,                                  # test cx, cx
    # .done:
    0x59, 0x58, 0xC3,                                  # pop ecx, pop eax, ret
])

# 战场形象 PATH2: 敌方角色精灵块条件覆盖
# hook 点原指令: add word ptr [ebp+8], 12 (5 字节: 66 83 45 08 0C)
# 逻辑: 若 WORD[260] != 0 → [ebp+8] = WORD[260] (直接使用自定义值)
#       若 WORD[260] == 0 → 保持原始 +12 逻辑
CAVE_AWK_SPRITE2 = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x0F, 0xBF, 0x45, 0x08,                            # movsx eax, word[ebp+8]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x7E, 0x1E,                                        # jle .default (+30)
    0x3D, 0xC8, 0x00, 0x00, 0x00,                      # cmp eax, 200
    0x77, 0x17,                                        # ja .default (+23)
    0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,               # imul eax, eax, 0x41E
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x208]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x07,                                        # jnz .use_custom (+7)
    # .default:
    0x66, 0x83, 0x45, 0x08, 0x0C,                      # add word[ebp+8], 12 (原始行为)
    0xEB, 0x04,                                        # jmp .done (+4)
    # .use_custom:
    0x66, 0x89, 0x4D, 0x08,                            # mov word[ebp+8], cx (自定义值)
    # .done:
    0x59, 0x58, 0xC3,                                  # pop ecx, pop eax, ret
])

# 队伍头像 PATH1: 选中队员头像查询
# hook 点原指令: add ax, 0xD3; push eax (5 字节)
# 进入时 ecx = char_idx * 527, ax = portrait原始值
# 计算: ecx*2 = char_idx*1054 = 记录字节偏移 (正确!)
CAVE_PORTRAIT1 = bytes([
    0x50, 0x51, 0x52,                                  # push eax, ecx, edx
    0x8B, 0xC1,                                        # mov eax, ecx
    0x85, 0xC0,                                        # test eax, eax
    0x7E, 0x1A,                                        # jle .default (+26)
    0x3D, 0x00, 0x00, 0x02, 0x00,                      # cmp eax, 0x20000
    0x77, 0x13,                                        # ja .default (+19)
    0x03, 0xC0,                                        # add eax, eax (char_idx*1054)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00,         # movzx eax, word[eax+0x20A]
    0x66, 0x85, 0xC0,                                  # test ax, ax
    0x75, 0x08,                                        # jnz .converge (+8)
    # .default:
    0x8B, 0x44, 0x24, 0x08,                            # mov eax, [esp+8]
    0x66, 0x05, 0xD3, 0x00,                            # add ax, 0xD3
    # .converge:
    0x83, 0xC4, 0x08,                                  # add esp, 8
    0x5A,                                              # pop edx
    0x87, 0x04, 0x24,                                  # xchg [esp], eax
    0xFF, 0xE0,                                        # jmp eax
])

# 队伍头像 PATH2: 非选中队员头像查询
# hook 点原指令: add dx, 0xD3; push edx (6 字节)
# 进入时 eax = char_idx * 527, dx = portrait原始值
# 计算: eax*2 = char_idx*1054 = 记录字节偏移 (正确!)
CAVE_PORTRAIT2 = bytes([
    0x50, 0x51,                                        # push eax, ecx
    0x85, 0xC0,                                        # test eax, eax
    0x7E, 0x1A,                                        # jle .default (+26)
    0x3D, 0x00, 0x00, 0x02, 0x00,                      # cmp eax, 0x20000
    0x77, 0x13,                                        # ja .default (+19)
    0x03, 0xC0,                                        # add eax, eax (char_idx*1054)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE
    0x0F, 0xB7, 0x88, 0x0A, 0x02, 0x00, 0x00,         # movzx ecx, word[eax+0x20A]
    0x66, 0x85, 0xC9,                                  # test cx, cx
    0x75, 0x07,                                        # jnz .has_custom (+7)
    # .default:
    0x66, 0x81, 0xC2, 0xD3, 0x00,                      # add dx, 0xD3
    0xEB, 0x03,                                        # jmp .done (+3)
    # .has_custom:
    0x66, 0x89, 0xCA,                                  # mov dx, cx
    # .done:
    0x59, 0x58,                                        # pop ecx, pop eax
    0x87, 0x14, 0x24,                                  # xchg [esp], edx
    0xFF, 0xE2,                                        # jmp edx
])

# 逆向依据: sub_41AB94 @0x41AD00 (存档界面队伍头像绘制)
# 原指令: movsx eax,byte[ecx+eax*2+0x29E]; add ax,0xD3; push eax
# 修复要点:
#   1. movzx ecx,al 取无符号角色索引 (0..199=有效, 0xFF=空槽)
#   2. cmp cl,0xFF 空槽检查 → 跳过 WarPC 查询避免越界崩溃
#   3. imul eax,ecx,0x41E 三操作数形式, ECX=源, 避免原二操作数 imul 破坏索引
#   4. 默认头像 = 索引 + 0xD3, 自定义头像 = warpc[index].field_0x20A
CAVE_ARCHIVE_PORTRAIT = bytes([
    0x52,                                              # push edx
    0x51,                                              # push ecx
    0x0F, 0xB6, 0xC8,                                  # movzx ecx, al          (无符号索引)
    0x80, 0xF9, 0xFF,                                  # cmp cl, 0xFF           (空槽?)
    0x74, 0x17,                                        # je .default            (空槽→默认)
    0x69, 0xC1, 0x1E, 0x04, 0x00, 0x00,               # imul eax, ecx, 0x41E   (索引*sizeof)
    0x05, 0x08, 0x7F, 0x75, 0x00,                      # add eax, WARPC_BASE    (→&warpc[idx])
    0x0F, 0xB7, 0x90, 0x0A, 0x02, 0x00, 0x00,         # movzx edx, word[eax+0x20A] (自定义头像)
    0x66, 0x85, 0xD2,                                  # test dx, dx
    0x75, 0x09,                                        # jnz .use_custom
    # .default:
    0x8B, 0xC1,                                        # mov eax, ecx
    0x05, 0xD3, 0x00, 0x00, 0x00,                      # add eax, 0xD3          (默认头像)
    0xEB, 0x02,                                        # jmp .done
    # .use_custom:
    0x8B, 0xC2,                                        # mov eax, edx           (自定义头像)
    # .done:
    0x59,                                              # pop ecx                (恢复 ecx)
    0x5A,                                              # pop edx                (恢复 edx)
    0x59,                                              # pop ecx                (ecx=返回地址)
    0x50,                                              # push eax               (portrait值入栈)
    0xFF, 0xE1,                                        # jmp ecx                (返回)
])

CAVE_HISTORY_TEXT = bytes([
    0x52, 0x69, 0xD2, 0x1E, 0x04, 0x00, 0x00, 0x81,
    0xC2, 0x08, 0x7F, 0x75, 0x00, 0x0F, 0xB7, 0x82,
    0x0C, 0x02, 0x00, 0x00, 0x85, 0xC0, 0x75, 0x08,
    0x5A, 0x81, 0xC2, 0x5A, 0x23, 0x00, 0x00, 0xC3,
    0x8B, 0xD0, 0x83, 0xC4, 0x04, 0xC3,
])

# 经验加成乘法溢出保护 Cave
# 逆向依据: sub_43B7FC @0x43BA27 exp_bonus 计算
# hook 点: mov edx,[eax]; movsx eax,word[ecx+3Eh]; imul edx,eax (9字节)
# 原始指令被替换为 E8(call)+4xNOP, cave执行后 ret回 +9处 (add edx,99)
# 逻辑:
#   1. mov edx, [eax]              — 加载 *v19 (原始指令1)
#   2. cmp edx, 30000             — 上界检查
#   3. jle .cap_done              — 已在范围内则跳过
#   4. mov edx, 30000             — 钳位到上限 (防止乘法溢出)
#   5. test edx, edx              — 下界检查
#   6. jns .no_neg                — 非负则跳过
#   7. xor edx, edx               — 负值置零
#   8. movsx eax, word[ecx+3Eh]   — 加载 exp_bonus (原始指令2)
#   9. imul edx, eax              — 安全乘法 (max 30000*32767 < INT32_MAX)
#  10. ret                        — 返回到 "add edx, 99"
CAVE_EXP_BONUS_SAFE_MUL = bytes([
    0x8B, 0x10,                                        # mov edx, [eax]
    0x81, 0xFA, 0x30, 0x75, 0x00, 0x00,                # cmp edx, 7530h
    0x7E, 0x05,                                        # jle .cap_done (+5)
    0xBA, 0x30, 0x75, 0x00, 0x00,                      # mov edx, 7530h
    # .cap_done:
    0x85, 0xD2,                                        # test edx, edx
    0x79, 0x02,                                        # jns .no_neg (+2)
    0x33, 0xD2,                                        # xor edx, edx
    # .no_neg:
    0x0F, 0xBF, 0x41, 0x3E,                            # movsx eax, word[ecx+3Eh]
    0x0F, 0xAF, 0xD0,                                  # imul edx, eax
    0xC3,                                              # ret
])

_WARPC_BASE_PLACEHOLDER = 0x757F08

# ============================================================
# Cave 模板: 召唤多随机 (224~231)
# 逆向依据: sub_444BB0 @0x444C83 查表指令; sub_452AC0 rand(n)->0..n-1
# hook 点 0x444C83 (movsx edx,byte[eax+0x4EB6F0], 7字节) -> E8 rel32 + 90 90
# cave 末尾 ret 回 0x444C8A (mov [ebp-2],dx 由原指令写回)
# count=0 走原查表 (向后兼容); count=N 调 sub_452AC0(N) 随机选 cand[0..N-1]
# 唯一动态重定位点: TABLE_BASE 占位符 0x52414E44 (cave 内出现 1 次)
# ============================================================

SUMMON_RANDOM_PLACEHOLDER = 0x52414E44   # "RAND", cave 内唯一, 指向 72 字节候选表

CAVE_SUMMON_RANDOM = bytes([
    0x53,                                              # 0  push ebx
    0x56,                                              # 1  push esi
    0x0F,0xBF,0x1D,0x7C,0x6C,0x9D,0x00,                # 2  movsx ebx, word[0x9D6C7C]
    0x81,0xEB,0xE0,0x00,0x00,0x00,                     # 9  sub ebx, 0xE0  (imm32! 避免 imm8 符号扩展, idx 224..231 -> 0..7)
    0x6B,0xDB,0x09,                                    # 15 imul ebx, ebx, 9       (entry 9 字节)
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 18 add ebx, TABLE_BASE   <- 占位符 (imm32 立即数加, 非[mem]解引用)
    0x8B,0xF3,                                         # 24 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 26 movzx ecx, byte[esi]   (count)
    0x85,0xC9,                                         # 29 test ecx, ecx
    0x74,0x1B,                                         # 31 jz  .default(60)
    0x83,0xF9,0x01,                                    # 33 cmp ecx, 1
    0x76,0x10,                                         # 36 jbe .single(54)
    0x51,                                              # 38 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 39 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 44 call eax               (rand(count))
    0x59,                                              # 46 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 47 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x14,                                         # 52 jmp .done(74)
    0x0F,0xB6,0x56,0x01,                               # 54 .single: movzx edx, byte[esi+1]
    0xEB,0x0E,                                         # 58 jmp .done(74)
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,                # 60 .default: movsx eax, word[0x9D6C7C]
    0x0F,0xBE,0x90,0xF0,0xB6,0x4E,0x00,                # 67 movsx edx, byte[eax+0x4EB6F0]  (原查表)
    0x5E,                                              # 74 .done: pop esi
    0x5B,                                              # 75 pop ebx
    0xC3,                                              # 76 ret
])

# ============================================================
# Cave 模板: 召唤多随机 222/251
# 与 224~231 区别: 222/251 hook 点之后不经 mov[ebp-2],dx, 故 cave 自行写 [ebp-2]
# 合并三段: entry_222(entry8) + entry_251(entry9) + shared(随机选 cand, 写[ebp-2])
# entry_222/entry_251 仅设 entry 常数后 jmp shared; shared 内 rand 选 cand -> [ebp-2]
# 仅在配了 skill_222_random/skill_251_random 时启用对应 hook (count>=1, 无 default 分支)
# ============================================================

CAVE_SUMMON_RANDOM_222_251 = bytes([
    # entry_222 @0  (hook 0x444C9C, ret->0x444CA2 jmp 0x444CCF)
    0x53,                                              # 0  push ebx
    0xBB,0x08,0x00,0x00,0x00,                          # 1  mov ebx, 8            (entry 8)
    0xEB,0x08,                                         # 6  jmp shared(16)
    # entry_251 @8  (hook 0x444CB3, ret->0x444CB8 NOP->0x444CCF)
    0x53,                                              # 8  push ebx
    0xBB,0x09,0x00,0x00,0x00,                          # 9  mov ebx, 9            (entry 9)
    0xEB,0x00,                                         # 14 jmp shared(16)
    # shared @16
    0x56,                                              # 16 push esi
    0x6B,0xDB,0x09,                                    # 17 imul ebx, ebx, 9
    0x81,0xC3,0x44,0x4E,0x41,0x52,                     # 20 add ebx, TABLE_BASE   <- 占位符 (imm32)
    0x8B,0xF3,                                         # 26 mov esi, ebx
    0x0F,0xB6,0x0E,                                    # 28 movzx ecx, byte[esi]  (count, >=1)
    0x83,0xF9,0x01,                                    # 31 cmp ecx, 1
    0x76,0x10,                                         # 34 jbe .single(52)
    0x51,                                              # 36 push ecx
    0xB8,0xC0,0x2A,0x45,0x00,                          # 37 mov eax, 0x452AC0
    0xFF,0xD0,                                         # 42 call eax              (rand(count))
    0x59,                                              # 44 pop ecx
    0x0F,0xB6,0x54,0x06,0x01,                          # 45 movzx edx, byte[esi+1+eax]  (i=cand[r])
    0xEB,0x04,                                         # 50 jmp .write(56)
    0x0F,0xB6,0x56,0x01,                               # 52 .single: movzx edx, byte[esi+1]
    0x66,0x89,0x55,0xFE,                               # 56 .write: mov [ebp-2], dx
    0x5E,                                              # 60 pop esi
    0x5B,                                              # 61 pop ebx
    0xC3,                                              # 62 ret
])

# ============================================================
# Cave 模板: 武器 cause_mask -> TKKon inflict_status
# 逆向依据: 注入点 sub_4400DC @0x4400F6 (TKKon拷贝后, 状态队列推送前)
# hook: mov word [0x9E028A], 0 (9字节) -> E8 rel32 + 4xNOP
# cave 末尾 ret 回 hook+5, 经4xNOP到 hook+9 继续
# 逻辑:
#   0. ★ 检查 word_9D6C7C (当前技能索引), 不等于-1则跳过 (物品/技能/防御不触发武器附加)
#   1. ★ 读取 [ebp+8] (sub_4400DC 参数 a1 = 当前动画实体)
#   2. ★ 验证 a1 == word_9D6F58 (仅攻击者本人的动画才触发, 排除反击/连击)
#   3. WarPC[attacker].offset_69 -> 装备武器 item_index
#   4. TKItem[item_index].offset_26/27 -> cause_mask[1/2]
#   5. OR 进 word_9D6C3C / word_9D6C3E
#   6. 执行被替换指令 mov word [0x9E028A], 0
# BUG FIX v4: v3 读取全局 word_9D6F58 导致反击场景中用被攻击角色的武器判断状态
#             v4 改读函数参数 [ebp+8] 并验证 == word_9D6F58, 排除非攻击者动画
# ============================================================
CAVE_WEAPON_CAUSE_MASK = bytes([
    # 保存寄存器
    0x60,                                              #  0 pushad

    # ★ 检查当前技能索引: 仅普通攻击 (索引==-1) 时才应用武器附加状态
    # 逆向依据: sub_447DAC case 2000 设 word_9D6C7C=-1 表示普通攻击
    #           技能/物品使用时为 >=0 的技能ID, 防御=-2, 逃跑=-3
    0x0F,0xBF,0x05,0x7C,0x6C,0x9D,0x00,               #  1 movsx eax, [0x9D6C7C] (当前技能索引)
    0x83,0xF8,0xFF,                                    #  8 cmp eax, -1
    0x75,0x4A,                                         # 11 jne .done (+74) — 非普通攻击则跳过

    # ★ 读取 sub_4400DC 参数 a1 (当前动画实体, 即 sub_4434BC 传入的 entity)
    # 逆向依据: sub_4400DC 参数为当前播放动画的实体索引
    #   - 主攻击: sub_4434BC(word_9D6F58) -> a1 == word_9D6F58
    #   - 反击:   sub_4434BC(v26) -> a1 != word_9D6F58 (被排除)
    0x0F,0xBF,0x45,0x08,                               # 13 movsx eax, word ptr [ebp+8]

    # ★ 验证当前动画实体 == 回合攻击者 (排除反击/连击/群攻副动画)
    0x66,0x3B,0x05,0x58,0x6F,0x9D,0x00,               # 17 cmp ax, word ptr [0x9D6F58]
    0x75,0x3D,                                         # 24 jne .done (+61) — 非攻击者动画则跳过

    # 范围检查 (无符号比较: 负数视为超大正数, 与 >=143 一同拦截)
    0x3D,0x8F,0x00,0x00,0x00,                          # 26 cmp eax, 143
    0x73,0x36,                                         # 31 jae .done (+54) — 越界跳过

    # 计算 WarPC 字节偏移: eax * 1054
    0x69,0xC0,0x1E,0x04,0x00,0x00,                     # 33 imul eax, eax, 1054
    0x05,0x08,0x7F,0x75,0x00,                          # 39 add eax, WARPC_BASE (占位符, 自动重定位)

    # 读取装备武器 item_index (字偏移69=字节偏移138=0x8A)
    0x0F,0xBF,0x90,0x8A,0x00,0x00,0x00,               # 44 movsx edx, [eax + 138]

    # 检查武器是否存在 (index != -1)
    0x83,0xFA,0xFF,                                    # 51 cmp edx, -1
    0x74,0x1F,                                         # 54 je .done (+31)

    # 计算 TKItem 字节偏移: edx * 64
    0xC1,0xE2,0x06,                                    # 56 shl edx, 6

    # 读取 cause_mask[1] (TKItem[26]=字节偏移52), OR 进 word_9D6C3C
    0x66,0x8B,0x82,0xFE,0xCB,0x77,0x00,               # 59 mov ax, [edx + 0x77CBFE]
    0x66,0x09,0x05,0x3C,0x6C,0x9D,0x00,               # 66 or [0x9D6C3C], ax

    # 读取 cause_mask[2] (TKItem[27]=字节偏移54), OR 进 word_9D6C3E
    0x66,0x8B,0x82,0x00,0xCC,0x77,0x00,               # 73 mov ax, [edx + 0x77CC00]
    0x66,0x09,0x05,0x3E,0x6C,0x9D,0x00,               # 80 or [0x9D6C3E], ax

    # .done: 恢复寄存器 + 执行被替换指令 + 返回
    0x61,                                              # 87 popad
    0x66,0xC7,0x05,0x8A,0x02,0x9E,0x00,0x00,0x00,     # 88 mov word [0x9E028A], 0
    0xC3,                                              # 97 ret
])

# Cave 模板: 死战状态决斗自我攻击修复
# 逆向依据: sub_4458B0 @0x445E99 (决斗循环入口, v24=byte_9D6FA4[0])
# hook: movsx ecx, byte ptr [0x9D6FA4] (7字节) -> E8 rel32 + 2xNOP
# 逻辑:
#   1. 执行被替换指令 (movsx ecx, byte [0x9D6FA4]) — 获取决斗目标实体
#   2. 读取 word_9D6F58 获取攻击者实体索引
#   3. 比较目标与攻击者: 相同则跳过决斗循环 (跳转到 0x4460F7)
#   4. 不同则正常返回执行决斗逻辑
# BUG 场景: 死战状态角色使用物品对自身后, 目标列表残留自身实体索引,
#           触发决斗循环导致角色自己攻击自己直到死去
# ============================================================
CAVE_DUEL_SELF_FIX = bytes([
    # 执行被替换指令: 获取决斗目标实体索引
    0x0F,0xBE,0x0D,0xA4,0x6F,0x9D,0x00,               #  0 movsx ecx, byte ptr [0x9D6FA4]

    # 读取攻击者实体索引并比较
    0x50,                                              #  7 push eax
    0x0F,0xBF,0x05,0x58,0x6F,0x9D,0x00,               #  8 movsx eax, word ptr [0x9D6F58]
    0x39,0xC1,                                         # 15 cmp ecx, eax
    0x58,                                              # 17 pop eax
    0x75,0x08,                                         # 18 jne .no_skip (+8) — 目标!=自身, 正常决斗

    # 目标==自身: 修改返回地址跳过决斗循环
    0xC7,0x04,0x24,0xF7,0x60,0x44,0x00,               # 20 mov dword ptr [esp], 0x4460F7
    0xC3,                                              # 27 ret → 跳到 skip_duel

    # .no_skip: 正常返回, 继续决斗
    0xC3,                                              # 28 ret
])

# ============================================================
# 补丁: 死战反击自伤修复 (duel_counter_self_fix)
# ============================================================
# 问题: sub_4458B0 AI强制反击段, sub_43D8B0从反击者自身坐标定位目标,
#       导致 byte_9D6FA4[0] == v26 (自身进入目标列表, 攻击自己)
#       现有 duel_self_target_fix 比较 word_9D6F58(原攻击者≠v26)无法拦截
# ============================================================
# 方案: Hook 在 sub_4434BC 入口 (0x4434BC), 替换前8字节函数头
#       hook 使用 E8 (call) 会在栈上多压一个返回地址,
#       因此 cave 开头先 pop edx 移除多余返回地址并暂存,
#       使栈布局还原为原始函数期望的 [ebp+4]=调用者返回地址
#       然后执行原序言并检查 byte_9D6FA4[0]==a1 (目标==施法者自身)
#       且 a1!=word_9D6F58 (反击场景, 非主攻击者)
#       若满足反击自伤条件: 将 byte_9D6FA4[0] 修正为 word_9D6F58
#       (原始攻击者), 使反击者正常攻击原攻击者而非自己
#       不影响主攻击者自伤(已有补丁)和治疗自愈(a1==word_9D6F58不过滤)
# ============================================================
CAVE_DUEL_COUNTER_SELF_FIX = bytes([
    # === 修复栈帧: pop 掉 E8 call 多压的返回地址 ===
    0x5A,                                              #  0 pop edx (edx = 0x4434C4, 暂存)
    # 现在栈布局与原始函数一致: [esp]=orig_ret, [esp+4]=a1

    # === 执行被替换的序言 (8 bytes) ===
    0x55,                                              #  1 push ebp
    0x8B, 0xEC,                                        #  2 mov ebp, esp (→ [ebp+4]=orig_ret, [ebp+8]=a1)
    0x83, 0xC4, 0x9C,                                  #  4 add esp, -64h
    0x56,                                              #  7 push esi
    0x57,                                              #  8 push edi

    # === 保存寄存器 ===
    0x50,                                              #  9 push eax
    0x51,                                              # 10 push ecx

    # === 检查 byte_9D6FA4[0] == a1 (自身目标?) ===
    0x0F, 0xBE, 0x05, 0xA4, 0x6F, 0x9D, 0x00,         # 11 movsx eax, byte [0x9D6FA4]
    0x0F, 0xBF, 0x4D, 0x08,                            # 18 movsx ecx, word [ebp+8] (a1)
    0x3B, 0xC1,                                        # 22 cmp eax, ecx
    0x75, 0x17,                                        # 24 jne .continue (+23) — 非自身, 正常执行

    # === 自身目标: 检查是否反击场景 (a1 != word_9D6F58) ===
    0x0F, 0xBF, 0x0D, 0x58, 0x6F, 0x9D, 0x00,         # 26 movsx ecx, word [0x9D6F58]
    0x66, 0x3B, 0x4D, 0x08,                            # 33 cmp cx, [ebp+8]
    0x74, 0x0A,                                        # 37 je .continue (+10) — 主攻击者, 已有补丁处理

    # === 反击自伤: 将目标修正为原始攻击者 ===
    0xA0, 0x58, 0x6F, 0x9D, 0x00,                      # 39 mov al, [0x9D6F58] (原始攻击者ID)
    0xA2, 0xA4, 0x6F, 0x9D, 0x00,                      # 44 mov [0x9D6FA4], al (修正第一目标)

    # === .continue: 正常继续 sub_4434BC ===
    0x59,                                              # 49 pop ecx
    0x58,                                              # 50 pop eax
    0x52,                                              # 51 push edx (0x4434C4, 之前暂存的)
    0xC3,                                              # 52 ret → 跳转到 0x4434C4 继续执行
])

# ============================================================
# Cave 模板: 主角替换 — TeamMember 脚本路由
# 逆向依据: sub_40DA00 @0x40DA1C (TeamMember 入口条件判断)
# hook: cmp word [ebp+8], 0; jnz 0x40DA8D (7字节) -> E8 rel32 + 2xNOP
# 路由逻辑 (最大化兼容原版脚本):
#   TeamMember(N, *)   (N>0) → 正常入队/离队 (不变)
#   TeamMember(0, 1)          → 主角入队槽位0: 检查→必要时整体右移→写入→调加入代码 (不变)
#   TeamMember(0, -1)         → 主角离队 (走正常离队分支, 压缩移位; 自定义扩展语义)
#   TeamMember(0, 0/其它)     → 清空全队 (原版语义: a1=0 恒清空, 兼容原版 TeamMember(0,0) 脚本)
# 格式: 精确计算所有跳转偏移, 模板大小 158 bytes
# ============================================================
CAVE_TEAM_MEMBER_LEAVE_ROUTING = bytes([
    # === Entry: 路由逻辑 ===
    0x66, 0x83, 0x7D, 0x08, 0x00,                      #  0 cmp [ebp+8], 0  ; a1==0?
    0x0F, 0x85, 0x89, 0x00, 0x00, 0x00,                #  5 jnz near .to_join_leave(148)
    0x66, 0x83, 0x7D, 0x0C, 0xFF,                      # 11 cmp [ebp+0Ch], -1  ; a2==-1?
    0x0F, 0x84, 0x7E, 0x00, 0x00, 0x00,                # 16 je near .to_join_leave(148)  ; a2==-1: 主角离队
    0x66, 0x83, 0x7D, 0x0C, 0x01,                      # 22 cmp [ebp+0Ch], 1  ; a2==1? 主角入队!
    0x0F, 0x84, 0x05, 0x00, 0x00, 0x00,                # 27 je near .proto_join(38)
    0xE9, 0x77, 0x00, 0x00, 0x00,                      # 33 jmp near .to_clear_all(157)  ; a2==0/其它: 清空全队(原版语义)

    # === .proto_join === (offset 38) 主角强制插入槽位0 ===
    0x66, 0x83, 0x3D, 0x8C, 0x68, 0x75, 0x00, 0x00,   # 38 cmp [0x75688C], 0  ; 已在槽位0?
    0x0F, 0x84, 0x57, 0x00, 0x00, 0x00,                # 46 je near .proto_return(139)
    0x66, 0x83, 0x3D, 0x8C, 0x68, 0x75, 0x00, 0xFF,   # 52 cmp [0x75688C], -1 ; 槽位0空?
    0x0F, 0x84, 0x30, 0x00, 0x00, 0x00,                # 60 je near .proto_set_slot0(114)
    0x33, 0xC9,                                        # 66 xor ecx, ecx  ; 查找第一个空位

    # === .find_empty === (offset 68) ===
    0x66, 0x83, 0x3C, 0x4D, 0x8C, 0x68, 0x75, 0x00, 0xFF,  # 68 cmp [ecx*2+0x75688C], -1
    0x74, 0x0B,                                        # 77 je short .found_empty(90)
    0x41,                                              # 79 inc ecx
    0x83, 0xF9, 0x06,                                  # 80 cmp ecx, 6
    0x7C, 0xEF,                                        # 83 jl short .find_empty(68)
    # 队伍已满 → 回退正常入队(会因满员失败)
    0xE9, 0x3A, 0x00, 0x00, 0x00,                      # 85 jmp near .to_join_leave(148)

    # === .found_empty === (offset 90) ecx=第一个空位索引 ===
    0x85, 0xC9,                                        # 90 test ecx, ecx
    0x74, 0x14,                                        # 92 jz short .proto_set_slot0(114) ; 槽位0本来就是空
    0x49,                                              # 94 dec ecx  ; 最后一个需右移的槽位

    # === .shift_loop === (offset 95) 整体右移: slot[i]→slot[i+1] ===
    0x66, 0x8B, 0x04, 0x4D, 0x8C, 0x68, 0x75, 0x00,   #  95 mov ax, [ecx*2+0x75688C]
    0x66, 0x89, 0x04, 0x4D, 0x8E, 0x68, 0x75, 0x00,   # 103 mov [ecx*2+0x75688E], ax
    0x49,                                              # 111 dec ecx
    0x79, 0xED,                                        # 112 jns short .shift_loop(95) ; ecx>=0继续

    # === .proto_set_slot0 === (offset 114) 放入主角, 跳到加入代码 ===
    0x66, 0xC7, 0x05, 0x8C, 0x68, 0x75, 0x00, 0x00, 0x00,  # 114 mov word [0x75688C], 0
    0xC7, 0x45, 0xFC, 0x00, 0x00, 0x00, 0x00,          # 123 mov dword [ebp-4], 0  ; v8=0
    0x83, 0xC4, 0x04,                                  # 130 add esp, 4  ; 丢弃CALL返回地址
    0x68, 0xBC, 0xDA, 0x40, 0x00,                      # 133 push 0x40DABC  ; 加入代码入口
    0xC3,                                              # 138 ret

    # === .proto_return === (offset 139) 主角已在槽位0, 直接返回 ===
    0x83, 0xC4, 0x04,                                  # 139 add esp, 4
    0x68, 0xED, 0xDB, 0x40, 0x00,                      # 142 push 0x40DBED  ; 函数尾声
    0xC3,                                              # 147 ret

    # === .to_join_leave === (offset 148) 正常入队/离队入口 ===
    0x83, 0xC4, 0x04,                                  # 148 add esp, 4
    0x68, 0x8D, 0xDA, 0x40, 0x00,                      # 151 push 0x40DA8D
    0xC3,                                              # 156 ret

    # === .to_clear_all === (offset 157) 清空全队 ===
    0xC3,                                              # 157 ret → 0x40DA21→NOP→NOP→0x40DA23
])

# ============================================================
# Cave 模板: 主角替换 — CheckMember 等级检查重定向
# 逆向依据: sub_40E88C @0x40E8CB (CheckMember a2==0 分支)
# hook: movsx edx, word [ebp+8] (5字节) -> E8 rel32
# 逻辑:
#   1. pop 掉 E8 call 多压的返回地址
#   2. 若 a1==0 (检查主角), 读取 word_75688C[0] (槽位0成员ID)
#   3. 若槽位0非空且非主角自身, 替换 a1 = 槽位0成员ID
#   4. 执行被替换指令 (movsx ecx, word [ebp+8]) 并 jmp 回 0x40E8D1
# ============================================================
CAVE_CHECKMEMBER_LEVEL = bytes([
    0x59,                                              #  0 pop ecx (丢弃 CALL 返回地址)
    0x50,                                              #  1 push eax
    0x66, 0x83, 0x7D, 0x08, 0x00,                      #  2 cmp word [ebp+8], 0        ; a1 == 0?
    0x75, 0x15,                                        #  7 jne .skip (→ 30)            ; a1 != 0 → 跳过
    0x66, 0xA1, 0x8C, 0x68, 0x75, 0x00,                #  9 mov ax, [0x75688C]         ; ax = word_75688C[0]
    0x66, 0x83, 0xF8, 0xFF,                            # 15 cmp ax, -1                  ; 槽位0为空?
    0x74, 0x09,                                        # 19 je .skip (→ 30)             ; 是 → 跳过
    0x66, 0x85, 0xC0,                                  # 21 test ax, ax                 ; 槽位0=主角自身?
    0x74, 0x04,                                        # 24 je .skip (→ 30)             ; 是 → 跳过
    0x66, 0x89, 0x45, 0x08,                            # 26 mov word [ebp+8], ax        ; 替换 a1 = 槽位0成员ID
    # 自然落入 .skip (无需 jmp, mov [ebp+8] 后紧跟 pop eax)
    # .skip:
    0x58,                                              # 30 pop eax                     ; 恢复 eax
    0x0F, 0xBF, 0x4D, 0x08,                            # 31 movsx ecx, word [ebp+8]    ; ecx = (可能修改后的) a1
    0x8B, 0xD1,                                        # 35 mov edx, ecx               ; edx = a1 (0x40E8D4 add/sub 需要!)
    0x68, 0xD1, 0xE8, 0x40, 0x00,                      # 37 push 0x40E8D1              ; 返回目标
    0xC3,                                              # 42 ret                         ; → 0x40E8D1
])

# ============================================================
# Cave 模板: 战斗经验锁定（压级）
# 逆向依据: sub_43B7FC @0x43BAF3  (战后经验分配, 读取 v11 = *v19 处)
# hook 点: mov eax,[esp+1C]; mov dx,[eax] (7字节) -> E8 rel32 + 2 NOP
#   原始被偷指令在 cave 内重放; cave ret 回 0x43BAF8(NOP,NOP)→0x43BAFA(mov [esp+6],dx)
# 目标: 锁定槽位将 dword_9D6F20[slot](=*v19, 每槽获得经验累加器) 置 0 ——
#   既使结算屏显示 0 (sub_43B2D4 读 *v6=dword_9D6F20 显示),
#   又使随后 v11=*v19=0 → 不升级、经验不写回。
# 逻辑 (入口 esp 已因 call +4, 故 [esp+1C]→[esp+20], [esp]→[esp+04]):
#   1. mov eax,[esp+20h]      — 重放: eax = v19 (dword_9D6F20[slot] 指针)
#   2. movzx ecx,word[esp+4]  — ecx = v5 = 战斗队伍槽位 (0..5)
#   3. mov dl, MASK           — dl = 锁定掩码 (imm8, 由 apply_exp_lock 按配置写入; bit i=锁定槽 i)
#   4. shr dl, cl / test dl,1 — 测试槽位 slot 的锁定位
#   5. jz .keep               — 未锁定 → 不改动
#   6. mov dword[eax], 0      — 锁定 → dword_9D6F20[slot]=0 (显示与逻辑均为0)
#   7. mov dx, [eax]          — 重放被偷指令2: dx=*v19 (锁定则=0), 随后存入 v11
#   8. ret
# 仅用 eax/ecx/dx (返回后原代码均重载), 无 push/pop, 栈平衡不变
# ============================================================
CAVE_EXP_LOCK_MASK_OFFSET = 10   # CAVE_EXP_LOCK 内 imm8 掩码字节偏移
CAVE_EXP_LOCK = bytes([
    0x8B, 0x44, 0x24, 0x20,                            #  0 mov eax, [esp+20h]        ; eax = v19 指针
    0x0F, 0xB7, 0x4C, 0x24, 0x04,                      #  4 movzx ecx, word [esp+04h] ; ecx = 槽位 v5
    0xB2, 0x00,                                        #  9 mov dl, MASK             ; [10]=掩码占位, 补丁写入
    0xD2, 0xEA,                                        # 11 shr dl, cl               ; dl >>= 槽位
    0xF6, 0xC2, 0x01,                                  # 13 test dl, 1
    0x74, 0x06,                                        # 16 jz .keep (→ 24)          ; 未锁定→不改动
    0xC7, 0x00, 0x00, 0x00, 0x00, 0x00,                # 18 mov dword [eax], 0       ; 锁定→dword_9D6F20[slot]=0
    # .keep:
    0x66, 0x8B, 0x10,                                  # 24 mov dx, [eax]            ; 重放: dx=*v19 (锁定则0)
    0xC3,                                              # 27 ret
])

# ============================================================
# Cave: 战斗技能菜单封顶 12 项 (skill_menu_cap)
# 逆向依据: sub_438F28 @0x439049 / sub_447BA8 @0x447C6B (两处指令序列完全相同)
#
# 战斗技能菜单的 5 组平行数组均只有 12 项, 地址首尾相接:
#   word_9D6D1A[12]      技能索引   0x9D6D1A..0x9D6D32 (24B; memset(...,-1,0x18))
#   byte_9D6D32[12]      可用标志   0x9D6D32..0x9D6D3E (12B; memset(...,1,0xC))
#   unk_9D6D3E[12]       标志备份   0x9D6D3E..0x9D6D4A (12B; memcpy(...,0xC))
#   dword_9D6D4A[12][3]  技能名     0x9D6D4A..0x9D6DDA (144B = 12×12)
#   word_9D6DF8[12]      MP 消耗    0x9D6DF8..0x9D6E10 (24B)
# 构建循环以 word_9D6C8A (0x9D6C8A) 为下标写入并递增, 且无任何越界检查:
#   if (skill_learn >= 20) { word_9D6D1A[cnt]=..; 名称/MP/标志同写; ++cnt; }
# 同一指令技能组已学子技能超过 12 个时, 第 13 项起溢出踩坏相邻数组
# (可用标志/技能名/MP), 叠加菜单窗口高度 28×cnt 超屏 → 战斗菜单错乱。
# (物品菜单 sub_4391E0 有 `if (cnt == 10) break` 保护, 技能菜单独缺此防线。)
#
# 本 cave 接管被 hook 掉的 8 字节状态载入指令 movsx ecx, byte[edx+eax*2+0xB0]:
#   先原样复现该载入, 随后若 word_9D6C8A >= 12 则将 ecx 清零。
#   ecx=0 < 20 → 紧随其后未被改动的原始 `cmp ecx,14h` + `jl skip` 自然跳过本项,
#   计数器不再增长, 菜单稳定封顶 12 项 (等价于在 ++cnt 前加 if(cnt>=12) skip)。
# 仅改动 ecx (原指令自身的输出寄存器); 标志位随后即被原始 cmp 重设, 无副作用。
# 0x9D6C8A 位于战斗数据区 (.bss 静态地址), 不属于 WarPC 重定位范围, 可直接硬编码。
# ============================================================
CAVE_SKILL_MENU_CAP = bytes([
    0x0F, 0xBE, 0x8C, 0x42, 0xB0, 0x00, 0x00, 0x00,  #  0 movsx ecx, byte [edx+eax*2+0B0h] ; 复现原指令
    0x66, 0x83, 0x3D, 0x8A, 0x6C, 0x9D, 0x00, 0x0C,  #  8 cmp  word [9D6C8Ah], 12         ; 菜单现有项数
    0x72, 0x02,                                      # 16 jb   .keep (→20)              ; <12 保留原状态
    0x33, 0xC9,                                      # 18 xor  ecx, ecx                  ; 已满→伪装未学会
    # .keep:
    0xC3,                                            # 20 ret
])

# ============================================================
# Cave 模板: 强制出战主角缺失时槽0顶替 (war_mustchar_fallback)
# 逆向依据: sub_4307CC (PlaceUnits) 强制名单解析 @0x430895
#   hook 点: movsx eax,byte[ecx]; dec eax; (5字节) -> E8 rel32
#   原始被偷指令: eax = (char)*v16 - 1 (名单角色 0-based ID), 存入 v26
#
# 问题背景: 主角离队后, WarData must_chars 含主角(值1)的战斗在名单解析阶段
#   找不到主角 → v23 全 0 → 0 人出战 → 0x430BC3 `idiv cx` (cx=byte_9DF886=0)
#   除零崩溃 (EXCEPTION_INT_DIVIDE_BY_ZERO)。
#
# 本 cave 在重放 movsx/dec 后追加判断: 若 v26==0 (强制主角) 且队伍
#   word_75688C[0..5] 中无主角, 则把 v26 替换为队伍槽0角色 ID
#   (槽0空则为 -1, 内层循环不匹配任何槽, 与 checkmember_level_redirect
#   同一槽0顶替语义)。非主角强制角色不受影响。
# 栈: call 压入返回地址先 pop eax (随即被 movsx 覆盖); 扫描段 push/pop
#   ecx,edx 保护 (edx=0x430892 设置的 v23 指针, 0x4308A3 仍需使用)。
# 返回 0x43089D (mov word [ebp-4],0, 内层循环 v27=0 初始化)。
# ============================================================
CAVE_WAR_MUSTCHAR_FALLBACK = bytes([
    0x58,                                              #  0 pop  eax                    ; 丢弃 call 返回地址
    0x0F, 0xBE, 0x01,                                  #  1 movsx eax, byte [ecx]      ; 重放: eax = (char)*v16
    0x48,                                              #  4 dec  eax                    ; 重放: v26 = ID-1
    0x66, 0x83, 0xF8, 0x00,                            #  5 cmp  ax, 0                  ; v26 == 0 (强制主角)?
    0x75, 0x21,                                        #  9 jnz  .store (→2C)           ; 非主角 → 直接存
    0x51,                                              # 11 push ecx                    ; 保护 (扫描用)
    0x52,                                              # 12 push edx                    ; 保护 v23 指针
    0xB9, 0x06, 0x00, 0x00, 0x00,                      # 13 mov  ecx, 6                 ; 6 槽
    0xBA, 0x8C, 0x68, 0x75, 0x00,                      # 18 mov  edx, 0x75688C          ; 队伍
    # .scan:
    0x66, 0x83, 0x3A, 0x00,                            # 23 cmp  word [edx], 0          ; 槽 == 0 (主角在队)?
    0x74, 0x0D,                                        # 27 je   .found (→2A)           ; 有主角 → 保持 v26=0
    0x83, 0xC2, 0x02,                                  # 29 add  edx, 2                 ; 下一槽
    0x49,                                              # 32 dec  ecx
    0x75, 0xF4,                                        # 33 jnz  .scan (→23)
    0x0F, 0xBF, 0x05, 0x8C, 0x68, 0x75, 0x00,          # 35 movsx eax, word [0x75688C]  ; 无主角 → v26 = 槽0角色ID (7字节)
    # .found:
    0x5A,                                              # 42 pop  edx
    0x59,                                              # 43 pop  ecx
    # .store:
    0x66, 0x89, 0x45, 0xFA,                            # 44 mov  word [ebp-6], ax       ; v26 = ax (重放)
    0x68, 0x9D, 0x08, 0x43, 0x00,                      # 48 push 0x43089D               ; 返回: 内层循环初始化
    0xC3,                                              # 53 ret
])

# ============================================================
# Cave 模板构建
# ============================================================

# awk_sprite / awk_sprite2 cave 中索引上限检查指令 `cmp eax, 200` 的原始字节
# 该上限是硬编码安全阈值, 角色 WarPC 索引 >200 时补丁被跳过 (回退原始公式),
# 扩容 WarPC.dat 后需按实际记录数动态上调, 否则新角色 WORD[260] 不生效
_AWK_CAP_OLD = bytes([0x3D, 0xC8, 0x00, 0x00, 0x00])  # cmp eax, 200

def build_cave_template(name: str, warpc_base: int, log_func=None,
                        idx_cap: Optional[int] = None,
                        external_code: Optional[bytes] = None) -> Optional[bytes]:
    log = log_func or (lambda x: None)

    # 外置 cave 代码优先 (.tkspatch 文件提供)
    if external_code is not None:
        c = bytearray(external_code)
        replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
        # 动态调整战场形象 cave 的 WarPC 索引上限
        if name in ("awk_sprite", "awk_sprite2") and idx_cap is not None:
            pos = c.find(_AWK_CAP_OLD)
            if pos >= 0:
                c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', idx_cap & 0xFFFFFFFF)
        log(f"    Cave 来源: 外置 .tkspatch ({len(c)} bytes)")
        return bytes(c)

    # 回退: 内置模板
    templates = {
        "awk_sprite": CAVE_AWK_SPRITE,
        "awk_sprite2": CAVE_AWK_SPRITE2,
        "portrait1": CAVE_PORTRAIT1,
        "portrait2": CAVE_PORTRAIT2,
        "archive_portrait": CAVE_ARCHIVE_PORTRAIT,
        "history_text": CAVE_HISTORY_TEXT,
        "exp_bonus_safe_mul": CAVE_EXP_BONUS_SAFE_MUL,
        "weapon_cause_mask": CAVE_WEAPON_CAUSE_MASK,
        "duel_self_fix": CAVE_DUEL_SELF_FIX,
        "duel_counter_self_fix": CAVE_DUEL_COUNTER_SELF_FIX,
        "team_member_leave_routing": CAVE_TEAM_MEMBER_LEAVE_ROUTING,
        "checkmember_level": CAVE_CHECKMEMBER_LEVEL,
        "exp_lock": CAVE_EXP_LOCK,
        "skill_menu_cap": CAVE_SKILL_MENU_CAP,
        "war_mustchar_fallback": CAVE_WAR_MUSTCHAR_FALLBACK,
    }
    if name not in templates:
        log(f"    [WARN] 未知 cave 模板: {name}")
        return None
    c = bytearray(templates[name])
    replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
    # 动态调整战场形象 cave 的 WarPC 索引上限 (cmp eax, imm32, 长度不变)
    if name in ("awk_sprite", "awk_sprite2") and idx_cap is not None:
        pos = c.find(_AWK_CAP_OLD)
        if pos >= 0:
            c[pos:pos + 5] = bytes([0x3D]) + struct.pack('<I', idx_cap & 0xFFFFFFFF)
        else:
            log("    [WARN] awk cave 索引上限指令未找到, 保持默认 200")
    return bytes(c)

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
        ptd = 0
        for off in hits:
            for rk, bv in entry["replace"].items():
                ro = int(rk)
                aa = code_start_addr + off + ro
                op = vp_ex(h_proc, aa, 1, PAGE_EXECUTE_READWRITE)
                write_pm(h_proc, aa, bytes([bv & 0xFF]))
                vp_ex(h_proc, aa, 1, op)
                idx = off + ro
                if idx < len(code_buf):
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
                                h_proc: int, variables: Dict[str, int], log_func=None,
                                exclude_ranges: list = None) -> bool:
    log = log_func or (lambda x: None)
    _excl = exclude_ranges or []
    ov = defn.expect_value
    nv = resolve_var(defn.new_value_expr, variables, log_func=log)
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
                                  h_proc: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    nv = resolve_var(defn.new_value_expr, variables, log_func=log)
    if nv is None:
        log(f"    -> 变量未定义, 跳过")
        return True
    nle = i32b(nv)
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
        log(f"    模式: [{entry.get('pattern')}] -> 匹配 {len(hits)} 处 (预期 {exp})")
        if exp > 0 and len(hits) != exp:
            log(f"  [FAIL] 匹配数 {len(hits)} != 预期 {exp}, 跳过")
            all_ok = False
            continue
        ptd = 0
        for off in hits:
            io = off + vo
            if io + 4 <= len(code_buf):
                act = b2i32(bytes(code_buf), io)
                if ov != 0 and act != ov:
                    log(f"    [SKIP] RVA 0x{off:X}: 原值 0x{act:08X} != 预期 0x{ov:08X}")
                    continue
            aa = code_start_addr + io
            op = vp_ex(h_proc, aa, 4, PAGE_EXECUTE_READWRITE)
            nw = write_pm(h_proc, aa, nle)
            vp_ex(h_proc, aa, 4, op)
            if nw != 4:
                log(f"    [FAIL] WriteProcessMemory 失败 @0x{aa:08X}")
                all_ok = False
                continue
            if io + 4 <= len(code_buf):
                code_buf[io:io+4] = nle
            log(f"    [OK] RVA 0x{off:X} (abs 0x{aa:08X})")
            ptd += 1
        if ptd == 0 and exp > 0:
            all_ok = False
    return all_ok

# ============================================================
# 补丁类型: cave_hook
# ============================================================

def apply_cave_hook(defn: PatchDef, hits: List[int], code_buf: bytearray,
                     code_start_addr: int, h_proc: int, cave_addr: int,
                     warpc_base: int, variables: Dict[str, int], log_func=None) -> bool:
    log = log_func or (lambda x: None)
    if not hits:
        log("    [WARN] 未找到 hook 点")
        return False

    # WarPC 索引上限: 按扩容后的记录数计算 (默认模板硬编码 200,
    # 索引 >200 的新角色会导致 WORD[260] 自定义形象不生效)
    rec_size = variables.get("warpc_rec_size", 1054)
    new_size = variables.get("warpc_new_size", 150722)
    idx_cap = (new_size // rec_size - 1) if rec_size > 0 else 142
    if idx_cap < 200:
        idx_cap = 200

    # 外置 cave 代码优先 (.tkspatch 提供), 回退到内置模板
    ext_cave = getattr(defn, '_cave_code_bytes', None)
    cd = build_cave_template(defn.cave_template, warpc_base, log_func=log,
                             idx_cap=idx_cap, external_code=ext_cave)
    if cd is None:
        return False

    # Phase 2: Cave 越界硬校验 — 防止 .tkspatch 声明超出 budget 的 offset/size
    cave_budget = variables.get("cave_total_size", 2048)
    if not _check_cave_bounds(cave_addr, defn.cave_offset, len(cd),
                              cave_budget, defn.id, log):
        return False

    ct = cave_addr + defn.cave_offset
    write_pm(h_proc, ct, cd)
    log(f"    Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")

    ptd = 0
    for off in hits:
        hook_off = off + defn.hook_offset
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
                       base_addr: int, h_proc: int, variables: Dict[str, int],
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
    rec_size = variables.get("warpc_rec_size", 1054)
    new_size = variables.get("warpc_new_size", 150722)
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
    _pid = variables.get("_target_pid", 0)
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
                                            cave_budget=variables.get("cave_total_size", 2048))

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

    # Phase 2: Cave 越界硬校验 — 在分配前一次性检查三块偏移
    if cave_addr:
        for off_key, size in [("random_table_offset", 90),
                              ("random_cave_offset", len(CAVE_SUMMON_RANDOM)),
                              ("random2_cave_offset", len(CAVE_SUMMON_RANDOM_222_251))]:
            off = getattr(defn, off_key, 0)
            if not _check_cave_bounds(cave_addr, off, size, cave_budget,
                                      f"{defn.id}/{off_key}", log):
                return False

    # 外置 cave 代码支持 (.tkspatch 提供)
    from .tkspatch_loader import _parse_hex_bytes
    _extra = getattr(defn, '_extra', {})
    _ext_cave1 = _parse_hex_bytes(_extra.get('summon_cave_code', '')) if _extra.get('summon_cave_code') else None
    _ext_cave2 = _parse_hex_bytes(_extra.get('summon_cave2_code', '')) if _extra.get('summon_cave2_code') else None
    _cave_summon_random = _ext_cave1 if _ext_cave1 else CAVE_SUMMON_RANDOM
    _cave_summon_222_251 = _ext_cave2 if _ext_cave2 else CAVE_SUMMON_RANDOM_222_251

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

    # 4b. 写 90 字节候选表
    table_abs = cave_addr + defn.random_table_offset
    if write_pm(h_proc, table_abs, bytes(table)) != len(table):
        log(f"  [FAIL] 候选表写入失败 @0x{table_abs:08X}")
        return False
    log(f"    [OK] 候选表 @0x{table_abs:08X} (90 字节)")

    all_ok = True

    # 4c. 224~231: entry_224 cave + hook 0x444C84 (结果->edx, 由原 mov[ebp-2],dx 写回)
    if has_224:
        all_ok &= _write_cave_and_hook(
            _cave_summon_random, defn.random_cave_offset, 0,           # cave 代码, 入口偏移 0
            defn.random_hook_pattern, defn.random_hook_size, defn.random_hook_expect_count,
            table_abs, code_buf, code_start_addr, h_proc, cave_addr,
            warpc_i_fn, log, tag="224~231")

    # 4d. 222/251: 合并 cave (entry_222+entry_251+shared) + 各 hook
    if extra_hooks_to_apply:
        cave2_abs = cave_addr + defn.random2_cave_offset
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
                None, defn.random2_cave_offset, hk.get("entry_offset", 0),  # 复用已写 cave, 仅 hook
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
            for i in range(len(new_bytes)):
                code_buf[hook_off + i] = new_bytes[i]
        else:
            log(f"  [FAIL] 写入失败 @ 0x{ha:08X}")
            all_ok = False

    return all_ok

# ============================================================
# 补丁类型: patch_exp_lock (战斗经验锁定 / 压级)
# 逆向依据: sub_43B7FC @0x43BAF3 (读取 v11=*v19); CAVE_EXP_LOCK
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
    # 外置 cave 代码优先 (.tkspatch 提供)
    ext_cave = getattr(defn, '_cave_code_bytes', None)
    if ext_cave is not None:
        cd = bytearray(ext_cave)
        # 从 _extra 获取掩码偏移, 默认使用 CAVE_EXP_LOCK_MASK_OFFSET
        mask_off = getattr(defn, '_extra', {}).get('cave_mask_offset', CAVE_EXP_LOCK_MASK_OFFSET)
    else:
        cd = bytearray(CAVE_EXP_LOCK)
        mask_off = CAVE_EXP_LOCK_MASK_OFFSET
    cd[mask_off] = mask & 0xFF
    # Phase 2: Cave 越界硬校验
    if not _check_cave_bounds(cave_addr, defn.cave_offset, len(cd),
                              cave_budget, defn.id, log):
        return True
    ct = cave_addr + defn.cave_offset
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
                          variables: Dict[str, int], log_func=None,
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

    for defn in config.patches:
        tag = f"[{defn.id}]"
        log(f"\n  {tag}: {defn.desc}")

        if selected_patches is not None and defn.optional and defn.id not in selected_patches:
            log(f"    -> 用户取消勾选, 跳过")
            continue

        if defn.id in disabled_patches:
            log(f"    -> 诊断/兼容模式强制跳过")
            continue

        # 第三方 MOD 兼容: profile_rules 检查
        if defn.profile_rules:
            rule = defn.profile_rules.get(_profile_name,
                                         defn.profile_rules.get("_default", "apply"))
            if rule == "skip":
                log(f"    -> profile '{_profile_name}' 规则: 跳过")
                continue

        # 第三方 MOD 兼容: profile skip_patches 检查
        if defn.id in _profile_skip:
            log(f"    -> 第三方 MOD 版本自动跳过")
            continue

        if defn.type == "patch_bytes":
            all_ok &= apply_patch_bytes(defn, code_buf, code_start_addr, h_proc, log_func=log)
        elif defn.type == "patch_extra_section":
            # MOD 额外 PE 段 (.test 等) 字节补丁: code_buf 扫描窗口之外的第三方 MOD 代码
            all_ok &= apply_patch_extra_section(defn, h_proc, exe_profile, log_func=log)
        elif defn.type == "cave_hook":
            hp = defn.hook_pattern or defn.pattern
            hpat, hwc = parse_pattern(hp or "")
            hh = pattern_scan(bytes(code_buf), hpat, hwc)
            if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
                # 模式匹配失败 — 尝试 fallback_rva 回退定位
                if len(hh) == 0 and defn.fallback_rva > 0:
                    # fallback_rva 是相对于基址的偏移, 转为 code_buf 内偏移
                    fb_hook = defn.fallback_rva - 0x1000  # RVA -> code_buf offset
                    fb_off = fb_hook - defn.hook_offset
                    if 0 <= fb_off < len(code_buf) - defn.hook_size:
                        hh = [fb_off]
                        log(f"  {tag}: 模式无匹配, 使用 fallback_rva 0x{defn.fallback_rva:X} (offset 0x{fb_hook:X})")
                    else:
                        log(f"  {tag}: fallback_rva 0x{defn.fallback_rva:X} 越界, 跳过")
                        continue
                elif len(hh) == 0 and exe_profile and exe_profile.has_extra_sections:
                    log(f"  {tag}: Hook 模式无匹配 (MOD 已修改, 无 fallback), 跳过")
                    continue
                else:
                    log(f"  {tag}: Hook 模式匹配 {len(hh)} 处 (预期 {defn.hook_expect_count}), 跳过")
                    continue
            # Hook 冲突检测: 检查 hook 点是否已被占用
            if hh and check_hook_conflict(code_buf, hh[0] + defn.hook_offset):
                action = defn.hook_conflict_action
                if action == "override":
                    log(f"  {tag}: Hook 点已被占用, 启动器优先级最高 → 覆盖")
                elif action == "skip":
                    log(f"  {tag}: Hook 点已被占用 (E8/E9 开头), 跳过")
                    continue
                else:
                    log(f"  {tag}: [WARN] Hook 点已被占用, 但仍尝试应用")
            defn._pre_scanned_hits = hh
            pch.append(defn)
        elif defn.type == "script":
            ctx = PatchContext(
                defn, variables.get("_target_pid", 0), h_proc, base_addr,
                code_buf, code_start_addr, cave_addr, warpc_base, variables,
                log_func=log, exe_profile=exe_profile,
                config_overrides=config_overrides,
            )
            all_ok &= run_script_patch(defn, ctx)
        elif defn.type == "patch_imm32":
            if defn.value_scan:
                nv = resolve_var(defn.new_value_expr, variables, log_func=log)
                if nv is None:
                    log(f"    -> 变量未定义, 跳过")
                    continue
                if defn.expect_value != 0 and nv == defn.expect_value:
                    log(f"    -> 值未变化 ({defn.expect_value}), 跳过")
                    continue
                all_ok &= apply_patch_imm32_by_value(defn, code_buf, code_start_addr, h_proc, variables, log_func=log,
                                                       exclude_ranges=exe_profile.extra_section_ranges if exe_profile else None)
            else:
                all_ok &= apply_patch_imm32_by_pattern(defn, code_buf, code_start_addr, h_proc, variables, log_func=log)
        elif defn.type == "patch_warpc_addr":
            log(f"    -> 由 WarPC 扩展流程处理 (base=0x{warpc_base:08X})")
        elif defn.type == "patch_summon_table":
            _summon_override = None
            if config_overrides:
                _summon_override = config_overrides.get("summon_table")
            all_ok &= apply_summon_table(defn, code_buf, code_start_addr, base_addr,
                                          h_proc, variables, log_func=log,
                                          cave_addr=cave_addr,
                                          config_override=_summon_override)
        elif defn.type == "patch_drop_probability":
            _drop_override = None
            if config_overrides:
                _drop_override = config_overrides.get("drop_probability")
            all_ok &= apply_drop_probability(defn, code_buf, code_start_addr,
                                              h_proc, log_func=log,
                                              config_override=_drop_override)
        elif defn.type == "patch_exp_lock":
            _explock_override = None
            if config_overrides:
                _explock_override = config_overrides.get("exp_lock")
            all_ok &= apply_exp_lock(defn, code_buf, code_start_addr,
                                     h_proc, cave_addr, log_func=log,
                                     config_override=_explock_override,
                                     cave_budget=variables.get("cave_total_size", 2048))
        elif defn.type == "patch_font_config":
            all_ok &= apply_font_config(defn, code_buf, code_start_addr,
                                         h_proc, log_func=log)
        elif defn.type == "patch_animation_speed":
            all_ok &= apply_animation_speed(defn, code_buf, code_start_addr,
                                             h_proc, log_func=log)
        else:
            log(f"  [WARN] 未知补丁类型: {defn.type}")

    if pch and not minimal_mode and not no_cave_mode:
        hta = pch
        if only_portrait:
            hta = [h for h in pch if h.id in ("portrait_cave1", "portrait_cave2")]
        elif only_awk:
            hta = [h for h in pch if h.id == "awk_sprite_cave"]
        log(f"\n  应用 {len(hta)} 个 cave hooks...")
        for defn in hta:
            all_ok &= apply_cave_hook(defn, defn._pre_scanned_hits, code_buf,
                                       code_start_addr, h_proc, cave_addr,
                                       warpc_base, variables, log_func=log)
    return all_ok
