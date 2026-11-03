"""Quota truth, animation lifetime and the four-column compact layout."""
import time

from PySide6.QtCore import QVariantAnimation
from PySide6.QtGui import QColor

from folego.core import ai_sessions as ai
from folego.ui.ai_strip import AIStrip
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
    assert 'desconhecida' in button.accessibleName()
    strip.shutdown()


def test_all_providers_use_rings_with_truthful_zero_and_unknown(qapp):
    strip = make(qapp)
    strip.set_items([observation(p, n) for p, n in zip(ai.NAMES, (100, 61, 20, 0))])
    for provider, remaining in zip(ai.NAMES, (100, 61, 20, 0)):
        button = strip.buttons[provider]
        assert button.remaining == remaining
        assert f'{remaining}% disponível' in button.accessibleName()
        assert not button.icon().isNull() and button.text() == ai.NAMES[provider]
    strip.failed('unavailable')
    assert all(b.remaining is None for b in strip.buttons.values())
    assert all(not contains_color(b, '#16a34a') for b in strip.buttons.values())
    strip.shutdown()


def test_pulse_only_for_confirmed_deliveries_while_visible(qapp):
    strip = make(qapp)
    strip.set_deliveries([dict(provider='claude', count=2, pending=[])])
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Stopped
    strip.show();qapp.processEvents()
    assert strip.delivery_pulse.state() == QVariantAnimation.State.Running
    strip.delivery_pulse.setCurrentTime(900)
    assert strip.buttons['claude'].halo > .9
    assert strip.buttons['claude'].remaining is None  # completion never invents quota
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


def test_four_columns_fit_with_gifts_in_light_dark_and_transparent_themes(qapp):
    strip = make(qapp)
    items = [observation(p, 31) for p in ai.NAMES]
    for item in items:
        item['reset_credits'] = dict(available=2, observed_at=time.time())
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
                assert contains_color(button, '#eab308')
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
