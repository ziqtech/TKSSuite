"""TKS Launcher GUI — PySide6 图形界面启动器入口"""
import sys
import os

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import MainWindow

# 图标路径
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TKS.ico")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TKS Mod Launcher")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("TKSMod")

    # 设置应用图标
    if os.path.isfile(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    # 创建主窗口 (自动检测系统主题)
    window = MainWindow()

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
