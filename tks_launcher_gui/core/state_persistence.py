"""GUI 勾选状态持久化 — 保存/加载启动器各列表的勾选结果

状态文件 (launcher_setting.json) 独立于 CLI 用的 launcher_config.json,
仅记录 GUI 中各列表的勾选情况, 每次勾选变化时自动更新, 下次启动时恢复。
"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class GuiState:
    """启动器 GUI 勾选状态快照"""
    # 可选补丁勾选状态: {patch_id: bool} (必选补丁始终启用, 不记录)
    patches: Dict[str, bool] = field(default_factory=dict)
    # 模组启用状态: {mod_id: bool}
    mods: Dict[str, bool] = field(default_factory=dict)
    # 辅助工具选择 (空字符串表示"无")
    tool: str = ""


def load_gui_state(path: str) -> Optional[GuiState]:
    """从 JSON 文件加载 GUI 状态。文件不存在或损坏时返回 None。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return None

    state = GuiState()
    patches = raw.get("patches", {})
    if isinstance(patches, dict):
        state.patches = {str(k): bool(v) for k, v in patches.items()}
    mods = raw.get("mods", {})
    if isinstance(mods, dict):
        state.mods = {str(k): bool(v) for k, v in mods.items()}
    tool = raw.get("tool", "")
    if isinstance(tool, str):
        state.tool = tool
    return state


def save_gui_state(path: str, state: GuiState) -> bool:
    """将 GUI 状态保存为 JSON 文件 (原子写入, 避免半截写损坏)。

    返回 True 表示保存成功, False 表示失败。
    """
    data = {
        "_说明": "TKS Launcher GUI 勾选状态 — 自动生成, 每次勾选变化时更新",
        "patches": state.patches,
        "mods": state.mods,
        "tool": state.tool,
    }
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
