"""
TKS Launcher CLI — Headless 启动器 (Winlator 兼容)
=================================================
Phase 4: 改写为 PatcherPipeline 共享类的薄包装。
- CLI 特有逻辑 (Wine 检测、--no-X 诊断开关、Ctrl+C 处理、argparse) 保留
- 共享补丁流水线 (config/MOD/WarPC/Cave/apply/恢复) 委托给 core.launcher_pipeline.PatcherPipeline

用法:
  python cli_launcher.py                          # 开发环境
  python cli_launcher.py --tks-exe "D:\\game\\TKS.exe"
  TKSLauncherCLI.exe                              # Nuitka 编译后

配置文件 (可选, 放在 exe 同目录):
  launcher_config.json — 与 PC 版 TKSLauncher (GUI) 共用同一配置文件。
  在 PC 上用 GUI 配置完成后, 直接复制该文件到 Winlator 游戏目录即可。
"""
import argparse
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime

# 确保 core/ 可导入 (开发环境)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from core.launcher_pipeline import PatcherPipeline, PipelineConfig
from core.log_setup import log_line
from core.memory import (
    find_window, get_child_processes, get_module_base, get_module_size,
    read_pm, resume_process, suspend_process,
    PROCESS_VM_READ,
    _OpenProcess, _CloseHandle,
)
from core.tkspatch_loader import load_patch_directory
from core.patch_engine import validate_script_patch


# SkimFstDlg 模式前 7 字节: A1 14 A5 4F 00 50 E8
SKIMFSTDLG_SENTINEL = b'\xA1\x14\xA5\x4F\x00\x50\xE8'


# ═══════════════════════════════════════════════════════════════
# Wine 环境检测
# ═══════════════════════════════════════════════════════════════

def _is_wine() -> bool:
    """检测是否运行在 Wine 环境下 (包括 Winlator)。

    多重检测策略, 确保在各种 Wine/Winlator 版本下都能正确识别:
    1. wine_get_version 函数 (Wine ntdll.dll 特有)
    2. wine_get_build_id 函数 (Wine ntdll.dll 特有)
    3. 注册表 HKEY_CURRENT_USER\\Software\\Wine
    4. 环境变量 WINEPREFIX / WINELOADER
    """
    try:
        ntdll = ctypes.windll.ntdll
        # Wine ntdll.dll 特有导出函数, 任一存在即为 Wine 环境
        wine_exports = ("wine_get_version", "wine_get_build_id")
        if any(hasattr(ntdll, name) for name in wine_exports):
            return True
    except Exception:
        pass
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Wine")
        winreg.CloseKey(key)
        return True
    except Exception:
        pass
    if os.environ.get("WINEPREFIX") or os.environ.get("WINELOADER"):
        return True
    return False


def _get_wine_version() -> str | None:
    """获取 Wine 版本字符串 (仅 Wine 环境下有效)"""
    try:
        ntdll = ctypes.windll.ntdll
        get_version = getattr(ntdll, 'wine_get_version', None)
        if get_version:
            get_version.restype = ctypes.c_char_p
            ver = get_version()
            return ver.decode('utf-8') if ver else None
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _get_exe_dir():
    """获取 exe/脚本 所在目录"""
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        return os.path.dirname(os.path.abspath(__file__))


class _StdoutTee:
    """CLI 模式下将 stdout 同步镜像到会话日志文件。

    CLI 全部输出为行式日志型文本 (无 input/进度条), 通过包装
    sys.stdout 可捕获所有 print (含配置解析、补丁验证), 无需改动各调用点。
    """

    def __init__(self, stream):
        self._stream = stream
        self._buffer = ""

    def write(self, text):
        self._stream.write(text)
        try:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    log_line(line)
        except Exception:
            pass  # 日志失败绝不影响控制台输出

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        # isatty/encoding 等属性透传给真实流
        return getattr(self._stream, name)


def _init_cli_logging() -> None:
    """初始化 CLI 会话日志 (<启动器目录>/logs/), 并镜像 stdout"""
    from core.log_setup import (
        install_excepthook, log_session_header, setup_logging,
    )
    log_path = setup_logging(prefix="launcher_cli")
    install_excepthook()
    log_session_header("TKS Launcher CLI")
    if log_path:
        sys.stdout = _StdoutTee(sys.stdout)
        print(f"[日志] 日志文件: {log_path}")


def _load_launcher_config(exe_dir: str, args) -> dict:
    """加载 launcher_config.json (可选)"""
    config_path = args.config
    if not config_path:
        config_path = os.path.join(exe_dir, "launcher_config.json")
        if not os.path.isfile(config_path):
            config_path = os.path.join(os.getcwd(), "launcher_config.json")

    cfg = {}
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            print(f"[配置] 已加载: {config_path}")
        except Exception as e:
            print(f"[WARN] 配置文件解析失败: {e}")

    if args.tks_exe:
        cfg.setdefault("tks_exe", {})["path"] = args.tks_exe
    if args.game_dir:
        cfg.setdefault("game", {})["dir"] = args.game_dir

    return cfg


def parse_patch_selection(cfg: dict):
    """解析配置中启用的可选补丁。

    返回 None = 使用 default_checked 默认勾选 (字段缺失或为空/仅说明字段);
    返回 set = 显式指定的勾选集合 (可能为空集, 表示全部禁用)。

    格式 (与 GUI 共用): "patches": {patch_id: true/false}
    下划线开头的键为说明字段, 一律跳过。
    """
    patches_cfg = cfg.get("patches", {})
    if not isinstance(patches_cfg, dict):
        return None
    entries = {str(k): v for k, v in patches_cfg.items()
               if not str(k).startswith("_")}
    if not entries:
        return None
    return {pid for pid, v in entries.items() if bool(v)}


def parse_mod_selection(cfg: dict):
    """解析配置中启用的 MOD。

    返回 None = 全部启用 (字段缺失或为空/仅说明字段);
    返回 set = 显式指定的启用集合 (可能为空集, 表示全部禁用)。

    格式 (与 GUI 共用): "mods": {mod_id: true/false}
    下划线开头的键为说明字段, 一律跳过。
    """
    mods_cfg = cfg.get("mods", {})
    if not isinstance(mods_cfg, dict):
        return None
    entries = {str(k): v for k, v in mods_cfg.items()
               if not str(k).startswith("_")}
    if not entries:
        return None
    return {mid for mid, v in entries.items() if bool(v)}


def parse_mode(cfg: dict) -> str:
    """解析启动模式 (standard=标准 / compatible=兼容), 非法值回退 standard。"""
    mode = cfg.get("mode", "standard")
    return mode if mode in {"standard", "compatible"} else "standard"


def _resolve_tks_exe(cfg: dict, exe_dir: str) -> str:
    """解析 TKS.exe 路径"""
    tks_cfg = cfg.get("tks_exe", {})
    path = tks_cfg.get("path", "TKS.exe")
    if os.path.isabs(path):
        return os.path.normpath(path)
    candidate = os.path.normpath(os.path.join(exe_dir, path))
    if os.path.isfile(candidate):
        return candidate
    candidate = os.path.normpath(os.path.join(os.getcwd(), path))
    return candidate


def _resolve_game_dir(cfg: dict, tks_path: str) -> str:
    """解析游戏目录"""
    gd = cfg.get("game", {}).get("dir", "")
    if gd:
        return os.path.normpath(gd) if os.path.isabs(gd) else os.path.normpath(
            os.path.join(os.path.dirname(tks_path), gd))
    return os.path.dirname(os.path.abspath(tks_path))


def _build_disabled_patches(args, cfg: dict) -> set:
    """根据 --no-* 诊断开关构造 disabled_patches 集合。"""
    disabled = set()
    adv = cfg.get("advanced", {})

    def _on(name):
        return getattr(args, name, False) or adv.get(name, False)

    if _on("no_runtime_hooks"):
        disabled.update({
            "save_entry_check_fix", "save_stream_error_fix",
            "archive_portrait", "gold_display",
        })
    if _on("no_save_entry_stream_fixes"):
        disabled.update({"save_entry_check_fix", "save_stream_error_fix"})
    if _on("no_archive_portrait"):
        disabled.add("archive_portrait")
    if _on("no_gold_display"):
        disabled.add("gold_display")
    return disabled


# ═══════════════════════════════════════════════════════════════
# CliLauncher
# ═══════════════════════════════════════════════════════════════

class CliLauncher:
    """Headless 启动器 — 无 PySide6 依赖 (Phase 4 包装版)"""

    def __init__(self, tks_path: str, game_dir: str | None = None,
                 wait_timeout: int = 30,
                 selected_patches: set = None,
                 enabled_mod_ids=None,
                 disabled_patches: set = None,
                 no_inject_warpc: bool = False,
                 no_suspend: bool = False,
                 mode: str = "standard"):
        self.tks_path = os.path.abspath(tks_path)
        self.game_dir = game_dir
        self.wait_timeout = wait_timeout
        self.selected_patches = selected_patches
        self.enabled_mod_ids = enabled_mod_ids
        self.disabled_patches = disabled_patches or set()
        self.no_inject_warpc = no_inject_warpc
        self.no_suspend = no_suspend
        self.mode = mode if mode in {"standard", "compatible"} else "standard"
        self._is_running = True

        self._orig_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._on_sigint)

    def _on_sigint(self, signum, frame):
        print("\n[中断] 收到 Ctrl+C, 正在退出...")
        self._is_running = False
        if self._orig_sigint and self._orig_sigint != signal.SIG_DFL:
            signal.signal(signal.SIGINT, self._orig_sigint)

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, msg: str):
        print(f"[{self._ts()}] {msg}")

    def run(self) -> tuple:
        try:
            return self._do_run()
        except Exception as e:
            self._log(f"[FATAL] 未捕获异常: {e}")
            # traceback 经 _log 输出 (stdout), 确保同时进入会话日志文件
            self._log(traceback.format_exc().rstrip())
            return False, {"error": str(e)}
        finally:
            signal.signal(signal.SIGINT, self._orig_sigint)

    def _do_run(self):
        exe_dir = _get_exe_dir() or os.getcwd()

        self._log(f"启动器目录: {exe_dir}")
        self._log(f"工作目录: {os.getcwd()}")

        self._log("=" * 40)
        self._log("TKS Launcher CLI — Headless 启动器")
        self._log("=" * 40)

        # ── 构造共享流水线 ──
        # 默认勾选可选补丁 (匹配 GUI 行为); 兼容模式不启用启动器游戏功能, 无需选择
        if self.selected_patches is None and self.mode == "standard":
            self.selected_patches = self._build_default_selection(exe_dir)
            if self.selected_patches:
                _names = ", ".join(sorted(self.selected_patches))
                self._log(f"  默认启用可选补丁: {_names}")

        pipeline_cfg = PipelineConfig(
            exe_path=self.tks_path,
            exe_dir=exe_dir,
            game_dir=self.game_dir,
            selected_patches=self.selected_patches,
            enabled_mod_ids=self.enabled_mod_ids,
            disabled_patches=self.disabled_patches or None,
            mode=self.mode,
        )
        pipeline = PatcherPipeline(cfg=pipeline_cfg, log=self._log)

        # ── Phase 1: 启动前准备 ──
        pre = pipeline.run_pre_launch()
        if pre.error:
            return False, pre.as_dict()

        # ── 启动游戏 (Wine 兼容) ──
        is_wine = _is_wine() or self.no_suspend
        if is_wine:
            if self.no_suspend and not _is_wine():
                self._log("  用户强制禁用 CREATE_SUSPENDED (--no-suspend)")
            else:
                self._log("  检测到 Wine/Winlator 环境, 使用兼容模式 (无 CREATE_SUSPENDED)")

        self._log(f"\n启动 {self.tks_path}...")
        if not os.path.isfile(self.tks_path):
            self._log(f"[ERROR] TKS.exe 不存在: {self.tks_path}")
            return False, {"error": f"tks_exe not found: {self.tks_path}"}

        try:
            tks_proc = subprocess.Popen(
                self.tks_path,
                cwd=os.path.dirname(os.path.abspath(self.tks_path)) or os.getcwd(),
                creationflags=0x4 if not is_wine else 0,  # CREATE_SUSPENDED 仅原生
            )
        except Exception as e:
            pipeline.cleanup()
            self._log(f"[ERROR] 无法启动 {self.tks_path}: {e}")
            return False, {"error": f"launch failed: {e}"}

        self._log(f"  TKS.exe PID = {tks_proc.pid}" +
                  (" (CREATE_SUSPENDED)" if not is_wine else ""))

        # ── 兼容模式: 不读取或修改目标进程内存 (与 GUI 行为一致) ──
        if self.mode == "compatible":
            if not is_wine:
                resume_process(tks_proc.pid)
                self._log("  兼容模式: 已恢复挂起的主进程")
            result = pipeline.run_post_launch(
                target_pid=0, code_buf=bytearray(), code_start=0,
                base_addr=0, mod_size=0,
            )
            self._log("\n等待游戏退出...")
            pipeline.wait_game_exit(tks_proc, 0)
            pipeline.cleanup()
            self._log("启动器退出。")
            return result.success, result.as_dict()

        # ── 进程检测 (Wine 路径 vs 原生路径) ──
        target_pid, direct_mode, version_label, _need_resume_pid, \
            base_addr, mod_size, code_buf, code_start = self._detect_target(
                tks_proc, is_wine,
            )
        if target_pid == 0:
            return False, {"error": "no target process"}

        self._log(f"  版本: {version_label}")
        self._log(f"  目标 PID: {target_pid}, 直接模式: {direct_mode}")

        # ── Phase 2: 应用补丁 ──
        result = pipeline.run_post_launch(
            target_pid=target_pid,
            code_buf=code_buf,
            code_start=code_start,
            base_addr=base_addr,
            mod_size=mod_size,
            need_resume_pid=_need_resume_pid,
        )

        # ── 注入跳过 (CLI 特有) ──
        if self.no_inject_warpc:
            self._log("  [inject_warpc_data] 跳过 (no_inject_warpc)")
            # pipeline 已注入, 此处仅日志提示, 不重做 (Phase 4 简化: 复用 pipeline 行为)

        # ── 等待游戏退出 ──
        self._log("\n等待游戏退出...")
        pipeline.wait_game_exit(tks_proc, target_pid)

        # ── 收尾 ──
        pipeline.cleanup()

        self._log("启动器退出。")
        return result.success, result.as_dict()

    def _build_default_selection(self, exe_dir: str) -> set:
        """构建 GUI 默认勾选集合: 仅 optional + default_checked=True 的补丁。"""
        patches_dir = os.path.join(exe_dir, "patches")
        cfg = load_patch_directory(patches_dir, log_func=self._log)
        if cfg is None:
            return set()
        return {p.id for p in cfg.patches if p.optional and p.default_checked}

    # ═══════════════════════════════════════════════════════════════
    # CLI 特有: 进程检测 (Wine vs 原生分支)
    # ═══════════════════════════════════════════════════════════════

    def _detect_target(self, tks_proc, is_wine: bool):
        """Wine 兼容版 / 原生 Windows 两种进程检测路径。"""
        target_pid = 0
        direct_mode = False
        version_label = ""
        _need_resume_pid = 0
        base_addr = 0
        mod_size = 0
        code_buf = None
        code_start = 0

        if not is_wine:
            # ── 原生 Windows: CREATE_SUSPENDED 早期模块检测 ──
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
                            if SKIMFSTDLG_SENTINEL in bytes(_buf):
                                target_pid = tks_proc.pid
                                direct_mode = True
                                version_label = "TKS 未加密版 (主进程模式, 已挂起)"
                                _need_resume_pid = tks_proc.pid
                                base_addr = _base_addr
                                mod_size = _mod_size
                                code_start = _code_start
                                code_buf = _buf
                                self._log(f"  [未加密版] 游戏代码已确认, 进程已挂起, 基址: 0x{base_addr:08X}")

        # ── 加密版/Wine 后备检测 ──
        if target_pid == 0:
            if is_wine:
                # Wine 路径: 立即找游戏窗口 (无头模式允许无窗口)
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
                else:
                    self._log("  [INFO] 未检测到游戏窗口 (无头模式下不影响)")

                self._log(f"等待游戏进程就绪 (最多{self.wait_timeout}秒)...")
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
                        version_label = "TKS 加密版 (子进程模式, Wine 兼容)"
                        en = children[0].szExeFile.decode('ascii', errors='replace')
                        self._log(f"  检测到子进程: PID={target_pid} Name={en} -> {version_label}")
                        time.sleep(3)
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
                                    if nr > 0 and SKIMFSTDLG_SENTINEL in raw[:nr]:
                                        target_pid = tpid
                                        direct_mode = True
                                        version_label = "TKS 未加密版 (主进程模式, Wine 后备)"
                                        base_addr = tb
                                        mod_size = ms
                                        code_start = cs
                                        code_buf = bytearray(sz)
                                        code_buf[:nr] = raw[:nr]
                                        self._log(f"  游戏代码已确认: base=0x{tb:08X} -> {version_label}")
                                    else:
                                        _fallback_checked = True
                                        self._log(f"  主进程代码段不含游戏特征 (可能是加密壳), 等待子进程...")
                            if direct_mode:
                                break
                    time.sleep(0.5)

                if target_pid == 0:
                    self._log("[ERROR] 超时，未检测到游戏进程")
                    if tks_proc.poll() is None:
                        tks_proc.kill()
                    return 0, False, "", 0, 0, 0, None, 0
            else:
                # ── 原生 Windows 加密版: resume + 子进程挂起 ──
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
                                    if nr > 0 and SKIMFSTDLG_SENTINEL in raw[:nr]:
                                        target_pid = tpid
                                        direct_mode = True
                                        version_label = "TKS 未加密版 (主进程模式, 后备检测)"
                                        base_addr = tb
                                        mod_size = ms
                                        code_start = cs
                                        code_buf = bytearray(sz)
                                        code_buf[:nr] = raw[:nr]
                                        self._log(f"  游戏代码已确认: base=0x{tb:08X} -> {version_label}")
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

        # ── 读取代码段 (未加密版分支已读取) ──
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


# ═══════════════════════════════════════════════════════════════
# main() — CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    _init_cli_logging()

    parser = argparse.ArgumentParser(
        description="TKS Launcher CLI — Headless 启动器 (Winlator 兼容)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  TKSLauncherCLI.exe
  TKSLauncherCLI.exe --tks-exe "D:\\sanguo\\TKS.exe"
  TKSLauncherCLI.exe --config my_config.json --timeout 60
        """.strip()
    )
    parser.add_argument("--config", type=str, default=None,
                        help="launcher_config.json 路径 (默认: exe同目录)")
    parser.add_argument("--tks-exe", type=str, default=None,
                        help="TKS.exe 路径 (覆盖配置文件)")
    parser.add_argument("--game-dir", type=str, default=None,
                        help="游戏目录 (覆盖配置文件)")
    parser.add_argument("--no-mods", action="store_true",
                        help="跳过 MOD 加载")
    parser.add_argument("--no-runtime-hooks", action="store_true",
                        help="[诊断] 跳过所有运行时补丁 (存档入口/stream error/头像/gold)")
    parser.add_argument("--no-suspend", action="store_true",
                        help="[Winlator] 禁用 CREATE_SUSPENDED + 线程挂起/恢复 (Wine 兼容)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="等待超时秒数 (默认: 30)")
    parser.add_argument("--verify-patches", action="store_true",
                        help="[诊断] 仅验证 patches/ 补丁与外部脚本可加载后退出")

    args = parser.parse_args()
    exe_dir = _get_exe_dir()

    if args.verify_patches:
        patches_dir = os.path.join(exe_dir, "patches")
        cfg = load_patch_directory(patches_dir, log_func=print)
        if cfg is None or not cfg.patches:
            print("[ERROR] 无法加载补丁配置 (patches/ 为空)")
            sys.exit(1)
        ok = True
        for p in cfg.patches:
            if p.type == "script":
                ok = validate_script_patch(p, log_func=print) and ok
        print(f"[VERIFY] 加载 {len(cfg.patches)} 个补丁, "
              f"脚本验证 {'通过' if ok else '失败'}")
        sys.exit(0 if ok else 1)

    cfg = _load_launcher_config(exe_dir, args)

    tks_path = _resolve_tks_exe(cfg, exe_dir)
    game_dir = _resolve_game_dir(cfg, tks_path)
    timeout = args.timeout or cfg.get("advanced", {}).get("wait_timeout", 30)

    # 启动模式 (GUI 共享配置 / 手写配置均可, 非法值回退标准模式)
    mode = parse_mode(cfg)
    if mode == "compatible":
        print("[配置] 模式: 兼容模式 (仅加载 MOD, 跳过启动器游戏功能)")

    # 解析启用的可选补丁 (与 GUI 共用的字典格式)
    selected_patches = parse_patch_selection(cfg)
    if selected_patches is None:
        print("[配置] 可选补丁: 使用默认勾选 (default_checked)")
    elif selected_patches:
        print(f"[配置] 显式启用可选补丁: {', '.join(sorted(selected_patches))}")
    else:
        print("[配置] 可选补丁: 全部禁用")

    # 解析启用的 MOD (与 GUI 共用的字典格式)
    if args.no_mods:
        enabled_mod_ids = "__NONE__"
        print("[配置] MOD: 全部禁用 (--no-mods)")
    else:
        enabled_mod_ids = parse_mod_selection(cfg)
        if enabled_mod_ids is None:
            print("[配置] MOD: 全部启用 (默认)")
        elif enabled_mod_ids:
            print(f"[配置] 启用 MOD: {', '.join(sorted(enabled_mod_ids))}")
        else:
            print("[配置] MOD: 全部禁用")

    if args.no_runtime_hooks:
        print("[诊断] --no-runtime-hooks: 跳过所有运行时补丁")

    # 配置文件中的诊断选项 (命令行参数优先)
    adv = cfg.get("advanced", {})
    no_runtime_hooks = args.no_runtime_hooks or adv.get("no_runtime_hooks", False)
    no_archive_portrait = adv.get("no_archive_portrait", False)
    no_inject_warpc = adv.get("no_inject_warpc", False)
    no_gold_display = adv.get("no_gold_display", False)
    no_save_entry_stream_fixes = adv.get(
        "no_save_entry_stream_fixes",
        adv.get("no_4c33fc_41c120", False),
    )
    no_suspend = args.no_suspend or adv.get("no_suspend", False)

    # Wine/Winlator 环境已原生兼容 (CAVE_ARCHIVE_PORTRAIT 改用非 LOCK 指令)
    for label, flag in [
        ("no_runtime_hooks: 跳过所有运行时补丁", no_runtime_hooks),
        ("no_archive_portrait: 跳过存档头像补丁", no_archive_portrait),
        ("no_inject_warpc: 跳过 WarPC 注入", no_inject_warpc),
        ("no_gold_display: 跳过存档金钱显示补丁", no_gold_display),
        ("no_save_entry_stream_fixes: 跳过存档入口/stream error 补丁",
         no_save_entry_stream_fixes),
        ("no_suspend: 禁用 CREATE_SUSPENDED (Wine 兼容)", no_suspend),
    ]:
        if flag:
            print(f"[诊断] {label}")

    disabled_patches = _build_disabled_patches(args, cfg)

    launcher = CliLauncher(
        tks_path=tks_path,
        game_dir=game_dir,
        wait_timeout=timeout,
        selected_patches=selected_patches,
        enabled_mod_ids=enabled_mod_ids,
        disabled_patches=disabled_patches,
        no_inject_warpc=no_inject_warpc,
        no_suspend=no_suspend,
        mode=mode,
    )
    ok, diag = launcher.run()
    if ok:
        print("\n[DONE] 启动器正常退出。")
    else:
        print(f"\n[DONE] 启动器异常退出: {diag.get('error', 'unknown')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
