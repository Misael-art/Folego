using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Automation;
using System.Windows.Forms;

namespace Folego.Windows {
    public sealed class TextContextTarget : EventArgs {
        public Point Position { get; internal set; }
        internal IntPtr Window, Hit;
        internal uint Process;
        internal long At;
        internal int[] Element;
        internal bool Released;
    }

    // The hook only observes the right button. It always forwards the original input.
    // Accessibility queries run off the UI thread, with at most one outstanding query.
    public sealed class TextContextWatcher : IDisposable {
        const int RightDown = 0x204, RightUp = 0x205;
        static readonly long Frequency = Stopwatch.Frequency;
        readonly Control dispatcher;
        readonly HookProc callback;
        readonly uint ownProcess;
        IntPtr hook;
        TextContextTarget pending;
        int probing;
        bool disposed;
        public event EventHandler<TextContextTarget> Found;
        public event EventHandler<ShortcutResult> ShortcutCompleted;

        public sealed class ShortcutResult : EventArgs {
            public bool Sent { get; private set; }
            internal ShortcutResult(bool sent) { Sent = sent; }
        }

        delegate IntPtr HookProc(int code, IntPtr message, IntPtr data);
        [StructLayout(LayoutKind.Sequential)] struct MouseData {
            public Point Position;
            public uint Data, Flags, Time;
            public UIntPtr Extra;
        }
        [StructLayout(LayoutKind.Sequential)] struct GuiInfo {
            public uint Size, Flags;
            public IntPtr Active, Focus, Capture, Menu, Move, Caret;
            public Rectangle CaretRect;
        }
        [StructLayout(LayoutKind.Sequential)] struct KeyData {
            public ushort VirtualKey, Scan;
            public uint Flags, Time;
            public UIntPtr Extra;
        }
        [StructLayout(LayoutKind.Sequential)] struct InputData {
            public uint Type;
            public InputUnion Data;
        }
        [StructLayout(LayoutKind.Sequential)] struct MouseInput {
            public int X, Y;
            public uint Data, Flags, Time;
            public UIntPtr Extra;
        }
        [StructLayout(LayoutKind.Explicit)] struct InputUnion {
            [FieldOffset(0)] public KeyData Key;
            [FieldOffset(0)] public MouseInput Mouse;
        }
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr SetWindowsHookEx(int id, HookProc fn, IntPtr module, uint thread);
        [DllImport("user32.dll")] static extern bool UnhookWindowsHookEx(IntPtr handle);
        [DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr handle, int code, IntPtr message, IntPtr data);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandle(string name);
        [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window, uint flags);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
        [DllImport("user32.dll")] static extern bool GetGUIThreadInfo(uint thread, ref GuiInfo info);
        [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
        [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint count, InputData[] inputs, int size);

        public TextContextWatcher(Control dispatcher) {
            if (!dispatcher.IsHandleCreated) throw new ArgumentException("A Forms handle is required.", "dispatcher");
            this.dispatcher = dispatcher;
            using (Process current = Process.GetCurrentProcess()) ownProcess = (uint)current.Id;
            callback = Observe;
            hook = SetWindowsHookEx(14, callback, GetModuleHandle(null), 0);
            if (hook == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        static bool Recent(TextContextTarget target, int seconds) {
            return Stopwatch.GetTimestamp() - target.At <= Frequency * seconds;
        }
        static bool SameWindow(TextContextTarget target) {
            uint process;
            return GetForegroundWindow() == target.Window &&
                   GetWindowThreadProcessId(target.Window, out process) != 0 && process == target.Process;
        }
        IntPtr Observe(int code, IntPtr message, IntPtr data) {
            try {
                if (!disposed && code >= 0 && (message == (IntPtr)RightDown || message == (IntPtr)RightUp)) {
                    var mouse = (MouseData)Marshal.PtrToStructure(data, typeof(MouseData));
                    if (message == (IntPtr)RightDown) Detect(mouse.Position);
                    else if (pending != null) {
                        if (Math.Abs(pending.Position.X - mouse.Position.X) > 8 ||
                            Math.Abs(pending.Position.Y - mouse.Position.Y) > 8) pending = null;
                        else {
                            pending.Released = true;
                            // Do not run Forms handlers in the hook callback.
                            QueueToUi(ShowIfReady);
                        }
                    }
                }
            } catch (Exception) { pending = null; }
            return CallNextHookEx(hook, code, message, data);
        }
        void Detect(Point position) {
            pending = null;
            IntPtr hit = WindowFromPoint(position);
            IntPtr root = GetAncestor(hit, 2);
            uint process;
            if (root == IntPtr.Zero || root != GetForegroundWindow() ||
                GetWindowThreadProcessId(root, out process) == 0 || process == ownProcess) return;
            if (Interlocked.CompareExchange(ref probing, 1, 0) != 0) return;
            var target = new TextContextTarget { Position = position, Window = root, Hit = hit, Process = process, At = Stopwatch.GetTimestamp() };
            pending = target;
            ThreadPool.QueueUserWorkItem(delegate {
                int[] identity = null;
                try {
                    var point = new System.Windows.Point(position.X, position.Y);
                    identity = Editable(AutomationElement.FromPoint(point), target.Process, point);
                    if (identity == null) identity = Editable(AutomationElement.FromHandle(target.Hit), target.Process, point);
                } catch (ElementNotAvailableException) { }
                  catch (COMException) { }
                  catch (ArgumentException) { }
                  catch (InvalidOperationException) { }
                  catch (UnauthorizedAccessException) { }
                  catch (TimeoutException) { }
                finally { Interlocked.Exchange(ref probing, 0); }
                QueueToUi(delegate {
                    if (pending != target) return;
                    target.Element = identity;
                    ShowIfReady();
                });
            });
        }
        static int[] Editable(AutomationElement element, uint process, System.Windows.Point? point) {
            for (int depth = 0; element != null && depth < 5; depth++, element = TreeWalker.RawViewWalker.GetParent(element)) {
                var current = element.Current;
                if ((uint)current.ProcessId != process || current.IsPassword || !current.IsEnabled || current.IsOffscreen) return null;
                if (current.ControlType != ControlType.Edit && current.ControlType != ControlType.Document) continue;
                if (point.HasValue && !current.BoundingRectangle.Contains(point.Value)) return null;
                object pattern;
                if (element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern))
                    return ((ValuePattern)pattern).Current.IsReadOnly ? null : element.GetRuntimeId();
                if (!current.IsKeyboardFocusable || !element.TryGetCurrentPattern(TextPattern.Pattern, out pattern)) return null;
                object readOnly = ((TextPattern)pattern).DocumentRange.GetAttributeValue(TextPattern.IsReadOnlyAttribute);
                return readOnly is bool && !(bool)readOnly ? element.GetRuntimeId() : null;
            }
            return null;
        }
        void QueueToUi(Action work) {
            try { dispatcher.BeginInvoke((Action)delegate { if (!disposed) work(); }); }
            catch (InvalidOperationException) { }
        }
        void ShowIfReady() {
            var target = pending;
            if (target == null || !target.Released || target.Element == null) return;
            pending = null;
            if (!Recent(target, 2) || !SameWindow(target)) return;
            var found = Found;
            if (found != null) found(this, target);
        }
        static bool FocusWindow(TextContextTarget target, out IntPtr focus) {
            focus = IntPtr.Zero;
            if (target == null || !Recent(target, 30) || !SameWindow(target)) return false;
            uint process;
            uint thread = GetWindowThreadProcessId(target.Window, out process);
            var info = new GuiInfo { Size = (uint)Marshal.SizeOf(typeof(GuiInfo)) };
            if (!GetGUIThreadInfo(thread, ref info) || (info.Flags & 0x1C) != 0 || info.Focus == IntPtr.Zero) return false;
            focus = info.Focus;
            return true;
        }
        public void ApplyShortcut(TextContextTarget target, int[] keys) {
            IntPtr before;
            if (disposed || keys == null || keys.Length < 1 || keys.Length > 5 || !FocusWindow(target, out before) ||
                Interlocked.CompareExchange(ref probing, 1, 0) != 0) {
                Report(false);
                return;
            }
            ThreadPool.QueueUserWorkItem(delegate {
                int[] identity = null;
                try { identity = Editable(AutomationElement.FocusedElement, target.Process, null); }
                catch (ElementNotAvailableException) { }
                catch (COMException) { }
                catch (InvalidOperationException) { }
                catch (UnauthorizedAccessException) { }
                catch (TimeoutException) { }
                finally { Interlocked.Exchange(ref probing, 0); }
                QueueToUi(delegate {
                    IntPtr after;
                    bool same = EqualElements(target.Element, identity) && FocusWindow(target, out after) && after == before;
                    Report(same && SendKeysOnce(keys));
                });
            });
        }
        static bool EqualElements(int[] first, int[] second) {
            if (first == null || second == null || first.Length == 0 || first.Length != second.Length) return false;
            for (int index = 0; index < first.Length; index++) if (first[index] != second[index]) return false;
            return true;
        }
        static InputData Key(int code, bool release) {
            uint flags = release ? 2u : 0u;
            if (code == 91 || (code >= 33 && code <= 46)) flags |= 1;
            return new InputData { Type = 1, Data = new InputUnion { Key = new KeyData { VirtualKey = (ushort)code, Flags = flags } } };
        }
        static bool SendKeysOnce(int[] keys) {
            foreach (int modifier in new[] { 16, 17, 18, 91, 92 }) if (GetAsyncKeyState(modifier) < 0) return false;
            for (int index = 0; index < keys.Length; index++)
                if (keys[index] < 1 || keys[index] > 255 || GetAsyncKeyState(keys[index]) < 0) return false;
            var input = new InputData[keys.Length * 2];
            for (int index = 0; index < keys.Length; index++) {
                input[index] = Key(keys[index], false);
                input[input.Length - 1 - index] = Key(keys[index], true);
            }
            int size = Marshal.SizeOf(typeof(InputData));
            uint sent = SendInput((uint)input.Length, input, size);
            if (sent == input.Length) return true;
            if (sent > 0) {
                int held = (int)Math.Min(sent, (uint)input.Length - sent);
                var releases = new InputData[held];
                for (int index = 0; index < held; index++) releases[index] = Key(keys[held - 1 - index], true);
                SendInput((uint)held, releases, size);
            }
            return false;
        }
        void Report(bool sent) {
            var completed = ShortcutCompleted;
            if (completed != null) completed(this, new ShortcutResult(sent));
        }
        public void Dispose() {
            disposed = true;
            pending = null;
            if (hook != IntPtr.Zero) { UnhookWindowsHookEx(hook); hook = IntPtr.Zero; }
        }
    }
}
