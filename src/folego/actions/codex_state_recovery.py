"""Automatic rollback of an interrupted SQLite transaction in the Codex home.

Requested by the user on 26/11/2026 after Codex Desktop stopped at bootstrap
with ``attempt to write a readonly database``. Scope: rollback-mode databases
directly in the Codex home or its ``sqlite/`` folder, with a hot journal, held
by no process. Intent is recorded first, the pair is copied and verified, the
state is revalidated at the act and SQLite performs the rollback itself. No
process is signalled; Codex Desktop is reopened by the user.
"""
from __future__ import annotations

import hashlib
import time

from ..adapters import codex_state as backend
from ..orchestration import Coordinator, CoordinatorBusy, CorruptJournal
from ..orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity

ACTION = 'codex.state-rollback'
WINDOW = 3600
BUDGET = 3
BUCKET = 600


class CodexStateRecovery:
    def __init__(self, *, coordinator=None, home=None, clock=time.time):
        self.coordinator = coordinator or Coordinator(now=clock)
        self.home = home
        self.clock = clock

    def status(self) -> dict:
        try:
            found = backend.find_hot_journals(self.home)
        except (OSError, backend.StateError) as exc:
            return dict(state='unknown', detail=str(exc), targets=[])
        return dict(state='pending' if found else 'clean', targets=found,
                    detail=('Transação interrompida em ' + ', '.join(t['database'] for t in found))
                    if found else 'Nenhuma transação interrompida nos bancos do Codex')

    def _plan(self, target):
        # Same journal, same 10-minute window: one attempt. A refusal caused by
        # a race at the act is retried in a later window; the breaker bounds it.
        journal = target['journal_stat']
        now = self.clock()
        operation_id = hashlib.sha256('|'.join(map(str, (
            ACTION, target['database'], target['database_stat']['dev'], target['database_stat']['ino'],
            journal['ino'], journal['size'], journal['mtime_ns'], int(now // BUCKET)))).encode()).hexdigest()
        return ActionPlan(ACTION, ResourceIdentity.path(target['database'], dev=target['database_stat']['dev'],
                                                        ino=target['database_stat']['ino']),
                          params=dict(target=target), operation_id=operation_id,
                          created_at=now, expires_at=now + 300)

    def _breaker(self, plan):
        records, problems = self.coordinator.journal.load()
        if problems:
            return 'Diário inconsistente; reparo bloqueado'
        results = {r.operation_id: r.result for r in records if r.result}
        prior = [r for r in records if r.plan and r.plan.action == ACTION and r.operation_id != plan.operation_id]
        if any(r.plan.target.key == plan.target.key and
               (r.operation_id not in results or results[r.operation_id].outcome == Outcome.UNKNOWN) for r in prior):
            return 'Reparo anterior incerto neste banco; consulte o mesmo ID antes de repetir'
        recent = [r for r in prior if self.clock() - r.ts < WINDOW]
        if len(recent) >= BUDGET:
            return f'Disjuntor aberto: {BUDGET} reparos na última hora; revisão manual'
        return None

    def repair(self, target) -> ActionResult:
        plan = self._plan(target)
        try:
            # Cheap preflight outside the journal: a database in use is only
            # postponed, without spending an attempt.
            backend.revalidate(target)
        except (OSError, backend.StateError) as exc:
            return ActionResult(ACTION, Outcome.REFUSED, operation_id=plan.operation_id,
                                target_key=plan.target.key, reason=str(exc))

        def execute(plan):
            def result(outcome, reason, **effects):
                return ActionResult(ACTION, outcome, operation_id=plan.operation_id,
                                    target_key=plan.target.key, reason=reason, effects=effects)
            blocked = self._breaker(plan)
            if blocked:
                return result(Outcome.REFUSED, blocked)
            target = plan.params['target']
            from ..audit_profile import SUSPENDED, normal_effects
            with normal_effects() as allowed:
                if not allowed:
                    return result(Outcome.REFUSED, SUSPENDED)
                try:
                    backend.revalidate(target)
                    preserved = backend.preserve(target, plan.operation_id)
                    backend.revalidate(target)
                except (OSError, backend.StateError) as exc:
                    return result(Outcome.REFUSED, str(exc))
                try:
                    checked = backend.rollback(target)
                except (OSError, backend.StateError) as exc:
                    return result(Outcome.UNKNOWN, f'{exc}; cópia preservada em {preserved["folder"]}',
                                  recovery=preserved['folder'])
            return result(Outcome.OK, 'Transação interrompida revertida pelo SQLite; reabra o Codex Desktop '
                                      f'se ele estiver sem janela. Cópia em {preserved["folder"]}',
                          recovery=preserved['folder'], **checked)

        return self.coordinator.run(plan, execute, wait=0)

    def handle(self) -> list[dict]:
        """One monitoring tick. Returns only results of this tick's repairs."""
        try:
            found = backend.find_hot_journals(self.home)
        except (OSError, backend.StateError) as exc:
            return [dict(outcome=Outcome.REFUSED, detail=str(exc), database=None, operation_id=None)]
        reports = []
        for target in found:
            try:
                outcome = self.repair(target)
                reports.append(dict(outcome=outcome.outcome, detail=outcome.reason,
                                    database=target['database'], operation_id=outcome.operation_id))
            except (OSError, ValueError, CoordinatorBusy, CorruptJournal) as exc:
                reports.append(dict(outcome=Outcome.REFUSED, detail=str(exc) or 'Coordenador ocupado',
                                    database=target['database'], operation_id=None))
        return reports
