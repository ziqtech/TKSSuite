# -*- coding: utf-8 -*-
"""tks_book 地图标签页 — 场景名称列表 + 背景层预览 (不渲染前景/碰撞层)"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QApplication

from book_loader import pil_to_qpixmap
from tab_common import BookTabBase


class MapTab(BookTabBase):
    """地图查看页: 左侧场景列表 (同 TKMat 编辑器场景列表), 右侧背景预览"""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)
        self._pix_cache = {}
        self._populated = False
        # 右侧预览: 直接放一张图 (滚动区已由基类提供)
        # GamePreview = 公共游戏画面预览区样式 (深色底, 同 tkt_editor 预览)
        self.detail_scroll.setObjectName("GamePreview")
        self.detail_scroll.setWidgetResizable(False)
        self._preview_lbl = QLabel("请从左侧选择地图")
        self._preview_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._preview_lbl.setMargin(8)
        self.detail_scroll.setWidget(self._preview_lbl)

    def populate(self):
        """惰性: SC.GRP 较大, 首次切到本页时才加载 (见 ensure_populated)"""
        self._populated = False
        self._pix_cache.clear()
        self.set_list_items([])
        self._preview_lbl.setText("请从左侧选择地图")
        self._preview_lbl.adjustSize()

    def ensure_populated(self):
        if self._populated:
            return
        self._populated = True
        self._preview_lbl.setText("正在加载 SC.GRP…")
        self._preview_lbl.adjustSize()
        QApplication.processEvents()
        grp = self.data.sc_grp()
        items = []
        if grp is not None:
            for sec in grp.sections:
                if sec.width <= 0 or sec.height <= 0:
                    continue
                sid = sec.index
                items.append((sid, f"{sid:>3}  {self.data.scene_name(sid)}"))
        self.set_list_items(items)
        if items:
            self._preview_lbl.setText("请从左侧选择地图")
        else:
            self._preview_lbl.setText("未找到 SC.GRP / SC.IDX, 无法预览地图")
        self._preview_lbl.adjustSize()

    def show_detail(self, sid):
        pix = self._pix_cache.get(sid)
        if pix is None:
            self._preview_lbl.setText(f"正在解码场景 {sid}…")
            self._preview_lbl.adjustSize()
            QApplication.processEvents()
            img = self.data.scene_background(sid)
            pix = pil_to_qpixmap(img)
            if pix is not None:
                self._pix_cache[sid] = pix
        if pix is None:
            self._preview_lbl.setText(f"场景 {sid} 无背景图")
        else:
            self._preview_lbl.setPixmap(pix)
            self._preview_lbl.setToolTip(
                f"{self.data.scene_name(sid)}  ({pix.width()}×{pix.height()})")
        self._preview_lbl.adjustSize()
