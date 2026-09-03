"""启动模式卡片按钮 — 完全自绘的可选中按钮

背景/边框/文本全部在 paintEvent 中绘制, 不依赖 QSS 伪态:
QSS 的 :checked 伪状态对自定义 QAbstractButton 子类不生效
(仅对 QPushButton 等内置按钮生效), 故颜色取自 theme_tokens.MODE_CARD
语义色表 (标准=主操作色: 现代族绿/经典族 Godot 蓝, 兼容=靛蓝辅助操作)。
"""
from PySide6.QtCore import QPointF, Qt, QRect, QRectF
from PySide6.QtGui import (
    QBrush, QColor, QFontMetrics, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

from editor_utils.theme_manager import business_colors, svg_path, THEMES

_ICON_PATHS = {
    "standard": svg_path("mode-standard.svg"),
    # 经典族 (Godot 风格) 标准模式使用蓝色变体, 与 Godot 蓝选中卡片协调
    "standard_classic": svg_path("mode-standard-classic.svg"),
    "compatible": svg_path("mode-compatible.svg"),
}
_ICON_CACHE: dict[str, QIcon] = {}


def _card_palette(theme_id: str) -> dict:
    """返回指定主题的模式卡片语义色板 (键见 theme_tokens.MODE_CARD)。"""
    if theme_id not in THEMES:
        theme_id = "gpt-dark"
    return business_colors("mode_card", theme_id)


def _rgba(value) -> QColor:
    if isinstance(value, str):
        return QColor(value)
    return QColor(*value)


class ModeCardButton(QAbstractButton):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._theme_id = "gpt-dark"
        self._dark = True
        self._hover = False
        self.setCheckable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(78)
        font = self.font()
        font.setPixelSize(13)
        self.setFont(font)

    # ── 主题 ──
    def set_theme(self, theme_id: str) -> None:
        theme_id = str(theme_id)
        if self._theme_id != theme_id:
            self._theme_id = theme_id
            self._dark = theme_id.endswith("dark")
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
        pal = _card_palette(self._theme_id)
        if not self.isEnabled():
            return pal["checked_disabled"] if self.isChecked() else pal["disabled"]
        if self.isChecked():
            key = "std" if self.property("mode") == "standard" else "compat"
        else:
            key = "base"
        if self._hover:
            key += "_hover"
        return pal[key]

    def _icon(self) -> QIcon:
        mode = self.property("mode") or "standard"
        if mode == "standard" and self._theme_id.startswith("classic"):
            mode = "standard_classic"
        if mode not in _ICON_CACHE:
            _ICON_CACHE[mode] = QIcon(_ICON_PATHS[mode])
        return _ICON_CACHE[mode]

    def _glow_color(self) -> QColor:
        pal = _card_palette(self._theme_id)
        key = "compat_glow" if self.property("mode") == "compatible" else "std_glow"
        color = QColor(pal[key])
        if not self.isEnabled():
            color.setAlpha(55)
        elif not self.isChecked():
            color.setAlpha(105 if self._hover else 70)
        return color

    def _badge_colors(self) -> tuple[QColor, QColor, QColor]:
        """返回当前标签的高对比背景、文字和边框颜色。"""
        pal = _card_palette(self._theme_id)
        key = "badge_compat" if self.property("mode") == "compatible" else "badge_std"
        bg, text, border = pal[key]
        return QColor(bg), QColor(text), QColor(border)

    def _paint_soft_glow(self, painter: QPainter, clip_path: QPainterPath,
                         rect: QRectF) -> None:
        """绘制边缘透明的径向光晕，避免出现实心椭圆色块。"""
        if not (self.isChecked() or self._hover):
            return

        color = self._glow_color()
        # 选中态有存在感，悬停态只做轻提示；两者都在边缘完全淡出。
        if self.isChecked():
            color.setAlpha(68 if self._dark else 42)
        else:
            color.setAlpha(24 if self._dark else 18)

        center = QPointF(rect.right() - 34, rect.top() + 18)
        radius = 126.0
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, color)
        mid = QColor(color)
        mid.setAlpha(round(color.alpha() * 0.38))
        gradient.setColorAt(0.48, mid)
        edge = QColor(color)
        edge.setAlpha(0)
        gradient.setColorAt(1.0, edge)

        painter.save()
        painter.setClipPath(clip_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius,
                                   radius * 2, radius * 2))
        painter.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg, border, title = (_rgba(v) for v in self._colors())

        # 圆角渐变背景 + 描边；选中卡片使用对应模式色做轻微光晕。
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10.0, 10.0)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, bg.lighter(112 if self._dark else 103))
        gradient.setColorAt(1.0, bg.darker(108 if self._dark else 103))
        p.fillPath(path, QBrush(gradient))

        self._paint_soft_glow(p, path, rect)

        p.setPen(QPen(border, 2.0 if self.isChecked() else 1.0))
        p.drawPath(path)

        # 左侧彩色 SVG 图标底座，图标本身使用主题资源中的彩色 SVG。
        icon_box = QRect(16, (self.height() - 44) // 2, 44, 44)
        icon_bg = self._glow_color()
        icon_bg.setAlpha(42 if self._dark else 30)
        p.setPen(QPen(self._glow_color(), 1.0))
        p.setBrush(icon_bg)
        p.drawEllipse(QRectF(icon_box))
        icon_rect = icon_box.adjusted(7, 7, -7, -7)
        self._icon().paint(p, icon_rect, Qt.AlignCenter,
                           QIcon.Disabled if not self.isEnabled() else QIcon.Normal)

        # 标题(加粗) + 副标题(小字, 标题色降透明度)
        sub_color = QColor(title)
        sub_color.setAlphaF(min(1.0, sub_color.alphaF() * 0.65 + 0.05))

        text_rect = self.rect().adjusted(74, 10, -72, -10)
        title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), 25)
        sub_rect = QRect(text_rect.left(), text_rect.top() + 25,
                         text_rect.width(), text_rect.height() - 25)

        title_font = self.font()
        title_font.setBold(True)
        title_font.setPixelSize(14)
        sub_font = self.font()
        sub_font.setPixelSize(11)

        p.setFont(title_font)
        p.setPen(title)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self._title)

        p.setFont(sub_font)
        p.setPen(sub_color)
        subtitle = QFontMetrics(sub_font).elidedText(
            self._subtitle, Qt.ElideRight, sub_rect.width())
        p.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, subtitle)

        # 右上角状态胶囊：仅选中时显示，强化当前模式的识别。
        if self.isChecked() and self.isEnabled():
            badge_bg, badge_text, badge_border = self._badge_colors()
            badge = QRect(self.width() - 64, 12, 48, 24)
            p.setPen(QPen(badge_border, 1.0))
            p.setBrush(badge_bg)
            p.drawRoundedRect(QRectF(badge), 7, 7)
            badge_font = self.font()
            badge_font.setPixelSize(10)
            badge_font.setBold(True)
            p.setFont(badge_font)
            p.setPen(badge_text)
            p.drawText(badge, Qt.AlignCenter, "当前")
