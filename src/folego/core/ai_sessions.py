"""Read-only AI quota observations. No Qt, account manager or token renewal.

Provider data is deliberately asymmetric: Codex reports rate limits, Claude
has a first-party usage endpoint, Grok's own CLI answers its billing extension
and Codex Web tunnels ChatGPT Web. Its launcher only counts its own sends;
that record is neither provider allowance nor a reset timestamp. A Web root's
Codex login is not that allowance. A reset
in the past invalidates an observation; it never creates a full allowance.
"""
from __future__ import annotations

import base64
import calendar
import copy
import hashlib
from email.utils import parsedate_to_datetime
import datetime as dt
import json
import math
import os
import selectors
import shutil
import subprocess
import tempfile
from pathlib import Path
import time
import urllib.request
import urllib.error

MAX_AGE = 900
MAX_FILE = 512 * 1024
MAX_TAIL = 64 * 1024
NAMES = {"codex": "Codex", "web": "Codex Web", "claude": "Claude", "grok": "Grok"}
_CLAUDE_CACHE = {}  # sanitized observations only; no tokens, no disk writes
_GROK_CACHE = {}
_CLAUDE_RENEWALS = {}  # config -> last request to the client, bounded attempts
STALE_CLAUDE = "Token de acesso vencido; use o Claude Code para renová-lo e atualizar a cota"
DAY = 86400


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("documento acima do orçamento")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("objeto esperado")
    return value


def timestamp(value):
    try:
        if isinstance(value, str):
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value) if value > 0 else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def unknown(provider, reason="Ainda não consultado", label=None):
    return dict(provider=provider, label=label or NAMES[provider], windows=[],
                remaining=None, observed_at=None, reason=reason, plan=None,
                paid_until=None, access="não verificado", renewal="não verificada")


def quota_window(name, used, reset, now, minutes=None):
    if (isinstance(used, bool) or not isinstance(used, (int, float))
            or not math.isfinite(used) or not 0 <= used <= 100):
        return None
    reset = timestamp(reset)
    known_duration = (isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
                      and math.isfinite(minutes) and minutes > 0)
    if known_duration:
        name = 'Semana' if minutes == 10080 else f'Sessão ({minutes / 60:g} h)' if minutes < 1440 else f'Janela ({minutes / 1440:g} dias)'
    window = dict(name=name, used=round(used), remaining=round(100 - used), resets_at=reset,
                  valid=reset is not None and reset > now)
    if known_duration:
        window['duration_minutes'] = minutes
    return window


def effective(item, now=None):
    """Re-evaluate freshness at display time, even without a collector response."""
    now = time.time() if now is None else now
    seen = item.get("observed_at")
    windows = item.get("windows", [])
    if (not seen or not 0 <= now - seen <= MAX_AGE or not windows
            or any(not w.get("valid") or not w.get("resets_at") or w["resets_at"] <= now
                   for w in windows)):
        return None
    return min(w["remaining"] for w in windows)


def band(remaining):
    return "unknown" if remaining is None else "green" if remaining > 60 else "yellow" if remaining > 20 else "red"


def session_reset_at(item, now=None):
    """Return a confirmed five-hour reset only when it clears every exhausted window."""
    now = time.time() if now is None else now
    if effective(item, now) != 0:
        return None
    exhausted = [window for window in item['windows'] if window['remaining'] == 0]
    for window in exhausted:
        duration = window.get('duration_minutes')
        if duration != 300 and not (duration is None and window.get('name') == 'Sessão (5 h)'):
            return None
    return max(window['resets_at'] for window in exhausted) if exhausted else None


def available_resets(item, now=None):
    """Confirmed redeemable tickets, independent of the quota window's reset.

    None means unknown or outdated, including after the first known expiry.
    Do not decrement a provider's count locally or assume a new allowance.
    """
    now = time.time() if now is None else now
    credits = item.get('reset_credits')
    if not isinstance(credits, dict): return None
    count = credits.get('available')
    seen = timestamp(credits.get('observed_at'))
    expiry = credits.get('expires_at')
    if (type(count) is not int or count < 0 or seen is None
            or not 0 <= now - seen <= MAX_AGE):
        return None
    if expiry is not None:
        expiry = timestamp(expiry)
        if expiry is None or expiry <= now: return None
    return count


def web_instances(item, now=None):
    """Fresh count of native Codex clients using a WebGPT account, not launchers."""
    now = time.time() if now is None else now
    count = item.get('web_instances')
    seen = timestamp(item.get('web_instances_at'))
    if type(count) is not int or count < 0 or seen is None or not 0 <= now - seen <= 120:
        return None
    return count


def _rollouts(home):
    """Bound both directory enumeration and bytes read, not just result count."""
    import itertools
    paths = [home / "sessions"]
    for _ in range(3):
        following = []
        for path in paths:
            try:
                with os.scandir(path) as entries:
                    names = list(itertools.islice(entries, 129))
                if len(names) > 128:
                    raise ValueError("inventário de sessões excede orçamento")
                following.extend(Path(e.path) for e in names if e.is_dir(follow_symlinks=False))
            except FileNotFoundError:
                continue
        paths = sorted(following, reverse=True)[:32]
    files = []
    for path in paths:
        with os.scandir(path) as entries:
            names = list(itertools.islice(entries, 257))
        if len(names) > 256:
            raise ValueError("inventário de rollouts excede orçamento")
        files.extend(Path(e.path) for e in names if e.name.startswith("rollout-")
                     and e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:40]


def _tail(path):
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - MAX_TAIL))
        if size > MAX_TAIL:
            stream.readline()  # discard the partial first record
        raw = stream.read(MAX_TAIL)
    # A torn final record is not a completed provider observation.
    return raw[:raw.rfind(b"\n") + 1].splitlines()


def _claims(auth):
    token = auth.get("tokens", {}).get("id_token")
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    try:
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        value = claims.get("https://api.openai.com/auth", {})
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def token_claims(token):
    """Untrusted local metadata, never proof of remote acceptance."""
    try:
        part = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, AttributeError, IndexError):
        return {}


def reset_credits(payload, now):
    count = payload.get('available_count', payload.get('availableCount'))
    if type(count) is not int or count < 0: raise ValueError('contagem de tickets inválida')
    details = payload.get('credits')
    if details is not None and (not isinstance(details, list) or len(details) > 128):
        raise ValueError('detalhes de tickets inválidos')
    expiry = []
    for credit in details or []:
        if not isinstance(credit, dict): raise ValueError('ticket inválido')
        if credit.get('status') != 'available': continue
        at = timestamp(credit.get('expires_at', credit.get('expiresAt')))
        # Keep an expired available entry as a freshness boundary too. A stale
        # server count must not look redeemable merely because we filtered it.
        if at: expiry.append(at)
    return dict(available=count, expires_at=min(expiry) if expiry else None, observed_at=now)


def codex_remote(home, result, now, fetch):
    """Read the same first-party GETs as Codex, never redeem or refresh auth."""
    auth_path = home / 'auth.json'
    auth = read_json(auth_path)
    tokens = auth.get('tokens') or {}
    token = tokens.get('access_token')
    expiry = timestamp(token_claims(token).get('exp'))
    if not isinstance(token, str) or not expiry or expiry <= now:
        return result
    headers = {'Authorization': 'Bearer ' + token, 'User-Agent': 'Folego/0.2'}
    account_id = tokens.get('account_id')
    if isinstance(account_id, str): headers['ChatGPT-Account-ID'] = account_id
    payload = fetch('https://chatgpt.com/backend-api/wham/usage', headers)
    if payload.get('account_id') and payload['account_id'] != account_id:
        return unknown('codex', 'Conta da resposta difere da conta selecionada', result['label'])
    windows = []
    limits = payload.get('rate_limit')
    if isinstance(limits, dict):
        for key, name in (('primary_window', 'Sessão'), ('secondary_window', 'Semana')):
            data = limits.get(key)
            if data is None: continue
            minutes = data.get('limit_window_seconds')
            minutes = minutes / 60 if type(minutes) in (int, float) else None
            window = quota_window(name, data.get('used_percent'), data.get('reset_at'), now, minutes)
            if not window: raise ValueError('janela remota inválida')
            windows.append(window)
    result.update(windows=windows, observed_at=now, plan=payload.get('plan_type') or result.get('plan'),
                  access='aceito pelo provedor nesta observação', source='consulta ao Codex', reason='')
    result['remaining'] = effective(result, now)
    if result['remaining'] is None: result['reason'] = 'Provedor não retornou uma janela percentual atual'
    summary = payload.get('rate_limit_reset_credits')
    if isinstance(summary, dict): result['reset_credits'] = reset_credits(summary, now)
    try:
        details = fetch('https://chatgpt.com/backend-api/wham/rate-limit-reset-credits', headers)
        result['reset_credits'] = reset_credits(details, now)
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # a failed optional detail read never becomes zero available
    credits = payload.get('credits')
    if isinstance(credits, dict):
        balance = credits.get('balance')
        if isinstance(balance, (str, int, float)) and not isinstance(balance, bool):
            try:
                if math.isfinite(float(balance)) and float(balance) >= 0:
                    result['extra_credits'] = str(balance)[:32]
            except ValueError: pass
    if read_json(auth_path) != auth:
        return unknown('codex', 'Conta alterada durante a consulta', result['label'])
    return result


def codex(home, now, *, provider="codex", label=None, fetch=None):
    result = unknown(provider, "Sem observação recente da conta", label)
    home = Path(home)
    if provider == 'web':
        return web_limits(home, result, now)
    auth = None
    try:
        auth = read_json(home / "auth.json")
        claims = _claims(auth)
        result.update(plan=claims.get("chatgpt_plan_type"),
                      paid_until=timestamp(claims.get("chatgpt_subscription_active_until")))
        tokens = auth.get("tokens") or {}
        if isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"]:
            result["renewal"] = "token presente; validade remota não verificada"
        # JWT claims are metadata, not proof that a server accepts a credential.
        result["access"] = "metadados locais; aceitação remota não verificada"
        auth_changed = (home / "auth.json").stat().st_mtime
    except FileNotFoundError:
        auth_changed = 0
    if fetch is not None and auth is not None:
        try:
            remote = codex_remote(home, dict(result), now, fetch)
            if remote.get('observed_at') or remote.get('reason', '').startswith('Conta '): return remote
        except (OSError, ValueError, TypeError, AttributeError):
            result['source'] = 'último registro local; consulta atual indisponível'
    best = None
    for path in _rollouts(home):
        for line in _tail(path):
            if b'"rate_limits"' not in line:
                continue
            try:
                record = json.loads(line)
                limits = record.get("payload", {}).get("rate_limits")
                seen = timestamp(record.get("timestamp"))
                if (isinstance(limits, dict) and limits.get("limit_id") == "codex"
                        and seen and (best is None or seen > best[0])):
                    best = seen, limits
            except (ValueError, AttributeError):
                continue
    if best:
        seen, limits = best
        if seen < auth_changed:
            result["reason"] = "Conta/credencial alterada após a observação; use a conta para atualizar"
            return result
        result["observed_at"] = seen
        result["plan"] = result["plan"] or limits.get("plan_type")
        for key, name in (("primary", "Sessão"), ("secondary", "Semana")):
            data = limits.get(key)
            if isinstance(data, dict):
                value = quota_window(name, data.get("used_percent"), data.get("resets_at"), now, data.get('window_minutes'))
                if value:
                    result["windows"].append(value)
                else:
                    result["reason"] = "Janela de cota inválida"
                    result["windows"] = []
                    return result
        result["remaining"] = effective(result, now)
        result["reason"] = "" if result["remaining"] is not None else "Observação vencida/incompleta; aguardando o provedor"
        summary = limits.get('rate_limit_reset_credits')
        if isinstance(summary, dict): result['reset_credits'] = reset_credits(summary, seen)
    if auth is not None and read_json(home / "auth.json") != auth:
        return unknown(provider, "Conta alterada durante a leitura", label)
    return result


def stamp(seconds):
    return dt.datetime.fromtimestamp(seconds).astimezone().strftime('%d/%m/%Y %H:%M')


def web_limits(home, result, now):
    """Read only local launcher submissions; server quota and reset stay unknown."""
    from .web_gpt import local_limits
    result.update(local_limits(Path(home).parent / 'launcher-data/limits.json', now))
    return result


def http_json(url, headers):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("redirecionamento recusado")
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
        raw = response.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("resposta acima do orçamento")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("resposta inválida")
    return value


def claude_account_context(config):
    """Native account/organization metadata; no PhaseZero state is consulted."""
    path = Path(config).with_suffix('.json')
    try:
        metadata = read_json(path)
    except FileNotFoundError:
        return dict(present=False)
    account = metadata.get('oauthAccount')
    if account is not None and not isinstance(account, dict):
        raise ValueError('metadados da conta Claude desconhecidos')
    return dict(present=True, account=account)


def claude(config, now, fetch, *, cache=None):
    result = unknown("claude", "Login do Claude não encontrado")
    credentials = read_json(Path(config) / ".credentials.json")
    oauth = credentials.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not isinstance(oauth.get("accessToken"), str):
        return result
    expiry = timestamp(oauth.get("expiresAt", 0) / 1000) if isinstance(oauth.get("expiresAt"), (int, float)) else None
    if not expiry or expiry <= now:
        renewal = oauth.get("refreshTokenExpiresAt")
        renewal = timestamp(renewal / 1000) if isinstance(renewal, (int, float)) else None
        if expiry and renewal and renewal > now and isinstance(oauth.get("refreshToken"), str):
            # The session is alive; only the client may renew it (never Fôlego).
            result.update(plan=oauth.get("subscriptionType"),
                          renewal="renovação local até " + dt.datetime.fromtimestamp(renewal).astimezone().strftime("%d/%m %H:%M"),
                          reason=STALE_CLAUDE)
        else:
            result["reason"] = "Login expirado/sem validade comprovada; renove no Claude"
        return result
    context = claude_account_context(config)
    def unchanged():
        try:
            return (read_json(Path(config) / '.credentials.json') == credentials
                    and claude_account_context(config) == context)
        except (OSError, ValueError):
            return False
    cache = {} if cache is None else cache
    material = json.dumps([credentials, context], sort_keys=True).encode()
    credential_key = (str(Path(config).resolve()), hashlib.sha256(material).hexdigest())
    auth_scope = hashlib.sha256(oauth['accessToken'].encode()).hexdigest()
    retry_at = 0
    for old_key in list(cache):
        if old_key[0] == credential_key[0] and old_key != credential_key:
            old = cache.pop(old_key)
            if old.get('auth_scope') == auth_scope:
                retry_at = max(retry_at, old.get('retry_at', 0))
    entry = cache.get(credential_key, dict(auth_scope=auth_scope, retry_at=retry_at))
    if retry_at > now:
        cache[credential_key] = entry
    previous = entry.get('item')
    age = now - previous['observed_at'] if previous else float('inf')
    limited = entry.get('retry_at', 0) > now
    if (previous and 0 <= age < 300) or limited:
        if previous and 0 <= age <= MAX_AGE:
            if not unchanged():
                return unknown('claude', 'Conta alterada durante a consulta')
            previous = copy.deepcopy(previous)
            previous['remaining'] = effective(previous, now)
            if limited: previous['reason'] = 'Consulta limitada pelo Claude; última observação válida, aguardando nova tentativa'
            return previous
        result['reason'] = 'Claude limitou as consultas (HTTP 429); nova tentativa após ' + dt.datetime.fromtimestamp(entry['retry_at']).astimezone().strftime('%H:%M')
        return result
    # Never refresh, transfer or persist credentials. Only this first-party URL.
    headers = {"Authorization": "Bearer " + oauth["accessToken"],
               "anthropic-beta": "oauth-2025-04-20", "User-Agent": "Folego/0.2"}
    try:
        payload = fetch("https://api.anthropic.com/api/oauth/usage", headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 429: raise
        raw_delay = exc.headers.get('Retry-After', '180') if exc.headers else '180'
        try: delay = float(raw_delay)
        except (ValueError, TypeError):
            try: delay = parsedate_to_datetime(raw_delay).timestamp() - now
            except (ValueError, TypeError, OverflowError): delay = 180
        delay = max(60, delay) if math.isfinite(delay) else 180
        entry['retry_at'] = now + delay
        if len(cache) >= 16 and credential_key not in cache: cache.pop(next(iter(cache)))
        cache[credential_key] = entry
        if not unchanged():
            return unknown('claude', 'Conta alterada durante a consulta')
        if previous and 0 <= age <= MAX_AGE:
            previous = copy.deepcopy(previous)
            previous['remaining'] = effective(previous, now)
            previous['reason'] = 'Consulta limitada pelo Claude; última observação válida, aguardando nova tentativa'
            return previous
        result['reason'] = 'Claude limitou as consultas (HTTP 429); nova tentativa após ' + dt.datetime.fromtimestamp(now + delay).astimezone().strftime('%H:%M')
        return result
    # A credential/account rotation during HTTP invalidates that response.
    if not unchanged():
        result["reason"] = "Conta alterada durante a consulta; aguardando nova observação"
        return result
    for key, name in (("five_hour", "Sessão"), ("seven_day", "Semana"),
                      ("seven_day_opus", "Semana Opus"), ("seven_day_sonnet", "Semana Sonnet")):
        data = payload.get(key)
        if isinstance(data, dict):
            value = quota_window(name, data.get("utilization"), data.get("resets_at"), now,
                                 300 if key == "five_hour" else None)
            if value is None:
                result["reason"] = "Resposta parcial: janela inválida"
                return result
            result["windows"].append(value)
    result.update(observed_at=now, plan=oauth.get("subscriptionType"),
                  access="aceito pelo provedor nesta observação", reason="")
    result["renewal"] = "token presente; validade futura não verificada" if oauth.get("refreshToken") else "não informada"
    extra = payload.get('extra_usage')
    if isinstance(extra, dict) and type(extra.get('is_enabled')) is bool:
        result['extra_usage'] = dict(enabled=extra['is_enabled'])
        for key in ('monthly_limit', 'used_credits', 'utilization'):
            value = extra.get(key)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                result['extra_usage'][key] = value
    if not 0 <= now - entry.get('profile_at', 0) < 21600:
        entry.update(profile_at=now, profile_day=None)
        try:
            profile = fetch('https://api.anthropic.com/api/oauth/profile', headers)
            organization = profile.get('organization') or {}
            created = timestamp(organization.get('subscription_created_at'))
            if created and created <= now and organization.get('subscription_status') == 'active':
                entry['profile_day'] = dt.datetime.fromtimestamp(created, dt.timezone.utc).day
        except (OSError, ValueError, TypeError, AttributeError):
            entry['profile_at'] = 0
    if entry.get('profile_day'):
        result.update(billing_day=entry['profile_day'], billing_source='estimativa pelo início da assinatura; confirme no provedor')
    if not unchanged():
        return unknown('claude', 'Conta alterada durante a consulta')
    result["remaining"] = effective(result, now)
    if len(cache) >= 16 and credential_key not in cache: cache.pop(next(iter(cache)))
    cache[credential_key] = dict(entry, item=copy.deepcopy(result), retry_at=0)
    return result


def claude_renew(config, *, timeout=60):
    """Let Claude's own CLI renew its stored session (`claude doctor`, no inference)."""
    executable = shutil.which('claude')
    if not executable:
        raise FileNotFoundError('cliente Claude não encontrado')
    env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_CODE_')}
    if Path(config).resolve() != (Path(env.get('HOME') or Path.home()) / '.claude').resolve():
        env['CLAUDE_CONFIG_DIR'] = str(config)
    with tempfile.TemporaryDirectory(prefix='folego-claude-') as cwd:
        subprocess.run([executable, 'doctor'], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)


def claude_with_renewal(config, now, fetch, renew, *, cache=None, attempts=None):
    item = claude(config, now, fetch, cache=cache)
    attempts = _CLAUDE_RENEWALS if attempts is None else attempts
    key = str(Path(config).resolve())
    if item['reason'] != STALE_CLAUDE or renew is None or 0 <= now - attempts.get(key, -1e18) < 600:
        return item
    attempts[key] = now  # one request per 10 min; failure keeps the honest stale state
    renew(config)
    return claude(config, now, fetch, cache=cache)


def grok_billing(home, *, timeout=20):
    """Ask Grok's own CLI over ACP stdio; no prompt, token read or refresh here."""
    executable = shutil.which('grok')
    if not executable:
        raise FileNotFoundError('cliente Grok não encontrado')
    env = dict(os.environ, GROK_HOME=str(home))
    requests = [dict(jsonrpc='2.0', id=1, method='initialize', params=dict(protocolVersion=1, clientCapabilities={})),
                dict(jsonrpc='2.0', id=2, method='_x.ai/billing', params={})]
    # An empty private cwd keeps the agent from indexing a real project.
    with tempfile.TemporaryDirectory(prefix='folego-grok-') as cwd:
        process = subprocess.Popen([executable, 'agent', '--no-leader', 'stdio'], cwd=cwd, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return _acp_result(process, requests, timeout)


def _acp_result(process, requests, timeout):
    try:
        process.stdin.write(b''.join(json.dumps(r).encode() + b'\n' for r in requests))
        process.stdin.flush()
        selector, buffer, deadline = selectors.DefaultSelector(), b'', time.monotonic() + timeout
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline and len(buffer) <= MAX_FILE:
            if not selector.select(max(0, deadline - time.monotonic())): break
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk: break
            buffer += chunk
            *lines, buffer = buffer.split(b'\n')
            for line in lines:
                try: message = json.loads(line)
                except ValueError: continue
                if isinstance(message, dict) and message.get('id') == 2:
                    if not isinstance(message.get('result'), dict):
                        raise ValueError('Grok recusou a consulta de uso')
                    return message['result']
        raise TimeoutError('Grok não respondeu à consulta de uso')
    finally:
        process.stdin.close()  # the CLI exits on EOF; only our own child is followed
        try: process.wait(10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(5)


def grok(home, now, query, *, cache=None):
    result = unknown('grok', 'Login do Grok não encontrado')
    auth_path = Path(home) / 'auth.json'
    if not auth_path.is_file():
        return result
    material = auth_path.read_bytes()[:MAX_FILE]
    key = (str(Path(home).resolve()), hashlib.sha256(material).hexdigest())
    cache = {} if cache is None else cache
    previous = cache.get(key)
    if previous and 0 <= now - previous['observed_at'] < 300:
        previous = copy.deepcopy(previous)
        previous['remaining'] = effective(previous, now)
        return previous
    payload = query(home)
    if auth_path.read_bytes()[:MAX_FILE] != material:
        return unknown('grok', 'Conta alterada durante a consulta')
    config = payload.get('config')
    period = config.get('currentPeriod') if isinstance(config, dict) else None
    if not isinstance(period, dict):
        result['reason'] = 'Grok não retornou um período de uso'
        return result
    name = {'USAGE_PERIOD_TYPE_WEEKLY': 'Semana', 'USAGE_PERIOD_TYPE_MONTHLY': 'Mês',
            'USAGE_PERIOD_TYPE_DAILY': 'Dia'}.get(period.get('type'), 'Período')
    window = quota_window(name, config.get('creditUsagePercent'), timestamp(period.get('end')), now)
    if window is None:
        result['reason'] = 'Resposta parcial: janela inválida'
        return result
    tier = payload.get('subscription_tier')
    result.update(windows=[window], observed_at=now, plan=tier if isinstance(tier, str) else None,
                  access='aceito pelo provedor nesta observação', source='consulta ao cliente Grok', reason='')
    result['remaining'] = effective(result, now)
    if len(cache) >= 16 and key not in cache: cache.pop(next(iter(cache)))
    cache[key] = copy.deepcopy(result)
    return result


def collect(env=None, *, now=None, fetch=http_json, discover=None, grok_query=None, claude_renewal=None):
    from .ai_accounts import inventory, process_account, settings
    native = env is None
    env = dict(os.environ if native else env)
    now = time.time() if now is None else now
    try:
        configuration = settings(env)
        if discover is None and native:
            from .agent_deliveries import running_agents
            discover = running_agents
        processes_known = discover is not None
        processes = list(discover()) if discover is not None else []
        web_counts = {}
        seen_processes = set()
        for process in processes:
            provider, path = process_account(process, env)
            identity = process.get('identity')
            if provider == 'web' and identity is not None and identity not in seen_processes:
                seen_processes.add(identity)
                web_counts[path] = web_counts.get(path, 0) + 1
        from .web_gpt import installed_launchers
        accounts = inventory(env, discover=lambda: processes,
                             discover_web=installed_launchers if native else lambda _env: [])
    except (OSError, ValueError, TypeError, KeyError):
        return [unknown(p, 'Inventário de contas não confirmado; confira a configuração') for p in NAMES]
    result = []
    for account in accounts:
        provider = account['provider']
        try:
            if provider == 'codex':
                item = codex(account['path'], now, provider=provider, fetch=fetch)
            elif provider == 'web':
                from .web_gpt import observe
                root = Path(account['path']).parent
                item = unknown('web')
                item.update(observe(account.get('web_core_home', root / 'core-home'),
                                    account.get('web_launcher_data', root / 'launcher-data'),
                                    now=now, live=native and account['default']))
            elif provider == 'claude':
                renew = claude_renewal or (claude_renew if native else None)
                item = claude_with_renewal(account['path'], now, fetch, renew, cache=_CLAUDE_CACHE)
            elif grok_query is None and not native:
                item = unknown(provider, 'Percentual não disponibilizado nesta fonte')
            else:
                item = grok(account['path'], now, grok_query or grok_billing, cache=_GROK_CACHE)
            if provider == 'grok':
                item['paid_until'] = timestamp(configuration.get('grok_paid_until')) if account['default'] else None
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            item = unknown(provider, 'Fonte indisponível; confira o login no cliente')
        if provider == 'web' and processes_known:
            item.update(web_instances=web_counts.get(account['path'], 0), web_instances_at=now)
        item.update(account_id=account['account_id'], label=account['label'], default=account['default'])
        if account.get('inventory_warning'):
            item['reason'] = (item.get('reason', '') + '; ' + account['inventory_warning']).strip('; ')
        billing = configuration.get('billing_accounts', {})
        reference = billing.get(account['account_id'], {}) if isinstance(billing, dict) else {}
        if isinstance(billing, dict) and account['account_id'] not in billing and account['default']:
            legacy = configuration.get('billing', {})
            reference = legacy.get(provider, {}) if isinstance(legacy, dict) else {}
        day = reference.get('monthly_day') if isinstance(reference, dict) else None
        if type(day) is int and 1 <= day <= 31:
            item.update(billing_day=day, billing_source='referência pessoal; confirme no provedor')
        result.append(item)
    return result


def set_billing_day(provider, day, account=None, *, env=None):
    if provider not in NAMES or type(day) is not int or not 0 <= day <= 31:
        raise ValueError('dia de renovação inválido')
    env = dict(os.environ if env is None else env)
    home = Path(env.get('HOME') or Path.home())
    path = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'folego/ai-sessions.json'
    value = read_json(path) if path.exists() else dict(schema=1)
    if value.get('schema') != 1 or not isinstance(value.get('billing', {}), dict):
        raise ValueError('Configuração desconhecida; arquivo preservado')
    if account is not None:
        from .ai_accounts import inventory
        if not any(a['account_id'] == account and a['provider'] == provider for a in inventory(env)):
            raise ValueError('Conta não identificada; referência preservada')
    field, key = ('billing_accounts', account) if account else ('billing', provider)
    if not isinstance(value.get(field, {}), dict):
        raise ValueError('Referências de contas desconhecidas; arquivo preservado')
    billing = value.setdefault(field, {})
    reference = billing.get(key, {})
    if not isinstance(reference, dict): raise ValueError('Referência mensal desconhecida; arquivo preservado')
    reference = dict(reference)
    if day: reference['monthly_day'] = day
    else: reference.pop('monthly_day', None)
    if reference or account: billing[key] = reference
    else: billing.pop(key, None)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Configuração simbólica; arquivo preservado')
    from ..safely.atomicfile import write_atomic
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode(), mode=0o600)
    return 'Referência mensal salva' if day else 'Referência mensal removida'


def next_monthly(day, now):
    current = dt.datetime.fromtimestamp(now).astimezone().date()
    year, month = current.year, current.month
    date = dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))
    if date <= current:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        date = dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))
    return date.strftime('%d/%m/%Y')


def describe(item, now=None):
    now = time.time() if now is None else now
    if item.get('provider') == 'web':
        lines = [item.get('label', 'Codex Web')]
        instances = web_instances(item, now)
        lines.append('Instâncias Codex Web: ' + ('não verificadas' if instances is None else str(instances)))
        for title, key in (('Serviço local', 'web_service'), ('Runtime local do túnel', 'web_tunnel')):
            observation = item.get(key) or {}
            state = observation.get('state', 'unknown')
            lines.append(title + ': ' + {'ready': 'pronto', 'unavailable': 'indisponível',
                                         'not_required': 'não exigido', 'unknown': 'desconhecido'}.get(state, 'desconhecido'))
            if observation.get('checked_at'):
                lines.append(title + ' verificado: ' + stamp(observation['checked_at']))
        lines.extend(['Resposta ChatGPT Web: não comprovada sem envio',
                      'Limite, saldo e reposição da conta: não informados'])
        if item.get('web_recovery'):
            lines.append('Recuperação Web: ' + item['web_recovery']['detail'])
        usage = item.get('local_usage')
        if usage:
            lines.append('Envios registrados neste launcher em 7 dias: '
                         + str(sum(usage['counts'].values())) + ' (parcial)')
        if item.get('limits_checked_at'):
            lines.append('Plano verificado localmente: ' + stamp(item['limits_checked_at']))
        if item.get('reason'):
            lines.append(item['reason'])
        return '\n'.join(lines)
    left = effective(item, now)
    lines = [item['label'], 'Percentual não confirmado' if left is None else f'{left}% disponível na janela mais restrita']
    def date(value):
        return dt.datetime.fromtimestamp(value).astimezone().strftime('%d/%m/%Y %H:%M')
    def countdown(value):
        seconds = max(0, int(value - now))
        days, hours = divmod(seconds // 3600, 24)
        minutes = seconds // 60 % 60
        return f'{days}d {hours}h' if days else f'{hours}h {minutes:02}min'
    windows = item.get('windows', [])
    for window in windows:
        stale = ' · observação vencida' if left is None else ''
        reset = window.get('resets_at')
        renewal = (' · repõe ' + date(reset) + (' (em ' + countdown(reset) + ')' if reset > now else ' · aguardando atualização')) if reset else ' · reposição não informada'
        lines.append(f"{window['name']}: {window['used']}% usado / {window['remaining']}% livre" + renewal + stale)
    if not windows:
        lines.extend(['Uso da sessão: não informado nesta fonte', 'Reposição da sessão: não informada nesta fonte'])
    reset = item.get('reset_credits') or {}
    expiry = reset.get('expires_at')
    available = available_resets(item, now)
    if available is not None:
        text = str(available) + ' disponíveis'
        if available: text += ' · validade: ' + (date(expiry) if expiry else 'não informada')
        lines.append('Tickets de reposição: ' + text + ' · resgate na aplicação')
    else:
        lines.append('Tickets de reposição: ' + ('consulta vencida; aguardando atualização' if reset else 'não informados nesta fonte'))
    balance = item.get('extra_credits')
    lines.append('Créditos extras: ' + (str(balance) + ' (saldo informado pelo provedor)' if balance is not None else 'não informados nesta fonte'))
    extra = item.get('extra_usage')
    if extra:
        text = 'habilitado' if extra['enabled'] else 'desabilitado'
        if 'utilization' in extra: text += f" · {extra['utilization']:g}% do limite mensal"
        if 'used_credits' in extra: text += f" · consumo {extra['used_credits']:g}"
        if 'monthly_limit' in extra: text += f" / teto {extra['monthly_limit']:g} (unidades do provedor)"
        lines.append('Uso extra: ' + text)
    if item.get('plan'): lines.append('Plano: ' + str(item['plan']))
    day = item.get('billing_day')
    if day:
        lines.append(f'Renovação mensal: dia {day} · próxima referência ' + next_monthly(day, now))
        lines.append(item.get('billing_source', 'referência não verificada'))
    else:
        lines.append('Renovação mensal: data não informada; defina a referência nas opções')
    if item.get('paid_until'):
        lines.append('Assinatura até: ' + date(item['paid_until']) + ' (metadado; confira no provedor)')
    if item.get('source'): lines.append('Fonte: ' + item['source'])
    if item.get('observed_at'): lines.append('Consultado: ' + date(item['observed_at']))
    if item.get('reason'): lines.append(item['reason'])
    return '\n'.join(lines)
