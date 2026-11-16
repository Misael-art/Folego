"""Passive observations of the installed Codex ChatGPT Web launcher.

Only the launcher's own files and loopback health endpoint are read. The
read-only tunnel runtime inspection is cached; no turn, login or repair runs.
"""
from __future__ import annotations

import http.client
import itertools
import json
import os
from pathlib import Path
import stat
import subprocess
import time


_TUNNEL_CACHE = {}
_TUNNEL_TTL = 300


def installed_launchers(env, proc=Path('/proc')):
    """Find official packaged launcher paths from owned processes, not PhaseZero."""
    home = Path(env.get('HOME') or Path.home()).resolve()
    roots = {}
    try:
        directories = itertools.islice(proc.iterdir(), 8192)
        for directory in directories:
            if not directory.name.isdigit():
                continue
            try:
                if directory.stat().st_uid != os.getuid():
                    continue
                exe = Path(os.readlink(directory / 'exe'))
                if (exe.name != 'codex-web-gpt-launcher' or exe.parent.name != 'app'
                        or exe.parent.parent.parent.name != 'packages'):
                    continue
                root = exe.parent.parent.parent.parent.resolve()
                if not root.is_relative_to(home):
                    continue
                with (directory / 'cmdline').open('rb') as stream:
                    argv = stream.read(4096).split(b'\0')
                item = roots.setdefault(str(root), dict(core_home=str(root / 'core-home'),
                                                        launcher_data=str(root / 'launcher-data'),
                                                        codex_home=str(root / 'codex-home')))
                for arg in argv:
                    if arg.startswith(b'--user-data-dir='):
                        path = Path(arg.partition(b'=')[2].decode(errors='strict'))
                        if path.is_absolute() and path.resolve().is_relative_to(home):
                            item['launcher_data'] = str(path.resolve())
            except (OSError, ValueError, UnicodeError):
                continue
    except OSError:
        pass
    return list(roots.values())[:4]


def local_limits(path, now):
    """Report local submissions only. Never derive OpenAI remaining/reset."""
    from .ai_sessions import read_json
    result = dict(windows=[], remaining=None, plan=None, paid_until=None,
                  access='não verificado', renewal='não verificada',
                  limits_action=False, local_usage=None,
                  reason='Limite e reposição da conta ChatGPT não informados pelo WebGPT')
    try:
        state = read_json(path)
    except FileNotFoundError:
        result['reason'] += '; histórico local do launcher ausente'
        return result
    except (OSError, ValueError):
        result['reason'] += '; histórico local do launcher ilegível ou desconhecido'
        return result
    accounts, active = state.get('accounts'), state.get('activeAccountKey')
    account = accounts.get(active) if (state.get('version') == 1 and isinstance(accounts, dict)
                                   and isinstance(active, str) and active) else None
    if not isinstance(account, dict) or not isinstance(account.get('events'), list):
        result['reason'] += '; conta ativa do histórico desconhecida'
        return result
    checked = account.get('checkedAt')
    if type(checked) is int and 0 < checked <= (now + 300) * 1000:
        result['limits_checked_at'] = checked / 1000
        if now - checked / 1000 > 86400:
            result['reason'] += '; última classificação do plano antiga'
    plan = account.get('plan')
    if plan in ('pro_100', 'pro_200'):
        result['plan'] = 'Pro 5x (histórico local)' if plan == 'pro_100' else 'Pro 20x (histórico local)'
    since = account.get('initializedAt')
    if plan not in ('pro_100', 'pro_200'):
        result['reason'] += '; rastreamento de plano não suportado ou não confirmado'
        return result
    if type(since) is not int or not 0 < since <= now * 1000:
        result['reason'] += '; início do rastreamento desconhecido'
        return result
    counts = {'gpt-6-pro': 0, 'gpt-5.6-pro': 0, 'pro-unknown': 0}
    events = account['events']
    if len(events) > 10000:
        result['reason'] += '; histórico acima do orçamento'
        return result
    for event in events:
        if not isinstance(event, dict):
            result['reason'] += '; histórico inválido'
            return result
        at, model = event.get('at'), event.get('model')
        if (type(at) is not int or not since <= at <= (now + 300) * 1000
                or model not in ('gpt-6-pro', 'gpt-5.6-pro', 'pro-unknown', 'other')):
            result['reason'] += '; histórico inválido'
            return result
        if model in counts and at > (now - 7 * 86400) * 1000:
            counts[model] += 1
    result['local_usage'] = dict(counts=counts, since=since / 1000,
                                  partial=True, period='últimos 7 dias')
    result['source'] = 'Histórico parcial de envios pelo launcher; não inclui outros clientes nem saldo OpenAI'
    return result


def service_status(core_home):
    from .ai_sessions import read_json
    checked_at = time.time()
    try:
        config = read_json(Path(core_home) / 'config.json')
    except (OSError, ValueError):
        return dict(state='unknown', detail='Configuração do WebGPT ausente ou ilegível', checked_at=checked_at)
    host, port = config.get('host'), config.get('port')
    if host not in ('127.0.0.1', '::1') or type(port) is not int or not 1 <= port <= 65535:
        return dict(state='unknown', detail='Endpoint local não confirmado', checked_at=checked_at)
    result = dict(state='unavailable', detail='Serviço local não respondeu',
                  mode=config.get('mode'), checked_at=checked_at)
    try:
        connection = http.client.HTTPConnection(host, port, timeout=.7)
        try:
            connection.request('GET', '/healthz')
            response = connection.getresponse()
            raw = response.read(16385)
        finally:
            connection.close()
        if response.status != 200 or len(raw) > 16384:
            return result
        body = json.loads(raw)
        if (not isinstance(body, dict) or body.get('service') != 'codex-chatgpt-web'
                or body.get('status') != 'ok' or body.get('mode') != config.get('mode')
                or body.get('version') != config.get('releaseVersion')
                or body.get('accepting_turns') is not True):
            return result
        result.update(state='ready', detail='Serviço local aceita solicitações',
                      version=body.get('version') if isinstance(body.get('version'), str) else None)
        catalog = body.get('last_model_catalog_result')
        if isinstance(catalog, dict):
            result['catalog_status'] = catalog.get('status') if type(catalog.get('status')) is int else None
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return result


def tunnel_status(core_home, alias, now=None):
    now = time.monotonic() if now is None else now
    checked_at = time.time()
    if not isinstance(alias, str) or not alias or len(alias) > 100:
        return dict(state='unknown', detail='Alias do túnel não confirmado', checked_at=checked_at)
    binary = Path(core_home) / 'bin/tunnel-client'
    try:
        info = binary.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            return dict(state='unknown', detail='Cliente de túnel não confiável', checked_at=checked_at)
    except OSError:
        return dict(state='unknown', detail='Cliente de túnel ausente', checked_at=checked_at)
    key = (str(binary), info.st_mtime_ns, alias)
    cached = _TUNNEL_CACHE.get(key)
    if cached and now - cached[0] < _TUNNEL_TTL:
        return dict(cached[1])
    result = dict(state='unknown', detail='Estado local do túnel não disponível', checked_at=checked_at)
    try:
        response = subprocess.run([str(binary), 'runtimes', 'cleanup', '--json'],
                                  capture_output=True, timeout=2, check=False)
        if response.returncode == 0 and len(response.stdout) <= 65536:
            document = json.loads(response.stdout)
            entries = document.get('entries') if isinstance(document, dict) else None
            if isinstance(document, dict) and document.get('apply') is False and isinstance(entries, list) and len(entries) <= 64:
                matches = [e for e in entries if isinstance(e, dict) and e.get('alias') == alias]
                if len(matches) == 1:
                    entry = matches[0]
                    ready = entry.get('classification') == 'live_runtime' and entry.get('runtime_state') == 'ready'
                    result = dict(state='ready' if ready else 'unavailable', checked_at=checked_at,
                                  detail='Runtime local do túnel pronto' if ready else 'Runtime local do túnel não pronto')
                elif not matches:
                    result = dict(state='unavailable', detail='Runtime local do túnel ausente', checked_at=checked_at)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if len(_TUNNEL_CACHE) > 8:
        _TUNNEL_CACHE.clear()
    _TUNNEL_CACHE[key] = (now, result)
    return dict(result)


def observe(core_home, launcher_data, *, now, live=False):
    result = local_limits(Path(launcher_data) / 'limits.json', now)
    result['web_service'] = service_status(core_home) if live else dict(state='unknown', detail='Serviço não consultado')
    result['web_tunnel'] = dict(state='unknown', detail='Túnel não consultado')
    result['web_inference'] = 'não comprovada; nenhum envio de teste foi realizado'
    from ..adapters.web_recovery import status
    result['web_recovery'] = status(core_home, now=now)
    if live:
        from .ai_sessions import read_json
        try:
            config = read_json(Path(core_home) / 'config.json')
            mode = config.get('mode')
            alias = (config.get('tunnel') or {}).get('alias') if isinstance(config.get('tunnel'), dict) else None
            if mode == 'full':
                result['web_tunnel'] = tunnel_status(core_home, alias)
            elif mode == 'browser-only':
                result['web_tunnel'] = dict(state='not_required', detail='Modo sem ferramentas')
        except (OSError, ValueError):
            pass
    return result
