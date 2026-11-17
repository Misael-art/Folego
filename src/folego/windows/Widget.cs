// Widget window for Folego: never takes focus, stays out of the taskbar and Alt+Tab,
// floats above other windows, and moves by dragging any marked control.
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Folego.Windows {
    public class WidgetForm : Form {
        const int ToolWindow = 0x00000080, NoActivate = 0x08000000, Topmost = 0x00000008;
        [DllImport("user32.dll")] static extern bool ReleaseCapture();
        [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr w, IntPtr l);
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
        public event EventHandler DragFinished;

        public WidgetForm() {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            TopMost = true;
            StartPosition = FormStartPosition.Manual;
            DoubleBuffered = true;
            KeyPreview = true;
        }
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams {
            get { CreateParams p = base.CreateParams; p.ExStyle |= ToolWindow | NoActivate | Topmost; return p; }
        }
        protected override void OnHandleCreated(EventArgs e) {
            base.OnHandleCreated(e);
            // Windows 11 rounded corners; ignored where DWM does not support it.
            try { int round = 2; DwmSetWindowAttribute(Handle, 33, ref round, sizeof(int)); } catch (DllNotFoundException) { } catch (EntryPointNotFoundException) { }
        }
        public void MakeDraggable(Control control) {
            control.MouseDown += delegate(object sender, MouseEventArgs e) {
                if (e.Button != MouseButtons.Left) return;
                ReleaseCapture();
                SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero); // system move loop; returns on release
                EventHandler done = DragFinished;
                if (done != null) done(this, EventArgs.Empty);
            };
        }
    }

    // Live notification-area indicators: a number on the health colour, with a strip in the
    // metric's theme colour. Each icon owns its handle; the caller disposes the previous one.
    public static class TrayGlyph {
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr icon);
        static Icon Own(Bitmap bitmap) {
            IntPtr handle = bitmap.GetHicon();
            try { using (Icon borrowed = Icon.FromHandle(handle)) return (Icon)borrowed.Clone(); }
            finally { DestroyIcon(handle); }
        }
        public static Icon Text(string text, Color background, Color ink, Color strip, int size) {
            using (Bitmap bitmap = new Bitmap(size, size))
            using (Graphics g = Graphics.FromImage(bitmap)) {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                g.Clear(Color.Transparent);
                using (SolidBrush fill = new SolidBrush(background)) g.FillRectangle(fill, 0, 0, size, size);
                int band = Math.Max(2, size / 7);
                using (SolidBrush top = new SolidBrush(strip)) g.FillRectangle(top, 0, 0, size, band);
                float em = text.Length >= 3 ? size * 0.46f : size * 0.62f;
                using (Font font = new Font("Segoe UI", em, FontStyle.Bold, GraphicsUnit.Pixel))
                using (SolidBrush brush = new SolidBrush(ink))
                using (StringFormat center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center }) {
                    g.DrawString(text, font, brush, new RectangleF(-2, band - 1, size + 4, size - band + 2), center);
                }
                return Own(bitmap);
            }
        }
        public static Icon Dot(Color color, Color ring, int size) {
            using (Bitmap bitmap = new Bitmap(size, size))
            using (Graphics g = Graphics.FromImage(bitmap)) {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                int pad = Math.Max(1, size / 8);
                using (SolidBrush fill = new SolidBrush(color)) g.FillEllipse(fill, pad, pad, size - 2 * pad - 1, size - 2 * pad - 1);
                using (Pen edge = new Pen(ring, Math.Max(1, size / 12))) g.DrawEllipse(edge, pad, pad, size - 2 * pad - 1, size - 2 * pad - 1);
                return Own(bitmap);
            }
        }
        // Left click opens the same menu Windows shows on right click, positioned by the shell.
        public static void ShowMenu(NotifyIcon icon) {
            System.Reflection.MethodInfo show = typeof(NotifyIcon).GetMethod("ShowContextMenu", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            if (show != null) show.Invoke(icon, null);
        }
    }

    // Ring with the headroom number and the verdict word, like the Linux HealthGauge.
    public class HealthRing : Control {
        public Color TrackColor = Color.Gray, RingColor = Color.Green, TextColor = Color.Black, MutedColor = Color.DimGray;
        public int? Value;
        public string Verdict = "Desconhecido";
        public HealthRing() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Color.Transparent;
        }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int side = Math.Min(Width, Height) - 8, ring = Math.Max(5, side / 9);
            if (side <= ring * 2) return;
            Rectangle box = new Rectangle((Width - side) / 2, (Height - side) / 2, side, side);
            using (Pen track = new Pen(TrackColor, ring)) { track.StartCap = track.EndCap = LineCap.Round; g.DrawArc(track, box, 135, 270); }
            if (Value.HasValue) {
                using (Pen arc = new Pen(RingColor, ring)) {
                    arc.StartCap = arc.EndCap = LineCap.Round;
                    g.DrawArc(arc, box, 135, Math.Max(1, 270 * Math.Min(100, Math.Max(0, Value.Value)) / 100));
                }
            }
            string number = Value.HasValue ? Value.Value + "%" : "—";
            using (Font big = new Font(Font.FontFamily, Math.Max(7f, side / 5.5f), FontStyle.Bold, GraphicsUnit.Pixel))
            using (Font small = new Font(Font.FontFamily, Math.Max(6f, side / 9f), FontStyle.Regular, GraphicsUnit.Pixel))
            using (SolidBrush ink = new SolidBrush(TextColor))
            using (SolidBrush muted = new SolidBrush(MutedColor))
            using (StringFormat center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center }) {
                RectangleF top = new RectangleF(box.X, box.Y, box.Width, box.Height * 0.58f);
                RectangleF bottom = new RectangleF(box.X, box.Y + box.Height * 0.52f, box.Width, box.Height * 0.3f);
                g.DrawString(number, big, ink, top, center);
                g.DrawString(Verdict, small, muted, bottom, center);
            }
        }
    }
}
