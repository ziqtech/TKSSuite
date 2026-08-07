# 存档 Block A / Block B 字段布局

> 覆盖 `unk_755B18`（3432 字节）与 `unk_756880`（5768 字节）的已知字段、数组、别名和保留区。

## 1. Block A（SEG1，3432B）

基址：`unk_755B18`

| 相对偏移 | 大小 | 字段 | 说明 |
| --- | --- | --- | --- |
| 0x40 | 4 | map_id | 当前地图/场景 ID，`dword_755B58` |
| 0x44 | 4 | current_char | 当前角色 ID，`dword_755B5C` |
| 0x48 | 4 | game_active | 游戏激活标志，`dword_755B60` |
| 0x4C | 5 | given_name | 主角名，Big5 |
| 0x54 | 5 | surname | 主角姓，Big5 |
| 0x5C | 250 | bgm_table | `byte_755B74[250]` 场景 BGM 绑定表 |
| 0x15C | 2 | slot1_active | 编成槽 1 激活 |
| 0x15E | 2 | slot1_idx | 编成槽 1 角色索引 |
| 0x160 | 2 | slot2_active | 编成槽 2 激活 |
| 0x162 | 2 | slot2_idx | 编成槽 2 角色索引 |
| 0x168 | 4 | battle_flags | 遭遇战旗标 `dword_755C80` |
| 0x2F8 | 64 | switches | `word_755E10[32]` |
| 0x338 | 48 | results | `word_755E50[24]` |
| 0x368 | 512 | variables | `word_755E80[256]`，脚本实际用 0-249 |
| 0x568 | 2048 | flags | `word_756080[1024]` |

## 2. Block A 别名/重叠

同一个物理地址被不同符号引用：

| 相对偏移 | 别名 1 | 别名 2 |
| --- | --- | --- |
| 0x336 | comp_flag `word_755E4E` | switches[31] |
| 0x366 | minigame_rst `word_755E7E` | results[23] |
| 0x566 | last_acq `word_75607E` | variables[255] |
| 0x82C | map_timer `word_756344` | flags[354] |
| 0x82E | door_unlock `word_756346` | flags[355] |

注意：`word_756344`/`word_756346` 同时被战斗/地图代码写入，说明这些标志槽兼具运行状态与剧情状态用途。

## 3. Block B（SEG2，5768B）

基址：`unk_756880`

| 相对偏移 | 大小 | 字段 | 说明 |
| --- | --- | --- | --- |
| 0x02 | 2 | gold | 金钱，上限 30000 |
| 0x04 | 2 | wisdom | 智慧 |
| 0x06 | 2 | benevolence | 仁德 |
| 0x08 | 2 | courage | 勇气 |
| 0x0A | 2 | medicine | 医术，上限 100 |
| 0x0C | 12 | team | 6 个队伍成员 ID，`word_75688C[6]` |
| 0x58 | 2000 | notes | `word_7568D8[1000]`，脚本 Note 状态标记 |
| 0x828 | 2 | inv_count | 物品种类数 |
| 0x82A | 1200 | inv_items | 600 个物品 ID |
| 0xCDA | 1200 | inv_types | 600 个物品类型索引 |
| 0x118A | 1200 | inv_qtys | 600 个物品堆叠数量 |
| 0x163A | 2 | wins | 胜场数 |
| 0x163C | 2 | losses | 败场数 |
| 0x163E | 2 | kills | 杀敌数 |
| 0x167E | 2 | quest_pct | 完成任务百分比 |
| 0x1680 | 2 | special_pct | 特殊物品百分比 |
| 0x1684 | 2 | souls | 收纳灵魂 |
| 0x1686 | 2 | beasts | 收纳兽元 |

## 4. 保留/未标注区

- Block A：0x00-0x3F、0x160-0x2F7 等区域暂无直接语义标注；0x160-0x2F7 在现有存档中为零。
- Block B：0x18-0x57 位于队伍与 Note 数组之间，现有存档中为零；0x58-0x827 已确认为 Note 数组。
- 引擎层对四个事件数组无硬编码索引，未标注标志语义只能从 TKD 脚本上下文推断。

## 5. 真实存档分析

对 `逆向工作区/Save/sav.1` / `sav.2` 的 Frame2 解压结果：

- Block A 未标注区 212 个非零字节全部位于 BGM 表，且两个存档一致。
- Block B 非 Note 区几乎没有持久值；Note 数组在 sav.1 有 6 个非零槽，sav.2 有 8 个。
- 事件数组、队伍、金钱、背包、统计字段与现有编辑器实现一致。

## 6. 参考

- [`docs/save_editor/事件系统语义分析.md`](../save_editor/事件系统语义分析.md)
- [`docs/save_editor/TKS存档系统硬编码分析报告.md`](../save_editor/TKS存档系统硬编码分析报告.md)
- [`save_editor/save_editor_v2.py`](../../save_editor/save_editor_v2.py)
- [`save_system_runtime.md`](save_system_runtime.md)
