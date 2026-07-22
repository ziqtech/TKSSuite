"""
通用 UI 工具函数 — 供所有编辑器统一使用
包含: 路径状态显示、FakeInputBox、窗口图标加载等
"""
import os
import sys
from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QWidget)


# ── 颜色常量 (与 editor_themes 一致) ──
COLOR_LOADED_DARK = "#55b572"
COLOR_LOADED_LIGHT = "#178a39"
COLOR_MISSING_DARK = "#e27d60"
COLOR_MISSING_LIGHT = "#c93b16"


class NoWheelComboBox(QComboBox):
    """禁用鼠标滚轮切换值的下拉框。

    普通 QComboBox 在 QScrollArea 等可滚动容器中, 鼠标滚轮悬停即会误触
    切换当前选项。重写 wheelEvent 调用 event.ignore(), 使滚轮事件向上冒泡
    交给父级滚动区域 (滚动页面), 而非改变当前选中项。

    所有编辑器统一使用本类替代 QComboBox, 以获得一致的滚轮行为。
    """

    def wheelEvent(self, event):
        event.ignore()


def update_path_labels(labels_config, is_dark):
    """
    批量更新路径标签的加载状态与颜色 (仅显示状态, 完整路径见鼠标悬浮提示)
    labels_config: [(QLabel, path_or_None, display_name), ...]
    """
    for label, path, name in labels_config:
        if path and os.path.exists(path):
            label.setText(f"{name}: 已加载")
            label.setProperty("status", "loaded")
            label.setToolTip(os.path.normpath(path))
        elif path:
            label.setText(f"{name}: 文件缺失")
            label.setProperty("status", "missing")
            label.setToolTip(os.path.normpath(path))
        else:
            label.setText(f"{name}: 未加载")
            label.setProperty("status", "missing")
            label.setToolTip("")
        label.style().unpolish(label)
        label.style().polish(label)


def make_fake_input(widget=None, line_edit=None, combo=None,
                    button=None, stretch=True, height=28):
    """创建 FakeInputBox 外壳 (内凹输入框风格)
    用法1: make_fake_input(some_widget) — 单控件
    用法2: make_fake_input(line_edit=le, combo=cb, button=btn) — 多控件组合
    """
    box = QFrame()
    box.setObjectName("FakeInputBox")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)
    if widget is not None:
        h.addWidget(widget)
    else:
        if line_edit:
            h.addWidget(line_edit)
        if combo:
            h.addWidget(combo, 1)
        if button:
            h.addWidget(button)
        if stretch:
            h.addStretch()
    box.setFixedHeight(height)
    return box


def load_window_icon(widget, editor_dir=None):
    """加载 TKS.ico 窗口图标"""
    if editor_dir is None:
        editor_dir = os.path.dirname(
            widget.__class__.__module__.replace('.', os.sep))
        if not os.path.isdir(editor_dir):
            editor_dir = os.getcwd()
    ico_path = os.path.join(editor_dir, 'TKS.ico')
    if os.path.exists(ico_path):
        widget.setWindowIcon(QIcon(ico_path))



def confirm_close(parent, dirty, title="未保存", text="有未保存的修改, 确定退出?"):
    """未保存确认退出对话框，返回 True 表示可以关闭"""
    if not dirty:
        return True
    buttons = QMessageBox.Ok | QMessageBox.Cancel
    return QMessageBox.question(parent, title, text, buttons) == QMessageBox.Ok


def themed_messagebox(parent, icon, title, text):
    """信息弹窗 (标题栏主题由全局过滤器自动处理)。"""
    msg = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    return msg.exec()


class _DialogThemeFilter(QObject):
    """全局事件过滤器: 自动为所有弹出的顶层窗口应用 DWM 标题栏主题。

    由 install_dialog_theme_filter(app) 安装到 QApplication 上,
    捕获所有 QWidget 的 Show 事件, 对顶层窗口 (QDialog/QMessageBox/
    QInputDialog/QFileDialog/QColorDialog) 调用 apply_godot_theme,
    使其标题栏跟随编辑器主题 (深色/浅色), 无需在每个弹窗处手动调用。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app

    def _resolve_is_dark(self, widget):
        """从父窗口链查找 _is_dark / is_dark_theme, 回退到系统主题。"""
        # 1. 沿父窗口链查找 (主窗口/QMainWindow 通常带 _is_dark)
        p = widget.parentWidget() or widget.parent()
        while p is not None:
            for attr in ('_is_dark', 'is_dark_theme', '_dark_mode'):
                v = getattr(p, attr, None)
                if v is not None:
                    return bool(v)
            p = getattr(p, 'parentWidget', lambda: None)() or getattr(p, 'parent', lambda: None)()
        # 2. 扫描所有顶层窗口 (找任意一个带 _is_dark 的主窗口)
        for w in self._app.topLevelWidgets():
            for attr in ('_is_dark', 'is_dark_theme', '_dark_mode'):
                v = getattr(w, attr, None)
                if v is not None:
                    return bool(v)
        # 3. 回退到系统颜色方案
        return self._app.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Show
                and isinstance(obj, QWidget)
                and obj.isWindow()):
            # 跳过无标题栏的弹出控件 (QMenu/QToolTip 由 QSS 处理外观)
            if not isinstance(obj, (QMenu,)):
                try:
                    from editor_utils.window_theme import apply_godot_theme
                    apply_godot_theme(obj, self._resolve_is_dark(obj))
                except Exception:
                    pass  # 非 win32 或 winId 不可用, 静默跳过
        return False


def install_dialog_theme_filter(app):
    """安装全局事件过滤器, 自动为所有弹出的顶层窗口
    (QDialog/QMessageBox/QInputDialog/QFileDialog/QColorDialog) 应用 DWM 标题栏主题。

    一次安装, 永久生效, 无需在每次创建弹窗时手动调用。
    在每个编辑器的 main() 中 QApplication 创建后调用一次即可::

        app = QApplication(sys.argv)
        install_dialog_theme_filter(app)
    """
    app._dialog_theme_filter = _DialogThemeFilter(app)
    app.installEventFilter(app._dialog_theme_filter)


def resolve_config_path(config_filename):
    """解析 configs/ 目录下配置文件的绝对路径。

    支持两种运行模式:
      1. 开发环境 (脚本直接运行): 从 ui_helpers.py 所在目录 (editor_utils/)
         向上一级 ()，再进入 configs/ 目录查找。
      2. 打包环境 (Nuitka/PyInstaller): 通过 runtime_bootstrap.get_app_dir()
         获取 exe 所在目录，在相邻的 configs/ 子目录中查找。

    Args:
        config_filename: 配置文件名 (如 'equip_type_labels.json')

    Returns:
        配置文件的绝对路径，找不到时返回 None。
    """
    # ── 方法 1: 基于 __file__ 推算 (开发环境) ──
    try:
        editor_utils_dir = os.path.dirname(os.path.abspath(__file__))
        ai_programs_dir = os.path.dirname(editor_utils_dir)  # 
        path = os.path.join(ai_programs_dir, 'configs', config_filename)
        if os.path.isfile(path):
            return path
    except (NameError, OSError):
        pass  # __file__ 在某些打包环境下不可用

    # ── 方法 2: exe 相邻 configs/ 目录 (打包环境) ──
    try:
        from editor_utils.runtime_bootstrap import get_app_dir
        exe_dir = get_app_dir()
        path = os.path.join(exe_dir, 'configs', config_filename)
        if os.path.isfile(path):
            return path
    except (ImportError, OSError):
        pass

    # ── 方法 3: 当前工作目录 ──
    cwd_path = os.path.join(os.getcwd(), 'configs', config_filename)
    if os.path.isfile(cwd_path):
        return cwd_path

    return None
