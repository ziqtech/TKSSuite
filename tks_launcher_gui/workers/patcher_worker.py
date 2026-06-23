"""PatcherWorker — QThread 封装完整补丁流程, 通过 Signal 通知 UI"""
import os
import sys
import time
import struct
import ctypes
import subprocess
from datetime import datetime, timezone, timedelta

from PySide6.QtCore import QThread, Signal

from core.memory import (
    i32b, b2i32, b2u16, bhex,
    read_pm, write_pm, vp_ex,
    get_module_base, get_module_size, get_child_processes,
    find_window, get_decompressed_size,
    PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION,
    PAGE_EXECUTE_READWRITE,
    MEM_COMMIT, MEM_RESERVE,
    _OpenProcess, _CloseHandle, _VirtualAllocEx,
)
from core.scanner import parse_pattern, pattern_scan, discover_warpc_base
from core.config_loader import load_config
from core.patch_engine import (
    apply_config_patches,
    patch_4c33fc, patch_41c120, patch_archive_portrait, patch_gold_display,
)
from core.warpc_expander import (
    WARPC_BASE, WARPC_REC_SIZE, WARPC_ORIG_COUNT, WARPC_ORIG_SIZE,
    WARPC_TOTAL_ORIG_SIZE, DATA_FILE_ORIG_SIZES,
    ensure_save_directory_healthy, prepare_warpc_for_game,
    expand_warpc_buffer, inject_warpc_data,
)
from core.mod_loader import (
    scan_mods, resolve_dependencies, detect_conflicts,
    merge_mods, apply_mod_data, restore_originals,
)


class PatcherWorker(QThread):
    """后台线程：完整补丁工作流"""

    # --- 信号 ---
    log_emitted = Signal(str)
    status_changed = Signal(str, bool)  # text, is_ok
    game_window_found = Signal(int)     # game_hwnd → UI 线程创建悬浮窗
    overlay_update = Signal(str, bool)  # text, is_ok
    finished = Signal(bool, dict)       # success, diagnostics

    def __init__(self, exe_path: str, game_dir: str | None = None,
                 wait_timeout: int = 30, minimal_mode: bool = False,
                 no_cave_mode: bool = False, only_portrait: bool = False,
                 only_awk: bool = False, selected_patches: set = None):
        super().__init__()
        self.exe_path = exe_path
        self.game_dir = game_dir
        self.wait_timeout = wait_timeout
        self.minimal_mode = minimal_mode
        self.no_cave_mode = no_cave_mode
        self.only_portrait = only_portrait
        self.only_awk = only_awk
        self.selected_patches = selected_patches
        self._is_running = True

    def _log(self, msg: str):
        self.log_emitted.emit(msg)

    def run(self):
        try:
            self._do_run()
        except Exception as e:
            self._log(f"[FATAL] 未捕获异常: {e}")
            import traceback
            self._log(traceback.format_exc())
            self.finished.emit(False, {"error": str(e)})

    def _do_run(self):
        # 内部状态（模块级迁移）
        _warpc_expanded = False
        _warpc_full_data = None
        _warpc_new_buf = 0
        _truncated_files = {}

        # 确定启动器目录
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.dirname(os.path.abspath(__file__))
            exe_dir = os.path.dirname(exe_dir)  # workers/ -> root
        if not exe_dir:
            exe_dir = os.getcwd()

        self._log(f"启动器目录: {exe_dir}")
        self._log(f"工作目录: {os.getcwd()}")

        tks_path = self.exe_path
        game_dir = self.game_dir

        if game_dir:
            os.chdir(game_dir)
            self._log(f"  工作目录切换到: {game_dir}")

        self._log("========================================")
        self._log("TKS Launcher - 自动运行时补丁启动器 (PySide6 GUI)")
        self._log("========================================")

        # 加载配置
        config_path = os.path.join(exe_dir, "tks_patches.json")
        self._log(f"配置文件: {config_path} (存在={os.path.isfile(config_path)})")
        config = load_config(config_path, log_func=self._log)
        if config is None:
            self._log("[ERROR] 无法加载补丁配置, 退出")
            self.finished.emit(False, {"error": "config load failed"})
            return

        # 启动前检查
        ensure_save_directory_healthy(log_func=self._log)

        # === MOD 加载流程 ===
        mods_dir = os.path.join(exe_dir, "mods")
        self._log(f"\n=== MOD 加载 ({mods_dir}) ===")
        loaded_mods = scan_mods(mods_dir, log_func=self._log)
        if loaded_mods:
            sorted_mods = resolve_dependencies(loaded_mods, log_func=self._log)
            conflicts = detect_conflicts(sorted_mods, log_func=self._log)
            if conflicts:
                self._log(f"  [WARN] 检测到 {len(conflicts)} 个冲突, 继续加载 (后加载覆盖)")
            self._log(f"\n--- 合并 MOD 数据 ---")
            merged = merge_mods(sorted_mods, game_dir or os.getcwd(), log_func=self._log)
            if merged.file_data or merged.resource_replacements or merged.backed_up:
                self._log(f"\n--- 写入 MOD 数据 ---")
                apply_mod_data(merged, game_dir or os.getcwd(), log_func=self._log)
                self._log(f"  MOD 数据已写入, 游戏启动后将自动恢复原始文件")
            else:
                self._log(f"  MOD 无数据变更")
        else:
            self._log(f"  未发现 MOD 文件")

        expanded, full_data, truncated = prepare_warpc_for_game(log_func=self._log)
        _warpc_expanded = expanded
        _warpc_full_data = full_data
        _truncated_files = truncated

        # 启动游戏
        self._log(f"\n启动 {tks_path}...")
        try:
            tks_proc = subprocess.Popen(
                tks_path,
                cwd=os.path.dirname(os.path.abspath(tks_path)) or os.getcwd()
            )
        except Exception as e:
            self._log(f"[ERROR] 无法启动 {tks_path}: {e}")
            self.finished.emit(False, {"error": f"launch failed: {e}"})
            return
        self._log(f"  TKS.exe PID = {tks_proc.pid}")
        self.status_changed.emit("游戏已启动，等待进程就绪...", True)

        # 查找游戏窗口
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
            self.overlay_update.emit("正在等待游戏加载...", False)
        else:
            self._log("  [WARN] 未找到游戏窗口, 叠加提示不可用")

        # 等待进程就绪
        self._log(f"等待游戏进程就绪 (最多 {self.wait_timeout} 秒)...")
        target_pid = 0
        direct_mode = False
        version_label = ""
        st = time.time()
        tpid = tks_proc.pid

        while (time.time() - st) < self.wait_timeout:
            if not self._is_running:
                self._log("用户取消")
                if tks_proc.poll() is None:
                    tks_proc.kill()
                self.finished.emit(False, {"error": "cancelled"})
                return

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
                self.overlay_update.emit("正在加载游戏补丁...", False)
                time.sleep(3)
                break

            elapsed = time.time() - st
            if elapsed > 3.0 and not direct_mode:
                tb = get_module_base(tpid)
                if tb:
                    ht = _OpenProcess(PROCESS_VM_READ, False, tpid)
                    if ht:
                        psig, nr = read_pm(ht, tb, 2)
                        if nr == 2 and psig[0]==0x4D and psig[1]==0x5A:
                            target_pid = tpid; direct_mode = True
                            version_label = "TKS 未加密版 (主进程模式)"
                            self._log(f"  游戏模块已加载到主进程: base=0x{tb:08X} -> {version_label}")
                            self.overlay_update.emit("正在加载游戏补丁...", False)
                        _CloseHandle(ht)
                    if direct_mode:
                        break

            time.sleep(0.5)

        if target_pid == 0:
            self._log("[ERROR] 超时，未检测到游戏进程")
            if tks_proc.poll() is None:
                tks_proc.kill()
            self.finished.emit(False, {"error": "timeout"})
            return

        self._log(f"  版本: {version_label}")
        self._log(f"  目标 PID: {target_pid}, 直接模式: {direct_mode}")
        self.status_changed.emit(f"目标进程 PID={target_pid}，正在应用补丁...", True)

        base_addr = get_module_base(target_pid)
        if base_addr == 0:
            self._log(f"[ERROR] 无法获取目标进程 {target_pid} 的模块信息")
            if tks_proc.poll() is None:
                tks_proc.kill()
            self.finished.emit(False, {"error": "no module base"})
            return
        self._log(f"  模块基址: 0x{base_addr:08X}")

        # 读取代码段
        mod_size = get_module_size(target_pid)
        self._log(f"  模块大小: 0x{mod_size:X} ({mod_size} bytes)")

        code_start = base_addr + 0x1000
        code_size = min(mod_size - 0x1000, 0x700000 - code_start)
        code_buf = bytearray(code_size)
        hr = _OpenProcess(PROCESS_VM_READ, False, target_pid)
        if not hr:
            self._log("[ERROR] 无法打开进程读取代码段")
            if tks_proc.poll() is None:
                tks_proc.kill()
            self.finished.emit(False, {"error": "cannot read code"})
            return
        raw_buf, nr = read_pm(hr, code_start, code_size)
        _CloseHandle(hr)
        if nr <= 0:
            self._log("[ERROR] 无法读取代码段")
            if tks_proc.poll() is None:
                tks_proc.kill()
            self.finished.emit(False, {"error": "code read failed"})
            return
        code_buf[:nr] = raw_buf
        self._log(f"  代码段: 0x{code_start:08X}-0x{code_start + nr:08X} ({nr} bytes)")

        # 自动发现 WarPC BSS 基址
        fallback_base = config.variables.get("warpc_base", WARPC_BASE)
        discovered_base = discover_warpc_base(
            bytes(code_buf), code_start, int(fallback_base), log_func=self._log
        )
        config.variables["warpc_base"] = discovered_base

        # [补丁十一] GUARD 区 + 分配 WarPC 缓冲区
        warpc_base_for_caves = 0
        if _warpc_expanded and _warpc_full_data:
            import shutil
            wp = "WarPC.dat"; bp = wp + ".orig"
            if os.path.isfile(bp):
                shutil.copy2(bp, wp); os.remove(bp)
                self._log("  已恢复原始 WarPC.dat")

            ns = len(_warpc_full_data)
            hw = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
            if hw:
                GUARD_SIZE = 0x10000
                total_alloc = ns + GUARD_SIZE
                ab = _VirtualAllocEx(hw, None, total_alloc, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                if ab:
                    abv = ctypes.cast(ab, ctypes.c_void_p).value or 0
                    nb = abv + GUARD_SIZE
                    write_pm(hw, nb, _warpc_full_data)
                    _warpc_new_buf = nb; warpc_base_for_caves = nb
                    self._log(f"  WarPC 缓冲区: 0x{nb:08X} ({ns} 字节, {ns // WARPC_REC_SIZE} 角色)")
                _CloseHandle(hw)

        # 恢复其他被截断的 .dat
        import shutil
        for k in list(_truncated_files.keys()):
            if k == "WarPC.dat":
                continue
            bp = k + ".orig"
            if os.path.isfile(bp):
                shutil.copy2(bp, k); os.remove(bp)
                self._log(f"  已恢复原始 {k}")

        # 设置配置变量
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

        # 分配 cave 内存
        self.overlay_update.emit("正在应用内存补丁...", False)
        hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
        cave_addr = 0
        if hp:
            ca = _VirtualAllocEx(hp, None, 512, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
            if ca:
                cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
            _CloseHandle(hp)
        if cave_addr:
            self._log(f"  Cave 内存: 0x{cave_addr:08X} (512 bytes)")
        else:
            self._log("  [WARN] VirtualAllocEx failed, caves skipped")

        # 应用配置补丁
        self._log("\n=== 应用配置补丁 (模式扫描) ===")
        hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
        ok = False
        if hp:
            try:
                ok = apply_config_patches(
                    config, code_buf, code_start, hp,
                    warpc_base_for_caves if warpc_base_for_caves else discovered_base,
                    cave_addr, config.variables, log_func=self._log,
                    minimal_mode=self.minimal_mode, no_cave_mode=self.no_cave_mode,
                    only_portrait=self.only_portrait, only_awk=self.only_awk,
                    selected_patches=self.selected_patches,
                )
            except Exception as ex:
                self._log(f"[ERROR] ApplyConfigPatches 异常: {ex}")
                import traceback
                self._log(traceback.format_exc())
            _CloseHandle(hp)

        # WarPC 代码引用修补
        if not self.minimal_mode and _warpc_expanded and _warpc_new_buf:
            self.overlay_update.emit("正在扩展 WarPC 缓冲区...", False)
            expand_warpc_buffer(
                target_pid, base_addr, mod_size, cave_addr,
                code_buf, code_start, _warpc_new_buf, _warpc_full_data,
                log_func=self._log,
            )

        # [补丁十二~十四、十七] 运行时动态修补
        archive_cave = cave_addr + 192 if cave_addr else 0
        if not self.minimal_mode:
            patch_4c33fc(target_pid, base_addr, log_func=self._log)
            patch_41c120(target_pid, base_addr, log_func=self._log)
            patch_archive_portrait(target_pid, base_addr, archive_cave, log_func=self._log)
            patch_gold_display(target_pid, base_addr, log_func=self._log)
            inject_warpc_data(target_pid, discovered_base, _warpc_expanded, log_func=self._log)

        # 诊断 dump
        self._log("\n--- 存档索引文件内容详细 dump ---")
        for si in range(1, 10):
            ip = f"save\\{si}.sav"
            if not os.path.isfile(ip):
                self._log(f"  slot {si}: 不存在"); continue
            try:
                with open(ip, 'rb') as f:
                    idx = f.read()
                if len(idx) != 28:
                    self._log(f"  slot {si}: 大小={len(idx)} (异常)"); continue
                team = [struct.unpack('b', idx[k:k+1])[0] for k in range(6)]
                lvs = [b2i16(idx, 12 + k*2) for k in range(6)]
                self._log(f"  slot {si}: team=[{','.join(str(t) for t in team)}] levels=[{','.join('Lv'+str(l) for l in lvs)}]")
            except Exception as e:
                self._log(f"  slot {si}: 读取失败 {e}")

        # 完成
        if ok:
            self._log("\n补丁已应用！游戏正在运行。")
            self._log("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。")
            self.overlay_update.emit("补丁应用成功！游戏运行中", True)
            self.status_changed.emit("补丁应用成功，游戏运行中", True)
        else:
            self._log("\n[WARN] 部分补丁未应用成功")
            self.overlay_update.emit("补丁应用失败！", False)
            self.status_changed.emit("部分补丁未成功", False)

        time.sleep(2)
        self.overlay_update.emit("", False)

        # 等待游戏进程退出后再恢复原始文件
        # (游戏运行期间可能重新加载磁盘文件, 如 TitleMenu.gxp)
        if loaded_mods:
            self._log("\n等待游戏退出后恢复原始文件...")
            self.status_changed.emit("补丁已生效，等待游戏退出...", True)
            self._wait_game_exit(tks_proc, target_pid)
            restore_originals(game_dir or os.getcwd(), log_func=self._log)
            self._log("原始文件已恢复。")

        self.finished.emit(ok, {
            "base": base_addr,
            "cave": cave_addr,
            "warpc_expanded": _warpc_expanded,
            "new_buf": _warpc_new_buf,
        })

    def _wait_game_exit(self, tks_proc, target_pid: int):
        """等待游戏进程退出 (轮询检测, 纯 Win32 实现)"""
        # 收集需要监控的 PID
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

        while self._is_running:
            alive = False
            for pid in list(pids_to_watch):
                # 尝试打开进程, 如果失败说明已退出
                h = _OpenProcess(SYNCHRONIZE | 0x0400, False, pid)  # 0x0400 = PROCESS_QUERY_INFORMATION
                if h:
                    # 检查是否已退出 (WaitForSingleObject timeout=0)
                    ret = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
                    _CloseHandle(h)
                    if ret == WAIT_TIMEOUT:
                        alive = True
                        break
                    # ret == 0 (WAIT_OBJECT_0) 表示进程已退出
                else:
                    # OpenProcess 失败, 进程可能已退出
                    pass
            if not alive:
                break
            time.sleep(1)

        self._log("  游戏进程已退出。")

    def stop(self):
        self._is_running = False
