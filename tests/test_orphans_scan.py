"""Sampling for the headless path: two observations minimum, window honoured."""
from deck_wellness.actions.orphans.scan import scan_orphans
from deck_wellness.core.orphans import OrphanTracker
from fixtures_proc import proc_info, snapshot_of

IDLE = proc_info(500, comm="worker", ppid=1, pgid=900, session=901, uid=1000,
                 starttime=777, rss_kb=1234)


class FakeCollector:
    def __init__(self, *snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0

    def collect(self):
        snap = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return snap


def test_the_window_is_spent_between_observations():
    slept = []
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    collector = FakeCollector(snapshot_of(IDLE, ts=1_000.0),
                              snapshot_of(IDLE, ts=1_030.0))

    found = scan_orphans(collector, tracker=tracker, samples=3, window_s=20.0,
                        sleep=slept.append)

    assert slept == [10.0, 10.0]
    assert collector.calls == 3
    assert [c.pid for c in found] == [500]


def test_a_single_sample_never_sleeps_and_never_claims_idleness():
    slept = []
    tracker = OrphanTracker(min_idle_s=300.0, uid=1000, self_pid=10)

    found = scan_orphans(FakeCollector(snapshot_of(IDLE, ts=1_000.0)),
                         tracker=tracker, samples=1, window_s=300.0,
                         sleep=slept.append)

    assert slept == []
    assert found == ()


def test_a_busy_process_stays_out_even_over_a_long_window():
    from dataclasses import replace

    tracker = OrphanTracker(min_idle_s=300.0, uid=1000, self_pid=10)
    busy = replace(IDLE, utime=100)
    later = replace(IDLE, utime=400)
    collector = FakeCollector(snapshot_of(busy, ts=1_000.0),
                             snapshot_of(later, ts=2_000.0))

    found = scan_orphans(collector, tracker=tracker, samples=2, window_s=1_000.0,
                        sleep=lambda _s: None)

    assert found == ()
