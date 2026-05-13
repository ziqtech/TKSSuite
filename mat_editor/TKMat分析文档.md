# TKMat.Dat 数据结构分析

严格依据反编译代码。实体表 `dword_51AF40`，每条 384 字节 (96 × int32)，共 6000 条。

## 加载

- `sub_412688:21`: `sub_452544(aTkmatDat_0, dword_51AF40, 2304000)` — 原始二进制读取，无 LZSS 压缩
- `sub_41103C:26`: `sub_452B14(v5, &v8, dword_51AF40)` — 场景文件 LZSS 解压后覆盖实体表区域
- 文件大小: 2,304,000 = 6000 × 384

## 字段定义 (仅含反编译证实的)

| 索引 | 偏移 | 类型 | 名称 | 反编译证据 |
|------|------|------|------|-----------|
| [0] | 0 | int32 | type | 实体类型。sub_405CBC 按类型分支: 5/10/15/16/20/110/200 |
| [1] | 4 | int32 | scene_id | 所属场景。-1=全局。sub_405CBC 检查 v13[1]==dword_755B58 |
| [2] | 8 | int32 | flags | 标志位。sub_40C5A4/sub_40C648 操作 bit0/bit1 (禁用/启用) |
| [3] | 12 | int32 | timer | 等待计时器。sub_40BF88 ("SetWait") 写入 |
| [4] | 16 | int32 | tick | 事件Tick周期。sub_40C388 ("SetTick") 写入: `[96*a1+4]=a2` |
| [8] | 32 | int32 | sub_flags | 子标志。sub_408E5C 检查 bit0x10 (中断), bit0x20 (路径等待) |
| [9] | 36 | int32 | anim_set | 动画集ID (0-4)。sub_405CBC 使用 `dword_755AC0[v2[9]]` |
| [10] | 40 | int32 | x | 世界坐标X (像素)。sub_407070: `a1[10] = x` |
| [11] | 44 | int32 | y | 世界坐标Y (像素)。sub_407070: `a1[11] = y` |
| [13] | 52 | int32 | direction | 朝向 (1~8)。sub_4077E4: `if(a2>0&&a2<=8) a1[13]=a2` |
| [14] | 56 | int32 | frame_idx | 当前动画帧索引。sub_4077E4 根据 direction/[53]/[52]/[16] 计算 |
| [16] | 64 | int32 | frame_count | 总帧数。sub_4540E8 返回 |
| [17] | 68 | int32 | frame_cur | 当前帧计数。sub_405CBC, sub_40C1A4 |
| [18] | 72 | int32 | bound_x | 碰撞盒X起点。sub_410B74 范围判定 |
| [19] | 76 | int32 | bound_y | 碰撞盒Y起点。sub_410B74 范围判定 |
| [28] | 112 | int32 | cur_define | 当前DEFINE脚本号。sub_40B520 读取/写入 |
| [30] | 120 | int32 | max_A | 子场景A最大阶段数。sub_40EBD4 case 0, sub_40B520 |
| [31] | 124 | int32 | max_B | 子场景B最大阶段数 |
| [32] | 128 | int32 | max_C | 子场景C最大阶段数 |
| [33] | 132 | int32 | cur_A | 子场景A当前阶段。sub_40EBD4 case 0 |
| [34] | 136 | int32 | cur_B | 子场景B当前阶段 |
| [35] | 140 | int32 | cur_C | 子场景C当前阶段 |
| [39] | 156 | int32 | head_A | DefUnit链头A。sub_4066F0 (a2=0) |
| [40] | 160 | int32 | head_B | DefUnit链头B。sub_4066F0 (a2=1) |
| [41] | 164 | int32 | head_C | DefUnit链头C。sub_4066F0 (a2=2) |
| [42] | 168 | int32 | script_PC | 脚本程序计数器。sub_40EBD4 读取/写入 |
| [43] | 172 | int32 | saved_PC | 保存的程序计数器。sub_40EBD4: `[42]=[43]; [43]=-1` |
| [44] | 176 | int32 | defunit_idx | DefUnit记录索引。sub_40EBD4:18 `word_755AB2 = [96*a1+44]` |
| [50] | 200 | int32 | char_id | 所需角色ID。sub_4081F8 检查 `[200] > 0` |
| [51] | 204 | int32 | picture_id | 角色图片ID/玩家访问位掩码。sub_4081F8, sub_405CBC |
| [52] | 208 | int32 | anim_handle | 主动画句柄。sub_405CBC, sub_40D0CC |
| [53] | 212 | int32 | dir_mode | 方向模式: 4=NPC四方向, 8=玩家八方向, 其他=静态。sub_4077E4 |
| [56] | 224 | int32 | saved_x | 保存的X坐标 (路径寻找备份)。sub_408E5C |
| [57] | 228 | int32 | saved_y | 保存的Y坐标。sub_408E5C |
| [60] | 240 | int32 | dest_x | 移动目标X。sub_408E5C, sub_4081F8 |
| [61] | 244 | int32 | dest_y | 移动目标Y。sub_408E5C, sub_4081F8 |
| [64] | 256 | int32 | sub_model | 子角色动画模型ID。sub_405CBC, sub_40C1A4 |
| [65] | 260 | int32 | sub_handle | 子角色动画句柄。sub_405CBC, sub_40C1A4 |
| [67] | 268 | int32 | cur_frame | 当前动画帧。sub_405CBC, sub_40C1A4 |
| [68] | 272 | int32 | max_frame | 最大动画帧。sub_405CBC, sub_40C1A4 |
| [69] | 276 | int32 | anim_speed | 动画播放速度。sub_40C1A4 |
| [70] | 280 | int32 | moving | 移动中标志。sub_4077E4: `if(!a1[70])` |

## 实体类型枚举

| 值 | 名称 | sub_405CBC 处理 |
|----|------|----------------|
| 0 | 空槽 | 跳过 |
| 5 | 入口/传送点 | 跳过动画块 |
| 10 | 地形块 | sub_4526D0 绘制, 最多5个子位置 |
| 15 | 障碍物 | - |
| 16 | 建筑/门 | - |
| 20 | 事件对象 | Ani.jvg 动画 ([65] = sub_45410C) |
| 110 | 特殊机关 | dword_755AC0[anim_set] 动画 |
| 200 | NPC/角色 | Cha.jvg + Ani.jvg, 4/8方向渲染 |

## 空记录判定

`type == 0` → 空槽。gen_world_map_detail.py 实测: 2477 有效实体 / 6000 槽位。
