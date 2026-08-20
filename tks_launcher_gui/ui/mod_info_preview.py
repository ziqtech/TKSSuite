"""模组信息预览面板 — 独立面板，展示当前选中模组的元数据及预览图"""
from html import escape as _html_escape

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QPixmap, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from core.mod_loader import ModInfo, collect_pak_changed_targets
from editor_utils.dock_components import create_dock
from editor_utils.mod_exporter import extract_preview_image
from ui.image_preview_dialog import ImagePreviewDialog

# 预览缩略图在文档中的固定显示尺寸 (原图按自身比例缩放至此框; 可按需调整)
_PREVIEW_BOX = QSize(200, 150)
# 文档内图片资源 URL 与“打开大图”锚点 URL
_IMG_URL = "modpreview://thumb"
_OPEN_URL = "modpreview://open"


class ModInfoPreviewWidget(QWidget):
    """独立的模组信息预览面板。

    图文混排：预览图浮动于右上角，模组信息文字自动环绕。
    订阅 ModListWidget.mod_selected 信号。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 图文混排: 单个富文本浏览器, 预览图浮动到右上角, 文字自动环绕
        self._raw_pixmap: QPixmap | None = None
        self._detail = QTextBrowser()
        self._detail.setPlaceholderText("选中模组查看详情")
        self._detail.setOpenLinks(False)  # 点击图片锚点不导航, 交由我们处理
        self._detail.document().setDefaultStyleSheet("a { text-decoration: none; }")
        self._detail.anchorClicked.connect(self._on_anchor_clicked)

        # body_margins 内收: 详情文档避开 DockBody 圆角, 融入卡片表面 (样式见主题 QSS)
        outer.addWidget(create_dock("模组信息", self._detail,
                                    body_margins=(8, 4, 8, 8)))

    def set_default_height(self, height: int):
        """设置预览区默认最小高度（含 DockHeader 标题栏）。"""
        height = max(height, 70)
        self.setMinimumHeight(height)

    def show_mod(self, mod: ModInfo | None):
        """更新预览内容；mod 为 None 时清空。"""
        if mod is None:
            self._raw_pixmap = None
            self._detail.clear()
            return

        # 载入预览图 (原图保留供点击看大图), 稍后作为浮动图片嵌入富文本
        self._raw_pixmap = None
        if mod.preview_image:
            img_data = extract_preview_image(mod.path)
            if img_data:
                pm = QPixmap()
                pm.loadFromData(img_data)
                if not pm.isNull():
                    self._raw_pixmap = pm

        # 构建 (标题, 值, 是否预转义HTML) 行；标题列右对齐，使冒号在列边界对齐
        rows: list[tuple[str, str, bool]] = [
            ("文件路径", mod.path, False),
            ("名称", mod.name, False),
            ("ID", mod.mod_id, False),
            ("版本", mod.version, False),
            ("作者", mod.author, False),
            ("加载顺序", str(mod.load_order), False),
            ("描述", mod.description, False),
            ("分类", f"{mod.category or '未分类'}（自动识别）" if mod.inferred_metadata else mod.category or "未分类", False),
            ("标签", ", ".join(mod.tags) if mod.tags else "未声明", False),
        ]
        compat = mod.compatibility.get("compatible")
        compat_text = ("作者声明支持" if compat is True else
                       "作者声明不支持" if compat is False else "作者未声明")
        rows.append(("兼容模式", compat_text, False))
        if mod.requires_features:
            rows.append(("依赖游戏功能", ", ".join(mod.requires_features), False))
        if mod.notes:
            rows.append(("兼容说明", mod.notes, False))
        # 模组改动的游戏文件 (components/resources 的 target)，去重保序
        # .tksmodpak 合集：汇总内含各 .tksmod 的改动文件
        if mod.pak_contents:
            changed_files = collect_pak_changed_targets(mod.path)
        else:
            changed_files = []
            _seen_targets: set[str] = set()
            for entry in list(mod.components) + list(mod.resources):
                target = (entry.get("target") or "").strip()
                if target and target not in _seen_targets:
                    _seen_targets.add(target)
                    changed_files.append(target)
        if changed_files:
            files_html = "<br>".join(
                f"&nbsp;&nbsp;{_html_escape(t)}" for t in changed_files
            )
            rows.append(("改动文件", f"{len(changed_files)} 个", False))
            rows.append(("", files_html, True))
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
        if mod.config_files:
            cfg_names = ", ".join(sorted(mod.config_files.keys()))
            rows.append(("携带配置", f"{cfg_names} (优先级最高)", False))

        # 预览图浮动到右上角, 信息文字采用流式排版以便环绕图片 (图文混排)
        img_html = self._build_floated_image_html()
        lines = []
        for label, value, is_html in rows:
            val = value if is_html else _html_escape(value)
            lines.append(f"<b>{_html_escape(label)}:</b> {val}" if label else val)
        self._detail.setHtml(img_html + "<br>".join(lines))

    def _build_floated_image_html(self) -> str:
        """注册预览图为文档资源, 返回浮动到右上角的 <img> HTML (无图则空串)。"""
        pm = self._raw_pixmap
        if pm is None or pm.isNull():
            return ""
        scaled = pm.scaled(_PREVIEW_BOX, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        self._detail.document().addResource(
            QTextDocument.ImageResource, QUrl(_IMG_URL), scaled)
        return (
            f'<a href="{_OPEN_URL}"><img src="{_IMG_URL}" '
            f'width="{scaled.width()}" height="{scaled.height()}" '
            f'style="float:right; margin-left:8px; margin-bottom:6px;"></a>'
        )

    def _on_anchor_clicked(self, url):
        """点击预览图(锚点)时打开可缩放大图。"""
        if url.toString() == _OPEN_URL:
            self._open_preview_dialog()

    def _open_preview_dialog(self):
        """点击缩略图: 用原始分辨率打开可缩放的大图预览。"""
        pm = self._raw_pixmap
        if pm is None or pm.isNull():
            return
        dlg = ImagePreviewDialog(pm, title="模组预览图", parent=self.window())
        dlg.exec()
