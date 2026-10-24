import json
import os
from pathlib import Path

import pytest

from folego import cli
from folego.actions.orphans import coordinated
from folego.actions.orphans.reaper import Reaper
from folego.core import procfs
from folego.core.orphans import OrphanCandidate
from folego.core.process_protection import ProcessProtection
from folego.core.sessions import SessionRegistry
from folego.core.exclusions import ExclusionList
from folego.orchestration import Coordinator, Journal, Outcome
from folego.safely import procs
from fixtures_proc import build_proc, pid_dir, set_proc_fields


@pytest.fixture
def environment(tmp_path, fake_home, monkeypatch):
    root = tmp_path / "proc"
    build_proc(root, pids=[dict(pid=500, comm="fixture-worker", ppid=1, pgid=900,
                              session=901, uid=os.getuid(), starttime=777)])
    boot = root / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("fixture-boot")
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    calls = []
    coord = Coordinator()
    def signal(pid, sig):
        records, problems = coord.journal.load()
        assert not problems and records[-1].kind == "intent"
        calls.append((pid, int(sig)))
    reaper = Reaper(proc_root=root, kill_fn=signal, pin_fn=procs.unsupported,
                    follow_up_s=0, protected_fn=ProcessProtection(proc_root=root))
    live = procfs.read_proc(root, 500)
    target = OrphanCandidate(live.pid, live.comm, live.state, live.uid, live.rss_kb,
                            live.swap_kb, live.starttime, 100, cpu_ticks=live.utime + live.stime)
    plan = coordinated.plan_for([target], boot_id="fixture-boot")
    return root, reaper, coord, plan, calls


def test_process_effect_is_journaled_and_same_plan_is_not_reapplied(environment):
    root, reaper, coord, plan, calls = environment
    first = coordinated.execute(plan, reaper=reaper, coordinator=coord, confirm=True)
    assert first.verdict.outcome is Outcome.PARTIAL
    assert calls == [(500, 15)]
    again = coordinated.execute(plan, reaper=reaper, coordinator=Coordinator(), confirm=True)
    assert again.verdict.to_dict() == first.verdict.to_dict()
    assert calls == [(500, 15)]


@pytest.mark.parametrize("protection", ["exclusion", "session", "reboot", "recycled", "cpu", "child"])
def test_current_protections_added_after_plan_block_signal(environment, protection):
    root, reaper, coord, plan, calls = environment
    if protection == "exclusion":
        ExclusionList().add("app", "fixture-worker", keep_active=True)
    elif protection == "session":
        SessionRegistry(proc_root=root).register(500, keep_active=True)
    elif protection == "reboot":
        (root / "sys/kernel/random/boot_id").write_text("another-boot")
    elif protection == "recycled":
        set_proc_fields(root, 500, starttime=999)
    elif protection == "cpu":
        set_proc_fields(root, 500, utime=999)
    else:
        pid_dir(root, 501, comm="useful-build", ppid=500, uid=os.getuid())
    result = coordinated.execute(plan, reaper=reaper, coordinator=coord, confirm=True)
    assert result.verdict.outcome is Outcome.REFUSED
    assert calls == []


def test_keep_active_on_managed_ancestor_preserves_child(environment):
    root, reaper, coord, plan, calls = environment
    pid_dir(root, 400, comm="managed-launcher", ppid=1, uid=os.getuid(), starttime=500)
    # The last live stat now links the selected identity to a managed parent.
    stat_path = root / "500/stat"
    content = stat_path.read_text().replace(" S 1 900 ", " S 400 900 ")
    stat_path.write_text(content)
    SessionRegistry(proc_root=root).register(400, keep_active=True)
    result = coordinated.execute(plan, reaper=reaper, coordinator=coord, confirm=True)
    assert result.verdict.outcome is Outcome.REFUSED and calls == []
    assert "manter ativo" in result.verdict.effects["results"][0]["reason"]


def test_process_endpoint_requires_confirmation_and_reports_same_id(environment, monkeypatch, capsys):
    root, reaper, coord, plan, calls = environment
    monkeypatch.setattr(cli, "_reaper", lambda: reaper)
    args = ["process", "--plan", json.dumps(plan.to_dict()), "--json"]
    assert cli.main(args) == 2
    capsys.readouterr()
    assert calls == []
    assert cli.main([*args, "--confirmar"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation_id"] == plan.operation_id
    assert payload["effects"]["results"][0]["pid"] == 500
    assert calls == [(500, 15)]


def test_final_record_failure_never_repeats_a_signal(environment, monkeypatch):
    root, reaper, coord, plan, calls = environment
    def full(self, result):
        raise OSError(28, "journal full")
    monkeypatch.setattr(Journal, "append_result", full)
    result = coordinated.execute(plan, reaper=reaper, coordinator=coord, confirm=True)
    assert result.verdict.outcome is Outcome.UNKNOWN
    assert result.verdict.effects["results"][0]["ok"] is True
    assert calls == [(500, 15)]
    retry = coordinated.execute(plan, reaper=reaper, coordinator=Coordinator(), confirm=True)
    assert retry.verdict.outcome is Outcome.UNKNOWN and calls == [(500, 15)]
