"""GUI 勾选状态持久化 — 保存/加载启动器各列表的勾选结果

状态文件与 CLI (Winlator 版 TKSLauncherCLI) 共用 launcher_config.json:
GUI 每次勾选变化时自动更新其中的勾选状态字段, 下次启动时恢复;
文件中的 tks_exe / game / advanced 等字段供 CLI 使用, GUI 读写时原样保留。
用户在 PC 上用 GUI 配置完成后, 直接把该文件复制到 Winlator 游戏目录即可。
"""
import json
import os
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class GuiState:
    """启动器 GUI 勾选状态快照"""
    schema_version: int = 2
    # 最近一次选择的游戏程序。空值表示尚未选择。
    last_game_path: str = ""
    # standard / compatible；未知值由加载器降级为 standard。
    mode: str = "standard"
    # 可选补丁勾选状态: {patch_id: bool} (必选补丁始终启用, 不记录)
    patches: Dict[str, bool] = field(default_factory=dict)
    # 模组启用状态: {mod_id: bool}
    mods: Dict[str, bool] = field(default_factory=dict)
    # 辅助工具选择 (空字符串表示"无")
    tool: str = ""
    # 未来版本字段原样保留，避免旧启动器保存时破坏新配置。
    extra: Dict[str, object] = field(default_factory=dict)


def state_profile_key(game_path: str) -> str:
    """为游戏程序路径生成稳定键，避免路径中的特殊字符污染 JSON 键名。"""
    normalized = os.path.normcase(os.path.abspath(game_path)).replace("\\", "/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _clean_id_states(section: dict) -> Dict[str, bool]:
    """解析 {id: bool} 勾选状态, 下划线开头键为说明字段, 一律跳过。"""
    return {str(k): bool(v) for k, v in section.items()
            if not str(k).startswith("_")}


def _state_from_raw(raw: dict) -> GuiState:
    state = GuiState()
    known = {"_说明", "schema_version", "last_game_path", "mode",
             "patches", "mods", "tool", "profiles"}
    state.extra = {str(k): v for k, v in raw.items() if k not in known}
    raw_version = raw.get("schema_version", 1)
    if isinstance(raw_version, int) and raw_version > 0:
        state.schema_version = max(raw_version, 2)
    last_game_path = raw.get("last_game_path", "")
    if isinstance(last_game_path, str):
        state.last_game_path = last_game_path
    mode = raw.get("mode", "standard")
    state.mode = mode if mode in {"standard", "compatible"} else "standard"
    patches = raw.get("patches", {})
    if isinstance(patches, dict):
        state.patches = _clean_id_states(patches)
    mods = raw.get("mods", {})
    if isinstance(mods, dict):
        state.mods = _clean_id_states(mods)
    tool = raw.get("tool", "")
    if isinstance(tool, str):
        state.tool = tool
    return state


def load_gui_state(path: str, game_path: str | None = None) -> Optional[GuiState]:
    """从 JSON 文件加载 GUI 状态。文件不存在或损坏时返回 None。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return None

    legacy = _state_from_raw(raw)
    selected_path = game_path or legacy.last_game_path
    profiles = raw.get("profiles", {})
    if selected_path and isinstance(profiles, dict):
        profile = profiles.get(state_profile_key(selected_path))
        if isinstance(profile, dict):
            state = _state_from_raw(profile)
            state.last_game_path = selected_path
            return state
    return legacy


def save_gui_state(path: str, state: GuiState, game_path: str | None = None) -> bool:
    """将 GUI 状态保存为 JSON 文件 (原子写入, 避免半截写损坏)。

    返回 True 表示保存成功, False 表示失败。
    """
    data = {
        "_说明": "TKS Launcher 共享配置文件 — GUI 自动生成并更新勾选状态, "
                 "复制到 Winlator 游戏目录即可供 TKSLauncherCLI 使用",
        "schema_version": 2,
        "last_game_path": state.last_game_path,
        "mode": state.mode if state.mode in {"standard", "compatible"} else "standard",
        "patches": state.patches,
        "mods": state.mods,
        "tool": state.tool,
    }
    for key, value in state.extra.items():
        if key not in data and key != "profiles":
            data[key] = value
    # 保留已有 profiles；指定游戏路径时只更新该游戏的配置。
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                if isinstance(existing.get("profiles"), dict):
                    data["profiles"] = existing["profiles"]
                # 共享配置: 保留已有文件中的 CLI/外部字段
                # (tks_exe/game/advanced/下划线说明字段等), GUI 只更新自身字段
                for key, value in existing.items():
                    if key not in data:
                        data[key] = value
        selected_path = game_path or state.last_game_path
        if selected_path:
            data.setdefault("profiles", {})[state_profile_key(selected_path)] = {
                "schema_version": 2,
                "mode": data["mode"],
                "patches": data["patches"],
                "mods": data["mods"],
                "tool": data["tool"],
            }
    except Exception:
        pass
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False
