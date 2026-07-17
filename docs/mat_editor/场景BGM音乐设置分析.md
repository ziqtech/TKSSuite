# 场景BGM背景音乐设置分析

> 基于反编译 `sub_412688` / `sub_40EBD4` / `sub_40C044` 及静态数据表 `unk_4E7CF4` 的完整逆向分析。

---

## 一、系统架构

BGM 不存储在 TKMat.dat 实体数据中，而是由**三层机制**协同控制：

```
游戏启动
  └─ sub_412688: exe 静态表 unk_4E7CF4 (250B) → byte_755B74[256]

脚本执行 (TKD.dat)
  └─ SetMusic(scene_id, music_id) → 覆盖 byte_755B74[scene_id]

场景切换
  └─ ChangeScene(scene_id, x, y, dir)
       └─ sub_40C044: 查 byte_755B74[scene_id] → 加载 Sound/{id:04d}.mp3
```

---

## 二、第一层：静态默认表

> **逆向核对**：`412688.c:35-44` `v8=byte_755B74; v7=&unk_4E7CF4; do{*v8=*v7...}while(v5<250)` 确认 250 字节静态表 → `byte_755B74`；`40EBD4.c:436-443`（SetMusic，本文下方标 448-458，**实际行号为 436-443**）`if(music<0x100) byte_755B74[scene]=music`，负值时 `sub_44ACE8` 停 BGM。前两层机制均已核实；静态表具体数值属内存 dump 实测。

### 2.1 初始化代码

**文件**：`decompile/412688.c`，第 35-44 行

```c
v8 = byte_755B74;           // BGM 运行时表 (256 字节)
v7 = (char *)&unk_4E7CF4;   // exe 内静态默认表 (250 字节)
do {
    *v8 = *v7;              // 逐字节复制
    ++v5; ++v8; ++v7;
} while (v5 < 250);         // 共复制 250 个场景
```

### 2.2 静态表完整内容

**内存地址**：`0x4E7CF4`，250 字节，scene_id = 偏移量

**数据源**：`memory/004E6000--005E6000.txt` 第 470-490 行

| 场景范围 | BGM ID | mp3 文件 | 说明 |
|---------|--------|----------|------|
| 0 | 01 | 0001.mp3 | 大地图（条件切换为 02 或 19） |
| 1 | 0F (15) | 0015.mp3 | 初始场景 |
| 2-6 | FF (-1) | 无 | 教学/特殊场景，静音 |
| 7 | 09 | 0009.mp3 | |
| 8 | 0A (10) | 0010.mp3 | |
| 9-11 | 0F (15) | 0015.mp3 | |
| 12-31 | 04 | 0004.mp3 | |
| 32-50 | 07 | 0007.mp3 | |
| 51-52 | 0E (14) | 0014.mp3 | |
| 53-60 | 06 | 0006.mp3 | |
| 61-65 | 0A (10) | 0010.mp3 | |
| 66-68 | 07 | 0007.mp3 | |
| 69-74 | 06 | 0006.mp3 | |
| 75 | 0F (15) | 0015.mp3 | |
| 76-80 | 0D (13) | 0013.mp3 | |
| 81-86 | 06 | 0006.mp3 | |
| 87-91 | 07 | 0007.mp3 | |
| 92-97 | 0D (13) | 0013.mp3 | |
| 98-99 | 0E (14) | 0014.mp3 | |
| 100-102 | 08 | 0008.mp3 | |
| 103-105 | 0E (14) | 0014.mp3 | 仙人小屋（后被脚本 SetMusic 覆盖为 17） |
| **106-110** | **08** | **0008.mp3** | **天師塚系列** |
| 111-117 | 0E (14) | 0014.mp3 | 邺城（后被脚本覆盖为 05） |
| 118-122 | 06 | 0006.mp3 | |
| ... | ... | ... | 共 250 字节 (scene 0-249) |

> **注意**：FF (-1) 表示该场景无默认 BGM，进入时静音。

---

## 三、第二层：脚本命令覆盖

### 3.1 SetMusic — opcode 54

**文件**：`decompile/40EBD4.c`，第 448-458 行

```c
case 54:  // SetMusic(scene_id, music_id)
    if (scene_id < 0x100u)                              // scene_id < 256
    {
        if (scene_id == dword_755B58 && music_id < 0)   // 当前场景且设负数
            sub_44ACE8(&unk_9E0A04);                     // → 停止 BGM
        byte_755B74[scene_id] = (BYTE)music_id;          // 写入绑定
    }
```

- 仅写入绑定关系，**不立即播放**
- 下一次 `ChangeScene` 到该场景时生效
- 多次调用会覆盖（用于剧情推进后切换 BGM）

### 3.2 PlayMusic — opcode 53

**文件**：`decompile/40EBD4.c`，第 435-446 行

```c
case 53:  // PlayMusic(music_id, loop?)
    if (music_id >= 0)
    {
        sub_44AC50(&unk_9E0A04, music_id);   // 加载 MP3
        sub_44AC90(&unk_9E0A04, loop != 0);  // 播放
        if (loop)
            byte_755B74[current_scene] = music_id;  // 同时更新当前场景绑定
    }
    else
    {
        sub_44ACE8(&unk_9E0A04);              // 停止 BGM
    }
```

- **立即播放**，不等待场景切换
- 如果 `loop != 0`，同时更新当前场景的 BGM 绑定

---

## 四、第三层：ChangeScene 播放

**文件**：`decompile/40C044.c`，第 9-56 行

```c
int __cdecl sub_40C044(__int16 new_scene, __int16 x, __int16 y, __int16 dir)
{
    sub_4529D8();                                    // 预清理

    if (new_scene != dword_755B58)                   // ★ 场景确实变了
    {
        // --- BGM 处理 ---
        if (byte_755B74[new_scene] >= 0)             // 目标场景有 BGM 绑定?
        {
            // 同曲目跳过：如果新旧场景绑定同一首 BGM，不重新加载
            if (dword_755B58 < 0
                || byte_755B74[old] != byte_755B74[new])
            {
                sub_44AC50(&unk_9E0A04, byte_755B74[new]);  // 加载 MP3
                sub_44AC90(&unk_9E0A04, 1);                  // 循环播放
            }
        }
        else
        {
            sub_44ACE8(&unk_9E0A04);                 // 无 BGM → 停止
        }

        sub_451BB0(v4, 20);                          // 停止所有音效
        dword_755B58 = new_scene;                    // 更新当前场景 ID

        // --- 场景加载 ---
        sub_402B88(new_scene);                       // 加载 .twm 背景

        // 碰撞网格参数（大地图 vs 普通场景）
        if (new_scene && new_scene != 201) {
            dword_51AF90 = 18; dword_51AF94 = 16; dword_51B008 = 8;
        } else {
            dword_51AF90 = 5;  dword_51AF94 = 5;  dword_51B008 = 10;
        }

        sub_405CBC();                                // 重建活跃实体列表
    }

    // --- 无论场景是否切换都执行 ---
    sub_402E88();                                    // 加载 DefUnit
    sub_407070(player, x, y);                        // 设置玩家坐标
    sub_4077E4(player, dir);                         // 设置玩家朝向
    dword_8242BC = -1;                               // 重置最近 NPC
    // ... 其他状态重置 ...
}
```

### 关键逻辑

1. **场景没变**（同一场景内传送）：跳过整个 BGM 处理，BGM 继续播放
2. **场景变了 + 有绑定** + **不是同一首曲目**：加载新 MP3，循环播放
3. **场景变了 + 有绑定** + **同一首曲目**：跳过加载（避免中断重播）
4. **场景变了 + 无绑定**（FF）：停止当前 BGM

---

## 五、BGM 音频文件

### 5.1 文件路径

MP3 格式：`Sound/%04d.mp3`（来自 `sub_44AC50` 反编译）

| 资源 | 数量 | 格式 | 路径 |
|------|------|------|------|
| BGM MP3 | 29 首 | MP3 | `Sound/0000.mp3` ~ `Sound/0028.mp3` + `Sound/0100.mp3` |
| BGM WAV | 21 段 | WAV | `SMG.GRP` (备用/内嵌) |
| 音效 | 63 段 | WAV | `SSF.GRP` |

### 5.2 已知 BGM 与场景对应

| music_id | 文件 | 典型场景 |
|----------|------|---------|
| 1 | 0001.mp3 | 大地图(条件) |
| 2 | 0002.mp3 | 大地图(条件) |
| 3 | 0003.mp3 | 虎牢关战斗/特殊 |
| 4 | 0004.mp3 | 场景 12-31 |
| 5 | 0005.mp3 | 邺城区域(111-118) |
| 6 | 0006.mp3 | 李府初始(133-137)、场景 53-60,69-74,81-86,118-122 |
| 7 | 0007.mp3 | 场景 32-50,66-68,87-91 |
| 8 | 0008.mp3 | 天師塚(106-110)、场景 100-102 |
| 9 | 0009.mp3 | 医术提升(6)、許家村区域(205-209) |
| 10 | 0010.mp3 | 场景 8,61-65 |
| 12 | 0012.mp3 | 建业(130-132)、鲁肃府(160)、钟山(161-162) |
| 13 | 0013.mp3 | 襄阳(181-184)、场景 76-80,92-97 |
| 14 | 0014.mp3 | 场景 34-37,51-52,98-99,103-105,111-117 |
| 15 | 0015.mp3 | 场景 1,9-11,75 |
| 17 | 0017.mp3 | 仙人小屋(103-105，脚本覆盖) |
| 19 | 0019.mp3 | 大地图(0，脚本覆盖) |
| 21 | 0021.mp3 | 南阳(144-145)、北海(171-175)、武威(176-180) |

---

## 六、如何为新场景设置 BGM — 完整操作指南

### 6.0 核心原理：脚本必须放在源传送点上

SetMusic 在 ChangeScene **之前**执行才有效：

```
玩家踩到源地图传送点 (type=10)
  → sub_4081F8 → 脚本执行: SetMusic(目标场景, 音乐ID)
  → sub_40C044(目标场景, x, y, dir)
      → 查 byte_755B74[目标场景] → 加载 BGM ✓
      → 加载场景背景 → BGM 已响起
```

**不能放在目标地图的传送点上**：玩家已经到了才开始执行，BGM 在离开时才生效，等于设反了。

### 6.1 实体类型：必须用 type=10

type=5 被 `sub_409618` 显式跳过，无 per-tick 处理器，不调用 `sub_4081F8`，无法执行脚本也无法传送。只有 type=10 具备完整能力。

### 6.2 脚本内容

TKD.dat DEFINE 脚本，最简形式：

```
SetMusic(目标场景ID, 音乐ID)
End(0)
```

**不需要 PlayMusic**：`SetMusic` 写入绑定后，`sub_40C044` 切场景时自动检查 `byte_755B74[新场景]` 并播放。

### 6.3 实体字段配置清单

在 mat_editor 中配置 type=10 传送点实体的字段：

| 字段 | 推荐值 | 说明 |
|------|--------|------|
| **d0** (type) | 10 | 必须是 type=10 |
| **d1** (scene_id) | 源场景ID | 玩家当前所在场景 |
| **d2** (flags) | 15 | bit0=启用 bit1=可见 bit2=可交互 bit3=提示 |
| **d8** (cursor_id) | 3 | 开门光标动画 |
| **d18-d21** (碰撞盒) | 合理范围 | AABB 碰撞检测，玩家走入触发 |
| **d23** (hint_id) | 300+目标场景ID | 悬停显示目标场景名称 |
| **d44** (defunit_idx) | DefUnit索引 | 指向包含 SetMusic 脚本的 DefUnit |
| **d40** (head_B) | 同 d44 | B链头 |
| **d31** (max_B) | 1 | B链长度 |
| **d34** (cur_B) | 1 | ★ 触发开关：>0 时 sub_4081F8 执行脚本 |
| **d30** (max_A) | **0** | ★ 必须为 0 |
| **d33** (cur_A) | **0** | ★ 必须为 0 |
| **d52** (target_scene) | 目标场景ID | 传送目标（≠ 源场景） |
| **d53** (target_x) | 目标X坐标 | 玩家到达位置 |
| **d54** (target_y) | 目标Y坐标 | 玩家到达位置 |
| **d56** (target_dir) | 朝向 1-8 | 玩家到达朝向 |

### 6.4 ★ d30/d33 必须为 0 的原因

`End(0)` 在 `LABEL_16` 结尾调用 `sub_4066F0(entity, 0)`（模式0 = A链检查）：

```c
// sub_4066F0 mode 0（来自 decompile/4066F0.c）
if (entity[30](max_A) <= 0 || entity[33](cur_A) <= 0) {
    entity[44] = -1;   // defunit_idx → 清空！
    entity[42] = -1;   // script_PC → 清空！
    return;
}
```

- **d30=0 且 d33=0**：条件命中 → entity[44] = -1 → 下帧 `sub_40EBD4` 发现 `entity[44] < 0` → 立即返回，脚本不重复执行 ✓
- **d30>0 或 d33>0**：条件不命中 → entity[44] 不清空 → ChangeScene 重建实体后恢复 → 每帧重复触发 → **角色被锁死不能移动** ✗

### 6.5 完整执行流程（sub_4081F8）

```c
// decompile/4081F8.c，逐行注释
int sub_4081F8(int entity_id, int entity)
{
    if (game_frozen) return 0;
    if (entity[62] || !AABB_check(entity, player)) return 0;  // 碰撞检测
    if (entity[50] > 0 && player_char != entity[50]) return 0; // 角色条件
    if (entity[51] && (entity[51] & (1 << (dir-1))) == 0) return 0; // 访问掩码

    // ★ 进入脚本执行
    if (entity[34]) {                      // cur_B > 0?
        sub_4066F0(entity, 1);             // 模式1: 沿 B 链走到 cur_B，设 entity[43]
        entity[42] = 0;                    // script_PC = 0（从脚本开头执行）
        sub_40EBD4(entity_id);             // ★ 执行 SetMusic + End(0)
    }

    // End(0) → LABEL_16 → sub_4066F0(entity, 0)
    //   → d30=0 → entity[44] = -1 → 脚本不再执行

    sub_409830(fade);                      // 淡出效果
    sub_40C044(entity[52], entity[53],     // ★ ChangeScene
               entity[54], entity[56]);    //   → BGM 自动播放
    return 1;
}
```

### 6.6 操作步骤总结

1. **准备 DefUnit**：在 TKDefUnit.dat 中创建一个 DefUnit，指向包含 `SetMusic + End(0)` 的 DEFINE
2. **准备 TKD.dat DEFINE**：在 script_editor 中创建 DEFINE，内容 `SetMusic(目标场景ID, 音乐ID)` + `End(0)`
3. **在 mat_editor 中配置实体**：
   - 找到**源地图**中玩家踩上去的 type=10 传送点
   - 按上面表格填写 d40/d31/d34/d44（B链）和 d52-d56（传送目标）
   - **确认 d30=0 且 d33=0**
4. **保存并测试**：玩家踩上传送点 → 听到 BGM 切换 → 进入目标场景 → BGM 继续播放

---

## 七、关键运行时变量

| 变量 | 地址 | 类型 | 说明 |
|------|------|------|------|
| `byte_755B74` | `0x755B74` | `BYTE[256]` | BGM 绑定表，索引=scene_id，值=music_id（-1=无） |
| `dword_755B58` | `0x755B58` | `int` | 当前场景 ID |
| `unk_9E0A04` | `0x9E0A04` | 音频对象 | BGM 音频播放器实例 |
| `unk_4E7CF4` | `0x4E7CF4` | `BYTE[250]` | exe 内静态默认 BGM 表 |

## 八、相关反编译文件

| 文件 | 函数 | 说明 |
|------|------|------|
| `decompile/412688.c` | sub_412688 | 游戏数据初始化，复制静态 BGM 表 |
| `decompile/40EBD4.c` | sub_40EBD4 | 脚本 VM，case 53=PlayMusic, case 54=SetMusic, case 0=End |
| `decompile/40C044.c` | sub_40C044 | ChangeScene，场景切换 + BGM 播放 |
| `decompile/4081F8.c` | sub_4081F8 | 传送点触发，脚本执行入口，调用 sub_4066F0 → sub_40EBD4 → sub_40C044 |
| `decompile/4066F0.c` | sub_4066F0 | DefUnit 链定位，模式0检查A链并清零 entity[44] |
| `decompile/409618.c` | sub_409618 | 实体 tick 处理器，每帧调用 sub_4081F8（仅 type=10） |
| `memory/004E6000--005E6000.txt` | — | 静态默认 BGM 表原始数据 |
