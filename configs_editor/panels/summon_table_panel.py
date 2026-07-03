"""
SummonTablePanel — 召唤技能→WarPC 映射配置面板
编辑 summon_table.json 中的技能键→WarPC索引 + 可选 _random 数组。
包含 SummonEditDialog 编辑对话框。
"""
import re
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QListWidget, QListWidgetItem, QMessageBox, QFrame,
    QApplication, QToolButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage, QIcon

from editor_utils.window_theme import apply_godot_theme
from editor_utils.picker_dialogs import WarpcPickerDialog

from .base_panel import ConfigPanelBase


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


# ── 召唤表键解析工具 ──

def _parse_skill_key(key: str):
    """解析 summon_table.json 的键名。
    返回: (skill_num:int, suffix:str) 如 (222, ""), (222, "_random"), (251, "_a")
    无法解析的键返回 None。
    """
    m = re.match(r'^skill_(\d+)(_random|_a|_b)?$', key)
    if not m:
        return None
    skill_num = int(m.group(1))
    suffix = m.group(2) or ""
    return (skill_num, suffix)


def _build_skill_rows(data: dict, skill_names: dict | None = None):
    """从 JSON 数据构建表格行数据。
    若提供 skill_names (来自 TKSkill.dat)，优先使用技能真实名称作为 label。
    返回: list[dict]，每条含 skill_key, skill_num, skill_label, main_target, random_list, is_dual
    """
    # 收集所有 skill_NNN 键
    skills = {}  # skill_num -> {"main": int|None, "random": list[int]|None, "a": int|None, "b": int|None, "desc": str}
    for key, val in data.items():
        parsed = _parse_skill_key(key)
        if parsed is None:
            continue
        skill_num, suffix = parsed
        if skill_num not in skills:
            skills[skill_num] = {"main": None, "random": None, "a": None, "b": None, "desc": ""}

        if suffix == "":
            skills[skill_num]["main"] = val
        elif suffix == "_random":
            skills[skill_num]["random"] = list(val) if isinstance(val, list) else []
        elif suffix == "_a":
            skills[skill_num]["a"] = val
            skills[skill_num]["main"] = val  # 用于显示
        elif suffix == "_b":
            skills[skill_num]["b"] = val

        # 尝试获取说明
        desc_key = f"skill_{skill_num}_说明"
        if desc_key in data:
            skills[skill_num]["desc"] = str(data[desc_key])

    rows = []
    for skill_num in sorted(skills.keys()):
        info = skills[skill_num]
        is_dual = info["a"] is not None or info["b"] is not None
        main = info["main"] if info["main"] is not None else (info["a"] or 0)
        random_list = info["random"] or []
        # 简化技能名称为显示标签
        desc = info["desc"]
        # 若加载了 TKSkill.dat，优先使用真实技能名称
        label = ""
        if skill_names and skill_num in skill_names:
            label = skill_names[skill_num]
        if not label:
            # 回退: 从 JSON 说明中提取 (如 "技能228 召喚麒麟 → ..." → "召喚麒麟")
            m = re.match(r'^技能\d+\s+(\S+)', desc)
            if m:
                label = m.group(1)
        if not label:
            label = f"skill_{skill_num}"

        rows.append({
            "skill_num": skill_num,
            "skill_key": f"skill_{skill_num}",
            "label": label,
            "desc": desc,
            "main_target": main,
            "random_list": random_list,
            "is_dual": is_dual,
            "a": info["a"],
            "b": info["b"],
        })
    return rows


class SummonEditDialog(QDialog):
    """召唤表编辑对话框 — 编辑单个技能的 WarPC 目标和随机候选。"""

    def __init__(self, parent, row_data: dict, war_pc_records=None,
                 tkt_names=None, fa_sprites=None):
        super().__init__(parent)
        self._row = row_data
        self._records = war_pc_records or []
        self._tkt = tkt_names or {}
        self._fa_sprites = fa_sprites or []
        self._pixmap_cache = {}

        self._main_target = row_data["main_target"]
        self._random_list = list(row_data["random_list"])
        self._is_dual = row_data["is_dual"]
        self._a_target = row_data.get("a")
        self._b_target = row_data.get("b")

        self.setWindowTitle(f"编辑: 技能{row_data['skill_num']} {row_data['label']}")
        self.resize(420, 480)
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        is_dark = False
        app = QApplication.instance()
        if app:
            for w in app.topLevelWidgets():
                if hasattr(w, '_is_dark'):
                    is_dark = w._is_dark
                    break
        apply_godot_theme(self, is_dark)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 主召唤目标 ──
        layout.addWidget(QLabel("<b>🎯 主目标 (无多随机时使用)</b>"))

        if self._is_dual:
            # 双值键: a/b 两个选择器
            self._a_sel = self._make_target_selector(layout, "分支A (else)")
            self._b_sel = self._make_target_selector(layout, "分支B (if)")
            self._a_sel['btn'].clicked.connect(self._on_select_a)
            self._b_sel['btn'].clicked.connect(self._on_select_b)
            self._update_ab_displays()
        else:
            self._main_sel = self._make_target_selector(layout, "目标")
            self._main_sel['btn'].clicked.connect(self._on_select_main)
            self._update_main_display()

        # ── 随机候选列表 ──
        rand_header = QHBoxLayout()
        rand_header.addWidget(QLabel("<b>🎲 多随机池 (优先，配置后覆盖主目标)</b>"))
        rand_header.addStretch()
        layout.addLayout(rand_header)

        self._rand_list = QListWidget()
        self._rand_list.setMaximumHeight(160)
        self._rand_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        layout.addWidget(self._rand_list)

        # 随机候选操作按钮
        rand_btn_row = QHBoxLayout()
        btn_add_rand = QPushButton("➕ 添加…")
        btn_add_rand.clicked.connect(self._on_add_random)
        rand_btn_row.addWidget(btn_add_rand)

        btn_del_rand = QPushButton("🗑 删除")
        btn_del_rand.clicked.connect(self._on_del_random)
        rand_btn_row.addWidget(btn_del_rand)

        btn_up = QPushButton("🔼 上移")
        btn_up.clicked.connect(lambda: self._move_random(-1))
        rand_btn_row.addWidget(btn_up)

        btn_down = QPushButton("🔽 下移")
        btn_down.clicked.connect(lambda: self._move_random(1))
        rand_btn_row.addWidget(btn_down)

        rand_btn_row.addStretch()
        layout.addLayout(rand_btn_row)

        self._refresh_random_list()

        layout.addStretch()

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("✅ 确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def _make_target_selector(self, parent_layout, label_text):
        """创建一个目标选择行: 标签 + 显示区(头像+名称) + 选择按钮。
        返回 dict: {'icon': QLabel, 'name': QLabel, 'btn': QPushButton}
        """
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text + ":"))

        # 显示区: 头像图标 + 名称
        display_widget = QWidget()
        display_layout = QHBoxLayout(display_widget)
        display_layout.setContentsMargins(4, 2, 4, 2)
        display_layout.setSpacing(4)

        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setProperty("class", "TargetIcon")
        display_layout.addWidget(icon_label)

        name_label = QLabel()
        name_label.setProperty("class", "TargetName")
        name_label.setMinimumHeight(20)
        display_layout.addWidget(name_label, 1)

        display_widget.setProperty("class", "TargetDisplay")
        display_widget.setMinimumHeight(30)
        row.addWidget(display_widget, 1)

        btn = QPushButton("🔍 选择…")
        row.addWidget(btn)

        container = QWidget()
        container.setLayout(row)
        parent_layout.addWidget(container)

        return {'icon': icon_label, 'name': name_label, 'btn': btn}

    def _get_name(self, idx):
        if not self._records:
            return f"WarPC #{idx}"
        if idx < 0 or idx >= len(self._records):
            return f"未知 #{idx}"
        rec = self._records[idx]
        name_id = rec['fields'][0]
        name = self._tkt.get(name_id)
        return f"{name} (#{idx})" if name else f"未知 #{idx}"

    def _get_icon_pixmap(self, idx):
        """获取 WarPC 索引对应的头像 QPixmap (24x24)。"""
        cache_key = idx
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
        pix = _pil_to_pixmap(sprite, (24, 24))
        self._pixmap_cache[cache_key] = pix
        return pix

    def _update_target_display(self, sel: dict, idx):
        """更新一个目标选择器的显示: 头像 + 名称。"""
        icon_label = sel['icon']
        name_label = sel['name']
        pix = self._get_icon_pixmap(idx)
        if pix:
            icon_label.setPixmap(pix)
        else:
            icon_label.setText("👤")
        name_label.setText(self._get_name(idx))

    def _update_main_display(self):
        if hasattr(self, '_main_sel'):
            self._update_target_display(self._main_sel, self._main_target)

    def _update_ab_displays(self):
        if hasattr(self, '_a_sel'):
            self._update_target_display(self._a_sel, self._a_target or 0)
        if hasattr(self, '_b_sel'):
            self._update_target_display(self._b_sel, self._b_target or 0)

    def _on_select_main(self):
        """点击主目标选择按钮 — 弹出单选 WarPC 选择器。"""
        dlg = WarpcPickerDialog(self, self._records, self._tkt, self._fa_sprites,
                                multi_select=False,
                                current_indices=[self._main_target])
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_indices:
            self._main_target = dlg.selected_indices[0]
            self._update_main_display()

    def _on_select_a(self):
        """点击分支 A 选择按钮。"""
        excluded = [v for v in [self._b_target] if v is not None]
        dlg = WarpcPickerDialog(self, self._records, self._tkt, self._fa_sprites,
                                multi_select=False,
                                current_indices=[self._a_target or 0],
                                excluded_indices=excluded)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_indices:
            self._a_target = dlg.selected_indices[0]
            self._update_ab_displays()

    def _on_select_b(self):
        """点击分支 B 选择按钮。"""
        excluded = [v for v in [self._a_target] if v is not None]
        dlg = WarpcPickerDialog(self, self._records, self._tkt, self._fa_sprites,
                                multi_select=False,
                                current_indices=[self._b_target or 0],
                                excluded_indices=excluded)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_indices:
            self._b_target = dlg.selected_indices[0]
            self._update_ab_displays()

    def _refresh_random_list(self):
        self._rand_list.clear()
        for idx in self._random_list:
            item = QListWidgetItem(self._get_name(idx))
            item.setData(Qt.ItemDataRole.UserRole, idx)
            pix = self._get_icon_pixmap(idx)
            if pix:
                item.setIcon(QIcon(pix))
            self._rand_list.addItem(item)

    def _on_add_random(self):
        """弹出 WarPC 选择器（多选模式）添加随机候选。"""
        excluded = list(set(self._random_list))

        dlg = WarpcPickerDialog(self, self._records, self._tkt, self._fa_sprites,
                                multi_select=True,
                                current_indices=[],
                                excluded_indices=excluded)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for idx in dlg.selected_indices:
                if idx not in self._random_list and len(self._random_list) < 8:
                    self._random_list.append(idx)
            self._refresh_random_list()

    def _on_del_random(self):
        row = self._rand_list.currentRow()
        if 0 <= row < len(self._random_list):
            del self._random_list[row]
            self._refresh_random_list()

    def _move_random(self, direction):
        row = self._rand_list.currentRow()
        new_row = row + direction
        if 0 <= row < len(self._random_list) and 0 <= new_row < len(self._random_list):
            self._random_list[row], self._random_list[new_row] = \
                self._random_list[new_row], self._random_list[row]
            self._refresh_random_list()
            self._rand_list.setCurrentRow(new_row)

    def _on_ok(self):
        """确定: 收集数据。"""
        self.accept()

    # ── 公共接口 ──

    def get_main_target(self) -> int:
        if self._is_dual:
            return self._a_target or 0
        return self._main_target

    def get_a_target(self):
        return self._a_target

    def get_b_target(self):
        return self._b_target

    def get_random_list(self) -> list:
        return list(self._random_list)

    @property
    def is_dual(self) -> bool:
        return self._is_dual


class SummonTablePanel(ConfigPanelBase):
    config_name = "summon_table"
    tab_label = "召唤表"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._war_pc_records = []
        self._tkt_names = {}
        self._fa_sprites = []
        self._skill_names = {}
        self._game_data_loaded = False
        self._rows = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 未加载 TKS 目录提示条 ──
        self._hint_bar = QFrame()
        self._hint_bar.setObjectName("SummonHintBar")
        hint_layout = QHBoxLayout(self._hint_bar)
        hint_layout.setContentsMargins(8, 4, 8, 4)
        hint_label = QLabel("ℹ️ 未加载 TKS 目录，当前显示原始索引。点击此处加载 TKS 目录以显示角色名称和头像。")
        hint_label.setObjectName("SummonHintLabel")
        hint_layout.addWidget(hint_label)
        hint_layout.addStretch()
        self._hint_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hint_bar.mousePressEvent = lambda e: self._request_load_tks()
        self._hint_bar.setVisible(False)
        layout.addWidget(self._hint_bar)

        # ── 搜索 ──
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按技能名称或编号搜索...")
        self._search.textChanged.connect(self._refresh_table)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)

        # ── 表格 ──
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["技能", "技能名称", "主目标", "多随机池(优先)", "操作"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(self._on_edit_row)
        layout.addWidget(self._table)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("🔄 恢复默认")
        btn_reset.clicked.connect(self.reset)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _get_name(self, idx):
        if not self._game_data_loaded:
            return f"WarPC #{idx}"
        if idx < 0 or idx >= len(self._war_pc_records):
            return f"未知 #{idx}"
        rec = self._war_pc_records[idx]
        name_id = rec['fields'][0]
        name = self._tkt_names.get(name_id)
        return f"{name} (#{idx})" if name else f"未知 #{idx}"

    def _get_icon_pixmap(self, idx, size=(20, 20)):
        """获取 WarPC 索引对应的头像 QPixmap。"""
        if not self._game_data_loaded or not self._fa_sprites:
            return None
        if idx < 0 or idx >= len(self._war_pc_records):
            return None
        rec = self._war_pc_records[idx]
        portrait = rec['fields'][1]
        sprite_idx = portrait * 2
        if sprite_idx < 0 or sprite_idx >= len(self._fa_sprites):
            return None
        sprite = self._fa_sprites[sprite_idx]
        if sprite is None:
            return None
        return _pil_to_pixmap(sprite, size)

    def _refresh_table(self):
        """填充表格。"""
        ft = self._search.text().strip().lower()
        self._table.setRowCount(0)

        for row in self._rows:
            # 搜索过滤
            if ft:
                match = (ft in row["label"].lower() or
                         ft in str(row["skill_num"]) or
                         ft in row["desc"].lower())
                if not match:
                    continue

            r = self._table.rowCount()
            self._table.insertRow(r)

            # 技能键
            key_item = QTableWidgetItem(row["skill_key"])
            key_item.setToolTip(row["desc"])
            self._table.setItem(r, 0, key_item)

            # 技能名称
            label_item = QTableWidgetItem(row["label"])
            label_item.setToolTip(row["desc"])
            self._table.setItem(r, 1, label_item)

            # 主目标 (多随机生效时灰显)
            if row["is_dual"]:
                a_name = self._get_name(row.get("a") or 0)
                b_name = self._get_name(row.get("b") or 0)
                target_text = f"A: {a_name}  |  B: {b_name}"
                if row["random_list"]:
                    target_text += "  (被多随机覆盖)"
            else:
                target_text = self._get_name(row["main_target"])
                if row["random_list"]:
                    target_text += "  (被多随机覆盖)"
            target_item = QTableWidgetItem(target_text)
            if row["random_list"]:
                target_item.setForeground(Qt.GlobalColor.gray)
            pix = self._get_icon_pixmap(row["main_target"])
            if pix:
                target_item.setIcon(QIcon(pix))
            self._table.setItem(r, 2, target_item)

            # 多随机池
            if row["random_list"]:
                rand_names = [self._get_name(idx) for idx in row["random_list"]]
                rand_text = ", ".join(rand_names)
                rand_item = QTableWidgetItem(rand_text)
                pix = self._get_icon_pixmap(row["random_list"][0])
                if pix:
                    rand_item.setIcon(QIcon(pix))
            else:
                rand_item = QTableWidgetItem("-")
            self._table.setItem(r, 3, rand_item)

            # 操作列 (编辑按钮)
            edit_btn = QToolButton()
            edit_btn.setText("✏️ 编辑")
            edit_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            edit_btn.setAutoRaise(True)
            edit_btn.setToolTip("编辑此行")
            edit_btn.clicked.connect(lambda checked, idx=r: self._on_edit_row_idx(idx))
            self._table.setCellWidget(r, 4, edit_btn)

    def _on_edit_row(self, index):
        """双击行编辑。"""
        self._on_edit_row_idx(index.row())

    def _on_edit_row_idx(self, row_idx):
        """点击编辑按钮编辑指定行。"""
        if row_idx < 0 or row_idx >= len(self._rows):
            return
        row = self._rows[row_idx]
        dlg = SummonEditDialog(self, row, self._war_pc_records,
                                self._tkt_names, self._fa_sprites)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 更新行数据
            if row["is_dual"]:
                row["a"] = dlg.get_a_target()
                row["b"] = dlg.get_b_target()
                row["main_target"] = row["a"] or 0
            else:
                row["main_target"] = dlg.get_main_target()
            row["random_list"] = dlg.get_random_list()
            self._refresh_table()
            self._mark_dirty()

    def _request_load_tks(self):
        """提示主窗口加载 TKS 目录。"""
        main_win = self.window()
        if hasattr(main_win, 'load_tks_directory'):
            main_win.load_tks_directory()

    # ── ConfigPanelBase 实现 ──

    def set_game_data(self, war_pc_records, tkt_names, fa_sprites, skill_names=None):
        self._war_pc_records = war_pc_records or []
        self._tkt_names = tkt_names or {}
        self._fa_sprites = fa_sprites or []
        self._skill_names = skill_names or {}
        self._game_data_loaded = bool(self._war_pc_records)
        self._hint_bar.setVisible(not self._game_data_loaded)
        # 用 TKSkill.dat 真名重建技能行
        if self._loaded and self._data is not None:
            self._rows = _build_skill_rows(self._data, self._skill_names)
        self._refresh_table()

    def _populate_ui(self, data: dict):
        self._rows = _build_skill_rows(data, self._skill_names)
        self._game_data_loaded = bool(self._war_pc_records)
        self._hint_bar.setVisible(not self._game_data_loaded and self._loaded)
        self._refresh_table()

    def _collect_ui(self) -> dict:
        """从行数据收集为 JSON dict。
        保留所有 _说明、_多随机*说明 等元数据键（通过 _merge_with_baseline）。
        """
        result = {}
        for row in self._rows:
            skill_num = row["skill_num"]
            key = f"skill_{skill_num}"

            if row["is_dual"]:
                result[f"skill_{skill_num}_a"] = row.get("a") or 0
                result[f"skill_{skill_num}_b"] = row.get("b") or 0
            else:
                result[key] = row["main_target"]

            if row["random_list"]:
                result[f"skill_{skill_num}_random"] = list(row["random_list"])
            elif f"skill_{skill_num}_random" in (self._baseline or {}):
                # 原来有 _random 但现在清空了，主动删除该键
                result[f"skill_{skill_num}_random"] = None

        return result
