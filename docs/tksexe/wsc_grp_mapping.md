# WarData.map_id -> WSC.GRP / WarWay.dat 映射

> 战斗背景索引规则：`WarData.map_id` 同时作为 `WSC.IDX` 与 `WarWay.dat` 的偏移下标。

## 1. 证据链

```text
sub_436BD4（战斗初始化）
  -> sub_402BB8(word_9537F8)
  -> fseek(dword_4FA510, dword_4FA37C[map_id], 0)
  -> sub_42FA50(dword_4FA510)
      读取 WSC.GRP 区段 [2B width][2B height][4B frameA_size][4B frameB_size][data]

WarWay.dat
  -> map_id * 1024 字节偏移
  -> 32×32 地形网格
```

`word_9537F8` 来自 `WarData.dat` 记录偏移 32 的 `map_id`。

## 2. 文件统计

| 文件 | 区段数 | 说明 |
| --- | --- | --- |
| `WSC.IDX` | 84 个 uint32 偏移 | 83 个背景 + 文件大小哨兵 |
| `WSC.GRP` | 83 | 战场预渲染背景 |
| `WarWay.dat` | 100 × 1024B | 32×32 网格，按 map_id 取块 |

WarData 共 219 条有效战场记录，引用 70 个不同 map_id。

## 3. map_id 使用频次

| map_id | WarData 记录数 |
| --- | --- |
| 1 | 6 |
| 2 | 40 |
| 3 | 1 |
| 6 | 4 |
| 7 | 2 |
| 8 | 5 |
| 10 | 4 |
| 11 | 1 |
| 12 | 8 |
| 13 | 12 |
| 16 | 17 |
| 17 | 3 |
| 18 | 20 |
| 19 | 8 |
| 22 | 4 |
| 23-35 | 各 1-2 |
| 37 | 2 |
| 40+ | 其余低频 |

## 4. 关键结论

- `map_id` 是战场背景、WarWay 网格和战场记录之间的共享索引。
- 多个战场可复用同一 `map_id`；修改 WarWay 会影响所有使用该 map_id 的战场。
- WSC 区段头与 SC.GRP 相同，但加载路径由战斗初始化 `sub_402BB8 -> sub_42FA50` 完成。

## 5. 参考

- [`docs/wardata_editor/地图网格绘制逻辑.md`](../wardata_editor/地图网格绘制逻辑.md)
- [`docs/wardata_editor/战场地图坐标体系分析.md`](../wardata_editor/战场地图坐标体系分析.md)
- [`scene_grp_mapping.md`](scene_grp_mapping.md)
