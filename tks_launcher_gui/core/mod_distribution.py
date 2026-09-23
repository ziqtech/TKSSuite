"""离线 MOD 整合工作区：原版只读，暂存合并，事务发布。"""
import base64
import io
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from . import mod_loader
from .mod_loader import ModInfo


_MANIFEST = "tks_build_manifest.json"
_MARKERS = (".orig", ".mod_orig", ".mod_new", ".toolbak", ".expanded", ".bak")
_DEVICE = re.compile(r"^(con|prn|aux|nul|clock\$|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])$", re.I)
_KNOWN_NAMES = {n.casefold(): n for n in (
    *mod_loader.DAT_FILE_INFO, *mod_loader.STRUCTURED_FILE_INFO,
    "TKS.exe", "TKD.dat", "TKT.dat",
)}


def _relative(name: str) -> str:
    if not isinstance(name, str) or not name or ntpath.splitdrive(name)[0]:
        raise ValueError(f"无效的相对路径：{name!r}")
    parts = name.replace("\\", "/").split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((" ", "."))
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or _DEVICE.fullmatch(part.split(".")[0].rstrip(" "))
                or part.casefold().endswith(_MARKERS)
                or part.casefold() == _MANIFEST):
            raise ValueError(f"不安全的 Windows 相对路径：{name!r}")
    return "/".join(parts)


def _key(path):
    return os.path.normpath(os.path.abspath(path)).replace("\\", "/").casefold()


def _within(path, root):
    p, r = _key(path), _key(root)
    return p == r or p.startswith(r.rstrip("/") + "/")


def _link(path):
    if not os.path.lexists(path):
        return False
    attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    return os.path.islink(path) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _join(root, name):
    """按 Windows 大小写规则定位，同时拒绝目录链接和文件链接。"""
    current = root
    for part in name.split("/"):
        if os.path.isdir(current):
            matches = [n for n in os.listdir(current) if n.casefold() == part.casefold()]
            if len(matches) > 1:
                raise ValueError(f"路径存在大小写歧义：{name}")
            if matches:
                part = matches[0]
        current = os.path.join(current, part)
        if _link(current):
            raise ValueError(f"不允许链接路径：{current}")
    if not _within(os.path.realpath(current), os.path.realpath(root)):
        raise ValueError(f"路径超出目录：{name}")
    return current


def _clean_read(path):
    if _link(path):
        raise ValueError(f"不允许读取链接文件：{path}")
    if os.path.basename(path).casefold().endswith(_MARKERS):
        raise ValueError(f"不能使用恢复备份文件：{path}")
    parent = os.path.dirname(path)
    if os.path.isdir(parent):
        prefix = os.path.basename(path).casefold()
        for name in os.listdir(parent):
            if any(name.casefold() == prefix + suffix for suffix in _MARKERS):
                raise ValueError(f"检测到运行残留，请先独立恢复原版：{os.path.join(parent, name)}")


def _register(names, name):
    name = _relative(name)
    folded = name.casefold()
    if folded in names:
        return names[folded]
    for key in names:
        if key.startswith(folded + "/") or folded.startswith(key + "/"):
            raise ValueError(f"文件与目录目标冲突：{name} / {names[key]}")
    parts = name.split("/")
    for other in names.values():
        old = other.split("/")
        for i in range(min(len(parts), len(old)) - 1):
            if [p.casefold() for p in parts[:i + 1]] == [p.casefold() for p in old[:i + 1]]:
                parts[i] = old[i]
    name = "/".join(parts)
    names[folded] = name
    return name


def _archive(raw):
    zf = zipfile.ZipFile(io.BytesIO(raw))
    try:
        names = set()
        for info in zf.infolist():
            name = _relative(info.filename[:-1] if info.is_dir() else info.filename)
            if name.casefold() in names or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"包内成员重复或为链接：{info.filename}")
            names.add(name.casefold())
        if "mod.json" not in zf.namelist():
            raise ValueError("MOD 包缺少 mod.json")
        return zf
    except Exception:
        zf.close()
        raise


class ModBuildWorkspace:
    """两阶段 worker 共用的工作区；directory 是自身临时根目录。"""

    def __init__(self, source_exe: str, output_exe: str,
                 selected_mods: list[ModInfo], allowed_configs: set[str] | None = None,
                 log_func=None):
        if not os.path.isabs(source_exe) or not os.path.isabs(output_exe):
            raise ValueError("输入和输出 EXE 必须使用绝对路径")
        self._original_exe = os.path.abspath(source_exe)
        self.source_exe = self._original_exe
        self.output_exe = os.path.abspath(output_exe)
        self._source_dir = os.path.dirname(self._original_exe)
        self._source_real = os.path.realpath(self._source_dir)
        self._output_dir = os.path.dirname(self.output_exe)
        _relative(os.path.basename(self._original_exe))
        _relative(os.path.basename(self.output_exe))
        if not os.path.isfile(self._original_exe):
            raise FileNotFoundError(f"源 EXE 不存在：{self._original_exe}")
        self._check_output()
        self._output_real = os.path.realpath(self._output_dir)
        self._selected = list(selected_mods)
        self._allowed = None if allowed_configs is None else set(allowed_configs)
        self._log = log_func or (lambda message: None)
        self._temporary = tempfile.TemporaryDirectory(prefix="tks_mod_build_")
        self.directory = self._temporary.name
        self._data_dir = os.path.join(self.directory, "data")
        self.build_exe = os.path.join(self.directory, "output", os.path.basename(self.output_exe))
        self.config_overrides = {}
        self.files = set()
        self._state = "new"
        self._targets = {}
        self._exe_targets = {"tks.exe", os.path.basename(self._original_exe).casefold()}

    def _check_output(self):
        for output, source in ((self._output_dir, self._source_dir),
                               (os.path.realpath(self._output_dir), self._source_real)):
            if _within(source, output):
                raise ValueError("输出目录不能是原版目录或其祖先")
            if _within(output, source):
                relative = os.path.relpath(output, source).replace("\\", "/")
                if relative.split("/")[0].casefold() != "dist":
                    raise ValueError("游戏树内只允许输出到 dist 及其子目录")
        if hasattr(self, "_output_real") and _key(os.path.realpath(self._output_dir)) != _key(self._output_real):
            raise ValueError("输出目录的真实路径已改变")
        if _key(os.path.realpath(self._source_dir)) != _key(self._source_real):
            raise ValueError("原版目录的真实路径已改变")
        _join(self._output_dir, os.path.basename(self.output_exe))
        if os.path.exists(self.output_exe) and not os.path.isfile(self.output_exe):
            raise ValueError("输出 EXE 目标不是文件")

    def _source_file(self, name, required=False):
        name = _relative(name)
        if name.split("/")[0].casefold() == "dist":
            raise ValueError("不能从已有 dist 读取原版数据")
        path = _join(self._source_dir, name)
        _clean_read(path)
        if os.path.isfile(path):
            return path
        if os.path.exists(path):
            raise ValueError(f"原版目标不是文件：{name}")
        if required:
            raise FileNotFoundError(f"差分所需原版文件不存在：{name}")
        return None

    def _reload(self, log):
        mods = []
        for selected in self._selected:
            if not selected.enabled:
                continue
            path = os.path.abspath(selected.path)
            _clean_read(path)
            raw = Path(path).read_bytes()
            with _archive(raw) as archive:
                if path.lower().endswith(".tksmodpak"):
                    entries = [n for n in archive.namelist() if n.lower().endswith(".tksmod")]
                    if not entries:
                        raise ValueError(f"合集没有可加载的 MOD：{path}")
                    for entry in entries:
                        with _archive(archive.read(entry)):
                            pass
                    loaded = mod_loader.expand_pak_mods(io.BytesIO(raw), log, allowed_configs=self._allowed)
                    if len(loaded) != len(entries):
                        raise ValueError(f"合集未能完整加载：{path}")
                else:
                    mod = mod_loader._load_single_mod(io.BytesIO(raw), log, allowed_configs=self._allowed)
                    if mod is None:
                        raise ValueError(f"MOD 加载失败：{path}")
                    mod._data_raw = raw
                    loaded = [mod]
            for mod in loaded:
                mod.path = path
                mods.append(mod)
        return mods

    def _validate_mods(self, mods):
        ids = {}
        formats = {}
        for mod in mods:
            if not isinstance(mod.mod_id, str) or not mod.mod_id.strip() or mod.mod_id in ids:
                raise ValueError(f"MOD 标识为空或重复：{mod.mod_id!r}")
            ids[mod.mod_id] = mod
            with _archive(mod._data_raw) as archive:
                for item in [*mod.components, *mod.resources]:
                    target = _relative(item.get("target", ""))
                    # 合并器的 DAT 分派使用大小写敏感的字典。
                    target = _KNOWN_NAMES.get(target.casefold(), target)
                    item["target"] = _register(self._targets, target)
                    internal = item.get("file", "")
                    _relative(internal)
                    if internal not in archive.namelist() or archive.getinfo(internal).is_dir():
                        raise ValueError(f"MOD '{mod.name}' 缺少成员：{internal}")
                for comp in mod.components:
                    diff = mod.data_files.get(comp["file"])
                    if not isinstance(diff, dict):
                        raise ValueError(f"组件差分不是对象：{comp['file']}")
                    kind = diff.get("patch_type") or ("text" if mod_loader._is_text_diff(diff) else diff.get("field_type", "record"))
                    mode = (kind, diff.get("block_type", "grp_section") if kind == "block_diff" else "")
                    old = formats.setdefault(comp["target"], mode)
                    if mode != old:
                        raise ValueError(f"同一目标使用了不兼容的差分格式：{comp['target']}")
                    if kind in ("block_diff", "grp_layer_diff"):
                        modified = diff.get("modified", {}) if kind == "grp_layer_diff" else diff.get("modified", [])
                        entries = list(modified.values()) if isinstance(modified, dict) else modified
                        for entry in [*entries, *diff.get("appended", [])]:
                            if "data_b64" in entry:
                                base64.b64decode(entry["data_b64"], validate=True)
                            if "bin" in entry:
                                member = _relative(entry["bin"])
                                if member not in archive.namelist():
                                    raise ValueError(f"图层差分缺少二进制成员：{member}")
        exe_resources = [res for mod in mods for res in mod.resources
                         if res["target"].casefold() in self._exe_targets]
        if len(exe_resources) > 1:
            raise ValueError("选择了多个 EXE 替换，无法安全选择烧录基准，请只保留一个")
        visiting, visited = set(), set()

        def visit(mod_id):
            if mod_id in visiting:
                raise ValueError(f"MOD 依赖形成循环：{mod_id}")
            if mod_id in visited:
                return
            visiting.add(mod_id)
            for dep in ids[mod_id].dependencies:
                if dep not in ids:
                    raise ValueError(f"MOD '{mod_id}' 缺少依赖：{dep}")
                visit(dep)
            visiting.remove(mod_id)
            visited.add(mod_id)

        for mod_id in ids:
            visit(mod_id)

    def _validate_blocks(self, mods):
        # 图层处理器有无日志跳过分支，必须在调用前验证其索引、跨度和二进制成员。
        counts, bases = {}, {}
        for mod in mods:
            for comp in mod.components:
                diff = mod.data_files[comp["file"]]
                kind = diff.get("patch_type")
                if kind not in ("block_diff", "grp_layer_diff"):
                    continue
                target = comp["target"]
                path = _join(self._data_dir, target)
                block_type = diff.get("block_type", "grp_section")
                if target not in counts:
                    if kind == "grp_layer_diff" or block_type == "grp_section":
                        result = mod_loader._load_grp_sections(path)
                        sections = result[0] if result else None
                    elif block_type == "jvm_block":
                        sections = mod_loader._load_jvg_blocks(path)
                    elif block_type in mod_loader._FIXED_RECORD_SIZES:
                        sections = mod_loader._load_fixed_record_blocks(path, mod_loader._FIXED_RECORD_SIZES[block_type])
                    else:
                        raise ValueError(f"不支持的块差分类型：{block_type}")
                    if sections is None:
                        raise ValueError(f"无法读取差分基准块：{target}")
                    bases[target] = sections
                    counts[target] = len(sections)
                modified = diff.get("modified", {} if kind == "grp_layer_diff" else [])
                entries = modified.items() if isinstance(modified, dict) else ((e.get("index", -1), e) for e in modified)
                for index, entry in entries:
                    index = int(index)
                    if not 0 <= index < counts[target]:
                        raise ValueError(f"块修改索引越界：{target} #{index}")
                    if "planes" in entry:
                        if kind != "grp_layer_diff" or index >= len(bases[target]) or mod_loader._grp_codec is None:
                            raise ValueError(f"无法应用图层差分：{target} #{index}")
                        decoded = mod_loader._grp_codec.decode_section(bases[target][index])
                        if decoded is None:
                            raise ValueError(f"无法解码图层基准：{target} #{index}")
                        for plane, spans in entry["planes"].items():
                            if plane not in ("A", "L1", "L2"):
                                raise ValueError(f"无效图层名称：{plane}")
                            size = decoded["total_px"] * (2 if plane == "A" else 1)
                            for start, values in spans:
                                if (not isinstance(start, int) or start < 0 or start + len(values) > size
                                        or any(not isinstance(v, int) or not 0 <= v <= 255 for v in values)):
                                    raise ValueError(f"图层跨度或值越界：{target} #{index}")
                    elif not entry.get("data_b64"):
                        raise ValueError(f"块修改缺少数据：{target} #{index}")
                for entry in diff.get("appended", []):
                    index = entry.get("index", -1)
                    if not isinstance(index, int) or index < 0:
                        raise ValueError(f"块追加索引无效：{target}")
                    member = entry.get("bin")
                    if member:
                        if kind != "grp_layer_diff" or not member.startswith("blobs/"):
                            raise ValueError(f"不支持的块二进制成员路径：{member}")
                    elif not entry.get("data_b64"):
                        raise ValueError(f"块追加缺少数据：{target}")
                    counts[target] = max(counts[target], index + 1)
                for index in diff.get("deleted_indices", []):
                    if not isinstance(index, int) or not 0 <= index < counts[target]:
                        raise ValueError(f"块删除索引越界：{target}")

    def prepare(self):
        """重载所选包并完整整合；失败后的工作区不能用于发布。"""
        if self._state == "ready":
            return
        if self._state != "new":
            raise RuntimeError("工作区已失败或已清理，请重新创建")
        self._state = "preparing"
        errors = []

        def strict_log(message):
            if re.search(r"\[(?:WARN|ERROR)\]", message, re.I):
                errors.append(message)
            self._log(message)

        def check_errors():
            if errors:
                raise ValueError("MOD 未能完整整合：\n" + "\n".join(errors))

        try:
            self._check_output()
            self._source_file(os.path.basename(self._original_exe), required=True)
            mods = self._reload(strict_log)
            check_errors()
            self._validate_mods(mods)
            mods = mod_loader.resolve_dependencies(mods, strict_log)
            conflicts = mod_loader.detect_conflicts(mods, strict_log)
            if any(c.conflict_type == "explicit" for c in conflicts):
                raise ValueError("所选 MOD 存在显式互斥")
            if conflicts:
                self._log("普通冲突按依赖及加载顺序处理，后加载的 MOD 生效")
            copies = {}
            for mod in mods:
                for comp in mod.components:
                    target = comp["target"]
                    copies[target] = self._source_file(target, required=True)
                    diff = mod.data_files[comp["file"]]
                    needs_idx = (diff.get("patch_type") == "grp_layer_diff" or
                                 (diff.get("patch_type") == "block_diff" and
                                  diff.get("block_type", "grp_section") == "grp_section"))
                    if needs_idx:
                        idx = _register(self._targets, str(Path(target).with_suffix(".IDX")))
                        copies[idx] = self._source_file(idx, required=True)
                for res in mod.resources:
                    target = res["target"]
                    self._source_file(target)
                    if target.lower().endswith(".grp"):
                        idx = str(Path(target).with_suffix(".IDX"))
                        source = self._source_file(idx)
                        if source:
                            idx = _register(self._targets, idx)
                            copies.setdefault(idx, source)
                        elif idx.casefold() not in self._targets:
                            raise ValueError(f"GRP 资源缺少配套索引：{idx}")
            os.makedirs(self._data_dir)
            os.makedirs(os.path.dirname(self.build_exe))
            for target, source in copies.items():
                destination = _join(self._data_dir, target)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copyfile(source, destination)
            self._validate_blocks(mods)
            merged = mod_loader.merge_mods(mods, self._data_dir, strict_log)
            check_errors()
            mod_loader.apply_mod_data(merged, self._data_dir, strict_log)
            check_errors()
            for target in self._targets.values():
                if not os.path.isfile(_join(self._data_dir, target)):
                    raise ValueError(f"整合结果缺少文件：{target}")
            exe_name = next((self._targets[key] for key in ("tks.exe", os.path.basename(self._original_exe).casefold())
                             if key in self._targets), None)
            self.source_exe = _join(self._data_dir, exe_name) if exe_name else self._original_exe
            self.files = {n for n in self._targets.values() if n.casefold() not in self._exe_targets}
            self.config_overrides = dict(merged.config_overrides)
            self._state = "ready"
            self._log(f"MOD 暂存整合完成：{len(self.files)} 个数据及资源文件，原版未修改")
        except Exception:
            self.files.clear()
            self.config_overrides.clear()
            self.source_exe = self._original_exe
            self._state = "failed"
            raise

    def resolve_file(self, name: str) -> str | None:
        name = _relative(name)
        if self._state != "ready":
            raise RuntimeError("请先成功完成 MOD 暂存整合")
        target = self._targets.get(name.casefold())
        if target:
            path = _join(self._data_dir, target)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"暂存整合文件已丢失：{target}")
            return path
        return self._source_file(name)

    def _old_files(self):
        path = _join(self._output_dir, _MANIFEST)
        if not os.path.exists(path):
            return set()
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or value.get("version") != 1
                    or not isinstance(value.get("files"), list)):
                raise ValueError("清单格式无效")
            names = {}
            for name in value["files"]:
                canonical = _relative(name)
                if canonical.casefold() in names:
                    raise ValueError("清单包含重复路径")
                _register(names, canonical)
                _join(self._output_dir, canonical)
            return set(names.values())
        except (ValueError, TypeError, OSError) as exc:
            raise ValueError(f"旧构建清单无效，未修改输出目录：{exc}") from exc

    def publish(self, resources: list[tuple[str, str]], tool_dir: str = "") -> list[str]:
        """发布全部成品，返回绝对路径列表（包含清单）；失败回滚旧 dist。"""
        if self._state != "ready":
            raise RuntimeError("请先成功完成 MOD 暂存整合")
        self._check_output()
        if _link(self.build_exe) or not os.path.isfile(self.build_exe) or not os.path.getsize(self.build_exe):
            raise ValueError("尚未生成可发布的 EXE")
        names, sources = {}, {}

        def add(name, source):
            name = _relative(name)
            if name.casefold() in names:
                raise ValueError(f"发布目标同名冲突：{name}")
            name = _register(names, name)
            sources[name] = source

        for name in sorted(self.files):
            add(name, _join(self._data_dir, name))
        add(os.path.basename(self.output_exe), self.build_exe)
        seen_resources = set()
        for name, source in resources:
            name = _relative(name)
            key = name.casefold()
            if key in self._exe_targets or key == os.path.basename(self.output_exe).casefold():
                raise ValueError(f"补丁资源不能覆盖 EXE：{name}")
            if key in seen_resources:
                raise ValueError(f"补丁资源目标重复：{name}")
            seen_resources.add(key)
            if key in self._targets:
                self._log(f"补丁资源使用暂存 MOD 成品：{name}")
                continue
            add(name, os.path.abspath(source))
        if tool_dir:
            tool_dir = os.path.abspath(tool_dir)
            if not os.path.isdir(tool_dir) or _link(tool_dir):
                raise ValueError(f"工具目录不存在或为链接：{tool_dir}")

            def walk_error(error):
                raise error

            for root, dirs, files in os.walk(tool_dir, onerror=walk_error):
                for directory in dirs:
                    if _link(os.path.join(root, directory)):
                        raise ValueError(f"工具目录不能包含链接：{directory}")
                for filename in sorted(files):
                    path = os.path.join(root, filename)
                    name = _relative(os.path.relpath(path, tool_dir))
                    if name.casefold() in self._exe_targets:
                        raise ValueError(f"工具不能输出未烧录的原版名称 EXE：{name}")
                    add(name, path)
        old = self._old_files()
        for name in set(sources) | old:
            destination = _join(self._output_dir, name)
            if os.path.exists(destination) and not os.path.isfile(destination):
                raise ValueError(f"发布目标不是文件：{name}")
        # 所有外部资源先复制完毕，才允许创建或修改输出目录。
        with tempfile.TemporaryDirectory(prefix="publish_", dir=self.directory) as staged:
            for name, source in sources.items():
                if not _within(source, self.directory):
                    _clean_read(source)
                    if _within(os.path.realpath(source), os.path.realpath(self._output_dir)):
                        raise ValueError(f"不能从已有输出目录读取发布资源：{source}")
                destination = _join(staged, name)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copyfile(source, destination)
            manifest = {"version": 1, "files": sorted(sources)}
            Path(staged, _MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self._commit(staged, set(sources), old)
        self._log(f"发布完成：{self._output_dir}，原版未修改")
        return result

    def _commit(self, staged, current, old):
        self._check_output()
        created_dirs, backups, installed = [], [], []
        transaction = None

        def mkdir(path):
            missing = []
            while not os.path.exists(path):
                missing.append(path)
                path = os.path.dirname(path)
            for directory in reversed(missing):
                os.mkdir(directory)
                created_dirs.append(directory)

        try:
            mkdir(self._output_dir)
            transaction = tempfile.mkdtemp(prefix=".tks_publish_", dir=self._output_dir)
            # 同卷临时文件配合 replace，既支持跨盘输出，也不写坏旧文件的硬链接原件。
            prepared = {}
            for index, name in enumerate(sorted(current | {_MANIFEST})):
                path = os.path.join(transaction, f"new_{index}")
                shutil.copyfile(_join(staged, name), path)
                prepared[name] = path
            touched = sorted(current | old | {_MANIFEST}, key=lambda n: (n == _MANIFEST, n.casefold()))
            touched_keys = set()
            for name in touched:
                if name.casefold() in touched_keys:
                    continue
                touched_keys.add(name.casefold())
                self._check_output()
                destination = _join(self._output_dir, name)
                if os.path.exists(destination):
                    if not os.path.isfile(destination):
                        raise ValueError(f"发布目标不是文件：{name}")
                    backup = os.path.join(transaction, f"old_{len(backups)}")
                    os.replace(destination, backup)
                    backups.append((destination, backup))
                new_name = next((n for n in prepared if n.casefold() == name.casefold()), None)
                if new_name is not None:
                    destination = _join(self._output_dir, new_name)
                    mkdir(os.path.dirname(destination))
                    os.replace(prepared[new_name], destination)
                    installed.append(destination)
        except Exception as exc:
            rollback_errors = []
            for destination in reversed(installed):
                try:
                    os.unlink(destination)
                except OSError as error:
                    rollback_errors.append(str(error))
            for destination, backup in reversed(backups):
                try:
                    os.replace(backup, destination)
                except OSError as error:
                    rollback_errors.append(str(error))
            if rollback_errors:
                raise RuntimeError(f"发布失败且回滚未完成，备份保留在 {transaction}：{rollback_errors}") from exc
            if transaction:
                shutil.rmtree(transaction)
            for directory in reversed(created_dirs):
                os.rmdir(directory)
            self._log("发布失败，已回滚输出目录，原版未修改")
            raise
        shutil.rmtree(transaction)
        return [_join(self._output_dir, name) for name in sorted(current | {_MANIFEST})]

    def cleanup(self):
        self._temporary.cleanup()
        self._state = "closed"
