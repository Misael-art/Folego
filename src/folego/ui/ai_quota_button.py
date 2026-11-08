"""PhaseZero-style quota rings, using only Fôlego's existing observations."""
import math

from PySide6.QtCore import Qt, QRectF, QSize, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QToolButton, QSizePolicy

from ..core import ai_sessions


# Provider identity matches PhaseZero's quota meter, independently of UI themes.
PROVIDER_COLORS = dict(codex='#2563eb', web='#2563eb', claude='#d97757', grok='#9ca3af')
LEVEL_COLORS = dict(green='#16a34a', yellow='#eab308', red='#dc2626')


class QuotaButton(QToolButton):
    def __init__(self, provider, label, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.remaining = None
        self.displayed = None
        self.halo = 0.0
        self.instance_active = False
        self.ring_size = 30
        self.setText(label)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(30, 30))
        self.setFixedHeight(49)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('QToolButton{padding:0;border:none;background:transparent;font-size:8pt;}'
                          'QToolButton:hover{ text-decoration:underline; }')
        self.transition = QVariantAnimation(self)
        self.transition.setDuration(450)
        self.transition.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.transition.valueChanged.connect(self._frame)
        self._draw_icon()

    def set_presentation(self, vertical):
        self.ring_size = 42 if vertical else 30
        self.setIconSize(QSize(self.ring_size, self.ring_size))
        self.setFixedHeight(61 if vertical else 49)
        self._draw_icon()

    def set_remaining(self, value):
        if value == self.remaining:
            return
        previous = self.displayed
        self.remaining = value
        self.transition.stop()
        # Missing or expired evidence takes effect immediately, even mid-frame.
        if previous is None or value is None or not self.isVisible():
            self.displayed = value
            self._draw_icon()
        else:
            self.transition.setStartValue(float(previous))
            self.transition.setEndValue(float(value))
            self.transition.start()
            self._draw_icon()

    def _frame(self, value):
        self.displayed = value
        self._draw_icon()

    def set_halo(self, value):
        if self.halo != value:
            self.halo = value
            self._draw_icon()

    def set_instance_active(self, active):
        active = self.provider == 'web' and bool(active)
        if self.instance_active != active:
            self.instance_active = active
            self._draw_icon()

    def _draw_icon(self):
        # Render at the target screen's scale; retain PhaseZero's 64-unit geometry.
        ratio = self.devicePixelRatioF()
        pixels = math.ceil(self.ring_size * ratio)
        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(pixels / 64, pixels / 64)
        ring = QRectF(5, 5, 54, 54)
        painter.setPen(QPen(QColor(128, 128, 128, 110), 7))
        painter.drawEllipse(ring)
        if self.instance_active:
            painter.setPen(QPen(QColor(LEVEL_COLORS['green']), 7))
            painter.drawEllipse(ring)
        elif self.remaining is not None:
            color = QColor(LEVEL_COLORS[ai_sessions.band(self.remaining)])
            painter.setPen(QPen(color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(ring, 90 * 16, round(-360 * 16 * self.displayed / 100))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PROVIDER_COLORS[self.provider]))
        painter.drawEllipse(QRectF(14, 14, 36, 36))
        if self.halo:
            # Completion pulse is a separate inner rim, never a quota arc.
            color = QColor('#ffffff')
            color.setAlpha(round(180 * self.halo))
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(13, 13, 38, 38))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(18 if self.instance_active or self.remaining == 100 else 22)
        painter.setFont(font)
        painter.setPen(QColor('#ffffff'))
        painter.drawText(QRectF(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter,
                         'OK' if self.instance_active else '?' if self.remaining is None else str(self.remaining))
        painter.end()
        pixmap.setDevicePixelRatio(pixels / self.ring_size)
        self.setIcon(QIcon(pixmap))

    def hideEvent(self, event):
        self.transition.stop()
        self.displayed = self.remaining
        self.set_halo(0.0)
        self._draw_icon()
        super().hideEvent(event)

    def showEvent(self, event):
        self._draw_icon()
        super().showEvent(event)
