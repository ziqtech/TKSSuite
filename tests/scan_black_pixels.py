"""纯黑像素扫描 —— 找出浅色主题下被硬编码黑色绘制的窗口。

原理: 主题 token 与 QSS 槽位中不存在 #000000 (唯一的例外是 ColorSwatch
色块的底色)，因此浅色主题渲染结果里的精确 #000000 像素都来自 Python
绘制代码中的硬编码黑色或颜色解析失败 (QColor 无效串退化为黑)。

用法（项目根目录）:
    python tests/scan_black_pixels.py            # 浅色两主题 × 全部入口
    python tests/scan_black_pixels.py tks_book   # 仅指定入口
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtGui import QImage  # noqa: E402

from editor_utils import theme_manager  # noqa: E402
from editor_utils.theme_switcher import apply_theme_to_window  # noqa: E402
from tests.test_editor_smoke import (  # noqa: E402
    _SilenceDialogs,
    _ensure_app,
    _make_window_factory,
)

_LIGHT_THEMES = ("gpt-light", "classic-light")


def black_stats(image):
    """返回 (纯黑像素数, 前几个黑点坐标)。"""
    count = 0
    spots = []
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            c = image.pixelColor(x, y)
            if c.red() == 0 and c.green() == 0 and c.blue() == 0:
                count += 1
                if len(spots) < 5:
                    spots.append((x, y))
    # 步长 2 采样, 实际数量约为 4 倍
    return count * 4, spots


def main() -> int:
    wanted = sys.argv[1:]
    app = _ensure_app()
    factories = dict(_make_window_factory())
    names = wanted or list(factories)

    flagged = []
    for name in names:
        if name not in factories:
            print(f"跳过未知入口: {name}")
            continue
        with _SilenceDialogs():
            window = factories[name]()
        window.show()
        app.processEvents()
        for tid in _LIGHT_THEMES:
            apply_theme_to_window(window, tid, persist=False)
            app.processEvents()
            image = window.grab().toImage()
            count, spots = black_stats(image)
            mark = "  <-- 疑似" if count else ""
            print(f"{name} @ {tid}: 纯黑像素 ≈{count}{mark} {spots}")
            if count:
                flagged.append((name, tid))
        window.close()
        window.deleteLater()
        app.processEvents()

    print(f"\n扫描 {len(names)} 个入口 × {len(_LIGHT_THEMES)} 主题, "
          f"疑似问题: {len(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
