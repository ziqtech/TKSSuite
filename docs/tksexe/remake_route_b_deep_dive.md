# 方案 B 深入分析：C/C++ + CMake + SDL2/OpenGL 重制 TKS.exe

> 关联：[remake_feasibility.md](remake_feasibility.md)、[TKS_analysis.md](TKS_analysis.md)、[decompile_runtime_verification.md](decompile_runtime_verification.md)、[verification_gaps.md](verification_gaps.md)

## 1. 结论

方案 B 是当前资料条件下最稳的“重制 TKS.exe”路线，但必须把目标定义为“行为等价重写”，而不是“恢复原作者源码”。现有反编译、编辑器源码和验证文档已经足够把 B 从“能否做”推进到“按什么顺序做”。

推荐做法：

- 核心逻辑与平台后端分离，`core` 不依赖 SDL2/Win32；SDL2 只做窗口、输入、音频、纹理输出。
- 第一阶段不直接上 OpenGL。先用 SDL2 窗口加 640x480 软件合成帧缓冲，逐帧上传 `SDL_Texture`；OpenGL 作为后续可选后端。
- WAV/MP3 用 SDL_mixer，AVI 用一个 `AvPlayer` 门面隔离，可先接 Windows DirectShow，之后再换 FFmpeg。
- 最小里程碑不是“能打开窗口”，而是“C++ 能只读加载原游戏资源并与 Python 编辑器逐字节一致”。

## 2. 为什么 B 可行

### 2.1 真正需要迁移的游戏面不大

`imports.txt` 共 386 个导入函数，其中：

| 类别 | 数量 | 在 B 中的处置 |
| --- | --- | --- |
| DirectDraw | 1 | 全部由 SDL2 窗口/纹理/帧缓冲替代 |
| DirectSound | 1 | 由 SDL_mixer 替代 |
| DirectShow/COM | 3 个入口 | 保留在 AVI 门面内，后续可换 FFmpeg |
| User32 | 约 140 | 主要是 VCL 窗口/消息/控件，B 中大部分消失 |
| GDI | 约 54 | 主要是 VCL 画布和 DIB，B 中大部分消失 |
| ImageList | 22 | VCL 控件用，B 中直接删除 |
| Kernel32 | 较多 | 用 C++ 标准库和少量 Win32 保留 |

因此 B 的真实难点不是“替换 API”，而是“把 2040 个反编译函数中真正属于游戏逻辑的部分整理出来”。3134 个 `decompile_skipped` 函数大多是 VCL/RTL、STL、WinHelp、ImageList、OLE 自动化等，不需要进入重制范围。

### 2.2 已验证文档可以直接当规格

下面这些模块已经有高置信度描述，B 可以把它们当成需求规格：

| 子系统 | 文档 | 迁移目标 |
| --- | --- | --- |
| 脚本命令 0-82 | `script_command_mapping.md`、`script_engine_SCE.md` | `SceVM` |
| 实体/地图/事件 | `entity_map_event_system.md` | `EntityScheduler`、`SceneManager` |
| 战斗菜单/AI/公式/技能 | `battle_menu_state_machine.md`、`AI_decision_analysis.md`、`sub_43E980_formula_analysis.md`、`sub_4458B0_skill_case_index.md` | `BattleEngine` |
| 战斗核心 | `sub_4400DC_battle_core_analysis.md` | `BattleActionExecutor`，仍需手写 |
| 存档 | `save_system_runtime.md`、`save_block_ab_fields.md` | `SaveFormat` |
| 文本/字体 | `text_data_encoding.md`、`font_text_rendering.md`、`text_formatting_engine.md` | `TextEngine`、`Font9696` |
| 资源格式 | `resource_formats.md`、`scene_grp_mapping.md`、`wsc_grp_mapping.md` | `GrpCodec`、`JvgCodec`、`GxpCodec` |
| Alpha/光照 | `alpha_blend_formula.md` | `RenderBackend` 内的精确合成器 |
| 小游戏 | `minigame_reverse_analysis.md` | `MiniGameEngine` |

### 2.3 Python 编辑器是最便宜的 oracle

19 个编辑器已经实现并验证了数据层，它们应继续保留，作为 C++ 重制的对照基准：

- `editor_utils/lzss.py`：DAT/Save/Stream 三种 LZSS 变体。
- `editor_utils/grp_codec.py`：GRP Frame A/B 解码、图层差分。
- `editor_utils/jvg_loader.py`：JVG `@JVM` 块和 RLE 精灵解码。
- `editor_utils/rgb565.py`：RGB565 与 RGBA 转换。
- `warpc_editor/warpc_schema.py` 等：字段级结构定义。
- `tkt_editor`、`tks_book`：TKT/TKD 文本和编码。

C++ 数据层可以先提供 `dump_assets` 命令行工具，输出文件数量、记录数、字段哈希、解码像素哈希，再与 Python 编辑器输出 diff。这样不会让 C++ 层带着自己的“第二套理解”一路写到战斗。

## 3. SDL2 与 OpenGL 怎么选

### 3.1 第一版推荐：SDL2 + 软件合成

原版是 640x480 的 DirectDraw 2D 表面：

- 主画面固定 640x480。
- 大部分图像是 RGB565/15bpp 或 JVG 调色板精灵。
- Alpha 混合是自定义 32 级 LUT 查表相加，不是标准 `src * a + dst * (1-a)`。
- 还有光照 LUT、淡入淡出、天气等效果。

因此第一版最适合的结构是：

```text
JVG/GRP/GXP/FONT9696 解码
  -> 软件合成到 640x480 帧缓冲
  -> SDL_CreateTexture(... STREAMING)
  -> SDL_UpdateTexture + SDL_RenderCopy
```

优点：

- 不需要一开始维护复杂的 GPU 状态。
- 可以逐函数复刻原版 `sub_454D24` 等混合公式，而不是被 `SDL_BLENDMODE_BLEND` 的近似行为带偏。
- 调试像素、截图 diff、单帧回放都容易。
- 640x480 性能完全足够，约 16.6 帧/秒的节拍，软件合成压力很小。

### 3.2 OpenGL 放第二阶段

OpenGL 只在以下场景再引入：

- 整数倍缩放、双线性/CRT/扫描线等显示滤镜。
- 需要把大量图块一次提交给 GPU 时。
- 想做跨平台现代渲染后端时。

OpenGL 后端应放在 `IRenderBackend` 之后：

```text
IRenderBackend
  - SoftwareTextureBackend   // SDL2，默认
  - GlTextureBackend         // OpenGL 3.3+，可选
```

即使上 OpenGL，也不要直接写“每个精灵一个 GL call”的旧式立即模式。应把解码后的表面放入 `GL_RGB565`/`GL_RGBA8` 纹理，用 shader 做 RGB565 展开和 LUT 混合。

### 3.3 必须保留的像素细节

- RGB565 的 5-6-5 位深。
- JVG 调色板 5-6-5。
- `word_A39D30` 的 32 级 Alpha LUT。
- 16bpp 与 15bpp 两种掩码分支。
- FONT9696 的 1bpp RLE 字形。
- 淡入淡出使用 LUT 重建，不是简单的 alpha 插值。

任何渲染层都必须把这些细节作为回归测试，而不是“看起来差不多就行”。

## 4. 依赖与后端映射

| 原版 | B 方案 |
| --- | --- |
| `TForm1`、`Application.Run`、`TTimer` | SDL2 主窗口 + 固定步长主循环 |
| `TKGMThread` 主循环 | 单线程固定步长循环；音频线程由 SDL 管理 |
| DirectDraw 主表面/后备表面 | SDL_Window + SDL_Renderer + 软件帧缓冲 |
| `BitBlt`、`StretchBlt` | `SDL_UpdateTexture` + `SDL_RenderCopy` |
| DirectSound WAV | SDL_mixer `Mix_Chunk` |
| `PlayMp3` | SDL_mixer `Mix_Music` |
| DirectShow AVI | `AvPlayer` 门面：先 DirectShow，后 FFmpeg |
| GDI 字体/画布 | 游戏内 FONT9696，不依赖系统字体 |
| User32 消息循环 | SDL 事件循环 |
| IMM 中文输入 | `SDL_StartTextInput`；必要时保留 Win32 IME 适配 |
| ImageList | 删除，所有 UI 用 SDL/帧缓冲绘制 |
| OLE/SafeArray | 删除，游戏逻辑不依赖 |

### 4.1 AVI 的特殊性

`Logo1.avi`、`Logo2.avi`、`Title.avi`、`TKObj.dat` 是 DirectShow AVI。已确认：

- 视频流为 MPEG-4 Part 2，512x277。
- 音频流为 Microsoft ADPCM，双声道 44.1kHz。
- `TKObj.dat` 含 768 字节 `JUNQ` 对齐块，FFmpeg/Media Foundation 应能跳过。

建议：

- 第一阶段只做 `AvPlayer` 接口和“跳过播放”模式。
- 第二阶段接 DirectShow，因为 Windows 自带，代码量小。
- 若希望完全脱离老 API，再接入 FFmpeg 或 Windows Media Foundation。

## 5. 工程结构

建议新建 `TKSRemake/`，避免继续扩大 `tks_reverse/` 的伪 C 目录：

```text
TKSRemake/
  CMakeLists.txt
  cmake/
    deps.cmake
  src/
    main.cpp
    core/
      TksTypes.h
      GameState.h
      lzss.h/cpp
      fileio.h/cpp
      codecs/
        grp_codec.h/cpp
        jvg_codec.h/cpp
        gxp_codec.h/cpp
        font9696.h/cpp
      data/
        tkmat.h/cpp
        wardata.h/cpp
        warpc.h/cpp
        tkitem.h/cpp
        tkskill.h/cpp
        tkkon.h/cpp
        tkact.h/cpp
        tkt.h/cpp
      script/
        sce_vm.h/cpp
      scene/
        scene_manager.h/cpp
        entity_scheduler.h/cpp
      battle/
        battle_engine.h/cpp
        battle_menu.h/cpp
        battle_ai.h/cpp
        battle_action.h/cpp
      save/
        save_format.h/cpp
      ui/
        menu_state_machine.h/cpp
      render/
        framebuffer.h/cpp
        sprite_blitter.h/cpp
        lut_blend.h/cpp
    platform/
      sdl_app.h/cpp
      input.h/cpp
      audio.h/cpp
      av_player.h/cpp
      win_ime.h/cpp
    tools/
      dump_assets.cpp
      replay_trace.cpp
    tests/
      codec_golden_tests.cpp
      script_vm_tests.cpp
      save_roundtrip_tests.cpp
      battle_logic_tests.cpp
      render_pixel_tests.cpp
  golden/
    README.md
    lzss/...
    grp/...
    jvg/...
    save/...
```

### 5.1 关键设计原则

- `core` 禁止 include SDL2/Win32；只有 `platform/` 可以。
- `GameState` 保存所有运行时数据，不依赖进程全局变量，方便测试和回放。
- 数据层只读原版资源；写操作只允许存档路径。
- 每个结构体保留字段编号注释，例如 `WarPC[273]`，方便与文档和 Python schema 对照。

## 6. 数据层与类型定义

第一阶段优先定义这些结构：

| 结构 | 大小/字段 | 来源 |
| --- | --- | --- |
| `TKMatRec` | 96 x int32 | `mat_editor`、`entity_map_event_system.md` |
| `TKDefUnitRec` | 16 字节 | `entity_map_event_system.md` |
| `WarPCRec` | 527 x int16 | `warpc_schema.py` |
| `TKItemRec` | 32 x int16 | `item_editor_v2.py` |
| `TKSkillRec` | 47 x int16 | `skill_editor_v2.py` |
| `TKShopRec` | 4 x int16 | `shop_editor_v2.py` |
| `TKKonRec` | 20 x int16 | `kon_editor_v2.py` |
| `TKActRec` | 784 字节 | `act_editor_v2.py` |
| `WarDataRec` | 498 字节 | `wardata_editor_v2.py` |
| `WarWayBlock` | 1024 字节 | `wardata_editor_v2.py` |
| `SaveBlockA` | 3432 字节 | `save_system_runtime.md` |
| `SaveBlockB` | 5768 字节 | `save_system_runtime.md` |

Codec 也需要有明确 API：

```cpp
struct GrpSection {
  uint16_t width, height;
  std::vector<uint8_t> frameA; // RGB565 主图
  std::vector<uint8_t> layer1; // 前景/碰撞
  std::vector<uint8_t> layer2; // 可选
};

struct JvgSprite {
  uint16_t width, height;
  std::vector<uint8_t> palette; // 256 x RGB
  std::vector<uint8_t> pixels;
  std::vector<uint8_t> alpha;
};
```

## 7. 反编译代码迁移策略

### 7.1 优先级

```text
1. 已由 docs/editor 验证的模块  -> 直接按规格写
2. decompile/*.c 有完整伪 C      -> 人工翻译
3. disassembly fallback          -> 手写 + 运行时 trace
4. decompile_skipped             -> 不迁移
```

### 7.2 伪 C 翻译规则

| 伪 C 形态 | C++ 处理 |
| --- | --- |
| `sub_XXXXXX` | 按子系统命名：`SceneManager::ChangeScene`、`SceVM::Exec` |
| `v1/v2/j/k` | 按语义命名，最少保留类型 |
| `_DWORD` | `int32_t`/`uint32_t` |
| `_WORD` | `int16_t`/`uint16_t` |
| `__fastcall` | 普通 C++ 函数，不模拟寄存器传参 |
| `BYREF` | 指针/引用 |
| `*(int *)(base + off)` | 结构体字段访问 |
| `byte_9D6C28` | 放入 `GameState` 子结构，保留文档字段名 |

不要试图直接编译 `tks_reverse/remake/*.c`。那些文件是“反编译提取物”，缺少头文件、类型和全局声明。

### 7.3 全局内存怎么处理

建议：

- 不把地址 `0x401000-0xA7D000` 原样搬进新程序。
- 把 `pointers.txt`、`memory/`、`runtime_memory_map.md` 映射成 `GameState` 的具名字段。
- 在字段旁边保留原始地址/变量名注释，便于和 trace 对照。
- 不要用裸指针数组替代结构体；否则后续测试和可维护性会很差。

例如：

```cpp
struct ScriptState {
  int16_t vars[256];      // word_755E80
  int16_t switches[32];   // word_755E10
  int16_t results[24];    // word_755E50
  int16_t flags[1024];    // word_756080
};
```

## 8. 分阶段实施与验收标准

### 阶段 0：可编译骨架 + 数据层

范围：

- 新建 `TKSRemake/`，CMake + C++20。
- 接入 SDL2、SDL_mixer 作为开发依赖，但 core 不依赖它们。
- 移植 LZSS、GRP/IDX、JVG、GXP、FONT9696、TKT/TKD。
- 定义上述结构体。
- 提供 `dump_assets --game-dir <path>`。

验收：

- `dump_assets` 输出的记录数、容量、CRC/哈希与 Python 编辑器一致。
- GRP/JVG/GXP 解码像素与 Python 输出一致。
- 不修改任何 `.dat/.GRP/.JVG/.GXP`。

### 阶段 1：无渲染核心

范围：

- SCE VM：`DefCmd.Lst` 解析、`TKD.dat` DEFINE 编译、0-82 命令执行。
- 实体调度：`sub_409618` 的 type 5/10/15/16/20/110/200。
- 场景切换：`ChangeScene` 对应逻辑。
- 存档读写：`sav.%d`、`%d.sav`。

验收：

- 对选定 DEFINE 做脚本 trace，Flag/Var/Switch/PC 与原版一致。
- 读取原版存档，再写出，C++ 与 Python 结果一致。
- 可以先不显示画面，只输出状态日志。

### 阶段 2：SDL2 平台层

范围：

- SDL2 窗口、固定 60ms 主循环、键盘/鼠标。
- 软件帧缓冲、JVG/GRP 精灵绘制、FONT9696 文本、Alpha LUT。
- SDL_mixer WAV/MP3。
- AVI 门面 + 跳过模式。
- 中文输入适配。

验收：

- 能从标题进入主菜单。
- 能开始新游戏、走路、切换场景、触发对话。
- 关键画面与原版截图做像素/布局对照。

### 阶段 3：战斗与 7 个小游戏

范围：

- 战斗初始化、菜单状态机、移动/目标选择。
- 技能分发 `sub_4458B0`、公式 `sub_43E980`、AI `sub_4359A4` 等。
- 战斗核心 `sub_4400DC` 手写 C++。
- 战后奖励、回写。
- 7 个小游戏。

验收：

- 能完整打赢/打输一场战斗。
- 战斗前后 WarPC/队伍/存档变化与原版一致。
- 小游戏完成条件与返回结果一致。

### 阶段 4：行为与像素对照

范围：

- 原版和重制版同一游戏目录并行运行。
- 截图 diff：标题、地图、对话、战斗、小游戏。
- trace diff：脚本 PC、Flag/Var、战斗数值、掉落随机序列。
- 存档双向兼容：原版读取新写存档，新版读取原版存档。

验收：

- 核心路径无肉眼可见差异。
- 存档字节兼容或至少语义兼容。

## 9. 主要风险与缓解

### 9.1 `sub_4400DC` 和 7 个 fallback

风险：

- 3001 条汇编，命令数多。
- 无法靠自动反编译直接得到可编译 C++。

缓解：

- 阶段 0/1 完全不依赖它。
- 阶段 3 前先做运行 trace，记录输入/输出数组和全局变量变化。
- 按文档中的阶段划分逐块手写：技能特判、道具治疗、伤害、击杀/奖励、MP/范围、状态入队。

### 9.2 像素保真

风险：

- 直接使用 SDL 默认 alpha 会偏离原版 LUT。
- 光照、淡入淡出、JVG 翻转方向容易产生微小差异。

缓解：

- 渲染层以 16 位像素为内部格式。
- 把 `alpha_blend_formula.md` 写成单测。
- 截图 diff 作为阶段 2/4 的硬门槛。

### 9.3 中文输入

风险：

- SDL 文本输入在 Windows 上支持 IME，但原版 `InputChinese` 是 IMM 风格。

缓解：

- 先用 `SDL_StartTextInput` 和 `SDL_TEXTINPUT`。
- 若手感和候选框不符，再在 `platform/win_ime.cpp` 内处理 `WM_IME_*`。

### 9.4 老 AVI

风险：

- 老 DirectShow AVI 不一定被所有现代库直接支持。

缓解：

- AVI 不阻塞核心进度。
- `AvPlayer` 提供 skip/no-op 实现。
- 先保留 DirectShow，再逐步替换为 FFmpeg/Media Foundation。

### 9.5 存档兼容

风险：

- 存档有硬编码偏移和长度。
- 现有启动器已经做过 WarPC 扩展补丁。

缓解：

- 第一阶段严格按原版 150722/159922 布局。
- 所有写存档测试在副本上执行。
- 若未来支持 MOD 扩展，单独做兼容层，不混入核心保存逻辑。

### 9.6 随机与未定义行为

风险：

- 战斗、AI、掉落依赖同一随机数顺序。
- 有符号/无符号边界已经在验证文档中暴露过问题。

缓解：

- 复刻原版随机数调用序列，而不是“功能等价但顺序不同”。
- 结构体用 `int16_t`/`uint16_t` 明确符号。
- 对已知 patch 点建立回归测试。

## 10. 开发环境与工具链

### 10.1 工具清单

| 工具 | 用途 | 必需 | 当前机器状态 | 安装方式 |
| --- | --- | --- | --- | --- |
| Visual Studio 2022 Community | C++ 编译器、调试器、Windows SDK | 必需 | 已安装：`C:\Program Files\Microsoft Visual Studio\2022\Community` | 在 Visual Studio Installer 中增加“使用 C++ 的桌面开发”工作负载 |
| MSVC v143 | 编译 C++20 | 必需 | 已安装：14.44.35207 | 随 NativeDesktop 工作负载安装 |
| CMake | 构建系统 | 必需 | 已安装：4.4.2，位于 `C:\Program Files\CMake\bin` | `winget install Kitware.CMake --source winget`，或在 VS Installer 中安装 CMake tools |
| Ninja | 可选的快速构建后端 | 推荐 | 已安装：1.13.2，位于 `C:\dev\bin\ninja.exe` | `winget install Ninja-build.Ninja --source winget`；若 PATH 未更新，复制到 `C:\dev\bin` |
| Git | 拉取 vcpkg 和源码 | 必需 | 已安装：2.53.0.windows.3 | `winget install Git.Git` |
| Python 3.11+ | 运行 Python oracle、golden 对比、工具脚本 | 必需 | 已安装：3.13.14 | `winget install Python.Python.3.13` |
| PowerShell 7 | vcpkg 编译部分依赖时需要 | 必需 | 已安装：7.6.4 | `winget install Microsoft.PowerShell --source winget` |
| vcpkg | 安装 SDL2、SDL2_mixer 等 C++ 依赖 | 推荐 | 已安装：`C:\dev\vcpkg`，`VCPKG_ROOT` 已设置 | `git clone` + `bootstrap-vcpkg.bat`；GitHub 不可达时使用 Gitee 镜像 |
| SDL2 | 窗口、输入、纹理输出 | 必需 | 已安装：2.32.10 | 通过 vcpkg manifest 自动安装 |
| SDL2_mixer | WAV/MP3 音频 | 必需 | 已安装：2.8.2，启用 `mpg123` | 通过 vcpkg manifest 自动安装，启用 `mpg123` |
| FFmpeg | 后续替换 DirectShow AVI | 可选 | 未安装 | `vcpkg install ffmpeg[avcodec,avformat,swresample,swscale]` |
| clang-format / clang-tidy | 格式化与静态检查 | 可选 | 未安装 | `winget install LLVM.LLVM` |
| Visual Studio 调试器 | 断点、内存、调用栈 | 必需 | 随 VS 安装 | 无需单独安装 |
| signtool | 正式发布时代码签名 | 可选 | 随 Windows SDK 安装 | 无需单独安装 |

### 10.2 安装步骤

#### 10.2.1 安装/补齐 Visual Studio

如果尚未安装，用管理员 PowerShell 执行：

```powershell
winget install Microsoft.VisualStudio.2022.Community --override "--add Microsoft.VisualStudio.Workload.NativeDesktop --includeRecommended --passive --norestart"
```

如果 VS 2022 已经安装，打开 Visual Studio Installer，选择“修改”，勾选：

- 使用 C++ 的桌面开发
- Windows 11 SDK 或 Windows 10 SDK
- 可选：适用于 Windows 的 C++ CMake 工具

安装完成后重新打开 PowerShell，确认编译器可用：

```powershell
& "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cl
```

#### 10.2.2 安装 CMake、Ninja、Git、Python

```powershell
winget install Kitware.CMake
winget install Ninja-build.Ninja
winget install Git.Git
winget install Python.Python.3.13
winget install Microsoft.PowerShell
```

安装后关闭并重开终端，让 PATH 生效：

```powershell
cmake --version
ninja --version
git --version
python --version
pwsh --version
```

如果 `ninja` 仍然无法识别，说明 winget 没有把包目录加入 PATH。可以把它复制到已经存在的 `C:\dev\bin`：

```powershell
New-Item -ItemType Directory -Force -Path C:\dev\bin | Out-Null
Copy-Item "%USERPROFILE%/AppData\Local\Microsoft\WinGet\Packages\Ninja-build.Ninja_Microsoft.Winget.Source_8wekyb3d8bbwe\ninja.exe" C:\dev\bin\ninja.exe -Force
[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';C:\dev\bin', 'User')
```

#### 10.2.3 安装 vcpkg

```powershell
git clone https://github.com/microsoft/vcpkg.git C:\dev\vcpkg
C:\dev\vcpkg\bootstrap-vcpkg.bat
setx VCPKG_ROOT "C:\dev\vcpkg"
C:\dev\vcpkg\vcpkg.exe integrate install
```

如果 GitHub 直连失败，改用国内镜像：

```powershell
git clone https://gitee.com/mirrors/vcpkg.git C:\dev\vcpkg
C:\dev\vcpkg\bootstrap-vcpkg.bat -disableMetrics
```

推荐在 `TKSRemake/` 使用 manifest 模式，依赖声明放在项目的 `vcpkg.json`：

```json
{
  "name": "tks-remake",
  "version": "0.1.0",
  "dependencies": [
    "sdl2",
    {
      "name": "sdl2-mixer",
      "features": [ "mpg123" ]
    }
  ]
}
```

配置 CMake 时传入 vcpkg toolchain 文件，vcpkg 会自动安装依赖。也可以先手动安装：

```powershell
C:\dev\vcpkg\vcpkg.exe install sdl2 sdl2-mixer[mpg123] --triplet x64-windows
```

### 10.3 验证工具链

```powershell
cmake --version
ninja --version
git --version
python --version
C:\dev\vcpkg\vcpkg.exe list
```

预期能看到 CMake、Ninja、Git、Python 版本号，以及 `sdl2`、`sdl2-mixer` 依赖项。

## 11. 构建、运行、调试与发布

### 11.1 CMake 关键配置

`TKSRemake/CMakeLists.txt` 至少需要：

```cmake
cmake_minimum_required(VERSION 3.28)
project(TKS LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/bin/Debug")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/bin/Release")

find_package(SDL2 CONFIG REQUIRED)
find_package(SDL2_mixer CONFIG REQUIRED)

add_executable(TKS WIN32
  src/main.cpp
  ...
)

target_link_libraries(TKS PRIVATE
  SDL2::SDL2
  SDL2::SDL2main
  SDL2_mixer::SDL2_mixer
)

include(CTest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()
```

### 11.2 配置与构建

使用 Visual Studio 2022 生成器：

```powershell
cmake -S TKSRemake `
      -B TKSRemake\build `
      -G "Visual Studio 17 2022" `
      -A x64 `
      -DCMAKE_TOOLCHAIN_FILE=C:\dev\vcpkg\scripts\buildsystems\vcpkg.cmake `
      -DVCPKG_TARGET_TRIPLET=x64-windows
```

构建 Debug：

```powershell
cmake --build TKSRemake\build --config Debug
```

构建 Release：

```powershell
cmake --build TKSRemake\build --config Release
```

也可以直接打开生成的解决方案：

```powershell
start TKSRemake\build\TKS.sln
```

### 11.3 运行项目

默认从当前工作目录读取游戏资源，也支持 `--game-dir` 指定原游戏目录：

```powershell
cd "游戏目录（改版）"
TKSRemake\build\bin\Debug\TKS.exe
```

或：

```powershell
TKSRemake\build\bin\Debug\TKS.exe `
  --game-dir "游戏目录（改版）"
```

建议支持的启动参数：

| 参数 | 作用 |
| --- | --- |
| `--game-dir <path>` | 指定原游戏目录 |
| `--headless` | 不创建窗口，只跑逻辑，用于自动化测试 |
| `--trace-script` | 输出脚本 PC/Flag/Var 状态 |
| `--seed <n>` | 固定随机数种子 |
| `--screenshot-out <path>` | 每帧或指定帧输出画面 |
| `--log-level debug` | 打开详细日志 |

数据层验证工具：

```powershell
TKSRemake\build\bin\Debug\dump_assets.exe `
  --game-dir "游戏目录（改版）" --format json
```

### 11.4 运行测试

```powershell
ctest --test-dir TKSRemake\build -C Debug --output-on-failure
ctest --test-dir TKSRemake\build -C Release --output-on-failure
```

建议在每个阶段都固定运行：

- `codec_golden_tests`：LZSS/GRP/JVG/GXP/FONT9696 与原版文件 golden 对比。
- `script_vm_tests`：SCE 脚本 trace。
- `save_roundtrip_tests`：存档读写往返。
- `battle_logic_tests`：公式、AI、掉落、战斗结算。
- `render_pixel_tests`：16bpp、LUT alpha、字体渲染像素。

### 11.5 开发调试

#### 11.5.1 使用 Visual Studio 调试

方式一：用 Visual Studio 2022 以文件夹方式打开

```powershell
start "" "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe" TKSRemake
```

Visual Studio 会识别 `CMakeLists.txt`。在 CMake 设置或 `launch.vs.json` 中配置启动：

```json
{
  "version": "0.2.1",
  "configurations": [
    {
      "type": "cppvsdbg",
      "name": "TKS Debug",
      "project": "CMakeLists.txt",
      "args": [ "--game-dir", "游戏目录（改版）" ],
      "cwd": "游戏目录（改版）"
    }
  ]
}
```

然后在 `src/main.cpp`、`SceVM::Exec`、`SceneManager::ChangeScene`、`BattleActionExecutor` 等位置设置断点。

方式二：打开生成的 `.sln`

```powershell
start TKSRemake\build\TKS.sln
```

将 `TKS` 设为启动项目，在项目属性中设置：

- 工作目录：`游戏目录（改版）`
- 命令参数：`--game-dir "游戏目录（改版）"`

#### 11.5.2 调试要点

- 逻辑调试优先用 `--headless --trace-script --seed 1`，比直接开窗口稳定。
- 内存和结构体字段通过 `GameState` 查看，不要通过原始地址 `0x9D6C30` 找值；源码注释中保留原地址映射。
- 像素问题用 `--screenshot-out` 输出 BMP/PNG，和原版截图做像素 diff。
- 行为问题用 `replay_trace` 生成确定性 trace，再和原版运行 trace 对比。
- Python oracle 对比命令由 Phase 0 的工具提供：

```powershell
python tools\compare_python.py `
  --dump TKSRemake\build\bin\Debug\dump_assets.exe `
  --game-dir "游戏目录（改版）"
```

### 11.6 编译与发布新 TKS.exe

#### 11.6.1 Release 构建

```powershell
cmake --build TKSRemake\build --config Release
ctest --test-dir TKSRemake\build -C Release --output-on-failure
```

输出目录：

```text
TKSRemake\build\bin\Release\
  TKS.exe
```

如果使用 vcpkg 的 `x64-windows` dynamic 依赖，发布目录还需要：

```text
SDL2.dll
SDL2_mixer.dll
mpg123 相关 DLL（如果启用 mpg123 feature）
```

这些 DLL 通常位于：

```text
TKSRemake\build\vcpkg_installed\x64-windows\bin
```

#### 11.6.2 发布目录

建议的发布结构：

```text
dist\TKS\
  TKS.exe
  SDL2.dll
  SDL2_mixer.dll
  LICENSE.txt
  README.txt
```

发布到原游戏目录时：

```powershell
$dist = "TKSRemake\dist\TKS"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Copy-Item "TKSRemake\build\bin\Release\TKS.exe" $dist
Copy-Item "TKSRemake\build\vcpkg_installed\x64-windows\bin\SDL2.dll" $dist
Copy-Item "TKSRemake\build\vcpkg_installed\x64-windows\bin\SDL2_mixer.dll" $dist
Copy-Item "TKSRemake\build\vcpkg_installed\x64-windows\bin\*.mpg123*.dll" $dist
```

然后将 `dist\TKS` 下的文件复制到原游戏目录，保持 `.dat/.GRP/.JVG/.GXP/.mp3/.avi` 原样，不覆盖资源文件。

#### 11.6.3 发布前检查清单

- Release 构建通过。
- `ctest -C Release` 全部通过。
- `dump_assets` 与 Python 编辑器输出一致。
- 在干净的原版游戏目录副本中能启动到标题。
- 能开始新游戏、走路、对话、进出场景。
- 战斗和小游戏在对应阶段验收通过。
- 存档写入测试使用副本，确认原版资源目录没有被写入。
- 确认目标机器安装了 VC++ Redistributable，或项目统一使用静态运行库。

#### 11.6.4 单文件发布说明

如果要求最终只替换一个 `TKS.exe`、不附带 DLL：

- 需要把 SDL2、SDL2_mixer、mpg123 全部静态链接。
- MSVC 运行库统一使用 `/MT`。
- vcpkg triplet 改为 `x64-windows-static`。
- CMake 配置时增加 `-DVCPKG_TARGET_TRIPLET=x64-windows-static`。

这是后续可选项，不属于第一阶段默认流程。第一阶段先保证动态 DLL 发布路径简单可验证。

## 12. 工作量分配与下一步

粗略看，B 的工程量不是均匀分布的：

| 模块 | 相对成本 | 说明 |
| --- | --- | --- |
| 数据层/codec | 低-中 | 主要是机械翻译，Python oracle 已存在 |
| 脚本/实体/场景 | 中 | 文档完整，翻译为主 |
| 渲染/UI/音频 | 中 | 像素细节多，但范围可控 |
| 战斗核心/小游戏 | 高 | `sub_4400DC` 和交互手感最耗时 |
| 行为验证 | 中 | 需要贯穿全程，不能最后补 |

下一步建议按这个顺序执行：

1. 新建 `TKSRemake/` 的 CMake 骨架。
2. 按第 10 节安装并验证工具链。
3. 先移植 `LZSS` + `GRP/IDX` + `JVG` + `GXP`，写 golden 测试。
4. 定义 `TksTypes.h` 和 `GameState.h`。
5. 做 `dump_assets` 与 Python 编辑器对拍。
6. 数据层稳定后，再进入 SCE VM 和场景核心。
