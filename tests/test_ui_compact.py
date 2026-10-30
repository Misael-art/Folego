"""F5 compact control: navigation only, drag never acts, position recoverable."""
import pytest

from folego.core.snapshot import MemInfo, Pressure, Snapshot
from folego.ui.compact import CompactWindow, clamp_position
from folego.ui.desktop_caps import detect

pytest.importorskip("PySide6")


def snap(available_kb=5_000_000, total_kb=14_374_304):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=Pressure(0, 0, 0, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=(), self_rss_kb=90_000)


class Store:
    def __init__(self, value=""):
        self.data = {"compact/position": value}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        pass


class Host:
    def __init__(self):
        self.raised = 0
        self.quits = 0
        self.paused = False

    def raise_to_user(self):
        self.raised += 1

    def quit(self):
        self.quits += 1

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused


def wayland():
    return detect(session_type="wayland", platform="wayland", tray=True)


def x11():
    return detect(session_type="x11", platform="xcb", tray=True)


def make(qapp, *, caps=None, store=None):
    host = Host()
    view = CompactWindow(host, caps=caps or x11(), store=store or Store("100,100"))
    return view, host


# --------------------------------------------------------------------- capabilities

def test_wayland_does_not_pretend_to_support_absolute_placement():
    caps = wayland()
    assert caps.tray is True
    assert caps.absolute_position is False and caps.keep_above is False
    assert caps.compact_fallback is True
    assert "Wayland" in caps.note


def test_x11_exposes_placement_and_keep_above():
    caps = x11()
    assert caps.absolute_position and caps.keep_above
    assert caps.compact_fallback is False


def test_an_unknown_session_presumes_nothing():
    caps = detect(session_type=None, platform="unknown", tray=False)
    assert caps.absolute_position is False and caps.keep_above is False
    assert caps.autostart_hint is False


def test_hotplug_clamps_a_saved_position_onto_a_live_screen():
    screens = ((0, 0, 1920, 1080), (1920, 0, 1280, 800))
    assert clamp_position(2500, 100, 360, 190, screens) == (2500, 100)
    # the second monitor vanished: the saved point is no longer visible
    assert clamp_position(2500, 100, 360, 190, ((0, 0, 1920, 1080),)) == \
        (780, 445)
    assert clamp_position(10, 10, 360, 190, ()) == (0, 0)


def test_partial_overlap_keeps_all_controls_inside_the_screen():
    assert clamp_position(1900, 1000, 360, 190, ((0, 0, 1920, 1080),)) == (1560, 890)


def test_wayland_widget_never_takes_focus_nor_restores_absolute_coordinates(qapp):
    from PySide6.QtCore import Qt
    store = Store("5000,5000")
    view, _ = make(qapp, caps=wayland(), store=store)
    flags = view.windowFlags()
    assert flags & Qt.FramelessWindowHint and flags & Qt.WindowDoesNotAcceptFocus
    assert view.windowType() == Qt.Tool
    # keep-above is not provable on Wayland: it comes from the optional KWin rule, not from a hint
    assert not flags & Qt.WindowStaysOnTopHint
    view.show_compact()
    view._save_position()
    assert store.data["compact/position"] == "5000,5000"
    view.force_close()


def test_hotplug_repositions_an_already_open_x11_control(qapp, monkeypatch):
    view, _ = make(qapp)
    view.show_compact()
    view.move(1900, 1000)
    monkeypatch.setattr(view, "_screens", lambda: ((0, 0, 800, 600),))
    view._screen_changed()
    assert view.x() >= 0 and view.y() >= 0
    assert view.x() + view.width() <= 800
    assert view.y() + view.height() <= 600
    view.force_close()


# ------------------------------------------------------------------------- display

def test_the_health_alert_survives_a_later_completed_operation(qapp):
    view, _ = make(qapp)
    view.show_snapshot(snap(available_kb=100_000))
    alert = view.signal_label.text()
    assert "🔴" in alert

    view.set_operation("disk.quarantine · sucesso")

    assert view.signal_label.text() == alert, (
        "a completed operation must not erase a persistent health alert")
    assert "disk.quarantine · sucesso" in view.operation_label.text()


def test_the_compact_control_shows_the_real_automation_state(qapp):
    view, _ = make(qapp)
    view.set_automation(mode="assistido", preset="foco", active_grants=1)
    text = view.mode_label.text()
    assert "automação assistido" in text and "preset foco" in text
    assert "1 grant(s)" in text and "execução real desligada" in text
    assert "manual" not in text

    view.set_paused(True)
    assert "PAUSADO" in view.mode_label.text()
    assert "assistido" in view.mode_label.text()


def test_an_illegible_automation_state_is_not_drawn_as_manual(qapp):
    view, _ = make(qapp)
    view.set_automation(mode="desconhecido", preset="desconhecido",
                        error="registro ilegível")
    assert "ilegível" in view.mode_label.text()
    assert "fail-closed" in view.mode_label.text()
    assert "manual" not in view.mode_label.text()


def test_pause_is_a_distinct_state_and_says_so(qapp):
    view, host = make(qapp)
    view.pause_button.click()
    assert host.paused is True
    assert "PAUSADO" in view.mode_label.text()
    assert view.pause_button.toolTip() == "Retomar monitoramento"
    assert view.pause_button.accessibleDescription() == "monitoramento pausado"

    view.pause_button.click()
    assert host.paused is False
    assert "ativo" in view.mode_label.text()


def test_repeated_navigation_clicks_do_not_create_any_operation(qapp):
    view, host = make(qapp)
    view.open_button.click()
    view.open_button.click()
    assert host.raised == 2
    assert host.quits == 0
    assert "nenhuma" in view.operation_label.text(), (
        "navigation is not an operation and must not invent one")


def test_a_drag_moves_the_window_and_triggers_no_host_action(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    view, host = make(qapp, store=Store("100,100"))
    view.show_compact()
    qapp.processEvents()
    origin = view.pos()

    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                        QPointF(110, 110), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(40, 40),
                       QPointF(140, 140), Qt.MouseButton.NoButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(40, 40),
                          QPointF(140, 140), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(press)
    view.mouseMoveEvent(move)
    view.mouseReleaseEvent(release)

    assert view.pos() != origin
    assert (host.raised, host.quits, host.paused) == (0, 0, False)


def test_an_offscreen_saved_position_is_brought_back_before_showing(qapp):
    store = Store("5000,5000")
    view, _ = make(qapp, store=store)
    view.show_compact()
    qapp.processEvents()

    screens = view._screens()
    assert screens
    sx, sy, sw, sh = screens[0]
    assert sx <= view.x() < sx + sw
    assert sy <= view.y() < sy + sh


def test_closing_the_compact_control_only_hides_it(qapp):
    view, _ = make(qapp)
    view.show_compact()
    view.close()
    assert not view.isVisible()
    view.force_close()


def test_the_widget_button_returns_to_the_central_window_and_folds_itself(qapp):
    view, host = make(qapp)
    view.show_compact()
    view.open_button.click()
    assert host.raised == 1 and not view.isVisible()


def test_the_widget_shows_the_basic_numbers_and_a_mini_gauge(qapp):
    from folego.core.snapshot import MemInfo, Snapshot
    view, _ = make(qapp)
    snapshot = Snapshot(ts=0.0, mem=MemInfo(10_000_000, 3_000_000), swap_used_kb=500, swap_total_kb=1000,
                        pressure_memory=None, pressure_io=None, pressure_cpu=None, load=None,
                        apps=(), self_rss_kb=0, errors=(), tmpfs=(), sources=())
    view.show_snapshot(snapshot)
    text = view.detail_label.text()
    assert "RAM 70%" in text and "Swap 50%" in text
    assert view.gauge.value == 30
