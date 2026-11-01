"""Quota indicators, new completed sessions and verified application opening."""
from PySide6.QtCore import Qt, QTimer, QUrl, QEvent, QPoint
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
                              QMenu, QInputDialog, QWidgetAction)

from ..core import ai_sessions
from .theme import TOKENS
from .workers import Poller
from .desktop_shortcuts import DesktopController
from ..core.agent_deliveries import DeliveryMonitor
from ..adapters.agent_apps import AgentApps
from .ai_account_panel import AccountPanel


class AIStrip(QWidget):
    def __init__(self, parent=None, *, collect_fn=None, deliveries=None, opener=None):
        super().__init__(parent)
        self.items = [ai_sessions.unknown(p) for p in ai_sessions.NAMES]
        self.account_menu = None
        self.account_panel = None
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
            button.installEventFilter(self)
            button.clicked.connect(lambda checked=False, p=provider: self.open_agent(p))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point, p=provider: self.options(p, point))
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

    def default_item(self, provider):
        items = [i for i in self.items if i['provider'] == provider]
        return next((i for i in items if i.get('default')), items[0] if items else {})

    def open_agent(self, provider, account=None):
        account = account or self.default_item(provider).get('account_id')
        row = next((r for r in self.delivery_items if r['provider'] == provider), {})
        pending = row.get('pending', []) if row.get('count') is not None else []
        if account:
            pending = [p for p in pending if p.get('account_id') == account]
        self.opener.request('agent-open', (provider, list(pending), account) if account else (provider, list(pending)))

    def _opened(self, _message):
        self.delivery_poller.request()
        self.refresh()

    def options(self, provider, point):
        button = self.buttons[provider]
        menu = QMenu(button)
        menu.addAction('Atualizar dados', self.refresh)
        menu.addAction('Contas, uso e renovação…', lambda: QTimer.singleShot(0, lambda: self.details(provider)))
        menu.addAction('Definir dia da renovação mensal…', lambda: self.billing(provider))
        urls = {'codex': 'https://chatgpt.com/codex/settings/usage',
                'web': 'https://chatgpt.com/#settings/Account',
                'claude': 'https://claude.ai/settings/usage', 'grok': 'https://grok.com/usage'}
        menu.addAction('Consultar no site do provedor', lambda: QDesktopServices.openUrl(QUrl(urls[provider])))
        menu.exec(button.mapToGlobal(point))
        menu.deleteLater()

    def details(self, provider):
        if self.account_menu is not None:
            self.account_menu.close()
        button = self.buttons[provider]
        menu = QMenu(button)
        panel = AccountPanel(provider, [i for i in self.items if i['provider'] == provider])
        area = button.screen().availableGeometry()
        panel.setFixedSize(min(560, area.width() - 20), min(470, area.height() - 24))
        panel.open_requested.connect(lambda p, a: (menu.close(), self.open_agent(p, a)))
        panel.billing_requested.connect(lambda p, a: (menu.close(), self.billing(p, a)))
        panel.refresh_requested.connect(self.refresh)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        self.account_menu, self.account_panel = menu, panel
        menu.aboutToHide.connect(lambda: self._panel_hidden(menu))
        point = button.mapToGlobal(QPoint(0, button.height()))
        point.setX(max(area.left(), min(point.x(), area.right() + 1 - panel.width() - 4)))
        point.setY(max(area.top(), min(point.y(), area.bottom() + 1 - panel.height() - 4)))
        menu.popup(point)

    def _panel_hidden(self, menu):
        if self.account_menu is menu:
            self.account_menu = None
            self.account_panel = None
        menu.deleteLater()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            provider = next((p for p, b in self.buttons.items() if b is watched), None)
            if provider:
                self.details(provider)
                return True
        return super().eventFilter(watched, event)

    def billing(self, provider, account=None):
        item = next((i for i in self.items if account and i.get('account_id') == account), self.default_item(provider))
        account = item.get('account_id')
        current = item.get('billing_day', 0)
        day, accepted = QInputDialog.getInt(self, 'Renovação mensal · ' + ai_sessions.NAMES[provider],
             'Dia da cobrança mensal (1–31; 0 remove).\nReferência pessoal, sem confirmação de cobrança pelo provedor.', current, 0, 31)
        if accepted: self.opener.request('agent-billing', (provider, day, account) if account else (provider, day))

    def _notice(self, message):
        # The compact card owns visible transient feedback, separate from alerts.
        parent = self.window()
        show = getattr(parent, '_shortcut_result', None)
        if show: show(message)

    def render(self):
        colors = dict(green=TOKENS.ok, yellow=TOKENS.warning, red=TOKENS.danger, unknown=TOKENS.muted)
        for provider, button in self.buttons.items():
            items = [item for item in self.items if item.get("provider") == provider]
            left = ai_sessions.effective(self.default_item(provider))
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
            button.setToolTip('Uso e renovação por conta · clique para abrir o cliente da conta padrão')
        if self.account_panel is not None:
            panel = self.account_panel
            items = [i for i in self.items if i['provider'] == panel.provider]
            if {i.get('account_id', '') for i in items} == set(panel.account_buttons):
                panel.update_items(items)
            else:
                self.account_menu.close()

    def showEvent(self, event):
        super().showEvent(event)
        self.poller.start()
        self.freshness.start()
        self.refresh()
        self.delivery_poller.start()
        self.delivery_poller.request()

    def hideEvent(self, event):
        if self.account_menu is not None: self.account_menu.close()
        self.poller.pause()
        self.freshness.stop()
        self.delivery_poller.pause()
        super().hideEvent(event)

    def shutdown(self):
        if self.account_menu is not None: self.account_menu.close()
        self.freshness.stop()
        self.poller.stop()
        self.delivery_poller.stop()
        self.opener.close()
