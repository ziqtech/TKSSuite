"""补丁勾选列表 — 从 PatchDef 列表动态生成 QCheckBox"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QCheckBox,
                                QScrollArea, QLabel)
from PySide6.QtCore import Qt
from core.config_loader import PatchDef


class PatchListWidget(QScrollArea):
    def __init__(self, patches: list[PatchDef], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("patchListContent")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(2)

        title = QLabel(f"可用补丁 ({len(patches)})")
        title.setStyleSheet("font-weight: bold; padding-bottom: 4px;")
        self._layout.addWidget(title)

        self._checkboxes: dict[str, QCheckBox] = {}
        for p in patches:
            cb = QCheckBox(f"[{p.id}] {p.desc}")
            cb.setChecked(True)
            cb.setEnabled(p.optional)
            cb.setToolTip(f"类型: {p.type}\n模式: {p.pattern}")
            self._layout.addWidget(cb)
            self._checkboxes[p.id] = cb

        self._layout.addStretch()
        self.setWidget(content)

    def get_selected_patches(self) -> set[str]:
        return {pid for pid, cb in self._checkboxes.items() if cb.isChecked()}

    def select_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def deselect_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(False)
