"""Polling harness: collection can run off the Qt main thread.

A Python worker thread with two queues is used instead of QThread: PySide 6.11
on Python 3.14 showed unreliable cross-thread signal delivery, so the worker
never touches Qt. It only puts results in a queue; a QTimer on the main thread
drains it and emits signals there. At most one collection is in flight, so a slow
/proc scan cannot build a backlog or freeze the event loop.

`offload=False` keeps the historical synchronous `poll_once()` contract used by
small utilities and tests. The window starts the poller with `offload=True`.
"""
import queue
import threading

from PySide6.QtCore import QObject, Signal, Slot, QTimer


class Poller(QObject):
    snapshot_ready = Signal(object)
    error = Signal(str)

    def __init__(self, collect_fn, interval_s: float = 2.0, parent=None, *,
                 offload: bool = False, drain_ms: int = 50):
        super().__init__(parent)
        self._collect = collect_fn
        self._offload = offload
        self._inflight = False
        self._stop = threading.Event()
        self._requests: queue.Queue = queue.Queue(maxsize=1)
        self._results: queue.Queue = queue.Queue()
        self._thread = None
        if offload:
            self._thread = threading.Thread(
                target=self._work, name="folego-collector", daemon=True)
            self._thread.start()

        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_s * 1000))
        # `poll_once()` keeps its historical synchronous contract; the periodic
        # tick uses `request()` when offloading, so the event loop never waits.
        self._timer.timeout.connect(self.request if offload else self.poll_once)
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(drain_ms)
        self._drain_timer.timeout.connect(self.drain)

    # ------------------------------------------------------------------ worker

    def _work(self):
        while not self._stop.is_set():
            try:
                self._requests.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._stop.is_set():
                return
            try:
                result = ("ok", self._collect())
            except BaseException as exc:  # a bad poll must never kill the worker
                result = ("error", f"{type(exc).__name__}: {exc}")
            self._results.put(result)

    @Slot()
    def drain(self):
        while True:
            try:
                kind, payload = self._results.get_nowait()
            except queue.Empty:
                return
            self._inflight = False
            if kind == "ok":
                self.snapshot_ready.emit(payload)
            else:
                self.error.emit(payload)

    # ---------------------------------------------------------------- lifecycle

    def start(self):
        self._timer.start()
        if self._offload:
            self._drain_timer.start()

    def pause(self):
        """Stop polling without tearing the worker down: resume() is real."""
        self._timer.stop()
        if self._offload:
            self._drain_timer.stop()

    def resume(self):
        if self._stop.is_set():
            return
        self._timer.start()
        if self._offload:
            self._drain_timer.start()
        self.request()

    def stop(self):
        self._timer.stop()
        if not self._offload:
            return
        self._drain_timer.stop()
        self._stop.set()
        try:
            self._requests.put_nowait(True)  # acorda o worker sem bloquear
        except queue.Full:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.2)

    @Slot()
    def poll_once(self):
        """Collect on the caller thread. Kept synchronous for utilities/tests."""
        self._collect_once()

    @Slot()
    def request(self):
        if not self._offload:
            self.poll_once()
            return
        # fila de um: enquanto uma coleta não volta, o próximo tick é ignorado.
        if self._inflight:
            return
        if not self._drain_timer.isActive():
            self._drain_timer.start()  # request manual também entrega o resultado
        try:
            self._requests.put_nowait(True)
        except queue.Full:
            return
        self._inflight = True

    def _collect_once(self):
        try:
            snap = self._collect()
        except Exception as exc:  # a bad poll must never stop the loop
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.snapshot_ready.emit(snap)
