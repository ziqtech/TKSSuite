"""模组信息预览面板 — 独立面板，展示当前选中模组的元数据及预览图"""
from html import escape as _html_escape

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel, QSizePolicy, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from core.mod_loader import ModInfo
from editor_utils.dock_components import create_dock
from editor_utils.mod_exporter import extract_preview_image


class _AspectLabel(QLabel):
    """保持 4:3 宽高比的 QLabel，用于预览图显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("QLabel { background: #1a1a1a; }")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(80)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w: int) -> int:
        # 4:3 → 高 = 宽 × 3/4
        return int(w * 3 / 4)

    def sizeHint(self) -> QSize:
        w = self.width() or 160
        return QSize(w, self.heightForWidth(w))


class ModInfoPreviewWidget(QWidget):
    """独立的模组信息预览面板。

    左右布局：左侧文字信息，右侧预览图（4:3）。
    订阅 ModListWidget.mod_selected 信号。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左侧：文字信息
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("选中模组查看详情")

        # 右侧：预览图（4:3）
        self._lbl_preview = _AspectLabel()
        self._lbl_preview.hide()

        # 水平分割器：文字在左，预览图在右
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._detail)
        self._splitter.addWidget(self._lbl_preview)
        self._splitter.setStretchFactor(0, 1)  # 文字区可伸缩
        self._splitter.setStretchFactor(1, 0)  # 预览图区按 sizeHint

        outer.addWidget(create_dock("模组信息", self._splitter))

    def set_default_height(self, height: int):
        """设置预览区默认最小高度（含 DockHeader 标题栏）。"""
        height = max(height, 70)
        self.setMinimumHeight(height)

    def show_mod(self, mod: ModInfo | None):
        """更新预览内容；mod 为 None 时清空。"""
        if mod is None:
            self._detail.clear()
            self._lbl_preview.hide()
            return

        # 显示预览图
        if mod.preview_image:
            img_data = extract_preview_image(mod.path)
            if img_data:
                pm = QPixmap()
                pm.loadFromData(img_data)
                if not pm.isNull():
                    self._raw_pixmap = pm  # 保留原始图，resize 时重新缩放
                    self._update_preview_pixmap()
                    self._lbl_preview.show()
                else:
                    self._lbl_preview.hide()
            else:
                self._lbl_preview.hide()
        else:
            self._lbl_preview.hide()

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

    def _update_preview_pixmap(self):
        """根据当前 label 高度重算宽度（4:3），再缩放原始图片。"""
        pm = getattr(self, '_raw_pixmap', None)
        if pm is None or pm.isNull():
            return
        h = self._lbl_preview.height() or 120
        w = int(h * 4 / 3)  # 4:3
        self._lbl_preview.setFixedWidth(w)
        scaled = pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl_preview.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口大小变化时重新缩放预览图
        if self._lbl_preview.isVisible():
            self._update_preview_pixmap()
