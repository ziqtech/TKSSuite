# TKDefUnit.dat 与其他文件的引用/关联关系分析

严格依据反编译代码。分析范围：所有 `.dat` 文件和主要资源文件。

---

## 一、全局文件加载总览 (基于反编译代码)

> **逆向核对**：本表所有加载均已逐条验证——TKDefUnit `402E88:23`(80000)、TKMat `412688:21`(2304000)、TKAct `411624`(509600)、WarPC `4173F8:18`(150722)、TKItem `:19`(38400)、TKSkill `:20`(32900)、TKShop `:21`(1920)、TKKon `:22`(26000)，与各专文一致。

### 原始读取 (sub_452544: 直接 ReadFile, 无 LZSS)

| 文件 | 加载函数 | 目标缓冲区 | 大小 | 用途 |
|------|---------|-----------|------|------|
| TKDefUnit.dat | sub_402E88:23 | dword_753500 | 80,000B | 实体配置 |
| TKAct.dat | sub_411624:122 | unk_9539CA | 509,600B | 动画数据 |
| **TKMat.Dat** | **sub_412688:21** | **dword_51AF40** | **2,304,000B** | **实体表初始化** |
| *.grp/*.idx | sub_451600:44 | 动态分配 | 可变 | 通用资源包 |

### LZSS 解压读取 (sub_45343C: LZSS 解压)

| 文件 | 首次加载 | 目标缓冲区 | 解压大小 |
|------|---------|-----------|---------|
| WarPC.dat | sub_412688:22 | word_757F08 | 150,722B |
| WarPC.dat | sub_4173F8:18 | word_757F08 | (二次加载) |
| TKItem.dat | sub_4173F8:19 | word_77CBCA | 38,400B |
| TKSkill.dat | sub_4173F8:20 | word_7861CA | 32,900B |
| TKShop.dat | sub_4173F8:21 | unk_9508A0 | 1,920B |
| TKKon.dat | sub_4173F8:22 | unk_9D0698 | 26,000B |

### 文件系统直接访问 (fopen / sub_4B1FC8)

| 文件 | 用途 |
|------|------|
| TKD.dat | 脚本数据 (DEFINE 段解析) |
| TKT.dat | 文本数据库 |
| WarData.dat | 战斗数据 |
| WarWay.dat | 战场路径 |
| TKObj.dat | AVI 视频 |
| DefCmd.Lst | 脚本指令列表 |
| g2b.dat / b2g.dat 等 | 编码转换表 |

---

## 二、TKDefUnit.dat 与各文件的关系 (逐一分析)

### 2.1 TKDefUnit.dat ↔ TKMat.Dat ← 共享实体表 (直接关联)

**关系强度: ★★★★★ (核心关联)**

```
sub_412688:21   TKMat.Dat ──→ dword_51AF40 (实体表, 6000×384B)
sub_402E88:32    TKDefUnit.dat f1 ──→ dword_51AF40[96×v2+...] (查实体)
```

**证据:**
- `sub_412688:21`: `sub_452544(aTkmatDat_0, dword_51AF40, 2304000)` — TKMat.Dat 直接覆盖实体表
- `sub_402E88:32`: `dword_51AF40[96 * v2 + dword_4E6EF0]` — DefUnit 用 f1 索引此表
- `dword_51AF40` 是两者共享的核心数据结构

**数据流:**
```
TKMat.Dat (地图网格 200×240×48B) → dword_51AF40 (实体表)
TKDefUnit.dat (f1=实体ID) → dword_51AF40[96×f1] (查实体)
                            ↓
                     实体类型 [0] = 5/10/20/110/200...
                     场景ID   [1] = -1=全部场景
                     DefUnit索引 [44] = 初始脚本入口
                     脚本PC   [42] = 执行位置
```

### 2.2 TKDefUnit.dat ↔ TKD.dat ← 脚本字节码来源 (间接关联)

**关系强度: ★★★★☆**

```
TKD.dat DEFINE 段 ──→ sub_402BE8 解析 ──→ sub_41425C 创建脚本对象
                                              ↓
                                   TKDefUnit.dat offset 4 = 脚本指针
                                              ↓
                                   sub_40EBD4 以此为字节码执行
```

**证据:**
- `sub_402E88:37`: `if ( sub_402BE8() )` — 解析 TKD.dat 中的 DEFINE 段
- `sub_402BE8:32`: `sub_4BCFB4(v0, aDefine)` — 搜索 "DEFINE" 关键字
- `sub_402BE8:67`: `sub_4BCFB4(v5, aEnd)` — 搜索 "end" 关键字
- `sub_402E88:38`: `sub_41425C(dword_4FA598 - 1, dword_4FA000)` — 创建脚本对象

**注意:** DefUnit 文件本身不包含脚本字节码。offset 4 在文件中的值为 0（13条例外含坐标值）。运行时此字段被脚本对象指针覆盖。

### 2.3 TKDefUnit.dat ↔ TKAct.dat ← 实体动画数据 (间接关联)

**关系强度: ★★★☆☆**

```
sub_411624:122  TKAct.dat → unk_9539CA (509,600B)
                                  ↓
sub_405CBC  实体更新: 类型20/110/200 → 从 TKAct 获取动画帧
```

**证据:**
- `sub_411624:122`: `sub_452544(aTkactDat, &unk_9539CA, 509600)` — 全局加载
- `sub_405CBC:117-168`: 根据实体类型分配动画资源
- 无 DefUnit 字段直接引用 TKAct

**链:** `DefUnit f1 → 实体表 → 实体类型 → sub_405CBC → TKAct 动画数据`

### 2.4 TKDefUnit.dat ↔ WarPC.dat ← 战斗角色数据 (直接关联)

**关系强度: ★★★★☆**

```
sub_412688:22  WarPC.dat → word_757F08 (150,722B)
sub_4173F8:18  WarPC.dat → word_757F08 (二次加载, 36角色×527B)
```

**DefUnit 脚本直接操作 WarPC 数据:**
- case 40 → `sub_40CE30`: 给予/移除物品 → 修改角色装备/背包
- case 45 → `sub_40DA00`: 队员加入/离开 → 修改出战阵容
- case 48 → `sub_40E11C`: 修改角色属性 (HP/MP/STR/DEX等)
- case 61 → `sub_40E40C`: 检查事件标志
- case 62 → `sub_40E4E4`: 检查物品持有
- case 63 → `sub_40E65C`: 检查队伍状态
- case 65 → `sub_40E88C`: 检查队员条件

### 2.5 TKDefUnit.dat ↔ TKT.dat ← 文本数据库 (间接关联)

**关系强度: ★★★☆☆**

**证据:**
- `sub_401E88` 加载 TKT.dat → `dword_8242F0` (文本查找表)
- `sub_4119CC:21` 释放 `dword_8242F0` — 与 `dword_753500` (DefUnit缓冲区) 在同一清理函数中释放
- `sub_40EBD4` case 41 → `sub_40B05C` → 显示对话文本, 文本内容来自 `dword_8242F0` (TKT数据)
- `sub_40EBD4` case 1/2/34 → `sub_40A220` → 实体对话气泡, 同样使用 TKT 文本

**注意:** DefUnit 文件字段值 (f0-f7) 不直接引用 TKT ID。文本引用在脚本字节码的操作数中, 不在 DefUnit 记录字段中。旧文档 "TKDefUnit 字段值映射 TKT[-value]" 无代码证据。

### 2.6 TKDefUnit.dat ↔ TKItem.dat / TKSkill.dat / TKShop.dat / TKKon.dat

**关系强度: TKItem ★★★★☆ | TKSkill ★★★☆☆ | TKShop/TKKon ★★☆☆☆**

**TKItem.dat 直接关联证据:**
- `sub_40EBD4` case 40 → `sub_40CE30(entity, item_id, 1)` → 搜索 `word_77CBCA` (TKItem表), 添加物品到背包
- `sub_40EBD4` case 62 → `sub_40E4E4(entity, item_id, check_mode)` → 检查物品是否在背包中

**TKSkill.dat 间接关联:**
- WarPC 角色数据含技能索引, DefUnit case 45/48 操作角色数据时影响技能

### 2.7 TKDefUnit.dat ↔ WarData.dat / WarWay.dat

**关系强度: ★★★☆☆**

- `sub_40EBD4` case 66 → `sub_40EB10(entity, 0)` → 启动战斗模式
- `sub_40EB10` → `sub_436BD4` → `sub_42FDF8` 加载 WarData.dat → `byte_9537D8`
- `sub_40EB10` → `sub_436BD4` → `sub_42FE70` 加载 WarWay.dat → `unk_951942`

### 2.8 TKDefUnit.dat ↔ 资源文件 (.jvg / .grp / .gxp / .wav)

**关系强度: ★★☆☆☆ (间接, 通过实体类型或脚本操作码)**

| 资源文件 | 加载位置 | 与 DefUnit 的关联路径 |
|---------|---------|---------------------|
| Cha.jvg | sub_411624:44 | DefUnit f1 → 实体类型=200 → sub_405CBC |
| Ani.jvg | sub_411624:58 | DefUnit f1 → 实体类型=20/200 → sub_405CBC |
| Cur.jvg | sub_411624:72 | 光标动画 (无关) |
| SWS.GRP | sub_436BD4:19 | 屏幕切换效果 (无关) |
| Mu.jvg | sub_40D2D0:46 | 脚本操作码 case 44/50 |
| pface.jvg | sub_40D2D0:67 | 脚本操作码 case 44/50 |
| Mb.gxp | sub_40D804:20 | 脚本操作码 case 44/50 |
| smg.grp | sub_40E97C:19 | 脚本操作码 case 64 |
| ssf.grp | sub_40E97C:60 | 脚本操作码 case 64 |
| sound\*.wav | sub_451780:56 | 脚本操作码 case 51 |

**关键:** 所有 .jvg/.grp 引用均在脚本操作码或实体类型映射中, 不在 DefUnit 文件字段值中。

### 2.9 TKDefUnit.dat ↔ Check.GRP / DefCmd.Lst

**关系强度: ★★☆☆☆**

- `sub_41425C:37`: `sub_4BCFB4(v4, aCheckGrp)` — "Check.GRP" 用于验证 DEFINE 脚本格式
- `DefCmd.Lst` (0x4E81A0) — 脚本指令列表, 用于解析

这些是脚本解析工具文件, 不影响 DefUnit 的数据内容。

---

## 三、跨文件数据流图

```
                       ┌──────────────────┐
                       │   TKMat.Dat      │
                       │ 200×240×48B 网格  │
                       └────────┬─────────┘
                                │ sub_412688:21
                                ▼
    ┌──────────────────────────────────────────────┐
    │        dword_51AF40 (实体表)                  │
    │        6000条 × 384B = 2,304,000B            │
    │                                               │
    │  [0] 实体类型  [1] 场景ID  [10] X坐标         │
    │  [11] Y坐标   [42] 脚本PC  [44] DefUnit索引   │
    │  [39/40/41] DefUnit链头  [50] 动画ID          │
    └──────┬───────────────┬───────────────────────┘
           │               │
           │ 索引          │ 存储DefUnit索引
           │               │
    ┌──────┴──────┐ ┌──────┴──────────────┐
    │TKDefUnit.dat│ │     TKD.dat         │
    │ f1=实体ID   │ │  DEFINE { ... }     │
    │ f6=链表     │ │  脚本字节码         │
    └─────────────┘ └──────────┬──────────┘
                               │ sub_402BE8 解析
                               │ sub_41425C 创建对象
                               ▼
                    ┌────────────────────┐
                    │ sub_40EBD4         │
                    │ 脚本解释器 (82+指令)│
                    │                    │
                    │ case 1/2/34: 实体  │
                    │ case 19: 场景切换   │  ← 调用 sub_402E88 重载
                    │ case 44/50: 对话框  │     TKDefUnit.dat
                    │ case 51: 音效      │
                    │ case 64: 系统消息   │
                    └──────┬─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         sub_405CBC   sub_40D2D0   sub_451780
         实体更新      对话框       音效
              │            │            │
              ▼            ▼            ▼
         Ani.jvg      Mu.jvg      sound\*.wav
         Cha.jvg      pface.jvg
                      Mb.gxp
```

```
    ┌──────────────────────────────────────────────────┐
    │        sub_40EBD4 (脚本解释器) — 全部连接        │
    │                                                   │
    │  case 19 → sub_40C044 → sub_402E88 重载          │
    │            TKDefUnit.dat                          │
    │                                                   │
    │  case 40 → sub_40CE30 ────→ TKItem.dat           │
    │  case 41 → sub_40B05C ────→ TKT.dat              │
    │  case 44 → sub_40D2D0 ────→ Mu.jvg, pface.jvg    │
    │  case 45 → sub_40DA00 ────→ WarPC.dat            │
    │  case 48 → sub_40E11C ────→ WarPC.dat            │
    │  case 51 → sub_451780 ────→ sound\*.wav          │
    │  case 61 → sub_40E40C ────→ 事件标志              │
    │  case 62 → sub_40E4E4 ────→ TKItem.dat           │
    │  case 63 → sub_40E65C ────→ WarPC.dat            │
    │  case 65 → sub_40E88C ────→ WarPC.dat            │
    │  case 66 → sub_40EB10 ────→ WarData/WarWay.dat   │
    └──────────────────────────────────────────────────┘

LZSS 加载 (sub_45343C):
  WarPC.dat  ──→ word_757F08   (36角色)
  TKItem.dat ──→ word_77CBCA   (600物品)
  TKSkill.dat──→ word_7861CA   (350技能)
  TKShop.dat ──→ unk_9508A0   (商店)
  TKKon.dat  ──→ unk_9D0698   (条件)

原始加载 (sub_452544):
  TKMat.Dat ──→ dword_51AF40   (实体表)
  TKAct.dat ──→ unk_9539CA     (动画)
  TKDefUnit.dat→ dword_753500  (实体配置)

JVG加载 (sub_453BD0):
  Cha.jvg → dword_755AF0  Ani.jvg → dword_755AFC  Cur.jvg → dword_755AF8

文本加载 (sub_401E88):
  TKT.dat → dword_8242F0
```

---

### 2.10 TKDefUnit.dat ↔ 编码转换表 (g2b.dat / b2u.dat / u2b.dat / b2g.dat / j2b.dat)

**关系强度: ★☆☆☆☆ (间接, 通过文本显示)**

- `sub_45BB64`: 加载 g2b.dat (GB2312→Big5)
- `sub_45BA78`: 加载 b2u.dat (Big5→Unicode)
- `sub_45B98C`: 加载 u2b.dat (Unicode→Big5)
- DefUnit case 41 显示对话时需要编码转换

---

## 四、结论总结

| 关联类型 | 文件 | 证据强度 | DefUnit 交互方式 |
|---------|------|---------|----------------|
| **共享实体表** | TKMat.Dat | ★★★★★ | 同一 `dword_51AF40`, DefUnit f1 索引此表 |
| **脚本字节码源** | TKD.dat | ★★★★☆ | sub_402BE8 解析 DEFINE 段 → sub_41425C 创建脚本对象 |
| **物品操作** | TKItem.dat | ★★★★☆ | case 40 给物品, case 62 检查物品 |
| **角色属性操作** | WarPC.dat | ★★★★☆ | case 45/48 修改角色, case 61/62/63/65 检查 |
| **文本显示** | TKT.dat | ★★★☆☆ | case 41 对话; sub_4119CC 同生命周期释放 |
| **动画数据** | TKAct.dat | ★★★☆☆ | 实体类型→动画帧 (硬编码) |
| **战斗系统** | WarData/WarWay.dat | ★★★☆☆ | case 66 启动战斗 |
| **动画精灵** | Ani.jvg, Cha.jvg | ★★☆☆☆ | 实体类型映射 (硬编码), case 4/20/42 |
| **对话框资源** | Mu.jvg, pface.jvg, Mb.gxp | ★★☆☆☆ | case 44/50 触发加载 |
| **音效资源** | sound\*.wav | ★★☆☆☆ | case 51 触发加载 |
| **系统消息** | smg.grp, ssf.grp | ★★☆☆☆ | case 64 触发加载 |
| **技能系统** | TKSkill.dat | ★★☆☆☆ | 通过 WarPC 间接操作 |
| **商店系统** | TKShop.dat | ★★☆☆☆ | 通过 WarPC 间接操作 |
| **编码转换** | g2b/b2u/u2b.dat | ★☆☆☆☆ | 文本显示间接需要 |
| **视频** | TKObj.dat | ☆☆☆☆☆ | 无关联 |

**核心发现:**
1. TKDefUnit.dat **最紧密关联** TKMat.Dat — 共享实体表 `dword_51AF40`
2. TKDefUnit.dat 通过**脚本操作码** (sub_40EBD4) 间接操作 TKItem/WarPC/TKT/WarData 等文件数据
3. TKDefUnit.dat 文件字段 (f0-f7) **不直接引用** 任何资源文件或文本 — 均为实体组织/脚本指针
4. TKDefUnit.dat 的 f2-f3 (offset 4-7) 运行时被 TKD.dat 脚本指针覆盖
5. 旧文档 "DefUnit 字段值映射 TKT[-value]" **无任何反编译代码证据**
