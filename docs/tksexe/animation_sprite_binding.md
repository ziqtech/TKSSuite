# 动画与精灵绑定模块

> 覆盖 `TKAct.dat`、`Cha/Ani/Aa/Af/Awk/Awt/Mu/Fa` 等 JVG 的加载与绑定关系。
> 修正依据：[`逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md`](../../../逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md)。

## 1. TKAct.dat

| 属性 | 值 |
| --- | --- |
| 格式 | 原始二进制 |
| 大小 | 509600 字节 |
| 记录 | 784 字节 × 650 条 |
| 加载 | `sub_411624` -> `sub_452544` |
| 消费 | `sub_4434BC` 动画渲染 |

## 2. 图层类型

| layer_type | 行为 |
| --- | --- |
| 0 | 跳过 |
| 1 | 主段渲染，使用 **Aa.jvg** |
| 2 | 主段渲染，使用 **Af.jvg** |
| 3 | 延迟段渲染，使用 **Af.jvg** |
| 4 | 坐标锚点，不渲染 |
| 5 | 结束标记，不渲染 |

## 3. JVG 绑定关系

| 文件 | 用途 | 加载入口 |
| --- | --- | --- |
| `Cha.jvg` | 地图角色基础行走图 | `sub_411624` -> `dword_755AF0` |
| `Ani.jvg` | 通用/剧情/UI 动画 | `sub_411624` -> `dword_755AFC` |
| `Aa.jvg` | TKAct 主角动作库 | `sub_42FEE0` -> `dword_951924` |
| `Af.jvg` | TKAct 特效/物件库 | `sub_42FEE0` -> `dword_951930` |
| `Awt.jvg` | 战斗待机动画 | `sub_42FEE0` |
| `Awk.jvg` | 战斗行走动画 | `sub_42FEE0` |
| `Mu.jvg` | 菜单 UI / 物品图标 | 菜单初始化 |
| `Fa.jvg` | 角色头像 | `sub_42FEE0` |

## 4. 重要结论

- TKAct 图层不消费 `Cha.jvg`/`Ani.jvg`；type=1 走 Aa，其它走 Af。
- `Cha.jvg` 基础行走图由 `sub_4434BC` 直接按角色 base block 绘制，绕过 TKAct。
- 方向编码为 1-8，实际帧数取决于 `direction_count`（4/8）。
- 武器/战斗动画由 WarPC 字段与 `Awk/Awt` 关联，非 TKAct 主链。

## 5. 参考

- [`tkact_record_structure.md`](tkact_record_structure.md)
- [`逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md`](../../../逆向工作区/docs/05_角色与动画系统/TKAct实际JVG绑定修正.md)
- [`逆向工作区/docs/05_角色与动画系统/Awt_Awk动画与WarPC关联.md`](../../../逆向工作区/docs/05_角色与动画系统/Awt_Awk动画与WarPC关联.md)
- [`逆向工作区/docs/05_角色与动画系统/角色动画系统分析.md`](../../../逆向工作区/docs/05_角色与动画系统/角色动画系统分析.md)
