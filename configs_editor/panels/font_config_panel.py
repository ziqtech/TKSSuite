"""
FontConfigPanel — 游戏默认字体自定义配置面板
编辑 font_config.json 中的 3 个渲染器 FTYPE 值和描边开关。
"""
from functools import partial
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox,
    QCheckBox, QLabel, QPushButton, QWidget
)
from PySide6.QtCore import Qt

from .base_panel import ConfigPanelBase

# 渲染器显示名: (JSON键, 显示名)
RENDERERS = [
    ("main",           "对话框字体(原版=1)"),
    ("menu_name_font", "菜单字体(原版=2)"),
    ("tooltip_font",   "说明字体(原版=0)"),
]


class FontConfigPanel(ConfigPanelBase):
    config_name = "font_config"
    tab_label = "字体配置"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ftype_table = {}  # ftype_table 数据，用于显示字体名称
        self._combos: dict[str, QComboBox] = {}
        self._outline_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 字体类型设置 ──
        font_group = QGroupBox("字体类型设置")
        font_layout = QFormLayout(font_group)
        font_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for key, display_name in RENDERERS:
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(8)

            combo = QComboBox()
            combo.setFixedWidth(200)
            self._combos[key] = combo
            rh.addWidget(combo)

            outline_check = QCheckBox("描边")
            outline_check.setToolTip("0=关闭描边, 1=开启描边 (sub_44AF7C 的 a7 参数)")
            self._outline_checks[key] = outline_check
            rh.addWidget(outline_check)

            rh.addStretch()
            font_layout.addRow(f"{display_name}:", row)

        layout.addWidget(font_group)

        # ── 字体类型对照表 ──
        ref_group = QGroupBox("字体类型对照表 (FTYPE → FONT9696 区段)")
        ref_layout = QVBoxLayout(ref_group)
        self._ref_label = QLabel()
        self._ref_label.setWordWrap(True)
        self._ref_label.setTextFormat(Qt.TextFormat.RichText)
        ref_layout.addWidget(self._ref_label)
        layout.addWidget(ref_group)

        # ── 说明 ──
        tip_label = QLabel(
            "提示: 修改后需在启动器中勾选「字体配置」补丁才会生效。\n"
            "游戏使用图片字体，FTYPE 对应 FONT9696 区段索引 (0-7)。\n"
            "描边通过位图膨胀算法实现 (向右下各扩展2像素), 描边色固定为黑色。"
        )
        tip_label.setWordWrap(True)
        tip_label.setObjectName("TipLabel")
        layout.addWidget(tip_label)

        # ── 按钮 ──
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_reset = QPushButton("🔄 重置默认")
        btn_reset.setToolTip("恢复到本次加载时的原始值。")
        btn_reset.clicked.connect(self.reset)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        layout.addWidget(btn_row)

        layout.addStretch()

    def _refresh_combo_items(self):
        """根据 ftype_table 填充各 ComboBox 的选项。"""
        for combo in self._combos.values():
            combo.blockSignals(True)
            combo.clear()
            for ftype in range(8):
                key = str(ftype)
                desc = self._ftype_table.get(key, f"字体{ftype}")
                combo.addItem(f"{ftype} - {desc}", ftype)
            combo.blockSignals(False)

    def _refresh_ref_label(self):
        """刷新字体类型对照表显示。"""
        rows = []
        for ftype in range(8):
            key = str(ftype)
            desc = self._ftype_table.get(key, f"字体{ftype}")
            rows.append(f"<tr><td><b>FTYPE {ftype}</b></td><td>{desc}</td></tr>")
        self._ref_label.setText(
            "<table cellpadding='4'>"
            + "".join(rows)
            + "</table>"
        )

    def _on_changed(self):
        self._mark_dirty()

    # ── ConfigPanelBase 实现 ──

    def _populate_ui(self, data: dict):
        renderers = data.get("renderers", {})
        self._ftype_table = data.get("ftype_table", {})

        # 填充 ComboBox 选项
        self._refresh_combo_items()
        self._refresh_ref_label()

        # 设置各渲染器当前值
        for key, _ in RENDERERS:
            rc = renderers.get(key, {})
            ftype = int(rc.get("ftype", 0))
            outline = int(rc.get("outline", 0))

            combo = self._combos[key]
            combo.blockSignals(True)
            idx = combo.findData(ftype)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

            check = self._outline_checks[key]
            check.blockSignals(True)
            check.setChecked(bool(outline))
            check.blockSignals(False)

        # 连接信号（在初始填充之后，避免触发 dirty）
        for key, _ in RENDERERS:
            self._combos[key].currentIndexChanged.connect(self._on_changed)
            self._outline_checks[key].toggled.connect(self._on_changed)

    def _collect_ui(self) -> dict:
        result = {}
        for key, _ in RENDERERS:
            combo = self._combos[key]
            ftype = combo.currentData()
            if ftype is None:
                ftype = 0
            outline = 1 if self._outline_checks[key].isChecked() else 0
            result[key] = {"ftype": int(ftype), "outline": outline}
        return {"renderers": result}
