"""
app_init — 编辑器应用初始化辅助模块
=====================================
封装 Nuitka/PyInstaller 打包 / 开发环境 的路径差异，为所有编辑器提供统一的：
  - 资源目录定位 (get_resource_dir / get_frozen_base)
  - 翻译器安装 (install_translator)
  - 图标路径解析 (get_icon_path)
  - 外部配置目录 (get_config_dir)

支持环境:
  - 开发: 直接运行 Python 脚本
  - Nuitka --onefile: 单文件 exe，数据烘焙在 exe 内
  - Nuitka --standalone: 独立目录
  - PyInstaller (frozen): 后向兼容
"""
import os
import sys
from pathlib import Path
from PySide6.QtCore import QTranslator
from PySide6.QtGui import QIcon


# 单实例互量句柄 — 必须持有到进程结束, 防止被 GC 提前释放互斥量
_single_instance_mutex = None


def ensure_single_instance(app_name: str | None = None):
    """单实例守卫: 同一程序重复启动时弹窗提示并退出新实例。

    实现: Windows 命名互斥量 (ctypes CreateMutexW)。
      - 按编辑器锁定: 同名互斥量仅限制同一程序 (不同编辑器互不影响)
      - 进程退出/崩溃后系统自动释放互斥量, 无死锁残留
      - Wine (Winlator) 兼容
      - 非 Windows 平台或创建失败时静默放行 (不阻断主流程)

    互斥量名默认取自 sys.argv[0] 文件名 (不含扩展名):
      - 编译模式: exe 名 (如 TKSItemEditor)
      - 开发模式: 脚本名 (如 item_editor_v2)

    应在 main() 入口处尽早调用。检测到重复实例时创建临时 QApplication
    弹出提示框后 sys.exit(1)。
    """
    global _single_instance_mutex
    if os.name != 'nt':
        return

    name = app_name or os.path.splitext(os.path.basename(sys.argv[0]))[0]
    mutex_name = f"TKSEditors_{name}_Singleton"

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        ERROR_ALREADY_EXISTS = 183
        if not handle or kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            _single_instance_mutex = handle  # 首个实例: 持有句柄到进程结束
            return
    except Exception:
        return  # 创建失败时不阻断启动

    # ── 已有实例在运行: 提示后退出 ──
    from PySide6.QtWidgets import QApplication, QMessageBox
    if QApplication.instance() is None:
        QApplication(sys.argv)
    QMessageBox.warning(None, "程序已在运行",
        f"检测到 {name} 已有实例在运行。\n\n"
        "为避免多窗口同时编辑导致数据错乱，新实例即将退出。\n"
        "请在已打开的窗口中继续操作。")
    sys.exit(1)


def is_compiled() -> bool:
    """检测是否运行在编译环境 (Nuitka 或 PyInstaller)"""
    return (
        getattr(sys, 'frozen', False)           # PyInstaller
        or "__compiled__" in globals()          # Nuitka (module-level)
        or hasattr(sys, '_MEIPASS')             # PyInstaller fallback
    )


def get_frozen_base() -> str:
    """获取打包环境下的内部资源根目录。

    - Nuitka onefile: 数据文件在 exe 旁边的临时目录 (由 __file__ 解析)
    - Nuitka standalone: exe 同级目录
    - PyInstaller: sys._MEIPASS
    - 开发:  目录
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller
        return sys._MEIPASS
    # Nuitka 或开发环境 —— __file__ 都指向正确位置
    return os.path.join(os.path.dirname(__file__), '..')


def get_app_dir() -> Path:
    """获取 exe 实际所在目录 (用于定位 configs/, mods/ 等外部目录)。

    - 打包环境: 通过 runtime_bootstrap.get_app_dir() (使用 sys.argv[0],
      在 Nuitka onefile 下正确返回原始 exe 路径而非临时解压目录)
    - 开发环境:  目录
    """
    if is_compiled():
        from editor_utils.runtime_bootstrap import get_app_dir as _bs_get_app_dir
        return Path(_bs_get_app_dir())
    return Path(__file__).resolve().parent.parent


def get_config_dir() -> Path:
    """获取外部配置目录 (configs/)，始终位于 exe 同级目录。"""
    return get_app_dir() / "configs"


def get_resource_dir(subdir: str) -> str:
    """获取打包/开发环境下的资源子目录绝对路径。

    Args:
        subdir: 相对于 仓库根目录 (开发) 或打包根目录的子目录名
                例如 'editor_utils', 'editor_themes'
    """
    return os.path.join(get_frozen_base(), subdir)


def install_translator(app) -> QTranslator:
    """安装 Qt 中文翻译器 (qtbase_zh_CN.qm)。

    Args:
        app: QApplication 实例

    Returns:
        QTranslator 实例 (调用者需保持引用以防被 GC)
    """
    translator = QTranslator()
    qm_dir = get_resource_dir('editor_utils')
    translator.load("qtbase_zh_CN", qm_dir)
    app.installTranslator(translator)
    return translator


def get_icon_path(editor_dir: str = '', icon_name: str = 'TKS.ico') -> str:
    """获取编辑器图标的绝对路径。

    打包环境: 烘焙进 exe 的 TKS.ico (位于资源根目录)
    开发环境: <editor_dir>/<icon_name>

    Args:
        editor_dir: 开发环境下编辑器所在目录 (通常传 os.path.dirname(__file__))
        icon_name: 图标文件名

    Returns:
        图标文件绝对路径
    """
    if is_compiled():
        return os.path.join(get_frozen_base(), icon_name)
    return os.path.join(editor_dir, icon_name)


def setup_app_icon(app, editor_dir: str = '', icon_name: str = 'TKS.ico'):
    """为 QApplication 设置窗口图标 (如果图标文件存在)。

    Args:
        app: QApplication 实例
        editor_dir: 开发环境下编辑器所在目录
        icon_name: 图标文件名
    """
    ico_path = get_icon_path(editor_dir, icon_name)
    if os.path.isfile(ico_path):
        app.setWindowIcon(QIcon(ico_path))
