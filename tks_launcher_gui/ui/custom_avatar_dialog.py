"""自定义头像对话框 — 上传图片、1:1裁剪、预览、生成tksmod"""
import os
import sys
import struct
import zipfile
import json
import tempfile

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSizeF
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QPen, QBrush, QFont,
)

from PIL import Image

from editor_utils.mod_exporter import (
    pack_tksmod, generate_mod_json, build_block_diff_json,
    generate_short_uuid,
)

import base64

# MOD 常量
MOD_FILENAME = "[美化] 自定义头像.tksmod"
MOD_NAME = "[美化] 自定义头像"
MOD_AUTHOR = "玩家自定义"
MOD_DESC = "TKS子青启动器制作自定义头像"
MOD_LOAD_ORDER = 800
SCREEN_W = 640


# ═══════════════════════════════════════════════════════════════
# JVG 编码辅助（复用 jvg_editor_v2.py 逻辑）
# ═══════════════════════════════════════════════════════════════

def _encode_rle_game(pixels: bytes, alpha: bytes, w: int, h: int,
                     screen_w: int = SCREEN_W):
    """JVG RLE 编码 — 与 jvg_editor_v2._encode_rle_game 相同"""
    buf = bytearray()
    pair_count = 0
    pending = 0
    first = True
    for row in range(h - 1, -1, -1):
        if not first:
            pending += screen_w - w
        first = False
        col = w - 1
        while col >= 0:
            t0 = col
            while col >= 0 and alpha[row * w + col] == 0:
                col -= 1
            pending += t0 - col
            if col < 0:
                break
            while pending > 0xFFFF:
                buf += struct.pack("<HH", 0xFFFF, 0)
                pair_count += 1
                pending -= 0xFFFF
            run = bytearray()
            while col >= 0 and alpha[row * w + col] != 0 and len(run) < 0xFFFF:
                run.append(pixels[row * w + col])
                col -= 1
            buf += struct.pack("<HH", pending, len(run))
            buf += bytes(run)
            pair_count += 1
            pending = 0
    return bytes(buf), pair_count


def _pil_to_indexed(img: Image.Image):
    """将 RGBA PIL Image 量化为 8-bit 索引色 + RGB565 调色板。

    返回 (pixels_bytes, alpha_bytes, palette_rgb565_list, width, height)
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    w, h = img.size
    a_band = img.getchannel('A')
    alpha_data = a_band.tobytes()
    alpha = bytes(255 if b >= 128 else 0 for b in alpha_data)

    bg = Image.new('RGB', (w, h), (0, 0, 0))
    rgb = Image.composite(
        img.convert('RGB'), bg,
        img.getchannel('A').point(lambda x: 255 if x >= 128 else 0),
    )
    solid = sum(1 for b in alpha_data if b >= 128)
    n_colors = min(255, max(1, solid)) if solid > 0 else 1
    q = rgb.quantize(n_colors, method=Image.Quantize.MEDIANCUT, dither=0)
    raw_pal = q.getpalette() or [0] * 768

    pal_rgb565 = []
    for i in range(256):
        r = raw_pal[i * 3] if i * 3 + 2 < len(raw_pal) else 0
        g = raw_pal[i * 3 + 1] if i * 3 + 1 < len(raw_pal) else 0
        b = raw_pal[i * 3 + 2] if i * 3 + 2 < len(raw_pal) else 0
        pal_rgb565.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))

    idx_data = bytearray(q.tobytes())
    for i in range(w * h):
        if alpha[i] == 0:
            idx_data[i] = 0

    return bytes(idx_data), alpha, pal_rgb565, w, h


def _build_jvm_block(pil_img: Image.Image, target_size: int) -> bytes:
    """从 PIL Image 构建单个 @JVM 块二进制数据（1帧）。"""
    resized = pil_img.resize((target_size, target_size), Image.LANCZOS)
    pixels, alpha, pal_rgb565, w, h = _pil_to_indexed(resized)
    encoded_data, pair_count = _encode_rle_game(pixels, alpha, w, h)

    x_max = (w - 1) & 0xFFFF
    y_max = (h - 1) & 0xFFFF
    # row_count 必须为实际 RLE pair 数，否则游戏渲染可能异常
    meta = struct.pack("<8H", x_max, y_max, w, h, 0, 0, 0, pair_count & 0xFFFF)
    frame_data = meta + encoded_data

    buf = bytearray()
    buf += b'@JVM'
    buf += struct.pack('<I', 1)               # sprite_count
    buf += struct.pack('<I', 0)               # reserved
    buf += struct.pack('<I', len(frame_data))  # data_size
    buf += bytes(16)                           # header_reserved
    buf += struct.pack('<I', 0)                # offset[0]
    buf += struct.pack('<I', len(frame_data))  # offset[1]
    for e in pal_rgb565:
        buf += struct.pack('<H', e & 0xFFFF)
    buf += frame_data
    return bytes(buf)


# ═══════════════════════════════════════════════════════════════
# 裁剪控件 — 1:1 比例裁剪
# ═══════════════════════════════════════════════════════════════

class CropWidget(QWidget):
    """图片裁剪控件，锁定 1:1 比例。

    显示完整图片，叠加一个可拖动/缩放的 1:1 裁剪矩形。
    裁剪区域外半透明遮罩。
    """

    _HANDLE_SIZE = 8
    _MIN_CROP = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._crop_rect = QRectF()
        self._dragging = False
        self._drag_start = QPointF()
        self._drag_crop_start = QRectF()
        self._resize_handle = -1
        self._display_rect = QRectF()

    def set_image(self, pixmap: QPixmap):
        self._pixmap = pixmap
        if not pixmap or pixmap.isNull():
            return
        img_w, img_h = pixmap.width(), pixmap.height()
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            w, h = 400, 400
        scale = min(w / img_w, h / img_h)
        dw, dh = int(img_w * scale), int(img_h * scale)
        crop_size = int(min(dw, dh) * 0.8)
        cx = (dw - crop_size) / 2 + (w - dw) / 2
        cy = (dh - crop_size) / 2 + (h - dh) / 2
        self._crop_rect = QRectF(cx, cy, crop_size, crop_size)
        self._recalc_display_rect()
        self._clamp_crop_rect()
        self.update()

    def _recalc_display_rect(self):
        if self._pixmap and not self._pixmap.isNull():
            w, h = self.width(), self.height()
            scale = min(w / self._pixmap.width(), h / self._pixmap.height())
            dw = int(self._pixmap.width() * scale)
            dh = int(self._pixmap.height() * scale)
            self._display_rect = QRectF((w - dw) / 2, (h - dh) / 2, dw, dh)
        else:
            self._display_rect = QRectF()

    def _clamp_crop_rect(self):
        dr = self._display_rect
        if not dr.isValid():
            return
        r = self._crop_rect
        size = max(self._MIN_CROP, min(r.width(), r.height(), dr.width(), dr.height()))
        x = max(dr.left(), min(r.left(), dr.right() - size))
        y = max(dr.top(), min(r.top(), dr.bottom() - size))
        self._crop_rect = QRectF(x, y, size, size)

    def sizeHint(self):
        return self._display_rect.size().toSize() if self._display_rect.isValid() else super().sizeHint()

    # ── 鼠标事件 ──

    def mousePressEvent(self, event):
        if not self._pixmap or self._pixmap.isNull():
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle >= 0:
            self._resize_handle = handle
            self._drag_crop_start = QRectF(self._crop_rect)
            self._dragging = True
            return
        if self._crop_rect.contains(pos):
            self._dragging = True
            self._resize_handle = -1
            self._drag_start = pos
            self._drag_crop_start = QRectF(self._crop_rect)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if not self._dragging:
            handle = self._hit_handle(pos)
            if handle >= 0:
                self.setCursor(Qt.SizeFDiagCursor if handle in (0, 3) else
                               Qt.SizeBDiagCursor if handle in (1, 2) else
                               Qt.SizeAllCursor)
            elif self._crop_rect.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        if self._resize_handle >= 0:
            self._do_resize(pos)
        else:
            delta = pos - self._drag_start
            nr = self._drag_crop_start.translated(delta)
            nr.setSize(self._crop_rect.size())
            dr = self._display_rect
            x = max(dr.left(), min(nr.left(), dr.right() - nr.width()))
            y = max(dr.top(), min(nr.top(), dr.bottom() - nr.height()))
            self._crop_rect = QRectF(x, y, nr.width(), nr.height())
        self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._resize_handle = -1
        self.update()

    def _do_resize(self, pos: QPointF):
        orig = self._drag_crop_start
        dr = self._display_rect
        handle = self._resize_handle

        # 边缘中点 (4-7): 保持 1:1，用两方向较大变化量
        if handle >= 4:
            fixed_pt = {
                4: QPointF(orig.center().x(), orig.bottom()),
                5: QPointF(orig.right(), orig.center().y()),
                6: QPointF(orig.center().x(), orig.top()),
                7: QPointF(orig.left(), orig.center().y()),
            }[handle]
            dx = abs(pos.x() - fixed_pt.x())
            dy = abs(pos.y() - fixed_pt.y())
            size = max(self._MIN_CROP, max(dx, dy))
            if handle == 4:  # bottom center
                new_rect = QRectF(orig.center().x() - size / 2,
                                  fixed_pt.y() - size, size, size)
            elif handle == 5:  # right center
                new_rect = QRectF(fixed_pt.x() - size,
                                  orig.center().y() - size / 2, size, size)
            elif handle == 6:  # top center
                new_rect = QRectF(orig.center().x() - size / 2,
                                  fixed_pt.y(), size, size)
            else:  # left center (7)
                new_rect = QRectF(fixed_pt.x(),
                                  orig.center().y() - size / 2, size, size)
        else:
            # 角落: anchor 是对角固定点，opp 是鼠标映射点
            if handle == 0:  # top-left handle, anchor=bottomRight
                anchor = orig.bottomRight()
                size = max(self._MIN_CROP, max(abs(pos.x() - anchor.x()),
                                                abs(pos.y() - anchor.y())))
                new_rect = QRectF(anchor.x() - size, anchor.y() - size,
                                  size, size)
            elif handle == 1:  # top-right handle, anchor=bottomLeft
                anchor = orig.bottomLeft()
                size = max(self._MIN_CROP, max(abs(pos.x() - anchor.x()),
                                                abs(pos.y() - anchor.y())))
                new_rect = QRectF(anchor.x(), anchor.y() - size,
                                  size, size)
            elif handle == 2:  # bottom-left handle, anchor=topRight
                anchor = orig.topRight()
                size = max(self._MIN_CROP, max(abs(pos.x() - anchor.x()),
                                                abs(pos.y() - anchor.y())))
                new_rect = QRectF(anchor.x() - size, anchor.y(),
                                  size, size)
            else:  # handle == 3: bottom-right handle, anchor=topLeft
                anchor = orig.topLeft()
                size = max(self._MIN_CROP, max(abs(pos.x() - anchor.x()),
                                                abs(pos.y() - anchor.y())))
                new_rect = QRectF(anchor.x(), anchor.y(), size, size)

        # 确保正方形，且不超出图片显示区域
        s = max(self._MIN_CROP, min(new_rect.width(), new_rect.height()))
        if dr.isValid():
            s = min(s, dr.width(), dr.height())
            x = max(dr.left(), min(new_rect.left(), dr.right() - s))
            y = max(dr.top(), min(new_rect.top(), dr.bottom() - s))
            new_rect = QRectF(x, y, s, s)
        self._crop_rect = new_rect

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(100, 100, 100))
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "请点击「上传图片」按钮选择图片")
            painter.end()
            return

        dr = self._display_rect
        scaled = self._pixmap.scaled(
            int(dr.width()), int(dr.height()),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        dx = int(dr.left() + (dr.width() - scaled.width()) / 2)
        dy = int(dr.top() + (dr.height() - scaled.height()) / 2)
        self._display_rect = QRectF(dx, dy, scaled.width(), scaled.height())
        painter.drawPixmap(dx, dy, scaled)

        cr = self._crop_rect
        # 遮罩
        mask = QColor(0, 0, 0, 150)
        full = self._display_rect
        painter.fillRect(QRectF(full.left(), full.top(), full.width(),
                                cr.top() - full.top()), mask)
        painter.fillRect(QRectF(full.left(), cr.bottom(), full.width(),
                                full.bottom() - cr.bottom()), mask)
        painter.fillRect(QRectF(full.left(), cr.top(),
                                cr.left() - full.left(), cr.height()), mask)
        painter.fillRect(QRectF(cr.right(), cr.top(),
                                full.right() - cr.right(), cr.height()), mask)
        # 裁剪框
        pen = QPen(QColor(0, 200, 255), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(cr)
        # 十字线
        thin_pen = QPen(QColor(0, 200, 255, 80), 1)
        painter.setPen(thin_pen)
        painter.drawLine(QPointF(cr.center().x(), cr.top()),
                         QPointF(cr.center().x(), cr.bottom()))
        painter.drawLine(QPointF(cr.left(), cr.center().y()),
                         QPointF(cr.right(), cr.center().y()))
        # 缩放手柄
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QBrush(QColor(0, 200, 255)))
        for hr in self._handles():
            painter.drawRect(hr)
        painter.end()

    def _handles(self):
        r = self._crop_rect
        hs = self._HANDLE_SIZE
        hh = hs / 2
        l, t, ri, b, cx, cy = r.left(), r.top(), r.right(), r.bottom(), r.center().x(), r.center().y()
        return [
            QRectF(l - hh, t - hh, hs, hs), QRectF(ri - hh, t - hh, hs, hs),
            QRectF(l - hh, b - hh, hs, hs), QRectF(ri - hh, b - hh, hs, hs),
            QRectF(cx - hh, t - hh, hs, hs), QRectF(ri - hh, cy - hh, hs, hs),
            QRectF(cx - hh, b - hh, hs, hs), QRectF(l - hh, cy - hh, hs, hs),
        ]

    def _hit_handle(self, pos: QPointF) -> int:
        hs = self._HANDLE_SIZE + 4
        for i, hr in enumerate(self._handles()):
            expanded = hr.adjusted(-2, -2, 2, 2)
            if expanded.contains(pos):
                return i
        return -1

    # ── 公共接口 ──

    def get_cropped_pixmap(self) -> QPixmap | None:
        if not self._pixmap or self._pixmap.isNull():
            return None
        ir = self._widget_to_image(self._crop_rect)
        if ir.width() < 1 or ir.height() < 1:
            return None
        return self._pixmap.copy(ir)

    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def _widget_to_image(self, widget_rect: QRectF) -> QRect:
        dr = self._display_rect
        if not dr.isValid() or not self._pixmap:
            return QRect()
        sx = self._pixmap.width() / dr.width()
        sy = self._pixmap.height() / dr.height()
        x = max(0, int((widget_rect.left() - dr.left()) * sx))
        y = max(0, int((widget_rect.top() - dr.top()) * sy))
        w = min(self._pixmap.width() - x, int(widget_rect.width() * sx))
        h = min(self._pixmap.height() - y, int(widget_rect.height() * sy))
        return QRect(x, y, max(1, w), max(1, h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap and not self._pixmap.isNull():
            self._recalc_display_rect()
            self._clamp_crop_rect()


# ═══════════════════════════════════════════════════════════════
# 自定义头像对话框
# ═══════════════════════════════════════════════════════════════

class CustomAvatarDialog(QDialog):
    """自定义头像裁剪与生成对话框"""

    def __init__(self, mods_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义头像")
        self.resize(750, 530)
        self._mods_dir = mods_dir
        self._mod_path = os.path.join(mods_dir, MOD_FILENAME)
        self._mod_id = generate_short_uuid()

        self._setup_ui()
        self._load_existing()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # 主内容: 左裁剪 + 右预览
        content = QHBoxLayout()
        content.setSpacing(12)

        # 左: 裁剪区
        self._crop_widget = CropWidget()
        self._crop_widget.setMinimumSize(400, 400)
        content.addWidget(self._crop_widget, 1)

        # 右: 预览
        right = QVBoxLayout()
        right.setSpacing(12)

        right.addWidget(self._make_preview("70×70 预览", 70))
        right.addWidget(self._make_preview("35×35 预览", 35))
        right.addStretch()

        content.addLayout(right)
        layout.addLayout(content, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_upload = QPushButton("📁 上传图片")
        btn_upload.clicked.connect(self._on_upload)
        btn_layout.addWidget(btn_upload)
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("✅ 确定生成")
        btn_ok.clicked.connect(self._on_confirm)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _make_preview(self, label: str, size: int):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        # 预览图在左
        preview = QLabel()
        preview.setFixedSize(size, size)
        preview.setAlignment(Qt.AlignCenter)
        preview.setStyleSheet(
            "QLabel { border: 2px solid #555; background: #1a1a1a; }")
        h.addWidget(preview)
        # 标签在右，文字右对齐
        lbl = QLabel(label)
        lbl.setFixedWidth(80)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(lbl)
        h.addStretch()
        if size == 70:
            self._preview_70 = preview
        else:
            self._preview_35 = preview
        return w

    # ── 事件处理 ──

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)")
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            QMessageBox.warning(self, "错误", "无法加载所选图片")
            return
        self._crop_widget.set_image(pm)
        self._update_previews()

    def _update_previews(self):
        cropped = self._crop_widget.get_cropped_pixmap()
        if cropped:
            self._preview_70.setPixmap(cropped.scaled(
                70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._preview_35.setPixmap(cropped.scaled(
                35, 35, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_confirm(self):
        if not self._crop_widget.has_image():
            QMessageBox.warning(self, "提示", "请先上传一张图片")
            return
        cropped_pm = self._crop_widget.get_cropped_pixmap()
        if not cropped_pm:
            QMessageBox.warning(self, "提示", "无法获取裁剪后的图片")
            return

        # QImage → PIL
        qimg = cropped_pm.toImage().convertToFormat(QImage.Format_RGBA8888)
        pil_img = Image.frombytes('RGBA', (qimg.width(), qimg.height()),
                                  bytes(qimg.bits()))

        try:
            os.makedirs(self._mods_dir, exist_ok=True)
            tmp_dir = tempfile.mkdtemp(prefix='tks_avatar_')
            try:
                # 保存裁剪原图作为预览图
                preview_path = os.path.join(tmp_dir, 'preview.png')
                pil_img.save(preview_path)
                # 保存缩放图用于生成 JVG 块
                img_70_path = os.path.join(tmp_dir, 'avatar_70.png')
                img_35_path = os.path.join(tmp_dir, 'avatar_35.png')
                pil_img.resize((70, 70), Image.LANCZOS).save(img_70_path)
                pil_img.resize((35, 35), Image.LANCZOS).save(img_35_path)

                # 构建 JVG 块
                fa_b0 = _build_jvm_block(pil_img, 70)
                fa_b1 = _build_jvm_block(pil_img, 35)
                mu_b55 = _build_jvm_block(pil_img, 70)

                # 数据差异 JSON
                fa_diff = build_block_diff_json(
                    target="Fa.JVG", block_type="jvm_block",
                    original_count=200, original_crc32="0x00000000",
                    diff_result={
                        "modified": [
                            {"index": 0, "data_b64": base64.b64encode(fa_b0).decode('ascii')},
                            {"index": 1, "data_b64": base64.b64encode(fa_b1).decode('ascii')},
                        ],
                        "appended": [], "deleted_indices": [],
                    })
                mu_diff = build_block_diff_json(
                    target="Mu.JVG", block_type="jvm_block",
                    original_count=200, original_crc32="0x00000000",
                    diff_result={
                        "modified": [
                            {"index": 55, "data_b64": base64.b64encode(mu_b55).decode('ascii')},
                        ],
                        "appended": [], "deleted_indices": [],
                    })

                # MOD JSON（含预览图字段）
                metadata = {
                    "id": self._mod_id, "name": MOD_NAME,
                    "version": "1.0.0", "author": MOD_AUTHOR,
                    "description": MOD_DESC, "load_order": MOD_LOAD_ORDER,
                    "preview_image_path": img_70_path,
                }
                components = [
                    {"file": "data/Fa.JVG.json", "target": "Fa.JVG"},
                    {"file": "data/Mu.JVG.json", "target": "Mu.JVG"},
                ]
                mod_json = generate_mod_json(metadata, components)

                data_files = {
                    "data/Fa.JVG.json": fa_diff,
                    "data/Mu.JVG.json": mu_diff,
                }

                pack_tksmod(
                    self._mod_path, mod_json, data_files,
                    preview_image_path=preview_path)

                QMessageBox.information(
                    self, "生成成功",
                    f"自定义头像 MOD 已生成并保存到:\n{self._mod_path}\n\n"
                    f"包含:\n"
                    f"  • Fa.JVG block_00 (70×70)\n"
                    f"  • Fa.JVG block_01 (35×35)\n"
                    f"  • Mu.JVG block_55 (70×70)")
                self.accept()
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            QMessageBox.critical(self, "生成失败", f"生成 MOD 时出错:\n{e}")

    # ── 加载已有头像 ──

    def _load_existing(self):
        """如果 mods 目录已存在自定义头像 MOD，从预览图加载到裁剪区"""
        if not os.path.isfile(self._mod_path):
            return
        try:
            with zipfile.ZipFile(self._mod_path, 'r') as zf:
                # 读取 MOD ID 以保持一致
                if "mod.json" in zf.namelist():
                    mj = json.loads(zf.read("mod.json").decode('utf-8'))
                    self._mod_id = mj.get("id", self._mod_id)

                # 从预览图加载（preview.png 在 zip 根目录）
                if "preview.png" in zf.namelist():
                    img_data = zf.read("preview.png")
                    pm = QPixmap()
                    if pm.loadFromData(img_data):
                        self._crop_widget.set_image(pm)
                        self._update_previews()
        except Exception:
            pass

    # 通过定时器轮询裁剪变化来更新预览
    def showEvent(self, event):
        super().showEvent(event)
        from PySide6.QtCore import QTimer
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._update_previews)
        self._preview_timer.start(100)  # 每 100ms 刷新预览

    def hideEvent(self, event):
        if hasattr(self, '_preview_timer'):
            self._preview_timer.stop()
        super().hideEvent(event)
