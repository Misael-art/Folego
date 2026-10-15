"""M3 dashboard: the same numbers the title bar shows, plus what to do about them.

The panel receives plain data and a jump callback — it never measures, never
reads /proc and never mutates. That boundary is the test: a suggestion click
only changes which tab is visible.
"""
import pytest

from deck_wellness.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from deck_wellness.ui.dashboard_tab import DashboardTab

pytest.importorskip("PySide6")


def snap(*, available_kb=5_000_000, total_kb=14_374_304, psi10=0.0,
         swap_used_kb=0, swap_total_kb=7_208_724, self_rss_kb=96_000,
         apps=(AppRSS("edge", 3 * 1024 * 1024, 21),), errors=()):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=swap_used_kb, swap_total_kb=swap_total_kb,
                    pressure_memory=Pressure(psi10, psi10, psi10, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=apps, self_rss_kb=self_rss_kb, errors=errors)


@pytest.fixture
def panel(qapp):
    jumps = []
    return DashboardTab(on_jump=jumps.append), jumps


def test_the_headline_repeats_the_title_signal(panel):
    view, jumps = panel
    view.show_snapshot(snap(psi10=14.0))
    assert "🔴" in view.headline.text()


def test_suggestions_land_in_order_with_their_own_jump_target(panel):
    view, jumps = panel
    view.show_snapshot(snap(psi10=14.0, available_kb=900_000), orphan_count=2)
    assert [row.target for row in view.rows] == ["memoria", "memoria", "ajustes",
                                                 "orfaos"]


def test_clicking_a_suggestion_only_asks_to_change_tab(panel):
    view, jumps = panel
    view.show_snapshot(snap(apps=(AppRSS("edge", 3 * 1024 * 1024, 21),)))
    view.rows[0].jump_button.click()
    assert jumps == ["ajustes"]


def test_a_calm_machine_is_reported_calm_instead_of_left_blank(panel):
    view, _ = panel
    view.show_snapshot(snap(apps=(), psi10=0.0, available_kb=8_000_000))
    assert view.rows == []
    assert "nada" in view.status.text().lower()


def test_the_panel_shows_what_the_collector_could_not_read(panel):
    view, _ = panel
    view.show_snapshot(snap(errors=("meminfo: No space left on device",)))
    assert "No space left" in view.status.text()


def test_pressure_and_zram_get_their_own_numbers(panel):
    view, _ = panel
    view.show_snapshot(snap(psi10=12.0, swap_used_kb=6 * 1024 * 1024))
    text = view.details.text()
    assert "psi" in text.lower() and "12,0" in text
    assert "zram" in text.lower() and "6,0 GB" in text


def test_the_details_name_the_heaviest_apps(panel):
    """M1's body text listed them; the dashboard must not lose that."""
    view, _ = panel
    view.show_snapshot(snap(apps=(AppRSS("chrome", 900 * 1024, 9),
                                 AppRSS("codex", 120 * 1024, 3))))
    assert "chrome 900 MB" in view.details.text()
    assert "codex 120 MB" in view.details.text()


def test_a_snapshot_without_memory_leaves_the_title_alone(panel):
    view, _ = panel
    empty = Snapshot(ts=0.0, mem=None, swap_used_kb=0, swap_total_kb=0,
                     pressure_memory=None, pressure_io=None, pressure_cpu=None,
                     load=None, apps=(), self_rss_kb=0)
    view.show_snapshot(empty)
    assert "indisponível" in view.headline.text()
