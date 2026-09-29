"""
通用 UI 工具函数 — 供所有编辑器统一使用
包含: 路径状态显示、FakeInputBox、窗口图标加载等
"""
import os
import sys
from PySide6.QtCore import QObject, QEvent, Qt, QTimer, QPoint, QRect, QSize
from PySide6.QtGui import QIcon, QFont, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QMessageBox,
                               QPushButton, QTextEdit, QVBoxLayout, QWidget, QSpinBox)
from editor_utils.combo_box import EditorComboBox


# ── 颜色常量 (与 editor_themes 一致) ──
# 状态色 (已加载/缺失) — 值源于 theme_tokens.STATUS (P3-6 收编, 单一事实来源)
from editor_utils import theme_tokens as _theme_tokens

_COLOR_STATUS = _theme_tokens.STATUS
COLOR_LOADED_DARK = _COLOR_STATUS["loaded"][0]
COLOR_LOADED_LIGHT = _COLOR_STATUS["loaded"][1]
COLOR_MISSING_DARK = _COLOR_STATUS["missing"][0]
COLOR_MISSING_LIGHT = _COLOR_STATUS["missing"][1]


# 兼容旧导入；新代码统一从 editor_utils.ui_helpers 导入 EditorComboBox，
# 外部脚本仍可继续使用 NoWheelComboBox，不会产生两套下拉框实现。
NoWheelComboBox = EditorComboBox


class NoWheelSpinBox(QSpinBox):
    """禁用鼠标滚轮改值的数字输入框 (同 NoWheelComboBox 的动机)。

    在 QScrollArea 中滚轮悬停会误触改值, 重写 wheelEvent 令其向上冒泡滚动页面。
    """

    def wheelEvent(self, event):
        event.ignore()


class FlowLayout(QLayout):
    """自适应换行的流式布局 (Qt 官方 FlowLayout 示例的 PySide6 移植)。

    子项从左到右排列, 剩余宽度不足以容纳下一项时整项折到下一行 —
    适合工具条控件: 窄窗口自然折多行, 窗口拉宽/最大化时自动减少
    换行去利用空白。想保证"标签和它的控件不被折散"时, 先把它们
    包进一个 QWidget (内部 QHBoxLayout) 再加入本布局, 折行便只
    发生在逻辑组之间。

    可选"右侧固定项" (set_right_pinned): 不参与流式换行, 始终贴在
    控制区右缘 (有两行以上时贴第 2 行, 只有一行时贴该行右缘);
    其所在行装箱时会为它预留右侧宽度。

    布局声明 hasHeightForWidth, 外层 QVBoxLayout 会按可用宽度
    自动调整本布局的高度 (折行数变化时行数随之增减)。
    """

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self.setSpacing(spacing)
        self._items = []
        self._pin = None

    def __del__(self):
        while self._items:
            self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def set_right_pinned(self, widget):
        """设置右侧固定项 (传 None 清除)。该项的父窗口须与本布局相同。"""
        self._pin = widget
        self.update()
        self.invalidate()

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        if self._pin is not None:
            size = size.expandedTo(self._pin.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _pin_size(self):
        return self._pin.sizeHint() if self._pin is not None else QSize()

    def _pack_lines(self, width, reduced_line):
        """按可用宽度贪心装箱, 返回 [(items, line_w, line_h), ...]。

        reduced_line 行的可用宽度扣除右侧固定项占位 (负数表示不扣)。
        """
        pin_w = 0
        if self._pin is not None and reduced_line >= 0:
            pin_w = self._pin_size().width() + self.spacing()
        lines = []
        cur, cur_w, cur_h = [], 0, 0
        for item in self._items:
            hint = item.sizeHint()
            avail = width - (pin_w if len(lines) == reduced_line else 0)
            add = hint.width() + (self.spacing() if cur else 0)
            if cur and cur_w + add > avail:
                lines.append((cur, cur_w, cur_h))
                cur, cur_w, cur_h = [], 0, 0
                add = hint.width()
            cur.append(item)
            cur_w += add
            cur_h = max(cur_h, hint.height())
        if cur:
            lines.append((cur, cur_w, cur_h))
        return lines

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        spacing = self.spacing()
        pin = self._pin
        pin_hint = self._pin_size()

        # 先按整宽装箱定行数, 再令固定项所在行 (默认第 2 行) 预留右缘;
        # 固定项让该行变挤可能多折一行, 但行号仍有效, 只需钳到末行。
        lines = self._pack_lines(area.width(), -1)
        pin_line = -1
        if pin is not None:
            pin_line = min(1, len(lines) - 1)
            lines = self._pack_lines(area.width(), pin_line)
            pin_line = min(pin_line, len(lines) - 1)

        y = area.y()
        for li, (items, _lw, lh) in enumerate(lines):
            x = area.x()
            for item in items:
                hint = item.sizeHint()
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
            if li == pin_line:
                px = area.right() + 1 - pin_hint.width()
                py = y + max(0, (lh - pin_hint.height()) // 2)
                if not test_only:
                    pin.setGeometry(QRect(QPoint(px, py), pin_hint))
                lh = max(lh, pin_hint.height())
            y += lh + spacing
        if lines:
            y -= spacing
        return y - rect.y() + margins.bottom()


def update_path_labels(labels_config, is_dark):
    """
    批量更新路径标签的加载状态与颜色 (仅显示状态, 完整路径见鼠标悬浮提示)
    labels_config: [(QLabel, path_or_None, display_name), ...]
    """
    for label, path, name in labels_config:
        if path and os.path.exists(path):
            label.setText(f"{name}: 已加载")
            label.setProperty("status", "loaded")
            label.setToolTip(os.path.normpath(path))
        elif path:
            label.setText(f"{name}: 文件缺失")
            label.setProperty("status", "missing")
            label.setToolTip(os.path.normpath(path))
        else:
            label.setText(f"{name}: 未加载")
            label.setProperty("status", "missing")
            label.setToolTip("")
        label.style().unpolish(label)
        label.style().polish(label)


def mark_invalid(line_edit, invalid: bool) -> None:
    """数值输入校验反馈: 置/清 QLineEdit 的 invalid 动态属性。

    QSS 侧经 ``QLineEdit[invalid="true"]`` 渲染警示红边框
    (槽位 bd_error, theme_tokens), 供表单应用时对非法/越界值即时提示。
    """
    line_edit.setProperty("invalid", bool(invalid))
    line_edit.style().unpolish(line_edit)
    line_edit.style().polish(line_edit)


def make_fake_input(widget=None, line_edit=None, combo=None,
                    button=None, stretch=True, height=32):
    """创建 FakeInputBox 外壳 (内凹输入框风格)
    用法1: make_fake_input(some_widget) — 单控件
    用法2: make_fake_input(line_edit=le, combo=cb, button=btn) — 多控件组合
    """
    box = QFrame()
    box.setObjectName("FakeInputBox")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)
    if widget is not None:
        h.addWidget(widget)
    else:
        if line_edit:
            h.addWidget(line_edit)
        if combo:
            h.addWidget(combo, 1)
        if button:
            h.addWidget(button)
        if stretch:
            h.addStretch()
    box.setFixedHeight(height)
    return box


def load_window_icon(widget, editor_dir=None):
    """加载 TKS.ico 窗口图标"""
    if editor_dir is None:
        editor_dir = os.path.dirname(
            widget.__class__.__module__.replace('.', os.sep))
        if not os.path.isdir(editor_dir):
            editor_dir = os.getcwd()
    ico_path = os.path.join(editor_dir, 'TKS.ico')
    if os.path.exists(ico_path):
        widget.setWindowIcon(QIcon(ico_path))



def confirm_close(parent, dirty, title="未保存", text="有未保存的修改, 确定退出?"):
    """未保存确认退出对话框，返回 True 表示可以关闭。

    按钮 Yes/No 且默认 No: 回车/关闭键不会意外放弃修改。
    """
    if not dirty:
        return True
    return themed_question(parent, title, text) == QMessageBox.Yes


def clamp_dialog_size(dialog, width: int, height: int, *, margin: int = 48) -> None:
    """把对话框默认尺寸钳制到所在屏幕可用区域内 (逻辑像素, 含缩放折算)。

    只约束"期望值": 布局最小尺寸必须由对话框自己控制在屏幕预算内
    (Qt 会按 minimumSizeHint 撑大窗口, 钳制无法压到最小值以下)。
    """
    screen = dialog.screen()
    avail = screen.availableGeometry() if screen is not None else None
    if avail is not None and avail.isValid():
        width = min(width, max(320, avail.width() - margin))
        height = min(height, max(240, avail.height() - margin))
    dialog.resize(width, height)


def set_themed_icon(button, name: str) -> None:
    """给按钮显式指定主题感知 SVG 图标 (P4-1 图标库)。

    图标名对应 editor_themes/svg/<name>[-light].svg; 动态属性 themedIcon
    使主题切换 (apply_theme_to_window) 时自动更换深浅变体, 文本保持不变。
    """
    from editor_utils import theme_manager, theme_switcher
    button.setProperty("themedIcon", name)
    button.setIcon(
        theme_manager.themed_icon(name, theme_switcher.current_window_theme(
            button.window())))


def themed_question(parent, title, text,
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    default=QMessageBox.StandardButton.No):
    """确认弹窗 (统一入口): 默认 Yes/No、默认按钮 No (防误回车)。

    标题栏主题由全局过滤器 (install_dialog_theme_filter) 自动处理。
    返回用户点击的标准按钮 (QMessageBox.Yes / No / Cancel / Ok)。
    """
    msg = QMessageBox(QMessageBox.Icon.Question, title, text, buttons, parent)
    if default is not None:
        msg.setDefaultButton(default)
    return msg.exec()


def form_edits_pending(widget_map, record, keys, combo_keys=()):
    """检测表单控件当前值是否与记录不一致 (切换记录前提示用, P3-5)。

    widget_map: 字段名 -> QLineEdit/EditorComboBox; keys: 参与比对的字段名;
    combo_keys: 使用 currentText() 且形如 "N-标签" 的下拉字段。
    比较口径与各编辑器 _apply_edit 一致 (int 数值); 控件缺失或内容不可
    解析的字段跳过 (宁漏报不误报)。
    """
    for fn in keys:
        widget = widget_map.get(fn)
        if widget is None:
            continue
        try:
            if fn in combo_keys:
                value = int(widget.currentText().split('-', 1)[0])
            else:
                value = int(widget.text() or 0)
        except (ValueError, AttributeError, TypeError):
            continue
        if value != int(record.get(fn, 0) or 0):
            return True
    return False


def themed_messagebox(parent, icon, title, text):
    """信息弹窗 (标题栏主题由全局过滤器自动处理)。"""
    msg = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    return msg.exec()


def show_field_ref(parent, text, size=(700, 580)):
    """只读文本参考弹窗 (字段映射/说明类) — 阶段 4 合并 kon/warpc 两份 FieldRefDialog。

    内容由调用方构建; 等宽 Consolas 9 字体呈现字段表。
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle("字段参考")
    dlg.resize(*size)
    layout = QVBoxLayout(dlg)
    viewer = QTextEdit()
    viewer.setReadOnly(True)
    viewer.setFont(QFont("Consolas", 9))
    viewer.setPlainText(text)
    layout.addWidget(viewer)
    bl = QHBoxLayout()
    bl.addStretch()
    bl.addWidget(QPushButton("关闭", clicked=dlg.close))
    layout.addLayout(bl)
    dlg.exec()


TOOLTIP_WRAP_PX = 480        # 工具提示的目标阅读宽度 (像素)


def wrap_tooltip_text(text: str, max_px: int = TOOLTIP_WRAP_PX) -> str:
    """把长文本按像素宽度预换行, 供工具提示 (setToolTip) 使用。

    为什么要手动换行: Qt 的 tooltip 只在文本宽度超过"屏幕宽度的一定比例"
    时才软换行 (实测 800px 屏上阈值约 496px)。屏幕越宽阈值越大, 于是
    100~200 字的说明在 2K 屏上会拉成一条横贯屏幕的宽条 —— 而更长的文本
    反而会换行, 同一列表里两款补丁的提示表现不一致。这里按固定像素宽度
    主动插入 '\\n', 让所有提示框保持一致的阅读宽度。

    Args:
        text:   原始文本 (可含 '\\n' 分段, 分段会被保留)
        max_px: 每行最大像素宽度, 默认 480 (与 Qt 在小屏上的自适应宽度相近)

    Returns:
        已插入换行的文本; 未知字体/无 QApplication 时退化为原文本。
    """
    if not text:
        return text
    try:
        from PySide6.QtGui import QFontMetrics
        app = QApplication.instance()
        fm = QFontMetrics(app.font() if app is not None else QFont())
    except Exception:
        return text

    lines = []
    for para in text.split("\n"):
        line, width = "", 0
        for ch in para:
            cw = fm.horizontalAdvance(ch)
            if line and width + cw > max_px:
                # 断行点若落在 ASCII 单词中间, 回退到最近的空格/标点后
                cut = line.rfind(" ")
                if cut > 0 and len(line) - cut <= 12:
                    # 空格保留在行尾 (渲染时不可见): 保证"只插入换行, 不改动内容"
                    lines.append(line[:cut + 1])
                    line = line[cut + 1:]
                    width = fm.horizontalAdvance(line)
                else:
                    lines.append(line)
                    line, width = "", 0
            line += ch
            width += cw
        lines.append(line)
    return "\n".join(lines)


def _round_popup_win11_corners(popup) -> None:
    """给无边框弹出层窗口设置 Win11 DWM 系统圆角 (菜单/工具提示/下拉弹层)。

    QSS 的 border-radius 只作用于边框/背景的绘制裁剪, 这类弹出窗口本身
    仍是矩形, 视觉上角部是直角并与 QSS 圆角错位。DWMWA_WINDOW_CORNER_
    PREFERENCE(=33) + DWMWCP_ROUND(=2) 让系统对弹出窗口做抗锯齿圆角裁剪,
    且保留 DWM 原生投影; Win10 无此属性, 调用失败静默保持现状 (直角,
    与历史行为一致)。
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        pref = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(popup.winId()), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass  # 非 win32 / winId 不可用 / 旧系统不支持该属性, 静默跳过


def _shape_tooltip_window(tip) -> None:
    """把工具提示窗口整成"无遮罩 + 系统圆角" (与 QMenu 同形态)。

    为什么必须清遮罩: Qt 会给 tooltip 设置 ``SH_ToolTip_Mask`` 窗口遮罩,
    实测只裁掉 1px 角; 而主题 QSS 画的是 radius_md=8px 圆角 —— 8px 描边被
    1px 遮罩切断, 圆角之外那圈方形填充色就会露出来 (用户看到的"矩形背景")。
    又因为**窗口 region 的优先级高于 DWM 圆角** (实测 region 存在时,
    DWM 角偏好即使设成 ROUND 也不生效), 所以只设 DWM 不够, 必须先清遮罩,
    让形状交给 DWM 系统圆角 —— 即与 QMenu (无 region + DWM ROUND) 完全同形态。
    """
    try:
        tip.clearMask()
    except Exception:
        pass
    _round_popup_win11_corners(tip)


class _DialogThemeFilter(QObject):
    """全局事件过滤器: 自动为所有弹出的顶层窗口应用 DWM 标题栏主题。

    由 install_dialog_theme_filter(app) 安装到 QApplication 上,
    捕获所有 QWidget 的 Show 事件, 对顶层窗口 (QDialog/QMessageBox/
    QInputDialog/QFileDialog/QColorDialog) 调用 apply_titlebar_theme,
    使其标题栏跟随编辑器当前主题 (4 主题), 无需在每个弹窗处手动调用。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app

    def _resolve_theme(self, widget):
        """解析弹窗应跟随的主题: 窗口链 → 顶层窗口 → 持久化存档/系统默认。"""
        from editor_utils import theme_manager

        candidates = []
        p = widget.parentWidget() or widget.parent()
        while p is not None:
            candidates.append(p)
            p = getattr(p, 'parentWidget', lambda: None)() or getattr(p, 'parent', lambda: None)()
        candidates.extend(self._app.topLevelWidgets())

        for w in candidates:
            theme_id = getattr(w, '_theme_id', None)
            if theme_id is not None and str(theme_id) in theme_manager.THEMES:
                return str(theme_id)
        # 过渡回退: 仅带深浅布尔属性的旧式窗口
        for w in candidates:
            for attr in ('_is_dark', 'is_dark_theme', '_dark_mode'):
                v = getattr(w, attr, None)
                if v is not None:
                    return 'gpt-dark' if bool(v) else 'gpt-light'
        return theme_manager.load_initial_theme()

    def eventFilter(self, obj, event):
        if not (isinstance(obj, QWidget) and obj.isWindow()):
            return False
        _wtype = obj.windowFlags() & Qt.WindowType.WindowType_Mask

        # ── ① 工具提示: 清掉 Qt 自带的 1px 窗口遮罩, 让 DWM 圆角接管 ──
        # 实测数据: Qt 给 tooltip 设的 SH_ToolTip_Mask 只裁 1px 角, 而 QSS
        # 画的是 radius_md=8px 圆角 → 圆角描边被 1px 遮罩切断, 四角露出方形
        # 填充色; 且窗口 region 优先级高于 DWM 圆角 (region 在时 DWM=ROUND
        # 不生效)。清掉遮罩后 tooltip 与 QMenu 完全同形态 (无 region + DWM
        # ROUND), 而 QMenu 的圆角是既有验收过的形态。
        # Show 与 Resize 都要清 —— Qt 在这两个事件里都会重设遮罩; 且必须延迟
        # 一拍 (Qt 的处理在过滤器之后, 同步清会被它覆盖: 实测同步 clearMask
        # 后 processEvents 遮罩又回来了)。
        if _wtype == Qt.WindowType.ToolTip:
            if event.type() in (QEvent.Show, QEvent.Resize):
                QTimer.singleShot(0, lambda w=obj: _shape_tooltip_window(w))
            return False

        if event.type() != QEvent.Show:
            return False

        # ── ② 其余 Qt.Popup 弹层 (菜单/下拉弹层/补全弹层/自绘弹层) ──
        # QSS border-radius 只裁剪边框/背景绘制, 弹出窗口本身仍是矩形, 角部
        # 露出直角缺口; 按窗口类型统一识别 (而非逐组件白名单), 一律由 DWM
        # 设置系统圆角 — 此后新增弹层组件无需再单独接入。
        if _wtype == Qt.WindowType.Popup:
            _round_popup_win11_corners(obj)
            return False

        # ── ③ 非弹层顶层窗口 (QDialog/QMessageBox/...) 走原生标题栏主题 ──
        try:
            from editor_utils.window_theme import apply_titlebar_theme
            apply_titlebar_theme(obj, self._resolve_theme(obj))
        except Exception:
            pass  # 非 win32 或 winId 不可用, 静默跳过
        return False


def install_dialog_theme_filter(app):
    """安装全局事件过滤器, 自动为所有弹出的顶层窗口
    (QDialog/QMessageBox/QInputDialog/QFileDialog/QColorDialog) 应用 DWM 标题栏主题。

    一次安装, 永久生效, 无需在每次创建弹窗时手动调用。
    在每个编辑器的 main() 中 QApplication 创建后调用一次即可::

        app = QApplication(sys.argv)
        install_dialog_theme_filter(app)
    """
    app._dialog_theme_filter = _DialogThemeFilter(app)
    app.installEventFilter(app._dialog_theme_filter)

    # ── 首次启动免费声明确认 (防倒卖) ──
    # 全部 GUI 程序共用此挂载点: 仅编译环境首次启动弹窗,
    # 确认后永不再弹; 具体逻辑见 editor_utils/free_notice.py
    try:
        from editor_utils.free_notice import ensure_free_declaration
        ensure_free_declaration()
    except Exception:
        pass  # 声明功能异常不阻断启动 (SystemExit 不受此捕获影响)


def resolve_config_path(config_filename):
    """解析 configs/ 目录下配置文件的绝对路径。

    支持两种运行模式:
      1. 开发环境 (脚本直接运行): 从 ui_helpers.py 所在目录 (editor_utils/)
         向上一级 ()，再进入 configs/ 目录查找。
      2. 打包环境 (Nuitka/PyInstaller): 通过 runtime_bootstrap.get_app_dir()
         获取 exe 所在目录，在相邻的 configs/ 子目录中查找。

    Args:
        config_filename: 配置文件名 (如 'equip_type_labels.json')

    Returns:
        配置文件的绝对路径，找不到时返回 None。
    """
    # ── 方法 1: 基于 __file__ 推算 (开发环境) ──
    try:
        editor_utils_dir = os.path.dirname(os.path.abspath(__file__))
        ai_programs_dir = os.path.dirname(editor_utils_dir)  # 
        path = os.path.join(ai_programs_dir, 'configs', config_filename)
        if os.path.isfile(path):
            return path
    except (NameError, OSError):
        pass  # __file__ 在某些打包环境下不可用

    # ── 方法 2: exe 相邻 configs/ 目录 (打包环境) ──
    try:
        from editor_utils.runtime_bootstrap import get_app_dir
        exe_dir = get_app_dir()
        path = os.path.join(exe_dir, 'configs', config_filename)
        if os.path.isfile(path):
            return path
    except (ImportError, OSError):
        pass

    # ── 方法 3: 当前工作目录 ──
    cwd_path = os.path.join(os.getcwd(), 'configs', config_filename)
    if os.path.isfile(cwd_path):
        return cwd_path

    return None


def pil_to_pixmap(img, size=(32, 32)):
    """将 PIL.Image 缩放后转为 QPixmap。img 为 None 或转换失败时返回 None。

    合并自 picker_dialogs._pil_to_pixmap 与 summon_table_panel._pil_to_pixmap
    (None 检查与异常兜底取两者并集, 对既有调用路径行为一致)。
    """
    if img is None:
        return None
    try:
        img = img.resize(size, 1)  # Image.NEAREST = 1
        img = img.convert('RGBA')
        data = img.tobytes('raw', 'RGBA')
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


def backup_existing_file(path) -> None:
    """保存前把现有文件整块拷贝为 ``path + ".bak"`` (原文件不存在或
    拷贝失败均静默跳过, 不阻断保存流程)。

    供各编辑器写盘前调用 — 备份策略 (是否轮换/校验) 将来只需改这一处。
    """
    try:
        with open(path, 'rb') as src:
            with open(path + ".bak", 'wb') as dst:
                dst.write(src.read())
    except Exception:
        pass
