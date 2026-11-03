import json

import pytest

from folego.core import agents, perf_model, perf_rules
from folego.core.snapshot import ProcInfo


def proc(pid, comm, cmd=None, rss=100_000):
    return ProcInfo(pid, comm, "S", 1, pid, pid, 0, 0, pid, rss, 0, 1000,
                    tuple(cmd or ("/usr/bin/" + comm,)), cpu_frac=0.0)


def group(unit, label, pids, state=perf_model.OBSERVED, cpu=0.0, class_only=False, rss=500_000):
    return perf_model.AppGroup(unit, label, pids, rss, cpu, state, "x", class_only)


def view(*groups):
    act = agents.AgentActivity(frozenset(), frozenset(), frozenset(), agents.IDLE, 0.0)
    return perf_model.PerfView(groups, act, None, None, None)


DEFAULTS = {r.id: r.default for r in perf_rules.RULES}


def test_modes_default_without_file_and_fail_closed_on_bad_schema(tmp_path):
    path = tmp_path / "state" / "folego" / "rules.json"  # fresh host: no state dir yet
    assert perf_rules.load_modes(path) == DEFAULTS
    perf_rules.save_modes(path, {**DEFAULTS, "steam-idle": "off"})
    assert perf_rules.load_modes(path)["steam-idle"] == "off"
    for bad in ({"version": 2}, {"version": 1, "modes": {"steam-idle": "automatic"}},
                {"version": 1, "modes": {"nova": "suggest"}}):
        path.write_text(json.dumps(bad))
        with pytest.raises(perf_rules.PolicyError):
            perf_rules.load_modes(path)
    path.write_text("{")
    with pytest.raises(perf_rules.PolicyError):
        perf_rules.load_modes(path)


def test_suggestion_ready_only_after_continuous_wait():
    procs = (proc(1, "steam"),)
    v = view(group("app-steam.service", "steam", (1,)))
    tracker = perf_rules.ConditionTracker()
    first = perf_rules.plan(v, procs, DEFAULTS, tracker, 0.0)
    assert [s.rule for s in first] == ["steam-idle"] and not first[0].ready
    assert perf_rules.plan(v, procs, DEFAULTS, tracker, 601.0)[0].ready
    busy = view(group("app-steam.service", "steam", (1,), cpu=50.0))
    assert perf_rules.plan(busy, procs, DEFAULTS, tracker, 602.0) == ()
    assert not perf_rules.plan(v, procs, DEFAULTS, tracker, 603.0)[0].ready  # gap restarts


def test_game_marker_agent_and_off_mode_block_suggestions():
    tracker = perf_rules.ConditionTracker()
    game = (proc(1, "steam"), proc(2, "reaper", ("reaper", "SteamLaunch", "AppId=1")))
    assert perf_rules.plan(view(group("app-steam.service", "steam", (1, 2))), game,
                           DEFAULTS, tracker, 0.0) == ()
    agent = view(group("app-steam.service", "steam", (1,), state=perf_model.AGENT))
    assert perf_rules.plan(agent, game[:1], DEFAULTS, tracker, 0.0) == ()
    off = {**DEFAULTS, "steam-idle": "off"}
    assert perf_rules.plan(view(group("app-steam.service", "steam", (1,))), game[:1],
                           off, tracker, 0.0) == ()


def test_explicit_units_override_class_but_not_user_protection():
    unit = "biglinux-welcome.service"
    procs = (proc(1, "python3"),)
    by_class = view(group(unit, "biglinux-welcome", (1,), state=perf_model.PROTECTED, class_only=True))
    assert [s.rule for s in perf_rules.plan(by_class, procs, DEFAULTS,
                                            perf_rules.ConditionTracker(), 0.0)] == ["autostart-extras"]
    by_user = view(group(unit, "biglinux-welcome", (1,), state=perf_model.PROTECTED))
    assert perf_rules.plan(by_user, procs, DEFAULTS, perf_rules.ConditionTracker(), 0.0) == ()
    other = view(group("plasma-plasmashell.service", "plasma-plasmashell", (1,),
                       state=perf_model.PROTECTED, class_only=True))
    assert perf_rules.plan(other, procs, DEFAULTS, perf_rules.ConditionTracker(), 0.0) == ()


def test_duplicate_bridges_and_bloat_are_advice():
    cmd = ("npm exec mcp-remote@latest http://127.0.0.1:1/mcp",)
    procs = (proc(1, "npm exec mcp-re", cmd), proc(2, "npm exec mcp-re", cmd),
             proc(3, "node-MainThread", ("node", "mcp-remote", "http://127.0.0.1:1/mcp")),
             proc(4, "electron", rss=2_000_000))
    items = perf_rules.plan(view(), procs, DEFAULTS, perf_rules.ConditionTracker(), 0.0)
    assert {s.rule for s in items} == {"mcp-duplicate", "electron-bloat"}
    assert all(s.kind == perf_rules.ADVICE for s in items)
    assert next(s for s in items if s.rule == "mcp-duplicate").rss_kb == 200_000
