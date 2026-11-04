import time

from folego.core import ai_sessions as ai
from folego.ui.ai_strip import AIStrip
from folego.ui.desktop_shortcuts import DesktopController, ShortcutTabs


class Backend:
    def __init__(self):
        self.calls = []
        self.closed = False

    def perform(self, action, value=None):
        self.calls.append((action, value))
        return "enviado"

    def close(self):
        self.closed = True


def drain(qapp, controller):
    end = time.monotonic() + 2
    while controller.future is not None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(.01)
    assert controller.future is None


def test_tabs_use_distinct_keyboard_hit_targets_without_sticky_position(qapp, monkeypatch):
    backend = Backend()
    controller = DesktopController(backend=backend)
    tabs = ShortcutTabs(controller=controller)
    positions = []
    monkeypatch.setattr(tabs, "open_keyboard", positions.append)
    tabs.top_button.click()
    tabs.buttons["keyboard"].click()
    tabs.buttons["keyboard"].click()
    assert positions == ["top", "bottom", "bottom"]
    for action in ("copy", "paste", "print"):
        tabs.buttons[action].click()
        drain(qapp, controller)
    assert [call[0] for call in backend.calls] == ["copy", "paste", "print"]
    for action in ('select_all', 'delete_all'):
        tabs.buttons[action].click()
        drain(qapp, controller)
        assert backend.calls[-1][0] == action
    tabs.shutdown()


def test_busy_input_does_not_queue_or_replay_clicks(qapp):
    import threading
    gate = threading.Event()
    backend = Backend()
    original = backend.perform
    backend.perform = lambda *args: gate.wait(2) or original(*args)
    controller = DesktopController(backend=backend)
    assert controller.request("copy")
    assert not controller.request("paste")
    gate.set()
    drain(qapp, controller)
    controller.close()


def test_quota_reset_expires_on_screen_without_new_collection(qapp):
    strip = AIStrip(collect_fn=lambda: [])
    now = time.time()
    item = ai.unknown("codex")
    item.update(observed_at=now, windows=[ai.quota_window("Sessão", 72, now + 10, now)])
    strip.set_items([item])
    assert "28%" in strip.buttons["codex"].accessibleName()
    item["windows"][0]["resets_at"] = now - 1
    strip.render()
    assert "desconhecida" in strip.buttons["codex"].accessibleName()
    strip.shutdown()


def test_provider_failure_does_not_leave_old_green(qapp):
    strip = AIStrip(collect_fn=lambda: [])
    now = time.time()
    item = ai.unknown("claude")
    item.update(observed_at=now, windows=[ai.quota_window("Sessão", 10, now + 10, now)])
    strip.set_items([item])
    assert "90%" in strip.buttons["claude"].accessibleName()
    strip.failed("secret-bearing failure detail")
    assert "desconhecida" in strip.buttons["claude"].accessibleName()
    assert "secret" not in strip.buttons["claude"].toolTip()
    strip.shutdown()


def test_reset_gift_counts_all_confirmed_accounts_without_changing_delivery_count(qapp):
    strip = AIStrip(collect_fn=lambda: [])
    now = time.time()
    items = []
    for provider in ai.NAMES:
        for key, available in (('main', 0), ('work', 2), ('unknown', None)):
            item = ai.unknown(provider, label=key)
            item.update(account_id=provider + key, default=key == 'main')
            if available is not None:
                item['reset_credits'] = dict(available=available, observed_at=now, expires_at=now + 60)
            items.append(item)
    strip.set_deliveries([dict(provider=p, count=3, pending=[]) for p in ai.NAMES])
    strip.set_items(items)
    for provider in ai.NAMES:
        gift = strip.reset_badges[provider]
        assert not gift.isHidden() and gift.text() == '2' and not gift.icon().isNull()
        assert 'work: 2' in gift.toolTip() and 'sem confirmação' in gift.toolTip()
        assert strip.badges[provider].text() == '3'
        assert 'redefinições' in gift.accessibleName()
    # Gift opens the contributing account, while provider hover keeps default.
    strip.reset_badges['codex'].click()
    assert strip.account_panel.selected == 'codexwork'
    strip.account_menu.close()
    strip.details('codex')
    assert strip.account_panel.selected == 'codexmain'
    strip.account_menu.close()
    for item in items:
        if item.get('reset_credits'): item['reset_credits']['expires_at'] = now - 1
    strip.render()
    assert all(b.isHidden() for b in strip.reset_badges.values())
    assert all(b.text() == '3' for b in strip.badges.values())
    strip.shutdown()


def test_reset_blink_runs_only_with_visible_fresh_offers_and_stops_on_failure(qapp):
    from folego.ui.theme import STYLESHEET
    # Product theme has a minimum button height; the miniature gift overrides it.
    strip = AIStrip(collect_fn=lambda: [])
    strip.setStyleSheet(STYLESHEET)
    strip.resize(260, strip.sizeHint().height())
    # Isolate worker delivery from the visual lifecycle exercised here.
    strip.poller.request = lambda: None
    strip.delivery_poller.request = lambda: None
    now = time.time()
    item = ai.unknown('codex')
    item['reset_credits'] = dict(available=12, observed_at=now)
    strip.set_items([item])
    assert not strip.reset_blink.isActive()
    strip.show()
    qapp.processEvents()
    assert not strip.reset_blink.isActive() and not strip.columns['codex'].isVisible()
    item.update(observed_at=now, windows=[ai.quota_window('Sessão', 50, now + 60, now)])
    strip.render()
    assert strip.reset_blink.isActive()
    gift = strip.reset_badges['codex']
    assert gift.text() == '9+' and '12 redefinições' in gift.toolTip()
    assert gift.height() == 14 and gift.parentWidget().rect().contains(gift.geometry())
    assert gift.graphicsEffect().opacity() == 1
    strip._blink_resets()
    assert gift.graphicsEffect().opacity() == .5
    strip.render()  # freshness refresh must not reset the blink phase
    assert gift.graphicsEffect().opacity() == .5
    strip.hide()
    assert not strip.reset_blink.isActive()
    strip.show()
    qapp.processEvents()
    assert strip.reset_blink.isActive() and gift.graphicsEffect().opacity() == 1
    item['reset_credits']['observed_at'] = now - ai.MAX_AGE - 1
    strip.render()
    assert gift.isHidden() and not strip.reset_blink.isActive()
    item['reset_credits']['observed_at'] = now
    strip.render()
    assert strip.reset_blink.isActive()
    strip.failed('unavailable')
    assert gift.isHidden() and not strip.reset_blink.isActive()
    strip.shutdown()
    strip.close()


def test_native_keyboard_position_requires_same_physical_pixels(qapp, monkeypatch):
    import json
    from folego.ui.desktop_shortcuts import VirtualKeyboard
    controller = DesktopController(backend=Backend())
    keyboard = VirtualKeyboard(controller)
    monkeypatch.setattr(keyboard, "devicePixelRatioF", lambda: 1.35)
    keyboard._geometry = (0, 313, 948, 280)
    keyboard.placed(keyboard.windowTitle(), json.dumps([0, 313, 948.148148148, 280]))
    assert keyboard.confirmed_geometry == keyboard._geometry
    keyboard.confirmed_geometry = None
    keyboard._placement_event.clear()
    keyboard.placed(keyboard.windowTitle(), json.dumps([0, 313, 949, 280]))
    assert keyboard.confirmed_geometry is None and not keyboard._placement_event.is_set()
    keyboard.placed(keyboard.windowTitle(), json.dumps([0, 313, 948, 280, False]))
    assert keyboard.confirmed_geometry is None and not keyboard._placement_event.is_set()
    keyboard.placed(keyboard.windowTitle(), json.dumps([0, 313, 948, 280, True]))
    assert keyboard.confirmed_geometry == keyboard._geometry
    keyboard.bus.unregisterObject("/keyboard")
    keyboard.bus.unregisterService(keyboard.service)
    controller.close()


def test_delivery_badge_is_independent_of_quota_and_click_opens_application(qapp, monkeypatch):
    from PySide6.QtCore import QObject, Signal
    class Opener(QObject):
        result = Signal(str)
        feedback = Signal(str)
        def __init__(self): super().__init__(); self.requests = []
        def request(self, action, value): self.requests.append((action, value))
        def close(self): pass
    class Monitor:
        def collect(self): return []
    opener = Opener()
    strip = AIStrip(collect_fn=lambda: [], deliveries=Monitor(), opener=opener)
    pending = [{'session': 'test', 'event': 'done'}]
    strip.set_deliveries([dict(provider='codex', count=2, pending=pending)])
    assert strip.badges['codex'].text() == '2'
    strip.failed('quota unavailable')
    assert strip.badges['codex'].text() == '2'
    strip.buttons['codex'].click()
    assert opener.requests == [('agent-open', ('codex', pending))]
    strip.set_deliveries([dict(provider='codex', count=2, pending=pending, complete=False)])
    assert strip.badges['codex'].text() == '2+'
    assert 'Pelo menos' in strip.buttons['codex'].accessibleName()
    strip._delivery_failed('unknown log')
    assert strip.badges['codex'].text() == '?'
    strip.buttons['codex'].click()
    assert opener.requests[-1] == ('agent-open', ('codex', []))
    monkeypatch.setattr('folego.ui.ai_strip.QInputDialog.getInt', lambda *a, **k: (15, True))
    strip.billing('codex')
    assert opener.requests[-1] == ('agent-billing', ('codex', 15))
    strip.shutdown()
