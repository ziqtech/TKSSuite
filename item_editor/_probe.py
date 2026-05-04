#!/usr/bin/env python3
"""TKItem 字段实测 - 查找蝉翼刀/遁甲天书验证 [22]=装备后学习技能 假说"""
import struct, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from item_editor import lzss_decompress, load_tkt, load_tkskill_names

TKS = r"逆向工作区"
with open(os.path.join(TKS, 'TKItem.dat'), 'rb') as f: dec = lzss_decompress(f.read())
print(f"解压 {len(dec)} B, {len(dec)//64} 条")
tkt = load_tkt(os.path.join(TKS, 'TKT.dat'))
skills = load_tkskill_names(os.path.join(TKS, 'TKSkill.dat'), tkt)
print(f"TKT {len(tkt)} 条, 技能 {len(skills)} 条")

recs = []
for i in range(600):
    off = i * 64
    f32 = struct.unpack_from('<' + 'h'*32, dec, off)
    recs.append({'idx': i, 'f': list(f32)})

# 名字反查: tkt_id -> item_index
def name_of(rec):
    nid = rec['f'][2]
    return tkt.get(nid, f"(no TKT #{nid})")

# 找用户提到的物品
targets = ["蟬翼刀","蝉翼刀","遁甲天書","遁甲天书","虎紋刀","虎纹刀","修羅刀","修罗刀"]
print("\n=== 目标物品查找 (按 TKT 物品名) ===")
for t in targets:
    for r in recs:
        nm = name_of(r)
        if t in nm:
            f = r['f']
            print(f"★ {t} -> record #{r['idx']} '{nm}' item_id={f[0]} equip_type={f[5]}")
            print(f"  [21]attach_skill={f[21]} name={skills.get(f[21],'?')}")
            print(f"  [22]equip_learn ={f[22]} name={skills.get(f[22],'?')}")
            print(f"  [23]use_learn_1 ={f[23]} name={skills.get(f[23],'?')}")
            print(f"  [24]use_learn_2 ={f[24]} name={skills.get(f[24],'?')}")
            print(f"  [26]={f[26]:#06x}  [27]={f[27]:#06x}  [28]={f[28]:#06x}  [29]={f[29]:#06x}  [30]={f[30]:#06x}")
            break

# 列出所有 f[22] 非零的物品, 确认 [22] 值都是合理技能索引 (0-349)
print("\n=== 所有 f[22] 非零记录 (装备后学习技能候选) ===")
cnt22 = 0
for r in recs:
    f = r['f']
    if f[22] != 0 and 0 < f[22] < 350:
        nm = name_of(r)
        sn = skills.get(f[22], '?')
        print(f"  #{r['idx']:3d} id={f[0]:5d} equip_type={f[5]:3d}  '{nm[:20]}'  [22]={f[22]:3d} -> 技能={sn}")
        cnt22 += 1
print(f"  合计 {cnt22} 条有效 [22]")

# 列出所有 f[21] 非零的物品以对比
print("\n=== 所有 f[21] 非零记录 (附加技能) 前20条 ===")
cnt21 = 0
for r in recs:
    f = r['f']
    if f[21] != 0 and 0 < f[21] < 350:
        nm = name_of(r)
        sn = skills.get(f[21], '?')
        if cnt21 < 20:
            print(f"  #{r['idx']:3d} id={f[0]:5d} equip_type={f[5]:3d}  '{nm[:20]}'  [21]={f[21]:3d} -> 技能={sn}")
        cnt21 += 1
print(f"  合计 {cnt21} 条有效 [21]")

# 列出所有 f[23] 非零的物品
print("\n=== 所有 f[23] 非零记录 (使用后学习技能1) ===")
cnt23 = 0
for r in recs:
    f = r['f']
    if f[23] != 0 and 0 < f[23] < 350:
        nm = name_of(r)
        sn = skills.get(f[23], '?')
        print(f"  #{r['idx']:3d} id={f[0]:5d} equip_type={f[5]:3d}  '{nm[:20]}'  [23]={f[23]:3d} -> 技能={sn}")
        cnt23 += 1

# 列出所有 f[24] 非零的物品
print("\n=== 所有 f[24] 非零记录 (使用后学习技能2) ===")
cnt24 = 0
for r in recs:
    f = r['f']
    if f[24] != 0 and 0 < f[24] < 350:
        nm = name_of(r)
        sn = skills.get(f[24], '?')
        print(f"  #{r['idx']:3d} id={f[0]:5d} equip_type={f[5]:3d}  '{nm[:20]}'  [24]={f[24]:3d} -> 技能={sn}")
        cnt24 += 1

# 空槽判定
print("\n=== 记录头尾扫描 (空槽识别) ===")
for i in [0, 100, 400, 500, 540, 545, 549, 550, 551, 555, 559, 560, 570, 580, 590, 599]:
    f = recs[i]['f']
    nm = name_of(recs[i])
    tag = ''
    if f[0] == 0 and f[2] == 0: tag = ' <空槽 (item_id=0 & name_id=0)>'
    elif f[0] == 1: tag = ' <id=1 占位>'
    elif f[0] == 0: tag = ' <id=0 但 name_id非零>'
    print(f"  #{i:3d}  id={f[0]:5d} tab={f[1]:3d} name_id={f[2]:5d} desc_id={f[3]:5d} '{nm[:20]}'{tag}")

# 全部空槽统计
print("\n=== 空槽统计 ===")
empty_by_id0 = [r['idx'] for r in recs if r['f'][0] == 0]
empty_by_id1 = [r['idx'] for r in recs if r['f'][0] == 1]
empty_by_both = [r['idx'] for r in recs if r['f'][0] == 0 and r['f'][2] == 0]
print(f"  item_id==0 的记录: {len(empty_by_id0)} 条, 范围 {empty_by_id0[0] if empty_by_id0 else '-'}..{empty_by_id0[-1] if empty_by_id0 else '-'}")
print(f"  item_id==1 的记录: {len(empty_by_id1)} 条")
print(f"  (id==0 AND name_id==0) 的记录: {len(empty_by_both)} 条")
# 检查 #550 是什么
if len(recs) > 550:
    f = recs[550]['f']
    print(f"  #550 详情: id={f[0]} tab={f[1]} name_id={f[2]} desc_id={f[3]} name='{name_of(recs[550])}'")

# f[26]/f[27] 非零分布 (用来判断是防御还是状态 mask)
print("\n=== f[26]/f[27] 非零记录 (可能是远程/法术防御 或 导致状态 mask) ===")
for r in recs:
    f = r['f']
    if f[26] != 0 or f[27] != 0:
        nm = name_of(r)
        print(f"  #{r['idx']:3d} id={f[0]:5d} eq={f[5]:3d}  '{nm[:18]}'  [26]={f[26]:>6d}({f[26]&0xffff:#06x})  [27]={f[27]:>6d}({f[27]&0xffff:#06x})")
