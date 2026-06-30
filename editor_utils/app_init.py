"""
app_init — 编辑器应用初始化辅助模块
=====================================
封装 PyInstaller 打包 / 开发环境 的路径差异，为所有编辑器提供统一的：
  - 资源目录定位 (get_resource_dir / get_frozen_base)
  - 翻译器安装 (install_translator)
  - 图标路径解析 (get_icon_path)
"""
import sys
import os
from PySide6.QtCore import QTranslator
from PySide6.QtGui import QIcon


def get_frozen_base() -> str:
    """获取 PyInstaller 打包时的内部资源根目录 (_MEIPASS)，
    开发环境返回  目录。"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.join(os.path.dirname(__file__), '..')


def get_resource_dir(subdir: str) -> str:
    """获取打包/开发环境下的资源子目录绝对路径。

    Args:
        subdir: 相对于 仓库根目录 (开发) 或 _MEIPASS (打包) 的子目录名
                例如 'editor_utils', 'editor_themes'
    """
    return os.path.join(get_frozen_base(), subdir)


def install_translator(app) -> QTranslator:
    """安装 Qt 中文翻译器 (qtbase_zh_CN.qm)。

    翻译文件在打包时位于 _MEIPASS/editor_utils/qtbase_zh_CN.qm，
    开发时位于 editor_utils/qtbase_zh_CN.qm。

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

    打包环境: _MEIPASS/<icon_name>
    开发环境: <editor_dir>/<icon_name>

    Args:
        editor_dir: 开发环境下编辑器所在目录 (通常传 os.path.dirname(__file__))
        icon_name: 图标文件名

    Returns:
        图标文件绝对路径 (不保证文件存在，调用者需检查)
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, icon_name)
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
