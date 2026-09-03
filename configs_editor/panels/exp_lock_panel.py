"""
ExpLockPanel — 战斗经验锁定配置面板
编辑 exp_lock.json 中的 lock_slots (长度6的布尔数组，对应战斗队伍槽位0-5)。
勾选某槽 = 锁定该槽队员的战斗经验，胜利结算时不获经验、不升级。
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QLabel, QPushButton, QWidget
)

from .base_panel import ConfigPanelBase

SLOT_COUNT = 6


class ExpLockPanel(ConfigPanelBase):
    config_name = "exp_lock"
    tab_label = "战斗经验锁定"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 说明 ──
        hint = QLabel(
            "锁定后，被勾选槽位的队员在战斗胜利结算时不获得战斗经验、也不会升级。\n"
            "用于均衡培养队伍（把已练满的角色放入锁定槽即可压级）。\n"
            "锁定按“战斗队伍槽位 0-5”生效（随队形位置，而非角色）；技能点(JP)不受影响。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("ExpLockHint")
        layout.addWidget(hint)

        # ── 槽位勾选 ──
        slot_group = QGroupBox("锁定槽位（勾选=锁定该槽经验）")
        slot_group.setProperty("configEditorSurface", True)
        slot_layout = QVBoxLayout(slot_group)
        slot_layout.setSpacing(6)
        for i in range(SLOT_COUNT):
            chk = QCheckBox(f"槽位 {i}")
            chk.setToolTip(f"锁定战斗队伍第 {i} 个槽位队员的战斗经验（不获经验、不升级）")
            chk.toggled.connect(self._on_changed)
            self._checks.append(chk)
            slot_layout.addWidget(chk)
        layout.addWidget(slot_group)

        # ── 快捷 + 重置按钮 ──
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        btn_all = QPushButton("全部锁定")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_layout.addWidget(btn_all)

        btn_none = QPushButton("全部解锁")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(btn_none)

        btn_reset = QPushButton("重置默认")
        btn_reset.setToolTip("恢复到本次加载时的原始值。若需恢复出厂默认，请删除 JSON 文件后重启编辑器。")
        btn_reset.clicked.connect(self.reset)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()
        layout.addWidget(btn_row)

        layout.addStretch()

    def _set_all(self, checked: bool):
        """批量设置所有槽位勾选状态（触发一次 dirty）。"""
        changed = False
        for chk in self._checks:
            if chk.isChecked() != checked:
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
                changed = True
        if changed:
            self._mark_dirty()

    def _on_changed(self, _checked=False):
        self._mark_dirty()

    # ── ConfigPanelBase 实现 ──

    def _populate_ui(self, data: dict):
        slots = data.get("lock_slots", [])
        for i, chk in enumerate(self._checks):
            val = bool(slots[i]) if i < len(slots) else False
            chk.blockSignals(True)
            chk.setChecked(val)
            chk.blockSignals(False)

    def _collect_ui(self) -> dict:
        return {"lock_slots": [chk.isChecked() for chk in self._checks]}
