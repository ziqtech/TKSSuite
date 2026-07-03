"""
ConfigPanelBase — 配置编辑面板抽象基类
所有配置面板继承此类，实现 load/save/is_modified/reset 接口。
主窗口通过 modified 信号统一管理标签页标题的 `*` 标记。
"""
import json
import os
import copy
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal, Qt


class ConfigPanelBase(QWidget):
    """配置编辑面板基类。

    子类需设置:
        config_name: 配置文件名（不含 .json），如 "drop_probability"
        tab_label:   标签页显示名称，如 "掉落概率"

    子类需实现:
        _populate_ui(data):  从 dict 填充 UI 控件
        _collect_ui() -> dict:  从 UI 控件收集数据为 dict
    """

    config_name: str = ""
    tab_label: str = ""

    # 信号: 面板内容被修改时发射
    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._baseline: dict | None = None   # 加载时的原始数据快照
        self._data: dict | None = None       # 当前内存中的数据（含 UI 修改）
        self._config_path: Path | None = None  # 当前配置文件路径
        self._loaded = False

    # ── 公共接口 ──

    def load(self, config_dir: Path) -> bool:
        """从 config_dir / f"{config_name}.json" 读取 JSON，填充 UI。
        加载时深拷贝一份 _baseline 供 reset() 使用。
        """
        path = config_dir / f"{self.config_name}.json"
        self._config_path = path
        if not path.exists():
            self._loaded = False
            self._show_missing()
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self._loaded = False
            self._show_error(str(e))
            return False

        self._data = data
        self._baseline = copy.deepcopy(data)
        self._populate_ui(data)
        self._loaded = True
        return True

    def save(self) -> bool:
        """从 UI 收集数据，写回 JSON 文件（原子写入）。成功后清除 dirty。"""
        if not self._loaded or self._config_path is None:
            return False
        data = self._collect_ui()
        # 合并: 保留原始数据中面板不认识的键
        merged = self._merge_with_baseline(data)
        # 原子写入
        tmp_path = self._config_path.with_suffix('.json.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(self._config_path))
        except OSError:
            if tmp_path.exists():
                tmp_path.unlink()
            return False
        self._data = merged
        self._baseline = copy.deepcopy(merged)
        return True

    def is_modified(self) -> bool:
        """返回是否有未保存修改（对比当前 UI 数据与 _baseline）。"""
        if not self._loaded or self._baseline is None:
            return False
        current = self._collect_ui()
        merged = self._merge_with_baseline(current)
        return merged != self._baseline

    def reset(self) -> None:
        """丢弃修改，用 _baseline 快照重新填充 UI。"""
        if self._baseline is not None:
            self._data = copy.deepcopy(self._baseline)
            self._populate_ui(self._data)

    def set_game_data(self, war_pc_records, tkt_names, fa_sprites, skill_names=None) -> None:
        """接收主窗口加载的游戏数据。默认空实现，SummonTablePanel 覆盖。"""
        pass

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ── 子类需实现的接口 ──

    def _populate_ui(self, data: dict) -> None:
        """从 dict 填充 UI 控件。子类必须实现。"""
        raise NotImplementedError

    def _collect_ui(self) -> dict:
        """从 UI 控件收集数据为 dict。子类必须实现。
        返回的 dict 只需包含面板管理的键，_merge_with_baseline 会保留未知键。
        """
        raise NotImplementedError

    # ── 内部工具 ──

    def _merge_with_baseline(self, current: dict) -> dict:
        """将当前 UI 数据与 baseline 合并，保留 baseline 中面板不认识的键。
        面板管理的键使用 current 的值，其余使用 baseline 的值。
        若 current 中某键值为 None，表示面板主动删除该键（从结果中移除）。
        """
        if self._baseline is None:
            # 没有 baseline 时，直接返回 current（过滤 None）
            return {k: v for k, v in current.items() if v is not None}
        merged = copy.deepcopy(self._baseline)
        for k, v in current.items():
            if v is None:
                merged.pop(k, None)  # 主动删除键
            else:
                merged[k] = v
        return merged

    def _mark_dirty(self) -> None:
        """子类调用此方法标记面板已修改（发射 modified 信号）。"""
        self.modified.emit()

    def _show_missing(self) -> None:
        """配置文件缺失时显示占位提示。子类可覆盖。"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(f"配置文件不存在: {self.config_name}.json")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

    def _show_error(self, msg: str) -> None:
        """配置文件加载错误时显示错误提示。子类可覆盖。"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(f"加载失败: {msg}")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
