"""TKS Launcher GUI — PySide6 图形界面启动器入口"""
import sys
import os

# 确保当前目录在 path 中
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
# 将 仓库根目录 目录加入搜索路径，使 editor_utils 可导入
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import MainWindow

# 图标路径
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TKS.ico")


def main():
    from editor_utils.ui_helpers import install_dialog_theme_filter
    app = QApplication(sys.argv)
    install_dialog_theme_filter(app)
    app.setStyle("Fusion")  # 使用 Fusion 样式，避免 Windows 原生样式覆盖 QSS
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
