"""启动模式卡片按钮 — 完全自绘的可选中按钮

背景/边框/文本全部在 paintEvent 中绘制, 不依赖 QSS 伪态:
QSS 的 :checked 伪状态对自定义 QAbstractButton 子类不生效
(仅对 QPushButton 等内置按钮生效), 故颜色改由内置主题色表驱动,
色值与 editor_themes 的深/浅主题保持一致 (标准=绿色主操作, 兼容=蓝色辅助操作)。
"""
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

# (背景, 边框, 标题文字) — 与 editor_themes/dark.qss、light.qss 同步维护
_CARD_COLORS = {
    "dark": {
        "base": ("#2f2f2f", "#444444", (236, 236, 236, 220)),
        "base_hover": ("#383838", "#5a5a5a", (236, 236, 236, 235)),
        "std": ("#0f5f4c", "#10a37f", (230, 255, 247, 255)),
        "std_hover": ("#126e59", "#1aaf89", (240, 255, 250, 255)),
        "compat": ("#303b52", "#7aa2f7", (229, 237, 255, 255)),
        "compat_hover": ("#384967", "#91b2ff", (240, 245, 255, 255)),
        "disabled": ("#2a2a2a", "#333333", (236, 236, 236, 75)),
        "checked_disabled": ("#2a2f2e", "#3d5c56", (236, 236, 236, 90)),
    },
    "light": {
        "base": ("#f7f7f8", "#d9d9e3", (45, 45, 45, 220)),
        "base_hover": ("#f1f1f1", "#b6b6c4", (45, 45, 45, 235)),
        "std": ("#e8f7f2", "#10a37f", (8, 127, 99, 255)),
        "std_hover": ("#d9f1e9", "#0d8c6d", (8, 111, 88, 255)),
        "compat": ("#eef2ff", "#7c83fd", (63, 74, 154, 255)),
        "compat_hover": ("#e3e8ff", "#6570d9", (52, 63, 138, 255)),
        "disabled": ("#f7f7f8", "#ececf1", (45, 45, 45, 80)),
        "checked_disabled": ("#edf5f2", "#9acfc0", (45, 45, 45, 105)),
    },
}


def _rgba(value) -> QColor:
    if isinstance(value, str):
        return QColor(value)
    return QColor(*value)


class ModeCardButton(QAbstractButton):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._dark = True
        self._hover = False
        self.setCheckable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(66)
        font = self.font()
        font.setPixelSize(13)
        self.setFont(font)

    # ── 主题 ──
    def set_dark_mode(self, dark: bool) -> None:
        if self._dark != dark:
            self._dark = dark
            self.update()

    # ── 悬停态 (自绘需要手动跟踪) ──
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def _colors(self):
        pal = _CARD_COLORS["dark" if self._dark else "light"]
        if not self.isEnabled():
            return pal["checked_disabled"] if self.isChecked() else pal["disabled"]
        if self.isChecked():
            key = "std" if self.property("mode") == "standard" else "compat"
        else:
            key = "base"
        if self._hover:
            key += "_hover"
        return pal[key]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg, border, title = (_rgba(v) for v in self._colors())

        # 圆角背景 + 1px 描边 (rect 内收 0.5px 保证描边完整)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10.0, 10.0)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1.0))
        p.drawPath(path)

        # 标题(加粗) + 副标题(小字, 标题色降透明度)
        sub_color = QColor(title)
        sub_color.setAlphaF(min(1.0, sub_color.alphaF() * 0.65 + 0.05))

        text_rect = self.rect().adjusted(16, 8, -16, -8)
        half = text_rect.height() // 2

        title_font = self.font()
        title_font.setBold(True)
        sub_font = self.font()
        sub_font.setPixelSize(max(title_font.pixelSize() - 2, 9))

        p.setFont(title_font)
        p.setPen(title)
        p.drawText(QRect(text_rect.left(), text_rect.top(), text_rect.width(), half),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)

        p.setFont(sub_font)
        p.setPen(sub_color)
        p.drawText(QRect(text_rect.left(), text_rect.top() + half, text_rect.width(), half),
                   Qt.AlignLeft | Qt.AlignVCenter, self._subtitle)
