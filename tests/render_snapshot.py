"""样式快照工具 —— 离屏渲染指定入口窗口并保存 PNG。

用法（项目根目录）:
    python tests/render_snapshot.py tks_book item_editor
    python tests/render_snapshot.py tks_launcher_gui

对每个入口的 4 个主题各保存一张 PNG 到系统临时目录, 并打印路径。
用于主题样式的视觉核对 (配合像素取样定位绘制来源)。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from editor_utils import theme_manager  # noqa: E402
from editor_utils.theme_switcher import apply_theme_to_window  # noqa: E402
from tests.test_editor_smoke import (  # noqa: E402
    _SilenceDialogs,
    _ensure_app,
    _make_window_factory,
)

_OUT_DIR = Path(tempfile.gettempdir()) / "tks_style_snapshots"


def main() -> int:
    wanted = sys.argv[1:] or ["tks_book"]
    app = _ensure_app()
    _OUT_DIR.mkdir(exist_ok=True)

    factories = dict(_make_window_factory())
    for name in wanted:
        if name not in factories:
            print(f"未知入口: {name} (可选: {', '.join(factories)})")
            return 2
        with _SilenceDialogs():
            window = factories[name]()
        window.show()
        app.processEvents()
        for tid in theme_manager.THEME_ORDER:
            apply_theme_to_window(window, tid, persist=False)
            app.processEvents()
            out = _OUT_DIR / f"{name}_{tid}.png"
            window.grab().save(str(out))
            print(out)
        window.close()
        window.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
