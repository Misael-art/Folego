import json
import subprocess
import sys
from pathlib import Path

from folego.actions.performance import closers, executor
from folego.core import agents, perf_model, perf_rules, procfs
from folego.orchestration import Coordinator, Outcome
from folego.orchestration.journal import Journal
from folego.orchestration import review

UNIT = "app-steam.service"


def busctl(owner_pid, labels, calls):
    def run(argv, **_kw):
        calls.append(argv)
        if "RegisteredStatusNotifierItems" in argv:
            data = {"data": [":1.5/StatusNotifierItem"]}
        elif "GetConnectionUnixProcessID" in argv:
            data = {"data": [owner_pid]}
        elif "Menu" in argv:
            data = {"data": "/Menu"}
        elif "GetLayout" in argv:
            kids = [{"data": [i, {"label": {"data": label}}, []]} for i, label in enumerate(labels, 10)]
            data = {"data": [1, [0, {}, kids]]}
        else:
            data = {"data": []}
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
    return run


def test_tray_quit_clicks_only_the_groups_own_quit_entry():
    calls = []
    sent = closers.tray_quit([42], run=busctl(42, ["Library", "Exit Steam"], calls))
    assert sent.sent and "Exit Steam" in sent.detail
    assert calls[-1][-6:] == ["--", "11", "clicked", "s", "", "0"]
    calls.clear()
    assert not closers.tray_quit([7], run=busctl(42, ["Exit Steam"], calls)).sent
    assert not any("Event" in c for c in calls)
    assert not closers.tray_quit([42], run=busctl(42, ["Library"], [])).sent


def test_unit_stop_asks_systemd_and_refuses_odd_names():
    calls = []
    run = lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")
    assert closers.unit_stop("app-x@autostart.service", run=run).sent
    assert calls == [["systemctl", "--user", "stop", "--no-block", "--", "app-x@autostart.service"]]
    assert not closers.unit_stop("../etc; rm", run=run).sent and len(calls) == 1


def harness(tmp_path, child, *, mode=perf_rules.ASSISTED, state=perf_model.OBSERVED, cpu=0.0):
    root = Path("/proc")
    proc = procfs.read_proc(root, child.pid)
    group = perf_model.AppGroup(UNIT, "steam", (child.pid,), proc.rss_kb, cpu, state, "x")
    act = agents.AgentActivity(frozenset(), frozenset(), frozenset(), agents.IDLE, 0.0)
    view = perf_model.PerfView((group,), act, None, None, None)
    modes = {**{r.id: r.default for r in perf_rules.RULES}, "steam-idle": mode}
    item = perf_rules.Suggestion("steam-idle", "Steam", perf_rules.CLOSE, UNIT, "steam", 1, "", "",
                                 True, 600, 600, mode, "tray", (child.pid,))
    plan = executor.plan_for(item, (proc,), boot_id="boot-a")
    journal = Journal(tmp_path / "journal.jsonl")
    coordinator = Coordinator(journal=journal, lock_path=tmp_path / "lock")
    return plan, coordinator, journal, (lambda: (view, (proc,), modes)), (lambda pid: procfs.read_proc(root, pid))


def run(plan, coordinator, observe, read, closer, **kw):
    return executor.execute(plan, observe=observe, read_proc=read, confirm=kw.pop("confirm", True),
                            coordinator=coordinator, boot_id_fn=kw.pop("boot", lambda: "boot-a"),
                            closers={"tray": closer}, follow_s=kw.pop("follow_s", 5.0), **kw)


def child():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_close_records_intent_before_request_and_follows_exit(tmp_path):
    proc = child()
    try:
        plan, coordinator, journal, observe, read = harness(tmp_path, proc)
        seen = []

        def closer(pids):
            seen.append(bool(journal.records(plan.operation_id)))  # intent already durable
            proc.terminate(); proc.wait()
            return closers.Request(True, "bandeja", "pedido")
        verdict = run(plan, coordinator, observe, read, closer)
        assert verdict.outcome is Outcome.OK and seen == [True]
        assert run(plan, coordinator, observe, read, closer).outcome is Outcome.OK  # replay, no new effect
        assert seen == [True]
    finally:
        proc.kill()


def test_app_that_stays_is_partial_not_retried(tmp_path):
    proc = child()
    try:
        plan, coordinator, _j, observe, read = harness(tmp_path, proc)
        verdict = run(plan, coordinator, observe, read,
                      lambda pids: closers.Request(True, "bandeja", "pedido"), follow_s=0.6)
        assert verdict.outcome is Outcome.PARTIAL and "não repetir" in verdict.reason
        assert proc.poll() is None
    finally:
        proc.kill()


def test_revalidation_refuses_without_touching_the_app(tmp_path):
    proc = child()
    try:
        never = lambda pids: (_ for _ in ()).throw(AssertionError("closer must not run"))
        cases = [dict(confirm=False), dict(boot=lambda: "boot-b")]
        for kw in cases:
            plan, coordinator, _j, observe, read = harness(tmp_path / str(len(kw)) / str(id(kw)), proc)
            assert run(plan, coordinator, observe, read, never, **kw).outcome is Outcome.REFUSED
        for setup in (dict(mode=perf_rules.SUGGEST), dict(state=perf_model.AGENT), dict(cpu=90.0)):
            plan, coordinator, _j, observe, read = harness(tmp_path / str(id(setup)), proc, **setup)
            assert run(plan, coordinator, observe, read, never).outcome is Outcome.REFUSED
        plan, coordinator, _j, observe, read = harness(tmp_path / "unreadable", proc)
        broken = lambda: (_ for _ in ()).throw(perf_rules.PolicyError("ilegível"))
        assert run(plan, coordinator, broken, read, never).outcome is Outcome.REFUSED
        assert proc.poll() is None
    finally:
        proc.kill()


def test_automatic_trigger_requires_automatic_mode(tmp_path):
    proc = child()
    try:
        plan, coordinator, _j, observe, read = harness(tmp_path, proc)
        auto_plan = executor.ActionPlan(plan.action, plan.target, {**plan.params, "trigger": executor.AUTO})
        never = lambda pids: (_ for _ in ()).throw(AssertionError("closer must not run"))
        verdict = run(auto_plan, coordinator, observe, read, never)
        assert verdict.outcome is Outcome.REFUSED and "automático" in verdict.reason
    finally:
        proc.kill()


def test_manual_close_reviews_exact_plan_and_cli_recovers_same_id(fake_home, monkeypatch, capsys):
    from folego import cli
    from folego.core.snapshot import Snapshot
    from folego.actions.performance import closers as closer_registry
    proc = child()
    try:
        observed = procfs.read_proc(Path("/proc"), proc.pid)
        group = perf_model.AppGroup(UNIT, "steam", (proc.pid,), observed.rss_kb, 0.0,
                                    perf_model.OBSERVED, "fixture")
        activity = agents.AgentActivity(frozenset(), frozenset(), frozenset(), agents.IDLE, 0.0)
        view = perf_model.PerfView((group,), activity, None, None, None)
        snapshot = Snapshot(0, None, 0, 0, None, None, None, None, (), 0, procs=(observed,))
        class Collector:
            def collect(self): return snapshot
        monkeypatch.setattr(cli.scan, "collector_for", lambda: Collector())
        monkeypatch.setattr(perf_model, "observe", lambda *a, **kw: view)
        monkeypatch.setattr(perf_rules, "load_modes", lambda *a: {
            **{r.id: r.default for r in perf_rules.RULES}, "steam-idle": perf_rules.ASSISTED})
        monkeypatch.setattr(perf_rules, "condition", lambda *a: (True, "fixture"))
        calls = []
        def closer(pids):
            calls.append(bool(Journal().records(bundle["plan"]["operation_id"])))
            proc.terminate(); proc.wait(timeout=3)
            return closers.Request(True, "bandeja", "pedido fixture")
        monkeypatch.setattr(closer_registry, "CLOSERS", {"tray": closer})
        bundle = review.prepare(["performance", "close", "steam-idle", "--unit", UNIT, "--json"])
        key = bundle["plan"]["operation_id"]
        assert proc.poll() is None and calls == []
        result = review.execute(bundle, confirmed=True)
        assert result.outcome is Outcome.OK and result.operation_id == key and calls == [True]
        assert review.execute(bundle, confirmed=True) == result and calls == [True]
        assert cli.main(["review", "reconcile", key, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["operation_id"] == key
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
