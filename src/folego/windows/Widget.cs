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

    // Live notification-area indicators. The caption has its own background so the
    // metric's identity stays legible when the health colour changes.
    public static class TrayGlyph {
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr icon);
        static Icon Own(Bitmap bitmap) {
            IntPtr handle = bitmap.GetHicon();
            try { using (Icon borrowed = Icon.FromHandle(handle)) return (Icon)borrowed.Clone(); }
            finally { DestroyIcon(handle); }
        }
        // 3×5 pixel capitals keep four letters legible inside the shell's 16 px slot.
        static string CaptionGlyph(char letter) {
            switch (letter) {
                case 'A': return "010101111101101";
                case 'B': return "110101110101110";
                case 'C': return "011100100100011";
                case 'E': return "111100110100111";
                case 'M': return "101111111101101";
                case 'P': return "110101110100100";
                case 'R': return "110101110101101";
                case 'T': return "111010010010010";
                case 'U': return "101101101101111";
                default: throw new ArgumentOutOfRangeException("letter");
            }
        }
        static int Pixel(float unit, float scale) { return (int)Math.Round(unit * scale, MidpointRounding.AwayFromZero); }
        static void DrawCaption(Graphics g, string label, Color ink, int size) {
            float scale = size / 16f;
            float left = (16 - (4 * label.Length - 1)) / 2f;
            using (SolidBrush brush = new SolidBrush(ink)) {
                for (int letter = 0; letter < label.Length; letter++) {
                    string glyph = CaptionGlyph(label[letter]);
                    for (int cell = 0; cell < glyph.Length; cell++) {
                        if (glyph[cell] != '1') continue;
                        float x = left + 4 * letter + cell % 3;
                        int y = cell / 3;
                        int x0 = Pixel(x, scale), y0 = Pixel(y, scale);
                        g.FillRectangle(brush, x0, y0, Pixel(x + 1, scale) - x0, Pixel(y + 1, scale) - y0);
                    }
                }
            }
        }
        public static Icon Metric(string label, string value, Color background, Color ink, Color caption, Color captionInk, int size) {
            return Metric(label, value, background, ink, caption, captionInk, size, false);
        }
        public static Icon Metric(string label, string value, Color background, Color ink, Color caption, Color captionInk, int size, bool delayed) {
            using (Bitmap bitmap = new Bitmap(size, size))
            using (Graphics g = Graphics.FromImage(bitmap)) {
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                g.Clear(background);
                int band = Pixel(6, size / 16f);
                using (SolidBrush top = new SolidBrush(caption)) g.FillRectangle(top, 0, 0, size, band);
                DrawCaption(g, label, captionInk, size);
                float em = value.Length >= 3 ? size * 0.51f : size * 0.60f;
                using (StringFormat text = (StringFormat)StringFormat.GenericTypographic.Clone())
                using (Font font = new Font("Segoe UI", em, FontStyle.Bold, GraphicsUnit.Pixel))
                using (SolidBrush brush = new SolidBrush(ink))
                {
                    SizeF extent = g.MeasureString(value, font, PointF.Empty, text);
                    int mark = delayed ? Math.Max(1, size / 16) : 0;
                    g.DrawString(value, font, brush, new PointF((size - extent.Width) / 2, (size + band - extent.Height - mark) / 2), text);
                    if (delayed) {
                        for (int x = size / 4; x < size * 3 / 4; x += 3 * mark)
                            g.FillRectangle(brush, x, size - mark, mark, mark);
                    }
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
