"""Sondas da revisão: só executores falsos e estado descartável em .scratch.

Uso: .venv/bin/python docs/reviews/2026-10-18/evidencias/reproduzir.py
     .venv/bin/python docs/reviews/2026-10-18/evidencias/reproduzir.py --ci-sem-qt

O JSON descreve o comportamento observado; não é um teste que exige manter bugs.
Não sinaliza processos, não consulta daemons e não muda HOME/XDG do usuário.
"""
from __future__ import annotations

import contextlib
import importlib.abc
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))


def ci_sem_qt():
    class NoQt(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"PySide6", "shiboken6"}:
                raise ModuleNotFoundError(
                    "Qt deliberately unavailable in review: " + fullname,
                    name=fullname)

    sys.meta_path.insert(0, NoQt())
    import pytest
    files = [str(p) for p in sorted((ROOT / "tests").glob("test_*.py"))
             if "PySide6" not in p.read_text()]
    print(f"Selected {len(files)} files using CI literal selection")
    return pytest.main(["-o", "addopts=", "--collect-only", "-q", *files])


def probe(directory):
    from folego.orchestration.bridge import perform
    from folego.orchestration.coordinator import Coordinator
    from folego.orchestration.grants import GrantStore
    from folego.orchestration.journal import Journal
    from folego.orchestration.models import ActionPlan, ActionResult, Grant, Outcome, ResourceIdentity

    observations = {}
    target = ResourceIdentity.path(directory / "fake-target")

    def plan(**kwargs):
        return ActionPlan(action="tmpfs.release", target=target, **kwargs)

    def success(p):
        return ActionResult(action=p.action, outcome=Outcome.OK,
                            target_key=p.target.key)

    # Uma falha só na gravação FINAL não pode ser chamada "nada foi feito".
    class FinalWriteFails(Journal):
        def append_result(self, result):
            raise OSError("injected final journal write failure")

    effects = []
    coordinated = perform(
        coordinator=Coordinator(journal=FinalWriteFails(directory / "final.jsonl"),
                                lock_path=directory / "final.lock"),
        action="tmpfs.release", target=target, params={},
        act=lambda: effects.append("fake effect happened") or "domain result",
        verdict=lambda result, key: ActionResult(
            action="tmpfs.release", outcome=Outcome.OK, target_key=key))
    observations["falha_de_registro_apos_efeito"] = {
        "effects": effects, "domain_result": coordinated.result,
        "outcome": coordinated.verdict.outcome,
        "reason": coordinated.verdict.reason}

    # O relógio avança durante a espera pela trava; nenhum sleep é necessário.
    clock = [100.0]
    effects = []

    class DelayedLock(Coordinator):
        @contextlib.contextmanager
        def lock(self, **kwargs):
            clock[0] = 105.0
            yield

    delayed = DelayedLock(journal=Journal(directory / "expired.jsonl"),
                          now=lambda: clock[0])
    expiring = plan(created_at=99.0, expires_at=102.0)
    grant = Grant("expires", "tmpfs.release", issued_at=99.0, expires_at=102.0)

    def effect(p):
        effects.append("fake effect happened")
        return success(p)

    result = delayed.run(expiring, effect, grant=grant)
    observations["plano_e_grant_expiram_na_fila"] = {
        "now": clock[0], "expires_at": expiring.expires_at,
        "outcome": result.outcome, "effects": effects}

    # Revogação persistida enquanto a chamada aguardava a trava.
    grants = GrantStore(directory / "grants.json", clock=lambda: 100.0)
    persisted = grants.add("tmpfs.release", {}, ttl_s=50)
    effects = []

    class RevokeWhileWaiting(Coordinator):
        @contextlib.contextmanager
        def lock(self, **kwargs):
            grants.revoke(persisted.grant_id)
            yield

    revoked = RevokeWhileWaiting(journal=Journal(directory / "revoked.jsonl"),
                                now=lambda: 101.0)
    result = revoked.run(plan(), effect, grant=persisted)
    observations["grant_revogado_na_fila"] = {
        "persisted_revoked_at": grants.find(persisted.grant_id).revoked_at,
        "outcome": result.outcome, "effects": effects}

    # A mesma chave com outro conteúdo precisa causar conflito, nunca sucesso antigo.
    coordinator = Coordinator(journal=Journal(directory / "repeat.jsonl"),
                              lock_path=directory / "repeat.lock")
    first = plan(operation_id="same-operation")
    coordinator.run(first, success)
    other = ActionPlan(action="disk.purge", target=ResourceIdentity.entry("other"),
                       operation_id=first.operation_id)
    result = coordinator.run(other, success)
    observations["operation_id_com_outro_plano"] = {
        "requested_action": other.action, "requested_target": other.target.key,
        "returned_action": result.action, "returned_target": result.target_key,
        "outcome": result.outcome}

    grant = Grant("limited", "tmpfs.release", {"max_bytes": 1024})
    proposed = plan(params={"max_bytes": 100, "unapproved_option": True})
    observations["grant_aceita_parametro_nao_autorizado"] = {
        "limits": dict(grant.limits), "params": dict(proposed.params),
        "coverage": grant.covers(proposed)}
    observations["grant_vazio_persistido"] = {
        "limits": dict(persisted.limits), "coverage": persisted.covers(proposed)}

    # Snapshot de plano não é imutável em profundidade; digest muda depois do aceite.
    mutable = plan(params={"max_bytes": 1})
    before = mutable.digest
    mutable.params["max_bytes"] = 9000
    observations["plano_mutavel"] = {
        "digest_changed": before != mutable.digest,
        "max_bytes_after": mutable.params["max_bytes"]}

    # Interleaving determinístico de duas instâncias entre read e write.
    from folego.orchestration.config import ConfigStore
    config_a = ConfigStore(directory / "automation.json")
    config_b = ConfigStore(directory / "automation.json")
    write_a = config_a._write

    def concurrent_pause_then_write(config):
        config_b.set_paused(True)
        return write_a(config)

    with patch.object(config_a, "_write", side_effect=concurrent_pause_then_write):
        config_a.set_preset("conservador")
    observations["troca_de_preset_perde_pausa_concorrente"] = {
        "requested_paused": True, "persisted_paused": config_a.read().paused,
        "persisted_preset": config_a.read().preset}

    # Nenhum daemon é chamado: adapter e stdout são substituídos localmente.
    from folego import cli
    from folego.adapters.base import AdapterResult

    class FakeAdapter:
        name = "review-fake"
        calls = 0

        def inventory(self):
            self.calls += 1
            return AdapterResult(self.name, True)

    adapter = FakeAdapter()
    with patch.object(cli, "default_adapters", return_value=(adapter,)):
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli._cmd_ecosystem(SimpleNamespace(adapter=None, json=True))
    observations["ecosystem_json_coleta_duplicada"] = {
        "calls": adapter.calls, "exit": code}
    return observations


if __name__ == "__main__":
    if "--ci-sem-qt" in sys.argv:
        raise SystemExit(ci_sem_qt())
    (ROOT / ".scratch").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-probes-", dir=ROOT / ".scratch") as tmp:
        print(json.dumps(probe(Path(tmp)), ensure_ascii=False, indent=2))
