"""视觉验证脚本: 兼容蒙板/标准浅色/标准深色 截图后恢复原模式退出

注意: 程序化 setChecked 不触发 QButtonGroup.buttonClicked, 需手动调用 _on_mode_changed。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
os.chdir(_HERE)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.main_window import MainWindow

w = MainWindow()
w.show()
_START_MODE = w._get_mode()


def _set_mode(mode: str):
    btn = w._compatible_mode if mode == "compatible" else w._standard_mode
    btn.setChecked(True)
    w._on_mode_changed(btn)  # 程序化 setChecked 不发射 buttonClicked


def step1_compat_light():
    w.set_theme("light")
    _set_mode("compatible")
    QTimer.singleShot(300, step2)


def step2():
    w.grab().save(os.path.join(_HERE, "_shot_compat.png"))
    _set_mode("standard")
    QTimer.singleShot(300, step3)


def step3():
    w.grab().save(os.path.join(_HERE, "_shot_light.png"))
    w.set_theme("dark")
    QTimer.singleShot(300, step4)


def step4():
    w.grab().save(os.path.join(_HERE, "_shot_dark.png"))
    _set_mode(_START_MODE)  # 恢复用户原有模式
    QTimer.singleShot(200, app.quit)


QTimer.singleShot(1200, step1_compat_light)
sys.exit(app.exec())
