/*
 * TKS Launcher - 自动运行时内存补丁启动器
 *
 * 用法: 把编译后的 TKSLauncher.exe 放到游戏目录，双击运行即可
 * 编译: C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /target:winexe /out:TKSLauncher.exe tks_launcher.cs
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
        // PATH2: +12→+0 (敌方精灵块=WarPC记录号)
        new Patch {
            RVA = 0x31165, Data = new byte[] { 0x00 },
            Desc = "AwkSprite PATH2: +12→+0"
        },
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

    // Build the full patch list from dynamic cave address
    static Patch[] BuildPatches(IntPtr baseAddr, IntPtr caveAddr)
    {
        long cave = caveAddr.ToInt64();
        long baseVA = baseAddr.ToInt64();

        // Cave is self-contained (no internal call), just need the hook call
        byte[] caveData = (byte[])CaveTemplate.Clone();

        // Hook at cmp [ebp-6],0 (RVA 0x309A6), AFTER call sub_432668
        int hookRva = 0x309A6;
        int callOff = (int)(cave - baseVA) - (hookRva + 5);
        byte[] callData = new byte[5];
        callData[0] = 0xE8;
        BitConverter.GetBytes(callOff).CopyTo(callData, 1);

        var list = new List<Patch>(StaticPatches);
        list.Add(new Patch {
            RVA = (int)(cave - baseVA), Data = caveData,
            Desc = "AwkSprite PATH1 cave: hook after sub_432668→读WORD[260]→v26=WORD[260]-6 (51B)"
        });
        list.Add(new Patch {
            RVA = hookRva, Data = callData,
            Desc = string.Format("AwkSprite PATH1: hook→cave(0x{0:X8})", cave)
        });
        return list.ToArray();
    }

    // Inject WORD[260] values from WarPC.dat into game memory
    static void InjectWarPCData(int childPid)
    {
        string warpcPath = "WarPC.dat";
        if (!System.IO.File.Exists(warpcPath))
        {
            Console.WriteLine("  [WARN] WarPC.dat not found, skip data inject");
            return;
        }

        byte[] compressed = System.IO.File.ReadAllBytes(warpcPath);
        byte[] dec = LzssDecompress(compressed);
        if (dec.Length < 143 * 1054)
        {
            Console.WriteLine("  [WARN] WarPC.dat decompressed size mismatch, skip data inject");
            return;
        }

        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
        if (hProc == IntPtr.Zero) return;

        int count = 0;
        const int WARPC_BASE = 0x757F08;
        const int REC_SIZE = 1054;
        const int FIELD_OFFSET = 520; // WORD[260]

        for (int i = 0; i < 143; i++)
        {
            int off = i * REC_SIZE + FIELD_OFFSET;
            short val = BitConverter.ToInt16(dec, off);
            if (val != 0)
            {
                IntPtr addr = (IntPtr)(WARPC_BASE + off);
                byte[] data = BitConverter.GetBytes(val);
                int written;
                uint oldProt;
                VirtualProtectEx(hProc, addr, 2, PAGE_EXECUTE_READWRITE, out oldProt);
                WriteProcessMemory(hProc, addr, data, 2, out written);
                VirtualProtectEx(hProc, addr, 2, oldProt, out oldProt);
                count++;
            }
        }
        CloseHandle(hProc);
        Console.WriteLine(string.Format("  AwkSprite data inject: {0} chars with non-zero WORD[260]", count));
        System.IO.File.WriteAllText("tks_launcher.log",
            string.Format("patches=6 inject_chars={0}", count));
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

        // Allocate executable memory for AwkSprite cave
        IntPtr hProc = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, false, childPid);
        IntPtr caveAddr = IntPtr.Zero;
        if (hProc != IntPtr.Zero)
        {
            caveAddr = VirtualAllocEx(hProc, IntPtr.Zero, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
            CloseHandle(hProc);
        }
        if (caveAddr == IntPtr.Zero)
            Console.WriteLine("  [WARN] VirtualAllocEx failed, AwkSprite cave skipped");
        else
            Console.WriteLine(string.Format("  AwkSprite cave: 0x{0:X8} (dynamic alloc)", caveAddr.ToInt64()));

        Patch[] patches = BuildPatches(baseAddr, caveAddr);
        Console.WriteLine(string.Format("  补丁数量: {0}", patches.Length));
        foreach (var p in patches)
            Console.WriteLine(string.Format("    RVA=0x{0:X8}  bytes=[{1}]  {2}", p.RVA, BitConverter.ToString(p.Data), p.Desc));

        Console.WriteLine("\n应用补丁...");
        bool ok = ApplyPatches(childPid, baseAddr, patches, false);

        Console.WriteLine("\n验证补丁...");
        ApplyPatches(childPid, baseAddr, patches, true);

        // Inject WORD[260] from WarPC.dat into game memory
        InjectWarPCData(childPid);

        // Verify hook + data + cave
        string log = string.Format("ok={0} cave=0x{1:X8} base=0x{2:X8}",
            ok, caveAddr.ToInt64(), baseAddr.ToInt64());
        IntPtr hV = OpenProcess(PROCESS_VM_READ, false, childPid);
        if (hV != IntPtr.Zero)
        {
            int read;
            // Verify cave bytes
            byte[] caveBuf = new byte[51];
            if (ReadProcessMemory(hV, caveAddr, caveBuf, 51, out read))
                log += string.Format(" cave=[{0}]", BitConverter.ToString(caveBuf).Substring(0,20)+"...");
            else
                log += " cave_read=FAIL";
            // Verify hook bytes at 0x4309A6
            IntPtr hookAddr = (IntPtr)(baseAddr.ToInt64() + 0x309A6);
            byte[] hookBuf = new byte[5];
            if (ReadProcessMemory(hV, hookAddr, hookBuf, 5, out read))
                log += string.Format(" hook=[{0}]", BitConverter.ToString(hookBuf));
            else
                log += " hook_read=FAIL";
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
        System.IO.File.WriteAllText("tks_launcher.log", log);

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
