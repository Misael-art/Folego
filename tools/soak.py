#!/usr/bin/env python3
"""Synthetic long-run probe: fixed window, repeated snapshots, bounded state.

This is evidence for F8, not a substitute for a real-session soak. It uses an
isolated HOME/XDG and fake collectors/jobs, drives the real MainWindow offscreen
without starting a poller, and reports RSS/widget/sample growth. No system
process, project, container or user state is read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# roda do checkout sem depender de PYTHONPATH; instalado, o import normal vence.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STATE = tempfile.mkdtemp(prefix="folego-soak-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = STATE
os.environ["XDG_CONFIG_HOME"] = os.path.join(STATE, ".config")
os.environ["XDG_DATA_HOME"] = os.path.join(STATE, ".local", "share")
os.environ["XDG_STATE_HOME"] = os.path.join(STATE, ".local", "state")
os.environ.pop("DECKWELLNESS_PROC_ROOT", None)
os.environ.pop("DECKWELLNESS_SYS_ROOT", None)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot  # noqa: E402
from folego.core.tmpfs import TmpfsVolume  # noqa: E402
from folego.ui.main_window import MainWindow  # noqa: E402
from folego.ui.tmpfs_tab import SAMPLES_KEPT  # noqa: E402

MIB = 1024 ** 2


class _Jobs:
    def __init__(self):
        self.procs = []
        self.in_flight = 0

    def run(self, *args, **kwargs):
        raise AssertionError("soak não dispara atos")

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


class _Config:
    def read(self):
        return type("C", (), {"mode": "manual", "preset": "equilibrado",
                              "paused": False, "updated_at": 0.0})()


class _Grants:
    def for_action(self, action, **kwargs):
        return []


def pump(app) -> None:
    """One real event-loop turn so ``deleteLater`` runs as in the application."""
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    app.processEvents()


def rss_kb() -> int:
    with open("/proc/self/status", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def snapshot(i: int, total_kb: int = 14_374_304) -> Snapshot:
    used = 7 * 1024 ** 3 + (i % 200) * MIB
    return Snapshot(
        ts=1_700_000_000.0 + i * 2,
        mem=MemInfo(total_kb, 5_000_000 + (i % 50) * 100),
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(i % 20, 0, 0, 0),
        pressure_io=None, pressure_cpu=None, load=None,
        apps=(AppRSS("edge", 900 * 1024 + (i % 30) * 1024, 20),
              AppRSS("codex", 120 * 1024, 3)),
        self_rss_kb=90_000,
        tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * 1024 ** 3, used,
                           8 * 1024 ** 3 - used),),
        mono=1000.0 + i * 2,
        sources=(),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=20_000)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    jobs = _Jobs()
    window = MainWindow(
        collector_factory=None, jobs=jobs, disk_jobs=jobs, tmpfs_jobs=jobs,
        sessions=_Sessions(), exclusions=_Exclusions(), journal=_Journal(),
        config_store=_Config(), grant_store=_Grants())
    window.show()
    pump(app)

    rss_start = rss_kb()
    for i in range(args.cycles):
        window.apply_snapshot(snapshot(i))
        if i % 500 == 0:
            pump(app)
    pump(app)
    widgets_end = len(QApplication.allWidgets())
    samples = sum(len(series) for series in window.tmpfs._samples.values())
    report = {
        "cycles": args.cycles,
        "rss_start_kb": rss_start,
        "rss_end_kb": rss_kb(),
        "rss_growth_kb": rss_kb() - rss_start,
        "widgets_end": widgets_end,
        "samples": samples,
        "samples_cap": SAMPLES_KEPT,
        "volume_rows": len(window.tmpfs.volume_rows),
        "suggestion_rows": len(window.dashboard.rows),
        "child_procs": len(jobs.procs),
        "window_visible": window.isVisible(),
    }
    window.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))

    if report["rss_growth_kb"] > 64 * 1024:
        print("FAIL: crescimento de RSS acima de 64 MiB", file=sys.stderr)
        return 1
    if report["samples"] > SAMPLES_KEPT or report["volume_rows"] != 1:
        print("FAIL: estado de amostras/linhas cresceu sem limite", file=sys.stderr)
        return 1
    if report["child_procs"] != 0:
        print("FAIL: QProcess retido após o ensaio", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
