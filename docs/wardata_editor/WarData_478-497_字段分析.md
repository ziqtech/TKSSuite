# WarData.dat 偏移 478-497 字段完整分析

> 基于 TKS.exe 反编译 (sub_430578, sub_4307CC, sub_444FD4, sub_43CA64, sub_436BD4, sub_40EB10)
> 数据源: WarData.dat 219条原始记录
> 最后更新: 2026-05-25

---

## 一、字节布局

```
偏移      大小    地址标签          反编译引用                      语义
────────────────────────────────────────────────────────────────────────────
[478]     byte    byte_9539B6      sub_430578:17                   lv_spread_lo
[479]     byte    byte_9539B7      (无反编译引用, 全219条=0)        (保留/填充)
[480]     byte    byte_9539B8      sub_430578:18                   lv_spread_hi
[481]     byte    byte_9539B9      (无反编译引用, 全219条=0)        (保留/填充)
[482-483] uint16  word_9539BA      sub_43CA64:29,32,109            turn_limit
[484-497] byte[14]                  (无反编译引用, 全219条=0)        (保留)
```

### 数据统计

| 偏移 | 非零记录 | 值范围 | 说明 |
|------|---------|--------|------|
| 478 | 32/219 | 1-40 | 仅当有敌槽 lv_range.X==0 时非零 |
| 479 | 0/219 | 全0 | 永久为零 |
| 480 | 30/219 | 3-45 | 配合478一起使用 |
| 481 | 0/219 | 全0 | 永久为零 |
| 482-483 | 0/219 | 全0 | 原版无回合限制 |
| 484-497 | 0/219 | 全0 | 永久为零 |

---

## 二、lv_spread_lo (478) 和 lv_spread_hi (480) 语义

### 2.1 调用链

```
sub_40EB10(a1=battle_id, a2=use_avg_lv)
  └─ sub_436BD4(a1, a2)
       └─ sub_4307CC(a2)  ← 敌军初始化
            └─ sub_430578(enemy_data, enemy_power, lv_range_X, lv_range_Y, avg_lv)

sub_445564 → sub_444FD4  ← 增援敌军
            └─ sub_430578(enemy_data, enemy_power, lv_range_X, lv_range_Y, avg_lv)
```

### 2.2 sub_430578 完整算法

```c
// 参数:
//   a1 = 敌人运行时数据指针 (word_9D707A[527*slot])
//   a2 = enemy_power (属性加成倍率, offset 88+slot)
//   a3 = enemy_lv_range.X (offset 106+2*slot, int8)
//   a4 = enemy_lv_range.Y (offset 107+2*slot, int8)
//   a5 = avg_level (队伍平均等级, 0=禁用等级浮动)

void sub_430578(a1, a2, a3, a4, a5)
{
    // ── 步骤1: 等级参数回退 ──
    if (a3 == 0)                    // 该敌槽 lv_range.X 为0
    {
        a3 = byte_9539B6;           // → offset 478 (lv_spread_lo)
        a4 = byte_9539B8;           // → offset 480 (lv_spread_hi)
    }

    // ── 步骤2: 基于队伍平均等级的浮动 (430578.c:20-34) ──
    if (a5)                         // avg_level 启用时
    {
        // 幅度 v7: a3>=a4 时默认 3, 否则 a4-a3; 再钳制到 [2,5]
        v7 = (a3 >= a4) ? 3 : (a4 - a3);
        if (v7 < 2) v7 = 2;
        if (v7 > 5) v7 = 5;

        // 以队伍均等为中心, 上下浮动
        max_lv = a5 + v7;           // a4 = a5 + v7
        min_lv = a5 - v7;           // a3 = a5 - v7
        if (a5 == v7) min_lv = 1;   // 仅当 avg==v7 (min=0) 时置 1
    }
    else                            // avg_level 禁用 → a3,a4 直接作 [min,max]
    {
        min_lv = a3;
        max_lv = a4;
    }

    // ── 步骤3: 随机等级 ──
    if (min_lv >= max_lv)
        enemy_level = min_lv;
    else
        enemy_level = min_lv + rand() % (max_lv - min_lv + 1);

    // ── 步骤4: 赋值 ──
    sub_4302D8(a1, enemy_level, a2); // 将等级写入敌人数据, enemy_power控制属性倍率
}
```

### 2.3 avg_level 来源

sub_4307CC 中:
```c
if (a1)                             // a1 = sub_436BD4 的 a2 参数
    word_9D6C86 = v24;              // v24 = 友军等级平均值
else
    word_9D6C86 = 0;                // 禁用等级浮动
```

sub_40EB10 的调用路径决定 a2:
- `sub_40EBD4` 传 `a2=0` → 禁用等级浮动
- `sub_4084E0` 传 `a2=*(a2+248)` → 由存档/场景决定

### 2.4 语义总结

**lv_spread_lo 和 lv_spread_hi 不直接决定敌人等级。它们的差值 |hi-lo| 经过 clamp(2,5) 后，决定敌人等级围绕队伍平均等级的浮动幅度。**

当某个敌槽的 `enemy_lv_range.X == 0` 时：
1. 该系统用 lv_spread_lo/hi 替代该槽的 level params
2. spread = clamp(|hi-lo|, 2, 5) = 2~5
3. 敌人等级 = [avg - spread, avg + spread] 随机

当 `avg_level == 0`（禁用浮动）时：
- lv_spread_lo/hi 直接作为 [min, max] 等级范围使用

### 2.5 数据验证

全部32条记录中，|p2-p1| 的分布:

| |p2-p1| | clamp后 | 浮动范围 | 记录数 | 示例战场 |
|---------|--------|---------|---------|--------|
| 1 | 2 | ±2级 | 2 | #101, #155 |
| 2 | 2 | ±2级 | 2 | #154, #174 |
| 3 | 3 | ±3级 | 3 | #79, #163, #173 |
| 4 | 4 | ±4级 | 14 | #9-12, #77-78等 |
| 5 | 5 | ±5级 | 8 | #52-53, #59等 |
| 7 | 5 | ±5级 | 1 | #13 |

所有记录中，设置 lv_spread 的战场**均有敌槽 lv_range.X==0**，证实了"回退默认值"机制。

---

## 三、turn_limit (482-483) 语义

### 3.1 调用链

```
sub_40EB10 → sub_43CA64  ← 战斗回合主循环
```

### 3.2 sub_43CA64 关键逻辑

```c
while (!word_951940)               // 战斗未结束
{
    if (word_9539BA > 0)           // offset 482-483: turn_limit
    {
        if (当前回合数 / 每轮回合数 >= word_9539BA)
        {
            word_951940 = 2;       // 触发失败条件
            break;
        }
    }
    // ... 战斗逻辑 ...
}
```

- turn_limit == 0: 无回合限制（原版全部219场战斗均为0）
- turn_limit > 0: 超过该值后触发战斗失败 (word_951940=2)

在 case 1 (战斗胜利) 中也有检查:
```c
case 1:
    sub_43BFE8(1);                 // 胜利处理
    if (word_9539BA > 0 && 回合数 <= word_9539BA)
        word_951940 = -2;          // 仍在限制内, 转为失败
    break;
```

### 3.3 语义总结

**turn_limit 是一个回合数阈值。>0时，若战斗回合超过该值，判定为失败。原版全部219场战斗均未设置（全为0），该字段供 mod 使用。**

---

## 四、未引用字节

| 偏移 | 大小 | 状态 |
|------|------|------|
| 479 | byte | 全219条=0, 无反编译引用 |
| 481 | byte | 全219条=0, 无反编译引用 |
| 484-497 | byte[14] | 全219条=0, 无反编译引用 |

这些字节出现在已确认字段的间隙中，可能的原因:
1. 编译器对齐填充 (struct alignment/padding)
2. 预留字段（从未被实现）
3. 原游戏使用不同版本的 WarData 结构

无论如何，它们在运行时不会被任何函数读取。编辑器通过 `_raw` 保留原始值并原样写回。

---

## 五、字段命名对照

| 偏移 | 旧名称 | 新名称 | 理由 |
|------|--------|--------|------|
| 478 | default_lv_p1 | **lv_spread_lo** | 与 hi 的差值决定等级浮动幅度，非直接等级值 |
| 480 | default_lv_p2 | **lv_spread_hi** | 同上 |
| 482-483 | battle_turn_limit | **turn_limit** | 无变化，语义确认正确 |
