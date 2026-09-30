# 编辑器源码交叉验证报告

> 验证基准：`build/build_all.py` 中 `EDITORS` 注册的 19 个编辑器，以及它们实际使用的数据加载层。
> 验证方式：阅读源码中的格式常量和字段定义，并直接调用编辑器自身的加载函数读取 `逆向工作区` 下的原版文件，与 `docs/tksexe` 中的逆向结论逐项比对。

## 1. 验证范围

| 编辑器 | 入口 | 核心源码 | 对应 tksexe 主题 |
| --- | --- | --- | --- |
| `TKSItemEditor` | `build/entries/entry_item_editor.py` | `item_editor/item_editor_v2.py` | `item_skill_shop_condition_data.md` |
| `TKSWarpcEditor` | `build/entries/entry_warpc_editor.py` | `warpc_editor/warpc_editor_v2.py`、`warpc_editor/warpc_schema.py` | `character_data_warpc.md`、`warpc_tail_fields_map.md`、`warpc_skill_tkkon_mapping.md` |
| `TKSSkillEditor` | `build/entries/entry_skill_editor.py` | `skill_editor/skill_editor_v2.py` | `item_skill_shop_condition_data.md`、`tkskill_description_rule.md` |
| `TKSShopEditor` | `build/entries/entry_shop_editor.py` | `shop_editor/shop_editor_v2.py` | `item_skill_shop_condition_data.md` |
| `TKSMatEditor` | `build/entries/entry_mat_editor.py` | `mat_editor/mat_constants.py`、`mat_editor/mat_dat_io.py`、`mat_editor/mat_editor_v2.py` | `entity_map_event_system.md`、`runtime_memory_map.md`、`modding_capacity_limits.md` |
| `TKSJvgEditor` | `build/entries/entry_jvg_editor.py` | `jvg_editor/jvg_editor_v2.py` | `resource_formats.md`、`animation_sprite_binding.md` |
| `TKSGrpEditor` | `build/entries/entry_grp_editor.py` | `grp_editor/grp_editor_v2.py`、`editor_utils/grp_codec.py` | `resource_formats.md`、`scene_grp_mapping.md`、`wsc_grp_mapping.md` |
| `TKSTktEditor` | `build/entries/entry_tkt_editor.py` | `tkt_editor/tkt_editor_v2.py`、`editor_utils/tkt_loader.py` | `text_data_encoding.md`、`font_text_rendering.md` |
| `TKSKonEditor` | `build/entries/entry_kon_editor.py` | `kon_editor/kon_editor_v2.py` | `item_skill_shop_condition_data.md`、`tkkon_runtime_fields.md` |
| `TKSActEditor` | `build/entries/entry_act_editor.py` | `act_editor/act_editor_v2.py` | `tkact_record_structure.md`、`animation_sprite_binding.md` |
| `TKSWardataEditor` | `build/entries/entry_wardata_editor.py` | `wardata_editor/wardata_editor_v2.py` | `battle_init_and_wardata.md`、`wsc_grp_mapping.md` |
| `TKSGxpEditor` | `build/entries/entry_gxp_editor.py` | `gxp_editor/gxp_editor_v2.py` | `resource_formats.md` |
| `TKSSpritesheetEditor` | `build/entries/entry_spritesheet_editor.py` | `spritesheet_editor/spritesheet_editor_v2.py` | 通用贴图工具，不直接解析游戏私有格式 |
| `TKSSaveEditor` | `build/entries/entry_save_editor.py` | `save_editor/save_editor_v2.py` | `save_system_runtime.md`、`save_block_ab_fields.md` |
| `TKSConfigsEditor` | `build/entries/entry_configs_editor.py` | `configs_editor/configs_editor.py` 及 `panels/` | `modding_capacity_limits.md` |
| `TKSFontEditor` | `build/entries/entry_font_editor.py` | `font_editor/font9696_codec.py` | `font_text_rendering.md`、`resource_formats.md` |
| `TKSBook` | `build/entries/entry_tks_book.py` | `tks_book/tks_book_v2.py` 及 `book_loader.py` 等 | 数据查看器，复用上述加载层 |
| `TKSLauncher` | `build/entries/entry_launcher.py` | `tks_launcher_gui/main.py`、`core/warpc_expander.py`、`core/patch_engine.py` | `modding_capacity_limits.md`、`save_system_runtime.md` |
| `TKSLauncherCLI` ~~（已废弃，2026-09-30 停止提供）~~ | ~~`build/entries/entry_launcher_cli.py`~~ | ~~`tks_launcher_gui/cli_launcher.py`~~ | 已从仓库移除 |

## 2. 实际文件加载结果

下表使用编辑器自身的加载函数读取原版文件，结果与文档容量完全一致：

| 文件 | 文档容量 | 编辑器源码常量 | 实际加载结果 |
| --- | --- | --- | --- |
| `WarPC.dat` | 143 条 × 1054B = 150722B | `WARPC_ORIG_COUNT=143`、`WARPC_REC=1054` | 143 条 × 527 int16 |
| `TKItem.dat` | 600 条 × 64B = 38400B | `ITEM_CNT=600`、`ITEM_REC=64` | 600 条 × 32 int16 |
| `TKSkill.dat` | 350 条 × 94B = 32900B | `SKILL_CNT=350`、`SKILL_REC=94` | 350 条 × 47 int16 |
| `TKShop.dat` | 240 条 × 8B = 1920B | `FIXED_COUNT=240`、`REC_SIZE=8` | 240 条 × 4 字段 |
| `TKKon.dat` | 650 条 × 40B = 26000B | `KON_CNT=650`、`KON_REC=40` | 650 条 × 20 int16 |
| `TKAct.dat` | 650 条 × 784B = 509600B | `ACT_ENTRY_COUNT=650`、`ACT_ENTRY_SIZE=784` | 650 条 × 784B |
| `TKMat.Dat` | 6000 条 × 384B = 2304000B | `REC_COUNT=6000`、`REC_SIZE=384` | 6000 条 × 96 int32，非空 2477 条 |
| `TKDefUnit.dat` | 5000 条 × 16B = 80000B | `DEFUNIT_ORIG_COUNT=5000`、`DEFUNIT_REC_COUNT=10000` | 实际文件 80000B = 5000 条 |
| `WarData.dat` | 219 条 × 498B | `WAR_REC_COUNT=219`、`WAR_REC_SIZE=498` | 219 条 × 498B |
| `WarWay.dat` | 100 条 × 1024B | `load_warway_all` 按 1024B/条 | 100 条 × 32×32 int8 |
| `SC.IDX` | 215 个 uint32 | `grp_editor`/`scene_grp_mapping` | 215 个 uint32 |
| `WSC.IDX` | 84 个 uint32，83 个区段 | `wardata_editor_v2.load_wsc_idx` | 84 个 uint32，83 个区段 |
| `SWS.IDX` | 507 个 uint32 | 同 GRP/IDX | 507 个 uint32 |
| `SSF.IDX` | 64 个 uint32 | 同 GRP/IDX | 64 个 uint32 |
| `SMG.IDX` | 22 个 uint32 | 同 GRP/IDX | 22 个 uint32 |
| `TKT.dat` | 14438 条头记录 | `editor_utils/tkt_loader.py` | 头记录 14438，非空文本 7759 条 |
| `TKD.dat` | XOR 0xFF 后为 Big5 文本 | `editor_utils/mod_exporter.py` | 解码后含 1539 个 `DEFINE` 块 |
| `FONT9696` | 8 区段 × 14915 字形 | `Font9696.SECTIONS=8`、`GLYPHS_PER_SECTION=14915` | 索引表 477280B，字形缓冲 1152B |
| `TKObj.dat` | RIFF/AVI 片尾视频 | `grp_data.py` 等 RIFF 识别 | `RIFF....AVI `，含 `JUNQ` |

## 3. 关键字段交叉验证

### WarPC

- `warpc_schema.py` 把 `[0]-[4]` 定义为 `name_id / portrait / level / role / exp_to_next`，与 `character_data_warpc.md` 一致。
- `[3] role` 在源码中的语义是 `-1=未激活、0=已激活`，并非“-1 我方、0 敌方”。已在文档中修正。
- `[4] exp_to_next` 是当前角色“升到下一级所需经验”。源码注释同时给出典型值：大多数角色为 100，吕布 5092、张角 7292。对全部 143 条实际数据检查，113 条满足 `8*level^2+92`，30 条文件值仍为 100；因此该公式是入队/升级时的初始化或重算规则，不是所有记录的静态关系。原文档表述已改为“初始化/升级重算公式”。
- `[27]-[31]` 源码定义为智慧、仁德、勇气、医术、技能点数，且 `[30] medicine` 有 `sub_40E11C case4` 引用。
- `[43]-[50]` 源码定义为 8 个状态槽（低字节状态 ID、高字节持续回合），当前文件全部为 `-256`（`0xFF00`），与“待验证字段”的原描述不符，已移出缺口清单。
- `[77]-[81]` 源码定义为使用/装备权限位掩码；当前文件 `[78]` 为 `0/3/7`、`[79]` 为武器位掩码、`[80]` 为防具位掩码，`[77]/[81]` 全部为 0。缺口清单已更新。
- `[88]-[259]`、`[260]-[263]`、`[264]-[272]`、`[273]-[525]` 的字段分组与 `warpc_tail_fields_map.md` 一致。
- `warpc_skill_tkkon_mapping.md` 的 223/134/89 统计可由实际数据完全复现，示例技能 44-68 的 TKKon 值也逐项一致。

### TKItem / TKSkill / TKShop / TKKon

- `item_editor_v2.py` 的 32 字段定义与文档一致：`[2]/[3]` 为名称/描述 TKT ID，`[4]` 图标索引显示时 +130，`[5]` 使用权限，`[7]-[10]` HP/MP，`[11]-[18]` 八项属性，`[21]-[24]` 技能引用，`[25]` 医术，`[26]-[29]` 状态掩码，`[31]` 价格。
- `skill_editor_v2.py` 的 `SKILL_REC=94`、`SKILL_CNT=350` 与文档一致；对实际 350 条检查，344 条满足 `desc_id = text_id + 400`，6 条空槽，无不一致项。
- `shop_editor_v2.py` 显示 `condition` 是“幸运偏移”，不是等级偏移。商店出现概率为 `clamp(队伍最大幸运 - condition, 0, 100)%`；`condition=1` 为随机抽选，`condition<=-100` 为始终出现。原 `item_skill_shop_condition_data.md` 中“等级偏移/level-condition”已修正。
- `kon_editor_v2.py` 的 `KON_FIELDS` 将 `[3]` 定义为 `tkact_id`（TKAct 动画索引），不是“条件唯一 ID”。实际数据中 `[3]` 范围 -1..639，共 605 个不同值，与 TKAct 索引范围一致；`[15]-[18]` 全部为 0。原文档中的 `TKKon[0/1/8/9]->TKT.dat` 交叉引用不成立，已改为 TKAct/效果字段引用。

### WarData / WarWay

- `wardata_editor_v2.py` 与 `tks_launcher_gui/core/mod_loader.py` 都定义了 498B 的 WarData 字段布局，包括 `map_id@32`、敌军 18 组、友军 6 组、陷阱 28 组、宝物 10 组、等级浮动、回合限制等。
- `WarWay.dat` 为 100 条 × 1024B 的 32×32 int8 网格，`-1` 障碍、`0` 可通行、`1-5` 特殊区域。
- `WSC.IDX` 84 项、83 个区段，与 `wsc_grp_mapping.md` 一致。

### TKAct

- `act_editor_v2.py` 的常量 `ACT_ENTRY_SIZE=784`、`ACT_ENTRY_COUNT=650`、`ACT_LAYER_SIZE=80`、`ACT_MAX_LAYER=8`、`ACT_TAIL_OFFSET=720`、`ACT_TAIL_SIZE=64` 与 `tkact_record_structure.md` 完全对应。
- 方向表 32B、参数区 48B、8×80B 图层、末尾 64B 音效事件表的结构与文档一致。

### TKT / TKD

- `editor_utils/tkt_loader.py` 定义 `[4B total_size][4B count][XOR 0xFF 数据区]`，数据区为 `ID 表 + 偏移表 + 0x00 结尾文本`，控制标签与 `text_data_encoding.md` 完全一致。
- `TKD.dat` 无 TKT 式头，整文件 XOR 后为 Big5 文本；实际解码得到 `DEFINE` 块 1539 个。

### 存档

- `save_editor_v2.py` 的 `SEG1_SIZE=3432`、`SEG2_SIZE=5768`、`WARPC_OFFSET=9200`、`GAMESTATE_SIZE=2304000`、`SAV_META_SIZE=28` 与 `save_system_runtime.md`、`save_block_ab_fields.md` 一致。
- `tks_launcher_gui/core/warpc_expander.py` 同样使用 `150722`、`159922`、`9200`，支持动态 WarPC 扩容。
- 当前 `逆向工作区/Save/` 为空，因此未执行真实存档二进制往返验证；存档相关结论来自源码常量和既有分析。

### 资源格式

- `gxp_editor_v2.py`：`GXP_MAGIC=b"JGXP"`、48B 头、RGB565。实际读取 `TitleMenu.gxp`、`00.gxp`、`MG_44.gxp` 均为 640×480、16bpp。
- `jvg_editor_v2.py`：`JVG_MAGIC=b"@JVG"`、`JVM_MAGIC=b"@JVM"`、32B 头。实际读取 `MG_44.JVG` 17 块 17 帧、`Cur.JVG` 22 块 119 帧、`wm.JVG` 16 块 80 帧。
- `grp_editor_v2.py` / `grp_codec.py`：GRP 区段为 Frame A（RGB565 LZSS）+ Frame B（RLE 字节对），并可含音频/数据区段，与 `resource_formats.md` 一致。
- `font9696_codec.py`：8 区段、每区段 14915 字形、96×96、1bpp、1152B 缓冲、3 字节打包 4 个 6-bit 游程，与 `font_text_rendering.md` 一致。

## 4. 源码未直接覆盖的文档

以下主题没有被任何编辑器重新实现为可执行的数据层，仍以 `反编译产物/decompile` 为主依据：

- `script_command_mapping.md` 的 0-82 号 opcode 逐项行为。
- 战斗公式、AI 决策、技能分发、战后结算的具体计算路径。
- 7 种小游戏的规则实现。
- Alpha LUT、DirectSound/DirectShow、BGM/AVI 加载路径。
- `runtime_memory_map.md` 中纯运行时内存地址与全局变量。

这些主题仅能通过编辑器源码间接佐证（例如 `mat_editor` 对实体脚本字段的标注、`tks_launcher_gui` 对运行时补丁的地址扫描），不能算作编辑器源码的直接验证。第二阶段的 [decompile_runtime_verification.md](decompile_runtime_verification.md) 已用反编译/反汇编对上述主题做了补充复核。

## 5. 结论

本次验证覆盖全部 19 个注册编辑器。文件容量、记录大小、LZSS 头、IDX 区段数、TKT/TKD 编码、FONT9696、TKAct 布局和 WarPC 技能映射等核心结论均被编辑器源码和实际文件加载结果证实。

同时修正了三处旧文档错误：WarPC `[3]` 的身份语义、WarPC `[4]` 经验公式的表述、TKShop 条件按等级/按幸运的差异，以及 TKKon `[3]` 的字段语义和交叉引用。
