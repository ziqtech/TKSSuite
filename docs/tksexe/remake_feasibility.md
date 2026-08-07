# TKS.exe 真实代码重制可行性评估与工程路线

> 本文基于当前 `docs/tksexe` 的 40+ 份验证文档、`仓库根目录` 下 19 个编辑器及其数据层、`反编译产物` 的反编译资料，以及 `tks_reverse` 已生成的功能模块代码，评估“把 TKS.exe 从逆向工程恢复成真实代码并重制”的可行性。

## 1. 结论摘要

**“恢复原作者的原始源码工程”不可能**：注释、局部变量名、原始单元划分、`.dfm` 设计器布局等信息在编译时已经永久丢失。

**“重建一份可编译、可运行、与原版行为对齐的真实代码”可行，而且当前资产已经让难度从“未知”降到“工作量问题”**。真正的工作不是继续猜格式，而是把 Hex-Rays 伪 C 改写成可编译的 C/C++ 工程，并补齐类型、全局变量、渲染、输入、音频和 UI。

**重制范围明确限定为“只替换 TKS.exe”**：原游戏的 `.dat/.JVG/.GRP/.GXP/.mp3/.avi` 等资源全部原样使用，不需要重定义格式、不需要转换、不需要重新打包。重写后的 TKS.exe 直接读取原游戏目录中的这些文件。

当前 `tks_reverse/remake/` 已经存在 11 个“功能模块”C 文件，但它们不是可编译源码，而是反编译代码的提取/归档：

- 包含 165 个唯一函数，但实际出现 206 个函数标签，其中 33 个函数跨模块重复。
- 没有头文件、没有全局变量声明、没有 VCL/RTL 类型定义、没有构建系统。
- 大量代码仍使用 `sub_XXXXXX`、`v1/v2/j/k`、`_DWORD`、`BYREF`、`__fastcall` 等伪 C 表达。
- 战斗核心 `sub_4400DC` 仍是汇编 fallback，未还原成 C。

所以当前 `remake/` 的定位应是“供人工翻译的素材”，不是“离编译只差一步的源码”。

## 2. 现有资产盘点

### 2.1 `docs/tksexe`：逻辑真值表

已完成三批验证：

- 编辑器源码与真实文件加载结果验证：`editor_source_verification.md`
- 反编译/反汇编运行时行为验证：`decompile_runtime_verification.md`
- 未验证缺口清单：`verification_gaps.md`

已闭环的核心逻辑包括：

| 子系统 | 已确认程度 |
| --- | --- |
| 数据文件格式与容量 | 19 个编辑器 + 实际文件加载，全部通过 |
| LZSS / XOR / JVG / GRP / GXP / FONT9696 | 有可复用 Python codec 和双向测试 |
| 脚本命令 0-82 | `40EBD4.c` 逐 case 复核 |
| 实体类型与调度 | `409618.c`、`405CBC.c` 复核 |
| 战斗菜单状态机 | `447DAC.c` 复核 |
| 战斗 AI 与公式 | `4359A4/43E980/4458B0` 复核 |
| 战后奖励 | `43B7FC/43BF20` 复核 |
| 7 种小游戏调度 | `40E97C` 及 7 个主函数复核 |
| 文本格式化 | `409C60.c` 复核 |
| Alpha 混合 | `454D24/454D90/4553A4` 复核 |

这些文档的价值在于：重写时可以直接作为“需求规格”，不需要每个函数都重新读一遍反编译。

### 2.2 编辑器与 `editor_utils`：数据层实现

`仓库根目录` 的 19 个编辑器已经提供了可工作的数据加载、保存、预览和 MOD 打包能力：

- `editor_utils/lzss.py`：DAT/Save/Stream 三种 LZSS 变体。
- `editor_utils/jvg_loader.py`、`grp_codec.py`、`rgb565.py`：JVG/GRP/RGB565 解码。
- `warpc_editor/warpc_schema.py`：WarPC 527 字段结构。
- `save_editor/save_editor_v2.py`：存档三段布局。
- `tkt_editor`、`tks_book`：TKT 文本和控制标签。
- `tks_launcher_gui`：运行时补丁、WarPC 扩容、MOD 合并。

这些 Python 实现是重制工程最好的“oracle”：C++ 加载器对原游戏资源做**只读解析**时，读出的结果应与它们逐字节一致。重制 TKS.exe 只需要复用其中的加载/解析逻辑；保存、预览、MOD 打包、写回等编辑器功能不是重制目标。

### 2.3 `tks_reverse`：伪 C 素材库

`tks_reverse/raw/` 有 48 个按 SCC/调用链聚合的文件；`tks_reverse/remake/` 有 11 个按功能模块聚合的文件。它们由 `chain_decomp.py`、`merge_decompile.py`、`extract_remake.py` 自动生成，适合浏览，不适合直接编译。

用于重制时，可以从这些文件中：

- 提取每个 `sub_XXXXXX` 的伪 C 原文。
- 按 `function_index.txt` 恢复调用关系和依赖层级。
- 按 `pointers.txt` / `memory/` 恢复全局变量名、地址和大小。
- 按 `docs/tksexe` 的字段表把 `v4[5]` 等魔法索引替换成具名结构体字段。

### 2.4 `反编译产物`：游戏逆向工程原码

这是当前最接近“源码”的资产。它不是可编译源码，但它是从内存 dump 中导出的完整反编译工程，足以作为真实代码重建的主要输入。

| 文件/目录 | 内容 | 对重制的用途 |
| --- | --- | --- |
| `decompile/*.c` | 2033 个 Hex-Rays 伪 C 文件 | 每个 `sub_XXXXXX` 的伪 C 原文，是“真实代码”的主要翻译源 |
| `function_index.txt` | 2040 个已导出函数的地址、调用者、被调者、文件映射 | 生成调用图、模块拆分、函数清单 |
| `disassembly/*.asm` | 7 个反汇编 fallback 文件 | `sub_4400DC` 战斗核心等未生成 C 的函数，需要人工/工具还原 |
| `memory/*.txt` | 17 个格式化内存 dump，覆盖 `0x401000-0xA7D000` | 恢复全局变量初值、数据区布局、只读表 |
| `pointers.txt` | 31122 个指针记录，含 30074 个数据 xref、2697 个 raw pointer | 生成全局符号表和指针引用关系 |
| `strings.txt` | 1590 条字符串 | 定位资源路径、错误文本、VCL/RTTI 类型名 |
| `imports.txt` | 386 个导入函数 | 确定 DirectDraw/DirectSound/COM/GDI 等系统依赖 |
| `exports.txt` | 8 个导出符号 | 识别 `Unit1`、`Tkgmthread`、VCL 启动入口 |
| `decompile_skipped.txt` | 3134 个被标记为 library 的函数 | 区分“需要重写的游戏逻辑”和“可直接依赖/省略的 VCL/RTL 代码” |
| `disassembly_fallback.txt` | 7 个 fallback 地址及原因 | 标出黑盒函数清单 |
| `.export_progress` | 8315 条导出状态记录 | 了解导出覆盖范围；当前 `function_index.txt` 是有索引的 2040 个函数 |

7 个 disassembly fallback 函数：

| 地址 | 说明 |
| --- | --- |
| `sub_4400DC` | 战斗核心，指令数超过 3000 |
| `sub_469D84` | 反编译返回 None |
| `sub_49216C` | 反编译返回 None |
| `sub_49E358` | 反编译返回 None |
| `sub_4A6D58` | 反编译返回 None |
| `sub_4A70E4` | 反编译返回 None |
| `sub_4E4D20` | 反编译返回 None |

此外，`逆向工作区/` 目录里还有原始 `TKS.exe`、`TKS.exe.id2`、`TKS.exe.til` 以及全部游戏数据文件。`TKS.exe` 本身可用于行为对照、运行时 trace 和回归测试；`.id2/.til` 是 IDA 辅助数据，可用于重新分析。

### 2.5 现有移植尝试

`逆向工作区/godot_loader/` 只有 `BGMTable.gd`、`SceneManager.gd`、`TeleportArea.gd`、`TKMatLoader.gd`、`WorldEntityDB.gd`，属于早期原型，不足以直接运行完整游戏。它证明“用现有文档快速搭数据加载层”可行，但离完整 TKS 重制仍远。

## 3. 三条重制路线

| 路线 | 优点 | 缺点 | 适合目标 |
| --- | --- | --- | --- |
| A. 原框架：C++Builder/VCL + DirectDraw | 与反编译结构同构，验证最直接 | 工具链老、DDraw 已废弃、现代 Windows 兼容麻烦 | “考古级忠实复刻 TKS.exe” |
| B. C/C++ + CMake + SDL2/OpenGL | 可编译、可维护、产出新的 TKS.exe，直接加载原游戏资源 | 需要自己实现 VCL 表单和 DirectDraw 对应逻辑 | 推荐：只重写 TKS.exe |
| C. Godot | 跨平台、开发效率高 | 需要跨范式移植，行为保真需额外验证 | 商业/手机版重制 |

如果目标是“重制 TKS.exe 本身”，最稳妥的是路线 B：先做可编译的 C++ 核心，再根据需求选择是否套 VCL 原框架或 Godot。

## 4. “恢复真实代码”的具体路径

以 `反编译产物` 为输入时，重建流程可以这样对应：

```text
decompile/*.c          -> recovered/src/game/*.cpp      逐函数翻译为可编译 C++
function_index.txt     -> recovered/build/function_map  生成调用图、模块归属
pointers.txt+memory/   -> recovered/src/game/globals.h   生成全局变量/数据区声明
strings.txt            -> recovered/src/game/strings.h   资源路径和错误文本
imports.txt/exports.txt-> recovered/src/platform/        系统 API 和 VCL 入口映射
disassembly/*.asm      -> recovered/src/game/hard/*.asm  黑盒函数人工还原
```

翻译时，优先选择已经在 `docs/tksexe` 中被验证过的函数；尚未验证的函数用 `function_index.txt` 找出调用者，再结合 `pointers.txt` 和编辑器结构体推断语义。

整个重建过程只产出“新的 TKS.exe 及必需的系统 DLL/运行库”，游戏目录中的 `.dat/.JVG/.GRP/.GXP/.mp3/.avi` 保持原样。任何阶段都不需要把资源转换成中间格式再交给重制版。

### 阶段 0：建立 recovered 源码工程

建议新建 `remake/` 或 `tks_reverse/recovered/`：

- 用 CMake + C++20 建一个最小可编译工程。
- 先写只读解析器，不写渲染：直接加载原游戏目录中的 `.dat/.JVG/.GRP/.GXP`，在内存中重建与原版一致的数据结构，并与 Python 编辑器输出 diff。
- 生成统一的 `TksTypes.h`：把 WarPC/TKItem/TKSkill/TKKon/TKAct/TKMat/WarData/WarWay/TKT 等结构体按编辑器常量定义。

验收标准：`C++ 只读加载原资源 -> 内存结构` 与 `Python 编辑器解析原资源 -> 内存结构` 一致；不修改任何资源文件。

### 阶段 1：脚本 VM 与实体调度

- 把 `sub_40EBD4` 的 0-82 命令翻译成 C++ `SceScriptVM`。
- 把 `sub_409618` 的 type 5/10/15/16/20/110/200 调度翻译成 `EntityScheduler`。
- 实现 `sub_40C044` 场景切换、`sub_402E88` 脚本段加载、`sub_4066F0` DefUnit 链推进。

验收标准：原版 TKD 脚本可以在重建的 VM 中执行，Flag/Var/Switch 状态变化与原版一致。

### 阶段 2：战斗系统

- 战斗菜单 `sub_447DAC`：状态机、移动、目标选择、技能/道具执行。
- 战斗结算 `sub_43B7FC/43BF20`：经验、JP、金钱、掉落、回写。
- 伤害公式 `sub_43E980` 和技能分发 `sub_4458B0`。
- `sub_4400DC`：目前只有汇编，需要逐段阅读 `disassembly/4400DC.asm` 或运行时 trace，再手写 C++。

验收标准：能打完整一场战斗，战前战后 WarPC 变化与原版一致。

### 阶段 3：渲染、音频、UI 与小游戏

- JVG/GRP/GXP/FONT9696 的 C++ 渲染器可以从现有 Python codec 直译。
- DirectSound/MP3/AVI 可以先用 SDL_mixer/SDL 替代。
- 7 种小游戏按 `minigame_reverse_analysis.md` 实现。
- UI 可以先做与原版功能等价的新界面，再逐步对齐。

### 阶段 4：对照验证

- 建立回归测试：数据文件往返、脚本状态、战斗数值、掉落概率、存档读写。
- 可以用原版 TKS.exe 在 Wine/兼容环境下录制关键路径输出，与重建版 diff。

## 5. 可以自动加速的部分

现有资料已经足以让“大部分重写”机械化：

- 数据层结构体可由编辑器常量表直接生成。
- 全局变量可由 `pointers.txt` / `memory/` 生成声明骨架。
- 伪 C 函数可由 `remake/` 提取，再半自动改名。
- 调用关系可由 `function_index.txt` 生成。
- Python codec 可一对一翻译成 C++。
- 系统依赖可由 `imports.txt` 生成平台 API 映射，`exports.txt` 可定位 VCL 启动入口。
- `disassembly_fallback.txt` 可直接给出需要人工攻坚的 7 个黑盒函数清单。
- 原游戏资源不需要迁移或重新定义；C++ 只读加载器可以直接复用现有 codec 的逻辑。

最花时间、最不能自动化的部分是：

- 把伪 C 的魔法索引替换成语义字段。
- 把 VCL 事件和 DirectDraw 调用翻译成现代实现。
- 阅读 `sub_4400DC.asm` 并还原战斗核心。
- 小游戏中的鼠标交互和动画节奏。

## 6. 关键风险

1. 这不是“恢复原源码”，而是“等价重写”；不要期待得到原作者注释和命名。
2. `remake/*.c` 是反编译提取物，直接编译会因重复定义、缺少类型和全局声明而失败。
3. `sub_4400DC` 和 7 个 disassembly fallback 函数仍需人工/运行时验证。
4. DirectDraw、旧音频 API、VCL 布局在现代环境有兼容性风险。
5. 原版数据文件（剧情、美术、音乐）有版权，工程应设计为“用户自备原版数据文件”，不要随源码分发。
6. 重制范围必须保持在“只读加载原资源 + 重写 TKS.exe”；一旦加入数据转换、资源打包或新格式保存，就会把范围扩大到编辑器/转换器。

## 7. 建议下一步

建议先做“最小可编译核心”，验证“真实代码重制”这条路是否走得通：

1. 新建 C++/CMake 工程。
2. 移植 `editor_utils/lzss.py`、TKT 加载、JVG/GRP/GXP 解码。
3. 定义 `WarPC/TKItem/TKSkill/TKKon/TKAct/TKMat/WarData/WarWay` 结构体。
4. 用 Python 编辑器作为 oracle，对原资源做只读解析对照测试，不写回、不转换。
5. 如果数据层稳定，再进入脚本 VM、场景调度、战斗系统。

这一步完成后，就能从“逆向资料是否足以重制”的评估，进入“实际能编译、能运行”的工程阶段。
