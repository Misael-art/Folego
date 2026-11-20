using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Folego.Windows {
    public sealed class DiagnosticDisk {
        public readonly int Number;
        public readonly string Volume;
        public readonly string Device;

        DiagnosticDisk(int number, string volume, string device) {
            Number = number;
            Volume = volume;
            Device = device;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct DiskExtent { public uint Number; public long Start, Length; }
        [StructLayout(LayoutKind.Sequential)]
        struct VolumeExtents { public uint Count; public DiskExtent Extent; }

        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool GetVolumeNameForVolumeMountPointW(string root, StringBuilder volume, uint size);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr attributes, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool DeviceIoControl(SafeFileHandle handle, uint code, IntPtr input, uint inputBytes,
            out VolumeExtents output, uint outputBytes, out uint returned, IntPtr overlapped);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern uint QueryDosDeviceW(string name, [Out] char[] target, int size);

        public static DiagnosticDisk Resolve(string root) {
            // The diagnostic only targets a local Windows drive root.
            if (root == null || root.Length != 3 || root[1] != ':' || root[2] != '\\') return null;
            var volume = new StringBuilder(64);
            if (!GetVolumeNameForVolumeMountPointW(root, volume, (uint)volume.Capacity)) return null;
            string volumePath = volume.ToString();
            using (var handle = CreateFileW(volumePath.TrimEnd('\\'), 0, 7, IntPtr.Zero, 3, 0, IntPtr.Zero)) {
                if (handle.IsInvalid) return null;
                VolumeExtents extents;
                uint bytes;
                uint size = (uint)Marshal.SizeOf(typeof(VolumeExtents));
                const uint volumeDiskExtents = 0x00560000;
                if (!DeviceIoControl(handle, volumeDiskExtents, IntPtr.Zero, 0, out extents, size, out bytes, IntPtr.Zero)
                    || bytes < size || extents.Count != 1 || extents.Extent.Number > Int32.MaxValue || extents.Extent.Length <= 0) return null;
                var target = new char[1024];
                string number = extents.Extent.Number.ToString(CultureInfo.InvariantCulture);
                uint length = QueryDosDeviceW("PhysicalDrive" + number, target, target.Length);
                int end = length == 0 ? -1 : Array.IndexOf(target, '\0');
                if (end <= 0) return null;
                return new DiagnosticDisk((int)extents.Extent.Number, volumePath, new string(target, 0, end));
            }
        }

        public bool SameAs(DiagnosticDisk other) {
            return other != null && Number == other.Number
                && String.Equals(Volume, other.Volume, StringComparison.OrdinalIgnoreCase)
                && String.Equals(Device, other.Device, StringComparison.OrdinalIgnoreCase);
        }
    }

    // Persistent, language-neutral PDH query, adapted from the Deck panel's read-only collector.
    public sealed class DiagnosticCounters : IDisposable {
        [StructLayout(LayoutKind.Explicit, Size=16)]
        struct CounterValue {
            [FieldOffset(0)] public uint Status;
            [FieldOffset(8)] public double Value;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct CounterItem { public IntPtr Name; public CounterValue Value; }

        [DllImport("pdh.dll")] static extern uint PdhOpenQueryW(IntPtr source, UIntPtr data, out IntPtr query);
        [DllImport("pdh.dll", CharSet=CharSet.Unicode)]
        static extern uint PdhAddEnglishCounterW(IntPtr query, string path, UIntPtr data, out IntPtr counter);
        [DllImport("pdh.dll")] static extern uint PdhCollectQueryData(IntPtr query);
        [DllImport("pdh.dll")]
        static extern uint PdhGetFormattedCounterValue(IntPtr counter, uint format, out uint type, out CounterValue value);
        [DllImport("pdh.dll")]
        static extern uint PdhGetFormattedCounterArrayW(IntPtr counter, uint format, ref uint bytes, out uint count, IntPtr buffer);
        [DllImport("pdh.dll")] static extern uint PdhCloseQuery(IntPtr query);

        const uint FormatDouble = 0x200, BufferSize = 65536;
        IntPtr query, buffer;
        readonly IntPtr[] counters;
        readonly string diskPrefix;
        readonly int diskCounterCount;
        readonly int itemSize = Marshal.SizeOf(typeof(CounterItem));

        public DiagnosticCounters(string[] paths, int diskCounterCount, int diskNumber) {
            this.diskCounterCount = diskCounterCount;
            diskPrefix = diskNumber < 0 ? null : diskNumber.ToString(CultureInfo.InvariantCulture);
            counters = new IntPtr[paths.Length];
            if (PdhOpenQueryW(IntPtr.Zero, UIntPtr.Zero, out query) != 0) {
                query = IntPtr.Zero;
                return;
            }
            try {
                for (int i = 0; i < paths.Length; i++) {
                    if (i < diskCounterCount && diskPrefix == null) continue;
                    IntPtr counter;
                    if (PdhAddEnglishCounterW(query, paths[i], UIntPtr.Zero, out counter) == 0) counters[i] = counter;
                }
                if (diskPrefix != null) buffer = Marshal.AllocHGlobal((int)BufferSize);
                PdhCollectQueryData(query);
            } catch { Dispose(); throw; }
        }

        public static bool IsDiskInstance(string name, string number) {
            return name != null && (name.Equals(number, StringComparison.Ordinal)
                || name.StartsWith(number + " ", StringComparison.Ordinal));
        }

        static double? Valid(CounterValue value) {
            return value.Status <= 1 && value.Value >= 0 && !Double.IsInfinity(value.Value)
                ? (double?)value.Value : null;
        }

        double? ReadDiskCounter(IntPtr counter) {
            uint bytes = BufferSize, count;
            if (PdhGetFormattedCounterArrayW(counter, FormatDouble, ref bytes, out count, buffer) != 0
                || count > BufferSize / itemSize) return null;
            double? value = null;
            bool found = false;
            for (int i = 0; i < count; i++) {
                var item = (CounterItem)Marshal.PtrToStructure(IntPtr.Add(buffer, i * itemSize), typeof(CounterItem));
                if (!IsDiskInstance(Marshal.PtrToStringUni(item.Name), diskPrefix)) continue;
                if (found) return null;
                found = true;
                value = Valid(item.Value);
            }
            return value;
        }

        public double?[] Read(bool diskStillMatches) {
            var result = new double?[counters.Length];
            if (query == IntPtr.Zero || PdhCollectQueryData(query) != 0) return result;
            for (int i = 0; i < counters.Length; i++) {
                if (counters[i] == IntPtr.Zero) continue;
                if (i < diskCounterCount) {
                    if (diskStillMatches) result[i] = ReadDiskCounter(counters[i]);
                } else {
                    CounterValue value;
                    uint type;
                    if (PdhGetFormattedCounterValue(counters[i], FormatDouble, out type, out value) == 0) result[i] = Valid(value);
                }
            }
            return result;
        }

        public void Dispose() {
            if (query != IntPtr.Zero) { PdhCloseQuery(query); query = IntPtr.Zero; }
            if (buffer != IntPtr.Zero) { Marshal.FreeHGlobal(buffer); buffer = IntPtr.Zero; }
        }
    }
}
