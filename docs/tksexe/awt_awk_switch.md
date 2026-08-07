# Awt / Awk 切换点

> 结论：待机走 `sub_43709C` + `dword_9DF442`（Awt 帧），移动走 `sub_43DE90` 直接渲染 `dword_95192C`（Awk 帧），不依赖预拷贝。

## 1. 运行时数据

| 变量 | 含义 |
| --- | --- |
| `dword_9DF43A[5*i]` | Awt 基准精灵 |
| `dword_9DF43E[5*i]` | Awk 基准精灵 |
| `dword_9DF442[5*i]` | 当前动画帧（待机时指向 Awt 序列） |
| `byte_9DF446[20*i]` | 当前方向 0-3 |
| `byte_9DF447[20*i]` | Awt 每方向帧数 |
| `byte_9DF44B[20*i]` | Awk 每方向帧数 |
| `word_9E095A` | 行走步进计数器 |

## 2. 待机路径

`sub_43709C` 每战斗 tick 推进 `dword_9DF442`：

```text
每 2 个子 tick 前进一帧
播完 2 * frames_per_dir 后：
  当前单位暂停 3 tick，其它单位随机暂停 0-20 tick
  复位到 Awt_base + frames_per_dir * direction
```

## 3. 移动路径

`sub_43DE90` 执行单位移动，并对移动中的单位直接绘制 Awk：

```text
sprite = word_9E095A + dword_9DF43E[unit]
       + byte_9DF44B[unit] * byte_9DF446[unit]

sub_4544EC / sub_459168(dword_95192C, x, y, sprite, ...)

if ++word_9E095A >= byte_9DF44B[unit]:
    word_9E095A = 0
```

静止单位仍绘制 `dword_951928` + `dword_9DF442[unit]`。

## 4. 方向切换

`sub_449F84` 在移动开始时被 `sub_43DE90` 调用：

```text
frame_offset = current - (Awt_base + frames_per_dir * old_dir)
new_current  = frame_offset + Awt_base + frames_per_dir * new_dir
```

保持待机帧相位，使转向连续。

## 5. 与 sub_4434BC 的关系

`sub_4434BC` 中固定使用 `dword_951928` 绘制主体，是因为它是战斗动作渲染路径；单位移动由独立的 `sub_43DE90` 处理，并从 `dword_95192C` 直接取帧。

## 6. 参考

- `decompile/43DE90.c`、`decompile/43709C.c`、`decompile/449F84.c`
- [`逆向工作区/docs/05_角色与动画系统/Awt_Awk动画与WarPC关联.md`](../../../逆向工作区/docs/05_角色与动画系统/Awt_Awk动画与WarPC关联.md)
