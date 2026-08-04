"""
AnimationSpeedPanel — 动画/移动速度配置面板
编辑 animation_speed.json 中的 4 类战斗动画速度 + 剧情地图移动速度参数。

类型与有效范围 (与 patch_engine.py 中的验证一致):
- status_animation.frame_delay_ms:        1~127  (状态动画, 6个函数硬编码 0x3C)
- attack_animation.base_frame_delay_ms:   1~255  (攻击+技能动画, sub_4434BC 的 add edx,0x3C)
- attack_animation.extra_segment_delay_ms: 1~32767 (新动画段过渡延迟, mov word[ebp-2Ah],0x78)
- attack_animation.extra_delay_decrement_ms: 1~128 (额外延迟衰减步长, add word[ebp-2Ah],-30)
- move_animation.frame_delay_ms:          1~127  (移动动画, sub_43DE90 硬编码 0x3C)
- idle_animation.frame_delay_ms:          1~127  (待机动画, sub_43CA64 战场主循环硬编码 0x3C)
- map_movement.frame_delay_ms:            1~127  (剧情地图移动, sub_412BE8 地图主循环帧节流 0x3C)

安全约束: extra_segment_delay_ms 必须能被 extra_delay_decrement_ms 整除
         (否则 v30 递减后变负, 无符号比较导致死循环卡死)
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSlider, QSpinBox,
    QLabel, QPushButton, QWidget, QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt

from .base_panel import ConfigPanelBase

# 原始默认值 (与游戏源码一致)
ORIG_FRAME_DELAY = 60
ORIG_BASE_DELAY = 60
ORIG_EXTRA_DELAY = 120
ORIG_DECREMENT = 30


class AnimationSpeedPanel(ConfigPanelBase):
    config_name = "animation_speed"
    tab_label = "动画速度"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        # 外层: 内容放入 QScrollArea, 窗口高度不足时滚动而非压缩控件
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(8)

        # ── 状态动画 ──
        status_group, status_layout = self._new_group_box(
            "状态动画 (中毒/出血/恢复/死战等状态效果)")
        self._status_spin, self._status_slider, self._status_lbl = self._make_spin_slider(
            status_layout, "每帧延迟",
            spin_min=1, spin_max=127, default=ORIG_FRAME_DELAY, orig=ORIG_FRAME_DELAY,
            tooltip="状态动画每帧延迟(毫秒), 范围 1~127\n"
                    "jb 指令使用无符号比较, 值必须为正且 ≤127\n"
                    "原始值 60ms, 设为 30 可加速 2 倍")
        layout.addWidget(status_group)

        # ── 攻击+技能动画 ──
        attack_group, attack_layout = self._new_group_box(
            "攻击+技能动画 (Aa.JVG/TKAct.dat, sub_4434BC)")
        self._base_spin, self._base_slider, self._base_lbl = self._make_spin_slider(
            attack_layout, "基础帧延迟",
            spin_min=1, spin_max=255, default=ORIG_BASE_DELAY, orig=ORIG_BASE_DELAY,
            tooltip="基础帧延迟(毫秒), 范围 1~255\n"
                    "控制动画每帧基础等待时间\n"
                    "原始值 60ms")
        self._extra_spin, self._extra_slider, self._extra_lbl = self._make_spin_slider(
            attack_layout, "新段过渡延迟",
            spin_min=1, spin_max=32767, default=ORIG_EXTRA_DELAY, orig=ORIG_EXTRA_DELAY,
            tooltip="新动画段过渡延迟(毫秒), 范围 1~32767\n"
                    "新动画段开始时追加的等待时间\n"
                    "原始值 120ms\n"
                    "⚠ 必须能被「衰减步长」整除, 否则游戏卡死")
        self._decr_spin, self._decr_slider, self._decr_lbl = self._make_spin_slider(
            attack_layout, "衰减步长",
            spin_min=1, spin_max=128, default=ORIG_DECREMENT, orig=ORIG_DECREMENT,
            invert_multiplier=True,
            tooltip="额外延迟衰减步长(毫秒), 范围 1~128\n"
                    "控制额外延迟的衰减速度, 值越大衰减越快\n"
                    "原始值 30ms\n"
                    "⚠ 必须能整除「新段过渡延迟」, 否则游戏卡死")
        layout.addWidget(attack_group)

        # ── 移动动画 ──
        move_group, move_layout = self._new_group_box("移动动画 (Awk.JVG, sub_43DE90)")
        self._move_spin, self._move_slider, self._move_lbl = self._make_spin_slider(
            move_layout, "每帧延迟",
            spin_min=1, spin_max=127, default=ORIG_FRAME_DELAY, orig=ORIG_FRAME_DELAY,
            tooltip="移动动画每帧延迟(毫秒), 范围 1~127\n"
                    "原始值 60ms, 设为 30 可加速 2 倍")
        layout.addWidget(move_group)

        # ── 待机动画 ──
        idle_group, idle_layout = self._new_group_box(
            "待机动画 (Awt.JVG, sub_43CA64 战场主循环)")
        self._idle_spin, self._idle_slider, self._idle_lbl = self._make_spin_slider(
            idle_layout, "每帧延迟",
            spin_min=1, spin_max=127, default=ORIG_FRAME_DELAY, orig=ORIG_FRAME_DELAY,
            tooltip="待机动画每帧延迟(毫秒), 范围 1~127\n"
                    "原始值 60ms, 设为 30 可加速 2 倍")
        layout.addWidget(idle_group)

        # ── 剧情地图移动 ──
        map_group, map_layout = self._new_group_box(
            "剧情地图移动速度 (sub_412BE8 地图主循环帧节流)")
        self._map_spin, self._map_slider, self._map_lbl = self._make_spin_slider(
            map_layout, "每帧延迟",
            spin_min=1, spin_max=127, default=ORIG_FRAME_DELAY, orig=ORIG_FRAME_DELAY,
            tooltip="剧情地图主循环每帧延迟(毫秒), 范围 1~127\n"
                    "控制主角在所有剧情地图(大地图/城镇/室内)中的移动速度\n"
                    "原始值 60ms(约16.7帧/秒), 设为 30 移动加速 2 倍\n"
                    "注意: 地图上的 NPC 行走/事件动画也会同步加速")
        layout.addWidget(map_group)

        # ── 说明 ──
        tip_label = QLabel(
            "提示: 修改后需在启动器中勾选「战斗动画速度」补丁才会生效。\n"
            "所有值默认为游戏原始值 (60ms/120ms/30ms), 设小可加快动画播放。\n"
            "剧情地图移动速度同理: 帧延迟设小, 主角行走越快。\n"
            "⚠ 攻击动画的「新段过渡延迟」必须能被「衰减步长」整除, 否则游戏会卡死。"
        )
        tip_label.setWordWrap(True)
        tip_label.setObjectName("TipLabel")
        layout.addWidget(tip_label)

        # ── 按钮 ──
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        btn_2x = QPushButton("⚡ 全部 2 倍速")
        btn_2x.setToolTip("将所有动画参数设置为 2 倍速 (延迟减半)")
        btn_2x.clicked.connect(self._apply_2x_speed)
        btn_layout.addWidget(btn_2x)

        btn_3x = QPushButton("⚡⚡ 全部 3 倍速")
        btn_3x.setToolTip("将所有动画参数设置为 3 倍速 (延迟除以 3)")
        btn_3x.clicked.connect(self._apply_3x_speed)
        btn_layout.addWidget(btn_3x)

        btn_max = QPushButton("💥 全部极速")
        btn_max.setToolTip("将所有动画参数设置为 10ms (极速)")
        btn_max.clicked.connect(self._apply_max_speed)
        btn_layout.addWidget(btn_max)

        btn_reset = QPushButton("🔄 重置默认")
        btn_reset.setToolTip("恢复到游戏原始值")
        btn_reset.clicked.connect(self._reset_to_default)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()
        layout.addWidget(btn_row)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    @staticmethod
    def _new_group_box(title: str):
        """创建带紧凑边距的 QGroupBox, 减少组内空白占用。"""
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(10, 14, 10, 8)
        form.setVerticalSpacing(6)
        return group, form

    def _make_spin_slider(self, form_layout, label_text, spin_min, spin_max,
                           default, orig, tooltip, invert_multiplier=False):
        """创建 SpinBox + Slider + 倍数Label 联动控件行。

        布局: [Slider 拉伸] [SpinBox 固定宽] [倍数Label 固定宽]
        Slider 范围统一为 1~127, 超出时自动钳制。
        倍数Label 显示相对原始值的速度倍数:
          - 普通延迟参数: 倍数 = orig/value (值越小越快)
          - 衰减步长(invert): 倍数 = value/orig (值越大越快)

        返回 (spinbox, slider, mult_lbl) 三元组。
        """
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(1, 127)
        slider.setSingleStep(1)
        slider.setPageStep(10)

        spin = QSpinBox()
        spin.setRange(spin_min, spin_max)
        spin.setSingleStep(5)
        spin.setSuffix(" ms")
        spin.setFixedWidth(80)

        mult_lbl = QLabel()
        mult_lbl.setFixedWidth(50)
        mult_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def update_mult_label(val):
            if invert_multiplier:
                # 衰减步长: 值越大越快
                mult = val / orig if orig else 1.0
            else:
                # 延迟参数: 值越小越快
                mult = orig / val if val else 1.0
            mult_lbl.setText(f"{mult:.1f}x")

        def on_slider(val):
            # 钳制到 spinbox 范围
            clamped = max(spin_min, min(spin_max, val))
            if clamped != val:
                slider.blockSignals(True)
                slider.setValue(clamped)
                slider.blockSignals(False)
            spin.blockSignals(True)
            spin.setValue(clamped)
            spin.blockSignals(False)
            update_mult_label(clamped)
            self._mark_dirty()

        def on_spin(val):
            # 同步 slider (钳制到 1~127)
            clamped = max(1, min(127, val))
            slider.blockSignals(True)
            slider.setValue(clamped)
            slider.blockSignals(False)
            update_mult_label(val)
            self._mark_dirty()

        slider.valueChanged.connect(on_slider)
        spin.valueChanged.connect(on_spin)

        # 初始化默认值
        spin.blockSignals(True)
        spin.setValue(default)
        spin.blockSignals(False)
        slider.setValue(max(1, min(127, default)))
        update_mult_label(default)

        h.addWidget(slider, 1)
        h.addWidget(spin)
        h.addWidget(mult_lbl)

        form_layout.addRow(f"{label_text}:", widget)
        widget.setToolTip(tooltip)
        return spin, slider, mult_lbl

    # ── 快捷按钮 ──

    def _apply_2x_speed(self):
        """2 倍速: 延迟减半, 确保整除约束"""
        self._status_spin.setValue(30)
        self._base_spin.setValue(30)
        self._extra_spin.setValue(60)
        self._decr_spin.setValue(30)  # 60 % 30 == 0 ✓
        self._move_spin.setValue(30)
        self._idle_spin.setValue(30)
        self._map_spin.setValue(30)

    def _apply_3x_speed(self):
        """3 倍速: 延迟除以 3, 确保整除约束"""
        self._status_spin.setValue(20)
        self._base_spin.setValue(20)
        self._extra_spin.setValue(60)
        self._decr_spin.setValue(60)  # 60 % 60 == 0 ✓
        self._move_spin.setValue(20)
        self._idle_spin.setValue(20)
        self._map_spin.setValue(20)

    def _apply_max_speed(self):
        """极速: 所有延迟设为 10ms, 确保整除约束"""
        self._status_spin.setValue(10)
        self._base_spin.setValue(10)
        self._extra_spin.setValue(10)
        self._decr_spin.setValue(10)  # 10 % 10 == 0 ✓
        self._move_spin.setValue(10)
        self._idle_spin.setValue(10)
        self._map_spin.setValue(10)

    def _reset_to_default(self):
        """重置为游戏原始值"""
        self._status_spin.setValue(ORIG_FRAME_DELAY)
        self._base_spin.setValue(ORIG_BASE_DELAY)
        self._extra_spin.setValue(ORIG_EXTRA_DELAY)
        self._decr_spin.setValue(ORIG_DECREMENT)
        self._move_spin.setValue(ORIG_FRAME_DELAY)
        self._idle_spin.setValue(ORIG_FRAME_DELAY)
        self._map_spin.setValue(ORIG_FRAME_DELAY)

    # ── 整除约束验证 ──

    def _validate_extra_decrement(self) -> bool:
        """验证 extra_segment_delay_ms 能被 extra_delay_decrement_ms 整除"""
        extra = self._extra_spin.value()
        decr = self._decr_spin.value()
        if extra % decr != 0:
            QMessageBox.critical(
                self, "安全约束违反",
                f"「新段过渡延迟」({extra}ms) 必须能被「衰减步长」({decr}ms) 整除。\n\n"
                f"原因: 游戏逻辑 if (v30) v30 -= decrement; 每帧递减不检查是否变负,\n"
                f"while (GetTickCount() - dword_4E7CD0 < v30 + base_delay) 使用无符号比较(jb),\n"
                f"若 v30 变负, v30+base_delay 也可能为负, 无符号比较将其当作超大正数 → 死循环卡死。\n\n"
                f"建议: 新段过渡延迟 = 衰减步长 × N (N 为正整数)"
            )
            return False
        return True

    # ── ConfigPanelBase 实现 ──

    def _populate_ui(self, data: dict):
        # 状态动画
        status_cfg = data.get("status_animation", {})
        self._set_value(self._status_spin, self._status_slider, self._status_lbl,
                        int(status_cfg.get("frame_delay_ms", ORIG_FRAME_DELAY)),
                        ORIG_FRAME_DELAY)

        # 攻击+技能动画
        attack_cfg = data.get("attack_animation", {})
        self._set_value(self._base_spin, self._base_slider, self._base_lbl,
                        int(attack_cfg.get("base_frame_delay_ms", ORIG_BASE_DELAY)),
                        ORIG_BASE_DELAY)
        self._set_value(self._extra_spin, self._extra_slider, self._extra_lbl,
                        int(attack_cfg.get("extra_segment_delay_ms", ORIG_EXTRA_DELAY)),
                        ORIG_EXTRA_DELAY)
        self._set_value(self._decr_spin, self._decr_slider, self._decr_lbl,
                        int(attack_cfg.get("extra_delay_decrement_ms", ORIG_DECREMENT)),
                        ORIG_DECREMENT, invert_multiplier=True)

        # 移动动画
        move_cfg = data.get("move_animation", {})
        self._set_value(self._move_spin, self._move_slider, self._move_lbl,
                        int(move_cfg.get("frame_delay_ms", ORIG_FRAME_DELAY)),
                        ORIG_FRAME_DELAY)

        # 待机动画
        idle_cfg = data.get("idle_animation", {})
        self._set_value(self._idle_spin, self._idle_slider, self._idle_lbl,
                        int(idle_cfg.get("frame_delay_ms", ORIG_FRAME_DELAY)),
                        ORIG_FRAME_DELAY)

        # 剧情地图移动
        map_cfg = data.get("map_movement", {})
        self._set_value(self._map_spin, self._map_slider, self._map_lbl,
                        int(map_cfg.get("frame_delay_ms", ORIG_FRAME_DELAY)),
                        ORIG_FRAME_DELAY)

    def _set_value(self, spin, slider, lbl, value, orig, invert_multiplier=False):
        """统一设置 spinbox/slider/label 的值, 屏蔽信号避免触发 dirty"""
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
        slider.blockSignals(True)
        slider.setValue(max(1, min(127, value)))
        slider.blockSignals(False)
        if invert_multiplier:
            mult = value / orig if orig else 1.0
        else:
            mult = orig / value if value else 1.0
        lbl.setText(f"{mult:.1f}x")

    def _collect_ui(self) -> dict:
        return {
            "status_animation": {
                "frame_delay_ms": self._status_spin.value()
            },
            "attack_animation": {
                "base_frame_delay_ms": self._base_spin.value(),
                "extra_segment_delay_ms": self._extra_spin.value(),
                "extra_delay_decrement_ms": self._decr_spin.value()
            },
            "move_animation": {
                "frame_delay_ms": self._move_spin.value()
            },
            "idle_animation": {
                "frame_delay_ms": self._idle_spin.value()
            },
            "map_movement": {
                "frame_delay_ms": self._map_spin.value()
            }
        }

    def save(self) -> bool:
        """保存前验证整除约束"""
        if not self._validate_extra_decrement():
            return False
        return super().save()
