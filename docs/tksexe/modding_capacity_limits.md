# MOD 扩展容量与硬编码边界

> 汇总各数据表和脚本变量的固定容量，以及当前启动器已覆盖的补丁。

## 1. 数据文件容量

| 文件 | 记录 | 单条大小 | 固定容量 |
| --- | --- | --- | --- |
| `TKMat.Dat` | 实体 | 384B | 6000 |
| `TKDefUnit.dat` | DEFINE 链 | 16B | 5000 |
| `WarPC.dat` | 角色 | 1054B | 143 |
| `TKItem.dat` | 物品 | 64B | 600 |
| `TKSkill.dat` | 技能 | 94B | 350 |
| `TKShop.dat` | 商品 | 8B | 240 |
| `TKKon.dat` | 条件 | 40B | 650 |
| `TKAct.dat` | 动作 | 784B | 650 |
| `FONT9696` | 字形 | 96×96 | 8 × 14915 |

## 2. 脚本变量容量

| 系统 | 容量 |
| --- | --- |
| 脚本变量 `word_755E80` | 256 |
| 开关 `word_755E10` | 32 |
| 选择结果 `word_755E50` | 24 |
| 全局标志 `word_756080` | 1024 |
| Note 数组 | 1000 |
| 队伍槽位 | 6 |

## 3. 存档相关硬编码

```text
Frame1 = 2304000 = 6000 × 384
Frame2 = 159922 = 3432 + 5768 + 150722
WarPC 在 Frame2 的偏移 = 9200
```

扩展 WarPC 时需同时修补 `150722`、`159922` 与 WarPC 基址引用；扩展 Block A/B 时还要修改 `9200`。

## 4. 已实施的启动器补丁

- WarPC 缓冲区动态扩展（29 处基址引用 + 7 处字段引用 + 5 处大小）。
- 存档/读档 Frame2 缓冲扩展（`159922` 盲扫）。
- TeamMember 队伍上限 30 -> 200。
- 技能学习表扩容与战斗菜单 12 技能上限保护。
- AwkSprite/头像等硬编码字段补丁。

## 5. 未覆盖边界

- TKMat 6000 实体数量不可扩展。
- TKItem 600、TKSkill 350、TKShop 240、TKKon 650 均固定。
- 扩展这些文件需要同时改加载缓冲、Maker 校验、遍历上限和存档结构。

## 6. 参考

- [`save_system_runtime.md`](save_system_runtime.md)
- [`character_data_warpc.md`](character_data_warpc.md)
- [`item_skill_shop_condition_data.md`](item_skill_shop_condition_data.md)
- [`docs/save_editor/TKS存档系统硬编码分析报告.md`](../save_editor/TKS存档系统硬编码分析报告.md)
