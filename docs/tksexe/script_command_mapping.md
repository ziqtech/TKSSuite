# SCE 脚本命令 0-82 速查表

> 来源：`decompile/40EBD4.c` 逐 case 对照 `DEFCMD.LST`；参数语义补充参考 `逆向工作区/docs/03_脚本_事件_地图机制/脚本与事件系统.md`。
> 所有脚本数据按 16 位字（WORD）读取：第 1 个 WORD 是命令 ID，后续 WORD 是参数。

## 1. 执行模型

```text
sub_40EBD4(entity_id)
  -> 从 dword_51AF40[96 * entity_id] 取实体状态
  -> 从 DEFINE 表取当前脚本字节码指针
  -> while(1): 读命令 ID -> switch -> 按命令推进 PC
```

- 普通命令推进固定长度。
- 等待类命令（`WaitWalk`、`SetWait` 等）会把 PC 写回实体状态并让出，下次继续。
- 条件命令：条件成立走 `+base`，不成立走 `+offset` 并设置 `dword_755AAC = 2`。
- `Else(82)` 依据 `dword_755AAC` 决定跳过还是继续。

## 2. 普通命令 0-56

| ID | 命令 | 参数 | VM 动作 | PC |
| --- | --- | --- | --- | --- |
| 0 | `End` | mode | mode 0 恢复 saved PC；mode 1-3 递增对应循环计数并越界清零；mode 4-6 清零对应计数；未知 mode 报错 | 特殊 |
| 1 | `TalkB` | 4 | `sub_40A220(...,0,1)` 绘制对话，随后 `sub_40AEF4` 翻页 | +5 |
| 2 | `SetTalkB` | 4 | `sub_40A220(...,0,1)` 绘制对话，不阻塞 | +5 |
| 3 | `DoTalkB` | 0 | `sub_40AEF4()` 对话翻页 | +1 |
| 4 | `SetNowDef` | 3 | `sub_40B520(entity, selector, value)` 切换 DEFINE 链/序列/动画/帧 | +4 |
| 5 | `SysTalk` | 6 | `sub_40B1B4(...)` 系统提示/气泡 | +7 |
| 6 | `SetHint` | 3 | `sub_40B650(entity, hint, flag)` 设置提示并切换 flags bit3 | +4 |
| 7 | `MenuTalk` | 2 | `sub_40B710(text_id, text_id, result_slot)` 多选项，结果写 `word_755E50[result_slot]` | +3 |
| 8 | `SetScene` | 2 | `sub_40BB70(entity, scene_id)` 写实体场景归属 | +3 |
| 9 | `SetWalk` | 3 | `sub_40BC10(entity, x, y)` 设置行走目标 | +4 |
| 10 | `WaitWalk` | 2 | `sub_40BCC0(entity, flag)`；未到达则保存 PC 返回 | +3 或出让 |
| 11 | `StopWalk` | 2 | `sub_40BD84(entity, dir)` 对 type=200 实体停止/调整朝向 | +3 |
| 12 | `SetEnabled` | 2 | `sub_40BE30(entity, on)` 切换 flags bit0 | +3 |
| 13 | `SetVisible` | 2 | `sub_40BEDC(entity, on)` 切换 flags bit1 | +3 |
| 14 | `SetWait` | 3 | `sub_40BF88(entity, base, range)` 设置随机等待 | +4 |
| 15 | `Nop` | 0 | 保存 PC 并出让 | +1 |
| 16 | `SetCursor` | 3 | `sub_411BA4(...)` 切换调色板/光标资源 | +4 |
| 17 | `FadeOut` | 4 | `sub_409830(0,34,3,delay,r,g,b)` 淡出 | +5 |
| 18 | `FadeIn` | 4 | `sub_409830(34,0,-3,delay,r,g,b)` 淡入 | +5 |
| 19 | `ChangeScene` | 4 | `sub_40C044(scene,x,y,dir)` 切换场景 | +5 |
| 20 | `SetAni` | 7 | `sub_40C1A4(e,pic,start,end,cur,speed,loop)` 设置动画 | +8 |
| 21 | `SetTick` | 2 | `sub_40C388(entity, tick)` 写实体 tick | +3 |
| 22 | `SetShadow` | 2 | `sub_40C428(entity, shadow_id)` 写阴影帧 | +3 |
| 23 | `SetPos` | 4 | `sub_40C4D8(entity,x,y,dir)` 设置坐标/朝向 | +5 |
| 24 | `Disable` | 1 | `sub_40C5A4(entity)` 清 flags bit0/bit1 | +2 |
| 25 | `Enable` | 1 | `sub_40C648(entity)` 置 flags bit0/bit1 | +2 |
| 26 | `Redraw` | 1 | `sub_40C6EC(frames)` 按帧数循环重绘等待 | +2 |
| 27 | `SetPlayer` | 1 | `sub_40C7CC(entity)` 设置当前玩家实体 | +2 |
| 28 | `SetCamera` | 1 | `sub_40C854(entity)` 设置摄像机；-1 清除 | +2 |
| 29 | `SetView` | 2 | `sub_40C8E0(x,y)` 瞬时移动摄像机 | +3 |
| 30 | `SlideTo` | 3 | `sub_40C9E8(x,y,frames)` 平滑卷动摄像机 | +4 |
| 31 | `PlayerAct` | 1 | 写 `dword_755B60`（玩家行动/场景活跃标记） | +2 |
| 32 | `SetFlag` | 2 | `sub_40CB08(flag_id, val)` 写全局标志 | +3 |
| 33 | `AddFlag` | 2 | `sub_40CB4C(flag_id, delta)` 累加全局标志 | +3 |
| 34 | `TalkA` | 5 | `sub_40A220(...,0)` 无立绘对话 | +6 |
| 35 | `Switch` | 2 | `sub_40CB90(entity, mode)` 切换地图/战斗行走模式 | +3 |
| 36 | `SetVar` | 2 | `word_755E80[slot] = val`，slot <= 249 | +3 |
| 37 | `Random` | 3 | `word_755E80[slot] = min + rand(max-min+1)` | +4 |
| 38 | `SetFlagVar` | 2 | 读变量后 `sub_40CB08(flag, var)` | +3 |
| 39 | `AddFlagVar` | 2 | 读变量后 `sub_40CB4C(flag, var)` | +3 |
| 40 | `GetItem` | 2 | `sub_40CE30(item, count, 1)` 获得物品/金钱 | +3 |
| 41 | `BlackTalk` | 4 | `sub_40B05C(text_id,x,y,color)` 居中文本提示 | +5 |
| 42 | `SetChaPic` | 2 | `sub_40D0CC(entity, pic_id)` 设置角色立绘 | +3 |
| 43 | `SetWeather` | 2 | `sub_40D2A0(type, on)` 天气切换 | +3 |
| 44 | `ShowMenu` | 2 | 淡出 + `sub_40D2D0(type)` 姓名输入/商店菜单 + 淡入 | +3 |
| 45 | `TeamMember` | 2 | `sub_40DA00(character, op)` 角色入队/离队 | +3 |
| 46 | `Note` | 2 | `sub_40DBF4(slot, value)` 写 Note 数组（1000 项） | +3 |
| 47 | `SetBlock` | 2 | `sub_40DC1C(entity, on)` 切换实体碰撞块 | +3 |
| 48 | `Attribute` | 3 | `sub_40E11C(target, stat, delta)` 修改角色/队伍属性 | +4 |
| 49 | `SetSwitch` | 2 | `word_755E10[slot] = val`，slot < 32 | +3 |
| 50 | `BuyMenu` | 3 | 淡出 + `sub_40D804(area,cat,sub)` 购买界面 + 淡入 | +4 |
| 51 | `PlaySound` | 2 | `sub_451780(1)` + `sub_451C38(sound_id)` 播放音效 | +3 |
| 52 | `StopSound` | 1 | `sub_451D2C(..., sound_id)` 停止音效 | +2 |
| 53 | `PlayMusic` | 2 | 播放 BGM；可选写 `byte_755B74[scene]` | +3 |
| 54 | `SetMusic` | 2 | 写 `byte_755B74[scene] = music_id` | +3 |
| 55 | `TheEnd` | 1 | `word_951940 = value + 100`，结束游戏流程 | 特殊 |
| 56 | `Fix` | 1 | 空操作，跳过参数 | +2 |

> 17/18 方向说明：`sub_40512C` 中 0 表示重建正常调色板 LUT，34 表示纯色 LUT，因此 17（0→34）是淡出，18（34→0）是淡入。

## 3. 特殊命令 60-66

条件命令的“真”分支固定推进基础长度；“假”分支按偏移跳转并设置 `dword_755AAC = 2`。

| ID | 命令 | 参数 | VM 动作 | 真 PC |
| --- | --- | --- | --- | --- |
| 60 | `CheckResult` | 2 | 比较 `word_755E50[slot] == val` | +4 |
| 61 | `CheckFlag` | 3 | `sub_40E40C(flag, val, cmp)` 比较全局标志 | +5 |
| 62 | `CheckItem` | 3 | `sub_40E4E4(item, val, cmp)` 比较物品/好感/金钱 | +5 |
| 63 | `CheckTeam` | 3 | `sub_40E65C(type, val, cmp)` 检查队伍 | +5 |
| 64 | `MiniGame` | 3 | `sub_40E97C(type, target, cmp, &result)` 执行小游戏 | +5 |
| 65 | `CheckMember` | 4 | `sub_40E88C(char, party, val, cmp)` 检查队员属性 | +6 |
| 66 | `War` | 1 | `sub_40EB10(war_id, 0)` 启动战斗；1=胜利 | +3 |
| 82 | `Else` | 1 | `dword_755AAC` 控制跳过/继续 | 特殊 |

## 4. 未定义与边界

- 57-59、67-81 未在 `DEFCMD.LST` 定义，`sub_40EBD4` 落入 `default` 报错。
- 36 号 `SetVar` 变量槽上限 249（`> 0xF9` 报错）。
- 37 号 `Random` 要求 `min < max`。
- 49 号 `SetSwitch` 槽位上限 31（`>= 0x20` 报错）。
- 60 号 `CheckResult` 槽位上限 23（`>= 0x18` 报错）。
- 46 号 `Note` 槽位上限 999（`>= 0x3E8` 静默忽略）。

## 5. 参考

- 字节码执行器：`decompile/40EBD4.c`
- 命令表定义：`逆向工作区/DEFCMD.LST`
- 详细脚本/事件分析：[`逆向工作区/docs/03_脚本_事件_地图机制/脚本与事件系统.md`](../../../逆向工作区/docs/03_脚本_事件_地图机制/脚本与事件系统.md)
