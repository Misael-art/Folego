"""M4 core: which processes are *provably* safe to offer for termination.

Two surfaces: proven orphans (reaped one by one) and whole browser groups
(reaped as a unit, high yield). Both must refuse the strong pre-list.
"""
from dataclasses import replace

import pytest

from folego.core.orphans import OrphanTracker, group_targets, is_protected
from fixtures_proc import proc_info, snapshot_of

MIN_IDLE = 300.0


def orphan(pid=500, **kw):
    """A reparented, non-leader, idle process owned by us."""
    base = dict(comm="worker", state="S", ppid=1, pgid=900, session=901,
                uid=1000, starttime=777, rss_kb=200_000)
    base.update(kw)
    return proc_info(pid, **base)


def track(*procs, ts=1_000.0, **kw):
    tracker = OrphanTracker(**kw)
    return tracker, tracker.observe(snapshot_of(*procs, ts=ts))


# ---------------------------------------------------------------- proven orphans

def test_a_fresh_orphan_is_not_offered_until_it_has_been_idle():
    _, candidates = track(orphan(), uid=1000, self_pid=10)

    assert candidates == (), "idle time must be observed, not assumed"


def test_an_orphan_with_frozen_cpu_becomes_a_candidate_after_min_idle():
    tracker = OrphanTracker(min_idle_s=MIN_IDLE, uid=1000, self_pid=10)
    p = orphan()
    tracker.observe(snapshot_of(p, ts=1_000.0))

    found = tracker.observe(snapshot_of(p, ts=1_000.0 + MIN_IDLE + 1))

    assert [c.pid for c in found] == [500]
    assert found[0].rss_kb == 200_000
    assert found[0].starttime == 777
    assert found[0].idle_s >= MIN_IDLE


def test_cpu_that_keeps_advancing_is_never_an_orphan():
    tracker = OrphanTracker(min_idle_s=MIN_IDLE, uid=1000, self_pid=10)
    p = orphan()
    tracker.observe(snapshot_of(p, ts=1_000.0))

    busy = replace(p, utime=p.utime + 100)
    later = tracker.observe(snapshot_of(busy, ts=1_000.0 + MIN_IDLE + 1))

    assert later == ()
    stopped = tracker.observe(snapshot_of(busy, ts=1_000.0 + 2 * MIN_IDLE + 2))
    assert [c.pid for c in stopped] == [500], "idle clock restarts when CPU stops"


def test_a_reaped_process_that_grows_a_parent_again_is_dropped():
    tracker = OrphanTracker(min_idle_s=MIN_IDLE, uid=1000, self_pid=10)
    p = orphan()
    tracker.observe(snapshot_of(p, ts=1_000.0))
    assert tracker.observe(snapshot_of(p, ts=1_000.0 + MIN_IDLE + 1))

    adopted = tracker.observe(snapshot_of(replace(p, ppid=42),
                                          ts=1_000.0 + MIN_IDLE + 2))

    assert adopted == ()


def test_pid_that_disappears_is_forgotten():
    tracker = OrphanTracker(min_idle_s=MIN_IDLE, uid=1000, self_pid=10)
    p = orphan()
    tracker.observe(snapshot_of(p, ts=1_000.0))
    tracker.observe(snapshot_of(p, ts=1_000.0 + MIN_IDLE + 1))

    assert tracker.observe(snapshot_of(ts=1_000.0 + MIN_IDLE + 2)) == ()


@pytest.mark.parametrize("kw,why", [
    (dict(ppid=40), "has a live parent"),
    (dict(uid=0), "belongs to another user"),
    (dict(pgid=500), "is a process-group leader"),
    (dict(session=500), "is a session leader"),
])
def test_only_true_orphans_qualify(kw, why):
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    p = orphan(**kw)
    tracker.observe(snapshot_of(p, ts=1_000.0))

    assert tracker.observe(snapshot_of(p, ts=2_000.0)) == (), why


# ------------------------------------------- adoption by the session supervisor
# Measured on the Deck on 2026-10-14: systemd --user is a child subreaper, so a
# leftover whose launcher died is adopted by pid 1855 and never reaches PID 1.
# Demanding ppid == 1 made the app announce "sem órfãos" while leftovers piled up.

SUPERVISOR = proc_info(1855, comm="systemd", ppid=1, pgid=1855, session=1855, uid=1000)


def test_a_process_adopted_by_the_session_supervisor_is_an_orphan():
    leftover = orphan(ppid=1855, pgid=900, session=901)
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    tracker.observe(snapshot_of(SUPERVISOR, leftover, ts=1_000.0))

    found = tracker.observe(snapshot_of(SUPERVISOR, leftover, ts=2_000.0))

    assert [c.pid for c in found] == [500]
    assert found[0].ppid == 1855, "the row must say who adopted it"


def test_a_live_app_under_the_supervisor_is_not_offered_while_it_works():
    """Measured on the Deck: the user's MT5 terminal advances CPU (19 ticks/8 s)
    after its wine launcher exits, so it looks adopted — and the frozen-CPU proof
    is what keeps a running application out of the list."""
    app = orphan(ppid=1855, pgid=900, session=901, utime=2_342)
    tracker = OrphanTracker(uid=1000, self_pid=10)
    tracker.observe(snapshot_of(SUPERVISOR, app, ts=1_000.0))

    found = tracker.observe(snapshot_of(SUPERVISOR, replace(app, utime=2_361),
                                        ts=1_000.0 + MIN_IDLE + 8))

    assert found == (), "working, not idle: the idle clock restarted at this reading"


def test_a_process_running_inside_the_supervisor_session_is_not_a_leftover():
    supervised = orphan(ppid=1855, pgid=1855, session=1855)
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    tracker.observe(snapshot_of(SUPERVISOR, supervised, ts=1_000.0))

    found = tracker.observe(snapshot_of(SUPERVISOR, supervised, ts=2_000.0))

    assert found == (), "same session as its parent: it was started there, not adopted"


def test_a_child_of_a_still_live_plain_parent_is_not_an_orphan():
    launcher = proc_info(40, comm="bash", ppid=1855, pgid=40, session=40, uid=1000)
    child = orphan(ppid=40, pgid=40, session=40)
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    tracker.observe(snapshot_of(SUPERVISOR, launcher, child, ts=1_000.0))

    found = tracker.observe(snapshot_of(SUPERVISOR, launcher, child, ts=2_000.0))

    assert found == (), "its parent is alive and is not a supervisor"


def test_a_supervisor_with_live_children_is_never_offered():
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    supervisor = orphan()
    child = orphan(600, ppid=500)
    stray = orphan(601)
    procs = (supervisor, child, stray)
    tracker.observe(snapshot_of(*procs, ts=1_000.0))

    found = tracker.observe(snapshot_of(*procs, ts=2_000.0))

    assert [c.pid for c in found] == [601], (
        "500 has a live child (killing it cascades), 600 has a live parent")


def test_zombie_children_do_not_count_as_live():
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    parent = orphan()
    zombie = orphan(600, ppid=500, state="Z")
    tracker.observe(snapshot_of(parent, zombie, ts=1_000.0))

    found = tracker.observe(snapshot_of(parent, zombie, ts=2_000.0))

    assert [c.pid for c in found] == [500], "a zombie is already dead; it must not shield its parent"


def test_a_zombie_is_not_offered_because_it_cannot_be_killed():
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    p = orphan(state="Z")
    tracker.observe(snapshot_of(p, ts=1_000.0))

    assert tracker.observe(snapshot_of(p, ts=2_000.0)) == ()


def test_reused_pid_starts_the_idle_clock_over():
    tracker = OrphanTracker(min_idle_s=MIN_IDLE, uid=1000, self_pid=10)
    p = orphan()
    tracker.observe(snapshot_of(p, ts=1_000.0))
    tracker.observe(snapshot_of(p, ts=1_000.0 + MIN_IDLE + 1))

    impostor = replace(p, starttime=p.starttime + 9_999)
    found = tracker.observe(snapshot_of(impostor, ts=1_000.0 + MIN_IDLE + 2))

    assert found == (), "same pid, different birth: a new process, not the idle one"


PROTECTED = ["systemd", "systemd-userd", "plasmashell", "kwin_x11", "pipewire",
             "wireplumber", "dbus-daemon", "xdg-dbus-proxy", "bwrap",
             "chrome_crashpad", "xsettingsd", "polkitd", "Xwayland", "sddm",
             "konsole", "yakuake", "yad", "folego",
             # seen orphaned on the real Deck (census 2026-10-14): a D-Bus-activated
             # session service that respawned nothing and whose loss breaks the wallet
             "ksecretd", "kwalletd6", "kded5"]


@pytest.mark.parametrize("comm", PROTECTED)
def test_the_strong_pre_list_survives_every_orphan_rule(comm):
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    p = orphan(comm=comm)
    tracker.observe(snapshot_of(p, ts=1_000.0))

    assert tracker.observe(snapshot_of(p, ts=2_000.0)) == (), comm
    assert is_protected(p, self_pid=10, ancestor_pids=frozenset())


def test_our_own_ancestors_are_protected():
    init = proc_info(1, comm="systemd", ppid=0, uid=0)
    session = proc_info(10, comm="systemd-userd", ppid=1, uid=1000, pgid=10, session=10)
    shell = proc_info(20, comm="bash", ppid=10, uid=1000, pgid=20, session=20)
    app = proc_info(30, comm="folego", ppid=20, uid=1000, pgid=30, session=30)
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=30)
    tracker.observe(snapshot_of(init, session, shell, app, ts=1_000.0))

    found = tracker.observe(snapshot_of(init, session, shell, app, ts=2_000.0))

    assert found == ()
    assert is_protected(shell, self_pid=30, ancestor_pids=frozenset({1, 10, 20}))


def test_an_unrelated_idle_orphan_still_shows_up_next_to_protected_ones():
    tracker = OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10)
    procs = (orphan(comm="plasmashell"), orphan(611, comm="esquecido"),
             orphan(612, comm="systemd-userd"))
    tracker.observe(snapshot_of(*procs, ts=1_000.0))

    found = tracker.observe(snapshot_of(*procs, ts=2_000.0))

    assert [c.pid for c in found] == [611]


# ---------------------------------------------------------------- group targets

def edge(pid, **kw):
    base = dict(comm="msedge", ppid=400, uid=1000, rss_kb=400_000,
                pgid=400, session=401)
    base.update(kw)
    return proc_info(pid, **base)


def test_group_mode_offers_the_whole_browser_without_orphan_rules():
    members = [edge(400, pgid=400, session=400, ppid=10),
               edge(401, comm="msedge --type=gpu-process", ppid=400, rss_kb=90_000),
               edge(402, comm="msedge", ppid=400, rss_kb=60_000)]

    targets = group_targets(members, uid=1000, self_pid=10)

    assert [t.group for t in targets] == ["edge"]
    assert targets[0].total_rss_kb == 550_000
    assert [m.pid for m in targets[0].members] == [402, 401, 400], "children first"
    assert targets[0].label == "Microsoft Edge"


def test_group_mode_includes_the_browsers_but_not_the_automation_shell():
    """chrome-headless-shell is the Playwright/selenium binary, not the user's
    window: on the Deck 18 of 21 "Chrome family" processes were agent tooling."""
    members = [proc_info(700, comm="chrome", uid=1000, ppid=10, pgid=700,
                         session=700, rss_kb=900_000,
                         cmdline=["/opt/google/chrome/chrome", "--flag"]),
               proc_info(701, comm="chrome-headless-shell", uid=1000, ppid=700,
                         pgid=700, session=700, rss_kb=50_000,
                         cmdline=["/home/u/.cache/ms-playwright/chromium_headless_shell-1223"
                                  "/chrome-headless-shell-linux64/chrome-headless-shell",
                                  "--headless"]),
               proc_info(702, comm="chrome_crashpad", uid=1000, ppid=700,
                         pgid=700, session=700, rss_kb=5_000,
                         cmdline=["/opt/google/chrome/chrome_crashpad_handler"]),
               proc_info(703, comm="npm exec chrome", uid=1000, ppid=700,
                         pgid=700, session=700, rss_kb=5_000,
                         cmdline=["/usr/bin/npm", "exec", "chrome"])]

    targets = group_targets(members, uid=1000, self_pid=10)

    assert [t.group for t in targets] == ["chrome"]
    assert [m.pid for m in targets[0].members] == [700]
    assert targets[0].label == "Google Chrome/Chromium"


def test_group_mode_refuses_other_users_and_protected_names():
    members = [proc_info(800, comm="microsoft-edge", uid=0, ppid=1, pgid=800,
                         session=800),
               proc_info(801, comm="msedge", uid=1000, ppid=1, pgid=801, session=801),
               proc_info(1, comm="systemd", uid=0, ppid=0, pgid=1, session=1)]

    targets = group_targets(members, uid=1000, self_pid=10)

    assert [t.group for t in targets] == ["edge"]
    assert [m.pid for m in targets[0].members] == [801]


def test_group_mode_never_targets_the_app_itself():
    app = proc_info(30, comm="microsoft-edge-wrapper", ppid=20, uid=1000,
                    pgid=30, session=30)
    browser = proc_info(31, comm="msedge", ppid=30, uid=1000, pgid=30, session=30)

    targets = group_targets([app, browser], uid=1000, self_pid=30)

    assert [m.pid for t in targets for m in t.members] == [31]


def test_no_group_target_when_nothing_matches():
    assert group_targets([proc_info(5, comm="kwin_x11", uid=1000)],
                         uid=1000, self_pid=10) == ()


# ------------------------------------------- who is really in the group
# All three cases below were observed on the Deck on 2026-10-14: a Playwright
# chromium headless shell was announced as "Microsoft Edge" because its flags
# mention msEdgeUpdate*, and the family the user wanted to close was unreachable.


def test_a_flag_naming_edge_does_not_make_the_process_edge():
    shell = proc_info(900, comm="chrome-headless", uid=1000, ppid=1, pgid=900,
                      session=900,
                      cmdline=["/home/u/.cache/ms-playwright/chromium_headless_shell-1223"
                               "/chrome-headless-shell",
                               "--enable-features=msEdgeUpdateLaunchServicesPreferredVersion"])

    targets = group_targets([shell], uid=1000, self_pid=10)

    assert targets == (), "the executable decides, not a flag — and this one is tooling"


def test_a_process_labelled_chrome_by_its_comm_is_not_the_browser():
    """comm is a 15-character label; npm used it as a description."""
    imposter = proc_info(905, comm="npm exec chrome", uid=1000, ppid=1, pgid=905,
                         session=905, cmdline=["/usr/bin/npm", "exec", "chrome"])

    assert group_targets([imposter], uid=1000, self_pid=10) == ()


def test_a_browser_under_automation_control_is_never_offered():
    """A driver-attached browser is a tool's worker, not idle RAM: killing it
    breaks a running session, and the user cannot see which one."""
    procs = [proc_info(901, comm="chrome", uid=1000, ppid=1, pgid=901, session=901,
                       cmdline=["/opt/google/chrome/chrome", "--remote-debugging-pipe"]),
             proc_info(902, comm="msedge", uid=1000, ppid=1, pgid=902, session=902,
                       cmdline=["/usr/bin/msedge", "--remote-debugging-port=9222"])]

    assert group_targets(procs, uid=1000, self_pid=10) == ()


def test_one_process_belongs_to_at_most_one_group():
    procs = [proc_info(903, comm="msedge", uid=1000, ppid=1, pgid=903, session=903,
                       cmdline=["/opt/msedge/chrome", "--flag"])]

    targets = group_targets(procs, uid=1000, self_pid=10)

    assert [t.group for t in targets] == ["edge"]
    assert sum(len(t.members) for t in targets) == 1, "no double-counted yield"
