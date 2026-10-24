"""M3 tray: live signal in the KDE notification area, or an honest fallback.

Plasma/BigLinux can hide SNI icons by policy, and Wayland gives no way to prove
the icon is actually visible from here. So the tray is optional by design: the
window keeps working, and when the area is unavailable the app says which one it
fell back to instead of pretending.
"""
import pytest

from folego.core.snapshot import MemInfo, Pressure, Snapshot
from folego.core.tmpfs import TmpfsVolume
from folego.ui.tray import Tray

pytest.importorskip("PySide6")


@pytest.fixture(autouse=True)
def _app(qapp):
    """Menus and icons are widgets: the tray tests need the offscreen app."""
    return qapp


def snap(available_kb=5_000_000, total_kb=14_374_304, psi10=0.0, tmpfs=()):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=Pressure(psi10, psi10, psi10, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=(), self_rss_kb=90_000, tmpfs=tmpfs)


class StubSignal:
    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)


class FakeTray:
    """The QSystemTrayIcon surface the Tray uses."""

    def __init__(self, parent=None):
        self.tooltips = []
        self.visible = False
        self.messages = []
        self.menu_items = []
        self.icon = None
        self.activated = StubSignal()

    def setToolTip(self, text):
        self.tooltips.append(text)

    def setIcon(self, icon):
        self.icon = icon

    def show(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)

    def isVisible(self):
        return self.visible

    def showMessage(self, title, body, *a, **kw):
        self.messages.append((title, body))

    def setContextMenu(self, menu):
        self.menu_items = [action.text() for action in menu.actions()]


class FakeWindow:
    def __init__(self):
        self.raise_calls = 0
        self.quits = 0
        self.hides = 0
        self.pauses = 0
        self.compacts = 0

    def raise_to_user(self):
        self.raise_calls += 1

    def show_compact(self):
        self.compacts += 1

    def hide_window(self):
        self.hides += 1
        return True

    def toggle_pause(self):
        self.pauses += 1
        return bool(self.pauses % 2)

    def quit(self):
        self.quits += 1


def build(available=True, window=None):
    window = window or FakeWindow()
    tray = Tray(window, available_fn=lambda: available, tray_factory=FakeTray)
    return tray, window


def test_the_tray_is_not_installed_when_the_area_is_absent():
    tray, window = build(available=False)
    assert tray.install() is False
    assert tray.tray is None
    assert "bandeja indisponível" in tray.fallback


def test_the_fallback_names_where_the_user_still_sees_the_signal():
    tray, _ = build(available=False)
    tray.install()
    assert "janela" in tray.fallback and "título" in tray.fallback


def test_a_live_tray_shows_the_same_signal_as_the_title():
    tray, window = build()
    tray.install()
    tray.show_snapshot(snap(psi10=13.0))
    assert "🔴" in tray.tray.tooltips[-1]
    assert tray.tray.visible is True


def test_tray_route_exists_before_the_first_collection_arrives():
    tray, _ = build()
    tray.install()
    assert tray.tray.visible
    assert "aguardando primeira leitura" in tray.tray.tooltips[-1]


def test_the_tray_menu_offers_only_viewing_actions():
    tray, window = build()
    tray.install()
    assert "Abrir Fôlego" in tray.tray.menu_items
    assert not [item for item in tray.tray.menu_items
                if any(word in item.lower() for word in
                       ("encerrar", "aplicar", "matar", "limpar"))]


def test_the_menu_keeps_hide_pause_and_quit_as_distinct_actions():
    tray, window = build()
    tray.install()

    labels = tray.tray.menu_items
    assert "Mostrar controle compacto" in labels
    assert "Ocultar janela" in labels
    assert "Pausar monitoramento" in labels
    assert "Sair do Fôlego" in labels

    menu = tray._context_menu
    by_text = {action.text(): action for action in menu.actions()}
    by_text["Mostrar controle compacto"].trigger()
    by_text["Ocultar janela"].trigger()
    by_text["Pausar monitoramento"].trigger()
    by_text["Sair do Fôlego"].trigger()
    assert (window.compacts, window.hides, window.pauses, window.quits) == \
        (1, 1, 1, 1)

    tray.set_paused(True)
    assert by_text["Pausar monitoramento"].text() == "Retomar monitoramento"
    tray.set_paused(False)
    assert by_text["Pausar monitoramento"].text() == "Pausar monitoramento"


def test_clicking_the_icon_brings_the_window_and_nothing_else():
    tray, window = build()
    tray.install()
    tray.activated()
    assert window.raise_calls == 1 and window.quits == 0


def test_the_tray_never_writes_anywhere():
    """The tray is a viewer: no jobs object exists to give it a lever."""
    tray, _ = build()
    assert not hasattr(tray, "jobs")


def test_the_tooltip_shows_the_worst_watched_volume(qapp):
    """A bandeja não tem regra própria: ela herda o texto do título."""
    # 8 GiB de teto e 8_010_114_007 usados = 93,2%, que é o "93%" do exemplo da
    # spec (§8). Os bytes são literais e somam o teto porque a spec dava aquilo como
    # prosa ilustrativa e este plano o endureceu em asserção: com used+avail != total
    # o volume era incoerente e `round(used_frac*100)` dava 89%, não 93%.
    tray, _ = build()
    tray.install()
    tray.show_snapshot(snap(tmpfs=(TmpfsVolume(
        "/tmp", "tmpfs", 8 * 1024**3, 8_010_114_007, 579_820_585),)))
    assert "/tmp 93%" in tray.tray.tooltips[-1]
