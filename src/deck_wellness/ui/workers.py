"""Polling harness on the Qt main thread.

Design note: we deliberately avoid Python-subclass QThreads here — PySide
6.11 on Python 3.14 has unreliable cross-thread signal delivery (observed
aborts with minimal repros). /proc+sys reads are memory-serviced syscalls
(milliseconds), safe on the event loop; any operation that *can* block on
real file trees goes through a subprocess instead (see process/runner).
"""
from PySide6.QtCore import QObject, Signal, Slot, QTimer


class Poller(QObject):
    snapshot_ready = Signal(object)
    error = Signal(str)

    def __init__(self, collect_fn, interval_s: float = 2.0, parent=None):
        super().__init__(parent)
        self._collect = collect_fn
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_s * 1000))
        self._timer.timeout.connect(self.poll_once)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    @Slot()
    def poll_once(self):
        try:
            snap = self._collect()
        except Exception as exc:  # a bad poll must never stop the loop
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.snapshot_ready.emit(snap)
