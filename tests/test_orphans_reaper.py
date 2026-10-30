"""M4 actions: signalling real processes, with re-verification before every kill.

The candidate list came from a snapshot that is already stale by the time the
user clicks. Nothing is signalled without re-reading /proc/<pid> and proving it
is still the same process (starttime) and still outside the pre-list.
"""
import shutil
import signal
import os

import pytest

from folego.actions.orphans.reaper import Reaper
from folego.core.orphans import GroupMember, GroupTarget, OrphanCandidate
from folego.safely import procs
from folego.safely.audit import AuditLog
from fixtures_proc import pid_dir

TERM = signal.SIGTERM
KILL = signal.SIGKILL
UID = os.getuid()


def candidate(pid=500, comm="worker", starttime=12345):
    return OrphanCandidate(pid=pid, comm=comm, state="S", uid=UID, rss_kb=2000,
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

    return Reaper(proc_root=live, kill_fn=kill_fn, audit=log,
                  pin_fn=procs.unsupported, follow_up_s=0.0)


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
    member = GroupMember(401, "msedge", UID, 222, 400)
    pid_dir(live, 401, comm="msedge", starttime=222, ppid=400)

    result = reaper.force(member, confirm=True, require_orphan=False)

    assert result.ok and result.signal == KILL
    assert kills == [(401, KILL)]


def test_the_orphan_rule_still_blocks_force_when_the_caller_demands_it(reaper, live, kills):
    member = GroupMember(401, "msedge", UID, 222, 400)
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
                       tuple(GroupMember(pid, "msedge", UID, start, 400)
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
        GroupMember(401, "chrome_crashpad", UID, 222, 400),
        GroupMember(400, "msedge", UID, 111, 10)))

    results = reaper.terminate_group(target)

    assert [pid for pid, _ in kills] == [400]
    assert "protegido" in next(x for x in results if x.pid == 401).reason


def test_group_mode_refuses_a_member_that_got_a_driver_after_the_list(reaper, live, kills):
    """A Playwright session can attach between the poll and the click; the click
    re-reads /proc, so the family is not cut out from under the driver."""
    pid_dir(live, 400, comm="msedge", starttime=111, ppid=10,
            cmdline=["/usr/bin/msedge", "--remote-debugging-port=9222"])
    target = GroupTarget("edge", "Microsoft Edge",
                         (GroupMember(400, "msedge", UID, 111, 10),))

    result = reaper.terminate_group(target)[0]

    assert not result.ok and "automação" in result.reason
    assert kills == []


def test_group_mode_refuses_an_automation_shell(reaper, live, kills):
    pid_dir(live, 400, comm="chrome-headless", starttime=111, ppid=10,
            cmdline=["/home/u/.cache/ms-playwright/chromium_headless_shell-1223"
                     "/chrome-headless-shell", "--headless"])
    target = GroupTarget("chrome", "Google Chrome/Chromium",
                         (GroupMember(400, "chrome-headless", UID, 111, 10),))

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


# -------------------------------------------- acompanhamento e identidade (entrega 8)

class Clock:
    """Relógio falso: o prazo do acompanhamento passa sem dormir de verdade."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def test_sigterm_is_followed_until_the_process_is_gone(live, kills):
    proc(live)
    clock = Clock()

    def kill(pid, sig):
        kills.append((pid, sig))
        shutil.rmtree(live / str(pid))

    reaper = Reaper(proc_root=live, kill_fn=kill, pin_fn=procs.unsupported,
                    follow_up_s=2.0, poll_s=0.05, clock=clock, sleep=clock.sleep)

    result = reaper.terminate(candidate())

    assert result.ok and result.exited is True
    assert result.identity == "starttime"
    assert clock.t == 0.0, "saiu na primeira leitura: não gasta o prazo"


def test_a_sigterm_survivor_is_named_and_never_escalated(live, kills):
    proc(live)
    clock = Clock()
    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=procs.unsupported, follow_up_s=0.2, poll_s=0.05,
                    clock=clock, sleep=clock.sleep)

    result = reaper.terminate(candidate())

    assert result.ok and result.exited is False
    assert kills == [(500, TERM)], "sobreviver ao SIGTERM não autoriza SIGKILL"
    assert clock.t >= 0.2


def test_sigkill_is_followed_too(live, kills):
    proc(live)
    clock = Clock()

    def kill(pid, sig):
        kills.append((pid, sig))
        shutil.rmtree(live / str(pid))

    reaper = Reaper(proc_root=live, kill_fn=kill, pin_fn=procs.unsupported,
                    follow_up_s=1.0, clock=clock, sleep=clock.sleep)

    result = reaper.force(candidate(), confirm=True)

    assert result.ok and result.signal == KILL and result.exited is True


def test_group_follow_up_waits_once_for_the_whole_family(live, kills):
    target = a_browser_group(live)
    clock = Clock()

    def kill(pid, sig):
        kills.append((pid, sig))
        shutil.rmtree(live / str(pid))

    reaper = Reaper(proc_root=live, kill_fn=kill, pin_fn=procs.unsupported,
                    follow_up_s=2.0, poll_s=0.05, clock=clock, sleep=clock.sleep)

    results = reaper.terminate_group(target)

    assert all(x.exited is True for x in results)
    assert clock.t == 0.0, "a leva inteira saiu antes de qualquer espera"


def test_group_survivors_are_reported_without_killing_again(live, kills):
    target = a_browser_group(live)
    clock = Clock()
    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=procs.unsupported, follow_up_s=0.2, poll_s=0.05,
                    clock=clock, sleep=clock.sleep)

    results = reaper.terminate_group(target)

    assert all(x.exited is False for x in results)
    assert kills == [(402, TERM), (401, TERM), (400, TERM)]
    assert clock.t >= 0.2


def test_manual_kill_batch_has_one_shared_follow_deadline(live, kills):
    target = a_browser_group(live)
    clock = Clock()
    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=procs.unsupported, follow_up_s=.2, poll_s=.05,
                    clock=clock, sleep=clock.sleep)
    results = reaper.force_many(target.members, confirm=True, require_orphan=False)
    assert all(result.ok and result.exited is False for result in results)
    assert kills == [(402, KILL), (401, KILL), (400, KILL)]
    assert .2 <= clock.t < .25, "prazo coletivo não cresce com número de alvos"


def test_unreadable_process_after_signal_is_not_reported_as_exited(live, kills):
    proc(live)
    clock = Clock()
    def kill(pid, sig):
        kills.append((pid, sig))
        (live / str(pid) / "stat").write_text("corrupt stat")
    reaper = Reaper(proc_root=live, kill_fn=kill, pin_fn=procs.unsupported,
                    follow_up_s=.2, clock=clock, sleep=clock.sleep)
    result = reaper.terminate(candidate())
    assert result.ok and result.exited is None
    assert kills == [(500, TERM)]
    assert clock.t >= .2


def test_the_identity_method_comes_from_the_pinner(live, monkeypatch):
    proc(live)
    seen = []

    def fake_pin(pid):
        return procs.Pin(pid=pid, fd=None, supported=True)

    def fake_send(pinned, sig, *, kill_fn):
        seen.append((pinned.pid, sig))

    monkeypatch.setattr(procs, "send", fake_send)
    reaper = Reaper(proc_root=live, pin_fn=fake_pin, follow_up_s=0.0)

    result = reaper.terminate(candidate())

    assert result.ok and result.identity == "pidfd"
    assert seen == [(500, TERM)]


def test_a_pin_failure_is_a_recusa_with_no_signal(live, kills):
    proc(live)

    def gone(pid):
        raise ProcessLookupError()

    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=gone)

    result = reaper.terminate(candidate())

    assert not result.ok and "não existe mais" in result.reason
    assert kills == []


def test_session_protection_is_rechecked_at_act_time(live, kills, log):
    proc(live)
    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=procs.unsupported, follow_up_s=0.0,
                    protected_fn=lambda p: "sessão abc marcada como manter ativo")

    result = reaper.terminate(candidate())

    assert not result.ok and "proteção" in result.reason
    assert kills == []


def test_an_unreadable_protection_source_fails_closed(live, kills, log):
    proc(live)

    def broken(_proc):
        raise OSError("registro ilegível")

    reaper = Reaper(proc_root=live,
                    kill_fn=lambda pid, sig: kills.append((pid, sig)),
                    pin_fn=procs.unsupported, follow_up_s=0.0,
                    protected_fn=broken)

    result = reaper.terminate(candidate())

    assert not result.ok and "ilegível" in result.reason
    assert kills == []
