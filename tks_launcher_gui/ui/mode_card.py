"""启动模式卡片按钮 — 完全自绘的可选中按钮

背景/边框/文本全部在 paintEvent 中绘制, 不依赖 QSS 伪态:
QSS 的 :checked 伪状态对自定义 QAbstractButton 子类不生效
(仅对 QPushButton 等内置按钮生效), 故颜色改由内置主题色表驱动,
色值与 editor_themes 的深/浅主题保持一致 (标准=绿色主操作, 兼容=蓝色辅助操作)。
"""
from PySide6.QtCore import QPointF, Qt, QRect, QRectF
from PySide6.QtGui import (
    QBrush, QColor, QFontMetrics, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

from editor_utils.theme_manager import svg_path

# (背景, 边框, 标题文字) — 与 editor_themes/*.qss 同步维护
# 两族语义一致: 标准=绿色主操作、兼容=蓝色辅助; 经典族色值取自早期参考样式。
_CARD_COLORS = {
    "gpt-dark": {
        "base": ("#2f2f2f", "#444444", (236, 236, 236, 220)),
        "base_hover": ("#383838", "#5a5a5a", (236, 236, 236, 235)),
        "std": ("#0f5f4c", "#10a37f", (230, 255, 247, 255)),
        "std_hover": ("#126e59", "#1aaf89", (240, 255, 250, 255)),
        "compat": ("#303b52", "#7aa2f7", (229, 237, 255, 255)),
        "compat_hover": ("#384967", "#91b2ff", (240, 245, 255, 255)),
        "disabled": ("#2a2a2a", "#333333", (236, 236, 236, 75)),
        "checked_disabled": ("#2a2f2e", "#3d5c56", (236, 236, 236, 90)),
        "std_glow": "#10a37f",
        "compat_glow": "#7aa2f7",
        "badge_std": ("#D9FFF1", "#075C47", "#76E9C1"),
        "badge_compat": ("#DDE8FF", "#1E3977", "#9DBDFF"),
    },
    "gpt-light": {
        "base": ("#f7f7f8", "#d9d9e3", (45, 45, 45, 220)),
        "base_hover": ("#f1f1f1", "#b6b6c4", (45, 45, 45, 235)),
        "std": ("#e8f7f2", "#10a37f", (8, 127, 99, 255)),
        "std_hover": ("#d9f1e9", "#0d8c6d", (8, 111, 88, 255)),
        "compat": ("#eef2ff", "#7c83fd", (63, 74, 154, 255)),
        "compat_hover": ("#e3e8ff", "#6570d9", (52, 63, 138, 255)),
        "disabled": ("#f7f7f8", "#ececf1", (45, 45, 45, 80)),
        "checked_disabled": ("#edf5f2", "#9acfc0", (45, 45, 45, 105)),
        "std_glow": "#10a37f",
        "compat_glow": "#7c83fd",
        "badge_std": ("#087F63", "#FFFFFF", "#087F63"),
        "badge_compat": ("#4F5BB5", "#FFFFFF", "#4F5BB5"),
    },
    "classic-dark": {
        "base": ("#1a1e27", "#14171f", (220, 220, 220, 220)),
        "base_hover": ("#252a35", "#2a303d", (220, 220, 220, 235)),
        "std": ("#2b5f3a", "#1e4a2c", (224, 245, 229, 255)),
        "std_hover": ("#367a4a", "#55b572", (235, 250, 240, 255)),
        "compat": ("#303b52", "#7aa2f7", (229, 237, 255, 255)),
        "compat_hover": ("#384967", "#91b2ff", (240, 245, 255, 255)),
        "disabled": ("#252a35", "#14171f", (220, 220, 220, 75)),
        "checked_disabled": ("#2a303d", "#2b5f3a", (220, 220, 220, 90)),
        "std_glow": "#55b572",
        "compat_glow": "#7aa2f7",
        "badge_std": ("#DFF2E4", "#1E5A34", "#76C893"),
        "badge_compat": ("#DDE8FF", "#1E3977", "#9DBDFF"),
    },
    "classic-light": {
        "base": ("#ffffff", "#b0b5bd", (34, 34, 34, 220)),
        "base_hover": ("#f2f5f7", "#a6abb2", (34, 34, 34, 235)),
        "std": ("#3a8c52", "#2e7041", (255, 255, 255, 255)),
        "std_hover": ("#45a362", "#3a8c52", (255, 255, 255, 255)),
        "compat": ("#eef2ff", "#7c83fd", (63, 74, 154, 255)),
        "compat_hover": ("#e3e8ff", "#6570d9", (52, 63, 138, 255)),
        "disabled": ("#ffffff", "#b0b5bd", (34, 34, 34, 80)),
        "checked_disabled": ("#eaf3ea", "#9ac0a8", (34, 34, 34, 105)),
        "std_glow": "#3a8c52",
        "compat_glow": "#7c83fd",
        "badge_std": ("#2F855A", "#FFFFFF", "#2F855A"),
        "badge_compat": ("#4F5BB5", "#FFFFFF", "#4F5BB5"),
    },
}

_ICON_PATHS = {
    "standard": svg_path("mode-standard.svg"),
    "compatible": svg_path("mode-compatible.svg"),
}
_ICON_CACHE: dict[str, QIcon] = {}


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
        if theme_id not in _CARD_COLORS:
            theme_id = "gpt-dark"
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
        pal = _CARD_COLORS[self._theme_id]
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
        if mode not in _ICON_CACHE:
            _ICON_CACHE[mode] = QIcon(_ICON_PATHS[mode])
        return _ICON_CACHE[mode]

    def _glow_color(self) -> QColor:
        pal = _CARD_COLORS[self._theme_id]
        key = "compat_glow" if self.property("mode") == "compatible" else "std_glow"
        color = QColor(pal[key])
        if not self.isEnabled():
            color.setAlpha(55)
        elif not self.isChecked():
            color.setAlpha(105 if self._hover else 70)
        return color

    def _badge_colors(self) -> tuple[QColor, QColor, QColor]:
        """返回当前标签的高对比背景、文字和边框颜色。"""
        pal = _CARD_COLORS[self._theme_id]
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
