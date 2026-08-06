"""TKS Launcher GUI — PySide6 图形界面启动器入口"""
import os
import sys

# 确保当前目录在 path 中
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
# 将 仓库根目录 目录加入搜索路径，使 editor_utils 可导入
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

# 图标路径
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TKS.ico")


def _launcher_dir() -> str:
    if "__compiled__" in globals():
        from editor_utils.runtime_bootstrap import get_app_dir
        return get_app_dir()
    return os.path.dirname(os.path.abspath(__file__))


def _verify_patches() -> int:
    from core.patch_engine import validate_script_patch
    from core.tkspatch_loader import load_config_merged

    exe_dir = _launcher_dir()
    lines: list[str] = []
    cfg = load_config_merged(
        os.path.join(exe_dir, "tks_patches.json"),
        os.path.join(exe_dir, "patches"),
        log_func=lines.append,
    )
    if cfg is None or not cfg.patches:
        lines.append("[ERROR] 无法加载补丁配置 (patches/ 为空)")
        ok = False
    else:
        ok = True
        for p in cfg.patches:
            if p.type == "script":
                ok = validate_script_patch(p, log_func=lines.append) and ok
        lines.append(f"[VERIFY] 加载 {len(cfg.patches)} 个补丁, "
                     f"脚本验证 {'通过' if ok else '失败'}")

    try:
        with open(os.path.join(exe_dir, "verify_patches_result.txt"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return 0 if ok else 1


def main():
    if "--verify-patches" in sys.argv:
        sys.exit(_verify_patches())

    from editor_utils.app_init import ensure_single_instance
    ensure_single_instance()
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
