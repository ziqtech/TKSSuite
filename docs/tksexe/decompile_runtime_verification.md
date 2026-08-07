# 反编译与运行时行为验证报告

> 本报告是 [editor_source_verification.md](editor_source_verification.md) 的第二阶段，专门验证存档之外、编辑器源码未直接实现的运行时行为。
> 基准：`反编译产物/` 的 `decompile/*.c`、`disassembly/*.asm`、`function_index.txt`、`pointers.txt`、`strings.txt` 与真实 `TKS.exe`。

## 1. 函数引用完整性

- `docs/tksexe/*.md` 中出现的全部 `sub_*` 函数名均能在 `function_index.txt` 找到，缺 0 个。
- 全部 `0x0040xxxx` 函数地址均能对应到函数索引，缺 0 个。
- 原 `ui_menu_world_flow.md` 中 `0x00421103C` 是笔误，已修正为 `0x0041103C`（即 `sub_41103C`）。
- `function_index.txt` 记录 2040 个函数，`decompile/` 有 2033 个 C 文件；`4400DC.asm` 因超过 3000 条指令以反汇编 fallback 导出。

## 2. 启动、主循环与界面流程

### `WinMain`（40162C.c）

- 读取系统语言、删除 `tmp.dat`、初始化 Application 并 `Application.Run()`，与文档一致。

### `TForm1_FormCreate`（4030F0.c）

- 先打开 `SC.IDX/SC.GRP` 与 `WSC.IDX/WSC.GRP`，再 `sub_44EC0C(..., 640, 480, 1)` 创建 DirectDraw 主表面。
- 优先加载 `TKDef.txt` 写回 `TKD.dat`，否则直接加载 `TKD.dat`；随后 `sub_401E88()` 处理 TKT/TKTalk。
- 加载 `TKMat.Dat`、`TKDefUnit.dat`、`TitleMenu.gxp`，最后随机 `Logo1.avi`/`Logo2.avi`。

### 主线程（412BE8.c）

- 初始化 `Mu.jvg`、`pface.jvg`、输入与 `sub_425EAC`。
- 循环节拍为 `GetTickCount()` 间隔至少 `0x3C` ms。
- 每帧调用 `sub_405C28 / sub_412390 / sub_411E84 / sub_409618`，随后渲染并调用 `sub_40B2D0` 处理场景输入。
- 结束时调用 `sub_4128AC(word_951940)` 并发送 `WM_CLOSE`。

### 菜单与场景切换

- `sub_426164` 使用 `a1[461]` 状态 0/1/6/7/8/9/10，存档槽位公式 `(a1[614870]+1)/2 + 3*a1[614900]` 与文档一致。
- `sub_40C044` 在场景变化时切换 `byte_755B74[a1]` BGM、调用 `sub_402B88`/`sub_405CBC`/`sub_402E88`，最后设置玩家坐标/朝向。

## 3. 脚本引擎

### `sub_40EBD4`（40EBD4.c）

- 逐 case 核对 0-82 号命令：参数读取、PC 增量、等待类写回、条件跳转与 `dword_755AAC` 深度均与 `script_command_mapping.md` 一致。
- `End` 模式已修正：`1/2/3` 分别递增 `cur_A/cur_B/cur_C` 并越界归零，`4/5/6` 分别清零，`0` 恢复 `saved_PC`；不是简单的“返回上一级”。
- `SetVar` 上限 249、`Random` 要求 `min < max`、`SetSwitch` 上限 31、`CheckResult` 上限 23 均在 C 代码中得到确认。

### TKD / DEFINE

- 真实 `TKD.dat` 整文件 XOR 后为 Big5 文本，含 1539 个 `DEFINE` 块。
- `sub_402E88` 加载 5000×16B 的 `TKDefUnit.dat`，`sub_402BE8` 搜索 `DEFINE <id>`，`sub_41425C` 编译为字节码指针。
- `sub_4066F0` 沿 `TKDefUnit` 的 `dword3`（字节 12）推进链，不是旧文档所说的 `[f6]`。

## 4. 实体、地图与事件系统

- `409618.c` 确认调度：type 5 无专用 tick；type 10 走 `sub_4081F8`；type 15 走 `sub_408408`；type 16 走 `sub_4084E0`；type 20 或 type 200 且 `moving==1` 走 `sub_408704`。
- `405CBC.c` 确认 type 20 使用 `Ani.JVG`（`dword_755AFC`），type 200 使用 `Cha.JVG`（`dword_755AF0`）+ `Ani.JVG` 行走帧。
- `entity_map_event_system.md` 的实体类型表、TKMat 字段表与 TKDefUnit 布局已按反编译和 `mat_constants.py` 修正。

## 5. 战斗菜单、AI、公式与技能分发

### 战斗菜单 `sub_447DAC`

- 状态 0-43、动作码 1000/2000/3000/4000/98/99/180、目标格 `byte_952D54==1`、目标写入 `word_9D6F7C/7E` 与 `byte_9D6FA4/9D6FC4` 均与 C 代码一致。
- `3000` 防御写 `word_9D6C7C=-2`，`4000` 待机写 `-3`；技能/道具最终统一进入 `sub_4458B0`。

### 战斗主循环与结算

- `43CA64.c` 使用 `word_951940` 作为结果码，`-2/-1/1/2` 语义一致。
- `43B7FC.c` 确认经验/JP 池、30% 加成、30000 上限、掉落钳 99、金钱上限 9999。
- 金钱倍率已修正：`sub_452AC0(100)&3 + 2` 实际为 `2..5`，原文档写 `random(2..4)`。
- `43BF20.c` 回写 0x41C（1052B）到永久 WarPC，并把 `field[526]` 单独写入 `word_758324`；死亡单位 HP 置 1。

### AI 决策

- `436678/435D68/4359A4` 确认玩家方/敌方分派、AI 技能池、全图扫描和最高评分选择。
- 平手随机替换已修正：`sub_452AC0(1000) < 0x1F4` 是 50%，不是 20%。
- `43D53C/43D8B0` 确认目标/效果网格、过滤规则、技能 242 随机写 `word_9D6C30` 或 `word_9D6C38=50`。

### `sub_43E980`

- 基础值、技能专属倍率、命中 `攻击+50-目标防御`、距离修正 5%/15%/25%/50%、钳制 10..95、伤害 `ATK²/(ATK+3*DEF)` 随机区间、敌我正负号和状态价值均与 `43E980.c` 一致。
- 技能 200 的命中低于 5 时钳制到 20，文档已补充。

### `sub_4458B0`

- 技能 4-9 陷阱、44/50/81/126 连击、94 破咒、136 修罗刀扣 50 HP、157 天变、167 陌上桑、194/195 锁足/缩地、196 异位、197 障碍、238 打点、239 探宝 80/15/5、243 十八啦等分支均能在 `4458B0.c` 对应位置找到。

### `sub_4400DC`

- `disassembly/4400DC.asm` 存在且为 fallback 导出（超过 3000 条指令）。
- 关键阶段与公式可复现：技能 243-247 特判、道具治疗、HP/MP 两轮结算、经验/JP/金钱/掉落、状态结果入队。

## 6. 小游戏

- `40E97C.c` 确认先加载 `SMG.GRP/SMG.IDX`，按 type 1-7 分派到 `42AC40/428DAC/429C20/42DD88/42ED40/42D3A4/42E414`，并统一按 `a3==1 ? a2<=result : a2>result` 比较。
- 各 loader 确认资源名 `MG_WA/MG_EIGHT/MG_eighteen/MG_Ball/MG_44/MG_rotate/MG_reverse` 的 `.jvg/.gxp`。
- 关键常量复核：
  - 类型 1：`dword_95155C=300` 秒，5×4 网格，胜利条件 `dword_9513AC==2`。
  - 类型 2：8 个目标槽 + 40 格工作区，胜利序列 `64,37,26,28,7,39,55,52`。
  - 类型 3：双方初始 3000，4 骰 `sub_4B5A94()/0x1555+1`。
  - 类型 4：12 槽，胜利序列 `6,5,4,3,2,1`。
  - 类型 5：4×4 和 34 判定。
  - 类型 6/7：3×3 旋转与 4×4 龙蛇翻转结构存在。

## 7. 文本、字体、渲染与音视频

- `409C60.c` 的控制码展开与 `text_formatting_engine.md` 完全一致：`0x14=TEXT`、`0x15=VARNUM`、`0x16=VARTXT`、`0x1D=NAME`，未知标签报 `MakeText error`。
- `FONT9696` 的 `44B384/44B208/44E49C/44F420` 已由 `font9696_codec.py` 和实际文件验证。
- `454D24/454D90/4553A4` 确认 32 级 LUT 相加，`word_A39D30` 基址、`alpha<<7` 行偏移、16bpp/15bpp 掩码均正确。
- `451580/44AC50/44A2B8/45B98C/45BA78/45BB64` 确认 `sound\%04d.wav`、`sound\%04d.mp3`、DirectShow `CoCreateInstance` 和 `u2b/b2u/g2b` 双 0x20000 读取。
- `strings.txt` 找到 `Logo1.avi`、`Logo2.avi`、`Title.avi`、`TKObj.dat`，与文档路径一致。

## 8. 方向与运行时内存

- `4075C0.c` 的 8 方向编号与文档一致；`449F84.c` 实际使用 `target - current` delta，文档措辞已修正。
- `pointers.txt` 与反编译代码确认 `word_824290/292`、`word_78E276` 为 16 位变量，`0x753500` 的符号名是 `lpBuffer`；`runtime_memory_map.md` 已同步。

## 9. 发现并修正的问题

| 文件 | 修正 |
| --- | --- |
| `ui_menu_world_flow.md` | 读取存档地址 `0x00421103C` -> `0x0041103C` |
| `entity_map_event_system.md` | 实体类型、TKMat 字段表、TKDefUnit 布局按反编译修正 |
| `script_engine_SCE.md` | `End` 1-6 的具体递增/清零语义 |
| `battle_loop_and_rewards.md` | 金钱倍率 `random(2..4)` -> `random(2..5)` |
| `AI_decision_analysis.md` | 平手随机替换 20% -> 50% |
| `direction_mapping.md` | delta 方向从 `current-target` 改为 `target-current` |
| `runtime_memory_map.md` | `word_824290/292`、`word_78E276`、`lpBuffer` 命名 |
| `sub_43E980_formula_analysis.md` | 技能 200 命中下限 20 |

## 10. 结论

存档之外的主要运行时文档均能与反编译/反汇编和真实文件相互印证。脚本命令、战斗菜单、AI 决策、公式、技能分发、小游戏调度、文本格式化、Alpha 混合和音视频路径均已闭环。

仍需运行时实测的只剩少量纯行为项：小游戏逐帧操作手感、战斗菜单光标交互、动画播放时序，以及没有真实存档文件时的存档写读链路。
