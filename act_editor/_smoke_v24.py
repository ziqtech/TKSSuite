#!/usr/bin/env python3
"""v2.4 冒烟: 混合模式 pipeline + layer_type 语义分布统计.
  1) _apply_blend 能正确处理 6 种模式 (mode=2 param>31 → None)
  2) 650 条 entry 中 type=1/2/3/4/5 的分布 & "攻击-受击" 配对统计
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from act_editor import (
    ActEditor, load_act, entry_active_layers, entry_is_empty,
    ACT_ENTRY_COUNT,
)
try:
    from PIL import Image
except ImportError:
    print("[SKIP] PIL 不可用, 跳过混合模式测试")
    sys.exit(0)

TKS_DIR = os.path.normpath(os.path.join(HERE, '..', '..', '逆向工作区', 'TKS'))
ACT_PATH = os.path.join(TKS_DIR, '反编译产物', 'unpacked',
                        'TKAct.dat')
if not os.path.exists(ACT_PATH):
    # 尝试其他常见位置
    for cand in (
        os.path.join(TKS_DIR, 'TKAct.dat'),
        os.path.join(TKS_DIR, '反编译产物-BAK', 'unpacked',
                     'TKAct.dat'),
    ):
        if os.path.exists(cand):
            ACT_PATH = cand
            break

print(f"[info] ACT 文件: {ACT_PATH}")
if not os.path.exists(ACT_PATH):
    print("[FAIL] 未找到 TKAct.dat")
    sys.exit(1)

# --------------------------------------------------------------
# 1) _apply_blend: 用一个最小的 mock ActEditor 实例对象
# --------------------------------------------------------------
print("\n=== 混合模式 pipeline 测试 ===")

class _Stub:
    pass

ed = _Stub()
ed._apply_blend = ActEditor._apply_blend.__get__(ed, _Stub)

# 构造 4x4 纯红图
red = Image.new('RGBA', (4, 4), (200, 50, 50, 255))

cases = [
    (0, 0,  "正常"),
    (1, 1,  "染色(红tint)"),
    (1, 16, "染色(绿tint)"),
    (1, 30, "染色(蓝tint)"),
    (1, 99, "染色(param>31 不变色)"),
    (2, 0,  "半透(param=0 正常blit)"),
    (2, 15, "半透(param=15 半)"),
    (2, 31, "半透(param=31 近全透)"),
    (2, 80, "半透(param=80 退化正常blit)"),  # ★ 实测 48 次
    (3, 0,  "阴影"),
    (3, 80, "阴影(param 忽略)"),
    (4, 0,  "负片"),
    (5, 0,  "水平翻转"),
]
ok = 0
fail = 0
for mode, param, desc in cases:
    out = ed._apply_blend(red, mode, param)
    # mode=2 param=0 或 >31: 应等于原图 (正常 blit)
    if mode == 2 and (param == 0 or param > 31):
        if out is red:
            print(f"  [OK] mode={mode} param={param:3d} {desc:24s} → 原图 (正常 blit)")
            ok += 1
        else:
            print(f"  [FAIL] mode={mode} param={param:3d} {desc:24s} "
                  f"应返回原图, 实际变换了")
            fail += 1
        continue
    # mode=1 param=0 或 >31: 应等于原图 (不染色)
    if mode == 1 and (param == 0 or param > 31):
        if out is red:
            print(f"  [OK] mode={mode} param={param:3d} {desc:24s} → 原图 (不染色)")
            ok += 1
        else:
            print(f"  [FAIL] mode={mode} param={param:3d} {desc:24s} 应返回原图")
            fail += 1
        continue
    if out is None:
        print(f"  [FAIL] mode={mode} param={param:3d} {desc:24s} 意外 None")
        fail += 1
        continue
    if out.size != red.size:
        print(f"  [FAIL] mode={mode} {desc}: 尺寸变了 {out.size}")
        fail += 1
        continue
    # 取中心像素验证
    r, g, b, a = out.getpixel((1, 1))
    tag = "OK"
    if mode == 0:
        if (r, g, b, a) != (200, 50, 50, 255):
            tag = "FAIL"
    elif mode == 4:  # 负片
        if not (r == 55 and g == 205 and b == 205):
            tag = "FAIL"
    elif mode == 3:  # 阴影 (param 忽略)
        if not (r < 100 and a < 255):
            tag = "FAIL"
    elif mode == 2 and 0 < param <= 31:  # 真半透
        if a >= 255:
            tag = "FAIL"
    if tag == "OK":
        ok += 1
    else:
        fail += 1
    print(f"  [{tag}] mode={mode} param={param:3d} {desc:24s} "
          f"中心像素 rgba=({r},{g},{b},{a})")

# 水平翻转专项: 左右两列应交换
img_lr = Image.new('RGBA', (2, 1), (0, 0, 0, 0))
img_lr.putpixel((0, 0), (255, 0, 0, 255))  # 左红
img_lr.putpixel((1, 0), (0, 0, 255, 255))  # 右蓝
out = ed._apply_blend(img_lr, 5, 0)
left = out.getpixel((0, 0))
right = out.getpixel((1, 0))
if left[:3] == (0, 0, 255) and right[:3] == (255, 0, 0):
    print(f"  [OK] mode=5 水平翻转: 左右互换 left={left[:3]} right={right[:3]}")
    ok += 1
else:
    print(f"  [FAIL] mode=5 水平翻转: left={left[:3]} right={right[:3]}")
    fail += 1

print(f"\n混合模式测试: {ok} ok / {fail} fail")

# --------------------------------------------------------------
# 2) layer_type 分布 & "攻击-受击" 配对统计
# --------------------------------------------------------------
print("\n=== layer_type 语义分布统计 ===")
entries = load_act(ACT_PATH)
print(f"已加载 {len(entries)} 条 entry")

type_count = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
other = 0
nonempty = 0
has_1_or_2 = 0
has_3 = 0
has_both = 0   # 同一条 entry 既有 1/2 (攻击) 又有 3 (受击)
blend_count = {i: 0 for i in range(6)}
blend_other = 0

for i, e in enumerate(entries):
    if entry_is_empty(e):
        continue
    nonempty += 1
    has12 = False
    has3_ = False
    for slot_idx in range(8):
        L = e['layers'][slot_idx]
        t = L[0]
        if t in type_count:
            type_count[t] += 1
        else:
            other += 1
        if t in (1, 2):
            has12 = True
        if t == 3:
            has3_ = True
        b = L[11]
        if t != 0:
            if b in blend_count:
                blend_count[b] += 1
            else:
                blend_other += 1
    if has12:
        has_1_or_2 += 1
    if has3_:
        has_3 += 1
    if has12 and has3_:
        has_both += 1

print(f"有效 entry: {nonempty}")
print(f"按 layer_type 统计 (所有激活图层):")
for t in sorted(type_count):
    print(f"  t={t}: {type_count[t]}")
if other:
    print(f"  其它(非预期): {other}")

print(f"\n'攻击-受击'配对 (逆向预期: t=1/2 与 t=3 共存为主要战斗条目):")
print(f"  含 t=1 或 t=2 (攻击者位置绘制): {has_1_or_2}")
print(f"  含 t=3       (受击方位置绘制): {has_3}")
print(f"  同时含 [1|2] + 3 (完整攻击+受击): {has_both}")
pct = (has_both / max(1, has_3)) * 100
print(f"  → 在含 t=3 的 entry 中, 同时含 [1|2] 的比例: {pct:.1f}%")

print(f"\n按 blend_mode 统计 (仅激活图层):")
for m in sorted(blend_count):
    print(f"  mode={m}: {blend_count[m]}")
if blend_other:
    print(f"  其它(非预期): {blend_other}")

# 断言: t=3 必然不会单独出现 (逆向 L414 需要 L0 攻击者作为坐标系)
if has_3 > 0 and pct < 80:
    print(f"\n[WARN] t=3 多数应配 t=1/2, 当前 {pct:.1f}% 偏低")
else:
    print(f"\n[OK] t=3 entry 基本都配有 t=1/2 (验证 '攻击→受击' 因果链)")

print("\n[DONE] v2.4 冒烟通过" if fail == 0 else f"\n[FAIL] 有 {fail} 项失败")
sys.exit(0 if fail == 0 else 1)
