"""
通用选择器对话框 — 供所有编辑器统一使用
包含: TktPickerDialog (TKT 文本选择器)
      StatusPickerDialog (状态位掩码多选器)
      WarpcPickerDialog (WarPC 角色选择器)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QHeaderView,
    QScrollArea, QWidget, QCheckBox, QLabel, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage

from editor_utils.window_theme import apply_godot_theme


def _detect_dark_theme(parent) -> bool:
    """检测父窗口的深色主题状态，优先读属性，回退系统主题。"""
    for attr in ('is_dark_theme', '_is_dark'):
        val = getattr(parent, attr, None)
        if val is not None:
            return bool(val)
    return QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark


# 31 种状态名称 (Maker UI 状态列表; bit 0..30) — 供状态弹窗/标签渲染共用
STATUS_NAMES = [
    "破兵","碎甲","昏眩","封锁","羁绊","蓄力","刚体","集中",
    "云身","神行","无视","伪装","御风","死战","连计","连计",
    "误导","混乱","禁制","定身","诅咒","封印","燃烧","冰冻",
    "虚弱","麻痹","沈睡","中毒","迷恋","明镜","针灸",
]
# Mu.JVG 中状态图标起始精灵索引 (对齐 item_editor); 用于状态弹窗/预览中的图标
STATUS_ICON_BASE = 242


class TktPickerDialog(QDialog):
    """TKT 文本选择对话框 — 搜索过滤表格，支持双击选择"""

    def __init__(self, parent, tkt_dict, cur_val=0):
        super().__init__(parent)
        self.setWindowTitle("选择 TKT 文本")
        self.resize(500, 400)
        self.selected_id = cur_val
        self._is_dark = _detect_dark_theme(parent)

        layout = QVBoxLayout(self)

        # 搜索框
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索...")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["ID", "文本"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._accept)
        layout.addWidget(self.table)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("✅ 确定")
        btn_ok.clicked.connect(self._accept)
        btn_layout.addWidget(btn_ok)
        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        # 数据
        self._data = sorted(tkt_dict.items(), key=lambda x: x[0])
        self._populate()

    def showEvent(self, event):
        super().showEvent(event)
        apply_godot_theme(self, self._is_dark)

        # 选中当前值
        if self.selected_id > 0:
            for row in range(self.table.rowCount()):
                if int(self.table.item(row, 0).text()) == self.selected_id:
                    self.table.selectRow(row)
                    break

    def _populate(self, filter_text=""):
        self.table.setRowCount(0)
        for tid, text in self._data:
            if filter_text and filter_text.lower() not in text.lower() and filter_text != str(tid):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(tid)))
            self.table.setItem(row, 1, QTableWidgetItem(text[:80]))

    def _filter(self, text):
        self._populate(text)

    def _accept(self):
        sel = self.table.selectedItems()
        if sel:
            self.selected_id = int(self.table.item(sel[0].row(), 0).text())
        self.accept()


class StatusPickerDialog(QDialog):
    """状态位掩码多选对话框。

    16 个状态复选框 (base 起始), 可选每行前显示状态图标。
    确定后通过 ``selected_mask`` 属性返回带符号 int16。

    Args:
        parent: 父窗口
        title: 窗口标题
        status_names: 状态名称列表 (通常为 STATUS_NAMES)
        cur_mask: 当前掩码 (uint16)
        base: 起始状态索引 (0 或 16)
        get_pixmap_fn: 可选的图标获取回调 ``fn(icon_val, size) -> QPixmap``;
                       为 None 时不显示图标。
        is_cause: 是否为"导致状态"语义 (仅用于标题区分, 不影响渲染)。
    """
    def __init__(self, parent, title, status_names, cur_mask, base,
                 get_pixmap_fn=None, is_cause=False):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(380, 520)
        self.selected_mask = None
        self._is_dark = _detect_dark_theme(parent)
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); cl = QVBoxLayout(content)
        self.checkboxes = []
        for i in range(16):
            idx = base + i
            if idx >= len(status_names): break
            row = QHBoxLayout()
            if get_pixmap_fn is not None:
                pix = get_pixmap_fn(STATUS_ICON_BASE + idx - 130, (20, 20))
                if pix:
                    lbl = QLabel(); lbl.setPixmap(pix); row.addWidget(lbl)
            cb = QCheckBox(f"{idx}. {status_names[idx]}")
            cb.setChecked(bool(cur_mask & (1 << i)))
            self.checkboxes.append((i, cb)); row.addWidget(cb); row.addStretch()
            cl.addLayout(row)
        cl.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("全选", clicked=lambda: [cb.setChecked(True) for _, cb in self.checkboxes]))
        bl.addWidget(QPushButton("全清", clicked=lambda: [cb.setChecked(False) for _, cb in self.checkboxes]))
        bl.addStretch()
        bl.addWidget(QPushButton("✅ 确定", clicked=self._ok))
        bl.addWidget(QPushButton("❌ 取消", clicked=self.reject))
        layout.addLayout(bl)

    def showEvent(self, event):
        super().showEvent(event)
        apply_godot_theme(self, self._is_dark)

    def _ok(self):
        m = 0
        for i, cb in self.checkboxes:
            if cb.isChecked(): m |= (1 << i)
        if m >= 0x8000: m -= 0x10000
        self.selected_mask = m; self.accept()

    def get_mask(self):
        """兼容旧调用: 返回与 selected_mask 相同的带符号 int16"""
        return self.selected_mask


# ═══════════════════════════════════════════════════════════════
# WarPC 角色选择器
# ═══════════════════════════════════════════════════════════════

def _pil_to_pixmap(img, size=(32, 32)):
    """将 PIL.Image 转为 QPixmap"""
    try:
        img = img.resize(size, 1)  # Image.NEAREST = 1
        img = img.convert('RGBA')
        data = img.tobytes('raw', 'RGBA')
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


class WarpcPickerDialog(QDialog):
    """WarPC 角色选择对话框 — 搜索过滤表格，支持单选/多选。

    Args:
        parent: 父窗口
        war_pc_records: list[dict]，每条 {'index': i, 'fields': [...]}（fields[0]=name_id, fields[1]=portrait）
        tkt_names: dict[int, str]，{tkt_id: 角色名称}
        fa_sprites: list[PIL.Image|None]，Fa.JVG 头像精灵列表（可为空列表）
        multi_select: True=多选模式，False=单选模式
        current_indices: 当前已选中的 WarPC 索引列表（用于回显选中状态）
        excluded_indices: 排除的索引列表（多选模式中防止重复选择）
    """

    def __init__(self, parent, war_pc_records=None, tkt_names=None,
                 fa_sprites=None, multi_select=False,
                 current_indices=None, excluded_indices=None):
        super().__init__(parent)
        self.setWindowTitle("选择 WarPC 角色" + (" (多选)" if multi_select else ""))
        self.resize(520, 560)

        self._records = war_pc_records or []
        self._tkt = tkt_names or {}
        self._fa_sprites = fa_sprites or []
        self._multi = multi_select
        self._excluded = set(excluded_indices or [])
        self._selected_indices = list(current_indices or [])
        self._pixmap_cache = {}

        layout = QVBoxLayout(self)

        # 搜索框
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("🔍"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按名称或索引搜索...")
        self._search.textChanged.connect(self._populate)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["头像", "索引", "名称"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 40)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if multi_select:
            self._table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        else:
            self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        # 已选栏
        self._selected_label = QLabel("")
        self._selected_label.setWordWrap(True)
        self._selected_label.setObjectName("WarpcSelectedLabel")
        layout.addWidget(self._selected_label)
        self._update_selected_label()

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self._populate()

    def showEvent(self, event):
        super().showEvent(event)
        apply_godot_theme(self, self._is_dark_theme())

    @staticmethod
    def _is_dark_theme():
        """沿父窗口链检测当前是否为深色主题。"""
        app = QApplication.instance()
        if app:
            for w in app.topLevelWidgets():
                if hasattr(w, '_is_dark'):
                    return w._is_dark
        return QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _get_name(self, idx):
        """通过 WarPC 索引获取角色名称。"""
        if idx < 0 or idx >= len(self._records):
            return f"未知 #{idx}"
        rec = self._records[idx]
        name_id = rec['fields'][0]
        name = self._tkt.get(name_id)
        if name:
            return name
        return f"未知 #{idx}"

    def _get_pixmap(self, idx, size=(32, 32)):
        """获取 WarPC 索引对应的头像 QPixmap。"""
        cache_key = (idx, size)
        if cache_key in self._pixmap_cache:
            return self._pixmap_cache[cache_key]
        if not self._fa_sprites or idx < 0 or idx >= len(self._records):
            return None
        rec = self._records[idx]
        portrait = rec['fields'][1]
        sprite_idx = portrait * 2  # 大幅图
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites):
            return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None:
            return None
        pix = _pil_to_pixmap(sprite, size)
        self._pixmap_cache[cache_key] = pix
        return pix

    def _populate(self, filter_text=""):
        """填充表格。"""
        self._table.setRowCount(0)
        ft = filter_text.strip().lower()
        for i, rec in enumerate(self._records):
            name = self._get_name(i)
            # 搜索过滤
            if ft and ft not in name.lower() and ft != str(i):
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)

            # 头像列
            lbl = QLabel()
            pix = self._get_pixmap(i)
            if pix:
                lbl.setPixmap(pix)
            else:
                lbl.setText("👤")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 0, lbl)

            # 索引列
            idx_item = QTableWidgetItem(f"#{i}")
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            idx_item.setData(Qt.ItemDataRole.UserRole, i)
            self._table.setItem(row, 1, idx_item)

            # 名称列
            name_item = QTableWidgetItem(name)
            # 已排除的行灰色显示
            if i in self._excluded:
                name_item.setForeground(Qt.GlobalColor.gray)
                idx_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 2, name_item)

            # 回显选中状态
            if i in self._selected_indices:
                self._table.selectRow(row)

    def _on_double_click(self):
        """双击行: 单选模式直接确定。"""
        if not self._multi:
            self._on_accept()

    def _on_accept(self):
        """确定: 收集选中的索引。"""
        selected_rows = self._table.selectionModel().selectedRows()
        indices = []
        for idx in selected_rows:
            row = idx.row()
            item = self._table.item(row, 1)
            if item:
                warpc_idx = item.data(Qt.ItemDataRole.UserRole)
                if warpc_idx not in self._excluded:
                    indices.append(warpc_idx)
        self._selected_indices = indices
        self.accept()

    def _update_selected_label(self):
        """更新已选栏显示。"""
        if not self._selected_indices:
            self._selected_label.setText("")
            self._selected_label.setVisible(False)
            return
        self._selected_label.setVisible(True)
        names = [f"{self._get_name(i)}(#{i})" for i in self._selected_indices]
        self._selected_label.setText(f"已选 ({len(names)}): {', '.join(names)}")

    @property
    def selected_indices(self):
        """返回选中的 WarPC 索引列表。单选时列表长度为 1。"""
        return self._selected_indices

    @property
    def selected_index(self):
        """单选模式: 返回选中的 WarPC 索引，无选中时返回 None。"""
        return self._selected_indices[0] if self._selected_indices else None
