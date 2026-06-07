"""游戏内悬浮窗 — PySide6 无边框透明 QLabel, 替代原 Tkinter OverlayForm"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, QTimer
from core.memory import get_window_rect


class GameOverlay(QLabel):
    def __init__(self, game_hwnd: int):
        super().__init__()
        self.game_hwnd = game_hwnd
        self._ok = False

        self.setWindowFlags(
            Qt.Window |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowTransparentForInput |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.setStyleSheet("""
            QLabel {
                background-color: rgba(32, 37, 49, 210);
                color: #E0E0E0;
                font-family: "Microsoft YaHei", "Segoe UI";
                font-size: 13px;
                font-weight: bold;
                padding: 8px 14px;
                border-radius: 6px;
            }
        """)

        self.setText("正在等待游戏加载...")
        self.adjustSize()
        self.resize(max(self.width(), 240), self.height())

        self._update_position()

        self._tracker = QTimer(self)
        self._tracker.timeout.connect(self._update_position)
        self._tracker.start(100)

        self.show()

    def _update_position(self):
        if self.game_hwnd:
            left, top, right, bottom = get_window_rect(self.game_hwnd)
            if right > left and bottom > top:
                x = right - self.width() - 15
                y = bottom - self.height() - 15
                self.move(x, y)

    def update_text(self, text: str, ok: bool = False):
        if not text:
            # 空文本 = 关闭悬浮窗
            self.close_overlay()
            return
        self._ok = ok
        self.setText(text)
        if ok:
            self.setStyleSheet(self.styleSheet().replace(
                "color: #E0E0E0", "color: #98C379"
            ))
        else:
            self.setStyleSheet(self.styleSheet().replace(
                "color: #98C379", "color: #E0E0E0"
            ))

    def close_overlay(self):
        self._tracker.stop()
        self.close()
