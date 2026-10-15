"""M4 actions: signalling real processes, with re-verification before every kill.

The candidate list came from a snapshot that is already stale by the time the
user clicks. Nothing is signalled without re-reading /proc/<pid> and proving it
is still the same process (starttime) and still outside the pre-list.
"""
import shutil
import signal

import pytest

from deck_wellness.actions.orphans.reaper import Reaper
from deck_wellness.core.orphans import GroupMember, GroupTarget, OrphanCandidate
from deck_wellness.safely.audit import AuditLog
from fixtures_proc import pid_dir

TERM = signal.SIGTERM
KILL = signal.SIGKILL


def candidate(pid=500, comm="worker", starttime=12345):
    return OrphanCandidate(pid=pid, comm=comm, state="S", uid=1000, rss_kb=2000,
                           swap_kb=0, starttime=starttime, idle_s=900.0)


def proc(root, pid=500, comm="worker", starttime=12345, **kw):
    pid_dir(root, pid, comm=comm, starttime=starttime, **kw)


@pytest.fixture
def kills():
    return []


@pytest.fixture
def live(tmp_path):
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def reaper(live, kills, log):
    def kill_fn(pid, sig):
        kills.append((pid, sig))

    return Reaper(proc_root=live, kill_fn=kill_fn, audit=log)


# ------------------------------------------------------------------ SIGTERM

def test_terminate_sends_sigterm_after_rechecking_the_live_process(reaper, live, kills):
    proc(live)

    result = reaper.terminate(candidate())

    assert result.ok and result.signal == TERM
    assert result.pid == 500
    assert kills == [(500, TERM)], "SIGTERM only: escalation is a separate, deliberate act"


def test_terminate_refuses_a_recycled_pid(reaper, live, kills):
    proc(live, starttime=999_999)  # same pid, born later than the snapshot said

    result = reaper.terminate(candidate())

    assert not result.ok
    assert "reutilizado" in result.reason
    assert kills == []


def test_terminate_refuses_a_process_that_no_longer_exists(reaper, live, kills):
    proc(live)
    shutil.rmtree(live / "500")

    result = reaper.terminate(candidate())

    assert not result.ok
    assert "não existe mais" in result.reason
    assert kills == []


def test_terminate_refuses_a_process_that_changed_its_name(reaper, live, kills):
    proc(live, comm="systemd")

    result = reaper.terminate(candidate())

    assert not result.ok
    assert "protegido" in result.reason
    assert kills == []


def test_terminate_refuses_a_process_that_is_no_longer_an_orphan(reaper, live, kills):
    proc(live, ppid=4321)

    result = reaper.terminate(candidate())

    assert not result.ok
    assert "já tem pai" in result.reason
    assert kills == []


def test_a_process_adopted_by_the_session_supervisor_is_still_an_orphan(reaper, live, kills):
    """systemd --user reaps children of dead launchers; requiring PID 1 here would
    refuse every leftover the panel is allowed to offer on this desktop."""
    pid_dir(live, 1855, comm="systemd", ppid=1, pgid=1855, session=1855, starttime=7)
    proc(live, ppid=1855, pgid=900, session=901)

    result = reaper.terminate(candidate())

    assert result.ok
    assert kills == [(500, TERM)]


def test_permission_error_is_reported_not_raised(reaper, live, monkeypatch):
    proc(live)

    def refuse(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    reaper.kill_fn = refuse
    result = reaper.terminate(candidate())

    assert not result.ok
    assert "permissão" in result.reason


def test_a_process_that_exited_between_check_and_signal_counts_as_done(reaper, live):
    proc(live)

    def vanished(pid, sig):
        raise ProcessLookupError(3, "No such process")

    reaper.kill_fn = vanished
    result = reaper.terminate(candidate())

    assert result.ok
    assert "já saiu" in (result.reason or "")


def test_refusals_are_audited_like_successes(reaper, log):
    result = reaper.terminate(candidate())

    records = log.tail(5)
    assert len(records) == 1
    assert records[0]["outcome"] == "refused"
    assert records[0]["kind"] == "process.terminate"
    assert "500" in " ".join(records[0]["targets"])
    assert result.ok is False


# -------------------------------------------------------------------- SIGKILL

def test_force_needs_its_own_explicit_confirmation(reaper, live, kills):
    proc(live)

    result = reaper.force(candidate())

    assert not result.ok
    assert "confirm" in result.reason.lower()
    assert kills == [], "SIGKILL is never a side effect of asking"


def test_force_confirmed_sends_sigkill(reaper, live, kills):
    proc(live)

    result = reaper.force(candidate(), confirm=True)

    assert result.ok and result.signal == KILL
    assert kills == [(500, KILL)]


def test_force_still_rechecks_before_killing(reaper, live, kills):
    proc(live, starttime=999_999)

    result = reaper.force(candidate(), confirm=True)

    assert not result.ok
    assert kills == []


def test_a_group_member_can_be_forced_without_the_orphan_rule(reaper, live, kills):
    """Children of a browser always have a live parent; escalation must still be possible."""
    member = GroupMember(401, "msedge", 1000, 222, 400)
    pid_dir(live, 401, comm="msedge", starttime=222, ppid=400)

    result = reaper.force(member, confirm=True, require_orphan=False)

    assert result.ok and result.signal == KILL
    assert kills == [(401, KILL)]


def test_the_orphan_rule_still_blocks_force_when_the_caller_demands_it(reaper, live, kills):
    member = GroupMember(401, "msedge", 1000, 222, 400)
    pid_dir(live, 401, comm="msedge", starttime=222, ppid=400)

    result = reaper.force(member, confirm=True)

    assert not result.ok
    assert "não é mais órfão" in result.reason
    assert kills == []


# ------------------------------------------------------------------ group mode

def a_browser_group(root):
    members = ((402, 333), (401, 222), (400, 111))
    for pid, starttime in members:
        pid_dir(root, pid, comm="msedge", starttime=starttime, ppid=400)
    return GroupTarget("edge", "Microsoft Edge",
                       tuple(GroupMember(pid, "msedge", 1000, start, 400)
                             for pid, start in members))


def test_group_terminates_children_before_the_parent(reaper, live, kills):
    target = a_browser_group(live)

    results = reaper.terminate_group(target)

    assert [pid for pid, _ in kills] == [402, 401, 400], \
        "a live parent respawns a killed child"
    assert all(x.ok for x in results)


def test_group_reports_each_member_separately_when_one_is_stale(reaper, live, kills):
    target = a_browser_group(live)
    shutil.rmtree(live / "401")
    pid_dir(live, 401, comm="msedge", starttime=8_888, ppid=400)

    results = reaper.terminate_group(target)

    by_pid = {x.pid: x for x in results}
    assert by_pid[401].ok is False and "reutilizado" in by_pid[401].reason
    assert [pid for pid, _ in kills] == [402, 400]


def test_group_writes_one_audit_record_per_member(reaper, live, kills, log):
    target = a_browser_group(live)

    reaper.terminate_group(target)

    records = log.tail(10)
    assert len(records) == 3
    assert {rec["action_id"] for rec in records} == {"groups.edge"}
    assert {rec["outcome"] for rec in records} == {"signaled"}


def test_group_refuses_a_protected_member_even_when_the_caller_asked(reaper, live, kills):
    pid_dir(live, 400, comm="msedge", starttime=111, ppid=10)
    pid_dir(live, 401, comm="chrome_crashpad", starttime=222, ppid=400)
    target = GroupTarget("chrome", "Google Chrome/Chromium", (
        GroupMember(401, "chrome_crashpad", 1000, 222, 400),
        GroupMember(400, "msedge", 1000, 111, 10)))

    results = reaper.terminate_group(target)

    assert [pid for pid, _ in kills] == [400]
    assert "protegido" in next(x for x in results if x.pid == 401).reason


def test_group_mode_refuses_a_member_that_got_a_driver_after_the_list(reaper, live, kills):
    """A Playwright session can attach between the poll and the click; the click
    re-reads /proc, so the family is not cut out from under the driver."""
    pid_dir(live, 400, comm="msedge", starttime=111, ppid=10,
            cmdline=["/usr/bin/msedge", "--remote-debugging-port=9222"])
    target = GroupTarget("edge", "Microsoft Edge",
                         (GroupMember(400, "msedge", 1000, 111, 10),))

    result = reaper.terminate_group(target)[0]

    assert not result.ok and "automação" in result.reason
    assert kills == []


def test_group_mode_refuses_an_automation_shell(reaper, live, kills):
    pid_dir(live, 400, comm="chrome-headless", starttime=111, ppid=10,
            cmdline=["/home/u/.cache/ms-playwright/chromium_headless_shell-1223"
                     "/chrome-headless-shell", "--headless"])
    target = GroupTarget("chrome", "Google Chrome/Chromium",
                         (GroupMember(400, "chrome-headless", 1000, 111, 10),))

    result = reaper.terminate_group(target)[0]

    assert not result.ok and "automação" in result.reason
    assert kills == []


def test_a_proven_orphan_shell_is_still_killable(reaper, live, kills):
    """The orphan surface keeps its own proof: five minutes without CPU under PID 1
    is dead weight, whoever left it behind — the tooling veto is a group-mode rule."""
    pid_dir(live, 400, comm="chrome-headless", starttime=111, ppid=1, pgid=900,
            session=901,
            cmdline=["/home/u/.cache/ms-playwright/chromium_headless_shell-1223"
                     "/chrome-headless-shell", "--headless"])

    result = reaper.terminate(candidate(pid=400, comm="chrome-headless", starttime=111))

    assert result.ok
    assert kills == [(400, TERM)]
