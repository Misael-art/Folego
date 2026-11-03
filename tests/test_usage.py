import json
import os
import subprocess

from folego.core import agents, perf_model, perf_rules, usage
from folego.core.snapshot import ProcInfo


def runner(stdout, code=0):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, stdout, "")


def test_focus_and_audio_probes_parse_and_fail_protective(monkeypatch):
    monkeypatch.setattr(usage.shutil, "which", lambda name: "/usr/bin/" + name)
    assert usage.focused_pid(runner("{uuid}\n4242\n")) == 4242
    assert isinstance(usage.focused_pid(runner("", 1)), str)
    streams = [{"corked": False, "properties": {"application.process.id": "7"}},
               {"corked": True, "properties": {"application.process.id": "8"}}]
    assert usage.audio_pids(runner(json.dumps(streams))) == {7}
    assert isinstance(usage.audio_pids(runner("not json")), str)
    monkeypatch.setattr(usage.shutil, "which", lambda name: None)
    assert isinstance(usage.focused_pid(), str) and isinstance(usage.audio_pids(), str)


def test_in_use_reasons(tmp_path):
    calm = usage.Probes(None, frozenset())
    files = {1: [("/home/u/Downloads/a.iso.crdownload", os.O_WRONLY)],
             2: [("/p/repo/src/x.py", os.O_RDWR)], 3: [("/p/repo/src/x.py", os.O_RDONLY)]}
    fake = lambda pid, root: files.get(pid, ())
    check = lambda pids, probes=calm: usage.in_use(pids, probes=probes, projects={"/p/repo"}, files=fake)
    assert check([9], usage.Probes(9, frozenset())) == "janela em foco"
    assert "desconhecido" in check([9], usage.Probes("foco desconhecido: x", frozenset()))
    assert check([9], usage.Probes(None, frozenset({9}))) == "tocando áudio"
    assert check([1]) == "download em andamento"
    assert check([2]) == "arquivo de projeto aberto para escrita"
    assert check([3]) is None and check([9]) is None


def test_automation_flags_make_a_browser_an_agent():
    proc = ProcInfo(5, "msedge", "S", 1, 5, 5, 0, 0, 5, 1, 0, 1000,
                    ("/opt/msedge", "--remote-debugging-port=9222"))
    assert agents.is_agent_root(proc)
    assert not agents.is_agent_root(ProcInfo(6, "msedge", "S", 1, 6, 6, 0, 0, 6, 1, 0, 1000, ("/opt/msedge",)))
    # Steam's own embedded Chromium uses CDP; that is not an agent (found in the host soak)
    helper = ProcInfo(7, "steamwebhelper", "S", 1, 7, 7, 0, 0, 7, 1, 0, 1000,
                      ("./steamwebhelper", "--remote-debugging-port=8080"))
    assert not agents.is_agent_root(helper)


def test_in_use_blocks_plan_and_revalidation():
    proc = ProcInfo(1, "msedge", "S", 1, 1, 1, 0, 0, 1, 1, 0, 1000, ("/opt/msedge",), cpu_frac=0.0)
    group = perf_model.AppGroup("app-microsoft-edge.service", "microsoft-edge", (1,), 1, 0.0,
                                perf_model.OBSERVED, "x")
    act = agents.AgentActivity(frozenset(), frozenset(), frozenset(), agents.IDLE, 0.0)
    view = perf_model.PerfView((group,), act, None, None, None, {group.unit: "download em andamento"})
    modes = {r.id: r.default for r in perf_rules.RULES}
    assert perf_rules.plan(view, (proc,), modes, perf_rules.ConditionTracker(), 0.0) == ()
    ok, why = perf_rules.condition(perf_rules.BY_ID["edge-after-login"], group, (proc,), view.in_use)
    assert not ok and "download" in why
