"""M3 window: five tabs, one signal, and a deep link that actually lands.

The window is the only place that owns the polling and the jobs; the tabs receive
data. These tests drive it offscreen with fake job layers — the real child path
is covered in test_ui_tune_jobs.py.
"""
from types import SimpleNamespace
import os

import pytest

from folego.core.exclusions import ExclusionError
from folego.core.sessions import ACTIVE, Session, SessionError
from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from folego.orchestration.config import ConfigError
from folego.ui.compact import CompactWindow
from folego.ui.main_window import MainWindow
from fixtures_automation import StaticConfig, StaticGrants, stores
from fixtures_proc import proc_info

pytest.importorskip("PySide6")

GIB = 1024 ** 3


def wait_history(qapp, win):
    import time
    deadline = time.monotonic() + 3
    while win._history_text == "aguardando leitura do histórico" and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert win._history_text != "aguardando leitura do histórico"


def test_health_expires_without_another_snapshot_or_journal_read(window, monkeypatch):
    import time
    view = window
    sampled_at = time.monotonic()
    view.apply_snapshot(snap(mono=sampled_at))
    assert view._last_signal.level == "green"
    def forbidden():
        raise AssertionError("freshness timer must not read history")
    monkeypatch.setattr(view, "_last_operation_text", forbidden)
    view._refresh_freshness(now_mono=sampled_at + 16.0)
    assert view._last_signal.level == "unknown"
    assert "antiga" in view.windowTitle()
    assert "não comprovada" in view.dashboard.resources.text()
    assert view.dashboard.rows == []


def test_collection_failure_and_monitoring_pause_remove_old_green_health(window):
    view = window
    view.apply_snapshot(snap())
    view.show_error("permission denied")
    assert view._last_signal.level == "unknown"
    assert "permission denied" in view.windowTitle()
    view.apply_snapshot(snap())
    assert view._last_signal.level == "green"
    view.pause_watching()
    assert view._last_signal.level == "unknown"
    assert "monitoramento pausado" in view.windowTitle()
    view.apply_snapshot(snap())  # a sample already queued before pause
    assert view._last_signal.level == "unknown"


def test_pause_before_first_sample_is_named_in_central_and_compact(window, qapp):
    window.show_compact()
    window.pause_watching()
    assert "monitoramento pausado" in window.windowTitle()
    assert "monitoramento pausado" in window._compact.signal_label.text()
    assert window._last_snapshot is None
    window.quit()


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
    config_store, grant_store = stores()
    win = MainWindow(collector_factory=lambda: snap,
                     jobs=FakeJobs(detect_answer), disk_jobs=FakeJobs(plan_answer),
                     tmpfs_jobs=FakeJobs(tmpfs_answer),
                     config_store=config_store, grant_store=grant_store)
    return win


def test_the_window_offers_resource_tabs_and_accessibility_in_order(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == \
        ["central", "ajustes", "órfãos", "disco", "temporários", "acessibilidade", "opções"]
    assert window.tabs.widget(0) is window.dashboard
    assert window.tabs.widget(4) is window.tmpfs


def test_the_window_reads_automation_state_but_offers_no_grant_control(qapp):
    config = StaticConfig(mode="assistido", preset="foco", paused=True)
    grants = StaticGrants([SimpleNamespace(action="tmpfs.release")])
    win = make_window(config_store=config, grant_store=grants)

    text = win.dashboard.automation_status.text()
    assert "modo assistido" in text and "preset foco" in text
    assert "pausada" in text and "1 grant(s) ativo(s)" in text
    assert "execução real desligada" in text
    assert not hasattr(win, "grant_button"), "grant não se cria na janela"


class _CompactStore:
    def value(self, key, default=None):
        return default

    def setValue(self, key, value):
        pass

    def sync(self):
        pass


def test_the_compact_control_receives_the_same_read_only_automation_state(qapp):
    config = StaticConfig(mode="assistido", preset="foco", paused=True)
    grants = StaticGrants([SimpleNamespace(action="tmpfs.release")])
    win = make_window(
        config_store=config, grant_store=grants,
        compact_factory=lambda view, caps: CompactWindow(
            view, caps=caps, store=_CompactStore()))

    win.show_compact()
    text = win._compact.mode_label.text()

    assert "automação assistido" in text and "preset foco" in text
    assert "execução real desligada" in text
    assert win._compact.pause_button.toolTip() == "Pausar monitoramento", (
        "pausa da automação não é a pausa da coleta")
    win._compact.force_close()


def test_an_illegible_automation_record_is_named_and_fails_closed(qapp):
    class BadConfig:
        def read(self):
            raise ConfigError("registro de automação ilegível: versão 99")

    win = make_window(config_store=BadConfig(), grant_store=StaticGrants())

    text = win.dashboard.automation_status.text()
    assert "ilegível" in text and "fail-closed" in text
    assert "execução desligada" in text


def test_the_watched_volumes_land_on_the_tmpfs_tab(window):
    from folego.core.tmpfs import TmpfsVolume
    window.apply_snapshot(snap(tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 7 * GIB,
                                                  GIB),)))
    assert window.tmpfs.volume_rows[0]["path"] == "/tmp"


def test_the_window_never_scans_tmpfs_by_itself(window):
    """Abrir a janela não pode virar varredura: o plano é ato de quem está olhando."""
    window.apply_snapshot(snap())
    assert window._tmpfs_jobs.calls == []
    window.tmpfs.refresh()
    assert [c[0] for c in window._tmpfs_jobs.calls] == ["plan", "ledger", "diagnose", "runtime-size"]
    assert all(c[2] is False for c in window._tmpfs_jobs.calls), "atualizar nunca leva --confirmar"


def test_a_snapshot_lands_on_the_title_the_dashboard_and_the_orphans(window):
    window.apply_snapshot(snap())
    assert window.windowTitle().startswith("Fôlego 🟢 ·")
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
        self.pauses = 0
        self.resumes = 0

    def start(self):
        pass

    def pause(self):
        self.pauses += 1

    def resume(self):
        self.resumes += 1

    def stop(self):
        self.stopped = True


def test_a_live_tray_makes_closing_the_window_a_hide(window, qapp):
    """The menu promises "Abrir Fôlego": closing must keep the signal alive."""
    poller = FakePoller()
    window._poller = poller
    window.tray.tray = object()
    window.show()
    window.close()
    assert window.isHidden()
    assert poller.stopped is False


def test_pause_is_not_hide_and_not_quit(window, qapp):
    poller = FakePoller()
    window._poller = poller
    window.show()

    assert window.toggle_pause() is True
    assert window.paused and window.isVisible()
    assert poller.pauses == 1
    assert not poller.stopped

    assert window.toggle_pause() is False
    assert poller.resumes == 1 and not poller.stopped
    assert window.isVisible()

    window.tray.tray = object()
    assert window.hide_window() is True
    assert window.isHidden() and not poller.stopped


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


def test_no_tray_close_keeps_visible_compact_and_workers_alive(window, qapp):
    poller = FakePoller()
    window._poller = poller
    window.show()
    window.show_compact()
    window.close()
    assert not window.isVisible() and window._compact.isVisible()
    assert not poller.stopped and window._jobs.calls == []
    window._compact.hide_button.click()
    assert window.isVisible() and not window._compact.isVisible()
    assert not poller.stopped
    assert not window.hide_window(), "hidden compact is not a route back"
    window.quit()
    assert poller.stopped


def test_the_window_never_detects_tunings_by_itself(window):
    window.apply_snapshot(snap())
    assert window.tunings.rows[0].state_label.text() == "consultando…"
    window.tunings.refresh()
    assert [c[0] for c in window._jobs.calls] == ["detect", "detect"]


class _Sessions:
    def __init__(self, *items):
        self.items = items

    def snapshot(self):
        return self.items


class _NoExclusions:
    def list(self):
        return ()


class _EmptyJournal:
    def load(self):
        return [], []


def make_window(**kw):
    kw.setdefault("journal", _EmptyJournal())
    kw.setdefault("config_store", stores()[0])
    kw.setdefault("grant_store", stores()[1])
    return MainWindow(collector_factory=lambda: snap(),
                      jobs=FakeJobs(detect_answer),
                      disk_jobs=FakeJobs(plan_answer),
                      tmpfs_jobs=FakeJobs(tmpfs_answer), **kw)


def test_a_keep_active_session_hides_an_otherwise_proven_orphan(qapp):
    proc = proc_info(500, comm="builder", ppid=1, pgid=900, session=901,
                     starttime=777)
    session = Session(
        session_id="00000000-0000-0000-0000-000000000001", pid=500,
        starttime=777, boot_id="b", uid=proc.uid, created_at=1.0,
        heartbeat_at=1.0, state=ACTIVE, keep_active=True)
    win = make_window(sessions=_Sessions(session),
                      exclusions=_NoExclusions())

    win.apply_snapshot(snap(ts=1_000.0, procs=(proc,)))
    win.apply_snapshot(snap(ts=2_000.0, procs=(proc,)))

    assert win.orphans.rows() == [], (
        "a session that says keep-active is not a leftover, even when idle")
    protections = win.orphans.protections_text()
    assert "sessões: active 1" in protections and "keep-active" in protections


def test_an_unreadable_session_registry_hides_every_candidate(qapp):
    class Broken:
        def snapshot(self):
            raise SessionError("registro ilegível")

    proc = proc_info(500, comm="maybe-orphan", ppid=1, pgid=900, session=901,
                     starttime=777)
    win = make_window(sessions=Broken(), exclusions=_NoExclusions())

    win.apply_snapshot(snap(ts=1_000.0, procs=(proc,)))
    win.apply_snapshot(snap(ts=2_000.0, procs=(proc,)))

    assert win.orphans.rows() == [], (
        "an unknown protection state must never authorize a termination")
    assert "proteção não comprovada" in win.orphans.protections_text()


def test_an_unreadable_exclusion_file_also_fails_closed(qapp):
    class Broken:
        def list(self):
            raise ExclusionError("lista ilegível")

    proc = proc_info(500, comm="maybe-orphan", ppid=1, pgid=900, session=901,
                     starttime=777)
    win = make_window(sessions=_Sessions(), exclusions=Broken())

    win.apply_snapshot(snap(ts=1_000.0, procs=(proc,)))
    win.apply_snapshot(snap(ts=2_000.0, procs=(proc,)))

    assert win.orphans.rows() == []
    assert "exclusões ilegíveis" in win.orphans.protections_text()


def test_the_overview_shows_the_journal_last_word(qapp):
    class Journal:
        def load(self):
            return ([SimpleNamespace(
                kind="result", ts=1_700_000_000.0,
                result=SimpleNamespace(action="disk.quarantine",
                                       outcome="sucesso", reason=None))], [])

    win = make_window(sessions=_Sessions(), exclusions=_NoExclusions(),
                      journal=Journal())
    win.apply_snapshot(snap())

    wait_history(qapp, win)

    text = win.dashboard.last_operation.text()
    assert "disk.quarantine · sucesso" in text
    assert "nenhuma operação" not in text


def test_an_absurd_journal_timestamp_does_not_break_the_overview(qapp):
    class Journal:
        def load(self):
            return ([SimpleNamespace(
                kind="result", ts=1e300,
                result=SimpleNamespace(action="disk.quarantine",
                                       outcome="sucesso", reason=None))], [])

    win = make_window(sessions=_Sessions(), exclusions=_NoExclusions(),
                      journal=Journal())
    win.apply_snapshot(snap())

    wait_history(qapp, win)

    assert "data inválida" in win.dashboard.last_operation.text()


def test_a_corrupt_journal_is_named_and_never_read_as_empty(qapp):
    class Journal:
        def load(self):
            return [], ["linha 1: JSON ilegível"]

    win = make_window(sessions=_Sessions(), exclusions=_NoExclusions(),
                      journal=Journal())
    win.apply_snapshot(snap())

    wait_history(qapp, win)

    text = win.dashboard.last_operation.text()
    assert "histórico com 1 problema" in text
    assert "mutações devem ser recusadas" in text


def test_an_unreadable_journal_file_is_unknown_not_empty(qapp):
    class Journal:
        def load(self):
            raise OSError("sem permissão")

    win = make_window(sessions=_Sessions(), exclusions=_NoExclusions(),
                      journal=Journal())
    win.apply_snapshot(snap())

    wait_history(qapp, win)

    assert "histórico ilegível" in win.dashboard.last_operation.text()


def test_a_cpu_active_adopted_process_surfaces_as_investigation(qapp):
    proc = proc_info(700, comm="runaway", ppid=1, pgid=900, session=901,
                     starttime=5_000, cpu_frac=77.0, uid=os.getuid())
    win = make_window(sessions=_Sessions(), exclusions=_NoExclusions())

    win.apply_snapshot(snap(ts=1_000.0, procs=(proc,)))

    text = win.orphans.investigation_text()
    assert "pid 700" in text and "cpu 77%" in text
    assert "abandono não provado" in text
    assert win.orphans.rows() == [], "not offered as a terminable orphan"


def test_navigation_is_a_left_sidebar_with_horizontal_labels(window):
    from PySide6.QtWidgets import QTabWidget
    from folego.ui.main_window import SidebarTabBar
    assert window.tabs.tabPosition() == QTabWidget.TabPosition.West
    bar = window.tabs.tabBar()
    assert isinstance(bar, SidebarTabBar)
    hint = bar.tabSizeHint(0)
    assert hint.width() > hint.height(), "rótulo horizontal: aba mais larga que alta"
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())][0] == "central"


def test_widget_mode_opens_the_widget_and_folds_the_window_without_touching_kwin(qapp, monkeypatch):
    from folego.ui import kwin_rule
    calls = []
    monkeypatch.setattr(kwin_rule, "installed", lambda **kw: calls.append("installed") or False)
    monkeypatch.setattr(kwin_rule, "install", lambda *a, **kw: calls.append(("install", a, kw)) or {})
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    asked = []
    win = make_window(compact_factory=lambda view, caps: CompactWindow(view, caps=caps, store=_CompactStore()))
    win._widget_confirm = lambda title, text: asked.append(title) or False
    win._widget_settings = lambda: _CompactStore()
    win.show()
    win.tray.tray = object()  # a way back exists: the window may hide
    assert win.dashboard.widget_button.isVisible()
    win.dashboard.widget_button.click()
    assert win._compact.isVisible() and not win.isVisible()
    assert asked == ["Manter o widget em primeiro plano"]
    assert not any(isinstance(c, tuple) for c in calls), "recusar não cria regra"
    win._compact.open_button.click()
    assert win.isVisible() and not win._compact.isVisible()
    win._compact.force_close()


def test_accepting_the_offer_installs_the_rule_with_the_widget_title(qapp, monkeypatch):
    from folego.ui import kwin_rule
    installs = []
    monkeypatch.setattr(kwin_rule, "installed", lambda **kw: False)
    monkeypatch.setattr(kwin_rule, "install", lambda title, x, y, **kw: installs.append((title, kw)) or {})
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    win = make_window(compact_factory=lambda view, caps: CompactWindow(view, caps=caps, store=_CompactStore()))
    win._widget_confirm = lambda title, text: True
    win._widget_settings = lambda: _CompactStore()
    win.tray.tray = object()
    win.enter_widget_mode()
    assert installs == [("Fôlego — widget", {"confirmed": True})]
    win._compact.force_close()
