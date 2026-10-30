"""F2.2/F2.3: o coordenador — uma mutação por vez, entre processos, com consulta.

O que estes testes provam, com processos reais: duas execuções simultâneas do
mesmo ``operation_id`` executam o ato **uma** vez (a segunda consulta o
resultado); uma trava ocupada recusa em vez de esperar para sempre (fila
limitada); intenção sem resultado não é reaplicada às cegas; e porta fechada
(plano expirado, grant inativo, diário corrompido) recusa sem registrar operação
— tentar de novo tem de ser possível.
"""
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path

import pytest

from folego.orchestration import (ActionPlan, ActionResult, Coordinator,
                                  CoordinatorBusy, CorruptJournal, Grant, Journal,
                                  Outcome, ResourceIdentity)

REPO = Path(__file__).resolve().parent.parent
CHILD_TIMEOUT = 30


@pytest.fixture
def coord(tmp_path):
    journal = Journal(tmp_path / "state" / "operations.jsonl")
    return Coordinator(journal=journal, lock_path=tmp_path / "state" / "coordinator.lock")


def a_plan(operation_id="", **over):
    base = {"action": "tmpfs.release",
            "target": ResourceIdentity.entry("1700-abc"),
            "params": {"bytes": 4096}, "operation_id": operation_id}
    base.update(over)
    return ActionPlan(**base)


def ok_result(plan):
    return ActionResult(action=plan.action, outcome=Outcome.OK,
                        operation_id=plan.operation_id, target_key=plan.target.key,
                        effects={"bytes_freed": 4096})


def counting_executor(calls):
    def execute(plan):
        calls.append(plan.operation_id)
        return ok_result(plan)
    return execute


# ------------------------------------------------------------------ em processo

def test_a_run_executes_once_and_records_intent_then_result(coord):
    calls = []
    plan = a_plan()

    result = coord.run(plan, counting_executor(calls))

    assert result.ok and calls == [plan.operation_id]
    records, problems = coord.journal.load()
    assert problems == [] and [r.kind for r in records] == ["intent", "result"]


def test_a_repeated_operation_is_consulted_not_reapplied(coord):
    calls = []
    plan = a_plan()

    first = coord.run(plan, counting_executor(calls))
    second = coord.run(plan, counting_executor(calls))

    assert calls == [plan.operation_id], "o ato não pode rodar duas vezes"
    assert second.to_dict() == first.to_dict()


@pytest.mark.parametrize("error", [OSError(28, "disk full"),
                                  PermissionError(13, "denied"),
                                  CorruptJournal("truncated result")])
def test_result_write_failure_preserves_observed_effect_and_blocks_retry(coord, monkeypatch, error):
    calls = []
    plan = a_plan()

    def fail(result):
        raise error

    monkeypatch.setattr(coord.journal, "append_result", fail)
    result = coord.run(plan, counting_executor(calls))
    assert result.outcome is Outcome.UNKNOWN
    assert result.operation_id == plan.operation_id
    assert result.effects == {"bytes_freed": 4096}
    assert "nada foi feito" not in result.reason
    restarted = Coordinator(journal=Journal(coord.journal.path), lock_path=coord.lock_path)
    retry = restarted.run(plan, counting_executor(calls))
    assert retry.outcome is Outcome.UNKNOWN
    assert calls == [plan.operation_id]


def test_an_intent_without_result_is_not_reapplied(coord):
    calls = []
    plan = a_plan()
    coord.journal.append_intent(plan)

    result = coord.run(plan, counting_executor(calls))

    assert calls == []
    assert result.outcome is Outcome.UNKNOWN
    assert "recuperação pendente" in result.reason


@pytest.mark.parametrize("changes", [
    {"action": "disk.purge"}, {"target": ResourceIdentity.entry("other")},
    {"params": {"bytes": 8192}}, {"expires_at": 9999999999.0},
])
def test_same_id_with_changed_plan_is_refused_after_restart(coord, changes):
    calls = []
    plan = a_plan()
    coord.run(plan, counting_executor(calls))
    restarted = Coordinator(journal=Journal(coord.journal.path), lock_path=coord.lock_path)
    result = restarted.run(replace(plan, **changes), counting_executor(calls))
    assert result.outcome is Outcome.REFUSED
    assert "conflito" in result.reason
    assert calls == [plan.operation_id]


def test_an_expired_plan_is_refused_without_touching_the_journal(coord):
    calls = []
    plan = a_plan(created_at=1000.0, expires_at=2000.0)
    coord._now = lambda: 3000.0

    result = coord.run(plan, counting_executor(calls))

    assert result.outcome is Outcome.REFUSED and "expirado" in result.reason
    assert calls == []
    assert coord.journal.load() == ([], [])


def test_plan_expiring_while_queued_never_executes(coord, monkeypatch):
    clock = [100.0]
    coord._now = lambda: clock[0]

    @contextmanager
    def queued(**kwargs):
        clock[0] = 105.0
        yield

    monkeypatch.setattr(coord, "lock", queued)
    calls = []
    result = coord.run(a_plan(created_at=100.0, expires_at=102.0), counting_executor(calls))
    assert result.outcome is Outcome.REFUSED and "expirado" in result.reason
    assert calls == [] and coord.journal.load() == ([], [])


@pytest.mark.parametrize("change", ["revoke", "pause"])
def test_persisted_authorization_changed_while_queued_blocks_effect(coord, monkeypatch, tmp_path, change):
    import threading
    from folego.orchestration.config import ConfigStore
    from folego.orchestration.grants import GrantStore
    config = ConfigStore(tmp_path / "config.json")
    grants = GrantStore(tmp_path / "grants.json")
    grant = grants.add("tmpfs.release", {"bytes": 4096}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=60)
    config.set_mode("automatico", grant_store=grants)
    coord.config_store, coord.grant_store = config, grants
    calls, results = [], []
    queued = threading.Event()
    original = coord.lock

    @contextmanager
    def waiting(**kwargs):
        queued.set()
        with original(**kwargs):
            yield

    with original():
        monkeypatch.setattr(coord, "lock", waiting)
        worker = threading.Thread(target=lambda: results.append(
            coord.run(a_plan(), counting_executor(calls), grant=grant)))
        worker.start()
        assert queued.wait(2)
        if change == "revoke":
            grants.revoke(grant.grant_id)
        else:
            config.set_paused(True)
    worker.join(3)
    assert not worker.is_alive()
    assert results[0].outcome is Outcome.REFUSED
    assert ("revogado" if change == "revoke" else "pausada") in results[0].reason
    assert calls == [] and coord.journal.load() == ([], [])


def test_current_persisted_authorization_allows_only_the_approved_target(coord, tmp_path):
    from folego.orchestration.config import ConfigStore
    from folego.orchestration.grants import GrantStore
    grants = GrantStore(tmp_path / "grants.json")
    config = ConfigStore(tmp_path / "config.json")
    plan = a_plan()
    grant = grants.add(plan.action, {"bytes": 4096}, resources=(plan.target,))
    config.set_mode("automatico", grant_store=grants)
    coord.config_store, coord.grant_store = config, grants
    calls = []
    assert coord.run(plan, counting_executor(calls), grant=grant).ok
    other = a_plan(target=ResourceIdentity.entry("other"))
    refused = coord.run(other, counting_executor(calls), grant=grant)
    assert refused.outcome is Outcome.REFUSED
    assert calls == [plan.operation_id]


def test_bridge_keeps_domain_result_if_unlock_fails_after_effect(coord, tmp_path, monkeypatch):
    from folego.orchestration.bridge import perform
    original = coord.lock
    payload = tmp_path / "effect"

    @contextmanager
    def failing_unlock(**kwargs):
        with original(**kwargs):
            yield
        raise OSError("unlock failed after effect")

    monkeypatch.setattr(coord, "lock", failing_unlock)
    def act():
        payload.write_bytes(b"observed effect")
        return {"written": 15}
    result = perform(coordinator=coord, action="tmpfs.release",
                     target=ResourceIdentity.entry("managed"), params={"bytes": 15},
                     act=act, verdict=lambda domain, key: ActionResult(
                         action="tmpfs.release", outcome=Outcome.OK, target_key=key,
                         effects=domain))
    assert payload.read_bytes() == b"observed effect"
    assert result.result == {"written": 15}
    assert result.verdict.outcome is Outcome.UNKNOWN
    assert result.verdict.effects == {"written": 15}
    assert "nada foi feito" not in result.verdict.reason


def test_legacy_plan_can_be_queried_but_never_started(coord):
    calls = []
    legacy = a_plan(plan_version=1)
    assert coord.run(legacy, counting_executor(calls)).outcome is Outcome.REFUSED
    coord.journal.append_intent(legacy)
    coord.journal.append_result(ok_result(legacy))
    assert coord.run(legacy, counting_executor(calls)).ok
    assert calls == []


def test_an_inactive_grant_refuses_before_the_journal(coord):
    calls = []
    grant = Grant("g-1", "tmpfs.release", {"bytes": 4096}, issued_at=1000.0,
                 revoked_at=1100.0)
    coord._now = lambda: 1200.0

    result = coord.run(a_plan(), counting_executor(calls), grant=grant)

    assert result.outcome is Outcome.REFUSED and "revogado" in result.reason
    assert calls == [] and coord.journal.load() == ([], [])


def test_a_grant_out_of_scope_refuses_before_the_journal(coord):
    calls = []
    grant = Grant("g-1", "tmpfs.release", {"bytes": 100}, issued_at=1000.0,
                  resources=(a_plan().target,), expires_at=5000.0)
    coord._now = lambda: 1200.0

    result = coord.run(a_plan(), counting_executor(calls), grant=grant)

    assert result.outcome is Outcome.REFUSED and "excede" in result.reason
    assert calls == [] and coord.journal.load() == ([], [])


def test_an_executor_exception_becomes_an_unknown_result_in_the_journal(coord):
    def explode(plan):
        raise RuntimeError("o executor caiu")

    result = coord.run(a_plan(), explode)

    assert result.outcome is Outcome.UNKNOWN and "RuntimeError" in result.reason
    state = coord.journal.state_of(result.operation_id)
    assert state.result is not None and state.result.outcome is Outcome.UNKNOWN


def test_an_executor_that_breaks_the_contract_gets_an_unknown_result(coord):
    def wrong(plan):
        return ActionResult(action=plan.action, outcome=Outcome.OK,
                            operation_id="outra-operacao")

    result = coord.run(a_plan(), wrong)

    assert result.outcome is Outcome.UNKNOWN
    assert "outra operação" in result.reason


def test_a_corrupt_journal_refuses_the_mutation(coord):
    calls = []
    coord.journal.path.parent.mkdir(parents=True, exist_ok=True)
    coord.journal.path.write_text("isto não é JSON\n")

    result = coord.run(a_plan(), counting_executor(calls))

    assert result.outcome is Outcome.REFUSED
    assert "diário inconsistente" in result.reason
    assert calls == []


def test_the_lock_refuses_when_the_deadline_is_up(coord):
    plan = a_plan()
    with coord.lock():
        calls = []
        result = coord.run(plan, counting_executor(calls), wait=0.0)

    assert result.outcome is Outcome.REFUSED and "outro processo" in result.reason
    assert calls == [], "trava ocupada não pode executar por baixo"


# ------------------------------------------------------------ entre processos

HOLDER = r"""
import sys, time
from pathlib import Path
from folego.orchestration import Coordinator, Journal

lock, journal, hold = sys.argv[1:4]
c = Coordinator(journal=Journal(Path(journal)), lock_path=Path(lock))
with c.lock():
    print("locked", flush=True)
    time.sleep(float(hold))
"""

SAME_OP_CHILD = r"""
import json, sys, time
from pathlib import Path
from folego.orchestration import (ActionPlan, ActionResult, Coordinator, Journal,
                                  Outcome)

lock, journal, plan_path, count_path = sys.argv[1:5]
plan = ActionPlan.from_dict(json.loads(Path(plan_path).read_text()))
def execute(p):
    with open(count_path, "a", encoding="utf-8") as fh:
        fh.write("x\n")
    time.sleep(0.4)
    return ActionResult(action=p.action, outcome=Outcome.OK,
                        operation_id=p.operation_id, target_key=p.target.key,
                        effects={"execucoes": 1})
coord = Coordinator(journal=Journal(Path(journal)), lock_path=Path(lock))
result = coord.run(plan, execute, wait=10)
print(json.dumps(result.to_dict(), ensure_ascii=False))
"""


def child_env():
    return dict(os.environ, PYTHONPATH=str(REPO / "src"))


def test_a_held_lock_makes_the_other_process_wait_and_then_proceed(tmp_path):
    state = tmp_path / "state"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(state / "coordinator.lock"),
         str(state / "operations.jsonl"), "0.6"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=child_env())
    try:
        assert holder.stdout.readline().strip() == "locked"
        coord = Coordinator(journal=Journal(state / "operations.jsonl"),
                            lock_path=state / "coordinator.lock")
        calls = []

        busy = coord.run(a_plan("op-a"), counting_executor(calls), wait=0.0)
        assert busy.outcome is Outcome.REFUSED and calls == []

        waited = coord.run(a_plan("op-a"), counting_executor(calls), wait=5.0)
        assert waited.ok and calls == ["op-a"], "depois da trava livre, o ato roda"
    finally:
        holder.communicate(timeout=CHILD_TIMEOUT)


def test_two_processes_running_the_same_operation_execute_it_once(tmp_path):
    state = tmp_path / "state"
    plan = a_plan("op-concorrente")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan.to_dict(), ensure_ascii=False))
    count_file = tmp_path / "execucoes.txt"
    argv = [sys.executable, "-c", SAME_OP_CHILD, str(state / "coordinator.lock"),
            str(state / "operations.jsonl"), str(plan_file), str(count_file)]

    procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=child_env()) for _ in range(2)]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=CHILD_TIMEOUT)
        assert proc.returncode == 0, err
        outputs.append(json.loads(out.strip().splitlines()[-1]))

    assert [o["outcome"] for o in outputs] == ["sucesso", "sucesso"]
    assert count_file.read_text().count("x") == 1, "o ato não pode rodar duas vezes"
    assert {o["operation_id"] for o in outputs} == {"op-concorrente"}
    journal = Journal(state / "operations.jsonl")
    records, problems = journal.load()
    assert problems == []
    assert [r.kind for r in records] == ["intent", "result"]


def test_a_lock_held_by_a_child_is_visible_to_the_parent(coord):
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(coord.lock_path),
         str(coord.journal.path), "0.3"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=child_env())
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert os.path.exists(coord.lock_path)
        with pytest.raises(CoordinatorBusy):
            with coord.lock(wait=0.0):
                pass
    finally:
        holder.communicate(timeout=CHILD_TIMEOUT)
