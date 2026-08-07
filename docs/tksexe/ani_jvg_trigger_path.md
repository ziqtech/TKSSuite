# Ani.JVG 实际触发路径

> 结论：`Ani.JVG` 是地图/实体动画资源，供 `TKMat` type 20 物件与 type 200 角色行走动画使用；它不参与 TKAct 战斗槽位渲染。

## 1. 加载

```text
sub_411624
  -> sub_453BD0(dword_755AFC, "Ani.jvg")
  -> dword_755AD0 = dword_755AFC
```

## 2. 实体动画初始化（sub_405CBC）

场景实体列表重建时：

```text
type 20 OBJECT:
  entity[65] = sub_45410C(dword_755AFC, entity[64])   # Ani 块偏移
  entity[16] = sub_4540E8(dword_755AFC, entity[64])   # 总帧数
  entity[14] = entity[17] + entity[65]                # 当前显示帧

type 200 CHARACTER 且 entity[70] == 1（行走态）:
  同样使用 Ani.JVG 初始化动画帧
```

## 3. 行走/待机切换（sub_40CB90）

脚本 `Switch(entity, mode)`：

```text
mode=1（行走）
  entity[9] = 4
  entity[70] = 1
  entity[16] = sub_4540E8(dword_755AFC, entity[64])
  entity[14] = entity[17] + entity[65]

mode=0（待机）
  entity[9] = 1
  entity[70] = 0
  entity[16] = sub_4540E8(dword_755AF0, entity[51]) / entity[53]
  按 4/8 方向计算 entity[14]
```

## 4. 其它引用

- `sub_411308` 会把场景 mask 数据写到 `dword_755AFC` 表面字段，说明该 JVG 对象同时承担场景动画表面。
- `sub_405CBC` 开始时释放 `dword_755AFC` 的精灵缓存。

## 5. 与 TKAct 的关系

```text
TKAct slot type=1 -> Aa.JVG
TKAct slot type=2/3/4/5 -> Af.JVG
地图实体行走/物件动画 -> Ani.JVG
地图角色基础立绘 -> Cha.JVG
```

## 6. 参考

- `decompile/405CBC.c`、`decompile/40CB90.c`、`decompile/411624.c`
- [`tkact_record_structure.md`](tkact_record_structure.md)
- [`animation_sprite_binding.md`](animation_sprite_binding.md)
