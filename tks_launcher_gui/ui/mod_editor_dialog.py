"""模组编辑对话框 — 打开 .tksmod/.tksmodpak，添加/删除内部文件，原地保存"""
import json
import os
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidgetItem, QVBoxLayout,
)

from editor_utils.adaptive_table import AdaptiveTableWidget

# MOD 可覆盖配置白名单回退默认 (正式白名单由补丁声明动态推导,
# 经构造参数 allowed_configs 传入; 与 core.mod_loader.allowed_mod_configs 一致)
_ALLOWED_CONFIGS = {"summon_table", "drop_probability"}


class ModEditorDialog(QDialog):
    """模组内容编辑器: 打开 .tksmod/.tksmodpak → 添加/删除内部文件 → 原地保存。

    - .tksmodpak: 可添加/删除内嵌的 .tksmod 文件
    - .tksmod: 可添加/删除 data/、configs/、resources/ 下的文件，
      自动维护 mod.json 中的 components/resources/configs 声明
    """

    def __init__(self, mods_dir: str = "mods", parent=None,
                 initial_path: str | None = None,
                 allowed_configs: set | None = None):
        super().__init__(parent)
        self.setWindowTitle("模组编辑")
        self.resize(720, 520)
        self._mods_dir = mods_dir
        # MOD 可覆盖配置白名单 (动态推导自补丁声明; None = 回退默认集)
        self._allowed_configs = (allowed_configs if allowed_configs is not None
                                 else set(_ALLOWED_CONFIGS))
        self._mod_path: str = ""
        self._is_pak: bool = False
        # 内存中的文件集: {internal_path: bytes}
        self._files: dict[str, bytes] = {}
        self._mod_json: dict = {}
        self._dirty: bool = False

        self._build_ui()

        if initial_path and os.path.isfile(initial_path):
            self._load(initial_path)

    # ────────────────────────────────────────────────
    # UI 构建
    # ────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 文件选择行
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("模组文件:"))
        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("点击「打开…」选择 .tksmod 或 .tksmodpak")
        file_row.addWidget(self.edit_path, 1)
        self.btn_open = QPushButton("打开…")
        self.btn_open.clicked.connect(self._on_open)
        file_row.addWidget(self.btn_open)
        layout.addLayout(file_row)

        # 文件列表
        layout.addWidget(QLabel("文件列表:"))
        self._table = AdaptiveTableWidget(
            0, 3,
            stretch_columns={0},
            minimum_widths=[160, 60, 70],
        )
        self._table.setHorizontalHeaderLabels(["文件路径", "类型", "大小"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加文件…")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_add.setEnabled(False)
        btn_row.addWidget(self.btn_add)

        self.btn_delete = QPushButton("🗑 删除选中")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_row.addWidget(self.btn_delete)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 提示
        self._label_info = QLabel("")
        self._label_info.setObjectName("hintLabel")
        self._label_info.setWordWrap(True)
        layout.addWidget(self._label_info)

        # 底部按钮
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setObjectName("btnPack")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        bottom_row.addWidget(self.btn_save)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self._close_check)
        bottom_row.addWidget(btn_close)
        layout.addLayout(bottom_row)

    # ────────────────────────────────────────────────
    # 打开 / 加载
    # ────────────────────────────────────────────────

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模组文件", self._mods_dir,
            "TKS 模组文件 (*.tksmod *.tksmodpak);;所有文件 (*)")
        if path:
            self._load(path)

    def _load(self, path: str):
        self._mod_path = path
        self._is_pak = path.lower().endswith(".tksmodpak")
        self._files.clear()
        self._mod_json = {}
        self._dirty = False

        try:
            with zipfile.ZipFile(path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    self._files[name] = zf.read(name)
                if "mod.json" in self._files:
                    self._mod_json = json.loads(self._files["mod.json"].decode('utf-8'))
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"读取文件失败:\n{e}")
            return

        self.edit_path.setText(path)
        self._refresh_table()
        self.btn_add.setEnabled(True)
        self.btn_save.setEnabled(False)

        if self._is_pak:
            self._label_info.setText(
                "合集包 (.tksmodpak): 可添加/删除内嵌的 .tksmod 文件。"
                "mod.json 和 preview 图片保留不变。")
        else:
            self._label_info.setText(
                "模组 (.tksmod): 可添加/删除 data/、configs/、resources/ 下的文件。"
                "添加 .json 时自动分类 (白名单配置 → configs/，其它 → data/)，"
                "其它文件 → resources/。mod.json 中的声明自动维护。")

    def _refresh_table(self):
        self._table.setRowCount(0)
        for name in sorted(self._files.keys()):
            ftype = self._classify_file(name)
            data = self._files[name]
            size = len(data)
            size_str = f"{size} B" if size < 1024 else f"{size / 1024:.1f} KB"

            row = self._table.rowCount()
            self._table.insertRow(row)
            item_path = QTableWidgetItem(name)
            if name == "mod.json":
                item_path.setForeground(Qt.GlobalColor.gray)
            path_item = item_path
            self._table.setItem(row, 0, path_item)
            self._table.setItem(row, 1, QTableWidgetItem(ftype))
            self._table.setItem(row, 2, QTableWidgetItem(size_str))

    def _classify_file(self, name: str) -> str:
        if name == "mod.json":
            return "元数据"
        if name.endswith(".tksmod"):
            return "子模组"
        if name.startswith("data/"):
            return "数据"
        if name.startswith("configs/"):
            return "配置"
        if name.startswith("resources/"):
            return "资源"
        if name.startswith("preview"):
            return "预览图"
        return "其他"

    def _on_selection_changed(self):
        has_selection = len(self._table.selectionModel().selectedRows()) > 0
        self.btn_delete.setEnabled(has_selection)

    # ────────────────────────────────────────────────
    # 添加文件
    # ────────────────────────────────────────────────

    def _on_add(self):
        if not self._mod_path:
            return
        if self._is_pak:
            self._add_to_pak()
        else:
            self._add_to_tksmod()

    def _add_to_pak(self):
        """向 .tksmodpak 添加 .tksmod 文件"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 .tksmod 文件", self._mods_dir,
            "TKS 模组 (*.tksmod);;所有文件 (*)")
        if not paths:
            return
        added = 0
        for path in paths:
            fname = os.path.basename(path)
            # 让用户确认/修改包内路径
            internal, ok = QInputDialog.getText(
                self, "设置包内路径",
                f"文件: {fname}\n请输入在包内的路径 (可含子目录，如 mods/{fname}):",
                text=fname)
            if not ok or not internal.strip():
                continue
            internal = internal.strip().lstrip("/")
            if internal in self._files:
                QMessageBox.warning(self, "冲突", f"文件已存在: {internal}")
                continue
            with open(path, 'rb') as f:
                self._files[internal] = f.read()
            added += 1
            self._dirty = True
        if added:
            self._refresh_table()
            self.btn_save.setEnabled(True)
            self._label_info.setText(f"已添加 {added} 个文件，点击「保存」写入原文件。")

    def _add_to_tksmod(self):
        """向 .tksmod 添加数据/配置/资源文件"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "", "所有文件 (*)")
        if not paths:
            return
        added = 0
        for path in paths:
            fname = os.path.basename(path)
            ext = os.path.splitext(fname)[1].lower()
            stem = os.path.splitext(fname)[0]
            # 自动分类建议路径
            if ext == ".json":
                if stem in self._allowed_configs:
                    suggested = f"configs/{fname}"
                else:
                    suggested = f"data/{fname}"
            else:
                suggested = f"resources/{fname}"

            # 让用户确认/修改包内路径
            internal, ok = QInputDialog.getText(
                self, "设置包内路径",
                f"文件: {fname}\n请输入在包内的路径 (如 {suggested}):",
                text=suggested)
            if not ok or not internal.strip():
                continue
            internal = internal.strip().lstrip("/")
            if internal == "mod.json":
                QMessageBox.warning(self, "无效路径", "不能覆盖 mod.json。")
                continue
            if internal in self._files:
                QMessageBox.warning(self, "冲突", f"文件已存在: {internal}")
                continue
            with open(path, 'rb') as f:
                self._files[internal] = f.read()

            # 自动维护 mod.json 声明 (仅对标准目录路径)
            if internal.startswith("data/"):
                self._add_component_entry(internal, stem)
            elif internal.startswith("configs/"):
                self._add_config_entry(internal, stem)
            elif internal.startswith("resources/"):
                self._add_resource_entry(internal, fname)

            added += 1
            self._dirty = True
        if added:
            self._refresh_table()
            self.btn_save.setEnabled(True)
            self._label_info.setText(f"已添加 {added} 个文件，点击「保存」写入原文件。")

    def _add_component_entry(self, internal: str, stem: str):
        comps = self._mod_json.setdefault("components", [])
        if not any(c.get("file") == internal for c in comps):
            comps.append({"file": internal, "target": f"{stem}.dat"})

    def _add_config_entry(self, internal: str, name: str):
        cfgs = self._mod_json.setdefault("configs", [])
        if not any(c.get("file") == internal for c in cfgs):
            cfgs.append({"file": internal, "name": name})

    def _add_resource_entry(self, internal: str, fname: str):
        res = self._mod_json.setdefault("resources", [])
        if not any(r.get("file") == internal for r in res):
            res.append({"file": internal, "target": fname})

    # ────────────────────────────────────────────────
    # 删除文件
    # ────────────────────────────────────────────────

    def _on_delete(self):
        if not self._mod_path:
            return
        rows = sorted(set(idx.row() for idx in self._table.selectionModel().selectedRows()),
                      reverse=True)
        if not rows:
            return
        names = [self._table.item(r, 0).text() for r in rows]
        # 不允许删除 mod.json
        if "mod.json" in names:
            names = [n for n in names if n != "mod.json"]
            if not names:
                QMessageBox.warning(self, "无法删除", "mod.json 是必需文件，不能删除。")
                return
            QMessageBox.information(self, "提示", "mod.json 不可删除，已跳过。")

        reply = QMessageBox.question(self, "确认删除",
            f"确定要删除以下 {len(names)} 个文件吗？\n\n" + "\n".join(names))
        if reply != QMessageBox.StandardButton.Yes:
            return

        for name in names:
            del self._files[name]
            # 从 mod.json 中移除引用
            self._remove_from_mod_json(name)
            self._dirty = True

        self._refresh_table()
        self.btn_save.setEnabled(self._dirty)
        if self._dirty:
            self._label_info.setText(f"已删除 {len(names)} 个文件，点击「保存」写入原文件。")

    def _remove_from_mod_json(self, internal: str):
        """从 mod.json 的 components/resources/configs 中移除引用"""
        for key in ("components", "resources", "configs"):
            entries = self._mod_json.get(key, [])
            self._mod_json[key] = [e for e in entries if e.get("file") != internal]

    # ────────────────────────────────────────────────
    # 保存
    # ────────────────────────────────────────────────

    def _on_save(self):
        if not self._mod_path:
            return
        tmp = self._mod_path + ".tmp"
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 先写 mod.json
                mod_json_str = json.dumps(self._mod_json,
                                          ensure_ascii=False, indent=2)
                zf.writestr("mod.json", mod_json_str)
                # 写其他文件 (按名称排序，保持稳定顺序)
                for name in sorted(self._files.keys()):
                    if name == "mod.json":
                        continue
                    zf.writestr(name, self._files[name])
            os.replace(tmp, self._mod_path)
            self._dirty = False
            self.btn_save.setEnabled(False)
            QMessageBox.information(self, "保存成功",
                f"已更新模组文件:\n{self._mod_path}")
        except Exception as e:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            QMessageBox.critical(self, "保存失败", f"保存失败:\n{e}")

    # ────────────────────────────────────────────────
    # 关闭
    # ────────────────────────────────────────────────

    def _close_check(self):
        if self._dirty:
            reply = QMessageBox.question(self, "未保存的更改",
                "有未保存的更改，确定要关闭吗？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.close()
