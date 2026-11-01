"""Read-only AI quota observations. No Qt, account manager or token renewal.

Provider data is deliberately asymmetric: Codex reports rate limits, Claude
has a first-party usage endpoint, Web/Grok do not supply a quota here. A reset
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
from pathlib import Path
import time
import urllib.request
import urllib.error
import tomllib

MAX_AGE = 900
MAX_FILE = 512 * 1024
MAX_TAIL = 64 * 1024
NAMES = {"codex": "Codex", "web": "Codex Web", "claude": "Claude", "grok": "Grok"}
_CLAUDE_CACHE = {}  # sanitized observations only; no tokens, no disk writes


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
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes > 0:
        name = 'Semana' if minutes == 10080 else f'Sessão ({minutes / 60:g} h)' if minutes < 1440 else f'Janela ({minutes / 1440:g} dias)'
    return dict(name=name, used=round(used), remaining=round(100 - used), resets_at=reset,
                valid=reset is not None and reset > now)


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
        if at and at > now: expiry.append(at)
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
    if provider == "web":
        result["reason"] = "Codex Web não fornece percentual de cota nesta fonte"
        return result
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


def claude(config, now, fetch, *, cache=None):
    result = unknown("claude", "Login do Claude não encontrado")
    credentials = read_json(Path(config) / ".credentials.json")
    oauth = credentials.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not isinstance(oauth.get("accessToken"), str):
        return result
    expiry = timestamp(oauth.get("expiresAt", 0) / 1000) if isinstance(oauth.get("expiresAt"), (int, float)) else None
    if not expiry or expiry <= now:
        result["reason"] = "Login expirado/sem validade comprovada; renove no Claude"
        return result
    cache = {} if cache is None else cache
    credential_key = (str(Path(config).resolve()), hashlib.sha256(json.dumps(credentials, sort_keys=True).encode()).hexdigest())
    entry = cache.get(credential_key, {})
    previous = entry.get('item')
    age = now - previous['observed_at'] if previous else float('inf')
    limited = entry.get('retry_at', 0) > now
    if (previous and 0 <= age < 300) or limited:
        if previous and 0 <= age <= MAX_AGE:
            if read_json(Path(config) / '.credentials.json') != credentials:
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
        if read_json(Path(config) / '.credentials.json') != credentials:
            return unknown('claude', 'Conta alterada durante a consulta')
        entry['retry_at'] = now + delay
        if len(cache) >= 16 and credential_key not in cache: cache.pop(next(iter(cache)))
        cache[credential_key] = entry
        if previous and 0 <= age <= MAX_AGE:
            previous = copy.deepcopy(previous)
            previous['remaining'] = effective(previous, now)
            previous['reason'] = 'Consulta limitada pelo Claude; última observação válida, aguardando nova tentativa'
            return previous
        result['reason'] = 'Claude limitou as consultas (HTTP 429); nova tentativa após ' + dt.datetime.fromtimestamp(now + delay).astimezone().strftime('%H:%M')
        return result
    # A credential/account rotation during HTTP invalidates that response.
    if read_json(Path(config) / ".credentials.json") != credentials:
        result["reason"] = "Conta alterada durante a consulta; aguardando nova observação"
        return result
    for key, name in (("five_hour", "Sessão"), ("seven_day", "Semana"),
                      ("seven_day_opus", "Semana Opus"), ("seven_day_sonnet", "Semana Sonnet")):
        data = payload.get(key)
        if isinstance(data, dict):
            value = quota_window(name, data.get("utilization"), data.get("resets_at"), now)
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
    if read_json(Path(config) / '.credentials.json') != credentials:
        return unknown('claude', 'Conta alterada durante a consulta')
    result["remaining"] = effective(result, now)
    if len(cache) >= 16 and credential_key not in cache: cache.pop(next(iter(cache)))
    cache[credential_key] = dict(entry, item=copy.deepcopy(result), retry_at=0)
    return result


def active_accounts(accounts, discover, home):
    """Native client paths, independent of the program which launched them."""
    for process in discover():
        if process['provider'] != 'codex': continue
        root = process['roots'].get('CODEX_HOME')
        if not root: continue
        # A private HOME (QA or a portable installation) must not inspect the
        # physical user's accounts discovered in another home.
        if not Path(root).is_absolute() or not Path(root).resolve().is_relative_to(home.resolve()): continue
        provider = 'codex'
        try:
            with (Path(root) / 'config.toml').open('rb') as stream:
                config = tomllib.loads(stream.read(MAX_TAIL).decode())
            if str(config.get('model', '')).startswith('chatgpt-web/'): provider = 'web'
        except (OSError, ValueError): pass
        accounts.append(dict(provider=provider, path=root))
    unique = {}
    for account in accounts:
        if not isinstance(account, dict) or account.get('provider') not in ('codex', 'web'):
            raise ValueError('conta inválida')
        path = Path(account['path']).expanduser()
        if not path.is_absolute(): raise ValueError('caminho inválido')
        unique[(account['provider'], str(path.resolve()))] = dict(account, path=str(path))
    if len(unique) > 20: raise ValueError('contas acima do orçamento')
    return list(unique.values())


def collect(env=None, *, now=None, fetch=http_json, discover=None):
    native = env is None
    env = dict(os.environ if env is None else env)
    now = time.time() if now is None else now
    home = Path(env.get("HOME") or Path.home())
    config_root = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    config_path = config_root / "folego/ai-sessions.json"
    settings = {}
    if config_path.exists():
        try:
            settings = read_json(config_path)
            if settings.get("schema") != 1:
                raise ValueError("schema desconhecido")
        except (OSError, ValueError):
            return [unknown(p, "Configuração de IAs ilegível/schema desconhecido") for p in NAMES]
    roots = settings.get("accounts", [])
    if not isinstance(roots, list) or len(roots) > 16:
        return [unknown(p, "Inventário de contas inválido/acima do orçamento") for p in NAMES]
    accounts = [dict(provider="codex", path=env.get("CODEX_HOME") or str(home / ".codex"))]
    web_default = home / ".local/share/codex-web-gpt/codex-home"
    accounts.append(dict(provider="web", path=str(web_default)))
    accounts.extend(roots)
    try:
        if discover is None:
            from .agent_deliveries import running_agents
            discover = running_agents if native else lambda: []
        accounts = active_accounts(accounts, discover, home)
    except (OSError, ValueError, TypeError, KeyError):
        return [unknown(p, 'Inventário de contas inválido/acima do orçamento') for p in NAMES]
    result = []
    for account in accounts:
        if not isinstance(account, dict) or account.get("provider") not in ("codex", "web"):
            return [unknown(p, "Configuração de conta inválida") for p in NAMES]
        provider = account["provider"]
        try:
            path = Path(account["path"]).expanduser()
            if not path.is_absolute():
                raise ValueError("caminho não absoluto")
            item = codex(path, now, provider=provider, label=account.get("label"), fetch=fetch)
            result.append(item)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            result.append(unknown(provider, "Fonte ausente, ilegível ou fora do orçamento"))
    try:
        result.append(claude(env.get("CLAUDE_CONFIG_DIR") or home / ".claude", now, fetch, cache=_CLAUDE_CACHE))
    except (OSError, ValueError, TypeError, AttributeError):
        result.append(unknown("claude", "Uso indisponível; verifique o login no Claude"))
    grok = unknown("grok", "O provedor não informa o percentual de cota nesta fonte")
    grok["paid_until"] = timestamp(settings.get("grok_paid_until"))
    grok["plan"] = "data informada pelo usuário" if grok["paid_until"] else None
    result.append(grok)
    billing = settings.get('billing', {})
    if not isinstance(billing, dict): billing = {}
    for item in result:
        day = billing.get(item['provider'], {}).get('monthly_day') if isinstance(billing.get(item['provider'], {}), dict) else None
        if type(day) is int and 1 <= day <= 31:
            item.update(billing_day=day, billing_source='data informada pelo usuário; não verificada pelo provedor')
    return result


def set_billing_day(provider, day, *, env=None):
    if provider not in NAMES or type(day) is not int or not 0 <= day <= 31:
        raise ValueError('dia de renovação inválido')
    env = dict(os.environ if env is None else env)
    home = Path(env.get('HOME') or Path.home())
    path = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'folego/ai-sessions.json'
    value = read_json(path) if path.exists() else dict(schema=1)
    if value.get('schema') != 1 or not isinstance(value.get('billing', {}), dict):
        raise ValueError('Configuração desconhecida; arquivo preservado')
    billing = value.setdefault('billing', {})
    reference = billing.get(provider, {})
    if not isinstance(reference, dict): raise ValueError('Referência mensal desconhecida; arquivo preservado')
    reference = dict(reference)
    if day: reference['monthly_day'] = day
    else: reference.pop('monthly_day', None)
    if reference: billing[provider] = reference
    else: billing.pop(provider, None)
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
    seen = reset.get('observed_at', 0)
    expiry = reset.get('expires_at')
    fresh = 0 <= now - seen <= MAX_AGE and (not expiry or expiry > now)
    if reset and fresh:
        text = str(reset['available']) + ' disponíveis'
        if reset['available']: text += ' · validade: ' + (date(expiry) if expiry else 'não informada')
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
