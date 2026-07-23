"""
MOD 深度合并器 — 将多个 .tksmod 深度合并为单个 .tksmod
========================================================================
与 mod_packer 的两个既有功能不同:
  - create_tksmodpak():     仅把多个 .tksmod 收纳进一个 .tksmodpak 合集(不合并内容)
  - merge_tksmod_files():   目标覆盖式合并(同一目标后者整体覆盖前者)
  - deep_merge_tksmods():   【本模块】数据文件级深度合并

当多个 .tksmod 修改同一个游戏文件(如都改 Mu.JVG)的不同帧 / 记录 / 条目时,
本模块把它们合并进同一个数据文件(如 Mu.JVG.json), 使互不冲突的改动共存;
当改动同一处(相同 index / id / 像素)时, 后加入者覆盖前者并给出警告。

支持的差异格式(与 core.mod_loader 的应用逻辑一一对应):
  - block_diff  (jvm_block / act_entry / grp_section): 按块索引合并 base64 数据
  - grp_layer_diff:                                    按区段 / 平面合并像素跨度
  - 文本差异     (TKD.dat / TKT.dat):                  按条目 id 合并
  - 定长记录 / 结构化 (TKMat/WarPC/.../WarData):        按记录索引合并字段
"""
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .mod_packer import MergeResult, read_tksmod_content


# ═══════════════════════════════════════════════════════════════
# 差异格式识别 (与 mod_loader.merge_mods 的分派顺序保持一致)
# ═══════════════════════════════════════════════════════════════

def _classify_diff(diff: Dict[str, Any]) -> str:
    """判定差异数据属于哪种合并类别。

    返回: "block" | "grp_layer" | "text" | "record" | "unknown"
    """
    if not isinstance(diff, dict):
        return "unknown"
    pt = diff.get("patch_type", "")
    if pt == "grp_layer_diff":
        return "grp_layer"
    if pt == "block_diff":
        return "block"
    # 文本差异: modified 为 dict, 含 deleted, 无 record_size
    modified = diff.get("modified")
    if isinstance(modified, dict) and "deleted" in diff and "record_size" not in diff:
        return "text"
    # 结构化(WarData) 与 定长记录(TKMat/WarPC/...) 的 modified 均为 list, 合并方式相同
    if diff.get("field_type") == "structured":
        return "record"
    if isinstance(modified, list):
        return "record"
    return "unknown"


def _extract_define_id(content: str) -> Optional[str]:
    """从一段 TKD 脚本块文本中提取 DEFINE 编号 (用于去重/删除)。"""
    for line in str(content).split('\n'):
        stripped = line.strip().rstrip('\r')
        if stripped.startswith('DEFINE') and not stripped.startswith('//'):
            parts = stripped.split(None, 1)
            if len(parts) > 1:
                return parts[1]
            break
    return None


# ═══════════════════════════════════════════════════════════════
# 各类差异的合并实现
# 每个函数接收 entries: List[(src_label, diff)] (按加载顺序), 返回合并后的 diff dict
# 冲突/覆盖信息写入 warnings。
# ═══════════════════════════════════════════════════════════════

def _merge_block_group(entries: List[Tuple[str, dict]], target: str,
                       warnings: List[str]) -> dict:
    """合并 block_diff (jvm_block / act_entry / grp_section)。

    按块索引合并: 不同索引共存; 相同索引后者覆盖。这正是「多个 MOD 改
    同一 JVG 的不同帧 → 合并为一个」的核心逻辑。
    """
    winner: Dict[int, dict] = {}     # index -> {"payload": {...}, "appended": bool}
    order: List[int] = []
    deleted: set = set()
    block_type = ""
    original_count = 0
    original_crc32 = None
    crc_mismatch = False
    overlap = 0

    for _src, diff in entries:
        if not block_type:
            block_type = diff.get("block_type", "")
        oc = diff.get("original_count")
        if isinstance(oc, int):
            original_count = max(original_count, oc)
        crc = diff.get("original_crc32")
        if crc is not None:
            if original_crc32 is None:
                original_crc32 = crc
            elif crc != original_crc32:
                crc_mismatch = True
        for di in diff.get("deleted_indices", []) or []:
            deleted.add(di)

        for group in ("modified", "appended"):
            is_app = (group == "appended")
            for entry in diff.get(group, []) or []:
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                if idx is None:
                    continue
                if "data_b64" in entry:
                    payload = {"data_b64": entry["data_b64"]}
                elif "bin" in entry:
                    payload = {"bin": entry["bin"]}
                else:
                    continue
                if idx in winner:
                    overlap += 1
                    is_app = is_app or winner[idx]["appended"]
                else:
                    order.append(idx)
                winner[idx] = {"payload": payload, "appended": is_app}

    modified, appended = [], []
    for idx in sorted(order):
        w = winner[idx]
        e = {"index": idx}
        e.update(w["payload"])
        (appended if w["appended"] else modified).append(e)

    merged: Dict[str, Any] = {
        "target": target,
        "patch_type": "block_diff",
        "block_type": block_type,
    }
    if original_count:
        merged["original_count"] = original_count
    if original_crc32 is not None:
        merged["original_crc32"] = original_crc32
    merged["modified"] = modified
    merged["appended"] = appended
    merged["deleted_indices"] = sorted(deleted)

    if overlap:
        warnings.append(f"[WARN] {target}: {overlap} 个块索引被多个模组同时修改，后加入者生效")
    if crc_mismatch:
        warnings.append(f"[WARN] {target}: 各模组的基准文件 CRC 不一致，"
                        f"请确认它们基于同一游戏版本导出")
    return merged


def _merge_record_group(entries: List[Tuple[str, dict]], target: str,
                        warnings: List[str]) -> dict:
    """合并定长记录 / 结构化差异 (modified/appended 均为 [{index, fields}])。

    按记录索引合并: 不同索引共存; 同一索引的不同字段共存(并集);
    同一字段后者覆盖。等价于 mod_loader 应用期的记录级合并行为。
    """
    fields_by_idx: Dict[int, dict] = {}
    appended_flag: Dict[int, bool] = {}
    order: List[int] = []
    idx_overlap: set = set()
    field_conflicts = 0
    top: Dict[str, Any] = {}

    for _src, diff in entries:
        if not top:
            top = {k: v for k, v in diff.items() if k not in ("modified", "appended")}
        for group in ("modified", "appended"):
            is_app = (group == "appended")
            for entry in diff.get(group, []) or []:
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                if idx is None:
                    continue
                fields = entry.get("fields", {})
                if not isinstance(fields, dict):
                    fields = {}
                if idx not in fields_by_idx:
                    fields_by_idx[idx] = {}
                    appended_flag[idx] = is_app
                    order.append(idx)
                else:
                    idx_overlap.add(idx)
                    field_conflicts += len(set(fields_by_idx[idx]) & set(fields))
                    appended_flag[idx] = appended_flag[idx] or is_app
                fields_by_idx[idx].update(fields)

    orig_count = top.get("original_count")
    if not isinstance(orig_count, int):
        orig_count = 0

    modified, appended = [], []
    for idx in sorted(order):
        e = {"index": idx, "fields": fields_by_idx[idx]}
        is_app = appended_flag[idx] or (orig_count > 0 and idx >= orig_count)
        (appended if is_app else modified).append(e)

    merged = dict(top)
    merged["modified"] = modified
    merged["appended"] = appended

    if idx_overlap:
        msg = f"[WARN] {target}: {len(idx_overlap)} 个记录槽位被多个模组同时修改"
        if field_conflicts:
            msg += f"，其中 {field_conflicts} 个字段直接覆盖(后者生效)"
        warnings.append(msg)
    return merged


def _merge_text_group(entries: List[Tuple[str, dict]], target: str,
                      warnings: List[str]) -> dict:
    """合并文本差异 (TKD.dat / TKT.dat), 按条目 id 合并。

    TKD.dat 的 appended 为脚本块文本 list; TKT.dat 的 appended 为 {id: text} dict。
    统一以 id -> (归属组, 内容) 处理, 再按目标文件类型序列化回对应格式。
    """
    is_tkd = target.lower() == "tkd.dat"
    present: Dict[str, Tuple[str, Any]] = {}   # id -> (group, content)
    order: List[str] = []
    del_set: set = set()
    id_overlap: set = set()
    top: Dict[str, Any] = {}

    def _put(key: str, group: str, content: Any):
        ks = str(key)
        if ks in present:
            id_overlap.add(ks)
        else:
            order.append(ks)
        present[ks] = (group, content)
        del_set.discard(ks)

    for _src, diff in entries:
        if not top:
            top = {k: v for k, v in diff.items()
                   if k not in ("modified", "appended", "deleted")}
        modified = diff.get("modified", {})
        if isinstance(modified, dict):
            for k, v in modified.items():
                _put(k, "modified", v)

        appended = diff.get("appended", {})
        if isinstance(appended, dict):
            for k, v in appended.items():
                _put(k, "appended", v)
        elif isinstance(appended, list):
            for content in appended:
                did = _extract_define_id(content)
                if did is None:
                    # 无法解析 id 的块: 用序号占位, 保证不丢失且不互相覆盖
                    did = f"__anon_{len(order)}"
                _put(did, "appended", content)

        for did in diff.get("deleted", []) or []:
            ks = str(did)
            del_set.add(ks)
            present.pop(ks, None)

    merged = dict(top)
    merged["modified"] = {k: c for k, (g, c) in present.items() if g == "modified"}
    if is_tkd:
        merged["appended"] = [c for k, (g, c) in present.items() if g == "appended"]
    else:
        merged["appended"] = {k: c for k, (g, c) in present.items() if g == "appended"}
    merged["deleted"] = sorted(del_set)

    if id_overlap:
        warnings.append(f"[WARN] {target}: {len(id_overlap)} 个文本条目被多个模组同时修改，"
                        f"后加入者生效")
    return merged


def _merge_grp_layer_group(entries: List[Tuple[str, dict]], target: str,
                           warnings: List[str]) -> dict:
    """合并 GRP 图层差分 (grp_layer_diff)。

    同时兼容混入的 block_diff / grp_section 整段替换: 统一输出为 grp_layer_diff,
    交由 mod_loader._merge_grp_layer_diff 应用(其原生支持 planes / data_b64 / 追加)。
    - 同区段不同平面共存; 同平面的跨度按加载顺序拼接(应用期后写覆盖先写)。
    - 整段 data_b64 替换按后者覆盖。
    """
    modified: Dict[str, dict] = {}
    mod_order: List[str] = []
    appended_winner: Dict[int, dict] = {}
    deleted: set = set()
    overlap = 0

    def _touch_full(sk: str, data_b64: str):
        nonlocal overlap
        if sk in modified:
            overlap += 1
        else:
            mod_order.append(sk)
        modified[sk] = {"data_b64": data_b64}

    for _src, diff in entries:
        m = diff.get("modified", {})
        if isinstance(m, dict):
            for sidx_str, entry in m.items():
                sk = str(sidx_str)
                if not isinstance(entry, dict):
                    continue
                if "data_b64" in entry:
                    _touch_full(sk, entry["data_b64"])
                elif "planes" in entry:
                    cur = modified.get(sk)
                    if cur is None or "planes" not in cur:
                        if cur is not None:
                            overlap += 1  # 之前是整段替换, 现改为平面差分
                        else:
                            mod_order.append(sk)
                        cur = {"planes": {}}
                        if "width" in entry:
                            cur["width"] = entry["width"]
                        if "height" in entry:
                            cur["height"] = entry["height"]
                        modified[sk] = cur
                    planes = cur["planes"]
                    for plane, spans in entry["planes"].items():
                        if plane in planes:
                            overlap += 1
                            planes[plane].extend(spans)   # 按顺序拼接, 应用期后写覆盖
                        else:
                            planes[plane] = list(spans)
        elif isinstance(m, list):
            # 混入的 block_diff/grp_section 整段替换
            for entry in m:
                if isinstance(entry, dict) and entry.get("index") is not None \
                        and "data_b64" in entry:
                    _touch_full(str(entry["index"]), entry["data_b64"])

        for entry in diff.get("appended", []) or []:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            if idx is None:
                continue
            if "data_b64" in entry:
                appended_winner[idx] = {"data_b64": entry["data_b64"]}
            elif "bin" in entry:
                appended_winner[idx] = {"bin": entry["bin"]}

        for di in diff.get("deleted_indices", []) or []:
            deleted.add(di)

    appended = []
    for idx in sorted(appended_winner):
        e = {"index": idx}
        e.update(appended_winner[idx])
        appended.append(e)

    merged = {
        "target": target,
        "patch_type": "grp_layer_diff",
        "modified": {sk: modified[sk] for sk in mod_order},
        "appended": appended,
        "deleted_indices": sorted(deleted),
    }
    if overlap:
        warnings.append(f"[WARN] {target}: {overlap} 处区段/平面被多个模组同时修改，"
                        f"重叠像素后者生效")
    return merged


def _merge_target_group(target: str, entries: List[Tuple[str, dict]],
                        warnings: List[str]) -> Optional[dict]:
    """按目标文件把多个模组的差异合并为一个差异 dict。

    entries 按加载顺序排列。单一来源时原样返回(保持格式与字节不变)。
    """
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0][1]

    kinds = {_classify_diff(d) for _, d in entries}
    kinds.discard("unknown")

    if "grp_layer" in kinds:
        return _merge_grp_layer_group(entries, target, warnings)
    if kinds == {"block"}:
        return _merge_block_group(entries, target, warnings)
    if kinds == {"record"}:
        return _merge_record_group(entries, target, warnings)
    if kinds == {"text"}:
        return _merge_text_group(entries, target, warnings)

    # 不兼容/无法识别的混合格式: 回退为整体后者覆盖(保留最后一个模组的差异)
    warnings.append(f"[WARN] {target}: 差异格式不兼容({', '.join(sorted(kinds)) or '未知'})，"
                    f"无法逐帧合并，改为保留最后加入模组的整体改动")
    return entries[-1][1]


# ═══════════════════════════════════════════════════════════════
# 合并分析 (供 UI 预览)
# ═══════════════════════════════════════════════════════════════

def _entry_indices(diff: dict) -> List[Any]:
    """提取一个差异中所有被改动的定位符 (index / 条目 id / 区段号)，用于重叠分析。"""
    kind = _classify_diff(diff)
    keys: List[Any] = []
    if kind in ("block", "record"):
        for group in ("modified", "appended"):
            for e in diff.get(group, []) or []:
                if isinstance(e, dict) and e.get("index") is not None:
                    keys.append(e["index"])
    elif kind == "grp_layer":
        m = diff.get("modified", {})
        if isinstance(m, dict):
            keys.extend(int(k) if str(k).lstrip('-').isdigit() else k for k in m.keys())
        for e in diff.get("appended", []) or []:
            if isinstance(e, dict) and e.get("index") is not None:
                keys.append(e["index"])
    elif kind == "text":
        m = diff.get("modified", {})
        if isinstance(m, dict):
            keys.extend(str(k) for k in m.keys())
        a = diff.get("appended", {})
        if isinstance(a, dict):
            keys.extend(str(k) for k in a.keys())
        elif isinstance(a, list):
            for c in a:
                did = _extract_define_id(c)
                if did is not None:
                    keys.append(did)
    return keys


def analyze_merge(mod_paths: List[str]) -> Dict[str, Any]:
    """分析将要合并的模组, 按目标文件汇总来源与改动定位符重叠情况。

    Returns:
        {
          "valid": bool, "error": str,
          "targets": [
             {"target": str, "kind": str, "sources": [filename,...],
              "total": int, "overlap": [locator,...], "is_resource": bool},
             ...
          ],
        }
    """
    result: Dict[str, Any] = {"valid": True, "error": "", "targets": []}
    # target_lower -> {"canonical","kind","per_source":[(filename,[keys])], "is_resource"}
    groups: Dict[str, dict] = {}
    order: List[str] = []

    for path in mod_paths:
        content = read_tksmod_content(path)
        if not content.valid:
            result["valid"] = False
            result["error"] = f"{content.filename}: {content.error}"
            return result
        fname = content.filename

        for comp in content.mod_json.get("components", []):
            target = comp.get("target", "")
            internal = comp.get("file", "")
            if not target:
                continue
            diff = content.data_files.get(internal, {})
            key = target.lower()
            g = groups.get(key)
            if g is None:
                g = {"canonical": target, "kind": _classify_diff(diff),
                     "per_source": [], "is_resource": False}
                groups[key] = g
                order.append(key)
            g["per_source"].append((fname, _entry_indices(diff)))

        for res in content.mod_json.get("resources", []):
            target = res.get("target", "")
            if not target:
                continue
            key = target.lower()
            g = groups.get(key)
            if g is None:
                g = {"canonical": target, "kind": "resource",
                     "per_source": [], "is_resource": True}
                groups[key] = g
                order.append(key)
            g["is_resource"] = True
            g["per_source"].append((fname, []))

    for key in order:
        g = groups[key]
        sources = [fn for fn, _ in g["per_source"]]
        # 统计跨来源的定位符重叠
        seen: Dict[Any, int] = {}
        for _fn, keys in g["per_source"]:
            for k in set(keys):
                seen[k] = seen.get(k, 0) + 1
        overlap = sorted((k for k, c in seen.items() if c > 1),
                         key=lambda x: (str(type(x)), str(x)))
        total = len(seen)
        result["targets"].append({
            "target": g["canonical"],
            "kind": g["kind"],
            "sources": sources,
            "total": total,
            "overlap": overlap,
            "is_resource": g["is_resource"],
        })
    return result


# ═══════════════════════════════════════════════════════════════
# 深度合并主入口
# ═══════════════════════════════════════════════════════════════

def _rewrite_bins(data_files: Dict[str, Any], mod_index: int,
                  blob_map: Dict[str, Tuple[str, str]], src_path: str):
    """把差异中引用的外部 blob 成员名改写为唯一名, 记录来源以便打包时复制。"""
    for diff in data_files.values():
        if not isinstance(diff, dict):
            continue
        for entry in diff.get("appended", []) or []:
            if isinstance(entry, dict) and entry.get("bin"):
                orig = entry["bin"]
                new_name = f"blobs/m{mod_index}_{os.path.basename(orig)}"
                entry["bin"] = new_name
                blob_map[new_name] = (src_path, orig)


def suggest_merge_output_name(metadata: Dict[str, Any]) -> str:
    """根据元数据建议合并输出文件名 (.tksmod)。"""
    name = (metadata.get("name") or "").strip()
    if name:
        safe = re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')
        if safe:
            return f"{safe}.tksmod"
    mod_id = metadata.get("id", "")
    if mod_id:
        return f"{mod_id}.tksmod"
    return "merged_mod.tksmod"


def deep_merge_tksmods(mod_paths: List[str], output_path: str,
                       metadata: Dict[str, Any],
                       preview_image_path: Optional[str] = None,
                       log_func=None) -> MergeResult:
    """将多个 .tksmod 深度合并为一个 .tksmod。

    合并策略:
      - 组件: 按目标文件(不区分大小写)分组; 同目标的多个差异按帧/记录/条目级合并
      - 资源: 按目标分组, 二进制整体替换, 后者覆盖前者
      - 白名单配置(summon_table/drop_probability): 后者覆盖前者
      - dependencies/conflicts: 合并去重; id_ranges: 键冲突后者覆盖; warpc_expand: 取最大

    Args:
        mod_paths:  要合并的 .tksmod 路径列表(按此顺序决定「后者覆盖」)
        output_path: 输出 .tksmod 路径
        metadata:    统一元数据 (id/name/version/author/description/type/load_order)
        preview_image_path: 可选预览图
        log_func:    日志回调
    """
    log = log_func or (lambda x: None)
    result = MergeResult()

    contents = []
    blob_map: Dict[str, Tuple[str, str]] = {}
    for i, path in enumerate(mod_paths):
        c = read_tksmod_content(path)
        if not c.valid:
            result.error = f"读取失败: {c.filename}: {c.error}"
            log(f"  [ERROR] {result.error}")
            return result
        _rewrite_bins(c.data_files, i, blob_map, c.path)
        contents.append(c)
        log(f"  读取: {c.filename} ({len(c.data_files)} 数据文件, "
            f"{len(c.resource_files)} 资源)")

    if not contents:
        result.error = "无有效的 .tksmod 文件"
        return result

    # ── 按目标(不区分大小写)分组组件差异 ──
    comp_groups: Dict[str, dict] = {}   # target_lower -> {"canonical","entries":[(fname,diff)]}
    comp_order: List[str] = []
    for c in contents:
        for comp in c.mod_json.get("components", []):
            target = comp.get("target", "")
            internal = comp.get("file", "")
            if not target or internal not in c.data_files:
                if target:
                    result.warnings.append(f"[WARN] {c.filename}: 组件 {target} 缺少数据文件，已跳过")
                continue
            key = target.lower()
            g = comp_groups.get(key)
            if g is None:
                g = {"canonical": target, "entries": []}
                comp_groups[key] = g
                comp_order.append(key)
            g["entries"].append((c.filename, c.data_files[internal]))

    merged_data_files: Dict[str, Any] = {}
    merged_components: List[Dict[str, str]] = []
    for key in comp_order:
        g = comp_groups[key]
        canonical = g["canonical"]
        merged_diff = _merge_target_group(canonical, g["entries"], result.warnings)
        if merged_diff is None:
            continue
        internal_path = f"data/{canonical}.json"
        merged_data_files[internal_path] = merged_diff
        merged_components.append({"file": internal_path, "target": canonical})
        srcs = len(g["entries"])
        log(f"  合并目标 {canonical}: {srcs} 个来源 → {internal_path}")

    # ── 资源: 按目标分组, 后者覆盖 ──
    res_groups: Dict[str, Tuple] = {}   # target_lower -> (canonical, content, res_internal)
    res_order: List[str] = []
    for c in contents:
        for res in c.mod_json.get("resources", []):
            target = res.get("target", "")
            internal = res.get("file", "")
            if not target or not internal:
                continue
            key = target.lower()
            if key not in res_groups:
                res_order.append(key)
            else:
                result.warnings.append(f"[WARN] 资源 {target} 被多个模组替换，后者生效")
            res_groups[key] = (target, c, internal)

    merged_resources: List[Dict[str, str]] = []
    for key in res_order:
        canonical, c, internal = res_groups[key]
        merged_resources.append({"file": internal, "target": canonical})

    # ── 白名单配置 / 依赖 / 冲突 / id_ranges / warpc_expand ──
    merged_config_files: Dict[str, Any] = {}
    merged_config_names: Dict[str, str] = {}
    merged_deps: List[str] = []
    merged_conflicts: List[str] = []
    merged_id_ranges: Dict[str, Any] = {}
    merged_warpc = 0
    for c in contents:
        mj = c.mod_json
        for cfg_internal, cfg_data in c.config_files.items():
            cfg_name = os.path.splitext(os.path.basename(cfg_internal))[0]
            merged_config_files[cfg_internal] = cfg_data
            merged_config_names[cfg_name] = cfg_internal
        for dep in mj.get("dependencies", []):
            if dep not in merged_deps:
                merged_deps.append(dep)
        for conf in mj.get("conflicts", []):
            if conf not in merged_conflicts:
                merged_conflicts.append(conf)
        for k, v in mj.get("id_ranges", {}).items():
            merged_id_ranges[k] = v
        merged_warpc = max(merged_warpc, mj.get("warpc_expand", 0) or 0)

    merged_configs = [{"file": path, "name": name}
                      for name, path in merged_config_names.items()]

    # ── 预览图 ──
    preview_filename = ""
    _preview = preview_image_path or metadata.get("preview_image_path", "")
    if _preview and os.path.isfile(_preview):
        ext = os.path.splitext(_preview)[1].lower() or ".png"
        preview_filename = f"preview{ext}"

    now = datetime.now(timezone(timedelta(hours=8)))
    mod_json = {
        "format": "TKSMOD",
        "format_version": 1,
        "id": metadata.get("id", "merged_mod"),
        "name": metadata.get("name", "合并模组"),
        "version": metadata.get("version", "1.0.0"),
        "author": metadata.get("author", ""),
        "description": metadata.get("description", ""),
        "created": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "game_version": metadata.get("game_version", "1.0"),
        "type": metadata.get("type", "mixed"),
        "mode": metadata.get("mode", "mixed"),
        "dependencies": merged_deps,
        "conflicts": merged_conflicts,
        "load_order": metadata.get("load_order", 100),
        "id_ranges": merged_id_ranges,
        "warpc_expand": merged_warpc,
        "components": merged_components,
        "resources": merged_resources,
        "configs": merged_configs,
        "_source_files": [c.filename for c in contents],
        "_merged_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if preview_filename:
        mod_json["preview_image"] = preview_filename

    log(f"  合并结果: {len(merged_components)} 组件, {len(merged_resources)} 资源, "
        f"{len(merged_config_files)} 配置")

    # ── 找出最终仍被引用的 blob, 准备复制 ──
    used_bins: set = set()
    for diff in merged_data_files.values():
        if isinstance(diff, dict):
            for entry in diff.get("appended", []) or []:
                if isinstance(entry, dict) and entry.get("bin"):
                    used_bins.add(entry["bin"])

    # ── 打包写出 ──
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mod.json", json.dumps(mod_json, ensure_ascii=False, indent=2))

            for internal_path, diff in merged_data_files.items():
                zf.writestr(internal_path, json.dumps(diff, ensure_ascii=False, indent=2))

            for cfg_path, cfg_data in merged_config_files.items():
                zf.writestr(cfg_path, json.dumps(cfg_data, ensure_ascii=False, indent=2))

            # 资源: 从各来源模组中提取字节写入
            for key in res_order:
                canonical, c, internal = res_groups[key]
                try:
                    with zipfile.ZipFile(c.path, 'r') as src_zf:
                        if internal in src_zf.namelist():
                            zf.writestr(internal, src_zf.read(internal))
                            log(f"  写入资源: {canonical} (来自 {c.filename})")
                        else:
                            result.warnings.append(f"[WARN] {c.filename} 缺少资源文件 {internal}")
                except Exception as e:
                    result.warnings.append(f"提取资源 {canonical} 失败: {e}")

            # blob: 从来源模组复制到唯一名
            for new_name in sorted(used_bins):
                src_info = blob_map.get(new_name)
                if not src_info:
                    continue
                src_path, orig = src_info
                try:
                    with zipfile.ZipFile(src_path, 'r') as src_zf:
                        if orig in src_zf.namelist():
                            zf.writestr(new_name, src_zf.read(orig))
                            log(f"  写入 blob: {new_name}")
                except Exception as e:
                    result.warnings.append(f"提取 blob {orig} 失败: {e}")

            # 预览图
            if preview_filename and _preview and os.path.isfile(_preview):
                zf.write(_preview, preview_filename)

        result.success = True
        result.output_path = output_path
        result.total_components = len(merged_components)
        result.total_resources = len(merged_resources)
        log(f"  输出: {output_path}")
        log(f"  文件大小: {os.path.getsize(output_path)} 字节")
    except Exception as e:
        result.error = f"打包失败: {e}"
        log(f"  [ERROR] {result.error}")

    return result
