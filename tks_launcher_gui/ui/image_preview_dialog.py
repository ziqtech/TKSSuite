"""图片预览对话框 — 可缩放 / 拖拽的大图查看。

PySide6 / Qt Widgets 没有现成的图片查看控件, 这里用
QGraphicsView + QGraphicsScene + QGraphicsPixmapItem 组合实现:
  - 滚轮缩放 (以光标为锚点), 工具栏显示当前缩放百分比
  - 按住拖拽平移
  - 打开时自适应窗口, 双击复位; 1:1 按钮切换原始像素比例
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from editor_utils.ui_helpers import set_themed_icon


class _ZoomGraphicsView(QGraphicsView):
    """支持滚轮缩放 + 拖拽平移的视图。"""

    _MIN_SCALE = 0.05
    _MAX_SCALE = 40.0

    #: 缩放变化后发出 (参数为当前缩放系数, 1.0 = 1:1)
    zoomChanged = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.black)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        cur = self.transform().m11()
        if not (self._MIN_SCALE <= cur * factor <= self._MAX_SCALE):
            return
        self.scale(factor, factor)
        self.zoomChanged.emit(self.transform().m11())

    def set_zoom(self, factor: float):
        """设置绝对缩放系数 (1.0 = 1:1), 以视口中心为锚点。"""
        factor = max(self._MIN_SCALE, min(self._MAX_SCALE, factor))
        cur = self.transform().m11()
        if cur <= 0 or factor == cur:
            return
        self.scale(factor / cur, factor / cur)
        self.zoomChanged.emit(self.transform().m11())


class ImagePreviewDialog(QDialog):
    """全分辨率图片预览: 滚轮缩放, 拖拽平移, 1:1 / 适应窗口, 双击复位适配。"""

    def __init__(self, pixmap: QPixmap, title: str = "图片预览", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem(pixmap)
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._scene.setSceneRect(self._item.boundingRect())

        self._view = _ZoomGraphicsView(self._scene, self)
        self._view.zoomChanged.connect(self._on_zoom_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view, 1)
        layout.addWidget(self._build_zoom_bar())

        self._init_size(pixmap)

    def _build_zoom_bar(self) -> QWidget:
        """底部缩放工具条: 缩小 / 百分比 / 放大 / 1:1 / 适应窗口。"""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 6)
        row.setSpacing(6)

        btn_out = QPushButton("")
        set_themed_icon(btn_out, "minus")
        btn_out.setProperty("class", "CompactBtn")
        btn_out.setFixedWidth(32)
        btn_out.setToolTip("缩小")
        btn_out.clicked.connect(lambda: self._view.set_zoom(
            self._view.transform().m11() / 1.25))
        row.addWidget(btn_out)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(56)
        self._zoom_label.setToolTip("当前缩放比例")
        row.addWidget(self._zoom_label)

        btn_in = QPushButton("")
        set_themed_icon(btn_in, "add")
        btn_in.setProperty("class", "CompactBtn")
        btn_in.setFixedWidth(32)
        btn_in.setToolTip("放大")
        btn_in.clicked.connect(lambda: self._view.set_zoom(
            self._view.transform().m11() * 1.25))
        row.addWidget(btn_in)

        btn_1_1 = QPushButton("1:1")
        btn_1_1.setProperty("class", "CompactBtn")
        btn_1_1.setToolTip("按原始像素比例显示 (100%)")
        btn_1_1.clicked.connect(self._zoom_1_1)
        row.addWidget(btn_1_1)

        btn_fit = QPushButton("适应窗口")
        btn_fit.setProperty("class", "CompactBtn")
        btn_fit.setToolTip("缩放至整幅图片适配视口 (双击视图同效)")
        btn_fit.clicked.connect(self._fit)
        row.addWidget(btn_fit)

        row.addStretch()
        return bar

    def _init_size(self, pixmap: QPixmap):
        """初始窗口大小: 略大于图片, 但不超过屏幕可用区域的 80%。"""
        scr = self.screen().availableGeometry() if self.screen() else None
        max_w = int(scr.width() * 0.8) if scr else 900
        max_h = int(scr.height() * 0.8) if scr else 700
        self.resize(min(pixmap.width() + 40, max_w),
                    min(pixmap.height() + 40, max_h))

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _fit(self):
        """将整幅图片缩放至适配视口。"""
        self._view.fitInView(self._item, Qt.KeepAspectRatio)
        self._view.zoomChanged.emit(self._view.transform().m11())

    def _zoom_1_1(self):
        """切换到 1:1 原始像素比例, 视图滚动到图片中心。"""
        self._view.set_zoom(1.0)
        self._view.centerOn(self._item)

    def _on_zoom_changed(self, factor: float):
        self._zoom_label.setText(f"{factor * 100:.0f}%")

    def mouseDoubleClickEvent(self, event):
        self._fit()
        super().mouseDoubleClickEvent(event)
