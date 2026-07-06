"""PatcherWorker — QThread 封装完整补丁流程, 通过 Signal 通知 UI"""
import os
import sys
import time
import struct
import ctypes
import shutil
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
from core.scanner import parse_pattern, pattern_scan, discover_warpc_base, detect_exe_profile, detect_exe_profile_runtime
from core.config_loader import load_config
from core.patch_engine import (
    apply_config_patches,
    patch_4c33fc, patch_41c120, patch_archive_portrait, patch_gold_display,
    find_load_hook_points, hook_save_load_portrait,
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
    expand_pak_mods,
)


class PatcherWorker(QThread):
    """后台线程：完整补丁工作流"""

    # --- 信号 ---
    log_emitted = Signal(str)
    status_changed = Signal(str, bool)  # text, is_ok
    game_window_found = Signal(int)     # game_hwnd → UI 线程创建悬浮窗
    overlay_update = Signal(str, bool)  # text, is_ok
    finished = Signal(bool, dict)       # success, diagnostics
    profile_detected = Signal(str)      # profile display_name → UI 显示版本信息

    def __init__(self, exe_path: str, game_dir: str | None = None,
                 wait_timeout: int = 30, minimal_mode: bool = False,
                 no_cave_mode: bool = False, only_portrait: bool = False,
                 only_awk: bool = False, selected_patches: set = None,
                 enabled_mod_ids: set = None, selected_tool: str = ""):
        super().__init__()
        self.exe_path = exe_path
        self.game_dir = game_dir
        self.wait_timeout = wait_timeout
        self.minimal_mode = minimal_mode
        self.no_cave_mode = no_cave_mode
        self.only_portrait = only_portrait
        self.only_awk = only_awk
        self.selected_patches = selected_patches
        self.enabled_mod_ids = enabled_mod_ids
        self.selected_tool = selected_tool
        self._is_running = True
        # 辅助工具注入追踪: {相对路径: True=新建 | False=覆盖已有}
        self._tool_injected_files: dict[str, bool] = {}

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
        if "__compiled__" in globals():
            from editor_utils.runtime_bootstrap import get_app_dir
            exe_dir = get_app_dir()
        else:
            exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # workers/ -> root
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
        # 按 UI 勾选状态过滤: 仅启用勾选的 MOD，未勾选的跳过
        if loaded_mods:
            if self.enabled_mod_ids is not None:
                skipped = []
                for m in loaded_mods:
                    m.enabled = m.mod_id in self.enabled_mod_ids
                    if not m.enabled:
                        skipped.append(m.mod_id)
                if skipped:
                    self._log(f"  用户取消勾选 {len(skipped)} 个 MOD: {', '.join(skipped)}")
            # 展开启用的 .tksmodpak 合集，将其内含的 .tksmod 加入加载列表
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
            # resolve_dependencies 内部按 m.enabled 过滤，未勾选的自动跳过
            sorted_mods = resolve_dependencies(expanded, log_func=self._log)
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

        # === 辅助工具注入 ===
        self._inject_tool_files(exe_dir, game_dir or os.getcwd())

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
        # 安全上限 3MB: 过大会触及 BSS 未映射页导致 ReadProcessMemory 整体失败
        code_size = mod_size - 0x1000 if mod_size > 0x1000 else 0
        if code_size > 0x300000:
            code_size = 0x300000
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

        # === EXE 版本指纹识别 (Task 1: 第三方 MOD 兼容) ===
        _exe_profile = detect_exe_profile(tks_path, base_addr, log_func=self._log)
        if _exe_profile.name != "original":
            self.profile_detected.emit(_exe_profile.display_name)
            for w in _exe_profile.warnings:
                self._log(f"  [MOD兼容] {w}")
            self.status_changed.emit(f"检测到: {_exe_profile.display_name}", True)
        else:
            self._log(f"  EXE 版本: 原版")

        # 自动发现 WarPC BSS 基址
        fallback_base = config.variables.get("warpc_base", WARPC_BASE)
        discovered_base = discover_warpc_base(
            bytes(code_buf), code_start, int(fallback_base), log_func=self._log
        )
        config.variables["warpc_base"] = discovered_base

        # [补丁十八] 在原始代码上定位存档加载函数的 Move 调用 (必须在任何常量/地址修补之前)
        _load_hook_rvas = find_load_hook_points(
            bytes(code_buf), discovered_base, WARPC_ORIG_SIZE, log_func=self._log
        )

        # [补丁十一] GUARD 区 + 分配 WarPC 缓冲区
        warpc_base_for_caves = 0
        if _warpc_expanded and _warpc_full_data:
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

        # 分配 cave 内存 + 应用配置补丁 (共用同一句柄)
        self.overlay_update.emit("正在应用内存补丁...", False)
        hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
        cave_addr = 0
        if hp:
            ca = _VirtualAllocEx(hp, None, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
            if ca:
                cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
        if cave_addr:
            self._log(f"  Cave 内存: 0x{cave_addr:08X} (1024 bytes)")
        else:
            self._log("  [WARN] VirtualAllocEx failed, caves skipped")

        # 应用配置补丁
        self._log("\n=== 应用配置补丁 (模式扫描) ===")
        config.variables["_target_pid"] = target_pid
        ok = False
        try:
            ok = apply_config_patches(
                config, code_buf, code_start, base_addr, hp,
                warpc_base_for_caves if warpc_base_for_caves else discovered_base,
                cave_addr, config.variables, log_func=self._log,
                minimal_mode=self.minimal_mode, no_cave_mode=self.no_cave_mode,
                only_portrait=self.only_portrait, only_awk=self.only_awk,
                selected_patches=self.selected_patches,
                exe_profile=_exe_profile,
            )
        except Exception as ex:
            self._log(f"[ERROR] ApplyConfigPatches 异常: {ex}")
            import traceback
            self._log(traceback.format_exc())
        if hp:
            _CloseHandle(hp)

        # WarPC 代码引用修补
        if not self.minimal_mode and _warpc_expanded and _warpc_new_buf:
            self.overlay_update.emit("正在扩展 WarPC 缓冲区...", False)
            expand_warpc_buffer(
                target_pid, base_addr, mod_size, cave_addr,
                code_buf, code_start, _warpc_new_buf, _warpc_full_data,
                log_func=self._log,
                exclude_ranges=_exe_profile.extra_section_ranges if _exe_profile else None,
            )

        # [补丁十二~十四、十七] 运行时动态修补
        # archive_portrait 独立于 cave_hook 系统, 自开句柄, 避免与召唤洞穴交互
        if not self.minimal_mode:
            patch_4c33fc(target_pid, base_addr, log_func=self._log)
            patch_41c120(target_pid, base_addr, log_func=self._log)
            archive_cave = cave_addr + 192 if cave_addr else 0
            patch_archive_portrait(target_pid, base_addr, archive_cave,
                                   warpc_base_for_caves if warpc_base_for_caves else discovered_base,
                                   log_func=self._log)
            patch_gold_display(target_pid, base_addr, log_func=self._log)
            inject_warpc_data(target_pid, discovered_base, _warpc_expanded, log_func=self._log)

            # [补丁十八] 存档加载后自动重注入头像数据
            if _load_hook_rvas:
                # 从 WarPC.dat 读取完整 mod 数据作为重注入源
                from core.lzss import lzss_decompress
                _wp_file = "WarPC.dat"
                _wp_orig = _wp_file + ".orig"
                _reinject_src = _wp_orig if os.path.isfile(_wp_orig) else _wp_file
                if os.path.isfile(_reinject_src):
                    with open(_reinject_src, 'rb') as _f:
                        _wp_dec = lzss_decompress(_f.read())
                    _wp_count = len(_wp_dec) // WARPC_REC_SIZE
                    _active_base = warpc_base_for_caves if warpc_base_for_caves else discovered_base
                    hook_save_load_portrait(
                        target_pid, base_addr, code_buf, code_start,
                        cave_addr, _active_base, _wp_dec, _wp_count,
                        _load_hook_rvas, log_func=self._log
                    )
                else:
                    self._log("  [补丁十八] WarPC.dat 不存在, 跳过重注入 hook")

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

        # 构建 portrait 看门狗数据 (用于游戏运行期间持续保护)
        _wd_params = None
        if not self.minimal_mode:
            _wd_params = self._build_portrait_watchdog_params(
                target_pid,
                warpc_base_for_caves if warpc_base_for_caves else discovered_base,
            )

        # 等待游戏进程退出 (含 portrait 看门狗)
        # (游戏运行期间可能重新加载磁盘文件, 如 TitleMenu.gxp)
        self._log("\n等待游戏退出...")
        self.status_changed.emit("补丁已生效，等待游戏退出...", True)
        self._wait_game_exit_with_watchdog(tks_proc, target_pid, _wd_params)

        if loaded_mods:
            restore_originals(game_dir or os.getcwd(), log_func=self._log)
            self._log("原始文件已恢复。")

        # === 辅助工具清理 ===
        self._remove_tool_files(game_dir or os.getcwd())

        self.finished.emit(ok, {
            "base": base_addr,
            "cave": cave_addr,
            "warpc_expanded": _warpc_expanded,
            "new_buf": _warpc_new_buf,
        })

    def _build_portrait_watchdog_params(self, target_pid: int, warpc_base: int):
        """
        从 WarPC.dat 构建 portrait 看门狗所需的重注入参数。
        返回 dict 或 None (无需看门狗时)。
        """
        from core.lzss import lzss_decompress
        wp_file = "WarPC.dat"
        wp_orig = wp_file + ".orig"
        src = wp_orig if os.path.isfile(wp_orig) else wp_file
        if not os.path.isfile(src):
            return None

        with open(src, 'rb') as f:
            dec = lzss_decompress(f.read())
        char_count = len(dec) // WARPC_REC_SIZE
        if char_count == 0:
            return None

        # 构建 (offset, dword) 写入列表 + 哨兵
        entries = []  # [(bss_offset, dword_value), ...]
        sentinel_offset = -1
        sentinel_value = 0
        for i in range(char_count):
            bo = i * WARPC_REC_SIZE
            if bo + 524 > len(dec):
                break
            w260 = int.from_bytes(dec[bo + 520:bo + 522], 'little')
            w261 = int.from_bytes(dec[bo + 522:bo + 524], 'little')
            dw = w260 | (w261 << 16)
            if dw:
                bss_off = bo + 520  # field_0x208 在 BSS 内的偏移
                entries.append((bss_off, dw))
                if sentinel_offset < 0:
                    sentinel_offset = bss_off
                    sentinel_value = dw

        if not entries or sentinel_offset < 0:
            self._log("  [看门狗] 无自定义头像数据, 跳过")
            return None

        self._log(f"  [看门狗] 已构建重注入表: {len(entries)} 条, 哨兵偏移=0x{sentinel_offset:X}")
        return {
            "pid": target_pid,
            "warpc_base": warpc_base,
            "entries": entries,
            "sentinel_offset": sentinel_offset,
            "sentinel_value": sentinel_value,
        }

    def _wait_game_exit_with_watchdog(self, tks_proc, target_pid: int, wd_params):
        """
        等待游戏进程退出, 同时运行 portrait 看门狗。
        每 500ms 检测哨兵值, 若被清零则重新注入全部自定义头像数据。
        """
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
        POLL_INTERVAL = 0.5  # 500ms

        reinject_count = 0

        while self._is_running:
            # --- 进程存活检查 ---
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

            # --- Portrait 看门狗: 哨兵检测 + 重注入 ---
            if wd_params:
                self._watchdog_check_and_reinject(wd_params)

            time.sleep(POLL_INTERVAL)

        self._log("  游戏进程已退出。")

    def _watchdog_check_and_reinject(self, wd):
        """
        检查哨兵值, 若被清零则重新注入所有 portrait 条目。
        使用单次 OpenProcess → 检测 + 写入 → CloseHandle, 最小化开销。
        """
        hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | 0x0008, False, wd["pid"])
        if not hp:
            return

        warpc_base = wd["warpc_base"]
        sentinel_addr = warpc_base + wd["sentinel_offset"]

        # 读取哨兵 (4 字节)
        buf, nr = read_pm(hp, sentinel_addr, 4)
        if nr < 4:
            _CloseHandle(hp)
            return

        current = int.from_bytes(buf[:4], 'little')
        if current == wd["sentinel_value"]:
            # 未被覆盖, 无需操作
            _CloseHandle(hp)
            return

        # 哨兵值变化 → 存档已加载, 重新注入所有条目
        self._log(f"  [看门狗] 检测到存档加载 (哨兵 0x{current:08X} != 0x{wd['sentinel_value']:08X}), 重注入...")
        patched = 0
        for bss_off, dw in wd["entries"]:
            addr = warpc_base + bss_off
            nw = write_pm(hp, addr, struct.pack('<I', dw))
            if nw == 4:
                patched += 1

        _CloseHandle(hp)
        self._log(f"  [看门狗] 重注入完成: {patched}/{len(wd['entries'])} 条")
        self.overlay_update.emit(f"头像数据已恢复 ({patched}条)", True)

    def stop(self):
        self._is_running = False

    # ────────────────────────────────────────────────
    # 辅助工具：注入 / 清理
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
            # 计算相对于 tool_src 的路径
            rel_root = os.path.relpath(root, tool_src)
            for fname in files:
                src_file = os.path.join(root, fname)
                rel_path = os.path.join(rel_root, fname) if rel_root != "." else fname
                dst_file = os.path.join(game_dir, rel_path)

                # 确保目标目录存在
                dst_dir = os.path.dirname(dst_file)
                if not os.path.isdir(dst_dir):
                    os.makedirs(dst_dir, exist_ok=True)
                    self._log(f"  创建目录: {os.path.relpath(dst_dir, game_dir)}")

                # 记录是否为新文件；若已存在则备份为 .toolbak
                is_new = not os.path.isfile(dst_file)
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
                # 新建的文件 — 直接删除
                if os.path.isfile(dst_file):
                    try:
                        os.remove(dst_file)
                        removed += 1
                        self._log(f"  [删除] {rel_path}")
                    except Exception as e:
                        self._log(f"  [ERROR] 删除 {rel_path} 失败: {e}")
            else:
                # 被覆盖的文件 — 从 .toolbak 恢复
                bak = dst_file + ".toolbak"
                if os.path.isfile(bak):
                    try:
                        shutil.copy2(bak, dst_file)
                        os.remove(bak)
                        removed += 1
                        self._log(f"  [恢复] {rel_path}")
                    except Exception as e:
                        self._log(f"  [ERROR] 恢复 {rel_path} 失败: {e}")
            # 记录需要检查的空目录
            rel_dir = os.path.dirname(rel_path)
            if rel_dir:
                restored_dirs.add(rel_dir)

        # 尝试删除辅助工具创建的空目录（从深到浅）
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
