"""Delegate to an installed, opted-in owner; never repair a browser ourselves."""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from ..core.ai_sessions import timestamp


STATES = {
    'ready': 'Infraestrutura local verificada; resposta Web ainda não comprovada',
    'login-required': 'Renove o login no ChatGPT dentro do launcher desta conta',
    'permission-required': 'Confira a permissão do conector no responsável pelo Web',
    'waiting-for-idle': 'Recuperação aguardando o encerramento do turno ativo',
    'waiting-for-resources': 'Recuperação aguardando margem de recursos',
    'cooldown': 'Recuperação em intervalo de espera',
    'circuit-open': 'Recuperação pausada após tentativas repetidas',
    'awaiting-validation': 'Reparo local realizado; valide uma nova resposta Web',
    'upstream-unavailable': 'Provedor indisponível; aguarde antes de tentar novamente',
    'rate-limited': 'Limite de solicitações do provedor; aguarde',
    'quota-exhausted': 'Franquia do provedor esgotada; confira no cliente',
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
    import json
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


def status(core_home, *, now=None):
    """Sanitized last observation, independent of model capacity and quota."""
    import json
    now = time.time() if now is None else now
    try:
        record = json.loads(trusted_bytes(Path(core_home).parent / 'recovery-state.json'))
        at = timestamp(record.get('observedAt'))
        if at is None or not -5 <= now - at <= 150:
            raise ValueError('Observação do responsável antiga ou desconhecida')
        state = record.get('state')
        if not isinstance(state, str):
            raise ValueError('Estado do responsável desconhecido')
        return dict(state=state if state in STATES else 'attention', checked_at=at,
                    detail=STATES.get(state, 'Consulte o diagnóstico do responsável pelo Web'))
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(state='unknown', detail='Diagnóstico recente do responsável não disponível')


def request(core_home, expected, *, env=None, run=subprocess.run):
    """Revalidate owner and systemd binding at the act. Only request its cycle."""
    if owner(core_home, env=env) != expected:
        raise ValueError('Responsável mudou; solicitação bloqueada')
    import json
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
