"""mat_editor 脚本编辑族 — MatScriptPanelMixin (T18 自 MatEditorApp 迁出)。

脚本页签构建/链表刷新/模板对话框/SETPOS 修复/脚本预览; 方法体原样迁入。"""
import os
import re
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from editor_utils.game_defs import GAME_COLORS
from editor_utils.theme_manager import business_colors
from mat_dat_io import has_data
from mat_script_desc import _dir_name
from mat_script_templates import SCRIPT_TEMPLATES
from mat_widgets import CodeEditor, ScriptSyntaxHighlighter


# ── 树/预览配色 (原 MatEditorApp 模块级常量, 脚本族专用) ──
TREE_VIRTUAL_COLOR = "#3366cc"   # 虚拟场景/子项: 蓝
TREE_SHARED_COLOR = "#CC6600"    # 共享头/空槽: 橙
TREE_LOOP_COLOR = "#CC0000"      # 循环: 红
TREE_FLAG_COLOR = "#2E9B57"      # 标志: 绿
PV_ITEM_RED = "#FF4444"          # 预览物品名红 (粗体)


class MatScriptPanelMixin:
    """脚本页签族方法 (自 MatEditorApp 原样迁入)。"""

    def _build_script_tab(self):
        """构建脚本编辑标签页"""
        layout = QVBoxLayout(self.tab_script)
        layout.setContentsMargins(4, 4, 4, 4)

        # Script splitter (vertical)
        script_splitter = QSplitter(Qt.Vertical)
        script_splitter.setHandleWidth(6)

        # Top: 脚本调度信息 + DefUnit链列表
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 调度信息
        sched_group = QFrame()
        sched_group.setObjectName("PreviewFrame")
        sched_layout = QGridLayout(sched_group)
        sched_layout.setContentsMargins(8, 8, 8, 8)
        sched_layout.setSpacing(4)

        sched_items = [
            ('enabled', '启用', 'flags bit0=启用'),
            ('pickable', '可交互', 'flags bit2=可交互'),
            ('tick', 'Tick周期', 'd4=Tick'),
            ('timer', '定时器', 'd3=定时器'),
            ('chain_a', 'A链(自动)', 'DEFINE链A = Tick自动执行'),
            ('chain_b', 'B链(触发)', 'DEFINE链B = 触发执行'),
            ('chain_c', 'C链(保留)', 'DEFINE链C = 保留链'),
            ('trigger', '触发方式', '基于实体类型'),
        ]
        for ri, (key, label, tip) in enumerate(sched_items):
            r, c = divmod(ri, 4)
            lbl = QLabel(f"{label}:")
            lbl.setProperty("class", "PropLabel")
            lbl.setToolTip(tip)
            val = QLabel("")
            val.setProperty("class", "ExtraPreviewText")
            sched_layout.addWidget(lbl, r, c * 2)
            sched_layout.addWidget(val, r, c * 2 + 1)
            self._sched_labels[key] = val
        top_layout.addWidget(sched_group)

        # DefUnit chain list
        chain_toolbar = QHBoxLayout()
        for text, chain in [("A链", "A"), ("B链", "B"), ("C链", "C")]:
            btn = QPushButton(text)
            btn.setFixedWidth(65)
            btn.setProperty("class", "CompactBtn")
            btn.clicked.connect(partial(self._add_chain_entry, chain))
            chain_toolbar.addWidget(btn)
        btn_del_chain = QPushButton("删除")
        btn_del_chain.setFixedWidth(65)
        btn_del_chain.setProperty("class", "CompactBtn")
        btn_del_chain.clicked.connect(self._delete_chain_entry)
        chain_toolbar.addWidget(btn_del_chain)
        btn_refr = QPushButton("刷新")
        btn_refr.setFixedWidth(65)
        btn_refr.setProperty("class", "CompactBtn")
        btn_refr.clicked.connect(self._refresh_chain_list)
        chain_toolbar.addWidget(btn_refr)
        chain_toolbar.addStretch()
        self.chain_info_lbl = QLabel("")
        self.chain_info_lbl.setProperty("class", "PropLabel")
        chain_toolbar.addWidget(self.chain_info_lbl)
        top_layout.addLayout(chain_toolbar)

        self.chain_tree = QTreeWidget()
        self.chain_tree.setHeaderLabels(["子场景", "序号", "DefUnit#", "DEFINE ID", "f0", "标记"])
        self.chain_tree.setColumnWidth(0, 60)
        self.chain_tree.setColumnWidth(1, 35)
        self.chain_tree.setColumnWidth(2, 55)
        self.chain_tree.setColumnWidth(3, 70)
        self.chain_tree.setColumnWidth(4, 35)
        self.chain_tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        self.chain_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chain_tree.setRootIsDecorated(False)
        self.chain_tree.itemSelectionChanged.connect(self._on_chain_select)
        top_layout.addWidget(self.chain_tree, 1)

        script_splitter.addWidget(top_widget)

        # Bottom: 脚本编辑器 + 预览
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        # Script toolbar
        stb = QHBoxLayout()
        self.script_info_lbl = QLabel("(未选中 DEFINE)")
        self.script_info_lbl.setProperty("class", "PropLabel")
        stb.addWidget(self.script_info_lbl, 1)
        self._btn_fix_validate = QPushButton("修复验证")
        self._btn_fix_validate.setFixedWidth(104)
        self._btn_fix_validate.setToolTip("校验脚本中 SetPos 等语句的实体号/坐标/朝向是否与当前实体一致, 不一致可一键修复")
        self._btn_fix_validate.clicked.connect(self._show_fix_validate_menu)
        stb.addWidget(self._btn_fix_validate)
        self._btn_script_tpl = QPushButton("脚本模板")
        self._btn_script_tpl.setFixedWidth(104)
        self._btn_script_tpl.setToolTip("从原版高频脚本写法中挑选模板, 一键填入脚本编辑框光标处")
        self._btn_script_tpl.clicked.connect(self._show_script_template_dialog)
        stb.addWidget(self._btn_script_tpl)
        btn_preview = QPushButton("预览")
        btn_preview.setFixedWidth(70)
        btn_preview.setToolTip("预览当前脚本执行流程")
        btn_preview.clicked.connect(self._preview_script)
        stb.addWidget(btn_preview)
        bot_layout.addLayout(stb)

        # Editor + preview (horizontal splitter)
        editor_splitter = QSplitter(Qt.Horizontal)
        editor_splitter.setHandleWidth(6)

        # Left: Script editor (CodeEditor)
        self.script_text = CodeEditor()
        self.script_text.setFont(QFont("Consolas", 10))
        self.script_text.setTabStopDistance(40)
        self.script_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.script_text.textChanged.connect(self._on_script_edit)
        # 语法高亮器 (逻辑对应 mat_editor.py _apply_syntax_highlight)
        self._script_highlighter = ScriptSyntaxHighlighter(self.script_text.document(), self._theme_id)
        editor_splitter.addWidget(self.script_text)

        # Right: Line preview
        self.script_preview = QPlainTextEdit()
        self.script_preview.setFont(QFont("Consolas", 10))
        self.script_preview.setReadOnly(True)
        self.script_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor_splitter.addWidget(self.script_preview)

        editor_splitter.setSizes([400, 400])
        bot_layout.addWidget(editor_splitter, 1)

        script_splitter.addWidget(bot_widget)
        script_splitter.setSizes([350, 400])
        layout.addWidget(script_splitter)

        # State
        self.script_text.setReadOnly(True)
        self._disable_scroll_sync = False

        # 滚动同步: 编辑器 <-> 行预览
        self._script_sb = self.script_text.verticalScrollBar()
        self._preview_sb = self.script_preview.verticalScrollBar()
        def _on_editor_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                self._disable_scroll_sync = True
                ratio = val / max(1, _es.maximum())
                _ps.setValue(int(ratio * max(1, _ps.maximum())))
                self._disable_scroll_sync = False
        def _on_preview_scroll(val, _ps=self._preview_sb, _es=self._script_sb):
            if not self._disable_scroll_sync:
                self._disable_scroll_sync = True
                ratio = val / max(1, _ps.maximum())
                _es.setValue(int(ratio * max(1, _es.maximum())))
                self._disable_scroll_sync = False
        self._script_sb.valueChanged.connect(_on_editor_scroll)
        self._preview_sb.valueChanged.connect(_on_preview_scroll)


    def _on_script_edit(self):
        self._script_dirty = True
        self._data._dirty = True  # 脚本编辑同属待保存修改, 防止切换链条目后丢失"未保存"判定 (§修复)
        if self._edit_debounce:
            self._edit_debounce.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._do_script_update)
        timer.start(150)
        self._edit_debounce = timer

    def _do_script_update(self):
        self._apply_syntax_highlight()

    def _apply_syntax_highlight(self):
        """语法高亮 — 逻辑对应 mat_editor.py _apply_syntax_highlight。
        实际逐行高亮由 ScriptSyntaxHighlighter 自动完成, 此处触发一次整文档重涂。"""
        if hasattr(self, '_script_highlighter') and self._script_highlighter:
            # rehighlight() 会触发 QPlainTextEdit.textChanged (Qt 行为), 必须屏蔽信号,
            # 否则会误触 _on_script_edit 并形成 "高亮→textChanged→防抖→高亮" 循环,
            # 令脏标记在保存后被反复置位, 导致退出时误报"有未保存的修改" (§修复)
            self.script_text.blockSignals(True)
            self._script_highlighter.rehighlight()
            self.script_text.blockSignals(False)

    def _update_line_preview(self):
        """更新右侧行功能预览 (带颜色分类) — 解析与着色逻辑对应 mat_editor.py _update_line_preview"""
        content = self.script_text.toPlainText()
        lines = content.split('\n')
        self.script_preview.clear()
        cursor = self.script_preview.textCursor()

        # 颜色格式 (对应 v1 的 pv_* tag); 灰色系在深色背景 #1a1e27 上对比度不足,
        # 深色模式提亮并复用本主题 QSS 既有灰阶 (#dcdcdc/#a5b0cb/#8a96b3), 浅色保持 v1 原值
        def mkfmt(color):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            return f
        syntax = business_colors("mat", self._theme_id)["syntax"]
        # 深色配色优化: 背景 #1a1e27 上彩色类提亮至对比度>=4.5:1 且与左侧高亮器色板语义一致
        # (白=普通命令, 紫=对话, 蓝=流程, 橙=分支, 红=道具, 绿=场景/队员); 灰阶类按
        # comment>block>raw 分层, 注释/未识别弱化以突出命令行
        fmt_cmd     = mkfmt(syntax['cmd'])     # pv_cmd   普通命令(深色=白色)
        fmt_talk    = mkfmt(syntax['talk'])    # pv_talk  对话
        fmt_flow    = mkfmt(syntax['flow'])    # pv_flow  流程
        fmt_branch  = mkfmt(syntax['branch'])  # pv_branch 分支
        fmt_getitem = mkfmt(syntax['getitem']) # pv_getitem 道具
        fmt_scene   = mkfmt(syntax['scene'])   # pv_scene  场景/队员
        fmt_comment = mkfmt(syntax['comment']) # pv_comment 注释(弱化)
        fmt_block   = mkfmt(syntax['block'])   # pv_block  块/DEFINE
        fmt_raw     = mkfmt(syntax['raw'])     # pv_raw   未识别(最弱)

        def trunc(s, max_len=28):
            s = s.replace('\n', ' ').replace('\r', '')
            if len(s) <= max_len:
                return s
            return s[:max_len - 1] + '…'

        talk_cmds = {'TalkB', 'TalkA', 'SetTalkB', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'DoTalkB', 'MenuTalk', 'SetHint'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else', 'SetNowDef'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam', 'CheckMember',
                       'Switch', 'Random'}

        seen_cmds = []  # 累积已解析命令(cmd,args), 供 CheckResult 回溯配套 MenuTalk; DEFINE 边界重置
        for i, line in enumerate(lines):
            stripped = line.strip()
            if i > 0:
                cursor.insertText('\n')
            if not stripped:
                continue
            if stripped.startswith('//'):
                cursor.insertText(trunc(stripped), fmt_comment)
                continue
            if stripped in ('{', '}; end') or stripped.startswith('};'):
                if stripped.startswith('};'):
                    seen_cmds = []  # DEFINE 结束, 重置回溯作用域
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            if stripped.startswith('DEFINE'):
                seen_cmds = []  # 新 DEFINE, 重置回溯作用域
                cursor.insertText(trunc(stripped), fmt_block)
                continue
            m = re.match(r'([A-Za-z_]\w*)\s*\((.*)\)', stripped)
            if m:
                cmd_name = m.group(1)
                args_str = m.group(2).strip()
                args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
                desc = self._format_cmd_desc(cmd_name, args)
                maxlen = 28
                # CheckResult: 回溯本 DEFINE 内配套 MenuTalk, 追加被判定的选项文本
                if cmd_name == 'CheckResult' and len(args) >= 2:
                    opt = self._resolve_menu_option(seen_cmds, len(seen_cmds), args[0], args[1])
                    if opt:
                        desc += f" →「{opt}」"
                        maxlen = 40
                seen_cmds.append((cmd_name, args))
                fmt = fmt_cmd
                if cmd_name in talk_cmds:
                    fmt = fmt_talk
                elif cmd_name in flow_cmds:
                    fmt = fmt_flow
                elif cmd_name in branch_cmds:
                    fmt = fmt_branch
                elif cmd_name == 'GetItem':
                    fmt = fmt_getitem
                elif cmd_name in ('TeamMember', 'ChangeScene'):
                    fmt = fmt_scene
                cursor.insertText(trunc(desc, maxlen), fmt)
            else:
                m2 = re.match(r'([A-Za-z_]\w+)\s*$', stripped)
                if m2 and m2.group(1) in SCRIPT_CMD_DESC:
                    cmd_name = m2.group(1)
                    desc = self._format_cmd_desc(cmd_name, [])
                    fmt = fmt_cmd
                    if cmd_name in talk_cmds:
                        fmt = fmt_talk
                    elif cmd_name in flow_cmds:
                        fmt = fmt_flow
                    elif cmd_name in branch_cmds:
                        fmt = fmt_branch
                    cursor.insertText(trunc(desc), fmt)
                else:
                    cursor.insertText(trunc(stripped, 40), fmt_raw)

    def _format_cmd_desc(self, cmd_name, args, tkt=None):
        desc_fn = SCRIPT_CMD_DESC.get(cmd_name)
        tkt = self._data.tkt_all if tkt is None else tkt
        if desc_fn:
            try:
                return desc_fn(args, tkt, self._data.item_names)
            except TypeError:
                try:
                    return desc_fn(args, tkt)
                except Exception:
                    pass
            except Exception:
                pass
        args_str = ', '.join(args) if args else ''
        return f"{cmd_name}({args_str})"

    def _resolve_menu_option(self, commands, idx, slot, expected):
        """CheckResult(变量槽, 期望值): 回溯 idx 之前最近的、写入同一变量槽的 MenuTalk,
        把期望值当作选项索引解析出对应的菜单选项文本。找不到匹配则返回 None。"""
        try:
            exp = int(expected)
        except (ValueError, TypeError):
            return None
        for pj in range(idx - 1, -1, -1):
            pc, pa = commands[pj][0], commands[pj][1]
            if pc == 'MenuTalk' and len(pa) >= 2 and pa[1] == slot:
                opts = _menu_options(self._data.tkt_all, pa[0])
                return opts[exp] if 0 <= exp < len(opts) else None
        return None

    # =========== DefUnit 链 ===========
    def _refresh_chain_list(self):
        # clear() 在清空过程中会瞬时选中其它行并发出 itemSelectionChanged (Qt 行为),
        # 误触 _on_chain_select 会把 _current_edit_define_id 覆盖成错误条目 → 刷新后跳错行。
        # 故先记录待保留的 DEFINE, 再屏蔽信号清空 (§修复: 应用修改后跳回第一条)
        preserve_define_id = self._current_edit_define_id
        self.chain_tree.blockSignals(True)
        self.chain_tree.clear()
        self.chain_tree.blockSignals(False)
        if not self._data.records:
            return
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self._data.records):
                rec = self._data.records[self._current_param_idx]
        if not rec or not has_data(rec):
            self._clear_script_editor()
            self._update_sched_info(None)
            return
        entity_id = rec['index']

        # 检测共享头指针: 若 headA/headB/headC 中有多者指向同一 DefUnit 节点,
        # 该节点会在多条链中重复显示 (数据异常, 如实体#44 headA==headB)。
        # 记录被共享的头节点索引 → 使用它的链名列表, 供下方在链头标注 ⚠共享头。
        _head_users = {}
        for _sn, _hd in (('A', 39), ('B', 40), ('C', 41)):
            _hv = rec.get(f'd{_hd}', 0)
            if _hv > 0:
                _head_users.setdefault(_hv, []).append(_sn)
        _shared_heads = {_hv: _sns for _hv, _sns in _head_users.items() if len(_sns) > 1}

        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            cur = rec.get(f'd{cur_di}', 0)
            if h <= 0 or mx <= 0:
                continue
            cur_str = f'当前={cur}' if cur > 0 else '未激活'
            # Group header (共享头节点追加 ⚠共享头 警示)
            _warn = ''
            if h in _shared_heads:
                _others = '/'.join(x for x in _shared_heads[h] if x != sub_name)
                _warn = f'  ⚠共享头(与{_others}链共用#{h})'
            group_item = QTreeWidgetItem([f'{sub_name}链', '', '', '', '', f'head=#{h} max={mx} {cur_str}{_warn}'])
            group_item.setForeground(0, QColor(TREE_SHARED_COLOR) if h in _shared_heads else QColor(TREE_VIRTUAL_COLOR))
            self.chain_tree.addTopLevelItem(group_item)
            # Traverse chain (with loop detection)
            idx = h
            visited_chain = set()
            for step in range(mx):
                if idx in visited_chain:
                    # 循环检测: 标记循环节点
                    loop_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'(循环→{idx})', '', '', '⚠循环'])
                    loop_item.setForeground(0, QColor(TREE_LOOP_COLOR))
                    self.chain_tree.addTopLevelItem(loop_item)
                    break
                visited_chain.add(idx)
                du_rec = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                if du_rec is None:
                    # 空槽检测
                    empty_item = QTreeWidgetItem([f'  {sub_name}', str(step + 1), f'#{idx}(空槽)', '', '', '⚠断开'])
                    empty_item.setForeground(0, QColor(TREE_SHARED_COLOR))
                    self.chain_tree.addTopLevelItem(empty_item)
                    break
                define_id = (du_rec['f1'] << 16) | du_rec['f0']
                marks = []
                if (step + 1) == cur:
                    marks.append('当前')
                if step == 0:
                    marks.append('链头')
                child = QTreeWidgetItem([f'  {sub_name}', str(step + 1), str(idx), str(define_id), str(du_rec['f0']), ','.join(marks)])
                self.chain_tree.addTopLevelItem(child)
                idx = du_rec['f6']
                if idx == 0:
                    break

        total = self.chain_tree.topLevelItemCount()
        self.chain_info_lbl.setText(f"entity={entity_id}, {total} 条节点")
        if total == 0:
            self._clear_script_editor()
            self.script_info_lbl.setText("(无关联 DEFINE)")
        else:
            # 刷新后优先恢复之前正在编辑的 DEFINE, 避免"应用修改"后跳回第一条 (§修复)
            target_item = None
            first_item = None
            for i in range(self.chain_tree.topLevelItemCount()):
                item = self.chain_tree.topLevelItem(i)
                if not (item.text(2).isdigit() and item.text(3).isdigit()):
                    continue
                if first_item is None:
                    first_item = item
                if preserve_define_id is not None and int(item.text(3)) == preserve_define_id:
                    target_item = item
                    break
            chosen = target_item or first_item
            if chosen is not None:
                # 阻断选择信号, 由下方显式调用 _on_chain_select 统一处理 (避免重复触发)
                self.chain_tree.blockSignals(True)
                self.chain_tree.setCurrentItem(chosen)
                self.chain_tree.blockSignals(False)
                self._on_chain_select()
        self._update_sched_info(rec)

    def _on_chain_select(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        define_id = int(define_str)
        du_idx = int(du_str)
        self._save_editor_to_define()
        self._load_define_to_editor(define_id)
        self.chain_info_lbl.setText(f"DefUnit #{du_idx} → DEFINE {define_id}")

    def _add_chain_entry(self, sub_scene, *_args):
        rec = None
        if hasattr(self, '_current_param_idx') and self._current_param_idx is not None:
            if 0 <= self._current_param_idx < len(self._data.records):
                rec = self._data.records[self._current_param_idx]
        if not rec or not has_data(rec):
            return
        entity_id = rec['index']

        # Find empty DefUnit slot
        # 槽位 0 是保留的空/空指针哨兵 (head=0 表示"无链", f6=0 表示"链尾"),
        # 绝不可分配给真实条目, 否则首次新增会令 head=0 被 _refresh_chain_list
        # 判为空链而不刷新, 再次新增又会覆盖 head 导致槽位 0 记录与其 TKD 块成为孤块(数据损坏)。
        # 因此从 1 开始搜索。
        empty_idx = None
        for i in range(1, DEFUNIT_REC_COUNT):
            existing = next((r for r in self._data.defunit_recs if r['index'] == i), None)
            if existing is None:
                empty_idx = i
                break
        if empty_idx is None:
            QMessageBox.information(self, "无空槽", f"TKDefUnit.dat 所有 {DEFUNIT_REC_COUNT} 条记录均已占用")
            return

        existing_blocks = [r['f0'] for r in self._data.defunit_recs if r['f1'] == entity_id and r['f0'] >= 256]
        new_f0 = max(existing_blocks) + 1 if existing_blocks else 256
        if new_f0 > 266:
            new_f0 = max(existing_blocks) + 1
        define_id = (entity_id << 16) | new_f0

        new_rec = {'index': empty_idx, 'f0': new_f0, 'f1': entity_id,
                   'f2': 0, 'f3': 0, 'f4': 0, 'f5': 0, 'f6': 0, 'f7': 0}
        self._data.defunit_recs.append(new_rec)
        self._data.defunit_entity.setdefault(entity_id, []).append(empty_idx)

        h_di, mx_di, cur_di = {'A': (39, 30, 33), 'B': (40, 31, 34), 'C': (41, 32, 35)}[sub_scene]
        head = rec.get(f'd{h_di}', 0)
        mx = rec.get(f'd{mx_di}', 0)
        if head == 0 or mx == 0:
            rec[f'd{h_di}'] = empty_idx
            rec[f'd{mx_di}'] = 1
            rec[f'd{cur_di}'] = 1
        else:
            idx = head
            tail = head
            for _ in range(mx):
                du_r = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                if du_r is None or du_r['f6'] == 0:
                    break
                idx = du_r['f6']
                tail = idx
            du_tail = next((r for r in self._data.defunit_recs if r['index'] == tail), None)
            if du_tail:
                du_tail['f6'] = empty_idx
            rec[f'd{mx_di}'] = mx + 1

        if define_id not in self._data.tkd_define_map:
            d = {'define_id': define_id, 'comment': '', 'prefix_lines': [],
                 'body_lines': ['{', 'End(0)', '}; end'], 'line_start': -1, 'line_end': -1,
                 'header_line': f'DEFINE {define_id}'}
            self._data.tkd_defines.append(d)
            self._data.tkd_define_map[define_id] = d

        self._data._dirty = True
        self._script_dirty = True
        self._sync_form_dwords(rec, (h_di, mx_di, cur_di))
        self._refresh_chain_list()
        QMessageBox.information(self, "新增成功", f"DefUnit #{empty_idx} → DEFINE {define_id} ({sub_scene}场景)")

    def _delete_chain_entry(self):
        sel = self.chain_tree.selectedItems()
        if not sel:
            return
        item = sel[0]
        du_str = item.text(2)
        define_str = item.text(3)
        if not du_str.isdigit() or not define_str.isdigit():
            return
        du_idx = int(du_str)
        define_id = int(define_str)
        du_rec = next((r for r in self._data.defunit_recs if r['index'] == du_idx), None)
        if du_rec is None:
            return
        entity_id = du_rec['f1']
        if themed_question(self, "确认删除",
                                f"删除 DefUnit #{du_idx} → DEFINE {define_id}?\n此操作同时从 TKD.dat 删除对应 DEFINE 块。",
                                    buttons=QMessageBox.Ok | QMessageBox.Cancel,
                                    default=QMessageBox.Cancel) != QMessageBox.Ok:
            return

        rec = self._data.records[self._current_param_idx]
        _modified_dis = []
        # 从 A/B/C 全部链中摘除该节点 (不能在首个匹配链后 break):
        # 若多条链共享同一头节点 (如实体#44 headA==headB 指向同一 DefUnit),
        # 只摘一条会残留悬空头指针 → 刷新后显示为 "空槽/断开" 且再也删不掉。
        for sub_name, h_di, mx_di, cur_di in [('A', 39, 30, 33), ('B', 40, 31, 34), ('C', 41, 32, 35)]:
            h = rec.get(f'd{h_di}', 0)
            mx = rec.get(f'd{mx_di}', 0)
            if h <= 0:
                continue
            prev = None
            idx = h
            for _ in range(mx):
                if idx == du_idx:
                    break
                prev = idx
                du_r = next((r for r in self._data.defunit_recs if r['index'] == idx), None)
                idx = du_r['f6'] if du_r else 0
            if idx != du_idx:
                continue
            if prev is None:
                rec[f'd{h_di}'] = du_rec['f6']
            else:
                prev_rec = next((r for r in self._data.defunit_recs if r['index'] == prev), None)
                if prev_rec:
                    prev_rec['f6'] = du_rec['f6']
            new_mx = max(0, mx - 1)
            rec[f'd{mx_di}'] = new_mx
            cur = rec.get(f'd{cur_di}', 0)
            if cur > new_mx:
                rec[f'd{cur_di}'] = new_mx
            _modified_dis.extend([h_di, mx_di, cur_di])

        du_rec['f0'] = du_rec['f1'] = du_rec['f6'] = 0
        self._data.defunit_recs = [r for r in self._data.defunit_recs if r['index'] != du_idx]
        if entity_id in self._data.defunit_entity and du_idx in self._data.defunit_entity[entity_id]:
            self._data.defunit_entity[entity_id].remove(du_idx)
        if define_id in self._data.tkd_define_map:
            d = self._data.tkd_define_map.pop(define_id)
            if d in self._data.tkd_defines:
                self._data.tkd_defines.remove(d)

        self._data._dirty = True
        self._script_dirty = True
        if _modified_dis:
            self._sync_form_dwords(rec, _modified_dis)
        self.script_text.setReadOnly(False)
        self.script_text.blockSignals(True)
        self.script_text.clear()
        self.script_text.blockSignals(False)
        self.script_text.setReadOnly(True)
        self._current_edit_define_id = None
        self._refresh_chain_list()

    def _sync_form_dwords(self, rec, dis):
        for di in dis:
            val = str(rec[f'd{di}'])
            for fields in (ALL_EDIT_FIELDS, RUNTIME_FIELDS):
                for key, f_di, label, cmt in fields:
                    if f_di == di and key in self._edit_vars:
                        w = self._edit_vars[key]
                        if isinstance(w, QLineEdit):
                            w.setText(val)
                        break
            for prefix in ('raw_', 'd'):
                key = f'{prefix}{di}'
                w = self._edit_vars.get(key)
                if isinstance(w, QLineEdit):
                    w.setText(val)
                    break

    # =========== 脚本调度信息 ===========
    def _update_sched_info(self, rec):
        if rec is None or is_empty(rec):
            for key in self._sched_labels:
                self._sched_labels[key].setText("")
            return
        flags = rec.get('d2', 0)
        tval = rec.get('d0', 0)
        en = (flags & 1) != 0
        self._sched_labels['enabled'].setText("✓ 已启用" if en else "✗ 未启用")
        self._sched_labels['enabled'].setProperty("status", "loaded" if en else "missing")
        self._sched_labels['enabled'].style().unpolish(self._sched_labels['enabled'])
        self._sched_labels['enabled'].style().polish(self._sched_labels['enabled'])
        pk = (flags & 4) != 0
        self._sched_labels['pickable'].setText("✓ 可交互" if pk else "✗ 不可交互")
        tick = rec.get('d4', 0)
        self._sched_labels['tick'].setText(f"{tick} (越大越慢)" if tick > 0 else "0 (无Tick)")
        timer = rec.get('d3', 0)
        self._sched_labels['timer'].setText(f"{timer} (暂停中)" if timer > 0 else "0 (正常运行)")
        cur_a = rec.get('d33', 0)
        head_a = rec.get('d39', 0)
        max_a = rec.get('d30', 0)
        if head_a > 0 and max_a > 0:
            a_status = "自动执行中" if cur_a > 0 else "已定义(未激活)"
            self._sched_labels['chain_a'].setText(f"✓ {a_status} [head=#{head_a},max={max_a},cur={cur_a}]")
        else:
            self._sched_labels['chain_a'].setText("— 无")
        cur_b = rec.get('d34', 0)
        head_b = rec.get('d40', 0)
        max_b = rec.get('d31', 0)
        if head_b > 0 and max_b > 0:
            b_status = "👆 交互触发" if cur_b > 0 else "已定义(未激活)"
            self._sched_labels['chain_b'].setText(f"✓ {b_status} [head=#{head_b},max={max_b},cur={cur_b}]")
        else:
            self._sched_labels['chain_b'].setText("— 无")
        cur_c = rec.get('d35', 0)
        head_c = rec.get('d41', 0)
        max_c = rec.get('d32', 0)
        if head_c > 0 and max_c > 0:
            c_status = "✱ 活跃" if cur_c > 0 else "已定义(未激活)"
            self._sched_labels['chain_c'].setText(f"✓ {c_status} [head=#{head_c},max={max_c},cur={cur_c}]")
        else:
            self._sched_labels['chain_c'].setText("— 无")
        trigger_map = {
            5: "仅脚本", 10: "接近传送", 15: "接近触发", 16: "接近遇敌",
            20: "点击对话", 110: "点击机关", 200: "点击对话",
        }
        trigger = trigger_map.get(tval, "未知")
        if cur_a > 0:
            trigger += " + A链自动(Tick)"
        self._sched_labels['trigger'].setText(trigger)

    # =========== 脚本模板 ===========
    def _show_script_template_dialog(self):
        """脚本模板选择器: 展示从原版 TKD.dat 高频写法归纳的模板, 选中后插入编辑框光标处。
        模板数据见 mat_script_templates.SCRIPT_TEMPLATES (按命令频率/骨架统计归纳)。"""
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "脚本模板", "请先在上方链列表选择一个 DEFINE 脚本块")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("脚本模板 — 常用脚本快速填充")
        dlg.resize(760, 540)
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            dlg.setWindowIcon(QIcon(ico))
        dlg_layout = QVBoxLayout(dlg)

        head = QLabel("挑选一个常用脚本模板, 双击或点击 [插入到光标处] 填入编辑框; "
                     "模板中的数字为占位值, 按首行注释替换为实际编号即可。")
        head.setProperty("class", "InfoTitle")
        head.setWordWrap(True)
        dlg_layout.addWidget(head)

        splitter = QSplitter(Qt.Horizontal)

        # 左: 模板树 (分类 → 模板)
        tree = QTreeWidget()
        tree.setHeaderLabels(["模板", "说明"])
        tree.setColumnWidth(0, 170)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setRootIsDecorated(True)
        for cat_name, items in SCRIPT_TEMPLATES:
            cat_item = QTreeWidgetItem([cat_name, ""])
            cf = cat_item.font(0)
            cf.setBold(True)
            cat_item.setFont(0, cf)
            cat_item.setFlags(Qt.ItemIsEnabled)  # 分类节点不可选中
            tree.addTopLevelItem(cat_item)
            for name, desc, body in items:
                it = QTreeWidgetItem([name, desc])
                it.setData(0, Qt.UserRole, body)
                it.setToolTip(1, desc)
                cat_item.addChild(it)
            cat_item.setExpanded(True)
        splitter.addWidget(tree)

        # 右: 模板内容预览 (只读, 复用脚本语法高亮)
        preview = QPlainTextEdit()
        preview.setFont(QFont("Consolas", 10))
        preview.setReadOnly(True)
        preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        preview.setPlaceholderText("← 选择左侧模板查看内容")
        self._tpl_preview_hl = ScriptSyntaxHighlighter(preview.document(), self._theme_id)
        splitter.addWidget(preview)
        splitter.setSizes([300, 440])
        dlg_layout.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_insert = QPushButton("插入到光标处")
        btn_insert.setDefault(True)
        btn_insert.setEnabled(False)
        btn_cancel = QPushButton("取消")
        btn_row.addWidget(btn_insert)
        btn_row.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_row)

        def _current_body():
            sel = tree.selectedItems()
            return sel[0].data(0, Qt.UserRole) if sel else None

        def _on_sel():
            body = _current_body()
            if body:
                preview.setPlainText(body)
                btn_insert.setEnabled(True)
            else:
                preview.clear()
                btn_insert.setEnabled(False)
        tree.itemSelectionChanged.connect(_on_sel)
        tree.itemDoubleClicked.connect(
            lambda item, col: dlg.accept() if item.data(0, Qt.UserRole) else None)
        btn_insert.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return
        body = _current_body()
        if body:
            self._insert_script_template(body)

    def _insert_script_template(self, body):
        """把模板 body 插入脚本编辑框光标处 (独占完整行), 随后刷新高亮/行预览并标记未保存。"""
        body = body.rstrip('\n')
        if not self.script_text.toPlainText().strip():
            self.script_text.setPlainText(body)
        else:
            cursor = self.script_text.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + body)
            cursor.endEditBlock()
            self.script_text.setTextCursor(cursor)
        self.script_text.setFocus()
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._save_editor_to_define()
        self._script_dirty = True
        self._data._dirty = True
        self.status_var.setText("已插入脚本模板 (请按首行注释替换占位数字)")

    # =========== 脚本修复验证 ===========
    def _show_fix_validate_menu(self):
        """弹出"修复验证"菜单, 选择要校验的脚本语句类型 (当前仅 SetPos, 预留扩展)"""
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "修复验证", "请先在上方链列表选择一个 DEFINE 脚本块")
            return
        menu = QMenu(self)
        act_setpos = menu.addAction("SetPos — 校验实体号 / 坐标 / 朝向")
        act_setpos.triggered.connect(self._fix_validate_setpos)
        btn = self._btn_fix_validate
        menu.exec(btn.mapToGlobal(QPoint(0, btn.height())))

    def _current_script_entity(self):
        """返回当前脚本所属实体记录 (由属性面板选中项决定, 与链列表同源)。无有效实体返回 None"""
        if self._current_param_idx is None:
            return None
        if not (0 <= self._current_param_idx < len(self._data.records)):
            return None
        rec = self._data.records[self._current_param_idx]
        return rec if has_data(rec) else None

    def _fix_validate_setpos(self):
        """校验当前脚本内所有 SetPos 的实体号/坐标/朝向是否与当前实体一致, 不一致时弹确认框修复。
        用途: 通用模板脚本(如"通用加入")复制到不同角色后, 一键把 SetPos 同步到当前实体实际值。"""
        rec = self._current_script_entity()
        if rec is None:
            QMessageBox.information(self, "SetPos 修复验证", "未找到当前脚本所属实体, 请先选中实体并选择 DEFINE")
            return
        ent_idx = rec['index']
        cur_x = rec.get('d10', 0)
        cur_y = rec.get('d11', 0)
        cur_dir = rec.get('d13', 0)

        lines = self.script_text.toPlainText().split('\n')
        setpos_re = re.compile(r'^(\s*)SetPos\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)(.*)$')
        total = 0
        mismatches = []  # (line_idx, indent, trailing, cur_stmt, new_stmt)
        for i, line in enumerate(lines):
            m = setpos_re.match(line)
            if not m:
                continue
            total += 1
            indent = m.group(1)
            e = int(m.group(2)); x = int(m.group(3)); y = int(m.group(4)); dd = int(m.group(5))
            trailing = m.group(6)
            # 目标: 显式实体号→当前实体索引; -1(上下文)/-2(自身) 相对引用保持不变; 坐标/朝向一律对齐当前实体
            tgt_e = e if e < 0 else ent_idx
            if tgt_e == e and x == cur_x and y == cur_y and dd == cur_dir:
                continue
            cur_stmt = f"SetPos({e},{x},{y},{dd})"
            new_stmt = f"SetPos({tgt_e},{cur_x},{cur_y},{cur_dir})"
            mismatches.append((i, indent, trailing, cur_stmt, new_stmt))

        if total == 0:
            QMessageBox.information(self, "SetPos 修复验证", "当前脚本未找到 SetPos 语句")
            return
        dir_txt = _dir_name(str(cur_dir), str(ent_idx))
        if not mismatches:
            QMessageBox.information(
                self, "SetPos 修复验证",
                f"当前脚本共 {total} 处 SetPos, 均与当前实体一致, 无需修复\n\n"
                f"当前实体 #{ent_idx} — 坐标({cur_x},{cur_y}) 朝向{cur_dir}({dir_txt})")
            return

        # 不一致 → 弹确认对话框 (逐条展示差异, 复选框默认全选, 用户确认后修复)
        dlg = QDialog(self)
        dlg.setWindowTitle("SetPos 修复验证")
        dlg.resize(660, 440)
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            dlg.setWindowIcon(QIcon(ico))
        dlg_layout = QVBoxLayout(dlg)

        head = QLabel(
            f"当前实体 #{ent_idx} — 坐标({cur_x},{cur_y}) 朝向{cur_dir}({dir_txt})\n"
            f"发现 {len(mismatches)} / {total} 处 SetPos 与当前实体不一致, 勾选需要修复的项后点击 [修复选中项]:")
        head.setProperty("class", "InfoTitle")
        head.setWordWrap(True)
        dlg_layout.addWidget(head)

        tree = QTreeWidget()
        tree.setHeaderLabels(["修复", "行", "当前语句", "建议修复为"])
        tree.setColumnWidth(0, 44)
        tree.setColumnWidth(1, 48)
        tree.setColumnWidth(2, 230)
        tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        tree.setRootIsDecorated(False)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        item_map = []  # (item, line_idx, indent, trailing, new_stmt)
        for (i, indent, trailing, cur_stmt, new_stmt) in mismatches:
            it = QTreeWidgetItem(["", str(i + 1), cur_stmt, new_stmt])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            it.setForeground(2, QColor(TREE_LOOP_COLOR))
            it.setForeground(3, QColor(TREE_FLAG_COLOR))
            tree.addTopLevelItem(it)
            item_map.append((it, i, indent, trailing, new_stmt))
        dlg_layout.addWidget(tree, 1)

        btn_row = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        btn_fix = QPushButton("修复选中项")
        btn_fix.setDefault(True)
        btn_cancel = QPushButton("取消")
        btn_row.addWidget(btn_fix)
        btn_row.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_row)

        def _set_all(state):
            for entry in item_map:
                entry[0].setCheckState(0, state)
        btn_all.clicked.connect(lambda: _set_all(Qt.Checked))
        btn_none.clicked.connect(lambda: _set_all(Qt.Unchecked))
        btn_cancel.clicked.connect(dlg.reject)
        btn_fix.clicked.connect(dlg.accept)

        if dlg.exec() != QDialog.Accepted:
            return

        new_lines = list(lines)
        fixed = 0
        for (it, i, indent, trailing, new_stmt) in item_map:
            if it.checkState(0) == Qt.Checked:
                new_lines[i] = f"{indent}{new_stmt}{trailing}"
                fixed += 1
        if fixed == 0:
            QMessageBox.information(self, "SetPos 修复验证", "未勾选任何项, 未做修改")
            return

        self.script_text.blockSignals(True)
        self.script_text.setPlainText('\n'.join(new_lines))
        self.script_text.blockSignals(False)
        self._apply_syntax_highlight()
        self._update_line_preview()
        self._save_editor_to_define()
        self._script_dirty = True
        self._data._dirty = True
        QMessageBox.information(self, "SetPos 修复验证", f"已修复 {fixed} 处 SetPos → 对齐实体 #{ent_idx} 坐标({cur_x},{cur_y}) 朝向{cur_dir}")

    # =========== 脚本预览 ===========
    def _preview_script(self):
        self._save_editor_to_define()
        if self._current_edit_define_id is None:
            QMessageBox.information(self, "预览", "请先选择一个 DEFINE 脚本块")
            return
        d = self._data.tkd_define_map.get(self._current_edit_define_id)
        if d is None:
            QMessageBox.information(self, "预览", "未找到当前 DEFINE 数据")
            return
        body_lines = d.get('body_lines', [])
        commands = self._parse_script_commands(body_lines)
        if not commands:
            QMessageBox.information(self, "预览", "未解析到有效命令")
            return
        self._preview_cmds = commands
        self._preview_step = 0

        win = QDialog(self)
        win.setWindowTitle(f"脚本预览 — DEFINE {self._current_edit_define_id}")
        win.resize(780, 680)
        # 图标
        ico = os.path.join(os.path.dirname(__file__), 'TKS.ico')
        if os.path.exists(ico):
            win.setWindowIcon(QIcon(ico))
        main_layout = QVBoxLayout(win)

        # 顶部信息栏
        info_row = QHBoxLayout()
        comment = d.get('comment', '')
        info_text = f"DEFINE {self._current_edit_define_id}"
        if comment:
            info_text += f"  —  {comment}"
        info_text += f"  |  {len(commands)} 条命令"
        info_lbl = QLabel(info_text)
        info_lbl.setProperty("class", "InfoTitle")
        info_row.addWidget(info_lbl, 1)
        self._pv_info_lbl = QLabel("")
        info_row.addWidget(self._pv_info_lbl)
        main_layout.addLayout(info_row)

        # 命令列表 + 详情面板 (垂直分割)
        splitter = QSplitter(Qt.Vertical)

        # 命令列表 (带颜色标签)
        self._pv_tree = QTreeWidget()
        self._pv_tree.setHeaderLabels(["#", "命令", "描述"])
        self._pv_tree.setColumnWidth(0, 35)
        self._pv_tree.setColumnWidth(1, 110)
        self._pv_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self._pv_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pv_tree.setRootIsDecorated(False)

        # 填充命令 (带颜色分类)
        talk_cmds = {'TalkB', 'TalkA', 'BlackTalk', 'ShowText', 'MenuChoice',
                     'SysTalk', 'SetTalkB', 'SetHint', 'DoTalkB', 'MenuTalk'}
        flow_cmds = {'End', 'Yield', 'Jump', 'Else'}
        branch_cmds = {'CheckFlag', 'CheckResult', 'CheckItem', 'CheckTeam',
                       'CheckMember', 'Switch', 'Random'}
        # 配色与右侧行预览 (_update_line_preview) 统一, 按主题切换深/浅色板
        syntax = business_colors("mat", self._theme_id)["syntax"]
        c_talk    = QColor(syntax['talk'])    # 紫=对话
        c_flow    = QColor(syntax['flow'])    # 蓝=流程
        c_branch  = QColor(syntax['branch'])  # 橙=分支
        c_getitem = QColor(syntax['getitem']) # 红=道具
        c_default = QColor(syntax['cmd'])      # 普通命令(深色=白色)
        for si, (cmd_name, args, line_text, line_idx) in enumerate(commands):
            desc = self._format_cmd_desc(cmd_name, args)
            # CheckResult: 回溯配套 MenuTalk, 在描述后追加被判定的选项文本
            if cmd_name == 'CheckResult' and len(args) >= 2:
                opt = self._resolve_menu_option(commands, si, args[0], args[1])
                if opt:
                    desc += f" → 选中「{opt}」"
            item = QTreeWidgetItem([str(si + 1), cmd_name, desc])
            # 颜色分类
            if cmd_name in talk_cmds:
                color = c_talk
            elif cmd_name in flow_cmds:
                color = c_flow
            elif cmd_name in branch_cmds:
                color = c_branch
            elif cmd_name == 'GetItem':
                color = c_getitem
            else:
                color = c_default
            for c in range(3):
                item.setForeground(c, color)
            item.setData(0, Qt.UserRole, si)  # 存储步骤索引
            self._pv_tree.addTopLevelItem(item)

        splitter.addWidget(self._pv_tree)

        # 详情面板 (QTextEdit 支持富文本颜色)
        self._pv_detail = QTextEdit()
        self._pv_detail.setReadOnly(True)
        self._pv_detail.setFont(QFont("Consolas", 10))
        # 预配置 FCOLOR 1-32 颜色格式 (按主题调整对比度, 避免白字白底不可见)
        self._pv_color_formats = {}
        for ci in range(1, 33):
            fmt = QTextCharFormat()
            fmt.setForeground(self._readable_tkt_color(GAME_COLORS[ci]))
            self._pv_color_formats[f'tkt_c{ci}'] = fmt
        # 物品名红色格式
        self._pv_item_red_fmt = QTextCharFormat()
        self._pv_item_red_fmt.setForeground(QColor(PV_ITEM_RED))
        self._pv_item_red_fmt.setFontWeight(QFont.Bold)
        # 动态 FCOLORD 格式缓存
        self._pv_dynamic_color_tags = {}
        splitter.addWidget(self._pv_detail)
        splitter.setSizes([380, 200])
        main_layout.addWidget(splitter, 1)

        # 选中事件
        self._pv_tree.itemSelectionChanged.connect(self._preview_on_select)
        # 选中第一步
        if self._pv_tree.topLevelItemCount() > 0:
            self._pv_tree.setCurrentItem(self._pv_tree.topLevelItem(0))

        self._preview_win = win
        win.exec()
