"""M2 engine: detect what a tuning is now, plan the change, and only then write it.

detect() and plan() never touch the disk beyond reading it: a plan is a promise
about bytes, the digest before and the digest after. apply() keeps that promise
honest — it re-reads the file, refuses if anything changed since the plan, takes
the backup first, and restores that backup if the written bytes are not the ones
it predicted. revert() and verify() answer the two questions a browser that
rewrites its own config makes you ask: can I undo it, and did it stick?
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ... import paths
from ...core import browser
from ...safely.atomicfile import write_atomic
from ...safely.audit import AuditLog
from ...safely.backup import BackupEntry, BackupStore
from ...safely.guard import validate_target
from ...safely.hashing import read_hashed, sha256_bytes
from ...safely.jsonedit import set_value
from .model import Tuning


@dataclass(frozen=True)
class Detect:
    tuning: Tuning
    target: Path
    exists: bool
    parses: bool
    present: bool
    current: object = None
    error: str | None = None

    @property
    def change_needed(self) -> bool:
        if not self.exists or not self.parses:
            return False
        if self.present:
            return self.current != self.tuning.desired
        return True


@dataclass(frozen=True)
class Plan:
    tuning: Tuning
    target: Path
    before_sha: str | None = None
    after_sha: str | None = None
    blocked: str | None = None

    @property
    def label(self) -> str:
        return self.tuning.label

    @property
    def why(self) -> str:
        return self.tuning.why


NEEDS_CONFIRM = "recusado: aplicar um tuning exige confirmação explícita"
REVERT_NEEDS_CONFIRM = "recusado: reverter um tuning exige confirmação explícita"


@dataclass(frozen=True)
class ApplyResult:
    tuning: Tuning
    target: Path
    ok: bool
    reason: str | None = None
    backup_id: str | None = None
    sha: str | None = None


@dataclass(frozen=True)
class RevertResult:
    tuning: Tuning
    target: Path
    ok: bool
    reason: str | None = None
    backup_id: str | None = None
    sha: str | None = None
    effect_started: bool = False


@dataclass(frozen=True)
class Verification:
    tuning: Tuning
    target: Path
    ok: bool
    message: str


class TuningEngine:
    def __init__(self, backup=None, audit=None, *, config_root: Path | None = None,
                 edge_running: Callable[[], str | None] = browser.edge_running,
                 write_fn=write_atomic):
        self.backup = backup or BackupStore(paths.backup_dir())
        self.audit = audit or AuditLog()
        self.config_root = Path(config_root) if config_root else paths.edge_config_dir()
        self.edge_running = edge_running
        self.write_fn = write_fn

    def detect(self, tuning: Tuning) -> Detect:
        target = tuning.target()
        if not target.is_file():
            return Detect(tuning, target, exists=False, parses=False, present=False,
                          error=f"{target.name} não existe em {target.parent}")
        try:
            data = target.read_bytes()
        except OSError as exc:
            return Detect(tuning, target, exists=True, parses=False, present=False,
                          error=f"não foi possível ler: {exc.strerror or exc}")
        try:
            doc = json.loads(data)
        except ValueError as exc:
            return Detect(tuning, target, exists=True, parses=False, present=False,
                          error=f"{target.name} não é JSON válido: {exc}")
        found, present = _at_path(doc, tuning.key_path)
        return Detect(tuning, target, exists=True, parses=True,
                      present=present, current=found)

    def plan(self, det: Detect) -> Plan | None:
        """None means there is genuinely nothing to change; a Plan with .blocked
        says why this tuning could not be planned. A corrupt or missing file is
        never reported as "all good" — the reason has to reach the user."""
        tuning = det.tuning
        if det.error:
            return Plan(tuning, det.target, blocked=det.error)
        if not det.change_needed:
            return None
        if not (verdict := validate_target(det.target, [self.config_root])).ok:
            return Plan(tuning, det.target, blocked=verdict.reason)
        try:
            data = det.target.read_bytes()
            after = set_value(data, tuning.key_path, tuning.desired)
            json.loads(after)
        except (OSError, ValueError) as exc:
            # ValueError covers MalformedDocument and KeyConflict: both are the
            # splicer refusing to guess what a broken document meant.
            return Plan(tuning, det.target, blocked=f"recusado: {exc}")
        return Plan(tuning, det.target, before_sha=sha256_bytes(data),
                    after_sha=sha256_bytes(after))

    def apply(self, plan: Plan, *, confirm: bool = False) -> ApplyResult:
        """Write a planned tuning. Four things must hold before a byte changes:
        the user confirmed, the browser that owns the file is closed, the file is
        still the one the plan was made from, and the backup landed."""
        tuning, target = plan.tuning, plan.target
        if plan.blocked:
            return self._refuse(plan, plan.blocked)
        if not confirm:
            return self._refuse(plan, NEEDS_CONFIRM)
        if not (verdict := validate_target(target, [self.config_root])).ok:
            return self._refuse(plan, verdict.reason)
        if tuning.requires_target_closed and (who := self.edge_running()):
            return self._refuse(plan, f"recusado: o Microsoft Edge está aberto ({who}). "
                                      f"Feche o Edge: ao sair ele regrava este arquivo "
                                      f"e desfaz o ajuste.")
        try:
            data = target.read_bytes()
        except OSError as exc:
            return self._refuse(plan, f"recusado: não foi possível ler {target.name}: {exc}")
        if sha256_bytes(data) != plan.before_sha:
            return self._refuse(plan, "recusado: o arquivo mudou depois do plano; "
                                      "nada foi escrito — faça um novo plano")
        after = set_value(data, tuning.key_path, tuning.desired)

        started = time.monotonic()
        try:
            backup_id = self.backup.create(tuning.action_id,
                                           [BackupEntry(target, plan.after_sha)])
        except OSError as exc:
            return self._refuse(plan, f"recusado: o backup falhou ({exc}); nada foi escrito")

        self.write_fn(target, after)
        _, written = read_hashed(target)
        if written != plan.after_sha:
            self.backup.restore(backup_id)
            self._audit("tuning.apply", plan, "verify_failed_reverted", backup_id, started,
                        error="sha256 pós-escrita diferente do planejado; backup restaurado")
            return ApplyResult(tuning, target, False,
                               "a verificação pós-escrita falhou; o arquivo foi "
                               "restaurado a partir do backup", backup_id)
        self._audit("tuning.apply", plan, "applied", backup_id, started)
        return ApplyResult(tuning, target, True, None, backup_id, written)

    def revert(self, tuning: Tuning, *, confirm: bool = False) -> RevertResult:
        """Restore the latest backup. The same three gates as apply — explicit
        confirmation, path guard, browser closed — because the direct entry
        (``python -m ...worker revert``) must not be more permissive than the CLI,
        and an open Edge would rewrite the file over the restore."""
        target = tuning.target()
        if not confirm:
            return RevertResult(tuning, target, False, REVERT_NEEDS_CONFIRM)
        if not (verdict := validate_target(target, [self.config_root])).ok:
            return RevertResult(tuning, target, False, verdict.reason)
        if tuning.requires_target_closed and (who := self.edge_running()):
            return RevertResult(tuning, target, False,
                                f"recusado: o Microsoft Edge está aberto ({who}). "
                                f"Feche o Edge: ao sair ele regrava este arquivo e "
                                f"desfaz a reversão.")
        backup_id = self.backup.latest_backup_id(tuning.action_id)
        if backup_id is None:
            return RevertResult(tuning, target, False,
                                "sem backup deste tuning; nada foi restaurado")
        entry = self.backup.read_manifest(backup_id)["entries"][0]
        if target.is_file():
            _, current = read_hashed(target)
            if entry["sha_after_expected"] and current != entry["sha_after_expected"]:
                return RevertResult(tuning, target, False,
                                    "o arquivo mudou desde a aplicação; nada foi "
                                    "restaurado — suas mudanças seriam perdidas",
                                    backup_id)
        results = self.backup.restore(backup_id)
        bad = [r for r in results if not r.ok]
        if bad:
            return RevertResult(tuning, target, False,
                                f"falha ao restaurar: {bad[0].error}", backup_id,
                                effect_started=True)
        self._audit("tuning.revert", Plan(tuning, target, after_sha=entry["sha_before"]),
                    "reverted", backup_id, time.monotonic(),
                    targets=[f"{target.name} ← {backup_id}"])
        return RevertResult(tuning, target, True, None, backup_id, entry["sha_before"])

    def verify(self, plan: Plan) -> Verification:
        """Did the browser keep what we wrote? Checked by digest, not by hope."""
        tuning, target = plan.tuning, plan.target
        try:
            _, current = read_hashed(target)
        except OSError as exc:
            return Verification(tuning, target, False,
                                f"não foi possível verificar: {exc.strerror or exc}")
        if current == plan.after_sha:
            return Verification(tuning, target, True, "persiste: o arquivo está "
                                                      "como foi aplicado")
        return Verification(tuning, target, False,
                            "sobrescrito — reaplicar: o Edge regrava este arquivo ao sair")

    # ----------------------------------------------------------------– internals

    def _refuse(self, plan: Plan, reason: str) -> ApplyResult:
        self._audit("tuning.apply", plan, "refused", None, time.monotonic(), error=reason)
        return ApplyResult(plan.tuning, plan.target, False, reason)

    def _audit(self, kind: str, plan: Plan, outcome: str, backup_id, started,
               error: str | None = None, targets: list[str] | None = None):
        if self.audit is None:
            return
        self.audit.append(kind=kind, action_id=plan.tuning.action_id, outcome=outcome,
                          targets=targets or [f"{plan.target}", f"chave {plan.tuning.key}"],
                          risk="reversible", backup_id=backup_id,
                          plan_digest=plan.after_sha, error=error,
                          duration_ms=int((time.monotonic() - started) * 1000))


def _at_path(doc: dict, key_path: tuple[str, ...]) -> tuple[object, bool]:
    node = doc
    for key in key_path:
        if not isinstance(node, dict) or key not in node:
            return (None, False)
        node = node[key]
    return (node, True)
