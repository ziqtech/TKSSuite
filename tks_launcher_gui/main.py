"""TKS Launcher GUI — PySide6 图形界面启动器入口"""
import os
import sys
from contextlib import suppress

# 确保当前目录在 path 中
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
# 将 仓库根目录 目录加入搜索路径，使 editor_utils 可导入
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

# 图标路径
_ICON_PATH = os.path.join(_THIS_DIR, "TKS.ico")


def _launcher_dir() -> str:
    if "__compiled__" in globals():
        from editor_utils.runtime_bootstrap import get_app_dir
        return get_app_dir()
    return os.path.dirname(os.path.abspath(__file__))


def _verify_patches() -> int:
    from core.patch_engine import validate_script_patch
    from core.tkspatch_loader import load_patch_directory

    exe_dir = _launcher_dir()
    lines: list[str] = []
    cfg = load_patch_directory(
        os.path.join(exe_dir, "patches"),
        log_func=lines.append,
    )
    if cfg is None or not cfg.patches:
        lines.append("[ERROR] 无法加载补丁配置 (patches/ 为空)")
        ok = False
    else:
        # 急切求值: 即使前面失败也要验证全部补丁, 保证日志完整
        script_results = [validate_script_patch(p, log_func=lines.append)
                          for p in cfg.patches if p.type == "script"]
        ok = all(script_results)
        lines.append(f"[VERIFY] 加载 {len(cfg.patches)} 个补丁, "
                     f"脚本验证 {'通过' if ok else '失败'}")

    with suppress(Exception):
        with open(os.path.join(exe_dir, "verify_patches_result.txt"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def _init_logging() -> None:
    """初始化文件日志 (写入 <启动器目录>/logs/, 打包后无控制台尤其依赖它)"""
    from core.log_setup import (
        install_excepthook, log_line, log_session_header, setup_logging,
    )
    log_path = setup_logging(prefix="launcher_gui")
    install_excepthook()
    log_session_header("TKS Launcher GUI")
    if log_path:
        # 经 log_line 写入文件并进入 UI 缓冲, 保证弹窗与文件内容一致
        log_line(f"[日志] 日志文件: {log_path}")
        # 打包后无控制台时 sys.stdout 可能不可写, 忽略
        with suppress(Exception):
            print(f"[日志] 日志文件: {log_path}")


def main():
    _init_logging()

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

    # 创建主窗口 (初始主题: 持久化存档优先, 否则跟随系统深浅色)
    window = MainWindow()

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
