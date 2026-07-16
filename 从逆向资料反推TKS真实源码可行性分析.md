# 从逆向工程资料反推《三国群侠传》(TKS) 真实源码 —— 可行性分析与开发建议

> 撰写目标：基于 `build_all.py` 注册的 18 个编辑器所体现的资源逆向深度，以及
> `反编译产物/` 的反编译资料，严谨评估"能否反推出游戏真实源码"，
> 并给出以**原开发框架**（Borland C++Builder 6 + VCL + DirectDraw/DirectSound）重建的开发步骤。
>
> **方法论纪律**：本文所有技术结论均标注证据来源（字符串地址 / 反编译函数 / 编辑器源码 / 已有分析文档）。
> 凡无法从现有资料直接核验的，一律显式标注为"未知/黑盒"，**禁止臆测**。

---

## 0. 结论摘要 (TL;DR)

| 命题 | 结论 | 依据强度 |
|------|------|----------|
| **能否还原逐字节等价的"原始源码"**（含原注释/原变量名/原 .dfm 设计器布局） | **不能** | 编译不可逆，信息已永久丢失 |
| **能否反推出原始技术栈并据此"净室等价重写"** | **能，且工程边界清晰可控** | 框架已 100% 确认、数据层已 100% 破解、逻辑层 98.7% 可读 |
| 原始开发框架 | **Borland C++Builder 6 + VCL + DirectDraw7 + DirectSound** | 多重强证据交叉印证（见 §2） |
| 数据格式掌握度 | **15+ 种格式全部完成编解码往返** | 18 个编辑器 + `editor_utils` codec（见 §4） |
| 反编译覆盖度 | **4808 函数中 4745 (98.7%) 反编译为 C** | `function_index.txt` / 已有分析文档 |

**一句话结论**：无法"复活"原始源码工程本身，但可以在**原框架 (C++Builder 6 VCL)** 下做一次**功能等价、行为可对照验证的净室重写**——因为最难的部分（数据格式、主循环、脚本 VM、战斗数值公式）都已被现有资产解决或高度还原。

---

## 1. 命题辨析：什么叫"反推真实源码"

"反推源码"存在两种截然不同的含义，必须先厘清，否则可行性结论会自相矛盾：

### 1.1 含义 A：逐字节源码还原（verbatim recovery）——**不可能**

编译是**有损**过程。以下信息在 `TKS.exe` 编译时已被永久丢弃，**任何反编译器都无法恢复**：

- **原始注释**：全部丢失。
- **原始标识符名**：局部变量退化为 `v1/v3/j/k`（见 `decompile/4030F0.c`）；游戏自有函数仅剩地址名 `sub_XXXXXX`。仅 VCL 框架方法因 RTTI 保留了名字（如 `Controls::TControl::SetCursor`）。
- **原始 `.dfm` 窗体设计**：VCL 的窗体是设计期可视化拼装的。运行期只剩组件的**创建调用序列**，设计器里设置的大量属性（位置、字体、Tag、事件绑定表）已被序列化进资源并被壳加密，难以完整回推。
- **单元(unit)划分与文件组织**：仅 `Unit1`、`Tkgmthread` 两个单元名经由导出符号 `@@Unit1@Initialize`、`@@Tkgmthread@Initialize` 幸存（`exports.txt`）；其余约 4800 个函数的原始 `.cpp/.h` 归属已丢失。
- **宏/内联/模板展开**：`_STL::` 模板已被实例化展开，无法回推原始泛型写法。

> 结论：**"拿回原作者的 .bpr 工程 + 原始 .cpp/.dfm"这件事在物理上不可能。** 这一点必须对预期设"硬约束"。

### 1.2 含义 B：功能等价的净室重写（clean-room reimplementation）——**可行**

指：**理解**原程序的行为与数据，在原框架下**重新编写**一份能产生相同游戏体验、且可与原版逐项对照验证的源码工程。这条路可行，因为它不依赖"恢复丢失信息"，只依赖"理解现存行为"，而现存资产恰好把理解成本压到了很低（见 §3–§5）。

**本文后续所有"可行""开发步骤"均指含义 B。**

---

## 2. 证据基础：原始技术栈的确定性识别

这是整份分析的地基。以下每一条都可在资料中直接核验。

### 2.1 关键澄清：`反编译产物` 是"脱壳后的真实游戏"，不是外壳

现有资料中存在一处**极易误导**的矛盾，必须先解决：

- `逆向工作区.exe逆向分析报告.md` 判定：编译器=**MSVC**、映像仅 68KB、90% 为加密 Overlay、保护壳=**Armadillo (Software Passport)**。
- 但 `反编译产物/memory/*.txt` 的地址跨度为 `0x00401000`–`0x00A7D000`（约 6.5 MB），且导入表基址在 `0xA6xxxx`（`imports.txt`）。

二者并不冲突，而是**两层不同的东西**：

| 层 | 是什么 | 编译器 | 证据 |
|----|--------|--------|------|
| 外层（发行 EXE） | Armadillo 保护壳/加载器 | MSVC | `TKS.exe逆向分析报告.md`：Mailslot IPC、`DebugActiveProcess`、CRC、529KB 高熵 Overlay |
| **内层（真实游戏）** | 被壳解密后注入内存运行的本体 | **Borland C++Builder** | 本导出目录 = 运行时内存 dump（文件名 `pe_dump_TKS.TMP0_pid11344_t2.exe`，见 `TKS游戏核心逻辑调用关系分析.md`） |

也就是说，逆向者已按报告建议完成了"内存转储脱壳"，`反编译产物` 就是**脱壳后本体**的反编译。**本文分析的对象是内层真实游戏。**

### 2.2 编译器与 UI 框架：Borland C++Builder 6 + VCL（多重强证据）

| 证据 | 位置 | 指向 |
|------|------|------|
| `Borland C++ - Copyright 2002 Borland Corporation` | `strings.txt` 0x4e6000 | Borland C++（2002 版即 **C++Builder 6**）|
| `System::DelphiInterface<Classes::IStringsAdapter>` 等 | `strings.txt` 0x404ab0+ | **C++Builder 独有**的 C++ 模板包装 Delphi 接口 |
| `Forms::TForm`、`TForm1`、`TApplication` | `strings.txt` 0x4045f4/0x4046f0/0x477a94 | **VCL** 框架（C++ `::` 命名空间 RTTI）|
| `_Form1`、`@@Unit1@Initialize/Finalize`、`@@Tkgmthread@Initialize/Finalize` | `exports.txt` | VCL 主窗体 + Borland 单元初始化/终结模型 |
| `___CPPdebugHook`、`__GetExceptDLLinfo` | `exports.txt` | Borland **C++** 运行时符号 |
| `_STL::num_put`、`_STL::hash_map` … | `strings.txt` 0x4e23c8+ | **STLport**（C++Builder 6 捆绑的 STL 实现）|
| `SOFTWARE\Borland\Delphi\RTL`、`Software\Borland\Locales` | `strings.txt` 0x4ab0e0+ | Borland VCL RTL 注册表键 |
| `_TForm1_FormCreate/FormClose/FormMouseDown/Up/MouseMove/DblClick/FormPaint/FormKeyDown/Up/KeyPress` | `function_index.txt` | VCL 主窗体标准事件处理器**全套齐备** |

> 判定：**Borland C++Builder 6（C++ 语言 + VCL 组件框架 + STLport）**，证据链闭合、无歧义。

### 2.3 图形 / 音频 / 视频子系统

| 子系统 | 技术 | 证据（`imports.txt` / `strings.txt`）|
|--------|------|------|
| 2D 渲染 | **DirectDraw**（表面 Blt，640×480，RGB565） | `DirectDrawCreate`；渲染分析见 `sub_4CB590` |
| 兼容渲染 | **GDI32** | `BitBlt/StretchBlt/CreateDIBSection/CreateDIBitmap/StretchDIBits` 等成套 GDI 导入 |
| 音频 | **DirectSound** | `DirectSoundCreate` |
| 视频 | 片头 AVI | 字符串 `Logo1.avi/Logo2.avi/Title.avi`；配合 `ole32:CoCreateInstance/CoInitialize` 的 COM 创建（AVI 播放路径）|
| 输入法 | IMM | `ImmGetDescriptionA/ImmReleaseContext`（中文输入）|

### 2.4 游戏引擎骨架（来自反编译，已由现有文档核验）

```
start → @@Unit1@Initialize
      → @@Tkgmthread@Initialize (0x4130EC, 游戏主线程)
            └─ sub_412BE8  ← 游戏主循环 (60fps, TForm1.MplayTimerTimer 驱动)
                 ├─ 资源初始化 (Mu.jvg/pface.jvg/Mb.gxp …)
                 ├─ SCE 脚本 VM      sub_40EBD4 (603 行, 82 opcode)
                 ├─ 实体调度器        sub_409618 (数据驱动 ECS 式类型分发)
                 ├─ 战斗系统          sub_447DAC(状态机) / sub_4458B0(伤害) / sub_43E980(AI) / sub_4434BC(动画)
                 └─ 场景渲染          sub_4CB590 (1322 行, 最大函数)
```

> 来源：`TKS游戏核心逻辑调用关系分析.md`、`TKS_地图数据驱动机制分析.md`。这些结论均带反编译函数地址，可复核。

---

## 3. 逆向资产盘点（"重建成本"为何很低）

反推含义 B 的成本，取决于三类资产的完备度。现状是三者都相当完整：

### 3.1 反编译代码

| 指标 | 数值 | 来源 |
|------|------|------|
| 导出函数总数 | 4808（`function_index.txt` 头部记 2040 为本次导出子集） | `function_index.txt` |
| 反编译为 C | 4745（98.7%） | `TKS手机版移植可行性分析报告.md` |
| 汇编回退 | 63（1.3%，含 `sub_4400DC` >3000 指令战斗核心） | `disassembly/4400DC.asm` 等 |
| 反编译总行数 | ~280,000 行 | 同上 |

**质量评估**（据 `decompile/4030F0.c` 实读）：Hex-Rays 输出，VCL 方法调用已符号化、资源加载逻辑清晰（可见 `SC.idx/SC.grp` 打开、`TKDef.txt/TKD.dat` 加载、`*i = ~*i` 的按位取反解密、`TKMat.Dat` 2,304,000 字节装载）。缺陷是局部变量自动命名、少量 FLIRT 误标（如 `Ibsql::TIBXSQLVAR::LoadFromFile` 实为流式 `LoadFromFile`）。**足以支撑逻辑理解，不足以直接编译。**

### 3.2 数据格式：18 个编辑器 + 共享 codec（100% 往返能力）

`build_all.py` 的 `EDITORS` 表注册了 18 个编辑器，配合 `editor_utils/` 的纯数据 codec，构成了对游戏数据层的**完全掌握**：

| 编辑器 | 目标格式 | 结构掌握度（证据）|
|--------|----------|------|
| item_editor | TKItem.dat（600×64B） | 字段级语义 + 反编译验证 `sub_41E40C/42234C/422BBC`（见 `item_editor_v2.py` 头注）|
| warpc_editor | WarPC.dat（143×1054B=527 int16） | 五大 Tab 字段分区 + 成长率 + 技能→TKKon 映射 |
| skill_editor | TKSkill.dat（350×94B） | 字段 + 技能大类 ID 段 |
| kon_editor | TKKon.dat（650×40B=20 int16） | 20 字段战斗指令语义（`kon_editor_v2.py` KON_FIELDS）|
| act_editor | TKAct.dat（650×784B） | 方向表/8图层/音效触发表 + 混合模式（`sub_4434BC` 逐段核验）|
| wardata_editor | WarData.dat(219×498B) / WarWay.dat(100×1024B) | 逐字段偏移 + War.dll 官方编辑器双重验证 |
| mat_editor | TKMat.Dat（6000×384B） | 世界实体表字段（`TKS_地图数据驱动机制分析.md`）|
| tkt_editor | TKT.dat（XOR 0xFF + 控制标签） | 完整含控制标签解析（`tkt_loader.py`）|
| jvg/grp/gxp/spritesheet | @JVG/@JVM、GRP+IDX、GXP | 头结构 + 调色板 + RLE/LZSS + RGB565（`jvg_data.py`/`grp_codec.py`/`rgb565.py`）|
| save_editor | 存档（3 段 LZSS） | 分块字段映射（移植报告 §4.3）|
| shop/configs/font | TKShop.dat / 配置 / 点阵字体 | — |

**压缩/加密算法已完全逆向**（`editor_utils/lzss.py`，注明逆向自 `sub_452B14/sub_4530A8`）：
- LZSS 三变体（DAT 12B 头 / Save 4B 头 / Stream 无头），核心参数 `窗口4096 / 填充0x20 / 起始4078 / 匹配3~18`，**编解码无损往返**。
- TKD/TKT 文本 `XOR 0xFF`（`~*i`）。

### 3.3 已有的机制分析文档（关键算法已成文）

- **地图/事件数据驱动**：`TKS_地图数据驱动机制分析.md` —— 实体表 96-DWORD 字段布局、`type` 分发（5/10/15/16/20/110/200）、`SetNowDef` 三级 DEFINE 索引、BGM 查表、Flag/Var/Switch 全局区。
- **SCE 脚本 VM**：`TKS手机版移植可行性分析报告.md` §4.1 —— 62+ opcode 精确语义、协程逐帧模型、字节码格式。
- **战斗数值**：伤害递减公式 `atk²/(atk+3·def)`、命中率、30+ 技能特效 case、AI 行动价值评估。
- **成长率**：`10. TKS_AI分析成长率.md` —— 精确到 `a1[7]+=a1[7]/v+1`、`exp=8·Lv²+92`、仅 7 属性参与缩放、存档回写机制。
- **资源关系**：`游戏资源关系数据库.md`（1061 行）—— JVG 块↔角色映射、技能表、TKT ID 段。

---

## 4. 可行性分项评估

按"净室重写"所需，对各子系统给出**已知度**与**风险**（严格区分已核验 / 未知）：

| 子系统 | 数据/逻辑已知度 | 关键证据 | 风险与黑盒点 |
|--------|:---:|------|------|
| 全部数据文件读写 | ★★★★★ | 18 编辑器 + codec 往返 | 无实质风险（已生产可用）|
| LZSS/XOR 编解码 | ★★★★★ | `lzss.py` 无损往返 | 无 |
| 主循环 / 帧模型 | ★★★★☆ | `sub_412BE8` + TForm1 事件 | 60fps 定时器细节需实测校准 |
| SCE 脚本 VM | ★★★★☆ | `sub_40EBD4` 62+ opcode 成文 | 少数 opcode（16/26/55 等）语义偏推定 |
| 实体调度 / 场景切换 | ★★★★☆ | `sub_409618/40C044` 已逐行 | `sub_405CBC` 活跃表重建按上下文推定 |
| 对话/文本渲染 | ★★★★☆ | `sub_40A220` 双缓冲 + TKT 控制标签 | 点阵排版细节需比对 |
| 战斗数值公式 | ★★★☆☆ | `sub_4458B0` 838 行 + 成长率成文 | 30+ 特效仍有部分 case 未逐一定性 |
| 战斗状态机 / AI | ★★★☆☆ | `sub_447DAC/43E980` | **`sub_4400DC`（>3000 指令）未反编译**，是最大黑盒 |
| 技能动画 8 层管线 | ★★★★☆ | `sub_4434BC` + TKAct 绑定修正文档 | Aa/Af.jvg 混合模式已定性 |
| 7 种小游戏 | ★★★☆☆ | 各自调度函数已定位 | 规则细节需逐个反编译确认 |
| DirectDraw 调色板/透明 | ★★★☆☆ | 导入表 + 渲染函数 | 色键/调色板实现细节需实测 |
| 63 个汇编回退函数 | ★★☆☆☆ | `disassembly/*.asm` | 需读汇编或运行时 trace |

**总体**：数据层与"数据驱动型玩法"（地图/事件/对话/物品/成长）已达可直接重建水平；**唯一实质工程风险集中在战斗核心** `sub_4400DC` 与部分战斗特效分支。

---

## 5. 推荐重建路线：以原框架 (C++Builder 6 VCL) 净室重写

用户要求"按游戏原本使用的开发框架和技术"。以下方案严格遵循此约束，同时诚实说明其代价。

### 5.1 目标技术栈（与原版一致）

- **IDE/编译器**：Embarcadero RAD Studio（C++Builder，向后兼容 BCB6 的 VCL；或原版 C++Builder 6）。
- **UI**：VCL，主窗体 `TForm1`（`Unit1`），游戏线程 `TThread` 派生（对应 `Tkgmthread`）。
- **渲染**：DirectDraw7（`IDirectDraw7`/`IDirectDrawSurface7`），保留 640×480 + RGB565 + GDI 回退。
- **音频**：DirectSound（WAV 音效）+ MP3 BGM 播放器包装。
- **视频**：DirectShow（COM）播放片头 AVI。

### 5.2 原框架 vs 现代引擎（诚实权衡）

| 维度 | 原框架重写 (C++Builder VCL + DDraw) | 现代引擎重写 (如 Godot，见移植报告) |
|------|------|------|
| 行为保真度 | 最高（可与原版逐像素/逐帧对照）| 高（需重映射）|
| 与反编译对照难度 | 最低（结构同构，`sub_XXXX`↔函数一一对应）| 中（要跨范式翻译）|
| 现代可移植性（移动端/高分屏）| **差**（DDraw7 已被废弃，Win-only）| 优（一键导出多平台）|
| 长期可维护性 | 中（VCL 生态老化）| 优 |
| 适用目标 | **考古级忠实复刻 / 逆向验证 / PC 原生 MOD** | 跨平台重制/商业化 |

> 建议：**若目标是"最忠实地反推并验证原源码逻辑"，选原框架**——它与反编译资料同构，能把每个 `sub_XXXXXX` 直接落到一个 C++ 方法，验证成本最低。若目标是跨平台/商业化，则 `TKS手机版移植可行性分析报告.md` 已论证 Godot 更优。二者可并行：**先用原框架做"黄金参考实现"，再据其行为移植到现代引擎。**

### 5.3 架构映射（反编译 → C++Builder 工程）

| 原始产物 | 重建单元（建议）|
|----------|------|
| `Unit1` / `TForm1` + 事件处理器 | `MainForm.cpp/.h/.dfm`（`FormCreate/KeyDown/MouseDown/Paint` 直接对应）|
| `Tkgmthread` | `GameThread.cpp/.h`（`TThread::Execute` = 主循环 `sub_412BE8`）|
| `sub_40EBD4` VM | `SceScriptVM.cpp`（opcode 分发表）|
| `sub_409618` 实体调度 | `EntityScheduler.cpp` |
| `sub_447DAC/4458B0/43E980/4434BC` | `Battle*.cpp`（状态机/伤害/AI/动画）|
| `sub_4CB590` 场景渲染 | `SceneRenderer.cpp`（DDraw 表面）|
| `editor_utils` 的 codec | 直接移植为 C++ 加载器（Python→C++ 一对一翻译）|

---

## 6. 详细开发步骤（分阶段，每阶段带验收口径）

> 原则：**先立"数据地基"，再立"可运行骨架"，最后攻"战斗核心"**。每一步都用现有编辑器/反编译作为"真值参照"做对照测试。

### 阶段 0：环境与真值基线（1 周）
1. 安装 C++Builder（RAD Studio），建立空 VCL 工程：`TForm1` + `TThread` 骨架。
2. 准备正版数据文件（`.dat/.grp/.jvg/.gxp/.mp3`）与现有 18 编辑器作为**真值发生器**。
3. 建立"对照测试"框架：任何 C++ 加载器的输出，必须与对应 Python 编辑器/codec 的输出**逐字节一致**。

### 阶段 1：数据层移植（3–4 周）—— 把 `editor_utils` 翻成 C++
1. `LZSS`（三变体）+ `XOR 0xFF`：直译 `lzss.py`，用编辑器导出的样本做无损往返测试。
2. `RGB565` LUT、`JVG(@JVG/@JVM)`、`GRP+IDX`、`GXP` 加载器：对照 `jvg_data.py/grp_codec.py`。
3. 结构体加载器：`TKItem/TKSkill/TKKon/TKAct/WarPC/WarData/WarWay/TKMat/TKT` —— 字段偏移直接抄编辑器常量表（`WARPC_REC=1054`、`KON_REC=40`、`SKILL_REC=94`…）。
4. **验收**：C++ 侧读入全部数据文件，转储为 JSON，与编辑器导出的 JSON diff 为空。

### 阶段 2：渲染与输入骨架（3–4 周）
1. DirectDraw7 初始化：640×480 主表面 + 后备缓冲；RGB565；GDI 回退路径。
2. 精灵绘制：实现 JVG 帧 blit + 色键透明（对照 `sub_458020` 语义）。
3. GXP 全屏背景绘制；TForm1 输入事件接线（键盘/鼠标，对照 `_TForm1_FormKeyDown` 等）。
4. **验收**：能显示 `TitleMenu.gxp` 标题、渲染任意 JVG 角色帧、响应方向键。

### 阶段 3：地图/实体/脚本 VM（6–8 周）—— 数据驱动核心
1. 装载 `TKMat.dat` 到实体表；实现 `ChangeScene`（`sub_40C044`）：BGM 查表 + 脚本段切换 + 活跃表重建。
2. 实现实体调度器（`sub_409618`）：`type` 分发（10 传送 / 15 可调查 / 16 门 / 200 NPC）。
3. 实现 SCE VM（`sub_40EBD4`）：62+ opcode 逐条落地为函数；三级 DEFINE 索引 + `SetNowDef`；协程逐帧（PC 保存/恢复）。
4. 对话双缓冲（`sub_40A220`：TalkA 24 槽 / TalkB 16 槽）+ TKT 控制标签渲染。
5. **验收**：可在场景间传送、触发 NPC 对话、开宝箱得物品、Flag 正确记录（用原版存档/剧情节点比对）。

### 阶段 4：战斗系统（9–15 周）—— 最大难点
1. 等距 32×32 战斗网格 + A* 寻路（`WarWay.dat`）。
2. 战斗状态机（`sub_447DAC`，20+ 状态）。
3. 伤害公式（`sub_4458B0`：递减公式 + 命中率 + 30+ 特效 case，逐 case 与反编译核对）。
4. 成长/等级缩放（`sub_410674/4302D8`：7 属性 `+=x/v+1`，`exp=8Lv²+92`）——**已精确成文，可直接实现**。
5. AI 决策（`sub_43E980` 行动价值评估）。
6. 技能动画 8 层（`sub_4434BC`：`layer_type==1→Aa.jvg`，否则 `Af.jvg`；mode 2/3/4 混合）。
7. **攻坚 `sub_4400DC`**：先读 `disassembly/4400DC.asm`，辅以对原版下内存断点做运行时 trace，以输入/输出反推行为。
8. **验收**：完整跑通一场战斗（遇敌→指令→移动→技能→结算→经验回写），数值与原版一致。

### 阶段 5：小游戏 + 存档（5–8 周）
1. 7 种小游戏逐个反编译确认规则后实现。
2. 存档系统：可选保留原 3 段 LZSS 二进制（最忠实），或旁路为 JSON（易调试）。字段映射见移植报告 §4.3。
3. **验收**：小游戏可玩通；存档/读档场景与角色状态正确还原。

### 阶段 6：对照验证与收尾（持续）
1. 建立"回归对照"：关键路径（伤害、成长、掉落、剧情 Flag）与原版结果自动 diff。
2. 补齐 63 个汇编回退函数中被实际调用到的部分。

---

## 7. 风险与注意事项

### 7.1 技术风险
- **`sub_4400DC`（>3000 指令，战斗核心）未反编译**：这是全项目最高风险点，需汇编级分析 + 运行时验证，务必在阶段 4 预留缓冲。
- **63 个汇编回退函数**：多为 VCL 底层/复杂状态机，按被调用频率择要攻关。
- **部分 SCE opcode 与战斗特效 case 语义为"推定"**：实现时必须以原版实机行为对照校准，不可直接采信推定值。
- **DirectDraw7 已过时**：现代 Windows 上 DDraw 走兼容层，色键/调色板行为可能与原版有细微差异，需实测。

### 7.2 法律 / 版权（重要）
- 必须走**净室逆向**：只用反编译资料**理解逻辑**，用新代码重写，**不得直接复制**原始二进制或反编译文本作为发行代码。
- **游戏数据文件**（`.dat/.jvg/.gxp/.grp/.mp3` 及其中的剧情文本、美术、音乐）版权属于原发行方。重建工程应设计为**"由用户自备原版数据文件"**模式，不随源码分发这些资产。
- 三国题材本身不涉版权，但**具体角色设计/剧情文本/美术**属原权利方。

### 7.3 预期管理
- 这是一次**"理解并等价重写"**，不是"恢复原工程"。交付物是一份新的、行为对齐的 C++Builder 源码，而非原作者的 `.bpr/.cpp/.dfm`。
- 工程量参考移植报告估算：单人全职约 **12–24 个月**量级（原框架路线因与反编译同构，逻辑翻译部分会更快，但 DDraw/VCL 手写渲染与输入会抵消一部分优势）。

---

## 8. 附录：关键证据索引

### 8.1 技术栈判定证据（`反编译产物/`）
- `exports.txt`：`_Form1`、`@@Unit1@Initialize`、`@@Tkgmthread@Initialize`、`___CPPdebugHook`
- `strings.txt`：0x4e6000 `Borland C++ - Copyright 2002`；0x404ab0 `System::DelphiInterface<>`；0x477a94 `TApplication`；0x4ab0e0 `SOFTWARE\Borland\Delphi\RTL`；`_STL::*`
- `imports.txt`：`DirectDrawCreate`、`DirectSoundCreate`、GDI 成套、`CoCreateInstance`
- `function_index.txt`：`_TForm1_Form*` 全套事件；`4030F0.c` = `TForm1_FormCreate`
- 资源文件名字符串：`TKT.dat/TKMat.Dat/SC.grp/WSC.grp/ssf.grp/TitleMenu.gxp/TKObj.dat/TKDefUnit.dat/Logo*.avi`

### 8.2 已有分析文档（`逆向工作区/`）
- `TKS游戏核心逻辑调用关系分析.md`（主调用链、战斗/场景函数、数据结构基址）
- `TKS_地图数据驱动机制分析.md`（实体表字段、opcode、BGM/Flag/Var）
- `TKS手机版移植可行性分析报告.md`（SCE VM opcode 表、伤害公式、存档结构、子系统难度）
- `10. TKS_AI分析成长率.md`（成长/等级缩放/经验公式）
- `TKS_AI修正TKAct.dat实际JVG绑定.md`（TKAct 图层→Aa/Af.jvg）
- `游戏资源关系数据库.md`（JVG↔角色映射、技能/文本 ID 段）
- `TKS.exe逆向分析报告.md`（外层 Armadillo 壳分析——注意区分内/外层）

### 8.3 数据层实现（``）
- `build/build_all.py`：18 编辑器注册表（`EDITORS`）
- `editor_utils/lzss.py`（LZSS 三变体）、`rgb565.py`、`jvg_data.py`、`grp_codec.py`、`tkt_loader.py`、`kon_name_resolver.py`、`mod_exporter.py`
- 各编辑器结构常量：`item_editor_v2.py`、`warpc_editor_v2.py`、`kon_editor_v2.py`、`act_editor_v2.py`、`wardata_editor_v2.py`、`skill_editor_v2.py`

---

## 9. 最终判断

1. **"反推出原作者的原始源码工程"——不可能**：注释、标识符名、`.dfm` 设计、单元划分在编译时已永久丢失。
2. **"反推出原始技术栈并据此在原框架下净室等价重写"——可行，且资产条件优越**：
   - 原框架已 100% 确认为 **Borland C++Builder 6 + VCL + DirectDraw7 + DirectSound**；
   - 数据层已由 18 个编辑器 + `editor_utils` codec **完全解决（无损往返）**；
   - 逻辑层 98.7% 反编译可读，且核心机制（主循环、脚本 VM、地图数据驱动、成长/伤害公式）**已成文**；
   - 唯一实质黑盒是战斗核心 `sub_4400DC`（>3000 指令）及少量战斗特效分支，需汇编级 + 运行时 trace 攻关。
3. **推荐**：以 C++Builder 6 VCL 建立"黄金参考实现"（与反编译同构、验证成本最低）；如需跨平台，再据其行为移植到现代引擎（Godot，见移植报告）。开发按 §6 六阶段推进，每阶段以现有编辑器/原版实机行为为真值做对照验证。
