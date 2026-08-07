# TKS.exe 静态逆向分析总索引

> 本目录汇总对脱壳版 `TKS.exe` 的静态逆向分析文档，当前批次已完成收尾。
> 权威基准：[`反编译产物/`](../../../逆向工作区/逆向工作区/反编译产物) 的 `decompile/*.c`、`function_index.txt`、`disassembly/`、`pointers.txt`、`strings.txt`、`memory/`。
> 二次交叉验证：[editor_source_verification.md](editor_source_verification.md) 使用 `build/build_all.py` 注册的编辑器源码及其实际加载函数核对文件格式、字段与容量；[decompile_runtime_verification.md](decompile_runtime_verification.md) 再对存档之外的脚本、战斗、AI、小游戏和运行时行为做反编译复核；[remake_feasibility.md](remake_feasibility.md) 评估基于这些资产重制 TKS.exe 真实代码的可行性。

## 推荐阅读顺序

1. [TKS_analysis.md](TKS_analysis.md) — 总览：PE、游戏身份、主流程、脚本引擎、数据文件格式
2. [startup_and_mainloop.md](startup_and_mainloop.md) — 启动流程、标题状态机、主线程循环
3. [script_engine_SCE.md](script_engine_SCE.md)、[script_command_mapping.md](script_command_mapping.md) 与 [entity_map_event_system.md](entity_map_event_system.md) — 脚本命令、实体/地图/事件系统
4. 数据模块 — [character_data_warpc.md](character_data_warpc.md)、[item_skill_shop_condition_data.md](item_skill_shop_condition_data.md)、[modding_capacity_limits.md](modding_capacity_limits.md)
5. 战斗相关文档 — 按“初始化 -> 菜单状态机 -> 主循环/结算 -> 核心汇编 -> AI/公式/技能分发”阅读
6. [text_and_save_system.md](text_and_save_system.md)、[resource_formats.md](resource_formats.md)、[audio_video_encoding.md](audio_video_encoding.md) — 文本存档与资源媒体
7. [minigame_reverse_analysis.md](minigame_reverse_analysis.md)、[TKObj_analysis.md](TKObj_analysis.md) — 小游戏与片尾视频专项

## 专项索引

### 总览与程序骨架

- [TKS_analysis.md](TKS_analysis.md) — PE/编译信息、架构、脚本命令表、数据文件、编码与本地化、改版信息
- [startup_and_mainloop.md](startup_and_mainloop.md) — `WinMain`、`TForm1_FormCreate`、视频/标题状态机、`TKGMThread` 主循环、退出/结局
- [ui_menu_world_flow.md](ui_menu_world_flow.md) — 主菜单状态机、场景切换、世界地图、保存/读取菜单、对话框、中文输入
- [runtime_memory_map.md](runtime_memory_map.md) — 实体/脚本/战斗/渲染/存档关键全局变量与内存布局
- [editor_source_verification.md](editor_source_verification.md) — 使用 19 个编辑器源码和实际文件加载结果交叉验证本文档目录
- [decompile_runtime_verification.md](decompile_runtime_verification.md) — 使用反编译/反汇编复核脚本引擎、战斗、AI、小游戏、渲染与音视频
- [remake_feasibility.md](remake_feasibility.md) — 结合编辑器源码与反编译资料评估 TKS.exe 真实代码重制路线
- [remake_route_b_deep_dive.md](remake_route_b_deep_dive.md) — 深入评估 C/C++ + CMake + SDL2/OpenGL 路线，给出依赖映射、工程分层、阶段与验证方案
- [verification_gaps.md](verification_gaps.md) — 当前未验证/未确认点清单，按已确认、待验证、外部工具分类
- [direction_mapping.md](direction_mapping.md) — 地图 8 方向与战斗 4 方向编号算法

### 脚本、实体与地图

- [script_engine_SCE.md](script_engine_SCE.md) — `SCE::TSCE` 对象布局、`DefCmd.Lst` 命令表、`TKD.dat` DEFINE 块、字节码执行与控制流
- [script_command_mapping.md](script_command_mapping.md) — `sub_40EBD4` 中 0-82 号脚本命令逐项映射、参数、PC 行为与边界
- [entity_map_event_system.md](entity_map_event_system.md) — `TKMat.Dat`、`TKDefUnit.dat`、实体类型、调度链、子场景 A/B/C、事件执行
- 外部参考：[`逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md`](../../../逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md) — TKMat 384 字节字段完整表、Species 分类、碰撞与脚本字段

### 数据文件模块

- [character_data_warpc.md](character_data_warpc.md) — `WarPC.dat` 角色数据、字段布局、引用关系与扩展限制
- [warpc_tail_fields_map.md](warpc_tail_fields_map.md) — WarPC `[88]-[526]` 尾部字段：技能学习、实体ID、成长率、奖励、掉落与动画引用区
- [warpc_skill_tkkon_mapping.md](warpc_skill_tkkon_mapping.md) — WarPC `[273+skill]` 到 TKKon 的完整映射表与生成脚本
- [item_skill_shop_condition_data.md](item_skill_shop_condition_data.md) — `TKItem`/`TKSkill`/`TKShop`/`TKKon` 格式、字段、交叉引用与容量
- [tkkon_runtime_fields.md](tkkon_runtime_fields.md) — TKKon 记录到 `byte_9D6C28` 运行时全局的字段映射
- [tkskill_description_rule.md](tkskill_description_rule.md) — 技能描述 TKT ID 的引擎规则与当前数据 `+400` 惯例
- [modding_capacity_limits.md](modding_capacity_limits.md) — 各数据表/脚本变量硬编码容量、存档常量与启动器补丁覆盖范围

### 战斗系统

- [battle_init_and_wardata.md](battle_init_and_wardata.md) — `WarData.dat`/`WarWay.dat` 格式、战斗初始化、动画资源、单位与地图网格初始化
- [battle_menu_state_machine.md](battle_menu_state_machine.md) — `sub_447DAC` 战斗菜单状态机、动作码、移动/目标确认/取消
- [battle_loop_and_rewards.md](battle_loop_and_rewards.md) — `sub_43CA64` 战斗主循环、战后转场、经验/JP/掉落/金钱结算、失败与逃跑
- [sub_4400DC_battle_core_analysis.md](sub_4400DC_battle_core_analysis.md) — `sub_4400DC` 汇编级阶段分析、调用图、全局变量热点
- [AI_decision_analysis.md](AI_decision_analysis.md) — 敌方 AI 回合入口、技能选择、全图扫描、行动价值、移动回退
- [sub_43E980_formula_analysis.md](sub_43E980_formula_analysis.md) — `sub_43E980` 基础值、技能公式、命中率、减伤、状态价值评分
- [sub_4458B0_skill_case_index.md](sub_4458B0_skill_case_index.md) — `sub_4458B0` 技能效果分发、技能 ID 速查、目标反应分支、调用图

### 文本、存档与资源

- [text_and_save_system.md](text_and_save_system.md) — `TKT.dat` 文本库、文本 ID 分段、存档文件与槽位、保存/读取函数
- [text_data_encoding.md](text_data_encoding.md) — `TKT.dat`/`TKD.dat` 编码格式、控制标签、双向转换工具与验证结果
- [save_system_runtime.md](save_system_runtime.md) — `sav.%d`/`%d.sav` 写读链路、双 Frame 格式、索引文件、硬编码常量与补丁风险
- [save_block_ab_fields.md](save_block_ab_fields.md) — Block A/B 已知字段、事件数组、背包/队伍/统计布局与内存别名
- [resource_formats.md](resource_formats.md) — GXP、JVG、GRP/IDX、TKAct、FONT9696 格式与加载函数
- [audio_video_encoding.md](audio_video_encoding.md) — WAV/MP3/AVI 路径、编码转换表、关键函数
- [TKObj_analysis.md](TKObj_analysis.md) — `TKObj.dat` 是片尾 AVI，含 RIFF/AVI 流、`JUNQ`、`idx1` 与替换影响

### 动画、字体与场景资源

- [animation_sprite_binding.md](animation_sprite_binding.md) — `TKAct` 图层、`Aa/Af` 绑定、`Cha/Ani` 基础行走图与战斗动画关联
- [tkact_record_structure.md](tkact_record_structure.md) — TKAct 784B 记录、方向表、8 个 80B 槽位、音效事件与推进逻辑
- [ani_jvg_trigger_path.md](ani_jvg_trigger_path.md) — Ani.JVG 地图实体/行走动画触发路径及其与 TKAct 的边界
- [awt_awk_switch.md](awt_awk_switch.md) — 待机/移动动画切换点：`sub_43709C` Awt 循环与 `sub_43DE90` Awk 直接渲染
- [scene_resource_pipeline.md](scene_resource_pipeline.md) — `SC/WSC/SWS/SSF/SMG` 资源包、场景切换与 BGM 加载链
- [scene_grp_mapping.md](scene_grp_mapping.md) — `scene_id -> SC.IDX/SC.GRP` 精确映射、50 个实际场景的偏移/尺寸表
- [wsc_grp_mapping.md](wsc_grp_mapping.md) — `WarData.map_id -> WSC.GRP/WarWay.dat` 战斗背景与地形网格索引
- [font_text_rendering.md](font_text_rendering.md) — `FONT9696` 位图字体、BIG5 索引、控制标签与文本渲染函数
- [text_formatting_engine.md](text_formatting_engine.md) — `sub_409C60` 对 TEXT/VARNUM/VARTXT/NAME 等控制码的运行时展开
- [alpha_blend_formula.md](alpha_blend_formula.md) — `sub_454D24` 的 32 级 LUT Alpha 混合公式

### 小游戏专项

- [minigame_reverse_analysis.md](minigame_reverse_analysis.md) — `MiniGame` 调度链、7 种小游戏规则、共享状态、修改/复用建议
