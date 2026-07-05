"""模组信息预览面板 — 独立面板，展示当前选中模组的元数据"""
from html import escape as _html_escape

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit

from editor_utils.dock_components import create_dock
from core.mod_loader import ModInfo


class ModInfoPreviewWidget(QWidget):
    """独立的模组信息预览面板。

    标题列右对齐，使冒号在列边界对齐。订阅 ModListWidget.mod_selected 信号。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("选中模组查看详情")
        outer.addWidget(create_dock("模组信息", self._detail))

    def set_default_height(self, height: int):
        """设置预览区默认最小高度（含 DockHeader 标题栏）。"""
        height = max(height, 70)  # 含标题栏(约30) + 详情区下限(40)
        self.setMinimumHeight(height)
        self._detail.setMinimumHeight(height - 30)

    def show_mod(self, mod: ModInfo | None):
        """更新预览内容；mod 为 None 时清空。"""
        if mod is None:
            self._detail.clear()
            return

        # 构建 (标题, 值, 是否预转义HTML) 行；标题列右对齐，使冒号在列边界对齐
        rows: list[tuple[str, str, bool]] = [
            ("文件路径", mod.path, False),
            ("名称", mod.name, False),
            ("ID", mod.mod_id, False),
            ("版本", mod.version, False),
            ("作者", mod.author, False),
            ("加载顺序", str(mod.load_order), False),
            ("描述", mod.description, False),
        ]
        if mod.dependencies:
            rows.append(("依赖", ", ".join(mod.dependencies), False))
        if mod.conflicts:
            rows.append(("冲突", ", ".join(mod.conflicts), False))
        if mod.pak_contents:
            rows.append(("合集内容", f"{len(mod.pak_contents)} 个模组", False))
            rows.append(("", ", ".join(mod.pak_contents), False))
        if mod.warpc_expand:
            rows.append(("WarPC 扩展到", f"{mod.warpc_expand} 角色", False))
        if mod.id_ranges:
            ranges = "<br>".join(
                f"&nbsp;&nbsp;{_html_escape(str(k))}: "
                f"{v.get('start', 0)}-{v.get('end', 0)}"
                for k, v in mod.id_ranges.items()
            )
            rows.append(("ID 范围", ranges, True))

        body = "".join(
            f"<tr><td align='right' style='padding-right:8px'>{_html_escape(label)}:</td>"
            f"<td>{value if is_html else _html_escape(value)}</td></tr>"
            for label, value, is_html in rows
        )
        self._detail.setHtml(
            f"<table cellspacing='0' cellpadding='0'>{body}</table>"
        )
