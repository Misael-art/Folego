"""Four quiet quota indicators with honest, per-account hover details."""
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..core import ai_sessions
from .theme import TOKENS
from .workers import Poller


class AIStrip(QWidget):
    def __init__(self, parent=None, *, collect_fn=None):
        super().__init__(parent)
        self.items = [ai_sessions.unknown(p) for p in ai_sessions.NAMES]
        self.buttons = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for provider, label in (("codex", "Codex"), ("web", "Web"), ("claude", "Claude"), ("grok", "Grok")):
            button = QPushButton(label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": cota desconhecida")
            button.setStyleSheet("padding:3px 0;border:none;background:transparent;")
            button.clicked.connect(self.refresh)
            self.buttons[provider] = button
            layout.addWidget(button, 1)
        self.poller = Poller(collect_fn or ai_sessions.collect, interval_s=60, parent=self, offload=True)
        # Destruction must stop the Python worker without touching deleted timers.
        self.destroyed.connect(self.poller._stop.set)
        self.poller.snapshot_ready.connect(self.set_items)
        self.poller.error.connect(self.failed)
        self.freshness = QTimer(self)
        self.freshness.setInterval(1000)
        self.freshness.timeout.connect(self.render)
        self.render()

    def refresh(self):
        self.poller.request()

    def set_items(self, items):
        self.items = items
        self.render()

    def failed(self, _message):
        self.items = [ai_sessions.unknown(p, "Consulta falhou; clique para atualizar") for p in ai_sessions.NAMES]
        self.render()

    def render(self):
        colors = dict(green=TOKENS.ok, yellow=TOKENS.warning, red=TOKENS.danger, unknown=TOKENS.muted)
        for provider, button in self.buttons.items():
            items = [item for item in self.items if item.get("provider") == provider]
            values = [ai_sessions.effective(item) for item in items]
            left = min(values) if values and all(v is not None for v in values) else None
            pixmap = QPixmap(10, 10)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors[ai_sessions.band(left)]))
            painter.drawEllipse(1, 1, 8, 8)
            painter.end()
            button.setIcon(QIcon(pixmap))
            summary = "cota desconhecida" if left is None else f"{left}% disponível"
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": " + summary)
            detail = "\n\n".join(ai_sessions.describe(item) for item in items) or "Sem observação"
            button.setToolTip("<p style='white-space:pre-wrap'>" + html.escape(detail) + "</p>")

    def showEvent(self, event):
        super().showEvent(event)
        self.poller.start()
        self.freshness.start()
        self.refresh()

    def hideEvent(self, event):
        self.poller.pause()
        self.freshness.stop()
        super().hideEvent(event)

    def shutdown(self):
        self.freshness.stop()
        self.poller.stop()
