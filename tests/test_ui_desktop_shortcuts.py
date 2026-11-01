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
    keyboard.bus.unregisterObject("/keyboard")
    keyboard.bus.unregisterService(keyboard.service)
    controller.close()


def test_delivery_badge_is_independent_of_quota_and_click_opens_application(qapp):
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
    strip.shutdown()
