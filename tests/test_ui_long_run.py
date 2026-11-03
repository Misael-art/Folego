"""F8 synthetic soak: repeated snapshots must not grow widgets, samples or jobs.

The 20 000-cycle run lives in ``tools/soak.py`` and measures RSS; this bounded
version runs inside the suite (isolated stores, no system reads) so a widget leak
like the one the F8 soak found fails on the next commit instead of months later.
"""
import pytest

from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from folego.core.tmpfs import TmpfsVolume
from folego.ui.tmpfs_tab import SAMPLES_KEPT

from fixtures_automation import stores

pytest.importorskip("PySide6")

GIB = 1024 ** 3
CYCLES = 1500


class _Jobs:
    def __init__(self):
        self.procs = []

    def run(self, *args, **kwargs):
        raise AssertionError("o ensaio não dispara atos")

    def shutdown(self):
        pass


class _Sessions:
    def snapshot(self):
        return ()


class _Exclusions:
    def list(self):
        return ()


class _Journal:
    def load(self):
        return [], []


def snap(i):
    used = 5 * GIB + (i % 100) * 16 * 1024 * 1024
    return Snapshot(
        ts=1_700_000_000.0 + i * 2,
        mem=MemInfo(14_374_304, 5_000_000 + (i % 50) * 100),
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(float(i % 20), 0, 0, 0),
        pressure_io=None, pressure_cpu=None, load=None,
        apps=(AppRSS("edge", 900 * 1024 + (i % 30) * 1024, 20),),
        self_rss_kb=90_000,
        tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
        mono=1000.0 + i * 2, sources=())


def _pump(app):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    app.processEvents()


def test_repeated_snapshots_do_not_grow_widgets_samples_or_jobs(qapp):
    from PySide6.QtWidgets import QApplication

    from folego.ui.main_window import MainWindow

    config_store, grant_store = stores()
    jobs = _Jobs()
    window = MainWindow(
        collector_factory=None, jobs=jobs, disk_jobs=jobs, tmpfs_jobs=jobs,
        sessions=_Sessions(), exclusions=_Exclusions(), journal=_Journal(),
        config_store=config_store, grant_store=grant_store)
    window.show()
    window.apply_snapshot(snap(0))
    _pump(qapp)
    widgets_before = len(QApplication.allWidgets())

    for i in range(CYCLES):
        window.apply_snapshot(snap(i))
        if i % 500 == 0:
            _pump(qapp)
    _pump(qapp)

    assert len(window.tmpfs._samples["/tmp"]) == SAMPLES_KEPT
    assert window.tmpfs.volume_table.rowCount() == 1
    assert len(jobs.procs) == 0
    widgets_after = len(QApplication.allWidgets())
    assert widgets_after - widgets_before <= 10, (
        f"widgets cresceram de {widgets_before} para {widgets_after} em "
        f"{CYCLES} amostras")
    window.close()
