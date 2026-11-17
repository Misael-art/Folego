// Windows backend for Folego. No driver, EC/SMU, fan or TDP APIs. Process
// termination exists only behind the confirmed, revalidated core path.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Folego.Windows {
    public sealed class Sample {
        public DateTime AtUtc;
        public long MonotonicMs;
        public ulong TotalPhysical, AvailablePhysical, CommitUsed, CommitLimit;
        public double? CpuPercent;
        public int? BatteryPercent;
        public bool? ExternalPower, Charging;
        public long? BatterySeconds;
        public ulong? DiskAvailable, DiskTotal;
        public long SelfRss;
        public readonly List<string> Errors = new List<string>();
    }
    public sealed class ProcInfo {
        public int Pid, ParentPid, Threads;
        public int? SessionId;
        public string Name, Path, OwnerSid;
        public long StartTicks, CpuTicks;
        public ulong ReadBytes, WriteBytes;
        public bool HasWindow, Queried;
    }
    public sealed class Native {
        [StructLayout(LayoutKind.Sequential)] struct MemoryStatus {
            public uint Length, Load;
            public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile;
            public ulong TotalVirtual, AvailableVirtual, AvailableExtendedVirtual;
        }
        [StructLayout(LayoutKind.Sequential)] struct PerformanceInfo {
            public uint Size;
            public UIntPtr CommitTotal, CommitLimit, CommitPeak, PhysicalTotal, PhysicalAvailable;
            public UIntPtr SystemCache, KernelTotal, KernelPaged, KernelNonpaged, PageSize;
            public uint HandleCount, ProcessCount, ThreadCount;
        }
        [StructLayout(LayoutKind.Sequential)] struct PowerStatus {
            public byte AcLine, BatteryFlag, BatteryPercent, Saver;
            public uint LifeSeconds, FullLifeSeconds;
        }
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetSystemTimes(out ulong idle, out ulong kernel, out ulong user);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetSystemPowerStatus(out PowerStatus status);
        [DllImport("kernel32.dll")] public static extern ulong GetTickCount64();
        [DllImport("kernel32.dll")] static extern uint GetActiveProcessorCount(ushort group);
        [DllImport("psapi.dll", SetLastError=true)] static extern bool GetPerformanceInfo(out PerformanceInfo info, uint size);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool GetDiskFreeSpaceEx(string root, out ulong available, out ulong total, out ulong free);
        [DllImport("powrprof.dll")] static extern uint PowerGetActiveScheme(IntPtr root, out IntPtr scheme);
        [DllImport("powrprof.dll")] static extern uint PowerSetActiveScheme(IntPtr root, ref Guid scheme);
        [DllImport("powrprof.dll")] static extern uint PowerEnumerate(IntPtr root, IntPtr scheme, IntPtr subgroup, uint access, uint index, [Out] byte[] buffer, ref uint size);
        [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr pointer);
        [DllImport("powrprof.dll")] static extern uint PowerReadACValueIndex(IntPtr root, ref Guid scheme, ref Guid subgroup, ref Guid setting, out uint value);
        [DllImport("powrprof.dll")] static extern uint PowerReadDCValueIndex(IntPtr root, ref Guid scheme, ref Guid subgroup, ref Guid setting, out uint value);
        [DllImport("powrprof.dll")] static extern uint PowerWriteACValueIndex(IntPtr root, ref Guid scheme, ref Guid subgroup, ref Guid setting, uint value);
        [DllImport("powrprof.dll")] static extern uint PowerWriteDCValueIndex(IntPtr root, ref Guid scheme, ref Guid subgroup, ref Guid setting, uint value);
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct ProcessEntry {
            public uint Size, Usage, ProcessId; public UIntPtr DefaultHeapId; public uint ModuleId, Threads, ParentProcessId;
            public int PriorityBase; public uint Flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string ExeFile;
        }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters {
            public ulong ReadOperations, WriteOperations, OtherOperations, ReadTransfer, WriteTransfer, OtherTransfer;
        }
        delegate bool WindowCallback(IntPtr window, IntPtr parameter);
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry entry);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry entry);
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr process, out long creation, out long exit, out long kernel, out long user);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessIoCounters(IntPtr process, out IoCounters counters);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, System.Text.StringBuilder name, ref uint size);
        [DllImport("kernel32.dll")] static extern bool ProcessIdToSessionId(int pid, out int session);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token, int infoClass, IntPtr buffer, int length, out int needed);
        [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback, IntPtr parameter);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out int pid);
        const uint QueryLimited = 0x1000, Terminate = 0x0001, Synchronize = 0x00100000, TokenQuery = 0x0008;
        ulong lastIdle, lastKernel, lastUser;
        bool hasCpu;

        public Sample Read(string drive) {
            Sample sample = new Sample();
            sample.AtUtc = DateTime.UtcNow;
            sample.MonotonicMs = (long)GetTickCount64();
            MemoryStatus memory = new MemoryStatus();
            memory.Length = (uint)Marshal.SizeOf(typeof(MemoryStatus));
            if (GlobalMemoryStatusEx(ref memory)) {
                sample.TotalPhysical = memory.TotalPhysical;
                sample.AvailablePhysical = memory.AvailablePhysical;
            } else sample.Errors.Add("RAM: Win32 " + Marshal.GetLastWin32Error());
            PerformanceInfo performance;
            if (GetPerformanceInfo(out performance, (uint)Marshal.SizeOf(typeof(PerformanceInfo)))) {
                sample.CommitUsed = performance.CommitTotal.ToUInt64() * performance.PageSize.ToUInt64();
                sample.CommitLimit = performance.CommitLimit.ToUInt64() * performance.PageSize.ToUInt64();
            } else sample.Errors.Add("Commit: Win32 " + Marshal.GetLastWin32Error());
            ulong idle, kernel, user;
            if (GetSystemTimes(out idle, out kernel, out user)) {
                if (hasCpu && kernel >= lastKernel && user >= lastUser && idle >= lastIdle) {
                    double total = (double)(kernel - lastKernel) + (double)(user - lastUser);
                    double idleDelta = (double)(idle - lastIdle);
                    if (total > 0 && idleDelta <= total) sample.CpuPercent = 100.0 * (total - idleDelta) / total;
                }
                lastIdle = idle; lastKernel = kernel; lastUser = user; hasCpu = true;
                if (GetActiveProcessorCount(0xffff) > 64) {
                    sample.CpuPercent = null;
                    sample.Errors.Add("CPU: GetSystemTimes restrito ao grupo atual neste host com mais de 64 processadores.");
                }
            } else sample.Errors.Add("CPU: Win32 " + Marshal.GetLastWin32Error());
            PowerStatus power;
            if (GetSystemPowerStatus(out power)) {
                if (power.AcLine <= 1) sample.ExternalPower = power.AcLine == 1;
                if (power.BatteryFlag != 255 && (power.BatteryFlag & 128) == 0) {
                    if (power.BatteryPercent <= 100) sample.BatteryPercent = power.BatteryPercent;
                    sample.Charging = (power.BatteryFlag & 8) != 0;
                    if (power.LifeSeconds != UInt32.MaxValue) sample.BatterySeconds = power.LifeSeconds;
                }
            } else sample.Errors.Add("Bateria: Win32 " + Marshal.GetLastWin32Error());
            ulong available, capacity, free;
            if (GetDiskFreeSpaceEx(drive, out available, out capacity, out free)) {
                sample.DiskAvailable = available; sample.DiskTotal = capacity;
            } else sample.Errors.Add("Disco: Win32 " + Marshal.GetLastWin32Error());
            using (Process process = Process.GetCurrentProcess()) sample.SelfRss = process.WorkingSet64;
            return sample;
        }
        public static string ActivePlan() {
            IntPtr pointer;
            uint code = PowerGetActiveScheme(IntPtr.Zero, out pointer);
            if (code != 0) throw new Win32Exception((int)code);
            try { return ((Guid)Marshal.PtrToStructure(pointer, typeof(Guid))).ToString(); }
            finally { LocalFree(pointer); }
        }
        public static string[] Plans() {
            List<string> plans = new List<string>();
            for (uint index = 0; index < 128; index++) {
                byte[] buffer = new byte[16]; uint size = 16;
                uint code = PowerEnumerate(IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 16, index, buffer, ref size);
                if (code == 259) return plans.ToArray();
                if (code != 0 || size != 16) throw new Win32Exception((int)code);
                plans.Add(new Guid(buffer).ToString());
            }
            throw new InvalidOperationException("Catálogo de planos excessivo; alteração bloqueada.");
        }
        public static void SetPlan(string value) {
            Guid plan = new Guid(value);
            uint code = PowerSetActiveScheme(IntPtr.Zero, ref plan);
            if (code != 0) throw new Win32Exception((int)code);
        }
        // Power setting index of an existing scheme. No scheme is created or duplicated.
        public static uint ReadSetting(string scheme, string subgroup, string setting, bool ac) {
            Guid s = new Guid(scheme), g = new Guid(subgroup), v = new Guid(setting); uint value;
            uint code = ac ? PowerReadACValueIndex(IntPtr.Zero, ref s, ref g, ref v, out value) : PowerReadDCValueIndex(IntPtr.Zero, ref s, ref g, ref v, out value);
            if (code != 0) throw new Win32Exception((int)code);
            return value;
        }
        public static void WriteSetting(string scheme, string subgroup, string setting, bool ac, uint value) {
            Guid s = new Guid(scheme), g = new Guid(subgroup), v = new Guid(setting);
            uint code = ac ? PowerWriteACValueIndex(IntPtr.Zero, ref s, ref g, ref v, value) : PowerWriteDCValueIndex(IntPtr.Zero, ref s, ref g, ref v, value);
            if (code != 0) throw new Win32Exception((int)code);
        }
        // Read-only process snapshot. Unreadable fields stay null/false; callers protect them.
        public static ProcInfo[] Processes() {
            HashSet<int> windows = new HashSet<int>();
            WindowCallback callback = delegate(IntPtr window, IntPtr parameter) {
                int owner; if (IsWindowVisible(window) && GetWindowThreadProcessId(window, out owner) != 0) windows.Add(owner);
                return true;
            };
            EnumWindows(callback, IntPtr.Zero);
            GC.KeepAlive(callback);
            List<ProcInfo> rows = new List<ProcInfo>();
            IntPtr snapshot = CreateToolhelp32Snapshot(2, 0);
            if (snapshot == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
            try {
                ProcessEntry entry = new ProcessEntry(); entry.Size = (uint)Marshal.SizeOf(typeof(ProcessEntry));
                if (!Process32FirstW(snapshot, ref entry)) throw new Win32Exception(Marshal.GetLastWin32Error());
                do {
                    ProcInfo row = new ProcInfo();
                    row.Pid = (int)entry.ProcessId; row.ParentPid = (int)entry.ParentProcessId; row.Threads = (int)entry.Threads;
                    row.Name = entry.ExeFile; row.HasWindow = windows.Contains(row.Pid);
                    int session; if (ProcessIdToSessionId(row.Pid, out session)) row.SessionId = session;
                    Fill(row);
                    rows.Add(row);
                    if (rows.Count > 4096) throw new InvalidOperationException("Lista de processos excessiva; triagem interrompida.");
                } while (Process32NextW(snapshot, ref entry));
            } finally { CloseHandle(snapshot); }
            return rows.ToArray();
        }
        static void Fill(ProcInfo row) {
            if (row.Pid == 0 || row.Pid == 4) return;
            IntPtr process = OpenProcess(QueryLimited, false, row.Pid);
            if (process == IntPtr.Zero) return;
            try {
                long creation, exit, kernel, user;
                if (GetProcessTimes(process, out creation, out exit, out kernel, out user)) { row.StartTicks = creation; row.CpuTicks = kernel + user; row.Queried = true; }
                IoCounters io; if (GetProcessIoCounters(process, out io)) { row.ReadBytes = io.ReadTransfer; row.WriteBytes = io.WriteTransfer; }
                System.Text.StringBuilder name = new System.Text.StringBuilder(1024); uint size = 1024;
                if (QueryFullProcessImageNameW(process, 0, name, ref size)) row.Path = name.ToString(0, (int)size);
                IntPtr token;
                if (OpenProcessToken(process, TokenQuery, out token)) {
                    try {
                        int needed; GetTokenInformation(token, 1, IntPtr.Zero, 0, out needed);
                        if (needed > 0 && needed < 4096) {
                            IntPtr buffer = Marshal.AllocHGlobal(needed);
                            try {
                                if (GetTokenInformation(token, 1, buffer, needed, out needed))
                                    row.OwnerSid = new System.Security.Principal.SecurityIdentifier(Marshal.ReadIntPtr(buffer)).Value;
                            } finally { Marshal.FreeHGlobal(buffer); }
                        }
                    } finally { CloseHandle(token); }
                }
            } finally { CloseHandle(process); }
        }
        // True only for the same live process: PID and creation time must both match.
        public static bool IsSameProcess(int pid, long startTicks) {
            IntPtr process = OpenProcess(QueryLimited, false, pid);
            if (process == IntPtr.Zero) return false;
            try {
                long creation, exit, kernel, user; uint code;
                return GetProcessTimes(process, out creation, out exit, out kernel, out user) && creation == startTicks
                    && GetExitCodeProcess(process, out code) && code == 259;
            } finally { CloseHandle(process); }
        }
        // Manual, separately confirmed force. Creation time is checked on the same handle.
        public static void TerminateSame(int pid, long startTicks) {
            IntPtr process = OpenProcess(QueryLimited | Terminate | Synchronize, false, pid);
            if (process == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            try {
                long creation, exit, kernel, user;
                if (!GetProcessTimes(process, out creation, out exit, out kernel, out user) || creation != startTicks) throw new InvalidOperationException("O PID agora pertence a outro processo; nada foi encerrado.");
                if (!TerminateProcess(process, 1)) throw new Win32Exception(Marshal.GetLastWin32Error());
            } finally { CloseHandle(process); }
        }
    }
}
