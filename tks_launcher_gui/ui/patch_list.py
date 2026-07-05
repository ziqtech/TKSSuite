"""补丁勾选列表 — 分必选/可选两组, 各自独立滚动, 从 PatchDef 列表动态生成 QCheckBox"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QCheckBox,
                                QScrollArea, QLabel, QSplitter)
from PySide6.QtCore import Qt
from editor_utils.dock_components import DockHeader
from core.config_loader import PatchDef

# 可选补丁区固定默认高度（不再按条数动态计算）；MOD 详情预览区同步使用此值
OPTIONAL_PATCH_DEFAULT_HEIGHT = 320


class PatchListWidget(QWidget):
    """两组补丁各自独立滚动: DockHeader 固定, 下方 QScrollArea 仅滚动勾选列表
    必选/可选两组之间为可拖动分割条, 高度可自由调整"""

    def __init__(self, patches: list[PatchDef], parent=None):
        super().__init__(parent)

        self._checkboxes: dict[str, QCheckBox] = {}

        required = [p for p in patches if not p.optional]
        optional = [p for p in patches if p.optional]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        req_section = self._build_section(
            f"必选补丁 ({len(required)})",
            [(p, False) for p in required])
        # 必选区默认约显示 10 条高度, 少于此数时不铺满、不出现多余滚动条
        req_section.setMinimumHeight(48 + min(len(required), 10) * 22)
        # 可选补丁通常较少, 按条数给默认高度; 少量时不显示滚动条
        opt_section = self._build_section(
            f"可选补丁 ({len(optional)})",
            [(p, True) for p in optional],
            scrollable=len(optional) > 6)
        opt_section.setMinimumHeight(40)

        # 必选/可选之间用可拖动分割条, 高度可自由调整
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(4)
        split.setChildrenCollapsible(False)
        split.addWidget(req_section)
        split.addWidget(opt_section)
        # 必选区可伸缩，可选区固定高度（与 MOD 详情预览区保持等高）
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        # 默认高度: 必选约 10 条, 可选为固定值
        req_h = 48 + min(len(required), 10) * 22
        opt_h = OPTIONAL_PATCH_DEFAULT_HEIGHT
        self._opt_default_height = opt_h
        split.setSizes([req_h, opt_h])
        outer.addWidget(split)

    @property
    def optional_default_height(self) -> int:
        """可选补丁区的固定默认高度（供其他面板同步高度参考）。"""
        return OPTIONAL_PATCH_DEFAULT_HEIGHT

    def _build_section(self, title: str, items: list[tuple[PatchDef, bool]],
                       scrollable: bool = True) -> QWidget:
        """构建一个分组: DockHeader(固定) + QScrollArea(独立滚动勾选项)

        scrollable=False 时关闭竖直滚动条 (少量条目直接铺开, 不出现滚动条)
        """
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(DockHeader(title))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if not scrollable:
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("patchListContent")
        inner = QVBoxLayout(content)
        inner.setContentsMargins(8, 8, 8, 8)
        inner.setSpacing(2)

        if items:
            for p, enabled in items:
                inner.addWidget(self._make_checkbox(p, enabled=enabled))
        else:
            hint = QLabel("  (无)")
            hint.setObjectName("hintLabel")
            inner.addWidget(hint)

        inner.addStretch()
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)
        return section

    def _make_checkbox(self, p: PatchDef, enabled: bool) -> QCheckBox:
        cb = QCheckBox(f"[{p.id}] {p.desc}")
        cb.setChecked(True)
        cb.setEnabled(enabled)
        cb.setToolTip(f"类型: {p.type}\n模式: {p.pattern}")
        if not enabled:
            # 必选补丁：复选框保持禁用外观，文字颜色由主题 QSS 中 #requiredPatch 规则控制
            cb.setObjectName("requiredPatch")
        self._checkboxes[p.id] = cb
        return cb

    def get_selected_patches(self) -> set[str]:
        return {pid for pid, cb in self._checkboxes.items() if cb.isChecked()}

    def select_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def deselect_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(False)
