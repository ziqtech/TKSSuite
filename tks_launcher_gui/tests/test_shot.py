"""Manual visual verification script for the launcher themes.

Kept import-safe so unittest discovery does not open a GUI window.
"""

import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))


def main():
    os.chdir(_HERE)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from editor_utils.theme_switcher import apply_theme_to_window
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    start_mode = window._get_mode()

    def set_mode(mode):
        button = (
            window._compatible_mode
            if mode == "compatible"
            else window._standard_mode
        )
        button.setChecked(True)
        window._on_mode_changed(button)

    def step4():
        window.grab().save(os.path.join(_HERE, "_shot_dark.png"))
        set_mode(start_mode)
        QTimer.singleShot(200, app.quit)

    def step3():
        window.grab().save(os.path.join(_HERE, "_shot_light.png"))
        apply_theme_to_window(window, "gpt-dark", persist=False)
        QTimer.singleShot(300, step4)

    def step2():
        window.grab().save(os.path.join(_HERE, "_shot_compat.png"))
        set_mode("standard")
        QTimer.singleShot(300, step3)

    def step1():
        apply_theme_to_window(window, "gpt-light", persist=False)
        set_mode("compatible")
        QTimer.singleShot(300, step2)

    QTimer.singleShot(1200, step1)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
