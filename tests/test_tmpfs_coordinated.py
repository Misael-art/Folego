"""F2: a ponte dos atos de tmpfs com o coordenador — intenção antes, veredito depois.

O que se prende aqui é o contrato da ponte, com atos de mentira: a intenção entra
no diário antes de o executor rodar; recusa do domínio também vira resultado
registrado, com o vocabulário estruturado; porta fechada (diário corrompido ou
sem escrita) recusa sem executar; dry-run e recusa de flag respondem direto pelo
domínio, sem diário; e os vereditos distinguem sucesso, parcial e recusa. O
caminho real (`release`/`restore`/`expire`/`recover` de verdade, com chão falso) é
preso em `test_cli_tmpfs.py`, que é quem tem o fixture do tmpfs.
"""
from types import SimpleNamespace

import pytest

from folego.actions.tmpfs import coordinated
from folego.actions.tmpfs.ledger import MAX_RETAINED_BYTES, Ledger
from folego.actions.tmpfs.release import (ExpireResult, RecoverResult, ReleaseResult,
                                          RestoreResult)
from folego.orchestration import (ActionResult, Coordinator, Journal, Outcome,
                                  ResourceIdentity)


@pytest.fixture
def coord(tmp_path):
    return Coordinator(journal=Journal(tmp_path / "state" / "operations.jsonl"),
                       lock_path=tmp_path / "state" / "coordinator.lock")


def call_perform(coord, act, verdict, *, action="tmpfs.release", key="alvo-1"):
    return coordinated.perform(coordinator=coord, action=action,
                               target=ResourceIdentity.entry(key),
                               params={"bytes": 4096}, act=act, verdict=verdict)


def test_a_coordinated_act_records_intent_before_result_and_returns_both_faces(coord):
    calls = []

    def act():
        calls.append("rodou")
        return ReleaseResult(True, "1700-abc", "ok", bytes=4096, stored="/ssd/x",
                             sha256="a" * 64, freed_bytes=4096)

    run = call_perform(coord, act, coordinated._verdict_release, key="1700-abc")

    assert calls == ["rodou"]
    assert run.result.entry_id == "1700-abc"
    assert run.verdict.ok
    assert run.verdict.target_key == "1700-abc"
    records, problems = coord.journal.load()
    assert problems == []
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[0].plan.action == "tmpfs.release"
    assert records[0].plan.params == {"bytes": 4096}
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["entry_id"] == "1700-abc"


def test_a_domain_refusal_is_recorded_with_the_structured_vocabulary(coord):
    """Recusa do domínio é resultado registrado, não silêncio: o diário a conta."""
    recusa = ReleaseResult(False, "1700-abc", "refused: o destino não tem folga")
    run = call_perform(coord, lambda: recusa, coordinated._verdict_release)

    assert run.result is recusa
    assert run.verdict.outcome is Outcome.REFUSED
    records, _ = coord.journal.load()
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[1].result.outcome is Outcome.REFUSED
    assert records[1].result.reason == "refused: o destino não tem folga"


def test_a_corrupt_journal_closes_the_door_before_the_act(coord, tmp_path):
    journal = tmp_path / "state" / "operations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("lixo\n", encoding="utf-8")
    calls = []

    run = call_perform(coord, lambda: calls.append("rodou"),
                       lambda r, key: ActionResult(action="tmpfs.release",
                                                   outcome=Outcome.OK))

    assert calls == [], "o ato não pode rodar sobre um diário que não fecha"
    assert run.result is None
    assert run.verdict.outcome is Outcome.REFUSED
    assert "diário inconsistente" in run.verdict.reason
    assert journal.read_text() == "lixo\n", "nada foi anexado por cima do problema"


def test_a_journal_that_cannot_be_read_closes_the_door_before_the_act(coord, tmp_path):
    """Ilegível também é porta fechada: sem registro da intenção, sem mutação."""
    (tmp_path / "state" / "operations.jsonl").mkdir(parents=True)
    calls = []

    run = call_perform(coord, lambda: calls.append("rodou"),
                       lambda r, key: ActionResult(action="tmpfs.release",
                                                   outcome=Outcome.OK))

    assert calls == []
    assert run.result is None and run.verdict.outcome is Outcome.REFUSED
    assert "não foi possível registrar a intenção" in run.verdict.reason


def test_the_release_verdict_distinguishes_the_retained_clone():
    """Clone na SSD e origem intacta é parcial; sem clone, é recusa de verdade."""
    parcial = ReleaseResult(False, "e", "refused: o clone está em /ssd/x e "
                                        "registrado como partial",
                            bytes=10, stored="/ssd/x", sha256="a" * 64)
    assert coordinated._verdict_release(parcial, "alvo").outcome is Outcome.PARTIAL

    limpa = ReleaseResult(False, "e", "refused: o destino não tem folga")
    assert coordinated._verdict_release(limpa, "alvo").outcome is Outcome.REFUSED

    ok = ReleaseResult(True, "e", "ok", bytes=10, stored="/ssd/x", sha256="a" * 64,
                       freed_bytes=10)
    assert coordinated._verdict_release(ok, "alvo").outcome is Outcome.OK


def test_the_expire_verdict_names_partial_never_a_clean_success_on_errors():
    ok = ExpireResult(True, "expiradas 1 entrada(s), 10 bytes liberados da SSD",
                      ("a",), 10)
    assert coordinated._verdict_expire(ok, "g").outcome is Outcome.OK

    com_erro = ExpireResult(True, "expiradas 1 entrada(s), 10 bytes liberados da SSD",
                            ("a",), 10, ("b: o payload já não existia",))
    verdict = coordinated._verdict_expire(com_erro, "g")
    assert verdict.outcome is Outcome.PARTIAL
    assert verdict.errors == ("b: o payload já não existia",)

    recusa = ExpireResult(False, "refused: faltou --irreversivel")
    assert coordinated._verdict_expire(recusa, "g").outcome is Outcome.REFUSED


def test_the_restore_verdict_maps_ok_and_refusal():
    ok = RestoreResult(True, "e", "ok", bytes=10, restored_to="/tmp/x")
    assert coordinated._verdict_restore(ok, "e").outcome is Outcome.OK

    recusa = RestoreResult(False, "e", "refused: a entrada está restored")
    assert coordinated._verdict_restore(recusa, "e").outcome is Outcome.REFUSED


def test_the_recover_verdict_names_partial_when_something_remains_pending():
    limpo = RecoverResult(True, "recuperação: 1 clone(s) inacabado(s) descartado(s), "
                                "0 mantido(s) para decisão manual", ("e1",))
    assert coordinated._verdict_recover(limpo, "g").outcome is Outcome.OK

    # clone preservado para decisão manual: o assunto não fechou
    pendente = RecoverResult(True, "recuperação: 0 descartado(s), 1 mantido(s)",
                             (), ("e2",), ("e2: a origem sumiu",))
    verdict = coordinated._verdict_recover(pendente, "g")
    assert verdict.outcome is Outcome.PARTIAL
    assert verdict.effects["kept"] == ["e2"] and verdict.effects["notes"] == \
        ["e2: a origem sumiu"]

    # falha relatada (guard recusou o clone): parcial nomeado, nunca sucesso limpo
    com_erro = RecoverResult(False, "recuperação: 0 descartado(s), 0 mantido(s)",
                             (), (), (), ("e3: allowed root",))
    verdict = coordinated._verdict_recover(com_erro, "g")
    assert verdict.outcome is Outcome.PARTIAL
    assert verdict.errors == ("e3: allowed root",)


def _seed_staging(ledger, *, entry_id, src, stored):
    ledger.append(entry_id=entry_id, src=str(src), volume=str(src), stored=str(stored),
                  bytes=0, sha256="", age_days=1.0, matched_pattern=None,
                  holder_pids=(), state="staging", action_id="tmpfs.release",
                  audit_event_id="")


def test_recover_without_confirmation_is_a_dry_run_that_leaves_everything_alone(
        coord, tmp_path):
    ledger = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    origem, clone = tmp_path / "origem", tmp_path / "ssd" / "clone"
    origem.mkdir()
    (origem / "x.bin").write_text("x")
    clone.mkdir(parents=True)
    (clone / "x.bin").write_text("x")
    _seed_staging(ledger, entry_id="st-1", src=origem, stored=clone)

    run = coordinated.recover(coordinator=coord, confirm=False, ledger=ledger,
                              audit=None, allowed_roots=[tmp_path])

    assert run.verdict is None and run.result.dry_run is True
    assert run.result.dropped == ("st-1",)
    assert clone.exists() and ledger.find(str(origem)).state == "staging"
    assert not (tmp_path / "state" / "operations.jsonl").exists(), \
        "dry-run não entra no diário"


def test_a_confirmed_recover_is_coordinated_and_recorded(coord, tmp_path):
    ledger = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    origem, clone = tmp_path / "origem", tmp_path / "ssd" / "clone"
    origem.mkdir()
    (origem / "x.bin").write_text("x")
    clone.mkdir(parents=True)
    (clone / "x.bin").write_text("x")
    _seed_staging(ledger, entry_id="st-1", src=origem, stored=clone)

    run = coordinated.recover(coordinator=coord, confirm=True, ledger=ledger,
                              audit=None, allowed_roots=[tmp_path])

    assert run.result.ok is True and run.result.dropped == ("st-1",)
    assert run.verdict.outcome is Outcome.OK
    records, problems = coord.journal.load()
    assert problems == []
    assert [r.kind for r in records] == ["intent", "result"]
    assert records[0].plan.action == "tmpfs.recover"
    assert records[0].plan.target.kind == "group"
    assert records[0].plan.target.key == "tmpfs.staging"
    assert records[1].result.outcome is Outcome.OK
    assert records[1].result.effects["dropped"] == ["st-1"]
    assert not clone.exists()
    assert ledger.find(str(origem)).state == "dropped"


def test_a_recover_that_keeps_a_clone_is_recorded_as_parcial(coord, tmp_path):
    """Origem sumida vira parcial no diário: o clone não certificado fica intocado."""
    ledger = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    clone = tmp_path / "ssd" / "clone"
    clone.mkdir(parents=True)
    (clone / "x.bin").write_text("x")
    _seed_staging(ledger, entry_id="st-2", src=tmp_path / "sumiu", stored=clone)

    run = coordinated.recover(coordinator=coord, confirm=True, ledger=ledger,
                              audit=None, allowed_roots=[tmp_path])

    assert run.result.kept == ("st-2",)
    assert run.verdict.outcome is Outcome.PARTIAL
    records, _ = coord.journal.load()
    assert records[1].result.outcome is Outcome.PARTIAL
    assert records[1].result.effects["kept"] == ["st-2"]
    assert clone.exists(), "o clone que pode ser a única cópia não é apagado"


def test_without_confirmation_the_verbs_answer_directly_and_leave_the_journal_alone(
        coord, tmp_path):
    """O portão `if not confirm` responde antes de ledger e política: nada é orquestrado.

    `plan=None` de propósito: com a recusa de flag o domínio não toca o plano, nem o
    ledger (contrato pinado em `release.py` e nos testes da CLI). O item é um stub
    porque `release_item` lê `item.path` antes do portão; se alguém reordenar o
    portão, este teste explode em vez de gravar uma operação que nunca aconteceria.
    """
    item = SimpleNamespace(path="/tmp/qualquer", bytes=1, volume="/tmp")
    run = coordinated.release(coordinator=coord, confirm=False, plan=None, item=item,
                              ledger=None, dest_root=None, audit=None,
                              allowed_roots=None)
    assert run.result.ok is False and "--confirmar" in run.result.reason
    assert run.verdict is None

    run = coordinated.restore(coordinator=coord, confirm=False, target="id-qualquer",
                              ledger=None, audit=None, allowed_roots=None)
    assert run.result.ok is False and "--confirmar" in run.result.reason
    assert run.verdict is None

    run = coordinated.expire(coordinator=coord, confirm=False, irreversible=False,
                             ledger=Ledger(tmp_path / "state" / "tmp-ledger.jsonl"),
                             audit=None, days=14, max_bytes=1024, allowed_roots=None)
    assert run.result.ok is True and "nada vencido" in run.result.reason
    assert run.verdict is None

    assert not (tmp_path / "state" / "operations.jsonl").exists(), \
        "dry-run/recusa de flag não entra no diário"


def test_expire_with_a_real_victim_but_one_flag_missing_is_not_coordinated(coord,
                                                                            tmp_path):
    """XOR de flags: com vítima de verdade, a recusa do domínio não vira operação."""
    ledger = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    ledger.append(entry_id="v-1", src="/tmp/vencido", volume="/tmp",
                  stored=str(tmp_path / "ssd" / "v-1"), bytes=MAX_RETAINED_BYTES + 1,
                  sha256="0" * 64, age_days=1.0, matched_pattern=None,
                  holder_pids=(), state="released", action_id="tmpfs.release")

    run = coordinated.expire(coordinator=coord, confirm=True, irreversible=False,
                             ledger=ledger, audit=None, days=14,
                             max_bytes=MAX_RETAINED_BYTES, allowed_roots=None)

    assert run.result.ok is False and "--irreversivel" in run.result.reason
    assert run.verdict is None
    assert not (tmp_path / "state" / "operations.jsonl").exists()
