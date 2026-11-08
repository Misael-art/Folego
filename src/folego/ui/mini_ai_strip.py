"""Compact quota cells backed by the shared AI monitor; no collection or effects."""
import time

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import ai_sessions
from ..core.battery_alerts import remaining_text
from .ai_strip import available_account, gift_icon
from .palettes import on_color
from .theme import background, on_theme_change, themed_style, TOKENS


class MiniAIStrip(QWidget):
    details_requested = Signal(str, str, object)
    changed = Signal()

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.buttons, self.values, self.badges, self.resets = {}, {}, {}, {}
        self.headings = {}
        self.accounts = {}
        self._signature = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for provider, name in ai_sessions.NAMES.items():
            button = QPushButton()
            button.setObjectName('miniQuota')
            button.setFixedHeight(34)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, p=provider: self.details_requested.emit(
                p, self.accounts.get(p, ''), self.buttons[p]))
            themed_style(button, lambda:
                         f'QPushButton#miniQuota{{background:{background(TOKENS.surface_alt)};'
                         'border:0;border-radius:6px;padding:0;min-height:0;}'
                         f'QPushButton#miniQuota:hover{{background:{background(TOKENS.surface)};}}')
            cell = QVBoxLayout(button)
            cell.setContentsMargins(6, 2, 6, 2)
            cell.setSpacing(0)
            heading = QHBoxLayout()
            heading.setSpacing(3)
            title = QLabel('Web' if provider == 'web' else name)
            themed_style(title, lambda: f'background:transparent;color:{TOKENS.muted};font-size:7pt;')
            heading.addWidget(title)
            badge = QLabel()
            badge.setFixedHeight(12)
            themed_style(badge, lambda: f'background:{TOKENS.accent};color:{on_color(TOKENS.accent)};'
                         'font-size:7pt;border-radius:4px;padding:0 2px;')
            heading.addWidget(badge)
            reset = QPushButton()
            reset.setFixedHeight(12)
            reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            themed_style(reset, lambda: f'background:{TOKENS.ok};color:{on_color(TOKENS.ok)};'
                         'font-size:7pt;border:0;border-radius:4px;padding:0 2px;min-height:0;')
            on_theme_change(reset, lambda target=reset: target.setIcon(gift_icon()))
            reset.setIcon(gift_icon())
            reset.setIconSize(QSize(9, 9))
            heading.addWidget(reset)
            heading.addStretch(1)
            value = QLabel('—')
            for label in (title, badge, reset, value):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                if isinstance(label, QLabel):
                    label.setTextFormat(Qt.TextFormat.PlainText)
            cell.addLayout(heading)
            cell.addWidget(value)
            layout.addWidget(button)
            button.hide()
            self.buttons[provider], self.values[provider] = button, value
            self.badges[provider], self.resets[provider] = badge, reset
            self.headings[provider] = heading
        self.monitor.quotas_ready.connect(self.refresh)
        self.monitor.deliveries_ready.connect(self.refresh)
        self.freshness = QTimer(self)
        self.freshness.setInterval(1000)
        self.freshness.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args):
        now = time.time()
        rows = []
        for provider, name in ai_sessions.NAMES.items():
            items = [i for i in self.monitor.items if i.get('provider') == provider]
            left, selected = available_account(items, now)
            reset_at = None
            if selected is None:
                returning = [(at, item) for item in items
                             if (at := ai_sessions.session_reset_at(item, now)) is not None]
                if returning:
                    reset_at, selected = min(returning, key=lambda pair: pair[0])
                    left = 0
                else:
                    selected = next((i for i in items if i.get('default')), items[0] if items else {})
                    left = ai_sessions.effective(selected, now)
            instances = None
            if provider == 'web':
                live = [(ai_sessions.web_instances(item, now), item) for item in items]
                live = [(n, item) for n, item in live if n is not None and n > 0]
                if live:
                    instances, selected = max(live, key=lambda pair: (pair[0], pair[1].get('default', False)))
                left = None
                reset_at = None
            delivery = next((row for row in self.monitor.delivery_items
                             if row.get('provider') == provider), {})
            count = delivery.get('count')
            partial = not delivery.get('complete', True)
            credits = [ai_sessions.available_resets(item, now) for item in items]
            tickets = sum(n for n in credits if n is not None)
            visible = ((left is not None and left > 0) or reset_at is not None
                       or bool(count) or tickets > 0)
            if provider == 'web':
                visible = instances is not None
            text = (f'Reset {remaining_text(round(reset_at - now))}' if reset_at is not None else
                    f'{left}%' if left is not None else '—')
            if provider == 'web' and instances is not None:
                text = 'OK'
            role = {'green': 'ok', 'yellow': 'warning', 'red': 'danger',
                    'unknown': 'muted'}[ai_sessions.band(left)]
            if provider == 'web' and instances is not None:
                role = 'ok'
            done = 'Entregas não verificadas' if count is None else (
                f'Pelo menos {count} entregas para revisitar' if partial else f'{count} entregas para revisitar')
            quota = ('Cota esgotada; reposição da janela de 5 h em ' +
                     remaining_text(round(reset_at - now)) if reset_at is not None else
                     f'{left}% de cota disponível' if left is not None else 'Cota não confirmada')
            resets_known = bool(credits) and all(n is not None for n in credits)
            resets = (f'{tickets} resets disponíveis confirmados' if tickets or resets_known
                      else 'Resets disponíveis não verificados')
            if tickets and any(n is None for n in credits):
                resets += '; outras contas não verificadas'
            detail = '\n'.join((name, selected.get('label', 'Conta não confirmada'), quota,
                                done, resets,
                                'Clique para consultar a conta'))
            if provider == 'web':
                status = ('Instâncias não verificadas' if instances is None else
                          f'{instances} instância(s) aberta(s); turno ativo não comprovado')
                detail = '\n'.join((name, selected.get('label', 'Conta não confirmada'),
                                    status, 'Limite e reposição não informados', done,
                                    'Clique para consultar a conta'))
            number = (str(min(count, 19)) + ('+' if count > 19 or partial else '')) if count else ''
            rows.append((provider, visible, text, role, number, tickets, detail,
                         selected.get('account_id', ''), left))
        signature = tuple(rows)
        if signature == self._signature:
            return
        self._signature = signature
        for provider, visible, text, role, number, tickets, detail, account, _left in rows:
            button, value = self.buttons[provider], self.values[provider]
            button.setVisible(visible)
            button.setAccessibleName(detail.replace('\n', ' · '))
            button.setToolTip(detail)
            value.setText(text)
            value.setProperty('level', role)
            themed_style(value, lambda level=role:
                         f'background:transparent;color:{getattr(TOKENS, level)};font-size:9pt;font-weight:600;')
            self.badges[provider].setText(number)
            self.badges[provider].setVisible(bool(number))
            self.resets[provider].setText(str(tickets) if tickets < 10 else '9+')
            self.resets[provider].setVisible(tickets > 0)
            self.accounts[provider] = account
            # QPushButton's own size hint ignores its caption/badge layout.
            button.ensurePolished()
            self.headings[provider].invalidate()
            button.layout().invalidate()
            button.setMinimumWidth(button.layout().minimumSize().width())
        order = sorted((row for row in rows if row[1]),
                       key=lambda row: (row[8] is None, -(row[8] or 0)))
        for index, row in enumerate(order):
            self.layout().insertWidget(index, self.buttons[row[0]])
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()
        self.changed.emit()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.freshness.start()

    def hideEvent(self, event):
        self.freshness.stop()
        super().hideEvent(event)
