"""图像画布视图基类 — Ctrl+滚轮缩放 + 像素悬停 (T12 收敛)。

收敛自 gxp_editor.EnhancedGraphicsView 与 grp_editor.GRPGraphicsView
的逐字孪生实现。jvg/spritesheet/wardata/mat 的画布有各自不同的初始化
样式或交互 (平铺点击/填充柄/涂刷拖拽), 不强行收编。

子类只需声明 ``zoom_step_delta`` (Ctrl+滚轮一次增减的步长), 构造后给
``editor`` 属性赋宿主; 宿主需提供 ``_zoom_step(delta)`` 与可选的
``_update_pixel_info(x, y)``。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView


class CtrlWheelZoomView(QGraphicsView):
    """Ctrl+滚轮缩放、拖拽平移、鼠标位置跟踪的图像视图基类。"""

    zoom_step_delta: float = 0.25

    def __init__(self, scene=None, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            editor = getattr(self, 'editor', None)
            if editor:
                editor._zoom_step(self.zoom_step_delta
                                  if event.angleDelta().y() > 0
                                  else -self.zoom_step_delta)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        editor = getattr(self, 'editor', None)
        if editor is not None and hasattr(editor, '_update_pixel_info'):
            sp = self.mapToScene(event.position().toPoint())
            editor._update_pixel_info(sp.x(), sp.y())
