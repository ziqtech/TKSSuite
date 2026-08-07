# 运行时文本格式化引擎

> 覆盖 `sub_409C60` 对 TKT 文本流中控制码的运行时展开。

## 1. 职责

`sub_409C60` 读取一条 TKT 文本字节流，把动态宏展开为可渲染字符串：

```text
TKT 原始字节
  -> sub_4067E8(id) 取文本
  -> sub_409C60 展开 TEXT/VARNUM/VARTXT/NAME
  -> sub_44E49C 渲染
```

## 2. 控制码展开

| 字节 | 标签 | 运行时行为 |
| --- | --- | --- |
| 0x01 | FRESET | 保留并带 1 字节参数 |
| 0x02 | FCOLOR | 保留并带 1 字节参数 |
| 0x04 | FSIZE | 保留并带 1 字节参数 |
| 0x05 | FTYPE | 保留并带 1 字节参数 |
| 0x14 | TEXT | 展开为另一条 TKT 文本 |
| 0x15 | VARNUM | `word_755E80[var]` 转数字字符串 |
| 0x16 | VARTXT | `word_755E80[var]` 作为 TKT ID 查文本 |
| 0x1D | NAME | 1=主角姓 `unk_755B6C`，2=主角名 `unk_755B64` |
| 其它 | - | 报 `MakeText error` |

## 3. 主要调用者

| 函数 | 用途 |
| --- | --- |
| `sub_40A220` | 对话渲染 |
| `sub_40B05C` | 居中提示 |
| `sub_40B1B4` | 系统气泡 |
| `sub_40B710` | 菜单文本 |
| `sub_4128AC` | 结局文本 |
| `sub_41762C` | 队伍/角色界面 |
| `sub_4393A8` / `sub_439750` | 技能说明 |

## 4. 参考

- `decompile/409C60.c`
- [`docs/tkt_editor/控制标签体系.md`](../tkt_editor/控制标签体系.md)
- [`text_data_encoding.md`](text_data_encoding.md)
