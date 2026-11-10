"""Quota indicators, new completed sessions and verified application opening."""
import time

from PySide6.QtCore import Qt, QTimer, QUrl, QEvent, QPoint, QSize, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QDesktopServices, QPen
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
                              QMenu, QInputDialog, QWidgetAction, QGraphicsOpacityEffect, QStyle)

from ..core import ai_sessions
from .theme import themed_style, TOKENS, on_theme_change
from .palettes import on_color
from .desktop_shortcuts import DesktopController
from .ai_monitor import AIMonitor
from ..adapters.agent_apps import AgentApps
from .ai_account_panel import AccountPanel
from .ai_quota_button import QuotaButton


def gift_icon():
    """Code-native gift; no platform emoji/font or icon-theme dependency."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(on_color(TOKENS.ok)), 1.8))
    painter.drawRoundedRect(QRectF(4, 12, 16, 9), 1, 1)
    painter.drawRoundedRect(QRectF(2, 8, 20, 5), 1, 1)
    painter.drawLine(12, 8, 12, 21)
    painter.drawEllipse(QRectF(5, 2, 7, 6))
    painter.drawEllipse(QRectF(12, 2, 7, 6))
    painter.end()
    return QIcon(pixmap)


def available_account(items, now):
    """Choose a confirmed usable account, preferring the default when usable."""
    usable = [(ai_sessions.effective(item, now), item) for item in items]
    usable = [(left, item) for left, item in usable if left is not None and left > 0]
    if not usable:
        return None, None
    default = next(((left, item) for left, item in usable if item.get('default')), None)
    return default or max(usable, key=lambda pair: (pair[0], pair[1].get('account_id') or ''))


class AIStrip(QWidget):
    def __init__(self, parent=None, *, collect_fn=None, deliveries=None, opener=None, monitor=None):
        super().__init__(parent)
        self.monitor = monitor or AIMonitor(self, collect_fn=collect_fn, deliveries=deliveries)
        self._owns_monitor = monitor is None
        self.items = self.monitor.items
        self.account_menu = None
        self.account_panel = None
        self.buttons = {}
        self.columns = {}
        self.display_accounts = {}
        self.visible_providers = set()
        self.arrival_animations = {}
        self.badges = {}
        self.badge_rows = {}
        self.reset_badges = {}
        self._reset_bright = True
        self.reset_blink = QTimer(self)
        self.reset_blink.setInterval(800)
        self.reset_blink.timeout.connect(self._blink_resets)
        self.delivery_pulse = QVariantAnimation(self)
        self.delivery_pulse.setDuration(1800)
        self.delivery_pulse.setStartValue(0.0)
        self.delivery_pulse.setKeyValueAt(.5, 1.0)
        self.delivery_pulse.setEndValue(0.0)
        self.delivery_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.delivery_pulse.setLoopCount(-1)
        self.delivery_pulse.valueChanged.connect(self._pulse_deliveries)
        self.deliveries = self.monitor.deliveries
        self.delivery_items = self.monitor.delivery_items
        self.opener = opener or DesktopController(self, backend=AgentApps(self.deliveries))
        self.opener.result.connect(self._opened)
        self.opener.feedback.connect(self._notice)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for provider, label in ai_sessions.NAMES.items():
            button = QuotaButton(provider, label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": cota desconhecida")
            button.installEventFilter(self)
            button.clicked.connect(lambda checked=False, p=provider: self.open_agent(
                p, self.display_accounts.get(p)))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point, p=provider: self.options(p, point))
            self.buttons[provider] = button
            column_widget = QWidget()
            column = QVBoxLayout(column_widget)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            badge_row = QWidget()
            badge_row.setFixedHeight(14)
            badge_row.setStyleSheet('background:transparent;')
            self.badge_rows[provider] = badge_row
            badge_layout = QHBoxLayout(badge_row)
            badge_layout.setContentsMargins(0, 0, 0, 0)
            badge_layout.setSpacing(2)
            badge = QLabel()
            badge.setFixedSize(30, 14)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            badge_layout.addWidget(badge)
            reset_badge = QPushButton()
            reset_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            reset_badge.setCursor(Qt.CursorShape.PointingHandCursor)
            reset_badge.setFixedSize(30, 14)
            reset_badge.setIcon(gift_icon())
            reset_badge.setIconSize(QSize(11, 11))
            themed_style(reset_badge, lambda: f'background:{TOKENS.ok};color:{on_color(TOKENS.ok)};'
                                      'padding:0;border:none;min-height:0;max-height:14px;'
                                      'border-radius:6px;font-size:8pt;font-weight:600;')
            reset_badge.setGraphicsEffect(QGraphicsOpacityEffect(reset_badge))
            reset_badge.clicked.connect(lambda checked=False, p=provider: self.reset_details(p))
            reset_badge.hide()
            badge_layout.addWidget(reset_badge)
            self.badges[provider] = badge
            self.reset_badges[provider] = reset_badge
            column.addWidget(button)
            column.addWidget(badge_row, 0, Qt.AlignmentFlag.AlignHCenter)
            arrival = QVariantAnimation(self)
            arrival.setDuration(220)
            arrival.setEasingCurve(QEasingCurve.Type.OutCubic)
            arrival.setStartValue(0.0)
            arrival.setEndValue(1.0)
            arrival.valueChanged.connect(lambda value, p=provider: self._arrival_frame(p, value))
            arrival.finished.connect(lambda p=provider: self._finish_arrival(p))
            self.arrival_animations[provider] = arrival
            self.columns[provider] = column_widget
            layout.addWidget(column_widget, 1)
        self.empty_label = QLabel('Sem cotas disponíveis confirmadas')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAccessibleName('Nenhuma cota disponível confirmada; consulte contas e cotas nos controles')
        layout.addWidget(self.empty_label, 1)
        self.monitor.deliveries_ready.connect(self.set_deliveries)
        self.monitor.quotas_ready.connect(self.set_items)
        self.freshness = QTimer(self)
        self.freshness.setInterval(1000)
        self.freshness.timeout.connect(self.render)
        on_theme_change(self, self.render)
        self.render()

    def _arrival_frame(self, provider, value):
        effect = self.columns[provider].graphicsEffect()
        if effect is not None:
            effect.setOpacity(value)

    def _finish_arrival(self, provider):
        column = self.columns[provider]
        if column.graphicsEffect() is not None:
            column.setGraphicsEffect(None)

    @property
    def poller(self): return self.monitor.poller

    @property
    def delivery_poller(self): return self.monitor.delivery_poller

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

    def reset_details(self, provider):
        # Prefer the default account, but let a gift from another account lead
        # to that account. Ordinary provider hover still starts at the default.
        items = [i for i in self.items if i.get('provider') == provider
                 and (ai_sessions.available_resets(i) or 0) > 0]
        if not items: return
        item = next((i for i in items if i.get('default')), items[0])
        self.details(provider)
        self.account_panel.select(item.get('account_id', ''))

    def _blink_resets(self):
        self._reset_bright = not self._reset_bright
        self._paint_reset_phase()

    def _paint_reset_phase(self):
        for badge in self.reset_badges.values():
            badge.graphicsEffect().setOpacity(1.0 if self._reset_bright else .5)

    def _pulse_deliveries(self, value):
        # The animation ticks at the display rate; repainting the ring icon on
        # every tick kept the GUI thread busy, so redraw only on 1/8 steps and
        # not at all while the window is minimized.
        if value and self.window().isMinimized(): return
        value = round(value * 8) / 8
        for provider, button in self.buttons.items():
            count = next((r.get('count') for r in self.delivery_items if r['provider'] == provider), None)
            active_web = provider == 'web' and button.instance_active
            button.set_halo(value if (count or active_web) and self.columns[provider].isVisible() else 0.0)

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
        menu = self.options_menu(provider)
        menu.exec(button.mapToGlobal(point))
        menu.deleteLater()

    def options_menu(self, provider):
        menu = QMenu(self.buttons[provider])
        menu.addAction('Atualizar dados', self.refresh)
        menu.addAction('Contas, uso e renovação…', lambda: QTimer.singleShot(0, lambda: self.details(provider)))
        menu.addAction('Definir dia da renovação mensal…', lambda: self.billing(provider))
        urls = {'codex': 'https://chatgpt.com/codex/settings/usage',
                'web': 'https://chatgpt.com/#settings/Account',
                'claude': 'https://claude.ai/settings/usage', 'grok': 'https://grok.com/usage'}
        menu.addAction('Consultar no site do provedor', lambda: QDesktopServices.openUrl(QUrl(urls[provider])))
        if provider == 'web':
            # The launcher has no deep link or external API; the plan check stays a user click there.
            menu.addAction('Abrir Limits no Codex Web', lambda: self.open_agent('web'))
        return menu

    def details(self, provider, anchor=None):
        if self.account_menu is not None:
            self.account_menu.close()
        button = self.buttons[provider]
        anchor = anchor or button
        menu = QMenu(anchor)
        panel = AccountPanel(provider, [i for i in self.items if i['provider'] == provider])
        if self.display_accounts.get(provider):
            panel.select(self.display_accounts[provider])
        menu.setObjectName('accountPopup')
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet('QMenu#accountPopup{background:transparent;border:none;padding:0;}')
        area = anchor.screen().availableGeometry()
        panel.setFixedSize(min(560, area.width() - 20), min(470, area.height() - 24))
        panel.open_requested.connect(lambda p, a: (menu.close(), self.open_agent(p, a)))
        panel.billing_requested.connect(lambda p, a: (menu.close(), self.billing(p, a)))
        panel.reset_note_requested.connect(lambda p, a: (menu.close(), self.reset_note(p, a)))
        panel.refresh_requested.connect(self.refresh)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        self.account_menu, self.account_panel = menu, panel
        menu.aboutToHide.connect(lambda: self._panel_hidden(menu))
        point = anchor.mapToGlobal(QPoint(0, anchor.height()))
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

    def reset_note(self, provider, account=None):
        item = next((i for i in self.items if account and i.get('account_id') == account), self.default_item(provider))
        account = item.get('account_id')
        if not account: return self._notice('Conta não identificada; lembrete não registrado')
        current = item.get('reset_credits') or {}
        text, accepted = QInputDialog.getText(self, 'Lembrete de reset · ' + ai_sessions.NAMES[provider],
            'Validade do reset mostrado pelo cliente (DD/MM/AAAA HH:MM; vazio remove).\n'
            'Lembrete pessoal: o Fôlego não consulta nem resgata o reset.',
            text=ai_sessions.stamp(current['expires_at']) if current.get('declared') and current.get('expires_at') else '')
        if not accepted: return
        try:
            expiry = ai_sessions.parse_local_time(text) if text.strip() else None
        except ValueError as exc:
            return self._notice(str(exc))
        self.opener.request('agent-reset-note', (account, expiry))

    def _notice(self, message):
        # The compact card owns visible transient feedback, separate from alerts.
        parent = self.window()
        show = getattr(parent, '_shortcut_result', None)
        if show: show(message)

    def render(self):
        now = time.time()
        has_resets = False
        has_deliveries = False
        available = []
        for provider, button in self.buttons.items():
            items = [item for item in self.items if item.get("provider") == provider]
            left, selected = available_account(items, now)
            instances = None
            if provider == 'web':
                live = [(ai_sessions.web_instances(item, now), item) for item in items]
                live = [(count, item) for count, item in live if count is not None and count > 0]
                if live:
                    instances, selected = max(live, key=lambda pair: (pair[0], pair[1].get('default', False)))
                    left = None
                else:
                    selected = None
            self.display_accounts[provider] = selected.get('account_id') if selected else None
            if selected is not None:
                available.append((provider, left if left is not None else -1))
            button.set_instance_active(provider == 'web' and instances is not None)
            button.set_remaining(None if provider == 'web' else
                                 left if selected else ai_sessions.effective(self.default_item(provider), now))
            summary = (f'{instances} instância(s) aberta(s) · {selected.get("label", "conta")}; cota não informada'
                       if provider == 'web' and instances is not None else
                       f'{left}% disponível · {selected.get("label", "conta")}' if selected else
                       '0% disponível' if button.remaining == 0 else 'cota desconhecida ou vencida')
            delivery = next((r for r in self.delivery_items if r['provider'] == provider), {})
            count = delivery.get('count')
            web_mcp_report = provider == 'web' and any(
                receipt.get('reported_web_mcp_error') for receipt in delivery.get('pending', ()))
            web_capacity_error = provider == 'web' and any(
                receipt.get('web_capacity_error') for receipt in delivery.get('pending', ()))
            if web_mcp_report:
                summary += ' · agente relatou sessão MCP encerrada'
            if web_capacity_error:
                summary += ' · erro de capacidade; confira a recuperação no painel da conta'
            has_deliveries |= (bool(count) or instances is not None) and selected is not None
            if not count and instances is None: button.set_halo(0.0)
            badge = self.badges[provider]
            partial = not delivery.get('complete', True)
            number = str(count) + ('+' if partial else '')
            badge_text = '?' if count is None else number if count else ''
            web_error = web_mcp_report or web_capacity_error
            if web_error and count: badge_text += '!'
            badge.setText(badge_text)
            background = TOKENS.danger if web_error else TOKENS.accent if count else TOKENS.muted if count is None else TOKENS.surface
            badge.setStyleSheet(f"background:{TOKENS.danger if web_error else TOKENS.accent if count else TOKENS.muted if count is None else 'transparent'};"
                               f"color:{on_color(background)};font-size:8pt;font-weight:600;border-radius:6px;")
            completed = 'conclusões não verificadas' if count is None else f'{count} novas entregas para revisitar'
            if count and partial: completed = 'Pelo menos ' + completed + '; outras sessões não verificadas'
            badge.setToolTip('Codex Web retornou erro de capacidade; confira a recuperação no painel da conta.'
                             if web_capacity_error else
                             'O agente relatou sessão MCP encerrada; abra o Codex Web para conferir.'
                             if web_mcp_report else completed)
            confirmed = [(i, ai_sessions.available_resets(i)) for i in items]
            offers = [(i, n) for i, n in confirmed if n is not None and n > 0]
            total = sum(n for _, n in offers)
            reset_badge = self.reset_badges[provider]
            reset_badge.setIcon(gift_icon())
            reset_badge.setVisible(total > 0)
            self.badge_rows[provider].setVisible(bool(count) or total > 0)
            reset_badge.setText(str(total) if total <= 9 else '9+')
            resets = f'{total} redefinições disponíveis confirmadas'
            reset_badge.setAccessibleName(ai_sessions.NAMES[provider] + ': ' + resets)
            detail = [resets] + [f"{i['label']}: {n}" for i, n in offers]
            if any(n is None for _, n in confirmed): detail.append('Outras contas sem confirmação atual')
            detail.append('Clique para ver a conta · resgate no cliente')
            reset_badge.setToolTip('\n'.join(detail))
            has_resets |= total > 0 and selected is not None
            button.setAccessibleName(ai_sessions.NAMES[provider] + ": " + summary + ' · ' + completed
                                     + (' · ' + resets if total else ''))
            button.setToolTip(('Instância Codex Web aberta; não confirma turno ativo nem limite · '
                               if provider == 'web' else 'Uso e renovação por conta · ')
                              + 'clique para abrir o cliente da conta exibida')
        order = {provider: index for index, provider in enumerate(ai_sessions.NAMES)}
        available.sort(key=lambda pair: (-pair[1], order[pair[0]]))
        self.empty_label.setVisible(not available)
        for index, (provider, _) in enumerate(available):
            column = self.columns[provider]
            was_visible = provider in self.visible_providers
            if self.layout().indexOf(column) != index:
                self.layout().insertWidget(index, column, 1)
            column.show()
            if not was_visible and self.isVisible():
                duration = self.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration, None, self)
                if self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, self) and duration > 0:
                    animation = self.arrival_animations[provider]
                    animation.stop()
                    animation.setDuration(min(220, duration))
                    effect = QGraphicsOpacityEffect(column)
                    effect.setOpacity(0.0)
                    column.setGraphicsEffect(effect)
                    animation.start()
        visible = {p for p, _ in available}
        for provider in self.buttons:
            if provider not in visible:
                self.arrival_animations[provider].stop()
                self._finish_arrival(provider)
                self.columns[provider].hide()
        self.visible_providers = visible
        if has_deliveries and self.isVisible():
            if self.delivery_pulse.state() != QVariantAnimation.State.Running:
                self.delivery_pulse.start()
        else:
            self.delivery_pulse.stop()
            self._pulse_deliveries(0.0)
        if has_resets and self.isVisible():
            if not self.reset_blink.isActive():
                self._reset_bright = True
                self._paint_reset_phase()
                self.reset_blink.start()
        else:
            self.reset_blink.stop()
            self._reset_bright = True
            self._paint_reset_phase()
        if self.account_panel is not None:
            panel = self.account_panel
            items = [i for i in self.items if i['provider'] == panel.provider]
            if {i.get('account_id', '') for i in items} == set(panel.account_buttons):
                panel.update_items(items)
            else:
                self.account_menu.close()

    def showEvent(self, event):
        super().showEvent(event)
        if self._owns_monitor: self.monitor.start()
        self.freshness.start()
        self.render()
        self.refresh()
        self.delivery_poller.request()

    def hideEvent(self, event):
        if self.account_menu is not None: self.account_menu.close()
        if self._owns_monitor: self.monitor.pause()
        self.freshness.stop()
        self.reset_blink.stop()
        self.delivery_pulse.stop()
        for provider, animation in self.arrival_animations.items():
            animation.stop()
            self._finish_arrival(provider)
        super().hideEvent(event)

    def shutdown(self):
        if self.account_menu is not None: self.account_menu.close()
        self.freshness.stop()
        self.reset_blink.stop()
        self.delivery_pulse.stop()
        for animation in self.arrival_animations.values(): animation.stop()
        for button in self.buttons.values(): button.transition.stop()
        if self._owns_monitor: self.monitor.shutdown()
        self.opener.close()
