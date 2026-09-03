#!/usr/bin/env python3
"""
GXP 图像编辑器 — 外部独立主题版 (PySide6)
===========================================
全面适配 editor_themes 四主题 QSS（gpt-dark/gpt-light/classic-dark/classic-light）
强制剥离透明通道导出 24-bit RGB (符合游戏引擎要求)
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTranslator
from PySide6.QtGui import (
    QColor, QImage, QKeySequence, QPainter, QPixmap, QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

HAS_PIL = False
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from editor_utils.dock_components import DockHeader, create_dock
from editor_utils.lzss import (
    lzss_compress_stream as _lzss_compress_stream,
    lzss_decompress_stream as _lzss_decompress_stream,
)
from editor_utils.mod_exporter import (
    ModImportPreviewDialog, ModMetadataDialog, compute_crc32,
    generate_mod_json, get_tksmod_info, pack_tksmod, read_tksmod,
    safe_mod_filename,
)
from editor_utils.rgb565 import rgb565_to_rgba, rgba_to_rgb565
from editor_utils import theme_manager
from editor_utils.theme_switcher import toggle_theme_in_family
from editor_utils.app_shell import EditorMainWindow, run_editor
from editor_utils.version import format_title
from editor_utils.ui_helpers import confirm_close
from editor_utils.ui_helpers import set_themed_icon

# ── GXP 格式常量 ──────────────────────────────────────────
GXP_MAGIC = b"JGXP"
GXP_HEADER_SIZE = 48

# ── 本地别名: 保持向后兼容 ──
def lzss_decompress(data, target_size):
    return _lzss_decompress_stream(data, target_size)


def lzss_compress(data):
    return _lzss_compress_stream(data)


def rgb565_bytes_to_rgba(raw, w, h):
    return rgb565_to_rgba(raw, w, h)


def rgba_to_rgb565_bytes(rgba, w, h):
    return rgba_to_rgb565(rgba, w, h)


class GXPImage:
    def __init__(self):
        self.width: int = 0
        self.height: int = 0
        self.bpp: int = 16
        self.rgba: bytearray = bytearray()
        self.filepath: Optional[str] = None

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def size_str(self) -> str:
        return f"{self.width}×{self.height}"


def load_gxp(filepath: str) -> GXPImage:
    data = Path(filepath).read_bytes()
    if len(data) < GXP_HEADER_SIZE + 4:
        raise ValueError("文件太小, 不足 48 字节头")
    if data[0:4] != GXP_MAGIC:
        raise ValueError(f"无效魔数: {data[0:4]!r}")

    width = ~struct.unpack_from("<i", data, 4)[0]
    height = ~struct.unpack_from("<i", data, 8)[0]
    compressed_size = struct.unpack_from("<I", data, 12)[0]
    bpp = struct.unpack_from("<I", data, 16)[0]

    uncompressed_size = struct.unpack_from("<I", data, GXP_HEADER_SIZE)[0]
    lzss_data = data[GXP_HEADER_SIZE + 4 : GXP_HEADER_SIZE + compressed_size]

    raw_pixels = lzss_decompress(lzss_data, uncompressed_size)
    img = GXPImage()
    img.width, img.height, img.bpp, img.filepath = width, height, bpp, filepath
    img.rgba = rgb565_bytes_to_rgba(raw_pixels, width, height)
    return img

def save_gxp(img: GXPImage, filepath: str):
    raw_rgb565 = rgba_to_rgb565_bytes(bytes(img.rgba), img.width, img.height)
    compressed = lzss_compress(raw_rgb565)

    buf = bytearray()
    buf += GXP_MAGIC
    buf += struct.pack("<i", ~img.width)
    buf += struct.pack("<i", ~img.height)
    buf += struct.pack("<I", len(compressed) + 4)
    buf += struct.pack("<I", img.bpp)
    buf += bytes(28)
    buf += struct.pack("<I", len(raw_rgb565))
    buf += compressed
    Path(filepath).write_bytes(bytes(buf))

def import_image(filepath: str, target_w: int = 0, target_h: int = 0) -> GXPImage:
    pil = Image.open(filepath).convert("RGBA")
    if target_w > 0 and target_h > 0:
        pil = pil.resize((target_w, target_h), Image.LANCZOS)
    elif target_w > 0 or target_h > 0:
        ow, oh = pil.size
        if target_w > 0:
            pil = pil.resize((target_w, int(oh * (target_w / ow))), Image.LANCZOS)
        else:
            pil = pil.resize((int(ow * (target_h / oh)), target_h), Image.LANCZOS)

    img = GXPImage()
    img.width, img.height = pil.size
    img.rgba = bytearray(pil.tobytes())
    return img

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

def export_png(img: GXPImage, filepath: str):
    """导出 24-bit RGB PNG (剥离透明通道，符合游戏引擎无透明背景要求)"""
    w, h = img.width, img.height
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))

    stride_in = w * 4
    stride_out = w * 3
    raw = bytearray(h * (stride_out + 1))
    mv = memoryview(img.rgba)

    for row in range(h):
        out = row * (stride_out + 1)
        raw[out] = 0
        for col in range(w):
            in_idx = row * stride_in + col * 4
            out_idx = out + 1 + col * 3
            raw[out_idx:out_idx+3] = mv[in_idx:in_idx+3]

    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    Path(filepath).write_bytes(png)

# ═══════════════════════════════════════════════════════════
# GUI 样式与组件
# ═══════════════════════════════════════════════════════════

class EnhancedGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.editor = None

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            delta = 0.25 if event.angleDelta().y() > 0 else -0.25
            if self.editor:
                self.editor._zoom_step(delta)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.editor:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.editor._update_pixel_info(scene_pos.x(), scene_pos.y())


# ═══════════════════════════════════════════════════════════
# 主程序窗口
# ═══════════════════════════════════════════════════════════

class GXPEditor(EditorMainWindow):
    EDITOR_KEY = "gxp_editor"
    DEFAULT_SIZE = (1200, 800)

    HELP_TEXT = (
        "功能: 编辑《三国群侠传》GXP 格式图像资源\n\n"
        "特性:\n"
        "  · 导入外部图片替换游戏图像\n"
        "  · 导出为 24 位 PNG (符合游戏引擎要求)\n"
        "  · 支持 MOD 格式导入导出 (.tksmod)\n"
        "  · 深色/浅色主题切换\n\n"
        "快捷键:\n"
        "  Ctrl+I = 导入图片   Ctrl+E = 导出 PNG\n"
        "  Ctrl+0 = 原始大小   Ctrl+T = 切换主题")

    def __init__(self, filepath: Optional[str] = None):
        self._initial_path = filepath
        super().__init__()

    def _init_data(self):
        self.img: Optional[GXPImage] = None
        self._pixmap_item = None
        self._zoom = 1.0
        self._dirty = False  # 导入置位, 打开/新建/保存后复位 (closeEvent 退出确认)

    def _build_ui(self):
        self._setup_menu()
        self._setup_ui()

    def _after_build(self):
        self._apply_theme()

        if self._initial_path and os.path.exists(self._initial_path):
            self._open(self._initial_path)
        else:
            self._new_empty()

    def _create_dock(self, title, widget_content, header_layout=None):
        """Dock 面板包裹 — 委托给 editor_utils.dock_components"""
        return create_dock(title, widget_content, header_layout)

    def closeEvent(self, event):
        if not confirm_close(self, self._dirty):
            event.ignore()
        else:
            event.accept()

    def _on_theme_applied(self, theme_id):
        spec = theme_manager.THEMES[theme_id]
        if spec.family == 'classic':
            scene_bg = QColor(32, 37, 49) if spec.is_dark else QColor(224, 228, 232)
        else:
            scene_bg = QColor("#212121") if spec.is_dark else QColor("#f7f7f8")  # 主题感知: 深浅两档 (与 QSS 底色同值)
        if hasattr(self, '_scene') and self._scene is not None:
            self._scene.setBackgroundBrush(scene_bg)

        # 强制刷新状态栏以更新 QSS 样式 (依据 tkt_editor 经验)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.style().unpolish(status_bar)
            status_bar.style().polish(status_bar)
        for label in [getattr(self, a, None)
                      for a in ('_status_left', '_status_size', '_status_pixel', '_status_sep')]:
            if label:
                label.style().unpolish(label)
                label.style().polish(label)

    def _toggle_theme(self):
        toggle_theme_in_family(self)
        self.statusBar().showMessage(
            f"已切换到{theme_manager.display_name(self._theme_id)}主题", 2000)

    def _setup_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("新建(&N)", QKeySequence("Ctrl+N"), self._new_empty)
        fm.addAction("打开(&O)", QKeySequence("Ctrl+O"), self._open_dlg)
        fm.addAction("保存(&S)", QKeySequence("Ctrl+S"), self._save)
        fm.addAction("另存为(&A)...", QKeySequence("Ctrl+Shift+S"), self._save_as)
        fm.addSeparator()
        fm.addAction("导入图片(&I)...", QKeySequence("Ctrl+I"), self._import_dlg)
        fm.addAction("导出 24位 PNG(&E)...", QKeySequence("Ctrl+E"), self._export_dlg)
        fm.addSeparator()
        fm.addAction("导出为 MOD (.tksmod)…", self._export_tksmod)
        fm.addAction("导入 MOD (.tksmod)…", self._import_tksmod)
        fm.addSeparator()
        fm.addAction("退出(&X)", QKeySequence("Alt+F4"), self.close)

        vm = mb.addMenu("视图(&V)")
        vm.addAction("原始大小 100%(&1)", QKeySequence("Ctrl+0"), lambda: self._set_zoom(1.0))
        vm.addAction("适合窗口(&F)", self._fit_to_window)
        vm.addSeparator()
        self.add_theme_submenu(vm)
        vm.addAction("快速切换主题(&T)", self._toggle_theme)

        # 帮助菜单
        self.add_help_menu(mb)

    def _setup_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        layout = QVBoxLayout(cw)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        layout.addWidget(splitter, 1)

        # ---------------- 左侧控制面板 ----------------
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        info_w = QWidget()
        info_l = QVBoxLayout(info_w)
        self._info_label = QLabel("无图像")
        self._info_label.setAlignment(Qt.AlignCenter)
        info_l.addWidget(self._info_label)
        left_layout.addWidget(self._create_dock("GXP 图像属性", info_w))

        ops_w = QWidget()
        ops_l = QVBoxLayout(ops_w)

        b1 = QPushButton("打开 GXP")
        b1.clicked.connect(self._open_dlg)
        ops_l.addWidget(b1)
        b2 = QPushButton("保存 / 另存为")
        b2.clicked.connect(self._save)
        ops_l.addWidget(b2)

        fline = QFrame()
        fline.setFrameShape(QFrame.HLine)
        fline.setProperty("class", "SepLine")
        ops_l.addWidget(fline)

        b3 = QPushButton("导入外部图片")
        b3.clicked.connect(self._import_dlg)
        ops_l.addWidget(b3)
        b4 = QPushButton("导出 24位 PNG")
        b4.clicked.connect(self._export_dlg)
        ops_l.addWidget(b4)

        left_layout.addWidget(self._create_dock("文件与资产操作", ops_w))
        left_layout.addStretch()
        splitter.addWidget(left_panel)

        # ---------------- 右侧画布视口 ----------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        tb_layout = QHBoxLayout()
        tb_layout.setContentsMargins(6, 2, 6, 2)
        tb_layout.setSpacing(6)
        btn_zout = QPushButton("")
        set_themed_icon(btn_zout, "minus")
        btn_zout.setProperty("class", "CompactBtn")
        btn_zout.clicked.connect(partial(self._zoom_step, -0.25))
        self._zoom_label = QLabel("100%")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(50)
        btn_zin = QPushButton("新增")
        btn_zin.setProperty("class", "CompactBtn")
        btn_zin.clicked.connect(partial(self._zoom_step, 0.25))
        btn_fit = QPushButton("适应窗口")
        btn_fit.setProperty("class", "CompactBtn")
        btn_fit.clicked.connect(self._fit_to_window)
        btn_theme = QPushButton("切换主题")
        btn_theme.setProperty("class", "CompactBtn")
        btn_theme.clicked.connect(self._toggle_theme)
        tb_layout.addWidget(btn_zout)
        tb_layout.addWidget(self._zoom_label)
        tb_layout.addWidget(btn_zin)
        tb_layout.addSpacing(12)
        tb_layout.addWidget(btn_fit)
        tb_layout.addWidget(btn_theme)
        tb_layout.addStretch()

        self._scene = QGraphicsScene()
        self._canvas = EnhancedGraphicsView(self._scene)
        self._canvas.editor = self

        # 工具栏容器
        tb_widget = QWidget()
        tb_widget.setLayout(tb_layout)
        tb_widget.setFixedHeight(32)
        right_layout.addWidget(tb_widget)
        right_layout.addWidget(self._canvas, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([280, 920])

        # ---------------- 状态栏 ----------------
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)  # 移除右下角大小调整手柄

        self._status_left = QLabel(" 就绪")
        self._status_left.setObjectName("StatusLabel")
        sb.addWidget(self._status_left, 1)

        self._status_pixel = QLabel("")
        self._status_pixel.setObjectName("StatusPixel")
        sb.addPermanentWidget(self._status_pixel)

        self._status_sep = QLabel(" │ ")
        self._status_sep.setObjectName("StatusSep")
        sb.addPermanentWidget(self._status_sep)

        self._status_size = QLabel("0×0")
        self._status_size.setObjectName("StatusInfo")
        sb.addPermanentWidget(self._status_size)

    def _update_pixel_info(self, x: float, y: float):
        if not self.img or not self._pixmap_item:
            self._status_pixel.setText("")
            return

        z = self._zoom
        px, py = int(x / z), int(y / z)
        w, h = self.img.width, self.img.height

        if 0 <= px < w and 0 <= py < h:
            idx = (py * w + px) * 4
            r, g, b, _ = self.img.rgba[idx:idx + 4]
            r5, g6, b5 = (r >> 3) & 0x1F, (g >> 2) & 0x3F, (b >> 3) & 0x1F
            val565 = (r5 << 11) | (g6 << 5) | b5
            self._status_pixel.setText(f"Pos:({px}, {py})  RGB:({r},{g},{b})  HEX565: 0x{val565:04X}")
        else:
            self._status_pixel.setText("")

    # ── 文件调度 ──────────────────────────────────────────

    def _new_empty(self):
        self.img = GXPImage()
        self.img.width, self.img.height = 640, 480
        self.img.rgba = bytearray(640 * 480 * 4)
        self._zoom = 1.0
        self._dirty = False
        self._refresh_view()
        self._status_left.setText(" 新建空白画布 640×480")
        self._info_label.setText("尺寸: 640×480\n格式: RGB565\n状态: 内存新建")
        self.setWindowTitle(format_title("gxp_editor", "[新建]"))

    def _open_dlg(self):
        p, _ = QFileDialog.getOpenFileName(self, "打开 GXP", "", "GXP (*.gxp *.GXP);;All (*.*)")
        if p:
            self._open(p)

    def _open(self, p: str):
        try:
            self._status_left.setText(f" 加载中: {Path(p).name} ...")
            QApplication.processEvents()
            self.img = load_gxp(p)
            self._dirty = False
            self._fit_to_window()
            self._refresh_view()
            self._status_left.setText(f" 已加载: {Path(p).name}  |  {os.path.getsize(p)/1024:.1f} KB")
            self._info_label.setText(f"尺寸: {self.img.size_str}\n格式: RGB{self.img.bpp}\n文件: {os.path.getsize(p)/1024:.1f} KB")
            self.setWindowTitle(format_title("gxp_editor", os.path.basename(p)))
        except Exception as e:
            QMessageBox.critical(self, "数据载入溃散", str(e))
            self._status_left.setText(" 打开失败")

    def _save(self):
        if not self.img: return
        if self.img.filepath:
            self._do_save(self.img.filepath)
        else:
            self._save_as()

    def _save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "打包输出 GXP", "", "GXP (*.gxp)")
        if p:
            self._do_save(p)

    def _do_save(self, p: str):
        try:
            self._status_left.setText(" 数据流压缩中...")
            QApplication.processEvents()
            save_gxp(self.img, p)
            self.img.filepath = p
            self._dirty = False
            size_kb = os.path.getsize(p) / 1024
            self._status_left.setText(f" 已保存: {Path(p).name}  |  {size_kb:.1f} KB")
            self.setWindowTitle(format_title("gxp_editor", os.path.basename(p)))
        except Exception as e:
            QMessageBox.critical(self, "构写失败", str(e))

    def _import_dlg(self):
        if not HAS_PIL:
            QMessageBox.warning(self, "缺少依赖", "外部图像导入功能需要安装 Pillow 库。\npip install Pillow")
            return
        p, _ = QFileDialog.getOpenFileName(self, "导入参考底图", "", "图片 (*.png *.bmp *.jpg *.jpeg);;All (*.*)")
        if not p: return
        try:
            self._status_left.setText(" 图像映射导入中...")
            QApplication.processEvents()
            self.img = import_image(p, self.img.width if self.img and self.img.width > 0 else 0,
                                       self.img.height if self.img and self.img.height > 0 else 0)
            self._fit_to_window()
            self._refresh_view()
            self._dirty = True
            self._status_left.setText(f" 已导入外部资产: {Path(p).name}")
            self._info_label.setText(f"尺寸: {self.img.size_str}\n格式: RGB{self.img.bpp}\n来源: 外部图片映射")
            self.setWindowTitle(format_title("gxp_editor", f"[资产导入] {os.path.basename(p)}"))
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _export_dlg(self):
        if not self.img or self.img.width <= 0: return
        p, _ = QFileDialog.getSaveFileName(self, "导出无透明 24-bit PNG", "", "PNG (*.png)")
        if not p: return
        try:
            export_png(self.img, p)
            self._status_left.setText(f" 已成功剥离导出: {Path(p).name}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod(self):
        """导出当前 GXP 为 .tksmod 资源替换 MOD"""
        if not self.img or not self.img.filepath:
            QMessageBox.information(self, "提示", "请先打开 GXP 文件")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        target_name = os.path.basename(self.img.filepath)
        mod_json = generate_mod_json(metadata, [],
            resources=[{"file": f"resources/{target_name}", "target": target_name}])
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, {}, resource_files={f"resources/{target_name}": self.img.filepath})
            self._status_left.setText(f" 已导出 MOD: {Path(fp).name}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到 GXP 编辑器 (资源替换模式)"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        # GXP 编辑器查找资源文件中的 .gxp/.GXP 文件
        resources = info.get("resources", [])
        gxp_resources = [r for r in resources
                         if r.get("target", "").upper().endswith(".GXP")]
        if not gxp_resources:
            QMessageBox.warning(self, "不兼容", "此 MOD 不包含 GXP 资源文件\n\n"
                f"包含的数据: {', '.join(info.get('targets', []))}\n"
                f"资源: {', '.join(r.get('target','') for r in resources)}")
            return


        dlg = ModImportPreviewDialog(self, info)
        if dlg.exec() != QDialog.Accepted: return

        # 从 ZIP 中提取 GXP 资源并加载
        import tempfile
        import zipfile
        res = gxp_resources[0]
        internal_path = res.get("file", "")
        target_name = res.get("target", "")

        try:
            with zipfile.ZipFile(fp, 'r') as zf:
                if internal_path not in zf.namelist():
                    QMessageBox.warning(self, "导入失败",
                        f"MOD 中找不到资源: {internal_path}")
                    return
                tmp = tempfile.mktemp(suffix='.gxp')
                with zf.open(internal_path) as src:
                    Path(tmp).write_bytes(src.read())
                self.img = load_gxp(tmp)
                self.img.filepath = None
                os.remove(tmp)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"加载 GXP 失败: {e}")
            return

        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._refresh_view()
        self._dirty = True
        self._status_left.setText(
            f" 已导入 MOD: {info.get('name', '')} | {target_name}")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"资源: {target_name}\n"
            f"尺寸: {self.img.width}×{self.img.height}\n\n"
            f"您现在可以继续编辑并重新导出。")

    # ── 视图调度 ──────────────────────────────────────────

    def _refresh_view(self):
        self._scene.clear()
        if not self.img or self.img.width <= 0: return

        w, h = self.img.width, self.img.height
        sw, sh = int(w * self._zoom), int(h * self._zoom)

        qimg = QImage(bytes(self.img.rgba), w, h, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)

        if self._zoom != 1.0:
            pixmap = pixmap.scaled(max(1, sw), max(1, sh), Qt.IgnoreAspectRatio, Qt.FastTransformation)

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(0, 0, sw, sh)

        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._status_size.setText(f"{self.img.size_str} ")

    def _set_zoom(self, z: float):
        self._zoom = max(0.5, min(3.0, z))
        self._refresh_view()

    def _zoom_step(self, delta: float):
        self._set_zoom(self._zoom + delta)

    def _fit_to_window(self):
        if not self.img or self.img.width <= 0: return
        view_w = self._canvas.viewport().width() - 20 or 800
        view_h = self._canvas.viewport().height() - 20 or 600
        z = min(1.0, view_w / self.img.width, view_h / self.img.height)
        self._set_zoom(max(0.5, z))


def main():
    run_editor(GXPEditor, filepath=sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    main()
