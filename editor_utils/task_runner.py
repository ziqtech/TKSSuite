"""后台任务执行器 — 编辑器/启动器共用的 QThread 薄封装 (P3-3 长任务线程化)。

以 mat_threads.py 的 QThread+Signal 范式为蓝本泛化: 一次任务一个
:class:`FunctionWorker`, 把任意纯数据函数挪出 UI 线程, 结果经队列信号
送回 UI 线程。两个入口:

  * :func:`run_background` — 无界面后台任务 (编辑器加载/保存, 进度走
    编辑器自身状态栏);
  * :func:`run_with_progress` — 模态 QProgressDialog (启动器对话框的
    备份/恢复等无日志区的长任务)。

线程安全约定:
  * ``fn`` 在工作线程执行, 只允许纯计算/文件 IO, **不得触碰任何 QWidget**;
    需要输出日志用 ``worker.progress(text)`` (信号自动排队到 UI 线程);
  * 可取消的任务周期性检查 ``worker.is_cancelled()`` 并尽早返回;
    底层函数不支持协作取消时不要给对话框挂取消按钮;
  * worker 完成后自动回收 (deleteLater), 重入守卫一律用
    :func:`is_running` 判断, 不要直接访问旧引用。
"""
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QProgressDialog


class FunctionWorker(QThread):
    """把 ``fn(worker) -> result`` 放到后台线程执行。

    信号 (均为队列投递, 槽在 UI 线程执行):
      progressed(str)    — work 内 progress() 调用的转发 (日志/阶段文本)
      finished_ok(object)— fn 正常返回 (参数为返回值)
      failed(str)        — fn 抛异常 (参数为 消息+traceback)
    """

    progressed = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    # ── 工作线程侧 API (fn 内调用) ──
    def progress(self, text: str) -> None:
        """向 UI 线程转发一条日志/进度文本。"""
        self.progressed.emit(str(text))

    def is_cancelled(self) -> bool:
        """协作取消检查: 长循环应周期性调用并尽早返回。"""
        return self._cancelled

    def cancel(self) -> None:
        """请求取消 (仅置位标志, 由 work 自行检查响应)。"""
        self._cancelled = True

    # ── 线程主体 ──
    def run(self):
        try:
            result = self._fn(self)
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.finished_ok.emit(result)


def is_running(worker) -> bool:
    """重入守卫: worker 为 None/已回收时返回 False。"""
    if worker is None:
        return False
    try:
        return worker.isRunning()
    except RuntimeError:  # C++ 对象已被回收
        return False


def run_background(parent, fn, *, on_success=None, on_error=None,
                   on_progress=None) -> FunctionWorker:
    """启动无界面后台任务。

    fn: callable(worker) -> result (工作线程执行);
    on_success/on_error: UI 线程回调 (参数为 result / 错误文本);
    on_progress: UI 线程回调 (参数为文本), 未提供时忽略进度。
    返回 worker (调用方持有引用用于重入守卫; 完成后自动回收)。
    """
    worker = FunctionWorker(fn, parent)
    if on_progress is not None:
        worker.progressed.connect(on_progress)

    def _finish(handler, arg):
        if handler is not None:
            handler(arg)
        worker.setParent(None)
        worker.deleteLater()

    worker.finished_ok.connect(lambda result: _finish(on_success, result))
    worker.failed.connect(lambda err: _finish(on_error, err))
    worker.start()
    return worker


def run_with_progress(parent, title, fn, *, on_success=None, on_error=None,
                      on_progress=None, label="处理中…",
                      cancellable=False) -> FunctionWorker:
    """启动带模态进度对话框的后台任务 (busy 圈, 无百分比刻度)。

    cancellable=True 时挂"取消"按钮 — 仅置位取消标志, fn 必须配合
    is_cancelled() 检查, 否则不要开启。
    """
    dlg = QProgressDialog(label, "取消" if cancellable else "", 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumDuration(0)
    if not cancellable:
        dlg.setCancelButton(None)
        # 任务不可取消时禁用 X: 防止关闭触发 cancel 语义而任务仍在跑
        dlg.setWindowFlag(Qt.WindowCloseButtonHint, False)
    dlg.show()

    def _done():
        dlg.reset()
        dlg.deleteLater()

    worker = FunctionWorker(fn, parent)
    if on_progress is not None:
        worker.progressed.connect(on_progress)
    else:
        worker.progressed.connect(dlg.setLabelText)  # 默认: 进度文本上对话框

    def _finish(handler, arg):
        if handler is not None:
            handler(arg)
        _done()
        worker.setParent(None)
        worker.deleteLater()

    worker.finished_ok.connect(lambda result: _finish(on_success, result))
    worker.failed.connect(lambda err: _finish(on_error, err))
    if cancellable:
        dlg.canceled.connect(worker.cancel)
    worker.start()
    return worker
