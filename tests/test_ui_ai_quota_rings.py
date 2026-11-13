"""Quota truth, animation lifetime and the compact availability strip."""
import time

from PySide6.QtCore import QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyle

from folego.core import ai_sessions as ai
from folego.ui.ai_strip import AIStrip
from folego.ui.ai_monitor import AIMonitor
from folego.ui.theme import apply_theme, TOKENS


def make(qapp):
    strip = AIStrip(collect_fn=lambda: [])
    strip.poller.request = lambda: None
    strip.delivery_poller.request = lambda: None
    strip.resize(256, strip.sizeHint().height())
    return strip


def observation(provider, remaining):
    now = time.time()
    item = ai.unknown(provider)
    item.update(observed_at=now, windows=[ai.quota_window('Sessão', 100-remaining, now+60, now)])
    return item


def contains_color(button, color):
    image = button.icon().pixmap(30, 30).toImage()
    expected = QColor(color)
    return any(image.pixelColor(x, y) == expected
               for x in range(image.width()) for y in range(image.height()))


def test_rings_show_remaining_not_used_and_expiry_cancels_transition(qapp):
    strip = make(qapp)
    item = observation('codex', 31)
    strip.set_items([item])
    button = strip.buttons['codex']
    assert button.remaining == 31 and contains_color(button, '#eab308')
    strip.show();qapp.processEvents()
    item['windows'][0]['remaining'] = 10
    strip.render()
    assert button.transition.state() == QVariantAnimation.State.Running
    button.transition.setCurrentTime(225)
    frame = button.displayed
    strip.render()  # the freshness tick must not restart the animation
    assert button.displayed == frame and button.transition.currentTime() == 225
    item['windows'][0]['resets_at'] = time.time() - 1
    strip.render()
    assert button.remaining is None and button.displayed is None
    assert button.transition.state() == QVariantAnimation.State.Stopped
    assert not contains_color(button, '#dc2626')
    assert not strip.columns['codex'].isVisible()
    assert 'cota desconhecida ou vencida' in button.accessibleName()
    strip.shutdown()


def test_all_providers_use_rings_with_truthful_zero_and_unknown(qapp):
    strip = make(qapp)
    strip.set_items([observation(p, n) for p, n in zip(ai.NAMES, (100, 61, 20, 0))])
    for provider, remaining in zip(ai.NAMES, (100, 61, 20, 0)):
        button = strip.buttons[provider]
        if provider == 'web':
            assert button.remaining is None and not strip.columns[provider].isVisible()
            continue
        assert button.remaining == remaining
        if remaining:
            assert f'{remaining}% disponível' in button.accessibleName()
        else:
            assert not strip.columns[provider].isVisible()
        assert not button.icon().isNull() and button.text() == ai.NAMES[provider]
    strip.failed('unavailable')
    assert all(b.remaining is None for b in strip.buttons.values())
    assert all(not contains_color(b, '#16a34a') for b in strip.buttons.values())
    strip.shutdown()


def test_pulse_only_for_confirmed_deliveries_while_visible(qapp):
    strip = make(qapp)
    strip.set_items([observation('claude', 50)])
    strip.set_deliveries([dict(provider='claude', count=2, pending=[])])
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Stopped
    strip.show();qapp.processEvents()
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Running
    strip.delivery_pulse.setCurrentTime(900)
    assert strip.buttons['claude'].halo > .9
    assert strip.buttons['claude'].remaining == 50  # completion never changes quota
    assert all(b.halo == 0 for p, b in strip.buttons.items() if p != 'claude')
    strip._delivery_failed('unreadable')
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Stopped
    assert all(b.halo == 0 for b in strip.buttons.values())
    strip.set_deliveries([dict(provider='claude', count=2, pending=[])])
    strip.hide();qapp.processEvents()
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Stopped
    assert all(b.transition.state() == QVariantAnimation.State.Stopped and b.halo == 0
               for b in strip.buttons.values())
    strip.shutdown()


def test_sorted_availability_alternate_account_and_confirmed_return(qapp):
    strip = make(qapp)
    codex = observation('codex', 25)
    codex.update(account_id='default', default=True)
    claude = observation('claude', 71)
    claude.update(account_id='claude', default=True)
    empty = observation('grok', 0)
    web = ai.unknown('web')
    strip.show(); qapp.processEvents()
    strip.set_items([codex, claude, empty, web])
    assert [strip.layout().itemAt(i).widget() for i in range(2)] == [
        strip.columns['claude'], strip.columns['codex']]
    codex['windows'][0]['remaining'] = 80
    strip.render()
    assert strip.layout().itemAt(0).widget() is strip.columns['codex']
    codex['windows'][0]['remaining'] = 71
    strip.render()
    assert strip.layout().itemAt(0).widget() is strip.columns['codex']  # stable tie
    codex['windows'][0]['remaining'] = 25
    strip.render()
    assert strip.layout().itemAt(0).widget() is strip.columns['claude']
    assert not strip.columns['grok'].isVisible() and not strip.columns['web'].isVisible()
    assert not strip.empty_label.isVisible()
    alternative = observation('codex', 45)
    alternative.update(account_id='alternate', default=False, label='Outra conta')
    codex['windows'][0]['remaining'] = 0
    strip.set_items([codex, alternative, claude, empty, web])
    assert strip.display_accounts['codex'] == 'alternate'
    assert strip.buttons['codex'].remaining == 45
    assert 'Outra conta' in strip.buttons['codex'].accessibleName()
    claude['windows'][0]['remaining'] = 0
    strip.render()
    assert not strip.columns['claude'].isVisible()
    claude['windows'][0]['remaining'] = 60
    strip.render()
    assert strip.columns['claude'].isVisible()
    duration = strip.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration, None, strip)
    expected = (QVariantAnimation.State.Running if duration > 0 and
                strip.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, strip)
                else QVariantAnimation.State.Stopped)
    assert strip.arrival_animations['claude'].state() == expected
    strip.hide(); qapp.processEvents()
    strip.show(); qapp.processEvents()
    assert strip.arrival_animations['claude'].state() == QVariantAnimation.State.Stopped
    strip.set_items([empty, web])
    assert strip.empty_label.isVisible()
    strip.shutdown()


def test_pulse_redraws_in_coarse_steps(qapp):
    strip = make(qapp)
    strip.set_deliveries([dict(provider='claude', count=1, pending=[])])
    button = strip.buttons['claude']
    draws = []
    button._draw_icon = lambda: draws.append(button.halo)
    for step in range(101):
        strip._pulse_deliveries(step / 100)
    assert set(draws) <= {i / 8 for i in range(9)} and len(draws) <= 9
    strip.shutdown()


def test_web_ring_tracks_real_instance_without_quota(qapp):
    strip = make(qapp)
    strip.show(); qapp.processEvents()
    web = ai.unknown('web')
    web.update(account_id='web-account', web_instances=1, web_instances_at=time.time())
    strip.set_items([web])
    assert strip.columns['web'].isVisible()
    assert strip.buttons['web'].instance_active
    assert strip.buttons['web'].remaining is None
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Running
    web['web_instances'] = 0
    strip.set_items([web])
    assert not strip.columns['web'].isVisible()
    assert not strip.buttons['web'].instance_active
    strip.shutdown()


def test_web_mcp_report_is_visible_and_emitted_once(qapp):
    strip = make(qapp)
    strip.show(); qapp.processEvents()
    web = ai.unknown('web')
    web.update(account_id='web-account', web_instances=1, web_instances_at=time.time())
    strip.set_items([web])
    receipt = dict(session='session', event='turn', at=time.time() + 1,
                   reported_web_mcp_error=True)
    row = dict(provider='web', count=1, pending=[receipt], complete=True)
    strip.set_deliveries([row])
    assert strip.badges['web'].text() == '1!'
    assert 'sessão MCP encerrada' in strip.buttons['web'].accessibleName()
    assert 'sessão MCP encerrada' in strip.badges['web'].toolTip()
    strip.shutdown()

    class QuietAlerts:
        def observe(self, *_): pass
        def shutdown(self): pass
    monitor = AIMonitor(alerts=QuietAlerts())
    emitted = []
    monitor.web_mcp_reported.connect(emitted.append)
    monitor.set_deliveries([row])
    monitor.set_deliveries([row])
    assert emitted == [receipt]
    monitor.shutdown()


def test_capacity_error_badge_and_notification_are_deduplicated(qapp):
    strip = make(qapp)
    web = ai.unknown('web')
    web.update(account_id='web-account', web_instances=1, web_instances_at=time.time())
    strip.set_items([web])
    receipt = dict(session='capacity-session', event='turn', at=time.time() + 1, web_capacity_error=True)
    row = dict(provider='web', count=1, pending=[receipt], complete=True)
    strip.set_deliveries([row])
    assert strip.badges['web'].text() == '1!'
    assert 'erro de capacidade' in strip.buttons['web'].accessibleName()
    assert 'recuperação' in strip.badges['web'].toolTip()
    emitted = []
    strip.monitor.web_capacity_reported.connect(emitted.append)
    strip.monitor.set_deliveries([row])
    strip.monitor.set_deliveries([row])
    assert emitted == [receipt]
    strip.shutdown()


def test_four_columns_fit_with_gifts_in_light_dark_and_transparent_themes(qapp):
    strip = make(qapp)
    items = [observation(p, 31) for p in ai.NAMES]
    for item in items:
        item['reset_credits'] = dict(available=2, observed_at=time.time())
        if item['provider'] == 'web':
            item.update(web_instances=1, web_instances_at=time.time())
    strip.set_items(items)
    strip.set_deliveries([dict(provider=p, count=3, pending=[]) for p in ai.NAMES])
    previous = TOKENS.key, TOKENS.transparency
    try:
        for key, alpha in (('snes-us', 0), ('ps2', 0), ('ps2', 100)):
            apply_theme(qapp, key, transparency=alpha)
            strip.show();qapp.processEvents()
            for provider, button in strip.buttons.items():
                assert button.width() >= button.sizeHint().width()
                assert strip.rect().contains(button.geometry())
                gift = strip.reset_badges[provider]
                assert gift.parentWidget().rect().contains(gift.geometry())
                assert not gift.geometry().intersects(strip.badges[provider].geometry())
                assert contains_color(button, '#16a34a' if provider == 'web' else '#eab308')
    finally:
        apply_theme(qapp, previous[0], transparency=previous[1])
        strip.shutdown()


def test_web_menu_offers_limits_shortcut_through_the_existing_opener(qapp):
    strip, opened = make(qapp), []
    strip.open_agent = lambda provider, account=None: opened.append(provider)
    web = {a.text(): a for a in strip.options_menu('web').actions()}
    assert 'Abrir Limits no Codex Web' not in [a.text() for a in strip.options_menu('codex').actions()]
    web['Abrir Limits no Codex Web'].trigger()
    assert opened == ['web']
