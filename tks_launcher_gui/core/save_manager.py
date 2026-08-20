"""存档备份管理 — 备份/恢复游戏存档 + 补丁状态快照

备份结构 (标准 .zip, 任何解压工具均可解压):
  backups/<名称>.zip
    ├── Save/                # 完整存档目录 (保留原始结构)
    │   ├── 1.sav
    │   ├── sav.1
    │   └── ...
    └── backup_meta.json     # 备份元数据 (启动器读取用, 外部工具可忽略)

game_dir 持久化:
  save_manager_state.json    # {last_game_dir: "..."} 记忆上次使用的游戏目录
"""
import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 存档目录名 (相对 game_dir)
_SAVE_DIR_NAME = "Save"
# 备份元数据文件名 (zip 内)
_META_NAME = "backup_meta.json"
# 元数据格式版本
_META_VERSION = 2
# game_dir 持久化文件名
_STATE_NAME = "save_manager_state.json"

# Windows 文件名非法字符
_INVALID_CHARS = '<>:"/\\|?*'


@dataclass
class BackupInfo:
    """备份信息 (从 zip 内 backup_meta.json 读取)"""
    path: str                          # zip 文件完整路径
    name: str                          # 用户自定义名称
    time: str                          # 备份时间 "YYYY-MM-DD HH:MM:SS"
    patch_state: Dict[str, bool] = field(default_factory=dict)
    mod_state: Dict[str, bool] = field(default_factory=dict)
    tool: str = ""
    mode: str = "standard"
    game_path: str = ""
    state_schema_version: int = 2
    save_file_count: int = 0           # 存档文件数量


# ============================================================
# game_dir 持久化
# ============================================================

def get_last_game_dir(launcher_dir: str) -> str:
    """读取上次使用的游戏目录 (空字符串表示无记录)"""
    path = os.path.join(launcher_dir, _STATE_NAME)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        d = raw.get("last_game_dir", "")
        return d if isinstance(d, str) else ""
    except Exception:
        return ""


def set_last_game_dir(launcher_dir: str, game_dir: str) -> None:
    """持久化游戏目录 (原子写入)"""
    path = os.path.join(launcher_dir, _STATE_NAME)
    data = {
        "_说明": "存档管理器游戏目录记录 — 自动生成",
        "last_game_dir": game_dir,
    }
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ============================================================
# 备份列表
# ============================================================

def list_backups(backups_dir: str) -> List[BackupInfo]:
    """扫描 backups 目录, 返回按备份时间倒序排列的备份列表"""
    result: List[BackupInfo] = []
    if not os.path.isdir(backups_dir):
        return result
    for name in os.listdir(backups_dir):
        if not name.lower().endswith(".zip"):
            continue
        zip_path = os.path.join(backups_dir, name)
        if not os.path.isfile(zip_path):
            continue
        info = _read_backup_meta(zip_path)
        if info is not None:
            result.append(info)
    # 按时间倒序 (最新的在前)
    result.sort(key=lambda b: b.time, reverse=True)
    return result


def _read_backup_meta(zip_path: str) -> Optional[BackupInfo]:
    """从 zip 中读取 backup_meta.json, 返回 BackupInfo"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # 统计 Save/ 下文件数 (大小写不敏感, 兼容旧备份)
            save_count = sum(
                1 for n in zf.namelist()
                if n.lower().startswith("save/") and not n.endswith("/")
            )
            # 读取元数据
            try:
                raw_bytes = zf.read(_META_NAME)
                raw = json.loads(raw_bytes.decode('utf-8'))
            except KeyError:
                # 无元数据 (可能是外部创建的 zip), 用文件名和时间戳兜底
                name = os.path.splitext(os.path.basename(zip_path))[0]
                mtime = datetime.fromtimestamp(
                    os.path.getmtime(zip_path)).strftime("%Y-%m-%d %H:%M:%S")
                return BackupInfo(
                    path=zip_path, name=name, time=mtime,
                    save_file_count=save_count)
            return BackupInfo(
                path=zip_path,
                name=raw.get("backup_name", os.path.splitext(
                    os.path.basename(zip_path))[0]),
                time=raw.get("backup_time", ""),
                patch_state=_to_bool_dict(raw.get("patch_state")),
                mod_state=_to_bool_dict(raw.get("mod_state")),
                tool=raw.get("tool", "") if isinstance(
                    raw.get("tool"), str) else "",
                mode=raw.get("mode", "standard") if raw.get("mode") in {"standard", "compatible"} else "standard",
                game_path=raw.get("game_path", "") if isinstance(raw.get("game_path"), str) else "",
                state_schema_version=int(raw.get("state_schema_version", 1) or 1),
                save_file_count=save_count,
            )
    except Exception:
        return None


def _to_bool_dict(raw) -> Dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


# ============================================================
# 创建备份
# ============================================================

def create_backup(
    backups_dir: str,
    game_dir: str,
    name: str,
    patch_state: Dict[str, bool],
    mod_state: Dict[str, bool],
    tool: str,
    mode: str = "standard",
    game_path: str = "",
    state_schema_version: int = 2,
) -> str:
    """创建存档备份 (最高压缩比 ZIP_DEFLATED level=9)

    返回 zip 文件完整路径。
    若 Save/ 目录不存在或为空, 仍会创建备份 (空存档快照)。
    """
    os.makedirs(backups_dir, exist_ok=True)

    safe_name = _sanitize_filename(name)
    if not safe_name:
        safe_name = "backup"
    zip_path = _unique_path(backups_dir, safe_name, ".zip")

    save_dir = os.path.join(game_dir, _SAVE_DIR_NAME)
    # 收集要压缩的存档文件
    save_files: List[Tuple[str, str]] = []  # (zip内路径, 本地完整路径)
    if os.path.isdir(save_dir):
        for root, _dirs, files in os.walk(save_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arc = os.path.relpath(full, game_dir).replace(os.sep, "/")
                save_files.append((arc, full))

    # 构建元数据
    meta = {
        "backup_name": name,
        "backup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "format_version": _META_VERSION,
        "patch_state": patch_state,
        "mod_state": mod_state,
        "tool": tool,
        "mode": mode if mode in {"standard", "compatible"} else "standard",
        "game_path": game_path,
        "state_schema_version": state_schema_version,
        "save_file_count": len(save_files),
    }

    # 写入 zip (compresslevel=9 最高压缩比)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arc, full in save_files:
            zf.write(full, arc)
        zf.writestr(_META_NAME, json.dumps(meta, ensure_ascii=False, indent=2))

    return zip_path


# ============================================================
# 恢复存档
# ============================================================

def validate_backup(zip_path: str) -> Tuple[bool, str]:
    """校验 zip 完整性。返回 (ok, 错误信息)"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"压缩包内文件损坏: {bad}"
            # 确认至少包含 Save/ 目录或 backup_meta.json
            names = zf.namelist()
            has_save = any(n.lower().startswith("save/") for n in names)
            has_meta = _META_NAME in names
            if not has_save and not has_meta:
                return False, "压缩包内未找到存档数据"
        return True, ""
    except zipfile.BadZipFile:
        return False, "压缩包格式损坏 (BadZipFile)"
    except Exception as e:
        return False, str(e)


def restore_save_files(zip_path: str, game_dir: str) -> int:
    """从备份恢复存档文件到 game_dir/Save/

    恢复前会清空 game_dir/Save/ 目录中的所有文件。
    返回恢复的文件数量。
    """
    save_dir = os.path.join(game_dir, _SAVE_DIR_NAME)

    # 清空当前 Save/ 目录
    if os.path.isdir(save_dir):
        for item in os.listdir(save_dir):
            item_path = os.path.join(save_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
    else:
        os.makedirs(save_dir, exist_ok=True)

    # 解压 Save/ 下的文件到 game_dir
    count = 0
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name == _META_NAME:
                continue  # 跳过元数据文件
            if name.endswith("/"):
                continue  # 跳过目录条目
            if not name.lower().startswith("save/"):
                continue  # 仅恢复 Save/ 下的存档文件
            # 防止路径穿越 (zip slip)
            target = os.path.join(game_dir, name.replace("/", os.sep))
            real_target = os.path.realpath(target)
            real_game = os.path.realpath(game_dir)
            if not real_target.startswith(real_game + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(name) as src, open(target, 'wb') as dst:
                dst.write(src.read())
            count += 1

    return count


# ============================================================
# 删除备份
# ============================================================

def delete_backup(zip_path: str) -> bool:
    """删除备份文件"""
    try:
        os.remove(zip_path)
        return True
    except Exception:
        return False


# ============================================================
# 辅助函数
# ============================================================

def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    result = name.strip()
    for ch in _INVALID_CHARS:
        result = result.replace(ch, "_")
    # 限制长度, 预留时间戳/序号空间
    if len(result) > 80:
        result = result[:80]
    return result


def _unique_path(directory: str, base: str, ext: str) -> str:
    """生成不冲突的文件路径。若已存在则追加 (2), (3)..."""
    candidate = os.path.join(directory, base + ext)
    if not os.path.exists(candidate):
        return candidate
    idx = 2
    while True:
        candidate = os.path.join(directory, f"{base} ({idx}){ext}")
        if not os.path.exists(candidate):
            return candidate
        idx += 1
