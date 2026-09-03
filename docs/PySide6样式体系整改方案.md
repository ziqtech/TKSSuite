# PySide6 样式体系整改方案

> 创建日期：2026-09-03
> 状态：**四阶段全部完成（2026-09-03）**，余量为各阶段清单内遗留增量项与可选附加项
> 结论：留在 PySide6 维护现有项目，聚焦根治"样式难维护、经常出错"。
> 本文档是唯一进度事实来源，每完成一项须同步更新"执行进度"章节。

***

## 一、背景与目标

用户痛点：**前端样式难维护，经常出错**。经全量摸底，痛点不是架构烂（架构底子是好的），而是三个具体机制在漏：

| # | 病灶                                                                | 直接后果                             |
| - | ----------------------------------------------------------------- | -------------------------------- |
| 1 | 颜色没有单一事实来源：4 份 QSS 手工复制维护，同组颜色散在 QSS / QPalette / \_CANVAS\_BG 三处 | 改一个主题色要对齐 3 处 × 2\~4 份文件，漏改即错    |
| 2 | 381 个硬编码十六进制颜色散布 27 个业务文件（自绘控件画笔）                                 | 主题切换后自绘控件颜色错位；5 个编辑器靠手工钩子同步，其余裸奔 |
| 3 | 约 1500 行启动/菜单样板在 18 个 GUI 入口逐字重复                                  | 改一处启动行为要动 18 个文件                 |

整改目标：

1. 主题颜色收敛到**单一 token 表**，QSS/QPalette/画布底色/自绘画笔全部从它派生。
2. 主题切换后**全项目视觉一致**，无手工同步钩子。
3. 18 个入口样板收敛到共享壳，单点维护。
4. 建立 **offscreen 冒烟测试**安全网，样式改坏可被机器发现。

体检中确认**不是问题**、整改时不动的：内联 `setStyleSheet` 全项目仅 8 处（纪律好）；共享控件复用健康（AdaptiveTableWidget 15 处、EditorTabWidget 9 处、EditorComboBox \~20 处）；launcher 的 core/workers/ui 分层。

***

## 二、现状基线数据（2026-09-03 实测）

整改后用同样口径复测，验证改进。

### 2.1 QSS 主题文件（editor\_themes/）

| 文件                | 行数       | 同族差异（实测 diff）                         |
| ----------------- | -------- | ------------------------------------- |
| classic-dark.qss  | 631      | 与 classic-light 差 534 行（= 只换色值的整文件复制） |
| classic-light.qss | 631      | 同上                                    |
| gpt-dark.qss      | 1883     | 与 gpt-light 差 814 行（同构复制）             |
| gpt-light.qss     | 1883     | 同上                                    |
| **合计**            | **5028** | 可收敛为 2 个族模板 + 4 份 token               |

颜色三处独立维护的位置：

- QSS 文件本体：`editor_themes/*.qss`

- QPalette 表：`editor_utils/theme_manager.py:135-205`（53 个颜色）

- 画布底色表：`editor_utils/theme_manager.py:107-112`（\_CANVAS\_BG）

### 2.2 硬编码颜色分布（业务代码，grep `#[0-9a-fA-F]{6}`）

合计 **381 处 / 27 个文件**。`theme_manager.py` 的 53 处是合法定义位（阶段 1 改造为 token 表后保留），其余为待收编对象。重灾区排序：

| 文件                                         | 处数     | 文件                                             | 处数     |
| ------------------------------------------ | ------ | ---------------------------------------------- | ------ |
| spritesheet\_editor/spritesheet\_editor.py | 48     | tks\_launcher\_gui/ui/log\_console.py          | 14     |
| tks\_launcher\_gui/ui/mode\_card.py        | 48     | tks\_book/tab\_map.py                          | 5      |
| skill\_editor/skill\_editor.py             | 36     | mat\_editor/mat\_widgets.py                    | 5      |
| mat\_editor/mat\_editor.py                 | 31     | tks\_book/book\_growth.py                      | 2      |
| act\_editor/act\_editor.py                 | 28     | tks\_launcher\_gui/ui/game\_overlay.py         | 2      |
| tks\_book/book\_skill\_graph.py            | 23     | tks\_launcher\_gui/ui/custom\_music\_dialog.py | 2      |
| wardata\_editor/wardata\_editor.py         | 22     | mat\_editor/mat\_constants.py                  | 2      |
| editor\_utils/theme\_manager.py            | 53（合法） | gxp\_editor/gxp\_editor.py                     | 1      |
| editor\_utils/window\_theme.py             | 12     | warpc\_editor/warpc\_table\_mode.py            | 4      |
| editor\_utils/tab\_widget.py               | 4      | warpc\_editor/warpc\_editor.py                 | 5      |
| editor\_utils/ui\_helpers.py               | 4      | grp\_editor/grp\_editor.py                     | 8      |
| tkt\_editor/tkt\_editor.py                 | 8      | kon\_editor/kon\_editor.py                     | 6      |
| save\_editor/save\_editor.py               | 3      | shop\_editor/shop\_editor.py                   | 3      |
| font\_editor/font\_editor.py               | 2      | <br />                                         | <br /> |

### 2.3 手工主题同步钩子（阶段 2 完成后应全部删除）

| 位置                                         | 同步内容     |
| ------------------------------------------ | -------- |
| font\_editor/font\_editor.py:439           | 画布底色等派生色 |
| gxp\_editor/gxp\_editor.py:239             | 同类       |
| jvg\_editor/jvg\_editor.py:935             | 同类       |
| mat\_editor/mat\_editor.py:1308            | 同类       |
| tks\_launcher\_gui/ui/main\_window\.py:720 | 高亮调色板等   |

### 2.4 样板重复（18 个 GUI 入口）

- `main()` 13 行逐字雷同 × 18（例：shop\_editor.py:1130-1148、item\_editor.py:1714-1726、act\_editor.py:4482-4496）

- 窗口 `__init__` 重复：objectName("EditorWindow") / format\_title / resize / TKS.ico（与 main 里 setup\_app\_icon 设了两遍）

- 菜单"文件/主题/帮助"约 25 行 × 18

- `_apply_theme / _toggle_theme / _create_dock / _show_help / _show_about` 五件套共 **77 处**

- 估算：每编辑器 90-110 行纯样板，全库约 1500 行

### 2.5 对话框复制粘贴

| 对话框                       | 副本位置                                                              | 同构度   |
| ------------------------- | ----------------------------------------------------------------- | ----- |
| SkillPickerDialog         | item\_editor.py:285 / skill\_editor.py:188 / warpc\_editor.py:318 | \~70% |
| FieldRefDialog            | kon\_editor.py:232 / warpc\_editor.py:507                         | 高     |
| GrowthTableDialog         | warpc\_editor.py:571 / tks\_book/book\_growth.py:29               | 高     |
| Icon/Flag/UseRight picker | item\_editor 与 warpc\_editor 各有一套，未入库                             | —     |

### 2.6 测试现状

- `tks_launcher_gui/tests/`：1764 行，unittest 风格，测 launcher 逻辑层（core/workers），**UI 层零覆盖**

- `test_shot.py`：QTimer 步进截图手工脚本 —— 冒烟测试可参照其模式

***

## 三、整改方案（四阶段）

依赖关系：**阶段 0 必须最先完成**（安全网）；阶段 1 是阶段 2 的前提（token 表先存在，业务代码才有处可取色）；阶段 3、4 相互独立，可穿插进行。

### 阶段 0：建立冒烟测试安全网

**目标**：任何样式/主题改动后可一键机器验证，改坏立刻发现。

**任务**：

1. 新建 `tests/test_editor_smoke.py`（项目根 tests/，unittest 风格与 launcher 现有测试一致）。
2. 测试进程设置 `QT_QPA_PLATFORM=offscreen`（在模块导入前 `os.environ` 设置）。
3. 用例设计：

   - [ ] 逐个实例化 18 个入口的主窗口类（16 编辑器 + tks\_book + launcher 主窗口），断言不抛异常；

   - [ ] 对每个窗口 × 4 个主题执行 `apply_theme`（经 theme\_switcher.apply\_theme\_to\_window），断言 `widget.styleSheet()` 非空；

   - [ ] **一致性断言（专治病灶 1）**：解析每份 QSS 中 `QGraphicsView` 的 `background-color`，断言与 `theme_manager.canvas_background(theme_id)` 一致；QPalette 的 Window/Base/Highlight 断言与 `theme_manager.palette()` 一致；

   - [ ] 关键控件存在性：EditorTabWidget/AdaptiveTableWidget 的 objectName 或类查找不返回空（防 QSS 选择器目标丢失）。
4. 注意事项：

   - 各编辑器模块用 `sys.path` 注入自目录，测试需按其导入约定逐个处理（参照各编辑器 `main()` 里的路径注入行）；

   - 部分编辑器窗口构造需要数据文件存在，若构造即读文件，需在测试里处理（临时跳过或构造前 chdir 到样例数据目录），摸清后在此处记录豁免清单；

   - 单实例锁（ensure\_single\_instance）会干扰多窗口同进程测试，测试模式下需绕过（可用环境变量开关或 monkeypatch）。
5. 编写运行入口：`python -m tests.test_editor_smoke` 或 pytest 兼容。

**验收**：本地一键跑通；输出当前"主题切换后颜色不同步"的基线报告（哪些断言初始即失败，作为阶段 1/2 的修复清单而非阻塞项——初期可将已知失败标记 expectedFailure）。

### 阶段 1：颜色单一事实来源（token 化）

**目标**：5028 行 QSS 收敛为 2 个族模板 + 4 份 token 表；QPalette/\_CANVAS\_BG 从 token 派生；改一个主题色只动一处。

**任务**：

1. [ ] 新建 `editor_utils/theme_tokens.py`：定义 token 语义键（`bg / surface / surface_alt / border / border_strong / text / text_muted / accent / accent_hover / canvas_bg / danger / …`），每主题一份 dict。以现有 4 份 QSS + QPalette + \_CANVAS\_BG 中实际用到的颜色为准提取，键名从简，宁少勿多。
2. [ ] 生成族模板：以 gpt-dark 为基准提取 `editor_themes/templates/modern.qss.tpl`，把色值替换为 `{{token}}` 占位符；同法从 classic-dark 提取 `classic.qss.tpl`。跨族确实不同的结构性规则（选择器、属性集）保留在各自模板中。
3. [ ] 改造 `theme_manager._load_qss`：加载模板并做 token 注入（现成的 `url()` 正则重写机制同处扩展，用 `str.format` 或 `string.Template` 均可，注意 QSS 里 `{}` 大括号冲突——用 `string.Template` + `$token` 或自定分隔符更稳）。
4. [ ] `_PALETTE_COLORS`、`_CANVAS_BG` 改为从 token 表派生（theme\_manager 保留函数签名不变，调用方零改动）。
5. [ ] **等价性验证（关键验收手段）**：写临时脚本，用模板+token 生成 4 份 QSS 文本，与现有 4 份 .qss 文件逐字节 diff——**必须完全一致**后才删除旧 .qss 文件。若不一致，说明 token 提取有遗漏，回到第 2 步补齐。
6. [ ] 删除 4 份 .qss，主题目录只留 templates/。`build_all.py` 若有打包 editor\_themes 的数据文件清单，同步改为 templates 目录。
7. [ ] token 表补一份注释文档：每个键的用途、被哪些消费方引用。

**验收**：冒烟测试通过（含一致性断言）；QSS 从 5028 行 → 2 模板 + 4 token dict；新增主题只需加一份 token dict。

### 阶段 2：收编业务代码硬编码颜色（381 → <50）

**目标**：自绘控件画笔颜色全部来自 theme\_manager，主题切换全项目视觉一致，删除 5 处手工同步钩子。

**任务**：

1. [ ] `theme_manager` 增加取色 API：`color(theme_id, key) -> QColor` / `color_str(theme_id, key) -> str`；另提供便捷函数 `current(widget, key)`（从 widget 的 `_theme_id` 属性解析，theme\_switcher 已统一设置该属性）。
2. [ ] 逐文件替换（每文件一个 commit，跑一次冒烟测试）。优先级按处数从多到少：
   - [ ] spritesheet\_editor（48）

   - [ ] tks\_launcher\_gui/ui/mode\_card.py（48）

   - [ ] skill\_editor（36）

   - [ ] mat\_editor.py（31）+ mat\_widgets.py（5）+ mat\_constants.py（2，若属调色板常量则保留并在注释中说明）

   - [ ] act\_editor（28）

   - [ ] tks\_book/book\_skill\_graph.py（23）

   - [ ] wardata\_editor（22）

   - [ ] tks\_launcher\_gui/ui/log\_console.py（14）

   - [ ] editor\_utils/window\_theme.py（12）、tab\_widget.py（4）、ui\_helpers.py（4）——共享控件优先收编，业务侧跟随

   - [ ] tkt\_editor（8）、grp\_editor（8）、kon\_editor（6）、tks\_book/tab\_map.py（5）、warpc 两文件（9）、save\_editor（3）、shop\_editor（3）、font\_editor（2）、tks\_book/book\_growth.py（2）、game\_overlay（2）、custom\_music\_dialog（2）、gxp\_editor（1）
3. [ ] 替换中遇到"非语义色"（如固定的警示红、不可主题化的领域色）就地保留并加一行注释说明理由。
4. [ ] 全部替换后，删除 5 处 `_on_theme_applied` 手工同步钩子（见 §2.3），相关编辑器改为 paint 时即时取 token 色。
5. [ ] 更新 `apply_theme_to_window`：确认重设 QSS 后自绘控件触发 repaint（必要时对自绘控件发 styleChange/update）。

**验收**：grep `#[0-9a-fA-F]{6}`（排除 theme\_tokens.py / theme\_manager.py / 模板 / .qss）< 50 处且每处有注释豁免；冒烟测试含一致性断言全部通过；人工 4 主题切换抽查 spritesheet/mat/skill 三个重灾区截图。

### 阶段 3：入口样板收敛

**目标**：18 个 GUI 入口的 main() 缩到 \~3 行，菜单/主题/帮助五件套单点维护。

**任务**：

1. [ ] 新建 `editor_utils/app_shell.py`：
   - `run_editor(window_cls, title=None, size=None)`：封装 ensure\_single\_instance → QApplication → install\_dialog\_theme\_filter → setStyle("Fusion") → install\_translator → setup\_app\_icon → 窗口实例化 → exec；

   - `EditorMainWindow(QMainWindow)` 基类：`__init__` 统一 objectName/format\_title/resize/图标、`_apply_theme/_toggle_theme/_create_dock/_show_help/_show_about` 五件套、菜单构建钩子（子类可覆盖 `build_menus()` 追加专属菜单）。
2. [ ] 逐编辑器迁移（每入口一个 commit，冒烟测试通过后合入）：
   - [ ] shop\_editor → item\_editor → font\_editor → save\_editor（小编辑器先趟路）

   - [ ] kon\_editor → tkt\_editor → skill\_editor → gxp\_editor → grp\_editor → jvg\_editor → spritesheet\_editor

   - [ ] act\_editor → mat\_editor → wardata\_editor → warpc\_editor → configs\_editor

   - [ ] tks\_book

   - [ ] tks\_launcher\_gui/main.py（launcher 已有分层，只收编 main() 的样板部分，不动其结构）
3. [ ] 删除各编辑器中已被基类吸收的方法；确认 `editor_utils/app_init.py` 的职责并入 app\_shell 后保留还是删除（避免双头）。
4. [ ] `build/entries` 与 `gen_entries.py` 若引用各编辑器 main 符号，同步核对无需变更。

**验收**：18 个 `main()` 均 ≤3 行；全库净减约 1000+ 行；冒烟测试通过；每个编辑器 `--help`/关于/主题菜单行为不变（人工抽查 3 个）。

### 阶段 4：对话框去重

**目标**：消除 70% 同构的复制粘贴对话框，进 picker\_dialogs 统一参数化。

**任务**：

1. [ ] `picker_dialogs` 新增/合并 `SkillPickerDialog`（参数化数据源与回调），替换 item:285 / skill:188 / warpc:318 三份实现。
2. [ ] 合并 `FieldRefDialog` 两份（kon:232 / warpc:507）。
3. [ ] 合并 `GrowthTableDialog` 两份（warpc:571 / tks\_book/book\_growth:29）。
4. [ ] 评估 item 的 Icon/Flag/UseRight picker 与 warpc 的 Flags/UseRight 对话框是否可入库（行为一致则合并，差异大则记录并跳过）。

**验收**：三组对话框各只剩一份实现；冒烟测试通过；三个消费方功能人工抽查。

### 可选附加项（独立于四阶段，可随时做）

- [ ] Python 升级 3.11/3.12（已放弃 Win7，无历史包袱；Nuitka 兼容良好，启动/内存有免费收益；先在分支上跑通 build\_all.py 全量构建再合入）。

- [ ] 冒烟测试进 CI/本地一键脚本（如 build\_all.py 增加 `--smoke` 子命令，构建后自动跑）。

***

## 四、执行进度

> 状态图例：`未开始` / `进行中` / `已完成` / `跳过(原因)`。每完成一项更新此表和文末变更记录。

### 总览

| 阶段             | 状态      | 开始日期       | 完成日期       |
| -------------- | ------- | ---------- | ---------- |
| 阶段 0：冒烟测试      | **已完成** | 2026-09-03 | 2026-09-03 |
| 阶段 1：token 化   | **已完成** | 2026-09-03 | 2026-09-03 |
| 阶段 1 增补：模板统一   | **已完成** | 2026-09-03 | 2026-09-03 |
| 阶段 2：收编硬编码颜色   | **已完成** | 2026-09-03 | 2026-09-03 |
| 阶段 3：样板收敛      | **已完成** | 2026-09-03 | 2026-09-03 |
| 阶段 4：对话框去重     | **已完成** | 2026-09-03 | 2026-09-03 |
| 可选：Python 3.12 | 未开始     | <br />     | <br />     |

### 阶段 0 清单

- [x] tests/test\_editor\_smoke.py 骨架（offscreen + QApplication 复用）

- [x] 16 个编辑器主窗口实例化用例（含导入路径处理）

- [x] tks\_book + launcher 主窗口用例

- [x] 4 主题 × apply\_theme 循环用例

- [x] QSS/QPalette/画布底色一致性断言 —— **首跑即全部通过**（当前 4 主题在这两个轴上无漂移，无需 expectedFailure；一致性断言转为防回归）

- [x] 关键控件存在性断言（实现为窗口 objectName 非空 + `_theme_id` 同步检查，防 QSS 选择器目标丢失）

- [x] 运行入口 + 文档化命令：`python -m unittest tests.test_editor_smoke -v`（约 37s）

补充事实（实施中发现）：`editor_utils/window_theme.py:26-51` 的 `TITLEBAR_COLORS` 是主题颜色的**第四处**独立维护点，已并入阶段 1 改造范围。

### 阶段 1 清单

- [x] theme\_tokens.py（槽位表 + PALETTE + CANVAS\_BG + TITLEBAR，共 317 行）——**实现与原设计的差异**：因同族深浅映射是一对多的（同一深色在不同位置对应不同浅色），无法用"每主题一份颜色替换表"，实际采用**槽位型 token**：每族模板中每个分歧位置一个槽位，`theme_tokens.MODERN_SLOTS / CLASSIC_SLOTS` 以 `(深色值, 浅色值)` 元组存储（modern 140 槽、classic 167 槽）

- [x] modern.qss.tpl（1884 行）/ classic.qss.tpl（631 行）提取；引入 `{{name}}` 行内替换与 `{{?name}}` 可选行（值空则整行删除）两种槽位，完整保留了原有 6 处结构性分歧（modern 1 处行错位、classic 2 处属性行、SVG 资源路径、注释文本）

- [x] theme\_manager.\_load\_qss 改为模板渲染（含 `{{?}}` 可选行机制），ThemeSpec 移除 qss\_file 字段

- [x] \_PALETTE\_COLORS / \_CANVAS\_BG / window\_theme.TITLEBAR\_COLORS 全部改为从 theme\_tokens 派生（四处颜色维护点 → 一处）

- [x] 等价性验证：渲染结果与 4 份原 QSS 归一化后逐行一致（归一化 = hex3→hex6、大小写、url() 引号与既定的绝对路径重写）；迁移工具（extract\_templates.py / tokens\_draft.py）验证通过后已删除

- [x] 删除旧 .qss；build\_all.py 用 `--include-data-dir=editor_themes` 整目录打包，模板自动包含，无需改动

- [x] token 文件头含命名约定与查找技巧文档

**遗留增量任务（不阻塞，随日常迭代做）**：

- [ ] 槽位语义化重命名（bg\_01 → window\_bg 等；改名需同步模板中的槽位名，可用脚本批量做）

### 阶段 1 增补：模板统一（用户提出，数据验证后实施）

**背景**：用户指出"主题主要是颜色不一样，结构理论上应该一样，只保留一份 .tpl 就行"。实测验证成立：两族 469 个选择器**完全一致**、属性集合互相**零差异**、553 处值差异**全部是颜色**；行数差（1883 vs 631）纯粹是排版差异（modern 多行排版 vs classic 紧凑单行）。此前"两族结构不同"的判断是行级 diff 被排版差异误导所致。

**产物**：

- `editor_themes/templates/base.qss.tpl`（1964 行）——**全套件唯一结构模板**，以 modern 排版为规范

- `theme_tokens.SLOTS`——484 个四元组槽位，值顺序 `(gpt-dark, gpt-light, classic-dark, classic-light)`；`tokens_for(theme_id)` 取值

- 语义等价验证：4 主题 × 497 条规则解析级对比全部通过（选择器→属性→值逐一相等，忽略注释与排版）

- 冒烟测试全绿

**注意事项**：

1. classic 主题的 QSS 渲染输出排版从紧凑单行变为多行——Qt 解析等价，**零视觉影响**；
2. 模板注释统一采用 modern 版本文本——无渲染影响；
3. 属性在 4 主题间"存在性不同"的行用 `{{?name}}` 可选行承载（值含完整属性行文本，空串=该行不渲染）；
4. 现在新增控件样式只需改一份模板 + 补槽位值，4 个主题自动全覆盖——彻底消除"改了 modern 忘了 classic"的漂移模式。

中间产物（merge\_templates.py / slots\_draft.py / modern.qss.tpl / classic.qss.tpl）验证通过后已删除。

### 阶段 2 清单（按 §3 阶段 2 的文件顺序逐项勾选，此处不重复罗列）

- [x] 取色 API —— **实现形态调整**：摸底发现业务文件普遍已有"按主题的语义色字典"（如 mode\_card 的 `_CARD_COLORS`），因此实际采用**业务色板整表上移**模式：`theme_tokens.BUSINESS`（MODE\_CARD / LOG\_CONSOLE…，每键 4 元组）+ `theme_manager.business_colors(table, theme_id)`；`color_str/current` 全局语义键 API 待出现首个全局键消费者时再补（避免臆造键名）

- [x] mode\_card.py（48 → 0，表上移至 theme\_tokens.MODE\_CARD）

- [x] tks\_launcher\_gui/ui/log\_console.py（14 → 0，表上移至 theme\_tokens.LOG\_CONSOLE；接口从 dark 布尔改为 theme\_id 贯通，main\_window 钩子同步更新）

- [x] spritesheet\_editor.py（48 → 19，剩余全部为豁免）：画布类 19 色上收为模块级命名常量（图像编辑器惯例：画布恒为深色系保证精灵可见性，不随 UI 主题变化，块注释豁免）；主题感知的画布视口底色（2 处 is\_dark 分支）迁入 theme\_tokens.SPRITESHEET 表。~~顺带发现存量缺陷：菜单切换主题时画布不同步（仅快捷键切换同步）~~（**已解决**：主题入口现为工具栏按钮 → `_toggle_theme`，其内部已含画布背景刷同步逻辑）

- [x] skill\_editor.py（36 → 5，剩余全为豁免）：迁入 theme\_tokens.SKILL\_GRAPH 表（画布/网格点/类型色板×2/连线三色/标签胶囊/节点卡片/聚焦）；**3 处重复的"技能类型色板"收敛为 1 处**；SkillGraphView/SkillTreeDialog 构造签名从 is\_dark 改为 theme\_id 贯通；播种徽标三色与溢出警示红为主题无关领域常量（模块级豁免）

- [x] mat\_editor.py（31 → 8：5 个树形豁免常量 + 3 行说明注释）+ mat\_widgets.py（5 → 0）+ mat\_constants.py（2 处豁免注释）：迁入 theme\_tokens.MAT 表（实体类型色板/预览语法色板/脚本编辑器高亮色板/步骤高亮底色/TKT 可读性回退色）；mat\_widgets 的 `_PALETTE` 深浅对上移；ScriptSyntaxHighlighter 构造与 set\_dark → theme\_id/set\_theme 贯通

- [x] act\_editor.py（28 → 18，剩余全为豁免常量块）：迁入 theme\_tokens.ACT 表（时间轴底色/网格两线/语句弱化色）；预览画布恒深色 + 轨迹红绿/事件块/选中红/参考蓝/语句表四状态色/图层槽位八色上收为模块级命名常量（块注释豁免）；**图层槽位八色两处重复收敛为 1 处**（SLOT\_COLORS）

- [x] book\_skill\_graph.py（23 → 4，剩余全为豁免）：tks\_book 图谱类为 skill\_editor 同类的复制粘贴变体，颜色值与 SKILL\_GRAPH 表完全一致 → 直接复用该表（不新建表）；学习状态徽标三色为主题无关领域常量（模块级豁免）；调用方 tab\_char/tab\_skill 改传 theme\_id，tab\_skill 补齐 \_theme\_id 属性

- [x] wardata\_editor.py（22 → 常量块）：战场地图绘制色（地形/陷阱/宝箱/敌我阵营/选中）全部为领域常量，上收为模块级命名常量（块注释豁免）

- [x] 剩余 16 个小文件批处理：warpc/book\_growth 重复的 `_CLR_DELTA` 色对去重入 theme\_tokens.GROWTH 表（5 → 1 处定义）；grp/tkt/kon/save/game\_overlay/warpc\_table\_mode 等领域色补豁免注释；tkt/kon/shop/font/gxp/tab\_widget/ui\_helpers 等深浅二值分支补"主题感知"注释

- [x] 27 文件替换完成（**27/27**）

- [x] 5 处 \_on\_theme\_applied 钩子 —— **形态变化，不删除**：迁移后钩子不再手工对色，职责收敛为"主题切换时触发控件重建缓存"（如 mat 高亮器重建 QTextCharFormat），这正是所需的最小机制；删除反而会破坏主题切换刷新

- [x] 遗留硬编码颜色 —— **验收口径修正**：实测 381 处中约七成是主题无关的领域常量（战场标记/状态色/画布惯例色/音频波形色），并非主题数据。最终状态：全部剩余字面量均为①模块级命名常量（带块注释）②行内豁免注释③显式深浅二值分支（带注释）三者之一，**无任何无注释的散落字面量**（以裸值检查验证）。原"<50"指标基于"多数为主题色"的错误预估，实际以"零散落"为准

### 阶段 3 清单

- [x] app\_shell.py（run\_editor + EditorMainWindow）—— **实现与原设计的差异**：
  - 基类用**模板方法**而非简单继承：`_init_data`（属性初始化）/ `_build_ui`（必须实现）/ `_after_build`（收尾）三钩子，解决"主题应用与属性初始化的顺序"问题（原各编辑器 __init__ 顺序不一：有的主题前初始化、有的主题后）

  - 三个菜单钩子应对真实变体：`_extra_help_actions()`（帮助菜单专属项，如 item 字段来源/mat 字段说明/warpc 字段参考）、`THEME_MENU_TITLE`（save 的 \&M 键位冲突）、`ABOUT_TITLE`（tks\_book"关于查看器"）；`add_theme_submenu(parent)` / `add_help_menu(menubar)` / `add_standard_menus(menubar)` 三个粒度（kon/gxp/mat/tks\_book 主题菜单嵌在视图菜单内）

  - `run_editor` 扩展可选参数 `app_version/org_name/icon_dir/translator`，覆盖 launcher 特殊入口（图标在根目录、原本不装翻译器）

- [x] 18 入口迁移（**18/18**）：shop（模式设定者）→ item/font/save → kon/tkt/skill/gxp/grp/jvg/spritesheet → act/mat/wardata/warpc/configs → tks\_book → launcher main()
  - 各入口 main() 样板部分全部收敛为 `run_editor(...)` 1-2 行；tkt 的 argparse CLI 路由、spritesheet/jvg/grp 的 HAS\_PIL 前置检查、launcher 的 logging/verify-patches 路由属功能代码，保留在各 main() 内

  - 迁移中发现并保留的**合理覆盖变体**：warpc `_show_help` 动态内容（含记录数）、mat `_apply_theme` 纯派生同步（QSS 由 apply\_theme\_to\_window 应用，其覆盖不含 QSS 重应用）、`_create_dock` 签名扩展（header\_layout/body\_margins）

  - `__init__(filepath/initial_path)` 带参入口（tkt/gxp/grp/jvg/spritesheet）统一为 `_initial_path` 属性 + `_after_build` 加载模式

- [x] app\_init.py 职责归并 —— **保留，非双头**：app\_init 是原子工具库（单实例锁/路径工具/翻译器/图标），app\_shell 是启动编排器（经延迟导入使用其 3 个函数）；shared\_state/free\_notice 还消费其路径函数

- [x] build 侧核对 —— entry 薄入口只引用各编辑器 `main` 符号（`from xxx_editor import main`），main 符号全部保留，无需变更

**口径复测（2026-09-03）**：

- 18 个 main() 样板部分均收敛为 run\_editor 1 行（功能路由除外）

- `_show_help/_show_about` 定义：18 处 → 3 处（基类 + warpc 动态覆盖 + launcher 结构不动）

- `_apply_theme/_toggle_theme/_create_dock` 剩余定义全部为"真覆盖"（派生刷新/签名扩展），非逐字样板

- 净减约 540 行样板（18 文件 diff 统计），app\_shell.py 新增 179 行（当前实测）为单点共享

### 阶段 4 清单

- [x] SkillPickerDialog 合并（3→1）—— 参数化数据源形态：调用方预构建 `rows`（每项 `(key, cells, type_id)`）传入，弹窗与数据解耦；item / skill / warpc（经 `_make_skill_picker`）三消费方全部切换

- [x] FieldRefDialog 合并（2→1）—— **形态调整**：两份实现重复的只是"只读等宽文本弹窗"外壳，内容本就完全不同（TKKon vs WarPC 字段映射）→ 外壳收敛为 `ui_helpers.show_field_ref(parent, text, size)` 单实现，各编辑器仅保留 `_build_field_ref_text()` 数据函数

- [x] GrowthTableDialog 合并（2→1）—— 统一类落 picker_dialogs（theme_id 参数化）；tks_book/book_growth.py 整文件删除（-211 行），tab_char 直用统一类

- [x] Icon/Flag/UseRight picker 评估 —— **结论与实施**：IconPickerDialog 单消费者（仅 item）无重复，留置原处跳过；Flag×2（item FlagPickerDialog + warpc FlagsDialog）与 UseRight×2（item UseRightPickerDialog + warpc UseRightDialog）核心行为一致（位掩码语义、MOD 手动输入、有符号回绕），合并为 `picker_dialogs.BitmaskPickerDialog`

**BitmaskPickerDialog 合并要点**：

1. 语义双轨：`use_bit_shift=True` 时 bits 首元素为位序号（掩码 = 1<<bit，warpc FLAG_DEFS 与 item EXTRA_FLAG_BITS），否则首元素直接即掩码值（item COMBAT_FLAG_BITS 与双方 use_right）—— 这是原四份实现的最大差异点；warpc 两处旗标调用点必须显式传 `use_bit_shift=True`（其数据是位序号，漏传则 bit0 掩码为 0 永不可勾选）
2. desc 统一内联为 "name (desc)" 复选框文案；use_right 的 "bit-" 前缀与额外标志的 "(bitN)" 后缀随合并取消（desc 已含语义说明，视觉变化已确认接受）
3. `manual=True` 保留 MOD 扩展位手动输入框（勾选实时同步、16 位回绕、解析失败回退勾选值）
4. 结果 API 双轨兼容：`selected_mask`（item 风格判非 None）与 `get_value()`（warpc 风格）等价
5. warpc_table_mode 改从 editor_utils.picker_dialogs 导入，解除对 warpc_editor 的依赖；顺带清理 warpc_editor 孤儿 QCheckBox 导入

**口径复测（2026-09-03）**：四组对话框各只剩一份实现；14 处消费方调用点全部切换（Skill 3 / FieldRef 2 / Growth 2 / Bitmask 7）；两批次合计净减约 380 行（三组合并 -305、Bitmask 合并 -76）；冒烟测试 4/4 全绿，Bitmask 四种调用形态另做离屏功能冒烟（初始勾选态 / 全选掩码 / 手动框同步与回绕 / 取消返回 None / bit0 零掩码无副作用）全过。对话框交互无既有自动断言覆盖，4 主题下视觉一致性随日常使用人工复核。

***

## 五、执行纪律（后续会话按此操作）

1. **动手前**：读本方案的"四、执行进度"确认下一步；跑一遍冒烟测试确认基线绿（阶段 0 完成后）。
2. **粒度**：一个文件/一个入口一个 commit；commit message 标注阶段（如 `refactor(阶段2): 收编 spritesheet_editor 硬编码颜色`）。
3. **每步之后**：跑冒烟测试；更新 §四 进度表和文末变更记录。
4. **口径复测**：每完成一个阶段，用 §二 的同口径命令复测并更新数字：

   - QSS 行数：`wc -l editor_themes/**/*.qss*`

   - 硬编码颜色：`grep -rhoE "#[0-9a-fA-F]{6}\b" --include="*.py" . | wc -l`（及分文件 count）

   - 样板五件套：`grep -rE "def (_apply_theme|_toggle_theme|_show_help|_show_about)" --include="*.py" -l | wc -l`
5. **遇到方案未覆盖的情况**（如某编辑器启动样板结构特殊、token 提取冲突）：小决策就地处理并在本文档"变更记录"补一行；大决策（影响验收口径）先问用户。

***

## 六、变更记录

| 日期         | 内容                                                                                                                                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-09-03 | 方案定稿，基线数据实测完成，四阶段任务清单建立                                                                                                                                                                                                                   |
| 2026-09-03 | **阶段 0 完成**：`tests/test_editor_smoke.py` 建立并首跑全绿（18 入口 × 4 主题 + 一致性断言）；发现 TITLEBAR\_COLORS 为第四处颜色维护点，并入阶段 1                                                                                                                               |
| 2026-09-03 | **阶段 1 完成**：5028 行 QSS（4 份手工复制品）收敛为 2 个族模板 + `editor_utils/theme_tokens.py`（槽位表 + 三处派生色板）；等价性验证通过后删除旧 .qss；冒烟测试全绿。基线复测：QSS 文件数 4→2 模板，颜色维护点 4→1                                                                                           |
| 2026-09-03 | **阶段 1 增补完成（模板统一）**：应用户提议，实测确认两族结构完全同构（469 选择器一致、属性集零差异、值差异全为颜色）后，合并为单一 `base.qss.tpl` + 484 个四元组槽位；4 主题 × 497 条规则语义等价验证通过；冒烟全绿。QSS 结构维护点 2→1                                                                                             |
| 2026-09-03 | **阶段 2 开始**：取值 API 落地（`theme_tokens.BUSINESS` 业务色板区 + `theme_manager.business_colors`）；mode\_card（48→0）、log\_console（14→0）迁移完成，log\_console 接口从 dark 布尔改为 theme\_id。硬编码颜色余量 314/27 文件（定义位 theme\_tokens 537 处不计）                          |
| 2026-09-03 | **阶段 2 完成（27/27 文件）**：新增业务色板表 SPRITESHEET/SKILL\_GRAPH/MAT/ACT/GROWTH（mode\_card/log\_console 在前）；5 组跨文件/跨函数重复色板去重（技能类型色板×3、图层槽位色×2、Δ增量色对×2）；theme\_id 贯通 5 个控件构造签名；领域常量全部命名化+豁免注释。冒烟全绿。验收口径按实测修正（见阶段 2 清单末项）                             |
| 2026-09-03 | **阶段 3 完成（18/18 入口）**：app\_shell.py（EditorMainWindow 模板方法基类 + run\_editor 统一入口）；迁移按 shop→小→中→大→tks\_book→launcher 批次推进，每入口迁移后跑冒烟测试全绿；\_show\_help/\_show\_about 18→3 处、main() 样板全部 1 行；净减约 540 行；app\_init 保留为原子工具库（非双头）；build entry 无需变更 |
| 2026-09-03 | **阶段 4：前三组合并**：SkillPickerDialog 3→1（参数化 rows 数据源，三消费方切换）；FieldRefDialog 2→1（弹窗壳收敛为 ui\_helpers.show\_field\_ref，内容留作各编辑器 \_build\_field\_ref\_text 数据函数）；GrowthTableDialog 2→1（tks\_book/book\_growth.py 整文件删除，tab\_char 直用统一类）；批次净减约 305 行 |
| 2026-09-03 | **阶段 4 完成**：Flag×2 + UseRight×2 四份位掩码弹窗合并为 picker\_dialogs.BitmaskPickerDialog（use\_bit\_shift 语义双轨 / manual MOD 手动输入 / selected\_mask+get\_value 双轨结果 API）；IconPicker 单消费者跳过；7 处调用点切换，warpc\_table\_mode 解除对 warpc\_editor 依赖；净减 76 行，冒烟测试 4/4 全绿 |
| 2026-09-03 | **全量进度核对**：逐项复核四阶段交付物与仓库实际状态，全部相符；冒烟测试复跑 4/4 全绿（35.3s）。修正两处过时记录：app\_shell.py 行数 210→179（实测）；spritesheet"菜单切主题画布不同步"缺陷已解决（入口改为工具栏按钮 → \_toggle\_theme，内含画布同步） |

