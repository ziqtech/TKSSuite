"""补丁包的纯数据准备、选择迁移与固定布局链接。"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .config_loader import (
    EffectivePatches, PatchDef, patch_metadata, resolve_effective_patches,
)
from .tkspatch_loader import load_package_module, parse_patch_dict, validate_tkspatch_dict


def migrate_patch_states(patches, states):
    result = dict(states)
    for patch in patches:
        targets = [(patch.id, patch_metadata(patch, "migrate_from", []))]
        targets.extend((option["id"], option.get("legacy_ids", []))
                       for option in patch_metadata(patch, "options", []))
        for target, aliases in targets:
            present = [alias for alias in aliases if alias in result]
            if target not in result and present:
                result[target] = any(result[alias] for alias in present)
            for alias in present:
                if alias != target:
                    result.pop(alias)
    return result


class PatchPlanError(ValueError):
    pass


@dataclass
class PatchPlan:
    patches: list[PatchDef]
    effective: EffectivePatches
    auto_enabled: dict[str, str] = field(default_factory=dict)
    resources: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ids(self):
        return self.effective.ids


class BundleContext:
    def __init__(self, patch, enabled_ids, selected, resolve_file, data_cache):
        self.patch = patch
        self.enabled_ids = frozenset(enabled_ids)
        self.enabled = patch.id in self.enabled_ids
        self._selected = selected
        self._resolve_file = resolve_file
        self._data_cache = data_cache

    def option(self, option_id):
        return option_id in self._selected

    def data_path(self, name):
        path = self._resolve_file(name)
        return os.path.abspath(path) if path and os.path.isfile(path) else None

    def read_data(self, name, *, compressed=False):
        path = self.data_path(name)
        if not path:
            raise ValueError(f"{self.patch.id}: 缺少数据文件 {name}")
        key = (path, compressed)
        if key not in self._data_cache:
            with open(path, "rb") as stream:
                data = stream.read()
            if compressed:
                from editor_utils.lzss import lzss_decompress_dat
                data = lzss_decompress_dat(data)
            self._data_cache[key] = data
        return self._data_cache[key]

    def data_size(self, name, *, compressed=False):
        return len(self.read_data(name, compressed=compressed))

    def read_json(self, name):
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in str(path):
            raise ValueError(f"{self.patch.id}: 非法包内资源路径 {name}")
        try:
            return json.loads(self.patch.package_files[str(path)].decode("utf-8"))
        except KeyError as exc:
            raise ValueError(f"{self.patch.id}: 缺少包内资源 {name}") from exc


def _load_bundle(patch):
    name = patch_metadata(patch, "prepare_file", "prepare.py")
    module = load_package_module(patch, name)
    if not callable(getattr(module, "prepare", None)):
        raise ValueError(f"{patch.id}: 包脚本必须声明 prepare(context)")
    return module


def _link_site_group(group, parts):
    owners = [part for part in parts if patch_metadata(part, "link_size", 0)]
    if len(owners) != 1:
        raise ValueError(f"链接组 {group} 必须有且仅有一个布局所有者")
    owner = owners[0]
    size = patch_metadata(owner, "link_size")
    if not isinstance(size, int) or not 0 < size <= 0x100000:
        raise ValueError(f"链接组 {group} 的代码大小无效")
    code = bytearray(size)
    coverage = bytearray(size)
    entries, sites, relocations, package_ids = {}, [], [], set()
    for part in parts:
        if part is not owner and part.globals_alloc_size:
            raise ValueError(f"链接组 {group} 不能重复分配 globals")
        spans = []
        for fragment in patch_metadata(part, "cave_fragments", []):
            offset = fragment["offset"]
            payload = bytes.fromhex(fragment["code"])
            if type(offset) is not int or not payload:
                raise ValueError(f"链接组 {group}: {part.id} 片段偏移或内容无效")
            end = offset + len(payload)
            if offset < 0 or end > size or any(coverage[offset:end]):
                raise ValueError(f"链接组 {group}: {part.id} 片段越界或重叠")
            code[offset:end] = payload
            coverage[offset:end] = b"\x01" * len(payload)
            spans.append((offset, end))
        for name, offset in part.cave_entries.items():
            if name in entries or not any(start <= offset < end for start, end in spans):
                raise ValueError(f"链接组 {group}: 入口 {name} 重复或不在所属片段内")
            entries[name] = offset
        sites.extend(part.sites)
        for offset in part.globals_relocations or []:
            if not any(start <= offset and offset + 4 <= end for start, end in spans):
                raise ValueError(f"链接组 {group}: 重定位不在所属片段内")
            relocations.append(offset)
        package_ids.update(patch_metadata(part, "owners", []))
    if not all(coverage):
        raise ValueError(f"链接组 {group} 缺少代码片段")
    if len(set(relocations)) != len(relocations):
        raise ValueError(f"链接组 {group} 的 globals 重定位位置重复")
    for offset in relocations:
        if not 0 <= offset <= size - 4:
            raise ValueError(f"链接组 {group} 的重定位位置越界")
        value = int.from_bytes(code[offset:offset + 4], "little")
        windows = [(owner.globals_ph_base, owner.globals_rebase_span)]
        windows.extend((owner.globals_ph_base + off, span)
                       for off, span in owner.globals_extra_windows)
        if not any(base <= value < base + span for base, span in windows):
            raise ValueError(f"链接组 {group} 的重定位值不在 globals 范围内")
    linked = copy.deepcopy(owner)
    linked._cave_code_bytes = bytes(code)
    linked.sites = sites
    linked.cave_entries = entries
    linked.globals_relocations = sorted(relocations)
    linked._extra["owners"] = sorted(package_ids)
    return linked


def link_patch_operations(operations):
    groups = {}
    for operation in operations:
        group = patch_metadata(operation, "link_group")
        if group:
            if operation.type != "patch_sites":
                raise ValueError(f"{operation.id}: 仅位点操作支持代码链接")
            groups.setdefault(group, []).append(operation)
    result, emitted = [], set()
    for operation in operations:
        group = patch_metadata(operation, "link_group")
        if not group:
            result.append(operation)
        elif group not in emitted:
            result.append(_link_site_group(group, groups[group]))
            emitted.add(group)
    occupied = []
    for operation in result:
        if operation.type != "patch_sites":
            continue
        for site in operation.sites:
            start = int(str(site["rva"]), 0) if isinstance(site["rva"], str) else site["rva"]
            end = start + len(bytes.fromhex(site["expect"]))
            if any(start < other_end and other_start < end
                   for other_start, other_end in occupied):
                raise ValueError(f"{operation.id}: 位点 0x{start:X} 与其它操作重叠")
            occupied.append((start, end))
            if site.get("kind") in {"call", "push_imm"}:
                if site.get("ref") not in operation.cave_entries:
                    raise ValueError(f"{operation.id}: 未定义入口 {site.get('ref')}")
    result.sort(key=lambda operation: operation.type == "patch_data_expand")
    return result


def protected_operation_ids(plan):
    return {operation.id for operation in plan.patches
            if patch_metadata(operation, "owners")
            or operation.id in plan.effective.required_by}


def validate_runtime_plan(plan, code_buf, exe_profile=None):
    from .scanner import parse_pattern, pattern_scan, value_scan_excluding_rel32

    code = bytes(code_buf)
    protected = protected_operation_ids(plan)
    profile_name = getattr(exe_profile, "name", "original")
    skipped = getattr(exe_profile, "skip_patches", None) or set()

    def check_pattern(patch_id, pattern, count):
        parsed, wildcards = parse_pattern(pattern)
        hits = pattern_scan(code, parsed, wildcards)
        if count and len(hits) != count:
            raise PatchPlanError(f"{patch_id}: 位点预检命中 {len(hits)} 处，预期 {count} 处")
        return hits

    for root in plan.effective.patches:
        if root.type != "bundle":
            continue
        if (root.id in skipped or root.profile_rules.get(
                profile_name, root.profile_rules.get("_default", "apply")) == "skip"):
            raise PatchPlanError(f"{root.id}: 当前游戏版本禁用了完整补丁包")
    for operation in plan.patches:
        if operation.id not in protected:
            continue
        owners = set(patch_metadata(operation, "owners", []))
        if (operation.id in skipped or owners & skipped or operation.profile_rules.get(
                profile_name, operation.profile_rules.get("_default", "apply")) == "skip"):
            raise PatchPlanError(f"{operation.id}: 当前游戏版本禁用了包内操作或依赖")
        if operation.type == "patch_sites":
            for site in operation.sites:
                rva = int(str(site["rva"]), 0) if isinstance(site["rva"], str) else site["rva"]
                offset = rva - 0x1000
                expected = bytes.fromhex(site["expect"])
                if offset < 0 or code[offset:offset + len(expected)] != expected:
                    raise PatchPlanError(f"{operation.id}: {site.get('tag', '')} 原始字节不符，RVA 0x{rva:X}")
        elif operation.type == "patch_bytes":
            patterns = operation.patterns or [{"pattern": operation.pattern,
                                               "expect_count": operation.expect_count}]
            for entry in patterns:
                check_pattern(operation.id, entry["pattern"], entry.get("expect_count", 0))
        elif operation.type == "cave_hook":
            check_pattern(operation.id, operation.hook_pattern or operation.pattern,
                          operation.hook_expect_count)
        elif operation.type == "patch_imm32":
            if operation.value_scan:
                count = len(value_scan_excluding_rel32(code, operation.expect_value))
                if operation.expect_count and count != operation.expect_count:
                    raise PatchPlanError(f"{operation.id}: 大小引用命中 {count} 处，预期 {operation.expect_count} 处")
            else:
                patterns = operation.patterns or [{"pattern": operation.pattern,
                                                   "expect_count": operation.expect_count}]
                for entry in patterns:
                    check_pattern(operation.id, entry["pattern"], entry.get("expect_count", 0))
        elif operation.type == "patch_data_expand":
            path = patch_metadata(operation, "data_path", operation.data_file)
            if not path or not os.path.isfile(path):
                raise PatchPlanError(f"{operation.id}: 缺少数据文件 {operation.data_file}")
            with open(path, "rb") as stream:
                data = stream.read()
            if operation.needs_lzss:
                from editor_utils.lzss import lzss_decompress_dat
                data = lzss_decompress_dat(data)
            if operation.activate_if_expanded and len(data) <= operation.old_size:
                continue
            if not value_scan_excluding_rel32(code, operation.old_base):
                raise PatchPlanError(f"{operation.id}: 缺少数据表基址引用")
            if patch_metadata(operation, "redirect_size", True) and operation.pattern:
                check_pattern(operation.id, operation.pattern, operation.expect_count)
            for entry in operation.bytes_patches:
                check_pattern(operation.id, entry["pattern"], entry.get("expect_count", 0))


def build_patch_plan(patches, selected=None, disabled=None, resolve_file=None, log_func=None):
    log = log_func or (lambda _: None)
    resolve_file = resolve_file or (lambda name: os.path.abspath(name))
    if len({patch.id for patch in patches}) != len(patches):
        raise ValueError("补丁 ID 重复")
    if selected is None:
        selection = {patch.id for patch in patches if patch.default_checked}
        for patch in patches:
            selection.update(option["id"] for option in patch_metadata(patch, "options", [])
                             if option.get("default", False))
    else:
        selection = {key for key, value in migrate_patch_states(
            patches, dict.fromkeys(selected, True)).items() if value}
    disabled = set(disabled or ())
    modules, data_cache, automatic = {}, {}, {}
    for patch in patches:
        if patch.type != "bundle":
            continue
        module = modules[patch.id] = _load_bundle(patch)
        detect = getattr(module, "detect", None)
        if callable(detect):
            context = BundleContext(patch, selection, selection, resolve_file, data_cache)
            reason = detect(context)
            if reason:
                if patch.id in disabled:
                    raise ValueError(f"{patch.name or patch.id} 已禁用，但数据要求启用：{reason}")
                selection.add(patch.id)
                automatic[patch.id] = str(reason)
                log(f"  [AUTO] {patch.name or patch.id}: {reason}")
    effective = resolve_effective_patches(patches, selection, disabled)
    operations, resources = [], []
    roots = list(effective.patches)
    roots.extend(patch for patch in patches
                 if patch.id not in effective.ids and patch.id not in disabled
                 and patch.type == "bundle" and patch_metadata(patch, "baseline", False))
    for patch in roots:
        if patch.type != "bundle":
            operation = copy.deepcopy(patch)
            if operation.data_file:
                path = resolve_file(operation.data_file)
                if path:
                    operation._extra["data_path"] = os.path.abspath(path)
            operations.append(operation)
            continue
        context = BundleContext(patch, effective.ids, selection, resolve_file, data_cache)
        raw_operations = modules[patch.id].prepare(context)
        if not isinstance(raw_operations, list):
            raise ValueError(f"{patch.id}: prepare 必须返回操作列表")
        for raw in raw_operations:
            errors = validate_tkspatch_dict(raw, patch.source_path)
            if errors:
                raise ValueError(f"{patch.id}: 内部操作无效：{'; '.join(errors)}")
            operation = parse_patch_dict(raw, patch.source_path)
            if operation.type == "bundle":
                raise ValueError(f"{patch.id}: 内部操作不能再次声明 bundle")
            operation.optional = False
            operation._extra["owners"] = [patch.id]
            if operation.data_file:
                path = context.data_path(operation.data_file)
                if path:
                    operation._extra["data_path"] = path
            operations.append(operation)
        if context.enabled:
            for name in patch_metadata(patch, "resources", []):
                path = context.data_path(name)
                if path and (name, path) not in resources:
                    resources.append((name, path))
    if len({operation.id for operation in operations}) != len(operations):
        raise ValueError("补丁包内部操作 ID 重复")
    linked = link_patch_operations(operations)
    for dependency, parent in effective.required_by.items():
        log(f"  [REQUIRES] {parent} -> {dependency}")
    return PatchPlan(linked, effective, automatic, resources)
