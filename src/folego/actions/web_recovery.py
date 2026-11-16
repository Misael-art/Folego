"""Capacity-error recovery through the existing owner and common journal."""
import hashlib
import re
import time

from ..adapters import web_recovery as backend
from ..core.ai_accounts import inventory
from ..core.ai_sessions import timestamp
from ..core.web_gpt import installed_launchers
from ..orchestration import Coordinator
from ..orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity
from ..orchestration.journal import CorruptJournal

ACTION = 'web.recovery-request'


class WebRecovery:
    def __init__(self, monitor, *, coordinator=None, env=None, clock=time.time):
        self.monitor = monitor
        self.env = monitor.env if env is None else env
        self.coordinator = coordinator or Coordinator(now=clock)
        self.clock = clock
        self.results = {}

    def _accounts(self):
        return inventory(self.env, discover=self.monitor.discover, discover_web=installed_launchers)

    def request(self, account, receipt):
        at = timestamp(receipt.get('at'))
        if (not receipt.get('web_capacity_error') or at is None
                or not -5 <= self.clock() - at < 900
                or any(not isinstance(receipt.get(k), str) or not re.fullmatch('[0-9a-f]{64}', receipt[k])
                       for k in ('session', 'event'))):
            raise ValueError('Erro nativo recente com identidade é obrigatório')
        account_id = account['account_id']
        operation_id = hashlib.sha256((ACTION + account_id + receipt['session'] + receipt['event']).encode()).hexdigest()
        previous = self.coordinator.journal.state_of(operation_id)
        if previous and previous.intent:
            return self.coordinator.run(previous.intent, lambda _: None, wait=0)
        core = account.get('web_core_home')
        if not core:
            raise ValueError('Responsável do launcher desta conta não identificado')
        registered = backend.owner(core, env=self.env)
        plan = ActionPlan(ACTION, ResourceIdentity.entry(account_id),
                          params=dict(owner=registered, core=core, session=receipt['session'], event=receipt['event']),
                          operation_id=operation_id, created_at=at, expires_at=at + 900)

        def execute(plan):
            def result(outcome, reason):
                return ActionResult(ACTION, outcome, operation_id=plan.operation_id,
                                    target_key=plan.target.key, reason=reason)
            # Refresh both account binding and the native completion at the act.
            current = next((a for a in self._accounts() if a['account_id'] == account_id), None)
            if current != account:
                return result(Outcome.REFUSED, 'Conta mudou; solicitação bloqueada')
            current_receipts = [p for row in self.monitor.collect() if row['provider'] == 'web'
                                for p in row['pending']]
            if not any(p.get('account_id') == account_id and p.get('session') == receipt['session']
                       and p.get('event') == receipt['event'] and p.get('web_capacity_error') for p in current_receipts):
                return result(Outcome.REFUSED, 'O turno mudou ou já foi visto; solicitação bloqueada')
            records, problems = self.coordinator.journal.load()
            if problems:
                return result(Outcome.REFUSED, 'Diário inconsistente; solicitação bloqueada')
            prior = [r for r in records if r.plan and r.plan.action == ACTION
                     and r.plan.target.key == account_id and r.operation_id != plan.operation_id]
            results = {r.operation_id: r.result for r in records if r.result}
            if any(r.operation_id not in results or results[r.operation_id].outcome == Outcome.UNKNOWN for r in prior):
                return result(Outcome.REFUSED, 'Solicitação anterior incerta; consulte/reconcilie o ID antes de repetir')
            attempts = [r.ts for r in prior if self.clock() - r.ts < 600
                        and r.operation_id != plan.operation_id]
            if len(attempts) >= 3 or any(self.clock() - t < 60 for t in attempts):
                return result(Outcome.REFUSED, 'Recuperação em espera ou disjuntor aberto (3 solicitações/10 min)')
            try:
                accepted = backend.request(core, registered, env=self.env)
            except ValueError as error:
                return result(Outcome.REFUSED, str(error))
            return result(Outcome.PARTIAL if accepted else Outcome.UNKNOWN,
                          'Ciclo solicitado ao responsável; recuperação e resposta Web ainda não comprovadas'
                          if accepted else 'Solicitação não confirmada; consulte o mesmo ID antes de repetir')

        return self.coordinator.run(plan, execute, wait=0)

    def handle(self, rows, *, since, account_id=None):
        accounts = None
        for row in rows:
            if row.get('provider') != 'web':
                continue
            for receipt in row.get('pending', ()):
                if (not receipt.get('web_capacity_error') or receipt.get('at', 0) < since
                        or account_id is not None and receipt.get('account_id') != account_id):
                    continue
                key = (receipt.get('account_id'), receipt.get('session'), receipt.get('event'))
                if key in self.results:
                    receipt['web_recovery'] = dict(self.results[key])
                    continue
                try:
                    if accounts is None:
                        accounts = self._accounts()
                    account = next(a for a in accounts if a['provider'] == 'web'
                                   and a['account_id'] == receipt.get('account_id'))
                    outcome = self.request(account, receipt)
                    receipt['web_recovery'] = dict(outcome=outcome.outcome, operation_id=outcome.operation_id,
                                                   detail=outcome.reason)
                    if len(self.results) >= 256:
                        self.results.pop(next(iter(self.results)))
                    self.results[key] = dict(receipt['web_recovery'])
                except (OSError, ValueError, RuntimeError, StopIteration, CorruptJournal) as error:
                    receipt['web_recovery'] = dict(outcome='recusa', detail=str(error) or 'Conta não identificada')
        return rows
