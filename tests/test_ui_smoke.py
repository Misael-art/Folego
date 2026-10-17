from folego.core.snapshot import (MemInfo, Pressure, Snapshot)
from folego.ui.main_window import MainWindow


def a_snapshot(available_kb=5_000_000, total_kb=14_374_304):
    return Snapshot(
        ts=0.0, mem=MemInfo(total_kb, available_kb),
        swap_used_kb=0, swap_total_kb=0,
        pressure_memory=Pressure(0, 0, 0, 0), pressure_io=None, pressure_cpu=None,
        load=None, apps=(), self_rss_kb=90_000,
    )


def test_main_window_shows_live_ram_in_title(qapp):
    win = MainWindow(collector_factory=lambda: a_snapshot())
    win.apply_snapshot(a_snapshot())
    assert win.windowTitle().startswith("Fôlego 🟢 ·")
    assert "app 87 MB" in win.windowTitle()  # 90000 kB -> 87 MB


def test_main_window_title_updates_on_red(qapp):
    win = MainWindow(collector_factory=lambda: a_snapshot())
    win.apply_snapshot(a_snapshot(available_kb=1_000_000))
    assert "🔴" in win.windowTitle()


def test_main_window_survives_snapshot_without_meminfo(qapp):
    from dataclasses import replace
    win = MainWindow(collector_factory=lambda: a_snapshot())
    win.apply_snapshot(replace(a_snapshot(), mem=None))
    assert "meminfo indisponível" in win.windowTitle()


def test_main_window_surfaces_poll_errors(qapp):
    """A failing collect must be visible in the UI, not silently swallowed."""
    def boom():
        raise OSError(28, "No space left on device")

    win = MainWindow(collector_factory=lambda: boom)
    win.start()
    win._poller.poll_once()  # o timer faria isso; no teste dirigimos direto
    assert "No space left" in win.dashboard.status.text()


def test_main_window_error_clears_on_good_snapshot(qapp):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return a_snapshot()

    win = MainWindow(collector_factory=lambda: flaky)
    win.start()
    win._poller.poll_once()
    win._poller.poll_once()
    assert "disk hiccup" not in win.dashboard.status.text()
