# TKAct.dat 记录结构

> 覆盖 784 字节动作记录的完整布局：方向表、8 个 80 字节槽位、音效事件队列与运行时推进逻辑。

## 1. 文件格式

| 属性 | 值 |
| --- | --- |
| 大小 | 509600 字节 |
| 记录 | 650 条 × 784 字节（0x310） |
| 加载 | `sub_411624` -> `sub_452544("TKAct.dat", &unk_9539CA, 509600)` |
| 工作区 | `unk_9D037A`，运行时复制当前动作记录 |

## 2. 记录布局

| 偏移 | 大小 | 内容 |
| --- | --- | --- |
| 0x00 | 32 | 方向表：4 方向 × 8 槽 |
| 0x20 | 4 | 记录头保留字（当前数据基本为 0） |
| 0x24 | 2 | 总时长 `word_9D039E` |
| 0x26 | 2 | 帧计数 `word_9D03A0`（文件=0，运行时递增） |
| 0x28 | 40 | 事件帧标记 `word_9D03A2[]` |
| 0x50 | 80 | slot[1] |
| 0xA0 | 80 | slot[2] |
| 0xF0 | 80 | slot[3] |
| 0x140 | 80 | slot[4] |
| 0x190 | 80 | slot[5] |
| 0x1E0 | 80 | slot[6] |
| 0x230 | 80 | slot[7] |
| 0x280 | 80 | slot[8] |
| 0x2D0 | 64 | 音效事件队列 |

## 3. 方向表

```text
dirtable[dir][k]
dir = 0..3
k   = 0..7
值  = 0（不绘制）或 1..8（取 slot[n]）
```

运行时 `v33 = byte_9DF446[20*unit]`，`v44 = rec[8*v33 + k]`，然后 `slot = rec + 80*v44`。

## 4. slot 字段（80 字节 = 40 × int16）

| int16 | 字节 | 名称 | 说明 |
| --- | --- | --- | --- |
| 0 | 0 | type | 1=Aa，2=Af 主段，3=Af 延迟，4=锚点，5=中心 |
| 1 | 2 | jvg_block | JVG 帧/块 ID |
| 2 | 4 | direction_mode | 4=随方向，其它=固定方向 0 |
| 3-6 | 6-12 | x_off[0..3] | 四方向 X 偏移 |
| 7-10 | 14-20 | y_off[0..3] | 四方向 Y 偏移 |
| 11 | 22 | blend_mode | 0-5 对应 6 种渲染函数 |
| 12 | 24 | blend_param | Alpha/混合参数 |
| 13 | 26 | blend_param_step | 每帧步进 |
| 14 | 28 | rt_frame_base | 运行时绝对帧基址 |
| 15 | 30 | rt_cur_frame | 运行时当前帧 |
| 16 | 32 | dir_frame_offset | 多方向帧偏移倍率 |
| 17 | 34 | first_frame | 循环起点（相对帧） |
| 18 | 36 | last_frame | 循环终点（相对帧） |
| 19 | 38 | loop_behavior | -1 循环，-2 停止，>=0 跳帧 |
| 20 | 40 | rt20 | 运行时保留 |
| 21 | 42 | tick_interval | 帧停留 tick 数 |
| 22 | 44 | start_delay | 启动延迟 |
| 23 | 46 | rt_counter | 运行时 tick 计数 |
| 24 | 48 | rt_dir_sign | 帧推进方向 +1/-1/0 |
| 25 | 50 | move_mode | 1=直线跟随，2=弧线往返 |
| 26 | 52 | step_value | 位移步进 |
| 27 | 54 | step_delta | 位移加速度 |
| 28-39 | 56-78 | reserved | 未在 `sub_4434BC` 中直接读取 |

## 5. 音效事件队列

记录末尾 0x2D0 起为 16 组事件，每组 2 × int16：

```text
[sound/status][trigger_frame]
```

运行时在每帧扫描队列，按触发帧播放/停止 DirectSound WAV。

## 6. 记录级元数据

方向表后的 0x20-0x4F 不是简单保留区：

| 偏移 | 符号 | 语义 |
| --- | --- | --- |
| 0x24 | `word_9D039E` | 动作总时长/总帧数 |
| 0x26 | `word_9D03A0` | 运行时当前帧计数，文件内为 0 |
| 0x28+ | `word_9D03A2[]` | 事件帧标记/移动分段，最多 8 个被主循环跟踪 |

`sub_4434BC` 用 `word_9D03A2[0]` 作为移动距离除数，并用 `word_9D039E` 控制动作帧循环。

全量 598 条非空记录统计：

| 偏移 | 非零条数 |
| --- | --- |
| 0x24 | 598 |
| 0x28 | 489 |
| 0x2A | 369 |
| 0x2C | 116 |
| 0x2E | 10 |
| 0x30 | 1 |

## 7. 运行时推进

```text
if delay_counter > 0: delay_counter--，暂停
else:
  frame_tick++
  if frame_tick >= tick_interval:
    frame_tick = 0
    按 move_mode 更新 x/y 偏移
    到达 last_frame 后按 loop_behavior 处理
    当前帧 += frame_direction
    blend_param += blend_param_step
    step_value += step_delta
```

## 8. 已知数据问题

- 方向 1 与方向 2 在 598 条非空记录中 100% 一致。
- 方向 0 与方向 3 有 9 条不一致，多为方向 3 缺层、重复图层或顺序颠倒。
- 详见 [`docs/skill_editor/TKAct方向表数据错误分析.md`](../skill_editor/TKAct方向表数据错误分析.md)。

## 9. 参考

- [`逆向工作区/docs/05_角色与动画系统/角色动画系统分析.md`](../../../逆向工作区/docs/05_角色与动画系统/角色动画系统分析.md)
- [`逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md`](../../../逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md)
- [`act_editor/act_editor_v2.py`](../../act_editor/act_editor_v2.py)
