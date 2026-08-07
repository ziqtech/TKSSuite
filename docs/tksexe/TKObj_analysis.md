# TKObj.dat 逆向分析

> 结论：`TKObj.dat` 不是对象/动作数据，也不是战斗动画索引，而是一个标准 RIFF/AVI 视频文件，作为游戏片尾/结局动画使用。

## 1. 文件身份

- 文件：`游戏目录（改版）/TKObj.dat`
- 大小：34,579,466 字节
- 头部：`RIFF .... AVI `
- 在 EXE 中，`TKObj.dat` 与 `Logo1.avi`、`Logo2.avi`、`Title.avi` 位于同一个 AVI 文件名表。
- 文件名表起始地址：`0x004E6164`

```text
0x004E6164: Logo1.avi
0x004E6174: Logo2.avi
0x004E6184: Title.avi
0x004E6194: TKObj.dat
```

## 2. 播放路径

`sub_403C08(a1)` 按索引调用 DirectShow 播放器：

```c
sub_44A2B8(handle, &aLogo1Avi[16 * a1], dword_A2B984);
```

索引对应关系：

| 索引 | 文件 | 用途 |
| --- | --- | --- |
| 0 | `Logo1.avi` | 随机开场 Logo |
| 1 | `Logo2.avi` | 随机开场 Logo |
| 2 | `Title.avi` | 标题动画 |
| 3 | `TKObj.dat` | 结局/片尾动画 |

`sub_4128AC` 在主线程结束时调用 `sub_403C08(3)`。脚本中的 `TheEnd` 命令：

```text
TheEnd(0) // 一般結局
TheEnd(1) // 貂嬋結局
TheEnd(2) // 孫尚香結局
```

对应 `word_951940 = 100/101/102`，随后统一先播放 `TKObj.dat`，再显示各自的 `00.gxp`/`04.gxp` 结局画面。

## 3. AVI 主头

| 字段 | 值 |
| --- | --- |
| `dwMicroSecPerFrame` | 33366 |
| 帧率 | 约 29.97 fps |
| `dwTotalFrames` | 3728 |
| `dwStreams` | 2 |
| `dwWidth` | 512 |
| `dwHeight` | 277 |
| `dwFlags` | 0x10 |
| 时长 | 约 124.4 秒 |

## 4. 视频流

- 流类型：`vids`
- Codec：`MPG4`，即 MPEG-4 Part 2 / MP4V
- 尺寸：512x277
- 位深：24-bit
- `biSizeImage`：425,472
- 视频帧数：3728

`movi` 内视频块统计：

| 项目 | 值 |
| --- | --- |
| `00dc` 总块数 | 3728 |
| 非空帧 | 3268 |
| 零长度帧 | 460 |
| 视频块大小范围 | 0 - 48,128 |
| 平均大小 | 约 7,770 字节 |

## 5. 音频流

- 流类型：`auds`
- 格式：Microsoft ADPCM（`wFormatTag = 0x0002`）
- 声道：2
- 采样率：44,100 Hz
- `nBlockAlign`：2048
- `01wb` 音频块数：129

## 6. `JUNQ` 自定义块

RIFF 主层存在一个 `JUNQ` 块，大小 768 字节：

- 前 158 字节全为 0
- 之后为约 610 字节非 ASCII 数据
- 全 768 字节，内容全零，位于 `hdrl` 与 `movi` 之间，判定为对齐/占位填充块

## 7. `idx1`

- 索引条目数：3857
- 与 3728 个视频块 + 129 个音频块一致

## 8. 对编辑器/替换的影响

- 不要按对象数据解析 `TKObj.dat`。
- 若要替换片尾动画，可以用 DirectShow 兼容的 AVI：
  - 视频：MPEG-4 Part 2，512x277，约 29.97 fps
  - 音频：Microsoft ADPCM，2ch，44.1 kHz
- 若只需要跳过片尾，可在 `sub_4128AC` 中 `sub_403C08(3)` 调用处做补丁。
