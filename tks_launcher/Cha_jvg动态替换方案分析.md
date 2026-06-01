# Cha.jvg 运行时动态替换方案分析

> **项目**: 三国群侠传 (TKS) Mod 支持
> **目标**: 支持角色 Mod 文件 (.tkspcsk) 动态替换/扩充 Cha.jvg
> **日期**: 2026-05-28

---

## 目录

1. [JVG 文件格式详解](#1-jvg-文件格式详解)
2. [游戏加载 Cha.jvg 机制](#2-游戏加载-cha_jvg-机制)
3. [Cha.jvg 在游戏中的使用](#3-cha_jvg-在游戏中的使用)
4. [动态替换方案对比](#4-动态替换方案对比)
5. [jvg_editor.py 已有功能分析](#5-jvg_editorpy-已有功能分析)
6. [最终推荐方案](#6-最终推荐方案)
7. [.tkspcsk 文件格式设计](#7-tkspcsk-文件格式设计)
8. [实施计划](#8-实施计划)

---

## 1. JVG 文件格式详解

### 1.1 文件结构概览

```
┌─────────────────────────────────────────────────────────┐
│ @JVG Header (32 bytes)                                  │
│   magic:       "@JVG" (4B)                              │
│   version:     block_count (4B)                         │
│   block_count: 块数量 (4B)                              │
│   data_size:   帧数据总大小 (4B)                        │
│   total_frames: 总帧数 (4B)                             │
│   padding:     12B                                      │
├─────────────────────────────────────────────────────────┤
│ @JVM Block 0 (可重复多个块)                             │
│   magic:       "@JVM" (4B)                              │
│   sprite_count: 精灵数 N (4B)                           │
│   reserved:    4B                                       │
│   data_size:   帧数据大小 (4B)                          │
│   padding:     16B                                      │
│   ─────────────────────────────────────────────────────  │
│   Stream1:     (N+1) × 4B 累积偏移表                    │
│   Palette:     256 × 2B (RGB565)                        │
│   Frame Data:  每帧 = 16B头 + RLE编码像素               │
├─────────────────────────────────────────────────────────┤
│ @JVM Block 1 ...                                        │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Frame 头部结构 (16 字节)

| 偏移 | 大小 | 字段 | 说明 |
|------|------|------|------|
| 0 | 2B | x_max | 右边界 (signed int16) |
| 2 | 2B | y_max | 下边界 (signed int16) |
| 4 | 2B | width | 宽度 |
| 6 | 2B | height | 高度 |
| 8 | 4B | reserved | 保留 |
| 12 | 2B | reserved | 保留 |
| 14 | 2B | row_count | RLE 对数 |

### 1.3 RLE 编码格式

```
数据流: [(skip:uint16, run:uint16), pixel_data:run bytes] ...

skip: 跳过的像素数 (含跨行补偿)
run:  连续不透明像素数
pixel_data: 调色板索引数组
```

**渲染逻辑** (匹配游戏 sub_4544EC):
```
dest = screen + 2 * (y_max * 640 + x_max)   # 起点 = 右下角
while (rle_pairs--):
    dest -= 2 * skip                          # 向左跳过 skip 像素
    while (run--):
        *dest = palette[*src++]               # 写像素 (RGB565)
        dest -= 2                             # 向左移
```

### 1.4 调色板格式

- 256 个条目，每个 2 字节
- 格式: RGB565 (R:5, G:6, B:5)
- 转换公式:
  ```python
  # RGB565 → RGB888
  r = ((entry >> 11) & 0x1F) << 3
  g = ((entry >> 5) & 0x3F) << 2
  b = (entry & 0x1F) << 3
  ```

---

## 2. 游戏加载 Cha.jvg 机制

### 2.1 加载入口

**函数**: `sub_411624` (游戏初始化)

```c
int sub_411624() {
    // ...
    handler = alloc(40);                    // 分配 40 字节 handler
    sub_453824(handler);                    // 清零 handler
    dword_755AF0 = handler;                 // 存储到全局变量
    sub_453BD0(handler, "Cha.jvg");         // 加载 JVG 文件
    dword_755AC4 = handler;                 // 备份引用
    // ...
}
```

### 2.2 JVG 加载函数 sub_453BD0

```c
char __cdecl sub_453BD0(_DWORD *handler, const char *filename) {
    // 1. 打开文件
    file_handle = sub_4B1FC8(filename, "rb");
    if (!file_handle) {
        printf("JVG file %s not exist !!", filename);
        return 0;
    }

    // 2. 读取并验证 header (32 字节)
    sub_4B2208(header_buf, 1, 32, file_handle);
    if (memcmp(header_buf, "@JVG", 4) != 0) {
        printf("%s is not a JVG file !!", filename);
        return 0;
    }

    // 3. 解析 header
    block_count = *(DWORD*)(header_buf + 4);
    data_size = *(DWORD*)(header_buf + 8);
    total_frames = *(DWORD*)(header_buf + 12);

    // 4. 分配 sprite 数组 (每条 64 字节)
    sprite_array = malloc(64 * sprite_count);

    // 5. 循环读取每个 @JVM block
    while (block_count > 0) {
        // 读取 block header
        sub_4B2208(block_header, 1, 32, file_handle);
        sprite_count = *(DWORD*)(block_header + 4);

        // 读取 Stream1 (N+1 个累积偏移)
        sub_4B2208(stream1_buf, 1, 4 * (sprite_count + 1), file_handle);

        // 读取调色板 (512 字节)
        sub_4B2208(palette_buf, 1, 512, file_handle);

        // 读取每帧数据
        for (i = 0; i < sprite_count; i++) {
            // 读取 16 字节帧头
            sub_4B2208(frame_header, 1, 16, file_handle);

            // 分配 512 字节名称缓冲区
            name_buf = malloc(512);

            // 记录帧元数据
            sprite_array[i * 64 + 0] = frame_type;
            sprite_array[i * 64 + 8] = name_buf;
            sprite_array[i * 64 + 40] = data_ptr;
            sprite_array[i * 64 + 48] = data_size;
            sprite_array[i * 64 + 56] = file_offset;  // 延迟加载用

            // 跳过帧数据 (延迟加载)
            sub_4B22A8(file_handle, data_size, 1);
        }
        block_count--;
    }

    // 6. 保存到 handler
    handler[0] = sprite_array;
    handler[4] = file_handle;
    handler[5] = sprite_count;
    handler[6] = total_frames;

    return 1;
}
```

### 2.3 JVG Handler 结构 (40 字节)

| 偏移 | 字段 | 说明 |
|------|------|------|
| `[0]` (0x00) | sprite_array_ptr | Sprite 数组指针 (每条 64 字节) |
| `[1]` (0x04) | alt_data_ptr | 备用数据指针 |
| `[2]` (0x08) | frame_map_ptr | frame→sprite 映射表 (WORD 数组) |
| `[3]` (0x0C) | subframe_map_ptr | 子 frame 映射表 (WORD 数组) |
| `[4]` (0x10) | file_handle | 文件句柄 |
| `[5]` (0x14) | sprite_count | Sprite 总数 |
| `[6]` (0x18) | total_frames | 总帧数 |
| `[7]` (0x1C) | reserved | 保留 |

### 2.4 Sprite 数组条目结构 (64 字节)

| 偏移 | 字段 | 说明 |
|------|------|------|
| `[0]` (0x00) | frame_count/type | 帧数或类型标志 |
| `[1..7]` (0x04-0x1C) | sub_frame_ptrs | 子帧数据指针 (7 个) |
| `[8]` (0x20) | name_ptr | 名称字符串指针 (512B) |
| `[9]` (0x24) | another_ptr | 另一个指针 |
| `[10]` (0x28) | data_ptr | 帧数据指针 |
| `[11]` (0x2C) | loaded_flag | 加载标志/数据缓冲区 |
| `[12]` (0x30) | data_size | 数据大小 |
| `[13]` (0x34) | ref_count | 引用计数 |
| `[14]` (0x38) | file_offset | 文件偏移 (延迟加载) |
| `[15]` (0x3C) | reserved | 保留 |

### 2.5 延迟加载机制

**关键函数**: `sub_45410C` (延迟加载)

```c
int __cdecl sub_45410C(_DWORD *handler, int frame_id, int flag) {
    if (!handler[4]) return -1;           // 无文件句柄
    if (frame_id >= handler[5]) return 0; // 越界

    if (frame_id >= 0) {
        sprite_entry = handler[0] + (frame_id << 6);

        if (sprite_entry[11]) {
            // 已加载，直接返回
            if (!flag) sprite_entry[13]++;  // 增加引用计数
            return sub_45408C(handler, frame_id);
        } else {
            // 首次加载：从文件读取像素数据
            data_size = sprite_entry[12];
            data_buf = malloc(data_size);
            sprite_entry[11] = data_buf;

            // 定位到文件偏移
            sub_4B22A8(handler[4], sprite_entry[14], 0);

            // 读取数据
            sub_4B2208(data_buf, 1, data_size, handler[4]);

            sprite_entry[13]++;  // 增加引用计数
            return sub_45408C(handler, frame_id);
        }
    } else {
        // frame_id < 0: 加载所有帧
        for (i = 0; i < handler[5]; i++)
            sub_45410C(handler, i, 0);
        return 0;
    }
}
```

---

## 3. Cha.jvg 在游戏中的使用

### 3.1 帧索引与角色的对应关系

**帧索引公式**: `frame_idx = name_id + 2`

其中 `name_id` = WarPC 记录的 word[0] (角色名称 ID)

| 角色类型 | name_id | frame_idx | 说明 |
|----------|---------|-----------|------|
| 原始角色 0 | 0 | 2 | Cha.jvg 中 frame[2] |
| 原始角色 1 | 1 | 3 | Cha.jvg 中 frame[3] |
| ... | ... | ... | ... |
| 原始角色 97 | 97 | 99 | 假设原始有 100 帧 |
| 新角色 143 | 143 | 145 | 需要扩展! |
| 新角色 144 | 144 | 146 | 需要扩展! |

### 3.2 战场渲染调用点

```c
// 从 WarPC 战斗副本读取角色 name_id，+2 作为 frame 索引
sub_458020(
    dword_755AF0,                    // Cha.jvg handler
    x, y,                            // 屏幕坐标
    word_9D7496[527 * char_idx] + 2, // frame_idx = name_id + 2
    screen, 0, 0, -1
);
```

**调用位置汇总**:

| 调用位置 | 场景 | 帧索引来源 |
|----------|------|------------|
| `sub_43339C:68` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_433A38:62` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_433690:62` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_434188:71` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_434D7C:98` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_43C340:60` | 战场角色渲染 | `word_9D7496[527*idx] + 2` |
| `sub_406864:38` | 角色详情界面 | `*(word_75480C + 220)` |
| `sub_405CBC:144` | 角色选择界面 | `v2[51]` (选中角色) |
| `sub_4434BC:292` | 其他场景 | `word_9D7496[527*idx] + 2` |

### 3.3 渲染时的帧索引检查

**函数**: `sub_458020`

```c
unsigned __int16 __cdecl sub_458020(int handler, int x, int y, __int16 frame_idx, ...) {
    if (frame_idx < *(DWORD*)(handler + 24))  // handler+24 = total_frames
    {
        // 执行渲染
        return sub_45871C(handler, x, y, frame_idx, ...);
    }
    return frame_idx;  // 越界则跳过渲染
}
```

**关键**: 只要 `frame_idx < total_frames`，游戏就会尝试渲染该帧。

### 3.4 Cha.jvg 的生命周期

| 事件 | 函数 | 说明 |
|------|------|------|
| 加载 | `sub_411624` | 游戏初始化时加载一次 |
| 使用 | `sub_458020` 等 | 战场/界面渲染时使用 |
| 释放 | `sub_4119CC` | 游戏退出时释放 |

**关键发现**: Cha.jvg 在游戏运行期间**不会重新加载**。

---

## 4. 动态替换方案对比

### 4.1 方案 A：启动时合并生成新 Cha.jvg

**流程**:
```
游戏启动前:
  1. 扫描 mods/*.tkspcsk
  2. 加载原始 Cha.jvg
  3. 对每个 .tkspcsk:
     - 解析角色序号 frame_idx
     - 将图像数据替换/追加到 Cha.jvg
  4. 保存为 Cha.jvg (覆盖)
  5. 启动游戏 (游戏加载修改后的文件)
```

**优点**:
| 优点 | 说明 |
|------|------|
| ✅ 实现简单 | 复用 jvg_editor.py 已有功能 |
| ✅ 稳定可靠 | 游戏加载的是标准 JVG 文件 |
| ✅ 兼容性好 | 不依赖游戏内部结构 |
| ✅ 调试容易 | 可以用 jvg_editor.py 验证结果 |
| ✅ 无运行时开销 | 游戏运行时零额外开销 |

**缺点**:
| 缺点 | 说明 |
|------|------|
| ⚠️ 修改原始文件 | 需要备份/恢复机制 |
| ⚠️ 启动稍慢 | 需要解析/重写整个 JVG (毫秒级) |
| ❌ 无法热切换 | 修改 mod 后需重启游戏 |

### 4.2 方案 B：运行时动态加载 (Hook 文件打开)

**流程**:
```
游戏启动前:
  1. 扫描 *.tkspcsk 文件，建立索引表
  2. Hook sub_4B1FC8 (文件打开函数)

游戏运行时:
  1. 当游戏打开 "Cha.jvg" 时
  2. Hook 重定向到 "Cha.jvg.mod"
  3. 游戏加载修改后的文件
```

**优点**:
| 优点 | 说明 |
|------|------|
| ✅ 不修改原始文件 | 更安全 |
| ✅ 理论上可热切换 | 运行时替换 mod 无需重启 |

**缺点**:
| 缺点 | 说明 |
|------|------|
| ❌ 实现复杂 | 需要编写 cave hook |
| ❌ 调色板冲突 | 运行时处理更复杂 |
| ❌ RLE 编码 | 需要在 C# 中重新实现 |
| ❌ 兼容性风险 | 游戏更新可能导致 hook 失效 |

### 4.3 方案 C：Hook 延迟加载函数

**流程**:
```
游戏运行时:
  1. Hook sub_45410C (延迟加载)
  2. 当加载特定 frame 时检查 .tkspcsk
  3. 如果有 mod，从 .tkspcsk 读取数据
  4. 替换内存中的帧数据
```

**优点**:
| 优点 | 说明 |
|------|------|
| ✅ 精确控制 | 只替换实际使用的 frame |
| ✅ 不修改原始文件 | 更安全 |

**缺点**:
| 缺点 | 说明 |
|------|------|
| ❌ 实现最复杂 | 需要理解延迟加载机制 |
| ❌ 性能开销 | 每次加载都需要检查索引表 |
| ❌ 内存管理 | 需要管理动态加载的帧数据 |

### 4.4 方案对比总结

| 维度 | 方案 A (合并) | 方案 B (Hook 文件) | 方案 C (Hook 延迟) |
|------|--------------|-------------------|-------------------|
| 实现难度 | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 稳定性 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 性能 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 灵活性 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 代码复用 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ |

---

## 5. jvg_editor.py 已有功能分析

### 5.1 Block 管理功能

| 功能 | 方法 | 说明 |
|------|------|------|
| ✅ 添加 Block | `_add_block()` | 创建新的 @JVM 分组 |
| ✅ 删除 Block | `_del_block()` | 删除指定分组 |

**代码**:
```python
def _add_block(self):
    if not self.jvg: self.jvg = JVGFile()
    name = f"block_{len(self.jvg.blocks):02d}"
    self.jvg.blocks.append(JVMBlock(name))
    # ...

def _del_block(self):
    if not self.jvg or self._bi < 0: return
    if messagebox.askyesno("确认", f"删除 [{self._bi}]?"):
        del self.jvg.blocks[self._bi]
        # ...
```

### 5.2 Frame 管理功能

| 功能 | 方法 | 说明 |
|------|------|------|
| ✅ 添加帧 | `_add_images()` | 导入图片到当前 block |
| ✅ 替换帧 | `_replace_frame()` | 替换选中的帧 (自动对齐锚点) |
| ✅ 删除帧 | `_del_frame()` | 删除选中的帧 |
| ✅ 批量导入 | `_batch_replace_gridsheet()` | 从图集批量导入 |

**代码**:
```python
def _add_images(self):
    if not self.jvg or self._bi < 0: return
    paths = filedialog.askopenfilenames(...)
    if not paths: return
    frames = import_images(list(paths))
    if frames:
        blk = self.jvg.blocks[self._bi]
        for f in frames:
            if f._palette: _remap_to_block_palette(f, blk)
        blk.frames.extend(frames)

def _replace_frame(self):
    if not self.jvg or self._bi < 0 or self._sel_fi < 0: return
    blk = self.jvg.blocks[self._bi]
    if self._sel_fi >= blk.frame_count: return
    paths = filedialog.askopenfilenames(...)
    if not paths: return
    frames = import_images([paths[0]])
    if frames:
        new_f = frames[0]
        old_f = blk.frames[self._sel_fi]
        _align_anchor(new_f, old_f, mode="bottom_center")
        if new_f._palette: _remap_to_block_palette(new_f, blk)
        blk.frames[self._sel_fi] = new_f
```

### 5.3 调色板处理功能

| 功能 | 方法 | 说明 |
|------|------|------|
| ✅ 调色板重映射 | `_remap_to_block_palette()` | 将帧映射到 block 调色板 |
| ✅ 批量量化 | `_batch_quantize_subs_to_block()` | 多帧共享调色板量化 |
| ✅ 锚点对齐 | `_align_anchor()` | 替换时保持视觉位置 |

**_remap_to_block_palette 核心逻辑**:
```python
def _remap_to_block_palette(f: JVGFrame, blk: JVMBlock):
    """将导入帧重映射到块调色板"""
    # 1. 扫描块中所有原始帧已使用的调色板索引
    used_by_original = set()
    for of in blk.frames:
        if of is f: continue
        if of.pixels:
            for b in of.pixels: used_by_original.add(b)

    # 2. 构建可用索引
    available = [i for i in range(256) if i not in used_by_original]

    # 3. 对导入帧中实际使用的颜色，分配空位并写入调色板
    used = set(f.pixels)
    remap = [0] * 256
    for fi in sorted(used):
        # 尝试精确匹配已有颜色
        # 如果没有，分配新空位
        # 如果空位不足，找最近颜色

    # 4. 重映射像素
    px = bytearray(f.pixels)
    for i in range(len(px)):
        if px[i] < 256: px[i] = remap[px[i]]
    f.pixels = bytes(px)

    # 5. 重新编码 RLE
    if f.width > 0 and f.height > 0:
        alpha = f.alpha if f.alpha else bytes([255] * (f.width * f.height))
        f.encoded_data, f.row_count = _encode_rle_game(f.pixels, alpha, f.width, f.height)
    f._palette = None
```

### 5.4 I/O 功能

| 功能 | 方法 | 说明 |
|------|------|------|
| ✅ 加载 JVG | `load_jvg()` | 解析 JVG 文件 |
| ✅ 保存 JVG | `save_jvg()` | 保存为游戏兼容格式 |
| ✅ 导入图片 | `import_images()` | 从 PNG/BMP/JPG 导入 |
| ✅ 导出帧 | `export_single()` | 导出单帧为 PNG |
| ✅ 导出分组 | `export_group()` | 导出整个 block |
| ✅ 导出图集 | `export_gridsheet()` | 导出为网格图集 |

### 5.5 RLE 编解码功能

| 功能 | 方法 | 说明 |
|------|------|------|
| ✅ RLE 解码 | `_decode_rle()` | 解码 RLE 数据为像素 |
| ✅ RLE 编码 | `_encode_rle_game()` | 按游戏格式编码 RLE |

**_encode_rle_game 核心逻辑**:
```python
def _encode_rle_game(pixels: bytes, alpha: bytes, w: int, h: int, screen_w: int = 640):
    """按游戏 sub_4544EC 渲染逻辑生成 RLE 数据"""
    buf = bytearray()
    pair_count = 0
    pending = 0  # 跨行累积 skip
    first = True

    for row in range(h - 1, -1, -1):
        # 行切换: 需要 (screen_w - w) 个像素的回跳
        if not first: pending += screen_w - w
        first = False
        col = w - 1

        while col >= 0:
            # 累计连续透明像素
            t0 = col
            while col >= 0 and alpha[row * w + col] == 0: col -= 1
            pending += t0 - col
            if col < 0: break

            # 如 pending 溢出 uint16，拆成若干空对
            while pending > 0xFFFF:
                buf += struct.pack("<HH", 0xFFFF, 0)
                pair_count += 1
                pending -= 0xFFFF

            # 收集连续不透明段
            run = bytearray()
            while col >= 0 and alpha[row * w + col] != 0 and len(run) < 0xFFFF:
                run.append(pixels[row * w + col])
                col -= 1

            buf += struct.pack("<HH", pending, len(run))
            buf += bytes(run)
            pair_count += 1
            pending = 0

    return bytes(buf), pair_count
```

---

## 6. 最终推荐方案

### 6.1 推荐：方案 A（启动时合并）

**理由**:

1. **已有基础设施完善**
   - jvg_editor.py 已有完整的 JVG 读写、RLE 编解码、调色板重映射功能
   - 无需重新实现任何核心逻辑

2. **启动器已有类似逻辑**
   - tks_launcher.cs 中的 `PrepareWarPcForGame()` 已实现"检测扩展文件 → 创建截断版本 → 运行时修补"的流程
   - 可以直接复用相同的模式

3. **可靠性优先**
   - 游戏 mod 工具的首要目标是稳定运行
   - 方案 A 的风险最低

4. **实现成本低**
   - 只需为 jvg_editor.py 添加命令行接口
   - 在 tks_launcher.cs 中添加调用逻辑

5. **用户体验足够好**
   - 启动时合并只需几毫秒（Cha.jvg 通常只有几百 KB）
   - 用户修改 .tkspcsk 后重启游戏即可生效

### 6.2 集成方式选择

| 方式 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **调用 Python 脚本** | 复用所有已有代码，维护成本低 | 需要 Python 环境 | ⭐⭐⭐⭐⭐ |
| 移植到 C# | 无 Python 依赖 | 需要重写 JVG 处理逻辑，工作量大 | ⭐⭐ |

**推荐**: 调用 Python 脚本方式

### 6.3 扩展 Cha.jvg 的可行性

**关键发现**: 游戏没有硬编码 JVG 的大小限制！

| 参数 | 来源 | 是否硬编码 |
|------|------|-----------|
| `block_count` | 文件头 offset 4 | ❌ 动态读取 |
| `sprite_count` | 每个 block 的 offset 4 | ❌ 动态读取 |
| `total_frames` | 文件头 offset 16 | ❌ 动态读取 |
| `data_size` | 文件头 offset 12 | ❌ 动态读取 |
| 内存分配 | `malloc(block_count * ...)` | ❌ 动态分配 |

**结论**: 扩展 Cha.jvg 完全可行！

**扩展策略**:
1. 在现有 Block 末尾追加新帧
2. 更新 `total_frames`、`sprite_count`、`data_size`
3. 扩展 Stream1 偏移表
4. 添加新帧的 RLE 数据

---

## 7. .tkspcsk 文件格式设计

### 7.1 文件结构

```
┌─────────────────────────────────────┐
│ .tkspcsk 文件结构                    │
├─────────────────────────────────────┤
│ Header (16 bytes)                   │
│   magic:      "TKSP" (4B)          │
│   mode:       uint8 (1B)           │
│     0 = 替换指定 frame              │
│     1 = 新增 (自动索引)             │
│     2 = 新增 (指定索引)             │
│   reserved:   3B                    │
│   target_idx: uint32 (4B)          │
│     mode=0: 要替换的 frame 全局索引  │
│     mode=1: 忽略                    │
│     mode=2: 指定的新 frame 索引     │
│   width:      uint16 (2B)          │
│   height:     uint16 (2B)          │
├─────────────────────────────────────┤
│ Pixel Data (width × height bytes)   │
│   调色板索引，0 = 透明              │
├─────────────────────────────────────┤
│ Alpha Mask (width × height bytes)   │
│   0 = 透明, 255 = 不透明            │
└─────────────────────────────────────┘
```

### 7.2 mode 说明

| mode | 含义 | target_idx | 使用场景 |
|------|------|-----------|----------|
| 0 | 替换 | 要替换的 frame 全局索引 | 修改现有角色外观 |
| 1 | 新增(自动) | 忽略 | 添加新角色，索引自动递增 |
| 2 | 新增(指定) | 指定的新 frame 索引 | 添加新角色，指定 name_id+2 |

### 7.3 设计说明

**为什么不需要包含调色板？**

因为 `_remap_to_block_palette()` 会自动将像素重映射到 block 的调色板。用户只需提供调色板索引的像素数据，编辑器会自动处理调色板分配。

**为什么使用调色板索引而不是 RGB？**

1. 文件更小
2. 与游戏格式一致
3. 调色板重映射更简单

---

## 8. 实施计划

### 8.1 Phase 1：基础功能（替换现有帧）

**目标**: 支持替换 Cha.jvg 中现有的 frame

**步骤**:

1. **定义 .tkspcsk 文件格式规范**
   - 编写格式文档
   - 编写示例文件

2. **为 jvg_editor.py 添加命令行接口**
   ```python
   def batch_apply_mods(jvg_path: str, mods_dir: str, output_path: str):
       """命令行批量应用 .tkspcsk mod 文件"""
       # 1. 加载原始 JVG
       jvg = load_jvg(jvg_path)

       # 2. 扫描 mods 目录
       mod_files = sorted(Path(mods_dir).glob("*.tkspcsk"))

       for mod_path in mod_files:
           # 3. 解析 .tkspcsk 文件
           mod_data = parse_tkspcsk(mod_path)

           # 4. 根据 mode 处理
           if mod_data['mode'] == 0:  # 替换
               frame_idx = mod_data['target_idx']
               block_idx, local_idx = find_frame(jvg, frame_idx)
               if block_idx >= 0:
                   new_frame = create_frame_from_mod(mod_data)
                   _align_anchor(new_frame, jvg.blocks[block_idx].frames[local_idx])
                   _remap_to_block_palette(new_frame, jvg.blocks[block_idx])
                   jvg.blocks[block_idx].frames[local_idx] = new_frame

       # 5. 保存
       save_jvg(jvg, output_path)
   ```

3. **在 tks_launcher.cs 中添加 Cha.jvg 处理**
   ```csharp
   static void PrepareChaJvgForGame()
   {
       string modsDir = "mods";
       if (!Directory.Exists(modsDir)) return;

       var modFiles = Directory.GetFiles(modsDir, "*.tkspcsk");
       if (modFiles.Length == 0) return;

       // 备份原始文件
       if (!File.Exists("Cha.jvg.orig"))
           File.Copy("Cha.jvg", "Cha.jvg.orig", true);

       // 调用 Python 脚本
       var psi = new ProcessStartInfo
       {
           FileName = "python",
           Arguments = "jvg_editor.py --batch Cha.jvg.orig mods Cha.jvg",
           UseShellExecute = false,
           RedirectStandardOutput = true,
           CreateNoWindow = true
       };

       var proc = Process.Start(psi);
       proc.WaitForExit();

       if (proc.ExitCode != 0)
           Log("  [WARN] Cha.jvg mod 应用失败");
       else
           Log("  [OK] Cha.jvg mod 已应用");
   }
   ```

4. **测试验证**
   - 创建测试 .tkspcsk 文件
   - 验证替换效果
   - 验证游戏正常运行

### 8.2 Phase 2：扩展功能（新增帧）

**目标**: 支持向 Cha.jvg 添加新的 frame

**步骤**:

1. **扩展 jvg_editor.py 的 batch_apply_mods**
   ```python
   def batch_apply_mods(jvg_path: str, mods_dir: str, output_path: str):
       # ...

       for mod_path in mod_files:
           mod_data = parse_tkspcsk(mod_path)

           if mod_data['mode'] == 1:  # 新增 (自动索引)
               frame_idx = jvg.total_frames  # 自动分配
               new_frame = create_frame_from_mod(mod_data)
               # 添加到第一个 block
               _remap_to_block_palette(new_frame, jvg.blocks[0])
               jvg.blocks[0].frames.append(new_frame)

           elif mod_data['mode'] == 2:  # 新增 (指定索引)
               frame_idx = mod_data['target_idx']
               # 扩展到指定索引
               extend_jvg_to_frame(jvg, frame_idx)
               new_frame = create_frame_from_mod(mod_data)
               set_frame(jvg, frame_idx, new_frame)

       # ...
   ```

2. **实现 extend_jvg_to_frame 辅助函数**
   ```python
   def extend_jvg_to_frame(jvg: JVGFile, target_idx: int):
       """扩展 JVG 以容纳指定的 frame 索引"""
       current_total = jvg.total_frames
       if target_idx < current_total:
           return  # 已经足够大

       # 在第一个 block 末尾追加空帧
       blk = jvg.blocks[0]
       for i in range(current_total, target_idx + 1):
           empty_frame = JVGFrame()
           empty_frame.width = 1
           empty_frame.height = 1
           empty_frame.pixels = bytes([0])
           empty_frame.alpha = bytes([0])
           empty_frame.encoded_data = b""
           empty_frame.row_count = 0
           blk.frames.append(empty_frame)
   ```

3. **测试验证**
   - 创建测试 .tkspcsk 文件 (mode=1, mode=2)
   - 验证新帧正确添加
   - 验证游戏能正确渲染新帧

### 8.3 Phase 3：优化和完善

**目标**: 优化用户体验，完善错误处理

**步骤**:

1. **错误处理**
   - 检测帧索引冲突
   - 检测文件格式错误
   - 提供友好的错误提示

2. **调色板优化**
   - 支持调色板继承选项
   - 优化颜色量化算法

3. **用户工具**
   - 编写 .tkspcsk 生成工具
   - 编写 Mod 管理工具

4. **文档完善**
   - 编写用户手册
   - 编写开发者文档

---

## 附录 A：关键代码位置

| 功能 | 函数 | RVA |
|------|------|-----|
| 游戏初始化 | `sub_411624` | 0x11624 |
| JVG 加载 | `sub_453BD0` | 0x53BD0 |
| 文件打开 | `sub_4B1FC8` | 0xB1FC8 |
| 延迟加载 | `sub_45410C` | 0x5410C |
| 渲染函数 | `sub_458020` | 0x58020 |
| 游戏清理 | `sub_4119CC` | 0x119CC |
| Cha.jvg handler | `dword_755AF0` | 0x755AF0 |
| Cha.jvg 字符串 | `aChaJvg` | 0x4E7F2E |

## 附录 B：相关文件

| 文件 | 说明 |
|------|------|
| `tks_launcher.cs` | 启动器主程序 |
| `jvg_editor.py` | JVG 编辑器 |
| `tks_patches.json` | 补丁配置 |
| `Cha.jvg` | 角色精灵图集 |
| `*.tkspcsk` | 角色 Mod 文件 |

## 附录 C：参考资料

- JVG 格式: `sub_453BD0` (加载器), `sub_4544EC` (渲染器)
- RLE 编码: `jvg_editor.py` 中的 `_encode_rle_game()`
- 调色板处理: `jvg_editor.py` 中的 `_remap_to_block_palette()`
- WarPC 扩展: `tks_launcher.cs` 中的 `ExpandWarPcBuffer()`
