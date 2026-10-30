"""Ponte comum entre domínios e o coordenador único (F2).

O domínio (atos de tmpfs, quarentena de disco, ...) não conhece o motor comum:
esta ponte monta o ``ActionPlan``, roda o ato com a intenção já no diário (a
trava entre processos é do coordenador) e traduz o resultado do domínio para o
``ActionResult`` estruturado. Devolve as duas faces (``Coordinated``) porque o
chamador imprime o texto do domínio e o diário guarda o veredito.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Generic, TypeVar

from .coordinator import Coordinator
from .models import ActionPlan, ActionResult, Outcome, ResourceIdentity

T = TypeVar("T")


@dataclass(frozen=True)
class Coordinated(Generic[T]):
    """As duas faces do mesmo ato.

    ``result``: o resultado do domínio, presente sempre que o ato rodou ou o
    dry-run respondeu. ``verdict``: o veredito do motor comum, presente sempre
    que uma operação foi de fato coordenada (mesmo que o domínio a tenha
    recusado). Porta fechada → ``result is None`` e o ato não rodou.
    """

    result: T | None = None
    verdict: ActionResult | None = None


def perform(*, coordinator: Coordinator, action: str, target: ResourceIdentity,
            params: dict, act: Callable[[], object],
            verdict: Callable[[object, str], ActionResult],
            reviewed_plan: ActionPlan | None = None) -> Coordinated:
    """Roda ``act`` sob o coordenador e captura as duas faces do mesmo ato.

    A ordem é o contrato: ``Coordinator.run`` grava a intenção antes de chamar
    ``execute``, então quando o domínio toca no mundo já existe linha no diário.
    O veredito recebe ``(resultado_do_domínio, chave_do_alvo)``.
    """
    from .review import ACTIVE
    review = ACTIVE.get()
    if review is not None:
        if review.capture:
            review.plan = ActionPlan(action=action, target=target, params=params)
            return Coordinated(None, ActionResult(action, Outcome.REFUSED, review.plan.operation_id,
                                                  target_key=target.key, reason="somente revisão; nenhum efeito"))
        reviewed_plan = review.plan
    plan = reviewed_plan or ActionPlan(action=action, target=target, params=params)
    if plan.action != action or plan.target != target or dict(plan.params) != params:
        refused = ActionResult(
            action=action, outcome=Outcome.REFUSED, operation_id=plan.operation_id,
            target_key=target.key, reason="plano revisado difere da operação solicitada")
        if review is not None: review.result = refused
        return Coordinated(None, refused)
    box: dict[str, object] = {}

    def execute(plan: ActionPlan) -> ActionResult:
        if review is not None:
            try:
                review.validate()
            except (OSError, ValueError) as exc:
                return ActionResult(action, Outcome.REFUSED, plan.operation_id,
                                    target_key=target.key, reason=str(exc))
        box["started"] = True
        result = act()
        box["result"] = result
        observed = replace(verdict(result, plan.target.key), operation_id=plan.operation_id)
        box["verdict"] = observed
        return observed

    try:
        outcome = coordinator.run(plan, execute)
    except OSError as exc:
        if box.get("started"):
            observed = box.get("verdict") or ActionResult(
                action=action, outcome=Outcome.UNKNOWN, operation_id=plan.operation_id,
                target_key=target.key)
            return Coordinated(box.get("result"), replace(
                observed, outcome=Outcome.UNKNOWN, errors=(*observed.errors, str(exc)),
                reason=f"falha de coordenação após início ({exc}); consulte {plan.operation_id}; "
                       "não repetir sem reconciliação"))
        # O diário ou a trava não puderam ser tocados: a intenção NÃO foi
        # registrada e o executor não rodou — nada foi feito, e é isso que a
        # recusa diz (falhar fechado, nunca mutar sem registro).
        return Coordinated(None, ActionResult(
            action=action, outcome=Outcome.REFUSED, operation_id=plan.operation_id,
            target_key=target.key,
            reason=f"não foi possível registrar a intenção ({exc}); nada foi feito"))
    if review is not None: review.result = outcome
    return Coordinated(box.get("result"), outcome)
