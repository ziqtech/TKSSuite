/*
 * TKS Launcher - 自动运行时内存补丁启动器
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

    // Static patches (RVA = baseAddr + RVA)
    static readonly Patch[] StaticPatches = new Patch[]
    {
        new Patch {
            RVA = 0xDA15, Data = new byte[] { 0xC8, 0x87 },
            Desc = "TeamMember: cmp 0x1E->0xC8, jg->ja (sub_40DA00)"
        },
        new Patch {
            RVA = 0xE6C1, Data = new byte[] { 0xC8, 0x76 },
            Desc = "CheckTeam: cmp 0x1E->0xC8, jle->jbe (sub_40E65C)"
        },
        new Patch {
            RVA = 0x31165, Data = new byte[] { 0x00 },
            Desc = "AwkSprite PATH2: +12→+0"
        },
        // Portrait patches REMOVED — static add→add,0 approach was breaking battle.
        // Replaced by inline caves below (PortraitCave1 / PortraitCave2).
    };

    // Cave body: 51 bytes. Hook AFTER call sub_432668 (at cmp [ebp-6],0).
    // Reads WarPC WORD[260] (byte offset 520 = 0x208).
    // If WORD[260]!=0: v26 = WORD[260]-6, then +6 gives WORD[260].
    // Sets ZF properly for the original jnz at 0x4309AD.
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

    // PortraitCave1 (41B): hook at RVA 0x17A50 (add ax,0xD3; push eax).
    // Verified: ECX = char_idx * 527, AX = portrait from [ecx*2+0x757F0A].
    // Both paths share identical epilogue (add esp,8; pop edx; xchg; jmp).
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

    // PortraitCave2 (42B): hook at RVA 0x17E1A (add dx,0xD3; push edx).
    // Verified: EAX = char_idx * 527, DX = portrait from [eax*2+0x757F0A].
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

    // Build the full patch list from dynamic cave address
    // warpcBaseAddr: if non-zero, caves will use this instead of 0x757F08
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

        return list.ToArray();
    }

    // ============================================================
    // WarPC 缓冲区动态扩展 — 突破 143 角色硬编码限制
    // ============================================================

    const int WARPC_BASE = 0x757F08;
    const int WARPC_REC_SIZE = 1054;
    const int WARPC_ORIG_COUNT = 143;
    const int WARPC_ORIG_SIZE = 150722; // = 143 * 1054 = 0x24CE2

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
    static readonly int[] WarpcSizeRVAs = new int[] {
        0x3FBD, 0x10F60, 0x110D8, 0x126A5, 0x173FC
    };

    /// <summary>
    /// 游戏启动前: 若 WarPC.dat 角色数大于143, 创建截断版本让游戏正常加载
    /// </summary>
    static void PrepareWarPcForGame()
    {
        string warpcPath = "WarPC.dat";
        if (!System.IO.File.Exists(warpcPath)) return;

        string bakPath = warpcPath + ".orig";

        // 如果存在 .orig 备份, 说明上次启动可能崩溃, 先恢复
        if (System.IO.File.Exists(bakPath))
        {
            System.IO.File.Copy(bakPath, warpcPath, true);
            System.IO.File.Delete(bakPath);
            Console.WriteLine("  检测到上次未恢复的 .orig 备份, 已自动恢复 WarPC.dat");
        }

        byte[] compressed = System.IO.File.ReadAllBytes(warpcPath);
        byte[] dec = LzssDecompress(compressed);
        int count = dec.Length / WARPC_REC_SIZE;
        if (count <= WARPC_ORIG_COUNT) return;

        _warpcExpanded = true;
        _warpcFullData = dec;
        Console.WriteLine(string.Format("  WarPC.dat 检测到扩展数据: {0} 角色 (原始 {1})", count, WARPC_ORIG_COUNT));

        // 截取前143角色 → 压缩 → 写入临时文件
        byte[] truncated = new byte[WARPC_ORIG_SIZE];
        Array.Copy(dec, 0, truncated, 0, WARPC_ORIG_SIZE);
        byte[] truncatedCompressed = LzssCompress(truncated);
        if (!System.IO.File.Exists(bakPath))
            System.IO.File.Copy(warpcPath, bakPath, true);
        System.IO.File.WriteAllBytes(warpcPath, truncatedCompressed);
        Console.WriteLine(string.Format("  已创建截断版 WarPC.dat ({0} 角色), 备份为 .orig", WARPC_ORIG_COUNT));
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
        if (hProc == IntPtr.Zero) { Console.WriteLine("  [ERROR] 无法打开进程进行 WarPC 扩展"); return; }

        IntPtr newBuf = _warpcNewBuf;
        Console.WriteLine(string.Format("  修补代码引用: 缓冲区 0x{0:X8}, 大小 {1}", newBuf.ToInt64(), newSize));

        // 精确修补: 在已验证的 RVA 位置替换 4 字节立即数
        byte[] newAddrLE = BitConverter.GetBytes((int)newBuf.ToInt64());
        byte[] newSizeLE = BitConverter.GetBytes(newSize);
        int addrPatches = 0, sizePatches = 0, fieldPatches = 0;
        int nw;
        int scanStart = 0, scanEnd = 0;  // for log

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
                Console.WriteLine(string.Format("  [WARN] RVA 0x{0:X} 原值 0x{1:X8} != 预期 0x{2:X8}, 跳过",
                    rva, oldInt, WARPC_BASE));
                continue;
            }
            WriteProcessMemory(hProc, pAddr, newAddrLE, 4, out nw);
            addrPatches++;
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
            int scanSize = scanEnd - scanStart;

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
            Console.WriteLine(string.Format("  字段基址修补: {0} 处 (范围 0x{1:X8}-0x{2:X8})",
                fieldPatches, rangeStart, rangeEnd));
        }

        // 扫描动态 cave 内存 — 不再需要, cave 已在 BuildPatches 中预修补

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
                Console.WriteLine(string.Format("  [WARN] RVA 0x{0:X} 原值 0x{1:X8} != 预期 {2}, 跳过",
                    rva, oldInt, WARPC_ORIG_SIZE));
                continue;
            }
            WriteProcessMemory(hProc, pAddr, newSizeLE, 4, out nw);
            sizePatches++;
        }

        CloseHandle(hProc);
        Console.WriteLine(string.Format("  已修补: {0} 个基址 + {1} 个字段基址 + {2} 个大小常量",
            addrPatches, fieldPatches, sizePatches));
        Console.WriteLine(string.Format("  扫描范围: 0x{0:X8}-0x{1:X8}, 新buf=0x{2:X8}, 新size={3}",
            scanStart, scanEnd, newBuf.ToInt64(), newSize));
        Console.WriteLine("  Cave 地址已在 BuildPatches 中预修补, 无需后期扫描");
        System.IO.File.WriteAllText("tks_launcher.log",
            string.Format("warpc_expand=1 new_buf=0x{0:X8} new_size={1} addr={2} field={3} size={4} scan=0x{5:X8}-0x{6:X8}",
                newBuf.ToInt64(), newSize, addrPatches, fieldPatches, sizePatches, scanStart, scanEnd));
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

    // Inject WORD[260]/WORD[261] values from WarPC.dat into game memory
    static void InjectWarPCData(int childPid)
    {
        // 如果已通过 ExpandWarPcBuffer 扩展缓冲区, 完整数据已写入新缓冲区
        if (_warpcExpanded)
        {
            Console.WriteLine("  Data inject: 已通过 ExpandWarPcBuffer 完成");
            return;
        }

        string warpcPath = "WarPC.dat";
        if (!System.IO.File.Exists(warpcPath))
        {
            Console.WriteLine("  [WARN] WarPC.dat not found, skip data inject");
            return;
        }

        byte[] compressed = System.IO.File.ReadAllBytes(warpcPath);
        byte[] dec = LzssDecompress(compressed);
        if (dec.Length < WARPC_ORIG_SIZE)
        {
            Console.WriteLine("  [WARN] WarPC.dat decompressed size mismatch, skip data inject");
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
        Console.WriteLine(string.Format("  Data inject: {0} W260, {1} W261", w260Count, portraitCount));
        System.IO.File.WriteAllText("tks_launcher.log",
            string.Format("patches=9 inject_w260={0} w261={1}", w260Count, portraitCount));
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
                Console.WriteLine(string.Format("  [ERROR] ReadProcessMemory failed at RVA 0x{0:X8}", p.RVA));
                allOk = false;
                continue;
            }

            bool alreadyPatched = true;
            for (int i = 0; i < p.Data.Length; i++)
                if (oldData[i] != p.Data[i]) { alreadyPatched = false; break; }

            if (alreadyPatched)
            {
                Console.WriteLine(string.Format("  [=] RVA 0x{0:X8}: already patched ({1})", p.RVA, p.Desc));
                continue;
            }

            if (dryRun)
            {
                Console.WriteLine(string.Format("  [~] RVA 0x{0:X8}: would patch ({1})", p.RVA, p.Desc));
                continue;
            }

            uint oldProtect;
            if (!VirtualProtectEx(proc, addr, p.Data.Length, PAGE_EXECUTE_READWRITE, out oldProtect))
            {
                Console.WriteLine(string.Format("  [ERROR] VirtualProtectEx failed at RVA 0x{0:X8}", p.RVA));
                allOk = false;
                continue;
            }

            int bytesWritten;
            if (!WriteProcessMemory(proc, addr, p.Data, p.Data.Length, out bytesWritten))
            {
                VirtualProtectEx(proc, addr, p.Data.Length, oldProtect, out oldProtect);
                Console.WriteLine(string.Format("  [ERROR] WriteProcessMemory failed at RVA 0x{0:X8}", p.RVA));
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
                Console.WriteLine(string.Format("  [OK] RVA 0x{0:X8}: {1} -> {2} ({3})", p.RVA, oldHex, newHex, p.Desc));
            else
            {
                Console.WriteLine(string.Format("  [FAIL] RVA 0x{0:X8}: verification failed ({1})", p.RVA, p.Desc));
                allOk = false;
            }
        }

        CloseHandle(proc);
        return allOk;
    }

    static int Main(string[] args)
    {
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
                Console.WriteLine("TKS Launcher - 自动运行时补丁启动器");
                Console.WriteLine("用法: TKSLauncher.exe [--exe TKS.exe] [--wait 秒]");
                Console.WriteLine("放到游戏目录双击运行即可。");
                return 0;
            }
        }

        Console.WriteLine("========================================");
        Console.WriteLine("TKS Launcher - 自动运行时补丁启动器");
        Console.WriteLine("========================================");

        // 游戏启动前: 检查 WarPC.dat 是否扩展, 必要时创建截断版
        PrepareWarPcForGame();

        Console.WriteLine(string.Format("\n启动 {0}...", tksPath));
        Process tksProc;
        try
        {
            tksProc = Process.Start(tksPath);
        }
        catch (Exception e)
        {
            Console.WriteLine(string.Format("[ERROR] 无法启动 {0}: {1}", tksPath, e.Message));
            Console.WriteLine("按任意键退出...");
            Console.ReadKey();
            return 1;
        }
        Console.WriteLine(string.Format("  TKS.exe PID = {0}", tksProc.Id));

        Console.WriteLine(string.Format("等待代码解密完成 (最多 {0} 秒)...", waitTimeout));
        int childPid = 0;
        DateTime start = DateTime.Now;

        while ((DateTime.Now - start).TotalSeconds < waitTimeout)
        {
            if (tksProc.HasExited)
            {
                Console.WriteLine(string.Format("  TKS.exe 已退出 (code={0})", tksProc.ExitCode));
                break;
            }

            var children = GetChildProcesses(tksProc.Id);
            if (children.Count > 0)
            {
                childPid = (int)children[0].th32ProcessID;
                Console.WriteLine(string.Format("  检测到子进程: PID={0} Name={1}", childPid, children[0].szExeFile));
                Thread.Sleep(3000);
                break;
            }
            Thread.Sleep(500);
        }

        if (childPid == 0)
        {
            Console.WriteLine("[ERROR] 超时，未检测到子进程");
            if (!tksProc.HasExited) tksProc.Kill();
            Console.WriteLine("按任意键退出...");
            Console.ReadKey();
            return 1;
        }

        IntPtr baseAddr = GetModuleBase(childPid);
        if (baseAddr == IntPtr.Zero)
        {
            Console.WriteLine(string.Format("[ERROR] 无法获取子进程 {0} 的模块信息", childPid));
            if (!tksProc.HasExited) tksProc.Kill();
            Console.WriteLine("按任意键退出...");
            Console.ReadKey();
            return 1;
        }
        Console.WriteLine(string.Format("  模块基址: 0x{0:X8}", baseAddr.ToInt64()));

        // Pre-patch diagnostic: dump raw code bytes at hook points
        IntPtr hDiag = OpenProcess(PROCESS_VM_READ, false, childPid);
        if (hDiag != IntPtr.Zero)
        {
            int nread;
            byte[] p1Pre = new byte[16];
            if (ReadProcessMemory(hDiag, (IntPtr)(baseAddr.ToInt64() + 0x17A50), p1Pre, 16, out nread))
                Console.WriteLine(string.Format("  [DIAG] PATH1@0x17A50 pre: [{0}]",
                    BitConverter.ToString(p1Pre, 0, nread)));
            byte[] p2Pre = new byte[16];
            if (ReadProcessMemory(hDiag, (IntPtr)(baseAddr.ToInt64() + 0x17E1A), p2Pre, 16, out nread))
                Console.WriteLine(string.Format("  [DIAG] PATH2@0x17E1A pre: [{0}]",
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
        Console.WriteLine(string.Format("  模块大小: 0x{0:X} ({0} bytes)", modSize));

        // 若 WarPC 扩展, 在 BuildPatches 之前分配缓冲区并写入数据
        // 这样 cave 数组可以在写入前直接嵌入正确地址
        int warpcBaseForCaves = 0;
        if (_warpcExpanded && _warpcFullData != null)
        {
            // 恢复原始 WarPC.dat
            string wpPath = "WarPC.dat";
            string bakPath = wpPath + ".orig";
            if (System.IO.File.Exists(bakPath))
            {
                System.IO.File.Copy(bakPath, wpPath, true);
                System.IO.File.Delete(bakPath);
                Console.WriteLine("  已恢复原始 WarPC.dat");
            }

            int newSize = _warpcFullData.Length;
            IntPtr hWarpc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
            if (hWarpc != IntPtr.Zero)
            {
                IntPtr newBuf = VirtualAllocEx(hWarpc, IntPtr.Zero, (uint)newSize,
                    MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
                if (newBuf != IntPtr.Zero)
                {
                    int wr;
                    WriteProcessMemory(hWarpc, newBuf, _warpcFullData, newSize, out wr);
                    _warpcNewBuf = newBuf;
                    warpcBaseForCaves = (int)newBuf.ToInt64();
                    Console.WriteLine(string.Format("  WarPC 缓冲区: 0x{0:X8} ({1} 字节, {2} 角色)",
                        warpcBaseForCaves, newSize, newSize / WARPC_REC_SIZE));
                }
                CloseHandle(hWarpc);
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
            Console.WriteLine("  [WARN] VirtualAllocEx failed, AwkSprite cave skipped");
        else
            Console.WriteLine(string.Format("  AwkSprite cave: 0x{0:X8} (dynamic alloc)", caveAddr.ToInt64()));

        Patch[] patches = BuildPatches(baseAddr, caveAddr, warpcBaseForCaves);
        Console.WriteLine(string.Format("  补丁数量: {0}", patches.Length));
        foreach (var p in patches)
            Console.WriteLine(string.Format("    RVA=0x{0:X8}  bytes=[{1}]  {2}", p.RVA, BitConverter.ToString(p.Data), p.Desc));

        Console.WriteLine("\n应用补丁...");
        bool ok = ApplyPatches(childPid, baseAddr, patches, false);

        Console.WriteLine("\n验证补丁...");
        ApplyPatches(childPid, baseAddr, patches, true);

        // WarPC 代码引用修补 (缓冲区已在 BuildPatches 之前分配)
        ExpandWarPcBuffer(childPid, baseAddr, modSize, caveAddr);

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
            CloseHandle(hV);
        }
        // Read back inject details from InjectWarPCData's log
        string injectLog = "";
        if (System.IO.File.Exists("tks_launcher.log"))
            injectLog = " " + System.IO.File.ReadAllText("tks_launcher.log").Trim();
        System.IO.File.WriteAllText("tks_launcher.log", log + injectLog);

        if (ok)
        {
            Console.WriteLine("\n补丁已应用！游戏正在运行。");
            Console.WriteLine("启动器即将退出，补丁在本次游戏会话中持续生效。");
            Console.WriteLine("关闭游戏后补丁失效（每次运行本启动器即可重新应用）。");
        }
        else
        {
            Console.WriteLine("\n[WARN] 部分补丁未应用成功");
        }

        Thread.Sleep(2000);
        return 0;
    }
}

