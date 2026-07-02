"""模组元数据编辑对话框 — 加载 .tksmod / .tksmodpak 编辑元数据后保存，不改模组内容"""
import json
import os
import zipfile
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QSpinBox,
    QPushButton, QFileDialog, QMessageBox,
)

from core.mod_packer import read_tksmod_content, rewrite_mod_metadata
from editor_utils.mod_exporter import generate_short_uuid


class ModMetaEditorDialog(QDialog):
    """模组元数据编辑器：打开 .tksmod → 编辑元数据 → 保存/另存为。

    仅修改 mod.json 中的元数据字段，data/* 与 resources/* 内容保持不变。
    """

    def __init__(self, mods_dir: str = "mods", parent=None, initial_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("模组信息编辑")
        self.resize(560, 540)
        self._mods_dir = mods_dir
        self._mod_path: str = ""

        layout = QVBoxLayout(self)

        # ---- 文件选择 ----
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("模组文件:"))
        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("点击「打开…」选择 .tksmod 文件")
        file_row.addWidget(self.edit_path, 1)
        self.btn_open = QPushButton("打开…")
        self.btn_open.clicked.connect(self._on_open)
        file_row.addWidget(self.btn_open)
        layout.addLayout(file_row)

        # ---- 元数据表单 ----
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        row = 0
        grid.addWidget(QLabel("模组 ID *:"), row, 0)
        id_row = QHBoxLayout()
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("唯一标识符")
        self.edit_id.setMaxLength(16)  # 模组 ID 最大 16 位
        # 输入时实时移除所有空格（前后及中间），并保持光标位置
        self.edit_id.textChanged.connect(self._on_id_text_changed)
        id_row.addWidget(self.edit_id)
        self.btn_regen_id = QPushButton("重新生成")
        self.btn_regen_id.clicked.connect(self._regen_id)
        id_row.addWidget(self.btn_regen_id)
        grid.addLayout(id_row, row, 1)

        row += 1
        grid.addWidget(QLabel("名称 *:"), row, 0)
        self.edit_name = QLineEdit()
        grid.addWidget(self.edit_name, row, 1)

        row += 1
        grid.addWidget(QLabel("版本:"), row, 0)
        self.edit_version = QLineEdit()
        grid.addWidget(self.edit_version, row, 1)

        row += 1
        grid.addWidget(QLabel("作者:"), row, 0)
        self.edit_author = QLineEdit()
        grid.addWidget(self.edit_author, row, 1)

        row += 1
        grid.addWidget(QLabel("描述:"), row, 0)
        self.edit_desc = QTextEdit()
        self.edit_desc.setMaximumHeight(80)
        grid.addWidget(self.edit_desc, row, 1)

        row += 1

        row += 1
        grid.addWidget(QLabel("加载顺序:"), row, 0)
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 9999)
        grid.addWidget(self.spin_order, row, 1)

        row += 1
        grid.addWidget(QLabel("游戏版本:"), row, 0)
        self.edit_gamever = QLineEdit()
        grid.addWidget(self.edit_gamever, row, 1)

        row += 1
        grid.addWidget(QLabel("依赖:"), row, 0)
        self.edit_deps = QLineEdit()
        self.edit_deps.setPlaceholderText("逗号分隔的模组 ID")
        grid.addWidget(self.edit_deps, row, 1)

        row += 1
        grid.addWidget(QLabel("冲突:"), row, 0)
        self.edit_conflicts = QLineEdit()
        self.edit_conflicts.setPlaceholderText("逗号分隔的模组 ID")
        grid.addWidget(self.edit_conflicts, row, 1)

        layout.addLayout(grid)

        # 提示
        tip = QLabel("<i>仅修改元数据，模组数据与资源内容保持不变。</i>")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("btnPack")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_saveas = QPushButton("另存为…")
        self.btn_saveas.clicked.connect(self._on_save_as)
        self.btn_saveas.setEnabled(False)
        btn_row.addWidget(self.btn_saveas)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._set_fields_enabled(False)

        # 若传入了初始路径且文件存在，自动加载
        if initial_path and os.path.isfile(initial_path):
            self._load(initial_path)

    # ────────────────────────────────────────────────
    # 字段状态
    # ────────────────────────────────────────────────

    def _fields(self):
        return (self.edit_id, self.btn_regen_id, self.edit_name, self.edit_version,
                self.edit_author, self.edit_desc,
                self.spin_order, self.edit_gamever, self.edit_deps, self.edit_conflicts)

    def _set_fields_enabled(self, enabled: bool):
        for w in self._fields():
            w.setEnabled(enabled)

    # ────────────────────────────────────────────────
    # 打开 / 加载
    # ────────────────────────────────────────────────

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模组文件", self._mods_dir,
            "TKS 模组文件 (*.tksmod *.tksmodpak);;所有文件 (*)"
        )
        if not path:
            return
        self._load(path)

    def _load(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".tksmodpak":
            self._load_tksmodpak(path)
        else:
            self._load_tksmod(path)

    def _load_tksmod(self, path: str):
        content = read_tksmod_content(path)
        if not content.valid:
            QMessageBox.warning(self, "无法加载", f"读取失败: {content.error}")
            return
        self._mod_path = path
        self.edit_path.setText(path)
        self._fill_fields(content.mod_json)

    def _load_tksmodpak(self, path: str):
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                if "mod.json" not in zf.namelist():
                    QMessageBox.warning(self, "无法加载", "该合集文件中缺少 mod.json")
                    return
                mj_str = zf.read("mod.json").decode('utf-8')
                mj = json.loads(mj_str)
        except Exception as e:
            QMessageBox.warning(self, "无法加载", f"读取失败: {e}")
            return

        self._mod_path = path
        self.edit_path.setText(path)
        self._fill_fields(mj)

    def _fill_fields(self, mj: dict):
        self.edit_id.setText(mj.get("id", ""))
        self.edit_name.setText(mj.get("name", ""))
        self.edit_version.setText(mj.get("version", "1.0.0"))
        self.edit_author.setText(mj.get("author", ""))
        self.edit_desc.setPlainText(mj.get("description", ""))

        self.spin_order.setValue(mj.get("load_order", 100))
        self.edit_gamever.setText(mj.get("game_version", "1.0"))
        self.edit_deps.setText(", ".join(mj.get("dependencies", [])))
        self.edit_conflicts.setText(", ".join(mj.get("conflicts", [])))

        self._set_fields_enabled(True)
        self.btn_save.setEnabled(True)
        self.btn_saveas.setEnabled(True)


    # ────────────────────────────────────────────────
    # 收集 / 校验 / 保存
    # ────────────────────────────────────────────────

    def _collect_metadata(self) -> dict:
        deps = [s.strip() for s in self.edit_deps.text().split(",") if s.strip()]
        conflicts = [s.strip() for s in self.edit_conflicts.text().split(",") if s.strip()]
        return {
            "id": self.edit_id.text().strip(),
            "name": self.edit_name.text().strip(),
            "version": self.edit_version.text().strip() or "1.0.0",
            "author": self.edit_author.text().strip(),
            "description": self.edit_desc.toPlainText().strip(),
            "load_order": self.spin_order.value(),
            "game_version": self.edit_gamever.text().strip() or "1.0",
            "dependencies": deps,
            "conflicts": conflicts,
        }

    def _validate(self) -> bool:
        if not self._mod_path:
            QMessageBox.warning(self, "提示", "请先打开一个模组文件")
            return False
        if not self.edit_id.text().strip():
            QMessageBox.warning(self, "必填", "请输入模组 ID")
            self.edit_id.setFocus()
            return False
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, "必填", "请输入模组名称")
            self.edit_name.setFocus()
            return False
        return True

    def _is_pak(self, path: str = None) -> bool:
        """判断给定路径（默认当前打开的文件）是否为 .tksmodpak 合集格式。"""
        p = path or self._mod_path
        return os.path.splitext(p)[1].lower() == ".tksmodpak"

    def _on_save(self):
        if not self._validate():
            return
        if self._is_pak():
            ok, msg = self._save_tksmodpak(self._mod_path)
        else:
            ok, msg = rewrite_mod_metadata(self._mod_path, self._collect_metadata())
        if ok:
            QMessageBox.information(self, "保存成功", f"已更新元数据:\n{self._mod_path}")
        else:
            QMessageBox.critical(self, "保存失败", msg)

    def _on_save_as(self):
        if not self._validate():
            return
        default = os.path.join(self._mods_dir, os.path.basename(self._mod_path))
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default,
            "TKS 模组文件 (*.tksmod *.tksmodpak);;所有文件 (*)"
        )
        if not path:
            return
        if self._is_pak(path):
            ok, msg = self._save_tksmodpak(path)
        else:
            ok, msg = rewrite_mod_metadata(self._mod_path, self._collect_metadata(),
                                           output_path=path)
        if ok:
            QMessageBox.information(self, "保存成功", f"已另存为:\n{path}")
        else:
            QMessageBox.critical(self, "保存失败", msg)

    def _save_tksmodpak(self, path: str) -> tuple[bool, str]:
        """写入 .tksmodpak 的 mod.json 元数据，保留所有 .tksmod 文件不变。"""
        try:
            tmp = path + ".tmp"
            with zipfile.ZipFile(path, 'r') as src, \
                 zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
                meta = self._collect_metadata()
                meta["format"] = "TKSMODPAK"
                meta["format_version"] = 1
                dst.writestr("mod.json",
                            json.dumps(meta, ensure_ascii=False, indent=2))
                for item in src.infolist():
                    if item.filename == "mod.json":
                        continue
                    dst.writestr(item, src.read(item.filename))
            os.replace(tmp, path)
            return True, "保存成功"
        except Exception as e:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False, f"保存失败: {e}"

    def _regen_id(self):
        """重新生成模组 ID（直接覆盖）。"""
        self.edit_id.setText(generate_short_uuid())
        self.edit_id.setFocus()

    def _on_id_text_changed(self, text: str):
        """实时移除模组 ID 中的所有空格（前后及中间），保持光标位置不跳变。"""
        if ' ' not in text:
            return
        cursor = self.edit_id.cursorPosition()
        spaces_before = text[:cursor].count(' ')
        no_space = text.replace(' ', '')
        self.edit_id.blockSignals(True)
        self.edit_id.setText(no_space)
        self.edit_id.blockSignals(False)
        self.edit_id.setCursorPosition(max(0, cursor - spaces_before))
