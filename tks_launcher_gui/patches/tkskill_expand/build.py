"""只读合成并校验固定片段，返回代码、入口、位点和重定位表。"""

import hashlib
import json
from pathlib import Path


_PART_FILES = (
    Path(__file__).resolve().with_name("state.json"),
    Path(__file__).resolve().parent.parent / "tksave_expand" / "persistence.json",
)
_GLOBALS_KEYS = ("globals_ph_base", "globals_rebase_span", "globals_alloc_size")


def assemble() -> tuple[bytes, dict[str, int], list[dict], list[int]]:
    """读取两包片段并校验布局、入口、位点和显式 globals 重定位。"""
    parts = [json.loads(path.read_text(encoding="utf-8")) for path in _PART_FILES]
    owners = [part for part in parts if "link_size" in part]
    if len(owners) != 1 or owners[0]["link_size"] != 0x2400:
        raise ValueError("固定链接布局必须有唯一的 9216 字节所有者")
    owner = owners[0]
    if not all(key in owner for key in _GLOBALS_KEYS):
        raise ValueError("布局所有者必须声明完整的 globals 布局")
    size = owner["link_size"]
    code, coverage = bytearray(size), bytearray(size)
    entries, sites, relocations = {}, [], []
    for part in parts:
        if part["type"] != "patch_sites" or part["link_group"] != "skill_state":
            raise ValueError("片段必须属于 skill_state 位点链接组")
        if any(key in part for key in ("cave_code", "globals_initializer", "requires", "supersedes")):
            raise ValueError("片段不得包含整体代码或根包初始化、依赖与替代声明")
        if part is not owner and any(key in part for key in _GLOBALS_KEYS):
            raise ValueError("globals 布局只能由唯一所有者声明")
        spans = []
        for fragment in part["cave_fragments"]:
            offset = fragment["offset"]
            payload = bytes.fromhex(fragment["code"])
            if type(offset) is not int or offset < 0 or not payload or offset + len(payload) > size:
                raise ValueError("片段为空或超出固定链接布局")
            end = offset + len(payload)
            if any(coverage[offset:end]):
                raise ValueError("固定链接片段重叠")
            code[offset:end] = payload
            coverage[offset:end] = b"\x01" * len(payload)
            spans.append((offset, end))
        for name, offset in part["cave_entries"].items():
            if name in entries:
                raise ValueError(f"入口名称重复：{name}")
            if type(offset) is not int or not any(start <= offset < end for start, end in spans):
                raise ValueError(f"入口不属于声明它的片段：{name}")
            entries[name] = offset
        for offset in part["globals_relocations"]:
            if type(offset) is not int or not any(start <= offset and offset + 4 <= end for start, end in spans):
                raise ValueError("重定位必须完整落在所属片段内")
            relocations.append(offset)
        sites.extend(part["sites"])
    if not all(coverage):
        raise ValueError("固定链接片段未完整覆盖布局")
    if len(set(relocations)) != len(relocations):
        raise ValueError("globals 重定位位置重复")
    base = int(owner["globals_ph_base"], 0)
    span = int(owner["globals_rebase_span"], 0)
    for offset in relocations:
        value = int.from_bytes(code[offset:offset + 4], "little")
        if not base <= value < base + span:
            raise ValueError(f"重定位值超出 globals 范围：{offset:#x}")
    rvas = [int(site["rva"], 0) for site in sites]
    if len(set(rvas)) != len(rvas):
        raise ValueError("位点 RVA 重复")
    for site in sites:
        if "ref" in site and site["ref"] not in entries:
            raise ValueError(f"位点引用未声明入口：{site['ref']}")
    return bytes(code), entries, sorted(sites, key=lambda site: int(site["rva"], 0)), sorted(relocations)


if __name__ == "__main__":
    blob, entries, sites, relocations = assemble()
    print(json.dumps({
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "entries": len(entries),
        "sites": len(sites),
        "relocations": len(relocations),
    }))
