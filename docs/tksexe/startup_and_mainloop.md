# 启动流程与主线程循环

## 1. WinMain

地址：`0x0040162C`

```text
WinMain
  -> 读取系统语言
  -> 若 tmp.dat 存在则删除
  -> 初始化 Application/Form1
  -> Application.Run()
```

## 2. FormCreate

地址：`0x004030F0`

初始化顺序：

1. 打开 `SC.IDX/SC.GRP` 和 `WSC.IDX/WSC.GRP`
2. 创建 DirectDraw 640x480 主表面
3. 若有 `TKDef.txt`，加载并写入 `TKD.dat`
4. 否则直接加载 `TKD.dat`
5. 若有 `TKTalk.txt`，生成 `TKT.dat`
6. 否则加载 `TKT.dat`
7. 加载 `TKMat.Dat`、`TKDefUnit.dat`
8. 加载 `TitleMenu.gxp`
9. 随机播放 `Logo1.avi` 或 `Logo2.avi`

## 3. 视频/标题状态机

`dword_4E6150` 表示当前媒体阶段：

| 值 | 内容 |
| --- | --- |
| 0/1 | Logo1/Logo2 |
| 2 | Title.avi |
| 3 | TKObj.dat 片尾 |
| -1 | 已进入游戏 |

`sub_403C08` 通过 `sub_44A2B8` 调用 DirectShow 播放 AVI。

`TForm1_MplayTimerTimer` 每帧刷新媒体播放器，保证 Logo/Title/片尾能持续渲染。

## 4. 游戏线程创建

`sub_4018DC`：

```text
sub_41310C(&unk_4F9A60)      // 初始化 SCE 命令表
sub_411DFC(off_4E8134, 1)    // 创建 TKGMThread
dword_4E614C = 线程对象
```

线程入口实际为 `sub_412BE8`。

## 5. 主线程循环

地址：`0x00412BE8`

初始化：

- 加载 `Mu.jvg` 菜单头像
- 加载 `pface.jvg` 头像
- 加载 BGM/输入配置
- 调用 `sub_425EAC` 初始化菜单数据

主循环节拍约 60ms：

```text
等待 GetTickCount() 间隔 >= 0x3C
-> 更新输入/菜单
-> 更新实体
-> 执行事件脚本
-> DirectDraw 渲染
-> 刷新文本/特效
```

核心调用：

| 函数 | 用途 |
| --- | --- |
| `sub_405C28` | 实体动作初始化 |
| `sub_412390` | 输入/镜头 |
| `sub_411E84` | 动画推进 |
| `sub_409618` | 实体调度 |
| `sub_406444/406864` | 场景/实体渲染 |
| `sub_44F77C/44F83C` | DirectDraw 表面切换 |

## 6. 退出/结局

`sub_412BE8` 结束时调用 `sub_4128AC`：

```text
TheEnd(0) -> word_951940 = 100 -> 播放 TKObj.dat -> 一般结局
TheEnd(1) -> word_951940 = 101 -> 播放 TKObj.dat -> 貂蟬結局
TheEnd(2) -> word_951940 = 102 -> 播放 TKObj.dat -> 孫尚香結局
```

随后向窗口发送 `WM_CLOSE`。

## 7. 关键地址

| 地址 | 功能 |
| --- | --- |
| `0x0040162C` | WinMain |
| `0x004030F0` | FormCreate |
| `0x004018DC` | 创建 TKGMThread |
| `0x00403C08` | AVI 播放状态机 |
| `0x00403CC8` | Logo/Title 结束后进入游戏 |
| `0x00412BE8` | 主线程循环 |
| `0x004128AC` | 结局/章节结束 |
| `0x00403ED4` | MplayTimer 刷新 |

