# TKSkill 描述文本 ID 规则

> 结论：技能描述 TKT ID 由 `TKSkill.field[1]` 直接提供；当前数据中它恰好等于 `field[0] + 400`，但引擎并不做加法。

## 1. 反编译证据

TKSkill 数据基址为 `word_7861CA`：

```text
field[0] = word_7861CA[47 * skill]   # 技能名 TKT ID
field[1] = word_7861CC[47 * skill]   # 技能描述 TKT ID
```

战斗菜单/详情显示函数使用 `field[1]` 查询描述：

- `sub_4393A8`：`sub_4067E8(word_7861CC[47 * skill])`
- `sub_439750`：`sub_4067E8(word_7861CC[47 * skill])`

未发现任何代码对 `field[0]` 做 `+400` 后再查询。

## 2. 数据验证

对 `TKSkill.dat` 全部 350 条记录验证：

| 结果 | 数量 |
| --- | --- |
| `field[1] == field[0] + 400` | 344 |
| 空槽（field[0]=0, field[1]=0） | 6 |
| 不一致 | 0 |

所以“`+400`”是当前数据的制作惯例，不是引擎规则。

## 3. 编辑建议

- 修改技能名称后，应同时显式设置 `field[1]` 为新的描述 TKT ID。
- 编辑器不应把 `field[1]` 当作只读派生字段。
- 若新增技能，请直接填写独立描述 ID，避免依赖 `+400` 假设。

## 4. 参考

- `decompile/4393A8.c`、`decompile/439750.c`
- [`逆向工作区/docs/06_物品技能商店条件/TKSkill技能配置与引用关系.md`](../../../逆向工作区/docs/06_物品技能商店条件/TKSkill技能配置与引用关系.md)
