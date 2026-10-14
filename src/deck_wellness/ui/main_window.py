"""Main window (M1): live RAM signal in the title bar + simple readout.

Tabs/tray arrive in M3; no action mutates the system from this window yet.
"""
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from . import title_signal
from ..core.snapshot import Snapshot


class MainWindow(QMainWindow):
    def __init__(self, collector_factory=None, thresholds: title_signal.Thresholds | None = None):
        super().__init__()
        self._thresholds = thresholds or title_signal.Thresholds()
        self.resize(640, 400)
        self._label = QLabel("Aguardando primeira leitura…")
        self._label.base_text = "Aguardando primeira leitura…"
        host = QWidget()
        host.setLayout(QVBoxLayout())
        host.layout().addWidget(self._label)
        self.setCentralWidget(host)
        self._poller = None
        self._collector_factory = collector_factory

    def start(self):
        if self._collector_factory is None or self._poller is not None:
            return
        from .workers import Poller
        collector = self._collector_factory()
        collect_fn = getattr(collector, "collect", None) or collector
        self._poller = Poller(collect_fn=collect_fn)
        self._poller.snapshot_ready.connect(self.apply_snapshot)
        self._poller.error.connect(self.show_error)
        self._poller.start()

    def show_error(self, message: str):
        self._last_error = message
        self._label.setText(f"⚠ última falha de coleta: {message}\n\n{self._label.base_text}")

    def apply_snapshot(self, snapshot: Snapshot):
        sig = title_signal.compute(snapshot, self._thresholds)
        self.setWindowTitle(sig.text)
        self._last_error = None
        top = ", ".join(f"{a.group} {a.rss_kb // 1024} MB" for a in snapshot.apps[:5])
        swap = snapshot.swap_used_kb // 1048576
        base = (f"{sig.text}\nswap/zram: {swap} GB usados\ntop apps (RSS): {top or '—'}")
        self._label.base_text = base
        self._label.setText(base)

    def closeEvent(self, event):
        if self._poller is not None:
            self._poller.stop()
        super().closeEvent(event)
