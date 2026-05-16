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
    }

    static readonly Patch[] Patches = new Patch[]
    {
        new Patch {
            RVA = 0xDA15,
            Data = new byte[] { 0xC8, 0x87 },
            Desc = "TeamMember: cmp 0x1E->0xC8, jg->ja (sub_40DA00)"
        },
        new Patch {
            RVA = 0xE6C1,
            Data = new byte[] { 0xC8, 0x76 },
            Desc = "CheckTeam: cmp 0x1E->0xC8, jle->jbe (sub_40E65C)"
        },
    };

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
        Console.WriteLine(string.Format("  补丁数量: {0}", Patches.Length));
        foreach (var p in Patches)
            Console.WriteLine(string.Format("    RVA=0x{0:X8}  bytes=[{1}]  {2}", p.RVA, BitConverter.ToString(p.Data), p.Desc));

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

        Console.WriteLine("\n应用补丁...");
        bool ok = ApplyPatches(childPid, baseAddr, Patches, false);

        Console.WriteLine("\n验证补丁...");
        ApplyPatches(childPid, baseAddr, Patches, true);

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
