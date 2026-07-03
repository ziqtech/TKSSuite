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
import sys
import os
from pathlib import Path
from PySide6.QtCore import QTranslator
from PySide6.QtGui import QIcon


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
