"""
shared_state — 跨编辑器共享状态 (目录记忆)
============================================
所有编辑器共用的持久化状态存储, 当前用于记忆用户选择的目录:

  - last_ref_dir: MOD 导出时选择的原始游戏目录 (差异参考)
  - last_tks_dir: 「加载 TKS 目录」选择的游戏目录

任何一个编辑器选择目录后写入共享状态, 其它编辑器下次打开时默认加载。

状态文件位置 (兼容编译/打包与开发环境):
  - 打包模式 (Nuitka onefile/thin): exe 所在发行目录 — 所有编辑器 exe
    同目录部署, 状态自然共享; 经 runtime_bootstrap 用 sys.argv[0] 解析,
    不会误落到 onefile 临时解压目录
  - 开发模式:  目录 (editor_utils 的上级目录)

读写全程容错: 状态文件缺失/损坏/不可写时静默回退, 绝不影响主流程。
"""
import json
import os
from pathlib import Path

_STATE_FILENAME = ".tks_editors_state.json"

# 状态键
KEY_LAST_REF_DIR = "last_ref_dir"   # MOD 导出参考目录
KEY_LAST_TKS_DIR = "last_tks_dir"   # 加载 TKS 游戏目录
KEY_RECENT_TKS_DIRS = "recent_tks_dirs"  # 最近加载的 TKS 目录列表 (最新在前)

RECENT_DIRS_MAX = 5


def shared_state_path() -> Path:
    """共享状态文件路径 (所有编辑器共用)。

    路径解析委托 editor_utils.app_init.get_app_dir, 兼容:
      - Nuitka onefile/thin exe (经 runtime_bootstrap 用 sys.argv[0] 定位)
      - 开发模式 ( 目录)
    """
    from editor_utils.app_init import get_app_dir
    return get_app_dir() / _STATE_FILENAME


def load_shared_state() -> dict:
    """读取共享状态 JSON, 任何异常都静默回退为空状态。"""
    try:
        with open(shared_state_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_shared_state(state: dict):
    """写回共享状态 JSON (失败静默忽略, 不影响主流程)。"""
    try:
        path = shared_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_dir(key: str) -> str:
    """读取目录类状态项 (不存在或目录已失效时返回空串)。"""
    d = load_shared_state().get(key, "")
    if isinstance(d, str) and d and os.path.isdir(d):
        return d
    return ""


def _set_dir(key: str, d: str):
    """写入目录类状态项 (空目录忽略)。"""
    if not d:
        return
    state = load_shared_state()
    state[key] = d
    save_shared_state(state)


# ── MOD 导出参考目录 ──

def get_last_ref_dir() -> str:
    """获取最近一次 MOD 导出选择的参考目录 (不存在或非法时返回空串)。"""
    return _get_dir(KEY_LAST_REF_DIR)


def save_last_ref_dir(d: str):
    """保存最近一次 MOD 导出选择的参考目录, 供其它编辑器默认加载。"""
    _set_dir(KEY_LAST_REF_DIR, d)


# ── 加载 TKS 游戏目录 ──

def get_last_tks_dir() -> str:
    """获取最近一次「加载 TKS 目录」选择的游戏目录 (失效时返回空串)。"""
    return _get_dir(KEY_LAST_TKS_DIR)


def save_last_tks_dir(d: str):
    """保存最近一次「加载 TKS 目录」选择的游戏目录, 供其它编辑器默认加载。

    同时压入最近目录列表 (KEY_RECENT_TKS_DIRS, 供"最近目录"菜单)。
    """
    _set_dir(KEY_LAST_TKS_DIR, d)
    push_recent_tks_dir(d)


def get_recent_tks_dirs() -> list[str]:
    """最近加载的 TKS 目录列表 (最新在前; 仅保留仍存在的目录, 去重, 上限 5)。"""
    raw = load_shared_state().get(KEY_RECENT_TKS_DIRS, [])
    if not isinstance(raw, list):
        return []
    dirs: list[str] = []
    for d in raw:
        if isinstance(d, str) and d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs[:RECENT_DIRS_MAX]


def push_recent_tks_dir(d: str):
    """把目录压入最近列表头部 (去重, 上限 RECENT_DIRS_MAX)。空目录忽略。"""
    if not d:
        return
    state = load_shared_state()
    raw = state.get(KEY_RECENT_TKS_DIRS, [])
    if not isinstance(raw, list):
        raw = []
    dirs = [x for x in raw if x != d]
    dirs.insert(0, d)
    state[KEY_RECENT_TKS_DIRS] = dirs[:RECENT_DIRS_MAX]
    save_shared_state(state)


def pick_tks_directory(parent=None, title: str = "选择 TKS 游戏目录") -> str:
    """弹出带记忆的 TKS 游戏目录选择对话框 (跨编辑器共享记忆)。

    对话框默认打开最近一次选择的游戏目录; 用户选定后立即写入共享状态
    (含最近目录列表, 供各编辑器"最近目录"菜单使用)。

    Args:
        parent: 父窗口
        title: 对话框标题 (各编辑器可自定义提示文案)

    Returns:
        选定的目录路径; 用户取消时返回空串 (与原 getExistingDirectory 语义一致)
    """
    from PySide6.QtWidgets import QFileDialog
    d = QFileDialog.getExistingDirectory(parent, title, get_last_tks_dir())
    if d:
        save_last_tks_dir(d)
        return d
    return ""
