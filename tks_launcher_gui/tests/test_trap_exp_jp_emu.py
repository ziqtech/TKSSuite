# -*- coding: utf-8 -*-
"""unicorn 执行级验证: trap_exp_jp_kill_fix + trap_exp_jp_personal_fix。

从原版内存转储 (反编译产物/memory/00401000--00481000.txt) 载入真实 .text,
按启动器 apply_cave_hook 的方式 (E8 rel32 + NOP) 安装 hook, 从 sub_4400DC @0x441827
(击杀门槛前) 端到端执行到击杀块出口 0x441CA6, 断言各累计器结果。

场景 (victim=10 为敌方, byte_9DF761[10]=3):
  1 team_kill    队伍成员(arg_0=2,camp=100)击杀 → 原版行为: 个人+750 共享池+1500 JP+66 金钱+166
  2 enemy_kill   敌方(arg_0=11,camp=5)击杀队员(victim camp=100) → 全部跳过 (与原 jnz 等价)
  3 trap_kill    陷阱(arg_0=-1, byte_9DF760=0)击杀敌人 → gate 放行, 个人经验跳过
                 (dword_9D6F1C 只 +166 金钱, 不被 +750 个人经验污染), 共享池/JP/金钱正常
  4 summon_kill  召唤物(arg_0=30,camp=20)且未开召唤补丁 → 全部跳过 (原版行为)
  5 both_enabled 同开召唤补丁: 召唤 cave 20→100 → 放行; 个人经验按 arg_0=30 写
                 dword_9D6F20[30] (召唤补丁既有语义), 共享池/JP/金钱正常
  6 trap_e100    陷阱且 byte_9DF760=100 (原版门槛本就放行的边界) → 与场景3一致
"""
import json
import os
import re
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX,
                               UC_X86_REG_ESP, UC_X86_REG_EIP)

DUMP = os.environ.get("TKS_MEM_DUMP", "")   # 反汇编内存转储 (00401000--00481000)
TEXT_BASE, TEXT_SIZE = 0x401000, 0x481000 - 0x401000
CAVE_BASE = 0x70000000
STACK = 0x7FF00000
STOP_ADDR = 0x441CA6

DATA_BASE, DATA_SIZE = 0x9D0000, 0x18000       # 0x9D0000-0x9E8000: 战斗数据区
GOLD_BASE = 0x750000                            # word_757F04/757F06

# 数据地址 (与逆向命名一致)
A_9D6F12 = 0x9D6F12
A_EXP_POOL = 0x9D6F14                           # dword_9D6F14 共享经验池
A_JP_POOL = 0x9D6F18                            # dword_9D6F18 共享JP池
A_MONEY = 0x9D6F1C                              # arglist 金钱累计器
A_PERSONAL = 0x9D6F20                           # dword_9D6F20[] 个人经验
A_9D7058 = 0x9D7058
A_9D6FC6 = 0x9D6FC6                             # 单位死亡态
A_CAMP = 0x9DF761                               # byte_9DF761[] 阵营
A_SCROLL = 0x9DF760                             # byte_9DF760 滚动偏移 = byte_9DF761[-1]
A_RANK = 0x9DF781                               # byte_9DF781[]
A_HP = 0x9D7084                                 # word_9D7084[527*u]
A_JPVAL = 0x9D7292                              # word_9D7292[527*u]
A_GOLDVAL = 0x9D7294                            # word_9D7294[527*u]
A_WEAPON = 0x9D6C7C                             # word_9D6C7C 武器ID (陷阱=-1)

VICTIM = 10
STRIDE = 527 * 2                                # word 数组按单位寻址的字节步进


def load_text() -> bytes:
    mem = {}
    with open(DUMP) as f:
        for line in f:
            m = re.match(r'^([0-9A-F]{16}) \| (.*?)\s*\|', line)
            if m:
                mem[int(m.group(1), 16)] = bytes.fromhex(
                    re.sub(r'[^0-9A-F]', '', m.group(2)))
    out = bytearray(TEXT_SIZE)
    a = TEXT_BASE
    while a < 0x481000:
        ch = mem.get(a)
        if ch is None:
            raise RuntimeError(f"dump gap @0x{a:X}")
        out[a - TEXT_BASE:a - TEXT_BASE + 16] = ch
        a += 16
    return bytes(out)


def install_hook(code: bytearray, hook_va: int, cave_va: int, size: int):
    """复刻 patch_engine.apply_cave_hook: E8 rel32 + NOP 填充。"""
    off = hook_va - TEXT_BASE
    rel = (cave_va - (hook_va + 5)) & 0xFFFFFFFF
    ci = bytearray(size)
    ci[0] = 0xE8
    ci[1:5] = struct.pack('<I', rel)
    for i in range(5, size):
        ci[i] = 0x90
    code[off:off + size] = ci


def cave_bytes_from_patch(patch_dir: str) -> bytes:
    with open(os.path.join(patch_dir, "patch.json"), encoding="utf-8") as f:
        cc = json.load(f)["cave_code"]
    return bytes.fromhex(cc.replace(" ", ""))


_PATCHES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patches")

try:
    CAVE_GATE = cave_bytes_from_patch(os.path.join(_PATCHES, "trap_exp_jp_kill_fix"))
    CAVE_PERSONAL = cave_bytes_from_patch(os.path.join(_PATCHES, "trap_exp_jp_personal_fix"))
    CAVE_SUMMON = cave_bytes_from_patch(os.path.join(_PATCHES, "summon_exp_jp_accumulation_fix"))
except (FileNotFoundError, KeyError, OSError):
    CAVE_GATE = CAVE_PERSONAL = CAVE_SUMMON = None

if CAVE_GATE is not None:
    assert len(CAVE_GATE) == 23 and len(CAVE_PERSONAL) == 21 and len(CAVE_SUMMON) == 18


def run(name: str, arg0: int, with_summon: bool, scroll0: int = 0) -> dict:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    code = bytearray(load_text())
    # 安装 hook (与启动器相同手法): cave 布局 0x000=gate 0x100=personal 0x200=summon
    install_hook(code, 0x44183C, CAVE_BASE + 0x000, 6)            # trap gate (jnz, 6B)
    install_hook(code, 0x4418F8, CAVE_BASE + 0x100, 14)           # personal add (14B)
    if with_summon:
        install_hook(code, 0x441832, CAVE_BASE + 0x200, 7)        # summon (movsx, 7B)
    uc.mem_map(TEXT_BASE, 0x80000)
    uc.mem_write(TEXT_BASE, bytes(code))
    uc.mem_map(CAVE_BASE, 0x1000)
    uc.mem_write(CAVE_BASE + 0x000, CAVE_GATE)
    uc.mem_write(CAVE_BASE + 0x100, CAVE_PERSONAL)
    uc.mem_write(CAVE_BASE + 0x200, CAVE_SUMMON)
    uc.mem_map(DATA_BASE, DATA_SIZE)
    uc.mem_map(GOLD_BASE, 0x1000)
    uc.mem_map(STACK - 0x100000, 0x200000)

    def w8(a, v): uc.mem_write(a, bytes([v & 0xFF]))
    def w16(a, v): uc.mem_write(a, struct.pack('<h', v))
    def w32(a, v): uc.mem_write(a, struct.pack('<i', v))
    def r8(a): return uc.mem_read(a, 1)[0]
    def r16(a): return struct.unpack('<h', uc.mem_read(a, 2))[0]
    def r32(a): return struct.unpack('<i', uc.mem_read(a, 4))[0]

    # ---- 数据环境 ----
    w16(A_WEAPON, -1)                 # 陷阱/无武器 → 跳过 0xE8/0xDC 计数块
    w8(A_SCROLL, scroll0)             # byte_9DF760 (byte_9DF761[-1])
    w8(A_CAMP + VICTIM, 3)            # victim=敌方 (camp<10)
    w8(A_RANK + VICTIM, 2)
    w16(A_HP + VICTIM * STRIDE, 300)
    w16(A_JPVAL + VICTIM * STRIDE, 40)
    w16(A_GOLDVAL + VICTIM * STRIDE, 50)
    w16(A_HP + 20 * STRIDE, 500)      # 场景2 victim=20 (队员)
    w8(A_CAMP + 20, 100)
    w8(A_CAMP + 2, 100)               # 队伍成员2
    w8(A_CAMP + 11, 5)                # 敌方11
    w8(A_CAMP + 30, 20)               # 召唤物30
    for u in range(6):
        w32(A_PERSONAL + 4 * u, 0)
    w32(A_EXP_POOL, 0); w32(A_JP_POOL, 0); w32(A_MONEY, 0)
    w16(A_9D6F12, 0); w16(A_9D7058, 0)

    # ---- 栈帧: [ebp+8]=arg_0, [ebp-0x10]=victim ----
    ebp = STACK
    esp = STACK - 0x1000
    uc.mem_write(ebp + 8, struct.pack('<h', arg0))       # word arg_0
    uc.mem_write(ebp - 0x10, struct.pack('<i', VICTIM))  # var_10 (场景2 单独覆盖)

    if arg0 == 11:  # enemy_kill 场景 victim=20
        uc.mem_write(ebp - 0x10, struct.pack('<i', 20))
        victim = 20
    else:
        victim = VICTIM

    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, esp)

    def hook_code(uc, addr, size, ud):
        if addr == STOP_ADDR:
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook_code, begin=1, end=0)  # 全地址 (含 cave 区)

    uc.emu_start(0x441827, STOP_ADDR)

    assert uc.reg_read(UC_X86_REG_EIP) == STOP_ADDR, f"{name}: 未到达出口 EIP=0x{uc.reg_read(UC_X86_REG_EIP):X}"
    assert uc.reg_read(UC_X86_REG_ESP) == esp, f"{name}: 栈不平衡 esp=0x{uc.reg_read(UC_X86_REG_ESP):X}"

    res = {
        "exp_pool": r32(A_EXP_POOL),
        "jp_pool": r32(A_JP_POOL),
        "money": r32(A_MONEY),
        "personal": [r32(A_PERSONAL + 4 * u) for u in range(6)],
        "personal30": r32(A_PERSONAL + 4 * 30),
        "victim_hp": r16(A_HP + victim * STRIDE),
        "victim_dead": r16(A_9D6FC6 + 2 * victim),
        "kills": r16(A_9D7058),
    }
    return res


def expect(name, got, **exp):
    ok = True
    for k, v in exp.items():
        g = got[k]
        good = (list(g) == list(v)) if isinstance(v, (list, tuple)) else (g == v)
        if not good:
            print(f"  [FAIL] {name}: {k} = {g} (期望 {v})")
            ok = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main():
    if not DUMP or not os.path.isfile(DUMP):
        print("SKIP: 需要设置 TKS_MEM_DUMP 指向反汇编内存转储文件")
        return 0
    if CAVE_GATE is None:
        print("SKIP: patch cave source is not available")
        return 0
    all_ok = True
    base = {"victim_hp": 0, "victim_dead": 2, "kills": 1}

    print("场景1 队伍成员击杀 (arg_0=2, camp=100) — 原版行为基线:")
    r = run("team_kill", arg0=2, with_summon=False)
    all_ok &= expect("team_kill", r, exp_pool=1500, jp_pool=66, money=166,
                     personal=[0, 0, 750, 0, 0, 0], personal30=0, **base)

    print("场景2 敌方击杀队员 (arg_0=11 camp=5, victim camp=100) — 与原 jnz 等价:")
    r = run("enemy_kill", arg0=11, with_summon=False)
    all_ok &= expect("enemy_kill", r, exp_pool=0, jp_pool=0, money=0,
                     personal=[0]*6, personal30=0, **base)

    print("场景3 陷阱击杀敌人 (arg_0=-1, byte_9DF760=0) — 新增行为:")
    r = run("trap_kill", arg0=-1, with_summon=False)
    all_ok &= expect("trap_kill", r, exp_pool=1500, jp_pool=66, money=166,
                     personal=[0]*6, personal30=0, **base)

    print("场景4 召唤物击杀且未开召唤补丁 (arg_0=30, camp=20) — 原版跳过:")
    r = run("summon_nopatch", arg0=30, with_summon=False)
    all_ok &= expect("summon_nopatch", r, exp_pool=0, jp_pool=0, money=0,
                     personal=[0]*6, personal30=0, **base)

    print("场景5 同开召唤补丁 (召唤 cave 20→100 放行, arg_0=30):")
    r = run("summon_patched", arg0=30, with_summon=True)
    all_ok &= expect("summon_patched", r, exp_pool=1500, jp_pool=66, money=166,
                     personal=[0]*6, personal30=750, **base)

    print("场景6 陷阱且 byte_9DF760=100 (原版门槛本就放行的边界, 行为须与场景3一致):")
    r = run("trap_e100", arg0=-1, with_summon=False, scroll0=100)
    all_ok &= expect("trap_e100", r, exp_pool=1500, jp_pool=66, money=166,
                     personal=[0]*6, personal30=0, **base)

    print("\n" + ("全部场景通过 ✓" if all_ok else "存在失败场景 ✗"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
