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
                web_tunnel=dict(state='ready', detail='Runtime local do túnel pronto'),
                web_inference='não comprovada; nenhum envio de teste foi realizado',
                local_usage=dict(counts={'gpt-6-pro': 2, 'gpt-5.6-pro': 1, 'pro-unknown': 0},
                                 since=time.time() - 3600),
                reason='Limite e reposição da conta ChatGPT não informados pelo WebGPT')
    panel = AccountPanel('web', [item])
    labels = '\n'.join(label.text() for label in panel.findChildren(QLabel))
    assert 'Serviço local · pronto' in labels and 'Runtime local do túnel · pronto' in labels
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
