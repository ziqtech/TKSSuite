#!/usr/bin/env python3
"""
WarPC 表格编辑模式 (model/view 虚拟化)
===========================================================
与表单模式共享 WarpcEditorV2.records 唯一数据源:
  - WarpcTableModel: QAbstractTableModel, 行=角色, 列=字段 (按列集预设)
  - 列集预设: 核心属性 / 装备与技能 / 成长·奖励·掉落 / 技能学习矩阵 /
    全部命名字段 / Raw 527列
  - Delegates: int→QSpinBox, enum→EditorComboBox;
    引用/掩码类字段 (skill_ref/item_*_ref/flags/use_right/status_mask)
    双击弹出与表单模式相同的选择器弹窗
  - 批量编辑: 行筛选 / TSV 复制粘贴 (Ctrl+C/V) / 选区向下填充 (Ctrl+D)
  - 修改值高亮: 与 editor._original_records 对比, 已修改单元格橙色显示
"""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableView, QStyledItemDelegate, QSpinBox, QDialog,
    QAbstractItemView, QApplication, QHeaderView, QAbstractSpinBox, QMenu,
)
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QEvent,
    QRect, QItemSelection, QItemSelectionModel, QTimer,
)

from warpc_schema import (
    FIELD_SCHEMA, SCHEMA_GROUPS, WARPC_FIELD_COUNT,
    SKILL_LEARN_COUNT, SKILL_LEARN_BASE, SKILL_LEARN_STATES,
    STATUS_RESIST_BASE, STATUS_RESIST_COUNT,
    STATUS_SLOT_BASE, STATUS_SLOT_COUNT,
    INT16_MIN, INT16_MAX, clamp_int16,
    get_packed_byte, set_packed_byte, parse_enum_value,
    FLAG_DEFS,
)
from editor_utils.ui_helpers import EditorComboBox
from editor_utils.picker_dialogs import STATUS_NAMES
from editor_utils.search_utils import search_match
from editor_utils.search_input import SearchInput

# 双击弹出选择器的字段类型
PICKER_FTYPES = {'skill_ref', 'item_idx_ref', 'item_id_ref',
                 'flags', 'use_right', 'status_mask'}

# 修改值高亮色 (深/浅主题通用的橙色系)
# 修改标记色 (阶段 2 豁免: 领域语义色)
CLR_MODIFIED = QColor("#e8a040")

# 技能学习状态: 与表单模式同源的下拉选项 (SKILL_LEARN_STATES) → 值/标签映射
_LEARN_LABELS = {}
_LEARN_VALUES = set()
for _s in SKILL_LEARN_STATES:
    try:
        _v = parse_enum_value(_s)
        _LEARN_LABELS[_v] = _s
        _LEARN_VALUES.add(_v)
    except ValueError:
        pass


@dataclass
class ColumnSpec:
    """表格模式单列定义"""
    kind: str            # 'index'/'name'/'field'/'learn'/'raw'/'byte'/'effect'
    label: str
    fdef: object = None  # kind='field' 时的 FieldDef
    learn_idx: int = -1  # kind='learn' 时的技能编号
    raw_idx: int = -1    # kind='raw'/'effect' 时的 int16 字段索引
    base_idx: int = -1   # kind='byte' 时的打包区起始 int16 索引
    byte_idx: int = -1   # kind='byte' 时的区内字节号
    role: str = ''       # kind='byte' 时的语义: 'status_id' → 状态下拉+名称显示


def _status_slot_columns():
    """身上状态 8 槽的语义列: 每槽 = 状态下拉(低字节) + 持续回合(高字节)
    (与表单模式的 下拉框+持续输入框 对应, 不暴露打包 int16 原始值)"""
    cols = []
    for i in range(STATUS_SLOT_COUNT):
        cols.append(ColumnSpec('byte', f'槽{i}状态',
                               base_idx=STATUS_SLOT_BASE, byte_idx=i * 2,
                               role='status_id'))
        cols.append(ColumnSpec('byte', f'槽{i}回合',
                               base_idx=STATUS_SLOT_BASE, byte_idx=i * 2 + 1,
                               role='status_dur'))
    return cols


def _status_resist_columns():
    """状态抵抗 32 列: 每状态 1 字节 (0-100 抵抗百分比, 允许 0-255)"""
    cols = []
    for i in range(STATUS_RESIST_COUNT):
        nm = STATUS_NAMES[i] if i < len(STATUS_NAMES) else f'状态{i+1}'
        cols.append(ColumnSpec('byte', f'抗:{nm}',
                               base_idx=STATUS_RESIST_BASE, byte_idx=i))
    return cols


def _preset_field_columns(group_names, resist_after_slots=False):
    """按 SCHEMA_GROUPS 顺序取指定分组的字段列"""
    cols = []
    for group, keys in SCHEMA_GROUPS:
        if group not in group_names:
            continue
        if group == '身上状态':
            # 状态槽打包值(如 -256)人类不可读 → 一律替换为语义列;
            # 与表单 Tab1 一致: 状态抵抗紧随身上状态之后
            cols += _status_slot_columns()
            if resist_after_slots:
                cols += _status_resist_columns()
            continue
        for k in keys:
            fd = FIELD_SCHEMA[k]
            cols.append(ColumnSpec('field', fd.label, fdef=fd))
    return cols


def build_preset_columns(preset, editor):
    """构建列集预设 → ColumnSpec 列表 (首两列恒为 #/角色名)。
    预设结构与表单模式五个页签一一对应。"""
    skill_names = editor.skill_names
    cols = [ColumnSpec('index', '#'), ColumnSpec('name', '角色名')]
    if preset == '核心属性':
        # = 表单 Tab1: 基本信息/HP MP/八属性/五维/技能加成/反应组/身上状态/状态抵抗/导致状态
        cols += _preset_field_columns({'基本信息', 'HP/MP', '八属性', '角色五维',
                                       '技能加成', '反应组', '身上状态', '攻击导致状态'},
                                      resist_after_slots=True)
    elif preset == '装备与技能':
        # = 表单 Tab2: 装备/权限/装备技能/补丁/成长率/战后奖励/掉落物品
        cols += _preset_field_columns({'装备索引', '装备物品ID', '使用装备权限',
                                       '装备技能', '补丁字段', '成长率',
                                       '战后奖励', '掉落物品'})
    elif preset == '技能学习':
        # = 表单 Tab3: 344 技能学习状态矩阵
        for i in range(SKILL_LEARN_COUNT):
            nm = skill_names.get(i, f'技能#{i}') if skill_names else f'技能#{i}'
            cols.append(ColumnSpec('learn', nm[:10], learn_idx=i))
    elif preset == '技能效果判定':
        # = 表单 Tab4: [273]+ 指令技能→TKKon 动画映射 (双击弹 TKKon 选择器)
        active = ([i for i in range(350) if editor._skill_types.get(i) == 0]
                  if editor._skill_types else [])
        max_slots = WARPC_FIELD_COUNT - 273
        for slot, skill_idx in enumerate(active[:max_slots]):
            nm = ('普通攻击' if skill_idx == 344
                  else skill_names.get(skill_idx, f'技能#{skill_idx}'))
            cols.append(ColumnSpec('effect', nm[:10], raw_idx=273 + slot))
        if len(cols) == 2:
            # 未加载 TKSkill 时退化为原始区段列
            for j in range(273, WARPC_FIELD_COUNT):
                cols.append(ColumnSpec('raw', f'[{j}]', raw_idx=j))
    else:  # 全部字段 (Raw)
        for j in range(WARPC_FIELD_COUNT):
            cols.append(ColumnSpec('raw', f'[{j}]', raw_idx=j))
    return cols


# 与表单模式五个页签一一对应
COLUMN_PRESETS = ['核心属性', '装备与技能', '技能学习', '技能效果判定', '全部字段 (Raw)']


class WarpcTableModel(QAbstractTableModel):
    """行=角色记录, 列=ColumnSpec; 直接读写共享草稿层 editor._draft_records
    (与表单模式同源, 「应用修改」才提交到 editor.records)"""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.columns = []
        # 变更日志: 每次写入记录 (rec_idx, int16字段号, 旧值, 新值) 供撤销使用
        # _batch 非 None 时累积到批量操作 (粘贴/填充), 否则逐条推送给 undo_sink
        self._batch = None
        self.undo_sink = None

    @property
    def recs(self):
        """数据源: 共享草稿层"""
        return self.editor._draft_records

    # ── 撤销支持: 变更日志 ──
    def begin_batch(self):
        self._batch = []

    def end_batch(self):
        batch, self._batch = self._batch, None
        return batch or []

    def _log_change(self, rec_idx, fi, old, new):
        entry = (rec_idx, fi, old, new)
        if self._batch is not None:
            self._batch.append(entry)
        elif self.undo_sink is not None:
            self.undo_sink([entry])

    # ── 结构 ──
    def set_columns(self, columns):
        self.beginResetModel()
        self.columns = columns
        self.endResetModel()


    def reload(self):
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.recs)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self.columns):
                return self.columns[section].label
            return None
        return str(section)

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        col = self.columns[index.column()]
        if col.kind in ('index', 'name'):
            return base
        if col.kind == 'effect':
            return base  # 双击由面板弹出 TKKon 选择器
        if col.kind == 'field' and col.fdef.ftype in PICKER_FTYPES:
            return base  # 双击由面板弹出选择器
        return base | Qt.ItemIsEditable

    # ── 取值/写值 (int) ──
    def get_value(self, row, col_i):
        rec = self.recs[row]
        f = rec['fields']
        col = self.columns[col_i]
        if col.kind == 'field':
            return f[col.fdef.index]
        if col.kind == 'learn':
            return get_packed_byte(f, SKILL_LEARN_BASE, col.learn_idx)
        if col.kind == 'byte':
            return get_packed_byte(f, col.base_idx, col.byte_idx)
        if col.kind in ('raw', 'effect'):
            return f[col.raw_idx]
        return rec['index']

    # ── 取值域校验 ──
    @staticmethod
    def _enum_domain(fd):
        vals = set()
        for it in fd.enum_items:
            try:
                vals.add(parse_enum_value(it))
            except ValueError:
                pass
        return vals

    def value_allowed(self, col_i, value):
        """写入前的取值域校验: enum 列限定义域, 状态ID 限 0-状态数;
        其余列 (含引用/掩码/Raw) 不限制 — MOD 可能扩展, 由应用前终检兵把关"""
        col = self.columns[col_i]
        try:
            v = int(round(float(value)))
        except (ValueError, TypeError):
            return False
        if col.kind == 'field' and col.fdef.ftype == 'enum' and col.fdef.enum_items:
            return v in self._enum_domain(col.fdef)
        if col.kind == 'byte' and col.role == 'status_id':
            return 0 <= v <= len(STATUS_NAMES)
        return True

    def set_value(self, row, col_i, value):
        col = self.columns[col_i]
        if col.kind in ('index', 'name'):
            return False
        rec = self.recs[row]
        f = rec['fields']
        try:
            v = int(round(float(value)))
        except (ValueError, TypeError):
            return False
        if not self.value_allowed(col_i, v):
            return False
        # 无外部批量时建隐式批: 主字段+配对同步必须合并为同一个撤销步骤
        own_batch = self._batch is None
        if own_batch:
            self._batch = []
        try:
            if col.kind == 'learn':
                fi = SKILL_LEARN_BASE + col.learn_idx // 2
                if get_packed_byte(f, SKILL_LEARN_BASE, col.learn_idx) == max(0, min(255, v)):
                    return False
                old = f[fi]
                set_packed_byte(f, SKILL_LEARN_BASE, col.learn_idx, v)
                self._log_change(rec['index'], fi, old, f[fi])
            elif col.kind == 'byte':
                fi = col.base_idx + col.byte_idx // 2
                if get_packed_byte(f, col.base_idx, col.byte_idx) == max(0, min(255, v)):
                    return False
                old = f[fi]
                set_packed_byte(f, col.base_idx, col.byte_idx, v)
                self._log_change(rec['index'], fi, old, f[fi])
            else:
                idx = col.fdef.index if col.kind == 'field' else col.raw_idx
                v = clamp_int16(v)
                if f[idx] == v:
                    return False
                old = f[idx]
                f[idx] = v
                self._log_change(rec['index'], idx, old, v)
                # equip_idx ↔ equip_id 配对同步 (与表单模式 _pick_item 一致)
                if col.kind == 'field':
                    self._sync_equip_pair(rec, col.fdef.key, v)
            self.editor._on_table_mode_edited(rec['index'])
            return True
        finally:
            if own_batch:
                changes = self.end_batch()
                if changes and self.undo_sink is not None:
                    self.undo_sink(changes)

    def _sync_equip_pair(self, rec, key, v):
        f = rec['fields']
        ed = self.editor
        if key.startswith('equip_idx'):
            pair = FIELD_SCHEMA.get(f'equip_id{key[-1]}')
            nv = clamp_int16(ed._idx_to_id.get(v, 0))
        elif key.startswith('equip_id'):
            pair = FIELD_SCHEMA.get(f'equip_idx{key[-1]}')
            nv = clamp_int16(ed._id_to_idx.get(v, -1))
        else:
            return
        if pair and f[pair.index] != nv:
            old = f[pair.index]
            f[pair.index] = nv
            self._log_change(rec['index'], pair.index, old, nv)

    # ── 显示 ──
    def _display_text(self, row, col_i):
        col = self.columns[col_i]
        ed = self.editor
        if col.kind == 'index':
            return str(ed._draft_records[row]['index'])
        if col.kind == 'name':
            return ed._char_name(ed._draft_records[row])
        v = self.get_value(row, col_i)
        if col.kind == 'learn':
            # 与表单下拉一致: 预设状态显示标签, 非预设进度值显示数字
            return _LEARN_LABELS.get(v, str(v))
        if col.kind == 'byte' and col.role == 'status_id':
            if v == 0:
                return '0 (无)'
            nm = STATUS_NAMES[v - 1] if 0 < v <= len(STATUS_NAMES) else '?'
            return f'{v} {nm}'
        if col.kind == 'byte' and col.role == 'status_dur':
            # 空槽编码为 0xFF00 (状态0, 回合255): 与表单模式一致显示为 0
            sid = get_packed_byte(ed._draft_records[row]['fields'],
                                  col.base_idx, col.byte_idx - 1)
            if sid == 0 and v == 255:
                return '0'
            return str(v)
        if col.kind == 'effect':
            # 与表单 Tab4 一致: 显示 TKKon 动画名称
            if v < 0:
                return f'{v} (未设置)'
            nm = ed.tkkon_names.get(v, '')
            return f'{v} {nm}' if nm else str(v)
        if col.kind == 'field':
            fd = col.fdef
            if fd.ftype == 'enum' and fd.enum_items:
                for item in fd.enum_items:
                    try:
                        if parse_enum_value(item) == v:
                            return item
                    except ValueError:
                        pass
                return str(v)
            if fd.ftype == 'skill_ref':
                if v == -1:
                    return '-1 (未装备)'
                nm = ed.skill_names.get(v, '')
                return f'{v} {nm}' if nm else str(v)
            if fd.ftype == 'item_idx_ref':
                if v == -1:
                    return '-1 (未装备)'
                nm = ed.item_idx_names.get(v, '')
                return f'{v} {nm}' if nm else str(v)
            if fd.ftype == 'item_id_ref':
                if v <= 0:
                    return f'{v} (无)' if v == 0 else str(v)
                nm = ed.item_names.get(v, '')
                return f'{v} {nm}' if nm else str(v)
            if fd.ftype == 'flags':
                # 与表单模式标签一致: 显示已勾选位名称
                _, bits = FLAG_DEFS[fd.key]
                sel = [name for bit, name, _d in bits if (v & 0xFFFF) & (1 << bit)]
                if sel:
                    return ', '.join(sel)
                return '(无)' if v == 0 else str(v)
            if fd.ftype == 'use_right':
                defs = ed._use_right_defs.get(fd.key)
                if defs:
                    sel = [name for bit, name in defs[1] if (v & 0xFFFF) & bit]
                    if sel:
                        return ', '.join(sel)
                    return '(无)' if v == 0 else str(v)
                return str(v)
            if fd.ftype == 'status_mask':
                base = 0 if fd.key.endswith('_mask1') else 16
                sel = [STATUS_NAMES[base + i] for i in range(16)
                       if ((v & 0xFFFF) & (1 << i)) and base + i < len(STATUS_NAMES)]
                if sel:
                    return ', '.join(sel)
                return '(无)' if v == 0 else str(v)
        return str(v)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col_i = index.row(), index.column()
        col = self.columns[col_i]
        if role == Qt.DisplayRole:
            return self._display_text(row, col_i)
        if role == Qt.EditRole:
            return self.get_value(row, col_i)
        if role == Qt.TextAlignmentRole:
            if col.kind == 'name':
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignCenter)
        if role == Qt.ForegroundRole:
            # 与已应用值 (editor.records) 对比: 未应用的草稿修改橙色高亮
            if col.kind not in ('index', 'name'):
                applied = self._applied_value(row, col_i)
                if applied is not None and applied != self.get_value(row, col_i):
                    return CLR_MODIFIED
        if role == Qt.ToolTipRole and col.kind == 'field':
            fd = col.fdef
            return f"[{fd.index}] {fd.label}: {fd.comment}"
        return None

    def _applied_value(self, row, col_i):
        """已应用值 (editor.records) 中同位置的值, 用于未应用高亮对比"""
        ed = self.editor
        if row >= len(ed.records):
            return None
        of = ed.records[row]['fields']
        col = self.columns[col_i]
        if col.kind == 'field':
            return of[col.fdef.index]
        if col.kind == 'learn':
            return get_packed_byte(of, SKILL_LEARN_BASE, col.learn_idx)
        if col.kind == 'byte':
            return get_packed_byte(of, col.base_idx, col.byte_idx)
        if col.kind in ('raw', 'effect'):
            return of[col.raw_idx]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        if self.set_value(index.row(), index.column(), value):
            self.dataChanged.emit(index, index)
            return True
        return False


class WarpcRowFilterProxyModel(QSortFilterProxyModel):
    """表格模式行筛选: 统一支持简繁、去空格和模糊匹配。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._query = ""

    def set_search_query(self, query: str) -> None:
        self._query = query or ""
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._query:
            return True
        model = self.sourceModel()
        if model is None:
            return False
        index_value = model.data(model.index(source_row, 0, source_parent), Qt.DisplayRole)
        name_value = model.data(model.index(source_row, 1, source_parent), Qt.DisplayRole)
        return search_match(self._query, index_value, name_value)


class TableFieldDelegate(QStyledItemDelegate):
    """int → SpinBox; enum → ComboBox; learn → 0-255 SpinBox

    注意: 视图挂的是 QSortFilterProxyModel, 因此这里收到的 index 是代理索引。
    行号在排序/筛选后与源模型不同, 取值/写值必须走 index.data()/model.setData()
    由代理自动映射到源行; 列映射不变, 可直接用 index.column() 查列定义。"""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model

    def createEditor(self, parent, option, index):
        col = self._model.columns[index.column()]
        if col.kind == 'learn':
            # 与表单模式一致: 技能学习状态下拉框 (SKILL_LEARN_STATES)
            cb = EditorComboBox(parent)
            cb.addItems(SKILL_LEARN_STATES)
            v = index.data(Qt.EditRole)
            # 保留非预设进度值 (1~9 等): 临时追加一项, 避免提交时被归一化丢失
            if v is not None and v not in _LEARN_VALUES:
                cb.addItem(f'{v}-（当前值）')
            return cb
        if col.kind == 'byte':
            if col.role == 'status_id':
                cb = EditorComboBox(parent)
                cb.addItem('0 (无)')
                for i, nm in enumerate(STATUS_NAMES):
                    cb.addItem(f'{i+1}-{nm}')
                return cb
            sp = QSpinBox(parent)
            sp.setRange(0, 255)
            sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
            return sp
        if col.kind == 'field' and col.fdef.ftype == 'enum' and col.fdef.enum_items:
            cb = EditorComboBox(parent)
            cb.addItems(col.fdef.enum_items)
            return cb
        sp = QSpinBox(parent)
        sp.setRange(INT16_MIN, INT16_MAX)
        sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
        return sp

    def eventFilter(self, editor, event):
        """Excel 式编辑内导航: 数值编辑器中 ↑/↓ 提交并移动到上/下单元格,
        回车提交并下移 (QSpinBox 默认 ↑/↓ 是步进, 与 Excel 不符, 拦截接管;
        enum 下拉的 ↑/↓ 仍用于选项切换, 不拦截)"""
        if event.type() == QEvent.KeyPress and isinstance(editor, QSpinBox):
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
                view = self.parent()
                if isinstance(view, QTableView):
                    cur = view.currentIndex()
                    step = -1 if key == Qt.Key_Up else 1  # 回车同 Excel: 提交后下移
                    nr = cur.row() + step
                    if cur.isValid() and 0 <= nr < view.model().rowCount():
                        view.setCurrentIndex(view.model().index(nr, cur.column()))
                return True
        return super().eventFilter(editor, event)

    def setEditorData(self, editor, index):
        # 经代理 EditRole 取源行值 (直接用 proxy 行号查源模型会在排序/筛选后错行)
        v = index.data(Qt.EditRole)
        if v is None:
            return
        if isinstance(editor, EditorComboBox):
            for i in range(editor.count()):
                try:
                    if parse_enum_value(editor.itemText(i)) == v:
                        editor.setCurrentIndex(i)
                        return
                except ValueError:
                    # '0 (无)' 等无 '-' 分隔的项: 按首段数字解析
                    try:
                        if int(editor.itemText(i).split()[0]) == v:
                            editor.setCurrentIndex(i)
                            return
                    except (ValueError, IndexError):
                        pass
        elif isinstance(editor, QSpinBox):
            editor.setValue(int(v))

    def setModelData(self, editor, model, index):
        if isinstance(editor, EditorComboBox):
            txt = editor.currentText()
            try:
                v = parse_enum_value(txt)
            except ValueError:
                try:
                    v = int(txt.split()[0])
                except (ValueError, IndexError):
                    return
        else:
            editor.interpretText()
            v = editor.value()
        model.setData(index, v, Qt.EditRole)


class FillHandleTableView(QTableView):
    """带 Excel 风格填充柄的表格视图:
    选区右下角绘制小方块, 拖拽小方块向四向扩展并预览 (虚线框),
    松手后通过 fill_requested 回调通知面板执行循环复制填充。
    坐标均为代理(可视)行列, 数据读写由面板映射到源模型。"""

    HANDLE = 7  # 填充柄边长 (px)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 回调(base_box, fill_box), 均为 (min_row, min_col, max_row, max_col)
        self.fill_requested = None
        # 回调(proxy_index)->bool: 该单元格是否允许"直接输入数字开始编辑"
        self.digit_edit_allowed = None
        # 冻结列总宽 (由面板同步); 键盘左移时防止当前格藏到冻结列下方
        self.frozen_width = 0
        self._dragging = False
        self._drag_base = None
        self._fill_box = None
        self.viewport().setMouseTracking(True)

    def moveCursor(self, action, modifiers):
        """键盘左移时若目标格位于冻结列遮罩下, 额外滚动使其可见 (Qt 冻结列标准处理)"""
        cur = super().moveCursor(action, modifiers)
        if (self.frozen_width > 0 and action == QAbstractItemView.MoveLeft
                and cur.column() > 1
                and self.visualRect(cur).topLeft().x() < self.frozen_width):
            new_val = (self.horizontalScrollBar().value()
                       + self.visualRect(cur).topLeft().x() - self.frozen_width)
            self.horizontalScrollBar().setValue(new_val)
        return cur

    # ── Excel 式直接输入: 选中单元格后敲数字/负号立即进入编辑并替换原值 ──
    def keyPressEvent(self, e):
        txt = e.text()
        if (txt and (txt.isdigit() or txt == '-')
                and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier))
                and self.state() != QAbstractItemView.EditingState):
            idx = self.currentIndex()
            if (idx.isValid()
                    and (self.model().flags(idx) & Qt.ItemIsEditable)
                    and (self.digit_edit_allowed is None
                         or self.digit_edit_allowed(idx))):
                if self.edit(idx, QAbstractItemView.AllEditTriggers, e):
                    editor = QApplication.focusWidget()
                    if isinstance(editor, QSpinBox):
                        # Excel 语义: 首个输入字符替换原值而非追加
                        editor.lineEdit().setText(txt)
                    return
        super().keyPressEvent(e)

    # ── 几何 ──
    def _selection_box(self):
        sm = self.selectionModel()
        idxs = sm.selectedIndexes() if sm else []
        if not idxs:
            return None
        rows = [i.row() for i in idxs]
        cols = [i.column() for i in idxs]
        return (min(rows), min(cols), max(rows), max(cols))

    def _handle_rect(self):
        box = self._selection_box()
        if box is None or self.model() is None:
            return None
        cell = self.visualRect(self.model().index(box[2], box[3]))
        if not cell.isValid():
            return None
        s = self.HANDLE
        return QRect(cell.right() - s // 2, cell.bottom() - s // 2, s, s)

    def _compute_fill_box(self, pos):
        """根据拖拽位置计算填充区 (主导方向优先, 同 Excel 单轴扩展)"""
        idx = self.indexAt(pos)
        if not idx.isValid() or self._drag_base is None:
            return None
        min_r, min_c, max_r, max_c = self._drag_base
        down, up = idx.row() - max_r, min_r - idx.row()
        right, left = idx.column() - max_c, min_c - idx.column()
        v, h = max(down, up), max(right, left)
        if v <= 0 and h <= 0:
            return None  # 拖回选区内部: 无填充
        if v >= h:
            if down >= up:
                return (max_r + 1, min_c, idx.row(), max_c)
            return (idx.row(), min_c, min_r - 1, max_c)
        if right >= left:
            return (min_r, max_c + 1, max_r, idx.column())
        return (min_r, idx.column(), max_r, min_c - 1)

    # ── 绘制 ──
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        hr = self._handle_rect()
        if hr is not None:
            painter.fillRect(hr, QColor("#478cbf"))  # 阶段 2 豁免: 检查器高亮 (classic 强调蓝)
            painter.setPen(QColor("#ffffff"))  # 阶段 2 豁免: 白字 (蓝底)
            painter.drawRect(hr.adjusted(0, 0, -1, -1))
        if self._fill_box is not None:
            r1, c1, r2, c2 = self._fill_box
            region = self.visualRect(self.model().index(r1, c1)).united(
                self.visualRect(self.model().index(r2, c2)))
            pen = QPen(QColor("#478cbf"), 2, Qt.DashLine)  # 阶段 2 豁免: 检查器虚线
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(region.adjusted(1, 1, -2, -2))
        painter.end()

    # ── 拖拽手势 ──
    def mousePressEvent(self, e):
        hr = self._handle_rect()
        if (hr is not None and e.button() == Qt.LeftButton
                and hr.contains(e.position().toPoint())):
            self._dragging = True
            self._drag_base = self._selection_box()
            self._fill_box = None
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._dragging:
            self._fill_box = self._compute_fill_box(pos)
            self.viewport().update()
            e.accept()
            return
        hr = self._handle_rect()
        if hr is not None and hr.contains(pos):
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            box, base = self._fill_box, self._drag_base
            self._fill_box = None
            self._drag_base = None
            self.viewport().update()
            if box is not None and base is not None and self.fill_requested:
                self.fill_requested(base, box)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class WarpcTablePanel(QWidget):
    """表格编辑模式面板: 预设选择 + 行筛选 + 虚拟化表格 + 批量编辑快捷键"""

    UNDO_LIMIT = 200  # 撤销步数上限

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        # 撤销/重做栈: 元素为 (操作名, [(rec_idx, fi, old, new), ...])
        self._undo_stack = []
        self._redo_stack = []
        # 整行(整条记录) 剪贴缓冲: 全 527 字段的 int16 列表
        self._row_clip = None
        self._records_id = id(editor.records)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("列集预设:"))
        self.preset_combo = EditorComboBox()
        self.preset_combo.addItems(COLUMN_PRESETS)
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        bar.addWidget(self.preset_combo)
        bar.addSpacing(12)
        bar.addWidget(QLabel("筛选角色:"))
        self.filter_edit = SearchInput("按名称/编号筛选行…")
        self.filter_edit.setMinimumWidth(160)
        self.filter_edit.textChanged.connect(self._apply_row_filter)
        bar.addWidget(self.filter_edit)
        bar.addSpacing(12)
        btn_undo = QPushButton("撤销")
        btn_undo.setToolTip("撤销表格模式的上一步修改 (Ctrl+Z)")
        btn_undo.clicked.connect(self._undo)
        bar.addWidget(btn_undo)
        btn_redo = QPushButton("重做")
        btn_redo.setToolTip("重做已撤销的修改 (Ctrl+Y)")
        btn_redo.clicked.connect(self._redo)
        bar.addWidget(btn_redo)
        bar.addSpacing(12)
        hint = QLabel("选中后直接输数字编辑 | 右键/Ctrl+Shift+C·V 整行复制粘贴 | Ctrl+C/V 单元格 | Ctrl+D/拖拽填充柄 填充 | Ctrl+Z/Y 撤销重做 | 橙色=未应用")
        hint.setProperty("class", "PreviewMeta")
        bar.addWidget(hint)
        bar.addStretch()
        layout.addLayout(bar)

        self.model = WarpcTableModel(self.editor, self)
        self.model.undo_sink = self._push_undo_step  # 单格编辑(委托/选择器)逐步入栈
        self.proxy = WarpcRowFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setSortRole(Qt.EditRole)

        self.view = FillHandleTableView()
        # 主题适配: editor_themes 主题 QSS 中 QTableView[class="WarpcGrid"] 提供交替行/网格线配色
        self.view.setProperty("class", "WarpcGrid")
        self.view.fill_requested = self._drag_fill  # Excel 风格填充柄回调
        self.view.digit_edit_allowed = self._digit_edit_allowed  # 数字直接输入
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(TableFieldDelegate(self.model, self.view))
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        # 收紧编辑触发: Qt 默认含 AnyKeyPressed (任意按键开编辑器),
        # 数字直接输入由 FillHandleTableView.keyPressEvent 接管 (仅数值列+替换语义),
        # enum/其他按键保持 双击/F2 习惯
        self.view.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setSortIndicatorClearable(True)
        # 初始按 # 升序 (setSortingEnabled 默认指示器为降序, 会导致首屏倒序显示)
        self.view.sortByColumn(0, Qt.AscendingOrder)
        self.view.horizontalHeader().setDefaultSectionSize(96)
        # 主题中的 QComboBox/QSpinBox 高度来自 QSS，默认 30px 行会在编辑
        # 时裁掉上下边缘；主视图和冻结视图必须使用相同的行高。
        self.view.verticalHeader().setDefaultSectionSize(44)
        self.view.verticalHeader().setVisible(False)
        self.view.setAlternatingRowColors(True)
        self.view.doubleClicked.connect(self._on_double_click)
        # 选区变化时重绘填充柄
        self.view.selectionModel().selectionChanged.connect(
            lambda *_: self.view.viewport().update())
        # 右键菜单: 整行复制/粘贴 (覆盖全部字段)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.view, 1)

        # 冻结列: #/角色名 固定不随横向滚动 (Qt Frozen Column 叠加视图方案)
        self._setup_frozen_view()

        # 批量编辑快捷键: 用事件过滤器在 KeyPress 阶段拦截 Ctrl+C/V/D。
        # 不用 QShortcut — PySide6 构造函数直连回调+context 的重载绑定不生效
        # (构造不报错但按键不触发), 事件过滤器路径确定性更强。
        # 同时监听 view 与 viewport: 用户点击后焦点可能落在两者任一。
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)

        self._apply_preset(self.preset_combo.currentText())

    # ── 冻结列 (#/角色名) ──
    def _setup_frozen_view(self):
        """在主表格上叠加只显示前两列的同步视图, 横向滚动时固定不动"""
        fz = QTableView(self.view)
        fz.setProperty("class", "WarpcGrid")
        fz.setModel(self.proxy)
        fz.setSelectionModel(self.view.selectionModel())  # 共享选区
        fz.setSelectionMode(QAbstractItemView.ExtendedSelection)
        fz.setSelectionBehavior(QAbstractItemView.SelectItems)
        fz.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 两列均只读
        fz.setFocusPolicy(Qt.NoFocus)
        fz.verticalHeader().setVisible(False)
        fz.verticalHeader().setDefaultSectionSize(44)
        fz.setAlternatingRowColors(True)
        fz.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fz.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 右键菜单在冻结区同样可用
        fz.setContextMenuPolicy(Qt.CustomContextMenu)
        fz.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(pos, fz))
        # 竖直滚动双向同步
        self.view.verticalScrollBar().valueChanged.connect(
            fz.verticalScrollBar().setValue)
        fz.verticalScrollBar().valueChanged.connect(
            self.view.verticalScrollBar().setValue)
        # 主表列宽变化 → 同步冻结列宽与遮罩几何
        self.view.horizontalHeader().sectionResized.connect(self._on_frozen_section_resized)
        # 排序: 冻结表头点击转发到主视图, 指示器双向同步
        fz.horizontalHeader().setSectionsClickable(True)
        fz.horizontalHeader().setSortIndicatorShown(True)
        fz.horizontalHeader().sectionClicked.connect(self._frozen_header_clicked)
        self.view.horizontalHeader().sortIndicatorChanged.connect(
            lambda col, order: fz.horizontalHeader().setSortIndicator(col, order))
        self.frozen = fz
        fz.show()

    def _frozen_header_clicked(self, col):
        """冻结表头点击: 复刻主视图的排序切换逻辑 (升序↔降序)"""
        hh = self.view.horizontalHeader()
        if hh.sortIndicatorSection() == col and hh.sortIndicatorOrder() == Qt.AscendingOrder:
            self.view.sortByColumn(col, Qt.DescendingOrder)
        else:
            self.view.sortByColumn(col, Qt.AscendingOrder)

    def _on_frozen_section_resized(self, logical, _old, new):
        if logical < 2:
            self.frozen.setColumnWidth(logical, new)
            self._update_frozen_geometry()

    def _update_frozen_geometry(self):
        """冻结遮罩定位: 覆盖主表前两列区域 (含表头)"""
        w = self.view.columnWidth(0) + self.view.columnWidth(1)
        self.frozen.setGeometry(
            self.view.frameWidth(), self.view.frameWidth(), w,
            self.view.viewport().height() + self.view.horizontalHeader().height())
        self.view.frozen_width = w  # 供 moveCursor 防遮挡

    def _digit_edit_allowed(self, proxy_index):
        """数字直接输入仅适用于纯数值列; enum/状态/技能学习下拉列保持下拉编辑习惯"""
        col = self.model.columns[proxy_index.column()]
        if col.kind == 'field' and col.fdef.ftype == 'enum':
            return False
        if col.kind == 'byte' and col.role == 'status_id':
            return False
        if col.kind == 'learn':
            return False
        return True

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.view:
            # 主表尺寸变化 → 延迟到布局稳定后重新定位冻结遮罩
            QTimer.singleShot(0, self._update_frozen_geometry)
        if event.type() == QEvent.KeyPress and obj in (self.view, self.view.viewport()):
            if event.matches(QKeySequence.Undo):
                self._undo()
                return True
            if event.matches(QKeySequence.Redo):
                self._redo()
                return True
            mods = event.modifiers()
            # Ctrl+Shift+C/V: 整行(整条记录, 全字段)复制/粘贴覆盖
            if (mods & Qt.ControlModifier) and (mods & Qt.ShiftModifier):
                if event.key() == Qt.Key_C:
                    self._copy_row()
                    return True
                if event.key() == Qt.Key_V:
                    self._paste_row()
                    return True
            if event.matches(QKeySequence.Copy):
                self._copy_selection()
                return True
            if event.matches(QKeySequence.Paste):
                self._paste_selection()
                return True
            if (event.key() == Qt.Key_D
                    and mods & Qt.ControlModifier):
                self._fill_down()
                return True
        return super().eventFilter(obj, event)

    # ── 右键菜单 / 整行复制粘贴 ──
    def _current_source_row(self):
        """当前单元格对应的源模型行号 (即草稿记录下标); 无效返回 None"""
        idx = self.view.currentIndex()
        if not idx.isValid():
            return None
        return self.proxy.mapToSource(idx).row()

    def _show_context_menu(self, pos, src_view=None):
        src_view = src_view or self.view
        menu = QMenu(src_view)
        row = self._current_source_row()
        act_copy = menu.addAction("复制整行 (全部字段)")
        act_copy.setEnabled(row is not None)
        act_paste = menu.addAction("粘贴整行 (覆盖当前行)")
        act_paste.setEnabled(row is not None and self._row_clip is not None)
        menu.addSeparator()
        act_ccell = menu.addAction("复制选中单元格 (Ctrl+C)")
        act_pcell = menu.addAction("粘贴到选中 (Ctrl+V)")
        chosen = menu.exec(src_view.viewport().mapToGlobal(pos))
        if chosen is act_copy:
            self._copy_row()
        elif chosen is act_paste:
            self._paste_row()
        elif chosen is act_ccell:
            self._copy_selection()
        elif chosen is act_pcell:
            self._paste_selection()

    def _copy_row(self):
        row = self._current_source_row()
        if row is None:
            return
        rec = self.editor._draft_records[row]
        self._row_clip = list(rec['fields'])
        self.editor.status_var.setText(
            f"已复制整行 #{rec['index']} 的全部 {len(self._row_clip)} 个字段 — 选中目标行后 Ctrl+Shift+V 覆盖")

    def _paste_row(self):
        if self._row_clip is None:
            self.editor.status_var.setText("粘贴整行: 尚未复制任何行")
            return
        row = self._current_source_row()
        if row is None:
            return
        rec = self.editor._draft_records[row]
        clip = self._row_clip
        changes = []
        for fi in range(min(WARPC_FIELD_COUNT, len(clip))):
            if rec['fields'][fi] != clip[fi]:
                changes.append((rec['index'], fi, rec['fields'][fi], clip[fi]))
                rec['fields'][fi] = clip[fi]
        if changes:
            self._push_undo_step(changes, "粘贴整行")
            self.model.reload()
            self.editor._on_table_mode_edited(rec['index'])
            self.editor.status_var.setText(
                f"已整行覆盖 → #{rec['index']} ({len(changes)} 个字段变更, 草稿未应用, Ctrl+Z 可撤销)")
        else:
            self.editor.status_var.setText(f"粘贴整行: #{rec['index']} 与源行完全相同, 无变更")

    # ── 撤销/重做 ──
    def _push_undo_step(self, changes, label="编辑单元格"):
        if not changes:
            return
        self._undo_stack.append((label, list(changes)))
        del self._undo_stack[:-self.UNDO_LIMIT]
        self._redo_stack.clear()

    def _apply_change_set(self, changes, use_old):
        """回放变更集到草稿: use_old=True 写回旧值(撤销), 否则写新值(重做)"""
        by_idx = {r['index']: r for r in self.editor._draft_records}
        touched = set()
        seq = reversed(changes) if use_old else changes
        for rec_idx, fi, old, new in seq:
            rec = by_idx.get(rec_idx)
            if rec is None:
                continue  # 记录已被删除/重载, 跳过
            rec['fields'][fi] = old if use_old else new
            touched.add(rec_idx)
        if touched:
            self.model.reload()
        return touched

    def _undo(self):
        if not self._undo_stack:
            self.editor.status_var.setText("撤销: 没有可撤销的表格修改")
            return
        label, changes = self._undo_stack.pop()
        touched = self._apply_change_set(changes, use_old=True)
        self._redo_stack.append((label, changes))
        self.editor.status_var.setText(
            f"已撤销: {label} ({len(changes)} 处, 涉及 {len(touched)} 个角色)")

    def _redo(self):
        if not self._redo_stack:
            self.editor.status_var.setText("重做: 没有可重做的修改")
            return
        label, changes = self._redo_stack.pop()
        touched = self._apply_change_set(changes, use_old=False)
        self._undo_stack.append((label, changes))
        self.editor.status_var.setText(
            f"已重做: {label} ({len(changes)} 处, 涉及 {len(touched)} 个角色)")

    # ── 刷新/主题 ──
    def refresh(self):
        """进入表格模式时调用: records 可能已整体重载"""
        # 数据源整体更换 (重新加载目录/存档) → 旧变更日志失效, 清空撤销栈
        if id(self.editor.records) != self._records_id:
            self._records_id = id(self.editor.records)
            self._undo_stack.clear()
            self._redo_stack.clear()
        # 技能学习/效果列依赖 skill_names/_skill_types, 重新构建当前预设
        self._apply_preset(self.preset_combo.currentText())

    def apply_theme(self, is_dark):
        # 主窗口 setStyleSheet 会级联到子控件; 这里强制重新拉取 QSS 并刷新视口,
        # 避免切换主题时 View 调色板残留旧配色
        self.view.style().unpolish(self.view)
        self.view.style().polish(self.view)
        self.view.viewport().update()

    def _apply_preset(self, preset):
        cols = build_preset_columns(preset, self.editor)
        self.model.set_columns(cols)
        self.view.setColumnWidth(0, 46)
        self.view.setColumnWidth(1, 140)
        for ci in range(2, len(cols)):
            col = cols[ci]
            # 解码文本类列 (标志/权限/状态掩码/状态下拉/技能效果) 加宽便于阅读
            if col.kind == 'field' and col.fdef.ftype in ('flags', 'use_right', 'status_mask'):
                self.view.setColumnWidth(ci, 160)
            elif col.kind == 'effect':
                self.view.setColumnWidth(ci, 130)
            elif col.kind == 'byte' and col.role == 'status_id':
                self.view.setColumnWidth(ci, 110)
            elif col.kind == 'learn':
                self.view.setColumnWidth(ci, 118)  # 容纳下拉标签如 "20-组技能学会"
            else:
                self.view.setColumnWidth(ci, 96)
        # 各字段保留预设的默认宽度；窗口有多余空间时由最后一列自然填充，
        # 避免表格右侧出现大片空白，同时不改变列数或冻结列逻辑。
        self.view.horizontalHeader().setStretchLastSection(True)
        # 冻结视图: 仅显示前两列, 列宽/行高与主表一致 (模型重置后需重新隐藏)
        if hasattr(self, 'frozen'):
            self.frozen.setColumnWidth(0, self.view.columnWidth(0))
            self.frozen.setColumnWidth(1, self.view.columnWidth(1))
            for ci in range(2, len(cols)):
                self.frozen.setColumnHidden(ci, True)
            self._update_frozen_geometry()
        # 名称列筛选
        self._apply_row_filter()

    def _apply_row_filter(self):
        self.proxy.set_search_query(self.filter_edit.text())

    # ── 双击: 引用/掩码/技能效果字段弹选择器 ──
    def _on_double_click(self, proxy_index):
        src = self.proxy.mapToSource(proxy_index)
        col = self.model.columns[src.column()]
        ed = self.editor
        if col.kind == 'effect':
            # 与表单 Tab4 一致: TKKon 动画选择器
            if not ed.tkkon_names:
                return
            from warpc_editor import TkkonPickerDialog
            cur = self.model.get_value(src.row(), src.column())
            dlg = TkkonPickerDialog(self, ed.tkkon_names, cur)
            if dlg.exec() == QDialog.Accepted and dlg.selected_id is not None:
                self.model.setData(src, dlg.selected_id, Qt.EditRole)
            return
        if col.kind != 'field' or col.fdef.ftype not in PICKER_FTYPES:
            return
        fd = col.fdef
        cur = self.model.get_value(src.row(), src.column())
        new_val = None
        if fd.ftype == 'skill_ref':
            if not ed.skill_names:
                return
            dlg = ed._make_skill_picker(self)
            if dlg.exec() == QDialog.Accepted and dlg.selected_index is not None:
                new_val = dlg.selected_index
        elif fd.ftype in ('item_idx_ref', 'item_id_ref'):
            if not getattr(ed, '_item_records', None):
                return
            from editor_utils.picker_dialogs import ItemPickerDialog
            is_idx = fd.ftype == 'item_idx_ref'
            use_right_opts = {}
            from warpc_schema import USE_RIGHT_PAGE_TO_FIELD
            for page, field_name in USE_RIGHT_PAGE_TO_FIELD.items():
                if field_name in ed._use_right_defs:
                    use_right_opts[page] = ed._use_right_defs[field_name][1]
            use_right_opts.setdefault(5, [(0, "通用")])
            dlg = ItemPickerDialog(
                self, ed._item_records,
                use_right_options=use_right_opts,
                icon_pixmap_fn=ed._get_icon_pixmap,
                current_value=cur,
                clear_text="清空(-1)" if is_idx else "清空(0)",
                return_key='index' if is_idx else 'item_id',
            )
            if dlg.exec() == QDialog.Accepted and dlg.selected_value is not None:
                new_val = dlg.selected_value
        elif fd.ftype == 'flags':
            from editor_utils.picker_dialogs import BitmaskPickerDialog
            title, bits = FLAG_DEFS[fd.key]
            dlg = BitmaskPickerDialog(self, title, bits, cur & 0xFFFF, use_bit_shift=True)
            if dlg.exec() == QDialog.Accepted:
                new_val = dlg.get_value()
        elif fd.ftype == 'use_right':
            from editor_utils.picker_dialogs import BitmaskPickerDialog
            if fd.key not in ed._use_right_defs:
                return
            title, opts = ed._use_right_defs[fd.key]
            dlg = BitmaskPickerDialog(self, title, opts, cur & 0xFFFF, manual=True)
            if dlg.exec() == QDialog.Accepted:
                new_val = dlg.get_value()
        elif fd.ftype == 'status_mask':
            from editor_utils.picker_dialogs import StatusPickerDialog, STATUS_NAMES
            base = 0 if fd.key.endswith('_mask1') else 16
            dlg = StatusPickerDialog(self, "选择导致状态 (位掩码)", STATUS_NAMES,
                                     cur & 0xFFFF, base, ed._get_icon_pixmap, True)
            if dlg.exec() == QDialog.Accepted and dlg.selected_mask is not None:
                new_val = dlg.selected_mask
        if new_val is not None:
            self.model.setData(src, new_val, Qt.EditRole)

    # ── 批量编辑 (均在代理/可视坐标系操作, 逐单元格映射到源模型读写) ──
    def _selected_grid(self):
        """选中单元格 → 按可视 (代理) 行/列排序的二维分组; 元素为代理索引"""
        idxs = self.view.selectedIndexes()
        if not idxs:
            return []
        rows = {}
        for i in idxs:
            rows.setdefault(i.row(), []).append(i)
        return [sorted(cells, key=lambda x: x.column())
                for _, cells in sorted(rows.items())]

    def _src_get(self, proxy_idx):
        s = self.proxy.mapToSource(proxy_idx)
        return self.model.get_value(s.row(), s.column())

    def _src_set(self, proxy_idx, value):
        s = self.proxy.mapToSource(proxy_idx)
        return self.model.set_value(s.row(), s.column(), value)

    def _copy_selection(self):
        grid = self._selected_grid()
        if not grid:
            return
        lines = []
        for cells in grid:
            lines.append('\t'.join(str(self._src_get(c)) for c in cells))
        QApplication.clipboard().setText('\n'.join(lines))
        self.editor.status_var.setText(
            f"已复制 {sum(len(r) for r in grid)} 个单元格 (TSV)")

    def _paste_selection(self):
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        anchor = self.view.currentIndex()  # 代理索引 (可视锚点)
        if not anchor.isValid():
            return
        data = [line.split('\t') for line in text.replace('\r\n', '\n')
                .rstrip('\n').split('\n')]
        changed = 0
        skipped = 0
        self.model.begin_batch()
        for dr, row_vals in enumerate(data):
            r = anchor.row() + dr
            if r >= self.proxy.rowCount():
                break
            for dc, val in enumerate(row_vals):
                c = anchor.column() + dc
                if c >= self.proxy.columnCount():
                    break
                sidx = self.proxy.index(r, c)
                src = self.proxy.mapToSource(sidx)
                col = self.model.columns[src.column()]
                # 取值域拦截: 非法值计入跳过数并提示 (只读列不计)
                if (col.kind not in ('index', 'name')
                        and not self.model.value_allowed(src.column(), val.strip())):
                    skipped += 1
                    continue
                if self._src_set(sidx, val.strip()):
                    changed += 1
        changes = self.model.end_batch()
        if changed:
            self._push_undo_step(changes, "粘贴")
            self.model.reload()
        if changed or skipped:
            msg = f"粘贴完成: {changed} 个单元格已更新"
            if skipped:
                msg += f", {skipped} 个因取值非法被跳过 (如枚举列只接受预定义值)"
            self.editor.status_var.setText(msg)

    def _fill_down(self):
        grid = self._selected_grid()
        if not grid:
            self.editor.status_var.setText("向下填充: 请先选中单元格")
            return
        if len(grid) == 1:
            # 单行选区: Excel 语义 — 从上方相邻单元格取值填入
            changed = 0
            self.model.begin_batch()
            for c in grid[0]:
                if c.row() == 0:
                    continue
                above = self.proxy.index(c.row() - 1, c.column())
                if self._src_set(c, self._src_get(above)):
                    changed += 1
            changes = self.model.end_batch()
            if changed:
                self._push_undo_step(changes, "向下填充")
                self.model.reload()
                self.editor.status_var.setText(
                    f"向下填充完成: 已从上方行复制 {changed} 个单元格")
            else:
                self.editor.status_var.setText(
                    "向下填充: 上方单元格值相同或已在首行, 无可填充")
            return
        # 多行选区: 可视首行作为模板, 按列号取值
        top = {c.column(): self._src_get(c) for c in grid[0]}
        changed = 0
        self.model.begin_batch()
        for cells in grid[1:]:
            for c in cells:
                if c.column() in top:
                    if self._src_set(c, top[c.column()]):
                        changed += 1
        changes = self.model.end_batch()
        if changed:
            self._push_undo_step(changes, "向下填充")
            self.model.reload()
            self.editor.status_var.setText(f"向下填充完成: {changed} 个单元格已更新")
        else:
            self.editor.status_var.setText("向下填充: 选区值已与模板行一致, 无需更新")

    def _drag_fill(self, base, box):
        """填充柄拖拽填充: 以源选区为模板循环复制到填充区 (Excel 复制填充语义)
        base/box 均为代理坐标 (min_row, min_col, max_row, max_col)"""
        min_r, min_c, max_r, max_c = base
        r1, c1, r2, c2 = box
        n_rows = max_r - min_r + 1
        n_cols = max_c - min_c + 1
        changed = 0
        self.model.begin_batch()
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                # 循环映射到源选区内的模板单元格
                if r > max_r:
                    src_r = min_r + (r - max_r - 1) % n_rows
                elif r < min_r:
                    src_r = max_r - (min_r - 1 - r) % n_rows
                else:
                    src_r = r
                if c > max_c:
                    src_c = min_c + (c - max_c - 1) % n_cols
                elif c < min_c:
                    src_c = max_c - (min_c - 1 - c) % n_cols
                else:
                    src_c = c
                val = self._src_get(self.proxy.index(src_r, src_c))
                if self._src_set(self.proxy.index(r, c), val):
                    changed += 1
        changes = self.model.end_batch()
        if changed:
            self._push_undo_step(changes, "拖拽填充")
            self.model.reload()
            # 扩展选区覆盖 源区+填充区 (同 Excel 行为)
            sel = QItemSelection(
                self.proxy.index(min(min_r, r1), min(min_c, c1)),
                self.proxy.index(max(max_r, r2), max(max_c, c2)))
            self.view.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect)
            self.editor.status_var.setText(
                f"拖拽填充完成: {changed} 个单元格已更新 (Ctrl+Z 可撤销)")
        else:
            self.editor.status_var.setText("拖拽填充: 目标区值未变化 (只读列或值相同)")
