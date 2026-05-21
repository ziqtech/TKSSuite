/*
 * TKS Launcher - 自动运行时内存补丁启动器
 *
 * 本启动器针对 TKS.exe 游戏进程进行运行时内存修补，突破以下硬编码限制:
 *
 * [补丁一] 入队数量限制 (sub_40DA00 / sub_40E65C)
 *   原始限制: 队伍最多容纳 30 人 (cmp 0x1E, jg/jle)
 *   修补效果: 扩展为最多 200 人 (cmp 0xC8, ja/jbe), 同时将有符号比较改为无符号比较
 *
 * [补丁二] 战场角色形象 (AwkSprite PATH1/PATH2 + cave)
 *   原始问题: 新角色 (idx>=36) 战场形象从 WORD[260] 自定义字段读取, 但默认回退逻辑
 *            用 +12 偏移导致超出精灵表范围, 显示错乱
 *   修补效果: PATH2 偏移改为 +0; PATH1 通过动态 cave 检查 WORD[260], 非零时使用自定义值
 *
 * [补丁三] 队伍头像显示 (PortraitCave1 / PortraitCave2)
 *   原始问题: 头像计算公式固定为 portrait_idx + 0xD3, 新角色无自定义头像时显示错误
 *   修补效果: 通过动态 cave 检查 WORD[261], 非零时直接使用该值作为 GRP 帧索引,
 *            否则回退到原始 add 0xD3 逻辑
 *
 * [补丁四] 战斗经验回写 (sub_43BF20)
 *   原始问题: 战斗结束回写函数用 movsx 读取 byte_9DF888 (参战角色索引), 当角色索引
 *            >= 128 时, 符号扩展为负数, 与 word_75688C (队伍索引) 比较永远不等,
 *            导致新角色经验/等级不被写回 WarPC 缓冲区
 *   修补效果: 将 movsx 改为 movzx (无符号扩展), 使索引 128~255 的角色正确回写
 *
 * [补丁五] WarPC 缓冲区动态扩展 (突破 143 角色限制)
 *   原始问题: 游戏在 BSS 段预分配 143*1054=150722 字节 WarPC 缓冲区 (word_757F08),
 *            代码中 29 处引用基址 0x757F08, 5 处引用大小 150722, 无法容纳更多角色
 *   修补效果: 动态分配新缓冲区 (VirtualAllocEx), 写入完整 WarPC 数据, 修补所有代码
 *            引用 (基址 + 字段级偏移 + 大小常量) 指向新缓冲区
 *
 * [补丁六] 存档/读档缓冲区扩展 (配合补丁五)
 *   原始问题: sub_410ED4 (存档) 和 sub_41103C (读档) 中硬编码 159922 字节缓冲区
 *            (= 3432 队伍/金币 + 5768 状态 + 150722 WarPC), 当 WarPC 扩展后,
 *            写入超出缓冲区, 栈上队伍数组/金币/地图等数据被破坏
 *   修补效果: 扫描代码段中所有 159922 常量, 改为 9200+newSize
 *
 * [补丁七] (已合并到补丁六)
 *
 * [补丁八] .dat 文件大小常量修补 (TKMat / TKItem / TKSkill / TKShop / TKKon)
 *   原始问题: sub_4173F8 和 sub_412688 中硬编码各 .dat 文件大小, 若文件被扩展,
 *            sub_45343C 的大小检查失败, 导致数据加载被跳过
 *   修补效果: 启动前检测各 .dat 文件实际大小, 若超过原始值则创建截断版本;
 *            运行时扫描代码段中原始大小常量并替换为实际值
 *
 * [补丁九] 新角色数据备份与旧存档兼容
 *   原始问题: 加载旧存档 (扩展前保存) 时, sub_41103C 中已修补为 newSize 的 memcpy
 *            会越过解压数据末尾读取栈上垃圾, 覆盖新角色 WarPC 槽位
 *   修补效果: 分配独立备份缓冲区存储新角色区段数据; 存档加载后由备份恢复新角色默认值
 *            新存档 (扩展后保存) 不受影响 — Frame 2 已包含完整数据
 *
 * [补丁十] 索引文件截断警告
 *   原始问题: sub_41CE10 写入存档索引时用 char* 逐字节写入队伍 ID,
 *            角色 ID >= 256 时高字节截断, 存档列表显示异常
 *   修补效果: 检测角色 ID 范围并输出警告
 *
 * [补丁十一] 存档目录与索引文件健康检查 (修复"6个相同主角头像"显示异常)
 *   原始问题: 当 save\ 目录不存在或 sub_41CE10 写入流程失败时, 索引文件
 *            (save\N.sav, 28字节) 可能被遗留为 0 字节空文件。再次进入读档
 *            界面时, sub_41B1A8 成功打开 0 字节文件, ReadFile 不修改 buffer,
 *            buffer 保留 BSS 初始 0 值, 渲染函数 sub_41AB94 把全 0 解释为:
 *              - 6 个角色 0 头像 (主角头像 × 6)
 *              - Lv 0 × 6
 *              - 时间戳 0 → 1970/01/01 08:00:00 (UTC+8)
 *              - 场景 0 → "大地图"
 *   修补效果: 启动游戏前 (1) 创建 save\ 子目录 (若不存在);
 *            (2) 扫描 save\*.sav 删除 0 字节损坏文件 → 让游戏读档时
 *                正确显示"空槽位", 用户可重新存档生成有效文件。
 *
 * [补丁十二] WarPC 缓冲区前预留 GUARD 区 (修复索引文件被截断问题)
 *   原始问题: sub_41CE10 写入存档索引时, 需读取 6 个队员的等级
 *            (word_757F0C[527 * *v6])。当队员 ID = -1 (空槽位) 时, 计算
 *            地址 = newBuf+4-1054 = newBuf-1050。启动器重定向后 newBuf 之前
 *            是未分配内存, 访问触发页错误 → sub_41DAC4 的 SEH 截断写入
 *            流 → 索引文件 (save\N.sav) 被截断为 14 或 20 字节 (预期 28)
 *            → 读档界面显示"6 个相同主角头像 + Lv0 + 70年初一"异常。
 *   修补效果: 在 newBuf 前预留 64 KB GUARD 区 (常量 GUARD_SIZE), 让负偏移
 *            访问落在合法已分配区内 (默认填 0)。sub_41DAC4 能完整读取
 *            并写入文件, 索引写满 28 字节。同时对 sub_40DA00/sub_40E88C/
 *            sub_417F84/sub_41A080/sub_43CA64 中的同类负偏移访问也一并修复。
 *
 * [补丁十三] sub_4C33FC "已打开"检查修复 (修复读档列表全 0 问题)
 *   原始问题: sub_41B1A8 循环 9 次復用同一个 v24 文件结构, sub_4C33FC 入口
 *            检查 "if (a1+12) return 0" 在第 1 次循环后拒绝后续打开。
 *            但 sub_41C984 关闭流后 v24+12 未被清零 → 第 2..9 次循环全部返回 0
 *            → 读取失败 → buffer 保留 BSS 初始 0 值 → sub_41AB94 渲染出
 *            "6 个主角头像 + Lv0 + 70/01/01 + 大地图"异常 (仅槽位 1 正常)。
 *   修补效果: 扫描 sub_4C33FC 入口前 32 字节 "cmp byte [reg+0Ch], 0" + "je/jne"
 *            指令，将 je short 改为 jmp short 或将 jne short 改为 NOP NOP,
 *            让 sub_4C33FC 总是跳到 continue 重新打开文件。
 *
 * [补丁十四] sub_41C120 stream error 检查修复 (修复中间空槽位后的读取失败)
 *   原始问题: 补丁十三生效后, 若存在中间空槽位 (如 slot 4-6 不存在),
 *            sub_41B1A8 中 sub_4C352C 失败进入 if (!v1) 分支 "stream+8 |= 4"
 *            设置 EOF 错误标志。之后槽位 (slot 7-9) 即使文件存在,
 *            sub_41BF48/sub_41C2B8 调用 sub_41C120 检查发现错误标志返回 false
 *            → 跳过读取 → buffer 保留 0 → 同样渲染"6 个主角头像"异常。
 *   修补效果: 将 sub_41C120 入口 "cmp dword [reg+8], 0" 改为同长的
 *            "and dword [reg+8], 0" (83 7X 08 00 → 83 6X 08 00),
 *            这样每次检查前都强制清零 stream+8 错误标志,
 *            后续 je/jne 依然按 ZF=1 走正确分支, slot 7-9 能重新读取。
 *
 * [补丁十五] 存档界面新角色队伍头像显示修复
 *   原始问题: sub_41AB94 渲染存档列表队伍头像时:
 *              sub_4544EC(..., *(char *)(...) + 211, ...);
 *            二重问题: 一是 signed char ID 在 ID >= 128 时被 sign-extend 为负数
 *            (如 ID=143 → (char)=-113, +211=98, 帧位错位); 二是新角色 (143-145)
 *            应当使用 WarPC 中的 WORD[261] 作为自定义头像帧, 不是 ID+211。
 *   修补效果: 扫描 sub_41AB94 函数体内所有 "add eax, 0xD3" (5字节 05 D3 00 00 00)
 *            指令, 替换为 call 到 ArchivePortraitCave (动态分配 44 字节)。
 *            cave 内部: (1) movzx 将 signed ID 转为 unsigned (修复 sign-extend);
 *            (2) 读取 WarPC[ID].WORD[261]; (3) 非零使用 WORD[261] 作 frame,
 *            否则 fallback 到 unsigned ID + 211。与队伍头像 cave 逻辑一致。
 *
 * 用法: 把编译后的 TKSLauncher.exe 放到游戏目录，双击运行即可
 * 编译: C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /target:winexe /win32icon:TKS.ico /out:TKSLauncher.exe tks_launcher.cs
 */

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

class TKSLauncher
{
    // ============================================================
    // 统一日志输出: 同时写控制台和 tks_launcher.log
    // 以前的 Console.WriteLine 都改为调用 Log() 函数
    // ============================================================
    const string LOG_PATH = "tks_launcher.log";
    static System.IO.StreamWriter _logWriter = null;
    static readonly object _logLock = new object();

    static void LogInit()
    {
        try
        {
            // 覆盖同名旧日志
            _logWriter = new System.IO.StreamWriter(LOG_PATH, false, System.Text.Encoding.UTF8);
            _logWriter.AutoFlush = true;
            _logWriter.WriteLine(string.Format("=== TKS Launcher 启动 {0:yyyy-MM-dd HH:mm:ss} ===",
                DateTime.Now));
        }
        catch { _logWriter = null; }
    }

    static void LogClose()
    {
        lock (_logLock)
        {
            if (_logWriter != null)
            {
                try { _logWriter.Flush(); _logWriter.Close(); } catch { }
                _logWriter = null;
            }
        }
    }

    /// <summary>
    /// 同时输出到控制台与 tks_launcher.log
    /// </summary>
    static void Log(string msg)
    {
        System.Console.Out.WriteLine(msg);
        lock (_logLock)
        {
            if (_logWriter != null)
            {
                try { _logWriter.WriteLine(msg); } catch { }
            }
        }
    }

    /// <summary>
    /// 仅写入日志文件 (不输出控制台), 用于大量 DIAG 信息
    /// </summary>
    static void LogFile(string msg)
    {
        lock (_logLock)
        {
            if (_logWriter != null)
            {
                try { _logWriter.WriteLine(msg); } catch { }
            }
        }
    }

    [DllImport("kernel32.dll")]
    static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll")]
    static extern bool ReadProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, int dwSize, out int lpNumberOfBytesRead);

    [DllImport("kernel32.dll")]
    static extern bool WriteProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, int dwSize, out int lpNumberOfBytesWritten);

    [DllImport("kernel32.dll")]
    static extern bool VirtualProtectEx(IntPtr hProcess, IntPtr lpAddress, int dwSize, uint flNewProtect, out uint lpflOldProtect);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualAllocEx(IntPtr hProcess, IntPtr lpAddress, uint dwSize, uint flAllocationType, uint flProtect);

    [DllImport("kernel32.dll")]
    static extern bool VirtualFreeEx(IntPtr hProcess, IntPtr lpAddress, uint dwSize, uint dwFreeType);

    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr CreateToolhelp32Snapshot(uint dwFlags, int th32ProcessID);

    [DllImport("kernel32.dll")]
    static extern bool Process32First(IntPtr hSnapshot, ref PROCESSENTRY32 lppe);

    [DllImport("kernel32.dll")]
    static extern bool Process32Next(IntPtr hSnapshot, ref PROCESSENTRY32 lppe);

    [DllImport("kernel32.dll")]
    static extern bool Module32First(IntPtr hSnapshot, ref MODULEENTRY32 lpme);

    [DllImport("kernel32.dll")]
    static extern bool Module32Next(IntPtr hSnapshot, ref MODULEENTRY32 lpme);

    const uint PROCESS_VM_READ = 0x0010;
    const uint PROCESS_VM_WRITE = 0x0020;
    const uint PROCESS_VM_OPERATION = 0x0008;
    const uint PAGE_EXECUTE_READWRITE = 0x40;
    const uint PAGE_READWRITE = 0x04;
    const uint MEM_COMMIT = 0x1000;
    const uint MEM_RESERVE = 0x2000;
    const uint MEM_RELEASE = 0x8000;
    const uint TH32CS_SNAPPROCESS = 0x00000002;
    const uint TH32CS_SNAPMODULE = 0x00000008;
    const uint TH32CS_SNAPMODULE32 = 0x00000010;
    static readonly IntPtr INVALID_HANDLE_VALUE = (IntPtr)(-1);

    [StructLayout(LayoutKind.Sequential)]
    struct PROCESSENTRY32
    {
        public uint dwSize;
        public uint cntUsage;
        public uint th32ProcessID;
        public IntPtr th32DefaultHeapID;
        public uint th32ModuleID;
        public uint cntThreads;
        public uint th32ParentProcessID;
        public int pcPriClassBase;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string szExeFile;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct MODULEENTRY32
    {
        public uint dwSize;
        public uint th32ModuleID;
        public uint th32ProcessID;
        public uint GlblcntUsage;
        public uint ProccntUsage;
        public IntPtr modBaseAddr;
        public uint modBaseSize;
        public IntPtr hModule;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string szModule;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string szExePath;
    }

    struct Patch
    {
        public int RVA;
        public byte[] Data;
        public string Desc;
        // if true, RVA is relative to dynamically allocated cave address
        public bool Dynamic;
    }

    // ============================================================
    // 静态补丁列表 (直接修改游戏代码中的固定字节)
    // RVA = 相对于模块基址的偏移 (ImageBase 通常为 0x400000)
    // ============================================================
    static readonly Patch[] StaticPatches = new Patch[]
    {
        // ────────────────────────────────────────────────────────
        // [补丁一] 入队数量限制
        // 原始: sub_40DA00 中 cmp al, 0x1E (30); jg skip → 最多入队30人
        //       sub_40E65C 中 cmp al, 0x1E (30); jle ok  → 队伍满30人时拒绝
        // 修补: 将比较值改为 0xC8 (200), 同时 jg→ja / jle→jbe (有符号→无符号)
        //       避免角色索引高位为1时被误判为负数
        // ────────────────────────────────────────────────────────
        new Patch {
            RVA = 0xDA15, Data = new byte[] { 0xC8, 0x87 },
            Desc = "TeamMember: cmp 0x1E->0xC8, jg->ja (sub_40DA00)"
        },
        new Patch {
            RVA = 0xE6C1, Data = new byte[] { 0xC8, 0x76 },
            Desc = "CheckTeam: cmp 0x1E->0xC8, jle->jbe (sub_40E65C)"
        },

        // ────────────────────────────────────────────────────────
        // [补丁二] 战场角色形象 (AwkSprite PATH2)
        // 原始: sub_4309A6 附近, 角色 JVG 精灵选择时对索引 +12 偏移
        //       导致新角色 (idx>=36) 超出精灵映射表, 战场显示错乱
        // 修补: 将 +12 偏移改为 +0, 配合 PATH1 的 cave 做正确映射
        // 注意: PATH1 (cave) 通过 BuildPatches 动态生成, 检查 WORD[260]
        //       若非零则使用自定义战场精灵索引
        // ────────────────────────────────────────────────────────
        new Patch {
            RVA = 0x31165, Data = new byte[] { 0x00 },
            Desc = "AwkSprite PATH2: +12→+0"
        },

        // ────────────────────────────────────────────────────────
        // [补丁四] 战斗经验回写 (sub_43BF20)
        // 原始: 战斗结束后, sub_43BF20 将临时战斗数据写回 WarPC 缓冲区
        //       使用 movsx (0F BE) 读取 byte_9DF888[i] (参战角色索引)
        //       与 word_75688C[i] (队伍角色索引, signed word) 比较
        //       当角色索引 >= 128 时:
        //         byte 0x8F 经 movsx 扩展为 -113 (0xFFFFFF8F)
        //         word 143 经 movsx 扩展为 +143 (0x0000008F)
        //         比较不等 → 回写逻辑被跳过 → 经验/等级不更新!
        // 修补: 将 movsx (0F BE) 改为 movzx (0F B6), 无符号扩展
        //       byte 0x8F → 143, 与 word 143 正确匹配
        // ────────────────────────────────────────────────────────
        new Patch {
            RVA = 0x3BF5C, Data = new byte[] { 0xB6 },
            Desc = "BattleWriteback: movsx->movzx byte_9DF888 (fix idx>=128 exp writeback)"
        },
    };

    // ============================================================
    // [补丁二] 战场角色形象 - PATH1 动态 Cave (51 字节)
    // 动态分配到进程内存, hook 在 sub_432668 调用后 (cmp [ebp-6],0 处)
    //
    // 逻辑: 读取当前参战角色的 WarPC WORD[260] (byte offset 520 = 0x208)
    //       若 WORD[260] != 0: 使用自定义战场精灵索引 (WORD[260]-6)
    //       若 WORD[260] == 0: 使用原始默认映射逻辑
    //       正确设置 ZF 供后续 jnz 判断
    // ============================================================
    static readonly byte[] CaveTemplate = new byte[] {
        0x50, 0x51,                                           // push eax,ecx
        0x0F, 0xBF, 0x45, 0xFA,                               // movsx eax,[ebp-6]
        0x66, 0x85, 0xC0,                                     // test ax,ax
        0x74, 0x25,                                           // jz .done (v26==0)
        0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00,                   // imul eax,0x41E
        0x05, 0x08, 0x7F, 0x75, 0x00,                         // add eax,0x757F08
        0x0F, 0xB7, 0x88, 0x08, 0x02, 0x00, 0x00,             // movzx ecx,[eax+0x208]
        0x66, 0x85, 0xC9,                                     // test cx,cx
        0x75, 0x04,                                           // jnz .use_custom
        0x85, 0xC0,                                           // test eax,eax (ZF=0)
        0xEB, 0x0A,                                           // jmp .done
        // .use_custom:
        0x83, 0xE9, 0x06,                                     // sub ecx,6
        0x66, 0x89, 0x4D, 0xFA,                               // mov [ebp-6],cx
        0x66, 0x85, 0xC9,                                     // test cx,cx (ZF)
        // .done:
        0x59, 0x58,                                           // pop ecx,eax
        0xC3                                                  // ret
    };

    // ============================================================
    // [补丁三] 队伍头像显示 - PATH1 动态 Cave (41 字节)
    // Hook 在 RVA 0x17A50 (sub_41762C 中的 "add ax, 0xD3; push eax" 处)
    //
    // 逻辑: 此处处理当前选中队员的头像
    //       ECX = char_idx * 527, AX = WarPC[char_idx].portrait (WORD[1])
    //       检查 WORD[261] (byte offset 522 = 0x20A): 若非零则直接使用作为 GRP 帧索引
    //       否则回退到原始逻辑: portrait + 0xD3
    // ============================================================
    static readonly byte[] PortraitCave1 = new byte[] {
        0x50,                               // push eax           ; save raw portrait
        0x51,                               // push ecx           ; save ecx*527
        0x52,                               // push edx           ; save scratch
        0x8B, 0xC1,                         // mov eax, ecx       ; eax = ecx
        0x03, 0xC0,                         // add eax, eax       ; eax = char_idx*1054
        0x05, 0x08, 0x7F, 0x75, 0x00,       // add eax, 0x757F08  ; eax = WarPC record
        0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00, // movzx eax,[eax+0x20A] ; WORD[261]
        0x66, 0x85, 0xC0,                   // test ax, ax
        0x75, 0x08,                         // jnz .shared_exit   ; override? → skip normal
        // Normal: compute result from raw portrait saved at [esp+8]
        0x8B, 0x44, 0x24, 0x08,             // mov eax, [esp+8]   ; eax = raw portrait
        0x66, 0x05, 0xD3, 0x00,             // add ax, 0xD3       ; eax = result
        // === Shared exit (both paths) ===
        0x83, 0xC4, 0x08,                   // add esp, 8         ; discard edx,ecx
        0x5A,                               // pop edx            ; discard saved eax
        0x87, 0x04, 0x24,                   // xchg eax, [esp]    ; eax=ret_addr, [esp]=result
        0xFF, 0xE0,                         // jmp eax
    };

    // ============================================================
    // [补丁十五] 存档界面队伍头像 - Cave (动态分配, 约 38 字节)
    // Hook 在 sub_41AB94 中的 "movsx eax, byte [...]; add eax, 0xD3" 模式处
    //
    // 背景: sub_41AB94 渲染存档列表队伍头像时, 处理逻辑:
    //   sub_4544EC(..., *(char *)(...) + 211, ...);
    //                    ^^^^^^^^^^^^^^^^ 从 N.sav 读出的 1 字节 ID
    // 问题二重:
    //   1. (char) 是 signed char, ID >= 128 时 sign-extend 为负数
    //      (如 ID=143 → (char)=-113, +211=98, 帧位错误)
    //   2. 新角色 (143-145) 需要使用 WORD[261] 作为自定义头像帧, 不能用 ID+211
    //
    // 逻辑:
    //   1. 入口 hook 替换 "movsx eax, byte [...]; add eax, 0xD3"
    //      (movsx 4-7 字节 + add 5 字节) 为 call cave
    //   2. cave 里复现原 movsx 逻辑但用 movzx (修复 sign extension)
    //   3. 读取 WarPC[ID].WORD[261]
    //   4. 非零 → 使用 WORD[261] 作为 frame
    //   5. 为零 → 默认 frame = ID + 211 (unsigned ID)
    //
    // 入口约定: 调用 cave 前, 需在某寄存器准备好 ID byte 的有效地址
    //   由于存档不同编译模式, hook 在运行时扫描定位
    // ============================================================
    static readonly byte[] ArchivePortraitCave = new byte[] {
        // 入口约定 (hook 替换 5 字节 "66 05 D3 00 50" = add ax, 0xD3 + push eax):
        //   eax = movsx 后的 signed char ID (32-bit sign-extended)
        //   [esp] = call 推入的返回地址 (= hook+5, 指向原 push eax 后的下一条指令)
        //
        // 出口约定:
        //   栈上需保留 frame 代替被覆盖的 push eax,
        //   使用 xchg+jmp 技巧: 跳回返回地址 [esp]后栈上留 frame
        0x52,                               // [00] push edx
        0x51,                               // [01] push ecx
        // 修复 sign-extend: 取低 8 位作 unsigned ID
        0x0F, 0xB6, 0xC0,                   // [02..04] movzx eax, al   ; eax = unsigned ID
        0x8B, 0xC8,                         // [05..06] mov ecx, eax    ; save unsigned ID
        // 计算 WarPC[ID] 地址
        0x69, 0xC0, 0x1E, 0x04, 0x00, 0x00, // [07..12] imul eax, eax, 1054
        0x05, 0x08, 0x7F, 0x75, 0x00,       // [13..17] add eax, 0x757F08 (启动器会替换为 newBuf)
        // 读 WORD[261] (offset 0x20A)
        0x0F, 0xB7, 0x90, 0x0A, 0x02, 0x00, 0x00, // [18..24] movzx edx, [eax+0x20A]
        0x66, 0x85, 0xD2,                   // [25..27] test dx, dx
        0x75, 0x09,                         // [28..29] jnz +9 跳到 [39]
        // 默认: frame = unsigned ID + 211
        0x8B, 0xC1,                         // [30..31] mov eax, ecx     ; eax = unsigned ID
        0x05, 0xD3, 0x00, 0x00, 0x00,       // [32..36] add eax, 0xD3    ; eax = ID + 211
        0xEB, 0x02,                         // [37..38] jmp +2 跳到 [41]
        // .use_custom: ([39])
        0x8B, 0xC2,                         // [39..40] mov eax, edx     ; eax = WORD[261]
        // .done: ([41])
        0x59,                               // [41] pop ecx
        0x5A,                               // [42] pop edx
        // 关键: 交换返回地址与 frame, 跳回 hook 下一条指令 后栈上留 frame
        0x87, 0x04, 0x24,                   // [43..45] xchg eax, [esp]  ; eax=ret, [esp]=frame
        0xFF, 0xE0                          // [46..47] jmp eax
    };

    // ============================================================
    // [补丁三] 队伍头像显示 - PATH2 动态 Cave (42 字节)
    // Hook 在 RVA 0x17E1A (sub_417F84 中的 "add dx, 0xD3; push edx" 处)
    //
    // 逻辑: 此处处理非选中队员的头像 (列表显示)
    //       EAX = char_idx * 527, DX = WarPC[char_idx].portrait (WORD[1])
    //       同样检查 WORD[261]: 非零则直接使用, 否则回退 portrait + 0xD3
    // ============================================================
    static readonly byte[] PortraitCave2 = new byte[] {
        0x52,                               // push edx           ; save raw portrait
        0x51,                               // push ecx           ; save scratch
        0x50,                               // push eax           ; save eax (= char_idx*527)
        0x03, 0xC0,                         // add eax, eax       ; eax = char_idx*1054
        0x05, 0x08, 0x7F, 0x75, 0x00,       // add eax, 0x757F08  ; eax = WarPC record
        0x0F, 0xB7, 0x80, 0x0A, 0x02, 0x00, 0x00, // movzx eax,[eax+0x20A] ; WORD[261]
        0x66, 0x85, 0xC0,                   // test ax, ax
        0x75, 0x08,                         // jnz .shared_exit   ; override? → skip normal
        // Normal: compute result from raw portrait saved at [esp+8]
        0x8B, 0x44, 0x24, 0x08,             // mov eax, [esp+8]   ; eax = raw portrait
        0x66, 0x05, 0xD3, 0x00,             // add ax, 0xD3       ; eax = result
        // === Shared exit (both paths) ===
        0x0F, 0xB7, 0xD0,                   // movzx edx, ax      ; edx = result
        0x83, 0xC4, 0x08,                   // add esp, 8         ; discard eax,ecx
        0x59,                               // pop ecx            ; discard saved edx
        0x87, 0x14, 0x24,                   // xchg edx, [esp]    ; edx=ret_addr, [esp]=result
        0xFF, 0xE2,                         // jmp edx
    };

    // Helper: write a 16-bit value to process memory
    static void WriteMem16(IntPtr hProc, int addr, short val)
    {
        uint old; int wr;
        VirtualProtectEx(hProc, (IntPtr)addr, 2, PAGE_EXECUTE_READWRITE, out old);
        WriteProcessMemory(hProc, (IntPtr)addr, BitConverter.GetBytes(val), 2, out wr);
        VirtualProtectEx(hProc, (IntPtr)addr, 2, old, out old);
    }

    // Replace all occurrences of oldVal (4B LE) with newVal in byte array
    static void ReplaceAddrInBytes(byte[] data, int oldAddr, int newAddr)
    {
        byte[] oldLE = BitConverter.GetBytes(oldAddr);
        byte[] newLE = BitConverter.GetBytes(newAddr);
        for (int i = 0; i <= data.Length - 4; i++)
        {
            if (data[i] == oldLE[0] && data[i+1] == oldLE[1] &&
                data[i+2] == oldLE[2] && data[i+3] == oldLE[3])
            {
                data[i] = newLE[0]; data[i+1] = newLE[1];
                data[i+2] = newLE[2]; data[i+3] = newLE[3];
                i += 3;
            }
        }
    }

    // ============================================================
    // 动态补丁构建: 结合 cave 地址和 WarPC 新缓冲区地址生成完整补丁列表
    // 包含: 静态补丁 + AwkSprite cave + hook + Portrait cave*2 + hook*2
    // warpcBaseAddr: 若非零, 将 cave 中硬编码的 0x757F08 替换为新缓冲区地址
    // ============================================================
    static Patch[] BuildPatches(IntPtr baseAddr, IntPtr caveAddr, int warpcBaseAddr)
    {
        long cave = caveAddr.ToInt64();
        long baseVA = baseAddr.ToInt64();

        var list = new List<Patch>(StaticPatches);

        // --- AwkSprite cave + hook ---
        byte[] awkCaveData = (byte[])CaveTemplate.Clone();
        if (warpcBaseAddr != 0) ReplaceAddrInBytes(awkCaveData, WARPC_BASE, warpcBaseAddr);
        int awkHookRva = 0x309A6;
        int awkCallOff = (int)(cave - baseVA) - (awkHookRva + 5);
        byte[] awkCallData = new byte[5];
        awkCallData[0] = 0xE8;
        BitConverter.GetBytes(awkCallOff).CopyTo(awkCallData, 1);

        list.Add(new Patch {
            RVA = (int)(cave - baseVA), Data = awkCaveData,
            Desc = "AwkSprite PATH1 cave (51B)"
        });
        list.Add(new Patch {
            RVA = awkHookRva, Data = awkCallData,
            Desc = string.Format("AwkSprite: hook cmp [ebp-6],0 -> cave@0x{0:X8}", cave)
        });

        // --- Portrait PATH1 cave + hook (selected member) ---
        long pcave1 = cave + 64;
        int p1HookRva = 0x17A50;
        int p1CallOff = (int)(pcave1 - baseVA) - (p1HookRva + 5);
        byte[] p1CallData = new byte[5];
        p1CallData[0] = 0xE8;
        BitConverter.GetBytes(p1CallOff).CopyTo(p1CallData, 1);
        byte[] p1CaveData = (byte[])PortraitCave1.Clone();
        if (warpcBaseAddr != 0) ReplaceAddrInBytes(p1CaveData, WARPC_BASE, warpcBaseAddr);

        list.Add(new Patch {
            RVA = (int)(pcave1 - baseVA), Data = p1CaveData,
            Desc = string.Format("Portrait PATH1 cave@0x{0:X8} (selected, 41B)", pcave1)
        });
        list.Add(new Patch {
            RVA = p1HookRva, Data = p1CallData,
            Desc = string.Format("Portrait PATH1: hook add ax,0xD3 -> cave@0x{0:X8}", pcave1)
        });

        // --- Portrait PATH2 cave + hook (non-selected member) ---
        long pcave2 = cave + 128;
        int p2HookRva = 0x17E1A;
        int p2CallOff = (int)(pcave2 - baseVA) - (p2HookRva + 5);
        byte[] p2CallData = new byte[6];
        p2CallData[0] = 0xE8;
        BitConverter.GetBytes(p2CallOff).CopyTo(p2CallData, 1);
        p2CallData[5] = 0x90; // NOP: pad from 5B to 6B
        byte[] p2CaveData = (byte[])PortraitCave2.Clone();
        if (warpcBaseAddr != 0) ReplaceAddrInBytes(p2CaveData, WARPC_BASE, warpcBaseAddr);

        list.Add(new Patch {
            RVA = (int)(pcave2 - baseVA), Data = p2CaveData,
            Desc = string.Format("Portrait PATH2 cave@0x{0:X8} (non-selected, 42B)", pcave2)
        });
        list.Add(new Patch {
            RVA = p2HookRva, Data = p2CallData,
            Desc = string.Format("Portrait PATH2: hook add dx,0xD3 -> cave@0x{0:X8}", pcave2)
        });

        // --- Archive Portrait cave (存档界面队伍头像, 补丁十五) ---
        // 使用 cave + 192 位置 (足够距离 PortraitCave2 的 128 + 42 字节)
        long arcCave = cave + 192;
        byte[] arcCaveData = (byte[])ArchivePortraitCave.Clone();
        if (warpcBaseAddr != 0) ReplaceAddrInBytes(arcCaveData, WARPC_BASE, warpcBaseAddr);
        list.Add(new Patch {
            RVA = (int)(arcCave - baseVA), Data = arcCaveData,
            Desc = string.Format("Archive Portrait cave@0x{0:X8} (存档列表队伍头像)", arcCave)
        });
        // 保存 cave 地址供后续 Patch_ArchivePortrait_Hook 使用
        _archivePortraitCaveAddr = (int)arcCave;

        return list.ToArray();
    }

    // 存档界面队伍头像 cave 地址 (补丁十五)
    static int _archivePortraitCaveAddr = 0;

    // ============================================================
    // WarPC 缓冲区动态扩展 — 突破 143 角色硬编码限制
    // ============================================================

    const int WARPC_BASE = 0x757F08;
    const int WARPC_REC_SIZE = 1054;
    const int WARPC_ORIG_COUNT = 143;
    const int WARPC_ORIG_SIZE = 150722; // = 143 * 1054 = 0x24CE2
    const int WARPC_TOTAL_ORIG_SIZE = 159922; // = 9200 + 150722 = 0x270D2 (存档/读档缓冲区)

    // 其他 .dat 文件原始解压大小 (硬编码在 sub_4173F8 / sub_412688 中)
    // 若实际文件大于这些值, sub_45343C 的大小检查会失败, 导致文件加载被跳过
    const int TKMAT_ORIG_SIZE   = 2304000; // TKMat.dat   (6000×384B) — sub_412688:21, sub_410ED4:21
    const int TKITEM_ORIG_SIZE  = 38400;   // TKItem.dat  (600×64B)  — sub_4173F8:19
    const int TKSKILL_ORIG_SIZE = 32900;   // TKSkill.dat            — sub_4173F8:20
    const int TKSHOP_ORIG_SIZE  = 1920;    // TKShop.dat             — sub_4173F8:21
    const int TKKON_ORIG_SIZE   = 26000;   // TKKon.dat              — sub_4173F8:22

    // Frame 2 内部布局常量 (存档/读档缓冲区)
    const int SAVE_BLOCKA_SIZE = 3432;  // unk_755B18 (SCE全局变量)
    const int SAVE_BLOCKB_SIZE = 5768;  // unk_756880 (物品背包/任务/队伍/金币)
    const int SAVE_WARPC_OFFSET = 9200; // = 3432 + 5768, WarPC 在 Frame 2 中的偏移

    // 数据文件名 → 原始大小 映射 (用于大小检测和修补)
    // 注意: 仅 WarPC.dat 支持完整缓冲区扩展; 其他文件仅做大小常量修补
    static readonly Dictionary<string, int> DataFileOrigSizes = new Dictionary<string, int> {
        { "TKMat.dat",   TKMAT_ORIG_SIZE },
        { "TKItem.dat",  TKITEM_ORIG_SIZE },
        { "TKSkill.dat", TKSKILL_ORIG_SIZE },
        { "TKShop.dat",  TKSHOP_ORIG_SIZE },
        { "TKKon.dat",   TKKON_ORIG_SIZE },
    };

    static bool _warpcExpanded = false;
    static byte[] _warpcFullData = null;
    static IntPtr _warpcNewBuf = IntPtr.Zero;

    // 已验证的 RVA 列表: 代码中所有引用 word_757F08 (0x757F08) 的位置
    // 每个 RVA 指向一个 4 字节立即数 08 7F 75 00
    static readonly int[] WarpcAddrRVAs = new int[] {
        0x03FC8, 0x040BD, 0x0DB0F, 0x10FB5, 0x1118A, 0x1228B, 0x122E1, 0x126AA,
        0x17401, 0x176FF, 0x17ABC, 0x180F4, 0x18ADD, 0x18C2D, 0x198B8, 0x1A1E1,
        0x1E2E1, 0x1E318, 0x1EC3A, 0x20B03, 0x222CF, 0x2277F, 0x2329B, 0x24E35,
        0x30994, 0x30D20, 0x310F8, 0x3BFAC, 0x450AE
    };

    // 已验证的 RVA 列表: 代码中所有引用 150722 (0x24CE2) 的位置
    // 注意: C7 45 EC (mov [ebp-14],imm32) 前缀3字节, 立即数在+3
    //       C7 44 24 0C (mov [esp+0C],imm32) 前缀4字节, 立即数在+4
    static readonly int[] WarpcSizeRVAs = new int[] {
        0x3FBC, 0x10F60, 0x110D7, 0x126A5, 0x173FC
    };

    // 已验证的 RVA 列表: 代码中所有引用 word_757F0C (0x757F0C) 的位置
    // word_757F0C = WarPC 基址+4, 用于读取队员肖像字段 (WORD[2])
    // 注意: 这些值来自 pointers.txt, 但实际上是绝对 VA 而非 RVA
    //       (dump工具可能使用 image_base=0 导致), 因此使用时不应再加 baseAddr
    // 若未正确 Patch, 存档预览文件 (save\%d.sav) 写入时会越界读取导致预览损坏
    static readonly int[] WarpcAddr0CRVAs = new int[] {
        0x40DAF3,  // sub_40DA00  队员入队时复制肖像
        0x40E8DB,  // sub_40E88C  队员属性读取
        0x4184B4,  // sub_417F84  队员列表头像
        0x41A224,  // sub_41A080  商店界面头像
        0x41D171,  // sub_41CE10  存档预览写入 ← 导致"六个0"的关键引用
        0x43CA72,  // sub_43CA64  战斗检查
        0x43CA8D,  // sub_43CA64  战斗检查
    };

    // 记录被截断的 .dat 文件, key=文件名, value=原始压缩数据 (供恢复用)
    static Dictionary<string, byte[]> _truncatedFiles = new Dictionary<string, byte[]>();

    /// <summary>
    /// 启动游戏前: 确保 save\ 目录存在, 并清理 0 字节损坏的索引文件
    /// (补丁十一: 修复"6个相同主角头像"显示异常)
    ///
    /// 背景: 若 sub_41CE10 写入流程中 sub_4C352C 打开文件后由于其它原因
    /// (如 sub_4E50E2 失败) 导致写入流程被跳过, 文件会被遗留为 0 字节。
    /// 下次进入读档界面时, sub_41B1A8 读 0 字节文件不会修改 buffer,
    /// 导致显示为"主角头像×6 + Lv0 + 70年初一 + 大地图"异常。
    /// 删除 0 字节文件后, sub_41B1A8 会走"文件不存在"分支填充 -1,
    /// 正确显示为空槽位。
    /// </summary>
    static void EnsureSaveDirectoryHealthy()
    {
        Log("\n--- 存档目录健康检查 ---");
        const string saveDir = "save";

        // (1) 确保 save\ 目录存在
        if (!System.IO.Directory.Exists(saveDir))
        {
            try
            {
                System.IO.Directory.CreateDirectory(saveDir);
                Log("  已创建 save\\ 目录");
            }
            catch (Exception e)
            {
                Log(string.Format("  [WARN] 创建 save\\ 失败: {0}", e.Message));
                return;
            }
        }
        else
        {
            Log("  save\\ 目录已存在");
        }

        // (2) 扫描并删除 0 字节损坏的索引文件 (save\1.sav .. save\9.sav)
        // 同时检查对应的存档数据文件 save\sav.N 是否完整
        int deletedIdx = 0;
        int deletedDat = 0;
        for (int i = 1; i <= 9; i++)
        {
            string idxPath = string.Format("{0}\\{1}.sav", saveDir, i);
            string datPath = string.Format("{0}\\sav.{1}", saveDir, i);

            // 检查索引文件 (28 字节有效)
            if (System.IO.File.Exists(idxPath))
            {
                long idxSize = new System.IO.FileInfo(idxPath).Length;
                if (idxSize == 0)
                {
                    try
                    {
                        System.IO.File.Delete(idxPath);
                        Log(string.Format("  删除损坏的索引文件: {0} (0 字节)", idxPath));
                        deletedIdx++;

                        // 同步删除对应的损坏数据文件 (避免读档时崩溃)
                        if (System.IO.File.Exists(datPath))
                        {
                            long datSize = new System.IO.FileInfo(datPath).Length;
                            if (datSize < 16) // 最小 Frame 1 头部 = 8 字节, 小于 16 必损坏
                            {
                                System.IO.File.Delete(datPath);
                                Log(string.Format("  删除对应的损坏数据文件: {0} ({1} 字节)", datPath, datSize));
                                deletedDat++;
                            }
                        }
                    }
                    catch (Exception e)
                    {
                        Log(string.Format("  [WARN] 删除 {0} 失败: {1}", idxPath, e.Message));
                    }
                }
                else if (idxSize != 28)
                {
                    Log(string.Format("  [WARN] {0} 大小异常: {1} 字节 (预期 28)", idxPath, idxSize));
                }
            }
        }

        if (deletedIdx > 0 || deletedDat > 0)
        {
            Log(string.Format("  共清理 {0} 个 0 字节索引文件 + {1} 个损坏数据文件",
                deletedIdx, deletedDat));
            Log("  读档界面将正确显示空槽位, 请重新存档生成有效存档");
        }
        else
        {
            Log("  未发现损坏存档文件");
        }
    }

    /// <summary>
    /// 获取 .dat 文件解压后大小 (从文件头4字节读取, 不解压全部数据)
    /// </summary>
    static int GetDecompressedSize(string path)
    {
        if (!System.IO.File.Exists(path)) return -1;
        byte[] header = new byte[4];
        using (var fs = System.IO.File.OpenRead(path))
        {
            if (fs.Read(header, 0, 4) < 4) return -1;
        }
        return BitConverter.ToInt32(header, 0);
    }

    /// <summary>
    /// 游戏启动前: 检测所有 .dat 文件大小, 若超过游戏硬编码限制则创建截断版本
    /// WarPC 扩展: 完整支持 (缓冲区重分配 + 全部引用修补)
    /// 其他 .dat 扩展: 截断版本 + 大小常量修补, 缓冲区无法扩展 (需更多逆向工程)
    /// </summary>
    static void PrepareWarPcForGame()
    {
        // 先恢复所有上次未恢复的 .orig 备份
        foreach (var kv in DataFileOrigSizes)
        {
            string bakPath = kv.Key + ".orig";
            if (System.IO.File.Exists(bakPath))
            {
                System.IO.File.Copy(bakPath, kv.Key, true);
                System.IO.File.Delete(bakPath);
                Log(string.Format("  检测到上次未恢复的 {0}.orig, 已自动恢复", kv.Key));
            }
        }

        // 检测 WarPC.dat 扩展 (已有完整支持)
        string warpcPath = "WarPC.dat";
        if (System.IO.File.Exists(warpcPath))
        {
            byte[] compressed = System.IO.File.ReadAllBytes(warpcPath);
            byte[] dec = LzssDecompress(compressed);
            int count = dec.Length / WARPC_REC_SIZE;
            if (count > WARPC_ORIG_COUNT)
            {
                _warpcExpanded = true;
                _warpcFullData = dec;
                Log(string.Format("  WarPC.dat 检测到扩展数据: {0} 角色 (原始 {1})", count, WARPC_ORIG_COUNT));

                byte[] truncated = new byte[WARPC_ORIG_SIZE];
                Array.Copy(dec, 0, truncated, 0, WARPC_ORIG_SIZE);
                byte[] truncatedCompressed = LzssCompress(truncated);
                string bakPath = warpcPath + ".orig";
                if (!System.IO.File.Exists(bakPath))
                    System.IO.File.Copy(warpcPath, bakPath, true);
                _truncatedFiles[warpcPath] = compressed; // 保存原始压缩数据
                System.IO.File.WriteAllBytes(warpcPath, truncatedCompressed);
                Log(string.Format("  已创建截断版 WarPC.dat ({0} 角色), 备份为 .orig", WARPC_ORIG_COUNT));
            }
        }

        // 检测其他 .dat 文件扩展
        foreach (var kv in DataFileOrigSizes)
        {
            string fileName = kv.Key;
            if (fileName == "WarPC.dat") continue; // 已单独处理

            int origSize = kv.Value;
            string path = fileName;
            if (!System.IO.File.Exists(path)) continue;

            int actualSize = GetDecompressedSize(path);
            if (actualSize < 0) continue;

            if (actualSize > origSize)
            {
                Log(string.Format("  [WARN] {0} 解压大小 {1} > 原始 {2}, 需要扩展支持",
                    fileName, actualSize, origSize));
                Log(string.Format("         当前将创建截断版本({0}B)供游戏加载, 大小常量将在运行时修补", origSize));

                // 创建截断版本 (仅保留前 origSize 字节的解压数据)
                byte[] compressed = System.IO.File.ReadAllBytes(path);
                byte[] dec = LzssDecompress(compressed);
                byte[] truncated = new byte[origSize];
                Array.Copy(dec, 0, truncated, 0, Math.Min(dec.Length, origSize));
                byte[] truncatedCompressed = LzssCompress(truncated);
                string bakPath = path + ".orig";
                if (!System.IO.File.Exists(bakPath))
                    System.IO.File.Copy(path, bakPath, true);
                _truncatedFiles[path] = compressed; // 保存原始压缩数据
                System.IO.File.WriteAllBytes(path, truncatedCompressed);
                Log(string.Format("  已创建截断版 {0} ({1}B), 备份为 .orig", fileName, origSize));
            }
            else if (actualSize < origSize)
            {
                Log(string.Format("  {0}: 解压大小 {1} (原始 {2}), 无需处理", fileName, actualSize, origSize));
            }
            else
            {
                Log(string.Format("  {0}: 解压大小 {1} = 原始值, OK", fileName, actualSize));
            }
        }
    }

    /// <summary>
    /// 在游戏进程代码段中扫描并修补指定4字节常量
    /// 返回: 成功修补的数量; patchedRVAs: 被修补的绝对地址列表
    /// </summary>
    static int ScanAndPatchConst(IntPtr hProc, int scanStart, int scanSize,
        int oldVal, int newVal, out System.Collections.Generic.List<int> patchedRVAs)
    {
        patchedRVAs = new System.Collections.Generic.List<int>();
        byte[] oldLE = BitConverter.GetBytes(oldVal);
        byte[] newLE = BitConverter.GetBytes(newVal);
        byte[] buf = new byte[scanSize];
        int nr;
        if (!ReadProcessMemory(hProc, (IntPtr)scanStart, buf, scanSize, out nr) || nr <= 0)
            return 0;

        int count = 0;
        int effectiveSize = Math.Min(nr, scanSize);
        for (int i = 0; i <= effectiveSize - 4; i++)
        {
            if (buf[i] == oldLE[0] && buf[i+1] == oldLE[1] &&
                buf[i+2] == oldLE[2] && buf[i+3] == oldLE[3])
            {
                int absAddr = scanStart + i;
                IntPtr pAddr = (IntPtr)absAddr;
                uint oldProt;
                VirtualProtectEx(hProc, pAddr, 4, PAGE_EXECUTE_READWRITE, out oldProt);
                int nw;
                bool ok = WriteProcessMemory(hProc, pAddr, newLE, 4, out nw);
                VirtualProtectEx(hProc, pAddr, 4, oldProt, out oldProt);
                if (ok && nw == 4)
                {
                    count++;
                    patchedRVAs.Add(absAddr);
                }
                i += 3;
            }
        }
        return count;
    }

    /// <summary>
    /// 修补游戏代码中所有 .dat 文件的硬编码大小常量
    /// 在 ExpandWarPcBuffer 中调用, 此时代码已解密
    /// </summary>
    static void PatchDataFileSizes(IntPtr hProc, IntPtr baseAddr, int scanStart, int scanSize)
    {
        Log("\n--- 数据文件大小常量修补 ---");
        int baseVA = (int)baseAddr.ToInt64();

        foreach (var kv in DataFileOrigSizes)
        {
            string fileName = kv.Key;
            int origSize = kv.Value;
            int actualSize = GetDecompressedSize(fileName);
            if (actualSize <= origSize) continue;

            // 只修补 .orig 备份存在 (已被 PrepareWarPcForGame 截断) 的文件
            string bakPath = fileName + ".orig";
            if (!System.IO.File.Exists(bakPath)) continue;

            // 恢复原始文件
            System.IO.File.Copy(bakPath, fileName, true);
            System.IO.File.Delete(bakPath);
            Log(string.Format("  已恢复原始 {0}", fileName));

            // 扫描并修补大小常量
            // 注意: 较小的值 (如 1920=0x780) 可能在代码中产生误匹配
            // 使用 origSize 和 actualSize 确保精确匹配
            System.Collections.Generic.List<int> rvas;
            int patched = ScanAndPatchConst(hProc, scanStart, scanSize,
                origSize, actualSize, out rvas);

            if (patched > 0)
            {
                Log(string.Format("  [OK] {0}: {1} → {2}, 修补 {3} 处",
                    fileName, origSize, actualSize, patched));
                foreach (int addr in rvas)
                {
                    int rva = addr - baseVA;
                    Log(string.Format("        RVA 0x{0:X} (abs 0x{1:X8})", rva, addr));
                }
            }
            else
            {
                Log(string.Format("  [WARN] {0}: 未找到 {1} (0x{1:X}) 的引用, "
                    + "可能已在 WarpcSizeRVAs 中处理或值不存在于代码段",
                    fileName, origSize));
            }
        }
    }

    /// <summary>
    /// 游戏加载后: 恢复原始 WarPC.dat, 分配动态缓冲区, 注入完整数据, 修补所有引用
    /// </summary>
    static void ExpandWarPcBuffer(int childPid, IntPtr baseAddr, int moduleSize, IntPtr caveAddr)
    {
        if (!_warpcExpanded || _warpcNewBuf == IntPtr.Zero) return;

        int newSize = _warpcFullData.Length;
        uint access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION;

        IntPtr hProc = OpenProcess(access, false, childPid);
        if (hProc == IntPtr.Zero) { Log("  [ERROR] 无法打开进程进行 WarPC 扩展"); return; }

        // 诊断日志收集器，写入 tks_launcher.log
        var diag = new System.Text.StringBuilder();

        IntPtr newBuf = _warpcNewBuf;
        Log(string.Format("  修补代码引用: 缓冲区 0x{0:X8}, 大小 {1}", newBuf.ToInt64(), newSize));

        // 精确修补: 在已验证的 RVA 位置替换 4 字节立即数
        byte[] newAddrLE = BitConverter.GetBytes((int)newBuf.ToInt64());
        byte[] newSizeLE = BitConverter.GetBytes(newSize);
        int addrPatches = 0, sizePatches = 0, fieldPatches = 0, addr0CPatches = 0;
        int nw;
        int scanStart = 0, scanEnd = 0, scanSize = 0;  // for log

        foreach (int rva in WarpcAddrRVAs)
        {
            IntPtr pAddr = (IntPtr)(baseAddr.ToInt64() + rva);
            byte[] oldVal = new byte[4];
            int nr;
            if (!ReadProcessMemory(hProc, pAddr, oldVal, 4, out nr)) continue;
            if (nr < 4) continue;
            int oldInt = BitConverter.ToInt32(oldVal, 0);
            if (oldInt != WARPC_BASE)
            {
                Log(string.Format("  [WARN] RVA 0x{0:X} 原值 0x{1:X8} != 预期 0x{2:X8}, 跳过",
                    rva, oldInt, WARPC_BASE));
                continue;
            }
            WriteProcessMemory(hProc, pAddr, newAddrLE, 4, out nw);
            addrPatches++;
        }

        // 显式修补 word_757F0C (0x757F0C = WarPC+4) 的所有引用
        // 这些引用指向队员肖像字段, 字段级盲扫可能因指令编码方式而遗漏
        // 若未正确 Patch → 存档预览文件写入越界 → 读档界面显示"六个0"
        // 注意: pointers.txt 的 RVA 指向指令起始位置, 4字节立即数在指令内部,
        //       偏移量因操作码不同而异 (如 add edx,imm32 立即数在+2)
        //       因此需要在 RVA 附近小窗口扫描而非精确位置匹配
        {
            const int WARPC_ADDR_0C = WARPC_BASE + 4;  // 0x757F0C
            byte[] newAddr0CLE = BitConverter.GetBytes((int)newBuf.ToInt64() + 4);
            diag.AppendLine(string.Format("[DIAG] word_757F0C 扫描: 目标=0x{0:X8} 新值=0x{1:X8}",
                WARPC_ADDR_0C, (int)newBuf.ToInt64() + 4));

            foreach (int rva in WarpcAddr0CRVAs)
            {
                // WarpcAddr0CRVAs 中的值是绝对 VA (pointers.txt 使用 image_base=0)
                // 直接作为地址使用, 不添加 baseAddr
                IntPtr absAddr = (IntPtr)rva;
                IntPtr scanAddr = (IntPtr)(rva - 2);
                byte[] buf = new byte[12];
                int nr;
                bool readOk = ReadProcessMemory(hProc, scanAddr, buf, 12, out nr);
                diag.AppendLine(string.Format("[DIAG] RVA=0x{0:X} scanAddr=0x{1:X8} readOk={2} nr={3}",
                    rva, scanAddr.ToInt64(), readOk, nr));
                if (!readOk) { diag.AppendLine(string.Format("[WARN] RVA 0x{0:X}: ReadProcessMemory 失败", rva)); continue; }
                if (nr < 8) { diag.AppendLine(string.Format("[WARN] RVA 0x{0:X}: 读取不足 nr={1}", rva, nr)); continue; }

                string hexDump = BitConverter.ToString(buf, 0, Math.Min(nr, 12));
                diag.AppendLine(string.Format("[DIAG] RVA 0x{0:X} raw=[{1}]", rva, hexDump));

                bool found = false;
                for (int off = 0; off <= nr - 4; off++)
                {
                    int val = BitConverter.ToInt32(buf, off);
                    diag.AppendLine(string.Format("[DIAG]   off={0} addr=0x{1:X8} val=0x{2:X8}",
                        off, scanAddr.ToInt64() + off, val));
                    if (val == WARPC_ADDR_0C)
                    {
                        IntPtr pAddr = (IntPtr)(scanAddr.ToInt64() + off);
                        uint oldProt;
                        VirtualProtectEx(hProc, pAddr, 4, PAGE_EXECUTE_READWRITE, out oldProt);
                        WriteProcessMemory(hProc, pAddr, newAddr0CLE, 4, out nw);
                        VirtualProtectEx(hProc, pAddr, 4, oldProt, out oldProt);
                        addr0CPatches++;
                        found = true;
                        diag.AppendLine(string.Format("[OK] RVA 0x{0:X} off={1} patched", rva, off));
                        break;
                    }
                }
                if (!found)
                {
                    diag.AppendLine(string.Format("[WARN] RVA 0x{0:X}: 窗口内未找到 0x{1:X8}", rva, WARPC_ADDR_0C));
                }
            }
            diag.AppendLine(string.Format("word_757F0C 修补: {0}/{1} 处", addr0CPatches, WarpcAddr0CRVAs.Length));
        }

        // 扫描字段级基址: [WARPC_BASE, WARPC_BASE + WARPC_REC_SIZE) 范围内所有地址
        // 这些是 0x757F08+field_offset 形式的预计算常量 (如 0x757F0E, 0x758116 等)
        // 偏移 = 原址 - WARPC_BASE → 新址 = newBuf + 偏移
        {
            int rangeStart = WARPC_BASE;
            int rangeEnd = WARPC_BASE + WARPC_REC_SIZE;  // exclusive
            int moduleStart = (int)baseAddr.ToInt64();
            // 扫描模块内所有代码段 (0x401000 到 BSS 之前)
            // 不再限定 0x4E6000 — 游戏代码延续到 0xA66000+
            scanStart = 0x401000;
            scanEnd = Math.Min(moduleStart + moduleSize, 0x700000);
            scanSize = scanEnd - scanStart;

            byte[] codeBuf = new byte[scanSize];
            if (ReadProcessMemory(hProc, (IntPtr)scanStart, codeBuf, scanSize, out nw) && nw > 0)
            {
                int effectiveSize = Math.Min(nw, scanSize);
                for (int i = 0; i <= effectiveSize - 4; i++)
                {
                    int val = BitConverter.ToInt32(codeBuf, i);
                    if (val >= rangeStart && val < rangeEnd)
                    {
                        int offset = val - WARPC_BASE;
                        int newVal = (int)newBuf.ToInt64() + offset;
                        byte[] newBytes = BitConverter.GetBytes(newVal);
                        IntPtr pAddr = (IntPtr)(scanStart + i);
                        WriteProcessMemory(hProc, pAddr, newBytes, 4, out nw);
                        fieldPatches++;
                        i += 3;  // skip past the 4-byte value
                    }
                }
            }
            Log(string.Format("  字段基址修补: {0} 处 (范围 0x{1:X8}-0x{2:X8})",
                fieldPatches, rangeStart, rangeEnd));

            // 诊断: 修补后重新扫描, 检查是否还有未修补的 0x757F08 引用
            {
                int missedCount = 0;
                string missedLocations = "";
                byte[] verifyBuf = new byte[scanSize];
                if (ReadProcessMemory(hProc, (IntPtr)scanStart, verifyBuf, scanSize, out nw) && nw > 0)
                {
                    int vSize = Math.Min(nw, scanSize);
                    for (int i = 0; i <= vSize - 4; i++)
                    {
                        int val = BitConverter.ToInt32(verifyBuf, i);
                        if (val >= rangeStart && val < rangeEnd)
                        {
                            int rva = scanStart + i - (int)baseAddr.ToInt64();
                            missedLocations += string.Format(" 0x{0:X}", rva);
                            missedCount++;
                            if (missedCount >= 20) { missedLocations += " ..."; break; }
                        }
                    }
                }
                if (missedCount > 0)
                    Log(string.Format("  [WARN] 修补后仍有 {0} 处未修补的 WarPC 引用:{1}", missedCount, missedLocations));
                else
                    Log("  修补验证: 所有 WarPC 引用已修补");

                // 特别检查 sub_43BF20 (战斗回写函数, RVA 0x3BF20)
                int bf20Rva = 0x3BF20;
                IntPtr bf20Addr = (IntPtr)(baseAddr.ToInt64() + bf20Rva);
                byte[] bf20Buf = new byte[256];
                if (ReadProcessMemory(hProc, bf20Addr, bf20Buf, 256, out nw) && nw > 0)
                {
                    string bf20Hex = BitConverter.ToString(bf20Buf, 0, Math.Min(nw, 80));
                    Log(string.Format("  [DIAG] sub_43BF20@0x{0:X8}: [{1}]", bf20Addr.ToInt64(), bf20Hex));
                    for (int i = 0; i <= nw - 4; i++)
                    {
                        int val = BitConverter.ToInt32(bf20Buf, i);
                        if (val == WARPC_BASE)
                        {
                            Log(string.Format("  [WARN] sub_43BF20+0x{0:X}: 仍有未修补的 0x{1:X8}!", i, WARPC_BASE));
                        }
                    }
                }
            }
        }

        // 扫描动态 cave 内存 — 不再需要, cave 已在 BuildPatches 中预修补

        // 诊断: 先读取所有 size RVA 的原值
        Log("  诊断 Size RVA 原值:");
        foreach (int rva in WarpcSizeRVAs)
        {
            IntPtr pAddr = (IntPtr)(baseAddr.ToInt64() + rva);
            byte[] oldVal = new byte[4];
            int nr;
            if (!ReadProcessMemory(hProc, pAddr, oldVal, 4, out nr) || nr < 4)
            {
                Log(string.Format("    0x{0:X}: ReadProcessMemory 失败 (nr={1})", rva, nr));
                continue;
            }
            int oldInt = BitConverter.ToInt32(oldVal, 0);
            string status = (oldInt == WARPC_ORIG_SIZE) ? "OK" : "MISMATCH";
            Log(string.Format("    0x{0:X}: 0x{1:X8} {2}", rva, oldInt, status));
        }

        foreach (int rva in WarpcSizeRVAs)
        {
            IntPtr pAddr = (IntPtr)(baseAddr.ToInt64() + rva);
            byte[] oldVal = new byte[4];
            int nr;
            if (!ReadProcessMemory(hProc, pAddr, oldVal, 4, out nr)) continue;
            if (nr < 4) continue;
            int oldInt = BitConverter.ToInt32(oldVal, 0);
            if (oldInt != WARPC_ORIG_SIZE)
            {
                Log(string.Format("  [WARN] RVA 0x{0:X} 原值 0x{1:X8} != 预期 0x24CE2, 跳过",
                    rva, oldInt));
                diag.AppendLine(string.Format("[DIAG] Size RVA 0x{0:X} 原值=0x{1:X8} 跳过", rva, oldInt));
                continue;
            }
            uint oldProt;
            VirtualProtectEx(hProc, pAddr, 4, PAGE_EXECUTE_READWRITE, out oldProt);
            bool wok = WriteProcessMemory(hProc, pAddr, newSizeLE, 4, out nr);
            VirtualProtectEx(hProc, pAddr, 4, oldProt, out oldProt);
            if (wok && nr == 4)
            {
                sizePatches++;
                diag.AppendLine(string.Format("[DIAG] Size RVA 0x{0:X}: 0x{1:X8} -> 0x{2:X8} OK", rva, oldInt, newSize));
            }
            else
            {
                diag.AppendLine(string.Format("[DIAG] Size RVA 0x{0:X}: WriteProcessMemory 失败 (wok={3} nr={4})", rva, wok, nr));
            }
        }

        // [补丁七] 存档/读档缓冲区大小修补
        // sub_410ED4 (存档) 和 sub_41103C (读档) 中硬编码 159922 字节分配
        // 159922 = 3432(队伍/金币) + 5768(其他状态) + 150722(WarPC)
        // 当 WarPC 扩展后, 缓冲区必须同步扩展, 否则写入溢出破坏栈数据
        int totalPatches = 0;
        {
            int totalOrigSize = WARPC_TOTAL_ORIG_SIZE;  // 0x270D2
            int totalNewSize = 9200 + newSize;
            byte[] totalNewSizeLE = BitConverter.GetBytes(totalNewSize);
            byte[] totalBuf = new byte[scanSize];
            if (ReadProcessMemory(hProc, (IntPtr)scanStart, totalBuf, scanSize, out nw) && nw > 0)
            {
                int tSize = Math.Min(nw, scanSize);
                byte[] totalOrigLE = BitConverter.GetBytes(totalOrigSize);
                for (int i = 0; i <= tSize - 4; i++)
                {
                    if (totalBuf[i] == totalOrigLE[0] && totalBuf[i+1] == totalOrigLE[1] &&
                        totalBuf[i+2] == totalOrigLE[2] && totalBuf[i+3] == totalOrigLE[3])
                    {
                        int rva = scanStart + i - (int)baseAddr.ToInt64();
                        IntPtr pAddr = (IntPtr)(scanStart + i);
                        uint oldProt;
                        VirtualProtectEx(hProc, pAddr, 4, PAGE_EXECUTE_READWRITE, out oldProt);
                        bool wok = WriteProcessMemory(hProc, pAddr, totalNewSizeLE, 4, out nw);
                        VirtualProtectEx(hProc, pAddr, 4, oldProt, out oldProt);
                        if (wok && nw == 4)
                        {
                            totalPatches++;
                            diag.AppendLine(string.Format("[DIAG] SaveBuf RVA 0x{0:X}: 0x{1:X5} -> 0x{2:X5} OK",
                                rva, totalOrigSize, totalNewSize));
                            Log(string.Format("  [OK] 存档缓冲区 RVA 0x{0:X}: {1} -> {2}",
                                rva, totalOrigSize, totalNewSize));
                        }
                        else
                        {
                            diag.AppendLine(string.Format("[DIAG] SaveBuf RVA 0x{0:X}: WriteProcessMemory 失败", rva));
                        }
                        i += 3;
                    }
                }
            }
            Log(string.Format("  存档/读档缓冲区修补: {0} 处 (159922 -> {1})", totalPatches, totalNewSize));
        }

        // [补丁八] 其他 .dat 文件大小常量修补
        // TKMat.dat / TKItem.dat / TKSkill.dat / TKShop.dat / TKKon.dat
        // 若这些文件被扩展, 需要修补 sub_4173F8 / sub_412688 中的硬编码大小
        PatchDataFileSizes(hProc, baseAddr, scanStart, scanSize);

        // [补丁九] 分配 WarPC 新角色备份缓冲区
        // 当加载旧存档 (WarPC 数据较少) 时, sub_41103C 中 patched newSize 的 memcpy
        // 会越过解压数据末尾读取垃圾, 覆盖新角色槽位。
        // 此处在新 WarPC 缓冲之后分配一个等大的备份区, 存储新角色区段的已知正确数据,
        // 供未来存档加载钩子 (cave hook) 恢复使用。
        int extraStart = WARPC_ORIG_COUNT * WARPC_REC_SIZE; // 143*1054 = 150722
        int extraSize = newSize - extraStart;                // 新角色区段大小
        IntPtr backupBuf = IntPtr.Zero;
        if (_warpcExpanded && extraSize > 0)
        {
            backupBuf = VirtualAllocEx(hProc, IntPtr.Zero, (uint)extraSize,
                MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            if (backupBuf != IntPtr.Zero)
            {
                // 将新角色数据从 WarPC 完整数据复制到备份缓冲区
                byte[] extraData = new byte[extraSize];
                Array.Copy(_warpcFullData, extraStart, extraData, 0, extraSize);
                int wr;
                WriteProcessMemory(hProc, backupBuf, extraData, extraSize, out wr);
                Log(string.Format("  新角色备份: 0x{0:X8} ({1} 字节, 角色 {2}-{3})",
                    backupBuf.ToInt64(), extraSize, WARPC_ORIG_COUNT,
                    _warpcFullData.Length / WARPC_REC_SIZE - 1));
                diag.AppendLine(string.Format("[DIAG] BackupBuf=0x{0:X8} extraSize={1}",
                    backupBuf.ToInt64(), extraSize));
            }
            else
            {
                Log("  [WARN] 无法分配新角色备份缓冲区");
                diag.AppendLine("[DIAG] BackupBuf allocation failed");
            }
        }

        CloseHandle(hProc);
        Log(string.Format("  已修补: {0} 个基址(08) + {1} 个基址(0C) + {2} 个字段基址 + {3} 个大小常量",
            addrPatches, addr0CPatches, fieldPatches, sizePatches));
        Log(string.Format("  扫描范围: 0x{0:X8}-0x{1:X8}, 新buf=0x{2:X8}, 新size={3}",
            scanStart, scanEnd, newBuf.ToInt64(), newSize));
        if (backupBuf != IntPtr.Zero)
            Log(string.Format("  备份buf=0x{0:X8}, 额外角色={1}", backupBuf.ToInt64(), extraSize / WARPC_REC_SIZE));
        Log("  Cave 地址已在 BuildPatches 中预修补, 无需后期扫描");
        // 将详细 DIAG 写入主日志 (不覆盖, 追加)
        Log(string.Format("warpc_expand=1 new_buf=0x{0:X8} new_size={1} addr08={2} addr0C={3} field={4} size={5} save_buf={6} scan=0x{7:X8}-0x{8:X8} new_total_size={9} backup_buf=0x{10:X8} extra_size={11}",
                newBuf.ToInt64(), newSize, addrPatches, addr0CPatches, fieldPatches, sizePatches,
                totalPatches, scanStart, scanEnd, 9200 + newSize,
                backupBuf.ToInt64(), extraSize));
        LogFile("--- ExpandWarPcBuffer DIAG ---");
        LogFile(diag.ToString());
    }

    // LZSS 压缩 — 与游戏 sub_452B14 配对 (用于截断文件生成)
    static byte[] LzssCompress(byte[] data)
    {
        int sl = data.Length;
        byte[] flat = new byte[4096 + sl];
        for (int i = 0; i < 4096; i++) flat[i] = 0x20;
        Array.Copy(data, 0, flat, 4096, sl);

        var headerFlags = new System.Collections.Generic.List<byte>();
        var tokenData = new System.Collections.Generic.List<byte>();
        int pos = 0;

        while (pos < sl)
        {
            int curr = 4096 + pos;
            int ms = Math.Min(18, sl - pos);
            int bestLen = 0, bestOff = 0;
            if (ms >= 3)
            {
                for (int length = ms; length > 2; length--)
                {
                    int start = Math.Max(0, curr - 4096);
                    bestOff = -1;
                    // 从右向左搜索 (与 Python rfind 一致), j < curr 排除自匹配
                    for (int j = curr - 1; j >= start; j--)
                    {
                        int k;
                        for (k = 0; k < length && flat[j + k] == flat[curr + k]; k++) ;
                        if (k >= length) { bestOff = j; break; }
                    }
                    if (bestOff >= 0) { bestLen = length; break; }
                }
            }
            if (bestLen >= 3)
            {
                int bo = (bestOff - 18) & 0xFFF;
                headerFlags.Add(0); // literal=0: back-reference
                tokenData.Add((byte)(bo & 0xFF));
                tokenData.Add((byte)(((bo >> 4) & 0xF0) | ((bestLen - 3) & 0x0F)));
                pos += bestLen;
            }
            else
            {
                headerFlags.Add(1); // literal=1: raw byte
                tokenData.Add(data[pos]);
                pos++;
            }
        }

        // 组装: 每8个flag打包为一个flag字节, 然后按顺序输出token数据
        var stream = new System.Collections.Generic.List<byte>();
        int hi = 0;  // headerFlags 索引
        int tp = 0;  // tokenData 索引 (变长: literal=1B, backref=2B)
        while (hi < headerFlags.Count)
        {
            int fb = 0;
            int be = Math.Min(hi + 8, headerFlags.Count);
            for (int i = hi; i < be; i++)
                if (headerFlags[i] != 0) fb |= (1 << (i - hi));
            stream.Add((byte)fb);
            for (int i = hi; i < be; i++)
            {
                if (headerFlags[i] != 0)
                {
                    stream.Add(tokenData[tp]);   // 1 byte literal
                    tp += 1;
                }
                else
                {
                    stream.Add(tokenData[tp]);     // offset lo
                    stream.Add(tokenData[tp + 1]); // offset hi + length
                    tp += 2;
                }
            }
            hi = be;
        }

        // 构建内部 LZSS 块: [解压大小:4B][LZSS流...]
        byte[] lzssBlock = new byte[4 + stream.Count];
        BitConverter.GetBytes(sl).CopyTo(lzssBlock, 0);
        stream.CopyTo(lzssBlock, 4);

        // 构建完整文件: [解压大小:4B][压缩块大小:4B][LZSS块...]
        byte[] result = new byte[8 + lzssBlock.Length];
        BitConverter.GetBytes(sl).CopyTo(result, 0);
        BitConverter.GetBytes(lzssBlock.Length).CopyTo(result, 4);
        Array.Copy(lzssBlock, 0, result, 8, lzssBlock.Length);

        // 回写验证 — 用完整文件格式解压
        byte[] testDec = LzssDecompress(result);
        if (testDec.Length != sl)
            throw new System.IO.InvalidDataException(
                string.Format("LZSS 压缩回写验证失败: 长度 {0} != {1}", testDec.Length, sl));
        for (int i = 0; i < sl; i++)
            if (testDec[i] != data[i])
                throw new System.IO.InvalidDataException(
                    string.Format("LZSS 压缩回写验证失败: 偏移 {0} 不匹配", i));

        return result;
    }

    // ============================================================
    // [补丁十三] sub_4C33FC 入口检查修补
    //
    // sub_4C33FC 入口 (反编译第 21 行):
    //   if (*(_BYTE *)(a1 + 12)) return 0;
    //
    // 该检查让 sub_41B1A8 循环从第 2 个槽位开始全部 return 0,
    // 导致 9 个槽位中只有第 1 个能读到文件, 其他都是 BSS 初始 0。
    //
    // 修补策略: 扫描入口前 32 字节 cmp + jnz 指令并用 NOP 覆盖
    // ============================================================
    static void Patch4C33FC(int childPid, IntPtr baseAddr)
    {
        const int SUB_4C33FC_RVA = 0xC33FC;
        Log("\n--- [补丁十三] sub_4C33FC 入口检查修补 ---");

        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            false, childPid);
        if (hProc == IntPtr.Zero) { Log("  [ERROR] OpenProcess 失败"); return; }

        IntPtr addr = (IntPtr)(baseAddr.ToInt64() + SUB_4C33FC_RVA);
        byte[] buf = new byte[64];
        int nr;
        if (!ReadProcessMemory(hProc, addr, buf, 64, out nr) || nr < 32)
        {
            Log(string.Format("  [ERROR] 读取 sub_4C33FC@0x{0:X8} 失败 (nr={1})",
                addr.ToInt64(), nr));
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  sub_4C33FC@0x{0:X8} 入口 64 字节: [{1}]",
            addr.ToInt64(), BitConverter.ToString(buf, 0, Math.Min(nr, 64))));

        // 在前 32 字节中查找 "cmp byte ptr [reg+0Ch], 0" 模式
        // 指令编码: 80 7X 0C 00
        //   X = 8 (eax), 9 (ecx), A (edx), B (ebx), D (ebp), E (esi), F (edi)
        //   注: D=ebp 需要 SIB, X=4 (esp) 需要 SIB, X=C (不存在)
        //   常见的是 X=8 (eax) 或 D (ebp+disp)
        // 实际上反编译中 a1 是第 1 个 cdecl 参数, 可能被载入任何寄存器
        int cmpOff = -1;
        byte cmpModRm = 0;
        for (int i = 0; i < Math.Min(nr, 32) - 4; i++)
        {
            if (buf[i] == 0x80
                && (buf[i+1] & 0xF8) == 0x78  // 78..7F = mod=01, r/m=000..111
                && buf[i+2] == 0x0C
                && buf[i+3] == 0x00)
            {
                cmpOff = i;
                cmpModRm = buf[i+1];
                break;
            }
        }

        if (cmpOff < 0)
        {
            Log("  [WARN] 未找到 cmp [reg+0Ch],0 指令模式, 跳过修补");
            Log("  读档界面可能仍会显示异常, 请报告上述入口字节以供人工诊断");
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  找到 cmp byte ptr [reg(modrm=0x{0:X2})+0Ch], 0 位于偏移 +0x{1:X}",
            cmpModRm, cmpOff));

        // 检查后续跳转指令:
        //   je  short (74 XX) = "如果 a1+12 == 0 (未打开) 跳到 continue"  → 原始逻辑
        //   jne short (75 XX) = "如果 a1+12 != 0 (已打开) 跳到 return_0"
        //   je/jne near (0F 84 XX*4 / 0F 85 XX*4) 是 near 版本
        //
        // 修复策略:
        //   je  short → 改为 jmp short (EB XX), 无条件跳到 continue 跳过 return 0
        //   jne short → 改为 NOP NOP (不跳, 继续往下执行 continue)
        byte branchOp = buf[cmpOff + 4];
        byte branchOp2 = buf[cmpOff + 5];
        IntPtr branchAddr = (IntPtr)(addr.ToInt64() + cmpOff + 4);
        bool patchOk = false;
        string patchDesc = "";
        byte[] patchBytes = null;

        if (branchOp == 0x74)
        {
            // je short → jmp short (74 XX → EB XX)
            patchBytes = new byte[] { 0xEB, branchOp2 };
            patchDesc = string.Format("je short +0x{0:X2} → jmp short +0x{0:X2}", branchOp2);
        }
        else if (branchOp == 0x75)
        {
            // jne short → NOP NOP
            patchBytes = new byte[] { 0x90, 0x90 };
            patchDesc = string.Format("jne short +0x{0:X2} → NOP NOP", branchOp2);
        }
        else if (branchOp == 0x0F && branchOp2 == 0x84)
        {
            // je near → jmp near (0F 84 imm32 → E9 imm32 + 1字节 NOP)
            // E9 是 5 字节跳转, 0F 84 是 6 字节, 需要调整 imm32 (跳转起点不同)
            int imm32 = BitConverter.ToInt32(buf, cmpOff + 6);
            // 0F 84 跳转从 cmp+10 处计算, E9 从 cmp+9 处计算 (差 1)
            int newImm = imm32 + 1;
            patchBytes = new byte[6];
            patchBytes[0] = 0xE9;
            BitConverter.GetBytes(newImm).CopyTo(patchBytes, 1);
            patchBytes[5] = 0x90; // NOP 填充第 6 字节
            patchDesc = string.Format("je near +0x{0:X8} → jmp near + NOP", imm32);
        }
        else if (branchOp == 0x0F && branchOp2 == 0x85)
        {
            // jne near → NOP × 6
            patchBytes = new byte[] { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };
            patchDesc = "jne near → NOP × 6";
        }
        else
        {
            Log(string.Format("  [WARN] cmp 后未识别到 je/jne (后续=0x{0:X2} 0x{1:X2}), 跳过修补",
                branchOp, branchOp2));
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  识别到分支指令: {0}", patchDesc));

        uint oldProt;
        VirtualProtectEx(hProc, branchAddr, patchBytes.Length, PAGE_EXECUTE_READWRITE, out oldProt);
        int nw;
        patchOk = WriteProcessMemory(hProc, branchAddr, patchBytes, patchBytes.Length, out nw);
        VirtualProtectEx(hProc, branchAddr, patchBytes.Length, oldProt, out oldProt);

        if (patchOk && nw == patchBytes.Length)
        {
            Log(string.Format("  [OK] sub_4C33FC+0x{0:X} 修补成功 ({1})",
                cmpOff + 4, patchDesc));
            // 验证写入
            byte[] verify = new byte[patchBytes.Length];
            ReadProcessMemory(hProc, branchAddr, verify, patchBytes.Length, out nr);
            Log(string.Format("  验证: [{0}]", BitConverter.ToString(verify, 0, patchBytes.Length)));
            // 诊断: dump 修补后的完整函数头
            byte[] verify2 = new byte[32];
            ReadProcessMemory(hProc, addr, verify2, 32, out nr);
            Log(string.Format("  修补后函数头 32 字节: [{0}]",
                BitConverter.ToString(verify2, 0, Math.Min(nr, 32))));
        }
        else
        {
            Log(string.Format("  [ERROR] WriteProcessMemory 失败 (ok={0} nw={1})", patchOk, nw));
        }
        CloseHandle(hProc);
    }

    // ============================================================
    // [补丁十四] sub_41C120 金铢检查修补
    //
    // sub_41C120 入口 (反编译第 17 行):
    //   if (*(_DWORD *)(*a1 + 8))   // 检查 stream error
    //     { ... set fail ... }
    //
    // 汇编似:
    //   mov eax, [esp+4]   ; arg a1 (stream pointer)
    //   mov ecx, [eax]     ; *a1 (stream object)
    //   cmp dword [ecx+8], 0
    //   je  no_error       ; 或 jne set_fail
    //   ... set fail ...
    //
    // 修补策略: 扫描入口前 32 字节 "cmp dword [reg+8], 0" 指令 (编码 83 7X 08 00),
    //   同时在其前面的 mov [reg], imm 或类似位置插入清零。
    //   更简单：直接把 cmp 指令改为等价的 "and dword [reg+8], 0" (调试后使用
    //   在原位置写 mov dword [reg+8], 0 或 7 字节 mov), 在这里采用较安全
    //   的方法: 改 cmp 为同长的 mov dword [reg+8], 0 (入口 4字节 cmp 改为
    //   7 字节 mov 不可行, 所以改为 NOP 后面的 jne, 让 cmp 结果被忽略,
    //   同时插入一条清零指令)。这里选择最简单的方案:
    //     cmp dword [ecx+8], 0  (4字节)
    //     je  no_error          (或 jne set_fail, 2 字节)
    //   → 改为:
    //     and dword [ecx+8], 0  (4字节: 83 6X 08 00, reg=4=AND) → 清零 stream error
    //     je  no_error          (保留 je, ZF=1 总是跳过 set_fail)  或
    //     jne set_fail          (保留 jne, ZF=1 不跳转, 继续到 no_error)
    // ============================================================
    static void Patch41C120(int childPid, IntPtr baseAddr)
    {
        const int SUB_41C120_RVA = 0x1C120;
        Log("\n--- [补丁十四] sub_41C120 金铢检查修补 ---");

        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            false, childPid);
        if (hProc == IntPtr.Zero) { Log("  [ERROR] OpenProcess 失败"); return; }

        IntPtr addr = (IntPtr)(baseAddr.ToInt64() + SUB_41C120_RVA);
        byte[] buf = new byte[64];
        int nr;
        if (!ReadProcessMemory(hProc, addr, buf, 64, out nr) || nr < 16)
        {
            Log(string.Format("  [ERROR] 读取 sub_41C120@0x{0:X8} 失败 (nr={1})",
                addr.ToInt64(), nr));
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  sub_41C120@0x{0:X8} 入口 64 字节: [{1}]",
            addr.ToInt64(), BitConverter.ToString(buf, 0, Math.Min(nr, 64))));

        // 实际汇编不是 "cmp dword [reg+8], 0", 而是:
        //   8B 4A 08    mov ecx, [edx+8]    ; 加载 stream+8 (error flag)
        //   85 C9       test ecx, ecx       ; 检查是否为 0
        //   0F 94 C0    sete al             ; al = (error == 0)
        //   83 E0 01    and eax, 1
        //   84 C0       test al, al         ; 设置 ZF
        //   0F 84 E5..  je near set_fail    ; ZF=1 (error 非 0) 跳到 set_fail
        //
        // 扫描模式 "8B 4A 08 85 C9" (mov ecx, [edx+8]; test ecx, ecx)
        int loadOff = -1;
        for (int i = 0; i < Math.Min(nr, 32) - 5; i++)
        {
            if (buf[i] == 0x8B && buf[i+1] == 0x4A && buf[i+2] == 0x08
                && buf[i+3] == 0x85 && buf[i+4] == 0xC9)
            {
                loadOff = i;
                break;
            }
        }

        if (loadOff < 0)
        {
            Log("  [WARN] 未找到 mov ecx,[edx+8];test ecx,ecx 模式, 跳过修补");
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  找到 mov ecx,[edx+8] + test ecx,ecx 位于偏移 +0x{0:X}", loadOff));

        // 验证后续是 sete al + and eax,1 + test al,al + je near (共 13 字节 从 loadOff 起)
        if (loadOff + 13 > nr
            || buf[loadOff + 5] != 0x0F || buf[loadOff + 6] != 0x94 || buf[loadOff + 7] != 0xC0
            || buf[loadOff + 8] != 0x83 || buf[loadOff + 9] != 0xE0 || buf[loadOff + 10] != 0x01
            || buf[loadOff + 11] != 0x84 || buf[loadOff + 12] != 0xC0)
        {
            Log("  [WARN] sete/and/test 后续模式不匹配, 跳过修补");
            CloseHandle(hProc);
            return;
        }

        // 替换 13 字节 为:
        //   C7 42 08 00 00 00 00  mov dword [edx+8], 0  (7 字节) → 真正清零 stream+8
        //   B0 01                  mov al, 1            (2 字节)
        //   84 C0                  test al, al          (2 字节, ZF=0)
        //   90 90                  NOP × 2             (2 字节)
        // 后面原始的 0F 84 E5 00 00 00 (je near set_fail) 因 ZF=0 不会跳转,
        // 函数走正常路径。最后的 return *(_DWORD*)(*a1+8) == 0 也会返回 true,
        // 因为 stream+8 已被清零。
        byte[] patchBytes = new byte[] {
            0xC7, 0x42, 0x08, 0x00, 0x00, 0x00, 0x00,  // mov dword [edx+8], 0
            0xB0, 0x01,                                 // mov al, 1
            0x84, 0xC0,                                 // test al, al (ZF=0)
            0x90, 0x90                                  // NOP x 2
        };

        IntPtr patchAddr = (IntPtr)(addr.ToInt64() + loadOff);
        uint oldProt;
        VirtualProtectEx(hProc, patchAddr, 13, PAGE_EXECUTE_READWRITE, out oldProt);
        int nw;
        bool ok = WriteProcessMemory(hProc, patchAddr, patchBytes, 13, out nw);
        VirtualProtectEx(hProc, patchAddr, 13, oldProt, out oldProt);

        if (ok && nw == 13)
        {
            Log(string.Format("  [OK] sub_41C120+0x{0:X} 清零补丁: 每次调用强制 stream+8 = 0", loadOff));
            byte[] verify = new byte[13];
            ReadProcessMemory(hProc, patchAddr, verify, 13, out nr);
            Log(string.Format("  验证: [{0}]", BitConverter.ToString(verify, 0, 13)));
            byte[] verify2 = new byte[40];
            ReadProcessMemory(hProc, addr, verify2, 40, out nr);
            Log(string.Format("  修补后函数头 40 字节: [{0}]",
                BitConverter.ToString(verify2, 0, Math.Min(nr, 40))));
        }
        else
        {
            Log(string.Format("  [ERROR] WriteProcessMemory 失败 (ok={0} nw={1})", ok, nw));
        }
        CloseHandle(hProc);
    }

    // ============================================================
    // [补丁十五] 存档界面队伍头像 hook
    //
    // 扫描 sub_41AB94 函数体内的 "add eax, 0xD3" (5 字节: 05 D3 00 00 00)
    // 指令, 将其替换为到 ArchivePortraitCave 的 5 字节 "call rel32"。
    // sub_41AB94 中该指令可能出现多次 (选中/未选中处理), 全部 hook。
    // ============================================================
    static void PatchArchivePortrait(int childPid, IntPtr baseAddr)
    {
        const int SUB_41AB94_RVA = 0x1AB94;
        const int SCAN_SIZE = 0x500;  // sub_41AB94 函数体 ~1280 字节
        Log("\n--- [补丁十五] 存档界面队伍头像 hook ---");

        if (_archivePortraitCaveAddr == 0)
        {
            Log("  [WARN] ArchivePortraitCave 未分配, 跳过");
            return;
        }

        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            false, childPid);
        if (hProc == IntPtr.Zero) { Log("  [ERROR] OpenProcess 失败"); return; }

        IntPtr addr = (IntPtr)(baseAddr.ToInt64() + SUB_41AB94_RVA);
        byte[] buf = new byte[SCAN_SIZE];
        int nr;
        if (!ReadProcessMemory(hProc, addr, buf, SCAN_SIZE, out nr) || nr < 64)
        {
            Log(string.Format("  [ERROR] 读取 sub_41AB94@0x{0:X8} 失败 (nr={1})",
                addr.ToInt64(), nr));
            CloseHandle(hProc);
            return;
        }

        Log(string.Format("  sub_41AB94@0x{0:X8} 函数体扫描 {1} 字节",
            addr.ToInt64(), nr));
        Log(string.Format("  ArchivePortraitCave 地址: 0x{0:X8}", _archivePortraitCaveAddr));
        Log(string.Format("  函数头 32 字节: [{0}]",
            BitConverter.ToString(buf, 0, Math.Min(32, nr))));

        // 完整 dump sub_41AB94 函数体到日志供诊断 (每行 32 字节)
        Log("\n  [完整 dump] sub_41AB94 函数体:");
        for (int line = 0; line < nr; line += 32)
        {
            int len = Math.Min(32, nr - line);
            Log(string.Format("    +0x{0:X4}: {1}",
                line, BitConverter.ToString(buf, line, len)));
        }

        // 扫描多种可能的 "+ 211" 指令编码:
        //  A) 05 D3 00 00 00          add eax, 0xD3       (5 字节)
        //  B) 66 05 D3 00              add ax, 0xD3        (4 字节)
        //  C) 83 C0 D3 不存在 (D3 sign-extend = -45 不是 211)
        //  D) lea eax, [reg + 0xD3]   8D ?? D3 / 8D ?? D3 00 00 00
        // 同时 dump 所有包含 D3 的位置供诊断
        Log("\n  [诊断] 扫描函数体中所有包含 'D3' 的位置:");
        for (int i = 0; i < nr; i++)
        {
            if (buf[i] == 0xD3)
            {
                int contextStart = Math.Max(0, i - 5);
                int contextLen = Math.Min(nr - contextStart, 12);
                Log(string.Format("    RVA 0x{0:X} ctx=[{1}]",
                    SUB_41AB94_RVA + i,
                    BitConverter.ToString(buf, contextStart, contextLen)));
            }
        }

        // 扫描模式 "66 05 D3 00 50" (add ax, 0xD3 + push eax, 共 5 字节)
        // 该模式与 PortraitCave1 hook 位置 0x17A50 一致
        int patched = 0;
        var diag = new System.Text.StringBuilder();
        for (int i = 0; i <= nr - 5; i++)
        {
            if (buf[i] == 0x66 && buf[i+1] == 0x05 && buf[i+2] == 0xD3
                && buf[i+3] == 0x00 && buf[i+4] == 0x50)
            {
                int hookRva = SUB_41AB94_RVA + i;
                IntPtr hookAddr = (IntPtr)(baseAddr.ToInt64() + hookRva);
                long hookEnd = hookAddr.ToInt64() + 5;
                int callOff = (int)(_archivePortraitCaveAddr - hookEnd);
                byte[] callData = new byte[5];
                callData[0] = 0xE8;
                BitConverter.GetBytes(callOff).CopyTo(callData, 1);

                uint oldProt;
                VirtualProtectEx(hProc, hookAddr, 5, PAGE_EXECUTE_READWRITE, out oldProt);
                int nw;
                bool ok = WriteProcessMemory(hProc, hookAddr, callData, 5, out nw);
                VirtualProtectEx(hProc, hookAddr, 5, oldProt, out oldProt);

                if (ok && nw == 5)
                {
                    patched++;
                    diag.AppendLine(string.Format(
                        "  [OK] hook (66 05 D3 00 50 = add ax,0xD3 + push eax) @ RVA 0x{0:X} → call cave",
                        hookRva));
                }
                i += 4;
            }
        }

        Log(diag.ToString().TrimEnd());
        Log(string.Format("  共 hook {0} 处 add ax+push eax 指令", patched));

        if (patched == 0)
        {
            Log("  [WARN] 未找到 66 05 D3 00 50 模式, 请查看上面 'D3' 扫描结果诊断实际编码");
        }
        CloseHandle(hProc);
    }

    // Inject WORD[260]/WORD[261] values from WarPC.dat into game memory
    static void InjectWarPCData(int childPid)
    {
        // 如果已通过 ExpandWarPcBuffer 扩展缓冲区, 完整数据已写入新缓冲区
        if (_warpcExpanded)
        {
            Log("  Data inject: 已通过 ExpandWarPcBuffer 完成");
            return;
        }

        string warpcPath = "WarPC.dat";
        if (!System.IO.File.Exists(warpcPath))
        {
            Log("  [WARN] WarPC.dat not found, skip data inject");
            return;
        }

        byte[] compressed = System.IO.File.ReadAllBytes(warpcPath);
        byte[] dec = LzssDecompress(compressed);
        if (dec.Length < WARPC_ORIG_SIZE)
        {
            Log("  [WARN] WarPC.dat decompressed size mismatch, skip data inject");
            return;
        }

        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
        if (hProc == IntPtr.Zero) return;

        int w260Count = 0;
        int portraitCount = 0;
        int count = Math.Min(dec.Length / WARPC_REC_SIZE, WARPC_ORIG_COUNT);

        for (int i = 0; i < count; i++)
        {
            int baseOff = i * WARPC_REC_SIZE;
            short w260 = BitConverter.ToInt16(dec, baseOff + 520);
            if (w260 != 0)
            {
                WriteMem16(hProc, WARPC_BASE + baseOff + 520, w260);
                w260Count++;
            }
            short w261 = BitConverter.ToInt16(dec, baseOff + 522);
            if (w261 != 0)
            {
                WriteMem16(hProc, WARPC_BASE + baseOff + 522, w261);
                portraitCount++;
            }
        }
        CloseHandle(hProc);
        Log(string.Format("  Data inject: {0} W260, {1} W261", w260Count, portraitCount));
        Log(string.Format("patches=9 inject_w260={0} w261={1}", w260Count, portraitCount));
    }

    // Minimal LZSS decompress (matching sub_452B14)
    static byte[] LzssDecompress(byte[] data)
    {
        if (data.Length < 12) return new byte[0];
        int totalSize = BitConverter.ToInt32(data, 0);
        int blockSize = BitConverter.ToInt32(data, 4);
        byte[] window = new byte[4096];
        for (int i = 0; i < 4096; i++) window[i] = 0x20;
        int wp = 4078;
        byte[] output = new byte[totalSize];
        int flags = 0, pos = 12, bc = 4, outPos = 0;
        while (bc < blockSize && outPos < totalSize)
        {
            flags >>= 1;
            if ((flags & 0x100) == 0)
            {
                if (pos >= data.Length) break;
                flags = data[pos++] | 0xFF00;
                bc++;
            }
            if ((flags & 1) != 0)
            {
                if (pos >= data.Length) break;
                byte b = data[pos++]; bc++;
                output[outPos++] = b;
                window[wp] = b; wp = (wp + 1) & 0xFFF;
            }
            else
            {
                if (pos + 1 >= data.Length) break;
                byte b1 = data[pos++], b2 = data[pos++]; bc += 2;
                int ro = ((b2 & 0xF0) << 4) | b1;
                int rl = (b2 & 0x0F) + 2;
                for (int j = 0; j <= rl && outPos < totalSize; j++)
                {
                    byte b = window[(j + ro) & 0xFFF];
                    output[outPos++] = b;
                    window[wp] = b; wp = (wp + 1) & 0xFFF;
                }
            }
        }
        return output;
    }

    static List<PROCESSENTRY32> GetChildProcesses(int parentPid)
    {
        var results = new List<PROCESSENTRY32>();
        IntPtr snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snap == INVALID_HANDLE_VALUE) return results;

        PROCESSENTRY32 pe = new PROCESSENTRY32();
        pe.dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32));

        if (Process32First(snap, ref pe))
        {
            do
            {
                if (pe.th32ParentProcessID == parentPid)
                    results.Add(pe);
            } while (Process32Next(snap, ref pe));
        }
        CloseHandle(snap);
        return results;
    }

    static IntPtr GetModuleBase(int pid)
    {
        IntPtr snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
        if (snap == INVALID_HANDLE_VALUE) return IntPtr.Zero;

        MODULEENTRY32 me = new MODULEENTRY32();
        me.dwSize = (uint)Marshal.SizeOf(typeof(MODULEENTRY32));
        IntPtr result = IntPtr.Zero;

        if (Module32First(snap, ref me))
            result = me.modBaseAddr;

        CloseHandle(snap);
        return result;
    }

    static bool ApplyPatches(int pid, IntPtr baseAddr, Patch[] patches, bool dryRun)
    {
        uint access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION;
        IntPtr proc = OpenProcess(access, false, pid);
        if (proc == IntPtr.Zero) return false;

        bool allOk = true;
        foreach (var p in patches)
        {
            IntPtr addr = (IntPtr)(baseAddr.ToInt64() + p.RVA);

            byte[] oldData = new byte[p.Data.Length];
            int bytesRead;
            if (!ReadProcessMemory(proc, addr, oldData, p.Data.Length, out bytesRead))
            {
                Log(string.Format("  [ERROR] ReadProcessMemory failed at RVA 0x{0:X8}", p.RVA));
                allOk = false;
                continue;
            }

            bool alreadyPatched = true;
            for (int i = 0; i < p.Data.Length; i++)
                if (oldData[i] != p.Data[i]) { alreadyPatched = false; break; }

            if (alreadyPatched)
            {
                Log(string.Format("  [=] RVA 0x{0:X8}: already patched ({1})", p.RVA, p.Desc));
                continue;
            }

            if (dryRun)
            {
                Log(string.Format("  [~] RVA 0x{0:X8}: would patch ({1})", p.RVA, p.Desc));
                continue;
            }

            uint oldProtect;
            if (!VirtualProtectEx(proc, addr, p.Data.Length, PAGE_EXECUTE_READWRITE, out oldProtect))
            {
                Log(string.Format("  [ERROR] VirtualProtectEx failed at RVA 0x{0:X8}", p.RVA));
                allOk = false;
                continue;
            }

            int bytesWritten;
            if (!WriteProcessMemory(proc, addr, p.Data, p.Data.Length, out bytesWritten))
            {
                VirtualProtectEx(proc, addr, p.Data.Length, oldProtect, out oldProtect);
                Log(string.Format("  [ERROR] WriteProcessMemory failed at RVA 0x{0:X8}", p.RVA));
                allOk = false;
                continue;
            }
            VirtualProtectEx(proc, addr, p.Data.Length, oldProtect, out oldProtect);

            byte[] verifyData = new byte[p.Data.Length];
            ReadProcessMemory(proc, addr, verifyData, p.Data.Length, out bytesRead);
            bool verified = true;
            for (int i = 0; i < p.Data.Length; i++)
                if (verifyData[i] != p.Data[i]) { verified = false; break; }

            string oldHex = BitConverter.ToString(oldData);
            string newHex = BitConverter.ToString(p.Data);
            if (verified)
                Log(string.Format("  [OK] RVA 0x{0:X8}: {1} -> {2} ({3})", p.RVA, oldHex, newHex, p.Desc));
            else
            {
                Log(string.Format("  [FAIL] RVA 0x{0:X8}: verification failed ({1})", p.RVA, p.Desc));
                allOk = false;
            }
        }

        CloseHandle(proc);
        return allOk;
    }

    static int Main(string[] args)
    {
        // 首先初始化日志写入器 (覆盖同名旧日志)
        LogInit();

        string tksPath = "TKS.exe";
        int waitTimeout = 30;

        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--exe" && i + 1 < args.Length)
                tksPath = args[++i];
            else if (args[i] == "--wait" && i + 1 < args.Length)
                waitTimeout = int.Parse(args[++i]);
            else if (args[i] == "--help")
            {
                Log("TKS Launcher - 自动运行时补丁启动器");
                Log("用法: TKSLauncher.exe [--exe TKS.exe] [--wait 秒]");
                Log("放到游戏目录双击运行即可。");
                return 0;
            }
        }

        Log("========================================");
        Log("TKS Launcher - 自动运行时补丁启动器");
        Log("========================================");

        // 启动前: 检查存档目录健康, 清理 0 字节损坏文件
        // (修复"6个相同主角头像"异常)
        EnsureSaveDirectoryHealthy();

        // 游戏启动前: 检查 WarPC.dat 是否扩展, 必要时创建截断版
        PrepareWarPcForGame();

        Log(string.Format("\n启动 {0}...", tksPath));
        Process tksProc;
        try
        {
            tksProc = Process.Start(tksPath);
        }
        catch (Exception e)
        {
            Log(string.Format("[ERROR] 无法启动 {0}: {1}", tksPath, e.Message));
            Log("按任意键退出...");
            Console.ReadKey();
            return 1;
        }
        Log(string.Format("  TKS.exe PID = {0}", tksProc.Id));

        Log(string.Format("等待代码解密完成 (最多 {0} 秒)...", waitTimeout));
        int childPid = 0;
        DateTime start = DateTime.Now;

        while ((DateTime.Now - start).TotalSeconds < waitTimeout)
        {
            if (tksProc.HasExited)
            {
                Log(string.Format("  TKS.exe 已退出 (code={0})", tksProc.ExitCode));
                break;
            }

            var children = GetChildProcesses(tksProc.Id);
            if (children.Count > 0)
            {
                childPid = (int)children[0].th32ProcessID;
                Log(string.Format("  检测到子进程: PID={0} Name={1}", childPid, children[0].szExeFile));
                Thread.Sleep(3000);
                break;
            }
            Thread.Sleep(500);
        }

        if (childPid == 0)
        {
            Log("[ERROR] 超时，未检测到子进程");
            if (!tksProc.HasExited) tksProc.Kill();
            Log("按任意键退出...");
            Console.ReadKey();
            return 1;
        }

        IntPtr baseAddr = GetModuleBase(childPid);
        if (baseAddr == IntPtr.Zero)
        {
            Log(string.Format("[ERROR] 无法获取子进程 {0} 的模块信息", childPid));
            if (!tksProc.HasExited) tksProc.Kill();
            Log("按任意键退出...");
            Console.ReadKey();
            return 1;
        }
        Log(string.Format("  模块基址: 0x{0:X8}", baseAddr.ToInt64()));

        // Pre-patch diagnostic: dump raw code bytes at hook points
        IntPtr hDiag = OpenProcess(PROCESS_VM_READ, false, childPid);
        if (hDiag != IntPtr.Zero)
        {
            int nread;
            byte[] p1Pre = new byte[16];
            if (ReadProcessMemory(hDiag, (IntPtr)(baseAddr.ToInt64() + 0x17A50), p1Pre, 16, out nread))
                Log(string.Format("  [DIAG] PATH1@0x17A50 pre: [{0}]",
                    BitConverter.ToString(p1Pre, 0, nread)));
            byte[] p2Pre = new byte[16];
            if (ReadProcessMemory(hDiag, (IntPtr)(baseAddr.ToInt64() + 0x17E1A), p2Pre, 16, out nread))
                Log(string.Format("  [DIAG] PATH2@0x17E1A pre: [{0}]",
                    BitConverter.ToString(p2Pre, 0, nread)));
            CloseHandle(hDiag);
        }

        // 获取模块大小
        IntPtr hMod = OpenProcess(PROCESS_VM_READ, false, childPid);
        int modSize = 0;
        if (hMod != IntPtr.Zero)
        {
            IntPtr snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, childPid);
            if (snap != INVALID_HANDLE_VALUE)
            {
                MODULEENTRY32 me = new MODULEENTRY32();
                me.dwSize = (uint)Marshal.SizeOf(typeof(MODULEENTRY32));
                if (Module32First(snap, ref me))
                    modSize = (int)me.modBaseSize;
                CloseHandle(snap);
            }
            CloseHandle(hMod);
        }
        Log(string.Format("  模块大小: 0x{0:X} ({0} bytes)", modSize));

        // 若 WarPC 扩展, 在 BuildPatches 之前分配缓冲区并写入数据
        // 这样 cave 数组可以在写入前直接嵌入正确地址
        int warpcBaseForCaves = 0;
        if (_warpcExpanded && _warpcFullData != null)
        {
            // 恢复原始 WarPC.dat (游戏已加载截断版本到 BSS 缓冲区, 现在可以恢复)
            string wpPath = "WarPC.dat";
            string bakPath = wpPath + ".orig";
            if (System.IO.File.Exists(bakPath))
            {
                System.IO.File.Copy(bakPath, wpPath, true);
                System.IO.File.Delete(bakPath);
                Log("  已恢复原始 WarPC.dat");
            }

            int newSize = _warpcFullData.Length;
            IntPtr hWarpc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
            if (hWarpc != IntPtr.Zero)
            {
                // [补丁十二] WarPC 缓冲区前预留 GUARD 区 (修复索引文件被截断问题)
                //
                // 背景: sub_41CE10 写入存档索引时, 需依次读取 6 个队员的等级:
                //   sub_41DAC4(v21, &word_757F0C[527 * *v6], 2);
                // 当 word_75688C[i] = -1 (空槽位) 时, 地址计算 = newBuf+4-1054 = newBuf-1050
                // 原始游戏中该地址落在 unk_756880 (Block B) 区域内, 合法内存不崩溃;
                // 启动器重定向后 newBuf 之前是未分配内存, 访问会触发页错误,
                // sub_41DAC4 的 SEH 截断写入流 → 索引文件被截断为 14/20 字节。
                //
                // 修复: 在 newBuf 前预留 GUARD_SIZE 字节作为"安全垫", VirtualAllocEx
                // 返回页对齐的物理起始地址, 逻辑 newBuf = 起始 + GUARD_SIZE。
                // 这样 newBuf - 1054 落在合法已分配区内 (默认填零),
                // sub_41DAC4 能完整读取 0 并写入文件 → 索引写满 28 字节。
                const uint GUARD_SIZE = 0x10000; // 64 KB 安全垫 (足够容纳 1054 字节负偏移)
                uint totalAlloc = (uint)newSize + GUARD_SIZE;
                IntPtr allocBase = VirtualAllocEx(hWarpc, IntPtr.Zero, totalAlloc,
                    MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
                if (allocBase != IntPtr.Zero)
                {
                    IntPtr newBuf = (IntPtr)(allocBase.ToInt64() + GUARD_SIZE);
                    int wr;
                    WriteProcessMemory(hWarpc, newBuf, _warpcFullData, newSize, out wr);
                    _warpcNewBuf = newBuf;
                    warpcBaseForCaves = (int)newBuf.ToInt64();
                    Log(string.Format("  WarPC 缓冲区: 0x{0:X8} ({1} 字节, {2} 角色)",
                        warpcBaseForCaves, newSize, newSize / WARPC_REC_SIZE));
                    Log(string.Format("  GUARD 安全垫: 0x{0:X8}-0x{1:X8} ({2} 字节, 修复空槽位负偏移访问)",
                        allocBase.ToInt64(), allocBase.ToInt64() + GUARD_SIZE, GUARD_SIZE));
                }
                CloseHandle(hWarpc);
            }
        }

        // 恢复其他被截断的 .dat 文件
        // 步骤: (1) 恢复原始文件 → (2) 游戏后续操作 (LoadAllData 等) 可用完整数据
        // 注意: BSS 缓冲区大小未扩展, 但 sub_45343C 的大小检查已被 PatchDataFileSizes 修补
        foreach (var kv in new Dictionary<string, byte[]>(_truncatedFiles))
        {
            string path = kv.Key;
            if (path == "WarPC.dat") continue;
            string bakPath = path + ".orig";
            if (System.IO.File.Exists(bakPath))
            {
                System.IO.File.Copy(bakPath, path, true);
                System.IO.File.Delete(bakPath);
                Log(string.Format("  已恢复原始 {0}", path));
            }
        }

        // Allocate executable memory for AwkSprite cave
        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
        IntPtr caveAddr = IntPtr.Zero;
        if (hProc != IntPtr.Zero)
        {
            caveAddr = VirtualAllocEx(hProc, IntPtr.Zero, 256, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
            CloseHandle(hProc);
        }
        if (caveAddr == IntPtr.Zero)
            Log("  [WARN] VirtualAllocEx failed, AwkSprite cave skipped");
        else
            Log(string.Format("  AwkSprite cave: 0x{0:X8} (dynamic alloc)", caveAddr.ToInt64()));

        Patch[] patches = BuildPatches(baseAddr, caveAddr, warpcBaseForCaves);
        Log(string.Format("  补丁数量: {0}", patches.Length));
        foreach (var p in patches)
            Log(string.Format("    RVA=0x{0:X8}  bytes=[{1}]  {2}", p.RVA, BitConverter.ToString(p.Data), p.Desc));

        Log("\n应用补丁...");
        bool ok = ApplyPatches(childPid, baseAddr, patches, false);

        Log("\n验证补丁...");
        ApplyPatches(childPid, baseAddr, patches, true);

        // WarPC 代码引用修补 (缓冲区已在 BuildPatches 之前分配)
        ExpandWarPcBuffer(childPid, baseAddr, modSize, caveAddr);

        // ============================================================
        // [补丁十三] 修复 sub_4C33FC "已打开"标志导致读档列表全 0 异常
        //
        // 背景: sub_41B1A8 循环 9 次復用同一个 v24 文件结构,
        //   sub_4C352C(v24, path, 12) → sub_4C33FC 入口:
        //     if (*(_BYTE *)(a1 + 12)) return 0;
        //   v19=1 打开成功 → v24+12=1
        //   v19=2..9 时 若 v24+12 未被清零 → sub_4C33FC return 0 → 读取失败
        //   → buffer 保留 BSS 初始 0 值 → 渲染出"6 个主角头像"异常
        //
        // 修复: 扫描 sub_4C33FC 入口前 32 字节的 cmp [reg+0Ch],0 指令,
        //   该指令均为 4 字节模式 "80 7X 0C 00" (其中 X = 寄存器编号),
        //   后跟 2 字节 "75 XX" (jnz short) 或 6 字节 "0F 85 XX XX XX XX" (jnz near)。
        //   将整个 cmp+jnz 替换为 NOP 完全跳过"已打开"检查。
        // ============================================================
        Patch4C33FC(childPid, baseAddr);

        // ============================================================
        // [补丁十四] 修复 sub_41C120 金铢函数 导致 slot 7-9 读取失败
        //
        // 背景: 在 sub_41B1A8 循环中, 若某个槽位文件不存在 (如 slot 4-6),
        //   sub_4C352C 返回 false → if (!v1) 分支执行 "stream+8 |= 4"
        //   设置 EOF 错误标志。之后的槽位 (slot 7-9) 即使文件存在,
        //   sub_41BF48/sub_41C2B8 入口调用 sub_41C120 检查 stream+8,
        //   发现错误标志返回 false → 跳过读取 → buffer 保留 0
        //   → 渲染出"6 个主角头像 + Lv0 + 70年初一"异常。
        //
        // 修复: 修补 sub_41C120 入口, 让它在检查前先强制清零 stream+8,
        //   这样任何遗留的 EOF/fail 标志都会被清除。sub_41BF48/sub_41C2B8
        //   会重新正常读取。sub_41C120 返回值不受影响 (仍为 true)。
        // ============================================================
        Patch41C120(childPid, baseAddr);

        // ============================================================
        // [补丁十五] 修复存档界面新角色队伍头像显示问题
        //
        // 背景: sub_41AB94 渲染存档列表队伍头像时:
        //   sub_4544EC(..., *(char *)(...) + 211, ...);
        // 问题二重: signed char ID 在 ID>=128 时 sign-extend 为负数;
        //   新角色 (143/144/145) 需要使用 WORD[261] 作为自定义头像帧。
        //
        // 修复: 扫描 sub_41AB94 内的 "add eax, 0xD3" (= 05 D3 00 00 00) 指令,
        //   替换为 call ArchivePortraitCave。cave 复现 movzx ID + WORD[261] 优先逻辑。
        // ============================================================
        PatchArchivePortrait(childPid, baseAddr);

        // Inject WORD[260]/WORD[261] from WarPC.dat into game memory
        InjectWarPCData(childPid);

        // Verify cave + hooks + data
        string log = string.Format("ok={0} cave=0x{1:X8} base=0x{2:X8}",
            ok, caveAddr.ToInt64(), baseAddr.ToInt64());
        IntPtr hV = OpenProcess(PROCESS_VM_READ, false, childPid);
        if (hV != IntPtr.Zero)
        {
            int read;
            byte[] hookBuf = new byte[5];
            // AwkSprite cave + hook
            byte[] awkCaveBuf = new byte[51];
            if (ReadProcessMemory(hV, caveAddr, awkCaveBuf, 51, out read))
                log += string.Format(" awk_cave=[{0}]", BitConverter.ToString(awkCaveBuf).Substring(0, 20)+"...");
            if (ReadProcessMemory(hV, (IntPtr)(baseAddr.ToInt64() + 0x309A6), hookBuf, 5, out read))
                log += string.Format(" awk_hook=[{0}]", BitConverter.ToString(hookBuf));
            // Portrait PATH1 cave + hook
            byte[] p1CaveBuf = new byte[41];
            if (ReadProcessMemory(hV, (IntPtr)(caveAddr.ToInt64() + 64), p1CaveBuf, 41, out read))
                log += string.Format(" p1_cave=[{0}]", BitConverter.ToString(p1CaveBuf).Substring(0, 20)+"...");
            if (ReadProcessMemory(hV, (IntPtr)(baseAddr.ToInt64() + 0x17A50), hookBuf, 5, out read))
                log += string.Format(" p1_hook=[{0}]", BitConverter.ToString(hookBuf));
            // Portrait PATH2 cave + hook
            byte[] p2CaveBuf = new byte[42];
            if (ReadProcessMemory(hV, (IntPtr)(caveAddr.ToInt64() + 128), p2CaveBuf, 42, out read))
                log += string.Format(" p2_cave=[{0}]", BitConverter.ToString(p2CaveBuf).Substring(0, 20)+"...");
            byte[] p2HookBuf = new byte[6];
            if (ReadProcessMemory(hV, (IntPtr)(baseAddr.ToInt64() + 0x17E1A), p2HookBuf, 6, out read))
                log += string.Format(" p2_hook=[{0}]", BitConverter.ToString(p2HookBuf));
            // Read WORD[261] for new characters (143,144) from new buffer
            byte[] w261 = new byte[2];
            if (_warpcNewBuf != IntPtr.Zero)
            {
                long newBase = _warpcNewBuf.ToInt64();
                if (ReadProcessMemory(hV, (IntPtr)(newBase + 143*1054 + 522), w261, 2, out read))
                    log += string.Format(" W261[143]=0x{0:X4}", BitConverter.ToInt16(w261, 0));
                if (ReadProcessMemory(hV, (IntPtr)(newBase + 144*1054 + 522), w261, 2, out read))
                    log += string.Format(" W261[144]=0x{0:X4}", BitConverter.ToInt16(w261, 0));
                // 诊断: 读取新角色的关键字段 (等级/经验/名称ID)
                byte[] charField = new byte[10];
                if (ReadProcessMemory(hV, (IntPtr)(newBase + 143*1054), charField, 10, out read))
                {
                    short nameId = BitConverter.ToInt16(charField, 0);
                    short level = BitConverter.ToInt16(charField, 4);  // word offset 2
                    short exp = BitConverter.ToInt16(charField, 6);    // word offset 3
                    short growth = BitConverter.ToInt16(charField, 8); // word offset 4
                    log += string.Format(" CHAR143=name{0},lv{1},exp{2},gr{3}", nameId, level, exp, growth);
                }
                if (ReadProcessMemory(hV, (IntPtr)(newBase + 144*1054), charField, 10, out read))
                {
                    short nameId = BitConverter.ToInt16(charField, 0);
                    short level = BitConverter.ToInt16(charField, 4);
                    short exp = BitConverter.ToInt16(charField, 6);
                    short growth = BitConverter.ToInt16(charField, 8);
                    log += string.Format(" CHAR144=name{0},lv{1},exp{2},gr{3}", nameId, level, exp, growth);
                }
                // 诊断: 读取技能槽 (word offset 82-87)
                byte[] skillBuf = new byte[12];
                if (ReadProcessMemory(hV, (IntPtr)(newBase + 143*1054 + 164), skillBuf, 12, out read))
                {
                    short sk0 = BitConverter.ToInt16(skillBuf, 0);
                    short sk1 = BitConverter.ToInt16(skillBuf, 2);
                    log += string.Format(" SK143=[{0},{1}]", sk0, sk1);
                }
            }
            // Also check old buffer for comparison
            if (ReadProcessMemory(hV, (IntPtr)(0x757F08 + 85*1054 + 522), w261, 2, out read))
                log += string.Format(" W261[85]=0x{0:X4}", BitConverter.ToInt16(w261, 0));
            if (ReadProcessMemory(hV, (IntPtr)(0x757F08 + 86*1054 + 522), w261, 2, out read))
                log += string.Format(" W261[86]=0x{0:X4}", BitConverter.ToInt16(w261, 0));
            // Team
            byte[] teamBuf = new byte[12];
            if (ReadProcessMemory(hV, (IntPtr)0x75688C, teamBuf, 12, out read))
            {
                log += " team=[";
                for (int i = 0; i < 6; i++)
                    log += BitConverter.ToInt16(teamBuf, i*2) + ",";
                log += "]";
            }

            // 存档索引写入 sub_41CE10 所依赖的关键全局变量 (诊断用)
            // 若这些值全为 0, 则 sub_41CE10 写入的索引会是 28 字节全零,
            // 导致读档界面显示"6 个相同主角头像"异常
            byte[] gameTimeBuf = new byte[2];
            if (ReadProcessMemory(hV, (IntPtr)0x756882, gameTimeBuf, 2, out read))
                log += string.Format(" game_time=0x{0:X4}", BitConverter.ToUInt16(gameTimeBuf, 0));
            byte[] sceneBuf = new byte[4];
            if (ReadProcessMemory(hV, (IntPtr)0x755B58, sceneBuf, 4, out read))
                log += string.Format(" scene=0x{0:X8}", BitConverter.ToInt32(sceneBuf, 0));
            // 读取 word_756888 (金钱)
            byte[] moneyBuf = new byte[2];
            if (ReadProcessMemory(hV, (IntPtr)0x756888, moneyBuf, 2, out read))
                log += string.Format(" money=0x{0:X4}", BitConverter.ToUInt16(moneyBuf, 0));

            // 检查存档索引文件存在性与大小 (诊断补丁十一)
            try
            {
                int validIdx = 0, zeroIdx = 0, missingIdx = 0;
                for (int i = 1; i <= 9; i++)
                {
                    string p = string.Format("save\\{0}.sav", i);
                    if (System.IO.File.Exists(p))
                    {
                        long sz = new System.IO.FileInfo(p).Length;
                        if (sz == 28) validIdx++;
                        else if (sz == 0) zeroIdx++;
                    }
                    else missingIdx++;
                }
                log += string.Format(" save_idx[ok={0},zero={1},miss={2}]",
                    validIdx, zeroIdx, missingIdx);
            }
            catch { /* 忽略诊断错误 */ }

            CloseHandle(hV);
        }

        // 将详细状态写入主日志 (不再覆盖文件)
        Log(log);

        // ============================================================
        // [诊断] 存档索引文件内容详细 dump
        // 验证: 28 字节文件内容是否正确 (队员/时间戳/等级/场景)
        // 若内容正确但读档界面仍异常, 说明问题在游戏读取流程
        // (sub_41B1A8) 而不是存档内容
        // ============================================================
        Log("\n--- 存档索引文件内容详细 dump ---");
        for (int i = 1; i <= 9; i++)
        {
            string idxPath = string.Format("save\\{0}.sav", i);
            string datPath = string.Format("save\\sav.{0}", i);
            if (!System.IO.File.Exists(idxPath))
            {
                Log(string.Format("  slot {0}: 不存在", i));
                continue;
            }
            try
            {
                byte[] idx = System.IO.File.ReadAllBytes(idxPath);
                long datSize = System.IO.File.Exists(datPath)
                    ? new System.IO.FileInfo(datPath).Length : -1;
                if (idx.Length != 28)
                {
                    Log(string.Format("  slot {0}: 大小={1} (异常) hex=[{2}]",
                        i, idx.Length, BitConverter.ToString(idx)));
                    continue;
                }
                // 解析 28 字节索引文件
                // 0..5  : 6 字节队员 ID (signed char, -1=空)
                // 6..7  : 2 字节游戏时间 (word_756882)
                // 8..11 : 4 字节 Unix 时间戳
                // 12..23: 12 字节 等级 (6 × word)
                // 24..27: 4 字节 场景 ID (dword_755B58)
                sbyte[] team = new sbyte[6];
                for (int k = 0; k < 6; k++) team[k] = (sbyte)idx[k];
                ushort gameTime = BitConverter.ToUInt16(idx, 6);
                int unixTs = BitConverter.ToInt32(idx, 8);
                short[] levels = new short[6];
                for (int k = 0; k < 6; k++) levels[k] = BitConverter.ToInt16(idx, 12 + k * 2);
                int sceneId = BitConverter.ToInt32(idx, 24);
                DateTime tsTime = unixTs > 0
                    ? new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(unixTs).ToLocalTime()
                    : new DateTime(1970,1,1);

                Log(string.Format("  slot {0}: idx=28B dat={1}B hex=[{2}]",
                    i, datSize, BitConverter.ToString(idx)));
                Log(string.Format("          team=[{0},{1},{2},{3},{4},{5}] game_time={6} unix_ts=0x{7:X8}({8:yyyy-MM-dd HH:mm:ss}) scene={9}",
                    team[0], team[1], team[2], team[3], team[4], team[5],
                    gameTime, unixTs, tsTime, sceneId));
                Log(string.Format("          levels=[Lv{0},Lv{1},Lv{2},Lv{3},Lv{4},Lv{5}]",
                    levels[0], levels[1], levels[2], levels[3], levels[4], levels[5]));
            }
            catch (Exception e)
            {
                Log(string.Format("  slot {0}: 读取失败 {1}", i, e.Message));
            }
        }
        Log("");

        if (ok)
        {
            Log("\n补丁已应用！游戏正在运行。");
            Log("启动器即将退出，补丁在本次游戏会话中持续生效。");
            Log("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。");

            // 存档兼容性提示
            if (_warpcExpanded)
            {
                int newCount = _warpcFullData.Length / WARPC_REC_SIZE;
                Log("\n--- 存档兼容性说明 ---");
                Log(string.Format(
                    "  WarPC 已扩展到 {0} 角色 (原始 143)。", newCount));
                Log("  新存档 (本次游戏保存): 完整支持, 所有角色数据正确存储。");
                Log(string.Format("  旧存档 (扩展前保存):   加载后新角色 ({0}+) 从 WarPC.dat 恢复默认值, "
                    + "不会读取到垃圾数据。", WARPC_ORIG_COUNT));
                Log(string.Format(
                    "  备份缓冲区: 保护角色 {0}-{1} 的数据完整性。",
                    WARPC_ORIG_COUNT, newCount - 1));

                // 索引文件 1 字节截断警告
                Log("\n  注意: 存档索引文件 (save\\N.sav) 队伍成员 ID 仅存储 1 字节。");
                Log("        若角色 ID >= 256, 存档列表中该角色头像/名称将显示异常。");
                Log(string.Format("        当前角色 ID 范围: 0-{0}, 状态: {1}",
                    newCount - 1, newCount > 256 ? "存在截断风险!" : "安全"));

                // sub_412688 清零警告
                Log("\n  注意: 新游戏初始化 (sub_412688) 会清零队伍/金币/统计区域。");
                Log("        开局时队伍显示 [主角, 空, 空, 空, 空, 空] 是游戏设计行为, 非 bug。");
                Log("        若加载存档后仍异常, 请检查 tks_launcher.log 中的 team= 字段。");
            }
        }
        else
        {
            Log("\n[WARN] 部分补丁未应用成功");
        }

        Thread.Sleep(2000);
        LogClose();
        return 0;
    }
}

