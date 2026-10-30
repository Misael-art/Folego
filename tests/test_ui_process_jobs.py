import json
import sys
import time

from PySide6.QtCore import QTimer

from folego.core.orphans import OrphanCandidate
from folego.core.snapshot import MemInfo, Snapshot
from folego.orchestration import ActionPlan
from folego.ui.main_window import MainWindow, process_argv
from folego.ui.tune_jobs import TuneJobs


class NoJobs:
    def run(self, *args, **kwargs):
        raise AssertionError("unrelated work must not run")
    def shutdown(self):
        pass


def test_process_child_does_not_block_gui_and_double_click_starts_once(qapp, fake_home):
    captured, ticks = [], []
    result = {"ok": True, "outcome": "sucesso", "effects": {"results": [
        {"pid": 500, "comm": "fixture-worker", "ok": True, "signal": 15,
         "reason": None, "exited": True, "identity": "pidfd"}]}}
    def argv(action, serialized, confirm):
        plan = ActionPlan.from_dict(json.loads(serialized))
        captured.append(plan)
        actual = process_argv(action, serialized, confirm)
        assert actual[-1] == "--confirmar" and "--forcar" not in actual
        return [sys.executable, "-c", "import time; time.sleep(.3); print(" + repr(json.dumps(result)) + ")"]
    jobs = TuneJobs(argv_factory=argv)
    view = MainWindow(collector_factory=None, jobs=NoJobs(), disk_jobs=NoJobs(),
                      tmpfs_jobs=NoJobs(), process_jobs=jobs, confirm_fn=lambda text: True)
    snapshot = Snapshot(ts=time.time(), mono=time.monotonic(), boot_id="fixture-boot",
        mem=MemInfo(1000, 800), swap_used_kb=0, swap_total_kb=0, pressure_memory=None,
        pressure_io=None, pressure_cpu=None, load=None, apps=(), self_rss_kb=1)
    view.apply_snapshot(snapshot)
    candidate = OrphanCandidate(500, "fixture-worker", "S", 1000, 1, 0, 777, 100, cpu_ticks=150)
    view.orphans.show_candidates([candidate])
    view.orphans.select(0)
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    try:
        view.orphans.terminate_clicked()
        view.orphans.terminate_clicked()
        assert view.orphans._pending is not None
        view.orphans.show_candidates([candidate])
        view.orphans.show_groups([])
        assert "aguardando acompanhamento" in view.orphans.status()
        assert len(captured) == 1 and captured[0].target.detail["boot_id"] == "fixture-boot"
        deadline = time.monotonic() + 5
        while view.orphans._pending is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.005)
        assert len(ticks) >= 3
        assert view.orphans._pending is None
        assert "encerrado" in view.orphans.status()
        assert jobs.procs == []
    finally:
        timer.stop()
        view.close()


def test_unknown_process_result_never_offers_blind_force(qapp, fake_home):
    from concurrent.futures import Future
    from folego.ui.orphans_panel import OrphansPanel
    pending = Future()
    panel = OrphansPanel()
    panel._after(pending, [], sigterm=True)
    pending.set_result({"outcome": "desconhecido", "operation_id": "stable-id",
                        "reason": "worker interrupted"})
    deadline = time.monotonic() + 2
    while panel._pending is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert "stable-id" in panel.status() and "não repetir" in panel.status()
    assert panel.survivors() == [] and not panel.force_button.isEnabled()
    panel.show_candidates([])
    panel.show_groups([])
    panel.terminate_clicked()
    panel.force_clicked()
    panel.group_clicked()
    assert "stable-id" in panel.status() and "não repetir" in panel.status()
    assert not panel.term_button.isEnabled() and not panel.group_button.isEnabled()


def test_malformed_child_result_is_unknown_instead_of_crashing_the_ui(qapp):
    from concurrent.futures import Future
    from folego.ui.orphans_panel import OrphansPanel
    pending = Future()
    panel = OrphansPanel()
    panel._after(pending, [], sigterm=True)
    pending.set_result({"outcome": "sucesso", "operation_id": "malformed-id",
                        "effects": {"results": [None]}})
    deadline = time.monotonic() + 2
    while panel._pending is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert "desconhecido" in panel.status()
    assert "malformed-id" in panel.status()
    assert not panel.term_button.isEnabled()
