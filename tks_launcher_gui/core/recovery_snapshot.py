"""启动任务恢复快照。

快照只记录任务边界和状态，不复制游戏文件；实际恢复继续复用现有
`.mod_orig`、`.orig` 和 `.toolbak` 备份机制。
"""
from __future__ import annotations

import json
import os
import uuid
import shutil
import hashlib
from dataclasses import dataclass, asdict


@dataclass
class RecoverySnapshot:
    task_id: str
    game_dir: str
    exe_path: str
    status: str = "active"
    file_manifest: dict[str, str] | None = None


def snapshot_path(launcher_dir: str) -> str:
    return os.path.join(launcher_dir, "launcher_recovery.json")


def begin_snapshot(launcher_dir: str, game_dir: str, exe_path: str) -> str:
    snapshot = RecoverySnapshot(
        task_id=uuid.uuid4().hex,
        game_dir=os.path.abspath(game_dir),
        exe_path=os.path.abspath(exe_path),
        file_manifest=_build_manifest(game_dir),
    )
    _write(snapshot_path(launcher_dir), snapshot)
    return snapshot.task_id


def finish_snapshot(launcher_dir: str, task_id: str) -> bool:
    path = snapshot_path(launcher_dir)
    current = load_snapshot(launcher_dir)
    if current is None or current.task_id != task_id:
        return False
    current.status = "completed"
    _write(path, current)
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def load_snapshot(launcher_dir: str) -> RecoverySnapshot | None:
    path = snapshot_path(launcher_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if raw.get("status") != "active":
            return None
        return RecoverySnapshot(
            task_id=str(raw["task_id"]),
            game_dir=str(raw["game_dir"]),
            exe_path=str(raw["exe_path"]),
            status="active",
            file_manifest=raw.get("file_manifest", {}) if isinstance(raw.get("file_manifest", {}), dict) else {},
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def recover_game_directory(game_dir: str, log_func=None) -> bool:
    """恢复启动器留下的 MOD/TKS.exe/辅助工具备份。"""
    log = log_func or (lambda _message: None)
    ok = True
    try:
        from .mod_loader import restore_originals
        restore_originals(game_dir, log_func=log)
    except Exception as exc:
        log(f"恢复 MOD 文件失败: {exc}")
        ok = False

    for root, _dirs, files in os.walk(game_dir):
        for filename in files:
            if not filename.endswith(".toolbak"):
                continue
            backup = os.path.join(root, filename)
            target = backup[:-len(".toolbak")]
            try:
                shutil.copy2(backup, target)
                os.remove(backup)
                log(f"恢复辅助工具文件: {os.path.relpath(target, game_dir)}")
            except OSError as exc:
                log(f"恢复辅助工具文件失败: {target}: {exc}")
                ok = False
    tks_backup = os.path.join(game_dir, "TKS.exe.mod_orig")
    tks_target = os.path.join(game_dir, "TKS.exe")
    if os.path.isfile(tks_backup):
        try:
            shutil.copy2(tks_backup, tks_target)
            os.remove(tks_backup)
            log("恢复 TKS.exe")
        except OSError as exc:
            log(f"恢复 TKS.exe 失败: {exc}")
            ok = False
    return ok


def manifest_changed(game_dir: str, manifest: dict[str, str] | None) -> list[str]:
    """返回启动前已登记、但当前内容发生变化的文件相对路径。"""
    if not manifest:
        return []
    current = _build_manifest(game_dir)
    return [path for path, digest in manifest.items() if current.get(path) != digest]


def _build_manifest(game_dir: str) -> dict[str, str]:
    """记录启动器常见备份目标的启动前哈希，避免扫描所有游戏资源。"""
    result: dict[str, str] = {}
    if not os.path.isdir(game_dir):
        return result
    candidates = [os.path.join(game_dir, "TKS.exe")]
    for root, _dirs, files in os.walk(game_dir):
        for filename in files:
            if filename.endswith((".mod_orig", ".mod_new", ".toolbak", ".orig")):
                candidates.append(os.path.join(root, filename))
    for path in candidates:
        if os.path.isfile(path):
            try:
                digest = hashlib.sha256()
                with open(path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                result[os.path.relpath(path, game_dir).replace(os.sep, "/")] = digest.hexdigest()
            except OSError:
                continue
    return result


def _write(path: str, snapshot: RecoverySnapshot) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(asdict(snapshot), handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
