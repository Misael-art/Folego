"""F2: a ponte dos atos de disco com o coordenador — intenção antes, veredito depois.

O que se prende aqui é o contrato da ponte com o domínio de verdade num chão
falso (alvo e quarentena no `tmp_path`): a intenção entra no diário antes de o
ato rodar; recusa de flag responde direto, sem diário; recusa do domínio vira
resultado registrado, com o vocabulário estruturado; porta fechada (diário
corrompido) recusa sem executar; os vereditos distinguem sucesso e recusa e
trazem os efeitos observados, não os supostos. O `reconcile` só entra no diário
quando há reparo pendente; manifesto inconsistente ou decisão manual aparecem no
veredito. O caminho real de ponta a ponta pelo `cli.main` é preso em
`test_cli_disk.py`.
"""
import json
import shutil

import pytest

from folego.actions.disk import coordinated
from folego.actions.disk.quarantine import Quarantine
from folego.orchestration import Coordinator, Journal, Outcome
from folego.safely.audit import AuditLog


@pytest.fixture
def coord(tmp_path):
    return Coordinator(journal=Journal(tmp_path / "state" / "operations.jsonl"),
                       lock_path=tmp_path / "state" / "coordinator.lock")


@pytest.fixture
def book(tmp_path):
    return Quarantine(root=tmp_path / "quarentena", allowed_roots=[tmp_path],
                      audit=AuditLog(tmp_path / "state" / "audit.jsonl"))


@pytest.fixture
def alvo(tmp_path):
    tree = tmp_path / "projeto-antigo"
    (tree / "target").mkdir(parents=True)
    (tree / "target" / "lixo.bin").write_bytes(b"a" * 2048)
    return tree


def _records(coord):
    records, problems = coord.journal.load()
    assert problems == []
    return records


def test_intent_lands_before_the_domain_act(coord, book, alvo, tmp_path):
    """A ordem é o contrato: quando o rename acontece, a intenção já está no diário."""
    journal = tmp_path / "state" / "operations.jsonl"

    class Spy:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def move_in(self, path, *, action_id="disk.quarantine", **kwargs):
            text = journal.read_text(encoding="utf-8")
            assert '"kind": "intent"' in text, "o ato rodou antes do registro"
            return self.inner.move_in(path, action_id=action_id, **kwargs)

    run = coordinated.quarantine(coordinator=coord, confirm=True, book=Spy(book),
                                 path=alvo)

    assert run.result.ok
    assert not alvo.exists()


def test_a_confirmed_quarantine_records_intent_before_result(coord, book, alvo):
    run = coordinated.quarantine(coordinator=coord, confirm=True, book=book,
                                 path=alvo)

    assert not alvo.exists()
    assert run.result.ok and run.result.entry.state == "stored"
    assert run.verdict.outcome is Outcome.OK
    assert run.verdict.target_key == str(alvo)
    records = _records(coord)
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[0].plan.action == "disk.quarantine"
    assert records[0].plan.target.kind == "path"
    assert records[0].plan.target.key == str(alvo)
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["entry_id"] == run.result.entry.entry_id
    assert records[1].result.effects["bytes"] == 2048


def test_change_after_manifest_write_is_refused_before_rename(coord, book, alvo, monkeypatch):
    from folego.actions.disk.review import plan_quarantine
    reviewed = plan_quarantine(alvo, book)
    original_write = book._write
    payload = alvo / "target/lixo.bin"
    def changed(rows):
        original_write(rows)
        payload.write_bytes(b"new useful work")
    monkeypatch.setattr(book, "_write", changed)
    run = coordinated.quarantine(coordinator=coord, confirm=True, book=book,
                                 path=alvo, reviewed_plan=reviewed)
    assert run.verdict.outcome is Outcome.REFUSED
    assert payload.read_bytes() == b"new useful work"
    entries = list(book.entries().values())
    assert len(entries) == 1 and entries[0].state == "planned"
    from pathlib import Path
    assert not Path(entries[0].stored).exists()


def test_an_unconfirmed_quarantine_never_touches_the_journal(coord, book, alvo):
    run = coordinated.quarantine(coordinator=coord, confirm=False, book=book,
                                 path=alvo)

    assert not run.result.ok
    assert "--confirmar" in run.result.reason
    assert run.verdict is None
    assert alvo.exists(), "a recusa de flag não pode ter tocado no alvo"
    assert not coord.journal.path.exists(), "flag recusada não é operação"


def test_purge_without_the_irreversible_flag_never_touches_the_journal(coord, book,
                                                                       alvo):
    entry = book.move_in(alvo)  # o item precisa existir para haver o que purgar
    run = coordinated.purge(coordinator=coord, confirm=True, irreversible=False,
                            book=book, entry_id=entry.entry_id)

    assert not run.result.ok
    assert "--irreversivel" in run.result.reason
    assert run.verdict is None
    assert book.entries()[entry.entry_id].state == "stored"
    assert not coord.journal.path.exists()


def test_a_domain_refusal_is_recorded_with_the_structured_vocabulary(coord, book,
                                                                     tmp_path):
    run = coordinated.quarantine(coordinator=coord, confirm=True, book=book,
                                 path=tmp_path / "não-existe")

    assert not run.result.ok
    assert run.verdict.outcome is Outcome.REFUSED
    records = _records(coord)
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[1].result.outcome is Outcome.REFUSED
    assert records[1].result.reason.startswith("refused:")


def test_a_corrupt_journal_closes_the_door_before_the_act(coord, book, alvo, tmp_path):
    journal = tmp_path / "state" / "operations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("lixo\n", encoding="utf-8")

    run = coordinated.quarantine(coordinator=coord, confirm=True, book=book,
                                 path=alvo)

    assert run.result is None, "sem intenção registrada, o rename não pode ter rodado"
    assert run.verdict.outcome is Outcome.REFUSED
    assert "diário inconsistente" in run.verdict.reason
    assert alvo.exists()
    assert book.entries() == {}
    assert journal.read_text(encoding="utf-8") == "lixo\n", "nada anexado por cima"


def test_restore_is_journaled_with_the_observed_state(coord, book, alvo):
    entry = book.move_in(alvo)

    run = coordinated.restore(coordinator=coord, confirm=True, book=book,
                              entry_id=entry.entry_id)

    assert run.result.ok
    assert run.result.entry.state == "restored"
    assert (alvo / "target" / "lixo.bin").read_bytes() == b"a" * 2048
    records = _records(coord)
    assert records[0].plan.action == "disk.restore"
    assert records[0].plan.target.kind == "entry"
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["state"] == "restored"
    assert records[1].result.effects["bytes"] == 2048


def test_restore_of_an_unknown_entry_is_recorded_as_recusa(coord, book):
    run = coordinated.restore(coordinator=coord, confirm=True, book=book,
                              entry_id="não-existe")

    assert not run.result.ok
    assert run.verdict.outcome is Outcome.REFUSED
    records = _records(coord)
    assert records[1].result.outcome is Outcome.REFUSED
    assert records[1].result.effects == {}, "sem entrada tocada, sem efeito inventado"


def test_a_confirmed_purge_deletes_and_is_journaled(coord, book, alvo):
    entry = book.move_in(alvo)

    run = coordinated.purge(coordinator=coord, confirm=True, irreversible=True,
                            book=book, entry_id=entry.entry_id)

    assert run.result.ok
    assert run.result.entry.state == "purged"
    assert not alvo.exists()
    records = _records(coord)
    assert records[0].plan.action == "disk.purge"
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["entry_id"] == entry.entry_id


def test_a_guard_refusal_on_purge_is_recorded_not_raised(coord, book, alvo, tmp_path):
    """O `_check` do domínio explode em PermissionError; a ponte a transforma em recusa."""
    entry = book.move_in(alvo)
    negado = Quarantine(root=book.root, allowed_roots=[tmp_path / "fora"], audit=None)

    run = coordinated.purge(coordinator=coord, confirm=True, irreversible=True,
                            book=negado, entry_id=entry.entry_id)

    assert not run.result.ok
    assert run.verdict.outcome is Outcome.REFUSED
    assert book.entries()[entry.entry_id].state == "stored", "nada foi apagado"
    assert (book.entries()[entry.entry_id].stored and
            (tmp_path / "quarentena").exists())
    records = _records(coord)
    assert records[1].result.outcome is Outcome.REFUSED


def _make_repair_pending(book, entry_id):
    """Finge a janela de queda: o rename concluiu, mas a linha ficou `planned`."""
    raw = json.loads(book.manifest_path.read_text())
    for row in raw["entries"]:
        if row["entry_id"] == entry_id:
            row["state"] = "planned"
    book.manifest_path.write_text(json.dumps(raw))


def test_reconcile_without_pending_repairs_never_touches_the_journal(coord, book,
                                                                    alvo):
    book.move_in(alvo)  # entrada sã: nada a reparar

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result is not None and not run.result.mutated
    assert run.verdict is None, "listar continua sendo ler"
    assert not coord.journal.path.exists()


def test_reconcile_repairs_under_the_door_and_is_journaled(coord, book, alvo):
    entry = book.move_in(alvo)
    _make_repair_pending(book, entry.entry_id)

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result.repaired == (entry.entry_id,)
    assert book.entries()[entry.entry_id].state == "stored"
    assert run.verdict.outcome is Outcome.OK
    records = _records(coord)
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[0].plan.action == "disk.reconcile"
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["repaired"] == [entry.entry_id]


def test_reconcile_manual_only_is_a_read_not_an_operation(coord, book, alvo):
    """Ambos os lados sumiram: vira decisão manual relatada, não operação registrada."""
    entry = book.move_in(alvo)
    _make_repair_pending(book, entry.entry_id)
    shutil.rmtree(book.entries()[entry.entry_id].stored)

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result.manual == (entry.entry_id,)
    assert run.verdict is None, "decisão manual já foi relatada; nada a registrar"
    assert not coord.journal.path.exists()
    assert book.entries()[entry.entry_id].state == "planned"


def test_reconcile_with_manual_leftovers_is_partial(coord, book, alvo, tmp_path):
    """Repara o que dava e nomeia o ambíguo: sucesso parcial, não varredura muda."""
    first = book.move_in(alvo)
    _make_repair_pending(book, first.entry_id)
    outro = tmp_path / "outro"
    (outro / "x").mkdir(parents=True)
    second = book.move_in(outro)
    _make_repair_pending(book, second.entry_id)
    shutil.rmtree(book.entries()[second.entry_id].stored)

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result.repaired == (first.entry_id,)
    assert run.result.manual == (second.entry_id,)
    assert run.verdict.outcome is Outcome.PARTIAL
    records = _records(coord)
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[1].result.outcome is Outcome.PARTIAL
    assert records[1].result.effects["manual"] == [second.entry_id]
    assert book.entries()[first.entry_id].state == "stored"
    assert book.entries()[second.entry_id].state == "planned", "nada foi fechado"


def test_a_corrupt_manifest_keeps_reconcile_out_of_the_journal(coord, book, tmp_path):
    book.root.mkdir(parents=True, exist_ok=True)
    book.manifest_path.write_text("lixo{")

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result is not None and run.result.problems
    assert run.verdict is None, "manifesto ilegível não é operação: é porta fechada"
    assert not coord.journal.path.exists()


def test_a_corrupt_journal_keeps_the_repair_out_of_the_manifest(coord, book, alvo,
                                                                tmp_path):
    entry = book.move_in(alvo)
    _make_repair_pending(book, entry.entry_id)
    journal = tmp_path / "state" / "operations.jsonl"
    journal.write_text("lixo\n", encoding="utf-8")

    run = coordinated.reconcile(coordinator=coord, book=book)

    assert run.result is None, "sem intenção registrada, o reparo não pode rodar"
    assert run.verdict.outcome is Outcome.REFUSED
    assert "diário inconsistente" in run.verdict.reason
    assert book.entries()[entry.entry_id].state == "planned", "nada foi reescrito"
    assert journal.read_text(encoding="utf-8") == "lixo\n"
