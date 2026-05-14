# Enable(4292) 触发机制分析

> 許褚如何从 許家村村北破廟 到 鄴城王殿 出现的完整链路。

## 关联实体

| 实体 | 类型 | 场景 | 说明 |
|------|------|------|------|
| #4292 | NPC(200) | scene 18 鄴城王殿 | 許褚（目标实体） |
| #2425 | 地形块(10) | scene 106 許家村 | 許家村场景脚本宿主 |
| #2032 | NPC(200) | scene 107 許家村許褚家 | 許褚家剧情脚本宿主 |

## 触发链路

```
許家村許褚家 (scene 107)
  entity #2032 执行 DEFINE 133169408
    │
    ├── (許褚家剧情对话序列...)
    ├── SetFlag(1023,4)          ← 标记事件完成
    ├── Enable(2425)              ← 激活 entity #2425
    ├── SetNowDef(2425,2,2)       ← cur_B 从 1 → 2
    │       │
    │       ▼ 引擎立即重新评估 entity #2425
    │       sub_4066F0(entity_2425, sub=1)
    │       沿链表: head_B=754 → (cur_B-1=1步) → DefUnit[755]
    │
    ▼
DEFINE 158925057 (entity #2425, scene 106 許家村)
    ├── Disable(2033)
    ├── Enable(4292)//許褚在王殿  ← ★ 激活王殿中的許褚
    ├── SetFlag(507,1)
    ├── AddFlag(501,1)
    └── End(2)
```

## Entity #2425 的 DefUnit 链

Entity #2425 的脚本参数：`head_B=754, max_B=2, cur_B=1` (初始)

| DefUnit | f0 | f1(entity) | f6(next) | DEFINE ID | cur_B= | 内容 |
|---------|----|-----------|----------|-----------|--------|------|
| [754] | 256 | 2425 | 755 | 158925056 | 1 | `End(0)` — 空操作 |
| [755] | 257 | 2425 | 0 | **158925057** | 2 | `Enable(4292)` — ★ |

**初始状态** (cur_B=1)：只执行 `End(0)`，无效果。

**切换后** (cur_B=2)：`SetNowDef(2425,2,2)` 将 cur_B 改为 2，触发 DEFINE 158925057。

## SetNowDef 语义

**反编译证据 — `40B520.c`（操作码 4）：**

SetNowDef 的第一个参数指定子场景（0=A, 1=B, 2=C），第二个参数指定新的 cur 值，写入 `entity[132/136/140]`。

```c
// TKD_decoded.txt:40036
SetNowDef(2425,2,2)
// → entity #2425, sub-scene B (2), cur_B ← 2
// → 效果: dword_51AF40[96*2425 + 136] = 2
```

## 完整游戏流程

```
1. 玩家初到 許家村 (scene 106)
   → entity #2425 cur_B=1 → DEFINE 158925056 (End(0))
   → entity #4292 (許褚) 在鄴城王殿中处于默认状态

2. 玩家到 許家村村北破廟 (scene 109)
   → 触发战斗 → 胜利 → 战斗后对话

3. 玩家到 許家村許褚家 (scene 107)
   → entity #2032 执行 DEFINE 133169408
   → 对话序列 → SetFlag(1023,4) → Enable(2425) → SetNowDef(2425,2,2)
   → 引擎立即评估 entity #2425:
       cur_B=2 → DefUnit[755] → DEFINE 158925057
   → Enable(4292) ★ 許褚在鄴城王殿中变为可见

4. 玩家前往 鄴城王殿 (scene 18)
   → entity #4292 已可见，可对话触发 DEFINE 281280768 (許渚加入)
```

## 关键证据

| 证据 | 来源 | 说明 |
|------|------|------|
| `SetNowDef(2425,2,2)` | `TKD_decoded.txt:40036` | 切换 entity #2425 cur_B |
| `Enable(4292)` | `TKD_decoded.txt:39943` | 激活 entity #4292 |
| entity #2425 head_B=754, max_B=2 | TKMat.Dat #2425 dword 40/31 | 链结构 |
| TKDefUnit[754].f6=755 | TKDefUnit.Dat | 链表 next 指针 |
| `sub_40B520` | `40B520.c` | SetNowDef 写入 entity[136] |
| `sub_4066F0` | `4066F0.c` | 沿链表计算 d44 |

## 结论

DEFINE 158925057 **不是**等玩家重新进入許家村时才触发，而是在**許褚家剧情完成的那一刻立即触发**——`Enable(2425)` + `SetNowDef(2425,2,2)` 使引擎立即重新评估 entity #2425，cur_B 变为 2，执行 DEFINE 158925057 中的 `Enable(4292)`，将鄴城王殿中的許褚设为可见。
