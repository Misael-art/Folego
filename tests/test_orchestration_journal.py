"""F2.2: diário de intenção — a intenção entra antes do efeito, a linha é durável.

O diário é a testemunha da operação: se o executor cai depois da intenção e antes
do resultado, o estado fica "intenção" (nunca "sucesso", nunca "nada"); se a
última linha foi truncada por uma queda no meio da escrita, o diário denuncia a
cauda em vez de fingir que ela não existe.
"""
import json
import os

import pytest

from folego.orchestration.journal import CorruptJournal, Journal
from folego.orchestration.models import (ActionPlan, ActionResult, OperationStatus,
                                         Outcome, ResourceIdentity)


@pytest.fixture
def book(tmp_path):
    return Journal(tmp_path / "state" / "operations.jsonl")


def a_plan(operation_id="op-1", **over):
    base = {"action": "tmpfs.release", "target": ResourceIdentity.entry("1700-abc"),
            "params": {"bytes": 4096}, "operation_id": operation_id}
    base.update(over)
    return ActionPlan(**base)


def a_result(operation_id="op-1", outcome=Outcome.OK):
    return ActionResult(action="tmpfs.release", outcome=outcome,
                        operation_id=operation_id, target_key="1700-abc")


def test_an_empty_journal_is_empty_not_an_error(book):
    records, problems = book.load()

    assert records == [] and problems == []
    assert book.state_of("op-1") is None


@pytest.mark.parametrize("change", ["id", "action", "target"])
def test_result_identity_corruption_cannot_be_returned_as_a_previous_success(book, change):
    book.append_intent(a_plan())
    book.append_result(a_result())
    rows = [json.loads(line) for line in book.path.read_text().splitlines()]
    result = rows[-1]["result"]
    result[{"id": "operation_id", "action": "action", "target": "target_key"}[change]] = {
        "id": "foreign", "action": "disk.purge", "target": "foreign-target"}[change]
    book.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(CorruptJournal):
        book.state_of("op-1")


def test_short_writes_are_completed_before_intent_is_accepted(book, monkeypatch):
    original = os.write

    def short_write(fd, payload):
        return original(fd, payload[:7])

    monkeypatch.setattr(os, "write", short_write)
    plan = a_plan()
    book.append_intent(plan)
    records, problems = book.load()
    assert problems == []
    assert len(records) == 1 and records[0].plan.to_dict() == plan.to_dict()


def test_intent_then_result_roundtrips_with_increasing_sequence(book):
    plan = a_plan()
    intent = book.append_intent(plan)
    result = book.append_result(a_result())

    assert (intent.seq, result.seq) == (1, 2)
    records, problems = book.load()
    assert problems == []
    assert [r.kind for r in records] == ["intent", "result"]
    state = book.state_of("op-1")
    assert state.status is OperationStatus.COMPLETED
    assert state.intent == plan and state.result == a_result()
    assert (state.intent_seq, state.result_seq) == (1, 2)


def test_an_intent_without_result_is_intended_never_success(book):
    book.append_intent(a_plan())

    state = book.state_of("op-1")

    assert state.status is OperationStatus.INTENDED
    assert state.result is None and state.intent is not None


def test_the_journal_is_append_only_across_reads(book):
    book.append_intent(a_plan("op-1"))
    before = book.path.read_text()

    book.append_intent(a_plan("op-2"))

    assert book.path.read_text().startswith(before)


def test_a_torn_tail_is_a_problem_and_blocks_state_by_default(book):
    book.append_intent(a_plan())
    book.append_result(a_result())
    with book.path.open("a") as fh:
        fh.write('{"schema": 1, "seq": 3, "operation_id"')  # queda no meio da escrita

    records, problems = book.load()
    assert [r.seq for r in records] == [1, 2]
    assert any("linha 3" in p for p in problems)
    with pytest.raises(CorruptJournal):
        book.state_of("op-1")
    assert book.state_of("op-1", allow_problems=True).status is OperationStatus.COMPLETED


def test_an_interior_garbage_line_is_a_problem(book):
    book.append_intent(a_plan("op-1"))
    book.append_intent(a_plan("op-2"))
    lines = book.path.read_text().splitlines()
    book.path.write_text("\n".join([lines[0], "isto não é JSON", lines[1]]) + "\n")

    records, problems = book.load()

    assert any("linha 2" in p for p in problems)
    assert [r.operation_id for r in records] == ["op-1", "op-2"]
    with pytest.raises(CorruptJournal):
        book.state_of("op-1")


def test_a_sequence_gap_is_a_problem(book):
    book.append_intent(a_plan("op-1"))
    row = json.loads(book.path.read_text().splitlines()[0])
    row["seq"] = 7
    book.path.write_text(json.dumps(row) + "\n")

    _, problems = book.load()

    assert any("sequência" in p for p in problems)


def test_appending_to_a_corrupt_journal_refuses(book):
    book.append_intent(a_plan())
    with book.path.open("a") as fh:
        fh.write("{quebrado\n")

    with pytest.raises(CorruptJournal):
        book.append_intent(a_plan("op-2"))


def test_the_journal_file_is_private(book):
    import stat as stat_mod

    book.append_intent(a_plan())

    assert stat_mod.S_IMODE(book.path.stat().st_mode) == 0o600


def test_a_result_without_intent_is_reported_as_completed_without_inventing_a_plan(book):
    book.append_result(a_result("op-solto"))

    state = book.state_of("op-solto")

    assert state.status is OperationStatus.COMPLETED
    assert state.intent is None and state.result is not None
