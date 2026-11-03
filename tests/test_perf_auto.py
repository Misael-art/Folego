import pytest

from folego.actions.performance import auto, executor
from folego.core import agents, perf_auto, perf_model, perf_rules
from folego.core.snapshot import Pressure
from folego.orchestration import ActionResult, Outcome

UNIT = "app-steam.service"


def item(ready=True, mode=perf_rules.AUTOMATIC, rule="steam-idle", unit=UNIT, label="steam"):
    return perf_rules.Suggestion(rule, "Steam", perf_rules.CLOSE, unit, label, 500_000, "CPU 0%",
                                 "Sair", ready, 600.0 if ready else 30.0, 600.0, mode, "tray", (5,))


def view(psi=0.0, load=agents.IDLE, avail=8_000_000):
    act = agents.AgentActivity(frozenset(), frozenset(), frozenset(), load, 0.0)
    return perf_model.PerfView((), act, Pressure(psi, psi, psi, 0), avail, 16_000_000)


def why(decision):
    return [w for _s, w in decision.waiting]


def test_without_pressure_nothing_closes_and_grace_precedes_close():
    state = perf_auto.AutoState()
    d = perf_auto.decide([item()], view(), state, now=0, boot="b")
    assert d.close is None and "sem pressão" in why(d)[0]
    d = perf_auto.decide([item()], view(psi=9.0), state, now=10, boot="b")
    assert d.close is None and len(d.announce) == 1 and "aviso" in why(d)[0]
    d = perf_auto.decide([item()], view(psi=9.0), state, now=40, boot="b")
    assert d.close is None and "carência" in why(d)[0]
    d = perf_auto.decide([item()], view(psi=9.0), state, now=71, boot="b")
    assert d.close is not None and d.trigger.startswith("pressão")


@pytest.mark.parametrize("v", [view(load=agents.BUSY), view(avail=1_000_000)])
def test_low_ram_or_agent_build_also_trigger(v):
    assert perf_auto.pressure(v)


def test_only_automatic_ready_items_and_one_close_per_cycle():
    state = perf_auto.AutoState(announced={perf_auto.key_of("steam-idle", UNIT): 0,
                                           perf_auto.key_of("edge-after-login", "e"): 0})
    items = [item(mode=perf_rules.ASSISTED, unit="x"), item(ready=False, unit="y"), item(),
             item(rule="edge-after-login", unit="e", label="edge")]
    d = perf_auto.decide(items, view(psi=9.0), state, now=100, boot="b")
    assert d.close.unit == UNIT and any("carência" in w for w in why(d))
    assert all(s.mode == perf_rules.AUTOMATIC for s, _ in d.waiting)


def test_snooze_breaker_budget_and_reopen_rest():
    ready = {perf_auto.key_of("steam-idle", UNIT): 0}
    cases = [
        (perf_auto.AutoState(announced=dict(ready), snoozed={perf_auto.key_of("steam-idle", UNIT): 999}), "adiado"),
        (perf_auto.AutoState(announced=dict(ready), breaker="2 falhas"), "disjuntor"),
        (perf_auto.AutoState(announced=dict(ready), history=[
            {"ts": 50, "boot": "old", "rule": "steam-idle", "unit": UNIT, "label": "x", "outcome": "parcial"}]),
         "orçamento"),
        (perf_auto.AutoState(announced=dict(ready), history=[
            {"ts": -9999, "boot": "b", "rule": "steam-idle", "unit": "old", "label": "steam",
             "outcome": "sucesso"}]), "repouso"),
    ]
    for state, expected in cases:
        d = perf_auto.decide([item()], view(psi=9.0), state, now=100, boot="b")
        assert d.close is None and expected in why(d)[0], expected


def test_two_failures_open_breaker_and_state_round_trips(tmp_path):
    store = perf_auto.AutoStore(tmp_path / "s" / "auto.json")
    with store.update() as state:
        state.record(ts=1, boot="b", rule="steam-idle", unit=UNIT, label="steam", outcome="parcial")
        assert not state.breaker
        state.record(ts=2, boot="b", rule="steam-idle", unit=UNIT, label="steam", outcome="recusa")
    assert store.read().breaker and store.read().failures == 2
    store.path.write_text('{"version": 9}')
    with pytest.raises(perf_auto.AutoStateError):
        store.read()


class Collector:
    def collect(self):
        from folego.core.snapshot import Snapshot
        return Snapshot(0.0, None, 0, 0, None, None, None, None, (), 0)


def test_cycle_announces_then_closes_with_automatic_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(perf_model, "observe", lambda snap, protected_fn=None: view(psi=9.0))
    monkeypatch.setattr(perf_rules, "plan", lambda *a, **k: (item(),))
    rules = tmp_path / "rules.json"
    perf_rules.save_modes(rules, {r.id: r.default for r in perf_rules.RULES} | {"steam-idle": "automatic"})
    store = perf_auto.AutoStore(tmp_path / "auto.json")
    clock = iter([0, 0, 100, 100, 100])
    notes, plans = [], []

    def execute(plan, **kw):
        plans.append(plan)
        return ActionResult(plan.action, Outcome.OK, plan.operation_id, "saiu", plan.target.key)
    common = dict(collector=Collector(), tracker=perf_rules.ConditionTracker(), store=store, rules_path=rules,
                  notify_fn=notes.append, execute=execute, boot_id_fn=lambda: "b", now=lambda: next(clock))
    assert auto.cycle(**common)["announced"] == 1 and plans == [] and len(notes) == 1
    report = auto.cycle(**common)
    assert report["outcome"] == "sucesso" and plans[0].params["trigger"] == executor.AUTO
    assert store.read().history[-1]["outcome"] == "sucesso"


def test_unreadable_rules_or_state_stop_the_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(perf_model, "observe", lambda snap, protected_fn=None: view(psi=9.0))
    bad = tmp_path / "rules.json"
    bad.write_text("{")
    store = perf_auto.AutoStore(tmp_path / "auto.json")
    never = lambda *a, **k: pytest.fail("must not execute")
    common = dict(collector=Collector(), tracker=perf_rules.ConditionTracker(), store=store,
                  notify_fn=never, execute=never, boot_id_fn=lambda: "b")
    assert not auto.cycle(rules_path=bad, **common)["ok"]
    good = tmp_path / "good.json"
    store.path.write_text('{"version": 9}')
    assert not auto.cycle(rules_path=good, **common)["ok"]


def test_unit_text_runs_watch_and_install_needs_confirmation():
    text = auto.unit_text("/x/python")
    assert text.startswith(auto.MARKER) and '"/x/python" -m folego performance watch' in text
    with pytest.raises(ValueError):
        auto.install()
