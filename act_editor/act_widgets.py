"""act_editor 预览控件 — PreviewCanvas/TimelineWidget/ThumbnailStrip (T16 自 act_editor.py 迁出)。"""
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QScrollArea, QDialog, QFileDialog, QMessageBox, QTextEdit,
    QFrame, QGridLayout, QAbstractItemView, QMenuBar,
    QComboBox, QSpinBox, QSlider, QRadioButton, QButtonGroup, QGroupBox,
    QStyle, QMenu,
    QToolTip,
)
from PySide6.QtGui import (
    QColor, QFont, QIntValidator, QPainter, QPen, QBrush,
    QPixmap, QImage, QAction, QPalette, QFontMetrics, QMouseEvent,
    QWheelEvent, QKeyEvent, QShortcut, QKeySequence, QCursor,
)
from PySide6.QtCore import (
    Qt, QTimer, QTranslator, Signal, QPoint, QRect, QSize,
)

from act_font import ActFont9696

from editor_utils.theme_manager import business_colors

from act_codec import (
    BLEND_MODE_LABELS, BLOCK_SHADOW_BG, BLOCK_SHADOW_BORDER, FONT_FAMILY,
    GUIDE_BLUE, PEN_TRAJECTORY_GREEN, PEN_TRAJECTORY_RED, PREVIEW_CANVAS_BG,
    SELECT_RED, SLOT_COLORS,
)

# ============================================================

class PreviewCanvas(QWidget):
    """动画预览画布: PIL 合成 + QPainter 叠加标注"""
    dragOffsetChanged = Signal(int, int, int, int)  # slot, eff_dir, gdx, gdy

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._composite_pixmap = None
        self._comp_ox = 0
        self._comp_oy = 0
        self._sprite_boxes = []
        self._origin_cv = (0, 0)
        self._enemy_cv = (0, 0)
        self._info_lines = []
        self._all_stopped = False
        self._tick = 0
        self._direction = 0
        self._scale = 1.0
        self._off_x = 0
        self._off_y = 0
        self._bbox = None
        self._drag_state = None
        self._entry_title = ""
        self._float_specs = []
        self._cursor_over_sprite = False

    def set_entry_title(self, title):
        self._entry_title = title
        self.update()

    def set_float_specs(self, specs):
        self._float_specs = list(specs)
        self.update()

    def set_frame_data(self, composite_pixmap, comp_ox, comp_oy,
                       sprite_boxes, origin_cv, enemy_cv, info_lines,
                       all_stopped, tick, direction, scale, off_x, off_y, bbox):
        self._composite_pixmap = composite_pixmap
        self._comp_ox = comp_ox
        self._comp_oy = comp_oy
        self._sprite_boxes = sprite_boxes
        self._origin_cv = origin_cv
        self._enemy_cv = enemy_cv
        self._info_lines = info_lines
        self._all_stopped = all_stopped
        self._tick = tick
        self._direction = direction
        self._scale = scale
        self._off_x = off_x
        self._off_y = off_y
        self._bbox = bbox
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        # 背景
        painter.fillRect(0, 0, w, h, QColor(PREVIEW_CANVAS_BG))

        if self._composite_pixmap and not self._composite_pixmap.isNull():
            painter.drawPixmap(int(self._comp_ox), int(self._comp_oy),
                             self._composite_pixmap)

        # Sprite 外框
        slot_colors = [QColor(c) for c in SLOT_COLORS]
        for (slot, eff_dir, cx, cy, ex, ey, ox, oy) in self._sprite_boxes:
            color = slot_colors[(slot - 1) % len(slot_colors)]
            pen = QPen(color, 1)
            painter.setPen(pen)
            painter.drawRect(QRect(int(cx), int(cy), int(ex - cx), int(ey - cy)))
            painter.setFont(QFont("Consolas", 6))
            painter.drawText(int(cx) + 2, int(cy) - 2, f"#{slot}")

        # 原点十字 (攻击方)
        ox_c, oy_c = self._origin_cv
        pen_green = QPen(QColor(PEN_TRAJECTORY_GREEN), 2)
        painter.setPen(pen_green)
        painter.drawLine(int(ox_c - 16), int(oy_c), int(ox_c + 16), int(oy_c))
        painter.drawLine(int(ox_c), int(oy_c - 16), int(ox_c), int(oy_c + 16))
        painter.setFont(QFont("Consolas", 7))
        painter.drawText(int(ox_c + 18), int(oy_c + 4), "攻击方")

        # 假想敌位置 (受击方)
        ex_c, ey_c = self._enemy_cv
        pen_red = QPen(QColor(PEN_TRAJECTORY_RED), 2)
        painter.setPen(pen_red)
        painter.drawLine(int(ex_c - 16), int(ey_c), int(ex_c + 16), int(ey_c))
        painter.drawLine(int(ex_c), int(ey_c - 16), int(ex_c), int(ey_c + 16))
        painter.drawText(int(ex_c + 18), int(ey_c + 4), "受击方")
        # 假想敌人形
        painter.fillRect(QRect(int(ex_c - 15), int(ey_c - 40), 30, 40), QColor(BLOCK_SHADOW_BG))
        painter.setPen(QColor(BLOCK_SHADOW_BORDER))
        painter.drawRect(QRect(int(ex_c - 15), int(ey_c - 40), 30, 40))
        painter.setPen(QColor('#f44'))
        painter.drawText(int(ex_c - 4), int(ey_c - 22), "敌")

        # 伤害飘字
        if self._float_specs:
            font = getattr(self.editor, '_font', None)
            if font is None:
                font = ActFont9696(getattr(self.editor, 'font_path', ''))
            for spec in self._float_specs:
                pixmap = font.text_pixmap(
                    spec['text'], spec['color'],
                    ftype=spec.get('ftype', 4), size=spec.get('size', 24),
                    outline=spec.get('outline', True))
                if pixmap is not None:
                    painter.drawPixmap(int(spec['x']), int(spec['y']), pixmap)
                else:
                    painter.setPen(QColor(*spec['color']))
                    painter.setFont(QFont("Microsoft YaHei UI", 24))
                    painter.drawText(
                        int(spec['x']), int(spec['y']) + 24, spec['text'])

        # 播放完毕标记
        if self._all_stopped:
            painter.setPen(QColor('#ff0'))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(w // 2 - 60, h - 16, f"■ 播放完毕 (tick {self._tick})")

        # 信息行 (左上)
        painter.setPen(QColor('#0f0'))
        painter.setFont(QFont("Consolas", 8))
        y = 12
        for line in self._info_lines[:24]:
            painter.drawText(8, y, line)
            y += 14

        # 条目标题 (左下, 同字体样式)
        if self._entry_title:
            painter.setPen(QColor('#0f0'))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(8, h - 12, self._entry_title)

    def _hit_test(self, cv_x, cv_y):
        for (slot, eff_dir, sx, sy, ex, ey, ox, oy) in self._sprite_boxes:
            if sx <= cv_x <= ex and sy <= cv_y <= ey:
                return (slot, eff_dir, ox, oy, sx, sy)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._hit_test(event.position().x(), event.position().y())
            if hit:
                slot, eff_dir, ox, oy, sx, sy = hit
                self._drag_state = (slot, eff_dir, ox, oy,
                                   event.position().x(), event.position().y(),
                                   sx, sy)
                self.setCursor(Qt.ClosedHandCursor)
                self.editor._preview_stop()
            else:
                self._drag_state = None

    def mouseMoveEvent(self, event):
        if self._drag_state is not None:
            slot, eff_dir, ox, oy, px, py, sx, sy_orig = self._drag_state
            dx = event.position().x() - px
            dy = event.position().y() - py
            gdx = int(dx / self._scale) if self._scale > 0 else 0
            gdy = int(dy / self._scale) if self._scale > 0 else 0
            self.editor._preview_apply_drag(slot, eff_dir, gdx, gdy)
            self._drag_state = (slot, eff_dir,
                              self.editor._get_layer_offset(slot, eff_dir, 'x'),
                              self.editor._get_layer_offset(slot, eff_dir, 'y'),
                              event.position().x(), event.position().y(),
                              sx + gdx, sy_orig + gdy)
        else:
            hit = self._hit_test(event.position().x(), event.position().y())
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_state is not None:
            self.editor._preview_finish_drag()
        self._drag_state = None
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        pass  # 缩放暂不实现

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.editor._preview_redraw()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.editor._tl_step_prev()
        elif event.key() == Qt.Key_Right:
            self.editor._tl_step_next()
        else:
            super().keyPressEvent(event)


# ============================================================
# 时间轴画布 (QWidget 自定义绘制)
# ============================================================

class TimelineWidget(QWidget):
    """时间轴可视化 + 编辑交互组件 (轨道边缘拖拽 / 平移 / 磁吸 / 框选 / 右键菜单)"""
    playheadMoved = Signal(int)

    TRACK_COLORS = ['#e74c3c', '#3498db', '#f39c12', '#2ecc71',
                    '#9b59b6', '#1abc9c', '#e67e22', '#95a5a6']
    SFX_COLORS = ['#e91e63', '#9c27b0', '#3f51b5', '#009688',
                  '#ff9800', '#795548', '#607d8b', '#4caf50']

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._zoom = 40
        self._pan_x = 0
        self._pan_y = 0
        self._track_h = 28
        self._margin = 30
        self._ruler_h = 22
        self._track_gap = 4
        self._playhead = 0
        self._layers_info = []
        self._sfx_in = []          # (0,0,sid,trig,idx) 入参
        self._sfx_pos = []         # (sx,sy,sid,trig,idx) widget 坐标 (paintEvent 算)
        self._track_bb = {}        # s -> (x1,y1,x2,y2) widget 坐标
        self._delay_bb = {}        # s -> (x1,y1,x2,y2)
        self._vis_bb = {}          # s -> (x1,y1,x2,y2) 眼睛点击区
        self._ph_bottom = 100
        self._pan_start = None
        self._drag_state = None
        self._marquee_start = None

    def set_zoom(self, z):
        self._zoom = z
        self.update()

    def zoom(self):
        return self._zoom

    def track_h(self):
        return self._track_h

    def set_data(self, playhead, layers_info, sfx_markers):
        self._playhead = playhead
        self._layers_info = layers_info
        self._sfx_in = sfx_markers
        self.update()

    def set_playhead(self, ph):
        self._playhead = ph
        self.update()

    def _content_x(self, tick):
        return self._margin + int(tick * self._zoom) + self._pan_x

    def _tick_at(self, widget_x):
        return max(0, int((widget_x - self._margin - self._pan_x) / self._zoom + 0.5))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w, h = self.width(), self.height()
        zoom = self._zoom
        margin = self._margin
        track_h = self._track_h
        track_gap = self._track_gap
        ruler_h = self._ruler_h

        is_dark = self.editor._is_dark
        bg = QColor(business_colors("act", self.editor._theme_id)["timeline_bg"])
        painter.fillRect(0, 0, w, h, bg)

        if not self._layers_info:
            return

        max_tick = 10
        for (s, ltype, delay, play_ticks, loop, interval) in self._layers_info:
            dur = delay + play_ticks
            if dur > max_tick:
                max_tick = dur

        # 刻度尺
        tick_step = max(1, int(20 / zoom))
        # 画布刻度尺绘制色豁免 (#888/#666: 深浅两档画布辅助色, 非样式体系 UI 色, P3-6 核对)
        ruler_color = QColor('#888') if is_dark else QColor('#666')
        painter.setPen(QPen(ruler_color, 1))
        painter.setFont(QFont(FONT_FAMILY, 8))
        for t in range(0, max_tick + tick_step, tick_step):
            x = self._content_x(t)
            painter.drawLine(int(x), ruler_h - 4, int(x), ruler_h)
            if t % max(1, tick_step * 5) == 0 or t == 0:
                painter.drawText(int(x) - 10, ruler_h - 6, str(t))

        self._track_bb.clear()
        self._delay_bb.clear()
        self._vis_bb.clear()

        for i, (s, ltype, delay, play_ticks, loop, interval) in enumerate(self._layers_info):
            y = ruler_h + i * (track_h + track_gap) + 4 + self._pan_y
            color = QColor(self.TRACK_COLORS[s % 8])
            is_sel = s in getattr(self.editor, '_tl_selected_layers', set())

            # 可见性眼睛 (左侧, 可点击)
            vis_cb = self.editor._preview_vis.get(s + 1)
            vis_on = vis_cb.isChecked() if vis_cb else True
            painter.setPen(QColor(self.TRACK_COLORS[s % 8] if vis_on else '#555'))
            painter.setFont(QFont(FONT_FAMILY, 10))
            painter.drawText(18 + self._pan_x, int(y + track_h // 2 + 4),
                             '●' if vis_on else '○')
            self._vis_bb[s] = (0 + self._pan_x, int(y),
                               30 + self._pan_x, int(y + track_h))

            # 图层标签
            painter.setPen(color)
            painter.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
            painter.drawText(34 + self._pan_x, int(y + track_h // 2 + 4), f"#{s+1}")

            # 延迟区
            dx = self._content_x(0)
            if delay > 0:
                dw = int(delay * zoom)
                painter.fillRect(QRect(int(dx), int(y), int(dw), track_h),
                               QColor(business_colors("act", self.editor._theme_id)["grid_major"]))
                painter.setPen(QColor(business_colors("act", self.editor._theme_id)["grid_minor"]))
                painter.drawRect(QRect(int(dx), int(y), int(dw), track_h))

            # 播放区
            px = self._content_x(delay)
            pw = max(4, int(play_ticks * zoom))
            painter.fillRect(QRect(int(px), int(y), int(pw), track_h), color)
            painter.setPen(color.darker(120))
            painter.drawRect(QRect(int(px), int(y), int(pw), track_h))
            if is_sel:
                painter.setPen(QPen(QColor('#fff'), 3))
                painter.drawRect(QRect(int(px), int(y), int(pw), track_h))

            # 帧范围文字
            painter.setPen(QColor('#fff'))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(int(px + 3), int(y + track_h // 2 + 4),
                           f"[{self.editor._get_layer_val(s, 17)}..{self.editor._get_layer_val(s, 18)}]")

            # Loop 标记
            loop_val = self.editor._get_layer_val(s, 19)
            if loop_val == -1:
                mark = "↻"
            elif loop_val == -2:
                mark = "■"
            elif loop_val >= 0:
                mark = f"↷{loop_val}"
            else:
                mark = ""
            if mark:
                painter.setPen(color)
                painter.drawText(int(px + pw + 4), int(y + track_h // 2 + 4), mark)

            self._track_bb[s] = (int(px), int(y), int(px + pw), int(y + track_h))
            self._delay_bb[s] = (int(dx), int(y), int(px), int(y + track_h))

        # 播放头
        ph_x = self._content_x(self._playhead)
        content_h = ruler_h + len(self._layers_info) * (track_h + track_gap) + 10
        self._ph_bottom = content_h
        painter.setPen(QPen(QColor(SELECT_RED), 2))
        painter.drawLine(int(ph_x), 0, int(ph_x), content_h)
        painter.setBrush(QColor(SELECT_RED))
        painter.drawPolygon([
            QPoint(int(ph_x - 5), 0),
            QPoint(int(ph_x + 5), 0),
            QPoint(int(ph_x), 8),
        ])

        # 音效标记 (同 tick 合并为一个 ♪, 下方列出所有 sid)
        self._sfx_pos = []
        sfx_y = content_h + 4 + self._pan_y
        # 按 trig 分组
        by_trig = {}  # trig → [(sid, idx), ...]
        for (sx_val, sy_val, sid, trig, idx) in self._sfx_in:
            by_trig.setdefault(trig, []).append((sid, idx))
        for trig, items in sorted(by_trig.items()):
            sx = self._content_x(trig)
            n = len(items)
            color = QColor(self.SFX_COLORS[items[0][1] % len(self.SFX_COLORS)])
            # ♪ 图标
            painter.setPen(color)
            painter.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
            note = "♪" if n == 1 else f"♪×{n}"
            painter.drawText(int(sx) - 8, int(sfx_y + 10), note)
            # sid 列表 (每个一行, 纵向错开)
            painter.setFont(QFont(FONT_FAMILY, 7))
            for i, (sid, idx) in enumerate(items):
                c = QColor(self.SFX_COLORS[idx % len(self.SFX_COLORS)])
                painter.setPen(c)
                painter.drawText(int(sx) - 12, int(sfx_y + 22 + i * 14), f"sid={sid}")
            # 虚线连接到轨道
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.drawLine(int(sx), int(sfx_y - 6), int(sx), int(sfx_y))
            # 记录点击区域 (覆盖整个 group)
            self._sfx_pos.append((int(sx), int(sfx_y), items[0][0], trig, items[0][1]))

        # 框选矩形
        if self._marquee_start is not None:
            x0, y0 = self._marquee_start
            pos = self.mapFromGlobal(QCursor.pos())
            x1, y1 = pos.x(), pos.y()
            painter.setPen(QPen(QColor(GUIDE_BLUE), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(min(x0, x1), min(y0, y1),
                                   abs(x1 - x0), abs(y1 - y0)))

    def _hit_test(self, x, y):
        """返回 (layer_idx|None, hit_type, tick). hit_type ∈
        playhead/left_edge/right_edge/body/sfx/empty"""
        ruler_h = self._ruler_h
        edge_margin = 6
        tick = self._tick_at(x)
        if y < ruler_h:
            return None, 'playhead', tick
        for s, bb in self._track_bb.items():
            db = self._delay_bb.get(s)
            if bb is None or db is None:
                continue
            ty, by = bb[1], bb[3]
            if not (ty <= y <= by):
                continue
            left_x = bb[0]
            if db[2] > db[0] and abs(x - left_x) <= edge_margin:
                return s, 'left_edge', tick
            right_x = bb[2]
            if abs(x - right_x) <= edge_margin:
                return s, 'right_edge', tick
            if db[0] <= x <= bb[2]:
                return s, 'body', tick
        for (sx, sy, sid, trig, idx) in self._sfx_pos:
            if abs(x - sx) < 12 and abs(y - sy) < 36:
                return idx, 'sfx', trig
        return None, 'empty', tick

    def mousePressEvent(self, event):
        x = event.position().x()
        y = event.position().y()
        edit_ok = self.editor._tl_edit_enabled

        if event.button() == Qt.MiddleButton:
            self._pan_start = (x, y, self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() != Qt.LeftButton:
            return

        # 可见性眼睛点击
        for s, bb in self._vis_bb.items():
            if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]:
                cb = self.editor._preview_vis.get(s + 1)
                if cb is not None:
                    cb.setChecked(not cb.isChecked())
                    self.editor._preview_redraw()
                    self.update()
                return

        layer_idx, hit_type, tick = self._hit_test(x, y)
        self._drag_state = None
        self._marquee_start = None

        if hit_type == 'sfx':
            if edit_ok:
                self._drag_state = ('sfx', layer_idx)
                return
            if self.editor._editing_idx >= 0:
                tail = self.editor.entries[self.editor._editing_idx].get('tail') or []
                sid = tail[layer_idx * 2] if layer_idx * 2 < len(tail) else 0
                if sid and self.editor.sws_grp:
                    self.editor._play_sound_preview(sid)
        elif hit_type in ('left_edge', 'right_edge') and edit_ok:
            self._drag_state = (layer_idx, hit_type)
        elif hit_type == 'body':
            if edit_ok:
                if not (event.modifiers() & Qt.ShiftModifier):
                    if layer_idx not in self.editor._tl_selected_layers:
                        self.editor._tl_selected_layers.clear()
                        self.editor._tl_selected_layers.add(layer_idx)
                else:
                    self.editor._tl_selected_layers.add(layer_idx)
                self.editor._tl_refresh_thumbnails()
                if self.editor._editing_idx >= 0:
                    entry = self.editor.entries[self.editor._editing_idx]
                    orig_delays = {}
                    for sel in self.editor._tl_selected_layers:
                        orig_delays[sel] = entry['layers'][sel][22]
                    self._drag_state = ('batch_move', tick, orig_delays)
                self.update()
            else:
                self.editor._tl_select_layer(layer_idx)
        elif hit_type == 'empty':
            if edit_ok:
                self._marquee_start = (x, y)
                if not (event.modifiers() & Qt.ShiftModifier):
                    self.editor._tl_selected_layers.clear()
                self.update()
        elif hit_type == 'playhead':
            self._playhead = tick
            self.editor._on_timeline_clicked(tick)
            self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        y = event.position().y()

        if self._pan_start is not None:
            sx, sy, px0, py0 = self._pan_start
            self._pan_x = px0 + (x - sx)
            self._pan_y = py0 + (y - sy)
            self.update()
            return

        if self._marquee_start is not None:
            self.update()
            return

        if self._drag_state is not None:
            self.editor._tl_handle_drag(self._drag_state, x, y,
                                        event.modifiers() & Qt.ShiftModifier)
            return

        if self.editor._tl_edit_enabled:
            _, hit_type, _ = self._hit_test(x, y)
            if hit_type == 'sfx':
                self.setCursor(Qt.PointingHandCursor)
            elif hit_type in ('left_edge', 'right_edge'):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            return
        if event.button() != Qt.LeftButton:
            return

        if self._marquee_start is not None:
            x0, y0 = self._marquee_start
            x1 = event.position().x()
            y1 = event.position().y()
            min_x, max_x = min(x0, x1), max(x0, x1)
            min_y, max_y = min(y0, y1), max(y0, y1)
            for s, bb in self._track_bb.items():
                hit = not (max_x < bb[0] or min_x > bb[2]
                           or max_y < bb[1] or min_y > bb[3])
                if hit:
                    self.editor._tl_selected_layers.add(s)
            self._marquee_start = None
            self.editor._tl_refresh_thumbnails()
            self.update()
            return

        had_drag = self._drag_state is not None
        was_sfx = had_drag and self._drag_state[0] == 'sfx'
        self._drag_state = None
        if had_drag:
            self.editor._tl_handle_release(was_sfx)
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            old_zoom = self._zoom
            old_cx = event.position().x() - self._pan_x - self._margin
            old_tick = old_cx / max(1, old_zoom)
            delta = 1 if event.angleDelta().y() > 0 else -1
            self._zoom = max(2, min(40, self._zoom + delta * 2))
            new_cx = old_tick * self._zoom
            self._pan_x = self._pan_x + (old_cx - new_cx)
            self.editor._tl_update_zoom_lbl()
            self.update()
        elif event.modifiers() & Qt.ShiftModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            self._track_h = max(20, min(80, self._track_h + delta * 4))
            self.update()
        else:
            self._pan_y -= int(event.angleDelta().y() / 120) * 30
            self.update()

    def contextMenuEvent(self, event):
        if not self.editor._tl_edit_enabled:
            return
        x = event.pos().x()
        y = event.pos().y()
        layer_idx, hit_type, _ = self._hit_test(x, y)
        if layer_idx is None:
            return
        if hit_type not in ('body', 'left_edge', 'right_edge'):
            return
        if self.editor._editing_idx < 0:
            return
        self.editor._tl_select_layer(layer_idx)
        menu = QMenu(self)
        vis_cb = self.editor._preview_vis.get(layer_idx + 1)
        is_vis = vis_cb.isChecked() if vis_cb else True
        menu.addAction("隐藏图层" if is_vis else "显示图层",
                       lambda li=layer_idx: self.editor._quick_toggle_vis(li))
        menu.addSeparator()
        blend_menu = menu.addMenu("混合模式")
        for val, label in BLEND_MODE_LABELS.items():
            blend_menu.addAction(
                label, lambda v=val, li=layer_idx: self.editor._quick_set_blend(li, v))
        menu.addSeparator()
        menu.addAction("清空该图层数据",
                       lambda li=layer_idx: self.editor._quick_clear_layer(li))
        menu.exec(event.globalPos())


# ============================================================
# 缩略图条 (QWidget 自定义绘制)
# ============================================================

class ThumbnailStrip(QWidget):
    """帧缩略图选择器"""
    frameRangeChanged = Signal(int, int)  # first, last

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(58)
        self.setMaximumHeight(58)
        self._pixmaps = []
        self._total_frames = 0
        self._first = 0
        self._last = 0
        self._dfo = 0
        self._thumb_h = 40
        self._thumb_spacing = 4
        self._margin = 4
        self._anchor = None

    def set_data(self, pixmaps, total_frames, first, last, dfo):
        self._pixmaps = pixmaps
        self._total_frames = total_frames
        self._first = first
        self._last = last
        self._dfo = dfo
        self.update()

    def clear(self):
        self._pixmaps = []
        self._total_frames = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        is_dark = self.editor._is_dark
        bg = QColor('#1a1e27') if is_dark else QColor('#f5f5f5')
        painter.fillRect(0, 0, w, h, bg)

        if not self._pixmaps:
            painter.setPen(QColor('#999'))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(w // 2 - 60, h // 2, "(选择图层查看帧缩略图)")
            return

        thumb_h = self._thumb_h
        spacing = self._thumb_spacing
        margin = self._margin

        for fi, pix in enumerate(self._pixmaps):
            x = margin + fi * (thumb_h + spacing)
            if pix and not pix.isNull():
                painter.drawPixmap(int(x), 8, pix)

        # DFO 标记
        if self._dfo > 0:
            pen_dfo = QPen(QColor(GUIDE_BLUE), 1)
            painter.setPen(pen_dfo)
            painter.setFont(QFont(FONT_FAMILY, 6))
            for di in range(0, self._total_frames, self._dfo):
                x = margin + di * (thumb_h + spacing)
                painter.drawLine(int(x), thumb_h + 8, int(x), thumb_h + 16)
                painter.drawText(int(x) - 4, thumb_h + 26, str(di))

        # 选中范围
        fx = margin + self._first * (thumb_h + spacing) - 1
        lx = margin + self._last * (thumb_h + spacing) + thumb_h + 1
        pen_sel = QPen(QColor(SELECT_RED), 2)
        painter.setPen(pen_sel)
        painter.drawRect(QRect(int(fx), 6, int(lx - fx), thumb_h + 4))
        painter.setFont(QFont(FONT_FAMILY, 7, QFont.Bold))
        painter.drawText(int(fx) + 2, 18, f"first={self._first}")
        painter.drawText(int(lx) - 40, 18, f"last={self._last}")

    def mousePressEvent(self, event):
        if not self._pixmaps:
            return
        x = event.position().x()
        thumb_h = self._thumb_h
        spacing = self._thumb_spacing
        margin = self._margin
        fi = int((x - margin) / (thumb_h + spacing) + 0.5)
        fi = max(0, min(self._total_frames - 1, fi))

        if event.modifiers() & Qt.ShiftModifier:
            if self._anchor is not None:
                f = min(self._anchor, fi)
                l = max(self._anchor, fi)
                self.frameRangeChanged.emit(f, l)
        else:
            self._anchor = fi
            self.frameRangeChanged.emit(fi, fi)
