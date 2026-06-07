"""TKS Launcher GUI — PySide6 图形界面启动器入口"""
import sys
import os

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TKS Mod Launcher")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("TKSMod")

    # 启用高 DPI 缩放
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # 创建主窗口
    window = MainWindow()

    # 加载深色主题
    window.set_theme("dark")

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
