# TKS 统一MOD系统可行性分析

> 分析日期：2026-05-31
> 分析范围： 下所有编辑器 + tks_launcher.cs + 逆向工程数据

---

## 一、当前架构全景

### 1.1 编辑器生态系统（17个编辑器）

| 编辑器 | 目标文件 | 文件格式 | 记录大小 | 记录数 | 保存方式 |
|--------|----------|----------|----------|--------|----------|
| **mat_editor** | TKMat.Dat + TKDefUnit.Dat + TKD.dat | 定长+文本 | 384B+16B+变长 | 6000+5000+~59319行 | 直接覆盖3个文件 |
| **warpc_editor** | WarPC.dat | LZSS压缩定长 | 1054B | 143条(可扩展) | 直接覆盖 |
| **skill_editor** | TKSkill.dat | LZSS压缩定长 | 94B | 350条 | 直接覆盖 |
| **item_editor** | TKItem.dat | LZSS压缩定长 | 64B | 600条 | 直接覆盖 |
| **script_editor** | TKD.dat | XOR 0xFF加密文本 | 变长 | ~1539个DEFINE块 | 直接覆盖 |
| **defunit_editor** | TKDefUnit.Dat | 定长 | 16B | 5000条 | 直接覆盖 |
| **tkt_editor** | TKT.dat | XOR 0xFF加密 | 变长 | 14438条 | 直接覆盖 |
| **shop_editor** | TKShop.dat | LZSS压缩 | 16B | 120条 | 直接覆盖 |
| **kon_editor** | TKKon.dat | LZSS压缩 | 104B | 250条 | 直接覆盖 |
| **wardata_editor** | WarData*.dat | 定长 | 变长 | 多文件 | 直接覆盖 |
| **act_editor** | ACT数据 | 二进制 | - | - | 直接覆盖 |
| **grp_editor** | SC.GRP/IDX | 二进制索引 | - | - | 直接覆盖 |
| **gxp_editor** | GXP文件 | 二进制 | - | - | 直接覆盖 |
| **jvg_editor** | JVG文件 | 二进制精灵 | - | - | 直接覆盖 |
| **spritesheet_editor** | 精灵表 | 二进制 | - | - | 直接覆盖 |
| **save_editor** | save\*.sav | 二进制存档 | - | - | 直接覆盖 |

### 1.2 数据文件分类

```
┌─────────────────────────────────────────────────────────────────┐
│                     TKS 数据文件分类                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【A类】定长记录文件（最适合增量补丁）                            │
│  ├── TKMat.Dat      6000×384B = 2,304,000B                     │
│  ├── TKDefUnit.Dat  5000×16B  = 80,000B                        │
│  ├── TKSkill.dat    350×94B   = 32,900B (LZSS)                 │
│  ├── TKItem.dat     600×64B   = 38,400B (LZSS)                 │
│  ├── TKShop.dat     120×16B   = 1,920B  (LZSS)                 │
│  ├── TKKon.dat      250×104B  = 26,000B (LZSS)                 │
│  └── WarPC.dat      143×1054B = 150,722B (LZSS)                │
│                                                                 │
│  【B类】文本文件（适合内容补丁）                                 │
│  ├── TKD.dat        XOR 0xFF加密, Big5编码                     │
│  └── TKT.dat        XOR 0xFF加密, 14438条文本                  │
│                                                                 │
│  【C类】二进制资源文件（适合完整替换）                           │
│  ├── SC.GRP/IDX     场景背景                                    │
│  ├── *.JVG          精灵/头像数据                               │
│  ├── *.GXP          图形资源                                    │
│  └── WarData*.dat   战场数据                                    │
│                                                                 │
│  【D类】存档文件（用户数据，不纳入MOD）                          │
│  └── save\*.sav     游戏存档                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 现有MOD格式分析

#### .tksmod 格式（mat_editor 提出）

```json
{
  "magic": "TKSMOD",
  "version": 1,
  "created": "2026-05-29T12:00:00",
  "comment": "My Mod v1.0",
  "checksums": {
    "TKMat.dat": "crc32_of_original",
    "TKDefUnit.dat": "crc32_of_original",
    "TKD.dat": "crc32_of_original"
  },
  "patches": {
    "TKMat.dat": [
      {"index": 142, "fields": {"d0": 200, "d10": 512, "d11": 384}}
    ],
    "TKDefUnit.dat": [
      {"index": 42, "fields": {"f0": 256, "f1": 5}}
    ],
    "TKD.dat": {
      "added": ["DEFINE 100663296\n{\n...\n}; end\n"],
      "modified": {"100663297": "DEFINE 100663297\n{\n...\n}; end\n"}
    }
  }
}
```

**特点**：
- 针对 mat_editor 的3个文件
- 字段级差异记录
- JSON格式，可读可调试
- 有CRC32校验

#### .tkspatch 格式（tks_launcher 提出）

```json
{
  "format": "TKSPATCH",
  "version": 1,
  "patch": {
    "id": "patch_team_limit",
    "name": "入队数量限制扩展",
    "requires": [],
    "conflicts": [],
    "actions": [
      {
        "type": "static_patch",
        "rva": "0xDA15",
        "data": "C887",
        "desc": "TeamMember: cmp 0x1E->0xC8, jg->ja"
      }
    ]
  }
}
```

**特点**：
- 针对游戏代码补丁（内存补丁）
- 支持多种action类型
- 有依赖/冲突声明
- 模块化设计

---

## 二、统一MOD系统可行性分析

### 2.1 核心问题

**问题**：不同MOD开发者使用不同编辑器编辑后，如何生成统一的MOD文件？

**答案**：✅ **高度可行**，但需要分层设计。

### 2.2 技术可行性评估

| 数据类型 | 增量补丁可行性 | 原因 |
|----------|---------------|------|
| **A类定长记录** | ⭐⭐⭐⭐⭐ 极高 | 按记录号+字段号比对，差异极小 |
| **B类文本文件** | ⭐⭐⭐⭐☆ 高 | DEFINE块独立，可按ID比对 |
| **C类二进制资源** | ⭐⭐⭐☆☆ 中等 | 只能完整替换，无法增量 |
| **D类存档** | ⭐☆☆☆☆ 低 | 用户数据，不纳入MOD |

### 2.3 统一MOD格式设计

#### 方案一：复合MOD包（推荐）

```
mymod.tksmod (ZIP压缩包)
├── mod.json              # MOD元数据 + 依赖声明
├── patches/
│   ├── TKMat.dat.json    # TKMat增量补丁
│   ├── TKDefUnit.dat.json # TKDefUnit增量补丁
│   ├── TKD.dat.json      # TKD脚本补丁
│   ├── TKSkill.dat.json  # TKSkill增量补丁
│   ├── TKItem.dat.json   # TKItem增量补丁
│   ├── WarPC.dat.json    # WarPC增量补丁
│   └── ...
├── resources/
│   ├── SC001.GRP         # 完整替换的资源文件
│   ├── character.JVG     # 完整替换的精灵文件
│   └── ...
└── patches/
    ├── warpc_expand.json # WarPC扩展配置
    └── code_patches.json # 代码补丁（.tkspatch格式）
```

**mod.json 格式**：

```json
{
  "format": "TKSMOD_UNIFIED",
  "version": 1,
  "id": "mymod_v1.0",
  "name": "我的MOD",
  "author": "作者名",
  "description": "MOD描述",
  "created": "2026-05-31T12:00:00",
  "game_version": "1.0",
  
  "dependencies": [],
  "conflicts": [],
  "load_order": 100,
  
  "components": {
    "TKMat.dat": {
      "type": "field_diff",
      "file": "patches/TKMat.dat.json"
    },
    "TKDefUnit.dat": {
      "type": "field_diff",
      "file": "patches/TKDefUnit.dat.json"
    },
    "TKD.dat": {
      "type": "text_merge",
      "file": "patches/TKD.dat.json"
    },
    "TKSkill.dat": {
      "type": "field_diff",
      "file": "patches/TKSkill.dat.json"
    },
    "WarPC.dat": {
      "type": "field_diff",
      "file": "patches/WarPC.dat.json"
    },
    "SC001.GRP": {
      "type": "full_replace",
      "file": "resources/SC001.GRP"
    }
  },
  
  "warpc_config": {
    "expand_to": 200,
    "skill_learn_extend": 30
  },
  
  "code_patches": [
    "patches/warpc_expand.json",
    "patches/code_patches.json"
  ]
}
```

#### 方案二：单一JSON文件（简单MOD）

对于只修改少量数据的简单MOD，可以使用单一JSON文件：

```json
{
  "format": "TKSMOD_SIMPLE",
  "version": 1,
  "name": "简单MOD",
  "patches": {
    "TKMat.dat": [...],
    "TKDefUnit.dat": [...],
    "TKD.dat": {...},
    "TKSkill.dat": [...]
  }
}
```

### 2.4 各编辑器改造方案

#### mat_editor 改造

**当前**：`_save()` → 直接写3个文件

**改造**：增加 `_export_tksmod()` 功能

```python
def _export_tksmod(self):
    """导出为.tksmod增量补丁"""
    # 1. 加载原始文件（校验CRC32）
    original_mat = load_mat(self.dat_path + ".orig")
    original_defunit = load_defunit(self.defunit_path + ".orig")
    original_tkd = load_tkd(self.tkd_path + ".orig")
    
    # 2. 逐记录比对
    mat_diff = diff_records(original_mat, self.records, "TKMat")
    defunit_diff = diff_records(original_defunit, self.defunit_recs, "TKDefUnit")
    tkd_diff = diff_text(original_tkd, self.tkd_defines)
    
    # 3. 生成.tksmod文件
    mod = {
        "format": "TKSMOD_UNIFIED",
        "version": 1,
        "patches": {
            "TKMat.dat": mat_diff,
            "TKDefUnit.dat": defunit_diff,
            "TKD.dat": tkd_diff
        }
    }
    
    # 4. 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mod, f, ensure_ascii=False, indent=2)
```

**关键实现细节**：
- 在 `_reload()` 中保存原始文件快照
- 比对当前状态与原始快照
- 只输出变化的记录/字段
- 对TKMat：比对96个dword，只输出不同的字段
- 对TKDefUnit：比对8个uint16字段
- 对TKD：文本级diff（完整替换修改过的DEFINE块）

#### warpc_editor 改造

**当前**：直接覆盖WarPC.dat

**改造**：增加导出.tksmod功能

```python
def _export_tksmod(self):
    """导出WarPC修改为.tksmod"""
    # 1. 加载原始WarPC.dat
    original = load_warpc("WarPC.dat.orig")
    
    # 2. 逐记录比对
    diff = []
    for i in range(min(len(original), len(self.records))):
        rec_diff = diff_warpc_record(original[i], self.records[i])
        if rec_diff:
            diff.append({"index": i, "fields": rec_diff})
    
    # 3. 生成补丁
    return {"WarPC.dat": diff}
```

#### skill_editor / item_editor 改造

类似warpc_editor，增加增量导出功能。

#### script_editor 改造

**当前**：直接覆盖TKD.dat

**改造**：增加DEFINE块级diff

```python
def _export_tksmod(self):
    """导出TKD修改为.tksmod"""
    # 1. 加载原始TKD.dat
    original_text = load_tkd("TKD.dat.orig")
    original_defines = parse_defines(original_text)
    
    # 2. 比对DEFINE块
    added = []
    modified = {}
    deleted = []
    
    for did, content in self.defines.items():
        if did not in original_defines:
            added.append(content)
        elif content != original_defines[did]:
            modified[did] = content
    
    for did in original_defines:
        if did not in self.defines:
            deleted.append(did)
    
    # 3. 生成补丁
    return {"TKD.dat": {"added": added, "modified": modified, "deleted": deleted}}
```

### 2.5 统一差异算法

#### A类文件（定长记录）差异算法

```python
def diff_records(original, modified, file_type):
    """生成记录级差异"""
    diffs = []
    
    # 确定记录格式
    if file_type == "TKMat":
        field_count = 96  # 96个dword
        field_size = 4
    elif file_type == "TKDefUnit":
        field_count = 8   # 8个uint16
        field_size = 2
    elif file_type == "TKSkill":
        field_count = 47  # 47个int16 + 1个byte
        field_size = 2
    # ... 其他文件类型
    
    for i in range(min(len(original), len(modified))):
        orig_rec = original[i]
        mod_rec = modified[i]
        
        # 逐字段比对
        field_diffs = {}
        for f in range(field_count):
            orig_val = get_field(orig_rec, f)
            mod_val = get_field(mod_rec, f)
            if orig_val != mod_val:
                field_diffs[f"f{f}"] = mod_val
        
        if field_diffs:
            diffs.append({"index": i, "fields": field_diffs})
    
    return diffs
```

#### B类文件（文本）差异算法

```python
def diff_text(original_text, modified_defines):
    """生成DEFINE块级差异"""
    original_defines = parse_defines(original_text)
    
    added = []
    modified = {}
    deleted = []
    
    for did, content in modified_defines.items():
        if did not in original_defines:
            added.append(content)
        elif content != original_defines[did]:
            modified[did] = content
    
    for did in original_defines:
        if did not in modified_defines:
            deleted.append(did)
    
    return {"added": added, "modified": modified, "deleted": deleted}
```

---

## 三、启动器多MOD加载方案

### 3.1 当前启动器架构

```
Main()
  ├─ LogInit()
  ├─ EnsureSaveDirectoryHealthy()    ← 补丁十一
  ├─ PrepareWarPcForGame()           ← WarPC扩展前置处理
  ├─ Process.Start("TKS.exe")        ← 启动游戏
  ├─ 检测子进程
  ├─ 分配 WarPC 缓冲区               ← 补丁五的一部分
  ├─ BuildPatches() + ApplyPatches() ← 补丁一~四,十五~十七
  ├─ ExpandWarPcBuffer()             ← 补丁五~九,十二
  ├─ Patch4C33FC()                   ← 补丁十三
  ├─ Patch41C120()                   ← 补丁十四
  ├─ PatchArchivePortrait()          ← 补丁十五
  └─ InjectWarPCData()               ← 数据注入
```

**问题**：
1. 所有补丁硬编码在源代码中
2. 没有MOD加载机制
3. 没有补丁优先级/冲突处理

### 3.2 改造方案

#### 方案一：MOD目录扫描（推荐）

```
游戏目录/
├── TKS.exe
├── TKSLauncher.exe
├── mods/                          # MOD目录
│   ├── 00_base.tksmod            # 基础MOD（WarPC扩展等）
│   ├── 10_balance.tksmod         # 平衡性MOD
│   ├── 20_content.tksmod         # 内容MOD
│   └── 99_custom.tksmod          # 自定义MOD
├── patches/                       # 代码补丁目录
│   ├── warpc_expand.tkspatch
│   ├── team_limit.tkspatch
│   └── ...
└── data/                          # 原始数据文件
    ├── TKMat.Dat
    ├── TKDefUnit.Dat
    └── ...
```

#### 方案二：单一MOD文件

```
游戏目录/
├── TKS.exe
├── TKSLauncher.exe
├── active_mod.tksmod              # 当前激活的MOD
└── data/
    └── ...
```

### 3.3 启动器改造详细设计

#### 新的Main()流程

```csharp
static int Main(string[] args)
{
    LogInit();
    
    // 1. 扫描并加载MOD
    var mods = LoadAllMods("mods/");
    var patches = LoadAllPatches("patches/");
    
    // 2. 依赖解析 + 拓扑排序
    var sortedMods = ResolveDependencies(mods);
    var sortedPatches = ResolveDependencies(patches);
    
    // 3. 合并MOD数据
    var mergedData = MergeMods(sortedMods);
    
    // 4. 准备游戏文件
    PrepareGameFiles(mergedData);
    
    // 5. 启动游戏
    Process tksProc = Process.Start("TKS.exe");
    
    // 6. 等待子进程
    int childPid = WaitForChildProcess(tksProc);
    
    // 7. 应用代码补丁
    ApplyCodePatches(childPid, sortedPatches);
    
    // 8. 扩展缓冲区
    if (mergedData.WarpcExpanded)
        ExpandWarPcBuffer(childPid, mergedData);
    
    // 9. 注入数据
    InjectModData(childPid, mergedData);
    
    return 0;
}
```

#### MOD加载器

```csharp
class ModLoader
{
    /// <summary>
    /// 扫描mods/目录，加载所有.tksmod文件
    /// </summary>
    static List<ModInfo> LoadAllMods(string modsDir)
    {
        var mods = new List<ModInfo>();
        
        if (!Directory.Exists(modsDir))
            return mods;
        
        foreach (var file in Directory.GetFiles(modsDir, "*.tksmod"))
        {
            try
            {
                var mod = LoadMod(file);
                mods.Add(mod);
                Log($"  加载MOD: {mod.Name} v{mod.Version}");
            }
            catch (Exception e)
            {
                Log($"  [WARN] 加载 {file} 失败: {e.Message}");
            }
        }
        
        return mods;
    }
    
    /// <summary>
    /// 加载单个MOD文件
    /// </summary>
    static ModInfo LoadMod(string path)
    {
        // .tksmod是ZIP压缩包
        using (var archive = ZipFile.OpenRead(path))
        {
            // 读取mod.json
            var modJsonEntry = archive.GetEntry("mod.json");
            using (var stream = modJsonEntry.Open())
            using (var reader = new StreamReader(stream))
            {
                var json = reader.ReadToEnd();
                var modInfo = JsonConvert.DeserializeObject<ModInfo>(json);
                modInfo.Path = path;
                return modInfo;
            }
        }
    }
    
    /// <summary>
    /// 依赖解析 + 拓扑排序
    /// </summary>
    static List<ModInfo> ResolveDependencies(List<ModInfo> mods)
    {
        // 构建依赖图
        var graph = new Dictionary<string, List<string>>();
        var inDegree = new Dictionary<string, int>();
        
        foreach (var mod in mods)
        {
            graph[mod.Id] = new List<string>();
            inDegree[mod.Id] = 0;
        }
        
        foreach (var mod in mods)
        {
            foreach (var dep in mod.Dependencies)
            {
                if (graph.ContainsKey(dep))
                {
                    graph[dep].Add(mod.Id);
                    inDegree[mod.Id]++;
                }
                else
                {
                    Log($"  [ERROR] MOD {mod.Id} 依赖 {dep} 未找到");
                }
            }
        }
        
        // 拓扑排序
        var queue = new Queue<string>();
        foreach (var kv in inDegree)
        {
            if (kv.Value == 0)
                queue.Enqueue(kv.Key);
        }
        
        var sorted = new List<ModInfo>();
        while (queue.Count > 0)
        {
            var id = queue.Dequeue();
            var mod = mods.First(m => m.Id == id);
            sorted.Add(mod);
            
            foreach (var next in graph[id])
            {
                inDegree[next]--;
                if (inDegree[next] == 0)
                    queue.Enqueue(next);
            }
        }
        
        // 检测循环依赖
        if (sorted.Count != mods.Count)
        {
            Log("  [ERROR] 检测到循环依赖!");
            return mods; // 返回原始顺序
        }
        
        return sorted;
    }
}
```

#### MOD合并器

```csharp
class ModMerger
{
    /// <summary>
    /// 合并多个MOD的数据
    /// </summary>
    static MergedData MergeMods(List<ModInfo> mods)
    {
        var merged = new MergedData();
        
        // 初始化为原始文件数据
        merged.TkMat = LoadOriginalTkMat();
        merged.TkDefUnit = LoadOriginalTkDefUnit();
        merged.Tkd = LoadOriginalTkd();
        merged.TkSkill = LoadOriginalTkSkill();
        merged.TkItem = LoadOriginalTkItem();
        merged.Warpc = LoadOriginalWarpc();
        
        // 按顺序应用每个MOD
        foreach (var mod in mods)
        {
            Log($"  应用MOD: {mod.Name}");
            
            // 应用数据补丁
            if (mod.Components.ContainsKey("TKMat.dat"))
                ApplyTkMatPatch(merged.TkMat, mod.Components["TKMat.dat"]);
            
            if (mod.Components.ContainsKey("TKDefUnit.dat"))
                ApplyTkDefUnitPatch(merged.TkDefUnit, mod.Components["TKDefUnit.dat"]);
            
            if (mod.Components.ContainsKey("TKD.dat"))
                ApplyTkdPatch(merged.Tkd, mod.Components["TKD.dat"]);
            
            if (mod.Components.ContainsKey("TKSkill.dat"))
                ApplyTkSkillPatch(merged.TkSkill, mod.Components["TKSkill.dat"]);
            
            if (mod.Components.ContainsKey("WarPC.dat"))
                ApplyWarpcPatch(merged.Warpc, mod.Components["WarPC.dat"]);
            
            // 应用资源配置
            foreach (var res in mod.Resources)
            {
                ApplyResource(merged, res);
            }
            
            // 应用WarPC扩展配置
            if (mod.WarpcConfig != null)
            {
                if (mod.WarpcConfig.ExpandTo > 0)
                    merged.WarpcExpandCount = Math.Max(merged.WarpcExpandCount, mod.WarpcConfig.ExpandTo);
                
                if (mod.WarpcConfig.SkillLearnExtend > 0)
                    merged.SkillLearnExtend = Math.Max(merged.SkillLearnExtend, mod.WarpcConfig.SkillLearnExtend);
            }
        }
        
        return merged;
    }
    
    /// <summary>
    /// 应用TKMat补丁
    /// </summary>
    static void ApplyTkMatPatch(List<TkMatRecord> records, PatchData patch)
    {
        foreach (var diff in patch.Diffs)
        {
            int index = diff.Index;
            if (index < 0 || index >= records.Count)
            {
                Log($"    [WARN] TKMat索引 {index} 超出范围，跳过");
                continue;
            }
            
            var rec = records[index];
            foreach (var field in diff.Fields)
            {
                SetField(rec, field.Key, field.Value);
            }
        }
    }
    
    /// <summary>
    /// 应用TKD补丁
    /// </summary>
    static void ApplyTkdPatch(Dictionary<int, string> defines, TkdPatch patch)
    {
        // 添加新的DEFINE块
        foreach (var added in patch.Added)
        {
            int id = ParseDefineId(added);
            defines[id] = added;
        }
        
        // 修改现有的DEFINE块
        foreach (var kv in patch.Modified)
        {
            defines[kv.Key] = kv.Value;
        }
        
        // 删除DEFINE块
        foreach (var id in patch.Deleted)
        {
            defines.Remove(id);
        }
    }
}
```

#### 冲突检测

```csharp
class ConflictDetector
{
    /// <summary>
    /// 检测MOD之间的冲突
    /// </summary>
    static List<Conflict> DetectConflicts(List<ModInfo> mods)
    {
        var conflicts = new List<Conflict>();
        
        // 检查声明的冲突
        for (int i = 0; i < mods.Count; i++)
        {
            for (int j = i + 1; j < mods.Count; j++)
            {
                var mod1 = mods[i];
                var mod2 = mods[j];
                
                // 检查显式冲突声明
                if (mod1.Conflicts.Contains(mod2.Id) || mod2.Conflicts.Contains(mod1.Id))
                {
                    conflicts.Add(new Conflict
                    {
                        Mod1 = mod1.Id,
                        Mod2 = mod2.Id,
                        Type = ConflictType.Explicit,
                        Description = "MOD显式声明冲突"
                    });
                }
                
                // 检查数据冲突
                var dataConflicts = DetectDataConflicts(mod1, mod2);
                conflicts.AddRange(dataConflicts);
            }
        }
        
        return conflicts;
    }
    
    /// <summary>
    /// 检测数据级冲突
    /// </summary>
    static List<Conflict> DetectDataConflicts(ModInfo mod1, ModInfo mod2)
    {
        var conflicts = new List<Conflict>();
        
        // 检查TKMat冲突
        if (mod1.Components.ContainsKey("TKMat.dat") && mod2.Components.ContainsKey("TKMat.dat"))
        {
            var patch1 = mod1.Components["TKMat.dat"];
            var patch2 = mod2.Components["TKMat.dat"];
            
            foreach (var diff1 in patch1.Diffs)
            {
                foreach (var diff2 in patch2.Diffs)
                {
                    if (diff1.Index == diff2.Index)
                    {
                        // 检查字段级冲突
                        foreach (var field1 in diff1.Fields)
                        {
                            if (diff2.Fields.ContainsKey(field1.Key))
                            {
                                conflicts.Add(new Conflict
                                {
                                    Mod1 = mod1.Id,
                                    Mod2 = mod2.Id,
                                    Type = ConflictType.Data,
                                    File = "TKMat.dat",
                                    Index = diff1.Index,
                                    Field = field1.Key,
                                    Description = $"TKMat记录{diff1.Index}字段{field1.Key}冲突"
                                });
                            }
                        }
                    }
                }
            }
        }
        
        // 类似检查其他文件...
        
        return conflicts;
    }
}
```

### 3.4 启动器GUI改造

```csharp
class ModManagerForm : Form
{
    private ListBox modListBox;
    private RichTextBox modDetailsBox;
    private Button btnEnable, btnDisable, btnUp, btnDown;
    private Button btnLaunch;
    
    public ModManagerForm()
    {
        InitializeComponent();
        LoadMods();
    }
    
    private void InitializeComponent()
    {
        this.Text = "TKS MOD管理器";
        this.Size = new Size(800, 600);
        
        // 左侧：MOD列表
        var leftPanel = new Panel { Dock = DockStyle.Left, Width = 300 };
        
        modListBox = new ListBox { Dock = DockStyle.Fill };
        modListBox.SelectedIndexChanged += ModListBox_SelectedIndexChanged;
        leftPanel.Controls.Add(modListBox);
        
        // 右侧：MOD详情
        var rightPanel = new Panel { Dock = DockStyle.Fill };
        
        modDetailsBox = new RichTextBox { Dock = DockStyle.Fill, ReadOnly = true };
        rightPanel.Controls.Add(modDetailsBox);
        
        // 底部：按钮
        var bottomPanel = new Panel { Dock = DockStyle.Bottom, Height = 50 };
        
        btnLaunch = new Button { Text = "启动游戏", Dock = DockStyle.Right };
        btnLaunch.Click += BtnLaunch_Click;
        bottomPanel.Controls.Add(btnLaunch);
        
        this.Controls.Add(rightPanel);
        this.Controls.Add(leftPanel);
        this.Controls.Add(bottomPanel);
    }
    
    private void LoadMods()
    {
        var mods = ModLoader.LoadAllMods("mods/");
        
        foreach (var mod in mods)
        {
            modListBox.Items.Add(new ModListItem
            {
                Mod = mod,
                Display = $"{mod.Name} v{mod.Version} ({mod.Author})"
            });
        }
    }
    
    private void ModListBox_SelectedIndexChanged(object sender, EventArgs e)
    {
        if (modListBox.SelectedItem is ModListItem item)
        {
            var mod = item.Mod;
            modDetailsBox.Text = $"名称: {mod.Name}\n" +
                                $"版本: {mod.Version}\n" +
                                $"作者: {mod.Author}\n" +
                                $"描述: {mod.Description}\n\n" +
                                $"依赖: {string.Join(", ", mod.Dependencies)}\n" +
                                $"冲突: {string.Join(", ", mod.Conflicts)}\n\n" +
                                $"组件:\n";
            
            foreach (var comp in mod.Components)
            {
                modDetailsBox.Text += $"  - {comp.Key} ({comp.Value.Type})\n";
            }
        }
    }
    
    private async void BtnLaunch_Click(object sender, EventArgs e)
    {
        // 收集选中的MOD
        var selectedMods = new List<ModInfo>();
        foreach (ModListItem item in modListBox.Items)
        {
            if (item.Enabled)
                selectedMods.Add(item.Mod);
        }
        
        // 依赖解析
        var sortedMods = ModLoader.ResolveDependencies(selectedMods);
        
        // 冲突检测
        var conflicts = ConflictDetector.DetectConflicts(sortedMods);
        if (conflicts.Count > 0)
        {
            var result = MessageBox.Show(
                $"检测到 {conflicts.Count} 个冲突，是否继续？\n\n" +
                string.Join("\n", conflicts.Select(c => c.Description)),
                "冲突警告",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning);
            
            if (result != DialogResult.Yes)
                return;
        }
        
        // 合并MOD
        var mergedData = ModMerger.MergeMods(sortedMods);
        
        // 启动游戏
        this.Hide();
        await GameLauncher.Launch(mergedData);
        this.Close();
    }
}

class ModListItem
{
    public ModInfo Mod { get; set; }
    public string Display { get; set; }
    public bool Enabled { get; set; } = true;
    
    public override string ToString()
    {
        return (Enabled ? "[✓] " : "[ ] ") + Display;
    }
}
```

---

## 四、实施方案

### 4.1 阶段一：编辑器改造（2-3周）

**目标**：让每个编辑器支持导出.tksmod增量补丁

**任务**：
1. 定义统一的.tksmod格式规范
2. 实现通用的差异算法库
3. 改造mat_editor（最复杂，涉及3个文件）
4. 改造warpc_editor
5. 改造skill_editor / item_editor
6. 改造script_editor / tkt_editor
7. 其他编辑器（按需）

**验证**：
- 每个编辑器导出的.tksmod可以独立应用
- 多个.tksmod可以正确合并

### 4.2 阶段二：启动器改造（2-3周）

**目标**：让启动器支持加载多个MOD

**任务**：
1. 实现MOD扫描和加载器
2. 实现依赖解析和拓扑排序
3. 实现MOD合并器
4. 实现冲突检测
5. 改造Main()流程
6. 添加GUI MOD管理器（可选）

**验证**：
- 可以加载单个MOD
- 可以加载多个MOD并正确合并
- 冲突检测正确工作
- 游戏正常运行

### 4.3 阶段三：测试和优化（1-2周）

**任务**：
1. 端到端测试
2. 性能优化
3. 文档编写
4. 示例MOD制作

### 4.4 实施顺序建议

```
阶段一（编辑器改造）：
  1. 定义.tksmod格式规范
  2. 实现差异算法库
  3. 改造 mat_editor（最复杂）
  4. 改造 warpc_editor
  5. 改造 skill_editor / item_editor
  6. 改造 script_editor / tkt_editor
  
阶段二（启动器改造）：
  1. 实现MOD加载器
  2. 实现依赖解析
  3. 实现MOD合并器
  4. 改造Main()流程
  5. 添加GUI（可选）
  
阶段三（测试优化）：
  1. 端到端测试
  2. 性能优化
  3. 文档编写
```

---

## 五、关键问题与解决方案

### 5.1 文件格式兼容性

**问题**：不同编辑器编辑的文件格式不同（定长/变长/压缩/加密）

**解决方案**：
- A类文件（定长记录）：统一使用记录号+字段号的差异格式
- B类文件（文本）：统一使用内容ID的差异格式
- C类文件（资源）：统一使用完整替换

### 5.2 WarPC扩展冲突

**问题**：多个MOD可能要求不同的WarPC扩展大小

**解决方案**：
- 取最大值：`merged.WarpcExpandCount = Math.Max(mod1, mod2, ...)`
- 启动器根据合并后的配置进行扩展

### 5.3 技能上限冲突

**问题**：多个MOD可能要求不同的技能上限

**解决方案**：
- 取最大值：`merged.SkillLearnExtend = Math.Max(mod1, mod2, ...)`
- 需要确保WarPC扩展足够容纳

### 5.4 资源文件冲突

**问题**：多个MOD可能替换同一个资源文件

**解决方案**：
- 后加载的MOD覆盖先加载的
- 冲突检测时警告用户

### 5.5 代码补丁冲突

**问题**：多个MOD可能修改同一个RVA

**解决方案**：
- 检测RVA冲突
- 如果数据相同，只应用一次
- 如果数据不同，报错并提示用户

---

## 六、总结

### 6.1 可行性评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **技术可行性** | ⭐⭐⭐⭐⭐ | 所有数据文件格式都支持增量补丁 |
| **工作量** | ⭐⭐⭐☆☆ | 中等，约4-6周 |
| **兼容性** | ⭐⭐⭐⭐☆ | 与现有代码高度兼容 |
| **扩展性** | ⭐⭐⭐⭐⭐ | 易于添加新文件类型支持 |
| **用户体验** | ⭐⭐⭐⭐☆ | MOD安装简单，冲突检测完善 |

### 6.2 核心优势

1. **统一格式**：所有编辑器输出统一的.tksmod格式
2. **增量补丁**：只存储差异，文件小
3. **依赖管理**：支持MOD依赖声明和解析
4. **冲突检测**：自动检测数据级冲突
5. **向后兼容**：与现有代码补丁系统兼容

### 6.3 实施建议

1. **先做mat_editor**：最复杂，做好后其他编辑器可复用模式
2. **先做简单MOD**：先支持只有数据修改的简单MOD
3. **逐步扩展**：后续添加资源替换、代码补丁等高级功能
4. **保持简单**：初期不要过度设计，按需扩展

---

## 附录A：数据文件格式速查

| 文件 | 记录大小 | 记录数 | 字段数 | 字段类型 |
|------|----------|--------|--------|----------|
| TKMat.Dat | 384B | 6000 | 96 | dword (int32) |
| TKDefUnit.Dat | 16B | 5000 | 8 | uint16 |
| TKSkill.dat | 94B | 350 | 47+1 | int16 + byte |
| TKItem.dat | 64B | 600 | 32 | int16 |
| TKShop.dat | 16B | 120 | 8 | uint16 |
| TKKon.dat | 104B | 250 | 52 | int16 |
| WarPC.dat | 1054B | 143 | 527 | int16 |

## 附录B：现有编辑器文件路径

```

├── mat_editor/mat_editor.py          # TKMat + TKDefUnit + TKD
├── warpc_editor/warpc_editor.py      # WarPC
├── skill_editor/skill_editor.py      # TKSkill
├── item_editor/item_editor.py        # TKItem
├── script_editor/script_editor.py    # TKD
├── defunit_editor/defunit_editor.py  # TKDefUnit
├── tkt_editor/tkt_editor.py          # TKT
├── shop_editor/shop_editor.py        # TKShop
├── kon_editor/kon_editor.py          # TKKon
├── wardata_editor/wardata_editor.py  # WarData
├── act_editor/act_editor.py          # ACT
├── grp_editor/grp_editor.py          # GRP/IDX
├── gxp_editor/gxp_editor.py          # GXP
├── jvg_editor/jvg_editor.py          # JVG
├── spritesheet_editor/spritesheet_editor.py  # 精灵表
└── save_editor/save_editor.py        # 存档
```

## 附录C：启动器文件路径

```
tks_launcher/
├── tks_launcher.cs                   # 主启动器代码
├── tkspatch补丁模块化方案可行性分析.md
├── 补丁十六_skill_learn扩容方案分析.md
└── ...
```
