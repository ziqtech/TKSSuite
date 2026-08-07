# TKS.exe 逆向信息提取报告

> 完整专项索引见 [README.md](README.md)。

## 0. 结论

- 目标不是 Unreal Engine 程序，而是 2002 年的《三國群俠傳》Windows 32 位版。
- 游戏由东方演算/河洛工作室开发，智冠发行；本目录中的 `TKS.exe` 是游戏主程序。
- 技术栈为 Borland C++ Builder + VCL/Delphi 窗体 + STLport，DirectDraw 2D 渲染，DirectSound 音频，DirectShow/AVI 视频。
- `反编译产物` 是已经做好的 IDA 导出，包含 2040 个函数索引、2033 个反编译 C 文件、内存转储、字符串表和指针表，适合继续做源码级定位。

## 1. PE 与编译信息

| 项目 | 值 |
| --- | --- |
| 文件 | `游戏目录（改版）/TKS.exe` |
| 大小 | 1,046,528 字节 |
| SHA-256 | `FEC73B10BA461CB57BDC3CE5B9176BF02FAA534FD235E622D282AB21862E488A` |
| PE 类型 | PE32, i386, Windows GUI |
| ImageBase | `0x00400000` |
| EntryPoint | `0x004013A8` |
| PE 时间戳 | `0x3D0EA063`，约 2002 年中 |
| 区段 | `.text`、`.data`、`.tls`、`.rdata`、`.icore`、`.edata`、`.rsrc`、`.idata` |
| 链接器标记 | `Borland C++ - Copyright 2002 Borland Corporation` |

主要导入 DLL：

`ddraw.dll`、`dsound.dll`、`advapi32.dll`、`kernel32.dll`、`comctl32.dll`、`gdi32.dll`、`user32.dll`、`imm32.dll`、`ole32.dll`、`oleaut32.dll`。

资源区没有正式版本资源；`TFORM1` DFM 显示主窗口是一个无边框置顶窗体，带 `TTimer MplayTimer`，游戏画面由 DirectDraw 直接绘制。`RT_STRING` 资源基本都是 VCL 自带英文错误文本，不是游戏文本。

## 2. 游戏身份与文本证据

从还原后的 `TKT.dat` 可以直接读到完整剧情，确定是《三國群俠傳》：

- 南華老仙、左慈、于吉召唤现代少年穿越到三國。
- 主角身边有鬼魂向导“苍溟”。
- 刑天附身在董卓身上，需要收集太古九鼎。
- 目标是让魏、蜀、吴人物归位，找回曹操、刘备、孙权。
- 地图包含汜水关、虎牢关、洛阳、成都、建业、长沙、襄阳、江夏、下邳、武威、西羌、南蛮等。
- `TKT.dat` 中还有大量武将/兵种列传，例如张梁、周仓、祝融夫人、赤兔马、僵尸兵、大鹏金翅鸟、五爪金龙等。

`TKD.dat` 还原后开头为：

```text
////DEFSTR_-01
DEFINE 256
{;狀態介面
//ShowMenu(1,0)
SetSwitch(0,1)
End(0)
};
```

这说明 `TKD.dat` 是事件/脚本源文件，`TKT.dat` 是文本数据库，两者都经过逐字节取反加密。

## 3. 程序架构与主流程

| 地址 | 功能 |
| --- | --- |
| `0x0040162C` | `WinMain` |
| `0x004030F0` | `TForm1_FormCreate`，加载存档索引、DirectDraw、地图/资源、脚本和文本 |
| `0x004018DC` | 创建 `TKGMThread` |
| `0x00412BE8` | `TKGMThread` 主循环，约 60 ms 节拍 |
| `0x004128AC` | 结束/章节切换流程 |
| `0x0041310C` | 加载 `DefCmd.Lst` 到 `SCE::TSCE` 命令表 |
| `0x0041335C` | 解析 `DefCmd.Lst` 命令定义 |
| `0x0040EBD4` | 脚本命令调度器 |
| `0x00452544` | 普通文件加载器 |
| `0x0045343C` | 压缩文件加载器 |
| `0x00452B14` | LZSS 解压器 |
| `0x0044EC0C` | DirectDraw 初始化，创建 640x480 主表面 |
| `0x00451580` | DirectSound 初始化 |

主循环 `sub_412BE8` 每轮等待 `GetTickCount()` 间隔至少 `0x3C` ms，然后依次调用：

```c
sub_405C28();
sub_412390();
sub_411E84();
sub_409618();
```

随后更新场景/单位状态、执行事件脚本，并通过 `DXDRAW` 对象输出画面。线程结束前会发送 `WM_CLOSE`。

## 4. 脚本命令引擎

命令定义文件是 `游戏目录（改版）/DEFCMD.LST`，格式为：

```text
命令名  参数个数  命令ID
```

完整命令表：

```text
[Normal]
End       1   0
TalkB     4   1
SetTalkB  4   2
DoTalkB   0   3
SetNowDef 3   4
SysTalk   6   5
SetHint   3   6
MenuTalk  2   7
SetScene  2   8
SetWalk   3   9
WaitWalk  2  10
StopWalk  2  11
SetEnabled 2 12
SetVisible 2 13
SetWait   3  14
Nop       0  15
SetCursor 3  16
FadeOut   4  17
FadeIn    4  18
ChangeScene 4 19
SetAni    7  20
SetTick   2  21
SetShadow 2  22
SetPos    4  23
Disable   1  24
Enable    1  25
Redraw    1  26
SetPlayer 1  27
SetCamera 1  28
SetView   2  29
SlideTo   3  30
PlayerAct 1  31
SetFlag   2  32
AddFlag   2  33
TalkA     5  34
Switch    2  35
SetVar    2  36
Random    3  37
SetFlagVar 2 38
AddFlagVar 2 39
GetItem   2  40
BlackTalk 4  41
SetChaPic 2  42
SetWeather 2 43
ShowMenu  2  44
TeamMember 2 45
Note      2  46
SetBlock  2  47
Attribute 3  48
SetSwitch 2  49
BuyMenu   3  50
PlaySound 2  51
StopSound 1  52
PlayMusic 2  53
SetMusic  2  54
TheEnd    1  55
Fix       1  56

[Special]
CheckResult 2 60
CheckFlag   3 61
CheckItem   3 62
CheckTeam   3 63
MiniGame    3 64
CheckMember 4 65
War         1 66

[NoArg]
Else       82
```

命令到事件函数的逐项映射见 [script_command_mapping.md](script_command_mapping.md)。

`SCE::TSCE` 内部有三个命令表区域：

- 普通命令表：100 项
- 特殊命令表：20 项
- 无参数命令表：20 项

`sub_40EBD4` 直接读取 16 位 opcode，按 ID 跳转到对应事件函数。`Else(82)` 不是直接函数，而是根据当前 `dword_755AAC` 决定跳过脚本段。

脚本中的“AI/事件”函数分布在 `0x0040A220` 到 `0x00410209`，例如 `TalkB`、`SetScene`、`SetWalk`、`WaitWalk`、`CheckFlag`、`CheckTeam`、`SetSwitch`、`Random` 等。

## 5. 数据文件格式

### 5.1 普通原始文件

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `TKMat.Dat` | 2,304,000 | 单位数据库，6000 条 × 384 字节；反编译中为 `dword_51AF40[96 * id]` |
| `TKDefUnit.dat` | 80,000 | 单位定义，按 `16 * dword_753504` 读取 |
| `WarData.dat` | 109,062 | 战争数据，单条记录 498 字节 |
| `WarWay.dat` | 102,400 | 战争路线，按 1024 字节块读取 |
| `TKAct.dat` | 509,600 | 动作/动画数据，加载到固定缓冲区 |
| `SC.GRP` / `SC.IDX` | 101,076,094 / 868 | 地图/场景资源包 |
| `WSC.GRP` / `WSC.IDX` | 42,758,162 / 336 | 场景资源包 |
| `SWS.GRP` / `SWS.IDX` | 150,843,156 / 2,028 | 世界地图资源包 |
| `SSF.GRP` / `SSF.IDX` | 20,744,550 / 256 | 战斗/头像资源包 |
| `SMG.GRP` / `SMG.IDX` | 790,180 / 88 | 小游戏资源包 |

### 5.2 LZSS 压缩文件

`sub_45343C` 读取的格式为：

```text
[解压后大小: 4][压缩后大小: 4][LZSS payload]
```

首个 DWORD 会与调用者传入的最大缓冲区比较，随后读取压缩大小，分配内存，用 `sub_452B14` 解压。

| 文件 | 当前大小 | 头部解压/压缩大小 |
| --- | --- | --- |
| `TKItem.dat` | 8,883 | 38,400 / 8,875 |
| `TKSkill.dat` | 6,638 | 32,900 / 6,630 |
| `TKShop.dat` | 866 | 1,920 / 858 |
| `TKKon.dat` | 5,152 | 26,000 / 5,144 |
| `WarPC.dat` | 35,571 | 212,878 / 35,563 |

注意：EXE 中 `WarPC.dat` 的调用点硬编码最大 150,722 字节，而当前 `WarPC.dat` 的解压大小声明为 212,878。按原版 `sub_45343C` 逻辑会报错。如果当前环境能正常运行，说明有运行期补丁/辅助器，或未走到该加载路径。

### 5.3 取反文本文件

`TKD.dat` 和 `TKT.dat` 在加载时会逐字节取反：

```c
*p = ~*p;
```

取反后使用 Big5/CP950 编码读取。

- `TKD.dat`：事件脚本源，`DEFINE`、`{...}`、`;` 注释、`SetSwitch`、`AddFlag`、`End` 等。
- `TKT.dat`：文本数据库，包含战役标题、对话、地点名、角色列传。

### 5.4 图形/媒体文件

| 签名 | 格式 |
| --- | --- |
| `4A 47 58 50` | `JGXP`，GXP 图形表面 |
| `40 4A 56 47` | `@JVG`，JVG 动画/图像 |
| `52 49 46 46 ... 41 56 49 20` | `RIFF/AVI `，例如 `TKObj.dat` 实际是 AVI 容器 |
| `.GRP` + `.IDX` | 资源包与索引对 |

音频路径：

```text
sound\%04d.mp3
sound\%04d.wav
```

视频/片头：

```text
Logo1.avi
Logo2.avi
Title.avi
```

### 5.5 存档

```text
save\%d.sav
save\sav.%d
save.gxp
```

存档槽位索引由 `(arglist[614870] + 1) / 2 + 3 * arglist[614900]` 计算。

## 6. 编码与本地化

程序内置多字节码转换：

```text
u2b.dat  unicode-big5
b2u.dat  big5-unicode
b2g.dat  big5-gb
b2j.dat  big5-sjis
j2b.dat  big5-sjis
g2b.dat  gb-big5
```

游戏原生文本是繁体 Big5；不要用 GBK 直接解析 `TKD.dat`/`TKT.dat`。

## 7. 改版相关的额外信息

- `DEFCMD.LST` 可以重新定义命令名/参数个数/ID，但增加真正的新指令需要同步修改 `sub_40EBD4` 的分支。
- `TKMat.Dat` 是直接可改的单位数据库，改前先备份；每条 384 字节，首字段是单位类型/状态。
- `TKD.dat`/`TKT.dat` 编辑流程：逐字节取反 -> CP950 解码 -> 修改 -> CP950 编码 -> 再取反写回。
- 目录中的 `SanxiaHelper.ini` 是辅助器配置，不是原版文件：

```ini
[HOT_KEY]
CpuDown=67      ; C
ConvMouse=77    ; M
NoEnemy=78      ; N
FullScreen=70   ; F
Teleport=84     ; T
AutoClick=76    ; L
ExtraWallet=80  ; P
NoTmpDat=79     ; O
```

- 当前目录部分数据文件时间和大小与 2002 年原始文件不同，说明目录是修改版；修改 `WarPC.dat` 时要注意上面提到的 150,722 上限。

## 8. 分析索引与完成状态

已完成专项的完整索引见 [README.md](README.md)。战斗核心、AI、公式、技能分发、小游戏、资源与文本存档等主题均已单独立档：

1. 战斗核心汇编分析：[sub_4400DC_battle_core_analysis.md](sub_4400DC_battle_core_analysis.md)
2. 战斗 AI 决策：[AI_decision_analysis.md](AI_decision_analysis.md)
3. 技能效果分发：[sub_4458B0_skill_case_index.md](sub_4458B0_skill_case_index.md)
4. 伤害/命中/行动价值公式：[sub_43E980_formula_analysis.md](sub_43E980_formula_analysis.md)
5. 7 个小游戏规则：[minigame_reverse_analysis.md](minigame_reverse_analysis.md)
6. `TKObj.dat` 片尾 AVI 分析：[TKObj_analysis.md](TKObj_analysis.md)
7. `sub_40EBD4` 的 0-82 号脚本命令逐项映射：[script_command_mapping.md](script_command_mapping.md)
8. TKMat 384 字节字段完整表（外部参考）：[`逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md`](../../../逆向工作区/docs/02_数据格式与解码/TKMat文件格式参考手册.md)
9. 存档系统运行时写读链路：[save_system_runtime.md](save_system_runtime.md)
10. `TKD.dat`/`TKT.dat` 编码与双向转换：[text_data_encoding.md](text_data_encoding.md)，工具在 [`逆向工作区/tkt_tkd_roundtrip.py`](../../../逆向工作区/逆向工作区/tkt_tkd_roundtrip.py)
11. WarPC 角色数据模块：[character_data_warpc.md](character_data_warpc.md)
12. 物品/技能/商店/条件数据模块：[item_skill_shop_condition_data.md](item_skill_shop_condition_data.md)
13. 动画与精灵绑定模块：[animation_sprite_binding.md](animation_sprite_binding.md)
14. 场景/地图/音乐资源管线：[scene_resource_pipeline.md](scene_resource_pipeline.md)
15. 字体与文本渲染模块：[font_text_rendering.md](font_text_rendering.md)
16. MOD 扩展容量与硬编码边界：[modding_capacity_limits.md](modding_capacity_limits.md)
17. 运行时内存布局与关键全局变量：[runtime_memory_map.md](runtime_memory_map.md)
18. 场景 ID -> SC.GRP Section 精确映射：[scene_grp_mapping.md](scene_grp_mapping.md)
19. 存档 Block A/B 字段布局：[save_block_ab_fields.md](save_block_ab_fields.md)
20. TKAct 记录结构与运行时推进：[tkact_record_structure.md](tkact_record_structure.md)
21. WarData.map_id -> WSC.GRP/WarWay 映射：[wsc_grp_mapping.md](wsc_grp_mapping.md)
22. TKSkill 描述文本 ID 规则：[tkskill_description_rule.md](tkskill_description_rule.md)
23. Ani.JVG 实际触发路径：[ani_jvg_trigger_path.md](ani_jvg_trigger_path.md)
24. Awt/Awk 切换点：[awt_awk_switch.md](awt_awk_switch.md)
25. 运行时文本格式化引擎：[text_formatting_engine.md](text_formatting_engine.md)
26. 验证缺口清单：[verification_gaps.md](verification_gaps.md)
27. Alpha 混合公式：[alpha_blend_formula.md](alpha_blend_formula.md)
28. WarPC 尾部字段映射：[warpc_tail_fields_map.md](warpc_tail_fields_map.md)
29. 方向编号与映射：[direction_mapping.md](direction_mapping.md)
30. TKKon 运行时字段映射：[tkkon_runtime_fields.md](tkkon_runtime_fields.md)
31. WarPC 技能 -> TKKon 映射表：[warpc_skill_tkkon_mapping.md](warpc_skill_tkkon_mapping.md)

当前批次已无待办；后续若继续扩展 MOD，可按 `modding_capacity_limits.md` 评估需要同步修补的常量。
