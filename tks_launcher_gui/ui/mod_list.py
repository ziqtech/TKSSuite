"""MOD 列表面板 — 显示 mods/ 目录中的 .tksmod 文件，支持启用/禁用"""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from core.mod_loader import scan_mods, ModInfo


class ModListWidget(QWidget):
    """MOD 列表面板，嵌入主窗口左侧"""

    def __init__(self, mods_dir: str = "mods", parent=None):
        super().__init__(parent)
        self._mods_dir = mods_dir
        self._mods: list[ModInfo] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 标题
        header = QLabel("MOD 列表")
        header.setProperty("class", "SectionTitle")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        # 列表
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

        # 详情
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(120)
        self._detail.setPlaceholderText("选中 MOD 查看详情")
        layout.addWidget(self._detail)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh_mods)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 初始加载
        self.refresh_mods()

    def refresh_mods(self):
        """重新扫描 mods 目录"""
        self._list.clear()
        self._mods = scan_mods(self._mods_dir)

        for mod in self._mods:
            item = QListWidgetItem()
            item.setText(f"{mod.name} v{mod.version}")
            item.setToolTip(f"ID: {mod.mod_id}\n作者: {mod.author}\n{mod.description}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if mod.enabled else Qt.Unchecked)
            self._list.addItem(item)

        self._detail.setPlainText(
            f"目录: {self._mods_dir}\n共 {len(self._mods)} 个 MOD")

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._mods):
            self._detail.setPlainText("")
            return
        mod = self._mods[row]
        lines = [
            f"名称: {mod.name}",
            f"ID: {mod.mod_id}",
            f"版本: {mod.version}",
            f"作者: {mod.author}",
            f"类型: {mod.mod_type} / {mod.mode}",
            f"加载顺序: {mod.load_order}",
            f"描述: {mod.description}",
        ]
        if mod.dependencies:
            lines.append(f"依赖: {', '.join(mod.dependencies)}")
        if mod.conflicts:
            lines.append(f"冲突: {', '.join(mod.conflicts)}")
        if mod.warpc_expand:
            lines.append(f"WarPC 扩展到: {mod.warpc_expand} 角色")
        if mod.id_ranges:
            ranges = [f"  {k}: {v.get('start',0)}-{v.get('end',0)}"
                      for k, v in mod.id_ranges.items()]
            lines.append("ID 范围:\n" + "\n".join(ranges))
        self._detail.setPlainText("\n".join(lines))

    def get_enabled_mods(self) -> list[ModInfo]:
        """获取所有勾选启用的 MOD 列表"""
        enabled = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.Checked and i < len(self._mods):
                self._mods[i].enabled = True
                enabled.append(self._mods[i])
            elif i < len(self._mods):
                self._mods[i].enabled = False
        return enabled

    def set_mods_dir(self, mods_dir: str):
        """更新 MOD 目录并刷新"""
        self._mods_dir = mods_dir
        self.refresh_mods()
