# .tksmod 增量补丁方案可行性分析

> 分析日期：2026-05-29
> 分析范围：`mat_editor.py` (3665行) + `tks_launcher.cs` (2572行)

---

## 一、当前架构梳理

### 1.1 编辑器保存管线（`mat_editor.py` 第 3602-3626 行）

```
_save() → 一次性写入 3 个文件:
  1. save_mat()     → TKMat.Dat     (2304000 字节, 6000×384B 定长结构体)
  2. save_defunit() → TKDefUnit.Dat (80000 字节, 5000×16B 定长结构体)
  3. save_tkd()     → TKD.dat       (变长, Big5文本 XOR 0xFF 加密)
```

**关键特征**：直接覆盖原文件，没有任何备份机制。

### 1.2 启动器文件处理（`tks_launcher.cs`）

```
Main() 启动流程:
  1. EnsureSaveDirectoryHealthy()    → 清理 0 字节存档索引
  2. PrepareWarPcForGame()           → ★ 已有 .orig 备份/截断/恢复机制
  3. Process.Start("TKS.exe")        → 启动游戏
  4. 检测子进程 → OpenProcess        → 内存补丁注入
  5. ExpandWarPcBuffer()             → VirtualAllocEx 扩展 WarPC 缓冲区
  6. 退出（补丁随进程消失）
```

**关键特征**：
- **只做内存级补丁**（WriteProcessMemory），不修改 .dat 文件内容
- **已有文件备份/恢复基础设施**：`PrepareWarPcForGame()` 创建 `.orig` 备份，截断超限文件；游戏启动后恢复原始文件
- 没有现有的 MOD 加载或 diff/patch 文件格式

### 1.3 编辑器加载管线（`mat_editor.py` `_reload()` 第 2352 行）

```
_reload() → 加载:
  1. TKT.dat          → 全文数据库 + 场景名称
  2. TKDefUnit.Dat    → DefUnit 链数据
  3. TKD.dat          → 脚本 DEFINE 块
  4. TKItem.dat       → 物品名称映射
  5. SC.GRP / SC.IDX  → 场景背景
  6. Ani.JVG / Cha.JVG / Cur.JVG → 精灵数据
  7. TKMat.Dat        → 实体表 (load_mat)
```

---

## 二、可行性判定：✅ 高度可行

### 2.1 核心优势

| 因素 | 分析 |
|------|------|
| **文件格式** | 三个目标文件都是定长记录结构（TKMat 6000×384B, TKDefUnit 5000×16B），TKD.dat 是文本。做 diff 极其简单——按记录号/字段号比对即可 |
| **启动器基础设施** | `PrepareWarPcForGame()` 已经实现了完全相同的"备份→修改→恢复"模式，`.tksmod` 可以复用这套机制 |
| **控制权** | 编辑器和启动器都在同一开发者控制下，格式设计不受第三方限制 |
| **无需逆向** | 不需要分析新的游戏函数，启动器只需在启动前修改文件，游戏正常读取即可 |

### 2.2 需要面对的问题

#### 问题一：两种补丁范式的区别

| 现有机制 | .tksmod 机制 |
|----------|-------------|
| 修改游戏**代码**（机器指令） | 修改游戏**数据文件**（实体表、脚本、DefUnit链） |
| 运行时注入进程内存 | 启动前修改磁盘文件（或启动后修改内存中的数据缓冲区） |
| 补丁地址是固定 RVA | 补丁目标是已知偏移的数据字段 |

#### 问题二：差异化策略选择

需要决定 diff 的粒度：

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **字节级 diff** | 对比原始文件和修改后文件的每个字节 | 最简单，通用 | 脆弱——原始文件任何变化都会导致 patch 失效 |
| **记录级 diff** | 按每条记录（384B/16B）比对，只存变化的记录 | TKMat/TKDefUnit 天然支持 | TKD.dat 不太适合按记录 |
| **字段级 diff** | 按每个字段（dword/word）比对 | 最精确，最鲁棒 | 实现稍复杂 |

---

## 三、推荐方案设计

### 3.1 .tksmod 文件格式（推荐 JSON 格式）

```json
{
  "magic": "TKSMOD",
  "version": 1,
  "created": "2026-05-29T12:00:00",
  "comment": "My Mod v1.0",
  "checksums": {
    "TKMat.dat":    "crc32_of_original",
    "TKDefUnit.dat": "crc32_of_original",
    "TKD.dat":       "crc32_of_original"
  },
  "patches": {
    "TKMat.dat": [
      {"index": 142, "fields": {"d0": 200, "d10": 512, "d11": 384}},
      {"index": 143, "fields": {"d0": 200, "d10": 530, "d11": 400}}
    ],
    "TKDefUnit.dat": [
      {"index": 42, "fields": {"f0": 256, "f1": 5}}
    ],
    "TKD.dat": {
      "added": ["DEFINE 100663296\n{\nSetFlag(1,1)\nEnd(0)\n}; end\n"],
      "modified": {"100663297": "DEFINE 100663297\n{\nTalkA(-1,9001)\nEnd(0)\n}; end\n"}
    }
  }
}
```

**为什么选 JSON 而不是二进制**：
- 格式完全可控，不需要为节省几 KB 引入二进制复杂度
- JSON 可读、可调试、可手动编辑
- TKMat 修改通常只涉及几十条记录的几个字段，数据量很小
- TKD.dat 的脚本内容本身就是文本，JSON 内嵌文本最自然

### 3.2 编辑器侧改造（mat_editor.py）

在 `_save()` 方法（第 3602 行）中增加分支选项：

```python
# 当前流程
_save() → 直接写 3 个 .dat 文件

# 新增流程  
_export_tksmod() → 
  1. 加载原始 .dat 文件（校验 CRC32）
  2. 逐记录比对当前内存状态与原始文件
  3. 生成差异 JSON
  4. 写入 .tksmod 文件
```

**关键实现细节**：
- 编辑器加载时，在 `_reload()` 中保存一份原始文件的快照（`self._original_records`、`self._original_defunit`、`self._original_tkd`）
- 导出 .tksmod 时，比对当前 `self.records` 与 `self._original_records`，只输出变化的记录
- 对 TKMat：比对 96 个 dword，只输出 `d0`~`d95` 中与原始不同的字段
- 对 TKDefUnit：比对 8 个 uint16 字段
- 对 TKD：文本级 diff（完整替换修改过的 DEFINE 块）

### 3.3 启动器侧改造（tks_launcher.cs）

在 `Main()` 的 `PrepareWarPcForGame()` 之前插入：

```csharp
// 第 2115 行附近，PrepareWarPcForGame() 之前
ApplyTksMod();  // 新增

static void ApplyTksMod()
{
    string modPath = "*.tksmod";  // 或指定文件名
    if (!File.Exists(modPath)) return;
    
    // 1. 解析 .tksmod JSON
    // 2. 校验原始文件 CRC32
    // 3. 对每个目标文件：
    //    a. 备份原始文件（复用现有的 .orig 机制）
    //    b. 解压/读取原始文件
    //    c. 在内存中应用 patch
    //    d. 写回修改后的文件
    // 4. PrepareWarPcForGame() 继续正常工作
}
```

**与现有机制的契合点**：
- 启动器已有的 `.orig` 备份/恢复机制完美兼容——游戏退出后原始文件自动恢复
- `LzssDecompress()` / `LzssCompress()` 已实现，可用于需要解压的 .dat 文件
- 如果 `TKMat.dat` 需要超过原始 2304000 字节，启动器已有的 `PatchDataFileSizes()` 会自动修补代码中的大小常量

---

## 四、需要注意的边界情况

### 4.1 原始文件 CRC 校验失败
用户可能已经直接修改过 .dat 文件，导致原始文件与 .tksmod 记录的校验和不匹配 → 启动器应给出明确警告并拒绝加载

### 4.2 多个 .tksmod 文件的冲突
如果用户有多个 MOD，需要决定加载顺序（例如按文件名排序，后面的覆盖前面的）

### 4.3 TKD.dat 的 "added" 语义
新增 DEFINE 块时需要插入到正确位置（在 `};` 之后、下一个 DEFINE 之前）。建议通过 define_id 定位插入点

### 4.4 TKMat.dat 的"空槽"问题
如果一个 patch 要修改 index 为 142 的记录但原始文件中该位置是空槽（d0=0），这是合法的——编辑器本身也支持修改空槽

### 4.5 文件大小变化
如果新增了大量实体导致 TKMat/DEFUnit 超过原始长度，启动器已有的 `PatchDataFileSizes()` 会处理。但 TKD.dat 是文本格式，没有固定大小限制

### 4.6 启动器崩溃恢复
如果启动器在写入修改文件后崩溃，`.orig` 备份不会被恢复。这和现有 WarPC 扩展的风险相同。可以在下次启动时检测 `.orig` 残留并自动恢复

---

## 五、总结

| 维度 | 评估 |
|------|------|
| **技术可行性** | ⭐⭐⭐⭐⭐ 极其可行 |
| **工作量** | 中等——编辑器 ~100 行新增代码，启动器 ~200 行 |
| **与现有代码的兼容性** | ⭐⭐⭐⭐⭐ 完美契合，复用现有 .orig 备份机制 |
| **风险** | 低——主要风险是原始文件校验不匹配，可检测并报错 |
| **扩展性** | 好——后续可以轻松添加对 WarPC.dat、TKItem.dat 等的支持 |

### 建议的实施顺序

1. 先在编辑器中实现"保存原始快照"逻辑（在 `_reload()` 中）
2. 实现 `_export_tksmod()` 导出功能
3. 在启动器中实现 `.tksmod` 解析和应用
4. 端到端测试：编辑器导出 → 启动器加载 → 游戏验证
