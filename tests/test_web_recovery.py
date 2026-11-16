import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from folego.adapters import web_recovery as backend
from folego.actions import web_recovery as action
from folego.core import web_gpt
from folego.core.agent_deliveries import DeliveryMonitor
from folego.orchestration import Coordinator
from folego.orchestration.journal import Journal
from folego.orchestration.models import Outcome


@pytest.fixture
def owner(tmp_path):
    root = tmp_path / 'web'
    config = tmp_path / '.config'
    service = config / 'systemd/user/pz-chatgpt-web-launcher-health.service'
    wrapper = root / 'bin/chatgpt-web-recovery.sh'
    target = root / 'bin/chatgpt-web-recovery.target'
    files = {}
    for path in (service, service.with_suffix('.timer'), wrapper, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('owned fixture ' + path.name)
        path.chmod(0o600)
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    state = dict(schemaVersion=1, optIn=dict(at='registered'), recovery=dict(enabled=True, files=files))
    (root / 'state.json').write_text(json.dumps(state))
    (root / 'state.json').chmod(0o600)
    return SimpleNamespace(root=root, core=root / 'core-home', state=state, service=service,
                           env=dict(HOME=str(tmp_path), XDG_CONFIG_HOME=str(config)), wrapper=wrapper)


def test_only_verified_enabled_owner_can_receive_request(owner):
    registered = backend.owner(owner.core, env=owner.env)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if 'show' in argv:
            out = (f'FragmentPath={owner.service}\nDropInPaths=\nNeedDaemonReload=no\nLoadState=loaded\n'
                   f'ExecStart={{ path={owner.wrapper} ; argv[]={owner.wrapper} ; }}\n')
            return SimpleNamespace(returncode=0, stdout=out)
        return SimpleNamespace(returncode=0)
    assert backend.request(owner.core, registered, env=owner.env, run=run)
    assert calls[-1] == ['systemctl', '--user', 'start', '--no-block', owner.service.name]
    owner.wrapper.write_text('changed')
    with pytest.raises(ValueError): backend.request(owner.core, registered, env=owner.env, run=run)
    assert len(calls) == 2


@pytest.mark.parametrize('fault', ['disabled', 'unknown-schema', 'missing-file', 'symlink', 'writable', 'other-account'])
def test_unknown_or_altered_owner_never_runs(owner, fault):
    if fault == 'disabled': owner.state['recovery']['enabled'] = False
    elif fault == 'unknown-schema': owner.state['schemaVersion'] = 2
    elif fault == 'missing-file': owner.wrapper.unlink()
    elif fault == 'symlink':
        dest = owner.wrapper.with_suffix('.own')
        owner.wrapper.rename(dest)
        owner.wrapper.symlink_to(dest)
    elif fault == 'writable': owner.wrapper.chmod(0o666)
    elif fault == 'other-account':
        owner.state['recovery']['files'][str(owner.root / 'other.service')] = '0' * 64
    (owner.root / 'state.json').write_text(json.dumps(owner.state))
    with pytest.raises((ValueError, OSError)): backend.owner(owner.core, env=owner.env)


@pytest.mark.parametrize('change', ['DropInPaths=override.conf', 'NeedDaemonReload=yes', 'LoadState=not-found',
                                     'FragmentPath=/other', 'ExecStart=other'])
def test_overridden_effective_systemd_unit_is_blocked(owner, change):
    registered = backend.owner(owner.core, env=owner.env)
    calls = []
    props = dict(FragmentPath=str(owner.service), DropInPaths='', NeedDaemonReload='no', LoadState='loaded',
                 ExecStart=f'{{ path={owner.wrapper} ; argv[]={owner.wrapper} ; }}')
    key, value = change.split('=', 1)
    props[key] = value
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='\n'.join(k + '=' + v for k, v in props.items()))
    with pytest.raises(ValueError): backend.request(owner.core, registered, env=owner.env, run=run)
    assert len(calls) == 1 and 'show' in calls[0]


def test_recent_login_diagnosis_is_visible_without_claiming_capacity_or_quota(owner):
    now = time.time()
    record = dict(observedAt=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                  state='login-required', observation=dict(secret='not exported'))
    (owner.root / 'recovery-state.json').write_text(json.dumps(record))
    result = web_gpt.observe(owner.core, owner.root / 'data', now=now, live=False)
    assert 'Renove o login' in result['web_recovery']['detail']
    assert result['web_service']['state'] == 'unknown'
    assert result['remaining'] is None
    assert 'secret' not in json.dumps(result)
    assert backend.status(owner.core, now=now + 151)['state'] == 'unknown'


def test_web_monitor_reports_deferred_race_without_treating_actions_as_success(owner, monkeypatch, capsys):
    from folego import cli
    from folego.core import ai_sessions

    now = time.time()
    path = owner.root / 'recovery-state.json'
    record = dict(observedAt=now - 4, state='waiting-for-idle', actions=['reverify-connector'],
                  observation=dict(busy=False, launcherTurns=[], launcherSetupIncomplete=True),
                  after=dict(busy=True, launcherTurns=['private-trace'], launcherSetupIncomplete=True),
                  nextAttemptAt=now + 56)
    path.write_text(json.dumps(record))
    legacy = backend.status(owner.core, now=now)
    assert legacy['turn_state'] == 'active'
    assert legacy['connector']['state'] == 'pending'

    record.update(schemaVersion=1, connectorVerification=dict(state='deferred', at=now - 2, secret='private'))
    path.write_text(json.dumps(record))
    item = dict(provider='web', **web_gpt.observe(owner.core, owner.root / 'data', now=now))
    monkeypatch.setattr(ai_sessions, 'collect', lambda: [item])
    assert cli.main(['ai', 'status', '--json']) == 0
    output = capsys.readouterr().out
    recovery = json.loads(output)['meters'][0]['web_recovery']
    assert recovery['connector']['state'] == 'deferred'
    assert recovery['freshness'] == 'fresh' and recovery['next_attempt_at'] == now + 56
    assert 'private' not in output and 'actions' not in output
    assert 'Verificação adiada' in ai_sessions.describe(item, now=now)

    record.update(state='ready', connectorVerification=dict(state='verified', at=now),
                  after=dict(busy=False, launcherTurns=[], launcherSetupIncomplete=False))
    path.write_text(json.dumps(record))
    assert backend.status(owner.core, now=now)['connector']['state'] == 'verified'


@pytest.mark.parametrize('fault, expected', [
    ('legacy', 'unknown'), ('version', 'unknown'), ('version-bool', 'unknown'),
    ('invalid-after', 'unknown'), ('pending', 'unknown'), ('old-result', 'unknown'),
    ('conflict', 'pending'), ('failed', 'failed'), ('unknown', 'unknown'),
])
def test_connector_readiness_requires_fresh_consistent_confirmation(owner, fault, expected):
    now = time.time()
    record = dict(schemaVersion=1, observedAt=now - 10, state='ready', actions=['reverify-connector'],
                  observation=dict(busy=False, launcherTurns=[], launcherSetupIncomplete=False),
                  connectorVerification=dict(state='verified', at=now - 5))
    if fault == 'legacy': record.pop('schemaVersion')
    elif fault == 'version': record['schemaVersion'] = 2
    elif fault == 'version-bool': record['schemaVersion'] = True
    elif fault == 'invalid-after': record['after'] = None
    elif fault == 'pending': record['pendingAction'] = 'reverify-connector'
    elif fault == 'old-result': record['connectorVerification']['at'] = now - 151
    elif fault == 'conflict': record['observation']['launcherSetupIncomplete'] = True
    else: record['connectorVerification']['state'] = fault
    (owner.root / 'recovery-state.json').write_text(json.dumps(record))
    assert backend.status(owner.core, now=now)['connector']['state'] == expected


def test_web_monitor_preserves_only_age_and_schedule_when_a_receipt_expires(owner):
    from folego.core import ai_sessions

    now = time.time()
    record = dict(observedAt=now - 150, state='turn-stuck', stuckTurns=['private-trace'],
                  observation=dict(busy=True, launcherTurns=['private-trace'], launcherSetupIncomplete=True),
                  nextAttemptAt=now + 90)
    (owner.root / 'recovery-state.json').write_text(json.dumps(record))
    fresh = backend.status(owner.core, now=now)
    assert fresh['turn_state'] == 'long-running' and fresh['connector']['state'] == 'pending'
    # The same snapshot can remain open while a background collection is delayed.
    lines = ai_sessions.web_recovery_lines(fresh, now=now + 1)
    assert any('Último diagnóstico há 2 min' in line for line in lines)
    assert any('Última previsão de nova tentativa' in line for line in lines)
    assert all('30 min' not in line and 'Verificação pendente' not in line for line in lines)
    stale = backend.status(owner.core, now=now + 1)
    assert stale['freshness'] == 'stale' and stale['state'] == 'unknown'
    assert stale['turn_state'] == stale['connector']['state'] == 'unknown'
    assert stale['last_observed_at'] == now - 150 and stale['next_attempt_at'] == now + 90
    assert 'private-trace' not in json.dumps(stale)
    assert 'next_attempt_at' not in backend.status(owner.core, now=now + 91)


def test_pending_owner_effect_blocks_another_cycle(owner):
    registered = backend.owner(owner.core, env=owner.env)
    (owner.root / 'recovery-state.json').write_text(json.dumps(dict(pendingAction='restart-backend')))
    with pytest.raises(ValueError, match='sem resultado'):
        backend.request(owner.core, registered, env=owner.env, run=lambda *_a, **_k: pytest.fail('effect ran'))


def test_explicit_environment_keeps_the_installed_launcher_owner_binding(owner, monkeypatch):
    for name in ('core-home', 'codex-home', 'launcher-data'):
        (owner.root / name).mkdir()
    def launchers(env):
        assert env == owner.env
        return [dict(core_home=str(owner.core), codex_home=str(owner.root / 'codex-home'),
                     launcher_data=str(owner.root / 'launcher-data'))]
    monkeypatch.setattr(action, 'installed_launchers', launchers)
    monitor = SimpleNamespace(env=owner.env, discover=lambda: [])
    rows = action.WebRecovery(monitor)._accounts()
    bound = next(a for a in rows if a['path'] == str(owner.root / 'codex-home'))
    assert bound['web_core_home'] == str(owner.core)


@pytest.fixture
def recovery(owner, monkeypatch):
    now = time.time()
    path = owner.root / 'codex-home/sessions/2026/11/08/rollout-one.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(type='session_meta', payload=dict(id='one', source='cli'))) + '\n')
    account = dict(provider='web', account_id='account', path=str(owner.root / 'codex-home'),
                   web_core_home=str(owner.core))
    monitor = DeliveryMonitor(env=owner.env, state=owner.root / 'deliveries.json', clock=lambda: now, discover=lambda: [])
    monitor._accounts = lambda _: [('web', account['path'])]
    monitor.collect()
    now += 1
    row = dict(type='event_msg', timestamp=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
               payload=dict(type='task_complete', turn_id='turn-1', error=dict(
                   message='Selected model is at capacity. Please try a different model.', codex_error_info='server_overloaded')))
    with path.open('a') as f: f.write(json.dumps(row) + '\n')
    coordinator = Coordinator(journal=Journal(owner.root / 'operations.jsonl'),
                              lock_path=owner.root / 'coordinator.lock', now=lambda: now)
    monkeypatch.setattr(action, 'inventory', lambda *_a, **_k: [account])
    monkeypatch.setattr('folego.core.ai_accounts.account_id', lambda *_: 'account')
    worker = action.WebRecovery(monitor, coordinator=coordinator, clock=lambda: now)
    calls = []
    def request(*args, **kwargs):
        records, problems = coordinator.journal.load()
        assert not problems and records[-1].kind == 'intent'
        calls.append(args)
        return True
    monkeypatch.setattr(backend, 'request', request)
    return SimpleNamespace(worker=worker, monitor=monitor, coordinator=coordinator, calls=calls,
                           path=path, now=now, account=account)


def test_native_capacity_requests_once_after_durable_intent_and_survives_restart(recovery):
    r = recovery
    rows = r.worker.handle(r.monitor.collect(), since=r.now - 1)
    receipt = next(row for row in rows if row['provider'] == 'web')['pending'][0]
    result = receipt['web_recovery']
    assert result['outcome'] == 'parcial' and len(r.calls) == 1
    worker = action.WebRecovery(r.monitor, coordinator=r.coordinator, clock=lambda: r.now)
    repeated = worker.handle(r.monitor.collect(), since=r.now - 1)
    assert next(row for row in repeated if row['provider'] == 'web')['pending'][0]['web_recovery'] == result
    assert len(r.calls) == 1
    journal = r.coordinator.journal.path.read_text()
    assert 'Selected model' not in journal and 'server_overloaded' not in journal


def test_old_errors_are_silent_at_gui_startup(recovery):
    recovery.worker.handle(recovery.monitor.collect(), since=recovery.now + 1)
    assert recovery.calls == []


def test_new_task_between_detection_and_act_prevents_recovery(recovery):
    rows = recovery.monitor.collect()
    with recovery.path.open('a') as f:
        f.write(json.dumps(dict(type='event_msg', timestamp=dt.datetime.fromtimestamp(
            recovery.now, dt.timezone.utc).isoformat(), payload=dict(type='task_started'))) + '\n')
    result = recovery.worker.handle(rows, since=recovery.now - 1)
    assert recovery.calls == []
    assert next(row for row in result if row['provider'] == 'web')['pending'][0]['web_recovery']['outcome'] == 'recusa'


def test_lost_submission_is_not_repeated(recovery, monkeypatch):
    def lost(*args, **kwargs):
        recovery.calls.append(True)
        raise TimeoutError('test timeout')
    monkeypatch.setattr(backend, 'request', lost)
    for _ in range(2):
        worker = action.WebRecovery(recovery.monitor, coordinator=recovery.coordinator, clock=lambda: recovery.now)
        rows = worker.handle(recovery.monitor.collect(), since=recovery.now - 1)
        assert next(row for row in rows if row['provider'] == 'web')['pending'][0]['web_recovery']['outcome'] == 'desconhecido'
    assert len(recovery.calls) == 1


def next_failure(recovery, turn):
    row = dict(type='event_msg', timestamp=dt.datetime.fromtimestamp(recovery.now, dt.timezone.utc).isoformat(),
               payload=dict(type='task_complete', turn_id=turn, error=dict(
                   message='Selected model is at capacity. Please try a different model.')))
    with recovery.path.open('a') as f: f.write(json.dumps(row) + '\n')


def test_repeated_capacity_turns_respect_cooldown_and_budget(recovery):
    r = recovery
    r.worker.handle(r.monitor.collect(), since=r.now - 1)
    next_failure(r, 'too-soon')
    r.worker.handle(r.monitor.collect(), since=r.now - 1)
    assert len(r.calls) == 1
    # The refused intent also consumes the conservative request budget.
    r.worker.clock = lambda: r.now + 61
    next_failure(r, 'third')
    r.worker.handle(r.monitor.collect(), since=r.now - 1)
    assert len(r.calls) == 2
    next_failure(r, 'fourth')
    r.worker.handle(r.monitor.collect(), since=r.now - 1)
    assert len(r.calls) == 2


def test_unfinished_intent_blocks_restart_and_later_turns(recovery):
    r = recovery
    r.worker.handle(r.monitor.collect(), since=r.now - 1)
    journal = r.coordinator.journal.path
    journal.write_text(journal.read_text().splitlines()[0] + '\n')
    worker = action.WebRecovery(r.monitor, coordinator=r.coordinator, clock=lambda: r.now + 61)
    rows = worker.handle(r.monitor.collect(), since=r.now - 1)
    assert next(row for row in rows if row['provider'] == 'web')['pending'][0]['web_recovery']['outcome'] == 'desconhecido'
    next_failure(r, 'later')
    worker.handle(r.monitor.collect(), since=r.now - 1)
    assert len(r.calls) == 1


def test_cli_requires_confirmation_before_collecting_native_state(monkeypatch, capsys):
    from folego import cli
    monkeypatch.setattr(DeliveryMonitor, 'collect', lambda _: pytest.fail('read before confirmation'))
    assert cli.main(['ai', 'recover-web', '--json']) == 2
