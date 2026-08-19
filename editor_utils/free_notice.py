"""
free_notice — 首次启动免费声明确认 (防倒卖提示)
=================================================
背景: 本软件为免费开源软件, 但存在被黑心商家倒卖的情况。
由于技术上无法阻止免费 exe 被复制转卖, 核心策略是消除信息差 ——
让每一位使用者在首次启动时明确知晓: 本软件永久免费, 付费获取即被骗。

机制:
  - 仅编译环境生效 (开发环境跳过, 不打扰开发)
  - 全机器/用户仅弹一次: 确认后写入 %LOCALAPPDATA%/TKSEditors/
    free_declaration.json 标记, 全部编辑器共享, 永不再弹
  - 用户必须逐字输入确认短语才能继续 —— 强制阅读, 印象深刻
  - 拒绝确认 (点"退出"或关闭窗口) 则退出程序:
    倒卖者无法简单教买家"跳过弹窗"绕过
  - 挂载点: ui_helpers.install_dialog_theme_filter() —— 全部 19 个
    GUI 程序的共同启动路径, 无需逐个编辑器改动

文案修改: 直接编辑下方 _DECLARATION_HTML / _CONFIRM_PHRASE 即可。
若修改了声明内容想让用户重新确认, 递增 _DECLARATION_VERSION。
"""
import json
import os
import sys

# 声明版本号 — 修改声明文案后递增, 可让已确认用户重新确认
_DECLARATION_VERSION = 1

# 用户必须逐字输入的确认短语 (强调"免费获取"本身,
# 付费买家输入时会产生强烈认知冲突, 警示效果最强)
_CONFIRM_PHRASE = "免费获取"

# 声明正文 (富文本, 玩家视角的温和口吻: 主打为爱发电/开源免费,
# 对付费场景只提醒不抨击)
_DECLARATION_HTML = (
    "<h3 style='margin-top:0;'>【致玩家】</h3>"
    "<p>亲爱的玩家：</p>"
    "<p>TKS 编辑器系列是一款<b>开源免费软件</b>——下载、使用、更新，"
    "永远不收取任何费用。这是作者用爱发电的作品，本意是希望更多玩家"
    "能参与到 MOD 创作中来，一起让 TKS 的世界变得更有趣。</p>"
    "<p>如果你意外地为它付过钱，那你可能遇到了有偿转发。"
    "建议向卖家申请退款，并向平台反馈——本软件不应被出售。</p>"
    "<p>作者：端木子青<br>"
    "欢迎免费分享给你的朋友，也请勿将其用于商业用途。</p>"
    "<p>请在下方逐字输入，确认你是免费获取的：</p>"
)

# 标记文件 — 与运行时缓存同目录 (%LOCALAPPDATA%/TKSEditors/), 全编辑器共享
_FLAG_FILENAME = "free_declaration.json"


def _flag_path() -> str:
    """标记文件绝对路径 (%LOCALAPPDATA%/TKSEditors/free_declaration.json)"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "TKSEditors", _FLAG_FILENAME)


def _is_confirmed() -> bool:
    """读取标记: 当前版本声明已确认返回 True (文件损坏视为未确认)"""
    try:
        with open(_flag_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return int(data.get("version", 0)) >= _DECLARATION_VERSION
    except (OSError, ValueError, TypeError):
        return False


def _mark_confirmed():
    """写入确认标记 (失败时静默 — 下次启动会再次提示, 不影响使用)"""
    try:
        path = _flag_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from datetime import datetime
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "version": _DECLARATION_VERSION,
                "confirmed_at": datetime.now().isoformat(timespec="seconds"),
            }, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def ensure_free_declaration():
    """首次启动免费声明确认 (未确认则弹窗; 拒绝确认则退出程序)。

    应在 QApplication 创建、对话框主题过滤器安装之后调用
    (由 ui_helpers.install_dialog_theme_filter 统一挂载, 无需手动调用)。
    """
    # 开发环境跳过 (不打扰开发调试)
    from editor_utils.app_init import is_compiled
    if not is_compiled():
        return

    if _is_confirmed():
        return

    # ── 弹出声明对话框 ──
    # ESC/X 关闭默认触发 reject() → 走下方拒绝流程 (提示后退出程序),
    # 倒卖者无法教买家"直接关掉弹窗"绕过
    from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                                   QPushButton, QVBoxLayout)

    dlg = QDialog()
    dlg.setWindowTitle("致玩家 — 免费声明")
    dlg.setModal(True)
    dlg.setMinimumWidth(520)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)

    body = QLabel(_DECLARATION_HTML)
    body.setTextFormat(_rt())
    body.setWordWrap(True)
    layout.addWidget(body)

    edit = QLineEdit()
    edit.setPlaceholderText(f"请输入：{_CONFIRM_PHRASE}")
    layout.addWidget(edit)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    btn_ok = QPushButton("确认并继续")
    btn_ok.setEnabled(False)
    btn_quit = QPushButton("退出程序")
    btn_row.addWidget(btn_ok)
    btn_row.addWidget(btn_quit)
    layout.addLayout(btn_row)

    hint = QLabel("提示：逐字输入上方要求的口号后，“确认并继续”才会点亮。")
    hint.setObjectName("hintLabel")
    layout.addWidget(hint)

    def _on_text_changed(text: str):
        btn_ok.setEnabled(text.strip() == _CONFIRM_PHRASE)

    edit.textChanged.connect(_on_text_changed)
    btn_ok.clicked.connect(dlg.accept)
    btn_quit.clicked.connect(dlg.reject)

    if dlg.exec() == QDialog.Accepted and edit.text().strip() == _CONFIRM_PHRASE:
        _mark_confirmed()
        return

    # ── 拒绝确认: 提示后退出 (防止倒卖者教买家直接跳过) ──
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(
        None, "未完成免费确认",
        "你还没有完成免费确认，程序即将退出。\n\n"
        "本软件永久免费，请放心使用。\n"
        "如果你是付费获得的，建议向卖家申请退款。\n"
        "重新启动程序即可再次确认。")
    sys.exit(1)


def _rt():
    """返回 Qt.RichText (延迟导入枚举, 保持模块顶部无 Qt 依赖)"""
    from PySide6.QtCore import Qt
    return Qt.RichText
