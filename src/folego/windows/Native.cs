// Windows backend for Folego. No process termination, driver or TDP APIs.
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
    }
}
