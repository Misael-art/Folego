"""Interactive quota card: accounts at left, current allowance at right."""
import calendar
import datetime as dt
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
                              QScrollArea, QProgressBar, QFrame)

from ..core import ai_sessions as ai
from .theme import background, themed_style, TOKENS as T, paint_surface


def date(at):
    return dt.datetime.fromtimestamp(at).astimezone().strftime('%d/%m · %H:%M')


def until(at, now):
    seconds = max(0, int(at - now))
    days, hours = divmod(seconds // 3600, 24)
    return f'{days}d {hours}h' if days else f'{hours}h {seconds // 60 % 60:02}min'


class AccountPanel(QWidget):
    open_requested = Signal(str, str)
    billing_requested = Signal(str, str)
    reset_note_requested = Signal(str, str)
    limit_note_requested = Signal(str, str)
    refresh_requested = Signal()

    def __init__(self, provider, items, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.setObjectName('accountPanel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.items = items or [ai.unknown(provider)]
        self._signature = None
        self.selected = next((i.get('account_id', '') for i in self.items if i.get('default')), self.items[0].get('account_id', ''))
        themed_style(self, lambda: f'QWidget{{background:transparent;color:{T.text};}}'
                          f'QWidget#accountPanel{{background:{background(T.surface)};border:1px solid {T.border};border-radius:10px;}}'
                          f'QPushButton{{background:{background(T.surface_alt)};padding:5px;border:1px solid {T.border};border-radius:5px;}}'
                          f'QPushButton:checked{{background:{background(T.surface_alt)};border-color:{T.accent};}}'
                          f'QProgressBar{{border:none;background:{T.border};height:5px;max-height:5px;}}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        title = QHBoxLayout()
        heading = QLabel(ai.NAMES[provider] + (' · estado e uso local' if provider == 'web' else ' · uso e renovação'))
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
        if provider != 'web':
            note = QPushButton('Lembrete de reset…')
            note.setToolTip('Registrar um reset resgatável que o cliente mostra e a fonte não expõe')
            note.clicked.connect(lambda: self.reset_note_requested.emit(provider, self.selected))
            actions.addWidget(note)
        else:
            note = QPushButton('Lembrete de limite…')
            note.setToolTip('Registrar quando o ChatGPT informou que o limite volta')
            note.clicked.connect(lambda: self.limit_note_requested.emit(provider, self.selected))
            actions.addWidget(note)
        outer.addLayout(actions)
        self.select(self.selected)

    def paintEvent(self, event):
        paint_surface(self)
        super().paintEvent(event)

    def line(self, text, *, big=False, color=None, layout=None):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        themed_style(label, lambda: f'color:{getattr(T, color or "text")};font-size:{18 if big else 9}pt;'
                           + ('font-weight:600;' if big else ''))
        (layout or self.content).addWidget(label)
        return label

    def update_items(self, items):
        # Keep the reading/scroll position stable between actual changes.
        now = time.time()
        validity = tuple((ai.effective(i, now), ai.available_resets(i, now))
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
        if self.provider == 'web':
            self._select_web(item)
            return
        now = time.time()
        remaining = ai.effective(item, now)
        color = dict(green='ok', yellow='warning', red='danger', unknown='muted')[ai.band(remaining)]
        status = ('Cota não confirmada' if remaining is None else
                  'Cota quase no fim' if remaining <= 20 else 'Atenção ao consumo' if remaining <= 60 else 'Cota disponível')
        self.line(status, color=color)
        if remaining is not None:
            self.line(f'{100 - remaining}% usado', big=True, color=color)
            self.line(f'{remaining}% restante · janela mais restrita', color='muted')
        for pace in ai.pace_forecast(item, now):
            self.line(f"Nesse ritmo, {pace['name']} esgota por volta de {date(pace['at'])} · estimativa local", color='warning')
        tickets = item.get('reset_credits') or {}
        expiry = tickets.get('expires_at')
        available = ai.available_resets(item, now)
        if available is not None:
            self.line(f"Tickets de reset · {available} disponíveis", color='ok' if available else 'muted')
            if available:
                self.line(('Valem até ' + date(expiry) if expiry else 'Validade não informada') + (' · lembrete seu; confirme e resgate no cliente' if tickets.get('declared') else ' · resgate no cliente'), color='muted')
        else:
            self.line('Tickets de reset · ' + ('consulta vencida' if tickets else 'não informados'), color='muted')
        day = item.get('billing_day')
        if day:
            next_date = ai.next_monthly(day, now)
            due = dt.datetime.strptime(next_date, '%d/%m/%Y').date()
            days = (due - dt.datetime.fromtimestamp(now).date()).days
            today = dt.datetime.fromtimestamp(now).day == min(day, calendar.monthrange(
                dt.datetime.fromtimestamp(now).year, dt.datetime.fromtimestamp(now).month)[1])
            self.line(f'Assinatura · dia {day}' + (' · hoje' if today else f' · em {days} dias' if days <= 7 else ''), color='warning' if today or days <= 7 else 'text')
            self.line(('Estimativa' if 'estimativa' in item.get('billing_source', '') else 'Referência pessoal') + ' · ' + next_date + ' · confirme no provedor', color='muted')
        else:
            self.line('Assinatura · dia não informado', color='muted')
        if item.get('paid_until'):
            self.line('Assinatura até ' + date(item['paid_until']) + ' · metadado local', color='muted')
        for window in item.get('windows', []):
            card = QFrame()
            card.setObjectName('quotaWindow')
            themed_style(card, lambda: f'QFrame#quotaWindow{{background:{background(T.surface_alt)};border-radius:5px;}}')
            block = QVBoxLayout(card)
            block.setContentsMargins(8, 6, 8, 6)
            block.setSpacing(3)
            self.line(f"{window['name']} · {window['used']}% usado" + (' · anterior' if remaining is None else ''), layout=block)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(window['used'])
            progress.setTextVisible(False)
            themed_style(progress, lambda: f'QProgressBar::chunk{{background:{getattr(T, color)};}}')
            block.addWidget(progress)
            reset = window.get('resets_at')
            text = ('Repõe em ' + until(reset, now) + ' · ' + date(reset) if reset and reset > now
                    else 'Reset passou · atualizando' if reset else 'Reset não informado')
            self.line(text, color='muted', layout=block)
            self.content.addWidget(card)
        if not item.get('windows'):
            self.line('Sessão e semana: indisponíveis nesta fonte.', color='muted')
        if item.get('extra_credits') is not None:
            self.line('Saldo extra · ' + str(item['extra_credits']))
        extra = item.get('extra_usage')
        if extra:
            text = 'Uso extra · ' + ('habilitado' if extra['enabled'] else 'desabilitado')
            if 'utilization' in extra: text += f" · {extra['utilization']:g}% do limite mensal"
            self.line(text, color='muted')
            if 'used_credits' in extra and 'monthly_limit' in extra:
                self.line(f"Consumo {extra['used_credits']:g} / {extra['monthly_limit']:g} · unidades do provedor", color='muted')
        spend = item.get('usage_credits')
        if spend:
            self.line('Créditos de uso · ' + ('habilitados' if spend['enabled'] else 'desabilitados')
                      + (' · consumo ' + spend['used'] if 'used' in spend else '')
                      + (' · saldo ' + spend['balance'] if 'balance' in spend else ''), color='muted')
        if item.get('plan'): self.line('Plano · ' + str(item['plan']), color='muted')
        if item.get('reason'): self.line(item['reason'], color='muted')
        if item.get('observed_at'): self.line('Consulta · ' + date(item['observed_at']), color='muted')
        if item.get('source'): self.line(item['source'], color='muted')
        self.content.addStretch()

    def _select_web(self, item):
        instances = ai.web_instances(item)
        self.line('Instâncias Codex Web · ' + ('não verificadas' if instances is None else str(instances)),
                  color='ok' if instances else 'muted')
        self.line('Instância aberta não confirma um turno em execução', color='muted')
        service = item.get('web_service') or {}
        tunnel = item.get('web_tunnel') or {}
        for title, state in (('Serviço local', service), ('Runtime local do túnel', tunnel)):
            code = state.get('state', 'unknown')
            color = 'ok' if code == 'ready' else 'danger' if code == 'unavailable' else 'muted'
            self.line(title + ' · ' + {'ready': 'pronto', 'unavailable': 'indisponível',
                                     'not_required': 'não exigido', 'unknown': 'desconhecido'}.get(code, 'desconhecido'),
                      color=color)
            if state.get('detail'):
                self.line(str(state['detail']), color='muted')
            if state.get('checked_at'):
                self.line('Verificado em ' + date(state['checked_at'])
                          + (' · sondagem a cada 5 min' if title == 'Runtime local do túnel' else ''), color='muted')
        if service.get('catalog_status') == 200:
            self.line('Catálogo de modelos · última consulta local bem-sucedida', color='muted')
        self.line('Resposta do ChatGPT Web · ' + item.get('web_inference', 'não comprovada'), color='muted')
        until = item.get('declared_limit_until')
        if until:
            waiting = until > time.time()
            self.line(('Limite esgotado até ' if waiting else 'Prazo do limite passou em ') + date(until)
                      + ' · lembrete seu', color='warning' if waiting else 'muted')
        recovery = item.get('web_recovery')
        if recovery:
            for line in ai.web_recovery_lines(recovery):
                self.line(line, color='muted')
        self.line('Limite da sessão/conta · não informado pelo WebGPT', big=True, color='muted')
        self.line('Saldo disponível e horário de reposição · desconhecidos', color='muted')
        usage = item.get('local_usage')
        if usage:
            counts = usage['counts']
            total = sum(counts.values())
            self.line(f'Envios registrados no launcher · {total} nos últimos 7 dias', color='text')
            self.line('GPT-6 Pro: ' + str(counts['gpt-6-pro']) + ' · GPT-5.6 Pro: '
                      + str(counts['gpt-5.6-pro']) + ' · modelo não identificado: '
                      + str(counts['pro-unknown']), color='muted')
            self.line('Rastreamento iniciado em ' + date(usage['since'])
                      + ' · só envios deste launcher; registro parcial', color='muted')
        if item.get('plan'):
            self.line('Plano no último registro · ' + str(item['plan']), color='muted')
        if item.get('limits_checked_at'):
            self.line('Plano verificado localmente em ' + date(item['limits_checked_at']), color='muted')
        if item.get('reason'):
            self.line(item['reason'], color='muted')
        self.content.addStretch()
