# 资源格式汇总

## 1. GXP 图像

签名：`JGXP`

- 单张 RGB565 图像。
- 48 字节头。
- LZSS 压缩。
- 加载：`sub_450264`。

典型文件：

```text
TitleMenu.gxp
00.gxp
MG_*.gxp
save.gxp
```

## 2. JVG 动画/精灵

签名：

```text
@JVG
@JVM
@JVS
```

结构：

- `@JVG` 总头
- 多个 `@JVM` 块
- 每块含调色板、流数据、帧数据
- 帧像素按块调色板存储

典型文件：

```text
Cha.jvg  NPC/角色
Ani.jvg  动画
Aa/Af.jvg 攻击/特效
Awt/Awk.jvg 战斗待机/行走
Mu.jvg  菜单头像
Fa.jvg  战斗头像
```

加载：`sub_453BD0` + `sub_45410C`。

## 3. GRP/IDX 资源包

配对文件：

```text
SC.GRP + SC.IDX
WSC.GRP + WSC.IDX
SWS.GRP + SWS.IDX
SSF.GRP + SSF.IDX
SMG.GRP + SMG.IDX
```

IDX 保存区段偏移/大小。

GRP 区段类型：

| 类型 | 内容 |
| --- | --- |
| 图像 A | RGB565 主图 |
| 图层 L1/L2 | 前景/碰撞 |
| 音频 | WAV 波形 |
| 数据 | 原始二进制 |

压缩：

- A 帧：LZSS/RLE 混合
- B 帧：RLE 字节对

加载：`sub_451600`。

## 4. TKAct.dat 动作数据

大小：509,600 字节

结构：

```text
509600 / 650 = 784
```

即 650 条 × 784 字节。

每条包含方向表、8 图层、音效触发等，由 `sub_4434BC` 使用。

## 5. FONT9696 字体

文件：`FONT9696`（无扩展名）

结构：

```text
8 个 FTYPE 区段
每个 FTYPE: 14915 个字形
索引表: 每个字形 4 字节 uint32 偏移
数据区: RLE 位图
```

字形：

```text
96 x 96 像素
1 bpp
位图缓冲 1152 字节
```

RLE：

```text
每 3 字节编码 4 个 6-bit run
bit=1 表示背景
```

关键函数：

| 地址 | 功能 |
| --- | --- |
| `0x0044B384` | 字符码 -> 字形索引 |
| `0x0044B208` | RLE 解码 |
| `0x0044E49C` | 文本步进/渲染 |

## 6. 加载函数速查

| 格式 | 函数 |
| --- | --- |
| GXP | `sub_450264` |
| JVG | `sub_453BD0` |
| GRP/IDX | `sub_451600` |
| TKAct | `sub_411624` |
| FONT9696 | `sub_411624`/`sub_44B384` |

## 7. 结论

TKS 资源体系：

```text
GXP = 静态背景/界面
JVG = 精灵/动画
GRP = 大地图/场景/界面资源包
TKAct = 动作帧表
FONT9696 = 位图字体
```

