import time

from PySide6.QtCore import QObject, Qt, Slot

from deck_wellness.core.snapshot import MemInfo, Snapshot
from deck_wellness.ui import workers


def tiny_snap():
    return Snapshot(ts=0.0, mem=MemInfo(1000, 500), swap_used_kb=0,
                    swap_total_kb=0, pressure_memory=None, pressure_io=None,
                    pressure_cpu=None, load=None, apps=(), self_rss_kb=1)


class Spy(QObject):
    def __init__(self):
        super().__init__()
        self.snapshots = []
        self.errors = []

    @Slot(object)
    def on_snapshot(self, s):
        self.snapshots.append(s)

    @Slot(str)
    def on_error(self, m):
        self.errors.append(m)


def test_poll_once_emits_snapshot(qapp):
    poller = workers.Poller(collect_fn=tiny_snap)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    poller.poll_once()
    assert spy.snapshots and not spy.errors


def test_poll_once_reports_error_and_keeps_working(qapp):
    state = {"boom": True}

    def flaky():
        if state["boom"]:
            raise RuntimeError("proc gone")
        return tiny_snap()

    poller = workers.Poller(collect_fn=flaky)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    poller.error.connect(spy.on_error)
    poller.poll_once()
    assert spy.errors == ["RuntimeError: proc gone"] and not spy.snapshots
    state["boom"] = False
    poller.poll_once()  # loop survives a raising collect
    assert len(spy.snapshots) == 1


def test_timer_fires_repeatedly(qapp):
    calls = [0]

    def count():
        calls[0] += 1
        return tiny_snap()

    poller = workers.Poller(collect_fn=count, interval_s=0.01)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    poller.start()
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    poller.stop()
    assert len(spy.snapshots) >= 3
    qapp.processEvents()
