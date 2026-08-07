# TKS 分析验证缺口清单

> 汇总当前仍未被反编译、数据统计或运行时实测完全证实的内容，按“已确认 / 待验证 / 外部工具”分类。
> 与 [editor_source_verification.md](editor_source_verification.md)、[decompile_runtime_verification.md](decompile_runtime_verification.md) 互补：前者以编辑器源码和实际文件加载结果为基准，后者复核存档之外的运行时行为。

## 1. 已确认，不再作为缺口

| 项目 | 结论 | 文档 |
| --- | --- | --- |
| 场景 -> SC.GRP | `scene_id` 直接索引 SC.IDX | `scene_grp_mapping.md` |
| 战场背景 | `WarData.map_id` 索引 WSC/WarWay | `wsc_grp_mapping.md` |
| TKD 加载 | FormCreate 加载并 XOR | `text_data_encoding.md` |
| 技能描述 ID | `TKSkill.field[1]` 直接提供 | `tkskill_description_rule.md` |
| Ani.JVG | 地图实体动画，非 TKAct | `ani_jvg_trigger_path.md` |
| Awt/Awk | `sub_43DE90` 直接渲染 Awk | `awt_awk_switch.md` |
| TKAct 元数据 | 0x24 总时长、0x28+ 事件帧标记 | `tkact_record_structure.md` |
| Block A/B 大块 | BGM 表、Note 数组、背包边界已确认 | `save_block_ab_fields.md` |
| WarPC [4] | 当前升级所需经验；入队/升级时按 `8*level^2+92` 初始化或重算，实际 30/143 条仍为 100 | `character_data_warpc.md` |
| WarPC [27]-[31] | 智慧/仁德/勇气/医术/技能点数；`medicine` 有 `sub_40E11C` 引用 | `character_data_warpc.md`、`warpc_editor_v2.py` |
| WarPC [43]-[50] | 8 个状态槽；当前全量数据为 -256（`0xFF00`） | `warpc_editor_v2.py`、`warpc_schema.py` |
| WarPC [77]-[81] | 使用/装备权限位掩码；[78]/[79]/[80] 有非零值，[77]/[81] 当前为 0 | `warpc_editor_v2.py`、`warpc_schema.py` |
| WarPC [88]-[272] | 技能学习/实体ID/成长率/奖励/掉落 | `warpc_tail_fields_map.md` |
| WarPC [273]-[525] | 技能索引 -> TKKon 配置表，`sub_435D68` 直接读取 | `warpc_tail_fields_map.md` |
| WarPC 技能逐条映射 | 223 个技能已提取，含多角色变体 | `warpc_skill_tkkon_mapping.md` |
| WarPC [526] | Cha.JVG 立绘/基础精灵 ID | `warpc_tail_fields_map.md` |
| TKShop condition | 幸运偏移：`clamp(最大幸运 - condition, 0, 100)%`；1=随机，<=-100=始终 | `shop_editor_v2.py`、`item_skill_shop_condition_data.md` |
| TKKon [3] | `tkact_id`：TKAct 动画索引，范围 -1..639 | `kon_editor_v2.py`、`tkkon_runtime_fields.md` |
| 脚本命令 0-82 | `40EBD4.c` 逐 case、PC 增量与边界已复核 | `decompile_runtime_verification.md` |
| AI 平手规则 | 随机替换为 50%（`sub_452AC0(1000) < 0x1F4`） | `decompile_runtime_verification.md` |
| 小游戏调度 | `40E97C` 分派、7 个主函数与资源名已复核 | `decompile_runtime_verification.md` |
| TKMat [3]-[5] | wait_timer / tick_threshold / tick_counter | [`TKMat文件格式参考手册.md`](../../../逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md) |
| Alpha 混合 | `sub_454D24` 使用 32 级 LUT 查表相加 | `alpha_blend_formula.md` |
| NAME 标签 | 1=主角姓，2=主角名 | `text_formatting_engine.md` |
| 方向算法 | 8 方向 `sub_4075C0`、4 方向 `sub_449F84` 已确认 | `direction_mapping.md` |
| 4 方向方位组 | 0=下、1=左、2=上、3=右，经 8 方向交叉验证 | `direction_mapping.md` |
| TKObj `JUNQ` | 768 字节全零填充块，位于 hdrl/movi 之间 | `TKObj_analysis.md` |
| TKItem [1] | 菜单/商店分页类别码，`word_77CBCC` 多处引用 | `TKItem物品字段详解.md` |
| TKKon [0]-[2] | exec_mode / target_param / target_filter 已确认 | `TKKon_字段语义逆向分析报告.md` |
| TKKon [3]-[11] | tkact_id、效果值、状态掩码已映射到运行时全局 | `tkkon_runtime_fields.md` |
| TKKon [12]-[14]/[19] | 解除状态、时序修正、执行标志已有编辑器字段定义 | `kon_editor_v2.py` |

## 2. 仍待验证的静态/运行时字段

| 项目 | 位置 | 当前状态 | 建议验证 |
| --- | --- | --- | --- |
| Block A 0x00-0x3F | SEG1 头部 | 现有存档为零 | 更多进度存档对比 |
| Block A 0x160-0x2F7 | SEG1 | 现有存档为零 | 更多进度存档对比 |
| Block B 0x18-0x57 | SEG2 | 现有存档为零 | 更多进度存档对比 |
| TKAct slot 28-39 | 每个 80B 槽位 | 全量文件中为零 | 动态修改后观察 |
| TKAct 0x20/0x22 | 记录头 | 全量文件中基本为零 | 动态修改后观察 |
| TKKon [15]-[18] | 每条 40B 记录尾部 | 编辑器标记为 unused，全量数据为 0 | 反汇编/运行时逐字段验证 |

## 3. 外部工具/非游戏本体范围

| 项目 | 位置 | 当前状态 |
| --- | --- | --- |
| `encode.dll` | Maker 工具链 | 仅知 QProcess 启动，算法未分析 |
| TksModify.dll 内存偏移 | Maker 修改器 | 未完全逆向 |
| Godot TODO | 移植代码 | 非 TKS.exe 逆向缺口 |

## 4. 说明

本节只列出“无法仅靠现有反编译直接证实”的点。大部分仍可通过全量数据统计、运行时内存 dump 或像素级渲染测试继续验证。
