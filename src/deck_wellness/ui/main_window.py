"""Main window: live RAM signal in the title bar + the M4 orphan/group panel.

The window owns the polling and the tracker; the panel only receives data and
calls back here when the user confirms an act. The Reaper is created lazily —
opening the window must never be enough to be able to signal a process.
"""
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from . import title_signal
from .orphans_panel import OrphansPanel
from ..core.orphans import OrphanTracker, group_targets


class MainWindow(QMainWindow):
    def __init__(self, collector_factory=None, thresholds: title_signal.Thresholds | None = None,
                 *, tracker: OrphanTracker | None = None, reaper_factory=None,
                 confirm_fn=None):
        super().__init__()
        self._thresholds = thresholds or title_signal.Thresholds()
        self.resize(760, 520)
        self._label = QLabel("Aguardando primeira leitura…")
        self._label.base_text = "Aguardando primeira leitura…"
        self._tracker = tracker or OrphanTracker()
        self._reaper_factory = reaper_factory or _default_reaper
        self._reaper = None
        self.orphans = OrphansPanel(confirm_fn=confirm_fn,
                                    on_terminate=self._terminate,
                                    on_force=self._force,
                                    on_group=self._group)

        host = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self._label)
        layout.addWidget(self.orphans)
        host.setLayout(layout)
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

    def apply_snapshot(self, snapshot):
        sig = title_signal.compute(snapshot, self._thresholds)
        self.setWindowTitle(sig.text)
        self._last_error = None
        top = ", ".join(f"{a.group} {a.rss_kb // 1024} MB" for a in snapshot.apps[:5])
        swap = snapshot.swap_used_kb // 1048576
        base = (f"{sig.text}\nswap/zram: {swap} GB usados\ntop apps (RSS): {top or '—'}")
        self._label.base_text = base
        self._label.setText(base)
        self.orphans.show_candidates(self._tracker.observe(snapshot))
        self.orphans.show_groups(group_targets(snapshot.procs))

    # ------------------------------------------------------------------ acts

    def _reaper_or_new(self):
        if self._reaper is None:
            self._reaper = self._reaper_factory()
        return self._reaper

    def _terminate(self, candidates):
        reaper = self._reaper_or_new()
        return [reaper.terminate(c) for c in candidates]

    def _force(self, candidates, confirm=False, require_orphan=True):
        reaper = self._reaper_or_new()
        return [reaper.force(c, confirm=confirm, require_orphan=require_orphan)
                for c in candidates]

    def _group(self, target, confirm=False):
        return self._reaper_or_new().terminate_group(target)

    def closeEvent(self, event):
        if self._poller is not None:
            self._poller.stop()
        super().closeEvent(event)


def _default_reaper():
    from ..actions.orphans.reaper import Reaper
    from ..safely.audit import AuditLog
    return Reaper(audit=AuditLog())
