"""Ponte F2: os atos da quarentena de disco rodam sob o coordenador único.

O domínio (``move_in``, ``restore``, ``purge``, ``reconcile``) não conhece o
motor comum: esta ponte monta o ``ActionPlan``, roda o ato com a intenção já no
diário e traduz o resultado para o ``ActionResult`` estruturado. O verbo
``reconcile`` repara as transições de uma queda e só entra no diário quando há
reparo pendente — listar continua sendo ler. O domínio não tem dry-run nem
opinião sobre flags: a recusa de ``--confirmar``/``--irreversivel`` mora aqui,
antes de qualquer registro, para que todo chamador (CLI hoje, GUI depois) passe
pela mesma porta — sem confirmação, nada entra no diário. Devolve as duas faces
(``Coordinated``) porque a CLI imprime o texto do domínio e o diário guarda o
veredito.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...orchestration import (ActionResult, Coordinator, Coordinated, Outcome,
                              ResourceIdentity, perform)
from .quarantine import Quarantine, QuarantineEntry, ReconcileReport

KIND_QUARANTINE = "disk.quarantine"
KIND_RESTORE = "disk.restore"
KIND_PURGE = "disk.purge"
KIND_RECONCILE = "disk.reconcile"

_MISSING_CONFIRM = "refused: mutação exige --confirmar (nada foi alterado)"
_MISSING_IRREVERSIBLE = ("refused: purga é irreversível, exige --irreversivel "
                         "(nada foi alterado)")


@dataclass(frozen=True)
class MutationResult:
    """Resultado de um ato da quarentena (o domínio não tem um tipo único).

    ``entry`` é a entrada tocada, relida depois do ato quando possível: os
    ``effects`` do veredito falam do estado observado, não do que se supôs.
    """

    ok: bool
    reason: str
    entry: QuarantineEntry | None = None


def _entry_effects(entry: QuarantineEntry | None) -> dict:
    if entry is None:
        return {}
    return {"entry_id": entry.entry_id, "bytes": entry.bytes,
            "original": entry.original, "stored": entry.stored,
            "state": entry.state}


# ------------------------------------------------------------------ vereditos


def _verdict_quarantine(result: MutationResult, target_key: str) -> ActionResult:
    return ActionResult(action=KIND_QUARANTINE,
                        outcome=Outcome.OK if result.ok else Outcome.REFUSED,
                        target_key=target_key, reason=result.reason,
                        effects=_entry_effects(result.entry))


def _verdict_restore(result: MutationResult, target_key: str) -> ActionResult:
    return ActionResult(action=KIND_RESTORE,
                        outcome=Outcome.OK if result.ok else Outcome.REFUSED,
                        target_key=target_key, reason=result.reason,
                        effects=_entry_effects(result.entry))


def _verdict_purge(result: MutationResult, target_key: str) -> ActionResult:
    return ActionResult(action=KIND_PURGE,
                        outcome=Outcome.OK if result.ok else Outcome.REFUSED,
                        target_key=target_key, reason=result.reason,
                        effects=_entry_effects(result.entry))


def _verdict_reconcile(report: ReconcileReport, target_key: str) -> ActionResult:
    if report.problems:
        # manifesto ilegível/inconsistente: o ato não escreveu nada, e chamar isso
        # de sucesso seria fechar os olhos para estado desconhecido
        outcome = Outcome.REFUSED
        reason = ("manifesto da quarentena inconsistente; nenhum reparo foi aplicado: "
                  + "; ".join(report.problems))
    elif report.manual:
        # reparou o que dava, mas o que é ambíguo ficou para decisão humana
        outcome = Outcome.PARTIAL
        reason = (f"reparadas {len(report.repaired)}, encerradas {len(report.dropped)}; "
                  f"{len(report.manual)} entrada(s) ficaram para decisão manual")
    else:
        outcome = Outcome.OK
        reason = f"reparadas {len(report.repaired)}, encerradas {len(report.dropped)}"
    return ActionResult(action=KIND_RECONCILE, outcome=outcome, target_key=target_key,
                        reason=reason,
                        effects={"repaired": list(report.repaired),
                                 "dropped": list(report.dropped),
                                 "manual": list(report.manual)},
                        errors=tuple(report.problems))


# ---------------------------------------------------------------------- verbos


def quarantine(*, coordinator: Coordinator, confirm: bool, book: Quarantine,
               path, reviewed_plan=None) -> Coordinated[MutationResult]:
    if not confirm:
        # resposta direta, sem diário: recusa de flag não é uma operação
        return Coordinated(MutationResult(False, _MISSING_CONFIRM), None)

    review_failure = ""
    if reviewed_plan is None:
        from .review import plan_quarantine
        try:
            reviewed_plan = plan_quarantine(path, book)
        except (OSError, ValueError) as exc:
            review_failure = f"refused: revisão incompleta/protegida: {exc}"

    # expandir `~` é o que o domínio faz antes de agir; a identidade do alvo
    # precisa falar do mesmo caminho que o ato vai tocar
    key = str(Path(os.path.expanduser(str(path))))
    if reviewed_plan is not None:
        key = str(Path(os.path.abspath(key)))

    def act():
        try:
            if review_failure:
                return MutationResult(False, review_failure)
            if reviewed_plan is not None:
                from .review import identity
                if identity(key) != reviewed_plan.target:
                    return MutationResult(False, "refused: alvo/árvore/montagem mudou após a revisão")
            kwargs = {"expected_identity": reviewed_plan.target} if reviewed_plan is not None else {}
            entry = book.move_in(path, action_id=KIND_QUARANTINE, **kwargs)
        except PermissionError as exc:
            # recusa do domínio (guard, alvo sumido, outro dispositivo): vira
            # resultado registrado, nunca silêncio
            return MutationResult(False, str(exc))
        return MutationResult(True, "ok", entry)

    return perform(coordinator=coordinator, action=KIND_QUARANTINE,
                   target=reviewed_plan.target if reviewed_plan is not None and reviewed_plan.target.key == key
                          else ResourceIdentity.path(key), params={}, reviewed_plan=reviewed_plan,
                   act=act, verdict=_verdict_quarantine)


def restore(*, coordinator: Coordinator, confirm: bool, book: Quarantine,
            entry_id) -> Coordinated[MutationResult]:
    if not confirm:
        return Coordinated(MutationResult(False, _MISSING_CONFIRM), None)

    def act():
        result = book.restore(str(entry_id))
        entry = book.entries().get(str(entry_id))
        return MutationResult(result.ok, result.reason, entry)

    return perform(coordinator=coordinator, action=KIND_RESTORE,
                   target=ResourceIdentity.entry(str(entry_id)), params={},
                   act=act, verdict=_verdict_restore)


def purge(*, coordinator: Coordinator, confirm: bool, irreversible: bool,
          book: Quarantine, entry_id) -> Coordinated[MutationResult]:
    if not confirm:
        return Coordinated(MutationResult(False, _MISSING_CONFIRM), None)
    if not irreversible:
        return Coordinated(MutationResult(False, _MISSING_IRREVERSIBLE), None)

    def act():
        try:
            result = book.purge(str(entry_id))
        except PermissionError as exc:
            # o `_check` do domínio recusa payload fora das raízes permitidas:
            # recusa registrada, nunca uma exceção crua na cara do chamador
            return MutationResult(False, str(exc))
        entry = book.entries().get(str(entry_id))
        return MutationResult(result.ok, result.reason, entry)

    return perform(coordinator=coordinator, action=KIND_PURGE,
                   target=ResourceIdentity.entry(str(entry_id)), params={},
                   act=act, verdict=_verdict_purge)


def reconcile(*, coordinator: Coordinator, book: Quarantine) -> Coordinated:
    """Repara as transições deixadas por uma queda, sob a porta única.

    A varredura é só leitura e decide se há o que reparar; havendo, o reparo roda
    sob o coordenador com a intenção no diário. Sem reparo pendente (ou com o
    manifesto inconsistente), nada é registrado: listar continua sendo ler.
    """
    scan = book.reconcile(dry_run=True)
    if scan.problems or not scan.mutated:
        return Coordinated(scan, None)
    return perform(coordinator=coordinator, action=KIND_RECONCILE,
                   target=ResourceIdentity("group", "disk.quarentena"), params={},
                   act=lambda: book.reconcile(), verdict=_verdict_reconcile)
