"""Conservative preflight for code ranges declared by patch operations."""
from __future__ import annotations

import json
import os

from .config_loader import patch_metadata
from .scanner import parse_pattern, pattern_scan, value_scan_excluding_rel32


_FONT_OUTLINE_VARIANTS = (
    ("8B 15 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 52 E8", 7, 9),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 15 {ptr} 52 E8", 1, 3),
    ("A1 {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 50 E8", 6, 8),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} A1 {ptr} 50 E8", 1, 3),
    ("8B 0D {ptr} 6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 51 E8", 7, 9),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A ?? 6A {ft} 8B 0D {ptr} 51 E8", 1, 3),
)
_FONT_MENU_VARIANTS = (
    ("8B 15 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 52 E8", 17, 7, 9),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 8B 15 08 5B 75 00 52 E8", 11, 1, 3),
    ("A1 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 50 E8", 16, 6, 8),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 A1 08 5B 75 00 50 E8", 11, 1, 3),
    ("8B 0D 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 51 E8", 17, 7, 9),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 18 6A 02 8B 0D 08 5B 75 00 51 E8", 11, 1, 3),
)
_FONT_TOOLTIP_VARIANTS = (
    ("8B 15 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 52 E8", 17),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 8B 15 08 5B 75 00 52 E8", 11),
    ("A1 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 50 E8", 16),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 A1 08 5B 75 00 50 E8", 11),
    ("8B 0D 08 5B 75 00 6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 51 E8", 17),
    ("6A ?? 6A ?? 6A ?? 6A ?? 6A 10 6A 00 8B 0D 08 5B 75 00 51 E8", 11),
)


def _patch_config(operation, overrides):
    key = os.path.splitext(os.path.basename(operation.json_file or ""))[0]
    if overrides and key in overrides:
        return overrides[key]
    try:
        with open(operation.json_file, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def validate_write_conflicts(plan, code_buf, config_overrides=None,
                             exe_profile=None, code_start_addr=0x401000,
                             base_addr=0x400000):
    """在任何补丁改动进程前, 拒绝声明写入互相重叠的组合。

    写入分两类:
    - 声明型 (pattern/hook/site 锚定): 以调用时的缓冲为锚, 后执行的补丁
      若仍匹配并覆盖先前的写入, 属于真实冲突。
    - 重扫描型 reconciling (value_scan 类: imm32 value_scan、data_expand 的
      基址/区间/大小重定向): 引擎在该补丁自身执行时基于【已变更】的缓冲
      重新定位 (值已变则跳过/重定向, 如 zero_hit_ok)。data_expand 按约定
      排在最后执行, 其扫描天然与先前补丁的写入协调 — 例如 tkskill 的
      call hook 会整体替换内嵌 0x757Fxx 的原版 lea 指令, span 扫描届时
      不再命中该位点。因此重叠组合中【靠后执行的一方是重扫描型】时,
      以原始缓冲判定的重叠是误报, 不拦截; 靠后一方是声明型时仍然拦截。
    """
    code = bytes(code_buf)
    writes = []
    profile_name = getattr(exe_profile, "name", "original")
    skipped = getattr(exe_profile, "skip_patches", None) or set()
    order = {operation.id: index for index, operation in enumerate(plan.patches)}

    def add(operation, offset, size, label, reconciling=False):
        if size > 0 and 0 <= offset and offset + size <= len(code):
            start_rva = code_start_addr - base_addr + offset
            writes.append((operation, start_rva, start_rva + size, label,
                           reconciling))

    def scan(pattern):
        parsed, wildcards = parse_pattern(pattern)
        return pattern_scan(code, parsed, wildcards)

    def add_pattern_bytes(operation, pattern, replacements, label):
        for hit in scan(pattern):
            for byte_offset in replacements:
                add(operation, hit + int(byte_offset), 1, label)

    def add_hook(operation, pattern, expect_count, hook_offset, hook_size,
                 fallback_rva, label, fallback_on_mismatch=False):
        hits = scan(pattern) if pattern else []
        if expect_count and len(hits) != expect_count:
            if (not hits or fallback_on_mismatch) and fallback_rva:
                hits = [fallback_rva - 0x1000 - hook_offset]
            else:
                return
        for hit in hits:
            add(operation, hit + hook_offset, hook_size, label)

    def add_declared_byte_patches(operation, entries):
        for index, entry in enumerate(entries or []):
            pattern = entry.get("pattern", "")
            if pattern:
                add_pattern_bytes(operation, pattern,
                                  (entry.get("replace") or {}).keys(),
                                  f"bytes_patches[{index}]")

    def active(operation):
        rule = operation.profile_rules.get(
            profile_name, operation.profile_rules.get("_default", "apply"))
        return operation.id not in skipped and rule != "skip"

    def config_data(operation):
        return _patch_config(operation, config_overrides)

    def add_font_config(operation):
        renderers = config_data(operation).get("renderers", {})
        pointer = {"main": "04 5B 75 00", "menu_name_font": "08 5B 75 00",
                   "tooltip_font": "08 5B 75 00"}
        original = {"main": None, "menu_name_font": 2, "tooltip_font": 0}
        for name, ptr_offset, exclude_special in (
                ("main", 4, False), ("menu_name_font", 8, True),
                ("tooltip_font", 8, False)):
            renderer = renderers.get(name, {})
            if "outline" not in renderer:
                continue
            outline = int(renderer["outline"])
            ft = "??" if original[name] is None else f"{original[name]:02X}"
            ptr = pointer[name]
            for pattern, a7_offset, a6_offset in _FONT_OUTLINE_VARIANTS:
                pattern = pattern.format(ptr=ptr, ft=ft)
                for hit in scan(pattern):
                    if exclude_special:
                        a7_value, a6_value = code[hit + a7_offset], code[hit + a6_offset]
                        if a6_value == 0 or (a7_value == 1 and a6_value == 1
                                             and not pattern.startswith("8B 15")):
                            continue
                    if code[hit + a7_offset] != outline:
                        add(operation, hit + a7_offset, 1, f"{name}.outline")
        main = renderers.get("main", {}).get("ftype", 1)
        if int(main) != 1:
            for hit in scan("6A ?? 6A 01 6A 00 6A 01 6A 10 6A 01 8B 15 04 5B 75 00"):
                add(operation, hit + 11, 1, "main.ftype")
        menu = int(renderers.get("menu_name_font", {}).get("ftype", 2))
        if menu != 2:
            for pattern, ftype_offset, a7_offset, a6_offset in _FONT_MENU_VARIANTS:
                for hit in scan(pattern):
                    a7_value, a6_value = code[hit + a7_offset], code[hit + a6_offset]
                    if a6_value == 0 or (a7_value == 1 and a6_value == 1
                                         and not pattern.startswith("8B 15")):
                        continue
                    add(operation, hit + ftype_offset, 1, "menu_name_font.ftype")
        tooltip = int(renderers.get("tooltip_font", {}).get("ftype", 0))
        if tooltip != 0:
            for pattern, ftype_offset in _FONT_TOOLTIP_VARIANTS:
                for hit in scan(pattern):
                    add(operation, hit + ftype_offset, 1, "tooltip_font.ftype")

    def add_animation_speed(operation):
        cfg = config_data(operation)
        function_groups = (
            ("status_animation", ((0x43339C, 512), (0x433690, 512),
                                   (0x433A38, 512), (0x434188, 512),
                                   (0x434D7C, 512), (0x445564, 512))),
            ("move_animation", ((0x43DE90, 512),)),
            ("idle_animation", ((0x43CA64, 512),)),
        )
        hits = scan("2B ?? 83 F8 3C")
        for key, functions in function_groups:
            if int(cfg.get(key, {}).get("frame_delay_ms", 60)) == 60:
                continue
            for address, length in functions:
                start = address - code_start_addr
                for hit in hits:
                    offset = hit + 4
                    if start <= hit < start + length and code[offset] == 0x3C:
                        add(operation, offset, 1, key)
        attack = cfg.get("attack_animation", {})
        if int(attack.get("base_frame_delay_ms", 60)) != 60:
            for hit in scan("0F BF 55 D6 8B 0D D0 7C 4E 00 83 C2 3C"):
                add(operation, hit + 12, 1, "attack.base_frame_delay_ms")
        if int(attack.get("extra_segment_delay_ms", 120)) != 120:
            for hit in scan("66 C7 45 D6 78 00"):
                add(operation, hit + 4, 2, "attack.extra_segment_delay_ms")
        if int(attack.get("extra_delay_decrement_ms", 30)) != 30:
            for hit in scan("66 83 45 D6 E2"):
                add(operation, hit + 4, 1, "attack.extra_delay_decrement_ms")
        if int(cfg.get("map_movement", {}).get("frame_delay_ms", 60)) != 60:
            for hit in scan("8B 15 D0 7C 4E 00 2B C2 83 F8 3C 0F 82"):
                add(operation, hit + 10, 1, "map_movement")

    for operation in plan.patches:
        if not active(operation):
            continue
        if operation.type == "patch_bytes":
            entries = operation.patterns or [{
                "pattern": operation.pattern,
                "replace": operation.replace,
            }]
            for index, entry in enumerate(entries):
                add_pattern_bytes(operation, entry.get("pattern", ""),
                                  (entry.get("replace") or {}).keys(),
                                  f"pattern[{index}]")

        elif operation.type == "patch_imm32":
            if operation.value_scan:
                new_value = None
                if operation.new_value_expr and not operation.new_value_expr.startswith("{"):
                    try:
                        new_value = int(operation.new_value_expr, 0)
                    except ValueError:
                        pass
                if new_value is None or new_value != operation.expect_value:
                    for hit in value_scan_excluding_rel32(code, operation.expect_value):
                        add(operation, hit, 4, "value_scan", reconciling=True)
            else:
                entries = operation.patterns or [{
                    "pattern": operation.pattern,
                    "value_offset": operation.value_offset,
                    "value_size": operation.value_size,
                }]
                for entry in entries:
                    width = int(entry.get("value_size", operation.value_size))
                    for hit in scan(entry.get("pattern", "")):
                        add(operation, hit + int(entry.get("value_offset", operation.value_offset)),
                            width, "patch_imm32")

        elif operation.type == "patch_sites":
            for site in operation.sites or []:
                rva = int(str(site["rva"]), 0) if isinstance(site["rva"], str) else int(site["rva"])
                add(operation, rva - 0x1000,
                    len(bytes.fromhex(site["expect"])), site.get("tag", "patch_sites"))

        elif operation.type == "cave_hook":
            add_hook(operation, operation.hook_pattern or operation.pattern,
                     operation.hook_expect_count, operation.hook_offset,
                     operation.hook_size, operation.fallback_rva, "cave_hook")

        elif operation.type == "patch_exp_lock":
            slots = config_data(operation).get("lock_slots", [])
            if any(slots):
                add_hook(operation, operation.hook_pattern, operation.hook_expect_count,
                         operation.hook_offset, operation.hook_size,
                         operation.fallback_rva, "patch_exp_lock")

        elif operation.type == "fixed_layout_cave":
            for index, hook in enumerate(operation.hooks or []):
                fallback = hook.get("fallback_rva", 0) or 0
                fallback = int(fallback, 0) if isinstance(fallback, str) else int(fallback)
                add_hook(operation, hook.get("pattern", ""),
                         int(hook.get("expect_count", 1) or 1), 0,
                         int(hook.get("hook_size", 0)), fallback,
                         f"hooks[{index}]", fallback_on_mismatch=True)
            add_declared_byte_patches(operation, operation.bytes_patches)

        elif operation.type == "patch_data_expand":
            path = patch_metadata(operation, "data_path", operation.data_file)
            if not path or not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as stream:
                    data = stream.read()
                if operation.needs_lzss:
                    from editor_utils.lzss import lzss_decompress_dat
                    data = lzss_decompress_dat(data)
            except (OSError, ValueError):
                continue
            if operation.activate_if_expanded and len(data) <= operation.old_size:
                continue
            if max(len(data), int(patch_metadata(operation, "buffer_cap", 0) or 0)) <= operation.old_size:
                continue
            for hit in value_scan_excluding_rel32(code, operation.old_base):
                add(operation, hit, 4, "data_base", reconciling=True)
            span = int(patch_metadata(operation, "redirect_base_span", 0) or 0)
            if span:
                for offset in range(max(0, len(code) - 3)):
                    value = int.from_bytes(code[offset:offset + 4], "little")
                    if operation.old_base < value < operation.old_base + span:
                        add(operation, offset, 4, "data_base_span", reconciling=True)
            if operation.pattern and patch_metadata(operation, "redirect_size", True):
                for hit in scan(operation.pattern):
                    add(operation, hit + operation.value_offset, 4, "data_size")
            elif patch_metadata(operation, "redirect_size", True):
                for hit in value_scan_excluding_rel32(code, operation.old_size):
                    add(operation, hit, 4, "data_size", reconciling=True)
            add_declared_byte_patches(operation, operation.bytes_patches)

        elif operation.type == "patch_summon_table":
            summon = config_data(operation)
            if any(key in summon for key in operation.data_keys or []):
                add(operation, operation.data_rva - 0x1000,
                    len(operation.data_keys), "data_table")
            for entry in operation.code_addrs or []:
                if entry.get("key") not in summon:
                    continue
                rva = int(str(entry["rva"]), 16) if isinstance(entry["rva"], str) else int(entry["rva"])
                add(operation, rva - 0x1000, 2, "code_addrs")
            if operation.random_hook_pattern and any(
                    isinstance(summon.get(f"{key}_random"), list) and summon[f"{key}_random"]
                    for key in operation.data_keys or []):
                add_hook(operation, operation.random_hook_pattern,
                         operation.random_hook_expect_count, 0,
                         operation.random_hook_size, 0, "random_hook")
            for index, hook in enumerate(operation.random2_hooks or []):
                key = hook.get("json_key", "")
                if not (isinstance(summon.get(key), list) and summon[key]):
                    continue
                add_hook(operation, hook.get("pattern", ""),
                         int(hook.get("expect_count", 1) or 1), 0,
                         int(hook.get("hook_size", 0)), 0, f"random2_hooks[{index}]")

        elif operation.type == "patch_font_config":
            add_font_config(operation)

        elif operation.type == "patch_animation_speed":
            add_animation_speed(operation)

        elif operation.type == "patch_drop_probability":
            # 配置存在时引擎对两处阈值无条件写入 (含写回原值), 按保守口径建模。
            # 0x441A2F/0x441AA2 为 VA, 需按 code_start 换算为缓冲偏移。
            if config_data(operation):
                add(operation, 0x441A2F - code_start_addr, 4, "normal_threshold")
                add(operation, 0x441AA2 - code_start_addr, 4, "rare_threshold")

    for index, (left, left_start, left_end, left_label, left_reconciles) in \
            enumerate(writes):
        for right, right_start, right_end, right_label, right_reconciles in \
                writes[index + 1:]:
            if left.id == right.id or left_start >= right_end or right_start >= left_end:
                continue
            # 重叠双方中【执行顺序靠后】的一方若是重扫描型 (value_scan 类),
            # 引擎会在其执行时基于已变更的缓冲重新判定, 与先前写入协调,
            # 原始缓冲上的重叠不构成冲突。
            later_reconciles = (right_reconciles if order[right.id] > order[left.id]
                                else left_reconciles)
            if later_reconciles:
                continue
            allowed_left = set(patch_metadata(left, "compatible_overlaps", []))
            allowed_right = set(patch_metadata(right, "compatible_overlaps", []))
            if right.id in allowed_left or left.id in allowed_right:
                continue
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            raise ValueError(
                f"补丁写入冲突: {left.id}/{left_label} 与 {right.id}/{right_label} "
                f"在 RVA 0x{start:X} 重叠 {end - start} 字节"
            )
