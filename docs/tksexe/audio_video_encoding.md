# 音频、视频与编码转换

## 1. 音效 WAV

路径：

```text
sound\%04d.wav
```

加载：`sub_451780`

- 解析 RIFF/WAVE
- 创建 DirectSound 缓冲区
- 播放/循环

## 2. BGM MP3

路径：

```text
sound\%04d.mp3
```

加载：`sub_44AC50`

```text
sprintf("sound\\%04d.mp3", id);
sub_44A8D8(player, path);
```

播放器为 `PlayMp3` 类，播放控制通过 `sub_44AD18` 等封装调用。

## 3. 片头/片尾 AVI

路径：

```text
Logo1.avi
Logo2.avi
Title.avi
TKObj.dat
```

加载：`sub_44A2B8`（DirectShow/COM）

- `CoCreateInstance`
- 建立 Graph
- 播放到窗口

刷新：`TForm1_MplayTimerTimer`。

## 4. 编码转换

文件：

```text
u2b.dat  Unicode -> Big5
b2u.dat  Big5 -> Unicode
b2g.dat  Big5 -> GB
b2j.dat  Big5 -> SJIS
j2b.dat  SJIS -> Big5
g2b.dat  GB -> Big5
```

加载函数：

| 地址 | 文件 | 用途 |
| --- | --- | --- |
| `0x0045B98C` | `u2b.dat` | Unicode -> Big5 |
| `0x0045BA78` | `b2u.dat` | Big5 -> Unicode |
| `0x0045BB64` | `g2b.dat` | GB -> Big5 |

转换表大小：

```text
每个表 2 × 0x20000 字节
```

## 5. 关键函数

| 地址 | 功能 |
| --- | --- |
| `0x00451780` | WAV -> DirectSound |
| `0x0044AC50` | MP3 加载 |
| `0x0044A2B8` | AVI DirectShow |
| `0x0045B98C` | Unicode/Big5 表 |
| `0x0045BA78` | Big5/Unicode 表 |
| `0x0045BB64` | GB/Big5 表 |

## 6. 结论

音频/视频系统：

```text
WAV -> DirectSound
MP3 -> PlayMp3
AVI -> DirectShow
文本编码 -> 查表转换
```

