"""Delegate to an installed, opted-in owner; never repair a browser ourselves."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from ..core.ai_sessions import WEB_RECOVERY_MAX_AGE, timestamp


STATES = {
    'ready': 'Infraestrutura local verificada; resposta Web ainda não comprovada',
    'login-required': 'Renove o login no ChatGPT dentro do launcher desta conta',
    'permission-required': 'Confira a permissão do conector no responsável pelo Web',
    'waiting-for-idle': 'Recuperação aguardando a ociosidade do launcher',
    'waiting-for-resources': 'Recuperação aguardando margem de recursos',
    'off': 'Monitor de recuperação desativado no responsável',
    'repairable': 'O responsável identificou uma ação de recuperação',
    'repair-failed': 'Uma ação do responsável falhou; confira o diagnóstico no PhaseZero',
    'cooldown': 'Recuperação em intervalo de espera',
    'circuit-open': 'Recuperação pausada após tentativas repetidas',
    'awaiting-validation': 'Reparo local realizado; valide uma nova resposta Web',
    'upstream-unavailable': 'Provedor indisponível; aguarde antes de tentar novamente',
    'rate-limited': 'Limite de solicitações do provedor; aguarde',
    'quota-exhausted': 'Franquia do provedor esgotada; confira no cliente',
    'turn-stuck': 'O responsável sinalizou uma tarefa de longa duração',
}


def trusted_bytes(path, limit=65536):
    path = Path(path)
    if path.resolve() != path.absolute():
        raise ValueError('Caminho do responsável simbólico; preservado')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or info.st_size > limit):
        raise ValueError('Arquivo do responsável não confiável; preservado')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Arquivo do responsável acima do orçamento')
    return data


def owner(core_home, *, env=None):
    """Recognize the existing PhaseZero recovery protocol, bound to this root.

    Optional adapter only. Other launchers retain passive monitoring. No global
    PhaseZero command or alternate account is selected as a fallback.
    """
    env = os.environ if env is None else env
    root = Path(core_home).absolute().parent
    state = json.loads(trusted_bytes(root / 'state.json'))
    if not isinstance(state, dict) or type(state.get('schemaVersion')) is not int or state['schemaVersion'] != 1:
        raise ValueError('Registro do responsável desconhecido')
    recovery = state.get('recovery')
    if (not isinstance(state.get('optIn'), dict) or not state['optIn']
            or not isinstance(recovery, dict) or recovery.get('enabled') is not True):
        raise ValueError('Recuperação do responsável não habilitada nesta conta')
    files = recovery.get('files')
    if not isinstance(files, dict) or len(files) != 4:
        raise ValueError('Manifesto do responsável desconhecido')
    configs = {Path(env.get('HOME') or Path.home()) / '.config'}
    if env.get('XDG_CONFIG_HOME'):
        configs.add(Path(env['XDG_CONFIG_HOME']))
    services = [Path(p) for p in files if Path(p).parent in {c / 'systemd/user' for c in configs}
                and re.fullmatch(r'pz-chatgpt-web-[a-z0-9-]+-health.service', Path(p).name)]
    if len(services) != 1:
        raise ValueError('Unit de recuperação da conta não identificada')
    service = services[0]
    wrapper = root / 'bin/chatgpt-web-recovery.sh'
    target = root / 'bin/chatgpt-web-recovery.target'
    expected = {str(p) for p in (service, service.with_suffix('.timer'), wrapper, target)}
    if set(files) != expected:
        raise ValueError('Manifesto não pertence ao responsável desta conta')
    for path, digest in files.items():
        if not isinstance(digest, str) or hashlib.sha256(trusted_bytes(path)).hexdigest() != digest:
            raise ValueError('Arquivos do responsável alterados; preservados')
    return dict(unit=service.name, service=str(service), wrapper=str(wrapper),
                digest=hashlib.sha256(trusted_bytes(root / 'state.json')).hexdigest())


def _turn_state(record, observation):
    turns = observation.get('launcherTurns')
    active = {turn for turn in turns if isinstance(turn, str) and turn} if isinstance(turns, list) else set()
    stuck = record.get('stuckTurns')
    if (record['state'] == 'turn-stuck' and isinstance(stuck, list)
            and any(isinstance(turn, str) and turn in active for turn in stuck)):
        return 'long-running'
    return 'active' if active or observation.get('busy') is True else 'unknown'


def _connector_status(record, observation, *, at, now):
    if 'pendingAction' in record or not isinstance(observation, dict):
        return dict(state='unknown')
    incomplete = observation.get('launcherSetupIncomplete') is True
    # Legacy receipts can prove the setup was incomplete. Their action list
    # also includes deferred attempts, and False can mean the launcher was unreadable.
    attempt = record.get('connectorVerification') if record.get('schemaVersion') == 1 else None
    if isinstance(attempt, dict):
        state = attempt.get('state')
        finished = timestamp(attempt.get('at'))
        if (state in ('verified', 'deferred', 'failed', 'unknown') and finished is not None
                and at <= finished <= now + 5 and (state != 'verified' or not incomplete)):
            return dict(state=state, checked_at=finished)
    return dict(state='pending' if incomplete else 'unknown')


def status(core_home, *, now=None):
    """Project bounded, account-local recovery metadata from the existing owner."""
    now = time.time() if now is None else now
    result = dict(state='unknown', freshness='unknown', turn_state='unknown', connector=dict(state='unknown'),
                  detail='Diagnóstico recente do responsável não disponível')
    try:
        record = json.loads(trusted_bytes(Path(core_home).parent / 'recovery-state.json'))
    except (OSError, ValueError, RecursionError):
        return result
    if not isinstance(record, dict) or not isinstance(record.get('state'), str):
        return result
    version = record.get('schemaVersion')
    if 'schemaVersion' in record and (type(version) is not int or version != 1):
        return result
    at = timestamp(record.get('observedAt'))
    if at is None or at > now + 5:
        return result
    result['last_observed_at'] = at
    next_attempt = timestamp(record.get('nextAttemptAt'))
    if next_attempt is not None and now < next_attempt <= at + 600:
        result['next_attempt_at'] = next_attempt
    if now - at > WEB_RECOVERY_MAX_AGE:
        result.update(freshness='stale', detail='Diagnóstico atual do responsável desconhecido')
        return result
    state = record['state']
    observation = record.get('after', record.get('observation'))
    result.update(state=state if state in STATES else 'attention', freshness='fresh', checked_at=at,
                  detail=STATES.get(state, 'Consulte o diagnóstico do responsável pelo Web'),
                  connector=_connector_status(record, observation, at=at, now=now))
    if isinstance(observation, dict):
        result['turn_state'] = _turn_state(record, observation)
    return result


def request(core_home, expected, *, env=None, run=subprocess.run):
    """Revalidate owner and systemd binding at the act. Only request its cycle."""
    if owner(core_home, env=env) != expected:
        raise ValueError('Responsável mudou; solicitação bloqueada')
    try:
        record = json.loads(trusted_bytes(Path(core_home).parent / 'recovery-state.json'))
        if not isinstance(record, dict) or record.get('pendingAction'):
            raise ValueError('Reparo do responsável sem resultado; consulte antes de repetir')
    except FileNotFoundError:
        pass  # Its first cycle still revalidates policy.
    result = run(['systemctl', '--user', 'show', expected['unit'],
                  '-p', 'FragmentPath', '-p', 'DropInPaths', '-p', 'NeedDaemonReload', '-p', 'LoadState',
                  '-p', 'ExecStart'], capture_output=True, text=True, timeout=4)
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if (result.returncode or properties.get('FragmentPath') != expected['service']
            or properties.get('LoadState') != 'loaded' or properties.get('DropInPaths') != ''
            or properties.get('NeedDaemonReload') != 'no'
            or f"path={expected['wrapper']} ; argv[]={expected['wrapper']} ;" not in properties.get('ExecStart', '')):
        raise ValueError('Unit efetiva não corresponde ao responsável registrado')
    if owner(core_home, env=env) != expected:
        raise ValueError('Autorização do responsável mudou antes da solicitação')
    # The owner keeps its own lock, idle check, intent, budget and circuit breaker.
    # Non-blocking submission is not proof of a repair or a successful Web turn.
    return run(['systemctl', '--user', 'start', '--no-block', expected['unit']],
               capture_output=True, text=True, timeout=4).returncode == 0
