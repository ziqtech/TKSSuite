#!/usr/bin/env python3
"""诊断: TKAct 数据中 blend_mode & blend_param 的实际分布,
并列出若干"强混合"典型 entry 供 GUI 肉眼对照验证."""
import os, sys
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from act_editor import load_act, entry_is_empty, BLEND_MODE_LABELS

TKS_DIR = os.path.normpath(os.path.join(HERE, '..', '..', '逆向工作区', 'TKS'))
ACT_PATH = os.path.join(TKS_DIR, 'TKAct.dat')
if not os.path.exists(ACT_PATH):
    print("未找到 TKAct.dat")
    sys.exit(1)

entries = load_act(ACT_PATH)

# (mode, param) 联合分布
combo_counter = Counter()
mode_param_set = {i: Counter() for i in range(8)}
# 按 entry 收集: 非 0 blend 出现次数
entry_strong = []

for i, e in enumerate(entries):
    if entry_is_empty(e):
        continue
    strong = 0  # 非0非2p0 layer 数
    layers_desc = []
    for slot_idx in range(8):
        L = e['layers'][slot_idx]
        t = L[0]
        if t == 0:
            continue
        m = L[11] & 0xFFFF
        p = L[12] & 0xFFFF
        if p >= 0x8000:
            p -= 0x10000  # 还原成有符号 int16
        combo_counter[(m, p)] += 1
        if m in mode_param_set:
            mode_param_set[m][p] += 1
        # 把"会显著改变画面"的视为强混合:
        #   - mode=1/3/4/5 无论 param
        #   - mode=2 且 param!=0
        is_strong = (m in (1, 3, 4, 5)) or (m == 2 and p != 0)
        if is_strong:
            strong += 1
        layers_desc.append((slot_idx + 1, t, m, p))
    if strong > 0:
        entry_strong.append((i, strong, layers_desc))

print("=" * 70)
print("blend_mode × 主要 blend_param 分布 (只看非空 layer)")
print("=" * 70)
for m in sorted(mode_param_set):
    tot = sum(mode_param_set[m].values())
    if tot == 0:
        continue
    label = BLEND_MODE_LABELS.get(m, f"mode={m}")
    print(f"\n[{label}] 共 {tot}")
    # 显示 top 8 param
    top = mode_param_set[m].most_common(10)
    for p, n in top:
        print(f"   param={p:6d}: {n} 次  ({n/tot*100:4.1f}%)")

print("\n" + "=" * 70)
print("'强混合' entry (非 0 混合模式 layer >= 1, 排 top 15)")
print("=" * 70)
entry_strong.sort(key=lambda x: -x[1])
for i, strong_n, layers in entry_strong[:15]:
    print(f"\n#{i}  强混合图层 {strong_n}:")
    for slot, t, m, p in layers:
        flag = "*" if (m in (1, 3, 4, 5) or (m == 2 and p != 0)) else " "
        label = BLEND_MODE_LABELS.get(m, str(m))
        print(f"   {flag} slot#{slot} t={t} blend={label:14s} param={p}")

print("\n" + "=" * 70)
print("mode=2 (半透) param 是否主要为 0?")
print("=" * 70)
m2 = mode_param_set[2]
if m2:
    zero = m2.get(0, 0)
    tot = sum(m2.values())
    print(f"param=0: {zero}/{tot} = {zero/tot*100:.1f}%")
    print("  (mode=2 param=0 在 sub_4559D0 走 sub_455B98/sub_456150 即 '正常 blit',")
    print("   这与 mode=0 视觉等效 → 数据层意图为'正常', 预览不加效果是对的)")
    print(f"param!=0 (真半透): {tot - zero} 次")
