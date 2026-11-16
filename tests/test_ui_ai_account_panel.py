import time

from PySide6.QtWidgets import QLabel

from folego.core import ai_sessions as ai
from folego.ui.ai_account_panel import AccountPanel
from folego.ui.ai_strip import AIStrip
from folego.ui.desktop_shortcuts import DesktopController, ShortcutTabs
from folego.core.development_prompts import PROMPTS, text


def items():
    now = time.time()
    rows = []
    for key, used in (('other', 95), ('principal', 10)):
        item = ai.unknown('codex', label=key)
        item.update(account_id=key, default=key == 'principal', observed_at=now,
                    windows=[ai.quota_window('Sessão (5 h)', used, now + 3600, now)])
        rows.append(item)
    return rows


def test_default_account_and_other_account_have_independent_readable_cards(qapp):
    panel = AccountPanel('codex', items())
    assert panel.selected == 'principal'
    assert any(w.text() == '10% usado' for w in panel.findChildren(QLabel))
    panel.account_buttons['other'].click()
    qapp.processEvents()
    assert panel.selected == 'other'
    assert any(w.text() == '95% usado' for w in panel.findChildren(QLabel))
    assert any(w.text() == 'Cota quase no fim' for w in panel.findChildren(QLabel))
    panel.close()


def test_web_card_separates_local_readiness_from_unknown_account_allowance(qapp):
    item = ai.unknown('web', label='Web instalado')
    item.update(account_id='web', default=True,
                web_service=dict(state='ready', detail='Serviço local aceita solicitações', catalog_status=200),
                web_tunnel=dict(state='ready', detail='Runtime local do túnel pronto', checked_at=time.time()),
                web_inference='não comprovada; nenhum envio de teste foi realizado',
                local_usage=dict(counts={'gpt-6-pro': 2, 'gpt-5.6-pro': 1, 'pro-unknown': 0},
                                 since=time.time() - 3600),
                reason='Limite e reposição da conta ChatGPT não informados pelo WebGPT')
    panel = AccountPanel('web', [item])
    labels = '\n'.join(label.text() for label in panel.findChildren(QLabel))
    assert 'Serviço local · pronto' in labels and 'Runtime local do túnel · pronto' in labels
    assert 'sondagem a cada 5 min' in labels
    assert 'Resposta do ChatGPT Web · não comprovada' in labels
    assert 'Saldo disponível e horário de reposição · desconhecidos' in labels
    assert 'Envios registrados no launcher · 3 nos últimos 7 dias' in labels
    assert '%' not in labels and 'Cota disponível' not in labels
    panel.close()


def test_meter_describes_default_without_aggregating_other_accounts(qapp):
    strip = AIStrip(collect_fn=lambda: [])
    strip.set_items(items())
    assert '90% disponível' in strip.buttons['codex'].accessibleName()
    strip.shutdown()


def test_web_login_diagnosis_is_actionable_even_when_local_service_is_ready(qapp):
    item = ai.unknown('web')
    item.update(account_id='web', web_service=dict(state='ready'),
                web_recovery=dict(state='login-required', detail='Renove o login no ChatGPT dentro do launcher desta conta'))
    panel = AccountPanel('web', [item])
    labels = '\n'.join(w.text() for w in panel.findChildren(QLabel))
    assert 'Renove o login' in labels and 'Serviço local · pronto' in labels
    assert 'Saldo disponível e horário de reposição · desconhecidos' in labels
    panel.close()


def test_web_accounts_show_independent_connector_and_turn_states(qapp, tmp_path):
    import json

    from folego.core import web_gpt

    now = time.time()
    rows = []
    for account, state in (('principal', 'deferred'), ('outra', 'verified')):
        root = tmp_path / account
        root.mkdir()
        busy = state == 'deferred'
        receipt = dict(schemaVersion=1, observedAt=now - 8, state='waiting-for-idle' if busy else 'ready',
                       observation=dict(busy=busy, launcherSetupIncomplete=busy),
                       connectorVerification=dict(state=state, at=now - 5))
        (root / 'recovery-state.json').write_text(json.dumps(receipt))
        rows.append(dict(provider='web', account_id=account, label=account, default=busy,
                         **web_gpt.observe(root / 'core-home', root / 'launcher-data', now=now)))

    def visible_lines(panel):
        return '\n'.join(panel.content.itemAt(i).widget().text() for i in range(panel.content.count())
                         if isinstance(panel.content.itemAt(i).widget(), QLabel))

    panel = AccountPanel('web', rows)
    principal = visible_lines(panel)
    assert 'Tarefa em andamento' in principal and 'Verificação adiada' in principal
    assert 'Último diagnóstico há menos de 1 min' in principal and 'Conector verificado' not in principal
    panel.account_buttons['outra'].click()
    other = visible_lines(panel)
    assert 'Conector verificado' in other and 'Verificação adiada' not in other
    assert 'Resposta do ChatGPT Web · não comprovada' in other
    panel.close()


def test_opening_selected_account_only_sends_its_delivery_receipts(qapp):
    from PySide6.QtCore import QObject, Signal
    class Opener(QObject):
        result = Signal(str)
        feedback = Signal(str)
        def __init__(self): super().__init__(); self.requests = []
        def request(self, *args): self.requests.append(args)
        def close(self): pass
    opener = Opener()
    strip = AIStrip(collect_fn=lambda: [], opener=opener)
    strip.set_items(items())
    principal, other = dict(account_id='principal', event='a'), dict(account_id='other', event='b')
    strip.set_deliveries([dict(provider='codex', count=2, pending=[principal, other])])
    strip.open_agent('codex', 'other')
    assert opener.requests[-1] == ('agent-open', ('codex', [other], 'other'))
    strip.open_agent('codex')
    assert opener.requests[-1] == ('agent-open', ('codex', [principal], 'principal'))
    strip.shutdown()


def test_prompt_choice_only_copies_selected_portable_text(qapp, monkeypatch):
    class Clipboard:
        copied = None
        def setText(self, value): self.copied = value
    class Backend:
        def perform(self, *args): raise AssertionError('prompt triggered a native action')
        def close(self): pass
    clipboard = Clipboard()
    monkeypatch.setattr('folego.ui.desktop_shortcuts.QGuiApplication.clipboard', lambda: clipboard)
    controller = DesktopController(backend=Backend())
    tabs = ShortcutTabs(controller=controller)
    tabs.copy_prompt('continue')
    assert clipboard.copied == text('continue')
    assert '/home/' not in clipboard.copied and 'passagem' in clipboard.copied
    assert len({p.key for p in PROMPTS}) == len(PROMPTS) >= 10
    assert all(len(text(p.key)) > 600 for p in PROMPTS)
    assert controller.future is None
    tabs.shutdown()


def test_declared_reset_reminder_is_labelled_and_requested_per_account(qapp):
    from PySide6.QtWidgets import QPushButton
    rows = items()
    rows[1]['reset_credits'] = dict(available=1, expires_at=time.time() + 3600,
                                    observed_at=time.time(), declared=True)
    panel = AccountPanel('codex', rows)
    labels = '\n'.join(label.text() for label in panel.findChildren(QLabel))
    assert 'Tickets de reset · 1 disponíveis' in labels and 'lembrete seu' in labels
    requested = []
    panel.reset_note_requested.connect(lambda provider, account: requested.append((provider, account)))
    next(b for b in panel.findChildren(QPushButton) if b.text() == 'Lembrete de reset…').click()
    assert requested == [('codex', 'principal')]
    panel.close()
