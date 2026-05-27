# Attribute 与 GetItem 双轨物品系统分析

> 以实体 #1297（type 110 特殊机关）为例，分析 `Attribute(-1, 11, 1)` 与 type 110 掉落系统的协同工作机制。基于 `运行时转储` 反编译代码交叉验证。

---

## 一、现象与问题

实体 1297 是一个 type 110（特殊机关）实体，场景 2，坐标 (785, 567)。玩家点击交互后：

1. **获得"晶礦" 1 个**（进入物品栏）
2. **特殊物品收集度 +1**（全局数值计数）

但其 B 链脚本仅有一行：

```cpp
{;1 #Define
Attribute(-1, 11, 1)
End(2)
};1 #Define end
```

**问题：`Attribute(-1, 11, 1)` 的逆向实现仅递增 `word_757F00` 计数器，并未调用物品添加函数。那么"晶礦"物品到底是在哪里加入的？**

---

## 二、实体 1297 完整数据

### 2.1 基本字段

| 字段 | 值 | 含义 |
|------|-----|------|
| d0 | 110 | type = 特殊机关 |
| d1 | 2 | 场景 2 |
| d2 | 7 | flags: bit0=启用, bit1=可见, bit2=可交互 |
| d10, d11 | 785, 567 | 坐标 |
| d31 (max_B) | 1 | B 链 1 个子场景 |
| d34 (cur_B) | 1 | 当前子场景 1 |
| d40 (head_B) | 1493 | DefUnit 入口 |

### 2.2 Type 110 专属字段（物品掉落配置）

Type 110 实体的字段语义与默认不同（逆向依据：`sub_408B30`）：

| 字段 | DWORD 值 | type 110 语义 | 说明 |
|------|---------|--------------|------|
| d52 | 1 | **行为模式** | 1 = 清除标志（交互后实体消失） |
| d53 | 8080 | **组1 - 物品ID下限** | 随机物品 ID 最小值 |
| d54 | 8080 | 组1 - 物品ID上限 | 与下限相同 → 固定为 8080 |
| d55 | 1 | **组1 - 数量下限** | 随机数量最小值 |
| d56 | 1 | 组1 - 数量上限 | 与下限相同 → 固定为 1 |
| d57~d60 | 0 | 组2（未配置） | → 无掉落 |
| d61~d64 | 0 | 组3（未配置） | → 无掉落 |

> **每组随机规则**（`sub_408B30`）：物品 ID = Random(Xmin, Xmax)，数量 = Random(Ymin, Ymax)。若 Xmin==Xmax 且 Ymin==Ymax，则为固定掉落。

---

## 三、双路径执行流程

玩家点击实体 1297 时，`sub_408E5C`（玩家交互处理）按以下顺序执行：

```
sub_408E5C()
    │
    ├─ 1. 检查交互条件 (sub_40818C) → 通过
    │
    ├─ 2. B 链遍历 (sub_4066F0)
    │      cur_B=1 → DefUnit[1493] → DEFINE 85000448
    │
    ├─ 3. B 链脚本执行 (sub_40EBD4)
    │      Attribute(-1, 11, 1)
    │      → sub_40E11C(-1, 11, 1)
    │      → case 11: word_757F00 += 1
    │      ★ 特殊物品收集度 +1
    │
    └─ 4. Type 110 处理 (sub_408B30)
          读取 d53=8080, d55=1 → GetItem(8080, 1)
          → sub_40CE30(8080, 1, 1)
          ★ 晶礦加入物品栏
          d52=1 → 清除实体 flags (实体消失)
```

### 3.1 证据：sub_408E5C 中的 B 链 + type 110 调用

```c
// 408E5C.c 第 63-76 行（简化）
if (sub_40818C(player, target)) {
    if (entity[136]) {                    // cur_B > 0
        sub_4066F0(entity, 1);           // 遍历 B 链
        sub_40EBD4(entity_id);           // ★ 执行 B 链脚本
    }
    if (type == 110)
        sub_408B30(entity_id, entity);    // ★ type 110 物品掉落
}
```

---

## 四、GetItem 实现（`sub_40CE30` opcode 40）

### 4.1 物品存储结构

```c
// 40CE30.c 逆向简化
__int16 sub_40CE30(__int16 item_id, __int16 qty, __int16 show_msg)
{
    // === 金钱 (item_id = 10000) ===
    if (item_id == 10000) {
        word_756882 += qty;              // 金钱累加，上限 30000
        if (show_msg && qty > 0)
            sub_40B1B4(9, 26, 40, ...);  // SysTalk: "获得 XXX 钱"
        return;
    }

    // === 普通物品 ===
    // 物品库存: word_7570AA[] = 物品ID数组, word_757A0A[] = 数量数组
    // word_7570A8 = 当前物品种类数

    // 查找是否已有该物品
    for (i = word_7570AA; i < word_7570AA + word_7570A8; i++) {
        if (*i == item_id) {
            i[1200] += qty;              // 数量叠加（上限 99）
            return;
        }
    }

    // 新物品：追加到库存
    if (qty >= 0) {
        word_7570AA[word_7570A8] = item_id;
        word_757A0A[word_7570A8] = qty;
        // 查找物品在 item_db 中的索引
        v12 = find_in_item_db(item_id);  // word_77CBCA[32*x]
        word_75755A[word_7570A8++] = v12;

        if (show_msg && qty > 0) {
            // 获取物品名并弹出 SysTalk 通知
            word_75607E = word_77CBCE[32 * v12];  // 物品名 TKT ID
            sub_40B1B4(10, 26, 40, ...);  // SysTalk: "获得 XXX"
        }
    }

    // qty == -1: 从队伍成员装备中移除物品
    if (qty == -1) {
        for each party member {
            remove_equipped_item(item_id);
        }
    }
}
```

### 4.2 物品系统内存布局

```
物品数据库 (item_db):
  word_77CBCA[32 * 600]   ← 600 种物品，每条 32 words
    [0]: item_id
    [...]: 物品属性
    word_77CBCE[32 * idx]  ← 物品名称 TKT 文本 ID

玩家库存:
  word_7570A8             ← 当前物品类别数
  word_7570AA[0..N]       ← 物品 ID 数组
  word_757A0A[0..N]       ← 对应数量数组（上限 99）
  word_75755A[0..N]       ← 物品在 item_db 中的索引

队伍成员装备:
  0x757D32[1054 * member_id]  ← 每个成员 1054 字节
    offset 0: 装备槽 0..3 (4 个 int16)
```

---

## 五、Attribute 实现与参数映射

### 5.1 实现代码（`sub_40E11C` opcode 48）

```c
__int16 sub_40E11C(__int16 entity_id, __int16 attr_id, __int16 delta)
{
    // entity_id: -1=玩家/全局, >=0=特定角色
    // attr_id: 属性编号
    // delta: 变化量

    if (entity_id < -1 || entity_id > 35) return;

    switch (attr_id) {
        case 1:   // 生命
            word_757F3E[527 * entity_id] += delta;  // 角色: 属性1
            word_756884 += delta;                    // 玩家: 属性1
            if (delta > 0) sub_40B1B4(2, 21, 50, 1, 0, 0);  // 恢复提示

        case 2:   // 内力
            word_757F40[527 * entity_id] += delta;
            word_756886 += delta;
            if (delta > 0) sub_40B1B4(3, 21, 50, 1, 0, 0);

        case 3:   // 属性3
            word_757F42[527 * entity_id] += delta;
            word_756888 += delta;
            if (delta > 0) sub_40B1B4(4, 21, 50, 1, 0, 0);

        case 4:   // 属性4
            word_757F44[527 * entity_id] += delta;
            word_75688A += delta;
            if (delta > 0) sub_40B1B4(5, 21, 50, 1, 0, 0);

        case 10:  // ★ 全局计数器 A
            word_757EFE += delta;
            break;  // ← 无 SysTalk 通知

        case 11:  // ★ 全局计数器 B（特殊物品收集度）
            word_757F00 += delta;
            break;  // ← 无 SysTalk 通知，无 GetItem 调用

        case 5:   // 角色属性5 (有上限)
            word_757F12[527 * entity_id] += delta;
            sub_40DFE4(entity_id);  // 钳位到上限

        case 6:   // 角色属性6 (有上限)
            word_757F14[527 * entity_id] += delta;
            sub_40DFE4(entity_id);

        default:  // 未列出的属性
            if (entity_id >= 0)
                sub_40DFE4(entity_id);
            else  // entity_id == -1: 遍历队伍成员递归调用
                for each party member
                    sub_40E11C(member_id, attr_id, delta);
    }
}
```

### 5.2 关键发现：Attribute 不涉及物品系统

- `case 10` 和 `case 11` **只修改 `word_757EFE` / `word_757F00`，不调用 `sub_40CE30`（GetItem）**
- `case 1~4` 会调用 `sub_40B1B4` 弹出 SysTalk 提示（恢复 HP/MP 的浮动文字），但也**不涉及物品库存**
- `default` 分支会遍历队伍成员递归调用，适用于队伍级别的属性变化

---

## 六、CheckTeam 参数映射（属性语义验证）

`sub_40E65C`（CheckTeam，opcode 63）读取各属性当前值进行比较，揭示了每个 Attribute ID 的语义：

| CheckTeam type | 读取的变量 | 语义 |
|---------------|-----------|------|
| 1 | `word_75688C[]` | 检查指定成员是否在队伍中 |
| 2 | `word_756884` | 玩家属性 1（可能是等级或生命上限） |
| 3 | `word_756886` | 玩家属性 2（可能是内力上限） |
| 4 | `word_756888` | 玩家属性 3 |
| 5 | `count_party_members()` | 当前队伍人数 |
| 6 | `word_75688A` | 玩家属性 4 |
| 10 | `word_757EFE` | 全局计数器 A |
| 11 | `word_757F00` | 全局计数器 B（**特殊物品收集度**） |
| 12 | `word_757EBA` | 全局计数器 C |
| 13 | `word_757EBC` | 全局计数器 D |
| 14 | `word_757EBC + word_757EBA` | 计数器 C + D 之和 |
| 15 | `word_757EBE` | 全局计数器 E |

---

## 七、Type 110 物品掉落配置（`sub_408B30`）

### 7.1 三组掉落槽

实体 DWORD 字段在 type 110 下的重映射：

| 组 | 物品ID范围 | 数量范围 |
|----|-----------|---------|
| 组1 | d53 (Xmin) ~ d54 (Xmax) | d55 (Ymin) ~ d56 (Ymax) |
| 组2 | d57 (Xmin) ~ d58 (Xmax) | d59 (Ymin) ~ d60 (Ymax) |
| 组3 | d61 (Xmin) ~ d62 (Xmax) | d63 (Ymin) ~ d64 (Ymax) |

### 7.2 执行逻辑（`408B30.c` 简化）

```c
int sub_408B30(int entity_id, int entity)
{
    // 1. 检查是否已经拿过 (d9 bit0)
    if (entity[9] & 1)
        return SysTalk("该物品已经拿过了");

    // 2. 生成 3 组随机物品
    // 组1
    if (entity[53] && entity[55]) {
        item1 = random(entity[53], entity[54]);  // 8080
        qty1  = random(entity[55], entity[56]);  // 1
    }
    // 组2, 组3 同理...

    // 3. 调用 GetItem 添加物品
    if (item1 && qty1) sub_40CE30(item1, qty1, 1);  // ★ 物品加入库存
    if (item2 && qty2) sub_40CE30(item2, qty2, 1);
    if (item3 && qty3) sub_40CE30(item3, qty3, 1);

    // 4. 根据 d52 行为模式处理实体
    if (entity[52] == 0) {
        // 随机掉落模式: 设置帧计数器, flags bit8
    } else if (entity[52] == 1) {
        // 清除标志模式: 清除 flags bit0+bit1 (实体消失)
    }
}
```

### 7.3 实体 1297 的实际掉落

```
d53=8080, d54=8080  → item1 = 8080 (固定)
d55=1, d56=1        → qty1 = 1 (固定)
d57~d64 = 0         → 组2、组3 无掉落
d52 = 1             → 交互后实体消失

结果: sub_40CE30(8080, 1, 1) → 物品 ID 8080 加入玩家库存 ×1
```

---

## 八、完整结论

### 8.1 实体 1297 交互的完整效果

| 效果 | 来源 | 函数 | 代码 |
|------|------|------|------|
| **晶礦物品 +1**（物品栏） | Type 110 掉落 | `sub_408B30` → `sub_40CE30(8080, 1, 1)` | 读取 d53=8080, d55=1 生成固定掉落 |
| **特殊物品收集度 +1** | B 链脚本 | `sub_40EBD4` → `sub_40E11C(-1, 11, 1)` | `word_757F00 += 1` |
| **实体消失** | Type 110 清除标志 | `sub_408B30` | d52=1 → 清除 flags bit0+bit1 |
| **B 链标记为已完成** | B 链脚本 End(2) | `sub_40EBD4` End handler | cur_B++，以后不再触发 |

### 8.2 Attribute vs GetItem 的本质区别

| | Attribute (opcode 48) | GetItem (opcode 40) |
|---|---|---|
| **操作对象** | 属性计数器（`word_757F00` 等） | 物品库存数组（`word_7570AA` 等） |
| **存储位置** | `.data` 段全局变量 | `.data` 段库存数组（最大 99/种） |
| **UI 表现** | 收集度数字变化（无浮动提示） | 物品栏显示 + SysTalk 浮动提示 |
| **脚本查询** | `CheckTeam(11, N, 0)` | `CheckItem(id, N, 0)` |
| **存档持久** | 是（保存在存档的属性区） | 是（保存在存档的物品区） |

### 8.3 通用分析模式

当遇到一个实体同时给出物品和改变属性时，检查以下两点：

1. **B 链脚本中的 `Attribute(-1, N, X)`**：查看 N 对应的计数器（见第六章映射表）
2. **Type 110 实体的 d53~d64 字段**：查看是否配置了物品掉落组

两者**独立运作**，互不依赖。实体 1297 恰好同时配置了两者，所以一次交互同时产生"晶礦入包"和"收集度 +1"两个效果。

---

## 九、反编译代码速查

| 函数 | 地址 | 文件 | 功能 |
|------|------|------|------|
| `sub_40E11C` | 0x40E11C | `40E11C.c` | **Attribute** 实现（opcode 48） |
| `sub_40CE30` | 0x40CE30 | `40CE30.c` | **GetItem** 实现（opcode 40） |
| `sub_408B30` | 0x408B30 | `408B30.c` | **Type 110 处理**（物品掉落 + 行为模式） |
| `sub_40E65C` | 0x40E65C | `40E65C.c` | **CheckTeam** 实现（opcode 63） |
| `sub_40E4E4` | 0x40E4E4 | `40E4E4.c` | **CheckItem** 实现（opcode 62） |
| `sub_40DFE4` | 0x40DFE4 | `40DFE4.c` | 属性钳位（上限检查） |
| `sub_40B1B4` | 0x40B1B4 | `40B1B4.c` | **SysTalk** 浮动文字通知 |
| `sub_408E5C` | 0x408E5C | `408E5C.c` | 玩家交互入口 |

---

*分析完成日期：2026-05-27*
*逆向依据：运行时转储 反编译代码 + TKMat.Dat 实体数据 + TKD.dat 脚本定义*
