"""Coordenador único das mutações (F2): uma trava, uma intenção, um resultado.

Duas CLIs e a GUI não podem mutar o mesmo estado ao mesmo tempo: toda mutação
passa por aqui, que serializa entre processos com ``flock`` por usuário/estado,
registra a intenção no diário *antes* de chamar o executor e grava o resultado
*depois*. Operação repetida é consultada, nunca reaplicada; intenção sem
resultado (queda no meio) vira resultado desconhecido até haver recuperação —
nada é reexecutado às cegas. Recusas de porta (plano expirado, grant inativo,
trava ocupada) não entram no diário: não houve operação, e tentar de novo tem de
ser possível.
"""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager, ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .. import paths
from .journal import CorruptJournal, Journal
from .models import (ActionPlan, ActionResult, Grant, Outcome, ValidationError)


class CoordinatorBusy(Exception):
    """Outro processo detém a trava e o tempo de espera acabou."""


class Coordinator:
    def __init__(self, *, journal: Journal | None = None, lock_path: Path | None = None,
                 now: Callable[[], float] | None = None, grant_store=None, config_store=None):
        self.journal = journal if journal is not None else Journal()
        self.lock_path = Path(lock_path) if lock_path else paths.coordinator_lock_path()
        self._now = now or time.time
        self.grant_store = grant_store
        self.config_store = config_store

    # -------------------------------------------------------------------- trava

    @contextmanager
    def lock(self, *, wait: float | None = None, poll: float = 0.02):
        """Trava exclusiva entre processos. ``wait=None`` espera sem prazo;
        ``wait`` finito desiste com ``CoordinatorBusy`` (fila limitada)."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if wait is None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                deadline = time.monotonic() + max(0.0, float(wait))
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise CoordinatorBusy(
                                f"outro processo muta o estado agora (trava "
                                f"{self.lock_path}); nada foi feito")
                        time.sleep(poll)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # ---------------------------------------------------------------------- ato

    def run(self, plan: ActionPlan, execute: Callable[[ActionPlan], ActionResult],
            *, grant: Grant | None = None, wait: float | None = 5.0) -> ActionResult:
        try:
            with self.lock(wait=5.0 if wait is None else wait), ExitStack() as authorization:
                state = self.journal.state_of(plan.operation_id)
                if state is not None and (state.intent is None or
                                          state.intent.to_dict() != plan.to_dict()):
                    return self._refuse(plan, "conflito de operation_id: plano diferente; "
                                             "nada foi reaplicado")
                if state is not None and state.result is not None:
                    return state.result
                if state is not None and state.intent is not None:
                    return ActionResult(
                        action=plan.action, outcome=Outcome.UNKNOWN,
                        operation_id=plan.operation_id, target_key=plan.target.key,
                        reason="intenção registrada sem resultado; recuperação pendente — "
                               "nada foi reaplicado")
                now = self._now()
                if plan.plan_version != 2:
                    return self._refuse(plan, "plano legado somente para consulta; revisar novo plano")
                if plan.expired(now):
                    return self._refuse(plan, f"plano expirado em {plan.expires_at:.0f}; "
                                              "emita um plano novo")
                if grant is not None:
                    if not grant.active(now):
                        return self._refuse(plan, f"grant {grant.grant_id} inativo ou revogado; "
                                                  "nada foi feito")
                    covered, why = grant.covers(plan)
                    if not covered:
                        return self._refuse(plan, f"grant {grant.grant_id} não cobre o plano: {why}")
                    from .config import ConfigStore, ConfigError
                    from .grants import GrantStore, GrantError
                    config_store = self.config_store or ConfigStore()
                    grant_store = self.grant_store or GrantStore()
                    # Global order: coordinator -> config -> grants. Writers of
                    # config/grants never acquire coordinator. Locks remain held
                    # through execution: a revocation completed before entry wins;
                    # one queued after entry never promises to undo that effect.
                    try:
                        authorization.enter_context(config_store._locked())
                        authorization.enter_context(grant_store._locked())
                        config = config_store.read()
                        current = grant_store.find(grant.grant_id)
                    except (ConfigError, GrantError, OSError) as exc:
                        return self._refuse(plan, f"autorização atual desconhecida: {exc}")
                    if config.paused or config.mode != "automatico":
                        return self._refuse(plan, "execução por grant pausada ou fora do modo automático")
                    now = self._now()
                    if plan.expired(now):
                        return self._refuse(plan, "plano expirado durante autorização")
                    if current is None or not current.active(now):
                        return self._refuse(plan, "grant atual ausente, expirado ou revogado")
                    covered, why = current.covers(plan)
                    if not covered:
                        return self._refuse(plan, f"grant atual não cobre o plano: {why}")

                self.journal.append_intent(plan)
                started = self._now()
                result = self._execute(plan, execute, started)
                try:
                    self.journal.append_result(result)
                except (OSError, CorruptJournal) as exc:
                    # The executor has returned: failure to persist cannot undo
                    # its effects. Keep the observed evidence and stable ID.
                    return replace(result, outcome=Outcome.UNKNOWN,
                                   reason=f"resultado observado, mas não persistido: {exc}; "
                                          "recuperação pendente; não repetir",
                                   errors=(*result.errors, str(exc)))
                return result
        except CoordinatorBusy as exc:
            return self._refuse(plan, str(exc))
        except CorruptJournal as exc:
            return self._refuse(plan, f"diário inconsistente: {exc}")

    def _execute(self, plan: ActionPlan, execute: Callable[[ActionPlan], ActionResult],
                 started: float) -> ActionResult:
        try:
            result = execute(plan)
            if not isinstance(result, ActionResult):
                raise ValidationError("executor devolveu algo que não é ActionResult")
        except Exception as exc:  # after entry, an exception cannot prove no effect
            return ActionResult(action=plan.action, outcome=Outcome.UNKNOWN,
                                operation_id=plan.operation_id,
                                target_key=plan.target.key, started_at=started,
                                finished_at=self._now(),
                                reason=f"{type(exc).__name__}: {exc}",
                                errors=(f"{type(exc).__name__}: {exc}",))
        if (result.operation_id != plan.operation_id or result.action != plan.action
                or result.target_key != plan.target.key):
            return ActionResult(action=plan.action, outcome=Outcome.UNKNOWN,
                                operation_id=plan.operation_id,
                                target_key=plan.target.key, started_at=started,
                                finished_at=self._now(),
                                reason="executor devolveu resultado de outra operação; "
                                       "o contrato do plano não foi respeitado")
        return replace(result, operation_id=plan.operation_id,
                       started_at=result.started_at or started,
                       finished_at=result.finished_at or self._now())

    @staticmethod
    def _refuse(plan: ActionPlan, reason: str) -> ActionResult:
        return ActionResult(action=plan.action, outcome=Outcome.REFUSED,
                            operation_id=plan.operation_id, target_key=plan.target.key,
                            reason=reason)
