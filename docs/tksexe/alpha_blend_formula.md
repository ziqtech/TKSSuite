# Alpha 混合公式

> 覆盖 `sub_454D24 -> sub_454D90 / sub_4553A4` 的 RGB LUT 混合逻辑。

## 1. 输入

```text
a6 = alpha（1..31）
v12 = 32 - a6
```

若 `a6 == 0` 或 `a6 > 31`，走普通 `sub_4544EC` 路径，不做混合。

## 2. LUT 混合

每个像素通道按颜色位深查表：

```text
out_channel = lut[32-alpha][dst_channel]
            + lut[alpha][src_channel]
```

LUT 基址：`word_A39D30`，行偏移为 `alpha << 7`。

颜色掩码：

| 位深 | R | G | B |
| --- | --- | --- | --- |
| 16bpp | `0x1F` | `0x7E0` | `0xF800` |
| 15bpp | `0x1F` | `0x3E0` | `0x7C00` |

## 3. 结论

这不是“源像素乘 alpha + 目标像素乘 (1-alpha)”的常规公式，而是两组 32 级查表相加：`(32-alpha)` 表贡献目标通道，`alpha` 表贡献源通道。

## 4. 参考

- `decompile/454D24.c`、`454D90.c`、`4553A4.c`
- `word_A39D30` 光照/混合矩阵
