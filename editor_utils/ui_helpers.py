"""
通用 UI 工具函数 — 供所有编辑器统一使用
包含: 路径状态显示、FakeInputBox、窗口图标加载、CSV 导出等
"""
import os
import csv
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QFileDialog, QMessageBox
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
