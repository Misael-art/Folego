"""Quota indicators, new completed sessions and verified application opening."""
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget

from ..core import ai_sessions
from .theme import TOKENS
from .workers import Poller
from .desktop_shortcuts import DesktopController
from ..core.agent_deliveries import DeliveryMonitor
from ..adapters.agent_apps import AgentApps


class AIStrip(QWidget):
    def __init__(self, parent=None, *, collect_fn=None, deliveries=None, opener=None):
        super().__init__(parent)
        self.items = [ai_sessions.unknown(p) for p in ai_sessions.NAMES]
        self.buttons = {}
        self.badges = {}
        self.deliveries = deliveries or DeliveryMonitor()
        self.delivery_items = []
        self.opener = opener or DesktopController(self, backend=AgentApps(self.deliveries))
        self.opener.result.connect(self._opened)
        self.opener.feedback.connect(self._notice)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for provider, label in (("codex", "Codex"), ("web", "Web"), ("claude", "Claude"), ("grok", "Grok")):
            button = QPushButton(label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": cota desconhecida")
            button.setStyleSheet("padding:3px 0;border:none;background:transparent;")
            button.clicked.connect(lambda checked=False, p=provider: self.open_agent(p))
            self.buttons[provider] = button
            column = QVBoxLayout()
            column.setSpacing(0)
            badge_row = QWidget()
            badge_row.setFixedHeight(14)
            badge_row.setStyleSheet('background:transparent;')
            badge_layout = QHBoxLayout(badge_row)
            badge_layout.setContentsMargins(0, 0, 0, 0)
            badge = QLabel()
            badge.setFixedSize(32, 14)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            badge_layout.addWidget(badge)
            badge_layout.addStretch(1)
            self.badges[provider] = badge
            column.addWidget(badge_row)
            column.addWidget(button)
            layout.addLayout(column, 1)
        self.delivery_poller = Poller(self.deliveries.collect, interval_s=5, parent=self, offload=True)
        self.destroyed.connect(self.delivery_poller._stop.set)
        self.delivery_poller.snapshot_ready.connect(self.set_deliveries)
        self.delivery_poller.error.connect(self._delivery_failed)
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
        self.items = [ai_sessions.unknown(p, "Consulta falhou; aguardando próxima atualização") for p in ai_sessions.NAMES]
        self.render()

    def set_deliveries(self, rows):
        self.delivery_items = rows
        self.render()

    def _delivery_failed(self, _message):
        self.set_deliveries([dict(provider=p, count=None, pending=[]) for p in ai_sessions.NAMES])

    def open_agent(self, provider):
        row = next((r for r in self.delivery_items if r['provider'] == provider), {})
        pending = row.get('pending', []) if row.get('count') is not None else []
        self.opener.request('agent-open', (provider, list(pending)))

    def _opened(self, _message):
        self.delivery_poller.request()

    def _notice(self, message):
        # The compact card owns visible transient feedback, separate from alerts.
        parent = self.window()
        show = getattr(parent, '_shortcut_result', None)
        if show: show(message)

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
            delivery = next((r for r in self.delivery_items if r['provider'] == provider), {})
            count = delivery.get('count')
            badge = self.badges[provider]
            partial = not delivery.get('complete', True)
            number = str(count) + ('+' if partial else '')
            badge.setText('?' if count is None else number if count else '')
            badge.setStyleSheet(f"background:{TOKENS.accent if count else TOKENS.muted if count is None else 'transparent'};"
                               f"color:{TOKENS.accent_text};font-size:8pt;font-weight:600;border-radius:6px;")
            completed = 'conclusões não verificadas' if count is None else f'{count} novas entregas para revisitar'
            if count and partial: completed = 'Pelo menos ' + completed + '; outras sessões não verificadas'
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": " + summary + ' · ' + completed)
            detail = "\n\n".join(ai_sessions.describe(item) for item in items) or "Sem observação"
            detail += '\n\n' + completed + '\nClique para abrir a aplicação/terminal e marcar estes avisos como vistos.'
            detail += '\nContagem de novas sessões concluídas desde a ativação do monitor; ferramentas não contam.'
            button.setToolTip("<p style='white-space:pre-wrap'>" + html.escape(detail) + "</p>")

    def showEvent(self, event):
        super().showEvent(event)
        self.poller.start()
        self.freshness.start()
        self.refresh()
        self.delivery_poller.start()
        self.delivery_poller.request()

    def hideEvent(self, event):
        self.poller.pause()
        self.freshness.stop()
        self.delivery_poller.pause()
        super().hideEvent(event)

    def shutdown(self):
        self.freshness.stop()
        self.poller.stop()
        self.delivery_poller.stop()
        self.opener.close()
