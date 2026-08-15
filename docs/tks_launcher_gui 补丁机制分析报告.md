# tks_launcher_gui 补丁机制分析报告

> 分析对象:`tks_launcher_gui`(补丁引擎、loader、worker、.tkspatch 体系)
> 逆向参照:`反编译产物/decompile`(原版游戏 IDA 反编译)
> 报告日期:2026-08-15
> **核心结论**:补丁机制完备,与"召唤数量扩展"目标高度匹配;但 cave 内存存在 **1024 字节硬上限已被超出 50%** 的严重瓶颈;`.tkspatchpak` 整合在现有数据模型上有天然承载基础,但必须先解决 cave 容量问题。

---

## 一、开发/调试友好度评估

### 1.1 优点(便于开发与调试)

#### 1) `.tkspatch` 是 ZIP 容器,patch.json + cave_code 内嵌,工程化清晰

`core/tkspatch_loader.py` 实现完整(374 行):

```python:1:26:tkspatch_loader.py
"""
.tkspatch 外置补丁加载器

文件格式: ZIP 容器, 扩展名 .tkspatch (旧版散装 JSON 兼容)
每个文件定义一个完整的补丁 (含 cave 机器码), 可独立分发替换。

新版 ZIP 格式 (类似 .tksmod):
  patch.json  — 补丁清单 (原散装 JSON 的全部字段)
  script.py   — type=script 时内嵌的外部脚本源码

旧版散装 JSON 仍可加载, 用于向后兼容。

优先级规则:
  patches/ 目录下的 .tkspatch 文件 (按 id) 覆盖 tks_patches.json 中同 id 的补丁。
  若 patches/ 目录不存在或为空, 完全回退到 tks_patches.json (向后兼容)。

Cave 机器码字段:
  cave_code: 空格分隔的十六进制字符串 (与 pattern 格式一致)
  例: "50 51 0F BF 45 FA 66 85 C0 ..."

外部脚本字段:
  script_file: 散装 JSON 指向 patches/_scripts 下的 .py; ZIP 型直接内嵌为 script.py

Cave hook 定位:
  hook_offset: hook 点相对 hook_pattern 起点的字节偏移 (默认 0)
"""
```

`.tkspatch` 单文件分发 = 1 个完整原子单元(JSON + 内嵌 cave 机器码),无需额外资源,**复制即可发布**。

#### 2) Patch 类型系统完整,覆盖召唤补丁需要的所有机制

`core/patch_engine.py` 已实现的类型:

| 类型 | 适用场景 | 召唤补丁适用点 |
|---|---|---|
| `patch_bytes` | 模式扫描 + 单字节替换 | **#5/#6 imm 常量改写**(`444FD4` 的 `+2`、`445564` 的 `≥6`) |
| `cave_hook` | E8 call 钩子 + 外置 cave 代码 | **#1/#2/#3/#4 满检/分配/清除 4 处** |
| `patch_imm32` | value_scan / pattern_scan 改 imm32 | 不直接需要 |
| `patch_summon_table` | 召唤表 + 多随机 cave(已有完整实现) | **可复用现成机制** |
| `script` | Python 脚本(完整 PatchContext) | 可选,便于调试输出 |
| `patch_warpc_addr` | WarPC 引用重定位 | #1 槽位数组迁 WarPC 必须 |

#### 3) Cave 引擎成熟,占位符自动重定位

```python:737:752:patch_engine.py
def build_cave_template(name: str, warpc_base: int, log_func=None,
                        idx_cap: Optional[int] = None,
                        external_code: Optional[bytes] = None) -> Optional[bytes]:
    log = log_func or (lambda x: None)

    # 外置 cave 代码优先 (.tkspatch 文件提供)
    if external_code is not None:
        c = bytearray(external_code)
        replace_addr_in_bytes(c, _WARPC_BASE_PLACEHOLDER, warpc_base)
```

- `0x757F08` 占位符 `replace_addr_in_bytes` 运行时重定位 → cave 代码**完全位置无关**,可被分配到任何 cave 地址
- `0x52414E44`(RAND)占位符也支持(见 `summon_table` cave)
- idx_cap 自动调整 → WarPC 扩容后无需改 cave 字节

#### 4) 已有同源先例可参照,降低开发难度

`team_member_routing.tkspatch`(158 字节 cave)、`weapon_cause_mask_hook.tkspatch`(98 字节)、`duel_counter_self_fix.tkspatch` 三个 cave 的复杂度与"召唤扩展"的子_431094 cave 改造相当,模板与注释完备:

```c-style
# Cave 模板: 主角替换 — TeamMember 脚本路由
# 逆向依据: sub_40DA00 @0x40DA1C (TeamMember 入口条件判断)
# hook: cmp word [ebp+8], 0; jnz 0x40DA8D (7字节) -> E8 rel32 + 2xNOP
```

每条 cave 注释都标明了:**逆向函数地址、hook 点原指令字节、cave 末尾 ret 目标、寄存器保存约定**。召唤补丁可严格仿写。

#### 5) 模式扫描 + 特征码回退,fail-safe 链完整

```python:2219:2236:patch_engine.py
if defn.hook_expect_count > 0 and len(hh) != defn.hook_expect_count:
    # 模式匹配失败 — 尝试 fallback_rva 回退定位
    if len(hh) == 0 and defn.fallback_rva > 0:
        # fallback_rva 是相对于基址的偏移, 转为 code_buf 内偏移
        fb_hook = defn.fallback_rva - 0x1000  # RVA -> code_buf offset
        fb_off = fb_hook - defn.hook_offset
        if 0 <= fb_off < len(code_buf) - defn.hook_size:
            hh = [fb_off]
            log(f"  {tag}: 模式无匹配, 使用 fallback_rva 0x{defn.fallback_rva:X} (offset 0x{fb_hook:X})")
```

+ `hook_conflict_action=override`(默认)→ 启动器优先级最高,天然兼容孝谈三国3终极版等第三方 MOD(`.test`/`.Silvana` 段):

```python:2238:2246:patch_engine.py
# Hook 冲突检测: 检查 hook 点是否已被占用
if hh and check_hook_conflict(code_buf, hh[0] + defn.hook_offset):
    action = defn.hook_conflict_action
    if action == "override":
        log(f"  {tag}: Hook 点已被占用, 启动器优先级最高 → 覆盖")
```

#### 6) 调试可见性良好

每个补丁应用都打 log(从 patch_engine.py 各处 `log(...)` 调用可见),`patcher_worker.py` 通过 Signal 把日志推 UI:

```python:500:511:patcher_worker.py
# 分配 cave 内存 + 应用配置补丁 (共用同一句柄)
self.overlay_update.emit("正在应用内存补丁...", False)
hp = _OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, target_pid)
cave_addr = 0
if hp:
    ca = _VirtualAllocEx(hp, None, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if ca:
        cave_addr = ctypes.cast(ca, ctypes.c_void_p).value or 0
if cave_addr:
    self._log(f"  Cave 内存: 0x{cave_addr:08X} (1024 bytes)")
```

任何 hook 失败、cave 写入失败、模式不匹配都会显式打印,调试无需额外工具。

---

### 1.2 缺点(开发障碍与风险)

#### ❌ 阻塞级缺陷 1:**cave 内存硬上限 1024 字节,实际已超出 50%**

`patcher_worker.py` 第 505 行:

```python
ca = _VirtualAllocEx(hp, None, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
```

**实测 16 个 cave 用户已累加占用 1526 字节**(已实测):

```
war_mustchar_fallback.tkspatch      offset=1472  end=1526
skill_menu_cap.tkspatch             offset=1408  end=1429
exp_lock.tkspatch                   offset=1344  end=1372
team_member_routing.tkspatch        offset=1152  end=1310
...
cave 内存大小 = 1024  ← 超额 502 字节
```

**这意味着当前启动器一旦用户同时启用所有相关补丁(默认勾选),cave 写入实际上在 1024 字节之后会被覆盖到下一个 cave 代码**,引发未定义行为。**召唤补丁新增 4~6 个 cave 后只会雪上加霜**(参见后文 cave 用量估算)。

> 注:此问题在 `patches/` 下 16 个 cave 用户中已有累积,不是召唤补丁引入的,但必须在整合 `.tkspatchpak` 前解决。

#### ❌ 阻塞级缺陷 2:**cave_offset 是静态写死常量,补丁组合无法动态布局**

```python:1020:1022:patch_engine.py
ct = cave_addr + defn.cave_offset
write_pm(h_proc, ct, cd)
log(f"  Cave 写入: 0x{ct:08X} ({len(cd)} bytes, 模板={defn.cave_template})")
```

cave_offset 由补丁作者**手工分配**(`patches/*.tkspatch` 中的 `cave_offset` 字段)。没有 linker、没有 collision check、没有按 size 排序自动布局。一旦新增补丁,极容易与已有 cave 偏移重叠。

#### ⚠ 风险 3:**cave 整体在单进程空间,补丁互相干扰不可见**

所有 cave 共享同一连续 1024 字节(单 `VirtualAllocEx` 分配)。cave 内任意 patch_bytes/patch_imm32 也会落到 cave 范围(若 `patch_imm32` 的 value 碰巧命中 0x757F08 占位符)——这是 cave 引擎的设计,不是 bug,但意味着 cave 容量规划必须严格。

#### ⚠ 风险 4:**cave_hook 仅支持单 cave 入口模式,无法表达多入口共享 cave**

召唤补丁 #3(sub_431094)需要循环找空槽,**不能简单复用 sub_431094 既有调用约定**,必须把循环体放进 cave 并由 cave 末尾 `ret` 回到原函数后续指令。

参考 `summon_table.tkspatch` 中的 222/251 cave 设计(共享入口):

```python:336:364:patch_engine.py
# 合并三段: entry_222(entry8) + entry_251(entry9) + shared(随机选 cand, 写[ebp-2])
# entry_222/entry_251 仅设 entry 常数后 jmp shared; shared 内 rand 选 cand -> [ebp-2]
CAVE_SUMMON_RANDOM_222_251 = bytes([
    # entry_222 @0  (hook 0x444C9C, ret->0x444CA2 jmp 0x444CCF)
    0x53,                                              # 0  push ebx
    0xBB,0x08,0x00,0x00,0x00,                          # 1  mov ebx, 8            (entry 8)
    0xEB,0x08,                                         # 6  jmp shared(16)
    # entry_251 @8  (hook 0x444CB3, ret->0x444CB8 NOP->0x444CCF)
    0x53,                                              # 8  push ebx
    0xBB,0x09,0x00,0x00,0x00,                          # 9  mov ebx, 9            (entry 9)
    0xEB,0x00,                                         # 14 jmp shared(16)
```

**这种"多 hook 共享单一 cave"模式可仿写到 4 个 cave**:每个 hook 都 `push ebx` 暂存入口常量,然后 jmp shared。

#### ⚠ 风险 5:**代码段扫描窗口限制为 3MB(对原版够,对 MOD 不够)**

```python:389:391:patcher_worker.py
code_size = mod_size - 0x1000 if mod_size > 0x1000 else 0
if code_size > 0x300000:
    code_size = 0x300000
```

但已有 `apply_patch_extra_section`(MOD 额外段)兜底,所以不阻塞。

#### ⚠ 风险 6:**cave 偏移硬编码对 cave 大小变化不感知**

`duel_counter_self_fix.tkspatch` 的 hook_size=8(覆盖 sub_4434BC 前 8 字节序言),如果原版序言字节数变化,会失败。召唤补丁的 hook 点字节数也已固化在注释里:

```python:482:518:patch_engine.py
# hook 使用 E8 (call) 会在栈上多压一个返回地址,
# 因此 cave 开头先 pop edx 移除多余返回地址并暂存,
# 使栈布局还原为原始函数期望的 [ebp+4]=调用者返回地址
```

召唤补丁 #1/#2/#3 同样需要这个约定(hook_size=5 / 7 / 9,cave 开头 pop eax 丢弃 call 返回地址)。

---

## 二、分发可行性评估

### 2.1 优点(便于分发)

#### 1) 单文件 = 单补丁,天然独立分发

`.tkspatch` ZIP 容器含 `patch.json`(人类可读)+ `cave_code`(空格分隔十六进制),**完全自包含**——不需要附 JSON 配置文件、cave 机器码文件、Python 脚本路径等外部资源。

发布者只需把 `.tkspatch` 文件扔到 `patches/` 目录,启动器自动加载。

#### 2) `patches/` 覆盖优先级策略已就绪

```python:331:364:tkspatch_loader.py
def merge_patches(base_config: PatchConfig, external_patches: List[PatchDef],
                  log_func=None) -> PatchConfig:
    """将外置补丁合并到基础配置。
    规则:
      - 外置补丁 id 与基础配置重复 → 覆盖 (外置优先)
      - 外置补丁 id 不存在于基础配置 → 追加
      - 保持基础配置中的顺序 (覆盖时位置不变), 新增项追加到末尾
    """
```

外置 `.tkspatch` 优先于 `tks_patches.json`,**便于第三方维护者分发补丁升级**(直接覆盖同名 id 的内部版本)。

#### 3) 变量系统唯一来源 `_variables.tkspatch`,分发可拆配置

```python:226:269:tkspatch_loader.py
def load_variables_from_dir(patches_dir: str, log_func=None) -> Dict[str, int]:
    """从 patches/_variables.tkspatch 读取全局变量 (唯一来源)。
```

召唤数量 N 可以作为全局变量分发在 `_variables.tkspatch` 里,cave 用 `{summon_max_count}` 引用,无需硬编码。`resolve_var` 已支持变量解析:

```python:201:214:config_loader.py
def resolve_var(expr: str, variables: Dict[str, int], log_func=None) -> Optional[int]:
    """解析变量引用。strict 模式下未定义变量返回 None"""
    log = log_func or (lambda x: None)
    if expr is None:
        return 0
    if expr.startswith('{') and expr.endswith('}'):
        vn = expr[1:-1]
        if vn in variables:
            return variables[vn]
```

#### 4) JSON 配置覆盖经 MOD 包携带 (`config_overrides`)

```python:1063:1076:patch_engine.py
# Step 0: 读取召唤表 JSON
# 优先使用 MOD 包提供的配置覆盖 (白名单内), 否则回退到 configs/ 目录
if config_override is not None:
    summon = config_override
    log(f"    JSON (MOD 覆盖): {len(summon)} 个键")
else:
    if not defn.json_file or not os.path.isfile(defn.json_file):
        log(f"    [WARN] 召唤表 JSON 不存在: {defn.json_file!r}, 跳过")
        return True
```

召唤补丁若需 JSON 配置(可选,非必需),可直接打包进 `.tksmod` 或 `.tkspatch`。

---

### 2.2 缺点(分发障碍)

#### ⚠ 风险 1:**cave 容量不足,整合后无法塞进单一 `.tkspatchpak`**

cave 容量硬上限 1024 字节,实际已占 1526 字节。如果不先扩容,任何"整合包"都做不到原子分发。

#### ⚠ 风险 2:**cave_offset 手工分配,缺乏自动布局**

分发新 `.tkspatchpak` 时,cave_offset 必须人工避开已有 16 个 cave 用户(64/128/192/256/640/704/800/900/960/1088/1152/1344/1408/1472 等)。如果不做布局工具,容易踩雷。

#### ⚠ 风险 3:**cave 冲突检测仅查 hook 字节,不查 cave 数据**

```python:104:112:patch_engine.py
def check_hook_conflict(code_buf: bytearray, off: int) -> bool:
    """检测 hook 点是否已被其他 MOD 占用
    若目标位置的第一字节已是 E8(call) 或 E9(jmp),
    说明已被其他补丁/MOD hook,存在冲稁。
    """
```

只检测 hook 入口,不检测 cave 区是否被覆盖。

---

## 三、整合成 `.tkspatchpak` 的可行性分析

### 3.1 现有数据模型

`tks_patches.json` → `PatchConfig.patches: List[PatchDef]`(每个 PatchDef 是一个独立原子)。`.tkspatch` ZIP 文件就是 PatchDef 的序列化,`patches/` 目录是 PatchDef 的集合。

**`PatchConfig.patches` 本身就是一个天然的"补丁包"容器**——加一层 group/tag 即可做 `.tkspatchpak`:

```python:54:57:config_loader.py
@dataclass
class PatchConfig:
    variables: Dict[str, int] = field(default_factory=dict)
    patches: List[PatchDef] = field(default_factory=list)
```

### 3.2 `.tkspatchpak` 与 `.tksmodpak` 已有先例

`patcher_worker.py` 已实现 `expand_pak_mods`(`.tksmodpak` 合集展开):

```python:149:156:patcher_worker.py
# 展开启用的 .tksmodpak 合集,将其内含的 .tksmod 加入加载列表
expanded = []
for m in loaded_mods:
    if m.enabled and m.pak_contents:
        self._log(f"  展开合集: {m.name} ({len(m.pak_contents)} 个模组)")
        pak_mods = expand_pak_mods(m.path, log_func=self._log)
        for pm in pak_mods:
            pm.enabled = True
        expanded.extend(pak_mods)
    elif not m.pak_contents:
        expanded.append(m)
```

`.tkspatchpak` 可参照同一模式:**ZIP 内含 N 个 `.tkspatch` 文件 + 1 个 manifest.json**。

### 3.3 `.tkspatchpak` 形态建议

```
battle_summon_expansion.tkspatchpak    (ZIP 容器)
├── manifest.json                     # 版本、依赖、作者、cave_offset 计划
├── init_slots.tkspatch               # #1 sub_436BD4 槽位初始化
├── check_full.tkspatch               # #2 sub_444BB0 满槽检查
├── alloc_slot.tkspatch               # #3 sub_431094 槽位分配 (核心)
├── clear_slot.tkspatch               # #4 sub_43C734 槽位清除
├── noise_index.tkspatch              # #5 sub_444FD4 「囔嚷」+2 → +N
├── noise_cap.tkspatch                # #6 sub_445564 ≥6 → 8−N
└── _variables.tkspatch               # summon_max_count = 4 (可被用户覆盖)
```

`manifest.json` 描述:
- `cave_layout`:每个 patch 的 `cave_offset`(集中分配,避免冲突)
- `requires_tkspatch`:依赖的其它 `.tkspatch`(如 `war_mustchar_fallback`)
- `default_checked` / `user_selectable`

### 3.4 cave 容量估算

按已有先例估算召唤 6 个补丁的 cave 总字节数(基于反汇编 + 现有 cave 模板复杂度):

| 补丁 | 反汇编函数 | cave 估算(字节) | 备注 |
|---|---|---|---|
| #1 init_slots (sub_436BD4) | L25-26 `mov byte_9DF88E, -1; mov byte_9DF88F, -1` | ~25 | hook_size=5(覆盖 `byte_9DF88E=-1`),循环写 N 个 -1 到 WarPC 槽位数组 |
| #2 check_full (sub_444BB0) | L25-30 满槽检查 | ~40 | hook_size=5,遍历 N 槽判满 |
| #3 alloc_slot (sub_431094) | L17-26 硬编码 2 分支 | ~80 | **核心难点**;需保存 v5/v6 栈状态供原函数后续 qmemcpy 使用 |
| #4 clear_slot (sub_43C734) | L18-25 2 个 if | ~30 | hook_size=5,遍历 N 槽 |
| #5 noise_index (sub_444FD4) | L45 `+2` 常量 | 0(imm patch_bytes) | hook 改字节 |
| #6 noise_cap (sub_445564) | L22 `>=6` | 0(imm patch_bytes) | hook 改字节 |
| **小计** | | **~175 字节** | 比 `team_member_routing`(158 字节)略多 |

加上 `summon_table.tkspatch` 现有的 cave 占用(随机表 + 90 字节表 = 560 字节,**已独占**),整合后 cave 总占用约:

```
现有 16 cave 用户: 1526 字节 (已超额)
+ 召唤补丁 6 个: ~175 字节
+ summon_table 已含: 560 字节(已含在 1526 中)
= 1701 字节
```

**结论:cave 必须扩容到至少 2048 字节(2× 现有)或 4096 字节(4× 现有)**。

### 3.5 推荐的 cave 扩容方案

`patcher_worker.py` 第 505 行的 `1024` 改为 `4096`:

```python:505:511:patcher_worker.py
ca = _VirtualAllocEx(hp, None, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
```

扩到 4096 字节后:
- 总占用 ~1701 / 4096 = **42%**(健康利用率)
- 仍有 ~2400 字节余量供后续召唤 N 提升(N=6 时 cave #3 alloc_slot 增大)或其它新补丁

4096 字节在 32-bit 进程空间微不足道,**无副作用**(仅多占 3KB 私有内存,游戏退出自动释放)。

---

## 四、`.tkspatchpak` 整合路线建议

### 路线 A(推荐):**仅做"召唤数量扩展"独立 `.tkspatchpak`,不整合其它补丁**

理由:
- 召唤扩展是**功能独立的特性集**(6 个 cave + 4 处 imm 改动),不与 `summon_table` 随机表冲突
- 单独分发 = 用户可独立启用/禁用
- 不动现有 16 个 cave 用户,**风险最低**

实施步骤:
1. **修复 cave 容量瓶颈**:`patcher_worker.py:505` 1024 → 4096
2. **设计召唤 `.tkspatchpak` 形态**:6 个 `.tkspatch` + manifest.json,集中分配 cave_offset(避开已有 16 个区间)
3. **cave 机器码开发**:严格遵循反汇编(`444BB0.c`/`431094.c`/`436BD4.c`/`43C734.c`/`444FD4.c`/`445564.c`)
4. **cave 入口约定**:每个 cave 头部 `pop eax`(丢弃 call 返回地址)+ pushad/push 保存寄存器 + cave 体 + ret 回原函数后续
5. **变量配置**:`_variables.tkspatch` 加 `summon_max_count = 4`,cave 用 `{summon_max_count}` 引用(cave 字节层需硬编码,可考虑在 `apply_cave_hook` 之前由 Python patch cave 中的占位符)
6. **profile_rules**:为 `.test`/`.Silvana` MOD 版设 `apply`(依赖 `hook_conflict_action=override`)
7. **测试**:在原版 TKS.exe 上挂载召唤补丁,N=4 跑战斗测试 → 验证「囔嚷」联动是否同步(联调 #5/#6)

### 路线 B:**全量 `.tkspatchpak` 整合 50+ 现有补丁**

- 把 `patches/` 下 50+ 个 `.tkspatch` 重新打包为 `core_patches.tkspatchpak`
- 增加 `cave_layout` 自动计算(按 size 排序紧凑布局)
- 增加 `cave_capacity` 字段,启动时校验是否超 cave 内存

工作量较大,收益不高(只是分发形态变更),**不建议**。

---

## 五、关键风险点(严格遵循逆向结论)

### 5.1 必须 100% 严格遵循反汇编,不能臆测

召唤系统涉及 6 个反汇编函数,任何 cave 字节必须**逐一对照反编译**手动核对:

- `decompile/444BB0.c` L25-30:满槽检查(双槽 ≥0 → 拒绝)
- `decompile/431094.c` L17-26:槽位分配硬编码 2 分支;L61 `byte_9DF88E[v5] = v6` 写回
- `decompile/436BD4.c` L25-26:战斗初始化清空两槽
- `decompile/43C734.c` L18-25:死亡清除 2 个 if
- `decompile/444FD4.c` L45:`v12 = byte_9DF887 + byte_9DF883 + 2` 常量 `+2` 必须改 `+N`
- `decompile/445564.c` L22:`if (byte_9DF887 >= 6) return 0` 常量 `6` 必须改 `8-N`

cave #3 (`sub_431094`)是最难点:**必须在 hook 后正确保存/恢复 v5(槽位号)/v6(角色索引)供原函数 qmemcpy、战场注册使用**,不能臆测寄存器约定。

### 5.2 「囔嚷」联动必须原子修改

`+2` 和 `≥6` 两个常量若漏改一个,玩家召唤与「囔嚷」敌人索引会在 `byte_9DF882` ≥24 后数据互踩。

> 注:「囔嚷」仅在 `word_9DF894=1` 的特殊战斗模式生效(普通战斗 `v36=0` 恒被抵抗),漏改影响面仅限少数战斗,**但仍必须改**。

### 5.3 N 的上限天花板

`byte_9DF882` 最大 32 = 队伍(≤6) + 敌人(≤18) + 玩家召唤 + 「囔嚷」上场敌人。`2+6` 池内重新分配后,**N ≤ 6**。超出后第 33 个角色会越界写坏 `word_9DF896` 光标坐标等全局变量。

### 5.4 Cave 内不得触碰 WarPC 索引上限检查

cave 中若涉及 WarPC 读/写,`awk_sprite` 类 cave 的 `cmp eax, 200` 上限会自动被 `idx_cap` 重写,但召唤补丁 cave 若需要读 WarPC 槽位数组,**必须避开 idx_cap 硬编码 200**——召唤补丁用的是新槽位数组(在 WarPC 扩展区),不受 idx_cap 影响。

---

## 六、关键文件索引

| 文件 | 作用 |
|---|---|
| `反编译产物/decompile/444BB0.c` | 召唤满检(L25) |
| `反编译产物/decompile/431094.c` | 召唤分配(L17-26) |
| `反编译产物/decompile/436BD4.c` | 战斗初始化清空槽(L25-26) |
| `反编译产物/decompile/43C734.c` | 死亡清除(L18-25) |
| `反编译产物/decompile/444FD4.c` | 「囔嚷」索引公式(L45) |
| `反编译产物/decompile/445564.c` | 「囔嚷」次数上限(L22) |
| `反编译产物/decompile/4307CC.c` | 战场初始化(L40-48 容量证据;L315-317 `byte_9DF883` 写入) |
| `tks_launcher_gui/core/patch_engine.py` | 补丁引擎;`apply_cave_hook`(L997)、`build_cave_template`(L737)、cave 模板集合(L118-726) |
| `tks_launcher_gui/core/tkspatch_loader.py` | `.tkspatch` ZIP 加载器(L72-374) |
| `tks_launcher_gui/core/scanner.py` | WarPC 基址发现(L340)、EXE 指纹(L147) |
| `tks_launcher_gui/workers/patcher_worker.py` | 挂起-补丁-恢复流程(L88);**cave 内存分配 L505(`1024`)**;cave_addr 注入 L520 |
| `tks_launcher_gui/patches/_variables.tkspatch` | 全局变量唯一来源 |
| `tks_launcher_gui/patches/summon_table.tkspatch` | 多随机 cave 模板参考(cave_code/summon_cave_code/summon_cave2_code) |
| `tks_launcher_gui/patches/team_member_routing.tkspatch` | 158 字节大型 cave 参考模板 |
| `tks_launcher_gui/patches/duel_counter_self_fix.tkspatch` | pop 返回地址 + 序言重放的 cave 写法 |

---

## 七、结论与建议

1. **可行**:召唤扩展补丁机制与现有 `tks_launcher_gui` 体系高度匹配,可作为 6 个独立的 `.tkspatch` 实现,然后打包为 `battle_summon_expansion.tkspatchpak`。

2. **必须先解决 cave 容量瓶颈**:`patcher_worker.py:505` 的 `1024` 必须改为 `4096`(`~1701 字节`总需求 ÷ `42%` 利用率)。否则召唤补丁即使实现正确,也会因 cave 内存不足被覆盖写入,引发未定义行为。

3. **`.tkspatchpak` 形态可行**:现有 `patches/` + `PatchConfig.patches` 数据模型是天然的"包"容器,加 `manifest.json`(版本、cave_layout 计划、依赖)即可。`.tksmodpak` 已有先例可参考。

4. **cave_offset 必须自动布局**:`.tkspatchpak` 的 manifest 必须含 `cave_layout` 集中分配表(避免手工分配踩雷)。可考虑按 size 排序紧凑布局的最小化算法。

5. **cave #3 (sub_431094) 是开发核心难点**:`v5`/`v6` 局部变量寄存器/栈状态必须精确保存/恢复供原函数后续 qmemcpy、战场注册使用。**必须严格按反编译对照,不能臆测。**

6. **首版推荐 N=4**(行为影响最小),稳定后再放宽到 N=6。「囔嚷」联动必须原子修改 #5/#6,普通战斗中「囔嚷」本就被抵抗,实际影响仅限少数特殊战斗。

**建议执行顺序**:`cave 扩容` → `cave_offset 自动布局工具` → `6 个 .tkspatch 单独开发 + 单测` → `整合 .tkspatchpak + manifest` → `端到端测试`。