"""Main window: five tabs, one title-bar signal, and the polling that feeds them.

The window owns the poller, the orphan tracker and the three child-process layers
(tunings, the disk plan and the tmpfs plan); every tab receives plain data and
calls back here when the user confirms an act. The Reaper stays lazy and the
tunings tab is never consulted on its own: opening the window must never be
enough to write a byte or signal a process.
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget

from . import title_signal
from .dashboard_tab import DashboardTab
from .disk_tab import DiskTab, plan_argv
from .orphans_panel import OrphansPanel
from .tmpfs_tab import TmpfsTab, argv_for
from .tray import Tray
from .tune_jobs import TuneJobs
from .tunings_tab import TuningsTab
from ..core.orphans import OrphanTracker, group_targets

# tab title -> the attribute the dashboard's "Ir para …" jumps to
TABS = (("memória", "dashboard"), ("ajustes", "tunings"),
        ("órfãos", "orphans"), ("disco", "disk"), ("temporários", "tmpfs"))
JUMPS = {"memoria": "dashboard", "ajustes": "tunings", "orfaos": "orphans",
         "disco": "disk"}
DISK_TIMEOUT_MS = 120_000  # the real cache walk took 54,7 s on this Deck (M3 log)
TMPFS_TIMEOUT_MS = 45_000  # três volumes × o prazo de varredura de 10 s, com folga


class MainWindow(QMainWindow):
    def __init__(self, collector_factory=None,
                 thresholds: title_signal.Thresholds | None = None,
                 *, tracker: OrphanTracker | None = None, reaper_factory=None,
                 confirm_fn=None, jobs=None, disk_jobs=None, tmpfs_jobs=None):
        super().__init__()
        self._thresholds = thresholds or title_signal.Thresholds()
        self.resize(900, 620)
        self._tracker = tracker or OrphanTracker()
        self._reaper_factory = reaper_factory or _default_reaper
        self._reaper = None
        self._collector_factory = collector_factory
        self._poller = None
        self._quitting = False
        self._tray_note = ""
        self._jobs = jobs if jobs is not None else TuneJobs(parent=self)
        self._disk_jobs = disk_jobs if disk_jobs is not None else TuneJobs(
            parent=self, argv_factory=plan_argv, timeout_ms=DISK_TIMEOUT_MS)
        self._tmpfs_jobs = tmpfs_jobs if tmpfs_jobs is not None else TuneJobs(
            parent=self, argv_factory=argv_for, timeout_ms=TMPFS_TIMEOUT_MS)

        self.dashboard = DashboardTab(on_jump=self.jump_to, thresholds=self._thresholds)
        self.tunings = TuningsTab(jobs=self._jobs, confirm_fn=confirm_fn)
        self.orphans = OrphansPanel(confirm_fn=confirm_fn,
                                    on_terminate=self._terminate,
                                    on_force=self._force,
                                    on_group=self._group)
        self.disk = DiskTab(jobs=self._disk_jobs)
        self.tmpfs = TmpfsTab(jobs=self._tmpfs_jobs, confirm_fn=confirm_fn)

        self.tabs = QTabWidget()
        for title, attribute in TABS:
            self.tabs.addTab(getattr(self, attribute), title)
        self.setCentralWidget(self.tabs)

        self.tray = Tray(self, thresholds=self._thresholds)

    # -------------------------------------------------------------------- polling

    def start(self):
        if self._collector_factory is None or self._poller is not None:
            return
        if not self.tray.install():
            self._tray_note = self.tray.fallback
        from .workers import Poller
        collector = self._collector_factory()
        collect_fn = getattr(collector, "collect", None) or collector
        self._poller = Poller(collect_fn=collect_fn)
        self._poller.snapshot_ready.connect(self.apply_snapshot)
        self._poller.error.connect(self.show_error)
        self._poller.start()

    def show_error(self, message: str):
        self.dashboard.status.setText(f"⚠ última falha de coleta: {message}")

    def apply_snapshot(self, snapshot):
        self.setWindowTitle(title_signal.compute(snapshot, self._thresholds).text)
        candidates = self._tracker.observe(snapshot)
        self.orphans.show_candidates(candidates)
        self.orphans.show_groups(group_targets(snapshot.procs))
        notes = (self._tray_note,) if self._tray_note else ()
        self.dashboard.show_snapshot(snapshot, orphan_count=len(candidates),
                                     thumbnails_kb=self.disk.thumbnails_kb,
                                     extra_notes=notes)
        self.tmpfs.show_volumes(snapshot.tmpfs, ts=snapshot.ts)
        if self.tray.tray is not None:
            self.tray.show_snapshot(snapshot)

    # ------------------------------------------------------- navigation and lifetime

    def jump_to(self, target: str):
        attribute = JUMPS.get(target)
        if attribute is not None:
            self.tabs.setCurrentWidget(getattr(self, attribute))

    def raise_to_user(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def quit(self):
        """The tray menu's way out: stop watching, take the children down."""
        self._quitting = True
        self.close()

    # ----------------------------------------------------------------------- acts

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
        if self._quitting or self.tray.tray is None:
            if self._poller is not None:
                self._poller.stop()
            self._jobs.shutdown()
            self._disk_jobs.shutdown()
            self._tmpfs_jobs.shutdown()
            super().closeEvent(event)
            return
        # a live icon means the signal is resident: hide the window, keep watching
        event.ignore()
        self.hide()


def _default_reaper():
    from ..actions.orphans.reaper import Reaper
    from ..safely.audit import AuditLog
    return Reaper(audit=AuditLog())
