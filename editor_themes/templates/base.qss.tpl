/* ChatGPT Desktop 风格深色主题 — 中性灰层级 + 绿色交互强调 */
/* 应用底色 #212121 / 侧栏与输入表面 #171717、#2f2f2f / 强调色 #10a37f */

QWidget {
    background-color: {{bg_root}};
    color: {{text_base}};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: {{fs_body}};
}
QMainWindow, QDialog {
    background-color: {{bg_window}};
}
QMainWindow#EditorWindow {
    background-color: {{bg_window}};
}
QToolTip {
    background-color: {{bg_04}};
    color: {{fg_02}};
    border: {{bd_01}};
    border-radius: 6px;
    padding: 6px 8px;
}

/* ── 表格、树与通用项目视图 ── */
QAbstractItemView {
    background-color: {{bg_05}};
    color: {{text_primary}};
    selection-background-color: {{sel_01}};
    selection-color: {{text_primary}};
    outline: none;
}
QTableWidget, QTreeWidget, QTableView, QTreeView {
    background-color: {{bg_surface}};
    color: {{text_base}};
    border: {{bd_regular}};
    border-radius: {{radius_md}};
    gridline-color: {{gridline_color_01}};
    selection-background-color: {{sel_02}};
    selection-color: {{fg_06}};
    alternate-background-color: {{altbg_01}};
    outline: none;
}
QTableWidget::item, QTreeWidget::item,
QTableView::item, QTreeView::item {
    min-height: 28px;
    padding: 6px 10px;
    border: none;
    /* 统一编辑器表格单元格的可读空间，避免文字贴边或被裁切。 */
}
QTableWidget::item:selected, QTreeWidget::item:selected,
QTableView::item:selected, QTreeView::item:selected {
    background-color: {{sel_01}};
    color: {{text_primary}};
}
QWidget#WarDataEditorRightPanel QTableWidget,
QWidget#WarDataEditorRightPanel QTableView {
    selection-background-color: transparent;
    selection-color: {{text_primary}};
}
QWidget#WarDataEditorRightPanel QTableWidget::item:selected,
QWidget#WarDataEditorRightPanel QTableView::item:selected {
    background-color: transparent;
    color: {{text_primary}};
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: {{bg_hover}};
}
QHeaderView {
    background-color: {{bg_09}};
}
QHeaderView::section {
    background-color: {{bg_10}};
    color: {{fg_10}};
    border: none;
    border-bottom: {{bd_regular}};
    padding: 7px 8px;
}
QHeaderView::section:hover {
    background-color: {{bg_11}};
    color: {{text_primary}};
}
QHeaderView::section:pressed {
    background-color: {{accent_soft}};
    color: {{fg_12}};
}
QTableCornerButton::section {
    background-color: {{bg_09}};
    border: none;
    border-bottom: {{bd_inset}};
}

/* ── 文本输入 ── */
QPlainTextEdit, QLineEdit, QTextEdit {
    background-color: {{bg_surface}};
    color: {{text_primary}};
    border: {{bd_regular}};
    padding: 7px 9px;
    border-radius: {{radius_md}};
    selection-background-color: {{accent}};
    selection-color: #ffffff;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {
    border-color: {{bd_hover}};
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: {{accent}};
}
/* 数值输入校验失败 (ui_helpers.mark_invalid 置 invalid 属性) */
QLineEdit[invalid="true"] {
    border: {{bd_error}};
}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    background-color: {{bg_15}};
    color: {{fg_14}};
    border-color: {{bd_08}};
}

/* ── 按钮与工具按钮 ── */
QPushButton {
    background-color: {{bg_16}};
    color: {{fg_15}};
    border: {{bd_09}};
    border-radius: {{radius_md}};
    padding: 6px 12px;
    min-height: 18px;
}
QPushButton:hover {
    background-color: {{bg_17}};
    border-color: {{bd_hover}};
}
QPushButton:focus {
    border-color: {{accent}};
}
QPushButton:pressed {
    background-color: {{bg_18}};
    border-color: {{accent}};
}
QPushButton:checked {
    background-color: {{accent_soft}};
    color: {{fg_12}};
    border-color: {{accent}};
}
QPushButton:disabled {
    background-color: {{bg_20}};
    color: {{fg_17}};
    border-color: {{bd_08}};
}
QPushButton:flat {
    background-color: transparent;
    border-color: transparent;
}
QPushButton:flat:hover {
    background-color: {{bg_11}};
    border-color: transparent;
}
QPushButton:flat:pressed {
    background-color: {{accent_soft}};
}
QToolButton {
    background-color: transparent;
    color: {{fg_18}};
    border: 1px solid transparent;
    border-radius: {{radius_md}};
    padding: 5px 8px;
}
QToolButton:hover {
    background-color: {{bg_11}};
    color: {{text_primary}};
    border-color: {{hairline}};
}
QToolButton:pressed, QToolButton:checked {
    background-color: {{accent_soft}};
    color: {{fg_12}};
    border-color: {{accent}};
}

/* ── 下拉框与数值输入 ── */
QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    background-color: {{bg_05}};
    color: {{text_primary}};
    border: {{bd_17}};
    border-radius: {{radius_md}};
    padding: 6px 9px;
    min-height: 18px;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QTimeEdit:hover, QDateTimeEdit:hover {
    border-color: {{bd_hover}};
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {
    border-color: {{accent}};
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QComboBox:hover::drop-down, QComboBox:focus::drop-down {
    background-color: {{bg_26}};
}
QComboBox::down-arrow {
    image: {{image_01}};
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background-color: {{bg_27}};
    color: {{fg_22}};
    border: {{bd_regular}};
    selection-background-color: {{accent}};
    selection-color: #ffffff;
    outline: none;
    padding: 4px;
    border-radius: {{radius_md}};
    show-decoration-selected: 1;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 6px 10px;
    border-radius: 6px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: {{bg_hover}};
    color: {{text_primary}};
}
QComboBox QAbstractItemView::item:selected {
    background-color: {{accent}};
    color: #ffffff;
}
QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    padding-right: 24px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QDateEdit::up-button, QTimeEdit::up-button, QDateTimeEdit::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    background-color: {{bg_30}};
    width: 20px;
    border-left: {{bd_inset}};
    border-bottom: {{bd_inset}};
    border-top-right-radius: 7px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QDateEdit::up-arrow, QTimeEdit::up-arrow, QDateTimeEdit::up-arrow {
    image: {{image_02}};
    width: 10px;
    height: 10px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button,
QDateEdit::down-button, QTimeEdit::down-button, QDateTimeEdit::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    background-color: {{bg_30}};
    width: 20px;
    border-left: {{bd_inset}};
    border-top: {{bd_inset}};
    border-bottom-right-radius: 7px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow,
QDateEdit::down-arrow, QTimeEdit::down-arrow, QDateTimeEdit::down-arrow {
    image: {{image_01}};
    width: 10px;
    height: 10px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: {{bg_32}};
}

/* ── 列表与选择器 ── */
QListWidget {
    background-color: {{bg_surface}};
    color: {{text_primary}};
    border: {{bd_regular}};
    border-radius: {{radius_md}};
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    border: none;
    border-radius: 6px;
    padding: 5px 8px;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: {{sel_01}};
    color: {{text_primary}};
}
QListWidget::item:focus, QTreeWidget::item:focus {
    outline: none;
}
QListWidget::indicator, QTableWidget::indicator {
    width: 16px;
    height: 16px;
    background-color: {{bg_surface}};
    border: {{bd_26}};
    border-radius: 5px;
}
QListWidget::indicator:checked, QTableWidget::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
    image: url(svg/checkmark.svg);
}
QListWidget::indicator:hover, QTableWidget::indicator:hover {
    border-color: {{bd_28}};
}

/* ── 分组框、复选框与单选按钮 ── */
QGroupBox {
    background-color: {{bg_37}};
    border: {{bd_regular}};
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {{fg_26}};
}
QCheckBox, QRadioButton {
    color: {{text_primary}};
    spacing: 7px;
    padding: 3px 0;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    background-color: {{bg_38}};
    border: {{bd_30}};
}
QCheckBox::indicator {
    border-radius: 5px;
}
QRadioButton::indicator {
    border-radius: {{radius_md}};
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
    image: url(svg/checkmark.svg);
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: {{accent}};
}
QCheckBox:disabled, QRadioButton:disabled {
    color: {{fg_14}};
}

/* ── 分割线与滚动条 ── */
QSplitter::handle {
    image: none;
    background-color: transparent;
}
QSplitter {
    background-color: transparent;
}
QSplitter::handle:horizontal {
    border-left: {{bd_33}};
    margin-left: 3px;
    margin-right: 3px;
}
QSplitter::handle:vertical {
    border-top: {{bd_33}};
    margin-top: 3px;
    margin-bottom: 3px;
}
QSplitter::handle:horizontal:hover, QSplitter::handle:vertical:hover {
    border-color: {{accent}};
}
QScrollBar:vertical {
    background: {{bg_40}};
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: {{bg_41}};
    border-radius: 4px;
    min-height: 28px;
    margin: 2px 1px;
}
QScrollBar::handle:vertical:hover {
    background: {{accent}};
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollBar:horizontal {
    background: {{bg_40}};
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: {{bg_41}};
    border-radius: 4px;
    min-width: 28px;
    margin: 1px 2px;
}
QScrollBar::handle:horizontal:hover {
    background: {{accent}};
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── 菜单栏与菜单 ── */
QMenuBar {
    background-color: {{bg_root}};
    color: {{fg_29}};
    border-bottom: {{bd_36}};
}
QMenuBar::item {
    background: transparent;
    padding: 6px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background-color: {{bg_47}};
    color: {{text_primary}};
}
QMenuBar::item:pressed {
    background-color: {{bg_48}};
    color: {{fg_31}};
}
QMenu {
    background-color: {{bg_27}};
    color: {{text_primary}};
    border: {{bd_regular}};
    border-radius: {{radius_md}};
    padding: 5px;
}
QMenu::item {
    padding: 7px 28px 7px 10px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: {{bg_50}};
    color: {{fg_33}};
}
QMenu::icon {
    padding-left: 4px;
}
QMenu::separator {
    height: 1px;
    background-color: {{bg_51}};
    margin: 5px 7px;
}

/* 所有编辑器下拉菜单共用原生 QMenu，保持单层圆角边框。 */
QMenu#EditorComboMenu {
    background-color: {{bg_05}};
    color: {{text_primary}};
    border: {{bd_17}};
    border-radius: {{radius_md}};
    padding: 4px;
}
QMenu#EditorComboMenu::item {
    padding: 6px 28px 6px 10px;
    border-radius: 5px;
}
QMenu#EditorComboMenu::item:selected {
    background-color: {{bg_hover}};
    color: {{text_primary}};
}
QMenu#EditorComboMenu::item:checked {
    background-color: {{accent}};
    color: #ffffff;
    font-weight: 600;
}

/* ── 下拉框可滚动弹层 (条目 >10 时替代 QMenu) ── */
QWidget#EditorComboPopup {
    background-color: {{bg_05}};
    border: {{bd_17}};
    border-radius: {{radius_md}};
}
QListWidget#EditorComboList {
    background-color: transparent;
    border: none;
    color: {{text_primary}};
    outline: none;
    padding: 0;
    /* 抵消 QComboBox QAbstractItemView{padding:4px} 泄漏到本列表, 否则
       视口比控件矮 8px, 弹层显示不足 max_visible 行而出现空隙 */
}
QListWidget#EditorComboList::item {
    padding: 6px 10px;
    border-radius: 5px;
}
QListWidget#EditorComboList::item:hover {
    background-color: {{bg_hover}};
    color: {{text_primary}};
}
QListWidget#EditorComboList::item:selected {
    background-color: {{accent}};
    color: #ffffff;
    font-weight: 600;
}
QListWidget#EditorComboList::item:disabled {
    color: {{fg_38}};
}

/* ── Tab 页 ── */
QTabWidget::pane {
    border: {{bd_regular}};
    background-color: {{bg_root}};
    top: -1px;
    border-radius: 10px;
    padding: 4px;
}
QTabBar::tab {
    background: {{bg_59}};
    color: {{fg_39}};
    border: {{bd_41}};
    padding: 7px 13px;
    margin: 2px 2px 0 0;
    border-radius: {{radius_md}};
    min-height: 18px;
}
QTabBar::tab:selected {
    background: {{bg_60}};
    color: {{fg_40}};
    border: {{bd_inset}};
    border-bottom: {{bd_accent2}};
}
QTabBar::tab:hover:!selected {
    background: {{bg_47}};
    color: {{text_primary}};
    border-color: {{gridline_color_01}};
}
QTabBar::tab:disabled {
    color: {{fg_42}};
}
QTabBar QToolButton {
    background-color: {{bg_62}};
    border: {{bd_inset}};
    border-radius: 6px;
    padding: 2px;
}

/* ── 连续内容面板页签: 平面导航 + 统一 TabPane ── */
QTabWidget[tabStyle="flat"] {
    background-color: transparent;
    border: none;
}
QTabWidget[tabStyle="flat"]::pane {
    border: {{bd_17}};
    border-top: none;
    border-radius: 0px 0px 8px 8px;
    background-color: {{bg_window}};
    padding: 0px;
    top: 0px;
}
QTabWidget[tabStyle="flat"] QTabBar {
    background-color: {{bg_window}};
    border: none;
    border-bottom: {{bd_17}};
}
QTabWidget[tabStyle="flat"] QTabBar::tab {
    background-color: transparent;
    color: {{text_muted}};
    border: none;
    border-bottom: {{bd_17}};
    border-radius: 0px;
    padding: 8px 13px;
    margin: 0px;
    min-height: 20px;
}
QTabWidget[tabStyle="flat"] QTabBar::tab:hover:!selected {
    background-color: {{bg_65}};
    color: {{text_primary}};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabWidget[tabStyle="flat"] QTabBar::tab:selected {
    background-color: {{bg_window}};
    color: {{text_primary}};
    font-weight: 600;
    border: {{bd_17}};
    border-top: {{bd_accent2}};
    border-bottom: {{bd_51}};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-bottom: -1px;
}
QTabWidget[tabStyle="flat"] QTabBar::tab:disabled {
    color: {{fg_46}};
}
QWidget#EditorTabCorner {
    background-color: {{bg_window}};
    border: none;
    border-bottom: {{bd_17}};
}

/* ── 编辑器面板、图形视图与滚动区域 ── */
QWidget#DockPanel {
    background-color: transparent;
    border: none;
}
QFrame#DockHeader {
    background-color: {{bg_68}};
    border: {{bd_inset}};
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QWidget#DockBody {
    background-color: {{bg_root}};
    border: {{bd_regular}};
    border-top: none;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QWidget#PalettePanel {
    background-color: {{bg_15}};
    border: {{bd_inset}};
    border-radius: 10px;
}
QLabel#DockTitle {
    background-color: transparent;
    color: {{fg_47}};
    font-weight: bold;
}
QGraphicsView {
    border: {{bd_regular}};
    border-radius: {{radius_md}};
    background-color: {{bg_71}};
}
QScrollArea {
    background-color: {{bg_root}};
    border: {{bd_57}};
    border-radius: {{radius_md}};
}

/* 主编辑区滚动页不再叠加自己的矩形边框，边框只由 tab 外壳负责。 */
QTabWidget[tabStyle="flat"] QScrollArea {
    background-color: transparent;
    border: none;
    border-radius: 0px;
}

/* 左侧角色表由外框负责圆角，表头保持透明以免覆盖四角。 */
QTableWidget#WarpcCharacterTable {
    border-radius: {{radius_md}};
}
QTableWidget#WarpcCharacterTable QHeaderView {
    background-color: transparent;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}
QTableWidget#WarpcCharacterTable QHeaderView::section,
QTableWidget#WarpcCharacterTable QTableCornerButton::section {
    background-color: transparent;
}
QSlider::groove:horizontal {
    background-color: {{bg_73}};
    border: {{bd_regular}};
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: {{bg_74}};
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: {{accent}};
}
QProgressBar {
    background-color: {{bg_62}};
    border: {{bd_inset}};
    border-radius: 6px;
    text-align: center;
    color: {{text_primary}};
}
QProgressBar::chunk {
    background-color: {{accent}};
    border-radius: 5px;
}

/* ── 状态栏与标签 ── */
QStatusBar {
    background-color: {{bg_root}};
    color: {{fg_49}};
    border-top: {{bd_36}};
    padding: 2px 8px;
}
QStatusBar::item {
    border: none;
}
/* 永久脏状态指示 (EditorMainWindow 状态栏右侧) */
QLabel#statusDirty {
    color: {{accent}};
    font-weight: bold;
    padding: 0 4px;
}
QLabel {
    color: {{fg_22}};
    background-color: transparent;
}
QLabel#StatusLabel {
    color: {{fg_51}};
    font-size: 12px;
    padding: 0 4px;
}
QLabel#StatusSep {
    color: {{fg_52}};
    font-size: 12px;
    padding: 0 2px;
}
QLabel#StatusInfo {
    color: {{fg_53}};
    font-size: 12px;
    padding: 0 4px;
}
QLabel#StatusPixel {
    color: {{fg_54}};
    font-size: 11px;
    padding: 0 4px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QLabel#hintLabel {
    color: {{fg_55}};
    font-size: 11px;
}
/* ── Inspector 标题 (kon/wardata/warpc) ── */
QLabel[class="InspectorTitle"] {
    font-weight: bold;
    color: {{fg_56}};
    border-bottom: {{bd_regular}};
    padding-bottom: 2px;
    margin-top: 8px;
}
QLabel[class="PropLabel"] {
    color: {{fg_57}};
}

/* ── 预览区面板 (kon/wardata/warpc) ── */
QFrame#PreviewFrame {
    background-color: {{bg_79}};
    border: {{bd_62}};
    border-top: {{bd_63}};
    border-radius: 10px;
    margin-top: 4px;
    margin-bottom: 8px;
}
QLabel[class="PreviewName"] {
    color: {{fg_58}};
    font-size: 18px;
    font-weight: bold;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
QLabel[class="PreviewMeta"] {
    color: {{fg_59}};
    font-size: 11px;
    border-bottom: {{bd_64}};
    padding-bottom: 8px;
    margin-bottom: 4px;
}
QLabel[class="PreviewDesc"] {
    color: {{text_success}};
    font-size: {{fs_body}};
    padding-top: 4px;
}
QLabel[class="PreviewSubMeta"] {
    color: {{fg_61}};
    font-size: 12px;
    font-weight: bold;
    padding-top: 4px;
}

/* ── FakeInputBox 内凹输入框 (kon/wardata/warpc) ── */
QFrame#FakeInputBox {
    background-color: {{bg_80}};
    border: {{bd_65}};
    border-radius: {{radius_md}};
}
QFrame#FakeInputBox:hover, QFrame#FakeInputBox:focus-within {
    background-color: {{bg_81}};
    border: {{bd_66}};
}
QFrame#FakeInputBox > QLineEdit {
    background: transparent;
    border: none;
    padding: 4px 8px;
    color: {{fg_62}};
    font-family: 'Consolas', 'Courier New', monospace;
    selection-background-color: {{accent}};
{{?fg_63}}
}
QFrame#FakeInputBox > QPushButton {
    background: transparent;
    border: none;
    border-left: {{bd_67}};
    border-right: {{bd_67}};
    border-radius: 0px;
    padding: 4px 8px;
    margin: 0px;
    color: {{fg_64}};
}
QFrame#FakeInputBox > QPushButton:hover {
    background-color: {{bg_82}};
    color: {{fg_65}};
}
QFrame#FakeInputBox > QPushButton:first:hover {
    border-top-left-radius: 7px;
    border-bottom-left-radius: 7px;
}
QFrame#FakeInputBox > QPushButton#FakeInputRightButton {
    border-right: none;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QFrame#FakeInputBox > QPushButton#FakeInputRightButton:hover {
    border-right: none;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QFrame#FakeInputBox > QPushButton#StatusPickerButton {
    border: none;
    border-radius: 7px;
}
QFrame#FakeInputBox > QPushButton#StatusPickerButton:hover {
    background-color: {{bg_83}};
    color: {{fg_66}};
}
QFrame#FakeInputBox > QComboBox {
    border: none;
    background: transparent;
    padding: 4px 8px;
    color: {{fg_62}};
}
QFrame#FakeInputBox > QComboBox::drop-down {
    border: none;
}
QFrame[class="FakeInputSep"] {
    background-color: {{bg_84}};
    border: none;
}

/* ── 额外预览文本 ── */
QLabel[class="ExtraPreviewText"] {
    padding: 4px 8px;
    color: {{text_success}};
    font-size: {{fs_body}};
}

/* ── 拆分字段内部标签 ── */
QLabel[class="SplitFieldLabel"] {
    color: {{fg_69}};
    font-size: 11px;
    padding: 0 2px;
}

/* ── 状态掩码标签颜色 (kon) ── */
QLabel[class="StatusInflict"] {
    color: {{fg_70}};
    font-size: 11px;
}
QLabel[class="StatusRemove"] {
    color: #3366cc;
    font-size: 11px;
}

/* ── 弹窗高亮主按钮 ── */
QPushButton#PrimaryButton {
    background-color: {{accent}};
    color: #ffffff;
    border: {{bd_69}};
    font-weight: bold;
}
QPushButton#PrimaryButton:hover {
    background-color: {{bg_86}};
}
QPushButton#PrimaryButton:pressed {
    background-color: {{bg_87}};
}

/* ── 工具栏 (tks_launcher_gui) ── */
QToolBar {
    background-color: {{bg_88}};
    border-bottom: {{bd_regular}};
    padding: 4px 2px;
    spacing: 6px;
}
QToolBar::separator {
    width: 1px;
    background-color: {{hairline}};
    margin: 5px 4px;
}

/* ── 控制台日志文本区 (tks_launcher_gui) ── */
/* 注意: 文字颜色由 log_console.py 通过 HTML 内联样式控制, 此处不设置 color */
QTextEdit#LogConsole {
    background-color: {{bg_90}};
    border: {{bd_regular}};
    border-radius: 4px;
    padding: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: {{accent}};
    selection-color: #ffffff;
}

/* ── QCheckBox 禁用状态 ── */
QCheckBox::indicator:disabled {
    background-color: {{bg_91}};
    border-color: {{bd_72}};
}
QCheckBox::indicator:checked:disabled {
    background-color: {{bg_92}};
    border-color: {{bg_92}};
    image: url(svg/checkmark.svg);
}
/* 必选补丁复选框：禁用态文字保持正常颜色 */
QCheckBox#requiredPatch:disabled {
    color: {{fg_22}};
}

/* ── 滚动条悬停 (tks_launcher_gui) ── */
QScrollBar::handle:vertical:hover {
    background-color: {{bg_93}};
}
QScrollBar::handle:horizontal:hover {
    background-color: {{bg_93}};
}

/* ── 状态栏标签 (tks_launcher_gui) ── */
QLabel#statusLabel {
    color: {{text_base}};
    font-weight: bold;
    padding: 4px 8px;
}
QLabel#statusLabelOk {
    color: {{fg_73}};
    font-weight: bold;
    padding: 4px 8px;
}
QLabel#statusLabelError {
    color: {{fg_74}};
    font-weight: bold;
    padding: 4px 8px;
}

/* ── DockHeader 内紧凑工具按钮 (tks_launcher_gui) ── */
QToolButton#dockToolButton {
    background-color: transparent;
    color: {{fg_75}};
    border: none;
    border-radius: 3px;
    padding: 0px 6px;
    max-height: 16px;
}
QToolButton#dockToolButton:hover {
    background-color: {{bg_16}};
{{?fg_76}}
}
QToolButton#dockToolButton:pressed {
    background-color: {{accent}};
    color: #fff;
}
QToolButton#dockToolButton:checked {
    background-color: {{accent}};
    color: #ffffff;
}
QToolButton#dockToolButton:checked:hover {
    background-color: {{bg_98}};
    color: #ffffff;
}

/* ── 启动按钮高亮 (tks_launcher_gui) ── */
QPushButton#btnStart {
    background-color: {{bg_99}};
    color: {{fg_77}};
    border: {{bd_74}};
    font-weight: bold;
}
QPushButton#btnStart:hover {
    background-color: {{bg_100}};
}
QPushButton#btnStart:pressed {
    background-color: {{bg_101}};
    color: #ffffff;
}
QPushButton#btnStart:disabled {
    background-color: {{bg_102}};
    color: {{fg_78}};
    border-color: {{bd_75}};
}

/* ── 记录标题标签 (item/skill/mat/warpc 编辑器) ── */
QLabel[class="RecordHeader"] {
    font-size: 14px;
    font-weight: bold;
    color: {{text_primary}};
    background-color: {{bg_62}};
    border: {{bd_inset}};
    border-radius: {{radius_md}};
    padding: 5px 10px;
}

/* ── 状态提示标签 (mat_editor) ── */
QLabel[class="StatusHint"] {
    color: {{fg_80}};
    font-size: 11px;
}

/* ── 紧凑按钮 (mat_editor 工具栏) ── */
QPushButton[class="CompactBtn"] {
    min-height: 16px;
    padding: 4px 8px;
    border-radius: 7px;
}

/* ── 打包/操作主按钮 (launcher dialogs) ── */
QPushButton#btnPack {
    font-weight: bold;
    padding: 6px 20px;
}

/* ── 图标选择器按钮 (item/warpc 编辑器) ── */
QPushButton[selected="true"] {
    background-color: {{bg_104}};
    border: {{bd_accent2}};
}
QPushButton[selected="false"] {
    background-color: transparent;
    border: 1px solid transparent;
}
QToolButton#IconPickerButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {{radius_md}};
    padding: 1px 2px 3px 2px;
    color: {{text_primary}};
}
QToolButton#IconPickerButton:hover {
    background-color: {{bg_11}};
    border-color: {{hairline}};
}
QToolButton#IconPickerButton[selected="true"] {
    background-color: {{accent_soft}};
    border: {{bd_accent2}};
    color: {{fg_82}};
}
QPushButton#PortraitTile {
    padding: 0px;
    min-width: 74px;
    min-height: 74px;
    border-radius: {{radius_md}};
}
QLabel#PortraitIndex {
    color: {{text_muted}};
    font-size: 11px;
    padding: 0px;
}

/* ── 活动槽位按钮 (save_editor) ── */
QPushButton[active="true"] {
    font-weight: bold;
    color: {{accent}};
}
QPushButton[active="false"] {
    font-weight: normal;
    color: {{fg_22}};
}

/* ── Chip 小标签 (item_editor) ── */
QLabel[class="ChipLabel"] {
    font-size: 10px;
}

/* ── 等宽文本区 (字段来源弹窗) ── */
QTextEdit[class="MonoText"] {
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}

/* ── 紧凑树控件 (mat_editor 场景/实体列表) ── */
QTreeWidget[class="CompactTree"] {
    font-size: 12px;
}
QTreeWidget[class="CompactTree"]::item {
    padding: 2px 4px;
    min-height: 22px;
}
QTreeWidget[class="CompactTree"] QHeaderView::section {
    padding: 4px 6px;
    font-weight: bold;
}

/* ── 成长率表格 (warpc_editor) ── */
QTableWidget[class="GrowthTable"]::item {
    background-color: {{bg_surface}};
}
QTableWidget[class="GrowthTable"]::item:alternate {
    background-color: {{bg_108}};
}
QTableWidget[class="GrowthTable"]::item:selected {
    background-color: {{accent}};
    color: #ffffff;
}

/* ── 表格编辑模式 (warpc_editor) ── */
QTableView[class="WarpcGrid"] {
    alternate-background-color: {{bg_108}};
    gridline-color: {{gridline_color_02}};
}
QTableView[class="WarpcGrid"]::item:selected {
    background-color: {{accent}};
    color: #ffffff;
}
QTableView[class="WarpcGrid"] QTableCornerButton::section {
    background-color: {{bg_10}};
    border: none;
}

/* ── 类型字段标签 (mat_editor 实体参数) ── */
QLabel[class="TypeFieldLabel"] {
    color: {{fg_86}};
}

/* ── 颜色色块 (mat/grp/wardata 色块通用) ── */
QFrame[class="ColorSwatch"], QLabel[class="ColorSwatch"] {
    background-color: #000000;
    border: {{bd_80}};
    border-radius: 6px;
}

/* ── 色块按钮 - 圆形 (tkt_editor 工具栏颜色快捷键) ── */
QPushButton[class="ColorSwatchRound"] {
    border: {{bd_81}};
    border-radius: 10px;
    padding: 0px;
}
QPushButton[class="ColorSwatchRound"]:hover {
    border: {{bd_accent2}};
}
QPushButton[class="ColorSwatchRound"]:focus {
    border: {{bd_accent2}};
}
QPushButton[class="ColorSwatchRound"]:pressed {
    border: {{bd_84}};
}

/* ── 色块按钮 - 方形 (tkt_editor 调色板弹窗) ── */
QPushButton[class="ColorSwatchBtn"] {
    border: {{bd_85}};
    border-radius: 6px;
    padding: 0px;
}
QPushButton[class="ColorSwatchBtn"]:hover {
    border: {{bd_accent2}};
}
QPushButton[class="ColorSwatchBtn"]:focus {
    border: {{bd_accent2}};
}
QPushButton[class="ColorSwatchBtn"]:pressed {
    border: {{bd_84}};
}

/* ── 存档编辑器的槽位与表格状态 ── */
QPushButton[class="SaveSlotButton"] {
    min-width: 32px;
    min-height: 18px;
    padding: 4px 8px;
    background-color: transparent;
    border-color: transparent;
    border-radius: {{radius_md}};
}
QPushButton[class="SaveSlotButton"]:hover {
    background-color: {{bg_112}};
    border-color: {{bd_89}};
}
QPushButton[class="SaveSlotButton"][active="true"] {
    background-color: {{accent_soft}};
    color: {{fg_82}};
    border-color: {{accent}};
    font-weight: bold;
}
QLabel[class="SaveStatusLabel"] {
    color: {{text_muted}};
    background-color: {{bg_62}};
    border: {{bd_inset}};
    border-radius: {{radius_md}};
    padding: 4px 10px;
}
/* ── 当前队伍成员卡片 (save_editor 总览) ── */
QWidget[class="TeamMemberCard"] {
    background-color: {{bg_38}};
    border: {{bd_inset}};
    border-radius: 10px;
}
QLabel[class="TeamMemberIndex"] {
    color: {{fg_89}};
    font-size: 11px;
}
QLabel[class="TeamMemberName"] {
    color: {{text_primary}};
    font-size: {{fs_body}};
    font-weight: 600;
    padding-top: 2px;
}
QLabel[class="TeamMemberLevel"] {
    color: {{fg_91}};
    font-size: 12px;
    padding-top: 2px;
}
QLabel[class="TeamMemberAvatar"] {
    background-color: {{bg_15}};
    border: {{bd_93}};
    border-radius: {{radius_md}};
}
QTableWidget#SaveInventoryTable,
QTableWidget#SaveWarpcTable {
    border-radius: 10px;
}
QTabWidget#SaveEditorTabs QTabBar::tab {
    padding-left: 15px;
    padding-right: 15px;
    font-weight: 600;
}
QTabWidget#SaveEventTabs QTabBar::tab {
    padding: 6px 10px;
    font-size: 12px;
}

/* ── 路径状态标签 (loaded/missing/unloaded) ── */
QLabel[status="loaded"] {
    color: {{text_success}};
}
QLabel[status="missing"] {
    color: {{fg_61}};
}
QLabel[status="unloaded"] {
    color: {{fg_94}};
}

/* ── 方向指示复选框 (mat_editor) ── */
QCheckBox[class="DirCheckBox"] {
    font-size: 11px;
}

/* ── 提示文本标签 (输入框下方, 无左距) ── */
QLabel[class="FieldHint"] {
    padding-left: 0px;
    font-size: 11px;
    color: {{text_success}};
}

/* ── 脏标记标签 (tkt_editor): 简体字警告, 色值取自原内嵌样式 #ff6b6b ── */
QLabel[class="DirtyIndicator"] {
    color: {{fg_96}};
    font-weight: bold;
}

/* ── 未保存标签 (tkt_editor): 还原 Tag 1.2 的实际渲染 (继承 DirtyIndicator 规则) ── */
QLabel[class="DirtyUnsaved"] {
    color: {{fg_97}};
    font-weight: bold;
}

/* ── 未知字段标签 (mat_editor “全部”页 d-index) ── */
QLabel[class="UnknownFieldLabel"] {
    color: {{fg_94}};
}

/* ── 探针标签 (act_editor 层/音效状态) ── */
QLabel[probe="ok"] {
    color: {{fg_99}};
}
QLabel[probe="warn"] {
    color: {{fg_100}};
}
QLabel[probe="error"] {
    color: {{fg_101}};
}
QLabel[probe="empty"] {
    color: {{fg_102}};
}

/* ── 信息标题标签 (mat_editor 脚本预览) ── */
QLabel[class="InfoTitle"] {
    font-size: {{fs_body}};
    font-weight: bold;
}

/* ── 缩放按钮 (tkt/spritesheet 编辑器) ── */
QPushButton[class="ZoomBtn"] {
    padding: 0px;
    font-size: 12px;
}

/* ── 缩放比例标签 ── */
QLabel[class="ZoomLabel"] {
    font-size: 11px;
    background-color: transparent;
}

/* ── 透明背景容器 (scroll content) ── */
QWidget#TransparentBg {
    background: transparent;
}

/* ── 主标题标签 (tkt_editor 蓝色强调) ── */
QLabel[class="PrimaryTitle"] {
    font-weight: bold;
    color: {{accent}};
}

/* ── 副标题标签 (tkt_editor 绿色强调) ── */
QLabel[class="SecondaryTitle"] {
    font-weight: bold;
    color: {{fg_99}};
    padding-top: 10px;
}

/* ── 确认操作按钮 (tkt_editor) ── */
QPushButton[class="ConfirmBtn"] {
    font-weight: bold;
    padding: 8px;
    margin-top: 10px;
    border-radius: {{radius_md}};
}

/* ── 分隔线框架 (QFrame separator) ── */
QFrame[class="SepLine"] {
    color: {{fg_105}};
    background-color: {{hairline}};
    border: none;
    max-height: 1px;
}
QFrame[class="VSepLine"] {
    color: {{hairline}};
    background-color: {{hairline}};
    border: none;
    min-width: 1px;
    max-width: 1px;
    min-height: 1px;
}

/* ── 游戏预览区 (tkt_editor 模拟游戏文本渲染背景) ── */
QScrollArea#GamePreview, QTextEdit#GamePreview {
    background-color: {{bg_119}};
    border: none;
    /* tkt_editor 2D 视口的游戏预览色，必须与渲染器固定色一致 */
}
QTextEdit#GamePreview {
    color: #ffffff;
}

/* ── configs_editor ── */

QFrame#Toolbar {
    max-height: 36px;
}

/* 召唤编辑对话框 — 目标选择器显示区 */
QWidget[class="TargetDisplay"] {
    border: {{bd_regular}};
    border-radius: 3px;
    background-color: {{bg_surface}};
}
QLabel[class="TargetIcon"], QLabel[class="TargetName"] {
    border: none;
    background: transparent;
    color: {{text_base}};
}
QLabel[class="TargetName"] {
    padding: 2px 0px;
}

/* 召唤表面板 — TKS目录未加载提示条 */
QFrame#SummonHintBar {
    background-color: {{bg_121}};
    border-radius: 4px;
}
QLabel#SummonHintLabel {
    color: {{fg_108}};
    background: transparent;
}

/* 掉落概率面板 — 常规槽标签 */
QLabel#RegularPctLabel {
    font-weight: bold;
    color: {{text_success}};
}

/* Config editor controls share the surrounding group-box surface. */
QGroupBox[configEditorSurface="true"] {
    background-color: transparent;
}
QGroupBox[configEditorSurface="true"] QSlider {
    background-color: transparent;
}
QGroupBox[configEditorSurface="true"] QSlider::groove:horizontal {
    background-color: transparent;
    border: {{bd_inset}};
}
QGroupBox[configEditorSurface="true"] QSlider::sub-page:horizontal {
    background-color: {{bg_122}};
    border-radius: 3px;
}
QGroupBox[configEditorSurface="true"] QSlider::handle:horizontal {
    background-color: {{fg_14}};
}
QGroupBox[configEditorSurface="true"] QSlider::handle:horizontal:hover {
    background-color: {{accent}};
}
QGroupBox[configEditorSurface="true"] QSpinBox,
QGroupBox[configEditorSurface="true"] QDoubleSpinBox,
QGroupBox[configEditorSurface="true"] QComboBox {
    background-color: transparent;
    border-color: {{hairline}};
}
QGroupBox[configEditorSurface="true"] QSpinBox:hover,
QGroupBox[configEditorSurface="true"] QDoubleSpinBox:hover,
QGroupBox[configEditorSurface="true"] QComboBox:hover {
    border-color: {{bd_hover}};
}
QGroupBox[configEditorSurface="true"] QSpinBox:focus,
QGroupBox[configEditorSurface="true"] QDoubleSpinBox:focus,
QGroupBox[configEditorSurface="true"] QComboBox:focus {
    border-color: {{accent}};
}
QGroupBox[configEditorSurface="true"] QCheckBox,
QGroupBox[configEditorSurface="true"] QRadioButton {
    background: transparent;
}
QGroupBox[configEditorSurface="true"] QCheckBox::indicator,
QGroupBox[configEditorSurface="true"] QRadioButton::indicator {
    background-color: transparent;
    border-color: {{bd_hover}};
}
QGroupBox[configEditorSurface="true"] QCheckBox::indicator:hover,
QGroupBox[configEditorSurface="true"] QRadioButton::indicator:hover {
    border-color: {{accent}};
}
QGroupBox[configEditorSurface="true"] QCheckBox::indicator:checked,
QGroupBox[configEditorSurface="true"] QRadioButton::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
}

/* 状态栏标签 — configs_editor */
QLabel#ConfigDirLabel[status="loaded"],
QLabel#StatusWarpcLabel[status="loaded"],
QLabel#StatusTktLabel[status="loaded"],
QLabel#StatusFaLabel[status="loaded"] {
    color: {{text_success}};
    font-weight: bold;
}
QLabel#ConfigDirLabel[status="missing"],
QLabel#StatusWarpcLabel[status="missing"],
QLabel#StatusTktLabel[status="missing"],
QLabel#StatusFaLabel[status="missing"] {
    color: {{fg_61}};
}
QLabel#ConfigDirLabel[status="unloaded"],
QLabel#StatusWarpcLabel[status="unloaded"],
QLabel#StatusTktLabel[status="unloaded"],
QLabel#StatusFaLabel[status="unloaded"] {
    color: {{fg_55}};
}
QLabel#StatusSkillLabel[status="loaded"] {
    color: {{text_success}};
    font-weight: bold;
}
QLabel#StatusSkillLabel[status="missing"] {
    color: {{fg_61}};
}
QLabel#StatusSkillLabel[status="unloaded"] {
    color: {{fg_55}};
}

/* WarPC 选择器 — 已选提示栏 */
QLabel#WarpcSelectedLabel {
    padding: 4px;
    border-radius: 4px;
    background: {{bg_126}};
}

/* ── 字形单元格 (font_editor) ── */
QLabel[class="GlyphCell"] {
    background-color: {{bg_surface}};
    border: {{bd_regular}};
}

/* ══ 功能补充规则 (bab68ba 提交后新增组件所需, 配色沿用本主题色板) ══ */

/* ── 启动状态警告标签 (tks_launcher_gui): 半成功/部分未应用 ── */
QLabel#statusLabelWarn {
    color: {{fg_116}};
    font-weight: bold;
    padding: 4px 8px;
}

/* ── 启动游戏分割按钮容器 (tks_launcher_gui): 透明背景避免圆角外侧出现锐角阴影 ── */
QWidget#startSplitButton {
    background-color: transparent;
    border: none;
    padding: 0px;
}

/* ── 兼容模式启动按钮 (tks_launcher_gui): 靛蓝区分标准模式主色 (现代族绿/经典族 Godot 蓝) ── */
QPushButton#btnStartCompat {
    background-color: {{bg_128}};
    color: {{fg_117}};
    border: {{bd_103}};
    font-weight: bold;
}
QPushButton#btnStartCompat:hover {
    background-color: {{bg_129}};
}
QPushButton#btnStartCompat:pressed {
    background-color: {{bg_130}};
    color: {{fg_118}};
}
/* 兼容模式禁用: 边框色与启用态完全一致 (与齿轮按钮边框色一体化), 仅背景与文字变浅表示禁用 */
QPushButton#btnStartCompat:disabled {
    background-color: {{bg_131}};
    color: {{fg_119}};
    border-color: {{bd_104}};
}

/* ── 启动游戏分割按钮: 主按钮圆左角, 齿轮按钮圆右角, 拼接处共享分隔线 ── */
QPushButton#btnStart,
QPushButton#btnStartCompat {
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
}
QPushButton#btnStartGear {
    background-color: {{bg_99}};
    color: {{fg_77}};
    border: {{bd_74}};
    border-left: none;
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    padding: 6px 9px;
}
QPushButton#btnStartGear:hover {
    background-color: {{bg_100}};
}
QPushButton#btnStartGear:pressed {
    background-color: {{bg_101}};
    color: #ffffff;
}
/* 齿轮按钮永远不允许禁用 — :disabled 样式与默认完全相同, 杜绝视觉差异 */
QPushButton#btnStartGear:disabled {
    background-color: {{bg_99}};
    color: {{fg_77}};
    border-color: {{bg_101}};
}
QPushButton#btnStartGearCompat {
    background-color: {{bg_128}};
    color: {{fg_117}};
    border: {{bd_103}};
    border-left: none;
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    padding: 6px 9px;
}
QPushButton#btnStartGearCompat:hover {
    background-color: {{bg_129}};
}
QPushButton#btnStartGearCompat:pressed {
    background-color: {{bg_130}};
    color: {{fg_118}};
}
/* 兼容模式齿轮按钮 — :disabled 与启用态完全相同, 始终保持可点击视觉 */
QPushButton#btnStartGearCompat:disabled {
    background-color: {{bg_128}};
    color: {{fg_117}};
    border-color: {{bd_104}};
}

/* ── 兼容模式蒙板 (补丁列表): 圆角与 DockHeader/DockBody 一致 ── */
QWidget#compatOverlay {
    background-color: rgba(0, 0, 0, 0.45);
    border-radius: 10px;
}
QLabel#compatOverlayLabel {
    background: transparent;
    color: {{fg_118}};
    font-size: 14px;
    font-weight: bold;
}

/* ── 启动状态面板当前模式值着色 (tks_launcher_gui) ── */
QLabel#modeValueStd {
    color: {{fg_126}};
    font-weight: bold;
}
QLabel#modeValueCompat {
    color: {{fg_127}};
    font-weight: bold;
}

/* ── 表头全选复选框 (launcher 列表) ── */
QCheckBox#headerCheck {
    background: transparent;
}

/* ── 详情区 / 对话框 / 预览占位 (launcher) ── */
QTextBrowser#detailBox {
    background-color: transparent;
    border: none;
    color: {{text_primary}};
}
QDialog {
    background-color: {{bg_140}};
}
QLabel#previewThumb {
    border: {{bd_109}};
    border-radius: 6px;
    background-color: {{bg_62}};
    color: {{fg_129}};
}
QLabel#avatarPreview {
    border: {{bd_110}};
    background-color: {{bg_38}};
}

/* ── 播放状态标签 (custom_music_dialog) ── */
QLabel#nowPlaying {
    color: {{fg_89}};
}
QLabel#nowPlaying[state="playing"] {
    color: {{accent}};
}

/* ── 学习模式提示 / 技能溢出警告 (warpc_editor) ── */
QLabel#learnModeHint {
    color: {{accent}};
    font-size: 11px;
    padding: 2px 0 4px 0;
}
QLabel#overflowBanner {
    color: {{fg_118}};
    background-color: #c0392b;
    font-weight: bold;
    padding: 6px;
    border-radius: 4px;
}

/* ── 定位闪烁高亮 (warpc_editor 字段定位) ── */
QLabel[class="FlashHint"] {
    background-color: #e8a040;
    color: {{fg_134}};
    border-radius: 3px;
    padding: 1px 3px;
}

/* ── 状态 chips (tks_book) ── */
QWidget[class="Chip"] {
    background-color: {{bg_30}};
    border: {{bd_111}};
    border-radius: 6px;
}

/* ── MOD 分类 Tag 标签 (mod_list 分类列, 按类型着色) ── */
QLabel[class="TagVisual"] {
    color: {{fg_135}};
    background: {{bg_144}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagAvatar"] {
    color: {{fg_136}};
    background: {{bg_145}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagMusic"] {
    color: {{fg_137}};
    background: {{bg_146}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagStory"] {
    color: {{fg_138}};
    background: {{bg_147}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagGameplay"] {
    color: {{fg_139}};
    background: {{bg_148}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagSave"] {
    color: {{fg_140}};
    background: {{bg_149}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagExe"] {
    color: {{fg_141}};
    background: {{bg_150}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagConfig"] {
    color: {{fg_142}};
    background: {{bg_151}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagMixed"] {
    color: {{fg_143}};
    background: {{bg_152}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagOther"] {
    color: {{fg_144}};
    background: {{bg_153}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagFont"] {
    color: {{fg_145}};
    background: {{bg_154}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagInterface"] {
    color: {{fg_146}};
    background: {{bg_155}};
    border-radius: 3px;
    padding: 1px 6px;
}
QLabel[class="TagMap"] {
    color: {{fg_147}};
    background: {{bg_156}};
    border-radius: 3px;
    padding: 1px 6px;
}

/* ── tks_book 语义值标签 ── */
QLabel[class="BookInfo"], QLabel[class="BookOk"], QLabel[class="BookBad"],
QLabel[class="BookSpecial"], QLabel[class="BookGold"], QLabel[class="BookMeta"],
QLabel[class="BookMuted"] {
    padding: 0px;
}
QLabel[class="BookInfo"] {
    color: {{fg_148}};
}
QLabel[class="BookOk"] {
    color: {{fg_91}};
}
QLabel[class="BookBad"] {
    color: {{fg_150}};
}
QLabel[class="BookSpecial"] {
    color: {{fg_151}};
}
QLabel[class="BookGold"] {
    color: {{fg_152}};
}
QLabel[class="BookMeta"] {
    color: {{fg_153}};
}
QLabel[class="BookMuted"] {
    color: {{fg_89}};
}

/* ══ TKS Launcher 视觉优化 ══ */
QMainWindow#LauncherWindow,
QWidget#LauncherRoot {
    background-color: {{bg_window}};
}
QToolBar#LauncherToolbar {
    background-color: {{bg_158}};
    border-bottom: {{bd_112}};
    padding: 8px 12px;
    spacing: 8px;
    min-height: 42px;
}
QToolBar#LauncherToolbar::separator {
    width: 1px;
    background-color: {{hairline}};
    margin: 7px 3px;
}
QToolBar#LauncherToolbar QPushButton#toolbarSecondary {
    background-color: {{bg_38}};
    color: {{fg_18}};
    border: {{bd_inset}};
    border-radius: {{radius_md}};
    padding: 7px 12px;
}
QToolBar#LauncherToolbar QPushButton#toolbarSecondary:hover {
    background-color: {{bg_hover}};
    color: {{text_primary}};
    border-color: {{bd_hover}};
}
QToolBar#LauncherToolbar QPushButton#toolbarSecondary:pressed {
    background-color: {{bg_162}};
    border-color: {{accent}};
}
QWidget#LauncherModeBar {
    background-color: transparent;
    border: none;
    padding: 0px;
}
QSplitter#LauncherSplitter {
    background-color: {{bg_window}};
}
QSplitter#LauncherSplitter::handle:horizontal,
QSplitter#LauncherRightSplitter::handle:vertical {
    background-color: {{bg_window}};
    border: none;
    margin: 0;
}
/* ── Dock 卡片化 (ChatGPT 风格): 标题栏只圆上角, 主体圆下角, 边框连成完整圆角卡片 ──
   (修复模组信息/画面兼容工具面板左下右直角边框、启动状态面板底部直角) */
QWidget#LauncherPatchPanel QFrame#DockHeader,
QWidget#LauncherModPanel QFrame#DockHeader,
QWidget#LauncherPreviewPanel QFrame#DockHeader,
QWidget#LauncherStatusPanel QFrame#DockHeader,
QWidget#LauncherToolsPanel QFrame#DockHeader {
    background-color: {{bg_165}};
    border: {{bd_116}};
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QWidget#LauncherPatchPanel QWidget#DockBody,
QWidget#LauncherModPanel QWidget#DockBody,
QWidget#LauncherPreviewPanel QWidget#DockBody,
QWidget#LauncherStatusPanel QWidget#DockBody,
QWidget#LauncherToolsPanel QWidget#DockBody {
    background-color: {{bg_15}};
    border: {{bd_116}};
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
/* 列表面板内容容器透明以露出 DockBody 表面 (表格由 body_margins 内收避开圆角) */
QWidget#LauncherPatchPanel QWidget#TransparentBg,
QWidget#LauncherModPanel QWidget#TransparentBg {
    background-color: transparent;
}
QWidget#LauncherPatchPanel QToolButton#dockToolButton,
QWidget#LauncherModPanel QToolButton#dockToolButton {
    max-height: 24px;
    padding: 4px 8px;
    border-radius: 6px;
}
QTableWidget#LauncherPatchTable,
QTableWidget#LauncherModTable {
    background-color: {{bg_167}};
    border: {{bd_116}};
    border-radius: {{radius_md}};
    gridline-color: {{gridline_color_03}};
    alternate-background-color: {{bg_167}};
}
/* 行/列分隔线统一由 gridline-color 绘制 (1px), ::item 不再加 border-bottom 避免双线叠加 */
QTableWidget#LauncherPatchTable::item,
QTableWidget#LauncherModTable::item {
    background-color: transparent;
    padding: 4px 8px;
}
QTableWidget#LauncherPatchTable::item:selected,
QTableWidget#LauncherModTable::item:selected {
    background-color: {{accent_soft}};
    color: {{text_primary}};
}
/* 表头顶部圆角: 表头组件自身圆角背景, section 透明以避免直角盖住卡片圆角 */
QTableWidget#LauncherPatchTable QHeaderView,
QTableWidget#LauncherModTable QHeaderView {
    background-color: {{bg_167}};
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}
QTableWidget#LauncherPatchTable QHeaderView::section,
QTableWidget#LauncherModTable QHeaderView::section {
    background-color: transparent;
    border-bottom: {{bd_inset}};
    padding: 8px;
    color: {{text_muted}};
}
QTextBrowser#detailBox {
    background-color: {{bg_140}};
    border: {{bd_116}};
    border-radius: 10px;
    color: {{text_primary}};
    padding: 12px 14px;
}
/* 模组信息面板: 详情文档以圆角内嵌组件形式适配 DockBody 圆角 */
QWidget#LauncherPreviewPanel QTextBrowser#detailBox {
    background-color: transparent;
    border: {{bd_116}};
    border-radius: {{radius_md}};
    padding: 8px 10px;
}
/* 内容容器透明, 露出 DockBody 圆角表面 (不透明背景会盖住底部圆角) */
QWidget#LauncherSummaryContent,
QWidget#LauncherToolsContent {
    background-color: transparent;
}
QLabel[class="SummaryValue"] {
    color: {{text_primary}};
    font-weight: 600;
}
QLabel#modeValueStd,
QLabel#modeValueCompat {
    border-radius: 6px;
    padding: 2px 8px;
    font-weight: bold;
}
QLabel#modeValueStd {
    color: {{fg_161}};
    background-color: {{bg_171}};
}
QLabel#modeValueCompat {
    color: {{fg_127}};
    background-color: {{bg_172}};
}
/* 启动状态值去除内边距, 与上方各行值左对齐 */
QWidget#LauncherSummaryContent QLabel#statusLabel,
QWidget#LauncherSummaryContent QLabel#statusLabelOk,
QWidget#LauncherSummaryContent QLabel#statusLabelWarn,
QWidget#LauncherSummaryContent QLabel#statusLabelError {
    padding: 0px;
}
/* 启动状态行内按钮 (启动状态值右侧, 靠右对齐) */
QPushButton#showLogInlineButton {
    background-color: transparent;
    color: {{fg_161}};
    border: none;
    border-radius: 6px;
    padding: 3px 8px;
}
QPushButton#showLogInlineButton:hover {
    background-color: {{bg_112}};
    color: {{text_primary}};
}
QPushButton#showLogInlineButton:pressed {
    background-color: {{bg_162}};
}
QWidget#LauncherToolsContent QRadioButton {
    background-color: {{bg_38}};
    border: {{bd_inset}};
    border-radius: 7px;
    padding: 5px 9px;
}
QWidget#LauncherToolsContent QRadioButton:hover {
    border-color: {{bd_hover}};
    background-color: {{bg_hover}};
}
QWidget#LauncherToolsContent QRadioButton:checked {
    color: {{fg_161}};
    border-color: {{accent}};
    background-color: {{bg_171}};
}
QStatusBar#LauncherStatusBar {
    background-color: {{bg_158}};
    border-top: {{bd_112}};
    padding: 3px 10px;
}
QLabel#enabledModSummary,
QLabel#gameDirSummary {
    color: {{fg_166}};
    padding: 4px 10px;
}
