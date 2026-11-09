"""Mini uses the shared monitor: confirmed quotas, reminders and short reset only."""
import time
from types import SimpleNamespace

import pytest

pytest.importorskip('PySide6')
from PySide6.QtTest import QSignalSpy

from folego.core import ai_sessions as ai
from folego.ui.ai_monitor import AIMonitor
from folego.ui.mini_ai_strip import MiniAIStrip


def quota(provider, left, now, *, account='main', minutes=300, reset=600, default=False):
    item = ai.unknown(provider)
    item.update(observed_at=now, account_id=account, default=default,
                windows=[ai.quota_window('Sessão', 100 - left, now + reset, now, minutes)])
    return item


def test_shared_monitor_updates_sorted_cells_and_opens_selected_account(qapp):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    strip = MiniAIStrip(monitor)
    strip.show()
    spy = QSignalSpy(strip.details_requested)
    monitor.set_items([quota('codex', 32, now), quota('claude', 80, now),
                       quota('grok', 0, now, minutes=10080), ai.unknown('web')])
    assert not strip.buttons['codex'].isHidden()
    assert not strip.buttons['claude'].isHidden()
    assert strip.buttons['grok'].isHidden() and strip.buttons['web'].isHidden()
    assert strip.layout().indexOf(strip.buttons['claude']) < strip.layout().indexOf(strip.buttons['codex'])
    monitor.set_items([quota('codex', 90, now, account='other'),
                       quota('codex', 20, now, default=True), quota('claude', 0, now)])
    strip.buttons['codex'].click()
    assert spy.at(0)[:2] == ['codex', 'main']
    assert strip.values['codex'].text() == '20%'
    assert strip.values['claude'].text() == 'Reset 10 min'
    assert strip.values['claude'].property('level') == 'danger'
    strip.hide()
    assert not strip.freshness.isActive()
    strip.close()


def test_reset_expiry_never_invents_new_allowance_and_weekly_never_counts_down(qapp, monkeypatch):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    monitor.set_items([quota('claude', 0, now), quota('grok', 0, now, minutes=10080)])
    strip = MiniAIStrip(monitor)
    assert strip.values['claude'].text() == 'Reset 10 min'
    assert strip.buttons['grok'].isHidden()
    monkeypatch.setattr('folego.ui.mini_ai_strip.time.time', lambda: now + 601)
    strip.refresh()
    assert strip.buttons['claude'].isHidden()
    assert strip.values['claude'].text() == '—'
    monitor.set_items([quota('claude', 72, now + 601)])
    assert not strip.buttons['claude'].isHidden() and strip.values['claude'].text() == '72%'
    strip.close()


def test_delivery_and_reset_badges_survive_unknown_quota_without_inventing_counts(qapp, monkeypatch):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    item = ai.unknown('codex')
    item['reset_credits'] = dict(available=2, observed_at=now, expires_at=now + 20)
    monitor.set_items([item])
    monitor.set_deliveries([dict(provider='codex', count=27, complete=False),
                            dict(provider='web', count=None, complete=False)])
    strip = MiniAIStrip(monitor)
    assert strip.values['codex'].text() == 'Entregas'
    assert strip.badges['codex'].text() == '19+'
    assert strip.resets['codex'].text() == '2' and not strip.resets['codex'].isHidden()
    assert 'Pelo menos 27 entregas' in strip.buttons['codex'].toolTip()
    assert strip.buttons['web'].isHidden()
    monkeypatch.setattr('folego.ui.mini_ai_strip.time.time', lambda: now + 21)
    strip.refresh()
    assert strip.resets['codex'].isHidden()
    assert not strip.badges['codex'].isHidden()
    assert 'Resets disponíveis não verificados' in strip.buttons['codex'].toolTip()
    strip.close()


def test_grok_switches_between_delivery_quota_and_hidden(qapp):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    strip = MiniAIStrip(monitor)
    monitor.set_items([quota('grok', 0, now, minutes=10080)])
    assert strip.buttons['grok'].isHidden()

    monitor.set_deliveries([dict(provider='grok', count=2)])
    assert not strip.buttons['grok'].isHidden()
    assert strip.values['grok'].text() == 'Entregas' and strip.badges['grok'].text() == '2'
    assert '0% de cota disponível' in strip.buttons['grok'].toolTip()

    monitor.set_items([quota('grok', 53, now, minutes=10080)])
    assert strip.values['grok'].text() == '53%' and strip.badges['grok'].text() == '2'

    monitor.set_items([ai.unknown('grok')])
    assert strip.values['grok'].text() == 'Entregas'
    assert 'Cota não confirmada' in strip.buttons['grok'].toolTip()
    monitor.set_deliveries([dict(provider='grok', count=0)])
    assert strip.buttons['grok'].isHidden()
    strip.close()


def test_only_confirmed_redeemable_reset_keeps_cell_visible(qapp, monkeypatch):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    item = ai.unknown('codex')
    item['reset_credits'] = dict(available=1, observed_at=now, expires_at=now + 20)
    monitor.set_items([item])
    strip = MiniAIStrip(monitor)
    assert not strip.buttons['codex'].isHidden()
    assert strip.values['codex'].text() == 'Resgate'
    monkeypatch.setattr('folego.ui.mini_ai_strip.time.time', lambda: now + 21)
    strip.refresh()
    assert strip.buttons['codex'].isHidden()
    strip.close()


def test_web_cell_shows_ok_only_with_fresh_open_instance(qapp):
    now = time.time()
    monitor = AIMonitor(collect_fn=lambda: [], deliveries=SimpleNamespace(collect=lambda: []))
    strip = MiniAIStrip(monitor)
    strip.show()
    web = ai.unknown('web')
    web.update(account_id='web-account', web_instances=2, web_instances_at=now)
    monitor.set_items([web])
    assert not strip.buttons['web'].isHidden()
    assert strip.values['web'].text() == 'OK'
    assert '2 instância(s) aberta(s)' in strip.buttons['web'].toolTip()
    web['web_instances'] = 0
    monitor.set_items([web])
    assert strip.buttons['web'].isHidden()
    monitor.set_deliveries([dict(provider='web', count=1)])
    assert not strip.buttons['web'].isHidden()
    assert strip.values['web'].text() == 'Entrega'
    assert 'Nenhuma instância aberta nesta conta' in strip.buttons['web'].toolTip()
    strip.close()
