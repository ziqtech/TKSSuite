# 字体与文本渲染模块

> 覆盖 `FONT9696` 位图字体、BIG5 索引、控制标签和文本渲染函数。
> 详细报告见 [`docs/tkt_editor/FONT9696逆向分析报告.md`](../tkt_editor/FONT9696逆向分析报告.md)。

## 1. FONT9696 文件

| 属性 | 值 |
| --- | --- |
| 文件 | `FONT9696` |
| 区段 | 8 个 FTYPE |
| 每区段字形数 | 14915 |
| 字形大小 | 96×96 像素，1bpp |
| 索引表 | 每个字形 4 字节 uint32 偏移 |
| 位图缓冲 | 1152 字节/字形 |

## 2. 字符索引

```text
BIG5 双字节 -> 低字节行内偏移 + 高字节区段 -> 字形索引
ASCII 先经 word_4EC810 映射表重编码
```

字形内容为简体，但用 BIG5 编码索引。

## 3. 控制标签

文本流中的控制码影响渲染：

| 字节 | 标签 | 含义 |
| --- | --- | --- |
| 0x01 | FRESET | 重置字体 |
| 0x02 | FCOLOR | 颜色 |
| 0x04 | FSIZE | 字号 |
| 0x05 | FTYPE | 字体区段 |
| 0x14 | TEXT | 文本引用 |
| 0x15 | VARNUM | 数字变量 |
| 0x16 | VARTXT | 文本变量 |
| 0x1D | NAME | 角色名 |

## 4. 渲染函数

| 地址 | 函数 | 职责 |
| --- | --- | --- |
| `0x0044B384` | CharToGlyph | BIG5 -> 字形索引 |
| `0x0044B208` | DecodeRLE | 96x96 RLE 位图解码 |
| `0x0044E49C` | TextStep | 文本步进与渲染 |
| `0x0044F420` | ClearSurface | 清屏 |

## 5. 参考

- [`docs/tkt_editor/FONT9696逆向分析报告.md`](../tkt_editor/FONT9696逆向分析报告.md)
- [`docs/tkt_editor/控制标签体系.md`](../tkt_editor/控制标签体系.md)
