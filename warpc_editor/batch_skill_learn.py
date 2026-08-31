#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
WarPC.dat 批处理工具：技能效果判定 → 技能学习「可以学」
=========================================================
将指定角色记录区间内，「技能效果判定」标签中所有"有效果"(默认非零)的字段，
在「技能学习」标签中对应技能批量设为指定学习状态(默认 10-可以学)。

复用 warpc_editor.py 的 load_warpc/save_warpc(LZSS 压缩 + 回写校验)，
严格按编辑器一致的映射规则执行:
  - 技能效果判定 槽位 i  → 记录字段 [273+i]，对应技能 = active_indices[i]
      active_indices = TKSkill.dat 中 type==0(指令技能) 的索引升序列表
      槽位数 count = min(len(active_indices), 527-273)
  - 技能学习 技能 skill_idx → 字段 [88 + skill_idx//2] 的低/高字节
      值 10 = 可以学; 0=不会 1~9=等待学 20=组技能学会 30=子技能学会

默认"不降级"：仅当目标技能当前学习值 < 设定值 时才修改，保留已学会(20/30)
或已达标的技能不变。可用 --allow-downgrade 关闭。

用法示例:
  # 默认文件的 #143..#199 (设为10, 不降级, 自动备份 + 回读校验)
  python batch_skill_learn.py

  # 指定文件与区间
  python batch_skill_learn.py --warpc D:\Game\WarPC.dat --from 143 --to 199

  # 先干跑看统计, 不写盘
  python batch_skill_learn.py --dry-run

  # 允许把已学会的也强制改为10 (会降级)
  python batch_skill_learn.py --allow-downgrade

  # 只把"正数"效果视为有效果 (排除 0 与 -1/未设置)
  python batch_skill_learn.py --effect-mode positive
"""
import argparse
import copy
import datetime
import os
import shutil
import struct
import sys
from collections import Counter

# stdout 强制 UTF-8, 避免 Windows 控制台中文乱码 (无需手动设 PYTHONIOENCODING)
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..'))   # editor_utils
sys.path.insert(0, _HERE)                        # warpc_editor
from warpc_editor import (                        # noqa: E402
    load_warpc, save_warpc, WARPC_FIELD_COUNT, SKILL_LEARN_COUNT,
)
from editor_utils.lzss import lzss_decompress_dat  # noqa: E402

# ── 常量 (与 warpc_editor._populate_edit/_apply_edit 保持一致) ──
EFFECT_BASE = 273      # 技能效果判定 起始 int16 字段索引
LEARN_BASE = 88        # 技能学习 起始 int16 字段索引
LEARN_END = 259        # 技能学习 结束 int16 字段索引 (含)
TKSKILL_REC = 94       # TKSkill.dat 每条字节数
TKSKILL_MAX = 350      # TKSkill 最大条目数
TKSKILL_TYPE_OFF = 4   # 技能类型 int16 字节偏移 (与 _load_skill_names 一致)
DEFAULT_WARPC = r"游戏目录/WarPC.dat"

LEARN_STATE_NAMES = {0: "不会", 10: "可以学", 20: "组技能学会", 30: "子技能学会"}

# 判定"有效果"的谓词: (函数, 描述)
EFFECT_PREDICATES = {
    'nonzero': (lambda v: v != 0, "非零 (!=0，与最初需求一致)"),
    'positive': (lambda v: v > 0, "正数 (>0，排除 0 与负/未设置)"),
    'nonneg': (lambda v: v >= 0, "非负 (>=0，含 0)"),
}


def build_active_indices(tkskill_path):
    """复刻 _load_skill_names + _build_skill_effect_section 的映射。
    返回 (active_indices, count)。"""
    with open(tkskill_path, 'rb') as f:
        raw = f.read()
    dec = lzss_decompress_dat(raw)
    if len(raw) % TKSKILL_REC == 0 and (len(dec) == 0 or len(dec) % TKSKILL_REC != 0):
        dec = raw  # 兜底: 文件本身未压缩
    active = []
    for i in range(TKSKILL_MAX):
        off = i * TKSKILL_REC
        if off + TKSKILL_TYPE_OFF + 2 > len(dec):
            break
        stype = struct.unpack_from('<h', dec, off + TKSKILL_TYPE_OFF)[0]
        if stype == 0:
            active.append(i)
    count = min(len(active), WARPC_FIELD_COUNT - EFFECT_BASE)
    return active, count


def read_learn_byte(fields, skill_idx):
    """读取技能 skill_idx 的学习状态字节。"""
    field_idx = LEARN_BASE + skill_idx // 2
    is_high = skill_idx % 2
    unsigned = fields[field_idx] & 0xFFFF
    return (unsigned >> (8 * is_high)) & 0xFF


def write_learn_byte(fields, skill_idx, byte_val):
    """写入技能 skill_idx 的学习状态字节 (与 _apply_edit 位打包一致)。"""
    field_idx = LEARN_BASE + skill_idx // 2
    is_high = skill_idx % 2
    unsigned = fields[field_idx] & 0xFFFF
    if is_high:
        new_val = (unsigned & 0x00FF) | ((byte_val & 0xFF) << 8)
    else:
        new_val = (unsigned & 0xFF00) | (byte_val & 0xFF)
    if new_val >= 0x8000:
        new_val -= 0x10000
    fields[field_idx] = new_val


def collect_targets(fields, active, count, effect_pred):
    """返回该记录中"有效果且有学习位"的 skill_idx 集合。"""
    targets = set()
    for i in range(count):
        if effect_pred(fields[EFFECT_BASE + i]):
            skill_idx = active[i]
            if skill_idx < SKILL_LEARN_COUNT:
                targets.add(skill_idx)
    return targets


def apply_changes(recs, active, count, lo, hi, value, effect_pred, allow_downgrade):
    """执行批量修改。返回统计 dict。"""
    stats = dict(changed=0, already=0, kept=0, skipped_no_learn=0,
                 from_state=Counter(), touched=set())
    for ri in range(lo, hi + 1):
        fields = recs[ri]['fields']
        for i in range(count):
            if not effect_pred(fields[EFFECT_BASE + i]):
                continue
            skill_idx = active[i]
            if skill_idx >= SKILL_LEARN_COUNT:      # 344..349 无对应学习位
                stats['skipped_no_learn'] += 1
                continue
            cur = read_learn_byte(fields, skill_idx)
            if cur == value:
                stats['already'] += 1
                continue
            if cur > value and not allow_downgrade:  # 已学会等更高状态, 保留
                stats['kept'] += 1
                continue
            write_learn_byte(fields, skill_idx, value)
            stats['changed'] += 1
            stats['from_state'][cur] += 1
            stats['touched'].add(ri)
    return stats


def verify(original, new, active, count, lo, hi, value, effect_pred, allow_downgrade):
    """对比修改前(内存快照)与保存后(重新读盘), 确认精确无误。
    返回 (errors, changed_bytes)。"""
    errors = []
    for ri in range(len(original)):
        if lo <= ri <= hi:
            continue
        if original[ri]['fields'] != new[ri]['fields']:
            errors.append(f"区间外记录 #{ri} 被改动")
    changed_bytes = 0
    for ri in range(lo, hi + 1):
        fo, fn = original[ri]['fields'], new[ri]['fields']
        # 学习区[88..259] 以外的所有字段必须一致 (含 技能效果[273..526])
        for idx in range(WARPC_FIELD_COUNT):
            if LEARN_BASE <= idx <= LEARN_END:
                continue
            if fo[idx] != fn[idx]:
                errors.append(f"#{ri} 非学习字段[{idx}] 被改动 {fo[idx]}->{fn[idx]}")
        targets = collect_targets(fn, active, count, effect_pred)
        for s in range(SKILL_LEARN_COUNT):
            bo, bn = read_learn_byte(fo, s), read_learn_byte(fn, s)
            if s in targets and bo != value and not (bo > value and not allow_downgrade):
                expected = value            # 应被改为 value
            else:
                expected = bo               # 应保持不变
            if bn != expected:
                errors.append(f"#{ri} 技能{s} 期望{expected} 实际{bn}")
            if bn != bo:
                changed_bytes += 1
    return errors, changed_bytes


def fmt_state_dist(counter):
    parts = []
    for k in sorted(counter):
        nm = LEARN_STATE_NAMES.get(k, "等待学" if 1 <= k <= 9 else "?")
        parts.append(f"{k}-{nm}×{counter[k]}")
    return ", ".join(parts) if parts else "(无)"


def build_parser():
    ap = argparse.ArgumentParser(
        description="WarPC.dat 批处理: 技能效果判定(非零) → 技能学习设为可以学(10)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--warpc', default=DEFAULT_WARPC,
                    help=f"WarPC.dat 路径 (默认: {DEFAULT_WARPC})")
    ap.add_argument('--tkskill', default=None,
                    help="TKSkill.dat 路径 (默认: 与 WarPC.dat 同目录)")
    ap.add_argument('--from', dest='lo', type=int, default=143,
                    help="起始记录号(含, 默认 143)")
    ap.add_argument('--to', dest='hi', type=int, default=199,
                    help="结束记录号(含, 默认 199)")
    ap.add_argument('--value', type=int, default=10,
                    help="要设置的学习状态值 (默认 10=可以学; 0/1-9/20/30 等)")
    ap.add_argument('--effect-mode', choices=list(EFFECT_PREDICATES), default='nonzero',
                    help="判定'有效果'的方式 (默认 nonzero)")
    ap.add_argument('--allow-downgrade', action='store_true',
                    help="允许把已达标/已学会(>=value)的技能也改为 value(会降级); 默认不降级")
    ap.add_argument('--dry-run', action='store_true',
                    help="仅分析并打印统计, 不写入文件、不备份")
    ap.add_argument('--no-backup', action='store_true',
                    help="不创建时间戳备份 (不推荐)")
    ap.add_argument('--no-verify', action='store_true',
                    help="写入后不做回读校验 (默认会校验)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    warpc = args.warpc
    tkskill = args.tkskill or os.path.join(os.path.dirname(warpc), 'TKSkill.dat')

    if not os.path.exists(warpc):
        print(f"[错误] 找不到 WarPC.dat: {warpc}", file=sys.stderr)
        return 2
    if not os.path.exists(tkskill):
        print(f"[错误] 找不到 TKSkill.dat: {tkskill}", file=sys.stderr)
        return 2
    if not (0 <= args.value <= 255):
        print(f"[错误] --value 需在 0..255 之间: {args.value}", file=sys.stderr)
        return 2

    pred, pred_desc = EFFECT_PREDICATES[args.effect_mode]
    active, count = build_active_indices(tkskill)
    recs = load_warpc(warpc)
    n = len(recs)

    lo, hi = args.lo, args.hi
    if lo < 0 or hi < 0 or lo > hi or hi >= n:
        print(f"[错误] 记录区间无效: #{lo}..#{hi}; 文件共 {n} 条(0..{n-1})",
              file=sys.stderr)
        return 2

    vname = LEARN_STATE_NAMES.get(args.value, "等待学" if 1 <= args.value <= 9 else "?")
    print("═" * 60)
    print(f"  WarPC.dat 批处理: 技能效果判定 → 技能学习")
    print("═" * 60)
    print(f"  文件      : {warpc}  (共 {n} 条记录)")
    print(f"  TKSkill   : {tkskill}")
    print(f"  记录区间  : #{lo} .. #{hi}  ({hi - lo + 1} 条)")
    print(f"  目标状态  : {args.value}-{vname}")
    print(f"  有效果判定: {args.effect_mode}  {pred_desc}")
    print(f"  降级策略  : {'允许降级' if args.allow_downgrade else '不降级(保留>=目标值的技能)'}")
    print(f"  effect映射: active_indices={len(active)} 槽位count={count} "
          f"字段[{EFFECT_BASE}..{EFFECT_BASE + count - 1}]")
    print("─" * 60)

    original = copy.deepcopy(recs)
    st = apply_changes(recs, active, count, lo, hi, args.value, pred, args.allow_downgrade)

    print(f"  实际改动学习位     = {st['changed']}")
    print(f"    改动前状态分布   = {fmt_state_dist(st['from_state'])}")
    print(f"  已是目标值(未改动) = {st['already']}")
    print(f"  {'已改为(降级)' if args.allow_downgrade else '保留>目标值(不降级)'} = {st['kept']}")
    print(f"  无学习位而跳过     = {st['skipped_no_learn']}  (skill_idx>=344)")
    print(f"  受影响记录数       = {len(st['touched'])} / {hi - lo + 1}")
    print("─" * 60)

    if args.dry_run:
        print("[DRY-RUN] 未写入任何文件。")
        return 0

    if st['changed'] == 0:
        print("[提示] 无任何需要改动的项，跳过写盘。")
        return 0

    if not args.no_backup:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = f"{warpc}.bak_{ts}"
        shutil.copy2(warpc, bak)
        print(f"[备份] 原文件 -> {bak}")

    save_warpc(warpc, recs)
    print(f"[保存] 已写回 {warpc} (LZSS 压缩 + 回写校验通过)")

    if not args.no_verify:
        new_recs = load_warpc(warpc)
        errors, changed_bytes = verify(original, new_recs, active, count,
                                       lo, hi, args.value, pred, args.allow_downgrade)
        if errors:
            print(f"[!!] 校验发现 {len(errors)} 处问题, 前20条:")
            for e in errors[:20]:
                print("   -", e)
            return 3
        print(f"[OK] 回读校验通过: 实际改动 {changed_bytes} 字节, 无越界/非预期改动。")
    return 0


if __name__ == '__main__':
    sys.exit(main())
