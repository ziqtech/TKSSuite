"""启动器文件日志 — GUI / CLI 共用, 无 PySide6 依赖。

只保留单个日志文件: <启动器目录>/logs/launcher_gui.log (CLI 为
launcher_cli.log), 每次启动清空重写。启动器日志只服务于"最近一次
启动"的问题排查, 不是服务器日志, 不做历史归档。

目录解析需区分两种运行环境 (与 main.py / cli_launcher.py 保持一致):
  打包环境 (Nuitka): sys.argv[0] 即 exe 路径, 取同级目录;
      GUI 薄 exe 优先复用 editor_utils.runtime_bootstrap.get_app_dir();
      CLI exe 未打包 editor_utils, 导入失败时回退到 sys.argv[0]。
  开发环境: 以本文件位置推算 (core/ 的上一级即启动器根目录),
      不依赖 os.getcwd() — 玩家/开发者可能从任意目录启动。

写入失败 (目录不可写等) 时静默降级为无文件日志, 不影响启动器运行。
"""
import logging
import os
import platform
import re
import sys

LOG_DIR_NAME = "logs"
_LOGGER_NAME = "tks_launcher"
_setup_done = False


def _is_compiled() -> bool:
    """是否运行在 Nuitka 打包环境 (本模块被编译时带有 __compiled__ 全局)"""
    return "__compiled__" in globals() or getattr(sys, "frozen", False)


def get_launcher_dir() -> str:
    """返回启动器根目录 (打包环境: exe 所在目录; 开发环境: 源码目录)"""
    if _is_compiled():
        # GUI 薄 exe: runtime_bootstrap 提供可靠的发行目录定位
        try:
            from editor_utils.runtime_bootstrap import get_app_dir
            app_dir = get_app_dir()
            if app_dir:
                return app_dir
        except Exception:
            pass  # CLI exe 未包含 editor_utils, 走 argv 回退
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    # 开发环境: core/log_setup.py -> core/ -> 启动器根目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_log_dir() -> str:
    """返回日志目录 <启动器目录>/logs (尽力创建, 失败返回空串)"""
    log_dir = os.path.join(get_launcher_dir(), LOG_DIR_NAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except OSError:
        return ""


def setup_logging(prefix: str = "launcher") -> str:
    """初始化日志文件, 返回日志路径 (失败返回空串)。

    固定单文件: <logs>/<prefix>.log, 每次启动清空重写 (mode='w')。
    prefix: GUI 用 "launcher_gui", CLI 用 "launcher_cli"。
    重复调用幂等, 返回已建立的日志路径。
    """
    global _setup_done
    logger = logging.getLogger(_LOGGER_NAME)
    if _setup_done:
        for h in logger.handlers:
            path = getattr(h, "baseFilename", "")
            if path:
                return path
        return ""

    _setup_done = True
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_dir = get_log_dir()
    if not log_dir:
        return ""

    log_path = os.path.join(log_dir, f"{prefix}.log")
    try:
        # mode='w': 每次启动清空, 日志只反映最近一次启动
        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
    except OSError:
        return ""

    _cleanup_legacy_logs(log_dir, prefix)
    return log_path


def _cleanup_legacy_logs(log_dir: str, prefix: str) -> None:
    """清理旧版时间戳命名日志 (<prefix>_<日期>_<时间>.log), 尽力而为。

    单文件方案上线前的历史产物; 现行方案只使用 <prefix>.log。
    """
    legacy = re.compile(rf"^{re.escape(prefix)}_\d{{8}}_\d{{6}}\.log$")
    try:
        for name in os.listdir(log_dir):
            if legacy.match(name):
                try:
                    os.remove(os.path.join(log_dir, name))
                except OSError:
                    pass
    except OSError:
        pass


# 行内标记 → logging 级别映射。标记体系与 ui/log_console.py 的高亮规则一致,
# 整条消息 (含多行) 统一取首个命中的级别, 保证 traceback 等续行归属同一级别。
_LEVEL_MARKERS = (
    ("[FATAL]", logging.CRITICAL),
    ("[CRITICAL]", logging.CRITICAL),
    ("[ERROR]", logging.ERROR),
    ("[WARN]", logging.WARNING),
    ("[WARNING]", logging.WARNING),
)
_last_level = logging.INFO


# traceback 续行特征: traceback 常与 [FATAL] 消息分开发送 (见
# patcher_worker.run / cli_launcher.run), 需按内容特征归为 CRITICAL,
# 否则会降为 INFO 失去检索意义。
_TB_CONT_MARKERS = (
    "Traceback (most recent call last)",
    '  File "',
)
# traceback 末尾的异常类型行, 如 "ZeroDivisionError: division by zero"
_TB_EXC_LINE = re.compile(r"^[A-Z][A-Za-z0-9_]*(?:Error|Exception|Interrupt)(?::|$)")


def _detect_level(msg: str) -> int:
    """按行内标记推断日志级别, 无标记的续行 (如 traceback) 继承上一条高级别"""
    for marker, level in _LEVEL_MARKERS:
        if marker in msg:
            return level
    # traceback 续行 (帧列表/异常类型行) 与前面的 FATAL/ERROR 同级
    if any(m in msg for m in _TB_CONT_MARKERS) or _TB_EXC_LINE.match(msg):
        return logging.CRITICAL
    # 缩进续行 (如 traceback 代码行) 继承上一条高级别; 顶格消息不继承
    if _last_level >= logging.ERROR and msg.startswith((" ", "\t")):
        return _last_level
    return logging.INFO


def log_line(msg: str) -> None:
    """将一行启动器日志 (原 [INFO]/[ERROR] 等格式) 同步写入日志文件。

    供 patcher_worker._log / cli_launcher._log 等回调式日志复用,
    多行内容 (如 traceback) 按行拆分写入;
    级别按 [FATAL]/[ERROR]/[WARN] 标记映射, 无标记默认为 INFO。
    """
    global _last_level
    if not _setup_done:
        return
    logger = logging.getLogger(_LOGGER_NAME)
    level = _detect_level(str(msg))
    _last_level = level
    for line in str(msg).splitlines() or [""]:
        logger.log(level, line)
        _buffer_pre_ui(line)


# ── UI 注入缓冲 ──
# GUI 控制台 (LogConsole) 在 MainWindow 构造时才存在, 而会话头等日志在此之前
# 已写入文件。暂存这些行, 由 UI 侧调用 take_startup_lines() 注入,
# 保证「查看详细日志」弹窗内容与日志文件一致。
_pre_ui_lines: list = []
_ui_attached = False


def _buffer_pre_ui(line: str) -> None:
    if not _ui_attached:
        _pre_ui_lines.append(line)


def take_startup_lines() -> list:
    """取出并清空启动期日志行 (供 GUI 控制台注入)。

    调用后标记 UI 已接管: 后续日志经 worker 信号直达控制台, 不再缓存。
    重复调用返回空列表。
    """
    global _ui_attached
    _ui_attached = True
    lines = list(_pre_ui_lines)
    _pre_ui_lines.clear()
    return lines


def log_session_header(app_label: str) -> None:
    """记录一次会话的启动环境信息, 方便定位问题。"""
    if not _setup_done:
        return
    logger = logging.getLogger(_LOGGER_NAME)
    runtime = "打包环境 (Nuitka)" if _is_compiled() else "开发环境 (源码)"
    lines = [
        "=" * 60,
        f"{app_label} 启动 | {runtime}",
        f"启动器目录: {get_launcher_dir()}",
        f"工作目录: {os.getcwd()}",
        f"Python: {platform.python_version()} | OS: {platform.platform()}",
        f"命令行: {sys.argv}",
        "=" * 60,
    ]
    for line in lines:
        logger.info(line)
        _buffer_pre_ui(line)


def install_excepthook() -> None:
    """捕获未处理异常写入日志 (打包后无控制台, 崩溃信息只在这里)。"""
    prev_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            logger = logging.getLogger(_LOGGER_NAME)
            logger.critical(
                "未捕获异常: %s", "".join(
                    __import__("traceback").format_exception(
                        exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        try:
            if prev_hook:
                prev_hook(exc_type, exc_value, exc_tb)
            else:
                sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:
            pass  # 打包后无控制台时原钩子写 stderr 可能失败, 日志已记录

    sys.excepthook = _hook
