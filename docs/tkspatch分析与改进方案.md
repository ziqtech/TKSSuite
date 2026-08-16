# TKS 启动器 tkspatch 模块分析与改进方案

**日期**: 2026-08-17  
**版本**: 1.0  
**作者**: AI Assistant

---

## 目录

1. [现状评估](#一现状评估)
2. [对比 .tksmodpak 模式](#二对比-tksmodpak-模式)
3. [改进方案：.tkspatchpak](#三改进方案tkspatchpak)
4. [风险评估](#四风险评估)
5. [推荐实施步骤](#五推荐实施步骤)
6. [总结](#六总结)

---

## 一、现状评估

### 1.1 当前架构

**文件组织**：
- **位置**: `tks_launcher_gui/patches/` 目录
- **数量**: 57 个独立的 `.tkspatch` 文件
- **格式**: 支持双格式
  - **旧版**: 散装 JSON 文件（向后兼容）
  - **新版**: ZIP 容器（包含 `patch.json` + 可选 `script.py`）

**核心模块**：
```
core/tkspatch_loader.py      # 加载器（250+ 行，完整的 ZIP/JSON 解析）
core/patch_engine.py          # 应用引擎（2600+ 行，15+ 种补丁类型）
core/config_loader.py         # 配置解析器（PatchDef 数据类）
ui/patch_list.py              # UI 补丁列表展示
```

**加载流程**（从 `tkspatch_loader.py` 分析）：
```python
load_config_merged()
  ├─ load_config(tks_patches.json)      # 旧版兼容（可选）
  ├─ load_variables_from_dir()          # 读取 _variables.tkspatch（唯一全局变量来源）
  └─ load_tkspatch_dir(patches/)        # 扫描所有 .tkspatch 并合并
       ├─ load_tkspatch_file()          # 单文件加载
       │    ├─ ZIP 格式：_load_tkspatch_zip()
       │    └─ JSON 格式：_load_tkspatch_json()
       └─ merge_patches()                # 同 id 覆盖规则
```

### 1.2 优点

✅ **格式统一**：
- ZIP 容器与 `.tksmod` 格式一致，便于理解
- 支持内嵌脚本（`script.py`），无需外部文件依赖

✅ **加载机制成熟**：
- 完整的 JSON Schema 校验（`validate_tkspatch_dict`）
- 错误处理完善（损坏文件不影响其他补丁加载）
- 覆盖规则清晰（外置补丁 > tks_patches.json）

✅ **可扩展性强**：
- 注册表模式（`@register_patch_type` 装饰器）
- 15+ 种补丁类型，易于新增
- 统一的 `PatchContext` 上下文

### 1.3 问题点

❌ **开发调试不便**：
- 57 个散装文件，难以批量管理
- 修改补丁需逐个编辑 JSON 文件
- 没有批量校验工具（需逐个加载才能发现格式错误）

❌ **分发困难**：
- 核心补丁分散在多个文件中，无法一键分发
- 用户需复制整个 `patches/` 目录（容易遗漏）
- 版本管理混乱（无法追踪哪些补丁属于同一版本）

❌ **缺少打包机制**：
- 虽然有 ZIP 格式支持，但仍是单文件单补丁
- 没有像 `.tksmodpak` 那样的合集打包功能
- 核心补丁（如 cave_hook 系列）无法作为整体分发

---

## 二、对比 .tksmodpak 模式

### 2.1 .tksmodpak 已有功能（从 `mod_packer.py` 分析）

✅ **成熟的合集打包**：
```python
create_tksmodpak(mod_paths, output_path, metadata)
  # 打包多个 .tksmod → 单个 .tksmodpak
  # 结构：mod.json + preview.png + *.tksmod（原样保留）
  
expand_pak_mods(pak_path)
  # 展开 .tksmodpak → 内存中的 ModInfo 列表（不落盘）
  
extract_tksmodpak(pack_path, output_dir)
  # 提取 .tksmodpak → 独立的 .tksmod 文件
```

✅ **清晰的元数据管理**：
```json
{
  "format": "TKSMODPAK",
  "id": "core_patches",
  "name": "核心补丁合集",
  "version": "1.0.0",
  "source_files": ["patch1.tksmod", "patch2.tksmod"]
}
```

✅ **UI 支持完善**：
- 合集展开：`expand_pak_mods()` 在内存解析
- 冲突检测：`detect_conflicts()` 检查槽位/资源重叠
- 优先级管理：`load_order` 控制应用顺序

### 2.2 tkspatch 缺失对比

| 功能 | .tksmodpak | .tkspatch | 差距 |
|------|-----------|-----------|------|
| 批量打包 | ✅ | ❌ | 无法将多个补丁打包为一个文件 |
| 合集展开 | ✅ 内存解析 | ⚠️ 只能逐个加载 | 无合集概念 |
| 元数据管理 | ✅ 统一 mod.json | ⚠️ 分散在各文件 | 版本追踪困难 |
| 预览图支持 | ✅ | ❌ | 无可视化标识 |
| 提取工具 | ✅ | N/A | 无需提取（本就散装） |

---

## 三、改进方案：.tkspatchpak

### 3.1 设计思路

**参考 .tksmodpak 模式**，但保持与补丁特性的契合：

```
核心补丁合集.tkspatchpak (ZIP 容器)
├── pack.json                    # 合集元数据
├── preview.png                  # 可选预览图
├── _variables.tkspatch          # 全局变量（合集级，优先于散装）
├── broke_weapon_fix.tkspatch    # 原样保留的补丁文件
├── gold_limit.tkspatch
├── summon_extend_v15.tkspatch
└── ... (更多补丁)
```

**pack.json 结构**：
```json
{
  "format": "TKSPATCHPAK",
  "format_version": 1,
  "id": "core_fixes",
  "name": "核心修复补丁合集",
  "version": "1.5.0",
  "author": "TKS Team",
  "description": "包含基础 BUG 修复、数值平衡等核心补丁",
  "created": "2024-08-17T02:00:00",
  "patches": [
    {"file": "broke_weapon_fix.tkspatch", "required": true},
    {"file": "gold_limit.tkspatch", "required": false}
  ],
  "dependencies": [],
  "conflicts": []
}
```

### 3.2 关键原则（遵循原版逻辑）

🔒 **严格遵循现有加载逻辑**（从 `tkspatch_loader.py:496-529` 分析）：

```python
# 现有逻辑（不可改变）：
load_config_merged(config_path, patches_dir, log_func):
    1. 加载 tks_patches.json（向后兼容，可选）
    2. 加载 patches/_variables.tkspatch（全局变量唯一来源）
    3. 扫描 patches/*.tkspatch，同 id 覆盖
    
# .tkspatchpak 需插入到步骤 3，不破坏 1、2
```

🔒 **禁止引入新的数据格式**：
- ✅ 复用 `load_tkspatch_file()` 加载单个补丁
- ✅ 复用 `merge_patches()` 合并逻辑
- ❌ 禁止修改 `PatchDef` 数据结构
- ❌ 禁止改变补丁应用顺序规则

### 3.3 实现方案

**新增模块**：`core/tkspatch_packer.py`（参考 `mod_packer.py:490-626`）

```python
def create_tkspatchpak(
    patch_paths: List[str],      # 要打包的 .tkspatch 文件路径
    output_path: str,             # 输出的 .tkspatchpak 路径
    metadata: Dict[str, Any],     # 合集元数据
    variables_path: str = None,   # 可选：合集级 _variables.tkspatch
    preview_image_path: str = None,
    log_func=None
) -> Tuple[bool, str]:
    """打包多个 .tkspatch 为 .tkspatchpak（完全参考 create_tksmodpak 逻辑）。
    
    不做任何数据合并，仅收纳原始 .tkspatch 文件 + 合集元数据。
    后续可通过 extract_tkspatchpak() 原样拆分还原。
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. 写入合集元数据
        pack_json = {
            "format": "TKSPATCHPAK",
            "format_version": 1,
            **metadata,
            "source_files": [os.path.basename(p) for p in patch_paths],
        }
        zf.writestr("pack.json", json.dumps(pack_json, ensure_ascii=False, indent=2))
        
        # 2. 可选：合集级 _variables.tkspatch
        if variables_path and os.path.isfile(variables_path):
            with open(variables_path, 'rb') as f:
                zf.writestr("_variables.tkspatch", f.read())
        
        # 3. 可选：预览图
        if preview_image_path and os.path.isfile(preview_image_path):
            ext = os.path.splitext(preview_image_path)[1] or ".png"
            zf.write(preview_image_path, f"preview{ext}")
        
        # 4. 逐字节复制原始 .tkspatch 文件
        for fp in patch_paths:
            with open(fp, 'rb') as src:
                zf.writestr(os.path.basename(fp), src.read())
    
    return True, f"已打包 {len(patch_paths)} 个补丁"


def expand_tkspatchpak(pak_path: str, log_func=None) -> List[PatchDef]:
    """展开 .tkspatchpak，在内存中解析为 PatchDef 列表（不落盘）。
    
    返回的 PatchDef 对象可直接传给 apply_config_patches()。
    参考 expand_pak_mods() 的内存解析逻辑。
    """
    import io
    result = []
    with zipfile.ZipFile(pak_path, 'r') as zf:
        patch_entries = [n for n in zf.namelist() 
                        if n.endswith('.tkspatch') and n != '_variables.tkspatch']
        for entry in patch_entries:
            raw_data = zf.read(entry)
            # 复用现有的 load_tkspatch_file() 逻辑
            if zipfile.is_zipfile(io.BytesIO(raw_data)):
                defn = _load_tkspatch_zip_from_bytes(raw_data, entry, log_func)
            else:
                defn = _load_tkspatch_json_from_bytes(raw_data, entry, log_func)
            if defn:
                result.append(defn)
    return result


def extract_tkspatchpak(pak_path: str, output_dir: str, log_func=None) -> dict:
    """提取 .tkspatchpak 中的所有 .tkspatch 文件到指定目录。
    
    完全参考 extract_tksmodpak() 的逻辑。
    """
    # （实现略，与 mod_packer.py:569-626 完全一致）
```

**修改 `tkspatch_loader.py`**（最小化改动）：

```python
def load_config_merged(config_path: str, patches_dir: str, log_func=None) -> Optional[PatchConfig]:
    """统一补丁配置加载入口。
    
    加载顺序（不变）：
      1. tks_patches.json（向后兼容）
      2. patches/_variables.tkspatch（全局变量唯一来源）
      3. patches/*.tkspatch → 合并
      4. 【新增】patches/*.tkspatchpak → 展开后合并
    """
    # ... 现有逻辑 1-3 不变 ...
    
    # 4. 扫描并展开 .tkspatchpak 合集
    pak_patches = []
    if os.path.isdir(patches_dir):
        for fname in sorted(os.listdir(patches_dir)):
            if fname.endswith('.tkspatchpak'):
                fpath = os.path.join(patches_dir, fname)
                try:
                    expanded = expand_tkspatchpak(fpath, log_func=log)
                    pak_patches.extend(expanded)
                    log(f"  [tkspatchpak] 从 {fname} 展开 {len(expanded)} 个补丁")
                except Exception as e:
                    log(f"  [WARN] 展开 {fname} 失败: {e}")
    
    if pak_patches:
        config = merge_patches(config, pak_patches, log_func=log)
    
    return config
```

### 3.4 优势分析

✅ **开发便利**：
- 核心补丁打包为 `core_fixes.tkspatchpak`，一键分发
- 实验性补丁保持散装（`patches/*.tkspatch`），便于迭代
- 测试时可提取合集（`extract_tkspatchpak`），逐个调试

✅ **分发便捷**：
- 玩家只需下载 `.tkspatchpak` 文件到 `patches/` 目录
- 版本管理清晰（`"version": "1.5.0"` 在 `pack.json`）
- 预览图支持（便于区分不同合集）

✅ **向后兼容**：
- 现有 57 个散装 `.tkspatch` 继续工作
- `tks_patches.json` 继续兼容
- 加载顺序不变（`_variables.tkspatch` 仍是全局变量唯一来源）

✅ **逻辑一致**：
- 完全复用 `load_tkspatch_file()` 加载单个补丁
- 完全复用 `merge_patches()` 合并逻辑
- 不修改 `PatchDef`、`PatchConfig` 数据结构
- 不引入新的补丁格式（仍是 ZIP 容器 + JSON）

---

## 四、风险评估

### 4.1 潜在风险

⚠️ **加载顺序冲突**：
- 如果同时存在散装 `gold_limit.tkspatch` 和合集中的 `gold_limit.tkspatch`
- 解决：按文件名排序，`.tkspatch` 优先于 `.tkspatchpak`（后者覆盖）

⚠️ **_variables.tkspatch 优先级**：
- 合集内的 `_variables.tkspatch` 与散装的冲突
- 解决：散装优先（保持现有逻辑：`load_variables_from_dir` 只读 `patches/_variables.tkspatch`）

⚠️ **性能影响**：
- 额外的 ZIP 解析开销
- 缓解：仅在启动时加载一次，可忽略（< 100ms）

### 4.2 测试策略

```python
# 测试用例（参考 mod_packer.py 的测试逻辑）
def test_tkspatchpak_loading():
    # 1. 打包测试
    patch_files = ["broke_weapon_fix.tkspatch", "gold_limit.tkspatch"]
    create_tkspatchpak(patch_files, "test_pack.tkspatchpak", 
                       metadata={"id": "test", "name": "测试合集"})
    
    # 2. 展开测试
    patches = expand_tkspatchpak("test_pack.tkspatchpak")
    assert len(patches) == 2
    assert all(isinstance(p, PatchDef) for p in patches)
    
    # 3. 合并测试（与散装补丁）
    config = load_config_merged("tks_patches.json", "patches/")
    # 验证同 id 覆盖规则
    
    # 4. 提取测试
    extract_tkspatchpak("test_pack.tkspatchpak", "output/")
    # 验证字节级一致性
```

---

## 五、推荐实施步骤

**Phase 1: 核心功能实现**（2-3 天）
1. 创建 `core/tkspatch_packer.py`
2. 实现 `create_tkspatchpak()` / `expand_tkspatchpak()` / `extract_tkspatchpak()`
3. 单元测试（参考 `mod_packer.py` 的测试用例）

**Phase 2: 集成到加载流程**（1 天）
1. 修改 `tkspatch_loader.py:load_config_merged()`
2. 添加 `.tkspatchpak` 扫描和展开逻辑
3. 集成测试（与现有 57 个散装补丁共存）

**Phase 3: UI 工具支持**（1-2 天）
1. 参考 `ui/mod_packer_dialog.py`，创建 `ui/patch_packer_dialog.py`
2. 补丁列表批量选择 → 打包按钮
3. 合集预览（显示内含补丁列表）

**Phase 4: 文档和分发**（1 天）
1. 将核心补丁打包为 `core_fixes_v1.5.tkspatchpak`
2. 编写使用文档（玩家端 / 开发者端）
3. 更新 `verify_patches_result.txt`（如有）

---

## 六、总结

### 当前 tkspatch 架构评估

- ✅ **加载机制成熟**：ZIP/JSON 双格式，Schema 校验，错误处理完善
- ✅ **可扩展性强**：注册表模式，15+ 种补丁类型
- ❌ **开发调试不便**：57 个散装文件，难以批量管理
- ❌ **分发困难**：无批量打包机制，版本管理混乱

### .tkspatchpak 改进方案

- 完全参考成熟的 `.tksmodpak` 模式
- 严格遵循原版加载逻辑（不破坏现有架构）
- 向后兼容（散装 `.tkspatch` 继续工作）
- 实现成本低（复用 90% 现有代码）

### 建议

1. **立即实施** `.tkspatchpak` 打包功能（开发便利性显著提升）
2. **保持散装模式**作为调试手段（实验性补丁仍用 `.tkspatch`）
3. **核心补丁**打包为合集分发（玩家体验改善）

---

**附录**：

- **参考文件**：
  - `core/tkspatch_loader.py` - 补丁加载逻辑
  - `core/mod_packer.py` - 合集打包参考实现
  - `core/patch_engine.py` - 补丁应用引擎
  
- **相关数据结构**：
  - `PatchDef` - 单个补丁定义
  - `PatchConfig` - 补丁配置容器
  - `PatchContext` - 补丁运行上下文
