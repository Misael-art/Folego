"""Durable manual reviews around the existing domain bridges, never a second executor."""
import contextlib
from contextvars import ContextVar
from dataclasses import replace, asdict
import hashlib
import io
import json
from pathlib import Path
import re
import os
import time

from .. import paths
from .models import ActionPlan, ActionResult, Outcome

ACTIVE = ContextVar("folego_manual_review", default=None)
ALLOWED = {("tune", "apply"), ("tune", "revert"), ("disk", "restore"), ("disk", "purge"),
           ("tmpfs", "release"), ("tmpfs", "restore"), ("tmpfs", "expire"), ("tmpfs", "recover")}


def root():
    return paths.state_dir() / "reviews"


def _path(key):
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("ID de revisão inválido")
    return root() / (key + ".json")


def _save(bundle):
    from ..actions.accessibility import save_object
    raw = json.dumps(bundle).encode()
    if len(raw) > 65536:
        raise ValueError("revisão excede orçamento")
    save_object(_path(bundle["plan"]["operation_id"]), bundle)


def _read(key):
    from ..actions.accessibility import read_object
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        return None
    path = _path(key)
    return read_object(path) or read_object(paths.state_dir() / "reviews-closed" / path.name)


def _close(bundle, result):
    from ..actions.accessibility import private_path
    bundle.update(state="closed", result=result.to_dict())
    _save(bundle)
    source = _path(result.operation_id)
    target = paths.state_dir() / "reviews-closed" / source.name
    private_path(target, create=True)
    if target.exists(): raise ValueError("recibo encerrado já existe; preservar ambos")
    os.rename(source, target)
    for folder in (source.parent, target.parent):
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def cancel(key, *, confirmed=False):
    from .coordinator import Coordinator
    if not confirmed: raise ValueError("cancelamento exige confirmação")
    with Coordinator().lock(wait=.2):
        bundle = _read(key)
        if not bundle or bundle.get("state") != "reviewed":
            raise ValueError("revisão já iniciada/encerrada; consultar sem cancelar o efeito")
        plan = ActionPlan.from_dict(bundle["plan"])
        result = ActionResult(plan.action, Outcome.CANCELLED, key, target_key=plan.target.key,
                              reason="revisão cancelada antes de executar; nenhum efeito")
        _close(bundle, result)
        return result


def _hash(path):
    from ..adapters.accessibility import bounded_read
    path = Path(path)
    if not path.exists():
        return {"absent": True}
    if path.is_symlink() or not path.is_file():
        raise ValueError("arquivo de revisão simbólico/especial")
    return {"sha256": hashlib.sha256(bounded_read(path, 8 * 1024**2).encode()).hexdigest()}


def evidence(command, plan):
    from .. import cli
    from ..actions.disk.review import identity
    from ..actions.tunings.engine import TuningEngine
    from ..actions.tunings.registry import tuning_by_id
    group, verb = command[:2]
    proof = {}
    summary = []
    if group == "tune":
        tuning = tuning_by_id(command[2])
        engine = TuningEngine()
        data = {"file": _hash(tuning.target())}
        summary = [{"key": str(tuning.target()), "source": str(tuning.target())}]
        if verb == "apply":
            proof = {"file": str(tuning.target()), "sha": plan.params["after_sha"]}
        else:
            backup = engine.backup.latest_backup_id(tuning.action_id)
            if not backup:
                raise ValueError("sem backup para revisar")
            manifest = engine.backup.read_manifest(backup)
            data.update(backup=backup, manifest=manifest)
            proof = {"file": str(tuning.target()), "sha": manifest["entries"][0]["sha_before"]}
    elif group == "disk":
        book = cli._quarantine()
        entry = book.entries().get(command[2])
        if entry is None:
            raise ValueError("entrada não encontrada")
        data = {"entry": asdict(entry), "stored": identity(entry.stored).to_dict()}
        summary = [{"key": entry.entry_id, "source": entry.original, "bytes": entry.bytes}]
        proof = {"entries": [entry.entry_id], "state": "restored" if verb == "restore" else "purged"}
    else:
        ledger = cli._tmpfs_ledger()
        if ledger.problems():
            raise ValueError("ledger inconsistente; revisão bloqueada")
        if verb == "release":
            data = {"source": identity(command[2]).to_dict()}
            summary = [{"key": command[2], "source": command[2], "bytes": plan.params["bytes"]}]
            proof = {"source": command[2], "state": "released"}
        else:
            if verb == "restore":
                found = ledger.find(command[2])
                records = [found] if found else []
            elif verb == "expire":
                args = cli.build_parser().parse_args(command)
                records = ledger.over_budget(days=args.dias, max_bytes=args.max_bytes, now=cli._tmpfs_now())
            else:
                records = [row for row in ledger.records().values() if row.state == "staging"]
            if not records or len(records) > 64:
                raise ValueError("nenhum alvo ou revisão excede orçamento de 64 entradas")
            data = {"entries": [row.to_dict() for row in records], "trees": []}
            summary = [{"key": row.entry_id, "source": row.src, "bytes": row.bytes} for row in records]
            for row in records:
                path = Path(row.stored)
                if path.exists():
                    data["trees"].append(identity(path).to_dict())
                elif verb != "recover":
                    raise ValueError("cópia retida ausente; evidência insuficiente")
                if verb == "recover":
                    source = Path(row.src)
                    data.setdefault("sources", []).append(identity(source).to_dict() if source.exists() else {"absent": str(source)})
            proof = {"entries": [row.entry_id for row in records],
                     "state": {"restore": "restored", "expire": "expired", "recover": "dropped"}[verb]}
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return {"digest": digest, "proof": proof, "summary": summary}


class Review:
    def __init__(self, command, bundle=None):
        self.command, self.bundle = command, bundle
        self.plan = ActionPlan.from_dict(bundle["plan"]) if bundle else None
        self.capture = bundle is None

    def validate(self):
        for key, target in _pending_map().items():
            if key != self.plan.operation_id and target == (self.plan.action, self.plan.target.key):
                raise ValueError("operação anterior incerta no mesmo alvo; reconciliar antes de repetir")
        if evidence(self.command, self.plan) != self.bundle["evidence"]:
            raise ValueError("alvos, vítimas, backup ou conteúdo mudaram após a revisão")


def _invoke(command):
    from .. import cli
    if command[0] == "tune":
        from ..actions.tunings.worker import run
        return run(command[1], command[2], confirm=True)
    argv = [*command, "--confirmar"]
    if command[1] in ("purge", "expire"):
        argv.append("--irreversivel")
    return cli._dispatch(cli.build_parser().parse_args(argv), argv)


def prepare(command):
    if (not isinstance(command, list) or not 2 <= len(command) <= 32
            or not all(isinstance(part, str) and len(part) <= 4096 for part in command)
            or tuple(command[:2]) not in ALLOWED
            or any(part in ("--confirmar", "--irreversivel", "--reviewed-plan") for part in command)):
        raise ValueError("comando de revisão inválido")
    review = Review(command)
    token = ACTIVE.set(review)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            _invoke(command)
    finally:
        ACTIVE.reset(token)
    if review.plan is None:
        raise ValueError("operação não produziu plano revisável; consulte o diagnóstico do domínio")
    if (review.plan.action, review.plan.target.key) in _pending_map().values():
        raise ValueError("operação anterior pendente no mesmo alvo; verificar seu ID antes de nova revisão")
    bundle = {"schema": 1, "plan": review.plan.to_dict(), "command": command,
              "evidence": evidence(command, review.plan), "state": "reviewed"}
    # No unbounded orphan reviews: never discard unknown work to free capacity.
    folder = root()
    if folder.exists() and sum(1 for _ in folder.iterdir()) >= 256:
        raise ValueError("revisões retidas exigem revisão de capacidade")
    from .coordinator import Coordinator
    with Coordinator().lock(wait=.2):
        if any(row["action"] == review.plan.action and row["target"] == review.plan.target.key for row in pending()):
            raise ValueError("já existe revisão/operação pendente no mesmo alvo; consultar ou cancelar a revisão anterior")
        _save(bundle)
    return bundle


def execute(bundle, *, confirmed=False, irreversible=False):
    from ..actions.accessibility import read_object
    from ..core.sessions import read_boot_id
    from .coordinator import Coordinator
    plan = ActionPlan.from_dict(bundle.get("plan") or {})
    stored = _read(plan.operation_id)
    if not confirmed or stored is None or any(stored.get(key) != bundle.get(key)
            for key in ("schema", "plan", "command", "evidence")):
        raise ValueError("revisão não corresponde ao registro durável/confirmacão")
    if bundle["command"][1] in ("purge", "expire") and not irreversible:
        raise ValueError("operação irreversível exige confirmação separada")
    state = Coordinator().journal.state_of(plan.operation_id)
    if stored.get("result"):
        return ActionResult.from_dict(stored["result"])
    if state is not None:
        if state.intent != plan:
            raise ValueError("ID registrado com outro plano")
        return state.result or ActionResult(plan.action, Outcome.UNKNOWN, plan.operation_id,
                target_key=plan.target.key, reason="intenção sem resultado; não repetir")
    with Coordinator().lock(wait=.2):
        stored = _read(plan.operation_id)
        if stored.get("state") != "reviewed":
            return ActionResult(plan.action, Outcome.UNKNOWN, plan.operation_id, target_key=plan.target.key,
                                reason="tentativa anterior registrada; reconciliar antes de repetir")
        fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
        stored.update(state="started", owner={"pid": os.getpid(), "start_ticks": int(fields[19]), "boot_id": read_boot_id()})
        _save(stored)  # Queryable even if the child dies before journal entry.
    review = Review(bundle["command"], stored)
    token = ACTIVE.set(review)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            _invoke(bundle["command"])
    finally:
        ACTIVE.reset(token)
    state = Coordinator().journal.state_of(plan.operation_id)
    if state and state.result:
        if state.result.outcome != Outcome.UNKNOWN:
            _close(stored, state.result)
        return state.result
    if getattr(review, "result", None) is not None and review.result.outcome == Outcome.REFUSED:
        _close(stored, review.result)
        return review.result
    return ActionResult(plan.action, Outcome.UNKNOWN, plan.operation_id, target_key=plan.target.key,
                        reason="resultado não registrado; consultar o mesmo ID")


def pending():
    from ..actions.accessibility import read_object
    rows = [{"operation_id": key, "action": action, "target": target}
            for key, (action, target) in _pending_map().items()]
    folder = root()
    if not folder.exists(): return rows
    for index, path in enumerate(folder.iterdir()):
        if index >= 256: raise ValueError("revisões excedem orçamento")
        value = read_object(path)
        if value and value.get("state") in ("reviewed", "started"):
            from .journal import Journal
            plan = ActionPlan.from_dict(value["plan"])
            state = Journal().state_of(plan.operation_id)
            if state is None or state.result is None or state.result.outcome == Outcome.UNKNOWN:
                if not any(row["operation_id"] == plan.operation_id for row in rows):
                    rows.append({"operation_id": plan.operation_id, "action": plan.action, "target": plan.target.key,
                                 "state": value["state"]})
    return rows


def _pending_map():
    from .journal import Journal
    from .history import PendingReader
    reader = PendingReader(Journal())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        text = reader.refresh()
        if reader.verified:
            if reader.problem_count: raise ValueError(text)
            return reader.pending
        if "em andamento" not in text:
            raise ValueError(text)
    raise ValueError("diário excede prazo da revisão; nenhuma ação autorizada")


def reconcile(key):
    from ..actions.accessibility import read_object, _alive
    from .coordinator import Coordinator
    from .. import cli
    from ..actions.tmpfs.release import tree_digest
    c = Coordinator()
    if _read(key) is None:
        state = c.journal.state_of(key)
        if state and state.result and state.result.outcome != Outcome.UNKNOWN:
            return state.result
        if state and state.intent:
            if state.intent.action == "accessibility.enable-input":
                from ..actions.accessibility import Supervisor
                return Supervisor(coordinator=c).reconcile(key)
            if state.intent.action == "tmpfs.runtime-size":
                from ..actions.tmpfs.runtime_size import reconcile as runtime_reconcile
                return runtime_reconcile(key, coordinator=c, volume_fn=cli._tmpfs_runtime_volume)
            return ActionResult(state.intent.action, Outcome.UNKNOWN, key, target_key=state.intent.target.key,
                reason="operação legada sem revisão de conteúdo; verificar pelo controlador do domínio; não repetir")
        raise ValueError("operação não encontrada")
    with c.lock(wait=.2):
        bundle = _read(key)
        if not bundle: raise ValueError("revisão não encontrada")
        plan = ActionPlan.from_dict(bundle["plan"])
        state = c.journal.state_of(key)
        if state is None and bundle.get("state") == "started" and _alive(bundle.get("owner")) is False:
            result = ActionResult(plan.action, Outcome.REFUSED, key, target_key=plan.target.key,
                                  reason="executor encerrado sem intenção no diário; nenhum efeito autorizado; criar nova revisão")
            _close(bundle, result)
            return result
        if state and state.result and state.result.outcome != Outcome.UNKNOWN:
            return state.result
        proof = bundle["evidence"]["proof"]
        ok = False
        if state and state.intent:
            group, verb = bundle["command"][:2]
            if "file" in proof:
                ok = _hash(proof["file"]).get("sha256") == proof["sha"]
            elif group == "disk":
                entries = cli._quarantine().entries()
                ok = all(key in entries and entries[key].state == proof["state"] for key in proof["entries"])
                if ok:
                    ok = all(not Path(entries[key].stored).exists() for key in proof["entries"])
            else:
                ledger = cli._tmpfs_ledger()
                if ledger.problems(): raise ValueError("ledger inconsistente")
                records = ([ledger.find(proof["source"])] if "source" in proof else
                           [ledger.records().get(key) for key in proof["entries"]])
                ok = bool(records) and all(row and row.state == proof["state"] for row in records)
                if ok and verb in ("release", "restore"):
                    ok = all(tree_digest(Path(row.stored if verb == "release" else row.src))[0] == row.sha256 for row in records)
        result = ActionResult(plan.action, Outcome.OK if ok else Outcome.UNKNOWN, key, target_key=plan.target.key,
            reason="estado atual do domínio verificado; nada reaplicado" if ok else "evidência insuficiente; não repetir")
        if ok:
            c.journal.append_result(result)
            _close(bundle, result)
        return result
