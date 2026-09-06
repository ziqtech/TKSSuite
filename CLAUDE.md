# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# 注意

进行代码检索/分析/编码的过程，必须遵循 “严谨仔细，禁止臆测” 这个核心规则
思考和输出内容时必须使用中文，不能使用英文

# Git 提交规范

主题行格式：`类型: 纯中文描述`，详细内容放正文。

1. **类型前缀必须保留**：`feat` / `fix` / `docs` / `style` / `refactor` / `perf` / `test` / `chore`，后跟英文冒号加空格。这是提交规范的核心部分，任何情况下不得省略。
2. **描述部分必须纯中文**：不得包含英文字母、阿拉伯数字与符号；数字用汉字表示（如“十五个”而非“15 个”）；不放任务编号（如 T6）、括号补充与破折号引出的细节。
3. **详细内容放正文**：正文用中文描述改动动机、范围与验证方式；必要的技术名词（如 ordered-set、task_runner、文件路径）可保留英文原文。
4. **类型选择**：新功能用 feat，缺陷修复用 fix，仅文档变更用 docs，不改行为的重构与清理用 refactor，构建、依赖、仓库卫生等杂务用 chore。
5. **一任务一提交**：提交信息与改动内容一一对应，便于单独回滚。

示例：

- ❌ 主题行：`chore: T6 仓库卫生——忽略运行时验证日志、注释 ordered-set 依赖、修正 utils README 过期路径`
- ✅ 主题行：`chore: 优化仓库卫生`
- ✅ 正文：`忽略运行时验证日志，为构建依赖中的 ordered-set 补注释说明，修正 utils README 的过期路径。`