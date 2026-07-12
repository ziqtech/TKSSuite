"""
MOD 打包器 — 将多个 .tksmod 文件合并为一个统一的 MOD 包
================================================================
核心功能:
  - merge_tksmod_files(): 将多个 .tksmod 合并为一个
  - validate_merge():     合并前验证兼容性
  - list_tksmod_contents(): 列出 .tksmod 内容概览

使用场景:
  MOD 开发者通过各编辑器分别导出 .tksmod 文件后，使用本模块将
  属于同一 MOD 的多个文件合并为一个独立包，方便玩家分发和管理。
"""
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TksmodContent:
    """单个 .tksmod 文件的解析内容"""
    path: str = ""
    filename: str = ""
    mod_json: Dict[str, Any] = field(default_factory=dict)
    data_files: Dict[str, Any] = field(default_factory=dict)  # {internal_path: parsed_json}
    resource_files: List[str] = field(default_factory=list)    # ZIP 内资源文件路径列表
    config_files: Dict[str, Any] = field(default_factory=dict)  # {configs/X.json: parsed_json} 白名单内
    valid: bool = False
    error: str = ""


@dataclass
class MergeResult:
    """合并结果"""
    success: bool = False
    output_path: str = ""
    total_components: int = 0
    total_resources: int = 0
    warnings: List[str] = field(default_factory=list)
    error: str = ""


def read_tksmod_content(mod_path: str) -> TksmodContent:
    """读取并解析单个 .tksmod 文件的完整内容。

    Returns:
        TksmodContent 数据结构
    """
    result = TksmodContent(path=mod_path, filename=os.path.basename(mod_path))

    if not os.path.isfile(mod_path):
        result.error = f"文件不存在: {mod_path}"
        return result

    try:
        with zipfile.ZipFile(mod_path, 'r') as zf:
            # 读取 mod.json
            if "mod.json" not in zf.namelist():
                result.error = "缺少 mod.json"
                return result

            mod_json_str = zf.read("mod.json").decode('utf-8')
            result.mod_json = json.loads(mod_json_str)

            if result.mod_json.get("format") != "TKSMOD":
                result.error = f"无效格式: {result.mod_json.get('format')}"
                return result

            # 读取所有 data/ 下的 JSON 文件
            for name in zf.namelist():
                if name.startswith("data/") and name.endswith(".json"):
                    content = zf.read(name).decode('utf-8')
                    result.data_files[name] = json.loads(content)

            # 读取 configs/ 下的 JSON 文件 (白名单内的启动器配置)
            for name in zf.namelist():
                if name.startswith("configs/") and name.endswith(".json") and not name.endswith("/"):
                    try:
                        content = zf.read(name).decode('utf-8')
                        result.config_files[name] = json.loads(content)
                    except Exception:
                        pass

            # 收集 resources/ 下的文件
            for name in zf.namelist():
                if name.startswith("resources/") and name != "resources/":
                    result.resource_files.append(name)

            result.valid = True
    except Exception as e:
        result.error = str(e)

    return result


def list_tksmod_contents(mod_path: str) -> Dict[str, Any]:
    """列出 .tksmod 文件内容概览，用于 UI 显示。

    Returns:
        {
            "filename": str,
            "mod_id": str,
            "name": str,
            "version": str,
            "author": str,
            "components": [{"file": ..., "target": ...}, ...],
            "resources": [{"file": ..., "target": ...}, ...],
            "valid": bool,
            "error": str,
        }
    """
    content = read_tksmod_content(mod_path)
    if not content.valid:
        return {
            "filename": content.filename,
            "valid": False,
            "error": content.error,
        }

    mj = content.mod_json
    return {
        "filename": content.filename,
        "mod_id": mj.get("id", ""),
        "name": mj.get("name", ""),
        "version": mj.get("version", ""),
        "author": mj.get("author", ""),
        "components": mj.get("components", []),
        "resources": mj.get("resources", []),
        "configs": mj.get("configs", []),
        "config_files": list(content.config_files.keys()),
        "valid": True,
        "error": "",
    }


def validate_merge(mod_paths: List[str]) -> Tuple[bool, List[str]]:
    """合并前验证: 检查所有文件是否兼容。

    检查项:
      - 文件是否都是有效的 .tksmod
      - 是否存在组件冲突（同一 target 被多个文件修改）
      - 资源文件是否冲突

    Returns:
        (can_merge: bool, warnings: list[str])
    """
    warnings = []
    contents = []

    for path in mod_paths:
        c = read_tksmod_content(path)
        if not c.valid:
            warnings.append(f"[ERROR] {c.filename}: {c.error}")
            return False, warnings
        contents.append(c)

    # 检查组件 target 冲突
    target_map: Dict[str, List[str]] = {}  # target -> [filenames]
    for c in contents:
        for comp in c.mod_json.get("components", []):
            target = comp.get("target", "")
            if target:
                if target not in target_map:
                    target_map[target] = []
                target_map[target].append(c.filename)

    for target, sources in target_map.items():
        if len(sources) > 1:
            warnings.append(
                f"[WARN] 组件冲突: {target} 被多个文件修改 ({', '.join(sources)})，"
                f"后者将覆盖前者"
            )

    # 检查资源 target 冲突
    res_map: Dict[str, List[str]] = {}
    for c in contents:
        for res in c.mod_json.get("resources", []):
            target = res.get("target", "")
            if target:
                if target not in res_map:
                    res_map[target] = []
                res_map[target].append(c.filename)

    for target, sources in res_map.items():
        if len(sources) > 1:
            warnings.append(
                f"[WARN] 资源冲突: {target} 被多个文件替换 ({', '.join(sources)})，"
                f"后者将覆盖前者"
            )

    return True, warnings


def merge_tksmod_files(mod_paths: List[str], output_path: str,
                       metadata: Dict[str, Any],
                       log_func=None) -> MergeResult:
    """将多个 .tksmod 文件合并为一个统一的 MOD 包。

    合并策略:
      - mod.json: 使用提供的 metadata 作为统一元数据
      - components: 合并所有文件的组件列表（重复 target 后者覆盖）
      - resources: 合并所有文件的资源列表（重复 target 后者覆盖）
      - data/*: 全部收纳，按原始内部路径保留
      - dependencies/conflicts: 合并所有文件的声明（去重）
      - id_ranges: 合并（键冲突时后者覆盖）
      - warpc_expand: 取最大值
      - load_order: 使用 metadata 中指定的值

    Args:
        mod_paths: 要合并的 .tksmod 文件路径列表
        output_path: 输出的 .tksmod 文件路径
        metadata: 统一的 MOD 元数据，至少包含 id, name, version, author, description
        log_func: 日志回调函数

    Returns:
        MergeResult
    """
    log = log_func or (lambda x: None)
    result = MergeResult()

    # 验证
    can_merge, warnings = validate_merge(mod_paths)
    result.warnings = warnings
    if not can_merge:
        result.error = "验证失败: " + "; ".join(w for w in warnings if w.startswith("[ERROR]"))
        return result

    # 读取所有内容
    contents: List[TksmodContent] = []
    for path in mod_paths:
        c = read_tksmod_content(path)
        if c.valid:
            contents.append(c)
            log(f"  读取: {c.filename} ({len(c.data_files)} 数据文件, "
                f"{len(c.resource_files)} 资源文件)")

    if not contents:
        result.error = "无有效的 .tksmod 文件"
        return result

    # 合并组件列表 (target 去重，后者覆盖前者)
    merged_components: List[Dict[str, str]] = []
    merged_comp_targets: Dict[str, Dict[str, str]] = {}  # target -> comp dict
    # 合并数据文件
    merged_data_files: Dict[str, Any] = {}
    # 合并资源声明
    merged_resources: List[Dict[str, str]] = []
    merged_res_targets: Dict[str, Dict[str, str]] = {}
    # 合并启动器配置文件 (白名单内, 后者覆盖前者)
    merged_config_files: Dict[str, Any] = {}
    merged_config_names: Dict[str, str] = {}  # config_name -> internal_path
    # 合并依赖和冲突
    merged_deps: List[str] = []
    merged_conflicts: List[str] = []
    # 合并 id_ranges
    merged_id_ranges: Dict[str, Any] = {}
    # warpc_expand 取最大
    merged_warpc_expand: int = 0

    # 用于追踪已使用的内部路径，避免冲突
    used_data_paths: Dict[str, str] = {}  # internal_path -> source filename

    for c in contents:
        mj = c.mod_json

        # 处理组件
        for comp in mj.get("components", []):
            target = comp.get("target", "")
            internal_file = comp.get("file", "")

            if not target or not internal_file:
                continue

            # 如果内部路径已被占用，重命名以避免冲突
            actual_internal = internal_file
            if internal_file in used_data_paths and used_data_paths[internal_file] != c.filename:
                # 为避免覆盖，给内部路径加前缀
                base = os.path.splitext(os.path.basename(internal_file))[0]
                # 使用源文件名作为区分
                src_base = os.path.splitext(c.filename)[0]
                actual_internal = f"data/{src_base}_{base}.json"
                log(f"  重命名内部路径: {internal_file} → {actual_internal} (来自 {c.filename})")

            # 记录组件
            new_comp = {"file": actual_internal, "target": target}
            merged_comp_targets[target] = new_comp
            used_data_paths[actual_internal] = c.filename

            # 复制数据文件内容
            if internal_file in c.data_files:
                merged_data_files[actual_internal] = c.data_files[internal_file]

        # 处理资源声明
        for res in mj.get("resources", []):
            target = res.get("target", "")
            if target:
                merged_res_targets[target] = res

        # 合并启动器配置文件 (白名单内, 后者覆盖前者)
        for cfg_internal, cfg_data in c.config_files.items():
            cfg_name = os.path.splitext(os.path.basename(cfg_internal))[0]
            merged_config_files[cfg_internal] = cfg_data
            merged_config_names[cfg_name] = cfg_internal

        # 合并依赖
        for dep in mj.get("dependencies", []):
            if dep not in merged_deps:
                merged_deps.append(dep)

        # 合并冲突
        for conf in mj.get("conflicts", []):
            if conf not in merged_conflicts:
                merged_conflicts.append(conf)

        # 合并 id_ranges
        for key, val in mj.get("id_ranges", {}).items():
            merged_id_ranges[key] = val

        # warpc_expand 取最大
        wp = mj.get("warpc_expand", 0)
        if wp > merged_warpc_expand:
            merged_warpc_expand = wp

    # 构建最终 components 列表
    merged_components = list(merged_comp_targets.values())
    merged_resources = list(merged_res_targets.values())
    # 构建 configs 元数据列表
    merged_configs = [{"file": path, "name": name}
                      for name, path in merged_config_names.items()]

    # 构建 mod.json
    now = datetime.now(timezone(timedelta(hours=8)))
    mod_json = {
        "format": "TKSMOD",
        "format_version": 1,
        "id": metadata.get("id", "merged_mod"),
        "name": metadata.get("name", "Merged MOD"),
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
        "warpc_expand": merged_warpc_expand,
        "components": merged_components,
        "resources": merged_resources,
        "configs": merged_configs,
        # 记录源文件信息 (仅供参考)
        "_source_files": [c.filename for c in contents],
        "_packed_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    log(f"  合并结果: {len(merged_components)} 组件, {len(merged_resources)} 资源, "
        f"{len(merged_config_files)} 配置")

    # 打包为 ZIP
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 写入 mod.json
            mod_json_str = json.dumps(mod_json, ensure_ascii=False, indent=2)
            zf.writestr("mod.json", mod_json_str)

            # 写入所有数据文件
            for internal_path, data_content in merged_data_files.items():
                json_str = json.dumps(data_content, ensure_ascii=False, indent=2)
                zf.writestr(internal_path, json_str)

            # 写入启动器配置文件 (白名单内)
            for cfg_path, cfg_content in merged_config_files.items():
                json_str = json.dumps(cfg_content, ensure_ascii=False, indent=2)
                zf.writestr(cfg_path, json_str)

            # 从源 .tksmod 中提取并写入资源文件
            for c in contents:
                with zipfile.ZipFile(c.path, 'r') as src_zf:
                    for res_path in c.resource_files:
                        # 检查是否在合并后的资源声明中
                        try:
                            res_data = src_zf.read(res_path)
                            zf.writestr(res_path, res_data)
                            log(f"  写入资源: {res_path} (来自 {c.filename})")
                        except Exception as e:
                            result.warnings.append(f"提取资源 {res_path} 失败: {e}")

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


def suggest_output_name(mod_paths: List[str], metadata: Dict[str, Any]) -> str:
    """根据元数据建议输出文件名。"""
    mod_id = metadata.get("id", "")
    if mod_id:
        return f"{mod_id}.tksmodpak"
    # 尝试从第一个文件推导
    if mod_paths:
        base = os.path.splitext(os.path.basename(mod_paths[0]))[0]
        return f"{base}_pack.tksmodpak"
    return "mod_pack.tksmodpak"


def rewrite_mod_metadata(mod_path: str, new_metadata: Dict[str, Any],
                         output_path: Optional[str] = None,
                         log_func=None) -> Tuple[bool, str]:
    """重写 .tksmod 的元数据，保留所有数据/资源内容不变。

    在原始 mod.json 的基础上仅更新 new_metadata 中给出的字段，其余字段
    （含 components、resources、id_ranges、warpc_expand、created 等）原样保留；
    data/* 与 resources/* 文件以字节级复制，确保 MOD 内容不被改动。

    Args:
        mod_path: 源 .tksmod 文件路径
        new_metadata: 要更新的元数据字段字典
        output_path: 输出路径；None 表示覆盖原文件
        log_func: 日志回调

    Returns:
        (success, message)
    """
    log = log_func or (lambda x: None)

    if not os.path.isfile(mod_path):
        return False, f"文件不存在: {mod_path}"

    content = read_tksmod_content(mod_path)
    if not content.valid:
        return False, f"无法读取: {content.error}"

    # 在原始 mod.json 基础上更新元数据，保留所有未提及字段
    mod_json = dict(content.mod_json)
    mod_json.update(new_metadata)
    # 强制保留格式标识（防止被 new_metadata 误覆盖）
    mod_json["format"] = content.mod_json.get("format", "TKSMOD")
    mod_json["format_version"] = content.mod_json.get("format_version", 1)

    if output_path is None:
        output_path = mod_path

    # 写入临时文件再替换，避免覆盖源文件时出错
    tmp_path = output_path + ".tmp"
    try:
        with zipfile.ZipFile(mod_path, 'r') as src_zf, \
                zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as dst_zf:
            # 先写新的 mod.json
            dst_zf.writestr("mod.json",
                            json.dumps(mod_json, ensure_ascii=False, indent=2))
            # 原样复制其余所有条目（数据 + 资源，字节级保留）
            for item in src_zf.infolist():
                if item.filename == "mod.json":
                    continue
                dst_zf.writestr(item, src_zf.read(item.filename))
        os.replace(tmp_path, output_path)
        log(f"  已保存元数据: {output_path}")
        return True, "保存成功"
    except Exception as e:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False, f"保存失败: {e}"


def create_tksmodpak(mod_paths: List[str], output_path: str,
                      metadata: Dict[str, Any] | None = None,
                      preview_image_path: str | None = None,
                      log_func=None) -> Tuple[bool, str]:
    """将多个 .tksmod 文件打包为一个 .tksmodpak 文件。

    不做任何数据合并，仅收纳原始 .tksmod 文件 + 合集元数据 mod.json。
    后续可通过 extract_tksmodpak() 原样拆分还原。

    .tksmodpak 结构:
        mod.json         — 合集元数据（名称、作者、描述等）
        preview.png      — 预览图（可选）
        xxx.tksmod       — 原始模组文件（逐字节保留）

    Args:
        mod_paths: 要打包的 .tksmod 文件路径列表
        output_path: 输出的 .tksmodpak 文件路径
        metadata: 合集元数据 dict，包含 id, name, version, author, description 等
        preview_image_path: 预览图本地路径（可选）
        log_func: 日志回调函数

    Returns:
        (success: bool, message: str)
    """
    log = log_func or (lambda x: None)

    if not mod_paths:
        return False, "未提供要打包的模组文件"

    now = datetime.now(timezone(timedelta(hours=8)))

    # 处理预览图
    preview_filename = ""
    _preview = preview_image_path or (metadata or {}).get("preview_image_path", "")
    if _preview and os.path.isfile(_preview):
        ext = os.path.splitext(_preview)[1].lower() or ".png"
        preview_filename = f"preview{ext}"

    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 写入合集元数据
            meta = {
                "format": "TKSMODPAK",
                "format_version": 1,
                "id": (metadata or {}).get("id", ""),
                "name": (metadata or {}).get("name", "模组合集"),
                "version": (metadata or {}).get("version", "1.0.0"),
                "author": (metadata or {}).get("author", ""),
                "description": (metadata or {}).get("description", ""),
                "type": (metadata or {}).get("type", "mixed"),
                "load_order": (metadata or {}).get("load_order", 100),
                "created": now.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_files": [os.path.basename(p) for p in mod_paths],
            }
            if preview_filename:
                meta["preview_image"] = preview_filename
            zf.writestr("mod.json",
                        json.dumps(meta, ensure_ascii=False, indent=2))
            log(f"  写入合集元数据: {meta['name']}")

            # 写入预览图
            if preview_filename and _preview and os.path.isfile(_preview):
                zf.write(_preview, preview_filename)
                log(f"  写入预览图: {preview_filename}")

            # 逐字节复制原始 .tksmod 文件
            for fp in mod_paths:
                filename = os.path.basename(fp)
                with open(fp, 'rb') as src:
                    zf.writestr(filename, src.read())
                log(f"  打包: {filename}")

        size_kb = os.path.getsize(output_path) / 1024
        log(f"  输出: {os.path.basename(output_path)} ({size_kb:.1f} KB)")
        return True, f"已打包 {len(mod_paths)} 个模组文件"
    except Exception as e:
        return False, f"打包失败: {e}"


def extract_tksmodpak(pack_path: str, output_dir: str,
                       log_func=None) -> dict:
    """从 .tksmodpak 文件中提取所有 .tksmod 文件。

    Args:
        pack_path: .tksmodpak 文件路径
        output_dir: 提取输出目录
        log_func: 日志回调函数

    Returns:
        {
            "success": bool,
            "extracted": list[str],   # 已提取的文件路径列表
            "error": str,
        }
    """
    log = log_func or (lambda x: None)
    result = {"success": False, "extracted": [], "error": ""}

    if not os.path.isfile(pack_path):
        result["error"] = f"文件不存在: {pack_path}"
        return result

    try:
        with zipfile.ZipFile(pack_path, 'r') as zf:
            mod_entries = sorted(
                n for n in zf.namelist()
                if n.lower().endswith(".tksmod") and not n.endswith("/")
            )
            if not mod_entries:
                result["error"] = "该合集包中未找到 .tksmod 文件"
                return result

            os.makedirs(output_dir, exist_ok=True)
            for entry in mod_entries:
                filename = os.path.basename(entry)
                output_path = os.path.join(output_dir, filename)

                # 处理重名冲突
                if os.path.exists(output_path):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(output_path):
                        output_path = os.path.join(output_dir, f"{base}_{counter}{ext}")
                        counter += 1
                    log(f"  重命名: {filename} → {os.path.basename(output_path)}")

                with zf.open(entry) as src:
                    with open(output_path, 'wb') as dst:
                        dst.write(src.read())
                result["extracted"].append(output_path)
                log(f"  提取: {os.path.basename(output_path)}")

            result["success"] = True
    except Exception as e:
        result["error"] = str(e)

    return result
