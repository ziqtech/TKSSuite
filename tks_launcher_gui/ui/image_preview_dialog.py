"""图片预览对话框 — 可缩放 / 拖拽的大图查看。

PySide6 / Qt Widgets 没有现成的图片查看控件, 这里用
QGraphicsView + QGraphicsScene + QGraphicsPixmapItem 组合实现:
  - 滚轮缩放 (以光标为锚点)
  - 按住拖拽平移
  - 打开时自适应窗口, 双击复位
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QVBoxLayout,
)


class _ZoomGraphicsView(QGraphicsView):
    """支持滚轮缩放 + 拖拽平移的视图。"""

    _MIN_SCALE = 0.05
    _MAX_SCALE = 40.0

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


class ImagePreviewDialog(QDialog):
    """全分辨率图片预览: 滚轮缩放, 拖拽平移, 双击复位适配窗口。"""

    def __init__(self, pixmap: QPixmap, title: str = "图片预览", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem(pixmap)
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._scene.setSceneRect(self._item.boundingRect())

        self._view = _ZoomGraphicsView(self._scene, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._init_size(pixmap)

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

    def mouseDoubleClickEvent(self, event):
        self._fit()
        super().mouseDoubleClickEvent(event)
