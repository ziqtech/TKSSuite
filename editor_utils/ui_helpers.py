"""
通用 UI 工具函数 — 供所有编辑器统一使用
包含: 路径状态显示、FakeInputBox、窗口图标加载、CSV 导出等
"""
import os
import sys
import csv
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QFileDialog, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon


# ── 颜色常量 (与 editor_themes 一致) ──
COLOR_LOADED_DARK = "#55b572"
COLOR_LOADED_LIGHT = "#178a39"
COLOR_MISSING_DARK = "#e27d60"
COLOR_MISSING_LIGHT = "#c93b16"


def update_path_labels(labels_config, is_dark):
    """
    批量更新路径标签的文本和颜色
    labels_config: [(QLabel, path_or_None, display_name), ...]
    """
    for label, path, name in labels_config:
        if path and os.path.exists(path):
            label.setText(f"{name}: {path}")
            label.setProperty("status", "loaded")
        elif path:
            label.setText(f"{name}: (不存在){path}")
            label.setProperty("status", "missing")
        else:
            label.setText(f"{name}: 未加载")
            label.setProperty("status", "missing")
        label.style().unpolish(label)
        label.style().polish(label)


def make_fake_input(widget=None, line_edit=None, combo=None, button=None, stretch=True, height=28):
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
        editor_dir = os.path.dirname(widget.__class__.__module__.replace('.', os.sep))
        if not os.path.isdir(editor_dir):
            editor_dir = os.getcwd()
    ico_path = os.path.join(editor_dir, 'TKS.ico')
    if os.path.exists(ico_path):
        widget.setWindowIcon(QIcon(ico_path))


def export_csv(parent, records, columns, row_func, default_name="export.csv"):
    """
    通用 CSV 导出
    parent: 父窗口
    records: 记录列表
    columns: 列名列表
    row_func: record -> list 转换函数
    default_name: 默认文件名
    """
    fp, _ = QFileDialog.getSaveFileName(parent, "导出 CSV", default_name, "CSV (*.csv)")
    if not fp:
        return False
    try:
        with open(fp, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for rec in records:
                writer.writerow(row_func(rec))
        QMessageBox.information(parent, "导出成功", f"已导出到 {fp}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "导出失败", str(e))
        return False


def confirm_close(parent, dirty, title="未保存", text="有未保存的修改, 确定退出?"):
    """未保存确认退出对话框，返回 True 表示可以关闭"""
    if not dirty:
        return True
    return QMessageBox.question(parent, title, text,
                                QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok


def dialog_show_event(dialog):
    """弹窗 title bar 主题跟随父窗口。在 QDialog.showEvent 中调用。"""
    from editor_utils.window_theme import apply_godot_theme
    parent = dialog.parent()
    if parent:
        is_dark = getattr(parent, '_is_dark', None) or getattr(parent, 'is_dark_theme', None)
    else:
        is_dark = None
    if is_dark is None:
        is_dark = QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark
    apply_godot_theme(dialog, bool(is_dark))


def themed_messagebox(parent, icon, title, text):
    """主题化 information/about 弹窗 — title bar 跟随父窗口主题。"""
    msg = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    dialog_show_event(msg)
    return msg.exec()


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
