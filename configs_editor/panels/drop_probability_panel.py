"""
DropProbabilityPanel — 物品掉落概率配置面板
编辑 drop_probability.json 中的 3 个百分比值。
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSlider, QSpinBox,
    QLabel, QPushButton, QWidget
)
from PySide6.QtCore import Qt

from .base_panel import ConfigPanelBase


class DropProbabilityPanel(ConfigPanelBase):
    config_name = "drop_probability"
    tab_label = "掉落概率"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 概率设置 ──
        prob_group = QGroupBox("概率设置")
        prob_group.setProperty("configEditorSurface", True)
        prob_layout = QFormLayout(prob_group)

        # 常规槽 (只读)
        self._regular_label = QLabel("100%")
        self._regular_label.setObjectName("RegularPctLabel")
        self._regular_label.setToolTip("原版无随机检查点，常规槽始终100%掉落")
        regular_row = QWidget()
        rl = QHBoxLayout(regular_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._regular_label)
        rl.addWidget(QLabel("只读 — 原版始终100%"))
        rl.addStretch()
        prob_layout.addRow("常规槽:", regular_row)

        # 普通槽
        self._normal_spin, self._normal_slider, self._normal_lbl = self._make_spin_slider(
            prob_layout, "普通槽",
            "原版20% (rand(1000)<200)。补丁修改 cmp ax, 0xC8 为 pct*10")

        # 稀有槽
        self._rare_spin, self._rare_slider, self._rare_lbl = self._make_spin_slider(
            prob_layout, "稀有槽",
            "原版5% (rand(1000)<50)。补丁修改 cmp ax, 0x32 为 pct*10")

        layout.addWidget(prob_group)

        # ── 按钮 ──
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_reset = QPushButton("🔄 重置默认")
        btn_reset.setToolTip("恢复到本次加载时的原始值。若需恢复出厂默认，请删除 JSON 文件后重启编辑器。")
        btn_reset.clicked.connect(self.reset)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        layout.addWidget(btn_row)

        layout.addStretch()

    def _make_spin_slider(self, form_layout, label_text, tooltip):
        """创建 SpinBox + Slider 联动控件行。
        返回 (spinbox, slider, prob_lbl) 三元组。
        滑块步长=5 (拖动时自动对齐到最近的 5 的倍数)。
        """
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)

        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setSingleStep(5)
        spin.setSuffix("%")
        spin.setFixedWidth(90)

        # 联动
        def on_slider(val):
            # 对齐到最近的 5 的倍数（步长=5）
            snapped = round(val / 5) * 5
            if snapped != val:
                slider.blockSignals(True)
                slider.setValue(snapped)
                slider.blockSignals(False)
            spin.blockSignals(True)
            spin.setValue(snapped)
            spin.blockSignals(False)
            update_prob_label(snapped)

        def on_spin(val):
            # 对齐到最近的 5 的倍数
            snapped = round(val / 5) * 5
            if snapped != val:
                spin.blockSignals(True)
                spin.setValue(snapped)
                spin.blockSignals(False)
                update_prob_label(snapped)
            slider.blockSignals(True)
            slider.setValue(snapped)
            slider.blockSignals(False)
            self._on_changed()

        slider.valueChanged.connect(on_slider)
        slider.sliderReleased.connect(self._on_changed)
        spin.valueChanged.connect(on_spin)

        h.addWidget(slider, 1)
        h.addWidget(spin)

        row_widget = QWidget()
        rh = QHBoxLayout(row_widget)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addWidget(widget, 1)
        prob_lbl = QLabel()
        prob_lbl.setFixedWidth(40)
        prob_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def update_prob_label(val):
            prob_lbl.setText(f"{val}%")
        spin.valueChanged.connect(update_prob_label)

        rh.addWidget(prob_lbl)

        form_layout.addRow(f"{label_text}:", row_widget)
        row_widget.setToolTip(tooltip)
        return spin, slider, prob_lbl

    def _on_changed(self):
        self._mark_dirty()

    def _on_slider_released(self):
        self._mark_dirty()

    # ── ConfigPanelBase 实现 ──

    def _populate_ui(self, data: dict):
        normal = data.get("normal_pct", 20)
        rare = data.get("rare_pct", 5)

        # 初始化普通槽: spin → slider → label（顺序设置避免触发 dirty）
        self._normal_spin.blockSignals(True)
        self._normal_spin.setValue(normal)
        self._normal_spin.blockSignals(False)
        self._normal_slider.setValue(normal)
        self._normal_lbl.setText(f"{normal}%")

        # 初始化稀有槽
        self._rare_spin.blockSignals(True)
        self._rare_spin.setValue(rare)
        self._rare_spin.blockSignals(False)
        self._rare_slider.setValue(rare)
        self._rare_lbl.setText(f"{rare}%")

    def _collect_ui(self) -> dict:
        return {
            "regular_pct": 100,  # 常规槽始终100%
            "normal_pct": self._normal_spin.value(),
            "rare_pct": self._rare_spin.value(),
        }
