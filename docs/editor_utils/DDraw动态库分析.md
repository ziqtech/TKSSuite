# ddraw.dll 完整逆向分析报告

> 基于 `ddraw.origin.dll`（原始文件）与 `ddraw.dll`（已修补版本）对比分析。

## 1. 基本信息

| 属性 | 值 |
|------|-----|
| 文件大小 | 106,496 bytes (104 KB) |
| Image Base | 0x10000000 |
| Entry Point RVA | 0x802B |
| 编译工具链 | MSVC (Visual C++ Runtime) |
| 作者源码路径 | `D:\Work\VC\Dx11Demo\TextureMap.fx` |
| 原始文件 | `ddraw.origin.dll`（未修改） |
| 修补文件 | `ddraw.dll`（移除了 27 个补丁字符串） |

### PE 段表

| 段名 | VA | VSize | RawPtr | RawSize | 属性 |
|------|-----|-------|--------|---------|------|
| .text | 0x10001000 | 0xF290 | 0x1000 | 0x10000 | CODE\|EXECUTE\|READ |
| .rdata | 0x10011000 | 0x16D4 | 0x11000 | 0x2000 | INITIALIZED\|READ |
| .data | 0x10013000 | 0x737C | 0x13000 | 0x2000 | INITIALIZED\|READ\|WRITE |
| .rsrc | 0x1001B000 | 0x2F48 | 0x15000 | 0x3000 | INITIALIZED\|READ |
| .reloc | 0x1001E000 | 0x18BC | 0x18000 | 0x2000 | INITIALIZED\|READ\|DISCARDABLE |

---

## 2. 整体架构

ddraw.dll 是一个 **DirectDraw 代理 + 游戏内存补丁 + 功能 Hook** 的综合性 MOD 工具。
其工作原理：

1. **DDraw 代理**：游戏调用 `DirectDrawCreate` 时，DLL 拦截并代理 DDraw 接口，可选使用 D2D/DX11 后端渲染
2. **功能 Hook**：在游戏关键函数入口注入 JMP，拦截存档读写、临时文件、敌方显示等
3. **内存补丁**：在游戏加载后，遍历 `.data` 段中的补丁定义字符串，用 `VirtualProtect` + 直接内存写入修改游戏代码

---

## 3. 功能 Hook（6 个入口点）

> **游戏侧 Hook 地址核对**（对照 TKS.exe 反编译）：`ReadSave 0x41116E` ↔ `sub_41103C`(LoadTKMat，已验证)、`WriteSave 0x410FA2` ↔ `sub_410ED4`(SaveTKMat，已验证)、`NoEnemy 0x4084FD` ↔ `sub_4084E0`(随机战斗，已验证 `word_9DF894`/`sub_40EB10`)——三者均落在对应函数体内，语义吻合。注：`ddraw.dll` 本身是独立于 TKS.exe 的代理 DLL，其内部（PE 段/补丁字符串表）不在 TKS.exe 逆向导出范围内，本节基于该 DLL 自身对比分析。

DLL 在游戏代码的特定地址注入 Hook，拦截以下功能。Hook 定义以成对字符串存储在 `.data` 段（文件偏移 0x15488~0x15690），格式为 `"游戏地址"` + `"Hook名称"`：

| 游戏地址 | Hook 名称 | 文件偏移 | 说明 |
|---------|-----------|---------|------|
| 0x00403C63 | **SkimFstDlg** | 0x15488/0x15498 | 快速对话跳过/加速 |
| 0x0047881A | **NoTmpDatRead** | 0x154E8/0x154F8 | 拦截 TmpDat 读取（临时数据文件） |
| 0x00478842 | **NoTmpDatWrite** | 0x15548/0x15558 | 拦截 TmpDat 写入 |
| 0x004084FD | **NoEnemy** | 0x155A8/0x155B8 | 无敌/无敌方模式 |
| 0x0041116E | **ReadSave** | 0x15608/0x15618 | 存档读取拦截（可注入修改后的数据） |
| 0x00410FA2 | **WriteSave** | 0x15668/0x15678 | 存档写入拦截 |

---

## 4. 内存补丁系统

### 4.1 补丁格式

补丁定义以 ASCII 字符串存储在 `.data` 段（文件偏移 0x156C8~0x15B90），共 **44 个**补丁。格式为：

```
"0x游戏VA,补丁字节,原指令描述,新指令描述"
```

- **游戏VA**：要修改的游戏代码地址
- **补丁字节**：替换的机器码前缀（十六进制），剩余部分用 NOP(0x90) 填充
- **描述**：原指令和新指令的简称（用于调试日志）

补丁应用流程：
1. `VirtualProtect` 将目标游戏地址改为可写
2. 将补丁字节写入目标地址
3. 恢复原内存保护属性
4. 失败时记录 `"Hook Fail %s"` 日志

### 4.2 全部 44 个补丁清单

> 原始 DLL 包含 44 个补丁。修补版（ddraw.dll）已将其中 27 个清零移除，保留 17 个。
> 两文件二进制对比确认：仅存在 27 处差异，全部位于 `.data` 段补丁字符串区域。

#### A. 智慧补丁组（9 个）— 已移除

将游戏对 `word ptr [0x756884]` (智慧) 的操作改为 `byte ptr [0x756887]`。

| 游戏地址 | 文件偏移 | 函数/场景 | 补丁字节 | 原指令 | 新指令 |
|---------|---------|----------|---------|--------|--------|
| 0x0040E187 | 0x159AA | Attribute() add | `90001587` | add word[0x756884] | add byte[0x756887] |
| 0x0040E720 | 0x159C4 | CheckTeam() case 2 | `908A1587` | mov dx, word[0x756884] | mov dl, byte[0x756887] |
| 0x00412875 | 0x159DE | 存档加载写入 | `90A287` | mov word[0x756884], ax | mov byte[0x756887], al |
| 0x004175A5 | 0x159F7 | 其他写入路径 | `90881587` | mov word[0x756884], dx | mov byte[0x756887], dl |
| 0x0041A3D2 | 0x15A11 | 存档预览显示 | `0FB60D87` | movsx ecx, word[0x756884] | movzx ecx, byte[0x756887] |
| 0x00422A8B | 0x15A32 | 减法运算 | `90280D87` | sub word[0x756884] | sub byte[0x756887] |
| 0x00422B13 | 0x15A4C | 加法运算 | `90000D87` | add word[0x756884] | add byte[0x756887] |
| 0x00422B6E | 0x15A66 | 比较运算 | `90803D87` | cmp word[0x756884] | cmp byte[0x756887] |
| 0x00422B78 | 0x15A80 | 清零 | `9090C6058768750000` | mov word[0x756884], 0 | mov byte[0x756887], 0 |

#### B. 仁德补丁组（9 个）— 已移除

将游戏对 `word ptr [0x756886]` (仁德) 的操作改为 `byte ptr [0x756886]`。

| 游戏地址 | 文件偏移 | 函数/场景 | 补丁字节 | 原指令 | 新指令 |
|---------|---------|----------|---------|--------|--------|
| 0x0040E1FB | 0x15AA5 | Attribute() add | `90000D` | add word[0x756886] | add byte[0x756886] |
| 0x0040E730 | 0x15ABD | CheckTeam() case 3 | `908A0D` | mov cx, word[0x756886] | mov cl, byte[0x756886] |
| 0x00412882 | 0x15AD5 | 存档加载写入 | `908815` | mov word[0x756886], dx | mov byte[0x756886], dl |
| 0x004175B3 | 0x15AEE | 其他写入路径 | `90880D` | mov word[0x756886], cx | mov byte[0x756886], cl |
| 0x0041A3F2 | 0x15B06 | 存档预览显示 | `0FB615` | movsx edx, word[0x756886] | movzx edx, byte[0x756886] |
| 0x00422AAA | 0x15B25 | 减法运算 | `90280D` | sub word[0x756886] | sub byte[0x756886] |
| 0x00422B32 | 0x15B3D | 加法运算 | `90000D` | add word[0x756886] | add byte[0x756886] |
| 0x00422B81 | 0x15B55 | 比较运算 | `90803D` | cmp word[0x756886] | cmp byte[0x756886] |
| 0x00422B8B | 0x15B6D | 清零 | `9090C6058668750000` | mov word[0x756886], 0 | mov byte[0x756886], 0 |

> **设计意图**：这 18 个补丁将智慧/仁德从 WORD(16位) 降为 BYTE(8位)，使数值范围从 0~65535 缩为 0~255。配合旧版存档编辑器（使用 BYTE 字段 @ SEG2+0x06/0x07）工作。
> **移除原因**：存档编辑器已修正为游戏原生 WORD 格式，这些补丁反而破坏正确数据。

#### C. 金钱上限补丁组（9 个）— 已移除

将金钱上限从默认的 9999 扩展到 30000。

| 游戏地址 | 补丁字节 | 原指令描述 | 新指令描述 |
|---------|---------|-----------|-----------|
| 0x0040CE49 | `9090A1` | mov ax, [imm] | NOP NOP + mov eax |
| 0x0040CE5F | `90010D` | add word → 9999 | add dword → 30000 |
| 0x0040CE66 | `9090` | _mov 30K | _addex |
| 0x0040CE6A | `0FB7` | mov (word) | movzx (扩展为 dword) |
| 0x0040CE6E | `9001` | add (word) | addex (dword) |
| 0x0040CE77 | `0` | mov 0x00 | NoChg |
| 0x0040E4F8 | `90A1` | mov ax (word) | XChg (dword) |
| 0x0040E4FE | `9089` | _mov ax | XChg |
| 0x00412372 | `0` | mov 30K | NoChg |

> **设计意图**：将金钱相关运算从 WORD(16位, 上限65535但检查9999) 扩展为 DWORD(32位)，使上限达到 30000。
> **移除原因**：启动器 tks_patches.json 中已有 `gold_cap_30000` 补丁组，无需 ddraw.dll 重复处理。

#### D. 保留的补丁（17 个）— 当前生效

这些补丁同样来自原始 DLL，修补版中保持不变。

| # | 游戏地址 | 补丁字节 | 原→新 | 推测功能 |
|---|---------|---------|--------|----------|
| 1 | **0x004197D9** | `908B` | movzdx→mov | SEG2 数据读取修正 |
| 2 | **0x0041D0F9** | `0` | push→NoChg | 栈操作修正 |
| 3 | **0x00423AFD** | `0FB7` | mov→movzx | `[ecx+0x29C]` WORD→BYTE 零扩展读取 |
| 4 | **0x00423B04** | `9029` | sub→subex | `sub word[0x756882]` → `sub dword` 减法扩展 |
| 5 | **0x00423B10** | `0FB7` | mov→movzx | `[edx+0x29C]` WORD→BYTE 零扩展读取 |
| 6 | **0x00423B17** | `9001` | add→addex | `add word[0x756882]` → `add dword` 加法扩展 |
| 7 | **0x00423E96** | `0FB7` | mov→movzx | `[edx+0x29C]` WORD→BYTE 零扩展读取 |
| 8 | **0x00423E9D** | `9029` | sub→subex | `sub word[0x756882]` → `sub dword` 减法扩展 |
| 9 | **0x00423EA9** | `0FB7` | mov→movzx | `[edx+0x29C]` WORD→BYTE 零扩展读取 |
| 10 | **0x00423EB0** | `9001` | add→addex | `add word[0x756882]` → `add dword` 加法扩展 |
| 11 | **0x00424DB3** | `9090A1` | movzax→mov | `movzx eax, word[0x756882]` → `mov eax, [0x756882]` |
| 12 | **0x004250A6** | `0FB7` | mov→movzx | `mov ax, [ecx]` → `movzx ax, byte[ecx]` |
| 13 | **0x004250B0** | `903B` | cmpax→cmpeax | `cmp word[0x756882]` → `cmp dword` 比较扩展 |
| 14 | **0x00425149** | `9090A1` | movzax→mov | `movzx eax, word[0x756882]` → `mov eax, [0x756882]` |
| 15 | **0x00425153** | `BA3075FF` | edx30K→edxXK | `mov edx, 0x7530` → `mov edx, 0xFF7530` 立即数替换 |
| 16 | **0x00438D39** | `908B` | movzcx→mov | `movzx ecx, word[0x756882]` → `mov ecx, [0x756882]` |
| 17 | **0x00439123** | `908B` | movzcx→mov | `movzx ecx, word[0x756882]` → `mov ecx, [0x756882]` |

> **功能分析**：
> - **#3~#10 (0x423xxx)**：成对出现的 `movzx` + `sub/add` 补丁，操作的是 `[ecx/edx+0x29C]` 和 `word[0x756882]` (SEG2+0x02, 金钱字段)。将金钱运算从 WORD(16位) 扩展为 DWORD(32位)，支持更大数值。
> - **#11~#17 (0x424xxx~0x439xxx)**：将 `movzx reg, word[0x756882]` 改为直接 `mov reg, [0x756882]`（移除零扩展），以及将 `mov edx, 0x7530`(30000) 改为 `mov edx, 0xFF7530`(16741616)。这些补丁与金钱数值处理相关。
> - **#1~#2**：独立的指令修正，可能是配合其他补丁的辅助修改。

---

## 5. 辅助函数（.text 段）

DLL 在 `.text` 段开头（VA 0x10001000~0x100011F0）包含若干辅助函数。.text 段总共包含 **97 个函数**（以 `push ebp; mov ebp, esp` 为特征识别）。

原始 DLL 中包含 3 处对 SEG2 地址的硬编码引用（均位于辅助函数内）：

| SEG2 地址 | 引用次数 | 文件偏移 | 所在函数 |
|-----------|---------|---------|----------|
| 0x756884 (智慧) | 1 | 0x10B6 | func_10AD（0x756884→0x756887 字节拷贝） |
| 0x756887 (仁德高字节) | 2 | 0x1073, 0x10B1 | func_1070（清零）和 func_10AD（拷贝目标） |

> 注意：这些硬编码引用仍存在于修补版中，但由于补丁字符串已清零，调用链已断开，这些函数不再被触发。

### 函数列表（详细机器码分析）

| VA | 文件偏移 | 入口指令 | 功能 |
|----|---------|----------|------|
| 0x10001000 | 0x1000 | `mov eax, [esp+4]` | **内存写入函数** `func(addr, value)`：`VirtualProtect` → 比较 → `WriteProcessMemory` → 恢复保护 |
| 0x10001030 | 0x1030 | `mov eax, [esp+4]` | **补丁应用入口 1**：push 参数 → call 0x10001050 → 返回静态字符串地址 |
| 0x10001050 | 0x1050 | `mov eax, [esp+4]` | **补丁应用入口 2**：push 参数 → call 0x10001070（清零函数） |
| 0x10001070 | 0x1070 | `push 0` | **清零 0x756887**：`push 0; push 0x756887; call func_1000` — 将 SEG2+0x07 写零 |
| 0x10001080 | 0x1080 | `mov eax, [esp+4]` | **字节拷贝** `copy_byte(dst, src)`：从 src 读 1 字节，调用 func_1000 写入 dst |
| 0x100010AD | 0x10AD | `push 0x756887` | **智慧→仁德高字节拷贝**：`push 0x756887; push 0x756884; call copy_byte` — 将智慧的低位字节拷贝到 0x756887 |
| 0x100010D0 | 0x10D0 | `mov eax, [esp+0C]` | **通用分发器**：3 参数，通过函数指针 `0x4B008C` 调用，然后递归调用 0x10005080 |
| 0x10001110 | 0x1110 | `mov ecx, [0x10018BF8]` | **分发器变体**：先调用 0x100050A0，成功后再调用分发器 |
| 0x10001160 | 0x1160 | `push -1` | **C++ 构造函数**：设置 vtable=0x10011240，初始化成员变量，调用 0x10001C80 |
| 0x100011C0 | 0x11C0 | `mov esi, ecx` | **析构函数**：调用虚函数+0x18，条件释放 |
| 0x100011E0 | 0x11E0 | `push ecx` | **虚函数实现**：设置 vtable，调用 delete，清零成员 |

---

## 6. 配置系统

DLL 从以下 INI 文件读取配置：

| 文件名 | 说明 |
|--------|------|
| `Config.ini` | 主配置 |
| `SanxiaHelper.ini` | 辅助器配置 |
| `Lang.ini` | 语言配置 |

### 可配置选项

| INI Key | 说明 |
|---------|------|
| `NoTmpDat` | 禁用 TmpDat 临时文件读写 |
| `UseDX10` | 使用 DirectX 10 渲染后端 |
| `UseDX11` | 使用 DirectX 11 渲染后端 |
| `ExtraWallet` | 额外金钱包 |
| `AutoClick` | 自动点击 |
| `Teleport` | 传送/瞬移 |
| `FullScreen` | 全屏模式 |
| `NoEnemy` | 无敌模式 |
| `ConvMouse` | 鼠标坐标转换 |
| `CpuDown` | CPU 降频/节能 |
| `Force16BitColor` | 强制 16 位色深 |
| `SpeedUpMenuID` | 加速菜单 ID |
| `WndBottom` / `WndTop` / `WndLeft` / `WndRight` | 窗口位置微调 |
| `HOT_KEY` | 热键配置 |
| `CHEAT_CODE` | 作弊码 |
| `OPTION` | 其他选项 |

---

## 7. 渲染后端支持

### DDraw 代理
- 拦截 `DirectDrawCreate`，代理 `IDirectDraw` 接口
- 日志：`"CreateSurface %d, %X"`, `"SetCooperativeLevel %d, %X"`, `"Surface Count: %d"`

### Direct2D 后端
- 动态加载 `D2d1.dll` → `D2D1CreateFactory`
- 失败日志：`"Create D2D factory failed!"`, `"Create render target failed!"`

### DirectX 11 后端
- 动态加载 `D3D11.dll` → `D3D11CreateDeviceAndSwapChain`
- 内置 **HLSL 着色器**（编译版本 9.29.952.3111）：
  - **Vertex Shader** (vs_4_0)：传递 POSITION + TEXCOORD0
  - **Pixel Shader** (ps_4_0)：Texture2D 采样输出
- 失败日志：`"CreateVertexShader Fail!"`, `"CreatePixelShader Fail!"`

---

## 8. 动态加载的外部模块

| DLL | 用途 | 字符串位置 |
|-----|------|----------|
| `DDraw.dll` | 真实 DirectDraw 实现（代理转发） | 0x1316C |
| `D2d1.dll` | Direct2D 渲染后端 | 0x1314C |
| `D3D11.dll` | DirectX 11 渲染后端 | 0x13210 |
| `SanxiaHelper.dll` | 三国辅助器扩展 | — |
| `MenuScript.dll` | 菜单脚本引擎 | — |
| `ntdll.dll` | `NtSetInformationProcess`（进程信息设置） | 0x130D0 |

---

## 9. 导入的 Windows API

### KERNEL32.dll
`VirtualProtect`, `VirtualAlloc`, `VirtualFree`, `VirtualQuery`, `LoadLibraryA`, `FreeLibrary`, `GetProcAddress`, `GetModuleHandleA`, `GetModuleFileNameA`, `CreateFileA`, `ReadFile`, `WriteFile`, `CloseHandle`, `SetFilePointer`, `GetPrivateProfileIntA`, `WritePrivateProfileStringA`, `GetTickCount`, `GetCurrentProcess`, `GetCurrentThreadId`, `TerminateProcess`, `ExitProcess`, `HeapAlloc/Free/Create/Destroy/ReAlloc/Size`, `TlsAlloc/Free/GetValue/SetValue`, `InterlockedIncrement/Decrement`, `EnterCriticalSection/LeaveCriticalSection/InitializeCriticalSection/DeleteCriticalSection`, `GetLastError`, `SetLastError`, `IsBadReadPtr`, `IsBadWritePtr`, `IsBadCodePtr`, `SetEnvironmentVariableA`, `GetEnvironmentStrings/FreeEnvironmentStrings`, `SetUnhandledExceptionFilter`, `FlushFileBuffers`, `SetEndOfFile`, `GetACP`, `GetOEMCP`, `GetCPInfo`, `MultiByteToWideChar`, `WideCharToMultiByte`, `LCMapStringA/W`, `CompareStringA/W`, `GetStringTypeA/W`, `GetCommandLineA`, `GetVersion`, `GetStartupInfoA`, `GetStdHandle`, `GetFileType`, `SetHandleCount`, `SetStdHandle`, `GetSystemDefaultLangID`, `GetSystemTime`, `GetLocalTime`, `GetTimeZoneInformation`, `RtlUnwind`

### USER32.dll
`MessageBoxA`, `SendMessageA`, `ShowWindow`, `MoveWindow`, `SetWindowPos`, `SetWindowLongA`, `GetWindowLongA`, `SetWindowTextA`, `GetClientRect`, `GetWindowRect`, `GetDesktopWindow`, `GetSystemMetrics`, `ScreenToClient`, `ClientToScreen`, `GetCursorPos`, `SetCursor`, `GetKeyState`, `mouse_event`, `PtInRect`, `SetRect`, `InvalidateRect`, `FillRect`, `SetTimer`, `KillTimer`, `IsWindow`, `IsZoomed`, `IsIconic`, `DestroyWindow`, `CreateWindowEx (implied)`, `LoadIconA`, `LoadCursorA`, `LoadMenuA`, `LoadStringA`, `SetMenu`, `GetMenu`, `EnableMenuItem`, `CheckMenuItem`, `AdjustWindowRectEx`, `CallWindowProcA`

### GDI32.dll
`BitBlt`, `StretchBlt`, `SetStretchBltMode`, `SelectObject`, `DeleteObject`, `DeleteDC`, `CreateCompatibleDC`, `CreateCompatibleBitmap`, `CreateSolidBrush`, `CreatePen`, `Ellipse`, `GetDIBits`, `GetStockObject`, `TextOutA`, `SetBkMode`, `SetBkColor`, `SetTextColor`

### 其他
`SHGetSpecialFolderPathA` (SHELL32), `ImageDirectoryEntryToData` (IMAGEHLP)

---

## 10. 日志系统

DLL 内置日志功能，输出到 `*_log.txt` 文件：

- 格式：`"%.2d:%.2d:%.2d "` (时:分:秒) + 内容
- 调试标记：`"[Bad Ptr]"`, `"[NULL]"`
- Hook 状态：`"Hook Fail %s"`, `"Rude %s at %p"`
- 代码列表：`"CODELIST"` 标记
- 速度显示：`"Speed %d"`, `"%s - %s"`

---

## 附录 A：补丁移除工具

`editor_utils/strip_ddraw_patches.py` 可安全移除以下补丁组：

```bash
python strip_ddraw_patches.py -g wisdom benevolence gold_cap  # 移除全部 27 个
python strip_ddraw_patches.py -g wisdom                        # 只移除智慧 (9个)
python strip_ddraw_patches.py -g all                           # 等同于上面三个
```

---

## 附录 B：补丁机器码对照表（原始游戏 EXE 验证）

以下通过实际读取 `TKS.exe` 原始字节，验证每个补丁的效果：

### 智慧补丁示例

| 地址 | 游戏原始字节 | 原始指令 | 补丁后指令 |
|------|------------|---------|----------|
| 0x0040E187 | `66 01 15 84 68 75 00` | `add word [0x756884], dx` | `add byte [0x756887], dl` |
| 0x0040E720 | `66 8B 15 84 68 75 00` | `mov dx, word [0x756884]` | `mov dl, byte [0x756887]` |
| 0x00412875 | `66 A3 84 68 75 00` | `mov word [0x756884], ax` | `mov byte [0x756887], al` |
| 0x0041A3D2 | `0F BF 0D 84 68 75 00` | `movsx ecx, word [0x756884]` | `movzx ecx, byte [0x756887]` |
| 0x00422B78 | `66 C7 05 84 68 75 00 00 00` | `mov word [0x756884], 0` | `mov byte [0x756887], 0` |

### 仁德补丁示例

| 地址 | 游戏原始字节 | 原始指令 | 补丁后指令 |
|------|------------|---------|----------|
| 0x0040E1FB | `66 01 0D 86 68 75 00` | `add word [0x756886], cx` | `add byte [0x756886], cl` |
| 0x0040E730 | `66 8B 0D 86 68 75 00` | `mov cx, word [0x756886]` | `mov cl, byte [0x756886]` |
| 0x0041A3F2 | `0F BF 15 86 68 75 00` | `movsx edx, word [0x756886]` | `movzx edx, byte [0x756886]` |
| 0x00422B8B | `66 C7 05 86 68 75 00 00 00` | `mov word [0x756886], 0` | `mov byte [0x756886], 0` |

### 金钱补丁示例

| 地址 | 游戏原始字节 | 原始指令 | 补丁后指令 |
|------|------------|---------|----------|
| 0x0040CE49 | `0F B7 05 82 68 75 00` | `movzx eax, word [0x756882]` | `NOP; NOP; mov eax, [0x756882]` |
| 0x0040CE5F | `66 C7 05 82 68 75 00 30 75` | `mov word [0x756882], 30000` | `NOP; add dword [0x756882], ecx` |

---

## 附录 C：DLL 内部函数指针表

`.data` 段开头（VA 0x10013000~0x1001305C）包含 DLL 内部函数指针表：

| VA | 指向 | 功能推测 |
|----|------|----------|
| 0x10013004 | RVA 0x2080 | DDraw 接口创建 |
| 0x10013008 | RVA 0x20C0 | DDraw Surface 管理 |
| 0x1001300C | RVA 0x20E0 | DDraw Flip 处理 |
| 0x10013010 | RVA 0x2100 | DDraw 释放 |
| 0x10013014 | RVA 0x3500 | 渲染管线初始化 |
| 0x10013018 | RVA 0x3520 | 渲染管线清理 |
| 0x1001301C | RVA 0x5D90 | Hook 安装/卸载 |
| 0x10013028 | RVA 0x7DE7 | 补丁字符串解析器 |
| 0x1001302C | RVA 0x9706 | 存档处理 |
| 0x10013030 | RVA 0xE905 | 配置读取 |
| 0x10013034 | RVA 0xC90A | 热键处理 |
| 0x10013040 | RVA 0x97AE | 存档处理变体 |
| 0x1001304C | RVA 0xC91B | 热键处理变体 |
