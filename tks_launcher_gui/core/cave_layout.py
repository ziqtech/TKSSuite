"""Cave 内存布局器 (Phase 6)

Phase 6 引入: 提供 `CaveLayout` 类, 让 .tkspatch 作者可以选择:
- **旧模式** (`autolayout_cave: false`): 继续硬编码 `cave_offset` / `random_*_offset`
- **新模式** (默认 `autolayout_cave: true`): 不写偏移, 由启动器按 16 字节对齐顺序分配

收益:
- 新作者无需关心 cave 在 1024/2048 字节内的布局, 不撞墙
- 旧 .tkspatch 完全向后兼容 (offset 字段保留, 默认走硬编码)
- 硬编码冲突被显式捕获 (CaveLayoutError)

决策: **兼容硬编码 + 新增自动模式** (Phase 6 spec §7.1)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class CaveLayoutError(Exception):
    """Cave 布局错误 (越界、冲突、负偏移)。"""


@dataclass
class CaveSlot:
    """单个 cave 槽位, 记录谁占用了 cave 中的哪一段。"""
    owner_id: str       # patch.id (用于日志)
    purpose: str        # "main" | "random_table" | "random_cave" | "random2_cave"
    size: int           # 占用字节数
    offset: int         # 在 cave 区内的偏移 (相对 cave_addr)

    def end(self) -> int:
        return self.offset + self.size


@dataclass
class CaveLayout:
    """Cave 内存布局管理器。

    使用方式:
        layout = CaveLayout(base_addr=cave_addr, budget=cave_total_size)

        # 自动分配 (新模式):
        slot = layout.allocate("portrait_cave1", "main", size=52)

        # 兼容硬编码 (旧模式):
        slot = layout.allocate("awk_sprite_cave", "main", size=58, force_offset=0)

        # 查看布局:
        for slot in layout.slots:
            print(f"{slot.owner_id}: 0x{slot.offset:X} + {slot.size}")
    """
    base_addr: int
    budget: int
    slots: List[CaveSlot] = field(default_factory=list)
    _used_end: int = 0     # 自动分配游标 (始终 16 字节对齐)
    _occupied: Dict[int, str] = field(default_factory=dict)  # offset -> owner_id, 用于冲突检测

    def allocate(self, owner_id: str, purpose: str, size: int,
                 force_offset: Optional[int] = None,
                 alignment: int = 16) -> CaveSlot:
        """分配一个 cave 槽位。

        Args:
            owner_id:   补丁 ID, 用于日志与冲突溯源
            purpose:    用途标识 ("main" / "random_table" / "random_cave" / "random2_cave")
            size:       占用字节数 (必须 > 0)
            force_offset: 硬编码偏移 (旧模式); None = 自动分配
            alignment:  自动分配时的对齐边界 (默认 16, 与 cave 内 E8 rel32 调用兼容)

        Returns:
            CaveSlot 实例, 含最终 offset。

        Raises:
            CaveLayoutError: 越界 / 硬编码冲突 / 负值参数
        """
        if size <= 0:
            raise CaveLayoutError(
                f"{owner_id}/{purpose}: size 必须 > 0, 得到 {size}"
            )

        if force_offset is not None:
            # ── 硬编码模式 (兼容旧 .tkspatch) ──
            if force_offset < 0:
                raise CaveLayoutError(
                    f"{owner_id}/{purpose}: 硬编码偏移 0x{force_offset:X} 为负"
                )
            offset = force_offset
            if offset + size > self.budget:
                raise CaveLayoutError(
                    f"{owner_id}/{purpose}: 硬编码偏移 0x{offset:X}+{size}={offset+size} "
                    f"超出 budget={self.budget}"
                )
            # 硬编码冲突检测: 同一 offset 已被其他 (硬编码或自动) 槽位占用
            for existing in self.slots:
                if existing.offset < offset + size and existing.end() > offset:
                    raise CaveLayoutError(
                        f"{owner_id}/{purpose}: 硬编码偏移 0x{offset:X}+{size} "
                        f"与 {existing.owner_id}/{existing.purpose} @0x{existing.offset:X}+{existing.size} 重叠"
                    )
        else:
            # ── 自动分配模式 (新模式) ──
            # 计算起点: 必须超过所有硬编码占用区间 (避免与硬编码区重叠)
            # 同时考虑自动分配游标 _used_end
            candidate = self._used_end
            for existing in self.slots:
                # 如果是自动分配, _used_end 已经处理; 跳过
                if existing.offset + existing.size <= candidate:
                    continue
                # 硬编码占用: 需要 candidate 跳到 end 之后
                if existing.end() > candidate:
                    candidate = existing.end()
            offset = (candidate + alignment - 1) & ~(alignment - 1)
            if offset + size > self.budget:
                raise CaveLayoutError(
                    f"{owner_id}/{purpose}: 自动分配失败, 需要 0x{offset:X}+{size}, "
                    f"budget={self.budget}, 已用={self._used_end}"
                )
            self._used_end = offset + size

        slot = CaveSlot(owner_id=owner_id, purpose=purpose,
                        size=size, offset=offset)
        self.slots.append(slot)
        return slot

    def used_bytes(self) -> int:
        """已使用的字节数 (含对齐空隙)。"""
        return self._used_end

    def summary(self) -> str:
        """返回布局摘要 (用于启动器日志)。"""
        lines = [f"Cave 布局: budget={self.budget}, 已用={self._used_end} "
                 f"({100 * self._used_end / max(1, self.budget):.1f}%)"]
        for slot in self.slots:
            lines.append(f"  0x{slot.offset:04X}+{slot.size:>3} "
                         f"{slot.owner_id}/{slot.purpose}")
        return "\n".join(lines)
