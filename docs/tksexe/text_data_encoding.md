# TKD.dat / TKT.dat 文本数据编码与双向转换

> 分析对象：`sub_401E88`（TKT 加载/生成）、`sub_4019D0`（控制标签编码）、TKD 整文件 XOR 解密。
> 配套工具：`逆向工作区/tkt_tkd_roundtrip.py`。

## 1. TKT.dat

### 1.1 文件结构

```text
[4B total_size]
[4B record_count]
[total_size 字节 XOR 0xFF 数据区]
```

XOR 后数据区：

```text
[4B × record_count]  ID 表（int32）
[4B × record_count]  偏移表（uint32，指向文本区）
[变长]               文本区
```

文本条目以 `0x00` 结束，多行之间以 `0x1E` 分隔。

### 1.2 控制标签

| 标签 | 字节 | 数据 | 范围 |
| --- | --- | --- | --- |
| `FRESET` | 0x01 | 1B | 1-4 |
| `FCOLOR` | 0x02 | 1B | 1-32 |
| `FSIZE` | 0x04 | 1B | 12-48 |
| `FTYPE` | 0x05 | 1B | 1-8 |
| `TEXT` | 0x14 | 2B lo+hi | 1-32767 |
| `VARNUM` | 0x15 | 1B | 1-255 |
| `VARTXT` | 0x16 | 1B | 1-255 |
| `NAME` | 0x1D | 1B | 1-2 |

未定义控制字节以 `<RAW,0xNN>` 保留；字面 `<` 写成 `<<` 以避免与标签冲突。

## 2. TKD.dat

TKD 是脚本源文件，无头结构：

```text
文件全部字节 XOR 0xFF -> Big5/CP950 文本
```

解密后包含 `DEFINE` 块、`{...}`、`;` 注释和命令文本。

加载证据：`TForm1_FormCreate`（`4030F0.c`）优先尝试 `TKDef.txt`，若存在则读取并 XOR 后写回 `TKD.dat`；否则直接读取 `TKD.dat` 并 XOR 到脚本字符串列表，再由 `sub_402BE8` 提取 DEFINE。

## 3. 双向转换工具

脚本：[`逆向工作区/tkt_tkd_roundtrip.py`](../../../逆向工作区/逆向工作区/tkt_tkd_roundtrip.py)

```text
python tkt_tkd_roundtrip.py decode-tkt TKT.dat -o tkt.json
python tkt_tkd_roundtrip.py encode-tkt tkt.json -o TKT.new.dat

python tkt_tkd_roundtrip.py decode-tkd TKD.dat -o tkd.txt
python tkt_tkd_roundtrip.py encode-tkd tkd.txt -o TKD.new.dat
```

编辑流程：

1. 解码 TKT 到 JSON，`text` 字段可直接修改，控制码用 `<TAG,n>` 表达。
2. 回写时自动做 Big5 编码、标签压缩、偏移表重建、XOR 加密。
3. TKD 解码为纯文本后修改，回写时整文件 Big5 编码 + XOR。

## 4. 验证结果

真实文件往返测试：

- `TKT.dat`：14438 条目导出 -> 回写 -> 再导出，ID 与文本逐条一致。
- `TKD.dat`：解密 -> 回写 -> 再解密，文本逐字符一致。

## 5. 关键函数

| 地址 | 函数 | 职责 |
| --- | --- | --- |
| `0x00401E88` | `sub_401E88` | 读取 TKT.dat，或从 TKTalk.txt 生成 |
| `0x004019D0` | `sub_4019D0` | `<TAG,n>` 到控制字节的编码 |
| `0x004067E8` | `sub_4067E8` | 按 ID 线性查询文本 |

## 6. 参考

- 解码器：[`逆向工作区/tkt_decoder.py`](../../../逆向工作区/逆向工作区/tkt_decoder.py)
- 文本 ID 分段与控制标签：[`text_and_save_system.md`](text_and_save_system.md)
