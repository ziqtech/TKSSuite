"""PatcherWorker — QThread 封装完整补丁流程, 通过 Signal 通知 UI

Phase 4: 改写为 PatcherPipeline 共享类的薄包装。
- GUI 特有逻辑 (tool 注入、TKS.exe MOD 替换、信号通知) 保留在 worker
- 共享补丁流水线 (config/MOD/WarPC/Cave/apply/恢复) 委托给 core.launcher_pipeline.PatcherPipeline
"""
import filecmp
import io
import os
import shutil
import subprocess
import time
import traceback
import zipfile

from PySide6.QtCore import QThread, Signal

from core.launcher_pipeline import PatcherPipeline, PipelineConfig
from core.launch_context import LaunchContext
from core.log_setup import log_line
from core.recovery_snapshot import begin_snapshot, finish_snapshot
from core.memory import (
    find_window, get_child_processes, get_module_base, get_module_size,
    resume_process, suspend_process, read_pm,
    PROCESS_VM_READ,
    _OpenProcess, _CloseHandle,
)


# SkimFstDlg 模式前 7 字节: A1 14 A5 4F 00 50 E8
# 见 sub_4084E0 等游戏代码段,用于早期检测"未加密版"是否已就绪。
# 之前在 4 处硬编码 (patcher_worker / cli_launcher x3),Phase 14 整合时考虑提取。
SKIMFSTDLG_SENTINEL = b'\xA1\x14\xA5\x4F\x00\x50\xE8'


class PatcherWorker(QThread):
    """后台线程：完整补丁工作流 (Phase 4 包装版)"""

    # --- 信号 ---
    log_emitted = Signal(str)
    status_changed = Signal(str, bool)  # text, is_ok
    game_window_found = Signal(int)     # game_hwnd → UI 线程创建悬浮窗
    overlay_update = Signal(str, bool)  # text, is_ok
    finished = Signal(bool, dict)       # success, diagnostics
    profile_detected = Signal(str)      # profile display_name → UI 显示版本信息

    def __init__(self, exe_path: str, game_dir: str | None = None,
                 wait_timeout: int = 30, minimal_mode: bool = False,
                 no_cave_mode: bool = False, selected_patches: set = None,
                 enabled_mod_ids: set = None, selected_tool: str = "",
                 mode: str = "standard"):
        super().__init__()
        self.exe_path = exe_path
        self.game_dir = game_dir
        self.wait_timeout = wait_timeout
        self.minimal_mode = minimal_mode
        self.no_cave_mode = no_cave_mode
        self.selected_patches = selected_patches
        self.enabled_mod_ids = enabled_mod_ids
        self.selected_tool = selected_tool
        self.mode = mode if mode in {"standard", "compatible"} else "standard"
        self._is_running = True
        self._tks_exe_replaced = False
        self._tks_exe_conflict = False
        # 辅助工具注入追踪: {相对路径: True=新建 | False=覆盖已有}
        self._tool_injected_files: dict[str, bool] = {}
        self._launcher_dir: str = ""
        self._recovery_task_id: str = ""

    @classmethod
    def from_context(cls, context: LaunchContext, **kwargs):
        """从不可变启动快照创建 Worker，避免启动期间读取 UI 状态。"""
        ctx = context.normalized()
        return cls(
            exe_path=ctx.exe_path,
            game_dir=ctx.game_dir,
            selected_patches=set(ctx.selected_patches),
            enabled_mod_ids=set(ctx.enabled_mod_ids),
            selected_tool=ctx.selected_tool,
            mode=ctx.mode,
            **kwargs,
        )

    def _log(self, msg: str):
        self.log_emitted.emit(msg)
        # 同步写入会话日志文件 (未初始化时为空操作)
        log_line(msg)

    def _status(self, text: str, is_ok: bool):
        self.status_changed.emit(text, is_ok)

    def _overlay(self, text: str, is_ok: bool):
        self.overlay_update.emit(text, is_ok)

    def run(self):
        try:
            self._do_run()
        except Exception as e:
            self._log(f"[FATAL] 未捕获异常: {e}")
            self._log(traceback.format_exc())
            # 异常路径不在未知游戏进程状态下强行恢复；保留 active 快照交给下次启动确认。
            self.finished.emit(False, {"error": str(e)})

    def _do_run(self):
        # ── 启动器目录 ──
        if "__compiled__" in globals():
            from editor_utils.runtime_bootstrap import get_app_dir
            exe_dir = get_app_dir()
        else:
            exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # workers/ -> root
        if not exe_dir:
            exe_dir = os.getcwd()
        self._launcher_dir = exe_dir
        self._recovery_task_id = begin_snapshot(
            exe_dir, self.game_dir or os.path.dirname(self.exe_path), self.exe_path)

        self._log(f"启动器目录: {exe_dir}")
        self._log(f"工作目录: {os.getcwd()}")

        self._log("========================================")
        self._log("TKS Launcher - 自动运行时补丁启动器 (PySide6 GUI)")
        self._log("========================================")

        # ── 构造共享流水线 ──
        pipeline_cfg = PipelineConfig(
            exe_path=self.exe_path,
            exe_dir=exe_dir,
            game_dir=self.game_dir,
            selected_patches=self.selected_patches,
            enabled_mod_ids=self.enabled_mod_ids,
            mode=self.mode,
            disabled_patches={
                "save_entry_check_fix",
                "save_stream_error_fix",
                "archive_portrait",
                "gold_display",
                "xiaotan_defend_glow",
                "xiaotan_disable_companion",
            } if self.minimal_mode else None,
        )
        pipeline = PatcherPipeline(
            cfg=pipeline_cfg,
            log=self._log,
            status=self._status,
            overlay=self._overlay,
        )

        # ── Phase 1: 启动前准备 (config/MOD/WarPC/TKAct 截断) ──
        pre = pipeline.run_pre_launch()
        if pre.error:
            finish_snapshot(self._launcher_dir, self._recovery_task_id)
            self.finished.emit(False, pre.as_dict())
            return

        # ── GUI 特有: TKS.exe MOD 替换 ──
        _tks_exe_replaced = self._maybe_replace_tks_exe(
            pipeline.loaded_mods,
            game_dir=self.game_dir or os.getcwd(),
        )
        if self._tks_exe_conflict:
            pipeline.cleanup()
            self._restore_tks_exe(self.game_dir or os.getcwd())
            finish_snapshot(self._launcher_dir, self._recovery_task_id)
            self._log("启动已取消：请只保留一个 TKS.exe 替换 MOD")
            self.finished.emit(False, {"error": "multiple TKS.exe replacement mods"})
            return

        # ── GUI 特有: 辅助工具注入 ──
        self._inject_tool_files(exe_dir, self.game_dir or os.getcwd())

        # ── 启动游戏 (CREATE_SUSPENDED: GUI 路径, Wine 走 CLI) ──
        tks_path = self.exe_path
        self._log(f"\n启动 {tks_path}...")
        try:
            tks_proc = subprocess.Popen(
                tks_path,
                cwd=os.path.dirname(os.path.abspath(tks_path)) or os.getcwd(),
                creationflags=0x4,  # CREATE_SUSPENDED
            )
        except Exception as e:
            pipeline.cleanup()
            self._remove_tool_files(self.game_dir or os.getcwd())
            self._restore_tks_exe(self.game_dir or os.getcwd())
            finish_snapshot(self._launcher_dir, self._recovery_task_id)
            self._log(f"[ERROR] 无法启动 {tks_path}: {e}")
            self.finished.emit(False, {"error": f"launch failed: {e}"})
            return
        self._log(f"  TKS.exe PID = {tks_proc.pid} (CREATE_SUSPENDED)")
        pipeline.result.process_started = True
        if self.mode == "compatible":
            # 兼容模式不读取或修改目标进程内存，直接恢复主进程并监控其退出。
            resume_process(tks_proc.pid)
            self._status("游戏运行中（兼容模式）", True)
            self._log("兼容模式: 已跳过目标进程检测和内存补丁")
            pipeline.wait_game_exit(tks_proc, 0)
            pipeline.cleanup()
            self._remove_tool_files(self.game_dir or os.getcwd())
            self._restore_tks_exe(self.game_dir or os.getcwd())
            finish_snapshot(self._launcher_dir, self._recovery_task_id)
            self.finished.emit(True, pipeline.result.as_dict())
            return
        self._status("正在应用游戏功能...", True)

        # ── 进程检测 (早期 + 加密版后备) ──
        target_pid, direct_mode, version_label, _need_resume_pid, \
            base_addr, mod_size, code_buf, code_start = self._detect_target(
                tks_proc, SKIMFSTDLG_SENTINEL
            )
        if target_pid == 0:
            pipeline.cleanup()
            self._remove_tool_files(self.game_dir or os.getcwd())
            self._restore_tks_exe(self.game_dir or os.getcwd())
            finish_snapshot(self._launcher_dir, self._recovery_task_id)
            self.finished.emit(False, {"error": "no target process"})
            return

        self._log(f"  版本: {version_label}")
        self._log(f"  目标 PID: {target_pid}, 直接模式: {direct_mode}")
        self._status("正在应用游戏功能...", True)

        # ── Phase 2: 应用补丁 (委托给 pipeline) ──
        result = pipeline.run_post_launch(
            target_pid=target_pid,
            code_buf=code_buf,
            code_start=code_start,
            base_addr=base_addr,
            mod_size=mod_size,
            need_resume_pid=_need_resume_pid,
            tks_exe_replaced=_tks_exe_replaced,
        )

        # ── 通知 UI profile 检测结果 ──
        if result.profile_name != "original":
            self.profile_detected.emit(result.profile_display)

        # ── 查找游戏窗口 ──
        game_hwnd = 0
        for _ in range(20):
            time.sleep(0.25)
            game_hwnd = find_window("TForm1", None)
            if not game_hwnd:
                game_hwnd = find_window(None, "TK")
            if game_hwnd:
                break
        if game_hwnd:
            self._log(f"  游戏窗口: 0x{game_hwnd:08X}")
            self.game_window_found.emit(game_hwnd)
        else:
            self._log("  [WARN] 未找到游戏窗口, 叠加提示不可用")

        if result.success:
            time.sleep(2)
            self._overlay("", False)

        # ── 等待游戏退出 ──
        self._log("\n等待游戏退出...")
        self._status("游戏功能已生效，游戏运行中" if result.success
                     else "游戏运行中（部分功能未应用）", True)
        pipeline.wait_game_exit(tks_proc, target_pid)

        # ── 收尾 ──
        pipeline.cleanup()
        self._remove_tool_files(self.game_dir or os.getcwd())
        self._restore_tks_exe(self.game_dir or os.getcwd())
        finish_snapshot(self._launcher_dir, self._recovery_task_id)

        self.finished.emit(result.success, result.as_dict())

    # ═══════════════════════════════════════════════════════════════
    # GUI 特有逻辑 (保留)
    # ═══════════════════════════════════════════════════════════════

    def _detect_target(self, tks_proc, sentinel: bytes):
        """早期未加密版检测 + 加密版子进程等待。

        返回 (target_pid, direct_mode, version_label, need_resume_pid,
              base_addr, mod_size, code_buf, code_start)。
        """
        target_pid = 0
        direct_mode = False
        version_label = ""
        _need_resume_pid = 0
        base_addr = 0
        mod_size = 0
        code_buf = None
        code_start = 0

        # ── 早期模块检测 ──
        _base_addr = 0
        for _ in range(6):
            _base_addr = get_module_base(tks_proc.pid)
            if _base_addr:
                break
            time.sleep(0.05)

        if _base_addr:
            _mod_size = get_module_size(tks_proc.pid)
            _code_start = _base_addr + 0x1000
            _code_size = min(_mod_size - 0x1000, 0x300000) if _mod_size > 0x1000 else 0
            if _code_size > 0:
                _hr = _OpenProcess(PROCESS_VM_READ, False, tks_proc.pid)
                if _hr:
                    _raw, _nr = read_pm(_hr, _code_start, _code_size)
                    _CloseHandle(_hr)
                    if _nr > 0:
                        _buf = bytearray(_code_size)
                        _buf[:_nr] = _raw
                        if sentinel in bytes(_buf):
                            target_pid = tks_proc.pid
                            direct_mode = True
                            version_label = "TKS 未加密版 (主进程模式, 已挂起)"
                            _need_resume_pid = tks_proc.pid
                            base_addr = _base_addr
                            mod_size = _mod_size
                            code_start = _code_start
                            code_buf = _buf
                            self._log(f"  [未加密版] 游戏代码已确认, 进程已挂起, 基址: 0x{base_addr:08X}")

        # ── 加密版后备: 恢复 + 轮询子进程 ──
        if target_pid == 0:
            self._log("  未检测到游戏代码 (加密版), 恢复进程以创建子进程...")
            resume_process(tks_proc.pid)
            st = time.time()
            tpid = tks_proc.pid
            _fallback_checked = False
            while (time.time() - st) < self.wait_timeout:
                if not self._is_running:
                    self._log("用户取消")
                    if tks_proc.poll() is None:
                        tks_proc.kill()
                    return 0, False, "", 0, 0, 0, None, 0

                retcode = tks_proc.poll()
                if retcode is not None:
                    self._log(f"  TKS.exe 已退出 (code={retcode})")
                    break

                children = get_child_processes(tpid)
                if children:
                    target_pid = children[0].th32ProcessID
                    version_label = "TKS 加密版 (子进程模式)"
                    en = children[0].szExeFile.decode('ascii', errors='replace')
                    self._log(f"  检测到子进程: PID={target_pid} Name={en} -> {version_label}")
                    self._overlay("正在加载游戏功能...", False)
                    for _ in range(60):
                        if get_module_base(target_pid):
                            break
                        time.sleep(0.05)
                    suspended = suspend_process(target_pid)
                    self._log(f"  已挂起子进程 {suspended} 个线程")
                    _need_resume_pid = target_pid
                    break

                if not direct_mode and not _fallback_checked:
                    tb = get_module_base(tpid)
                    if tb:
                        ms = get_module_size(tpid)
                        cs = tb + 0x1000
                        sz = min(ms - 0x1000, 0x300000) if ms > 0x1000 else 0
                        if sz > 0:
                            ht = _OpenProcess(PROCESS_VM_READ, False, tpid)
                            if ht:
                                raw, nr = read_pm(ht, cs, sz)
                                _CloseHandle(ht)
                                if nr > 0 and sentinel in raw[:nr]:
                                    target_pid = tpid
                                    direct_mode = True
                                    version_label = "TKS 未加密版 (主进程模式, 后备检测)"
                                    base_addr = tb
                                    mod_size = ms
                                    code_start = cs
                                    code_buf = bytearray(sz)
                                    code_buf[:nr] = raw[:nr]
                                    self._log(f"  游戏代码已确认: base=0x{tb:08X} -> {version_label}")
                                    self._overlay("正在加载游戏功能...", False)
                                else:
                                    _fallback_checked = True
                                    self._log(f"  主进程代码段不含游戏特征 (可能是加密壳), 等待子进程...")
                            if direct_mode:
                                break
                time.sleep(0.05)

            if target_pid == 0:
                self._log("[ERROR] 超时，未检测到游戏进程")
                if tks_proc.poll() is None:
                    tks_proc.kill()
                return 0, False, "", 0, 0, 0, None, 0

        # ── 加密版/后备: 读取代码段 ──
        if code_buf is None:
            base_addr = 0
            for _ in range(10):
                base_addr = get_module_base(target_pid)
                if base_addr:
                    break
                time.sleep(0.1)
            if base_addr == 0:
                self._log(f"[ERROR] 无法获取目标进程 {target_pid} 的模块信息")
                if tks_proc.poll() is None:
                    tks_proc.kill()
                return 0, False, "", 0, 0, 0, None, 0
            self._log(f"  模块基址: 0x{base_addr:08X}")
            mod_size = get_module_size(target_pid)
            self._log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")
            code_start = base_addr + 0x1000
            code_size = mod_size - 0x1000 if mod_size > 0x1000 else 0
            if code_size > 0x300000:
                code_size = 0x300000
            code_buf = bytearray(code_size)
            nr = 0
            raw_buf = b''
            for _ in range(5):
                hr = _OpenProcess(PROCESS_VM_READ, False, target_pid)
                if not hr:
                    time.sleep(0.1)
                    continue
                raw_buf, nr = read_pm(hr, code_start, code_size)
                _CloseHandle(hr)
                if nr > 0:
                    break
                time.sleep(0.1)
            if nr <= 0:
                self._log("[ERROR] 无法读取代码段")
                if tks_proc.poll() is None:
                    tks_proc.kill()
                return 0, False, "", 0, 0, 0, None, 0
            code_buf[:nr] = raw_buf
            self._log(f"  代码段: 0x{code_start:08X}-0x{code_start + nr:08X} ({nr} bytes)")
        else:
            self._log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")
            self._log(f"  代码段: 0x{code_start:08X}-0x{code_start + len(code_buf):08X} ({len(code_buf)} bytes)")

        return (target_pid, direct_mode, version_label, _need_resume_pid,
                base_addr, mod_size, code_buf, code_start)

    def _maybe_replace_tks_exe(self, loaded_mods, game_dir: str) -> bool:
        """GUI 特有: type=tks_exe 的 MOD 替换 TKS.exe。

        必须在 process launch 之前完成。
        """
        tks_exe_mod = None
        tks_exe_payload = None
        tks_exe_count = 0
        for m in loaded_mods:
            if getattr(m, 'mod_type', '') == "tks_exe":
                tks_exe_count += 1
                if tks_exe_mod is None:
                    tks_exe_mod = m
        if tks_exe_count > 1:
            self._tks_exe_conflict = True
            self._log(f"  [ERROR] 检测到 {tks_exe_count} 个 TKS.exe 替换 MOD，无法安全选择")
            return False
        if not tks_exe_mod:
            return False
        try:
            self._log(f"\n--- TKS.exe 替换 ({tks_exe_mod.name}) ---")
            tks_target = os.path.join(game_dir, "TKS.exe")
            tks_orig = tks_target + ".mod_orig"
            if os.path.isfile(tks_target) and not os.path.isfile(tks_orig):
                shutil.copy2(tks_target, tks_orig)
                self._log(f"  备份: TKS.exe → TKS.exe.mod_orig")
            if getattr(tks_exe_mod, "_data_raw", None):
                with zipfile.ZipFile(io.BytesIO(tks_exe_mod._data_raw), 'r') as zf:
                    tks_exe_payload = zf.read("resources/TKS.exe") if "resources/TKS.exe" in zf.namelist() else None
            else:
                with zipfile.ZipFile(tks_exe_mod.path, 'r') as zf:
                    tks_exe_payload = zf.read("resources/TKS.exe") if "resources/TKS.exe" in zf.namelist() else None
            if tks_exe_payload is not None:
                    exe_data = tks_exe_payload
                    with open(tks_target, 'wb') as f:
                        f.write(exe_data)
                    self._tks_exe_replaced = True
                    self._log(f"  已替换 TKS.exe ({len(exe_data):,} bytes)")
                    return True
            self._log(f"  [ERROR] MOD 中未找到 resources/TKS.exe")
            return False
        except Exception as e:
            self._log(f"  [ERROR] TKS.exe 替换失败: {e}")
            return False

    def _restore_tks_exe(self, game_dir: str):
        """恢复本次启动替换的 TKS.exe，避免第三方 EXE 永久留在游戏目录。"""
        if not self._tks_exe_replaced:
            return
        target = os.path.join(game_dir, "TKS.exe")
        backup = target + ".mod_orig"
        try:
            if os.path.isfile(backup):
                shutil.copy2(backup, target)
                os.remove(backup)
                self._log("已恢复原版 TKS.exe")
            else:
                self._log("[WARN] 找不到 TKS.exe 备份，无法自动恢复")
        except Exception as e:
            self._log(f"[WARN] 恢复 TKS.exe 失败: {e}")
        finally:
            self._tks_exe_replaced = False

    def stop(self):
        self._is_running = False

    # ────────────────────────────────────────────────
    # 辅助工具：注入 / 清理 (GUI 特有)
    # ────────────────────────────────────────────────

    def _inject_tool_files(self, launcher_dir: str, game_dir: str):
        """将选中的辅助工具文件复制到游戏目录，并记录注入状态以便后续清理。"""
        if not self.selected_tool:
            return

        tool_src = os.path.join(launcher_dir, "tools", self.selected_tool)
        if not os.path.isdir(tool_src):
            self._log(f"  [WARN] 辅助工具目录不存在: {tool_src}")
            return

        self._log(f"\n=== 注入辅助工具: {self.selected_tool} ===")
        injected = 0
        for root, dirs, files in os.walk(tool_src):
            rel_root = os.path.relpath(root, tool_src)
            for fname in files:
                src_file = os.path.join(root, fname)
                rel_path = os.path.join(rel_root, fname) if rel_root != "." else fname
                dst_file = os.path.join(game_dir, rel_path)

                dst_dir = os.path.dirname(dst_file)
                if not os.path.isdir(dst_dir):
                    os.makedirs(dst_dir, exist_ok=True)
                    self._log(f"  创建目录: {os.path.relpath(dst_dir, game_dir)}")

                is_new = not os.path.isfile(dst_file)
                if not is_new:
                    try:
                        if filecmp.cmp(src_file, dst_file, shallow=False):
                            is_new = True
                    except Exception:
                        pass
                if not is_new:
                    bak = dst_file + ".toolbak"
                    try:
                        shutil.copy2(dst_file, bak)
                    except Exception as e:
                        self._log(f"  [WARN] 备份 {rel_path} 失败: {e}")
                self._tool_injected_files[rel_path] = is_new

                try:
                    shutil.copy2(src_file, dst_file)
                    injected += 1
                    status = "新文件" if is_new else "覆盖"
                    self._log(f"  [{status}] {rel_path}")
                except Exception as e:
                    self._log(f"  [ERROR] 复制 {rel_path} 失败: {e}")

        self._log(f"  共注入 {injected} 个文件")

    def _remove_tool_files(self, game_dir: str):
        """游戏退出后，移除辅助工具注入的文件（恢复被覆盖的文件，删除新建的文件）。"""
        if not self._tool_injected_files:
            return

        self._log(f"\n=== 清理辅助工具文件 ===")
        removed = 0
        restored_dirs: set[str] = set()

        for rel_path, is_new in self._tool_injected_files.items():
            dst_file = os.path.join(game_dir, rel_path)
            if is_new:
                if os.path.isfile(dst_file):
                    try:
                        os.remove(dst_file)
                        removed += 1
                        self._log(f"  [删除] {rel_path}")
                    except Exception as e:
                        self._log(f"  [ERROR] 删除 {rel_path} 失败: {e}")
            else:
                bak = dst_file + ".toolbak"
                if os.path.isfile(bak):
                    try:
                        shutil.copy2(bak, dst_file)
                        os.remove(bak)
                        removed += 1
                        self._log(f"  [恢复] {rel_path}")
                    except Exception as e:
                        self._log(f"  [ERROR] 恢复 {rel_path} 失败: {e}")
            rel_dir = os.path.dirname(rel_path)
            if rel_dir:
                restored_dirs.add(rel_dir)

        sorted_dirs = sorted(restored_dirs, key=lambda d: d.count(os.sep), reverse=True)
        for rel_dir in sorted_dirs:
            dir_path = os.path.join(game_dir, rel_dir)
            if os.path.isdir(dir_path) and not os.listdir(dir_path):
                try:
                    os.rmdir(dir_path)
                    self._log(f"  [删除目录] {rel_dir}")
                except Exception:
                    pass

        self._log(f"  共清理 {removed} 个文件")
        self._tool_injected_files.clear()
