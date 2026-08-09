"""
TKS Launcher CLI — Headless 启动器 (Winlator 兼容)
=================================================
从 patcher_worker._do_run() 提取, 去掉所有 PySide6 依赖。
纯 Python 标准库 + ctypes, 可在 Wine/Winlator 中运行。

用法:
  python cli_launcher.py                          # 开发环境
  python cli_launcher.py --tks-exe "D:\\game\\TKS.exe"
  TKSLauncherCLI.exe                              # Nuitka 编译后

配置文件 (可选, 放在 exe 同目录):
  launcher_config.json
"""
import argparse
import ctypes
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
import traceback
from datetime import datetime

# 确保 core/ 可导入 (开发环境)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from core.config_loader import load_config
from core.tkspatch_loader import load_config_merged
from core.memory import (
    read_pm, write_pm,
    get_module_base, get_module_size, get_child_processes,
    find_window, get_decompressed_size,
    suspend_process, resume_process,
    b2i16,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    MEM_COMMIT, MEM_RESERVE,
    _OpenProcess, _CloseHandle, _VirtualAllocEx,
)
from core.mod_loader import (
    scan_mods, resolve_dependencies, detect_conflicts,
    merge_mods, apply_mod_data, restore_originals,
    expand_pak_mods,
)
from core.patch_engine import apply_config_patches
from core.scanner import discover_warpc_base, detect_exe_profile
from core.warpc_expander import (
    WARPC_BASE, WARPC_REC_SIZE, WARPC_ORIG_SIZE,
    WARPC_TOTAL_ORIG_SIZE, DATA_FILE_ORIG_SIZES,
    ensure_save_directory_healthy, prepare_warpc_for_game,
    expand_warpc_buffer, inject_warpc_data,
)
from core.tkact_expander import (
    prepare_tkact_for_game,
    restore_tkact_for_game,
)


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
    # 方法1: wine_get_version
    try:
        ntdll = ctypes.windll.ntdll
        if hasattr(ntdll, 'wine_get_version'):
            return True
    except Exception:
        pass

    # 方法2: wine_get_build_id
    try:
        ntdll = ctypes.windll.ntdll
        if hasattr(ntdll, 'wine_get_build_id'):
            return True
    except Exception:
        pass

    # 方法3: 注册表
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Wine")
        winreg.CloseKey(key)
        return True
    except Exception:
        pass

    # 方法4: 环境变量
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


def _load_launcher_config(exe_dir: str, args) -> dict:
    """加载 launcher_config.json (可选)"""
    config_path = args.config
    if not config_path:
        # 自动查找: exe 同目录
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

    # 命令行参数优先级高于配置文件
    if args.tks_exe:
        cfg.setdefault("tks_exe", {})["path"] = args.tks_exe
    if args.game_dir:
        cfg.setdefault("game", {})["dir"] = args.game_dir
    if args.no_mods:
        cfg.setdefault("mods", {})["enabled_ids"] = "__NONE__"

    return cfg


def _resolve_tks_exe(cfg: dict, exe_dir: str) -> str:
    """解析 TKS.exe 路径"""
    tks_cfg = cfg.get("tks_exe", {})
    path = tks_cfg.get("path", "TKS.exe")
    if os.path.isabs(path):
        return os.path.normpath(path)
    # 相对路径: 先相对于 exe_dir, 再相对于 cwd
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


# ═══════════════════════════════════════════════════════════════
# CliLauncher
# ═══════════════════════════════════════════════════════════════

class CliLauncher:
    """Headless 启动器 — 无 PySide6 依赖"""

    def __init__(self, tks_path: str, game_dir: str | None = None,
                 wait_timeout: int = 30,
                 selected_patches: set = None,
                 enabled_mod_ids: set = None,
                 no_runtime_hooks: bool = False,
                 no_archive_portrait: bool = False,
                 no_inject_warpc: bool = False,
                 no_gold_display: bool = False,
                 no_save_entry_stream_fixes: bool = False,
                 no_suspend: bool = False):
        self.tks_path = os.path.abspath(tks_path)
        self.game_dir = game_dir
        self.wait_timeout = wait_timeout
        self.selected_patches = selected_patches
        self.enabled_mod_ids = enabled_mod_ids
        self.no_runtime_hooks = no_runtime_hooks
        self.no_archive_portrait = no_archive_portrait
        self.no_inject_warpc = no_inject_warpc
        self.no_gold_display = no_gold_display
        self.no_save_entry_stream_fixes = no_save_entry_stream_fixes
        self.no_suspend = no_suspend
        self._is_running = True

        # 注册 Ctrl+C 处理
        self._orig_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._on_sigint)

    def _on_sigint(self, signum, frame):
        print("\n[中断] 收到 Ctrl+C, 正在退出...")
        self._is_running = False
        # 恢复默认处理 (第二次 Ctrl+C 强制退出)
        if self._orig_sigint and self._orig_sigint != signal.SIG_DFL:
            signal.signal(signal.SIGINT, self._orig_sigint)

    @staticmethod
    def _ts() -> str:
        """时间戳"""
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, msg: str):
        print(f"[{self._ts()}] {msg}")

    def run(self) -> tuple:
        """执行完整补丁流程, 返回 (success: bool, diagnostics: dict)"""
        try:
            return self._do_run()
        except Exception as e:
            self._log(f"[FATAL] 未捕获异常: {e}")
            traceback.print_exc()
            return False, {"error": str(e)}
        finally:
            signal.signal(signal.SIGINT, self._orig_sigint)

    def _do_run(self):
        # ── 内部状态 ──
        _warpc_expanded = False
        _warpc_full_data = None
        _warpc_new_buf = 0
        _truncated_files = {}
        _tkact_expanded = False

        # ── 确定 exe 目录 ──
        exe_dir = _get_exe_dir()
        if not exe_dir:
            exe_dir = os.getcwd()

        self._log(f"启动器目录: {exe_dir}")
        self._log(f"工作目录: {os.getcwd()}")

        tks_path = self.tks_path
        game_dir = self.game_dir

        if game_dir:
            os.chdir(game_dir)
            self._log(f"工作目录切换到: {game_dir}")

        self._log("=" * 40)
        self._log("TKS Launcher CLI — Headless 启动器")
        self._log("=" * 40)

        # ── 1. 加载补丁配置 (外置 .tkspatch 为唯一来源) ──
        config_path = os.path.join(exe_dir, "tks_patches.json")
        patches_dir = os.path.join(exe_dir, "patches")
        self._log(f"补丁目录: {patches_dir} (存在={os.path.isdir(patches_dir)})")
        config = load_config_merged(config_path, patches_dir, log_func=self._log)
        if config is None or not config.patches:
            self._log("[ERROR] 无法加载补丁配置 (patches/ 为空且无 tks_patches.json), 退出")
            return False, {"error": "config load failed"}

        # ── 1b. 构建选中补丁集合 (匹配 GUI 默认勾选行为) ──
        # selected_patches=None → 根据 default_checked 构建 (GUI 默认勾选的补丁)
        # selected_patches=set(...) → 用户显式指定, 直接使用
        if self.selected_patches is None:
            self.selected_patches = {
                p.id for p in config.patches if p.optional and p.default_checked
            }
            _names = ', '.join(sorted(self.selected_patches)) or "(无)"
            self._log(f"  默认启用可选补丁: {_names}")

        # ── 2. 存档健康检查 ──
        ensure_save_directory_healthy(log_func=self._log)

        # ── 3. MOD 加载流程 ──
        mods_dir = os.path.join(exe_dir, "mods")
        self._log(f"\n=== MOD 加载 ({mods_dir}) ===")
        loaded_mods = scan_mods(mods_dir, log_func=self._log)
        # MOD 包携带的启动器配置覆盖 (白名单内, 优先级最高)
        _mod_config_overrides = None

        if loaded_mods:
            if self.enabled_mod_ids is not None:
                # 特殊值 "__NONE__" 表示禁用全部 MOD
                if self.enabled_mod_ids == "__NONE__":
                    for m in loaded_mods:
                        m.enabled = False
                    self._log("  --no-mods: 已禁用全部 MOD")
                else:
                    skipped = []
                    for m in loaded_mods:
                        m.enabled = m.mod_id in self.enabled_mod_ids
                        if not m.enabled:
                            skipped.append(m.mod_id)
                    if skipped:
                        self._log(f"  用户取消勾选 {len(skipped)} 个 MOD: {', '.join(skipped)}")
            # 展开启用的 .tksmodpak
            expanded = []
            for m in loaded_mods:
                if m.enabled and m.pak_contents:
                    self._log(f"  展开合集: {m.name} ({len(m.pak_contents)} 个模组)")
                    pak_mods = expand_pak_mods(m.path, log_func=self._log)
                    for pm in pak_mods:
                        pm.enabled = True
                    expanded.extend(pak_mods)
                elif not m.pak_contents:
                    expanded.append(m)
            sorted_mods = resolve_dependencies(expanded, log_func=self._log)
            conflicts = detect_conflicts(sorted_mods, log_func=self._log)
            if conflicts:
                self._log(f"  [WARN] 检测到 {len(conflicts)} 个冲突, 继续加载 (后加载覆盖)")
            self._log(f"\n--- 合并 MOD 数据 ---")
            merged = merge_mods(sorted_mods, game_dir or os.getcwd(), log_func=self._log)
            _mod_config_overrides = merged.config_overrides
            if merged.file_data or merged.resource_replacements or merged.backed_up:
                self._log(f"\n--- 写入 MOD 数据 ---")
                apply_mod_data(merged, game_dir or os.getcwd(), log_func=self._log)
                self._log(f"  MOD 数据已写入, 游戏启动后将自动恢复原始文件")
            else:
                self._log(f"  MOD 无数据变更")
        else:
            self._log(f"  未发现 MOD 文件")

        # ── 4. WarPC/DAT 预截断 ──
        expanded, full_data, truncated = prepare_warpc_for_game(log_func=self._log)
        _warpc_expanded = expanded
        _warpc_full_data = full_data
        _truncated_files = truncated

        # ── 5. 启动游戏 ──
        # Wine/Winlator 不兼容 CREATE_SUSPENDED + SuspendThread/ResumeThread,
        # 在 Wine 下使用普通启动方式 (回退到修改前的行为)
        is_wine = _is_wine() or self.no_suspend
        if is_wine:
            if self.no_suspend and not _is_wine():
                self._log("  用户强制禁用 CREATE_SUSPENDED (--no-suspend)")
            else:
                self._log("  检测到 Wine/Winlator 环境, 使用兼容模式 (无 CREATE_SUSPENDED)")

        self._log(f"\n启动 {tks_path}...")
        if not os.path.isfile(tks_path):
            self._log(f"[ERROR] TKS.exe 不存在: {tks_path}")
            return False, {"error": f"tks_exe not found: {tks_path}"}

        _tkact_expanded = prepare_tkact_for_game(log_func=self._log)

        try:
            tks_proc = subprocess.Popen(
                tks_path,
                cwd=os.path.dirname(os.path.abspath(tks_path)) or os.getcwd(),
                creationflags=0x4 if not is_wine else 0,  # CREATE_SUSPENDED (原生Windows only)
            )
        except Exception as e:
            if _tkact_expanded:
                restore_tkact_for_game(log_func=self._log)
            self._log(f"[ERROR] 无法启动 {tks_path}: {e}")
            return False, {"error": f"launch failed: {e}"}

        self._log(f"  TKS.exe PID = {tks_proc.pid}" +
                  (" (CREATE_SUSPENDED)" if not is_wine else ""))

        # ── 6. 进程检测 ──
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
                            # 检查游戏特征 (SkimFstDlg 模式前 7 字节: A1 14 A5 4F 00 50 E8)
                            if b'\xA1\x14\xA5\x4F\x00\x50\xE8' in bytes(_buf):
                                target_pid = tks_proc.pid
                                direct_mode = True
                                version_label = "TKS 未加密版 (主进程模式, 已挂起)"
                                _need_resume_pid = tks_proc.pid
                                base_addr = _base_addr
                                mod_size = _mod_size
                                code_start = _code_start
                                code_buf = _buf
                                self._log(f"  [未加密版] 游戏代码已确认, 进程已挂起, 基址: 0x{base_addr:08X}")

        # ── 7. 加密版/后备检测 ──
        if target_pid == 0:
            if is_wine:
                # ── Wine/Winlator: 完全复刻旧版流程 (01c9bf2 之前) ──
                # 7a. 查找游戏窗口 (提供延迟让进程初始化)
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

                # 7b. 等待进程就绪 (500ms 轮询, 立即检查 SkimFstDlg 模式)
                self._log(f"等待游戏进程就绪 (最多{self.wait_timeout}秒)...")
                st = time.time()
                tpid = tks_proc.pid
                _fallback_checked = False  # 标记是否已检查过后备检测 (避免对加密壳重复读取 3MB 代码段)
                while (time.time() - st) < self.wait_timeout:
                    if not self._is_running:
                        self._log("用户取消")
                        if tks_proc.poll() is None:
                            tks_proc.kill()
                        return False, {"error": "cancelled"}

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

                    # 后备: 立即检查主进程模块 (SkimFstDlg 模式)
                    # 加密壳没有 SkimFstDlg 模式, 不会误判; 检查一次不匹配后标记, 不再重复读取
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
                                    # 检查游戏特征 (SkimFstDlg 模式前 7 字节: A1 14 A5 4F 00 50 E8)
                                    if nr > 0 and b'\xA1\x14\xA5\x4F\x00\x50\xE8' in raw[:nr]:
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
                                        # 代码段不含 SkimFstDlg 模式, 是加密壳, 后续不再重复检查
                                        _fallback_checked = True
                                        self._log(f"  主进程代码段不含游戏特征 (可能是加密壳), 等待子进程...")
                            if direct_mode:
                                break

                    time.sleep(0.5)

                if target_pid == 0:
                    self._log("[ERROR] 超时，未检测到游戏进程")
                    if tks_proc.poll() is None:
                        tks_proc.kill()
                    return False, {"error": "timeout"}

            else:
                # ── 原生 Windows: CREATE_SUSPENDED 快速检测 ──
                self._log("  未检测到游戏代码 (加密版), 恢复进程以创建子进程...")
                resume_process(tks_proc.pid)

                st = time.time()
                tpid = tks_proc.pid
                _fallback_checked = False  # 标记是否已检查过后备检测 (避免对加密壳重复读取 3MB 代码段)
                while (time.time() - st) < self.wait_timeout:
                    if not self._is_running:
                        self._log("用户取消")
                        if tks_proc.poll() is None:
                            tks_proc.kill()
                        return False, {"error": "cancelled"}

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
                        # 等待子进程主模块加载完成再挂起
                        # (子进程刚创建时模块列表可能为空, 立即挂起会导致 get_module_base 返回 0)
                        for _ in range(60):  # 最多等 3 秒
                            if get_module_base(target_pid):
                                break
                            time.sleep(0.05)
                        # 立即挂起子进程所有线程 (在 TForm1_FormCreate 之前)
                        suspended = suspend_process(target_pid)
                        self._log(f"  已挂起子进程 {suspended} 个线程")
                        _need_resume_pid = target_pid
                        break

                    # 后备: 未加密版模块加载延迟时 (CREATE_SUSPENDED 失效)
                    # 立即检查 SkimFstDlg 模式 (不延迟, 避免未加密版补丁来不及应用)
                    # 加密壳没有 SkimFstDlg 模式, 不会误判; 检查一次不匹配后标记, 不再重复读取
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
                                    # 检查游戏特征 (SkimFstDlg 模式前 7 字节: A1 14 A5 4F 00 50 E8)
                                    if nr > 0 and b'\xA1\x14\xA5\x4F\x00\x50\xE8' in raw[:nr]:
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
                                        # 代码段不含 SkimFstDlg 模式, 是加密壳, 后续不再重复检查
                                        _fallback_checked = True
                                        self._log(f"  主进程代码段不含游戏特征 (可能是加密壳), 等待子进程...")
                            if direct_mode:
                                break

                    time.sleep(0.05)

                if target_pid == 0:
                    self._log("[ERROR] 超时，未检测到游戏进程")
                    if tks_proc.poll() is None:
                        tks_proc.kill()
                    return False, {"error": "timeout"}

        self._log(f"  版本: {version_label}")
        self._log(f"  目标 PID: {target_pid}, 直接模式: {direct_mode}")

        # ── 8. 获取模块基址 + 读取代码段 (仅加密版/后备需要, 未加密版已读取) ──
        if code_buf is None:
            # 重试获取模块基址 (加密版子进程模块加载可能有延迟, 快照可能瞬时为空)
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
                return False, {"error": "no module base"}
            self._log(f"  模块基址: 0x{base_addr:08X}")

            mod_size = get_module_size(target_pid)
            self._log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")

            code_start = base_addr + 0x1000
            code_size = mod_size - 0x1000 if mod_size > 0x1000 else 0
            if code_size > 0x300000:
                code_size = 0x300000
            code_buf = bytearray(code_size)
            # 重试读取代码段 (页面可能尚未完全提交到物理内存)
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
                return False, {"error": "code read failed"}
            code_buf[:nr] = raw_buf
            self._log(f"  代码段: 0x{code_start:08X}-0x{code_start + nr:08X} ({nr} bytes)")
        else:
            self._log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")
            self._log(f"  代码段: 0x{code_start:08X}-0x{code_start + len(code_buf):08X} ({len(code_buf)} bytes)")

        # ── 10. EXE 版本指纹 ──
        _exe_profile = detect_exe_profile(tks_path, base_addr, log_func=self._log)
        if _exe_profile.name != "original":
            self._log(f"  [MOD兼容] {_exe_profile.display_name}")
            for w in _exe_profile.warnings:
                self._log(f"  [MOD兼容] {w}")
        else:
            self._log(f"  EXE 版本: 原版")

        # ── 11. 自动发现 WarPC BSS 基址 ──
        fallback_base = config.variables.get("warpc_base", WARPC_BASE)
        discovered_base = discover_warpc_base(
            bytes(code_buf), code_start, int(fallback_base), log_func=self._log
        )
        config.variables["warpc_base"] = discovered_base
        config.variables["warpc_new_base"] = discovered_base

        # ── 13. 分配 WarPC 缓冲区 ──
        warpc_base_for_caves = 0
        if _warpc_expanded and _warpc_full_data:
            wp = "WarPC.dat"
            bp = wp + ".orig"
            if os.path.isfile(bp):
                shutil.copy2(bp, wp)
                os.remove(bp)
                self._log("  已恢复原始 WarPC.dat")

            ns = len(_warpc_full_data)
            hw = _OpenProcess(
                PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                False, target_pid
            )
            if hw:
                GUARD_SIZE = 0x10000
                total_alloc = ns + GUARD_SIZE
                ab = _VirtualAllocEx(hw, None, total_alloc,
                                     MEM_COMMIT | MEM_RESERVE,
                                     PAGE_EXECUTE_READWRITE)
                if ab:
                    abv = ctypes.cast(ab, ctypes.c_void_p).value or 0
                    nb = abv + GUARD_SIZE
                    write_pm(hw, nb, _warpc_full_data)
                    _warpc_new_buf = nb
                    warpc_base_for_caves = nb
                    config.variables["warpc_new_base"] = nb
                    self._log(f"  WarPC 缓冲区: 0x{nb:08X} ({ns} 字节, "
                              f"{ns // WARPC_REC_SIZE} 角色)")
                _CloseHandle(hw)

        # 恢复其他被截断的 .dat
        for k in list(_truncated_files.keys()):
            if k == "WarPC.dat":
                continue
            bp = k + ".orig"
            if os.path.isfile(bp):
                shutil.copy2(bp, k)
                os.remove(bp)
                self._log(f"  已恢复原始 {k}")

        # ── 14. 设置配置变量 ──
        if _warpc_expanded and _warpc_full_data:
            ns = len(_warpc_full_data)
            config.variables["warpc_new_size"] = ns
            config.variables["save_new_size"] = 9200 + ns
        else:
            config.variables["warpc_new_size"] = WARPC_ORIG_SIZE
            config.variables["save_new_size"] = WARPC_TOTAL_ORIG_SIZE

        for fname in DATA_FILE_ORIG_SIZES:
            basename = os.path.splitext(fname)[0]
            vn = basename.lower() + "_actual_size"
            actual = get_decompressed_size(fname)
            config.variables[vn] = actual if actual > 0 else DATA_FILE_ORIG_SIZES[fname]

        # TKDefUnit.Dat 记录数扩容 (剧情/脚本节点扩展)。
        # 定长无压缩, 每条 16 字节; 按文件实际字节数推导条数, 下限为原版 5000。
        # 未扩容时 = 5000 → tkdefunit_count 补丁写回原值 (无副作用); 扩容后引擎按此
        # 条数分配缓冲区/读取/遍历 (sub_402E88 中 count<<4 派生)。
        _du_orig = int(config.variables.get("tkdefunit_orig_count", 5000))
        _du_count = _du_orig
        try:
            if os.path.isfile("TKDefUnit.Dat"):
                _du_count = max(_du_orig, (os.path.getsize("TKDefUnit.Dat") + 15) // 16)
        except OSError:
            pass
        config.variables["tkdefunit_new_count"] = _du_count

        # TKAct.dat 扩展大小 (定长无压缩, 每条 784 字节; 超过原版 509600 字节时
        # 由 tkact_expand 脚本补丁分配新缓冲区并重定向加载/运行时引用)。
        _tkact_orig = int(config.variables.get("tkact_orig_size", 509600))
        _tkact_rec = int(config.variables.get("tkact_rec_size", 784))
        _tkact_new = _tkact_orig
        try:
            if os.path.isfile("TKAct.dat"):
                _tkact_path = "TKAct.dat.expanded"
                if not os.path.isfile(_tkact_path):
                    _tkact_path = "TKAct.dat"
                _tkact_sz = os.path.getsize(_tkact_path)
                if _tkact_sz % _tkact_rec == 0:
                    _tkact_new = max(_tkact_orig, _tkact_sz)
        except OSError:
            pass
        config.variables["tkact_new_size"] = _tkact_new

        # ── 15. 分配 cave 内存 ──
        hp = _OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False, target_pid
        )
        cave_addr = 0
        if hp:
            ca = _VirtualAllocEx(hp, None, 1024,
                                 MEM_COMMIT | MEM_RESERVE,
                                 PAGE_EXECUTE_READWRITE)
            if ca:
                cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
        if cave_addr:
            self._log(f"  Cave 内存: 0x{cave_addr:08X} (1024 bytes)")
        else:
            self._log("  [WARN] VirtualAllocEx failed, caves skipped")

        # ── 16. 应用配置补丁 ──
        self._log("\n=== 应用配置补丁 (模式扫描) ===")
        config.variables["_target_pid"] = target_pid
        disabled_patches = set()
        if self.no_runtime_hooks:
            disabled_patches.update({
                "save_entry_check_fix",
                "save_stream_error_fix",
                "archive_portrait",
                "gold_display",
                "xiaotan_defend_glow",
                "xiaotan_disable_companion",
            })
        if self.no_save_entry_stream_fixes:
            disabled_patches.update({
                "save_entry_check_fix",
                "save_stream_error_fix",
            })
        if self.no_archive_portrait:
            disabled_patches.add("archive_portrait")
        if self.no_gold_display:
            disabled_patches.add("gold_display")
        ok = False
        try:
            ok = apply_config_patches(
                config, code_buf, code_start, base_addr, hp,
                warpc_base_for_caves if warpc_base_for_caves else discovered_base,
                cave_addr, config.variables, log_func=self._log,
                selected_patches=self.selected_patches,
                exe_profile=_exe_profile,
                disabled_patches=disabled_patches or None,
                config_overrides=_mod_config_overrides,
            )
        except Exception as ex:
            self._log(f"[ERROR] ApplyConfigPatches 异常: {ex}")
            traceback.print_exc()
        if hp:
            _CloseHandle(hp)

        # ── 17. WarPC 代码引用修补 ──
        if _warpc_expanded and _warpc_new_buf:
            self._log("正在扩展 WarPC 缓冲区...")
            expand_warpc_buffer(
                target_pid, base_addr, mod_size, cave_addr,
                code_buf, code_start, _warpc_new_buf, _warpc_full_data,
                log_func=self._log,
                exclude_ranges=_exe_profile.extra_section_ranges if _exe_profile else None,
                warpc_base=discovered_base,
                warpc_rec_size=int(config.variables.get("warpc_rec_size", WARPC_REC_SIZE)),
            )

        # ── 18. 运行时动态修补 ──
        if self.no_runtime_hooks:
            self._log("\n=== 跳过运行时补丁 (no_runtime_hooks) ===")
        else:
            # WarPC 数据注入
            if self.no_inject_warpc:
                self._log("  [inject_warpc_data] 跳过 (no_inject_warpc)")
            else:
                inject_warpc_data(target_pid, discovered_base, _warpc_expanded, log_func=self._log)

        # ── 19. 诊断 dump ──
        self._log("\n--- 存档索引文件内容 dump ---")
        for si in range(1, 10):
            ip = f"save\\{si}.sav"
            if not os.path.isfile(ip):
                self._log(f"  slot {si}: 不存在")
                continue
            try:
                with open(ip, 'rb') as f:
                    idx = f.read()
                if len(idx) != 28:
                    self._log(f"  slot {si}: 大小={len(idx)} (异常)")
                    continue
                team = [struct.unpack('b', idx[k:k + 1])[0] for k in range(6)]
                lvs = [b2i16(idx, 12 + k * 2) for k in range(6)]
                self._log(f"  slot {si}: team=[{','.join(str(t) for t in team)}] "
                          f"levels=[{','.join('Lv' + str(l) for l in lvs)}]")
            except Exception as e:
                self._log(f"  slot {si}: 读取失败 {e}")

        # ── 19b. 恢复挂起的进程 (所有补丁已应用完毕) ──
        if _need_resume_pid:
            resumed = resume_process(_need_resume_pid)
            self._log(f"\n已恢复进程 PID={_need_resume_pid} ({resumed} 个线程)")
            _need_resume_pid = 0

        # ── 20. 完成提示 ──
        if ok:
            self._log("\n补丁已应用！游戏正在运行。")
            self._log("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。")
        else:
            self._log("\n[WARN] 部分补丁未应用成功")

        # ── 22. 等待游戏退出 ──
        self._log("\n等待游戏退出...")
        self._wait_game_exit(tks_proc, target_pid)

        # ── 23. 恢复 MOD 原始文件 ──
        if loaded_mods:
            restore_originals(game_dir or os.getcwd(), log_func=self._log)
            self._log("原始文件已恢复。")

        if _tkact_expanded:
            restore_tkact_for_game(log_func=self._log)

        self._log("启动器退出。")
        return ok, {
            "base": base_addr,
            "cave": cave_addr,
            "warpc_expanded": _warpc_expanded,
            "new_buf": _warpc_new_buf,
        }

    def _wait_game_exit(self, tks_proc, target_pid: int):
        """等待游戏进程退出 (已移除 portrait 看门狗)。"""
        pids_to_watch = set()
        if tks_proc and tks_proc.poll() is None:
            pids_to_watch.add(tks_proc.pid)
        if target_pid:
            pids_to_watch.add(target_pid)

        if not pids_to_watch:
            return

        self._log(f"  监控进程: {pids_to_watch}")
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 258
        POLL_INTERVAL = 0.5

        while self._is_running:
            alive = False
            for pid in list(pids_to_watch):
                h = _OpenProcess(SYNCHRONIZE | 0x0400, False, pid)
                if h:
                    ret = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
                    _CloseHandle(h)
                    if ret == WAIT_TIMEOUT:
                        alive = True
                        break
            if not alive:
                break
            time.sleep(POLL_INTERVAL)

        self._log("  游戏进程已退出。")


# ═══════════════════════════════════════════════════════════════
# main() — CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
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
        from core.patch_engine import validate_script_patch
        patches_dir = os.path.join(exe_dir, "patches")
        config_path = os.path.join(exe_dir, "tks_patches.json")
        cfg = load_config_merged(config_path, patches_dir, log_func=print)
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

    # 解析启用的可选补丁
    # None  = 配置未指定 → _do_run 中根据 default_checked 构建 (匹配 GUI 默认勾选行为)
    # set() = 配置显式指定 (可为空集 = 禁用全部可选补丁)
    selected_patches = None
    patches_cfg = cfg.get("patches", {})
    enabled_list = patches_cfg.get("enabled", None)
    if enabled_list is not None:
        selected_patches = set(enabled_list)
        if selected_patches:
            print(f"[配置] 显式启用可选补丁: {', '.join(sorted(selected_patches))}")
        else:
            print("[配置] 可选补丁: 全部禁用 (enabled=[])")
    else:
        print("[配置] 可选补丁: 使用默认勾选 (default_checked)")

    # 解析启用的 MOD
    enabled_mod_ids = None
    mods_cfg = cfg.get("mods", {})
    mod_ids_list = mods_cfg.get("enabled_ids", [])
    if args.no_mods:
        enabled_mod_ids = "__NONE__"
        print("[配置] MOD: 全部禁用 (--no-mods)")
    elif mod_ids_list:
        enabled_mod_ids = set(mod_ids_list)
        print(f"[配置] 启用 MOD: {', '.join(sorted(enabled_mod_ids))}")
    else:
        print("[配置] MOD: 全部启用 (默认)")

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

    launcher = CliLauncher(
        tks_path=tks_path,
        game_dir=game_dir,
        wait_timeout=timeout,
        selected_patches=selected_patches,
        enabled_mod_ids=enabled_mod_ids,
        no_runtime_hooks=no_runtime_hooks,
        no_archive_portrait=no_archive_portrait,
        no_inject_warpc=no_inject_warpc,
        no_gold_display=no_gold_display,
        no_save_entry_stream_fixes=no_save_entry_stream_fixes,
        no_suspend=no_suspend,
    )
    ok, diag = launcher.run()
    if ok:
        print("\n[DONE] 启动器正常退出。")
    else:
        print(f"\n[DONE] 启动器异常退出: {diag.get('error', 'unknown')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
