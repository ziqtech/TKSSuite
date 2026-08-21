"""
Godot 风格 Dock 面板组件 — 供所有编辑器统一使用
包含: DockHeader (标题栏) + create_dock (面板工厂)
"""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel


class DockHeader(QFrame):
    """Godot 风格 Dock 面板标题栏"""
    def __init__(self, title, right_layout=None):
        super().__init__()
        self.setObjectName("DockHeader")
        layout = QHBoxLayout(self)
        # 标题栏保持紧凑，但给文字和右侧工具留出稳定的呼吸空间。
        # 外框、圆角和底部分界线由主题 QSS 统一绘制。
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(6)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)
        if right_layout:
            layout.addLayout(right_layout)


def create_dock(title, widget_content, header_layout=None,
                body_margins=(8, 8, 8, 8)):
    """创建 Godot 风格 Dock 面板 (DockHeader + DockBody 包裹)

    body_margins: DockBody 内容四周边距 (left, top, right, bottom)，
    默认 8px；传 (0, 0, 0, 0) 可让内容与标题栏/边框齐平。
    """
    container = QWidget()
    container.setObjectName("DockPanel")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(DockHeader(title, header_layout))
    body = QWidget()
    body.setObjectName("DockBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(*body_margins)
    body_layout.setSpacing(6)
    body_layout.addWidget(widget_content)
    layout.addWidget(body, 1)
    return container
