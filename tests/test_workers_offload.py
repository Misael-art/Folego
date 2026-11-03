"""F3.4: coleta fora da thread da UI, fila de um e modelos por diferença."""
import threading
import time

from PySide6.QtCore import QObject, Slot

from folego.core.snapshot import MemInfo, Snapshot
from folego.ui import workers


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
    def on_snapshot(self, snapshot):
        self.snapshots.append(snapshot)

    @Slot(str)
    def on_error(self, message):
        self.errors.append(message)


def wait_for(qapp, predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_offload_schedules_and_does_not_block_the_caller(qapp):
    started = threading.Event()
    gate = threading.Event()

    def slow():
        started.set()
        gate.wait(1.0)
        return tiny_snap()

    poller = workers.Poller(collect_fn=slow, offload=True)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    try:
        began = time.monotonic()
        poller.request()
        assert time.monotonic() - began < 0.1
        assert started.wait(0.5)
        assert spy.snapshots == [], "a UI não recebe antes do resultado"
        gate.set()
        assert wait_for(qapp, lambda: spy.snapshots)
        assert not spy.errors
    finally:
        poller.stop()


def test_at_most_one_collection_is_in_flight(qapp):
    started = threading.Event()
    gate = threading.Event()
    calls = []

    def slow():
        calls.append(1)
        started.set()
        gate.wait(1.0)
        return tiny_snap()

    poller = workers.Poller(collect_fn=slow, offload=True)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    try:
        poller.request()
        assert started.wait(0.5)
        poller.request()
        poller.request()
        gate.set()
        assert wait_for(qapp, lambda: spy.snapshots)
        assert len(calls) == 1, "ticks atrasados não formam fila"

        poller.request()
        assert wait_for(qapp, lambda: len(spy.snapshots) == 2)
        assert len(calls) == 2
    finally:
        poller.stop()


def test_errors_cross_the_queue_to_the_main_thread(qapp):
    def broken():
        raise RuntimeError("proc sumiu")

    poller = workers.Poller(collect_fn=broken, offload=True)
    spy = Spy()
    poller.error.connect(spy.on_error)
    try:
        poller.request()
        assert wait_for(qapp, lambda: spy.errors)
        assert spy.errors == ["RuntimeError: proc sumiu"]
    finally:
        poller.stop()


def test_pause_keeps_the_worker_alive_and_resume_collects_again(qapp):
    poller = workers.Poller(collect_fn=tiny_snap, offload=True)
    spy = Spy()
    poller.snapshot_ready.connect(spy.on_snapshot)
    try:
        poller.start()
        poller.pause()
        assert not poller._timer.isActive()
        assert not poller._drain_timer.isActive()
        assert poller._thread.is_alive(), "pausar não destrói o worker"

        poller.resume()
        assert poller._timer.isActive()
        assert wait_for(qapp, lambda: spy.snapshots)
    finally:
        poller.stop()


def test_resume_after_stop_does_nothing(qapp):
    poller = workers.Poller(collect_fn=tiny_snap, offload=True)
    poller.start()
    poller.stop()
    poller.resume()
    assert not poller._timer.isActive()
    assert not poller._drain_timer.isActive()


def test_stop_joins_the_worker_and_stops_the_timers(qapp):
    poller = workers.Poller(collect_fn=tiny_snap, offload=True)
    poller.start()
    poller.stop()
    assert not poller._timer.isActive()
    assert not poller._drain_timer.isActive()
    assert not poller._thread.is_alive()
