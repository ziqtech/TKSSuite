"""启动器核心流水线 — 供 GUI Worker 与 CLI 共用。

Phase 4 引入。从 `patcher_worker._do_run()` 与 `cli_launcher._do_run()` 提取
共享逻辑, 消除两份 ~700 行的复制粘贴。

设计原则:
- 纯逻辑, 无 PySide6 依赖
- 通过回调函数 (log/status/overlay) 解耦 GUI 通知
- GUI 特有逻辑 (tool 注入、TKS.exe MOD 替换) 留在 worker
- CLI 特有逻辑 (Wine 检测、--no-X 诊断开关) 留在 cli_launcher
- 游戏进程拉起 + 子进程检测也留在调用方, 因 GUI/CLI/Wine 三路径行为差异较大

调用方契约:
- 流水线开始前: 调用方应已完成 `Popen(tks_path)` 与目标进程检测
  (返回 `target_pid`, `direct_mode`, `version_label`, `_need_resume_pid`)
- 流水线接受已读出的 `code_buf`, `code_start`, `base_addr`, `mod_size`
- 流水线结束后: 调用方负责等待游戏退出 + MOD 还原 + 工具清理
"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .config_loader import PatchConfig, PatchRuntimeState, PatchSettings
from .mod_loader import (
    allowed_mod_configs, apply_mod_data, detect_conflicts, expand_pak_mods,
    merge_mods, resolve_dependencies, restore_originals, scan_mods,
)
from .patch_engine import apply_config_patches
from .patch_plan import PatchPlanError, build_patch_plan, validate_runtime_plan
from .scanner import detect_exe_profile, discover_warpc_base
from .tkact_expander import (
    prepare_tkact_for_game, restore_tkact_for_game,
)
from .warpc_expander import (
    DATA_FILE_ORIG_SIZES, WARPC_BASE, WARPC_ORIG_SIZE,
    WARPC_REC_SIZE,
    ensure_save_directory_healthy, expand_warpc_buffer,
    inject_warpc_data, prepare_warpc_for_game, restore_prepared_dats,
)
from .memory import (
    b2i16, get_decompressed_size,
    PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE,
    PAGE_EXECUTE_READWRITE, MEM_COMMIT, MEM_RESERVE,
    _CloseHandle, _OpenProcess, _VirtualAllocEx,
)


# 回调签名
LogFunc = Callable[[str], None]
StatusFunc = Callable[[str, bool], None]   # text, is_ok
OverlayFunc = Callable[[str, bool], None]   # text, is_ok


@dataclass
class PipelineConfig:
    """流水线输入参数。

    涵盖 GUI Worker 与 CLI 共用的可配置项, 不含 GUI/CLI 私有开关
    (minimal_mode, no_runtime_hooks 等保留在调用方, 由 disabled_patches
    间接表达)。
    """
    exe_path: str
    exe_dir: str
    game_dir: Optional[str] = None
    patches_dir: Optional[str] = None
    mods_dir: Optional[str] = None
    selected_patches: Optional[Set[str]] = None
    enabled_mod_ids: Optional[Any] = None  # set | "__NONE__" | None
    disabled_patches: Optional[Set[str]] = None
    # standard: 应用启动器游戏功能；compatible: 只处理可独立加载的 MOD。
    mode: str = "standard"


@dataclass
class PipelineResult:
    """流水线输出诊断信息。"""
    success: bool = False
    base_addr: int = 0
    mod_size: int = 0
    code_start: int = 0
    code_size: int = 0
    cave_addr: int = 0
    cave_budget: int = 0
    warpc_expanded: bool = False
    warpc_new_buf: int = 0
    warpc_new_base: int = 0
    profile_name: str = "original"
    profile_display: str = "原版"
    loaded_mods: List[str] = field(default_factory=list)
    applied_patch_count: int = 0
    skipped_patch_count: int = 0
    error: str = ""
    mode: str = "standard"
    process_started: bool = False
    patches_status: str = "not_started"
    mods_loaded_count: int = 0
    mods_failed_count: int = 0
    tool_status: str = "not_started"
    cleanup_status: str = "pending"
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "base": self.base_addr,
            "cave": self.cave_addr,
            "cave_budget": self.cave_budget,
            "warpc_expanded": self.warpc_expanded,
            "new_buf": self.warpc_new_buf,
            "profile_name": self.profile_name,
            "applied_patch_count": self.applied_patch_count,
            "error": self.error,
            "mode": self.mode,
            "process_started": self.process_started,
            "patches_status": self.patches_status,
            "mods_loaded_count": self.mods_loaded_count,
            "mods_failed_count": self.mods_failed_count,
            "tool_status": self.tool_status,
            "cleanup_status": self.cleanup_status,
            "warnings": list(self.warnings),
        }


class PatcherPipeline:
    """共享补丁流水线。

    用法:
        pipeline = PatcherPipeline(cfg, log=..., status=..., overlay=...)
        result = pipeline.run_pre_launch()        # 加载配置 + MOD + 预截断
        # ... 调用方启动游戏 + 进程检测 ...
        result = pipeline.run_post_launch(
            target_pid=..., code_buf=..., code_start=..., base_addr=..., mod_size=...,
            need_resume_pid=...,
        )
        # ... 调用方等待游戏退出 ...
        pipeline.cleanup()

    所有方法返回 PipelineResult, 调用方据此决定是否继续。
    """

    def __init__(self, cfg: PipelineConfig,
                 log: LogFunc,
                 status: Optional[StatusFunc] = None,
                 overlay: Optional[OverlayFunc] = None):
        self.cfg = cfg
        self.log = log or (lambda x: None)
        self.status = status or (lambda *_: None)
        self.overlay = overlay or (lambda *_: None)
        self.result = PipelineResult()
        self.result.mode = cfg.mode if cfg.mode in {"standard", "compatible"} else "standard"
        self.settings = PatchSettings()
        self.runtime = PatchRuntimeState()

        # 内部状态 (在 run_pre_launch / run_post_launch 中填充)
        self.config: Optional[PatchConfig] = None
        self.patch_plan = None
        self._mod_config_overrides: Optional[Dict[str, Any]] = None
        self.loaded_mods: List = []
        self._warpc_expanded: bool = False
        self._warpc_full_data: Optional[bytes] = None
        self._truncated_files: Dict = {}
        self._warpc_new_buf: int = 0
        self._tkact_expanded: bool = False
        self._warpc_base_for_caves: int = 0
        self._discovered_base: int = 0

    # ═══════════════════════════════════════════════════════════════
    # 阶段 1: 启动前准备 (config / MOD / WarPC / TKAct 截断)
    # ═══════════════════════════════════════════════════════════════

    def run_pre_launch(self) -> PipelineResult:
        """执行启动前的所有准备工作。

        包含: 加载配置 + 存档健康检查 + MOD 加载 + WarPC/TKAct 预截断。
        GUI 在这一步可以显示进度条, CLI 可以直接 print。
        """
        # 切换工作目录
        if self.cfg.game_dir:
            try:
                os.chdir(self.cfg.game_dir)
                self.log(f"  工作目录切换到: {self.cfg.game_dir}")
            except OSError as e:
                self.log(f"  [ERROR] 切换工作目录失败: {e}")
                self.result.error = f"chdir failed: {e}"
                return self.result

        compatible_mode = self.result.mode == "compatible"

        # 兼容模式不读取启动器补丁配置作为执行依据，但仍扫描 MOD。
        patches_dir = self.cfg.patches_dir or os.path.join(self.cfg.exe_dir, "patches")
        self.log(f"补丁目录: {patches_dir} (存在={os.path.isdir(patches_dir)})")

        from .tkspatch_loader import load_patch_directory
        self.config = load_patch_directory(patches_dir, log_func=self.log)
        if not compatible_mode and (self.config is None or not self.config.patches):
            self.log("[ERROR] 无法加载补丁配置 (patches/ 不存在或为空), 退出")
            self.result.error = "config load failed"
            return self.result
        if compatible_mode:
            self.log("兼容模式: 跳过启动器游戏功能补丁")

        if not compatible_mode:
            restore_prepared_dats(log_func=self.log)
            restore_tkact_for_game(log_func=self.log)

        # 存档健康检查
        ensure_save_directory_healthy(log_func=self.log)

        # MOD 加载
        mods_dir = self.cfg.mods_dir or os.path.join(self.cfg.exe_dir, "mods")
        self._load_mods(mods_dir)

        if compatible_mode:
            self.log("兼容模式: 跳过 WarPC/TKAct 启动器数据扩展")
        else:
            try:
                self.patch_plan = build_patch_plan(
                    self.config.patches, selected=self.cfg.selected_patches,
                    disabled=self.cfg.disabled_patches, log_func=self.log)
            except Exception as exc:
                self.log(f"[ERROR] 补丁计划准备失败: {exc}")
                self.result.error = str(exc)
                self.result.patches_status = "blocked"
                self.cleanup()
                return self.result
            # WarPC / DAT 预截断
            self._warpc_expanded, self._warpc_full_data, self._truncated_files = (
                prepare_warpc_for_game(log_func=self.log)
            )

            # TKAct 预截断
            self._tkact_expanded = prepare_tkact_for_game(log_func=self.log)

        return self.result

    # ═══════════════════════════════════════════════════════════════
    # 阶段 2: 应用补丁 (目标进程已挂起, code_buf 已读取)
    # ═══════════════════════════════════════════════════════════════

    def run_post_launch(self, target_pid: int,
                        code_buf: bytearray, code_start: int,
                        base_addr: int, mod_size: int,
                        need_resume_pid: int = 0,
                        tks_exe_replaced: bool = False) -> PipelineResult:
        """应用补丁到目标进程。

        Args:
            target_pid: 已挂起的目标进程 PID
            code_buf:   已读取的代码段缓冲 (会被 mutate)
            code_start: 代码段绝对起始地址
            base_addr:  模块基址
            mod_size:   模块大小
            need_resume_pid: 需要最后 resume 的 PID (0 = 不需要)
            tks_exe_replaced: GUI 侧是否已替换 TKS.exe (用于诊断提示)
        """
        if self.result.mode == "compatible":
            self.result.patches_status = "skipped"
            self.result.success = True
            self.log("兼容模式: 不执行目标进程内存补丁")
            return self.result

        if self.config is None:
            self.log("[ERROR] run_post_launch 调用前必须先 run_pre_launch")
            self.result.error = "pre_launch not called"
            return self.result

        self.result.base_addr = base_addr
        self.result.mod_size = mod_size
        self.result.code_start = code_start
        self.result.code_size = len(code_buf)

        # ── EXE 版本指纹识别 (Phase 13: 优先加载持久化缓存) ──
        from .scanner import ExeProfileCache
        exe_profile = ExeProfileCache.load_or_detect(
            self.cfg.exe_path, base_addr, log_func=self.log)
        self.result.profile_name = exe_profile.name
        self.result.profile_display = exe_profile.display_name
        if exe_profile.name != "original":
            self.log(f"  [MOD兼容] {exe_profile.display_name}")
            for w in exe_profile.warnings:
                self.log(f"  [MOD兼容] {w}")
            self.status(f"检测到游戏版本: {exe_profile.display_name}", True)
        else:
            self.log(f"  EXE 版本: 原版")

        try:
            validate_runtime_plan(self.patch_plan, code_buf, exe_profile)
        except ValueError as exc:
            self.result.error = str(exc)
            self.result.patches_status = "blocked"
            self.log(f"[ERROR] 补丁计划预检失败，进程保持挂起: {exc}")
            return self.result

        # ── 自动发现 WarPC BSS 基址 ──
        fallback_base = self.settings.warpc_base_fallback
        self._discovered_base = discover_warpc_base(
            bytes(code_buf), code_start, int(fallback_base), log_func=self.log
        )
        self.runtime.warpc_base = self._discovered_base
        self.runtime.warpc_new_base = self._discovered_base

        # ── 分配 WarPC 缓冲区 (GUARD + 数据) ──
        self._allocate_warpc_buffer(target_pid)
        if self.runtime.blocked_error:
            self.result.error = self.runtime.blocked_error
            self.result.patches_status = "blocked"
            return self.result

        # ── 恢复其他被截断的 .dat ──
        self._restore_truncated_dats()

        # ── 设置配置变量 (新大小、实际大小) ──
        self._populate_runtime_state()

        # ── 分配 Cave 内存 ──
        cave_addr, cave_budget = self._allocate_cave(target_pid)
        self.result.cave_addr = cave_addr
        self.result.cave_budget = cave_budget

        # ── 应用配置补丁 ──
        self.overlay("正在应用游戏功能...", False)
        applied_ok = self._apply_patches(
            target_pid, code_buf, code_start, base_addr,
            cave_addr, exe_profile,
        )
        self.result.applied_patch_count = sum(
            1 for p in self.config.patches if getattr(p, "_applied", False)
        )
        if self.runtime.blocked_error:
            self.result.error = self.runtime.blocked_error
            self.result.patches_status = "blocked"
            self.log("[ERROR] 完整补丁计划未能应用，进程保持挂起")
            return self.result

        # ── WarPC 代码引用修补 ──
        if self._warpc_expanded and self._warpc_new_buf:
            self.overlay("正在准备游戏数据...", False)
            expand_warpc_buffer(
                target_pid, base_addr, mod_size, cave_addr,
                code_buf, code_start, self._warpc_new_buf, self._warpc_full_data,
                log_func=self.log,
                exclude_ranges=exe_profile.extra_section_ranges if exe_profile else None,
                warpc_base=self._discovered_base,
                warpc_rec_size=self.settings.warpc_rec_size,
            )

        # ── 运行时 WarPC 数据注入 ──
        self._inject_runtime_warpc(target_pid)

        # ── 存档索引 dump (诊断) ──
        self._dump_save_slots()

        # ── 恢复挂起的进程 ──
        if need_resume_pid:
            from .memory import resume_process
            resumed = resume_process(need_resume_pid)
            self.log(f"\n已恢复进程 PID={need_resume_pid} ({resumed} 个线程)")

        # ── 成功/失败提示 ──
        if applied_ok:
            self.log("\n补丁已应用！游戏正在运行。")
            self.log("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。")
            self.overlay("游戏功能已应用，祝游戏愉快！", True)
            self.status("游戏功能已应用，游戏运行中", True)
        else:
            self.log("\n[WARN] 部分补丁未应用成功")
            if tks_exe_replaced or exe_profile.name != "original":
                self.log(f"[INFO] 当前使用非原版 TKS.exe（检测为「{exe_profile.display_name}」），"
                          "部分补丁因目标代码已被该 MOD 修改而无法定位，属正常现象，不影响游戏运行。")
            self.overlay("部分游戏功能未能应用", False)
            self.status("部分游戏功能未应用", False)
            self.result.error = "some patches failed"

        self.result.success = applied_ok
        self.result.patches_status = "applied" if applied_ok else "partial"
        return self.result

    # ═══════════════════════════════════════════════════════════════
    # 阶段 3: 收尾 (游戏退出后)
    # ═══════════════════════════════════════════════════════════════

    def cleanup(self) -> None:
        """游戏退出后清理: 还原 MOD 原始文件 + 还原 TKAct。"""
        cleanup_ok = True
        if self.loaded_mods:
            try:
                restore_originals(self.cfg.game_dir or os.getcwd(), log_func=self.log)
                self.log("原始文件已恢复。")
            except Exception as e:
                cleanup_ok = False
                self.log(f"  [WARN] 还原 MOD 原始文件失败: {e}")

        if self._tkact_expanded:
            try:
                restore_tkact_for_game(log_func=self.log)
            except Exception as e:
                cleanup_ok = False
                self.log(f"  [WARN] 还原 TKAct 失败: {e}")
        self.result.cleanup_status = "succeeded" if cleanup_ok else "failed"

    def wait_game_exit(self, tks_proc, target_pid: int,
                       poll_interval: float = 0.5) -> None:
        """等待游戏进程退出。复用 worker/CLI 现有 _wait_game_exit 行为。"""
        from .memory import resume_process as _rp
        pids_to_watch = set()
        if tks_proc and tks_proc.poll() is None:
            pids_to_watch.add(tks_proc.pid)
        if target_pid:
            pids_to_watch.add(target_pid)
        if not pids_to_watch:
            return

        self.log(f"  监控进程: {pids_to_watch}")
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 258

        while True:
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
            time.sleep(poll_interval)

        self.log("  游戏进程已退出。")

    # ═══════════════════════════════════════════════════════════════
    # 私有辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _load_mods(self, mods_dir: str) -> None:
        """加载并应用 MOD 数据。"""
        self.log(f"\n=== MOD 加载 ({mods_dir}) ===")
        # MOD 可覆盖配置白名单: 从补丁声明 (mod_config_overridable) 动态推导,
        # 补丁配置不可用 (如兼容模式) 时自动回退默认集。
        _allowed = allowed_mod_configs(self.config)
        self.loaded_mods = scan_mods(mods_dir, log_func=self.log,
                                     allowed_configs=_allowed)
        self._mod_config_overrides = None
        if not self.loaded_mods:
            self.log(f"  未发现 MOD 文件")
            return

        # 按 UI/CLI 勾选状态过滤
        if self.cfg.enabled_mod_ids is not None:
            if self.cfg.enabled_mod_ids == "__NONE__":
                for m in self.loaded_mods:
                    m.enabled = False
                self.log("  --no-mods: 已禁用全部 MOD")
            else:
                skipped = []
                for m in self.loaded_mods:
                    m.enabled = m.mod_id in self.cfg.enabled_mod_ids
                    if not m.enabled:
                        skipped.append(m.mod_id)
                if skipped:
                    self.log(f"  用户取消勾选 {len(skipped)} 个 MOD: {', '.join(skipped)}")

        # 展开 .tksmodpak 合集
        expanded = []
        for m in self.loaded_mods:
            if m.enabled and m.pak_contents:
                self.log(f"  展开合集: {m.name} ({len(m.pak_contents)} 个模组)")
                pak_mods = expand_pak_mods(m.path, log_func=self.log,
                                           allowed_configs=_allowed)
                for pm in pak_mods:
                    pm.enabled = True
                expanded.extend(pak_mods)
            elif not m.pak_contents:
                expanded.append(m)
        sorted_mods = resolve_dependencies(expanded, log_func=self.log)
        conflicts = detect_conflicts(sorted_mods, log_func=self.log)
        if conflicts:
            self.log(f"  [WARN] 检测到 {len(conflicts)} 个冲突, 继续加载 (后加载覆盖)")

        # 合并 + 写入
        self.log(f"\n--- 合并 MOD 数据 ---")
        merged = merge_mods(sorted_mods, self.cfg.game_dir or os.getcwd(), log_func=self.log)
        self._mod_config_overrides = merged.config_overrides
        if merged.file_data or merged.resource_replacements or merged.backed_up:
            self.log(f"\n--- 写入 MOD 数据 ---")
            apply_mod_data(merged, self.cfg.game_dir or os.getcwd(), log_func=self.log)
            self.log(f"  MOD 数据已写入, 游戏启动后将自动恢复原始文件")
        else:
            self.log(f"  MOD 无数据变更")

        self.result.loaded_mods = [m.mod_id for m in self.loaded_mods if m.enabled]
        self.result.mods_loaded_count = len(self.result.loaded_mods)

    def _allocate_warpc_buffer(self, target_pid: int) -> None:
        """分配 WarPC 缓冲区 (GUARD + 数据)。"""
        if not (self._warpc_expanded and self._warpc_full_data):
            return
        wp = "WarPC.dat"
        bp = wp + ".orig"
        if os.path.isfile(bp):
            shutil.copy2(bp, wp)
            os.remove(bp)
            self.log("  已恢复原始 WarPC.dat")

        ns = len(self._warpc_full_data)
        hw = _OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False, target_pid
        )
        if not hw:
            self.runtime.blocked_error = "无法取得扩展数据写入句柄"
            self.log("  [ERROR] OpenProcess 失败，扩展数据缓冲区未分配")
            return
        try:
            GUARD_SIZE = 0x10000
            total_alloc = ns + GUARD_SIZE
            ab = _VirtualAllocEx(hw, None, total_alloc,
                                 MEM_COMMIT | MEM_RESERVE,
                                 PAGE_EXECUTE_READWRITE)
            if ab:
                abv = ctypes.cast(ab, ctypes.c_void_p).value or 0
                nb = abv + GUARD_SIZE
                from .memory import write_pm
                if write_pm(hw, nb, self._warpc_full_data) != ns:
                    self.runtime.blocked_error = "扩展数据缓冲区写入不完整"
                    return
                self._warpc_new_buf = nb
                self._warpc_base_for_caves = nb
                self.runtime.warpc_new_base = nb
                self.result.warpc_new_buf = nb
                self.result.warpc_new_base = nb
                self.log(f"  WarPC 缓冲区: 0x{nb:08X} ({ns} 字节, "
                          f"{ns // WARPC_REC_SIZE} 角色)")
            else:
                self.runtime.blocked_error = "扩展数据缓冲区分配失败"
        finally:
            _CloseHandle(hw)

    def _restore_truncated_dats(self) -> None:
        """恢复非 WarPC 的 .dat 截断备份。"""
        for k in list(self._truncated_files.keys()):
            if k == "WarPC.dat":
                continue
            bp = k + ".orig"
            if os.path.isfile(bp):
                shutil.copy2(bp, k)
                os.remove(bp)
                self.log(f"  已恢复原始 {k}")
        if self._tkact_expanded:
            restore_tkact_for_game(log_func=self.log)

    def _populate_runtime_state(self) -> None:
        """填充运行时状态 (warpc_new_size / *_actual_size)。"""
        if self._warpc_expanded and self._warpc_full_data:
            self.runtime.warpc_new_size = len(self._warpc_full_data)
        else:
            self.runtime.warpc_new_size = WARPC_ORIG_SIZE

        for fname in DATA_FILE_ORIG_SIZES:
            basename = os.path.splitext(fname)[0]
            attr_name = basename.lower() + "_actual_size"
            actual = get_decompressed_size(fname)
            setattr(self.runtime, attr_name,
                    actual if actual > 0 else DATA_FILE_ORIG_SIZES[fname])

        count = self.settings.tkdefunit_orig_count
        try:
            if os.path.isfile("TKDefUnit.Dat"):
                count = max(count, (os.path.getsize("TKDefUnit.Dat") + 15) // 16)
        except OSError:
            pass
        self.runtime.tkdefunit_new_count = count

        new_size = self.settings.tkact_orig_size
        try:
            if os.path.isfile("TKAct.dat"):
                path = "TKAct.dat.expanded"
                if not os.path.isfile(path):
                    path = "TKAct.dat"
                size = os.path.getsize(path)
                if size % self.settings.tkact_rec_size == 0:
                    new_size = max(new_size, size)
        except OSError:
            pass
        self.runtime.tkact_new_size = new_size

    def _allocate_cave(self, target_pid: int) -> Tuple[int, int]:
        """分配 Cave 内存 (Phase 1: 1024→2048 + Phase 3: cave_total_size)。"""
        hp = _OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False, target_pid
        )
        if not hp:
            self.log("  [WARN] OpenProcess 失败, caves skipped")
            return 0, 0

        # Phase 1+3: Cave 虚拟页大小 (cave_total_size 变量 + TKS_CAVE_BUDGET 环境变量覆盖)
        cave_budget = int(os.environ.get(
            "TKS_CAVE_BUDGET",
            self.settings.cave_total_size,
        ))
        try:
            ca = _VirtualAllocEx(hp, None, cave_budget,
                                 MEM_COMMIT | MEM_RESERVE,
                                 PAGE_EXECUTE_READWRITE)
            if ca:
                cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
                self.log(f"  Cave 内存: 0x{cave_addr:08X} ({cave_budget} bytes)")
                return cave_addr, cave_budget
        finally:
            _CloseHandle(hp)
        self.log("  [WARN] VirtualAllocEx failed, caves skipped")
        return 0, cave_budget

    def _apply_patches(self, target_pid: int, code_buf: bytearray,
                       code_start: int, base_addr: int,
                       cave_addr: int, exe_profile) -> bool:
        """调用 apply_config_patches 应用所有补丁。

        单独打开进程句柄 (apply_config_patches 需要 HANDLE 而非 PID),
        调用结束后关闭。
        """
        self.runtime.target_pid = target_pid
        hp = _OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False, target_pid
        )
        if not hp:
            self.runtime.blocked_error = "无法取得补丁写入句柄"
            self.log("  [ERROR] OpenProcess 失败，已阻止继续执行补丁计划")
            return False
        try:
            ok = apply_config_patches(
                self.config, code_buf, code_start, base_addr,
                hp,
                self._warpc_base_for_caves if self._warpc_base_for_caves else self._discovered_base,
                cave_addr, self.settings, self.runtime, log_func=self.log,
                minimal_mode=False,
                selected_patches=self.cfg.selected_patches,
                exe_profile=exe_profile,
                disabled_patches=self.cfg.disabled_patches,
                config_overrides=self._mod_config_overrides,
                plan=self.patch_plan,
            )
            return bool(ok)
        except PatchPlanError as ex:
            self.runtime.blocked_error = str(ex)
            self.log(f"[ERROR] 补丁计划已阻止继续执行: {ex}")
            return False
        except Exception as ex:
            self.runtime.blocked_error = str(ex)
            self.log(f"[ERROR] ApplyConfigPatches 异常: {ex}")
            self.log(traceback.format_exc())
            return False
        finally:
            _CloseHandle(hp)

    def _inject_runtime_warpc(self, target_pid: int) -> None:
        """运行时 WarPC 数据注入。"""
        inject_warpc_data(target_pid, self._discovered_base,
                          self._warpc_expanded, log_func=self.log)

    def _dump_save_slots(self) -> None:
        """存档索引文件内容 dump (诊断)。"""
        self.log("\n--- 存档索引文件内容 dump ---")
        for si in range(1, 10):
            ip = f"save\\{si}.sav"
            if not os.path.isfile(ip):
                self.log(f"  slot {si}: 不存在")
                continue
            try:
                with open(ip, 'rb') as f:
                    idx = f.read()
                if len(idx) != 28:
                    self.log(f"  slot {si}: 大小={len(idx)} (异常)")
                    continue
                team = [struct.unpack('b', idx[k:k+1])[0] for k in range(6)]
                lvs = [b2i16(idx, 12 + k*2) for k in range(6)]
                self.log(f"  slot {si}: team=[{','.join(str(t) for t in team)}] "
                          f"levels=[{','.join('Lv'+str(l) for l in lvs)}]")
            except Exception as e:
                self.log(f"  slot {si}: 读取失败 {e}")
