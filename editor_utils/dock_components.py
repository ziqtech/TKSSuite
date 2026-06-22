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
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("DockTitle")
        layout.addWidget(lbl, 1)
        if right_layout:
            layout.addLayout(right_layout)


def create_dock(title, widget_content, header_layout=None):
    """创建 Godot 风格 Dock 面板 (DockHeader + DockBody 包裹)"""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(DockHeader(title, header_layout))
    body = QWidget()
    body.setObjectName("DockBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(8, 8, 8, 8)
    body_layout.addWidget(widget_content)
    layout.addWidget(body)
    return container
