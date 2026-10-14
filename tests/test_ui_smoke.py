from deck_wellness.core.snapshot import (MemInfo, Pressure, Snapshot)
from deck_wellness.ui.main_window import MainWindow


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
    assert win.windowTitle().startswith("DeckWellness 🟢 ·")
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
