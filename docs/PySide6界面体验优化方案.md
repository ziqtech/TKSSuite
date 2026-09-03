# PySide6 界面体验优化方案

> 创建日期：2026-09-04
> 状态：**P0 已完成（2026-09-04）**，P1~P4 未开始
> 前置文档：《PySide6样式体系整改方案.md》（四阶段已完成）——本方案是其续篇
> 结论：四阶段解决了"样式难维护"；本方案解决"体验不够好"——设计体系补全（排版令牌/图标/动效）、交互安全网（退出保护/脏标记/校验）、数据量增长后的列表能力。

***

## 一、背景与目标

《PySide6样式体系整改方案》四阶段（冒烟测试 / token 化 / 样板收敛 / 对话框去重）已全部完成，颜色单一事实来源、18 入口样板收敛、对话框去重均已落地。2026-09-04 的全量 UI 体检发现，"可维护"与"好用、好看"是两个维度，当前短板集中在：

| # | 缺口 | 直接后果 |
| - | --- | ------ |
| 1 | 设计体系只 token 化了**颜色**，排版（字号/圆角/间距/字体族）、图标、动效三个维度空白 | 排版数值散落难统一；emoji 图标基线不齐、不能随主题换色；全项目零动效质感生硬 |
| 2 | 编辑器**交互安全网**有真实数据丢失缺口 | spritesheet 误关窗口全丢；脏状态无标题栏标记；数值输入静默钳制/归零 |
| 3 | 数据量增长后的**列表操作能力**几乎为零 | 表格全家族无排序/过滤/右键菜单/复制/列宽记忆；Ctrl+F 全项目仅 1 家；最近文件 0 处 |

体检中确认**不是问题**、本方案不动的：自适应表格的列宽策略（水位填充+用户拖宽优先）、EditorComboBox 弹层与滚轮免疫、DWM 标题栏全局过滤器、防递归三态表头全选、原子写入、简繁双向搜索（zhconv）、启动器初始几何与居中逻辑。全窗主题切换 crossfade **明确不做**（Qt Widgets 下成本高收益低）。

***

## 二、现状基线数据（2026-09-04 实测）

### 2.1 槽位值重复度（P1 的核心依据）

`theme_tokens.SLOTS` 共 484 个槽位，**仅 222 个唯一值，54% 槽位值完全重复**：

| 值（四元组） | 出现次数 | 实际语义 |
| ---------- | ------ | ------- |
| `('#10a37f','#10a37f','#478cbf','#478cbf')` | 40 处 | accent 主色 |
| `('#ececec','#2d2d2d','#e0e4eb','#2d2d2d')` | 32 处 | text primary |
| `('1px solid #444444',…)` 边框两组 | 33 处 | border regular / border inset |
| `('2px solid #10a37f',…)` | 8 处 | 选中强调边框 |
| `('#5a5a5a','#b6b6c4','#505a74','#b6b6c4')` | 7 处 | border hover |

原方案遗留任务"槽位语义化重命名"按 484 个逐个改名；实测应改为**先按值去重合并（484→222），再对高频组语义命名**——改一个强调色从"找准 40 个槽位"变成"改 1 处"。

### 2.2 排版数值分布（QSS 模板实测）

| 维度 | 现状 | 问题 |
| --- | --- | --- |
| font-size | 7 种（10/11/12/13/14/18px + 9pt） | **px/pt 混用**（9pt 在 `QTextEdit[class="MonoText"]`）；正常设计系统 4~5 档 |
| border-radius | 9 种 | 主体为 3/6/8/10 四档，5/7 是 8-1 内缩派生值 |
| padding | 45 种组合 | 无间距标尺 |
| min-height | 9 种 | 控件高度不统一 |
| font-family | 5 种写法 | monospace 就有 3 种变体写法 |

### 2.3 交互安全网覆盖情况

| 能力 | 覆盖 | 缺口 |
| --- | --- | --- |
| closeEvent dirty 检查 | 11/16 编辑器有（mat 最完善，warpc 三选提示） | **spritesheet 无 `_dirty` 无 closeEvent（最大单点风险）**；shop 有完整 dirty 标志但无 closeEvent 消费；gxp/grp 无 dirty 概念 |
| setWindowModified（标题栏 * 标记） | **0 处** | 脏状态仅 kon 状态文本"[已修改]"、item 状态栏一句话 |
| QUndoStack/QUndoCommand | **0 处** | 仅 mat 快照栈（mat_editor.py:227,621-630）与 warpc changeset 栈（warpc_table_mode.py:1000-1040）两条自研路线 |
| 数值输入校验 | 无 QIntValidator | item_editor.py:1205-1212 / skill_editor.py:1361-1366：越界**静默钳制** ±32767、ValueError **静默归零** |
| 大文件加载反馈 | QProgressDialog **0 处** | `QApplication.processEvents()` 假异步 **21 处**（act 2475/3276、gxp 448/474/491、kon 736/1256、jvg 1876/2041/2123/2904、grp 876/908、mat 3083、tks_book 212、tab_map 87/115、shop 581、warpc 1577/1595）；mat_threads.py 双 QThread 是唯一正例 |

### 2.4 列表操作能力（AdaptiveTableWidget 家族）

| 能力 | 状态 |
| --- | --- |
| 列宽自适应 | ✅ 优秀（水位填充 + 用户拖宽优先） |
| 列宽记忆 / 点表头排序 / 过滤搜索 / 右键菜单 / Ctrl+C 复制 / CSV 导出 | ❌ 全部未实现（右键菜单 `customContextMenuRequested` 0 处） |
| Ctrl+F | 仅 tkt_editor 一家（tkt_editor.py:947） |
| 最近文件菜单 | 0 处（shared_state.py 已有 QSettings 跨编辑器持久化基建可复用） |
| 窗口几何/分割器/列宽持久化 | 全部会话级，重启即丢 |

### 2.5 其他实测

- 状态栏：真 QStatusBar 仅 6/18（configs/font/grp/gxp/jvg/mat），其余 QLabel 混工具栏。
- QSS 之外色值孤岛 ~9 处：ui_helpers.py:17-20 状态色 4 常量、custom_music_dialog.py:52-53（#2f80ed/#888888）、mod_list.py:239/252（220,50,50）、custom_avatar_dialog.py:318/320/348/353（裁剪控件整块）、**tab_widget.py:53-56 `_BORDER_COLORS` 四组 hex（自称"就近维护"，改主题必漏）**、packer/merger/meta 的 `#888` 斜体占位 ×3。
- emoji 图标：svg 目录仅 8 个文件；`theme_manager.svg_icon()` API 存在但无工具栏调用；main_window.py:297 设 `setIconSize(QSize(20,20))` 却无 QAction 图标。
- 动效：全项目 0 个 QPropertyAnimation。
- statusTip/whatsThis：0 处；tooltip ~28 处覆盖较好。
- 色值对比度：avatar 裁剪提示文字 (100,100,100) on (30,30,30) ≈ 2.4:1，低于 WCAG 4.5:1。
- `themed_messagebox` 只有单 OK 变体 → 确认场景全部裸调 QMessageBox.question（main_window.py:261、music:737、packer:398、save_mgr:384 等），按钮文案与标题栏主题双双分裂。

***

## 三、优化方案（五批次）

依赖关系：批次间相互独立可穿插；**P0 强烈建议最先做**（纯数据丢失风险，每项 10~50 行）；P1 有冒烟测试渲染等价对比兜底；P2/P3/P4 可按需推进。每项完成后跑冒烟测试（`python -m unittest tests.test_editor_smoke -v`）。

### P0：交互安全网（数据丢失风险，每项 10~50 行）

**目标**：消除已知的误操作丢数据路径；脏状态全编辑器可见。

1. [x] spritesheet_editor 补 `_dirty` 跟踪 + closeEvent 未保存确认（全项目最大单点风险）
2. [x] shop_editor closeEvent 接入已有 `_dirty` 标志（dirty 在 275/597/862/883/896/931/1073 处置位但无人消费，`ui_helpers.confirm_close` 现成可用）
3. [x] gxp_editor 补 dirty 概念 + closeEvent（font_editor 为导出式模型风险低，可豁免并注释）
4. [x] grp_editor closeEvent 在停音频之外补 dirty 检查
5. [x] `EditorMainWindow` 基类统一脏标记：提供 `set_dirty(bool)` 钩子内部调 `setWindowModified`，标题模板加 `[*]` 占位；18 个子编辑器统一接入（替代 kon 的文本"[已修改]"方案）
6. [x] 数值输入校验：item_editor.py:1205-1212 / skill_editor.py:1361-1366 的 int() 手工转换换 QIntValidator + 越界即时反馈；QSS 模板加一条 `QLineEdit[invalid="true"] { border-color: 警示红 }`（槽位值入 theme_tokens）

**验收**：人工抽查 spritesheet/shop/gxp/grp 改动后关窗必弹确认；item 输入非法值有红框不再静默归零；冒烟测试全绿。

### P1：设计体系 2.0（token 升级）

**目标**：484 槽位收敛为 ~222 语义槽位；改一个语义色只动一处；排版数值开始有令牌。

1. [ ] 写一次性脚本对 `SLOTS` 按值分组，相同四元组值合并为单一槽位（484 → 222）；模板 base.qss.tpl 中同名槽位批量替换
2. [ ] 高频组语义命名（accent / text_primary / border_regular / border_inset / border_hover / surface 系…），其余低频组暂保留编号名渐进改名
3. [ ] 渲染等价验证：复用阶段 1 增补的解析级对比（4 主题 × 全规则：选择器→属性→值逐一相等），通过后合入
4. [ ] font-family 统一：5 种写法 → 2 种（UI 体 `'Segoe UI','Microsoft YaHei',sans-serif` / 等宽体 `'Consolas','Courier New',monospace`）
5. [ ] `QTextEdit[class="MonoText"]` 的 9pt 改 px（与全模板口径统一）
6. [ ] （渐进项）字号/圆角引入排版槽位（`{{fs_body}}`/`{{radius_md}}`…），值集中到 theme_tokens 新增 TYPOGRAPHY/RADIUS 表；先做 13px 正文与 8px 主圆角两个高频值，其余随日常迭代迁入

**验收**：SLOTS 数量减半且高频组有语义名；渲染等价对比通过；冒烟测试全绿；改 accent 色验证只动 1 处槽位全项目生效。

### P2：列表操作能力（数据量增长前做）

**目标**：表格家族获得排序/过滤/复制/记忆四件套；主工作流列表可搜索；布局状态可持久化。

1. [ ] AdaptiveTableWidget 内置点表头排序（`setSortingEnabled` + 数值列感知）
2. [ ] AdaptiveTableWidget 内置右键菜单（`customContextMenuRequested`：复制单元格/整行/导出选中为 CSV）
3. [ ] AdaptiveTableWidget 列宽持久化：按 `objectName+列号` 存 QSettings，`reset_column_layout` 清除
4. [ ] mod_list.py 补搜索框 + 分类过滤（主工作流列表，模组量大后第一痛点）
5. [ ] 搜索交互全量对齐：统一"textChanged 增量 + Ctrl+F 聚焦 + `setClearButtonEnabled(True)`"；`setFixedWidth(160)` 七处（skill:808/act:1803/warpc:671,680/tkt:989/wardata:667/kon:358/warpc_table_mode:766）改 `setMinimumWidth(160)`
6. [ ] 窗口几何 + QSplitter 状态持久化：EditorMainWindow 基类 closeEvent 存 QSettings（launcher main_window 一并接入，其初始几何逻辑保留作首次默认值）
7. [ ] 最近文件菜单：基于 shared_state.py 的 QSettings 基建加"最近 5 个 TKS 目录"子菜单（EditorMainWindow 基类内置，子类零成本继承）
8. [ ] log_console.py：滚动条不在底部时暂停 autoscroll（现行 :124 无条件 `ensureCursorVisible` 会拽回底部）；加导出日志按钮与行数上限

**验收**：冒烟测试全绿；mod 列表可搜索过滤排序；重启后窗口几何/列宽保留；任一表格右键可复制整行。

### P3：反馈与一致性（跨编辑器肌肉记忆）

**目标**：弹窗/状态栏/长任务反馈全项目统一；散落色值孤岛清零。

1. [ ] `themed_messagebox` 增加 `question()` 变体（Yes/No/Cancel），替换全部裸 QMessageBox.question 调用点（main_window:261、music:737、packer:398、save_mgr:384 等）
2. [ ] `EditorMainWindow` 基类内置状态栏（三段式：记录数 | 当前文件 | 修改状态），6/18 的 QStatusBar 覆盖率提升为全量；菜单动作补 statusTip
3. [ ] 长任务线程化：mat_threads.py 的 QThread 模式推广到 jvg/grp/tkt/wardata 加载；启动器 packer/merger/splitter/save_manager 四对话框执行按钮移入 QThread（最低限度先加 QProgressDialog 模态+取消）；清理 21 处 processEvents 假异步
4. [ ] QUndoStack 共享 mixin：以 warpc changeset 栈（warpc_table_mode.py:1000-1040）为蓝本抽共享实现，先铺 item/skill/kon 表单型编辑器
5. [ ] 表单提交模型收敛（短期）："✅ 应用"模型补"切换记录时若有未应用改动则提示"（warpc 三选提示有现成逻辑）；长期向 warpc 草稿模型收敛
6. [ ] QSS 外色值孤岛收编（~9 处 → theme_tokens 业务色板）：tab_widget.py:53-56 `_BORDER_COLORS`（改为从 theme_tokens 派生或迁入槽位）、ui_helpers.py:17-20 状态色、custom_music_dialog.py:52-53、mod_list.py:239/252、packer/merger/meta 的 `#888` 占位；avatar 裁剪控件整块记为画布类豁免但修对比度（见 P4）
7. [ ] 细节统一：帮助文案与 UI 对齐（main_window.py:225 提到已删除的"设置"菜单）；省略号三种写法（`...`/`…`）统一为 `…`；packer/merger/meta 缩略图 120 vs 96、按钮 56 vs 60 统一；save_editor 菜单 emoji 与其他编辑器口径统一（若 P4 图标落地则一并替换）
8. [ ] 主题切换按钮位置统一（多数在工具栏右侧，mat 在预览工具栏、tks_book 在标签页角落——统一到工具栏右侧或全部走菜单）

**验收**：冒烟测试全绿；grep `QMessageBox.question` 在业务文件 0 处；grep QSS 外裸色值仅剩豁免注释项。

### P4：视觉打磨与可访问性

**目标**：摆脱 emoji 图标；两处关键动效；键盘焦点可见；对比度达标。

1. [ ] SVG 图标库：补 ~20 个 16×16 线性图标（打开/保存/新建/撤销/搜索/刷新/启动/主题/导出/删除/新增/齿轮/日志/帮助…），深浅主题成对准备（沿用 down-arrow.svg / down-arrow-light.svg 先例）或用可着色方案；优先替换启动器工具栏与各编辑器工具行高频按钮
2. [ ] GameOverlay 淡入淡出：QPropertyAnimation windowOpacity 0→1，250ms
3. [ ] ModeCard hover 光晕过渡：QVariantAnimation 插值 hover 强度（150ms），消除 24→68 alpha 突变
4. [ ] ModeCard 键盘焦点环：paintEvent 补 `hasFocus()` 时 2px accent 描边（StrongFocus 已设但视觉不可见）
5. [ ] avatar 裁剪控件提示文字对比度修复（(100,100,100) on (30,30,30) ≈ 2.4:1 → 提亮至 ≥4.5:1）
6. [ ] 主题菜单加色块图标（四主题各自 accent 色的小色块，切换前有视觉预期）
7. [ ] 主题切换按钮位置统一（若 P3-8 未做则并入此处）

**验收**：冒烟测试全绿；启动器工具栏无 emoji 图标；Tab 键可在模式卡片间可见地移动焦点；人工 4 主题抽查截图。

### 可选附加项（独立于五批次，可随时做）

- [ ] 排版槽位全量化（P1-6 的完整版：字号 7 档归并 4~5 档、圆角 9 种归并 3 档、padding 45 种归并间距标尺）
- [ ] Empty state 引导页：未加载 TKS 目录时左侧列表区显示居中引导（图标 + "Ctrl+O 打开数据"），替代两个空灰框
- [ ] 图像预览对话框补缩放百分比显示与 1:1 按钮
- [ ] custom_music_dialog 操作列六按钮收敛为"播放 + ⋯更多"两级或悬浮工具条（90px 列宽下必然溢出）
- [ ] mode_card.py 像素字号集中为模块级常量（13/14/11/10 px 散在 paintEvent），后续可随系统字体缩放
- [ ] combo_box.py 弹层总高 `row_h * rows + 10` 的脆弱耦合（QSS 改边框/边距后错位）改为实测 sizeHint

***

## 四、执行进度

> 状态图例：`未开始` / `进行中` / `已完成` / `跳过(原因)`。每完成一项更新此表和文末变更记录。

### 总览

| 批次 | 状态 | 开始日期 | 完成日期 |
| --- | --- | --- | --- |
| P0：交互安全网 | **已完成** | 2026-09-04 | 2026-09-04 |
| P1：设计体系 2.0 | 未开始 |  |  |
| P2：列表操作能力 | 未开始 |  |  |
| P3：反馈与一致性 | 未开始 |  |  |
| P4：视觉打磨与可访问性 | 未开始 |  |  |

### P0 清单

- [x] spritesheet 退出保护
- [x] shop closeEvent 接入 dirty
- [x] gxp dirty + closeEvent
- [x] grp closeEvent 补 dirty
- [x] 基类 setWindowModified + 标题 `[*]`
- [x] 数值校验 QIntValidator + invalid 红框

### P1 清单

- [ ] 槽位值去重合并（484 → 222）
- [ ] 高频组语义命名
- [ ] 渲染等价验证
- [ ] font-family 统一 2 种
- [ ] 9pt → px
- [ ] （渐进）排版槽位首批（fs_body / radius_md）

### P2 清单

- [ ] AdaptiveTable 排序
- [ ] AdaptiveTable 右键菜单 + 复制/导出
- [ ] AdaptiveTable 列宽持久化
- [ ] mod_list 搜索 + 分类过滤
- [ ] 搜索交互全量对齐（增量 + Ctrl+F + 清除按钮）
- [ ] 窗口几何/Splitter 持久化
- [ ] 最近文件菜单
- [ ] 日志控制台 autoscroll 智能暂停 + 导出 + 行数上限

### P3 清单

- [ ] themed_messagebox.question 变体 + 替换裸调用
- [ ] 基类状态栏 + statusTip
- [ ] 长任务 QThread 化（编辑器加载 + 四对话框）
- [ ] QUndoStack 共享 mixin
- [ ] 表单提交模型短期收敛
- [ ] QSS 外色值孤岛收编（~9 处）
- [ ] 细节统一（帮助文案/省略号/对话框尺寸/emoji 口径）
- [ ] 主题切换按钮位置统一

### P4 清单

- [ ] SVG 图标库 ~20 个 + 高频按钮替换
- [ ] GameOverlay 淡入淡出
- [ ] ModeCard 光晕过渡动画
- [ ] ModeCard 焦点环
- [ ] avatar 裁剪对比度修复
- [ ] 主题菜单色块图标

***

## 五、执行纪律（后续会话按此操作）

1. **动手前**：读本方案"四、执行进度"确认下一步；跑一遍冒烟测试确认基线绿（`python -m unittest tests.test_editor_smoke -v`）。
2. **粒度**：一个任务/一个文件一个 commit；commit message 标注批次（如 `feat(P0): spritesheet 补退出保护`）。
3. **每步之后**：跑冒烟测试；更新 §四 进度表和文末变更记录。
4. **口径复测**：每完成一个批次，用 §二 的同口径复测并更新数字：
   - 槽位数与唯一值数：`python -c "from editor_utils import theme_tokens as t; print(len(t.SLOTS), len(set(t.SLOTS.values())))"`
   - 裸 QMessageBox.question：`grep -rn "QMessageBox.question" --include="*.py" . | grep -v ui_helpers | wc -l`
   - processEvents 残留：`grep -rn "processEvents" --include="*.py" . | wc -l`
   - setWindowModified 覆盖：`grep -rl "setWindowModified" --include="*.py" . | wc -l`
5. **遇到方案未覆盖的情况**：小决策就地处理并在"变更记录"补一行；大决策（影响验收口径）先问用户。
6. **P1 专项纪律**：槽位合并与改名必须以"渲染等价验证通过"为合入前提，验证脚本失败则回退补齐，禁止跳过验证直接改。

***

## 六、变更记录

| 日期 | 内容 |
| --- | --- |
| 2026-09-04 | 方案定稿：全量 UI 体检完成（样式整改四阶段之后的增量分析），五批次任务清单建立；实测基线数据录入（槽位 484/222/54% 重复、字号 7 档、圆角 9 种、padding 45 种、setWindowModified 0 处、QUndoStack 0 处、Ctrl+F 1 家、最近文件 0 处、QSS 外色值孤岛 ~9 处、状态栏 6/18、processEvents 21 处） |
| 2026-09-04 | **P0 完成（6/6）**：spritesheet/shop/gxp/grp 四编辑器补退出保护（confirm_close + 脏标志全点位接入）；基类 `_dirty` 以 **property** 承载（实现与原设计差异：既有 `self._dirty = …` 赋值自动同步 `setWindowModified`，13 个编辑器零逐个接入；mat 经 MapDataManager dirty property + `_script_dirty` property 双路联动，configs 因对比式脏检查用 1.5s 低频轮询）；`format_title` 加 `[*]` 占位（全编辑器标题自动获得修改标记位，kon 的状态文本"[已修改]"已移除）；item/skill 数值字段 QIntValidator(-32768,32767) + `ui_helpers.mark_invalid` 红框反馈（新槽位 `bd_error`，越界仍钳制保数据但不再静默）。冒烟测试 4/4 全绿（28.6s）；离屏验证：4 主题渲染无残留槽位、`_dirty`/`set_dirty`/标题`[*]`/mark_invalid 机制全过 |
