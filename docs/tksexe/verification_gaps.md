# TKS 分析验证缺口清单

> 汇总当前仍未被反编译、数据统计或运行时实测完全证实的内容，按“已确认 / 待验证 / 外部工具”分类。

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
| WarPC [4] | 升级所需经验 `8*level^2+92` | `character_data_warpc.md` |
| WarPC [88]-[272] | 技能学习/实体ID/成长率/奖励/掉落 | `warpc_tail_fields_map.md` |
| WarPC [273]-[525] | 技能索引 -> TKKon 配置表，`sub_435D68` 直接读取 | `warpc_tail_fields_map.md` |
| WarPC 技能逐条映射 | 223 个技能已提取，含多角色变体 | `warpc_skill_tkkon_mapping.md` |
| WarPC [526] | Cha.JVG 立绘/基础精灵 ID | `warpc_tail_fields_map.md` |
| TKMat [3]-[5] | wait_timer / tick_threshold / tick_counter | [`TKMat文件格式参考手册.md`](../../../逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md) |
| Alpha 混合 | `sub_454D24` 使用 32 级 LUT 查表相加 | `alpha_blend_formula.md` |
| NAME 标签 | 1=主角姓，2=主角名 | `text_formatting_engine.md` |
| 方向算法 | 8 方向 `sub_4075C0`、4 方向 `sub_449F84` 已确认 | `direction_mapping.md` |
| 4 方向方位组 | 0=下、1=左、2=上、3=右，经 8 方向交叉验证 | `direction_mapping.md` |
| TKObj `JUNQ` | 768 字节全零填充块，位于 hdrl/movi 之间 | `TKObj_analysis.md` |
| TKItem [1] | 菜单/商店分页类别码，`word_77CBCC` 多处引用 | `TKItem物品字段详解.md` |
| TKKon [0]-[2] | exec_mode / target_param / target_filter 已确认 | `TKKon_字段语义逆向分析报告.md` |
| TKKon [3]-[11] | tkact_id、效果值、状态掩码已映射到运行时全局 | `tkkon_runtime_fields.md` |

## 2. 仍待验证的静态/运行时字段

| 项目 | 位置 | 当前状态 | 建议验证 |
| --- | --- | --- | --- |
| WarPC [27]-[30] | 偏移 54-60 | 无反编译直接引用 | 全数据统计 + 等级/进度关联 |
| WarPC [43]-[50] | 偏移 86-100 | 无反编译直接引用 | 数据统计 |
| WarPC [77]-[81] | 偏移 154-162 | 未验证，[79]疑似装备位掩码 | 装备/战斗交叉验证 |
| Block A 0x00-0x3F | SEG1 头部 | 现有存档为零 | 更多进度存档对比 |
| Block A 0x160-0x2F7 | SEG1 | 现有存档为零 | 更多进度存档对比 |
| Block B 0x18-0x57 | SEG2 | 现有存档为零 | 更多进度存档对比 |
| TKAct slot 28-39 | 每个 80B 槽位 | 全量文件中为零 | 动态修改后观察 |
| TKAct 0x20/0x22 | 记录头 | 全量文件中基本为零 | 动态修改后观察 |
| TKKon [12]-[19] | 650 条条件 | 无命名引用，疑似保留或仅供 4400DC 汇编内部使用 | 反汇编/运行时逐字段验证 |

## 3. 外部工具/非游戏本体范围

| 项目 | 位置 | 当前状态 |
| --- | --- | --- |
| `encode.dll` | Maker 工具链 | 仅知 QProcess 启动，算法未分析 |
| TksModify.dll 内存偏移 | Maker 修改器 | 未完全逆向 |
| Godot TODO | 移植代码 | 非 TKS.exe 逆向缺口 |

## 4. 说明

本节只列出“无法仅靠现有反编译直接证实”的点。大部分仍可通过全量数据统计、运行时内存 dump 或像素级渲染测试继续验证。
