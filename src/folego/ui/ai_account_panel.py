"""Interactive quota card: accounts at left, current allowance at right."""
import calendar
import datetime as dt
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
                              QScrollArea, QProgressBar, QFrame)

from ..core import ai_sessions as ai
from .theme import TOKENS as T


def date(at):
    return dt.datetime.fromtimestamp(at).astimezone().strftime('%d/%m · %H:%M')


def until(at, now):
    seconds = max(0, int(at - now))
    days, hours = divmod(seconds // 3600, 24)
    return f'{days}d {hours}h' if days else f'{hours}h {seconds // 60 % 60:02}min'


class AccountPanel(QWidget):
    open_requested = Signal(str, str)
    billing_requested = Signal(str, str)
    refresh_requested = Signal()

    def __init__(self, provider, items, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.items = items or [ai.unknown(provider)]
        self._signature = None
        self.selected = next((i.get('account_id', '') for i in self.items if i.get('default')), self.items[0].get('account_id', ''))
        self.setStyleSheet(f'QWidget{{background:{T.surface};color:{T.text};}}'
                          f'QPushButton{{padding:5px;border:1px solid {T.border};border-radius:5px;}}'
                          f'QPushButton:checked{{background:{T.surface_alt};border-color:{T.accent};}}'
                          f'QProgressBar{{border:none;background:{T.border};height:5px;max-height:5px;}}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        title = QHBoxLayout()
        heading = QLabel(ai.NAMES[provider] + ' · uso e renovação')
        heading.setStyleSheet('font-size:12pt;font-weight:600;')
        title.addWidget(heading, 1)
        refresh = QPushButton('↻')
        refresh.setAccessibleName('Atualizar contas')
        refresh.setFixedWidth(28)
        refresh.clicked.connect(self.refresh_requested)
        title.addWidget(refresh)
        outer.addLayout(title)
        body = QHBoxLayout()
        body.setSpacing(10)
        outer.addLayout(body, 1)
        side = QWidget()
        side.setFixedWidth(135)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(5)
        self.account_buttons = {}
        for item in self.items:
            key = item.get('account_id', '')
            label = item['label'] + (' · padrão' if item.get('default') else '')
            button = QPushButton()
            button.setAccessibleName(label)
            # Long labels remain available to accessibility and on hover.
            button.setText(button.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, 117))
            button.setToolTip(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, identity=key: self.select(identity))
            side_layout.addWidget(button)
            self.account_buttons[key] = button
        side_layout.addStretch()
        side_scroll = QScrollArea()
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFixedWidth(145)
        side_scroll.setWidget(side)
        body.addWidget(side_scroll)
        self.details = QWidget()
        self.content = QVBoxLayout(self.details)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(7)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.details)
        self.scroll = scroll
        body.addWidget(scroll, 1)
        actions = QHBoxLayout()
        open_button = QPushButton('Abrir cliente')
        open_button.clicked.connect(lambda: self.open_requested.emit(provider, self.selected))
        billing = QPushButton('Dia da assinatura…')
        billing.clicked.connect(lambda: self.billing_requested.emit(provider, self.selected))
        actions.addWidget(open_button)
        actions.addWidget(billing)
        outer.addLayout(actions)
        self.select(self.selected)

    def line(self, text, *, big=False, color=None, layout=None):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(f'color:{color or T.text};font-size:{18 if big else 9}pt;'
                           + ('font-weight:600;' if big else ''))
        (layout or self.content).addWidget(label)
        return label

    def update_items(self, items):
        # Keep the reading/scroll position stable between actual changes.
        now = time.time()
        validity = tuple((ai.effective(i, now),
                          0 <= now - (i.get('reset_credits') or {}).get('observed_at', 0) <= ai.MAX_AGE,
                          ((i.get('reset_credits') or {}).get('expires_at') or now + 1) > now)
                         for i in items)
        signature = (repr(items), validity, int(now // 60))
        if signature == self._signature: return
        self._signature = signature
        position = self.scroll.verticalScrollBar().value()
        self.items = items or self.items
        self.select(self.selected)
        self.scroll.verticalScrollBar().setValue(position)

    def select(self, identity):
        item = next((i for i in self.items if i.get('account_id', '') == identity), self.items[0])
        self.selected = item.get('account_id', '')
        for key, button in self.account_buttons.items():
            button.setChecked(key == self.selected)
        while self.content.count():
            child = self.content.takeAt(0).widget()
            if child: child.deleteLater()
        now = time.time()
        remaining = ai.effective(item, now)
        color = dict(green=T.ok, yellow=T.warning, red=T.danger, unknown=T.muted)[ai.band(remaining)]
        status = ('Cota não confirmada' if remaining is None else
                  'Cota quase no fim' if remaining <= 20 else 'Atenção ao consumo' if remaining <= 60 else 'Cota disponível')
        self.line(status, color=color)
        if remaining is not None:
            self.line(f'{100 - remaining}% usado', big=True, color=color)
            self.line(f'{remaining}% restante · janela mais restrita', color=T.muted)
        tickets = item.get('reset_credits') or {}
        expiry = tickets.get('expires_at')
        fresh = 0 <= now - tickets.get('observed_at', 0) <= ai.MAX_AGE and (not expiry or expiry > now)
        if tickets and fresh:
            self.line(f"Tickets de reset · {tickets['available']} disponíveis", color=T.accent if tickets['available'] else T.muted)
            if tickets['available']:
                self.line(('Valem até ' + date(expiry) if expiry else 'Validade não informada') + ' · resgate no cliente', color=T.muted)
        else:
            self.line('Tickets de reset · ' + ('consulta vencida' if tickets else 'não informados'), color=T.muted)
        day = item.get('billing_day')
        if day:
            next_date = ai.next_monthly(day, now)
            due = dt.datetime.strptime(next_date, '%d/%m/%Y').date()
            days = (due - dt.datetime.fromtimestamp(now).date()).days
            today = dt.datetime.fromtimestamp(now).day == min(day, calendar.monthrange(
                dt.datetime.fromtimestamp(now).year, dt.datetime.fromtimestamp(now).month)[1])
            self.line(f'Assinatura · dia {day}' + (' · hoje' if today else f' · em {days} dias' if days <= 7 else ''), color=T.warning if today or days <= 7 else T.text)
            self.line(('Estimativa' if 'estimativa' in item.get('billing_source', '') else 'Referência pessoal') + ' · ' + next_date + ' · confirme no provedor', color=T.muted)
        else:
            self.line('Assinatura · dia não informado', color=T.muted)
        if item.get('paid_until'):
            self.line('Assinatura até ' + date(item['paid_until']) + ' · metadado local', color=T.muted)
        for window in item.get('windows', []):
            card = QFrame()
            card.setStyleSheet(f'QFrame{{background:{T.surface_alt};border-radius:5px;}}')
            block = QVBoxLayout(card)
            block.setContentsMargins(8, 6, 8, 6)
            block.setSpacing(3)
            self.line(f"{window['name']} · {window['used']}% usado" + (' · anterior' if remaining is None else ''), layout=block)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(window['used'])
            progress.setTextVisible(False)
            progress.setStyleSheet(f'QProgressBar::chunk{{background:{color};}}')
            block.addWidget(progress)
            reset = window.get('resets_at')
            text = ('Repõe em ' + until(reset, now) + ' · ' + date(reset) if reset and reset > now
                    else 'Reset passou · atualizando' if reset else 'Reset não informado')
            self.line(text, color=T.muted, layout=block)
            self.content.addWidget(card)
        if not item.get('windows'):
            self.line('Sessão e semana: indisponíveis nesta fonte.', color=T.muted)
        if item.get('extra_credits') is not None:
            self.line('Saldo extra · ' + str(item['extra_credits']))
        extra = item.get('extra_usage')
        if extra:
            text = 'Uso extra · ' + ('habilitado' if extra['enabled'] else 'desabilitado')
            if 'utilization' in extra: text += f" · {extra['utilization']:g}% do limite mensal"
            self.line(text, color=T.muted)
            if 'used_credits' in extra and 'monthly_limit' in extra:
                self.line(f"Consumo {extra['used_credits']:g} / {extra['monthly_limit']:g} · unidades do provedor", color=T.muted)
        if item.get('plan'): self.line('Plano · ' + str(item['plan']), color=T.muted)
        if item.get('reason'): self.line(item['reason'], color=T.muted)
        if item.get('observed_at'): self.line('Consulta · ' + date(item['observed_at']), color=T.muted)
        if item.get('source'): self.line(item['source'], color=T.muted)
        self.content.addStretch()
