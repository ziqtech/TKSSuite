# TKItem.battle_anim 字段关联关系分析报告

## 概述

分析 TKItem.dat 中 `battle_anim` 字段（offset 12, v15[6]）在战斗中的实际关联目标：是直接关联 TKKon.dat 还是 TKAct.dat？以及三者之间的完整关联链路。

---

## 一、三个数据文件概览

| 文件 | 记录数 | 单条大小 | 总大小 | 格式 |
|------|--------|----------|--------|------|
| TKItem.dat | 600 条 | 64 字节 (32×int16) | 38,400 字节 | LZSS 压缩 |
| TKKon.dat | 650 条 | 40 字节 (20×int16) | 26,000 字节 | LZSS 压缩 |
| TKAct.dat | 650 条 | 784 字节 | 509,600 字节 | 原始读取 |

### 加载入口（反编译证据）

**TKItem.dat** — `sub_45343C(aTkitemDat, word_77CBCA, 38400)`  
**TKKon.dat** — `sub_45343C(aTkkonDat, &unk_9D0698, 26000)` (sub_4173F8)  
**TKAct.dat** — `sub_452544(aTkactDat, &unk_9539CA, 509600)` (sub_411624)

---

## 二、TKItem 字段定义

TKItem 共 32 个 int16 字段 (64 字节)，其中 `battle_anim` 位于：

```
字段名:    battle_anim
偏移:      12 (字节) / int16[6]
类型:      int16
Maker UI:  "战场动画"
语义:      战斗中使用物品时的动画效果/攻击范围参数
```

---

## 三、数据实证：battle_anim 的值域分析

### 3.1 统计概览

| 指标 | 数值 |
|------|------|
| 总物品数 | 600 条 |
| battle_anim = 0（无动画） | 568 条 |
| battle_anim ≠ 0 | **32 条** |
| 非零值范围 | **539 ~ 643** |
| 唯一值数量 | **16 个** |

### 3.2 全部 16 个唯一值

```
[539, 540, 541, 542, 543, 544, 545, 546, 547, 548, 549, 550, 551, 640, 641, 643]
```

所有值均在 **TKKon.dat 的索引范围 (0..649)** 内。

### 3.3 非零 battle_anim 的物品完整列表

#### 药品类 (page=0, tab_code=0)

| Item # | item_id | battle_anim | → TKKon | cond_id | → TKAct | 关键参数 |
|--------|---------|-------------|---------|---------|---------|----------|
| 0 | 8037 | 544 | #544 | 544 | #544 | exec_mode=512, exec_flags=3 |
| 1 | 8038 | 543 | #543 | 543 | #543 | exec_mode=512, exec_flags=3 |
| 2 | 8039 | 541 | #541 | 541 | #541 | exec_mode=512, exec_flags=3 |
| 3 | 8096 | 541 | #541 | 541 | #541 | exec_mode=512, exec_flags=3 |
| 4 | 8092 | 544 | #544 | 544 | #544 | exec_mode=512, exec_flags=3 |
| 5 | 101 | 539 | #539 | 539 | #539 | exec_mode=512, exec_flags=3 |
| 6 | 102 | 539 | #539 | 539 | #539 | exec_mode=512, exec_flags=3 |
| 7 | 103 | 539 | #539 | 539 | #539 | exec_mode=512, exec_flags=3 |
| 8 | 104 | **640** | #640 | **539** | #539 | exec_mode=**768(dist=3)**, exec_flags=3 |
| 9 | 105 | 540 | #540 | 540 | #540 | exec_mode=512, exec_flags=3 |
| 10 | 106 | 540 | #540 | 540 | #540 | exec_mode=512, exec_flags=3 |
| 11 | 107 | 540 | #540 | 540 | #540 | exec_mode=512, exec_flags=3 |
| 12 | 108 | **641** | #641 | **540** | #540 | exec_mode=**768(dist=3)**, exec_flags=3 |
| 13 | 109 | 543 | #543 | 543 | #543 | exec_mode=512, exec_flags=3 |
| 14 | 110 | 544 | #544 | 544 | #544 | exec_mode=512, exec_flags=3 |
| 15 | 111 | 543 | #543 | 543 | #543 | exec_mode=512, exec_flags=3 |
| 16 | 112 | 544 | #544 | 544 | #544 | exec_mode=512, exec_flags=3 |
| 17 | 113 | 542 | #542 | 542 | #542 | exec_mode=512, exec_flags=3 |
| 18 | 114 | 542 | #542 | 542 | #542 | exec_mode=512, exec_flags=3 |
| 19 | 115 | 545 | #545 | 545 | #545 | exec_mode=512, exec_flags=3 |
| 20 | 116 | 546 | #546 | 546 | #546 | exec_mode=512, exec_flags=3 |
| 21 | 117 | 547 | #547 | 547 | #547 | exec_mode=512, exec_flags=3 |
| 22 | 118 | 543 | #543 | 543 | #543 | exec_mode=512, exec_flags=3 |
| 23 | 119 | 542 | #542 | 542 | #542 | exec_mode=512, exec_flags=3 |
| 24 | 120 | 542 | #542 | 542 | #542 | exec_mode=512, exec_flags=3 |

#### 道具类 (page=1, tab_code=1)

| Item # | item_id | battle_anim | → TKKon | cond_id | → TKAct | 关键参数 |
|--------|---------|-------------|---------|---------|---------|----------|
| 50 | 6001 | 541 | #541 | 541 | #541 | exec_mode=512, exec_flags=3 |
| 54 | 8029 | 548 | #548 | 548 | #548 | exec_mode=512, exec_flags=3 |
| 57 | 8070 | **643** | #643 | **541** | #541 | hp_restore=1100, mp_restore=1100, exec_flags=3 |
| 58 | 8071 | 551 | #551 | 551 | #551 | exec_mode=1536, damage_base=500, exec_flags=3 |
| 64 | 8098 | 550 | #550 | 550 | #550 | exec_mode=-256(self), damage_base=500, exec_flags=3 |
| 65 | 8089 | 549 | #549 | 549 | #549 | exec_mode=-512, exec_flags=3 |
| 108 | 8171 | 541 | #541 | 541 | #541 | exec_mode=512, exec_flags=3 |

---

## 四、关联链路：三层结构

### 4.1 链路图

```
┌──────────────────────┐
│     TKItem.dat       │  物品属性数据库 (600 条)
│  ═══════════════════ │
│  item_id             │  物品唯一标识
│  name_id / desc_id   │  名称/说明 (→ TKT.dat)
│  icon                │  图标 (→ Mu.JVG)
│  equip_type          │  使用权限 (位掩码)
│                      │
│  battle_anim ────────┼──→ TKKon 记录索引 (直接)
│  (offset 12)         │
│                      │
│  hp_inc / hp_heal    │  生命上限/恢复
│  mp_inc / mp_heal    │  内力上限/恢复
│  atk/def/hit/dodge   │  属性加成
│  equip_learn         │  装备后学习技能 (→ TKSkill)
│  use_learn1/use_learn2│ 使用后学习技能 (→ TKSkill)
│  cause_mask/cure_mask│  状态导致/解除 (位掩码)
│  combat_flag         │  战斗结算效果
│  extra_flags         │  地图/遇敌标志
│  price               │  价格
└──────────┬───────────┘
           │ battle_anim 字段的值 = TKKon 记录索引
           ▼
┌──────────────────────┐
│     TKKon.dat        │  技能/动作参数数据库 (650 条)
│  ═══════════════════ │
│  exec_mode           │  执行模式 (高字节=攻击距离, 低字节=范围)
│  target_param        │  目标参数 (高字节=面积, 低字节=扩散)
│  target_filter       │  目标过滤 (格子类型 + 阵营匹配)
│                      │
│  cond_id ────────────┼──→ TKAct 条目索引 (间接)
│  (offset 6)          │
│                      │
│  damage_base         │  伤害基础值
│  mp_damage           │  内力伤害
│  accuracy            │  附加命中
│  extra_damage        │  附加伤害
│  hp_restore          │  HP 回复
│  mp_restore          │  MP 回复
│  inflict_status      │  导致状态 (位掩码)
│  remove_status       │  解除状态 (位掩码)
│  timing_mod          │  时序修正
│  exec_flags          │  执行标志 (bit0=可见, bit2=物理/魔法)
└──────────┬───────────┘
           │ cond_id 字段的值 = TKAct 条目索引
           ▼
┌──────────────────────┐
│     TKAct.dat        │  2D 精灵动画数据库 (650 条)
│  ═══════════════════ │
│  dirs[0..3]          │  4 方向绘制顺序 (z-order)
│  layers[0..7]        │  8 个图层 × 80 字节
│    ├─ layer_type     │    1=角色动作(Aa.jvg), 2=攻击特效(Af.jvg)
│    ├─ jvg_block_index│    3=受击特效, 4=锚点, 5=全屏特效
│    ├─ first/last_frame│   帧范围
│    ├─ tick_interval  │    帧停留时间
│    ├─ blend_mode     │    混合模式 (0=正常/1=染色/2=加法/3=减法/4=亮度融合/5=翻转)
│    ├─ x_off/y_off    │    位移偏移 (4 方向)
│    └─ direction_mode │    方向感知
│  tail[0..15]         │  音效触发表 (sound_id, trigger_tick)
└──────────────────────┘
```

### 4.2 关联方向总结

```
TKItem.battle_anim  ──(一级, 直接索引)──→  TKKon 记录
TKKon.cond_id       ──(二级, 间接索引)──→  TKAct 条目
```

**battle_anim 关联的是 TKKon.dat，不是 TKAct.dat。**

---

## 五、反编译证据

### 5.1 sub_4434BC — 动画运行时（核心函数）

```c
// sub_4434BC: 动画运行时, 调用者 sub_4458B0 (技能执行主函数)
char __cdecl sub_4434BC(__int16 a1)
{
    // ...
    if ( word_9D6C2E == -1 )
    {
        // 正常路径: 通过技能ID查表获取 TKKon 索引
        i = word_9D7494[527 * a1];       // a1=角色ID, 527字/角色 → TKKon 索引
        if ( !i )
            i = word_9D6C84;             // 默认值 (物品使用时设置为此值)
        
        // 关键行: 加载 TKAct 条目
        // word_9D069E = TKKon 基址(0x9D0698) + 6字节 = field[3] = cond_id
        // 9779658 = 0x9539CA = TKAct 基址
        // 784 = 每条 TKAct 条目大小
        qmemcpy(&unk_9D037A,
            (const void *)(784 * word_9D069E[20 * i] + 9779658), 0x310u);
        //                     ↑ cond_id                ↑ TKAct_base
    }
    else
    {
        // 覆写路径: 直接使用 word_9D6C2E 作为 TKAct 索引 (跳过 TKKon)
        qmemcpy(&unk_9D037A,
            (const void *)(784 * word_9D6C2E + 9779658), 0x310u);
    }
    // ...
}
```

### 5.2 内存布局验证

```
TKKon 基址:   0x9D0698  (sub_4173F8 加载)
word_9D069E = 0x9D0698 + 6 字节 = field[3] = cond_id 起始位置
word_9D069E[20 * i] = TKKon 记录 i 的 cond_id 值

TKAct 基址:   0x9539CA = 9779658 (sub_411624 加载)
784 * cond_id + 9779658 = TKAct 条目 #cond_id 的起始地址
```

### 5.3 sub_4458B0 — 技能执行主函数（多处引用）

```c
// 战斗中 AI/玩家选择动作后, 多次出现此模式:
word_9D6C7A = word_9D7494[527 * character_id];  // 查 TKKon 索引
if ( !word_9D6C7A )
    word_9D6C7A = word_9D6C84;                   // 默认后备值

// 读取 TKKon 记录 (40字节) 到战斗工作区
qmemcpy(&byte_9D6C28,
    (const void *)(40 * word_9D6C7A + 10290840), 0x28u);
//                ↑ TKKon 基址 0x9D0698
```

---

## 六、关键设计模式

### 6.1 同一动画 + 不同战斗参数

游戏中通过 **不同的 TKKon 记录指向同一个 TKAct 动画** 来实现"同一套视觉动画, 不同攻击参数"的效果:

| 场景 | TKKon 记录 | exec_mode | cond_id | TKAct 动画 | 效果 |
|------|-----------|-----------|---------|-----------|------|
| 药品近距离 | #539 | 512 (dist=2) | 539 | #539 | 2格距离 |
| 药品远距离 | #640 | 768 (dist=3) | 539 | #539 | 3格距离, 同一动画 |
| 道具 HP/MP | #541 | 512 (dist=2) | 541 | #541 | 标准恢复动画 |
| 道具 HP/MP 远 | #643 | -256 (self) | 541 | #541 | 自身目标, 同一动画 |

### 6.2 exec_flags=3 标识物品动作

所有被物品 `battle_anim` 引用的 TKKon 记录均设置 `exec_flags = 3`:
- **bit0 = 1**: 保持施法者待机动画
- **bit1 = 1**: 使用物品逻辑（非技能/非普通攻击）

TKKon 的 #539-#551 区间和 #640-#643 是专门为"物品在战斗中使用"而预留的动作槽位。

### 6.3 多物品共享同一动作

多个不同物品可以共用同一个 TKKon 记录（即相同的战斗参数和动画）：

| TKKon | 引用次数 | 物品（部分） |
|-------|---------|-------------|
| #539 | 3 次 | Item #5, #6, #7 (药品 101/102/103) |
| #540 | 3 次 | Item #9, #10, #11 (药品 105/106/107) |
| #541 | 4 次 | Item #2, #3, #50, #108 (药品/道具) |
| #542 | 4 次 | Item #17, #18, #23, #24 |
| #543 | 4 次 | Item #1, #13, #15, #22 |
| #544 | 4 次 | Item #0, #4, #14, #16 |

---

## 七、与 TKKon → TKAct 关系的区别

前次分析报告指出 TKKon 与 TKAct 之间是"多对一"关系, 但那是针对**所有 650 条记录**的全局视角。物品的 `battle_anim` 场景更加聚焦：

| 维度 | TKKon ↔ TKAct (全局) | TKItem → TKKon (物品场景) |
|------|----------------------|--------------------------|
| 映射方向 | TKKon.cond_id → TKAct | Item.battle_anim → TKKon |
| 基数 | 650 条 TKKon, 604 个唯一 cond_id | 32 个物品, 16 个唯一 TKKon |
| 复用程度 | 5 个 cond_id 被多条 TKKon 共享 | 16 个 TKKon 共享给 32 个物品 |
| 空引用 | 46 个 TKAct 未被引用 | 568 个物品无需动画 |

---

## 八、结论

1. **TKItem.battle_anim 是 TKKon.dat 的直接索引**，不是 TKAct.dat 的索引。

2. **完整的三级链路为：**
   ```
   TKItem.battle_anim → TKKon 记录 (战斗参数)
                    → TKKon.cond_id → TKAct 条目 (动画资源)
   ```

3. **TKKon 作为中间层**，承担了"战斗逻辑参数"与"视觉动画资源"的解耦角色。物品只需指定一个 TKKon 索引，TKKon 内部通过 cond_id 决定播放哪个 TKAct 动画。

4. **设计意图：** 同一套动画可以搭配不同的攻击参数（距离、范围、伤害值等），只需创建不同的 TKKon 记录指向同一个 TKAct 动画即可，避免为每种参数组合单独制作动画资源。

---

## 附录：相关文件路径

| 文件 | 路径 |
|------|------|
| TKItem.dat | `逆向工作区/TKItem.dat` |
| TKKon.dat | `逆向工作区/TKKon.dat` |
| TKAct.dat | `逆向工作区/TKAct.dat` |
| 物品编辑器 | `item_editor\item_editor.py` |
| Kon 编辑器 | `kon_editor\kon_editor.py` |
| Act 编辑器 | `act_editor\act_editor.py` |
| PE Dump | `运行时转储/` |

## 附录：关键反编译函数索引

| 函数 | 地址 | 功能 |
|------|------|------|
| sub_4173F8 | 0x4173F8 | TKKon/TKItem 等 DAT 文件统一加载入口 |
| sub_411624 | 0x411624 | 游戏初始化, 加载 TKAct/JVG 等资源 |
| sub_41E40C | 0x41E40C | 物品使用效果处理 (属性/技能/状态) |
| sub_4434BC | 0x4434BC | 动画运行时, TKKon.cond_id → TKAct 加载 |
| sub_4458B0 | 0x4458B0 | 战斗技能/物品执行主函数 |
| sub_4307CC | 0x4307CC | 战斗初始化, 设置 word_9D6C84 等默认值 |
