"""M3 window: five tabs, one signal, and a deep link that actually lands.

The window is the only place that owns the polling and the jobs; the tabs receive
data. These tests drive it offscreen with fake job layers — the real child path
is covered in test_ui_tune_jobs.py.
"""
import pytest

from deck_wellness.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from deck_wellness.ui.main_window import MainWindow

pytest.importorskip("PySide6")

GIB = 1024 ** 3


def snap(**over):
    base = dict(ts=0.0, mem=MemInfo(14_374_304, 5_000_000), swap_used_kb=0,
                swap_total_kb=7_208_724, pressure_memory=Pressure(0, 0, 0, 0),
                pressure_io=None, pressure_cpu=None, load=None,
                apps=(AppRSS("edge", 3 * GIB, 21),), self_rss_kb=90_000)
    base.update(over)
    return Snapshot(**base)


class FakeJobs:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def run(self, acao, tuning_id, *, confirm=False, done):
        self.calls.append((acao, tuning_id, confirm))
        done(self.answers(acao, tuning_id))

    def shutdown(self):
        """Part of the job-layer surface the window closes children through."""
        self.calls.append(("shutdown", "*", False))


def detect_answer(acao, tuning_id):
    return {"acao": "detect", "ok": True, "exit": 0, "exists": True, "present": True,
            "current": True, "desired": False, "change_needed": True, "error": None,
            "file": f"/home/u/{tuning_id}", "key": "a.b", "label": tuning_id,
            "why": "motivo"}


def plan_answer(acao, tuning_id):
    return {"acao": "plan", "ok": True, "exit": 0, "digest": "d", "total_bytes": 2 * GIB,
            "scanned_bytes": 2 * GIB, "volumes": [],
            "items": [{"target_id": "thumbnails", "label": "Miniaturas",
                       "path": "/home/u/.cache/thumbnails", "bytes": 2 * GIB,
                       "files": 10, "age_days": 1.0, "reclaimable": True,
                       "reason": "ok", "errors": [], "truncated": False}]}


def tmpfs_answer(acao, tuning_id):
    return {"acao": acao, "ok": True, "exit": 0, "generated_at": "x", "volumes": [],
            "policy": {}, "reclaimable": [], "protected": [], "total_bytes": 0,
            "scanned_entries": 0, "scanned_bytes": 0, "digest": "d" * 64, "errors": [],
            "records": [], "budget": {"retained_bytes": 0, "retained_count": 0,
                                      "oldest_days": 0.0, "slack_bytes": 0,
                                      "freed_bytes": 0, "by_volume": {},
                                      "max_bytes": 0, "days": 14.0}}


@pytest.fixture
def window(qapp):
    win = MainWindow(collector_factory=lambda: snap,
                     jobs=FakeJobs(detect_answer), disk_jobs=FakeJobs(plan_answer),
                     tmpfs_jobs=FakeJobs(tmpfs_answer))
    return win


def test_the_window_offers_the_five_approved_tabs_in_order(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == \
        ["memória", "ajustes", "órfãos", "disco", "temporários"]
    assert window.tabs.widget(0) is window.dashboard
    assert window.tabs.widget(4) is window.tmpfs


def test_the_watched_volumes_land_on_the_tmpfs_tab(window):
    from deck_wellness.core.tmpfs import TmpfsVolume
    window.apply_snapshot(snap(tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 7 * GIB,
                                                  GIB),)))
    assert window.tmpfs.volume_rows[0]["path"] == "/tmp"


def test_the_window_never_scans_tmpfs_by_itself(window):
    """Abrir a janela não pode virar varredura: o plano é ato de quem está olhando."""
    window.apply_snapshot(snap())
    assert window._tmpfs_jobs.calls == []
    window.tmpfs.refresh()
    assert [c[0] for c in window._tmpfs_jobs.calls] == ["plan", "ledger"]


def test_a_snapshot_lands_on_the_title_the_dashboard_and_the_orphans(window):
    window.apply_snapshot(snap())
    assert window.windowTitle().startswith("DeckWellness 🟢 ·")
    assert [row.target for row in window.dashboard.rows] == ["ajustes"]


def test_a_suggestion_jump_selects_that_tab(window):
    window.apply_snapshot(snap())
    window.dashboard.rows[0].jump_button.click()
    assert window.tabs.currentWidget() is window.tunings


def test_jump_to_an_unknown_tab_leaves_the_view_alone(window):
    window.tabs.setCurrentWidget(window.orphans)
    window.jump_to("nada_disso")
    assert window.tabs.currentWidget() is window.orphans


def test_a_failing_poll_is_visible_and_clears_when_the_next_one_works(window):
    window.show_error("No space left on device")
    assert "No space left" in window.dashboard.status.text()
    window.apply_snapshot(snap())
    assert "No space left" not in window.dashboard.status.text()


def test_the_disk_measurement_feeds_the_dashboard_rule(window):
    window.apply_snapshot(snap())
    assert "thumbnails" not in [row.suggestion.id for row in window.dashboard.rows]

    window.disk.refresh()
    window.apply_snapshot(snap())
    assert "thumbnails" in [row.suggestion.id for row in window.dashboard.rows]


class FakePoller:
    def __init__(self):
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True


def test_a_live_tray_makes_closing_the_window_a_hide(window, qapp):
    """The menu promises "Abrir DeckWellness": closing must keep the signal alive."""
    poller = FakePoller()
    window._poller = poller
    window.tray.tray = object()
    window.show()
    window.close()
    assert window.isHidden()
    assert poller.stopped is False


def test_sair_do_deckwellness_really_stops(window, qapp):
    poller = FakePoller()
    window._poller = poller
    window.tray.tray = object()
    window.show()
    window.quit()
    assert poller.stopped is True


def test_closing_the_window_takes_every_child_layer_down(window):
    """A child stuck in D-state must not outlive the window that spawned it."""
    window.close()
    assert window._jobs.calls == [("shutdown", "*", False)]
    assert window._disk_jobs.calls == [("shutdown", "*", False)]
    assert window._tmpfs_jobs.calls == [("shutdown", "*", False)]


def test_the_window_never_detects_tunings_by_itself(window):
    window.apply_snapshot(snap())
    assert window.tunings.rows[0].state_label.text() == "consultando…"
    window.tunings.refresh()
    assert [c[0] for c in window._jobs.calls] == ["detect", "detect"]
