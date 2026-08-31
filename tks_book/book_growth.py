# -*- coding: utf-8 -*-
"""tks_book 角色成长数据表弹窗 — 基于反编译公式 (sub_410674/sub_43066C)

成长公式 (每升一级):
  选择成长除数:
    level < 21       → growth_early  (field[264])
    21 ≤ level < 41  → growth_mid    (field[265])
    level ≥ 41       → growth_late   (field[266])
  stat += stat // divisor + 1   (hp/mp/atk/def/hit/eva)
  spd  += 1                     (固定)
  hp = min(hp, 9999);  mp = min(mp, 9999)
等级上限: 60
注意: 除数越小成长越快 (每级约涨 stat/divisor + 1)
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton,
)

from editor_utils import theme_manager
from editor_utils.theme_switcher import apply_theme_to_window
from editor_utils.window_theme import apply_titlebar_theme


class GrowthTableDialog(QDialog):
    """角色逐级成长数据表 (只读查看器版本, 无grp加成)"""

    STAT_CAP_HPMP = 9999
    MAX_LEVEL = 60

    _IDX_HP = 7
    _IDX_MP = 9
    _IDX_ATK = 11
    _IDX_DEF = 13
    _IDX_HIT = 15
    _IDX_EVA = 17
    _IDX_SPD = 19
    _IDX_GE = 264
    _IDX_GM = 265
    _IDX_GL = 266

    STAT_LABELS = ["HP", "MP", "攻击", "防御", "命中", "闪避", "速度"]

    def __init__(self, parent, rec, char_name, theme_id="gpt-dark"):
        super().__init__(parent)
        self.setWindowTitle(f"成长数据表 — {char_name}")
        self.resize(900, 650)
        self._f = rec['fields']
        self._char_name = char_name
        self._rec_idx = rec['index']

        apply_theme_to_window(self, theme_id, persist=False)
        is_dark = theme_manager.is_dark(theme_id)

        if is_dark:
            self._CLR_DELTA = QColor("#55b572")
        else:
            self._CLR_DELTA = QColor("#2d7a2d")

        self._cur_level = max(1, self._f[2])
        self._cur_stats = [
            self._f[self._IDX_HP], self._f[self._IDX_MP],
            self._f[self._IDX_ATK], self._f[self._IDX_DEF],
            self._f[self._IDX_HIT], self._f[self._IDX_EVA],
            self._f[self._IDX_SPD],
        ]
        self._ge = self._f[self._IDX_GE]
        self._gm = self._f[self._IDX_GM]
        self._gl = self._f[self._IDX_GL]

        self._base_stats = [self._estimate_base(cur, self._cur_level)
                            for cur in self._cur_stats]
        self._table_data = self._build_table()
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        apply_titlebar_theme(self, self._theme_id)

    def _get_divisor(self, level):
        if level >= 41:
            return self._gl
        if level >= 21:
            return self._gm
        return self._ge

    def _simulate_stat(self, base, from_level, to_level):
        val = base
        for lvl in range(from_level, to_level):
            d = self._get_divisor(lvl)
            if d > 0:
                val += val // d + 1
            else:
                val += 1
        return val

    def _estimate_base(self, current_stat, current_level):
        if current_level <= 1:
            return current_stat
        lo, hi = 1, max(current_stat, 1)
        while lo < hi:
            mid = (lo + hi) // 2
            sim = self._simulate_stat(mid, 1, current_level)
            if sim < current_stat:
                lo = mid + 1
            else:
                hi = mid
        if lo > 1:
            sim_lo = self._simulate_stat(lo, 1, current_level)
            sim_lo1 = self._simulate_stat(lo - 1, 1, current_level)
            if abs(sim_lo1 - current_stat) <= abs(sim_lo - current_stat):
                return lo - 1
        return lo

    def _build_table(self):
        data = []
        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base = list(self._base_stats[:6]) + [spd_base]
        prev = list(base)
        for lvl in range(1, self.MAX_LEVEL + 1):
            if lvl == 1:
                stats = list(base)
            else:
                d = self._get_divisor(lvl - 1)
                stats = []
                for i in range(6):
                    v = prev[i]
                    stats.append(v + (v // d + 1) if d > 0 else v + 1)
                stats.append(prev[6] + 1)
            capped = list(stats)
            capped[0] = min(capped[0], self.STAT_CAP_HPMP)
            capped[1] = min(capped[1], self.STAT_CAP_HPMP)
            deltas = [capped[i] - prev[i] for i in range(7)] if lvl > 1 else [0] * 7
            divisor = self._get_divisor(lvl)
            data.append({
                'level': lvl, 'divisor': divisor, 'stats': capped,
                'deltas': deltas, 'is_current': (lvl == self._cur_level),
            })
            prev = capped
        return data

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.setSpacing(2)
        info_layout.addWidget(QLabel(
            f"<b>{self._char_name}</b>  (编号 #{self._rec_idx},  当前等级 {self._cur_level})"))
        info_layout.addWidget(QLabel(
            f"成长除数: 初期={self._ge} (Lv1-20) | "
            f"中期={self._gm} (Lv21-40) | "
            f"后期={self._gl} (Lv41-60)  (除数越小成长越快)"))
        info_layout.addWidget(QLabel(
            f"公式: stat += stat // divisor + 1  |  速度: 每级固定+1  |  HP/MP上限={self.STAT_CAP_HPMP}"))

        spd_base = max(0, self._cur_stats[6] - (self._cur_level - 1))
        base_parts = [f"{l}={b}" for l, b in zip(self.STAT_LABELS[:6], self._base_stats[:6])]
        base_parts.append(f"速度={spd_base} (固定+1/级)")
        base_lbl = QLabel(f"<b>估算 1 级基础值</b>:  {'  |  '.join(base_parts)}")
        base_lbl.setWordWrap(True)
        info_layout.addWidget(base_lbl)
        layout.addWidget(info_frame)

        cols = ["等级", "除数"]
        for s in self.STAT_LABELS:
            cols += [s, "Δ"]
        self._table = QTableWidget(len(self._table_data), len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setProperty("class", "GrowthTable")
        self._table.setFont(QFont("Consolas", 9))

        font_bold = QFont("Consolas", 9, QFont.Bold)
        delta_cols = {3, 5, 7, 9, 11, 13, 15}
        for row, d in enumerate(self._table_data):
            is_cur = d['is_current']
            vals = [str(d['level']), str(d['divisor'])]
            for si in range(7):
                vals.append(str(d['stats'][si]))
                delta = d['deltas'][si]
                vals.append(f"+{delta}" if delta > 0 else str(delta))
            for ci, txt in enumerate(vals):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                if is_cur:
                    item.setFont(font_bold)
                if ci in delta_cols and d['level'] > 1:
                    item.setForeground(self._CLR_DELTA)
                self._table.setItem(row, ci, item)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 48)
        self._table.setColumnWidth(1, 48)
        for ci in range(2, len(cols)):
            hh.setSectionResizeMode(ci, QHeaderView.Fixed)
            self._table.setColumnWidth(ci, 55)
        # 保留密集成长列的默认宽度，最大化时由最后一个可见列填充额外空间。
        hh.setStretchLastSection(True)

        for row, d in enumerate(self._table_data):
            if d['is_current']:
                self._table.scrollToItem(self._table.item(row, 0))
                break

        layout.addWidget(self._table, 1)

        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(QPushButton("关闭", clicked=self.close))
        layout.addLayout(bl)
