"""启动模式卡片按钮 — 完全自绘的可选中按钮

背景/边框/文本全部在 paintEvent 中绘制, 不依赖 QSS 伪态:
QSS 的 :checked 伪状态对自定义 QAbstractButton 子类不生效
(仅对 QPushButton 等内置按钮生效), 故颜色改由内置主题色表驱动,
色值与 editor_themes 的深/浅主题保持一致 (标准=蓝, 兼容=琥珀)。
"""
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

# (背景, 边框, 标题文字) — 与 editor_themes/dark.qss、light.qss 同步维护
_CARD_COLORS = {
    "dark": {
        "base": ("#202531", "#2a303d", (255, 255, 255, 191)),
        "base_hover": ("#2e3548", "#3b445c", (255, 255, 255, 191)),
        "std": ("#1e3a5f", "#478cbf", (220, 235, 255, 255)),
        "std_hover": ("#24456e", "#478cbf", (220, 235, 255, 255)),
        "compat": ("#4a3a16", "#e8a33d", (255, 233, 196, 255)),
        "compat_hover": ("#57441b", "#e8a33d", (255, 233, 196, 255)),
        "disabled": ("#252a35", "#2a303d", (255, 255, 255, 77)),
        "checked_disabled": ("#252b33", "#3d5570", (255, 255, 255, 89)),
    },
    "light": {
        "base": ("#d9dee4", "#b0b5bd", (0, 0, 0, 191)),
        "base_hover": ("#cdd3d9", "#a6abb2", (0, 0, 0, 191)),
        "std": ("#dbe9ff", "#478cbf", (19, 59, 118, 255)),
        "std_hover": ("#c9defc", "#478cbf", (19, 59, 118, 255)),
        "compat": ("#ffedd0", "#d47d03", (122, 72, 0, 255)),
        "compat_hover": ("#fde3b8", "#d47d03", (122, 72, 0, 255)),
        "disabled": ("#d5d9dd", "#c3c8cf", (0, 0, 0, 89)),
        "checked_disabled": ("#e3e9f2", "#9db8dc", (0, 0, 0, 102)),
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
        self.setMinimumHeight(54)
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
        path.addRoundedRect(rect, 6.0, 6.0)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1.0))
        p.drawPath(path)

        # 标题(加粗) + 副标题(小字, 标题色降透明度)
        sub_color = QColor(title)
        sub_color.setAlphaF(min(1.0, sub_color.alphaF() * 0.65 + 0.05))

        text_rect = self.rect().adjusted(14, 6, -14, -6)
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
