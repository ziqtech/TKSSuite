"""补丁勾选列表 — 分必选/可选两组, 从 PatchDef 列表动态生成 QCheckBox"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QCheckBox,
                                QScrollArea, QLabel)
from PySide6.QtCore import Qt
from core.config_loader import PatchDef

_SECTION_LABEL = "font-weight: bold; padding: 8px 0 4px 0;"


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

        required = [p for p in patches if not p.optional]
        optional = [p for p in patches if p.optional]

        self._checkboxes: dict[str, QCheckBox] = {}

        # --- 必选补丁 ---
        label_r = QLabel(f"必选补丁 ({len(required)})")
        label_r.setStyleSheet(_SECTION_LABEL)
        self._layout.addWidget(label_r)

        for p in required:
            cb = self._make_checkbox(p, enabled=False)
            self._layout.addWidget(cb)

        # --- 可选补丁 ---
        label_o = QLabel(f"可选补丁 ({len(optional)})")
        label_o.setStyleSheet(_SECTION_LABEL)
        self._layout.addWidget(label_o)

        if optional:
            for p in optional:
                cb = self._make_checkbox(p, enabled=True)
                self._layout.addWidget(cb)
        else:
            hint = QLabel("  (无)")
            hint.setStyleSheet("color: #666; padding-left: 4px;")
            self._layout.addWidget(hint)

        self._layout.addStretch()
        self.setWidget(content)

    def _make_checkbox(self, p: PatchDef, enabled: bool) -> QCheckBox:
        cb = QCheckBox(f"[{p.id}] {p.desc}")
        cb.setChecked(True)
        cb.setEnabled(enabled)
        cb.setToolTip(f"类型: {p.type}\n模式: {p.pattern}")
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
