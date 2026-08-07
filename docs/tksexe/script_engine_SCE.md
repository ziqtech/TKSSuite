# SCE 脚本引擎与 DEFINE 执行

## 1. 模块定位

TKS 的地图事件/剧情脚本由 `SCE::TSCE` 管理：

```text
DefCmd.Lst  -> 命令名字表
TKD.dat     -> DEFINE 块源码
sub_402BE8  -> 按 DEFINE ID 切出源码段
sub_41310C  -> 初始化 SCE 命令表
sub_40EBD4  -> 执行已解析的 DEFINE 字节码
```

## 2. SCE::TSCE 对象布局

`sub_41310C` 在 `unk_4F9A60` 初始化三个命令表：

| 偏移 | 大小 | 内容 |
| --- | --- | --- |
| `+0` | 100 × 10 | 普通命令表 |
| `+1000` | 20 × 10 | 特殊命令表 |
| `+1200` | 20 × 10 | 无参数命令表 |

每个命令项约 10 字节，保存命令名/参数个数/命令 ID。

## 3. DefCmd.Lst 命令定义

文件：`DEFCMD.LST`

格式：

```text
命令名  参数个数  命令ID
```

分区：

```text
[Normal]
[Special]
[NoArg]
```

完整命令表见 [TKS_analysis.md](TKS_analysis.md) 第 4 节；命令到事件函数的逐项映射见 [script_command_mapping.md](script_command_mapping.md)，或直接读 `游戏目录（改版）/DEFCMD.LST`。

## 4. TKD.dat 与 DEFINE 块

`TKD.dat` 是 XOR `0xFF` 后的 Big5 文本，包含大量：

```text
DEFINE 46858496
{
;注释
TalkB(...)
...
};
```

`DEFINE ID` 由实体编码：

```text
DEFINE_ID = (entity_id << 16) | block_id
```

其中：

- `entity_id`：TKMat 实体 ID
- `block_id`：该实体的子场景/阶段编号

`sub_402BE8` 按 ID 搜索 `DEFINE <id>`，截取到 `end`，得到单块脚本文本。

## 5. 字节码执行

`sub_40EBD4` 是脚本执行器：

- 从实体表 `dword_51AF40[96 * entity]` 获取当前脚本状态。
- 脚本数据由 16 位字组成。
- 第一个 16 位是命令 ID，后续 16 位是参数。
- 按命令 ID 跳转到对应事件函数。

核心状态：

| 变量 | 含义 |
| --- | --- |
| `dword_75350C` | 当前实体 ID |
| `dword_755A98` | 当前实体记录 |
| `word_755AB2` | 脚本 PC（按 16 位字偏移） |
| `dword_755A94` | 当前脚本数据指针 |
| `dword_755AAC` | 跳转/Else 深度计数 |

## 6. 控制流

### `End`

`End` 有结束模式参数：

```text
End(0)  正常结束
End(1)  返回上一级/保留状态
End(2)  结束并继续后续外部流程
```

### `Else`

命令 ID 82。执行时：

```text
if 当前块条件失败:
    跳过到匹配的块结束
else:
    继续执行
```

### 等待类

`SetWait`、`WaitWalk`、`SetTick` 等不会立即完成，而是设置实体状态，由主循环后续帧推进。

## 7. 主要命令族

| 族 | 命令 |
| --- | --- |
| 对话 | `TalkA/TalkB/SetTalkB/DoTalkB/SysTalk/BlackTalk` |
| 场景 | `SetScene/ChangeScene/SetView/SlideTo` |
| 移动 | `SetWalk/WaitWalk/StopWalk/SetPos` |
| 显示 | `SetVisible/SetEnabled/Redraw/SetAni/SetShadow` |
| 角色 | `SetPlayer/SetCamera/SetChaPic/TeamMember` |
| 数据 | `SetFlag/AddFlag/SetVar/SetSwitch/Random/GetItem` |
| 商店/技能 | `BuyMenu/PlaySound/PlayMusic/SetMusic` |
| 条件 | `CheckFlag/CheckItem/CheckTeam/CheckMember/CheckResult` |
| 战斗 | `War` |
| 小游戏 | `MiniGame` |
| 结局 | `TheEnd/Fix` |

## 8. 关键函数

| 地址 | 功能 |
| --- | --- |
| `0x00402BE8` | 从 TKD 文本提取单个 DEFINE |
| `0x0041310C` | 加载 `DefCmd.Lst` 到命令表 |
| `0x0041335C` | 解析命令名/参数/ID |
| `0x0040EBD4` | 字节码执行器 |
| `0x00414C6C` | 创建脚本对象并加载 `Check.GRP` 校验数据 |

## 9. 结论

脚本系统不是独立语言，而是“文本定义 -> 命令 ID -> 事件函数”的查表执行：

- 改命令名/参数个数：改 `DEFCMD.LST`
- 加新命令：需要同时改 `sub_40EBD4` 分支
- 改剧情：直接编辑 `TKD.dat` 的 DEFINE 块
