"""共享字段撤销栈 — warpc changeset 栈 (warpc_table_mode) 的表单型泛化 (P3-4)。

数据格式与 warpc changeset 一脉相承::

    undo_stack: [(label, rec_index, [(field, old, new), …]), …]

:func:`FieldUndoMixin.field_diff` 的"逐字段快照比对"与
``ui_helpers.form_edits_pending`` 的"控件值 vs 记录"同源——这里比较的是
**应用前后**的记录字段 (含钳制后的真实写入值), 精确且不依赖控件解析。

宿主接入 (EditorMainWindow 子类, 四步)::

    class ItemEditorApp(FieldUndoMixin, EditorMainWindow):   # ① 混入
        def _init_data(self):
            ...
            self._init_undo()                                # ② 初始化
        def _on_load_success(...):
            ...
            self.clear_undo()                                # ③ 数据整体重载清栈
        # ④ _apply_edit 应用后: self.push_field_changes(diff, label)
        #    菜单挂 self.undo / self.redo (Ctrl+Z / Ctrl+Y)

撤销/重做回放 (:meth:`FieldUndoMixin._undo_apply` 默认实现) 写回记录字段
→ ``_apply_filter`` 刷新列表 → 若被改记录正是当前编辑对象则
``_populate_edit`` 重填表单; 宿主行为不同可覆盖 ``_undo_apply``。
"""
from __future__ import annotations

#: 撤销步数上限 (与 warpc changeset 栈一致)
UNDO_LIMIT = 100


class FieldUndoMixin:
    """字段级撤销/重做 mixin — 供表单型编辑器混入。"""

    def _init_undo(self) -> None:
        self._undo_stack: list = []
        self._redo_stack: list = []

    # ── 栈维护 ──
    def clear_undo(self) -> None:
        """数据整体重载 (加载/导入) 后调用: 旧变更集全部失效。"""
        if not hasattr(self, '_undo_stack'):
            self._init_undo()
            return
        self._undo_stack.clear()
        self._redo_stack.clear()

    def push_field_changes(self, rec_index: int, changes, label="编辑字段") -> None:
        """推入一个变更集; 空变更集忽略, 超限截断最旧, 清空重做栈。"""
        if not changes:
            return
        self._undo_stack.append((label, rec_index, list(changes)))
        del self._undo_stack[:-UNDO_LIMIT]
        self._redo_stack.clear()

    @staticmethod
    def field_diff(before: dict, after: dict, keys) -> list:
        """逐字段比对两份字段快照 → [(field, old, new), …]。

        before/after 取同一记录应用前后的字段值 (建议直接对记录本身取
        before, after 传记录), 与 form_edits_pending 的比对口径一致。
        """
        return [(fn, before.get(fn, 0), after.get(fn, 0))
                for fn in keys if before.get(fn, 0) != after.get(fn, 0)]

    # ── 撤销 / 重做 ──
    def can_undo(self) -> bool:
        return bool(getattr(self, '_undo_stack', None))

    def can_redo(self) -> bool:
        return bool(getattr(self, '_redo_stack', None))

    def undo(self) -> None:
        if not self._undo_stack:
            self._undo_notify("撤销: 没有可撤销的修改")
            return
        label, rec_index, changes = self._undo_stack.pop()
        n = self._undo_apply(rec_index, changes, use_old=True)
        self._redo_stack.append((label, rec_index, changes))
        self._undo_notify(f"已撤销: {label} ({n} 处)")

    def redo(self) -> None:
        if not self._redo_stack:
            self._undo_notify("重做: 没有可重做的修改")
            return
        label, rec_index, changes = self._redo_stack.pop()
        n = self._undo_apply(rec_index, changes, use_old=False)
        self._undo_stack.append((label, rec_index, changes))
        self._undo_notify(f"已重做: {label} ({n} 处)")

    # ── 回放 (默认实现; 宿主可覆盖) ──
    def _record_by_index(self, idx: int):
        """按记录 index 字段定位 (records 通常与 index 对齐, 兜底线性查找)。"""
        recs = getattr(self, 'records', [])
        if 0 <= idx < len(recs) and recs[idx].get('index', idx) == idx:
            return recs[idx]
        for r in recs:
            if r.get('index') == idx:
                return r
        return None

    def _undo_apply(self, rec_index: int, changes, use_old: bool) -> int:
        rec = self._record_by_index(rec_index)
        if rec is None:
            return 0  # 记录已被删除/重载, 跳过 (与 warpc 回放策略一致)
        for fn, old, new in changes:
            rec[fn] = old if use_old else new
        self._dirty = True
        if hasattr(self, '_apply_filter'):
            self._apply_filter()
        # 被回放的记录正是当前编辑对象 → 重填表单保持一致
        cur = getattr(self, '_editing_idx', None)
        if (isinstance(cur, int) and 0 <= cur < len(getattr(self, 'records', []))
                and self.records[cur] is rec and hasattr(self, '_populate_edit')):
            self._populate_edit(rec)
        return len(changes)

    def _undo_notify(self, text: str) -> None:
        """状态提示 — 兼容三个编辑器各异的状态栏属性名。"""
        for name in ('status_var', 'status_label', 'lbl_status'):
            w = getattr(self, name, None)
            if w is not None:
                w.setText(text)
                return
