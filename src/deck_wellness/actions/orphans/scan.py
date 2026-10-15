"""M4 CLI-side sampling: idleness is only provable across time.

A one-shot process cannot claim "idle for 5 minutes" without having watched for
5 minutes, so the window and the threshold are both explicit here.
"""
import time

from ...core.collector import MetricsCollector
from ...core.orphans import OrphanTracker


def scan_orphans(collector, *, tracker: OrphanTracker | None = None, samples: int = 2,
                 window_s: float = 10.0, sleep=time.sleep) -> tuple:
    tracker = tracker or OrphanTracker()
    step = window_s / (samples - 1) if samples > 1 else 0.0
    collect = getattr(collector, "collect", None) or collector
    found: tuple = ()
    for index in range(samples):
        if index:
            sleep(step)
        found = tracker.observe(collect())
    return found


def collector_for(proc_root=None) -> MetricsCollector:
    return MetricsCollector(proc_root=proc_root)
