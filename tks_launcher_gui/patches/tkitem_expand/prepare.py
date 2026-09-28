# -*- coding: utf-8 -*-
"""tkitem_expand 组合补丁准备脚本：展开为"物品表扩容 + 战斗图标取帧修正"两个操作。

- `data_expand.json`：TKItem 数据段扩容（自身按 TKItem.dat 实际大小门控）。
- `icon.json`：战斗初始化把 Mu2.JVG 对象重载为 Mu.JVG 并前移帧表 130 帧，
  使战斗内物品图标与菜单/商店同源（详细逆向依据见 icon_cave.py）。

是否注入 icon 操作由**数据**决定：战斗内绘制用 `if (图标值 < Mu2 总帧数)` 判越界
（`sub_4544EC` 的 `a5 < a2[6]`，a2[6] = 载入器写进 obj+0x18 的 JVG 头 +0x10 值），
因此只有物品表实际出现「图标值 ≥ Mu2 总帧数」的条目时图标才会空白，此时才注入 cave。

由此两条路线都成立：
- 只在 Mu.JVG 追加扩展图标（图标值 ≥ 144）→ 原版 Mu2(107 帧) 必然越界 → 注入 cave；
- 或者把扩展图标同时补进 Mu2.JVG（帧号 = 图标值）→ 取值本身合法 → 不注入, 纯数据方案。
Mu.JVG 缺失时跳过 (cave 无源可载)。
"""
from __future__ import annotations

# 原版 Mu2.JVG 总帧数：帧 0..75 = 物品图标 (Mu 帧 130..205)，76..106 = 状态图标 1..31。
MU2_VANILLA_FRAMES = 107
TKITEM_RECORD = 64
ICON_FIELD_OFFSET = 8

_ICON_OP_FILE = "icon.json"
_DATA_OP_FILE = "data_expand.json"


def _mu2_frames(context) -> int:
    """本目录 Mu2.JVG 的总帧数（= 战斗初始化写进 obj+0x18 的越界阈值）。

    取 JVG 头 +0x10 的 dword（与逐块帧数之和一致，实测 107/274/764 三份文件均吻合）。
    Mu2.JVG 缺失/非 JVG 时按原版 107 处理：原版战斗本就依赖该文件，缺失时图标
    另有问题，但门控判据仍应与原版一致。
    """
    path = context.data_path("Mu2.JVG")
    if not path:
        return MU2_VANILLA_FRAMES
    try:
        with open(path, "rb") as stream:
            head = stream.read(0x14)
    except OSError:
        return MU2_VANILLA_FRAMES
    if len(head) < 0x14 or head[:4] != b"@JVG":
        return MU2_VANILLA_FRAMES
    frames = int.from_bytes(head[0x10:0x14], "little")
    return frames or MU2_VANILLA_FRAMES


def _battle_frame_overflow(context) -> bool:
    """物品表中是否存在"战斗内取帧必然越界"的图标值。

    读取/解压失败时保守返回 False (与 TKItem.dat 缺失同路), 不阻断其它操作 ——
    数据文件本身的问题由 data_expand 操作自行处理并单独报错。
    负值 (int16 有符号读, 如空槽 -1) 不构成越界。
    """
    if not context.data_path("TKItem.dat"):
        return False
    try:
        data = context.read_data("TKItem.dat", compressed=True)
    except Exception:
        return False
    if len(data) < TKITEM_RECORD:
        return False
    limit = _mu2_frames(context)
    for offset in range(ICON_FIELD_OFFSET, len(data) - 1, TKITEM_RECORD):
        icon = int.from_bytes(data[offset:offset + 2], "little", signed=True)
        if icon >= limit:
            return True
    return False


def prepare(context):
    if not context.enabled:
        return []
    operations = [context.read_json(_DATA_OP_FILE)]
    if _battle_frame_overflow(context) and context.data_path("Mu.JVG"):
        operations.append(context.read_json(_ICON_OP_FILE))
    return operations
