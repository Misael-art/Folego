"""CLI for M4: see it first, then signal it — both modes work from a TTY."""
import os
import signal

import pytest

from folego.actions.orphans.reaper import Reaper
from folego.cli import main
from folego.safely.audit import AuditLog
from fixtures_proc import build_proc

UID = os.getuid()
TERM = int(signal.SIGTERM)
KILL = int(signal.SIGKILL)


@pytest.fixture
def proc_tree(tmp_path, monkeypatch):
    """What PID 1 reaped: one provable orphan, a supervisor with a live child,
    that child, a protected desktop process and a group leader."""
    root = tmp_path / "proc"
    build_proc(root, pids=[
        dict(pid=500, comm="esquecido", ppid=1, pgid=900, session=901, uid=UID,
             starttime=777, rss_kb=250_000),
        dict(pid=501, comm="supervisor", ppid=1, pgid=900, session=901, uid=UID,
             starttime=888, rss_kb=50_000),
        dict(pid=503, comm="em-uso", ppid=501, pgid=900, session=901, uid=UID,
             starttime=999, rss_kb=5_000),
        dict(pid=600, comm="plasmashell", ppid=1, pgid=600, session=600, uid=UID,
             starttime=1_111, rss_kb=900_000),
        dict(pid=601, comm="lider", ppid=1, pgid=601, session=903, uid=UID,
             starttime=2_222, rss_kb=30_000),
    ])
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    return root


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Route the CLI's Reaper at the fake tree, never at real processes.

    Deliberately avoids the fake_home fixture: it clears DECKWELLNESS_PROC_ROOT,
    which is the seam these tests rely on.
    """
    calls = []

    def kill_fn(pid, sig):
        calls.append((pid, sig))

    def factory():
        return Reaper(proc_root=tmp_path / "proc", kill_fn=kill_fn,
                      audit=AuditLog(tmp_path / "audit.jsonl"))

    monkeypatch.setattr("folego.cli._reaper", factory)
    return calls


# ------------------------------------------------------------------- orphans

def test_orphans_dry_run_lists_only_the_proven_orphan(proc_tree, sent, capsys):
    code = main(["orphans", "--janela", "0"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("pid ") == 1
    assert "esquecido" in captured.out
    assert "244,1 MB" in captured.out
    assert "supervisor" not in captured.out, "has a live child: killing it cascades"
    assert "em-uso" not in captured.out, "has a live parent"
    assert "plasmashell" not in captured.out, "protected"
    assert "lider" not in captured.out, "group leader"
    assert "dry-run" in captured.err.lower()
    assert sent == [], "listing must not signal anything"


def test_confirmar_sends_sigterm_to_the_listed_orphan(proc_tree, sent, capsys):
    code = main(["orphans", "--janela", "0", "--confirmar"])

    out = capsys.readouterr().out
    assert code == 0
    assert sent == [(500, TERM)]
    assert "encerrado" in out


def test_force_flag_without_confirmation_is_refused(proc_tree, sent, capsys):
    code = main(["orphans", "--janela", "0", "--forcar"])

    err = capsys.readouterr().err
    assert code == 2
    assert "--confirmar" in err
    assert sent == []


def test_force_with_both_flags_uses_sigkill(proc_tree, sent, capsys):
    code = main(["orphans", "--janela", "0", "--confirmar", "--forcar"])

    assert code == 0
    assert sent == [(500, KILL)]


def test_a_recycled_pid_is_refused_at_the_last_moment(proc_tree, tmp_path,
                                                     monkeypatch, capsys):
    calls = []
    other = tmp_path / "other-proc"
    build_proc(other, pids=[dict(pid=500, comm="esquecido", ppid=1, pgid=900,
                                 session=901, uid=UID, starttime=4_242)])
    monkeypatch.setattr(
        "folego.cli._reaper",
        lambda: Reaper(proc_root=other, kill_fn=lambda pid, sig: calls.append(pid),
                       audit=AuditLog(tmp_path / "audit.jsonl")))

    code = main(["orphans", "--janela", "0", "--confirmar"])

    assert code == 1
    assert calls == []
    assert "reutilizado" in capsys.readouterr().err


def test_min_idle_threshold_can_be_raised(proc_tree, sent, capsys):
    code = main(["orphans", "--janela", "0", "--ocioso", "3_600"])

    out = capsys.readouterr().out
    assert code == 0
    assert "esquecido" not in out


# ----------------------------------------------------------------- group mode

@pytest.fixture
def browser_tree(tmp_path, monkeypatch):
    root = tmp_path / "proc"
    build_proc(root, pids=[
        dict(pid=700, comm="msedge", ppid=10, uid=UID, starttime=111, rss_kb=900_000),
        dict(pid=701, comm="msedge", ppid=700, uid=UID, starttime=222, rss_kb=200_000),
        dict(pid=702, comm="msedge", ppid=700, uid=UID, starttime=333, rss_kb=80_000),
        dict(pid=703, comm="chrome_crashpad", ppid=700, uid=UID, starttime=444,
             rss_kb=10_000),
    ])
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    return root


def test_groups_dry_run_totals_the_family_and_skips_protected_members(
        browser_tree, sent, capsys):
    code = main(["groups"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Microsoft Edge" in out
    assert "3 processo" in out
    assert "1,1 GB" in out
    assert "chrome_crashpad" not in out
    assert sent == []


def test_groups_confirmar_terminates_children_first(browser_tree, sent, capsys):
    code = main(["groups", "--grupo", "edge", "--confirmar"])

    out = capsys.readouterr().out
    assert code == 0
    assert [pid for pid, _ in sent] == [702, 701, 700]
    assert "Edge" in out


def test_groups_without_confirmation_is_a_dry_run(browser_tree, sent, capsys):
    assert main(["groups", "--grupo", "edge"]) == 0
    assert sent == []
    assert "dry-run" in capsys.readouterr().err.lower()


def test_groups_reports_when_nothing_matches(proc_tree, sent, capsys):
    code = main(["groups"])

    assert code == 0
    assert "nenhum grupo" in capsys.readouterr().out.lower()


def test_unknown_group_is_refused(browser_tree, sent, capsys):
    code = main(["groups", "--grupo", "firefox"])

    assert code == 2
    assert sent == []
